"""M15 tool ``map_residue_numbering``: validated pre-check + ``residue_numbering_map@1`` result.

Order on every call path (``Run.call``, argument repair, prerequisite retry), enforced by the registry pre-check hook
that ``Run._validated_bound`` runs before the generic argument check:
  1. pin the active reference set (missing / invalid -> ``precondition`` failure, before any cache lookup);
  2. validate the whole input, reading the pinned snapshot and the structure (-> ``input_invalid``);
  3. the cache key includes the pinned set hash (``NumberingBound.key_fields``);
  4. the implementation runs with the same pinned set (``ToolContext.bound``), never re-reading ``active.json``.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .. import reference_snapshots as rs
from .. import residue_numbering as rn
from ..core.errors import FailureClass, ToolFailure
from ..core.handles import Handle, canonical_json
from .registry import ToolContext, ToolRegistry
from .structural import _parse, _res_ref

TOOL = "map_residue_numbering"
ALLOWED_KINDS = ("structure", "prepared_structure")
_PDB_ID = re.compile(r"[0-9][A-Za-z0-9]{3}\Z")
_ARG_KEYS = frozenset({"structure", "pdb_id", "chains"})
_CHAIN_KEYS = frozenset({"chain_auth", "uniprot_accession"})


@dataclass(frozen=True)
class NumberingBound:
    """What the pre-check fixed for one call: the pinned set and the per-chain plans."""

    pinned: rs.PinnedSet
    index: rn.ReferenceIndex
    structure: str
    structure_kind: str
    model_number: int
    pdb_id: str | None
    plans: tuple[rn.ChainPlan, ...]

    @property
    def key_fields(self) -> dict[str, Any]:
        return {"_reference_set_hash": self.pinned.set_hash}


def _invalid(message: str, reason_code: str, chain_auth: str | None = None) -> ToolFailure:
    detail: dict[str, Any] = {"reason_code": reason_code}
    if chain_auth is not None:
        detail["chain_auth"] = chain_auth
    return ToolFailure(FailureClass.input_invalid, message, detail=detail)


def _unavailable(exc: rs.SnapshotUnavailable) -> ToolFailure:
    return ToolFailure(FailureClass.precondition, exc.reason, detail={"reason_code": exc.reason_code})


def _normalized(store: Any, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    unknown = set(args) - _ARG_KEYS
    if unknown:
        raise _invalid(f"unknown parameters: {sorted(unknown)}", "unknown_field")
    handle = args.get("structure")
    if type(handle) is not str:
        raise _invalid("'structure' must be a structure handle", "structure_invalid")
    try:
        kind = store.kind_of(handle)
    except KeyError:
        raise _invalid("unknown handle (not an object of this run)", "structure_invalid") from None
    if kind not in ALLOWED_KINDS:
        raise _invalid(f"structure must be one of {list(ALLOWED_KINDS)}, got '{kind}'", "structure_kind_not_allowed")
    pdb_id = args.get("pdb_id")
    if pdb_id is not None and (type(pdb_id) is not str or not _PDB_ID.fullmatch(pdb_id)):
        raise _invalid("pdb_id must be a four-character PDB ID or null", "pdb_id_invalid")
    chains = args.get("chains")
    if type(chains) is not list or not chains:
        raise _invalid("chains must be a non-empty list", "chains_invalid")
    normalized_chains = []
    seen: set[str] = set()
    for item in chains:
        if type(item) is not dict:
            raise _invalid("each chain must be an object", "chains_invalid")
        extra = set(item) - _CHAIN_KEYS
        if extra:
            raise _invalid(f"unknown chain fields: {sorted(extra)}", "unknown_field")
        chain_auth = item.get("chain_auth")
        accession = item.get("uniprot_accession")
        if type(chain_auth) is not str or not chain_auth:
            raise _invalid("chain_auth must be a non-empty string", "chains_invalid")
        if accession is not None and (type(accession) is not str or not accession):
            raise _invalid("uniprot_accession must be a non-empty string or null", "chains_invalid", chain_auth)
        if chain_auth in seen:
            raise _invalid("duplicate chain_auth", "duplicate_chain", chain_auth)
        seen.add(chain_auth)
        normalized_chains.append({"chain_auth": chain_auth, "uniprot_accession": accession})
    return {"structure": handle, "pdb_id": pdb_id.upper() if pdb_id is not None else None,
            "chains": normalized_chains}, kind


def precheck(store: Any, args: dict[str, Any], bound: NumberingBound | None = None,
             ) -> tuple[dict[str, Any], NumberingBound]:
    """Registry pre-check hook: ``(normalized args, bound)`` or ``ToolFailure``; never runs the implementation."""
    try:
        pinned = bound.pinned if bound is not None else rs.pin_active_set()
    except rs.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc
    normalized, kind = _normalized(store, args)
    try:
        index = rn.reference_index(pinned)
    except rs.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc
    st = _parse(ToolContext(store=store, call_id="numbering_precheck"), normalized["structure"])
    model_number = st[0].num
    try:
        per_chain = rn.chain_residues(st, _res_ref)
    except ValueError as exc:
        raise ToolFailure(FailureClass.input_invalid, "structure entity setup is inconsistent",
                          detail={"reason_code": "structure_entities_inconsistent"}) from exc
    plans = []
    for item in normalized["chains"]:
        chain_auth = item["chain_auth"]
        found = per_chain.get(chain_auth)
        if found is None:
            raise _invalid("chain has no polymer residues in the selected model (or does not exist)",
                           "chain_not_found", chain_auth)
        try:
            plans.append(rn.plan_chain(chain_auth, found["residues"], found["modified"], normalized["pdb_id"],
                                       item["uniprot_accession"], index, rn.MAX_ALIGNMENT_CELLS))
        except rn.NumberingInvalid as exc:
            raise _invalid(exc.message, exc.reason_code, chain_auth) from exc
        except rs.SnapshotUnavailable as exc:
            raise _unavailable(exc) from exc
    return normalized, NumberingBound(pinned, index, normalized["structure"], kind, model_number,
                                      normalized["pdb_id"], tuple(plans))


def register(reg: ToolRegistry) -> None:
    @reg.register(TOOL, precheck=precheck)
    def map_residue_numbering(ctx: ToolContext, structure: str, chains: list[dict[str, Any]],
                              pdb_id: str | None = None) -> Handle:
        bound = ctx.bound
        if not isinstance(bound, NumberingBound) or bound.structure != structure or bound.pdb_id != pdb_id:
            raise ToolFailure(FailureClass.fatal, "numbering implementation called without its pre-check")
        if [p.chain_auth for p in bound.plans] != [c["chain_auth"] for c in chains]:
            raise ToolFailure(FailureClass.fatal, "numbering pre-check does not match the arguments")
        try:
            content = rn.build_map(structure_handle=structure, structure_kind=bound.structure_kind,
                                   model_number=bound.model_number, pdb_id=pdb_id, plans=bound.plans,
                                   pinned=bound.pinned, index=bound.index)
        except ValueError as exc:  # malformed KLIFS pocket: the snapshot format is unknown
            raise _unavailable(rs.SnapshotUnavailable("snapshot_invalid")) from exc
        manifest = bound.pinned.manifest
        if hashlib.sha256(canonical_json(manifest)).hexdigest() != bound.pinned.set_hash:
            raise _unavailable(rs.SnapshotUnavailable("snapshot_invalid"))
        # The set record goes first; identical content is the identical handle (no second event).
        ctx.store.put(rn.SET_KIND, rs.SET_SCHEMA, manifest, produced_by=ctx.call_id,
                      summary={"set_hash": bound.pinned.set_hash})
        totals = {status: sum(c["counts"][status] for c in content["chains"])
                  for status in ("mapped", "unmapped", "conflict")}
        summary = {"structure": structure, "chains": [c["chain_auth"] for c in content["chains"]],
                   "set_hash": bound.pinned.set_hash, **totals}
        return ctx.store.put(rn.KIND, rn.SCHEMA, content, produced_by=ctx.call_id, summary=summary,
                             null_result=content["null_result"])
