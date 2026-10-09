"""M20 tool ``generate_mutation_candidates``: validated pre-check + ``mutation_candidate_set@1`` result.

The registry pre-check hook runs the spec 2 admission checks on every call path before the generic argument check and
before the implementation, in this order: ``unknown_field``; ``structure_invalid`` (a prepared_structure of this run);
``no_position_source`` .. ``ligand_invalid`` (``mutation_candidates.normalize_request``); the handle kind/run checks of
``pocket_set`` (published fpocket result via ``pocket_bundle.validated_pocket_set`` over a store-backed run view, not
a null result), ``numbering_map`` and ``annotation``; ``catalytic_annotation`` (M26 spec 8.1: a
``reaction_knowledge@1`` of this run that passes ``reaction_knowledge.validated_result``); then ``structure_mismatch``
(pocket set, map, annotation, catalytic annotation); ``pocket_rank_invalid`` / ``pocket_residue_mismatch``;
``annotation_map_mismatch``. Every failure is ``input_invalid`` with ``detail.reason_code``. The hook returns the
normalized args (the call key, ``catalytic_annotation`` always included) and no bound.

The implementation reads only this run's stored objects (structure bytes, pocket set, numbering map, annotation,
reaction knowledge result); every set it builds is v2. The reaction result is validated here, in the tool layer, and
``catalytic_input`` hands ``mutation_candidates`` only the plain per-chain values the protection needs. More than
``MAX_POSITIONS`` positions (``too_many_positions``) or a catalytic conflict / unmatched list above its limit
(``catalytic_list_too_long``) is ``resource_exceeded`` and nothing is stored.
"""
from __future__ import annotations

from typing import Any

from .. import mutation_candidates as mc
from .. import reaction_knowledge as rk
from .. import reaction_knowledge_constants as RK
from ..core.errors import FailureClass, ToolFailure
from ..core.handles import Handle
from ..mutation_constants import (
    CATALYTIC_COVERED,
    CATALYTIC_ENTRY_KEYS,
    CATALYTIC_LIST_TOO_LONG,
    CATALYTIC_LISTED_KEYS,
    KIND,
    SCHEMA,
    STRUCTURE_KIND,
    TOO_MANY_POSITIONS,
    TOOL,
)
from ..pocket_bundle import PocketEvidenceError, validated_pocket_set
from .registry import ToolContext, ToolRegistry
from .structural import _parse, structure_residues

STRUCTURE_TYPE = (STRUCTURE_KIND, f"{STRUCTURE_KIND}@1")
MAP_TYPE = ("residue_numbering_map", "residue_numbering_map@1")
ANNOTATION_TYPE = ("reference_site_annotation", "reference_site_annotation@1")
CATALYTIC_TYPE = (RK.KIND, RK.SCHEMA)
RESOURCE_REASONS = (TOO_MANY_POSITIONS, CATALYTIC_LIST_TOO_LONG)


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


def _catalytic(store: Any, handle: Any) -> dict[str, Any]:
    """A ``reaction_knowledge@1`` object of this run whose content passes ``validated_result``."""
    content = _same_run(store, handle, CATALYTIC_TYPE, "catalytic_annotation_invalid")
    try:
        return rk.validated_result(content)
    except rk.ResultInvalid:
        raise _invalid("catalytic_annotation does not validate as reaction_knowledge@1",
                       "catalytic_annotation_invalid") from None


def catalytic_input(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The plain per-chain values of a VALIDATED ``reaction_knowledge@1`` result that the M20 protection needs.

    ``{chain_auth: {"coverage", "counts", "rows"}}``: ``coverage`` is the M-CSA section's ``coverage``, or
    ``not_checked`` when the section was not checked (no PDB ID); ``counts`` (``matched`` / ``unmatched`` /
    ``conflict``) and ``rows`` (``mcsa_id``, ``residue_index``, ``is_reference``, ``status``, ``reason``, ``residue``,
    ``listed`` reduced to ``chain_name`` / ``resid`` / ``auth_resid`` / ``code``) only for a ``covered`` chain. UniProt
    sites and reactions are never used (M26 spec 1, 8.2).
    """
    chains: dict[str, dict[str, Any]] = {}
    for chain in result["chains"]:
        mcsa = chain["mcsa"]
        if mcsa["status"] == RK.NOT_CHECKED:
            chains[chain["chain_auth"]] = {"coverage": RK.NOT_CHECKED, "counts": None, "rows": None}
        elif mcsa["coverage"] != CATALYTIC_COVERED:
            chains[chain["chain_auth"]] = {"coverage": mcsa["coverage"], "counts": None, "rows": None}
        else:
            chains[chain["chain_auth"]] = {
                "coverage": CATALYTIC_COVERED, "counts": dict(mcsa["counts"]),
                "rows": [{**{key: row[key] for key in CATALYTIC_ENTRY_KEYS}, "status": row["status"],
                          "reason": row["reason"], "residue": row["residue"],
                          "listed": {key: row["listed"][key] for key in CATALYTIC_LISTED_KEYS}}
                         for row in mcsa["rows"]]}
    return chains


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
    catalytic_content = (_catalytic(store, params["catalytic_annotation"])
                         if params["catalytic_annotation"] is not None else None)
    if pocket_content is not None and pocket_content["source_handle"] != structure:
        raise _invalid("the pocket set was detected on another structure", "structure_mismatch")
    if map_content is not None and map_content["structure"]["handle"] != structure:
        raise _invalid("the numbering map was made for another structure", "structure_mismatch")
    if annotation_content is not None and annotation_content["structure"]["handle"] != structure:
        raise _invalid("the annotation was made for another structure", "structure_mismatch")
    if catalytic_content is not None and catalytic_content["structure"]["handle"] != structure:
        raise _invalid("the catalytic annotation was made for another structure", "structure_mismatch")
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
                                     numbering_map: str | None, annotation: str | None,
                                     catalytic_annotation: str | None) -> Handle:
        params = {"sources": sources, "ligand": ligand, "allowed_residues": allowed_residues,
                  "protected_residues": protected_residues, "released_residues": released_residues,
                  "metal_contact_A": metal_contact_A, "numbering_map": numbering_map, "annotation": annotation,
                  "catalytic_annotation": catalytic_annotation}
        pocket = sources["pocket"]
        try:
            content = mc.build_candidate_set(
                structure, _parse(ctx, structure), params,
                pocket_content=ctx.store.load(pocket["pocket_set"]) if pocket is not None else None,
                numbering_content=ctx.store.load(numbering_map) if numbering_map is not None else None,
                annotation_content=ctx.store.load(annotation) if annotation is not None else None,
                catalytic_content=(catalytic_input(_catalytic(ctx.store, catalytic_annotation))
                                   if catalytic_annotation is not None else None))
        except mc.MutationInvalid as exc:
            cls = (FailureClass.resource_exceeded if exc.reason_code in RESOURCE_REASONS
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
