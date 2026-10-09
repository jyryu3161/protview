"""M25 T3-B: the loop read layer and ``GET /runs/{rid}/jev_loops`` / ``GET /runs/{rid}/jev_loops/{loop_id}`` (spec
.dryforge/spec.md 3.2, 3.3, 6.4, 9.1, 11).

Two real scenarios run once per module through the product job lane (``JobQueue.submit`` / ``start`` /
``request_cancel`` with the pinned docking worker, ``qvina2`` and the M21 OpenMM / PDBFixer worker; a missing engine
FAILS, never skips): a ligand loop over a real M17 candidate set (the T3-A template run) and a protein loop over a real
M20 set of public 1UBQ in a fresh run (no first expensive-call approval yet). The compute route is T6, so each loop
step's ``jev_loop_compute_approved`` event is written by the ``approve`` test helper below (LABELLED: the test writes it
with the key the step's real job gets) and the job is submitted with the loop's own request builder. Small manual box /
exhaustiveness 1 keep docking short; engine values are never an oracle: expected scores are read from the stored
``docking_result@1`` objects. Expected states, phases, counts and ``current`` are written by hand from the spec rule
next to each stage. Padding objects (``synthetic_padding@1``) and the malformed approval event are LABELLED SYNTHETIC
fault / size injections.
"""
from __future__ import annotations

import base64
import copy
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jev_send_fixture import Fake
from ligand_job_fixture import import_file, new_ligand_run
from test_jev_loops_api import DRY_RID, FIX, I44, PHENOL, RID, UBQ, _template, ligand_body, protein_body

from mw import docking_bundle, jev_loop_store, jev_loops, mutation_model_bundle
from mw import docking_constants as DC
from mw import jev_loop_constants as L
from mw import jev_sends as S
from mw import mutation_model_constants as MC
from mw.api import app as api_module
from mw.core.handles import canonical_json, object_sha
from mw.jobs.queue import JobQueue
from mw.runtime.orchestrator import ApprovalRequired
from mw.workspace import new_run

CENTER = json.loads((FIX / "docking/expected.json").read_text())["public_example_box"]["center_A"]
SMALL_BOX = {"source": "manual", "center_A": CENTER, "size_A": [12.0, 12.0, 12.0]}
FAST = {"seed": 1, "exhaustiveness": 1, "num_modes": 2}
PROTEIN_FAST = {"seed": 20261007, "exhaustiveness": 1, "num_modes": 2}
PRID = "run_m25_loops_protein"
LOOP_L = "1c6f0a6e-3b1d-4b8e-9a51-6a2d1f0b7c11"
LOOP_P = "2d7e1b7f-4c2e-4c9f-8b62-7b3e2a1c8d22"
OTHER_LOOP = "3e8f2c80-5d3f-4dab-9c73-8c4f3b2d9e33"
ZERO = {"expensive_units": 0, "wall_clock_s": 0, "external_tokens": None, "usd": None, "sends": 0}
JSON = {"content-type": "application/json"}


# ---------------------------------------------------------------- helpers


class _Api:
    """Serve ``root`` through the product app with these live ``Run`` objects (module-scope setup; restored after)."""

    def __init__(self, root: Path, runs: dict) -> None:
        self.saved = (api_module.RUNS_DIR, dict(api_module.RUNS), api_module.SCIENCE_GATE)
        api_module.RUNS_DIR = root
        api_module.RUNS.clear()
        api_module.RUNS.update(runs)
        api_module.SCIENCE_GATE = Fake().gate
        self.client = TestClient(api_module.app, base_url="http://127.0.0.1")

    def detail(self, rid: str, loop_id: str) -> dict:
        response = self.client.get(f"/runs/{rid}/jev_loops/{loop_id}")
        assert response.status_code == 200, response.text
        return response.json()

    def close(self) -> None:
        api_module.RUNS_DIR, runs, api_module.SCIENCE_GATE = self.saved
        api_module.RUNS.clear()
        api_module.RUNS.update(runs)


def approve(run, loop_id, iteration, step, ref, call_key, units=1):
    """LABELLED test stand-in for the T6 compute route's approval event (exactly the spec 6.1 payload)."""
    run.events.append(L.EVENT_COMPUTE_APPROVED, loop_id=loop_id, iteration=iteration, step=step, candidate_ref=ref,
                      decided_by="human", proposal_handle=None, call_key=call_key, units=units,
                      approved_by=L.APPROVED_BY)


