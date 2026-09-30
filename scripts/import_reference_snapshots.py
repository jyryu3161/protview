"""Import the M15 reference snapshot set (UniProt, SIFTS, KLIFS) from a local kbase_kinase checkout.

Usage: python scripts/import_reference_snapshots.py --from <kbase_kinase path> [--dest .deps/reference]

For each source the most recent-dated snapshot in ``<kbase>/ref/manifest.json`` is chosen and only the listed files
are copied. Every file's SHA-256, byte count and row count are checked against the kbase manifest first; on any
mismatch nothing under ``--dest`` is changed. The copied files are kbase_kinase *processed* JSONL snapshots, not the
original upstream bytes (those survive only as the kbase ``raw_sha256`` list, which is recorded verbatim).

Layout written under ``--dest``::

    active.json                      {"schema":"reference_active@1","set_hash":"<hex>"} (replaced by one rename)
    sets/<set_hash>/manifest.json    canonical JSON set manifest; set_hash = sha256(these exact bytes)
    sets/<set_hash>/files/<source>/<date>/<name>

Canonical manifest bytes: ``json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
allow_nan=False).encode()`` with no trailing newline. ``imported_at`` is inside the manifest, so every import makes
a new set hash. Older set folders are never deleted. No network is used; the kbase git commit is read with
``git -C <path>`` (local subprocess).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST = ROOT / ".deps" / "reference"
ACTIVE_NAME = "active.json"
MANIFEST_NAME = "manifest.json"
SET_SCHEMA = "reference_snapshot_set@1"
POINTER_SCHEMA = "reference_active@1"
ORIGIN = "kbase_kinase processed snapshot"
# source -> [(file name, use)]; "comparison_only" files are for tests/measurement comparison, never product compute.
SOURCES: dict[str, list[tuple[str, str]]] = {
    "uniprot": [("entries.jsonl", "product")],
    "sifts": [("residues.jsonl", "product"), ("segments.jsonl", "product")],
    "klifs": [("kinases.jsonl", "product"), ("match_residues.jsonl", "comparison_only")],
}
MAX_KBASE_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
KBASE_SHA_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ImportFailure(Exception):
    """The import was refused; nothing under the destination was changed."""


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rows(data: bytes) -> int:
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def read_git_info(kbase: Path) -> dict[str, Any]:
    """The kbase checkout's HEAD commit and whether its working tree is dirty (local git only)."""
    def git(*args: str) -> str:
        try:
            proc = subprocess.run(["git", "-C", str(kbase), *args], capture_output=True, text=True, timeout=60, check=False,
                                  stdin=subprocess.DEVNULL, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        except (OSError, subprocess.SubprocessError) as exc:
            raise ImportFailure(f"cannot run git in {kbase}: {exc}") from exc
        if proc.returncode != 0:
            raise ImportFailure(f"git {' '.join(args)} failed in {kbase}: {proc.stderr.strip()}")
        return proc.stdout

    commit = git("rev-parse", "HEAD").strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise ImportFailure(f"unexpected git commit id {commit!r}")
    return {"commit": commit, "dirty": bool(git("status", "--porcelain").strip())}


def _load_kbase_manifest(ref: Path) -> list[dict[str, Any]]:
    path = ref / "manifest.json"
    try:
        if path.stat().st_size > MAX_KBASE_MANIFEST_BYTES:
            raise ImportFailure(f"{path} is larger than {MAX_KBASE_MANIFEST_BYTES} bytes")
        data = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ImportFailure(f"cannot read kbase manifest {path}: {exc}") from exc
    if type(data) is not dict or type(data.get("snapshots")) is not list:
        raise ImportFailure("kbase manifest has no snapshots list")
    return data["snapshots"]


def _latest(snapshots: list[Any], source: str) -> dict[str, Any]:
    mine = [s for s in snapshots if type(s) is dict and s.get("source") == source]
    if not mine:
        raise ImportFailure(f"kbase manifest has no {source} snapshot")
    for snap in mine:
        if type(snap.get("date")) is not str or not DATE_RE.fullmatch(snap["date"]):
            raise ImportFailure(f"{source} snapshot has an invalid date: {snap.get('date')!r}")
    newest = max(s["date"] for s in mine)
    chosen = [s for s in mine if s["date"] == newest]
    if len(chosen) != 1:
        raise ImportFailure(f"{len(chosen)} {source} snapshots share the newest date {newest}; refusing to choose")
    return chosen[0]


def _check_snapshot(snap: dict[str, Any], source: str) -> None:
    if type(snap.get("snapshot_id")) is not str or not snap["snapshot_id"]:
        raise ImportFailure(f"{source} snapshot has no snapshot_id")
    if type(snap.get("license")) is not str or not snap["license"]:
        raise ImportFailure(f"{source} snapshot has no license")
    if snap.get("version_hint") is not None and type(snap["version_hint"]) is not str:
        raise ImportFailure(f"{source} snapshot has an invalid version_hint")
    if type(snap.get("urls")) is not list or not all(type(u) is str for u in snap["urls"]):
        raise ImportFailure(f"{source} snapshot has an invalid urls list")
    raw = snap.get("raw_sha256")
    if type(raw) is not list or not all(type(v) is str and KBASE_SHA_RE.fullmatch(v) for v in raw):
        raise ImportFailure(f"{source} snapshot has an invalid raw_sha256 list")
    if type(snap.get("files")) is not list:
        raise ImportFailure(f"{source} snapshot has no files list")


def _collect(ref: Path, source: str, snap: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[str, bytes]]]:
    """Verify one source's chosen files in memory and build its manifest record (no writes)."""
    _check_snapshot(snap, source)
    by_path = {}
    for entry in snap["files"]:
        if type(entry) is not dict or type(entry.get("path")) is not str:
            raise ImportFailure(f"{source} snapshot has a malformed file entry")
        by_path[entry["path"]] = entry
    records, payloads = [], []
    for name, use in SOURCES[source]:
        rel = f"{source}/{snap['date']}/{name}"
        entry = by_path.get(rel)
        if entry is None:
            raise ImportFailure(f"{snap['snapshot_id']} does not list {rel}")
        want_sha, want_bytes, want_rows = entry.get("sha256"), entry.get("bytes"), entry.get("rows")
        if (type(want_sha) is not str or not KBASE_SHA_RE.fullmatch(want_sha) or type(want_bytes) is not int
                or type(want_rows) is not int or want_bytes < 0 or want_bytes > MAX_FILE_BYTES):
            raise ImportFailure(f"{rel}: malformed sha256/bytes/rows in the kbase manifest")
        path = ref / rel
        try:
            if path.is_symlink() or not path.is_file():
                raise ImportFailure(f"{rel}: not a regular file")
            data = path.read_bytes()
        except OSError as exc:
            raise ImportFailure(f"{rel}: cannot read: {exc}") from exc
        if len(data) != want_bytes:
            raise ImportFailure(f"{rel}: bytes {len(data)} != manifest {want_bytes}")
        digest = _sha(data)
        if "sha256:" + digest != want_sha:
            raise ImportFailure(f"{rel}: sha256 {digest} != manifest {want_sha}")
        rows = _rows(data)
        if rows != want_rows:
            raise ImportFailure(f"{rel}: rows {rows} != manifest {want_rows}")
        records.append({"name": name, "path": rel, "sha256": digest, "bytes": len(data), "rows": rows, "use": use})
        payloads.append((rel, data))
    record = {"source": source, "snapshot_id": snap["snapshot_id"], "date": snap["date"],
              "version_hint": snap.get("version_hint"), "license": snap["license"], "origin": ORIGIN,
              "url_count": len(snap["urls"]), "raw_sha256": list(snap["raw_sha256"]), "files": records}
    return record, payloads


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def import_snapshots(kbase: Path, dest: Path, *, git_info: Callable[[Path], dict[str, Any]] = read_git_info,
                     now: Callable[[], str] = _now) -> dict[str, Any]:
    """Verify, write a complete new set folder, then atomically point ``active.json`` at it."""
    kbase = Path(kbase).resolve()
    dest = Path(dest)
    ref = kbase / "ref"
    snapshots = _load_kbase_manifest(ref)
    sources, payloads = [], []
    for source in SOURCES:
        record, files = _collect(ref, source, _latest(snapshots, source))
        sources.append(record)
        payloads.extend(files)
    repo = git_info(kbase)
    manifest = {"schema": SET_SCHEMA, "imported_at": now(), "kbase_repo": repo, "sources": sources}
    raw = canonical_json(manifest)
    set_hash = _sha(raw)
    sets = dest / "sets"
    final = sets / set_hash
    if final.exists():
        raise ImportFailure(f"set folder {final} already exists")
    # Every check has passed; only now may the destination change.
    sets.mkdir(parents=True, exist_ok=True)
    staging = sets / f".staging-{uuid.uuid4().hex}"
    try:
        staging.mkdir()
        for rel, data in payloads:
            _write_file(staging / "files" / rel, data)
        _write_file(staging / MANIFEST_NAME, raw)
        directories = {staging}
        for rel, _data in payloads:
            parent = (staging / "files" / rel).parent
            while parent != staging:
                directories.add(parent)
                parent = parent.parent
        for directory in directories:
            _fsync_dir(directory)
        os.rename(staging, final)
        _fsync_dir(sets)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    pointer_tmp = dest / f".{ACTIVE_NAME}.{uuid.uuid4().hex}.tmp"
    try:
        _write_file(pointer_tmp, canonical_json({"schema": POINTER_SCHEMA, "set_hash": set_hash}))
        os.replace(pointer_tmp, dest / ACTIVE_NAME)
        _fsync_dir(dest)
    except BaseException:
        try:
            pointer_tmp.unlink()
        except FileNotFoundError:
            pass
        raise
    return {"set_hash": set_hash, "set_dir": str(final), "imported_at": manifest["imported_at"],
            "kbase_repo": repo, "sources": [{k: s[k] for k in ("source", "snapshot_id", "date", "version_hint",
                                                              "license")} for s in sources]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--from", dest="kbase", required=True, type=Path, help="local kbase_kinase checkout")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help=f"reference folder (default {DEFAULT_DEST})")
    args = parser.parse_args(argv)
    try:
        result = import_snapshots(args.kbase, args.dest)
    except ImportFailure as exc:
        print(f"import_reference_snapshots: refused, nothing changed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
