"""M15 SIFTS decoder: kbase_kinase processed SIFTS rows -> PDBe residue listing + per-entity UniProt segments.

Pure functions over the pinned reference set (``mw.reference_snapshots``); standard library only. This module does not
match structure residues (a later step does that by author number + insertion code) and never guesses:

* ``residues.jsonl`` rows ``{id, pdb_id, chain, status, data[, reason]}``. ``data`` is either the historical v0 JSON
  list of raw PDBe residue-listing rows or the ``pdbe-residue-runs-v1`` dict ``{format, runs, exceptions, columns,
  insertion_codes}``. In v1 the runs map PDBe number -> author number (``pdbe_start``/``pdb_start``/``length``);
  exception rows carry the PDBe number in a field named ``uniprot_resnum`` (it is NOT a UniProt position); column
  values and ``insertion_codes`` are indexed by the restored rows sorted in kbase's row order. Row count, column
  lengths, insertion codes and the ``not_observed`` <-> ``observed_ratio == 0`` invariant are all cross-checked; any
  mismatch or unknown shape makes the chain unusable (``sifts_chain_lookup_failed``).
* PDBe numbers restart at 1 per entity and one chain row mixes entities (polymer, ligands, water), so residues are
  keyed by ``(entity_id, pdbe_number)``; only entities that have a UniProt segment for this chain are mapped.
* ``segments.jsonl`` rows ``{id, pdb_id, status, data[, chain][, reason]}`` hold every chain's segments for the entry
  (``chain`` is only the chain that triggered the fetch and may be absent). Segments are selected by
  ``chain_id == chain_auth``. ``res_start``/``res_end`` are PDBe numbers and a segment is linear:
  ``position = unp_start + (pdbe_number - res_start)`` (ranges must have equal length, else the chain is rejected).
"""
from __future__ import annotations

import itertools
import json
import math
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from . import reference_snapshots as rs

RESIDUE_FORMAT_V1 = "pdbe-residue-runs-v1"
OUTSIDE_SEGMENTS = "sifts_outside_segments"
REASONS = {
    "pdb_not_in_sifts_snapshot": ("이 PDB 항목은 SIFTS 참조 스냅샷에 없습니다. "
                                  "This PDB entry is not in the SIFTS reference snapshot."),
    "chain_not_in_sifts_snapshot": ("이 체인은 SIFTS 참조 스냅샷에 없습니다. "
                                    "This chain is not in the SIFTS reference snapshot."),
    "sifts_chain_lookup_failed": ("SIFTS 스냅샷의 이 체인 기록을 사용할 수 없습니다(조회 실패, 알 수 없는 형식 또는 복원 불일치). "
                                  "The SIFTS snapshot record for this chain is unusable (lookup failed, unknown format "
                                  "or restore mismatch)."),
    "sifts_chain_no_segments": ("SIFTS 스냅샷에 이 체인의 UniProt 구간이 없습니다. "
                                "The SIFTS snapshot has no UniProt segment for this chain."),
    OUTSIDE_SEGMENTS: ("이 잔기는 SIFTS UniProt 구간 밖에 있습니다. "
                       "This residue lies outside the SIFTS UniProt segments."),
}
_KNOWN_STATUS = ("not_found", "lookup_failed")
_EXCEPTION_REASONS = ("not_observed", "missing_number")
_V1_KEYS = frozenset({"format", "runs", "exceptions", "columns", "insertion_codes"})
_RUN_KEYS = frozenset({"pdbe_start", "pdb_start", "length", "insertion_code"})
_EXCEPTION_ROW_KEYS = frozenset({"uniprot_resnum", "pdb_resnum", "insertion_code", "observed_ratio"})
_V0_REQUIRED = ("residue_number", "author_residue_number", "author_insertion_code", "residue_name", "entity_id",
                "chain", "pdb_id", "observed_ratio")
_SEGMENT_INTS = ("entity_id", "unp_start", "unp_end", "res_start", "res_end")
_CACHE_SETS = 2


