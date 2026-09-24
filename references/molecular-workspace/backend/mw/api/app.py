"""FastAPI surface for the frontend (and later the MCP server).

Humans and the agent use the SAME command path: POST /runs/{id}/commands -> Run.call.
Run `uvicorn mw.api.app:app --reload` from backend/.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..core.errors import ToolFailure
from ..runtime.guards import LoopStop
from ..runtime.orchestrator import ApprovalRequired, Run
from ..workspace import build_registry, new_run

RUNS_DIR = Path(os.environ.get("MW_RUNS_DIR", "runs"))
app = FastAPI(title="Molecular Workspace")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])
REGISTRY = build_registry()
RUNS: dict[str, Run] = {}


class NewRun(BaseModel):
    goal: str
    context: list[str] = []
    dry_run: bool = True
    egress: str = "local_only"


class Command(BaseModel):
    tool: str
    args: dict[str, Any] = {}
    decided_by: str = "human"


def _run(rid: str) -> Run:
    if rid not in RUNS:
        raise HTTPException(404, f"run {rid} not found")
    return RUNS[rid]


@app.get("/tools")
def tools(levels: str = "L5") -> list[dict[str, Any]]:
    return [s.model_dump() for s in REGISTRY.visible(set(levels.split(",")))]


@app.post("/runs")
def create_run(body: NewRun) -> dict[str, Any]:
    run = new_run(RUNS_DIR, dry_run=body.dry_run, registry=REGISTRY)
    run.events.append("goal", text=body.goal, context=body.context, egress=body.egress)
    RUNS[run.run_id] = run
    return {"run_id": run.run_id}


@app.post("/runs/{rid}/commands")
def command(rid: str, cmd: Command) -> dict[str, Any]:
    run = _run(rid)
    try:
        h = run.call(cmd.tool, cmd.args, decided_by=cmd.decided_by)  # type: ignore[arg-type]
        return {"ok": True, "handle": h.model_dump(by_alias=True)}
    except ToolFailure as f:
        return {"ok": False, **f.to_dict()}
    except ApprovalRequired as a:
        return {"ok": False, "approval": {"gate": a.gate, "tool": a.tool, "reason": a.reason}}
    except LoopStop as s:
        return {"ok": False, "loop_stop": {"reason": s.reason, **s.detail}}


@app.post("/runs/{rid}/approvals/{gate}")
def approve(rid: str, gate: str) -> dict[str, Any]:
    _run(rid).approve(gate)
    return {"ok": True}


@app.get("/runs/{rid}/events")
def events(rid: str, after: int = 0) -> list[dict[str, Any]]:
    return [e for e in _run(rid).events.read() if e["seq"] > after]


@app.get("/runs/{rid}/budget")
def budget(rid: str) -> dict[str, Any]:
    return _run(rid).budget.snapshot()


@app.get("/runs/{rid}/objects")
def materialize(rid: str, handle: str, columns: str | None = None, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    run = _run(rid)
    meta = run.store.meta(handle)
    rows = run.store.materialize(handle, columns.split(",") if columns else None, offset, limit)
    return {"meta": meta, "rows": rows}
