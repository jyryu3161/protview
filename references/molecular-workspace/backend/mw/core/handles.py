"""Content-addressed object store (plan §3.1–3.2).

Tools never return data. They put data here and return a Handle + summary.
Same kind + schema + canonical content  ->  same sha256  ->  same handle.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field

HANDLE_PREFIX = "obj://"
PREVIEW_MAX = 5


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON bytes: sorted keys, no whitespace, floats as repr."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Handle(BaseModel):
    """What a tool returns. The model passes `handle` as an opaque string."""
    handle: str
    kind: str
    schema_: str = Field(alias="schema")
    summary: dict[str, Any] = {}
    preview: list[dict[str, Any]] = []
    produced_by: str | None = None
    null_result: bool = False          # scientific_null: a result, not an error
    model_config = {"populate_by_name": True}

    @property
    def sha(self) -> str:
        return self.handle.rsplit("/", 1)[-1]


class ObjectStore:
    """runs/<run_id>/objects/<sha>.<fmt> + runs/<run_id>/index.sqlite (derived)."""

    def __init__(self, run_dir: Path, run_id: str) -> None:
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self.obj_dir = self.run_dir / "objects"
        self.obj_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.run_dir / "index.sqlite")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS objects (handle TEXT PRIMARY KEY, kind TEXT, schema TEXT,"
            " path TEXT, fmt TEXT, size INTEGER, produced_by TEXT, created REAL, summary TEXT)"
        )

    # ---- write -----------------------------------------------------------
    def put(self, kind: str, schema: str, content: Any, *, fmt: str = "json",
            produced_by: str | None = None, summary: dict[str, Any] | None = None,
            null_result: bool = False) -> Handle:
        """Store `content` (JSON-able object, list of rows, or raw bytes)."""
        raw = content if isinstance(content, (bytes, bytearray)) else canonical_json(content)
        sha = sha256_hex(kind.encode() + b"\0" + schema.encode() + b"\0" + bytes(raw))
        handle = f"{HANDLE_PREFIX}{self.run_id}/{kind}/{sha[:16]}"
        path = self.obj_dir / f"{sha[:16]}.{fmt}"
        if fmt == "parquet":
            self._write_parquet(path, content)
        elif not path.exists():
            path.write_bytes(bytes(raw))
        self.db.execute(
            "INSERT OR IGNORE INTO objects VALUES (?,?,?,?,?,?,?,?,?)",
            (handle, kind, schema, str(path.relative_to(self.run_dir)), fmt, path.stat().st_size,
             produced_by, time.time(), json.dumps(summary or {}, ensure_ascii=False)),
        )
        self.db.commit()
        preview = content[:PREVIEW_MAX] if isinstance(content, list) else []
        return Handle(handle=handle, kind=kind, schema=schema, summary=summary or {},
                      preview=preview, produced_by=produced_by, null_result=null_result)

    # ---- read ------------------------------------------------------------
    def meta(self, handle: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT handle, kind, schema, path, fmt, size, produced_by, summary FROM objects WHERE handle=?",
            (handle,),
        ).fetchone()
        if not row:
            raise KeyError(handle)
        m = dict(zip(["handle", "kind", "schema", "path", "fmt", "size", "produced_by", "summary"], row))
        m["summary"] = json.loads(m["summary"] or "{}")
        return m

    def kind_of(self, handle: str) -> str:
        return self.meta(handle)["kind"]

    def load(self, handle: str) -> Any:
        m = self.meta(handle)
        p = self.run_dir / m["path"]
        if m["fmt"] == "json":
            return json.loads(p.read_bytes())
        if m["fmt"] == "parquet":
            import pyarrow.parquet as pq
            return pq.read_table(p).to_pylist()
        return p.read_bytes()

    def materialize(self, handle: str, columns: Iterable[str] | None = None,
                    offset: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Projection over a row table. The only way full content reaches a model or UI."""
        rows = self.load(handle)
        if not isinstance(rows, list):
            raise TypeError(f"{handle} is not a row table")
        cols = list(columns) if columns else None
        out = rows[offset: offset + limit]
        return [{k: r.get(k) for k in cols} for r in out] if cols else out

    def handles(self) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT handle FROM objects")}

    # ---- helpers ---------------------------------------------------------
    @staticmethod
    def _write_parquet(path: Path, rows: Any) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq
        if not path.exists():
            pq.write_table(pa.Table.from_pylist(rows), path)
