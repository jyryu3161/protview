"""Judgement, ledger, evidence and trace-audit rules of the M28 runner modules (no service is started here).

Covers scripts/m28_common.py, scripts/m28_offscreen_acceptance.py, scripts/m28_trace_audit.py and
scripts/m28_export_fixed_sentences.py with synthetic input (.dryforge/spec.md §3.1, §3.3, §5, §6.2, §6.3, §7).
"""

import argparse
import ast
import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest

from scripts import m27_offscreen_acceptance as m27
from scripts import m28_common as c
from scripts import m28_offscreen_acceptance as m28
from scripts import m28_trace_audit as audit

REPO = Path(m28.__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
PYTHON = sys.executable
RID = "run_" + "1" * 32
OTHER = "run_" + "2" * 32
H = {name: f"{index:064x}" for index, name in enumerate(
    ("report", "markdown", "map", "set", "mut", "react", "prec", "inter", "prep", "sasa", "dist", "x", "y"), 1)}
SET = "a" * 64
REACTION_SET = "b" * 64
PRECEDENT_SET = "c" * 64
DONE = "검증 통과, 사용자 확인 대기"
USER_PATH = "/" + "Users/alice/protview/x"          # a made-up user path (built, not written)


# ---------------------------------------------------------------------------------------------------- helpers
def _all(status="pass", phase="fixture"):
    return {case_id: c.case_record(case_id, status) for case_id in (c.FIXTURE_CASES if phase == "fixture"
                                                                    else c.LIVE_CASES)}


def _judge(cases=None, phase="fixture", branches=None, **override):
    values = {"build": {"buildCurrentWithSource": True}, "leftover": {"processes": [], "ports": []},
              "runs_claimed": True,
              "external": ({"browser_non_loopback_requests": 0, "provider_calls": 0, "live_calls_counted": None}
                           if phase == "fixture" else
                           {"browser_non_loopback_requests": 0, "provider_calls": None, "live_calls_counted": 2}),
              "export_ok": True, "rehearsal": False}
    values.update(override)
    return m28.judge_phase(phase, _all(phase=phase) if cases is None else cases,
                           list(m28.PHASE_BRANCHES[phase]) if branches is None else branches, **values)


def _statuses(**changes):
    statuses = {case_id: "pass" for case_id in c.FIXTURE_CASES}
    statuses.update(changes)
    return statuses


@pytest.fixture
def inputs(tmp_path):
    kbase = tmp_path / "kbase"
    (kbase / "dist").mkdir(parents=True)
    (kbase / "dist/manifest.json").write_text("{}")
    sets = {}
    for name in ("m15", "reaction"):
        folder = tmp_path / name
        (folder / "sets" / ("e" * 64)).mkdir(parents=True)
        (folder / "sets" / ("e" * 64) / "manifest.json").write_text("{}")
        (folder / "active.json").write_text(json.dumps({"set_hash": "e" * 64}))
        sets[name] = str(folder)
    return {"kbase": str(kbase), "m15_reference": sets["m15"], "reaction_set": sets["reaction"]}


def _args(inputs, tmp_path, **override):
    values = {"root": str(tmp_path / "root"), "artifacts": str(REPO / "frontend/tests/offscreen/artifacts/m28-unit"),
              "out": str(tmp_path / "out"), "code_root": str(REPO), "build": "never", "phase": "fixture",
              "branches": None, "live_calls": None, "rehearse": False, **inputs}
    values.update(override)
    return argparse.Namespace(**values)


# ---------------------------------------------------------------------------------------------------- case records
def test_case_catalogue_matches_the_spec():
    assert len(c.FIXTURE_CASES) == 31 and len(set(c.FIXTURE_CASES)) == 31
    assert c.LIVE_CASES == ("L-pre-B2", "L-pre-B3", "L-pre-B4", "L-pre-C2", "L-B7", "L-C6", "L-X3", "L-X4", "L-X6")
    assert c.CASE_BRANCH["X1-A"] == "a" and c.CASE_BRANCH["X2"] == "x" and c.CASE_BRANCH["L-pre-C2"] == "c"
    assert c.CASE_BRANCH["L-B7"] == "b" and c.CASE_BRANCH["L-X3"] == "x" and c.CASE_BRANCH["C7"] == "c"
    chained = {case for item in c.DEFINITION_ITEMS.values() for chain in item["parts"].values() for case in chain}
    assert chained - set(c.FIXTURE_CASES) == {"L-B7", "L-C6"}
    assert set(c.FIXTURE_CASES) - chained == {"B1", "X3", "X4", "X5", "X6"}      # required, but in no item chain
    assert c.CASE_ITEMS["A6"] == [1, 2, 6] and c.CASE_ITEMS["X2"] == [6] and c.CASE_ITEMS["L-C6"] == [5]
    assert c.DEFINITION_ITEMS[2]["parts"] == {"kinase": ["A5", "A6", "A7"], "enzyme": ["A8"]}
    assert c.DEFINITION_ITEMS[4]["parts"] == {"protection": ["C1"], "modelling": ["C2", "C3"]}
    assert c.DEFINITION_ITEMS[5]["parts"]["live"] == ["L-B7", "L-C6"]


@pytest.mark.parametrize("reason", c.ALLOWED_UNOBSERVED)
def test_allowed_not_observed_reasons_need_a_named_covering_test(reason):
    with pytest.raises(ValueError, match="covering"):
        c.case_record("A8", "not_observed", reason)
    record = c.case_record("A8", "not_observed", reason, covering_tests=["backend/tests/test_x.py::test_y"])
    assert record["definition_items"] == [2, 6] and c.reason_class(reason) == "allowed"


@pytest.mark.parametrize("reason,kind", [
    ("prerequisite_failed:A1", "prerequisite"), ("not_sent:earlier_provider_failed", "not_sent"),
    ("not_sent:earlier_product_failed", "not_sent"), ("not_sent:ledger_refused", "not_sent"),
    ("not_sent:prerequisite_failed:L-pre-B3", "not_sent"), ("prerequisite_failed:ZZ9", "invalid"),
    ("not_sent:because", "invalid"), ("skipped", "invalid"), ("", "invalid"), (None, "invalid")])
def test_not_observed_reasons_are_a_closed_list(reason, kind):
    assert c.reason_class(reason) == kind
    if kind == "invalid":
        with pytest.raises(ValueError):
            c.case_record("A2", "not_observed", reason, covering_tests=["t"])
    else:
        assert c.case_record("A2", "not_observed", reason)["reason"] == reason


@pytest.mark.parametrize("args", [("ZZ", "pass"), ("A1", "skip"), ("A1", "pass", "no_public_input")])
def test_invalid_case_records_are_refused(args):
    with pytest.raises(ValueError):
        c.case_record(*args)


def test_cascade_marks_unrun_dependents_prerequisite_failed_and_keeps_reported_cases():
    records = {"A1": c.case_record("A1", "fail")}
    done = c.cascade(records, c.FIXTURE_CASES)
    assert done["A2"]["status"] == "not_observed" and done["A2"]["reason"] == "prerequisite_failed:A1"
    assert done["A5"]["reason"] == "prerequisite_failed:A1"
    assert done["A6"]["reason"] == "prerequisite_failed:A1"
    assert done["A7"]["reason"] == "prerequisite_failed:A5"           # the chain: A1 → A5 → A7
    assert "A8" not in done and "B1" not in done                     # no prerequisite: left to the caller
    kept = c.cascade({"A1": c.case_record("A1", "fail"), "A2": c.case_record("A2", "pass")}, c.FIXTURE_CASES)
    assert kept["A2"]["status"] == "pass"                            # it ran: its state existed
    live = c.cascade({"L-pre-B2": c.case_record("L-pre-B2", "fail")}, c.LIVE_CASES)
    assert live["L-pre-B3"]["reason"] == "prerequisite_failed:L-pre-B2"
    assert live["L-pre-B4"]["reason"] == "prerequisite_failed:L-pre-B3"
    assert live["L-B7"]["reason"] == "prerequisite_failed:L-pre-B2"


def test_the_cascade_follows_the_stored_state_each_case_uses():
    """R3 / R5: B4 uses B3's receptor, parent and docking values and B7's two docked candidates, B5 B3's values, C6
    the C3 docking of the modelled candidate; B8 / C7 list the reports of every earlier case of the branch."""
    assert c.PREREQUISITES["B4"] == ("B2", "B3", "B7") and c.PREREQUISITES["B5"] == ("B2", "B3")
    assert c.PREREQUISITES["B8"] == ("B1", "B2", "B3", "B4", "B5", "B6", "B7")
    assert c.PREREQUISITES["C6"] == ("C2", "C3") and c.PREREQUISITES["C7"] == ("C1", "C2", "C3", "C4", "C5", "C6")
    passed = {case: c.case_record(case, "pass") for case in ("B1", "B2", "B4", "B5", "B6", "B8")}
    done = c.cascade({**passed, "B3": c.case_record("B3", "fail")}, c.FIXTURE_CASES)
    assert done["B4"]["status"] == "pass"                            # reported: it ran
    done = c.cascade({"B1": passed["B1"], "B2": passed["B2"], "B3": c.case_record("B3", "fail")}, c.FIXTURE_CASES)
    assert {case: done[case]["reason"] for case in ("B4", "B5", "B7", "B8")} == {
        "B4": "prerequisite_failed:B3", "B5": "prerequisite_failed:B3", "B7": "prerequisite_failed:B3",
        "B8": "prerequisite_failed:B3"}
    done = c.cascade({case: c.case_record(case, "pass") for case in ("B1", "B2", "B3", "B5", "B6")}
                     | {"B7": c.case_record("B7", "fail")}, c.FIXTURE_CASES)
    assert done["B4"]["reason"] == "prerequisite_failed:B7" and done["B8"]["reason"] == "prerequisite_failed:B4"
    done = c.cascade({"C2": c.case_record("C2", "pass"), "C3": c.case_record("C3", "fail")}, c.FIXTURE_CASES)
    assert done["C6"]["reason"] == "prerequisite_failed:C3" and "C4" not in done   # C4 needs C2 only
    assert done["C7"]["reason"] == "prerequisite_failed:C1"


def test_complete_cases_fails_an_unreported_case_and_cascades():
    cases = m28.complete_cases("fixture", {"A1": c.case_record("A1", "pass")})
    assert list(cases) == list(c.FIXTURE_CASES)
    assert cases["A2"]["status"] == "fail" and cases["A2"]["reason"] == "case_not_reported"
    assert cases["A7"]["reason"] == "prerequisite_failed:A5"
    assert not m28.judge_phase("fixture", cases, ["a", "b", "c"], build={"buildCurrentWithSource": True},
                               leftover={}, external={"browser_non_loopback_requests": 0, "provider_calls": 0},
                               export_ok=True)["acceptance"]


# ---------------------------------------------------------------------------------------------------- items
def test_combine_statuses():
    assert c.combine_statuses(["pass", "pass"]) == "pass"
    assert c.combine_statuses(["pass", "not_observed"]) == "not_observed"
    assert c.combine_statuses(["not_observed", "fail", "pass"]) == "fail"
    assert c.combine_statuses([]) == "not_observed" and c.combine_statuses(["pass", None]) == "not_observed"


def test_all_pass_gives_every_item_pass_and_item_5_pending_live():
    items = c.definition_items(_statuses(), "fixture")
    assert [items[str(n)]["status"] for n in range(1, 7)] == ["pass", "pass", "pass", "pass", "pending_live", "pass"]
    assert items["5"]["parts"] == {"ligand": "pass", "protein": "pass", "live": None}


@pytest.mark.parametrize("case,status,expect", [
    ("A1", "fail", {"1": "fail"}), ("A4", "fail", {"1": "fail", "6": "fail"}),
    ("A6", "fail", {"1": "fail", "2": "fail", "6": "fail"}),
    ("A8", "not_observed", {"2": "not_observed", "6": "not_observed"}), ("A7", "fail", {"2": "fail", "6": "fail"}),
    ("B3", "fail", {"3": "fail"}), ("B4", "not_observed", {"3": "not_observed"}), ("C1", "fail", {"4": "fail"}),
    ("C3", "not_observed", {"4": "not_observed"}), ("B6", "fail", {"5": "fail"}), ("C4", "not_observed",
                                                                                   {"5": "not_observed"}),
    ("B8", "fail", {"6": "fail"}), ("X1-B", "fail", {"6": "fail"}), ("X2", "not_observed", {"6": "not_observed"}),
    ("B1", "fail", {}), ("X5", "fail", {})])
def test_one_case_changes_exactly_its_items(case, status, expect):
    items = c.definition_items(_statuses(**{case: status}), "fixture")
    base = {"1": "pass", "2": "pass", "3": "pass", "4": "pass", "5": "pending_live", "6": "pass"}
    assert {number: item["status"] for number, item in items.items()} == {**base, **expect}


def test_items_2_and_4_need_both_halves():
    items = c.definition_items(_statuses(A8="fail"), "fixture")
    assert items["2"]["parts"] == {"kinase": "pass", "enzyme": "fail"} and items["2"]["status"] == "fail"
    items = c.definition_items(_statuses(C2="fail"), "fixture")
    assert items["4"]["parts"] == {"protection": "pass", "modelling": "fail"} and items["4"]["status"] == "fail"


def test_live_ledger_items_and_the_combined_items():
    live = c.definition_items({"L-B7": "pass", "L-C6": "pass"}, "live")
    assert live["5"]["status"] == "pass" and all(live[n]["status"] is None for n in "12346")
    final = c.combine_items(c.definition_items(_statuses(), "fixture"), live)
    assert {n: item["status"] for n, item in final.items()} == {str(n): "pass" for n in range(1, 7)}
    unseen = c.combine_items(c.definition_items(_statuses(), "fixture"),
                             c.definition_items({"L-B7": "pass", "L-C6": "not_observed"}, "live"))
    assert unseen["5"]["status"] == "not_observed"
    missing = c.combine_items(c.definition_items(_statuses(), "fixture"), {})
    assert missing["5"]["status"] == "not_observed"
    assert {v["status"] for v in final.values()} <= {"pass", "fail", "not_observed"}


# ---------------------------------------------------------------------------------------------------- acceptance
def test_every_case_pass_and_every_part_true_is_acceptance():
    judged = _judge()
    assert judged["acceptance"] is True and all(judged["parts"].values())


@pytest.mark.parametrize("branches", [["a"], ["a", "b"], ["b", "c"], ["c"]])
def test_a_partial_branch_run_is_never_acceptance(branches):
    assert _judge(branches=branches)["acceptance"] is False


@pytest.mark.parametrize("override,part", [
    ({"build": {"buildCurrentWithSource": False}}, "buildStamped"), ({"build": None}, "buildStamped"),
    ({"leftover": {"processes": ["123 qvina2"], "ports": []}}, "nothingLeft"),
    ({"leftover": {"processes": [], "ports": ["port 8000 still listening: pid 1"]}}, "nothingLeft"),
    ({"external": {"browser_non_loopback_requests": 1, "provider_calls": 0}}, "external"),
    ({"external": {"browser_non_loopback_requests": None, "provider_calls": 0}}, "external"),
    ({"external": {"browser_non_loopback_requests": 0, "provider_calls": None}}, "external"),
    ({"export_ok": False}, "exportChecks")])
def test_each_part_blocks_acceptance(override, part):
    judged = _judge(**override)
    assert judged["acceptance"] is False and judged["parts"][part] is False


def test_allowed_not_observed_keeps_acceptance_but_not_the_item():
    cases = _all()
    cases["A8"] = c.case_record("A8", "not_observed", "no_public_input", covering_tests=["backend/tests/t.py::t"])
    assert _judge(cases)["acceptance"] is True
    statuses = {case_id: record["status"] for case_id, record in cases.items()}
    assert c.definition_items(statuses, "fixture")["2"]["status"] == "not_observed"


@pytest.mark.parametrize("case,record", [
    ("A2", c.case_record("A2", "not_observed", "prerequisite_failed:A1")),
    ("B2", c.case_record("B2", "fail")),
    ("X2", c.case_record("X2", "not_observed", "unreachable_by_ui", covering_tests=["t"])),
    ("X5", c.case_record("X5", "fail", "no_observation")),
    ("B1", c.case_record("B1", "fail")),
    ("A3", {"id": "A3", "status": "not_observed", "reason": "no_public_input", "covering_tests": []})])
def test_blocking_cases_refuse_acceptance(case, record):
    cases = _all()
    cases[case] = record
    assert _judge(cases)["acceptance"] is False


def test_live_acceptance_and_rehearsal():
    assert _judge(phase="live")["acceptance"] is True
    over = {"browser_non_loopback_requests": 0, "provider_calls": None, "live_calls_counted": 3}
    assert _judge(phase="live", external=over)["acceptance"] is False
    clean = {"browser_non_loopback_requests": 0, "provider_calls": 0, "live_calls_counted": 2,
             "product_key_resolver_calls": 0}
    rehearsal = _judge(phase="live", rehearsal=True, external=clean)
    assert rehearsal["acceptance"] is False and rehearsal["rehearsalPassed"] is True
    real_calls = _judge(phase="live", rehearsal=True, external={**clean, "provider_calls": None})
    assert real_calls["rehearsalPassed"] is False
    for resolver in (1, None):                      # a rehearsal never runs the product key resolver (T8 / T9)
        assert _judge(phase="live", rehearsal=True, external={**clean, "product_key_resolver_calls": resolver})[
            "rehearsalPassed"] is False
    cases = _all(phase="live")
    cases["L-C6"] = c.case_record("L-C6", "not_observed", "not_sent:earlier_provider_failed")
    assert _judge(cases, phase="live")["acceptance"] is False
    assert _judge(phase="live", branches=["b"])["acceptance"] is False


def test_the_ledger_shape():
    cases = m28.complete_cases("fixture", {case: record for case, record in _all().items()})
    ledger = m28.assemble_ledger("fixture", cases, ["a", "b", "c"], build={"buildCurrentWithSource": True},
                                 leftover={"processes": [], "ports": []},
                                 external={"browser_non_loopback_requests": 0, "provider_calls": 0,
                                           "live_calls_counted": None},
                                 trace_audit={"status": "pass", "failures": [], "reportCount": 3, "_markdown": {}},
                                 export_ok=True, source_head="abc", dirty_files=[" M x"], runs_claimed=True)
    assert ledger["schema"] == "m28_case_ledger@1" and ledger["acceptance"] is True and ledger["phase"] == "fixture"
    assert {"source_head", "dirty_files", "cases", "definition_items", "external", "leftover", "trace_audit",
            "unobserved"} <= set(ledger)
    assert set(ledger["external"]) >= {"browser_non_loopback_requests", "provider_calls", "live_calls_counted"}
    assert set(ledger["leftover"]) == {"processes", "ports"} and "_markdown" not in ledger["trace_audit"]
    first = ledger["cases"][0]
    assert set(first) >= {"id", "branch", "definition_items", "status", "reason", "evidence_refs"}
    assert ledger["definition_items"]["5"]["status"] == "pending_live"
    json.dumps(ledger)


# ---------------------------------------------------------------------------------------------------- live §6.3
def test_live_results_both_completed():
    out = c.live_outcome({"L-B7": "completed", "L-C6": "completed"})
    assert out["cases"] == {"L-B7": ("pass", None), "L-C6": ("pass", None)}
    assert out["item5Live"] == "pass" and out["verdict"] is None and out["waivable"] is False


@pytest.mark.parametrize("results,causes,expect", [
    ({"L-B7": "provider_failed"}, {"L-C6": "earlier_provider_failed"},
     {"L-B7": ("fail", "provider_failed"), "L-C6": ("not_observed", "not_sent:earlier_provider_failed")}),
    ({"L-B7": "completed", "L-C6": "provider_failed"}, {},
     {"L-B7": ("pass", None), "L-C6": ("fail", "provider_failed")})])
def test_live_provider_failed_is_a_waivable_hold(results, causes, expect):
    out = c.live_outcome(results, causes)
    assert out["cases"] == expect and out["item5Live"] == "fail" and out["verdict"] == "보류"
    assert out["waivable"] is True and any("실모델 미관찰" in line for line in out["closing"])


@pytest.mark.parametrize("results,causes", [
    ({"L-B7": "product_failed"}, {"L-C6": "earlier_product_failed"}),
    ({"L-B7": "completed", "L-C6": "product_failed"}, {}),
    ({"L-B7": "provider_failed", "L-C6": "product_failed"}, {})])
def test_live_product_failed_is_never_waived(results, causes):
    out = c.live_outcome(results, causes)
    assert out["verdict"] == "보류" and out["waivable"] is False and out["item5Live"] == "fail"
    assert any(status == "fail" and reason == "product_failed" for status, reason in out["cases"].values())
    assert any("never waived" in line for line in out["closing"])


def test_live_not_sent_after_a_prerequisite_is_not_observed():
    out = c.live_outcome({}, {"L-B7": "prerequisite_failed:L-pre-B3", "L-C6": "prerequisite_failed:L-pre-C2"})
    assert out["cases"]["L-B7"] == ("not_observed", "not_sent:prerequisite_failed:L-pre-B3")
    assert out["item5Live"] == "not_observed" and out["verdict"] == "보류" and out["waivable"] is False
    assert any("allocation again" in line for line in out["closing"])


@pytest.mark.parametrize("result,cause", [("timeout", None), ("not_sent", None), ("not_sent", "who_knows")])
def test_live_results_outside_the_closed_set_raise(result, cause):
    with pytest.raises(ValueError):
        c.live_case_status(result, not_sent_cause=cause)


def test_next_round_cause():
    assert c.next_round_cause("provider_failed") == "earlier_provider_failed"
    assert c.next_round_cause("product_failed") == "earlier_product_failed"
    assert c.next_round_cause("completed") is None


def _ledgers(fixture_change=None, live_results=("completed", "completed"), live_causes=None):
    fixture = _all()
    fixture.update(fixture_change or {})
    fixture_ledger = {"acceptance": all(r["status"] == "pass" for r in fixture.values()),
                      "cases": list(fixture.values()),
                      "definition_items": c.definition_items({k: v["status"] for k, v in fixture.items()}, "fixture")}
    out = c.live_outcome(dict(zip(c.LIVE_ROUNDS, live_results)), live_causes)
    live = _all(phase="live")
    for round_id, (status, reason) in out["cases"].items():
        live[round_id] = c.case_record(round_id, status, reason)
    live_ledger = {"acceptance": all(r["status"] == "pass" for r in live.values()), "cases": list(live.values()),
                   "definition_items": c.definition_items({k: v["status"] for k, v in live.items()}, "live")}
    return fixture_ledger, live_ledger


def test_verdict_values_and_hold_reasons():
    fixture, live = _ledgers()
    assert m28.verdict(fixture, live, review_passed=True, user_decision_defects=False)["verdict"] == DONE
    assert m28.verdict(fixture, live, review_passed=False, user_decision_defects=False)["verdict"] == "보류"
    held = m28.verdict(fixture, live, review_passed=True, user_decision_defects=True)
    assert held["verdict"] == "보류" and any(r.startswith("(b)") for r in held["reasons"])
    fixture, live = _ledgers({"B1": c.case_record("B1", "fail")})
    held = m28.verdict(fixture, live, review_passed=True, user_decision_defects=False)
    assert any(r.startswith("(c)") for r in held["reasons"])
    fixture, live = _ledgers({"A3": c.case_record("A3", "fail")})
    assert any(r.startswith("(a)") for r in m28.verdict(fixture, live, review_passed=True,
                                                        user_decision_defects=False)["reasons"])
    for results, causes in ((("provider_failed", "not_sent"), {"L-C6": "earlier_provider_failed"}),
                            (("product_failed", "not_sent"), {"L-C6": "earlier_product_failed"}),
                            (("not_sent", "not_sent"), {"L-B7": "prerequisite_failed:L-pre-B2",
                                                        "L-C6": "prerequisite_failed:L-pre-C2"})):
        fixture, live = _ledgers(live_results=results, live_causes=causes)
        held = m28.verdict(fixture, live, review_passed=True, user_decision_defects=False)
        assert held["verdict"] == "보류" and any(r.startswith("(d)") for r in held["reasons"])
        assert held["items"]["5"]["status"] in ("fail", "not_observed")


def test_the_runner_never_writes_the_user_confirmed_value():
    forbidden = [re.compile("완성" + r"\(범위 명시\)"), re.compile("M28" + r"[ ]*(완료|완성)")]
    for path in (SCRIPTS / "m28_common.py", SCRIPTS / "m28_offscreen_acceptance.py", SCRIPTS / "m28_trace_audit.py",
                 SCRIPTS / "m28_export_fixed_sentences.py", Path(__file__)):
        text = path.read_text(encoding="utf-8")
        assert not any(rule.search(text) for rule in forbidden), path


# ---------------------------------------------------------------------------------------------------- live ledger
def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "runs").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text("runs/\n")
    return repo


