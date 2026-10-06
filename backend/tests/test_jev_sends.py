"""M24 T4 consent, approval, send records and the ``jev_choice@1`` proposal (``mw.jev_sends``; spec 5, 6, 7).

Every HTTP exchange is an ``httpx.MockTransport`` (``jev_send_fixture.Fake``) and every credential the inert sentinel;
no socket is opened and ``.env`` is never read. Inputs are the REAL template runs of ``jev_send_fixture`` (public 1UBQ
M20 set, real M17 set, real ``build_jev_projection`` objects). Monkeypatched stores, caps and stored-object edits are
fault injection, marked where used.
"""
from __future__ import annotations

import asyncio
import copy
import json
import shutil
import uuid

import httpx
import pytest
from jev_send_fixture import (
    SENTINEL,
    USAGE,
    Fake,
    approval,
    body_of,
    clone,
    events,
    new_send_id,
    no_secret,
    projection_of,
    reopen,
    reply,
    run_bytes,
    send,
    templates,
)

from mw import jev_constants as J
from mw import jev_projection as P
from mw import jev_sends as S
from mw.core.errors import ToolFailure
from mw.egress.viewer import request_viewer
from mw.runtime.guards import BudgetLimits
from mw.viewer_intents import create_session, projected_state, request_intent, set_online
from mw.workspace import new_run

SEND_KEYS = {"schema", "send_id", "status", "reason_code", "projection_handle", "source", "kind", "question_id",
             "selection_count", "body_sha256", "body_bytes", "audit_id", "requested_model", "served_model", "usage",
             "choice_handle", "late", "late_reason", "approved_event_seq", "outcome_event_seq"}
STATUS_KEYS = {"schema", "enabled", "policy", "send_cap", "used", "remaining", "budget", "egress_stop_reason",
               "dry_run", "cancelled", "question_ids", "send_in_progress", "request_model", "allowed_served_model",
               "destination"}
PREVIEW_KEYS = {"schema", "projection_handle", "kind", "source", "question", "body", "body_sha256", "body_bytes",
                "selection", "selection_sent", "reservation", "send_cap", "used", "remaining", "budget_remaining",
                "blocked_by", "previous_sends"}
CHOICE_KEYS = {"schema", "method_version", "label", "scientific_result", "send", "source", "projection", "question",
               "requested_model", "served_model", "selection", "answer", "usage", "arrival", "limitations"}


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return templates(tmp_path_factory.getbasetemp() / "jev_send_templates")


@pytest.fixture
def mut(base, tmp_path):
    return clone(base["mutation"], tmp_path / "runs")


@pytest.fixture
def lig(base, tmp_path):
    return clone(base["ligand"], tmp_path / "runs")


@pytest.fixture
def dry(base, tmp_path):
    return clone(base["dry"], tmp_path / "runs")


@pytest.fixture(autouse=True)
def no_active_sends():
    S.ACTIVE_SENDS.clear()
    yield
    assert not S.ACTIVE_SENDS
    S.ACTIVE_SENDS.clear()


def fields(event):
    return {key: value for key, value in event.items() if key not in ("seq", "ts", "type")}


def refused(call, code, status):
    with pytest.raises(S.JevSendError) as caught:
        call()
    assert (caught.value.code, caught.value.http_status) == (code, status), caught.value.message
    return caught.value


def current(run):
    return list(run.events.read())


# ---------------------------------------------------------------- consent


def test_consent_is_one_run_event_and_leaves_the_viewer_mode_alone(mut):
    run = mut["run"]
    assert S.consent_enabled(current(run)) is False and S.status_for(run, current(run))["enabled"] is False
    before = len(events(run))
    status = S.set_consent(run, True)
    new = events(run)[before:]
    assert [e["type"] for e in new] == [J.EVENT_CONSENT]
    assert fields(new[0]) == {"enabled": True, "policy": "jev_science@1", "send_cap": 10,
                              "request_model": J.REQUEST_MODEL, "allowed_served_model": J.SERVED_SNAPSHOT,
                              "destination": J.DESTINATION}
    assert status["schema"] == J.STATUS_SCHEMA and status["enabled"] is True
    assert run.egress_config["mode"] == "local_only"
    again = reopen(mut)
    assert again.egress_config["mode"] == "local_only" and S.consent_enabled(current(again)) is True
    assert S.set_consent(run, False)["enabled"] is False and S.consent_enabled(current(run)) is False
    before = len(events(run))
    for value in ("yes", 1, None):
        refused(lambda value=value: S.set_consent(run, value), "input_invalid", 422)
    assert len(events(run)) == before


