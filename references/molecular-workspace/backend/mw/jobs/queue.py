"""Local job queue for PyRosetta (plan §8). One SQLite table, worker processes poll it.

No Celery/Redis. Each job runs in its own subprocess (PyRosetta has global state and a
heavy init), with a hard timeout -> resource_exceeded, and a recorded seed.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from ..core.errors import FailureClass, ToolFailure

SCHEMA = """CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, run_id TEXT, protocol TEXT, params TEXT, seed INTEGER,
  status TEXT, worker TEXT, created REAL, started REAL, finished REAL,
  attempts INTEGER DEFAULT 0, result TEXT, error TEXT)"""


class JobQueue:
    def __init__(self, db_path: Path) -> None:
        self.db = sqlite3.connect(db_path, isolation_level=None)
        self.db.execute(SCHEMA)

    def enqueue(self, run_id: str, protocol: str, params: dict[str, Any], seed: int) -> str:
        jid = "j_" + uuid.uuid4().hex[:8]
        self.db.execute("INSERT INTO jobs (id, run_id, protocol, params, seed, status, created) VALUES (?,?,?,?,?,?,?)",
                        (jid, run_id, protocol, json.dumps(params), seed, "queued", time.time()))
        return jid

    def claim(self, worker: str) -> dict[str, Any] | None:
        self.db.execute("BEGIN IMMEDIATE")
        row = self.db.execute("SELECT id, protocol, params, seed FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
        if not row:
            self.db.execute("COMMIT")
            return None
        self.db.execute("UPDATE jobs SET status='running', worker=?, started=?, attempts=attempts+1 WHERE id=?",
                        (worker, time.time(), row[0]))
        self.db.execute("COMMIT")
        return {"id": row[0], "protocol": row[1], "params": json.loads(row[2]), "seed": row[3]}

    def finish(self, jid: str, result: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> None:
        self.db.execute("UPDATE jobs SET status=?, finished=?, result=?, error=? WHERE id=?",
                        ("failed" if error else "done", time.time(), json.dumps(result), json.dumps(error), jid))

    def get(self, jid: str) -> dict[str, Any]:
        cols = [d[1] for d in self.db.execute("PRAGMA table_info(jobs)")]
        return dict(zip(cols, self.db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()))

    def list(self, run_id: str | None = None) -> list[dict[str, Any]]:
        cols = [d[1] for d in self.db.execute("PRAGMA table_info(jobs)")]
        q = "SELECT * FROM jobs" + (" WHERE run_id=?" if run_id else "") + " ORDER BY created DESC"
        return [dict(zip(cols, r)) for r in self.db.execute(q, (run_id,) if run_id else ())]


def run_job_subprocess(job: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    """Execute one job in a fresh interpreter: python -m mw.jobs.rosetta_worker <json>."""
    try:
        p = subprocess.run([sys.executable, "-m", "mw.jobs.rosetta_worker", json.dumps(job)],
                           capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise ToolFailure(FailureClass.resource_exceeded, f"job {job['id']} exceeded {timeout_s}s",
                          detail={"suggest": "reduce nstruct/iterations or trim the structure"})
    if p.returncode != 0:
        try:
            err = json.loads(p.stdout.strip().splitlines()[-1])
            raise ToolFailure(FailureClass(err["error"]), err["message"])
        except (ValueError, IndexError, KeyError):
            raise ToolFailure(FailureClass.fatal, f"worker crashed: {p.stderr[-400:]}")
    return json.loads(p.stdout.strip().splitlines()[-1])
