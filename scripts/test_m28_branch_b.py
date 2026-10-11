"""Independent expectations and case judgement of the M28 branch B module (scripts/m28_branch_b.py); no service.

The input files are read from this repository (the ProLIF public example receptor and poses, the public-derived parent,
the labeled synthetic block lists and rules) and the GA ranges from the product constants file as text: a missing file
is a failure, never a skip (.dryforge/spec.md R1, plan T7).
"""

import ast
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from scripts import m28_branch_b as b
from scripts import m28_common as c

REPO = Path(b.__file__).resolve().parents[1]
FIXTURES = REPO / "backend/tests/fixtures"
HARNESS = REPO / "frontend/tests/offscreen" / b.HARNESS


def _need(path: Path) -> Path:
    assert path.exists(), f"required local input is missing (no skip): {path}"
    return path


# ---------------------------------------------------------------------------------------------------- input files
def test_receptor_pdb_atoms_of_the_prolif_example():
    atoms = b.pdb_atoms(_need(FIXTURES / "chemical/prolif-vina-rec.pdb"))
    assert len(atoms) == 4988
    assert Counter(atom["element"] for atom in atoms) == {"H": 2545, "C": 1623, "O": 412, "N": 393, "S": 15}
    assert atoms[0] == {"serial": 1, "name": "CAY", "altloc": "", "resname": "TYR", "chain": "A", "seq": 38,
                        "icode": "", "element": "C", "xyz": [5.44, 4.56, 22.88]}


def test_pdb_atoms_reads_fixed_columns_and_refuses_an_empty_file(tmp_path):
    line = "HETATM   12 ZN   ZN  B 101A     -1.000   2.500  10.125  1.00  0.00          ZN"
    (tmp_path / "x.pdb").write_text("HEADER\n" + line + "\nEND\n")
    assert b.pdb_atoms(tmp_path / "x.pdb") == [{"serial": 12, "name": "ZN", "altloc": "", "resname": "ZN", "chain": "B",
                                               "seq": 101, "icode": "A", "element": "ZN",
                                               "xyz": [-1.0, 2.5, 10.125]}]
    (tmp_path / "empty.pdb").write_text("HEADER\nEND\n")
    with pytest.raises(ValueError):
        b.pdb_atoms(tmp_path / "empty.pdb")


def test_sdf_records_of_the_pose_parent_and_block_files():
    poses = b.sdf_records(_need(FIXTURES / "chemical/prolif-vina-output.sdf"))
    assert len(poses) == 9 and all(record["atoms"] and len(record["atoms"]) == 79 for record in poses)
    assert poses[0]["title"] == "" and poses[0]["bonds"] == 86
    assert poses[0]["atoms"][0] == {"serial": 1, "element": "C", "xyz": [1.424, 1.34, 12.727]}
    parent = b.sdf_records(_need(FIXTURES / "docking/public-derived-parent-record0.sdf"))
    assert len(parent) == 1 and parent[0]["title"].startswith("PUBLIC-DERIVED-FIXTURE")
    assert parent[0]["atoms"] == poses[0]["atoms"]           # record 0 of the public poses (provenance)
    blocks = b.sdf_records(_need(FIXTURES / "ligand/synthetic-blocks.sdf"))
    assert len(blocks) == 10 and blocks[-1]["title"] == "sdf_bromomethane"


def test_sdf_records_keep_unreadable_records_counted(tmp_path):
    (tmp_path / "x.sdf").write_text("one\n\n\n  1  0  0  0  0  0  0  0  0  0999 V3000\nM  END\n$$$$\n"
                                    "two\n\n\n  1  0  0  0  0  0  0  0  0  0999 V2000\n"
                                    "    0.0000    1.0000    2.0000 O   0  0\nM  END\n$$$$\n")
    records = b.sdf_records(tmp_path / "x.sdf")
    assert [record["title"] for record in records] == ["one", "two"]
    assert records[0]["atoms"] is None
    assert records[1]["atoms"] == [{"serial": 1, "element": "O", "xyz": [0.0, 1.0, 2.0]}]


def test_block_counts_and_rule_texts():
    assert len(b.smiles_blocks(_need(FIXTURES / "ligand_ga/synthetic-ga-small-blocks.smi"))) == 10
    rules = json.loads(_need(FIXTURES / "ligand_ga/synthetic-ga-pool2000-rules.json").read_text())["rules"]
    assert b.rule_texts(FIXTURES / "ligand_ga/synthetic-ga-pool2000-rules.json") == rules[1:3]
    assert b.RULE_PICK == (2, 3)


