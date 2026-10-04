"""Event-authoritative local queue and fixed POSIX guardian supervision.

Only fixed OpenMM/ProLIF/fpocket/RDKit-ligand/qvina-docking/OpenMM-mutation-model workers and internal lifecycle
fixtures can dispatch.
Fixtures are injected by Python tests, never selected by an API field.
"""
from __future__ import annotations

import fcntl
import hashlib
import itertools
import json
import math
import os
import re
import select
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import ParseError

import psutil

from ..core.contracts import check_args
from ..core.errors import FailureClass, ToolFailure
from ..core.events import idempotency_key
from ..core.handles import RUN_ID_RE, canonical_json
from ..mutation_model_constants import PROTOCOL as MUTATION_MODEL_PROTOCOL
from ..mutation_model_constants import TIMEOUT_DEFAULT_S as MUTATION_TIMEOUT_DEFAULT_S
from ..mutation_model_constants import TIMEOUT_MAX_S as MUTATION_TIMEOUT_MAX_S
from ..runtime.orchestrator import (
    ApprovalRequired,
    ExecutionLink,
    ExecutionStopped,
    Run,
    RunCancelled,
    checked_link,
    link_fields,
)
from ..tools.energetic import JOB_PROTOCOLS, require_protocol
from ..tools.openmm_method import PROTOCOL as OPENMM_PROTOCOL
from ..tools.openmm_method import preflight
from .process_identity import IdentityUnavailable, capture, matches, supported, valid

GUARDIAN = Path(__file__).with_name("guardian.py").resolve()
CHEMICAL_PROTOCOLS = frozenset({"prolif_prepare_v1", "prolif_detect_v1"})
POCKET_PROTOCOL = "fpocket_detect_v1"
POCKET_STAGED_LIMIT = 48 * 1024 * 1024
LIGAND_PROTOCOLS = frozenset({"rdkit_inspect_v1", "rdkit_enumerate_v1"})
DOCKING_PROTOCOL = "qvina_dock_v1"  # M18; job timeout bound 900 s (the generic bound below)
BATCH_PROTOCOL = "qvina_batch_dock_v1"  # M19; its own job timeout bound and one attempt (no automatic retry)
BATCH_TIMEOUT_MAX_S = 7800  # = docking_batch_constants.TIMEOUT_MAX_S (in-job clock 7200 s + finishing margin)
# M22 qvina_ga_dock_v1: its own job timeout bound 15000 s (= ga total_s max 14400 + 600) and no server default; the
# range [ga.total_s + 600, 15000] is checked with its arguments (invalid_job_arguments) by ligand_ga_inputs. One attempt.
GA_PROTOCOL = "qvina_ga_dock_v1"
GA_TIMEOUT_MAX_S = 15000    # = ligand_ga_constants.TIMEOUT_MAX_S
SUMMARY_PROTOCOLS = frozenset({BATCH_PROTOCOL, GA_PROTOCOL})   # one attempt; staged results + summary after cleanup
# M21 openmm_mutation_model_v1: its own job timeout bound 240 s (default 120 s), checked with its arguments
# (argument_invalid) by mutation_model_bundle.admission; MUTATION_TIMEOUT_MAX_S/DEFAULT_S are imported above.
DEFAULT_TIMEOUT_S = 60      # every other protocol's default when the JobSubmit field is absent
CHEMICAL_DERIVED_KINDS = frozenset({"chemical_preparation_manifest", "chemical_structure",
                                    "chemical_graph", "chemical_interaction_set"})
CHEMICAL_INPUT_REASONS = frozenset({"ligand_disconnected", "stereo_unsupported", "stereo_conflict",
                                    "ligand_chemistry_invalid", "receptor_graph_invalid",
                                    "ligand_graph_invalid", "histidine_ring_graph",
                                    "histidine_charge_state", "histidine_alias_state"})
_CHEMICAL_OUTPUTS = {
    "prolif_prepare_v1": ("chemical_preparation_manifest", "chemical_structure", "chemical_graph"),
    "prolif_detect_v1": ("chemical_interaction_set",),
}
FIXTURE_MODES = frozenset({"normal", "nonzero", "malformed", "oversize", "wrong_id", "invalid",
                           "sleep", "grandchild", "leader_exit"})
TERMINAL = frozenset({"done", "failed", "cancelled", "interrupted"})
MAX_CONTROL = 8192
# Root-wide unclosed-job scan bounds (see _unclosed_jobs); exceeding any fails closed.
MAX_GLOBAL_RUN_ENTRIES = 1000
MAX_GLOBAL_LIFECYCLE_EVENTS = 250_000
MAX_GLOBAL_EVENT_LINE = 256 * 1024 * 1024
MAX_GLOBAL_SCAN_S = 20.0
_GLOBAL_LOCK_GUARD = threading.Lock()
_GLOBAL_LOCAL_LOCKS: dict[str, threading.Lock] = {}


def require_completed_chemical_handle(run: Run, handle: str) -> dict[str, Any]:
    """Admit a derived object only through a completed fixed-protocol publication.

    An identical-byte retry can reuse an object first created by an interrupted
    attempt. Its successful candidate/terminal, rather than the original
    produced_by field, is the authority for public availability.
    """
    meta = run.store.meta(handle)
    if meta["kind"] not in CHEMICAL_DERIVED_KINDS:
        return meta
    if meta["schema"] != f"{meta['kind']}@1":
        raise ToolFailure(FailureClass.input_invalid, "unsupported chemical object schema")
    events = list(run.events.read())
    created = [event for event in events if event["type"] == "object_created" and
               event.get("handle") == handle and event.get("kind") == meta["kind"] and
               event.get("schema") == meta["schema"]]
    if len(created) != 1:
        raise ToolFailure(FailureClass.input_invalid, "chemical object has no unique creation evidence")
    submissions = {event["job"]["job_id"]: event["job"] for event in events
                   if event["type"] == "job_submitted"}
    for candidate in events:
        if candidate["type"] != "job_result_candidate":
            continue
        job = submissions.get(candidate.get("job_id"))
        if job is None or job.get("protocol_id") not in _CHEMICAL_OUTPUTS:
            continue
        protocol = job["protocol_id"]
        expected = _CHEMICAL_OUTPUTS[protocol]
        outputs = candidate.get("output_handles")
        if (meta["kind"] not in expected or type(outputs) is not list or len(outputs) != len(expected) or
                handle not in outputs or outputs[expected.index(meta["kind"])] != handle):
            continue
        tool = {"prolif_prepare_v1": "prepare_chemical_structure",
                "prolif_detect_v1": "compute_chemical_interactions"}[protocol]
        if job.get("tool_id") != tool:
            continue
        try:
            if any((item_meta["kind"], item_meta["schema"]) != (kind, f"{kind}@1")
                   for item_meta, kind in ((run.store.meta(item), kind)
                                           for item, kind in zip(outputs, expected, strict=True))):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        attempt = candidate.get("attempt_id")
        reserved = [event for event in events if event["type"] == "budget_reserved" and
                    event.get("attempt_id") == attempt and event.get("root_call_id") == job["job_id"] and
                    event.get("tool") == tool]
        dispatched = [event for event in events if event["type"] == "job_dispatch_intent" and
                      event.get("job_id") == job["job_id"] and event.get("attempt_id") == attempt]
        cleaned = [event for event in events if event["type"] == "job_cleanup_verified" and
                   event.get("job_id") == job["job_id"] and event.get("attempt_id") == attempt and
                   event.get("group_empty") is True]
        if (len(reserved) != 1 or len(dispatched) != 1 or len(cleaned) != 1 or
                not (reserved[0]["seq"] < dispatched[0]["seq"] < cleaned[0]["seq"] < candidate["seq"])):
            continue
        if created[0]["seq"] >= candidate["seq"]:
            continue
        try:
            if protocol == "prolif_prepare_v1":
                payload = run.store.load_bounded_json(outputs[0], 8 * 1024 * 1024)
                params = job.get("parameters")
                if type(params) is not dict:
                    continue
                expected_inputs = ([params[key] for key in ("complex_handle", "receptor_input_handle",
                                                          "ligand_sdf_handle") if key in params] +
                                   ([params["connectivity"]["sidecar_handle"]] if
                                    params.get("connectivity", {}).get("sidecar_handle") else []))
                expected_source = params.get("complex_handle", params.get("receptor_input_handle"))
                if (payload.get("request") != params or
                        payload.get("source_handle") != expected_source or
                        job.get("input_handles") != expected_inputs):
                    continue
            else:
                payload = run.store.load_bounded_json(handle, 8 * 1024 * 1024)
                if (payload.get("graph_handle") != job.get("parameters", {}).get("graph_handle") or
                        job.get("input_handles") != [payload.get("graph_handle")]):
                    continue
        except (KeyError, TypeError, ValueError):
            continue
        if any(event["type"] == "job_terminal" and event.get("job_id") == job["job_id"] and
               event.get("attempt_id") == attempt and event.get("status") == "done" and
               event.get("output_handles") == outputs and event["seq"] > candidate["seq"]
               for event in events):
            return {**meta, "first_creator_attempt_id": created[0].get("produced_by"),
                    "successful_publisher_attempt_id": attempt, "successful_publisher_job_id": job["job_id"]}
    raise ToolFailure(FailureClass.input_invalid, "chemical object has no completed producer")


_LIFECYCLE_MARKER = b'"type": "job_'
# EventLog writes sort_keys JSON with default separators, so for most records the final top-level
# pair before the closing brace is the record type. A record whose tail names a non-lifecycle type
# (object payloads) or job_submitted is skipped unparsed: a submission always precedes its job's
# other records and only ever sets "queued", which is not an unclosed state. A record without that
# tail (a key sorting after "type") falls back to the conservative marker test and is parsed.
_TYPE_TAIL = re.compile(rb', "type": "([A-Za-z0-9_]{1,64})"\}\n\Z')
_UNFOLDED_TYPES = frozenset({b"job_submitted"})


