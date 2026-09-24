"""Event-authoritative local queue and fixed POSIX guardian supervision.

Only the internal lifecycle fixture can dispatch in this release. It is injected by
Python tests, never selected by a production request or API field.
"""
from __future__ import annotations

import json
import math
import os
import select
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil

from ..core.contracts import check_args
from ..core.errors import FailureClass, ToolFailure
from ..core.events import idempotency_key
from ..runtime.orchestrator import ApprovalRequired, Run, RunCancelled
from ..tools.energetic import PROTOCOLS, require_protocol

GUARDIAN = Path(__file__).with_name("guardian.py").resolve()
FIXTURE_MODES = frozenset({"normal", "nonzero", "malformed", "oversize", "wrong_id", "invalid",
                           "sleep", "grandchild", "leader_exit"})
TERMINAL = frozenset({"done", "failed", "cancelled", "interrupted"})
MAX_CONTROL = 8192


def _safe_id(value: str) -> bool:
    return value.startswith(("job_", "attempt_")) and len(value) < 100 and all(
        c.isalnum() or c == "_" for c in value)


def _members(pgid: int) -> list[dict[str, Any]]:
    found = []
    for pid in psutil.pids():
        if pid <= 0:
            continue
        try:
            if os.getpgid(pid) != pgid:
                continue
            proc = psutil.Process(pid)  # fresh identity, including on Darwin
            if proc.status() == psutil.STATUS_ZOMBIE:
                continue
            found.append({"pid": pid, "create_time": proc.create_time(), "uid": proc.uids().real})
        except (psutil.NoSuchProcess, ProcessLookupError):
            continue
    return found


def _same_identity(identity: dict[str, Any]) -> bool:
    try:
        pid = identity["pid"]
        proc = psutil.Process(pid)
        return (proc.create_time() == identity["create_time"] and
                proc.uids().real == identity["uid"] and
                os.getpgid(pid) == identity["pgid"] and os.getsid(pid) == identity["session"] and
                pid == identity["pgid"] == identity["session"] and
                proc.status() != psutil.STATUS_ZOMBIE)
    except (KeyError, TypeError, psutil.NoSuchProcess, psutil.AccessDenied,
            ProcessLookupError, PermissionError):
        return False


def _signal_member(member: dict[str, Any], pgid: int, sig: int) -> None:
    try:
        proc = psutil.Process(member["pid"])
        if (proc.create_time() == member["create_time"] and proc.uids().real == member["uid"] and
                os.getpgid(member["pid"]) == pgid and proc.status() != psutil.STATUS_ZOMBIE):
            os.kill(member["pid"], sig)
    except (psutil.NoSuchProcess, ProcessLookupError):
        pass


def _message(sock: socket.socket, timeout: float) -> dict[str, Any] | None:
    end = time.monotonic() + max(0, timeout)
    data = bytearray()
    while len(data) < MAX_CONTROL:
        ready, _, _ = select.select([sock], [], [], max(0, end - time.monotonic()))
        if not ready:
            if data:
                raise ValueError("incomplete guardian message")
            return {}
        part = sock.recv(1)
        if not part:
            return None
        if part == b"\n":
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError("invalid guardian message")
            return value
        data.extend(part)
    raise ValueError("oversized guardian message")


def _worker_environment(attempt_dir: Path) -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1", "TMPDIR": str(attempt_dir)}


def _guardian_argv(control_fd: int) -> list[str]:
    # abspath retains the venv's executable symlink; resolve() escapes its prefix.
    return [os.path.abspath(sys.executable), "-I", str(GUARDIAN), str(control_fd)]


def _send(sock: socket.socket, value: dict[str, Any]) -> None:
    raw = json.dumps(value, separators=(",", ":")).encode()
    if len(raw) >= MAX_CONTROL:
        raise ValueError("oversized control request")
    sock.sendall(raw + b"\n")


