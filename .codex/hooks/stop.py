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


PYTHON = project_python(ROOT)
T = "backend/tests/"

# The gate's script tests (docs/standards.md), all in the last group.
SCRIPT_TESTS = [
    "scripts/test_execute.py", "scripts/test_codex_hooks.py", "scripts/test_setup_fpocket.py",
    "scripts/test_m13_offscreen_acceptance.py", "scripts/test_m14_offscreen_acceptance.py",
    "scripts/test_import_reference_snapshots.py", "scripts/test_m15_offscreen_acceptance.py",
    "scripts/test_measure_klifs_numbering.py", "scripts/test_m16_offscreen_acceptance.py",
    "scripts/test_m17_offscreen_acceptance.py", "scripts/test_m18_offscreen_acceptance.py",
    "scripts/test_m19_offscreen_acceptance.py", "scripts/test_setup_qvina.py", "scripts/test_setup_docking_worker.py",
    "scripts/test_m20_offscreen_acceptance.py", "scripts/test_m21_offscreen_acceptance.py",
    "scripts/test_m22_offscreen_acceptance.py", "scripts/test_m23_offscreen_acceptance.py",
    "scripts/test_m24_offscreen_acceptance.py", "scripts/test_m25_offscreen_acceptance.py",
    "scripts/test_import_reaction_references.py", "scripts/test_m26_offscreen_acceptance.py",
    "scripts/test_import_precedent_snapshots.py", "scripts/test_m27_offscreen_acceptance.py",
    "scripts/test_m28_offscreen_acceptance.py", "scripts/test_m28_branch_a.py",
    "scripts/test_m28_branch_b.py", "scripts/test_m28_branch_c.py",
]

# test_sequence_ga_jobs.py alone takes about 540 s, more than one group's bound, so its tests are split by node id.
SEQUENCE_GA_JOBS = T + "test_sequence_ga_jobs.py"
SEQUENCE_GA_JOBS_LONG = [
    "test_product_path_publication_m18_identity_reuse_duplicates_and_events_only",
    "test_golden_m18_m19_m21_call_keys_results_and_hashed_files_are_unchanged",
]
SEQUENCE_GA_JOBS_OTHER = [
    "test_registration_capability_and_protocol_timeout_bound",
    "test_admission_order_refusals_record_and_charge_nothing",
    "test_dry_run_plans_only",
    "test_set_model_receptor_source_needs_publication_evidence",
    "test_a_failed_reference_row_ends_the_run_before_any_individual_with_a_summary",
    "test_cancel_mid_run_keeps_published_rows_and_a_partial_summary",
    "test_a_cancel_before_the_reference_row_is_recorded_has_no_summary",
    "test_run_budget_deadline_is_time_exhausted_with_a_partial_summary",
    "test_hard_kill_of_the_worker_is_worker_failed_and_has_no_retry",
    "test_server_death_recovery_publishes_staged_rows_and_a_worker_failed_summary",
    "test_contradicting_staged_files_fail_fatal_or_worker_failed",
    "test_a_prepared_box_that_is_not_the_servers_is_fatal_before_any_object_is_published",
]