def created_of(run, loop_id):
    return jev_loop_store.created_payload(list(run.events.read()), loop_id)


def first_mode(run, handle):
    """The stored first-mode qvina score, read from the stored object itself (not through the loop code)."""
    modes = run.store.load(handle)["modes"]
    return modes[0]["score_kcal_mol"] if modes else None


def log_bytes(run) -> bytes:
    return (run.run_dir / "events.jsonl").read_bytes()


def _ligand_scenario(root: Path) -> dict:
    world = _template(root)
    run = new_ligand_run(root, RID)          # reopened from its events: the M17 jobs approved expensive calls
    api = _Api(root, {RID: run})
    out = {"world": world, "root": root, "records": {}, "logs": {}, "jobs": {}}
    try:
        ids = world["ids"]
        body = ligand_body(world, loop_id=LOOP_L, goal="exploit", iteration_cap=4)
        body["pool"]["candidates"] = [ids[3], ids[1], ids[0], ids[2]]
        body["setup"] = {**body["setup"], "box": SMALL_BOX, "parameters": FAST}
        response = api.client.post(f"/runs/{RID}/jev_loops", content=json.dumps(body).encode(), headers=JSON)
        assert response.status_code == 200, response.text
        out["records"]["created"] = response.json()
        created = created_of(run, LOOP_L)
        setup, source = created["setup"], created["pool"]["source"]["handle"]
        a, b, c, d = created["pool"]["candidates"]
        keys = jev_loop_store.candidate_keys(created)
        out.update(refs=(a, b, c, d), keys=keys)
        queue = JobQueue(run)

        def submit(ref):
            job = queue.submit(DC.PROTOCOL, jev_loop_store.ligand_request(setup, source, ref),
                               timeout_s=L.STEP_TIMEOUT_DEFAULTS_S["ligand_dock"])
            assert job["call_key"] == keys[ref]["ligand_dock"] and job["status"] == "queued"
            return job["job_id"]

        # Outside the loop: A docked by a standalone M18 job (same call key), B's same-key job cancelled.
        out["jobs"]["a"] = submit(a)
        done = queue.start(out["jobs"]["a"])
        assert done["status"] == "done", done
        out["handles"] = {"a": done["output_handles"][0]}
        out["jobs"]["b"] = submit(b)
        assert queue.request_cancel(out["jobs"]["b"])["job"]["status"] == "cancelled"
        out["records"]["outside"] = api.detail(RID, LOOP_L)
        # Iteration 1: the human approves C, its job waits in the queue, then runs.
        approve(run, LOOP_L, 1, "ligand_dock", c, keys[c]["ligand_dock"])
        out["jobs"]["c"] = submit(c)
        out["records"]["queued"] = api.detail(RID, LOOP_L)
        out["logs"]["queued"] = log_bytes(run)
        done = queue.start(out["jobs"]["c"])
        assert done["status"] == "done", done
        out["handles"]["c"] = done["output_handles"][0]
        out["records"]["scored"] = api.detail(RID, LOOP_L)
        # Iteration 2: D approved, its job cancelled before any process started.
        approve(run, LOOP_L, 2, "ligand_dock", d, keys[d]["ligand_dock"])
        out["jobs"]["d"] = submit(d)
        assert queue.request_cancel(out["jobs"]["d"])["job"]["status"] == "cancelled"
        out["records"]["final"] = api.detail(RID, LOOP_L)
        out["logs"]["final"] = log_bytes(run)
        out["list"] = api.client.get(f"/runs/{RID}/jev_loops").json()
    finally:
        api.close()
    return out


