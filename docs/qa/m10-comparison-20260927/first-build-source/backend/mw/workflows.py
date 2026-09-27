"""Finite, event-backed inspect_complex driver over Run.call."""
from __future__ import annotations

import fcntl
import hashlib
import os
import re
import threading
from contextlib import contextmanager
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .core.contracts import check_args
from .core.errors import FailureClass, ToolFailure
from .core.events import idempotency_key
from .core.handles import canonical_json
from .core.residue import ResidueRef
from .runtime.guards import LoopStop
from .runtime.orchestrator import ApprovalRequired, RunCancelled
from .tools.structural import structure_residues

_LOCAL_WORKFLOW_LOCKS: dict[str, threading.Lock] = {}
_LOCK_GUARD = threading.Lock()
VERSION = "inspect_complex@1"
UPLOAD_TOKEN_RE = re.compile(r"upload://([A-Za-z0-9_-]+)/([0-9a-f]{64})\.(pdb|cif|mmcif)\Z")


class InspectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    upload_id: str | None = None
    input_handle: str | None = None
    model_index: int | None = Field(default=None, ge=0)
    altloc: Literal["highest_occupancy", "first"] = "highest_occupancy"
    waters: Literal["strip_all", "keep_all"] = "strip_all"
    hydrogens: Literal["strip", "keep"] = "strip"
    missing_residues: Literal["leave_gaps"] = "leave_gaps"
    symmetry_mates: Literal["ignore"] = "ignore"
    ligand: ResidueRef | None = None
    cutoff_A: float = Field(default=4.0, ge=2.5, le=6.0, allow_inf_nan=False)
    types: list[Literal["contact", "polar_contact", "hydrophobic_contact"]] = Field(
        default_factory=lambda: ["contact", "polar_contact", "hydrophobic_contact"])

    @model_validator(mode="after")
    def _valid(self):
        if (self.upload_id is None) == (self.input_handle is None):
            raise ValueError("exactly one upload_id or input_handle is required")
        if self.upload_id is not None and self.model_index is None:
            raise ValueError("explicit model_index is required for an upload")
        if self.input_handle is not None and self.model_index is not None:
            raise ValueError("existing handles already fix model choice")
        if not self.types or len(self.types) != len(set(self.types)):
            raise ValueError("types must be nonempty and unique")
        return self


def normalize_request(request: InspectionRequest) -> dict[str, Any]:
    value = request.model_dump(mode="json")
    value["types"] = sorted(value["types"])
    return value


@contextmanager
def _workflow_owner(run: Any):
    """Serializes same-run progress without holding nonreentrant Run._owner."""
    path = str((run.run_dir / "workflow.lock").resolve())
    with _LOCK_GUARD:
        lock = _LOCAL_WORKFLOW_LOCKS.setdefault(path, threading.Lock())
    if not lock.acquire(blocking=False):
        raise ToolFailure(FailureClass.transient, "workflow owner is busy", detail={"busy": True})
    try:
        descriptor = os.open(run.run_dir / "workflow.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a+b") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ToolFailure(FailureClass.transient, "workflow owner is busy",
                                  detail={"busy": True}) from exc
            yield
    finally:
        lock.release()


_STEP_TO_TOOL = {"load": "load_structure", "prepare": "prepare_structure",
                 "interactions": "compute_interactions"}


def _steps(run: Any, workflow_id: str, start_seq: int) -> dict[str, dict[str, Any]]:
    result = {}
    for event in run.events.read():
        if event["type"] == "workflow_step_completed" and event.get("workflow_id") == workflow_id:
            step = event.get("step")
            if (step not in _STEP_TO_TOOL or step in result or event.get("seq", 0) <= start_seq or
                    event.get("version") != VERSION or event.get("tool") != _STEP_TO_TOOL[step]):
                raise ValueError("corrupt workflow step identity")
            result[event["step"]] = event
    ordered = sorted(result.values(), key=lambda item: item["seq"])
    if [list(_STEP_TO_TOOL).index(item["step"]) for item in ordered] != sorted(
            list(_STEP_TO_TOOL).index(item["step"]) for item in ordered):
        raise ValueError("corrupt workflow step order")
    return result