# ---------------------------------------------------------------------------------------------------- GA settings
def test_ga_ranges_are_read_as_text_and_the_two_settings_fit():
    constants = b.ga_ranges(REPO)
    assert constants["GA_RANGES"]["population_size"] == (4, 24, 12)
    assert constants["MIN_NEW_SLOTS"] == 2 and constants["PER_CANDIDATE_S"] == 300
    for setting in (b.GA_SETTING_1, b.GA_SETTING_2):
        assert b.ga_problems(setting, constants) == []
    assert b.settings_differ(b.GA_SETTING_1, b.GA_SETTING_2) == ["generations", "random_fraction"]
    assert b.GA_SETTING_1["seed"] == b.GA_SETTING_2["seed"] and b.GA_SETTING_1["population_size"] == 4
    assert b.ga_need(b.GA_SETTING_1, constants) == {"reserved": 6, "neededWall": 1200, "mayBePartial": True}
    assert b.ga_need(b.GA_SETTING_2, constants) == {"reserved": 8, "neededWall": 1200, "mayBePartial": True}


def test_ga_problems_name_each_range_and_cross_rule():
    constants = b.ga_ranges(REPO)
    bad = {**b.GA_SETTING_1, "population_size": 25, "random_fraction": 0.6}
    named = {problem.split("=")[0] for problem in b.ga_problems(bad, constants)}
    assert named >= {"population_size", "random_fraction"}
    assert "population_size - elite_count below MIN_NEW_SLOTS" in b.ga_problems(
        {**b.GA_SETTING_1, "elite_count": 3}, constants)
    assert "max_new_dockings below population_size" in b.ga_problems(
        {**b.GA_SETTING_1, "population_size": 8, "max_new_dockings": 6}, constants)
    assert b.ga_problems({key: value for key, value in b.GA_SETTING_1.items() if key != "seed"}, constants)


def test_ga_ranges_never_import_the_product(tmp_path):
    (tmp_path / "backend/mw").mkdir(parents=True)
    (tmp_path / b.GA_CONSTANTS).write_text("GA_RANGES = {'seed': (0, 1, None)}\nMIN_NEW_SLOTS = 2\n"
                                           "PER_CANDIDATE_S = 300\nFINISH_MARGIN_S = 600\nNEED_MARGIN_S = 300\n"
                                           "raise SystemExit('executed')\n")
    assert b.ga_ranges(tmp_path)["GA_RANGES"] == {"seed": (0, 1, None)}
    (tmp_path / b.GA_CONSTANTS).write_text("GA_RANGES = dict(seed=(0, 1, None))\n")
    with pytest.raises(ValueError):
        b.ga_ranges(tmp_path)


# ---------------------------------------------------------------------------------------------------- units
def test_unit_plan_of_the_fixture_phase_is_the_coordinators_budget():
    plan = b.unit_plan("fixture")
    assert plan["remainingBefore"] == {"B1-prepare": 8, "B1-detect": 7, "B2-inspect": 6, "B2-enumerate": 5, "B3": 4,
                                       "B3-again": 3, "B7-explore": 3, "B7-exploit": 2, "B4": 1, "B5-1": 0, "B5-2": 0}
    assert plan["raises"] == {"B4": 1, "B5-1": 6, "B5-2": 8} and len(plan["raises"]) == 3
    assert plan["totalUsed"] == plan["finalLimit"] == 23 and plan["finalRemaining"] == 0
    # the work no raise can cover (B1 + B2 + B3 + B7) is 7 of the default 8
    assert sum(units for label, units in plan["units"].items() if label.split("-")[0] in ("B1", "B2", "B3", "B7")) == 7


def test_unit_plan_of_the_live_phase_has_no_margin_and_no_raise():
    plan = b.unit_plan("live")
    assert plan["units"] == {"B2-inspect": 1, "B2-enumerate": 1, "B3": 1, "B3-again": 0, "B4": 4, "B7-exploit": 1}
    assert plan["raises"] == {} and plan["remainingBefore"]["B7-exploit"] == 1 and plan["finalRemaining"] == 0
    assert b.BATCH["live"] == {"computed": 1, "new": 3, "newRows": 4}
    assert b.BATCH["fixture"] == {"computed": 3, "new": 1, "newRows": 2}


def test_unit_plan_refuses_a_plan_that_does_not_add_up(monkeypatch):
    monkeypatch.setitem(b.UNIT_PLAN, "live", {"B3": 9})
    with pytest.raises(ValueError):
        b.unit_plan("live")
    monkeypatch.setitem(b.UNIT_PLAN, "live", {"B4": 9})
    monkeypatch.setitem(b.RAISES, "live", {"B4": 2})
    with pytest.raises(ValueError):
        b.unit_plan("live")


# ---------------------------------------------------------------------------------------------------- plan
def test_plan_is_json_with_the_inputs_and_without_core_forbidden_words():
    plan = b.build_plan(REPO, "fixture")
    text = json.dumps(plan, ensure_ascii=False)
    assert json.loads(text)["schema"] == b.PLAN_SCHEMA and plan["live"] is None
    assert {key: plan["inputs"][key]["rel"] for key in plan["inputs"]} == {key: rel for key, (rel, _l, _s) in
                                                                            b.INPUTS.items()}
    assert sorted(key for key, item in plan["inputs"].items() if item["syntheticLabeled"]) == [
        "blocksSdf", "blocksSmiles", "rules"]
    assert plan["b2"]["smilesBlocks"] == 10 and plan["b2"]["sdfRecords"] == 10 and plan["poseRecords"] == 9
    assert plan["docking"] == b.DOCKING and plan["docking"]["center"] == ["3.41", "0.72", "11.31"]
    assert plan["loops"]["explore"]["script"] in ("good", "good_second")
    assert plan["loops"]["exploit"]["script"] in ("good", "good_second")
    assert not c.CORE_FORBIDDEN.search(text), "the plan would add X4 hits to the evidence"
    live = b.build_plan(REPO, "live", send_allowed=False, dispatch_limit=3)
    assert live["live"] == {"sendAllowed": False, "dispatchLimit": 3, "roundNeed": b.LIVE_ROUND_NEED}
    assert live["batch"] == b.BATCH["live"]
    with pytest.raises(ValueError):
        b.build_plan(REPO, "other")


