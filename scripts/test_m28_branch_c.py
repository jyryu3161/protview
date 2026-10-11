"""Independent expectations and case judgement of the M28 branch C module (scripts/m28_branch_c.py); no service.

The input files are read from this repository (public 1A30 and 1UBQ, the labeled synthetic phenol SDF), the archived
M26 reaction set from ``.deps/reaction_qa/import2`` and the GA ranges from the product constants file as text: a
missing file is a failure, never a skip (.dryforge/spec.md R1, plan T8).
"""

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import m28_branch_c as cc
from scripts import m28_common as c

REPO = Path(cc.__file__).resolve().parents[1]
FIXTURES = REPO / "backend/tests/fixtures"
HARNESS = REPO / "frontend/tests/offscreen" / cc.HARNESS
ARCHIVE = REPO / ".deps/reaction_qa/import2"


def _need(path: Path) -> Path:
    assert path.exists(), f"required local input is missing (no skip): {path}"
    return path


def _set_dir() -> Path:
    active = json.loads(_need(ARCHIVE / "active.json").read_text())
    return _need(ARCHIVE / "sets" / active["set_hash"])


# ---------------------------------------------------------------------------------------------------- C1 (M-CSA)
def test_mcsa_groups_of_1a30_name_entry_175_on_both_chains():
    entries = cc.a.read_jsonl(_set_dir() / "files/mcsa/entries.jsonl")
    groups = {chain: [(g["mcsa_id"], g["residue_index"], g["auth"], g["is_reference"]) for g in
                      cc.mcsa_groups(entries, "1a30", chain)] for chain in ("A", "B", "C")}
    assert groups["A"] == [(175, 1, 25, True), (175, 2, 26, True), (175, 4, 27, True)]
    assert groups["B"] == [(175, 0, 27, True), (175, 3, 26, True), (175, 5, 25, True)]
    assert groups["C"] == []


def test_checked_rule_is_true_only_when_every_position_chain_is_covered():
    coverage = {"A": "covered", "B": "covered", "C": "chain_not_listed"}
    assert cc.checked_expectation(["A", "B"], ["A", "B"], coverage) == {
        "status": "checked", "reason": None, "covered": ["A", "B"], "uncovered": []}
    assert cc.checked_expectation(["B", "A"], ["A"], coverage) == {
        "status": "not_checked", "reason": "chains_not_covered", "covered": ["A"],
        "uncovered": [{"chain_auth": "B", "coverage": "not_in_annotation"}]}
    assert cc.checked_expectation(["A", "C"], ["A", "C"], coverage)["uncovered"] == [
        {"chain_auth": "C", "coverage": "chain_not_listed"}]
    assert cc.checked_expectation([], ["A"], coverage)["status"] == "not_checked"     # no position: never checked


def test_c1_expectation_from_the_archived_set_and_the_1a30_file():
    expect = cc.c1_expectation(_set_dir(), _need(FIXTURES / "public_1a30.cif"))
    assert expect["setHash"] == json.loads((ARCHIVE / "active.json").read_text())["set_hash"]
    assert expect["coverage"] == {"A": "covered", "B": "covered"}
    assert expect["catalytic"] == {"ARG A:8": [], "ASP A:25": [[175, 1, True]], "THR A:26": [[175, 2, True]],
                                   "ASP B:25": [[175, 5, True]], "GLY B:27": [[175, 0, True]]}
    assert expect["partial"] == {"status": "not_checked", "reason": "chains_not_covered", "covered": ["A"],
                                 "uncovered": [{"chain_auth": "B", "coverage": "not_in_annotation"}],
                                 "counts": {"matched_rows": 3, "conflict_rows": 0, "unmatched_rows": 0},
                                 "protected": ["ASP A:25", "THR A:26"]}
    assert expect["all"]["status"] == "checked" and expect["all"]["reason"] is None
    assert expect["all"]["counts"] == {"matched_rows": 6, "conflict_rows": 0, "unmatched_rows": 0}
    assert expect["all"]["protected"] == ["ASP A:25", "ASP B:25", "GLY B:27", "THR A:26"]
    assert expect["release"] == {"residue": "ASP A:25", "catalytic": [[175, 1, True]]}
    assert expect["reportRender"] == "mutation_candidates_markdown@2"


def test_c1_expectation_refuses_a_position_that_is_not_in_the_structure():
    spec = {**cc.C1, "residues": [*cc.C1["residues"], {"resname": "TRP", "chain": "A", "seq": 25}]}
    with pytest.raises(ValueError):
        cc.c1_expectation(_set_dir(), FIXTURES / "public_1a30.cif", spec)


