"""M23 sequence GA design job lane on the server side: capability, admission, reuse, staging, publication, limit raise,
validated reads (spec .dryforge/spec.md 2, 4, 7, 8, 9, 11). Mirrors the M22 lane (``ligand_ga_jobs``).

The server never imports RDKit, Meeko, MDAnalysis or PDBFixer and never executes qvina2; OpenMM is reached only through
the M7 ``openmm_method.dependencies()`` / ``preflight()``. ``JobQueue`` calls these functions:

- ``capability`` / ``require_ready``: the M21 ``mutation_model`` capability (process identity, OpenMM 8.6.0, PDBFixer
  1.12.0 by metadata), the M18 ``ligand_docking`` capability (environments, qvina2 hash, worker handshake), the M23
  module files, the project interpreter ``<repo>/.venv/bin/python`` (never resolved) and the GA worker's own
  ``--handshake``. Pins = ``{"modules", "model_method", "docking"}`` (``sequence_ga_inputs.check_pins``); the job record
  keeps ``method`` = the M18 pins (an individual's M18 view) and ``ga_method`` = ``{"modules", "model_method"}``.
- ``submission`` (admission steps 1-4, ``sequence_ga_inputs.admission``), ``selection`` (5: 412 unavailability, 6: the
  M7 preflight, ``residue_mismatch``, ``box_no_receptor_atoms``, 7: ``ga_space_too_small``, 8: staged bytes 429) and
  ``require_budget`` (9: 429 ``ga_limit_raise_required``); nothing is charged. ``admission_plan`` runs 1-8 for reads.
- ``start_plan``: at the start, once, under the run owner and before the reservation: the reuse index (``reuse_plan``)
  and the staged manifest bytes (16 MiB, re-checked; 429 before anything is charged) and ``reserved_units``; the queue
  stages these bytes (``manifest``: the worker manifest ``sequence_ga_worker_input@1``, ``sequence_ga_worker.py``
  docstring).
- ``finish``: after the attempt's process group is verified empty, in every end state, once ``reference.status.json``
  exists: the reference row and every newly evaluated individual are published (mmCIF ``mutation_set_model_structure@1``
  -> model ``mutation_set_model@1`` -> ``docking_result@1``, then ``sequence_ga_individual_published``), reused rows are
  re-validated, then the summary ``sequence_ga_result@1`` and ``sequence_ga_published`` (last). Before the reference
  row's status file there is no summary.
- ``limit_approval``: the human-approved limit raise for one sequence GA, reached only from its HTTP route.
- Reads (never write, never run anything): ``summary_producer``, ``validated_summary``, ``complete_job``,
  ``progress``, the set-model reads ``model_producer``, ``set_model`` (light) and ``validated_set_model`` (full), and
  the two M18 hooks ``set_model_receptor`` (``docking_bundle._mutation_receptor`` for a ``mutation_set_model@1``) and
  ``individual_view`` (``docking_bundle.producer`` for a GA individual).

Validation levels of a stored ``mutation_set_model@1`` (T2 concern). Publication (``finish``): the server rebuilds the
worker's ``model.json`` with ``sequence_model_bundle.model_content`` (byte-identical required), runs the full
``validated_model`` (a mutant against the reference row's model), checks the mmCIF atom rows against the entry
(``openmm_bundle._cif``, as M21) and the reference row's heavy atoms against the M7 projection, and only then stores
it. While the same ``finish`` builds and checks the individual's M18 docking result, the model has no publication event
yet: the models this ``finish`` itself stored are handed to the M18 receptor path through a context variable only this
module sets (``_publishing``). Every later read needs the publication evidence (``model_producer``: reservation <
verified cleanup < ``sequence_ga_individual_published`` naming the model) and runs ``validated_model_alone`` (the M18
receptor path: structure entry, stored mmCIF, the model's own records) or, for summary reads, the full
``validated_model`` with the reference row's model.

One read folds the event log once (``_Snapshot``, spec 9 and T1 C1): the M18 and set-model checks of every individual
get the same in-memory event list, and validated models, candidate sets, receptors and M18 selections are remembered
for that read only. The M18, M19, M21 and M22 read paths themselves are unchanged.

Staged files are read with ``O_NOFOLLOW``, regular-file and size bounds, canonical JSON only. The worker's own
``cancelled`` stop is the user's cancel only when the server stopped the job for a cancel; the server's stop cause
(cancel, job deadline, crash) always wins. A docked receptor that is not the stored model (mmCIF hash, sidecar hash,
source) or a prepared box / engine / method that is not the server's ends the job fatal (``SequenceGaFatal``); the
prepared box, engine and method are compared before anything of the attempt is published.
"""
from __future__ import annotations

import base64
import contextlib
import contextvars
import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import threading
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from . import docking_bundle, docking_inputs
from . import docking_constants as C
from . import mutation_model_bundle as mmb
from . import mutation_model_constants as MK
from . import mutation_model_inputs as mi
from . import sequence_ga_bundle as SB
from . import sequence_ga_constants as SC
from . import sequence_ga_inputs as GI
from . import sequence_model_bundle as SM
from .core.errors import FailureClass, ToolFailure
from .core.handles import canonical_json
from .mutation_candidates import identity, seven
from .openmm_bundle import _cif
from .runtime.orchestrator import RunCancelled
from .sequence_ga_bundle import SequenceGaEvidenceError
from .tools import openmm_method

ROOT = GI.ROOT
GA_WORKER = GI.GA_MODULES["ga_worker_sha256"]
GA_CONSTANTS = GI.GA_MODULES["ga_constants_sha256"]
MODEL_WORKER = GI.GA_MODULES["model_worker_sha256"]
PROJECT_PYTHON = ROOT / ".venv" / "bin" / "python"   # the venv link itself, never resolved (spec 8)
IMPLEMENTATION = SC.IMPLEMENTATION
STAGED_LIMIT = SC.MAX_STAGED_BYTES                     # = the worker's read bound
MAX_PREPARED_BYTES = 64 * 1024
MAX_END_BYTES = 64 * 1024                              # guardian SEQUENCE_GA_OUTPUT_LIMIT
MAX_STATUS_BYTES = 1024
MAX_GENERATION_BYTES = 256 * 1024                      # <= 16 entries of a few hundred bytes each
MAX_CIF_BYTES = SC.PER_INDIVIDUAL_OUTPUT_MAX           # an individual's files never pass this bound (worker rule)
ACTIVE = ("queued", "claimed", "running")
ID_RE = re.compile(r"(job|attempt)_[0-9a-z_]{1,90}")
REFERENCE_PREFIX = "reference."
STATUS_KEYS = frozenset({"state", "reason_code", "stage"})
END_KEYS = frozenset({"schema", "protocol", "job_id", "attempt_id", "stop_reason", "generations_done"})
PREPARED_KEYS = frozenset({"box", "engine", "model_method"})
RECORD_KEYS = frozenset({"index", "complete", "individuals"})
ENTRY_KEYS = frozenset({"key", "origin", "parents", "edit_op", "evaluation", "pick_index", "eval_index"})
MODEL_TYPE = (SC.MODEL_KIND, SC.MODEL_SCHEMA, "json")
STRUCTURE_TYPE = (SC.STRUCTURE_OBJECT_KIND, SC.STRUCTURE_OBJECT_SCHEMA, "cif")
REASONS = {**mmb.REASONS, **docking_bundle.REASONS}

_HANDSHAKE_CACHE: dict[tuple, dict[str, Any]] = {}
_HANDSHAKE_LOCK = threading.Lock()


