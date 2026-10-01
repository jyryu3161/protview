"""Ledger judgement, environment and option rules of scripts/m17_offscreen_acceptance.py (no services run here)."""

import argparse
import ast
from pathlib import Path

import pytest

from scripts import m17_offscreen_acceptance as m17

ENV = {"workerPython": True, "mainAvailable": True, "layoutReason": "worker_missing"}
REPO = Path(m17.__file__).resolve().parents[1]


def _cases(step):
    return [case for case, modes in m17.CASE_PLAN.items() if step in modes]


def _row(step, cases=None, status="pass", external=0, provider=True):
    cases = _cases(step) if cases is None else cases
    return {"step": step, "status": status, "cases": {case: "pass" for case in cases} if isinstance(cases, list) else cases,
            "externalRequestCount": external, "providerCallsZero": provider}


def _rows():
    return [_row(step) for step in m17.FLOW_STEPS]


def _args(**override):
    values = {"root": str(REPO / "runs/m17-test-root"), "artifacts": str(REPO / "frontend/tests/offscreen/artifacts/x"),
              "out": str(REPO / "runs/m17-test-out"), "code_root": str(REPO), "build": "never"}
    return argparse.Namespace(**{**values, **override})


def test_every_spec_case_is_planned_and_covered():
    assert set(m17.CASE_PLAN) == set(m17.CASE_TEXT)
    assert all(modes and set(modes) <= set(m17.FLOW_STEPS) for modes in m17.CASE_PLAN.values())
    assert all(_cases(step) for step in m17.FLOW_STEPS)
    assert set(m17.MODE_OF) == set(m17.FLOW_STEPS)
    assert len(m17.CASE_PLAN) == 20


def test_flow_declares_every_planned_case_and_mode():
    flow = (REPO / "frontend/tests/offscreen" / m17.FLOW).read_text()
    for case in m17.CASE_PLAN:
        assert f'"{case}"' in flow, case
    for mode in m17.MODE_OF.values():
        assert f'"{mode}"' in flow, mode


def test_all_passing_rows_pass():
    judged = m17.assemble(_rows(), [], ENV)
    assert judged["passed"] is True
    assert all(value["status"] == "pass" for value in judged["cases"].values())
    assert judged["cases"]["S-no-egress"]["status"] == "pass"
    assert m17.acceptance_ok(judged["passed"], {"buildCurrentWithSource": True}) is True


def test_a_case_missing_from_its_row_fails():
    rows = _rows()
    del rows[0]["cases"]["L-paging"]
    judged = m17.assemble(rows, [], ENV)
    assert judged["cases"]["L-paging"]["status"] == "fail"
    assert judged["passed"] is False


def test_a_failed_case_fails_even_if_the_row_says_pass():
    rows = _rows()
    rows[0]["cases"]["L-candidates-oracle"] = "fail"
    judged = m17.assemble(rows, [], ENV)
    assert judged["cases"]["L-candidates-oracle"]["status"] == "fail"
    assert judged["passed"] is False


def test_missing_step_fails_its_cases_and_egress():
    judged = m17.assemble(_rows()[:1], [], ENV)
    assert judged["steps"]["ligand-unavailable"]["status"] == "missing"
    assert judged["cases"]["L-unavailable"]["status"] == "fail"
    assert judged["cases"]["S-no-egress"]["status"] == "fail"
    assert judged["passed"] is False


def test_unmeasured_or_nonzero_egress_and_provider_calls_fail():
    for bad in ({"external": None}, {"external": 1}, {"provider": None}, {"provider": False}):
        rows = _rows()
        rows[0] = _row("ligand-main", **bad)
        judged = m17.assemble(rows, [], ENV)
        assert judged["steps"]["ligand-main"]["status"] == "fail", bad
        assert judged["cases"]["S-no-egress"]["status"] == "fail", bad
        assert judged["passed"] is False


@pytest.mark.parametrize("environment", [
    {**ENV, "workerPython": False},  # no .deps/prolif/venv-locked: a failure, never "unavailable"
    {**ENV, "mainAvailable": False},
    {**ENV, "layoutReason": "available"},
    {**ENV, "layoutReason": "handshake_failed"},
    {},
])
def test_environment_must_be_present_and_the_layout_must_lack_it(environment):
    judged = m17.assemble(_rows(), [], environment)
    assert judged["verdictParts"]["environment"] is False
    assert judged["passed"] is False


def test_leftovers_and_stale_build_fail():
    judged = m17.assemble(_rows(), ["port 8000 still listening: pid 1"], ENV)
    assert judged["verdictParts"]["leftoverProcesses"] is False
    assert judged["passed"] is False
    assert m17.acceptance_ok(True, {"buildCurrentWithSource": False}) is False
    assert m17.acceptance_ok(True, None) is False
    assert m17.acceptance_ok(False, {"buildCurrentWithSource": True}) is False


def test_latest_attempt_decides():
    failed = _row("ligand-main", {case: "fail" for case in _cases("ligand-main")}, status="fail")
    retried = _row("ligand-main-20261001T120000000000", _cases("ligand-main"))
    rows = [failed, retried, _rows()[1]]
    judged = m17.assemble(rows, [], ENV)
    assert judged["steps"]["ligand-main"]["latest"] == "ligand-main-20261001T120000000000"
    assert judged["steps"]["ligand-main"]["attempts"] == 2
    assert judged["passed"] is True
    rows = [retried, _row("ligand-main-20261001T130000000000", {}, status="fail"), _rows()[1]]
    assert m17.assemble(rows, [], ENV)["passed"] is False


def test_ligand_worker_counts_as_a_leftover_worker():
    assert "ligand_worker.py" in m17.WORKERS
    assert set(m17.m13.WORKERS) <= set(m17.WORKERS)


def test_options():
    parser = m17.build_parser()
    args = parser.parse_args(["--root", "runs/r", "--artifacts", "frontend/tests/offscreen/artifacts/a"])
    assert (args.build, args.out, args.code_root) == ("auto", None, str(REPO))
    with pytest.raises(SystemExit):
        parser.parse_args(["--artifacts", "a"])  # --root is required
    with pytest.raises(SystemExit):
        parser.parse_args(["--root", "r", "--artifacts", "a", "--build", "sometimes"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--root", "r", "--artifacts", "a", "--kbase", "k"])  # no reference snapshot is used


def test_default_out_is_the_m17_qa_folder():
    runner = m17.Runner(_args(out=None))
    assert runner.out.parent.name.startswith("m17-ligand-") and runner.out.name == "acceptance"
    assert runner.out.parent.parent == REPO / "docs/qa"


@pytest.mark.parametrize("field", ["root", "artifacts", "out"])
def test_tmp_paths_are_refused(field):
    with pytest.raises(SystemExit, match="/tmp"):
        m17.Runner(_args(**{field: "/tmp/m17-qa"}))


def test_repository_runs_folder_and_tracked_artifacts_are_refused():
    with pytest.raises(SystemExit, match="fresh folder"):
        m17.Runner(_args(root=str(REPO / "runs")))
    with pytest.raises(SystemExit, match="git-ignored"):
        m17.Runner(_args(artifacts=str(REPO / "docs/qa/m17-not-ignored")))


def test_runner_never_imports_mw():
    tree = ast.parse(Path(m17.__file__).read_text())
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in names if name == "mw" or name.startswith("mw.")]
