"""M25 T5-B: a loop projection sent through the unchanged M24 send path (spec .dryforge/spec.md 5.1-5.3, 3.2 sends,
7, 9.3, 11, 12): ``jev_sends.run_send`` with the loop check inside the approval callback (409 ``loop_send_invalid``),
``EgressGate.request_science`` with the loop body / reply parser, ``_finish`` storing ``jev_loop_choice@1``, the send
records with their ``loop`` key and ``GET /jev/sends/{send_id}`` re-validating the loop proposal.

Inputs:
* REAL product run (built once per module, every test on an events-only copy): public 1UBQ prepared by the unmodified
  cheap tools, a real M20 set (ILE44, 19 candidates), the labelled synthetic phenol SDF, a real M24
  ``build_jev_projection`` object, and ONE real M21 model (PDBFixer + OpenMM job through ``JobQueue``; a missing engine
  FAILS, never skips) of candidate I44W under the loop setup used below; a dry-run run with the same cheap objects.
  Loops are made by the real creation admission and projections by the real ``build_jev_loop_projection`` tool.
* Every HTTP exchange is an ``httpx.MockTransport`` (``jev_send_fixture.Fake``) with the inert sentinel credential;
  replies are fixture replies, never provider output; nothing opens a socket or reads ``.env``.
* LABELLED stand-ins and fault injection (marked where used): ``approve`` / ``abandon`` / ``ended`` write the T6 route
  events (adopting the stored model, abandoning its docking, ending the loop); ``forged`` stores a loop projection
  built by the pure builders without the tool (another loop id, or an iteration the tool would refuse); tampered
  proposals; an M21 job submitted and cancelled outside the loop.

Expected values are written from the spec: the closed refusal names and their order, the M24 record keys, the body
bytes from the stored projection, the M24 reservation formula, the stored first-criteria alias.
"""
from __future__ import annotations

import ast
import copy
import json
import math
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from jev_send_fixture import SENTINEL, USAGE, Fake, new_send_id, no_secret, reply, run_bytes
from ligand_job_fixture import import_file, run_job
from test_jev_loops_api import I44, PHENOL, UBQ, protein_body

from mw import jev_constants as J
from mw import jev_loop_constants as L
from mw import jev_loop_projection as LP
from mw import jev_loop_store, jev_loops
from mw import jev_projection as P
from mw import jev_sends as S
from mw import mutation_model_constants as MC
from mw.api import app as api_module
from mw.jobs.queue import JobQueue
from mw.tools.registry import ToolContext
from mw.tools.structural import _parse
from mw.workspace import new_run

MW = Path(__file__).resolve().parents[1] / "mw"
RID, DRY = "run_m25_loop_sends", "run_m25_loop_sends_dry"
JSON_HEADERS = {"content-type": "application/json"}
M24_SEND_KEYS = {"schema", "send_id", "status", "reason_code", "projection_handle", "source", "kind", "question_id",
                 "selection_count", "body_sha256", "body_bytes", "audit_id", "requested_model", "served_model",
                 "usage", "choice_handle", "late", "late_reason", "approved_event_seq", "outcome_event_seq"}
SETTLED_USAGE = {"input_tokens": 3000, "output_tokens": 20, "external_tokens": 3020, "cost": 0.001}


# ---------------------------------------------------------------- the template runs (built once)


def _cheap_objects(run) -> dict:
    loaded = run.call("load_structure", {"source": str(UBQ), "model_index": 0}).handle
    prepared = run.call("prepare_structure", {"structure": loaded}).handle
    source = run.call("generate_mutation_candidates", {
        "structure": prepared, "sources": {"pocket": None, "ligand_shell": None, "residues": [I44]}}).handle
    indexes = [row["index"] for row in run.store.load(source)["candidates"]]
    return {"set": source, "indexes": indexes}


def _template(root: Path) -> dict:
    run = new_run(root, run_id=RID, dry_run=False)
    world = _cheap_objects(run)
    world["phenol"] = import_file(run, "ligand_sdf", "phenol.sdf", PHENOL)
    indexes = world["indexes"]
    world["m24"] = run.call(J.TOOL, {"source": world["set"], "candidates": [indexes[0], indexes[3]]}).handle
    setup = jev_loop_store.normalize_setup("protein", _body(world, str(uuid.uuid4()), [17, 3], 2)["setup"],
                                           world["set"])
    model = run_job(run, MC.PROTOCOL, jev_loop_store.model_request(setup, world["set"], indexes[17]), timeout_s=120)
    assert model["status"] == "done", model                    # one real M21 model of I44W (the engines are present)
    dry = new_run(root, run_id=DRY, dry_run=True)
    world["dry"] = _cheap_objects(dry)
    world["logs"] = {rid: (root / rid / "events.jsonl").read_bytes() for rid in (RID, DRY)}
    return world


def _body(world, loop_id, positions, cap, *, goal="exploit", seed=11) -> dict:
    body = protein_body({"ubq_set": world["set"], "phenol": world["phenol"], "indexes": world["indexes"]},
                        loop_id=loop_id, goal=goal, loop_seed=seed, iteration_cap=cap)
    body["pool"]["candidates"] = [world["indexes"][at] for at in positions]
    return body


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    return _template(tmp_path_factory.mktemp("jev_loop_sends"))


