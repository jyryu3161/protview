"""M25 T6: the compute route ``POST /runs/{rid}/jev_loops/{loop_id}/compute``, the docking abandon route
``POST /runs/{rid}/jev_loops/{loop_id}/abandon_docking`` and the end route ``POST /runs/{rid}/jev_loops/{loop_id}/end``
with its summary ``jev_loop_result@1`` (spec .dryforge/spec.md 3.2, 3.3, 6.1-6.5, 7, 8.1, 8.2, 9.1-9.3, 11, 12).

Inputs are REAL product objects, built once per module, and every test gets an events-only copy served by the product
app (``SCIENCE_GATE`` is a ``jev_send_fixture.Fake``: MockTransport, inert sentinel credential, fixture replies):
* ligand world: real M17 jobs on the labelled synthetic small blocks (``fixtures/ligand_ga``), the public-derived
  parent SDF and the public prepared docking example receptor (not experimental validation); then, outside any loop
  and with the loop setup used below (small manual box, exhaustiveness 1), a real M22 GA (one generation of four new
  dockings), a real one-row M19 batch, a real standalone M18 job and a same-key M18 job cancelled before it started.
* protein world: public 1UBQ through the unmodified cheap tools (an M20 set at ILE44) and the labelled synthetic phenol
  SDF ("fresh": no expensive call yet), then one real M21 model of I44W submitted with a request written out by hand
  ("modelled": the first expensive-call approval resolved).
Jobs run through ``JobQueue`` with the pinned docking worker + ``qvina2`` and the M21 OpenMM / PDBFixer worker; a
missing engine FAILS, never skips. Engine values are never an oracle: scores are read from the stored results.
Expected values are written from the spec (closed names, their order and HTTP status, the approval payload, the needs
of spec 6.1 / 7, the states of 3.2 / 6.4); call keys are checked against a standalone ``POST /jobs`` of a request
written out by hand, which the queue answers with the loop's own job only when the keys are equal.

LABELLED fault injection, marked where used: a held run lock; a ``JobQueue.start`` that reports a held run owner (the
start lost the race to another request, so the approved job stays queued); ``Run._time_left`` reporting one second
left (a job that times out after its reservation); edited engine pins; a missing docking worker; an M18 / M21 job
admission refusal; a same-key job submitted between the locked read and the approval event; a synthetic
``jev_loop_ended`` event; a server stop right before the end event; stored summaries that are not their loop's;
engines, job lane and gate made to fail for the events-only replay.
"""
from __future__ import annotations

import ast
import json
import threading
import time
import uuid
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jev_send_fixture import Fake, new_send_id, reply
from ligand_job_fixture import import_file, new_ligand_run, run_job
from test_jev_loops_api import I44, PHENOL, UBQ
from test_ligand_ga_jobs import ACK, BLOCKS, BOX, FAST, GA, IDS, PARENT, REC, evaluated, ga_args, run_ga, summary

from mw import (
    docking_batch_inputs,
    docking_bundle,
    docking_inputs,
    jev_loop_store,
    jev_loops,
    mutation_model_bundle,
)
from mw import docking_constants as DC
from mw import jev_constants as J
from mw import jev_loop_constants as L
from mw import jev_loop_result as R
from mw import jev_sends as S
from mw import mutation_model_constants as MC
from mw.api import app as api_module
from mw.core.errors import FailureClass, ToolFailure
from mw.jobs.queue import JobQueue
from mw.runtime.guards import BudgetLimits
from mw.runtime.orchestrator import Run
from mw.workspace import new_run

MW = Path(__file__).resolve().parents[1] / "mw"
LRID, PRID = "run_m25_compute_ligand", "run_m25_compute_protein"
JSON_HEADERS = {"content-type": "application/json"}
SMALL_GA = {**GA, "population_size": 4, "generations": 1, "elite_count": 2, "max_new_dockings": 4}
PROTEIN_FAST = {"seed": 20261007, "exhaustiveness": 1, "num_modes": 2}
W, A, B, X = 17, 0, 3, 9        # positions in the ILE44 set's candidate list (17 = I44W, as in the M21 / M24 tests)
STATUS = {"unknown_field": 422, "loop_not_found": 404, "cancelled": 409, "loop_ended": 409, "send_in_progress": 409,
          "iteration_invalid": 409, "phase_invalid": 409, "iteration_cap_reached": 409, "proposal_invalid": 409,
          "proposal_late": 409, "candidate_invalid": 422, "candidate_unavailable": 409, "candidate_computed": 409,
          "capability_unavailable": 412, "budget_blocked": 429, "step_unavailable": 409, "job_running": 409,
          "docking_pending": 409}                                                  # spec 6.1 and 8.1, written out
LOOP_EVENTS = set(L.EVENT_TYPES)


# ---------------------------------------------------------------- standalone requests written out by hand (spec 6.1)


def hand_ligand_request(world: dict, candidate_id: str) -> dict:
    """A standalone M18 free docking of one M17 candidate, written from the M18 request shape (no loop builder)."""
    return {"receptor_handle": world["receptor"], "receptor_model_number": 1,
            "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
            "ligand": {"source": "candidate", "candidate_set_handle": world["set"], "candidate_id": candidate_id,
                       "parent_sdf_handle": world["parent"]},
            "mode": "free", "box": BOX, "parameters": FAST, "acknowledgement": ACK}


def hand_model_request(world: dict, index: int) -> dict:
    """A standalone M21 request of one mutation candidate (seed = the loop's docking seed, the M21 defaults)."""
    return {"candidate_set": world["set"], "candidate_index": index, "seed": PROTEIN_FAST["seed"],
            "contact_cutoff_A": 4.0, "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}


def hand_dock_request(world: dict, model: str) -> dict:
    """A standalone M18 free docking of the phenol SDF into the mutant side of one stored model."""
    return {"receptor_source": {"kind": "mutation_model", "mutation_model": model, "side": "mutant"},
            "ligand": {"source": "sdf", "sdf_handle": world["phenol"]}, "mode": "free",
            "box": {"source": "ligand_range", "margin_A": 8}, "parameters": PROTEIN_FAST, "acknowledgement": ACK}


# ---------------------------------------------------------------- the two worlds (built once)


def _ligand_world(root: Path) -> dict:
    run = new_ligand_run(root, LRID)
    world = {"rid": LRID}
    world["receptor"] = import_file(run, "receptor", "rec.pdb", REC)
    world["parent"] = import_file(run, "ligand_sdf", "parent.sdf", PARENT)
    blocks = import_file(run, "building_blocks_smiles", "blocks.smi", BLOCKS)
    inspected = run_job(run, "rdkit_inspect_v1", {"parent_sdf_handle": world["parent"], "block_handles": [blocks]})
    assert inspected["status"] == "done", inspected
    enumerated = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": inspected["output_handles"][0],
                                                     "site_atoms": [22], "use_fixed": True})
    assert enumerated["status"] == "done", enumerated
    world["set"] = enumerated["output_handles"][0]
    assert [row["id"] for row in run.store.load(world["set"])["candidates"]] == IDS
    run.update_limits(BudgetLimits(expensive_calls=40, wall_clock_s=30000), by="test")
    # Outside any loop, under the loop's setup: an M22 GA, an M19 one-row batch, an M18 job, a cancelled M18 job.
    ga_job = run_ga(run, ga_args({"receptor": world["receptor"], "parent": world["parent"],
                                  "candidate_set": world["set"]}, **SMALL_GA))
    assert ga_job["status"] == "done", ga_job
    ga_entries = evaluated(summary(run, ga_job)[1])
    world["ga"] = next(entry["candidate_id"] for entry in ga_entries
                       if entry["evaluation"] == "docked" and entry["result_handle"] is not None)
    rest = [cid for cid in IDS if cid not in {entry["candidate_id"] for entry in ga_entries}]
    assert len(rest) == 6, rest
    world["m19"], world["m18"], world["cancelled"], *world["free"] = rest
    queue = JobQueue(run)
    batch = queue.submit("qvina_batch_dock_v1", {
        "receptor_handle": world["receptor"], "receptor_model_number": 1,
        "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
        "candidate_set_handle": world["set"], "parent_sdf_handle": world["parent"], "candidate_ids": [world["m19"]],
        "include_parent": False, "mode": "free", "box": BOX, "parameters": FAST, "acknowledgement": ACK},
        timeout_s=1200)
    assert queue.start(batch["job_id"])["status"] == "done"
    single = queue.submit(DC.PROTOCOL, hand_ligand_request(world, world["m18"]), timeout_s=300)
    assert queue.start(single["job_id"])["status"] == "done"
    cancelled = queue.submit(DC.PROTOCOL, hand_ligand_request(world, world["cancelled"]), timeout_s=300)
    assert queue.request_cancel(cancelled["job_id"])["job"]["status"] == "cancelled"
    world["log"] = (root / LRID / "events.jsonl").read_bytes()
    return world


def _protein_world(root: Path) -> dict:
    run = new_run(root, run_id=PRID, dry_run=False)
    loaded = run.call("load_structure", {"source": str(UBQ), "model_index": 0}).handle
    prepared = run.call("prepare_structure", {"structure": loaded}).handle
    world = {"rid": PRID}
    world["set"] = run.call("generate_mutation_candidates", {
        "structure": prepared, "sources": {"pocket": None, "ligand_shell": None, "residues": [I44]}}).handle
    world["phenol"] = import_file(run, "ligand_sdf", "phenol.sdf", PHENOL)
    world["refs"] = [row["index"] for row in run.store.load(world["set"])["candidates"]]
    world["fresh"] = (root / PRID / "events.jsonl").read_bytes()          # no expensive call yet
    model = run_job(run, MC.PROTOCOL, hand_model_request(world, world["refs"][W]), timeout_s=120)
    assert model["status"] == "done", model
    world["model"], world["model_key"] = model["output_handles"][0], model["call_key"]
    world["modelled"] = (root / PRID / "events.jsonl").read_bytes()
    return world


