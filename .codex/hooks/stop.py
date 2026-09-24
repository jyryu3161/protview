#!/usr/bin/env python3
"""Codex Stop hook: 턴 종료 시 ruff와 pytest를 돌리고, 실패하면 한 번 더 작업하게 한다."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def project_python(root: Path) -> str:
    """프로젝트 .venv가 있으면 그 python을, 없으면 hook을 띄운 python을 쓴다."""
    venv_python = root / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


# Only check product and harness code; references/ is source material.
CHECKS = [
    ([project_python(ROOT), "-m", "ruff", "check", "backend/mw", "backend/tests", "scripts", ".codex/hooks", "design/build_tokens.py"], {0}),
    ([project_python(ROOT), "-m", "pytest", "-q", "backend/tests", "scripts/test_execute.py", "scripts/test_codex_hooks.py"], {0}),
]

MAX_OUTPUT_CHARS = 1500
CHECK_TIMEOUT = 240


def run_check(cmd, root: Path):
    process = subprocess.Popen(cmd, cwd=root, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        deadline = time.monotonic() + 1
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        time.sleep(max(0, deadline - time.monotonic()))
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)


def run_checks(root: Path, checks) -> list[str]:
    failures = []
    for cmd, ok_codes in checks:
        label = "$ " + " ".join(cmd)
        try:
            r = run_check(cmd, root)
        except FileNotFoundError:
            failures.append(f"{label}\n명령을 찾을 수 없음")
            continue
        except subprocess.TimeoutExpired:
            failures.append(f"{label}\n{CHECK_TIMEOUT}초 시간 초과; 프로세스 그룹 종료")
            continue
        if r.returncode not in ok_codes:
            output = (r.stdout + r.stderr).strip()[-MAX_OUTPUT_CHARS:]
            failures.append(f"{label} (exit {r.returncode})\n{output}")
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
