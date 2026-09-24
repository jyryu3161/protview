"""Tool registry: binds ToolSpecs (config/tools.yaml) to Python implementations.

An implementation has the signature  fn(ctx: ToolContext, **args) -> Handle
and must:
  * put its output in ctx.store and return the Handle (never raw data)
  * raise ToolFailure(<class>) on failure
  * return a Handle with null_result=True for an empty scientific result
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..core.contracts import ToolSpec, load_specs
from ..core.handles import Handle, ObjectStore

ToolFn = Callable[..., Handle]


@dataclass
class ToolContext:
    store: ObjectStore
    call_id: str
    dry_run: bool = False
    seed: int = 0


class ToolRegistry:
    def __init__(self, specs: dict[str, ToolSpec]) -> None:
        self.specs = specs
        self.impls: dict[str, ToolFn] = {}
        self.stubs: dict[str, ToolFn] = {}   # used for expensive tools in dry_run

    @classmethod
    def from_yaml(cls, path: Path) -> "ToolRegistry":
        return cls(load_specs(path))

    def register(self, name: str, *, stub: ToolFn | None = None) -> Callable[[ToolFn], ToolFn]:
        if name not in self.specs:
            raise KeyError(f"tool '{name}' has no spec in tools.yaml")

        def deco(fn: ToolFn) -> ToolFn:
            self.impls[name] = fn
            if stub:
                self.stubs[name] = stub
            return fn
        return deco

    def visible(self, levels: set[str]) -> list[ToolSpec]:
        """Hierarchical exposure (plan §5.2): the agent sees L5 by default."""
        return [s for s in self.specs.values() if s.level in levels and s.name in self.impls]