def _expected_call(run: Any, tool: str, args: dict[str, Any],
                   source_sha: str | None = None, source_format: str | None = None) -> tuple[dict[str, Any], str]:
    spec = run.registry.specs[tool]
    normalized = check_args(spec, args, run.store.kind_of)
    effective = {**normalized, "_run_seed": run.seed, "_dry_run": run.dry_run}
    if tool == "load_structure":
        if source_sha is None or source_format is None:
            raise ValueError("missing workflow upload identity")
        effective.update(_source_sha256=source_sha, _source_format=source_format)
    return normalized, idempotency_key(tool, spec.version, effective)


def _one(events: list[dict[str, Any]], predicate: Any, message: str) -> dict[str, Any]:
    found = [event for event in events if predicate(event)]
    if len(found) != 1:
        raise ValueError(f"corrupt workflow {message}")
    return found[0]


def _verified_content(run: Any, step: str, handle: str, args: dict[str, Any],
                      source_sha: str | None, source_format: str | None) -> None:
    content = run.store.load(handle)
    meta = run.store.meta(handle)
    schemas = {"load": ("structure", "structure_selection@2"),
               "prepare": ("prepared_structure", "prepared_structure@1"),
               "interactions": ("interaction_set", "interaction_set@1")}
    if (meta["kind"], meta["schema"]) != schemas[step]:
        raise ValueError("corrupt workflow output type")
    if step == "load":
        source = content["source"]
        source_meta = run.store.meta(source)
        raw = run.store.load(source)
        if (content["model_index"] != args["model_index"] or
                (source_meta["kind"], source_meta["schema"], source_meta["fmt"]) !=
                ("structure_source", "structure_source@1", source_format) or
                hashlib.sha256(raw).hexdigest() != source_sha):
            raise ValueError("corrupt workflow loaded input")
    elif step == "prepare":
        manifest_handle = content["manifest"]
        manifest_meta = run.store.meta(manifest_handle)
        manifest = run.store.load(manifest_handle)
        original = run.store.load(args["structure"])
        if ((manifest_meta["kind"], manifest_meta["schema"]) !=
                ("preparation_manifest", "preparation_manifest@1") or
                run.store.meta(args["structure"])["schema"] != "structure_selection@2" or
                manifest["input"] != args["structure"] or
                manifest["source_handle"] != original["source"] or
                manifest["model_index"] != original["model_index"] or
                content["model_index"] != manifest["model_index"] or
                content["model_number"] != manifest["model_number"] or
                any(manifest.get(field) != args[field] for field in
                    ("altloc", "waters", "hydrogens", "missing_residues", "symmetry_mates"))):
            raise ValueError("corrupt workflow preparation link")
    else:
        prepared = run.store.load(args["structure"])
        manifest = run.store.load(prepared["manifest"])
        if (run.store.meta(args["structure"])["schema"] != "prepared_structure@1" or
                run.store.meta(prepared["manifest"])["schema"] != "preparation_manifest@1" or
                content["structure"] != args["structure"] or
                content["selection"]["ligand"] != args["ligand"] or
                content["parameters"] != {"cutoff_A": args["cutoff_A"], "types": sorted(args["types"])} or
                content["method"].get("name") != "heavy_atom_distance" or
                content["method"].get("version") != "1" or
                content["method"].get("unit") != "angstrom" or
                args["engine"] != "geometric" or
                args["ligand"]["model_number"] != manifest["model_number"]):
            raise ValueError("corrupt workflow interaction link")


