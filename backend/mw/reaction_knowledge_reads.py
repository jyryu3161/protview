"""M26 read-only projections (spec 6): the reaction reference set and this run's ``reaction_knowledge@1`` results.

No tool call, no job, no event, no external request. Run-scoped reads look at the event log at most once per request
(the list reads it once to find the result objects in creation order; the detail reads the object from the store and
does not need the log). Every result read loads the stored object (content-hash check) and re-checks it with
``reaction_knowledge.validated_result``; the result carries its own reference rows and set record, so it reopens from
events alone, without the reference folder. The current active set is only compared, never used to recompute.

* ``capability()``: ``/capabilities`` ``methods.reaction_knowledge`` (set pinned AND decoded; five keys).
* ``status()``: ``reaction_reference_status@1``; unavailable -> ``installed: false`` + the reason code, rest null.
* ``pdb_entries(pdb_id)``: the M-CSA entries naming a PDB ID (``ReadInvalid`` for a malformed ID,
  ``reaction_snapshots.SnapshotUnavailable`` without a usable set).
* ``list_results(run, offset, limit)`` / ``detail(run, handle, ...)``: the caller checks the handle's run and kind
  (``KIND``, ``SCHEMA``); ``validated(run, handle)`` is the one stored-result read (``ResultEvidenceError``).
"""
from __future__ import annotations

import re
from typing import Any

from . import reaction_knowledge as rk
from . import reaction_knowledge_constants as K
from . import reaction_snapshots as rs

LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX = 50, 100
CHAIN_LIMIT_DEFAULT, CHAIN_LIMIT_MAX = 10, 10
ROW_LIMIT_DEFAULT, ROW_LIMIT_MAX = 50, 200
FEATURE_LIMIT_DEFAULT, FEATURE_LIMIT_MAX = 50, 200
KIND, SCHEMA = K.KIND, K.SCHEMA
SnapshotUnavailable = rs.SnapshotUnavailable   # no usable set: the route answers with the tool's 412 body
_PDB_ID = re.compile(K.PDB_ID_PATTERN + r"\Z")


class ReadInvalid(ValueError):
    """A request this read cannot answer (mapped to 422 ``input_invalid``)."""


class ResultEvidenceError(ValueError):
    """The stored object does not load or does not validate."""


def capability() -> dict[str, Any]:
    return rk.capability()


def _active_set_hash() -> str | None:
    """The usable active set's hash, or ``None`` (not installed / invalid)."""
    try:
        return rk.pin_and_index()[0].set_hash
    except rs.SnapshotUnavailable:
        return None


def status() -> dict[str, Any]:
    try:
        pinned, _index = rk.pin_and_index()
    except rs.SnapshotUnavailable as exc:
        return {"schema": K.STATUS_SCHEMA, "installed": False, "reason": exc.reason_code, "set_hash": None,
                "imported_at": None, "sources": None, "requested_accessions": None, "skipped_accessions": None}
    manifest = pinned.manifest
    return {"schema": K.STATUS_SCHEMA, "installed": True, "reason": None, "set_hash": pinned.set_hash,
            "imported_at": manifest["imported_at"], "sources": pinned.summary(),
            "requested_accessions": manifest["requested_accessions"],
            "skipped_accessions": manifest["skipped_accessions"]}


def normalized_pdb_id(value: str) -> str:
    if not _PDB_ID.fullmatch(value):
        raise ReadInvalid("pdb_id must be a four-character PDB ID ([0-9][A-Za-z0-9]{3})")
    return value.upper()


def pdb_entries(pdb_id: str) -> dict[str, Any]:
    pdb = normalized_pdb_id(pdb_id)   # before the folder is read
    _pinned, index = rk.pin_and_index()
    return {"pdb_id": pdb, "entries": rk.pdb_entries(index, pdb)}


def validated(run: Any, handle: str) -> dict[str, Any]:
    try:
        return rk.validated_result(run.store.load(handle))
    except (rk.ResultInvalid, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ResultEvidenceError("invalid reaction knowledge result") from exc


def _created(run: Any) -> dict[str, int]:
    """Creating event sequence number of each ``reaction_knowledge`` handle, in creation order (one log read)."""
    found: dict[str, int] = {}
    for event in run.events.read():
        if event["type"] == "object_created" and event.get("kind") == K.KIND and event["handle"] not in found:
            found[event["handle"]] = event["seq"]
    return found


def list_results(run: Any, offset: int, limit: int) -> dict[str, Any]:
    created = _created(run)
    active = _active_set_hash()
    items = []
    for handle in list(reversed(created))[offset:offset + limit]:   # newest first
        content = validated(run, handle)
        counts, set_hash = content["counts"], content["snapshot_set"]["set_hash"]
        features = counts["uniprot_features"]
        items.append({"handle": handle, "structure_handle": content["structure"]["handle"],
                      "structure_kind": content["structure"]["structure_kind"], "pdb_id": content["pdb_id"],
                      "chain_count": counts["chains"], "covered_chain_count": counts["covered_chains"],
                      "mcsa_rows": counts["mcsa_rows"],
                      "uniprot_feature_count": None if features is None else sum(features.values()),
                      "null_result": content["null_result"], "set_hash": set_hash,
                      "active": active is not None and set_hash == active})
    return {"items": items, "total": len(created)}


def _page(values: list[Any] | None, offset: int, limit: int) -> tuple[list[Any] | None, int | None]:
    return (None, None) if values is None else (values[offset:offset + limit], len(values))


def detail(run: Any, handle: str, *, chain_offset: int, chain_limit: int, row_offset: int, row_limit: int,
           feature_offset: int, feature_limit: int) -> dict[str, Any]:
    content = validated(run, handle)
    chains = []
    for chain in content["chains"][chain_offset:chain_offset + chain_limit]:
        rows, row_total = _page(chain["mcsa"]["rows"], row_offset, row_limit)
        features, feature_total = _page(chain["uniprot"]["features"], feature_offset, feature_limit)
        chains.append({**chain, "mcsa": {**chain["mcsa"], "rows": rows, "row_total": row_total},
                       "uniprot": {**chain["uniprot"], "features": features, "feature_total": feature_total}})
    active = _active_set_hash()
    return {**content, "chains": chains,
            "page": {"chain_total": len(content["chains"]), "chain_offset": chain_offset, "chain_limit": chain_limit,
                     "row_offset": row_offset, "row_limit": row_limit, "feature_offset": feature_offset,
                     "feature_limit": feature_limit},
            "active_set": {"set_hash": active,
                           "same": active is not None and active == content["snapshot_set"]["set_hash"]}}
