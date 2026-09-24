"""Contract tests for the phase runner's verification gates."""

import hashlib
import json
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from scripts import execute

COMPLETE_JSONL = "\n".join(json.dumps({"type": kind}) for kind in (
    "thread.started", "turn.started", "turn.completed")) + "\n"
TOOL_ERROR_STDERR = (
    "2026-09-24T03:27:00.215896Z ERROR codex_core::tools::router: "
    "error=apply_patch verification failed: Failed to find expected lines in docs/HARNESS.md:\n"
    "The runner rejects a CLI result that reports skipped or untrusted hooks.\n"
    "2026-09-24T03:28:16.562552Z ERROR codex_core::tools::router: "
    "error=apply_patch verification failed: Failed to find expected lines in docs/M4_JOBS.md:\n"
    "The parent retains phase review and acceptance ownership.\n"
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(execute, "ROOT", tmp_path)
    phase = tmp_path / "phases" / "demo"
    phase.mkdir(parents=True)
    (phase / "step0.md").write_text("Implement demo", encoding="utf-8")
    (phase / "index.json").write_text(json.dumps({
        "project": "Demo", "phase": "demo", "steps": [{
            "step": 0, "name": "demo-step", "status": "pending",
            "acceptance_checks": [["python3", "-c", "print('ok')"]],
        }],
    }), encoding="utf-8")
    (tmp_path / "phases" / "index.json").write_text(json.dumps({
        "phases": [{"dir": "demo", "status": "pending"}],
    }), encoding="utf-8")
    implementation = tmp_path / "app.py"
    implementation.write_text("print('hello')\n", encoding="utf-8")
    report = phase / "reviews" / "step0.md"
    report.parent.mkdir()
    report.write_text("# Findings\nThe implementation matches the step and its acceptance check. "
                      "I inspected app.py and found no blocking issues.\n\nVerdict: APPROVED\n", encoding="utf-8")
    return tmp_path, implementation, report


def test_dry_run_does_not_change_index(project, capsys):
    root, _, _ = project
    index = root / "phases" / "demo" / "index.json"
    before = index.read_bytes()
    assert execute.main(["demo", "--dry-run"]) == 0
    assert index.read_bytes() == before
    assert "gpt-6-sol" in capsys.readouterr().out


def test_review_requires_real_checks_and_bound_files(project):
    root, implementation, report = project
    runner = execute.StepExecutor("demo")
    runner.record_review(0, report, [implementation])
    review = runner.step(0)["review"]
    assert review["model"] == "gpt-6-astra"
    assert review["reviewed_files"]["app.py"] == hashlib.sha256(implementation.read_bytes()).hexdigest()
    runner.verify()
    top = json.loads((root / "phases" / "index.json").read_text())
    assert top["phases"][0]["status"] == "completed"


def test_changed_code_invalidates_review(project):
    _, implementation, report = project
    runner = execute.StepExecutor("demo")
    runner.record_review(0, report, [implementation])
    implementation.write_text("print('changed')\n", encoding="utf-8")
    with pytest.raises(ValueError, match="reviewed file changed"):
        runner.verify()


def test_changed_report_invalidates_review(project):
    _, implementation, report = project
    runner = execute.StepExecutor("demo")
    runner.record_review(0, report, [implementation])
    report.write_text(report.read_text() + "Another note", encoding="utf-8")
    with pytest.raises(ValueError, match="report changed"):
        runner.verify()


def test_model_label_without_report_is_insufficient(project):
    _, _, _ = project
    runner = execute.StepExecutor("demo")
    runner.save_step(0, status="completed", review={"model": "gpt-6-astra", "verdict": "approved"})
    with pytest.raises(ValueError):
        runner.verify()


def test_failing_ac_cannot_complete(project):
    _, implementation, report = project
    runner = execute.StepExecutor("demo")
    runner.save_step(0, acceptance_checks=[["python3", "-c", "raise SystemExit(2)"]])
    with pytest.raises(ValueError, match="Acceptance checks failed"):
        runner.record_review(0, report, [implementation])
    assert runner.step(0)["status"] == "pending"


def test_rejects_private_evidence(project):
    root, _, report = project
    secret = root / ".env"
    secret.write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError, match="private"):
        execute.StepExecutor("demo").record_review(0, report, [secret])


def test_rejects_shell_acceptance_check(project):
    _, _, _ = project
    with pytest.raises(ValueError, match="shell"):
        execute.checks_for({"step": 0, "acceptance_checks": [["bash", "-c", "true"]]})


