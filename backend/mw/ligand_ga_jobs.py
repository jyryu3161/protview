"""M22 GA design job lane on the server side: capability, admission, reuse, staging, publication, limit raise,
validated reads (spec .dryforge/spec.md 2, 4, 6, 7, 10). Mirrors the M19 lane (``docking_batch_jobs``).

The server never imports RDKit, Meeko or MDAnalysis and never executes qvina2. ``JobQueue`` calls these functions:

- ``capability`` / ``require_ready``: ``ligand_docking`` (M18 environments, engine hash, worker handshake) plus the GA
  worker and GA constants files and the GA worker's own ``--handshake`` (cached per file-hash key). Pins: the M18
  pins (an individual's call key and result checks are M18's) and the two GA file hashes.
- ``submission``: ``ligand_ga_inputs.submission`` (admission steps 1-3 before any job, no budget). The job record's
  ``selected`` holds the pool ids in stored order, eligibility, ``pool_sha256``, filter and values only (spec 7).
- ``require_admission``: steps 4 (``ga_reuse_too_large``, 422) and 5 (``ga_limit_raise_required``, 429), nothing
  charged; the need is ``reserved_units`` whatever is reused (spec 6).
- ``reuse_plan``: candidate id -> a validated stored ``docking_result@1`` with the candidate's full M18 call key
  (``docking_batch_inputs.published_m18_results``), decided once at the start under the run owner.
- ``stage``: the worker manifest ``ligand_ga_worker_input@1``: the receptor and parent blocks exactly as
  ``docking_bundle.stage`` stages them for the first eligible candidate, the box and M18 values, the GA values and the
  lean pool rows (index, id, SMILES, eligibility; for eligible rows the M18 candidate fields, ``input_sha256`` and
  the reused result bytes or null).
- ``finish``: after the attempt's process group is verified empty, in every terminal state: each newly docked
  individual of the worker's generation records is converted and checked exactly like an M18 result and published
  (``ligand_ga_individual_published``), then the summary ``ligand_ga_result@1`` (``ligand_ga_published``, last).
  Per-individual M18 selections are rebuilt here for the evaluated individuals only (one receptor check at
  admission, ``ligand_ga_inputs.individual_selection``). Scores and states come from the staged result files and
  stored results, never from the worker's records. A summary that cannot be built raises (the queue fails the job
  with that reason); individuals already published stay readable and reusable on their own evidence.
- ``limit_approval``: the human-approved limit raise for one GA (spec 6), reached only from its HTTP route.
- ``validated_summary`` / ``summary_producer`` / ``complete_job`` / ``individual_view``: reads that re-check the
  summary, its single publication, every individual's result and its rebuilt selection; ``progress``: staged file
  counts for polling (no object is loaded before a summary exists).

Individuals the worker never listed in a generation record (an interrupted docking leaves only ``<k>.started``) have
no candidate identity on the server side and are not part of the summary, after a stop or a crash alike. Staged files
are read with ``O_NOFOLLOW``, regular-file and size bounds, canonical JSON only. The worker's own run-level
``cancelled`` stop (written on SIGTERM) is the user's cancel only when the server stopped the job for a cancel; the
server's stop cause (cancel, job deadline, crash) always wins.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import docking_batch_inputs, docking_bundle, docking_inputs, ligand_ga_inputs
from . import docking_constants as C
from . import ligand_ga_constants as GC
from .core.errors import FailureClass, ToolFailure
from .core.handles import canonical_json
from .ligand_ga_bundle import LigandGaEvidenceError, build_summary, call_key, check_summary, complete_duplicate
from .runtime.orchestrator import RunCancelled

ROOT = Path(__file__).resolve().parents[2]
GA_WORKER = ROOT / "backend/mw/jobs/ligand_ga_worker.py"
GA_CONSTANTS = ROOT / "backend/mw/ligand_ga_constants.py"
IMPLEMENTATION = GC.IMPLEMENTATION
SUMMARY_EVENT = "ligand_ga_published"
STAGED_LIMIT = GC.MAX_STAGED_BYTES                # = the worker's read bound
MAX_PREPARED_BYTES = 64 * 1024
MAX_END_BYTES = 64 * 1024                         # guardian LIGAND_GA_OUTPUT_LIMIT
MAX_STATUS_BYTES = 1024
MAX_GENERATION_BYTES = 256 * 1024                 # <= 24 entries of a few hundred bytes each
ACTIVE = ("queued", "claimed", "running")
ID_RE = re.compile(r"(job|attempt)_[0-9a-z_]{1,90}")
STATUS_REASONS = {"scored": (None,), "null_result": (None,), "failed": C.REASONS + GC.FAILED_EXTRA_REASONS}
END_KEYS = frozenset({"schema", "protocol", "job_id", "attempt_id", "stop_reason", "generations_done"})

_HANDSHAKE_CACHE: dict[tuple, dict[str, Any]] = {}
_HANDSHAKE_LOCK = threading.Lock()


class LigandGaJobError(ValueError):
    """The staged GA output or the GA job record does not support a summary."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _evidence(condition: Any, message: str) -> None:
    if not condition:
        raise LigandGaEvidenceError(message)


