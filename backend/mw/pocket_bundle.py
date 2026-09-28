"""M12 fpocket job lane on the server side: capability, call key, staging, publication and validated reads.

The server never runs fpocket. The capability handshake runs ``pocket_worker.py --handshake`` which
only hashes the installed executable and install record; only a successful handshake is cached.
Publication happens after verified group cleanup: the server re-projects the same-run source,
re-reads the native output files from the private attempt directory under the pinned reader's caps,
requires the worker's classification to agree byte for byte, and stores every object only after the
per-run native-evidence retention cap has been checked (nothing is stored partially).
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import os
import platform
import stat
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from . import pocket_output
from .core.errors import FailureClass, ToolFailure
from .core.events import idempotency_key
from .core.handles import canonical_json
from .jobs import pocket_worker
from .pocket_input import preflight as input_preflight
from .pocket_input import project

ROOT = Path(__file__).resolve().parents[2]
# Administrator configuration only; a request can never name an executable, path, env or argv.
ENGINE_ROOT = ROOT / ".deps/fpocket"
WORKER = Path(pocket_worker.__file__).resolve()
PARAMETERS = ROOT / "config/pockets/fpocket-4.2.3-parameters.json"
PROTOCOL = "fpocket_detect_v1"
TOOL = "detect_pockets"
IMPLEMENTATION = "fpocket_detect_v1@1"
SOURCE_KINDS = {"prepared_structure": "prepared_structure@1", "chemical_structure": "chemical_structure@1",
                "openmm_minimized_structure": "openmm_minimized_structure@1"}
ARGV = ["fpocket", *pocket_worker.ARGV_TAIL]
PARAMETERS_ARGV = ["<fpocket>", *pocket_worker.ARGV_TAIL]
TIMEOUT_S = 120
# Tunable per-run cap on the stored bytes of all pocket_native_output objects (events hold them whole).
MAX_RETAINED_NATIVE_BYTES = 64 * 1024 * 1024
MAX_SET_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_NATIVE_BYTES = 64 * 1024 * 1024
MAX_RESULT_DESCRIPTOR_BYTES = 64 * 1024
LIMITS = {"heavy_atoms": 10_000, "residues": 3_000, "chains": 62, "input_bytes": 10 * 1024 * 1024,
          "timeout_s": TIMEOUT_S, "rss_bytes": 2 * 1024 * 1024 * 1024,
          "output_bytes": pocket_output.MAX_OUTPUT_BYTES, "output_files": pocket_output.MAX_OUTPUT_FILES,
          "stdout_bytes": pocket_output.MAX_STREAM_BYTES, "stderr_bytes": pocket_output.MAX_STREAM_BYTES,
          "pockets": pocket_output.MAX_POCKETS, "alpha_spheres": pocket_output.MAX_SPHERES,
          "termination_grace_s": 2.0}
DETERMINISM = {"seed_control": "unsupported", "fresh_execution_deterministic": False,
               "note": ("fpocket 4.2.3 seeds its random generator from the clock; a completed call with the same "
                        "call key returns its stored result, and a fresh execution can differ (Monte Carlo volume).")}
REASONS = {
    "not_installed": "fpocket 4.2.3 작업 환경이 설치되어 있지 않습니다(설정 명령 scripts/setup_fpocket.py).",
    "unreviewed_build": "설치된 fpocket 실행 파일 또는 설치 기록이 검토된 4.2.3 hb88c64c_2 빌드 해시와 다릅니다.",
    "handshake_failed": "fpocket 작업 프로세스 확인(handshake)에 실패했습니다.",
    "unsupported_platform": "fpocket 4.2.3 hb88c64c_2 빌드는 macOS arm64(14.5 이상)에서만 사용할 수 있습니다.",
}
SET_KEYS = frozenset({"schema", "source_handle", "source_kind", "model_number", "preparation_handle",
                      "detector_input_handle", "native_output_handle", "method", "total_count", "null_result",
                      "completeness", "limitations", "units", "pockets", "raw_file_hashes"})
METHOD_KEYS = frozenset({"engine", "release", "build", "package_sha256", "executable_sha256", "observed_banner",
                         "recipe_provenance", "argv", "effective_parameters", "parser_version", "seed_control",
                         "fresh_execution_deterministic", "transport_precision_A"})
POCKET_KEYS = frozenset({"rank", "descriptors", "native_fields", "spheres", "lining_atoms", "lining_residues",
                         "display_center"})
RESULT_KEYS = frozenset({"schema", "job_id", "attempt_id", "worker_sha256", "argv", "stage", "outcome", "failure",
                         "exit_code", "stdout_bytes", "stderr_bytes", "stdout_sha256", "stderr_sha256",
                         "engine_environment_keys", "result_sha256", "total_count"})
ENGINE_ENVIRONMENT_KEYS = ["LANG", "LC_ALL", "PATH", "TMPDIR"]

_HANDSHAKE_CACHE: dict[tuple, dict[str, Any]] = {}
_HANDSHAKE_LOCK = threading.Lock()


class PocketJobFailure(Exception):
    """A typed attempt failure after reservation (charged); never publishes anything."""

    def __init__(self, failure_class: str, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.reason_code = reason_code
        self.message = message

    def to_error(self) -> dict[str, Any]:
        return {"error": self.failure_class, "message": self.message, "reason_code": self.reason_code}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ----------------------------------------------------------------- capability
def _platform_supported() -> bool:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return False
    try:
        parts = tuple(int(part) for part in platform.mac_ver()[0].split(".")[:2])
    except ValueError:
        return False
    return len(parts) >= 1 and (parts + (0,))[:2] >= (14, 5)


def _handshake_key(root: Path) -> tuple:
    """Everything a successful handshake is bound to; any change forces a fresh handshake."""
    executable = (root / pocket_worker.EXECUTABLE_RELPATH).resolve(strict=True)
    info = executable.stat()
    return (str(root), str(executable), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            _sha((root / pocket_worker.RECORD_NAME).read_bytes()), _sha(WORKER.read_bytes()),
            _sha(pocket_worker.LOCK_EXPLICIT.read_bytes()), _sha(pocket_worker.LOCK_HASHES.read_bytes()))


def _handshake(root: Path) -> dict[str, Any]:
    proc = subprocess.run([os.path.abspath(sys.executable), "-I", str(WORKER), "--handshake", str(root)],
                          cwd=ROOT, env={"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1"},
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=True)
    if len(proc.stdout) > 64 * 1024 or proc.stderr:
        raise ValueError("unexpected handshake output")
    data = json.loads(proc.stdout)
    if (type(data) is not dict or data.get("schema") != "pocket_worker_handshake@1" or
            data.get("status") not in {"ready", "not_installed", "unreviewed_build"} or
            data.get("worker_sha256") != _sha(WORKER.read_bytes()) or
            (data["status"] == "ready" and (data.get("executable_sha256") != pocket_worker.EXECUTABLE_SHA256 or
                                             type(data.get("observed_banner")) is not str or
                                             type(data.get("recipe_provenance")) is not dict))):
        raise ValueError("invalid handshake")
    return data


def _dependency(root: Path) -> dict[str, Any]:
    if not _platform_supported():
        return {"status": "unsupported_platform", "reason_code": "unsupported_platform"}
    if not (root / pocket_worker.EXECUTABLE_RELPATH).is_file() or not (root / pocket_worker.RECORD_NAME).is_file():
        return {"status": "not_installed", "reason_code": "engine_not_installed"}
    with _HANDSHAKE_LOCK:
        try:
            key = _handshake_key(root)
        except OSError:
            return {"status": "not_installed", "reason_code": "engine_not_installed"}
        cached = _HANDSHAKE_CACHE.get(key)
        if cached is not None:
            return copy.deepcopy(cached)
        try:
            data = _handshake(root)
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, TypeError, KeyError):
            return {"status": "handshake_failed", "reason_code": "handshake_failed"}
        if data["status"] == "ready":  # only a verified handshake is reused
            _HANDSHAKE_CACHE.clear()
            _HANDSHAKE_CACHE[key] = copy.deepcopy(data)
        return data


def capability() -> dict[str, Any]:
    data = _dependency(ENGINE_ROOT)
    status = data["status"]
    ready = status == "ready"
    return {"schema": "pocket_capability@1", "status": status, "available": ready,
            "reason_code": None if ready else data["reason_code"], "reason": REASONS.get(status),
            "protocol_id": PROTOCOL, "tool_id": TOOL, "execution_lane": "durable_job",
            "engine": pocket_worker.ENGINE, "release": pocket_worker.RELEASE, "build": pocket_worker.BUILD,
            "package_sha256": pocket_worker.PACKAGE_SHA256, "executable_sha256": pocket_worker.EXECUTABLE_SHA256,
            "observed_banner": data.get("observed_banner") if ready else None,
            "recipe_provenance": data.get("recipe_provenance") if ready else None,
            "parser_version": pocket_output.PARSER_VERSION, "argv": list(ARGV), "limits": dict(LIMITS),
            "determinism": dict(DETERMINISM), "limitations": list(pocket_output.LIMITATIONS)}


def worker_sha256() -> str:
    return _sha(WORKER.read_bytes())


def require_ready() -> dict[str, Any]:
    value = capability()
    if not value["available"]:
        raise ToolFailure(FailureClass.precondition, value["reason"] or "fpocket unavailable",
                          detail={"reason_code": value["status"]})
    return value


# ----------------------------------------------------------------- sources and preflight
def _check_source(run: Any, handle: Any) -> None:
    """Admit a same-run source only through its reviewed producer; raw structures need preparation."""
    if type(handle) is not str:
        raise ToolFailure(FailureClass.input_invalid, "structure must be a handle string",
                          detail={"reason_code": "unknown_source"})
    try:
        meta = run.store.meta(handle)
    except KeyError as exc:
        raise ToolFailure(FailureClass.input_invalid, "unknown same-run source",
                          detail={"reason_code": "unknown_source"}) from exc
    if meta["kind"] == "structure":
        raise ToolFailure(FailureClass.precondition, "prepare the structure first (explicit model and altloc policy)",
                          detail={"reason_code": "raw_structure_requires_preparation"})
    if SOURCE_KINDS.get(meta["kind"]) != meta["schema"]:
        raise ToolFailure(FailureClass.input_invalid, "unsupported pocket input source kind",
                          detail={"reason_code": "unsupported_source_kind", "source_kind": meta["kind"]})
    try:
        if meta["kind"] == "chemical_structure":
            from .jobs.queue import require_completed_chemical_handle

            require_completed_chemical_handle(run, handle)
        elif meta["kind"] == "openmm_minimized_structure":
            from .openmm_reports import validated_minimized_structure

            validated_minimized_structure(run, handle)
    except ToolFailure as exc:
        raise ToolFailure(FailureClass.input_invalid, "source has no completed reviewed producer",
                          detail={"reason_code": "source_producer_invalid"}) from exc
    except (KeyError, ValueError, TypeError) as exc:
        raise ToolFailure(FailureClass.input_invalid, "source has no completed reviewed producer",
                          detail={"reason_code": "source_producer_invalid"}) from exc


def retention(run: Any) -> dict[str, int]:
    used = 0
    seen: set[str] = set()
    for event in run.events.read():
        if event["type"] == "object_created" and event.get("kind") == "pocket_native_output" and \
                event["handle"] not in seen:
            seen.add(event["handle"])
            used += run.store.meta(event["handle"])["size"]
    return {"limit_bytes": MAX_RETAINED_NATIVE_BYTES, "used_bytes": used,
            "remaining_bytes": max(0, MAX_RETAINED_NATIVE_BYTES - used)}


def preflight(run: Any, handle: Any, chains: list[str] | None) -> dict[str, Any]:
    """Read-only summary for the UI; runs no tool, job or engine."""
    summary = input_preflight(run.store, handle, chains)
    try:
        _check_source(run, handle)
    except ToolFailure as failure:
        summary.update(ready=False, reject={"failure_class": failure.cls.value,
                                            "reason_code": failure.detail.get("reason_code"),
                                            "message": failure.message, "stage": "source", "detail": {}})
    cap = capability()
    status = cap["status"] if not cap["available"] else ("ready" if summary["ready"] else "unsupported_input")
    return {**summary, "status": status, "available": status == "ready", "capability": cap,
            "retention": retention(run), "budget": run.budget_snapshot(), "method": {
                "engine": cap["engine"], "release": cap["release"], "build": cap["build"], "argv": list(ARGV),
                "parser_version": pocket_output.PARSER_VERSION}, "limits": dict(LIMITS),
            "determinism": dict(DETERMINISM), "limitations": list(pocket_output.LIMITATIONS),
            "timeout_s": TIMEOUT_S, "starts_job": False}


# ----------------------------------------------------------------- submission and staging
def submission(run: Any, args: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Validate ``{structure, chains}`` and project; returns (selected, normalized parameters, method pins)."""
    if type(args) is not dict or not set(args) <= {"structure", "chains"} or "structure" not in args:
        raise ToolFailure(FailureClass.input_invalid, "pocket job arguments are exactly {structure, chains}",
                          detail={"reason_code": "invalid_job_arguments"})
    chains = args.get("chains")
    if chains is not None and (type(chains) is not list or any(type(chain) is not str for chain in chains)):
        raise ToolFailure(FailureClass.input_invalid, "chains must be a list of chain_auth strings",
                          detail={"reason_code": "invalid_chain_selection"})
    _check_source(run, args["structure"])
    projected = project(run.store, args["structure"], chains or None)
    manifest = projected["manifest"]
    selected = {"schema": "pocket_job_selection@1", "source_handle": manifest["source_handle"],
                "source_kind": manifest["source_kind"], "model_number": manifest["model_number"],
                "preparation_handle": manifest["preparation_handle"],
                "selected_chains": projected["selected_chains"], "transport_pdb_sha256": projected["pdb_sha256"],
                "transport_pdb_bytes": manifest["transport_pdb_bytes"], "counts": manifest["counts"],
                "excluded_counts": manifest["excluded_counts"]}
    normalized = {"structure": args["structure"], "chains": projected["selected_chains"]}
    pins = {"engine": pocket_worker.ENGINE, "release": pocket_worker.RELEASE, "build": pocket_worker.BUILD,
            "package_sha256": pocket_worker.PACKAGE_SHA256, "executable_sha256": pocket_worker.EXECUTABLE_SHA256,
            "argv": list(ARGV), "parser_version": pocket_output.PARSER_VERSION}
    return selected, normalized, pins