@pytest.fixture(scope="module")
def ligand(tmp_path_factory):
    return _ligand_world(tmp_path_factory.mktemp("m25_compute_ligand"))


@pytest.fixture(scope="module")
def protein(tmp_path_factory):
    return _protein_world(tmp_path_factory.mktemp("m25_compute_protein"))


@pytest.fixture(autouse=True)
def no_active_sends():
    S.ACTIVE_SENDS.clear()
    yield
    S.ACTIVE_SENDS.clear()


class Served:
    """One events-only copy of a world's run served by the product app."""

    def __init__(self, rid: str, root: Path) -> None:
        self.rid, self.root = rid, root
        self.client = TestClient(api_module.app, base_url="http://127.0.0.1")
        self.run = api_module._run(rid)          # reopened (job reconcile) before any baseline is taken

    def log(self) -> bytes:
        return (self.root / self.rid / "events.jsonl").read_bytes()

    def events(self, kind: str | None = None) -> list[dict]:
        return [event for event in self.run.events.read() if kind is None or event["type"] == kind]

    def create(self, body: dict) -> str:
        response = self.client.post(f"/runs/{self.rid}/jev_loops", content=json.dumps(body).encode(),
                                    headers=JSON_HEADERS)
        assert response.status_code == 200, response.text
        return response.json()["loop_id"]

    def post(self, loop_id: str, action: str, body: dict | None = None, *, raw: bytes | None = None,
             headers: dict | None = JSON_HEADERS, query: str = ""):
        content = raw if raw is not None else json.dumps(body).encode()
        return self.client.post(f"/runs/{self.rid}/jev_loops/{loop_id}/{action}{query}", content=content,
                                headers=headers or {})

    def compute(self, loop_id: str, **body):
        return self.post(loop_id, "compute", body)

    def abandon(self, loop_id: str, **body):
        return self.post(loop_id, "abandon_docking", body)

    def end(self, loop_id: str, **body):
        return self.post(loop_id, "end", body)

    def record(self, loop_id: str) -> dict:
        response = self.client.get(f"/runs/{self.rid}/jev_loops/{loop_id}")
        assert response.status_code == 200, response.text
        return response.json()

    def used(self) -> int:
        return self.run.budget_snapshot()["expensive_calls"]["used"]

    def limit(self, *, units: int, wall: float = 30000) -> None:
        self.run.update_limits(BudgetLimits(expensive_calls=units, wall_clock_s=wall), by="test")

    def submit_job(self, protocol: str, args: dict, timeout_s: float) -> dict:
        response = self.client.post(f"/runs/{self.rid}/jobs", content=json.dumps({
            "protocol_id": protocol, "args": args, "timeout_s": timeout_s}).encode(), headers=JSON_HEADERS)
        assert response.status_code == 200, response.text
        return response.json()

    def send(self, fake: Fake, projection: str) -> dict:
        """One approved M24 send of a loop projection (``POST /jev/sends``) with ``fake`` as the science gate."""
        api_module.SCIENCE_GATE = fake.gate
        body = {"send_id": new_send_id(), "projection": projection,
                "body_sha256": self.run.store.load(projection)["body_sha256"], "confirm": J.CONFIRM}
        response = self.client.post(f"/runs/{self.rid}/jev/sends", content=json.dumps(body).encode(),
                                    headers=JSON_HEADERS)
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture
def serve(tmp_path, monkeypatch):
    def open_copy(world: dict, raw: bytes, name: str = "runs") -> Served:
        root = tmp_path / name
        (root / world["rid"]).mkdir(parents=True)
        (root / world["rid"] / "events.jsonl").write_bytes(raw)
        monkeypatch.setattr(api_module, "RUNS_DIR", root)
        monkeypatch.setattr(api_module, "SCIENCE_GATE", Fake().gate)
        api_module.RUNS.clear()
        return Served(world["rid"], root)
    yield open_copy
    api_module.RUNS.clear()


def ligand_loop(world: dict, pool: list, *, cap: int = 5, goal: str = "exploit") -> dict:
    return {"loop_id": str(uuid.uuid4()), "branch": "ligand",
            "pool": {"source": world["set"], "candidates": pool, "filter": None}, "goal": goal, "loop_seed": 7,
            "iteration_cap": cap,
            "setup": {"receptor_handle": world["receptor"], "receptor_model_number": 1,
                      "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
                      "box": BOX, "parameters": FAST, "acknowledgement": ACK, "parent_sdf_handle": world["parent"]}}


def protein_loop(world: dict, positions: tuple, *, cap: int = 8, goal: str = "exploit") -> dict:
    return {"loop_id": str(uuid.uuid4()), "branch": "protein",
            "pool": {"source": world["set"], "candidates": [world["refs"][at] for at in positions], "filter": None},
            "goal": goal, "loop_seed": 11, "iteration_cap": cap,
            "setup": {"ligand": {"source": "sdf", "sdf_handle": world["phenol"]},
                      "box": {"source": "ligand_range", "margin_A": 8}, "parameters": PROTEIN_FAST,
                      "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7", "acknowledgement": ACK}}


def refused(response, reason: str, **detail) -> dict:
    assert response.status_code == STATUS[reason], response.text
    got = response.json()["detail"]
    assert got["reason_code"] == reason, got
    for key, value in detail.items():
        assert got[key] == value, got
    return got


def candidate(record: dict, ref) -> dict:
    return next(row for row in record["candidates"] if row["ref"] == ref)


def counts(**over) -> dict:
    return {**dict.fromkeys(jev_loops.COUNT_KEYS, 0), **over}


def first_mode(run: Run, handle: str):
    modes = run.store.load(handle)["modes"]
    return modes[0]["score_kcal_mol"] if modes else None


def scored_state(run: Run, handle: str) -> str:
    return "scored" if run.store.load(handle)["modes"] else "null_result"


def approval(**fields) -> dict:
    return {key: value for key, value in fields.items()} | {"approved_by": "human"}


def payload(event: dict) -> dict:
    return {key: value for key, value in event.items() if key not in ("seq", "ts", "type")}


def m18_key(request: dict) -> str:
    """The call key a standalone M18 submission of ``request`` gets (normalized arguments + current pins)."""
    return docking_bundle.call_key(docking_inputs.validate_arguments(request), docking_bundle.require_ready())


class held_start:
    """LABELLED fault injection: ``JobQueue.start`` reports a held run owner (another request took the owner between
    the compute route's release and its start), so the approved job stays queued and nothing runs."""

    def __init__(self, monkeypatch) -> None:
        self.patch = monkeypatch.context()

    def __enter__(self):
        patch = self.patch.__enter__()

        def held(queue, job_id, **options):
            raise ToolFailure(FailureClass.transient, "run execution owner is busy", detail={"busy": True})

        patch.setattr(JobQueue, "start", held)
        return self

    def __exit__(self, *exc) -> None:
        self.patch.__exit__(*exc)


class one_second_left:
    """LABELLED fault injection: the run reports one second of activity time left, so a job that reserved its unit
    times out right after its process started (a charged failure, spec 6.4)."""

    def __init__(self, monkeypatch) -> None:
        self.patch = monkeypatch.context()

    def __enter__(self):
        self.patch.__enter__().setattr(Run, "_time_left", lambda run: 1.0)
        return self

    def __exit__(self, *exc) -> None:
        self.patch.__exit__(*exc)


def unchanged(served: Served, before: bytes) -> None:
    assert served.log() == before


def stored_score(served: Served, request: dict):
    """The first-mode score of the stored M18 result a standalone submission of ``request`` would reuse: read from the
    run's publication index and the stored object (not through the loop code)."""
    handle = docking_batch_inputs.published_m18_results(served.events())[m18_key(request)]
    return first_mode(served.run, handle)


def end_loop(served: Served, loop_id: str, reason: str) -> tuple[dict, dict]:
    """``POST .../end`` (spec 8.1): the summary object first, then ``jev_loop_ended`` naming it; the ended record shows
    the summary's rows and LJ sentences; every write route then answers ``loop_ended``. Returns (record, summary)."""
    before = len(served.events())
    response = served.end(loop_id)
    assert response.status_code == 200, response.text
    new = served.events()[before:]
    assert [(event["type"], event.get("kind")) for event in new] == [("object_created", L.RESULT_KIND),
                                                                    (L.EVENT_ENDED, None)]
    handle = new[0]["handle"]
    assert (new[0]["schema"], payload(new[1])) == (L.RESULT_SCHEMA, {"loop_id": loop_id, "end_reason": reason,
                                                                     "result_handle": handle})
    record = response.json()
    assert (record["status"], record["end_reason"], record["result_handle"]) == ("ended", reason, handle)
    assert record["current"]["action"] == "none" and record == served.record(loop_id)
    content = served.run.store.load(handle)
    assert R.validated_loop_result(content) == content and content["end_reason"] == reason
    assert (content["candidates"], content["counts"], content["pool"]) == (record["candidates"], record["counts"],
                                                                         record["pool"])
    assert record["limitations"] == [L.STATEMENTS[name] for name in content["limitations"]]
    log = served.log()
    refused(served.end(loop_id), "loop_ended")
    refused(served.abandon(loop_id, iteration=1), "loop_ended")
    refused(served.compute(loop_id, iteration=1, candidate=record["candidates"][0]["ref"]), "loop_ended")
    unchanged(served, log)
    return record, content


