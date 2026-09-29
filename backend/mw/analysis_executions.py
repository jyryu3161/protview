"""M13 analysis executions over immutable ``analysis_plan@1`` plans.

An execution is a mutable, event-backed record (events prefixed ``analysis_``; the legacy
``inspect_complex`` ``workflow_*`` events and their interpreter are untouched). It references one
recorded plan and moves only through explicit requests: plan approval/revocation, one-step Advance,
one explicit retry per step, scoped Stop and the existing run-level scientific approval.

Science runs only through ``Run.call`` and ``JobQueue``; reports only through the existing builders.
Every child carries an internal ``ExecutionLink`` (execution_id, step_id, operation_id) whose admission
callback re-validates the durable dispatch record under ``Run._transition()``. Step outcomes are never
taken from in-memory return values: after a child returns (or after a crash) the same reconciliation
derives the outcome from the linked durable child events, so the normal path and crash windows 1–4
share one code path. Reads never append events.

Locks: a short same-run workflow lock (``analysis.lock``) serializes admission, dispatch records and
outcome records and is never held while ``Run.call``, a job or a report builder runs. A per-execution
driver lock is held for the whole Advance/Retry and makes a concurrent Advance/Retry of the same
execution ``409 busy``; Stop and revoke never wait for it. Lock order: driver → workflow →
``Run._transition()``; link callbacks run under ``Run._transition()`` and take no lock.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
import re
import threading
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from . import analysis_plans as plans
from . import chemical_reports, comparison_reports, method_reports, openmm_reports, pocket_reports
from . import reports as inspection_reports
from .core.contracts import check_args
from .core.errors import FailureClass, ToolFailure
from .core.handles import canonical_json
from .jobs.queue import JobQueue, require_completed_chemical_handle
from .runtime.guards import LoopStop
from .runtime.orchestrator import ApprovalRequired, ExecutionLink, ExecutionStopped, RunCancelled
from .tools.structural import structure_residues

EXECUTION_SCHEMA = "analysis_execution@1"
SUMMARY_KIND = "workflow_summary"
SUMMARY_SCHEMA = "workflow_summary@1"
MAX_EXECUTIONS_PER_RUN = 100
MAX_SUMMARY_BYTES = 1024 * 1024
STATUSES = ("plan_only", "awaiting_approval", "ready", "executing", "waiting_job",
            "awaiting_scientific_approval", "blocked", "failed", "cancelled", "complete")
STEP_STATUSES = ("pending", "dispatched", "waiting_job", "completed", "failed", "interrupted", "cancelled",
                 "blocked")
EXECUTION_ID_RE = re.compile(r"exec_[0-9a-f]{32}\Z")
STEP_ID_RE = re.compile(r"s0[1-8]\Z")

CREATED = "analysis_execution_created"
ADMITTED = "analysis_request_admitted"
FINISHED = "analysis_request_completed"
APPROVED = "analysis_plan_approved"
REVOKED = "analysis_approval_revoked"
STOP = "analysis_stop_requested"
BLOCKED = "analysis_execution_blocked"
DISPATCHED = "analysis_step_dispatched"
RELEASED = "analysis_dispatch_released"
DEFERRED = "analysis_step_deferred"
STEP_DONE = "analysis_step_completed"
STEP_FAILED = "analysis_step_failed"
ATTEMPT = "analysis_attempt_recorded"
REFUSED = "analysis_attempt_refused"
SCIENTIFIC = "analysis_scientific_approval_recorded"
COMPLETE = "analysis_execution_completed"
EVENT_TYPES = (CREATED, ADMITTED, FINISHED, APPROVED, REVOKED, STOP, BLOCKED, DISPATCHED, RELEASED, DEFERRED,
               STEP_DONE, STEP_FAILED, ATTEMPT, REFUSED, SCIENTIFIC, COMPLETE)

JOB_TOOLS = frozenset({"openmm_protein_minimize", "prepare_chemical_structure", "compute_chemical_interactions",
                       "detect_pockets"})
# JobQueue failure messages for a job timeout (recorded with error class resource_exceeded).
JOB_TIMEOUT_MESSAGES = frozenset({"job timeout", "job timeout during guardian bootstrap"})
BUSY_CODES = frozenset({"global_concurrency_busy", "global_job_cleanup_pending", "global_job_ledger_unavailable",
                        "job_cleanup_pending"})
# analysis_type -> (module, builder function, builder label used by the report admission, saved reader).
REPORTS: dict[str, tuple[Any, str, str, str]] = {
    "interaction_contacts": (inspection_reports, "build_inspection_report", "inspection", "saved_report"),
    "interface_sasa": (method_reports, "build_method_report", "interface_sasa", "saved_method_report"),
    "atom_distance": (comparison_reports, "build_comparison_report", "comparison", "saved_comparison_report"),
    "rigid_alignment": (comparison_reports, "build_comparison_report", "comparison", "saved_comparison_report"),
    "chemical_interactions": (chemical_reports, "build_chemical_report", "chemical", "saved_chemical_report"),
    "pocket_detection": (pocket_reports, "build_pocket_report", "pocket", "saved_pocket_report"),
    "openmm_protein_minimize": (openmm_reports, "build_openmm_report", "openmm", "saved_openmm_report"),
}
MESSAGES = {
    "run_budget_exhausted": "run 예산이 소진되어 시작하지 않았습니다. 기존 한도 변경 절차 뒤 다시 실행하세요.",
    "run_busy": "run이 다른 작업을 처리 중이라 시작하지 않았습니다. 잠시 뒤 다시 실행하세요.",
    "not_started": "이전 요청이 자식 작업을 시작하기 전에 끝나 시작하지 않은 것으로 조정했습니다.",
    "scientific_approval_required": "작업 시작에 run의 첫 비싼 계산 승인이 필요합니다.",
    "shared_job_waiting": "수동으로 만든 같은 작업을 기다리는 중이며, 시작·취소는 원래 화면에서 합니다.",
    "shared_job_failed": "관찰하던 공유 작업이 실패하거나 취소되었습니다. 이 실행은 그 작업을 재시도하지 않습니다.",
    "shared_job_detached": "중지는 관찰만 끊었고 공유 작업은 그대로 둡니다.",
    "compatibility_changed": "승인한 계획의 방법·도구 호환성이 달라졌습니다. 새 계획을 만드세요.",
    "identity_changed": "전처리 결과에서 선택한 식별자가 요청과 다릅니다. 다른 식별자로 바꾸지 않았습니다.",
    "max_physical_attempts": "실행당 물리 시도 한도(24회)를 넘었습니다.",
    "max_active_wall": "실행 활동 시간 한도(1800초)를 넘었습니다.",
    "recovery_error": "인과 기록이 충돌하거나 손상되어 복구할 수 없습니다.",
}


class AnalysisError(Exception):
    """A typed HTTP refusal: nothing was admitted or changed by this request."""

    def __init__(self, status: int, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.detail = status, code, message, detail or {}


class _RecoveryError(Exception):
    pass


# Test-only fault injection (crash windows); production never sets it.
_FAULT_HOOK: Callable[[str], None] | None = None


def _fault(stage: str) -> None:
    if _FAULT_HOOK is not None:
        _FAULT_HOOK(stage)


def _job_queue(run: Any) -> JobQueue:
    return JobQueue(run)


# ---------------------------------------------------------------------------------------------- locks
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _thread_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


_HELD = threading.local()


@contextmanager
def _workflow_lock(run: Any):
    """Short same-run workflow owner, distinct from the nonreentrant run owner; held for transitions only.

    Reentrant within one thread so read helpers can run under it (driver-lock probes happen only here).
    """
    path = run.run_dir / "analysis.lock"
    key = str(path.resolve())
    held = getattr(_HELD, "keys", None)
    if held is None:
        held = _HELD.keys = set()
    if key in held:
        yield
        return
    with _thread_lock(key):
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            held.add(key)
            try:
                yield
            finally:
                held.discard(key)
        finally:
            os.close(descriptor)


class _DriverLock:
    """Per-execution driver-operation marker; held for a whole Advance/Retry, never waited on."""

    def __init__(self, run: Any, execution_id: str) -> None:
        self.path = run.run_dir / f"analysis-driver-{execution_id}.lock"
        self.lock = _thread_lock(str(self.path.resolve()))
        self.descriptor = -1

    def try_acquire(self) -> bool:
        if not self.lock.acquire(blocking=False):
            return False
        try:
            self.descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            self._close()
            self.lock.release()
            return False
        except BaseException:
            self._close()
            self.lock.release()
            raise

    def _close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1

    def release(self) -> None:
        self._close()
        self.lock.release()


def _driver_live(run: Any, execution_id: str) -> bool:
    """True while another request holds this execution's driver lock.

    The probe runs under the workflow lock, which every driver acquisition also holds, so a probe can never
    make a concurrent Advance/Retry fail its non-blocking acquisition (no spurious ``busy``).
    """
    probe = _DriverLock(run, execution_id)
    if not probe.path.exists():
        return probe.lock.locked()
    with _workflow_lock(run):
        if not probe.try_acquire():
            return True
        probe.release()
        return False


# ---------------------------------------------------------------------------------------------- events and fold
def _own(events: list[dict[str, Any]], execution_id: str) -> list[dict[str, Any]]:
    return [event for event in events if event.get("type") in EVENT_TYPES and
            event.get("execution_id") == execution_id]


def _append(run: Any, kind: str, **data: Any) -> dict[str, Any]:
    with run._transition():
        return run.events.append(kind, **data)


def _link_record(execution_id: str, step_id: str, operation_id: str) -> dict[str, str]:
    return {"execution_id": execution_id, "step_id": step_id, "operation_id": operation_id}


def _fold(events: list[dict[str, Any]], execution_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    own = _own(events, execution_id)
    if not own or own[0]["type"] != CREATED:
        raise KeyError(execution_id)
    created = own[0]
    order = [step["step_id"] for step in plan["steps"]]
    steps = {sid: {"status": "pending", "dispatch": None, "dispatches": [], "result": None, "failure": None,
                   "retryable": False, "retries": 0, "deferred": None, "attempts": 0} for sid in order}
    state: dict[str, Any] = {
        "execution_id": execution_id, "plan_handle": created["plan_handle"], "plan_sha256": created["plan_sha256"],
        "created_seq": created["seq"], "dry_run": created["initial_status"] == "plan_only", "revision": len(own),
        "approval": None, "ever_dispatched": False, "stop": None, "blocked": None, "complete": None,
        "steps": steps, "order": order, "requests": {}, "attempts": [], "refusals": [], "notice": None,
        "scientific": [], "seqs": [event["seq"] for event in own], "revoked": []}
    for event in own[1:]:
        kind = event["type"]
        step = steps.get(event.get("step_id")) if event.get("step_id") is not None else None
        if event.get("step_id") is not None and step is None:
            raise ValueError("analysis event names an unknown step")
        if kind == ADMITTED:
            if event["request_id"] in state["requests"]:
                raise ValueError("duplicate analysis request admission")
            state["requests"][event["request_id"]] = {"action": event["action"], "state": "pending",
                                                      "outcome": None, "seq": event["seq"]}
        elif kind == FINISHED:
            request = state["requests"].get(event["request_id"])
            if request is None or request["state"] != "pending":
                raise ValueError("analysis request completion without pending admission")
            request.update(state="completed", outcome=event["outcome"])
        elif kind == APPROVED:
            state["approval"] = event
        elif kind == REVOKED:
            state["revoked"].append(event)
            if event["outcome"] == "awaiting_approval":
                state["approval"] = None
        elif kind == STOP:
            state["stop"] = state["stop"] or event
        elif kind == BLOCKED:
            state["blocked"] = state["blocked"] or event
        elif kind == DISPATCHED:
            assert step is not None
            if step["dispatch"] is not None or step["status"] == "completed":
                raise ValueError("analysis dispatch while another dispatch of the step is open")
            step.update(status="dispatched", dispatch=event, deferred=None)
            step["dispatches"].append(event)
            step["retries"] += event["attempt_kind"] == "retry"
            state["ever_dispatched"] = True
            state["notice"] = None
        elif kind == RELEASED:
            assert step is not None
            if step["dispatch"] is not None and step["dispatch"]["attempt_kind"] == "retry":
                step["retries"] -= 1  # a released dispatch started nothing: the explicit retry is not used up
            step.update(status="pending", dispatch=None)
            state["notice"] = {"code": event["reason_code"], "step_id": event["step_id"],
                               "message": MESSAGES.get(event["reason_code"])}
        elif kind == DEFERRED:
            assert step is not None
            step["deferred"] = event["reason_code"]
            state["notice"] = {"code": event["reason_code"], "step_id": event["step_id"],
                               "message": MESSAGES.get(event["reason_code"])}
        elif kind == STEP_DONE:
            assert step is not None
            step.update(status="completed", dispatch=None, result=event)
            state["notice"] = None
        elif kind == STEP_FAILED:
            assert step is not None
            step.update(status=event["status"], dispatch=None, failure=event, retryable=bool(event["retryable"]))
        elif kind == ATTEMPT:
            assert step is not None
            step["attempts"] += 1
            state["attempts"].append(event)
        elif kind == REFUSED:
            state["refusals"].append(event)
        elif kind == SCIENTIFIC:
            state["scientific"].append(event)
        elif kind == COMPLETE:
            state["complete"] = event
    return state


def _current(state: dict[str, Any]) -> str | None:
    return next((sid for sid in state["order"] if state["steps"][sid]["status"] != "completed"), None)


def _plan_step(plan: dict[str, Any], step_id: str) -> dict[str, Any]:
    return next(step for step in plan["steps"] if step["step_id"] == step_id)


def _expensive(events: list[dict[str, Any]]) -> tuple[bool, dict[str, Any] | None]:
    """(run approved expensive work, pending approval request) with Run._refresh semantics."""
    approved = False
    last = None
    for event in events:
        if event["type"] in {"approval_requested", "approval_resolved"} and event.get("gate") == "expensive_first_call":
            last = event
            if event["type"] == "approval_resolved":
                approved = bool(event["approved"])
    return approved, last if last is not None and last["type"] == "approval_requested" else None


def _job_binding(events: list[dict[str, Any]], execution_id: str, step_id: str) -> tuple[str | None, str | None]:
    for event in events:
        link = event.get("execution_link")
        if type(link) is not dict or link.get("execution_id") != execution_id or link.get("step_id") != step_id:
            continue
        if event["type"] == "job_submitted":
            return event["job"]["job_id"], "owned"
        if event["type"] == "job_observed":
            return event["job_id"], "observed_shared"
    return None, None


def _jobs(run: Any) -> dict[str, dict[str, Any]]:
    return {job["job_id"]: job for job in _job_queue(run).list()}


def _jobs_if_needed(run: Any, plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _jobs(run) if any(step["lane"] == "durable_job" for step in plan["steps"]) else {}


def _active_wall(events: list[dict[str, Any]], execution_id: str) -> float:
    refs = {event["attempt_ref"] for event in events if event.get("type") == ATTEMPT and
            event.get("execution_id") == execution_id}
    return float(sum(event["seconds"] for event in events if event["type"] == "wall_charged" and
                     event.get("call_id") in refs))


def _retry_allowed(state: dict[str, Any], plan: dict[str, Any], step: dict[str, Any]) -> bool:
    return (step["retryable"] and step["retries"] < plan["limits"]["max_retries_per_step"] and
            len(state["attempts"]) < plan["limits"]["max_physical_attempts"])


def _derive(state: dict[str, Any], plan: dict[str, Any], events: list[dict[str, Any]],
            jobs: dict[str, dict[str, Any]] | None, live: bool) -> tuple[str, str | None]:
    """Execution status and retryable step from recorded events plus derived owned-job state."""
    if state["complete"] is not None:
        return "complete", None
    if state["stop"] is not None:
        return "cancelled", None
    if state["blocked"] is not None:
        return "blocked", None
    if state["dry_run"]:
        return "plan_only", None
    if state["approval"] is None:
        return "awaiting_approval", None
    current = _current(state)
    if current is None:
        return "ready", None  # all steps recorded; the next Advance records the summary (recovery case 4)
    step = state["steps"][current]
    if step["status"] in {"failed", "interrupted"}:
        return "failed", current if _retry_allowed(state, plan, step) else None
    if step["status"] in {"blocked", "cancelled"}:
        return "blocked" if step["status"] == "blocked" else "cancelled", None
    if step["status"] != "dispatched":
        return "ready", None
    if _plan_step(plan, current)["lane"] != "durable_job":
        return "executing", None
    job_id, ownership = _job_binding(events, state["execution_id"], current)
    job = (jobs or {}).get(job_id) if job_id else None
    if job is None:
        return "executing", None
    if job["status"] == "running" or ownership == "observed_shared":
        return "waiting_job", None
    if job["status"] in {"queued", "claimed"}:
        if live:
            return "waiting_job", None
        approved, pending = _expensive(events)
        if not approved and (pending is not None or step["deferred"] == "scientific_approval_required"):
            return "awaiting_scientific_approval", None
        return "ready", None  # the next Advance starts the owned job
    return "waiting_job", None  # terminal job, recorded by the next Advance (reads never write)


# ---------------------------------------------------------------------------------------------- public record
def _plan_for(run: Any, events: list[dict[str, Any]], execution_id: Any) -> dict[str, Any]:
    if type(execution_id) is not str or not EXECUTION_ID_RE.fullmatch(execution_id):
        raise AnalysisError(404, "not_found", "unknown analysis execution")
    created = next((event for event in events if event["type"] == CREATED and
                    event.get("execution_id") == execution_id), None)
    if created is None:
        raise AnalysisError(404, "not_found", "unknown analysis execution")
    plan = plans.load_plan(run, created["plan_handle"])
    if plans.canonical_plan_hash(plan) != created["plan_sha256"]:
        raise ValueError("stored analysis plan differs from execution binding")
    return plan


def _child_call_ids(events: list[dict[str, Any]], execution_id: str, step_id: str) -> list[str]:
    ids: list[str] = []
    for event in events:
        link = event.get("execution_link")
        if type(link) is not dict or link.get("execution_id") != execution_id or link.get("step_id") != step_id:
            continue
        value = (event.get("call_id") if event["type"] == "tool_called" else
                 event.get("source_call_id") if event["type"] == "cache_hit" else None)
        if value and value not in ids:
            ids.append(value)
    return ids


def _step_record(state: dict[str, Any], plan: dict[str, Any], events: list[dict[str, Any]],
                 jobs: dict[str, dict[str, Any]] | None, step_id: str) -> dict[str, Any]:
    step, spec = state["steps"][step_id], _plan_step(plan, step_id)
    result = step["result"] or {}
    job_id, ownership = (_job_binding(events, state["execution_id"], step_id) if spec["lane"] == "durable_job"
                         else (None, None))
    job = (jobs or {}).get(job_id) if job_id else None
    status = step["status"]
    if status == "dispatched" and job is not None and job["status"] in {"queued", "claimed", "running"}:
        status = "waiting_job"
    failure = step["failure"]
    last = step["dispatches"][-1] if step["dispatches"] else None
    return {
        "step_id": step_id, "operation": spec["operation"], "lane": spec["lane"], "status": status,
        "null_result": result.get("null_result") if status == "completed" else None,
        "operation_id": last["operation_id"] if last else None,
        "dispatch_seqs": [item["seq"] for item in step["dispatches"]],
        "completed_seq": result.get("seq"), "attempts": step["attempts"], "retries_used": step["retries"],
        "outputs": result.get("outputs", {}), "report_handle": (result.get("outputs") or {}).get("report"),
        "child_call_ids": _child_call_ids(events, state["execution_id"], step_id),
        "job_id": job_id, "job_ownership": ownership,
        "job_status": job["status"] if job else None, "job_cleanup_status": job.get("cleanup_status") if job else None,
        "job_blocked_reason": job.get("blocked_reason") if job else None,
        "job_cancel_requested": job.get("cancel_requested") if job else None,
        "shared_job_notice": (MESSAGES["shared_job_detached"] if ownership == "observed_shared" and state["stop"]
                              else MESSAGES["shared_job_waiting"] if ownership == "observed_shared" and job and
                              job["status"] not in {"done", "failed", "cancelled", "interrupted"} else None),
        "deferred_reason": step["deferred"],
        "failure": None if failure is None else {key: failure.get(key) for key in
                                                 ("status", "error", "reason_code", "message", "retryable")},
    }


def _record(run: Any, execution_id: str, events: list[dict[str, Any]] | None = None,
            plan: dict[str, Any] | None = None) -> dict[str, Any]:
    events = list(run.events.read()) if events is None else events
    plan = _plan_for(run, events, execution_id) if plan is None else plan
    state = _fold(events, execution_id, plan)
    pending_driver = [rid for rid, item in state["requests"].items()
                      if item["state"] == "pending" and item["action"] in {"advance", "retry"}]
    live = _driver_live(run, execution_id) if pending_driver else False
    try:
        jobs = _jobs(run) if any(step["lane"] == "durable_job" for step in plan["steps"]) else {}
    except (KeyError, ValueError, TypeError):
        jobs = None
    status, retryable = _derive(state, plan, events, jobs, live)
    approved, pending_gate = _expensive(events)
    has_jobs = any(step["lane"] == "durable_job" for step in plan["steps"])
    current = _current(state)
    open_dispatch = current is not None and state["steps"][current]["dispatch"] is not None
    stale_child = open_dispatch and (
        _plan_step(plan, current)["lane"] != "durable_job" or
        (jobs or {}).get(_job_binding(events, execution_id, current)[0] or "", {}).get("status") in
        {"done", "failed", "cancelled", "interrupted"})
    finishing = (current is None and state["complete"] is None and state["stop"] is None and
                 state["approval"] is not None and state["blocked"] is None)
    recovery_pending = not live and (bool(pending_driver) or finishing or (
        stale_child and state["blocked"] is None and state["complete"] is None))
    approval = state["approval"]
    return {
        "schema": EXECUTION_SCHEMA, "execution_id": execution_id, "run_id": run.run_id,
        "plan_handle": state["plan_handle"], "plan_sha256": state["plan_sha256"], "goal": plan["goal"],
        "template_version": plan["template_version"], "source": plans.SOURCE, "planner": plans.PLANNER,
        "dry_run": state["dry_run"], "status": status, "retryable_step": retryable, "revision": state["revision"],
        "created_seq": state["created_seq"], "current_step": current,
        "plan_approval": {"approved": approval is not None, "event_seq": approval["seq"] if approval else None,
                          "plan_sha256": approval["plan_sha256"] if approval else None,
                          "revocations": [{"seq": item["seq"], "outcome": item["outcome"]}
                                          for item in state["revoked"]]},
        "scientific_approval": {
            "required": has_jobs, "run_approved": approved,
            "state": ("not_required" if not has_jobs else "already_approved_in_run" if approved else
                      "pending" if status == "awaiting_scientific_approval" else "not_yet_requested"),
            "pending_tool": pending_gate.get("tool") if pending_gate and not approved else None,
            "recorded_seqs": [item["seq"] for item in state["scientific"]]},
        "blocked_reason": (None if state["blocked"] is None else
                           {key: state["blocked"].get(key) for key in ("reason_code", "message", "step_id", "detail")}),
        "stop": (None if state["stop"] is None else {"seq": state["stop"]["seq"], "reason": state["stop"]["reason"]}),
        "notice": state["notice"],
        "driver": {"in_progress": bool(pending_driver) and live, "request_ids": pending_driver},
        "recovery_pending": bool(recovery_pending),
        "steps": [_step_record(state, plan, events, jobs, sid) for sid in state["order"]],
        "physical_attempts": len(state["attempts"]),
        "active_wall_s": _active_wall(events, execution_id),
        "limits": dict(plan["limits"]),
        "summary_handle": state["complete"]["summary_handle"] if state["complete"] else None,
        "event_seqs": state["seqs"], "jobs_readable": jobs is not None,
    }


def execution_detail(run: Any, execution_id: Any) -> dict[str, Any]:
    """Read-only: derives state from events and job reads; never appends an event."""
    return _record(run, execution_id)


def list_executions(run: Any) -> dict[str, Any]:
    """One event read and one fold per execution; a corrupt execution becomes an error row.

    The detail GET for that execution still fails closed (409 run_corrupt).
    """
    events = list(run.events.read())
    created: list[dict[str, Any]] = []
    own: dict[str, list[dict[str, Any]]] = {}
    linked: dict[str, list[dict[str, Any]]] = {}
    approvals: list[dict[str, Any]] = []
    for event in events:
        kind = event["type"]
        if kind in EVENT_TYPES and isinstance(event.get("execution_id"), str):
            own.setdefault(event["execution_id"], []).append(event)
            if kind == CREATED:
                created.append(event)
        link = event.get("execution_link")
        if type(link) is dict and isinstance(link.get("execution_id"), str):
            linked.setdefault(link["execution_id"], []).append(event)
        if kind in {"approval_requested", "approval_resolved"}:
            approvals.append(event)
    plans_by_handle: dict[str, dict[str, Any]] = {}
    jobs: list[dict[str, dict[str, Any]] | None] = []
    rows = []
    for event in created[:MAX_EXECUTIONS_PER_RUN]:
        execution_id = event["execution_id"]
        try:
            handle = event["plan_handle"]
            if handle not in plans_by_handle:
                plans_by_handle[handle] = plans.load_plan(run, handle, events)
            plan = plans_by_handle[handle]
            if plans.canonical_plan_hash(plan) != event["plan_sha256"]:
                raise ValueError("stored analysis plan differs from execution binding")
            state = _fold(own[execution_id], execution_id, plan)
            job_view = None
            if any(step["lane"] == "durable_job" for step in plan["steps"]):
                if not jobs:
                    try:
                        jobs.append(_jobs(run))
                    except (KeyError, ValueError, TypeError):
                        jobs.append(None)
                job_view = jobs[0]
            pending_driver = any(item["state"] == "pending" and item["action"] in {"advance", "retry"}
                                 for item in state["requests"].values())
            live = _driver_live(run, execution_id) if pending_driver else False
            # _derive reads events only for this execution's linked job binding and run approval gates.
            relevant = sorted(linked.get(execution_id, []) + approvals, key=lambda item: item["seq"])
            status, _retryable = _derive(state, plan, relevant, job_view, live)
            rows.append({"execution_id": execution_id, "plan_handle": state["plan_handle"], "goal": plan["goal"],
                         "status": status, "revision": state["revision"], "created_seq": state["created_seq"],
                         "dry_run": state["dry_run"], "current_step": _current(state),
                         "summary_handle": state["complete"]["summary_handle"] if state["complete"] else None,
                         "error": None})
        except (KeyError, ValueError, TypeError, ToolFailure, AssertionError):
            rows.append({"execution_id": execution_id, "plan_handle": event.get("plan_handle"), "goal": None,
                         "status": None, "revision": None, "created_seq": event.get("seq"), "dry_run": None,
                         "current_step": None, "summary_handle": None,
                         "error": {"code": "execution_record_invalid", "message": MESSAGES["recovery_error"]}})
    return {"schema": "analysis_execution_list@1", "total": len(created), "rows": rows}


def _response(run: Any, execution_id: str, request_id: str, *, replayed: bool) -> dict[str, Any]:
    events = list(run.events.read())
    record = _record(run, execution_id, events)
    plan = _plan_for(run, events, execution_id)
    request = _fold(events, execution_id, plan)["requests"].get(request_id)
    return {"execution": record, "replayed": replayed,
            "request": {"request_id": request_id, "action": request["action"] if request else "create",
                        "state": request["state"] if request else "completed",
                        "outcome": request["outcome"] if request else "created"}}


# ---------------------------------------------------------------------------------------------- admission helpers
def _request_sha(action: str, execution_id: str, body: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json({"action": action, "execution_id": execution_id, **body})).hexdigest()


def _replay(run: Any, events: list[dict[str, Any]], request_id: str, sha: str,
            execution_id: str) -> dict[str, Any] | None:
    binding = plans.request_binding(events, request_id)
    if binding is None:
        return None
    if binding["type"] != ADMITTED or binding.get("request_sha256") != sha or \
            binding.get("execution_id") != execution_id:
        raise plans.AnalysisConflict("request_id_conflict", "request_id was already used with a different body")
    return _response(run, execution_id, request_id, replayed=True)


def _check_revision(state: dict[str, Any], expected: Any) -> None:
    if type(expected) is not int or expected != state["revision"]:
        raise AnalysisError(409, "stale_revision", "execution revision changed; reload and retry",
                            {"revision": state["revision"]})


def _admit(run: Any, execution_id: str, request_id: str, sha: str, action: str, expected: int,
           **extra: Any) -> None:
    _append(run, ADMITTED, execution_id=execution_id, request_id=request_id, request_sha256=sha, action=action,
            expected_revision=expected, **extra)


def _finish(run: Any, execution_id: str, request_id: str, action: str, outcome: str) -> None:
    _append(run, FINISHED, execution_id=execution_id, request_id=request_id, action=action, outcome=outcome)


def _close_stale(run: Any, execution_id: str, state: dict[str, Any], current: str | None, driver_live: bool) -> None:
    """Requests admitted by a request that died before completing (crash). Caller holds the workflow lock."""
    for request_id, item in state["requests"].items():
        if item["state"] != "pending" or request_id == current:
            continue
        if item["action"] in {"advance", "retry"} and driver_live:
            continue
        _finish(run, execution_id, request_id, item["action"], "interrupted")


def _refuse_plan_only(state: dict[str, Any]) -> None:
    if state["dry_run"]:
        raise AnalysisError(412, "dry_run_plan_only",
                            "연습용 run의 계획은 미리보기 전용입니다. 실행하려면 일반 run에서 같은 입력으로 계획을 다시 만드세요.")


# ---------------------------------------------------------------------------------------------- create
def create_execution(run: Any, request_id: Any, plan_handle: Any) -> dict[str, Any]:
    request_id = plans._request_uuid(request_id)
    if type(plan_handle) is not str:
        raise ToolFailure(FailureClass.input_invalid, "plan_handle must be a string")
    sha = hashlib.sha256(canonical_json({"action": "create", "plan_handle": plan_handle})).hexdigest()
    with _workflow_lock(run):
        events = list(run.events.read())
        binding = plans.request_binding(events, request_id)
        if binding is not None:
            if binding["type"] != CREATED or binding.get("request_sha256") != sha:
                raise plans.AnalysisConflict("request_id_conflict", "request_id was already used with a different body")
            return _response(run, binding["execution_id"], request_id, replayed=True)
        plan = plans.load_plan(run, plan_handle)
        if plan["unmet_prerequisites"]:
            raise AnalysisError(412, "plan_blocked", "this plan has unmet prerequisites and cannot be executed",
                                {"codes": [item["code"] for item in plan["unmet_prerequisites"]]})
        if sum(event["type"] == CREATED for event in events) >= MAX_EXECUTIONS_PER_RUN:
            raise ToolFailure(FailureClass.resource_exceeded, "analysis execution limit per run reached",
                              detail={"reason_code": "execution_limit"})
        execution_id = f"exec_{uuid.uuid4().hex}"
        _append(run, CREATED, execution_id=execution_id, request_id=request_id, request_sha256=sha,
                plan_handle=plan_handle, plan_sha256=plans.canonical_plan_hash(plan),
                initial_status="plan_only" if run.dry_run else "awaiting_approval")
    return _response(run, execution_id, request_id, replayed=False)


# ---------------------------------------------------------------------------------------------- short requests
def _short(run: Any, execution_id: Any, action: str, request_id: Any, expected: Any, body: dict[str, Any],
           handler: Callable[[dict[str, Any], dict[str, Any], list[dict[str, Any]], bool], str]) -> dict[str, Any]:
    request_id = plans._request_uuid(request_id)
    with _workflow_lock(run):
        events = list(run.events.read())
        plan = _plan_for(run, events, execution_id)
        sha = _request_sha(action, execution_id, {"expected_revision": expected, **body})
        replay = _replay(run, events, request_id, sha, execution_id)
        if replay is not None:
            return replay
        state = _fold(events, execution_id, plan)
        _check_revision(state, expected)
        live = _driver_live(run, execution_id)
        # Recovery first (request-independent, no physical work), then judge the request on reconciled state.
        _close_stale(run, execution_id, state, None, live)
        _reconcile(run, execution_id, plan, driver_live=live)
        events = list(run.events.read())
        state = _fold(events, execution_id, plan)
        outcome = handler(state, plan, events, live)  # raises AnalysisError before admission when refused
        _admit(run, execution_id, request_id, sha, action, expected)
        outcome = _perform(run, execution_id, plan, action, outcome, request_id, live)
        _finish(run, execution_id, request_id, action, outcome)
    return _response(run, execution_id, request_id, replayed=False)


def _perform(run: Any, execution_id: str, plan: dict[str, Any], action: str, decision: str, request_id: str,
             live: bool) -> str:
    """Side effects of an admitted short request (workflow lock held, admission recorded)."""
    if action == "approve":
        compatibility = plans.check_compatibility(run, plan)
        if not compatibility["compatible"]:
            _append(run, BLOCKED, execution_id=execution_id, request_id=request_id, reason_code="compatibility_changed",
                    message=MESSAGES["compatibility_changed"], step_id=None,
                    detail={"mismatched_steps": compatibility["mismatched_steps"]})
            return "blocked"
        _append(run, APPROVED, execution_id=execution_id, request_id=request_id,
                plan_handle=plan_handle_of(run, execution_id),
                plan_sha256=plans.canonical_plan_hash(plan), step_ids=[step["step_id"] for step in plan["steps"]],
                compatibility_sha256=hashlib.sha256(canonical_json(plan["compatibility"])).hexdigest())
        return "approved"
    if action == "revoke":
        if decision == "awaiting_approval":
            _append(run, REVOKED, execution_id=execution_id, request_id=request_id, outcome="awaiting_approval")
            return "revoked"
        _append(run, REVOKED, execution_id=execution_id, request_id=request_id, outcome="cancelled")
        _append(run, STOP, execution_id=execution_id, request_id=request_id, reason="revoke")
        _reconcile(run, execution_id, plan, driver_live=live)
        return "cancelled"
    if action == "cancel":
        if decision == "already_terminal":
            return "already_terminal"
        _append(run, STOP, execution_id=execution_id, request_id=request_id, reason="stop")
        _reconcile(run, execution_id, plan, driver_live=live)
        return "cancelled"
    if action == "scientific_approval":
        try:
            run.approve("expensive_first_call", by="human_api")
        except ToolFailure as exc:
            if exc.detail.get("busy") is not True:
                raise
            return "run_busy"
        _append(run, SCIENTIFIC, execution_id=execution_id, request_id=request_id, job_id=decision,
                gate="expensive_first_call")
        return "approved"
    raise ValueError("unknown analysis action")


def plan_handle_of(run: Any, execution_id: str) -> str:
    return next(event["plan_handle"] for event in run.events.read()
                if event["type"] == CREATED and event.get("execution_id") == execution_id)


def approve(run: Any, execution_id: Any, request_id: Any, expected_revision: Any, plan_hash: Any) -> dict[str, Any]:
    def check(state: dict[str, Any], plan: dict[str, Any], events: list[dict[str, Any]], live: bool) -> str:
        _refuse_plan_only(state)
        status, _ = _derive(state, plan, events, None, live)
        if status != "awaiting_approval":
            raise AnalysisError(412, "not_awaiting_approval", "execution is not awaiting plan approval",
                                {"status": status})
        if plan_hash != plans.canonical_plan_hash(plan) or plan_hash != state["plan_sha256"]:
            raise AnalysisError(412, "plan_hash_mismatch", "plan hash differs from the current immutable plan")
        return "approve"
    return _short(run, execution_id, "approve", request_id, expected_revision, {"plan_hash": plan_hash}, check)


_CHILD_STARTS = {"tool_called", "cache_hit", "job_submitted", "job_observed", "report_created",
                 "method_report_created"}


def _child_admitted(state: dict[str, Any], events: list[dict[str, Any]]) -> bool:
    """A released dispatch whose child never started does not count; an open dispatch may be in flight.

    Only real child starts count (a call, cache hit, job submission/observation or linked report), not an
    ``execution_call_admitted`` whose call was then released by the run budget, a busy run or an unclosed job.
    """
    if any(state["steps"][sid]["dispatch"] is not None for sid in state["order"]):
        return True
    return any(event["type"] in _CHILD_STARTS and type(event.get("execution_link")) is dict and
               event["execution_link"].get("execution_id") == state["execution_id"] for event in events)


def _terminal(status: str, retryable: str | None) -> bool:
    return status in {"complete", "cancelled", "blocked"} or (status == "failed" and retryable is None)


def execution_active(run: Any, execution_id: str) -> bool:
    """Read-only: False once the execution ended (it never drives its owned jobs again). Fails closed."""
    try:
        events = list(run.events.read())
        plan = _plan_for(run, events, execution_id)
        return not _terminal(*_derive(_fold(events, execution_id, plan), plan, events, None, False))
    except (AnalysisError, KeyError, ValueError, TypeError):
        return True


def revoke(run: Any, execution_id: Any, request_id: Any, expected_revision: Any) -> dict[str, Any]:
    def check(state: dict[str, Any], plan: dict[str, Any], events: list[dict[str, Any]], live: bool) -> str:
        _refuse_plan_only(state)
        if state["complete"] or state["stop"] or state["blocked"]:
            raise AnalysisError(412, "execution_terminal", "execution already ended")
        status, retryable = _derive(state, plan, events, None, live)
        if status == "failed" and retryable is None:
            raise AnalysisError(412, "execution_terminal", "execution already ended")
        if state["approval"] is None:
            raise AnalysisError(412, "not_approved", "execution has no plan approval to revoke")
        return "cancelled" if _child_admitted(state, events) else "awaiting_approval"
    return _short(run, execution_id, "revoke", request_id, expected_revision, {}, check)


def cancel(run: Any, execution_id: Any, request_id: Any, expected_revision: Any) -> dict[str, Any]:
    """Scoped Stop: this execution only; never ``Run.cancel``; never waits for a running driver."""
    def check(state: dict[str, Any], plan: dict[str, Any], events: list[dict[str, Any]], live: bool) -> str:
        return "already_terminal" if _terminal(*_derive(state, plan, events, None, live)) else "stop"
    return _short(run, execution_id, "cancel", request_id, expected_revision, {}, check)


def scientific_approval(run: Any, execution_id: Any, request_id: Any, expected_revision: Any) -> dict[str, Any]:
    """Existing /jobs/approve rule, scoped to a pending gate of this execution's own job."""
    def check(state: dict[str, Any], plan: dict[str, Any], events: list[dict[str, Any]], live: bool) -> str:
        _refuse_plan_only(state)
        jobs = _jobs(run)
        status, _ = _derive(state, plan, events, jobs, live)
        current = _current(state)
        job_id, ownership = _job_binding(events, execution_id, current) if current else (None, None)
        approved, pending = _expensive(events)
        job = jobs.get(job_id) if job_id else None
        if (status != "awaiting_scientific_approval" or job is None or ownership != "owned" or
                job["status"] not in {"queued", "claimed"} or approved or pending is None or
                pending.get("tool") not in JOB_TOOLS or pending.get("tool") != job["tool_id"]):
            raise AnalysisError(412, "no_pending_scientific_approval",
                                "no pending scientific approval request for this execution's job")
        return job_id
    return _short(run, execution_id, "scientific_approval", request_id, expected_revision, {}, check)