def _protein_scenario(root: Path) -> dict:
    run = new_run(root, run_id=PRID, dry_run=False)
    loaded = run.call("load_structure", {"source": str(UBQ), "model_index": 0}).handle
    prepared = run.call("prepare_structure", {"structure": loaded}).handle
    mutation_set = run.call("generate_mutation_candidates", {
        "structure": prepared, "sources": {"pocket": None, "ligand_shell": None, "residues": [I44]}}).handle
    phenol = import_file(run, "ligand_sdf", "phenol.sdf", PHENOL)
    world = {"ubq_set": mutation_set, "phenol": phenol,
             "indexes": [row["index"] for row in run.store.load(mutation_set)["candidates"]]}
    api = _Api(root, {PRID: run})
    out = {"root": root, "records": {}, "logs": {}, "jobs": {}, "handles": {}}
    try:
        body = protein_body(world, loop_id=LOOP_P, goal="explore", iteration_cap=2)
        body["pool"]["candidates"] = [world["indexes"][17], world["indexes"][0]]   # I44W, I44A
        body["setup"] = {**body["setup"], "parameters": PROTEIN_FAST}
        response = api.client.post(f"/runs/{PRID}/jev_loops", content=json.dumps(body).encode(), headers=JSON)
        assert response.status_code == 200, response.text
        out["records"]["created"] = response.json()
        created = created_of(run, LOOP_P)
        setup, source = created["setup"], created["pool"]["source"]["handle"]
        other, w = created["pool"]["candidates"]                                    # stored order: A (0), W (17)
        keys = jev_loop_store.candidate_keys(created)
        out.update(refs=(other, w), keys=keys)
        queue = JobQueue(run)
        approve(run, LOOP_P, 1, "model", w, keys[w]["model"])
        job = queue.submit(MC.PROTOCOL, jev_loop_store.model_request(setup, source, w),
                           timeout_s=L.STEP_TIMEOUT_DEFAULTS_S["model"])
        assert job["call_key"] == keys[w]["model"]
        out["jobs"]["model"] = job["job_id"]
        with pytest.raises(ApprovalRequired):        # the run's first expensive call waits for the human
            queue.start(job["job_id"])
        out["records"]["approval"] = api.detail(PRID, LOOP_P)
        run.approve("expensive_first_call", by="test")
        done = queue.start(job["job_id"])
        assert done["status"] == "done", done
        model = done["output_handles"][0]
        out["handles"]["model"] = model
        out["records"]["awaiting_docking"] = api.detail(PRID, LOOP_P)
        dock_key = jev_loop_store.dock_call_key(setup, model, created["pins"]["m18"])
        assert jev_loop_store.candidate_keys(created, {keys[w]["model"]: model})[w]["dock"] == dock_key
        approve(run, LOOP_P, 1, "dock", w, dock_key)
        job = queue.submit(DC.PROTOCOL, jev_loop_store.dock_request(setup, model),
                           timeout_s=L.STEP_TIMEOUT_DEFAULTS_S["dock"])
        assert job["call_key"] == dock_key
        out["jobs"]["dock"] = job["job_id"]
        done = queue.start(job["job_id"])
        assert done["status"] == "done", done
        out["handles"]["dock"] = done["output_handles"][0]
        out["records"]["final"] = api.detail(PRID, LOOP_P)
        out["logs"]["final"] = log_bytes(run)
        out["run"] = run
    finally:
        api.close()
    return out


@pytest.fixture(scope="module")
def ligand(tmp_path_factory):
    return _ligand_scenario(tmp_path_factory.mktemp("jev_loop_read_ligand"))


@pytest.fixture(scope="module")
def protein(tmp_path_factory):
    return _protein_scenario(tmp_path_factory.mktemp("jev_loop_read_protein"))


@pytest.fixture(autouse=True)
def no_active_sends():
    S.ACTIVE_SENDS.clear()
    yield
    S.ACTIVE_SENDS.clear()


def _clone(tmp_path, monkeypatch, logs: dict[str, bytes]):
    """Events-only copies of run logs under one root, served by the API (Fake science gate)."""
    root = tmp_path / "runs"
    for rid, raw in logs.items():
        (root / rid).mkdir(parents=True)
        (root / rid / "events.jsonl").write_bytes(raw)
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    monkeypatch.setattr(api_module, "SCIENCE_GATE", Fake().gate)
    api_module.RUNS.clear()
    return root, TestClient(api_module.app, base_url="http://127.0.0.1")


def _template_logs(ligand) -> dict[str, bytes]:
    base = ligand["world"]["root"]
    return {rid: (base / rid / "events.jsonl").read_bytes() for rid in (DRY_RID,)}