# ---------------------------------------------------------------------------------------------------- C2 (1UBQ)
def test_ubq_expectation_counts_the_m7_preflight_and_the_m20_candidates():
    expect = cc.ubq_expectation(_need(FIXTURES / "public_1ubq.cif"))
    assert expect["proteinHeavyAtoms"] == 602 and expect["waters"] == 58      # T1 (c): 602 heavy atoms, 58 excluded
    assert expect["residueNames"] == {3: "ILE", 6: "LYS", 44: "ILE", 76: "GLY"}
    assert [f"{x['residue']} {x['from']}→{x['to']}" for x in expect["candidates"]] == [
        "LYS A:6 K→A", "LYS A:6 K→W", "ILE A:44 I→A", "ILE A:44 I→W", "GLY A:76 G→A", "GLY A:76 G→W"]
    assert expect["space"] == {"positions": 3, "candidates": 6, "effective_max_mutations": 3, "size": 26}
    assert expect["modelTarget"] == {"residue": "ILE A:44", "from": "I", "to": "W"}
    assert expect["loopPool"] == ["LYS A:6 K→A", "LYS A:6 K→W", "ILE A:44 I→A"]
    assert expect["positions"] == 4 and expect["candidatePositions"] == 3


def test_ubq_expectation_refuses_a_wrong_residue_name():
    with pytest.raises(ValueError):
        cc.ubq_expectation(FIXTURES / "public_1ubq.cif", {**cc.C2, "residues": [["TRP", 3]], "protect": []})


def test_space_size_is_the_sum_of_elementary_symmetric_polynomials():
    assert cc.space_size([2, 2, 2], 3) == 6 + 12 + 8
    assert cc.space_size([2, 2, 2], 1) == 6
    assert cc.space_size([3, 1], 4) == 4 + 3
    assert cc.space_size([], 3) == 0


# ---------------------------------------------------------------------------------------------------- GA settings
def test_ga_ranges_are_read_as_text_and_the_two_settings_fit():
    constants = cc.ga_ranges(REPO)
    assert constants["GA_RANGES"]["population_size"] == (4, 16, 8)
    assert constants["UNITS_PER_EVALUATION"] == 2 and constants["SECONDS_PER_UNIT"] == 270
    for setting in (cc.GA_SETTING_1, cc.GA_SETTING_2):
        assert cc.ga_problems(setting, constants, 26) == []
    assert cc.settings_differ(cc.GA_SETTING_1, cc.GA_SETTING_2) == ["population_size", "generations", "random_fraction"]
    assert cc.GA_SETTING_1["seed"] == cc.GA_SETTING_2["seed"] == 21
    assert cc.ga_need(cc.GA_SETTING_1, constants) == {"reservedEvaluations": 10, "reserved": 22, "neededWall": 1200,
                                                       "mayBePartial": True}
    assert cc.ga_need(cc.GA_SETTING_2, constants) == {"reservedEvaluations": 6, "reserved": 14, "neededWall": 1200,
                                                       "mayBePartial": True}


def test_ga_problems_name_each_range_and_cross_rule():
    constants = cc.ga_ranges(REPO)
    named = {problem.split("=")[0] for problem in cc.ga_problems({**cc.GA_SETTING_1, "population_size": 17,
                                                                  "random_fraction": 0.6}, constants)}
    assert named >= {"population_size", "random_fraction"}
    assert "population_size - elite_count below MIN_NEW_SLOTS" in cc.ga_problems(
        {**cc.GA_SETTING_1, "elite_count": 3}, constants)
    assert "max_new_evaluations below population_size" in cc.ga_problems(
        {**cc.GA_SETTING_1, "population_size": 8, "max_new_evaluations": 6}, constants)
    assert "combination space below population_size" in cc.ga_problems(cc.GA_SETTING_2, constants, 5)
    assert cc.ga_problems({key: value for key, value in cc.GA_SETTING_1.items() if key != "seed"}, constants)


def test_ga_ranges_never_import_the_product(tmp_path):
    (tmp_path / "backend/mw").mkdir(parents=True)
    (tmp_path / cc.SEQ_GA_CONSTANTS).write_text(
        "GA_RANGES = {'seed': (0, 1, None)}\nMIN_NEW_SLOTS = 2\nUNITS_PER_EVALUATION = 2\nSECONDS_PER_UNIT = 270\n"
        "NEED_MARGIN_S = 300\nFINISH_MARGIN_S = 600\nraise SystemExit('executed')\n")
    assert cc.ga_ranges(tmp_path)["GA_RANGES"] == {"seed": (0, 1, None)}
    (tmp_path / cc.SEQ_GA_CONSTANTS).write_text("GA_RANGES = dict(seed=(0, 1, None))\n")
    with pytest.raises(ValueError):
        cc.ga_ranges(tmp_path)