# ----------------------------------------------------------------- capability (no RDKit/Meeko here, qvina never run)
def ga_pins() -> dict[str, str]:
    return {"ga_worker_sha256": _sha(GA_WORKER.read_bytes()), "ga_constants_sha256": _sha(GA_CONSTANTS.read_bytes())}


def _handshake_key() -> tuple:
    return (*docking_bundle._handshake_key(), _sha(GA_WORKER.read_bytes()), _sha(GA_CONSTANTS.read_bytes()))


def _handshake() -> dict[str, Any]:
    """``ligand_ga_worker.py --handshake`` in the pinned interpreter (the M18 handshake's fixed argv shape)."""
    proc = subprocess.run([str(docking_bundle.WORKER_PYTHON), "-I", str(GA_WORKER), "--handshake"], cwd=ROOT,
                          env={"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"},
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=120, check=True)
    if len(proc.stdout) > 8192 or len(proc.stderr) > 8192:
        raise ValueError("oversized handshake output")
    data = json.loads(proc.stdout)
    if type(data) is not dict:
        raise ValueError("invalid GA worker handshake")
    return data


def _check_handshake(data: Any) -> None:
    if (type(data) is not dict or data.get("schema") != "ligand_ga_worker_handshake@1" or
            data.get("protocols") != [GC.PROTOCOL] or data.get("worker_sha256") != _sha(GA_WORKER.read_bytes()) or
            data.get("row_worker_sha256") != _sha(docking_bundle.WORKER.read_bytes()) or
            data.get("ga_constants_sha256") != _sha(GA_CONSTANTS.read_bytes())):
        raise ValueError("invalid GA worker handshake")


def _handshake_ok() -> bool:
    """The GA worker imports and names this protocol and the three module hashes; only a verified record is cached,
    per file-hash key (the M18 key plus both GA file hashes)."""
    with _HANDSHAKE_LOCK:
        try:
            key = _handshake_key()
            data = copy.deepcopy(_HANDSHAKE_CACHE.get(key))
            if data is None:
                data = _handshake()
                _check_handshake(data)
                _HANDSHAKE_CACHE.clear()
                _HANDSHAKE_CACHE[key] = copy.deepcopy(data)
            _check_handshake(data)
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
            return False
    return True