# ---------------------------------------------------------------------------------------------- dispatch
def _blocked(run: Any, execution_id: str, request_id: str | None, code: str, step_id: str | None,
             detail: dict[str, Any] | None = None, message: str | None = None) -> None:
    _append(run, BLOCKED, execution_id=execution_id, request_id=request_id, reason_code=code,
            message=message or MESSAGES.get(code, code), step_id=step_id, detail=detail or {})


def _resolve_bindings(run: Any, state: dict[str, Any], step: dict[str, Any]) -> dict[str, str]:
    resolved = {}
    for name, binding in step["bindings"].items():
        if binding["kind"] == "existing":
            handle = binding["handle"]
        else:
            produced = state["steps"][binding["step_id"]]
            if produced["status"] != "completed":
                raise ToolFailure(FailureClass.precondition, "step input is not available",
                                  detail={"reason_code": "binding_unavailable"})
            handle = produced["result"]["outputs"].get(binding["output_name"])
        try:
            meta = run.store.meta(handle)
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolFailure(FailureClass.input_invalid, "bound handle is unavailable",
                              detail={"reason_code": "binding_unavailable", "binding": name}) from exc
        if (meta["kind"], meta["schema"]) != (binding["expected_kind"], binding["expected_schema"]):
            raise ToolFailure(FailureClass.input_invalid, "bound handle kind/schema differs",
                              detail={"reason_code": "binding_type_mismatch", "binding": name})
        resolved[name] = handle
    return resolved