def test_model_invocation_pins_sandbox_and_hooks(project):
    runner = execute.StepExecutor("demo")
    output = '\n'.join(json.dumps({"type": kind}) for kind in (
        "thread.started", "turn.started", "turn.completed")) + '\n'
    with patch.object(runner, "codex_binary", return_value="/working/codex"), \
         patch.object(execute, "run_supervised", return_value=subprocess.CompletedProcess([], 0, output, "")) as call:
        runner.invoke(execute.IMPLEMENTER_MODEL, "Implement")
    command = call.call_args.args[0]
    assert "--json" in command
    assert command[command.index("--model") + 1] == "gpt-6-sol"
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    assert command[command.index("--enable") + 1] == "hooks"
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert "--dangerously-bypass-hook-trust" not in command


def test_jsonl_agent_and_tool_content_cannot_trigger_hook_rejection(project):
    _, _, report = project
    events = [{"type": "thread.started", "thread_id": "fixture"},
              {"type": "turn.started"},
              {"type": "item.completed", "item": {"type": "agent_message",
                  "text": "hooks.py returned 181 passed, 17 skipped; warning: hooks untrusted"}},
              {"type": "item.completed", "item": {"type": "command_execution",
                  "output": {"nested": "hook reached 1 failed, 197 passed, 0 skipped"}}},
              {"type": "turn.completed"}]
    output = "\n".join(json.dumps(event) for event in events) + "\n"
    runner = execute.StepExecutor("demo")
    with patch.object(runner, "codex_binary", return_value="/working/codex"), \
         patch.object(execute, "run_supervised", return_value=subprocess.CompletedProcess(
             [], 0, output, "hooks.py returned 181 passed, 17 skipped\n"
                            "Stop hook reached 1 failed, 197 passed, 0 skipped")) as call:
        runner.invoke(execute.REVIEWER_MODEL, "Review", read_only=True, report=report)
    command = call.call_args.args[0]
    assert command[command.index("--model") + 1] == "gpt-6-astra"
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--output-last-message") + 1] == str(report)


def test_multiline_tool_error_does_not_turn_quoted_source_into_hook_warning():
    # Focused, path-sanitized fixture from the 139-event M4 CLI capture.
    result = subprocess.CompletedProcess([], 0, COMPLETE_JSONL, TOOL_ERROR_STDERR)
    execute.check_codex_result(result, execute.IMPLEMENTER_MODEL)
    continuation = TOOL_ERROR_STDERR + "skipped untrusted hooks\n"
    execute.check_codex_result(subprocess.CompletedProcess([], 0, COMPLETE_JSONL, continuation),
                               execute.IMPLEMENTER_MODEL)


@pytest.mark.parametrize("position", ["before", "after"])
def test_genuine_standalone_warning_is_rejected_next_to_tool_error(position):
    warning = "Warning: skipped untrusted hooks\n"
    stderr = warning + TOOL_ERROR_STDERR if position == "before" else TOOL_ERROR_STDERR + warning
    result = subprocess.CompletedProcess([], 0, COMPLETE_JSONL, stderr)
    with pytest.raises(ValueError, match="hooks"):
        execute.check_codex_result(result, execute.IMPLEMENTER_MODEL)


@pytest.mark.parametrize("header", ["Warning", "WARN", "Error"])
def test_standalone_diagnostic_headers_are_rejected(header):
    result = subprocess.CompletedProcess([], 0, COMPLETE_JSONL, f"{header}: project hooks are untrusted\n")
    with pytest.raises(ValueError, match="hooks"):
        execute.check_codex_result(result, execute.IMPLEMENTER_MODEL)


def test_ansi_and_multiple_runtime_records_keep_header_boundaries():
    stderr = ("\x1b[31m" + TOOL_ERROR_STDERR +
              "2026-09-24T03:29:00Z WARN codex_core::hooks: project hooks skipped as untrusted\x1b[0m\n")
    result = subprocess.CompletedProcess([], 0, COMPLETE_JSONL, stderr)
    with pytest.raises(ValueError, match="hooks"):
        execute.check_codex_result(result, execute.IMPLEMENTER_MODEL)


def test_tool_header_quoting_warning_is_not_runtime_hook_diagnostic():
    stderr = ("2026-09-24T03:29:00Z ERROR codex_core::tools::router: "
              "Warning: skipped untrusted hooks\n")
    execute.check_codex_result(subprocess.CompletedProcess([], 0, COMPLETE_JSONL, stderr),
                               execute.IMPLEMENTER_MODEL)


@pytest.mark.parametrize("body", ["skipped untrusted hooks", "Warning: skipped untrusted hooks"])
def test_generic_runtime_header_with_direct_hook_warning_is_rejected(body):
    stderr = f"2026-09-24T03:29:00Z WARN codex_core::runtime: {body}\n"
    result = subprocess.CompletedProcess([], 0, COMPLETE_JSONL, stderr)
    with pytest.raises(ValueError, match="hooks"):
        execute.check_codex_result(result, execute.IMPLEMENTER_MODEL)