def capability(docking: dict[str, Any] | None = None) -> dict[str, Any]:
    """Available only with ``ligand_docking`` available, the GA worker and constants present and the GA worker's
    own verified handshake; otherwise the M18 capability reason (same closed set) and no pins, ranges or limits."""
    docking = docking_bundle.capability() if docking is None else docking
    base = {"schema": "ligand_ga_capability@1", "protocol_id": GC.PROTOCOL, "tool_id": GC.TOOL,
            "engine": GC.ENGINE, "execution_lane": "durable_job"}

    def unavailable(status: str, reason: str) -> dict[str, Any]:
        return {**base, "available": False, "status": status, "reason_code": status, "reason": reason,
                "pins": None, "ga_pins": None}

    if not docking["available"]:
        return unavailable(docking["reason_code"], docking["reason"])
    try:
        pins = ga_pins()
    except OSError:
        return unavailable("worker_missing", docking_bundle.REASONS["worker_missing"])
    if not _handshake_ok():
        return unavailable("handshake_failed", docking_bundle.REASONS["handshake_failed"])
    ranges = {key: {"min": low, "max": high, "default": default}
              for key, (low, high, default) in GC.GA_RANGES.items()}
    return {**base, "available": True, "status": "ready", "reason_code": None, "reason": None,
            "pins": dict(docking["pins"]), "ga_pins": pins, "method": C.METHODS[GC.MODE],
            "ga_ranges": ranges, "timeout_s": {"max": GC.TIMEOUT_MAX_S, "finish_margin": GC.FINISH_MARGIN_S},
            "limits": {"max_pool": GC.MAX_POOL, "per_candidate_s": GC.PER_CANDIDATE_S,
                       "max_new_dockings": GC.MAX_NEW_DOCKINGS, "total_s_max": GC.TOTAL_S_MAX,
                       "output_bytes": GC.MAX_OUTPUT_BYTES, "summary_bytes": GC.MAX_SUMMARY_BYTES,
                       "reuse_staging_bytes": GC.MAX_REUSE_STAGING_BYTES},
            "score_label": C.SCORE_LABEL, "score_row_label": GC.SCORE_ROW_LABEL, "statements": dict(GC.STATEMENTS)}


def require_ready() -> tuple[dict[str, Any], dict[str, str]]:
    """(M18 pins, GA pins) recorded at submission (a precondition failure when unavailable)."""
    value = capability()
    if not value["available"]:
        raise ToolFailure(FailureClass.precondition, value["reason"], detail={"reason_code": value["reason_code"]})
    return value["pins"], value["ga_pins"]


