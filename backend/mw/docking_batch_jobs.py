"""M19 batch docking job lane on the server side: capability, admission, reuse, staging, publication, validated reads
(spec .dryforge/spec.md 4.5, 5.1-5.3, 6.1, 7.1-7.3, 12).

The server never imports RDKit, Meeko or MDAnalysis and never executes qvina2. ``JobQueue`` calls these functions:

- ``capability`` / ``require_ready``: ``ligand_docking`` (M18 environments, engine hash, worker handshake) plus the
  batch worker and batch constants files. Pins: the M18 pins (a row's call key and result checks are M18's) and the
  two batch file hashes.
- ``submission``: ``docking_batch_inputs.submission`` (every refusal before any job, no budget).
- ``reuse_plan``: per planned row, the validated stored ``docking_result@1`` with the row's full M18 call key, or None.
  Reused rows are not computed and not charged (spec 4.5); ``N`` = the rows left.
- ``stage``: the worker manifest ``docking_batch_worker_input@1``; the receptor and parent blocks are exactly what
  ``docking_bundle.stage`` stages for the first row (bytes re-read from the immutable imports, hashes checked).
- ``finish``: after the attempt's process group is verified empty, in every terminal state, publish each verifiable
  staged row (``rows/<n>.result.json``, converted and checked exactly like an M18 result, then
  ``docking_batch_row_published``) and then the summary ``docking_batch_result@1`` (``docking_batch_published``,
  last). The summary rows come from the staging files and the server's stop cause only (T2 ``build_summary``).
- ``limit_approval``: the human-approved limit raise (spec 6.3), reached only from its HTTP route.
- ``validated_summary`` / ``summary_producer`` / ``complete_job``: reads that re-check the summary, its single
  publication and every per-row result; ``progress``: the job's row counts for polling (no object is loaded).

Staged files are read with ``O_NOFOLLOW``, regular-file and size bounds, canonical JSON only. A worker ``cancelled``
status (written on SIGTERM) is the user's cancel only when the server stopped the job for a cancel; under the job
deadline it is ``time_exhausted``, and under a parent loss or kill it is no status (the row was in progress).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import docking_batch_constants as BC
from . import docking_batch_inputs, docking_bundle
from . import docking_constants as C
from .core.errors import FailureClass, ToolFailure
from .core.handles import canonical_json
from .docking_batch_bundle import (
    REASONS_BY_STATE,
    DockingBatchEvidenceError,
    batch_call_key,
    build_summary,
    check_summary,
    complete_duplicate,
)

ROOT = Path(__file__).resolve().parents[2]
BATCH_WORKER = ROOT / "backend/mw/jobs/docking_batch_worker.py"
BATCH_CONSTANTS = ROOT / "backend/mw/docking_batch_constants.py"
IMPLEMENTATION = "qvina_batch_dock_v1@1"
WORKER_INPUT_SCHEMA = "docking_batch_worker_input@1"
WORKER_OUTPUT_SCHEMA = "docking_batch_worker_output@1"
STAGED_LIMIT = docking_bundle.STAGED_LIMIT        # = the worker's read bound (rows add a few KB each)
MAX_PREPARED_BYTES = 64 * 1024
MAX_END_BYTES = 64 * 1024                         # guardian DOCKING_BATCH_OUTPUT_LIMIT
MAX_STATUS_BYTES = 1024
ACTIVE = ("queued", "claimed", "running")
ID_RE = re.compile(r"(job|attempt)_[0-9a-z_]{1,90}")
WORKER_STOPS = (None, "cancelled", "time_exhausted", "resource_exceeded")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ----------------------------------------------------------------- capability (no RDKit/Meeko here, qvina never run)
def batch_pins() -> dict[str, str]:
    return {"batch_worker_sha256": _sha(BATCH_WORKER.read_bytes()),
            "batch_constants_sha256": _sha(BATCH_CONSTANTS.read_bytes())}


def capability(docking: dict[str, Any] | None = None) -> dict[str, Any]:
    """Available only with ``ligand_docking`` available and the batch worker and constants present; otherwise the
    M18 capability reason (same closed set) and no pins or limits."""
    docking = docking_bundle.capability() if docking is None else docking
    base = {"schema": "docking_batch_capability@1", "protocol_id": BC.PROTOCOL, "tool_id": BC.TOOL,
            "engine": BC.ENGINE, "execution_lane": "durable_job"}

    def unavailable(status: str, reason: str) -> dict[str, Any]:
        return {**base, "available": False, "status": status, "reason_code": status, "reason": reason,
                "pins": None, "batch_pins": None}

    if not docking["available"]:
        return unavailable(docking["reason_code"], docking["reason"])
    try:
        pins = batch_pins()
    except OSError:
        return unavailable("worker_missing", docking_bundle.REASONS["worker_missing"])
    return {**base, "available": True, "status": "ready", "reason_code": None, "reason": None,
            "pins": dict(docking["pins"]), "batch_pins": pins, "methods": dict(C.METHODS),
            "timeout_s": {"max": BC.TIMEOUT_MAX_S},
            "limits": {**BC.LIMITS, "output_bytes": BC.MAX_OUTPUT_BYTES, "summary_bytes": BC.MAX_SUMMARY_BYTES},
            "score_label": C.SCORE_LABEL, "batch_statements": dict(BC.BATCH_STATEMENTS)}


def require_ready() -> tuple[dict[str, Any], dict[str, str]]:
    """(M18 pins, batch pins) recorded at submission (a precondition failure when unavailable)."""
    value = capability()
    if not value["available"]:
        raise ToolFailure(FailureClass.precondition, value["reason"], detail={"reason_code": value["reason_code"]})
    return value["pins"], value["batch_pins"]


# ----------------------------------------------------------------- admission, reuse, duplicates
def submission(run: Any, args: Any) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    return docking_batch_inputs.submission(run, args)


def row_job(job: dict[str, Any], index: int) -> dict[str, Any]:
    """Row ``index`` as the M18 job the per-row checks expect: its own ``docking_selection@1``, the batch's M18 pins."""
    return {**job, "selected": job["selected"]["rows"][index]["selected"]}


