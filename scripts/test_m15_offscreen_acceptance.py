"""Ledger judgement and acceptance rules of scripts/m15_offscreen_acceptance.py (no services run here)."""

import ast
from pathlib import Path

from scripts import m15_offscreen_acceptance as m15

REFERENCE = {"reference-import": {"status": "pass", "setHash": "a" * 64},
             "reference-reimport": {"status": "pass", "setHash": "b" * 64}}


def _cases(step):
    return [case for case, modes in m15.CASE_PLAN.items() if step in modes]


def _row(step, cases=None, status="pass", external=0, provider=True):
    cases = _cases(step) if cases is None else cases
    return {"step": step, "status": status, "cases": {case: "pass" for case in cases} if isinstance(cases, list) else cases,
            "externalRequestCount": external, "providerCallsZero": provider}


def _rows():
    return [_row(step) for step in m15.FLOW_STEPS]


def test_every_spec_case_is_planned_and_covered():
    assert set(m15.CASE_PLAN) == set(m15.CASE_TEXT)
    assert all(modes and set(modes) <= set(m15.FLOW_STEPS) for modes in m15.CASE_PLAN.values())
    assert all(_cases(step) for step in m15.FLOW_STEPS)
    assert len(m15.CASE_PLAN) == 13


def test_all_passing_rows_pass():
    judged = m15.assemble(_rows(), [], REFERENCE)
    assert judged["passed"] is True
    assert all(value["status"] == "pass" for value in judged["cases"].values())
    assert m15.acceptance_ok(judged["passed"], {"buildCurrentWithSource": True}) is True


def test_a_case_missing_from_its_row_fails():
    rows = _rows()
    del rows[1]["cases"]["N-klifs-oracle"]
    judged = m15.assemble(rows, [], REFERENCE)
    assert judged["cases"]["N-klifs-oracle"]["status"] == "fail"
    assert judged["passed"] is False


def test_missing_step_fails_its_cases_and_egress():
    judged = m15.assemble(_rows()[:2], [], REFERENCE)
    assert judged["steps"]["numbering-stale"]["status"] == "missing"
    assert judged["cases"]["N-stale"]["status"] == "fail"
    assert judged["cases"]["S-no-egress"]["status"] == "fail"
    assert judged["passed"] is False


def test_unmeasured_or_nonzero_egress_and_provider_calls_fail():
    for bad in ({"external": None}, {"external": 1}, {"provider": None}, {"provider": False}):
        rows = _rows()
        rows[1] = _row("numbering-main", **bad)
        judged = m15.assemble(rows, [], REFERENCE)
        assert judged["steps"]["numbering-main"]["status"] == "fail", bad
        assert judged["cases"]["S-no-egress"]["status"] == "fail", bad
        assert judged["passed"] is False


def test_reference_changes_must_both_pass_with_different_hashes():
    for reference in ({}, {**REFERENCE, "reference-reimport": {"status": "fail", "setHash": None}},
                      {**REFERENCE, "reference-reimport": {"status": "pass", "setHash": "a" * 64}},
                      {"reference-reimport": REFERENCE["reference-reimport"]}):
        judged = m15.assemble(_rows(), [], reference)
        assert judged["verdictParts"]["reference"] is False, reference
        assert judged["passed"] is False


def test_leftovers_and_stale_build_fail():
    judged = m15.assemble(_rows(), ["port 8000 still listening: pid 1"], REFERENCE)
    assert judged["verdictParts"]["leftoverProcesses"] is False
    assert judged["passed"] is False
    assert m15.acceptance_ok(True, {"buildCurrentWithSource": False}) is False
    assert m15.acceptance_ok(True, None) is False
    assert m15.acceptance_ok(False, {"buildCurrentWithSource": True}) is False


def test_latest_attempt_decides():
    failed = _row("numbering-main", {case: "fail" for case in _cases("numbering-main")}, status="fail")
    retried = _row("numbering-main-20260930T120000000000", _cases("numbering-main"))
    rows = [_rows()[0], failed, retried, _rows()[2]]
    judged = m15.assemble(rows, [], REFERENCE)
    assert judged["steps"]["numbering-main"]["latest"] == "numbering-main-20260930T120000000000"
    assert judged["steps"]["numbering-main"]["attempts"] == 2
    assert judged["passed"] is True
    rows = [_rows()[0], retried, _row("numbering-main-20260930T130000000000", {}, status="fail"), _rows()[2]]
    assert m15.assemble(rows, [], REFERENCE)["passed"] is False


def test_runner_never_imports_mw():
    tree = ast.parse(Path(m15.__file__).read_text())
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in names if name == "mw" or name.startswith("mw.")]