def _verified_step(run: Any, event: dict[str, Any], workflow_id: str, start_seq: int,
                   step: str, tool: str, args: dict[str, Any], kind: str,
                   source_sha: str | None, source_format: str | None) -> str:
    normalized, key = _expected_call(run, tool, args, source_sha, source_format)
    handle = event.get("output_handle")
    if (event.get("workflow_id") != workflow_id or event.get("version") != VERSION or
            event.get("step") != step or event.get("tool") != tool or
            event.get("normalized_args") != normalized or event.get("key") != key or
            not isinstance(handle, str) or not event.get("call_id") or
            not event.get("source_call_id") or not event.get("proposal_id") or
            not isinstance(event.get("child_event_seq"), int) or
            not isinstance(event.get("source_event_seq"), int) or
            event["seq"] <= start_seq):
        raise ValueError("corrupt workflow progress identity")
    events = list(run.events.read())
    proposal = _one(events, lambda e: e["type"] == "branch_proposed" and
                    e.get("proposal_id") == event["proposal_id"], "proposal identity")
    observed = _one(events, lambda e: e["type"] == "branch_observed" and
                    e.get("proposal_id") == event["proposal_id"], "observation identity")
    if (proposal.get("branch_id") != workflow_id or proposal.get("tool") != tool or
            proposal.get("key") != key or observed.get("branch_id") != workflow_id or
            observed.get("output_handle") != handle or
            not start_seq < proposal["seq"] < event["child_event_seq"] < observed["seq"] < event["seq"]):
        raise ValueError("corrupt workflow observation link")
    child = _one(events, lambda e: e["seq"] == event["child_event_seq"], "child event")
    if (child.get("tool") != tool or child.get("key") != key or
            child.get("output", {}).get("handle") != handle or
            child.get("output", {}).get("kind") != kind):
        raise ValueError("corrupt workflow child output")
    if child["type"] == "cache_hit":
        if (child.get("observation_id") != event["call_id"] or
                child.get("proposal_id") != event["proposal_id"] or
                child.get("branch_id") != workflow_id or child.get("args") != normalized or
                child.get("source_call_id") != event["source_call_id"]):
            raise ValueError("corrupt workflow cache observation")
    elif child["type"] == "tool_succeeded":
        if event["call_id"] != event["source_call_id"] or child.get("call_id") != event["call_id"]:
            raise ValueError("corrupt workflow physical call")
    else:
        raise ValueError("corrupt workflow child event type")
    source_call = _one(events, lambda e: e["type"] == "tool_called" and
                       e.get("call_id") == event["source_call_id"], "source call")
    success = _one(events, lambda e: e["type"] == "tool_succeeded" and
                   e.get("call_id") == event["source_call_id"], "source success")
    if (success["seq"] != event["source_event_seq"] or
            not source_call["seq"] < success["seq"] <= child["seq"] or
            source_call.get("tool") != tool or source_call.get("version") != run.registry.specs[tool].version or
            source_call.get("key") != key or success.get("key") != key or
            success.get("output") != child.get("output") or
            (tool != "load_structure" and source_call.get("args") != normalized) or
            (tool == "load_structure" and source_call.get("args", {}).get("model_index") != normalized["model_index"])):
        raise ValueError("corrupt workflow source call link")
    if child["type"] == "tool_succeeded" and (
            source_call.get("root_call_id") != event["proposal_id"] or
            source_call.get("branch_id") != workflow_id or
            source_call.get("execution_mode") != "autonomous"):
        raise ValueError("corrupt workflow physical branch")
    _verified_content(run, step, handle, normalized, source_sha, source_format)
    if run.store.meta(handle)["null_result"] != event.get("null_result"):
        raise ValueError("corrupt workflow null marker")
    return handle


def _call_step(run: Any, workflow_id: str, start_seq: int, step: str, tool: str, args: dict[str, Any],
               kind: str, *, source_bytes: bytes | None = None, source_format: str | None = None,
               source_sha: str | None = None) -> str:
    existing = _steps(run, workflow_id, start_seq).get(step)
    if existing:
        return _verified_step(run, existing, workflow_id, start_seq, step, tool, args, kind,
                              source_sha, source_format)
    normalized, key = _expected_call(run, tool, args, source_sha, source_format)
    before = list(run.events.read())[-1]["seq"]
    result = run.call(tool, args, decided_by="rule", execution_mode="autonomous",
                      branch_id=workflow_id, source_bytes=source_bytes, source_format=source_format)
    if result.kind != kind:
        raise ValueError("workflow child kind mismatch")
    events = list(run.events.read())
    proposal = _one(events, lambda e: e["seq"] > before and e["type"] == "branch_proposed" and
                    e.get("branch_id") == workflow_id and e.get("tool") == tool and e.get("key") == key,
                    "new proposal")
    proposal_id = proposal["proposal_id"]
    observed = _one(events, lambda e: e["type"] == "branch_observed" and
                    e.get("proposal_id") == proposal_id and e.get("branch_id") == workflow_id,
                    "new observation")
    if observed.get("output_handle") != result.handle:
        raise ValueError("workflow observed output mismatch")
    children = [e for e in events if proposal["seq"] < e["seq"] < observed["seq"] and
                e["type"] in {"tool_succeeded", "cache_hit"} and e.get("tool") == tool and
                e.get("key") == key and e.get("output", {}).get("handle") == result.handle and
                (e.get("observation_id") == proposal_id if e["type"] == "cache_hit" else any(
                    call["type"] == "tool_called" and call.get("call_id") == e.get("call_id") and
                    call.get("root_call_id") == proposal_id and call.get("branch_id") == workflow_id
                    for call in events))]
    if len(children) != 1:
        raise ValueError("workflow child call is not uniquely recorded")
    child = children[0]
    call_id = child.get("call_id") or child["observation_id"]
    source_call_id = child.get("source_call_id", call_id)
    source_success = _one(events, lambda e: e["type"] == "tool_succeeded" and
                          e.get("call_id") == source_call_id, "source success")
    completed = run.events.append("workflow_step_completed", workflow_id=workflow_id, version=VERSION,
                                  step=step, tool=tool, normalized_args=normalized, key=key,
                                  proposal_id=proposal_id, child_event_seq=child["seq"],
                                  source_event_seq=source_success["seq"], call_id=call_id,
                                  source_call_id=source_call_id, output_handle=result.handle,
                                  null_result=result.null_result)
    _verified_step(run, completed, workflow_id, start_seq, step, tool, args, kind,
                   source_sha, source_format)
    return result.handle


