"""Immutable, content-addressed scientific objects with event-backed recovery."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import stat
import threading
import time
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .events import EventLog

HANDLE_PREFIX = "obj://"
PREVIEW_MAX = 5
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
KIND_RE = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
FMT_RE = re.compile(r"[a-z0-9]{1,12}\Z")


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_sha(kind: str, schema: str, raw: bytes) -> str:
    return sha256_hex(kind.encode() + b"\0" + schema.encode() + b"\0" + raw)


class Handle(BaseModel):
    handle: str
    kind: str
    schema_: str = Field(alias="schema")
    summary: dict[str, Any] = Field(default_factory=dict)
    preview: list[dict[str, Any]] = Field(default_factory=list)
    produced_by: str | None = None
    null_result: bool = False
    model_config = {"populate_by_name": True}

    @property
    def sha(self) -> str:
        return self.handle.rsplit("/", 1)[-1]


class ObjectStore:
    """The event is synced before the blob and disposable SQLite row are written.

    An interrupted write is repaired by rebuild_from_events(). Content and handle
    hashes are rechecked during recovery and reads, so a corrupt blob never wins.
    """

    def __init__(self, run_dir: Path, run_id: str, events: EventLog | None = None) -> None:
        if not RUN_ID_RE.fullmatch(run_id):
            raise ValueError("invalid run identifier")
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        if events is None:
            from .events import EventLog
            events = EventLog(self.run_dir / "events.jsonl")
        self.events = events
        self.obj_dir = self.run_dir / "objects"
        self.obj_dir.mkdir(parents=True, exist_ok=True)
        if self.obj_dir.is_symlink() or self.obj_dir.resolve().parent != self.run_dir.resolve():
            raise ValueError("unsafe object directory")
        if (self.run_dir / "index.sqlite").is_symlink():
            raise ValueError("unsafe object index")
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.run_dir / "index.sqlite", check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS objects (handle TEXT PRIMARY KEY, kind TEXT NOT NULL, "
            "schema TEXT NOT NULL, path TEXT NOT NULL, fmt TEXT NOT NULL, size INTEGER NOT NULL, "
            "produced_by TEXT, created REAL NOT NULL, summary TEXT NOT NULL, null_result INTEGER NOT NULL)"
        )
        self.db.commit()

    def _check_handle(self, handle: str) -> tuple[str, str]:
        match = re.fullmatch(r"obj://([^/]+)/([^/]+)/([0-9a-f]{64})", handle)
        if not match or match.group(1) != self.run_id or not KIND_RE.fullmatch(match.group(2)):
            raise KeyError(handle)
        return match.group(2), match.group(3)

    def _open_obj_dir(self) -> int:
        run_fd = -1
        try:
            run_fd = os.open(self.run_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            return os.open("objects", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                           dir_fd=run_fd)
        except OSError as exc:
            raise ValueError("unsafe object directory") from exc
        finally:
            if run_fd >= 0:
                os.close(run_fd)

    def put(self, kind: str, schema: str, content: Any, *, fmt: str = "json",
            produced_by: str | None = None, summary: dict[str, Any] | None = None,
            null_result: bool = False) -> Handle:
        if not KIND_RE.fullmatch(kind) or not FMT_RE.fullmatch(fmt):
            raise ValueError("invalid object kind or format")
        if fmt == "parquet":
            import pyarrow as pa
            if not isinstance(content, list) or any(not isinstance(row, dict) for row in content):
                raise ValueError("parquet content must be a list of rows")
            if any(not isinstance(key, str) for row in content for key in row):
                raise ValueError("parquet column names must be strings")
            keys = sorted({key for row in content for key in row})
            content = [{key: row.get(key) for key in keys} for row in content]
            raw_preflight = canonical_json(content)
            if canonical_json(pa.Table.from_pylist(content).to_pylist()) != raw_preflight:
                raise ValueError("parquet conversion would change row values")
        raw = bytes(content) if isinstance(content, (bytes, bytearray)) else canonical_json(content)
        sha = object_sha(kind, schema, raw)
        handle = f"{HANDLE_PREFIX}{self.run_id}/{kind}/{sha}"
        with self._lock:
            try:
                meta = self.meta(handle)
            except KeyError:
                meta = None
            if meta is None:
                payload = {
                    "handle": handle, "kind": kind, "schema": schema, "fmt": fmt,
                    "payload_b64": base64.b64encode(raw).decode("ascii"),
                    "summary": summary or {}, "produced_by": produced_by,
                    "null_result": null_result,
                }
                self.events.append("object_created", **payload)
                self._install(payload, raw)
            else:
                if self._raw(meta) != raw:
                    raise ValueError("object handle collision or corrupt content")
                if meta["summary"] != (summary or {}) or meta["null_result"] != null_result:
                    raise ValueError("conflicting metadata for identical object content")
            preview = (content[:PREVIEW_MAX] if isinstance(content, list) else
                       content.get("rows", [])[:PREVIEW_MAX]
                       if kind == "interaction_set" and isinstance(content, dict) else [])
            return Handle(handle=handle, kind=kind, schema=schema, summary=meta["summary"] if meta else summary or {},
                          preview=preview, produced_by=produced_by, null_result=null_result)

    def _install(self, event: dict[str, Any], raw: bytes, *, commit: bool = True) -> None:
        kind, sha = self._check_handle(event["handle"])
        if kind != event["kind"] or object_sha(kind, event["schema"], raw) != sha:
            raise ValueError("corrupt object event hash")
        fmt = event["fmt"]
        if not FMT_RE.fullmatch(fmt):
            raise ValueError("invalid object format")
        name = f"{sha}.{fmt}"
        obj_fd = self._open_obj_dir()
        try:
            try:
                existing_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                      dir_fd=obj_fd)
            except FileNotFoundError:
                existing_fd = None
            if existing_fd is not None:
                existing = self._decode_fd(existing_fd, fmt)
                if existing != raw:
                    raise ValueError("corrupt existing object payload")
            else:
                temp_name = f".tmp-{uuid.uuid4().hex}"
                temp_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                  0o600, dir_fd=obj_fd)
                try:
                    with os.fdopen(temp_fd, "wb") as temp:
                        if fmt == "parquet":
                            import pyarrow as pa
                            import pyarrow.parquet as pq
                            pq.write_table(pa.Table.from_pylist(json.loads(raw)), temp)
                        else:
                            temp.write(raw)
                        temp.flush()
                        os.fsync(temp.fileno())
                    os.replace(temp_name, name, src_dir_fd=obj_fd, dst_dir_fd=obj_fd)
                except BaseException:
                    os.unlink(temp_name, dir_fd=obj_fd)
                    raise
            size = os.stat(name, dir_fd=obj_fd, follow_symlinks=False).st_size
        except OSError as exc:
            raise ValueError("unsafe object path") from exc
        finally:
            os.close(obj_fd)
        self.db.execute(
            "INSERT OR REPLACE INTO objects VALUES (?,?,?,?,?,?,?,?,?,?)",
            (event["handle"], kind, event["schema"], f"objects/{name}",
             fmt, size, event.get("produced_by"), time.time(),
             canonical_json(event.get("summary", {})).decode(), int(event.get("null_result", False))),
        )
        if commit:
            self.db.commit()

    @staticmethod
    def _decode_fd(descriptor: int, fmt: str) -> bytes:
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("object is not a regular file")
            if fmt == "parquet":
                import pyarrow.parquet as pq
                return canonical_json(pq.read_table(stream).to_pylist())
            return stream.read()

    def rebuild_from_events(self) -> set[str]:
        """Publish a validated event-derived index in one SQLite transaction."""
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute("DELETE FROM objects")
                for event in self.events.read():
                    if event["type"] != "object_created":
                        continue
                    try:
                        raw = base64.b64decode(event["payload_b64"], validate=True)
                    except (ValueError, KeyError) as exc:
                        raise ValueError("corrupt object event payload") from exc
                    self._install(event, raw, commit=False)
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise
            return self.handles()

    def meta(self, handle: str) -> dict[str, Any]:
        self._check_handle(handle)
        with self._lock:
            row = self.db.execute(
                "SELECT handle,kind,schema,path,fmt,size,produced_by,summary,null_result "
                "FROM objects WHERE handle=?", (handle,),
            ).fetchone()
        if not row:
            raise KeyError(handle)
        meta = dict(zip(("handle", "kind", "schema", "path", "fmt", "size", "produced_by",
                         "summary", "null_result"), row))
        meta["summary"] = json.loads(meta["summary"])
        meta["null_result"] = bool(meta["null_result"])
        return meta

    def kind_of(self, handle: str) -> str:
        return self.meta(handle)["kind"]

    def _raw(self, meta: dict[str, Any]) -> bytes:
        _, sha = self._check_handle(meta["handle"])
        if meta["path"] != f"objects/{sha}.{meta['fmt']}":
            raise ValueError("unsafe object path")
        obj_fd = self._open_obj_dir()
        try:
            descriptor = os.open(f"{sha}.{meta['fmt']}",
                                 os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=obj_fd)
            raw = self._decode_fd(descriptor, meta["fmt"])
        except OSError as exc:
            raise ValueError("unsafe object path") from exc
        finally:
            os.close(obj_fd)
        if object_sha(meta["kind"], meta["schema"], raw) != sha:
            raise ValueError("corrupt object payload hash")
        return raw

    def load(self, handle: str) -> Any:
        meta = self.meta(handle)
        raw = self._raw(meta)
        return json.loads(raw) if meta["fmt"] in ("json", "parquet") else raw

    def materialize(self, handle: str, columns: Iterable[str] | None = None,
                    offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("invalid materialization page")
        meta = self.meta(handle)
        rows = self.load(handle)
        if meta["kind"] == "interaction_set" and isinstance(rows, dict):
            rows = rows["rows"]
        if not isinstance(rows, list):
            raise TypeError("object is not a row table")
        selected = list(columns) if columns is not None else None
        if selected is not None and (not selected or any(not isinstance(c, str) for c in selected)):
            raise ValueError("invalid column projection")
        page = rows[offset:offset + limit]
        if selected is None:
            return page
        valid = {key for row in rows for key in row}
        if meta["kind"] == "interaction_set":
            valid |= {"residue", "ligand", "model_number", "type", "distance_A", "protein_atom",
                      "ligand_atom", "engine", "method", "unit", "limitations"}
        if any(c not in valid for c in selected):
            raise ValueError("unknown materialization column")
        return [{key: row.get(key) for key in selected} for row in page]

    def handles(self) -> set[str]:
        with self._lock:
            return {row[0] for row in self.db.execute("SELECT handle FROM objects")}
