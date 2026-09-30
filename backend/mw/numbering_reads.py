"""M15 read-only projections for the residue numbering UI (no tool call, no job, no event).

* ``snapshots()``: the active reference set's manifest records, or the unavailable reason (always a 200 body).
* ``pdb_id_hint()``: a PDB ID *suggestion* from the uploaded bytes a structure came from (``structure`` ->
  ``structure_source``; ``prepared_structure`` -> its preparation manifest's ``source_handle``): mmCIF ``_entry.id``
  or the PDB ``HEADER`` idcode (columns 63-66). Only values matching ``[0-9][A-Za-z0-9]{3}`` are suggested (uppercase).
* ``sifts_chains()`` / ``uniprot_search()``: prefill lookups in the pinned set (UniProt ``status: ok`` entries only;
  the sequence is never returned).
* ``numbering_maps()``: this run's ``residue_numbering_map`` objects, newest first; ``stale_snapshot`` is true when
  the map's set hash differs from the active set or no usable active set exists.
* ``numbering_rows()``: one page of a map's ``rows`` for the generic ``GET /runs/{id}/objects`` route.
"""
from __future__ import annotations

import re
import threading
from typing import Any

from . import reference_snapshots as rs
from . import residue_numbering as rn
from . import sifts_mapping as sm

PDB_ID_RE = re.compile(r"[0-9][A-Za-z0-9]{3}\Z")
HINT_KINDS = ("structure", "prepared_structure")
UNIPROT_FIELDS = ("accession", "entry_name", "gene", "protein_name", "organism")
_SEARCH_FIELDS = ("accession", "gene", "entry_name", "protein_name")
_CACHE_SETS = 2
_UNIPROT: dict[str, list[dict[str, Any]]] = {}
_LOCK = threading.Lock()


class ReadInvalid(ValueError):
    """The request names something this read cannot answer for (mapped to 422 ``input_invalid``)."""


def _unavailable(exc: rs.SnapshotUnavailable) -> dict[str, Any]:
    return {"available": False, "reason_code": exc.reason_code, "reason": exc.reason, "set_hash": None}


def _available(pinned: rs.PinnedSet) -> dict[str, Any]:
    return {"available": True, "reason_code": None, "reason": None, "set_hash": pinned.set_hash}


def snapshots() -> dict[str, Any]:
    try:
        pinned = rs.pin_active_set()
    except rs.SnapshotUnavailable as exc:
        return {"schema": "reference_snapshots@1", **_unavailable(exc), "origin": None, "imported_at": None,
                "kbase_repo": None, "sources": []}
    manifest = pinned.manifest
    return {"schema": "reference_snapshots@1", **_available(pinned), "origin": rs.ORIGIN,
            "imported_at": manifest["imported_at"], "kbase_repo": manifest["kbase_repo"],
            "sources": manifest["sources"]}


def normalized_pdb_id(value: str) -> str:
    if not PDB_ID_RE.fullmatch(value):
        raise ReadInvalid("pdb_id must be a four-character PDB ID")
    return value.upper()


def _suggested(value: Any) -> str | None:
    return value.upper() if type(value) is str and PDB_ID_RE.fullmatch(value) else None


def _mmcif_entry_id(text: str) -> str | None:
    import gemmi
    try:
        value = gemmi.cif.read_string(text).sole_block().find_value("_entry.id")
    except Exception:  # noqa: BLE001 - a suggestion only; unreadable -> no suggestion
        return None
    return _suggested(gemmi.cif.as_string(value)) if value is not None else None


def _pdb_header_idcode(text: str) -> str | None:
    for line in text.splitlines():
        if line[:6] == "HEADER":
            return _suggested(line[62:66])
    return None


def pdb_id_hint(store: Any, handle: str, kind: str) -> dict[str, Any]:
    """``kind`` is the handle's already checked kind; the source bytes are read, never parsed as coordinates."""
    if kind not in HINT_KINDS:
        raise ReadInvalid(f"structure must be one of {list(HINT_KINDS)}")
    if kind == "structure":
        source = store.load(handle)["source"]
    else:
        source = store.load(store.load(handle)["manifest"])["source_handle"]
    meta = store.meta(source)
    if meta["kind"] != "structure_source":
        raise ValueError("structure source is not an uploaded structure")
    raw = store.load(source)
    text = raw.decode("utf-8") if isinstance(raw, bytes) else ""
    fmt = meta["fmt"]
    if fmt in ("cif", "mmcif"):
        pdb_id, origin = _mmcif_entry_id(text), "mmcif_entry_id"
    else:
        pdb_id, origin = _pdb_header_idcode(text), "pdb_header"
    return {"structure": handle, "structure_kind": kind, "format": fmt, "pdb_id": pdb_id,
            "origin": origin if pdb_id is not None else None}