# ---------------------------------------------------------------------------------------------------- units
def test_unit_plan_of_the_fixture_phase_is_the_coordinators_budget():
    plan = cc.unit_plan("fixture")
    assert plan["remainingBefore"] == {"C2-m7": 8, "C2-m21": 7, "C3-pair": 6, "C6-explore": 4, "C6-exploit": 2,
                                       "C4-1": 0, "C4-2": 0}
    assert plan["raises"] == {"C4-1": 22, "C4-2": 14}
    assert plan["totalUsed"] == plan["finalLimit"] == 44 and plan["finalRemaining"] == 0
    # the work no raise can cover (M7 + M21 + C3 pair + C6) is exactly the default 8 (no margin)
    assert sum(units for label, units in plan["units"].items() if not label.startswith("C4")) == 8


def test_unit_plan_of_the_live_phase_has_no_raise():
    plan = cc.unit_plan("live")
    assert plan["units"] == {"C2-m7": 1, "C2-m21": 1, "C6-explore": 2} and plan["raises"] == {}
    assert plan["remainingBefore"]["C6-explore"] == 6 and plan["totalUsed"] == 4


def test_unit_plan_refuses_a_plan_that_does_not_add_up(monkeypatch):
    monkeypatch.setitem(cc.UNIT_PLAN, "live", {"C2-m7": 9})
    with pytest.raises(ValueError):
        cc.unit_plan("live")
    monkeypatch.setitem(cc.UNIT_PLAN, "live", {"C4-1": 22})
    monkeypatch.setitem(cc.RAISES, "live", {"C4-1": 20})
    with pytest.raises(ValueError):
        cc.unit_plan("live")


# ---------------------------------------------------------------------------------------------------- plan
def test_plan_is_json_with_the_inputs_and_without_core_forbidden_words():
    plan = cc.build_plan(REPO, "fixture", _set_dir())
    text = json.dumps(plan, ensure_ascii=False)
    assert json.loads(text)["schema"] == cc.PLAN_SCHEMA and plan["live"] is None
    assert {key: plan["inputs"][key]["rel"] for key in plan["inputs"]} == {key: rel for key, (rel, _l, _s) in
                                                                            cc.INPUTS.items()}
    assert [key for key, item in plan["inputs"].items() if item["syntheticLabeled"]] == ["phenol"]
    assert plan["structures"] == {"c1": "1A30", "c2": "1UBQ", "same": False}
    assert plan["c1"]["expect"]["all"]["status"] == "checked" and plan["c2"]["waters"] == "keep_all"
    assert plan["loops"]["explore"]["script"] in ("good", "good_second")
    assert plan["loops"]["exploit"]["script"] in ("good", "good_second")
    assert plan["send"]["script"] in ("good", "good_second") and plan["send"]["pick"] >= 2
    assert not c.CORE_FORBIDDEN.search(text), "the plan would add X4 hits to the evidence"
    live = cc.build_plan(REPO, "live", None, send_allowed=False, dispatch_limit=3)
    assert live["live"] == {"sendAllowed": False, "dispatchLimit": 3} and live["c1"] is None
    with pytest.raises(ValueError):
        cc.build_plan(REPO, "other", None)


def test_build_plan_refuses_settings_outside_the_ranges(monkeypatch):
    monkeypatch.setattr(cc, "GA_SETTING_2", {**cc.GA_SETTING_1, "generations": 9})
    with pytest.raises(ValueError):
        cc.build_plan(REPO, "live", None)
    monkeypatch.setattr(cc, "GA_SETTING_2", {**cc.GA_SETTING_1, "generations": 2})
    with pytest.raises(ValueError):                         # one parameter differs only
        cc.build_plan(REPO, "live", None)


# ---------------------------------------------------------------------------------------------------- judgement
def _plan(phase="fixture"):
    plan = cc.build_plan(REPO, phase, _set_dir() if phase == "fixture" else None)
    return plan


