"""M17 ``ligand_inspection@1``: server-side validation, tamper rejection, events-only recovery, stable handles.

The object comes from a real ``rdkit_inspect_v1`` job (pinned RDKit worker; fails, never skips, when absent) on the
labeled synthetic fixtures. Every mutation below is a labeled fault applied to a copy of the genuine content.
"""
from __future__ import annotations

import copy
import json
import math
import shutil

import pytest
from ligand_job_fixture import EXPECTED, RULES, events, new_ligand_run, standard_run

from mw import ligand_bundle
from mw.jobs.queue import JobQueue
from mw.ligand_bundle import LigandEvidenceError, check_inspection, validated_inspection
from mw.runtime.orchestrator import Run


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    return standard_run(tmp_path_factory.mktemp("inspection"), "run_ligand_inspection")


def _job(made) -> dict:
    return JobQueue(made["run"]).get(made["inspect_job"]["job_id"])


def test_genuine_inspection_validates_and_matches_the_oracle(made):
    run, handle = made["run"], made["inspection"]
    content = validated_inspection(run, handle)
    assert content == run.store.load(handle) and set(content) == ligand_bundle.INSPECTION_KEYS
    assert content["parent_handle"] == made["parent"] and content["block_handles"] == [made["smiles"], made["sdf"]]
    hand = EXPECTED["parents"]["no_h"]
    assert [{"serial": a["serial"], "element": a["element"]} for a in content["parent"]["atoms"]] == hand["heavy_atoms"]
    assert [(r["rule_id"], r["status"]) for r in content["rules"]] == [
        (r["rule_id"], r["status"]) for r in EXPECTED["rules"]["results"]]
    assert [lib["accepted"] for lib in content["block_libraries"]] == [
        EXPECTED["block_libraries"][key]["summary"]["accepted"] for key in ("smiles", "sdf")]
    meta = run.store.meta(handle)
    assert (meta["kind"], meta["schema"]) == ("ligand_inspection", "ligand_inspection@1")
    assert meta["produced_by"] == made["inspect_job"]["attempt_id"]
    assert len(json.dumps(content).encode()) <= ligand_bundle.MAX_INSPECTION_BYTES


def _set(path: list, value):
    def mutate(content: dict) -> None:
        target = content
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return mutate