# ---------------------------------------------------------------- ligand: one human-decided iteration end to end


def test_a_human_compute_writes_one_approval_then_runs_the_standalone_m18_job(ligand, serve):
    served = serve(ligand, ligand["log"])
    f1 = ligand["free"][0]
    loop_id = served.create(ligand_loop(ligand, [f1, ligand["ga"], ligand["m19"], ligand["m18"],
                                                 ligand["cancelled"]]))
    used, before = served.used(), len(served.events())
    response = served.compute(loop_id, iteration=1, candidate=f1)
    assert response.status_code == 200, response.text
    record = response.json()
    new = served.events()[before:]
    approvals = [event for event in new if event["type"] == L.EVENT_COMPUTE_APPROVED]
    submitted = [event for event in new if event["type"] == "job_submitted"]
    assert len(approvals) == 1 and len(submitted) == 1
    key = m18_key(hand_ligand_request(ligand, f1))            # the standalone M18 key of the hand-written request
    assert payload(approvals[0]) == approval(loop_id=loop_id, iteration=1, step="ligand_dock", candidate_ref=f1,
                                             decided_by="human", proposal_handle=None, call_key=key, units=1)
    job = JobQueue(served.run).get(submitted[0]["job"]["job_id"])
    assert (job["protocol_id"], job["call_key"], job["timeout_s"], job["status"]) == (DC.PROTOCOL, key, 300, "done")
    assert job["parameters"] == docking_inputs.validate_arguments(hand_ligand_request(ligand, f1))
    reserved = [event for event in new if event["type"] == "budget_reserved"
                and event.get("root_call_id") == job["job_id"]]
    assert approvals[0]["seq"] < submitted[0]["seq"] < reserved[0]["seq"]       # the approval comes first
    assert served.used() == used + 1
    assert not {event["type"] for event in new} & {"egress", "tool_called", J.EVENT_APPROVED, J.EVENT_DISPATCH}
    handle = job["output_handles"][0]
    state, score = scored_state(served.run, handle), first_mode(served.run, handle)
    assert candidate(record, f1) == {"ref": f1, "display": candidate(record, f1)["display"], "state": state,
                                     "evaluation": "computed", "score_kcal_mol": score, "iteration": 1}
    assert record["iterations"] == [{
        "index": 1, "phase": "done", "decided_by": "human", "candidate_ref": f1, "proposal_handle": None,
        "list_position": None, "list_size": None,
        "approvals": [{"step": "ligand_dock", "candidate_ref": f1, "decided_by": "human", "proposal_handle": None,
                       "call_key": key}],
        "sends": [],
        "steps": [{"step": "ligand_dock", "candidate_ref": f1, "job_id": job["job_id"], "call_key": key,
                   "result_handle": handle, "state": "completed", "reason_code": None, "evaluation": "computed"}],
        "state": state, "score_kcal_mol": score}]
    assert record["counts"] == counts(started=1, done=1, human_decided=1, units_charged=1, reused_count=3)
    assert record == served.record(loop_id)
    # A standalone POST /jobs of the hand-written request is answered with the loop's job: the same call key.
    jobs = len(served.events("job_submitted"))
    again = served.submit_job(DC.PROTOCOL, hand_ligand_request(ligand, f1), 300)
    assert again["job_id"] == job["job_id"] and len(served.events("job_submitted")) == jobs
    # The same press after the iteration ended: the current iteration is now 2.
    log = served.log()
    refused(served.compute(loop_id, iteration=1, candidate=f1), "iteration_invalid")
    unchanged(served, log)
    # Nothing is left to compute (F1 computed, three stored results, one unavailable): the person ends the loop.
    assert served.record(loop_id)["exhausted_reason"] == "pool_exhausted"
    record, content = end_loop(served, loop_id, "pool_exhausted")
    assert content["iterations"] == [{
        "index": 1, "decided_by": "human", "candidate_ref": f1, "proposal_handle": None, "send_id": None,
        "list_position": None, "list_size": None,
        "approvals": [{"step": "ligand_dock", "candidate_ref": f1, "decided_by": "human", "proposal_handle": None,
                       "call_key": key}],
        "steps": [{"step": "ligand_dock", "candidate_ref": f1, "job_id": job["job_id"], "call_key": key,
                   "result_handle": handle, "state": "completed", "reason_code": None}],
        "state": state, "score_kcal_mol": score}]
    for ref in (ligand["ga"], ligand["m19"], ligand["m18"]):     # each score is its stored result's first mode
        row = candidate(content, ref)
        assert (row["evaluation"], row["score_kcal_mol"]) == ("reused", stored_score(
            served, hand_ligand_request(ligand, ref)))
    assert candidate(content, f1)["score_kcal_mol"] == score and content["unfinished"] == []
    assert content["limitations"] == ["LJ1", "LJ2", "LJ3", "LJ4", "LJ6", "LJ8"]   # one candidate left unavailable
    assert (content["setup"], content["pins"]) == (record["setup"], {"m18": docking_bundle.require_ready()})
    served.create(ligand_loop(ligand, ligand["free"][1:]))       # an ended loop never reopens; a new one may start


def test_stored_m18_m19_and_m22_results_are_computed_and_cannot_be_chosen(ligand, serve):
    served = serve(ligand, ligand["log"])
    pool = [ligand["ga"], ligand["m19"], ligand["m18"], ligand["cancelled"], ligand["free"][0]]
    loop_id = served.create(ligand_loop(ligand, pool))
    record = served.record(loop_id)
    for ref in (ligand["ga"], ligand["m19"], ligand["m18"]):       # spec 3.2 priority 2, whoever produced it
        row = candidate(record, ref)
        assert (row["evaluation"], row["iteration"]) == ("reused", None)
        assert row["state"] in ("scored", "null_result") and row["state"] != "pending"
    assert candidate(record, ligand["cancelled"])["state"] == "unavailable"      # priority 3
    assert record["counts"] == counts(reused_count=3)
    used, log = served.used(), served.log()
    for ref in (ligand["ga"], ligand["m19"], ligand["m18"]):
        refused(served.compute(loop_id, iteration=1, candidate=ref), "candidate_computed")
    refused(served.compute(loop_id, iteration=1, candidate=ligand["cancelled"]), "candidate_unavailable")
    unchanged(served, log)
    assert served.used() == used


# ---------------------------------------------------------------- ligand: two presses, cancels before start


def test_two_presses_make_one_step_and_a_job_cancelled_before_start_is_unavailable(ligand, serve, monkeypatch):
    served = serve(ligand, ligand["log"])
    f1, f2, f3 = ligand["free"]
    loop_id = served.create(ligand_loop(ligand, [f1, f2, f3], cap=3, goal="explore"))
    used = served.used()
    # F1: approved, its start lost the race (held owner), then cancelled before any process: unavailable.
    with held_start(monkeypatch):
        response = served.compute(loop_id, iteration=1, candidate=f1)
    assert response.status_code == 503 and response.json()["detail"] == {"busy": True}, response.text
    record = served.record(loop_id)
    job_f1 = record["current"]["job"]["job_id"]
    assert record["current"] == {
        "iteration": 1, "phase": "running", "step": "ligand_dock", "action": "wait_job",
        "needs": {"expensive_units": 0, "wall_clock_s": 0, "external_tokens": None, "usd": None, "sends": 0},
        "remaining": record["current"]["remaining"], "blocked_axes": [], "send_blocked_axes": [], "can_end": False,
        "job": {"job_id": job_f1, "step": "ligand_dock", "status": "queued", "start_blocked": None}}
    log = served.log()
    refused(served.compute(loop_id, iteration=1, candidate=f2), "phase_invalid")   # cancel first (spec 6.1)
    unchanged(served, log)
    cancel = served.client.post(f"/runs/{LRID}/jobs/{job_f1}/cancel")
    assert cancel.status_code == 200 and cancel.json()["job"]["status"] == "cancelled"
    record = served.record(loop_id)
    assert candidate(record, f1)["state"] == "unavailable" and candidate(record, f1)["iteration"] is None
    assert (record["iterations"][0]["state"], record["iterations"][0]["phase"]) == ("unavailable", "awaiting_selection")
    assert record["iterations"][0]["steps"][0]["state"] == "unavailable"
    assert record["counts"] == counts() and record["current"]["action"] == "select"
    # F1 is left out of the next projection's wire and alias table.
    projection = served.run.store.load(served.run.call(L.TOOL, {"loop_id": loop_id, "iteration": 1}).handle)
    assert sorted(item["ref"] for item in projection["selection"]) == sorted([f2, f3])
    assert len(projection["wire"]["candidates"]) == 2
    log = served.log()
    refused(served.compute(loop_id, iteration=1, candidate=f1), "candidate_unavailable")
    unchanged(served, log)
    # F2: approved (the iteration's second approval) with a held start; the second press starts the same job.
    with held_start(monkeypatch):
        assert served.compute(loop_id, iteration=1, candidate=f2).status_code == 503
    approvals, jobs = len(served.events(L.EVENT_COMPUTE_APPROVED)), len(served.events("job_submitted"))
    with served.run._owner():   # fault injection: a held run lock -> the press would start a job -> busy, no write
        busy = served.compute(loop_id, iteration=1, candidate=f2)
    assert busy.status_code == 503 and busy.json()["detail"]["error"] == "busy", busy.text
    response = served.compute(loop_id, iteration=1, candidate=f2)
    assert response.status_code == 200, response.text
    assert len(served.events(L.EVENT_COMPUTE_APPROVED)) == approvals and len(served.events("job_submitted")) == jobs
    record = response.json()
    first = record["iterations"][0]
    assert [item["candidate_ref"] for item in first["approvals"]] == [f1, f2]
    assert [(step["candidate_ref"], step["state"]) for step in first["steps"]] == [(f1, "unavailable"),
                                                                                 (f2, "completed")]
    handle = first["steps"][1]["result_handle"]
    assert (first["state"], candidate(record, f2)["state"]) == (scored_state(served.run, handle),) * 2
    assert served.used() == used + 1
    # F3: approved for iteration 2, cancelled before start -> unavailable; it does not hold back pool_exhausted.
    with held_start(monkeypatch):
        assert served.compute(loop_id, iteration=2, candidate=f3).status_code == 503
    job_f3 = served.record(loop_id)["current"]["job"]["job_id"]
    assert served.client.post(f"/runs/{LRID}/jobs/{job_f3}/cancel").json()["job"]["status"] == "cancelled"
    record = served.record(loop_id)
    assert [candidate(record, ref)["state"] for ref in (f1, f3)] == ["unavailable", "unavailable"]
    assert record["iterations"][1]["state"] == "unavailable"
    assert (record["status"], record["exhausted_reason"], record["current"]["action"]) == (
        "active", "pool_exhausted", "end")
    assert record["counts"] == counts(started=1, done=1, human_decided=1, units_charged=1)
    assert served.used() == used + 1
    record, content = end_loop(served, loop_id, "pool_exhausted")
    assert content["unfinished"] == [{"iteration": 2, "candidate_ref": f3}]      # approved, never started
    assert [item["candidate_ref"] for item in content["iterations"][0]["approvals"]] == [f1, f2]
    assert [(row["index"], row["candidate_ref"], row["state"]) for row in content["iterations"]] == [
        (1, f2, scored_state(served.run, handle)), (2, f3, "unavailable")]
    assert content["counts"] == counts(started=1, done=1, human_decided=1, units_charged=1)
    assert content["limitations"][-1] == "LJ8"