def test_plain_test_output_and_nested_jsonl_prose_are_not_diagnostics():
    events = [json.loads(line) for line in COMPLETE_JSONL.splitlines()]
    events.insert(2, {"type": "item.completed", "item": {"type": "agent_message",
                      "text": "Warning: skipped untrusted hooks"}})
    events.insert(3, {"type": "item.completed", "item": {"type": "command_execution",
                      "output": {"text": "Error: project hooks not trusted"}}})
    output = "\n".join(json.dumps(event) for event in events) + "\n"
    stderr = "hooks.py returned 181 passed, 17 skipped\nStop hook: 1 failed, 197 passed, 0 skipped\n"
    execute.check_codex_result(subprocess.CompletedProcess([], 0, output, stderr),
                               execute.IMPLEMENTER_MODEL)


@pytest.mark.parametrize(("returncode", "events", "stderr", "error"), [
    (0, ["thread.started", "turn.started", "turn.completed"],
     "\x1b[33mWARNING: skipped untrusted hooks\x1b[0m", "hooks"),
    (2, ["thread.started", "turn.started", "turn.completed"], "runtime failed", r"failed \(2\)"),
    (0, ["thread.started", "turn.started", "turn.failed"], "", "turn.failed"),
    (0, ["thread.started", "turn.started", "error", "turn.completed"], "", "reported error"),
    (0, ["thread.started", "turn.started"], "", "without a completed turn"),
])
def test_jsonl_invocation_rejects_runtime_failure(project, returncode, events, stderr, error):
    output = "\n".join(json.dumps({"type": kind}) for kind in events) + "\n"
    runner = execute.StepExecutor("demo")
    with (patch.object(runner, "codex_binary", return_value="/working/codex"),
          patch.object(execute, "run_supervised", return_value=subprocess.CompletedProcess([], returncode, output, stderr)),
          pytest.raises(ValueError, match=error)):
        runner.invoke(execute.IMPLEMENTER_MODEL, "Implement")


@pytest.mark.parametrize("output", ["not json\n", '{"type":"turn.completed"}\n',
                                     '{"type":"thread.started"}\n{"type":4}\n'])
def test_jsonl_invocation_rejects_malformed_or_incomplete_stream(project, output):
    runner = execute.StepExecutor("demo")
    with (patch.object(runner, "codex_binary", return_value="/working/codex"),
          patch.object(execute, "run_supervised", return_value=subprocess.CompletedProcess([], 0, output, "")),
          pytest.raises(ValueError, match="malformed JSONL|without a completed turn|out-of-order completion")):
        runner.invoke(execute.IMPLEMENTER_MODEL, "Implement")


def test_changed_spec_invalidates_review_and_status(project):
    root, implementation, report = project
    runner = execute.StepExecutor("demo")
    runner.record_review(0, report, [implementation])
    runner.verify()
    (root / "phases" / "demo" / "step0.md").write_text("Different spec", encoding="utf-8")
    with pytest.raises(ValueError, match="specification changed"):
        runner.verify()
    assert runner.step(0)["status"] == "error"
    assert json.loads((root / "phases" / "index.json").read_text())["phases"][0]["status"] == "error"


def test_changed_acceptance_checks_invalidate_review(project):
    _, implementation, report = project
    runner = execute.StepExecutor("demo")
    runner.record_review(0, report, [implementation])
    runner.save_step(0, acceptance_checks=[["python3", "-c", "print('different')"]])
    with pytest.raises(ValueError, match="acceptance checks changed"):
        runner.verify()


def test_cannot_complete_step_out_of_order(project):
    root, implementation, report = project
    index_path = root / "phases" / "demo" / "index.json"
    index = json.loads(index_path.read_text())
    index["steps"].append({"step": 1, "name": "next-step", "status": "pending",
                           "acceptance_checks": [["python3", "-c", "print('ok')"]]})
    index_path.write_text(json.dumps(index))
    (root / "phases" / "demo" / "step1.md").write_text("Next", encoding="utf-8")
    with pytest.raises(ValueError, match="Step 0"):
        execute.StepExecutor("demo").record_review(1, report, [implementation])


def test_timeout_kills_descendants(project):
    root, _, _ = project
    marker = root / "late.txt"
    child = f"import time; time.sleep(0.7); open({str(marker)!r}, 'w').write('late')"
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(5)"
    with pytest.raises(subprocess.TimeoutExpired):
        execute.run_supervised([sys.executable, "-c", parent], timeout=0.1)
    time.sleep(0.9)
    assert not marker.exists()