@pytest.fixture
def world(template, tmp_path, monkeypatch):
    """Events-only copies of both template runs served by the product app."""
    root = tmp_path / "runs"
    for rid, raw in template["logs"].items():
        (root / rid).mkdir(parents=True)
        (root / rid / "events.jsonl").write_bytes(raw)
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    monkeypatch.setattr(api_module, "SCIENCE_GATE", Fake().gate)
    api_module.RUNS.clear()
    out = {**template, "root": root, "monkeypatch": monkeypatch, "run": api_module._run(RID),
           "client": TestClient(api_module.app, base_url="http://127.0.0.1")}
    yield out
    api_module.RUNS.clear()


@pytest.fixture(autouse=True)
def no_active_sends():
    S.ACTIVE_SENDS.clear()
    yield
    assert not S.ACTIVE_SENDS
    S.ACTIVE_SENDS.clear()


# ---------------------------------------------------------------- helpers


X, A, B, C = 17, 3, 0, 9          # positions in the set's candidate list: I44W (modelled), I44?, I44A, I44?


def make_loop(world, positions=(X, A, B, C), cap=3, *, goal="exploit", seed=11) -> str:
    loop_id = str(uuid.uuid4())
    record = jev_loop_store.create(world["run"], _body(world, loop_id, positions, cap, goal=goal, seed=seed),
                                   send_active=False)
    assert record["current"]["action"] == "select"
    return loop_id


def project(world, loop_id, iteration=1) -> str:
    return world["run"].call(L.TOOL, {"loop_id": loop_id, "iteration": iteration}).handle


def events(run) -> list[dict]:
    return list(run.events.read())


def of_type(run, kind) -> list[dict]:
    return [event for event in events(run) if event["type"] == kind]


def consent(world, enabled=True) -> None:
    S.set_consent(world["run"], enabled)


def post(world, fake, projection, *, send_id=None, body_sha256=None, run_id=RID):
    """``POST /runs/{rid}/jev/sends`` with ``fake`` as the science gate."""
    world["monkeypatch"].setattr(api_module, "SCIENCE_GATE", fake.gate)
    run = api_module._run(run_id)
    body = {"send_id": send_id or new_send_id(), "projection": projection,
            "body_sha256": body_sha256 or run.store.load(projection)["body_sha256"], "confirm": J.CONFIRM}
    return world["client"].post(f"/runs/{run_id}/jev/sends", content=json.dumps(body).encode(), headers=JSON_HEADERS)


def criteria(world, projection) -> list[str]:
    return LP.criteria_aliases(world["run"].store.load(projection))


def first_alias(world, projection) -> Fake:
    """A fake provider that picks the first not-yet-computed alias (fixture reply)."""
    alias = criteria(world, projection)[0]
    return Fake(lambda request: reply(alias, confidence=0.5, probabilities={alias: 0.5}))


def read(world, loop_id):
    run = world["run"]
    return jev_loop_store.read_loop(jev_loop_store.LoopReadView(run), loop_id,
                                    budget=jev_loop_store.remaining_budget(run.budget_snapshot()))


def keys_of(world, loop_id) -> dict:
    return jev_loop_store.candidate_keys(jev_loop_store.created_payload(events(world["run"]), loop_id))


def approve(world, loop_id, iteration, step, ref, call_key, units=1) -> None:
    """LABELLED stand-in for the T6 compute route's approval event (the spec 6.1 payload)."""
    world["run"].events.append(L.EVENT_COMPUTE_APPROVED, loop_id=loop_id, iteration=iteration, step=step,
                               candidate_ref=ref, decided_by="human", proposal_handle=None, call_key=call_key,
                               units=units, approved_by=L.APPROVED_BY)


def adopt_and_abandon(world, loop_id, iteration) -> int:
    """LABELLED stand-ins for the T6 routes: the iteration adopts I44W's stored model (no unit) and abandons its
    docking, so the iteration started and is done (I44W ``not_run``, a computed candidate)."""
    ref = world["indexes"][X]
    approve(world, loop_id, iteration, "model", ref, keys_of(world, loop_id)[ref]["model"], units=0)
    world["run"].events.append(L.EVENT_DOCKING_ABANDONED, loop_id=loop_id, iteration=iteration, candidate_ref=ref)
    return ref


def ended(world, loop_id) -> None:
    """LABELLED SYNTHETIC ``jev_loop_ended`` (the T6 end route writes the real one with its summary)."""
    world["run"].events.append(L.EVENT_ENDED, loop_id=loop_id, end_reason="ended_by_user",
                               result_handle=f"obj://{RID}/{L.RESULT_KIND}/" + "e" * 64)


def forged(world, loop_id, iteration, states, *, ordinal=0, seed=11, goal="exploit", run=None) -> str:
    """LABELLED fault injection: a well-formed loop projection made by the pure builders from the stored set and
    structure (as the tool makes one) and stored without the tool. ``states``: {position: state}."""
    run = run or world["run"]
    content = run.store.load(world["set"] if run is world["run"] else world["dry"]["set"])
    structure = _parse(ToolContext(store=run.store, call_id="t5b_forged"), content["structure"]["handle"])
    rows = [{"ref": content["candidates"][at]["index"], "state": state, "score_kcal_mol": None}
            for at, state in states.items()]
    wire, selection = LP.build_loop_mutation_wire(content, rows, structure, goal=goal, loop_seed=seed,
                                                  iteration=iteration, send_ordinal=ordinal)
    projection = LP.build_loop_projection_content(
        "mutation", world["set"] if run is world["run"] else world["dry"]["set"], wire, selection, loop_id=loop_id,
        loop_seed=seed, iteration=iteration, send_ordinal=ordinal,
        structure={"handle": content["structure"]["handle"], "model_number": content["structure"]["model_number"]})
    return run.store.put(L.PROJECTION_KIND, L.PROJECTION_SCHEMA, projection, produced_by="synthetic_forgery").handle