def call_key(selected: dict[str, Any], pins: dict[str, Any]) -> str:
    """Protocol, implementation, source/preparation handles, resolved sorted chains, transport hash, build, argv."""
    return idempotency_key(PROTOCOL, IMPLEMENTATION, {
        "source_handle": selected["source_handle"], "preparation_handle": selected["preparation_handle"],
        "model_number": selected["model_number"], "selected_chains": selected["selected_chains"],
        "transport_pdb_sha256": selected["transport_pdb_sha256"], "method": pins})


def _reproject(run: Any, job: dict[str, Any]) -> dict[str, Any]:
    projected = project(run.store, job["parameters"]["structure"], job["parameters"]["chains"])
    if (projected["pdb_sha256"] != job["selected"]["transport_pdb_sha256"] or
            projected["selected_chains"] != job["selected"]["selected_chains"]):
        raise ValueError("pocket transport projection changed since submission")
    return projected


def stage(run: Any, job: dict[str, Any], attempt_id: str) -> bytes:
    projected = _reproject(run, job)
    return canonical_json({"schema": "pocket_worker_input@1", "job_id": job["job_id"], "attempt_id": attempt_id,
                           "executable": str(ENGINE_ROOT / pocket_worker.EXECUTABLE_RELPATH),
                           "executable_sha256": pocket_worker.EXECUTABLE_SHA256,
                           "argv_tail": list(pocket_worker.ARGV_TAIL),
                           "pdb": projected["pdb_bytes"].decode("ascii"), "pdb_sha256": projected["pdb_sha256"],
                           "atoms": projected["atoms"]})