# ---------------------------------------------------------------- ligand: the refusals, their order, no write


def test_compute_refusals_follow_the_spec_order_and_write_nothing(ligand, serve, tmp_path, monkeypatch):
    served = serve(ligand, ligand["log"])
    f1, f2 = ligand["free"][:2]
    loop_id = served.create(ligand_loop(ligand, [f1, f2, ligand["m18"], ligand["cancelled"]]))
    log, used, jobs = served.log(), served.used(), len(served.events("job_submitted"))
    # shape (422 unknown_field) before the loop lookup
    for body in ({"iteration": 1, "candidate": f1, "extra": 1}, {"candidate": f1}, {"iteration": "1", "candidate": f1},
                 {"iteration": 1, "candidate": f1, "proposal": "x"}, {"iteration": 1, "candidate": None},
                 {"iteration": True, "candidate": f1}):
        refused(served.post(str(uuid.uuid4()), "compute", body), "unknown_field")
    refused(served.compute(str(uuid.uuid4()), iteration=1, candidate=f1), "loop_not_found")
    S.begin_send(LRID, "another-send")
    try:
        refused(served.compute(str(uuid.uuid4()), iteration=1, candidate=f1), "loop_not_found")
        refused(served.compute(loop_id, iteration=2, candidate=f1), "send_in_progress")
    finally:
        S.end_send(LRID, "another-send")
    refused(served.compute(loop_id, iteration=2, candidate="c_0000000000000000"), "iteration_invalid")
    refused(served.compute(loop_id, iteration=1), "phase_invalid")                 # no docking step in a ligand loop
    refused(served.abandon(loop_id, iteration=1), "phase_invalid")
    refused(served.compute(loop_id, iteration=1, proposal=f"obj://{LRID}/{L.CHOICE_KIND}/" + "0" * 64),
            "proposal_invalid")
    refused(served.compute(loop_id, iteration=1, proposal=7), "proposal_invalid")
    refused(served.compute(loop_id, iteration=1, candidate="c_0000000000000000"), "candidate_invalid")
    refused(served.compute(loop_id, iteration=1, candidate=3), "candidate_invalid")
    refused(served.compute(loop_id, iteration=1, candidate=ligand["cancelled"]), "candidate_unavailable")
    refused(served.compute(loop_id, iteration=1, candidate=ligand["m18"]), "candidate_computed")
    unchanged(served, log)
    # capability (a missing docking worker) after the candidate checks
    with monkeypatch.context() as patch:
        patch.setattr(docking_bundle, "WORKER_PYTHON", tmp_path / "missing/python")   # fault injection
        docking_bundle._HANDSHAKE_CACHE.clear()
        refused(served.compute(loop_id, iteration=1, candidate="c_0000000000000000"), "candidate_invalid")
        refused(served.compute(loop_id, iteration=1, candidate=ligand["m18"]), "candidate_computed")
        got = refused(served.compute(loop_id, iteration=1, candidate=f1), "capability_unavailable")
        assert got["capability"] == {"reason_code": "worker_missing",
                                     "reason": docking_bundle.REASONS["worker_missing"]}
        served.limit(units=used)          # short budget too: capability still comes first
        log = served.log()
        refused(served.compute(loop_id, iteration=1, candidate=f1), "capability_unavailable")
    docking_bundle._HANDSHAKE_CACHE.clear()
    got = refused(served.compute(loop_id, iteration=1, candidate=f1), "budget_blocked")
    assert got["blocked_axes"] == ["expensive_units"]
    unchanged(served, log)
    # a loop end and a run cancel come first of all (after the lookup)
    served.limit(units=40)
    assert served.end(loop_id).json()["end_reason"] == "ended_by_user"
    S.begin_send(LRID, "another-send")
    try:
        refused(served.compute(loop_id, iteration=1, candidate=f1), "loop_ended")
        refused(served.abandon(loop_id, iteration=1), "loop_ended")
        served.run.cancel()
        refused(served.compute(loop_id, iteration=1, candidate=f1), "cancelled")
        refused(served.abandon(loop_id, iteration=1), "cancelled")
    finally:
        S.end_send(LRID, "another-send")
    assert not served.events(L.EVENT_COMPUTE_APPROVED) and len(served.events("job_submitted")) == jobs
    assert served.used() == used


def test_budget_blocked_names_each_short_axis_and_charges_nothing(ligand, serve):
    served = serve(ligand, ligand["log"])
    f1 = ligand["free"][0]
    loop_id = served.create(ligand_loop(ligand, [f1, ligand["free"][1]]))
    used = served.used()
    wall = served.run.budget_snapshot()["wall_clock_s"]["used"]
    for units, wall_limit, axes in ((used, 30000, ["expensive_units"]), (40, wall + 100, ["wall_clock_s"]),
                                    (used, wall + 100, ["expensive_units", "wall_clock_s"])):
        served.limit(units=units, wall=wall_limit)
        log = served.log()
        got = refused(served.compute(loop_id, iteration=1, candidate=f1), "budget_blocked")
        assert got["blocked_axes"] == axes and got["needs"] == {"expensive_units": 1, "wall_clock_s": 300}
        unchanged(served, log)
        assert served.used() == used
        assert served.record(loop_id)["current"]["blocked_axes"] == axes
    assert not served.events(L.EVENT_COMPUTE_APPROVED)


def test_changed_pins_and_job_admission_refusals_write_nothing(ligand, serve, monkeypatch):
    served = serve(ligand, ligand["log"])
    f1 = ligand["free"][0]
    loop_id = served.create(ligand_loop(ligand, [f1, ligand["free"][1]]))
    log = served.log()
    real = docking_bundle.require_ready()
    with monkeypatch.context() as patch:   # fault injection: the M18 worker changed after the loop was created
        patch.setattr(docking_bundle, "require_ready", lambda: {**real, "worker_sha256": "f" * 64})
        got = refused(served.compute(loop_id, iteration=1, candidate=f1), "capability_unavailable")
    assert got["capability"]["reason_code"] == "missing_configuration" and got["capability"]["reason"]
    with monkeypatch.context() as patch:   # fault injection: the M18 submission admission refuses this request
        def refuse(run, args):
            raise ToolFailure(FailureClass.input_invalid, "parent SDF SHA-256 differs",
                              detail={"reason_code": "parent_mismatch"})
        patch.setattr(docking_bundle, "submission", refuse)
        response = served.compute(loop_id, iteration=1, candidate=f1)
    assert response.status_code == 422, response.text
    assert (response.json()["error"], response.json()["detail"]) == ("input_invalid",
                                                                      {"reason_code": "parent_mismatch"})
    unchanged(served, log)
    assert served.record(loop_id)["candidates"][0]["state"] == "pending"


def test_a_same_key_job_that_lands_after_the_read_is_step_unavailable(ligand, serve, monkeypatch):
    served = serve(ligand, ligand["log"])
    f1 = ligand["free"][0]
    loop_id = served.create(ligand_loop(ligand, [f1, ligand["free"][1]]))
    real, injected = docking_bundle.submission, {}

    def race(run, args):
        """LABELLED fault injection: another request's same-key submission lands between the compute route's locked
        read and its approval event (the queue's submission only takes the transition lock)."""
        if not injected:
            injected["job"] = None
            injected["job"] = JobQueue(run).submit(DC.PROTOCOL, hand_ligand_request(ligand, f1), timeout_s=300)
        return real(run, args)

    with monkeypatch.context() as patch:
        patch.setattr(docking_bundle, "submission", race)
        got = refused(served.compute(loop_id, iteration=1, candidate=f1), "step_unavailable")
    assert got["job"] == {"id": injected["job"]["job_id"], "status": "queued"}
    assert not served.events(L.EVENT_COMPUTE_APPROVED)
    assert candidate(served.record(loop_id), f1)["state"] == "unavailable"
    refused(served.compute(loop_id, iteration=1, candidate=f1), "candidate_unavailable")