def _observed(plan):
    e1, e2 = plan["c1"]["expect"], plan["c2"]["expect"]
    sets = {name: {key: e1[name][key] for key in ("status", "reason", "covered", "uncovered", "counts")}
            for name in ("partial", "all")}
    return {
        "C1": {"sets": sets, "catalytic": e1["catalytic"], "protected": e1["all"]["protected"],
               "release": {"residue": "ASP A:25", "status": "candidate", "released": True,
                           "catalytic": e1["release"]["catalytic"]},
               "report": {"renderVersion": "mutation_candidates_markdown@2", "setHashes": [e1["setHash"]]}},
        "C2": {"m7": {"heavyAtoms": 602, "excluded": 58},
               "set": {"positions": 4,
                       "candidates": [f"{x['residue']} {x['from']}→{x['to']}" for x in e2["candidates"]]},
               "model": {"target": e2["modelTarget"], "sideBySideMismatches": 0, "contactMismatches": 0,
                         "differenceKeys": [], "energyUnit": "kJ/mol"}, "units": [1, 1]},
        "C3": {"scoresFirstMode": True, "units": 2},
        "C4": {"settings": {key: {"reserved": need["reserved"], "reservedEvaluations": need["reservedEvaluations"],
                                  "space": e2["space"]} for key, need in plan["ga"]["need"].items()},
               "reuseMismatches": 0},
        "C5": {"bodyHashEqual": True, "limitationsOk": True},
        "C6": {"explore": {"bodyHasScore": False, "computedSent": 1, "vacuous": False},
               "exploit": {"bodyScoresStored": True}},
        "C7": {"listed": 9, "created": 9, "downloadMismatches": 0}}


def _row(**change):
    return {"status": "pass", "offscreenComplete": True, "externalRequestCount": 0, "fixtureProof": True, **change}


def _handles(reports, status=201):
    return [{"case": case, "kind": kind, "httpStatus": status, "handle": f"obj://run_x/method_report_manifest/{n}"}
            for case, kinds in reports.items() for kind, count in kinds.items() for n in range(count)]


def _evidence(plan, **parts):
    states = {name: {"status": "pass"} for name in cc.CASES}
    states.update(parts)
    return {"parts": states, "observed": _observed(plan), "reportHandles": _handles(cc.REPORTS["fixture"])}


def _by_id(records):
    return {record["id"]: record for record in records}


def test_compare_observed_flags_each_independent_mismatch():
    plan = _plan()
    assert cc.compare_observed(plan, _observed(plan)) == {}
    bad = _observed(plan)
    bad["C1"]["sets"]["partial"]["status"] = "checked"            # the checked rule broken
    bad["C2"]["model"]["differenceKeys"] = ['"energy_delta']
    bad["C3"]["scoresFirstMode"] = False
    bad["C4"]["reuseMismatches"] = 1
    bad["C5"]["bodyHashEqual"] = False
    bad["C6"]["explore"]["bodyHasScore"] = True
    bad["C7"]["listed"] = 8
    assert set(cc.compare_observed(plan, bad)) == set(cc.CASES)
    one = _observed(plan)
    one["C1"]["report"]["setHashes"] = ["0" * 64]
    assert list(cc.compare_observed(plan, one)) == ["C1"]
    one = _observed(plan)
    one["C1"]["protected"] = []
    assert list(cc.compare_observed(plan, one)) == ["C1"]
    one = _observed(plan)
    one["C2"]["m7"]["excluded"] = 0
    assert list(cc.compare_observed(plan, one)) == ["C2"]
    assert cc.compare_observed(plan, {}) == {}              # nothing observed: the harness part decides


def test_compare_observed_judges_the_live_part_by_the_c2_rule():
    plan = _plan("live")
    observed = {"L-pre-C2": {**_observed(_plan())["C2"]}}
    assert cc.compare_observed(plan, observed) == {}
    observed["L-pre-C2"]["units"] = [1, 2]
    assert list(cc.compare_observed(plan, observed)) == ["L-pre-C2"]


def test_case_records_map_parts_to_spec_cases():
    plan = _plan()
    records = _by_id(cc.case_records(_row(), _evidence(plan), plan, ["x"]))
    assert list(records) == list(cc.CASES) and all(r["status"] == "pass" for r in records.values())
    assert all(not c.case_problems(r) for r in records.values())
    blocked = _by_id(cc.case_records(_row(), _evidence(plan, C2={"status": "fail"},
                                                       C3={"status": "not_run", "blockedBy": ["C2"]}), plan, []))
    assert blocked["C2"]["reason"] == "harness_assertion_failed"
    assert (blocked["C3"]["status"], blocked["C3"]["reason"]) == ("not_observed", "prerequisite_failed:C2")
    setup = _by_id(cc.case_records(_row(), _evidence(plan), plan, [],
                                   setup={"C1": {"status": "fail", "reason": "reaction_set_copy_failed"}}))
    assert (setup["C1"]["status"], setup["C1"]["reason"]) == ("fail", "reaction_set_copy_failed")


