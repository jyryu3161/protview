"""Fixed POSIX launch anchor. Invoked only by the local queue with an inherited control fd."""
from __future__ import annotations

import hashlib
import json
import os
import re
import select
import signal
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

import psutil

# -I deliberately removes the project import path when run as a script. Add
# only the fixed sibling directory in that launch, not during package imports.
if __package__:
    from .process_identity import IdentityUnavailable, capture, matches, supported
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from process_identity import IdentityUnavailable, capture, matches, supported

MAX_CONTROL = 8192
MAX_RESULT = 8192
FIXTURE = Path(__file__).with_name("lifecycle_fixture.py")
OPENMM = Path(__file__).with_name("openmm_worker.py")
FIXTURE_MODES = {"normal", "nonzero", "malformed", "oversize", "wrong_id", "invalid",
                 "sleep", "grandchild", "leader_exit"}


def read_small_json(name: str, limit: int) -> dict:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("invalid control file")
        raw = os.read(fd, limit + 1)
        if len(raw) > limit:
            raise ValueError("oversized control file")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise TypeError("control file must contain an object")
        return value
    finally:
        os.close(fd)


def send(sock: socket.socket, value: dict) -> None:
    raw = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
    if len(raw) > MAX_CONTROL - 1:
        raise ValueError("control message too large")
    sock.sendall(raw + b"\n")


def receive(sock: socket.socket, timeout: float) -> dict | None:
    ready, _, _ = select.select([sock], [], [], timeout)
    if not ready:
        return {}
    data = bytearray()
    while len(data) < MAX_CONTROL:
        part = sock.recv(1)
        if not part:
            return None
        if part == b"\n":
            return json.loads(data)
        data.extend(part)
    raise ValueError("oversized control message")


def members(pgid: int, own: int) -> list[dict]:
    result = []
    for pid in psutil.pids():
        if pid <= 0 or pid == own:
            continue
        try:
            if os.getpgid(pid) != pgid:
                continue
            proc = psutil.Process(pid)
            start = capture(pid)
            if proc.status() == psutil.STATUS_ZOMBIE:
                continue
            uid = proc.uids().real
            session = os.getsid(pid)
            if capture(pid) != start:
                raise IdentityUnavailable("process identity changed during group enumeration")
            if os.getpgid(pid) == pgid:
                result.append({"pid": pid, "start_identity": start, "uid": uid, "session": session})
        except (psutil.NoSuchProcess, ProcessLookupError):
            continue
    return result


def signal_member(entry: dict, pgid: int, sig: int) -> None:
    try:
        if (any(type(entry[key]) is not int or entry[key] <= 0 for key in ("pid", "session")) or
                type(entry["uid"]) is not int or entry["uid"] < 0 or
                not matches(entry["pid"], entry["start_identity"])):
            return
        proc = psutil.Process(entry["pid"])
        if (matches(entry["pid"], entry["start_identity"]) and
                proc.uids().real == entry["uid"] == os.getuid() and
                os.getpgid(entry["pid"]) == pgid and os.getsid(entry["pid"]) == entry["session"] and
                proc.status() != psutil.STATUS_ZOMBIE and matches(entry["pid"], entry["start_identity"])):
            os.kill(entry["pid"], sig)
    except (KeyError, TypeError, psutil.Error, ProcessLookupError, OSError):
        pass


def cleanup(pgid: int, own: int, child: subprocess.Popen | None) -> tuple[bool, list[dict]]:
    try:
        known: dict[int, dict] = {}
        for entry in members(pgid, own):
            known[entry["pid"]] = entry
            signal_member(entry, pgid, signal.SIGTERM)
        end = time.monotonic() + 0.7
        while time.monotonic() < end and members(pgid, own):
            time.sleep(0.02)
        for entry in members(pgid, own):
            known[entry["pid"]] = entry
            signal_member(entry, pgid, signal.SIGKILL)
        if child is not None:
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=1)
        end = time.monotonic() + 1
        while time.monotonic() < end and members(pgid, own):
            time.sleep(0.02)
        return not members(pgid, own), list(known.values())
    except (OSError, psutil.Error, IdentityUnavailable):
        # Enumeration failure never grants blanket group signal authority.
        # The still-owned, unreaped direct Popen child remains safe to stop.
        if child is not None:
            try:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
        return False, list(known.values())