# ---------------------------------------------------------------- protein: model reuse, docking, abandon


def test_a_stored_model_is_adopted_without_a_job_and_only_the_docking_is_charged(protein, serve):
    served = serve(protein, protein["modelled"])
    w = protein["refs"][W]
    loop_id = served.create(protein_loop(protein, (W, A, B), cap=3))
    used, before = served.used(), len(served.events())
    response = served.compute(loop_id, iteration=1, candidate=w)
    assert response.status_code == 200, response.text
    new = served.events()[before:]
    assert [event["type"] for event in new] == [L.EVENT_COMPUTE_APPROVED]          # no job, no reservation
    assert payload(new[0]) == approval(loop_id=loop_id, iteration=1, step="model", candidate_ref=w,
                                       decided_by="human", proposal_handle=None, call_key=protein["model_key"],
                                       units=0)
    record = response.json()
    assert record["current"] == {
        "iteration": 1, "phase": "awaiting_docking", "step": "dock", "action": "dock",
        "needs": {"expensive_units": 1, "wall_clock_s": 300, "external_tokens": None, "usd": None, "sends": 0},
        "remaining": record["current"]["remaining"], "blocked_axes": [], "send_blocked_axes": [], "can_end": False,
        "job": None}
    assert record["iterations"][0]["steps"] == [{
        "step": "model", "candidate_ref": w, "job_id": None, "call_key": protein["model_key"],
        "result_handle": protein["model"], "state": "reused", "reason_code": None, "evaluation": "reused"}]
    assert record["counts"] == counts(started=1, human_decided=1) and served.used() == used
    # the same press again: the step is adopted, nothing to start, nothing written
    log = served.log()
    again = served.compute(loop_id, iteration=1, candidate=w)
    assert again.status_code == 200 and again.json() == record
    unchanged(served, log)
    refused(served.compute(loop_id, iteration=1, candidate=protein["refs"][A]), "phase_invalid")
    # the docking step: one M18 job into the mutant side of the model, one unit
    before = len(served.events())
    response = served.compute(loop_id, iteration=1)
    assert response.status_code == 200, response.text
    new = served.events()[before:]
    key = m18_key(hand_dock_request(protein, protein["model"]))
    approved = [event for event in new if event["type"] == L.EVENT_COMPUTE_APPROVED]
    assert [payload(event) for event in approved] == [approval(
        loop_id=loop_id, iteration=1, step="dock", candidate_ref=w, decided_by="human", proposal_handle=None,
        call_key=key, units=1)]
    submitted = [event for event in new if event["type"] == "job_submitted"]
    job = JobQueue(served.run).get(submitted[0]["job"]["job_id"])
    assert (job["protocol_id"], job["call_key"], job["timeout_s"], job["status"]) == (DC.PROTOCOL, key, 300, "done")
    record = response.json()
    handle = job["output_handles"][0]
    assert candidate(record, w) == {"ref": w, "display": candidate(record, w)["display"],
                                    "state": scored_state(served.run, handle), "evaluation": "computed",
                                    "score_kcal_mol": first_mode(served.run, handle), "iteration": 1}
    assert [step["state"] for step in record["iterations"][0]["steps"]] == ["reused", "completed"]
    assert record["counts"] == counts(started=1, done=1, human_decided=1, units_charged=1)
    assert served.used() == used + 1
    # standalone POST /jobs of the hand-written M21 and mutant M18 requests answer the loop's model and docking jobs
    assert served.submit_job(MC.PROTOCOL, hand_model_request(protein, w), 120)["call_key"] == protein["model_key"]
    assert served.submit_job(DC.PROTOCOL, hand_dock_request(protein, protein["model"]), 300)["job_id"] == job["job_id"]
    assert len(served.events("job_submitted")) == len(submitted) + 1                    # the template's model job


def test_abandoning_the_docking_ends_the_iteration_not_run_and_an_outside_docking_is_not_adopted(protein, serve):
    served = serve(protein, protein["modelled"])
    w, a = protein["refs"][W], protein["refs"][A]
    loop_id = served.create(protein_loop(protein, (W, A), cap=2))
    assert served.compute(loop_id, iteration=1, candidate=w).status_code == 200
    used, before = served.used(), len(served.events())
    response = served.abandon(loop_id, iteration=1)
    assert response.status_code == 200, response.text
    new = served.events()[before:]
    assert [(event["type"], payload(event)) for event in new] == [
        (L.EVENT_DOCKING_ABANDONED, {"loop_id": loop_id, "iteration": 1, "candidate_ref": w})]
    record = response.json()
    assert candidate(record, w) == {"ref": w, "display": candidate(record, w)["display"], "state": "not_run",
                                    "evaluation": "computed", "score_kcal_mol": None, "iteration": 1}
    assert (record["iterations"][0]["phase"], record["iterations"][0]["state"]) == ("done", "not_run")
    assert record["counts"] == counts(started=1, done=1, human_decided=1)
    assert (record["current"]["iteration"], record["current"]["action"]) == (2, "select")
    assert served.used() == used                                          # the adopted model was never charged here
    log = served.log()
    refused(served.abandon(loop_id, iteration=1), "iteration_invalid")    # the iteration has ended
    refused(served.compute(loop_id, iteration=1), "iteration_invalid")
    refused(served.abandon(loop_id, iteration=2), "phase_invalid")
    unchanged(served, log)
    # Outside the loop the same docking runs and its result is stored: the loop keeps W not_run (spec 6.5).
    job = served.submit_job(DC.PROTOCOL, hand_dock_request(protein, protein["model"]), 300)
    started = served.client.post(f"/runs/{PRID}/jobs/{job['job_id']}/start")
    assert started.status_code == 200 and started.json()["status"] == "done", started.text
    record = served.record(loop_id)
    assert candidate(record, w)["state"] == "not_run" and record["counts"]["reused_count"] == 0
    assert candidate(record, a)["state"] == "pending"


def test_abandon_refusals_follow_the_compute_order(protein, serve):
    served = serve(protein, protein["modelled"])
    w = protein["refs"][W]
    loop_id = served.create(protein_loop(protein, (W, A), cap=2))
    log = served.log()
    for body in ({"iteration": 1, "candidate": w}, {}, {"iteration": "1"}, {"iteration": 1.0}):
        refused(served.post(loop_id, "abandon_docking", body), "unknown_field")
    refused(served.abandon(str(uuid.uuid4()), iteration=1), "loop_not_found")
    refused(served.abandon(loop_id, iteration=2), "iteration_invalid")
    refused(served.abandon(loop_id, iteration=1), "phase_invalid")         # awaiting_selection, not awaiting_docking
    unchanged(served, log)
    assert served.compute(loop_id, iteration=1, candidate=w).status_code == 200
    log = served.log()
    S.begin_send(PRID, "another-send")
    try:
        refused(served.abandon(loop_id, iteration=2), "send_in_progress")
    finally:
        S.end_send(PRID, "another-send")
    refused(served.abandon(loop_id, iteration=2), "iteration_invalid")
    with served.run._owner():   # fault injection: a held run lock; the refusal is still read, a write is busy
        refused(served.abandon(loop_id, iteration=2), "iteration_invalid")
        busy = served.abandon(loop_id, iteration=1)
    assert busy.status_code == 503 and busy.json()["detail"]["error"] == "busy"
    unchanged(served, log)
    served.run.cancel()
    refused(served.abandon(loop_id, iteration=1), "cancelled")
    assert not served.events(L.EVENT_DOCKING_ABANDONED)


def test_a_docking_cancelled_before_it_started_leaves_the_candidate_not_run(protein, serve, monkeypatch):
    served = serve(protein, protein["modelled"])
    w = protein["refs"][W]
    loop_id = served.create(protein_loop(protein, (W, A), cap=2))
    assert served.compute(loop_id, iteration=1, candidate=w).status_code == 200
    with held_start(monkeypatch):
        assert served.compute(loop_id, iteration=1).status_code == 503
    record = served.record(loop_id)
    job = record["current"]["job"]
    assert (record["current"]["phase"], job["step"], job["status"]) == ("running", "dock", "queued")
    assert served.client.post(f"/runs/{PRID}/jobs/{job['job_id']}/cancel").json()["job"]["status"] == "cancelled"
    record = served.record(loop_id)
    assert candidate(record, w)["state"] == "not_run" and candidate(record, w)["iteration"] == 1
    steps = record["iterations"][0]["steps"]
    assert [(step["step"], step["state"], step["reason_code"]) for step in steps] == [
        ("model", "reused", None), ("dock", "unavailable", L.NOT_RUN_REASON)]
    assert (record["iterations"][0]["state"], record["counts"]) == ("not_run", counts(started=1, done=1,
                                                                                      human_decided=1))
    assert record["current"]["iteration"] == 2


