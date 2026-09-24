"""Orchestrator: the ONLY path by which any tool runs — for the agent and for humans.

Owns (plan §4, §12: do not delegate these to an agent framework):
  contract check -> idempotency/resume -> loop guards -> approval gate -> budget
  -> execute (or dry-run stub) -> retry by failure class -> event log
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..core.contracts import check_args
from ..core.errors import FailureClass, ToolFailure
from ..core.events import DecisionSource, EventLog, idempotency_key
from ..core.handles import Handle, ObjectStore
from ..tools.registry import ToolContext, ToolRegistry
from .guards import DEFAULT_RETRY, Budget, LoopGuard, LoopStop, backoff_s


class ApprovalRequired(Exception):
    def __init__(self, gate: str, tool: str, args: dict[str, Any], reason: str) -> None:
        super().__init__(reason)
        self.gate, self.tool, self.args, self.reason = gate, tool, args, reason


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
    approved_expensive: bool = False

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir)
        self.store = ObjectStore(self.run_dir, self.run_id)
        self.events = EventLog(self.run_dir / "events.jsonl")
        self._n = sum(1 for e in self.events.read() if e["type"] == "tool_called")
        if not any(True for _ in self.events.read()):
            self.events.append("run_started", run_id=self.run_id, dry_run=self.dry_run, seed=self.seed)

    # ------------------------------------------------------------------
    def decide(self, source: DecisionSource, question: str, answer: Any, **meta: Any) -> None:
        self.events.append("decision", source=source, question=question, answer=answer, **meta)

    def approve(self, gate: str, by: str = "human") -> None:
        if gate == "expensive_first_call":
            self.approved_expensive = True
        self.events.append("approval_resolved", gate=gate, approved=True, by=by)

    # ------------------------------------------------------------------
    def call(self, tool: str, args: dict[str, Any], *, decided_by: DecisionSource = "rule",
             _attempt: int = 1) -> Handle:
        spec = self.registry.specs[tool]
        args = check_args(spec, args, self.store.kind_of)       # rejects BEFORE execution
        key = idempotency_key(tool, spec.version, args)

        done = self.events.completed().get(key)
        if done:                                                 # resume / cache: re-attach handle
            self.events.append("tool_succeeded", tool=tool, key=key, call_id=done["call_id"],
                               output=done["output"], cached=True)
            return Handle(**done["output"])

        self.guard.before_call(key, tool)                        # may raise LoopStop

        if spec.cost_class == "expensive" and not self.dry_run:
            if not self.approved_expensive:
                self.events.append("approval_requested", gate="expensive_first_call", tool=tool, args=args)
                raise ApprovalRequired("expensive_first_call", tool, args, f"{tool} is expensive (first call)")
            axis = self.budget.would_exceed(expensive_calls=1)
            if axis:
                self.events.append("checkpoint", reason="budget", axis=axis, budget=self.budget.snapshot())
                raise ApprovalRequired("budget", tool, args, f"budget axis '{axis}' exhausted")

        self._n += 1
        call_id = f"call_{self._n:04d}"
        self.events.append("tool_called", tool=tool, key=key, call_id=call_id, args=args,
                           decided_by=decided_by, attempt=_attempt, version=spec.version)
        fn = self.registry.impls[tool]
        if self.dry_run and spec.cost_class == "expensive":
            fn = self.registry.stubs.get(tool, fn)
        ctx = ToolContext(store=self.store, call_id=call_id, dry_run=self.dry_run, seed=self.seed)
        t0 = time.time()
        try:
            out = fn(ctx, **args)
        except ToolFailure as f:
            self.events.append("tool_failed", tool=tool, key=key, call_id=call_id, **f.to_dict())
            rule = DEFAULT_RETRY[f.cls]
            if f.cls == FailureClass.transient and _attempt <= rule.max:
                self.sleep(backoff_s(rule, _attempt))
                self.guard._calls[key] -= 1                      # a transient retry is not a repeat
                return self.call(tool, args, decided_by="rule", _attempt=_attempt + 1)
            raise                                                # others: caller/agent decides
        dt = time.time() - t0
        if spec.cost_class == "expensive" and not self.dry_run:
            self.budget.charge(expensive_calls=1)
        self.budget.charge(wall_clock_s=dt)
        self.events.append("tool_succeeded", tool=tool, key=key, call_id=call_id,
                           output=out.model_dump(by_alias=True), duration_s=dt,
                           null_result=out.null_result)
        self.guard.after_call({out.handle})
        return out


def replay(events_path: Path, new_dir: Path, registry: ToolRegistry, run_id: str) -> set[str]:
    """Re-execute every tool_called from an events.jsonl into a fresh run dir.

    Reproducibility test (plan §9): the handle set must be identical.
    Input files referenced by load_structure must still exist.
    """
    src = EventLog(events_path)
    started = next(e for e in src.read() if e["type"] == "run_started")
    run = Run(run_id=run_id, run_dir=new_dir, registry=registry, dry_run=started["dry_run"],
              seed=started["seed"], approved_expensive=True)
    run.guard = LoopGuard(repeated_call_hash=10**9, no_progress_steps=10**9)
    for e in src.read():
        if e["type"] == "tool_succeeded" and not e.get("cached"):
            called = next(c for c in src.read() if c["type"] == "tool_called" and c["call_id"] == e["call_id"])
            run.call(called["tool"], called["args"], decided_by=called["decided_by"])
    return run.store.handles()