def _identity_check(run: Any, plan: dict[str, Any], state: dict[str, Any], step: dict[str, Any],
                    resolved: dict[str, str], params: dict[str, Any]) -> None:
    """After preparation, the exact selected identities must exist unchanged; never remap."""
    derived = {name for name, binding in step["bindings"].items() if binding["kind"] == "step_output"}
    if "structure" in derived and params.get("ligand") is not None:
        ligands = structure_residues(run.store, resolved["structure"])["ligands"]
        if sum(item == params["ligand"] for item in ligands) != 1:
            raise _IdentityChanged("selected ligand is absent or ambiguous after preparation")
    if step["operation"] == "prolif_detect_v1":
        manifest_handle = state["steps"]["s01"]["result"]["outputs"]["preparation_manifest"]
        manifest = run.store.load_bounded_json(manifest_handle, 8 * 1024 * 1024)
        request = plan["inputs"]["request"]
        if manifest.get("request") != request or manifest.get("mode") != request.get("mode"):
            raise _IdentityChanged("prepared chemistry differs from the approved request")
        graph = run.store.load_bounded_json(resolved["graph_handle"], 32 * 1024 * 1024)
        if graph.get("manifest_handle") != manifest_handle:
            raise _IdentityChanged("prepared chemical graph is not bound to the recorded manifest")
        if request["mode"] == "attach_existing":
            expected = {item["sdf_atom_index"]: item["source_atom"] for item in request["mapping"]}
            actual = {item["sdf_atom_index"]: item["source_atom"] for item in manifest["attached_source_sites"]}
            if actual != expected or any(item["residue"] != request["selected_ligand"] for item in expected.values()):
                raise _IdentityChanged("attached ligand atom identities differ from the request mapping")