def test_a_docking_that_fails_after_its_reservation_is_failed_and_an_outside_retry_is_not_adopted(
        protein, serve, monkeypatch):
    served = serve(protein, protein["modelled"])
    w = protein["refs"][W]
    loop_id = served.create(protein_loop(protein, (W, A), cap=2))
    assert served.compute(loop_id, iteration=1, candidate=w).status_code == 200
    used = served.used()
    with one_second_left(monkeypatch):
        response = served.compute(loop_id, iteration=1)
    assert response.status_code == 200, response.text
    record = response.json()
    dock = record["iterations"][0]["steps"][1]
    job = JobQueue(served.run).get(dock["job_id"])
    assert job["status"] == "failed" and job["failure"]["error"] == "resource_exceeded", job["failure"]
    assert "timeout" in job["failure"]["message"] and "reason_code" not in job["failure"]
    assert (dock["state"], dock["reason_code"], dock["result_handle"], dock["evaluation"]) == (
        "failed", None, None, "computed")
    assert candidate(record, w) == {"ref": w, "display": candidate(record, w)["display"], "state": "failed",
                                    "evaluation": "computed", "score_kcal_mol": None, "iteration": 1}
    assert record["counts"] == counts(started=1, done=1, human_decided=1, units_charged=1)
    assert served.used() == used + 1
    # Outside the loop the same job is retried and completes: the loop keeps W failed (spec 6.4 / 6.5).
    assert served.client.post(f"/runs/{PRID}/jobs/{job['job_id']}/retry").json()["status"] == "queued"
    started = served.client.post(f"/runs/{PRID}/jobs/{job['job_id']}/start")
    assert started.status_code == 200 and started.json()["status"] == "done", started.text
    after = served.record(loop_id)
    assert candidate(after, w)["state"] == "failed" and after["iterations"][0]["steps"][1]["state"] == "failed"
    assert after["counts"] == record["counts"]


def test_an_outside_same_key_docking_job_is_step_unavailable(protein, serve):
    served = serve(protein, protein["modelled"])
    w = protein["refs"][W]
    loop_id = served.create(protein_loop(protein, (W, A), cap=2))
    assert served.compute(loop_id, iteration=1, candidate=w).status_code == 200
    outside = served.submit_job(DC.PROTOCOL, hand_dock_request(protein, protein["model"]), 300)
    log = served.log()
    got = refused(served.compute(loop_id, iteration=1), "step_unavailable")
    assert got["job"] == {"id": outside["job_id"], "status": "queued"}
    unchanged(served, log)


def test_protein_needs_are_per_candidate_and_per_step(protein, serve):
    served = serve(protein, protein["modelled"])
    w, a = protein["refs"][W], protein["refs"][A]
    loop_id = served.create(protein_loop(protein, (W, A), cap=2))
    used = served.used()
    served.limit(units=used + 1)
    log = served.log()
    got = refused(served.compute(loop_id, iteration=1, candidate=a), "budget_blocked")
    assert got["blocked_axes"] == ["expensive_units"] and got["needs"] == {"expensive_units": 2, "wall_clock_s": 420}
    unchanged(served, log)
    assert served.compute(loop_id, iteration=1, candidate=w).status_code == 200      # stored model: 1 unit / 300 s
    served.limit(units=used)
    got = refused(served.compute(loop_id, iteration=1), "budget_blocked")
    assert got["blocked_axes"] == ["expensive_units"] and got["needs"] == {"expensive_units": 1, "wall_clock_s": 300}
    wall = served.run.budget_snapshot()["wall_clock_s"]["used"]
    served.limit(units=used + 5, wall=wall + 100)
    got = refused(served.compute(loop_id, iteration=1), "budget_blocked")
    assert got["blocked_axes"] == ["wall_clock_s"]
    assert served.used() == used and len(served.events(L.EVENT_COMPUTE_APPROVED)) == 1


def test_the_iteration_cap_is_checked_before_the_proposal_and_the_candidate(protein, serve):
    served = serve(protein, protein["modelled"])
    w, a = protein["refs"][W], protein["refs"][A]
    loop_id = served.create(protein_loop(protein, (W, A), cap=1))
    assert served.compute(loop_id, iteration=1, candidate=w).status_code == 200
    record = served.abandon(loop_id, iteration=1).json()
    assert (record["exhausted_reason"], record["current"]["action"]) == ("iteration_cap", "end")
    log = served.log()
    refused(served.compute(loop_id, iteration=2, candidate=a), "iteration_cap_reached")
    refused(served.compute(loop_id, iteration=2, proposal=f"obj://{PRID}/{L.CHOICE_KIND}/" + "1" * 64),
            "iteration_cap_reached")
    refused(served.compute(loop_id, iteration=2, candidate=w), "iteration_cap_reached")
    unchanged(served, log)
    record, content = end_loop(served, loop_id, "iteration_cap")
    assert [(row["candidate_ref"], row["state"]) for row in content["iterations"]] == [(w, "not_run")]
    assert [step["state"] for step in content["iterations"][0]["steps"]] == ["reused"]
    assert content["counts"] == counts(started=1, done=1, human_decided=1) and content["unfinished"] == []
    assert candidate(content, a)["state"] == "pending" and content["limitations"][-1] == "LJ8"


def test_a_jev_proposal_decides_by_jev_and_late_or_other_proposals_are_refused(protein, serve):
    served = serve(protein, protein["modelled"])
    w = protein["refs"][W]
    loop_id = served.create(protein_loop(protein, (W, A, B), cap=3, goal="explore"))
    S.set_consent(served.run, True)

    def project() -> tuple[str, str]:
        handle = served.run.call(L.TOOL, {"loop_id": loop_id, "iteration": 1}).handle
        content = served.run.store.load(handle)
        return handle, next(item["alias"] for item in content["selection"] if item["ref"] == w)

    first, alias = project()

    def slow(request):           # consent turned off while the request is in flight: a late reply (fixture)
        S.set_consent(served.run, False)
        return reply(alias, confidence=0.4)

    late = served.send(Fake(slow), first)
    assert (late["status"], late["late"]) == ("completed", True)
    S.set_consent(served.run, True)
    second, alias = project()
    chosen = served.send(Fake(lambda request: reply(alias, confidence=0.6)), second)
    assert (chosen["status"], chosen["late"]) == ("completed", False)
    proposal = chosen["choice_handle"]
    assert served.record(loop_id)["current"]["action"] == "compute"
    snapshot = served.log()
    refused(served.compute(loop_id, iteration=1, proposal=late["choice_handle"]), "proposal_late")
    refused(served.compute(loop_id, iteration=1, proposal=second), "proposal_invalid")
    refused(served.compute(loop_id, iteration=1, proposal=f"obj://{PRID}/{L.CHOICE_KIND}/" + "2" * 64),
            "proposal_invalid")
    refused(served.compute(loop_id, iteration=2, proposal=proposal), "iteration_invalid")
    unchanged(served, snapshot)
    # JEV's choice approved by the person: decided_by jev with the proposal (W has a stored model: adopted)
    before = len(served.events())
    response = served.compute(loop_id, iteration=1, proposal=proposal)
    assert response.status_code == 200, response.text
    assert [payload(event) for event in served.events()[before:]] == [approval(
        loop_id=loop_id, iteration=1, step="model", candidate_ref=w, decided_by="jev", proposal_handle=proposal,
        call_key=protein["model_key"], units=0)]
    choice = served.run.store.load(proposal)["answer"]
    first_iteration = response.json()["iterations"][0]
    assert (first_iteration["decided_by"], first_iteration["proposal_handle"], first_iteration["list_position"],
            first_iteration["list_size"]) == ("jev", proposal, choice["list_position"], choice["list_size"])
    assert response.json()["counts"] == counts(started=1, jev_decided=1, sends_dispatched=2)
    again = served.compute(loop_id, iteration=1, proposal=proposal)
    assert again.status_code == 200 and again.json() == response.json()
    assert served.abandon(loop_id, iteration=1).status_code == 200
    refused(served.compute(loop_id, iteration=2, proposal=proposal), "proposal_invalid")   # another iteration's
    _record, content = end_loop(served, loop_id, "ended_by_user")
    decided = content["iterations"][0]
    assert (decided["decided_by"], decided["candidate_ref"], decided["proposal_handle"], decided["send_id"],
            decided["list_position"], decided["list_size"], decided["state"]) == (
        "jev", w, proposal, chosen["send_id"], choice["list_position"], choice["list_size"], "not_run")
    assert content["counts"] == counts(started=1, done=1, jev_decided=1, sends_dispatched=2)
    assert content["limitations"] == ["LJ1", "LJ2", "LJ3", "LJ5", "LJ7", "LJ8"]
    # The same state, but the person names the candidate: decided_by human even with a JEV choice present.
    other = serve(protein, snapshot, name="human")
    response = other.compute(loop_id, iteration=1, candidate=w)
    assert response.status_code == 200, response.text
    assert payload(other.events(L.EVENT_COMPUTE_APPROVED)[-1])["decided_by"] == "human"
    assert payload(other.events(L.EVENT_COMPUTE_APPROVED)[-1])["proposal_handle"] is None
    first_iteration = response.json()["iterations"][0]
    assert (first_iteration["decided_by"], first_iteration["proposal_handle"], first_iteration["list_position"]) == (
        "human", None, None)


def test_changed_m21_pins_and_an_m21_admission_refusal_write_nothing(protein, serve, monkeypatch):
    served = serve(protein, protein["modelled"])
    a = protein["refs"][A]
    loop_id = served.create(protein_loop(protein, (W, A), cap=2))
    log = served.log()
    real = mutation_model_bundle.require_ready()
    with monkeypatch.context() as patch:   # fault injection: the M21 worker changed after the loop was created
        patch.setattr(mutation_model_bundle, "require_ready", lambda: {**real, "worker_sha256": "e" * 64})
        got = refused(served.compute(loop_id, iteration=1, candidate=a), "capability_unavailable")
    assert got["capability"]["reason_code"] == "missing_configuration"
    with monkeypatch.context() as patch:   # fault injection: the M7 preflight of the M21 submission refuses
        def refuse(run, admitted):
            raise ToolFailure(FailureClass.input_invalid, "M7 preflight failed",
                              detail={"reason_code": "openmm_preflight_failed"})
        patch.setattr(mutation_model_bundle, "selection", refuse)
        response = served.compute(loop_id, iteration=1, candidate=a)
    assert response.status_code == 422 and response.json()["detail"] == {"reason_code": "openmm_preflight_failed"}
    unchanged(served, log)