def test_build_plan_refuses_settings_outside_the_ranges(monkeypatch):
    monkeypatch.setattr(b, "GA_SETTING_2", {**b.GA_SETTING_1, "generations": 9})
    with pytest.raises(ValueError):
        b.build_plan(REPO, "fixture")
    monkeypatch.setattr(b, "GA_SETTING_2", {**b.GA_SETTING_1, "generations": 3})
    with pytest.raises(ValueError):                         # one parameter differs only
        b.build_plan(REPO, "fixture")


# ---------------------------------------------------------------------------------------------------- geometry
def test_nearest_atom_and_contact_pairs_follow_the_m18_rule():
    atoms = [{"element": "O", "xyz": [0.0, 0.0, 0.0]}, {"element": "O", "xyz": [0.001, 0.0, 0.0]}]
    assert b.nearest_atom(atoms, "O", [0.0, 0.0, 0.0]) is None           # two candidates: no unique match
    assert b.nearest_atom(atoms[:1], "o", [0.0, 0.0, 0.001]) == atoms[0]
    assert b.nearest_atom(atoms[:1], "N", [0.0, 0.0, 0.0]) is None
    receptor = [{"element": "N", "xyz": [0, 0, 0], "chain": "A", "seq": 1, "icode": "", "resname": "GLY", "name": "N"},
                {"element": "H", "xyz": [0, 0, 1], "chain": "A", "seq": 1, "icode": "", "resname": "GLY", "name": "H"},
                {"element": "C", "xyz": [0, 0, 5], "chain": "A", "seq": 1, "icode": "", "resname": "GLY", "name": "CA"}]
    pose = [{"serial": 1, "element": "O", "xyz": [0, 0, 3]}, {"serial": 2, "element": "C", "xyz": [0, 0, 8.5]},
            {"serial": 3, "element": "H", "xyz": [0, 0, 0.5]}]
    pairs = b.contact_pairs(receptor, pose)
    assert [(p["ligandSerial"], p["name"], p["kind"]) for p in pairs] == [
        (1, "N", "polar_contact"), (1, "CA", "contact"), (2, "CA", "hydrophobic_contact")]
    assert pairs[0]["distance_A"] == 3.0 and all(p["distance_A"] <= b.CONTACT_CUTOFF_A for p in pairs)


def test_contact_pairs_of_the_public_pose_equal_the_harness_recomputation():
    """The harness (JavaScript) and this module recompute the same receptor–pose contacts from the input files."""
    assert shutil.which("node"), "node is needed by the offscreen harness"
    plan = b.build_plan(REPO, "fixture")
    pose_text = (FIXTURES / "chemical/prolif-vina-output.sdf").read_text().split("$$$$")[0]
    mine = b.contact_pairs(plan["receptorAtoms"], plan["poseRecord0"])
    script = ("const h=require(process.argv[1]);const fs=require('fs');"
              "const plan=JSON.parse(fs.readFileSync(0,'utf8'));"
              "const out=h.recomputeContacts(plan.plan, plan.pose).map(p=>[p.key,p.distance,p.kind]);"
              "process.stdout.write(JSON.stringify(out));")
    done = subprocess.run(["node", "-e", script, str(HARNESS)], input=json.dumps({"plan": plan, "pose": pose_text}),
                          capture_output=True, text=True, check=True, cwd=REPO / "frontend")
    theirs = json.loads(done.stdout)
    assert len(mine) == len(theirs) > 0
    keyed = {f"{p['ligandSerial']}|{p['chain']}|{p['seq']}|{p['icode']}|{p['resname']}|{p['name']}": p for p in mine}
    for key, distance, kind in theirs:
        assert math.isclose(keyed[key]["distance_A"], distance, abs_tol=1e-9) and keyed[key]["kind"] == kind


# ---------------------------------------------------------------------------------------------------- judgement
def _plan(phase="fixture"):
    return {"phase": phase, "units": b.unit_plan(phase),
            "b2": {"minCandidates": 5, "sdfRecords": 10, "smilesBlocks": 10},
            "batch": b.BATCH[phase], "ga": {"need": {"1": {"reserved": 6}, "2": {"reserved": 8}}},
            "reports": b.REPORTS[phase]}


