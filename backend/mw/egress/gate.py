"""Single owner of the optional Jev Decisions HTTP boundary.

The run event stream is the durable audit and budget ledger. No caller receives an
outbound dictionary to dispatch independently.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import stat
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import anyio
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

from ..runtime.orchestrator import Run

DESTINATION = "https://openrouter.ai/api/alpha/decisions"
REQUEST_MODEL = "typesafe/jev-1.13"
SERVED_SNAPSHOT = "typesafe/jev-1.13-20260917"
QUESTION_VERSION = "inspection_view@1"
ACTIONS = ("summary", "all_contacts", "polar_contacts", "hydrophobic_contacts")
PROVIDER = {"data_collection": "deny", "zdr": True, "allow_fallbacks": False}
QUESTIONS = {"inspection_view": {
    "type": "choice",
    "instructions": ("Choose one local view for inspecting measured heavy-atom geometric contacts. "
                     "Proximity does not prove a hydrogen bond, affinity or stability."),
    "criteria": {
        "summary": "Overview of the measured contact set; use for an empty set.",
        "all_contacts": "Inspect all measured contact rows.",
        "polar_contacts": "Inspect measured N/O proximity rows; this is not a validated hydrogen bond.",
        "hydrophobic_contacts": "Inspect measured carbon-carbon proximity rows; this is not an energy estimate.",
    },
}}
MAX_RESPONSE_BYTES = 65_536
MAX_SAFE_INT = 9_007_199_254_740_991


def _finite_number(value: Any, *, maximum: float) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) and 0 <= number <= maximum else None


class EgressInspectionStateV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_: Literal["inspection_state@1"] = Field(alias="schema")
    measurement_method: Literal["heavy_atom_distance"]
    contact_count: StrictInt
    contacting_residue_count: StrictInt
    polar_contact_count: StrictInt
    hydrophobic_contact_count: StrictInt
    other_contact_count: StrictInt
    minimum_distance_A: float | None
    cutoff_A: float
    null_result: StrictBool

    @field_validator("minimum_distance_A", "cutoff_A", mode="before")
    @classmethod
    def finite_number(cls, value: Any) -> Any:
        if value is not None and _finite_number(value, maximum=1000) is None:
            raise ValueError("invalid numeric state")
        return value

    @model_validator(mode="after")
    def consistent(self) -> EgressInspectionStateV1:
        counts = (self.contact_count, self.contacting_residue_count, self.polar_contact_count,
                  self.hydrophobic_contact_count, self.other_contact_count)
        if any(type(value) is not int or not 0 <= value <= 10_000_000 for value in counts):
            raise ValueError("invalid contact counts")
        if (self.contacting_residue_count > self.contact_count or
                sum(counts[2:]) != self.contact_count or
                self.null_result != (self.contact_count == 0) or
                (self.contact_count == 0) != (self.minimum_distance_A is None) or
                (self.minimum_distance_A is not None and not 0 <= self.minimum_distance_A <= 1000) or
                not 2.5 <= self.cutoff_A <= 6.0 or
                (self.minimum_distance_A is not None and self.minimum_distance_A > self.cutoff_A)):
            raise ValueError("inconsistent inspection state")
        return self

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)


@dataclass(frozen=True)
class GateResult:
    status: Literal["accepted", "fallback"]
    reason_code: str
    action: str | None = None
    requested_model: str | None = None
    served_model: str | None = None
    audit_id: str | None = None
    usage: dict[str, Any] | None = None
    failure_class: str | None = None
    http_status: int | None = None


def _safe_int(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= MAX_SAFE_INT else None


def _safe_cost(value: Any) -> float | None:
    return _finite_number(value, maximum=MAX_SAFE_INT)


def _usage(data: Any) -> dict[str, Any]:
    raw = data.get("usage") if isinstance(data, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    in_tokens = _safe_int(raw.get("input_tokens"))
    out_tokens = _safe_int(raw.get("output_tokens"))
    total = in_tokens + out_tokens if in_tokens is not None and out_tokens is not None else None
    if total is not None and total > MAX_SAFE_INT:
        total = None
    return {"input_tokens": in_tokens, "output_tokens": out_tokens,
            "external_tokens": total, "cost": _safe_cost(raw.get("cost"))}


def _safe_model(data: Any) -> str | None:
    model = data.get("model") if isinstance(data, dict) else None
    return model if model == SERVED_SNAPSHOT else None


def _parse_answer(data: Any, state: EgressInspectionStateV1) -> tuple[str | None, str]:
    if not isinstance(data, dict):
        return None, "response_invalid"
    if "model" not in data or data["model"] is None:
        return None, "missing_model"
    served = _safe_model(data)
    if served is None or served != SERVED_SNAPSHOT:
        return None, "model_mismatch"
    answers = data.get("answers")
    answer = answers.get("inspection_view") if isinstance(answers, dict) else None
    if not isinstance(answer, dict) or answer.get("type") != "choice" or answer.get("choice") not in ACTIONS:
        return None, "response_invalid"
    confidence = answer.get("confidence")
    if "confidence" in answer and _finite_number(confidence, maximum=1) is None:
        return None, "response_invalid"
    probabilities = answer.get("probabilities")
    if ("probabilities" in answer and
            (not isinstance(probabilities, dict) or len(probabilities) > 4 or
             any(key not in ACTIONS or _finite_number(value, maximum=1) is None
                 for key, value in probabilities.items()))):
        return None, "response_invalid"
    action = answer["choice"]
    if ((action == "polar_contacts" and state.polar_contact_count == 0) or
            (action == "hydrophobic_contacts" and state.hydrophobic_contact_count == 0)):
        return None, "inapplicable_choice"
    return action, "accepted"


def env_or_root_dotenv_key() -> str | None:
    """Deferred fixed-root resolver; never invoked while local_only or dry_run."""
    value = os.environ.get("OPENROUTER_API_KEY")
    if value:
        return value
    path = Path(__file__).resolve().parents[3] / ".env"
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            return None
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"\'') or None
    except OSError:
        return None
    return None


class EgressGate:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None,
                 credential_resolver: Callable[[], str | None] = env_or_root_dotenv_key) -> None:
        self.transport = transport
        self.credential_resolver = credential_resolver

    @staticmethod
    def _audit(run: Run, stage: str, audit_id: str, **fields: Any) -> None:
        run.events.append("egress", stage=stage, audit_id=audit_id, **fields)

    async def _http_request(self, encoded: bytes, key: str, timeout: float,
                            observed: dict[str, int]) -> tuple[bytes, bool]:
        """Own the request and both closes inside a real total operation deadline."""
        client = httpx.AsyncClient(transport=self.transport, follow_redirects=False,
                                   trust_env=False, timeout=timeout)
        response: httpx.Response | None = None
        try:
            with anyio.fail_after(timeout):
                request = client.build_request(
                    "POST", DESTINATION, content=encoded,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
                response = await client.send(request, stream=True)
                observed["status"] = response.status_code
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > MAX_RESPONSE_BYTES:
                        return bytes(chunks), True
                return bytes(chunks), False
        finally:
            # Cleanup is bounded even when the operation's cancellation is active.
            with anyio.move_on_after(0.25, shield=True):
                if response is not None:
                    await response.aclose()
                await client.aclose()

    def request_jev(self, run: Run, state: EgressInspectionStateV1 | dict[str, Any]) -> GateResult:
        audit_id = f"eg_{uuid.uuid4().hex}"
        with run._mutation():
            operation_started = run.monotonic()

            def remaining_wall() -> float:
                # _mutation charges this overhead on exit; count it before dispatch too.
                return run._time_left() - max(0.0, run.monotonic() - operation_started)

            def wall_exhausted() -> GateResult:
                run.events.append("checkpoint", reason="budget", axis="wall_clock_s",
                                  usage=run.budget.wall_clock_s, limit=run.budget.limits.wall_clock_s)
                self._audit(run, "denied", audit_id, reason_code="budget_exhausted", mode="online",
                            transport_invoked=False, sent=False)
                return GateResult("fallback", "budget_exhausted", audit_id=audit_id)

            mode = run.egress_config.get("mode")
            if run.dry_run or mode != "online":
                reason = "dry_run" if run.dry_run else "local_only"
                self._audit(run, "denied", audit_id, reason_code=reason, mode=mode,
                            transport_invoked=False, sent=False)
                return GateResult("fallback", reason, audit_id=audit_id)
            config = run.egress_config.get("jev")
            if (not isinstance(config, dict) or config.get("enabled") is not True or
                    config.get("request_model") != REQUEST_MODEL or
                    config.get("allowed_served_models") != [SERVED_SNAPSHOT]):
                self._audit(run, "denied", audit_id, reason_code="missing_configuration", mode="online",
                            transport_invoked=False, sent=False)
                return GateResult("fallback", "missing_configuration", audit_id=audit_id)
            try:
                candidate = state.model_dump(by_alias=True, warnings=False) if isinstance(
                    state, EgressInspectionStateV1) else state
                approved = EgressInspectionStateV1.model_validate(candidate)
            except (ValueError, TypeError):
                self._audit(run, "denied", audit_id, reason_code="state_invalid", mode="online",
                            transport_invoked=False, sent=False)
                return GateResult("fallback", "state_invalid", audit_id=audit_id)
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                self._audit(run, "denied", audit_id, reason_code="sync_context_required", mode="online",
                            transport_invoked=False, sent=False)
                return GateResult("fallback", "sync_context_required", audit_id=audit_id)
            if remaining_wall() <= 0:
                return wall_exhausted()
            if run.egress_stop_reason:
                self._audit(run, "denied", audit_id, reason_code=run.egress_stop_reason, mode="online",
                            transport_invoked=False, sent=False)
                return GateResult("fallback", run.egress_stop_reason, audit_id=audit_id)
            run._check_cancelled()
            if not run.approved_expensive:
                run.events.append("approval_requested", gate="expensive_first_call",
                                  tool="decide_inspection_view", args={})
                self._audit(run, "denied", audit_id, reason_code="approval_required", mode="online",
                            transport_invoked=False, sent=False)
                return GateResult("fallback", "approval_required", audit_id=audit_id)
            try:
                key = self.credential_resolver()
            except Exception:  # noqa: BLE001 - resolver diagnostics may contain secrets
                key = None
            if remaining_wall() <= 0:
                return wall_exhausted()
            if not isinstance(key, str) or not key or any(ch in key for ch in "\r\n"):
                self._audit(run, "denied", audit_id, reason_code="missing_credential", mode="online",
                            transport_invoked=False, sent=False)
                return GateResult("fallback", "missing_credential", audit_id=audit_id)
            if remaining_wall() <= 0:
                return wall_exhausted()
            token_reserve, usd_reserve = 4096, 0.05
            for axis, value in (("expensive_calls", 1), ("external_tokens", token_reserve),
                                ("usd", usd_reserve)):
                if run.budget.would_exceed(**{axis: value}):
                    run.events.append("checkpoint", reason="budget", axis=axis,
                                      usage=getattr(run.budget, axis), limit=getattr(run.budget.limits, axis))
                    self._audit(run, "denied", audit_id, reason_code="budget_exhausted", mode="online",
                                transport_invoked=False, sent=False)
                    return GateResult("fallback", "budget_exhausted", audit_id=audit_id)
            remaining = remaining_wall()
            if remaining <= 0:
                return wall_exhausted()
            configured_timeout = config.get("timeout_s", 15)
            if _finite_number(configured_timeout, maximum=60) is None or configured_timeout <= 0:
                self._audit(run, "denied", audit_id, reason_code="missing_configuration", mode="online",
                            transport_invoked=False, sent=False)
                return GateResult("fallback", "missing_configuration", audit_id=audit_id)
            body = {"model": REQUEST_MODEL, "state": approved.wire(), "questions": QUESTIONS,
                    "provider": PROVIDER}
            encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            if len(encoded) > 16_384:
                self._audit(run, "denied", audit_id, reason_code="state_invalid", mode="online",
                            transport_invoked=False, sent=False)
                return GateResult("fallback", "state_invalid", audit_id=audit_id)
            if remaining_wall() <= 0:
                return wall_exhausted()
            payload_hash = hashlib.sha256(encoded).hexdigest()
            run.events.append("budget_reserved", audit_id=audit_id, expensive_calls=1,
                              external_tokens=token_reserve, usd=usd_reserve)
            run.budget.charge(expensive_calls=1, external_tokens=token_reserve, usd=usd_reserve)
            self._audit(run, "prepared", audit_id, mode="online", destination=DESTINATION,
                        requested_model=REQUEST_MODEL, question_version=QUESTION_VERSION,
                        body=body, payload_sha256=payload_hash,
                        reservation={"expensive_calls": 1, "external_tokens": token_reserve,
                                     "usd": usd_reserve},
                        transport_invoked=False, sent=False)
            run._check_cancelled()
            def refund_without_dispatch() -> GateResult:
                # Only a planned intent exists; no physical expensive attempt started.
                delta = {"expensive_calls": -1, "external_tokens": -token_reserve, "usd": -usd_reserve}
                run.events.append("egress_budget_settled", audit_id=audit_id, delta=delta,
                                  actual={"external_tokens": 0, "usd": 0}, unknown_axes=[])
                run.budget.charge(**delta)
                self._audit(run, "dispatch_skipped", audit_id, reason_code="budget_exhausted",
                            transport_invoked=False, sent=False)
                return wall_exhausted()

            remaining = remaining_wall()
            if remaining <= 0:
                return refund_without_dispatch()
            self._audit(run, "dispatch_started", audit_id, remaining_wall_s=remaining,
                        transport_invoked=True, sent="unknown")
            remaining = remaining_wall()
            if remaining <= 0:
                return refund_without_dispatch()
            timeout = min(float(configured_timeout), 15.0, remaining)
            start = run.monotonic()
            run._active_started = start
            observed: dict[str, int] = {}
            try:
                raw, too_large = anyio.run(self._http_request, encoded, key, timeout, observed)
                if run.monotonic() - start > timeout:
                    raise TimeoutError
            except Exception as exc:  # noqa: BLE001 - never serialize transport/credential errors
                self._charge_wall(run, audit_id, start)
                code = ("external_timeout" if isinstance(exc, (TimeoutError, httpx.TimeoutException))
                        else "transport_error")
                response_status = observed.get("status")
                if response_status is None:
                    self._audit(run, "transport_failed", audit_id, error_code=code,
                                transport_invoked=True, sent="unknown")
                else:
                    unknown_usage = {"input_tokens": None, "output_tokens": None,
                                     "external_tokens": None, "cost": None}
                    self._audit(run, "response_received", audit_id, http_status=response_status,
                                response_sha256=None, response_oversized=False, served_model=None,
                                usage=unknown_usage, error_code=code, transport_invoked=True, sent=True)
                    run._settle_egress(audit_id, unknown_usage)
                run.egress_unknown = True
                run.egress_stop_reason = "usage_unknown"
                return GateResult("fallback", code,
                                  requested_model=REQUEST_MODEL, audit_id=audit_id,
                                  failure_class="transient", http_status=response_status)
            self._charge_wall(run, audit_id, start)
            response_status = observed["status"]
            data: Any = None
            if not too_large:
                try:
                    data = json.loads(raw)
                except (ValueError, UnicodeError):
                    pass
            usage = _usage(data)
            served = _safe_model(data)
            self._audit(run, "response_received", audit_id, http_status=response_status,
                        response_sha256=hashlib.sha256(raw).hexdigest() if not too_large else None,
                        response_oversized=too_large, served_model=served, usage=usage,
                        transport_invoked=True, sent=True)
            unknown_axes, overrun = run._settle_egress(audit_id, usage)
            if run._time_left() <= 0:
                run.events.append("checkpoint", reason="budget", axis="wall_clock_s",
                                  audit_id=audit_id, usage=run.budget.wall_clock_s,
                                  limit=run.budget.limits.wall_clock_s)
            self._audit(run, "settled", audit_id, unknown_axes=unknown_axes, overrun=overrun,
                        transport_invoked=True, sent=True)
            if response_status != 200:
                failure = ("transient" if response_status in (408, 429) or response_status >= 500 else
                           "input_invalid" if response_status in (400, 422) else "fatal")
                return GateResult("fallback", "provider_http_error", requested_model=REQUEST_MODEL,
                                  served_model=served, audit_id=audit_id, usage=usage,
                                  failure_class=failure, http_status=response_status)
            if too_large:
                return GateResult("fallback", "response_invalid", requested_model=REQUEST_MODEL,
                                  served_model=served, audit_id=audit_id, usage=usage)
            action, reason = _parse_answer(data, approved)
            return GateResult("accepted" if action else "fallback", reason, action=action,
                              requested_model=REQUEST_MODEL, served_model=served, audit_id=audit_id,
                              usage=usage, http_status=response_status)

    @staticmethod
    def _charge_wall(run: Run, audit_id: str, start: float) -> None:
        elapsed = max(0.0, run.monotonic() - start)
        run.events.append("wall_charged", audit_id=audit_id, seconds=elapsed, reason="egress")
        run.budget.charge(wall_clock_s=elapsed)
        run._active_started = None
