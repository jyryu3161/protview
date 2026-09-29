"""Only fixed fpocket 4.2.3 worker, launched by the authenticated local guardian (standard library only).

Job mode (no arguments, cwd = the private attempt directory): read the server-staged transport input,
write ``fpocket/protein.pdb`` into a fresh private job root, copy the hash-verified engine bytes into a
private ``engine/`` directory and run that copy with the fixed argv, an allowlisted environment and
private TMPDIR, keep bounded stdout/stderr, classify the output with the pinned
``mw.pocket_output`` reader and write a small ``result.json`` descriptor. The server re-reads the
native files itself after verified group cleanup; nothing here is trusted as the published result.
Generated PyMOL/VMD scripts are never executed; nothing is downloaded or installed.

Handshake mode (``--handshake <engine root>``): compare the installed executable SHA-256 and the
install record's package hash, build and lock hashes with the pinned values. It never runs fpocket;
the observed help banner is read from the install record.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

ENGINE = "fpocket"
RELEASE = "4.2.3"
BUILD = "hb88c64c_2"
SUBDIR = "osx-arm64"
PACKAGE_SHA256 = "b40c27414ee32f543f4ed67bbf06f74063796c7d3a5759e8da4c5eac37271c5a"
EXECUTABLE_SHA256 = "a79058e4d727a798212e8deb3a47587b7c9915451b5f70c7b56bd62e15252894"
EXECUTABLE_RELPATH = "env/bin/fpocket"
RECORD_NAME = "install-record.json"
ARGV_TAIL = ("-f", "protein.pdb", "-m", "3.4", "-M", "6.2", "-D", "2.4", "-C", "s", "-e", "e", "-i", "15",
             "-p", "0.0", "--number_apol_asph_pocket", "3", "-v", "300", "-w", "p")
REPO = Path(__file__).resolve().parents[3]
LOCK_EXPLICIT = REPO / "config/pockets/fpocket-conda-explicit-osx-arm64.txt"
LOCK_HASHES = REPO / "config/pockets/fpocket-conda-lock-hashes-osx-arm64.json"
OUTPUT_MODULE = Path(__file__).resolve().parents[1] / "pocket_output.py"
JOB_ROOT = "fpocket"
JOB_TMP = "fpocket_tmp"
ENGINE_DIR = "engine"
# The worker executes a private copy of exactly the bytes it hashed, so the installed file cannot be
# swapped between the hash check and exec. The pinned binary links only /usr/lib system libraries.
ENGINE_COPY = ENGINE_DIR + "/fpocket"
MAX_EXECUTABLE_BYTES = 64 * 1024 * 1024
ENGINE_STDOUT = "engine.stdout"
ENGINE_STDERR = "engine.stderr"
MAX_STAGED_BYTES = 48 * 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_STREAM_BYTES = 1024 * 1024
PREFLIGHT_REASONS = frozenset({"staged_input_invalid", "engine_missing", "engine_hash_mismatch",
                               "transport_write_failed", "engine_launch_failed"})


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_json(value: Any) -> bytes:
    """Byte-identical to ``mw.core.handles.canonical_json``."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _read_regular(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("not a bounded regular file")
        chunks, remaining = [], limit + 1
        while remaining > 0:
            chunk = os.read(fd, min(remaining, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > limit or len(raw) != info.st_size:
            raise ValueError("file changed while reading")
        return raw
    finally:
        os.close(fd)


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("executable is not a regular file")
        while chunk := os.read(fd, 1 << 20):
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def _read_executable(path: Path) -> bytes:
    """The installed engine bytes, read once through one descriptor (bounded, regular file only)."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_EXECUTABLE_BYTES:
            raise ValueError("executable is not a bounded regular file")
        chunks, remaining = [], MAX_EXECUTABLE_BYTES + 1
        while remaining > 0 and (chunk := os.read(fd, min(remaining, 1 << 20))):
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) != info.st_size:
            raise ValueError("executable changed while reading")
        return raw
    finally:
        os.close(fd)


# ----------------------------------------------------------------- handshake
def handshake(engine_root: Path) -> dict[str, Any]:
    base = {"schema": "pocket_worker_handshake@1", "engine": ENGINE, "release": RELEASE, "build": BUILD,
            "package_sha256": PACKAGE_SHA256, "worker_sha256": _sha(Path(__file__).read_bytes()),
            "observed_banner": None, "recipe_provenance": None, "executable_sha256": None,
            "install_record_sha256": None}
    record_path = engine_root / RECORD_NAME
    executable = engine_root / EXECUTABLE_RELPATH
    if not record_path.is_file() or not executable.is_file():
        return {**base, "status": "not_installed", "reason_code": "engine_not_installed"}
    try:
        raw = _read_regular(record_path, MAX_RECORD_BYTES)
        record = json.loads(raw)
        actual = _file_sha(executable)
    except (OSError, ValueError):
        return {**base, "status": "unreviewed_build", "reason_code": "install_record_invalid"}
    base.update(executable_sha256=actual, install_record_sha256=_sha(raw))
    try:
        fpocket = [p for p in record["packages"] if type(p) is dict and p.get("name") == ENGINE]
        provenance = record["recipe_provenance"]
        reviewed = (type(record) is dict and record["schema"] == "fpocket_install_record@1" and
                    record["engine"] == ENGINE and record["release"] == RELEASE and record["build"] == BUILD and
                    record["subdir"] == SUBDIR and record["package_sha256"] == PACKAGE_SHA256 and
                    record["executable"] == {"path": EXECUTABLE_RELPATH, "sha256": EXECUTABLE_SHA256} and
                    record["lock"]["explicit_sha256"] == _sha(LOCK_EXPLICIT.read_bytes()) and
                    record["lock"]["hashes_sha256"] == _sha(LOCK_HASHES.read_bytes()) and
                    len(fpocket) == 1 and fpocket[0].get("sha256") == PACKAGE_SHA256 and
                    fpocket[0].get("build") == BUILD and fpocket[0].get("version") == RELEASE and
                    type(provenance) is dict and provenance.get("package", {}).get("build") == BUILD and
                    provenance.get("package", {}).get("version") == RELEASE and
                    type(record["observed_banner"]) is str and 0 < len(record["observed_banner"]) <= 200)
    except (KeyError, TypeError, AttributeError, OSError):
        reviewed = False
    if not reviewed:
        return {**base, "status": "unreviewed_build", "reason_code": "install_record_mismatch"}
    if actual != EXECUTABLE_SHA256:
        return {**base, "status": "unreviewed_build", "reason_code": "executable_hash_mismatch"}
    return {**base, "status": "ready", "reason_code": None, "observed_banner": record["observed_banner"],
            "recipe_provenance": provenance}


# ----------------------------------------------------------------- job
def _load_output_module():
    spec = importlib.util.spec_from_file_location("pocket_output_pinned", OUTPUT_MODULE)
    if spec is None or spec.loader is None:
        raise ImportError("pinned pocket output reader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _private_dir(name: str) -> Path:
    os.mkdir(name, 0o700)
    info = os.lstat(name)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise OSError("unsafe private directory")
    return Path.cwd() / name


def _exclusive(path: Path | str, raw: bytes | None = None):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    if raw is None:
        return os.fdopen(fd, "wb")
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return None


def _write_result(value: dict[str, Any]) -> None:
    _exclusive("result.json", canonical_json(value))


# TMPDIR is given relative to the job root (the engine's cwd). The pinned binary builds temporary file
# names from TMPDIR in a fixed-size buffer and was observed to die with SIGTRAP once the TMPDIR string
# exceeded about 220 characters (deep run roots); the relative spelling keeps it short and private.
ENGINE_TMPDIR = "../" + JOB_TMP


def engine_environment() -> dict[str, str]:
    """Allowlist only: no credentials, proxies, loader or Python variables reach the engine."""
    return {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TMPDIR": ENGINE_TMPDIR}


def _bounded_stream(name: str) -> tuple[bytes, bool]:
    """Read at most the stream limit plus one byte; an oversized stream is never read whole."""
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("engine stream is not a regular file")
        chunks, remaining = [], MAX_STREAM_BYTES + 1
        while remaining > 0 and (chunk := os.read(fd, min(remaining, 1 << 20))):
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        return raw, info.st_size > MAX_STREAM_BYTES or len(raw) > MAX_STREAM_BYTES
    finally:
        os.close(fd)


def run_job() -> int:
    control = json.loads(_read_regular(Path("input.json"), 4096))
    base = {"schema": "pocket_worker_result@1", "job_id": control["job_id"],
            "attempt_id": control["attempt_id"], "worker_sha256": _sha(Path(__file__).read_bytes()),
            "argv": [ENGINE, *ARGV_TAIL], "stage": "preflight", "outcome": "failure", "failure": None,
            "exit_code": None, "stdout_bytes": None, "stderr_bytes": None, "stdout_sha256": None,
            "stderr_sha256": None, "engine_environment_keys": [], "result_sha256": None, "total_count": None}

    def refuse(code: str) -> int:
        _write_result({**base, "failure": {"failure_class": "fatal", "reason_code": code}})
        return 0

    try:
        raw = _read_regular(Path("structure.json"), MAX_STAGED_BYTES)
        staged = json.loads(raw)
        if (_sha(raw) != control["input_sha256"] or canonical_json(staged) != raw or type(staged) is not dict or
                set(staged) != {"schema", "job_id", "attempt_id", "executable", "executable_sha256", "argv_tail",
                                "pdb", "pdb_sha256", "atoms"} or
                staged["schema"] != "pocket_worker_input@1" or staged["job_id"] != control["job_id"] or
                staged["attempt_id"] != control["attempt_id"] or staged["executable_sha256"] != EXECUTABLE_SHA256 or
                staged["argv_tail"] != list(ARGV_TAIL) or type(staged["executable"]) is not str or
                not os.path.isabs(staged["executable"]) or type(staged["pdb"]) is not str or
                type(staged["atoms"]) is not list or not staged["atoms"] or
                not re.fullmatch(r"[0-9a-f]{64}", staged["pdb_sha256"])):
            return refuse("staged_input_invalid")
        pdb = staged["pdb"].encode("ascii")
        if _sha(pdb) != staged["pdb_sha256"]:
            return refuse("staged_input_invalid")
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return refuse("staged_input_invalid")
    try:
        image = _read_executable(Path(staged["executable"]))
    except (OSError, ValueError):
        return refuse("engine_missing")
    if _sha(image) != EXECUTABLE_SHA256:
        return refuse("engine_hash_mismatch")
    try:
        _private_dir(ENGINE_DIR)
        _exclusive(ENGINE_COPY, image)
        os.chmod(ENGINE_COPY, 0o500)
        executable = Path.cwd() / ENGINE_COPY
        if _sha(_read_regular(executable, len(image))) != EXECUTABLE_SHA256:
            return refuse("engine_hash_mismatch")
    except (OSError, ValueError):
        return refuse("engine_launch_failed")
    try:
        output = _load_output_module()
        root = _private_dir(JOB_ROOT)
        _private_dir(JOB_TMP)
        _exclusive(root / "protein.pdb", pdb)
        if _sha(_read_regular(root / "protein.pdb", len(pdb))) != staged["pdb_sha256"]:
            return refuse("transport_write_failed")
    except (OSError, ValueError, ImportError):
        return refuse("transport_write_failed")
    env = engine_environment()
    base["engine_environment_keys"] = sorted(env)
    stdout_file = _exclusive(ENGINE_STDOUT)
    stderr_file = _exclusive(ENGINE_STDERR)
    try:
        # Fixed argv, no shell; the process stays in the guardian's owned process group.
        process = subprocess.Popen([str(executable), *ARGV_TAIL], cwd=root, env=env, stdin=subprocess.DEVNULL,
                                   stdout=stdout_file, stderr=stderr_file, close_fds=True, shell=False)
    except OSError:
        return refuse("engine_launch_failed")
    finally:
        stdout_file.close()
        stderr_file.close()
    exit_code = process.wait()
    stdout, stdout_over = _bounded_stream(ENGINE_STDOUT)
    stderr, stderr_over = _bounded_stream(ENGINE_STDERR)
    base.update(stage="engine", exit_code=exit_code, stdout_bytes=len(stdout), stderr_bytes=len(stderr),
                stdout_sha256=_sha(stdout), stderr_sha256=_sha(stderr))
    if stdout_over or stderr_over:
        _write_result({**base, "failure": {"failure_class": "resource_exceeded",
                                           "reason_code": "stdout_limit" if stdout_over else "stderr_limit"}})
        return 0
    try:
        result, _ = output.classify(root, staged["atoms"], exit_code=exit_code, stdout=stdout, stderr=stderr,
                                    killed=exit_code < 0)
    except output.PocketOutputFailure as failure:
        _write_result({**base, "failure": {"failure_class": failure.failure_class,
                                           "reason_code": failure.reason_code}})
        return 0
    _write_result({**base, "outcome": result["classification"], "result_sha256": _sha(canonical_json(result)),
                   "total_count": result["total_count"]})
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--handshake":
        sys.stdout.write(json.dumps(handshake(Path(argv[1])), sort_keys=True) + "\n")
        return 0
    if argv:
        return 2
    return run_job()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
