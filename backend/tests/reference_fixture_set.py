"""Test utility: assemble a reference snapshot FIXTURE set in the importer's layout from the committed fixture lines.

The files come from ``fixtures/reference/{uniprot,sifts,klifs}/*_fixture.jsonl`` (verbatim kbase_kinase processed
snapshot rows, see each folder's ``provenance_fixture.json``). The set is written exactly as
``scripts/import_reference_snapshots.py`` lays it out (``active.json`` + ``sets/<hash>/manifest.json`` +
``sets/<hash>/files/<source>/<date>/<name>``) so ``mw.reference_snapshots.pin_active_set`` accepts it. The manifest's
``url_count``/``raw_sha256`` are empty because the fixture set has no upstream download list; it is a FIXTURE, not a
reference snapshot import.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "reference"

# source -> (snapshot_id, date, version_hint, license, [(set file name, use, fixture file)])
FIXTURE_SOURCES: dict[str, tuple[str, str, str | None, str, list[tuple[str, str, str]]]] = {
    "uniprot": ("SNAP-uniprot-2026-09-15", "2026-09-15", "2026_03", "CC-BY-4.0",
                [("entries.jsonl", "product", "uniprot/entries_fixture.jsonl")]),
    "sifts": ("SNAP-sifts-2026-09-20", "2026-09-20", None, "EMBL-EBI-terms",
              [("residues.jsonl", "product", "sifts/residues_fixture.jsonl"),
               ("segments.jsonl", "product", "sifts/segments_fixture.jsonl")]),
    "klifs": ("SNAP-klifs-2026-09-19", "2026-09-19", None, "none-stated",
              [("kinases.jsonl", "product", "klifs/kinases_fixture.jsonl"),
               ("match_residues.jsonl", "comparison_only", "klifs/match_residues_fixture.jsonl")]),
}
KBASE_COMMIT = "77354f94b844a8c64e7cd47691ac20a2e96214b3"


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _rows(data: bytes) -> int:
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def build_fixture_set(root: Path, *, tag: str = "fixture", activate: bool = True,
                      replace: dict[tuple[str, str], bytes] | None = None) -> str:
    """Write one FIXTURE set under ``root`` (importer layout) and return its set hash.

    ``replace`` maps ``(source, set file name)`` to bytes used instead of the committed fixture file (for tests that
    need a modified row); ``tag`` goes into ``imported_at`` so two builds get different hashes.
    """
    replace = replace or {}
    sets = Path(root) / "sets"
    staging = sets / f".staging-{tag}"
    sources = []
    for source, (snapshot_id, date, version_hint, license_, files) in FIXTURE_SOURCES.items():
        entries = []
        for name, use, fixture in files:
            data = replace.get((source, name))
            if data is None:
                data = (FIXTURES / fixture).read_bytes()
            rel = f"{source}/{date}/{name}"
            path = staging / "files" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            entries.append({"name": name, "path": rel, "sha256": hashlib.sha256(data).hexdigest(),
                            "bytes": len(data), "rows": _rows(data), "use": use})
        sources.append({"source": source, "snapshot_id": snapshot_id, "date": date, "version_hint": version_hint,
                        "license": license_, "origin": "kbase_kinase processed snapshot", "url_count": 0,
                        "raw_sha256": [], "files": entries})
    manifest = {"schema": "reference_snapshot_set@1", "imported_at": f"2026-09-30T00:00:00Z {tag}",
                "kbase_repo": {"commit": KBASE_COMMIT, "dirty": False}, "sources": sources}
    raw = canonical_json(manifest)
    (staging / "manifest.json").write_bytes(raw)
    set_hash = hashlib.sha256(raw).hexdigest()
    staging.rename(sets / set_hash)
    if activate:
        tmp = Path(root) / "active.json.tmp"
        tmp.write_bytes(canonical_json({"schema": "reference_active@1", "set_hash": set_hash}))
        tmp.replace(Path(root) / "active.json")
    return set_hash