class _IdentityChanged(Exception):
    pass


def _dispatch_record(run: Any, plan: dict[str, Any], state: dict[str, Any], step_id: str) -> dict[str, Any]:
    """Concrete normalized child arguments for one step (no side effect)."""
    step = _plan_step(plan, step_id)
    params = plans.resolved_params(plan, step)
    resolved = _resolve_bindings(run, state, step)
    _identity_check(run, plan, state, step, resolved, params)
    record: dict[str, Any] = {"lane": step["lane"], "operation": step["operation"],
                              "operation_version": step["operation_version"],
                              "expected_outputs": step["outputs"]}
    table = plans.OPERATIONS[step["operation"]]
    if step["lane"] == "run_call":
        spec = run.registry.specs[table["tool"]]
        if spec.version != step["operation_version"]:
            raise _Incompatible()
        record.update(tool=table["tool"], tool_version=spec.version, branch_id=f"analysis_{state['execution_id']}",
                      args=check_args(spec, {**resolved, **params}, run.store.kind_of))
    elif step["lane"] == "durable_job":
        timeout = params.pop("timeout_s")
        args = params["request"] if step["operation"] == "prolif_prepare_v1" else {**resolved, **params}
        spec = run.registry.specs[table["tool"]]
        if spec.version != step["operation_version"]:
            raise _Incompatible()
        expected = (check_args(spec, args, run.store.kind_of) if step["operation"] == "openmm_protein_minimize"
                    else {"structure": args["structure"], "chains": args["chains"]}
                    if step["operation"] == "fpocket_detect_v1" else args)
        record.update(protocol=table["protocol_id"], tool=table["tool"], args=args, timeout_s=timeout,
                      expected_parameters=expected)
    else:
        analysis_type = params["analysis_type"]
        _module, builder, label, _saved = REPORTS[analysis_type]
        source = resolved.get("interaction_handle", resolved.get("result_handle"))
        record.update(analysis_type=analysis_type, builder=builder, builder_label=label, args=resolved,
                      source_handle=source)
    return record