def reuse_plan(run: Any, selected: dict[str, Any], pins: dict[str, Any]) -> list[str | None]:
    """Per planned row: a stored result with the row's full M18 call key that still validates, else None."""
    index = docking_batch_inputs.published_m18_results(run.events.read())
    plan: list[str | None] = []
    for row, key in zip(selected["rows"], docking_batch_inputs.row_call_keys(selected, pins), strict=True):
        handle = index.get(key)
        if handle is not None:
            try:
                if docking_bundle.validated_result(run, handle)["input_sha256"] != row["selected"]["input_sha256"]:
                    handle = None
            except docking_bundle.DockingEvidenceError:
                handle = None
        plan.append(handle)
    return plan


def require_budget(run: Any, selected: dict[str, Any], pins: dict[str, Any]) -> int:
    """Admission (spec 6.3): refuse a short budget (429 ``batch_limit_raise_required``, nothing charged); return N."""
    new = sum(handle is None for handle in reuse_plan(run, selected, pins))
    docking_batch_inputs.require_budget(docking_batch_inputs.needed_budget(new), run.budget_snapshot())
    return new


def limit_approval(run: Any, args: Any) -> dict[str, Any]:
    """Spec 6.3: the human-approved limit raise for one batch, called only by its HTTP route (a UI action; never a
    tool, plan or workflow step, model command or loop action). Dry-run runs plan only and refuse it (412 ``dry_run``,
    nothing written). The need is recomputed from the stored results and the current budget (under the run owner),
    and only the shortfall is raised (``docking_batch_inputs.limit_increase``) with one ``budget_limit_updated``
    (by ``human``) carrying the batch context. Nothing short: nothing changes and no event is written. It never
    approves the first expensive call, reserves, charges or refunds anything."""
    if run.dry_run:
        raise ToolFailure(FailureClass.precondition, "dry-run runs plan only; there is no limit to raise",
                          detail={"reason_code": "dry_run"})
    selected, _normalized, _handles = submission(run, args)
    pins, _batch_pins = require_ready()
    new = sum(handle is None for handle in reuse_plan(run, selected, pins))
    needed = docking_batch_inputs.needed_budget(new)

    def plan(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        return docking_batch_inputs.limit_increase(needed, snapshot), {
            "purpose": "docking_batch_limit_raise", "batch_input_sha256": selected["batch_input_sha256"],
            "new_dockings": new, "needed": needed, "shortfall": docking_batch_inputs.shortfall(needed, snapshot)}

    run._refresh()
    increase, context = plan(run.budget_snapshot())
    event = run.raise_limits(plan, by="human") if any(increase.values()) else None
    if event is not None:
        context = event["context"]
    else:
        limits = {axis: run.budget_snapshot()[axis]["limit"] for axis in docking_batch_inputs.AXES}
        context = {**context, "increase": dict.fromkeys(docking_batch_inputs.AXES, 0), "limits_before": limits,
                   "limits_after": limits}
    budget = run.budget_snapshot()
    return {"raised": event is not None, "batch_input_sha256": context["batch_input_sha256"], "new_dockings": new,
            "needed": needed, "shortfall_before": context["shortfall"], "increase": context["increase"],
            "limits_before": context["limits_before"], "limits_after": context["limits_after"],
            "shortfall_after": docking_batch_inputs.shortfall(needed, budget),
            "event_seq": None if event is None else event["seq"], "budget": budget}


def complete_job(run: Any, jobs: Mapping[str, dict[str, Any]], key: str) -> dict[str, Any] | None:
    """Spec 5.3: an active job with this batch call key, else the job of a validated ``complete`` summary with it
    (a ``partial`` summary never deduplicates); None means a new batch job."""
    active = next((job for job in jobs.values() if job["protocol_id"] == BC.PROTOCOL and job["call_key"] == key and
                   job["status"] in ACTIVE), None)
    if active is not None:
        return active
    owners, summaries = {}, []
    for event in run.events.read():
        job = jobs.get(event.get("job_id")) if event["type"] == "docking_batch_published" else None
        if job is None or job["protocol_id"] != BC.PROTOCOL or job["call_key"] != key:
            continue
        try:
            summaries.append((event["summary_handle"], validated_summary(run, event["summary_handle"])))
            owners[event["summary_handle"]] = job
        except DockingBatchEvidenceError:
            continue
    handle = complete_duplicate(summaries, key)
    return None if handle is None else owners[handle]


# ----------------------------------------------------------------- staging
def stage(run: Any, job: dict[str, Any], attempt_id: str, reused: set[int]) -> bytes:
    """The worker manifest; nothing in it is read from the request (selection and immutable imports only)."""
    selected = job["selected"]
    first = json.loads(docking_bundle.stage(run, row_job(job, 0), attempt_id))
    ligand = first["ligand"]
    rows = [{"row_index": row["row_index"], "kind": row["kind"], "reuse": row["row_index"] in reused,
             "candidate": None if row["kind"] == "parent" else row["selected"]["ligand"]["candidate"]}
            for row in selected["rows"]]
    return canonical_json({"schema": WORKER_INPUT_SCHEMA, "receptor": first["receptor"],
                           "parent_sdf": ligand["sdf"] if ligand["source"] == "sdf" else ligand["parent_sdf"],
                           "candidate_set_parent_sha256": selected["candidate_set"]["parent_sha256"],
                           "mode": first["mode"], "box": first["box"], "parameters": first["parameters"],
                           "rows": rows})


# ----------------------------------------------------------------- staged files (bounded, never followed)
def _read(directory: Path | None, name: str, limit: int) -> bytes | None:
    if directory is None:
        return None
    try:
        descriptor = os.open(directory / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            return None
        raw = stream.read(limit + 1)
    return raw if len(raw) <= limit else None


def _canonical(raw: bytes | None) -> Any:
    if not raw:
        return None
    try:
        data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, UnicodeError, RecursionError):
        return None
    return data if canonical_json(data) == raw else None


def _rows_dir(attempt_dir: Path | None) -> Path | None:
    if attempt_dir is None:
        return None
    try:
        return attempt_dir / "rows" if stat.S_ISDIR(os.lstat(attempt_dir / "rows").st_mode) else None
    except OSError:
        return None


def _status(rows: Path | None, index: int) -> dict[str, Any] | None:
    """A status file inside the closed sets, else none (an unreadable status never invalidates the summary)."""
    data = _canonical(_read(rows, f"{index}.status.json", MAX_STATUS_BYTES))
    ok = (type(data) is dict and set(data) == {"state", "reason_code"} and data["state"] in REASONS_BY_STATE and
          data["reason_code"] in REASONS_BY_STATE[data["state"]])
    return data if ok else None


def _end_record(attempt_dir: Path | None, job: dict[str, Any], attempt_id: str) -> dict[str, Any] | None:
    data = _canonical(_read(attempt_dir, "result.json", MAX_END_BYTES))
    ok = (type(data) is dict and set(data) == {"schema", "protocol", "job_id", "attempt_id", "stop_reason"} and
          data["schema"] == WORKER_OUTPUT_SCHEMA and data["protocol"] == BC.PROTOCOL and
          data["job_id"] == job["job_id"] and data["attempt_id"] == attempt_id and data["stop_reason"] in WORKER_STOPS)
    return data if ok else None


def _prepared(attempt_dir: Path | None) -> dict[str, Any] | None:
    data = _canonical(_read(attempt_dir, "prepared.json", MAX_PREPARED_BYTES))
    return data if type(data) is dict and set(data) == {"box", "engine"} else None


def _interpret(status: dict[str, Any] | None, server_cause: str | None) -> dict[str, Any] | None:
    """A worker ``cancelled`` status is written on SIGTERM; only the server knows why it was sent."""
    if status != {"state": "cancelled", "reason_code": "cancelled"} or server_cause == "cancelled":
        return status
    return {"state": "cancelled", "reason_code": "time_exhausted"} if server_cause == "time_exhausted" else None


def progress(run: Any, job: dict[str, Any]) -> dict[str, Any]:
    """Polling view (spec 7.2, 9): rows, reused rows, finished rows (= readable ``rows/*.status.json`` of the attempt)
    and the summary handle once published. Reads the attempt directory listing only; no object is loaded."""
    intent = job.get("dispatch_intent") or {}
    finished = 0
    attempt = job.get("attempt_id")
    if type(attempt) is str and ID_RE.fullmatch(attempt) and ID_RE.fullmatch(job["job_id"]):
        rows = _rows_dir(run.run_dir / "jobs" / job["job_id"] / attempt)
        try:
            finished = 0 if rows is None else sum(entry.name.endswith(".status.json") and
                                                  entry.is_file(follow_symlinks=False) for entry in os.scandir(rows))
        except OSError:
            finished = 0
    return {"rows": len(job["selected"]["rows"]),
            "reused_rows": sorted(item["row_index"] for item in intent.get("batch_reused", [])),
            "finished_rows": finished, "summary_handle": job.get("batch_summary_handle")}


# ----------------------------------------------------------------- publication (after the group is verified empty)
def _publish_row(run: Any, job: dict[str, Any], attempt_id: str, index: int, data: Any) -> tuple[str, dict] | None:
    """The row's worker bytes as an M18 result, with every M18 check; None when it does not validate."""
    try:
        if type(data) is not dict or data.get("job_id") != job["job_id"] or data.get("attempt_id") != attempt_id:
            return None
        view = row_job(job, index)
        content = docking_bundle.result_content(view, data)
        return docking_bundle.store_result(run, view, attempt_id, content), content
    except (docking_bundle.DockingEvidenceError, docking_bundle.DockingJobFailure, ToolFailure, KeyError, TypeError,
            ValueError, IndexError, AttributeError, OSError, RecursionError):
        return None


def finish(run: Any, job: dict[str, Any], attempt_id: str, attempt_dir: Path | None,
           server_cause: str | None) -> str | None:
    """Publish the staged rows and then the summary; return the summary handle, or None when the batch never
    started a row (no ``prepared.json`` and rows left to compute: no summary, spec 4.1/12).

    ``server_cause``: None (the worker ended by itself, or N = 0), ``cancelled`` (user), ``time_exhausted`` (job
    deadline) or ``worker_failed`` (crash, kill, limit, parent loss). Raises on summary evidence errors."""
    selected = job["selected"]
    reused = {item["row_index"]: item["handle"] for item in job["dispatch_intent"]["batch_reused"]}
    prepared = _prepared(attempt_dir)
    if prepared is None and len(reused) < len(selected["rows"]):
        return None
    cause = server_cause
    if cause is None and len(reused) < len(selected["rows"]):
        end = _end_record(attempt_dir, job, attempt_id)
        cause = "worker_failed" if end is None else end["stop_reason"]
    events = list(run.events.read())
    recorded = {event["row_index"]: event["handle"] for event in events
                if event["type"] == "docking_batch_row_published" and event.get("attempt_id") == attempt_id}
    rows_dir = _rows_dir(attempt_dir)
    results: dict[str, Any] = {}
    observations = []
    for row in selected["rows"]:
        index = row["row_index"]
        if index in reused:
            results[reused[index]] = docking_bundle.validated_result(run, reused[index])
            observations.append({"started": False, "status": None, "result_handle": reused[index]})
            continue
        status = _interpret(_status(rows_dir, index), server_cause)
        handle = None
        if status is None or status["state"] in ("scored", "null_result"):
            data = _canonical(_read(rows_dir, f"{index}.result.json", C.MAX_RESULT_BYTES))
            published = None if data is None else _publish_row(run, job, attempt_id, index, data)
            if published is not None:
                handle, results[handle] = published[0], published[1]
                if recorded.get(index) != handle:
                    run.events.append("docking_batch_row_published", job_id=job["job_id"], attempt_id=attempt_id,
                                      row_index=index, handle=handle)
        observations.append({"started": _read(rows_dir, f"{index}.started", 0) == b"", "status": status,
                             "result_handle": handle})
    if prepared is not None:
        box, engine = prepared["box"], prepared["engine"]
    else:
        first = results[reused[min(reused)]]
        box, engine = first["box"], first["engine"]
    content = build_summary(selected, observations=observations, results=results, stop_cause=cause, box=box,
                            engine=engine)
    check_summary(content, selected, results, job["method"])
    out = run.store.put(BC.OUTPUT_KIND, BC.SUMMARY_SCHEMA, content, produced_by=attempt_id,
                        summary={"batch_input_sha256": content["batch_input_sha256"], "mode": content["inputs"]["mode"],
                                 "status": content["status"], "stop_reason": content["stop_reason"],
                                 "rows": content["counts"]["rows"]})
    if not any(event["type"] == "docking_batch_published" and event.get("attempt_id") == attempt_id and
               event.get("summary_handle") == out.handle for event in events):
        run.events.append("docking_batch_published", job_id=job["job_id"], attempt_id=attempt_id,
                          summary_handle=out.handle, reused_rows=sorted(reused))
    return out.handle


# ----------------------------------------------------------------- validated reads (never run anything)
def summary_producer(run: Any, handle: str) -> dict[str, Any]:
    """The batch attempt that published ``handle`` (reservation < verified cleanup < summary publication)."""
    events = list(run.events.read())
    jobs = {event["job"]["job_id"]: event["job"] for event in events if event["type"] == "job_submitted"}
    created = [event for event in events if event["type"] == "object_created" and event.get("handle") == handle]
    for published in events:
        if published["type"] != "docking_batch_published" or published.get("summary_handle") != handle:
            continue
        job = jobs.get(published.get("job_id"))
        attempt = published.get("attempt_id")
        if job is None or job.get("protocol_id") != BC.PROTOCOL or job.get("tool_id") != BC.TOOL:
            continue
        reserved = [event for event in events if event["type"] == "budget_reserved" and
                    event.get("attempt_id") == attempt and event.get("tool") == BC.TOOL]
        cleaned = [event for event in events if event["type"] == "job_cleanup_verified" and
                   event.get("job_id") == job["job_id"] and event.get("attempt_id") == attempt and
                   event.get("group_empty") is True]
        if (len(reserved) == 1 and cleaned and created and
                reserved[0]["seq"] < cleaned[0]["seq"] < published["seq"] and created[0]["seq"] < published["seq"]):
            return {"job_id": job["job_id"], "attempt_id": attempt, "job": job, "created_seq": created[0]["seq"],
                    "published_seq": published["seq"], "reused_rows": published.get("reused_rows")}
    raise DockingBatchEvidenceError("object has no completed qvina_batch_dock_v1 publication")


def validated_summary(run: Any, handle: Any) -> dict[str, Any]:
    """The stored summary, re-checked against its publication, its batch selection and every per-row result."""
    try:
        if type(handle) is not str:
            raise DockingBatchEvidenceError("handle must be a string")
        try:
            meta = run.store.meta(handle)
        except (KeyError, ValueError) as exc:
            raise DockingBatchEvidenceError("unknown same-run handle") from exc
        if (meta["kind"], meta["schema"], meta["fmt"]) != (BC.OUTPUT_KIND, BC.SUMMARY_SCHEMA, "json"):
            raise DockingBatchEvidenceError("expected docking_batch_result")
        content = run.store.load_bounded_json(handle, BC.MAX_SUMMARY_BYTES)
        job = summary_producer(run, handle)["job"]
        results = {row["result_handle"]: docking_bundle.validated_result(run, row["result_handle"])
                   for row in content["rows"] if row["result_handle"] is not None}
        check_summary(content, job["selected"], results, job["method"])
        if batch_call_key(job["selected"]) != job["call_key"]:
            raise DockingBatchEvidenceError("batch call key")
        return content
    except DockingBatchEvidenceError:
        raise
    except (docking_bundle.DockingEvidenceError, KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise DockingBatchEvidenceError("docking batch summary evidence is invalid") from exc