# ---------------------------------------------------------------- protein, fresh run: first approval, cancel, failure


def test_first_approval_wait_cancel_another_candidate_running_press_and_a_failed_model(protein, serve, monkeypatch,
                                                                                      tmp_path):
    served = serve(protein, protein["fresh"])
    w, a, x = protein["refs"][W], protein["refs"][A], protein["refs"][X]
    loop_id = served.create(protein_loop(protein, (W, A, X), cap=3))
    # W: the run's first expensive call waits for the person (200 + start_blocked, nothing charged)
    response = served.compute(loop_id, iteration=1, candidate=w)
    assert response.status_code == 200, response.text
    current = response.json()["current"]
    job_w = current["job"]["job_id"]
    assert (current["phase"], current["action"], current["job"]) == (
        "running", "wait_job", {"job_id": job_w, "step": "model", "status": "claimed",
                                "start_blocked": L.START_BLOCKED})
    assert JobQueue(served.run).get(job_w)["protocol_id"] == MC.PROTOCOL and served.used() == 0
    approvals, jobs = len(served.events(L.EVENT_COMPUTE_APPROVED)), len(served.events("job_submitted"))
    again = served.compute(loop_id, iteration=1, candidate=w)     # the same press: the same job is started again
    assert again.status_code == 200 and again.json()["current"]["job"]["start_blocked"] == L.START_BLOCKED
    assert (len(served.events(L.EVENT_COMPUTE_APPROVED)), len(served.events("job_submitted"))) == (approvals, jobs)
    refused(served.compute(loop_id, iteration=1, candidate=a), "phase_invalid")
    # cancelling the waiting job (no process, nothing charged): W unavailable, the iteration is not started
    assert served.client.post(f"/runs/{PRID}/jobs/{job_w}/cancel").json()["job"]["status"] == "cancelled"
    record = served.record(loop_id)
    assert candidate(record, w)["state"] == "unavailable" and record["counts"] == counts()
    assert record["current"]["action"] == "select" and record["iterations"][0]["state"] == "unavailable"
    projection = served.run.store.load(served.run.call(L.TOOL, {"loop_id": loop_id, "iteration": 1}).handle)
    assert sorted(item["ref"] for item in projection["selection"]) == sorted([a, x])
    refused(served.compute(loop_id, iteration=1, candidate=w), "candidate_unavailable")
    # A: a new approval of iteration 1, still waiting for the person; the person approves; the next press runs it
    response = served.compute(loop_id, iteration=1, candidate=a)
    assert response.status_code == 200 and response.json()["current"]["job"]["start_blocked"] == L.START_BLOCKED
    job_a = response.json()["current"]["job"]["job_id"]
    assert served.client.post(f"/runs/{PRID}/jobs/approve").status_code == 200
    pressed = {}
    thread = threading.Thread(target=lambda: pressed.setdefault("response", TestClient(
        api_module.app, base_url="http://127.0.0.1").post(
        f"/runs/{PRID}/jev_loops/{loop_id}/compute", content=json.dumps({"iteration": 1, "candidate": a}).encode(),
        headers=JSON_HEADERS)))
    thread.start()
    deadline = time.monotonic() + 120
    while JobQueue(served.run).get(job_a)["status"] != "running" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert JobQueue(served.run).get(job_a)["status"] == "running"
    approvals, jobs = len(served.events(L.EVENT_COMPUTE_APPROVED)), len(served.events("job_submitted"))
    during = served.compute(loop_id, iteration=1, candidate=a)    # pressed again while it runs: the record, no start
    assert during.status_code == 200, during.text
    assert during.json()["current"]["job"] == {"job_id": job_a, "step": "model", "status": "running",
                                               "start_blocked": None}
    assert (len(served.events(L.EVENT_COMPUTE_APPROVED)), len(served.events("job_submitted"))) == (approvals, jobs)
    thread.join(300)
    assert not thread.is_alive() and pressed["response"].status_code == 200, pressed["response"].text
    record = pressed["response"].json()
    assert record["current"]["phase"] == "awaiting_docking" and record["counts"] == counts(
        started=1, human_decided=1, units_charged=1)
    first = record["iterations"][0]
    assert [(item["candidate_ref"], item["step"]) for item in first["approvals"]] == [(w, "model"), (a, "model")]
    assert [(step["candidate_ref"], step["state"]) for step in first["steps"]] == [(w, "unavailable"), (a, "completed")]
    model_a = first["steps"][1]["result_handle"]
    assert served.submit_job(MC.PROTOCOL, hand_model_request(protein, a), 120)["job_id"] == job_a
    # A's docking
    response = served.compute(loop_id, iteration=1)
    assert response.status_code == 200, response.text
    dock = response.json()["iterations"][0]["steps"][2]
    assert dock["call_key"] == m18_key(hand_dock_request(protein, model_a)) and dock["state"] == "completed"
    assert candidate(response.json(), a)["state"] == scored_state(served.run, dock["result_handle"])
    # X: the model fails after its reservation -> X failed, iteration 2 ends, no docking step
    with one_second_left(monkeypatch):
        response = served.compute(loop_id, iteration=2, candidate=x)
    assert response.status_code == 200, response.text
    record = response.json()
    second = record["iterations"][1]
    assert [(step["step"], step["state"]) for step in second["steps"]] == [("model", "failed")]
    assert (second["phase"], second["state"]) == ("done", "failed")
    assert candidate(record, x) == {"ref": x, "display": candidate(record, x)["display"], "state": "failed",
                                    "evaluation": "computed", "score_kcal_mol": None, "iteration": 2}
    refused(served.compute(loop_id, iteration=2), "iteration_invalid")
    # W unavailable does not hold back pool_exhausted
    assert (record["status"], record["exhausted_reason"], record["current"]["action"]) == (
        "active", "pool_exhausted", "end")
    assert record["counts"] == counts(started=2, done=2, human_decided=2, units_charged=3)
    assert served.used() == 3
    record, content = end_loop(served, loop_id, "pool_exhausted")
    first, second = content["iterations"]
    assert [(step["step"], step["candidate_ref"], step["state"]) for step in first["steps"]] == [
        ("model", w, "unavailable"), ("model", a, "completed"), ("dock", a, "completed")]
    assert (first["candidate_ref"], first["state"], second["candidate_ref"], second["state"]) == (
        a, scored_state(served.run, dock["result_handle"]), x, "failed")
    assert candidate(content, a)["score_kcal_mol"] == first_mode(served.run, dock["result_handle"])
    assert content["unfinished"] == [] and content["counts"] == counts(started=2, done=2, human_decided=2,
                                                                       units_charged=3)
    assert content["limitations"] == ["LJ1", "LJ2", "LJ3", "LJ4", "LJ7", "LJ8"]     # W left unavailable
    # Events-only replay of the ended loop with no engine, job lane or tool: the same record and summary.
    log = served.log()
    with monkeypatch.context() as patch:   # fault injection: every engine, job and tool path fails
        patch.setattr(docking_bundle, "WORKER_PYTHON", tmp_path / "missing/python")
        docking_bundle._HANDSHAKE_CACHE.clear()

        def missing(*args):
            raise PackageNotFoundError("pdbfixer")

        def no_lane(*args, **kwargs):
            raise AssertionError("a read never reaches the job lane or a tool")

        patch.setattr(mutation_model_bundle, "_pdbfixer_version", missing)
        for name in ("submit", "start", "retry", "request_cancel"):
            patch.setattr(JobQueue, name, no_lane)
        patch.setattr(Run, "call", no_lane)
        replay = serve(protein, log, name="replay")
        base = replay.log()
        assert replay.record(loop_id) == record
        rows = replay.client.get(f"/runs/{PRID}/jev_loops").json()
        assert (rows[0]["loop_id"], rows[0]["status"], rows[0]["end_reason"]) == (loop_id, "ended", "pool_exhausted")
        view = jev_loop_store.LoopReadView(replay.run)
        assert jev_loop_store.stored_result(view, record["result_handle"]) == content
        unchanged(replay, base)
    docking_bundle._HANDSHAKE_CACHE.clear()


# ---------------------------------------------------------------- ending a loop: refusals, reasons, summary reads


def test_end_refusals_follow_the_spec_order_and_write_nothing(protein, serve, monkeypatch):
    served = serve(protein, protein["modelled"])
    w = protein["refs"][W]
    loop_id = served.create(protein_loop(protein, (W, A), cap=2))
    log = served.log()
    for body in ({"iteration": 1}, {"x": None}):
        refused(served.post(loop_id, "end", body), "unknown_field")
    refused(served.end(str(uuid.uuid4())), "loop_not_found")
    unchanged(served, log)
    assert served.compute(loop_id, iteration=1, candidate=w).status_code == 200      # W's stored model adopted
    log = served.log()
    refused(served.end(loop_id), "docking_pending")
    S.begin_send(PRID, "another-send")
    try:
        refused(served.end(loop_id), "send_in_progress")
    finally:
        S.end_send(PRID, "another-send")
    with held_start(monkeypatch):
        assert served.compute(loop_id, iteration=1).status_code == 503              # the docking job stays queued
    log = served.log()
    refused(served.end(loop_id), "job_running")
    S.begin_send(PRID, "another-send")
    try:
        refused(served.end(loop_id), "send_in_progress")
    finally:
        S.end_send(PRID, "another-send")
    with served.run._owner():          # fault injection: a held run lock; a refusal is still read
        refused(served.end(loop_id), "job_running")
    unchanged(served, log)
    job = served.record(loop_id)["current"]["job"]["job_id"]
    assert served.client.post(f"/runs/{PRID}/jobs/{job}/cancel").json()["job"]["status"] == "cancelled"
    log = served.log()
    with served.run._owner():          # fault injection: a held run lock; the end would write -> busy
        busy = served.end(loop_id)
    assert busy.status_code == 503 and busy.json()["detail"]["error"] == "busy"
    unchanged(served, log)
    served.run.cancel()
    refused(served.end(loop_id), "cancelled")
    assert not served.events(L.EVENT_ENDED) and not [event for event in served.events("object_created")
                                                     if event["kind"] == L.RESULT_KIND]


