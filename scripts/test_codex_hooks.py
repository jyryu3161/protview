"""
.codex/hooks/ 스크립트 테스트.
Codex는 hook에 stdin JSON을 넘기고, exit 2(stderr 사유) 또는 stdout JSON으로 결정을 받는다.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / ".codex" / "hooks"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, HOOKS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_hook(name, payload):
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / f"{name}.py")],
        input=json.dumps(payload), capture_output=True, text=True, check=False,
    )


# ---------------------------------------------------------------------------
# PreToolUse: 위험 명령 차단 (.claude/settings.json 훅과 같은 패턴)
# ---------------------------------------------------------------------------

class TestPreToolUse:
    @pytest.mark.parametrize("command", [
        "rm -rf build",
        "git push --force origin main",
        "git reset --hard HEAD~1",
        "psql -c 'DROP TABLE example_records'",
    ])
    def test_blocks_dangerous_command(self, command):
        r = _run_hook("pre_tool_use", {"tool_name": "Bash", "tool_input": {"command": command}})
        assert r.returncode == 2
        assert "BLOCKED" in r.stderr

    @pytest.mark.parametrize("command", ["pytest -q", "git status", "rm build/tmp.txt"])
    def test_allows_safe_command(self, command):
        r = _run_hook("pre_tool_use", {"tool_name": "Bash", "tool_input": {"command": command}})
        assert r.returncode == 0

    def test_accepts_argv_list_command(self):
        r = _run_hook("pre_tool_use", {"tool_name": "Bash", "tool_input": {"command": ["bash", "-lc", "rm -rf x"]}})
        assert r.returncode == 2
        assert "BLOCKED" in r.stderr

    def test_missing_command_is_allowed(self):
        r = _run_hook("pre_tool_use", {"tool_name": "Bash", "tool_input": {}})
        assert r.returncode == 0


# ---------------------------------------------------------------------------
# Stop: ruff + pytest. 실패하면 한 번만 계속 진행시킨다.
# ---------------------------------------------------------------------------

PASS = [sys.executable, "-c", "raise SystemExit(0)"]
FAIL = [sys.executable, "-c", "print('E501 boom'); raise SystemExit(1)"]
NO_TESTS = [sys.executable, "-c", "raise SystemExit(5)"]


class TestStop:
    def test_default_checks_are_ruff_and_pytest(self):
        stop = _load("stop")
        cmds = [" ".join(cmd) for cmd, _ in stop.CHECKS]
        assert any(" -m ruff check " in f" {c} " for c in cmds)
        assert any("pytest" in c for c in cmds)

    def test_all_pass_returns_none(self, tmp_path):
        stop = _load("stop")
        assert stop.decide({}, tmp_path, [(PASS, {0})]) is None

    def test_failure_blocks_with_output_in_reason(self, tmp_path):
        stop = _load("stop")
        result = stop.decide({}, tmp_path, [(PASS, {0}), (FAIL, {0})])
        assert result["decision"] == "block"
        assert "E501 boom" in result["reason"]

    def test_allowed_nonzero_code_passes(self, tmp_path):
        # pytest exit 5 = 수집된 테스트 없음. 실패로 보지 않는다.
        stop = _load("stop")
        assert stop.decide({}, tmp_path, [(NO_TESTS, {0, 5})]) is None

    def test_stop_hook_active_does_not_block_again(self, tmp_path):
        # 이미 한 번 계속 진행시킨 턴이면 무한 루프를 막기 위해 통과시킨다.
        stop = _load("stop")
        assert stop.decide({"stop_hook_active": True}, tmp_path, [(FAIL, {0})]) is None

    def test_missing_tool_is_reported(self, tmp_path):
        stop = _load("stop")
        result = stop.decide({}, tmp_path, [(["no-such-tool-xyz"], {0})])
        assert result["decision"] == "block"
        assert "no-such-tool-xyz" in result["reason"]

    def test_uses_project_venv_python_when_present(self, tmp_path):
        # hook은 PATH의 python3로 뜨지만 pytest는 프로젝트 .venv에서 돌아야 의존성이 맞는다.
        venv_python = tmp_path / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.touch()
        stop = _load("stop")
        assert stop.project_python(tmp_path) == str(venv_python)

    def test_falls_back_to_current_python_without_venv(self, tmp_path):
        stop = _load("stop")
        assert stop.project_python(tmp_path) == sys.executable

    def test_reason_is_truncated(self, tmp_path):
        stop = _load("stop")
        noisy = [sys.executable, "-c", "print('x' * 50000); raise SystemExit(1)"]
        result = stop.decide({}, tmp_path, [(noisy, {0})])
        assert len(result["reason"]) < 5000
