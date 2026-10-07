"""M25 tool ``build_jev_loop_projection``: the loop admission pre-check + ``jev_loop_projection@1`` (spec
.dryforge/spec.md 4.1-4.5).

The registry pre-check hook runs the spec 4.1 admission on every call path, before the generic argument check and the
implementation, in this order (first failure only, ``detail.reason_code`` = the name; input and existence problems
are ``input_invalid`` (422 on ``/commands``), loop-state refusals ``precondition`` (412), the size ``resource_exceeded``
(429)):

1. ``unknown_field``: any argument outside ``loop_id`` / ``iteration``.
2. ``loop_not_found``: no ``jev_loop_created`` with this ``loop_id`` in this run (a dry-run run never has one).
3. ``loop_ended`` / ``iteration_mismatch`` / ``selection_done`` / ``phase_invalid`` / ``cap_reached`` /
   ``too_few_candidates``: ``jev_loops.selection_refusal`` on the ``jev_loop@1`` record that ``jev_loop_store.read_loop``
   derives and checks (the loop record judgment is not written again here).
4. ``source_invalid``: the loop's candidate set no longer validates (M17 ``validated_candidate_set``, M20
   ``validated_set``). The record is derived from that set (notation, stored results), so a set that fails its check
   is answered here even when the record could not be derived for that reason (the steps above need the record).
5. ``structure_unavailable`` (protein): the M24 tool's own structure check, then the M24 residue resolution.
6. ``wire_field_invalid``: the loop and M24 allow-list rules (``jev_loop_projection.check_loop_wire``).
7. ``payload_too_large``: a body over 64 KiB, never truncated.

The hook returns the normalized arguments ``{loop_id, iteration}`` and a bound that pins the record inputs the
projection reads (``jev_loop_store.projection_inputs``: pool order, goal, loop seed, send ordinal, every candidate's
state and stored score); the call key adds their SHA-256 (``key_fields``), so the same inputs give the same key and,
with no time or call id in the content, the same handle. A re-validation of the same call keeps the pinned bound
(the M15 rule). The implementation repeats the stored-object reads (candidate set, M17 inspection, prepared
structure bytes) for those pinned inputs, builds the projection with the pure T2 functions and stores it only when
its stored form passes ``validated_loop_projection`` (``projection_invalid`` otherwise). It reads this run's stored
objects and loop record only: no job, no budget, no network, no credential and no send.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from .. import jev_loop_constants as L
from .. import jev_loop_projection as LP
from .. import jev_loop_store, jev_loops
from .. import jev_projection as P
from ..core.errors import FailureClass, ToolFailure
from ..core.handles import Handle, canonical_json
from . import jev as m24_tool
from .registry import ToolRegistry

INPUTS_KEY = "_loop_inputs_sha256"
# The admission reads no budget-derived field of the record (spec 4.1 has no budget refusal; the tool spends none),
# so the derivation gets neutral remaining amounts instead of the run budget the store does not carry.
READ_BUDGET = dict.fromkeys(jev_loops.BUDGET_KEYS, 0)
FAILURE_CLASS = {
    "unknown_field": FailureClass.input_invalid, "loop_not_found": FailureClass.input_invalid,
    "loop_ended": FailureClass.precondition, "iteration_mismatch": FailureClass.precondition,
    "selection_done": FailureClass.precondition, "phase_invalid": FailureClass.precondition,
    "cap_reached": FailureClass.precondition, "too_few_candidates": FailureClass.precondition,
    "source_invalid": FailureClass.input_invalid, "structure_unavailable": FailureClass.input_invalid,
    "wire_field_invalid": FailureClass.input_invalid, "payload_too_large": FailureClass.resource_exceeded,
    L.PROJECTION_INVALID: FailureClass.input_invalid,
}
MESSAGES = {
    "loop_not_found": "this run has no JEV loop with this loop_id",
    "loop_ended": "the loop has ended",
    "iteration_mismatch": "iteration is not the loop's current iteration (counts.started + 1)",
    "selection_done": "this iteration already has its first completed, not-late JEV proposal",
    "phase_invalid": "the current iteration is not awaiting a selection",
    "cap_reached": "the loop has started its effective iteration cap",
    "too_few_candidates": "fewer than two candidates are not yet computed",
    "source_invalid": "the loop's candidate set is not a published, valid set of this run",
}


@dataclass(frozen=True)
class LoopProjectionBound:
    """The pinned loop inputs of one call (``key_fields`` enter the call key)."""

    normalized_args: dict[str, Any]
    key_fields: dict[str, str]
    branch: str
    source_handle: str
    inputs: dict[str, Any]


def _refused(reason: str, message: str | None = None, **detail: Any) -> ToolFailure:
    return ToolFailure(FAILURE_CLASS[reason], message or MESSAGES[reason], detail={"reason_code": reason, **detail})


def _view(store: Any) -> jev_loop_store.LoopReadView:
    """One event-log read over the run's store (the pre-check hook gets the store, not the run)."""
    return jev_loop_store.LoopReadView(SimpleNamespace(store=store, run_id=store.run_id, run_dir=store.run_dir,
                                                       events=store.events))