class SequenceGaFatal(Exception):
    """A worker output that contradicts the server's own records (the job ends fatal, nothing more is published)."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _evidence(condition: Any, message: str) -> None:
    if not condition:
        raise SequenceGaEvidenceError(message)


def _fatal(condition: Any, message: str) -> None:
    if not condition:
        raise SequenceGaFatal(message)


# ----------------------------------------------------------------- capability (no PDBFixer import, qvina never run)
def _handshake_key() -> tuple:
    return (*docking_bundle._handshake_key(), _sha(GA_WORKER.read_bytes()), _sha(GA_CONSTANTS.read_bytes()),
            _sha(MODEL_WORKER.read_bytes()), str(PROJECT_PYTHON), PROJECT_PYTHON.is_file())


def _handshake() -> dict[str, Any]:
    """``sequence_ga_worker.py --handshake`` in the pinned docking interpreter (the M18 handshake's argv shape)."""
    proc = subprocess.run([str(docking_bundle.WORKER_PYTHON), "-I", str(GA_WORKER), "--handshake"], cwd=ROOT,
                          env={"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"},
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=120, check=True)
    if len(proc.stdout) > 8192 or len(proc.stderr) > 8192:
        raise ValueError("oversized handshake output")
    data = json.loads(proc.stdout)
    if type(data) is not dict:
        raise ValueError("invalid sequence GA worker handshake")
    return data


def _check_handshake(data: Any) -> None:
    if (type(data) is not dict or data.get("schema") != "sequence_ga_worker_handshake@1" or
            data.get("protocols") != [SC.PROTOCOL] or data.get("worker_sha256") != _sha(GA_WORKER.read_bytes()) or
            data.get("row_worker_sha256") != _sha(docking_bundle.WORKER.read_bytes()) or
            data.get("ga_constants_sha256") != _sha(GA_CONSTANTS.read_bytes()) or
            data.get("model_worker_sha256") != _sha(MODEL_WORKER.read_bytes()) or
            data.get("project_python") != str(PROJECT_PYTHON) or data.get("project_python_present") is not True):
        raise ValueError("invalid sequence GA worker handshake")


def _handshake_ok() -> bool:
    """The GA worker imports, names this protocol, the module hashes and this checkout's project interpreter; only a
    verified record is cached, per file-hash key."""
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


def capability(docking: dict[str, Any] | None = None, mutation: dict[str, Any] | None = None) -> dict[str, Any]:
    """``methods.sequence_ga_design``: available only with the M21 modeling engines, the M18 docking environment, the
    M23 module files, the project interpreter and the GA worker's own handshake; otherwise the closed reason in the
    admission step 5 order and no pins, versions, ranges or limits."""
    base = {"schema": "sequence_ga_capability@1", "protocol_id": SC.PROTOCOL, "tool_id": SC.TOOL,
            "engine": SC.ENGINE, "execution_lane": "durable_job", "result_schema": SC.SUMMARY_SCHEMA,
            "model_schema": SC.MODEL_SCHEMA}

    def unavailable(code: str, reason: str) -> dict[str, Any]:
        return {**base, "available": False, "status": code, "reason_code": code, "reason": reason, "pins": None,
                "versions": None}

    mutation = mmb.capability() if mutation is None else mutation
    if not mutation["available"]:
        return unavailable(mutation["reason_code"], mutation["reason"])
    docking = docking_bundle.capability() if docking is None else docking
    if not docking["available"]:
        return unavailable(docking["reason_code"], docking["reason"])
    try:
        modules = GI.module_pins()
        if not PROJECT_PYTHON.is_file():
            raise FileNotFoundError(str(PROJECT_PYTHON))
    except OSError:
        return unavailable("worker_missing", docking_bundle.REASONS["worker_missing"])
    if not _handshake_ok():
        return unavailable("handshake_failed", docking_bundle.REASONS["handshake_failed"])
    try:
        model_method = GI.model_method(mmb.require_ready()["method"])
    except ToolFailure as exc:
        code = exc.detail.get("reason_code")
        return unavailable(code, REASONS.get(code, exc.message))
    pins = GI.check_pins({"modules": modules, "model_method": model_method, "docking": dict(docking["pins"])})
    ranges = {key: {"min": low, "max": high, "default": default} for key, (low, high, default) in SC.GA_RANGES.items()}
    return {**base, "available": True, "status": "ready", "reason_code": None, "reason": None, "pins": pins,
            "versions": {"model": dict(mutation["versions"]), "docking": dict(docking["versions"])},
            "ga_ranges": ranges, "timeout_s": {"max": SC.TIMEOUT_MAX_S, "finish_margin": SC.FINISH_MARGIN_S},
            "limits": {"positions": SC.MAX_POSITIONS, "candidates": SC.MAX_CANDIDATES,
                       "population": SC.MAX_POPULATION, "generations": SC.MAX_GENERATIONS,
                       "new_evaluations": SC.MAX_NEW_EVALUATIONS, "max_mutations": SC.MAX_MUTATIONS,
                       "model_step_s": SC.MODEL_STEP_S, "docking_step_s": SC.DOCKING_STEP_S,
                       "total_s_max": SC.TOTAL_S_MAX, "model_object_bytes": SC.MAX_MODEL_OBJECT_BYTES,
                       "output_bytes": SC.MAX_OUTPUT_BYTES, "summary_bytes": SC.MAX_SUMMARY_BYTES,
                       "staged_bytes": SC.MAX_STAGED_BYTES, "m18_heavy_atom_estimate": SC.M18_HEAVY_ATOM_ESTIMATE,
                       "consecutive_failures": SC.CONSECUTIVE_FAILURE_LIMIT},
            "units_per_evaluation": SC.UNITS_PER_EVALUATION, "score_label": SC.SCORE_LABEL,
            "score_row_label": SC.SCORE_ROW_LABEL, "statements": dict(SC.STATEMENTS),
            "model_limitations": list(SC.MODEL_LIMITATION_ORDER)}


def require_ready() -> dict[str, Any]:
    """The pins recorded at submission and rechecked at the start (a 412 with the closed reason when unavailable)."""
    value = capability()
    if not value["available"]:
        raise ToolFailure(FailureClass.precondition, value["reason"], detail={"reason_code": value["reason_code"]})
    return value["pins"]


def job_pins(job: Mapping[str, Any]) -> dict[str, Any]:
    """The pins of a job record (``method`` = the M18 pins, ``ga_method`` = modules and model method)."""
    return {"modules": job["ga_method"]["modules"], "model_method": job["ga_method"]["model_method"],
            "docking": job["method"]}


def record_pins(pins: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(``method``, ``ga_method``) a job record keeps."""
    return dict(pins["docking"]), {"modules": pins["modules"], "model_method": pins["model_method"]}


# ----------------------------------------------------------------- one read: the events once, objects once
class _Memo:
    def __init__(self) -> None:
        self.models: dict[str, tuple[dict[str, Any], dict[str, Any] | None]] = {}
        self.full: dict[tuple[str, str | None], dict[str, Any]] = {}
        self.candidate_sets: dict[str, dict[str, Any]] = {}
        self.receptors: dict[tuple[str, str], dict[str, Any]] = {}
        self.selections: dict[str, dict[str, Any]] = {}


class _Snapshot:
    """A read-only view of a run whose ``events.read()`` is one folded list (spec 9, T1 C1)."""

    def __init__(self, run: Any) -> None:
        self.store, self.run_id, self.run_dir = run.store, run.run_id, run.run_dir
        self._events = list(run.events.read())
        self.events = self
        self.sequence_memo = _Memo()

    def read(self) -> list[dict[str, Any]]:
        return self._events


def snapshot(run: Any) -> Any:
    """One read of ``run`` (the same view when it already is one)."""
    return run if isinstance(run, _Snapshot) else _Snapshot(run)


_PUBLISHING: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("sequence_ga_publishing",
                                                                                     default=None)


@contextlib.contextmanager
def _publishing(models: dict[str, dict[str, Any]]) -> Iterator[None]:
    """Inside ``finish`` only: the set models this attempt has just stored (fully validated, mmCIF stored) are M18
    receptors before their publication event exists."""
    token = _PUBLISHING.set({"models": models, "memo": _Memo()})
    try:
        yield
    finally:
        _PUBLISHING.reset(token)


def _memo(run: Any) -> _Memo | None:
    memo = getattr(run, "sequence_memo", None)
    if memo is None:
        state = _PUBLISHING.get()
        memo = None if state is None else state["memo"]
    return memo


# ----------------------------------------------------------------- set models (reads; never written here)
def _meta(run: Any, handle: Any) -> dict[str, Any] | None:
    if type(handle) is not str or not handle:
        return None
    try:
        return run.store.meta(handle)
    except (KeyError, ValueError, TypeError):
        return None


def candidate_set(run: Any, handle: Any) -> dict[str, Any]:
    """The validated M20 candidate set (and its ``prepared_structure@1``) of this run."""
    memo = _memo(run)
    if memo is not None and handle in memo.candidate_sets:
        return memo.candidate_sets[handle]
    try:
        content = mi.validated_candidate_set(handle, _meta(run, handle), run.store.load)
        mi.check_structure(content, _meta(run, content["structure"]["handle"]))
    except ToolFailure as exc:
        raise SequenceGaEvidenceError("the candidate set no longer validates") from exc
    if memo is not None:
        memo.candidate_sets[handle] = content
    return content


def model_producer(run: Any, handle: str) -> dict[str, Any]:
    """The earliest completed publication of a set model: a ``sequence_ga_dock_v1`` attempt's
    ``sequence_ga_individual_published`` naming it (reservation < verified cleanup < event; created < event)."""
    events = list(run.events.read())
    jobs = {event["job"]["job_id"]: event["job"] for event in events if event["type"] == "job_submitted"}
    created = [event for event in events if event["type"] == "object_created" and event.get("handle") == handle]
    for item in events:
        if item["type"] != SC.INDIVIDUAL_EVENT or item.get("model_handle") != handle:
            continue
        found = _publication(events, jobs, created, item)
        if found is not None:
            return found
    raise SequenceGaEvidenceError("object has no completed sequence_ga_dock_v1 publication")


def _publication(events: list[dict[str, Any]], jobs: Mapping[str, Any], created: list[dict[str, Any]],
                 item: dict[str, Any]) -> dict[str, Any] | None:
    job = jobs.get(item.get("job_id"))
    attempt = item.get("attempt_id")
    if job is None or job.get("protocol_id") != SC.PROTOCOL or job.get("tool_id") != SC.TOOL:
        return None
    reserved = [event for event in events if event["type"] == "budget_reserved" and
                event.get("attempt_id") == attempt and event.get("tool") == SC.TOOL]
    cleaned = [event for event in events if event["type"] == "job_cleanup_verified" and
               event.get("job_id") == job["job_id"] and event.get("attempt_id") == attempt and
               event.get("group_empty") is True]
    summary = [event for event in events if event["type"] == SC.SUMMARY_EVENT and
               event.get("job_id") == job["job_id"] and event.get("attempt_id") == attempt and
               event["seq"] > item["seq"]]
    if (len(reserved) == 1 and cleaned and created and reserved[0]["seq"] < cleaned[0]["seq"] < item["seq"] and
            created[0]["seq"] < item["seq"]):
        return {"job_id": job["job_id"], "attempt_id": attempt, "job": job, "created_seq": created[0]["seq"],
                "published_seq": (summary[0] if summary else item)["seq"], "key": item.get("key"),
                "model_handle": item.get("model_handle"), "result_handle": item.get("result_handle")}
    return None


def _key_matches(key: Any, mutations: list[dict[str, Any]]) -> bool:
    if key == SC.REFERENCE_KEY:
        return mutations == []
    return bool(mutations) and key == GI.key_text(row["candidate_index"] for row in mutations)


def _stored_cif(run: Any, entry: dict[str, Any]) -> bytes:
    meta = _meta(run, entry["structure_object"])
    _evidence(meta is not None and (meta["kind"], meta["schema"], meta["fmt"]) == STRUCTURE_TYPE,
              "the structure object is a mutation_set_model_structure@1 of this run")
    raw = run.store.load_bounded_bytes(entry["structure_object"], MAX_CIF_BYTES)
    _evidence(_sha(raw) == entry["structure_sha256"], "stored mmCIF bytes")
    return raw


def set_model(run: Any, handle: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """(content, publication evidence) of a stored set model, light check (``validated_model_alone``): the M18
    receptor path. The models ``finish`` is publishing right now come back without evidence (None)."""
    state = _PUBLISHING.get()
    if state is not None and handle in state["models"]:
        return state["models"][handle], None
    memo = _memo(run)
    if memo is not None and handle in memo.models:
        return memo.models[handle]
    try:
        meta = _meta(run, handle)
        _evidence(meta is not None and (meta["kind"], meta["schema"], meta["fmt"]) == MODEL_TYPE,
                  "expected a mutation_set_model@1 of this run")
        content = run.store.load_bounded_json(handle, SC.MAX_MODEL_OBJECT_BYTES)
        source = model_producer(run, handle)
        job = source["job"]
        selected = job["selected"]
        args = selected["arguments"]
        cset = candidate_set(run, args["candidate_set"])
        _evidence(type(content) is dict and type(content.get("structures")) is dict and
                  len(content["structures"]) == 1, "one structure")
        (entry,) = content["structures"].values()
        SM.validated_model_alone(content, run_id=run.run_id, candidate_set_handle=args["candidate_set"],
                                 candidate_set=cset, structure_cif=_stored_cif(run, entry))
        _evidence(content["candidate_set"] == args["candidate_set"] and content["structure"] == selected["structure"]
                  and content["seed"] == args["parameters"]["seed"] and
                  content["method"] == job["ga_method"]["model_method"], "the model is its publishing GA's")
        _evidence(_key_matches(source["key"], content["mutations"]), "the published key is the model's mutations")
    except SequenceGaEvidenceError:
        raise
    except (SM.ModelInvalid, KeyError, TypeError, ValueError, IndexError, AttributeError, OSError) as exc:
        raise SequenceGaEvidenceError("sequence model evidence is invalid") from exc
    if memo is not None:
        memo.models[handle] = (content, source)
    return content, source


def validated_set_model(run: Any, handle: Any, reference: dict[str, Any] | None = None) -> dict[str, Any]:
    """A stored set model with the full ``validated_model``: a mutant against ``reference`` (the validated wild-type
    reference row's model of the same conditions); the reference model takes none."""
    content, _source = set_model(run, handle)
    memo = _memo(run)
    key = (handle, None if reference is None or not content["mutations"] else
           reference["structures"][SC.REFERENCE_SIDE]["structure_sha256"])
    if memo is not None and key in memo.full:
        return memo.full[key]
    try:
        cset_handle = content["candidate_set"]
        (entry,) = content["structures"].values()
        SM.validated_model(content, run_id=run.run_id, candidate_set_handle=cset_handle,
                           candidate_set=candidate_set(run, cset_handle), structure_cif=_stored_cif(run, entry),
                           reference=reference if content["mutations"] else None)
    except SequenceGaEvidenceError:
        raise
    except (SM.ModelInvalid, KeyError, TypeError, ValueError, IndexError, AttributeError, OSError) as exc:
        raise SequenceGaEvidenceError("sequence model evidence is invalid") from exc
    if memo is not None:
        memo.full[key] = content
    return content


def set_model_receptor(run: Any, source: dict[str, Any]) -> dict[str, Any]:
    """``docking_bundle._mutation_receptor`` for a ``mutation_set_model@1`` handle (spec 8 (b)): the same shape as the
    M21 path (``{handle, raw, sha256, model_number, sidecar_raw}``), from the model's one structure (its key is
    ``side``) and its stored topology. ``mutation_model_invalid`` for anything but a published same-run set model;
    the M18 receptor rules (atom cap included) stay ``receptor_invalid``."""
    memo = _memo(run)
    cache = (source.get("mutation_model"), source.get("side")) if type(source) is dict else None
    if memo is not None and cache in memo.receptors:
        return dict(memo.receptors[cache])
    try:
        content, _evidence_record = set_model(run, source["mutation_model"])
        _evidence(set(content["structures"]) == {source["side"]}, "side is the model's one structure")
        entry = content["structures"][source["side"]]
        raw = _stored_cif(run, entry)
    except (SequenceGaEvidenceError, KeyError, TypeError, ValueError, OSError) as exc:
        raise docking_bundle._invalid("receptor_source.mutation_model is not a published mutation_set_model@1 of "
                                      "this run", "mutation_model_invalid") from exc
    handle, model_number = entry["structure_object"], content["structure"]["model_number"]
    rows = docking_inputs.receptor_rows(raw, "cif", handle, model_number)
    sidecar_raw = docking_inputs.mutation_model_sidecar(rows, entry["atom_mapping"], entry["final_bonds"], handle)
    out = {"handle": handle, "raw": raw, "sha256": entry["structure_sha256"], "model_number": model_number,
           "sidecar_raw": sidecar_raw}
    if memo is not None:
        memo.receptors[cache] = out
    return dict(out)


def _side(key: str) -> str:
    return SC.REFERENCE_SIDE if key == SC.REFERENCE_KEY else SC.MUTANT_SIDE


def m18_request(arguments: dict[str, Any], model_handle: str, side: str) -> dict[str, Any]:
    """The standalone M18 free request docking one model side with the GA's ligand, box and values (the request
    form of ``sequence_ga_inputs.individual_arguments``, which is its normalized copy)."""
    return {"receptor_source": {"kind": "mutation_model", "mutation_model": model_handle, "side": side},
            "ligand": dict(arguments["ligand"]), "mode": SC.MODE, "box": copy.deepcopy(arguments["box"]),
            "parameters": {key: arguments["parameters"][key] for key in GI.PARAMETER_KEYS},
            "acknowledgement": dict(arguments["acknowledgement"])}


def m18_selection(run: Any, arguments: dict[str, Any], model_handle: str, side: str) -> dict[str, Any]:
    """The ``docking_selection@1`` of one model side under the GA's ligand, box and values: the standalone M18
    admission itself (``docking_bundle.submission``) on ``m18_request``."""
    request = m18_request(arguments, model_handle, side)
    memo = _memo(run)
    key = canonical_json(request).decode()
    if memo is not None and key in memo.selections:
        return copy.deepcopy(memo.selections[key])
    selected, _normalized, _handles = docking_bundle.submission(run, request)
    if memo is not None:
        memo.selections[key] = copy.deepcopy(selected)
    return selected


def individual_view(run: Any, evidence: dict[str, Any]) -> dict[str, Any]:
    """``docking_bundle.producer`` for a GA individual: the publication evidence with the individual's M18 job view
    (the GA job with the rebuilt ``docking_selection@1`` of its model side; ``method`` is already the M18 pins)."""
    try:
        job = evidence["job"]
        key, model_handle = evidence["key"], evidence["model_handle"]
        content, _source = set_model(run, model_handle)
        _evidence(_key_matches(key, content["mutations"]), "the published key is the model's mutations")
        selected = m18_selection(run, job["selected"]["arguments"], model_handle, _side(key))
        return {**evidence, "job": {**job, "selected": selected}}
    except (SequenceGaEvidenceError, ToolFailure, KeyError, TypeError, ValueError, IndexError,
            AttributeError) as exc:
        raise docking_bundle.DockingEvidenceError("sequence GA individual publication evidence is invalid") from exc


# ----------------------------------------------------------------- admission (no job, no event, no budget)
def admission_timeout(args: Any) -> Any:
    """The timeout the screen always sends (``ga.total_s + 600``), for the limit raise whose body is the GA job
    arguments only; malformed arguments give None, which admission refuses (``invalid_job_arguments``)."""
    ga = args.get("ga") if type(args) is dict else None
    total = ga.get("total_s") if type(ga) is dict else None
    return total + SC.FINISH_MARGIN_S if type(total) is int else None


def submission(run: Any, args: Any, timeout_s: Any) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Steps 1-4 (spec 2): (selection record, normalized arguments, input handles)."""
    admitted = GI.admission(run, args, timeout_s)
    selected = SB.selection_record(admitted)
    return selected, admitted["arguments"], [selected["arguments"]["candidate_set"], selected["structure"]["handle"],
                                             selected["ligand"]["sdf_handle"]]


def _sdf_bytes(run: Any, selected: dict[str, Any]) -> bytes:
    ligand = selected["ligand"]
    return docking_bundle._import_bytes(run, ligand["sdf_handle"], "ligand_sdf", ligand["sdf_sha256"])


def _admitted(run: Any, selected: dict[str, Any]) -> dict[str, Any]:
    """The admission facts of a selection re-derived from the store (candidate set, space, the server's box)."""
    args = selected["arguments"]
    content, structure = GI.candidate_set_and_structure(run, args["candidate_set"])
    if structure != selected["structure"]:
        raise ValueError("the candidate set's structure differs from the selection")
    raw = _sdf_bytes(run, selected)
    ligand = GI.check_ligand_sdf(raw)
    return {"arguments": args, "candidate_set": content, "structure": structure, "ligand": dict(selected["ligand"]),
            "ligand_check": ligand, "box": GI.ligand_box(args["box"], ligand),
            "space": GI.candidate_space(content, args["ga"]["max_mutations"]), "sdf": raw}


def projection(run: Any, selected: dict[str, Any]) -> dict[str, Any]:
    """The M7 preflight projection of the selection's structure (422 ``openmm_preflight_failed``; the 412
    unavailability is the caller's earlier ``require_ready``)."""
    try:
        value = openmm_method.preflight(run.store, selected["structure"]["handle"],
                                        seed=selected["arguments"]["parameters"]["seed"])
    except ToolFailure as exc:
        raise mi.preflight_failure(exc) from exc
    if value["model_number"] != selected["structure"]["model_number"]:
        raise ToolFailure(FailureClass.input_invalid, "the candidate set's model is not the preflight model",
                          detail={"reason_code": "structure_invalid"})
    return value


def _checked(run: Any, selected: dict[str, Any], pins: dict[str, Any],
             reuse: dict[str, Any] | None = None) -> dict[str, Any]:
    """Steps 6-8 for a selection with the environment pinned: M7 preflight, positions, box atoms, space, then the
    staged manifest (with the reuse index found now) within 16 MiB."""
    projected = projection(run, selected)
    admitted = _admitted(run, selected)
    figures = GI.after_preflight(admitted, projected)
    reuse = reuse_plan(run, selected, pins) if reuse is None else reuse
    raw = manifest(run, selected, pins, reuse, admitted=admitted, projected=projected)
    GI.require_staged(len(raw))
    return {"projection": projected, "admitted": admitted, "figures": figures, "reuse": reuse, "raw": raw}


def selection(run: Any, selected: dict[str, Any]) -> dict[str, Any]:
    """Steps 5-8 after the dry-run point: the pins (412 when unavailable), then the M7 preflight and the 422 / 429
    checks. Nothing is recorded or charged."""
    pins = require_ready()
    _checked(run, selected, pins)
    return pins


def require_budget(run: Any, selected: dict[str, Any]) -> None:
    """Step 9: a short run budget refuses (429 ``ga_limit_raise_required``, nothing charged). The need is
    ``reserved_units`` whatever is reused (spec 7)."""
    GI.require_budget(GI.needed_budget(selected["arguments"]["ga"]), run.budget_snapshot())


def admission_plan(run: Any, args: Any, timeout_s: Any) -> dict[str, Any]:
    """Steps 1-8 for a read (T6 preflight): raises the first refusal; no job, event, reservation or charge."""
    selected, normalized, _handles = submission(run, args, timeout_s)
    pins = require_ready()
    checked = _checked(run, selected, pins)
    reuse = checked["reuse"]
    return {"selected": selected, "arguments": normalized, "pins": pins, "call_key": GI.call_key(selected, pins),
            "conditions_sha256": GI.conditions_sha256(selected, pins), "space": selected["space"],
            "projection_heavy_atoms": checked["figures"]["projection_heavy_atoms"],
            "heavy_atom_warning": checked["figures"]["heavy_atom_warning"], "reusable_count": len(reuse["records"]),
            "reference_reusable": reuse["reference"] is not None, "staged_bytes": len(checked["raw"])}


def _refuse_cancelled(run: Any) -> None:
    if run._cancel_path.exists() or run.cancelled:
        raise RunCancelled("run cancelled")


def limit_approval(run: Any, args: Any) -> dict[str, Any]:
    """Spec 7: the human-approved limit raise for one sequence GA, called only by its HTTP route (a UI action; never
    a tool, plan or workflow step, model command or loop action). Body = the GA job arguments. Dry-run runs refuse it
    (412 ``dry_run``, nothing written). The need (``reserved_units`` and its wall time) is recomputed from the
    request, and only the shortfall of the current budget is raised (``sequence_ga_inputs.limit_increase``, the M23
    constants) with one ``budget_limit_updated`` (by ``human``) carrying the GA context. Nothing short: nothing
    changes and no event is written. It never approves the first expensive call, reserves, charges or refunds. A
    cancelled run refuses it (``RunCancelled``). Every decision uses the snapshot ``Run.raise_limits`` plans with."""
    if run.dry_run:
        raise ToolFailure(FailureClass.precondition, "dry-run runs plan only; there is no limit to raise",
                          detail={"reason_code": "dry_run"})
    run._refresh()
    _refuse_cancelled(run)
    selected, _normalized, _handles = submission(run, args, admission_timeout(args))
    require_ready()
    ga = selected["arguments"]["ga"]
    units = GI.reserved_units(ga)
    needed = GI.needed_budget(ga)

    def plan(snapshot_: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        _refuse_cancelled(run)   # again under the run owner, right before the limit event
        return GI.limit_increase(needed, snapshot_), {
            "purpose": "sequence_ga_limit_raise", "selection_sha256": selected["selection_sha256"],
            "reserved_evaluations": GI.reserved_evaluations(ga), "reserved_units": units, "needed": needed,
            "shortfall": GI.shortfall(needed, snapshot_)}

    run._refresh()
    increase, context = plan(run.budget.snapshot())
    event = run.raise_limits(plan, by="human") if any(increase.values()) else None
    if event is not None:
        context = event["context"]
    else:
        limits = {axis: run.budget.snapshot()[axis]["limit"] for axis in GI.AXES}
        context = {**context, "increase": dict.fromkeys(GI.AXES, 0), "limits_before": limits, "limits_after": limits}
    budget = run.budget.snapshot()
    return {"raised": event is not None, "selection_sha256": context["selection_sha256"],
            "reserved_evaluations": context["reserved_evaluations"], "reserved_units": units, "needed": needed,
            "shortfall_before": context["shortfall"], "increase": context["increase"],
            "limits_before": context["limits_before"], "limits_after": context["limits_after"],
            "shortfall_after": GI.shortfall(needed, budget),
            "event_seq": None if event is None else event["seq"], "budget": budget}


def complete_job(run: Any, jobs: Mapping[str, dict[str, Any]], key: str) -> dict[str, Any] | None:
    """Spec 7: an active sequence GA job with this call key, else the job of a validated ``complete`` summary with
    it (a ``partial`` summary never deduplicates); None means a new job."""
    active = next((job for job in jobs.values() if job["protocol_id"] == SC.PROTOCOL and job["call_key"] == key and
                   job["status"] in ACTIVE), None)
    if active is not None:
        return active
    for event in list(run.events.read()):
        job = jobs.get(event.get("job_id")) if event["type"] == SC.SUMMARY_EVENT else None
        if job is None or job["protocol_id"] != SC.PROTOCOL or job["call_key"] != key:
            continue
        try:
            content = validated_summary(run, event["summary_handle"])
        except SequenceGaEvidenceError:
            continue
        if content["call_key"] == key and content["status"] == "complete":
            return job
    return None


# ----------------------------------------------------------------- reuse index (spec 4), once at the start
def _own_result(result: dict[str, Any], arguments: dict[str, Any], model_handle: str, side: str) -> bool:
    """The stored result is this model side's own standalone M18 request under the GA's ligand, box and values."""
    request = GI.individual_arguments(arguments, model_handle, side)
    return (result["input_sha256"] == docking_inputs.input_sha256(request) and
            result["inputs"]["receptor"]["source"] == request["receptor_source"])


def reuse_plan(run: Any, selected: dict[str, Any], pins: dict[str, Any]) -> dict[str, Any]:
    """``{"records": [...], "reference": ... | None}`` (spec 4): the individuals of earlier GAs of this run with the same
    ``conditions_sha256`` whose model and docking result are both stored and validated (state ``scored`` /
    ``null_result``; a failed individual has no result and is never reused), as small facts
    (``sequence_ga_inputs.reuse_record``; the score is the validated stored result's first mode). Mutant models are
    validated against the validated reference row model of the same conditions; keys outside this GA's space (another
    ``max_mutations``) are left out. One event-log read (``_Snapshot``). The first record of a key wins."""
    view = snapshot(run)
    args = selected["arguments"]
    conditions = GI.conditions_sha256(selected, pins)
    cset = candidate_set(view, args["candidate_set"])
    space = GI.candidate_space(cset, args["ga"]["max_mutations"])
    published = [event for event in view.read() if event["type"] == SC.INDIVIDUAL_EVENT and
                 event.get("conditions_sha256") == conditions and type(event.get("model_handle")) is str]
    reference_model = None
    for event in published:
        if event.get("key") == SC.REFERENCE_KEY:
            try:
                reference_model = validated_set_model(view, event["model_handle"])
                break
            except SequenceGaEvidenceError:
                continue
    records: list[dict[str, Any]] = []
    reference_record = None
    for event in published:
        key, model_handle, result_handle = event.get("key"), event["model_handle"], event.get("result_handle")
        if type(result_handle) is not str or (key == SC.REFERENCE_KEY and reference_record is not None):
            continue
        try:
            rows = [] if key == SC.REFERENCE_KEY else GI.key_mutations(cset, space, key)
            if rows and reference_model is None:
                continue
            model = validated_set_model(view, model_handle, reference_model if rows else None)
            _evidence(model["mutations"] == [{**row, "mutant_resname": MK.THREE_LETTER[row["to"]]} for row in rows]
                      and model["candidate_set"] == args["candidate_set"] and
                      model["structure"] == selected["structure"] and model["seed"] == args["parameters"]["seed"]
                      and model["method"] == pins["model_method"], "the model is of these conditions")
            result = docking_bundle.validated_result(view, result_handle)
            _evidence(_own_result(result, args, model_handle, _side(key)), "the result is the model's own docking")
            record = GI.reuse_record(key, model_handle=model_handle, result_handle=result_handle, result=result)
        except (SequenceGaEvidenceError, docking_bundle.DockingEvidenceError, ToolFailure, KeyError, TypeError,
                ValueError, IndexError, AttributeError):
            continue
        if key == SC.REFERENCE_KEY:
            (entry,) = model["structures"].values()
            reference_record = {**record, "model_summary": {name: copy.deepcopy(entry[name]) for name in
                                                            ("structure_sha256", "protonation_variants",
                                                             "disulfide_bonds")}}
        else:
            records.append(record)
    return {"records": list(GI.reuse_index(records).values()), "reference": reference_record}


# ----------------------------------------------------------------- staging
def _b64(raw: bytes) -> dict[str, str]:
    return {"b64": base64.b64encode(raw).decode(), "sha256": _sha(raw)}


def manifest(run: Any, selected: dict[str, Any], pins: dict[str, Any], reuse: dict[str, Any], *,
             admitted: dict[str, Any] | None = None, projected: dict[str, Any] | None = None) -> bytes:
    """The worker manifest ``sequence_ga_worker_input@1`` (worker docstring): nothing in it is read from the request
    (selection record, immutable imports, the validated candidate set, the M7 projection, the job's pins, the reuse
    facts)."""
    args = selected["arguments"]
    admitted = _admitted(run, selected) if admitted is None else admitted
    projected = projection(run, selected) if projected is None else projected
    content = admitted["candidate_set"]
    candidates = [{"index": row["index"], "position_index": row["position_index"],
                   "residue": seven(content["positions"][row["position_index"]]["residue"]), "from": row["from"],
                   "to": row["to"], "mutant_resname": MK.THREE_LETTER[row["to"]]} for row in content["candidates"]]
    method = {key: value for key, value in pins["model_method"].items() if key not in SC.MULTI_MUTATION_METHOD}
    return canonical_json({
        "schema": SC.WORKER_INPUT_SCHEMA, "run_id": run.run_id, "project_python": str(PROJECT_PYTHON),
        "candidate_set": args["candidate_set"], "structure": dict(selected["structure"]),
        "model_number": projected["model_number"], "protein": projected["protein"], "method": method,
        "ligand_sdf": _b64(admitted["sdf"]), "box": copy.deepcopy(args["box"]),
        "parameters": dict(args["parameters"]), "ga": dict(args["ga"]), "candidates": candidates,
        "reuse": copy.deepcopy(reuse["records"]), "reference_reuse": copy.deepcopy(reuse["reference"]),
        "selection_sha256": selected["selection_sha256"],
        "conditions_sha256": GI.conditions_sha256(selected, pins)})


def start_plan(run: Any, job: dict[str, Any]) -> dict[str, Any]:
    """At the start, once, under the run owner and before the reservation: the reuse index, the staged manifest
    bytes (429 ``staged_input_bytes`` before anything is charged; the reuse set can have grown since admission) and
    the reservation ``reserved_units`` (whatever is reused, no refund)."""
    selected = job["selected"]
    pins = job_pins(job)
    reuse = reuse_plan(run, selected, pins)
    raw = manifest(run, selected, pins, reuse)
    GI.require_staged(len(raw))
    return {"reuse": reuse, "raw": raw, "units": GI.reserved_units(selected["arguments"]["ga"])}


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


def _status(directory: Path | None, name: str) -> dict[str, Any] | None:
    """A status file inside the closed sets, else None."""
    data = _canonical(_read(directory, name, MAX_STATUS_BYTES))
    ok = (type(data) is dict and set(data) == STATUS_KEYS and data["state"] in SC.STATES and
          data["stage"] in SC.STAGES and data["reason_code"] in SB.REASONS_BY_STATE[data["state"]])
    return data if ok else None


def _end_record(attempt_dir: Path | None, job: dict[str, Any], attempt_id: str) -> dict[str, Any] | None:
    data = _canonical(_read(attempt_dir, "result.json", MAX_END_BYTES))
    ok = (type(data) is dict and set(data) == END_KEYS and data["schema"] == SC.WORKER_OUTPUT_SCHEMA and
          data["protocol"] == SC.PROTOCOL and data["job_id"] == job["job_id"] and
          data["attempt_id"] == attempt_id and data["stop_reason"] in SC.STOP_REASONS and
          type(data["generations_done"]) is int)
    return data if ok else None


def _prepared(attempt_dir: Path | None) -> dict[str, Any] | None:
    data = _canonical(_read(attempt_dir, "prepared.json", MAX_PREPARED_BYTES))
    return data if type(data) is dict and set(data) == PREPARED_KEYS else None


def _records(attempt_dir: Path | None) -> tuple[list[Any], bool]:
    """(the readable worker generation records 1, 2, ... in order, intact); as M22: the list stops before the first
    present but unreadable record; a gap or a stray file after the readable ones is not intact."""
    directory = _subdir(attempt_dir, "generations")
    if directory is None:
        return [], True
    try:
        names = {entry.name for entry in os.scandir(directory) if entry.is_file(follow_symlinks=False)}
    except OSError:
        return [], False
    records = []
    for number in range(1, len(names) + 2):
        if f"{number}.json" not in names:
            break
        data = _canonical(_read(directory, f"{number}.json", MAX_GENERATION_BYTES))
        if type(data) is not dict or data.get("index") != number:
            return records, False
        records.append(data)
    intact = {f"{n}.json" for n in range(1, len(records) + 1)} == {name for name in names if not name.endswith(".tmp")}
    return records, intact


def _entries_ok(record: Any, cset: dict[str, Any], space: dict[str, Any], reused: Mapping[str, Any],
                seen: set[int]) -> bool:
    """A generation record whose entries are keys of this GA's space, whose evaluated entries agree with the start's
    reuse plan and carry unused integer eval indices (``seen`` collects the indices of an accepted record)."""
    if (type(record) is not dict or set(record) != RECORD_KEYS or type(record["individuals"]) is not list or
            type(record["complete"]) is not bool):
        return False
    indices = set()
    for entry in record["individuals"]:
        if type(entry) is not dict or set(entry) != ENTRY_KEYS:
            return False
        try:
            GI.key_mutations(cset, space, entry["key"])
        except (ValueError, KeyError, IndexError, TypeError):
            return False
        if entry["origin"] == "carried":
            continue
        evaluation, index = entry["evaluation"], entry["eval_index"]
        if evaluation not in SC.EVALUATIONS or (evaluation == "reused") != (entry["key"] in reused):
            return False
        if evaluation == "reused" and index is not None:
            return False
        if evaluation == "computed" and (type(index) is not int or index < 0 or index in seen or index in indices):
            return False
        if evaluation == "computed":
            indices.add(index)
    seen |= indices
    return True


def _count(directory: Path | None, suffix: str) -> int:
    try:
        return 0 if directory is None else sum(entry.name.endswith(suffix) and entry.is_file(follow_symlinks=False)
                                               for entry in os.scandir(directory))
    except OSError:
        return 0


def progress(run: Any, job: dict[str, Any]) -> dict[str, Any]:
    """Polling view (spec 9): figures from the job record, then the attempt's staged file counts only (the reference
    row's status file, ``individuals/*.started`` and ``*.status.json``: new evaluations only, a reused individual has
    no file; generation records and how many say ``complete``) and the summary handle once published, with that
    summary's ``status`` / ``stop_reason`` through ``validated_summary`` (null when it does not validate). No object
    is loaded before a summary exists; no event, job or tool."""
    selected = job["selected"]
    ga = selected["arguments"]["ga"]
    reuse = (job.get("dispatch_intent") or {}).get("sequence_reuse") or {}
    started = finished = generations = complete = reference = 0
    attempt = job.get("attempt_id")
    if type(attempt) is str and ID_RE.fullmatch(attempt) and ID_RE.fullmatch(job["job_id"]):
        attempt_dir = run.run_dir / "jobs" / job["job_id"] / attempt
        try:
            reference = int(stat.S_ISREG(os.lstat(attempt_dir / (REFERENCE_PREFIX + "status.json")).st_mode))
        except OSError:
            reference = 0
        individuals = _subdir(attempt_dir, "individuals")
        started, finished = _count(individuals, ".started"), _count(individuals, ".status.json")
        directory = _subdir(attempt_dir, "generations")
        generations = _count(directory, ".json")
        for number in range(1, generations + 1):
            data = _canonical(_read(directory, f"{number}.json", MAX_GENERATION_BYTES))
            complete += type(data) is dict and data.get("complete") is True
    handle = job.get("sequence_ga_summary_handle")
    status = stop_reason = None
    if handle is not None:
        try:
            content = validated_summary(run, handle)
            status, stop_reason = content["status"], content["stop_reason"]
        except SequenceGaEvidenceError:
            pass
    return {"space": dict(selected["space"]), "reserved_evaluations": GI.reserved_evaluations(ga),
            "reserved_units": GI.reserved_units(ga), "reused_planned": len(reuse.get("records") or []),
            "reference_reuse_planned": reuse.get("reference") is not None, "reference_recorded": bool(reference),
            "individuals_started": started, "individuals_finished": finished, "generation_records": generations,
            "generations_complete": complete, "summary_handle": handle, "summary_status": status,
            "summary_stop_reason": stop_reason}


# ----------------------------------------------------------------- publication (after the group is verified empty)
def _context(run: Any, job: dict[str, Any]) -> dict[str, Any]:
    selected = job["selected"]
    pins = job_pins(job)
    admitted = _admitted(run, selected)
    return {"job": job, "selected": selected, "args": selected["arguments"], "pins": pins,
            "candidate_set": admitted["candidate_set"], "space": admitted["space"], "box": admitted["box"],
            "projection": projection(run, selected), "conditions": GI.conditions_sha256(selected, pins)}


def _projection_heavy(protein: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [(identity(r["residue"]), a["atom_name"], a["element"]) for c in protein for r in c["residues"]
            for a in r["atoms"]]


def _publish_model(run: Any, ctx: dict[str, Any], attempt_id: str, directory: Path | None, prefix: str,
                   rows: list[dict[str, Any]], reference: dict[str, Any] | None) -> tuple[str, dict[str, Any]] | None:
    """One model of the worker: rebuilt by the server (byte-identical), fully validated, its mmCIF rows checked, the
    reference row bound to the M7 projection; then the mmCIF object and the model object are stored (or None)."""
    model_raw = _read(directory, prefix + "model.json", SC.MAX_MODEL_OBJECT_BYTES)
    cif_raw = _read(directory, prefix + "model.cif", MAX_CIF_BYTES)
    data = _canonical(model_raw)
    args = ctx["args"]
    try:
        side = SM.side(rows)
        _evidence(type(data) is dict and cif_raw is not None and type(data.get("structures")) is dict and
                  set(data["structures"]) == {side} and type(data["structures"][side]) is dict, "model files")
        entry = {key: value for key, value in data["structures"][side].items() if key != "structure_object"}
        content = SM.model_content(run_id=run.run_id, candidate_set_handle=args["candidate_set"],
                                   structure=ctx["selected"]["structure"], mutations=rows,
                                   seed=args["parameters"]["seed"], method=ctx["pins"]["model_method"], entry=entry,
                                   cif_raw=cif_raw, reference=reference)
        _evidence(canonical_json(content) == model_raw, "the worker model is the server's rebuild")
        SM.validated_model(content, run_id=run.run_id, candidate_set_handle=args["candidate_set"],
                           candidate_set=ctx["candidate_set"], structure_cif=cif_raw,
                           reference=reference if rows else None)
        atoms = content["structures"][side]["atom_mapping"]
        _cif(cif_raw.decode(), atoms, [atom["coordinates_A"] for atom in atoms],
             ctx["selected"]["structure"]["model_number"])
        if not rows:
            heavy = [(identity(a["residue"]), a["atom_name"], a["element"]) for a in atoms
                     if a["element"] not in MK.HYDROGEN_ELEMENTS]
            _evidence(heavy == _projection_heavy(ctx["projection"]["protein"]),
                      "the reference model's heavy atoms are the M7 projection")
    except (SequenceGaEvidenceError, SM.ModelInvalid, KeyError, TypeError, ValueError, IndexError, AttributeError,
            UnicodeError, RuntimeError):
        return None
    stored = run.store.put(SC.STRUCTURE_OBJECT_KIND, SC.STRUCTURE_OBJECT_SCHEMA, cif_raw, fmt="cif",
                           produced_by=attempt_id)
    _fatal(stored.handle == content["structures"][side]["structure_object"], "structure object handle")
    out = run.store.put(SC.MODEL_KIND, SC.MODEL_SCHEMA, content, produced_by=attempt_id,
                        summary={"candidate_set": content["candidate_set"],
                                 "structure": content["structure"]["handle"], "seed": content["seed"],
                                 "key": SC.REFERENCE_KEY if not rows else
                                 GI.key_text(row["candidate_index"] for row in rows)})
    return out.handle, content


def _publish_result(run: Any, ctx: dict[str, Any], attempt_id: str, directory: Path | None, prefix: str,
                    model_handle: str, side: str) -> tuple[str, dict[str, Any]] | None:
    """One docking output of the worker as the individual's standalone M18 result, with every M18 check (or None).
    A docked receptor that is not the stored model (hash, sidecar, source) is fatal."""
    data = _canonical(_read(directory, prefix + "result.json", C.MAX_RESULT_BYTES))
    job = ctx["job"]
    if type(data) is not dict or data.get("job_id") != job["job_id"] or data.get("attempt_id") != attempt_id:
        return None
    try:
        selected = m18_selection(run, ctx["args"], model_handle, side)
    except ToolFailure as exc:
        raise SequenceGaFatal("the stored model is not an M18 receptor although the worker docked it") from exc
    recorded = selected["receptor_source"]
    inputs = data.get("inputs")
    echo = inputs.get("receptor") if type(inputs) is dict else None
    _fatal(echo == {"sha256": selected["receptor"]["sha256"], "format": "cif", "model_number": recorded["model_number"],
                    "atom_count": selected["receptor"]["atom_count"],
                    "connectivity": {"kind": "sidecar", "sidecar_sha256": recorded["sidecar_sha256"]},
                    "removed_instance": None},
           "the docked receptor is not the stored model (mmCIF or sidecar hash)")
    view = {**job, "selected": selected}
    try:
        content = docking_bundle.result_content(view, data)
        return docking_bundle.store_result(run, view, attempt_id, content), content
    except (docking_bundle.DockingEvidenceError, docking_bundle.DockingJobFailure, ToolFailure, KeyError, TypeError,
            ValueError, IndexError, AttributeError, OSError, RecursionError):
        return None


def _publish_row(run: Any, ctx: dict[str, Any], attempt_id: str, directory: Path | None, prefix: str, key: str,
                 rows: list[dict[str, Any]], status: dict[str, Any] | None, reference: dict[str, Any] | None,
                 models: dict[str, Any], results: dict[str, Any], recorded: set[tuple]) -> tuple[Any, Any]:
    """(model handle | None, result handle | None) of one new evaluation, in the spec 8 order: mmCIF -> model ->
    docking result -> ``sequence_ga_individual_published`` (one event per stored model)."""
    if status is not None and status["stage"] == "model":
        return None, None                                  # the modeling step failed: the worker stored nothing
    published = _publish_model(run, ctx, attempt_id, directory, prefix, rows, reference)
    if published is None:
        return None, None
    model_handle, content = published
    models[model_handle] = content
    result_handle = None
    if status is None or status["state"] in ("scored", "null_result"):
        found = _publish_result(run, ctx, attempt_id, directory, prefix, model_handle, SM.side(rows))
        if found is not None:
            result_handle, results[found[0]] = found
    job = ctx["job"]
    if (key, model_handle, result_handle) not in recorded:
        run.events.append(SC.INDIVIDUAL_EVENT, job_id=job["job_id"], attempt_id=attempt_id, key=key,
                          model_handle=model_handle, result_handle=result_handle,
                          conditions_sha256=ctx["conditions"])
        recorded.add((key, model_handle, result_handle))
    return model_handle, result_handle


def _same_box(ctx: dict[str, Any], prepared: dict[str, Any]) -> None:
    """Spec 8: when the server and the worker both have a box, it is the same box. Checked before the reference row
    or any individual is published: a mismatch ends the job fatal with nothing of the attempt stored."""
    server, worker = ctx["box"], prepared["box"]
    _fatal(server is None or worker is None or worker == server, "the worker's box is not the server's")


def _summary_box(ctx: dict[str, Any], prepared: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any] | None:
    """Spec 8: the server's box (``_same_box`` compared it with the worker's before publication); a null worker box
    only with a ligand / box refusal of the reference row; the worker's box when the server could not read the
    ligand."""
    server, worker = ctx["box"], prepared["box"]
    if worker is None:
        _fatal(reference["state"] == "failed" and reference["reason_code"] in SB.BOXLESS_REASONS,
               "the worker computed no box although the reference row was not refused for its ligand or box")
        return copy.deepcopy(server)
    return copy.deepcopy(worker if server is None else server)


def _stop_reason(attempt_dir: Path | None, job: dict[str, Any], attempt_id: str, server_cause: str | None,
                 records: list[Any], intact: bool, reference_failed: bool) -> str:
    """A failed reference row is ``reference_failed`` whatever stopped the worker; then the server's stop cause;
    else ``worker_failed`` when the worker's records are not intact, its end record is missing or disagrees, or it
    says ``cancelled`` (no user cancel) or ``reference_failed`` (a reference row that did not fail)."""
    if reference_failed:
        return "reference_failed"
    if server_cause is not None:
        return server_cause
    end = _end_record(attempt_dir, job, attempt_id)
    if (not intact or end is None or
            end["generations_done"] != sum(type(r) is dict and r.get("complete") is True for r in records)):
        return "worker_failed"
    return "worker_failed" if end["stop_reason"] in ("cancelled", "reference_failed") else end["stop_reason"]


def finish(run: Any, job: dict[str, Any], attempt_id: str, attempt_dir: Path | None,
           server_cause: str | None) -> str | None:
    """Publish the reference row and the newly evaluated individuals, then the summary; return the summary handle, or
    None when the worker stopped before ``reference.status.json`` (no summary; spec 4).

    ``server_cause``: None (the worker ended by itself), ``cancelled`` (user), ``time_exhausted`` (job deadline) or
    ``worker_failed`` (crash, kill, limit, parent loss). Every new evaluation of the readable generation records is
    published before the run's end is decided (M22); unreadable, gapped or malformed records end as
    ``worker_failed``, never an exception. Raises ``SequenceGaFatal`` for a worker output that contradicts the
    server's records, and when the summary itself cannot be built."""
    status_ref = _status(attempt_dir, REFERENCE_PREFIX + "status.json")
    if status_ref is None:
        return None
    prepared = _prepared(attempt_dir)
    _fatal(prepared is not None, "prepared.json is missing after the reference row")
    ctx = _context(run, job)
    pins = ctx["pins"]
    engine = prepared["engine"]
    _fatal(prepared["model_method"] == pins["model_method"] and type(engine) is dict and
           engine.get("name") == C.ENGINE and engine.get("binary_sha256") == pins["docking"]["qvina_sha256"] and
           engine.get("package") == pins["docking"]["qvina_package"], "the worker's engine or model method")
    _same_box(ctx, prepared)
    reuse = job["dispatch_intent"]["sequence_reuse"]
    reused = {record["key"]: record for record in reuse["records"]}
    readable, intact = _records(attempt_dir)
    records: list[Any] = []
    seen: set[int] = set()
    for record in readable:
        if not _entries_ok(record, ctx["candidate_set"], ctx["space"], reused, seen):
            intact = False
            break
        records.append(record)
    recorded = {(event.get("key"), event.get("model_handle"), event.get("result_handle"))
                for event in run.events.read()
                if event["type"] == SC.INDIVIDUAL_EVENT and event.get("attempt_id") == attempt_id}
    models: dict[str, Any] = {}
    results: dict[str, Any] = {}
    observations: dict[str, Any] = {}
    individuals = _subdir(attempt_dir, "individuals")
    fact = reuse["reference"]
    with _publishing(models):
        if fact is not None:
            _fatal(status_ref == {"state": fact["state"], "reason_code": None, "stage": "docking"},
                   "the reused reference row's status")
            reference_model = validated_set_model(snapshot(run), fact["model_handle"])
            models[fact["model_handle"]] = reference_model
            reference = {"evaluation": "reused", "state": fact["state"], "reason_code": None,
                         "model_handle": fact["model_handle"], "result_handle": fact["result_handle"]}
        else:
            model_handle, result_handle = _publish_row(run, ctx, attempt_id, attempt_dir, REFERENCE_PREFIX,
                                                       SC.REFERENCE_KEY, [], status_ref, None, models, results,
                                                       recorded)
            reference = {"evaluation": "computed",
                         **SB.resolve_observation(status_ref, model_handle, result_handle, results)}
            reference_model = models.get(model_handle) if model_handle is not None else None
        reused_keys = []
        for record in records:
            for entry in record["individuals"]:
                if entry["origin"] == "carried":
                    continue
                key = entry["key"]
                if entry["evaluation"] == "reused":
                    reused_keys.append(key)
                    continue
                index = entry["eval_index"]
                status = _status(individuals, f"{index}.status.json")
                rows = SM.model_mutations(ctx["candidate_set"], key)
                model_handle, result_handle = (None, None) if reference_model is None else _publish_row(
                    run, ctx, attempt_id, individuals, f"{index}.", key, rows, status, reference_model, models,
                    results, recorded)
                observations[key] = SB.resolve_observation(status, model_handle, result_handle, results)
    # Reused rows (their evidence is earlier) are validated again on one fresh read, after every new row.
    view = snapshot(run)
    try:
        if fact is not None:
            results[fact["result_handle"]] = docking_bundle.validated_result(view, fact["result_handle"])
        for key in reused_keys:
            item = reused[key]
            models[item["model_handle"]] = validated_set_model(view, item["model_handle"], reference_model)
            results[item["result_handle"]] = docking_bundle.validated_result(view, item["result_handle"])
            observations[key] = {"state": item["state"], "reason_code": None, "model_handle": item["model_handle"],
                                 "result_handle": item["result_handle"]}
    except (SequenceGaEvidenceError, docking_bundle.DockingEvidenceError) as exc:
        raise SequenceGaFatal("a reused row no longer validates") from exc
    box = _summary_box(ctx, prepared, reference)
    cause = _stop_reason(attempt_dir, job, attempt_id, server_cause, records, intact, reference["state"] == "failed")

    def build(stop: str) -> dict[str, Any]:
        return SB.build_summary(ctx["selected"], candidate_set=ctx["candidate_set"], records=records,
                                reference=reference, observations=observations, results=results, models=models,
                                stop_reason=stop, box=box, pins=pins)

    try:
        content = build(cause)
    except SequenceGaEvidenceError:
        if server_cause is not None or cause in SB.OUTSIDE_STOPS or cause == "reference_failed":
            raise
        content = build("worker_failed")   # the worker's own stop disagrees with its records
    _fatal(content["call_key"] == job["call_key"], "GA call key")
    out = run.store.put(SC.OUTPUT_KIND, SC.SUMMARY_SCHEMA, content, produced_by=attempt_id,
                        summary={"selection_sha256": content["selection_sha256"], "status": content["status"],
                                 "stop_reason": content["stop_reason"],
                                 "generations_done": content["generations_done"],
                                 "new_evaluations_used": content["new_evaluations_used"],
                                 "reused_count": content["reused_count"]})
    if not any(event["type"] == SC.SUMMARY_EVENT and event.get("attempt_id") == attempt_id and
               event.get("summary_handle") == out.handle for event in run.events.read()):
        run.events.append(SC.SUMMARY_EVENT, job_id=job["job_id"], attempt_id=attempt_id, summary_handle=out.handle,
                          reused_count=content["reused_count"])
    return out.handle


# ----------------------------------------------------------------- validated reads (never run anything)
def summary_producer(run: Any, handle: str) -> dict[str, Any]:
    """The sequence GA attempt that published ``handle`` (reservation < verified cleanup < summary publication)."""
    events = list(run.events.read())
    jobs = {event["job"]["job_id"]: event["job"] for event in events if event["type"] == "job_submitted"}
    created = [event for event in events if event["type"] == "object_created" and event.get("handle") == handle]
    for published in events:
        if published["type"] != SC.SUMMARY_EVENT or published.get("summary_handle") != handle:
            continue
        job = jobs.get(published.get("job_id"))
        attempt = published.get("attempt_id")
        if job is None or job.get("protocol_id") != SC.PROTOCOL or job.get("tool_id") != SC.TOOL:
            continue
        reserved = [event for event in events if event["type"] == "budget_reserved" and
                    event.get("attempt_id") == attempt and event.get("tool") == SC.TOOL]
        cleaned = [event for event in events if event["type"] == "job_cleanup_verified" and
                   event.get("job_id") == job["job_id"] and event.get("attempt_id") == attempt and
                   event.get("group_empty") is True]
        if (len(reserved) == 1 and cleaned and created and
                reserved[0]["seq"] < cleaned[0]["seq"] < published["seq"] and created[0]["seq"] < published["seq"]):
            return {"job_id": job["job_id"], "attempt_id": attempt, "job": job, "created_seq": created[0]["seq"],
                    "published_seq": published["seq"], "reserved_units": reserved[0].get("expensive_calls")}
    raise SequenceGaEvidenceError("object has no completed sequence_ga_dock_v1 publication")


def validated_summary(run: Any, handle: Any) -> dict[str, Any]:
    """The stored summary, re-checked against its single publication, its job's selection and pins, the validated
    candidate set, every model (fully: mutants against the reference row's model) and every individual's M18 result;
    the reservation must be ``reserved_units``. One event-log read for all of it (spec 9)."""
    try:
        _evidence(type(handle) is str, "handle must be a string")
        meta = _meta(run, handle)
        _evidence(meta is not None and (meta["kind"], meta["schema"], meta["fmt"]) ==
                  (SC.OUTPUT_KIND, SC.SUMMARY_SCHEMA, "json"), "expected a sequence_ga_result@1 of this run")
        content = run.store.load_bounded_json(handle, SC.MAX_SUMMARY_BYTES)
        view = snapshot(run)
        source = summary_producer(view, handle)
        job = source["job"]
        selected = job["selected"]
        pins = job_pins(job)
        cset = candidate_set(view, selected["arguments"]["candidate_set"])
        models: dict[str, Any] = {}
        reference = content["reference"]
        reference_model = None
        if reference["model_handle"] is not None:
            reference_model = models[reference["model_handle"]] = validated_set_model(view, reference["model_handle"])
        rows = [reference] + [entry for generation in content["generations"] for entry in generation["individuals"]]
        for entry in rows:
            if entry["model_handle"] is not None and entry["model_handle"] not in models:
                models[entry["model_handle"]] = validated_set_model(view, entry["model_handle"], reference_model)
        results = {entry["result_handle"]: docking_bundle.validated_result(view, entry["result_handle"])
                   for entry in rows if entry["result_handle"] is not None}
        SB.validated_summary(content, selected=selected, candidate_set=cset, results=results, models=models,
                             pins=pins)
        _evidence(content["call_key"] == job["call_key"] == GI.call_key(selected, pins), "GA call key")
        _evidence(source["reserved_units"] == content["reserved_units"], "the reservation is reserved_units")
        return content
    except SequenceGaEvidenceError:
        raise
    except (docking_bundle.DockingEvidenceError, ToolFailure, KeyError, TypeError, ValueError, IndexError,
            AttributeError, OSError) as exc:
        raise SequenceGaEvidenceError("sequence GA summary evidence is invalid") from exc
