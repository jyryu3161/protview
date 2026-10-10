"""M27 kinase precedents: link a numbering map's chains to the kbase_kinase precedent records of a pinned precedent set
(spec .dryforge/spec.md 3.5, 5.3-5.6), and validate the result.

Pure logic over an already pinned set (``mw.precedent_snapshots``) and an already loaded ``residue_numbering_map@1``
content; the tool wrapper owns argument normalization, the admission order (spec 5.2), failure classes, the call key
and storage. Nothing here reads the network, kbase, the M15 / M26 reference folders or the event log. Read filters,
sorting and facets belong to ``mw.kinase_precedents_reads``.

Interface (consumed by the tool, the read routes and the report; keep it stable):

* ``pin_and_index(root=None) -> (PinnedPrecedentSet, PrecedentIndex)`` and ``precedent_index(pinned)``: decode the four
  files of one pinned set with ``precedent_constants.validate_dist_files`` / ``parse_pubmed`` (the import command's own
  rules, record hashes included) and index them (spec 3.5); one cached set (the most recent), keyed by set hash + the
  files' stat identity, successes only. Any format problem is ``SnapshotUnavailable("snapshot_invalid")``.
  ``clear_index_cache()``; ``capability(root=None)`` (the ``methods.kinase_precedents`` shape with records decoded);
  ``set_summary(index)`` (a copy of the set-wide summary, spec 5.6).
* ``numbering_map_shape_ok(content) -> bool``: the fields this module reads exist with their types (the tool's local
  shape check for ``numbering_map_invalid``).
* ``chain_rows(numbering_map, chains) -> list``: spec 5.3, selected chains in the map's order (``chains`` None = all;
  ``ValueError`` for an empty, repeated or unknown chain).
* ``build_kinase_precedents(*, pinned, index, numbering_map, numbering_map_handle, chains, include_flagged) -> dict``:
  the ``kinase_precedents@1`` content. Raises ``SnapshotUnavailable("snapshot_invalid")`` when an included record's
  ``content_hash`` no longer matches the record (checked on every call) and ``ResultTooLarge`` (a
  ``ResourceExceeded``; canonical JSON above ``MAX_RESULT_BYTES``; ``target_sizes`` and ``size_without_flagged`` say
  which chains to split or whether turning ``include_flagged`` off fits): nothing is truncated or returned.
  Same input + same set -> the same dict; no time or call ID.
* ``validated_result(obj) -> obj``: pure re-check of a new or stored result (exact key sets, closed sets, null vs []
  vs 0, counts recounted, order, record copies without the two removed paths, ``review_status``, integrity, fixed
  sentences); raises ``ResultInvalid`` (a ``ValueError`` whose message starts with ``"kinase_precedents@1"``).
* helpers shared with reads / reports: ``record_copy``, ``integrity_values``, ``target_counts``,
  ``precedent_set_record``, ``SnapshotUnavailable`` (= ``precedent_snapshots.SnapshotUnavailable``).

Precedent fields are kbase values copied as they are; the only values computed here are counts, word counts and the
integrity checks. A record whose target accession is null, or another accession, is never linked; names and
``effects[].target_ref`` are never matched. Not included, unresolved and missing bibliography stay ``null`` (never 0).
"""
from __future__ import annotations

import copy
import re
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from . import precedent_constants as K
from . import precedent_snapshots as ps

SnapshotUnavailable = ps.SnapshotUnavailable

_HANDLE = re.compile(r"obj://([A-Za-z0-9][A-Za-z0-9_-]{0,79})/([a-z][a-z0-9_]{0,79})/[0-9a-f]{64}\Z")
_RESULT_PDB_ID = re.compile(r"[0-9][A-Z0-9]{3}\Z")
STRUCTURE_KINDS = ("structure", "prepared_structure")
MAP_KIND = "residue_numbering_map"
MAP_SCHEMA = "residue_numbering_map@1"

TOP_KEYS = frozenset({"schema", "method_version", "numbering_map", "structure", "pdb_id", "include_flagged",
                      "record_format", "precedent_set", "chains", "targets", "bibliography", "set_summary", "counts",
                      "null_result", "limitations"})
PRECEDENT_SET_KEYS = frozenset({"set_hash", "imported_at", "importer_version", "kbase", "files",
                                "bibliography_snapshot"})
BIBLIOGRAPHY_SNAPSHOT_KEYS = frozenset({"snapshot_id", "date", "license", "origin", "file"})
CHAIN_KEYS = frozenset({"chain_auth", "total_residue_count", "mapped_residue_count", "cross_check",
                        "cross_check_absent_reason", "status", "reason", "accession", "accessions"})