def candidate(record, ref):
    return next(row for row in record["candidates"] if row["ref"] == ref)


def counts(**over):
    return {**dict.fromkeys(jev_loops.COUNT_KEYS, 0), **over}


# ---------------------------------------------------------------- ligand: states from real job records


def test_ligand_states_follow_the_real_job_records(ligand):
    a, b, c, d = ligand["refs"]
    run_store = new_ligand_run(ligand["root"], RID)
    score_a, score_c = first_mode(run_store, ligand["handles"]["a"]), first_mode(run_store, ligand["handles"]["c"])
    assert score_a is not None and score_c is not None   # small box: both runs returned modes

    created = ligand["records"]["created"]
    assert [row["state"] for row in created["candidates"]] == ["pending"] * 4
    assert created["current"]["action"] == "select" and created["counts"] == counts()

    # Spec 3.2 priority 2: A has a same-key stored, validated result -> reused (scored, its first mode);
    # priority 3: B's same-key job is unusable (cancelled outside the loop) -> unavailable.
    outside = ligand["records"]["outside"]
    assert candidate(outside, a) == {"ref": a, "display": candidate(created, a)["display"], "state": "scored",
                                     "evaluation": "reused", "score_kcal_mol": score_a, "iteration": None}
    assert candidate(outside, b)["state"] == "unavailable" and candidate(outside, b)["evaluation"] is None
    assert [candidate(outside, ref)["state"] for ref in (c, d)] == ["pending", "pending"]
    assert outside["counts"] == counts(reused_count=1) and outside["exhausted_reason"] is None
    assert outside["current"]["action"] == "select" and outside["current"]["iteration"] == 1

    # Iteration 1 approved, its job queued and not started: running / waiting_start, C held pending, nothing charged.
    queued = ligand["records"]["queued"]
    assert queued["current"] == {
        "iteration": 1, "phase": "running", "step": "ligand_dock", "action": "wait_job", "needs": ZERO,
        "remaining": queued["current"]["remaining"], "blocked_axes": [], "send_blocked_axes": [], "can_end": False,
        "job": {"job_id": ligand["jobs"]["c"], "step": "ligand_dock", "status": "queued", "start_blocked": None}}
    assert candidate(queued, c)["state"] == "pending" and queued["counts"] == counts(reused_count=1)
    step = {"step": "ligand_dock", "candidate_ref": c, "job_id": ligand["jobs"]["c"],
            "call_key": ligand["keys"][c]["ligand_dock"], "result_handle": None, "state": "waiting_start",
            "reason_code": None, "evaluation": None}
    assert queued["iterations"] == [{
        "index": 1, "phase": "running", "decided_by": "human", "candidate_ref": c, "proposal_handle": None,
        "list_position": None, "list_size": None,
        "approvals": [{"step": "ligand_dock", "candidate_ref": c, "decided_by": "human", "proposal_handle": None,
                       "call_key": ligand["keys"][c]["ligand_dock"]}],
        "sends": [], "steps": [step], "state": "in_progress", "score_kcal_mol": None}]

    # The job ran (charged) and its result is published: C scored by this loop's iteration 1.
    scored = ligand["records"]["scored"]
    assert candidate(scored, c) == {"ref": c, "display": candidate(created, c)["display"], "state": "scored",
                                    "evaluation": "computed", "score_kcal_mol": score_c, "iteration": 1}
    first = scored["iterations"][0]
    assert (first["phase"], first["state"], first["score_kcal_mol"]) == ("done", "scored", score_c)
    assert first["steps"][0] == {**step, "result_handle": ligand["handles"]["c"], "state": "completed",
                                 "evaluation": "computed"}
    assert scored["counts"] == counts(started=1, done=1, human_decided=1, units_charged=1, reused_count=1)
    assert (scored["current"]["iteration"], scored["current"]["action"]) == (2, "select")
    assert scored["current"]["needs"]["expensive_units"] == 1 and scored["current"]["needs"]["sends"] == 0

    # Iteration 2 approved D, whose job was cancelled before any process: D unavailable, iteration 2 not started,
    # no pending candidate left -> pool_exhausted (the loop stays active until a person ends it).
    final = ligand["records"]["final"]
    assert candidate(final, d)["state"] == "unavailable" and candidate(final, d)["iteration"] is None
    assert [candidate(final, ref)["state"] for ref in (a, b, c, d)] == ["scored", "unavailable", "scored",
                                                                       "unavailable"]
    second = final["iterations"][1]
    assert (second["index"], second["state"], second["steps"][0]["state"], second["candidate_ref"]) == (
        2, "unavailable", "unavailable", d)
    assert final["counts"] == counts(started=1, done=1, human_decided=1, units_charged=1, reused_count=1)
    assert (final["status"], final["exhausted_reason"]) == ("active", "pool_exhausted")
    assert final["current"] | {"remaining": None} == {
        "iteration": None, "phase": None, "step": None, "action": "end", "needs": ZERO, "remaining": None,
        "blocked_axes": [], "send_blocked_axes": [], "can_end": True, "job": None}