def receipt(identity: dict) -> None:
    path = Path("bootstrap.receipt")
    with Path("bootstrap.tmp").open("x", encoding="utf-8") as stream:
        json.dump(identity, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace("bootstrap.tmp", path)
    directory = os.open(".", os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main(fd: int) -> int:
    sock = socket.socket(fileno=fd)
    input_data = read_small_json("input.json", 4096)
    adapter = input_data.get("adapter")
    expected = ({"nonce", "job_id", "attempt_id", "adapter", "fixture_mode"} if adapter == "internal_lifecycle_fixture" else
                {"nonce", "job_id", "attempt_id", "adapter", "input_sha256"})
    if (set(input_data) != expected or
            not isinstance(input_data["nonce"], str) or not re.fullmatch(r"[0-9a-f]{32}", input_data["nonce"]) or
            adapter not in {"internal_lifecycle_fixture", "openmm_protein_minimize_v1"} or
            (adapter == "internal_lifecycle_fixture" and input_data["fixture_mode"] not in FIXTURE_MODES) or
            (adapter == "openmm_protein_minimize_v1" and not re.fullmatch(r"[0-9a-f]{64}", input_data["input_sha256"])) or
            any(not isinstance(input_data[key], str) or not re.fullmatch(r"[a-z0-9_]{1,100}", input_data[key])
                for key in ("job_id", "attempt_id"))):
        return 2
    nonce = input_data["nonce"]
    own = os.getpid()
    pgid = os.getpgid(own)
    session = os.getsid(own)
    if own != pgid or own != session:
        return 2
    supported()
    identity = {"nonce": nonce, "pid": own, "pgid": pgid, "session": session,
                "start_identity": capture(own), "uid": os.getuid()}
    receipt(identity)
    send(sock, {"kind": "HELLO", **identity,
                "runtime": {"prefix": sys.prefix, "executable": sys.executable,
                            "psutil_version": psutil.__version__,
                            "environment_keys": sorted(os.environ)}})
    command = receive(sock, 3)
    if command is None or command.get("kind") != "GO" or command.get("nonce") != nonce:
        return 0
    worker = FIXTURE if adapter == "internal_lifecycle_fixture" else OPENMM
    child = subprocess.Popen([sys.executable, "-I", str(worker)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             close_fds=True, cwd=Path.cwd(), env={"PATH": "/usr/bin:/bin", "LANG": "C",
                                                                   "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1",
                                                                   "TMPDIR": str(Path.cwd())})
    reason = "completed"
    try:
        send(sock, {"kind": "STARTED", "nonce": nonce,
                    "job_id": input_data["job_id"], "attempt_id": input_data["attempt_id"], "pid": child.pid,
                    "start_identity": capture(child.pid)})
        while child.poll() is None:
            command = receive(sock, 0.025)
            if command is None or command.get("kind") == "STOP":
                reason = "parent_eof" if command is None else "stopped"
                break
            if command and command.get("kind") not in (None,):
                reason = "invalid_command"
                break
    finally:
        returncode = child.poll()
        try:
            unexpected = members(pgid, own)
        except (OSError, psutil.Error, IdentityUnavailable):
            unexpected = [{"enumeration_failed": True}]
        clean, known = cleanup(pgid, own, child)
    payload = None
    if adapter == "internal_lifecycle_fixture":
        try:
            payload = read_small_json("result.json", MAX_RESULT)
            json.dumps(payload, allow_nan=False)  # reject nonfinite fixture data before IPC
        except (OSError, ValueError, TypeError):
            payload = None
    elif reason == "completed" and returncode == 0:
        try:
            path = Path("result.json")
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 64_000_000:
                raise ValueError("invalid scientific output")
            raw = path.read_bytes()
            payload = {"output_sha256": hashlib.sha256(raw).hexdigest(), "output_bytes": len(raw)}
        except (OSError, ValueError):
            payload = None
    try:
        send(sock, {"kind": "RESULT", "nonce": nonce,
                    "job_id": input_data["job_id"], "attempt_id": input_data["attempt_id"],
                    "reason": reason, "returncode": returncode,
                    "unexpected_members": bool(unexpected and returncode is not None),
                    "clean": clean, "direct_child_reaped": child.returncode is not None,
                    "members": known, "payload": payload})
    except (BrokenPipeError, OSError):
        pass
    return 0 if clean else 4


if __name__ == "__main__":
    try:
        raise SystemExit(main(int(sys.argv[1])))
    except (BrokenPipeError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise SystemExit(5)
