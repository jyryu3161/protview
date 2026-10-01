"""M17 ``ligand_candidate_set@1``: server-side validation, tamper rejection, events-only recovery, oracle agreement.

The object comes from real ``rdkit_inspect_v1`` -> ``rdkit_enumerate_v1`` jobs (pinned RDKit worker; fails, never
skips, when absent) on the labeled synthetic fixtures. Expected SMILES are the T1 hand oracle canonicalised in
the pinned interpreter on the test side only. Every mutation is a labeled fault applied to a copy of genuine content.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import subprocess

import pytest
from ligand_job_fixture import EXPECTED, VALID_RULE_IDS, new_ligand_run, run_job, standard_run

from mw import ligand_bundle
from mw import ligand_constants as C
from mw.jobs.queue import JobQueue
from mw.ligand_bundle import LigandEvidenceError, check_candidate_set, validated_candidate_set
from mw.runtime.orchestrator import Run

ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1"}


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    return standard_run(tmp_path_factory.mktemp("enumeration"), "run_ligand_enumeration")


def _job(made) -> dict:
    return JobQueue(made["run"]).get(made["enumerate_job"]["job_id"])


def _inspection(made) -> dict:
    return made["run"].store.load(made["inspection"])


def _canon(smiles: list[str]) -> list[str]:
    code = ("import json,sys\nfrom rdkit import Chem\n"
            "print(json.dumps([Chem.MolToSmiles(Chem.MolFromSmiles(s)) for s in json.load(sys.stdin)]))")
    out = subprocess.run([str(ligand_bundle.WORKER_PYTHON), "-I", "-c", code], input=json.dumps(smiles),
                         capture_output=True, text=True, timeout=120, check=False, env=ENV)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_genuine_candidate_set_validates_and_matches_the_hand_oracle(made):
    run = made["run"]
    content, inspection = validated_candidate_set(run, made["candidate_set"])
    assert content == run.store.load(made["candidate_set"]) and inspection == _inspection(made)
    assert set(content) == ligand_bundle.SET_KEYS
    gen = EXPECTED["generation_with_site_methoxy"]
    union = gen["union_unique_candidates_fixed_plus_valid_rules_both_libraries"]
    hand = [EXPECTED["properties"][name]["hand_smiles"] for name in union]
    assert sorted(row["smiles"] for row in content["candidates"]) == sorted(_canon(hand))
    assert content["retained_parent_atoms"] == EXPECTED["parents"]["no_h"]["core_retained_parent_atoms"]
    assert content["counts"]["raw_products"] == (content["counts"]["candidates"] + content["counts"]["duplicate_products"]
                                                 + sum(content["counts"]["rejected"].values()))
    assert {r: n for r, n in content["counts"]["rejected"].items() if n} == {"equals_parent": 2, "outside_site": 2}
    assert [rule["rule_id"] for rule in content["rules_used"]] == ["fixed", *VALID_RULE_IDS]
    assert content["inspection_handle"] == made["inspection"] and content["parent_sha256"] == inspection["parent"]["sha256"]
    meta = run.store.meta(made["candidate_set"])
    assert meta["null_result"] is False and meta["summary"]["candidates"] == 10


def _set(path: list, value):
    def mutate(content: dict) -> None:
        target = content
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return mutate


def _dup_row(content: dict) -> None:
    content["candidates"].append(copy.deepcopy(content["candidates"][0]))
    content["counts"]["candidates"] += 1
    content["counts"]["raw_products"] += 1


MUTATIONS = {
    "unknown_field": lambda c: c.update(extra=None),
    "schema": _set(["schema"], "ligand_candidate_set@0"),
    "pin": _set(["method", "lock_sha256"], "1" * 64),
    "inspection_handle": lambda c: c.update(inspection_handle=c["parent_handle"]),
    "parent_sha": _set(["parent_sha256"], "0" * 64),
    "parent_smiles": _set(["parent_canonical_smiles"], "CCO"),
    "parent_properties": _set(["parent_properties", "tpsa"], 1.0),
    "site": _set(["site_atoms"], [12]),
    "retained": _set(["retained_parent_atoms"], list(range(1, 10))),
    "crossing": _set(["crossing_bond", "core_atom"], 7),
    "use_fixed": _set(["use_fixed"], False),
    "rule_text": _set(["rules_used", 1, "text"], "[O:1]>>[O:1]"),
    "methods": lambda c: c["methods"].reverse(),
    "block_libraries": _set(["block_libraries", 0, "accepted"], 0),
    "limits": _set(["limits", "max_candidates"], 3),
    "limitations": lambda c: c["limitations"].pop(),
    "count_invariant": _set(["counts", "raw_products"], 18),
    "candidates_count": _set(["counts", "candidates"], 9),
    "duplicates": _set(["counts", "duplicate_products"], 0),
    "rejected_reason": lambda c: c["counts"]["rejected"].update(too_toxic=0),
    "rejected_negative": _set(["counts", "rejected", "equals_parent"], -1),
    "not_applicable": _set(["counts", "not_applicable", "fixed"], 4),
    "not_applicable_key": lambda c: c["counts"]["not_applicable"].pop("user_10"),
    "blocks_accepted": _set(["counts", "blocks_accepted"], 16),
    "limit_flag": _set(["limit_reached"], True),
    "stop_reason": _set(["stop_reason"], "time_limit"),
    "stop_without_flag": _set(["stop_reason"], "candidate_limit"),
    "duplicate_row": _dup_row,
    "row_id": _set(["candidates", 0, "id"], "c_" + "0" * 16),
    "row_id_format": _set(["candidates", 0, "id"], "x_1"),
    "row_smiles": _set(["candidates", 0, "smiles"], "CCN"),
    "row_equals_parent": lambda c: c["candidates"][0].update(
        smiles=c["parent_canonical_smiles"], id="c_" + hashlib.sha256(c["parent_canonical_smiles"].encode()).hexdigest()[:16]),
    "row_unknown_field": lambda c: c["candidates"][0].update(score=1.0),
    "row_origins_empty": _set(["candidates", 0, "origins"], []),
    "row_origin_rule": _set(["candidates", 0, "origins", 0, "rule_id"], "user_4"),
    "row_origin_repeat": lambda c: c["candidates"][0]["origins"].append(dict(c["candidates"][0]["origins"][0])),
    "row_retained": _set(["candidates", 0, "retained_parent_atoms"], [1, 2]),
    "row_stereo": _set(["candidates", 0, "stereo_flag"], "unknown"),
    "row_property_nan": _set(["candidates", 0, "properties", "crippen_logp"], math.nan),
    "row_property_type": _set(["candidates", 0, "properties", "rotatable_bonds"], 2.5),
    "row_property_missing": lambda c: c["candidates"][0]["properties"].pop("mol_weight"),
    "row_heavy_atoms": _set(["candidates", 0, "properties", "heavy_atoms"], 257),
    "row_pains_catalog": _set(["candidates", 0, "pains", "matches"], [{"catalog": "PAINS_D", "name": "x"}]),
    "row_pains_repeat": _set(["candidates", 0, "pains", "matches"], [{"catalog": "PAINS_A", "name": "x"}] * 2),
    "row_pains_keys": _set(["candidates", 0, "pains"], {"matches": [], "verdict": "bad"}),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_each_tampered_candidate_set_is_rejected(made, name):
    content = copy.deepcopy(made["run"].store.load(made["candidate_set"]))
    check_candidate_set(content, _job(made), _inspection(made))  # the genuine copy passes
    MUTATIONS[name](content)
    with pytest.raises(LigandEvidenceError):
        check_candidate_set(content, _job(made), _inspection(made))


def test_candidate_set_is_rejected_when_its_inspection_or_job_differs(made):
    content = made["run"].store.load(made["candidate_set"])
    inspection = copy.deepcopy(_inspection(made))
    inspection["parent"]["sha256"] = "0" * 64
    with pytest.raises(LigandEvidenceError):
        check_candidate_set(content, _job(made), inspection)
    job = copy.deepcopy(_job(made))
    job["selected"]["site_atoms"] = [5]
    with pytest.raises(LigandEvidenceError):
        check_candidate_set(content, job, _inspection(made))
    job = copy.deepcopy(_job(made))
    job["selected"]["rules"][0]["text"] = "[O:1][CH3]>>[O:1]"
    with pytest.raises(LigandEvidenceError):
        check_candidate_set(content, job, _inspection(made))


def test_reads_reject_forged_and_corrupt_candidate_sets(made, tmp_path):
    run = made["run"]
    genuine = run.store.load(made["candidate_set"])
    forged = run.store.put("ligand_candidate_set", "ligand_candidate_set@1",
                           {**genuine, "candidates": genuine["candidates"][:-1],
                            "counts": {**genuine["counts"], "candidates": 9,
                                       "duplicate_products": genuine["counts"]["duplicate_products"] + 1}})
    with pytest.raises(LigandEvidenceError):
        validated_candidate_set(run, forged.handle)  # no completed rdkit_enumerate_v1 publication
    for wrong in (made["inspection"], made["parent"], None, f"obj://{run.run_id}/ligand_candidate_set/{'1' * 64}"):
        with pytest.raises(LigandEvidenceError):
            validated_candidate_set(run, wrong)


def test_events_only_recovery_restores_identical_bytes(made, tmp_path, monkeypatch):
    run = made["run"]
    before = (run.run_dir / "events.jsonl").read_bytes()
    originals = {key: (run.run_dir / run.store.meta(made[key])["path"]).read_bytes()
                 for key in ("inspection", "candidate_set")}
    replay = tmp_path / "events_only"
    (replay / run.run_id).mkdir(parents=True)
    (replay / run.run_id / "events.jsonl").write_bytes(before)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("events-only reads must not execute scientific work")

    monkeypatch.setattr(ligand_bundle, "WORKER_PYTHON", tmp_path / "rdkit_removed/python")
    monkeypatch.setattr(ligand_bundle, "_handshake", forbidden)
    monkeypatch.setattr(ligand_bundle, "stage", forbidden)
    monkeypatch.setattr(JobQueue, "_supervise", forbidden)
    monkeypatch.setattr(Run, "call", forbidden)
    recovered = new_ligand_run(replay, run.run_id)
    content, inspection = validated_candidate_set(recovered, made["candidate_set"])
    assert content == run.store.load(made["candidate_set"]) and inspection == _inspection(made)
    for key, raw in originals.items():
        assert (replay / run.run_id / recovered.store.meta(made[key])["path"]).read_bytes() == raw
    assert (replay / run.run_id / "events.jsonl").read_bytes() == before
    # A tampered recovered object never reads.
    path = replay / run.run_id / recovered.store.meta(made["candidate_set"])["path"]
    path.write_text(json.dumps({**content, "candidates": []}))
    with pytest.raises(LigandEvidenceError):
        validated_candidate_set(recovered, made["candidate_set"])


def test_rules_only_and_empty_scientific_result(tmp_path):
    made = standard_run(tmp_path, "run_ligand_rules_only")
    run = made["run"]
    empty = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": made["inspection"], "site_atoms": [11, 12],
                                                "use_fixed": False, "rule_ids": ["user_3"]})
    assert empty["status"] == "done", empty
    content, _ = validated_candidate_set(run, empty["output_handles"][0])
    assert content["candidates"] == [] and content["counts"]["candidates"] == 0
    assert content["counts"]["rejected"]["outside_site"] == 2 and content["rules_used"][0]["rule_id"] == "user_3"
    assert content["counts"]["not_applicable"] == {"user_3": 13}
    assert run.store.meta(empty["output_handles"][0])["null_result"] is True
    assert C.LIMITATIONS == tuple(content["limitations"])