def test_ledger_place_is_the_main_checkout_runs_folder_and_never_the_m24_m25_ledgers(tmp_path):
    repo = _git_repo(tmp_path)
    old = {name: repo / "runs" / name for name in ("m24-live-ledger.json", "m25-live-ledger.json")}
    old["m24-live-ledger.json"].write_text("{not json")
    old["m25-live-ledger.json"].write_text(json.dumps({"schema": "m25_live_ledger@1", "roots": {
        "/x": {"phases": [], "dispatch": {"run_a": 8}}}}))
    before = {name: (path.read_bytes(), path.stat().st_mtime_ns) for name, path in old.items()}
    path = m28.ledger_path(repo)
    assert path == (repo / "runs" / "m28-live-ledger.json").resolve()
    ledger = m28.read_ledger(path)
    assert ledger == {"schema": "m28_live_ledger@1", "roots": {}} and m28.ledger_total(ledger) == 0
    assert m28.ledger_admission(0, 0, 2, 2) is None
    assert {name: (p.read_bytes(), p.stat().st_mtime_ns) for name, p in old.items()} == before
    (repo / ".gitignore").write_text("")
    with pytest.raises(m28.LedgerError, match="not git-ignored"):
        m28.ledger_path(repo)


def test_runner_source_never_reaches_the_old_ledgers():
    source = (SCRIPTS / "m28_offscreen_acceptance.py").read_text() + (SCRIPTS / "m28_common.py").read_text()
    for name in ("m24-live-ledger", "m25-live-ledger", "m25.ledger_path", "m25.read_ledger", "m25.ledger_total",
                 "m25.root_count", "m25.LEDGER_NAME", "m25.ledger_admission", "m24_offscreen_acceptance"):
        assert name not in source, name


@pytest.mark.parametrize("text", ["{", "[]", json.dumps({"schema": "m25_live_ledger@1", "roots": {}}),
                                  json.dumps({"schema": "m28_live_ledger@1", "roots": {"relative": {
                                      "phases": [], "dispatch": {}}}}),
                                  json.dumps({"schema": "m28_live_ledger@1", "roots": {"/r": {
                                      "phases": [{"phase": "calibrate", "startedAt": "t", "finishedAt": "t"}],
                                      "dispatch": {}}}}),
                                  json.dumps({"schema": "m28_live_ledger@1", "roots": {"/r": {
                                      "phases": [], "dispatch": {"run_a": -1}}}})])
def test_an_unreadable_or_damaged_ledger_is_refused(tmp_path, text):
    path = tmp_path / "m28-live-ledger.json"
    path.write_text(text)
    with pytest.raises(m28.LedgerError):
        m28.read_ledger(path)


def test_ledger_counts_and_admission(tmp_path):
    root = tmp_path / "root-a"
    runs = root / m28.LIVE_RUNS / "run_x"
    runs.mkdir(parents=True)
    (runs / "events.jsonl").write_text(json.dumps({"type": "jev_science_dispatch_started", "seq": 1}) + "\n"
                                       + json.dumps({"type": "jev_science_dispatch_started", "seq": 2}) + "\n")
    finished = {"phases": [{"phase": "live", "startedAt": "t", "finishedAt": "t"}], "dispatch": {"run_x": 1}}
    assert m28.root_count(str(root), finished) == 2                  # events recounted: the larger
    unfinished = {"phases": [{"phase": "live", "startedAt": "t", "finishedAt": None, "planned": 2}], "dispatch": {}}
    assert m28.root_count(str(tmp_path / "gone"), {"phases": [], "dispatch": {"run_y": 1}}) == 1
    with pytest.raises(m28.LedgerError):
        m28.root_count(str(tmp_path / "gone"), unfinished)
    assert m28.root_count(str(root), unfinished) == 2
    assert m28.ledger_admission(2, 0, 2, 2) is not None              # the ledger is full
    assert m28.ledger_admission(1, 0, 2, 2) is not None              # 1 + 2 > 2
    assert m28.ledger_admission(0, 0, 2, 1) is not None              # the plan passes --live-calls
    assert m28.ledger_admission(0, 1, 1, 2) is None
    assert m28.ledger_admission(1, 0, 1, 2) is not None              # --live-calls passes what is left