def test_case_records_fail_on_mismatch_unclean_row_and_missing_parts():
    plan = _plan()
    bad = _evidence(plan)
    bad["observed"]["C1"]["sets"]["all"]["status"] = "not_checked"
    assert _by_id(cc.case_records(_row(), bad, plan, []))["C1"]["reason"] == "independent_expectation_mismatch"
    for row in (_row(fixtureProof=False), _row(externalRequestCount=1), _row(offscreenComplete=False)):
        assert {r["reason"] for r in cc.case_records(row, _evidence(plan), plan, [])} == {"harness_row_not_clean"}
    nothing = _by_id(cc.case_records(None, None, plan, []))
    assert {(r["status"], r["reason"]) for r in nothing.values()} == {("fail", "case_not_completed")}


def test_case_records_of_the_live_phase_leave_l_c6_to_the_live_outcome():
    plan = _plan("live")
    evidence = {"parts": {name: {"status": "pass"} for name in cc.LIVE_PARTS}, "observed": {},
                "reportHandles": _handles(cc.REPORTS["live"])}
    records = _by_id(cc.case_records(_row(fixtureProof=None), evidence, plan, [], phase="live"))
    assert list(records) == ["L-pre-C2"] and records["L-pre-C2"]["status"] == "pass"
    rehearsal = _by_id(cc.case_records(_row(fixtureProof=None), evidence, plan, [], phase="live", rehearse=True))
    assert rehearsal["L-pre-C2"]["reason"] == "harness_row_not_clean"


def _live(send=None, compute=None, guard=None, egress=None):
    return {"live": {"send": send, "compute": compute, "guard": guard, "egressStop": egress}}


def test_live_result_follows_spec_6_3():
    ok = {"L-pre-C2": {"status": "pass"}}
    done = {"dispatched": True, "status": "completed"}
    assert cc.live_result(_live(done, {"state": "scored"}), ok, True) == ("completed", None)
    assert cc.live_result(_live(done, {"state": "null_result"}), ok, True) == ("completed", None)
    assert cc.live_result(_live(done, {"state": "failed"}), ok, True) == ("product_failed", None)
    assert cc.live_result(_live(done, None), ok, True) == ("product_failed", None)
    assert cc.live_result(_live(done, {"state": "scored"}, egress="usage_unknown"), ok, True) == ("product_failed",
                                                                                                  None)
    for reason in cc.PROVIDER_FAILURES:
        assert cc.live_result(_live({"dispatched": True, "status": "failed", "reasonCode": reason}), ok, True)[0] == \
            "provider_failed"
    for reason in ("response_invalid", "model_mismatch", "outcome_not_recorded"):
        assert cc.live_result(_live({"dispatched": True, "status": "failed", "reasonCode": reason}), ok, True)[0] == \
            "product_failed"
    blocked = {"L-pre-C2": {"status": "fail"}}
    assert cc.live_result(_live(), blocked, True) == ("not_sent", "prerequisite_failed:L-pre-C2")
    assert cc.live_result(_live(guard="dispatch events 1 ≥ the limit 1"), ok, True) == ("not_sent", "ledger_refused")
    assert cc.live_result(_live(), ok, False) == (None, None)
    assert cc.live_result(None, ok, True) == ("product_failed", None)
    assert c.live_case_status("not_sent", not_sent_cause="prerequisite_failed:L-pre-C2") == (
        "not_observed", "not_sent:prerequisite_failed:L-pre-C2")


def test_observations_tab_texts_and_step_folder(tmp_path):
    (tmp_path / "texts").mkdir()
    (tmp_path / "texts/p.tabtext").write_text("panel text")
    evidence = {"x5": [{"ok": True, "detail": "d1"}, {"ok": False, "detail": "d2"}],
                "texts": {"protein@C1": "texts/p.tabtext", "gone": "texts/none.tabtext"}}
    assert cc.observations(evidence) == [(True, "d1"), (False, "d2")]
    assert cc.tab_texts(tmp_path, evidence) == {"protein@C1": "panel text"}
    first, second = tmp_path / "c-endtoend", tmp_path / "c-endtoend-20261011T000000"
    for folder in (first, second):
        folder.mkdir()
        (folder / cc.EVIDENCE_FILE).write_text("{}")
    assert cc.step_folder({"artifacts": str(first)}) == first
    os.utime(first, (1, 1))
    assert cc.step_folder({}) is None and cc.step_folder(None) is None      # never another attempt's folder


