"""Viewer-only Jev boundary through the existing EgressGate transport owner."""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from ..viewer_intents import (
    CAMERAS,
    DISPOSITIONS,
    MAX_BODY_BYTES,
    QUESTION_VERSION,
    REPRESENTATIONS,
    SELECTIONS,
    EgressViewerIntentV1,
    effective_online,
    intent_live,
    viewer_used,
)
from .gate import (
    DESTINATION,
    MAX_RESPONSE_BYTES,
    PROVIDER,
    REQUEST_MODEL,
    SERVED_SNAPSHOT,
    EgressGate,
    _finite_number,
    _safe_model,
    _usage,
)

TOKEN_RESERVE = 16_384
USD_RESERVE = 0.05
REQUEST_CAP = 4
INSTRUCTIONS = (
    "Interpret only a local molecular viewer request. Choose clarify for ambiguous target identity. "
    "Choose unsupported for scientific calculations, file/network operations, code execution, reports, jobs or approvals. "
    "Use keep for unspecified axes. Choose at most one value on each axis. "
    "A geometric contact is not a validated hydrogen bond, affinity or stability prediction."
)


@dataclass(frozen=True)
class ViewerGateResult:
    status: Literal["accepted", "rejected"]
    reason_code: str
    answers: dict[str, Any] | None = None
    audit_id: str | None = None
    requested_model: str | None = None
    served_model: str | None = None
    usage: dict[str, Any] | None = None
    projection_sha256: str | None = None


def questions(catalog: list[dict[str, Any]], selected_target: str | None = None) -> dict[str, Any]:
    selection = {name: ("No requested selection change." if name == "keep" else
                        "Explicitly remove current selection.")
                 for name in SELECTIONS}
    for entry in catalog:
        if "model_number" not in entry and entry["alias"] != selected_target:
            continue
        identity = ", ".join(f"{key}={entry[key]}" for key in (
            "category", "model_number", "chain_auth", "seq_auth", "icode", "chain_label", "seq_label") if key in entry)
        selection[entry["alias"]] = f"Explicitly requested exact target {entry['alias']} ({identity})."
    return {
        "disposition": {"type": "choice", "instructions": INSTRUCTIONS,
                        "criteria": {name: {"apply": "Viewer request has one unambiguous supported action.",
                                            "clarify": "Target or action is ambiguous or contradictory.",
                                            "unsupported": "Outside the supported viewer action scope."}[name]
                                     for name in DISPOSITIONS}},
        "representation": {"type": "choice", "instructions": "Choose one representation; keep if unspecified.",
                           "criteria": {name: {"keep": "Keep current representation.",
                                               "cartoon": "Cartoon molecular representation.",
                                               "ball_and_stick": "Ball and stick molecular representation.",
                                               "surface": "Molecular surface representation."}[name]
                                        for name in REPRESENTATIONS}},
        "selection": {"type": "choice", "instructions": (
            "The selected_target field describes existing scene context, not an instruction to select it again. "
            "Choose clear when the user explicitly requests deselect, clear selection, 선택 해제, or 선택을 해제. "
            "Choose keep when no selection change is requested. Choose a target alias only when the user "
            "explicitly asks to select or focus that exact target. If clear is requested, do not select the "
            "current target merely because selected_target is present."),
                      "criteria": selection},
        "camera": {"type": "choice", "instructions": "Choose one camera operation; keep if unspecified.",
                   "criteria": {name: {"keep": "Keep current camera.",
                                       "focus_selected": "Focus the selected exact target.",
                                       "zoom_in": "Zoom in by the fixed local factor 1.25.",
                                       "zoom_out": "Zoom out by the fixed local factor 0.8.",
                                       "reset": "Reset camera."}[name]
                                for name in CAMERAS}},
    }


def body_for(state: EgressViewerIntentV1) -> bytes:
    # Pydantic instances are mutable; validate the serialized boundary again.
    state = EgressViewerIntentV1.model_validate(state.wire())
    body = {"model": REQUEST_MODEL, "state": state.wire(),
            "questions": questions([entry.model_dump(exclude_none=True) for entry in state.catalog],
                                   state.selected_target),
            "provider": PROVIDER}
    encoded = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > MAX_BODY_BYTES:
        raise ValueError("viewer model request exceeds 64 KiB")
    return encoded


def _valid_answer_shape(data: Any, choices: set[str]) -> bool:
    if (not isinstance(data, dict) or set(data) - {"type", "choice", "confidence", "probabilities"}
            or data.get("type") != "choice" or not isinstance(data.get("choice"), str)
            or data["choice"] not in choices):
        return False
    if "confidence" in data and _finite_number(data["confidence"], maximum=1) is None:
        return False
    probabilities = data.get("probabilities")
    return "probabilities" not in data or (isinstance(probabilities, dict)
        and len(probabilities) <= len(choices)
        and all(key in choices and _finite_number(value, maximum=1) is not None
                for key, value in probabilities.items()))


