"""M29 ``repair_structure``: the job-only tool registration and the free preflight read (spec 4.1, 4.3, 4.6).

``repair_structure`` runs only as the durable job ``pdbfixer_repair_v1`` (``JobQueue``); ``Run.call`` refuses it as a
job-only tool. ``preflight(run, structure)`` answers ``structure_repair_preflight@1`` and never creates an event,
tool call or job: the defect analysis of the core (gemmi + the installed template, no PDBFixer), the run's expensive
budget (one unit per job; a short budget is ``shortfall``, never a refusal) and the admission outcome of
``POST /runs/{rid}/jobs`` for this structure in the job order (input 422s -> 412 unavailability -> 422
``repair_not_possible`` -> 429 staged size). A refused admission and an unavailable environment are answered with
``admission.admitted: false`` (HTTP 200).
"""
from __future__ import annotations

from typing import Any

from .. import structure_repair_constants as K
from .. import structure_repair_jobs as jobs
from ..core.errors import FailureClass, ToolFailure
from ..core.handles import Handle
from .registry import ToolContext, ToolRegistry

AXES = ("expensive_calls", "wall_clock_s")
UNITS_PER_JOB = 1
PREFLIGHT_KEYS = ("schema", "starts_job", "capability", "structure", "repairable", "blockers", "defects",
                  "expected_added_residues", "expected_added_heavy_atoms", "budget", "remaining", "shortfall",
                  "admission", "statements")


def register(reg: ToolRegistry) -> None:
    @reg.register(K.TOOL, unavailable_reason="use the fixed durable PDBFixer structure-repair job lane")
    def repair_structure(ctx: ToolContext, **kwargs: object) -> Handle:
        raise ToolFailure(FailureClass.precondition, "submit through the durable structure-repair job lane")


def _admission(exc: ToolFailure | None) -> dict[str, Any]:
    if exc is None:
        return {"admitted": True, "error": None, "reason_code": None, "message": None, "detail": None}
    return {"admitted": False, "error": exc.cls.value, "reason_code": (exc.detail or {}).get("reason_code"),
            "message": exc.message, "detail": exc.detail}


def preflight(run: Any, structure: Any) -> dict[str, Any]:
    run._refresh()
    snapshot = run.budget_snapshot()
    remaining = {axis: snapshot[axis]["limit"] - snapshot[axis]["used"] for axis in AXES}
    base: dict[str, Any] = {
        "schema": K.PREFLIGHT_SCHEMA, "starts_job": False, "capability": jobs.capability(), "structure": structure,
        "repairable": None, "blockers": [], "defects": None, "expected_added_residues": None,
        "expected_added_heavy_atoms": None, "budget": {axis: dict(snapshot[axis]) for axis in AXES},
        "remaining": remaining,
        "shortfall": {"expensive_calls": max(0, UNITS_PER_JOB - remaining["expensive_calls"])},
        "admission": None, "statements": []}
    try:
        admitted, _timeout = jobs.admission(run, {"structure": structure, "repair_policy": K.REPAIR_POLICY}, None)
    except ToolFailure as exc:
        return {**base, "admission": _admission(exc)}
    analysed = None
    try:
        analysed = jobs.analysis_of(run, structure)
    except ToolFailure:   # the installed template is unreadable: no defect numbers (the selection below refuses)
        pass
    if analysed is not None:
        analysis = analysed[1]
        base.update(repairable=analysis["repairable"], blockers=analysis["blockers"], defects=analysis["defects"],
                    expected_added_residues=analysis["expected_added_residues"],
                    expected_added_heavy_atoms=analysis["expected_added_heavy_atoms"],
                    statements=analysis["statements"])
    try:   # 412 unavailability first, then the analysis refusal and the staged size, as POST /jobs
        jobs.selection(run, admitted, analysed)
    except ToolFailure as exc:
        return {**base, "admission": _admission(exc)}
    return {**base, "admission": _admission(None)}