TARGET_KEYS = frozenset({"accession", "chains", "status", "references", "excluded_flagged", "records", "counts"})
REFERENCE_RESULT_KEYS = ("ref_id", "gene", "klifs_name", "group", "family", "coverage", "content_hash")
ITEM_KEYS = frozenset({"file", "integrity", "record"})
INTEGRITY_KEYS = frozenset({"hash_verified", "observation_quote_words", "tradeoff_quote_words", "quotes_within_limit",
                            "locations_have_page"})
TARGET_COUNT_KEYS = frozenset({"moves", "moves_flagged", "variants", "tags", "resolution_basis"})
SET_SUMMARY_KEYS = frozenset({"records", "references", "unresolved_target_records", "unresolved_names",
                              "unresolved_names_total", "resolution_basis_counts"})
COUNTS_KEYS = frozenset({"chains", "linked_chains", "not_linked_chains", "targets", "records",
                         "excluded_moves_flagged"})
_FILE_PLAIN_KEYS = ("name", "path", "sha256", "bytes", "rows")


class ResultInvalid(ValueError):
    """A result that does not have the fixed ``kinase_precedents@1`` shape and values."""


class ResourceExceeded(Exception):
    """A result above a cap (refused, never truncated)."""

    def __init__(self, message: str, *, limit: int, actual: int | None = None) -> None:
        super().__init__(message)
        self.limit = limit
        self.actual = actual


class ResultTooLarge(ResourceExceeded):
    """The canonical JSON of the result is larger than ``MAX_RESULT_BYTES``.

    ``target_sizes``: per target ``{accession, chains, bytes}`` = the size of a request for that target's chains alone;
    ``size_without_flagged``: the size with ``include_flagged`` off (``None`` when it was already off).
    """

    def __init__(self, message: str, *, limit: int, actual: int, target_sizes: list[dict[str, Any]],
                 size_without_flagged: int | None) -> None:
        super().__init__(message, limit=limit, actual=actual)
        self.target_sizes = target_sizes
        self.size_without_flagged = size_without_flagged


# ------------------------------------------------------------------------------------------- set index (3.5)

@dataclass(frozen=True)
class PrecedentIndex:
    set_hash: str
    key: tuple
    by_uniprot: Mapping[str, tuple[tuple[str, dict[str, Any]], ...]]  # accession -> ((file, record), ...) move order
    references_by_uniprot: Mapping[str, tuple[dict[str, Any], ...]]  # accession -> references, ref_id ascending
    bibliography: Mapping[str, dict[str, Any]]                        # PMID -> {title, journal, year, doi, pmc}
    unresolved: Mapping[str, Any]   # {"records": {file: n}, "names": {name_as_written | None: {file: n}}}
    resolution_basis_counts: Mapping[str, dict[str, int]]  # basis -> {file: n}, records with a target accession
    summary: Mapping[str, Any]      # the set-wide ``set_summary`` (spec 5.6)


_INDEX_CACHE: dict[tuple, PrecedentIndex] = {}
_INDEX_LOCK = threading.Lock()


def clear_index_cache() -> None:
    with _INDEX_LOCK:
        _INDEX_CACHE.clear()


def _per_file() -> dict[str, int]:
    return {source: 0 for source in K.FILE_SOURCES}


def _summary(records: dict[str, int], references: int, unresolved: dict[str, Any],
             bases: dict[str, dict[str, int]]) -> dict[str, Any]:
    names = unresolved["names"]
    ordered = sorted(names, key=lambda name: (-sum(names[name].values()), name is not None, name or ""))
    return {
        "records": dict(records),
        "references": references,
        "unresolved_target_records": dict(unresolved["records"]),
        "unresolved_names": [{"name_as_written": name, **names[name]} for name in ordered[:K.MAX_UNRESOLVED_NAMES]],
        "unresolved_names_total": len(names),
        "resolution_basis_counts": [{"basis": basis, **bases[basis]} for basis in sorted(bases)],
    }


