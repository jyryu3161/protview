"""M24 T4 gate ``request_science`` (``mw.egress.science``) through ``EgressGate`` (spec .dryforge/spec.md 5).

Every HTTP exchange is an ``httpx.MockTransport`` (``jev_send_fixture.Fake``) and every credential the inert sentinel;
no socket is opened and ``.env`` is never read. Inputs are the REAL template runs of ``jev_send_fixture`` (public 1UBQ
M20 set, real M17 set, real ``build_jev_projection`` objects). Monkeypatched caps, clocks, audits and pins are fault
injection, marked where used. Every send here goes through an approval: ``jev_send_fixture.approver`` records the
``jev_send_approved`` event exactly as ``jev_sends.run_send``'s ``admit`` does (the gate has no path without one).
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import logging
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from jev_send_fixture import (
    RAW_ERROR,
    SENTINEL,
    USAGE,
    Fake,
    approver,
    audits,
    body_of,
    clone,
    events,
    new_send_id,
    no_secret,
    projection_of,
    reopen,
    reply,
    run_bytes,
    templates,
)

from mw import jev_constants as J
from mw import jev_projection as P
from mw import jev_sends as S
from mw.egress import gate as G
from mw.egress import science
from mw.egress.viewer import request_viewer
from mw.runtime.guards import BudgetLimits
from mw.viewer_intents import create_session, projected_state, request_intent, set_online
from mw.workspace import new_run

REPO = Path(__file__).resolve().parents[2]
MW = REPO / "backend/mw"
FIX = Path(__file__).resolve().parent / "fixtures"


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


def gate_send(world, fake, *, which="projection", send_id=None):
    send_id = send_id or new_send_id()
    return asyncio.run(fake.gate.request_science(world["run"], projection_of(world, which), send_id,
                                                 admit=approver(world, send_id, which)))


def stages(run, audit_id):
    return [event["stage"] for event in audits(run, audit_id)]


def tail_types(run, before):
    return [event["type"] + (f":{event['stage']}" if event["type"] == "egress" else "")
            for event in events(run)[before:]]


def limited(world, **limits):
    run = world["run"]
    run.update_limits(BudgetLimits(**{**run.budget.limits.model_dump(), **limits}))


# ---------------------------------------------------------------- accepted


def test_accepted_send_is_one_audited_reserved_and_settled_request_of_the_preview_bytes(mut, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    run = mut["run"]
    S.set_consent(run, True)
    content = projection_of(mut)
    # fixture reply values chosen so that any rounding or float re-formatting would change them
    probabilities = {"m01": 1e-9, "m02": 0.9999999999, "m03": 0.1 + 0.2}
    fake = Fake(lambda request: reply("m02", confidence=0.123456789, probabilities=probabilities))
    before = len(events(run))
    send_id = new_send_id()
    result = asyncio.run(fake.gate.request_science(run, content, send_id, admit=approver(mut, send_id)))
    assert isinstance(result, science.ScienceGateResult)
    assert (result.status, result.reason_code) == ("accepted", None)
    assert result.answer == {"choice_alias": "m02", "confidence": 0.123456789, "probabilities": probabilities}
    assert result.requested_model == J.REQUEST_MODEL and result.served_model == J.SERVED_SNAPSHOT
    assert result.usage == {"input_tokens": 3000, "output_tokens": 20, "external_tokens": 3020, "cost": 0.001}
    # one request, the exact bytes of the preview / projection body, the key only in the transport header
    assert len(fake.requests) == 1 and fake.key_reads == 1
    request = fake.requests[0]
    assert request.method == "POST" and str(request.url) == J.DESTINATION
    assert request.headers["authorization"] == f"Bearer {SENTINEL}"
    assert request.headers["content-type"] == "application/json"
    body, encoded = P.projection_body(content)
    preview = S.preview_for(run, mut["projection"], list(run.events.read()))
    assert request.content == encoded == preview["body"].encode("ascii") == body_of(mut)
    prepared = next(e for e in audits(run, result.audit_id) if e["stage"] == "prepared")
    assert P.canonical_ascii(prepared["body"]) == request.content and prepared["body"] == body
    assert prepared["payload_sha256"] == hashlib.sha256(request.content).hexdigest() == content["body_sha256"]
    assert prepared["projection_sha256"] == content["wire_sha256"]
    tokens = J.reserve_tokens(len(encoded))
    assert {key: prepared[key] for key in ("destination", "requested_model", "question_version", "reservation",
                                           "scope", "send_id", "transport_invoked", "sent")} == {
        "destination": J.DESTINATION, "requested_model": J.REQUEST_MODEL,
        "question_version": J.MUTATION_QUESTION_ID, "reservation": {"external_tokens": tokens, "usd": J.RESERVE_USD},
        "scope": "science", "send_id": send_id, "transport_invoked": False, "sent": False}
    # audit chain, reservation without an expensive-call axis, settlement, the dispatch event
    assert stages(run, result.audit_id) == ["prepared", "dispatch_started", "response_received", "settled"]
    assert all(e["scope"] == "science" and e["send_id"] == send_id for e in audits(run, result.audit_id))
    assert tail_types(run, before) == [
        J.EVENT_APPROVED, "budget_reserved", "egress:prepared", "egress:dispatch_started", "jev_science_dispatch_started",
        "wall_charged", "egress:response_received", "egress_budget_settled", "egress:settled", "wall_charged"]
    reserved = events(run, "budget_reserved")[-1]
    assert {k: v for k, v in reserved.items() if k not in ("seq", "ts", "type")} == {
        "audit_id": result.audit_id, "send_id": send_id, "external_tokens": tokens, "usd": J.RESERVE_USD}
    settled = events(run, "egress_budget_settled")[-1]
    assert settled["actual"] == {"external_tokens": 3020, "usd": 0.001} and settled["unknown_axes"] == []
    assert settled["delta"] == {"external_tokens": 3020 - tokens, "usd": 0.001 - J.RESERVE_USD}
    assert events(run, "jev_science_dispatch_started")[-1] | {"seq": 0, "ts": 0} == {
        "seq": 0, "ts": 0, "type": "jev_science_dispatch_started", "send_id": send_id, "audit_id": result.audit_id}
    received = next(e for e in audits(run, result.audit_id) if e["stage"] == "response_received")
    assert received["http_status"] == 200 and received["served_model"] == J.SERVED_SNAPSHOT
    assert run.egress_stop_reason is None and run.budget.expensive_calls == 0
    assert run.budget.external_tokens == 3020 and run.budget.usd == pytest.approx(0.001)
    assert reopen(mut).egress_stop_reason is None
    assert SENTINEL.encode() not in run_bytes(run) and no_secret(result)
    captured = capsys.readouterr()
    assert SENTINEL not in caplog.text and SENTINEL not in captured.out + captured.err


def test_accepted_ligand_send_without_confidence_or_probabilities(lig):
    run = lig["run"]
    S.set_consent(run, True)
    fake = Fake(lambda request: reply("c03"))
    result = gate_send(lig, fake)
    assert result.status == "accepted"
    assert result.answer == {"choice_alias": "c03", "confidence": None, "probabilities": None}
    assert fake.requests[0].content == body_of(lig)
    prepared = next(e for e in audits(run, result.audit_id) if e["stage"] == "prepared")
    assert prepared["question_version"] == J.LIGAND_QUESTION_ID
    state = json.loads(fake.requests[0].content)["state"]
    assert state["schema"] == "jev_ligand_candidates@1" and set(state) == set(J.ALLOWED_LIGAND_TOP)
    assert SENTINEL.encode() not in run_bytes(run)


def test_projection_content_that_does_not_validate_is_refused_before_any_event(mut):
    run = mut["run"]
    S.set_consent(run, True)
    content = projection_of(mut)
    content["wire"]["candidates"][0]["rank"] = 1   # fault injection: an edited projection
    before = len(events(run))
    fake = Fake()
    send_id = new_send_id()
    with pytest.raises(P.ProjectionInvalid):
        asyncio.run(fake.gate.request_science(run, content, send_id, admit=approver(mut, send_id)))
    assert len(events(run)) == before and fake.requests == [] and fake.key_reads == 0


def test_the_gate_delegate_is_the_science_function(mut, monkeypatch):
    seen = []

    async def fake_science(gate, run, content, send_id, *, admit):
        seen.append((gate, run, content, send_id, admit))
        return "ok"

    monkeypatch.setattr(science, "request_science", fake_science)
    gate = G.EgressGate(credential_resolver=lambda: pytest.fail("read"))
    admit = approver(mut, "s")
    assert asyncio.run(gate.request_science(mut["run"], {"x": 1}, "s", admit=admit)) == "ok"
    assert seen == [(gate, mut["run"], {"x": 1}, "s", admit)]
    with pytest.raises(TypeError):   # the delegate itself has no default either
        gate.request_science(mut["run"], {"x": 1}, "s")
    assert len(seen) == 1


# ---------------------------------------------------------------- no send without a recorded approval


def _untouched(world, fake, before, *, owner=False, hook_wrote=()):
    """Nothing of a send: no approval the gate accepted, audit, reservation, dispatch, key read or request.

    ``owner``: the hook ran under the run owner, whose exit always charges its activity time (one existing
    ``wall_charged``/``runtime_overhead`` accounting event, written for every owner entry; not a send step).
    ``hook_wrote``: event types the faulty hook itself appended."""
    run = world["run"]
    new = [(e["type"], e.get("reason")) for e in events(run)[before:]]
    overhead = [("wall_charged", "runtime_overhead")] if owner else []
    assert new in ([*[(t, None) for t in hook_wrote], *overhead], [(t, None) for t in hook_wrote]), new
    assert fake.requests == [] and fake.key_reads == 0
    assert not events(run, "budget_reserved") and not events(run, J.EVENT_DISPATCH) and not audits(run)
    assert not events(run, "egress_budget_settled") and not events(run, J.EVENT_OUTCOME)
    assert run.budget.external_tokens == 0 and run.budget.usd == 0


@pytest.mark.parametrize("via", ["gate", "module"])
@pytest.mark.parametrize("admit", ["missing", None, "admit", 5, {"admit": True}])
def test_without_a_callable_approval_hook_nothing_is_written_read_or_sent(mut, via, admit):
    run = mut["run"]
    S.set_consent(run, True)   # everything else would let this send through
    fake = Fake(lambda request: pytest.fail("sent without an approval"))
    before = len(events(run))
    call = fake.gate.request_science if via == "gate" else (
        lambda *args, **kwargs: science.request_science(fake.gate, *args, **kwargs))
    kwargs = {} if admit == "missing" else {"admit": admit}
    with pytest.raises(TypeError):
        asyncio.run(call(run, projection_of(mut), new_send_id(), **kwargs))
    _untouched(mut, fake, before)


def test_an_approval_hook_that_raises_sends_nothing(mut):
    run = mut["run"]
    S.set_consent(run, True)
    fake = Fake(lambda request: pytest.fail("sent after a failed approval"))
    before = len(events(run))

    def admit(events_seen):
        raise RuntimeError("approval refused")   # fault injection
    with pytest.raises(RuntimeError, match="approval refused"):
        asyncio.run(fake.gate.request_science(run, projection_of(mut), new_send_id(), admit=admit))
    _untouched(mut, fake, before, owner=True)


@pytest.mark.parametrize("hook", ["records_nothing", "other_send_id", "other_body", "other_question",
                                  "other_source", "other_count", "not_human", "other_projection_body"])
def test_an_approval_hook_that_does_not_record_this_approval_sends_nothing(mut, hook):
    run = mut["run"]
    S.set_consent(run, True)
    fake = Fake(lambda request: pytest.fail("sent without a matching approval"))
    send_id = new_send_id()
    admit = {   # fault injection: hooks that record no approval, or one that does not match this body
        "records_nothing": lambda events_seen: None,
        "other_send_id": approver(mut, new_send_id()),
        "other_body": approver(mut, send_id, body_sha256="0" * 64),
        "other_question": approver(mut, send_id, question_id=J.LIGAND_QUESTION_ID),
        "other_source": approver(mut, send_id, source_handle=mut["prepared"]),
        "other_count": approver(mut, send_id, selection_count=1),
        "not_human": approver(mut, send_id, approved_by="model"),
        "other_projection_body": approver(mut, send_id, which="other_projection"),
    }[hook]
    before = len(events(run))
    with pytest.raises(PermissionError):
        asyncio.run(fake.gate.request_science(run, projection_of(mut), send_id, admit=admit))
    _untouched(mut, fake, before, owner=True, hook_wrote=() if hook == "records_nothing" else (J.EVENT_APPROVED,))


# ---------------------------------------------------------------- rejections (first failure only)


def _rejected(world, fake, reason, *, keys=0, checkpoint=False):
    run = world["run"]
    before = len(events(run))
    send_id = new_send_id()
    result = gate_send(world, fake, send_id=send_id)
    assert (result.status, result.reason_code) == ("rejected", reason)
    assert result.answer is None and result.requested_model is None and result.usage is None
    new = events(run)[before:]
    denied = [e for e in new if e["type"] == "egress"]
    assert [(e["stage"], e["reason_code"], e["scope"], e["transport_invoked"], e["sent"]) for e in denied] == [
        ("denied", reason, "science", False, False)]
    assert denied[0]["audit_id"] == result.audit_id and denied[0]["send_id"] == send_id
    # the approval is the gate's first step: recorded before the refusal's audit, in log order
    approved = [e for e in new if e["type"] == J.EVENT_APPROVED]
    assert new[0] is approved[0] and len(approved) == 1 and approved[0]["send_id"] == send_id
    assert approved[0]["seq"] < denied[0]["seq"]
    assert not [e for e in new if e["type"] in ("budget_reserved", "jev_science_dispatch_started",
                                                "egress_budget_settled")]
    assert [e.get("axis") for e in new if e["type"] == "checkpoint"] == (["wall_clock_s"] if checkpoint else [])
    assert fake.requests == [] and fake.key_reads == keys
    assert SENTINEL.encode() not in run_bytes(run)
    return result


def test_dry_run_rejects_before_any_key_read(dry):
    _rejected(dry, Fake(), "dry_run")


def test_consent_off_rejects_before_any_key_read(mut):
    _rejected(mut, Fake(), "consent_off")          # a new run: never enabled
    S.set_consent(mut["run"], True)
    S.set_consent(mut["run"], False)
    _rejected(mut, Fake(), "consent_off")          # the last consent event decides


def test_cancelled_run_rejects(mut):
    S.set_consent(mut["run"], True)
    mut["run"].cancel()
    _rejected(mut, Fake(), "cancelled")


def test_egress_stop_rejects_every_later_send(mut):
    S.set_consent(mut["run"], True)
    first = gate_send(mut, Fake(lambda request: reply("m01", usage=None)))
    assert first.status == "accepted" and mut["run"].egress_stop_reason == "usage_unknown"
    _rejected(mut, Fake(), "egress_stopped")
    assert reopen(mut).egress_stop_reason == "usage_unknown"


def test_send_cap_counts_dispatch_events(mut, monkeypatch):
    S.set_consent(mut["run"], True)
    monkeypatch.setattr(J, "SEND_CAP", 1)   # fault injection: a cap of one (the real ten are in test_jev_sends.py)
    assert gate_send(mut, Fake()).status == "accepted"
    _rejected(mut, Fake(), "send_cap_exhausted")


@pytest.mark.parametrize("limits", [{"external_tokens": 4000}, {"usd": 0.05}])
def test_external_token_or_usd_reservation_over_the_limit_is_budget_exhausted(mut, limits):
    S.set_consent(mut["run"], True)
    limited(mut, **limits)
    _rejected(mut, Fake(), "budget_exhausted")


def test_exhausted_activity_time_is_budget_exhausted_with_a_checkpoint(mut):
    S.set_consent(mut["run"], True)
    limited(mut, wall_clock_s=0.001)
    _rejected(mut, Fake(), "budget_exhausted", checkpoint=True)


def test_pins_that_differ_from_the_gate_are_missing_configuration(mut, monkeypatch):
    S.set_consent(mut["run"], True)
    monkeypatch.setattr(J, "SERVED_SNAPSHOT", "typesafe/jev-1.12-20250101")   # fault injection: a drifted pin
    _rejected(mut, Fake(), "missing_configuration")
    monkeypatch.undo()
    monkeypatch.setattr(G, "DESTINATION", "https://example.invalid/decisions")
    _rejected(mut, Fake(), "missing_configuration")


@pytest.mark.parametrize("key", [None, "", "line\nbreak", 5, RuntimeError(f"resolver failed: {SENTINEL}")])
def test_missing_or_unusable_key_is_missing_credential_after_one_read(mut, key):
    S.set_consent(mut["run"], True)
    result = _rejected(mut, Fake(key=key), "missing_credential", keys=1)
    assert no_secret(result, events(mut["run"]))


def test_only_the_first_failing_step_is_reported(mut):
    run = mut["run"]
    limited(mut, external_tokens=10, wall_clock_s=0.001)
    run.cancel()
    _rejected(mut, Fake(), "consent_off")
    S.set_consent(run, True)
    _rejected(mut, Fake(), "cancelled")


def _reservation(world):
    return {"external_tokens": J.reserve_tokens(len(body_of(world))), "usd": J.RESERVE_USD}


def _usage_unknown_send(world):
    assert gate_send(world, Fake(lambda request: reply("m01", usage=None))).status == "accepted"
    assert world["run"].egress_stop_reason == "usage_unknown"


def _drift_pin(monkeypatch):
    monkeypatch.setattr(J, "SERVED_SNAPSHOT", "typesafe/jev-1.12-20250101")   # fault injection: a drifted pin


def _pair_dry_run_and_consent_off(world, monkeypatch):
    assert world["run"].dry_run is True   # a dry-run run can never enable science consent


def _pair_consent_off_and_cancelled(world, monkeypatch):
    world["run"].cancel()


def _pair_cancelled_and_egress_stopped(world, monkeypatch):
    S.set_consent(world["run"], True)
    _usage_unknown_send(world)
    world["run"].cancel()


def _pair_egress_stopped_and_send_cap(world, monkeypatch):
    monkeypatch.setattr(J, "SEND_CAP", 1)   # fault injection: a cap of one
    S.set_consent(world["run"], True)
    _usage_unknown_send(world)


def _pair_send_cap_and_time(world, monkeypatch):
    monkeypatch.setattr(J, "SEND_CAP", 1)   # fault injection: a cap of one
    S.set_consent(world["run"], True)
    assert gate_send(world, Fake()).status == "accepted"
    limited(world, wall_clock_s=0.001)


def _pair_time_and_reservation(world, monkeypatch):
    S.set_consent(world["run"], True)
    limited(world, wall_clock_s=0.001, usd=0.05)


def _pair_reservation_and_configuration(world, monkeypatch):
    S.set_consent(world["run"], True)
    limited(world, usd=0.05)
    _drift_pin(monkeypatch)


def _pair_configuration_and_credential(world, monkeypatch):
    S.set_consent(world["run"], True)
    _drift_pin(monkeypatch)


#        setup, fixture, reported reason, checkpoint (time step), the later condition that also holds
ADJACENT_PAIRS = {
    "dry_run>consent_off": (_pair_dry_run_and_consent_off, "dry", "dry_run", False, "consent_off"),
    "consent_off>cancelled": (_pair_consent_off_and_cancelled, "mut", "consent_off", False, "cancelled"),
    "cancelled>egress_stopped": (_pair_cancelled_and_egress_stopped, "mut", "cancelled", False, "egress_stopped"),
    "egress_stopped>send_cap": (_pair_egress_stopped_and_send_cap, "mut", "egress_stopped", False, "send_cap"),
    "send_cap>time": (_pair_send_cap_and_time, "mut", "send_cap_exhausted", False, "time"),
    "time>reservation": (_pair_time_and_reservation, "mut", "budget_exhausted", True, "reservation"),
    "reservation>configuration": (_pair_reservation_and_configuration, "mut", "budget_exhausted", False,
                                  "configuration"),
    "configuration>credential": (_pair_configuration_and_credential, "mut", "missing_configuration", False,
                                 "credential"),
}


def _later_holds(world, later):
    run = world["run"]
    seen = list(run.events.read())
    return {"consent_off": lambda: not S.consent_enabled(seen),
            "cancelled": lambda: S.cancel_seen(run, seen),
            "egress_stopped": lambda: run.egress_stop_reason is not None,
            "send_cap": lambda: S.dispatch_count(seen) >= J.SEND_CAP,
            "time": lambda: run._time_left() <= 0,
            "reservation": lambda: bool(run.budget.would_exceed(**_reservation(world))),
            "configuration": lambda: not science._pins_match(P.projection_body(projection_of(world))[0]),
            "credential": lambda: True}[later]()   # the credential case uses an unusable key below


@pytest.mark.parametrize("pair", list(ADJACENT_PAIRS))
def test_two_adjacent_failing_steps_report_only_the_earlier_one(pair, request, monkeypatch):
    setup, fixture, reason, checkpoint, later = ADJACENT_PAIRS[pair]
    world = request.getfixturevalue(fixture)
    setup(world, monkeypatch)
    assert _later_holds(world, later), f"the later condition {later} does not hold"
    reserved = len(events(world["run"], "budget_reserved"))
    fake = Fake(key=None) if later == "credential" else Fake()
    _rejected(world, fake, reason, checkpoint=checkpoint)   # no key read, no reservation, no transport
    assert len(events(world["run"], "budget_reserved")) == reserved


# ---------------------------------------------------------------- failures (sent, no choice)


def _failed(world, responder, reason, *, stopped=None, settled=True, http_status=200):
    run = world["run"]
    S.set_consent(run, True)
    fake = Fake(responder)
    result = gate_send(world, fake)
    assert (result.status, result.reason_code) == ("failed", reason)
    assert result.answer is None and result.requested_model == J.REQUEST_MODEL
    assert len(fake.requests) == 1 and fake.key_reads == 1
    assert len(events(run, "jev_science_dispatch_started")) == 1
    expected = (["prepared", "dispatch_started", "response_received", "settled"] if settled else
                ["prepared", "dispatch_started", "transport_failed"])
    assert stages(run, result.audit_id) == expected
    if settled:
        received = next(e for e in audits(run, result.audit_id) if e["stage"] == "response_received")
        assert received["http_status"] == http_status
    assert run.egress_stop_reason == stopped
    assert reopen(world).egress_stop_reason == stopped
    assert no_secret(result, events(run)) and SENTINEL.encode() not in run_bytes(run)
    assert RAW_ERROR.encode() not in run_bytes(run)
    return result


def test_transport_timeout_is_external_timeout_and_usage_unknown(mut):
    def timeout(request):
        raise httpx.ReadTimeout(RAW_ERROR, request=request)
    result = _failed(mut, timeout, "external_timeout", stopped="usage_unknown", settled=False)
    assert result.usage is None and result.served_model is None
    failed = audits(mut["run"], result.audit_id)[-1]
    assert failed["error_code"] == "external_timeout" and failed["sent"] == "unknown"


def test_a_slow_provider_hits_the_deadline_as_external_timeout(mut, monkeypatch):
    monkeypatch.setattr(J, "TIMEOUT_S", 0.05)   # fault injection: a short deadline

    async def slow(request):
        await asyncio.sleep(2)
        return reply("m01")
    _failed(mut, slow, "external_timeout", stopped="usage_unknown", settled=False)


def test_other_transport_errors_are_transport_error(mut):
    def broken(request):
        raise httpx.ConnectError(RAW_ERROR, request=request)
    _failed(mut, broken, "transport_error", stopped="usage_unknown", settled=False)


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_non_200_is_provider_http_error_and_settles_reported_usage(mut, status):
    result = _failed(mut, lambda request: httpx.Response(status, json={"error": RAW_ERROR, "usage": USAGE}),
                     "provider_http_error", http_status=status)
    assert result.usage["external_tokens"] == 3020 and result.served_model is None


RESPONSE_INVALID = {   # SYNTHETIC provider replies
    "alias_outside": lambda r: reply("m09"),
    "alias_of_other_kind": lambda r: reply("c01"),
    "extra_answer_field": lambda r: reply("m01", rank=1),
    "extra_answer_key": lambda r: reply(answers={"candidate_choice": {"type": "choice", "choice": "m01"},
                                                 "best": {"type": "choice", "choice": "m01"}}),
    "wrong_type": lambda r: reply(answer={"type": "boolean", "choice": "m01"}),
    "confidence_range": lambda r: reply("m01", confidence=1.5),
    "probability_range": lambda r: reply("m01", probabilities={"m01": -0.1}),
    "probability_key": lambda r: reply("m01", probabilities={"m09": 0.5}),
    "probability_bool": lambda r: reply("m01", probabilities={"m01": True}),
}


@pytest.mark.parametrize("name", sorted(RESPONSE_INVALID))
def test_answers_outside_the_closed_shape_are_response_invalid(mut, name):
    result = _failed(mut, RESPONSE_INVALID[name], "response_invalid")
    assert result.usage["external_tokens"] == 3020


def test_unparsable_body_is_response_invalid_with_unknown_usage(mut):
    _failed(mut, lambda request: httpx.Response(200, content=b"not json " + RAW_ERROR.encode()),
            "response_invalid", stopped="usage_unknown")


def test_oversized_body_is_response_invalid_and_unhashed(mut):
    big = json.dumps({"model": J.SERVED_SNAPSHOT, "pad": "x" * 70_000, "usage": USAGE}).encode()
    result = _failed(mut, lambda request: httpx.Response(200, content=big), "response_invalid",
                     stopped="usage_unknown")
    received = next(e for e in audits(mut["run"], result.audit_id) if e["stage"] == "response_received")
    assert received["response_oversized"] is True and received["response_sha256"] is None


def test_model_missing_or_other_model(mut, lig):
    result = _failed(mut, lambda request: reply("m01", drop_model=True), "missing_model")
    assert result.served_model is None
    result = _failed(lig, lambda request: reply("c01", model="typesafe/jev-1.12-20250101"), "model_mismatch")
    assert result.served_model is None


def test_missing_usage_stops_all_later_egress_including_the_viewer(mut):
    run = mut["run"]
    S.set_consent(run, True)
    result = gate_send(mut, Fake(lambda request: reply("m01", usage=None)))
    assert result.status == "accepted" and result.usage == {"input_tokens": None, "output_tokens": None,
                                                            "external_tokens": None, "cost": None}
    assert run.egress_stop_reason == "usage_unknown"
    set_online(run, True)
    scene = create_session(run, client_instance_id=str(uuid.uuid4()), scene_generation=1,
                           structure_handle=mut["prepared"])
    intent_id, internal, _ = request_intent(run, client_instance_id=scene["client_instance_id"],
                                            viewer_session_id=scene["viewer_session_id"], scene_generation=1,
                                            request_id=str(uuid.uuid4()), prompt="Show surface")
    viewer = Fake(lambda request: pytest.fail("viewer request sent"))
    outcome = asyncio.run(request_viewer(viewer.gate, run, projected_state(internal, "Show surface"), intent_id))
    assert outcome.reason_code == "usage_unknown" and viewer.requests == [] and viewer.key_reads == 0


# ---------------------------------------------------------------- refunds: reserved but never sent


def _hooked(fake, stage, action):
    original = fake.gate._audit

    def hooked(owner, kind, audit_id, **fields):
        if kind == stage and action.get("before"):
            action["before"](owner)
        original(owner, kind, audit_id, **fields)
        if kind == stage and action.get("after"):
            action["after"](owner)
    fake.gate._audit = hooked


def _refunded(world, fake, reason, raises=None):
    run = world["run"]
    before = len(events(run))
    if raises:
        with pytest.raises(raises):
            gate_send(world, fake)
        result = None
    else:
        result = gate_send(world, fake)
        assert (result.status, result.reason_code) == ("rejected", reason)
    new = [t for t in tail_types(run, before) if t.startswith("egress") or t in ("budget_reserved",
                                                                                   "jev_science_dispatch_started")]
    expected = ["budget_reserved", *([] if raises else ["egress:prepared"]), "egress_budget_settled",
                "egress:dispatch_skipped"]
    assert new == expected
    settle = events(run, "egress_budget_settled")[-1]
    reserved = events(run, "budget_reserved")[-1]
    assert settle["delta"] == {"external_tokens": -reserved["external_tokens"], "usd": -reserved["usd"]}
    assert settle["actual"] == {"external_tokens": 0, "usd": 0} and settle["unknown_axes"] == []
    assert fake.requests == [] and not events(run, "jev_science_dispatch_started")
    assert run.budget.external_tokens == 0 and run.budget.usd == 0
    for again in (reopen(world), reopen(world)):   # a restart never turns a refunded reservation into usage_unknown
        assert again.egress_stop_reason is None and again.egress_unknown is False
        assert again.budget.external_tokens == 0 and again.budget.usd == 0
    return result


def test_cancel_after_the_reservation_refunds_then_records_dispatch_skipped(mut):
    S.set_consent(mut["run"], True)
    fake = Fake()
    _hooked(fake, "prepared", {"after": lambda run: run.events.append("cancel_requested")})   # fault injection
    _refunded(mut, fake, "cancelled")


def test_consent_off_after_the_reservation_refunds(mut):
    S.set_consent(mut["run"], True)
    fake = Fake()
    _hooked(fake, "prepared", {"after": lambda run: run.events.append(   # fault injection: a racing consent change
        J.EVENT_CONSENT, enabled=False, policy=J.CONSENT_POLICY, send_cap=J.SEND_CAP)})
    _refunded(mut, fake, "consent_off")


def test_time_running_out_after_the_reservation_refunds_with_a_checkpoint(mut):
    run = mut["run"]
    S.set_consent(run, True)
    clock = [1000.0]
    run.monotonic = lambda: clock[0]   # fault injection: a controllable clock
    fake = Fake()
    _hooked(fake, "prepared", {"after": lambda owner: clock.__setitem__(0, clock[0] + 10_000)})
    _refunded(mut, fake, "budget_exhausted")
    assert events(run, "checkpoint")[-1]["axis"] == "wall_clock_s"


def test_a_prepared_audit_that_cannot_be_written_is_never_sent(mut):
    S.set_consent(mut["run"], True)
    fake = Fake()

    def fail(owner):
        raise OSError("disk full")   # fault injection
    _hooked(fake, "prepared", {"before": fail})
    _refunded(mut, fake, None, raises=OSError)


def test_a_crash_after_dispatch_reopens_as_usage_unknown_never_resent(mut, tmp_path):
    run = mut["run"]
    S.set_consent(run, True)
    snapshot = tmp_path / "crash" / mut["run_id"]
    snapshot.mkdir(parents=True)

    def crash(request):   # the log as it is while the request is in flight = a server death at this point
        shutil.copyfile(run.run_dir / "events.jsonl", snapshot / "events.jsonl")
        return reply("m01")
    result = gate_send(mut, Fake(crash))
    restarted = new_run(tmp_path / "crash", run_id=mut["run_id"], dry_run=False)
    assert restarted.egress_stop_reason == "usage_unknown" and restarted.egress_unknown is True
    assert stages(restarted, result.audit_id) == ["prepared", "dispatch_started"]   # no automatic resend
    charged = [e for e in events(restarted, "wall_charged") if e.get("audit_id") == result.audit_id]
    assert [e["reason"] for e in charged] == ["egress"]
    assert len(events(restarted, "jev_science_dispatch_started")) == 1


# ---------------------------------------------------------------- unchanged neighbours and module hygiene


def test_existing_m3_and_m8_gate_goldens_are_unchanged():
    out = subprocess.run([sys.executable, str(FIX / "jev/prototype_golden_egress.py"), "--check"],
                         capture_output=True, text=True, cwd=str(REPO), check=False)
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    assert "matches a fresh recording" in out.stdout


def test_new_modules_have_no_limit_strings_and_build_no_http_client():
    for name in ("egress/science.py", "jev_sends.py"):
        text = (MW / name).read_text()
        assert "raise_limits" not in text and "limit_approval" not in text, name
        tree = ast.parse(text)
        built = [node for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                 and node.attr in ("AsyncClient", "Client", "request", "post", "stream")
                 and isinstance(node.value, ast.Name) and node.value.id == "httpx"]
        assert built == [], name
    sends = (MW / "jev_sends.py").read_text()
    for word in ("httpx", "rdkit", "meeko", "MDAnalysis", "pdbfixer", "openmm", "urllib", "socket", "requests",
                 "credential_resolver", "OPENROUTER_API_KEY", ".env"):
        assert word not in sends, word
    code = ("import sys, mw.jev_sends, mw.egress.science\n"
            "print([m for m in ('rdkit', 'meeko', 'MDAnalysis', 'pdbfixer', 'openmm') if m in sys.modules])\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=str(MW.parent))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr
    gate_text = (MW / "egress/gate.py").read_text()
    assert gate_text.count("async def request_science(") == 1 and "from .science import request_science" in gate_text