def test_consent_follows_the_last_valid_event_only():
    def consent(enabled, policy=J.CONSENT_POLICY):
        return {"type": J.EVENT_CONSENT, "enabled": enabled, "policy": policy}
    assert S.consent_enabled([]) is False
    assert S.consent_enabled([consent(True)]) is True
    assert S.consent_enabled([consent(True), consent(False)]) is False
    assert S.consent_enabled([consent(True), {"type": "viewer_consent_changed", "enabled": True}]) is True
    assert S.consent_enabled([consent(True), consent(True, "viewer_model@1")]) is False   # fail closed
    assert S.consent_enabled([consent(True), consent("true")]) is False


def test_dry_run_cannot_enable_consent_and_rejects_sends(dry):
    run = dry["run"]
    before = len(events(run))
    refused(lambda: S.set_consent(run, True), "dry_run", 412)
    assert len(events(run)) == before
    fake = Fake()
    record = send(dry, fake)
    assert (record["status"], record["reason_code"]) == ("rejected", "dry_run")
    assert fake.requests == [] and fake.key_reads == 0


def _viewer_intent(world):
    run = world["run"]
    scene = create_session(run, client_instance_id=str(uuid.uuid4()), scene_generation=1,
                           structure_handle=world["prepared"])
    intent_id, internal, _ = request_intent(run, client_instance_id=scene["client_instance_id"],
                                            viewer_session_id=scene["viewer_session_id"], scene_generation=1,
                                            request_id=str(uuid.uuid4()), prompt="Show surface")
    return intent_id, internal


def test_viewer_consent_and_science_consent_grant_nothing_to_each_other(base, tmp_path):
    viewer_only = clone(base["mutation"], tmp_path / "viewer_only")
    set_online(viewer_only["run"], True)
    fake = Fake()
    record = send(viewer_only, fake)
    assert (record["status"], record["reason_code"]) == ("rejected", "consent_off") and fake.key_reads == 0
    science_only = clone(base["mutation"], tmp_path / "science_only")
    S.set_consent(science_only["run"], True)
    intent_id, internal = _viewer_intent(science_only)
    viewer = Fake(lambda request: pytest.fail("viewer request sent"))
    outcome = asyncio.run(request_viewer(viewer.gate, science_only["run"], projected_state(internal, "Show surface"),
                                         intent_id))
    assert outcome.reason_code == "local_only" and viewer.requests == [] and viewer.key_reads == 0
    assert science_only["run"].egress_config["mode"] == "local_only"


# ---------------------------------------------------------------- an approved send


