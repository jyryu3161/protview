"""M26 reaction reference sets on the server side: locate, pin and verify (standard library only, spec 3.1).

The folder is written only by the user-run command ``scripts/import_reaction_references.py``:

    <MW_REACTION_REFERENCE_DIR or <repo>/.deps/reaction_reference>/
        active.json                              {"schema":"reaction_active@1","set_hash":"<hex64>"}
        sets/<set_hash>/manifest.json            canonical JSON; set_hash = sha256(these exact bytes)
        sets/<set_hash>/files/<source>/<name>    processed JSONL (mcsa, uniprot_function, rhea)
        sets/<set_hash>/files/request_log.jsonl

This family is separate from the M15 reference snapshots (own variable, folder, pointer schema, module and caches);
the pinning behaviour is the same. ``pin_active_set()`` reads ``active.json`` exactly once and returns a
``PinnedReactionSet`` bound to that set folder only, so a concurrent import (new folder + pointer rename) can never mix
two sets inside one call. Each listed file (the three processed files and the request log) must be a regular file
opened with ``O_NOFOLLOW`` inside the set folder, within the size cap, and match the manifest's SHA-256, byte count and
line count; the set folder itself must not be a symbolic link. Files are verified on the first pin of a set after
server start and again whenever the set or any file's stat identity changes; only successful verifications are cached
(one entry per set folder). Content formats are decoded by ``mw.reaction_knowledge``, not here.

Interface: ``reference_dir()``, ``pin_active_set(root=None) -> PinnedReactionSet``, ``capability(root=None)``,
``SnapshotUnavailable(reason_code)`` (``not_installed`` | ``snapshot_invalid``, mapped to a 412 precondition by the
tool), ``SnapshotAccessError`` (a caller asked for a source/file the set does not list).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import threading
from pathlib import Path
from typing import Any

from . import reaction_knowledge_constants as K

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT.joinpath(*K.DEFAULT_DIR_PARTS)

# resolved set dir -> latest (resolved set dir, set hash, per-file stat identity) whose files verified;
# success only, one entry per set folder.
_VERIFIED: dict[str, tuple] = {}
_LOCK = threading.Lock()


class SnapshotUnavailable(Exception):
    """No usable active set: ``reason_code`` is ``not_installed`` or ``snapshot_invalid``."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(K.SNAPSHOT_REASONS[reason_code])
        self.reason_code = reason_code
        self.reason = K.SNAPSHOT_REASONS[reason_code]


class SnapshotAccessError(Exception):
    """A caller asked a pinned set for a source or file it does not list."""


def reference_dir() -> Path:
    """``MW_REACTION_REFERENCE_DIR`` (a relative value is taken from the repository root) or the default folder."""
    value = os.environ.get(K.ENV_VAR, "")
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


def _read_pointer(root: Path) -> str:
    """The active set hash; FileNotFoundError when nothing is installed, ValueError when malformed."""
    return K.validate_pointer(json.loads(_read_limited(root / K.ACTIVE_NAME, K.MAX_POINTER_BYTES)))


def _stat_identity(path: Path) -> tuple:
    info = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("not a regular file")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _verify_file(path: Path, entry: dict[str, Any]) -> None:
    """Bytes, SHA-256 and line count of one listed file (every line ends with a newline)."""
    data = _read_limited(path, K.MAX_FILE_BYTES)
    if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError("file hash mismatch")
    if (data and not data.endswith(b"\n")) or data.count(b"\n") != entry["rows"]:
        raise ValueError("file line count mismatch")


def _listed(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for record in manifest["sources"] for entry in record["files"]] + [manifest["request_log"]]


