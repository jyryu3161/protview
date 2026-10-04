"""M21 ``openmm_mutation_model_v1`` job lane on the server side: capability, admission, call key, staging, worker
errors, publication and validated reads (spec .dryforge/spec.md 2, 4, 5).

The server never imports PDBFixer (its presence and version come from ``importlib.metadata`` only) and imports OpenMM
only through the existing M7 ``openmm_method.dependencies()`` / ``preflight()`` path. Modeling runs only in the fixed
worker ``mw/jobs/openmm_mutation_worker.py`` (project interpreter, as M7).

Submission order (``JobQueue.submit``): ``admission`` (pure checks 1--7 of ``mutation_model_inputs`` plus the
``JobSubmit.timeout_s`` field, 422) -> dry-run plan (as M7, before any engine) -> ``selection`` (unavailability 412:
process identity, OpenMM, PDBFixer; then the M7 preflight, whose failures are 422 ``openmm_preflight_failed``) ->
``call_key`` (normalized arguments + worker SHA-256 + dependency SHA-256 map + fixed method record; never the
timeout). Nothing is reserved or
charged before a job starts.

Publication (``publish``) re-validates the worker output against the job's selection and the pinned method, checks
each mmCIF against its atom rows and SHA-256, binds the wild-type heavy atoms to the staged M7 projection, runs the
pure ``validated_model`` on the final content and only then stores the two mmCIF objects
(``mutation_model_structure@1``) and one ``mutation_model@1`` object. Object contents hold no time, job or attempt
identity (same input -> same handle). Every read (``validated_result``, ``structure_bytes``) re-validates the stored
object against its single completed publication, its job selection and the stored mmCIF bytes; the objects recover
from ``events.jsonl`` alone, without any engine.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from . import mutation_model_constants as K
from . import mutation_model_inputs as mi
from . import mutation_model_math as mm
from .core.errors import FailureClass, ToolFailure
from .core.events import idempotency_key
from .core.handles import HANDLE_PREFIX, canonical_json, object_sha
from .mutation_candidates import identity, validated_set
from .openmm_bundle import _cif
from .tools import openmm_method
from .tools.structural import structure_residues

ROOT = Path(__file__).resolve().parents[2]
# Deployment-fixed path; a request can never name an interpreter, module, path, env or argv.
WORKER = ROOT / "backend/mw/jobs/openmm_mutation_worker.py"
# The project modules the worker imports (its results and the validated content depend on them), hashed into the
# call key and the start-time recheck like the worker itself (as M18 pins its constants file).
DEPENDENCIES = {name: ROOT / "backend" / name for name in (
    "mw/mutation_model_math.py", "mw/mutation_model_constants.py", "mw/jobs/openmm_worker.py",
    "mw/tools/openmm_method.py", "mw/mutation_candidates.py")}
PROTOCOL = K.PROTOCOL
TOOL = K.TOOL
IMPLEMENTATION = "openmm_mutation_model_v1@1"
SELECTION_SCHEMA = "mutation_model_selection@1"
INPUT_SCHEMA = "openmm_mutation_model_input@1"      # = openmm_mutation_worker.INPUT_SCHEMA
OUTPUT_SCHEMA = "mutation_model_worker_output@1"    # = openmm_mutation_worker.OUTPUT_SCHEMA
STRUCTURE_OBJECT_KIND = "mutation_model_structure"
STRUCTURE_OBJECT_SCHEMA = "mutation_model_structure@1"
STAGED_LIMIT = 4_000_000          # the M7 staged-selection bound (the same M7 protein projection is staged)
OUTPUT_LIMIT = 64_000_000         # = openmm_mutation_worker.MAX_OUTPUT_BYTES = the guardian's read bound
MAX_MODEL_BYTES = 64_000_000      # stored mutation_model@1 canonical JSON; larger is resource_exceeded, never truncated
MAX_STRUCTURE_BYTES = OUTPUT_LIMIT
MAX_ERROR_BYTES = 64 * 1024
OUTPUT_KEYS = frozenset({"schema", "method", "structures", "structure_cifs", "comparison", "protonation_differences",
                         "limitations"})
REASONS = {
    "openmm_unavailable": "고정 OpenMM 8.6.0 CPU 포스필드(amber14-all + implicit/gbn2)를 사용할 수 없습니다.",
    "pdbfixer_unavailable": "고정 PDBFixer 1.12.0이 프로젝트 환경에 설치되어 있지 않습니다.",
    "process_identity_unavailable": "작업 프로세스 신원 어댑터(psutil 7.2.2 raw 시작 신원)를 사용할 수 없습니다.",
}
# Worker failure reason -> job failure class (the reason itself is the closed ``detail.reason_code``).
FAILURE_CLASSES = {"mutation_modeling_failed": "input_invalid", "unexpected_atoms_added": "input_invalid",
                   "coordinates_changed": "input_invalid", "topology_unsupported": "input_invalid",
                   "energy_invalid": "fatal", "engine_failed": "fatal", "resource_exceeded": "resource_exceeded"}


class MutationJobFailure(Exception):
    """A typed attempt failure after reservation (charged); nothing is published."""

    def __init__(self, failure_class: str, reason_code: str, message: str, detail: dict[str, Any]) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.reason_code = reason_code
        self.message = message
        self.detail = {"reason_code": reason_code, **detail}

    def to_error(self) -> dict[str, Any]:
        return {"error": self.failure_class, "reason_code": self.reason_code, "message": self.message,
                "detail": self.detail}


class MutationEvidenceError(ValueError):
    """A stored or produced mutation model does not validate against its inputs and publication."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise MutationEvidenceError(message)