@pytest.mark.parametrize("which", ["mutation", "ligand"])
def test_an_approved_send_records_approval_outcome_and_one_choice(which, mut, lig, tmp_path):
    world = mut if which == "mutation" else lig
    run = world["run"]
    S.set_consent(run, True)
    content = projection_of(world)
    if which == "mutation":   # fixture reply values: any rounding or float re-formatting would change them
        answer = {"choice": "m01", "confidence": 0.123456789,
                  "probabilities": {"m03": 1e-9, "m01": 0.9999999999, "m02": 0.1 + 0.2}}
    else:
        answer = {"choice": "c02"}
    replies = []

    def respond(request):
        response = reply(**answer)
        replies.append(response.content)   # the exact bytes the gate receives
        return response
    fake = Fake(respond)
    send_id = new_send_id()
    before = len(events(run))
    record = send(world, fake, send_id=send_id)
    assert set(record) == SEND_KEYS and record["schema"] == J.SEND_SCHEMA
    assert fake.requests[0].content == body_of(world)
    assert fake.requests[0].headers["authorization"] == f"Bearer {SENTINEL}"
    new = events(run)[before:]
    approved = [e for e in new if e["type"] == J.EVENT_APPROVED]
    outcome = [e for e in new if e["type"] == J.EVENT_OUTCOME]
    assert new[0]["type"] == J.EVENT_APPROVED and new[-1]["type"] == J.EVENT_OUTCOME and len(outcome) == 1
    assert fields(approved[0]) == {"send_id": send_id, "projection_handle": world["projection"],
                                   "body_sha256": content["body_sha256"], "question_id": content["question"]["id"],
                                   "source_handle": world["source"], "selection_count": len(content["selection"]),
                                   "approved_by": "human"}
    assert fields(approved[0]) == approval(world, send_id)   # the gate tests' approver records the same event
    usage = {"input_tokens": 3000, "output_tokens": 20, "external_tokens": 3020, "cost": 0.001}
    assert fields(outcome[0]) == {"send_id": send_id, "status": "completed", "reason_code": None,
                                  "audit_id": record["audit_id"], "requested_model": J.REQUEST_MODEL,
                                  "served_model": J.SERVED_SNAPSHOT, "choice_handle": record["choice_handle"],
                                  "usage": usage, "late": False, "late_reason": None}
    assert record == {"schema": J.SEND_SCHEMA, "send_id": send_id, "status": "completed", "reason_code": None,
                      "projection_handle": world["projection"],
                      "source": {"handle": world["source"], "schema": J.SOURCE_SCHEMAS[which]}, "kind": which,
                      "question_id": content["question"]["id"], "selection_count": len(content["selection"]),
                      "body_sha256": content["body_sha256"], "body_bytes": content["body_bytes"],
                      "audit_id": record["audit_id"], "requested_model": J.REQUEST_MODEL,
                      "served_model": J.SERVED_SNAPSHOT, "usage": usage, "choice_handle": record["choice_handle"],
                      "late": False, "late_reason": None, "approved_event_seq": approved[0]["seq"],
                      "outcome_event_seq": outcome[0]["seq"]}
    assert S.send_record(current(run), send_id) == record and S.list_sends(current(run)) == [record]
    # the proposal object
    meta = run.store.meta(record["choice_handle"])
    assert (meta["kind"], meta["schema"]) == (J.CHOICE_KIND, J.CHOICE_SCHEMA)
    choice = S.load_choice(run, record["choice_handle"])
    assert set(choice) == CHOICE_KEYS and choice == run.store.load(record["choice_handle"])
    source = S.source_content(run, content)
    chosen = next(item for item in content["selection"] if item["alias"] == answer["choice"])
    if which == "mutation":
        row = next(row for row in source["candidates"] if row["index"] == chosen["candidate_index"])
        residue = source["positions"][chosen["position_index"]]["residue"]
        display = {"residue": {key: residue[key] for key in J.ALLOWED_RESIDUE}, "from": row["from"], "to": row["to"]}
        assert display["residue"]["seq_auth"] == 1 and display["from"] == "M"
        local_ref = {"candidate_index": chosen["candidate_index"], "position_index": chosen["position_index"]}
    else:
        display = {"smiles": next(r["smiles"] for r in source["candidates"] if r["id"] == chosen["candidate_id"])}
        local_ref = {"candidate_id": chosen["candidate_id"]}
    assert choice == {
        "schema": J.CHOICE_SCHEMA, "method_version": J.CHOICE_METHOD_VERSION, "label": "JEV 판정(모델 선택)",
        "scientific_result": False, "send": {"send_id": send_id, "audit_id": record["audit_id"]},
        "source": content["source"],
        "projection": {"handle": world["projection"], "wire_sha256": content["wire_sha256"],
                       "body_sha256": content["body_sha256"], "body_bytes": content["body_bytes"]},
        "question": {"id": content["question"]["id"], "key": J.QUESTION_KEY,
                     "instructions_sha256": J.instructions_sha256(content["question"]["id"])},
        "requested_model": J.REQUEST_MODEL, "served_model": J.SERVED_SNAPSHOT,
        "selection": content["selection"],
        "answer": {"choice_alias": answer["choice"], "local_ref": local_ref, "local_display": display,
                   "confidence": answer.get("confidence"), "probabilities": answer.get("probabilities")},
        "usage": usage, "arrival": {"late": False, "late_reason": None},
        "limitations": J.limitations_for(which, False)}
    if which == "mutation":   # the reply's floats, unchanged: no rounding, no re-formatting, also after JSON
        replied = json.loads(replies[0])["answers"][J.QUESTION_KEY]
        sha = record["choice_handle"].rsplit("/", 1)[1]
        stored_raw = json.loads((run.run_dir / "objects" / f"{sha}.json").read_bytes())["answer"]
        replayed = S.load_choice(reopen(world, tmp_path / "replayed"), record["choice_handle"])["answer"]
        for got in (choice["answer"], stored_raw, replayed, json.loads(json.dumps(choice["answer"]))):
            assert got["confidence"] == replied["confidence"] == 0.123456789
            assert got["probabilities"] == replied["probabilities"] == answer["probabilities"]
            for alias, value in answer["probabilities"].items():
                assert type(got["probabilities"][alias]) is float and repr(got["probabilities"][alias]) == repr(value)
        assert answer["probabilities"]["m02"] != 0.3 and round(answer["probabilities"]["m01"], 2) == 1.0
    assert S.preview_for(run, world["projection"], current(run))["previous_sends"] == 1
    assert SENTINEL.encode() not in run_bytes(run) and no_secret(record, choice)


