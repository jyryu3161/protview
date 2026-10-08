"""M26 tool ``link_reaction_knowledge``: validated pre-check + ``reaction_knowledge@1`` result (spec 5).

Order on every call path (``Run.call``, argument repair, prerequisite retry), enforced by the registry pre-check hook
that ``Run._validated_bound`` runs before the generic argument check:
  0. pin the active reaction reference set and decode it (none -> ``not_installed``; hash or format mismatch ->
     ``snapshot_invalid``): ``precondition``, before any admission check and before any cache lookup;
  1-9. the closed admission checks of spec 5.2 in ``ADMISSION_REASON_CODES`` order, each check over every chain
     before the next one (``input_invalid`` with ``detail.reason_code``); the implementation is never called;
  then the cache key adds the pinned set hash (``ReactionBound.key_fields``) and the implementation builds the result
  from that same pinned set (``ToolContext.bound``), never re-reading ``active.json``.

The tool reads only the pinned set, this run's structure bytes and the chosen ``residue_numbering_map@1`` object: no
network, no M15 reference folder, no ``../kbase_kinase``. The built content is re-checked by
``reaction_knowledge.validated_result`` before it is stored (failure: ``input_invalid`` ``result_invalid``, nothing
stored); above the result size or link cap it is ``resource_exceeded`` (``result_too_large`` / ``too_many_links``),
nothing stored and nothing truncated. Admission does not judge whether an accession is in the snapshot or agrees with
the numbering map: those are result states (spec 5.4).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .. import reaction_knowledge as rk
from .. import reaction_knowledge_constants as K
from .. import reaction_snapshots as rs
from ..core.errors import FailureClass, ToolFailure
from ..core.handles import Handle, canonical_json
from .registry import ToolContext, ToolRegistry
from .structural import _parse

TOOL = K.TOOL
MAP_TYPE = (rk.MAP_KIND, "residue_numbering_map@1")
_ARG_KEYS = frozenset({"structure", "pdb_id", "chains", "numbering_map"})
_CHAIN_KEYS = frozenset({"chain_auth", "uniprot_accession"})
_PDB_ID = re.compile(K.PDB_ID_PATTERN + r"\Z")


@dataclass(frozen=True)
class ReactionBound:
    """What the pre-check fixed for one call: the pinned set, the structure's chain residues and the map content."""

    pinned: rs.PinnedReactionSet
    index: rk.ReactionIndex
    structure_kind: str
    model_number: int
    chain_residues: dict[str, list[dict[str, Any]]]
    numbering_map: dict[str, Any] | None
    normalized_args: dict[str, Any]

    @property
    def key_fields(self) -> dict[str, Any]:
        return {"_reaction_set_hash": self.pinned.set_hash}


def _invalid(message: str, reason_code: str, chain_auth: str | None = None) -> ToolFailure:
    detail: dict[str, Any] = {"reason_code": reason_code}
    if chain_auth is not None:
        detail["chain_auth"] = chain_auth
    return ToolFailure(FailureClass.input_invalid, message, detail=detail)


def _unavailable(exc: rs.SnapshotUnavailable) -> ToolFailure:
    return ToolFailure(FailureClass.precondition, exc.reason, detail={"reason_code": exc.reason_code})


def _same_call(args: dict[str, Any], bound: Any) -> bool:
    if not isinstance(bound, ReactionBound):
        return False
    try:
        return canonical_json(args) == canonical_json(bound.normalized_args)
    except (TypeError, ValueError):
        return False


def _structure(store: Any, handle: Any) -> tuple[str, int, dict[str, list[dict[str, Any]]]]:
    """2. a structure / prepared_structure of this run, parsed (selected model) into its chain residues."""
    if type(handle) is not str:
        raise _invalid("structure must be a structure or prepared_structure handle of this run", "structure_invalid")
    try:
        kind = store.meta(handle)["kind"]
    except (KeyError, ValueError, TypeError):
        raise _invalid("unknown handle (not an object of this run)", "structure_invalid") from None
    if kind not in rk.STRUCTURE_KINDS:
        raise _invalid(f"structure must be one of {list(rk.STRUCTURE_KINDS)}, got '{kind}'", "structure_invalid")
    try:
        st = _parse(ToolContext(store=store, call_id="reaction_knowledge_precheck"), handle)
    except ToolFailure as exc:
        raise _invalid(f"the structure cannot be read: {exc.message}", "structure_invalid") from exc
    try:
        residues = rk.chain_polymer_residues(st)
    except ValueError as exc:
        raise _invalid("structure entity setup is inconsistent", "structure_invalid") from exc
    return kind, st[0].num, residues


