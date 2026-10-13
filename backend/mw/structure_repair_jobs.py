"""M29 ``pdbfixer_repair_v1`` job lane on the server side: capability, admission, call key, staging, worker errors and
publication with the pre-publication checks (spec .dryforge/spec.md 3.3, 3.4, 4.1, 4.2, 4.4, 4.6).

The server never imports PDBFixer (its version comes from ``importlib.metadata`` only) and imports OpenMM only through
the M7 ``openmm_method.dependencies()`` / ``preflight()`` path. PDBFixer runs only in the fixed worker
``mw/jobs/structure_repair_worker.py`` (project interpreter, as M7 and M21).

Submission order (``JobQueue.submit``), every refusal before any job, reservation or charge:
1. ``admission`` (422 ``input_invalid``, ``detail.reason_code``): ``unknown_field`` -> ``confirmation_missing``
   (``repair_policy`` is not the literal) -> ``argument_invalid`` (``structure`` not a non-empty string, or
   ``JobSubmit.timeout_s`` outside (0, 240], default 120) -> ``structure_invalid`` (not a ``prepared_structure@1`` of
   this run) -> ``already_repaired`` (its manifest has ``repair``).
2. dry-run: the plan only (as M7 and M21).
3. ``selection``: 412 ``precondition`` ``process_identity_unavailable`` -> ``openmm_unavailable`` ->
   ``pdbfixer_unavailable``; then the core analysis (gemmi + the installed template, no PDBFixer): 422
   ``input_invalid`` with ``detail.error`` = ``repair_not_possible``, ``detail.reason_code`` the first code of
   ``REFUSAL_REASONS``, ``detail.blockers`` every blocker (and ``detail.m7_reason`` for ``m7_condition_unsupported``);
   then 429 ``resource_exceeded`` (``limit: staged_input_bytes``) above 4,000,000 B of staged payload.
4. ``call_key``: normalized arguments + worker SHA-256 + the SHA-256 of each project module the worker imports or the
   published content depends on (``DEPENDENCIES``) + the fixed method record; never the timeout. One prepared
   structure has one call key (the seed is the constant ``REPAIR_SEED``), so the same input returns the same job.

Publication (``publish``), after the worker's group is verified empty: the worker output is read within its bound and
must carry the job's pinned method and the fixed engine values; the core splices the added atoms into the prepared
structure (``build_repaired``) and re-validates (``validated_repair``, checks 1, 2, 3 and 5); the M7 ``preflight``
then runs on a read-only overlay of the four pending objects (check 4; its refusal is ``repair_incomplete`` with
``detail.m7_reason``). Only then are the four objects stored and the published event appended
(``structure_repair_bundle.store``). A closed failure is ``RepairJobFailure`` (the job fails with that reason and
stores nothing; the reserved unit is not refunded); any other mismatch in the worker output raises and the queue ends
the attempt as ``fatal`` (``invalid scientific output``), again storing nothing.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from . import structure_repair as sr
from . import structure_repair_bundle as bundle
from . import structure_repair_constants as K
from .core.errors import FailureClass, ToolFailure
from .core.events import idempotency_key
from .core.handles import canonical_json
from .mutation_model_bundle import REASONS as M21_REASONS
from .structure_origin import is_repaired
from .tools import openmm_method
from .tools.structural import _res_ref

ROOT = Path(__file__).resolve().parents[2]
# Deployment-fixed path; a request can never name an interpreter, module, path, env or argv.
WORKER = ROOT / "backend/mw/jobs/structure_repair_worker.py"
# The project modules the worker imports and the core whose output is published, hashed into the call key and the
# start-time recheck like the worker itself (as M21 pins its dependencies).
DEPENDENCIES = {name: ROOT / "backend" / name for name in (
    "mw/structure_repair.py", "mw/structure_repair_constants.py", "mw/jobs/openmm_worker.py",
    "mw/tools/openmm_method.py", "mw/mutation_model_constants.py")}
PROTOCOL = K.PROTOCOL
TOOL = K.TOOL
IMPLEMENTATION = "pdbfixer_repair_v1@1"
SELECTION_SCHEMA = bundle.SELECTION_SCHEMA
INPUT_SCHEMA = "structure_repair_worker_input@1"     # = structure_repair_worker.INPUT_SCHEMA
OUTPUT_SCHEMA = "structure_repair_worker_output@1"   # = structure_repair_worker.OUTPUT_SCHEMA
OUTPUT_LIMIT = 4_000_000          # = structure_repair_worker.MAX_OUTPUT_BYTES = the guardian's read bound
MAX_ERROR_BYTES = 64 * 1024
OUTPUT_KEYS = frozenset({"schema", "method", "engine", "added_atoms", "diagnostics"})
ENGINE_KEYS = ("pdbfixer_version", "openmm_distribution_version", "forcefield_files_sha256")
# The three unavailability reasons and their sentences are M21's (same engines, same adapter).
REASONS = {code: M21_REASONS[code] for code in K.UNAVAILABLE_REASON_CODES}
# Job failure reason -> job failure class (the reason itself is the closed ``detail.reason_code``).
FAILURE_CLASSES = {"repair_incomplete": "input_invalid", "repair_modeling_failed": "input_invalid",
                   "coordinates_changed": "input_invalid", "unexpected_atoms_added": "input_invalid",
                   "repair_identity_mismatch": "input_invalid", "repair_record_mismatch": "input_invalid",
                   "resource_exceeded": "resource_exceeded", "engine_failed": "fatal"}


class RepairJobFailure(Exception):
    """A typed attempt failure after reservation (charged, never refunded); nothing is stored."""

    def __init__(self, reason_code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        if reason_code not in K.FAILURE_REASON_CODES:
            raise ValueError(f"unknown failure reason {reason_code}")
        super().__init__(message)
        self.failure_class = FAILURE_CLASSES[reason_code]
        self.reason_code = reason_code
        self.message = message
        self.detail = {**(detail or {}), "reason_code": reason_code}

    def to_error(self) -> dict[str, Any]:
        return {"error": self.failure_class, "reason_code": self.reason_code, "message": self.message,
                "detail": self.detail}


def _invalid(reason_code: str, message: str) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail={"reason_code": reason_code})


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ----------------------------------------------------------------- capability (PDBFixer by metadata only)
def _pdbfixer_version() -> str:
    return version("pdbfixer")


def _unavailable(reason_code: str) -> ToolFailure:
    return ToolFailure(FailureClass.precondition, REASONS[reason_code], detail={"reason_code": reason_code})


def _ready_method() -> dict[str, Any]:
    """The fixed method record (M7 ``dependencies()`` + ``pdbfixer_version``) or a 412 in the order
    ``process_identity_unavailable`` -> ``openmm_unavailable`` -> ``pdbfixer_unavailable``."""
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
    """``methods.structure_repair``: available only with the fixed OpenMM 8.6.0 force field, PDBFixer 1.12.0 and the
    process-identity adapter; otherwise the closed reason, its sentence and no versions (spec 4.6)."""
    base = {"schema": "structure_repair_capability@1", "protocol_id": PROTOCOL, "tool_id": TOOL,
            "execution_lane": "durable_job", "result_schema": K.SCHEMA, "method_version": K.METHOD_VERSION,
            "timeout_s": {"default": K.TIMEOUT_DEFAULT_S, "max": K.TIMEOUT_MAX_S},
            "limits": {"max_gap_residues": K.MAX_GAP_RESIDUES, "protein_heavy_atoms": K.M7_ATOM_CAP,
                       "staged_input_bytes": K.MAX_STAGED_INPUT_BYTES, "record_bytes": K.MAX_RECORD_BYTES}}
    try:
        method = _ready_method()
    except ToolFailure as exc:
        code = exc.detail["reason_code"]
        return {**base, "available": False, "reason_code": code, "reason": REASONS[code], "versions": None}
    return {**base, "available": True, "reason_code": None, "reason": None,
            "versions": {"openmm": method["distribution_version"], "openmm_engine_build": method["engine_build"],
                         "pdbfixer": method["pdbfixer_version"]}}


def require_ready() -> dict[str, Any]:
    """The pins a job records at submission and rechecks at start: worker SHA-256, the SHA-256 of each dependency
    module and the fixed method record."""
    return {"worker_sha256": _sha(WORKER.read_bytes()),
            "dependency_sha256": {name: _sha(path.read_bytes()) for name, path in sorted(DEPENDENCIES.items())},
            "method": _ready_method()}


# ----------------------------------------------------------------- admission (no job, no engine, no event)
def normalize_arguments(args: Any) -> dict[str, Any]:
    """Checks ``unknown_field`` -> ``confirmation_missing`` -> ``argument_invalid``; the call-key arguments."""
    if not isinstance(args, dict):
        raise _invalid("argument_invalid", "arguments must be an object")
    unknown = sorted(set(args) - set(K.ARG_KEYS))
    if unknown:
        raise _invalid("unknown_field", f"unknown parameters: {unknown}")
    if type(args.get("repair_policy")) is not str or args["repair_policy"] != K.REPAIR_POLICY:
        raise _invalid("confirmation_missing", f"repair_policy must be '{K.REPAIR_POLICY}' (a structure with "
                                               "modeled coordinates is made)")
    structure = args.get("structure")
    if type(structure) is not str or not structure:
        raise _invalid("argument_invalid", "structure must be a prepared_structure handle")
    return {"structure": structure, "repair_policy": K.REPAIR_POLICY}


def normalize_timeout(value: Any) -> float:
    """``JobSubmit.timeout_s`` for this protocol: default 120 s, (0, 240] s (not an argument, not in the key)."""
    if value is None:
        return float(K.TIMEOUT_DEFAULT_S)
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= K.TIMEOUT_MAX_S:
        raise _invalid("argument_invalid", f"timeout_s must be a finite number in (0, {K.TIMEOUT_MAX_S}]")
    return float(value) + 0.0


def admission(run: Any, args: Any, timeout_s: Any) -> tuple[dict[str, Any], float]:
    """Step 1 (422, in order); ``({"arguments"}, timeout_s)``."""
    arguments = normalize_arguments(args)
    timeout = normalize_timeout(timeout_s)
    structure = arguments["structure"]
    try:
        meta = run.store.meta(structure)
    except (KeyError, ValueError, TypeError):
        meta = None
    if meta is None or (meta["kind"], meta["schema"]) != (K.STRUCTURE_KIND, K.STRUCTURE_SCHEMA):
        raise _invalid("structure_invalid", "structure must be a prepared_structure@1 of this run")
    if is_repaired(run.store, structure):
        raise _invalid("already_repaired", "the structure is already a repaired structure")
    return {"arguments": arguments}, timeout


def analysis_of(run: Any, structure: str) -> tuple[sr.RepairInputs, dict[str, Any]]:
    inputs = sr.load_inputs(run.store, structure)
    return inputs, sr.analyze(inputs)


def refusal_failure(analysis: dict[str, Any]) -> ToolFailure | None:
    """The 422 ``repair_not_possible`` (class ``input_invalid``) of an unrepairable analysis, else None."""
    detail = sr.refusal(analysis)
    if detail is None:
        return None
    return ToolFailure(FailureClass.input_invalid, f"structure repair is not possible ({detail['reason_code']})",
                       detail={"error": K.REPAIR_NOT_POSSIBLE, **detail})


def payload(inputs: sr.RepairInputs, analysis: dict[str, Any], method: dict[str, Any]) -> dict[str, Any]:
    """The staged worker input: the protein polymer residues (heavy atoms, input identities), chain parts merged by
    author chain in the order the core builder merges them, and each gap in front of its ``before_residue``."""
    model = sr._read(inputs.prepared_bytes, inputs.prepared_fmt)[0]   # the core's reading, polymer rule and merge
    order, parts = sr._parts(model)
    gaps = {(gap["chain_auth"], sr._key(gap["before_residue"])): gap for gap in analysis["defects"]["gaps"]}
    chains = []
    for name in order:
        residues: list[dict[str, Any]] = []
        chain_gaps: list[dict[str, Any]] = []
        for chain, res in ((part, res) for part in parts[name] for res in part if sr._is_polymer(res)):
            ref = _res_ref(chain, res, model.num)
            gap = gaps.pop((name, sr._key(ref)), None)
            if gap is not None:
                if not residues or sr._key(residues[-1]["ref"]) != sr._key(gap["after_residue"]):
                    raise ValueError("a gap is not between two consecutive staged residues")
                chain_gaps.append({"before_index": len(residues), "residues": gap["residues"]})
            residues.append({"ref": ref, "atoms": [
                {"atom_name": atom.name, "element": atom.element.name,
                 "coordinates_A": [atom.pos.x, atom.pos.y, atom.pos.z]}
                for atom in res if atom.element.name not in K.HYDROGEN_ELEMENTS]})
        if residues:
            chains.append({"chain_auth": name, "residues": residues, "gaps": chain_gaps})
    if gaps:
        raise ValueError("a gap is not between two staged residues")
    return {"schema": INPUT_SCHEMA, "method": method, "seed": K.REPAIR_SEED, "model_number": model.num,
            "chains": chains}


def selection(run: Any, admitted: dict[str, Any],
              analysed: tuple[sr.RepairInputs, dict[str, Any]] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Steps 3-5: unavailability (412), the analysis refusal (422 ``repair_not_possible``), the staged size (429);
    ``(selected, pins)``. ``analysed`` is an analysis the caller already made of the same structure."""
    pins = require_ready()
    arguments = admitted["arguments"]
    inputs, analysis = analysed if analysed is not None else analysis_of(run, arguments["structure"])
    refused = refusal_failure(analysis)
    if refused is not None:
        raise refused
    staged = payload(inputs, analysis, pins["method"])
    size = len(canonical_json(staged))
    if size > K.MAX_STAGED_INPUT_BYTES:
        raise ToolFailure(FailureClass.resource_exceeded, "staged structure-repair input exceeds its limit",
                          detail={"reason_code": "resource_exceeded", "limit": K.STAGED_INPUT_LIMIT, "bytes": size,
                                  "max_bytes": K.MAX_STAGED_INPUT_BYTES})
    selected = {"schema": SELECTION_SCHEMA, "arguments": arguments,
                "structure": {"handle": arguments["structure"], "model_number": inputs.model_number},
                "classes": analysis["classes"], "expected_added_residues": analysis["expected_added_residues"],
                "expected_added_heavy_atoms": analysis["expected_added_heavy_atoms"], "payload": staged}
    return selected, pins


