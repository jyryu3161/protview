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


def test_acceptance_needs_every_phase_to_have_run_and_passed():
    full = ["workflows", "unavailable", "regressions", "m11", "m12", "ledger"]
    assert m13.acceptance_ok(False, full, True) is True
    assert m13.acceptance_ok(False, full, False) is False
    assert m13.acceptance_ok(True, full, True) is False
    assert m13.acceptance_ok(False, ["workflows", "unavailable", "ledger"], True) is False  # the default phases
    assert m13.acceptance_ok(False, [p for p in full if p != "m12"], True) is False


def _frontend(tmp_path):
    front = tmp_path / "frontend"
    for name, text in {"src/lib/a.ts": "a", "app/page.tsx": "p", "package.json": "{}", "next.config.mjs": "",
                       "tests/x.test.cjs": "t"}.items():
        (front / name).parent.mkdir(parents=True, exist_ok=True)
        (front / name).write_text(text)
    return front


def test_existing_build_is_reused_only_when_built_from_the_current_source(tmp_path):
    front = _frontend(tmp_path)
    assert m13.build_is_current(front) is False  # no build at all
    (front / ".next").mkdir()
    (front / ".next/BUILD_ID").write_text("abc")
    assert m13.build_is_current(front) is False  # built outside the runner: source unknown
    m13.stamp_build(front)
    assert m13.build_is_current(front) is True
    (front / "tests/x.test.cjs").write_text("changed")  # not a build input
    assert m13.build_is_current(front) is True
    (front / "src/lib/a.ts").write_text("changed")
    assert m13.build_is_current(front) is False
    m13.stamp_build(front)
    (front / "src/lib/new.ts").write_text("n")
    assert m13.build_is_current(front) is False