def _chains(value: Any) -> list[dict[str, Any]]:
    """4. ``[{chain_auth, uniprot_accession | null}]``, non-empty, unique ``chain_auth``, no other fields."""
    if type(value) is not list or not value:
        raise _invalid("chains must be a non-empty list", "chains_invalid")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if type(item) is not dict or set(item) - _CHAIN_KEYS:
            raise _invalid("each chain is {chain_auth, uniprot_accession | null} and nothing else", "chains_invalid")
        chain_auth, accession = item.get("chain_auth"), item.get("uniprot_accession")
        if type(chain_auth) is not str or not chain_auth:
            raise _invalid("chain_auth must be a non-empty string", "chains_invalid")
        if accession is not None and type(accession) is not str:
            raise _invalid("uniprot_accession must be a string or null", "chains_invalid", chain_auth)
        if chain_auth in seen:
            raise _invalid("duplicate chain_auth", "chains_invalid", chain_auth)
        seen.add(chain_auth)
        out.append({"chain_auth": chain_auth, "uniprot_accession": accession})
    return out


def _residue_ok(value: Any) -> bool:
    return type(value) is dict and all(key in value for key in K.RESIDUE_FIELDS) and type(value["chain_auth"]) is str


def _map_shape_ok(content: Any) -> bool:
    """The fields the linking rules read (spec 5.4) exist with their types; anything else is the map's own record."""
    if (type(content) is not dict or content.get("schema") != MAP_TYPE[1] or type(content.get("structure")) is not dict
            or type(content["structure"].get("handle")) is not str
            or not (content.get("pdb_id") is None or type(content.get("pdb_id")) is str)
            or type(content.get("chains")) is not list or type(content.get("rows")) is not list):
        return False
    for chain in content["chains"]:
        if (type(chain) is not dict or type(chain.get("chain_auth")) is not str
                or "requested_uniprot_accession" not in chain
                or not (chain["requested_uniprot_accession"] is None
                        or type(chain["requested_uniprot_accession"]) is str)):
            return False
    for row in content["rows"]:
        if (type(row) is not dict or not _residue_ok(row.get("residue")) or type(row.get("status")) is not str
                or not all(key in row for key in ("uniprot_accession", "uniprot_position", "uniprot_residue",
                                                  "residue_match"))
                or not (row["uniprot_position"] is None or type(row["uniprot_position"]) is int)):
            return False
    return True


def _numbering_map(store: Any, handle: Any) -> dict[str, Any] | None:
    """7. null or a ``residue_numbering_map@1`` of this run."""
    if handle is None:
        return None
    if type(handle) is not str:
        raise _invalid("numbering_map must be a residue_numbering_map handle of this run or null",
                       "numbering_map_invalid")
    try:
        meta = store.meta(handle)
    except (KeyError, ValueError, TypeError):
        raise _invalid("unknown handle (not an object of this run)", "numbering_map_invalid") from None
    if (meta["kind"], meta["schema"]) != MAP_TYPE:
        raise _invalid(f"numbering_map must be a residue_numbering_map, got '{meta['kind']}'", "numbering_map_invalid")
    content = store.load(handle)
    if not _map_shape_ok(content):
        raise _invalid("the numbering map object does not have the residue_numbering_map@1 fields",
                       "numbering_map_invalid")
    return content