def _handles(reports, status=201):
    return [{"case": case, "kind": kind, "httpStatus": status, "handle": f"obj://run_x/method_report_manifest/{n}"}
            for case, kinds in reports.items() for kind, count in kinds.items() for n in range(count)]


def _observed():
    return {"B1": {"rows": 12, "rolesUnmatched": 0, "distanceMismatches": 0, "units": [1, 1]},
            "B2": {"candidates": 13, "filterMismatches": 0, "idMismatches": 0, "sdfBlocksSeen": 10,
                   "smilesBlocksSeen": 10},
            "B3": {"again": {"sameJob": True, "units": 0}, "contactMismatches": 0, "scoreIsFirstMode": True},
            "B4": {"newRows": 2, "rowScoreMismatches": 0},
            "B5": {"settings": {"1": {"reserved": 6}, "2": {"reserved": 8}}, "reuseMismatches": 0},
            "B7": {"explore": {"bodyHasScore": False, "computedSent": 1}, "exploit": {"bodyScoresStored": True}},
            "B8": {"listed": 9, "created": 9, "downloadMismatches": 0}}


def _row(**change):
    return {"status": "pass", "offscreenComplete": True, "externalRequestCount": 0, "fixtureProof": True, **change}


def _evidence(**parts):
    states = {name: {"status": "pass"} for name in b.CASES}
    states.update(parts)
    return {"parts": states, "observed": _observed(), "reportHandles": _handles(b.REPORTS["fixture"])}


def _by_id(records):
    return {record["id"]: record for record in records}


def test_compare_observed_flags_each_independent_mismatch():
    assert b.compare_observed(_plan(), _observed()) == {}
    bad = _observed()
    bad["B1"]["units"] = [1, 2]
    bad["B2"]["candidates"] = 4
    bad["B3"]["again"]["sameJob"] = False
    bad["B4"]["newRows"] = 3
    bad["B5"]["reuseMismatches"] = 1
    bad["B7"]["explore"]["bodyHasScore"] = True
    bad["B8"]["listed"] = 8
    problems = b.compare_observed(_plan(), bad)
    assert set(problems) == {"B1", "B2", "B3", "B4", "B5", "B7", "B8"}
    assert b.compare_observed(_plan(), {}) == {}            # nothing observed: the harness part decides


def test_compare_observed_judges_the_live_parts_by_their_case_rules():
    observed = {"L-pre-B2": _observed()["B2"], "L-pre-B3": _observed()["B3"], "L-pre-B4": {"newRows": 4,
                                                                                         "rowScoreMismatches": 0}}
    assert b.compare_observed(_plan("live"), observed) == {}
    observed["L-pre-B4"]["newRows"] = 5                     # one new row more would leave L-B7 without its unit
    assert list(b.compare_observed(_plan("live"), observed)) == ["L-pre-B4"]


def test_case_records_map_parts_to_spec_cases():
    records = _by_id(b.case_records(_row(), _evidence(), _plan(), ["x"]))
    assert list(records) == list(b.CASES) and all(r["status"] == "pass" for r in records.values())
    assert all(not c.case_problems(r) for r in records.values())
    blocked = _by_id(b.case_records(_row(), _evidence(B3={"status": "fail"},
                                                      B7={"status": "not_run", "blockedBy": ["B3"]}), _plan(), []))
    assert blocked["B3"]["reason"] == "harness_assertion_failed"
    assert (blocked["B7"]["status"], blocked["B7"]["reason"]) == ("not_observed", "prerequisite_failed:B3")
    assert c.reason_class(blocked["B7"]["reason"]) == "prerequisite"


def test_case_records_fail_on_mismatch_unclean_row_and_missing_parts():
    bad = _evidence()
    bad["observed"]["B2"]["filterMismatches"] = 2
    assert _by_id(b.case_records(_row(), bad, _plan(), []))["B2"]["reason"] == "independent_expectation_mismatch"
    for row in (_row(fixtureProof=False), _row(externalRequestCount=1), _row(offscreenComplete=False)):
        assert {r["reason"] for r in b.case_records(row, _evidence(), _plan(), [])} == {"harness_row_not_clean"}
    nothing = _by_id(b.case_records(None, None, _plan(), []))
    assert {(r["status"], r["reason"]) for r in nothing.values()} == {("fail", "case_not_completed")}


def test_case_records_of_the_live_phase_leave_l_b7_to_the_live_outcome():
    evidence = {"parts": {name: {"status": "pass"} for name in b.LIVE_PARTS}, "observed": {},
                "reportHandles": _handles(b.REPORTS["live"])}
    records = _by_id(b.case_records(_row(fixtureProof=None), evidence, _plan("live"), [], phase="live"))
    assert list(records) == ["L-pre-B2", "L-pre-B3", "L-pre-B4"]
    assert all(r["status"] == "pass" for r in records.values())                       # the real gate has no fixture
    rehearsal = _by_id(b.case_records(_row(fixtureProof=None), evidence, _plan("live"), [], phase="live",
                                      rehearse=True))
    assert {r["reason"] for r in rehearsal.values()} == {"harness_row_not_clean"}


