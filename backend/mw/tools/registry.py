"""Tool registry: binds ToolSpecs (config/tools.yaml) to Python implementations.

An implementation has the signature  fn(ctx: ToolContext, **args) -> Handle
and must:
  * put its output in ctx.store and return the Handle (never raw data)
  * raise ToolFailure(<class>) on failure
  * return a Handle with null_result=True for an empty scientific result
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.contracts import ToolSpec, load_specs
from ..core.handles import Handle, ObjectStore

ToolFn = Callable[..., Handle]
# Pre-check hook: (store, raw args, previous bound or None) -> (normalized args, bound). Runs inside the orchestrator's
# argument validation on every call path, before the generic check, the cache key and the implementation; it raises
# ToolFailure. A bound may expose ``key_fields`` (merged into the cache key) and reaches the tool as ToolContext.bound.
PrecheckFn = Callable[[Any, dict[str, Any], Any], tuple[dict[str, Any], Any]]


@dataclass
class ToolContext:
    store: ObjectStore
    call_id: str
    dry_run: bool = False
    seed: int = 0
    source_bytes: bytes | None = None
    source_format: str | None = None
    remaining_s: Callable[[], float] | None = None
    check_cancelled: Callable[[], None] | None = None
    bound: Any = None


class ToolRegistry:
    def __init__(self, specs: dict[str, ToolSpec]) -> None:
        self.specs = specs
        self.impls: dict[str, ToolFn] = {}
        self.stubs: dict[str, ToolFn] = {}   # used for expensive tools in dry_run
        self.unavailable: dict[str, str] = {}
        self.prechecks: dict[str, PrecheckFn] = {}

    @classmethod
    def from_yaml(cls, path: Path) -> ToolRegistry:
        return cls(load_specs(path))

    def register(self, name: str, *, stub: ToolFn | None = None,
                 unavailable_reason: str | None = None,
                 precheck: PrecheckFn | None = None) -> Callable[[ToolFn], ToolFn]:
        if name not in self.specs:
            raise KeyError(f"tool '{name}' has no spec in tools.yaml")

        def deco(fn: ToolFn) -> ToolFn:
            self.impls[name] = fn
            if stub:
                self.stubs[name] = stub
            if unavailable_reason:
                self.unavailable[name] = unavailable_reason
            if precheck:
                self.prechecks[name] = precheck
            return fn
        return deco

    def visible(self, levels: set[str]) -> list[ToolSpec]:
        """Hierarchical exposure (plan §5.2): the agent sees L5 by default."""
        return [s for s in self.specs.values() if s.level in levels and s.name in self.impls
                and s.name not in self.unavailable]