# ----------------------------------------------------------------- pool rows and per-individual views
def pool_rows(run: Any, selected: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """candidate id -> stored candidate row, after re-checking the validated candidate set against the GA record
    (same ids in stored order, same eligibility under the recorded filter, same pool hash)."""
    from .ligand_bundle import LigandEvidenceError, validated_candidate_set

    try:
        candidate_set, _inspection = validated_candidate_set(run, selected["candidate_set"]["handle"])
    except LigandEvidenceError as exc:
        raise LigandGaEvidenceError("the GA candidate set no longer validates") from exc
    rows = candidate_set["candidates"]
    pool = ligand_ga_inputs.eligibility(rows, selected["arguments"]["filter"])
    _evidence(pool == selected["pool"] and ligand_ga_inputs.pool_sha256(pool) == selected["pool_sha256"] and
              candidate_set["parent_sha256"] == selected["candidate_set"]["parent_sha256"],
              "the candidate set is the GA pool")
    return {row["id"]: row for row in rows}


def individual_job(job: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """The GA job as the M18 job one individual's checks expect: its own rebuilt ``docking_selection@1`` and the GA
    job's M18 pins."""
    return {**job, "selected": ligand_ga_inputs.individual_selection(job["selected"], row)}


def individual_view(run: Any, evidence: dict[str, Any]) -> dict[str, Any]:
    """``docking_bundle.producer`` for a GA individual: the publication evidence with the individual's M18 job view
    (the candidate row re-read from the validated candidate set)."""
    try:
        job = evidence["job"]
        rows = pool_rows(run, job["selected"])
        cid = evidence["candidate_id"]
        _evidence(cid in set(ligand_ga_inputs.eligible_ids(job["selected"])), "an eligible pool candidate")
        return {**evidence, "job": individual_job(job, rows[cid])}
    except (LigandGaEvidenceError, KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise docking_bundle.DockingEvidenceError("GA individual publication evidence is invalid") from exc


# ----------------------------------------------------------------- admission, reuse, duplicates
def admission_timeout(args: Any) -> Any:
    """The timeout the screen always sends (``ga.total_s + 600``), for the limit raise whose body is the GA job
    arguments only; malformed arguments give None, which admission refuses (``invalid_job_arguments``)."""
    ga = args.get("ga") if type(args) is dict else None
    total = ga.get("total_s") if type(ga) is dict else None
    return total + GC.FINISH_MARGIN_S if type(total) is int else None


def submission(run: Any, args: Any, timeout_s: Any) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    return ligand_ga_inputs.submission(run, args, timeout_s)


def reuse_plan(run: Any, selected: dict[str, Any], pins: dict[str, Any]) -> dict[str, str]:
    """candidate id -> a stored result with the candidate's full M18 call key that still validates (pool order)."""
    existing = docking_batch_inputs.published_m18_results(run.events.read())
    args = selected["arguments"]
    plan: dict[str, str] = {}
    for cid, handle in ligand_ga_inputs.reuse_index(selected, pins, existing).items():
        try:
            expected = docking_inputs.input_sha256(ligand_ga_inputs.row_arguments(args, cid))
            if docking_bundle.validated_result(run, handle)["input_sha256"] == expected:
                plan[cid] = handle
        except docking_bundle.DockingEvidenceError:
            continue
    return plan


def require_admission(run: Any, selected: dict[str, Any], pins: dict[str, Any]) -> None:
    """Admission steps 4-5 (spec 2, 6): reused results to stage <= 128 MiB (422 ``ga_reuse_too_large``), then a
    short budget refuses (429 ``ga_limit_raise_required``); nothing is charged either way."""
    plan = reuse_plan(run, selected, pins)
    ligand_ga_inputs.require_reuse_size(sum(run.store.meta(handle)["size"] for handle in plan.values()))
    ligand_ga_inputs.require_budget(ligand_ga_inputs.needed_budget(selected["arguments"]["ga"]),
                                    run.budget_snapshot())


def _refuse_cancelled(run: Any) -> None:
    if run._cancel_path.exists() or run.cancelled:
        raise RunCancelled("run cancelled")


def limit_approval(run: Any, args: Any) -> dict[str, Any]:
    """Spec 6: the human-approved limit raise for one GA, called only by its HTTP route (a UI action; never a tool,
    plan or workflow step, model command or loop action). Body = the GA job arguments. Dry-run runs refuse it
    (412 ``dry_run``, nothing written). The need (``reserved_units`` and its wall time) is recomputed from the
    request and the current budget (under the run owner), and only the shortfall is raised
    (``ligand_ga_inputs.limit_increase``, the GA constants) with one ``budget_limit_updated`` (by ``human``) carrying
    the GA context. Nothing short: nothing changes and no event is written. It never approves the first expensive
    call, reserves, charges or refunds anything. A cancelled run refuses it (``RunCancelled``, nothing written).
    Every decision uses the snapshot ``Run.raise_limits`` plans with (``run.budget.snapshot()``: charged usage)."""
    if run.dry_run:
        raise ToolFailure(FailureClass.precondition, "dry-run runs plan only; there is no limit to raise",
                          detail={"reason_code": "dry_run"})
    run._refresh()
    _refuse_cancelled(run)
    selected, _normalized, _handles = submission(run, args, admission_timeout(args))
    require_ready()
    ga = selected["arguments"]["ga"]
    units = ligand_ga_inputs.reserved_units(ga)
    needed = ligand_ga_inputs.needed_budget(ga)

    def plan(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        _refuse_cancelled(run)   # again under the run owner, right before the limit event
        return ligand_ga_inputs.limit_increase(needed, snapshot), {
            "purpose": "ligand_ga_limit_raise", "selection_sha256": selected["selection_sha256"],
            "reserved_units": units, "needed": needed, "shortfall": ligand_ga_inputs.shortfall(needed, snapshot)}

    run._refresh()
    increase, context = plan(run.budget.snapshot())
    event = run.raise_limits(plan, by="human") if any(increase.values()) else None
    if event is not None:
        context = event["context"]
    else:
        limits = {axis: run.budget.snapshot()[axis]["limit"] for axis in ligand_ga_inputs.AXES}
        context = {**context, "increase": dict.fromkeys(ligand_ga_inputs.AXES, 0), "limits_before": limits,
                   "limits_after": limits}
    budget = run.budget.snapshot()
    return {"raised": event is not None, "selection_sha256": context["selection_sha256"], "reserved_units": units,
            "needed": needed, "shortfall_before": context["shortfall"], "increase": context["increase"],
            "limits_before": context["limits_before"], "limits_after": context["limits_after"],
            "shortfall_after": ligand_ga_inputs.shortfall(needed, budget),
            "event_seq": None if event is None else event["seq"], "budget": budget}


def complete_job(run: Any, jobs: Mapping[str, dict[str, Any]], key: str) -> dict[str, Any] | None:
    """Spec 6: an active GA job with this call key, else the job of a validated ``complete`` summary with it (a
    ``partial`` summary never deduplicates); None means a new GA job."""
    active = next((job for job in jobs.values() if job["protocol_id"] == GC.PROTOCOL and job["call_key"] == key and
                   job["status"] in ACTIVE), None)
    if active is not None:
        return active
    owners, summaries = {}, []
    for event in run.events.read():
        job = jobs.get(event.get("job_id")) if event["type"] == SUMMARY_EVENT else None
        if job is None or job["protocol_id"] != GC.PROTOCOL or job["call_key"] != key:
            continue
        try:
            summaries.append((event["summary_handle"], validated_summary(run, event["summary_handle"])))
            owners[event["summary_handle"]] = job
        except LigandGaEvidenceError:
            continue
    handle = complete_duplicate(summaries, key)
    return None if handle is None else owners[handle]


# ----------------------------------------------------------------- staging
def _b64(raw: bytes) -> dict[str, str]:
    return {"b64": base64.b64encode(raw).decode(), "sha256": _sha(raw)}


def stage(run: Any, job: dict[str, Any], attempt_id: str, reused: Mapping[str, str]) -> bytes:
    """The worker manifest; nothing in it is read from the request (GA record, immutable imports, stored
    candidate rows and the validated reused results only)."""
    selected = job["selected"]
    args = selected["arguments"]
    rows = pool_rows(run, selected)
    eligible = ligand_ga_inputs.eligible_ids(selected)
    first = json.loads(docking_bundle.stage(run, individual_job(job, rows[eligible[0]]), attempt_id))
    pool = []
    for item in selected["pool"]:
        cid, ok = item["candidate_id"], item["eligible"]
        row = rows[cid]
        handle = reused.get(cid) if ok else None
        pool.append({"index": item["index"], "candidate_id": cid, "smiles": row["smiles"], "eligible": ok,
                     "retained_parent_atoms": copy.deepcopy(row["retained_parent_atoms"]) if ok else None,
                     "stereo_flag": row["stereo_flag"] if ok else None,
                     "input_sha256": (docking_inputs.input_sha256(ligand_ga_inputs.row_arguments(args, cid))
                                      if ok else None),
                     "reuse_result_bytes": (None if handle is None else
                                            _b64(canonical_json(docking_bundle.validated_result(run, handle))))})
    return canonical_json({"schema": GC.WORKER_INPUT_SCHEMA, "receptor": first["receptor"],
                           "parent_sdf": first["ligand"]["parent_sdf"],
                           "candidate_set_parent_sha256": selected["candidate_set"]["parent_sha256"],
                           "box": first["box"], "parameters": first["parameters"], "ga": args["ga"], "pool": pool})


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


def _subdir(attempt_dir: Path | None, name: str) -> Path | None:
    if attempt_dir is None:
        return None
    try:
        return attempt_dir / name if stat.S_ISDIR(os.lstat(attempt_dir / name).st_mode) else None
    except OSError:
        return None


def _status(individuals: Path | None, index: int) -> dict[str, Any] | None:
    """A status file inside the closed sets, else none (an unreadable status never invalidates the summary)."""
    data = _canonical(_read(individuals, f"{index}.status.json", MAX_STATUS_BYTES))
    ok = (type(data) is dict and set(data) == {"state", "reason_code"} and data["state"] in STATUS_REASONS and
          data["reason_code"] in STATUS_REASONS[data["state"]])
    return data if ok else None


def _end_record(attempt_dir: Path | None, job: dict[str, Any], attempt_id: str) -> dict[str, Any] | None:
    data = _canonical(_read(attempt_dir, "result.json", MAX_END_BYTES))
    ok = (type(data) is dict and set(data) == END_KEYS and data["schema"] == GC.WORKER_OUTPUT_SCHEMA and
          data["protocol"] == GC.PROTOCOL and data["job_id"] == job["job_id"] and
          data["attempt_id"] == attempt_id and data["stop_reason"] in GC.STOP_REASONS and
          type(data["generations_done"]) is int)
    return data if ok else None


def _prepared(attempt_dir: Path | None) -> dict[str, Any] | None:
    data = _canonical(_read(attempt_dir, "prepared.json", MAX_PREPARED_BYTES))
    return data if type(data) is dict and set(data) == {"box", "engine"} else None


def _records(attempt_dir: Path | None) -> list[Any]:
    """The worker generation records 1, 2, ... in order (no gap; a present but unreadable record raises)."""
    directory = _subdir(attempt_dir, "generations")
    if directory is None:
        return []
    names = {entry.name for entry in os.scandir(directory) if entry.is_file(follow_symlinks=False)}
    records = []
    for number in range(1, len(names) + 2):
        if f"{number}.json" not in names:
            break
        data = _canonical(_read(directory, f"{number}.json", MAX_GENERATION_BYTES))
        if type(data) is not dict or data.get("index") != number:
            raise LigandGaJobError("unreadable generation record")
        records.append(data)
    if {f"{n}.json" for n in range(1, len(records) + 1)} != {name for name in names if not name.endswith(".tmp")}:
        raise LigandGaJobError("generation records have a gap or a stray file")
    return records


def _count(directory: Path | None, suffix: str) -> int:
    try:
        return 0 if directory is None else sum(entry.name.endswith(suffix) and entry.is_file(follow_symlinks=False)
                                               for entry in os.scandir(directory))
    except OSError:
        return 0


def progress(run: Any, job: dict[str, Any]) -> dict[str, Any]:
    """Polling view (spec 8): pool counts and reserved units from the job record, then the attempt's staged file
    counts (``individuals/*.started`` / ``*.status.json``, generation records and how many say ``complete``) and
    the summary handle once published, with that summary's ``status``/``stop_reason`` read through
    ``validated_summary`` (null when it does not validate). No object is loaded before a summary exists."""
    selected = job["selected"]
    intent = job.get("dispatch_intent") or {}
    started = finished = generations = complete = 0
    attempt = job.get("attempt_id")
    if type(attempt) is str and ID_RE.fullmatch(attempt) and ID_RE.fullmatch(job["job_id"]):
        attempt_dir = run.run_dir / "jobs" / job["job_id"] / attempt
        individuals = _subdir(attempt_dir, "individuals")
        started, finished = _count(individuals, ".started"), _count(individuals, ".status.json")
        directory = _subdir(attempt_dir, "generations")
        generations = _count(directory, ".json")
        for number in range(1, generations + 1):
            data = _canonical(_read(directory, f"{number}.json", MAX_GENERATION_BYTES))
            complete += type(data) is dict and data.get("complete") is True
    handle = job.get("ga_summary_handle")
    status = stop_reason = None
    if handle is not None:
        try:
            content = validated_summary(run, handle)
            status, stop_reason = content["status"], content["stop_reason"]
        except LigandGaEvidenceError:
            pass
    return {"pool": ligand_ga_inputs.pool_counts(selected["pool"]),
            "reserved_units": ligand_ga_inputs.reserved_units(selected["arguments"]["ga"]),
            "reused_planned": len(intent.get("ga_reused", [])), "individuals_started": started,
            "individuals_finished": finished, "generation_records": generations, "generations_complete": complete,
            "summary_handle": handle, "summary_status": status, "summary_stop_reason": stop_reason}


# ----------------------------------------------------------------- publication (after the group is verified empty)
def _publish(run: Any, view: dict[str, Any], attempt_id: str, data: Any) -> tuple[str, dict] | None:
    """One individual's worker bytes as an M18 result, with every M18 check; None when it does not validate."""
    try:
        if type(data) is not dict or data.get("job_id") != view["job_id"] or data.get("attempt_id") != attempt_id:
            return None
        content = docking_bundle.result_content(view, data)
        return docking_bundle.store_result(run, view, attempt_id, content), content
    except (docking_bundle.DockingEvidenceError, docking_bundle.DockingJobFailure, ToolFailure, KeyError, TypeError,
            ValueError, IndexError, AttributeError, OSError, RecursionError):
        return None


def _stop_reason(attempt_dir: Path | None, job: dict[str, Any], attempt_id: str, server_cause: str | None,
                 records: list[Any]) -> str:
    if server_cause is not None:
        return server_cause
    end = _end_record(attempt_dir, job, attempt_id)
    if end is None:
        return "worker_failed"
    if end["generations_done"] != sum(type(r) is dict and r.get("complete") is True for r in records):
        raise LigandGaJobError("worker end record disagrees with its generation records")
    # A SIGTERM the server did not send for a user cancel is not the user's cancel.
    return "worker_failed" if end["stop_reason"] == "cancelled" else end["stop_reason"]


def finish(run: Any, job: dict[str, Any], attempt_id: str, attempt_dir: Path | None,
           server_cause: str | None) -> str | None:
    """Publish the newly docked individuals and then the summary; return the summary handle, or None when the GA
    never reached its first individual (no ``prepared.json``: no summary, as an M19 batch without a first row).

    ``server_cause``: None (the worker ended by itself), ``cancelled`` (user), ``time_exhausted`` (job deadline) or
    ``worker_failed`` (crash, kill, limit, parent loss). Raises on summary evidence errors."""
    selected = job["selected"]
    reused = {item["candidate_id"]: item["handle"] for item in job["dispatch_intent"]["ga_reused"]}
    prepared = _prepared(attempt_dir)
    if prepared is None:
        return None
    records = _records(attempt_dir)
    cause = _stop_reason(attempt_dir, job, attempt_id, server_cause, records)
    rows = pool_rows(run, selected)
    events = list(run.events.read())
    recorded = {event["eval_index"]: event["handle"] for event in events
                if event["type"] == GC.INDIVIDUAL_EVENT and event.get("attempt_id") == attempt_id}
    individuals = _subdir(attempt_dir, "individuals")
    results: dict[str, Any] = {}
    observations: dict[int, dict[str, Any]] = {}
    selections: dict[str, Any] = {}
    for record in records:
        for entry in record.get("individuals", []) if type(record) is dict else []:
            if type(entry) is not dict or entry.get("origin") == "carried":
                continue
            cid, index = entry.get("candidate_id"), entry.get("eval_index")
            if type(cid) is not str or cid not in rows or type(index) is not int or index in observations:
                raise LigandGaJobError("generation record entry")
            view = individual_job(job, rows[cid])
            selections[cid] = view["selected"]
            if entry.get("evaluation") == "reused":
                _evidence(cid in reused, "a reused individual is in the start's reuse plan")
                results[reused[cid]] = docking_bundle.validated_result(run, reused[cid])
                observations[index] = {"status": None, "result_handle": reused[cid]}
                continue
            _evidence(entry.get("evaluation") == "docked" and cid not in reused,
                      "a docked individual was not planned for reuse")
            status = _status(individuals, index)
            handle = None
            if status is None or status["state"] in ("scored", "null_result"):
                data = _canonical(_read(individuals, f"{index}.result.json", C.MAX_RESULT_BYTES))
                published = None if data is None else _publish(run, view, attempt_id, data)
                if published is not None:
                    handle, results[handle] = published[0], published[1]
                    if recorded.get(index) != handle:
                        run.events.append(GC.INDIVIDUAL_EVENT, job_id=job["job_id"], attempt_id=attempt_id,
                                          eval_index=index, candidate_id=cid, handle=handle)
            observations[index] = {"status": status, "result_handle": handle}
    content = build_summary(selected, records=records, observations=observations, results=results,
                            individual_selections=selections, stop_reason=cause, box=prepared["box"],
                            m18_pins=job["method"], ga_pins=job["ga_method"])
    _evidence(content["call_key"] == job["call_key"], "GA call key")
    out = run.store.put(GC.OUTPUT_KIND, GC.SUMMARY_SCHEMA, content, produced_by=attempt_id,
                        summary={"selection_sha256": content["selection_sha256"], "status": content["status"],
                                 "stop_reason": content["stop_reason"],
                                 "generations_done": content["generations_done"],
                                 "new_dockings_used": content["new_dockings_used"],
                                 "reused_count": content["reused_count"]})
    if not any(event["type"] == SUMMARY_EVENT and event.get("attempt_id") == attempt_id and
               event.get("summary_handle") == out.handle for event in events):
        run.events.append(SUMMARY_EVENT, job_id=job["job_id"], attempt_id=attempt_id, summary_handle=out.handle,
                          reused_count=content["reused_count"])
    return out.handle


# ----------------------------------------------------------------- validated reads (never run anything)
def summary_producer(run: Any, handle: str) -> dict[str, Any]:
    """The GA attempt that published ``handle`` (reservation < verified cleanup < summary publication)."""
    events = list(run.events.read())
    jobs = {event["job"]["job_id"]: event["job"] for event in events if event["type"] == "job_submitted"}
    created = [event for event in events if event["type"] == "object_created" and event.get("handle") == handle]
    for published in events:
        if published["type"] != SUMMARY_EVENT or published.get("summary_handle") != handle:
            continue
        job = jobs.get(published.get("job_id"))
        attempt = published.get("attempt_id")
        if job is None or job.get("protocol_id") != GC.PROTOCOL or job.get("tool_id") != GC.TOOL:
            continue
        reserved = [event for event in events if event["type"] == "budget_reserved" and
                    event.get("attempt_id") == attempt and event.get("tool") == GC.TOOL]
        cleaned = [event for event in events if event["type"] == "job_cleanup_verified" and
                   event.get("job_id") == job["job_id"] and event.get("attempt_id") == attempt and
                   event.get("group_empty") is True]
        if (len(reserved) == 1 and cleaned and created and
                reserved[0]["seq"] < cleaned[0]["seq"] < published["seq"] and created[0]["seq"] < published["seq"]):
            return {"job_id": job["job_id"], "attempt_id": attempt, "job": job, "created_seq": created[0]["seq"],
                    "published_seq": published["seq"], "reserved_units": reserved[0].get("expensive_calls")}
    raise LigandGaEvidenceError("object has no completed qvina_ga_dock_v1 publication")


def validated_summary(run: Any, handle: Any) -> dict[str, Any]:
    """The stored summary, re-checked against its publication, its GA selection, the rebuilt selections of the
    evaluated individuals and every individual's result; the reservation must be ``reserved_units``."""
    try:
        if type(handle) is not str:
            raise LigandGaEvidenceError("handle must be a string")
        try:
            meta = run.store.meta(handle)
        except (KeyError, ValueError) as exc:
            raise LigandGaEvidenceError("unknown same-run handle") from exc
        if (meta["kind"], meta["schema"], meta["fmt"]) != (GC.OUTPUT_KIND, GC.SUMMARY_SCHEMA, "json"):
            raise LigandGaEvidenceError("expected ligand_ga_result")
        content = run.store.load_bounded_json(handle, GC.MAX_SUMMARY_BYTES)
        source = summary_producer(run, handle)
        job = source["job"]
        rows = pool_rows(run, job["selected"])
        selections = {entry["candidate_id"]: ligand_ga_inputs.individual_selection(job["selected"],
                                                                                   rows[entry["candidate_id"]])
                      for generation in content["generations"] for entry in generation["individuals"]
                      if entry["origin"] != "carried"}
        results = {entry["result_handle"]: docking_bundle.validated_result(run, entry["result_handle"])
                   for generation in content["generations"] for entry in generation["individuals"]
                   if entry["result_handle"] is not None}
        check_summary(content, job["selected"], selections, results, job["method"], job["ga_method"])
        _evidence(content["call_key"] == job["call_key"] == call_key(job["selected"], job["method"],
                                                                    job["ga_method"]), "GA call key")
        _evidence(source["reserved_units"] == content["reserved_units"], "the reservation is reserved_units")
        return content
    except LigandGaEvidenceError:
        raise
    except (docking_bundle.DockingEvidenceError, KeyError, TypeError, ValueError, IndexError,
            AttributeError) as exc:
        raise LigandGaEvidenceError("GA summary evidence is invalid") from exc