def science_reserved(run) -> list[dict]:
    """The science reservations (the template's M21 job reserved an expensive unit, without an audit id)."""
    return [event for event in of_type(run, "budget_reserved") if "audit_id" in event]


def prepared_body(run, audit_id) -> bytes:
    prepared = next(event for event in of_type(run, "egress") if event["audit_id"] == audit_id
                    and event["stage"] == "prepared")
    return P.canonical_ascii(prepared["body"])


# ---------------------------------------------------------------- the loop send goes through the M24 path


def test_a_loop_send_is_one_approved_m24_send_and_its_proposal_is_the_selection(world):
    run = world["run"]
    loop_id = make_loop(world)
    handle = project(world, loop_id)
    content = run.store.load(handle)
    consent(world)
    preview = world["client"].post(f"/runs/{RID}/jev/preview", content=json.dumps({"projection": handle}).encode(),
                                   headers=JSON_HEADERS).json()
    assert preview["loop_blocks"] == [] and preview["blocked_by"] == []
    alias = criteria(world, handle)[0]
    fake = Fake(lambda request: reply(alias, confidence=0.123456789, probabilities={alias: 0.9999999999}))
    send_id = new_send_id()
    before = len(events(run))
    response = post(world, fake, handle, send_id=send_id)
    assert response.status_code == 200, response.text
    record = response.json()
    # one request whose bytes are the preview string, the prepared audit body and the stored projection's body
    assert len(fake.requests) == 1 and fake.key_reads == 1
    sent = fake.requests[0].content
    assert sent == preview["body"].encode("ascii") == prepared_body(run, record["audit_id"])
    assert sent == LP.loop_projection_body(content)[1] and P.body_sha256(sent) == content["body_sha256"]
    assert fake.requests[0].headers["authorization"] == f"Bearer {SENTINEL}"
    # the M24 event order: approval first, the dispatch, the outcome last
    new = events(run)[before:]
    types = [event["type"] for event in new]
    assert types[0] == J.EVENT_APPROVED and types[-1] == J.EVENT_OUTCOME and types.count(J.EVENT_DISPATCH) == 1
    reserved = next(event for event in new if event["type"] == "budget_reserved")
    tokens = min(50_000, 4_096 + math.ceil(content["body_bytes"] * 2 / 3))   # the M24 formula, written out
    assert (reserved["external_tokens"], reserved["usd"]) == (tokens, 0.10)
    # the record: the M24 record plus the projection's loop reference
    assert set(record) == M24_SEND_KEYS | {"loop"}
    assert record["loop"] == {"loop_id": loop_id, "iteration": 1, "send_ordinal": 0} == content["loop"]
    assert (record["status"], record["reason_code"], record["kind"], record["question_id"]) == (
        "completed", None, "mutation", "mutation_loop_choice@1")
    assert record["source"] == {"handle": world["set"], "schema": "mutation_candidate_set@1"}
    assert (record["body_sha256"], record["body_bytes"]) == (content["body_sha256"], content["body_bytes"])
    assert record["selection_count"] == len(content["selection"]) and record["usage"] == SETTLED_USAGE
    # the stored proposal: jev_loop_choice@1, valid against its projection and set, the answer as received
    meta = run.store.meta(record["choice_handle"])
    assert (meta["kind"], meta["schema"]) == (L.CHOICE_KIND, L.CHOICE_SCHEMA)
    choice = run.store.load(record["choice_handle"])
    source = S.source_content(run, content)
    assert LP.validated_loop_choice(choice, content, source) == choice
    assert choice["answer"]["choice_alias"] == alias and choice["answer"]["list_position"] == 1
    assert choice["answer"]["confidence"] == 0.123456789 and choice["answer"]["probabilities"] == {alias: 0.9999999999}
    assert choice["send"] == {"send_id": send_id, "audit_id": record["audit_id"]} and choice["usage"] == SETTLED_USAGE
    assert not [event for event in new if event["type"] == "object_created" and event["kind"] == J.CHOICE_KIND]
    # reads: detail re-validates the proposal; list and status show the loop send
    detail = world["client"].get(f"/runs/{RID}/jev/sends/{send_id}").json()
    assert detail == {**record, "choice": choice, "local_display": choice["answer"]["local_display"]}
    assert world["client"].get(f"/runs/{RID}/jev/sends").json() == [record]
    status = world["client"].get(f"/runs/{RID}/jev/status").json()
    assert (status["used"], status["remaining"], status["send_in_progress"]) == (1, 9, False)
    # the loop record: the first completed, not-late answer is iteration 1's selection
    state = read(world, loop_id)
    iteration = state.record["iterations"][0]
    assert (iteration["phase"], state.record["current"]["action"]) == ("awaiting_compute", "compute")
    assert iteration["sends"] == [{"send_id": send_id, "status": "completed", "send_ordinal": 0,
                                   "proposal_handle": record["choice_handle"], "late": False}]
    chosen = choice["answer"]["local_ref"]["candidate_index"]
    admitted = jev_loops.compute_admission(state, iteration=1, proposal=record["choice_handle"],
                                           capability_available=True)
    assert (admitted["outcome"], admitted["candidate_ref"], admitted["decided_by"]) == ("approve", chosen, "jev")
    assert SENTINEL.encode() not in run_bytes(run) and no_secret(record, detail, status, preview)