MUTATIONS = {
    "unknown_field": lambda c: c.update(extra=1),
    "schema": _set(["schema"], "ligand_inspection@2"),
    "protocol": _set(["protocol"], "rdkit_enumerate_v1"),
    "pin": _set(["method", "rdkit_version"], "2026.03.5"),
    "worker_sha": _set(["method", "worker_sha256"], "0" * 64),
    "parent_handle": lambda c: c.update(parent_handle=c["block_handles"][0]),
    "block_order": lambda c: c.update(block_handles=c["block_handles"][::-1]),
    "parent_sha": _set(["parent", "sha256"], "0" * 64),
    "input_rule_sha": lambda c: c["input_sha256"]["rules"].reverse(),
    "element": _set(["parent", "atoms", 0, "element"], "Se"),
    "hydrogen_element": _set(["parent", "atoms", 0, "element"], "H"),
    "serial_gap": _set(["parent", "atoms_in_sdf"], 13),
    "bond_order": _set(["parent", "bonds", 0, "order"], "quadruple"),
    "neighbors": _set(["parent", "atoms", 0, "neighbors"], []),
    "heavy_count": _set(["parent", "heavy_atom_count"], 11),
    "svg_script": lambda c: c["parent"].update(svg=c["parent"]["svg"] + "<script>alert(1)</script>",
                                               svg_bytes=len((c["parent"]["svg"] + "<script>alert(1)</script>").encode())),
    "svg_bytes": _set(["parent", "svg_bytes"], 1),
    "svg_too_large": lambda c: c["parent"].update(svg=c["parent"]["svg"] + " " * 300_000,
                                                  svg_bytes=len(c["parent"]["svg"].encode()) + 300_000),
    "property_nan": _set(["parent", "properties", "mol_weight"], math.nan),
    "property_inf": _set(["parent", "properties", "tpsa"], math.inf),
    "property_bool": _set(["parent", "properties", "hbd"], True),
    "property_float_count": _set(["parent", "properties", "hba"], 3.0),
    "property_missing": lambda c: c["parent"]["properties"].pop("crippen_logp"),
    "property_heavy": _set(["parent", "properties", "heavy_atoms"], 13),
    "property_methods": lambda c: c["property_methods"].pop("tpsa"),
    "rule_status": _set(["rules", 0, "status"], "too_large"),
    "rule_unknown_status": _set(["rules", 3, "status"], "almost_valid"),
    "rule_text": _set(["rules", 0, "text"], "[C:1]>>[C:1]"),
    "rule_too_large_text": _set(["rules", 8, "text"], RULES[8]),
    "rule_id": _set(["rules", 0, "rule_id"], "user_0"),
    "duplicate_status": _set(["rules", 7, "status"], "valid"),
    "rule_dropped": lambda c: c["rules"].pop(),
    "library_counts": _set(["block_libraries", 0, "accepted"], 13),
    "library_reason": _set(["block_libraries", 0, "rejected", 0, "reason"], "too_heavy"),
    "library_rejected_counts": lambda c: c["block_libraries"][0]["rejected_counts"].update(unparseable=0),
    "library_limit_flag": _set(["block_libraries", 1, "block_limit_reached"], True),
    "library_kind": _set(["block_libraries", 0, "kind"], "building_blocks_sdf"),
    "library_sha": _set(["block_libraries", 1, "sha256"], "0" * 64),
    "library_targets": _set(["block_libraries", 0, "fixed_targets"], 12),
    "library_ordinal": _set(["block_libraries", 0, "rejected", 0, "ordinal"], 0),
    "library_name_long": _set(["block_libraries", 0, "rejected", 0, "name"], "n" * 129),
    "library_dropped": lambda c: c["block_libraries"].pop(),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_each_tampered_inspection_is_rejected(made, name):
    content = copy.deepcopy(made["run"].store.load(made["inspection"]))
    check_inspection(made["run"], content, _job(made))  # the genuine copy passes
    MUTATIONS[name](content)
    with pytest.raises(LigandEvidenceError):
        check_inspection(made["run"], content, _job(made))


def test_inspection_size_bound_is_enforced(made, monkeypatch):
    content = made["run"].store.load(made["inspection"])
    size = len(json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
    monkeypatch.setattr(ligand_bundle, "MAX_INSPECTION_BYTES", size - 1)  # labeled: bound lowered for the test
    with pytest.raises(LigandEvidenceError):
        check_inspection(made["run"], content, _job(made))


def test_reads_reject_forged_corrupt_and_wrong_kind_objects(made, tmp_path):
    run = made["run"]
    genuine = run.store.load(made["inspection"])
    forged = run.store.put("ligand_inspection", "ligand_inspection@1", {**genuine, "rules": genuine["rules"][:9]})
    with pytest.raises(LigandEvidenceError):
        validated_inspection(run, forged.handle)  # no completed rdkit_inspect_v1 publication
    for wrong in (made["parent"], made["candidate_set"], 7, f"obj://{run.run_id}/ligand_inspection/{'0' * 64}",
                  made["inspection"].replace(run.run_id, "run_other_ligand")):
        with pytest.raises(LigandEvidenceError):
            validated_inspection(run, wrong)
    copied = tmp_path / "copy"
    shutil.copytree(run.run_dir, copied / run.run_id)
    clone = new_ligand_run(copied, run.run_id)
    assert validated_inspection(clone, made["inspection"]) == genuine
    path = copied / run.run_id / run.store.meta(made["inspection"])["path"]
    path.write_text(json.dumps({**genuine, "rules": []}))  # labeled fault: stored object bytes replaced
    with pytest.raises(LigandEvidenceError):
        validated_inspection(clone, made["inspection"])


def test_events_only_recovery_restores_identical_bytes(made, tmp_path, monkeypatch):
    run = made["run"]
    before = (run.run_dir / "events.jsonl").read_bytes()
    original_bytes = (run.run_dir / run.store.meta(made["inspection"])["path"]).read_bytes()
    replay = tmp_path / "events_only"
    (replay / run.run_id).mkdir(parents=True)
    (replay / run.run_id / "events.jsonl").write_bytes(before)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("events-only reads must not execute scientific work")

    monkeypatch.setattr(ligand_bundle, "WORKER_PYTHON", tmp_path / "rdkit_removed/python")
    monkeypatch.setattr(ligand_bundle, "_handshake", forbidden)
    monkeypatch.setattr(JobQueue, "_supervise", forbidden)
    monkeypatch.setattr(Run, "call", forbidden)
    recovered = new_ligand_run(replay, run.run_id)
    assert not (replay / run.run_id / "uploads").exists()
    assert validated_inspection(recovered, made["inspection"]) == run.store.load(made["inspection"])
    assert (replay / run.run_id / recovered.store.meta(made["inspection"])["path"]).read_bytes() == original_bytes
    assert ligand_bundle.capability()["available"] is False
    assert (replay / run.run_id / "events.jsonl").read_bytes() == before


def test_same_input_gives_the_same_handle_and_job(made, tmp_path):
    run = made["run"]
    args = {"parent_sdf_handle": made["parent"], "block_handles": [made["smiles"], made["sdf"]], "rules": RULES}
    again = JobQueue(run).submit("rdkit_inspect_v1", args, timeout_s=30)
    assert again["job_id"] == made["inspect_job"]["job_id"] and again["output_handles"] == [made["inspection"]]
    assert len([e for e in events(run) if e["type"] == "budget_reserved"]) == 2
    # A fresh run with identical inputs stores the same content up to its own run's input handles: no time,
    # job or attempt identity enters the object.
    other = standard_run(tmp_path, "run_ligand_inspection_again")
    assert other["inspect_job"]["job_id"] != made["inspect_job"]["job_id"]
    for key in ("inspection", "candidate_set"):
        mine = (run.run_dir / run.store.meta(made[key])["path"]).read_text()
        theirs = (other["run"].run_dir / other["run"].store.meta(other[key])["path"]).read_text()
        mine = mine.replace(made["inspection"], "INSPECTION").replace(run.run_id, "RUN")
        theirs = theirs.replace(other["inspection"], "INSPECTION").replace(other["run"].run_id, "RUN")
        assert theirs == mine