def test_the_list_is_one_row_per_loop_newest_first(ligand, tmp_path, monkeypatch):
    rows = ligand["list"]
    assert [row["loop_id"] for row in rows] == [LOOP_L]
    final = ligand["records"]["final"]
    assert rows[0] == {"loop_id": LOOP_L, "branch": "ligand", "status": "active", "end_reason": None,
                       "goal": "exploit", "pool_size": 4, "counts": final["counts"],
                       "created_seq": next(event["seq"] for event in map(json.loads, ligand["logs"][
                           "final"].splitlines()) if event["type"] == L.EVENT_CREATED)}
    _root, client = _clone(tmp_path, monkeypatch, {RID: ligand["logs"]["final"]})
    body = protein_body({"ubq_set": ligand["world"]["ubq_set"], "phenol": ligand["world"]["phenol"],
                         "indexes": ligand["world"]["indexes"]}, loop_id=OTHER_LOOP)
    assert client.post(f"/runs/{RID}/jev_loops", content=json.dumps(body).encode(), headers=JSON).status_code == 200
    rows = client.get(f"/runs/{RID}/jev_loops").json()
    assert [row["loop_id"] for row in rows] == [OTHER_LOOP, LOOP_L]
    assert rows[0]["created_seq"] > rows[1]["created_seq"] and rows[0]["branch"] == "protein"
    assert all(set(row) == set(jev_loops.ROW_KEYS) for row in rows)


# ---------------------------------------------------------------- protein: model, approval wait, docking


def test_protein_states_follow_the_model_then_the_docking_job(protein):
    other, w = protein["refs"]
    run = protein["run"]
    approval = protein["records"]["approval"]
    # The first expensive call waits for the human: the job is claimed and blocked, nothing charged yet.
    assert approval["current"] == {
        "iteration": 1, "phase": "running", "step": "model", "action": "wait_job", "needs": ZERO,
        "remaining": approval["current"]["remaining"], "blocked_axes": [], "send_blocked_axes": [], "can_end": False,
        "job": {"job_id": protein["jobs"]["model"], "step": "model", "status": "claimed",
                "start_blocked": "approval_required"}}
    assert candidate(approval, w)["state"] == "pending" and approval["counts"] == counts()

    # Model done (charged), no docking decision yet: awaiting_docking; the candidate is still pending.
    waiting = protein["records"]["awaiting_docking"]
    assert waiting["current"] == {
        "iteration": 1, "phase": "awaiting_docking", "step": "dock", "action": "dock",
        "needs": {**ZERO, "expensive_units": 1, "wall_clock_s": 300}, "remaining": waiting["current"]["remaining"],
        "blocked_axes": [], "send_blocked_axes": [], "can_end": False, "job": None}
    assert candidate(waiting, w) == {"ref": w, "display": candidate(approval, w)["display"], "state": "pending",
                                     "evaluation": None, "score_kcal_mol": None, "iteration": None}
    model_step = waiting["iterations"][0]["steps"][0]
    assert (model_step["step"], model_step["state"], model_step["result_handle"], model_step["evaluation"]) == (
        "model", "completed", protein["handles"]["model"], "computed")
    assert waiting["counts"] == counts(started=1, human_decided=1, units_charged=1)

    # The mutant docking ran: W scored by iteration 1 (two charged steps), the next iteration selects.
    final = protein["records"]["final"]
    score = first_mode(run, protein["handles"]["dock"])
    assert candidate(final, w) == {"ref": w, "display": candidate(approval, w)["display"], "state": "scored"
                                   if score is not None else "null_result", "evaluation": "computed",
                                   "score_kcal_mol": score, "iteration": 1}
    assert [step["step"] for step in final["iterations"][0]["steps"]] == ["model", "dock"]
    assert final["counts"] == counts(started=1, done=1, human_decided=1, units_charged=2)
    assert (final["current"]["iteration"], final["current"]["action"]) == (2, "select")
    assert final["current"]["needs"]["expensive_units"] == 2 and final["current"]["needs"]["wall_clock_s"] == 420
    assert candidate(final, other)["state"] == "pending"