def test_the_route_order_check_request_preview_replay_active_then_the_loop_check(world):
    run = world["run"]
    loop_id = make_loop(world)
    handle = project(world, loop_id)
    consent(world)
    send_id = new_send_id()
    first = post(world, first_alias(world, handle), handle, send_id=send_id).json()
    assert first["status"] == "completed"
    count = len(events(run))
    # the same send_id again: the recorded send, before any loop check (which would now say selection_done)
    again = Fake()
    replay = post(world, again, handle, send_id=send_id)
    assert replay.status_code == 200 and replay.json() == first
    assert len(events(run)) == count and again.requests == [] and again.key_reads == 0
    # M24 request checks and preview_mismatch come before the loop check: nothing written
    bad = world["client"].post(f"/runs/{RID}/jev/sends", headers=JSON_HEADERS, content=json.dumps({
        "send_id": new_send_id(), "projection": handle, "body_sha256": first["body_sha256"],
        "confirm": "yes"}).encode())
    assert bad.status_code == 422
    mismatch = post(world, Fake(), handle, body_sha256="0" * 64)
    assert mismatch.status_code == 409 and mismatch.json()["detail"]["error"] == "preview_mismatch"
    assert len(events(run)) == count
    # an active send of the run comes before the loop check
    S.begin_send(RID, "another-send")
    try:
        busy = post(world, Fake(), handle)
    finally:
        S.end_send(RID, "another-send")
    assert busy.status_code == 409 and busy.json()["detail"]["error"] == "send_in_progress"
    assert len(events(run)) == count
    # then the loop check
    refused = post(world, Fake(), handle)
    assert refused.status_code == 409 and refused.json()["detail"]["reason"] == "selection_done"
    assert {event["type"] for event in events(run)[count:]} <= {"wall_charged"}


# ---------------------------------------------------------------- every loop send refusal, nothing recorded


def _loop_not_found(world):
    return forged(world, str(uuid.uuid4()), 1, {X: "pending", A: "pending", B: "pending"})


def _loop_ended(world):
    loop_id = make_loop(world)
    consent(world)
    handle = project(world, loop_id)
    assert post(world, Fake(lambda r: httpx.Response(500, json={"usage": USAGE})), handle).json()["status"] == \
        "failed"                                   # its ordinal no longer matches either: loop_ended comes first
    ended(world, loop_id)
    return handle


def _iteration_mismatch(world):
    loop_id = make_loop(world)
    return forged(world, loop_id, 2, {X: "pending", A: "pending", B: "pending", C: "pending"})


def _selection_done(world):
    loop_id = make_loop(world)
    handle = project(world, loop_id)
    consent(world)
    assert post(world, first_alias(world, handle), handle).json()["status"] == "completed"
    return handle


def _phase_invalid(world):
    loop_id = make_loop(world)
    handle = project(world, loop_id)
    run, ref = world["run"], world["indexes"][A]
    setup = jev_loop_store.created_payload(events(run), loop_id)["setup"]
    approve(world, loop_id, 1, "model", ref, keys_of(world, loop_id)[ref]["model"])
    job = JobQueue(run).submit(MC.PROTOCOL, jev_loop_store.model_request(setup, world["set"], ref), timeout_s=120)
    assert job["status"] == "queued"               # approved, waiting in the queue: the iteration is running
    return handle


def _cap_reached(world):
    loop_id = make_loop(world, (X, A, B), cap=1)
    adopt_and_abandon(world, loop_id, 1)
    return forged(world, loop_id, 2, {X: "not_run", A: "pending", B: "pending"})


def _too_few_candidates(world):
    loop_id = make_loop(world, (X, A), cap=2)
    adopt_and_abandon(world, loop_id, 1)
    return forged(world, loop_id, 2, {X: "pending", A: "pending"})


def _state_changed(world):
    loop_id = make_loop(world)
    handle = project(world, loop_id)
    run, ref = world["run"], world["indexes"][B]
    setup = jev_loop_store.created_payload(events(run), loop_id)["setup"]
    queue = JobQueue(run)                         # outside the loop: a same-key job cancelled before it started
    job = queue.submit(MC.PROTOCOL, jev_loop_store.model_request(setup, world["set"], ref), timeout_s=120)
    assert queue.request_cancel(job["job_id"])["job"]["status"] == "cancelled"
    return handle


def _ordinal_mismatch(world):
    loop_id = make_loop(world)
    handle = project(world, loop_id)
    consent(world)
    record = post(world, Fake(lambda r: httpx.Response(500, json={"usage": USAGE})), handle).json()
    assert (record["status"], record["reason_code"]) == ("failed", "provider_http_error")
    return handle


REFUSALS = {"loop_not_found": _loop_not_found, "loop_ended": _loop_ended, "iteration_mismatch": _iteration_mismatch,
            "selection_done": _selection_done, "phase_invalid": _phase_invalid, "cap_reached": _cap_reached,
            "too_few_candidates": _too_few_candidates, "state_changed": _state_changed,
            "ordinal_mismatch": _ordinal_mismatch}


def test_the_refusal_states_cover_the_closed_loop_send_reasons():
    assert tuple(REFUSALS) == L.LOOP_SEND_REASONS