def _ctx(tmp_path, phase="fixture", flow=None, send_allowed=True, live_calls=0, rehearse=False):
    return c.BranchContext(
        phase=phase, rehearse=rehearse, branch="c", code=REPO, root=tmp_path, stage=tmp_path / phase,
        runs=tmp_path / "runs", reference=tmp_path / "reference", precedent=tmp_path / "precedent",
        reaction=tmp_path / "reaction", artifacts=tmp_path / "artifacts" / "c", kbase=tmp_path / "kbase",
        m15_reference=tmp_path / "m15", reaction_set=ARCHIVE, python=Path("/py"),
        api=c.Api(), flow=flow or (lambda *args, **kwargs: None), record=lambda *args, **kwargs: None,
        child_env=lambda extra=None: {}, fixture={"control": tmp_path / "control", "pid": 4242},
        live_calls=live_calls, send_allowed=send_allowed)


def test_run_copies_the_set_and_reports_every_case_failed_without_a_row(tmp_path):
    calls = []

    def flow(step, harness, mode, extra, limit=None):
        calls.append((step, harness, mode, extra))
    result = cc.run(_ctx(tmp_path, flow=flow))
    plan_file = tmp_path / "artifacts/c/plan.json"
    assert calls == [("c-endtoend", cc.HARNESS, "fixture", ["--plan", str(plan_file), "--control",
                                                          str(tmp_path / "control"), "--backend-pid", "4242"])]
    plan = json.loads(plan_file.read_text())
    assert plan["phase"] == "fixture" and plan["c1"]["expect"]["setHash"] == result.notes["reactionCopy"]["setHash"]
    assert result.notes["reactionCopy"]["status"] == "pass" and result.notes["reactionCopy"]["copiedBy"] == "branch"
    assert {(record["id"], record["status"], record["reason"]) for record in result.cases} == {
        (case, "fail", "case_not_completed") for case in cc.CASES}
    assert result.runs == [] and result.reports_created is None and result.live == {}
    assert result.notes["defaultFoldersBefore"] == result.notes["defaultFoldersAfter"]
    assert result.notes["syntheticInputs"] == ["phenol"]
    assert result.notes["structures"] == {"c1": "1A30", "c2": "1UBQ", "same": False}


def _dispatch(runs, run="run_c1"):
    folder = Path(runs) / run
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "events.jsonl").open("a") as out:
        out.write(json.dumps({"type": "jev_science_dispatch_started"}) + "\n")


def _harness_evidence(extra, mode, **content):
    plan = Path(extra[extra.index("--plan") + 1])
    return {"planSha256": hashlib.sha256(plan.read_bytes()).hexdigest(), "mode": mode, **content}


def test_run_live_reads_the_harness_evidence_and_gives_the_round_result(tmp_path):
    (tmp_path / "runs").mkdir()
    limits = []

    def flow(step, harness, mode, extra, limit=None):
        limits.append(limit)
        _dispatch(tmp_path / "runs")
        folder = tmp_path / "artifacts" / step
        folder.mkdir(parents=True)
        (folder / cc.EVIDENCE_FILE).write_text(json.dumps(_harness_evidence(
            extra, mode, run="run_c1", reportsCreated=5, reportHandles=_handles(cc.REPORTS["live"]),
            parts={name: {"status": "pass"} for name in cc.LIVE_PARTS}, observed={},
            live={"send": {"dispatched": True, "status": "completed"}, "compute": {"state": "scored"}})))
        return {"artifacts": str(folder), "offscreenComplete": True, "externalRequestCount": 0, "fixtureProof": True}
    result = cc.run(_ctx(tmp_path, phase="live", flow=flow, live_calls=1, rehearse=True))
    assert result.live == {"L-C6": "completed"} and result.not_sent_causes == {}
    records = _by_id(result.cases)
    assert records["L-C6"]["status"] == "pass" and records["L-pre-C2"]["status"] == "pass"
    assert result.runs == ["run_c1"] and result.reports_created == 5 and result.notes["dispatchLimit"] == 1
    assert limits == [1] and result.notes["dispatchedDuringFlow"] == 1
    plan = json.loads((tmp_path / "artifacts/c/plan.json").read_text())
    assert plan["live"] == {"sendAllowed": True, "dispatchLimit": 1} and plan["c1"] is None
    assert not (tmp_path / "reaction").exists()             # the live phase has no C1 and copies no set