@pytest.mark.parametrize("text", ["0", "3", "-1", "two"])
def test_live_calls_argument_is_1_to_2(text):
    with pytest.raises(argparse.ArgumentTypeError):
        m28.live_calls_arg(text)
    assert m28.live_calls_arg("2") == 2 and m28.live_calls_arg("1") == 1


def test_live_plan_fits_the_run_defaults():
    plan = m28.live_plan_budget()
    assert plan["ok"] and plan["planned"] == 2 and plan["needs"]["B"]["expensive_units"] == 8
    assert plan["needs"]["C"]["expensive_units"] <= 8 and plan["needs"]["B"]["sends"] == 1
    assert not m28.live_plan_budget([*m28.LIVE_PLAN, {"id": "x", "run": "B", "branch": "ligand", "sends": 1}])["ok"]


def test_rehearsal_ledger_guard_and_close(inputs, tmp_path):
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", rehearse=True))
    runner.artifacts = tmp_path / "artifacts"
    runner.artifacts.mkdir()
    runner.ledger_guard()
    ledger = json.loads((runner.root / m28.REHEARSAL_LEDGER_NAME).read_text())
    entry = ledger["roots"][str(runner.root)]
    assert entry["phases"][0]["finishedAt"] is None and entry["phases"][0]["planned"] == 2
    assert runner.ledger_close() == 0 and runner.ledger_close() is None
    closed = json.loads((runner.root / m28.REHEARSAL_LEDGER_NAME).read_text())["roots"][str(runner.root)]
    assert closed["phases"][0]["finishedAt"] is not None
    assert runner.checks["liveLedger"]["ok"] is True


def test_ledger_guard_refuses_when_full_or_unreadable(inputs, tmp_path, monkeypatch):
    full = tmp_path / "full-ledger.json"
    full.write_text(json.dumps({"schema": "m28_live_ledger@1", "roots": {str(tmp_path / "old"): {
        "phases": [{"phase": "live", "startedAt": "t", "finishedAt": "t"}], "dispatch": {"run_a": 2}}}}))
    monkeypatch.setattr(m28.Runner, "ledger_location", lambda self: full)
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=2))
    with pytest.raises(SystemExit, match="refused, nothing started"):
        runner.ledger_guard()
    assert json.loads(full.read_text())["roots"].keys() == {str(tmp_path / "old")}
    full.write_text("{broken")
    with pytest.raises(SystemExit, match="refused, nothing started"):
        runner.ledger_guard()
    assert not runner.root.exists()


def test_the_live_plan_counts_the_selected_branches_only(monkeypatch):
    assert [entry["id"] for entry in m28.live_plan(["b"])] == ["L-B7"]
    assert [entry["id"] for entry in m28.live_plan(["c"])] == ["L-C6"]
    assert [entry["id"] for entry in m28.live_plan(["b", "c"])] == ["L-B7", "L-C6"]
    assert m28.live_plan() == m28.LIVE_PLAN
    assert m28.live_plan_budget(m28.live_plan(["b"]))["planned"] == 1
    assert m28.live_plan_budget(m28.live_plan(["c"]))["planned"] == 1
    both = m28.live_plan_budget(m28.live_plan(["b", "c"]))
    assert both == m28.live_plan_budget() and both["planned"] == 2          # the default plan is unchanged
    # The default is read when called (it used to be bound when the function was defined).
    monkeypatch.setattr(m28, "LIVE_PLAN", m28.LIVE_PLAN[:1])
    assert m28.live_plan_budget()["planned"] == 1 and m28.live_plan(["b", "c"]) == m28.LIVE_PLAN[:1]


@pytest.mark.parametrize("branches,live_calls,planned", [(["b"], 1, 1), (["c"], 1, 1), (["b", "c"], 2, 2),
                                                         (["b"], 2, 1)])
def test_a_one_branch_rehearsal_plans_one_call(inputs, tmp_path, branches, live_calls, planned):
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", rehearse=True, branches=branches,
                              live_calls=live_calls))
    runner.artifacts = tmp_path / "artifacts"
    runner.artifacts.mkdir()
    runner.ledger_guard()
    entry = json.loads((runner.root / m28.REHEARSAL_LEDGER_NAME).read_text())["roots"][str(runner.root)]
    assert entry["phases"][0]["planned"] == planned == runner.checks["liveLedger"]["planned"]
    runner.ledger_close()


def test_both_branches_with_one_live_call_are_refused(inputs, tmp_path):
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", rehearse=True, live_calls=1))
    with pytest.raises(SystemExit, match="plans 2 calls but --live-calls is 1"):
        runner.ledger_guard()


@pytest.mark.parametrize("recorded,branches,live_calls,refused", [
    (2, ["b"], None, True), (1, ["b", "c"], None, True), (1, ["c"], 1, False), (1, ["c"], 2, True)])
def test_the_rehearsal_ledger_keeps_the_cap_of_two(inputs, tmp_path, recorded, branches, live_calls, refused):
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", rehearse=True, branches=branches,
                              live_calls=live_calls))
    runner.artifacts = tmp_path / "artifacts"
    runner.artifacts.mkdir()
    runner.root.mkdir(parents=True, exist_ok=True)
    other = str(tmp_path / "earlier-root")
    (runner.root / m28.REHEARSAL_LEDGER_NAME).write_text(json.dumps({"schema": "m28_live_ledger@1", "roots": {
        other: {"phases": [{"phase": "live", "startedAt": "t", "finishedAt": "t"}],
                "dispatch": {"run_a": recorded}}}}))
    if refused:
        with pytest.raises(SystemExit, match="refused, nothing started"):
            runner.ledger_guard()
        assert set(json.loads((runner.root / m28.REHEARSAL_LEDGER_NAME).read_text())["roots"]) == {other}
    else:
        runner.ledger_guard()
        runner.ledger_close()
    (runner.root / m28.REHEARSAL_LEDGER_NAME).write_text("{unreadable")
    with pytest.raises(SystemExit, match="refused, nothing started"):
        runner.ledger_guard()


def test_a_rehearsal_never_runs_the_product_key_resolver(inputs, tmp_path, monkeypatch):
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", rehearse=True))

    def refuse(*args, **kwargs):
        raise AssertionError("the product key resolver ran in a rehearsal")
    monkeypatch.setattr(m28.subprocess, "run", refuse)
    runner.records = []
    monkeypatch.setattr(m28.Runner, "record", lambda self, step, status, **extra: self.records.append(
        (step, status, extra)))
    assert runner.key_present() is True
    assert runner.checks["key"] == {"skipped": "rehearsal", "rehearsal": True}
    assert runner.records == [("key-present", "pass", {"skipped": "rehearsal"})]
    folder = tmp_path / "scan"
    folder.mkdir()
    (folder / "clean.txt").write_text("nothing here")
    scan = runner.key_scan([folder])
    assert scan["ok"] is True and scan["keySearch"] == "skipped: rehearsal" and runner.resolver_calls == 0
    (folder / "leak.txt").write_text(m28.SENTINELS[0])
    assert runner.key_scan([folder])["sentinelHits"] == [str(folder / "leak.txt")]
    assert runner.resolver_calls == 0


def test_the_real_live_phase_counts_its_key_resolver_runs(inputs, tmp_path, monkeypatch):
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=2))

    class Done:
        returncode, stdout = 0, json.dumps({"keyAvailable": True, "files": 0, "hits": {"key": [], "sentinel": []}})
    monkeypatch.setattr(m28.subprocess, "run", lambda *a, **k: Done())
    assert runner.key_scan([])["keyAvailable"] is True and runner.resolver_calls == 1


# ---------------------------------------------------------------------------------------------------- runner options
@pytest.mark.parametrize("field", ["root", "artifacts", "out"])
def test_tmp_paths_are_refused(inputs, tmp_path, field):
    for bad in ("/tmp/m28-qa", "/private/tmp/m28-qa"):
        with pytest.raises(SystemExit, match="/tmp"):
            m28.Runner(_args(inputs, tmp_path, **{field: bad}))


def test_runner_option_rules(inputs, tmp_path):
    used = tmp_path / "used"
    used.mkdir()
    (used / "x").write_text("x")
    with pytest.raises(SystemExit, match="not new"):
        m28.Runner(_args(inputs, tmp_path, root=str(used)))
    with pytest.raises(SystemExit, match="git-ignored"):
        m28.Runner(_args(inputs, tmp_path, artifacts=str(REPO / "docs/qa/m28-not-ignored")))
    with pytest.raises(SystemExit, match="rehearses the live phase"):
        m28.Runner(_args(inputs, tmp_path, rehearse=True))
    with pytest.raises(SystemExit, match="needs --live-calls"):
        m28.Runner(_args(inputs, tmp_path, phase="live"))
    with pytest.raises(SystemExit, match="belongs to the live phase"):
        m28.Runner(_args(inputs, tmp_path, live_calls=2))
    with pytest.raises(SystemExit, match="has no branch"):
        m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=2, branches=["a", "b"]))
    with pytest.raises(SystemExit, match="m15-reference"):
        m28.Runner(_args({**inputs, "m15_reference": str(tmp_path / "none")}, tmp_path))
    with pytest.raises(SystemExit, match="dist/manifest.json"):
        m28.Runner(_args({**inputs, "kbase": str(tmp_path / "none")}, tmp_path))
    m28.Runner(_args({**inputs, "kbase": str(tmp_path / "none")}, tmp_path, branches=["b", "c"]))
    with pytest.raises(SystemExit, match="reaction-set"):
        m28.Runner(_args({**inputs, "reaction_set": str(tmp_path / "none")}, tmp_path, branches=["c"]))
    m28.Runner(_args({**inputs, "reaction_set": str(tmp_path / "none")}, tmp_path, branches=["b"]))
    rehearsal = m28.Runner(_args(inputs, tmp_path, phase="live", rehearse=True, out=None))
    assert rehearsal.live_calls == 2 and rehearsal.out == rehearsal.root / "out-live-rehearsal"
    assert rehearsal.branches == ["b", "c"]


def test_branches_argument():
    assert m28.branches_arg("c,a") == ["a", "c"] and m28.branches_arg("a,b,c") == ["a", "b", "c"]
    for bad in ("", "d", "a,a", "a,,x"):
        with pytest.raises(argparse.ArgumentTypeError):
            m28.branches_arg(bad)


def test_phase_folders_and_default_out(inputs, tmp_path):
    runner = m28.Runner(_args(inputs, tmp_path, out=None))
    assert runner.runs == runner.root / "fixture/runs" and runner.reference == runner.root / "fixture/reference"
    assert runner.precedent == runner.root / "fixture/precedent_reference"
    assert runner.reaction == runner.root / "fixture/reaction_reference"
    assert re.fullmatch(r"m28-final-\d{8}", runner.out.parent.name) and runner.out.name == "acceptance-fixture"
    env = runner.backend_env()
    assert env["MW_RUNS_DIR"] == str(runner.runs) and env["MW_REACTION_REFERENCE_DIR"] == str(runner.reaction)
    assert env["MW_PRECEDENT_REFERENCE_DIR"] == str(runner.precedent) and "OPENROUTER_API_KEY" not in env


def test_prepared_folders_are_read_only_copies(inputs, tmp_path):
    runner = m28.Runner(_args(inputs, tmp_path))
    before = {p: p.read_bytes() for p in Path(inputs["reaction_set"]).rglob("*") if p.is_file()}
    runner.prepare_folders()
    assert runner.checks["m15"]["status"] == "pass" and runner.checks["reaction"]["status"] == "pass"
    assert not (runner.reaction / "active.json").stat().st_mode & 0o222
    assert runner.precedent.is_dir() and not any(runner.precedent.iterdir())
    assert {p: p.read_bytes() for p in Path(inputs["reaction_set"]).rglob("*") if p.is_file()} == before


def test_the_registry_holds_the_three_branch_modules_and_an_unregistered_branch_fails(inputs, tmp_path,
                                                                                    monkeypatch):
    assert m28.BRANCH_REGISTRY == {"a": m28.branch_a.run, "b": m28.branch_b.run, "c": m28.branch_c.run}
    assert [Path(module.__file__).name for module in (m28.branch_a, m28.branch_b, m28.branch_c)] == [
        "m28_branch_a.py", "m28_branch_b.py", "m28_branch_c.py"]
    monkeypatch.setattr(m28, "BRANCH_REGISTRY", {})
    runner = m28.Runner(_args(inputs, tmp_path))
    runner.artifacts = tmp_path / "artifacts"
    runner.artifacts.mkdir()
    result = runner.run_branch("a")
    assert result.cases == [] and result.notes["error"] == "branch_module_not_registered"
    runner.results = {"a": result}
    cases = m28.complete_cases("fixture", runner.branch_records())
    assert (cases["A1"]["status"], cases["A1"]["reason"]) == ("fail", "case_not_reported")
    assert (cases["A2"]["status"], cases["A2"]["reason"]) == ("not_observed", "prerequisite_failed:A1")
    assert cases["B1"]["status"] == "fail" and "X2" in cases


def test_live_rounds_come_from_the_result_values(inputs, tmp_path):
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=2))
    pre = [c.case_record(case, "pass") for case in ("L-pre-B2", "L-pre-B3", "L-pre-B4")]
    runner.results = {"b": c.BranchResult(cases=[*pre, c.case_record("L-B7", "pass")],
                                          live={"L-B7": "provider_failed"}),
                      "c": c.BranchResult(cases=[c.case_record("L-pre-C2", "pass")],
                                          not_sent_causes={"L-C6": "earlier_provider_failed"})}
    records = runner.branch_records()
    assert (records["L-B7"]["status"], records["L-B7"]["reason"]) == ("fail", "provider_failed")
    assert records["L-C6"]["reason"] == "not_sent:earlier_provider_failed"
    assert runner.checks["liveOutcome"]["waivable"] is True
    runner.results = {"b": c.BranchResult(cases=[c.case_record("L-pre-B2", "fail")])}
    records = runner.branch_records()
    assert records["L-B7"]["reason"] == "not_sent:prerequisite_failed:L-pre-B2"
    # the plan ended at L-B7 (spec §6.1): L-C6 names that round, never ledger_refused or its own prerequisite only
    assert records["L-C6"]["reason"] == "not_sent:prerequisite_failed:L-B7"
    assert records["L-B7"]["status"] == records["L-C6"]["status"] == "not_observed"