# ---------------------------------------------------------------- reads write nothing, read the log once, replay


def test_reads_write_nothing_and_read_the_event_log_once_per_request(ligand, tmp_path, monkeypatch):
    root, client = _clone(tmp_path, monkeypatch, {RID: ligand["logs"]["final"]})
    run = api_module._run(RID)
    before = (root / RID / "events.jsonl").read_bytes()
    reads = {"n": 0}
    original = run.events.read

    def counting():
        reads["n"] += 1
        return original()

    monkeypatch.setattr(run.events, "read", counting)
    for path in (f"/runs/{RID}/jev_loops/{LOOP_L}", f"/runs/{RID}/jev_loops"):
        reads["n"] = 0
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert reads["n"] == 1, (path, reads["n"])
    assert (root / RID / "events.jsonl").read_bytes() == before


def test_events_only_reopen_gives_the_same_records_without_any_engine(ligand, protein, tmp_path, monkeypatch):
    def no_engine(*args, **kwargs):   # fault injection: an engine, pin lookup or job start in a read fails the test
        raise AssertionError("a loop read must not need an engine")

    for module, names in ((docking_bundle, ("capability", "require_ready", "submission")),
                          (mutation_model_bundle, ("capability", "require_ready", "admission", "selection"))):
        for name in names:
            monkeypatch.setattr(module, name, no_engine)
    for name in ("submit", "start", "retry", "request_cancel"):
        monkeypatch.setattr(JobQueue, name, no_engine)
    _root, client = _clone(tmp_path, monkeypatch, {RID: ligand["logs"]["final"], PRID: protein["logs"]["final"]})
    for rid, loop_id, record in ((RID, LOOP_L, ligand["records"]["final"]),
                                 (PRID, LOOP_P, protein["records"]["final"])):
        response = client.get(f"/runs/{rid}/jev_loops/{loop_id}")
        assert response.status_code == 200, response.text
        assert response.json() == record


def test_protein_loop_reads_keep_their_bytes_when_the_m20_module_hash_changes(protein, tmp_path, monkeypatch):
    """M26 spec 9 (T1 preflight (k)): a loop record comes from its created-event pins, never the current ones, so
    after ``mutation_candidates.py`` changes (the M26 upgrade) the in-progress protein loop and the same loop once
    ended (run cancel) read the same bytes; only the compute press is refused (test_jev_loops_compute)."""
    _root, client = _clone(tmp_path, monkeypatch, {PRID: protein["logs"]["final"]})
    real = mutation_model_bundle.require_ready()
    changed = {**real, "dependency_sha256": {**real["dependency_sha256"], "mw/mutation_candidates.py": "d" * 64}}

    def reads():
        answers = [client.get(f"/runs/{PRID}/jev_loops/{LOOP_P}"), client.get(f"/runs/{PRID}/jev_loops")]
        assert all(answer.status_code == 200 for answer in answers), [answer.text for answer in answers]
        return [answer.content for answer in answers]

    in_progress = reads()
    assert json.loads(in_progress[0]) == protein["records"]["final"]
    with monkeypatch.context() as patch:   # fault injection: another mutation_candidates.py SHA-256
        patch.setattr(mutation_model_bundle, "require_ready", lambda: changed)
        assert reads() == in_progress
    api_module._run(PRID).cancel()
    ended = reads()
    assert json.loads(ended[0])["status"] == "ended"
    with monkeypatch.context() as patch:
        patch.setattr(mutation_model_bundle, "require_ready", lambda: changed)
        assert reads() == ended


