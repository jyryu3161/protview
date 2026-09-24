"""Wiring: config -> registry -> runs. One place that knows where everything lives."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml

from .runtime.guards import Budget, BudgetLimits, LoopGuard
from .runtime.orchestrator import Run
from .tools import energetic, structural
from .tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]          # repo root
CONFIG = ROOT / "config"


def load_config(path: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load((path or CONFIG / "default.yaml").read_text())


def build_registry(tools_yaml: Path | None = None) -> ToolRegistry:
    reg = ToolRegistry.from_yaml(tools_yaml or CONFIG / "tools.yaml")
    structural.register(reg)
    energetic.register(reg)
    return reg


def new_run(runs_dir: Path, *, dry_run: bool = True, seed: int = 1207, run_id: str | None = None,
            config: dict[str, Any] | None = None, registry: ToolRegistry | None = None) -> Run:
    cfg = config or load_config()
    rid = run_id or time.strftime("run_%Y%m%d_%H%M%S")
    g = cfg["runtime"]["loop_guards"]
    return Run(run_id=rid, run_dir=Path(runs_dir) / rid, registry=registry or build_registry(),
               dry_run=dry_run, seed=seed,
               budget=Budget(limits=BudgetLimits(**cfg["runtime"]["budget"])),
               guard=LoopGuard(**g))
