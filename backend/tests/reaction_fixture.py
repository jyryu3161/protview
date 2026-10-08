"""Test utility: write a LABELLED SYNTHETIC M26 reaction reference set in the importer's layout (spec 3.1-3.3).

Layout (the same one ``scripts/import_reaction_references.py`` writes):

    <root>/active.json                              {"schema":"reaction_active@1","set_hash":"<hex64>"}
    <root>/sets/<set_hash>/manifest.json            canonical JSON; set_hash = sha256(these bytes)
    <root>/sets/<set_hash>/files/<source>/<name>    processed JSONL (one canonical JSON row + "\n" per line)
    <root>/sets/<set_hash>/files/request_log.jsonl

Everything is built ONLY with the shared helpers of ``mw.reaction_knowledge_constants`` (``encode_jsonl``,
``jsonl_line``, ``file_record``, ``raw_sha256_digest``, ``canonical_json``, ``set_hash_of``, ``validate_manifest``,
``pointer_bytes``), so this helper and the import command follow one manifest rule. Rows default to the synthetic
fixtures in ``fixtures/reaction/t2/`` (see SYNTHETIC-PROVENANCE-t2.md); the request log names no real response (its
body hashes are hashes of fixed synthetic strings). This is a FIXTURE set, not an import.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mw import reaction_knowledge_constants as K

T2 = Path(__file__).resolve().parent / "fixtures" / "reaction" / "t2"
DATE = "2026-10-08"
IMPORTED_AT = "2026-10-08T00:00:00Z"
FIXTURE_KINASE_SET = "e" * 64  # synthetic M15 set hash written into requested_accessions (no M15 set is read)
SKIPPED = [
    {"accession": "P0SYN6", "reason": "demerged", "target_accessions": ["P0SYN1", "P0SYN2"]},
    {"accession": "Q0SYN4", "reason": "merged", "target_accessions": ["Q0SYN9"]},
    {"accession": "Q0SYN7", "reason": "obsolete", "target_accessions": []},
]
_URLS = {
    "mcsa": "https://www.ebi.ac.uk/thornton-srv/m-csa/api/entries/?format=json&page=1&page_size=100",
    "uniprot_function": "https://rest.uniprot.org/uniprotkb/accessions?accessions=P0SYN3,Q0SYN1&format=json",
    "rhea": "https://www.rhea-db.org/rhea?query=&columns=rhea-id,equation,chebi,chebi-id,ec&format=tsv&limit=20000",
}


def synthetic_rows() -> dict[str, list[dict[str, Any]]]:
    """The committed synthetic processed rows per source (fresh copies)."""
    return {"mcsa": json.loads((T2 / "mcsa_entries.json").read_text(encoding="utf-8")),
            "uniprot_function": json.loads((T2 / "uniprot_entries.json").read_text(encoding="utf-8")),
            "rhea": json.loads((T2 / "rhea_reactions.json").read_text(encoding="utf-8"))}


def default_request_log() -> list[dict[str, Any]]:
    rows = []
    for seq, source in enumerate(K.SOURCES, start=1):
        body = f"SYNTHETIC fixture response body {source}".encode()
        rows.append({"seq": seq, "source": source, "method": "GET", "url": _URLS[source], "status": 200,
                     "bytes": len(body), "sha256": K.sha256_hex(body)})
    return rows


def requested_for(mcsa_rows: list[dict[str, Any]], skipped: list[dict[str, Any]]) -> dict[str, Any]:
    """``requested_accessions`` for a fixture set: M-CSA accessions + a synthetic two-accession kinase list."""
    derived = sorted({acc for row in mcsa_rows for acc in K.entry_accessions(row)})
    kinase = 2
    return {"from_mcsa": len(derived), "from_m15_kinase_set": {"set_hash": FIXTURE_KINASE_SET, "count": kinase},
            "m15_kinase_list": "present", "user_named": [], "dropped_previous_user_named": [],
            "union_count": len(derived) + kinase}


def activate(root: Path, set_hash: str) -> None:
    tmp = Path(root) / "active.json.tmp"
    tmp.write_bytes(K.pointer_bytes(set_hash))
    tmp.replace(Path(root) / K.ACTIVE_NAME)


def build_set(root: Path, *, rows: dict[str, list[dict[str, Any]]] | None = None,
              skipped: list[dict[str, Any]] | None = None, requested: dict[str, Any] | None = None,
              imported_at: str = IMPORTED_AT, activate_set: bool = True,
              file_bytes: dict[str, bytes] | None = None,
              request_log: list[dict[str, Any]] | None = None,
              manifest_patch: Callable[[dict[str, Any]], None] | None = None,
              validate: bool = True) -> str:
    """Write one FIXTURE set under ``root`` and return its set hash.

    ``file_bytes`` replaces a source's processed file bytes (the manifest records the replacement's hash, size and
    line count, as an importer that wrote those bytes would); ``manifest_patch`` edits the manifest dict before it is
    hashed (for tests that need an internally consistent but wrong manifest; pass ``validate=False`` when the patch
    makes it invalid). ``imported_at`` makes two builds of the same rows different sets.
    """
    root = Path(root)
    rows = synthetic_rows() if rows is None else copy.deepcopy(rows)
    skipped = copy.deepcopy(SKIPPED if skipped is None else skipped)
    file_bytes = file_bytes or {}
    log = default_request_log() if request_log is None else copy.deepcopy(request_log)
    sets = root / "sets"
    staging = sets / f".staging-{K.sha256_hex(imported_at.encode())[:12]}"
    (staging / "files").mkdir(parents=True)
    sources = []
    for source in K.SOURCES:
        (name,) = K.SOURCE_FILES[source]
        data = file_bytes[source] if source in file_bytes else K.encode_jsonl(source, rows[source])
        rel = f"files/{source}/{name}"
        (staging / rel).parent.mkdir(parents=True, exist_ok=True)
        (staging / rel).write_bytes(data)
        digests = [r["sha256"] for r in log if r["source"] == source]
        sources.append({"source": source, "date": DATE, "license": K.LICENSE, "license_url": K.LICENSE_URL,
                        "origin": K.ORIGIN, "files": [K.file_record(rel, name, data)],
                        "raw_response_count": len(digests), "raw_sha256_digest": K.raw_sha256_digest(digests)})
    log_bytes = b"".join(K.jsonl_line(r) for r in log)
    (staging / K.REQUEST_LOG_PATH).write_bytes(log_bytes)
    manifest = {"schema": K.SET_SCHEMA, "imported_at": imported_at, "importer_version": K.IMPORTER_VERSION,
                "sources": sources,
                "requested_accessions": requested if requested is not None else requested_for(rows["mcsa"], skipped),
                "skipped_accessions": skipped,
                "request_log": K.file_record(K.REQUEST_LOG_PATH, K.REQUEST_LOG_NAME, log_bytes)}
    if manifest_patch is not None:
        manifest_patch(manifest)
    if validate:
        K.validate_manifest(manifest)
    raw = K.canonical_json(manifest)
    (staging / K.MANIFEST_NAME).write_bytes(raw)
    set_hash = K.set_hash_of(raw)
    staging.rename(sets / set_hash)
    if activate_set:
        activate(root, set_hash)
    return set_hash