def test_the_live_flow_is_capped_by_the_runner(inputs, tmp_path, monkeypatch):
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=2))
    runner.artifacts = tmp_path / "artifacts"
    seen = {}

    def watch(proc, runs, limit, timeout):
        seen["limit"] = limit
        proc.wait()
        return 0, None
    real_popen = subprocess.Popen
    monkeypatch.setattr(m28.m25, "watch_process", watch)
    monkeypatch.setattr(m28.subprocess, "Popen", lambda *a, **k: real_popen([PYTHON, "-c", "0"]))
    runner.flow("step", "x.cjs", "m", [], limit=None)
    assert seen["limit"] == 2
    runner.flow("step", "x.cjs", "m", [], limit=1)
    assert seen["limit"] == 1
    events = runner.runs / "run_b"
    events.mkdir(parents=True)
    (events / "events.jsonl").write_text(json.dumps({"type": "jev_science_dispatch_started"}) + "\n")
    runner.send_allowed = False                      # the plan ended: any new dispatch stops the harness
    runner.flow("step", "x.cjs", "m", [], limit=None)
    assert seen["limit"] == 1 and runner.context("c").send_allowed is False


def test_a_dispatched_round_that_did_not_complete_ends_the_plan(inputs, tmp_path):
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=2))
    pre = [c.case_record(case, "pass") for case in ("L-pre-B2", "L-pre-B3", "L-pre-B4")]
    for first, cause in (("provider_failed", "earlier_provider_failed"), ("product_failed", "earlier_product_failed")):
        runner.results = {"b": c.BranchResult(cases=pre, live={"L-B7": first}),
                          "c": c.BranchResult(cases=[c.case_record("L-pre-C2", "pass")])}
        records = runner.branch_records()
        assert records["L-C6"]["reason"] == f"not_sent:{cause}"
    runner.results = {"b": c.BranchResult(cases=pre, live={"L-B7": "completed"}),
                      "c": c.BranchResult(cases=[c.case_record("L-pre-C2", "fail")])}
    assert runner.branch_records()["L-C6"]["reason"] == "not_sent:prerequisite_failed:L-pre-C2"


# ---------------------------------------------------------------------------------------------------- T11 (review)
@pytest.mark.parametrize("branches", [["b"], ["c"]])
def test_a_real_live_phase_refuses_a_branch_subset(inputs, tmp_path, branches):
    """R1: the real live phase always plans both rounds (spec §6.1); a subset is for the rehearsal only."""
    with pytest.raises(SystemExit, match="rehearsal only"):
        m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=2, branches=branches))
    with pytest.raises(SystemExit, match="rehearsal only"):
        m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=1, branches=branches))
    rehearsal = m28.Runner(_args(inputs, tmp_path, phase="live", rehearse=True, live_calls=1, branches=branches))
    assert rehearsal.branches == branches and rehearsal.live_cap == 1
    full = m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=2))
    assert full.branches == ["b", "c"] and full.live_cap == 2


@pytest.mark.parametrize("branches,live_calls", [(["b"], 2), (["c"], 2), (["b"], 1), (["b", "c"], 2)])
def test_the_runtime_cap_is_the_reservation(inputs, tmp_path, monkeypatch, branches, live_calls):
    """R1: the calls an unfinished phase reserves in the ledger are the calls its harnesses may make (a second runner
    can never pass the allocation through the gap between the two)."""
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", rehearse=True, branches=branches,
                              live_calls=live_calls))
    runner.artifacts = tmp_path / "artifacts"
    runner.artifacts.mkdir()
    runner.ledger_guard()
    reserved = json.loads((runner.root / m28.REHEARSAL_LEDGER_NAME).read_text())["roots"][str(runner.root)][
        "phases"][0]["planned"]
    seen = {}

    def watch(proc, runs, limit, timeout):
        seen["limit"] = limit
        proc.wait()
        return 0, None
    real_popen = subprocess.Popen
    monkeypatch.setattr(m28.m25, "watch_process", watch)
    monkeypatch.setattr(m28.subprocess, "Popen", lambda *a, **k: real_popen([PYTHON, "-c", "0"]))
    runner.flow("step", "x.cjs", "m", [], limit=None)
    assert seen["limit"] == reserved == len(branches) == runner.live_cap
    assert runner.context(branches[0]).live_calls == reserved
    runner.ledger_close()


def test_a_real_live_ledger_reserves_both_rounds(inputs, tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setattr(m28.Runner, "ledger_location", lambda self: ledger)
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=2))
    runner.artifacts = tmp_path / "artifacts"
    runner.artifacts.mkdir()
    runner.ledger_guard()
    phase = json.loads(ledger.read_text())["roots"][str(runner.root)]["phases"][0]
    assert phase["planned"] == 2 == runner.live_cap and phase["liveCalls"] == 2


def _dispatch(runs, run="run_aa", count=1):
    folder = Path(runs) / run
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "events.jsonl").open("a") as out:
        for _ in range(count):
            out.write(json.dumps({"type": "jev_science_dispatch_started"}) + "\n")


def _live_runner(inputs, tmp_path, monkeypatch, b_run, c_run, rehearse=True, branches=None):
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", rehearse=rehearse, branches=branches,
                              live_calls=None if rehearse else 2))
    runner.artifacts = tmp_path / "artifacts"
    runner.artifacts.mkdir()
    runner.runs.mkdir(parents=True)
    monkeypatch.setattr(m28, "BRANCH_REGISTRY", {"b": b_run, "c": c_run})
    return runner


def test_a_branch_that_raised_after_its_dispatch_is_product_failed_and_ends_the_plan(inputs, tmp_path, monkeypatch):
    """R2: the dispatch events decide whether a round was sent, not the harness's own report."""
    allowed = []

    def b_run(ctx):
        _dispatch(ctx.runs, "run_bb")
        raise RuntimeError("the harness died after the send")

    def c_run(ctx):
        allowed.append(ctx.send_allowed)
        return c.BranchResult(cases=[c.case_record("L-pre-C2", "pass")])
    runner = _live_runner(inputs, tmp_path, monkeypatch, b_run, c_run)
    runner.run_branches()
    assert allowed == [False] and runner.send_allowed is False
    records = runner.branch_records()
    assert (records["L-B7"]["status"], records["L-B7"]["reason"]) == ("fail", "product_failed")
    assert records["L-C6"]["reason"] == "not_sent:earlier_product_failed"
    assert runner.checks["liveOutcome"]["dispatched"] == {"L-B7": 1, "L-C6": 0}


def test_a_dispatched_round_without_evidence_is_product_failed(inputs, tmp_path, monkeypatch):
    pre = [c.case_record(case, "pass") for case in ("L-pre-B2", "L-pre-B3", "L-pre-B4")]
    allowed = []

    def b_run(ctx):
        _dispatch(ctx.runs, "run_bb")
        return c.BranchResult(cases=pre)                    # no live result although an event shows the send

    def c_run(ctx):
        allowed.append(ctx.send_allowed)
        _dispatch(ctx.runs, "run_cc")                       # a harness that sent although the plan had ended
        return c.BranchResult(cases=[c.case_record("L-pre-C2", "pass")], live={"L-C6": "not_sent"},
                              not_sent_causes={"L-C6": "ledger_refused"})
    runner = _live_runner(inputs, tmp_path, monkeypatch, b_run, c_run)
    runner.run_branches()
    assert allowed == [False]
    records = runner.branch_records()
    assert (records["L-B7"]["status"], records["L-B7"]["reason"]) == ("fail", "product_failed")
    assert (records["L-C6"]["status"], records["L-C6"]["reason"]) == ("fail", "product_failed")


def _c_branch(allowed, dispatches=1):
    """A C branch the way m28_branch_c.run behaves: it sends (one dispatch, completed) only when allowed."""
    def c_run(ctx):
        allowed.append(ctx.send_allowed)
        if not ctx.send_allowed:
            return c.BranchResult(cases=[c.case_record("L-pre-C2", "pass")])     # the runner names the cause
        _dispatch(ctx.runs, "run_cc", dispatches)
        return c.BranchResult(cases=[c.case_record("L-pre-C2", "pass")], live={"L-C6": "completed"})
    return c_run


@pytest.mark.parametrize("rehearse", [True, False])
def test_no_dispatch_and_no_result_is_not_sent_and_ends_the_plan(inputs, tmp_path, monkeypatch, rehearse):
    """BLOCKING 2: a ligand round that was not sent (here the branch died before the send) ends the plan: C sends
    nothing and L-C6 is not_sent:prerequisite_failed:L-B7."""
    allowed = []

    def b_run(ctx):
        raise RuntimeError("the harness died before the send")
    runner = _live_runner(inputs, tmp_path, monkeypatch, b_run, _c_branch(allowed), rehearse=rehearse)
    runner.run_branches()
    assert allowed == [False] and runner.send_allowed is False
    assert m28.m25.dispatch_total(m28.m25.count_events(runner.runs)) == 0
    records = runner.branch_records()
    assert (records["L-B7"]["status"], records["L-B7"]["reason"]) == ("not_observed",
                                                                     "not_sent:prerequisite_failed:L-pre-B2")
    assert (records["L-C6"]["status"], records["L-C6"]["reason"]) == ("not_observed",
                                                                     "not_sent:prerequisite_failed:L-B7")


@pytest.mark.parametrize("rehearse", [True, False])
def test_a_failed_ligand_prerequisite_sends_nothing_in_branch_c(inputs, tmp_path, monkeypatch, rehearse):
    """BLOCKING 2: L-pre-B4 failed (e.g. a unit shortfall), so L-B7 was not_sent; C must not use a real call."""
    allowed = []
    pre = [c.case_record("L-pre-B2", "pass"), c.case_record("L-pre-B3", "pass"), c.case_record("L-pre-B4", "fail")]

    def b_run(ctx):
        return c.BranchResult(cases=[*pre, c.case_record("L-B7", "not_observed",
                                                         "not_sent:prerequisite_failed:L-pre-B4")],
                              live={"L-B7": "not_sent"}, not_sent_causes={"L-B7": "prerequisite_failed:L-pre-B4"})
    runner = _live_runner(inputs, tmp_path, monkeypatch, b_run, _c_branch(allowed), rehearse=rehearse)
    runner.run_branches()
    assert allowed == [False] and m28.m25.dispatch_total(m28.m25.count_events(runner.runs)) == 0
    records = runner.branch_records()
    assert records["L-B7"]["reason"] == "not_sent:prerequisite_failed:L-pre-B4"
    assert records["L-C6"]["reason"] == "not_sent:prerequisite_failed:L-B7"
    assert c.reason_class(records["L-C6"]["reason"]) == "not_sent"


def test_only_a_completed_ligand_round_with_one_dispatch_lets_c_send(inputs, tmp_path, monkeypatch):
    allowed = []

    def b_run(ctx):
        _dispatch(ctx.runs, "run_bb")
        return c.BranchResult(cases=[c.case_record(case, "pass") for case in ("L-pre-B2", "L-pre-B3", "L-pre-B4")],
                              live={"L-B7": "completed"})
    runner = _live_runner(inputs, tmp_path, monkeypatch, b_run, _c_branch(allowed))
    runner.run_branches()
    records = runner.branch_records()
    assert allowed == [True] and records["L-B7"]["status"] == records["L-C6"]["status"] == "pass"


@pytest.mark.parametrize("b_dispatches,c_dispatches", [(0, 1), (2, 1), (1, 0), (1, 2)])
def test_a_round_counts_only_with_exactly_one_dispatch(inputs, tmp_path, monkeypatch, b_dispatches, c_dispatches):
    """Recommendation 1: completed / provider_failed stand only when the round added exactly one dispatch event;
    0 (nothing was sent) or 2+ (more than the round's one send) is product_failed and ends the plan."""
    allowed = []

    def b_run(ctx):
        _dispatch(ctx.runs, "run_bb", b_dispatches)
        return c.BranchResult(cases=[c.case_record(case, "pass") for case in ("L-pre-B2", "L-pre-B3", "L-pre-B4")],
                              live={"L-B7": "completed" if b_dispatches else "provider_failed"})
    runner = _live_runner(inputs, tmp_path, monkeypatch, b_run, _c_branch(allowed, c_dispatches))
    runner.run_branches()
    records = runner.branch_records()
    if b_dispatches != 1:
        assert allowed == [False] and (records["L-B7"]["status"], records["L-B7"]["reason"]) == ("fail",
                                                                                                 "product_failed")
        assert records["L-C6"]["reason"] == "not_sent:earlier_product_failed"
        assert runner.checks["liveOutcome"]["waivable"] is False                # never a waivable provider failure
    else:
        assert allowed == [True] and records["L-B7"]["status"] == "pass"
        assert (records["L-C6"]["status"], records["L-C6"]["reason"]) == ("fail", "product_failed")


def test_a_one_branch_rehearsal_still_sends(inputs, tmp_path, monkeypatch):
    allowed = []
    runner = _live_runner(inputs, tmp_path, monkeypatch, None, _c_branch(allowed), branches=["c"])
    runner.run_branches()
    assert allowed == [True] and runner.branch_records()["L-C6"]["status"] == "pass"


def test_a_lock_without_its_ledger_is_refused(inputs, tmp_path, monkeypatch):
    """A removed ledger never rewinds the allocation: its lock file left behind refuses the phase."""
    ledger = tmp_path / "gone" / "m28-live-ledger.json"
    ledger.parent.mkdir()
    ledger.with_name(ledger.name + ".lock").write_text("")
    monkeypatch.setattr(m28.Runner, "ledger_location", lambda self: ledger)
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=2))
    with pytest.raises(SystemExit, match="refused, nothing started.*lock"):
        runner.ledger_guard()
    assert not ledger.exists()
    with pytest.raises(m28.LedgerError, match="lock"):
        m28.ledger_precheck(ledger)
    fresh = tmp_path / "fresh" / "m28-live-ledger.json"
    m28.ledger_precheck(fresh)                                 # neither file: the first phase ever
    fresh.parent.mkdir()
    fresh.write_text(json.dumps({"schema": "m28_live_ledger@1", "roots": {}}))
    fresh.with_name(fresh.name + ".lock").write_text("")
    m28.ledger_precheck(fresh)


def test_a_real_live_phase_needs_both_calls_before_touching_the_ledger(inputs, tmp_path, monkeypatch):
    """BLOCKING 1 (b): the real live phase plans both rounds, so --live-calls must be 2; 1 is refused in __init__,
    before the ledger or its lock file exists. A rehearsal keeps 1..2."""
    touched = []
    monkeypatch.setattr(m28.Runner, "ledger_location", lambda self: touched.append(1) or tmp_path / "never.json")
    with pytest.raises(SystemExit, match="--live-calls 2"):
        m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=1))
    assert touched == [] and not list(tmp_path.glob("never.json*"))
    assert m28.Runner(_args(inputs, tmp_path, phase="live", rehearse=True, live_calls=1, branches=["b"])).live_cap == 1
    parser = m28.build_parser()
    live_help = next(action.help for action in parser._actions if "--live-calls" in action.option_strings)
    assert "real live phase: 2" in live_help and "rehearsal: 1..2" in live_help
    assert "--live-calls N (1..2) is required" not in m28.__doc__


