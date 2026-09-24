"""Loopback workspace API. HTTP imports only run-scoped uploaded bytes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..core.errors import FailureClass, ToolFailure
from ..core.handles import RUN_ID_RE
from ..jobs.queue import JobQueue
from ..method_reports import build_method_report, saved_method_report, validated_sasa
from ..openmm_reports import build_openmm_report, saved_openmm_report, validated_minimized_structure, validated_openmm
from ..reports import EvidenceError, build_inspection_report, saved_report
from ..runtime.guards import LoopStop
from ..runtime.orchestrator import ApprovalRequired, Run, RunCancelled
from ..tools.energetic import protocol_capabilities
from ..tools.openmm_method import capability as openmm_capability
from ..tools.openmm_method import preflight as openmm_preflight
from ..tools.structural import structure_bytes, structure_residues, validate_upload
from ..workflows import InspectionRequest, inspect_complex
from ..workspace import build_registry, new_run

RUNS_DIR = Path(os.environ.get("MW_RUNS_DIR", "runs"))
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_RE = re.compile(r"upload://([A-Za-z0-9_-]+)/([0-9a-f]{64})\.(pdb|cif|mmcif)\Z")
SUPPORTED_TOOLS = {"load_structure", "prepare_structure", "compute_interactions", "compute_interface_sasa", "compile_state"}

app = FastAPI(title="ProtView local API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["*"], allow_headers=["*"])
REGISTRY = build_registry()
RUNS: dict[str, Run] = {}


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
    timeout_s: float = Field(default=60, gt=0, le=900, allow_inf_nan=False)
    model_config = {"extra": "forbid"}


class ReportRequest(BaseModel):
    interaction_handle: str
    prepared_handle: str | None = None
    model_config = {"extra": "forbid"}


class MethodReportRequest(BaseModel):
    result_handle: str
    model_config = {"extra": "forbid"}


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


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    """Keep private launch nonce, owner token and process identities off HTTP."""
    intent = job.get("dispatch_intent") or {}
    return {key: job.get(key) for key in ("job_id", "run_id", "root_call_id", "call_key",
                                         "protocol_id", "tool_id", "status", "created",
                                         "finished", "timeout_s", "attempt_id", "attempt_ordinal",
                                         "blocked_reason", "cancel_requested", "cleanup_status",
                                         "failure", "input_handles", "output_handles",
                                         "preparation_handle", "preparation_attempt_id")} | {"started": intent.get("ts"),
                                                                  "remaining_wall_s_at_dispatch":
                                                                      intent.get("remaining_wall_s")}


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
    return {key: meta[key] for key in ("handle", "kind", "schema", "fmt", "size", "produced_by",
                                        "summary", "null_result")}


@app.get("/capabilities")
def capabilities() -> dict[str, Any]:
    matrix = protocol_capabilities()
    try:
        from ..tools.sasa import engine_capability
        sasa = engine_capability()
    except (AttributeError, ImportError, OSError, PackageNotFoundError, RuntimeError, ToolFailure, ValueError) as exc:
        sasa = {"available": False, "reason_code": "engine_missing_or_invalid", "explanation": str(exc)}
    return {"mode": "local_only", "energy_protocols": matrix, "methods": {"interface_sasa": sasa, "openmm_protein_minimize": openmm_capability()}, "supported": {
        "upload": "local PDB/mmCIF, up to 25 MiB", "preparation": "model, altloc, water, hydrogen policies",
        "interactions": "heavy-atom geometric contacts in angstroms", "viewer_bytes": "local PDB/mmCIF",
        "jobs": "event-backed local job records and POSIX lifecycle supervision",
        "reports": "offline selected-interaction and interface-SASA evidence reports with Markdown and JSON downloads",
        "inspect_complex": "fixed local workflow over validated run calls"},
        "unavailable": {
            "remote_structure_lookup": "no M1 fetch adapter; local upload only",
            "hbond_or_affinity": "geometric proximity is not chemical or energetic validation",
            "prolif_plip": "adapters and mapping validation are not implemented",
            "pocket_detection": "no implemented adapter",
            **{f"energy_{name}": item["explanation"] for name, item in matrix["protocols"].items() if not item["available"]},
            "model_decisions": "internal Jev adapter requires explicit online run configuration and credentials; no public decision route"}}


@app.get("/tools")
def tools(levels: str = "L2,L4") -> list[dict[str, Any]]:
    selected = set(levels.split(","))
    records = [spec.model_dump() for spec in REGISTRY.visible(selected)
               if spec.name in SUPPORTED_TOOLS]
    if "L3" in selected:
        records.append({**REGISTRY.specs["openmm_protein_minimize"].model_dump(),
                        "execution_lane": "durable_job", "submit_protocol_id": "openmm_protein_minimize"})
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
        if kind == "interface_sasa":
            return build_method_report(run, body.result_handle)
        if kind == "openmm_minimization":
            return build_openmm_report(run, body.result_handle)
        raise EvidenceError("wrong_method_result_kind")
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
                    {"result_handle": e["result_handle"], "analysis_type": run.store.load(e["report_handle"])["analysis_type"]}),
                 "markdown_handle": e["markdown_handle"], "created_seq": e["seq"],
                 "snapshot_event_seq": e["snapshot_event_seq"]} for e in records]
    except (EvidenceError, KeyError, ValueError) as exc:
        raise HTTPException(422, detail={"error": "report_evidence_invalid", "message": str(exc)}) from exc


def _saved_any_report(run: Run, handle: str) -> dict[str, Any]:
    meta = run.store.meta(handle)
    if (meta["kind"], meta["schema"]) == ("report_manifest", "report_manifest@1"):
        return saved_report(run, handle)
    if (meta["kind"], meta["schema"]) == ("method_report_manifest", "method_report_manifest@1"):
        report = run.store.load(handle)
        if report.get("analysis_type") == "interface_sasa":
            return saved_method_report(run, handle)
        if report.get("analysis_type") == "openmm_protein_minimize":
            return saved_openmm_report(run, handle)
        raise EvidenceError("unknown_method_report_type")
    raise EvidenceError("wrong_report_kind")


@app.get("/runs/{rid}/reports/selected")
def report_detail(rid: str, handle: str) -> dict[str, Any]:
    try:
        return _saved_any_report(_run(rid), handle)
    except (EvidenceError, KeyError, ValueError) as exc:
        raise HTTPException(422, detail={"error": "report_evidence_invalid", "message": str(exc)}) from exc


@app.get("/runs/{rid}/reports/download")
def report_download(rid: str, handle: str, format: Literal["markdown", "json"] = "markdown") -> Response:
    try:
        result = _saved_any_report(_run(rid), handle)
    except (EvidenceError, KeyError, ValueError) as exc:
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
    if not any(e["type"] == "approval_requested" and e.get("gate") == "expensive_first_call"
               and e.get("tool") == "openmm_protein_minimize" for e in run.events.read()):
        raise HTTPException(412, detail={"error": "precondition", "message": "no pending OpenMM approval request"})
    run.approve("expensive_first_call", by="human_api")
    return {"approved": True, "budget": run.budget_snapshot()}


@app.get("/runs/{rid}/jobs")
def jobs(rid: str) -> list[dict[str, Any]]:
    return [_public_job(job) for job in JobQueue(_run(rid)).list()]


@app.get("/runs/{rid}/jobs/{job_id}")
def job_detail(rid: str, job_id: str) -> dict[str, Any]:
    try:
        return _public_job(JobQueue(_run(rid)).get(job_id))
    except KeyError as exc:
        raise HTTPException(404, detail={"error": "not_found", "message": "unknown job"}) from exc


@app.post("/runs/{rid}/jobs")
def submit_job(rid: str, body: JobSubmit) -> Any:
    try:
        result = JobQueue(_run(rid)).submit(body.protocol_id, body.args, timeout_s=body.timeout_s)
        return result if result.get("plan_only") else _public_job(result)
    except ToolFailure as error:
        return _tool_error(error)


@app.post("/runs/{rid}/jobs/{job_id}/start")
def start_job(rid: str, job_id: str) -> Any:
    try:
        return _public_job(JobQueue(_run(rid)).start(job_id))
    except KeyError as exc:
        raise HTTPException(404, detail={"error": "not_found", "message": "unknown job"}) from exc
    except ApprovalRequired as exc:
        return JSONResponse(status_code=409, content={"ok": False, "approval": {
            "gate": exc.gate, "tool": exc.tool, "reason": exc.reason}})
    except RunCancelled:
        return JSONResponse(status_code=409, content={"ok": False, "error": "cancelled", "message": "run cancelled"})
    except ToolFailure as error:
        return _tool_error(error)


@app.post("/runs/{rid}/jobs/{job_id}/retry")
def retry_job(rid: str, job_id: str) -> Any:
    try:
        return _public_job(JobQueue(_run(rid)).retry(job_id))
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
    selected = columns.split(",") if columns is not None else None
    try:
        rows = run.store.materialize(handle, selected, offset, limit)
        content = run.store.load(handle)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, detail={"error": "input_invalid", "message": str(exc)}) from exc
    total = len(content["rows"] if meta["kind"] == "interaction_set" else content)
    return {"meta": meta, "rows": rows, "total": total, "offset": offset, "limit": limit}


@app.get("/runs/{rid}/objects/meta")
def object_meta(rid: str, handle: str) -> dict[str, Any]:
    return _object(_run(rid), handle)


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