class _Incompatible(Exception):
    pass


def _limits_exhausted(state: dict[str, Any], plan: dict[str, Any], events: list[dict[str, Any]],
                      lane: str) -> str | None:
    # Report steps make no physical start, so neither the attempt nor the active-wall limit refuses them.
    if lane == "report":
        return None
    if len(state["attempts"]) >= plan["limits"]["max_physical_attempts"]:
        return "max_physical_attempts"
    if _active_wall(events, state["execution_id"]) >= plan["limits"]["max_active_wall_s"]:
        return "max_active_wall"
    return None


def _link(run: Any, plan: dict[str, Any], execution_id: str, step_id: str, operation_id: str) -> ExecutionLink:
    def admit(info: dict[str, Any]) -> None:
        # Held under Run._transition(): read-only validation of the durable dispatch record.
        events = list(run.events.read())
        state = _fold(events, execution_id, plan)
        dispatch = state["steps"][step_id]["dispatch"]
        if (state["stop"] is not None or state["blocked"] is not None or state["complete"] is not None or
                state["approval"] is None or dispatch is None or dispatch["operation_id"] != operation_id or
                _current(state) != step_id):
            raise ToolFailure(FailureClass.precondition, "analysis step is not admissible",
                              detail={"reason_code": "analysis_admission_refused"})
        lane = info.get("lane")
        if lane == "run_call":
            same = (info["tool"] == dispatch["tool"] and info["version"] == dispatch["tool_version"] and
                    info["args"] == dispatch["args"] and info["branch_id"] == dispatch["branch_id"] and
                    info["execution_mode"] == "autonomous" and info["decided_by"] == "rule")
        elif lane == "job":
            same = (info["protocol"] == dispatch["protocol"] and info["timeout_s"] == dispatch["timeout_s"] and
                    info["parameters"] == dispatch["expected_parameters"])
        elif lane == "report":
            same = info["builder"] == dispatch["builder_label"] and info["source_handle"] == dispatch["source_handle"]
        else:
            same = False
        if not same or lane != {"run_call": "run_call", "durable_job": "job", "report": "report"}[dispatch["lane"]]:
            raise ToolFailure(FailureClass.precondition, "analysis child differs from its dispatch record",
                              detail={"reason_code": "analysis_dispatch_mismatch"})

    def stopped() -> bool:
        return any(event["type"] == STOP and event.get("execution_id") == execution_id
                   for event in run.events.read())

    def before_attempt(info: dict[str, Any]) -> None:
        # Held under Run._transition(): durable per-execution physical attempt count before the start.
        events = list(run.events.read())
        count = sum(event["type"] == ATTEMPT and event.get("execution_id") == execution_id for event in events)
        reason = ("max_physical_attempts" if count >= plan["limits"]["max_physical_attempts"] else
                  "max_active_wall" if _active_wall(events, execution_id) >= plan["limits"]["max_active_wall_s"]
                  else None)
        if reason is not None:
            run.events.append(REFUSED, execution_id=execution_id, step_id=step_id, operation_id=operation_id,
                              reason_code=reason)
            raise ToolFailure(FailureClass.resource_exceeded, MESSAGES[reason], detail={"reason_code": reason})
        run.events.append(ATTEMPT, execution_id=execution_id, step_id=step_id, operation_id=operation_id,
                          lane=info["lane"], attempt_ref=info.get("call_id") or info.get("attempt_id"),
                          ordinal=count + 1)

    return ExecutionLink(execution_id=execution_id, step_id=step_id, operation_id=operation_id, admit=admit,
                         stopped=stopped, before_attempt=before_attempt)


def _child(run: Any, plan: dict[str, Any], execution_id: str, step_id: str, dispatch: dict[str, Any],
           mode: str) -> None:
    """Run exactly one child operation (no workflow lock held). mode: new | retry | start."""
    link = _link(run, plan, execution_id, step_id, dispatch["operation_id"])
    if dispatch["lane"] == "run_call":
        run.call(dispatch["tool"], dispatch["args"], decided_by="rule", execution_mode="autonomous",
                 branch_id=dispatch["branch_id"], execution_link=link)
    elif dispatch["lane"] == "durable_job":
        queue = _job_queue(run)
        if mode == "new":
            job = queue.submit(dispatch["protocol"], dispatch["args"], timeout_s=dispatch["timeout_s"],
                               execution_link=link)
            if job.get("execution_ownership") != "owned":
                return  # observed_shared: never start, retry or cancel someone else's job
            job_id = job["job_id"]
        else:
            job_id = dispatch["job_id"]
            if mode == "retry":
                queue.retry(job_id, execution_link=link)
        _fault("after_job_submit")
        queue.start(job_id, execution_link=link)
    else:
        module, builder, _, _ = REPORTS[dispatch["analysis_type"]]
        build = getattr(module, builder)
        if dispatch["analysis_type"] == "interaction_contacts":
            build(run, dispatch["args"]["interaction_handle"], prepared_handle=dispatch["args"]["prepared_handle"],
                  execution_link=link)
        else:
            if dispatch["analysis_type"] == "chemical_interactions":
                require_completed_chemical_handle(run, dispatch["args"]["result_handle"])
            build(run, dispatch["args"]["result_handle"], execution_link=link)