def test_a_first_live_phase_refused_at_admission_leaves_a_usable_ledger(inputs, tmp_path, monkeypatch):
    """BLOCKING 1 (a): the first read-and-write makes the ledger and its lock together, so a phase refused at the
    admission leaves an empty m28_live_ledger@1 (never a lock alone) and a later admitted phase can use it."""
    ledger = tmp_path / "shared" / "m28-live-ledger.json"
    ledger.parent.mkdir()
    monkeypatch.setattr(m28.Runner, "ledger_location", lambda self: ledger)
    real_admission = m28.ledger_admission
    refuse = [True]
    monkeypatch.setattr(m28, "ledger_admission", lambda *a: "refused for the test" if refuse[0] else real_admission(*a))
    first = m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=2, root=str(tmp_path / "root-1")))
    with pytest.raises(SystemExit, match="refused, nothing started"):
        first.ledger_guard()
    assert json.loads(ledger.read_text()) == {"schema": "m28_live_ledger@1", "roots": {}}
    assert ledger.with_name(ledger.name + ".lock").exists()
    m28.ledger_precheck(ledger)                              # ledger and lock together: not damaged
    refuse[0] = False
    second = m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=2, root=str(tmp_path / "root-2")))
    second.artifacts = tmp_path / "artifacts"
    second.artifacts.mkdir()
    second.ledger_guard()
    entry = json.loads(ledger.read_text())["roots"][str(second.root)]
    assert entry["phases"][0]["planned"] == 2 and str(first.root) not in json.loads(ledger.read_text())["roots"]


def test_a_rehearsal_refused_at_admission_also_leaves_its_ledger(inputs, tmp_path, monkeypatch):
    ledger = tmp_path / "shared" / "rehearsal-live-ledger.json"
    ledger.parent.mkdir()
    monkeypatch.setattr(m28.Runner, "ledger_location", lambda self: ledger)
    refused = m28.Runner(_args(inputs, tmp_path, phase="live", rehearse=True, live_calls=1, root=str(tmp_path / "r1")))
    with pytest.raises(SystemExit, match="plans 2 calls but --live-calls is 1"):
        refused.ledger_guard()
    assert json.loads(ledger.read_text())["roots"] == {}
    again = m28.Runner(_args(inputs, tmp_path, phase="live", rehearse=True, live_calls=2, root=str(tmp_path / "r2")))
    again.artifacts = tmp_path / "artifacts"
    again.artifacts.mkdir()
    again.ledger_guard()
    assert str(again.root) in json.loads(ledger.read_text())["roots"]


def test_a_second_export_that_raises_leaves_no_acceptance(inputs, tmp_path, monkeypatch):
    """Recommendation 2: the final export raising rewrites the case ledger with the export not passed."""
    runner = m28.Runner(_args(inputs, tmp_path))
    runner.artifacts = tmp_path / "artifacts"
    runner.artifacts.mkdir()
    runner.state["build"] = {"buildCurrentWithSource": True}
    runner.audited = True
    cases = m28.complete_cases("fixture", _all())
    passing = {"browser_non_loopback_requests": 0, "provider_calls": 0, "live_calls_counted": None}
    calls = []

    def export(self, ledger):
        calls.append(ledger["acceptance"])
        if len(calls) == 2:
            raise OSError("disk full in the second export")
        return True
    monkeypatch.setattr(m28.Runner, "export", export)
    with pytest.raises(OSError, match="second export"):
        runner.finish(cases, passing, {"processes": [], "ports": []})
    assert calls == [False, True, False]                     # the not-accepted ledger is exported once more
    assert json.loads((runner.artifacts / "case-ledger.json").read_text())["acceptance"] is False


def test_a_leaking_sha256sums_goes_back_to_the_artifacts_too(inputs, tmp_path):
    """Recommendation 3: when the list itself holds a leak (here an artifact path with a /home/… part), it is moved
    back as well; nothing the search finds stays in --out."""
    runner = m28.Runner(_args(inputs, tmp_path))
    runner.artifacts = tmp_path / "artifacts"
    odd = runner.artifacts / "step x /home" / "bob"
    odd.mkdir(parents=True)
    (odd / "clean.txt").write_text("nothing here")
    cases = m28.complete_cases("fixture", _all())
    ledger = m28.assemble_ledger("fixture", cases, ["a", "b", "c"], build={"buildCurrentWithSource": True},
                                 leftover={"processes": [], "ports": []}, external={}, trace_audit=None,
                                 export_ok=False)
    assert runner.export(ledger) is False
    assert "SHA256SUMS" in runner.checks["exportScan"]["movedToArtifacts"]
    assert not (runner.out / "SHA256SUMS").exists() and (runner.artifacts / "held-from-out/SHA256SUMS").is_file()
    assert m28.scan_evidence(runner.out) == {}


def test_x4_without_texts_counts_every_requested_branch(inputs, tmp_path):
    """Recommendation 4: a requested branch that left no result (or no tab text) fails X4."""
    runner = m28.Runner(_args(inputs, tmp_path))
    runner.artifacts = tmp_path / "artifacts"
    runner.artifacts.mkdir()
    runner.fixed = {}
    runner.results = {"a": c.BranchResult(texts={"structure@A1": "x"}), "b": c.BranchResult(texts={"ligand@B1": "y"})}
    runner.x4_scans()
    assert runner.without_texts == ["c"]


def test_the_branch_dispatch_limit_reaches_the_flow(inputs, tmp_path, monkeypatch):
    """The runner's cap is min(its own cap, the limit a branch passes for its round)."""
    runner = m28.Runner(_args(inputs, tmp_path, phase="live", live_calls=2))
    runner.artifacts = tmp_path / "artifacts"
    seen = []

    def watch(proc, runs, limit, timeout):
        seen.append(limit)
        proc.wait()
        return 0, None
    real_popen = subprocess.Popen
    monkeypatch.setattr(m28.m25, "watch_process", watch)
    monkeypatch.setattr(m28.subprocess, "Popen", lambda *a, **k: real_popen([PYTHON, "-c", "0"]))
    runner.flow("step", "x.cjs", "m", [], limit=1)
    runner.flow("step", "x.cjs", "m", [], limit=5)
    assert seen == [1, 2]


def test_every_run_of_the_phase_is_audited_and_an_unclaimed_run_fails(inputs, tmp_path):
    runner = m28.Runner(_args(inputs, tmp_path))
    for name in ("run_a1", "run_b1", "run_zz"):
        (runner.runs / name).mkdir(parents=True)
    (runner.runs / "jobs.global.lock").write_text("")
    runner.results = {"a": c.BranchResult(runs=["run_a1"]), "b": c.BranchResult(runs=["run_b1"])}
    runs, unclaimed = runner.audit_targets()
    assert runs == ["run_a1", "run_b1", "run_zz"] and unclaimed == ["run_zz"]
    summary = {"status": "pass", "failures": [], "partialProductRecheck": []}
    case = m28.x2_case(summary, {}, unclaimed=unclaimed)
    assert (case["status"], case["reason"]) == ("fail", "unclaimed_runs") and case["detail"]["unclaimedRuns"] == [
        "run_zz"]
    assert m28.x2_case(summary, {}, unclaimed=[])["status"] == "pass"
    assert _judge(runs_claimed=False)["parts"]["runsClaimed"] is False
    assert _judge(runs_claimed=False)["acceptance"] is False and _judge()["parts"]["runsClaimed"] is True


def test_x4_needs_tab_text_from_every_branch_that_ran():
    clean = {"a:screen:structure@A1": {"hits": [], "excepted": []}}
    assert m28.x4_case("fixture", clean, without_texts=[])["status"] == "pass"
    case = m28.x4_case("fixture", clean, without_texts=["b"])
    assert (case["status"], case["reason"]) == ("fail", "no_tab_text") and case["detail"]["withoutTabText"] == ["b"]
    assert m28.x4_case("live", clean, without_texts=["c"])["status"] == "fail"


def test_the_case_ledger_says_no_until_the_export_passed(inputs, tmp_path, monkeypatch):
    """The first case-ledger.json is written with the export not yet passed: an export that raises leaves a ledger
    that is not acceptance."""
    runner = m28.Runner(_args(inputs, tmp_path))
    runner.artifacts = tmp_path / "artifacts"
    runner.artifacts.mkdir()
    cases = m28.complete_cases("fixture", _all())
    passing = {"browser_non_loopback_requests": 0, "provider_calls": 0, "live_calls_counted": None}
    runner.state["build"] = {"buildCurrentWithSource": True}
    runner.audited = True                                    # the trace audit ran and every run was claimed

    def boom(ledger):
        raise OSError("disk full")
    monkeypatch.setattr(m28.Runner, "export", lambda self, ledger: boom(ledger))
    with pytest.raises(OSError):
        runner.finish(cases, passing, {"processes": [], "ports": []})
    written = json.loads((runner.artifacts / "case-ledger.json").read_text())
    assert written["acceptance"] is False and written["acceptanceParts"]["exportChecks"] is False
    exports = []
    monkeypatch.setattr(m28.Runner, "export", lambda self, ledger: exports.append(ledger["acceptance"]) or True)
    runner.summary.clear()
    ledger = runner.finish(cases, passing, {"processes": [], "ports": []})
    assert exports == [False, True] and ledger["acceptance"] is True
    assert json.loads((runner.artifacts / "case-ledger.json").read_text())["acceptance"] is True
    # the pessimistic first write is provisional, never a failed step of a passing phase
    assert [(entry["step"], entry["status"]) for entry in runner.summary] == [("case-ledger", "provisional"),
                                                                             ("case-ledger", "pass")]


def test_remaining_short_reads_the_budget_and_the_send_status():
    class FakeApi:
        def __init__(self, budget, jev):
            self.answers = {"budget": budget, "status": jev}

        def get(self, path):
            return self.answers["budget" if path.endswith("/budget") else "status"]
    budget = {"expensive_calls": {"limit": 8, "used": 7}, "wall_clock_s": {"limit": 1800, "used": 100},
              "external_tokens": {"limit": 120000, "used": 0}, "usd": {"limit": 2.0, "used": 0}}
    need = {"expensive_units": 1, "wall_clock_s": 300, "external_tokens": 12288, "usd": 0.1, "sends": 1}
    assert c.remaining_short(FakeApi((200, budget), (200, {"remaining": 10})), "r", need) == []
    assert c.remaining_short(FakeApi((200, budget), (200, {"remaining": 10})), "r",
                             {**need, "expensive_units": 2}) == ["expensive_units"]
    assert c.remaining_short(FakeApi((500, None), (200, {})), "r", need) == ["unreadable"]


# ---------------------------------------------------------------------------------------------------- X cases
def test_x1_compares_events_openings_and_the_case_code_count():
    assert m28.x1_case("a", 4, 4, 4)["status"] == "pass"
    for args in ((4, 4, 3), (4, 3, 4), (0, 0, 0), (4, 4, None)):
        assert m28.x1_case("b", *args)["status"] == "fail"
    assert m28.x1_case("c", 2, 2, 2)["id"] == "X1-C"


def test_x2_needs_the_audit_and_the_cases_that_supplement_its_partial_kinds():
    partial = [{"kind": "inspection", "note": "제품 재계산 전제 불성립: x"},
               {"kind": "interface_sasa", "note": "제품 재계산 전제 불성립: y"}]
    summary = {"status": "pass", "failures": [], "partialProductRecheck": partial}
    records = {"A2": c.case_record("A2", "pass"), "A3": c.case_record("A3", "pass")}
    case = m28.x2_case(summary, records)
    assert case["status"] == "pass"
    assert [(item["kind"], item["supplementedBy"], item["caseStatus"])
            for item in case["detail"]["partialProductRecheck"]] == [("inspection", "A2", "pass"),
                                                                     ("interface_sasa", "A3", "pass")]
    failed = m28.x2_case(summary, {**records, "A3": c.case_record("A3", "fail", "x")})
    assert (failed["status"], failed["reason"]) == ("fail", "partial_recheck_not_supplemented")
    assert failed["detail"]["notSupplemented"] == ["interface_sasa"]
    unknown = {**summary, "partialProductRecheck": [{"kind": "openmm_protein_minimize", "note": "n"}]}
    assert m28.x2_case(unknown, records)["status"] == "fail"
    assert m28.x2_case({"status": "fail", "failures": [1]}, records)["reason"] == "trace_audit_failed"
    assert m28.x2_case({"status": "pass", "failures": []}, {})["status"] == "pass"
    assert m28.AUDIT_SUPPLEMENTS == {"inspection": "A2", "interface_sasa": "A3"}
    assert set(m28.AUDIT_SUPPLEMENTS) == {a.kind for a in audit.ADAPTERS.values() if a.reopen != audit.FULL}


def test_x3_x5_x6_rules():
    ok = {"browser_non_loopback_requests": 0, "provider_calls": 0, "live_calls_counted": None}
    assert m28.x3_case("fixture", ok)["status"] == "pass"
    assert m28.x3_case("fixture", {**ok, "provider_calls": None})["status"] == "fail"
    live = {"browser_non_loopback_requests": 0, "provider_calls": None, "live_calls_counted": 2}
    assert m28.x3_case("live", live, ledger_count=2, live_calls=2)["status"] == "pass"
    assert m28.x3_case("live", live, ledger_count=1, live_calls=2)["status"] == "fail"
    assert m28.x3_case("live", live, ledger_count=2, live_calls=1)["status"] == "fail"
    assert m28.x5_case([(True, "a"), (True, "b")])["status"] == "pass"
    assert m28.x5_case([(True, "a"), (False, "0 shown")])["status"] == "fail"
    assert m28.x5_case([])["reason"] == "no_observation"
    clean = {"processes": [], "ports": []}
    none = {".deps/precedent_reference": False, ".deps/reaction_reference": False}
    assert m28.x6_case("fixture", clean, none, none)["status"] == "pass"
    made = {**none, ".deps/reaction_reference": True}
    assert m28.x6_case("fixture", clean, none, made)["detail"]["defaultFoldersCreated"] == [".deps/reaction_reference"]
    assert m28.x6_case("live", {"processes": ["1 fixture"], "ports": []}, none, none)["status"] == "fail"


