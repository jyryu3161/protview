#!/usr/bin/env python3
"""Codex Stop hook: 턴 종료 시 ruff와 pytest를 돌리고, 실패하면 한 번 더 작업하게 한다."""

import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def project_python(root: Path) -> str:
    """프로젝트 .venv가 있으면 그 python을, 없으면 hook을 띄운 python을 쓴다."""
    venv_python = root / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


# Only check product and harness code; references/ is source material.
CHECKS = [
    ([project_python(ROOT), "-m", "ruff", "check", "backend/mw", "backend/tests", "scripts", ".codex/hooks", "design/build_tokens.py"], {0}),
    ([project_python(ROOT), "-m", "pytest", "-q", "backend/tests/test_chemical_interactions.py"], {0}),
    ([project_python(ROOT), "-m", "pytest", "-q", "backend/tests/test_m11_job_api.py"], {0}),
    ([project_python(ROOT), "-m", "pytest", "-q", "backend/tests", "scripts/test_execute.py",
      "scripts/test_codex_hooks.py", "scripts/test_setup_fpocket.py",
      "--ignore=backend/tests/test_chemical_interactions.py",
      "--ignore=backend/tests/test_m11_job_api.py"], {0}),
]

MAX_OUTPUT_CHARS = 1500
# Ruff runs first; the three disjoint pytest groups then run concurrently.
# Their exact collection union is the former sequential suite. Even one group
# reaching its bound leaves process-group cleanup below the trusted 600 s hook.
RUFF_TIMEOUT = 45
CHECK_TIMEOUT = 480


def check_timeout(cmd) -> int:
    return RUFF_TIMEOUT if len(cmd) >= 4 and cmd[1:4] == ["-m", "ruff", "check"] else CHECK_TIMEOUT


def _text(value) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""


def run_check(cmd, root: Path):
    timeout = check_timeout(cmd)
    process = subprocess.Popen(cmd, cwd=root, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as expired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        # Do not reap the leader before escalation: its reserved PID anchors
        # the process-group identity even if it exits on TERM while a child
        # ignores TERM and has closed its inherited output pipes.
        time.sleep(0.2)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired as final:
            # A detached descendant may retain a pipe after the owned group
            # is killed. Never let that defeat the outer trusted deadline.
            stdout = _text(final.stdout) or _text(expired.stdout)
            stderr = _text(final.stderr) or _text(expired.stderr)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        raise subprocess.TimeoutExpired(cmd, timeout,
                                        output=_text(stdout) or _text(expired.stdout),
                                        stderr=_text(stderr) or _text(expired.stderr)) from expired
    return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)


def run_checks(root: Path, checks) -> list[str]:
    def one(item):
        cmd, ok_codes = item
        label = "$ " + " ".join(cmd)
        try:
            r = run_check(cmd, root)
        except FileNotFoundError:
            return f"{label}\n명령을 찾을 수 없음"
        except subprocess.TimeoutExpired as expired:
            output = (_text(expired.stdout) + _text(expired.stderr)).strip()[-MAX_OUTPUT_CHARS:]
            return f"{label}\n{expired.timeout}초 시간 초과; 프로세스 그룹 종료\n{output}"
        if r.returncode not in ok_codes:
            output = (r.stdout + r.stderr).strip()[-MAX_OUTPUT_CHARS:]
            return f"{label} (exit {r.returncode})\n{output}"
        return None

    if checks is CHECKS:
        first = one(CHECKS[0])
        if first is not None:
            return [first]
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(one, CHECKS[1:]))
        return [result for result in results if result is not None]
    failures = []
    for item in checks:
        result = one(item)
        if result is not None:
            failures.append(result)
    return failures


def decide(payload: dict, root: Path, checks) -> dict | None:
    # 이미 hook이 계속 진행시킨 턴이면 무한 루프를 막기 위해 통과시킨다.
    if payload.get("stop_hook_active"):
        return None
    failures = run_checks(root, checks)
    if not failures:
        return None
    reason = "Stop hook 검사 실패. 아래 오류를 고친 뒤 끝내라.\n\n" + "\n\n".join(failures)
    return {"decision": "block", "reason": reason}


def main() -> int:
    result = decide(json.load(sys.stdin), ROOT, CHECKS)
    if result:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