def _unclosed_jobs(root: Path, current_run_id: str, cancelled: Callable[[], bool],
                   lock_deadline: float, scan_deadline: float | None = None) -> list[str]:
    """Durable cross-run guard against an orphan whose parent's flock was lost.

    The ledger is streamed line by line. Lines without a top-level job lifecycle type (object
    payloads) and job_submitted records are skipped without JSON parsing, so the bounds are the
    number of runs, parsed lifecycle records, the longest single record and wall time, never the
    unrelated payload bytes. Exceeding any bound fails closed.
    """
    pending = []
    lifecycle_events = 0
    if scan_deadline is None:
        scan_deadline = time.monotonic() + MAX_GLOBAL_SCAN_S
    directories = list(itertools.islice(root.iterdir(), MAX_GLOBAL_RUN_ENTRIES + 1))
    if len(directories) > MAX_GLOBAL_RUN_ENTRIES:
        raise ToolFailure(FailureClass.precondition, "too many run entries for global job ledger",
                          detail={"reason_code": "global_job_ledger_unavailable"})
    for directory in directories:
        if directory.name == current_run_id or not RUN_ID_RE.fullmatch(directory.name):
            continue
        if directory.is_symlink():
            raise ToolFailure(FailureClass.precondition, "unsafe global job ledger directory",
                              detail={"reason_code": "global_job_ledger_unavailable"})
        if not directory.is_dir():
            continue
        events_path = directory / "events.jsonl"
        if events_path.is_symlink():
            raise ToolFailure(FailureClass.precondition, "unsafe global job ledger file",
                              detail={"reason_code": "global_job_ledger_unavailable"})
        if not events_path.exists():
            continue
        status: dict[str, str] = {}
        cleanup_pending: set[str] = set()
        try:
            lock_path = directory / "events.lock"
            lock_fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
                    raise ValueError("unsafe global event lock")
                while True:
                    if cancelled():
                        raise RunCancelled("run cancelled while checking global job ledger")
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= lock_deadline:
                            raise ToolFailure(FailureClass.precondition,
                                              "global job ledger is locked",
                                              detail={"reason_code": "global_job_ledger_unavailable"})
                        time.sleep(min(0.02, max(0, lock_deadline - time.monotonic())))
                events_fd = os.open(events_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(events_fd, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise ValueError("unsafe global job event ledger")
                    for ordinal in itertools.count(1):
                        line = stream.readline(MAX_GLOBAL_EVENT_LINE + 1)
                        if not line:
                            break
                        if len(line) > MAX_GLOBAL_EVENT_LINE or not line.endswith(b"\n"):
                            raise ValueError("incomplete or oversized global job event record")
                        if time.monotonic() >= scan_deadline:
                            raise ValueError("global job ledger scan exceeded its time bound")
                        tail = _TYPE_TAIL.search(line[-128:])
                        if tail is not None:
                            if not tail.group(1).startswith(b"job_") or tail.group(1) in _UNFOLDED_TYPES:
                                continue
                        elif _LIFECYCLE_MARKER not in line:
                            continue
                        lifecycle_events += 1
                        if lifecycle_events > MAX_GLOBAL_LIFECYCLE_EVENTS:
                            raise ValueError("global job ledger exceeds bounded lifecycle scan")
                        event = json.loads(line)
                        if type(event) is not dict or type(event.get("seq")) is not int or event["seq"] != ordinal:
                            raise ValueError("invalid global job event sequence")
                        kind = event["type"]
                        if kind == "job_submitted":
                            status[event["job"]["job_id"]] = "queued"
                        elif kind == "job_claimed":
                            status[event["job_id"]] = "claimed"
                        elif kind == "job_dispatch_intent":
                            status[event["job_id"]] = "running"
                        elif kind == "job_cleanup_pending":
                            cleanup_pending.add(event["job_id"])
                        elif kind == "job_cleanup_verified":
                            cleanup_pending.discard(event["job_id"])
                        elif kind == "job_terminal":
                            status[event["job_id"]] = event["status"]
                        elif kind == "job_retry_queued":
                            status[event["job_id"]] = "queued"
            finally:
                os.close(lock_fd)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ToolFailure(FailureClass.precondition, "global job ledger cannot be checked",
                              detail={"reason_code": "global_job_ledger_unavailable"}) from exc
        pending.extend(f"{directory.name}/{job_id}" for job_id, state in status.items()
                       if state == "running" or job_id in cleanup_pending)
    return pending


@contextmanager
def _global_worker_slot(run_dir: Path, *, cancelled: Callable[[], bool] | None = None):
    root = run_dir.parent.resolve(strict=True)
    with _GLOBAL_LOCK_GUARD:
        local = _GLOBAL_LOCAL_LOCKS.setdefault(str(root), threading.Lock())
    if not local.acquire(blocking=False):
        raise ToolFailure(FailureClass.transient, "global scientific worker is busy",
                          detail={"reason_code": "global_concurrency_busy", "busy": True})
    root_fd = descriptor = -1
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptor = os.open("jobs.global.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600,
                             dir_fd=root_fd)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("unsafe global job lock")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ToolFailure(FailureClass.transient, "global scientific worker is busy",
                              detail={"reason_code": "global_concurrency_busy", "busy": True}) from exc
        unclosed = _unclosed_jobs(root, run_dir.name,
                                 cancelled or (lambda: (run_dir / "cancel.request").exists()),
                                 time.monotonic() + 1.0)
        if unclosed:
            raise ToolFailure(FailureClass.precondition, "prior scientific worker needs reconciliation",
                              detail={"reason_code": "global_job_cleanup_pending", "jobs": unclosed[:5]})
    except (OSError, ValueError) as exc:
        raise ToolFailure(FailureClass.precondition, "global job lock unavailable",
                          detail={"reason_code": "global_job_ledger_unavailable"}) from exc
    else:
        yield descriptor
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if root_fd >= 0:
            os.close(root_fd)
        local.release()


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
            proc = psutil.Process(pid)
            start = capture(pid)
            if proc.status() == psutil.STATUS_ZOMBIE:
                continue
            uid = proc.uids().real
            session = os.getsid(pid)
            if capture(pid) != start:
                raise IdentityUnavailable("process identity changed during group enumeration")
            if os.getpgid(pid) != pgid:
                continue
            found.append({"pid": pid, "start_identity": start, "uid": uid, "session": session})
        except (psutil.NoSuchProcess, ProcessLookupError):
            continue
    return found


def _same_identity(identity: dict[str, Any]) -> bool:
    try:
        if (not isinstance(identity, dict) or
                any(type(identity[key]) is not int or identity[key] <= 0
                    for key in ("pid", "pgid", "session")) or
                type(identity["uid"]) is not int or identity["uid"] < 0 or
                identity["uid"] != os.getuid() or not valid(identity["start_identity"])):
            return False
        pid = identity["pid"]
        proc = psutil.Process(pid)
        return (matches(pid, identity["start_identity"]) and
                proc.uids().real == identity["uid"] and
                os.getpgid(pid) == identity["pgid"] and os.getsid(pid) == identity["session"] and
                pid == identity["pgid"] == identity["session"] and
                proc.status() != psutil.STATUS_ZOMBIE and matches(pid, identity["start_identity"]))
    except (KeyError, TypeError, ValueError, psutil.Error, IdentityUnavailable,
            ProcessLookupError, PermissionError, OSError):
        return False


def _signal_member(member: dict[str, Any], pgid: int, sig: int) -> None:
    try:
        if (any(type(member[key]) is not int or member[key] <= 0 for key in ("pid", "session")) or
                type(member["uid"]) is not int or member["uid"] < 0 or
                not valid(member["start_identity"])):
            return
        proc = psutil.Process(member["pid"])
        pid = member["pid"]
        if (matches(pid, member["start_identity"]) and proc.uids().real == member["uid"] == os.getuid() and
                os.getpgid(pid) == pgid and os.getsid(pid) == member["session"] and
                proc.status() != psutil.STATUS_ZOMBIE and matches(pid, member["start_identity"])):
            os.kill(member["pid"], sig)
    except (KeyError, TypeError, psutil.Error, IdentityUnavailable, ProcessLookupError, OSError):
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


GO_WAIT_GRACE_S = 5.0
MAX_GO_WAIT_S = 3600.0


def _guardian_argv(control_fd: int, global_fd: int | None = None, *, go_wait_s: float = 3.0) -> list[str]:
    """The GO wait bound is the attempt's remaining time plus grace, never unbounded."""
    if not (0 < go_wait_s <= MAX_GO_WAIT_S):  # also rejects nan/inf
        raise ValueError("invalid guardian GO wait bound")
    # abspath retains the venv's executable symlink; resolve() escapes its prefix.
    return [os.path.abspath(sys.executable), "-I", str(GUARDIAN), str(control_fd),
            *([str(global_fd)] if global_fd is not None else []), f"--go-wait-s={go_wait_s:g}"]


def chemical_capability() -> dict[str, Any]:
    """Validate the fixed, locally provisioned worker without importing its native stack."""
    base = {"protocol": "prolif_prepared_explicit_h@1", "ligand_sdf_variant": "V2000",
            "available": False,
            "supported_limits": {"receptor_atoms": 10_000, "ligand_atoms": 256,
                                 "bonds": 20_000, "input_bytes_per_file": 10 * 1024 * 1024,
                                 "output_bytes": 30 * 1024 * 1024, "assignments": 20_000,
                                 "timeout_s": 120, "rss_bytes": 2 * 1024 * 1024 * 1024}}
    try:
        from ..chemical_bundle import dependency
        value = dependency()
        return {**base, "available": True, "reason_code": None, "reason": None,
                "versions": value["versions"], "worker_sha256": value["worker_sha256"],
                "dependency_manifest_sha256": value["lock_sha256"]}
    except ToolFailure as exc:
        missing = exc.detail.get("reason_code") == "chemical_worker_missing"
        return {**base, "reason_code": "worker_missing" if missing else "worker_version_invalid",
                "reason": exc.message}


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
        # Construction is lock-free and writes nothing: the derived SQLite index is rebuilt lazily
        # by the writers that fold state under the transition lock (claim_next reads it).

    def _state(self) -> dict[str, dict[str, Any]]:
        jobs: dict[str, dict[str, Any]] = {}
        reserved: dict[str, dict[str, Any]] = {}
        root_reservations: dict[tuple[str, str], set[str]] = {}
        candidates: dict[str, list[str]] = {}
        clean: set[str] = set()
        preparations: set[str] = set()
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
                            output_handles=[], failure=None, cleanup_status=None,
                            preparation_handle=None, preparation_attempt_id=None)
                if "execution_link" in event:
                    item["execution_link"] = event["execution_link"]
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
            elif kind == "job_preparation_recorded":
                item = jobs[event["job_id"]]
                attempt_id = event["attempt_id"]
                handles = event["handles"]
                if (item["status"] != "running" or item["attempt_id"] != attempt_id or attempt_id not in clean or
                        attempt_id in preparations or
                        set(handles) != {"manifest", "system_xml", "input_coordinates"}):
                    raise ValueError("invalid preparation event")
                expected_types = {"manifest": ("openmm_preparation_manifest", "openmm_preparation_manifest@1"),
                                  "system_xml": ("openmm_system_xml", "openmm_system_xml@1"),
                                  "input_coordinates": ("openmm_input_coordinates", "openmm_input_coordinates@1")}
                for name, handle in handles.items():
                    meta = self.run.store.meta(handle)
                    if (meta["kind"], meta["schema"]) != expected_types[name]:
                        raise ValueError("wrong preparation object type")
                    self.run.store.load(handle)
                preparations.add(attempt_id)
                item.update(preparation_handle=handles["manifest"], preparation_attempt_id=attempt_id)
            elif kind == "job_cleanup_pending":
                jobs[event["job_id"]].update(cleanup_status="pending", blocked_reason=event["reason"])
            elif kind == "docking_batch_published":
                jobs[event["job_id"]]["batch_summary_handle"] = event["summary_handle"]
            elif kind == "ligand_ga_published":
                jobs[event["job_id"]]["ga_summary_handle"] = event["summary_handle"]
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
                item.update(preparation_handle=None, preparation_attempt_id=None)
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

    # Reads fold one consistent events snapshot (the event log's own shared lock guarantees whole
    # lines) and every durable prefix is a valid state, exactly as events-only replay requires. They
    # therefore neither take the transition lock nor rewrite the derived SQLite index, which with
    # multi-MB M11 job records held the lock for about a second on every status poll. Neither does
    # the constructor, so an HTTP GET (a fresh JobQueue per request) is lock-free end to end.
    def get(self, job_id: str) -> dict[str, Any]:
        state = self._state()
        if job_id not in state:
            raise KeyError(job_id)
        return state[job_id]

    def list(self) -> list[dict[str, Any]]:
        state = self._state()
        return sorted(state.values(), key=lambda item: item["created"], reverse=True)

    def submit(self, protocol: str, args: dict[str, Any], *, timeout_s: float | None = None,
               execution_link: ExecutionLink | None = None) -> dict[str, Any]:
        """``timeout_s`` None is the protocol default (M21: 120 s, every other protocol: 60 s)."""
        link = checked_link(execution_link)
        if not isinstance(protocol, str) or protocol not in JOB_PROTOCOLS:
            raise ToolFailure(FailureClass.input_invalid, "unknown energy protocol")
        if not isinstance(args, dict) or any(key in args for key in
                                              ("argv", "executable", "module", "env", "path", "cwd", "fixture")):
            # M21 keeps its closed admission reasons (a non-object is argument_invalid, these keys are unknown).
            raise ToolFailure(FailureClass.input_invalid, "unsafe job arguments", detail=(
                {"reason_code": "argument_invalid" if not isinstance(args, dict) else "unknown_field"}
                if protocol == MUTATION_MODEL_PROTOCOL else None))
        bound = (BATCH_TIMEOUT_MAX_S if protocol == BATCH_PROTOCOL else
                 GA_TIMEOUT_MAX_S if protocol == GA_PROTOCOL else
                 MUTATION_TIMEOUT_MAX_S if protocol == MUTATION_MODEL_PROTOCOL else
                 120 if protocol in {OPENMM_PROTOCOL, POCKET_PROTOCOL} or protocol in CHEMICAL_PROTOCOLS or
                 protocol in LIGAND_PROTOCOLS else 900)
        if protocol == MUTATION_MODEL_PROTOCOL:
            # Range (0, bound] checked in the admission order (argument_invalid) by mutation_model_bundle.admission.
            timeout_s = MUTATION_TIMEOUT_DEFAULT_S if timeout_s is None else timeout_s
        elif protocol == GA_PROTOCOL:
            # No default (spec 2); (0, bound] and >= ga.total_s + 600 are checked with the arguments
            # (invalid_job_arguments) by ligand_ga_inputs.validate_arguments, whose ceiling is this bound.
            pass
        else:
            timeout_s = DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s
            if (not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or
                    not 0 < timeout_s <= bound):
                raise ToolFailure(FailureClass.input_invalid, "invalid job timeout")
        spec = self.run.registry.specs[JOB_PROTOCOLS[protocol][0]]
        if protocol in CHEMICAL_PROTOCOLS:
            from ..chemical_bundle import detect_selected, prepare_selected

            try:
                if protocol == "prolif_detect_v1":
                    require_completed_chemical_handle(self.run, args["graph_handle"])
                selected = (prepare_selected(self.run.store, args) if protocol == "prolif_prepare_v1"
                            else detect_selected(self.run.store, args))
            except (KeyError, ValueError, TypeError) as exc:
                raise ToolFailure(FailureClass.input_invalid, "invalid chemical job request",
                                  detail={"reason_code": "chemical_input_invalid"}) from exc
            if len(canonical_json(selected)) > 32 * 1024 * 1024:
                raise ToolFailure(FailureClass.resource_exceeded, "staged chemical input exceeds limit")
            normalized = args
        elif protocol == POCKET_PROTOCOL:
            from ..pocket_bundle import submission

            selected, normalized, pocket_pins = submission(self.run, args)
        elif protocol in LIGAND_PROTOCOLS:
            from ..ligand_bundle import submission as ligand_submission

            selected, normalized, input_handles = ligand_submission(self.run, protocol, args)
        elif protocol == DOCKING_PROTOCOL:
            from ..docking_bundle import submission as docking_submission

            selected, normalized, input_handles = docking_submission(self.run, args)
        elif protocol == BATCH_PROTOCOL:
            from ..docking_batch_jobs import submission as batch_submission

            selected, normalized, input_handles = batch_submission(self.run, args)
        elif protocol == GA_PROTOCOL:
            from ..ligand_ga_jobs import submission as ga_submission

            selected, normalized, input_handles = ga_submission(self.run, args, timeout_s)  # timeout <= bound
        elif protocol == MUTATION_MODEL_PROTOCOL:
            from ..mutation_model_bundle import admission as mutation_admission

            mutation_admitted, timeout_s = mutation_admission(self.run, args, timeout_s)
            normalized = mutation_admitted["arguments"]
        else:
            normalized = check_args(spec, args, self.run.store.kind_of)
            for name in spec.accepts:
                value = normalized[name]
                for handle in value if isinstance(value, list) else [value]:
                    self.run.store.load(handle)
        if self.run.dry_run:
            return {"plan_only": True, "protocol_id": protocol, "reason_code": "dry_run",
                    "available": False, "output_handles": [], "normalized_parameters": normalized}
        if (protocol not in CHEMICAL_PROTOCOLS and protocol not in LIGAND_PROTOCOLS and
                protocol not in {OPENMM_PROTOCOL, POCKET_PROTOCOL, DOCKING_PROTOCOL, BATCH_PROTOCOL,
                                 GA_PROTOCOL, MUTATION_MODEL_PROTOCOL}):
            require_protocol(protocol)
            raise AssertionError("unreachable")
        if protocol == OPENMM_PROTOCOL:
            selected = preflight(self.run.store, normalized["structure"], seed=self.run.seed)
            implementation = "openmm_protein_minimize_v1"
            input_handles = [normalized["structure"]]
        elif protocol == POCKET_PROTOCOL:
            from ..pocket_bundle import IMPLEMENTATION, call_key, require_ready, worker_sha256

            require_ready()
            implementation = IMPLEMENTATION
            input_handles = [normalized["structure"]]
        elif protocol in LIGAND_PROTOCOLS:
            from ..ligand_bundle import IMPLEMENTATIONS
            from ..ligand_bundle import call_key as ligand_call_key
            from ..ligand_bundle import require_ready as ligand_ready

            ligand_pins = ligand_ready()
            implementation = IMPLEMENTATIONS[protocol]
        elif protocol == DOCKING_PROTOCOL:
            from ..docking_bundle import IMPLEMENTATION as DOCKING_IMPLEMENTATION
            from ..docking_bundle import call_key as docking_call_key
            from ..docking_bundle import require_ready as docking_ready

            docking_pins = docking_ready()
            implementation = DOCKING_IMPLEMENTATION
        elif protocol == BATCH_PROTOCOL:
            from ..docking_batch_bundle import batch_call_key
            from ..docking_batch_jobs import IMPLEMENTATION as BATCH_IMPLEMENTATION
            from ..docking_batch_jobs import complete_job
            from ..docking_batch_jobs import require_budget as batch_budget
            from ..docking_batch_jobs import require_ready as batch_ready

            docking_pins, batch_pins = batch_ready()
            implementation = BATCH_IMPLEMENTATION
        elif protocol == GA_PROTOCOL:
            from ..ligand_ga_bundle import call_key as ga_call_key
            from ..ligand_ga_jobs import IMPLEMENTATION as GA_IMPLEMENTATION
            from ..ligand_ga_jobs import complete_job as ga_complete_job
            from ..ligand_ga_jobs import require_admission as ga_admission
            from ..ligand_ga_jobs import require_ready as ga_ready

            docking_pins, ga_pins = ga_ready()
            implementation = GA_IMPLEMENTATION
        elif protocol == MUTATION_MODEL_PROTOCOL:
            from ..mutation_model_bundle import IMPLEMENTATION as MUTATION_IMPLEMENTATION
            from ..mutation_model_bundle import call_key as mutation_call_key
            from ..mutation_model_bundle import input_handles as mutation_inputs
            from ..mutation_model_bundle import selection as mutation_selection

            # 412 unavailability, then the M7 preflight (422 openmm_preflight_failed); nothing reserved.
            selected, mutation_pins = mutation_selection(self.run, mutation_admitted)
            implementation = MUTATION_IMPLEMENTATION
            input_handles = mutation_inputs(selected)
        else:
            capability = chemical_capability()
            if not capability["available"]:
                raise ToolFailure(FailureClass.precondition, capability["reason"],
                                  detail={"reason_code": capability["reason_code"]})
            implementation = "prolif_prepared_explicit_h@1"
            input_handles = ([args["graph_handle"]] if protocol == "prolif_detect_v1" else
                             [args[key] for key in ("complex_handle", "receptor_input_handle",
                                                   "ligand_sdf_handle") if key in args] +
                             ([args["connectivity"]["sidecar_handle"]] if
                              args.get("connectivity", {}).get("sidecar_handle") else []))
        key = (call_key(selected, pocket_pins) if protocol == POCKET_PROTOCOL else
               ligand_call_key(protocol, selected, ligand_pins) if protocol in LIGAND_PROTOCOLS else
               docking_call_key(normalized, docking_pins) if protocol == DOCKING_PROTOCOL else
               batch_call_key(selected) if protocol == BATCH_PROTOCOL else
               ga_call_key(selected, docking_pins, ga_pins) if protocol == GA_PROTOCOL else
               mutation_call_key(normalized, mutation_pins) if protocol == MUTATION_MODEL_PROTOCOL else
               idempotency_key(protocol, implementation,
                               {"selected": selected, "parameters": normalized,
                                **({"worker_sha256": capability["worker_sha256"],
                                    "dependency_manifest_sha256": capability["dependency_manifest_sha256"]}
                                   if protocol in CHEMICAL_PROTOCOLS else {})}))
        with self.run._transition():
            state = self._rebuild()
            # M19: only an active or a complete batch with this key is returned; a partial one never blocks.
            existing = (complete_job(self.run, state, key) if protocol == BATCH_PROTOCOL else
                        ga_complete_job(self.run, state, key) if protocol == GA_PROTOCOL else
                        next((job for job in state.values() if job["call_key"] == key), None))
            if link is not None:
                if link.admit is not None:
                    link.admit({"lane": "job", "protocol": protocol, "key": key, "parameters": normalized,
                                "timeout_s": timeout_s,
                                "existing_job_id": existing["job_id"] if existing else None})
                if existing is not None:
                    return self._linked_existing(existing, link)
            if existing is not None:
                return existing
            if protocol == BATCH_PROTOCOL:
                self.run._refresh()
                batch_budget(self.run, selected, docking_pins)  # 429 batch_limit_raise_required, nothing charged
            elif protocol == GA_PROTOCOL:
                self.run._refresh()
                ga_admission(self.run, selected, docking_pins)  # 422 ga_reuse_too_large, 429 ga_limit_raise_required
            job_id = "job_" + uuid.uuid4().hex
            job = {"job_id": job_id, "run_id": self.run.run_id, "root_call_id": job_id,
                   "protocol_id": protocol, "tool_id": JOB_PROTOCOLS[protocol][0], "call_key": key,
                   "implementation_version": implementation,
                   "input_handles": input_handles, "parameters": normalized,
                   "selected": selected, "seed": self.run.seed,
                   "created": time.time(), "timeout_s": timeout_s, "fixture_only": False}
            if protocol in CHEMICAL_PROTOCOLS:
                job["worker_sha256"] = capability["worker_sha256"]
                job["dependency_manifest_sha256"] = capability["dependency_manifest_sha256"]
            elif protocol == POCKET_PROTOCOL:
                job["method"] = pocket_pins
                job["worker_sha256"] = worker_sha256()
            elif protocol in LIGAND_PROTOCOLS:
                job["method"] = ligand_pins
            elif protocol == DOCKING_PROTOCOL:
                job["method"] = docking_pins
            elif protocol == BATCH_PROTOCOL:
                job["method"] = docking_pins  # the rows' M18 pins (row call keys and result checks)
                job["batch_method"] = batch_pins
            elif protocol == GA_PROTOCOL:
                job["method"] = docking_pins  # the individuals' M18 pins (call keys and result checks)
                job["ga_method"] = ga_pins
            elif protocol == MUTATION_MODEL_PROTOCOL:
                job["method"] = mutation_pins  # worker + dependency SHA-256 + fixed method record (rechecked at start)
            self.run.events.append("job_submitted", job=job, **link_fields(link))
            created = self._rebuild()[job_id]
            return created if link is None else {**created, "execution_ownership": "owned"}

    def _linked_existing(self, job: dict[str, Any], link: ExecutionLink) -> dict[str, Any]:
        """Caller holds the transition: ownership comes from the durable submission link only."""
        if job.get("execution_link") == link.record():
            return {**job, "execution_ownership": "owned"}
        if not any(event["type"] == "job_observed" and event.get("job_id") == job["job_id"] and
                   event.get("execution_link") == link.record() for event in self.run.events.read()):
            self.run.events.append("job_observed", job_id=job["job_id"], ownership="observed_shared",
                                   **link_fields(link))
        return {**job, "execution_ownership": "observed_shared"}

    @staticmethod
    def _refuse_unlinked_owned(job: dict[str, Any], owner_active: Callable[[str], bool] | None) -> None:
        """Manual start/retry never drives a workflow-owned job while its execution may (cancel stays manual).

        ``owner_active(execution_id)`` is the caller's read-only check; without it the refusal fails closed.
        Once the owning execution ended, the existing manual start/retry rules apply unchanged.
        """
        owner = job.get("execution_link")
        if owner is not None and (owner_active is None or owner_active(owner["execution_id"])):
            raise ToolFailure(FailureClass.precondition, "job is owned by an analysis execution",
                              detail={"reason_code": "job_owned_by_analysis_execution", "job_id": job["job_id"]})

    @staticmethod
    def _require_owner(job: dict[str, Any], link: ExecutionLink) -> None:
        owner = job.get("execution_link")
        if (owner is None or owner.get("execution_id") != link.execution_id or
                owner.get("step_id") != link.step_id):
            raise ToolFailure(FailureClass.precondition, "job is not owned by this execution",
                              detail={"reason_code": "job_not_owned", "job_id": job["job_id"]})

    def submit_fixture(self, *, timeout_s: float = 3,
                       execution_link: ExecutionLink | None = None) -> dict[str, Any]:
        """Internal test entry point; no public request can select a fixture."""
        link = checked_link(execution_link)
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
            self.run.events.append("job_submitted", job=job, **link_fields(link))
            self._rebuild()
        return self.get(job_id) if link is None else {**self.get(job_id), "execution_ownership": "owned"}

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

    def start(self, job_id: str, *, execution_link: ExecutionLink | None = None,
              owner_active: Callable[[str], bool] | None = None) -> dict[str, Any]:
        """Claim one named job, then use the same owner/guardian path as tests."""
        link = checked_link(execution_link)
        with self.run._owner(), self.run._transition():
            job = self._rebuild().get(job_id)
            if job is None:
                raise KeyError(job_id)
            if link is not None:
                self._require_owner(job, link)
                if link.is_stopped():
                    raise ExecutionStopped("before_start")
            else:
                self._refuse_unlinked_owned(job, owner_active)
            if job["status"] == "queued":
                owner = "owner_" + uuid.uuid4().hex
                self.run.events.append("job_claimed", job_id=job_id, owner_token=owner,
                                       **link_fields(job.get("execution_link")))
                job = self._rebuild()[job_id]
            elif job["status"] == "claimed" and job.get("blocked_reason") in {
                    "approval_or_cancel", "global_concurrency_busy", "global_job_cleanup_pending",
                    "global_job_ledger_unavailable"}:
                owner = job["owner_token"]
            else:
                raise ToolFailure(FailureClass.precondition, "job cannot start from its current state")
        return self.execute_claim(job_id, owner, execution_link=link)

    def request_cancel(self, job_id: str, *, execution_link: ExecutionLink | None = None) -> dict[str, Any]:
        """``execution_link`` makes this a scoped workflow Stop: only the owning execution may cancel."""
        link = checked_link(execution_link)
        with self.run._transition():
            state = self._rebuild()
            if job_id not in state:
                raise KeyError(job_id)
            job = state[job_id]
            if link is not None:
                self._require_owner(job, link)
            if job["status"] in TERMINAL:
                return {"status": "already_terminal", "job": job}
            if not job["cancel_requested"]:
                self.run.events.append("job_cancel_requested", job_id=job_id, **link_fields(link))
            if job["status"] in {"queued", "claimed"}:
                self.run.events.append("job_terminal", job_id=job_id, attempt_id=job["attempt_id"],
                                       status="cancelled", output_handles=[], failure=None,
                                       **link_fields(job.get("execution_link")))
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
                    kind = self.run.store.meta(handle)["kind"]
                    if kind in CHEMICAL_DERIVED_KINDS:
                        limit = (8 * 1024 * 1024 if kind in
                                 {"chemical_preparation_manifest", "chemical_interaction_set"}
                                 else 32 * 1024 * 1024)
                        self.run.store.load_bounded_json(handle, limit)
                    else:
                        self.run.store.load(handle)
            self.run.events.append("job_terminal", job_id=job_id, attempt_id=attempt_id,
                                   status=status, failure=failure, output_handles=handles or [],
                                   **link_fields(job.get("execution_link")))
            return self._rebuild()[job_id]

    def _cleanup_owned(self, identity: dict[str, Any]) -> bool:
        """Signal only members admitted while this launch's guardian is still alive."""
        if not valid(identity.get("start_identity")):
            return False
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
                    if member["uid"] != uid or member["session"] != identity["session"] or member["pid"] == own_pid:
                        continue
                    if member["pid"] == identity["pid"] and (
                            member["start_identity"] != identity["start_identity"]):
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
            if (value["nonce"] != intent["launch_nonce"] or value["uid"] != os.getuid() or
                    not valid(value.get("start_identity"))):
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
            global_fd = dispatch.get("global_fd")
            inherited = (child.fileno(),) if global_fd is None else (child.fileno(), global_fd)
            go_wait_s = min(MAX_GO_WAIT_S, max(0.0, deadline - time.monotonic()) + GO_WAIT_GRACE_S)
            guardian = self._popen(_guardian_argv(child.fileno(), global_fd, go_wait_s=go_wait_s),
                                   cwd=attempt_dir, env=_worker_environment(attempt_dir),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, shell=False, close_fds=True,
                                   pass_fds=inherited, start_new_session=True)
            dispatch["spawned"] = True
            child.close()
            self._barrier("before_hello")
            hello = _message(parent, min(3, max(0, deadline - time.monotonic())))
            if not hello or hello.get("kind") != "HELLO":
                if time.monotonic() >= deadline:
                    raise ToolFailure(FailureClass.resource_exceeded, "job timeout during guardian bootstrap")
                raise ToolFailure(FailureClass.fatal, "guardian bootstrap failed")
            try:
                candidate = {key: hello[key] for key in ("nonce", "pid", "pgid", "session", "start_identity", "uid")}
            except KeyError as exc:
                raise ValueError("malformed guardian identity") from exc
            if (candidate["nonce"] != nonce or candidate["pid"] != guardian.pid or
                    self._read_receipt(job) != candidate or not _same_identity(candidate)):
                raise ToolFailure(FailureClass.fatal, "guardian identity mismatch")
            identity = candidate
            self._barrier("after_hello")
            self.run.events.append("job_launch_identity", job_id=job["job_id"], attempt_id=attempt_id,
                                   identity=identity)
            dispatch["identity"] = identity
            with self.run._transition():
                # Only an up-to-date fold is needed here; the derived SQLite index is not.
                current = self._state()[job["job_id"]]
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
                    except (OSError, psutil.Error, IdentityUnavailable):
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
            if (type(message.get("pid")) is not int or message["pid"] <= 0 or
                    not valid(message.get("start_identity"))):
                raise ValueError("invalid worker start observation")
            self.run.events.append("job_worker_started", job_id=job_id,
                                   attempt_id=attempt_id, pid=message["pid"],
                                   start_identity=message["start_identity"])
            self._barrier("after_worker_started")
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

    def execute_claim(self, job_id: str, owner_token: str, *,
                      execution_link: ExecutionLink | None = None) -> dict[str, Any]:
        link = checked_link(execution_link)

        def cancelled() -> bool:
            if self.run._cancel_path.exists():
                return True
            latest = next((event for event in reversed(list(self.run.events.read()))
                           if event.get("job_id") == job_id and event["type"] in
                           {"job_cancel_requested", "job_terminal", "job_retry_queued"}), None)
            return latest is not None and latest["type"] != "job_retry_queued"

        try:
            with _global_worker_slot(self.run.run_dir, cancelled=cancelled) as global_fd:
                return self._execute_claim_with_slot(job_id, owner_token, global_fd, link)
        except ToolFailure as exc:
            reason = exc.detail.get("reason_code")
            if reason in {"global_concurrency_busy", "global_job_cleanup_pending",
                          "global_job_ledger_unavailable"}:
                # Same owner -> transition order as every other job_blocked writer. The global slot
                # was refused before this claim took the run owner, so nothing here holds it. The
                # owner lock is non-blocking: if another owner is live it progresses this run and
                # the informational block note is skipped; the original refusal still propagates.
                try:
                    with self.run._owner(), self.run._transition():
                        job = self._rebuild().get(job_id)
                        if (job is not None and job["status"] == "claimed" and
                                job["owner_token"] == owner_token and job["blocked_reason"] != reason):
                            self.run.events.append("job_blocked", job_id=job_id, reason=reason)
                except ToolFailure as busy:
                    if busy.detail.get("busy") is not True:
                        raise
            raise

    def _execute_claim_with_slot(self, job_id: str, owner_token: str, global_fd: int,
                                 link: ExecutionLink | None = None) -> dict[str, Any]:
        with self.run._owner():
            self.run.store.rebuild_from_events()
            self.run._refresh()
            job = self.get(job_id)
            if job["status"] != "claimed" or job["owner_token"] != owner_token:
                raise ToolFailure(FailureClass.input_invalid, "job is not owned by this claim")
            if job["fixture_only"]:
                if self._fixture_mode is None:
                    raise ToolFailure(FailureClass.precondition, "internal fixture adapter unavailable")
            elif (job["protocol_id"] not in {OPENMM_PROTOCOL, POCKET_PROTOCOL, *CHEMICAL_PROTOCOLS,
                                             *LIGAND_PROTOCOLS, DOCKING_PROTOCOL, BATCH_PROTOCOL, GA_PROTOCOL,
                                             MUTATION_MODEL_PROTOCOL} or
                  self._fixture_mode is not None):
                raise ToolFailure(FailureClass.precondition, "production adapter unavailable")
            if job["protocol_id"] in CHEMICAL_PROTOCOLS:
                capability = chemical_capability()
                if (not capability["available"] or
                        capability["worker_sha256"] != job.get("worker_sha256") or
                        capability["dependency_manifest_sha256"] != job.get("dependency_manifest_sha256")):
                    raise ToolFailure(FailureClass.precondition, "pinned chemical worker changed or unavailable",
                                      detail={"reason_code": "worker_version_invalid"})
            if job["protocol_id"] == POCKET_PROTOCOL:
                from ..pocket_bundle import capability as pocket_capability
                from ..pocket_bundle import worker_sha256

                capability = pocket_capability()
                if not capability["available"]:
                    raise ToolFailure(FailureClass.precondition, capability["reason"],
                                      detail={"reason_code": capability["status"]})
                if (capability["executable_sha256"] != job["method"]["executable_sha256"] or
                        capability["package_sha256"] != job["method"]["package_sha256"] or
                        worker_sha256() != job["worker_sha256"]):
                    raise ToolFailure(FailureClass.precondition, "pinned fpocket build or worker changed",
                                      detail={"reason_code": "worker_version_invalid"})
            if job["protocol_id"] in LIGAND_PROTOCOLS:
                from ..ligand_bundle import capability as ligand_capability

                capability = ligand_capability()
                if not capability["available"]:
                    raise ToolFailure(FailureClass.precondition, capability["reason"],
                                      detail={"reason_code": capability["reason_code"]})
                if capability["pins"] != job.get("method"):
                    raise ToolFailure(FailureClass.precondition, "pinned RDKit ligand worker changed",
                                      detail={"reason_code": "worker_version_invalid"})
            if job["protocol_id"] == DOCKING_PROTOCOL:
                from ..docking_bundle import capability as docking_capability

                capability = docking_capability()
                if not capability["available"]:
                    raise ToolFailure(FailureClass.precondition, capability["reason"],
                                      detail={"reason_code": capability["reason_code"]})
                if capability["pins"] != job.get("method"):
                    raise ToolFailure(FailureClass.precondition, "pinned qvina docking worker or engine changed",
                                      detail={"reason_code": "worker_version_invalid"})
            if job["protocol_id"] == BATCH_PROTOCOL:
                from ..docking_batch_jobs import require_ready as batch_ready

                if batch_ready() != (job.get("method"), job.get("batch_method")):
                    raise ToolFailure(FailureClass.precondition, "pinned qvina batch worker or engine changed",
                                      detail={"reason_code": "worker_version_invalid"})
            if job["protocol_id"] == GA_PROTOCOL:
                from ..ligand_ga_jobs import require_ready as ga_ready

                if ga_ready() != (job.get("method"), job.get("ga_method")):
                    raise ToolFailure(FailureClass.precondition, "pinned qvina GA worker or engine changed",
                                      detail={"reason_code": "worker_version_invalid"})
            if job["protocol_id"] == MUTATION_MODEL_PROTOCOL:
                from ..mutation_model_bundle import require_ready as mutation_ready

                # 412 openmm_unavailable / pdbfixer_unavailable / process_identity_unavailable before reservation.
                if mutation_ready() != job.get("method"):
                    raise ToolFailure(FailureClass.precondition,
                                      "pinned OpenMM mutation-model worker or engine changed",
                                      detail={"reason_code": "worker_version_invalid"})
            if job["cancel_requested"] or self.run._cancel_path.exists():
                return self._terminal(job_id, None, "cancelled")
            if self.run.dry_run:
                raise ToolFailure(FailureClass.precondition, "fixture execution disabled in dry_run")
            if job["attempt_ordinal"] >= (1 if job["protocol_id"] in SUMMARY_PROTOCOLS else 4):
                raise ToolFailure(FailureClass.resource_exceeded, "root recovery allowance exhausted")
            try:
                supported()
            except IdentityUnavailable as exc:
                raise ToolFailure(FailureClass.precondition, str(exc),
                                  detail={"reason_code": "process_identity_unavailable"}) from exc
            attempt_id = "attempt_" + uuid.uuid4().hex
            nonce = uuid.uuid4().hex
            # Reservation is the only expensive debit, shared with synchronous Run.call.
            self._barrier("before_reservation")
            gate = None
            if link is not None:
                self._require_owner(job, link)

                def gate() -> None:
                    # Held under the reservation transition: scoped stop, then durable attempt count.
                    if link.is_stopped():
                        raise ExecutionStopped("before_attempt")
                    if link.before_attempt is not None:
                        link.before_attempt({"lane": "job", "job_id": job_id, "attempt_id": attempt_id,
                                             "root_call_id": job["root_call_id"], "tool": job["tool_id"],
                                             "protocol": job["protocol_id"],
                                             "attempt_ordinal": job["attempt_ordinal"],
                                             "execution_link": link.record()})
            batch_reused = units = None
            if job["protocol_id"] == BATCH_PROTOCOL:
                from ..docking_batch_jobs import reuse_plan

                # Reuse is decided here, once, under the run owner: the reservation is the new rows (no refund).
                plan = reuse_plan(self.run, job["selected"], job["method"])
                batch_reused = [{"row_index": index, "handle": handle} for index, handle in enumerate(plan)
                                if handle is not None]
                units = len(plan) - len(batch_reused)
            ga_reused = None
            if job["protocol_id"] == GA_PROTOCOL:
                from ..ligand_ga_inputs import reserved_units
                from ..ligand_ga_jobs import reuse_plan as ga_reuse_plan

                # Reuse is decided here, once, under the run owner; the reservation is reserved_units (no refund).
                ga_reused = [{"candidate_id": cid, "handle": handle}
                             for cid, handle in ga_reuse_plan(self.run, job["selected"], job["method"]).items()]
                units = reserved_units(job["selected"]["arguments"]["ga"])
            try:
                self.run.reserve_attempt(attempt_id, job["root_call_id"], job["tool_id"], {},
                                         job_id=job_id, before_reserve=gate,
                                         **({} if units is None else {"units": units}))
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
            except (ApprovalRequired, RunCancelled, ExecutionStopped):
                with self.run._transition():
                    self.run.events.append("job_blocked", job_id=job_id, reason="approval_or_cancel")
                    self._rebuild()
                raise
            started = self.run.monotonic()
            try:
                return self._execute_reserved(job_id, attempt_id, nonce, started, global_fd, link, batch_reused,
                                              ga_reused)
            finally:
                elapsed = max(0.0, self.run.monotonic() - started)
                self.run.events.append("wall_charged", seconds=elapsed, reason="job_attempt", call_id=attempt_id)
                self.run.budget.charge(wall_clock_s=elapsed)
                if self.run._time_left() <= 0:
                    self.run.events.append("checkpoint", reason="budget", axis="wall_clock_s",
                                           usage=self.run.budget.wall_clock_s,
                                           limit=self.run.budget.limits.wall_clock_s)

    def _execute_reserved(self, job_id: str, attempt_id: str, nonce: str,
                          started: float, global_fd: int,
                          link: ExecutionLink | None = None,
                          batch_reused: list[dict[str, Any]] | None = None,
                          ga_reused: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        remaining = self.run._time_left()
        cancelled_after_reservation = False
        with self.run._transition():
            job = self._rebuild()[job_id]
            if job["cancel_requested"] or self.run._cancel_path.exists():
                cancelled_after_reservation = True
            else:
                self.run.events.append("job_dispatch_intent", job_id=job_id, attempt_id=attempt_id,
                                       launch_nonce=nonce, ordinal=job["attempt_ordinal"],
                                       remaining_wall_s=remaining, timeout_s=job["timeout_s"],
                                       **({} if batch_reused is None else {"batch_reused": batch_reused}),
                                       **({} if ga_reused is None else {"ga_reused": ga_reused}),
                                       **link_fields(link if link is not None else job.get("execution_link")))
                self._rebuild()
        if cancelled_after_reservation:
            return self._terminal(job_id, None, "cancelled")
        if batch_reused is not None and len(batch_reused) == len(job["selected"]["rows"]):
            # M19 N = 0: every row is a stored result; no worker or qvina is launched, only the summary is published.
            self.run.events.append("job_cleanup_verified", job_id=job_id, attempt_id=attempt_id, group_empty=True,
                                   source="no_go_or_no_launch", guardian_clean=None)
            return self._finish_batch(self.get(job_id), attempt_id, None, None, None)
        attempt_dir = None
        result = None
        identity = None
        dispatch: dict[str, Any] = {"global_fd": global_fd}
        error: dict[str, Any] | None = None
        try:
            attempt_dir = self._attempt_dir(job_id, attempt_id)
            if job["fixture_only"]:
                data = {"nonce": nonce, "job_id": job_id, "attempt_id": attempt_id,
                        "adapter": "internal_lifecycle_fixture", "fixture_mode": self._fixture_mode}
            else:
                if job["protocol_id"] == POCKET_PROTOCOL:
                    from ..pocket_bundle import stage

                    raw = stage(self.run, job, attempt_id)
                    limit = POCKET_STAGED_LIMIT
                elif job["protocol_id"] in LIGAND_PROTOCOLS:
                    from ..ligand_bundle import STAGED_LIMIT
                    from ..ligand_bundle import stage as ligand_stage

                    raw = ligand_stage(self.run, job, attempt_id)
                    limit = STAGED_LIMIT  # own bound: base64 parent + two 10 MiB block libraries (~41 MiB)
                elif job["protocol_id"] == DOCKING_PROTOCOL:
                    from ..docking_bundle import STAGED_LIMIT as DOCKING_STAGED_LIMIT
                    from ..docking_bundle import stage as docking_stage

                    raw = docking_stage(self.run, job, attempt_id)
                    limit = DOCKING_STAGED_LIMIT  # own bound: base64 receptor + sidecar + one SDF (~40 MiB)
                elif job["protocol_id"] == BATCH_PROTOCOL:
                    from ..docking_batch_jobs import STAGED_LIMIT as BATCH_STAGED_LIMIT
                    from ..docking_batch_jobs import stage as batch_stage

                    raw = batch_stage(self.run, job, attempt_id, {item["row_index"] for item in batch_reused or []})
                    limit = BATCH_STAGED_LIMIT  # the M18 bound: one receptor (+ sidecar) and one parent SDF + rows
                elif job["protocol_id"] == GA_PROTOCOL:
                    from ..ligand_ga_jobs import STAGED_LIMIT as GA_STAGED_LIMIT
                    from ..ligand_ga_jobs import stage as ga_stage

                    raw = ga_stage(self.run, job, attempt_id,
                                   {item["candidate_id"]: item["handle"] for item in ga_reused or []})
                    limit = GA_STAGED_LIMIT  # the M18 bound for the blocks and pool + base64 of 128 MiB reused bytes
                elif job["protocol_id"] == MUTATION_MODEL_PROTOCOL:
                    from ..mutation_model_bundle import STAGED_LIMIT as MUTATION_STAGED_LIMIT
                    from ..mutation_model_bundle import stage as mutation_stage

                    raw = mutation_stage(job)
                    limit = MUTATION_STAGED_LIMIT  # the M7 bound: the same staged M7 protein projection
                else:
                    raw = canonical_json(job["selected"])
                    limit = 32 * 1024 * 1024 if job["protocol_id"] in CHEMICAL_PROTOCOLS else 4_000_000
                if len(raw) > limit:
                    raise ToolFailure(FailureClass.resource_exceeded, "staged scientific input exceeds limit")
                data = {"nonce": nonce, "job_id": job_id, "attempt_id": attempt_id,
                        "adapter": (job["protocol_id"] if job["protocol_id"] in {*CHEMICAL_PROTOCOLS, POCKET_PROTOCOL,
                                                                                 *LIGAND_PROTOCOLS, DOCKING_PROTOCOL,
                                                                                 BATCH_PROTOCOL, GA_PROTOCOL,
                                                                                 MUTATION_MODEL_PROTOCOL}
                                    else "openmm_protein_minimize_v1"),
                        "input_sha256": hashlib.sha256(raw).hexdigest()}
                input_fd = os.open(attempt_dir / "structure.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(input_fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
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
        authenticated_identity = identity or self.get(job_id).get("identity")
        identity = authenticated_identity or self._read_receipt(self.get(job_id))
        try:
            group_clean = (not dispatch.get("spawned") or
                           (identity is None and dispatch.get("reaped") and not dispatch.get("authorized")) or
                           (identity is not None and
                            (not _members(identity["pgid"]) or
                             (authenticated_identity is not None and
                              valid(identity.get("start_identity")) and self._cleanup_owned(identity)))))
        except (OSError, psutil.Error, IdentityUnavailable):
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
        preparation_handles = None if job["fixture_only"] or attempt_dir is None or job["protocol_id"] in {
            *CHEMICAL_PROTOCOLS, POCKET_PROTOCOL, *LIGAND_PROTOCOLS, DOCKING_PROTOCOL, BATCH_PROTOCOL, GA_PROTOCOL,
            MUTATION_MODEL_PROTOCOL} else \
            self._record_preparation(job, attempt_id)
        if job["protocol_id"] in SUMMARY_PROTOCOLS:
            return self._finish_batch(self.get(job_id), attempt_id, attempt_dir, result, error)
        if error is None:
            if result is None:
                error = {"error": "fatal", "message": "missing guardian result"}
            elif result.get("reason") == "timeout":
                error = {"error": "resource_exceeded", "message": "job timeout"}
            elif result.get("reason") == "resource_exceeded":
                error = {"error": "resource_exceeded", "message": "worker memory or output limit exceeded"}
            elif result.get("reason") == "resource_monitor_unavailable":
                error = {"error": "fatal", "message": "worker resource monitoring unavailable"}
            elif result.get("reason") == "cancelled":
                return self._terminal(job_id, attempt_id, "cancelled")
            elif not result.get("clean", False):
                error = {"error": "fatal", "message": "parent cleanup required after guardian result"}
            elif result.get("returncode") != 0 or result.get("unexpected_members"):
                error = (self._chemical_worker_error(job, attempt_dir)
                         if job["protocol_id"] in CHEMICAL_PROTOCOLS and attempt_dir is not None and
                         not result.get("unexpected_members") else
                         self._ligand_worker_error(attempt_dir)
                         if job["protocol_id"] in LIGAND_PROTOCOLS and attempt_dir is not None and
                         not result.get("unexpected_members") else
                         self._docking_worker_error(attempt_dir)
                         if job["protocol_id"] == DOCKING_PROTOCOL and attempt_dir is not None and
                         not result.get("unexpected_members") else
                         self._mutation_worker_error(attempt_dir)
                         if job["protocol_id"] == MUTATION_MODEL_PROTOCOL and attempt_dir is not None and
                         not result.get("unexpected_members") else
                         {"error": "fatal", "message": "worker exit or abandoned helper"})
            else:
                payload = result.get("payload")
                if job["fixture_only"]:
                    if (not isinstance(payload, dict) or payload != {
                            "schema": "lifecycle_fixture@1", "attempt_id": attempt_id,
                            "job_id": job_id, "fixture": True, "ok": True}):
                        error = {"error": "fatal", "message": "invalid bounded lifecycle result"}
                elif (not isinstance(payload, dict) or not isinstance(payload.get("output_sha256"), str) or
                      not isinstance(payload.get("output_bytes"), int)):
                    error = {"error": "fatal", "message": "missing bounded scientific output"}
        if error is not None:
            return self._terminal(job_id, attempt_id, "failed", error)
        assert result is not None
        if job["fixture_only"]:
            out = self.run.store.put("job_lifecycle", "job_lifecycle@1", result["payload"],
                                     produced_by=attempt_id, summary={"fixture_only": True})
            handles = [out.handle]
        else:
            try:
                if job["protocol_id"] in CHEMICAL_PROTOCOLS:
                    handles = self._publish_chemical(job, attempt_id, attempt_dir, result["payload"])
                elif job["protocol_id"] in {POCKET_PROTOCOL, *LIGAND_PROTOCOLS, DOCKING_PROTOCOL,
                                            MUTATION_MODEL_PROTOCOL}:
                    outcome = (self._publish_pocket(job, attempt_id, attempt_dir, result["payload"])
                               if job["protocol_id"] == POCKET_PROTOCOL else
                               self._publish_docking(job, attempt_id, attempt_dir, result["payload"])
                               if job["protocol_id"] == DOCKING_PROTOCOL else
                               self._publish_mutation_model(job, attempt_id, attempt_dir, result["payload"])
                               if job["protocol_id"] == MUTATION_MODEL_PROTOCOL else
                               self._publish_ligand(job, attempt_id, attempt_dir, result["payload"]))
                    if type(outcome) is dict:
                        return self._terminal(job_id, attempt_id, outcome["status"], outcome.get("failure"))
                    handles = outcome
                else:
                    if preparation_handles is None:
                        raise ValueError("complete preparation checkpoint missing")
                    handles = self._publish_openmm(job, attempt_id, attempt_dir, result["payload"])
            except Exception as exc:  # noqa: BLE001 - any parser/validator error in untrusted worker output
                # (IndexError, AttributeError, RecursionError, ...) must end this attempt as a typed
                # failure; escaping here would leave a dispatched job "running" and close the global gate.
                return self._terminal(job_id, attempt_id, "failed",
                                      {"error": "fatal", "message": "invalid scientific output",
                                       "diagnostic": type(exc).__name__})
        self.run.events.append("job_result_candidate", job_id=job_id, attempt_id=attempt_id,
                               output_handles=handles)
        self._barrier("before_terminal")
        return self._terminal(job_id, attempt_id, "done", handles=handles)

    def _chemical_worker_error(self, job: dict[str, Any], attempt_dir: Path) -> dict[str, Any]:
        """Accept only a small pinned-worker diagnostic bound to staged identities."""
        fatal = {"error": "fatal", "message": "worker exit or invalid chemical error envelope"}
        try:
            descriptor = os.open(attempt_dir / "error.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 4096:
                    return fatal
                raw = stream.read(4097)
            if len(raw) != info.st_size:
                return fatal
            data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if (type(data) is not dict or canonical_json(data) != raw or
                    set(data) != {"schema", "error_class", "reason_code", "message",
                                  "source_residues", "source_atoms", "sdf_atom_indices"} or
                    data["schema"] != "chemical_worker_error@1" or
                    data["error_class"] not in {"input_invalid", "fatal"} or
                    type(data["message"]) is not str or not 0 < len(data["message"]) <= 240 or
                    any(type(data[key]) is not list or len(data[key]) > 8 for key in
                        ("source_residues", "source_atoms", "sdf_atom_indices"))):
                return fatal
            if data["error_class"] == "fatal":
                return fatal
            if data["reason_code"] not in CHEMICAL_INPUT_REASONS:
                return fatal
            selected = job["selected"]
            atoms: set[bytes] = set()
            residues: set[bytes] = set()

            def collect(value: Any) -> None:
                if type(value) is dict:
                    if set(value) == {"structure_handle", "residue", "atom_name", "altloc",
                                       "element", "site_index"}:
                        atoms.add(canonical_json(value))
                        residues.add(canonical_json(value["residue"]))
                    for child in value.values():
                        collect(child)
                elif type(value) is list:
                    for child in value:
                        collect(child)

            collect(selected)
            for key, admitted in (("source_residues", residues), ("source_atoms", atoms)):
                values = [canonical_json(item) for item in data[key]]
                if len(set(values)) != len(values) or any(value not in admitted for value in values):
                    return fatal
            max_sdf = (len(selected["ligand_atom_names"]) if job["protocol_id"] == "prolif_prepare_v1"
                       else len(selected["graph"]["ligand_atoms"]))
            indices = data["sdf_atom_indices"]
            if (any(type(item) is not int or not 0 <= item < min(max_sdf, 256) for item in indices) or
                    len(set(indices)) != len(indices)):
                return fatal
            return {"error": "input_invalid", "reason_code": data["reason_code"],
                    "message": data["message"], "source_residues": data["source_residues"],
                    "source_atoms": data["source_atoms"], "sdf_atom_indices": indices}
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            return fatal

    @staticmethod
    def _ligand_worker_error(attempt_dir: Path) -> dict[str, Any]:
        from ..ligand_bundle import worker_error

        return worker_error(attempt_dir)

    @staticmethod
    def _docking_worker_error(attempt_dir: Path) -> dict[str, Any]:
        from ..docking_bundle import worker_error

        return worker_error(attempt_dir)

    @staticmethod
    def _mutation_worker_error(attempt_dir: Path) -> dict[str, Any]:
        from ..mutation_model_bundle import worker_error

        return worker_error(attempt_dir)

    def _read_preparation_checkpoint(self, job_id: str, attempt_id: str) -> bytes | None:
        if not _safe_id(job_id) or not _safe_id(attempt_id):
            return None
        opened: list[int] = []
        try:
            opened.append(os.open(self.run.run_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
            for name in ("jobs", job_id, attempt_id):
                opened.append(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                      dir_fd=opened[-1]))
            opened.append(os.open("preparation.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                  dir_fd=opened[-1]))
            info = os.fstat(opened[-1])
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 64_000_000:
                return None
            chunks = []
            remaining = info.st_size
            while remaining:
                part = os.read(opened[-1], min(1_048_576, remaining))
                if not part:
                    return None
                chunks.append(part)
                remaining -= len(part)
            return b"".join(chunks)
        except OSError:
            return None
        finally:
            for fd in reversed(opened):
                os.close(fd)

    def _record_preparation(self, job: dict[str, Any], attempt_id: str) -> dict[str, str] | None:
        """Ingest only complete fixed-name evidence after verified group cleanup."""
        from ..openmm_bundle import validate_preparation

        existing = [e for e in self.run.events.read() if e["type"] == "job_preparation_recorded" and
                    e.get("job_id") == job["job_id"] and e.get("attempt_id") == attempt_id]
        if existing:
            if len(existing) != 1:
                raise ValueError("duplicate preparation events")
            return existing[0]["handles"]
        if not any(e["type"] == "job_cleanup_verified" and e.get("job_id") == job["job_id"] and
                   e.get("attempt_id") == attempt_id and e.get("group_empty") is True
                   for e in self.run.events.read()):
            raise ValueError("preparation ingestion requires verified cleanup")
        try:
            raw = self._read_preparation_checkpoint(job["job_id"], attempt_id)
            if raw is None:
                return None
            data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if not isinstance(data, dict) or canonical_json(data) != raw:
                return None
            if not isinstance(data.get("system_xml"), str):
                return None
            system_xml = data["system_xml"].encode()
            validate_preparation(self.run.store, job["selected"], data, system_xml)
        except (FileNotFoundError, OSError, ValueError, KeyError, TypeError, UnicodeError,
                ParseError, RuntimeError, OverflowError, StopIteration, ToolFailure):
            return None
        system = self.run.store.put("openmm_system_xml", "openmm_system_xml@1",
                                    system_xml, fmt="xml", produced_by=attempt_id)
        before = self.run.store.put("openmm_input_coordinates", "openmm_input_coordinates@1",
                                    data["input_cif"].encode(), fmt="cif", produced_by=attempt_id)
        prep = self.run.store.put("openmm_preparation_manifest", "openmm_preparation_manifest@1",
                                  {"selected": job["selected"], "selected_sha256": data["selected_sha256"],
                                   "atom_mapping": data["atom_mapping"], "residue_mapping": data["residue_mapping"],
                                   "added_hydrogens": data["added_hydrogens"],
                                   "protonation_variants": data["protonation_variants"],
                                   "disulfide_bonds": data["disulfide_bonds"],
                                   "source_bonds": data["source_bonds"], "final_bonds": data["final_bonds"],
                                   "input_positions_A": data["input_positions_A"],
                                   "input_coordinates": before.handle,
                                   "system_xml": system.handle, "system_xml_sha256": data["system_xml_sha256"],
                                   "topology_sha256": data["topology_sha256"]}, produced_by=attempt_id)
        handles = {"manifest": prep.handle, "system_xml": system.handle, "input_coordinates": before.handle}
        self.run.events.append("job_preparation_recorded", job_id=job["job_id"], attempt_id=attempt_id,
                               handles=handles, checkpoint_sha256=hashlib.sha256(raw).hexdigest())
        return handles

    def _publish_openmm(self, job: dict[str, Any], attempt_id: str,
                        attempt_dir: Path, descriptor: dict[str, Any]) -> list[str]:
        path = attempt_dir / "result.json"
        if path.is_symlink() or not path.is_file() or path.stat().st_size != descriptor["output_bytes"] or path.stat().st_size > 64_000_000:
            raise ValueError("scientific output size mismatch")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != descriptor["output_sha256"]:
            raise ValueError("scientific output hash mismatch")
        data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        selected = job["selected"]
        from ..openmm_bundle import PREPARATION_FIELDS, validate_native

        system_xml = data["system_xml"].encode()
        validate_native(self.run.store, selected, data, system_xml)
        events = [e for e in self.run.events.read() if e["type"] == "job_preparation_recorded" and
                  e.get("job_id") == job["job_id"] and e.get("attempt_id") == attempt_id]
        if len(events) != 1:
            raise ValueError("successful result lacks attempt preparation")
        handles = events[0]["handles"]
        prep_data = self.run.store.load(handles["manifest"])
        recorded = {key: data[key] for key in PREPARATION_FIELDS}
        expected = {"schema": "openmm_preparation_checkpoint@1", **recorded}
        if (hashlib.sha256(canonical_json(expected)).hexdigest() != events[0]["checkpoint_sha256"] or
                prep_data["selected"] != selected or prep_data["selected_sha256"] != expected["selected_sha256"] or
                prep_data["input_positions_A"] != expected["input_positions_A"] or
                prep_data["input_coordinates"] != handles["input_coordinates"] or
                self.run.store.load(handles["system_xml"]) != system_xml or
                self.run.store.load(handles["input_coordinates"]) != data["input_cif"].encode() or
                any(prep_data[key] != data[key] for key in ("atom_mapping", "residue_mapping", "added_hydrogens",
                    "protonation_variants", "disulfide_bonds", "source_bonds", "final_bonds",
                    "system_xml_sha256", "topology_sha256"))):
            raise ValueError("result differs from recorded preparation")
        system_handle, prep_handle, before_handle = (handles["system_xml"], handles["manifest"],
                                                      handles["input_coordinates"])
        final_coordinates = self.run.store.put("openmm_final_coordinates", "openmm_final_coordinates@1",
                                               data["final_cif"].encode(), fmt="cif", produced_by=attempt_id)
        final_structure = self.run.store.put("openmm_minimized_structure", "openmm_minimized_structure@1",
                                             {"coordinates": final_coordinates.handle, "manifest": prep_handle,
                                              "model_number": selected["model_number"],
                                              "source_prepared": selected["structure"]}, produced_by=attempt_id)
        result = {"schema": "openmm_protein_minimization@1", "structure": selected["structure"],
                  "method": selected["method"], "source_handle": selected["source_handle"],
                  "preparation_manifest": prep_handle, "input_coordinates": before_handle,
                  "minimized_structure": final_structure.handle, "final_coordinates": final_coordinates.handle,
                  "system_xml": system_handle, "system_xml_sha256": data["system_xml_sha256"],
                  "topology_sha256": data["topology_sha256"],
                  "before_kJ_mol": data["before_kJ_mol"], "after_kJ_mol": data["after_kJ_mol"],
                  "potential_change_kJ_mol": data["potential_change_kJ_mol"],
                  "input_positions_A": data["input_positions_A"], "final_positions_A": data["final_positions_A"],
                  "atom_count": len(data["atom_mapping"]), "heavy_atom_count": data["heavy_atoms"],
                  "added_hydrogen_count": len(data["added_hydrogens"]),
                  "excluded": selected["excluded"], "source_hydrogens_removed": selected["source_hydrogens_removed"],
                  "convergence": "convergence_not_claimed", "iterations": None,
                  "job_id": job["job_id"], "attempt_id": attempt_id, "seed": selected["seed"]}
        out = self.run.store.put("openmm_minimization", "openmm_protein_minimization@1", result,
                                 produced_by=attempt_id,
                                 summary={"structure": selected["structure"], "job_id": job["job_id"],
                                          "before_kJ_mol": result["before_kJ_mol"],
                                          "after_kJ_mol": result["after_kJ_mol"],
                                          "minimized_structure": final_structure.handle})
        return [out.handle]

    def _publish_chemical(self, job: dict[str, Any], attempt_id: str,
                          attempt_dir: Path, descriptor: dict[str, Any]) -> list[str]:
        from ..chemical_bundle import publish_detect, publish_prepare

        if (set(descriptor) != {"output_sha256", "output_bytes"} or
                type(descriptor["output_bytes"]) is not int or
                not 0 < descriptor["output_bytes"] <= 30 * 1024 * 1024 or
                type(descriptor["output_sha256"]) is not str or
                not re.fullmatch(r"[0-9a-f]{64}", descriptor["output_sha256"])):
            raise ValueError("invalid chemical output descriptor")
        fd = os.open(attempt_dir / "result.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != descriptor["output_bytes"]:
                raise ValueError("chemical output size mismatch")
            raw = stream.read(descriptor["output_bytes"] + 1)
        if (len(raw) != descriptor["output_bytes"] or
                hashlib.sha256(raw).hexdigest() != descriptor["output_sha256"]):
            raise ValueError("chemical output hash mismatch")
        data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if canonical_json(data) != raw or type(data) is not dict:
            raise ValueError("chemical output is not canonical JSON")
        dependency = data.get("dependency")
        if (type(dependency) is not dict or
                dependency.get("worker_sha256") != job["worker_sha256"] or
                dependency.get("lock_sha256") != job["dependency_manifest_sha256"]):
            raise ValueError("chemical output worker identity mismatch")
        if job["protocol_id"] == "prolif_prepare_v1":
            handles = publish_prepare(self.run, job, attempt_id, data)
            expected = ("chemical_preparation_manifest", "chemical_structure", "chemical_graph")
        elif job["protocol_id"] == "prolif_detect_v1":
            handles = publish_detect(self.run, job, attempt_id, data)
            expected = ("chemical_interaction_set",)
        else:
            raise ValueError("unknown chemical publish protocol")
        if (type(handles) is not list or len(handles) != len(expected) or
                any(self.run.store.meta(handle)["kind"] != kind
                    for handle, kind in zip(handles, expected, strict=True))):
            raise ValueError("chemical publisher returned wrong output kinds")
        return handles

    def _publish_pocket(self, job: dict[str, Any], attempt_id: str, attempt_dir: Path,
                        descriptor: dict[str, Any]) -> list[str] | dict[str, Any]:
        """Stale or cancelled completions store nothing; typed native failures stay typed (charged)."""
        from ..pocket_bundle import PocketJobFailure, publish

        with self.run._transition():  # same guard as cancellation and the terminal CAS
            current = self.get(job["job_id"])
            if current["cancel_requested"] or self.run._cancel_path.exists():
                return {"status": "cancelled"}
            if current["status"] in TERMINAL or current["attempt_id"] != attempt_id:
                # Stale completion: _terminal keeps the existing terminal (or rejects the stale attempt).
                return {"status": "failed", "failure": {"error": "fatal", "message": "stale attempt completion"}}
        try:
            return publish(self.run, job, attempt_id, attempt_dir, descriptor)
        except PocketJobFailure as failure:
            return {"status": "failed", "failure": failure.to_error()}

    def _publish_ligand(self, job: dict[str, Any], attempt_id: str, attempt_dir: Path,
                        descriptor: dict[str, Any]) -> list[str] | dict[str, Any]:
        """Same guard as fpocket: a stale or cancelled completion stores nothing; typed failures stay typed."""
        from ..ligand_bundle import LigandJobFailure, publish

        with self.run._transition():
            current = self.get(job["job_id"])
            if current["cancel_requested"] or self.run._cancel_path.exists():
                return {"status": "cancelled"}
            if current["status"] in TERMINAL or current["attempt_id"] != attempt_id:
                return {"status": "failed", "failure": {"error": "fatal", "message": "stale attempt completion"}}
        try:
            return publish(self.run, job, attempt_id, attempt_dir, descriptor)
        except LigandJobFailure as failure:
            return {"status": "failed", "failure": failure.to_error()}

    def _publish_docking(self, job: dict[str, Any], attempt_id: str, attempt_dir: Path,
                         descriptor: dict[str, Any]) -> list[str] | dict[str, Any]:
        """Same guard as fpocket and RDKit: stale or cancelled completions store nothing; typed failures stay typed."""
        from ..docking_bundle import DockingJobFailure, publish

        with self.run._transition():
            current = self.get(job["job_id"])
            if current["cancel_requested"] or self.run._cancel_path.exists():
                return {"status": "cancelled"}
            if current["status"] in TERMINAL or current["attempt_id"] != attempt_id:
                return {"status": "failed", "failure": {"error": "fatal", "message": "stale attempt completion"}}
        try:
            return publish(self.run, job, attempt_id, attempt_dir, descriptor)
        except DockingJobFailure as failure:
            return {"status": "failed", "failure": failure.to_error()}

    def _publish_mutation_model(self, job: dict[str, Any], attempt_id: str, attempt_dir: Path,
                                descriptor: dict[str, Any]) -> list[str] | dict[str, Any]:
        """Same guard as fpocket, RDKit and qvina: stale or cancelled completions store nothing; the size bound is a
        typed (charged) failure."""
        from ..mutation_model_bundle import MutationJobFailure, publish

        with self.run._transition():
            current = self.get(job["job_id"])
            if current["cancel_requested"] or self.run._cancel_path.exists():
                return {"status": "cancelled"}
            if current["status"] in TERMINAL or current["attempt_id"] != attempt_id:
                return {"status": "failed", "failure": {"error": "fatal", "message": "stale attempt completion"}}
        try:
            return publish(self.run, job, attempt_id, attempt_dir, descriptor)
        except MutationJobFailure as failure:
            return {"status": "failed", "failure": failure.to_error()}

    def _existing_attempt_dir(self, job_id: str, attempt_id: str) -> Path | None:
        path = self.run.run_dir / "jobs" / job_id / attempt_id
        if not _safe_id(job_id) or not _safe_id(attempt_id) or path.is_symlink() or not path.is_dir():
            return None
        return path

    def _finish_batch(self, job: dict[str, Any], attempt_id: str, attempt_dir: Path | None,
                      result: dict[str, Any] | None, error: dict[str, Any] | None, *,
                      recovered: bool = False) -> dict[str, Any]:
        """M19 (and M22 GA), after verified group cleanup in every end state: publish the staged rows (GA: newly
        docked individuals), then the summary, then the terminal (``done`` carries the summary handle only). A batch
        that never started a row (a GA that never reached its first individual) has no summary."""
        if job["protocol_id"] == GA_PROTOCOL:
            from ..ligand_ga_jobs import finish
            before_first = "GA worker stopped before its first individual"
        else:
            from ..docking_batch_jobs import finish
            before_first = "batch worker stopped before its first row"

        job_id = job["job_id"]
        with self.run._transition():
            current = self.get(job_id)
            stale = current["status"] in TERMINAL or current["attempt_id"] != attempt_id
        if stale:
            return self._terminal(job_id, attempt_id, "failed", {"error": "fatal", "message": "stale attempt completion"})
        reason = None if result is None else result.get("reason")
        if recovered:   # a cancel the user asked for before the owner was lost stays the first stop
            cause = "cancelled" if current["cancel_requested"] else "worker_failed"
            failure = {"error": "interrupted", "message": "owner lost; group verified stopped"}
        elif result is None and error is None and attempt_dir is None:
            cause, failure = None, None   # N = 0: nothing was launched
        elif error is not None or result is None:
            cause, failure = "worker_failed", error or {"error": "fatal", "message": "missing guardian result"}
        elif reason == "cancelled":
            cause, failure = "cancelled", None
        elif reason == "timeout":
            cause, failure = "time_exhausted", {"error": "resource_exceeded", "message": "job timeout"}
        elif reason == "resource_exceeded":
            cause, failure = "worker_failed", {"error": "resource_exceeded",
                                               "message": "worker memory or output limit exceeded"}
        elif not result.get("clean", False) or result.get("unexpected_members"):
            cause, failure = "worker_failed", {"error": "fatal", "message": "worker exit or abandoned helper"}
        elif result.get("returncode") != 0:
            cause, failure = "worker_failed", self._docking_worker_error(attempt_dir)
        elif reason == "completed":
            cause, failure = None, None
        else:
            cause, failure = "worker_failed", {"error": "fatal", "message": "worker resource monitoring unavailable"}
        try:
            handle = finish(self.run, current, attempt_id, attempt_dir, cause)
        except Exception as exc:  # noqa: BLE001 - untrusted staged output: a typed failure, never a running job
            return self._terminal(job_id, attempt_id, "failed",
                                  {"error": "fatal", "message": "invalid scientific output",
                                   "diagnostic": type(exc).__name__})
        if recovered:
            return self._terminal(job_id, attempt_id, "interrupted", failure)
        if cause == "cancelled":
            return self._terminal(job_id, attempt_id, "cancelled")
        if handle is None or failure is not None:
            return self._terminal(job_id, attempt_id, "failed",
                                  failure or {"error": "fatal", "message": before_first})
        self.run.events.append("job_result_candidate", job_id=job_id, attempt_id=attempt_id, output_handles=[handle])
        self._barrier("before_terminal")
        return self._terminal(job_id, attempt_id, "done", handles=[handle])

    def retry(self, job_id: str, *, execution_link: ExecutionLink | None = None,
              owner_active: Callable[[str], bool] | None = None) -> dict[str, Any]:
        link = checked_link(execution_link)
        with self.run._owner(), self.run._transition():
            self.run._refresh()
            self._settle_terminal_wall()
            job = self._rebuild()[job_id]
            if link is not None:
                self._require_owner(job, link)
            else:
                self._refuse_unlinked_owned(job, owner_active)
            if (job["status"] not in {"failed", "interrupted"} or
                    job["attempt_ordinal"] >= (1 if job["protocol_id"] in SUMMARY_PROTOCOLS else 4)):
                raise ToolFailure(FailureClass.precondition, "job recovery allowance exhausted or not eligible")
            if self.run._cancel_path.exists() or job["cancel_requested"]:
                raise RunCancelled("run cancelled")
            self.run.events.append("job_retry_queued", job_id=job_id, retry_index=job["attempt_ordinal"],
                                   **link_fields(link))
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
                    authenticated_identity = job.get("identity")
                    identity = authenticated_identity or self._read_receipt(job)
                    if identity is None:
                        with self.run._transition():
                            self.run.events.append("job_cleanup_pending", job_id=job["job_id"],
                                                   attempt_id=job["attempt_id"], reason="launch_identity_unknown")
                        continue
                    if _same_identity(identity):
                        end = time.monotonic() + 1.2
                        while time.monotonic() < end and _same_identity(identity):
                            time.sleep(0.02)  # guardian may be cleaning after parent EOF
                    if (authenticated_identity is not None and _same_identity(identity) and
                            not self._cleanup_owned(identity)):
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
                    if not job["fixture_only"] and job["protocol_id"] == OPENMM_PROTOCOL:
                        self._record_preparation(job, job["attempt_id"])
                    if job["protocol_id"] in SUMMARY_PROTOCOLS:
                        # Close as worker_failed and still publish what the attempt durably staged (spec 7.2).
                        self._finish_batch(self.get(job["job_id"]), job["attempt_id"],
                                           self._existing_attempt_dir(job["job_id"], job["attempt_id"]), None, None,
                                           recovered=True)
                        continue
                    self._terminal(job["job_id"], job["attempt_id"], "interrupted",
                                   {"error": "interrupted", "message": "owner lost; group verified stopped"})
                except (OSError, psutil.Error, IdentityUnavailable):
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
