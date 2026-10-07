"""Loopback workspace API. HTTP imports only run-scoped uploaded bytes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from contextlib import ExitStack
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from starlette.concurrency import run_in_threadpool

from .. import (
    analysis_executions,
    analysis_plans,
    docking_batch_jobs,
    docking_batch_reads,
    docking_bundle,
    docking_reads,
    jev_constants,
    jev_loop_constants,
    jev_loop_store,
    jev_loops,
    jev_projection,
    jev_sends,
    ligand_bundle,
    ligand_ga_jobs,
    ligand_ga_reads,
    ligand_reads,
    mutation_model_bundle,
    mutation_model_reads,
    mutation_reads,
    numbering_reads,
    sequence_ga_jobs,
    sequence_ga_reads,
)
from .. import site_annotation as site_annotations
from ..chemical_bundle import atom_catalog as chemical_atom_catalog
from ..chemical_bundle import validated_graph as validated_chemical_graph
from ..chemical_bundle import validated_result as validated_chemical_result
from ..chemical_bundle import validated_source as validated_chemical_source
from ..chemical_inputs import import_raw as import_chemical_raw
from ..chemical_inputs import inspect as inspect_chemical_import
from ..chemical_inputs import preview as preview_chemical
from ..chemical_inputs import receptor_atom_page
from ..chemical_reports import build_chemical_report, saved_chemical_report
from ..comparison_reports import build_comparison_report, saved_comparison_report, validated_comparison_result
from ..core.errors import FailureClass, ToolFailure
from ..core.handles import RUN_ID_RE, canonical_json
from ..docking_batch_reports import build_docking_batch_report, saved_docking_batch_report
from ..docking_reports import build_docking_report, saved_docking_report
from ..egress import science as egress_science
from ..egress.gate import EgressGate
from ..jev_reports import build_jev_report, saved_jev_report
from ..jobs.queue import CHEMICAL_DERIVED_KINDS, JobQueue, chemical_capability, require_completed_chemical_handle
from ..ligand_ga_constants import PROTOCOL as GA_PROTOCOL
from ..ligand_ga_reports import build_ligand_ga_report, saved_ligand_ga_report
from ..ligand_reports import build_ligand_report, saved_ligand_report
from ..method_reports import build_method_report, saved_method_report, validated_sasa
from ..mutation_model_constants import PROTOCOL as MUTATION_MODEL_PROTOCOL
from ..mutation_model_reports import build_mutation_model_report, saved_mutation_model_report
from ..mutation_reports import build_mutation_report, saved_mutation_report
from ..numbering_reports import build_numbering_report, saved_numbering_report
from ..openmm_reports import build_openmm_report, saved_openmm_report, validated_minimized_structure, validated_openmm
from ..pocket_bundle import PocketEvidenceError
from ..pocket_bundle import capability as pocket_capability
from ..pocket_bundle import geometry as pocket_geometry
from ..pocket_bundle import list_sets as list_pocket_sets
from ..pocket_bundle import preflight as pocket_preflight
from ..pocket_bundle import result_summary as pocket_result_summary
from ..pocket_reports import build_pocket_report, saved_pocket_report
from ..reports import EvidenceError, build_inspection_report, saved_report
from ..runtime.guards import LoopStop
from ..runtime.orchestrator import ApprovalRequired, Run, RunCancelled
from ..saved_scenes import (
    figure_detail,
    figure_download,
    list_figures,
    list_scenes,
    parse_figure_save,
    parse_scene_save,
    save_figure,
    save_scene,
    scene_detail,
)
from ..sequence_ga_constants import PROTOCOL as SEQUENCE_GA_PROTOCOL
from ..sequence_ga_reports import build_sequence_ga_report, saved_sequence_ga_report
from ..site_annotation_reports import build_site_annotation_report, saved_site_annotation_report
from ..tools.comparison import atom_rows
from ..tools.energetic import protocol_capabilities
from ..tools.openmm_method import capability as openmm_capability
from ..tools.openmm_method import preflight as openmm_preflight
from ..tools.structural import structure_bytes, structure_residues, validate_upload
from ..viewer_intents import (
    ACTIVE_INTENTS,
    ViewerError,
    acknowledge,
    cancel_intent,
    compile_answers,
    create_session,
    effective_online,
    finish_intent,
    intent_live,
    intent_public,
    list_intents,
    local_answers,
    online_status,
    projected_state,
    projection_preview,
    request_intent,
    session_public,
    set_online,
    update_scene,
)
from ..viewer_intents import QUESTION_VERSION as VIEWER_QUESTION_VERSION
from ..workflows import InspectionRequest, inspect_complex
from ..workspace import build_registry, new_run

RUNS_DIR = Path(os.environ.get("MW_RUNS_DIR", "runs"))
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_RE = re.compile(r"upload://([A-Za-z0-9_-]+)/([0-9a-f]{64})\.(pdb|cif|mmcif)\Z")
SUPPORTED_TOOLS = {"load_structure", "prepare_structure", "compute_interactions", "compute_interface_sasa",
                   "measure_distance", "align_structures", "compile_state", "map_residue_numbering",
                   "annotate_reference_sites", "generate_mutation_candidates", "build_jev_projection",
                   "build_jev_loop_projection"}
SCENE_BODY_LIMIT = 64 * 1024
FIGURE_BODY_LIMIT = (8 * 1024 * 1024 * 4 // 3) + 64 * 1024
CHEMICAL_IMPORT_LIMIT = 10 * 1024 * 1024
CHEMICAL_REQUEST_LIMIT = 512 * 1024
CHEMICAL_SOURCE_READ_LIMIT = 32 * 1024 * 1024
CHEMICAL_MANIFEST_READ_LIMIT = 8 * 1024 * 1024
ANALYSIS_REQUEST_LIMIT = 64 * 1024
ANALYSIS_PLAN_REQUEST_LIMIT = 1024 * 1024  # plan creation carries full CA-pair maps / chemistry mappings

# Host header allowlist (DNS-rebinding guard). Only loopback names, optional port, case-insensitive.
HOST_REJECT_STATUS = 400
HOST_REJECT_MESSAGE = "Host header not allowed"
_ALLOWED_HOST_RE = re.compile(r"(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]{1,5})?", re.IGNORECASE)


def host_allowed(headers: list[tuple[bytes, bytes]]) -> bool:
    hosts = [value for name, value in headers if name.lower() == b"host"]
    if len(hosts) != 1:
        return False
    try:
        host = hosts[0].decode("ascii")
    except UnicodeDecodeError:
        return False
    return _ALLOWED_HOST_RE.fullmatch(host) is not None


class HostAllowlistMiddleware:
    """Reject any HTTP request whose Host is not a loopback name, before routing or CORS."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and not host_allowed(scope.get("headers") or []):
            await JSONResponse({"detail": HOST_REJECT_MESSAGE}, status_code=HOST_REJECT_STATUS)(scope, receive, send)
            return
        await self.app(scope, receive, send)


app = FastAPI(title="ProtView local API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["*"], allow_headers=["*"])
app.add_middleware(HostAllowlistMiddleware)  # added last = outermost
REGISTRY = build_registry()
RUNS: dict[str, Run] = {}
VIEWER_GATE = EgressGate()
# M24: the science sends' own gate (not VIEWER_GATE); only POST /runs/{rid}/jev/sends uses it. Tests and the offscreen
# fixture server replace it with a fixture-transport gate.
SCIENCE_GATE = EgressGate()


class NewRun(BaseModel):
    goal: str = ""
    context: list[str] = Field(default_factory=list)
    dry_run: bool = False
    egress: Literal["local_only"] = "local_only"


class Command(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    decided_by: Literal["human", "rule"] = "human"
    execution_mode: Literal["human"] = "human"


class JobSubmit(BaseModel):
    protocol_id: str
    args: dict[str, Any] = Field(default_factory=dict)
    # 15000 s only for qvina_ga_dock_v1 and sequence_ga_dock_v1 (M23) and 7800 s for qvina_batch_dock_v1;
    # JobQueue.submit keeps every other protocol's own bound (<= 900 s) and refuses a longer timeout there
    # ("invalid job timeout", 422).
    timeout_s: float = Field(default=60, gt=0, le=15000, allow_inf_nan=False)
    model_config = {"extra": "forbid"}


class ReportRequest(BaseModel):
    interaction_handle: str
    prepared_handle: str | None = None
    model_config = {"extra": "forbid"}


class MethodReportRequest(BaseModel):
    result_handle: str
    filters: dict[str, Any] | None = None  # ligand_candidates only (M17 filter spec, applied to stored rows)
    model_config = {"extra": "forbid"}


class ViewerSessionRequest(BaseModel):
    client_instance_id: str
    scene_generation: int
    structure_handle: str
    representation: Literal["cartoon", "ball_and_stick", "surface"] = "cartoon"
    scope_chain_auth: str | None = None
    scope_target: dict[str, Any] | None = None
    selected_target: dict[str, Any] | None = None
    model_config = {"extra": "forbid"}


class ViewerSceneUpdate(BaseModel):
    representation: Literal["cartoon", "ball_and_stick", "surface"]
    selected_alias: str | None
    action_revision: int
    model_config = {"extra": "forbid"}


class ViewerOnlineRequest(BaseModel):
    enabled: bool
    model_config = {"extra": "forbid"}


class ViewerIntentRequest(BaseModel):
    client_instance_id: str
    viewer_session_id: str
    scene_generation: int
    request_id: str
    prompt: str
    model_config = {"extra": "forbid"}


class ViewerAckRequest(BaseModel):
    command_id: str
    status: Literal["applied", "no_change", "failed"]
    reason_code: str | None = None
    client_instance_id: str
    viewer_session_id: str
    scene_generation: int
    action_revision: int
    model_config = {"extra": "forbid"}


class ViewerCancelRequest(BaseModel):
    client_instance_id: str
    viewer_session_id: str
    scene_generation: int
    model_config = {"extra": "forbid"}


def _viewer_error(error: ViewerError) -> HTTPException:
    return HTTPException(error.status, detail={"error": error.code, "message": error.message})


def _run_path(rid: str) -> Path:
    if not RUN_ID_RE.fullmatch(rid):
        raise HTTPException(400, detail={"error": "input_invalid", "message": "invalid run identifier"})
    root = RUNS_DIR.resolve()
    path = RUNS_DIR / rid
    if path.is_symlink() or path.resolve().parent != root:
        raise HTTPException(400, detail={"error": "input_invalid", "message": "invalid run path"})
    return path


def _started(path: Path, rid: str) -> dict[str, Any]:
    events = path / "events.jsonl"
    if not events.is_file() or events.is_symlink():
        raise HTTPException(404, detail={"error": "not_found", "message": "run not found"})
    try:
        with events.open(encoding="utf-8") as stream:
            first = json.loads(stream.readline())
    except (OSError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid run event log"}) from exc
    if first.get("type") != "run_started" or first.get("run_id") != rid:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "run identity mismatch"})
    return first


def _run(rid: str) -> Run:
    path = _run_path(rid)
    started = _started(path, rid)
    if rid not in RUNS or RUNS[rid].run_dir.resolve() != path.resolve():
        try:
            reopened = new_run(RUNS_DIR, run_id=rid, registry=REGISTRY,
                               dry_run=started["dry_run"], seed=started["seed"],
                               egress_config=started.get("egress", {"mode": "local_only"}))
            if any(event["type"] == "job_submitted" for event in reopened.events.read()):
                try:
                    JobQueue(reopened).reconcile_run()
                except ToolFailure as exc:
                    if not exc.detail.get("busy"):
                        raise
            RUNS[rid] = reopened
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(409, detail={"error": "run_corrupt", "message": "cannot reopen run"}) from exc
    return RUNS[rid]


def _summary(run: Run) -> dict[str, Any]:
    events = list(run.events.read())
    goal = next((event for event in events if event["type"] == "goal"), {})
    return {"run_id": run.run_id, "goal": goal.get("text", ""), "context": goal.get("context", []),
            "dry_run": run.dry_run, "egress": run.egress_config["mode"],
            "last_seq": events[-1]["seq"] if events else 0}


def _tool_error(error: ToolFailure) -> JSONResponse:
    status = {FailureClass.input_invalid: 422, FailureClass.precondition: 412,
              FailureClass.resource_exceeded: 429, FailureClass.transient: 503,
              FailureClass.fatal: 503}[error.cls]
    return JSONResponse(status_code=status, content={"ok": False, **error.to_dict()})


async def _bounded_chemical_body(request: Request, limit: int) -> bytes:
    length = request.headers.get("content-length")
    if length is not None and (not length.isdecimal() or int(length) > limit):
        raise HTTPException(413, detail={"error": "resource_exceeded", "message": "chemical request too large"})
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, detail={"error": "resource_exceeded", "message": "chemical request too large"})
        chunks.append(chunk)
    return b"".join(chunks)


def _chemical_json(raw: bytes) -> dict[str, Any]:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate chemical JSON key")
            value[key] = item
        return value

    try:
        body = json.loads(raw, object_pairs_hook=unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if type(body) is not dict:
            raise ValueError("expected JSON object")
        return body
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(422, detail={"error": "input_invalid", "message": "invalid chemical JSON"}) from exc


def _public_job(job: dict[str, Any], run: Run | None = None) -> dict[str, Any]:
    """Keep private launch nonce, owner token and process identities off HTTP."""
    intent = job.get("dispatch_intent") or {}
    result = {key: job.get(key) for key in ("job_id", "run_id", "root_call_id", "call_key",
                                         "protocol_id", "tool_id", "status", "created",
                                         "finished", "timeout_s", "attempt_id", "attempt_ordinal",
                                         "blocked_reason", "cancel_requested", "cleanup_status",
                                         "failure", "input_handles", "output_handles",
                                         "preparation_handle", "preparation_attempt_id")} | {"started": intent.get("ts"),
                                                                  "remaining_wall_s_at_dispatch":
                                                                      intent.get("remaining_wall_s")}
    if job.get("protocol_id") == "prolif_prepare_v1" and job.get("status") == "done":
        result["artifacts"] = dict(zip(("preparation_manifest", "chemical_structure", "chemical_graph"),
                                       job["output_handles"], strict=True))
    elif job.get("protocol_id") == "prolif_detect_v1" and job.get("status") == "done":
        result["artifacts"] = {"chemical_interaction_set": job["output_handles"][0]}
    elif job.get("protocol_id") == "fpocket_detect_v1" and job.get("status") == "done":
        result["artifacts"] = {"pocket_set": job["output_handles"][0]}
    elif job.get("protocol_id") == "rdkit_inspect_v1" and job.get("status") == "done":
        result["artifacts"] = {"ligand_inspection": job["output_handles"][0]}
    elif job.get("protocol_id") == "rdkit_enumerate_v1" and job.get("status") == "done":
        result["artifacts"] = {"ligand_candidate_set": job["output_handles"][0]}
    elif job.get("protocol_id") == "qvina_dock_v1" and job.get("status") == "done":
        result["artifacts"] = {"docking_result": job["output_handles"][0]}
    elif job.get("protocol_id") == "qvina_batch_dock_v1" and job.get("status") == "done":
        result["artifacts"] = {"docking_batch_result": job["output_handles"][0]}
    elif job.get("protocol_id") == GA_PROTOCOL and job.get("status") == "done":
        result["artifacts"] = {"ligand_ga_result": job["output_handles"][0]}
    elif job.get("protocol_id") == SEQUENCE_GA_PROTOCOL and job.get("status") == "done":
        result["artifacts"] = {"sequence_ga_result": job["output_handles"][0]}
    elif job.get("protocol_id") == "openmm_mutation_model_v1" and job.get("status") == "done":
        result["artifacts"] = {"mutation_model": job["output_handles"][0]}
    else:
        result["artifacts"] = {}
    if job.get("protocol_id") == "qvina_batch_dock_v1" and run is not None:
        # Progress = readable rows/*.status.json of the attempt; the summary handle once published (any end state).
        result["batch"] = docking_batch_jobs.progress(run, job)
    if job.get("protocol_id") == GA_PROTOCOL and run is not None:
        # Progress = staged individual/generation file counts; the summary handle once published (any end state).
        result["ga"] = ligand_ga_jobs.progress(run, job)
    if job.get("protocol_id") == SEQUENCE_GA_PROTOCOL and run is not None:
        # M23: staged reference/individual/generation file counts; the summary handle once published (any end state).
        result["sequence_ga"] = sequence_ga_jobs.progress(run, job)
    return result


def _upload_dir_fd(run: Run, *, create: bool) -> int:
    """Open the run's upload directory without following its nested symlinks."""
    _run_path(run.run_id)
    run_fd = -1
    try:
        run_fd = os.open(run.run_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        if create:
            try:
                os.mkdir("uploads", mode=0o700, dir_fd=run_fd)
            except FileExistsError:
                pass
        return os.open("uploads", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                       dir_fd=run_fd)
    except OSError as exc:
        raise HTTPException(422, detail={"error": "input_invalid",
                                         "message": "unsafe or unavailable upload directory"}) from exc
    finally:
        if run_fd >= 0:
            os.close(run_fd)


def _read_upload(directory_fd: int, name: str) -> bytes:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory_fd)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise HTTPException(422, detail={"error": "input_invalid",
                                                 "message": "upload is not a regular file"})
            return stream.read(MAX_UPLOAD_BYTES + 1)
    except OSError as exc:
        raise HTTPException(422, detail={"error": "input_invalid",
                                         "message": "unsafe or unavailable upload file"}) from exc


def _verified_upload(run: Run, token: Any) -> tuple[bytes, str]:
    match = UPLOAD_RE.fullmatch(token) if isinstance(token, str) else None
    if match is None or match.group(1) != run.run_id:
        raise HTTPException(422, detail={"error": "input_invalid", "message": "source must be a run upload_id"})
    try:
        directory_fd = _upload_dir_fd(run, create=False)
        try:
            raw = _read_upload(directory_fd, f"{match.group(2)}.{match.group(3)}")
        finally:
            os.close(directory_fd)
    except HTTPException as exc:
        raise HTTPException(422, detail={"error": "input_invalid", "message": "unknown or unsafe upload_id"}) from exc
    if hashlib.sha256(raw).hexdigest() != match.group(2):
        raise HTTPException(422, detail={"error": "input_invalid", "message": "unknown or corrupt upload_id"})
    return raw, match.group(3)


def _object(run: Run, handle: str) -> dict[str, Any]:
    try:
        meta = run.store.meta(handle)
    except KeyError as exc:
        raise HTTPException(404, detail={"error": "not_found", "message": "unknown run handle"}) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, detail={"error": "input_invalid", "message": "invalid run handle"}) from exc
    return {key: meta[key] for key in ("handle", "kind", "schema", "fmt", "size", "produced_by",
                                        "summary", "null_result")}