def precedent_index(pinned: ps.PinnedPrecedentSet) -> PrecedentIndex:
    """The decoded, indexed content of one pinned set (built once per set + file identity; one set kept)."""
    key = (pinned.set_hash, pinned.files_identity)
    with _INDEX_LOCK:
        cached = _INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    manifest = pinned.manifest
    try:
        dist = K.validate_dist_files(*(pinned.read_bytes(name) for name in K.DIST_FILE_NAMES))
        pubmed = K.parse_pubmed(pinned.read_bytes(manifest["bibliography"]["file"]["name"]))
        if dist.verification != manifest["verification"]:
            raise K.FormatError("the records differ from the manifest's verification counts")
    except (ValueError, RecursionError) as exc:
        raise ps.SnapshotUnavailable("snapshot_invalid") from exc
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    unresolved: dict[str, Any] = {"records": _per_file(), "names": {}}
    bases: dict[str, dict[str, int]] = {}
    for source, records in (("moves", dist.moves), ("moves_flagged", dist.moves_flagged)):
        for record in records:
            target = record["target"]
            if target["uniprot"] is None:
                unresolved["records"][source] += 1
                unresolved["names"].setdefault(target["name_as_written"], _per_file())[source] += 1
            else:
                grouped.setdefault(target["uniprot"], []).append((source, record))
                bases.setdefault(target["resolution_basis"], _per_file())[source] += 1
    references: dict[str, list[dict[str, Any]]] = {}
    for reference in dist.references:
        references.setdefault(reference["uniprot"], []).append(reference)
    records_total = {"moves": len(dist.moves), "moves_flagged": len(dist.moves_flagged)}
    index = PrecedentIndex(
        set_hash=pinned.set_hash, key=key,
        by_uniprot={acc: tuple(sorted(items, key=lambda item: K.move_number(item[1]["move_id"])))
                    for acc, items in grouped.items()},
        references_by_uniprot={acc: tuple(sorted(items, key=lambda r: r["ref_id"])) for acc, items in references.items()},
        bibliography=K.bibliography_entries(pubmed),
        unresolved=unresolved,
        resolution_basis_counts=bases,
        summary=_summary(records_total, len(dist.references), unresolved, bases),
    )
    with _INDEX_LOCK:
        _INDEX_CACHE.clear()
        _INDEX_CACHE[key] = index
    return index


def pin_and_index(root: Path | None = None) -> tuple[ps.PinnedPrecedentSet, PrecedentIndex]:
    pinned = ps.pin_active_set(root)
    return pinned, precedent_index(pinned)


def capability(root: Path | None = None) -> dict[str, Any]:
    """``methods.kinase_precedents`` with the records decoded: available, reason_code, reason, set_hash, sources."""
    try:
        pinned, _index = pin_and_index(root)
    except ps.SnapshotUnavailable as exc:
        return {"available": False, "reason_code": exc.reason_code, "reason": exc.reason, "set_hash": None,
                "sources": []}
    return {"available": True, "reason_code": None, "reason": None, "set_hash": pinned.set_hash,
            "sources": pinned.summary()}


def set_summary(index: PrecedentIndex) -> dict[str, Any]:
    return copy.deepcopy(dict(index.summary))


def precedent_set_record(pinned: ps.PinnedPrecedentSet) -> dict[str, Any]:
    """The result's ``precedent_set`` block (spec 5.6; file records without ``kbase_sha256``)."""
    manifest = pinned.manifest
    bibliography = manifest["bibliography"]
    return {"set_hash": pinned.set_hash, "imported_at": manifest["imported_at"],
            "importer_version": manifest["importer_version"], "kbase": manifest["kbase"],
            "files": [{k: entry[k] for k in _FILE_PLAIN_KEYS} for entry in manifest["files"]],
            "bibliography_snapshot": {"snapshot_id": bibliography["snapshot_id"], "date": bibliography["date"],
                                      "license": bibliography["license"], "origin": bibliography["origin"],
                                      "file": {k: bibliography["file"][k] for k in _FILE_PLAIN_KEYS}}}


# ------------------------------------------------------------------------------------------- numbering map (5.2/5.3)

def _count(value: Any) -> bool:
    return type(value) is int and value >= 0


def numbering_map_shape_ok(content: Any) -> bool:
    """The fields the linking rules read exist with their types; anything else is the map's own record."""
    if type(content) is not dict or content.get("schema") != MAP_SCHEMA:
        return False
    structure = content.get("structure")
    if (type(structure) is not dict or type(structure.get("handle")) is not str
            or type(structure.get("structure_kind")) is not str or type(structure.get("model_number")) is not int):
        return False
    if "pdb_id" not in content or not (content["pdb_id"] is None or type(content["pdb_id"]) is str):
        return False
    chains, rows = content.get("chains"), content.get("rows")
    if type(chains) is not list or type(rows) is not list:
        return False
    names = []
    for chain in chains:
        if type(chain) is not dict or type(chain.get("chain_auth")) is not str or not chain["chain_auth"]:
            return False
        counts = chain.get("counts")
        if type(counts) is not dict or not all(_count(counts.get(k)) for k in ("mapped", "unmapped", "conflict")):
            return False
        if type(chain.get("cross_check")) is not bool or "cross_check_absent_reason" not in chain:
            return False
        if not (chain["cross_check_absent_reason"] is None or type(chain["cross_check_absent_reason"]) is str):
            return False
        names.append(chain["chain_auth"])
    if len(set(names)) != len(names):
        return False
    for row in rows:
        if (type(row) is not dict or type(row.get("residue")) is not dict
                or type(row["residue"].get("chain_auth")) is not str or type(row.get("status")) is not str
                or "uniprot_accession" not in row):
            return False
        accession = row["uniprot_accession"]
        if not (accession is None or type(accession) is str):
            return False
        if row["status"] == "mapped" and not (type(accession) is str and accession):
            return False
    return True