def test_a_rejected_send_writes_its_denied_audit_and_a_rejected_outcome(mut):
    run = mut["run"]
    fake = Fake()
    record = send(mut, fake)
    assert (record["status"], record["reason_code"]) == ("rejected", "consent_off")
    assert record["choice_handle"] is None and record["usage"] is None and record["requested_model"] is None
    denied = [e for e in events(run) if e["type"] == "egress"]
    assert [(e["stage"], e["audit_id"]) for e in denied] == [("denied", record["audit_id"])]
    outcome = events(run, J.EVENT_OUTCOME)[-1]
    assert fields(outcome) == {"send_id": record["send_id"], "status": "rejected", "reason_code": "consent_off",
                               "audit_id": record["audit_id"], "requested_model": None, "served_model": None,
                               "choice_handle": None, "usage": None, "late": False, "late_reason": None}
    assert fake.key_reads == 0 and not [e for e in events(run, "object_created") if e["kind"] == J.CHOICE_KIND]


# ---------------------------------------------------------------- approval request rules


def test_a_body_hash_other_than_the_preview_is_refused_without_events(mut):
    run = mut["run"]
    S.set_consent(run, True)
    before = len(events(run))
    fake = Fake()
    refused(lambda: send(mut, fake, body_sha256="0" * 64), "preview_mismatch", 409)
    refused(lambda: send(mut, fake, body_sha256=P.body_sha256(body_of(mut, "other_projection"))),
            "preview_mismatch", 409)
    assert len(events(run)) == before and fake.requests == [] and fake.key_reads == 0


def test_the_same_send_id_is_idempotent_and_a_different_projection_conflicts(mut):
    run = mut["run"]
    S.set_consent(run, True)
    fake = Fake()
    send_id = new_send_id()
    first = send(mut, fake, send_id=send_id)
    count = len(events(run))
    assert send(mut, fake, send_id=send_id) == first
    assert len(events(run)) == count and len(fake.requests) == 1
    refused(lambda: send(mut, fake, which="other_projection", send_id=send_id), "send_id_conflict", 409)
    assert len(events(run)) == count
    rejected_id = new_send_id()
    S.set_consent(run, False)
    rejected = send(mut, fake, send_id=rejected_id)
    count = len(events(run))
    assert send(mut, fake, send_id=rejected_id) == rejected and len(events(run)) == count


@pytest.mark.parametrize("override", [
    {"confirm": "yes"}, {"confirm": None}, {"confirm": "SEND_TO_JEV"},
    {"send_id": "not-a-uuid"}, {"send_id": str(uuid.uuid1())}, {"send_id": str(uuid.uuid4()).upper()},
    {"send_id": None}, {"send_id": 5},
    {"body_sha256": "abc"}, {"body_sha256": "A" * 64}, {"body_sha256": None},
    {"projection": 5}, {"projection": None}, {"projection": ["obj://x"]},
    {"rank": 1}, {"run": "x"}, {"gate": "x"},
], ids=lambda value: json.dumps(value)[:40])
def test_malformed_requests_are_input_invalid_without_events(mut, override):
    run = mut["run"]
    S.set_consent(run, True)
    before = len(events(run))
    fake = Fake()
    refused(lambda: send(mut, fake, **override), "input_invalid", 422)
    assert len(events(run)) == before and fake.requests == []


def test_a_projection_not_of_this_run_or_not_a_valid_projection(mut, lig):
    run = mut["run"]
    S.set_consent(run, True)
    before = len(events(run))
    fake = Fake()
    digest = "0" * 64
    for handle in (f"obj://{mut['run_id']}/jev_projection/{digest}", lig["projection"], "not a handle"):
        refused(lambda handle=handle: send(mut, fake, projection=handle, body_sha256=digest), "not_found", 404)
    error = refused(lambda: send(mut, fake, projection=mut["source"], body_sha256=digest), "input_invalid", 422)
    assert error.detail == {"reason_code": "projection_invalid"}
    forged = copy.deepcopy(projection_of(mut))   # fault injection: a stored projection that does not validate
    forged["wire"]["candidates"][0]["rank"] = 1
    handle = run.store.put(J.PROJECTION_KIND, J.PROJECTION_SCHEMA, forged).handle
    before = len(events(run))
    error = refused(lambda: send(mut, fake, projection=handle, body_sha256=forged["body_sha256"]),
                    "input_invalid", 422)
    assert error.detail == {"reason_code": "projection_invalid"}
    assert len(events(run)) == before and fake.requests == []


