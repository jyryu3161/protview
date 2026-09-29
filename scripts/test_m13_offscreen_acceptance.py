"""Sub-runner ledger verdicts in scripts/m13_offscreen_acceptance.py (no services run here)."""

from scripts import m13_offscreen_acceptance as m13


def _m11(fail=0, missing=0, passed=17, total=0, unknown=()):
    return {"schema": "m11_case_ledger@1", "summary": {"pass": passed, "fail": fail, "missing": missing},
            "nonLoopbackRequestsTotal": total, "rowsWithUnknownRequestCount": list(unknown)}


def _m12(verdict="pass", total=0, unknown=()):
    return {"schema": "m12_case_ledger@1", "verdict": verdict, "externalRequestsTotal": total,
            "rowsWithUnknownExternalCount": list(unknown)}


def test_m11_ledger_without_verdict_field():
    assert m13.sub_ledger_verdict(_m11()) == ("pass", 0)
    assert m13.sub_ledger_verdict(_m11(fail=1)) == ("fail", 0)
    assert m13.sub_ledger_verdict(_m11(missing=1)) == ("fail", 0)
    assert m13.sub_ledger_verdict(_m11(passed=0)) == ("fail", 0)
    assert m13.sub_ledger_verdict(_m11(total=2)) == ("fail", 2)
    assert m13.sub_ledger_verdict(_m11(unknown=["row.json"])) == ("fail", None)


def test_m12_ledger_verdict_and_external_count():
    assert m13.sub_ledger_verdict(_m12()) == ("pass", 0)
    assert m13.sub_ledger_verdict(_m12("fail")) == ("fail", 0)
    assert m13.sub_ledger_verdict(_m12("partial_not_acceptance")) == ("partial_not_acceptance", 0)
    assert m13.sub_ledger_verdict(_m12(total=1)) == ("fail", 1)
    assert m13.sub_ledger_verdict(_m12(unknown=["x"])) == ("fail", None)


def test_missing_or_unknown_ledger():
    assert m13.sub_ledger_verdict(None) == (None, None)
    assert m13.sub_ledger_verdict({"schema": "other"}) == (None, None)
