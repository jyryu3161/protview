"""M24 science scope of the EgressGate: one human-approved Jev request for one stored ``jev_projection@1``.

Spec .dryforge/spec.md 5. The bytes sent are ``jev_projection.projection_body(content)`` -- the same function the
preview and the ``prepared`` audit use -- so the transport, the preview string and the audited body are identical.
There is no send without an approval: ``admit`` is required (a missing or non-callable hook is a ``TypeError`` before
anything is written, read or sent), and after it runs the log must hold this send's ``jev_send_approved`` for exactly
this body (else ``PermissionError``: no audit, reservation, key read or request). Under the run owner and one
transition guard the steps run in this order, and only the first failing check is recorded (one ``denied`` audit,
``rejected``): the caller's ``admit`` hook (records the approval) and its check -> ``dry_run`` ->
``consent_off`` -> ``cancelled`` -> ``egress_stopped`` -> ``send_cap_exhausted`` -> activity time (``budget_exhausted``
with a checkpoint) -> external tokens / USD reservation (``budget_exhausted``) -> ``missing_configuration`` (pins) ->
the key (``missing_credential``; nothing earlier reads it) -> ``budget_reserved`` (external tokens and USD only) ->
``prepared`` audit -> re-check of cancel, consent and time (a failure refunds with a negative settlement, then a
``dispatch_skipped`` audit) -> ``dispatch_started`` audit + ``jev_science_dispatch_started``. The one HTTP request
(no retry, no redirect, environment proxies ignored, deadline = min(15 s, remaining activity time)) runs outside the
transition guard, so a cancel or a consent change can land while it is in flight; the reply is then recorded and
settled by the existing rules (``response_received`` / ``transport_failed`` / ``settled``, ``Run._settle_egress``).
No key, header, raw provider error or response body is written anywhere: only safe enums and the HTTP status.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from .. import jev_constants as J
from .. import jev_projection as P
from ..jev_sends import cancel_seen, consent_enabled, dispatch_count
from . import gate as G

UNKNOWN_USAGE = {"input_tokens": None, "output_tokens": None, "external_tokens": None, "cost": None}


@dataclass(frozen=True)
class ScienceGateResult:
    status: Literal["accepted", "rejected", "failed"]
    reason_code: str | None
    answer: dict[str, Any] | None = None       # {choice_alias, confidence, probabilities}, as received and checked
    audit_id: str | None = None
    requested_model: str | None = None
    served_model: str | None = None
    usage: dict[str, Any] | None = None


def _pins_match(body: dict[str, Any]) -> bool:
    """The science constants, the projection module's copies and the gate's pins all agree with the body."""
    return (J.REQUEST_MODEL == P.REQUEST_MODEL == G.REQUEST_MODEL == body.get("model")
            and J.SERVED_SNAPSHOT == P.SERVED_SNAPSHOT == G.SERVED_SNAPSHOT
            and J.PROVIDER == P.PROVIDER == G.PROVIDER == body.get("provider")
            and J.DESTINATION == G.DESTINATION and J.MAX_RESPONSE_BYTES == G.MAX_RESPONSE_BYTES)


def _approval_recorded(events: list[dict[str, Any]], send_id: str, content: dict[str, Any],
                       payload_sha256: str) -> bool:
    """The first ``jev_send_approved`` of this send_id is a human approval of exactly this body."""
    approved = next((event for event in events if event.get("type") == J.EVENT_APPROVED
                     and event.get("send_id") == send_id), None)
    return (approved is not None and approved.get("body_sha256") == payload_sha256
            and approved.get("question_id") == content["question"]["id"]
            and approved.get("source_handle") == content["source"]["handle"]
            and approved.get("selection_count") == len(content["selection"])
            and approved.get("approved_by") == J.APPROVED_BY)


async def request_science(gate: G.EgressGate, run: Any, projection_content: Any, send_id: str, *,
                          admit: Callable[[list[dict[str, Any]]], None]) -> ScienceGateResult:
    """At most one physical request, only after ``admit(events)`` (under the owner and transition guard) has
    recorded this send's approval of this body."""
    if not callable(admit):   # before any event, key read or transport
        raise TypeError("request_science needs the approval hook admit(events); nothing was recorded or sent")
    content = P.validated_projection(projection_content)   # a refusal here writes nothing
    body, encoded = P.projection_body(content)
    payload_sha256 = P.body_sha256(encoded)
    aliases = [item["alias"] for item in content["selection"]]
    reservation = {"external_tokens": J.reserve_tokens(len(encoded)), "usd": J.RESERVE_USD}
    audit_id = f"eg_{uuid.uuid4().hex}"

    def audit(stage: str, **fields: Any) -> None:
        gate._audit(run, stage, audit_id, **fields, scope=J.AUDIT_SCOPE, send_id=send_id)

    def rejected(reason: str) -> ScienceGateResult:
        return ScienceGateResult("rejected", reason, audit_id=audit_id)

    def deny(reason: str, **fields: Any) -> ScienceGateResult:
        audit("denied", reason_code=reason, **fields, transport_invoked=False, sent=False)
        return rejected(reason)

    def failed(reason: str, served: str | None = None, usage: dict[str, Any] | None = None) -> ScienceGateResult:
        return ScienceGateResult("failed", reason, audit_id=audit_id, requested_model=G.REQUEST_MODEL,
                                 served_model=served, usage=usage)

    def time_checkpoint() -> None:
        run.events.append("checkpoint", reason="budget", axis="wall_clock_s", audit_id=audit_id,
                          usage=run.budget.wall_clock_s, limit=run.budget.limits.wall_clock_s)

    def refund(reason: str) -> ScienceGateResult:
        # Settle before the skip audit: a crash in between must never leave an unsettled reservation.
        delta = {axis: -amount for axis, amount in reservation.items()}
        run.events.append("egress_budget_settled", audit_id=audit_id, delta=delta,
                          actual={"external_tokens": 0, "usd": 0}, unknown_axes=[])
        run.budget.charge(**delta)
        audit("dispatch_skipped", reason_code=reason, transport_invoked=False, sent=False)
        return rejected(reason)

    with run._mutation():
        started = run.monotonic()

        def remaining() -> float:
            return run._time_left() - max(0.0, run.monotonic() - started)

        with run._transition():
            admit(list(run.events.read()))
            events = list(run.events.read())
            if not _approval_recorded(events, send_id, content, payload_sha256):
                raise PermissionError("no recorded approval of this send's body; nothing was sent")
            if run.dry_run:
                return deny("dry_run")
            if not consent_enabled(events):
                return deny("consent_off")
            if cancel_seen(run, events):
                return deny("cancelled")
            if run.egress_stop_reason:
                return deny("egress_stopped", stop_reason=run.egress_stop_reason)
            if dispatch_count(events) >= J.SEND_CAP:
                return deny("send_cap_exhausted")
            if remaining() <= 0:
                time_checkpoint()
                return deny("budget_exhausted")
            if run.budget.would_exceed(**reservation):
                return deny("budget_exhausted")
            if not _pins_match(body):
                return deny("missing_configuration")
            try:
                key = gate.credential_resolver()
            except Exception:  # noqa: BLE001 - resolver diagnostics may contain secrets
                key = None
            if not isinstance(key, str) or not key or any(ch in key for ch in "\r\n"):
                return deny("missing_credential")
            run.events.append("budget_reserved", audit_id=audit_id, send_id=send_id, **reservation)
            run.budget.charge(**reservation)
            try:
                audit("prepared", destination=G.DESTINATION, requested_model=G.REQUEST_MODEL,
                      question_version=content["question"]["id"], body=body, payload_sha256=payload_sha256,
                      projection_sha256=content["wire_sha256"], reservation=reservation,
                      transport_invoked=False, sent=False)
            except BaseException:
                refund("prepared_not_recorded")
                raise
            current = list(run.events.read())
            if cancel_seen(run, current):
                return refund("cancelled")
            if not consent_enabled(current):
                return refund("consent_off")
            left = remaining()
            if left <= 0:
                outcome = refund("budget_exhausted")
                time_checkpoint()
                return outcome
            audit("dispatch_started", destination=G.DESTINATION, remaining_wall_s=left,
                  transport_invoked=True, sent="unknown")
            run.events.append(J.EVENT_DISPATCH, send_id=send_id, audit_id=audit_id)
        # Outside the transition guard: a cancel or a consent change may arrive while the request is in flight.
        timeout = min(J.TIMEOUT_S, left)
        observed: dict[str, int] = {}
        raw: bytes | None = None
        too_large = False
        error: Exception | None = None
        start_http = run.monotonic()
        run._active_started = start_http
        try:
            raw, too_large = await gate._http_request(encoded, key, timeout, observed)
        except Exception as exc:  # noqa: BLE001 - never serialize transport/credential errors
            error = exc
        except BaseException:
            # This task itself was cancelled (server shutdown): delivery and usage are unknown. The unsettled
            # reservation stops egress on the next refresh; stop it in memory now as well.
            run.egress_unknown = True
            run.egress_stop_reason = "usage_unknown"
            raise
        finally:
            gate._charge_wall(run, audit_id, start_http)
        del key
        status = observed.get("status")
        if raw is None:
            code = ("external_timeout" if isinstance(error, (TimeoutError, httpx.TimeoutException))
                    else "transport_error")
            if status is None:
                audit("transport_failed", error_code=code, transport_invoked=True, sent="unknown")
                run.egress_unknown = True
                run.egress_stop_reason = "usage_unknown"
                return failed(code)
            usage = dict(UNKNOWN_USAGE)
            audit("response_received", http_status=status, response_sha256=None, response_oversized=False,
                  served_model=None, usage=usage, error_code=code, transport_invoked=True, sent=True)
            unknown_axes, overrun = run._settle_egress(audit_id, usage)
            audit("settled", unknown_axes=unknown_axes, overrun=overrun, transport_invoked=True, sent=True)
            return failed(code, usage=usage)
        data: Any = None
        if not too_large:
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError, RecursionError):
                data = None
        usage = G._usage(data)
        served = G._safe_model(data)
        audit("response_received", http_status=status,
              response_sha256=None if too_large else hashlib.sha256(raw).hexdigest(),
              response_oversized=too_large, served_model=served, usage=usage, transport_invoked=True, sent=True)
        unknown_axes, overrun = run._settle_egress(audit_id, usage)
        if run._time_left() <= 0:
            time_checkpoint()
        audit("settled", unknown_axes=unknown_axes, overrun=overrun, transport_invoked=True, sent=True)
        if status != 200:
            return failed("provider_http_error", served, usage)
        if too_large or len(raw) > J.MAX_RESPONSE_BYTES:
            return failed("response_invalid", served, usage)
        answer, reason = P.parse_choice(data, aliases)
        if answer is None:
            return failed(reason or "response_invalid", served, usage)
        return ScienceGateResult("accepted", None, answer=answer, audit_id=audit_id,
                                 requested_model=G.REQUEST_MODEL, served_model=served, usage=usage)