# ---------------------------------------------------------------- one send at a time, in-progress reads


def test_a_send_in_flight_blocks_other_sends_and_reads_as_in_progress(mut):
    run = mut["run"]
    S.set_consent(run, True)
    send_id, other_id, seen = new_send_id(), new_send_id(), {}
    request = {"projection": mut["projection"], "body_sha256": P.body_sha256(body_of(mut)), "confirm": J.CONFIRM}

    async def in_flight(http_request):
        evs = current(run)
        seen["record"] = S.send_record(evs, send_id)
        seen["status"] = S.status_for(run, evs)
        seen["preview"] = S.preview_for(run, mut["projection"], evs)
        try:
            await S.run_send(run, fake.gate, send_id=other_id, **request)
        except S.JevSendError as exc:
            seen["other"] = (exc.code, exc.http_status)
        seen["same"] = await S.run_send(run, fake.gate, send_id=send_id, **request)
        return reply("m01")

    fake = Fake(in_flight)
    record = send(mut, fake, send_id=send_id)
    assert seen["record"]["status"] == "in_progress" and seen["record"]["reason_code"] is None
    assert seen["record"]["outcome_event_seq"] is None and seen["record"]["choice_handle"] is None
    assert seen["record"]["audit_id"] == record["audit_id"]
    assert seen["status"]["send_in_progress"] is True and "send_in_progress" in seen["preview"]["blocked_by"]
    assert seen["other"] == ("send_in_progress", 409) and seen["same"]["status"] == "in_progress"
    assert record["status"] == "completed" and len(fake.requests) == 1
    assert not [e for e in events(run) if e.get("send_id") == other_id]
    assert S.status_for(run, current(run))["send_in_progress"] is False


def test_a_busy_run_owner_writes_nothing_and_frees_the_send(mut):
    run = mut["run"]
    S.set_consent(run, True)
    before = len(events(run))
    fake = Fake()
    send_id = new_send_id()
    with run._owner(), pytest.raises(ToolFailure) as caught:   # another mutation holds the run owner
        send(mut, fake, send_id=send_id)
    assert caught.value.detail.get("busy") is True
    assert len(events(run)) == before and fake.requests == [] and fake.key_reads == 0 and not S.ACTIVE_SENDS
    assert send(mut, fake, send_id=send_id)["status"] == "completed"   # nothing was recorded, so it is fresh


def test_a_cancelled_server_task_leaves_delivery_unknown_and_stops_egress(mut):
    run = mut["run"]
    S.set_consent(run, True)
    send_id = new_send_id()

    async def scenario():
        entered = asyncio.Event()

        async def hang(request):
            entered.set()
            await asyncio.Event().wait()
        fake = Fake(hang)
        task = asyncio.create_task(S.run_send(run, fake.gate, send_id=send_id, projection=mut["projection"],
                                              body_sha256=P.body_sha256(body_of(mut)), confirm=J.CONFIRM))
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()   # e.g. server shutdown while the request is in flight
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    record = S.send_record(current(run), send_id)
    assert (record["status"], record["reason_code"], record["outcome_event_seq"]) == (
        "failed", "delivery_unknown", None)
    assert run.egress_stop_reason == "usage_unknown"
    assert S.preview_for(run, mut["projection"], current(run))["blocked_by"] == ["egress_stopped"]
    assert reopen(mut).egress_stop_reason == "usage_unknown"


def test_the_same_projection_may_be_sent_again_as_a_new_send(mut):
    run = mut["run"]
    S.set_consent(run, True)
    first = send(mut, Fake(lambda request: reply("m01")))
    second = send(mut, Fake(lambda request: reply("m03", confidence=1)))
    assert first["status"] == second["status"] == "completed" and first["choice_handle"] != second["choice_handle"]
    assert S.list_sends(current(run)) == [first, second]
    assert S.load_choice(run, second["choice_handle"])["answer"]["confidence"] == 1
    status = S.status_for(run, current(run))
    assert (status["used"], status["remaining"]) == (2, 8)
    assert S.preview_for(run, mut["projection"], current(run))["previous_sends"] == 2