def chain_rows(numbering_map: Mapping[str, Any], chains: Sequence[str] | None) -> list[dict[str, Any]]:
    """Spec 5.3 for the selected chains (``None`` = all), in the map's ``chains[]`` order."""
    names = [chain["chain_auth"] for chain in numbering_map["chains"]]
    if chains is not None and (not chains or len(set(chains)) != len(chains)
                               or any(name not in names for name in chains)):
        raise ValueError("chains must be distinct chain_auth values of the numbering map")
    selected = set(names if chains is None else chains)
    by_chain: dict[str, set[str]] = {name: set() for name in selected}
    for row in numbering_map["rows"]:
        name = row["residue"]["chain_auth"]
        if name in by_chain and row["status"] == "mapped":
            by_chain[name].add(row["uniprot_accession"])
    out = []
    for chain in numbering_map["chains"]:
        name = chain["chain_auth"]
        if name not in selected:
            continue
        accessions = sorted(by_chain[name])
        if len(accessions) == 1:
            status, reason, accession = "linked", None, accessions[0]
        elif not accessions:
            status, reason, accession = "not_linked", "no_mapped_residues", None
        else:
            status, reason, accession = "not_linked", "multiple_accessions", None
        counts = chain["counts"]
        out.append({"chain_auth": name,
                    "total_residue_count": counts["mapped"] + counts["unmapped"] + counts["conflict"],
                    "mapped_residue_count": counts["mapped"], "cross_check": chain["cross_check"],
                    "cross_check_absent_reason": chain["cross_check_absent_reason"], "status": status,
                    "reason": reason, "accession": accession, "accessions": accessions})
    return out


# ------------------------------------------------------------------------------------------- records (5.4/5.5)

def record_copy(record: Mapping[str, Any]) -> dict[str, Any]:
    """The stored copy: the record minus exactly ``source.parser`` and ``checks.cross_parser_numbers.measurements``
    (``content_hash`` stays the original record's hash; it is not recomputed)."""
    out = copy.deepcopy(dict(record))
    for path in K.REMOVED_PATHS:
        node = out
        for key in path[:-1]:
            node = node[key]
        node.pop(path[-1], None)
    return out


def integrity_values(record: Mapping[str, Any]) -> dict[str, Any]:
    """Word counts (``str.split()``), the 25-word check and the page check of one record (no hash)."""
    observation = len(record["observation"]["quote"].split())
    tradeoffs = [None if t["quote"] is None else len(t["quote"].split()) for t in record["tradeoffs"]]
    words = [observation, *(w for w in tradeoffs if w is not None)]
    return {"observation_quote_words": observation, "tradeoff_quote_words": tradeoffs,
            "quotes_within_limit": all(w <= K.MAX_QUOTE_WORDS for w in words),
            "locations_have_page": all(type(loc["page"]) is int and loc["page"] >= 1
                                       for loc in record["source"]["locations"])}


def _tally(values: Sequence[str], label: str) -> list[dict[str, Any]]:
    counter = Counter(values)
    return [{label: value, "count": counter[value]} for value in sorted(counter)]


def target_counts(records: Sequence[Mapping[str, Any]], include_flagged: bool) -> dict[str, Any]:
    """``targets[].counts`` of the result elements ``records`` (a record counts once per distinct tag term)."""
    copies = [item["record"] for item in records]
    flagged = sum(1 for item in records if item["file"] == "moves_flagged")
    return {
        "moves": sum(1 for item in records if item["file"] == "moves"),
        "moves_flagged": flagged if include_flagged else None,
        "variants": _tally([r["target"]["variant"] for r in copies], "variant"),
        "tags": {axis: _tally([term for r in copies for term in set(r["tags"][axis])], "term") for axis in K.TAG_AXES},
        "resolution_basis": _tally([r["target"]["resolution_basis"] for r in copies], "basis"),
    }


def _item(source: str, original: dict[str, Any]) -> dict[str, Any]:
    if not K.hash_matches(original):        # the original record, re-hashed on every call (spec 5.5)
        clear_index_cache()
        raise ps.SnapshotUnavailable("snapshot_invalid")
    return {"file": source, "integrity": {"hash_verified": True, **integrity_values(original)},
            "record": record_copy(original)}