# ----------------------------------------------------------------- publication
def _read_bounded(path: Path, limit: int) -> tuple[bytes, int]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("not a regular file")
        chunks, remaining = [], limit + 1
        while remaining > 0 and (chunk := os.read(fd, min(remaining, 1 << 20))):
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks), info.st_size
    finally:
        os.close(fd)


def _parameters_document() -> dict[str, Any]:
    document = json.loads(PARAMETERS.read_bytes())
    if (type(document) is not dict or document.get("argv") != PARAMETERS_ARGV or
            document.get("release") != pocket_worker.RELEASE or document.get("build") != pocket_worker.BUILD):
        raise ValueError("effective parameter record does not match the fixed argv/build")
    return document


def _worker_result(job: dict[str, Any], attempt_id: str, attempt_dir: Path,
                   descriptor: dict[str, Any]) -> dict[str, Any]:
    if (type(descriptor) is not dict or set(descriptor) != {"output_sha256", "output_bytes"} or
            type(descriptor["output_bytes"]) is not int or
            not 0 < descriptor["output_bytes"] <= MAX_RESULT_DESCRIPTOR_BYTES):
        raise ValueError("invalid pocket worker descriptor")
    raw, size = _read_bounded(attempt_dir / "result.json", MAX_RESULT_DESCRIPTOR_BYTES)
    if size != descriptor["output_bytes"] or len(raw) != size or _sha(raw) != descriptor["output_sha256"]:
        raise ValueError("pocket worker result changed")
    data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if (type(data) is not dict or canonical_json(data) != raw or set(data) != RESULT_KEYS or
            data["schema"] != "pocket_worker_result@1" or data["job_id"] != job["job_id"] or
            data["attempt_id"] != attempt_id or data["argv"] != ARGV or
            data["worker_sha256"] != job["worker_sha256"] or data["stage"] not in {"preflight", "engine"} or
            data["outcome"] not in {"success", "scientific_null", "failure"}):
        raise ValueError("invalid pocket worker result")
    return data