def parse_answers(data: Any, catalog: list[dict[str, Any]],
                  selected_target: str | None = None) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(data, dict):
        return None, "response_invalid"
    if data.get("model") is None:
        return None, "missing_model"
    if data.get("model") != SERVED_SNAPSHOT:
        return None, "model_mismatch"
    answers = data.get("answers")
    expected = {"disposition": set(DISPOSITIONS), "representation": set(REPRESENTATIONS),
                "selection": set(SELECTIONS) | {entry["alias"] for entry in catalog
                                                if "model_number" in entry or entry["alias"] == selected_target},
                "camera": set(CAMERAS)}
    if not isinstance(answers, dict) or set(answers) != set(expected):
        return None, "response_invalid"
    if any(not _valid_answer_shape(answers[name], values) for name, values in expected.items()):
        return None, "response_invalid"
    return answers, "accepted"


async def request_viewer(gate: EgressGate, run: Any, state: EgressViewerIntentV1,
                         intent_id: str) -> ViewerGateResult:
    """One owned physical request. Cancellation uses the short transition/event lane."""
    audit_id = f"eg_{uuid.uuid4().hex}"
    projection_sha = hashlib.sha256(json.dumps(state.wire(), sort_keys=True, ensure_ascii=False,
                                               separators=(",", ":")).encode()).hexdigest()

    def result(reason: str, **kw: Any) -> ViewerGateResult:
        return ViewerGateResult("rejected", reason, audit_id=audit_id,
                                projection_sha256=projection_sha, **kw)

    with run._mutation():
        started = run.monotonic()
        def remaining() -> float:
            return run._time_left() - max(0.0, run.monotonic() - started)

        if run.dry_run or not effective_online(run):
            reason = "dry_run" if run.dry_run else "local_only"
            gate._audit(run, "denied", audit_id, reason_code=reason,
                        transport_invoked=False, sent=False, viewer_intent_id=intent_id)
            return result(reason)
        if not intent_live(run, intent_id):
            gate._audit(run, "denied", audit_id, reason_code="cancelled",
                        transport_invoked=False, sent=False, viewer_intent_id=intent_id)
            return result("cancelled")
        if run.egress_stop_reason:
            return result(run.egress_stop_reason)
        if viewer_used(run) >= REQUEST_CAP:
            gate._audit(run, "denied", audit_id, reason_code="viewer_cap_exhausted",
                        transport_invoked=False, sent=False, viewer_intent_id=intent_id)
            return result("viewer_cap_exhausted")
        if remaining() <= 0:
            return result("budget_exhausted")
        try:
            encoded = body_for(state)
        except (ValueError, TypeError):
            return result("projection_invalid")
        for axis, amount in (("expensive_calls", 1), ("external_tokens", TOKEN_RESERVE), ("usd", USD_RESERVE)):
            if run.budget.would_exceed(**{axis: amount}):
                gate._audit(run, "denied", audit_id, reason_code="budget_exhausted",
                            transport_invoked=False, sent=False, viewer_intent_id=intent_id)
                return result("budget_exhausted")
        # No credential is touched before mode, cap, projection and budget checks.
        try:
            key = gate.credential_resolver()
        except Exception:  # noqa: BLE001 - resolver diagnostics may contain secrets
            key = None
        if not isinstance(key, str) or not key or any(ch in key for ch in "\r\n"):
            gate._audit(run, "denied", audit_id, reason_code="missing_credential",
                        transport_invoked=False, sent=False, viewer_intent_id=intent_id)
            return result("missing_credential")
        if remaining() <= 0 or not intent_live(run, intent_id):
            return result("cancelled" if not intent_live(run, intent_id) else "budget_exhausted")
        with run._transition():
            if any(event["type"] == "viewer_dispatch_started" and event.get("intent_id") == intent_id
                   for event in run.events.read()):
                return result("already_dispatched")
            if not intent_live(run, intent_id) or viewer_used(run) >= REQUEST_CAP:
                return result("cancelled" if not intent_live(run, intent_id) else "viewer_cap_exhausted")
            for axis, amount in (("expensive_calls", 1), ("external_tokens", TOKEN_RESERVE), ("usd", USD_RESERVE)):
                if run.budget.would_exceed(**{axis: amount}):
                    return result("budget_exhausted")
            run.events.append("budget_reserved", audit_id=audit_id, viewer_intent_id=intent_id,
                              expensive_calls=1, external_tokens=TOKEN_RESERVE, usd=USD_RESERVE)
            run.budget.charge(expensive_calls=1, external_tokens=TOKEN_RESERVE, usd=USD_RESERVE)
            gate._audit(run, "prepared", audit_id, destination=DESTINATION,
                        requested_model=REQUEST_MODEL, question_version=QUESTION_VERSION,
                        payload_sha256=hashlib.sha256(encoded).hexdigest(),
                        projection_sha256=projection_sha,
                        reservation={"expensive_calls": 1, "external_tokens": TOKEN_RESERVE, "usd": USD_RESERVE},
                        transport_invoked=False, sent=False, viewer_intent_id=intent_id)
        if remaining() <= 0 or not intent_live(run, intent_id):
            delta = {"expensive_calls": -1, "external_tokens": -TOKEN_RESERVE, "usd": -USD_RESERVE}
            run.events.append("egress_budget_settled", audit_id=audit_id, delta=delta,
                              actual={"external_tokens": 0, "usd": 0}, unknown_axes=[])
            run.budget.charge(**delta)
            gate._audit(run, "dispatch_skipped", audit_id, reason_code="cancelled_or_deadline",
                        transport_invoked=False, sent=False, viewer_intent_id=intent_id)
            return result("cancelled" if not intent_live(run, intent_id) else "budget_exhausted")
        with run._transition():
            if not intent_live(run, intent_id):
                delta = {"expensive_calls": -1, "external_tokens": -TOKEN_RESERVE, "usd": -USD_RESERVE}
                run.events.append("egress_budget_settled", audit_id=audit_id, delta=delta,
                                  actual={"external_tokens": 0, "usd": 0}, unknown_axes=[])
                run.budget.charge(**delta)
                return result("cancelled")
            gate._audit(run, "dispatch_started", audit_id, destination=DESTINATION,
                        remaining_wall_s=remaining(), viewer_intent_id=intent_id,
                        transport_invoked=True, sent="unknown")
            if remaining() <= 0 or not intent_live(run, intent_id):
                delta = {"expensive_calls": -1, "external_tokens": -TOKEN_RESERVE, "usd": -USD_RESERVE}
                run.events.append("egress_budget_settled", audit_id=audit_id, delta=delta,
                                  actual={"external_tokens": 0, "usd": 0}, unknown_axes=[])
                run.budget.charge(**delta)
                gate._audit(run, "dispatch_skipped", audit_id, reason_code="cancelled_or_deadline",
                            transport_invoked=False, sent=False, viewer_intent_id=intent_id)
                return result("cancelled" if not intent_live(run, intent_id) else "budget_exhausted")
            run.events.append("viewer_dispatch_started", intent_id=intent_id, audit_id=audit_id)
        observed: dict[str, int] = {}
        timeout = min(15.0, remaining())
        start_http = run.monotonic()
        run._active_started = start_http
        task = asyncio.create_task(gate._http_request(encoded, key, timeout, observed))
        cancelled = False
        raw: bytes | None = None
        too_large = False
        failure: Exception | None = None
        try:
            while not task.done():
                done, _ = await asyncio.wait({task}, timeout=0.05)
                if not done and not intent_live(run, intent_id):
                    cancelled = True
                    task.cancel()
                    break
            try:
                raw, too_large = await task
            except asyncio.CancelledError:
                cancelled = True
            except Exception as exc:  # noqa: BLE001 - sanitize transport diagnostics
                failure = exc
        except asyncio.CancelledError:
            cancelled = True
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            gate._charge_wall(run, audit_id, start_http)
        status = observed.get("status")
        if raw is None:
            code = "cancelled" if cancelled else "external_timeout" if isinstance(failure, (TimeoutError, httpx.TimeoutException)) else "transport_error"
            if status is None:
                gate._audit(run, "transport_failed", audit_id, error_code=code,
                            transport_invoked=True, sent="unknown", viewer_intent_id=intent_id)
                run.egress_unknown = True
                run.egress_stop_reason = "usage_unknown"
            else:
                usage = {"input_tokens": None, "output_tokens": None, "external_tokens": None, "cost": None}
                gate._audit(run, "response_received", audit_id, http_status=status,
                            usage=usage, error_code=code, transport_invoked=True, sent=True,
                            viewer_intent_id=intent_id)
                run._settle_egress(audit_id, usage)
            return result(code, requested_model=REQUEST_MODEL)
        data: Any = None
        if not too_large:
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                pass
        usage = _usage(data)
        served = _safe_model(data)
        gate._audit(run, "response_received", audit_id, http_status=status,
                    response_sha256=hashlib.sha256(raw).hexdigest() if not too_large else None,
                    response_oversized=too_large, served_model=served, usage=usage,
                    transport_invoked=True, sent=True, viewer_intent_id=intent_id)
        run._settle_egress(audit_id, usage)
        if cancelled or not intent_live(run, intent_id):
            return result("cancelled", requested_model=REQUEST_MODEL, served_model=served, usage=usage)
        if status != 200:
            return result("provider_http_error", requested_model=REQUEST_MODEL,
                          served_model=served, usage=usage)
        if too_large or len(raw) > MAX_RESPONSE_BYTES:
            return result("response_invalid", requested_model=REQUEST_MODEL,
                          served_model=served, usage=usage)
        answers, reason = parse_answers(data, [entry.model_dump(exclude_none=True) for entry in state.catalog],
                                        state.selected_target)
        if answers is None:
            return result(reason, requested_model=REQUEST_MODEL, served_model=served, usage=usage)
        return ViewerGateResult("accepted", "accepted", answers=answers, audit_id=audit_id,
                                requested_model=REQUEST_MODEL, served_model=served, usage=usage,
                                projection_sha256=projection_sha)
