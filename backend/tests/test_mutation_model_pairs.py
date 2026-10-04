"""M21 T7: ``GET /runs/{id}/mutation_models/{handle}/docking_pairs`` (spec .dryforge/spec.md 7, same-condition docking).

The model comes from the real M21 worker (``mutation_model_fixture.shared_world``; public 1UBQ I44W, public structure,
not experimental validation). Its run is copied here from ``events.jsonl`` alone (events-only recovery). Four condition
groups are built through the product job API (POST /jobs -> approve -> start), differing only by seed:

* A: both sides docked by the REAL M18 worker (qvina2) -> both published, scores side by side.
* B: wild type docked for real; the mutant job ends ``failed`` through a LABELED SIMULATED GUARDIAN that reports a
  timeout (no process is launched; the queue records the failure, a charged attempt and no object, as for a real one).
* C: the wild type job is submitted only (stays ``queued``); the mutant is docked for real, and the read is taken once
  while that job is ``running`` (inside the guardian call, before the worker starts).
* D: only the wild type job is ever submitted, then cancelled while queued (no attempt, no charge).

The ligand is the labeled synthetic phenol ``fixtures/mutation_model/synthetic-phenol-ligand.sdf`` (hand-built, not
experimental). Tests FAIL, never skip, when an engine is absent. Scores are compared only with the stored M18 values,
never between the two structures.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import psutil
import pytest
from fastapi.testclient import TestClient
from mutation_model_fixture import SIDES, shared_world

from mw import docking_bundle, docking_inputs, mutation_model_reads
from mw import docking_constants as C
from mw import mutation_reports as m20
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.jobs import process_identity
from mw.jobs.queue import JobQueue
from mw.runtime.orchestrator import Run
from mw.workspace import new_run

FIX = Path(__file__).parent / "fixtures"
LIGAND = (FIX / "mutation_model/synthetic-phenol-ligand.sdf").read_bytes()
ACK = {key: True for key in C.ACKNOWLEDGEMENT_KEYS}
SEEDS = {"A": 20261004, "B": 20261005, "C": 20261006, "D": 20261007}
PAIR_KEYS = {"index", "first_submitted_seq", "condition", "both_published", "sides"}
SIDE_KEYS = {"side", "job_id", "job_status", "submitted_seq", "result_handle", "score_kcal_mol", "score_mode",
             "reason_code", "reason"}
# Field-name fragments a pair must never carry: no difference, change, ranking or choice between the two structures.
FORBIDDEN_KEY = re.compile(r"diff|delta|change|rank|best|improv|better|worse|winner|ratio|order|preferred|top",
                           re.IGNORECASE)
FORBIDDEN_TEXT = re.compile(m20.INTERPRETIVE.pattern + r"|차이|변화|증가|감소|difference|delta|better|worse",
                            re.IGNORECASE)


# ----------------------------------------------------------------- helpers
def _client(root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _events_bytes(root: Path, rid: str) -> bytes:
    return (root / rid / "events.jsonl").read_bytes()


def _kill_leftovers(root: Path, rid: str) -> None:
    for line in _events_bytes(root, rid).decode().splitlines():
        event = json.loads(line)
        if event["type"] == "job_worker_started" and process_identity.matches(event["pid"], event["start_identity"]):
            try:
                psutil.Process(event["pid"]).kill()
            except psutil.Error:
                pass


def _args(model: str, side: str, sdf: str, seed: int) -> dict:
    return {"receptor_source": {"kind": "mutation_model", "mutation_model": model, "side": side},
            "ligand": {"source": "sdf", "sdf_handle": sdf}, "mode": "free",
            "box": {"source": "ligand_range", "margin_A": 8},
            "parameters": {"seed": seed, "exhaustiveness": 4, "num_modes": 5}, "acknowledgement": ACK}


def _submit(client: TestClient, rid: str, args: dict) -> dict:
    response = client.post(f"/runs/{rid}/jobs", json={"protocol_id": "qvina_dock_v1", "args": args, "timeout_s": 600})
    assert response.status_code == 200, response.text
    return response.json()


def _start(client: TestClient, rid: str, job_id: str) -> dict:
    started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    if started.status_code == 409:
        assert client.post(f"/runs/{rid}/jobs/approve").status_code == 200
        started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    assert started.status_code == 200, started.text
    return started.json()


def _timeout_guardian(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch):
    """LABELED SIMULATED GUARDIAN: reports a timeout without launching any process."""
    return {"kind": "RESULT", "reason": "timeout", "returncode": None, "clean": True, "direct_child_reaped": True,
            "unexpected_members": False}, None


def _pairs(client: TestClient, rid: str, model: str, **params):
    return client.get(f"/runs/{rid}/mutation_models/{model}/docking_pairs", params=params)


def _keys(value, found: set) -> set:
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(key)
            _keys(item, found)
    elif isinstance(value, list):
        for item in value:
            _keys(item, found)
    return found


# ----------------------------------------------------------------- the paired world (built once per module)
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return shared_world(tmp_path_factory)


@pytest.fixture(scope="module")
def paired(world, tmp_path_factory):
    root = tmp_path_factory.mktemp("m21_pairs") / "runs"
    rid, model = world["rid"], world["model"]
    (root / rid).mkdir(parents=True)
    shutil.copyfile(world["root"] / rid / "events.jsonl", root / rid / "events.jsonl")
    new_run(root, run_id=rid, dry_run=False)
    saved = api_module.RUNS_DIR
    patch = pytest.MonkeyPatch()
    jobs: dict[tuple[str, str], dict] = {}
    try:
        client = _client(root, patch)
        response = client.post(f"/runs/{rid}/chemical/imports", params={"kind": "ligand_sdf", "filename": "p.sdf"},
                               content=LIGAND, headers={"content-type": "application/octet-stream"})
        assert response.status_code == 201, response.text
        sdf = response.json()["handle"]
        empty = _pairs(client, rid, model)
        assert empty.status_code == 200, empty.text
        for side in SIDES:                                                     # A: both real
            jobs["A", side] = _start(client, rid, _submit(client, rid, _args(model, side, sdf, SEEDS["A"]))["job_id"])
        jobs["B", "wild_type_reference"] = _start(client, rid, _submit(
            client, rid, _args(model, "wild_type_reference", sdf, SEEDS["B"]))["job_id"])
        with pytest.MonkeyPatch.context() as simulated:                       # B: mutant timeout (simulated)
            simulated.setattr(JobQueue, "_supervise", _timeout_guardian)
            jobs["B", "mutant"] = _start(client, rid, _submit(
                client, rid, _args(model, "mutant", sdf, SEEDS["B"]))["job_id"])
        jobs["C", "wild_type_reference"] = _submit(client, rid, _args(model, "wild_type_reference", sdf, SEEDS["C"]))
        running: list[dict] = []
        original = JobQueue._supervise

        def observe(self, job, *rest):
            running.append(mutation_model_reads.docking_pairs(self.run, model))
            return original(self, job, *rest)

        with pytest.MonkeyPatch.context() as watched:                          # C: mutant real, observed running
            watched.setattr(JobQueue, "_supervise", observe)
            jobs["C", "mutant"] = _start(client, rid, _submit(
                client, rid, _args(model, "mutant", sdf, SEEDS["C"]))["job_id"])
        queued = _submit(client, rid, _args(model, "wild_type_reference", sdf, SEEDS["D"]))   # D: one side only
        cancelled = client.post(f"/runs/{rid}/jobs/{queued['job_id']}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        jobs["D", "wild_type_reference"] = client.get(f"/runs/{rid}/jobs/{queued['job_id']}").json()
        return {"root": root, "rid": rid, "model": model, "sdf": sdf, "jobs": jobs, "running": running,
                "empty": empty.json()}
    finally:
        _kill_leftovers(root, rid)
        patch.undo()
        api_module.RUNS_DIR = saved
        api_module.RUNS.clear()


@pytest.fixture
def client(paired, monkeypatch):
    return _client(paired["root"], monkeypatch)


def _body(client, paired) -> dict:
    response = _pairs(client, paired["rid"], paired["model"])
    assert response.status_code == 200, response.text
    return response.json()


def _stored_first_score(paired, handle: str) -> tuple[int, float]:
    content = api_module._run(paired["rid"]).store.load(handle)
    return content["modes"][0]["mode"], content["modes"][0]["score_kcal_mol"]


# ----------------------------------------------------------------- the job states are the intended ones
def test_job_states_are_real(paired):
    jobs = paired["jobs"]
    for key in (("A", "wild_type_reference"), ("A", "mutant"), ("B", "wild_type_reference"), ("C", "mutant")):
        assert jobs[key]["status"] == "done" and len(jobs[key]["output_handles"]) == 1, (key, jobs[key])
    assert jobs["B", "mutant"]["status"] == "failed" and jobs["B", "mutant"]["output_handles"] == []
    assert jobs["B", "mutant"]["failure"]["message"] == "job timeout"
    assert jobs["C", "wild_type_reference"]["status"] == "queued"
    assert jobs["D", "wild_type_reference"]["status"] == "cancelled"
    assert paired["empty"]["pairs"] == [] and paired["empty"]["total"] == 0


# ----------------------------------------------------------------- the pairs
def test_four_groups_in_submission_order_one_per_condition(client, paired):
    body = _body(client, paired)
    assert body["schema"] == "mutation_model_docking_pairs@1" and body["handle"] == paired["model"]
    assert body["score_label"] == C.SCORE_LABEL and body["starts_job"] is False
    assert set(body) == {"schema", "handle", "score_label", "total", "pairs", "starts_job"}
    assert body["total"] == len(body["pairs"]) == 4
    assert [pair["condition"]["parameters"]["seed"] for pair in body["pairs"]] == [SEEDS[g] for g in "ABCD"]
    assert [pair["index"] for pair in body["pairs"]] == [0, 1, 2, 3]
    firsts = [pair["first_submitted_seq"] for pair in body["pairs"]]
    assert firsts == sorted(firsts) and len(set(firsts)) == 4
    for pair in body["pairs"]:
        assert set(pair) == PAIR_KEYS and list(pair["sides"]) == list(SIDES)
        assert all(set(entry) == SIDE_KEYS for entry in pair["sides"].values())
        condition = pair["condition"]
        assert set(condition) == {"ligand", "mode", "box", "parameters", "method_pins_sha256"}
        normalized = docking_inputs.validate_arguments(_args(paired["model"], "mutant", paired["sdf"],
                                                             condition["parameters"]["seed"]))
        assert {key: condition[key] for key in ("ligand", "mode", "box", "parameters")} == {
            key: normalized[key] for key in ("ligand", "mode", "box", "parameters")}
        assert condition["ligand"] == {"source": "sdf", "sdf_handle": paired["sdf"]}
    assert len({pair["condition"]["method_pins_sha256"] for pair in body["pairs"]}) == 1


def test_both_sides_done_show_the_stored_first_mode_scores(client, paired):
    pair = _body(client, paired)["pairs"][0]
    assert pair["both_published"] is True
    for side in SIDES:
        job = paired["jobs"]["A", side]
        entry = pair["sides"][side]
        handle = job["output_handles"][0]
        mode, score = _stored_first_score(paired, handle)
        assert entry == {"side": side, "job_id": job["job_id"], "job_status": "done",
                         "submitted_seq": entry["submitted_seq"], "result_handle": handle, "score_kcal_mol": score,
                         "score_mode": mode, "reason_code": None, "reason": None}
        assert mode == 1 and isinstance(score, float)
        # the published result is the one M18 validates, with this model and side as its receptor source
        content = docking_bundle.validated_result(api_module._run(paired["rid"]), handle)
        assert content["inputs"]["receptor"]["source"] == {"kind": "mutation_model",
                                                           "mutation_model": paired["model"], "side": side}
        assert content["parameters"]["seed"] == SEEDS["A"]
    assert pair["sides"]["wild_type_reference"]["result_handle"] != pair["sides"]["mutant"]["result_handle"]


def test_one_side_failed_shows_status_only_on_both_sides(client, paired):
    pair = _body(client, paired)["pairs"][1]
    assert pair["both_published"] is False
    done, failed = pair["sides"]["wild_type_reference"], pair["sides"]["mutant"]
    assert done["job_status"] == "done" and done["job_id"] == paired["jobs"]["B", "wild_type_reference"]["job_id"]
    assert (done["result_handle"], done["score_kcal_mol"], done["score_mode"]) == (None, None, None)
    assert done["reason_code"] == "other_side_missing"
    assert done["reason"] == mutation_model_reads.PAIR_REASONS["other_side_missing"]
    assert failed["job_status"] == "failed" and failed["job_id"] == paired["jobs"]["B", "mutant"]["job_id"]
    assert (failed["result_handle"], failed["score_kcal_mol"], failed["reason_code"]) == (None, None, "job_failed")


def test_one_side_still_queued_or_running(client, paired):
    pair = _body(client, paired)["pairs"][2]
    assert pair["both_published"] is False
    queued, done = pair["sides"]["wild_type_reference"], pair["sides"]["mutant"]
    assert (queued["job_status"], queued["reason_code"], queued["score_kcal_mol"]) == ("queued", "job_not_finished",
                                                                                     None)
    assert (done["job_status"], done["reason_code"], done["score_kcal_mol"], done["result_handle"]) == (
        "done", "other_side_missing", None, None)
    # The read taken while the mutant job of C was running (one observation, inside the guardian call).
    [snapshot] = paired["running"]
    observed = next(p for p in snapshot["pairs"] if p["condition"]["parameters"]["seed"] == SEEDS["C"])
    assert observed["both_published"] is False
    assert observed["sides"]["mutant"]["job_status"] == "running"
    assert observed["sides"]["mutant"]["reason_code"] == "job_not_finished"
    assert observed["sides"]["wild_type_reference"]["job_status"] == "queued"
    assert all(entry["score_kcal_mol"] is None and entry["result_handle"] is None
               for entry in observed["sides"].values())
    # groups A and B read the same while C ran (A still shows both stored scores)
    assert snapshot["pairs"][0] == _body(client, paired)["pairs"][0]


def test_only_one_side_ever_submitted(client, paired):
    pair = _body(client, paired)["pairs"][3]
    assert pair["both_published"] is False
    cancelled, missing = pair["sides"]["wild_type_reference"], pair["sides"]["mutant"]
    assert (cancelled["job_status"], cancelled["reason_code"]) == ("cancelled", "job_cancelled")
    assert missing == {"side": "mutant", "job_id": None, "job_status": "not_submitted", "submitted_seq": None,
                       "result_handle": None, "score_kcal_mol": None, "score_mode": None,
                       "reason_code": "not_submitted", "reason": mutation_model_reads.PAIR_REASONS["not_submitted"]}


def test_same_conditions_repeated_stay_one_group_and_seeds_split_groups(client, paired):
    before = _body(client, paired)
    for side in SIDES:     # the same conditions again: the queue returns the existing job (same call key)
        again = _submit(client, paired["rid"], _args(paired["model"], side, paired["sdf"], SEEDS["A"]))
        assert again["job_id"] == paired["jobs"]["A", side]["job_id"]
    after = _body(client, paired)
    assert after == before
    seeds = [pair["condition"]["parameters"]["seed"] for pair in after["pairs"]]
    assert len(seeds) == len(set(seeds)) == 4
    job_ids = [entry["job_id"] for pair in after["pairs"] for entry in pair["sides"].values() if entry["job_id"]]
    assert len(job_ids) == len(set(job_ids)) == 7


def test_a_result_that_no_longer_validates_shows_no_score(client, paired, monkeypatch):
    """LABELED TEST HOOK: the M18 validator refuses the wild type result of A, as for tampered evidence."""
    refused = paired["jobs"]["A", "wild_type_reference"]["output_handles"][0]
    original = docking_bundle.validated_result

    def validate(run, handle):
        if handle == refused:
            raise docking_bundle.DockingEvidenceError("labeled refusal")
        return original(run, handle)

    monkeypatch.setattr(docking_bundle, "validated_result", validate)
    pair = _body(client, paired)["pairs"][0]
    assert pair["both_published"] is False
    assert pair["sides"]["wild_type_reference"]["reason_code"] == "result_invalid"
    assert pair["sides"]["mutant"]["reason_code"] == "other_side_missing"
    assert all(entry["score_kcal_mol"] is None and entry["result_handle"] is None
               for entry in pair["sides"].values())


# ----------------------------------------------------------------- no difference, no rank, no chosen pair
def test_no_difference_rank_or_choice_in_the_payload(client, paired):
    body = _body(client, paired)
    keys = _keys(body, set())
    assert not [key for key in keys if FORBIDDEN_KEY.search(key)], keys
    for value in mutation_model_reads.PAIR_REASONS.values():
        assert not FORBIDDEN_TEXT.search(value), value
    assert set(mutation_model_reads.PAIR_REASONS) == {
        "not_submitted", "job_not_finished", "job_failed", "job_cancelled", "job_interrupted", "result_invalid",
        "other_side_missing", "no_modes"}
    # the only numbers per side are the stored score, the mode number and the submission sequence
    for pair in body["pairs"]:
        for entry in pair["sides"].values():
            numbers = {key for key, value in entry.items() if isinstance(value, (int, float)) and
                       not isinstance(value, bool)}
            assert numbers <= {"score_kcal_mol", "score_mode", "submitted_seq"}


# ----------------------------------------------------------------- reads write nothing, refusals
def _forbid(*_args, **_kwargs):
    raise AssertionError("a read must not run a tool, a job or a process")


def test_read_leaves_the_event_log_unchanged_and_runs_nothing(client, paired, monkeypatch):
    rid, model = paired["rid"], paired["model"]
    _body(client, paired)
    before = _events_bytes(paired["root"], rid)
    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_supervise", _forbid)
        patch.setattr(JobQueue, "submit", _forbid)
        patch.setattr(JobQueue, "start", _forbid)
        patch.setattr(Run, "call", _forbid)
        patch.setattr(subprocess, "Popen", _forbid)
        first = _body(client, paired)
        second = _body(client, paired)
        assert canonical_json(first) == canonical_json(second)
        assert _pairs(client, rid, model, page=1).status_code == 422
        assert _pairs(client, rid, model, side="mutant").status_code == 422
    assert _events_bytes(paired["root"], rid) == before


def test_other_run_wrong_kind_and_unknown_handles_are_refused(client, paired, world):
    rid, model = paired["rid"], paired["model"]
    renamed = model.replace(rid, world["other_rid"])
    unknown = model[:-64] + "0" * 64
    for handle in (world["other_model"], renamed, unknown, "not-a-handle"):
        response = _pairs(client, rid, handle)
        assert response.status_code == 404 and response.json()["detail"]["error"] == "not_found", handle
    docking_result = paired["jobs"]["A", "mutant"]["output_handles"][0]
    for wrong in (world["candidate_set"], world["structure"], docking_result, paired["sdf"]):
        response = _pairs(client, rid, wrong)
        assert response.status_code == 422 and response.json()["detail"]["error"] == "input_invalid", wrong
    assert _pairs(client, "run_missing", model).status_code == 404