def test_the_ten_send_cap_counts_dispatches_failed_included_rejected_not(mut):
    run = mut["run"]
    assert send(mut, Fake())["reason_code"] == "consent_off"
    S.set_consent(run, True)
    for _ in range(9):
        record = send(mut, Fake(lambda request: httpx.Response(500, json={"usage": USAGE})))
        assert (record["status"], record["reason_code"]) == ("failed", "provider_http_error")
    assert send(mut, Fake())["status"] == "completed"
    status = S.status_for(run, current(run))
    assert (status["used"], status["remaining"], status["send_cap"]) == (10, 0, 10)
    assert "send_cap_exhausted" in S.preview_for(run, mut["projection"], current(run))["blocked_by"]
    over = Fake()
    record = send(mut, over)
    assert (record["status"], record["reason_code"]) == ("rejected", "send_cap_exhausted")
    assert over.requests == [] and over.key_reads == 0
    assert [r["status"] for r in S.list_sends(current(run))] == ["rejected", *["failed"] * 9, "completed", "rejected"]
    assert len(events(run, J.EVENT_DISPATCH)) == 10


# ---------------------------------------------------------------- late replies


@pytest.mark.parametrize("interrupt, reason", [
    ("consent_off", "consent_off"), ("off_then_on", "consent_off"), ("cancel", "run_cancelled"),
    ("cancel_and_consent_off", "run_cancelled")])
def test_a_valid_reply_after_cancel_or_consent_off_is_kept_and_marked_late(mut, interrupt, reason):
    run = mut["run"]
    S.set_consent(run, True)

    def slow(request):   # the interruption lands while the request is in flight
        if "consent_off" in interrupt or interrupt == "off_then_on":
            S.set_consent(run, False)
        if interrupt == "off_then_on":
            S.set_consent(run, True)
        if "cancel" in interrupt:
            run.cancel()
        return reply("m02", confidence=0.4)

    record = send(mut, Fake(slow))
    assert (record["status"], record["reason_code"], record["late"], record["late_reason"]) == (
        "completed", None, True, reason)
    choice = S.load_choice(run, record["choice_handle"])
    assert choice["arrival"] == {"late": True, "late_reason": reason}
    assert choice["limitations"] == J.limitations_for("mutation", True) and choice["limitations"][-1] == J.J7
    dispatched = events(run, J.EVENT_DISPATCH)[-1]["seq"]
    later = {e["type"] for e in events(run) if e["seq"] > dispatched}
    assert not later & {"tool_called", "job_submitted", "proposal_rejected", "approval_requested"}


def test_an_invalid_reply_after_cancel_is_failed_with_no_choice(mut):
    run = mut["run"]
    S.set_consent(run, True)

    def slow(request):
        run.cancel()
        return reply("m09")
    record = send(mut, Fake(slow))
    assert (record["status"], record["reason_code"], record["choice_handle"]) == ("failed", "response_invalid", None)
    assert (record["late"], record["late_reason"]) == (True, "run_cancelled")
    assert not [e for e in events(run, "object_created") if e["kind"] == J.CHOICE_KIND]


# ---------------------------------------------------------------- restart and events-only recovery


def test_restart_without_an_outcome_derives_delivery_unknown_or_outcome_not_recorded(mut, tmp_path, monkeypatch):
    run = mut["run"]
    S.set_consent(run, True)
    snapshot = tmp_path / "crash" / mut["run_id"]
    snapshot.mkdir(parents=True)
    send_id = new_send_id()

    def crash(request):   # the log while the request is in flight = a server death at this point
        shutil.copyfile(run.run_dir / "events.jsonl", snapshot / "events.jsonl")
        return reply("m01")
    live = send(mut, Fake(crash), send_id=send_id)
    restarted = new_run(tmp_path / "crash", run_id=mut["run_id"], dry_run=False)
    derived = S.send_record(current(restarted), send_id)
    assert (derived["status"], derived["reason_code"], derived["outcome_event_seq"]) == (
        "failed", "delivery_unknown", None)
    assert (derived["audit_id"], derived["requested_model"], derived["served_model"], derived["usage"],
            derived["choice_handle"]) == (live["audit_id"], J.REQUEST_MODEL, None, None, None)
    assert restarted.egress_stop_reason == "usage_unknown"
    # a reply that was received and settled but whose outcome was never written
    original = run.store.put

    def failing_put(kind, *args, **kwargs):
        if kind == J.CHOICE_KIND:
            raise OSError("disk full")   # fault injection
        return original(kind, *args, **kwargs)
    monkeypatch.setattr(run.store, "put", failing_put)
    lost_id = new_send_id()
    with pytest.raises(OSError):
        send(mut, Fake(lambda request: reply("m01")), send_id=lost_id)
    derived = S.send_record(current(run), lost_id)
    assert (derived["status"], derived["reason_code"], derived["served_model"]) == (
        "failed", "outcome_not_recorded", J.SERVED_SNAPSHOT)
    assert derived["usage"]["external_tokens"] == 3020 and derived["choice_handle"] is None
    assert run.egress_stop_reason is None


