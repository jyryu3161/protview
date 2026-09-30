"""M15 reference snapshot sets on the server side: locate, pin, verify and read (standard library only).

The folder is written by ``scripts/import_reference_snapshots.py`` (this module never reads the kbase_kinase checkout):

    <MW_REFERENCE_DIR or <repo>/.deps/reference>/
        active.json                    {"schema":"reference_active@1","set_hash":"<hex>"}
        sets/<set_hash>/manifest.json  canonical JSON; set_hash = sha256(these exact bytes)
        sets/<set_hash>/files/<source>/<date>/<name>

``pin_active_set()`` reads ``active.json`` exactly once and returns a ``PinnedSet`` bound to that set folder only, so a
concurrent re-import (which writes a new folder and renames the pointer) can never mix two sets inside one call.
File hashes are verified on the first pin of a set after server start and again whenever the active set or any of its
files' stat identity changes; only successful verifications are cached. Content formats (UniProt, SIFTS, KLIFS) are
not decoded here. ``comparison_only`` files (KLIFS ``match_residues.jsonl``) are for tests and measurement comparison
only and need an explicit opt-in.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .core.handles import canonical_json

ROOT = Path(__file__).resolve().parents[2]
ENV_VAR = "MW_REFERENCE_DIR"
DEFAULT_DIR = ROOT / ".deps" / "reference"
ACTIVE_NAME = "active.json"
MANIFEST_NAME = "manifest.json"
SET_SCHEMA = "reference_snapshot_set@1"
POINTER_SCHEMA = "reference_active@1"
ORIGIN = "kbase_kinase processed snapshot"
SOURCES: dict[str, tuple[tuple[str, str], ...]] = {
    "uniprot": (("entries.jsonl", "product"),),
    "sifts": (("residues.jsonl", "product"), ("segments.jsonl", "product")),
    "klifs": (("kinases.jsonl", "product"), ("match_residues.jsonl", "comparison_only")),
}
MAX_POINTER_BYTES = 4 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
REASONS = {
    "not_installed": ("참조 스냅샷 세트가 설치되어 있지 않습니다(가져오기 명령 scripts/import_reference_snapshots.py). "
                      "Reference snapshot set is not installed."),
    "snapshot_invalid": ("참조 스냅샷 세트의 매니페스트 또는 파일 해시가 맞지 않거나 형식을 알 수 없습니다. "
                         "Reference snapshot set manifest or file hashes do not match, or the format is unknown."),
}
SUMMARY_KEYS = ("source", "snapshot_id", "date", "version_hint", "license", "origin")

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_KBASE_SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z|[0-9a-f]{64}\Z")
_SET_KEYS = frozenset({"schema", "imported_at", "kbase_repo", "sources"})
_SOURCE_KEYS = frozenset({"source", "snapshot_id", "date", "version_hint", "license", "origin", "url_count",
                          "raw_sha256", "files"})
_FILE_KEYS = frozenset({"name", "path", "sha256", "bytes", "rows", "use"})

# (resolved set dir, set hash, per-file stat identity) of sets whose file hashes verified; success only.
_VERIFIED: set[tuple] = set()
_LOCK = threading.Lock()


class SnapshotUnavailable(Exception):
    """No usable active set: ``reason_code`` is ``not_installed`` or ``snapshot_invalid``."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(REASONS[reason_code])
        self.reason_code = reason_code
        self.reason = REASONS[reason_code]


class SnapshotAccessError(Exception):
    """A caller asked a pinned set for a source/file it does not have, or a comparison-only file without opt-in."""


