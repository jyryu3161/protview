"""M24 tool ``build_jev_projection``: validated pre-check + ``jev_projection@1`` result (spec .dryforge/spec.md 3).

The registry pre-check hook runs the spec 3 admission checks on every call path, before the generic argument check and
before the implementation, in this order (first failure only; every one ``input_invalid`` with ``detail.reason_code``):

1. ``unknown_field``: any argument outside ``source`` / ``candidates`` / ``filter``.
2. ``source_invalid``: not a handle of this run, another kind, not published, or the stored object does not validate.
   M17 sets go through ``ligand_bundle.validated_candidate_set`` over a store-backed run view (completed job
   publication + stored-object check, the M20 pocket-set precedent); M20 sets are store objects of this run checked
   with ``mutation_candidates.validated_set`` (the M21 / M23 precedent).
3. ``selection_invalid`` / 4. ``candidate_unknown``: ``jev_projection.normalize_selection``.
5. ``filter_invalid``: a ligand filter that ``ligand_filters.normalize_filter_spec`` refuses, or any non-null filter on
   a mutation set (null is the absent filter for both kinds).
6. ``candidate_filtered_out``: a chosen candidate whose stored values fail an active filter (``passes_all`` false);
   with no active filter every candidate is kept (the M17 ``passes_only`` / M22 eligibility rule).
7. ``structure_unavailable`` (mutation): the set's structure is not a ``prepared_structure@1`` of this run, cannot be
   parsed, or a position's 7 fields do not resolve to exactly one protein residue of it.
8. ``wire_field_invalid``: the allow-list rules of ``jev_projection.check_wire``.

The hook returns the normalized args (the call key: candidates in the source set's stored order whatever the request
order, the normalized filter or null) and no bound. The implementation repeats the same reads on this run's stored
objects only (candidate set, its inspection, the prepared structure bytes; no network, reference folder or
credential), builds ``jev_projection@1`` with the pure T2 functions and stores it. A body over 64 KiB is
``resource_exceeded`` (``payload_too_large``, nothing truncated) and content that fails ``validated_projection`` after
a store round trip is ``input_invalid`` (``projection_invalid``); in both cases nothing is stored.
"""
from __future__ import annotations

import json
from typing import Any

from .. import jev_projection as P
from .. import ligand_bundle, ligand_filters
from .. import mutation_candidates as mc
from ..core.errors import FailureClass, ToolFailure
from ..core.handles import Handle, canonical_json
from ..jev_constants import (
    KINDS,
    PROJECTION_INVALID,
    PROJECTION_KIND,
    PROJECTION_SCHEMA,
    SOURCE_SCHEMAS,
    SOURCE_STORE_KINDS,
    STRUCTURE_KIND,
    TOOL,
)
from .registry import ToolContext, ToolRegistry
from .structural import _parse

ARG_KEYS = ("source", "candidates", "filter")
STRUCTURE_TYPE = (STRUCTURE_KIND, f"{STRUCTURE_KIND}@1")


def _invalid(reason_code: str, message: str, **detail: Any) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail={"reason_code": reason_code, **detail})


def _refused(exc: P.JevProjectionError) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, exc.message, detail=exc.detail)


def _view(store: Any) -> Any:
    """A run view over the store for the published-evidence reads (``events`` and ``run_id`` come with the store)."""
    return type("RunView", (), {"store": store, "events": store.events, "run_id": store.run_id})()


def _source(store: Any, handle: Any) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """Check 2: ``(kind, validated set content, M17 inspection or None)``."""
    if type(handle) is not str:
        raise _invalid("source_invalid", "source must be a candidate set handle of this run")
    try:
        meta = store.meta(handle)
    except (KeyError, ValueError, TypeError):
        raise _invalid("source_invalid", "unknown handle (not an object of this run)") from None
    kind = next((name for name in KINDS
                 if (meta["kind"], meta["schema"]) == (SOURCE_STORE_KINDS[name], SOURCE_SCHEMAS[name])), None)
    if kind is None:
        raise _invalid("source_invalid", "source must be a ligand_candidate_set@1 or mutation_candidate_set@1")
    try:
        if kind == "ligand":
            content, inspection = ligand_bundle.validated_candidate_set(_view(store), handle)
            return kind, content, inspection
        return kind, mc.validated_set(store.load(handle)), None
    except (ValueError, TypeError, KeyError) as exc:   # LigandEvidenceError / MutationSetInvalid are ValueErrors
        raise _invalid("source_invalid", "the source is not a published, valid candidate set of this run") from exc