@pytest.mark.parametrize("reason", L.LOOP_SEND_REASONS)
def test_every_loop_send_refusal_is_409_and_records_nothing(reason, world):
    run = world["run"]
    handle = REFUSALS[reason](world)
    consent(world)
    before = events(run)
    reserved = run.budget_snapshot()["external_tokens"]["used"]
    fake = Fake()
    response = post(world, fake, handle)
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert set(detail) == {"error", "message", "reason"}
    assert (detail["error"], detail["reason"]) == (L.LOOP_SEND_INVALID, reason)
    new = events(run)[len(before):]
    assert {event["type"] for event in new} <= {"wall_charged"}, [event["type"] for event in new]
    assert fake.requests == [] and fake.key_reads == 0
    assert run.budget_snapshot()["external_tokens"]["used"] == reserved
    assert S.list_sends(events(run)) == S.list_sends(before)


def test_a_loop_projection_in_a_dry_run_run_names_no_loop_and_never_reads_the_key(world):
    dry = api_module._run(DRY)
    handle = forged(world, str(uuid.uuid4()), 1, {X: "pending", A: "pending"}, run=dry)
    fake = Fake()
    before = events(dry)
    response = post(world, fake, handle, run_id=DRY)
    assert response.status_code == 409 and response.json()["detail"]["reason"] == "loop_not_found"
    assert {event["type"] for event in events(dry)[len(before):]} <= {"wall_charged"}
    assert fake.requests == [] and fake.key_reads == 0


def test_consent_off_is_the_m24_rejection_after_the_approval_and_reads_no_key(world):
    run = world["run"]
    loop_id = make_loop(world)
    handle = project(world, loop_id)
    fake = Fake()
    record = post(world, fake, handle).json()           # a new run: science consent was never enabled
    assert (record["status"], record["reason_code"], record["loop"]["send_ordinal"]) == ("rejected", "consent_off", 0)
    assert fake.requests == [] and fake.key_reads == 0
    assert not science_reserved(run) and not of_type(run, J.EVENT_DISPATCH)
    denied = [event for event in of_type(run, "egress") if event["stage"] == "denied"]
    assert len(denied) == 1 and denied[0]["reason_code"] == "consent_off"
    # nothing dispatched: the same projection may be sent again once consent is on
    consent(world)
    assert post(world, first_alias(world, handle), handle).json()["status"] == "completed"


# ---------------------------------------------------------------- the gate's loop reply parser


def test_a_computed_alias_or_probability_key_is_response_invalid_at_the_gate(world):
    run = world["run"]
    loop_id = make_loop(world, (X, A, B), cap=3)
    modelled = adopt_and_abandon(world, loop_id, 1)
    consent(world)
    for number in range(2):
        handle = project(world, loop_id, iteration=2)                # each dispatch: a new order, new aliases
        content = run.store.load(handle)
        computed = next(item["alias"] for item in content["selection"] if item["ref"] == modelled)
        assert next(item["state"] for item in content["selection"] if item["alias"] == computed) == "not_run"
        pending = LP.criteria_aliases(content)
        answer = (reply(computed) if number == 0 else
                  reply(pending[0], probabilities={pending[0]: 0.5, computed: 0.5}))   # fixture replies
        record = post(world, Fake(lambda request, answer=answer: answer), handle).json()
        assert (record["status"], record["reason_code"], record["choice_handle"]) == (
            "failed", "response_invalid", None)
        assert record["usage"] == SETTLED_USAGE                      # the usage is settled all the same
        assert record["loop"] == {"loop_id": loop_id, "iteration": 2, "send_ordinal": number}
    assert not [event for event in of_type(run, "object_created") if event["kind"] in (L.CHOICE_KIND, J.CHOICE_KIND)]
    settled = of_type(run, "egress_budget_settled")
    assert len(settled) == 2 and all(event["actual"]["external_tokens"] == 3020 for event in settled)
    assert read(world, loop_id).record["iterations"][1]["phase"] == "awaiting_selection"


def test_the_send_ordinal_moves_with_each_dispatch_and_reorders_the_next_projection(world):
    run = world["run"]
    loop_id = make_loop(world)
    consent(world)
    first = project(world, loop_id)
    assert post(world, Fake(lambda r: httpx.Response(500, json={"usage": USAGE})), first).json()["status"] == "failed"
    second = project(world, loop_id)
    one, two = run.store.load(first), run.store.load(second)
    assert (one["loop"]["send_ordinal"], two["loop"]["send_ordinal"]) == (0, 1) and first != second
    pool = jev_loop_store.created_payload(events(run), loop_id)["pool"]["candidates"]
    for content, ordinal in ((one, 0), (two, 1)):
        assert [item["ref"] for item in content["selection"]] == LP.shuffled_refs(
            pool, loop_seed=11, iteration=1, send_ordinal=ordinal)
    assert [item["ref"] for item in one["selection"]] != [item["ref"] for item in two["selection"]]
    assert post(world, first_alias(world, second), second).json()["status"] == "completed"


@pytest.mark.parametrize(("name", "answer", "reason"), [
    ("model_mismatch", lambda alias: reply(alias, model="typesafe/jev-1.14-20261001"), "model_mismatch"),
    ("missing_model", lambda alias: reply(alias, drop_model=True), "missing_model"),
    ("http_error", lambda alias: reply(alias, status=503), "provider_http_error")])