# ---------------------------------------------------------------- not found, other runs, cancel, corrupt, size


def test_unknown_loops_other_runs_and_unknown_queries(ligand, tmp_path, monkeypatch):
    logs = {RID: ligand["logs"]["final"], **_template_logs(ligand)}
    root, client = _clone(tmp_path, monkeypatch, logs)
    before = {rid: (root / rid / "events.jsonl").read_bytes() for rid in logs}
    for rid, loop_id in ((RID, OTHER_LOOP), (DRY_RID, LOOP_L), (RID, "not-a-uuid"), (RID, LOOP_L.upper())):
        response = client.get(f"/runs/{rid}/jev_loops/{loop_id}")
        assert response.status_code == 404, response.text
        assert response.json()["detail"]["reason_code"] == "loop_not_found"
    assert client.get(f"/runs/{DRY_RID}/jev_loops").json() == []
    for path in (f"/runs/{RID}/jev_loops?x=1", f"/runs/{RID}/jev_loops/{LOOP_L}?branch=ligand"):
        assert client.get(path).status_code == 422
    assert client.get("/runs/run_missing_m25/jev_loops").status_code == 404
    assert {rid: (root / rid / "events.jsonl").read_bytes() for rid in logs} == before


def test_a_run_cancel_ends_every_unended_loop_as_run_cancelled(ligand, tmp_path, monkeypatch):
    _root, client = _clone(tmp_path, monkeypatch, {RID: ligand["logs"]["final"]})
    api_module._run(RID).cancel()
    record = client.get(f"/runs/{RID}/jev_loops/{LOOP_L}").json()
    assert (record["status"], record["end_reason"], record["result_handle"]) == ("ended", "run_cancelled", None)
    assert record["current"]["action"] == "none" and record["current"]["can_end"] is False
    assert record["limitations"][-1] == L.LJ8   # ended with unavailable candidates left
    assert client.get(f"/runs/{RID}/jev_loops").json()[0]["end_reason"] == "run_cancelled"


def test_an_event_order_the_routes_never_write_is_a_fixed_500(ligand, tmp_path, monkeypatch):
    raw = ligand["logs"]["queued"]
    _root, client = _clone(tmp_path, monkeypatch, {RID: raw})
    run = api_module._run(RID)
    # LABELLED SYNTHETIC: an approval for iteration 3 while iteration 1 runs (no route writes this order).
    approve(run, LOOP_L, 3, "ligand_dock", ligand["refs"][3], ligand["keys"][ligand["refs"][3]]["ligand_dock"])
    for path in (f"/runs/{RID}/jev_loops/{LOOP_L}", f"/runs/{RID}/jev_loops"):
        response = client.get(path)
        assert response.status_code == 500, response.text
        assert response.json()["detail"] == {"error": "internal_error",
                                             "message": api_module.JEV_LOOP_INTERNAL_MESSAGE}
        assert LOOP_L not in response.text and ligand["refs"][3] not in response.text


def test_reading_a_padded_multi_megabyte_log_is_quick_and_unchanged(ligand, tmp_path, monkeypatch):
    raw = ligand["logs"]["final"]
    lines = raw.decode().splitlines()
    seq = len(lines)
    padded = [raw]
    for n in range(80):   # LABELLED SYNTHETIC padding objects, ~64 KiB each (M25 T1 (e) method)
        content = {"schema": "synthetic_padding@1", "label": "SYNTHETIC M25 T3 padding, not a result", "n": n,
                   "blob": base64.b64encode(os.urandom(48 * 1024)).decode("ascii")}
        body = canonical_json(content)
        handle = f"obj://{RID}/synthetic_padding/{object_sha('synthetic_padding', 'synthetic_padding@1', body)}"
        seq += 1
        padded.append(json.dumps({"seq": seq, "ts": time.time(), "type": "object_created", "handle": handle,
                                  "kind": "synthetic_padding", "schema": "synthetic_padding@1", "fmt": "json",
                                  "payload_b64": base64.b64encode(body).decode(), "summary": {}, "produced_by": None,
                                  "null_result": False}, sort_keys=True).encode() + b"\n")
    raw = b"".join(padded)
    assert len(raw) > 5 * 1024 * 1024
    _root, client = _clone(tmp_path, monkeypatch, {RID: raw})
    assert client.get(f"/runs/{RID}/jev_loops/{LOOP_L}").status_code == 200   # warm: the reopen
    started = time.perf_counter()
    response = client.get(f"/runs/{RID}/jev_loops/{LOOP_L}")
    elapsed = time.perf_counter() - started
    assert response.status_code == 200 and response.json() == ligand["records"]["final"]
    assert elapsed < 3.0, elapsed


