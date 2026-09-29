"""
.codex/hooks/ 스크립트 테스트.
Codex는 hook에 stdin JSON을 넘기고, exit 2(stderr 사유) 또는 stdout JSON으로 결정을 받는다.
"""

import importlib.util
import json
import os
import subprocess
import sys
import time
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

    def test_measured_check_budgets_fit_outer_hook_deadline(self):
        stop = _load("stop")
        assert stop.check_timeout(stop.CHECKS[0][0]) == 45
        assert len(stop.CHECKS) == 4
        assert all(stop.check_timeout(command) == 480 for command, _ in stop.CHECKS[1:])
        assert 45 + max(stop.check_timeout(command) for command, _ in stop.CHECKS[1:]) + 4 < 600

    def test_parallel_pytest_groups_have_exact_disjoint_file_union(self):
        stop = _load("stop")
        groups = [command for command, _ in stop.CHECKS[1:]]
        assert all(command[1:4] == ["-m", "pytest", "-q"] for command in groups)
        assert groups[0][4:] == ["backend/tests/test_chemical_interactions.py"]
        assert groups[1][4:] == ["backend/tests/test_m11_job_api.py"]
        assert groups[2][4:] == ["backend/tests", "scripts/test_execute.py", "scripts/test_codex_hooks.py",
                                 "scripts/test_setup_fpocket.py", "scripts/test_m13_offscreen_acceptance.py",
                                 "--ignore=backend/tests/test_chemical_interactions.py",
                                 "--ignore=backend/tests/test_m11_job_api.py"]

    def test_default_groups_really_run_concurrently_and_all_must_pass(self, tmp_path, monkeypatch):
        stop = _load("stop")
        gate = ("from pathlib import Path; import sys,time; "
                "p=Path(sys.argv[1]); p.write_text('started'); "
                "end=time.monotonic()+3; "
                "exec('while time.monotonic()<end and len(list(p.parent.glob(\"group-*\")))<3: "
                "time.sleep(0.01)\\n'); "
                "raise SystemExit(0 if len(list(p.parent.glob('group-*')))==3 else 9)")
        checks = [(PASS, {0})] + [([sys.executable, "-c", gate, str(tmp_path / f"group-{i}")], {0})
                                 for i in range(3)]
        monkeypatch.setattr(stop, "CHECKS", checks)
        assert stop.run_checks(tmp_path, stop.CHECKS) == []
        checks[2] = (FAIL, {0})
        assert any("E501 boom" in failure for failure in stop.run_checks(tmp_path, stop.CHECKS))

    def test_timeout_blocks_and_retains_partial_output(self, tmp_path, monkeypatch):
        stop = _load("stop")
        monkeypatch.setattr(stop, "CHECK_TIMEOUT", 0.1)
        hanging = [sys.executable, "-u", "-c",
                   ("import time; print('x' * 10000); "
                    "print('partial-native-test-output', flush=True); time.sleep(30)")]
        result = stop.decide({}, tmp_path, [(hanging, {0})])
        assert result["decision"] == "block"
        assert "시간 초과" in result["reason"]
        assert "partial-native-test-output" in result["reason"]
        assert len(result["reason"]) < 5000

    def test_timeout_kills_descendant_group_with_bounded_cleanup(self, tmp_path, monkeypatch):
        stop = _load("stop")
        monkeypatch.setattr(stop, "CHECK_TIMEOUT", 0.2)
        pidfile = tmp_path / "child.pid"
        script = ("import subprocess,sys,time; "
                  "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                  "open(sys.argv[1],'w').write(str(p.pid)); "
                  "print('group-partial',flush=True); time.sleep(30)")
        started = time.monotonic()
        result = stop.decide({}, tmp_path, [([sys.executable, "-u", "-c", script, str(pidfile)], {0})])
        assert time.monotonic() - started < 5
        assert "group-partial" in result["reason"]
        pid = int(pidfile.read_text())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            import psutil
            assert psutil.Process(pid).status() == psutil.STATUS_ZOMBIE

    def test_timeout_escalates_even_when_leader_exits_and_child_closes_pipes(self, tmp_path, monkeypatch):
        stop = _load("stop")
        monkeypatch.setattr(stop, "CHECK_TIMEOUT", 0.2)
        pidfile = tmp_path / "ignoring-child.pid"
        child = ("import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                 "time.sleep(30)")
        parent = ("import subprocess,sys,time; "
                  f"p=subprocess.Popen([sys.executable,'-c',{child!r}],"
                  "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
                  "open(sys.argv[1],'w').write(str(p.pid)); "
                  "print('leader-partial',flush=True); time.sleep(30)")
        started = time.monotonic()
        result = stop.decide({}, tmp_path, [([sys.executable, "-u", "-c", parent, str(pidfile)], {0})])
        assert time.monotonic() - started < 5
        assert "leader-partial" in result["reason"]
        pid = int(pidfile.read_text())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            import psutil
            assert psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