def test_failed_replies_make_no_proposal(world, name, answer, reason):
    run = world["run"]
    loop_id = make_loop(world)
    handle = project(world, loop_id)
    consent(world)
    alias = criteria(world, handle)[0]
    record = post(world, Fake(lambda request: answer(alias)), handle).json()
    assert (record["status"], record["reason_code"], record["choice_handle"]) == ("failed", reason, None), name
    assert not [e for e in of_type(run, "object_created") if e["kind"] == L.CHOICE_KIND]
    assert read(world, loop_id).record["iterations"][0]["phase"] == "awaiting_selection"


def test_a_reply_without_usage_is_a_proposal_and_stops_every_later_send(world):
    run = world["run"]
    loop_id = make_loop(world)
    handle = project(world, loop_id)
    consent(world)
    alias = criteria(world, handle)[0]
    record = post(world, Fake(lambda request: reply(alias, usage=None)), handle).json()
    assert record["status"] == "completed" and record["usage"] == {key: None for key in S.USAGE_KEYS}
    choice = run.store.load(record["choice_handle"])
    assert choice["usage"] == record["usage"] and run.egress_stop_reason == "usage_unknown"
    m24 = post(world, Fake(), world["m24"]).json()           # the stop state is the run's, shared with M24 sends
    assert (m24["status"], m24["reason_code"]) == ("rejected", "egress_stopped") and "loop" not in m24


# ---------------------------------------------------------------- late replies


@pytest.mark.parametrize("interrupt", ["consent_off", "cancel"])
def test_a_late_reply_is_kept_but_never_the_selection(world, interrupt):
    run = world["run"]
    loop_id = make_loop(world)
    handle = project(world, loop_id)
    consent(world)
    alias = criteria(world, handle)[0]

    def slow(request):   # the interruption lands while the request is in flight
        if interrupt == "consent_off":
            S.set_consent(run, False)
        else:
            run.cancel()
        return reply(alias, confidence=0.4)

    record = post(world, Fake(slow), handle).json()
    reason = "consent_off" if interrupt == "consent_off" else "run_cancelled"
    assert (record["status"], record["late"], record["late_reason"]) == ("completed", True, reason)
    choice = run.store.load(record["choice_handle"])
    assert choice["arrival"] == {"late": True, "late_reason": reason} and choice["limitations"][-1] == J.J7
    assert jev_loop_store.load_proposals(jev_loop_store.LoopReadView(run), jev_loop_store.created_payload(
        events(run), loop_id)) == {record["choice_handle"]: choice}
    state = read(world, loop_id)
    assert state.record["iterations"][0]["sends"][0]["late"] is True
    dispatched = of_type(run, J.EVENT_DISPATCH)[-1]["seq"]
    later = {event["type"] for event in events(run) if event["seq"] > dispatched}
    assert not later & {"tool_called", "job_submitted", L.EVENT_COMPUTE_APPROVED, "approval_requested"}
    if interrupt == "cancel":
        assert (state.record["status"], state.record["end_reason"]) == ("ended", "run_cancelled")
        return
    assert state.record["iterations"][0]["phase"] == "awaiting_selection"   # not the iteration's selection
    refused = jev_loops.compute_admission(state, iteration=1, proposal=record["choice_handle"],
                                          capability_available=True)
    assert refused["reason_code"] == "proposal_late"
    consent(world)                                       # consent on again: a new send of iteration 1 is allowed
    fresh = project(world, loop_id)
    assert run.store.load(fresh)["loop"]["send_ordinal"] == 1
    second = post(world, first_alias(world, fresh), fresh).json()
    assert (second["status"], second["late"]) == ("completed", False)
    assert read(world, loop_id).record["iterations"][0]["proposal_handle"] is None   # chosen but not yet approved
    assert read(world, loop_id).record["current"]["action"] == "compute"


# ---------------------------------------------------------------- shared reservation, settlement and send cap


