"""Retry policy, loop guards and budget (plan §4.2–4.3)."""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from ..core.errors import FailureClass


class RetryRule(BaseModel):
    max: int = 0
    backoff: str | None = None
    base_s: float = 2.0
    requires_different_args: bool = False
    must_run_prerequisite: bool = False


DEFAULT_RETRY: dict[FailureClass, RetryRule] = {
    FailureClass.transient: RetryRule(max=3, backoff="exponential", base_s=2),
    FailureClass.input_invalid: RetryRule(max=1, requires_different_args=True),
    FailureClass.precondition: RetryRule(max=1, must_run_prerequisite=True),
    FailureClass.resource_exceeded: RetryRule(max=0),
    FailureClass.fatal: RetryRule(max=0),
}


def backoff_s(rule: RetryRule, attempt: int) -> float:
    return rule.base_s * (2 ** (attempt - 1)) if rule.backoff == "exponential" else 0.0


class LoopStop(Exception):
    """Raised when a loop guard trips. The orchestrator checkpoints and asks."""
    def __init__(self, reason: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


@dataclass
class LoopGuard:
    no_progress_steps: int = 4
    repeated_call_hash: int = 2
    oscillation_window: int = 6
    _calls: Counter = field(default_factory=Counter)
    _recent: deque = field(default_factory=lambda: deque(maxlen=64))
    _since_progress: int = 0
    _seen_handles: set = field(default_factory=set)

    def before_call(self, call_hash: str, tool: str) -> None:
        self._calls[call_hash] += 1
        if self._calls[call_hash] > self.repeated_call_hash:
            raise LoopStop("repeated_call_hash", {"tool": tool, "count": self._calls[call_hash]})
        self._recent.append(tool)
        w = list(self._recent)[-self.oscillation_window:]
        if len(w) == self.oscillation_window and len(set(w)) == 2 and all(w[i] != w[i + 1] for i in range(len(w) - 1)):
            raise LoopStop("oscillation", {"pattern": w})

    def after_call(self, new_handles: set[str]) -> None:
        fresh = new_handles - self._seen_handles
        self._seen_handles |= new_handles
        self._since_progress = 0 if fresh else self._since_progress + 1
        if self._since_progress >= self.no_progress_steps:
            raise LoopStop("no_progress", {"steps": self._since_progress})


class BudgetLimits(BaseModel):
    wall_clock_s: float = 1800
    expensive_calls: int = 8
    external_tokens: int = 120_000
    usd: float = 2.00


class Budget(BaseModel):
    limits: BudgetLimits = BudgetLimits()
    wall_clock_s: float = 0
    expensive_calls: int = 0
    external_tokens: int = 0
    usd: float = 0

    def would_exceed(self, **delta: float) -> str | None:
        """Return the first axis that `delta` would push over its limit, else None."""
        for axis, d in delta.items():
            if getattr(self, axis) + d > getattr(self.limits, axis):
                return axis
        return None

    def charge(self, **delta: float) -> None:
        for axis, d in delta.items():
            setattr(self, axis, getattr(self, axis) + d)

    def snapshot(self) -> dict[str, Any]:
        return {a: {"used": getattr(self, a), "limit": getattr(self.limits, a)}
                for a in ("wall_clock_s", "expensive_calls", "external_tokens", "usd")}