def test_run_live_without_the_send_allowed_leaves_the_cause_to_the_runner(tmp_path):
    def flow(step, harness, mode, extra, limit=None):
        folder = tmp_path / "artifacts" / step
        folder.mkdir(parents=True)
        (folder / cc.EVIDENCE_FILE).write_text(json.dumps(_harness_evidence(
            extra, mode, run="run_c1", parts={"L-pre-C2": {"status": "pass"}}, observed={},
            reportHandles=_handles(cc.REPORTS["live"]), live={"send": None, "guard": None})))
        return {"artifacts": str(folder), "offscreenComplete": True, "externalRequestCount": 0, "fixtureProof": None}
    result = cc.run(_ctx(tmp_path, phase="live", flow=flow, send_allowed=False, live_calls=2))
    assert result.live == {} and result.not_sent_causes == {}
    missing = cc.run(_ctx(tmp_path / "second", phase="live", send_allowed=True, live_calls=1))
    assert missing.live == {"L-C6": "not_sent"} and missing.not_sent_causes == {"L-C6": "prerequisite_failed:L-pre-C2"}
    assert _by_id(missing.cases)["L-C6"]["reason"] == "not_sent:prerequisite_failed:L-pre-C2"
    assert cc.run(_ctx(tmp_path, phase="other")).notes["error"].startswith("unknown phase")


def test_branch_module_never_imports_mw_or_calls_limit_routes():
    source = Path(cc.__file__).read_text()
    tree = ast.parse(source)
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "mw" not in imported and "importlib" not in imported and "urllib" not in imported
    assert "limit_approval" not in source and "raise_limits" not in source
    assert "/jev" not in source


def test_harness_file_is_present_with_its_sources_named():
    text = HARNESS.read_text()
    for source in ("mutation-flow.cjs", "mutation-model-flow.cjs", "sequence-ga-flow.cjs", "jev-flow.cjs",
                   "jev-loop-flow.cjs", "openmm-flow.cjs", "endtoend-b-flow.cjs"):
        assert f"copied from {source}" in text.lower() or f"adapted from {source}" in text.lower(), source
    assert "m28_branch_c_plan@1" in text and "ledger-row.json" in text and "m28_branch_c_row@1" in text
    assert shutil.which("node"), "node is needed by the offscreen harness"
    subprocess.run(["node", "--check", str(HARNESS)], check=True)


def test_harness_loop_pool_follows_the_plan_rule():
    """The harness maps the plan's pool (residue and substitution text) to the stored candidate indices in set order."""
    assert shutil.which("node"), "node is needed by the offscreen harness"
    plan = cc.build_plan(REPO, "live", None)
    residue = {"LYS": 6, "ILE": 44, "GLY": 76}
    rows = [{"index": i, "residue": {"resname": name, "chain_auth": "A", "seq_auth": residue[name], "icode": ""},
             "from": src, "to": dst} for i, (name, src, dst) in enumerate(
        [("LYS", "K", "A"), ("LYS", "K", "W"), ("ILE", "I", "A"), ("ILE", "I", "W"), ("GLY", "G", "A"),
         ("GLY", "G", "W")])]
    script = ("const h=require(process.argv[1]);const fs=require('fs');const x=JSON.parse(fs.readFileSync(0,'utf8'));"
              "process.stdout.write(JSON.stringify(h.loopPoolRefs(x.plan,x.rows)));")
    done = subprocess.run(["node", "-e", script, str(HARNESS)], input=json.dumps({"plan": plan, "rows": rows}),
                          capture_output=True, text=True, check=True, cwd=REPO / "frontend")
    assert json.loads(done.stdout) == [0, 1, 2]


# ---------------------------------------------------------------------------------------------------- T11 (review)
def test_live_result_counts_the_dispatch_events_not_the_harness_report():
    ok = {"L-pre-C2": {"status": "pass"}}
    blocked = {"L-pre-C2": {"status": "fail"}}
    for evidence in (None, _live(), _live(guard="dispatch events 1 ≥ the limit 1")):
        for records in (ok, blocked):
            for allowed in (True, False):
                assert cc.live_result(evidence, records, allowed, dispatched=1) == ("product_failed", None)
    assert cc.live_result(_live(), blocked, True, dispatched=0) == ("not_sent", "prerequisite_failed:L-pre-C2")


def test_run_live_gives_product_failed_when_the_harness_sent_and_left_no_evidence(tmp_path):
    (tmp_path / "runs").mkdir()

    def flow(step, harness, mode, extra, limit=None):
        _dispatch(tmp_path / "runs")
    result = cc.run(_ctx(tmp_path, phase="live", flow=flow, live_calls=1, rehearse=True))
    assert result.live == {"L-C6": "product_failed"}


def test_c7_is_not_observed_until_every_earlier_case_passed():
    plan = _plan()
    for failed in ("C1", "C3", "C4", "C6"):
        records = _by_id(cc.case_records(_row(), _evidence(plan, **{failed: {"status": "fail"}}), plan, []))
        assert (records["C7"]["status"], records["C7"]["reason"]) == ("not_observed", f"prerequisite_failed:{failed}")