def test_the_ten_send_cap_and_the_budget_are_shared_with_m24_sends(world):
    run = world["run"]
    loop_id = make_loop(world)
    consent(world)
    failing = Fake(lambda request: httpx.Response(500, json={"usage": USAGE}))
    expected = []
    for number in range(10):
        if number % 2:
            handle = project(world, loop_id)
            record = post(world, failing, handle).json()
            assert (record["status"], record["loop"]["send_ordinal"]) == ("failed", number // 2)
        else:
            handle = world["m24"]
            record = post(world, Fake(lambda request: reply("m01")), handle).json()
            assert record["status"] == "completed" and "loop" not in record and set(record) == M24_SEND_KEYS
        expected.append(min(50_000, 4_096 + math.ceil(run.store.load(handle)["body_bytes"] * 2 / 3)))
    assert [event["external_tokens"] for event in science_reserved(run)] == expected
    assert len(of_type(run, "egress_budget_settled")) == 10
    assert run.budget_snapshot()["external_tokens"]["used"] == 10 * 3020
    status = world["client"].get(f"/runs/{RID}/jev/status").json()
    assert (status["used"], status["remaining"]) == (10, 0)
    over_loop, over_m24 = Fake(), Fake()
    loop_record = post(world, over_loop, project(world, loop_id)).json()
    m24_record = post(world, over_m24, world["m24"]).json()
    for record, fake in ((loop_record, over_loop), (m24_record, over_m24)):
        assert (record["status"], record["reason_code"]) == ("rejected", "send_cap_exhausted")
        assert fake.requests == [] and fake.key_reads == 0
    assert loop_record["loop"]["send_ordinal"] == 5 and "loop" not in m24_record
    assert len(of_type(run, J.EVENT_DISPATCH)) == 10 and len(science_reserved(run)) == 10
    rows = world["client"].get(f"/runs/{RID}/jev/sends").json()
    assert [("loop" in row) for row in rows] == [False, True] * 5 + [True, False]
    assert all(set(row) == M24_SEND_KEYS for row in rows if row["projection_handle"] == world["m24"])


# ---------------------------------------------------------------- the stored proposal on read


def test_the_send_detail_refuses_a_tampered_loop_proposal(world):
    run = world["run"]
    loop_id = make_loop(world)
    handle = project(world, loop_id)
    consent(world)
    record = post(world, first_alias(world, handle), handle).json()
    assert world["client"].get(f"/runs/{RID}/jev/sends/{record['send_id']}").status_code == 200
    content = run.store.load(handle)
    good = run.store.load(record["choice_handle"])
    for edit in (lambda c: c["answer"].update(list_position=c["answer"]["list_position"] + 1),
                 lambda c: c.update(scientific_result=True), lambda c: c["answer"].update(rank=1)):
        tampered = copy.deepcopy(good)
        edit(tampered)
        forged_choice = run.store.put(L.CHOICE_KIND, L.CHOICE_SCHEMA, tampered).handle   # fault injection
        with pytest.raises(S.ChoiceInvalid):
            S.load_loop_choice(run, forged_choice, record["send_id"])
        # LABELLED SYNTHETIC send events naming the tampered object as their proposal
        send_id, audit_id = new_send_id(), f"eg_{uuid.uuid4().hex}"
        run.events.append(J.EVENT_APPROVED, send_id=send_id, projection_handle=handle,
                          body_sha256=content["body_sha256"], question_id=content["question"]["id"],
                          source_handle=content["source"]["handle"], selection_count=len(content["selection"]),
                          approved_by=J.APPROVED_BY)
        run.events.append(J.EVENT_OUTCOME, send_id=send_id, status="completed", reason_code=None,
                          audit_id=audit_id, requested_model=J.REQUEST_MODEL, served_model=J.SERVED_SNAPSHOT,
                          choice_handle=forged_choice, usage=None, late=False, late_reason=None)
        response = world["client"].get(f"/runs/{RID}/jev/sends/{send_id}")
        assert response.status_code == 422 and response.json()["detail"]["error"] == "method_evidence_invalid"
    with pytest.raises(S.JevSendError):                    # the M24 loader keeps refusing a loop proposal
        S.load_choice(run, record["choice_handle"])
    assert S.load_loop_choice(run, record["choice_handle"], record["send_id"]) == good


# ---------------------------------------------------------------- a proposal counts only for its own send


def synthetic_send(world, projection, choice, *, send_id, audit_id, body_sha256=None, late_reason=None) -> None:
    """LABELLED SYNTHETIC send events (as ``run_send`` / ``_finish`` write them) whose outcome names ``choice``."""
    run = world["run"]
    content = run.store.load(projection)
    run.events.append(J.EVENT_APPROVED, send_id=send_id, projection_handle=projection,
                      body_sha256=body_sha256 or content["body_sha256"], question_id=content["question"]["id"],
                      source_handle=content["source"]["handle"], selection_count=len(content["selection"]),
                      approved_by=J.APPROVED_BY)
    run.events.append(J.EVENT_DISPATCH, send_id=send_id, audit_id=audit_id)
    if late_reason is not None:
        S.set_consent(run, False)
    run.events.append(J.EVENT_OUTCOME, send_id=send_id, status="completed", reason_code=None, audit_id=audit_id,
                      requested_model=J.REQUEST_MODEL, served_model=J.SERVED_SNAPSHOT, choice_handle=choice,
                      usage=SETTLED_USAGE, late=late_reason is not None, late_reason=late_reason)


def stored_choice(world, projection, *, ref_position=None, send_id, audit_id, late_reason=None) -> str:
    """A proposal made by the product builder for ``projection`` (fault injection: stored without a send)."""
    run = world["run"]
    content = run.store.load(projection)
    pending = LP.criteria_aliases(content)
    alias = pending[0] if ref_position is None else next(
        item["alias"] for item in content["selection"] if item["ref"] == world["indexes"][ref_position])
    choice = LP.build_loop_choice(projection, content, S.source_content(run, content), send_id=send_id,
                                  audit_id=audit_id, answer={"choice_alias": alias, "confidence": None,
                                                             "probabilities": None},
                                  served_model=J.SERVED_SNAPSHOT, usage=SETTLED_USAGE,
                                  late=late_reason is not None, late_reason=late_reason)
    return run.store.put(L.CHOICE_KIND, L.CHOICE_SCHEMA, choice).handle


def _projection_swap(world, loop_id):
    """P1 lists B as not yet computed; B's same-key job is then cancelled outside the loop; P2 (same iteration and
    send ordinal) leaves B out. The send of P2 names a proposal made from P1 that chose B."""
    run = world["run"]
    p1 = project(world, loop_id)
    ref = world["indexes"][B]
    setup = jev_loop_store.created_payload(events(run), loop_id)["setup"]
    queue = JobQueue(run)
    job = queue.submit(MC.PROTOCOL, jev_loop_store.model_request(setup, world["set"], ref), timeout_s=120)
    assert queue.request_cancel(job["job_id"])["job"]["status"] == "cancelled"
    p2 = project(world, loop_id)
    assert p2 != p1 and ref not in {item["ref"] for item in run.store.load(p2)["selection"]}
    send_id, audit_id = new_send_id(), f"eg_{uuid.uuid4().hex}"
    choice = stored_choice(world, p1, ref_position=B, send_id=send_id, audit_id=audit_id)
    synthetic_send(world, p2, choice, send_id=send_id, audit_id=audit_id)
    return send_id, choice


def _other_send_id(world, loop_id):
    handle = project(world, loop_id)
    send_id, audit_id = new_send_id(), f"eg_{uuid.uuid4().hex}"
    choice = stored_choice(world, handle, send_id=new_send_id(), audit_id=audit_id)
    synthetic_send(world, handle, choice, send_id=send_id, audit_id=audit_id)
    return send_id, choice


def _other_late_reason(world, loop_id):
    handle = project(world, loop_id)
    send_id, audit_id = new_send_id(), f"eg_{uuid.uuid4().hex}"
    choice = stored_choice(world, handle, send_id=send_id, audit_id=audit_id, late_reason="run_cancelled")
    synthetic_send(world, handle, choice, send_id=send_id, audit_id=audit_id, late_reason="consent_off")
    return send_id, choice


def _other_body(world, loop_id):
    handle = project(world, loop_id)
    send_id, audit_id = new_send_id(), f"eg_{uuid.uuid4().hex}"
    choice = stored_choice(world, handle, send_id=send_id, audit_id=audit_id)
    synthetic_send(world, handle, choice, send_id=send_id, audit_id=audit_id, body_sha256="0" * 64)
    return send_id, choice


def _matching(world, loop_id):
    handle = project(world, loop_id)
    send_id, audit_id = new_send_id(), f"eg_{uuid.uuid4().hex}"
    choice = stored_choice(world, handle, send_id=send_id, audit_id=audit_id)
    synthetic_send(world, handle, choice, send_id=send_id, audit_id=audit_id)
    return send_id, choice


SEND_MISMATCH = {"projection_swap": _projection_swap, "other_send_id": _other_send_id,
                 "other_late_reason": _other_late_reason, "other_approved_body": _other_body}


@pytest.mark.parametrize("name", sorted(SEND_MISMATCH))
def test_a_proposal_that_does_not_belong_to_its_send_is_no_selection_and_its_detail_is_refused(name, world):
    run = world["run"]
    loop_id = make_loop(world)
    send_id, choice = SEND_MISMATCH[name](world, loop_id)
    created = jev_loop_store.created_payload(events(run), loop_id)
    assert choice not in jev_loop_store.load_proposals(jev_loop_store.LoopReadView(run), created)
    response = world["client"].get(f"/runs/{RID}/jev_loops/{loop_id}")
    assert response.status_code == 200, response.text      # a forged input never blocks the loop read
    iteration = response.json()["iterations"][0]
    assert iteration["phase"] == "awaiting_selection"
    assert [(row["send_id"], row["status"], row["proposal_handle"]) for row in iteration["sends"]] == [
        (send_id, "completed", None)]
    detail = world["client"].get(f"/runs/{RID}/jev/sends/{send_id}")
    assert detail.status_code == 422 and detail.json()["detail"]["error"] == "method_evidence_invalid"
    with pytest.raises(S.ChoiceInvalid):
        S.load_loop_choice(run, choice, send_id)


def test_a_proposal_that_belongs_to_its_send_is_still_the_selection(world):
    run = world["run"]
    loop_id = make_loop(world)
    send_id, choice = _matching(world, loop_id)
    record = world["client"].get(f"/runs/{RID}/jev_loops/{loop_id}").json()
    assert record["iterations"][0]["phase"] == "awaiting_compute"
    assert record["iterations"][0]["sends"][0]["proposal_handle"] == choice
    detail = world["client"].get(f"/runs/{RID}/jev/sends/{send_id}")
    assert detail.status_code == 200 and detail.json()["choice"] == run.store.load(choice)
    with pytest.raises(S.ChoiceInvalid):                    # the right proposal, asked for another send
        S.load_loop_choice(run, choice, new_send_id())


# ---------------------------------------------------------------- source structure


def test_the_gate_branches_only_by_projection_schema_and_the_loop_modules_stay_apart():
    science = (MW / "egress/science.py").read_text()
    for name in ("validated_loop_projection", "loop_projection_body", "parse_loop_choice"):
        assert f"LP.{name}" in science, name
    tree = ast.parse((MW / "jev_sends.py").read_text())
    admit = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "admit")
    line = {ast.unparse(node.func): node.lineno for node in ast.walk(admit) if isinstance(node, ast.Call)}
    assert line["_approved"] < line["_loop_send_refusal"] < line["run.events.append"]   # check, then the approval
    for name in ("jev_loop_store.py", "jev_loops.py", "jev_loop_projection.py", "jev_loop_constants.py"):
        text = (MW / name).read_text()
        imported = {alias.name for node in ast.walk(ast.parse(text)) if isinstance(node, ast.ImportFrom)
                    for alias in node.names} | {node.module or "" for node in ast.walk(ast.parse(text))
                                                if isinstance(node, ast.ImportFrom)}
        assert not {item for item in imported if "jev_sends" in item or "egress" in item}, name
