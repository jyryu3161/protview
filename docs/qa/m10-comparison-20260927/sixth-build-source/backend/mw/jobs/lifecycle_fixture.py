"""Private supervision fixtures. Never a production scientific adapter or result."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil


def main() -> int:
    input_file = Path("input.json")
    if input_file.stat().st_size > 4096:
        return 2
    request = json.loads(input_file.read_text())
    mode = request["fixture_mode"]
    attempt = request["attempt_id"]
    # Private test evidence; the job result and public events never reference it.
    Path("fixture_runtime.json").write_text(json.dumps({
        "prefix": sys.prefix, "executable": sys.executable,
        "psutil_version": psutil.__version__, "environment_keys": sorted(os.environ),
    }))
    if mode in {"grandchild", "leader_exit"}:
        code = f"""import json, os, signal, sys, time
from pathlib import Path
sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
from process_identity import capture
signal.signal(signal.SIGTERM, signal.SIG_IGN)
with Path('grandchild.ready').open('x') as stream:
    json.dump({{'pid': os.getpid(), 'start_identity': capture(os.getpid())}}, stream)
    stream.flush()
    os.fsync(stream.fileno())
time.sleep(30)
"""
        child = subprocess.Popen([sys.executable, "-I", "-c", code],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, close_fds=True)
        end = time.monotonic() + 3
        while time.monotonic() < end and not Path("grandchild.ready").exists():
            if child.poll() is not None:
                break
            time.sleep(0.01)
        if not Path("grandchild.ready").exists():
            return 3
    if mode in {"sleep", "grandchild"}:
        time.sleep(30)
    if mode == "nonzero":
        return 7
    payload = {"schema": "lifecycle_fixture@1", "attempt_id": attempt,
               "job_id": request["job_id"], "fixture": True, "ok": True}
    if mode == "wrong_id":
        payload["attempt_id"] = "wrong"
    if mode == "invalid":
        payload["ok"] = float("nan")
    if mode == "malformed":
        Path("result.json").write_text("{")
    elif mode == "oversize":
        Path("result.json").write_bytes(b"x" * 9000)
    else:
        Path("result.json").write_text(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