def publish(run: Any, job: dict[str, Any], attempt_id: str, attempt_dir: Path,
            descriptor: dict[str, Any]) -> list[str]:
    worker = _worker_result(job, attempt_id, attempt_dir, descriptor)
    if worker["stage"] == "preflight":
        failure = worker["failure"]
        if (worker["outcome"] != "failure" or type(failure) is not dict or
                failure.get("reason_code") not in pocket_worker.PREFLIGHT_REASONS):
            raise ValueError("invalid pocket worker preflight failure")
        raise PocketJobFailure("fatal", failure["reason_code"], "fpocket worker refused before engine launch")
    if worker["engine_environment_keys"] != ENGINE_ENVIRONMENT_KEYS or type(worker["exit_code"]) is not int:
        raise ValueError("invalid pocket worker engine record")
    streams = {}
    for name, key in ((pocket_worker.ENGINE_STDOUT, "stdout"), (pocket_worker.ENGINE_STDERR, "stderr")):
        raw, size = _read_bounded(attempt_dir / name, pocket_output.MAX_STREAM_BYTES)
        if size > pocket_output.MAX_STREAM_BYTES or len(raw) > pocket_output.MAX_STREAM_BYTES:
            raise PocketJobFailure("resource_exceeded", f"{key}_limit", f"fpocket {key} exceeds 1 MiB")
        if len(raw) != size or _sha(raw) != worker[f"{key}_sha256"]:
            raise ValueError("fpocket stream differs from the worker record")
        streams[key] = raw
    job_root = attempt_dir / pocket_worker.JOB_ROOT
    info = os.lstat(job_root)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("unsafe fpocket job root")
    projected = _reproject(run, job)
    exit_code = worker["exit_code"]
    try:
        result, native = pocket_output.classify(job_root, projected["atoms"], exit_code=exit_code,
                                                stdout=streams["stdout"], stderr=streams["stderr"],
                                                killed=exit_code < 0)
    except pocket_output.PocketOutputFailure as failure:
        if worker["outcome"] != "failure" or worker["failure"] != {"failure_class": failure.failure_class,
                                                                   "reason_code": failure.reason_code}:
            raise ValueError("worker and server classification disagree") from failure
        raise PocketJobFailure(failure.failure_class, failure.reason_code, failure.message) from failure
    if (worker["outcome"] != result["classification"] or worker["failure"] is not None or
            worker["result_sha256"] != _sha(canonical_json(result)) or worker["total_count"] != result["total_count"]):
        raise ValueError("worker and server classification disagree")
    cap = capability()
    if (not cap["available"] or cap["executable_sha256"] != job["method"]["executable_sha256"] or
            cap["package_sha256"] != job["method"]["package_sha256"]):
        raise PocketJobFailure("fatal", "engine_changed", "pinned fpocket build changed during the attempt")
    manifest = projected["manifest"]
    evidence = pocket_output.native_output_evidence(native, streams["stdout"], streams["stderr"])
    native_content = {"schema": "pocket_native_output@1", "argv": list(ARGV), "exit_code": exit_code,
                      "transport_pdb_sha256": projected["pdb_sha256"], **evidence}
    native_bytes = len(canonical_json(native_content))
    method = {"engine": pocket_worker.ENGINE, "release": pocket_worker.RELEASE, "build": pocket_worker.BUILD,
              "package_sha256": pocket_worker.PACKAGE_SHA256, "executable_sha256": pocket_worker.EXECUTABLE_SHA256,
              "observed_banner": cap["observed_banner"], "recipe_provenance": cap["recipe_provenance"],
              "argv": list(ARGV), "effective_parameters": _parameters_document(),
              "parser_version": pocket_output.PARSER_VERSION, "seed_control": "unsupported",
              "fresh_execution_deterministic": False,
              "transport_precision_A": manifest["quantization"]["transport_precision_A"]}
    pockets = [{key: pocket[key] for key in POCKET_KEYS} for pocket in result["pockets"]]
    # Retention is decided before anything is stored: exceeding it stores nothing (charged failure).
    if retention(run)["used_bytes"] + native_bytes > MAX_RETAINED_NATIVE_BYTES:
        raise PocketJobFailure("resource_exceeded", "native_output_retention_limit",
                               "run native fpocket output retention limit exceeded")
    pdb = run.store.put("pocket_transport_pdb", "pocket_transport_pdb@1", projected["pdb_bytes"], fmt="pdb",
                        produced_by=attempt_id, summary={"sha256": projected["pdb_sha256"]})
    detector_input = run.store.put("pocket_detector_input", "pocket_detector_input@1",
                                   {**manifest, "transport_pdb_handle": pdb.handle}, produced_by=attempt_id,
                                   summary={"source_handle": manifest["source_handle"],
                                            "selected_chains": manifest["selected_chains"],
                                            "heavy_atoms": manifest["counts"]["heavy_atoms"]})
    native_output = run.store.put("pocket_native_output", "pocket_native_output@1",
                                  {**native_content, "detector_input_handle": detector_input.handle},
                                  produced_by=attempt_id, summary={"retained_bytes": evidence["retained_bytes"]})
    content = {"schema": "pocket_set@1", "source_handle": manifest["source_handle"],
               "source_kind": manifest["source_kind"], "model_number": manifest["model_number"],
               "preparation_handle": manifest["preparation_handle"], "detector_input_handle": detector_input.handle,
               "native_output_handle": native_output.handle, "method": method,
               "total_count": result["total_count"], "null_result": result["null_result"],
               "completeness": result["completeness"], "limitations": result["limitations"],
               "units": result["units"], "pockets": pockets, "raw_file_hashes": result["raw_file_hashes"]}
    out = run.store.put("pocket_set", "pocket_set@1", content, produced_by=attempt_id,
                        null_result=result["null_result"],
                        summary={"source_handle": manifest["source_handle"], "source_kind": manifest["source_kind"],
                                 "model_number": manifest["model_number"],
                                 "selected_chains": manifest["selected_chains"],
                                 "total_count": result["total_count"], "null_result": result["null_result"],
                                 "job_id": job["job_id"]})
    return [out.handle]


