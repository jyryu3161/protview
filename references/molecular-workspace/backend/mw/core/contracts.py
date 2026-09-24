"""Tool type contracts (plan §3.3, §5).

A tool declares which handle kinds each argument accepts. Mismatches are rejected
BEFORE execution, with a conversion path in `fix`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Literal

import yaml
from pydantic import BaseModel

from .errors import FailureClass, Fix, ToolFailure
from .handles import HANDLE_PREFIX

CostClass = Literal["cheap", "moderate", "expensive"]


class ToolSpec(BaseModel):
    name: str
    level: Literal["L1", "L2", "L3", "L4", "L5"]
    version: str = "0.1.0"
    accepts: dict[str, list[str]] = {}          # arg -> accepted handle kinds
    params: dict[str, dict[str, Any]] = {}      # scalar args: {type, enum?, min?, max?, default?}
    emits: str
    cost_class: CostClass = "cheap"
    idempotent: bool = True
    read_only: bool = False
    typical_runtime_s: float = 1.0
    description: str = ""


# kind -> (tool that converts to it, arg name that tool takes)
CONVERSIONS: dict[str, tuple[str, str]] = {
    "prepared_structure": ("prepare_structure", "structure"),
    "relaxed_structure": ("relax_structure", "structure"),
}


def load_specs(path: Path) -> dict[str, ToolSpec]:
    data = yaml.safe_load(Path(path).read_text())
    return {t["name"]: ToolSpec(**t) for t in data["tools"]}


def check_args(spec: ToolSpec, args: dict[str, Any], kind_of: Callable[[str], str]) -> dict[str, Any]:
    """Validate args against the contract. Returns args with scalar defaults filled."""
    out = dict(args)
    for arg, kinds in spec.accepts.items():
        val = args.get(arg)
        if val is None:
            raise ToolFailure(FailureClass.input_invalid, f"missing handle argument '{arg}'")
        vals = val if isinstance(val, list) else [val]
        for h in vals:
            if not isinstance(h, str) or not h.startswith(HANDLE_PREFIX):
                raise ToolFailure(FailureClass.input_invalid,
                                  f"'{arg}' must be a handle string (obj://...), got {type(h).__name__}")
            try:
                k = kind_of(h)
            except KeyError:
                raise ToolFailure(FailureClass.input_invalid, f"unknown handle {h}")
            if k not in kinds:
                target = next((x for x in kinds if x in CONVERSIONS), None)
                fix = None
                if target:
                    tool, targ = CONVERSIONS[target]
                    fix = Fix(tool=tool, args={targ: h})
                raise ToolFailure(FailureClass.precondition,
                                  f"{spec.name}.{arg} accepts {kinds}, got '{k}'", fix=fix)
    for name, p in spec.params.items():
        if name not in out:
            if "default" in p:
                out[name] = p["default"]
            elif p.get("required"):
                raise ToolFailure(FailureClass.input_invalid, f"missing param '{name}'")
            continue
        v = out[name]
        if "enum" in p:
            allowed = p["enum"]
            bad = [x for x in (v if isinstance(v, list) else [v]) if x not in allowed]
            if bad:
                raise ToolFailure(FailureClass.input_invalid, f"'{name}' must be one of {allowed}, got {bad}")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if "min" in p and v < p["min"] or "max" in p and v > p["max"]:
                raise ToolFailure(FailureClass.input_invalid,
                                  f"'{name}'={v} outside [{p.get('min')}, {p.get('max')}]")
    return out