def _live(send=None, compute=None, guard=None, egress=None):
    return {"live": {"send": send, "compute": compute, "guard": guard, "egressStop": egress}}


def test_live_result_follows_spec_6_3():
    ok = {f"L-pre-B{n}": {"status": "pass"} for n in (2, 3, 4)}
    done = {"dispatched": True, "status": "completed"}

    def sent(evidence, records=ok):                       # a send: exactly one dispatch event during the flow
        return b.live_result(evidence, records, True, dispatched=1)
    assert sent(_live(done, {"state": "scored"})) == ("completed", None)
    assert sent(_live(done, {"state": "null_result"})) == ("completed", None)
    assert sent(_live(done, {"state": "failed"})) == ("product_failed", None)
    assert sent(_live(done, {"state": "scored"}, egress="usage_unknown")) == ("product_failed", None)
    for reason in b.PROVIDER_FAILURES:
        assert sent(_live({"dispatched": True, "status": "failed", "reasonCode": reason}))[0] == "provider_failed"
    for reason in ("response_invalid", "model_mismatch", "missing_model", "outcome_not_recorded"):
        assert sent(_live({"dispatched": True, "status": "failed", "reasonCode": reason}))[0] == "product_failed"
    assert b.live_result(_live({"dispatched": True, "status": "rejected", "reasonCode": "missing_credential"}), ok,
                         True)[0] == "product_failed"
    blocked = {**ok, "L-pre-B4": {"status": "fail"}}
    assert b.live_result(_live(), blocked, True) == ("not_sent", "prerequisite_failed:L-pre-B4")
    assert b.live_result(_live(guard="dispatch events 1 ≥ the limit 1"), ok, True) == ("not_sent", "ledger_refused")
    assert b.live_result(_live(), ok, False) == (None, None)                    # the runner names the cause
    assert b.live_result(None, ok, True) == ("product_failed", None)
    status, reason = c.live_case_status("not_sent", not_sent_cause="prerequisite_failed:L-pre-B4")
    assert (status, reason) == ("not_observed", "not_sent:prerequisite_failed:L-pre-B4")


def test_observations_tab_texts_and_step_folder(tmp_path):
    (tmp_path / "texts").mkdir()
    (tmp_path / "texts/l.tabtext").write_text("panel text")
    evidence = {"x5": [{"ok": True, "detail": "d1"}, {"ok": False, "detail": "d2"}],
                "texts": {"ligand@B2": "texts/l.tabtext", "gone": "texts/none.tabtext"}}
    assert b.observations(evidence) == [(True, "d1"), (False, "d2")]
    assert b.observations(None) == []
    assert b.tab_texts(tmp_path, evidence) == {"ligand@B2": "panel text"}
    first, second = tmp_path / "b-endtoend", tmp_path / "b-endtoend-20261011T000000"
    for folder in (first, second):
        folder.mkdir()
        (folder / b.EVIDENCE_FILE).write_text("{}")
    assert b.step_folder({"artifacts": str(first)}) == first
    os.utime(first, (1, 1))
    # only the folder the ledger row names: never the newest folder of another attempt
    assert b.step_folder({}) is None and b.step_folder(None) is None
    assert b.step_folder({"artifacts": str(tmp_path / "gone")}) is None


def _ctx(tmp_path, phase="fixture", flow=None, send_allowed=True, live_calls=0, rehearse=False):
    return c.BranchContext(
        phase=phase, rehearse=rehearse, branch="b", code=REPO, root=tmp_path, stage=tmp_path / phase,
        runs=tmp_path / "runs", reference=tmp_path / "reference", precedent=tmp_path / "precedent",
        reaction=tmp_path / "reaction", artifacts=tmp_path / "artifacts" / "b", kbase=tmp_path / "kbase",
        m15_reference=tmp_path / "m15", reaction_set=tmp_path / "set", python=Path("/py"),
        api=c.Api(), flow=flow or (lambda *args, **kwargs: None), record=lambda *args, **kwargs: None,
        child_env=lambda extra=None: {}, fixture={"control": tmp_path / "control", "pid": 4242},
        live_calls=live_calls, send_allowed=send_allowed)


def test_run_reports_every_case_failed_when_the_harness_leaves_no_row(tmp_path):
    calls = []

    def flow(step, harness, mode, extra, limit=None):
        calls.append((step, harness, mode, extra))
    result = b.run(_ctx(tmp_path, flow=flow))
    plan_file = tmp_path / "artifacts/b/plan.json"
    assert calls == [("b-endtoend", b.HARNESS, "fixture", ["--plan", str(plan_file), "--control",
                                                          str(tmp_path / "control"), "--backend-pid", "4242"])]
    assert json.loads(plan_file.read_text())["phase"] == "fixture"
    assert {(record["id"], record["status"], record["reason"]) for record in result.cases} == {
        (case, "fail", "case_not_completed") for case in b.CASES}
    assert result.runs == [] and result.reports_created is None and result.live == {}
    assert result.notes["defaultFoldersBefore"] == result.notes["defaultFoldersAfter"]
    assert result.notes["syntheticInputs"] == {"parent": "공개 파생(합성 아님)", "blocksSmiles": "합성 표시",
                                               "blocksSdf": "합성 표시", "rules": "합성 표시"}