def test_send_records_and_choices_recover_from_events_only(mut, tmp_path):
    run = mut["run"]
    send(mut, Fake())                                   # rejected (consent off)
    S.set_consent(run, True)
    record = send(mut, Fake(lambda request: reply("m03", probabilities={"m01": 0.25})))
    original = S.list_sends(current(run))
    sha = record["choice_handle"].rsplit("/", 1)[1]
    raw = (run.run_dir / "objects" / f"{sha}.json").read_bytes()
    replayed = reopen(mut, tmp_path / "replayed")
    assert S.list_sends(current(replayed)) == original
    assert (replayed.run_dir / "objects" / f"{sha}.json").read_bytes() == raw
    assert S.load_choice(replayed, record["choice_handle"]) == S.load_choice(run, record["choice_handle"])
    assert replayed.egress_stop_reason is None


# ---------------------------------------------------------------- the proposal object is checked on every read


def _other_ref(choice, selection):
    other = next(item for item in selection if item["alias"] != choice["answer"]["choice_alias"])
    return {key: value for key, value in other.items() if key != "alias"}


CHOICE_TAMPER = {   # SYNTHETIC edits of a stored proposal
    "answer_rank": lambda c, s: c["answer"].update(rank=1),
    "top_best": lambda c, s: c.update(best="m01"),
    "top_score": lambda c, s: c.update(score=0.9),
    "scientific_result": lambda c, s: c.update(scientific_result=True),
    "label": lambda c, s: c.update(label="JEV 추천"),
    "alias_outside": lambda c, s: c["answer"].update(choice_alias="m09"),
    "probability_key_outside": lambda c, s: c["answer"].update(probabilities={"m09": 0.1}),
    "probability_range": lambda c, s: c["answer"].update(probabilities={"m01": 1.1}),
    "probabilities_ranked_list": lambda c, s: c["answer"].update(probabilities=[["m01", 0.9]]),
    "confidence_range": lambda c, s: c["answer"].update(confidence=-0.2),
    "local_ref_other": lambda c, s: c["answer"].update(local_ref=_other_ref(c, s)),
    "local_display_other": lambda c, s: c["answer"]["local_display"].update(to="W" if c["answer"]["local_display"]
                                                                              ["to"] != "W" else "A"),
    "late_without_reason": lambda c, s: c["arrival"].update(late=True),
    "reason_without_late": lambda c, s: c["arrival"].update(late_reason="consent_off"),
    "late_without_j7": lambda c, s: c.update(arrival={"late": True, "late_reason": "consent_off"}),
    "projection_hash": lambda c, s: c["projection"].update(body_sha256="0" * 64),
    "selection_reordered": lambda c, s: c.update(selection=c["selection"][::-1]),
    "served_model": lambda c, s: c.update(served_model="typesafe/jev-1.12-20250101"),
    "usage_negative": lambda c, s: c.update(usage={**c["usage"], "input_tokens": -1}),
    "send_id": lambda c, s: c["send"].update(send_id="x"),
    "instructions_hash": lambda c, s: c["question"].update(instructions_sha256="0" * 64),
}


@pytest.fixture
def stored_choice(mut):
    S.set_consent(mut["run"], True)
    record = send(mut, Fake(lambda request: reply("m01", confidence=0.5, probabilities={"m01": 0.5, "m02": 0.3})))
    content = projection_of(mut)
    return mut, record, S.load_choice(mut["run"], record["choice_handle"]), content, \
        S.source_content(mut["run"], content)


@pytest.mark.parametrize("name", sorted(CHOICE_TAMPER))
def test_validated_choice_refuses_tampered_proposals(name, stored_choice):
    world, _record, choice, content, source = stored_choice
    assert S.validated_choice(copy.deepcopy(choice), content, source) == choice
    tampered = copy.deepcopy(choice)
    CHOICE_TAMPER[name](tampered, content["selection"])
    with pytest.raises(S.ChoiceInvalid):
        S.validated_choice(tampered, content, source)
    handle = world["run"].store.put(J.CHOICE_KIND, J.CHOICE_SCHEMA, tampered).handle   # fault injection
    with pytest.raises(S.ChoiceInvalid):
        S.load_choice(world["run"], handle)


