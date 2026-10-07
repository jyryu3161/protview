"""M24 JEV science sends: consent, approval, send records and the ``jev_choice@1`` proposal (spec .dryforge/spec.md 5-7).

Server logic the T5 routes wrap. This module never builds an HTTP client and never touches a key: the one external
call is ``EgressGate.request_science`` (``mw.egress.science``), made once per approved send by ``run_send``. Records
are derived from run events only (the in-progress state alone comes from the process-memory set ``ACTIVE_SENDS``), so
they survive an events-only recovery. Nothing here ranks, scores, merges or compares proposals.

Public API:

    class JevSendError(Exception)   JevSendError(code, message, http_status, **detail); .code .message .http_status
        .detail. Codes: not_found 404; input_invalid 422 (detail {"reason_code": "projection_invalid"} for a handle of
        this run that is not a valid jev_projection@1); preview_mismatch / send_id_conflict / send_in_progress 409;
        dry_run 412.
    class ChoiceInvalid(ValueError)  a stored jev_choice@1 that does not validate against its projection and source.
    ACTIVE_SENDS: set[(run_id, send_id)]; begin_send(run_id, send_id) (send_in_progress when the run has one);
        end_send(run_id, send_id); send_active(run_id) -> bool
    consent_enabled(events) -> bool        the last jev_science_consent_changed decides; none (new run) is off
    dispatch_count(events) -> int          jev_science_dispatch_started events (the run's send cap counts these)
    cancel_seen(run, events) -> bool       a cancel event or the cancel marker file
    set_consent(run, enabled) -> jev_status@1      one event; 412 dry_run when enabling a dry-run run
    load_projection(run, handle, *, accept_loop=False) -> content
                                           this run's validated jev_projection@1 (M25: also a validated
                                           jev_loop_projection@1 when accept_loop)
    status_for(run, events) -> jev_status@1        never reads a key
    preview_for(run, projection_handle, events) -> jev_preview@1     the exact body string and its SHA-256; for a
                                           jev_loop_projection@1 (M25) also ``loop`` and ``loop_blocks`` (the loop
                                           send check of ``jev_loop_store``)
    async run_send(run, gate, /, *, send_id, projection, body_sha256, confirm) -> jev_send@1
                                           M25: also a jev_loop_projection@1, whose loop send check runs inside the
                                           approval callback before the approval event (409 loop_send_invalid,
                                           detail ``reason``; nothing recorded); its answer is a jev_loop_choice@1
    send_record(events, send_id) -> jev_send@1 (404 not_found);  list_sends(events) -> [jev_send@1], oldest first
                                           a loop send's record adds ``loop`` {loop_id, iteration, send_ordinal}
    late_arrival(events, send_id) -> (late, late_reason)
    source_content(run, projection) -> the projection's stored candidate set content (ChoiceInvalid if unusable)
    build_choice(...) -> jev_choice@1 content;  validated_choice(content, projection, source) -> content
    load_choice(run, handle) -> validated jev_choice@1 content
    load_loop_choice(run, handle) -> validated jev_loop_choice@1 content (M25; ChoiceInvalid if it does not validate)
"""
from __future__ import annotations

import base64
import copy
import json
import math
import re
import threading
import uuid
from typing import Any

from . import jev_constants as J
from . import jev_loop_constants as L
from . import jev_loop_projection as LP
from . import jev_loop_store, ligand_bundle
from . import jev_projection as P
from . import mutation_candidates as mc
from .core.handles import canonical_json

SEND_REQUEST_KEYS = ("send_id", "projection", "body_sha256", "confirm")
CHOICE_KEYS = ("schema", "method_version", "label", "scientific_result", "send", "source", "projection", "question",
               "requested_model", "served_model", "selection", "answer", "usage", "arrival", "limitations")
ANSWER_KEYS = ("choice_alias", "local_ref", "local_display", "confidence", "probabilities")
USAGE_KEYS = ("input_tokens", "output_tokens", "external_tokens", "cost")
OUTCOME_FIELDS = ("status", "reason_code", "audit_id", "requested_model", "served_model", "usage", "choice_handle",
                  "late", "late_reason")
STATUS_FOR_RESULT = {"accepted": "completed", "rejected": "rejected", "failed": "failed"}
KIND_FOR_QUESTION = {question: kind for kind, question in J.QUESTION_FOR_KIND.items()}
LOOP_KIND_FOR_QUESTION = {question: kind for kind, question in L.QUESTION_FOR_KIND.items()}   # M25 loop sends
_CANCEL_EVENTS = ("cancel_requested", "run_cancelled")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_AUDIT_ID_RE = re.compile(r"eg_[0-9a-f]{32}")
_PROJECTION_HANDLE_RE = re.compile(r"obj://[A-Za-z0-9][A-Za-z0-9_-]{0,79}/jev_projection/[0-9a-f]{64}")
_MAX_SAFE_INT = 9_007_199_254_740_991

