"""Ledger judgement and acceptance rules of scripts/m16_offscreen_acceptance.py (no services run here)."""

import argparse
import ast
from pathlib import Path

import pytest

from scripts import m16_offscreen_acceptance as m16

REFERENCE = {"reference-import": {"status": "pass", "setHash": "a" * 64}}


def _cases(step):
    return [case for case, modes in m16.CASE_PLAN.items() if step in modes]


def _row(step, cases=None, status="pass", external=0, provider=True):
    cases = _cases(step) if cases is None else cases
    return {"step": step, "status": status, "cases": {case: "pass" for case in cases} if isinstance(cases, list) else cases,
            "externalRequestCount": external, "providerCallsZero": provider}


def _rows():
    return [_row(step) for step in m16.FLOW_STEPS]


def test_every_spec_case_is_planned_and_covered():
    assert set(m16.CASE_PLAN) == set(m16.CASE_TEXT)
    assert all(modes and set(modes) <= set(m16.FLOW_STEPS) for modes in m16.CASE_PLAN.values())
    assert all(_cases(step) for step in m16.FLOW_STEPS)
    assert set(m16.MODE_OF) == set(m16.FLOW_STEPS)
    assert len(m16.CASE_PLAN) == 18


def test_flow_declares_every_planned_case():
    flow = (Path(m16.__file__).resolve().parents[1] / "frontend/tests/offscreen" / m16.FLOW).read_text()
    for case in m16.CASE_PLAN:
        assert f'"{case}"' in flow, case


def test_all_passing_rows_pass():
    judged = m16.assemble(_rows(), [], REFERENCE)
    assert judged["passed"] is True
    assert all(value["status"] == "pass" for value in judged["cases"].values())
    assert m16.acceptance_ok(judged["passed"], {"buildCurrentWithSource": True}) is True


def test_a_case_missing_from_its_row_fails():
    rows = _rows()
    del rows[0]["cases"]["A-figure-pixels"]
    judged = m16.assemble(rows, [], REFERENCE)
    assert judged["cases"]["A-figure-pixels"]["status"] == "fail"
    assert judged["passed"] is False


def test_a_failed_case_fails_even_if_the_row_says_pass():
    rows = _rows()
    rows[0]["cases"]["A-show-readback"] = "fail"
    judged = m16.assemble(rows, [], REFERENCE)
    assert judged["cases"]["A-show-readback"]["status"] == "fail"
    assert judged["passed"] is False


def test_missing_step_fails_its_cases_and_egress():
    judged = m16.assemble(_rows()[:1], [], REFERENCE)
    assert judged["steps"]["annotation-minimized"]["status"] == "missing"
    assert judged["cases"]["B-minimized"]["status"] == "fail"
    assert judged["cases"]["S-no-egress"]["status"] == "fail"
    assert judged["passed"] is False


def test_unmeasured_or_nonzero_egress_and_provider_calls_fail():
    for bad in ({"external": None}, {"external": 1}, {"provider": None}, {"provider": False}):
        rows = _rows()
        rows[0] = _row("annotation-main", **bad)
        judged = m16.assemble(rows, [], REFERENCE)
        assert judged["steps"]["annotation-main"]["status"] == "fail", bad
        assert judged["cases"]["S-no-egress"]["status"] == "fail", bad
        assert judged["passed"] is False


def test_reference_import_must_pass_with_a_hash():
    for reference in ({}, {"reference-import": {"status": "fail", "setHash": None}},
                      {"reference-import": {"status": "pass", "setHash": None}}):
        judged = m16.assemble(_rows(), [], reference)
        assert judged["verdictParts"]["reference"] is False, reference
        assert judged["passed"] is False


def test_leftovers_and_stale_build_fail():
    judged = m16.assemble(_rows(), ["port 8000 still listening: pid 1"], REFERENCE)
    assert judged["verdictParts"]["leftoverProcesses"] is False
    assert judged["passed"] is False
    assert m16.acceptance_ok(True, {"buildCurrentWithSource": False}) is False
    assert m16.acceptance_ok(True, None) is False
    assert m16.acceptance_ok(False, {"buildCurrentWithSource": True}) is False


def test_latest_attempt_decides():
    failed = _row("annotation-main", {case: "fail" for case in _cases("annotation-main")}, status="fail")
    retried = _row("annotation-main-20261001T120000000000", _cases("annotation-main"))
    rows = [failed, retried, _rows()[1]]
    judged = m16.assemble(rows, [], REFERENCE)
    assert judged["steps"]["annotation-main"]["latest"] == "annotation-main-20261001T120000000000"
    assert judged["steps"]["annotation-main"]["attempts"] == 2
    assert judged["passed"] is True
    rows = [retried, _row("annotation-main-20261001T130000000000", {}, status="fail"), _rows()[1]]
    assert m16.assemble(rows, [], REFERENCE)["passed"] is False


@pytest.mark.parametrize("field", ["root", "artifacts", "out"])
def test_tmp_paths_are_refused(tmp_path, field):
    repo = Path(m16.__file__).resolve().parents[1]
    values = {"root": str(repo / "runs/m16-test-root"), "artifacts": str(repo / "frontend/tests/offscreen/artifacts/x"),
              "out": str(repo / "runs/m16-test-out"), field: "/tmp/m16-qa"}
    args = argparse.Namespace(code_root=str(repo), kbase=str(repo.parent / "kbase_kinase"), build="never", **values)
    with pytest.raises(SystemExit, match="/tmp"):
        m16.Runner(args)


def test_runner_never_imports_mw():
    tree = ast.parse(Path(m16.__file__).read_text())
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in names if name == "mw" or name.startswith("mw.")]