def _filter(kind: str, raw: Any, rows: list[dict[str, Any]], positions: list[int]) -> dict[str, Any] | None:
    """Checks 5 and 6: the normalized filter (ligand) or None."""
    if raw is None:
        return None
    if kind == "mutation":
        raise _invalid("filter_invalid", "a filter applies to ligand candidate sets only")
    try:
        spec = ligand_filters.normalize_filter_spec(raw)
    except ToolFailure as exc:
        raise _invalid("filter_invalid", f"filter is not a valid M17 filter spec: {exc.message}") from exc
    failing = [rows[position]["id"] for position in positions
               if ligand_filters.evaluate_row(rows[position], spec)["passes_all"] is False]
    if failing:
        raise _invalid("candidate_filtered_out", "chosen candidates do not pass the filter", candidates=failing)
    return spec


def _structure(store: Any, content: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    """Check 7 (first half): ``({handle, model_number}, parsed prepared structure)``."""
    handle = content["structure"]["handle"]
    try:
        meta = store.meta(handle)
    except (KeyError, ValueError, TypeError):
        raise _invalid("structure_unavailable", "the set's structure is not an object of this run") from None
    if (meta["kind"], meta["schema"]) != STRUCTURE_TYPE:
        raise _invalid("structure_unavailable", "the set's structure is not a prepared_structure@1 of this run")
    try:
        parsed = _parse(ToolContext(store=store, call_id="metadata"), handle)
    except ToolFailure as exc:
        raise _invalid("structure_unavailable", "the set's prepared structure cannot be read") from exc
    return {"handle": handle, "model_number": content["structure"]["model_number"]}, parsed


def _admit(store: Any, args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Checks 1--8 in order: ``(normalized args, built parts)``."""
    unknown = sorted(set(args) - set(ARG_KEYS))
    if unknown:
        raise _invalid("unknown_field", f"unknown parameters: {unknown}")
    handle = args.get("source")
    kind, content, inspection = _source(store, handle)
    rows = content["candidates"]
    try:
        positions = P.normalize_selection(kind, content, args.get("candidates"))
    except P.JevProjectionError as exc:
        raise _refused(exc) from exc
    spec = _filter(kind, args.get("filter"), rows, positions)
    normalized = [rows[position]["id" if kind == "ligand" else "index"] for position in positions]
    structure = None
    try:
        if kind == "ligand":
            wire, selection = P.build_ligand_wire(content, normalized, inspection=inspection)
        else:
            structure, parsed = _structure(store, content)
            wire, selection = P.build_mutation_wire(content, normalized, parsed)
    except P.JevProjectionError as exc:   # structure_unavailable before wire_field_invalid
        raise _refused(exc) from exc
    return ({"source": handle, "candidates": normalized, "filter": spec},
            {"kind": kind, "wire": wire, "selection": selection, "structure": structure})


def precheck(store: Any, args: dict[str, Any], bound: Any = None) -> tuple[dict[str, Any], None]:
    """Registry pre-check hook: ``(normalized args, None)`` or ``ToolFailure``; never runs the implementation."""
    return _admit(store, args)[0], None


def register(reg: ToolRegistry) -> None:
    @reg.register(TOOL, precheck=precheck)
    def build_jev_projection(ctx, source: str, candidates: list[Any], filter: dict[str, Any] | None) -> Handle:
        normalized, parts = _admit(ctx.store, {"source": source, "candidates": candidates, "filter": filter})
        try:
            content = P.build_projection_content(parts["kind"], source, parts["wire"], parts["selection"],
                                                 structure=parts["structure"], filter_spec=normalized["filter"])
            P.validated_projection(json.loads(canonical_json(content)))   # the stored form validates, or no store
        except P.PayloadTooLarge as exc:
            raise ToolFailure(FailureClass.resource_exceeded, exc.message, detail=exc.detail) from exc
        except P.ProjectionInvalid as exc:
            raise ToolFailure(FailureClass.input_invalid, f"the built projection does not validate: {exc.message}",
                              detail={"reason_code": PROJECTION_INVALID}) from exc
        except P.JevProjectionError as exc:
            raise _refused(exc) from exc
        summary = {"kind": content["kind"], "source": source, "selection_count": len(content["selection"]),
                   "body_bytes": content["body_bytes"], "body_sha256": content["body_sha256"]}
        return ctx.store.put(PROJECTION_KIND, PROJECTION_SCHEMA, content, produced_by=ctx.call_id, summary=summary,
                             null_result=False)