ACTIVE_SENDS: set[tuple[str, str]] = set()
_ACTIVE_LOCK = threading.Lock()


class JevSendError(Exception):
    def __init__(self, code: str, message: str, http_status: int, **detail: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.http_status, self.detail = code, message, http_status, detail


class ChoiceInvalid(ValueError):
    pass


class _AlreadyApproved(Exception):
    """Another owner recorded this send_id's approval first (raised inside the gate, before any gate event)."""


# --- process-memory in-progress set ----------------------------------------------------------------------------------

def begin_send(run_id: str, send_id: str) -> None:
    with _ACTIVE_LOCK:
        if any(active == run_id for active, _ in ACTIVE_SENDS):
            raise JevSendError("send_in_progress", "another science send of this run is in progress", 409)
        ACTIVE_SENDS.add((run_id, send_id))


def end_send(run_id: str, send_id: str) -> None:
    with _ACTIVE_LOCK:
        ACTIVE_SENDS.discard((run_id, send_id))


def send_active(run_id: str) -> bool:
    with _ACTIVE_LOCK:
        return any(active == run_id for active, _ in ACTIVE_SENDS)


def _active(run_id: Any, send_id: str) -> bool:
    with _ACTIVE_LOCK:
        return (run_id, send_id) in ACTIVE_SENDS


# --- event-derived state -----------------------------------------------------------------------------------------------

def consent_enabled(events: Any) -> bool:
    last = None
    for event in events:
        if event.get("type") == J.EVENT_CONSENT:
            last = event
    return bool(last is not None and last.get("policy") == J.CONSENT_POLICY and last.get("enabled") is True)


def dispatch_count(events: Any) -> int:
    return sum(event.get("type") == J.EVENT_DISPATCH for event in events)


def cancel_seen(run: Any, events: Any) -> bool:
    return run._cancel_path.exists() or any(event.get("type") in _CANCEL_EVENTS for event in events)


def late_arrival(events: list[dict[str, Any]], send_id: str) -> tuple[bool, str | None]:
    """Late = a cancel event or a consent-off event after this send's dispatch (event order only, no clock)."""
    dispatch = next((event for event in events if event.get("type") == J.EVENT_DISPATCH
                     and event.get("send_id") == send_id), None)
    if dispatch is None:
        return False, None
    later = [event for event in events if event["seq"] > dispatch["seq"]]
    if any(event.get("type") in _CANCEL_EVENTS for event in later):
        return True, "run_cancelled"
    if any(event.get("type") == J.EVENT_CONSENT and not consent_enabled([event]) for event in later):
        return True, "consent_off"
    return False, None


# --- consent -------------------------------------------------------------------------------------------------------------

def set_consent(run: Any, enabled: Any) -> dict[str, Any]:
    """One ``jev_science_consent_changed`` event; the viewer mode (``egress_config["mode"]``) is never touched."""
    if type(enabled) is not bool:
        raise JevSendError("input_invalid", "enabled must be a boolean", 422)
    if enabled and run.dry_run:
        raise JevSendError("dry_run", "a dry-run run cannot enable science sends", 412)
    with run._transition():
        run.events.append(J.EVENT_CONSENT, enabled=enabled, policy=J.CONSENT_POLICY, send_cap=J.SEND_CAP,
                          request_model=J.REQUEST_MODEL, allowed_served_model=J.SERVED_SNAPSHOT,
                          destination=J.DESTINATION)
    return status_for(run, list(run.events.read()))


# --- projection, status, preview ---------------------------------------------------------------------------------------

def load_projection(run: Any, handle: Any, *, accept_loop: bool = False) -> dict[str, Any]:
    """This run's validated ``jev_projection@1``; with ``accept_loop`` also a ``jev_loop_projection@1`` (M25,
    validated by ``jev_loop_projection.validated_loop_projection``). Without it a loop projection is refused as
    before (the send route takes loop projections only with its loop branch)."""
    if type(handle) is not str:
        raise JevSendError("input_invalid", "projection must be a handle string", 422)
    try:
        meta = run.store.meta(handle)
    except (KeyError, ValueError):
        raise JevSendError("not_found", "no such projection in this run", 404) from None
    invalid = JevSendError("input_invalid", "not a valid jev_projection@1 of this run", 422,
                           reason_code=J.PROJECTION_INVALID)
    loop = accept_loop and (meta["kind"], meta["schema"]) == (L.PROJECTION_KIND, L.PROJECTION_SCHEMA)
    if not loop and (meta["kind"], meta["schema"]) != (J.PROJECTION_KIND, J.PROJECTION_SCHEMA):
        raise invalid
    validated = LP.validated_loop_projection if loop else P.validated_projection
    try:
        content = validated(run.store.load_bounded_json(handle, J.MAX_OBJECT_BYTES))
    except (P.JevProjectionError, ValueError, TypeError, KeyError):
        raise invalid from None
    prefix = f"obj://{run.run_id}/"
    if (not content["source"]["handle"].startswith(prefix) or
            (content["structure"] is not None and not content["structure"]["handle"].startswith(prefix))):
        raise invalid
    return content


def _budget(run: Any) -> dict[str, dict[str, Any]]:
    snapshot = run.budget_snapshot()
    return {axis: {"used": snapshot[axis]["used"], "limit": snapshot[axis]["limit"],
                   "remaining": max(0, snapshot[axis]["limit"] - snapshot[axis]["used"])}
            for axis in ("external_tokens", "usd")}


def status_for(run: Any, events: list[dict[str, Any]]) -> dict[str, Any]:
    used = dispatch_count(events)
    return {"schema": J.STATUS_SCHEMA, "enabled": consent_enabled(events), "policy": J.CONSENT_POLICY,
            "send_cap": J.SEND_CAP, "used": used, "remaining": max(0, J.SEND_CAP - used), "budget": _budget(run),
            "egress_stop_reason": run.egress_stop_reason, "dry_run": run.dry_run,
            "cancelled": cancel_seen(run, events), "question_ids": list(J.QUESTION_IDS),
            "send_in_progress": send_active(run.run_id), "request_model": J.REQUEST_MODEL,
            "allowed_served_model": J.SERVED_SNAPSHOT, "destination": J.DESTINATION}


def _blocked(run: Any, events: list[dict[str, Any]], reservation: dict[str, Any]) -> list[str]:
    """Every pre-send refusal that holds now, in the closed order (the gate re-checks them at send time)."""
    reasons = []
    if run.dry_run:
        reasons.append("dry_run")
    if not consent_enabled(events):
        reasons.append("consent_off")
    if cancel_seen(run, events):
        reasons.append("cancelled")
    if run.egress_stop_reason:
        reasons.append("egress_stopped")
    if dispatch_count(events) >= J.SEND_CAP:
        reasons.append("send_cap_exhausted")
    if run._time_left() <= 0 or run.budget.would_exceed(**reservation):
        reasons.append("budget_exhausted")
    if send_active(run.run_id):
        reasons.append("send_in_progress")
    return reasons


def _loop_preview(run: Any, content: dict[str, Any], events: list[dict[str, Any]],
                  reservation: dict[str, Any]) -> dict[str, Any]:
    """M25 (spec 5.1): the ``loop`` block (the projection's loop reference with the send-side ``needs`` /
    ``remaining`` / ``send_blocked_axes`` of the loop record derived from the same events with this preview's
    reservation) and ``loop_blocks``: the refusal of the loop send check (``jev_loop_store.loop_send_check``, the
    loop judgment the send uses), empty when the loop may send this projection now."""
    state, reason = jev_loop_store.loop_send_check(
        jev_loop_store.LoopReadView(run, events), content,
        budget=jev_loop_store.remaining_budget(run.budget_snapshot()), send_active=send_active(run.run_id),
        send_reservation=reservation)
    current = None if state is None else state.record["current"]
    block = {**content["loop"], **{name: None if current is None else copy.deepcopy(current[name])
                                   for name in ("needs", "remaining", "send_blocked_axes")}}
    return {"loop": block, "loop_blocks": [] if reason is None else [reason]}


def preview_for(run: Any, projection_handle: Any, events: list[dict[str, Any]]) -> dict[str, Any]:
    content = load_projection(run, projection_handle, accept_loop=True)
    loop = content["schema"] == L.PROJECTION_SCHEMA
    _, encoded = LP.loop_projection_body(content) if loop else P.projection_body(content)
    question_id = content["question"]["id"]
    if loop:
        instructions = L.INSTRUCTIONS[(content["kind"], content["goal"])]
        instructions_sha256 = L.instructions_sha256(content["kind"], content["goal"])
    else:
        instructions, instructions_sha256 = J.INSTRUCTIONS[question_id], J.instructions_sha256(question_id)
    reservation = {"external_tokens": J.reserve_tokens(len(encoded)), "usd": J.RESERVE_USD}
    used = dispatch_count(events)
    dispatched = {event["send_id"] for event in events if event.get("type") == J.EVENT_DISPATCH}
    previous = sum(event.get("type") == J.EVENT_APPROVED and event.get("projection_handle") == projection_handle
                   and event.get("send_id") in dispatched for event in events)
    budget = _budget(run)
    preview = {"schema": J.PREVIEW_SCHEMA, "projection_handle": projection_handle, "kind": content["kind"],
               "source": dict(content["source"]),
               "question": {"id": question_id, "key": J.QUESTION_KEY, "type": J.QUESTION_TYPE,
                            "instructions": instructions, "instructions_sha256": instructions_sha256},
               "body": encoded.decode("ascii"), "body_sha256": P.body_sha256(encoded), "body_bytes": len(encoded),
               "selection": copy.deepcopy(content["selection"]), "selection_sent": False,
               "reservation": reservation, "send_cap": J.SEND_CAP, "used": used,
               "remaining": max(0, J.SEND_CAP - used),
               "budget_remaining": {axis: budget[axis]["remaining"] for axis in ("external_tokens", "usd")},
               "blocked_by": _blocked(run, events, reservation), "previous_sends": previous}
    if loop:
        preview.update(_loop_preview(run, content, events, reservation))
    return preview


# --- one approved send ---------------------------------------------------------------------------------------------------

def _is_uuid4(value: Any) -> bool:
    if type(value) is not str:
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value


def _check_request(send_id: Any, projection: Any, body_sha256: Any, confirm: Any, unknown: dict[str, Any]) -> None:
    def bad(message: str) -> JevSendError:
        return JevSendError("input_invalid", message, 422)
    if unknown:
        raise bad("the send has fields outside send_id, projection, body_sha256 and confirm")
    if type(confirm) is not str or confirm != J.CONFIRM:
        raise bad(f"confirm must be '{J.CONFIRM}'")
    if not _is_uuid4(send_id):
        raise bad("send_id must be a canonical version 4 UUID")
    if type(projection) is not str:
        raise bad("projection must be a handle string")
    if type(body_sha256) is not str or not _SHA256_RE.fullmatch(body_sha256):
        raise bad("body_sha256 must be 64 lowercase hex digits")


def _approved(events: list[dict[str, Any]], send_id: str) -> dict[str, Any] | None:
    return next((event for event in events if event.get("type") == J.EVENT_APPROVED
                 and event.get("send_id") == send_id), None)


def _replayed(run: Any, send_id: str, projection: str, body_sha256: str) -> dict[str, Any] | None:
    """The existing record of this send_id (idempotent), ``send_id_conflict`` for other content, None if unused."""
    events = list(run.events.read())
    approved = _approved(events, send_id)
    if approved is None:
        return None
    if approved["projection_handle"] != projection or approved["body_sha256"] != body_sha256:
        raise JevSendError("send_id_conflict", "this send_id was approved for another projection or body", 409)
    return send_record(events, send_id)


def _loop_send_refusal(run: Any, content: dict[str, Any], events: list[dict[str, Any]], body_bytes: int) -> None:
    """M25 spec 5.1: the loop send check of a ``jev_loop_projection@1`` inside the approval callback (the gate's run
    owner and transition guard are held; nothing here takes either again). The loop record is derived from the
    callback's event list only, with this process's in-flight state (``send_active``) and the M24 reservation of this
    body; a refusal raises 409 ``loop_send_invalid`` with ``reason`` in ``LOOP_SEND_REASONS`` before any approval,
    audit, reservation or key read."""
    reservation = {"external_tokens": J.reserve_tokens(body_bytes), "usd": J.RESERVE_USD}
    _, reason = jev_loop_store.loop_send_check(
        jev_loop_store.LoopReadView(run, events), content,
        budget=jev_loop_store.remaining_budget(run.budget_snapshot()), send_active=send_active(run.run_id),
        send_reservation=reservation)
    if reason is not None:
        raise JevSendError(L.LOOP_SEND_INVALID, "the JEV loop cannot send this projection now; nothing was recorded",
                           409, reason=reason)


async def run_send(run: Any, gate: Any, /, *, send_id: Any = None, projection: Any = None, body_sha256: Any = None,
                   confirm: Any = None, **unknown: Any) -> dict[str, Any]:
    """Check, approve and send one projection body; returns its ``jev_send@1`` record (also for refusals)."""
    _check_request(send_id, projection, body_sha256, confirm, unknown)
    content = load_projection(run, projection, accept_loop=True)
    loop = content["schema"] == L.PROJECTION_SCHEMA
    _, encoded = LP.loop_projection_body(content) if loop else P.projection_body(content)
    if P.body_sha256(encoded) != body_sha256:
        raise JevSendError("preview_mismatch", "body_sha256 is not the SHA-256 of this projection's body", 409)
    existing = _replayed(run, send_id, projection, body_sha256)
    if existing is not None:
        return existing
    begin_send(run.run_id, send_id)
    try:
        approval = {"send_id": send_id, "projection_handle": projection, "body_sha256": body_sha256,
                    "question_id": content["question"]["id"], "source_handle": content["source"]["handle"],
                    "selection_count": len(content["selection"]), "approved_by": J.APPROVED_BY}

        def admit(events: list[dict[str, Any]]) -> None:
            # Runs under the gate's run owner and transition guard, before its first check: a busy run writes nothing.
            if _approved(events, send_id) is not None:
                raise _AlreadyApproved
            if loop:   # M25: the loop send check, from this event list only, before the approval event
                _loop_send_refusal(run, content, events, len(encoded))
            run.events.append(J.EVENT_APPROVED, **approval)

        try:
            result = await gate.request_science(run, content, send_id, admit=admit)
        except _AlreadyApproved:
            end_send(run.run_id, send_id)
            return _replayed(run, send_id, projection, body_sha256)
        return _finish(run, content, projection, send_id, result)
    finally:
        end_send(run.run_id, send_id)


def _finish(run: Any, content: dict[str, Any], projection_handle: str, send_id: str, result: Any) -> dict[str, Any]:
    status = STATUS_FOR_RESULT[result.status]
    reason = None if status == "completed" else result.reason_code
    allowed = {"completed": (None,), "rejected": J.REJECTED_REASONS, "failed": J.FAILED_REASONS}[status]
    if reason not in allowed:
        raise ValueError("the gate returned a reason outside the closed send reasons")
    with run._transition():
        events = list(run.events.read())
        late, late_reason = late_arrival(events, send_id) if status != "rejected" else (False, None)
        choice_handle = None
        if status == "completed" and content["schema"] == L.PROJECTION_SCHEMA:
            # M25: a loop projection's answer is a jev_loop_choice@1, stored only once it validates (a
            # LoopChoiceInvalid propagates like the M24 ChoiceInvalid below: no outcome is recorded)
            choice = LP.build_loop_choice(projection_handle, content, source_content(run, content), send_id=send_id,
                                          audit_id=result.audit_id, answer=result.answer,
                                          served_model=result.served_model, usage=result.usage, late=late,
                                          late_reason=late_reason)
            choice_handle = run.store.put(L.CHOICE_KIND, L.CHOICE_SCHEMA, choice,
                                          summary={"kind": content["kind"], "send_id": send_id,
                                                   "projection": projection_handle, "late": late}).handle
        elif status == "completed":
            source = source_content(run, content)
            choice = build_choice(projection_handle, content, source, send_id=send_id, audit_id=result.audit_id,
                                  answer=result.answer, served_model=result.served_model, usage=result.usage,
                                  late=late, late_reason=late_reason)
            validated_choice(choice, content, source)
            choice_handle = run.store.put(J.CHOICE_KIND, J.CHOICE_SCHEMA, choice,
                                          summary={"kind": content["kind"], "send_id": send_id,
                                                   "projection": projection_handle, "late": late}).handle
        run.events.append(J.EVENT_OUTCOME, send_id=send_id, status=status, reason_code=reason,
                          audit_id=result.audit_id, requested_model=result.requested_model,
                          served_model=result.served_model, choice_handle=choice_handle, usage=result.usage,
                          late=late, late_reason=late_reason)
        events = list(run.events.read())
    return send_record(events, send_id)


# --- send records (events only) ------------------------------------------------------------------------------------------

def _index(events: list[dict[str, Any]]) -> dict[str, Any]:
    index: dict[str, Any] = {"run_id": events[0].get("run_id") if events else None, "approved": {}, "outcomes": {},
                             "dispatches": {}, "responses": {}, "projections": {}, "body_bytes": {}}
    for event in events:
        kind = event.get("type")
        if kind == J.EVENT_APPROVED:
            index["approved"].setdefault(event["send_id"], event)
        elif kind == J.EVENT_OUTCOME:
            index["outcomes"].setdefault(event["send_id"], event)
        elif kind == J.EVENT_DISPATCH:
            index["dispatches"].setdefault(event["send_id"], event)
        elif kind == "egress" and event.get("stage") == "response_received":
            index["responses"].setdefault(event["audit_id"], event)
        elif kind == "object_created" and event.get("kind") in (J.PROJECTION_KIND, L.PROJECTION_KIND):
            index["projections"].setdefault(event["handle"], event)
    return index


def _body_bytes(index: dict[str, Any], handle: str) -> int | None:
    if handle not in index["body_bytes"]:
        try:
            content = json.loads(base64.b64decode(index["projections"][handle]["payload_b64"], validate=True))
            value = content["body_bytes"]
            index["body_bytes"][handle] = value if type(value) is int else None
        except (KeyError, TypeError, ValueError):
            index["body_bytes"][handle] = None
    return index["body_bytes"][handle]


def _record(index: dict[str, Any], send_id: str) -> dict[str, Any]:
    approved = index["approved"][send_id]
    outcome = index["outcomes"].get(send_id)
    dispatch = index["dispatches"].get(send_id)
    kind = KIND_FOR_QUESTION.get(approved["question_id"], LOOP_KIND_FOR_QUESTION.get(approved["question_id"]))
    record: dict[str, Any] = {
        "schema": J.SEND_SCHEMA, "send_id": send_id, "status": None, "reason_code": None,
        "projection_handle": approved["projection_handle"],
        "source": {"handle": approved["source_handle"], "schema": J.SOURCE_SCHEMAS.get(kind)}, "kind": kind,
        "question_id": approved["question_id"], "selection_count": approved["selection_count"],
        "body_sha256": approved["body_sha256"], "body_bytes": _body_bytes(index, approved["projection_handle"]),
        "audit_id": None, "requested_model": None, "served_model": None, "usage": None, "choice_handle": None,
        "late": False, "late_reason": None, "approved_event_seq": approved["seq"], "outcome_event_seq": None}
    if outcome is not None:
        record.update({key: outcome[key] for key in OUTCOME_FIELDS}, outcome_event_seq=outcome["seq"])
        return record
    if dispatch is not None:
        record.update(audit_id=dispatch["audit_id"], requested_model=J.REQUEST_MODEL)
    if _active(index["run_id"], send_id):
        record["status"] = J.IN_PROGRESS   # read-only derived state, never stored
        return record
    response = index["responses"].get(dispatch["audit_id"]) if dispatch is not None else None
    record["status"] = "failed"
    record["reason_code"] = "outcome_not_recorded" if response is not None else "delivery_unknown"
    if response is not None:
        record.update(served_model=response.get("served_model"), usage=response.get("usage"))
    return record


def _loop_of(index: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """M25: a send of a ``jev_loop_projection@1`` adds ``loop`` {loop_id, iteration, send_ordinal}, read from that
    projection's event payload (None if it does not read back); an M24 send's record is unchanged (no ``loop`` key)."""
    event = index["projections"].get(record["projection_handle"])
    if event is None or event.get("kind") != L.PROJECTION_KIND:
        return record
    try:
        loop = json.loads(base64.b64decode(event["payload_b64"], validate=True))["loop"]
        record["loop"] = {key: loop[key] for key in L.LOOP_REF_KEYS}
    except (KeyError, TypeError, ValueError):
        record["loop"] = None
    return record


def send_record(events: list[dict[str, Any]], send_id: Any) -> dict[str, Any]:
    index = _index(events)
    if type(send_id) is not str or send_id not in index["approved"]:
        raise JevSendError("not_found", "no such science send in this run", 404)
    return _loop_of(index, _record(index, send_id))


def list_sends(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = _index(events)
    return [_loop_of(index, _record(index, send_id)) for send_id in index["approved"]]


# --- the proposal object -------------------------------------------------------------------------------------------------

def source_content(run: Any, projection: dict[str, Any]) -> dict[str, Any]:
    """The projection's stored candidate set, checked the way the projection tool checks it."""
    kind, handle = projection["kind"], projection["source"]["handle"]
    try:
        meta = run.store.meta(handle)
        if (meta["kind"], meta["schema"]) != (J.SOURCE_STORE_KINDS[kind], J.SOURCE_SCHEMAS[kind]):
            raise ValueError("source kind")
        if kind == "ligand":
            return ligand_bundle.validated_candidate_set(run, handle)[0]
        return mc.validated_set(run.store.load(handle))
    except (KeyError, ValueError, TypeError) as exc:   # LigandEvidenceError / MutationSetInvalid are ValueErrors
        raise ChoiceInvalid("the projection's candidate set is not a valid set of this run") from exc


def _display(kind: str, source: dict[str, Any], local_ref: dict[str, Any]) -> dict[str, Any]:
    """The chosen candidate's local notation, copied from the stored candidate set."""
    if kind == "ligand":
        rows = [row for row in source["candidates"] if row["id"] == local_ref["candidate_id"]]
        _require(len(rows) == 1, "chosen candidate is not in the candidate set")
        return {"smiles": rows[0]["smiles"]}
    rows = [row for row in source["candidates"] if row["index"] == local_ref["candidate_index"]]
    positions = [item for item in source["positions"] if item["index"] == local_ref["position_index"]]
    _require(len(rows) == 1 and len(positions) == 1 and rows[0]["position_index"] == local_ref["position_index"],
             "chosen candidate is not in the candidate set")
    residue = positions[0]["residue"]
    return {"residue": {key: residue[key] for key in J.ALLOWED_RESIDUE}, "from": rows[0]["from"],
            "to": rows[0]["to"]}


def _local_ref(projection: dict[str, Any], alias: str) -> dict[str, Any]:
    item = next(item for item in projection["selection"] if item["alias"] == alias)
    return {key: item[key] for key in J.SELECTION_KEYS[projection["kind"]] if key != "alias"}


def build_choice(projection_handle: str, projection: dict[str, Any], source: dict[str, Any], *, send_id: str,
                 audit_id: str, answer: dict[str, Any], served_model: Any, usage: dict[str, Any] | None,
                 late: bool, late_reason: str | None) -> dict[str, Any]:
    """The proposal: the answer exactly as received (no reordering or rounding) plus local references."""
    kind, question_id = projection["kind"], projection["question"]["id"]
    local_ref = _local_ref(projection, answer["choice_alias"])
    return {
        "schema": J.CHOICE_SCHEMA, "method_version": J.CHOICE_METHOD_VERSION, "label": J.CHOICE_LABEL,
        "scientific_result": False, "send": {"send_id": send_id, "audit_id": audit_id},
        "source": dict(projection["source"]),
        "projection": {"handle": projection_handle, "wire_sha256": projection["wire_sha256"],
                       "body_sha256": projection["body_sha256"], "body_bytes": projection["body_bytes"]},
        "question": {"id": question_id, "key": J.QUESTION_KEY,
                     "instructions_sha256": J.instructions_sha256(question_id)},
        "requested_model": J.REQUEST_MODEL, "served_model": served_model,
        "selection": copy.deepcopy(projection["selection"]),
        "answer": {"choice_alias": answer["choice_alias"], "local_ref": local_ref,
                   "local_display": _display(kind, source, local_ref), "confidence": answer["confidence"],
                   "probabilities": copy.deepcopy(answer["probabilities"])},
        "usage": None if usage is None else {key: usage[key] for key in USAGE_KEYS},
        "arrival": {"late": late, "late_reason": late_reason},
        "limitations": J.limitations_for(kind, late),
    }


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise ChoiceInvalid(message)


def _same(left: Any, right: Any) -> bool:
    return canonical_json(left) == canonical_json(right)


def _is_unit(value: Any) -> bool:
    return (type(value) is int and 0 <= value <= 1) or (type(value) is float and math.isfinite(value)
                                                        and 0.0 <= value <= 1.0)


def _usage_value(key: str, value: Any) -> bool:
    if value is None:
        return True
    if key == "cost":
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    return type(value) is int and 0 <= value <= _MAX_SAFE_INT


def _check_choice(content: Any, projection: dict[str, Any], source: dict[str, Any]) -> None:
    _require(type(content) is dict and set(content) == set(CHOICE_KEYS), "proposal keys")
    _require(content["schema"] == J.CHOICE_SCHEMA and content["method_version"] == J.CHOICE_METHOD_VERSION
             and content["label"] == J.CHOICE_LABEL, "schema or label")
    _require(content["scientific_result"] is False, "a proposal is never a scientific result")
    send = content["send"]
    _require(type(send) is dict and set(send) == {"send_id", "audit_id"} and _is_uuid4(send["send_id"])
             and type(send["audit_id"]) is str and _AUDIT_ID_RE.fullmatch(send["audit_id"]), "send")
    kind, question_id = projection["kind"], projection["question"]["id"]
    _require(_same(content["source"], projection["source"]), "source")
    ref = content["projection"]
    _require(type(ref) is dict and set(ref) == {"handle", "wire_sha256", "body_sha256", "body_bytes"}
             and type(ref["handle"]) is str and _PROJECTION_HANDLE_RE.fullmatch(ref["handle"])
             and _same([ref[key] for key in ("wire_sha256", "body_sha256", "body_bytes")],
                       [projection[key] for key in ("wire_sha256", "body_sha256", "body_bytes")]), "projection")
    _require(_same(content["question"], {"id": question_id, "key": J.QUESTION_KEY,
                                         "instructions_sha256": J.instructions_sha256(question_id)}), "question")
    _require(content["requested_model"] == J.REQUEST_MODEL and content["served_model"] == J.SERVED_SNAPSHOT,
             "models")
    _require(_same(content["selection"], projection["selection"]), "selection")
    aliases = [item["alias"] for item in projection["selection"]]
    answer = content["answer"]
    _require(type(answer) is dict and set(answer) == set(ANSWER_KEYS), "answer keys")
    _require(type(answer["choice_alias"]) is str and answer["choice_alias"] in aliases, "chosen alias")
    local_ref = _local_ref(projection, answer["choice_alias"])
    _require(_same(answer["local_ref"], local_ref), "local reference")
    _require(_same(answer["local_display"], _display(kind, source, local_ref)), "local display")
    _require(answer["confidence"] is None or _is_unit(answer["confidence"]), "confidence")
    probabilities = answer["probabilities"]
    _require(probabilities is None or (type(probabilities) is dict and len(probabilities) <= len(aliases) and all(
        type(key) is str and key in aliases and _is_unit(value) for key, value in probabilities.items())),
        "probabilities")
    usage = content["usage"]
    _require(usage is None or (type(usage) is dict and set(usage) == set(USAGE_KEYS)
                               and all(_usage_value(key, value) for key, value in usage.items())), "usage")
    arrival = content["arrival"]
    _require(type(arrival) is dict and set(arrival) == {"late", "late_reason"} and type(arrival["late"]) is bool
             and (arrival["late_reason"] in J.LATE_REASONS if arrival["late"] else arrival["late_reason"] is None),
             "arrival")
    _require(content["limitations"] == J.limitations_for(kind, arrival["late"]), "limitations")
    _require(len(canonical_json(content)) <= J.MAX_OBJECT_BYTES, "object size")


def validated_choice(content: Any, projection: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """``content`` if it is a well-formed proposal of this projection and candidate set; else ``ChoiceInvalid``."""
    try:
        _check_choice(content, projection, source)
    except ChoiceInvalid:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, StopIteration) as exc:
        raise ChoiceInvalid("proposal content is malformed") from exc
    return content


def load_choice(run: Any, handle: Any) -> dict[str, Any]:
    """This run's stored ``jev_choice@1``, re-validated against its projection and candidate set on every read."""
    if type(handle) is not str:
        raise JevSendError("input_invalid", "choice must be a handle string", 422)
    try:
        meta = run.store.meta(handle)
    except (KeyError, ValueError):
        raise JevSendError("not_found", "no such proposal in this run", 404) from None
    if (meta["kind"], meta["schema"]) != (J.CHOICE_KIND, J.CHOICE_SCHEMA):
        raise JevSendError("input_invalid", "not a jev_choice@1 of this run", 422)
    try:
        content = run.store.load_bounded_json(handle, J.MAX_OBJECT_BYTES)
        projection = load_projection(run, content["projection"]["handle"])
    except (ValueError, KeyError, TypeError, JevSendError) as exc:
        raise ChoiceInvalid("the proposal or its projection is unreadable") from exc
    return validated_choice(content, projection, source_content(run, projection))


def load_loop_choice(run: Any, handle: Any) -> dict[str, Any]:
    """M25: this run's stored ``jev_loop_choice@1``, re-validated against its ``jev_loop_projection@1`` and candidate
    set on every read (``jev_loop_projection.validated_loop_choice``); ``ChoiceInvalid`` as for ``load_choice``."""
    if type(handle) is not str:
        raise JevSendError("input_invalid", "choice must be a handle string", 422)
    try:
        meta = run.store.meta(handle)
    except (KeyError, ValueError):
        raise JevSendError("not_found", "no such proposal in this run", 404) from None
    if (meta["kind"], meta["schema"]) != (L.CHOICE_KIND, L.CHOICE_SCHEMA):
        raise JevSendError("input_invalid", "not a jev_loop_choice@1 of this run", 422)
    try:
        content = run.store.load_bounded_json(handle, L.MAX_OBJECT_BYTES)
        projection = load_projection(run, content["projection"]["handle"], accept_loop=True)
        if projection["schema"] != L.PROJECTION_SCHEMA:
            raise ValueError("a loop proposal names a loop projection")
        return LP.validated_loop_choice(content, projection, source_content(run, projection))
    except (ValueError, KeyError, TypeError, JevSendError) as exc:   # LoopChoiceInvalid is a ValueError
        raise ChoiceInvalid("the loop proposal does not validate against its projection and candidate set") from exc