# ----------------------------------------------------------------- validated reads (never run anything)
class PocketEvidenceError(ValueError):
    """A stored pocket_set does not validate against its immutable input and native evidence."""


def _typed(run: Any, handle: Any, kind: str, limit: int) -> Any:
    if type(handle) is not str:
        raise PocketEvidenceError("handle must be a string")
    try:
        meta = run.store.meta(handle)
    except KeyError as exc:
        raise PocketEvidenceError("unknown same-run handle") from exc
    if (meta["kind"], meta["schema"], meta["fmt"]) != (kind, f"{kind}@1", "json"):
        raise PocketEvidenceError(f"expected {kind}")
    return run.store.load_bounded_json(handle, limit)


def producer(run: Any, handle: str) -> dict[str, Any]:
    """The single completed fixed-protocol publication of this pocket_set (else evidence error)."""
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
        # An identical-byte retry may reuse an object first created by an interrupted attempt; the
        # successful candidate/terminal of this attempt, not the first creator, is the authority.
        if (len(candidates) == 1 and len(cleaned) == 1 and created and
                cleaned[0]["seq"] < candidates[0]["seq"] and created[0]["seq"] < candidates[0]["seq"]):
            return {"job_id": job["job_id"], "attempt_id": attempt, "created_seq": created[0]["seq"],
                    "published_seq": terminal["seq"], "job": job}
    raise PocketEvidenceError("pocket_set has no completed fpocket_detect_v1 publication")


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def validated_pocket_set(run: Any, handle: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return (pocket_set, detector input manifest, producer) after full structural validation."""
    try:
        content = _typed(run, handle, "pocket_set", MAX_SET_BYTES)
        source = producer(run, handle)
        manifest = _typed(run, content["detector_input_handle"], "pocket_detector_input", MAX_MANIFEST_BYTES)
        native = _typed(run, content["native_output_handle"], "pocket_native_output", MAX_NATIVE_BYTES)
        _validate(run, content, manifest, native, source)
    except PocketEvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise PocketEvidenceError("pocket_set evidence is invalid") from exc
    return content, manifest, source


def _validate(run: Any, content: dict, manifest: dict, native: dict, source: dict) -> None:
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise PocketEvidenceError(message)

    require(type(content) is dict and set(content) == SET_KEYS and content["schema"] == "pocket_set@1",
            "pocket_set keys")
    selected = source["job"]["selected"]
    for key in ("source_handle", "source_kind", "model_number", "preparation_handle"):
        require(content[key] == manifest[key] == selected[key], f"pocket_set {key} differs from its input")
    require(manifest["schema"] == "pocket_detector_input@1" and
            manifest["selected_chains"] == selected["selected_chains"] and
            manifest["transport_pdb_sha256"] == selected["transport_pdb_sha256"], "detector input differs from job")
    pdb = run.store.load_bounded_bytes(manifest["transport_pdb_handle"], 16 * 1024 * 1024)
    require(run.store.meta(manifest["transport_pdb_handle"])["kind"] == "pocket_transport_pdb" and
            _sha(pdb) == manifest["transport_pdb_sha256"], "transport PDB evidence")
    method = content["method"]
    require(type(method) is dict and set(method) == METHOD_KEYS, "method keys")
    require(method["engine"] == pocket_worker.ENGINE and method["release"] == pocket_worker.RELEASE and
            method["build"] == pocket_worker.BUILD and method["package_sha256"] == pocket_worker.PACKAGE_SHA256 and
            method["executable_sha256"] == pocket_worker.EXECUTABLE_SHA256 and method["argv"] == ARGV and
            method["parser_version"] == pocket_output.PARSER_VERSION and method["seed_control"] == "unsupported" and
            method["fresh_execution_deterministic"] is False and type(method["observed_banner"]) is str and
            type(method["recipe_provenance"]) is dict and type(method["effective_parameters"]) is dict and
            method["effective_parameters"].get("argv") == PARAMETERS_ARGV and
            method["transport_precision_A"] == manifest["quantization"]["transport_precision_A"], "method pins")
    require(native["schema"] == "pocket_native_output@1" and native["detector_input_handle"] ==
            content["detector_input_handle"] and native["parser_version"] == pocket_output.PARSER_VERSION and
            native["transport_pdb_sha256"] == manifest["transport_pdb_sha256"], "native output binding")
    retained = {}
    for item in native["files"]:
        if item["retained"]:
            raw = base64.b64decode(item["content_b64"], validate=True)
            require(len(raw) == item["size"] and _sha(raw) == item["sha256"], "native file hash")
            retained[item["path"]] = item["sha256"]
    for name in ("stdout", "stderr"):
        raw = base64.b64decode(native[name]["content_b64"], validate=True)
        require(len(raw) == native[name]["size"] and _sha(raw) == native[name]["sha256"], "native stream hash")
    require(content["raw_file_hashes"] == retained, "raw file hashes differ from native evidence")
    pockets = content["pockets"]
    require(type(pockets) is list and content["total_count"] == len(pockets) and
            content["null_result"] is (not pockets) and content["completeness"] == "complete" and
            content["limitations"] == pocket_output.LIMITATIONS and content["units"] == pocket_output.UNITS,
            "pocket_set totals, limitations or units")
    atoms = manifest["atoms"]
    for index, pocket in enumerate(pockets, start=1):
        require(type(pocket) is dict and set(pocket) == POCKET_KEYS and pocket["rank"] == index, "pocket rank")
        descriptors = pocket["descriptors"]
        require(set(descriptors) == set(pocket_output.DESCRIPTOR_KEYS), "descriptor keys")
        for key, entry in descriptors.items():
            require(entry["unit"] == pocket_output.UNITS[key] and _finite(entry["value"]), f"descriptor {key}")
        require(descriptors["druggability_score"].get("detector_specific_note") ==
                pocket_output.DETECTOR_SPECIFIC_NOTE, "druggability warning")
        spheres = pocket["spheres"]
        require(type(spheres) is list and spheres and descriptors["alpha_sphere_count"]["value"] == len(spheres),
                "sphere count")
        for sphere in spheres:
            require(set(sphere) == {"x_A", "y_A", "z_A", "radius_A"} and all(_finite(v) for v in sphere.values()) and
                    pocket_output.MIN_SPHERE_RADIUS_A - 0.006 <= sphere["radius_A"] <=
                    pocket_output.MAX_SPHERE_RADIUS_A + 0.006, "sphere geometry")
        require(pocket["display_center"] == pocket_output.display_center(spheres), "display center")
        lining = pocket["lining_atoms"]
        indices = lining["transport_indices"]
        require(type(indices) is list and indices and len(set(indices)) == len(indices) and
                all(type(i) is int and 0 <= i < len(atoms) for i in indices) and
                lining["atoms"] == [atoms[i]["ref"] for i in indices] and
                type(lining["native_record_count"]) is int and lining["native_record_count"] >= len(indices),
                "lining atoms differ from the detector input")
        residues: list[dict] = []
        for ref in lining["atoms"]:
            if ref["residue"] not in residues:
                residues.append(ref["residue"])
        require(pocket["lining_residues"] == residues, "lining residues differ from lining atoms")


def list_sets(run: Any, offset: int, limit: int) -> dict[str, Any]:
    events = list(run.events.read())
    jobs = {event["job"]["job_id"]: event["job"] for event in events if event["type"] == "job_submitted"}
    created = {event["handle"]: event for event in events if event["type"] == "object_created" and
               event.get("kind") == "pocket_set"}
    rows = []
    for terminal in events:
        job = jobs.get(terminal.get("job_id")) if terminal["type"] == "job_terminal" else None
        if job is None or terminal.get("status") != "done" or job.get("protocol_id") != PROTOCOL:
            continue
        outputs = terminal.get("output_handles")
        if type(outputs) is not list or len(outputs) != 1 or outputs[0] not in created:
            continue
        summary = created[outputs[0]].get("summary", {})
        rows.append({"handle": outputs[0], "source_handle": summary.get("source_handle"),
                     "source_kind": summary.get("source_kind"), "model_number": summary.get("model_number"),
                     "selected_chains": summary.get("selected_chains"), "total_count": summary.get("total_count"),
                     "null_result": summary.get("null_result"), "job_id": job["job_id"],
                     "created_seq": created[outputs[0]]["seq"], "published_seq": terminal["seq"]})
    rows.reverse()  # newest first
    return {"schema": "pocket_set_list@1", "total": len(rows), "offset": offset, "limit": limit,
            "rows": rows[offset:offset + limit]}


def result_summary(run: Any, handle: str) -> dict[str, Any]:
    content, manifest, source = validated_pocket_set(run, handle)
    return {"schema": "pocket_set_summary@1", "handle": handle, "job_id": source["job_id"],
            **{key: content[key] for key in ("source_handle", "source_kind", "model_number", "preparation_handle",
                                             "detector_input_handle", "native_output_handle", "method",
                                             "total_count", "null_result", "completeness", "limitations", "units",
                                             "raw_file_hashes")},
            "selected_chains": manifest["selected_chains"], "excluded_counts": manifest["excluded_counts"],
            "resname_mapping": manifest["resname_mapping"], "quantization": manifest["quantization"],
            "counts": manifest["counts"],
            "pockets": [{"rank": pocket["rank"], "descriptors": pocket["descriptors"],
                         "native_fields": pocket["native_fields"],
                         "alpha_sphere_count": len(pocket["spheres"]),
                         "lining_atom_count": len(pocket["lining_atoms"]["atoms"]),
                         "lining_residue_count": len(pocket["lining_residues"]),
                         "display_center": pocket["display_center"]} for pocket in content["pockets"]]}


def geometry(run: Any, handle: str, rank: int) -> dict[str, Any] | None:
    content, _, _ = validated_pocket_set(run, handle)
    if not 1 <= rank <= len(content["pockets"]):
        return None
    pocket = content["pockets"][rank - 1]
    return {"schema": "pocket_geometry@1", "handle": handle, "rank": rank,
            "source_handle": content["source_handle"], "model_number": content["model_number"],
            "units": content["units"], "descriptors": pocket["descriptors"], "spheres": pocket["spheres"],
            "lining_atoms": pocket["lining_atoms"], "lining_residues": pocket["lining_residues"],
            "display_center": pocket["display_center"]}
