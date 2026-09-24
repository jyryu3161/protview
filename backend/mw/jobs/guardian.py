"""Fixed POSIX launch anchor. Invoked only by the local queue with an inherited control fd."""
from __future__ import annotations

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

MAX_CONTROL = 8192
MAX_RESULT = 8192
FIXTURE = Path(__file__).with_name("lifecycle_fixture.py")
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
            if proc.status() == psutil.STATUS_ZOMBIE:
                continue
            result.append({"pid": pid, "create_time": proc.create_time(), "uid": proc.uids().real})
        except (psutil.NoSuchProcess, ProcessLookupError):
            continue
    return result


def signal_member(entry: dict, pgid: int, sig: int) -> None:
    try:
        proc = psutil.Process(entry["pid"])
        if (proc.create_time() == entry["create_time"] and proc.uids().real == entry["uid"] == os.getuid() and
                os.getpgid(entry["pid"]) == pgid and
                proc.status() != psutil.STATUS_ZOMBIE):
            os.kill(entry["pid"], sig)
    except (psutil.NoSuchProcess, ProcessLookupError):
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
    except (OSError, psutil.Error):
        # The authenticated guardian owns this fresh session. If enumeration is
        # unavailable, fail closed by killing its entire group, including itself.
        os.killpg(pgid, signal.SIGKILL)
        raise


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
    if (set(input_data) != {"nonce", "job_id", "attempt_id", "adapter", "fixture_mode"} or
            not isinstance(input_data["nonce"], str) or not re.fullmatch(r"[0-9a-f]{32}", input_data["nonce"]) or
            input_data["adapter"] != "internal_lifecycle_fixture" or
            input_data["fixture_mode"] not in FIXTURE_MODES or
            any(not isinstance(input_data[key], str) or not re.fullmatch(r"[a-z0-9_]{1,100}", input_data[key])
                for key in ("job_id", "attempt_id"))):
        return 2
    nonce = input_data["nonce"]
    own = os.getpid()
    pgid = os.getpgid(own)
    session = os.getsid(own)
    if own != pgid or own != session:
        return 2
    identity = {"nonce": nonce, "pid": own, "pgid": pgid, "session": session,
                "create_time": psutil.Process(own).create_time(), "uid": os.getuid()}
    receipt(identity)
    send(sock, {"kind": "HELLO", **identity,
                "runtime": {"prefix": sys.prefix, "executable": sys.executable,
                            "psutil_version": psutil.__version__,
                            "environment_keys": sorted(os.environ)}})
    command = receive(sock, 3)
    if command is None or command.get("kind") != "GO" or command.get("nonce") != nonce:
        return 0
    if input_data.get("adapter") != "internal_lifecycle_fixture":
        send(sock, {"kind": "RESULT", "error": "adapter_unavailable"})
        return 3
    child = subprocess.Popen([sys.executable, "-I", str(FIXTURE)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             close_fds=True, cwd=Path.cwd(), env={"PATH": "/usr/bin:/bin", "LANG": "C",
                                                                   "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1",
                                                                   "TMPDIR": str(Path.cwd())})
    reason = "completed"
    try:
        send(sock, {"kind": "STARTED", "nonce": nonce,
                    "job_id": input_data["job_id"], "attempt_id": input_data["attempt_id"], "pid": child.pid,
                    "create_time": psutil.Process(child.pid).create_time()})
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
        except (OSError, psutil.Error):
            unexpected = [{"enumeration_failed": True}]
        clean, known = cleanup(pgid, own, child)
    payload = None
    try:
        payload = read_small_json("result.json", MAX_RESULT)
        json.dumps(payload, allow_nan=False)  # reject nonfinite fixture data before IPC
    except (OSError, ValueError, TypeError):
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