def _completed_chemical(run: Run, handle: str) -> None:
    try:
        require_completed_chemical_handle(run, handle)
    except (KeyError, ValueError, TypeError) as exc:
        raise ToolFailure(FailureClass.input_invalid, "unknown or corrupt chemical object") from exc


@app.post("/runs/{rid}/chemical/imports", status_code=201)
async def chemical_import(rid: str, request: Request,
                          kind: Literal["receptor", "ligand_sdf", "receptor_bonds", "building_blocks_sdf",
                                        "building_blocks_smiles"],
                          filename: str) -> Any:
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/octet-stream":
        raise HTTPException(415, detail={"error": "input_invalid", "message": "expected octet-stream import"})
    raw = await _bounded_chemical_body(request, CHEMICAL_IMPORT_LIMIT)
    run = _run(rid)
    try:
        def write() -> dict[str, Any]:
            with run._owner(), run._transition():
                run.store.rebuild_from_events()
                return import_chemical_raw(run.store, kind, filename, raw)

        return await run_in_threadpool(write)
    except ToolFailure as exc:
        return _tool_error(exc)
    except (KeyError, ValueError, TypeError):
        return _tool_error(ToolFailure(FailureClass.input_invalid, "invalid chemical import"))


@app.get("/runs/{rid}/chemical/imports/inspect")
def chemical_import_inspect(rid: str, handle: str) -> Any:
    try:
        return inspect_chemical_import(_run(rid).store, handle)
    except ToolFailure as exc:
        return _tool_error(exc)
    except (KeyError, ValueError, TypeError):
        return _tool_error(ToolFailure(FailureClass.input_invalid, "unknown or corrupt chemical import"))


@app.get("/runs/{rid}/chemical/imports/atoms")
def chemical_import_atoms(rid: str, handle: str, model_number: int = Query(..., ge=1),
                          offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)) -> Any:
    try:
        return receptor_atom_page(_run(rid).store, handle, model_number, offset, limit)
    except ToolFailure as exc:
        return _tool_error(exc)
    except (KeyError, ValueError, TypeError):
        return _tool_error(ToolFailure(FailureClass.input_invalid, "unknown or corrupt chemical import"))


@app.post("/runs/{rid}/chemical/preview")
async def chemical_preview(rid: str, request: Request) -> Any:
    body = _chemical_json(await _bounded_chemical_body(request, CHEMICAL_REQUEST_LIMIT))
    try:
        return await run_in_threadpool(lambda: preview_chemical(_run(rid).store, body))
    except ToolFailure as exc:
        return _tool_error(exc)
    except (KeyError, ValueError, TypeError):
        return _tool_error(ToolFailure(FailureClass.input_invalid, "invalid chemical preview request"))


@app.get("/runs/{rid}/chemical/prerequisites")
def chemical_prerequisites(rid: str, mode: Literal["create_new", "attach_existing"]) -> dict[str, Any]:
    run = _run(rid)
    imports = [event for event in run.events.read() if event["type"] == "object_created" and
               event.get("kind") == "chemical_raw_input"]
    count = {kind: 0 for kind in ("receptor", "ligand_sdf", "receptor_bonds")}
    for event in imports:
        input_kind = event.get("summary", {}).get("input_kind")
        if input_kind in count:
            count[input_kind] += 1
    return {"schema": "chemical_prerequisites@1", "mode": mode,
            "capability": chemical_capability(), "import_counts": count,
            "requires": (["receptor", "ligand_sdf", "connectivity", "acknowledgement"] if mode == "create_new"
                         else ["prepared_complex", "ligand_sdf", "connectivity", "mapping", "acknowledgement"]),
            "starts_job": False}


@app.get("/runs/{rid}/chemical/structures/view")
def chemical_structure_view(rid: str, handle: str) -> Any:
    run = _run(rid)
    try:
        _completed_chemical(run, handle)
        source = validated_chemical_source(run.store, handle)
        return {key: source[key] for key in ("schema", "handle", "format", "text", "model_number",
                                              "viewer_source_sha256", "manifest_handle", "manifest_sha256")} | {
                                                  "schema": "chemical_structure_view@1", "kind": "chemical_structure"}
    except ToolFailure as exc:
        return _tool_error(exc)
    except (KeyError, ValueError, TypeError):
        return _tool_error(ToolFailure(FailureClass.input_invalid, "invalid chemical source"))


@app.get("/runs/{rid}/chemical/preparation-manifests")
def chemical_preparation_manifest(rid: str, source_handle: str) -> Any:
    """Read the exact saved preparation decisions bound to one same-run chemical source."""
    run = _run(rid)
    try:
        _completed_chemical(run, source_handle)
        source_meta = run.store.meta(source_handle)
        if ((source_meta["kind"], source_meta["schema"], source_meta["fmt"]) !=
                ("chemical_structure", "chemical_structure@1", "json") or
                source_meta["size"] > CHEMICAL_SOURCE_READ_LIMIT):
            raise ToolFailure(FailureClass.input_invalid, "invalid or oversized chemical source")
        source_payload = run.store.load_bounded_json(source_handle, CHEMICAL_SOURCE_READ_LIMIT)
        manifest_handle = source_payload["manifest_handle"]
        _completed_chemical(run, manifest_handle)
        manifest_meta = run.store.meta(manifest_handle)
        if ((manifest_meta["kind"], manifest_meta["schema"], manifest_meta["fmt"]) !=
                ("chemical_preparation_manifest", "chemical_preparation_manifest@1", "json") or
                manifest_meta["size"] > CHEMICAL_MANIFEST_READ_LIMIT):
            raise ToolFailure(FailureClass.input_invalid, "invalid or oversized chemical preparation manifest")
        source = validated_chemical_source(run.store, source_handle)
        manifest = run.store.load_bounded_json(manifest_handle, CHEMICAL_MANIFEST_READ_LIMIT)
        if (source["manifest_handle"] != manifest_handle or
                source["manifest_sha256"] != hashlib.sha256(canonical_json(manifest)).hexdigest()):
            raise ToolFailure(FailureClass.input_invalid, "chemical source/manifest hash mismatch")
        return {"meta": _object(run, manifest_handle), "manifest": manifest}
    except ToolFailure as exc:
        return _tool_error(exc)
    except (KeyError, ValueError, TypeError):
        return _tool_error(ToolFailure(FailureClass.input_invalid,
                                       "invalid or corrupt chemical source/manifest"))


@app.get("/runs/{rid}/chemical/structures/atoms")
def chemical_structure_atoms(rid: str, handle: str, offset: int = Query(0, ge=0),
                             limit: int = Query(100, ge=1, le=1000)) -> Any:
    try:
        run = _run(rid)
        _completed_chemical(run, handle)
        return chemical_atom_catalog(run.store, handle, offset, limit)
    except ToolFailure as exc:
        return _tool_error(exc)
    except (KeyError, ValueError, TypeError):
        return _tool_error(ToolFailure(FailureClass.input_invalid, "invalid chemical source"))


@app.get("/runs/{rid}/chemical/graphs")
def chemical_graph(rid: str, handle: str) -> Any:
    run = _run(rid)
    try:
        _completed_chemical(run, handle)
        return {"meta": _object(run, handle), "graph": validated_chemical_graph(run.store, handle)}
    except ToolFailure as exc:
        return _tool_error(exc)
    except (KeyError, ValueError, TypeError):
        return _tool_error(ToolFailure(FailureClass.input_invalid, "invalid chemical graph"))


@app.get("/runs/{rid}/chemical/results")
def chemical_result(rid: str, handle: str) -> Any:
    run = _run(rid)
    try:
        _completed_chemical(run, handle)
        return {"meta": _object(run, handle), "result": validated_chemical_result(run.store, handle)}
    except ToolFailure as exc:
        return _tool_error(exc)
    except (KeyError, ValueError, TypeError):
        return _tool_error(ToolFailure(FailureClass.input_invalid, "invalid chemical result"))


@app.get("/runs/{rid}/chemical/results/rows")
def chemical_result_rows(rid: str, handle: str, offset: int = Query(0, ge=0),
                         limit: int = Query(50, ge=1, le=100),
                         category: Literal["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"] | None = None) -> Any:
    try:
        run = _run(rid)
        _completed_chemical(run, handle)
        result = validated_chemical_result(run.store, handle)
        rows = [row for row in result["rows"] if category is None or row["category"] == category]
        return {"schema": "chemical_interaction_page@1", "handle": handle, "total": len(rows),
                "offset": offset, "limit": limit, "rows": rows[offset:offset + limit]}
    except ToolFailure as exc:
        return _tool_error(exc)
    except (KeyError, ValueError, TypeError):
        return _tool_error(ToolFailure(FailureClass.input_invalid, "invalid chemical result"))


@app.get("/capabilities")
def capabilities() -> dict[str, Any]:
    matrix = protocol_capabilities()
    try:
        from ..tools.sasa import engine_capability
        sasa = engine_capability()
    except (AttributeError, ImportError, OSError, PackageNotFoundError, RuntimeError, ToolFailure, ValueError) as exc:
        sasa = {"available": False, "reason_code": "engine_missing_or_invalid", "explanation": str(exc)}
    methods = {"interface_sasa": sasa, "openmm_protein_minimize": openmm_capability(),
               "chemical_interactions": chemical_capability(), "pocket_detection": pocket_capability()}
    methods["analysis_workflows"] = analysis_plans.capability(methods)
    methods["residue_numbering"] = numbering_reads.capability()
    # M16: reads only the run's own objects (no reference folder, no network), so it is always available.
    methods["reference_site_annotation"] = {"available": True, "reason_code": None, "reason": None}
    # M20: reads only the run's own stored objects (no engine, reference folder or network): always available.
    methods["mutation_candidates"] = {"available": True, "reason_code": None, "reason": None}
    # M17: pinned environment + RDKit version + PAINS A/B/C, checked by the worker handshake (no RDKit here).
    methods["ligand_candidates"] = ligand_bundle.capability()
    # M18: both locked environments, qvina2 hash = install record = pin, worker handshake versions (no RDKit/Meeko
    # import and no qvina run here).
    methods["ligand_docking"] = docking_bundle.capability()
    # M19: ligand_docking + the batch worker and constants (own worker handshake, same environment and pins).
    methods["ligand_docking_batch"] = docking_batch_jobs.capability(methods["ligand_docking"])
    # M22: ligand_docking + the GA worker and constants (own worker handshake, same environment and pins).
    methods["ligand_ga_design"] = ligand_ga_jobs.capability(methods["ligand_docking"])
    # M21: fixed OpenMM 8.6.0 (M7 dependencies()) + PDBFixer 1.12.0 (metadata only) + process-identity adapter.
    methods["mutation_model"] = mutation_model_bundle.capability()
    # M23: mutation_model + ligand_docking + the sequence GA modules, project interpreter and GA worker handshake.
    methods["sequence_ga_design"] = sequence_ga_jobs.capability(methods["ligand_docking"], methods["mutation_model"])
    # M24: local conditions only (tool exposed, pins equal the gate's); never reads a credential or a run's consent.
    methods["jev_choice"] = _jev_choice_capability()
    # M25: per branch, the loop projection tool, the science pins (as jev_choice), then that branch's engines.
    methods["jev_loop"] = _jev_loop_capability(methods)
    return {"mode": "local_only", "energy_protocols": matrix, "methods": methods, "supported": {
        "upload": "local PDB/mmCIF, up to 25 MiB", "preparation": "model, altloc, water, hydrogen policies",
        "interactions": "heavy-atom geometric contacts in angstroms", "viewer_bytes": "local PDB/mmCIF",
        "viewer_intents": "typed local viewer commands; optional explicit online Jev interpretation is credential and budget dependent",
        "jobs": "event-backed local job records and POSIX lifecycle supervision",
        "reports": "offline selected-interaction and interface-SASA evidence reports with Markdown and JSON downloads",
        "inspect_complex": "fixed local workflow over validated run calls"},
        "unavailable": {
            "remote_structure_lookup": "no M1 fetch adapter; local upload only",
            "hbond_or_affinity": "geometric proximity is not chemical or energetic validation",
        "plip": "no validated PLIP adapter is implemented",
            **{f"energy_{name}": item["explanation"] for name, item in matrix["protocols"].items() if not item["available"]},
            "general_model_decisions": "no autonomous scientific tool, job, report, or general decision route"}}


class AnalysisPlanRequest(BaseModel):
    request_id: str
    goal: str
    inputs: dict[str, Any]
    model_config = {"extra": "forbid", "strict": True}


def _analysis_conflict(error: analysis_plans.AnalysisConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"ok": False, "error": error.code, "message": error.message,
                                                  "fix": None, "detail": {}})


@app.get("/runs/{rid}/analysis/templates")
def analysis_templates(rid: str) -> dict[str, Any]:
    """Checked-in local-rule templates; reads capabilities only, runs no tool, job or report."""
    _run(rid)
    return analysis_plans.templates()