def sifts_chains(pdb_id: str) -> dict[str, Any]:
    pdb = normalized_pdb_id(pdb_id)
    try:
        pinned = rs.pin_active_set()
        chains = sm.sifts_chains_for_pdb(pdb, pinned=pinned)
    except rs.SnapshotUnavailable as exc:
        return {"schema": "reference_sifts_chains@1", **_unavailable(exc), "pdb_id": pdb, "chains": []}
    return {"schema": "reference_sifts_chains@1", **_available(pinned), "pdb_id": pdb,
            "chains": [{**chain, "reason": sm.REASONS[chain["reason_code"]] if chain["reason_code"] else None}
                       for chain in chains]}


def _uniprot_entries(pinned: rs.PinnedSet) -> list[dict[str, Any]]:
    with _LOCK:
        cached = _UNIPROT.get(pinned.set_hash)
    if cached is not None:
        return cached
    index = rn.reference_index(pinned)  # validates the UniProt rows exactly as the tool does
    entries = []
    for row in pinned.iter_jsonl("uniprot", "entries.jsonl"):
        record = index.uniprot[row["id"]]
        if record["status"] != "ok":
            continue
        data = row["data"]
        entry = {field: data.get(field) if type(data.get(field)) is str else None for field in UNIPROT_FIELDS}
        entry["accession"] = row["id"]
        entry["sequence_length"] = len(record["sequence"])
        entries.append(entry)
    with _LOCK:
        while len(_UNIPROT) >= _CACHE_SETS:
            _UNIPROT.pop(next(iter(_UNIPROT)))
        return _UNIPROT.setdefault(pinned.set_hash, entries)


def uniprot_search(query: str, offset: int, limit: int) -> dict[str, Any]:
    head = {"schema": "reference_uniprot_search@1", "query": query, "offset": offset, "limit": limit}
    try:
        pinned = rs.pin_active_set()
        entries = _uniprot_entries(pinned)
    except rs.SnapshotUnavailable as exc:
        return {**head, **_unavailable(exc), "total": 0, "entries": []}
    needle = query.casefold()
    found = [entry for entry in entries
             if any(entry[field] is not None and needle in entry[field].casefold() for field in _SEARCH_FIELDS)]
    return {**head, **_available(pinned), "total": len(found), "entries": found[offset:offset + limit]}


def numbering_maps(run: Any, offset: int, limit: int) -> dict[str, Any]:
    try:
        active: str | None = rs.pin_active_set().set_hash
    except rs.SnapshotUnavailable:
        active = None
    created: dict[str, int] = {}
    for event in run.events.read():
        if event["type"] == "object_created" and event.get("kind") == rn.KIND and event["handle"] not in created:
            created[event["handle"]] = event["seq"]
    handles = sorted(created, key=created.__getitem__, reverse=True)  # newest first
    rows = []
    for handle in handles[offset:offset + limit]:
        content = run.store.load(handle)
        if type(content) is not dict or content.get("schema") != rn.SCHEMA:
            raise ValueError("residue numbering map payload is invalid")
        counts = {status: sum(chain["counts"][status] for chain in content["chains"])
                  for status in ("mapped", "unmapped", "conflict")}
        set_hash = content["snapshot_set"]["set_hash"]
        rows.append({"handle": handle, "structure": content["structure"]["handle"],
                     "structure_kind": content["structure"]["structure_kind"],
                     "model_number": content["structure"]["model_number"], "pdb_id": content["pdb_id"],
                     "chains": [chain["chain_auth"] for chain in content["chains"]],
                     "cross_checked_chains": [chain["chain_auth"] for chain in content["chains"]
                                              if chain["cross_check"]],
                     "set_hash": set_hash, "counts": counts, "row_count": len(content["rows"]),
                     "null_result": content["null_result"], "created_seq": created[handle],
                     "stale_snapshot": active is None or set_hash != active})
    return {"schema": "residue_numbering_map_list@1", "active_set_hash": active, "snapshot_available": active is not None,
            "total": len(handles), "offset": offset, "limit": limit, "rows": rows}


def numbering_rows(content: Any, columns: list[str] | None, offset: int, limit: int) -> tuple[list[dict], int]:
    """A page of a map's ``rows`` (same column rules as ``ObjectStore.materialize``) and the total row count."""
    if type(content) is not dict or type(content.get("rows")) is not list:
        raise TypeError("object is not a row table")
    rows = content["rows"]
    page = rows[offset:offset + limit]
    if columns is None:
        return page, len(rows)
    valid = {key for row in rows for key in row}
    if not columns or any(column not in valid for column in columns):
        raise ValueError("unknown materialization column")
    return [{key: row.get(key) for key in columns} for row in page], len(rows)
