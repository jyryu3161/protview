"""Event-backed, single-owner execution of validated tool calls."""
from __future__ import annotations

import fcntl
import hashlib
import math
import os
import re
import shutil
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..core.contracts import check_args
from ..core.errors import FailureClass, ToolFailure
from ..core.events import DecisionSource, EventLog, idempotency_key
from ..core.handles import Handle, ObjectStore
from ..tools.energetic import JOB_ONLY_TOOLS
from ..tools.registry import ToolContext, ToolRegistry
from .guards import TRANSIENT_DELAYS_S, Budget, BudgetLimits, LoopGuard, LoopStop

ExecutionMode = Literal["human", "autonomous"]
_LOCAL_LOCKS: dict[str, threading.Lock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()
_MODEL_ID = re.compile(r"[A-Za-z0-9._/-]{1,100}\Z")


def _validated_egress_config(config: Any) -> dict[str, Any]:
    """Persist only bounded policy fields, never credentials or arbitrary options."""
    if not isinstance(config, dict) or set(config) - {"mode", "jev"} or config.get("mode") not in {
        "online", "local_only", "dry_run"
    }:
        raise ValueError("invalid egress configuration")
    jev = config.get("jev")
    if jev is not None:
        if not isinstance(jev, dict) or set(jev) - {
            "enabled", "request_model", "allowed_served_models", "timeout_s"
        }:
            raise ValueError("invalid Jev configuration")
        if "enabled" in jev and type(jev["enabled"]) is not bool:
            raise ValueError("invalid Jev configuration")
        if "request_model" in jev and (not isinstance(jev["request_model"], str) or
                                       not _MODEL_ID.fullmatch(jev["request_model"])):
            raise ValueError("invalid Jev configuration")
        if "allowed_served_models" in jev and (
                not isinstance(jev["allowed_served_models"], list) or
                len(jev["allowed_served_models"]) > 4 or
                any(not isinstance(item, str) or not _MODEL_ID.fullmatch(item)
                    for item in jev["allowed_served_models"])):
            raise ValueError("invalid Jev configuration")
        if "timeout_s" in jev:
            value = jev["timeout_s"]
            try:
                finite = type(value) in (int, float) and math.isfinite(float(value))
            except (OverflowError, ValueError):
                finite = False
            if not finite or not 0 < value <= 60:
                raise ValueError("invalid Jev configuration")
    return config.copy()


def _event_safe(value: Any) -> Any:
    """Keep rejected malformed input auditable without writing invalid JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _event_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_event_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


class ApprovalRequired(Exception):
    def __init__(self, gate: str, tool: str, args: dict[str, Any], reason: str) -> None:
        super().__init__(reason)
        # Exception.args is Python's positional message tuple, so keep the
        # pending tool arguments under a distinct attribute.
        self.gate, self.tool, self.requested_args, self.reason = gate, tool, args, reason


class RunCancelled(Exception):
    pass


_LINK_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


@dataclass(frozen=True)
class ExecutionLink:
    """Internal (execution_id, step_id, operation_id) link for one analysis-workflow operation.

    Constructed only by server code; no HTTP request field can supply it. Callbacks are optional:
    ``admit(info)`` runs under ``Run._transition()`` in the same critical section as child admission
    and may raise to refuse; ``stopped()`` reports this execution's scoped Stop (never the run-wide
    cancel marker); ``before_attempt(info)`` runs under ``Run._transition()`` before every physical
    attempt so the caller can durably count it or raise to refuse. Callbacks must not re-enter
    ``Run._transition()`` or the run owner.
    """
    execution_id: str
    step_id: str
    operation_id: str
    admit: Callable[[dict[str, Any]], None] | None = field(default=None, compare=False, repr=False)
    stopped: Callable[[], bool] | None = field(default=None, compare=False, repr=False)
    before_attempt: Callable[[dict[str, Any]], None] | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        for value in (self.execution_id, self.step_id, self.operation_id):
            if not isinstance(value, str) or not _LINK_ID.fullmatch(value):
                raise ValueError("invalid execution link identifier")

    def record(self) -> dict[str, str]:
        return {"execution_id": self.execution_id, "step_id": self.step_id,
                "operation_id": self.operation_id}

    def is_stopped(self) -> bool:
        return self.stopped is not None and bool(self.stopped())


class ExecutionStopped(Exception):
    """A linked operation ended because its execution was stopped; the run itself is not cancelled."""

    def __init__(self, stage: str) -> None:
        super().__init__(f"execution stopped {stage}")
        self.stage = stage


def checked_link(value: Any) -> ExecutionLink | None:
    if value is not None and not isinstance(value, ExecutionLink):
        raise TypeError("execution_link must be an internal ExecutionLink")
    return value


def link_fields(value: ExecutionLink | dict[str, Any] | None) -> dict[str, Any]:
    """Event kwargs for a link; empty when unlinked so historical events stay byte-identical."""
    if value is None:
        return {}
    return {"execution_link": value.record() if isinstance(value, ExecutionLink) else dict(value)}


@dataclass
class Run:
    run_id: str
    run_dir: Path
    registry: ToolRegistry
    dry_run: bool = False
    seed: int = 0
    sleep: Callable[[float], None] = time.sleep
    budget: Budget = field(default_factory=Budget)
    guard: LoopGuard = field(default_factory=LoopGuard)
    monotonic: Callable[[], float] = time.monotonic
    utc: Callable[[], float] = time.time
    approved_expensive: bool = False
    egress_config: dict[str, Any] = field(default_factory=lambda: {"mode": "local_only"})

    def __post_init__(self) -> None:
        self.egress_config = _validated_egress_config(self.egress_config)
        self._requested_limits = self.budget.limits.model_dump()
        self._requested_guard = self._guard_config()
        self._requested_egress = self.egress_config.copy()
        self.run_dir = Path(self.run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.events = EventLog(self.run_dir / "events.jsonl")
        self.store = ObjectStore(self.run_dir, self.run_id, self.events)
        self._cancel_path = self.run_dir / "cancel.request"
        self._transition_path = self.run_dir / "transitions.lock"
        self._active_started: float | None = None
        # Construction is observational when an execution owner is live.
        try:
            with self._owner():
                if not list(self.events.read()):
                    self.events.append("run_started", run_id=self.run_id, dry_run=self.dry_run,
                                       seed=self.seed, budget_limits=self.budget.limits.model_dump(),
                                       loop_guards=self._guard_config(), egress=self.egress_config)
                self.store.rebuild_from_events()
                self._refresh()
                self._reconcile_egress()
        except ToolFailure as exc:
            if exc.detail.get("busy") is not True:
                raise
        self._refresh()

    def _guard_config(self) -> dict[str, int]:
        return {key: getattr(self.guard, key) for key in
                ("no_progress_steps", "repeated_call_hash", "oscillation_window")}

    @contextmanager
    def _owner(self):
        path = str(self.run_dir.resolve())
        with _LOCAL_LOCKS_GUARD:
            lock = _LOCAL_LOCKS.setdefault(path, threading.Lock())
        if not lock.acquire(blocking=False):
            raise ToolFailure(FailureClass.transient, "run execution owner is busy", detail={"busy": True})
        descriptor = -1
        try:
            descriptor = os.open(self.run_dir / "execution.lock", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ToolFailure(FailureClass.transient, "run execution owner is busy",
                                  detail={"busy": True}) from exc
            yield
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            lock.release()

    @contextmanager
    def _mutation(self):
        with self._owner():
            self.store.rebuild_from_events()
            self._refresh()
            self._reconcile_orphans()
            self._refresh()
            started = self.monotonic()
            charged_before = self.budget.wall_clock_s
            try:
                yield
            finally:
                if self._active_started is not None:
                    # A BaseException escaped an active attempt/backoff. The next
                    # owner reconciles that interval from its start event.
                    self._active_started = None
                else:
                    active_charges = self.budget.wall_clock_s - charged_before
                    overhead = max(0.0, self.monotonic() - started - active_charges)
                    if overhead:
                        self.events.append("wall_charged", seconds=overhead, reason="runtime_overhead")
                        self.budget.charge(wall_clock_s=overhead)

    @contextmanager
    def _transition(self):
        """Short cross-process guard shared by cancellation, reservation and job terminal CAS."""
        path = str(self.run_dir.resolve()) + ":transition"
        with _LOCAL_LOCKS_GUARD:
            lock = _LOCAL_LOCKS.setdefault(path, threading.Lock())
        with lock:
            fd = os.open(self._transition_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                os.close(fd)

    def reserve_attempt(self, attempt_id: str, root_call_id: str, tool: str,
                        args: dict[str, Any], *, job_id: str | None = None,
                        before_reserve: Callable[[], None] | None = None) -> dict[str, Any]:
        """One durable expensive unit per physical attempt; caller holds the run owner."""
        with self._transition():
            self._refresh()
            # Admission belongs to the same short critical section as the debit.
            # A claimed job is harmless here; any unclosed dispatch is not.
            self._check_jobs_clear()
            existing = next((e for e in self._events if e["type"] == "budget_reserved" and
                             e.get("attempt_id") == attempt_id), None)
            if existing:
                if (existing.get("root_call_id") != root_call_id or existing.get("tool") != tool or
                        existing.get("expensive_calls") != 1):
                    raise ValueError("attempt reservation identity mismatch")
                return existing
            if self._cancel_path.exists() or self.cancelled:
                raise RunCancelled("run cancelled")
            if job_id is not None:
                latest = next((e for e in reversed(self._events) if e.get("job_id") == job_id and
                               e["type"] in {"job_cancel_requested", "job_terminal", "job_retry_queued"}), None)
                if latest is not None and latest["type"] != "job_retry_queued":
                    raise RunCancelled("job cancelled or terminal")
                # A reservation is a physical attempt even if the owner dies before
                # it can append dispatch_intent. Count durable identities, not intents.
                used = {e["attempt_id"] for e in self._events
                        if e["type"] == "budget_reserved" and
                        e.get("root_call_id") == root_call_id and e.get("tool") == tool}
                if len(used) >= 4:
                    raise ToolFailure(FailureClass.resource_exceeded,
                                      "root recovery allowance exhausted")
            if self._time_left() <= 0:
                self._checkpoint_budget(tool, args, "wall_clock_s")
            if not self.approved_expensive:
                self.events.append("approval_requested", gate="expensive_first_call", tool=tool, args=args)
                raise ApprovalRequired("expensive_first_call", tool, args,
                                       "first expensive call needs approval")
            if self.budget.would_exceed(expensive_calls=1):
                self._checkpoint_budget(tool, args, "expensive_calls")
            if before_reserve is not None:
                # Linked attempts: scoped stop check + durable attempt count, same critical section.
                before_reserve()
            event = self.events.append("budget_reserved", attempt_id=attempt_id,
                                       root_call_id=root_call_id, tool=tool, expensive_calls=1)
            self.budget.charge(expensive_calls=1)
            return event

    def _refresh(self) -> None:
        events = list(self.events.read())
        if not events or events[0].get("type") != "run_started" or events[0].get("run_id") != self.run_id:
            raise ValueError("run identity or start event is invalid")
        start = events[0]
        default_limits = BudgetLimits().model_dump()
        default_guard = {key: getattr(LoopGuard(), key) for key in
                         ("no_progress_steps", "repeated_call_hash", "oscillation_window")}
        # M0/M1 compatibility: absent limits mean the historical project defaults.
        limits = start.get("budget_limits", default_limits)
        guard_config = start.get("loop_guards", default_guard)
        egress_config = start.get("egress", {"mode": "local_only"})
        if (self.dry_run != start["dry_run"] or self.seed != start["seed"] or
                self._requested_limits not in (limits, default_limits) or
                self._requested_guard not in (guard_config, default_guard) or
                self._requested_egress not in (egress_config, {"mode": "local_only"})):
            raise ValueError("incompatible run configuration")
        self.dry_run, self.seed = start["dry_run"], start["seed"]
        self.egress_config = egress_config
        self.guard = LoopGuard(**guard_config)
        self.budget = Budget(limits=BudgetLimits(**limits))
        self.approved_expensive = False
        self.cancelled = False
        self.egress_unknown = False
        self.egress_stop_reason: str | None = None
        self.branches: dict[str, dict[str, Any]] = {}
        self._events = events
        reservations = [e["attempt_id"] for e in events if e["type"] == "budget_reserved" and
                        e.get("attempt_id")]
        if len(reservations) != len(set(reservations)):
            raise ValueError("duplicate physical attempt reservation")
        ledger_charged_calls = {event.get("call_id") for event in events
                                if event["type"] == "wall_charged" and event.get("reason") == "attempt"}
        for event in events[1:]:
            kind = event["type"]
            if kind == "budget_limit_updated":
                self.budget.limits = BudgetLimits(**event["limits"])
            elif kind == "budget_reserved":
                self.budget.charge(**{axis: event[axis] for axis in
                                      ("expensive_calls", "external_tokens", "usd") if axis in event})
            elif kind == "egress_budget_settled":
                self.budget.charge(**event["delta"])
            elif kind == "wall_charged":
                self.budget.charge(wall_clock_s=event["seconds"])
            elif (kind == "tool_succeeded" and "budget_limits" not in start and
                  not event.get("cached") and event.get("call_id") not in ledger_charged_calls):
                self.budget.charge(wall_clock_s=event.get("duration_s", 0))
            elif kind == "approval_resolved" and event.get("gate") == "expensive_first_call":
                self.approved_expensive = bool(event["approved"])
            elif kind == "viewer_consent_changed":
                if event.get("policy") != "viewer_model@1" or type(event.get("enabled")) is not bool:
                    raise ValueError("invalid viewer consent event")
                self.egress_config = {**self.egress_config,
                                      "mode": "online" if event["enabled"] else "local_only"}
            elif kind in ("run_cancelled", "cancel_requested"):
                self.cancelled = True
            elif kind == "branch_proposed":
                branch = self._branch(event["branch_id"])
                branch["counts"][event["key"]] += 1
                branch["recent"].append(event["key"])
            elif kind == "branch_observed":
                branch = self._branch(event["branch_id"])
                handle = event.get("output_handle")
                if handle and handle not in branch["seen"]:
                    branch["seen"].add(handle)
                    branch["no_progress"] = 0
                    branch["recent"] = []
                else:
                    branch["no_progress"] += 1
            elif kind == "checkpoint" and event.get("branch_id"):
                self._branch(event["branch_id"])["stopped"] = event["reason"]
        reserved = {event["audit_id"]: event for event in events if event["type"] == "budget_reserved"
                    and "audit_id" in event}
        settled = {event["audit_id"]: event for event in events if event["type"] == "egress_budget_settled"}
        unknown = bool(reserved.keys() - settled.keys()) or any(event.get("unknown_axes")
                                                                for event in settled.values())
        overrun = any(
            any(actual is not None and actual > reservation.get(axis, 0)
                for axis, actual in event.get("actual", {}).items())
            for audit_id, event in settled.items() if (reservation := reserved.get(audit_id))
        ) or any(getattr(self.budget, axis) > getattr(self.budget.limits, axis)
                 for axis in ("external_tokens", "usd"))
        self.egress_unknown = unknown or overrun
        self.egress_stop_reason = "usage_unknown" if unknown else "budget_exhausted" if overrun else None

    def _settle_egress(self, audit_id: str, usage: dict[str, Any]) -> tuple[list[str], bool]:
        """Persist one audit's per-axis actuals; reservation remains for unknown axes."""
        events = list(self.events.read())
        if any(item["type"] == "egress_budget_settled" and item["audit_id"] == audit_id for item in events):
            raise ValueError("egress audit already settled")
        reservation = next((item for item in events if item["type"] == "budget_reserved" and
                            item.get("audit_id") == audit_id), None)
        if reservation is None:
            raise ValueError("missing egress reservation")
        actual = {"external_tokens": usage.get("external_tokens"), "usd": usage.get("cost")}
        unknown_axes = [axis for axis, value in actual.items() if value is None]
        delta = {axis: value - reservation[axis] for axis, value in actual.items() if value is not None}
        self.events.append("egress_budget_settled", audit_id=audit_id, delta=delta,
                           actual=actual, unknown_axes=unknown_axes)
        self.budget.charge(**delta)
        overrun = any(value is not None and value > reservation[axis] for axis, value in actual.items()) or any(
            getattr(self.budget, axis) > getattr(self.budget.limits, axis) for axis in actual)
        if unknown_axes or overrun:
            self.egress_unknown = True
            self.egress_stop_reason = "usage_unknown" if unknown_axes else "budget_exhausted"
            self.events.append("checkpoint", reason="egress_usage_unknown" if unknown_axes else "budget",
                               audit_id=audit_id, unknown_axes=unknown_axes, overrun=overrun)
        return unknown_axes, overrun

    def _branch(self, branch_id: str) -> dict[str, Any]:
        return self.branches.setdefault(branch_id, {"counts": Counter(), "recent": [],
                                                     "seen": set(), "no_progress": 0, "stopped": None})

    def _reconcile_orphans(self) -> None:
        self._reconcile_egress()
        finished = {event["call_id"] for event in self._events if
                    event["type"] in ("tool_succeeded", "tool_failed", "tool_interrupted")}
        for event in self._events:
            if event["type"] != "tool_called" or event["call_id"] in finished:
                continue
            elapsed = self.utc() - event["ts"]
            if elapsed < 0:
                self.events.append("clock_anomaly", call_id=event["call_id"],
                                   observed_elapsed_s=elapsed)
            already = sum(item["seconds"] for item in self._events if item["type"] == "wall_charged"
                          and item.get("call_id") == event["call_id"])
            remaining = event.get("remaining_wall_s", self._time_left())
            charge = min(max(0.0, elapsed - already), max(0.0, remaining - already),
                         max(0.0, self._time_left()))
            self.events.append("wall_charged", call_id=event["call_id"], seconds=charge,
                               reason="orphan_recovery")
            self.budget.charge(wall_clock_s=charge)
            self.events.append("tool_interrupted", call_id=event["call_id"],
                               root_call_id=event.get("root_call_id", event["call_id"]),
                               reason="owner_lost", **link_fields(event.get("execution_link")))
            if self._time_left() <= 0:
                self.events.append("checkpoint", reason="budget", axis="wall_clock_s",
                                   usage=self.budget.wall_clock_s,
                                   limit=self.budget.limits.wall_clock_s)
        settled_backoffs = {event["backoff_id"] for event in self._events if
                            event["type"] in ("backoff_completed", "backoff_interrupted")}
        for event in self._events:
            if event["type"] != "backoff_started" or event["backoff_id"] in settled_backoffs:
                continue
            elapsed = self.utc() - event["ts"]
            if elapsed < 0:
                self.events.append("clock_anomaly", backoff_id=event["backoff_id"],
                                   observed_elapsed_s=elapsed)
            already = sum(item["seconds"] for item in self._events
                          if item["type"] == "wall_charged" and
                          item.get("backoff_id") == event["backoff_id"])
            remaining = event["remaining_wall_s"]
            charge = min(max(0.0, elapsed - already), max(0.0, remaining - already),
                         max(0.0, self._time_left()))
            self.events.append("wall_charged", backoff_id=event["backoff_id"],
                               call_id=event["after_call_id"], seconds=charge,
                               reason="orphan_backoff_recovery")
            self.events.append("backoff_interrupted", backoff_id=event["backoff_id"],
                               root_call_id=event["root_call_id"],
                               after_call_id=event["after_call_id"], reason="owner_lost")
            self.budget.charge(wall_clock_s=charge)
            if self._time_left() <= 0:
                self.events.append("checkpoint", reason="budget", axis="wall_clock_s",
                                   usage=self.budget.wall_clock_s,
                                   limit=self.budget.limits.wall_clock_s)

    def _reconcile_egress(self) -> None:
        settled_egress = {event["audit_id"] for event in self._events
                          if event["type"] == "egress_budget_settled"}
        received = {event["audit_id"]: event for event in self._events
                    if event["type"] == "egress" and event.get("stage") == "response_received"}
        for audit_id, response in received.items():
            if audit_id not in settled_egress:
                self._settle_egress(audit_id, response.get("usage", {}))
        charged_egress = {item.get("audit_id") for item in self._events
                          if item["type"] == "wall_charged" and item.get("reason") == "egress"}
        skipped_egress = {item.get("audit_id") for item in self._events
                          if (item["type"] == "egress" and item.get("stage") == "dispatch_skipped") or
                          (item["type"] == "egress_budget_settled" and
                           item.get("delta", {}).get("expensive_calls") == -1)}
        for event in self._events:
            if event["type"] != "egress" or event.get("stage") != "dispatch_started":
                continue
            if event["audit_id"] in charged_egress or event["audit_id"] in skipped_egress:
                continue
            elapsed = self.utc() - event["ts"]
            if elapsed < 0:
                self.events.append("clock_anomaly", audit_id=event["audit_id"],
                                   observed_elapsed_s=elapsed)
            charge = min(max(0.0, elapsed), max(0.0, event["remaining_wall_s"]),
                         max(0.0, self._time_left()))
            self.events.append("wall_charged", audit_id=event["audit_id"], seconds=charge,
                               reason="egress")
            self.budget.charge(wall_clock_s=charge)

    def _check_cancelled(self) -> None:
        if self._cancel_path.exists() or self.cancelled:
            with self._transition():
                if not any(e["type"] == "run_cancelled" for e in self.events.read()):
                    self.events.append("run_cancelled", reason="requested")
                self.cancelled = True
            raise RunCancelled("run cancelled")

    def _check_jobs_clear(self) -> None:
        """An unclosed physical job blocks new tool execution until reconciliation."""
        status: dict[str, str] = {}
        for event in self.events.read():
            kind = event["type"]
            if kind == "job_submitted":
                status[event["job"]["job_id"]] = "queued"
            elif kind == "job_claimed":
                status[event["job_id"]] = "claimed"
            elif kind == "job_dispatch_intent":
                status[event["job_id"]] = "running"
            elif kind == "job_terminal":
                status[event["job_id"]] = event["status"]
            elif kind == "job_retry_queued":
                status[event["job_id"]] = "queued"
        active = next((job_id for job_id, state in status.items() if state == "running"), None)
        if active:
            raise ToolFailure(FailureClass.precondition, "running job needs verified cleanup before new work",
                              detail={"job_id": active, "reason_code": "job_cleanup_pending"})

    def cancel(self) -> None:
        """Signal the execution owner without waiting for its lock."""
        with self._transition():
            if self._cancel_path.exists():
                return
            descriptor = os.open(self._cancel_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                stream.write("cancel\n")
                stream.flush()
                os.fsync(stream.fileno())
            self.events.append("cancel_requested")

    def decide(self, source: DecisionSource, question: str, answer: Any, **meta: Any) -> None:
        with self._mutation():
            self.events.append("decision", source=source, question=question, answer=answer, **meta)

    def approve(self, gate: str, by: str = "human") -> None:
        with self._mutation():
            self.events.append("approval_resolved", gate=gate, approved=True, by=by)
            self._refresh()

    def update_limits(self, limits: BudgetLimits, *, by: str = "human") -> None:
        with self._mutation():
            self.events.append("budget_limit_updated", limits=limits.model_dump(), by=by)
            self._refresh()

    def budget_snapshot(self) -> dict[str, Any]:
        """Expose current active elapsed time without charging idle/offline time."""
        snapshot = self.budget.snapshot()
        if self._active_started is not None:
            snapshot["wall_clock_s"]["used"] += max(0.0, self.monotonic() - self._active_started)
        return snapshot

    def _validated(self, tool: str, args: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        spec = self.registry.specs.get(tool)
        if spec is None or tool not in self.registry.impls:
            raise ToolFailure(FailureClass.input_invalid, f"unknown or unimplemented tool '{tool}'")
        if tool in JOB_ONLY_TOOLS:
            raise ToolFailure(FailureClass.precondition, "submit through the durable job lane",
                              detail={"reason_code": "job_only_tool"})
        if not isinstance(args, dict):
            raise ToolFailure(FailureClass.input_invalid, "tool args must be an object")
        normalized = check_args(spec, args, self.store.kind_of)
        for name in spec.accepts:
            value = normalized[name]
            for handle in value if isinstance(value, list) else [value]:
                self.store.load(handle)
        if not self.dry_run and tool in self.registry.unavailable:
            raise ToolFailure(FailureClass.precondition, self.registry.unavailable[tool])
        return spec, normalized

    def _source_input(self, tool: str, args: dict[str, Any],
                      source_bytes: bytes | None,
                      source_format: str | None) -> tuple[bytes | None, str | None]:
        if tool != "load_structure":
            return source_bytes, source_format
        source = args["source"]
        if source_format is not None and not isinstance(source_format, str):
            raise ToolFailure(FailureClass.input_invalid, "source format must be a string")
        if source_bytes is not None and not isinstance(source_bytes, bytes):
            raise ToolFailure(FailureClass.input_invalid, "source bytes must be bytes")
        if source_bytes is None and source.startswith(("pdb:", "afdb:")):
            raise ToolFailure(FailureClass.precondition, "remote loading requires M3 egress adapter")
        suffix = Path(source).suffix.lstrip(".").lower()
        if source_bytes is None and source_format is not None and source_format.lower() != suffix:
            raise ToolFailure(FailureClass.input_invalid, "source format conflicts with path suffix")
        fmt = (source_format if source_format is not None else suffix).lower()
        if fmt not in {"pdb", "cif", "mmcif"}:
            raise ToolFailure(FailureClass.input_invalid, "supported formats are PDB and mmCIF")
        if source_bytes is None:
            try:
                source_bytes = Path(source).read_bytes()
            except OSError as exc:
                raise ToolFailure(FailureClass.input_invalid, "source bytes unavailable") from exc
        return source_bytes, fmt

    def _key(self, tool: str, version: str, args: dict[str, Any],
             source_bytes: bytes | None, source_format: str | None) -> str:
        effective = dict(args)
        effective["_run_seed"] = self.seed
        effective["_dry_run"] = self.dry_run
        if tool == "load_structure":
            if source_bytes is None:
                raise ValueError("load_structure key requires bound source bytes")
            effective["_source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
            effective["_source_format"] = source_format
        if tool == "compute_interface_sasa":
            from ..tools.sasa import dependencies
            effective["_scientific_dependencies"] = dependencies()
        return idempotency_key(tool, version, effective)

    def _verified(self, event: dict[str, Any], expected_kind: str) -> Handle:
        output = Handle(**event["output"])
        if output.kind != expected_kind or self.store.kind_of(output.handle) != expected_kind:
            raise ValueError("cached output kind mismatch")
        content = self.store.load(output.handle)
        meta = self.store.meta(output.handle)
        preview = (content[:5] if isinstance(content, list) else
                   content.get("rows", [])[:5]
                   if expected_kind == "interaction_set" and isinstance(content, dict) else [])
        if (meta["schema"] != output.schema_ or meta["summary"] != output.summary or
                meta["null_result"] != output.null_result or output.preview != preview):
            raise ValueError("cached output metadata mismatch")
        return output

    def _checkpoint_budget(self, tool: str, args: dict[str, Any], axis: str) -> None:
        self.events.append("checkpoint", reason="budget", axis=axis,
                           usage=getattr(self.budget, axis), limit=getattr(self.budget.limits, axis),
                           pending_action={"tool": tool, "args": args})
        raise ApprovalRequired("budget", tool, args, f"budget axis '{axis}' exhausted")

    def _time_left(self) -> float:
        return self.budget.limits.wall_clock_s - self.budget.wall_clock_s

    def _charge_time(self, started: float, *, reason: str, call_id: str | None = None,
                     backoff_id: str | None = None) -> float:
        duration = max(0.0, self.monotonic() - started)
        self.events.append("wall_charged", seconds=duration, reason=reason, call_id=call_id,
                           backoff_id=backoff_id)
        self.budget.charge(wall_clock_s=duration)
        if self._active_started == started:
            self._active_started = None
        return duration

    def _propose(self, branch_id: str, key: str, tool: str, proposal_id: str) -> None:
        branch = self._branch(branch_id)
        if branch["stopped"]:
            raise LoopStop(branch["stopped"], {"branch_id": branch_id})
        self.events.append("branch_proposed", branch_id=branch_id, proposal_id=proposal_id,
                           tool=tool, key=key)
        branch["counts"][key] += 1
        branch["recent"].append(key)
        if branch["counts"][key] > self.guard.repeated_call_hash:
            self._stop_branch(branch_id, "repeated_call_hash")
        window = branch["recent"][-self.guard.oscillation_window:]
        if (len(window) == self.guard.oscillation_window and len(set(window)) == 2 and
                all(window[i] != window[i + 1] for i in range(len(window) - 1))):
            self._stop_branch(branch_id, "oscillation")

    def _observe(self, branch_id: str | None, proposal_id: str, handle: str | None) -> None:
        if branch_id is None:
            return
        branch = self._branch(branch_id)
        self.events.append("branch_observed", branch_id=branch_id, proposal_id=proposal_id,
                           output_handle=handle)
        if handle and handle not in branch["seen"]:
            branch["seen"].add(handle)
            branch["no_progress"] = 0
            branch["recent"] = []
        else:
            branch["no_progress"] += 1
        if branch["no_progress"] >= self.guard.no_progress_steps:
            self._stop_branch(branch_id, "no_progress")

    def _stop_branch(self, branch_id: str, reason: str) -> None:
        self.events.append("checkpoint", reason=reason, branch_id=branch_id)
        self._branch(branch_id)["stopped"] = reason
        raise LoopStop(reason, {"branch_id": branch_id})

    def call(self, tool: str, args: dict[str, Any], *, decided_by: DecisionSource = "rule",
             execution_mode: ExecutionMode = "human", branch_id: str | None = None,
             source_bytes: bytes | None = None, source_format: str | None = None,
             execution_link: ExecutionLink | None = None) -> Handle:
        link = checked_link(execution_link)
        if execution_mode not in ("human", "autonomous") or (execution_mode == "autonomous" and not branch_id):
            raise ToolFailure(FailureClass.input_invalid, "autonomous calls require a branch_id")
        with self._mutation():
            self._check_cancelled()
            proposal_id = f"proposal_{uuid.uuid4().hex}"
            try:
                spec, normalized = self._validated(tool, args)
                source_bytes, source_format = self._source_input(tool, normalized,
                                                                 source_bytes, source_format)
                key = self._key(tool, spec.version, normalized, source_bytes, source_format)
            except ToolFailure as failure:
                self.events.append("proposal_rejected", proposal_id=proposal_id, root_call_id=proposal_id,
                                   tool=tool, args=_event_safe(args), **_event_safe(failure.to_dict()),
                                   **link_fields(link))
                if branch_id and execution_mode == "autonomous":
                    self._propose(branch_id, idempotency_key(tool, "invalid", {"repr": repr(args)}),
                                  tool, proposal_id)
                    self._observe(branch_id, proposal_id, None)
                raise
            if link is not None:
                # Child admission: the caller's validation and the admission record share one
                # short transition, before any proposal, cache observation or physical attempt.
                with self._transition():
                    if link.admit is not None:
                        link.admit({"lane": "run_call", "tool": tool, "version": spec.version, "key": key,
                                    "args": normalized, "proposal_id": proposal_id,
                                    "branch_id": branch_id, "execution_mode": execution_mode,
                                    "decided_by": decided_by})
                    self.events.append("execution_call_admitted", proposal_id=proposal_id, tool=tool,
                                       key=key, **link_fields(link))
            active_branch = branch_id if execution_mode == "autonomous" else None
            done = self.events.completed().get(key) if spec.idempotent else None
            if link is not None and not done:
                # A linked call that cannot start (run wall budget, unclosed job) records no branch
                # proposal: guards must not rise from calls that never started. Same checks as the chain.
                if self._time_left() <= 0:
                    self._checkpoint_budget(tool, normalized, "wall_clock_s")
                self._check_jobs_clear()
            if active_branch:
                self._propose(active_branch, key, tool, proposal_id)
            if done:
                out = self._verified(done, "planned_call" if self.dry_run and spec.cost_class == "expensive"
                                     else spec.emits)
                self.events.append("cache_hit", observation_id=proposal_id, proposal_id=proposal_id,
                                   tool=tool, key=key, args=normalized, output=out.model_dump(by_alias=True),
                                   source_call_id=done["call_id"], branch_id=active_branch,
                                   **link_fields(link))
                self._observe(active_branch, proposal_id, out.handle)
                return out
            self._check_jobs_clear()
            try:
                out = self._execute_chain(tool, normalized, key, proposal_id, None, "initial",
                                          decided_by, execution_mode, branch_id,
                                          source_bytes, source_format, link=link)
            except (ToolFailure, ApprovalRequired, RunCancelled, ExecutionStopped):
                self._observe(active_branch, proposal_id, None)
                raise
            self._observe(active_branch, proposal_id, out.handle)
            return out

    def _execute_chain(self, tool: str, args: dict[str, Any], key: str, root: str,
                       parent: str | None, attempt_kind: str, decided_by: DecisionSource,
                       mode: ExecutionMode, branch_id: str | None,
                       source_bytes: bytes | None = None, source_format: str | None = None,
                       allow_transient: bool = True, link: ExecutionLink | None = None) -> Handle:
        spec, args = self._validated(tool, args)
        used = sum(event["attempt_kind"] == "transient_retry" for event in self.events.read()
                   if event["type"] == "tool_called" and event.get("root_call_id") == root)
        while True:
            self._check_cancelled()
            if self._time_left() <= 0:
                self._checkpoint_budget(tool, args, "wall_clock_s")
            if spec.cost_class == "expensive" and self.dry_run:
                call_id = f"call_{uuid.uuid4().hex}"
                detail = {"tool": tool, "arguments": args, "cost_class": "expensive",
                          "unmet_conditions": ["real execution disabled by dry_run"],
                          "plan_only": True}
                stub = self.registry.stubs.get(tool)
                if stub:
                    # Stubs may supply planning detail, never scientific output.
                    detail["planning_stub_available"] = True
                out = self.store.put("planned_call", "planned_call@1", detail,
                                     produced_by=call_id, summary={"tool": tool, "plan_only": True})
                self.events.append("tool_called", tool=tool, key=key, call_id=call_id,
                                   root_call_id=root, parent_call_id=parent, args=args,
                                   attempt_kind=attempt_kind, decided_by=decided_by,
                                   execution_mode=mode, branch_id=branch_id, version=spec.version,
                                   plan_only=True, remaining_wall_s=self._time_left(), **link_fields(link))
                self.events.append("tool_succeeded", tool=tool, key=key, call_id=call_id,
                                   output=out.model_dump(by_alias=True), null_result=False,
                                   plan_only=True, duration_s=0, **link_fields(link))
                return out
            call_id = f"call_{uuid.uuid4().hex}"
            gate = None
            if link is not None:
                def gate(call_id: str = call_id, attempt_kind: str = attempt_kind,
                         parent: str | None = parent) -> None:
                    self._linked_attempt_gate(link, {
                        "lane": "run_call", "tool": tool, "key": key, "call_id": call_id,
                        "root_call_id": root, "parent_call_id": parent, "attempt_kind": attempt_kind,
                        "cost_class": spec.cost_class, "execution_link": link.record()})
            if spec.cost_class == "expensive":
                self.reserve_attempt(call_id, root, tool, args, before_reserve=gate)
            elif gate is not None:
                with self._transition():
                    gate()
            self.events.append("tool_called", tool=tool, key=key, call_id=call_id,
                               root_call_id=root, parent_call_id=parent, args=args,
                               attempt_kind=attempt_kind, decided_by=decided_by,
                               execution_mode=mode, branch_id=branch_id, version=spec.version,
                               remaining_wall_s=self._time_left(), ts=self.utc(), **link_fields(link))
            start = self.monotonic()
            self._active_started = start
            ctx = ToolContext(store=self.store, call_id=call_id, dry_run=self.dry_run, seed=self.seed,
                              source_bytes=source_bytes, source_format=source_format,
                              remaining_s=lambda started=start: max(0, self._time_left() - (self.monotonic() - started)),
                              check_cancelled=self._check_cancelled)
            failure: ToolFailure | None = None
            out: Handle | None = None
            try:
                out = self.registry.impls[tool](ctx, **args)
                if not isinstance(out, Handle) or out.kind != spec.emits:
                    raise ToolFailure(FailureClass.fatal, "tool returned wrong output kind")
                self._verified({"output": out.model_dump(by_alias=True)}, spec.emits)
            except RunCancelled:
                self.events.append("tool_interrupted", call_id=call_id, root_call_id=root,
                                   reason="cancelled", **link_fields(link))
                self._charge_time(start, reason="attempt", call_id=call_id)
                raise
            except ToolFailure as exc:
                failure = exc
            except Exception as exc:  # noqa: BLE001 - unexpected tool exceptions are fatal events
                failure = ToolFailure(FailureClass.fatal, "unexpected tool exception",
                                      detail={"diagnostic": f"{type(exc).__name__}: {exc}"})
            duration = self._charge_time(start, reason="attempt", call_id=call_id)
            if failure:
                self.events.append("tool_failed", tool=tool, key=key, call_id=call_id,
                                   root_call_id=root, parent_call_id=parent, args=args,
                                   **_event_safe(failure.to_dict()), **link_fields(link))
            else:
                assert out is not None
                self.events.append("tool_succeeded", tool=tool, key=key, call_id=call_id,
                                   output=out.model_dump(by_alias=True), duration_s=duration,
                                   null_result=out.null_result, **link_fields(link))
            self._check_cancelled()
            if self._time_left() <= 0:
                self._checkpoint_budget(tool, args, "wall_clock_s")
            if failure is None:
                return out
            if failure.cls != FailureClass.transient or not allow_transient or used >= len(TRANSIENT_DELAYS_S):
                raise failure
            if link is not None and link.is_stopped():
                # Scoped Stop: the finished attempt stays recorded and charged; no backoff or retry.
                self._record_stop(link, "before_backoff", root, call_id)
            delay = TRANSIENT_DELAYS_S[used]
            if spec.cost_class == "expensive" and self.budget.would_exceed(expensive_calls=1):
                self._checkpoint_budget(tool, args, "expensive_calls")
            if self._time_left() < delay:
                self._checkpoint_budget(tool, args, "wall_clock_s")
            self._check_cancelled()
            backoff_id = f"backoff_{uuid.uuid4().hex}"
            backoff_utc = self.utc()
            remaining_wall_s = self._time_left()
            self.events.append("backoff_started", backoff_id=backoff_id, root_call_id=root,
                               after_call_id=call_id, retry_index=used + 1, delay_s=delay,
                               remaining_wall_s=remaining_wall_s,
                               deadline_utc=backoff_utc + remaining_wall_s, ts=backoff_utc)
            backoff_start = self.monotonic()
            self._active_started = backoff_start
            slept = False
            try:
                self.sleep(delay)
                slept = True
            finally:
                self._charge_time(backoff_start, reason="backoff", call_id=call_id,
                                  backoff_id=backoff_id)
                self.events.append("backoff_completed" if slept else "backoff_interrupted",
                                   backoff_id=backoff_id, root_call_id=root,
                                   after_call_id=call_id,
                                   **({} if slept else {"reason": "sleep_interrupted"}))
            self._check_cancelled()
            used += 1
            parent = call_id
            attempt_kind = "transient_retry"

    def _record_stop(self, link: ExecutionLink, stage: str, root: str, after_call_id: str | None) -> None:
        self.events.append("execution_call_stopped", stage=stage, root_call_id=root,
                           after_call_id=after_call_id, **link_fields(link))
        raise ExecutionStopped(stage)

    def _linked_attempt_gate(self, link: ExecutionLink, info: dict[str, Any]) -> None:
        """Caller holds ``_transition()``: scoped stop check, then the durable attempt hook."""
        if link.is_stopped():
            self._record_stop(link, "before_attempt", info["root_call_id"], info["parent_call_id"])
        if link.before_attempt is not None:
            link.before_attempt(info)

    def _failed(self, failed_id: str) -> dict[str, Any]:
        event = next((item for item in reversed(list(self.events.read()))
                      if item["type"] in ("tool_failed", "proposal_rejected") and
                      (item.get("call_id") == failed_id or item.get("proposal_id") == failed_id)), None)
        if not event:
            raise ToolFailure(FailureClass.input_invalid, "unknown or nonfailed call")
        return event

    def repair_call(self, failed_call_id: str, corrected_args: dict[str, Any],
                    *, source_bytes: bytes | None = None, source_format: str | None = None) -> Handle:
        with self._mutation():
            self._check_jobs_clear()
            failed = self._failed(failed_call_id)
            root = failed.get("root_call_id", failed_call_id)
            attempt = next((event for event in self.events.read() if event["type"] == "tool_called"
                            and event.get("call_id") == failed_call_id), None)
            if attempt and attempt.get("attempt_kind") == "prerequisite":
                raise ToolFailure(FailureClass.input_invalid, "prerequisite has no nested repair")
            if failed["error"] != FailureClass.input_invalid.value:
                raise ToolFailure(FailureClass.input_invalid, "call is not an input failure")
            if any(event["type"] == "tool_called" and event.get("root_call_id") == root and
                   event.get("attempt_kind") == "argument_repair" for event in self.events.read()):
                raise ToolFailure(FailureClass.input_invalid, "argument repair already used")
            spec, fixed = self._validated(failed["tool"], corrected_args)
            original = failed["args"]
            try:
                old = check_args(spec, original, self.store.kind_of)
            except ToolFailure:
                old = original
            if fixed == old:
                raise ToolFailure(FailureClass.input_invalid, "repair must change effective arguments")
            source_bytes, source_format = self._source_input(failed["tool"], fixed,
                                                             source_bytes, source_format)
            key = self._key(failed["tool"], spec.version, fixed, source_bytes, source_format)
            return self._execute_chain(failed["tool"], fixed, key, root, failed_call_id,
                                       "argument_repair", "human", "human", None,
                                       source_bytes, source_format)

    def satisfy_precondition(self, failed_call_id: str) -> Handle:
        with self._mutation():
            self._check_jobs_clear()
            failed = self._failed(failed_call_id)
            root = failed.get("root_call_id", failed_call_id)
            if failed["error"] != FailureClass.precondition.value:
                raise ToolFailure(FailureClass.input_invalid, "call has no precondition failure")
            if any(event["type"] == "tool_called" and event.get("root_call_id") == root and
                   event.get("attempt_kind") == "prerequisite" for event in self.events.read()):
                raise ToolFailure(FailureClass.input_invalid, "prerequisite repair already used")
            fix = failed.get("fix")
            if not isinstance(fix, dict) or fix.get("tool") != "prepare_structure":
                raise ToolFailure(FailureClass.precondition, "no allowlisted prerequisite")
            args = failed["args"]
            target = next((name for name, value in args.items()
                           if value == fix.get("args", {}).get("structure") and
                           name in self.registry.specs[failed["tool"]].accepts), None)
            if target is None or "prepared_structure" not in self.registry.specs[failed["tool"]].accepts[target]:
                raise ToolFailure(FailureClass.precondition, "undeclared prerequisite target")
            pre_spec, pre_args = self._validated("prepare_structure", fix["args"])
            pre_key = self._key("prepare_structure", pre_spec.version, pre_args, None, None)
            pre = self._execute_chain("prepare_structure", pre_args, pre_key, root, failed_call_id,
                                      "prerequisite", "rule", "human", None, allow_transient=False)
            if pre.kind != "prepared_structure":
                raise ToolFailure(FailureClass.precondition, "prerequisite returned wrong kind")
            pre_call = next(event["call_id"] for event in reversed(list(self.events.read()))
                            if event["type"] == "tool_succeeded" and event["output"]["handle"] == pre.handle)
            self.events.append("decision", source="rule", question="prerequisite_evidence",
                               answer={"root_call_id": root, "failed_call_id": failed_call_id,
                                       "prerequisite_call_id": pre_call, "output_handle": pre.handle,
                                       "accepted_kind": pre.kind, "target_argument": target})
            rebound = dict(args)
            rebound[target] = pre.handle
            spec, rebound = self._validated(failed["tool"], rebound)
            key = self._key(failed["tool"], spec.version, rebound, None, None)
            return self._execute_chain(failed["tool"], rebound, key, root, pre_call,
                                       "prerequisite_retry", "rule", "human", None)


def replay(events_path: Path, new_dir: Path, registry: ToolRegistry, run_id: str) -> set[str]:
    """Restore immutable objects and state from events; never rerun science."""
    source = Path(events_path)
    target = Path(new_dir) / "events.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)
    log = EventLog(target)
    started = next((event for event in log.read() if event["type"] == "run_started"), None)
    if started is None or started.get("run_id") != run_id:
        raise ValueError("event log does not match requested run")
    run = Run(run_id=run_id, run_dir=new_dir, registry=registry,
              dry_run=started["dry_run"], seed=started["seed"],
              egress_config=started.get("egress", {"mode": "local_only"}))
    return run.store.handles()