# ---------------------------------------------------------------- the record check on every read


def _tampered(record, scored, foreign_ref):
    """Copies of a valid record, each with one edit the record check must refuse."""
    edits = [
        lambda r: r.update(best=r["candidates"][scored]["ref"]),
        lambda r: r["candidates"][scored].update(score_kcal_mol=r["candidates"][scored]["score_kcal_mol"] - 1),
        lambda r: r["candidates"][scored].update(state="best"),
        lambda r: r["candidates"][scored].update(score_kcal_mol=None),
        lambda r: r["candidates"][0].update(ref=foreign_ref),
        lambda r: r["counts"].update(started=r["counts"]["started"] + 1),
        lambda r: r["counts"].update(reused_count=r["counts"]["reused_count"] + 1),
        lambda r: r["current"].update(action="rank"),
        lambda r: r["current"].update(blocked_axes=["usd"]),
        lambda r: r.update(limitations=r["limitations"][:-1]),
        lambda r: r.update(status="ended"),
        lambda r: r["iterations"][0].update(state="improved"),
        lambda r: r["iterations"][0]["steps"][0].update(state="done"),
        lambda r: r.update(effective_cap=r["effective_cap"] + 1),
        lambda r: r["pool"]["candidates"].reverse(),
    ]
    out = []
    for edit in edits:
        copied = copy.deepcopy(record)
        edit(copied)
        out.append(copied)
    return out


def test_validated_loop_record_refuses_tampered_records(ligand, protein, tmp_path, monkeypatch):
    for logs, rid, loop_id in (({RID: ligand["logs"]["final"]}, RID, LOOP_L),
                               ({PRID: protein["logs"]["final"]}, PRID, LOOP_P)):
        root, _client = _clone(tmp_path / rid, monkeypatch, logs)
        run = new_run(root, run_id=rid, dry_run=False)
        view = jev_loop_store.LoopReadView(run)
        created = jev_loop_store.created_payload(view.read(), loop_id)
        inputs = jev_loop_store.derive_inputs(view, created, budget=jev_loop_store.remaining_budget(
            run.budget_snapshot()), send_active=False)
        record = jev_loops.derive_loop(loop_id, view.read(), **inputs).record
        assert jev_loop_store.validated_loop_record(record, inputs) == record
        scored = next(index for index, row in enumerate(record["candidates"]) if row["state"] == "scored")
        tampered = _tampered(record, scored, "c_" + "f" * 16 if rid == RID else 9999)
        for item in tampered:
            with pytest.raises(jev_loops.LoopRecordInvalid):
                jev_loop_store.validated_loop_record(item, inputs)
        assert jev_loop_store.load_proposals(view, created) == {}


def test_a_stored_result_that_does_not_validate_is_not_computed(ligand, tmp_path, monkeypatch):
    _root, client = _clone(tmp_path, monkeypatch, {RID: ligand["logs"]["final"]})
    a = ligand["refs"][0]

    def invalid(run, handle):   # fault injection: A's stored result no longer validates
        raise docking_bundle.DockingEvidenceError("tampered")

    monkeypatch.setattr(docking_bundle, "validated_result", invalid)
    record = client.get(f"/runs/{RID}/jev_loops/{LOOP_L}").json()
    # Without a usable result A's same-key job (done outside the loop) is all that is left: unavailable, not reused.
    assert candidate(record, a)["state"] == "unavailable" and record["counts"]["reused_count"] == 0
    # C's charged step ended done but its result does not validate: failed (never scored, no score).
    c = ligand["refs"][2]
    assert candidate(record, c) | {"display": None} == {"ref": c, "display": None, "state": "failed",
                                                        "evaluation": "computed", "score_kcal_mol": None,
                                                        "iteration": 1}