def _source(view: Any, branch: str, handle: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        return jev_loop_store.projection_source(view, branch, handle)
    except (KeyError, TypeError, ValueError) as exc:   # LigandEvidenceError / MutationSetInvalid are ValueErrors
        raise _refused("source_invalid") from exc


def _project(view: Any, store: Any, bound: LoopProjectionBound) -> dict[str, Any]:
    """Checks 4-7: the ``jev_loop_projection@1`` content of the pinned inputs, from this run's stored objects."""
    kind = L.KIND_FOR_BRANCH[bound.branch]
    source, inspection = _source(view, bound.branch, bound.source_handle)
    structure = parsed = None
    if kind == "mutation":
        structure, parsed = m24_tool._structure(store, source)   # structure_unavailable, the M24 reason
    inputs, iteration = bound.inputs, bound.normalized_args["iteration"]
    rows = [dict(row) for row in inputs["candidates"]]
    order = {"goal": inputs["goal"], "loop_seed": inputs["loop_seed"], "iteration": iteration,
             "send_ordinal": inputs["send_ordinal"]}
    try:
        if kind == "ligand":
            wire, selection = LP.build_loop_ligand_wire(source, rows, inspection=inspection, **order)
        else:
            wire, selection = LP.build_loop_mutation_wire(source, rows, parsed, **order)
        return LP.build_loop_projection_content(
            kind, bound.source_handle, wire, selection, loop_id=bound.normalized_args["loop_id"],
            loop_seed=inputs["loop_seed"], iteration=iteration, send_ordinal=inputs["send_ordinal"],
            structure=structure)
    except P.JevProjectionError as exc:   # structure_unavailable, wire_field_invalid, payload_too_large, ...
        reason = exc.reason_code if exc.reason_code in FAILURE_CLASS else L.PROJECTION_INVALID
        raise ToolFailure(FAILURE_CLASS[reason], exc.message, detail={**exc.detail, "reason_code": reason}) from exc


def _admit(store: Any, args: dict[str, Any]) -> tuple[dict[str, Any], LoopProjectionBound]:
    """Checks 1-7 in order: ``(normalized args, bound)``."""
    unknown = sorted(set(args) - set(L.TOOL_ARGUMENTS))
    if unknown:
        raise _refused("unknown_field", f"unknown parameters: {unknown}")
    loop_id, iteration = args.get("loop_id"), args.get("iteration")
    if not L.is_loop_id(loop_id):
        raise _refused("loop_not_found")
    view = _view(store)
    try:
        created = jev_loop_store.created_payload(view.read(), loop_id)
    except jev_loops.LoopNotFound:
        raise _refused("loop_not_found") from None
    branch, source_handle = created["branch"], created["pool"]["source"]["handle"]
    try:
        state = jev_loop_store.read_loop(view, loop_id, budget=READ_BUDGET)
    except jev_loops.LoopRecordInvalid:
        raise
    except (KeyError, TypeError, ValueError):
        _source(view, branch, source_handle)   # a set that no longer validates leaves no record: source_invalid
        raise
    refusal = jev_loops.selection_refusal(state, iteration)
    if refusal is not None:
        raise _refused(refusal)
    inputs = jev_loop_store.projection_inputs(state, iteration)
    normalized = {"loop_id": loop_id, "iteration": iteration}
    bound = LoopProjectionBound(normalized, {INPUTS_KEY: hashlib.sha256(canonical_json(inputs)).hexdigest()},
                                branch, source_handle, inputs)
    _project(view, store, bound)
    return normalized, bound


def precheck(store: Any, args: dict[str, Any], bound: Any = None) -> tuple[dict[str, Any], LoopProjectionBound]:
    """Registry pre-check hook: ``(normalized args, bound)`` or ``ToolFailure``; never runs the implementation. A
    re-validation of the same call (same normalized arguments) keeps its pinned bound."""
    if (isinstance(bound, LoopProjectionBound) and not set(args) - set(L.TOOL_ARGUMENTS)
            and canonical_json(bound.normalized_args) == canonical_json({name: args.get(name)
                                                                        for name in L.TOOL_ARGUMENTS})):
        return dict(bound.normalized_args), bound
    return _admit(store, args)


def register(reg: ToolRegistry) -> None:
    @reg.register(L.TOOL, precheck=precheck)
    def build_jev_loop_projection(ctx, loop_id: str, iteration: int) -> Handle:
        bound = ctx.bound
        if not isinstance(bound, LoopProjectionBound):
            bound = precheck(ctx.store, {"loop_id": loop_id, "iteration": iteration})[1]
        content = _project(_view(ctx.store), ctx.store, bound)
        try:
            LP.validated_loop_projection(json.loads(canonical_json(content)))   # the stored form, or no store
        except P.ProjectionInvalid as exc:
            raise _refused(L.PROJECTION_INVALID, f"the built projection does not validate: {exc.message}") from exc
        summary = {"kind": content["kind"], "loop_id": loop_id, "iteration": iteration,
                   "send_ordinal": content["loop"]["send_ordinal"], "selection_count": len(content["selection"]),
                   "body_bytes": content["body_bytes"], "body_sha256": content["body_sha256"]}
        return ctx.store.put(L.PROJECTION_KIND, L.PROJECTION_SCHEMA, content, produced_by=ctx.call_id,
                             summary=summary, null_result=False)