def reference_dir() -> Path:
    """``MW_REFERENCE_DIR`` (a relative value is taken from the repository root) or ``<repo>/.deps/reference``."""
    value = os.environ.get(ENV_VAR, "")
    if not value:
        return DEFAULT_DIR
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def _read_limited(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("not a regular file within the size limit")
        chunks, total = [], 0
        while chunk := os.read(fd, 1 << 20):
            total += len(chunk)
            if total > limit:
                raise ValueError("file grew beyond the size limit")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(_read_limited(path, MAX_FILE_BYTES)).hexdigest()


def _read_pointer(root: Path) -> str:
    """The active set hash; FileNotFoundError when nothing is installed, ValueError when malformed."""
    raw = _read_limited(root / ACTIVE_NAME, MAX_POINTER_BYTES)
    data = json.loads(raw)
    if (type(data) is not dict or set(data) != {"schema", "set_hash"} or data["schema"] != POINTER_SCHEMA
            or type(data["set_hash"]) is not str or not _HEX64.fullmatch(data["set_hash"])):
        raise ValueError("unknown active pointer")
    return data["set_hash"]


def _str(value: Any) -> bool:
    return type(value) is str and value != ""


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0


def _validate_manifest(manifest: Any) -> None:
    if type(manifest) is not dict or set(manifest) != _SET_KEYS or manifest["schema"] != SET_SCHEMA:
        raise ValueError("unknown set manifest")
    repo = manifest["kbase_repo"]
    if (not _str(manifest["imported_at"]) or type(repo) is not dict or set(repo) != {"commit", "dirty"}
            or type(repo["commit"]) is not str or not _COMMIT.fullmatch(repo["commit"])
            or type(repo["dirty"]) is not bool):
        raise ValueError("malformed set header")
    sources = manifest["sources"]
    if type(sources) is not list or [s.get("source") if type(s) is dict else None for s in sources] != list(SOURCES):
        raise ValueError("unexpected sources")
    for record in sources:
        name = record["source"]
        if (set(record) != _SOURCE_KEYS or not _str(record["snapshot_id"]) or type(record["date"]) is not str
                or not _DATE.fullmatch(record["date"]) or not _str(record["license"])
                or not (record["version_hint"] is None or _str(record["version_hint"]))
                or record["origin"] != ORIGIN or not _count(record["url_count"])
                or type(record["raw_sha256"]) is not list
                or not all(type(v) is str and _KBASE_SHA.fullmatch(v) for v in record["raw_sha256"])
                or type(record["files"]) is not list or len(record["files"]) != len(SOURCES[name])):
            raise ValueError("malformed source record")
        for entry, (file_name, use) in zip(record["files"], SOURCES[name]):
            if (type(entry) is not dict or set(entry) != _FILE_KEYS or entry["name"] != file_name
                    or entry["use"] != use or entry["path"] != f"{name}/{record['date']}/{file_name}"
                    or type(entry["sha256"]) is not str or not _HEX64.fullmatch(entry["sha256"])
                    or not _count(entry["bytes"]) or entry["bytes"] > MAX_FILE_BYTES or not _count(entry["rows"])):
                raise ValueError("malformed file record")


class PinnedSet:
    """One verified snapshot set. Every accessor stays inside this set's folder, whatever becomes active later."""

    def __init__(self, set_hash: str, set_dir: Path, manifest_bytes: bytes, manifest: dict[str, Any]) -> None:
        self.set_hash = set_hash
        self.set_dir = set_dir
        self.manifest_bytes = manifest_bytes
        self._manifest = manifest
        self._sources = {record["source"]: record for record in manifest["sources"]}

    @property
    def manifest(self) -> dict[str, Any]:
        return copy.deepcopy(self._manifest)

    def summary(self) -> list[dict[str, Any]]:
        return [{key: record[key] for key in SUMMARY_KEYS} for record in self._manifest["sources"]]

    def source(self, name: str) -> dict[str, Any]:
        if name not in self._sources:
            raise SnapshotAccessError(f"unknown reference source {name!r}")
        return copy.deepcopy(self._sources[name])

    def _entry(self, source: str, name: str, allow_comparison_only: bool) -> dict[str, Any]:
        if source not in self._sources:
            raise SnapshotAccessError(f"unknown reference source {source!r}")
        for entry in self._sources[source]["files"]:
            if entry["name"] == name:
                if entry["use"] != "product" and not allow_comparison_only:
                    raise SnapshotAccessError(f"{source}/{name} is comparison-only")
                return entry
        raise SnapshotAccessError(f"{source} has no file {name!r}")

    def file_path(self, source: str, name: str, *, allow_comparison_only: bool = False) -> Path:
        return self.set_dir / "files" / self._entry(source, name, allow_comparison_only)["path"]

    def read_bytes(self, source: str, name: str, *, allow_comparison_only: bool = False) -> bytes:
        """The file's bytes, re-checked against the pinned manifest hash (snapshot_invalid on any difference)."""
        entry = self._entry(source, name, allow_comparison_only)
        try:
            data = _read_limited(self.set_dir / "files" / entry["path"], MAX_FILE_BYTES)
        except (OSError, ValueError) as exc:
            raise SnapshotUnavailable("snapshot_invalid") from exc
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise SnapshotUnavailable("snapshot_invalid")
        return data

    def iter_jsonl(self, source: str, name: str, *, allow_comparison_only: bool = False) -> Iterator[Any]:
        """Each non-empty line parsed as JSON (content is not interpreted here)."""
        data = self.read_bytes(source, name, allow_comparison_only=allow_comparison_only)
        for line in data.splitlines():
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError as exc:
                    raise SnapshotUnavailable("snapshot_invalid") from exc


def _stat_identity(path: Path) -> tuple:
    info = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("not a regular file")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def pin_active_set(root: Path | None = None) -> PinnedSet:
    """Read the active pointer once, verify that set (cached per set hash + file stats) and pin it."""
    root = reference_dir() if root is None else root
    try:
        set_hash = _read_pointer(root)
    except FileNotFoundError as exc:
        raise SnapshotUnavailable("not_installed") from exc
    except (OSError, ValueError) as exc:
        raise SnapshotUnavailable("snapshot_invalid") from exc
    set_dir = root / "sets" / set_hash
    try:
        raw = _read_limited(set_dir / MANIFEST_NAME, MAX_MANIFEST_BYTES)
        if hashlib.sha256(raw).hexdigest() != set_hash:
            raise ValueError("manifest hash differs from the active pointer")
        manifest = json.loads(raw)
        if canonical_json(manifest) != raw:
            raise ValueError("manifest bytes are not canonical")
        _validate_manifest(manifest)
        files = [(set_dir / "files" / entry["path"], entry) for record in manifest["sources"]
                 for entry in record["files"]]
        for path, _entry in files:
            if not path.resolve(strict=True).is_relative_to(set_dir.resolve(strict=True)):
                raise ValueError("file outside its set folder")
        key = (str(set_dir.resolve()), set_hash, tuple(_stat_identity(path) for path, _entry in files))
        with _LOCK:
            cached = key in _VERIFIED
        if not cached:
            for path, entry in files:
                if _stat_identity(path)[2] != entry["bytes"] or _file_sha256(path) != entry["sha256"]:
                    raise ValueError("file hash mismatch")
            if tuple(_stat_identity(path) for path, _entry in files) != key[2]:
                raise ValueError("files changed during verification")
            with _LOCK:
                _VERIFIED.add(key)
    except (OSError, ValueError) as exc:
        raise SnapshotUnavailable("snapshot_invalid") from exc
    return PinnedSet(set_hash, set_dir, raw, manifest)


def capability(root: Path | None = None) -> dict[str, Any]:
    """The ``methods.*`` shape: available, reason_code (null | not_installed | snapshot_invalid), fixed reason."""
    try:
        pinned = pin_active_set(root)
    except SnapshotUnavailable as exc:
        return {"available": False, "reason_code": exc.reason_code, "reason": exc.reason, "set_hash": None,
                "sources": []}
    return {"available": True, "reason_code": None, "reason": None, "set_hash": pinned.set_hash,
            "sources": pinned.summary()}