def _bounded_value(value: Any, depth: int = 0) -> Any:
    if depth > 2:
        return None
    if isinstance(value, str):
        if value.startswith(("/", "file:", "http:", "https:")):
            return "[redacted]"
        return value[:240]
    if value is None or type(value) in (bool, int, float):
        return value
    if isinstance(value, list):
        return [_bounded_value(item, depth + 1) for item in value[:8]]
    if isinstance(value, dict):
        return {key: _bounded_value(item, depth + 1) for key, item in list(value.items())[:16]
                if isinstance(key, str) and len(key) <= 48}
    return None


def _outcome_detail(exc: Exception, run: Any) -> dict[str, Any]:
    if isinstance(exc, ToolFailure):
        detail = {key: _bounded_value(value) for key, value in exc.detail.items()
                  if key in {"axis", "busy", "reason_code", "job_id", "branch_id"}}
        fix = None
        if exc.fix is not None and exc.fix.tool in run.registry.specs:
            spec = run.registry.specs[exc.fix.tool]
            fix = {"tool": exc.fix.tool,
                   "args": {key: _bounded_value(value) for key, value in exc.fix.args.items()
                            if key in spec.accepts or key in spec.params}}
        return {"failure": {"classification": exc.cls.value, "message": _bounded_value(exc.message),
                            "fix": fix, "detail": detail}}
    if isinstance(exc, ApprovalRequired):
        spec = run.registry.specs.get(exc.tool)
        allowed = set(spec.accepts) | set(spec.params) if spec else set()
        return {"approval": {"gate": exc.gate, "tool": exc.tool,
                             "args": {key: _bounded_value(value) for key, value in exc.requested_args.items()
                                      if key in allowed}, "reason": _bounded_value(exc.reason)}}
    if isinstance(exc, LoopStop):
        return {"loop_stop": {"reason": _bounded_value(exc.reason),
                              "detail": {key: _bounded_value(value) for key, value in exc.detail.items()
                                         if key == "branch_id"}}}
    return {"cancellation": {"status": "cancelled", "reason": "run_cancelled"}}


def _causal_context(run: Any, workflow_id: str, tool: str | None, since: int) -> dict[str, Any]:
    events = list(run.events.read())
    recent = [e for e in events if e["seq"] > since]
    proposals = [e for e in recent if e["type"] == "branch_proposed" and
                 e.get("branch_id") == workflow_id and e.get("tool") == tool]
    proposal = proposals[-1] if proposals else None
    calls = [e for e in recent if e["type"] == "tool_called" and
             proposal is not None and e.get("root_call_id") == proposal.get("proposal_id") and
             e.get("branch_id") == workflow_id]
    call = calls[-1] if calls else None
    linked = [e for e in recent if call is not None and e.get("call_id") == call["call_id"] and
              e["type"] in {"tool_failed", "tool_interrupted"}]
    checkpoints = [e for e in recent if e["type"] in {"checkpoint", "approval_requested"} and
                   (e.get("branch_id") == workflow_id or e.get("pending_action", {}).get("tool") == tool or
                    e.get("tool") == tool)]
    cancelled = [e for e in recent if e["type"] == "run_cancelled"]
    causal = (linked[-1] if linked else checkpoints[-1] if checkpoints else
              cancelled[-1] if cancelled else call if call else proposal)
    return {"event_seq": causal["seq"] if causal else None,
            "call_id": call["call_id"] if call else None,
            "proposal_id": proposal["proposal_id"] if proposal else None}


