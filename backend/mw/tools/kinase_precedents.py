"""M27 tool ``link_kinase_precedents``: validated pre-check + ``kinase_precedents@1`` result (spec 5).

Order on every call path (``Run.call``, argument repair, prerequisite retry), enforced by the registry pre-check hook
that ``Run._validated_bound`` runs before the generic argument check:
  0. pin the active precedent reference set and decode it (none -> ``not_installed``; hash or format mismatch ->
     ``snapshot_invalid``): ``precondition``, before any admission check and before any cache lookup;
  1-5. the closed admission checks of spec 5.2 in ``ADMISSION_REASON_CODES`` order (``input_invalid`` with
     ``detail.reason_code``); the implementation is never called. The numbering map is read from this run's store and
     checked locally (``kinase_precedents.numbering_map_shape_ok``: the fields the linking reads), not by M15 code;
  then the cache key adds the pinned set hash and the method version (``PrecedentBound.key_fields``) to the normalized
  arguments (``chains`` is always the sorted list: null means every chain of the map), and the implementation builds
  the result from that same pinned set (``ToolContext.bound``), never re-reading ``active.json``.

The tool reads only the pinned set and the chosen ``residue_numbering_map@1`` object: no network, no M15 or M26
reference folder, no kbase folder, no structure bytes. An included record whose ``content_hash`` no longer matches is
``snapshot_invalid`` (412). The built content is re-checked by ``kinase_precedents.validated_result`` before it is
stored (failure: ``input_invalid`` ``result_invalid``, nothing stored); above 1 MiB it is ``resource_exceeded``
``result_too_large`` (nothing stored, nothing truncated; the detail says which targets fit alone and whether turning
``include_flagged`` off fits). A chain that does not link is a result state (spec 5.3), not an admission refusal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import kinase_precedents as kp
from .. import precedent_constants as K
from .. import precedent_snapshots as ps
from ..core.errors import FailureClass, ToolFailure
from ..core.handles import Handle, canonical_json
from .registry import ToolContext, ToolRegistry

TOOL = K.TOOL
MAP_TYPE = (kp.MAP_KIND, kp.MAP_SCHEMA)
_ARG_KEYS = frozenset({"numbering_map", "chains", "include_flagged"})


@dataclass(frozen=True)
class PrecedentBound:
    """What the pre-check fixed for one call: the pinned set, its index and the numbering map content."""

    pinned: ps.PinnedPrecedentSet
    index: kp.PrecedentIndex
    numbering_map: dict[str, Any]
    normalized_args: dict[str, Any]

    @property
    def key_fields(self) -> dict[str, Any]:
        return {"_precedent_set_hash": self.pinned.set_hash, "_method_version": K.METHOD_VERSION}


def _invalid(message: str, reason_code: str, chain_auth: str | None = None) -> ToolFailure:
    detail: dict[str, Any] = {"reason_code": reason_code}
    if chain_auth is not None:
        detail["chain_auth"] = chain_auth
    return ToolFailure(FailureClass.input_invalid, message, detail=detail)


def _unavailable(exc: ps.SnapshotUnavailable) -> ToolFailure:
    return ToolFailure(FailureClass.precondition, exc.reason, detail={"reason_code": exc.reason_code})


def _same_call(args: dict[str, Any], bound: Any) -> bool:
    if not isinstance(bound, PrecedentBound):
        return False
    try:
        return canonical_json(args) == canonical_json(bound.normalized_args)
    except (TypeError, ValueError):
        return False


def _numbering_map(store: Any, handle: Any) -> dict[str, Any]:
    """2. a ``residue_numbering_map@1`` of this run whose stored object has the fields the linking reads."""
    if type(handle) is not str:
        raise _invalid("numbering_map must be a residue_numbering_map handle of this run", "numbering_map_invalid")
    try:
        meta = store.meta(handle)
    except (KeyError, ValueError, TypeError):
        raise _invalid("unknown handle (not an object of this run)", "numbering_map_invalid") from None
    if (meta["kind"], meta["schema"]) != MAP_TYPE:
        raise _invalid(f"numbering_map must be a residue_numbering_map, got '{meta['kind']}'", "numbering_map_invalid")
    try:
        content = store.load(handle)
    except RecursionError:   # a stored object nested past the recursion limit is not a map (never a 500)
        raise _invalid("the numbering map object cannot be read", "numbering_map_invalid") from None
    if not kp.numbering_map_shape_ok(content):
        raise _invalid("the numbering map object does not have the residue_numbering_map@1 fields the linking reads",
                       "numbering_map_invalid")
    if not content["chains"]:
        raise _invalid("the numbering map lists no chain", "numbering_map_invalid")
    return content


def _chains(value: Any) -> list[str] | None:
    """4. null or a non-empty list of distinct ``chain_auth`` strings."""
    if value is None:
        return None
    if type(value) is not list or not value:
        raise _invalid("chains must be null or a non-empty list of chain_auth strings", "chains_invalid")
    seen: set[str] = set()
    for item in value:
        if type(item) is not str:
            raise _invalid("each chain is a chain_auth string", "chains_invalid")
        if item in seen:
            raise _invalid("duplicate chain_auth", "chains_invalid", item)
        seen.add(item)
    return list(value)


def precheck(store: Any, args: dict[str, Any], bound: PrecedentBound | None = None,
             ) -> tuple[dict[str, Any], PrecedentBound]:
    """Registry pre-check hook: ``(normalized args, bound)`` or ``ToolFailure``; never runs the implementation."""
    if isinstance(bound, PrecedentBound):
        pinned, index = bound.pinned, bound.index        # re-validation inside one call keeps its pinned set
    else:
        try:
            pinned, index = kp.pin_and_index()            # 0. before any admission check and any cache lookup
        except ps.SnapshotUnavailable as exc:
            raise _unavailable(exc) from exc
    if _same_call(args, bound):
        return dict(bound.normalized_args), bound          # the same normalized call: objects are immutable
    unknown = set(args) - _ARG_KEYS                                                   # 1
    if unknown:
        raise _invalid(f"unknown parameters: {sorted(unknown)}", "unknown_field")
    handle = args.get("numbering_map")
    content = _numbering_map(store, handle)                                           # 2
    include_flagged = args.get("include_flagged")                                     # 3
    if type(include_flagged) is not bool:
        raise _invalid("include_flagged must be true or false", "include_flagged_invalid")
    chains = _chains(args.get("chains"))                                              # 4
    names = [chain["chain_auth"] for chain in content["chains"]]
    for name in chains or ():                                                         # 5
        if name not in names:
            raise _invalid("the chain is not a chain of the numbering map", "chain_not_in_map", name)
    normalized = {"numbering_map": handle, "chains": sorted(names if chains is None else chains),
                  "include_flagged": include_flagged}
    return normalized, PrecedentBound(pinned, index, content, normalized)


def register(reg: ToolRegistry) -> None:
    @reg.register(TOOL, precheck=precheck)
    def link_kinase_precedents(ctx: ToolContext, numbering_map: str, chains: list[str],
                               include_flagged: bool) -> Handle:
        bound = ctx.bound
        args = {"numbering_map": numbering_map, "chains": chains, "include_flagged": include_flagged}
        if not isinstance(bound, PrecedentBound) or bound.normalized_args != args:
            raise ToolFailure(FailureClass.fatal, "kinase precedent implementation called without its pre-check")
        try:
            content = kp.build_kinase_precedents(
                pinned=bound.pinned, index=bound.index, numbering_map=bound.numbering_map,
                numbering_map_handle=numbering_map, chains=chains, include_flagged=include_flagged)
        except ps.SnapshotUnavailable as exc:   # an included record no longer matches its content_hash
            raise _unavailable(exc) from exc
        except kp.ResultTooLarge as exc:
            raise ToolFailure(FailureClass.resource_exceeded, str(exc),
                              detail={"reason_code": K.RESULT_TOO_LARGE_REASON, "limit": exc.limit,
                                      "actual": exc.actual, "size_without_flagged": exc.size_without_flagged,
                                      "target_sizes": exc.target_sizes}) from exc
        try:   # a build/validate mismatch is never stored
            kp.validated_result(content)
        except kp.ResultInvalid as exc:
            raise ToolFailure(FailureClass.input_invalid, f"the built result does not validate: {exc}",
                              detail={"reason_code": K.RESULT_INVALID_REASON}) from exc
        summary = {"numbering_map": numbering_map, "pdb_id": content["pdb_id"],
                   "chains": [chain["chain_auth"] for chain in content["chains"]], "include_flagged": include_flagged,
                   "set_hash": bound.pinned.set_hash, "linked_chains": content["counts"]["linked_chains"]}
        return ctx.store.put(K.KIND, K.SCHEMA, content, produced_by=ctx.call_id, summary=summary,
                             null_result=content["null_result"])