@app.post("/runs/{rid}/analysis/plans", status_code=201)
async def analysis_plan_create(rid: str, request: Request) -> Any:
    try:
        raw = await _bounded_chemical_body(request, ANALYSIS_PLAN_REQUEST_LIMIT)
    except HTTPException as exc:
        raise HTTPException(413, detail={"error": "resource_exceeded",
                                         "message": "analysis plan request exceeds 1 MiB"}) from exc
    try:
        body = AnalysisPlanRequest.model_validate(_chemical_json(raw))
    except (HTTPException, PydanticValidationError):
        return _tool_error(ToolFailure(FailureClass.input_invalid, "invalid analysis plan request"))
    run = _run(rid)
    try:
        return await run_in_threadpool(lambda: analysis_plans.create_plan(run, body.request_id, body.goal,
                                                                          body.inputs))
    except analysis_plans.AnalysisConflict as exc:
        return _analysis_conflict(exc)
    except ToolFailure as exc:
        return _tool_error(exc)
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "analysis plan record invalid"}) from exc


@app.get("/runs/{rid}/analysis/plans")
def analysis_plan_list(rid: str) -> dict[str, Any]:
    return analysis_plans.list_plans(_run(rid))


@app.get("/runs/{rid}/analysis/plans/detail")
def analysis_plan_detail(rid: str, handle: str) -> Any:
    try:
        return analysis_plans.plan_detail(_run(rid), handle)
    except ToolFailure as exc:
        return _tool_error(exc)


class AnalysisExecutionCreate(BaseModel):
    request_id: str
    plan_handle: str
    model_config = {"extra": "forbid", "strict": True}


class AnalysisRevisionRequest(BaseModel):
    request_id: str
    expected_revision: int
    model_config = {"extra": "forbid", "strict": True}


class AnalysisApproveRequest(AnalysisRevisionRequest):
    plan_hash: str


class AnalysisRetryRequest(AnalysisRevisionRequest):
    step_id: str


async def _analysis_body(request: Request, model: type[BaseModel]) -> BaseModel | None:
    try:
        raw = await _bounded_chemical_body(request, ANALYSIS_REQUEST_LIMIT)
    except HTTPException as exc:
        raise HTTPException(413, detail={"error": "resource_exceeded",
                                         "message": "analysis request exceeds 64 KiB"}) from exc
    try:
        return model.model_validate(_chemical_json(raw))
    except (HTTPException, PydanticValidationError):
        return None


def _analysis_error(error: analysis_executions.AnalysisError) -> JSONResponse:
    return JSONResponse(status_code=error.status, content={"ok": False, "error": error.code, "message": error.message,
                                                          "fix": None, "detail": error.detail})


async def _analysis_call(fn: Any) -> Any:
    try:
        return await run_in_threadpool(fn)
    except analysis_executions.AnalysisError as exc:
        return _analysis_error(exc)
    except analysis_plans.AnalysisConflict as exc:
        return _analysis_conflict(exc)
    except ToolFailure as exc:
        return _tool_error(exc)
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "analysis execution record invalid"}) from exc


def _invalid_analysis_request() -> JSONResponse:
    return _tool_error(ToolFailure(FailureClass.input_invalid, "invalid analysis execution request"))


@app.post("/runs/{rid}/analysis/executions", status_code=201)
async def analysis_execution_create(rid: str, request: Request) -> Any:
    body = await _analysis_body(request, AnalysisExecutionCreate)
    if body is None:
        return _invalid_analysis_request()
    run = _run(rid)
    return await _analysis_call(lambda: analysis_executions.create_execution(run, body.request_id, body.plan_handle))


@app.get("/runs/{rid}/analysis/executions")
async def analysis_execution_list(rid: str) -> Any:
    """Read-only list; never reconciles, retries or appends events."""
    run = _run(rid)
    return await _analysis_call(lambda: analysis_executions.list_executions(run))


@app.get("/runs/{rid}/analysis/executions/{execution_id}")
async def analysis_execution_detail(rid: str, execution_id: str) -> Any:
    """Read-only record; owned job state is a derived view, recorded only by the next Advance."""
    run = _run(rid)
    return await _analysis_call(lambda: analysis_executions.execution_detail(run, execution_id))


@app.post("/runs/{rid}/analysis/executions/{execution_id}/approve")
async def analysis_execution_approve(rid: str, execution_id: str, request: Request) -> Any:
    body = await _analysis_body(request, AnalysisApproveRequest)
    if body is None:
        return _invalid_analysis_request()
    run = _run(rid)
    return await _analysis_call(lambda: analysis_executions.approve(
        run, execution_id, body.request_id, body.expected_revision, body.plan_hash))


@app.post("/runs/{rid}/analysis/executions/{execution_id}/revoke")
async def analysis_execution_revoke(rid: str, execution_id: str, request: Request) -> Any:
    body = await _analysis_body(request, AnalysisRevisionRequest)
    if body is None:
        return _invalid_analysis_request()
    run = _run(rid)
    return await _analysis_call(lambda: analysis_executions.revoke(
        run, execution_id, body.request_id, body.expected_revision))


@app.post("/runs/{rid}/analysis/executions/{execution_id}/advance")
async def analysis_execution_advance(rid: str, execution_id: str, request: Request) -> Any:
    body = await _analysis_body(request, AnalysisRevisionRequest)
    if body is None:
        return _invalid_analysis_request()
    run = _run(rid)
    return await _analysis_call(lambda: analysis_executions.advance(
        run, execution_id, body.request_id, body.expected_revision))


@app.post("/runs/{rid}/analysis/executions/{execution_id}/retry")
async def analysis_execution_retry(rid: str, execution_id: str, request: Request) -> Any:
    body = await _analysis_body(request, AnalysisRetryRequest)
    if body is None:
        return _invalid_analysis_request()
    run = _run(rid)
    return await _analysis_call(lambda: analysis_executions.retry(
        run, execution_id, body.request_id, body.expected_revision, body.step_id))


@app.post("/runs/{rid}/analysis/executions/{execution_id}/cancel")
async def analysis_execution_cancel(rid: str, execution_id: str, request: Request) -> Any:
    body = await _analysis_body(request, AnalysisRevisionRequest)
    if body is None:
        return _invalid_analysis_request()
    run = _run(rid)
    return await _analysis_call(lambda: analysis_executions.cancel(
        run, execution_id, body.request_id, body.expected_revision))


@app.post("/runs/{rid}/analysis/executions/{execution_id}/scientific-approval")
async def analysis_execution_scientific_approval(rid: str, execution_id: str, request: Request) -> Any:
    body = await _analysis_body(request, AnalysisRevisionRequest)
    if body is None:
        return _invalid_analysis_request()
    run = _run(rid)
    return await _analysis_call(lambda: analysis_executions.scientific_approval(
        run, execution_id, body.request_id, body.expected_revision))


