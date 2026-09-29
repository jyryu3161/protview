"""Ledger judgement and acceptance rules of scripts/m14_offscreen_acceptance.py (no services run here)."""

from scripts import m14_offscreen_acceptance as m14

MAIN_CASES = [case for case, modes in m14.CASE_PLAN.items() if "tabs-main" in modes]
CHEM_CASES = [case for case, modes in m14.CASE_PLAN.items() if "tabs-chemical" in modes]


def _row(step, cases, status="pass", external=0, provider=True):
    return {"step": step, "status": status, "cases": {case: "pass" for case in cases} if isinstance(cases, list) else cases,
            "externalRequestCount": external, "providerCallsZero": provider}


def _rows():
    return [_row("tabs-main", MAIN_CASES), _row("tabs-chemical", CHEM_CASES)]


def test_every_spec_case_is_planned_and_covered():
    assert set(m14.CASE_PLAN) == set(m14.CASE_TEXT)
    assert all(modes and set(modes) <= set(m14.TAB_STEPS) for modes in m14.CASE_PLAN.values())
    assert len(m14.CASE_PLAN) == 14


def test_all_passing_rows_pass():
    judged = m14.assemble(_rows(), m14.TAB_STEPS, [])
    assert judged["passed"] is True
    assert all(value["status"] == "pass" for value in judged["cases"].values())
    assert judged["cases"]["S-no-egress"]["status"] == "pass"


def test_a_case_missing_from_a_covering_row_fails():
    rows = _rows()
    del rows[1]["cases"]["T-global-run"]  # covered by both modes: the chemical row must report it too
    judged = m14.assemble(rows, m14.TAB_STEPS, [])
    assert judged["cases"]["T-global-run"]["status"] == "fail"
    assert judged["passed"] is False


def test_missing_step_fails_its_cases():
    judged = m14.assemble(_rows()[:1], m14.TAB_STEPS, [])
    assert judged["steps"]["tabs-chemical"]["status"] == "missing"
    assert judged["cases"]["T-chemical-preserved"]["status"] == "fail"
    assert judged["passed"] is False


def test_unmeasured_or_nonzero_egress_and_provider_calls_fail():
    for bad in ({"external": None}, {"external": 1}, {"provider": None}, {"provider": False}):
        rows = [_row("tabs-main", MAIN_CASES, **bad), _row("tabs-chemical", CHEM_CASES)]
        judged = m14.assemble(rows, m14.TAB_STEPS, [])
        assert judged["steps"]["tabs-main"]["status"] == "fail", bad
        assert judged["cases"]["S-no-egress"]["status"] == "fail", bad
        assert judged["passed"] is False


def test_product_issue_and_leftovers_fail():
    rows = _rows()
    rows[0]["cases"]["P-panel_busy_after_create_execution"] = "fail"
    assert m14.assemble(rows, m14.TAB_STEPS, [])["cases"]["P-panel_busy_after_create_execution"]["status"] == "fail"
    judged = m14.assemble(_rows(), m14.TAB_STEPS, ["port 8000 still listening: pid 1"])
    assert judged["verdictParts"]["leftoverProcesses"] is False
    assert judged["passed"] is False


def test_latest_attempt_decides():
    failed = _row("tabs-main", {case: "fail" for case in MAIN_CASES}, status="fail")
    retried = _row("tabs-main-20260929T120000000000", MAIN_CASES)
    judged = m14.assemble([failed, retried, _rows()[1]], m14.TAB_STEPS, [])
    assert judged["steps"]["tabs-main"]["latest"] == "tabs-main-20260929T120000000000"
    assert judged["steps"]["tabs-main"]["attempts"] == 2
    assert judged["passed"] is True
    judged = m14.assemble([retried, _row("tabs-main-20260929T130000000000", {}, status="fail"), _rows()[1]],
                          m14.TAB_STEPS, [])
    assert judged["passed"] is False


def test_acceptance_needs_the_tabs_phase_complete_and_passed():
    assert m14.acceptance_ok(False, ["tabs", "ledger"], True) is True
    assert m14.acceptance_ok(False, ["tabs", "ledger"], False) is False
    assert m14.acceptance_ok(True, ["tabs", "ledger"], True) is False  # --only is partial
    assert m14.acceptance_ok(False, ["ledger"], True) is False