class SiftsFormatError(ValueError):
    """A snapshot row cannot even be keyed by (pdb_id, chain): the whole file is not the expected SIFTS layout."""


class _Reject(Exception):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


def _fail(detail: str) -> _Reject:
    return _Reject("sifts_chain_lookup_failed", detail)


@dataclass(frozen=True)
class SiftsUnusable:
    """Why a chain has no SIFTS numbering: ``reason_code`` (REASONS key), fixed ``reason`` text, safe ``detail`` enum."""

    pdb_id: str
    chain_auth: str
    reason_code: str
    detail: str | None = None

    @property
    def reason(self) -> str:
        return REASONS[self.reason_code]


@dataclass(frozen=True)
class SiftsSegment:
    accession: str
    entity_id: int
    pdbe_start: int
    pdbe_end: int
    unp_start: int
    unp_end: int
    identity: float | None
    coverage: float | None


@dataclass(frozen=True)
class SiftsChain:
    """One decoded chain: residue rows (all entities, sorted) and the chain's UniProt segments per entity."""

    pdb_id: str
    chain_auth: str
    residues: tuple[dict[str, Any], ...]
    segments: dict[int, tuple[SiftsSegment, ...]]

    @property
    def accessions(self) -> frozenset[str]:
        return frozenset(s.accession for group in self.segments.values() for s in group)

    def uniprot_position(self, entity_id: int, pdbe_number: int) -> tuple[str, int] | None:
        """``(accession, position)`` by the linear segment rule, or None (reason ``sifts_outside_segments``)."""
        for segment in self.segments.get(entity_id, ()):
            if segment.pdbe_start <= pdbe_number <= segment.pdbe_end:
                return segment.accession, segment.unp_start + (pdbe_number - segment.pdbe_start)
        return None

    def mapping(self, entity_id: int, pdbe_number: int) -> dict[str, Any]:
        found = self.uniprot_position(entity_id, pdbe_number)
        if found is None:
            return {"accession": None, "position": None, "reason_code": OUTSIDE_SEGMENTS}
        return {"accession": found[0], "position": found[1], "reason_code": None}


def _is_int(value: Any, minimum: int | None = None) -> bool:
    return type(value) is int and (minimum is None or value >= minimum)