def test_fixture_provider_calls_need_the_fixture_server_proof():
    server = {"fixture": True, "scienceGate": "EgressGate(httpx.MockTransport scripted)",
              "viewerGate": "EgressGate(httpx.MockTransport refusing)", "defaultGate": "httpx.MockTransport refusing"}
    calls = [{"authorizationIsSentinel": True}, {"authorizationIsSentinel": True}]
    reads = {"productResolverReads": 0, "sentinelReads": 2}
    assert m28.fixture_provider_calls(server, calls, 2, reads) == 0
    assert m28.fixture_provider_calls(server, [], 0, reads) == 0
    assert m28.fixture_provider_calls(server, calls, 3, reads) is None
    assert m28.fixture_provider_calls({**server, "scienceGate": "EgressGate(real)"}, calls, 2, reads) is None
    assert m28.fixture_provider_calls(server, calls, 2, {"productResolverReads": 1}) is None
    assert m28.fixture_provider_calls(server, [{"authorizationIsSentinel": False}], 1, reads) is None


# ---------------------------------------------------------------------------------------------------- wording (X4)
def test_forbidden_words_skip_fixed_lines_phrases_and_reasoned_exceptions():
    g1 = "GA는 후보 풀에서 어디를 도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 순위나 추천이 아니다."
    fixed = c.FixedText.build([g1, "Geometric proximity does not establish a hydrogen bond, affinity, stability."],
                              ["qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)"])
    text = "\n".join([g1, f"- {g1}", "| 후보 | qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님) |",
                      "Geometric proximity does not establish a hydrogen bond, affinity, stability.",
                      "이 후보가 최고다", "접촉 3개는 수소결합이다", "the best pose", "best_mode 3", "UniProt FAKE1"])
    found = c.forbidden_hits(text, fixed)
    assert [hit["words"] for hit in found["hits"]] == [["최고"], ["수소결합"], ["best"]]
    exception = {c.line_sha256("이 후보가 최고다"): {"reason": "synthetic test line", "words": ["최고"]}}
    found = c.forbidden_hits(text, fixed, exception)
    assert [hit["words"] for hit in found["hits"]] == [["수소결합"], ["best"]] and len(found["excepted"]) == 1
    with pytest.raises(ValueError, match="no reason"):
        c.forbidden_hits(text, fixed, {c.line_sha256("x"): {"words": ["x"]}})


def test_core_forbidden_words_cover_the_spec_list():
    for word in ("순위", "최고", "개선", "승자", "추천", "친화도", "ΔΔG", "안정성", "좋아짐", "수소결합", "수소 결합"):
        assert c.CORE_FORBIDDEN.search(f"값 {word} 표시"), word
    for clean in ("대응됨", "qvina 점수", "best_mode", "ranked_list_id", "kcal/mol", "obj://run/x/abc"):
        assert not c.CORE_FORBIDDEN.search(clean), clean


def test_normalize_line_undoes_markdown_and_list_markers():
    assert c.normalize_line(r"- a\_b \(c\) &amp; d") == "a_b (c) & d"
    assert c.normalize_line("  1.   text  here ") == "text here"
    assert c.normalize_line("**a bold fixed sentence.**") == "a bold fixed sentence."
    assert c.normalize_line("- **x** and **y**") == "x** and **y"          # only a whole-line wrapper goes
    assert c.normalize_line("****") == "****"


def test_line_templates_write_every_number_as_hash():
    assert c.line_template("- Rank 12: GLU auth A/981 model 1; 0.00 Å² (254 claims) v1.2.3") == \
        "Rank #: GLU auth A/# model #; # Å² (# claims) v#"
    assert c.template_sha256("x 1") == c.template_sha256("x 22") != c.template_sha256("y 1")
    assert c.line_sha256("x 1") != c.line_sha256("x 22")


def test_template_label_and_line_exceptions_match_only_their_kind():
    fixed = c.FixedText.build()
    template = {c.template_sha256("Exact rank selectors (12 claims)."): {"match": "template", "reason": "r"}}
    found = c.forbidden_hits("Exact rank selectors (254 claims).\nExact rank selectors (254 notes).", fixed, template)
    assert len(found["excepted"]) == 1 and [hit["words"] for hit in found["hits"]] == [["rank"]]
    assert found["excepted"][0]["match"] == "template" and found["excepted"][0]["reason"] == "r"
    line = {c.line_sha256("Exact rank selectors (12 claims)."): {"match": "line", "reason": "r"}}
    assert len(c.forbidden_hits("Exact rank selectors (254 claims).", fixed, line)["hits"]) == 1
    assert len(c.forbidden_hits("Exact rank selectors (12 claims).", fixed, line)["excepted"]) == 1
    label = {hashlib.sha256(b"Rank #").hexdigest(): {"match": "label", "reason": "fpocket label"}}
    found = c.forbidden_hits("- Rank 3: GLU auth A/1 label A/1 model 1\nRank 4: the best pocket\nRank 5 best: x",
                             fixed, label)
    assert [hit["exception"] for hit in found["excepted"]] == [hashlib.sha256(b"Rank #").hexdigest()]
    assert [hit["words"] for hit in found["hits"]] == [["best"], ["Rank", "best"]]
    assert found["hits"][0]["labelException"] == hashlib.sha256(b"Rank #").hexdigest()
    # A label key never excepts a whole line, a template key never a label.
    assert c.forbidden_hits("Rank 3", fixed, label)["hits"]
    as_template = {hashlib.sha256(b"Rank #").hexdigest(): {"match": "template", "reason": "r"}}
    assert c.forbidden_hits("Rank 3: GLU", fixed, as_template)["hits"]
    with pytest.raises(ValueError, match="unknown match"):
        c.forbidden_hits("x", fixed, {"k": {"match": "regex", "reason": "r"}})


def test_a_json_line_is_checked_string_by_string():
    sentence = "This is a queue-order choice only; it is not a prediction of affinity or stability."
    fixed = c.FixedText.build([sentence])
    body = json.dumps({"model": "m", "questions": {"q": {"instructions": sentence, "criteria": {"c01": "the best"}}},
                       "best_key": ["x\nrecommended"]}, ensure_ascii=False)
    found = c.forbidden_hits(f"<pre>\n{body}\n</pre>", fixed)
    assert [hit["words"] for hit in found["hits"]] == [["best"], ["recommended"]]
    assert {hit["part"] for hit in found["hits"]} == {"json_string"}
    assert not c.forbidden_hits(json.dumps({"instructions": sentence}), fixed)["hits"]
    assert c.forbidden_hits("{not json, the best}", fixed)["hits"][0]["part"] == "line"


def test_the_x4_exceptions_name_kind_cases_source_and_reason():
    kinds = {"fpocket_rank_label", "frontend_fixed_sentence", "frontend_composed_line",
             "product_criterion_definition", "reference_text"}
    assert m28.X4_EXCEPTIONS
    for key, entry in m28.X4_EXCEPTIONS.items():
        assert re.fullmatch(r"[0-9a-f]{64}", key), key
        assert set(entry) == {"match", "kind", "cases", "source", "reason"}, key
        assert entry["match"] in c.EXCEPTION_MATCHES and entry["kind"] in kinds, key
        assert entry["cases"] and set(entry["cases"]) <= set(c.FIXTURE_CASES), key
        assert entry["source"].startswith(("frontend/", "backend/mw/")), key
        for field in ("reason", "source", "kind"):          # the committed ledger lists them: no core word
            assert not c.CORE_FORBIDDEN.search(entry[field]), (key, field)
    assert sum(entry["match"] == "label" for entry in m28.X4_EXCEPTIONS.values()) == 1
    c.forbidden_hits("x", c.FixedText.build(), m28.X4_EXCEPTIONS)        # a valid exception table


def test_x4_committed_holds_hashes_only_and_the_raw_lines_stay_held(tmp_path):
    reference = ("roles_summary: synthetic stand-in for a reference role text, hydrogen bond donor and acceptor, long "
                 "enough to be real text")
    quote = "A synthetic stand-in for a real kbase quotation that has the best observed change in it."
    key = c.line_sha256(reference)
    exceptions = {key: {"match": "line", "kind": "reference_text", "cases": ["A8"], "source": "backend/mw/x.py",
                        "reason": "reference role vocabulary"}}
    scans = {"report:obj://run_1/method_report/" + "a" * 64: c.forbidden_hits(reference, c.FixedText.build(),
                                                                              exceptions),
             "a:screen:knowledge@A7": c.forbidden_hits(quote, c.FixedText.build(), exceptions)}
    origin = {name: ("report" if name.startswith("report") else "screen", ["A8"] if "report" in name else ["A7"])
              for name in scans}
    record = m28.x4_committed(scans, origin, exceptions)
    text = json.dumps(record, ensure_ascii=False)
    assert reference not in text and quote not in text and "hydrogen" not in text and "best" not in text
    assert m28.leak_kinds(text, m27.RealText([reference, quote])) == []          # the realSafe rule (M27)
    report = record["scans"]["report:obj://run_1/method_report/" + "a" * 64]
    assert report["excepted"][0] == {"line_sha256": key, "template_sha256": c.template_sha256(reference),
                                     "bytes": len(reference.encode()), "part": "line", "cases": ["A8"],
                                     "exception": key, "match": "line", "kind": "reference_text",
                                     "reason": "reference role vocabulary"}
    screen = record["scans"]["a:screen:knowledge@A7"]
    assert screen["hits"][0]["kind"] == "not_excepted" and screen["hits"][0]["cases"] == ["A7"]
    assert record["exceptionsUsed"] == {key: 1} and record["exceptionsNotMet"] == []
    (tmp_path / m28.X4_LINES).write_text(json.dumps(scans, ensure_ascii=False))
    (tmp_path / "x4-scan.json").write_text(text)
    assert m28.hold_reason(tmp_path, tmp_path / m28.X4_LINES, None) == "raw_lines"
    assert m28.hold_reason(tmp_path, tmp_path / "x4-scan.json", m27.RealText([reference, quote])) is None
    assert {m28.X4_LINES, "x4-scan.json"} <= m28.WORDING_SKIP


def test_case_attribution_of_screen_texts_and_reports():
    assert m28.screen_cases("structure@A3") == ["A3"] and m28.screen_cases("ligand@L-B7") == ["L-B7"]
    assert m28.screen_cases("no-case") == []
    assert m28.report_cases("fixture", "a", "interface_sasa") == ["A3"]
    assert m28.report_cases("fixture", "c", "mutation_candidates") == ["C1", "C2"]
    assert m28.report_cases("live", "c", "jev_loop") == ["L-C6"]
    assert m28.report_cases("fixture", "b", "unknown_kind") == ["branch-b"]
    assert m28.report_cases("live", None, "x") == []


def test_evidence_wording_scans_json_strings_and_skips_service_logs(tmp_path):
    (tmp_path / "services").mkdir()
    (tmp_path / "services/backend.log").write_text("최고\n")
    (tmp_path / "step").mkdir()
    (tmp_path / "step/ledger-row.json").write_text(json.dumps({"text": "A\n추천 후보", "ok": "대응됨"}))
    (tmp_path / "step/tab.dom.txt").write_text("최고\n")
    (tmp_path / "x4-scan.json").write_text(json.dumps({"text": "최고"}))
    scans = m28.evidence_wording(tmp_path, c.FixedText.build(), {})
    assert set(scans) == {"evidence:step/ledger-row.json"}
    assert [hit["words"] for hit in scans["evidence:step/ledger-row.json"]["hits"]] == [["추천"]]
    assert m28.x4_case("fixture", scans)["status"] == "fail" and m28.x4_case("fixture", {})["status"] == "fail"
    assert m28.x4_case("live", {"a": {"hits": [], "excepted": []}})["id"] == "L-X4"


# ---------------------------------------------------------------------------------------------------- leaks
REAL = "The observed change in this synthetic real-like quote is long enough to count."


@pytest.mark.parametrize("text,kind", [
    ("token sk-or-v1-" + "a1" * 20, "key_pattern"), ("Authorization: Bearer abcdefghijklmnop1234", "key_pattern"),
    ("OPENROUTER_API_KEY=xyz", "key_pattern"), ("m25-loop-fixture-sentinel-placeholder-not-a-key", "placeholder"),
    ("m24-fixture-sentinel-placeholder-not-a-key", "placeholder"), ("see " + USER_PATH, "absolute_path"),
    ("at /home/bob/x", "absolute_path"), (json.dumps({"q": REAL.upper()}), "real_kbase_text"),
    ("prefix " + REAL[5:50] + " suffix", "real_kbase_text")])
def test_leak_kinds(text, kind):
    assert kind in m28.leak_kinds(text, m27.RealText([REAL]))


@pytest.mark.parametrize("text", ["<repo>/scripts/x.py", "<home>/x", "obj://run_1/kind/abc", "/runs/run_1/reports",
                                  "sk-short", "count 3 at /tmp", "SYNTHETIC P0QA01"])
def test_clean_text_has_no_leak(text):
    assert m28.leak_kinds(text, m27.RealText([REAL])) == []


def test_hold_reasons(tmp_path):
    (tmp_path / "step/downloads").mkdir(parents=True)
    files = {"step/downloads/r.json": "{}", "step/big.txt": "x" * (m28.MAX_TEXT_BYTES + 1),
             "step/a-failure.panel.html": "<p/>", "step/key.txt": "sk-or-v1-" + "b" * 40, "step/path.txt":
             USER_PATH, "step/home.txt": "at /home/bob/data", "step/repo.txt": str(REPO / "x"),
             "step/real.json": json.dumps({"t": REAL}), "step/ok.json": "{}"}
    for rel, text in files.items():
        (tmp_path / rel).write_text(text)
    real = m27.RealText([REAL])
    replacements = [(str(REPO), "<repo>")]
    reasons = {rel: m28.hold_reason(tmp_path, tmp_path / rel, real, replacements) for rel in files}
    # an absolute path the redaction does not cover (another user's /Users/x, a /home/… path) is held
    assert reasons == {"step/downloads/r.json": "download", "step/big.txt": "over_256KiB",
                       "step/a-failure.panel.html": "failure_panel", "step/key.txt": "key_pattern",
                       "step/path.txt": "absolute_path", "step/home.txt": "absolute_path", "step/repo.txt": None,
                       "step/real.json": "real_kbase_text", "step/ok.json": None}


