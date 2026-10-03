"""M20 tool ``generate_mutation_candidates``: validated pre-check + ``mutation_candidate_set@1`` result.

The registry pre-check hook runs the spec 2 admission checks on every call path before the generic argument check and
before the implementation, in this order: ``unknown_field``; ``structure_invalid`` (a prepared_structure of this run);
``no_position_source`` .. ``ligand_invalid`` (``mutation_candidates.normalize_request``); the handle kind/run checks of
``pocket_set`` (published fpocket result via ``pocket_bundle.validated_pocket_set`` over a store-backed run view, not
a null result), ``numbering_map`` and ``annotation``; then ``structure_mismatch`` (pocket set, map, annotation);
``pocket_rank_invalid`` / ``pocket_residue_mismatch``; ``annotation_map_mismatch``. Every failure is
``input_invalid`` with ``detail.reason_code``. The hook returns the normalized args (the call key) and no bound.

The implementation reads only this run's stored objects (structure bytes, pocket set, numbering map, annotation);
more than ``MAX_POSITIONS`` positions is ``resource_exceeded`` (``too_many_positions``) and nothing is stored.
"""
from __future__ import annotations

from typing import Any

from .. import mutation_candidates as mc
from ..core.errors import FailureClass, ToolFailure
from ..core.handles import Handle
from ..mutation_constants import KIND, SCHEMA, STRUCTURE_KIND, TOO_MANY_POSITIONS, TOOL
from ..pocket_bundle import PocketEvidenceError, validated_pocket_set
from .registry import ToolContext, ToolRegistry
from .structural import _parse, structure_residues

STRUCTURE_TYPE = (STRUCTURE_KIND, f"{STRUCTURE_KIND}@1")
MAP_TYPE = ("residue_numbering_map", "residue_numbering_map@1")
ANNOTATION_TYPE = ("reference_site_annotation", "reference_site_annotation@1")


def _invalid(message: str, reason_code: str) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail={"reason_code": reason_code})


def _same_run(store: Any, handle: Any, expected: tuple[str, str], reason_code: str) -> dict[str, Any]:
    if type(handle) is not str:
        raise _invalid(f"expected a {expected[0]} handle of this run", reason_code)
    try:
        meta = store.meta(handle)
    except (KeyError, ValueError, TypeError):
        raise _invalid("unknown handle (not an object of this run)", reason_code) from None
    if (meta["kind"], meta["schema"]) != expected:
        raise _invalid(f"expected a {expected[0]} handle, got '{meta['kind']}'", reason_code)
    return store.load(handle)


def _pocket_set(store: Any, handle: Any) -> dict[str, Any]:
    view = type("RunView", (), {"store": store, "events": store.events, "run_id": store.run_id})()
    try:
        content, _manifest, _producer = validated_pocket_set(view, handle)
    except PocketEvidenceError:
        raise _invalid("pocket_set must be a published pocket_set@1 of this run", "pocket_set_invalid") from None
    if content["null_result"] is not False:
        raise _invalid("the pocket set has no pockets (null result)", "pocket_set_invalid")
    return content


def _admit(store: Any, args: dict[str, Any]) -> dict[str, Any]:
    mc.check_fields(args)
    structure = args.get("structure")
    _same_run(store, structure, STRUCTURE_TYPE, "structure_invalid")
    listing = structure_residues(store, structure)
    params = mc.normalize_request(args, listing["residues"], listing["ligands"])
    if params["ligand"] is not None:
        mc.check_ligand_heavy_atoms(_parse(ToolContext(store=store, call_id="metadata"), structure), params["ligand"])
    pocket = params["sources"]["pocket"]
    pocket_content = _pocket_set(store, pocket["pocket_set"]) if pocket is not None else None
    map_content = (_same_run(store, params["numbering_map"], MAP_TYPE, "numbering_map_invalid")
                   if params["numbering_map"] is not None else None)
    annotation_content = (_same_run(store, params["annotation"], ANNOTATION_TYPE, "annotation_invalid")
                          if params["annotation"] is not None else None)
    if pocket_content is not None and pocket_content["source_handle"] != structure:
        raise _invalid("the pocket set was detected on another structure", "structure_mismatch")
    if map_content is not None and map_content["structure"]["handle"] != structure:
        raise _invalid("the numbering map was made for another structure", "structure_mismatch")
    if annotation_content is not None and annotation_content["structure"]["handle"] != structure:
        raise _invalid("the annotation was made for another structure", "structure_mismatch")
    if pocket_content is not None:
        mc.pocket_lining(pocket_content, pocket["ranks"], listing["residues"])
    if (map_content is not None and annotation_content is not None
            and annotation_content["numbering_map"] != params["numbering_map"]):
        raise _invalid("the annotation was made from another numbering map", "annotation_map_mismatch")
    return params


def precheck(store: Any, args: dict[str, Any], bound: Any = None) -> tuple[dict[str, Any], None]:
    """Registry pre-check hook: ``(normalized args, None)`` or ``ToolFailure``; never runs the implementation."""
    try:
        return _admit(store, args), None
    except mc.MutationInvalid as exc:
        raise ToolFailure(FailureClass.input_invalid, exc.message, detail=exc.detail) from exc


def register(reg: ToolRegistry) -> None:
    @reg.register(TOOL, precheck=precheck)
    def generate_mutation_candidates(ctx, structure: str, sources: dict[str, Any], ligand: dict[str, Any] | None,
                                     allowed_residues: str, protected_residues: list[dict[str, Any]],
                                     released_residues: list[dict[str, Any]], metal_contact_A: float,
                                     numbering_map: str | None, annotation: str | None) -> Handle:
        params = {"sources": sources, "ligand": ligand, "allowed_residues": allowed_residues,
                  "protected_residues": protected_residues, "released_residues": released_residues,
                  "metal_contact_A": metal_contact_A, "numbering_map": numbering_map, "annotation": annotation}
        pocket = sources["pocket"]
        try:
            content = mc.build_candidate_set(
                structure, _parse(ctx, structure), params,
                pocket_content=ctx.store.load(pocket["pocket_set"]) if pocket is not None else None,
                numbering_content=ctx.store.load(numbering_map) if numbering_map is not None else None,
                annotation_content=ctx.store.load(annotation) if annotation is not None else None)
        except mc.MutationInvalid as exc:
            cls = (FailureClass.resource_exceeded if exc.reason_code == TOO_MANY_POSITIONS
                   else FailureClass.input_invalid)
            raise ToolFailure(cls, exc.message, detail=exc.detail) from exc
        try:   # a build/validate mismatch is never stored
            mc.validated_set(content)
        except mc.MutationSetInvalid as exc:
            raise ToolFailure(FailureClass.input_invalid, f"the built candidate set does not validate: {exc}",
                              detail={"reason_code": "candidate_set_invalid"}) from exc
        summary = {"structure": structure, **content["counts"], "null_result": content["null_result"]}
        return ctx.store.put(KIND, SCHEMA, content, produced_by=ctx.call_id, summary=summary,
                             null_result=content["null_result"])