def _dispatch(runs, run="run_ab"):
    folder = Path(runs) / run
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "events.jsonl").open("a") as out:
        out.write(json.dumps({"type": "jev_science_dispatch_started"}) + "\n")


def _harness_evidence(extra, mode, **content):
    """Evidence the way the harness writes it: the SHA-256 of the plan file it was given and its mode."""
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
        (folder / b.EVIDENCE_FILE).write_text(json.dumps(_harness_evidence(
            extra, mode, run="run_ab", reportsCreated=4, reportHandles=_handles(b.REPORTS["live"]),
            parts={name: {"status": "pass"} for name in b.LIVE_PARTS},
            observed={"L-pre-B4": {"newRows": 4, "rowScoreMismatches": 0}},
            live={"send": {"dispatched": True, "status": "completed"}, "compute": {"state": "scored"}})))
        return {"artifacts": str(folder), "offscreenComplete": True, "externalRequestCount": 0, "fixtureProof": True}
    result = b.run(_ctx(tmp_path, phase="live", flow=flow, live_calls=1, rehearse=True))
    assert result.live == {"L-B7": "completed"} and result.not_sent_causes == {}
    records = _by_id(result.cases)
    assert records["L-B7"]["status"] == "pass" and records["L-pre-B4"]["status"] == "pass"
    assert result.runs == ["run_ab"] and result.reports_created == 4 and result.notes["dispatchLimit"] == 1
    assert limits == [1] and result.notes["dispatchedDuringFlow"] == 1      # the round limit reaches the runner
    plan = json.loads((tmp_path / "artifacts/b/plan.json").read_text())
    assert plan["live"] == {"sendAllowed": True, "dispatchLimit": 1,
                            "roundNeed": {"expensive_units": 1, "wall_clock_s": 300}}


def test_run_live_without_the_send_allowed_leaves_the_cause_to_the_runner(tmp_path):
    limits = []

    def flow(step, harness, mode, extra, limit=None):
        limits.append(limit)
        folder = tmp_path / "artifacts" / step
        folder.mkdir(parents=True)
        (folder / b.EVIDENCE_FILE).write_text(json.dumps(_harness_evidence(
            extra, mode, run="run_ab", reportHandles=_handles(b.REPORTS["live"]),
            parts={name: {"status": "pass"} for name in b.LIVE_PARTS[:3]}, observed={},
            live={"send": None, "guard": None})))
        return {"artifacts": str(folder), "offscreenComplete": True, "externalRequestCount": 0, "fixtureProof": None}
    result = b.run(_ctx(tmp_path, phase="live", flow=flow, send_allowed=False, live_calls=2))
    assert result.live == {} and result.not_sent_causes == {} and limits == [0]
    assert json.loads((tmp_path / "artifacts/b/plan.json").read_text())["live"] == {
        "sendAllowed": False, "dispatchLimit": 0, "roundNeed": {"expensive_units": 1, "wall_clock_s": 300}}
    missing = b.run(_ctx(tmp_path / "second", phase="live", send_allowed=True, live_calls=1))
    assert missing.live == {"L-B7": "not_sent"} and missing.not_sent_causes == {"L-B7": "prerequisite_failed:L-pre-B2"}
    assert _by_id(missing.cases)["L-B7"]["reason"] == "not_sent:prerequisite_failed:L-pre-B2"
    assert b.run(_ctx(tmp_path, phase="other")).notes["error"].startswith("unknown phase")


def test_branch_module_never_imports_mw_or_calls_limit_routes():
    source = Path(b.__file__).read_text()
    tree = ast.parse(source)
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "mw" not in imported and "importlib" not in imported and "urllib" not in imported
    assert "limit_approval" not in source and "raise_limits" not in source
    assert "/jev" not in source


def test_harness_file_is_present_with_its_sources_named():
    text = HARNESS.read_text()
    for source in ("chemical-flow.cjs", "ligand-flow.cjs", "docking-flow.cjs", "docking-batch-flow.cjs",
                   "ligand-ga-flow.cjs", "jev-flow.cjs", "jev-loop-flow.cjs", "tabs-flow.cjs", "endtoend-a-flow.cjs"):
        assert f"copied from {source}" in text.lower() or f"adapted from {source}" in text.lower(), source
    assert "m28_branch_b_plan@1" in text and "ledger-row.json" in text and "m28_branch_b_row@1" in text
    assert shutil.which("node"), "node is needed by the offscreen harness"
    subprocess.run(["node", "--check", str(HARNESS)], check=True)