@pytest.mark.parametrize("leak", ["/home/bob/data/x.json", USER_PATH])
def test_an_out_file_that_fails_the_search_goes_back_to_the_artifacts(inputs, tmp_path, leak):
    """The files the runner writes into --out itself (summary, cases, README, listing) are searched too; one that
    still holds a leak is moved back to the git-ignored artifacts and the export fails."""
    runner = m28.Runner(_args(inputs, tmp_path))
    runner.artifacts = tmp_path / "artifacts"
    (runner.artifacts / "step").mkdir(parents=True)
    (runner.artifacts / "step/ok.json").write_text("{}")
    cases = m28.complete_cases("fixture", _all())
    cases["B1"] = c.case_record("B1", "fail", "x", detail={"file": leak})
    ledger = m28.assemble_ledger("fixture", cases, ["a", "b", "c"], build={"buildCurrentWithSource": True},
                                 leftover={"processes": [], "ports": []}, external={}, trace_audit=None,
                                 export_ok=False)
    assert runner.export(ledger) is False
    assert not (runner.out / "cases.json").exists() and (runner.artifacts / "held-from-out/cases.json").is_file()
    assert runner.checks["exportScan"]["movedToArtifacts"] == ["cases.json"]
    assert "cases.json" not in (runner.out / "SHA256SUMS").read_text()
    assert m28.scan_evidence(runner.out) == {}
    assert (runner.out / "evidence/step/ok.json").is_file()


def test_export_holds_leaks_and_fails_on_an_unredacted_user_path(inputs, tmp_path):
    runner = m28.Runner(_args(inputs, tmp_path))
    runner.artifacts = tmp_path / "artifacts"
    (runner.artifacts / "step").mkdir(parents=True)
    (runner.artifacts / "step/row.json").write_text(json.dumps({"dir": str(REPO / "x")}))
    (runner.artifacts / "step/key.txt").write_text("sk-or-v1-" + "c" * 40)
    (runner.artifacts / "step/shot.png").write_bytes(b"\x89PNG")
    cases = m28.complete_cases("fixture", _all())
    ledger = m28.assemble_ledger("fixture", cases, ["a", "b", "c"], build={"buildCurrentWithSource": True},
                                 leftover={"processes": [], "ports": []}, external={}, trace_audit=None,
                                 export_ok=True)
    assert runner.export(ledger) is True
    exported = (runner.out / "evidence/step/row.json").read_text()
    assert "<repo>" in exported and str(REPO) not in exported
    assert not (runner.out / "evidence/step/key.txt").exists()
    listing = json.loads((runner.out / "binary-artifacts.json").read_text())
    assert [item["held"] for item in listing["heldText"]] == ["key_pattern"]
    assert [item["path"] for item in listing["files"]] == ["step/shot.png"]
    (runner.artifacts / "step/other.txt").write_text("from /home/bob/data")
    (runner.artifacts / "step/user.txt").write_text("from " + USER_PATH)
    assert runner.export(ledger) is True                   # held: never copied, path / size / SHA-256 listed only
    assert not (runner.out / "evidence/step/other.txt").exists()
    assert not (runner.out / "evidence/step/user.txt").exists()
    listing = json.loads((runner.out / "binary-artifacts.json").read_text())
    assert sorted(item["held"] for item in listing["heldText"]) == ["absolute_path", "absolute_path", "key_pattern"]
    assert m28.scan_evidence(runner.out) == {}


# ---------------------------------------------------------------------------------------------------- trace audit
NUM_RULES = {"residue_numbering": {"fields": {"computed": r"rows\.status|chains\[\d+\]\.counts\.mapped",
                                              "reference_value": r"chains\[\d+\]\.sifts\.accessions\[\d+\]"}},
             "mutation_candidates": {"fields": {"computed": r"positions\[\*\]",
                                                "reference_value": r"positions\[\d+\]\.numbering\.uniprot_accession"}},
             "reaction_knowledge": {"fields": {"computed": r"chains\[\*\]",
                                               "reference_value": r"snapshot_set\.sources\[\d+\]\.files\[\d+\]\.rows"}},
             "kinase_precedents": {"fields": {"computed": r"chains\[\*\]",
                                              "reference_value": r"precedent_set\.files\[\d+\]\.rows"}},
             "ligand_docking": {"fields": {"computed": r"modes\[\*\]\.score_kcal_mol|counts\.modes"}}}


def _h(kind, key, run=RID):
    return f"obj://{run}/{kind}/{H[key]}"


def _claim(kind, key, path, unit="count", **extra):
    claim = {"source_handle": _h(kind, key), "source_kind": kind, "source_schema": f"{kind}@1",
             "source_sha256": H[key], "field_path": path, "unit": unit, "quantity": "q", "exact_value": 1}
    claim.update(extra)
    return claim


def _m15_set(set_hash=SET):
    return {"origin": "kbase_kinase processed snapshot", "set_hash": set_hash,
            "sources": [{"source": "uniprot", "date": "2026-09-15"}, {"source": "sifts", "date": "2026-09-20"},
                        {"source": "klifs", "date": "2026-09-20"}]}


def _numbering(**change):
    ref = {"note": audit.REFERENCE_NOTE, "origin": "kbase_kinase processed snapshot", "set_hash": SET,
           "sources": [{"source": "sifts", "date": "2026-09-20"}]}
    manifest = {"schema": "method_report_manifest@1", "analysis_type": "residue_numbering",
                "render_version": "residue_numbering_markdown@1", "snapshot_set": _m15_set(),
                "claims": [_claim("residue_numbering_map", "map", "rows.status", evidence_kind="computed",
                                  operation="count_kind(rows.status)", reference=None,
                                  row_selector={"status": "mapped"}),
                           _claim("residue_numbering_map", "map", "chains[0].sifts.accessions[0]", unit="identifier",
                                  evidence_kind="reference_value", operation=None, reference=ref,
                                  row_selector={"chain_auth": "A"})]}
    manifest.update(change)
    return manifest