def _is_ratio(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def _is_code(value: Any) -> bool:
    return value is None or type(value) is str


def _residue(entity_id: Any, pdbe: Any, author: Any, code: Any, name: Any, ratio: Any,
             reason: str | None) -> dict[str, Any]:
    if not (_is_int(entity_id, 1) and _is_int(pdbe, 1) and (author is None or _is_int(author))
            and _is_code(code) and type(name) is str and name and _is_ratio(ratio)):
        raise _fail("restore_mismatch")
    if (reason == "not_observed") != (ratio == 0):
        raise _fail("restore_mismatch")
    return {"entity_id": entity_id, "pdbe_number": pdbe, "author_number": author, "icode": code or "",
            "residue_name": name, "observed": ratio > 0, "exception_reason": reason}


def _decode_v0(rows: list, pdb_id: str, chain_auth: str) -> list[dict[str, Any]]:
    """Historical v0: the raw PDBe residue-listing rows (plus pdb_id/chain/entity_id) as a JSON list."""
    result = []
    for row in rows:
        if type(row) is not dict or any(key not in row for key in _V0_REQUIRED):
            raise _fail("unknown_format")
        if row["chain"] != chain_auth or row["pdb_id"] != pdb_id:
            raise _fail("restore_mismatch")
        ratio, author = row["observed_ratio"], row["author_residue_number"]
        reason = "not_observed" if ratio == 0 else "missing_number" if author is None else None
        result.append(_residue(row["entity_id"], row["residue_number"], author, row["author_insertion_code"],
                               row["residue_name"], ratio, reason))
    return result


def _kbase_order(row: dict[str, Any]) -> tuple:
    """kbase's row order for restored rows (PDBe number, author number, code, then the row's sorted-key JSON)."""
    number, author = row.get("uniprot_resnum"), row.get("pdb_resnum")
    return (number is None, number or 0, author is None, author or 0, row.get("insertion_code") or "",
            json.dumps(row, sort_keys=True))


def _decode_v1(data: dict, pdb_id: str, chain_auth: str) -> list[dict[str, Any]]:
    if set(data) != _V1_KEYS or data["format"] != RESIDUE_FORMAT_V1:
        raise _fail("unknown_format")
    runs, exceptions, columns, codes = data["runs"], data["exceptions"], data["columns"], data["insertion_codes"]
    if type(runs) is not list or type(exceptions) is not list or type(columns) is not dict or type(codes) is not list:
        raise _fail("unknown_format")
    restored: list[tuple[dict[str, Any], str | None]] = []
    for run in runs:
        if (type(run) is not dict or set(run) != _RUN_KEYS or not _is_int(run["pdbe_start"], 1)
                or not _is_int(run["pdb_start"]) or not _is_int(run["length"], 1) or not _is_code(run["insertion_code"])):
            raise _fail("unknown_format")
        for offset in range(run["length"]):
            restored.append(({"uniprot_resnum": run["pdbe_start"] + offset, "pdb_resnum": run["pdb_start"] + offset,
                              "insertion_code": run["insertion_code"]}, None))
    for item in exceptions:
        if type(item) is not dict or set(item) != {"reason", "row"} or item["reason"] not in _EXCEPTION_REASONS:
            raise _fail("unknown_format")
        row = item["row"]
        # "uniprot_resnum" here is the PDBe residue number (kbase naming), never a UniProt position.
        if (type(row) is not dict or not set(row) <= _EXCEPTION_ROW_KEYS or not _is_int(row.get("uniprot_resnum"), 1)
                or not (row.get("pdb_resnum") is None or _is_int(row["pdb_resnum"]))
                or not _is_code(row.get("insertion_code"))
                or ("observed_ratio" in row and row["observed_ratio"] != 0)):
            raise _fail("unknown_format")
        expected = ("not_observed" if row.get("observed_ratio") == 0 else
                    "missing_number" if row.get("pdb_resnum") is None else None)
        if item["reason"] != expected:
            raise _fail("restore_mismatch")
        restored.append((row, item["reason"]))
    restored.sort(key=lambda pair: _kbase_order(pair[0]))
    count = len(restored)
    if len(codes) != count:
        raise _fail("restore_mismatch")
    cells: dict[str, list[Any]] = {}
    for key in ("entity_id", "residue_name", "observed_ratio", "chain", "pdb_id"):
        column = columns.get(key)
        if type(column) is not dict or set(column) != {"values", "indices"} or type(column["values"]) is not list:
            raise _fail("restore_mismatch")
        values, indices = column["values"], column["indices"]
        if not all(type(v) is dict and set(v) == {"value"} for v in values):
            raise _fail("restore_mismatch")   # a row without the field ({}) is not accepted for required columns
        if indices is None:
            if len(values) != 1:
                raise _fail("restore_mismatch")
            cells[key] = [values[0]["value"]] * count
        else:
            if (type(indices) is not list or len(indices) != count
                    or not all(_is_int(i, 0) and i < len(values) for i in indices)):
                raise _fail("restore_mismatch")
            cells[key] = [values[i]["value"] for i in indices]
    result = []
    for i, (row, reason) in enumerate(restored):
        code = codes[i]
        if not _is_code(code) or (code or None) != (row.get("insertion_code") or None):
            raise _fail("restore_mismatch")
        if cells["chain"][i] != chain_auth or cells["pdb_id"][i] != pdb_id:
            raise _fail("restore_mismatch")
        result.append(_residue(cells["entity_id"][i], row["uniprot_resnum"], row.get("pdb_resnum"), code,
                               cells["residue_name"][i], cells["observed_ratio"][i], reason))
    return result


def _decode_residues(row: dict, pdb_id: str, chain_auth: str) -> list[dict[str, Any]]:
    status = row.get("status")
    if status != "ok":
        raise _fail(f"residues_status_{status}" if status in _KNOWN_STATUS else "residues_status_unknown")
    data = row.get("data")
    if type(data) is list:
        return _decode_v0(data, pdb_id, chain_auth)
    if type(data) is dict:
        return _decode_v1(data, pdb_id, chain_auth)
    raise _fail("unknown_format")


def _chain_segments(rows: list[dict], chain_auth: str) -> dict[int, tuple[SiftsSegment, ...]]:
    if not rows:
        raise _Reject("sifts_chain_no_segments", "segments_row_missing")
    if len(rows) > 1:
        raise _fail("duplicate_rows")
    row = rows[0]
    status = row.get("status")
    if status != "ok":
        detail = f"segments_status_{status}" if status in _KNOWN_STATUS else "segments_status_unknown"
        raise _Reject("sifts_chain_no_segments", detail)
    if type(row.get("data")) is not list:
        raise _fail("segment_invalid")
    groups: dict[int, list[SiftsSegment]] = {}
    for item in row["data"]:
        if type(item) is not dict or type(item.get("chain_id")) is not str:
            raise _fail("segment_invalid")
        if item["chain_id"] != chain_auth:
            continue
        if (not all(_is_int(item.get(key), 1) for key in _SEGMENT_INTS) or type(item.get("uniprot")) is not str
                or not item["uniprot"] or item["res_end"] < item["res_start"]
                or item["unp_end"] - item["unp_start"] != item["res_end"] - item["res_start"]
                or not all(item.get(key) is None or (type(item[key]) in (int, float) and math.isfinite(item[key]))
                           for key in ("identity", "coverage"))):
            raise _fail("segment_invalid")
        groups.setdefault(item["entity_id"], []).append(SiftsSegment(
            item["uniprot"], item["entity_id"], item["res_start"], item["res_end"], item["unp_start"],
            item["unp_end"], item.get("identity"), item.get("coverage")))
    if not groups:
        raise _Reject("sifts_chain_no_segments", "no_segment_for_chain")
    result = {}
    for entity_id, group in sorted(groups.items()):
        group.sort(key=lambda s: (s.pdbe_start, s.pdbe_end))
        if any(b.pdbe_start <= a.pdbe_end for a, b in itertools.pairwise(group)):
            raise _fail("segments_overlap")
        result[entity_id] = tuple(group)
    return result


def _residue_order(row: dict[str, Any]) -> tuple:
    author = row["author_number"]
    return (row["entity_id"], row["pdbe_number"], author is None, author or 0, row["icode"], row["residue_name"])


class SiftsIndex:
    """Rows of one SIFTS snapshot keyed by (PDB id, chain); chains decode on first lookup and are then cached."""

    def __init__(self, residue_rows: Iterable[Any], segment_rows: Iterable[Any]) -> None:
        self._residues: dict[tuple[str, str], list[dict]] = {}
        self._chains: dict[str, list[str]] = {}
        self._segments: dict[str, list[dict]] = {}
        for row in residue_rows:
            if (type(row) is not dict or type(row.get("pdb_id")) is not str or not row["pdb_id"]
                    or type(row.get("chain")) is not str or not row["chain"]):
                raise SiftsFormatError("SIFTS residue row without pdb_id/chain")
            pdb = row["pdb_id"].upper()
            key = (pdb, row["chain"])
            if key not in self._residues:
                self._chains.setdefault(pdb, []).append(row["chain"])
            self._residues.setdefault(key, []).append(row)
        for row in segment_rows:
            if type(row) is not dict or type(row.get("pdb_id")) is not str or not row["pdb_id"]:
                raise SiftsFormatError("SIFTS segment row without pdb_id")
            self._segments.setdefault(row["pdb_id"].upper(), []).append(row)
        self._decoded: dict[tuple[str, str], SiftsChain | SiftsUnusable] = {}
        self._lock = threading.Lock()

    def lookup(self, pdb_id: str, chain_auth: str) -> SiftsChain | SiftsUnusable:
        pdb = pdb_id.upper()
        key = (pdb, chain_auth)
        with self._lock:
            cached = self._decoded.get(key)
        if cached is not None:
            return cached
        result = self._decode(pdb, chain_auth)
        with self._lock:
            return self._decoded.setdefault(key, result)

    def _decode(self, pdb: str, chain_auth: str) -> SiftsChain | SiftsUnusable:
        if pdb not in self._chains:
            return SiftsUnusable(pdb, chain_auth, "pdb_not_in_sifts_snapshot")
        rows = self._residues.get((pdb, chain_auth))
        if rows is None:
            return SiftsUnusable(pdb, chain_auth, "chain_not_in_sifts_snapshot")
        try:
            if len(rows) > 1:
                raise _fail("duplicate_rows")
            residues = _decode_residues(rows[0], pdb, chain_auth)
            segments = _chain_segments(self._segments.get(pdb, []), chain_auth)
            seen: set[tuple[int, int]] = set()
            for residue in residues:
                if residue["entity_id"] in segments:
                    key = (residue["entity_id"], residue["pdbe_number"])
                    if key in seen:
                        raise _fail("duplicate_pdbe_number")
                    seen.add(key)
        except _Reject as exc:
            return SiftsUnusable(pdb, chain_auth, exc.reason_code, exc.detail)
        return SiftsChain(pdb, chain_auth, tuple(sorted(residues, key=_residue_order)), segments)

    def chains_for_pdb(self, pdb_id: str) -> list[dict[str, Any]]:
        """Every chain of the entry in snapshot order: ``{chain_auth, accessions (sorted), reason_code}``."""
        result = []
        for chain_auth in self._chains.get(pdb_id.upper(), []):
            found = self.lookup(pdb_id, chain_auth)
            usable = isinstance(found, SiftsChain)
            result.append({"chain_auth": chain_auth, "accessions": sorted(found.accessions) if usable else [],
                           "reason_code": None if usable else found.reason_code})
        return result


_INDEXES: dict[str, SiftsIndex] = {}
_INDEX_LOCK = threading.Lock()


def index_for_set(pinned: rs.PinnedSet) -> SiftsIndex:
    """The SIFTS index of a pinned set, built once per set hash (a malformed file -> SnapshotUnavailable)."""
    with _INDEX_LOCK:
        index = _INDEXES.get(pinned.set_hash)
        if index is not None:
            return index
        try:
            index = SiftsIndex(pinned.iter_jsonl("sifts", "residues.jsonl"), pinned.iter_jsonl("sifts", "segments.jsonl"))
        except SiftsFormatError as exc:
            raise rs.SnapshotUnavailable("snapshot_invalid") from exc
        while len(_INDEXES) >= _CACHE_SETS:
            _INDEXES.pop(next(iter(_INDEXES)))
        _INDEXES[pinned.set_hash] = index
        return index


def lookup_chain(pdb_id: str, chain_auth: str, *, pinned: rs.PinnedSet | None = None) -> SiftsChain | SiftsUnusable:
    """Decode one chain from ``pinned`` (default: the active set; SnapshotUnavailable when none is usable)."""
    return index_for_set(pinned or rs.pin_active_set()).lookup(pdb_id, chain_auth)


def sifts_chains_for_pdb(pdb_id: str, *, pinned: rs.PinnedSet | None = None) -> list[dict[str, Any]]:
    """UI prefill: ``[{chain_auth, accessions, reason_code}]`` for the entry ([] when it is not in the snapshot)."""
    return index_for_set(pinned or rs.pin_active_set()).chains_for_pdb(pdb_id)
