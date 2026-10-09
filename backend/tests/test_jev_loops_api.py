"""M25 T3-A: the JEV loop events, ``POST /runs/{rid}/jev_loops`` and ``/capabilities`` ``methods.jev_loop`` (spec
.dryforge/spec.md 3.1, 3.2 keys, 9.1, 9.2, 11).

Inputs are REAL product objects: chemical imports of the public prepared docking example receptor
(``fixtures/chemical``, not experimental validation), the public-derived parent SDF, the labelled synthetic M22 small
blocks and the labelled synthetic phenol SDF; a real M17 candidate set from real RDKit jobs (``ligand_job_fixture``,
a missing environment FAILS, never skips); real M20 sets from the cheap tool on public 1UBQ (I44, K48) and public 1MQ4
(K143, which the M7 preflight refuses, M25 T1 (f)). The template runs are built once per module and each test gets an
events-only copy. ``api_module.SCIENCE_GATE`` is a ``jev_send_fixture.Fake`` gate (MockTransport, inert sentinel
credential) only to show no request and no key read happen. Expected values are written from the spec: the closed
reasons and their order, the HTTP status of each, the normalized setup (M18 / M21 defaults), the stored candidate
notation; the per-candidate call keys are checked against the real ``JobQueue.submit`` of the same request, never
against this module. Held run locks, broken engine paths and the one labelled synthetic ``jev_loop_ended`` event are
fault injection, marked where used.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import typing
import uuid
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import m20_v2_fixture as V2
import pytest
from fastapi.testclient import TestClient
from jev_send_fixture import Fake
from ligand_job_fixture import import_file, new_ligand_run, run_job

from mw import docking_batch_inputs, docking_bundle, jev_loop_store, jev_loops, mutation_model_bundle
from mw import docking_constants as DC
from mw import jev_constants as J
from mw import jev_loop_constants as L
from mw import jev_sends as S
from mw import mutation_model_constants as MC
from mw.api import app as api_module
from mw.core import events as core_events
from mw.core.errors import ToolFailure
from mw.core.handles import canonical_json
from mw.egress import science as egress_science
from mw.jobs.queue import JobQueue
from mw.workspace import new_run

TESTS = Path(__file__).resolve().parent
MW = TESTS.parent / "mw"
FIX = TESTS / "fixtures"
REC = (FIX / "chemical/prolif-vina-rec.pdb").read_bytes()
PARENT = (FIX / "docking/public-derived-parent-record0.sdf").read_bytes()
BLOCKS = (FIX / "ligand_ga/synthetic-ga-small-blocks.smi").read_bytes()
PHENOL = (FIX / "mutation_model/synthetic-phenol-ligand.sdf").read_bytes()
UBQ = FIX / "public_1ubq.cif"
MQ4 = FIX / "public_1mq4.cif"
ACK = {key: True for key in DC.ACKNOWLEDGEMENT_KEYS}
I44 = {"model_number": 1, "chain_auth": "A", "seq_auth": 44, "icode": "", "resname": "ILE"}
K48 = {"model_number": 1, "chain_auth": "A", "seq_auth": 48, "icode": "", "resname": "LYS"}
K143 = {"model_number": 1, "chain_auth": "A", "seq_auth": 143, "icode": "", "resname": "LYS"}
RID, DRY_RID = "run_m25_loops", "run_m25_loops_dry"
JSON = {"content-type": "application/json"}
LIGAND_REASONS = set(DC.REASONS) | set(DC.ADMISSION_ONLY_REASONS)
PROTEIN_REASONS = LIGAND_REASONS | set(MC.ADMISSION_REASON_CODES)
CREATE_STATUS = {"unknown_field": 422, "loop_id_invalid": 422, "dry_run": 412, "branch_invalid": 422,
                 "capability_unavailable": 412, "loop_active": 409, "pool_invalid": 422, "goal_invalid": 422,
                 "seed_invalid": 422, "iteration_cap_invalid": 422, "setup_invalid": 422,
                 "loop_id_conflict": 409}   # spec 3.1
BUDGET_EVENTS = {"budget_reserved", "wall_charged", "egress_budget_settled", "budget_limit_updated"}


# ---------------------------------------------------------------- template runs (built once) and per-test copies


def _template(root: Path) -> dict:
    run = new_ligand_run(root, RID)
    world = {"root": root, "run_id": RID}
    world["receptor"] = import_file(run, "receptor", "rec.pdb", REC)
    world["parent"] = import_file(run, "ligand_sdf", "parent.sdf", PARENT)
    world["phenol"] = import_file(run, "ligand_sdf", "phenol.sdf", PHENOL)
    world["ubq_receptor"] = import_file(run, "receptor", "ubq.cif", UBQ.read_bytes())
    blocks = import_file(run, "building_blocks_smiles", "blocks.smi", BLOCKS)
    inspected = run_job(run, "rdkit_inspect_v1", {"parent_sdf_handle": world["parent"], "block_handles": [blocks]})
    assert inspected["status"] == "done", inspected
    enumerated = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": inspected["output_handles"][0],
                                                     "site_atoms": [22], "use_fixed": True})
    assert enumerated["status"] == "done", enumerated
    world["ligand_set"] = enumerated["output_handles"][0]
    world["ids"] = [row["id"] for row in run.store.load(world["ligand_set"])["candidates"]]
    assert len(world["ids"]) >= 4
    for name, path, residues in (("ubq", UBQ, [I44, K48]), ("mq4", MQ4, [K143])):
        loaded = run.call("load_structure", {"source": str(path), "model_index": 0}).handle
        prepared = run.call("prepare_structure", {"structure": loaded}).handle
        world[f"{name}_set"] = run.call("generate_mutation_candidates", {
            "structure": prepared, "sources": {"pocket": None, "ligand_shell": None, "residues": residues}}).handle
        world[f"{name}_structure"] = prepared
    content = run.store.load(world["ubq_set"])
    world["indexes"] = [row["index"] for row in content["candidates"]]
    assert len(world["indexes"]) >= 21   # 19 alternatives at I44 + 19 at K48
    world["mq4_indexes"] = [row["index"] for row in run.store.load(world["mq4_set"])["candidates"]]
    new_run(root, run_id=DRY_RID, dry_run=True)
    return world


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return _template(tmp_path_factory.mktemp("jev_loop_templates"))


@pytest.fixture(autouse=True)
def no_active_sends():
    S.ACTIVE_SENDS.clear()
    yield
    S.ACTIVE_SENDS.clear()


def _open(base, tmp_path, monkeypatch, *, dry=False):
    """An events-only copy of the template run served by the API (Fake science gate: no socket, no key file)."""
    root = tmp_path / "runs"
    for rid in (RID, DRY_RID):
        (root / rid).mkdir(parents=True)
        shutil.copyfile(base["root"] / rid / "events.jsonl", root / rid / "events.jsonl")
    fake = Fake()
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    monkeypatch.setattr(api_module, "SCIENCE_GATE", fake.gate)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    world = {**base, "root": root, "rid": DRY_RID if dry else RID, "fake": fake, "client": client}
    world["run"] = api_module._run(world["rid"])   # the reopen (job reconcile) happens before any baseline
    return world


def _log(world) -> bytes:
    return (world["root"] / world["rid"] / "events.jsonl").read_bytes()


def _events(world) -> list[dict]:
    return [json.loads(line) for line in _log(world).splitlines()]


def _loop_id() -> str:
    return str(uuid.uuid4())


def ligand_body(world, **over) -> dict:
    ids = world["ids"]
    body = {"loop_id": _loop_id(), "branch": "ligand",
            "pool": {"source": world["ligand_set"], "candidates": [ids[2], ids[0], ids[1]], "filter": None},
            "goal": "explore", "loop_seed": 7, "iteration_cap": 5,
            "setup": {"receptor_handle": world["receptor"], "receptor_model_number": 1,
                      "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
                      "box": {"source": "ligand_range", "margin_A": 8}, "parameters": {"seed": 7},
                      "acknowledgement": dict(ACK), "parent_sdf_handle": world["parent"]}}
    body.update(over)
    return body


def protein_body(world, **over) -> dict:
    indexes = world["indexes"]
    body = {"loop_id": _loop_id(), "branch": "protein",
            "pool": {"source": world["ubq_set"], "candidates": [indexes[17], indexes[3], indexes[0]], "filter": None},
            "goal": "exploit", "loop_seed": 11, "iteration_cap": 8,
            "setup": {"ligand": {"source": "sdf", "sdf_handle": world["phenol"]},
                      "box": {"source": "ligand_range", "margin_A": 8}, "parameters": {"seed": 20261007},
                      "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7",
                      "acknowledgement": dict(ACK)}}   # contact_cutoff_A omitted: the M21 default 4.0
    body.update(over)
    return body


def _with(body, path, value):
    """A deep copy of ``body`` with ``path`` (keys) set to ``value``; ``...`` deletes it."""
    out = copy.deepcopy(body)
    target = out
    for key in path[:-1]:
        target = target[key]
    if value is ...:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return out


def _post(world, body, *, raw=None, headers=JSON, rid=None):
    content = raw if raw is not None else json.dumps(body).encode()
    return world["client"].post(f"/runs/{rid or world['rid']}/jev_loops", content=content, headers=headers)


def _refused(response, reason, **detail):
    assert response.status_code == CREATE_STATUS[reason], response.text
    got = response.json()["detail"]
    assert got["reason_code"] == reason, got
    for key, value in detail.items():
        assert got[key] == value, got
    return got


def _created(world, body) -> dict:
    response = _post(world, body)
    assert response.status_code == 200, response.text
    return response.json()


def _no_side_effects(world, before: bytes) -> None:
    assert _log(world) == before
    assert world["fake"].requests == [] and world["fake"].key_reads == 0


# ---------------------------------------------------------------- the four event types


def test_the_four_loop_event_types_are_registered_with_the_constant_names():
    names = set(typing.get_args(core_events.EventType))
    assert {L.EVENT_CREATED, L.EVENT_COMPUTE_APPROVED, L.EVENT_DOCKING_ABANDONED, L.EVENT_ENDED} <= names
    assert L.EVENT_TYPES == ("jev_loop_created", "jev_loop_compute_approved", "jev_loop_docking_abandoned",
                             "jev_loop_ended")
    text = (MW / "core/events.py").read_text()
    for name in L.EVENT_TYPES:
        assert text.count(f'"{name}"') == 1, name


# ---------------------------------------------------------------- creating a loop


def test_a_ligand_loop_is_one_created_event_and_answers_its_record(base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    budget_before = world["run"].budget_snapshot()
    before = _events(world)
    body = ligand_body(world)
    record = _created(world, body)
    after = _events(world)
    added = after[len(before):]
    assert after[:len(before)] == before and [event["type"] for event in added] == [L.EVENT_CREATED]
    assert world["fake"].requests == [] and world["fake"].key_reads == 0
    assert not {event["type"] for event in added} & (BUDGET_EVENTS | {"job_submitted", "tool_called", "egress"})
    assert world["run"].budget_snapshot() == budget_before
    payload = jev_loops.parse_created(added[0])     # the reader's own closed check
    ids = world["ids"]
    setup = {"receptor_handle": world["receptor"], "receptor_model_number": 1,
             "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
             "box": {"source": "ligand_range", "margin_A": 8.0},
             "parameters": {"seed": 7, "exhaustiveness": 8, "num_modes": 9, "energy_range": 3.0, "conformers": None},
             "acknowledgement": ACK, "parent_sdf_handle": world["parent"]}   # M18 / M22 normalization by hand
    assert payload == {
        "loop_id": body["loop_id"], "branch": "ligand",
        "pool": {"source": {"handle": world["ligand_set"], "schema": "ligand_candidate_set@1"}, "structure": None,
                 "candidates": [ids[0], ids[1], ids[2]], "filter": None},   # the candidate set's stored order
        "goal": "explore", "loop_seed": 7, "iteration_cap": 5, "setup": setup,
        "setup_sha256": hashlib.sha256(canonical_json(setup)).hexdigest(),
        "pins": {"m18": docking_bundle.require_ready()}}
    rows = {row["id"]: row for row in world["run"].store.load(world["ligand_set"])["candidates"]}
    assert set(record) == set(jev_loops.RECORD_KEYS) and record["schema"] == "jev_loop@1"
    assert (record["loop_id"], record["branch"], record["status"], record["end_reason"]) == (
        body["loop_id"], "ligand", "active", None)
    assert (record["goal"], record["loop_seed"], record["iteration_cap"], record["effective_cap"]) == (
        "explore", 7, 5, 3)   # min(iteration_cap, pool size)
    assert record["setup"] == setup and record["setup_sha256"] == payload["setup_sha256"]
    assert record["pins"] == payload["pins"] and record["exhausted_reason"] is None
    assert record["pool"] == {"source": payload["pool"]["source"], "structure": None, "filter": None,
                              "candidates": [{"ref": ref, "display": {"smiles": rows[ref]["smiles"]}}
                                             for ref in (ids[0], ids[1], ids[2])]}
    assert record["candidates"] == [{"ref": ref, "display": {"smiles": rows[ref]["smiles"]}, "state": "pending",
                                     "evaluation": None, "score_kcal_mol": None, "iteration": None}
                                    for ref in (ids[0], ids[1], ids[2])]
    assert record["counts"] == dict.fromkeys(jev_loops.COUNT_KEYS, 0) and record["iterations"] == []
    current = record["current"]
    assert (current["iteration"], current["phase"], current["step"], current["action"]) == (
        1, "awaiting_selection", "ligand_dock", "select")
    assert current["needs"]["expensive_units"] == 1 and current["needs"]["wall_clock_s"] == 300
    assert record["result_handle"] is None
    assert record["limitations"] == [L.LJ1, L.LJ2, L.LJ3, L.LJ5, L.LJ6]


def test_a_protein_loop_records_the_structure_both_pins_and_the_m21_default_cutoff(base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    before = _log(world)
    body = protein_body(world)
    record = _created(world, body)
    added = _events(world)[len(before.splitlines()):]
    assert [event["type"] for event in added] == [L.EVENT_CREATED]
    payload = jev_loops.parse_created(added[0])
    content = world["run"].store.load(world["ubq_set"])
    setup = {"ligand": {"source": "sdf", "sdf_handle": world["phenol"]},
             "box": {"source": "ligand_range", "margin_A": 8.0},
             "parameters": {"seed": 20261007, "exhaustiveness": 8, "num_modes": 9, "energy_range": 3.0,
                            "conformers": None},
             "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7", "acknowledgement": ACK,
             "contact_cutoff_A": 4.0}
    indexes = world["indexes"]
    assert payload["pool"] == {"source": {"handle": world["ubq_set"], "schema": "mutation_candidate_set@1"},
                               "structure": {"handle": content["structure"]["handle"],
                                             "model_number": content["structure"]["model_number"]},
                               "candidates": [indexes[0], indexes[3], indexes[17]], "filter": None}
    assert payload["setup"] == setup and payload["setup_sha256"] == hashlib.sha256(canonical_json(setup)).hexdigest()
    assert payload["pins"] == {"m18": docking_bundle.require_ready(), "m21": mutation_model_bundle.require_ready()}
    positions = {item["index"]: item for item in content["positions"]}
    by_index = {row["index"]: row for row in content["candidates"]}
    expected = []
    for ref in (indexes[0], indexes[3], indexes[17]):
        row = by_index[ref]
        residue = positions[row["position_index"]]["residue"]
        expected.append({"ref": ref, "display": {"residue": {key: residue[key] for key in J.ALLOWED_RESIDUE},
                                                 "from": row["from"], "to": row["to"]}})
    assert record["pool"]["candidates"] == expected
    assert by_index[indexes[17]]["to"] == "W" and expected[2]["display"]["residue"]["seq_auth"] == 44
    assert (record["branch"], record["goal"], record["effective_cap"], record["current"]["step"]) == (
        "protein", "exploit", 3, "model")
    assert record["current"]["needs"]["expensive_units"] == 2 and record["current"]["needs"]["wall_clock_s"] == 420
    assert record["limitations"] == [L.LJ1, L.LJ2, L.LJ3, L.LJ4, L.LJ7]


def test_a_protein_loop_pool_takes_a_v2_set_with_a_checked_catalytic_annotation(base, tmp_path, monkeypatch):
    """M26 spec 9: a v2 set built by the M20 tool with a catalytic annotation (``link_reaction_knowledge`` over the
    LABELLED SYNTHETIC 0SY8 reaction set of ``m20_v2_fixture``) is a protein pool like any M20 set (the template's
    tool-built sets are v2 ``not_checked``); the loop sentences stay LJ1-LJ8 (no J6 variant)."""
    world = _open(base, tmp_path, monkeypatch)
    run = world["run"]
    assert run.store.load(world["ubq_set"])["protection_checks"]["catalytic_residue_database"]["status"] == \
        "not_checked"
    V2.activate_ubq(tmp_path / "reaction_reference", monkeypatch)
    try:
        knowledge = V2.link_ubq(run, world["ubq_structure"])
        checked = run.call("generate_mutation_candidates", {"structure": world["ubq_structure"], **V2.TINY_ARGS,
                                                            "catalytic_annotation": knowledge}).handle
    finally:
        V2.CF.reset_caches()
    content = run.store.load(checked)
    assert content["protection_checks"]["catalytic_residue_database"]["status"] == "checked"
    refs = [row["index"] for row in content["candidates"]][:3]
    before = _log(world)
    record = _created(world, protein_body(world, pool={"source": checked, "candidates": refs, "filter": None}))
    added = _events(world)[len(before.splitlines()):]
    assert [event["type"] for event in added] == [L.EVENT_CREATED]
    payload = jev_loops.parse_created(added[0])
    assert payload["pool"]["source"] == {"handle": checked, "schema": "mutation_candidate_set@1"}
    assert payload["pool"]["candidates"] == refs
    assert [item["ref"] for item in record["pool"]["candidates"]] == refs
    assert record["limitations"] == [L.LJ1, L.LJ2, L.LJ3, L.LJ4, L.LJ7]


def test_the_loop_requests_have_the_call_keys_the_job_queue_gives_the_same_request(base, tmp_path, monkeypatch):
    """Independent check of the request builders T6 submits with: the real ``JobQueue.submit`` (no start, no charge)
    computes its own call key for the request the loop module builds; the record's pins are the job's pins."""
    world = _open(base, tmp_path, monkeypatch)
    ligand_record = _created(world, ligand_body(world))
    protein_record = _created(world, protein_body(world))
    run, queue = world["run"], JobQueue(world["run"])
    for record in (ligand_record, protein_record):
        created = next(jev_loops.parse_created(event) for event in run.events.read()
                       if event["type"] == L.EVENT_CREATED and event["loop_id"] == record["loop_id"])
        keys = jev_loop_store.candidate_keys(created)
        source = created["pool"]["source"]["handle"]
        for ref in created["pool"]["candidates"]:
            if record["branch"] == "ligand":
                job = queue.submit(DC.PROTOCOL, jev_loop_store.ligand_request(created["setup"], source, ref),
                                   timeout_s=L.STEP_TIMEOUT_DEFAULTS_S["ligand_dock"])
                assert keys[ref] == {"ligand_dock": job["call_key"]} and job["method"] == created["pins"]["m18"]
            else:
                job = queue.submit(MC.PROTOCOL, jev_loop_store.model_request(created["setup"], source, ref),
                                   timeout_s=L.STEP_TIMEOUT_DEFAULTS_S["model"])
                assert keys[ref] == {"model": job["call_key"], "dock": None}
                assert job["method"] == created["pins"]["m21"]
            assert job["status"] == "queued"
    # The ligand request is the M19 / M22 row request (docking_batch_inputs.row_request with mode free).
    created = jev_loops.parse_created(next(event for event in run.events.read()
                                           if event["type"] == L.EVENT_CREATED
                                           and event["loop_id"] == ligand_record["loop_id"]))
    setup, source, ref = created["setup"], created["pool"]["source"]["handle"], created["pool"]["candidates"][0]
    shared = {key: setup[key] for key in docking_batch_inputs.SHARED_KEYS if key != "mode"}
    assert jev_loop_store.ligand_request(setup, source, ref) == docking_batch_inputs.row_request(
        {**shared, "mode": "free", "candidate_set_handle": source, "parent_sdf_handle": setup["parent_sdf_handle"]},
        "candidate", ref)


def test_the_created_event_alone_reopens_the_same_record_without_any_engine(base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    records = [_created(world, ligand_body(world)), _created(world, protein_body(world))]
    other = tmp_path / "reopened"
    (other / RID).mkdir(parents=True)
    shutil.copyfile(world["root"] / RID / "events.jsonl", other / RID / "events.jsonl")

    def no_engine(*args, **kwargs):   # fault injection: any engine or pin lookup during a read fails the test
        raise AssertionError("a loop read must not need an engine")

    for module, names in ((docking_bundle, ("capability", "require_ready", "submission")),
                          (mutation_model_bundle, ("capability", "require_ready", "admission", "selection"))):
        for name in names:
            monkeypatch.setattr(module, name, no_engine)
    run = new_run(other, run_id=RID, dry_run=False)
    view = jev_loop_store.LoopReadView(run)
    budget = jev_loop_store.remaining_budget(run.budget_snapshot())
    for record in records:
        state = jev_loop_store.read_loop(view, record["loop_id"], budget=budget, send_active=False)
        assert state.record == record


def test_a_new_loop_event_changes_no_replay_budget_job_or_send_state(base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    without = _log(world)
    _created(world, ligand_body(world))
    _created(world, protein_body(world))
    with_loops = _log(world)
    states = []
    for name, raw in (("without", without), ("with", with_loops)):
        (tmp_path / name / RID).mkdir(parents=True)
        (tmp_path / name / RID / "events.jsonl").write_bytes(raw)
        run = new_run(tmp_path / name, run_id=RID, dry_run=False)
        events = list(run.events.read())
        states.append({"budget": run.budget_snapshot(), "egress": (run.egress_stop_reason, run.egress_unknown),
                       "approved": run.approved_expensive, "cancelled": run.cancelled,
                       "jobs": JobQueue(run).list(), "published": docking_batch_inputs.published_m18_results(events),
                       "sends": S.list_sends(events), "consent": S.consent_enabled(events),
                       "dispatched": S.dispatch_count(events)})
        assert (run.run_dir / "events.jsonl").read_bytes() == raw   # reopening wrote nothing
    assert states[0] == states[1]


# ---------------------------------------------------------------- admission order (first failure only)


def test_the_admission_checks_run_in_the_spec_order_and_stop_at_the_first(base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    good = ligand_body(world)
    bad_loop_id = "not-a-uuid"
    cases = [
        ({**good, "extra": 1, "loop_id": bad_loop_id, "branch": "x"}, "unknown_field"),
        ({**good, "loop_id": bad_loop_id, "branch": "x"}, "loop_id_invalid"),
        ({**good, "branch": "x", "pool": None}, "branch_invalid"),
        ({**good, "pool": None, "goal": "x"}, "pool_invalid"),
        ({**good, "goal": "x", "loop_seed": -1}, "goal_invalid"),
        ({**good, "loop_seed": -1, "iteration_cap": 0}, "seed_invalid"),
        ({**good, "iteration_cap": 0, "setup": None}, "iteration_cap_invalid"),
        ({**good, "setup": None}, "setup_invalid"),
    ]
    before = _log(world)
    for body, reason in cases:
        _refused(_post(world, body), reason)
    _no_side_effects(world, before)
    # dry_run comes after loop_id_invalid and before every other check.
    dry = _open(base, tmp_path / "dry", monkeypatch, dry=True)
    before = _log(dry)
    _refused(_post(dry, {**ligand_body(dry), "extra": 1}), "unknown_field")
    _refused(_post(dry, {**ligand_body(dry), "loop_id": bad_loop_id}), "loop_id_invalid")
    for body in ({**ligand_body(dry), "branch": "x", "pool": None}, ligand_body(dry), protein_body(dry)):
        _refused(_post(dry, body), "dry_run")
    _no_side_effects(dry, before)


def test_capability_comes_before_loop_active_and_the_pool(base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    _created(world, ligand_body(world))
    before = _log(world)
    _refused(_post(world, ligand_body(world, pool=None)), "loop_active")   # loop_active before pool_invalid
    monkeypatch.setattr(docking_bundle, "WORKER_PYTHON", tmp_path / "missing/python")   # fault injection
    docking_bundle._HANDSHAKE_CACHE.clear()
    try:
        detail = _refused(_post(world, ligand_body(world, pool=None)), "capability_unavailable")
        assert detail["capability"] == {"reason_code": "worker_missing", "reason": docking_bundle.REASONS[
            "worker_missing"]}
        _refused(_post(world, protein_body(world, pool=None)), "capability_unavailable")   # docking env too
    finally:
        monkeypatch.undo()
        docking_bundle._HANDSHAKE_CACHE.clear()
    _no_side_effects(world, before)


def test_a_missing_protein_engine_is_capability_unavailable_and_the_ligand_branch_still_works(
        base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)

    def missing(*args):   # fault injection: PDBFixer not installed
        raise PackageNotFoundError("pdbfixer")

    monkeypatch.setattr(mutation_model_bundle, "_pdbfixer_version", missing)
    before = _log(world)
    detail = _refused(_post(world, protein_body(world)), "capability_unavailable")
    assert detail["capability"] == {"reason_code": "pdbfixer_unavailable",
                                    "reason": mutation_model_bundle.REASONS["pdbfixer_unavailable"]}
    _no_side_effects(world, before)
    assert _created(world, ligand_body(world))["status"] == "active"


@pytest.mark.parametrize("loop_id", ["not-a-uuid", "00000000-0000-1000-8000-000000000000", None, 7,
                                     "6F1C2A3B-4D5E-4F60-8A7B-9C0D1E2F3A4B", "6f1c2a3b4d5e4f608a7b9c0d1e2f3a4b"])
def test_loop_id_must_be_a_canonical_v4_uuid(loop_id, base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    before = _log(world)
    _refused(_post(world, ligand_body(world, loop_id=loop_id)), "loop_id_invalid")
    _refused(_post(world, {key: value for key, value in ligand_body(world).items() if key != "loop_id"}),
             "loop_id_invalid")
    _no_side_effects(world, before)


# ---------------------------------------------------------------- idempotency and one active loop per branch


def test_the_same_loop_id_and_body_answers_the_existing_record_and_another_body_conflicts(
        base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    ligand = ligand_body(world)
    first = _created(world, ligand)
    protein = protein_body(world)
    protein_first = _created(world, protein)
    stable = _log(world)
    # Same request, also with another key order, candidate order or number spelling: no new event, same record.
    reordered = {key: ligand[key] for key in reversed(list(ligand))}
    reordered["pool"] = {**ligand["pool"], "candidates": list(reversed(ligand["pool"]["candidates"]))}
    for body in (ligand, reordered, _with(ligand, ("setup", "box", "margin_A"), 8.0),
                 _with(ligand, ("setup", "parameters"), {"seed": 7, "exhaustiveness": 8})):
        assert _created(world, body) == first
    for body in (protein, _with(protein, ("setup", "contact_cutoff_A"), 4),
                 _with(protein, ("setup", "contact_cutoff_A"), 4.0)):
        assert _created(world, body) == protein_first
    assert _log(world) == stable
    for body in (_with(ligand, ("loop_seed",), 8), _with(ligand, ("goal",), "exploit"),
                 _with(ligand, ("iteration_cap",), 4), _with(ligand, ("pool", "candidates"), ligand["pool"][
                     "candidates"][:2]), _with(ligand, ("setup", "parameters", "seed"), 8),
                 _with(ligand, ("branch",), "protein"), _with(ligand, ("setup",), None),
                 _with(ligand, ("loop_seed",), 7.0), _with(protein, ("loop_id",), ligand["loop_id"]),
                 _with(protein, ("setup", "contact_cutoff_A"), 5.0)):
        _refused(_post(world, body), "loop_id_conflict")
    assert _log(world) == stable and world["fake"].requests == []


def test_one_unended_loop_per_branch_and_the_other_branch_is_allowed(base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    first = _created(world, ligand_body(world))
    before = _log(world)
    _refused(_post(world, ligand_body(world)), "loop_active")
    assert _log(world) == before
    protein = _created(world, protein_body(world))       # the other branch: its own active loop
    _refused(_post(world, protein_body(world)), "loop_active")
    # LABELLED SYNTHETIC end event (the end route is T6): once a loop has ended, the branch takes a new loop.
    world["run"].events.append(L.EVENT_ENDED, loop_id=first["loop_id"], end_reason="ended_by_user",
                               result_handle=f"obj://{RID}/{L.RESULT_KIND}/{'0' * 64}")
    second = _created(world, ligand_body(world))
    assert second["status"] == "active" and second["loop_id"] != first["loop_id"]
    _refused(_post(world, protein_body(world)), "loop_active")
    assert protein["status"] == "active"


# ---------------------------------------------------------------- the pool


def test_pool_refusals(base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    ids, indexes = world["ids"], world["indexes"]
    rows = world["run"].store.load(world["ligand_set"])["candidates"]
    low = min(row["properties"]["heavy_atoms"] for row in rows)
    high = max(row["properties"]["heavy_atoms"] for row in rows)
    assert low < high   # the stored values differ, so a range can exclude a candidate
    heaviest = next(row["id"] for row in rows if row["properties"]["heavy_atoms"] == high)
    other_run = f"obj://run_other/ligand_candidate_set/{'a' * 64}"
    lig, pro = ligand_body(world), protein_body(world)
    cases = [
        _with(lig, ("pool",), None), _with(lig, ("pool",), []), _with(lig, ("pool", "extra"), 1),
        _with(lig, ("pool", "source"), ...), _with(lig, ("pool", "candidates"), ...),
        _with(lig, ("pool", "candidates"), ids[:1]),                                         # one candidate
        _with(lig, ("pool", "candidates"), [ids[0], ids[0]]),                                # duplicate
        _with(lig, ("pool", "candidates"), [ids[0], "c_" + "f" * 16]),                       # not in the set
        _with(lig, ("pool", "candidates"), [ids[0], 1]), _with(lig, ("pool", "candidates"), "x"),
        _with(lig, ("pool", "candidates"), [ids[0], ids[1].upper()]),
        _with(lig, ("pool", "source"), world["ubq_set"]),                                    # the other kind
        _with(lig, ("pool", "source"), world["parent"]), _with(lig, ("pool", "source"), other_run),
        _with(lig, ("pool", "source"), "obj://not a handle"), _with(lig, ("pool", "source"), 3),
        _with(lig, ("pool", "filter"), {"ranges": {"unknown_property": {"max": 1}}}),         # malformed filter
        _with(lig, ("pool", "filter"), {"ranges": {}, "pains_exclude": "yes"}), _with(lig, ("pool", "filter"), []),
        _with(_with(lig, ("pool", "candidates"), [ids[0], heaviest] if heaviest != ids[0] else [ids[1], heaviest]),
              ("pool", "filter"), {"ranges": {"heavy_atoms": {"max": high - 1}}}),            # filtered out
        _with(pro, ("pool", "candidates"), indexes[:21]),                                    # 21 candidates
        _with(pro, ("pool", "candidates"), [indexes[0]]),
        _with(pro, ("pool", "candidates"), [indexes[0], indexes[0]]),
        _with(pro, ("pool", "candidates"), [indexes[0], 10_000]),
        _with(pro, ("pool", "candidates"), [indexes[0], True]), _with(pro, ("pool", "candidates"), [0, "1"]),
        _with(pro, ("pool", "candidates"), [0, -1]),
        _with(pro, ("pool", "source"), world["ligand_set"]),                                 # the other kind
        _with(pro, ("pool", "source"), world["ubq_structure"]),
        _with(pro, ("pool", "filter"), {"ranges": {}}),                                      # protein: null only
    ]
    before = _log(world)
    for body in cases:
        _refused(_post(world, body), "pool_invalid")
    _no_side_effects(world, before)
    # 20 is the cap (accepted) and a filter every chosen candidate passes is kept, normalized.
    twenty = _created(world, _with(pro, ("pool", "candidates"), indexes[:20]))
    assert len(twenty["candidates"]) == 20 and twenty["effective_cap"] == 8
    kept = _created(world, _with(lig, ("pool", "filter"), {"ranges": {"heavy_atoms": {"max": high}}}))
    assert kept["pool"]["filter"] == {"ranges": {"heavy_atoms": {"min": None, "max": high}}, "pains_exclude": False}


@pytest.mark.parametrize("field,values,reason", [
    ("goal", ["neutral", None, "", "EXPLORE", 1, ...], "goal_invalid"),
    ("loop_seed", [-1, 2_147_483_648, 1.0, True, "1", None, ...], "seed_invalid"),
    ("iteration_cap", [0, 9, 5.0, True, "5", None, ...], "iteration_cap_invalid"),
    ("branch", ["Ligand", None, "mutation", 1, ...], "branch_invalid"),
])
def test_goal_seed_iteration_cap_and_branch_values(field, values, reason, base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    before = _log(world)
    for value in values:
        _refused(_post(world, _with(ligand_body(world), (field,), value)), reason)
    _no_side_effects(world, before)


def test_seed_and_cap_bounds_are_accepted_and_the_effective_cap_is_the_smaller(base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    low = _created(world, ligand_body(world, loop_seed=0, iteration_cap=1))
    assert (low["loop_seed"], low["iteration_cap"], low["effective_cap"]) == (0, 1, 1)
    high = _created(world, protein_body(world, loop_seed=2_147_483_647, iteration_cap=8))
    assert (high["loop_seed"], high["iteration_cap"], high["effective_cap"]) == (2_147_483_647, 8, 3)


# ---------------------------------------------------------------- the setup (closed names, first submission's reasons)


def _ligand_job_reason(world, setup, ref):
    """The reason the real job lane gives a standalone M18 free request built from the RAW setup (the oracle)."""
    request = {key: setup[key] for key in ("receptor_handle", "receptor_model_number", "connectivity",
                                           "receptor_instance", "box", "parameters", "acknowledgement")
               if key in setup}
    request.update(mode="free", ligand={"source": "candidate", "candidate_set_handle": world["ligand_set"],
                                        "candidate_id": ref, "parent_sdf_handle": setup.get("parent_sdf_handle")})
    try:
        JobQueue(world["run"]).submit(DC.PROTOCOL, request, timeout_s=300)
    except ToolFailure as exc:
        return exc.detail.get("reason_code")
    return None


def test_ligand_setup_refusals_are_the_m18_submission_reasons(base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    body = ligand_body(world)
    setup = body["setup"]
    missing_instance = {"model_number": 1, "chain_auth": "Z", "chain_label": None, "seq_auth": 999,
                        "seq_label": None, "icode": "", "resname": "LIG"}
    cases = [
        ({**setup, "parameters": {"seed": 7, "conformers": 5}}, "invalid_job_arguments"),
        ({**setup, "parameters": {"seed": DC.SEED_MAX + 1}}, "invalid_job_arguments"),
        ({**setup, "acknowledgement": {**ACK, "rigid_no_optimization": False}}, "acknowledgement_missing"),
        ({k: v for k, v in setup.items() if k != "acknowledgement"}, "acknowledgement_missing"),
        ({**setup, "box": {"source": "manual", "center_A": [0, 0, 0], "size_A": [5, 20, 20]}}, "box_invalid"),
        ({**setup, "box": {"source": "manual", "center_A": [0, 0, 0], "size_A": [41, 20, 20]}}, "box_too_large"),
        ({**setup, "box": {"source": "instance_range", "margin_A": 8}}, "box_invalid"),
        ({**setup, "parent_sdf_handle": world["phenol"]}, "parent_mismatch"),
        ({**setup, "receptor_handle": world["parent"]}, "invalid_job_arguments"),
        ({**setup, "parent_sdf_handle": world["receptor"]}, "invalid_job_arguments"),
        ({**setup, "receptor_instance": missing_instance}, "receptor_instance_unknown"),
        ({**setup, "receptor_handle": world["ubq_receptor"]}, None),     # whatever M18 says (closed name)
    ]
    first = body["pool"]["candidates"][0]
    stored_first = world["ids"][0]   # the first pool candidate in the set's stored order
    assert first != stored_first
    before = _log(world)
    for raw_setup, reason in cases:
        job_reason = _ligand_job_reason(world, raw_setup, stored_first)
        assert job_reason is not None and (reason is None or job_reason == reason), (raw_setup, job_reason)
        detail = _refused(_post(world, {**body, "setup": raw_setup}), "setup_invalid")
        assert detail["setup_reason"] == job_reason and job_reason in LIGAND_REASONS, detail
    # Keys outside the closed setup and a missing or malformed setup: M18 invalid_job_arguments.
    for raw_setup in ({**setup, "mode": "free"}, {**setup, "filter": None}, {**setup, "candidate_set_handle": "x"},
                      {k: v for k, v in setup.items() if k != "parent_sdf_handle"},
                      {k: v for k, v in setup.items() if k != "box"}, [], "setup", None):
        detail = _refused(_post(world, {**body, "setup": raw_setup}), "setup_invalid")
        assert detail["setup_reason"] == "invalid_job_arguments"
    detail = _refused(_post(world, {k: v for k, v in body.items() if k != "setup"}), "setup_invalid")
    assert detail["setup_reason"] == "invalid_job_arguments"
    _no_side_effects(world, before)   # the oracle's submissions were refused too: no job, no loop event


def _model_job_reason(world, setup, source, ref):
    request = {"candidate_set": source, "candidate_index": ref, "seed": setup["parameters"]["seed"],
               **{key: setup[key] for key in ("selection_policy", "hydrogen_policy", "contact_cutoff_A")
                  if key in setup}}
    try:
        JobQueue(world["run"]).submit(MC.PROTOCOL, request, timeout_s=120)
    except ToolFailure as exc:
        return exc.detail.get("reason_code")
    return None


def test_protein_setup_refusals_are_the_m18_pure_and_m21_server_reasons(base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    body = protein_body(world)
    setup = body["setup"]
    cases = [
        ({**setup, "mode": "free"}, "invalid_job_arguments"),
        ({**setup, "receptor_handle": world["receptor"]}, "invalid_job_arguments"),
        ({**setup, "ligand": {"source": "sdf"}}, "invalid_job_arguments"),
        ({**setup, "ligand": {"source": "candidate", "candidate_set_handle": world["ligand_set"],
                              "candidate_id": world["ids"][0], "parent_sdf_handle": world["parent"]}},
         "mode_source_mismatch"),
        ({**setup, "box": {"source": "instance_range", "margin_A": 8}}, "box_invalid"),
        ({**setup, "box": {"source": "manual", "center_A": [0, 0, 0], "size_A": [50, 20, 20]}}, "box_too_large"),
        ({**setup, "parameters": {"seed": 1, "conformers": 2}}, "invalid_job_arguments"),
        ({k: v for k, v in setup.items() if k != "acknowledgement"}, "acknowledgement_missing"),
        ({k: v for k, v in setup.items() if k != "ligand"}, "invalid_job_arguments"),
        ({**setup, "ligand": {"source": "sdf", "sdf_handle": world["receptor"]}}, "invalid_job_arguments"),
        ({**setup, "ligand": {"source": "sdf", "sdf_handle": f"obj://{RID}/chemical_raw_input/{'b' * 64}"}},
         "invalid_job_arguments"),
    ]
    before = _log(world)
    for raw_setup, reason in cases:
        detail = _refused(_post(world, {**body, "setup": raw_setup}), "setup_invalid")
        assert detail["setup_reason"] == reason, (raw_setup, detail)
    # The M21 part: the reason the real M21 job lane gives the first pool candidate's request (the oracle).
    stored_first = world["indexes"][0]
    m21 = [({**setup, "selection_policy": "all_atoms"}, "confirmation_missing"),
           ({k: v for k, v in setup.items() if k != "hydrogen_policy"}, "confirmation_missing"),
           ({**setup, "contact_cutoff_A": 7.0}, "argument_invalid"),
           ({**setup, "contact_cutoff_A": 2.4}, "argument_invalid"),
           ({**setup, "contact_cutoff_A": True}, "argument_invalid"),
           ({**setup, "contact_cutoff_A": "4.0"}, "argument_invalid"),
           ({**setup, "contact_cutoff_A": None}, "argument_invalid")]
    for raw_setup, reason in m21:
        assert _model_job_reason(world, raw_setup, world["ubq_set"], stored_first) == reason
        detail = _refused(_post(world, {**body, "setup": raw_setup}), "setup_invalid")
        assert detail["setup_reason"] == reason
    # 1MQ4 passes M21 admission 1-7 and fails the M7 preflight at submission (T1 (f)): refused when made.
    mq4 = _with(body, ("pool", "source"), world["mq4_set"])
    mq4["pool"]["candidates"] = world["mq4_indexes"][:2]
    assert _model_job_reason(world, setup, world["mq4_set"], world["mq4_indexes"][0]) == "openmm_preflight_failed"
    detail = _refused(_post(world, mq4), "setup_invalid")
    assert detail["setup_reason"] == "openmm_preflight_failed" and detail["setup_reason"] in PROTEIN_REASONS
    loop_events = [event for event in _events(world)[len(before.splitlines()):] if event["type"] in L.EVENT_TYPES]
    assert loop_events == [] and world["fake"].requests == []
    assert _created(world, _with(body, ("setup", "contact_cutoff_A"), 6))["setup"]["contact_cutoff_A"] == 6.0


# ---------------------------------------------------------------- HTTP shape: JSON only, body bound, busy


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded",
                                          "multipart/form-data; boundary=pv", "application/jsonx", None])
def test_create_takes_application_json_only_and_refuses_before_reading(content_type, base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    raw = json.dumps(ligand_body(world)).encode()
    before = _log(world)
    headers = {} if content_type is None else {"content-type": content_type}
    for content in (raw, b"not json", raw + b" " * (L.MAX_CREATE_REQUEST_BYTES + 1)):
        response = _post(world, None, raw=content, headers=headers)
        assert response.status_code == 415, response.text
        assert response.json()["detail"]["error"] == "unsupported_media_type"
    _no_side_effects(world, before)


def test_create_body_bound_json_shape_and_query(base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    body = ligand_body(world)
    before = _log(world)
    padded = json.dumps({**body, "setup": {**body["setup"], "pad": "x" * L.MAX_CREATE_REQUEST_BYTES}}).encode()
    assert _post(world, None, raw=padded).status_code == 413
    for raw in (b"not json", b"[]", b'{"loop_id": 1, "loop_id": 2}', b'{"loop_seed": NaN}'):
        response = _post(world, None, raw=raw)
        assert response.status_code == 422 and response.json()["detail"]["error"] == "input_invalid", raw
    response = world["client"].post(f"/runs/{RID}/jev_loops?x=1", content=json.dumps(body).encode(), headers=JSON)
    assert response.status_code == 422
    assert world["client"].post("/runs/run_missing_m25/jev_loops", content=b"{}", headers=JSON).status_code == 404
    _no_side_effects(world, before)
    ok = world["client"].post(f"/runs/{RID}/jev_loops", content=json.dumps(body).encode(),
                              headers={"content-type": "Application/JSON; charset=utf-8"})
    assert ok.status_code == 200, ok.text
    assert len(json.dumps(protein_body(world, pool={**protein_body(world)["pool"], "candidates": world[
        "indexes"][:20]})).encode()) < L.MAX_CREATE_REQUEST_BYTES


def test_a_held_run_lock_is_503_busy_and_writes_nothing(base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    before = _log(world)
    with world["run"]._owner():   # fault injection: another owner (a Run.call, a job start) holds the run lock
        response = _post(world, ligand_body(world))
    assert response.status_code == 503 and response.json()["detail"]["error"] == "busy", response.text
    _no_side_effects(world, before)


# ---------------------------------------------------------------- /capabilities methods.jev_loop


def test_capability_names_the_branch_reasons_without_numbers(base, tmp_path, monkeypatch):
    world = _open(base, tmp_path, monkeypatch)
    client = world["client"]
    methods = client.get("/capabilities").json()["methods"]
    assert "jev_loop" in methods
    loop = methods["jev_loop"]
    assert set(loop) == {"ligand", "protein"}
    # M25 T4 registered the projection tool: both branches are available on this host (real engines). (This test
    # pinned tool_unavailable while T3 had no tool; the unexposed case is now simulated below.)
    for branch in L.BRANCHES:
        assert loop[branch] == {"available": True, "reason_code": None, "reason": None}
    monkeypatch.setattr(api_module, "SUPPORTED_TOOLS", api_module.SUPPORTED_TOOLS - {L.TOOL})   # tool not exposed
    loop = client.get("/capabilities").json()["methods"]["jev_loop"]
    for branch in L.BRANCHES:
        assert loop[branch] == {"available": False, "reason_code": "tool_unavailable",
                                "reason": jev_loop_store.CAPABILITY_REASONS["tool_unavailable"]}
    monkeypatch.setattr(api_module, "SUPPORTED_TOOLS", api_module.SUPPORTED_TOOLS | {L.TOOL})
    loop = client.get("/capabilities").json()["methods"]["jev_loop"]
    for branch in L.BRANCHES:
        assert loop[branch] == {"available": True, "reason_code": None, "reason": None}
    monkeypatch.setattr(egress_science, "_pins_match", lambda pins: False)   # fault injection: edited pins
    loop = client.get("/capabilities").json()["methods"]["jev_loop"]
    assert {branch: loop[branch]["reason_code"] for branch in L.BRANCHES} == dict.fromkeys(
        L.BRANCHES, "missing_configuration")
    monkeypatch.setattr(egress_science, "_pins_match", lambda pins: True)

    def missing(*args):   # fault injection: PDBFixer not installed
        raise PackageNotFoundError("pdbfixer")

    monkeypatch.setattr(mutation_model_bundle, "_pdbfixer_version", missing)
    loop = client.get("/capabilities").json()["methods"]["jev_loop"]
    assert loop["ligand"]["available"] is True
    assert loop["protein"] == {"available": False, "reason_code": "pdbfixer_unavailable",
                               "reason": mutation_model_bundle.REASONS["pdbfixer_unavailable"]}
    monkeypatch.setattr(docking_bundle, "WORKER_PYTHON", tmp_path / "missing/python")
    docking_bundle._HANDSHAKE_CACHE.clear()
    try:
        loop = client.get("/capabilities").json()["methods"]["jev_loop"]
        assert loop["ligand"] == {"available": False, "reason_code": "worker_missing",
                                  "reason": docking_bundle.REASONS["worker_missing"]}
        assert loop["protein"]["reason_code"] == "pdbfixer_unavailable"   # OpenMM / PDBFixer before docking
    finally:
        monkeypatch.undo()
        docking_bundle._HANDSHAKE_CACHE.clear()


# ---------------------------------------------------------------- module and route boundaries


def test_the_store_module_names_no_send_path_limit_raise_or_m24_event_string():
    text = (MW / "jev_loop_store.py").read_text()
    assert "raise_limits" not in text and "limit_approval" not in text
    for event in (J.EVENT_CONSENT, J.EVENT_APPROVED, J.EVENT_DISPATCH, J.EVENT_OUTCOME):
        assert event not in text, event
    tree = ast.parse(text)
    names = {node.id if isinstance(node, ast.Name) else node.attr for node in ast.walk(tree)
             if isinstance(node, (ast.Name, ast.Attribute))}
    assert not names & {"run_send", "request_science", "SCIENCE_GATE", "begin_send", "jev_sends", "egress",
                        "raise_limits", "limit_approval"}
    modules = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    modules |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    for module in modules:
        assert module.split(".")[0] not in {"httpx", "rdkit", "meeko", "MDAnalysis", "pdbfixer", "urllib", "http",
                                            "requests", "socket", "aiohttp", "fastapi"}, module
        assert "jev_sends" not in module and "egress" not in module, module


def test_importing_the_store_module_loads_no_send_or_network_module():
    code = ("import sys, mw.jev_loop_store\n"
            "bad = [m for m in ('httpx', 'mw.jev_sends', 'mw.egress', 'mw.egress.gate', 'mw.egress.science',"
            " 'fastapi', 'rdkit', 'meeko', 'MDAnalysis', 'pdbfixer') if m in sys.modules]\n"
            "print(bad)\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=str(MW.parent))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr


def test_the_create_route_is_one_post_that_names_no_send_job_or_limit_path():
    routes = [(route.path, sorted(route.methods)) for route in api_module.app.routes
              if getattr(route, "endpoint", None) is not None and route.endpoint.__name__ == "jev_loop_create"]
    assert routes == [("/runs/{rid}/jev_loops", ["POST"])]
    tree = ast.parse((MW / "api/app.py").read_text())
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "jev_loop_create")
    names = {node.id if isinstance(node, ast.Name) else node.attr for node in ast.walk(function)
             if isinstance(node, (ast.Name, ast.Attribute))}
    assert not names & {"run_send", "request_science", "SCIENCE_GATE", "raise_limits", "limit_approval",
                        "JobQueue", "submit", "start"}
    store = ast.parse((MW / "jev_loop_store.py").read_text())
    called = {node.func.attr for node in ast.walk(store) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)}
    assert not called & {"submit", "start", "retry", "request_cancel", "call", "reserve_attempt", "approve"}