def test_a_loop_short_of_compute_budget_ends_budget_exhausted_with_its_unfinished_iteration(protein, serve,
                                                                                          monkeypatch):
    served = serve(protein, protein["modelled"])
    w, a = protein["refs"][W], protein["refs"][A]
    loop_id = served.create(protein_loop(protein, (W, A), cap=2))
    with held_start(monkeypatch):
        assert served.compute(loop_id, iteration=1, candidate=a).status_code == 503
    job = JobQueue(served.run).get(served.record(loop_id)["current"]["job"]["job_id"])
    assert served.client.post(f"/runs/{PRID}/jobs/{job['job_id']}/cancel").json()["job"]["status"] == "cancelled"
    served.limit(units=served.used())                       # no unit left: W (stored model) needs one
    assert served.record(loop_id)["current"]["blocked_axes"] == ["expensive_units"]
    _record, content = end_loop(served, loop_id, "budget_exhausted")
    assert content["iterations"] == [{
        "index": 1, "decided_by": "human", "candidate_ref": a, "proposal_handle": None, "send_id": None,
        "list_position": None, "list_size": None,
        "approvals": [{"step": "model", "candidate_ref": a, "decided_by": "human", "proposal_handle": None,
                       "call_key": job["call_key"]}],
        "steps": [{"step": "model", "candidate_ref": a, "job_id": job["job_id"], "call_key": job["call_key"],
                   "result_handle": None, "state": "unavailable", "reason_code": None}],
        "state": "unavailable", "score_kcal_mol": None}]
    assert content["unfinished"] == [{"iteration": 1, "candidate_ref": a}] and content["counts"] == counts()
    assert [(row["ref"], row["state"]) for row in content["candidates"]] == [(a, "unavailable"), (w, "pending")]
    assert content["limitations"] == ["LJ1", "LJ2", "LJ3", "LJ4", "LJ7", "LJ8"]
    served.limit(units=40)
    served.create(protein_loop(protein, (W, A), cap=2))     # the same branch may start a new loop


def test_an_end_stopped_after_its_summary_retries_to_the_same_summary(protein, serve, monkeypatch):
    served = serve(protein, protein["modelled"])
    loop_id = served.create(protein_loop(protein, (W, A), cap=2))
    real = served.run.events.append

    def stop(event_type, /, **fields):  # fault injection: the server stops right before the end event
        if event_type == L.EVENT_ENDED:
            raise RuntimeError("stopped before jev_loop_ended")
        return real(event_type, **fields)

    with monkeypatch.context() as patch:
        patch.setattr(served.run.events, "append", stop)
        with pytest.raises(RuntimeError):
            served.end(loop_id)
    stored = [event for event in served.events("object_created") if event["kind"] == L.RESULT_KIND]
    assert len(stored) == 1 and not served.events(L.EVENT_ENDED)
    assert served.record(loop_id)["status"] == "active"           # no end event: the loop has not ended
    before = len(served.events())
    response = served.end(loop_id)
    assert response.status_code == 200, response.text
    assert [(event["type"], event.get("result_handle")) for event in served.events()[before:]] == [
        (L.EVENT_ENDED, stored[0]["handle"])]                      # the same content, the same handle, stored once
    assert response.json()["result_handle"] == stored[0]["handle"]


def test_a_stored_summary_that_is_not_its_loops_summary_is_refused_on_read(protein, serve):
    served = serve(protein, protein["modelled"])
    loop_id = served.create(protein_loop(protein, (W, A), cap=2))
    content = R.build_loop_result(served.record(loop_id), "ended_by_user")
    forged = {**content, "loop_seed": content["loop_seed"] + 1}          # LABELLED fault injection
    assert R.validated_loop_result(forged) == forged                       # well formed, but not this loop's
    handle = served.run.store.put(L.RESULT_KIND, L.RESULT_SCHEMA, forged).handle
    served.run.events.append(L.EVENT_ENDED, loop_id=loop_id, end_reason="ended_by_user", result_handle=handle)
    log = served.log()
    for response in (served.client.get(f"/runs/{PRID}/jev_loops/{loop_id}"),
                     served.client.get(f"/runs/{PRID}/jev_loops"), served.end(loop_id)):
        assert response.status_code == 409 and response.json()["detail"]["error"] == "run_corrupt", response.text
    unchanged(served, log)
    with pytest.raises(R.LoopResultInvalid):
        jev_loop_store.stored_result(jev_loop_store.LoopReadView(served.run), handle)
    other = serve(protein, protein["modelled"], name="missing")
    loop_id = other.create(protein_loop(protein, (W, A), cap=2))
    other.run.events.append(L.EVENT_ENDED, loop_id=loop_id, end_reason="ended_by_user",   # LABELLED SYNTHETIC
                            result_handle=f"obj://{PRID}/{L.RESULT_KIND}/" + "0" * 64)
    response = other.client.get(f"/runs/{PRID}/jev_loops/{loop_id}")
    assert response.status_code == 409 and response.json()["detail"]["error"] == "run_corrupt"


# ---------------------------------------------------------------- HTTP shape, route order and boundaries


@pytest.mark.parametrize("action", ["compute", "abandon_docking", "end"])
def test_the_action_routes_take_json_only_bound_the_body_and_refuse_queries(action, protein, serve):
    served = serve(protein, protein["fresh"])
    loop_id = served.create(protein_loop(protein, (W, A), cap=2))
    log = served.log()
    raw = json.dumps({"iteration": 1}).encode()
    for content_type in ("text/plain", "application/x-www-form-urlencoded", "application/jsonx", None):
        response = served.post(loop_id, action, raw=raw, headers={} if content_type is None else {
            "content-type": content_type})
        assert response.status_code == 415 and response.json()["detail"]["error"] == "unsupported_media_type"
    padded = json.dumps({"iteration": 1, "pad": "x" * L.MAX_ACTION_REQUEST_BYTES}).encode()
    assert served.post(loop_id, action, raw=padded).status_code == 413
    for content in (b"not json", b"[]", b'{"iteration": 1, "iteration": 2}', b'{"iteration": NaN}'):
        response = served.post(loop_id, action, raw=content)
        assert response.status_code == 422 and response.json()["detail"]["error"] == "input_invalid", content
    assert served.post(loop_id, action, {"iteration": 1}, query="?x=1").status_code == 422
    assert served.client.post(f"/runs/run_missing_m25/jev_loops/{loop_id}/{action}", content=raw,
                              headers=JSON_HEADERS).status_code == 404
    assert served.client.get(f"/runs/{PRID}/jev_loops/{loop_id}/{action}").status_code == 405
    unchanged(served, log)


def test_a_held_run_lock_is_busy_only_for_a_press_that_would_write(protein, serve):
    served = serve(protein, protein["modelled"])
    w = protein["refs"][W]
    loop_id = served.create(protein_loop(protein, (W, A), cap=2))
    log = served.log()
    with served.run._owner():      # fault injection: another owner (a job start, a send, a tool call) holds the lock
        busy = served.compute(loop_id, iteration=1, candidate=w)
        refused(served.compute(loop_id, iteration=2, candidate=w), "iteration_invalid")
    assert busy.status_code == 503 and busy.json()["detail"] == {
        "error": "busy", "message": api_module.JEV_LOOP_BUSY_MESSAGE}
    unchanged(served, log)


def test_the_action_routes_are_posts_registered_before_the_detail_route():
    paths = [(route.path, sorted(route.methods)) for route in api_module.app.routes
             if getattr(route, "methods", None) and route.path.startswith("/runs/{rid}/jev_loops")]
    detail = paths.index(("/runs/{rid}/jev_loops/{loop_id}", ["GET"]))
    for action in ("compute", "abandon_docking", "end"):
        assert paths.index((f"/runs/{{rid}}/jev_loops/{{loop_id}}/{action}", ["POST"])) < detail
    assert [path for path, _ in paths].count("/runs/{rid}/jev_loops/{loop_id}/compute") == 1


def test_the_action_routes_and_the_loop_modules_name_no_send_approval_or_limit_path():
    tree = ast.parse((MW / "api/app.py").read_text())
    functions = {node.name: node for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
                     "jev_loop_compute", "jev_loop_abandon_docking", "_jev_loop_compute", "jev_loop_end"}}
    assert set(functions) == {"jev_loop_compute", "jev_loop_abandon_docking", "_jev_loop_compute", "jev_loop_end"}
    for function in functions.values():
        names = {node.id if isinstance(node, ast.Name) else node.attr for node in ast.walk(function)
                 if isinstance(node, (ast.Name, ast.Attribute))}
        assert not names & {"run_send", "request_science", "SCIENCE_GATE", "raise_limits", "limit_approval",
                            "approve", "retry", "request_cancel", "update_limits", "Thread", "Timer"}
    for name in ("jev_loop_store.py", "jev_loops.py", "jev_loop_constants.py", "jev_loop_result.py"):
        text = (MW / name).read_text()
        assert "raise_limits" not in text and "limit_approval" not in text, name
    store = ast.parse((MW / "jev_loop_store.py").read_text())
    called = {node.func.attr for node in ast.walk(store) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)}
    assert not called & {"submit", "start", "retry", "request_cancel", "call", "reserve_attempt", "approve"}