def inspect_complex(run: Any, request: InspectionRequest | dict[str, Any], *,
                    source_bytes: bytes | None = None, source_format: str | None = None) -> dict[str, Any]:
    """Stable steps, honest selections and resumable physical provenance."""
    req = request if isinstance(request, InspectionRequest) else InspectionRequest.model_validate(request)
    normalized = normalize_request(req)
    if req.upload_id is not None:
        match = UPLOAD_TOKEN_RE.fullmatch(req.upload_id)
        if match is None or match.group(1) != run.run_id:
            raise ToolFailure(FailureClass.input_invalid, "upload_id must belong to this run")
        if source_bytes is not None and (source_format != match.group(3) or
                                         hashlib.sha256(source_bytes).hexdigest() != match.group(2)):
            raise ToolFailure(FailureClass.input_invalid, "verified upload bytes do not match upload_id")
        normalized["upload_sha256"] = match.group(2)
        normalized["upload_format"] = match.group(3)
    elif source_bytes is not None or source_format is not None:
        raise ToolFailure(FailureClass.input_invalid, "handle input cannot receive upload bytes")
    elif not re.fullmatch(rf"obj://{re.escape(run.run_id)}/(?:structure|prepared_structure)/[0-9a-f]{{64}}",
                          req.input_handle or ""):
        raise ToolFailure(FailureClass.input_invalid, "input_handle must be a same-run structure handle")
    digest = hashlib.sha256(canonical_json({"version": VERSION, "run_id": run.run_id,
                                            "request": normalized})).hexdigest()
    workflow_id = f"workflow_{digest}"
    with _workflow_owner(run):
        starts = [e for e in run.events.read() if e["type"] == "workflow_started" and
                  e.get("workflow_id") == workflow_id]
        if len(starts) > 1:
            raise ValueError("duplicate workflow start event")
        if starts and (starts[0].get("request") != normalized or starts[0].get("version") != VERSION or
                       starts[0].get("driver_mode") != "finite_rules" or
                       starts[0].get("branch_id") != workflow_id):
            raise ValueError("corrupt workflow start identity")
        if not starts:
            if req.upload_id is not None and source_bytes is None:
                raise ToolFailure(FailureClass.input_invalid, "verified upload bytes are required")
            start = run.events.append("workflow_started", workflow_id=workflow_id, version=VERSION,
                                      request=normalized, driver_mode="finite_rules", branch_id=workflow_id)
        else:
            start = starts[0]
        start_seq = start["seq"]
        prior = _steps(run, workflow_id, start_seq)
        if ((req.upload_id is not None and
             (("prepare" in prior and "load" not in prior) or
              ("interactions" in prior and "prepare" not in prior))) or
                (req.upload_id is None and "load" in prior)):
            raise ValueError("corrupt workflow step dependency")
        outputs: dict[str, str] = {}
        current_step: str | None = None
        current_tool: str | None = None
        step_since = start_seq
        try:
            if req.upload_id is not None:
                current_step, current_tool = "load", "load_structure"
                step_since = list(run.events.read())[-1]["seq"]
                if source_bytes is None and "load" not in _steps(run, workflow_id, start_seq):
                    raise ToolFailure(FailureClass.input_invalid, "verified upload bytes are required for missing load step")
                outputs["load"] = _call_step(run, workflow_id, start_seq, "load", "load_structure",
                                             {"source": req.upload_id, "model_index": req.model_index}, "structure",
                                             source_bytes=source_bytes, source_format=match.group(3),
                                             source_sha=match.group(2))
                input_handle = outputs["load"]
            else:
                current_step, current_tool = "input", None
                input_handle = req.input_handle
                try:
                    kind = run.store.meta(input_handle)["kind"]
                except KeyError as exc:
                    raise ToolFailure(FailureClass.input_invalid, "unknown run input_handle") from exc
                if kind not in {"structure", "prepared_structure"}:
                    raise ToolFailure(FailureClass.input_invalid, "input handle must be structure or prepared_structure")
                run.store.load(input_handle)
                if ((kind == "structure" and "interactions" in prior and "prepare" not in prior) or
                        (kind == "prepared_structure" and "prepare" in prior)):
                    raise ValueError("corrupt workflow input step dependency")
            if run.store.meta(input_handle)["kind"] == "structure":
                current_step, current_tool = "prepare", "prepare_structure"
                step_since = list(run.events.read())[-1]["seq"]
                outputs["prepare"] = _call_step(run, workflow_id, start_seq, "prepare", "prepare_structure", {
                    "structure": input_handle, "altloc": req.altloc, "waters": req.waters,
                    "hydrogens": req.hydrogens, "missing_residues": req.missing_residues,
                    "symmetry_mates": req.symmetry_mates}, "prepared_structure")
            else:
                current_step, current_tool = "prepare", None
                prepared = run.store.load(input_handle)
                manifest = run.store.load(prepared["manifest"])
                original = run.store.load(manifest["input"])
                if ((run.store.meta(input_handle)["kind"], run.store.meta(input_handle)["schema"]) !=
                        ("prepared_structure", "prepared_structure@1") or
                        (run.store.meta(prepared["manifest"])["kind"],
                         run.store.meta(prepared["manifest"])["schema"]) !=
                        ("preparation_manifest", "preparation_manifest@1") or
                        run.store.meta(manifest["input"])["schema"] != "structure_selection@2" or
                        manifest["source_handle"] != original["source"] or
                        manifest["model_index"] != original["model_index"] or
                        prepared["model_index"] != manifest["model_index"] or
                        prepared["model_number"] != manifest["model_number"]):
                    raise ValueError("corrupt prepared input linkage")
                for field in ("altloc", "waters", "hydrogens", "missing_residues", "symmetry_mates"):
                    if manifest[field] != getattr(req, field):
                        raise ToolFailure(FailureClass.input_invalid, f"prepared handle conflicts with {field} policy")
                outputs["prepare"] = input_handle
            candidates = structure_residues(run.store, outputs["prepare"])["ligands"]
            if not candidates:
                result = {"workflow_id": workflow_id, "status": "no_ligand", "outputs": outputs,
                          "choices": [], "message": "selected prepared structure has no ligand instance"}
                run.events.append("workflow_outcome", **result)
                return result
            if req.ligand is None:
                if len(candidates) > 1:
                    result = {"workflow_id": workflow_id, "status": "needs_selection", "outputs": outputs,
                              "choices": candidates, "message": "select one exact ligand instance"}
                    run.events.append("workflow_outcome", **result)
                    return result
                ligand = candidates[0]
            else:
                ligand = req.ligand.model_dump()
                if not any(c == ligand for c in candidates):
                    raise ToolFailure(FailureClass.input_invalid, "exact ligand is absent from prepared structure")
            current_step, current_tool = "interactions", "compute_interactions"
            step_since = list(run.events.read())[-1]["seq"]
            outputs["interactions"] = _call_step(run, workflow_id, start_seq, "interactions", "compute_interactions",
                {"structure": outputs["prepare"], "ligand": ligand, "cutoff_A": req.cutoff_A,
                 "types": normalized["types"], "engine": "geometric"}, "interaction_set")
            result = {"workflow_id": workflow_id, "status": "complete", "outputs": outputs,
                      "ligand": ligand, "scientific_null": run.store.meta(outputs["interactions"])["null_result"]}
            run.events.append("workflow_outcome", **result)
            return result
        except (ToolFailure, ApprovalRequired, LoopStop, RunCancelled) as exc:
            status = "checkpoint" if isinstance(exc, (ApprovalRequired, LoopStop)) else (
                "cancelled" if isinstance(exc, RunCancelled) else "failed")
            result = {"workflow_id": workflow_id, "status": status, "outputs": outputs,
                      "failed_step": current_step, "failed_tool": current_tool,
                      "causal": _causal_context(run, workflow_id, current_tool, step_since),
                      "message": _bounded_value(str(exc)), **_outcome_detail(exc, run)}
            run.events.append("workflow_outcome", **result)
            return result