# ---------------------------------------------------------------------------------------------- reconciliation
def _outcome_from_class(error: str | None, *, interrupted: bool = False) -> dict[str, Any]:
    if error in {FailureClass.input_invalid.value, FailureClass.precondition.value}:
        return {"kind": "blocked", "error": error, "reason_code": "step_" + error}
    if error == FailureClass.transient.value:
        return {"kind": "failed", "status": "failed", "error": error, "reason_code": "transient_exhausted",
                "retryable": True}
    if interrupted:
        return {"kind": "failed", "status": "interrupted", "error": "interrupted", "reason_code": "interrupted",
                "retryable": True}
    return {"kind": "failed", "status": "failed", "error": error or "fatal", "reason_code": error or "fatal",
            "retryable": False}


def _hint_outcome(hint: BaseException | None, *, started: bool) -> dict[str, Any] | None:
    if hint is None:
        return None
    if isinstance(hint, ApprovalRequired):
        if hint.gate == "budget":
            return {"kind": "released" if not started else "deferred", "reason_code": "run_budget_exhausted"}
        return {"kind": "deferred", "reason_code": "scientific_approval_required"}
    if isinstance(hint, ExecutionStopped):
        return {"kind": "cancelled"}
    if isinstance(hint, RunCancelled):
        return {"kind": "failed", "status": "failed", "error": "cancelled", "reason_code": "run_cancelled",
                "retryable": False}
    if isinstance(hint, LoopStop):
        return {"kind": "failed", "status": "failed", "error": "fatal", "reason_code": f"loop_guard_{hint.reason}",
                "retryable": False}
    if isinstance(hint, ToolFailure):
        code = hint.detail.get("reason_code")
        if hint.detail.get("busy") is True or code in BUSY_CODES:
            return {"kind": "released" if not started else "deferred", "reason_code": code or "run_busy"}
        if code == "analysis_admission_refused":
            return {"kind": "released", "reason_code": "not_started"}
        return _outcome_from_class(hint.cls.value) | ({"reason_code": code} if code else {})
    if isinstance(hint, inspection_reports.EvidenceError):
        return {"kind": "blocked", "error": "input_invalid", "reason_code": "report_evidence_invalid"}
    return {"kind": "failed", "status": "failed", "error": "fatal", "reason_code": "unexpected_error",
            "retryable": False}


def _verified_output(run: Any, handle: Any, kind: str, schema: str) -> dict[str, Any]:
    meta = run.store.meta(handle)
    if (meta["kind"], meta["schema"]) != (kind, schema):
        raise _RecoveryError("child output kind/schema differs")
    if meta["fmt"] == "json":
        run.store.load_bounded_json(handle, 64 * 1024 * 1024)
    else:
        run.store.load(handle)
    return meta


def _run_call_outcome(run: Any, events: list[dict[str, Any]], state: dict[str, Any], dispatch: dict[str, Any],
                      hint: BaseException | None) -> dict[str, Any]:
    link = _link_record(state["execution_id"], dispatch["step_id"], dispatch["operation_id"])
    linked = [event for event in events if event.get("execution_link") == link]
    admitted = [event for event in linked if event["type"] == "execution_call_admitted"]
    success = [event for event in linked if event["type"] in {"tool_succeeded", "cache_hit"}]
    if success:
        event = success[-1]
        if len(admitted) != 1 or admitted[0]["seq"] > event["seq"] or event.get("key") != admitted[0]["key"]:
            raise _RecoveryError("linked success lacks one matching admission")
        if event["type"] == "tool_succeeded":
            call = [item for item in linked if item["type"] == "tool_called" and item["call_id"] == event["call_id"]]
            if (len(call) != 1 or call[0]["tool"] != dispatch["tool"] or call[0]["version"] != dispatch["tool_version"]
                    or call[0]["args"] != dispatch["args"] or call[0]["key"] != event["key"]):
                raise _RecoveryError("linked call identity differs from dispatch")
            child = {"kind": "tool_succeeded", "call_id": event["call_id"]}
        else:
            source = [item for item in events if item["type"] == "tool_succeeded" and
                      item["call_id"] == event.get("source_call_id") and item.get("key") == event["key"]]
            if (len(source) != 1 or event["tool"] != dispatch["tool"] or event["args"] != dispatch["args"] or
                    source[0]["output"] != event["output"]):
                raise _RecoveryError("linked cache hit differs from its source call")
            child = {"kind": "cache_hit", "source_call_id": event["source_call_id"]}
        (name, kind, schema) = (dispatch["expected_outputs"][0][key] for key in ("name", "kind", "schema"))
        meta = _verified_output(run, event["output"]["handle"], kind, schema)
        if meta["null_result"] != bool(event["output"].get("null_result")):
            raise _RecoveryError("child output null_result differs")
        return {"kind": "completed", "seq": event["seq"], "outputs": {name: event["output"]["handle"]},
                "null_result": meta["null_result"], "child": {**child, "event_seq": event["seq"]}}
    if any(event["type"] == "execution_call_stopped" for event in linked):
        return {"kind": "cancelled"}
    if any(event["type"] == REFUSED and event.get("operation_id") == dispatch["operation_id"] and
           event.get("execution_id") == state["execution_id"] for event in events):
        return {"kind": "failed", "status": "failed", "error": "resource_exceeded",
                "reason_code": _refusal_code(events, state, dispatch), "retryable": False}
    called = [event for event in linked if event["type"] == "tool_called"]
    ended = {event["call_id"] for event in linked if event["type"] in {"tool_succeeded", "tool_failed",
                                                                        "tool_interrupted"}}
    if any(event["call_id"] not in ended for event in called):
        return {"kind": "orphan"}
    terminals = [event for event in linked if event["type"] in {"tool_failed", "tool_interrupted", "proposal_rejected"}]
    if terminals:
        last = terminals[-1]
        if last["type"] == "tool_interrupted":
            if last.get("reason") == "cancelled":
                return {"kind": "failed", "status": "interrupted", "error": "cancelled", "reason_code": "run_cancelled",
                        "retryable": False}
            return _outcome_from_class(None, interrupted=True)
        return _outcome_from_class(last.get("error"))
    guard = next((event for event in events if event["type"] == "checkpoint" and
                  event.get("branch_id") == dispatch["branch_id"] and event["seq"] > dispatch["seq"] and
                  event.get("reason") in {"repeated_call_hash", "oscillation", "no_progress"}), None)
    if guard is not None or (hint is None and any(event["type"] == "checkpoint" and
                                                  event.get("branch_id") == dispatch["branch_id"]
                                                  for event in events)):
        reason = guard["reason"] if guard else "stopped_branch"
        return {"kind": "failed", "status": "failed", "error": "fatal", "reason_code": f"loop_guard_{reason}",
                "retryable": False}
    return _hint_outcome(hint, started=False) or {"kind": "released", "reason_code": "not_started"}


def _refusal_code(events: list[dict[str, Any]], state: dict[str, Any], dispatch: dict[str, Any]) -> str:
    return next(event["reason_code"] for event in events if event["type"] == REFUSED and
                event.get("execution_id") == state["execution_id"] and
                event.get("operation_id") == dispatch["operation_id"])


def _job_outcome(run: Any, events: list[dict[str, Any]], state: dict[str, Any], dispatch: dict[str, Any],
                 hint: BaseException | None) -> dict[str, Any]:
    execution_id, step_id = state["execution_id"], dispatch["step_id"]
    refused = any(event["type"] == REFUSED and event.get("execution_id") == execution_id and
                  event.get("operation_id") == dispatch["operation_id"] for event in events)
    job_id, ownership = _job_binding(events, execution_id, step_id)
    if job_id is None:
        if refused:
            return {"kind": "failed", "status": "failed", "error": "resource_exceeded",
                    "reason_code": _refusal_code(events, state, dispatch), "retryable": False}
        return _hint_outcome(hint, started=False) or {"kind": "released", "reason_code": "not_started"}
    job = _job_queue(run).get(job_id)
    if job["protocol_id"] != dispatch["protocol"] or job["tool_id"] != dispatch["tool"]:
        raise _RecoveryError("linked job differs from dispatch")
    base = {"job_id": job_id, "ownership": ownership}
    terminal = next((event for event in reversed(events) if event["type"] == "job_terminal" and
                     event.get("job_id") == job_id), None)
    # A retry dispatch whose own job_retry_queued is missing started nothing. A job found queued here was
    # re-queued outside this dispatch: release (never block or cancel someone's queued job).
    if dispatch["attempt_kind"] == "retry" and job["status"] in {"failed", "interrupted", "queued"} and not any(
            event["type"] == "job_retry_queued" and event.get("job_id") == job_id and
            event.get("execution_link") == _link_record(execution_id, step_id, dispatch["operation_id"])
            for event in events):
        if job["status"] == "queued":
            return {"kind": "released", "reason_code": "not_started"}
        return _hint_outcome(hint, started=False) or {"kind": "released", "reason_code": "not_started"}
    status = job["status"]
    if status == "done":
        outputs = job["output_handles"]
        expected = dispatch["expected_outputs"]
        if type(outputs) is not list or len(outputs) != len(expected) or terminal is None:
            raise _RecoveryError("done job outputs differ from the expected outputs")
        metas = [_verified_output(run, handle, item["kind"], item["schema"]) for handle, item in
                 zip(outputs, expected, strict=True)]
        if dispatch["protocol"] in {"prolif_prepare_v1", "prolif_detect_v1"}:
            for handle in outputs:
                require_completed_chemical_handle(run, handle)
        return {"kind": "completed", "seq": terminal["seq"], **base,
                "outputs": {item["name"]: handle for handle, item in zip(outputs, expected, strict=True)},
                "null_result": bool(metas[-1]["null_result"]),
                "child": {"kind": "job", "job_id": job_id, "job_ownership": ownership, "event_seq": terminal["seq"],
                          "attempt_id": job.get("attempt_id")}}
    if status in {"failed", "interrupted"}:
        failure = job.get("failure") or {}
        if ownership != "owned":
            return {"kind": "failed", "status": "failed", "error": failure.get("error") or "fatal",
                    "reason_code": "shared_job_failed", "retryable": False, **base}
        if refused:
            return {"kind": "failed", "status": "failed", "error": "resource_exceeded",
                    "reason_code": _refusal_code(events, state, dispatch), "retryable": False, **base}
        outcome = _outcome_from_class(failure.get("error"), interrupted=status == "interrupted")
        if outcome["kind"] == "failed":
            # Spec §6: an owned job failure or timeout is retryable once when JobQueue.retry permits it
            # (status failed/interrupted, recovery allowance left); the workflow's own limits are handled above.
            # The queue records a timeout as resource_exceeded with a timeout message; any other
            # resource_exceeded (memory/output/staged input/recovery allowance) is not retryable.
            timeout = failure.get("message") in JOB_TIMEOUT_MESSAGES
            outcome.update(retryable=job["attempt_ordinal"] < 4 and (
                               timeout or status == "interrupted" or failure.get("error") != "resource_exceeded"),
                           reason_code="job_timeout" if timeout else
                           "job_interrupted" if status == "interrupted" else "job_failed")
        return {**outcome, **base}
    if status == "cancelled":
        if state["stop"] is not None:
            return {"kind": "cancelled", **base}
        return {"kind": "failed", "status": "failed", "error": "cancelled",
                "reason_code": "shared_job_failed" if ownership != "owned" else "job_cancelled",
                "retryable": False, **base}
    if refused and ownership == "owned":
        return {"kind": "failed_cancel_job", "status": "failed", "error": "resource_exceeded",
                "reason_code": _refusal_code(events, state, dispatch), "retryable": False, **base}
    hinted = _hint_outcome(hint, started=True) if ownership == "owned" else None
    if hinted is not None and hinted["kind"] in {"blocked", "failed"}:
        return {**hinted, "kind": hinted["kind"] + "_cancel_job", **base}
    if hinted is not None and hinted["kind"] == "deferred":
        return {**hinted, **base}
    return {"kind": "in_progress", **base}