# ---------------------------------------------------------------------------------------------------- T11 (review)
def test_live_result_counts_the_dispatch_events_not_the_harness_report():
    """R2: a dispatch event without the harness's send evidence (it died, timed out or was stopped) is product_failed,
    whatever else the evidence says; no dispatch keeps the not_sent rules."""
    ok = {f"L-pre-B{n}": {"status": "pass"} for n in (2, 3, 4)}
    blocked = {**ok, "L-pre-B4": {"status": "fail"}}
    for evidence in (None, _live(), _live(guard="dispatch events 1 ≥ the limit 1"),
                     _live({"dispatched": False, "status": "rejected", "reasonCode": "x"})):
        for records in (ok, blocked):
            for allowed in (True, False):
                assert b.live_result(evidence, records, allowed, dispatched=1) == ("product_failed", None)
    assert b.live_result(_live(), blocked, True, dispatched=0) == ("not_sent", "prerequisite_failed:L-pre-B4")
    done = {"dispatched": True, "status": "completed"}
    assert b.live_result(_live(done, {"state": "scored"}), ok, True, dispatched=1) == ("completed", None)


def test_run_live_gives_product_failed_when_the_harness_sent_and_left_no_evidence(tmp_path):
    (tmp_path / "runs").mkdir()

    def flow(step, harness, mode, extra, limit=None):
        _dispatch(tmp_path / "runs")                       # the click happened; the harness was stopped after it
    result = b.run(_ctx(tmp_path, phase="live", flow=flow, live_calls=1, rehearse=True))
    assert result.live == {"L-B7": "product_failed"} and result.not_sent_causes == {}
    assert _by_id(result.cases)["L-B7"]["reason"] == "product_failed"


def test_b8_is_not_observed_until_every_earlier_case_passed():
    """R3: B8 lists the reports B1–B7 made; it says nothing when one of them did not pass."""
    plan = _plan()
    for failed in ("B1", "B3", "B5", "B6"):
        records = _by_id(b.case_records(_row(), _evidence(**{failed: {"status": "fail"}}), plan, []))
        assert (records["B8"]["status"], records["B8"]["reason"]) == ("not_observed", f"prerequisite_failed:{failed}")
    chained = _by_id(b.case_records(_row(), _evidence(B7={"status": "fail"}), plan, []))
    assert chained["B4"]["reason"] == "prerequisite_failed:B7"            # the first need of B8 that is not pass
    assert chained["B8"]["reason"] == "prerequisite_failed:B4"
    blocked = _by_id(b.case_records(_row(), _evidence(B4={"status": "fail"}, B8={"status": "not_run",
                                                                                 "blockedBy": ["B4"]}), plan, []))
    assert blocked["B8"]["reason"] == "prerequisite_failed:B4"


def test_a_case_whose_expected_report_is_missing_fails():
    """R3: the reports each case must make (kind and count) are in the plan and compared with the harness's list."""
    plan = _plan()
    assert plan["reports"] == {"B1": {"chemical_interactions": 1}, "B2": {"ligand_candidates": 1},
                               "B3": {"ligand_docking": 1}, "B4": {"ligand_docking_batch": 1}, "B5": {"ligand_ga": 2},
                               "B6": {"jev_choice": 1}, "B7": {"jev_loop": 2}, "B8": {}}
    evidence = _evidence()
    evidence["reportHandles"] = [item for item in evidence["reportHandles"] if item["case"] != "B3"]
    records = _by_id(b.case_records(_row(), evidence, plan, []))
    assert (records["B3"]["status"], records["B3"]["reason"]) == ("fail", "expected_report_missing")
    assert records["B8"]["reason"] == "prerequisite_failed:B3"
    evidence = _evidence()
    evidence["reportHandles"].remove(next(item for item in evidence["reportHandles"] if item["kind"] == "ligand_ga"))
    assert _by_id(b.case_records(_row(), evidence, plan, []))["B5"]["reason"] == "expected_report_missing"
    evidence = _evidence()
    evidence["reportHandles"] = [{**item, "httpStatus": 422} if item["case"] == "B6" else item
                                 for item in evidence["reportHandles"]]
    assert _by_id(b.case_records(_row(), evidence, plan, []))["B6"]["reason"] == "expected_report_missing"
    assert list(b.compare_observed(plan, {"B8": {"listed": 8, "created": 8, "downloadMismatches": 0}})) == ["B8"]


def test_b4_and_b5_wait_for_the_state_they_use():
    """R5: B4 docks with B3's receptor, parent and values and lists B3's and both B7 candidates as stored results; B5
    uses B3's receptor, parent and values."""
    plan = _plan()
    records = _by_id(b.case_records(_row(), _evidence(B7={"status": "fail"}), plan, []))
    assert (records["B4"]["status"], records["B4"]["reason"]) == ("not_observed", "prerequisite_failed:B7")
    assert records["B5"]["status"] == "pass"
    records = _by_id(b.case_records(_row(), _evidence(B3={"status": "fail"}), plan, []))
    for case in ("B4", "B5", "B7"):
        assert (records[case]["status"], records[case]["reason"]) == ("not_observed", "prerequisite_failed:B3")
    assert b.PART_NEEDS["B4"] == ("B2", "B3", "B7") and b.PART_NEEDS["B5"] == ("B2", "B3")