def input_handles(selected: dict[str, Any]) -> list[str]:
    return [selected["structure"]["handle"]]


def call_key(normalized: dict[str, Any], pins: dict[str, Any]) -> str:
    """Normalized arguments + worker SHA-256 + its dependency SHA-256 map + the fixed method record (spec 4.1)."""
    return idempotency_key(PROTOCOL, IMPLEMENTATION, {"arguments": normalized, "worker_sha256": pins["worker_sha256"],
                                                      "dependency_sha256": pins["dependency_sha256"],
                                                      "method": pins["method"]})


# ----------------------------------------------------------------- staging and worker errors
def stage(job: dict[str, Any]) -> bytes:
    """``structure.json``: the payload recorded at submission (its method is the job's pinned method)."""
    staged = job["selected"]["payload"]
    if staged["method"] != job["method"]["method"] or staged["schema"] != INPUT_SCHEMA:
        raise ValueError("staged payload differs from the job pins")
    return canonical_json(staged)


def worker_error(attempt_dir: Path) -> dict[str, Any]:
    """Accept only the worker's ``{reason_code, message, detail}`` envelope with a closed reason; else fatal."""
    fatal = {"error": "fatal", "message": "worker exit or invalid structure-repair error envelope"}
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
        raise ValueError("invalid structure-repair output descriptor")
    fd = os.open(attempt_dir / "result.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != descriptor["output_bytes"]:
            raise ValueError("structure-repair output size mismatch")
        raw = stream.read(descriptor["output_bytes"] + 1)
    if len(raw) != descriptor["output_bytes"] or _sha(raw) != descriptor["output_sha256"]:
        raise ValueError("structure-repair output hash mismatch")
    data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if type(data) is not dict:
        raise ValueError("structure-repair output is not an object")
    return data


def _closed(exc: ToolFailure) -> RepairJobFailure:
    """A core refusal with a closed job failure reason; anything else is not a closed failure (-> fatal)."""
    code = exc.detail.get("reason_code") if isinstance(exc.detail, dict) else None
    if code not in K.FAILURE_REASON_CODES:
        raise ValueError(f"unexpected structure-repair refusal: {exc.message}") from exc
    return RepairJobFailure(code, exc.message, {key: value for key, value in exc.detail.items()
                                                if key != "reason_code"})


def m7_check(run: Any, objects: bundle.Pending) -> None:
    """Check 4: the M7 preflight on the read-only overlay (nothing is written); its refusal is
    ``repair_incomplete`` with ``detail.m7_reason`` (M7 unavailability mid-job is ``engine_failed``)."""
    try:
        openmm_method.preflight(bundle.Overlay(run.store, objects), objects.structure, seed=run.seed)
    except ToolFailure as exc:
        code = exc.detail.get("reason_code") if isinstance(exc.detail, dict) else None
        if exc.cls is FailureClass.precondition and code in ("openmm_unavailable", "process_identity_unavailable"):
            raise RepairJobFailure("engine_failed", f"the M7 preflight could not run: {exc.message}",
                                   {"m7_reason": code}) from exc
        detail = {"m7_reason": sr.m7_reason(exc)}
        if isinstance(exc.detail.get("residue"), dict):
            detail["residue"] = exc.detail["residue"]
        raise RepairJobFailure("repair_incomplete", "the repaired structure does not pass the M7 OpenMM preflight",
                               detail) from exc


def prepared_objects(run: Any, job: dict[str, Any], data: dict[str, Any]) -> bundle.Pending:
    """The four validated pending objects of one worker output (checks 1-5); raises ``RepairJobFailure`` with a
    closed reason or ``ValueError`` for an output that does not belong to this job. Stores nothing."""
    selected = job["selected"]
    staged = selected["payload"]
    fixed = sr.fixed_method()
    if (set(data) != OUTPUT_KEYS or data["schema"] != OUTPUT_SCHEMA or data["method"] != staged["method"] or
            data["method"] != job["method"]["method"] or
            data["engine"] != {key: fixed[key] for key in ENGINE_KEYS}):
        raise ValueError("worker output keys, schema, method or engine mismatch")
    try:
        inputs = sr.load_inputs(run.store, selected["structure"]["handle"])
        raw, record = sr.build_repaired(inputs, data["added_atoms"])
        sr.validated_repair(inputs, raw, json.loads(canonical_json(record)))
        objects = bundle.pending(run, inputs, raw, record)
    except ToolFailure as exc:
        raise _closed(exc) from exc
    m7_check(run, objects)
    return objects


def publish(run: Any, job: dict[str, Any], attempt_id: str, attempt_dir: Path, descriptor: Any) -> list[str]:
    """Validate this attempt's worker output, then store the four objects and the published event (or raise,
    storing nothing). Output handles: ``[record, repaired prepared_structure]``."""
    objects = prepared_objects(run, job, _read_result(attempt_dir, descriptor))
    return bundle.store(run, objects, job["job_id"], attempt_id)