def test_a_case_whose_expected_report_is_missing_fails():
    plan = _plan()
    assert plan["reports"] == {"C1": {"mutation_candidates": 1}, "C2": {"openmm_protein_minimize": 1,
                                                                        "mutation_candidates": 1, "mutation_model": 1},
                               "C3": {}, "C4": {"sequence_ga": 2}, "C5": {"jev_choice": 1}, "C6": {"jev_loop": 2},
                               "C7": {}}
    evidence = _evidence(plan)
    evidence["reportHandles"] = [item for item in evidence["reportHandles"] if item["kind"] != "mutation_model"]
    records = _by_id(cc.case_records(_row(), evidence, plan, []))
    assert (records["C2"]["status"], records["C2"]["reason"]) == ("fail", "expected_report_missing")
    assert records["C7"]["reason"] == "prerequisite_failed:C2"
    assert records["C3"]["reason"] == "prerequisite_failed:C2"
    assert list(cc.compare_observed(plan, {"C7": {"listed": 8, "created": 8, "downloadMismatches": 0}})) == ["C7"]


def test_c6_waits_for_the_pair_docking_it_reuses_and_its_explore_body_is_not_empty():
    """The fixture explore round includes the modelled candidate whose C3 docking is stored (reused, no unit), so
    "the explore body carries no score" is checked on a computed candidate (not vacuously)."""
    plan = _plan()
    records = _by_id(cc.case_records(_row(), _evidence(plan, C3={"status": "fail"}), plan, []))
    assert (records["C6"]["status"], records["C6"]["reason"]) == ("not_observed", "prerequisite_failed:C3")
    assert cc.PART_NEEDS["C6"] == ("C2", "C3")
    pools = plan["c2"]["expect"]
    assert pools["loopPoolFixture"] == ["LYS A:6 K→A", "LYS A:6 K→W", "ILE A:44 I→A", "ILE A:44 I→W"]
    assert pools["loopPool"] == ["LYS A:6 K→A", "LYS A:6 K→W", "ILE A:44 I→A"]
    empty = _observed(plan)
    empty["C6"]["explore"] = {"bodyHasScore": False, "computedSent": 0, "vacuous": True}
    assert list(cc.compare_observed(plan, empty)) == ["C6"]


def _harness_export(name):
    script = f"const h=require(process.argv[1]);process.stdout.write(JSON.stringify(h.{name}));"
    done = subprocess.run(["node", "-e", script, str(HARNESS)], capture_output=True, text=True, check=True,
                          cwd=REPO / "frontend")
    return json.loads(done.stdout)


def test_the_harness_needs_are_the_module_needs_and_the_cascade():
    assert _harness_export("NEEDS") == {name: list(value) for name, value in cc.PART_NEEDS.items()}
    for name, value in cc.PART_NEEDS.items():
        assert tuple(value) == c.PREREQUISITES.get(name, ()), name
    for order in (cc.FIXTURE_ORDER, cc.LIVE_PARTS):
        for index, name in enumerate(order):
            assert set(cc.PART_NEEDS[name]) <= set(order[:index]), name
    calls = re.findall(r"rec\.part\(([^,]+), ([^,]+),", HARNESS.read_text())
    assert calls and all(needs.startswith("NEEDS[") for _name, needs in calls), calls


def test_the_harness_restores_the_sequence_ga_preflight_wording_check():
    source = HARNESS.read_text()
    c4 = source[source.index("async function flowC4"):source.index("async function flowC7")]
    assert c4.count("gaForbidden(") >= 2                    # the preflight (sequence-ga-flow "GA 1 preflight") too


def test_evidence_of_another_plan_or_mode_fails_every_case(tmp_path):
    def flow(step, harness, mode, extra, limit=None):
        folder = tmp_path / "artifacts" / step
        folder.mkdir(parents=True)
        plan = Path(extra[extra.index("--plan") + 1])
        (folder / cc.EVIDENCE_FILE).write_text(json.dumps({
            "planSha256": hashlib.sha256(plan.read_bytes()).hexdigest(), "mode": "live", "run": "run_c1",
            "parts": {name: {"status": "pass"} for name in cc.CASES}}))
        return {"artifacts": str(folder), "offscreenComplete": True, "externalRequestCount": 0, "fixtureProof": True}
    result = cc.run(_ctx(tmp_path, flow=flow))
    assert {(record["status"], record["reason"]) for record in result.cases} == {("fail", "evidence_not_of_this_step")}
    assert result.notes["evidenceCheck"] == {"planSha256": True, "mode": False}