def _harness_export(name):
    script = (f"const h=require(process.argv[1]);process.stdout.write(JSON.stringify(h.{name}));")
    done = subprocess.run(["node", "-e", script, str(HARNESS)], capture_output=True, text=True, check=True,
                          cwd=REPO / "frontend")
    return json.loads(done.stdout)


def test_the_harness_needs_are_the_module_needs_and_the_cascade():
    needs = _harness_export("NEEDS")
    assert needs == {name: list(value) for name, value in b.PART_NEEDS.items()}
    for name, value in b.PART_NEEDS.items():
        assert tuple(value) == c.PREREQUISITES.get(name, ()), name
    for order in (b.FIXTURE_ORDER, b.LIVE_PARTS):
        for index, name in enumerate(order):
            assert set(b.PART_NEEDS[name]) <= set(order[:index]), name
    calls = re.findall(r"rec\.part\(([^,]+), ([^,]+),", HARNESS.read_text())
    assert calls and all(needs.startswith("NEEDS[") for _name, needs in calls), calls


def test_the_harness_checks_the_batch_headers_and_the_area_wording():
    """R4: the batch table headers equal the M19 business-rule columns (no difference, rank or change column) and
    the batch and GA areas get the wording checks of the older harnesses."""
    assert _harness_export("BATCH_HEADERS") == ["행 번호", "후보 id", "상태", "qvina 점수(kcal/mol)", "점수 대상", "이유",
                                                "재사용", "상세"]
    script = ("const h=require(process.argv[1]);const t=JSON.parse(require('fs').readFileSync(0,'utf8'));"
              "process.stdout.write(JSON.stringify(t.map(x=>h.gaForbiddenWords(x,[]).map(f=>f.word))));")
    texts = ["이 개체가 승자", "추천 개체", "평균 비교", "부분 완료", "best pose", "점수 1.2 (kcal/mol)", "순위"]
    done = subprocess.run(["node", "-e", script, str(HARNESS)], input=json.dumps(texts), capture_output=True,
                          text=True, check=True, cwd=REPO / "frontend")
    found = json.loads(done.stdout)
    assert [bool(words) for words in found] == [True, True, True, True, True, False, True]
    source = HARNESS.read_text()
    b4 = source[source.index("async function flowB4"):source.index("async function flowB5")]
    b5 = source[source.index("async function flowB5"):source.index("async function flowB8")]
    table = source[source.index("function batchTableEquals"):source.index("async function batchWording")]
    assert "batchTableEquals(" in b4 and "deepEqual(table.headers.map(clean), BATCH_HEADERS" in table
    assert b4.count("batchWording(") >= 2 and b5.count("gaWording(") >= 2          # preflight and results
    assert "stored.limitations.batch_statements" in source and "SCORE_ROW_LABEL" in source


def test_live_round_need_is_the_runner_step_and_no_live_raise():
    from scripts import m28_offscreen_acceptance as m28
    plan = b.build_plan(REPO, "live", send_allowed=True, dispatch_limit=1)
    assert plan["live"]["roundNeed"] == m28.LIVE_STEP["ligand"] == {"expensive_units": 1, "wall_clock_s": 300}
    assert plan["units"]["raises"] == {}
    source = HARNESS.read_text()
    assert "a live phase never raises a limit" in source and "roundNeed" in source


def test_evidence_of_another_plan_or_mode_fails_every_case(tmp_path):
    def flow(step, harness, mode, extra, limit=None):
        folder = tmp_path / "artifacts" / step
        folder.mkdir(parents=True)
        (folder / b.EVIDENCE_FILE).write_text(json.dumps({**_evidence(), "planSha256": "0" * 64, "mode": mode,
                                                          "run": "run_ab"}))
        return {"artifacts": str(folder), "offscreenComplete": True, "externalRequestCount": 0, "fixtureProof": True}
    result = b.run(_ctx(tmp_path, flow=flow))
    assert {(record["status"], record["reason"]) for record in result.cases} == {("fail", "evidence_not_of_this_step")}
    assert result.notes["evidenceCheck"]["planSha256"] is False and result.notes["evidenceCheck"]["mode"] is True


def test_a_round_result_needs_exactly_one_dispatch():
    """Recommendation 1: completed and provider_failed stand only with exactly one dispatch event during the flow;
    none (the harness says it sent, the events do not) or two and more is product_failed (never a waivable
    provider failure)."""
    ok = {f"L-pre-B{n}": {"status": "pass"} for n in (2, 3, 4)}
    done = {"dispatched": True, "status": "completed"}
    failed = {"dispatched": True, "status": "failed", "reasonCode": b.PROVIDER_FAILURES[0]}
    for dispatched in (0, 2, 3):
        assert b.live_result(_live(done, {"state": "scored"}), ok, True, dispatched=dispatched) == ("product_failed",
                                                                                                         None)
        assert b.live_result(_live(failed), ok, True, dispatched=dispatched) == ("product_failed", None)
    assert b.live_result(_live(done, {"state": "scored"}), ok, True, dispatched=1) == ("completed", None)
    assert b.live_result(_live(failed), ok, True, dispatched=1) == ("provider_failed", None)