class PinnedReactionSet:
    """One verified set. Every accessor stays inside this set's folder, whatever becomes active later."""

    def __init__(self, set_hash: str, set_dir: Path, manifest_bytes: bytes, manifest: dict[str, Any],
                 files_identity: tuple) -> None:
        self.set_hash = set_hash
        self.set_dir = set_dir
        self.manifest_bytes = manifest_bytes
        self.files_identity = files_identity  # stat identity of every listed file at verification
        self._manifest = manifest
        self._sources = {record["source"]: record for record in manifest["sources"]}

    @property
    def manifest(self) -> dict[str, Any]:
        return copy.deepcopy(self._manifest)

    def source(self, name: str) -> dict[str, Any]:
        if name not in self._sources:
            raise SnapshotAccessError(f"unknown reaction reference source {name!r}")
        return copy.deepcopy(self._sources[name])

    def summary(self) -> list[dict[str, Any]]:
        """Per source ``{source, date, license, origin, rows}`` (``rows`` = the source files' rows summed)."""
        return [{"source": r["source"], "date": r["date"], "license": r["license"], "origin": r["origin"],
                 "rows": sum(f["rows"] for f in r["files"])} for r in self._manifest["sources"]]

    def _entry(self, source: str, name: str) -> dict[str, Any]:
        if source not in self._sources:
            raise SnapshotAccessError(f"unknown reaction reference source {source!r}")
        for entry in self._sources[source]["files"]:
            if entry["name"] == name:
                return entry
        raise SnapshotAccessError(f"{source} has no file {name!r}")

    def file_path(self, source: str, name: str) -> Path:
        return self.set_dir / self._entry(source, name)["path"]

    def read_bytes(self, source: str, name: str) -> bytes:
        """The file's bytes, re-checked against the pinned manifest (snapshot_invalid on any difference)."""
        entry = self._entry(source, name)
        try:
            data = _read_limited(self.set_dir / entry["path"], K.MAX_FILE_BYTES)
        except (OSError, ValueError) as exc:
            raise SnapshotUnavailable("snapshot_invalid") from exc
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise SnapshotUnavailable("snapshot_invalid")
        return data


def _no_constant(value: str) -> Any:
    raise ValueError(f"non-finite number {value}")


def pin_active_set(root: Path | None = None) -> PinnedReactionSet:
    """Read the active pointer once, verify that set (cached per set folder + file stats) and pin it."""
    root = reference_dir() if root is None else Path(root)
    try:
        set_hash = _read_pointer(root)
    except FileNotFoundError as exc:
        raise SnapshotUnavailable("not_installed") from exc
    except (OSError, ValueError, RecursionError) as exc:  # RecursionError: JSON nested past the recursion limit
        raise SnapshotUnavailable("snapshot_invalid") from exc
    set_dir = root / K.SETS_DIR / set_hash
    try:
        if not stat.S_ISDIR(os.lstat(set_dir).st_mode):
            raise ValueError("the set folder is not a plain directory")
        raw = _read_limited(set_dir / K.MANIFEST_NAME, K.MAX_MANIFEST_BYTES)
        if K.set_hash_of(raw) != set_hash:
            raise ValueError("manifest hash differs from the active pointer")
        manifest = json.loads(raw, parse_constant=_no_constant)
        if K.canonical_json(manifest) != raw:
            raise ValueError("manifest bytes are not canonical")
        K.validate_manifest(manifest)
        files = [(set_dir / entry["path"], entry) for entry in _listed(manifest)]
        inside = set_dir.resolve(strict=True)
        for path, _entry in files:
            if not path.resolve(strict=True).is_relative_to(inside):
                raise ValueError("file outside its set folder")
        identity = tuple(_stat_identity(path) for path, _entry in files)
        key = (str(inside), set_hash, identity)
        with _LOCK:
            cached = _VERIFIED.get(key[0]) == key
        if not cached:
            for path, entry in files:
                _verify_file(path, entry)
            if tuple(_stat_identity(path) for path, _entry in files) != identity:
                raise ValueError("files changed during verification")
            with _LOCK:
                _VERIFIED[key[0]] = key
    except (OSError, ValueError, RecursionError) as exc:
        raise SnapshotUnavailable("snapshot_invalid") from exc
    return PinnedReactionSet(set_hash, set_dir, raw, manifest, identity)


def capability(root: Path | None = None) -> dict[str, Any]:
    """Hash-level ``methods.*`` shape: available, reason_code, reason, set_hash, sources (``[]`` when unusable).

    Content formats are not decoded here; ``mw.reaction_knowledge.capability()`` also decodes them.
    """
    try:
        pinned = pin_active_set(root)
    except SnapshotUnavailable as exc:
        return {"available": False, "reason_code": exc.reason_code, "reason": exc.reason, "set_hash": None,
                "sources": []}
    return {"available": True, "reason_code": None, "reason": None, "set_hash": pinned.set_hash,
            "sources": pinned.summary()}