# ----------------------------------------------------------------- capability (PDBFixer by metadata only)
def _pdbfixer_version() -> str:
    return version("pdbfixer")


def _unavailable(reason_code: str) -> ToolFailure:
    return ToolFailure(FailureClass.precondition, REASONS[reason_code], detail={"reason_code": reason_code})


def _ready_method() -> dict[str, Any]:
    """The fixed method record (M7 ``dependencies()`` + ``pdbfixer_version``) or a 412 with a closed reason."""
    try:
        openmm_method.require_process_identity()
        method = openmm_method.dependencies()
    except ToolFailure as exc:
        code = exc.detail.get("reason_code") if isinstance(exc.detail, dict) else None
        raise _unavailable(code if code in K.UNAVAILABLE_REASON_CODES else "openmm_unavailable") from exc
    try:
        pdbfixer = _pdbfixer_version()
    except PackageNotFoundError:
        pdbfixer = None
    if pdbfixer != K.PDBFIXER_VERSION:
        raise _unavailable("pdbfixer_unavailable")
    return {**method, "pdbfixer_version": pdbfixer}


def capability() -> dict[str, Any]:
    """``methods.mutation_model``: available only with the fixed OpenMM 8.6.0 force field, PDBFixer 1.12.0 and the
    process-identity adapter; otherwise the closed reason and no versions (spec 5)."""
    base = {"schema": "mutation_model_capability@1", "protocol_id": PROTOCOL, "tool_id": TOOL,
            "execution_lane": "durable_job", "result_schema": K.SCHEMA, "method_version": K.METHOD_VERSION,
            "timeout_s": {"default": K.TIMEOUT_DEFAULT_S, "max": K.TIMEOUT_MAX_S},
            "contact_cutoff_A": {"default": K.CONTACT_CUTOFF_DEFAULT_A, "min": K.CONTACT_CUTOFF_RANGE_A[0],
                                 "max": K.CONTACT_CUTOFF_RANGE_A[1]},
            "limits": {"protein_heavy_atoms": openmm_method.ATOM_CAP, "contact_rows_per_structure": K.MAX_CONTACT_ROWS,
                       "output_bytes": OUTPUT_LIMIT}}
    try:
        method = _ready_method()
    except ToolFailure as exc:
        code = exc.detail["reason_code"]
        return {**base, "available": False, "reason_code": code, "reason": REASONS[code], "versions": None}
    return {**base, "available": True, "reason_code": None, "reason": None,
            "versions": {"openmm": method["distribution_version"], "openmm_engine_build": method["engine_build"],
                         "pdbfixer": method["pdbfixer_version"]}}


def require_ready() -> dict[str, Any]:
    """The pins a job records at submission and rechecks at start: worker SHA-256, the SHA-256 of each worker
    dependency module and the fixed method record."""
    return {"worker_sha256": _sha(WORKER.read_bytes()),
            "dependency_sha256": {name: _sha(path.read_bytes()) for name, path in sorted(DEPENDENCIES.items())},
            "method": _ready_method()}