# Disjoint pytest groups balanced on measured per-file time (docs/operations.md). A file is named in one group only;
# a split file names each of its tests in exactly one group. The last group is backend/tests without every file
# named here, plus the script tests, so a new backend test file lands there.
PYTEST_GROUPS = [
    [T + "test_chemical_interactions.py"],
    [T + "test_m11_job_api.py"],
    [T + "test_docking_inputs.py", T + "test_docking_worker.py", T + "test_docking_jobs.py",
     T + "test_docking_api.py", T + "test_docking_reports.py", T + "test_pocket_jobs.py"],
    [T + "test_docking_batch_worker.py", T + "test_docking_batch_jobs.py",
     T + "test_pockets.py", T + "test_pocket_reports.py", T + "test_pocket_output.py"],
    [T + "test_docking_batch_inputs.py", T + "test_docking_batch_bundle.py", T + "test_docking_batch_budget.py",
     T + "test_docking_batch_api.py", T + "test_docking_batch_reports.py",
     T + "test_ligand_ga_bundle.py", T + "test_ligand_ga_inputs.py", T + "test_ligand_ga_budget.py",
     T + "test_ligand_ga_api.py", T + "test_ligand_ga_reports.py"],
    [T + "test_ligand_ga_jobs.py"],
    [T + "test_ligand_ga_worker.py"],
    [f"{SEQUENCE_GA_JOBS}::{name}" for name in SEQUENCE_GA_JOBS_LONG],
    [f"{SEQUENCE_GA_JOBS}::{name}" for name in SEQUENCE_GA_JOBS_OTHER],
    [T + "test_sequence_ga_api.py"],
    [T + "test_sequence_ga_reports.py"],
    [T + "test_sequence_ga_worker.py", T + "test_sequence_model_worker.py", T + "test_sequence_ga_inputs.py",
     T + "test_sequence_ga_budget.py", T + "test_sequence_ga_bundle.py", T + "test_sequence_model_bundle.py"],
    [T + "test_mutation_model_worker.py", T + "test_mutation_model_jobs.py", T + "test_mutation_model_inputs.py",
     T + "test_mutation_model_api.py", T + "test_mutation_model_pairs.py", T + "test_mutation_model_docking.py",
     T + "test_mutation_model_reports.py", T + "test_openmm.py"],
    [T + "test_jev_loops_read.py", T + "test_jev_loop_sends.py", T + "test_jev_loop_tool.py",
     T + "test_jev_loop_choice.py", T + "test_jev_loops_api.py"],
    [T + "test_jev_loops_compute.py"],
    [T + "test_precedent_constants.py", T + "test_precedent_snapshots.py", T + "test_kinase_precedents.py",
     T + "test_kinase_precedents_tool.py", T + "test_kinase_precedents_api.py",
     T + "test_kinase_precedents_reports.py", T + "test_kinase_precedents_ast.py"],
    [T + "test_analysis_workflows.py", T + "test_jev_loop_reports.py"],
    # M29 structure repair job lane: real PDBFixer worker processes (8VF6 about 25-35 s alone); T8b downstream reads:
    # real repair, M21 and qvina workers on 1UBQ (about 55 s alone; the rest group is near its bound).
    [T + "test_structure_repair_jobs.py", T + "test_structure_repair_lane.py", T + "test_structure_repair_worker.py",
     T + "test_structure_repair_downstream_reads.py"],
]


def named_files(groups) -> list[str]:
    files = []
    for args in groups:
        for arg in args:
            path = arg.split("::", 1)[0]
            if path not in files:
                files.append(path)
    return files


REST_GROUP = ["backend/tests", *SCRIPT_TESTS, *(f"--ignore={path}" for path in named_files(PYTEST_GROUPS))]

# Only check product and harness code; references/ is source material.
CHECKS = [
    ([PYTHON, "-m", "ruff", "check", "backend/mw", "backend/tests", "scripts", ".codex/hooks", "design/build_tokens.py"], {0}),
    *(([PYTHON, "-m", "pytest", "-q", *args], {0}) for args in [*PYTEST_GROUPS, REST_GROUP]),
]

MAX_OUTPUT_CHARS = 1500
MAX_LABEL_CHARS = 600
# Ruff runs first; the disjoint pytest groups then all run concurrently.
# Their exact collection union is the gate's backend and script tests. Even one
# group reaching its bound leaves process-group cleanup below the trusted 600 s hook.
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
        if len(label) > MAX_LABEL_CHARS:  # the last group lists every --ignore; its first arguments name it
            label = label[:MAX_LABEL_CHARS] + " …"
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
        with ThreadPoolExecutor(max_workers=len(CHECKS) - 1) as executor:
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