def _target(index: PrecedentIndex, accession: str, chains: list[str], include_flagged: bool) -> dict[str, Any]:
    entries = index.by_uniprot.get(accession, ())
    records = [_item(source, record) for source, record in entries if source == "moves" or include_flagged]
    references = [{k: ref[k] for k in REFERENCE_RESULT_KEYS} for ref in index.references_by_uniprot.get(accession, ())]
    if records:
        status = "precedents_found"
    elif references:
        status = "none_in_included_files"
    else:
        status = "not_in_kbase_references"
    excluded = None if include_flagged else sum(1 for source, _record in entries if source == "moves_flagged")
    return {"accession": accession, "chains": chains, "status": status, "references": copy.deepcopy(references),
            "excluded_flagged": excluded, "records": records, "counts": target_counts(records, include_flagged)}


def _counts(chains: Sequence[Mapping[str, Any]], targets: Sequence[Mapping[str, Any]],
            include_flagged: bool) -> dict[str, Any]:
    linked = sum(1 for chain in chains if chain["status"] == "linked")
    return {
        "chains": len(chains),
        "linked_chains": linked,
        "not_linked_chains": len(chains) - linked,
        "targets": len(targets),
        "records": {"moves": sum(t["counts"]["moves"] for t in targets),
                    "moves_flagged": sum(t["counts"]["moves_flagged"] for t in targets) if include_flagged else None},
        "excluded_moves_flagged": None if include_flagged else sum(t["excluded_flagged"] for t in targets),
    }