# ----------------------------------------------------------------- admission (no job, no engine, no event)
def _meta(run: Any, handle: str) -> dict[str, Any] | None:
    """Store metadata of an object of this run, or None (other run, unknown, malformed)."""
    try:
        return run.store.meta(handle)
    except (KeyError, ValueError, TypeError):
        return None


def _residues(run: Any, structure: str) -> list[dict[str, Any]]:
    return structure_residues(run.store, structure)["residues"]


def admission(run: Any, args: Any, timeout_s: Any) -> tuple[dict[str, Any], float]:
    """Checks 1--7 (spec 2) with the job timeout checked with the arguments (``argument_invalid``); every refusal is
    422 ``input_invalid`` with a closed reason before any job exists. Returns ``(admitted, timeout_s)``."""
    arguments = mi.normalize_arguments(args)
    timeout = mi.normalize_timeout(timeout_s)
    admitted = mi.admit(arguments, meta=lambda handle: _meta(run, handle), load=run.store.load,
                        residues=lambda handle: _residues(run, handle))
    return admitted, timeout


def selection(run: Any, admitted: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Unavailability (412) then the M7 preflight (422 ``openmm_preflight_failed``); ``(selected, pins)``."""
    pins = require_ready()
    arguments = admitted["arguments"]
    try:
        projection = openmm_method.preflight(run.store, admitted["structure"], seed=arguments["seed"])
    except ToolFailure as exc:
        raise mi.preflight_failure(exc) from exc
    if projection["model_number"] != admitted["model_number"]:
        raise ToolFailure(FailureClass.input_invalid, "the candidate set's model is not the preflight model",
                          detail={"reason_code": "structure_invalid"})
    key = identity(admitted["residue"])
    found = [r["residue"] for c in projection["protein"] for r in c["residues"] if identity(r["residue"]) == key]
    if len(found) != 1:
        raise ToolFailure(FailureClass.input_invalid, "the candidate position residue is not one residue of the M7 "
                          "protein projection", detail={"reason_code": "residue_mismatch"})
    residue = found[0]
    payload = {"schema": INPUT_SCHEMA, "method": pins["method"], "model_number": projection["model_number"],
               "protein": projection["protein"], "seed": arguments["seed"], "residue": residue,
               "mutant_resname": admitted["mutant_resname"], "contact_cutoff_A": arguments["contact_cutoff_A"]}
    if len(canonical_json(payload)) > STAGED_LIMIT:
        raise ToolFailure(FailureClass.resource_exceeded, "staged mutation-model input exceeds its limit",
                          detail={"reason_code": "resource_exceeded", "limit": "staged_input_bytes",
                                  "max_bytes": STAGED_LIMIT})
    candidate = admitted["candidate"]
    selected = {"schema": SELECTION_SCHEMA, "arguments": arguments,
                "candidate": {"candidate_set": arguments["candidate_set"], "candidate_index": candidate["index"],
                              "position_index": candidate["position_index"], "from": candidate["from"],
                              "to": candidate["to"], "residue": residue, "mutant_resname": admitted["mutant_resname"]},
                "structure": {"handle": admitted["structure"], "model_number": projection["model_number"],
                              "structure_kind": K.STRUCTURE_KIND},
                "excluded_components": mi.excluded_components(projection["excluded"]),
                "payload": payload}
    return selected, pins


def input_handles(selected: dict[str, Any]) -> list[str]:
    return [selected["candidate"]["candidate_set"], selected["structure"]["handle"]]


def call_key(normalized: dict[str, Any], pins: dict[str, Any]) -> str:
    """Spec 2: normalized arguments + worker module SHA-256 + its dependency SHA-256 map + the fixed method record
    (the timeout is not in it)."""
    return idempotency_key(PROTOCOL, IMPLEMENTATION, {"arguments": normalized, "worker_sha256": pins["worker_sha256"],
                                                      "dependency_sha256": pins["dependency_sha256"],
                                                      "method": pins["method"]})


# ----------------------------------------------------------------- staging and worker errors
def stage(job: dict[str, Any]) -> bytes:
    """``structure.json``: the payload recorded at submission (its method is the job's pinned method)."""
    payload = job["selected"]["payload"]
    if payload["method"] != job["method"]["method"] or payload["schema"] != INPUT_SCHEMA:
        raise ValueError("staged payload differs from the job pins")
    return canonical_json(payload)


def worker_error(attempt_dir: Path) -> dict[str, Any]:
    """Accept only the worker's ``{reason_code, message, detail}`` envelope with a closed reason; else fatal."""
    fatal = {"error": "fatal", "message": "worker exit or invalid mutation-model error envelope"}
    try:
        descriptor = os.open(attempt_dir / "error.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_ERROR_BYTES:
                return fatal
            raw = stream.read(MAX_ERROR_BYTES + 1)
        data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if (type(data) is not dict or set(data) != {"reason_code", "message", "detail"} or
                data["reason_code"] not in K.FAILURE_REASON_CODES or type(data["message"]) is not str or
                not 0 < len(data["message"]) <= 300 or type(data["detail"]) is not dict or
                data["detail"].get("reason_code") != data["reason_code"]):
            return fatal
        return {"error": FAILURE_CLASSES[data["reason_code"]], "reason_code": data["reason_code"],
                "message": data["message"], "detail": data["detail"]}
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return fatal


# ----------------------------------------------------------------- publication
def _read_result(attempt_dir: Path, descriptor: Any) -> dict[str, Any]:
    if (type(descriptor) is not dict or set(descriptor) != {"output_sha256", "output_bytes"} or
            type(descriptor["output_bytes"]) is not int or not 0 < descriptor["output_bytes"] <= OUTPUT_LIMIT or
            type(descriptor["output_sha256"]) is not str or len(descriptor["output_sha256"]) != 64):
        raise ValueError("invalid mutation-model output descriptor")
    fd = os.open(attempt_dir / "result.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != descriptor["output_bytes"]:
            raise ValueError("mutation-model output size mismatch")
        raw = stream.read(descriptor["output_bytes"] + 1)
    if len(raw) != descriptor["output_bytes"] or _sha(raw) != descriptor["output_sha256"]:
        raise ValueError("mutation-model output hash mismatch")
    data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if type(data) is not dict:
        raise ValueError("mutation-model output is not an object")
    return data


def _structure_handle(run: Any, raw: bytes) -> str:
    """The handle ``ObjectStore.put`` gives these mmCIF bytes (computed before anything is stored)."""
    sha = object_sha(STRUCTURE_OBJECT_KIND, STRUCTURE_OBJECT_SCHEMA, raw)
    return f"{HANDLE_PREFIX}{run.run_id}/{STRUCTURE_OBJECT_KIND}/{sha}"


def _projection_heavy(protein: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [(identity(r["residue"]), a["atom_name"], a["element"]) for c in protein for r in c["residues"]
            for a in r["atoms"]]


def model_content(run: Any, job: dict[str, Any], data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bytes]]:
    """The ``mutation_model@1`` content and the two mmCIF byte strings for one worker output, fully validated
    (raises ``ValueError``/``ModelInvalid`` on any mismatch; stores nothing)."""
    selected = job["selected"]
    payload = selected["payload"]
    arguments = selected["arguments"]
    if (set(data) != OUTPUT_KEYS or data["schema"] != OUTPUT_SCHEMA or data["method"] != payload["method"] or
            data["method"] != job["method"]["method"]):
        raise ValueError("worker output keys, schema or method mismatch")
    structures, cifs_text = data["structures"], data["structure_cifs"]
    if (type(structures) is not dict or set(structures) != set(K.STRUCTURE_SIDES) or type(cifs_text) is not dict or
            set(cifs_text) != set(K.STRUCTURE_SIDES)):
        raise ValueError("worker output structure sides mismatch")
    cifs: dict[str, bytes] = {}
    entries: dict[str, dict[str, Any]] = {}
    for side in K.STRUCTURE_SIDES:
        text, entry = cifs_text[side], structures[side]
        if type(text) is not str or type(entry) is not dict or "structure_object" in entry:
            raise ValueError("worker structure entry shape")
        raw = text.encode()
        if _sha(raw) != entry.get("structure_sha256") or len(raw) > MAX_STRUCTURE_BYTES:
            raise ValueError("mmCIF SHA-256 mismatch")
        atoms = entry.get("atom_mapping")
        _cif(text, atoms, [atom["coordinates_A"] for atom in atoms], payload["model_number"])
        cifs[side] = raw
        entries[side] = {"structure_object": _structure_handle(run, raw), **entry}
    # The wild-type heavy atoms are the staged M7 projection, in order; the mutant's added atoms are exactly the
    # mutated residue's heavy atoms that the input residue lacked.
    wild_heavy = [(identity(a["residue"]), a["atom_name"], a["element"])
                  for a in entries["wild_type_reference"]["atom_mapping"] if a["element"] not in K.HYDROGEN_ELEMENTS]
    if wild_heavy != _projection_heavy(payload["protein"]):
        raise ValueError("wild-type heavy atoms differ from the staged projection")
    residue = payload["residue"]
    source_names = {a["atom_name"] for c in payload["protein"] for r in c["residues"]
                    if identity(r["residue"]) == identity(residue) for a in r["atoms"]}
    renamed = identity({**residue, "resname": payload["mutant_resname"]})
    mutant_names = {a["atom_name"] for a in entries["mutant"]["atom_mapping"]
                    if identity(a["residue"]) == renamed and a["element"] not in K.HYDROGEN_ELEMENTS}
    if {a["atom_name"] for a in entries["mutant"]["added_heavy_atoms"]} != mutant_names - source_names:
        raise ValueError("added heavy atoms differ from the mutated residue")
    content = {"schema": K.SCHEMA, "method_version": K.METHOD_VERSION, "candidate": selected["candidate"],
               "structure": selected["structure"],
               "parameters": {key: arguments[key] for key in ("seed", "contact_cutoff_A", "selection_policy",
                                                              "hydrogen_policy")},
               "method": data["method"], "excluded_components": selected["excluded_components"],
               "structures": entries, "comparison": data["comparison"],
               "protonation_differences": data["protonation_differences"], "limitations": data["limitations"]}
    mm.validated_model(content)
    return content, cifs


def publish(run: Any, job: dict[str, Any], attempt_id: str, attempt_dir: Path, descriptor: Any) -> list[str]:
    """Validate this attempt's worker output, then store the two mmCIF objects and one ``mutation_model@1`` object
    (or raise, storing nothing). ``MutationJobFailure`` for the size bound."""
    content, cifs = model_content(run, job, _read_result(attempt_dir, descriptor))
    size = len(canonical_json(content))
    if size > MAX_MODEL_BYTES:
        raise MutationJobFailure("resource_exceeded", "resource_exceeded",
                                 f"mutation model exceeds {MAX_MODEL_BYTES} bytes; never truncated",
                                 {"limit": "model_bytes", "bytes": size, "max_bytes": MAX_MODEL_BYTES})
    for side in K.STRUCTURE_SIDES:
        stored = run.store.put(STRUCTURE_OBJECT_KIND, STRUCTURE_OBJECT_SCHEMA, cifs[side], fmt="cif",
                               produced_by=attempt_id)
        if stored.handle != content["structures"][side]["structure_object"]:
            raise ValueError("structure object handle mismatch")
    candidate = content["candidate"]
    out = run.store.put(K.KIND, K.SCHEMA, content, produced_by=attempt_id,
                        summary={"candidate_set": candidate["candidate_set"],
                                 "candidate_index": candidate["candidate_index"], "from": candidate["from"],
                                 "to": candidate["to"], "structure": content["structure"]["handle"],
                                 "seed": content["parameters"]["seed"]})
    return [out.handle]


# ----------------------------------------------------------------- validated reads (never run anything)
def producer(run: Any, handle: str) -> dict[str, Any]:
    """The earliest completed ``openmm_mutation_model_v1`` publication of ``handle`` (else an evidence error)."""
    events = list(run.events.read())
    jobs = {event["job"]["job_id"]: event["job"] for event in events if event["type"] == "job_submitted"}
    created = [event for event in events if event["type"] == "object_created" and event.get("handle") == handle]
    for terminal in events:
        if (terminal["type"] != "job_terminal" or terminal.get("status") != "done" or
                terminal.get("output_handles") != [handle]):
            continue
        job = jobs.get(terminal.get("job_id"))
        attempt = terminal.get("attempt_id")
        if job is None or job.get("protocol_id") != PROTOCOL or job.get("tool_id") != TOOL:
            continue
        candidates = [event for event in events if event["type"] == "job_result_candidate" and
                      event.get("job_id") == job["job_id"] and event.get("attempt_id") == attempt and
                      event.get("output_handles") == [handle] and event["seq"] < terminal["seq"]]
        cleaned = [event for event in events if event["type"] == "job_cleanup_verified" and
                   event.get("attempt_id") == attempt and event.get("group_empty") is True]
        reserved = [event for event in events if event["type"] == "budget_reserved" and
                    event.get("attempt_id") == attempt and event.get("tool") == TOOL]
        if (len(candidates) == 1 and len(cleaned) == 1 and len(reserved) == 1 and created and
                reserved[0]["seq"] < cleaned[0]["seq"] < candidates[0]["seq"] and
                created[0]["seq"] < candidates[0]["seq"]):
            return {"job_id": job["job_id"], "attempt_id": attempt, "job": job,
                    "created_seq": created[0]["seq"], "published_seq": terminal["seq"]}
    raise MutationEvidenceError("object has no completed openmm_mutation_model_v1 publication")


def _check_relations(run: Any, content: dict[str, Any], job: dict[str, Any]) -> None:
    selected = job["selected"]
    arguments = selected["arguments"]
    _require(selected.get("schema") == SELECTION_SCHEMA, "selection schema")
    _require(content["candidate"] == selected["candidate"] and content["structure"] == selected["structure"] and
             content["parameters"] == {key: arguments[key] for key in ("seed", "contact_cutoff_A",
                                                                        "selection_policy", "hydrogen_policy")} and
             content["method"] == job["method"]["method"] == selected["payload"]["method"] and
             content["excluded_components"] == selected["excluded_components"], "content differs from its job")
    candidate = content["candidate"]
    set_meta = _meta(run, candidate["candidate_set"])
    structure_meta = _meta(run, content["structure"]["handle"])
    _require(set_meta is not None and (set_meta["kind"], set_meta["schema"]) == mi.CANDIDATE_SET_TYPE and
             structure_meta is not None and (structure_meta["kind"], structure_meta["schema"]) == mi.PREPARED_TYPE,
             "candidate set / structure handle kinds")
    stored_set = validated_set(run.store.load(candidate["candidate_set"]))
    row = [item for item in stored_set["candidates"] if item["index"] == candidate["candidate_index"]]
    _require(len(row) == 1 and row[0]["position_index"] == candidate["position_index"] and
             row[0]["from"] == candidate["from"] and row[0]["to"] == candidate["to"] and
             stored_set["structure"]["handle"] == content["structure"]["handle"], "candidate set relation")
    for side in K.STRUCTURE_SIDES:
        entry = content["structures"][side]
        meta = _meta(run, entry["structure_object"])
        _require(meta is not None and (meta["kind"], meta["schema"], meta["fmt"]) ==
                 (STRUCTURE_OBJECT_KIND, STRUCTURE_OBJECT_SCHEMA, "cif"), f"{side} structure object kind")
        _require(_sha(run.store.load_bounded_bytes(entry["structure_object"], MAX_STRUCTURE_BYTES)) ==
                 entry["structure_sha256"], f"{side} structure bytes")


def validated_result(run: Any, handle: Any) -> dict[str, Any]:
    """The stored ``mutation_model@1`` of this run, re-validated on every read (no engine, no event)."""
    try:
        _require(type(handle) is str, "handle must be a string")
        meta = _meta(run, handle)
        _require(meta is not None and (meta["kind"], meta["schema"], meta["fmt"]) == (K.KIND, K.SCHEMA, "json"),
                 "expected a mutation_model@1 of this run")
        content = run.store.load_bounded_json(handle, MAX_MODEL_BYTES)
        mm.validated_model(content)
        _check_relations(run, content, producer(run, handle)["job"])
        return content
    except MutationEvidenceError:
        raise
    except (mm.ModelInvalid, KeyError, TypeError, ValueError, IndexError, AttributeError, OSError) as exc:
        raise MutationEvidenceError("mutation model evidence is invalid") from exc


def structure_bytes(run: Any, handle: Any, side: Any) -> bytes:
    """The stored mmCIF bytes of one side of a validated model (hash-checked against the model)."""
    if side not in K.STRUCTURE_SIDES:
        raise MutationEvidenceError("side must be wild_type_reference or mutant")
    content = validated_result(run, handle)
    entry = content["structures"][side]
    try:
        raw = run.store.load_bounded_bytes(entry["structure_object"], MAX_STRUCTURE_BYTES)
    except (KeyError, ValueError, OSError) as exc:
        raise MutationEvidenceError("structure object does not load") from exc
    _require(_sha(raw) == entry["structure_sha256"], "structure bytes")
    return raw