@app.get("/runs/{rid}/analysis/executions/{execution_id}/summary")
async def analysis_execution_summary(rid: str, execution_id: str,
                                     download: Literal["json"] | None = None) -> Any:
    run = _run(rid)
    result = await _analysis_call(lambda: analysis_executions.summary(run, execution_id))
    if not isinstance(result, dict):
        return result
    if download == "json":
        return Response(result["raw"], media_type="application/json", headers={
            "Content-Disposition": f'attachment; filename="protview-workflow-summary-{execution_id[5:17]}.json"',
            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
    return {"handle": result["handle"], "summary": result["summary"]}


@app.get("/tools")
def tools(levels: str = "L2,L4") -> list[dict[str, Any]]:
    selected = set(levels.split(","))
    records = [spec.model_dump() for spec in REGISTRY.visible(selected)
               if spec.name in SUPPORTED_TOOLS]
    if "L3" in selected:
        records.append({**REGISTRY.specs["openmm_protein_minimize"].model_dump(),
                        "execution_lane": "durable_job", "submit_protocol_id": "openmm_protein_minimize"})
        # M21: the job-only mutation model tool (JobQueue protocol, not Run.call).
        records.append({**REGISTRY.specs["openmm_mutation_model"].model_dump(),
                        "execution_lane": "durable_job", "submit_protocol_id": "openmm_mutation_model_v1"})
    return records


@app.post("/runs", status_code=201)
def create_run(body: NewRun) -> dict[str, Any]:
    rid = f"run_{uuid.uuid4().hex}"
    run = new_run(RUNS_DIR, dry_run=body.dry_run, run_id=rid, registry=REGISTRY,
                  egress_config={"mode": body.egress})
    run.events.append("goal", text=body.goal, context=body.context, egress=body.egress)
    RUNS[rid] = run
    return _summary(run)


@app.get("/runs")
def list_runs() -> list[dict[str, Any]]:
    if not RUNS_DIR.exists():
        return []
    result = []
    for path in sorted(RUNS_DIR.iterdir()):
        if path.is_dir() and not path.is_symlink() and RUN_ID_RE.fullmatch(path.name):
            try:
                result.append(_summary(_run(path.name)))
            except HTTPException:
                continue
    return result


@app.get("/runs/{rid}")
def get_run(rid: str) -> dict[str, Any]:
    return _summary(_run(rid))


@app.post("/runs/{rid}/viewer/sessions", status_code=201)
def viewer_session_create(rid: str, body: ViewerSessionRequest) -> dict[str, Any]:
    run = _run(rid)
    try:
        session = create_session(run, **body.model_dump())
        return {**session, "projection": projection_preview(session)}
    except ViewerError as exc:
        raise _viewer_error(exc) from exc
    except (EvidenceError, ToolFailure, ValueError, KeyError) as exc:
        raise HTTPException(422, detail={"error": "scene_invalid", "message": "displayed structure is invalid"}) from exc


@app.get("/runs/{rid}/viewer/sessions/{session_id}")
def viewer_session_get(rid: str, session_id: str) -> dict[str, Any]:
    run = _run(rid)
    try:
        session = session_public(run, session_id)
        return {**session, "projection": projection_preview(session)}
    except ViewerError as exc:
        raise _viewer_error(exc) from exc


@app.post("/runs/{rid}/viewer/sessions/{session_id}/state")
def viewer_scene_state(rid: str, session_id: str, body: ViewerSceneUpdate) -> dict[str, Any]:
    try:
        return update_scene(_run(rid), session_id, **body.model_dump())
    except ViewerError as exc:
        raise _viewer_error(exc) from exc


async def _bounded_scene_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise HTTPException(413, detail={"error": "resource_exceeded", "message": "viewer payload exceeds limit"})
        except ValueError as exc:
            raise HTTPException(400, detail={"error": "input_invalid", "message": "invalid content length"}) from exc
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > limit:
            raise HTTPException(413, detail={"error": "resource_exceeded", "message": "viewer payload exceeds limit"})
        chunks.extend(chunk)
    return bytes(chunks)


@app.post("/runs/{rid}/viewer/scenes", status_code=201)
async def viewer_scene_save(rid: str, request: Request) -> dict[str, Any]:
    try:
        body = parse_scene_save(await _bounded_scene_body(request, SCENE_BODY_LIMIT))
        return await run_in_threadpool(lambda: save_scene(_run(rid), body))
    except PydanticValidationError as exc:
        raise HTTPException(422, detail={"error": "input_invalid", "message": "invalid scene payload"}) from exc
    except ViewerError as exc:
        raise _viewer_error(exc) from exc


@app.get("/runs/{rid}/viewer/scenes")
def viewer_scenes(rid: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    try:
        return list_scenes(_run(rid), offset, limit)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc


@app.get("/runs/{rid}/viewer/scenes/selected")
def viewer_scene_selected(rid: str, handle: str) -> dict[str, Any]:
    try:
        return scene_detail(_run(rid), handle)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc


@app.post("/runs/{rid}/viewer/figures", status_code=201)
async def viewer_figure_save(rid: str, request: Request) -> dict[str, Any]:
    try:
        body = parse_figure_save(await _bounded_scene_body(request, FIGURE_BODY_LIMIT))
        return await run_in_threadpool(lambda: save_figure(_run(rid), body))
    except PydanticValidationError as exc:
        raise HTTPException(422, detail={"error": "input_invalid", "message": "invalid figure payload"}) from exc
    except ViewerError as exc:
        raise _viewer_error(exc) from exc


@app.get("/runs/{rid}/viewer/figures")
def viewer_figures(rid: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    try:
        return list_figures(_run(rid), offset, limit)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc


@app.get("/runs/{rid}/viewer/figures/selected")
def viewer_figure_selected(rid: str, handle: str) -> dict[str, Any]:
    try:
        return figure_detail(_run(rid), handle)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc


@app.get("/runs/{rid}/viewer/figures/download")
def viewer_figure_download(rid: str, handle: str, format: Literal["png", "json"]) -> Response:
    try:
        raw = figure_download(_run(rid), handle, format)
        suffix = handle.rsplit("/", 1)[-1][:12]
        return Response(content=raw, media_type="image/png" if format == "png" else "application/json",
                        headers={"Content-Disposition": f'attachment; filename="protview-figure-{suffix}.{format}"',
                                 "Cache-Control": "no-store"})
    except ViewerError as exc:
        raise _viewer_error(exc) from exc


@app.get("/runs/{rid}/viewer/online")
def viewer_online_get(rid: str) -> dict[str, Any]:
    return online_status(_run(rid))


@app.post("/runs/{rid}/viewer/online")
def viewer_online_change(rid: str, body: ViewerOnlineRequest) -> dict[str, Any]:
    try:
        return set_online(_run(rid), body.enabled)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc


@app.post("/runs/{rid}/viewer/intents", status_code=201)
async def viewer_intent_create(rid: str, body: ViewerIntentRequest) -> dict[str, Any]:
    run = _run(rid)
    try:
        intent_id, session, duplicate = request_intent(run, **body.model_dump())
        if duplicate:
            return intent_public(run, intent_id)
        if body.prompt.strip().startswith("/"):
            try:
                answers = local_answers(body.prompt, session)
                status, commands, reason = compile_answers(answers, session, intent_id=intent_id)
                return finish_intent(run, intent_id, status=status, reason_code=reason,
                                     commands=commands, question_version="local_commands@1")
            except ViewerError as exc:
                return finish_intent(run, intent_id, status="unsupported", reason_code=exc.code)
        if not effective_online(run) or run.dry_run:
            return finish_intent(run, intent_id, status="unsupported",
                                 reason_code="dry_run" if run.dry_run else "online_not_enabled")
        state = projected_state(session, body.prompt)
        ACTIVE_INTENTS.add(intent_id)
        try:
            result = await VIEWER_GATE.request_viewer(run, state, intent_id)
        finally:
            ACTIVE_INTENTS.discard(intent_id)
        metadata = {"projection_sha256": result.projection_sha256,
                    "question_version": VIEWER_QUESTION_VERSION,
                    "requested_model": result.requested_model,
                    "served_model": result.served_model, "audit_id": result.audit_id,
                    "usage": result.usage}
        if result.status != "accepted" or result.answers is None:
            return finish_intent(run, intent_id,
                                 status="cancelled" if result.reason_code == "cancelled" else "rejected",
                                 reason_code=result.reason_code,
                                 **metadata)
        latest_session = session_public(run, session["viewer_session_id"])
        if (not intent_live(run, intent_id) or not latest_session["current"] or
                latest_session["action_revision"] != session["action_revision"]):
            return finish_intent(run, intent_id, status="cancelled", reason_code="scene_or_mode_changed",
                                 **metadata)
        try:
            status, commands, reason = compile_answers(result.answers, session, intent_id=intent_id)
        except ViewerError as exc:
            return finish_intent(run, intent_id, status="rejected", reason_code=exc.code, **metadata)
        return finish_intent(run, intent_id, status=status, reason_code=reason,
                             commands=commands, **metadata)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc
    except ToolFailure as exc:
        return _tool_error(exc)


@app.get("/runs/{rid}/viewer/intents")
def viewer_intent_list(rid: str) -> list[dict[str, Any]]:
    return list_intents(_run(rid))


@app.get("/runs/{rid}/viewer/intents/{intent_id}")
def viewer_intent_get(rid: str, intent_id: str) -> dict[str, Any]:
    try:
        return intent_public(_run(rid), intent_id)
    except ViewerError as exc:
        raise _viewer_error(exc) from exc


@app.post("/runs/{rid}/viewer/intents/{intent_id}/cancel")
def viewer_intent_cancel(rid: str, intent_id: str, body: ViewerCancelRequest | None = None) -> dict[str, Any]:
    try:
        return cancel_intent(_run(rid), intent_id, **(body.model_dump() if body else {}))
    except ViewerError as exc:
        raise _viewer_error(exc) from exc


@app.post("/runs/{rid}/viewer/intents/{intent_id}/ack")
def viewer_intent_ack(rid: str, intent_id: str, body: ViewerAckRequest) -> dict[str, Any]:
    try:
        return acknowledge(_run(rid), intent_id, **body.model_dump())
    except ViewerError as exc:
        raise _viewer_error(exc) from exc


@app.post("/runs/{rid}/uploads", status_code=201)
async def upload(rid: str, request: Request, filename: str = Query(...)) -> dict[str, Any]:
    run = _run(rid)
    fmt = Path(filename).suffix.lower().lstrip(".")
    if fmt not in {"pdb", "cif", "mmcif"}:
        raise HTTPException(422, detail={"error": "input_invalid", "message": "use .pdb, .cif or .mmcif"})
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, detail={"error": "resource_exceeded", "message": "upload exceeds 25 MiB"})
        raw.extend(chunk)
    try:
        parsed = validate_upload(bytes(raw), fmt)
    except ToolFailure as error:
        return _tool_error(error)
    sha = hashlib.sha256(raw).hexdigest()
    directory_fd = _upload_dir_fd(run, create=True)
    name = f"{sha}.{fmt}"
    try:
        try:
            descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory_fd)
        except FileExistsError:
            if _read_upload(directory_fd, name) != raw:
                raise HTTPException(409, detail={"error": "upload_conflict",
                                                 "message": "stored upload differs"})
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
    except OSError as exc:
        raise HTTPException(422, detail={"error": "input_invalid",
                                         "message": "unsafe upload path"}) from exc
    finally:
        os.close(directory_fd)
    upload_id = f"upload://{rid}/{sha}.{fmt}"
    run.events.append("upload_received", upload_id=upload_id, sha256=sha, size=len(raw), format=fmt)
    return {"upload_id": upload_id, "sha256": sha, "size": len(raw), **parsed}


@app.post("/runs/{rid}/commands")
def command(rid: str, cmd: Command) -> Any:
    run = _run(rid)
    if cmd.tool not in SUPPORTED_TOOLS:
        return _tool_error(ToolFailure(FailureClass.input_invalid, f"unsupported tool '{cmd.tool}'"))
    args = dict(cmd.args)
    source_bytes = None
    source_format = None
    if cmd.tool == "load_structure":
        try:
            source_bytes, source_format = _verified_upload(run, args.get("source"))
        except HTTPException as exc:
            return _tool_error(ToolFailure(FailureClass.input_invalid, exc.detail["message"]))
    try:
        result = run.call(cmd.tool, args, decided_by=cmd.decided_by, execution_mode="human",
                          source_bytes=source_bytes, source_format=source_format)
        return {"ok": True, "handle": result.model_dump(by_alias=True)}
    except ToolFailure as error:
        return _tool_error(error)
    except ValueError as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": str(exc)}) from exc
    except ApprovalRequired as error:
        return JSONResponse(status_code=409, content={"ok": False,
                            "approval": {"gate": error.gate, "tool": error.tool, "reason": error.reason}})
    except LoopStop as error:
        return JSONResponse(status_code=409, content={"ok": False,
                            "loop_stop": {"reason": error.reason, **error.detail}})
    except RunCancelled:
        return JSONResponse(status_code=409, content={"ok": False,
                            "error": "cancelled", "message": "run cancelled"})


@app.post("/runs/{rid}/inspect_complex")
def inspection(rid: str, body: InspectionRequest) -> dict[str, Any]:
    run = _run(rid)
    raw = None
    fmt = None
    if body.upload_id is not None:
        try:
            raw, fmt = _verified_upload(run, body.upload_id)
        except HTTPException:
            # A completed load step can resume from events after uploads are gone.
            if not any(e["type"] == "workflow_started" and
                       e.get("request", {}).get("upload_id") == body.upload_id and
                       any(s["type"] == "workflow_step_completed" and s.get("step") == "load" and
                           s.get("workflow_id") == e["workflow_id"] for s in run.events.read())
                       for e in run.events.read()):
                raise
    try:
        return inspect_complex(run, body, source_bytes=raw, source_format=fmt)
    except ToolFailure as exc:
        return _tool_error(exc)
    except (ValueError, KeyError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": str(exc)}) from exc


@app.post("/runs/{rid}/reports", status_code=201)
def create_report(rid: str, body: ReportRequest) -> dict[str, Any]:
    try:
        result = build_inspection_report(_run(rid), body.interaction_handle,
                                         prepared_handle=body.prepared_handle)
        return result
    except ToolFailure as exc:
        return _tool_error(exc)
    except (EvidenceError, KeyError, ValueError) as exc:
        raise HTTPException(422, detail={"error": "report_evidence_invalid", "message": str(exc)}) from exc


@app.post("/runs/{rid}/method_reports", status_code=201)
def create_method_report(rid: str, body: MethodReportRequest) -> dict[str, Any]:
    try:
        run = _run(rid)
        kind = run.store.meta(body.result_handle)["kind"]
        if kind == "ligand_candidate_set":
            # Reads the stored candidate set only; nothing is enumerated again.
            return build_ligand_report(run, body.result_handle, filters=body.filters)
        if body.filters is not None:
            raise EvidenceError("filters_apply_only_to_ligand_candidates")
        if kind == "interface_sasa":
            return build_method_report(run, body.result_handle)
        if kind == "openmm_minimization":
            return build_openmm_report(run, body.result_handle)
        if kind in {"atom_distance", "rigid_alignment"}:
            return build_comparison_report(run, body.result_handle)
        if kind == "chemical_interaction_set":
            _completed_chemical(run, body.result_handle)
            return build_chemical_report(run, body.result_handle)
        if kind == "pocket_set":
            # Completion (single fpocket_detect_v1 publication) is validated inside the build.
            return build_pocket_report(run, body.result_handle)
        if kind == "residue_numbering_map":
            return build_numbering_report(run, body.result_handle)
        if kind == "reference_site_annotation":
            # The active reference set is recorded in the report snapshot only; the report reads stored objects.
            return build_site_annotation_report(run, body.result_handle,
                                                active_set_hash=numbering_reads.capability()["set_hash"])
        if kind == "docking_result":
            # Reads the stored docking result only (validated against its publication); nothing is docked again.
            return build_docking_report(run, body.result_handle)
        if kind == "docking_batch_result":
            # Reads the stored batch summary and its per-row results only; nothing is docked again and no per-row
            # docking report is made.
            return build_docking_batch_report(run, body.result_handle)
        if kind == ligand_ga_reads.SUMMARY:
            # Reads the stored GA summary and its individuals' results only; nothing is docked again.
            return build_ligand_ga_report(run, body.result_handle)
        if kind == sequence_ga_reads.SUMMARY:
            # M23: reads the stored sequence GA summary, its rows' models and results only; nothing is modelled or
            # docked again.
            return build_sequence_ga_report(run, body.result_handle)
        if kind == "mutation_candidate_set":
            # Reads the stored candidate set only (re-validated); no candidate is generated again.
            return build_mutation_report(run, body.result_handle)
        if kind == "mutation_model":
            # Reads the stored mutation model only (re-validated); nothing is modelled or minimized again.
            return build_mutation_model_report(run, body.result_handle)
        if kind == jev_constants.CHOICE_KIND:
            # M24: reads the stored proposal, its projection, candidate set and send events only; nothing is sent.
            return build_jev_report(run, body.result_handle)
        raise EvidenceError("wrong_method_result_kind")
    except ToolFailure as exc:
        return _tool_error(exc)
    except (EvidenceError, KeyError, ValueError) as exc:
        raise HTTPException(422, detail={"error": "report_evidence_invalid", "message": str(exc)}) from exc


@app.get("/runs/{rid}/reports")
def list_reports(rid: str) -> list[dict[str, Any]]:
    run = _run(rid)
    records = [e for e in run.events.read() if e["type"] in {"report_created", "method_report_created"}]
    try:
        for event in records:
            expected = (("report_manifest", "report_manifest@1") if event["type"] == "report_created" else
                        ("method_report_manifest", "method_report_manifest@1"))
            meta = run.store.meta(event["report_handle"])
            if (meta["kind"], meta["schema"]) != expected:
                raise EvidenceError("report_event_type_mismatch")
            _saved_any_report(run, event["report_handle"])
        return [{"handle": e["report_handle"],
                 **({"interaction_handle": e["interaction_handle"]} if e["type"] == "report_created" else
                    {"result_handle": e["result_handle"],
                     "analysis_type": (run.store.load_bounded_json(e["report_handle"], 8 * 1024 * 1024)
                                       if run.store.meta(e["report_handle"])["summary"].get("analysis_type") in
                                       {"chemical_interactions", "pocket_detection", "residue_numbering",
                                        "reference_site_annotation", "ligand_candidates", "ligand_docking",
                                        "ligand_docking_batch", "mutation_candidates", "mutation_model",
                                        "ligand_ga", "sequence_ga", "jev_choice"}
                                       else run.store.load(e["report_handle"]))["analysis_type"]}),
                 "markdown_handle": e["markdown_handle"], "created_seq": e["seq"],
                 "snapshot_event_seq": e["snapshot_event_seq"]} for e in records]
    except (EvidenceError, KeyError, ValueError, ToolFailure) as exc:
        raise HTTPException(422, detail={"error": "report_evidence_invalid", "message": str(exc)}) from exc


def _saved_any_report(run: Run, handle: str) -> dict[str, Any]:
    meta = run.store.meta(handle)
    if (meta["kind"], meta["schema"]) == ("report_manifest", "report_manifest@1"):
        return saved_report(run, handle)
    if (meta["kind"], meta["schema"]) == ("method_report_manifest", "method_report_manifest@1"):
        report = (run.store.load_bounded_json(handle, 8 * 1024 * 1024)
                  if meta["summary"].get("analysis_type") in {"chemical_interactions", "pocket_detection", "residue_numbering",
                                                              "reference_site_annotation", "ligand_candidates",
                                                              "ligand_docking", "ligand_docking_batch",
                                                              "mutation_candidates", "mutation_model", "ligand_ga",
                                                              "sequence_ga", "jev_choice"}
                  else run.store.load(handle))
        if report.get("analysis_type") == "interface_sasa":
            return saved_method_report(run, handle)
        if report.get("analysis_type") == "openmm_protein_minimize":
            return saved_openmm_report(run, handle)
        if report.get("analysis_type") in {"atom_distance", "rigid_alignment"}:
            return saved_comparison_report(run, handle)
        if report.get("analysis_type") == "chemical_interactions":
            _completed_chemical(run, report["result_handle"])
            return saved_chemical_report(run, handle)
        if report.get("analysis_type") == "pocket_detection":
            return saved_pocket_report(run, handle)
        if report.get("analysis_type") == "residue_numbering":
            return saved_numbering_report(run, handle)
        if report.get("analysis_type") == "reference_site_annotation":
            return saved_site_annotation_report(run, handle)
        if report.get("analysis_type") == "ligand_candidates":
            return saved_ligand_report(run, handle)
        if report.get("analysis_type") == "ligand_docking":
            return saved_docking_report(run, handle)
        if report.get("analysis_type") == "ligand_docking_batch":
            return saved_docking_batch_report(run, handle)
        if report.get("analysis_type") == "ligand_ga":
            return saved_ligand_ga_report(run, handle)
        if report.get("analysis_type") == "sequence_ga":
            return saved_sequence_ga_report(run, handle)
        if report.get("analysis_type") == "mutation_candidates":
            return saved_mutation_report(run, handle)
        if report.get("analysis_type") == "mutation_model":
            return saved_mutation_model_report(run, handle)
        if report.get("analysis_type") == "jev_choice":
            return saved_jev_report(run, handle)
        raise EvidenceError("unknown_method_report_type")
    raise EvidenceError("wrong_report_kind")


@app.get("/runs/{rid}/reports/selected")
def report_detail(rid: str, handle: str) -> dict[str, Any]:
    try:
        return _saved_any_report(_run(rid), handle)
    except (EvidenceError, KeyError, ValueError, ToolFailure) as exc:
        raise HTTPException(422, detail={"error": "report_evidence_invalid", "message": str(exc)}) from exc


@app.get("/runs/{rid}/reports/download")
def report_download(rid: str, handle: str, format: Literal["markdown", "json"] = "markdown") -> Response:
    try:
        result = _saved_any_report(_run(rid), handle)
    except (EvidenceError, KeyError, ValueError, ToolFailure) as exc:
        raise HTTPException(422, detail={"error": "report_evidence_invalid", "message": str(exc)}) from exc
    suffix = handle.rsplit("/", 1)[-1][:12]
    if format == "markdown":
        raw = result["markdown"].encode("utf-8")
        mime, ext = "text/markdown; charset=utf-8", "md"
    else:
        from ..core.handles import canonical_json
        raw = canonical_json(result["manifest"])
        mime, ext = "application/json", "json"
    return Response(raw, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="protview-report-{suffix}.{ext}"',
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@app.get("/runs/{rid}/events")
def events(rid: str, after: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=500)) -> list[dict[str, Any]]:
    page = [event for event in _run(rid).events.read() if event["seq"] > after][:limit]
    return [{key: value for key, value in event.items()
             if key not in {"payload_b64", "launch_nonce", "identity", "owner_token"}} for event in page]


@app.get("/runs/{rid}/budget")
def budget(rid: str) -> dict[str, Any]:
    return _run(rid).budget_snapshot()


@app.get("/runs/{rid}/jobs/preflight")
def job_preflight(rid: str, structure: str) -> dict[str, Any]:
    run = _run(rid)
    try:
        selected = openmm_preflight(run.store, structure, seed=run.seed)
        return {"available": True, "structure": structure, "selection_policy": "protein_only",
                "hydrogen_policy": "rebuild_pH7", "heavy_atom_count": selected["heavy_atom_count"],
                "excluded": selected["excluded"],
                "source_hydrogens_removed": selected["source_hydrogens_removed"],
                "method": selected["method"], "budget": run.budget_snapshot()}
    except ToolFailure as error:
        return _tool_error(error)


@app.post("/runs/{rid}/jobs/approve")
def approve_job(rid: str) -> dict[str, Any]:
    run = _run(rid)
    decisions = [event for event in run.events.read()
                 if event["type"] in {"approval_requested", "approval_resolved"} and
                 event.get("gate") == "expensive_first_call"]
    pending = decisions[-1] if decisions else None
    approved_tools = {"openmm_protein_minimize", "prepare_chemical_structure", "compute_chemical_interactions",
                      "detect_pockets", "rdkit_inspect_ligand", "rdkit_enumerate_ligands", "qvina_dock_ligand",
                      "qvina_dock_batch", "openmm_mutation_model", "qvina_ga_design", "sequence_ga_design"}
    active = {job["tool_id"] for job in JobQueue(run).list() if job["status"] in {"queued", "claimed"}}
    if (pending is None or pending["type"] != "approval_requested" or
            pending.get("tool") not in approved_tools or pending["tool"] not in active):
        raise HTTPException(412, detail={"error": "precondition", "message": "no pending supported job approval request"})
    run.approve("expensive_first_call", by="human_api")
    return {"approved": True, "budget": run.budget_snapshot()}


@app.get("/runs/{rid}/jobs")
def jobs(rid: str) -> list[dict[str, Any]]:
    run = _run(rid)
    return [_public_job(job, run) for job in JobQueue(run).list()]


@app.get("/runs/{rid}/jobs/{job_id}")
def job_detail(rid: str, job_id: str) -> dict[str, Any]:
    try:
        run = _run(rid)
        return _public_job(JobQueue(run).get(job_id), run)
    except KeyError as exc:
        raise HTTPException(404, detail={"error": "not_found", "message": "unknown job"}) from exc


@app.post("/runs/{rid}/jobs")
async def submit_job(rid: str, request: Request) -> Any:
    raw = await _bounded_chemical_body(request, CHEMICAL_REQUEST_LIMIT)
    data = _chemical_json(raw)
    try:
        body = JobSubmit.model_validate(data)
    except PydanticValidationError as exc:
        # M21 keeps its closed admission reason for the request model's own timeout_s / args refusals.
        if data.get("protocol_id") == MUTATION_MODEL_PROTOCOL and all(
                error["loc"] and error["loc"][0] in {"timeout_s", "args"} for error in exc.errors()):
            return _tool_error(ToolFailure(FailureClass.input_invalid, "invalid job timeout or arguments",
                                           detail={"reason_code": "argument_invalid"}))
        # M22 and M23 keep their closed admission reason too (no server timeout default; timeout_s <= 15000).
        if data.get("protocol_id") in (GA_PROTOCOL, SEQUENCE_GA_PROTOCOL) and all(
                error["loc"] and error["loc"][0] in {"timeout_s", "args"} for error in exc.errors()):
            return _tool_error(ToolFailure(FailureClass.input_invalid, "invalid job timeout or arguments",
                                           detail={"reason_code": "invalid_job_arguments"}))
        raise HTTPException(422, detail={"error": "input_invalid", "message": "invalid job request"}) from exc
    try:
        # An absent timeout_s is the protocol default (M21: 120 s; M22, M23: none, refused; every other: 60 s).
        timeout_s = body.timeout_s if "timeout_s" in body.model_fields_set else None
        result = await run_in_threadpool(lambda: JobQueue(_run(rid)).submit(
            body.protocol_id, body.args, timeout_s=timeout_s))
        return result if result.get("plan_only") else _public_job(result)
    except ToolFailure as error:
        return _tool_error(error)


@app.post("/runs/{rid}/jobs/{job_id}/start")
def start_job(rid: str, job_id: str) -> Any:
    try:
        run = _run(rid)
        return _public_job(JobQueue(run).start(
            job_id, owner_active=lambda eid: analysis_executions.execution_active(run, eid)), run)
    except KeyError as exc:
        raise HTTPException(404, detail={"error": "not_found", "message": "unknown job"}) from exc
    except ApprovalRequired as exc:
        return JSONResponse(status_code=409, content={"ok": False, "approval": {
            "gate": exc.gate, "tool": exc.tool, "reason": exc.reason}})
    except RunCancelled:
        return JSONResponse(status_code=409, content={"ok": False, "error": "cancelled", "message": "run cancelled"})
    except ToolFailure as error:
        if error.detail.get("reason_code") in {"global_concurrency_busy", "global_job_cleanup_pending",
                                               "global_job_ledger_unavailable"}:
            return JSONResponse(status_code=409, content={"ok": False, **error.to_dict()})
        return _tool_error(error)


@app.post("/runs/{rid}/jobs/{job_id}/retry")
def retry_job(rid: str, job_id: str) -> Any:
    try:
        run = _run(rid)
        return _public_job(JobQueue(run).retry(
            job_id, owner_active=lambda eid: analysis_executions.execution_active(run, eid)))
    except KeyError as exc:
        raise HTTPException(404, detail={"error": "not_found", "message": "unknown job"}) from exc
    except ToolFailure as error:
        return _tool_error(error)
    except RunCancelled:
        return JSONResponse(status_code=409, content={"ok": False, "error": "cancelled", "message": "run cancelled"})


@app.post("/runs/{rid}/jobs/{job_id}/cancel")
def cancel_job(rid: str, job_id: str) -> dict[str, Any]:
    try:
        result = JobQueue(_run(rid)).request_cancel(job_id)
        return {"status": result["status"], "job": _public_job(result["job"])}
    except KeyError as exc:
        raise HTTPException(404, detail={"error": "not_found", "message": "unknown job"}) from exc


@app.get("/runs/{rid}/objects")
def materialize(rid: str, handle: str, columns: str | None = None, offset: int = Query(0, ge=0),
                limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    run = _run(rid)
    meta = _object(run, handle)
    if meta["kind"] in CHEMICAL_DERIVED_KINDS:
        try:
            _completed_chemical(run, handle)
        except ToolFailure as exc:
            return _tool_error(exc)
    selected = columns.split(",") if columns is not None else None
    try:
        if meta["kind"] == "residue_numbering_map":
            rows, total = numbering_reads.numbering_rows(run.store.load(handle), selected, offset, limit)
        else:
            rows = run.store.materialize(handle, selected, offset, limit)
            content = run.store.load(handle)
            total = len(content["rows"] if meta["kind"] == "interaction_set" else content)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, detail={"error": "input_invalid", "message": str(exc)}) from exc
    return {"meta": meta, "rows": rows, "total": total, "offset": offset, "limit": limit}


@app.get("/runs/{rid}/objects/meta")
def object_meta(rid: str, handle: str) -> dict[str, Any]:
    run = _run(rid)
    meta = _object(run, handle)
    if meta["kind"] in CHEMICAL_DERIVED_KINDS:
        try:
            _completed_chemical(run, handle)
        except ToolFailure as exc:
            return _tool_error(exc)
    return meta


def _read_invalid(exc: Exception) -> HTTPException:
    return HTTPException(422, detail={"error": "input_invalid", "message": str(exc)})


@app.get("/reference/snapshots")
def reference_snapshot_summary() -> dict[str, Any]:
    """Active reference set records or the unavailable reason; reads the local reference folder only."""
    return numbering_reads.snapshots()


@app.get("/reference/sifts_chains")
def reference_sifts_chains(pdb_id: str) -> dict[str, Any]:
    try:
        return numbering_reads.sifts_chains(pdb_id)
    except numbering_reads.ReadInvalid as exc:
        raise _read_invalid(exc) from exc


@app.get("/reference/uniprot")
def reference_uniprot(query: str = Query("", max_length=100), offset: int = Query(0, ge=0),
                      limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    return numbering_reads.uniprot_search(query, offset, limit)


@app.get("/runs/{rid}/reference/pdb_id_hint")
def reference_pdb_id_hint(rid: str, structure: str) -> dict[str, Any]:
    """A PDB ID suggestion from the structure's uploaded bytes; runs no tool and writes no event."""
    run = _run(rid)
    meta = _object(run, structure)
    try:
        return numbering_reads.pdb_id_hint(run.store, structure, meta["kind"])
    except numbering_reads.ReadInvalid as exc:
        raise _read_invalid(exc) from exc
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid structure source"}) from exc


@app.get("/runs/{rid}/numbering_maps")
def numbering_maps(rid: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    run = _run(rid)
    try:
        return numbering_reads.numbering_maps(run, offset, limit)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid residue numbering map"}) from exc


def _only_query(request: Request, allowed: set[str]) -> None:
    unknown = set(request.query_params) - allowed
    if unknown:
        raise HTTPException(422, detail={"error": "input_invalid", "message": f"unknown parameters: {sorted(unknown)}"})


@app.get("/runs/{rid}/site_annotations")
def site_annotation_list(rid: str, request: Request, structure: str | None = None, offset: int = Query(0, ge=0),
                         limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    """M16: this run's reference site annotations, newest first (optionally one structure); no event, no tool."""
    _only_query(request, {"structure", "offset", "limit"})
    run = _run(rid)
    active = numbering_reads.capability()["set_hash"]   # None when no usable active reference set
    try:
        return site_annotations.list_annotations(run, structure, offset, limit, active)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid reference site annotation"}) from exc


@app.get("/runs/{rid}/site_annotations/detail")
def site_annotation_detail(rid: str, request: Request, handle: str) -> dict[str, Any]:
    """M16: one stored annotation as written by the tool; no event, no tool."""
    _only_query(request, {"handle"})
    run = _run(rid)
    meta = _object(run, handle)
    if (meta["kind"], meta["schema"]) != (site_annotations.KIND, site_annotations.SCHEMA):
        raise HTTPException(422, detail={"error": "input_invalid", "message": "handle is not a reference site annotation"})
    try:
        content = run.store.load(handle)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid reference site annotation"}) from exc
    return {"meta": meta, "annotation": content}


# ----------------------------------------------------------------- M17 ligand reads (no event, job, tool or RDKit)
LIGAND_PREVIEW_LIMIT = 64 * 1024


def _ligand_object(run: Run, handle: str, kind: str) -> dict[str, Any]:
    meta = _object(run, handle)
    if (meta["kind"], meta["schema"]) != (kind, f"{kind}@1"):
        raise HTTPException(422, detail={"error": "input_invalid", "message": f"handle is not a {kind}"})
    return meta


def _ligand_evidence_error(exc: Exception) -> HTTPException:
    return HTTPException(422, detail={"error": "method_evidence_invalid", "message": "invalid ligand evidence"})


def _ligand_corrupt(exc: Exception) -> HTTPException:
    return HTTPException(409, detail={"error": "run_corrupt", "message": "invalid ligand object record"})


@app.get("/runs/{rid}/ligand/prerequisites")
def ligand_prerequisites(rid: str, request: Request) -> dict[str, Any]:
    """M17 input readiness: ligand import counts, inspection/candidate-set counts, capability; starts nothing."""
    _only_query(request, set())
    return ligand_reads.prerequisites(_run(rid))


@app.get("/runs/{rid}/ligand/inspections")
def ligand_inspections(rid: str, request: Request, offset: int = Query(0, ge=0),
                       limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    _only_query(request, {"offset", "limit"})
    run = _run(rid)
    try:
        return ligand_reads.list_inspections(run, offset, limit)
    except (KeyError, TypeError, ValueError) as exc:
        raise _ligand_corrupt(exc) from exc


@app.get("/runs/{rid}/ligand/inspections/detail")
def ligand_inspection_detail(rid: str, request: Request, handle: str) -> dict[str, Any]:
    _only_query(request, {"handle"})
    run = _run(rid)
    meta = _ligand_object(run, handle, ligand_reads.INSPECTION)
    try:
        return {**ligand_reads.inspection_detail(run, handle), "meta": meta}
    except ligand_bundle.LigandEvidenceError as exc:
        raise _ligand_evidence_error(exc) from exc


@app.get("/runs/{rid}/ligand/candidate_sets")
def ligand_candidate_sets(rid: str, request: Request, inspection: str | None = None, offset: int = Query(0, ge=0),
                          limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    _only_query(request, {"inspection", "offset", "limit"})
    run = _run(rid)
    try:
        return ligand_reads.list_candidate_sets(run, inspection, offset, limit)
    except (KeyError, TypeError, ValueError) as exc:
        raise _ligand_corrupt(exc) from exc


@app.get("/runs/{rid}/ligand/candidate_sets/detail")
def ligand_candidate_set_detail(rid: str, request: Request, handle: str) -> dict[str, Any]:
    _only_query(request, {"handle"})
    run = _run(rid)
    meta = _ligand_object(run, handle, ligand_reads.CANDIDATE_SET)
    try:
        return {**ligand_reads.candidate_set_detail(run, handle), "meta": meta}
    except ligand_bundle.LigandEvidenceError as exc:
        raise _ligand_evidence_error(exc) from exc


@app.get("/runs/{rid}/ligand/candidate_sets/rows")
def ligand_candidate_rows(rid: str, request: Request) -> dict[str, Any]:
    """Filter spec, sort and page from the query; evaluated on stored values by the server (spec 5)."""
    try:
        query = ligand_reads.parse_page_query(list(request.query_params.multi_items()))
    except ligand_reads.ReadInvalid as exc:
        raise _read_invalid(exc) from exc
    run = _run(rid)
    _ligand_object(run, query["handle"], ligand_reads.CANDIDATE_SET)
    try:
        return ligand_reads.candidate_page(run, query)
    except ligand_bundle.LigandEvidenceError as exc:
        raise _ligand_evidence_error(exc) from exc
    except ToolFailure as exc:  # a stored row the filter module refuses is corrupt evidence
        raise _ligand_evidence_error(exc) from exc


@app.post("/runs/{rid}/ligand/preview")
async def ligand_preview(rid: str, request: Request) -> Any:
    """Site pre-check on the stored inspection graph (spec 4.1); pure, no event, no job."""
    _only_query(request, set())
    body = _chemical_json(await _bounded_chemical_body(request, LIGAND_PREVIEW_LIMIT))
    run = _run(rid)
    try:
        return await run_in_threadpool(lambda: ligand_reads.preview(run, body))
    except ToolFailure as exc:
        return _tool_error(exc)


# ----------------------------------------------------------------- M18 docking reads (no event, job, tool or engine)
def _docking_result(run: Run, handle: str) -> dict[str, Any]:
    meta = _object(run, handle)
    if (meta["kind"], meta["schema"]) != (docking_reads.RESULT, docking_reads.RESULT_SCHEMA):
        raise HTTPException(422, detail={"error": "input_invalid", "message": "handle is not a docking_result"})
    return meta


def _docking_evidence_error(exc: Exception) -> HTTPException:
    return HTTPException(422, detail={"error": "method_evidence_invalid", "message": "invalid docking evidence"})


def _docking_mode_unknown(exc: Exception) -> HTTPException:
    return HTTPException(404, detail={"error": "not_found", "message": str(exc)})


def _docking_sdf(raw: bytes, filename: str) -> Response:
    return Response(raw, media_type="chemical/x-mdl-sdfile", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@app.get("/runs/{rid}/docking/prerequisites")
def docking_prerequisites(rid: str, request: Request) -> dict[str, Any]:
    """M18 input readiness: receptor/bonds/ligand imports, M17 candidate sets, capability; starts nothing."""
    _only_query(request, set())
    run = _run(rid)
    try:
        return docking_reads.prerequisites(run)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid docking input record"}) from exc


@app.get("/runs/{rid}/docking/receptor_instances")
def docking_receptor_instances(rid: str, request: Request, handle: str) -> Any:
    """Nonstandard residue instances of one receptor import (gemmi); a selection aid, rechecked at admission."""
    _only_query(request, {"handle"})
    run = _run(rid)
    try:
        return docking_reads.receptor_instances(run, handle)
    except docking_reads.ReadInvalid as exc:
        raise _read_invalid(exc) from exc
    except ToolFailure as exc:
        return _tool_error(exc)
    except ValueError as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid receptor import"}) from exc


@app.get("/runs/{rid}/docking/results")
def docking_results(rid: str, request: Request, offset: int = Query(0, ge=0),
                    limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    _only_query(request, {"offset", "limit"})
    run = _run(rid)
    try:
        return docking_reads.list_results(run, offset, limit)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid docking object record"}) from exc


@app.get("/runs/{rid}/docking/results/detail")
def docking_result_detail(rid: str, request: Request, handle: str) -> dict[str, Any]:
    _only_query(request, {"handle"})
    run = _run(rid)
    meta = _docking_result(run, handle)
    try:
        return {**docking_reads.result_detail(run, handle), "meta": meta}
    except docking_bundle.DockingEvidenceError as exc:
        raise _docking_evidence_error(exc) from exc


@app.get("/runs/{rid}/docking/results/contacts")
def docking_result_contacts(rid: str, request: Request, handle: str,
                            mode: int = Query(..., ge=1, le=docking_reads.MODE_MAX),
                            offset: int = Query(0, ge=0),
                            limit: int = Query(docking_reads.CONTACT_LIMIT_DEFAULT, ge=1,
                                               le=docking_reads.CONTACT_LIMIT_MAX)) -> dict[str, Any]:
    """One mode's stored geometric contact rows (ligand_serial, site_index order), paged."""
    _only_query(request, {"handle", "mode", "offset", "limit"})
    run = _run(rid)
    _docking_result(run, handle)
    try:
        return docking_reads.contact_page(run, handle, mode, offset, limit)
    except docking_bundle.DockingEvidenceError as exc:
        raise _docking_evidence_error(exc) from exc
    except docking_reads.ModeUnknown as exc:
        raise _docking_mode_unknown(exc) from exc


@app.get("/runs/{rid}/docking/results/pose_sdf")
def docking_pose_sdf(rid: str, request: Request, handle: str,
                     mode: int = Query(..., ge=1, le=docking_reads.MODE_MAX)) -> Response:
    """One mode's stored pose SDF record (no $$$$), byte for byte."""
    _only_query(request, {"handle", "mode"})
    run = _run(rid)
    _docking_result(run, handle)
    try:
        return _docking_sdf(*docking_reads.pose_sdf(run, handle, mode))
    except docking_bundle.DockingEvidenceError as exc:
        raise _docking_evidence_error(exc) from exc
    except docking_reads.ModeUnknown as exc:
        raise _docking_mode_unknown(exc) from exc


@app.get("/runs/{rid}/docking/results/poses_sdf")
def docking_poses_sdf(rid: str, request: Request, handle: str) -> Response:
    """Every mode's stored pose SDF record in mode order, each followed by $$$$ (titles mode_<n> as stored)."""
    _only_query(request, {"handle"})
    run = _run(rid)
    _docking_result(run, handle)
    try:
        return _docking_sdf(*docking_reads.all_poses_sdf(run, handle))
    except docking_bundle.DockingEvidenceError as exc:
        raise _docking_evidence_error(exc) from exc
    except docking_reads.ModeUnknown as exc:
        raise _docking_mode_unknown(exc) from exc


# ----------------------------------------------------------------- M20 mutation candidate reads (no event, job or tool)
def _mutation_set(run: Run, handle: str) -> dict[str, Any]:
    meta = _object(run, handle)
    if (meta["kind"], meta["schema"]) != (mutation_reads.KIND, mutation_reads.SCHEMA):
        raise HTTPException(422, detail={"error": "input_invalid", "message": "handle is not a mutation_candidate_set"})
    return meta


def _mutation_evidence_error(exc: Exception) -> HTTPException:
    return HTTPException(422, detail={"error": "method_evidence_invalid", "message": "invalid mutation candidate set"})


@app.get("/runs/{rid}/mutation_candidate_sets")
def mutation_candidate_sets(rid: str, request: Request, offset: int = Query(0, ge=0),
                            limit: int = Query(mutation_reads.LIST_LIMIT_DEFAULT, ge=1,
                                               le=mutation_reads.LIST_LIMIT_MAX)) -> dict[str, Any]:
    """This run's mutation candidate sets, newest first; each row re-validated."""
    _only_query(request, {"offset", "limit"})
    run = _run(rid)
    try:
        return mutation_reads.list_sets(run, offset, limit)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid mutation object record"}) from exc


# The handle (obj://<run>/<kind>/<sha>) contains slashes: the sub-resource routes are registered before the detail.
@app.get("/runs/{rid}/mutation_candidate_sets/{handle:path}/positions")
def mutation_candidate_positions(rid: str, handle: str, request: Request, status: str | None = None,
                                 source: str | None = None, exclusion_reason: str | None = None,
                                 chain_auth: str | None = None, sort: str = "order", offset: int = Query(0, ge=0),
                                 limit: int = Query(mutation_reads.POSITION_LIMIT_DEFAULT, ge=1,
                                                    le=mutation_reads.POSITION_LIMIT_MAX)) -> dict[str, Any]:
    """Stored position rows, filtered and sorted on stored values (ligand_distance: ascending, nulls last)."""
    _only_query(request, {"status", "source", "exclusion_reason", "chain_auth", "sort", "offset", "limit"})
    run = _run(rid)
    _mutation_set(run, handle)
    try:
        return mutation_reads.position_page(run, handle, status=status, source=source,
                                            exclusion_reason=exclusion_reason, chain_auth=chain_auth, sort=sort,
                                            offset=offset, limit=limit)
    except mutation_reads.ReadInvalid as exc:
        raise _read_invalid(exc) from exc
    except mutation_reads.MutationEvidenceError as exc:
        raise _mutation_evidence_error(exc) from exc


@app.get("/runs/{rid}/mutation_candidate_sets/{handle:path}/candidates")
def mutation_candidate_rows(rid: str, handle: str, request: Request,
                            position_index: int | None = Query(None, ge=0), to: str | None = None,
                            offset: int = Query(0, ge=0),
                            limit: int = Query(mutation_reads.CANDIDATE_LIMIT_DEFAULT, ge=1,
                                               le=mutation_reads.CANDIDATE_LIMIT_MAX)) -> dict[str, Any]:
    """Stored candidate rows (residue copied from the position row), filtered on stored values."""
    _only_query(request, {"position_index", "to", "offset", "limit"})
    run = _run(rid)
    _mutation_set(run, handle)
    try:
        return mutation_reads.candidate_page(run, handle, position_index=position_index, to=to, offset=offset,
                                             limit=limit)
    except mutation_reads.ReadInvalid as exc:
        raise _read_invalid(exc) from exc
    except mutation_reads.MutationEvidenceError as exc:
        raise _mutation_evidence_error(exc) from exc


@app.get("/runs/{rid}/mutation_candidate_sets/{handle:path}")
def mutation_candidate_set_detail(rid: str, handle: str, request: Request) -> dict[str, Any]:
    """One validated set without positions/candidates, with their totals."""
    _only_query(request, set())
    run = _run(rid)
    meta = _mutation_set(run, handle)
    try:
        return {**mutation_reads.set_detail(run, handle), "meta": meta}
    except mutation_reads.MutationEvidenceError as exc:
        raise _mutation_evidence_error(exc) from exc


# ----------------------------------------------------------------- M21 mutation model reads (no event, job or tool)
def _mutation_model(run: Run, handle: str) -> dict[str, Any]:
    meta = _object(run, handle)
    if (meta["kind"], meta["schema"]) != (mutation_model_reads.KIND, mutation_model_reads.SCHEMA):
        raise HTTPException(422, detail={"error": "input_invalid", "message": "handle is not a mutation_model"})
    return meta


def _mutation_model_evidence_error(exc: Exception) -> HTTPException:
    return HTTPException(422, detail={"error": "method_evidence_invalid", "message": "invalid mutation model"})


@app.get("/runs/{rid}/mutation_models")
def mutation_models(rid: str, request: Request, offset: int = Query(0, ge=0),
                    limit: int = Query(mutation_model_reads.LIST_LIMIT_DEFAULT, ge=1,
                                       le=mutation_model_reads.LIST_LIMIT_MAX)) -> dict[str, Any]:
    """This run's mutation models, newest first; each row re-validated."""
    _only_query(request, {"offset", "limit"})
    run = _run(rid)
    try:
        return mutation_model_reads.list_models(run, offset, limit)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid mutation model record"}) from exc


# The handle (obj://<run>/<kind>/<sha>) contains slashes: every sub-resource route (/contacts, /structure,
# /docking_pairs) is registered before the detail route.
@app.get("/runs/{rid}/mutation_models/{handle:path}/contacts")
def mutation_model_contacts(rid: str, handle: str, request: Request, structure: str,
                            page: int = Query(1, ge=1),
                            page_size: int = Query(mutation_model_reads.CONTACT_PAGE_SIZE_DEFAULT, ge=1,
                                                   le=mutation_model_reads.CONTACT_PAGE_SIZE_MAX)) -> dict[str, Any]:
    """One structure's stored contact rows (stored order), by page."""
    _only_query(request, {"structure", "page", "page_size"})
    run = _run(rid)
    _mutation_model(run, handle)
    try:
        return mutation_model_reads.contact_page(run, handle, structure=structure, page=page, page_size=page_size)
    except mutation_model_reads.ReadInvalid as exc:
        raise _read_invalid(exc) from exc
    except mutation_model_reads.MutationEvidenceError as exc:
        raise _mutation_model_evidence_error(exc) from exc


@app.get("/runs/{rid}/mutation_models/{handle:path}/structure")
def mutation_model_structure(rid: str, handle: str, request: Request, side: str) -> Response:
    """One structure's stored mmCIF bytes, byte for byte (SHA-256 checked against the model)."""
    _only_query(request, {"side"})
    run = _run(rid)
    _mutation_model(run, handle)
    try:
        raw, filename = mutation_model_reads.structure_download(run, handle, side)
    except mutation_model_reads.ReadInvalid as exc:
        raise _read_invalid(exc) from exc
    except mutation_model_reads.MutationEvidenceError as exc:
        raise _mutation_model_evidence_error(exc) from exc
    return Response(raw, media_type="chemical/x-mmcif", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@app.get("/runs/{rid}/mutation_models/{handle:path}/docking_pairs")
def mutation_model_docking_pairs(rid: str, handle: str, request: Request) -> dict[str, Any]:
    """Same-condition M18 docking on the two structures, every condition group listed; scores only when both
    sides are published results (spec 7)."""
    _only_query(request, set())
    run = _run(rid)
    _mutation_model(run, handle)
    try:
        return mutation_model_reads.docking_pairs(run, handle)
    except mutation_model_reads.MutationEvidenceError as exc:
        raise _mutation_model_evidence_error(exc) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid docking job record"}) from exc


@app.get("/runs/{rid}/mutation_models/{handle:path}")
def mutation_model_detail(rid: str, handle: str, request: Request) -> dict[str, Any]:
    """One validated model without contact rows, final_bonds or atom_mapping."""
    _only_query(request, set())
    run = _run(rid)
    meta = _mutation_model(run, handle)
    try:
        return {**mutation_model_reads.model_detail(run, handle), "meta": meta}
    except mutation_model_reads.MutationEvidenceError as exc:
        raise _mutation_model_evidence_error(exc) from exc


# ----------------------------------------------------------------- M19 batch limit raise (human UI action only)
@app.post("/runs/{rid}/docking/batches/limit_approval")
async def docking_batch_limit_approval(rid: str, request: Request) -> Any:
    """Spec 6.3: the person's explicit approval to raise the run limits by this batch's shortfall (body = the batch
    request). Not a tool, plan or workflow step, model command or loop action; no other path calls it."""
    _only_query(request, set())
    args = _chemical_json(await _bounded_chemical_body(request, CHEMICAL_REQUEST_LIMIT))
    try:
        return await run_in_threadpool(lambda: docking_batch_jobs.limit_approval(_run(rid), args))
    except ToolFailure as error:
        return _tool_error(error)
    except RunCancelled:
        return JSONResponse(status_code=409, content={"ok": False, "error": "cancelled", "message": "run cancelled"})


# ----------------------------------------------------------------- M22 GA limit raise (human UI action only)
@app.post("/runs/{rid}/ligand/ga/limit_approval")
async def ligand_ga_limit_approval(rid: str, request: Request) -> Any:
    """Spec 6: the person's explicit approval to raise the run limits by this GA's shortfall (body = the GA job
    arguments). Not a tool, plan or workflow step, model command or loop action; no other path calls it."""
    _only_query(request, set())
    args = _chemical_json(await _bounded_chemical_body(request, CHEMICAL_REQUEST_LIMIT))
    try:
        return await run_in_threadpool(lambda: ligand_ga_jobs.limit_approval(_run(rid), args))
    except ToolFailure as error:
        return _tool_error(error)
    except RunCancelled:
        return JSONResponse(status_code=409, content={"ok": False, "error": "cancelled", "message": "run cancelled"})


# ----------------------------------------------------------------- M23 sequence GA limit raise (human UI action only)
@app.post("/runs/{rid}/sequence_ga/limit_approval")
async def sequence_ga_limit_approval(rid: str, request: Request) -> Any:
    """Spec 7: the person's explicit approval to raise the run limits by this sequence GA's shortfall (body = the GA
    job arguments). Not a tool, plan or workflow step, model command or loop action; no other path calls it."""
    _only_query(request, set())
    args = _chemical_json(await _bounded_chemical_body(request, CHEMICAL_REQUEST_LIMIT))
    try:
        return await run_in_threadpool(lambda: sequence_ga_jobs.limit_approval(_run(rid), args))
    except ToolFailure as error:
        return _tool_error(error)
    except RunCancelled:
        return JSONResponse(status_code=409, content={"ok": False, "error": "cancelled", "message": "run cancelled"})


# ----------------------------------------------------------------- M19 batch reads (no event, job, tool or engine)
@app.post("/runs/{rid}/docking/batches/preflight")
async def docking_batch_preflight(rid: str, request: Request) -> dict[str, Any]:
    """Spec 6.2: admission, reuse per row, N, need, remaining budget, shortfall, B1 and the M18 sentences for a batch
    request (body = the batch job arguments). A read: no event, job, tool, reservation or limit change."""
    _only_query(request, set())
    args = _chemical_json(await _bounded_chemical_body(request, CHEMICAL_REQUEST_LIMIT))
    run = _run(rid)
    return await run_in_threadpool(lambda: docking_batch_reads.preflight(run, args))


@app.get("/runs/{rid}/docking/batches")
def docking_batches(rid: str, request: Request, offset: int = Query(0, ge=0),
                    limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    _only_query(request, {"offset", "limit"})
    run = _run(rid)
    try:
        return docking_batch_reads.list_summaries(run, offset, limit)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid docking batch record"}) from exc


@app.get("/runs/{rid}/docking/batches/detail")
def docking_batch_detail(rid: str, request: Request, handle: str) -> dict[str, Any]:
    """One validated batch summary and its rows; per-row results open in the M18 /docking/results/* reads."""
    _only_query(request, {"handle"})
    run = _run(rid)
    meta = _object(run, handle)
    if (meta["kind"], meta["schema"]) != (docking_batch_reads.SUMMARY, docking_batch_reads.SUMMARY_SCHEMA):
        raise HTTPException(422, detail={"error": "input_invalid", "message": "handle is not a docking_batch_result"})
    try:
        return {**docking_batch_reads.summary_detail(run, handle), "meta": meta}
    except docking_batch_jobs.DockingBatchEvidenceError as exc:
        raise HTTPException(422, detail={"error": "method_evidence_invalid",
                                         "message": "invalid docking batch evidence"}) from exc


# ----------------------------------------------------------------- M22 GA reads (no event, job, tool or engine)
@app.post("/runs/{rid}/ligand/ga/preflight")
async def ligand_ga_preflight(rid: str, request: Request) -> dict[str, Any]:
    """Spec 6, 8: admission, pool counts, reusable candidates, reserved_units, need, remaining budget, shortfall,
    full_run_may_be_partial and G1 for a GA request (body = the GA job arguments). A read: no event, job, tool,
    reservation or limit change."""
    _only_query(request, set())
    args = _chemical_json(await _bounded_chemical_body(request, CHEMICAL_REQUEST_LIMIT))
    run = _run(rid)
    return await run_in_threadpool(lambda: ligand_ga_reads.preflight(run, args))


@app.get("/runs/{rid}/ligand/ga/results")
def ligand_ga_results(rid: str, request: Request, offset: int = Query(0, ge=0),
                      limit: int = Query(ligand_ga_reads.LIST_LIMIT_DEFAULT, ge=1,
                                         le=ligand_ga_reads.LIST_LIMIT_MAX)) -> dict[str, Any]:
    """This run's GA summaries, newest first; each row re-validated."""
    _only_query(request, {"offset", "limit"})
    run = _run(rid)
    try:
        return ligand_ga_reads.list_summaries(run, offset, limit)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid ligand GA record"}) from exc


def _ligand_ga_summary(run: Run, handle: str) -> dict[str, Any]:
    meta = _object(run, handle)
    if (meta["kind"], meta["schema"]) != (ligand_ga_reads.SUMMARY, ligand_ga_reads.SUMMARY_SCHEMA):
        raise HTTPException(422, detail={"error": "input_invalid", "message": "handle is not a ligand_ga_result"})
    return meta


def _ligand_ga_evidence_error(exc: Exception) -> HTTPException:
    return HTTPException(422, detail={"error": "method_evidence_invalid", "message": "invalid ligand GA evidence"})


# The handle (obj://<run>/<kind>/<sha>) contains slashes: the sub-resource route is registered before the detail.
@app.get("/runs/{rid}/ligand/ga/results/{handle:path}/individual")
def ligand_ga_individual(rid: str, handle: str, request: Request, candidate_id: str | None = None) -> dict[str, Any]:
    """One individual (by candidate id) and the M18 detail read of its standalone result."""
    _only_query(request, {"candidate_id"})
    run = _run(rid)
    _ligand_ga_summary(run, handle)
    try:
        return ligand_ga_reads.individual(run, handle, candidate_id)
    except ligand_ga_reads.ReadInvalid as exc:
        raise _read_invalid(exc) from exc
    except (ligand_ga_reads.LigandGaEvidenceError, docking_bundle.DockingEvidenceError) as exc:
        raise _ligand_ga_evidence_error(exc) from exc


@app.get("/runs/{rid}/ligand/ga/results/{handle:path}")
def ligand_ga_detail(rid: str, handle: str, request: Request) -> dict[str, Any]:
    """One validated GA summary with its generations; individual results open in the M18 /docking/results/* reads."""
    _only_query(request, set())
    run = _run(rid)
    meta = _ligand_ga_summary(run, handle)
    try:
        return {**ligand_ga_reads.summary_detail(run, handle), "meta": meta}
    except ligand_ga_reads.LigandGaEvidenceError as exc:
        raise _ligand_ga_evidence_error(exc) from exc


# ---------------------------------------------------------------- M23 sequence GA reads (no event, job, tool or engine)
@app.post("/runs/{rid}/sequence_ga/preflight")
async def sequence_ga_preflight(rid: str, request: Request) -> dict[str, Any]:
    """Spec 9: admission (steps 1-8, refusals answered 200), space, projected heavy atoms, reuse, reserved figures,
    need, remaining budget, shortfall, full_run_may_be_partial and S1/S4-S6 for a sequence GA request (body = the GA
    job arguments). A read: no event, job, tool, reservation or limit change."""
    _only_query(request, set())
    args = _chemical_json(await _bounded_chemical_body(request, CHEMICAL_REQUEST_LIMIT))
    run = _run(rid)
    return await run_in_threadpool(lambda: sequence_ga_reads.preflight(run, args))


@app.get("/runs/{rid}/sequence_ga/results")
def sequence_ga_results(rid: str, request: Request, offset: int = Query(0, ge=0),
                        limit: int = Query(sequence_ga_reads.LIST_LIMIT_DEFAULT, ge=1,
                                           le=sequence_ga_reads.LIST_LIMIT_MAX)) -> dict[str, Any]:
    """This run's sequence GA summaries, newest first; each row re-validated (one event-log read)."""
    _only_query(request, {"offset", "limit"})
    run = _run(rid)
    try:
        return sequence_ga_reads.list_summaries(run, offset, limit)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid sequence GA record"}) from exc


def _sequence_ga_summary(run: Run, handle: str) -> dict[str, Any]:
    meta = _object(run, handle)
    if (meta["kind"], meta["schema"]) != (sequence_ga_reads.SUMMARY, sequence_ga_reads.SUMMARY_SCHEMA):
        raise HTTPException(422, detail={"error": "input_invalid", "message": "handle is not a sequence_ga_result"})
    return meta


def _sequence_ga_evidence_error(exc: Exception) -> HTTPException:
    return HTTPException(422, detail={"error": "method_evidence_invalid", "message": "invalid sequence GA evidence"})


def _sequence_ga_row_unknown(exc: Exception) -> HTTPException:
    return HTTPException(404, detail={"error": "not_found", "message": str(exc)})


# The handle (obj://<run>/<kind>/<sha>) contains slashes: the sub-resource routes (/individual, /structure) are
# registered before the detail route.
@app.get("/runs/{rid}/sequence_ga/results/{handle:path}/individual")
def sequence_ga_individual(rid: str, handle: str, request: Request, key: str | None = None) -> dict[str, Any]:
    """One individual (key ``12-57-203``) or the wild-type reference row (``wild_type``): stored row, stored model
    without atom and bond rows, appearances and the M18 detail read of its result."""
    _only_query(request, {"key"})
    run = _run(rid)
    _sequence_ga_summary(run, handle)
    try:
        return sequence_ga_reads.individual(run, handle, key)
    except sequence_ga_reads.ReadInvalid as exc:
        raise _read_invalid(exc) from exc
    except sequence_ga_reads.RowUnknown as exc:
        raise _sequence_ga_row_unknown(exc) from exc
    except (sequence_ga_reads.SequenceGaEvidenceError, docking_bundle.DockingEvidenceError) as exc:
        raise _sequence_ga_evidence_error(exc) from exc


@app.get("/runs/{rid}/sequence_ga/results/{handle:path}/structure")
def sequence_ga_structure(rid: str, handle: str, request: Request, key: str | None = None) -> Response:
    """The stored mmCIF bytes of one row's model, byte for byte (SHA-256 and handle checked)."""
    _only_query(request, {"key"})
    run = _run(rid)
    _sequence_ga_summary(run, handle)
    try:
        raw, filename = sequence_ga_reads.structure_download(run, handle, key)
    except sequence_ga_reads.ReadInvalid as exc:
        raise _read_invalid(exc) from exc
    except sequence_ga_reads.RowUnknown as exc:
        raise _sequence_ga_row_unknown(exc) from exc
    except sequence_ga_reads.SequenceGaEvidenceError as exc:
        raise _sequence_ga_evidence_error(exc) from exc
    return Response(raw, media_type="chemical/x-mmcif", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@app.get("/runs/{rid}/sequence_ga/results/{handle:path}")
def sequence_ga_detail(rid: str, handle: str, request: Request) -> dict[str, Any]:
    """One validated sequence GA summary with its generations and its reference row; individual results open in the
    M18 /docking/results/* reads."""
    _only_query(request, set())
    run = _run(rid)
    meta = _sequence_ga_summary(run, handle)
    try:
        return {**sequence_ga_reads.summary_detail(run, handle), "meta": meta}
    except sequence_ga_reads.SequenceGaEvidenceError as exc:
        raise _sequence_ga_evidence_error(exc) from exc


# ----------------------------------------------------------------- M24 JEV science sends (one human-approved send route)
JEV_REQUEST_LIMIT = jev_constants.MAX_SEND_REQUEST_BYTES   # every /jev POST body; 4 KiB is the approval bound
JEV_BUSY_MESSAGE = "the run is busy with another operation; nothing was approved or sent"
JEV_MEDIA_TYPE_MESSAGE = "expected Content-Type application/json; the body was not read and nothing was recorded"
JEV_INTERNAL_MESSAGE = "the science send stopped on an internal error; its record in GET /jev/sends shows what was kept"
JEV_CAPABILITY_REASONS = {
    "tool_unavailable": "투영 도구 build_jev_projection이 등록·노출되어 있지 않다.",
    "missing_configuration": "과학 전송의 요청·응답 모델·provider pin이 게이트 값과 다르다.",
}


class JevConsentRequest(BaseModel):
    enabled: bool
    model_config = {"extra": "forbid", "strict": True}


class JevPreviewRequest(BaseModel):
    projection: str
    model_config = {"extra": "forbid", "strict": True}


class JevSendRequest(BaseModel):
    send_id: str
    projection: str
    body_sha256: str
    confirm: str
    model_config = {"extra": "forbid", "strict": True}


def _jev_choice_capability() -> dict[str, Any]:
    """Local conditions only: the projection tool is registered and exposed, and the science pins equal the gate's
    (the gate's own check). No credential and no run consent is read; a missing key surfaces at send time as the
    ``missing_credential`` refusal."""
    if jev_constants.TOOL not in SUPPORTED_TOOLS or jev_constants.TOOL not in REGISTRY.specs:
        reason = "tool_unavailable"
    elif not egress_science._pins_match({"model": jev_projection.REQUEST_MODEL, "provider": jev_projection.PROVIDER}):
        reason = "missing_configuration"
    else:
        return {"available": True, "reason_code": None, "reason": None}
    return {"available": False, "reason_code": reason, "reason": JEV_CAPABILITY_REASONS[reason]}


async def _jev_request(request: Request, model: type[BaseModel]) -> Any:
    """No query parameter, Content-Type application/json (415 before the body is read: a cross-site simple POST
    cannot carry it), a body of at most 4 KiB (413), one JSON object with exactly the model's typed keys (422)."""
    _only_query(request, set())
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, detail={"error": "unsupported_media_type", "message": JEV_MEDIA_TYPE_MESSAGE})
    raw = _chemical_json(await _bounded_chemical_body(request, JEV_REQUEST_LIMIT))
    try:
        return model.model_validate(raw)
    except PydanticValidationError as exc:
        raise HTTPException(422, detail={"error": "input_invalid", "message": (
            f"expected exactly the keys {sorted(model.model_fields)} with their documented types")}) from exc


def _jev_error(error: jev_sends.JevSendError) -> HTTPException:
    return HTTPException(error.http_status, detail={"error": error.code, "message": error.message, **error.detail})


class _JevReadView:
    """One event-log read for a JEV read: ``events.read()`` returns that one list (the M23 read-snapshot precedent)."""

    def __init__(self, run: Run) -> None:
        self.store, self.run_id, self.run_dir = run.store, run.run_id, run.run_dir
        self._events = list(run.events.read())
        self.events = self

    def read(self) -> list[dict[str, Any]]:
        return self._events


@app.get("/runs/{rid}/jev/status")
def jev_status(rid: str, request: Request) -> dict[str, Any]:
    """``jev_status@1``: consent, cap use, budget, the two question ids, a send in progress. No event, no key."""
    _only_query(request, set())
    run = _run(rid)
    return jev_sends.status_for(run, list(run.events.read()))


@app.post("/runs/{rid}/jev/consent")
async def jev_consent(rid: str, request: Request) -> dict[str, Any]:
    """The run-level science consent: the only writer of ``jev_science_consent_changed`` (412 ``dry_run`` when turning
    it on in a dry-run run). The viewer mode, viewer consent and every other gate are untouched."""
    body = await _jev_request(request, JevConsentRequest)
    try:
        return await run_in_threadpool(lambda: jev_sends.set_consent(_run(rid), body.enabled))
    except jev_sends.JevSendError as exc:
        raise _jev_error(exc) from exc


@app.post("/runs/{rid}/jev/preview")
async def jev_preview(rid: str, request: Request) -> dict[str, Any]:
    """``jev_preview@1``: the exact body string, its SHA-256 and bytes, the alias table (local only), the reservation,
    the cap use and every refusal that holds now. A read: no event, tool, job or external request. A loop projection
    (M25) adds ``loop`` and ``loop_blocks`` from its loop record (one log read for both)."""
    body = await _jev_request(request, JevPreviewRequest)

    def read() -> dict[str, Any]:
        run = _run(rid)
        return jev_sends.preview_for(run, body.projection, list(run.events.read()))

    try:
        return await run_in_threadpool(read)
    except jev_sends.JevSendError as exc:
        raise _jev_error(exc) from exc
    except jev_loops.LoopRecordInvalid as exc:   # a loop event order no loop route writes: fixed body, no content
        raise HTTPException(500, detail={"error": "internal_error", "message": JEV_LOOP_INTERNAL_MESSAGE}) from exc
    except (KeyError, TypeError, ValueError) as exc:   # a stored object of the loop that does not read back
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid JEV loop record"}) from exc


@app.post("/runs/{rid}/jev/sends")
async def jev_send_create(rid: str, request: Request) -> Any:
    """The person's approval of one exact projection body and its one send (spec 5): the only caller of
    ``jev_sends.run_send``, so the only path to ``EgressGate.request_science``. Not a tool, plan or workflow step,
    model command or job. Refusals and failures answer 200 with their ``jev_send@1`` record. A ``jev_loop_projection@1``
    (M25) takes the same call; its loop send check refuses with 409 ``loop_send_invalid`` (``JevSendError``)."""
    body = await _jev_request(request, JevSendRequest)
    run = _run(rid)
    try:
        return await jev_sends.run_send(run, SCIENCE_GATE, send_id=body.send_id, projection=body.projection,
                                        body_sha256=body.body_sha256, confirm=body.confirm)
    except jev_sends.JevSendError as exc:
        raise _jev_error(exc) from exc
    except ToolFailure as exc:
        if exc.detail.get("busy"):
            raise HTTPException(503, detail={"error": "busy", "message": JEV_BUSY_MESSAGE}) from exc
        return _tool_error(exc)
    except jev_loops.LoopRecordInvalid as exc:   # M25: a loop event order no loop route writes; nothing was sent
        raise HTTPException(500, detail={"error": "internal_error", "message": JEV_LOOP_INTERNAL_MESSAGE}) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt",
                                         "message": "the science send could not be recorded"}) from exc
    except OSError as exc:
        # A disk error while recording, or the gate's post-approval check (PermissionError is an OSError): one fixed
        # body, never the exception text. The send record keeps the replay rule (delivery_unknown /
        # outcome_not_recorded).
        raise HTTPException(500, detail={"error": "internal_error", "message": JEV_INTERNAL_MESSAGE}) from exc


@app.get("/runs/{rid}/jev/sends")
def jev_send_list(rid: str, request: Request) -> list[dict[str, Any]]:
    """This run's sends, oldest first; each row a ``jev_send@1`` derived from events only (one log read)."""
    _only_query(request, set())
    run = _run(rid)
    try:
        return jev_sends.list_sends(list(run.events.read()))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid science send record"}) from exc


@app.get("/runs/{rid}/jev/sends/{send_id}")
def jev_send_detail(rid: str, send_id: str, request: Request) -> dict[str, Any]:
    """One ``jev_send@1`` plus, when completed, its ``jev_choice@1`` proposal re-validated against the projection and
    the candidate set (``choice``, ``local_display``; null otherwise). One log read, no event."""
    _only_query(request, set())
    view = _JevReadView(_run(rid))
    try:
        record = jev_sends.send_record(view.read(), send_id)
    except jev_sends.JevSendError as exc:
        raise _jev_error(exc) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid science send record"}) from exc
    choice = None
    if record["status"] == "completed":
        try:
            choice = (jev_sends.load_loop_choice(view, record["choice_handle"], record["send_id"]) if "loop" in record
                      else jev_sends.load_choice(view, record["choice_handle"]))   # M25: a loop send's own proposal
        except (jev_sends.ChoiceInvalid, jev_sends.JevSendError) as exc:
            raise HTTPException(422, detail={"error": "method_evidence_invalid",
                                             "message": "the stored JEV choice does not validate"}) from exc
    return {**record, "choice": choice, "local_display": None if choice is None else choice["answer"]["local_display"]}


# ----------------------------------------------------------------- M25 JEV design loops (record and creation)
JEV_LOOP_BUSY_MESSAGE = "the run is busy with another operation; nothing was recorded"
JEV_LOOP_INTERNAL_MESSAGE = "the JEV loop record could not be derived from this run's events; nothing was changed"


def _jev_loop_capability(methods: dict[str, Any]) -> dict[str, Any]:
    """``methods.jev_loop``: per branch, the loop projection tool exposed, the science pins equal to the gate's (the
    M24 check), then the branch's engines (the creation admission's engine order). Reasons only, no numbers."""
    tool = jev_loop_constants.TOOL
    return jev_loop_store.capability(
        methods["ligand_docking"], methods["mutation_model"],
        tool_exposed=tool in SUPPORTED_TOOLS and tool in REGISTRY.specs,
        pins_match=egress_science._pins_match({"model": jev_projection.REQUEST_MODEL,
                                               "provider": jev_projection.PROVIDER}))


async def _jev_loop_request(request: Request, limit: int) -> dict[str, Any]:
    """No query parameter, Content-Type application/json (415 before the body is read, as the M24 posts), a body of
    at most ``limit`` bytes (413) and one JSON object (422). Its keys are the loop admission's."""
    _only_query(request, set())
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, detail={"error": "unsupported_media_type", "message": JEV_MEDIA_TYPE_MESSAGE})
    return _chemical_json(await _bounded_chemical_body(request, limit))


@app.post("/runs/{rid}/jev_loops")
async def jev_loop_create(rid: str, request: Request) -> Any:
    """``jev_loop@1`` of a new loop (spec 3.1): the closed admission in order, then one ``jev_loop_created`` event; the
    same loop_id and request answers the existing record. No job, tool, external request or budget change."""
    body = await _jev_loop_request(request, jev_loop_constants.MAX_CREATE_REQUEST_BYTES)
    run = _run(rid)
    send_active = jev_sends.send_active(rid)
    try:
        return await run_in_threadpool(lambda: jev_loop_store.create(run, body, send_active=send_active))
    except jev_loop_store.LoopRequestError as exc:
        raise HTTPException(exc.http_status, detail=exc.detail) from exc
    except ToolFailure as exc:
        if exc.detail.get("busy"):
            raise HTTPException(503, detail={"error": "busy", "message": JEV_LOOP_BUSY_MESSAGE}) from exc
        return _tool_error(exc)
    except jev_loops.LoopRecordInvalid as exc:   # an event order no loop route writes: fixed body, no content
        raise HTTPException(500, detail={"error": "internal_error", "message": JEV_LOOP_INTERNAL_MESSAGE}) from exc
    except (KeyError, TypeError, ValueError) as exc:   # a loop or stored record that does not read back
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid JEV loop record"}) from exc


JEV_LOOP_START_RACE = {"global_concurrency_busy", "global_job_cleanup_pending", "global_job_ledger_unavailable"}


def _jev_loop_compute(run: Run, loop_id: str, body: Any, send_active: bool) -> dict[str, Any]:
    """Spec 6.1 up to the submission, under the run owner: the request shape, the loop read and admission, the step's
    M18 / M21 job admission, the approval event, then ``JobQueue.submit`` of the standalone request (outside the
    transition lock the submission takes itself). Returns {"job_id", "start"}: the job the route starts after the
    owner is released. While another request holds the owner only an answer that writes and starts nothing is given
    (``jev_loop_store.compute_when_busy``); the rest is the owner's busy failure, nothing written."""
    request = jev_loop_store.action_request(body, jev_loop_constants.COMPUTE_KEYS)
    with ExitStack() as stack:
        try:
            stack.enter_context(run._owner())
        except ToolFailure as busy:
            if busy.detail.get("busy") is not True:
                raise
            return jev_loop_store.compute_when_busy(run, loop_id, request, send_active=send_active, busy=busy)
        view, budget = jev_loop_store.locked_view(run)
        state, decision = jev_loop_store.compute_decision(view, loop_id, request, budget=budget,
                                                          send_active=send_active)
        if decision["outcome"] == "idempotent":       # the same step again: no event, no job (spec 6.1)
            return {"job_id": decision["job_id"], "start": decision["start"]}
        job = jev_loop_store.step_job(run, state, decision)
        jev_loop_store.write_approval(run, state, decision, job)
        if job is None:                                # a stored model adopted: no job, no unit
            return {"job_id": None, "start": False}
        submitted = JobQueue(run).submit(job["protocol"], job["args"], timeout_s=job["timeout_s"])
        return {"job_id": submitted["job_id"], "start": submitted["status"] == "queued"}


@app.post("/runs/{rid}/jev_loops/{loop_id}/compute")
async def jev_loop_compute(rid: str, loop_id: str, request: Request) -> Any:
    """The person's start of one loop step (spec 6.1): ``jev_loop_compute_approved`` first, then the standalone M18 /
    M21 job with the arguments and call key a standalone submission gets, started like ``POST /jobs/{id}/start``
    after the run owner is released (the response waits for the job; reads go on without the lock). The first
    expensive-call approval answers 200 with the record (``current.job.start_blocked``; the person approves with
    ``POST /jobs/approve`` and presses again). Every other start failure answers as the job start route does; the
    same press of a queued or claimed (blocked) job starts it again. Calls no tool, send, approval or limit path;
    nothing runs in the background."""
    body = await _jev_loop_request(request, jev_loop_constants.MAX_ACTION_REQUEST_BYTES)
    run = _run(rid)
    send_active = jev_sends.send_active(rid)
    try:
        step = await run_in_threadpool(lambda: _jev_loop_compute(run, loop_id, body, send_active))
    except jev_loop_store.LoopRequestError as exc:
        raise HTTPException(exc.http_status, detail=exc.detail) from exc
    except ToolFailure as exc:
        if exc.detail.get("busy"):
            raise HTTPException(503, detail={"error": "busy", "message": JEV_LOOP_BUSY_MESSAGE}) from exc
        return _tool_error(exc)        # the M18 / M21 job admission refusal as it is; nothing was written
    except jev_loops.LoopRecordInvalid as exc:   # an event order no loop route writes: fixed body, no content
        raise HTTPException(500, detail={"error": "internal_error", "message": JEV_LOOP_INTERNAL_MESSAGE}) from exc
    except (KeyError, TypeError, ValueError) as exc:   # a loop or stored record that does not read back
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid JEV loop record"}) from exc
    if step["start"]:
        try:
            await run_in_threadpool(lambda: JobQueue(run).start(
                step["job_id"], owner_active=lambda eid: analysis_executions.execution_active(run, eid)))
        except ApprovalRequired as exc:
            if exc.gate != "expensive_first_call":      # a budget checkpoint: as the job start route answers it
                return JSONResponse(status_code=409, content={"ok": False, "approval": {
                    "gate": exc.gate, "tool": exc.tool, "reason": exc.reason}})
            # spec 6.1: 200 and the record, whose current.job shows the wait for the first expensive-call approval
        except RunCancelled:
            return JSONResponse(status_code=409, content={"ok": False, "error": "cancelled",
                                                          "message": "run cancelled"})
        except ToolFailure as error:
            if error.detail.get("reason_code") in JEV_LOOP_START_RACE:
                return JSONResponse(status_code=409, content={"ok": False, **error.to_dict()})
            return _tool_error(error)
    return await run_in_threadpool(lambda: _jev_loop_read(rid, request, lambda view, budget, active: (
        jev_loop_store.read_loop(view, loop_id, budget=budget, send_active=active).record)))


@app.post("/runs/{rid}/jev_loops/{loop_id}/abandon_docking")
async def jev_loop_abandon_docking(rid: str, loop_id: str, request: Request) -> Any:
    """The person's decision not to dock the modelled candidate of the iteration (spec 6.3): one
    ``jev_loop_docking_abandoned`` event, the candidate ``not_run``, the iteration ended. No job, tool or send."""
    body = await _jev_loop_request(request, jev_loop_constants.MAX_ACTION_REQUEST_BYTES)
    run = _run(rid)
    send_active = jev_sends.send_active(rid)
    try:
        return await run_in_threadpool(lambda: jev_loop_store.abandon_docking(run, loop_id, body,
                                                                             send_active=send_active))
    except jev_loop_store.LoopRequestError as exc:
        raise HTTPException(exc.http_status, detail=exc.detail) from exc
    except ToolFailure as exc:
        if exc.detail.get("busy"):
            raise HTTPException(503, detail={"error": "busy", "message": JEV_LOOP_BUSY_MESSAGE}) from exc
        return _tool_error(exc)
    except jev_loops.LoopRecordInvalid as exc:   # an event order no loop route writes: fixed body, no content
        raise HTTPException(500, detail={"error": "internal_error", "message": JEV_LOOP_INTERNAL_MESSAGE}) from exc
    except (KeyError, TypeError, ValueError) as exc:   # a loop or stored record that does not read back
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid JEV loop record"}) from exc


@app.post("/runs/{rid}/jev_loops/{loop_id}/end")
async def jev_loop_end(rid: str, loop_id: str, request: Request) -> Any:
    """The person's end of a loop (spec 8.1): the refusals in order, the end reason, the summary
    ``jev_loop_result@1`` stored first and then ``jev_loop_ended``. No job, tool, send or limit change."""
    body = await _jev_loop_request(request, jev_loop_constants.MAX_ACTION_REQUEST_BYTES)
    run = _run(rid)
    send_active = jev_sends.send_active(rid)
    try:
        return await run_in_threadpool(lambda: jev_loop_store.end_loop(run, loop_id, body, send_active=send_active))
    except jev_loop_store.LoopRequestError as exc:
        raise HTTPException(exc.http_status, detail=exc.detail) from exc
    except ToolFailure as exc:
        if exc.detail.get("busy"):
            raise HTTPException(503, detail={"error": "busy", "message": JEV_LOOP_BUSY_MESSAGE}) from exc
        return _tool_error(exc)
    except jev_loops.LoopRecordInvalid as exc:   # an event order no loop route writes: fixed body, no content
        raise HTTPException(500, detail={"error": "internal_error", "message": JEV_LOOP_INTERNAL_MESSAGE}) from exc
    except (KeyError, TypeError, ValueError) as exc:   # a loop or stored record (its summary) that does not read back
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid JEV loop record"}) from exc


def _jev_loop_read(rid: str, request: Request, read: Any) -> Any:
    """One loop read: no run lock, ONE event-log read (``LoopReadView``), nothing written. ``send_active`` is this
    process's in-flight science send (the loop modules never import the send module). A record read has no
    preview, so ``send_reservation`` is None; the preview of a loop projection carries the record's send-side amounts
    derived with its reservation (``jev_sends.preview_for``)."""
    _only_query(request, set())
    run = _run(rid)
    view = jev_loop_store.LoopReadView(run)
    budget = jev_loop_store.remaining_budget(run.budget_snapshot())
    try:
        return read(view, budget, jev_sends.send_active(rid))
    except jev_loops.LoopNotFound as exc:
        error = jev_loop_store.LoopRequestError("loop_not_found", "no such loop in this run", 404)
        raise HTTPException(404, detail=error.detail) from exc
    except jev_loops.LoopRecordInvalid as exc:   # an event order no loop route writes: fixed body, no content
        raise HTTPException(500, detail={"error": "internal_error", "message": JEV_LOOP_INTERNAL_MESSAGE}) from exc
    except (KeyError, TypeError, ValueError) as exc:   # a stored object of the loop that does not read back
        raise HTTPException(409, detail={"error": "run_corrupt", "message": "invalid JEV loop record"}) from exc


@app.get("/runs/{rid}/jev_loops")
def jev_loop_list(rid: str, request: Request) -> list[dict[str, Any]]:
    """This run's loops, newest first: one row each (spec 3.2), every loop derived and checked from one log read."""
    return _jev_loop_read(rid, request, lambda view, budget, active: jev_loop_store.list_loops(
        view, budget=budget, send_active=active))


@app.get("/runs/{rid}/jev_loops/{loop_id}")
def jev_loop_detail(rid: str, loop_id: str, request: Request) -> dict[str, Any]:
    """``jev_loop@1`` of one loop (404 ``loop_not_found`` when this run has none with that id)."""
    return _jev_loop_read(rid, request, lambda view, budget, active: jev_loop_store.read_loop(
        view, loop_id, budget=budget, send_active=active).record)


@app.get("/runs/{rid}/interface_sasa")
def interface_sasa(rid: str, handle: str) -> dict[str, Any]:
    run = _run(rid)
    try:
        data, _ = validated_sasa(run.store, handle)
        return {"meta": _object(run, handle), "result": data}
    except (EvidenceError, KeyError, ValueError) as exc:
        raise HTTPException(422, detail={"error": "method_evidence_invalid", "message": str(exc)}) from exc


@app.get("/runs/{rid}/openmm_minimization")
def openmm_minimization(rid: str, handle: str) -> dict[str, Any]:
    run = _run(rid)
    try:
        return {"meta": _object(run, handle), "result": validated_openmm(run, handle)}
    except (EvidenceError, KeyError, ValueError) as exc:
        raise HTTPException(422, detail={"error": "method_evidence_invalid", "message": str(exc)}) from exc


def _pocket_evidence_error(exc: Exception) -> HTTPException:
    return HTTPException(422, detail={"error": "method_evidence_invalid",
                                      "message": str(exc) or "invalid pocket evidence"})


@app.get("/runs/{rid}/pockets/preflight")
def pockets_preflight(rid: str, structure: str,
                      chains: Annotated[list[str] | None, Query()] = None) -> dict[str, Any]:
    """Read-only projection/capability/budget/retention summary; runs no tool, job or engine."""
    return pocket_preflight(_run(rid), structure, chains)


@app.get("/runs/{rid}/pockets")
def pockets(rid: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    return list_pocket_sets(_run(rid), offset, limit)


@app.get("/runs/{rid}/pockets/result")
def pocket_result(rid: str, handle: str) -> dict[str, Any]:
    run = _run(rid)
    try:
        return pocket_result_summary(run, handle)
    except (PocketEvidenceError, KeyError, ValueError, TypeError) as exc:
        raise _pocket_evidence_error(exc) from exc


@app.get("/runs/{rid}/pockets/geometry")
def pocket_geometry_read(rid: str, handle: str, rank: int = Query(..., ge=1, le=10_000)) -> dict[str, Any]:
    run = _run(rid)
    try:
        value = pocket_geometry(run, handle, rank)
    except (PocketEvidenceError, KeyError, ValueError, TypeError) as exc:
        raise _pocket_evidence_error(exc) from exc
    if value is None:
        raise HTTPException(404, detail={"error": "not_found", "message": "unknown pocket rank"})
    return value


@app.get("/runs/{rid}/structures/residues")
def residues(rid: str, handle: str) -> Any:
    run = _run(rid)
    meta = _object(run, handle)
    if meta["kind"] not in {"structure", "prepared_structure", "openmm_minimized_structure"}:
        raise HTTPException(422, detail={"error": "input_invalid", "message": "handle is not a structure"})
    try:
        if meta["kind"] == "openmm_minimized_structure":
            validated_minimized_structure(run, handle)
        return structure_residues(run.store, handle)
    except EvidenceError as exc:
        raise HTTPException(422, detail={"error": "method_evidence_invalid", "message": str(exc)}) from exc
    except ToolFailure as error:
        return _tool_error(error)
    except ValueError as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": str(exc)}) from exc


@app.get("/runs/{rid}/structures/atoms")
def atoms(rid: str, handle: str, offset: int = Query(0, ge=0),
          limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    run = _run(rid)
    try:
        catalog = atom_rows(run.store, handle)
        return {**{key: value for key, value in catalog.items() if key != "rows"},
                "offset": offset, "limit": limit, "rows": catalog["rows"][offset:offset + limit]}
    except ToolFailure as error:
        raise HTTPException(422, detail=error.to_dict()) from error
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": str(exc)}) from exc


@app.get("/runs/{rid}/objects/measurement")
def measurement(rid: str, handle: str) -> dict[str, Any]:
    run = _run(rid)
    meta = _object(run, handle)
    if (meta["kind"], meta["schema"]) not in {("atom_distance", "atom_distance@1"),
                                               ("rigid_alignment", "rigid_alignment@1")}:
        raise HTTPException(422, detail={"error": "input_invalid", "message": "not a measurement handle"})
    try:
        return {"meta": meta, "result": validated_comparison_result(run.store, handle)}
    except (EvidenceError, KeyError, ValueError) as exc:
        raise HTTPException(422, detail={"error": "method_evidence_invalid", "message": str(exc)}) from exc


@app.get("/runs/{rid}/structures/bytes")
def coordinates(rid: str, handle: str) -> Response:
    run = _run(rid)
    meta = _object(run, handle)
    if meta["kind"] not in {"structure", "prepared_structure", "openmm_minimized_structure"}:
        raise HTTPException(422, detail={"error": "input_invalid", "message": "handle is not a structure"})
    try:
        if meta["kind"] == "openmm_minimized_structure":
            validated_minimized_structure(run, handle)
        raw, fmt = structure_bytes(run.store, handle)
    except EvidenceError as exc:
        raise HTTPException(422, detail={"error": "method_evidence_invalid", "message": str(exc)}) from exc
    except ToolFailure as error:
        return _tool_error(error)
    except ValueError as exc:
        raise HTTPException(409, detail={"error": "run_corrupt", "message": str(exc)}) from exc
    return Response(raw, media_type="chemical/x-pdb" if fmt == "pdb" else "chemical/x-mmcif",
                    headers={"X-Structure-Format": fmt, "Cache-Control": "private, no-store"})