def precheck(store: Any, args: dict[str, Any], bound: ReactionBound | None = None,
             ) -> tuple[dict[str, Any], ReactionBound]:
    """Registry pre-check hook: ``(normalized args, bound)`` or ``ToolFailure``; never runs the implementation."""
    if isinstance(bound, ReactionBound):
        pinned, index = bound.pinned, bound.index        # re-validation inside one call keeps its pinned set
    else:
        try:
            pinned, index = rk.pin_and_index()            # 0. before any admission check and any cache lookup
        except rs.SnapshotUnavailable as exc:
            raise _unavailable(exc) from exc
    if _same_call(args, bound):
        return dict(bound.normalized_args), bound          # the same normalized call: objects are immutable
    unknown = set(args) - _ARG_KEYS                                                   # 1
    if unknown:
        raise _invalid(f"unknown parameters: {sorted(unknown)}", "unknown_field")
    structure = args.get("structure")
    kind, model_number, residues = _structure(store, structure)                       # 2
    pdb_id = args.get("pdb_id")                                                       # 3
    if pdb_id is not None and (type(pdb_id) is not str or not _PDB_ID.fullmatch(pdb_id)):
        raise _invalid("pdb_id must be a four-character PDB ID ([0-9][A-Za-z0-9]{3}) or null", "pdb_id_invalid")
    pdb_id = pdb_id.upper() if pdb_id is not None else None
    chains = _chains(args.get("chains"))                                              # 4
    for item in chains:                                                               # 5
        if not residues.get(item["chain_auth"]):
            raise _invalid("the chain has no polymer residues in the selected model (or does not exist)",
                           "chain_not_found", item["chain_auth"])
    for item in chains:                                                               # 6
        if item["uniprot_accession"] is not None and not K.is_accession(item["uniprot_accession"]):
            raise _invalid("uniprot_accession must be a UniProt accession or null", "accession_invalid",
                           item["chain_auth"])
    map_handle = args.get("numbering_map")
    map_content = _numbering_map(store, map_handle)                                  # 7
    if map_content is not None and map_content["structure"]["handle"] != structure:  # 8
        raise _invalid("the numbering map was made for another structure", "structure_mismatch")
    if map_content is not None and pdb_id is not None and map_content["pdb_id"] not in (None, pdb_id):  # 9
        raise _invalid("the numbering map names another PDB ID", "map_pdb_mismatch")
    normalized = {"structure": structure, "pdb_id": pdb_id, "chains": chains, "numbering_map": map_handle}
    return normalized, ReactionBound(pinned, index, kind, model_number, residues, map_content, normalized)


def register(reg: ToolRegistry) -> None:
    @reg.register(TOOL, precheck=precheck)
    def link_reaction_knowledge(ctx: ToolContext, structure: str, chains: list[dict[str, Any]],
                                pdb_id: str | None = None, numbering_map: str | None = None) -> Handle:
        bound = ctx.bound
        args = {"structure": structure, "pdb_id": pdb_id, "chains": chains, "numbering_map": numbering_map}
        if not isinstance(bound, ReactionBound) or bound.normalized_args != args:
            raise ToolFailure(FailureClass.fatal, "reaction knowledge implementation called without its pre-check")
        try:
            content = rk.build_reaction_knowledge(
                pinned=bound.pinned, index=bound.index, structure_handle=structure,
                structure_kind=bound.structure_kind, model_number=bound.model_number, pdb_id=pdb_id, chains=chains,
                chain_residues=bound.chain_residues, numbering_map=bound.numbering_map,
                numbering_map_handle=numbering_map)
        except rk.TooManyLinks as exc:
            raise ToolFailure(FailureClass.resource_exceeded, str(exc),
                              detail={"reason_code": K.TOO_MANY_LINKS_REASON, "limit": exc.limit}) from exc
        except rk.ResultTooLarge as exc:
            raise ToolFailure(FailureClass.resource_exceeded, str(exc),
                              detail={"reason_code": K.RESULT_TOO_LARGE_REASON, "limit": exc.limit,
                                      "actual": exc.actual}) from exc
        try:   # a build/validate mismatch is never stored
            rk.validated_result(content)
        except rk.ResultInvalid as exc:
            raise ToolFailure(FailureClass.input_invalid, f"the built result does not validate: {exc}",
                              detail={"reason_code": K.RESULT_INVALID_REASON}) from exc
        summary = {"structure": structure, "pdb_id": pdb_id, "chains": [c["chain_auth"] for c in content["chains"]],
                   "set_hash": bound.pinned.set_hash, "covered_chains": content["counts"]["covered_chains"]}
        return ctx.store.put(K.KIND, K.SCHEMA, content, produced_by=ctx.call_id, summary=summary,
                             null_result=content["null_result"])
