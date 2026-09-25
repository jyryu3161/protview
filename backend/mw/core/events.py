"""Append-only event log — the single source of truth (plan §4.4, §9).

run.sqlite / index.sqlite are derived and may be deleted; events.jsonl may not.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

from .handles import canonical_json, sha256_hex

EventType = Literal[
    "run_started", "goal", "tool_called", "tool_succeeded", "tool_failed",
    "decision", "approval_requested", "approval_resolved", "egress", "llm_call",
    "checkpoint", "run_finished", "object_created", "upload_received",
    "proposal_rejected", "branch_proposed", "branch_observed", "cache_hit",
    "budget_reserved", "wall_charged", "tool_interrupted", "clock_anomaly",
    "budget_limit_updated", "cancel_requested", "run_cancelled",
    "backoff_started", "backoff_completed", "backoff_interrupted",
    "egress_budget_settled",
    "job_submitted", "job_claimed", "job_blocked", "job_cancel_requested",
    "job_dispatch_intent", "job_launch_identity", "job_execution_authorized",
    "job_result_candidate", "job_terminal", "job_cleanup_pending",
    "job_worker_started", "job_retry_queued",
    "job_cleanup_verified",
    "workflow_started", "workflow_step_completed", "workflow_outcome", "report_created",
    "viewer_consent_changed", "viewer_session_created", "viewer_scene_updated",
    "viewer_intent_requested", "viewer_intent_outcome", "viewer_intent_cancelled",
    "viewer_command_ack", "viewer_dispatch_started",
]
DecisionSource = Literal["rule", "jev", "frontier", "human"]


def normalize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Drop None, sort keys (canonical_json sorts). Floats kept as given."""
    return {k: v for k, v in sorted(args.items()) if v is not None}


def idempotency_key(tool: str, version: str, args: dict[str, Any]) -> str:
    return sha256_hex(canonical_json({"tool": tool, "v": version, "args": normalize_args(args)}))


class EventLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.path.with_name("events.lock")

    def append(self, type: EventType, **data: Any) -> dict[str, Any]:
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            existing = self._read_unlocked()
            ev = {"seq": len(existing) + 1, "ts": time.time(), "type": type, **data}
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        return ev

    def read(self) -> Iterator[dict[str, Any]]:
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            events = self._read_unlocked()
        return iter(events)

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            events = [json.loads(line) for line in f if line.strip()]
        if any(event.get("seq") != i for i, event in enumerate(events, 1)):
            raise ValueError("broken event sequence")
        return events

    def completed(self) -> dict[str, dict[str, Any]]:
        """idempotency_key -> tool_succeeded event (used to skip on resume)."""
        return {e["key"]: e for e in self.read()
                if e["type"] == "tool_succeeded" and not e.get("cached")}