def _report_outcome(run: Any, events: list[dict[str, Any]], state: dict[str, Any], dispatch: dict[str, Any],
                    hint: BaseException | None) -> dict[str, Any]:
    link = _link_record(state["execution_id"], dispatch["step_id"], dispatch["operation_id"])
    published = [event for event in events if event["type"] in {"report_created", "method_report_created"} and
                 event.get("execution_link") == link]
    if published:
        event = published[-1]
        field = "interaction_handle" if dispatch["analysis_type"] == "interaction_contacts" else "result_handle"
        if len(published) != 1 or event.get(field) != dispatch["source_handle"]:
            raise _RecoveryError("linked report differs from dispatch")
        module, _, _, saved = REPORTS[dispatch["analysis_type"]]
        try:
            report = getattr(module, saved)(run, event["report_handle"])
        except (inspection_reports.EvidenceError, KeyError, ValueError, TypeError, ToolFailure) as exc:
            raise _RecoveryError("linked report evidence is invalid") from exc
        manifest = report["manifest"]
        if manifest.get("schema") != dispatch["expected_outputs"][0]["schema"] or (
                dispatch["analysis_type"] != "interaction_contacts" and
                manifest.get("analysis_type") != dispatch["analysis_type"]):
            raise _RecoveryError("linked report type differs from dispatch")
        _verified_output(run, event["report_handle"], dispatch["expected_outputs"][0]["kind"],
                         dispatch["expected_outputs"][0]["schema"])
        return {"kind": "completed", "seq": event["seq"], "outputs": {"report": event["report_handle"]},
                "null_result": False, "child": {"kind": "report", "report_handle": event["report_handle"],
                                                "markdown_handle": event.get("markdown_handle"),
                                                "event_seq": event["seq"]}}
    return _hint_outcome(hint, started=False) or {"kind": "released", "reason_code": "not_started"}


def _cancel_owned_job(run: Any, execution_id: str, step_id: str, job_id: str) -> None:
    job = _job_queue(run).get(job_id)
    if job["status"] in {"done", "failed", "cancelled", "interrupted"} or job.get("cancel_requested"):
        return
    stop_link = ExecutionLink(execution_id=execution_id, step_id=step_id, operation_id=f"stop_{uuid.uuid4().hex}")
    _job_queue(run).request_cancel(job_id, execution_link=stop_link)


