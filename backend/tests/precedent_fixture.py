"""Test utility: LABELLED SYNTHETIC M27 precedent records and precedent reference sets (spec 3.1-3.4).

Everything here is SYNTHETIC (합성): made-up accessions (``P0SYN1`` ...), PMIDs (``9000000n``), move IDs, texts that say
"SYNTHETIC fixture ...". No real kbase_kinase record, quote, observation or bibliography fragment is used; field names
and value types follow spec 3.4 and the structure notes of ``docs/qa/m27-precedents-20261010/preflight.md``.

Public API (also used by the import-command, tool/read and QA tests of later tasks):

* ``make_move(move_id, **options)`` -> a valid kbase-shaped move record (21 top-level keys, ``content_hash`` set).
  Keyword options name the usual fields (``uniprot``, ``resolution_basis``, ``name_as_written``, ``variant``,
  ``pmid``, ``site`` / ``goal`` / ``tactic``, ``quote``, ``observation_text``, ``tradeoffs``, ``locations``,
  ``effects``, ``structure_links``); any other keyword replaces a top-level key. The hash is computed last.
* ``make_reference(ref_id, uniprot, *, hashed=True, **fields)``, ``make_pubmed_row(pmid, **options)``.
* ``set_path(record, "a.b.0.c", value)`` (no rehash), ``rehash(record)`` (recompute ``content_hash``).
* ``jsonl(records)`` -> kbase-style JSONL bytes (``json.dumps`` default separators, NOT canonical, one record and
  ``"\\n"`` per line): the server must hash the parsed record, never the line bytes.
* ``t2_bytes()`` / ``t2_records()``: the committed T2 synthetic files (``fixtures/precedent/t2/``).
* ``build_set(root, ...)`` -> set hash: writes ``sets/<hash>/files/...`` + ``manifest.json`` and (by default)
  ``active.json`` in the importer's layout, using only ``mw.precedent_constants`` helpers (``file_record``,
  ``validate_manifest``, ``manifest_bytes``, ``set_hash_of``, ``pointer_bytes``) so the fixture and the import
  command follow one manifest rule. ``activate(root, set_hash)`` moves the pointer.

This is a FIXTURE set, not an import: no kbase folder, git or network is touched.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from mw import precedent_constants as K

T2 = Path(__file__).resolve().parent / "fixtures" / "precedent" / "t2"
T2_FILES = {"moves": T2 / "dist" / "moves.jsonl", "moves_flagged": T2 / "dist" / "moves_flagged.jsonl",
            "references": T2 / "dist" / "references.jsonl", "pubmed": T2 / "pubmed" / "documents.jsonl"}
IMPORTED_AT = "2026-10-10T00:00:00Z"
PUBMED_DATE = "2026-10-01"
KBASE = {
    "commit": "c0de" * 10,
    "dist_commit": "d157" * 10,
    "dist_commit_date": "2026-10-01T09:00:00+09:00",
    "dirty": False,
    "kb_version": "kbv1:synthetic-fixture",
    "schema_version": K.KBASE_PINS["schema_version"],
    "effect_rules_version": K.KBASE_PINS["effect_rules_version"],
    "vocab_version": K.KBASE_PINS["vocab_version"],
    "source_snapshots": ["SNAP-synthetic-fixture-2026-10-01"],
    "origin": K.KBASE_ORIGIN,
}
BIBLIOGRAPHY = {"snapshot_id": "SNAP-pubmed-synthetic-2026-10-01", "license": "synthetic-fixture-license"}

_LOCATION = {"kind": "table", "page": 3, "table_index": 1, "row": 2, "figure_id": None, "panel": None, "bbox": None}


def default_effect(**fields: Any) -> dict[str, Any]:
    """One SYNTHETIC effect with the 15 keys of spec 3.4 (any keyword replaces a key)."""
    effect = {
        "metric": "IC50", "assay": "SYNTHETIC fixture assay", "assay_context": "synthetic fixture context",
        "target_ref": "SYN-KINASE", "target_role": "on_target",
        "before": {"qualifier": "=", "value": 100, "unit": "nM"}, "after": {"qualifier": "=", "value": 10, "unit": "nM"},
        "direction": "improved", "direction_basis": "numeric", "magnitude_bucket": "large", "comparable": True,
        "comparability_reason": None, "fold_change": 10.0, "chembl_crosscheck": None,
        "evidence": {"synthetic": "fixture evidence"},
    }
    effect.update(fields)
    return effect


def default_checks() -> dict[str, Any]:
    """The ten check names, all ``pass``; ``cross_parser_numbers`` carries the ``measurements`` list."""
    checks: dict[str, Any] = {name: {"status": "pass"} for name in K.CHECK_NAMES}
    checks["cross_parser_numbers"] = {"status": "pass", "match_unit_unverified_count": 0,
                                      "measurements": [{"synthetic": "fixture measurement", "value": 1}]}
    return checks


def rehash(record: dict[str, Any]) -> dict[str, Any]:
    record["content_hash"] = K.content_hash(record)
    return record


def set_path(record: Any, dotted: str, value: Any) -> None:
    """Set ``record[a][b][0][c] = value`` for ``"a.b.0.c"`` (integer parts index lists). No rehash."""
    parts = dotted.split(".")
    node = record
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


def make_move(move_id: str = "MOVE-0001", *, uniprot: str | None = "P0SYN1", resolution_basis: str = "gene",
              name_as_written: str | None = "SYN-KINASE", variant: str = "not_reported", pmid: str = "90000001",
              site: Iterable[str] = ("bp_I_A",), goal: Iterable[str] = ("potency",),
              tactic: Iterable[str] = ("add_hydrophobic_bulk",), quote: str = "SYNTHETIC fixture quote words",
              observation_text: str = "합성 SYNTHETIC fixture observation.",
              tradeoffs: list[dict[str, Any]] | None = None, locations: list[dict[str, Any]] | None = None,
              effects: list[dict[str, Any]] | None = None, structure_links: list[dict[str, Any]] | None = None,
              **fields: Any) -> dict[str, Any]:
    """A valid SYNTHETIC move record (spec 3.4); ``fields`` replace top-level keys; ``content_hash`` computed last."""
    record = {
        "review_status": "unreviewed",
        "schema_version": 1,
        "move_id": move_id,
        "source": {"pmid": pmid, "locations": copy.deepcopy(locations) if locations is not None else [dict(_LOCATION)],
                   "parser": {"synthetic_option": "fixture parser option"}},
        "target": {"gene": "SYNG" if uniprot is not None else None, "uniprot": uniprot,
                   "name_as_written": name_as_written, "resolution_basis": resolution_basis, "candidates": [],
                   "variant": variant},
        "structure_ref": None,
        "structure_link_reason": None,
        "structure_ref_from": None,
        "structure_links": copy.deepcopy(structure_links) if structure_links is not None else [],
        "interactions": [],
        "observation": {"text": observation_text, "quote": quote, "quote_truncated": False,
                        "evidence": {"synthetic": "fixture evidence"}},
        "change": {"description": "합성 SYNTHETIC fixture change.", "from_compound": "SYN-cpd-from",
                   "to_compound": "SYN-cpd-to", "smiles_from": None, "smiles_to": None},
        "effects": copy.deepcopy(effects) if effects is not None else [default_effect()],
        "tradeoffs": copy.deepcopy(tradeoffs) if tradeoffs is not None else [],
        "mutations": [],
        "tags": {"site": list(site), "goal": list(goal), "tactic": list(tactic)},
        "proposed_tags": [],
        "figures": [],
        "checks": default_checks(),
        "extraction": {"model": "synthetic-fixture-model", "provider": "synthetic", "prompt_version": "fixture-1",
                       "run_at": "2026-10-01T00:00:00Z", "notes": "SYNTHETIC nested key kept as is"},
    }
    record.update(copy.deepcopy(fields))
    record.pop("content_hash", None)
    return rehash(record)


def make_reference(ref_id: str, uniprot: str, *, hashed: bool = True, **fields: Any) -> dict[str, Any]:
    """A valid SYNTHETIC reference record (spec 3.4); ``hashed=False`` leaves ``content_hash`` null."""
    record = {
        "ref_id": ref_id, "gene": f"SYNG-{ref_id[-1]}", "klifs_name": f"SYN-{ref_id[-1]}", "uniprot": uniprot,
        "group": "SYNGROUP", "family": "SYNFAMILY", "coverage": "partial", "review_status": "unreviewed",
        "schema_version": 1, "source_snapshots": ["SNAP-synthetic-fixture-2026-10-01"],
        "domain": {"synthetic": "합성 fixture domain"},
    }
    record.update(copy.deepcopy(fields))
    record["content_hash"] = None
    if hashed:
        record["content_hash"] = K.content_hash(record)
    return record


def make_pubmed_row(pmid: str, *, status: str = "ok", data_pmid: str | None = None,
                    title: str | None = None, journal: str | None = "Synthetic Fixture Journal",
                    year: str | None = "2020", doi: str | None = None, pmc: str | None = None) -> dict[str, Any]:
    """A SYNTHETIC ``pubmed/<date>/documents.jsonl`` row (keys ``data``, ``id``, ``pmid``, ``status``)."""
    return {"data": {"doi": doi, "journal": journal, "pmc": pmc, "pmid": data_pmid if data_pmid is not None else pmid,
                     "title": title if title is not None else f"합성 SYNTHETIC fixture title {pmid}", "year": year},
            "id": pmid, "pmid": pmid, "status": status}


def jsonl(records: Iterable[Mapping[str, Any]]) -> bytes:
    """kbase-style JSONL bytes: ``json.dumps`` with its default separators (not canonical) + ``"\\n"``."""
    return b"".join(json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n" for record in records)


def t2_bytes() -> dict[str, bytes]:
    """The committed T2 synthetic file bytes: ``moves``, ``moves_flagged``, ``references``, ``pubmed``."""
    return {key: path.read_bytes() for key, path in T2_FILES.items()}


def t2_records() -> dict[str, list[dict[str, Any]]]:
    """The committed T2 synthetic records (fresh parsed copies)."""
    return {key: [json.loads(line) for line in data.splitlines()] for key, data in t2_bytes().items()}


def _rows(data: bytes) -> list[Any]:
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def activate(root: Path, set_hash: str) -> None:
    tmp = Path(root) / "active.json.tmp"
    tmp.write_bytes(K.pointer_bytes(set_hash))
    tmp.replace(Path(root) / K.ACTIVE_NAME)


def build_set(root: Path, *, moves: list[dict[str, Any]] | None = None,
              moves_flagged: list[dict[str, Any]] | None = None, references: list[dict[str, Any]] | None = None,
              pubmed: list[dict[str, Any]] | None = None, file_bytes: dict[str, bytes] | None = None,
              kbase: dict[str, Any] | None = None, pubmed_date: str = PUBMED_DATE,
              imported_at: str = IMPORTED_AT, activate_set: bool = True,
              manifest_patch: Callable[[dict[str, Any]], None] | None = None, validate: bool = True) -> str:
    """Write one FIXTURE set under ``root`` and return its set hash.

    Records default to the committed T2 files. ``file_bytes`` (keys ``moves`` / ``moves_flagged`` / ``references`` /
    ``pubmed``) replaces a file's bytes as an importer that wrote those bytes would (the manifest records their hash,
    size and line count). ``verification`` records what a successful import counts (every move line, references with
    a hash / without). ``manifest_patch`` edits the manifest before hashing (pass ``validate=False`` when the patch
    makes it invalid). ``imported_at`` makes two builds of the same records different sets.
    """
    root = Path(root)
    given = {"moves": moves, "moves_flagged": moves_flagged, "references": references, "pubmed": pubmed}
    defaults = t2_bytes()
    data = {key: (jsonl(value) if value is not None else defaults[key]) for key, value in given.items()}
    data.update(file_bytes or {})
    sets = root / K.SETS_DIR
    sets.mkdir(parents=True, exist_ok=True)
    staging = sets / f".staging-{K.sha256_hex(imported_at.encode())[:12]}"
    names = dict(zip(("moves", "moves_flagged", "references"), K.DIST_FILE_NAMES))
    names["pubmed"] = K.pubmed_file_name(pubmed_date)
    records = {}
    for key, name in names.items():
        path = staging / K.file_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data[key])
        records[key] = K.file_record(name, data[key])
    references_rows = _rows(data["references"])
    without_hash = sum(1 for row in references_rows if row.get("content_hash") is None)
    manifest = {
        "schema": K.SET_SCHEMA,
        "imported_at": imported_at,
        "importer_version": K.IMPORTER_VERSION,
        "kbase": copy.deepcopy(KBASE if kbase is None else kbase),
        "files": [records["moves"], records["moves_flagged"], records["references"]],
        "bibliography": {"snapshot_id": BIBLIOGRAPHY["snapshot_id"], "date": pubmed_date,
                         "license": BIBLIOGRAPHY["license"], "origin": K.BIBLIOGRAPHY_ORIGIN,
                         "file": records["pubmed"]},
        "verification": {"records_hash_verified": {"moves": records["moves"]["rows"],
                                                   "moves_flagged": records["moves_flagged"]["rows"],
                                                   "references": len(references_rows) - without_hash},
                         "references_without_hash": without_hash},
    }
    if manifest_patch is not None:
        manifest_patch(manifest)
    raw = K.manifest_bytes(manifest) if validate else K.canonical_json(manifest)
    (staging / K.MANIFEST_NAME).write_bytes(raw)
    set_hash = K.set_hash_of(raw)
    staging.rename(sets / set_hash)
    if activate_set:
        activate(root, set_hash)
    return set_hash