def _record_pmids(targets: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted({item["record"]["source"]["pmid"] for t in targets for item in t["records"]})


def _assemble(pinned: ps.PinnedPrecedentSet, index: PrecedentIndex, numbering_map: Mapping[str, Any],
              numbering_map_handle: str, chains: Sequence[str] | None, include_flagged: bool) -> dict[str, Any]:
    chain_list = chain_rows(numbering_map, chains)
    groups: dict[str, list[str]] = {}
    for chain in chain_list:
        if chain["status"] == "linked":
            groups.setdefault(chain["accession"], []).append(chain["chain_auth"])
    targets = [_target(index, accession, sorted(groups[accession]), include_flagged) for accession in sorted(groups)]
    structure = numbering_map["structure"]
    return {
        "schema": K.SCHEMA,
        "method_version": K.METHOD_VERSION,
        "numbering_map": {"handle": numbering_map_handle},
        "structure": {"handle": structure["handle"], "structure_kind": structure["structure_kind"],
                      "model_number": structure["model_number"]},
        "pdb_id": numbering_map["pdb_id"],
        "include_flagged": include_flagged,
        "record_format": K.RECORD_FORMAT,
        "precedent_set": precedent_set_record(pinned),
        "chains": chain_list,
        "targets": targets,
        "bibliography": {pmid: copy.deepcopy(index.bibliography.get(pmid)) for pmid in _record_pmids(targets)},
        "set_summary": set_summary(index),
        "counts": _counts(chain_list, targets, include_flagged),
        "null_result": all(not t["records"] for t in targets),
        "limitations": list(K.LIMITATIONS),
    }


def _size(obj: Any) -> int:
    return len(K.canonical_json(obj))


def _too_large(size: int, result: Mapping[str, Any], rebuild: Any, chains: Sequence[str] | None,
               include_flagged: bool) -> ResultTooLarge:
    limit = K.MAX_RESULT_BYTES
    sizes = [{"accession": t["accession"], "chains": list(t["chains"]),
              "bytes": _size(rebuild(t["chains"], include_flagged))} for t in result["targets"]]
    without = _size(rebuild(chains, False)) if include_flagged else None
    parts = [f"결과 정규 JSON {size} B가 상한 {limit} B를 넘어 저장하지 않았습니다(자르지 않음)."]
    if without is not None:
        parts.append(f"include_flagged를 끄면 {without} B입니다({'상한 안' if without <= limit else '여전히 상한 초과'}).")
    parts.append("표적별 단독 요청 크기: " + "; ".join(
        f"{s['accession']}(체인 {', '.join(s['chains'])}) {s['bytes']} B({'상한 안' if s['bytes'] <= limit else '상한 초과'})"
        for s in sizes) + ".")
    parts.append("체인을 나눠 요청하거나 include_flagged를 끄십시오. The result is above the 1 MiB cap; request fewer "
                 "chains or turn include_flagged off.")
    return ResultTooLarge(" ".join(parts), limit=limit, actual=size, target_sizes=sizes, size_without_flagged=without)


def build_kinase_precedents(*, pinned: ps.PinnedPrecedentSet, index: PrecedentIndex, numbering_map: Mapping[str, Any],
                            numbering_map_handle: str, chains: Sequence[str] | None,
                            include_flagged: bool) -> dict[str, Any]:
    """The ``kinase_precedents@1`` content (deterministic for the same inputs and set; no time or call ID)."""
    if index.set_hash != pinned.set_hash:
        raise ValueError("the index belongs to another pinned set")
    if type(include_flagged) is not bool:
        raise ValueError("include_flagged must be a boolean")

    def rebuild(selected: Sequence[str] | None, flagged: bool) -> dict[str, Any]:
        return _assemble(pinned, index, numbering_map, numbering_map_handle, selected, flagged)

    result = rebuild(chains, include_flagged)
    size = _size(result)
    if size > K.MAX_RESULT_BYTES:
        raise _too_large(size, result, rebuild, chains, include_flagged)
    return result


# ------------------------------------------------------------------------------------------- validation

def _fail(message: str) -> None:
    raise ResultInvalid(f"kinase_precedents@1: {message}")


def _same(a: Any, b: Any) -> bool:
    """Equal with exact JSON types (``2`` vs ``2.0``, ``1`` vs ``true`` differ)."""
    return K.canonical_json(a) == K.canonical_json(b)


def _keys(obj: Any, keys: frozenset, where: str) -> None:
    if type(obj) is not dict or set(obj) != keys:
        _fail(f"{where}: keys differ")


def _strictly_ascending(values: Sequence[Any]) -> bool:
    return all(a < b for a, b in pairwise(values))


def _validate_precedent_set(value: Any) -> None:
    _keys(value, PRECEDENT_SET_KEYS, "precedent_set")
    if (type(value["set_hash"]) is not str or not re.fullmatch(K.HEX64_PATTERN, value["set_hash"])
            or type(value["imported_at"]) is not str or not re.fullmatch(K.IMPORTED_AT_PATTERN, value["imported_at"])
            or value["importer_version"] != K.IMPORTER_VERSION):
        _fail("precedent_set: header")
    K.validate_kbase_block(value["kbase"])
    files = value["files"]
    if type(files) is not list or len(files) != len(K.DIST_FILE_NAMES):
        _fail("precedent_set.files: expected the three dist files")
    for entry, name in zip(files, K.DIST_FILE_NAMES):
        K.validate_file_entry(entry, name, False)
    snapshot = value["bibliography_snapshot"]
    _keys(snapshot, BIBLIOGRAPHY_SNAPSHOT_KEYS, "precedent_set.bibliography_snapshot")
    if (type(snapshot["snapshot_id"]) is not str or not snapshot["snapshot_id"]
            or type(snapshot["date"]) is not str or not re.fullmatch(K.DATE_PATTERN, snapshot["date"])
            or type(snapshot["license"]) is not str or not snapshot["license"]
            or snapshot["origin"] != K.BIBLIOGRAPHY_ORIGIN):
        _fail("precedent_set.bibliography_snapshot: values")
    K.validate_file_entry(snapshot["file"], K.pubmed_file_name(snapshot["date"]), False)


def _validate_chains(chains: Any) -> dict[str, list[str]]:
    """The chain rows; returns accession -> linked chain names (ascending)."""
    if type(chains) is not list or not chains:
        _fail("chains: expected a non-empty list")
    names = [c.get("chain_auth") if type(c) is dict else None for c in chains]
    if len(set(names)) != len(names):
        _fail("chains: duplicate chain_auth")
    groups: dict[str, list[str]] = {}
    for chain in chains:
        _keys(chain, CHAIN_KEYS, "chain")
        name, accessions = chain["chain_auth"], chain["accessions"]
        total, mapped = chain["total_residue_count"], chain["mapped_residue_count"]
        if type(name) is not str or not name:
            _fail("chain_auth")
        if not _count(total) or not _count(mapped) or mapped > total:
            _fail(f"chain {name}: residue counts")
        if type(chain["cross_check"]) is not bool or not (chain["cross_check_absent_reason"] is None
                                                          or type(chain["cross_check_absent_reason"]) is str):
            _fail(f"chain {name}: cross check")
        if (type(accessions) is not list or not all(type(a) is str and a for a in accessions)
                or not _strictly_ascending(accessions)):
            _fail(f"chain {name}: accessions must be distinct strings in ascending order")
        if (mapped == 0) != (accessions == []):
            _fail(f"chain {name}: mapped residues and accessions disagree")
        state = (chain["status"], chain["reason"], chain["accession"])
        if len(accessions) == 1:
            expected = ("linked", None, accessions[0])
        elif not accessions:
            expected = ("not_linked", "no_mapped_residues", None)
        else:
            expected = ("not_linked", "multiple_accessions", None)
        if state != expected:
            _fail(f"chain {name}: status/reason/accession differ from the accessions")
        if chain["status"] == "linked":
            groups.setdefault(chain["accession"], []).append(name)
    return {accession: sorted(found) for accession, found in groups.items()}


def _validate_reference_rows(references: Any, where: str) -> None:
    if type(references) is not list:
        _fail(f"{where}.references: expected a list")
    for reference in references:
        _keys(reference, frozenset(REFERENCE_RESULT_KEYS), f"{where}.references[]")
        if type(reference["ref_id"]) is not str or not reference["ref_id"]:
            _fail(f"{where}.references[]: ref_id")
        content_hash = reference["content_hash"]
        if content_hash is not None and (type(content_hash) is not str
                                         or not re.fullmatch(K.RECORD_HASH_PATTERN, content_hash)):
            _fail(f"{where}.references[]: content_hash")
    if not _strictly_ascending([r["ref_id"] for r in references]):
        _fail(f"{where}.references: ref_id must ascend")


def _validate_item(item: Any, accession: str, include_flagged: bool, where: str) -> None:
    _keys(item, ITEM_KEYS, where)
    if item["file"] not in K.FILE_SOURCES or (not include_flagged and item["file"] != "moves"):
        _fail(f"{where}: file")
    record = item["record"]
    K.validate_move(record)
    if "parser" in record["source"] or "measurements" in record["checks"]["cross_parser_numbers"]:
        _fail(f"{where}: a removed path is present in the record copy")
    if record["target"]["uniprot"] != accession:
        _fail(f"{where}: the record's target accession is not the target's")
    _keys(item["integrity"], INTEGRITY_KEYS, f"{where}.integrity")
    if not _same(item["integrity"], {"hash_verified": True, **integrity_values(record)}):
        _fail(f"{where}: integrity values differ from the record (hash_verified is always true)")


def _validate_targets(targets: Any, groups: Mapping[str, list[str]], include_flagged: bool) -> None:
    if type(targets) is not list:
        _fail("targets: expected a list")
    if [t.get("accession") if type(t) is dict else None for t in targets] != sorted(groups):
        _fail("targets: one per linked accession, ascending")
    seen: set[str] = set()
    for target in targets:
        _keys(target, TARGET_KEYS, "target")
        accession = target["accession"]
        where = f"target {accession}"
        if not _same(target["chains"], groups[accession]):
            _fail(f"{where}: chains differ from the linked chains")
        _validate_reference_rows(target["references"], where)
        excluded = target["excluded_flagged"]
        if (excluded is not None) if include_flagged else not _count(excluded):
            _fail(f"{where}: excluded_flagged is null when included and an integer otherwise")
        records = target["records"]
        if type(records) is not list:
            _fail(f"{where}.records: expected a list")
        for item in records:
            _validate_item(item, accession, include_flagged, f"{where}.records[]")
            move_id = item["record"]["move_id"]
            if move_id in seen:
                _fail(f"{where}: move_id {move_id} repeats")
            seen.add(move_id)
        if not _strictly_ascending([K.move_number(item["record"]["move_id"]) for item in records]):
            _fail(f"{where}.records: move_id order")
        status = ("precedents_found" if records else
                  "none_in_included_files" if target["references"] else "not_in_kbase_references")
        if target["status"] != status:
            _fail(f"{where}: status")
        _keys(target["counts"], TARGET_COUNT_KEYS, f"{where}.counts")
        if not _same(target["counts"], target_counts(records, include_flagged)):
            _fail(f"{where}: counts differ from the records")


def _validate_bibliography(bibliography: Any, targets: Sequence[Mapping[str, Any]]) -> None:
    if type(bibliography) is not dict or list(bibliography) != _record_pmids(targets):
        _fail("bibliography: exactly the records' PMIDs, ascending")
    for pmid, value in bibliography.items():
        if value is None:
            continue
        _keys(value, frozenset(K.BIBLIOGRAPHY_FIELDS), f"bibliography {pmid}")
        if not all(v is None or type(v) is str for v in value.values()):
            _fail(f"bibliography {pmid}: values are strings or null")


def _pair(value: Any, where: str) -> dict[str, int]:
    _keys(value, frozenset(K.FILE_SOURCES), where)
    if not all(_count(v) for v in value.values()):
        _fail(f"{where}: counts")
    return value


def _validate_set_summary(summary: Any) -> None:
    _keys(summary, SET_SUMMARY_KEYS, "set_summary")
    records = _pair(summary["records"], "set_summary.records")
    unresolved = _pair(summary["unresolved_target_records"], "set_summary.unresolved_target_records")
    if not _count(summary["references"]) or any(unresolved[f] > records[f] for f in K.FILE_SOURCES):
        _fail("set_summary: references / unresolved counts")
    names = summary["unresolved_names"]
    if type(names) is not list or len(names) > K.MAX_UNRESOLVED_NAMES:
        _fail("set_summary.unresolved_names: list within the cap")
    for entry in names:
        _keys(entry, frozenset({"name_as_written", *K.FILE_SOURCES}), "set_summary.unresolved_names[]")
        _pair({f: entry[f] for f in K.FILE_SOURCES}, "set_summary.unresolved_names[]")
        if not (entry["name_as_written"] is None or type(entry["name_as_written"]) is str):
            _fail("set_summary.unresolved_names[]: name")
        if entry["moves"] + entry["moves_flagged"] < 1:
            _fail("set_summary.unresolved_names[]: a listed name has a record")
    order = [(-(e["moves"] + e["moves_flagged"]), e["name_as_written"] is not None, e["name_as_written"] or "")
             for e in names]
    if len({e["name_as_written"] for e in names}) != len(names) or not _strictly_ascending(order):
        _fail("set_summary.unresolved_names: distinct names, most records first, then name (null first)")
    total = summary["unresolved_names_total"]
    if not _count(total) or len(names) != min(total, K.MAX_UNRESOLVED_NAMES):
        _fail("set_summary.unresolved_names_total")
    listed = {f: sum(e[f] for e in names) for f in K.FILE_SOURCES}
    if total == len(names):
        if listed != unresolved:
            _fail("set_summary: every unresolved record is in a listed name")
    elif sum(listed.values()) + (total - len(names)) > sum(unresolved.values()):
        _fail("set_summary: listed names exceed the unresolved records")
    bases = summary["resolution_basis_counts"]
    if type(bases) is not list:
        _fail("set_summary.resolution_basis_counts: expected a list")
    for entry in bases:
        _keys(entry, frozenset({"basis", *K.FILE_SOURCES}), "set_summary.resolution_basis_counts[]")
        _pair({f: entry[f] for f in K.FILE_SOURCES}, "set_summary.resolution_basis_counts[]")
        if entry["basis"] not in K.RESOLUTION_BASES or entry["moves"] + entry["moves_flagged"] < 1:
            _fail("set_summary.resolution_basis_counts[]: basis")
    if not _strictly_ascending([e["basis"] for e in bases]):
        _fail("set_summary.resolution_basis_counts: basis must ascend")
    for f in K.FILE_SOURCES:
        if sum(e[f] for e in bases) + unresolved[f] != records[f]:
            _fail("set_summary: resolved + unresolved records differ from the set's records")


def _validate(obj: Any) -> None:
    _keys(obj, TOP_KEYS, "result")
    if (obj["schema"] != K.SCHEMA or obj["method_version"] != K.METHOD_VERSION
            or obj["record_format"] != K.RECORD_FORMAT):
        _fail("schema / method_version / record_format")
    include_flagged = obj["include_flagged"]
    if type(include_flagged) is not bool:
        _fail("include_flagged")
    structure = obj["structure"]
    _keys(structure, frozenset({"handle", "structure_kind", "model_number"}), "structure")
    match = _HANDLE.fullmatch(structure["handle"]) if type(structure["handle"]) is str else None
    if (match is None or structure["structure_kind"] not in STRUCTURE_KINDS
            or match.group(2) != structure["structure_kind"] or type(structure["model_number"]) is not int):
        _fail("structure")
    nmap = obj["numbering_map"]
    _keys(nmap, frozenset({"handle"}), "numbering_map")
    found = _HANDLE.fullmatch(nmap["handle"]) if type(nmap["handle"]) is str else None
    if found is None or found.group(2) != MAP_KIND or found.group(1) != match.group(1):
        _fail("numbering_map: a residue_numbering_map handle of the structure's run")
    pdb_id = obj["pdb_id"]
    if pdb_id is not None and (type(pdb_id) is not str or not _RESULT_PDB_ID.fullmatch(pdb_id)):
        _fail("pdb_id")
    _validate_precedent_set(obj["precedent_set"])
    groups = _validate_chains(obj["chains"])
    _validate_targets(obj["targets"], groups, include_flagged)
    _validate_bibliography(obj["bibliography"], obj["targets"])
    _validate_set_summary(obj["set_summary"])
    _keys(obj["counts"], COUNTS_KEYS, "counts")
    if not _same(obj["counts"], _counts(obj["chains"], obj["targets"], include_flagged)):
        _fail("counts differ from the chains and targets")
    if obj["null_result"] is not all(not t["records"] for t in obj["targets"]):
        _fail("null_result")
    if not _same(obj["limitations"], list(K.LIMITATIONS)):
        _fail("limitations must be KP1-KP6 verbatim and in order")


def validated_result(obj: Any) -> Any:
    """``obj`` when it is a valid ``kinase_precedents@1`` content; ``ResultInvalid`` otherwise (pure)."""
    try:
        _validate(obj)
    except ResultInvalid:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, RecursionError) as exc:
        raise ResultInvalid(f"kinase_precedents@1: malformed result: {exc}") from exc
    return obj