class JobQueue:
    def __init__(self, run: Run, *, fixture_mode: str | None = None,
                 barrier: Callable[[str], None] | None = None,
                 popen: Callable[..., subprocess.Popen] = subprocess.Popen) -> None:
        self.run = run
        if fixture_mode is not None and fixture_mode not in FIXTURE_MODES:
            raise ValueError("unknown internal fixture")
        self._fixture_mode = fixture_mode
        self._barrier = barrier or (lambda stage: None)
        self._popen = popen
        self.path = run.run_dir / "jobs.sqlite"
        if self.path.is_symlink():
            raise ValueError("unsafe job index")
        with self.run._transition():
            self._rebuild()

    def _state(self) -> dict[str, dict[str, Any]]:
        jobs: dict[str, dict[str, Any]] = {}
        reserved: dict[str, dict[str, Any]] = {}
        root_reservations: dict[tuple[str, str], set[str]] = {}
        candidates: dict[str, list[str]] = {}
        clean: set[str] = set()
        for event in self.run.events.read():
            kind = event["type"]
            if kind == "budget_reserved" and event.get("attempt_id"):
                reserved[event["attempt_id"]] = event
                key = (event.get("root_call_id"), event.get("tool"))
                root_reservations.setdefault(key, set()).add(event["attempt_id"])
                for item in jobs.values():
                    if (item["root_call_id"], item["tool_id"]) == key:
                        item["attempt_ordinal"] = len(root_reservations[key])
            elif kind == "job_submitted":
                item = dict(event["job"])
                item.update(status="queued", blocked_reason=None, cancel_requested=False,
                            owner_token=None, attempt_id=None,
                            attempt_ordinal=len(root_reservations.get(
                                (item["root_call_id"], item["tool_id"]), set())),
                            output_handles=[], failure=None, cleanup_status=None)
                jobs[item["job_id"]] = item
            elif kind == "job_claimed":
                item = jobs[event["job_id"]]
                if item["status"] != "queued":
                    raise ValueError("invalid job claim event")
                item.update(status="claimed", owner_token=event["owner_token"])
            elif kind == "job_blocked":
                jobs[event["job_id"]]["blocked_reason"] = event["reason"]
            elif kind == "job_cancel_requested":
                jobs[event["job_id"]]["cancel_requested"] = True
            elif kind == "job_dispatch_intent":
                item = jobs[event["job_id"]]
                if (item["status"] != "claimed" or item["cancel_requested"] or
                        event["attempt_id"] not in reserved or
                        reserved[event["attempt_id"]].get("root_call_id") != item["root_call_id"] or
                        reserved[event["attempt_id"]].get("tool") != item["tool_id"] or
                        event["ordinal"] != item["attempt_ordinal"]):
                    raise ValueError("job dispatch lacks an eligible durable reservation")
                item.update(status="running", attempt_id=event["attempt_id"],
                            attempt_ordinal=event["ordinal"], dispatch_intent=event,
                            blocked_reason=None, cleanup_status="pending")
            elif kind == "job_launch_identity":
                if jobs[event["job_id"]]["attempt_id"] != event["attempt_id"]:
                    raise ValueError("stale launch identity")
                jobs[event["job_id"]]["identity"] = event["identity"]
            elif kind == "job_execution_authorized":
                item = jobs[event["job_id"]]
                if item["attempt_id"] != event["attempt_id"] or not item.get("identity"):
                    raise ValueError("unauthenticated execution authorization")
                jobs[event["job_id"]]["authorized"] = True
            elif kind == "job_result_candidate":
                item = jobs[event["job_id"]]
                if item["attempt_id"] != event["attempt_id"]:
                    raise ValueError("stale result candidate")
                candidates[event["attempt_id"]] = event["output_handles"]
            elif kind == "job_cleanup_verified":
                item = jobs[event["job_id"]]
                if item["attempt_id"] != event["attempt_id"] or event.get("group_empty") is not True:
                    raise ValueError("invalid cleanup evidence")
                clean.add(event["attempt_id"])
            elif kind == "job_cleanup_pending":
                jobs[event["job_id"]].update(cleanup_status="pending", blocked_reason=event["reason"])
            elif kind == "job_terminal":
                item = jobs[event["job_id"]]
                if event["status"] not in TERMINAL:
                    raise ValueError("invalid job terminal status")
                if item["status"] in TERMINAL or (item["attempt_id"] and
                                                  event.get("attempt_id") != item["attempt_id"]):
                    raise ValueError("duplicate or stale job terminal event")
                if item["attempt_id"] is not None and item["attempt_id"] not in clean:
                    raise ValueError("terminal job lacks verified cleanup")
                if event["status"] == "done":
                    if (item["attempt_id"] is None or not event["output_handles"] or
                            candidates.get(item["attempt_id"]) != event["output_handles"]):
                        raise ValueError("done job lacks matching candidate")
                    for handle in event["output_handles"]:
                        self.run.store.load(handle)
                item.update(status=event["status"], output_handles=event.get("output_handles", []),
                            failure=event.get("failure"), cleanup_status="verified",
                            finished=event["ts"])
            elif kind == "job_retry_queued":
                item = jobs[event["job_id"]]
                if item["status"] not in {"failed", "interrupted"}:
                    raise ValueError("invalid job retry event")
                item.update(status="queued", owner_token=None, attempt_id=None,
                            cancel_requested=False, failure=None, cleanup_status=None,
                            dispatch_intent=None, identity=None, authorized=False)
        return jobs

    def _connect(self) -> sqlite3.Connection:
        if self.path.is_symlink():
            raise ValueError("unsafe job index")
        db = sqlite3.connect(self.path, timeout=2)
        db.execute("CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, status TEXT NOT NULL, "
                   "created REAL NOT NULL, record TEXT NOT NULL)")
        return db

    def _rebuild(self) -> dict[str, dict[str, Any]]:
        state = self._state()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM jobs")
            db.executemany("INSERT INTO jobs VALUES (?,?,?,?)", [
                (job_id, item["status"], item["created"], json.dumps(item, allow_nan=False))
                for job_id, item in state.items()])
        return state

    def get(self, job_id: str) -> dict[str, Any]:
        with self.run._transition():
            state = self._rebuild()
        if job_id not in state:
            raise KeyError(job_id)
        return state[job_id]

    def list(self) -> list[dict[str, Any]]:
        with self.run._transition():
            state = self._rebuild()
        return sorted(state.values(), key=lambda item: item["created"], reverse=True)

    def submit(self, protocol: str, args: dict[str, Any], *, timeout_s: float = 30) -> dict[str, Any]:
        if not isinstance(protocol, str) or protocol not in PROTOCOLS:
            raise ToolFailure(FailureClass.input_invalid, "unknown energy protocol")
        if not isinstance(args, dict) or any(key in args for key in
                                              ("argv", "executable", "module", "env", "path", "cwd", "fixture")):
            raise ToolFailure(FailureClass.input_invalid, "unsafe job arguments")
        if not math.isfinite(timeout_s) or not 0 < timeout_s <= 900:
            raise ToolFailure(FailureClass.input_invalid, "invalid job timeout")
        # Validate typed scientific handles before capability, even though no engine can run yet.
        spec = self.run.registry.specs[PROTOCOLS[protocol][0]]
        normalized = check_args(spec, args, self.run.store.kind_of)
        for name in spec.accepts:
            value = normalized[name]
            for handle in value if isinstance(value, list) else [value]:
                self.run.store.load(handle)
        if self.run.dry_run:
            return {"plan_only": True, "protocol_id": protocol, "reason_code": "dry_run",
                    "available": False, "output_handles": [], "normalized_parameters": normalized}
        require_protocol(protocol)
        raise AssertionError("unreachable")

    def submit_fixture(self, *, timeout_s: float = 3) -> dict[str, Any]:
        """Internal test entry point; no public request can select a fixture."""
        if self._fixture_mode is None:
            raise ValueError("fixture adapter not configured")
        if not math.isfinite(timeout_s) or not 0 < timeout_s <= 30:
            raise ValueError("invalid fixture timeout")
        job_id = "job_" + uuid.uuid4().hex
        job = {"job_id": job_id, "run_id": self.run.run_id, "root_call_id": job_id,
               "protocol_id": "internal_lifecycle_fixture", "tool_id": "lifecycle_fixture",
               "call_key": idempotency_key("internal_lifecycle_fixture", "fixture@1",
                                           {"mode": self._fixture_mode, "seed": self.run.seed}),
               "implementation_version": "fixture@1",
               "input_handles": [], "parameters": {}, "seed": self.run.seed,
               "created": time.time(), "timeout_s": timeout_s, "fixture_only": True}
        with self.run._transition():
            self.run.events.append("job_submitted", job=job)
            self._rebuild()
        return self.get(job_id)

    def claim_next(self, owner_token: str) -> dict[str, Any] | None:
        if not isinstance(owner_token, str) or not owner_token or len(owner_token) > 100:
            raise ValueError("invalid owner token")
        with self.run._owner(), self.run._transition():
            self._rebuild()
            db = self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT job_id FROM jobs WHERE status='queued' "
                                 "ORDER BY created, job_id LIMIT 1").fetchone()
                if row is None:
                    db.rollback()
                    return None
                self.run.events.append("job_claimed", job_id=row[0], owner_token=owner_token)
                db.execute("UPDATE jobs SET status='claimed' WHERE job_id=? AND status='queued'", (row[0],))
                db.commit()
            finally:
                db.close()
            return self._rebuild()[row[0]]

    def request_cancel(self, job_id: str) -> dict[str, Any]:
        with self.run._transition():
            state = self._rebuild()
            if job_id not in state:
                raise KeyError(job_id)
            job = state[job_id]
            if job["status"] in TERMINAL:
                return {"status": "already_terminal", "job": job}
            if not job["cancel_requested"]:
                self.run.events.append("job_cancel_requested", job_id=job_id)
            if job["status"] in {"queued", "claimed"}:
                self.run.events.append("job_terminal", job_id=job_id, attempt_id=job["attempt_id"],
                                       status="cancelled", output_handles=[], failure=None)
            return {"status": "accepted", "job": self._rebuild()[job_id]}

    def _attempt_dir(self, job_id: str, attempt_id: str) -> Path:
        if not _safe_id(job_id) or not _safe_id(attempt_id):
            raise ValueError("invalid job identifier")
        run_fd = os.open(self.run.run_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                os.mkdir("jobs", mode=0o700, dir_fd=run_fd)
            except FileExistsError:
                pass
            jobs_fd = os.open("jobs", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=run_fd)
            try:
                try:
                    os.mkdir(job_id, mode=0o700, dir_fd=jobs_fd)
                except FileExistsError:
                    pass
                job_fd = os.open(job_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=jobs_fd)
                try:
                    os.mkdir(attempt_id, mode=0o700, dir_fd=job_fd)
                    attempt_fd = os.open(attempt_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                         dir_fd=job_fd)
                    os.close(attempt_fd)
                finally:
                    os.close(job_fd)
            finally:
                os.close(jobs_fd)
        finally:
            os.close(run_fd)
        return self.run.run_dir / "jobs" / job_id / attempt_id

    def _terminal(self, job_id: str, attempt_id: str | None, status: str,
                  failure: dict[str, Any] | None = None, handles: list[str] | None = None) -> dict[str, Any]:
        if status not in TERMINAL:
            raise ValueError("invalid terminal status")
        with self.run._transition():
            job = self._rebuild()[job_id]
            if job["status"] in TERMINAL:
                return job
            if job["attempt_id"] != attempt_id:
                raise ValueError("stale attempt terminal")
            if job["cancel_requested"] or self.run._cancel_path.exists():
                status, handles = "cancelled", []
                failure = {"error": "cancelled", "message": "cancellation accepted before terminal commit"}
            events = list(self.run.events.read())
            if attempt_id is not None and not any(e["type"] == "job_cleanup_verified" and
                                                   e.get("attempt_id") == attempt_id and
                                                   e.get("group_empty") is True for e in events):
                raise ValueError("terminal attempt lacks verified group cleanup")
            if status == "done":
                if not handles or not any(e["type"] == "job_result_candidate" and
                           e.get("attempt_id") == attempt_id and e.get("output_handles") == (handles or [])
                           for e in events):
                    raise ValueError("done attempt lacks matching result candidate")
                for handle in handles or []:
                    self.run.store.load(handle)
            self.run.events.append("job_terminal", job_id=job_id, attempt_id=attempt_id,
                                   status=status, failure=failure, output_handles=handles or [])
            return self._rebuild()[job_id]

    def _cleanup_owned(self, identity: dict[str, Any]) -> bool:
        """Signal only members admitted while this launch's guardian is still alive."""
        pgid = identity["pgid"]
        uid = identity["uid"]
        own_pid = os.getpid()
        cohort: dict[int, dict[str, Any]] = {}

        def scan() -> list[dict[str, Any]]:
            # Enumeration is not atomic with guardian exit or PGID reuse. Both
            # checks must succeed before any newly observed process is owned.
            anchor_before = _same_identity(identity)
            current = _members(pgid)
            if anchor_before and _same_identity(identity):
                for member in current:
                    if member["uid"] != uid or member["pid"] == own_pid:
                        continue
                    if member["pid"] == identity["pid"] and (
                            member["create_time"] != identity["create_time"]):
                        continue
                    # A reused PID cannot replace a previously admitted identity.
                    cohort.setdefault(member["pid"], dict(member))
            return current

        def owned(current: list[dict[str, Any]], *, guardian: bool) -> list[dict[str, Any]]:
            return [cohort[member["pid"]] for member in current
                    if member["pid"] in cohort and member == cohort[member["pid"]]
                    and (guardian or member["pid"] != identity["pid"])]

        current = scan()
        for member in owned(current, guardian=False):
            _signal_member(member, pgid, signal.SIGTERM)
        end = time.monotonic() + 0.7
        while time.monotonic() < end:
            current = scan()
            if not owned(current, guardian=False):
                break
            time.sleep(0.02)
        current = scan()
        for member in owned(current, guardian=False):
            _signal_member(member, pgid, signal.SIGKILL)
        # Keep the guardian as an ownership anchor while descendants are
        # handled. Its own termination happens only after their escalation.
        if _same_identity(identity):
            _signal_member(identity, pgid, signal.SIGTERM)
        end = time.monotonic() + 1
        while time.monotonic() < end:
            current = scan()
            if not current:
                return True
            time.sleep(0.02)
        current = scan()
        if _same_identity(identity):
            _signal_member(identity, pgid, signal.SIGKILL)
            current = scan()
        return not current

    def _read_receipt(self, job: dict[str, Any]) -> dict[str, Any] | None:
        intent = job.get("dispatch_intent")
        if not intent:
            return None
        path = self.run.run_dir / "jobs" / job["job_id"] / intent["attempt_id"] / "bootstrap.receipt"
        try:
            if path.is_symlink() or path.stat().st_size > 2048:
                return None
            value = json.loads(path.read_text())
            if value["nonce"] != intent["launch_nonce"] or value["uid"] != os.getuid():
                return None
            return value
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _supervise(self, job: dict[str, Any], attempt_id: str, nonce: str,
                   attempt_dir: Path, deadline: float,
                   dispatch: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        parent, child = socket.socketpair()
        guardian: subprocess.Popen | None = None
        identity = None
        result = None
        try:
            guardian = self._popen(_guardian_argv(child.fileno()),
                                   cwd=attempt_dir, env=_worker_environment(attempt_dir),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, shell=False, close_fds=True,
                                   pass_fds=(child.fileno(),), start_new_session=True)
            dispatch["spawned"] = True
            child.close()
            self._barrier("before_hello")
            hello = _message(parent, min(3, max(0, deadline - time.monotonic())))
            if not hello or hello.get("kind") != "HELLO":
                if time.monotonic() >= deadline:
                    raise ToolFailure(FailureClass.resource_exceeded, "job timeout during guardian bootstrap")
                raise ToolFailure(FailureClass.fatal, "guardian bootstrap failed")
            identity = {key: hello[key] for key in ("nonce", "pid", "pgid", "session", "create_time", "uid")}
            if (identity["nonce"] != nonce or identity["pid"] != guardian.pid or
                    self._read_receipt(job) != identity or not _same_identity(identity)):
                raise ToolFailure(FailureClass.fatal, "guardian identity mismatch")
            self._barrier("after_hello")
            self.run.events.append("job_launch_identity", job_id=job["job_id"], attempt_id=attempt_id,
                                   identity=identity)
            dispatch["identity"] = identity
            with self.run._transition():
                current = self._rebuild()[job["job_id"]]
                if current["cancel_requested"] or self.run._cancel_path.exists():
                    _send(parent, {"kind": "STOP", "nonce": nonce})
                    guardian.wait(timeout=2)
                    return {"kind": "RESULT", "reason": "cancelled", "clean": True}, identity
                if time.monotonic() >= deadline:
                    _send(parent, {"kind": "STOP", "nonce": nonce})
                    guardian.wait(timeout=2)
                    return {"kind": "RESULT", "reason": "timeout", "clean": True}, identity
                self.run.events.append("job_execution_authorized", job_id=job["job_id"], attempt_id=attempt_id)
                dispatch["authorized"] = True
            _send(parent, {"kind": "GO", "nonce": nonce})
            self._barrier("after_go")
            while True:
                if self.run._cancel_path.exists() or self.get(job["job_id"])["cancel_requested"]:
                    reason = "cancelled"
                elif time.monotonic() >= deadline:
                    reason = "timeout"
                else:
                    reason = None
                if reason is not None:
                    _send(parent, {"kind": "STOP", "nonce": nonce})
                    cleanup_deadline = time.monotonic() + 4
                    result = self._stopped_result(parent, job["job_id"], attempt_id,
                                                  nonce, reason, cleanup_deadline)
                    break
                message = _message(parent, min(0.05, max(0, deadline - time.monotonic())))
                if message is None:
                    raise ToolFailure(FailureClass.fatal, "guardian channel closed")
                if self._record_control(message, job["job_id"], attempt_id, nonce):
                    result = message
                    break
            guardian.wait(timeout=(max(0, cleanup_deadline - time.monotonic())
                                   if reason is not None else 2))
            return result, identity
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise ToolFailure(FailureClass.fatal, "guardian launch or control failure",
                              detail={"diagnostic": type(exc).__name__}) from exc
        finally:
            parent.close()
            child.close()
            if guardian is not None and guardian.poll() is None:
                if identity is not None:
                    try:
                        if not self._cleanup_owned(identity):
                            dispatch["cleanup_error"] = True
                    except (OSError, psutil.Error):
                        dispatch["cleanup_error"] = True
                    if _same_identity(identity):
                        _signal_member(identity, identity["pgid"], signal.SIGKILL)
                else:
                    guardian.terminate()
                try:
                    guardian.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    if identity is not None and _same_identity(identity):
                        _signal_member(identity, identity["pgid"], signal.SIGKILL)
                    elif identity is None:
                        guardian.kill()  # pre-GO direct child, confirmed by Popen.poll
                    try:
                        guardian.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        dispatch["cleanup_error"] = True
            dispatch["reaped"] = guardian is None or guardian.poll() is not None

    def _record_control(self, message: dict[str, Any], job_id: str,
                        attempt_id: str, nonce: str) -> bool:
        if not message:
            return False
        if (message.get("nonce") != nonce or message.get("job_id") != job_id or
                message.get("attempt_id") != attempt_id):
            raise ValueError("guardian control identity mismatch")
        if message.get("kind") == "STARTED":
            if (not isinstance(message.get("pid"), int) or message["pid"] <= 0 or
                    not isinstance(message.get("create_time"), (int, float)) or
                    not math.isfinite(message["create_time"])):
                raise ValueError("invalid worker start observation")
            self.run.events.append("job_worker_started", job_id=job_id,
                                   attempt_id=attempt_id, pid=message["pid"],
                                   create_time=message["create_time"])
            return False
        if message.get("kind") == "RESULT" and isinstance(message.get("clean"), bool) and \
                isinstance(message.get("direct_child_reaped"), bool):
            return True
        raise ValueError("invalid guardian control message")

    def _stopped_result(self, sock: socket.socket, job_id: str, attempt_id: str,
                        nonce: str, reason: str, cleanup_deadline: float) -> dict[str, Any] | None:
        while time.monotonic() < cleanup_deadline:
            message = _message(sock, cleanup_deadline - time.monotonic())
            if message is None:
                return None
            if self._record_control(message, job_id, attempt_id, nonce):
                return {**message, "reason": reason}
        return None

    def execute_claim(self, job_id: str, owner_token: str) -> dict[str, Any]:
        with self.run._owner():
            self.run.store.rebuild_from_events()
            self.run._refresh()
            job = self.get(job_id)
            if job["status"] != "claimed" or job["owner_token"] != owner_token:
                raise ToolFailure(FailureClass.input_invalid, "job is not owned by this claim")
            if self._fixture_mode is None or not job["fixture_only"]:
                raise ToolFailure(FailureClass.precondition, "no production energy adapter")
            if job["cancel_requested"] or self.run._cancel_path.exists():
                return self._terminal(job_id, None, "cancelled")
            if self.run.dry_run:
                raise ToolFailure(FailureClass.precondition, "fixture execution disabled in dry_run")
            if job["attempt_ordinal"] >= 4:
                raise ToolFailure(FailureClass.resource_exceeded, "root recovery allowance exhausted")
            attempt_id = "attempt_" + uuid.uuid4().hex
            nonce = uuid.uuid4().hex
            # Reservation is the only expensive debit, shared with synchronous Run.call.
            self._barrier("before_reservation")
            try:
                self.run.reserve_attempt(attempt_id, job["root_call_id"], job["tool_id"], {},
                                         job_id=job_id)
            except ToolFailure as exc:
                if (exc.cls == FailureClass.precondition and
                        exc.detail.get("reason_code") == "job_cleanup_pending"):
                    with self.run._transition():
                        current = self._rebuild()[job_id]
                        if current["status"] == "claimed" and current["blocked_reason"] != "job_cleanup_pending":
                            self.run.events.append("job_blocked", job_id=job_id,
                                                   reason="job_cleanup_pending")
                            self._rebuild()
                raise
            except (ApprovalRequired, RunCancelled):
                with self.run._transition():
                    self.run.events.append("job_blocked", job_id=job_id, reason="approval_or_cancel")
                    self._rebuild()
                raise
            started = self.run.monotonic()
            try:
                return self._execute_reserved(job_id, attempt_id, nonce, started)
            finally:
                elapsed = max(0.0, self.run.monotonic() - started)
                self.run.events.append("wall_charged", seconds=elapsed, reason="job_attempt", call_id=attempt_id)
                self.run.budget.charge(wall_clock_s=elapsed)
                if self.run._time_left() <= 0:
                    self.run.events.append("checkpoint", reason="budget", axis="wall_clock_s",
                                           usage=self.run.budget.wall_clock_s,
                                           limit=self.run.budget.limits.wall_clock_s)

    def _execute_reserved(self, job_id: str, attempt_id: str, nonce: str,
                          started: float) -> dict[str, Any]:
        remaining = self.run._time_left()
        cancelled_after_reservation = False
        with self.run._transition():
            job = self._rebuild()[job_id]
            if job["cancel_requested"] or self.run._cancel_path.exists():
                cancelled_after_reservation = True
            else:
                self.run.events.append("job_dispatch_intent", job_id=job_id, attempt_id=attempt_id,
                                       launch_nonce=nonce, ordinal=job["attempt_ordinal"],
                                       remaining_wall_s=remaining, timeout_s=job["timeout_s"])
                self._rebuild()
        if cancelled_after_reservation:
            return self._terminal(job_id, None, "cancelled")
        attempt_dir = None
        result = None
        identity = None
        dispatch: dict[str, Any] = {}
        error: dict[str, Any] | None = None
        try:
            attempt_dir = self._attempt_dir(job_id, attempt_id)
            data = {"nonce": nonce, "job_id": job_id, "attempt_id": attempt_id,
                    "adapter": "internal_lifecycle_fixture", "fixture_mode": self._fixture_mode}
            directory_fd = os.open(attempt_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                fd = os.open("input.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory_fd)
                with os.fdopen(fd, "w") as stream:
                    json.dump(data, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            deadline = started + min(remaining, job["timeout_s"])
            result, identity = self._supervise(self.get(job_id), attempt_id, nonce,
                                               attempt_dir, deadline, dispatch)
        except ToolFailure as exc:
            error = exc.to_dict()
        except (OSError, ValueError) as exc:
            error = {"error": "fatal", "message": "launch failed", "diagnostic": type(exc).__name__}
        identity = identity or self.get(job_id).get("identity") or self._read_receipt(self.get(job_id))
        try:
            group_clean = (not dispatch.get("spawned") or
                           (identity is None and dispatch.get("reaped") and not dispatch.get("authorized")) or
                           (identity is not None and
                            (not _members(identity["pgid"]) or self._cleanup_owned(identity))))
        except (OSError, psutil.Error):
            group_clean = False
        if not group_clean:
            with self.run._transition():
                self.run.events.append("job_cleanup_pending", job_id=job_id,
                                       attempt_id=attempt_id, reason="group_not_verified_empty")
                return self._rebuild()[job_id]
        if result is None and dispatch.get("authorized"):
            with self.run._transition():
                self.run.events.append("job_cleanup_pending", job_id=job_id,
                                       attempt_id=attempt_id, reason="guardian_result_missing")
                return self._rebuild()[job_id]
        if (result is not None and not result.get("clean", False) and
                not result.get("direct_child_reaped", False)):
            with self.run._transition():
                self.run.events.append("job_cleanup_pending", job_id=job_id,
                                       attempt_id=attempt_id, reason="guardian_reap_unconfirmed")
                return self._rebuild()[job_id]
        self.run.events.append("job_cleanup_verified", job_id=job_id, attempt_id=attempt_id,
                               group_empty=True,
                               source="parent_group_check" if identity else "no_go_or_no_launch",
                               guardian_clean=result.get("clean") if result else None)
        if error is None:
            if result is None:
                error = {"error": "fatal", "message": "missing guardian result"}
            elif result.get("reason") == "timeout":
                error = {"error": "resource_exceeded", "message": "job timeout"}
            elif result.get("reason") == "cancelled":
                return self._terminal(job_id, attempt_id, "cancelled")
            elif not result.get("clean", False):
                error = {"error": "fatal", "message": "parent cleanup required after guardian result"}
            elif result.get("returncode") != 0 or result.get("unexpected_members"):
                error = {"error": "fatal", "message": "worker exit or abandoned helper"}
            else:
                payload = result.get("payload")
                if (not isinstance(payload, dict) or payload != {
                        "schema": "lifecycle_fixture@1", "attempt_id": attempt_id,
                        "job_id": job_id, "fixture": True, "ok": True}):
                    error = {"error": "fatal", "message": "invalid bounded lifecycle result"}
        if error is not None:
            return self._terminal(job_id, attempt_id, "failed", error)
        assert result is not None
        out = self.run.store.put("job_lifecycle", "job_lifecycle@1", result["payload"],
                                 produced_by=attempt_id, summary={"fixture_only": True})
        self.run.events.append("job_result_candidate", job_id=job_id, attempt_id=attempt_id,
                               output_handles=[out.handle])
        self._barrier("before_terminal")
        return self._terminal(job_id, attempt_id, "done", handles=[out.handle])

    def retry(self, job_id: str) -> dict[str, Any]:
        with self.run._owner(), self.run._transition():
            self.run._refresh()
            self._settle_terminal_wall()
            job = self._rebuild()[job_id]
            if job["status"] not in {"failed", "interrupted"} or job["attempt_ordinal"] >= 4:
                raise ToolFailure(FailureClass.precondition, "job recovery allowance exhausted or not eligible")
            if self.run._cancel_path.exists() or job["cancel_requested"]:
                raise RunCancelled("run cancelled")
            self.run.events.append("job_retry_queued", job_id=job_id, retry_index=job["attempt_ordinal"])
            return self._rebuild()[job_id]

    def _settle_terminal_wall(self) -> None:
        """Recover a crash after terminal commit but before the owner's final charge."""
        events = list(self.run.events.read())
        charged = {e.get("call_id") for e in events if e["type"] == "wall_charged" and
                   e.get("reason") in {"job_attempt", "job_orphan_recovery"}}
        terminal = {e.get("attempt_id"): e for e in events if e["type"] == "job_terminal" and
                    e.get("attempt_id")}
        for intent in events:
            if intent["type"] != "job_dispatch_intent" or intent["attempt_id"] in charged:
                continue
            end = terminal.get(intent["attempt_id"])
            if end is None:
                continue
            elapsed = end["ts"] - intent["ts"]
            if elapsed < 0:
                self.run.events.append("clock_anomaly", attempt_id=intent["attempt_id"],
                                       observed_elapsed_s=elapsed)
            amount = min(max(0.0, elapsed), max(0.0, intent["remaining_wall_s"]),
                         intent["timeout_s"])
            self.run.events.append("wall_charged", seconds=amount, reason="job_orphan_recovery",
                                   call_id=intent["attempt_id"])
            self.run.budget.charge(wall_clock_s=amount)
            if self.run._time_left() <= 0:
                self.run.events.append("checkpoint", reason="budget", axis="wall_clock_s",
                                       usage=self.run.budget.wall_clock_s,
                                       limit=self.run.budget.limits.wall_clock_s)

    def reconcile_run(self) -> list[dict[str, Any]]:
        with self.run._owner():
            self.run.store.rebuild_from_events()
            self.run._refresh()
            self._settle_terminal_wall()
            for job in self.list():
                if job["status"] not in {"claimed", "running"}:
                    continue
                # Close the interrupted UTC interval at recovery start, then charge
                # only actual active cleanup time with the monotonic clock.
                recovery_started = self.run.monotonic()
                attempt = job.get("dispatch_intent")
                if attempt and not any(e["type"] == "wall_charged" and
                                       e.get("call_id") == job["attempt_id"] and
                                       e.get("reason") in {"job_attempt", "job_orphan_recovery"}
                                       for e in self.run.events.read()):
                    elapsed = time.time() - attempt["ts"]
                    if elapsed < 0:
                        self.run.events.append("clock_anomaly", attempt_id=job["attempt_id"],
                                               observed_elapsed_s=elapsed)
                    amount = min(max(0.0, elapsed), max(0.0, attempt["remaining_wall_s"]),
                                 attempt["timeout_s"])
                    self.run.events.append("wall_charged", seconds=amount, reason="job_orphan_recovery",
                                           call_id=job["attempt_id"])
                    self.run.budget.charge(wall_clock_s=amount)
                try:
                    if job["status"] == "claimed":
                        self._terminal(job["job_id"], None, "interrupted",
                                       {"error": "interrupted", "message": "claim owner lost"})
                        continue
                    identity = job.get("identity") or self._read_receipt(job)
                    if identity is None:
                        with self.run._transition():
                            self.run.events.append("job_cleanup_pending", job_id=job["job_id"],
                                                   attempt_id=job["attempt_id"], reason="launch_identity_unknown")
                        continue
                    if _same_identity(identity):
                        end = time.monotonic() + 1.2
                        while time.monotonic() < end and _same_identity(identity):
                            time.sleep(0.02)  # guardian may be cleaning after parent EOF
                    if _same_identity(identity) and not self._cleanup_owned(identity):
                        with self.run._transition():
                            self.run.events.append("job_cleanup_pending", job_id=job["job_id"],
                                                   attempt_id=job["attempt_id"], reason="cleanup_failed")
                        continue
                    if _members(identity["pgid"]):
                        with self.run._transition():
                            self.run.events.append("job_cleanup_pending", job_id=job["job_id"],
                                                   attempt_id=job["attempt_id"], reason="group_identity_ambiguous")
                        continue
                    self.run.events.append("job_cleanup_verified", job_id=job["job_id"],
                                           attempt_id=job["attempt_id"], group_empty=True,
                                           source="orphan_reconciliation")
                    self._terminal(job["job_id"], job["attempt_id"], "interrupted",
                                   {"error": "interrupted", "message": "owner lost; group verified stopped"})
                except (OSError, psutil.Error):
                    with self.run._transition():
                        self.run.events.append("job_cleanup_pending", job_id=job["job_id"],
                                               attempt_id=job["attempt_id"],
                                               reason="process_enumeration_unavailable")
                finally:
                    cleanup_s = max(0.0, self.run.monotonic() - recovery_started)
                    self.run.events.append("wall_charged", seconds=cleanup_s, reason="job_recovery_cleanup",
                                           call_id=job["attempt_id"])
                    self.run.budget.charge(wall_clock_s=cleanup_s)
                    if self.run._time_left() <= 0:
                        self.run.events.append("checkpoint", reason="budget", axis="wall_clock_s",
                                               usage=self.run.budget.wall_clock_s,
                                               limit=self.run.budget.limits.wall_clock_s)
            return self.list()