def test_a_late_proposal_with_j7_is_valid(stored_choice):
    _, _, choice, content, source = stored_choice
    late = copy.deepcopy(choice)
    late["arrival"] = {"late": True, "late_reason": "run_cancelled"}
    late["limitations"] = J.limitations_for("mutation", True)
    assert S.validated_choice(late, content, source) == late
    refused(lambda: S.load_choice(stored_choice[0]["run"], stored_choice[0]["projection"]), "input_invalid", 422)


# ---------------------------------------------------------------- status and preview reads


def test_status_and_preview_read_the_log_once_never_the_key(mut):
    run = mut["run"]
    evs = current(run)
    reads = []
    original = run.events.read
    run.events.read = lambda: reads.append(1) or original()
    try:
        status = S.status_for(run, evs)
        preview = S.preview_for(run, mut["projection"], evs)
    finally:
        run.events.read = original
    assert reads == []
    content = projection_of(mut)
    body = body_of(mut)
    assert set(status) == STATUS_KEYS and set(preview) == PREVIEW_KEYS
    assert status == {"schema": J.STATUS_SCHEMA, "enabled": False, "policy": J.CONSENT_POLICY, "send_cap": 10,
                      "used": 0, "remaining": 10,
                      "budget": {"external_tokens": {"used": 0, "limit": 120_000, "remaining": 120_000},
                                 "usd": {"used": 0, "limit": 2.0, "remaining": 2.0}},
                      "egress_stop_reason": None, "dry_run": False, "cancelled": False,
                      "question_ids": list(J.QUESTION_IDS), "send_in_progress": False,
                      "request_model": J.REQUEST_MODEL, "allowed_served_model": J.SERVED_SNAPSHOT,
                      "destination": J.DESTINATION}
    question_id = content["question"]["id"]
    assert preview == {
        "schema": J.PREVIEW_SCHEMA, "projection_handle": mut["projection"], "kind": "mutation",
        "source": content["source"],
        "question": {"id": question_id, "key": J.QUESTION_KEY, "type": "choice",
                     "instructions": J.INSTRUCTIONS[question_id],
                     "instructions_sha256": J.instructions_sha256(question_id)},
        "body": body.decode("ascii"), "body_sha256": content["body_sha256"], "body_bytes": len(body),
        "selection": content["selection"], "selection_sent": False,
        "reservation": {"external_tokens": J.reserve_tokens(len(body)), "usd": J.RESERVE_USD},
        "send_cap": 10, "used": 0, "remaining": 10,
        "budget_remaining": {"external_tokens": 120_000, "usd": 2.0},
        "blocked_by": ["consent_off"], "previous_sends": 0}
    assert len(preview["body"].encode("ascii")) == content["body_bytes"]


def test_preview_lists_every_blocking_reason_in_the_closed_order(mut, dry):
    assert S.preview_for(dry["run"], dry["projection"], current(dry["run"]))["blocked_by"] == ["dry_run", "consent_off"]
    run = mut["run"]
    S.set_consent(run, True)
    assert S.preview_for(run, mut["projection"], current(run))["blocked_by"] == []
    run.update_limits(BudgetLimits(**{**run.budget.limits.model_dump(), "usd": 0.05}))
    run.cancel()
    blocked = S.preview_for(run, mut["projection"], current(run))["blocked_by"]
    assert blocked == ["cancelled", "budget_exhausted"]
    assert set(blocked) <= set(J.PREVIEW_BLOCK_REASONS)
    status = S.status_for(run, current(run))
    assert status["cancelled"] is True and status["budget"]["usd"]["remaining"] == 0.05


def test_preview_shows_a_stopped_egress(mut):
    run = mut["run"]
    S.set_consent(run, True)
    assert send(mut, Fake(lambda request: reply("m01", usage=None)))["status"] == "completed"
    preview = S.preview_for(run, mut["projection"], current(run))
    assert preview["blocked_by"] == ["egress_stopped"]
    assert S.status_for(run, current(run))["egress_stop_reason"] == "usage_unknown"
    refused(lambda: S.preview_for(run, mut["source"], current(run)), "input_invalid", 422)
    refused(lambda: S.send_record(current(run), new_send_id()), "not_found", 404)