def _world(manifests, metas=None, selected_status=None, events_status=200):
    """A GET-only fake of the loopback API: events, /reports/selected, /objects/meta."""
    def kind(manifest):
        return "report" if manifest.get("schema") == "report_manifest@1" else "method_report"
    events = [{"type": f"{kind(m)}_created", "report_handle": f"obj://{RID}/{kind(m)}_manifest/{index:064x}",
               "seq": index} for index, m in enumerate(manifests, 1)]
    by_handle = {event["report_handle"]: (manifest, event) for event, manifest in zip(events, manifests)}
    metas = {} if metas is None else metas
    calls = []

    def fetch(path):
        calls.append(path)
        parsed = urllib.parse.urlparse(path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path.endswith("/events"):
            return events_status, events if events_status == 200 else {"detail": "x"}
        if parsed.path.endswith("/reports/selected"):
            handle = query["handle"][0]
            manifest, _ = by_handle[handle]
            status = (selected_status or {}).get(handle, 200)
            if status != 200:
                return status, {"detail": {"error": "report_evidence_invalid", "message": "x"}}
            return 200, {"handle": handle, "markdown_handle": "m", "manifest": manifest,
                         "markdown": manifest.get("_markdown", f"report {SET} {REACTION_SET}")}
        if parsed.path.endswith("/objects/meta"):
            handle = query["handle"][0]
            if handle in metas:
                return metas[handle]
            if not handle.startswith(f"obj://{RID}/"):
                return 404, {"detail": {"error": "not_found"}}
            kind = handle.split("/")[3]
            return 200, {"handle": handle, "kind": kind, "schema": f"{kind}@1"}
        raise AssertionError(path)
    fetch.calls = calls
    fetch.events = events
    return fetch


def _audit(manifests, **world):
    fetch = _world(manifests, **world)
    return audit.audit_runs(fetch, [RID], NUM_RULES), fetch


def test_a_clean_report_passes_every_check_with_get_only_reads():
    summary, fetch = _audit([_numbering()])
    assert summary["status"] == "pass" and summary["reportCount"] == 1
    assert all(summary["checks"][check]["pass"] == 1 for check in audit.CHECKS)
    assert all(not path.startswith("/runs/" + RID + "/reports?") for path in fetch.calls)   # never the list route
    report = summary["reports"][0]
    assert report["hashes"]["handleSha256"] == f"{1:064x}" and len(report["hashes"]["markdownSha256"]) == 64
    assert summary["_markdown"] and summary["units"]["unitless"] == ["count", "identifier"]


def _fails(summary, check):
    return [f for f in summary["failures"] if f["check"] == check]


def test_check_1_reopen_failure():
    manifest = _numbering()
    handle = f"obj://{RID}/method_report_manifest/{1:064x}"
    summary, _ = _audit([manifest], selected_status={handle: 422})
    assert summary["status"] == "fail" and _fails(summary, "reopen")[0]["problem"].endswith("report_evidence_invalid")
    assert summary["reports"][0]["checks"]["evidence_exists"] == "not_checked"


@pytest.mark.parametrize("change,problem", [
    ({"source_handle": _h("residue_numbering_map", "map", OTHER)}, "belongs to run"),
    ({"source_sha256": H["x"]}, "source_sha256"),
    ({"source_kind": "interaction_set", "source_handle": _h("interaction_set", "map")}, "not an evidence kind"),
    ({"source_handle": "not-a-handle"}, "not an object handle")])
def test_check_2a_evidence_must_exist_in_the_same_run(change, problem):
    manifest = _numbering()
    manifest["claims"][0].update(change)
    summary, _ = _audit([manifest])
    assert any(problem in f["problem"] for f in _fails(summary, "evidence_exists"))
    assert _fails(summary, "evidence_exists")[0]["claim"].startswith("#0")


def test_check_2a_stored_object_kind_and_schema():
    manifest = _numbering()
    handle = manifest["claims"][0]["source_handle"]
    summary, _ = _audit([manifest], metas={handle: (404, {"detail": {"error": "not_found"}})})
    assert any("not in the run's store" in f["problem"] for f in _fails(summary, "evidence_exists"))
    summary, _ = _audit([manifest], metas={handle: (200, {"kind": "residue_numbering_map", "schema": "other@2"})})
    assert any("stored object is" in f["problem"] for f in _fails(summary, "evidence_exists"))


@pytest.mark.parametrize("change,problem", [
    ({"field_path": ""}, "field_path empty"), ({"unit": ""}, "unit missing"), ({"unit": None}, "unit missing"),
    ({"quantity": None}, "quantity missing"), ({"operation": None}, "without an aggregate operation"),
    ({"row_selector": {}}, "row_selector")])
def test_check_2b_claim_fields(change, problem):
    manifest = _numbering()
    manifest["claims"][0].update(change)
    summary, _ = _audit([manifest])
    assert any(problem in f["problem"] for f in _fails(summary, "claim_fields")), summary["failures"]


def test_check_2b_comparison_quantity_exemption_and_row_fingerprint():
    distance = {"schema": "method_report_manifest@1", "analysis_type": "atom_distance",
                "render_version": "comparison_markdown@1",
                "claims": [{k: v for k, v in _claim("atom_distance", "dist", "distance_A", unit="angstrom").items()
                            if k != "quantity"}]}
    summary, _ = _audit([distance])
    assert summary["status"] == "pass", summary["failures"]
    inspection = {"schema": "report_manifest@1", "render_version": "inspection_markdown@1",
                  "claims": [_claim("interaction_set", "inter", "rows[0].distance_A", unit="angstrom",
                                    operation="row_distance", row_index=0, row_fingerprint="z"),
                             _claim("interaction_set", "inter", "rows.residue", operation=None)]}
    summary, _ = _audit([inspection])
    problems = [f["problem"] for f in _fails(summary, "claim_fields")]
    assert any("row_fingerprint" in p for p in problems) and any("collection path" in p for p in problems)
    unprinted = {"schema": "report_manifest@1", "render_version": "inspection_markdown@1",
                 "claims": [_claim("interaction_set", "inter", "rows[0].distance_A", unit="angstrom",
                                   operation="row_distance", row_index=0)]}          # no row_fingerprint key at all
    summary, _ = _audit([unprinted])
    assert any("row_fingerprint" in f["problem"] for f in _fails(summary, "claim_fields")), summary["failures"]


def test_a_report_without_claims_passes_checks_2_and_4_only_when_its_adapter_allows_it(monkeypatch):
    empty = _numbering(claims=[])
    summary, _ = _audit([empty])
    assert summary["status"] == "fail"
    assert {f["check"] for f in summary["failures"]} == {"evidence_exists", "claim_fields", "no_mixing"}
    assert all("no claims" in f["problem"] for f in summary["failures"])
    assert not any(adapter.claims_optional for adapter in audit.ADAPTERS.values())   # none of the 20 kinds
    assert all("claims_optional" in row for row in audit.adapter_table())
    allowed = {**audit.ADAPTERS, "residue_numbering": dataclasses.replace(
        audit.ADAPTERS["residue_numbering"], claims_optional=True)}
    monkeypatch.setattr(audit, "ADAPTERS", allowed)
    assert _audit([empty])[0]["status"] == "pass"


def test_check_3_reference_source_must_be_in_the_report_itself():
    summary, _ = _audit([_numbering(snapshot_set=None)])
    assert any("snapshot_set" in f["problem"] for f in _fails(summary, "reference_source"))
    other = _numbering()
    other["claims"][1]["reference"] = {**other["claims"][1]["reference"], "set_hash": "d" * 64}
    summary, _ = _audit([other])
    assert any("names no set" in f["problem"] for f in _fails(summary, "reference_source"))


def _m20(version, **extra):
    ref = {"note": audit.REFERENCE_NOTE, "reference_object": _h("residue_numbering_map", "map")}
    manifest = {"schema": "method_report_manifest@1", "analysis_type": "mutation_candidates",
                "render_version": version,
                "claims": [_claim("mutation_candidate_set", "mut", "positions[*]", evidence_kind="computed",
                                  operation="count(positions[*])", reference=None, row_selector=None),
                           _claim("mutation_candidate_set", "mut", "positions[0].numbering.uniprot_accession",
                                  unit="identifier", evidence_kind="reference_value", operation=None, reference=ref,
                                  row_selector={"row_index": 0, "row_sha256": "f" * 64})]}
    manifest.update(extra)
    return manifest


def test_check_3_m20_v1_resolving_through_the_cited_object_does_not_pass():
    summary, _ = _audit([_m20("mutation_candidates_markdown@1")])
    problems = _fails(summary, "reference_source")
    assert problems and "only through the cited object" in problems[0]["problem"] and problems[0]["claim"] == "#1 " + \
        "positions[0].numbering.uniprot_accession"
    no_refs = _m20("mutation_candidates_markdown@1")
    no_refs["claims"] = no_refs["claims"][:1]
    assert _audit([no_refs])[0]["status"] == "pass"                       # nothing cited: nothing to source


def test_check_3_m20_v2_needs_each_cited_family_set_in_the_report():
    summary, _ = _audit([_m20("mutation_candidates_markdown@2")])
    assert any("no m15 snapshot set" in f["problem"] for f in _fails(summary, "reference_source"))
    table = {"numbering_sets": [_m15_set()]}
    summary, _ = _audit([_m20("mutation_candidates_markdown@2", reference_snapshots=table)])
    assert summary["status"] == "pass", summary["failures"]
    hidden = _m20("mutation_candidates_markdown@2", reference_snapshots=table, _markdown="no hash here")
    assert _fails(_audit([hidden])[0], "reference_source")
    catalytic = _m20("mutation_candidates_markdown@2", reference_snapshots=table)
    catalytic["claims"][1]["reference"]["reference_object"] = _h("reaction_knowledge", "react")
    summary, _ = _audit([catalytic])
    assert any("no m26 snapshot set" in f["problem"] for f in _fails(summary, "reference_source"))
    catalytic["reaction_sets"] = [{"set_hash": REACTION_SET, "sources": [{"source": "mcsa", "date": "2026-10-08"}]}]
    assert _audit([catalytic])[0]["status"] == "pass"


def test_check_3_reaction_and_precedent_sets():
    ref = {"note": audit.REFERENCE_NOTE, "set_hash": REACTION_SET, "sources": [{"source": "mcsa", "date": "d"}]}
    reaction = {"schema": "method_report_manifest@1", "analysis_type": "reaction_knowledge",
                "render_version": "reaction_knowledge_markdown@1",
                "snapshot_set": {"set_hash": REACTION_SET, "imported_at": "2026-10-08T00:00:00Z",
                                 "sources": [{"source": "mcsa", "date": "2026-10-08"}]},
                "claims": [_claim("reaction_knowledge", "react", "snapshot_set.sources[0].files[0].rows",
                                  evidence_kind="reference_value", operation=None, reference=ref,
                                  row_selector={"source": "mcsa"})]}
    assert _audit([reaction])[0]["status"] == "pass"
    reaction["snapshot_set"] = {**reaction["snapshot_set"], "imported_at": ""}
    assert _fails(_audit([reaction])[0], "reference_source")
    pref = {"note": audit.KBASE_NOTE, "set_hash": PRECEDENT_SET, "kb_version": "kbv1:x", "imported_at": "t",
            "source": "kbase_dist"}
    precedent = {"schema": "method_report_manifest@1", "analysis_type": "kinase_precedents",
                 "render_version": "kinase_precedents_markdown@1",
                 "precedent_set": {"set_hash": PRECEDENT_SET, "kbase": {"kb_version": "kbv1:x", "origin": "o"}},
                 "claims": [_claim("kinase_precedents", "prec", "precedent_set.files[0].rows",
                                   evidence_kind="reference_value", operation=None, reference=pref,
                                   row_selector={"file": "dist/moves.jsonl"})]}
    assert _audit([precedent])[0]["status"] == "pass"
    precedent["claims"][0]["reference"] = {**pref, "kb_version": "kbv1:other"}
    assert any("kb_version" in f["problem"] for f in _fails(_audit([precedent])[0], "reference_source"))


def test_check_3_a_kind_without_references_must_not_cite_one():
    docking = {"schema": "method_report_manifest@1", "analysis_type": "ligand_docking",
               "render_version": "ligand_docking_markdown@1",
               "claims": [_claim("docking_result", "x", "counts.modes", evidence_kind="reference_value",
                                 operation=None, reference={"note": audit.REFERENCE_NOTE})]}
    summary, _ = _audit([docking])
    assert _fails(summary, "reference_source") and _fails(summary, "no_mixing")


@pytest.mark.parametrize("index,change,problem", [
    (0, {"reference": {"note": audit.REFERENCE_NOTE}}, "computed claim carries a reference"),
    (1, {"reference": None}, "without the kind's reference note"),
    (1, {"reference": {"note": "something else", "set_hash": SET, "sources": [{"source": "sifts"}]}},
     "reference note"),
    (0, {"evidence_kind": "guess"}, "not in"),
    (0, {"field_path": "chains[0].sifts.accessions[0]", "operation": None}, "cites a reference_value field"),
    (1, {"field_path": "rows.status", "operation": "count_kind(rows.status)"}, "not a reference_value field")])
def test_check_4_no_mixing(index, change, problem):
    manifest = _numbering()
    manifest["claims"][index].update(change)
    summary, _ = _audit([manifest])
    assert any(problem in f["problem"] for f in _fails(summary, "no_mixing")), summary["failures"]


def test_check_4_needs_the_exported_field_rules():
    summary = audit.audit_runs(_world([_numbering()]), [RID], None)
    assert any("not exported" in f["problem"] for f in _fails(summary, "no_mixing"))


@pytest.mark.parametrize("manifest", [
    {"schema": "method_report_manifest@1", "analysis_type": "new_kind", "render_version": "new_kind_markdown@1",
     "claims": []},
    {"schema": "method_report_manifest@1", "analysis_type": "residue_numbering",
     "render_version": "residue_numbering_markdown@9", "claims": []},
    {"schema": "method_report_manifest@1", "analysis_type": "inspection", "render_version": "inspection_markdown@1",
     "claims": []}])
def test_a_kind_or_version_without_an_adapter_fails(manifest):
    summary, _ = _audit([manifest])
    assert summary["status"] == "fail"
    assert all(f["problem"].startswith("no adapter") for f in summary["failures"])
    assert {f["check"] for f in summary["failures"]} == set(audit.CHECKS[1:])


def test_no_report_or_unreadable_events_is_not_a_pass():
    assert audit.audit_runs(_world([]), [RID], NUM_RULES)["status"] == "fail"
    summary = audit.audit_runs(_world([_numbering()], events_status=500), [RID], NUM_RULES)
    assert summary["status"] == "fail" and summary["failures"][0]["check"] == "reopen"


def test_adapter_table_covers_the_twenty_kinds_and_the_partial_recheck_note():
    table = audit.adapter_table()
    assert len(table) == 20 and len({row["kind"] for row in table}) == 20
    notes = {row["kind"]: row["note"] for row in table if row["note"]}
    assert set(notes) == {"inspection", "interface_sasa"}
    assert all(note.startswith("제품 재계산 전제 불성립") for note in notes.values())
    doc = audit.__doc__
    for kind in audit.ADAPTERS:
        assert kind in doc, kind
    assert "제품 재계산 전제 불성립" in doc


def test_adapters_know_every_product_render_version():
    """Drift guard without importing mw: every RENDER_VERSION constant of a report module has an adapter."""
    versions = set()
    for path in (REPO / "backend/mw").glob("*reports.py"):
        versions |= set(re.findall(r'^RENDER_VERSION = "([^"]+)"', path.read_text(), re.MULTILINE))
    known = {version for adapter in audit.ADAPTERS.values() for version in adapter.versions}
    assert versions and versions <= known, versions - known


def test_audit_only_reads_with_get():
    source = (SCRIPTS / "m28_trace_audit.py").read_text()
    assert 'method="GET"' in source and '"POST"' not in source and "urlopen(" in source


def test_audit_fails_closed_when_the_backend_does_not_answer():
    fetch = audit.http_fetch("http://127.0.0.1:9")            # nothing listens on the discard port
    status, body = fetch("/runs/x/events?after=0&limit=500")
    assert status == 0 and body["error"]
    summary = audit.audit_runs(fetch, [RID], NUM_RULES)
    assert summary["status"] == "fail" and summary["noReports"] is True


# ---------------------------------------------------------------------------------------------------- fixed sentences
@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    out = tmp_path_factory.mktemp("fixed") / "fixed.json"
    env = {**{k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG")},
           "PYTHONPATH": str(REPO / "backend")}
    done = subprocess.run([PYTHON, str(SCRIPTS / "m28_export_fixed_sentences.py"), "--out", str(out)], cwd=REPO,
                          env=env, capture_output=True, text=True, timeout=300, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(out.read_text())


def test_export_holds_fixed_sentences_inline_literals_phrases_and_rules(exported):
    assert exported["schema"] == "m28_fixed_sentences@1" and len(exported["sha256"]) == 64
    ids = {item["id"] for item in exported["sentences"]}
    for name in ("mw.ligand_ga_constants.STATEMENTS[G1]", "mw.jev_loop_constants.STATEMENTS[LJ8]",
                 "mw.precedent_constants.STATEMENTS[KT1]", "mw.mutation_model_constants.L7",
                 "mw.docking_batch_constants.BATCH_STATEMENTS[B3]", "mw.numbering_reports.KLIFS_TERMS",
                 "mw.mutation_constants.LIMITATION_3_NOT_CHECKED", "mw.pocket_reports.DRUGGABILITY_WARNING"):
        assert name in ids, name
    inline = {item["text"] for item in exported["inline"]}
    assert "Geometric proximity does not establish a hydrogen bond, affinity, stability, or energy." in inline
    assert ("These are chemistry-dependent native assignments, not experimental bond validation, affinity or energy."
            in inline)                                                       # the M11 report literal (T9)
    for name in ("mw.jev_constants.INSTRUCTIONS[ligand_candidate_choice@1]",
                 "mw.jev_constants.INSTRUCTIONS[mutation_candidate_choice@1]",
                 "mw.jev_loop_constants.INSTRUCTIONS[('ligand', 'exploit')]",
                 "mw.jev_loop_constants.INSTRUCTIONS[('mutation', 'explore')]"):
        assert name in ids, name
    assert {item["id"] for item in exported["phrases"]} == {"mw.docking_constants.SCORE_LABEL",
                                                             "mw.docking_constants.SCORE_COLUMN_LABEL",
                                                             "mw.sequence_ga_constants.SCORE_LABEL"}
    rules = exported["reportRules"]
    assert {"residue_numbering", "mutation_candidates", "jev_choice", "jev_loop", "reaction_knowledge",
            "kinase_precedents", "ligand_docking"} <= set(rules)
    for kind, rule in rules.items():
        assert set(rule["fields"]) == set(rule["evidenceKinds"]), kind
        assert rule["renderVersion"] in audit.ADAPTERS[kind].versions
        assert rule["referenceNote"] in (None, audit.ADAPTERS[kind].reference_note)
        if "model_response" in rule["evidenceKinds"]:
            assert rule["modelResponseNote"] == audit.MODEL_RESPONSE_NOTE
        if "reference_value" in rule["evidenceKinds"]:
            assert rule["referenceNote"] == audit.ADAPTERS[kind].reference_note
    fixed = c.FixedText.from_export(exported)
    g1 = next(item["text"] for item in exported["sentences"] if item["id"] == "mw.ligand_ga_constants.STATEMENTS[G1]")
    assert c.CORE_FORBIDDEN.search(g1) and not c.forbidden_hits(f"- {g1}", fixed)["hits"]


def test_a_request_body_line_passes_by_its_exported_instructions(exported):
    """The M24 / M25 request body shown in a <pre> is one JSON line: its instructions are exported fixed sentences
    and every other string is checked on its own (T9; the line is never skipped)."""
    fixed = c.FixedText.from_export(exported)
    texts = {item["id"]: item["text"] for item in exported["sentences"]}
    instructions = texts["mw.jev_constants.INSTRUCTIONS[ligand_candidate_choice@1]"]
    assert c.CORE_FORBIDDEN.search(instructions)
    body = {"model": "m", "questions": {"candidate_choice": {"type": "choice", "instructions": instructions,
                                                             "criteria": {"c01": "Candidate c01."}}}}
    assert not c.forbidden_hits(json.dumps(body), fixed)["hits"]
    body["questions"]["candidate_choice"]["criteria"]["c01"] = "Candidate c01 is the best."
    assert [hit["words"] for hit in c.forbidden_hits(json.dumps(body), fixed)["hits"]] == [["best"]]
    evidence = "**" + texts["mw.pocket_reports.EVIDENCE_STATEMENT"] + "**"       # the pocket report's bold line
    assert not c.forbidden_hits(evidence, fixed)["hits"]


def test_exported_field_rules_separate_the_kinds(exported):
    rules = exported["reportRules"]
    assert re.fullmatch(rules["residue_numbering"]["fields"]["reference_value"], "chains[0].sifts.accessions[0]")
    assert not re.fullmatch(rules["residue_numbering"]["fields"]["computed"], "chains[0].sifts.accessions[0]")
    assert re.fullmatch(rules["jev_choice"]["fields"]["computed"], "selection[*]")
    assert re.fullmatch(rules["mutation_candidates"]["fields"]["computed"], "positions[*]")


# ---------------------------------------------------------------------------------------------------- boundaries
def _imports(path):
    tree = ast.parse(path.read_text())
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    return names


@pytest.mark.parametrize("name", ["m28_offscreen_acceptance.py", "m28_common.py", "m28_trace_audit.py"])
def test_runner_common_and_audit_never_import_mw(name):
    path = SCRIPTS / name
    assert not [module for module in _imports(path) if module == "mw" or module.startswith("mw.")]
    source = path.read_text()
    # The only mention of a limit-raising route is the refusal list of m28_common.Api.post.
    allowed = 'FORBIDDEN_POST_PARTS = ("limit_approval", "raise_limits", "/jev")'
    rest = source.replace(allowed, "") if name == "m28_common.py" else source
    assert (allowed in source) == (name == "m28_common.py")
    assert "limit_approval" not in rest and "raise_limits" not in rest
    assert "m28_export_fixed_sentences" not in [module.split(".")[-1] for module in _imports(path)]


def test_the_audit_uses_the_standard_library_only():
    for module in _imports(SCRIPTS / "m28_trace_audit.py"):
        assert module.split(".")[0] in sys.stdlib_module_names or module == "__future__", module


def test_the_runner_posts_nothing_to_limit_or_jev_routes():
    api = c.Api()
    for path in ("/runs/r/ligand/ga/limit_approval", "/runs/r/jev/sends", "/runs/r/jev_loops", "/x/raise_limits"):
        with pytest.raises(PermissionError):
            api.post(path, {})
    with pytest.raises(ValueError):
        c.Api("http://example.org:8000")
    with pytest.raises(ValueError):
        audit.http_fetch("http://10.0.0.1:8000")


def test_the_npm_script_runs_this_runner_from_the_repository_root():
    scripts = json.loads((REPO / "frontend/package.json").read_text())["scripts"]
    assert scripts["test:offscreen:endtoend"] == "cd .. && .venv/bin/python scripts/m28_offscreen_acceptance.py"
    for branch in "abc":
        assert (REPO / f"frontend/tests/offscreen/endtoend-{branch}-flow.cjs").is_file()


def test_stop_hook_runs_this_test():
    assert '"scripts/test_m28_offscreen_acceptance.py"' in (REPO / ".codex/hooks/stop.py").read_text()