def _summary_content(state: dict[str, Any], plan: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    execution_id = state["execution_id"]
    rows = []
    for step in plan["steps"]:
        item = state["steps"][step["step_id"]]
        result = item["result"]
        job_id, ownership = _job_binding(events, execution_id, step["step_id"])
        outputs = [result["outputs"][output["name"]] for output in step["outputs"]]
        rows.append({"step_id": step["step_id"], "operation": step["operation"], "status": "completed",
                     "null_result": result["null_result"], "output_handles": outputs,
                     "report_handle": result["outputs"].get("report"),
                     "child_call_ids": _child_call_ids(events, execution_id, step["step_id"]),
                     "job_ids": [job_id] if job_id else [], "job_ownership": ownership,
                     "attempts": item["attempts"]})
    last = max(state["steps"][sid]["result"]["seq"] for sid in state["order"])
    return {"schema": SUMMARY_SCHEMA, "plan_handle": state["plan_handle"], "plan_hash": state["plan_sha256"],
            "execution_id": execution_id, "goal": plan["goal"], "source": plans.SOURCE,
            "approval_event_seq": state["approval"]["seq"], "first_event_seq": state["created_seq"],
            "last_event_seq": last, "steps": rows, "physical_attempts": len(state["attempts"]),
            "note": ("Links only. Numeric scientific values are read from each linked report's validated fields. "
                     "first_event_seq is the execution creation event; last_event_seq is the seq of the last "
                     "step-completion event (the completion event is recorded after this summary).")}


def _reconcile(run: Any, execution_id: str, plan: dict[str, Any], *, hint: BaseException | None = None,
               driver_live: bool = False, request_id: str | None = None) -> None:
    """Record outcomes already durable in linked child events (no physical work). Workflow lock held.

    ``driver_live`` means another request's child may still be running: only Stop propagation happens.
    """
    orphan_fixed = False
    for _ in range(len(plan["steps"]) + 4):
        events = list(run.events.read())
        state = _fold(events, execution_id, plan)
        if state["complete"] is not None or state["blocked"] is not None:
            return
        current = _current(state)
        if current is None:
            if state["stop"] is not None or state["approval"] is None:
                return
            _fault("before_summary")
            content = _summary_content(state, plan, events)
            with run._transition():
                stored = run.store.put(SUMMARY_KIND, SUMMARY_SCHEMA, content, produced_by=execution_id,
                                       summary={"execution_id": execution_id, "plan_handle": state["plan_handle"]})
                run.events.append(COMPLETE, execution_id=execution_id, request_id=request_id,
                                  summary_handle=stored.handle)
            return
        step = state["steps"][current]
        dispatch = step["dispatch"]
        if dispatch is None:
            return
        lane = dispatch["lane"]
        if driver_live:
            if state["stop"] is not None and lane == "durable_job":
                job_id, ownership = _job_binding(events, execution_id, current)
                if job_id and ownership == "owned":
                    _cancel_owned_job(run, execution_id, current, job_id)
            return
        try:
            outcome = (_run_call_outcome if lane == "run_call" else _job_outcome if lane == "durable_job"
                       else _report_outcome)(run, events, state, dispatch, hint)
        except (_RecoveryError, KeyError, ValueError, TypeError, ToolFailure) as exc:
            _blocked(run, execution_id, request_id, "recovery_error", current,
                     {"diagnostic": type(exc).__name__})
            return
        kind = outcome["kind"]
        common = {"execution_id": execution_id, "step_id": current, "operation_id": dispatch["operation_id"],
                  "request_id": request_id}
        if kind == "orphan":
            if orphan_fixed:
                return
            orphan_fixed = True
            try:
                with run._mutation():  # existing runtime orphan reconciliation (tool_interrupted, wall charge)
                    pass
            except ToolFailure as exc:
                if exc.detail.get("busy") is not True:
                    raise
                return
            continue
        if kind == "in_progress":
            if state["stop"] is not None and outcome.get("ownership") == "owned":
                _cancel_owned_job(run, execution_id, current, outcome["job_id"])
                continue_after = _job_queue(run).get(outcome["job_id"])["status"] == "cancelled"
                if continue_after:
                    continue
            elif state["stop"] is not None and outcome.get("ownership") == "observed_shared":
                _append(run, STEP_FAILED, **common, status="cancelled", error="cancelled",
                        reason_code="shared_job_detached", message=MESSAGES["shared_job_detached"], retryable=False)
            return
        if kind == "completed":
            if state["stop"] is not None and outcome["seq"] > state["stop"]["seq"]:
                _append(run, STEP_FAILED, **common, status="cancelled", error="cancelled",
                        reason_code="result_after_stop_not_adopted", message=None, retryable=False)
                return
            _append(run, STEP_DONE, **common, outputs=outcome["outputs"], null_result=outcome["null_result"],
                    child=outcome["child"])
            hint = None
            _fault("after_step_recorded")
            continue
        if state["stop"] is not None:
            if kind.endswith("_cancel_job") or kind in {"deferred"}:
                job_id = outcome.get("job_id")
                if job_id and outcome.get("ownership") == "owned":
                    _cancel_owned_job(run, execution_id, current, job_id)
                    continue
            _append(run, STEP_FAILED, **common, status="cancelled", error="cancelled", reason_code="stopped",
                    message=None, retryable=False)
            return
        if kind in {"blocked_cancel_job", "failed_cancel_job"}:
            _cancel_owned_job(run, execution_id, current, outcome["job_id"])
            kind = kind.removesuffix("_cancel_job")
        if kind == "cancelled":
            _append(run, STEP_FAILED, **common, status="cancelled", error="cancelled", reason_code="stopped",
                    message=None, retryable=False)
            return
        if kind == "released":
            _append(run, RELEASED, **common, reason_code=outcome["reason_code"])
            return
        if kind == "deferred":
            if step["deferred"] != outcome["reason_code"]:
                _append(run, DEFERRED, **common, reason_code=outcome["reason_code"])
            return
        if kind == "blocked":
            _append(run, STEP_FAILED, **common, status="blocked", error=outcome.get("error"),
                    reason_code=outcome["reason_code"], message=None, retryable=False)
            _blocked(run, execution_id, request_id, outcome["reason_code"], current, {"error": outcome.get("error")})
            return
        if kind == "failed":
            _append(run, STEP_FAILED, **common, status=outcome["status"], error=outcome.get("error"),
                    reason_code=outcome["reason_code"], message=MESSAGES.get(outcome["reason_code"]),
                    retryable=bool(outcome.get("retryable")))
            return
        raise ValueError("unknown reconciliation outcome")


# ---------------------------------------------------------------------------------------------- Advance / Retry
def advance(run: Any, execution_id: Any, request_id: Any, expected_revision: Any) -> dict[str, Any]:
    return _drive(run, execution_id, "advance", request_id, expected_revision, None)


def retry(run: Any, execution_id: Any, request_id: Any, expected_revision: Any, step_id: Any) -> dict[str, Any]:
    if type(step_id) is not str or not STEP_ID_RE.fullmatch(step_id):
        raise ToolFailure(FailureClass.input_invalid, "step_id must be s01..s08")
    return _drive(run, execution_id, "retry", request_id, expected_revision, step_id)


def _drive(run: Any, execution_id: Any, action: str, request_id: Any, expected: Any,
           step_id: str | None) -> dict[str, Any]:
    request_id = plans._request_uuid(request_id)
    body = {"expected_revision": expected, **({"step_id": step_id} if action == "retry" else {})}
    driver: _DriverLock | None = None
    work: tuple[str, dict[str, Any], str] | None = None
    with _workflow_lock(run):
        events = list(run.events.read())
        plan = _plan_for(run, events, execution_id)
        sha = _request_sha(action, execution_id, body)
        replay = _replay(run, events, request_id, sha, execution_id)
        if replay is not None:
            return replay
        driver = _DriverLock(run, execution_id)
        if not driver.try_acquire():
            raise AnalysisError(409, "busy", "다른 요청을 처리 중입니다. 잠시 뒤 다시 시도하세요.")
        try:
            state = _fold(events, execution_id, plan)
            _check_revision(state, expected)
            _refuse_plan_only(state)
            # Recovery first: this request holds the driver lock, so every pending driver request is stale.
            _close_stale(run, execution_id, state, None, False)
            _reconcile(run, execution_id, plan)
            events = list(run.events.read())
            state = _fold(events, execution_id, plan)
            status, retryable = _derive(state, plan, events, _jobs_if_needed(run, plan), False)
            if state["approval"] is None and status == "awaiting_approval":
                raise AnalysisError(412, "plan_not_approved", "plan approval is required before execution")
            if action == "advance" and status == "failed" and retryable is not None:
                raise AnalysisError(412, "retry_or_stop_required", "retry or stop the failed step first",
                                    {"retryable_step": retryable})
            if action == "retry" and (status != "failed" or retryable != step_id):
                raise AnalysisError(412, "retry_not_allowed", "this step has no remaining explicit retry",
                                    {"retryable_step": retryable})
            _admit(run, execution_id, request_id, sha, action, expected,
                   **({"step_id": step_id} if step_id else {}))
            work, outcome = _next_work(run, execution_id, plan, action, request_id)
            if work is None:
                _finish(run, execution_id, request_id, action, outcome)
        except BaseException:
            driver.release()
            raise
    if work is None:
        driver.release()
        return _response(run, execution_id, request_id, replayed=False)
    try:
        mode, dispatch, current = work
        hint: BaseException | None = None
        try:
            _fault("after_dispatch")
            _child(run, plan, execution_id, current, dispatch, mode)
            _fault("after_child")
        except (ToolFailure, ApprovalRequired, ExecutionStopped, RunCancelled, LoopStop,
                inspection_reports.EvidenceError) as exc:
            hint = exc
        except Exception as exc:  # noqa: BLE001 - any other child error is recorded fail-closed, never retried
            hint = exc
        with _workflow_lock(run):
            _reconcile(run, execution_id, plan, hint=hint, request_id=request_id)
            _fault("before_request_completed")
            outcome = "run_busy" if isinstance(hint, ToolFailure) and hint.detail.get("busy") is True else "advanced"
            _finish(run, execution_id, request_id, action, outcome)
    finally:
        driver.release()
    return _response(run, execution_id, request_id, replayed=False)


def _cancel_open_owned_job(run: Any, execution_id: str, state: dict[str, Any], events: list[dict[str, Any]],
                           step_id: str) -> None:
    """Before a terminal record closes an open dispatch, cancel its waiting owned job (as ``_reconcile`` does)."""
    if state["steps"][step_id]["dispatch"] is None:
        return
    job_id, ownership = _job_binding(events, execution_id, step_id)
    if job_id is not None and ownership == "owned":
        _cancel_owned_job(run, execution_id, step_id, job_id)


def _next_work(run: Any, execution_id: str, plan: dict[str, Any], action: str,
               request_id: str) -> tuple[tuple[str, dict[str, Any], str] | None, str]:
    """After reconciliation: at most one step dispatch or one job transition. Workflow lock held."""
    events = list(run.events.read())
    state = _fold(events, execution_id, plan)
    jobs = _jobs(run) if any(step["lane"] == "durable_job" for step in plan["steps"]) else {}
    status, retryable = _derive(state, plan, events, jobs, False)
    current = _current(state)
    if action == "advance":
        if status == "failed" and retryable is not None:
            return None, "retry_or_stop_required"
        if status != "ready" or current is None:
            return None, "no_op_" + status
    elif status != "failed" or retryable is None or retryable != current:
        return None, "retry_not_allowed"
    step = state["steps"][current]
    exhausted = _limits_exhausted(state, plan, events, _plan_step(plan, current)["lane"])
    if exhausted is not None:
        _cancel_open_owned_job(run, execution_id, state, events, current)
        _append(run, STEP_FAILED, execution_id=execution_id, step_id=current, operation_id=None,
                request_id=request_id, status="failed", error="resource_exceeded", reason_code=exhausted,
                message=MESSAGES[exhausted], retryable=False)
        return None, "resource_exceeded"
    compatibility = plans.check_compatibility(run, plan)
    if (not compatibility["compatible"] or state["approval"]["plan_sha256"] != plans.canonical_plan_hash(plan) or
            state["approval"]["compatibility_sha256"] !=
            hashlib.sha256(canonical_json(plan["compatibility"])).hexdigest()):
        _cancel_open_owned_job(run, execution_id, state, events, current)
        _blocked(run, execution_id, request_id, "compatibility_changed", current,
                 {"mismatched_steps": compatibility["mismatched_steps"]})
        return None, "blocked"
    if step["dispatch"] is not None:
        # Owned job submitted earlier and not started (approval/budget/busy): the job transition is start.
        job_id, ownership = _job_binding(events, execution_id, current)
        job = jobs.get(job_id) if job_id else None
        if job is None or ownership != "owned" or job["status"] not in {"queued", "claimed"}:
            return None, "no_op_" + status
        return ("start", {**step["dispatch"], "job_id": job_id}, current), "started"
    # A retry dispatch released before its child started is resumed by the next Advance as that retry.
    mode = "retry" if action == "retry" or step["failure"] is not None else "new"
    try:
        record = _dispatch_record(run, plan, state, current)
    except _IdentityChanged as exc:
        _blocked(run, execution_id, request_id, "identity_changed", current, message=str(exc))
        return None, "blocked"
    except _Incompatible:
        _blocked(run, execution_id, request_id, "compatibility_changed", current)
        return None, "blocked"
    except ToolFailure as exc:
        code = exc.detail.get("reason_code") or "step_" + exc.cls.value
        _blocked(run, execution_id, request_id, code, current, {"error": exc.cls.value})
        return None, "blocked"
    if mode == "retry" and record["lane"] == "durable_job":
        job_id, ownership = _job_binding(events, execution_id, current)
        if job_id is None or ownership != "owned":
            return None, "retry_not_allowed"
        record["job_id"] = job_id
    dispatch = _append(run, DISPATCHED, execution_id=execution_id, step_id=current,
                       operation_id=f"op_{uuid.uuid4().hex}", request_id=request_id,
                       plan_sha256=plans.canonical_plan_hash(plan),
                       attempt_kind="retry" if mode == "retry" else "initial", **record)
    return (mode, dispatch, current), "dispatched"


# ---------------------------------------------------------------------------------------------- summary
def summary(run: Any, execution_id: Any) -> dict[str, Any]:
    events = list(run.events.read())
    plan = _plan_for(run, events, execution_id)
    state = _fold(events, execution_id, plan)
    if state["complete"] is None:
        raise AnalysisError(404, "not_found", "workflow summary exists only for a complete execution")
    handle = state["complete"]["summary_handle"]
    meta = run.store.meta(handle)
    if (meta["kind"], meta["schema"]) != (SUMMARY_KIND, SUMMARY_SCHEMA):
        raise ValueError("workflow summary handle has the wrong type")
    content = run.store.load_bounded_json(handle, MAX_SUMMARY_BYTES)  # hash-verified stored JSON
    raw = canonical_json(content)  # the stored canonical bytes (the handle hash covers exactly these)
    if content.get("execution_id") != execution_id or content.get("plan_handle") != state["plan_handle"]:
        raise ValueError("workflow summary differs from its execution")
    return {"handle": handle, "summary": content, "raw": raw}
