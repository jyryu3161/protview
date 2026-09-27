"""Runtime policy values; durable branch state is reconstructed by Run."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

TRANSIENT_DELAYS_S = (2, 4, 8)


class LoopStop(Exception):
    def __init__(self, reason: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


@dataclass
class LoopGuard:
    no_progress_steps: int = 4
    repeated_call_hash: int = 2
    oscillation_window: int = 6


class BudgetLimits(BaseModel):
    wall_clock_s: float = Field(default=1800, gt=0, allow_inf_nan=False)
    expensive_calls: int = Field(default=8, ge=0)
    external_tokens: int = Field(default=120_000, ge=0)
    usd: float = Field(default=2.00, ge=0, allow_inf_nan=False)


class Budget(BaseModel):
    limits: BudgetLimits = Field(default_factory=BudgetLimits)
    wall_clock_s: float = 0
    expensive_calls: int = 0
    external_tokens: int = 0
    usd: float = 0

    def would_exceed(self, **delta: float) -> str | None:
        for axis, amount in delta.items():
            if getattr(self, axis) + amount > getattr(self.limits, axis):
                return axis
        return None

    def charge(self, **delta: float) -> None:
        for axis, amount in delta.items():
            setattr(self, axis, getattr(self, axis) + amount)

    def snapshot(self) -> dict[str, Any]:
        return {axis: {"used": getattr(self, axis), "limit": getattr(self.limits, axis)}
                for axis in ("wall_clock_s", "expensive_calls", "external_tokens", "usd")}
