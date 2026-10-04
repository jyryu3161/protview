"""M19 T5: the human-approved budget-limit raise for one batch (spec .dryforge/spec.md 6.1-6.3, 11.8, 12, 13.3).

``POST /runs/{id}/docking/batches/limit_approval`` (body = the batch request) recomputes the batch's need from the
current budget and stored results, raises only the shortfall, records ``budget_limit_updated`` (by "human") with the
batch context and changes nothing (no event) when nothing is short. Increase rule (per call, per axis), typed here
from the spec, never copied from the module under test:

    calls = min(shortfall_calls, needed_calls)
    wall  = 0 if shortfall_wall == 0 else min(shortfall_wall, needed_wall) + 60

where shortfall = max(0, needed - (limit - used)). Clamping the shortfall at the need is clamping a negative
remaining (usage above the limit) at zero, so one approval never raises an axis by more than the batch's need (+ the
60 s wall margin): at most 51 units and 7860 s.

The product-path test uses the real M17 jobs and a real small batch (``.deps/docking/venv-locked`` + qvina2; fails,
never skips, when an environment is absent). The server test process never imports RDKit, Meeko or MDAnalysis.
"""
from __future__ import annotations

import ast
import copy
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ligand_job_fixture import import_file, new_ligand_run, run_job
from test_docking_batch_jobs import (
    BLOCKS,
    IDS,
    PARENT,
    PROTOCOL,
    REC,
    RID,
    _args,
    _check_rows_against_results,
    _no_strays,
    _reserved,
    _summary,
    _world,
)

from mw import analysis_executions, analysis_plans, workflows
from mw import docking_batch_inputs as BI
from mw import docking_batch_jobs as BJ
from mw.api import app as api_module
from mw.docking_reports import build_docking_report
from mw.runtime.guards import BudgetLimits
from mw.runtime.orchestrator import ApprovalRequired
from mw.tools.energetic import JOB_ONLY_TOOLS, JOB_PROTOCOLS

MW = Path(__file__).resolve().parents[1] / "mw"
ROUTE = "/runs/{rid}/docking/batches/limit_approval"
CONTEXT_KEYS = {"purpose", "batch_input_sha256", "new_dockings", "needed", "shortfall", "increase", "limits_before",
                "limits_after"}
RESPONSE_KEYS = {"raised", "batch_input_sha256", "new_dockings", "needed", "shortfall_before", "increase",
                 "limits_before", "limits_after", "shortfall_after", "event_seq", "budget"}


def _budget(calls_used=0, wall_used=0.0, calls_limit=8, wall_limit=1800.0) -> dict:
    return {"expensive_calls": {"used": calls_used, "limit": calls_limit},
            "wall_clock_s": {"used": wall_used, "limit": wall_limit}}


def _apply(snapshot: dict, increase: dict) -> dict:
    out = copy.deepcopy(snapshot)
    for axis, amount in increase.items():
        out[axis]["limit"] += amount
    return out


# ----------------------------------------------------------------- the exact increase rule (pure)
@pytest.mark.parametrize(("new", "snapshot", "expected"), [
    # Nothing short: no raise on either axis.
    (4, _budget(0, 0.0), {"expensive_calls": 0, "wall_clock_s": 0}),
    # Exact shortfall: 2 units / 1200 s left, need 4 / 1500 s -> +2 units, +300 + 60 s.
    (4, _budget(6, 600.0), {"expensive_calls": 2, "wall_clock_s": 360}),
    # Only one axis short: the other is untouched.
    (4, _budget(8, 0.0, 8), {"expensive_calls": 4, "wall_clock_s": 0}),
    # Remaining exactly 0 and N >= 25: the wall need is capped at 7800 s; the margin is kept (T2 swallowed it).
    (51, _budget(8, 1800.0), {"expensive_calls": 51, "wall_clock_s": 7860}),
    (25, _budget(8, 1800.0), {"expensive_calls": 25, "wall_clock_s": 7860}),
    # Usage above the limit (an attempt charged past it): the increment is still the need (+ margin), never more.
    (4, _budget(8, 1900.0), {"expensive_calls": 4, "wall_clock_s": 1560}),
    (51, _budget(10, 9000.0, 8), {"expensive_calls": 51, "wall_clock_s": 7860}),
    # N = 0 needs 60 s and no unit: a spent wall gets 60 + 60 s, the call axis nothing.
    (0, _budget(8, 1800.0), {"expensive_calls": 0, "wall_clock_s": 120}),
    (0, _budget(8, 1700.0), {"expensive_calls": 0, "wall_clock_s": 0}),
    # Large earlier usage: no absolute ceiling, only the need.
    (10, _budget(300, 50_000.0, 300, 50_000.0), {"expensive_calls": 10, "wall_clock_s": 3360}),
])
def test_increase_rule(new, snapshot, expected):
    assert BI.limit_increase(BI.needed_budget(new), snapshot) == expected


def test_increase_never_exceeds_need_plus_margin_and_covers_the_need():
    for new in (0, 1, 4, 24, 25, 50, 51):
        needed = BI.needed_budget(new)
        for calls_used in (0, 5, 8, 9, 60):
            for wall_used in (0.0, 1799.5, 1800.0, 1830.0, 1900.0, 20_000.0):
                snapshot = _budget(calls_used, wall_used)
                increase = BI.limit_increase(needed, snapshot)
                assert 0 <= increase["expensive_calls"] <= needed["expensive_calls"] <= 51
                assert 0 <= increase["wall_clock_s"] <= needed["wall_clock_s"] + 60 <= 7860
                raised = _apply(snapshot, increase)
                after = BI.shortfall(needed, raised)
                if calls_used <= 8:
                    assert after["expensive_calls"] == 0
                if wall_used - 1800.0 <= 60:   # the 60 s margin also absorbs a small overrun
                    assert after["wall_clock_s"] == 0
                if after == {"expensive_calls": 0, "wall_clock_s": 0}:
                    assert BI.limit_increase(needed, raised) == {"expensive_calls": 0, "wall_clock_s": 0}


def test_usage_far_above_the_limit_stays_short_after_one_approval():
    """The per-approval cap wins over covering an overrun: 200 s over the wall limit, need 1500 s -> +1560 s, the
    batch is still 140 s short (a second explicit approval raises the rest; nothing is raised silently)."""
    snapshot = _budget(0, 2000.0)
    raised = _apply(snapshot, BI.limit_increase(BI.needed_budget(4), snapshot))
    assert BI.shortfall(BI.needed_budget(4), raised) == {"expensive_calls": 0, "wall_clock_s": 140.0}
    again = _apply(raised, BI.limit_increase(BI.needed_budget(4), raised))
    assert BI.shortfall(BI.needed_budget(4), again) == {"expensive_calls": 0, "wall_clock_s": 0}


# ----------------------------------------------------------------- not a tool, plan step, workflow or model action
def test_the_raise_is_reachable_only_from_its_human_route():
    names = {"limit_approval", "docking_batch_limit_approval", "raise_limits", "qvina_dock_batch_limit_approval"}
    for name in names:
        assert name not in api_module.REGISTRY.specs and name not in api_module.SUPPORTED_TOOLS
        assert name not in JOB_ONLY_TOOLS and name not in JOB_PROTOCOLS
        assert name not in analysis_plans.OPERATIONS and name not in analysis_executions.JOB_TOOLS
        assert name not in workflows._STEP_TO_TOOL.values()
    assert all(spec.get("tool") not in names for spec in analysis_plans.OPERATIONS.values())
    # Source scan: only the orchestrator (definition), the batch job lane (definition) and the HTTP route name them.
    # M22 adds the GA lane's own limit approval and route (spec M22 6, test_ligand_ga_budget.py); the batch one below
    # is still reached only from its route.
    mentions = {str(path.relative_to(MW)) for path in MW.rglob("*.py")
                if any(name in path.read_text() for name in ("raise_limits", "limit_approval"))}
    assert mentions == {"runtime/orchestrator.py", "docking_batch_jobs.py", "api/app.py", "ligand_ga_jobs.py"}
    tree = ast.parse((MW / "api/app.py").read_text())
    callers = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               for call in ast.walk(node) if isinstance(call, ast.Attribute) and call.attr == "limit_approval" and
               isinstance(call.value, ast.Name) and call.value.id == "docking_batch_jobs"}
    assert callers == {"docking_batch_limit_approval"}
    jobs_tree = ast.parse((MW / "docking_batch_jobs.py").read_text())
    callers = {node.name for node in ast.walk(jobs_tree) if isinstance(node, ast.FunctionDef)
               for call in ast.walk(node) if isinstance(call, ast.Attribute) and call.attr == "raise_limits"}
    assert callers == {"limit_approval"}
    routes = [(route.path, sorted(route.methods)) for route in api_module.app.routes
              if getattr(route, "path", "").endswith("limit_approval") and "/ligand/ga/" not in route.path]  # M22
    assert routes == [(ROUTE, ["POST"])]


def test_dry_run_permits_no_raise_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path / "runs")
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    rid = client.post("/runs", json={"goal": "M19 dry", "dry_run": True}).json()["run_id"]
    events = (tmp_path / "runs" / rid / "events.jsonl").read_bytes()
    refused = client.post(ROUTE.format(rid=rid), json={})
    assert refused.status_code == 412 and refused.json()["detail"]["reason_code"] == "dry_run"
    assert (tmp_path / "runs" / rid / "events.jsonl").read_bytes() == events


def test_update_limits_without_context_keeps_its_event_bytes(tmp_path):
    run = new_ligand_run(tmp_path, "run_limits")
    run.update_limits(BudgetLimits(expensive_calls=9, wall_clock_s=1900), by="test")
    event = [e for e in run.events.read() if e["type"] == "budget_limit_updated"][-1]
    assert set(event) == {"seq", "ts", "type", "limits", "by"} and event["by"] == "test"
    assert event["limits"] == BudgetLimits(expensive_calls=9, wall_clock_s=1900).model_dump()


# ----------------------------------------------------------------- the product path (real M17 jobs, real batch)
@pytest.fixture(scope="module")
def base(tmp_path_factory):
    root = tmp_path_factory.mktemp("m19_budget_base")
    run = new_ligand_run(root, RID)
    receptor = import_file(run, "receptor", "rec.pdb", REC)
    parent = import_file(run, "ligand_sdf", "parent.sdf", PARENT)
    blocks = import_file(run, "building_blocks_smiles", "blocks.smi", BLOCKS)
    inspected = run_job(run, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [blocks]})
    assert inspected["status"] == "done", inspected
    enumerated = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": inspected["output_handles"][0],
                                                     "site_atoms": [22], "use_fixed": True})
    assert enumerated["status"] == "done", enumerated
    return {"root": root, "receptor": receptor, "parent": parent, "candidate_set": enumerated["output_handles"][0]}


def test_the_raise_never_grants_the_first_expensive_approval(base, tmp_path, monkeypatch):
    """A run without the first expensive approval: the raise adds limits only; the batch still needs the approval."""
    world, _root = _world(base, tmp_path, "world")
    args = _args(base, IDS[:1])
    selection = BJ.submission(world, args)   # the real selection, computed on the world that holds the inputs
    root = tmp_path / "runs"
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    rid = client.post("/runs", json={"goal": "M19 approval", "dry_run": False}).json()["run_id"]
    monkeypatch.setattr(BJ, "submission", lambda _run, _args: selection)   # labeled internal hooks: same selection,
    monkeypatch.setattr(BJ, "reuse_plan", lambda _run, selected, _pins: [None] * len(selected["rows"]))   # N = 1
    run = api_module._run(rid)
    run.update_limits(BudgetLimits(expensive_calls=0, wall_clock_s=100), by="test")
    body = client.post(ROUTE.format(rid=rid), json=args).json()
    assert body["raised"] is True and body["increase"]["expensive_calls"] == 1
    assert body["limits_after"]["expensive_calls"] == 1 and body["shortfall_after"]["wall_clock_s"] == 0
    kinds = [e["type"] for e in run.events.read()]
    assert "approval_resolved" not in kinds and "approval_requested" not in kinds
    run._refresh()
    assert run.approved_expensive is False
    with pytest.raises(ApprovalRequired) as caught:
        run.reserve_attempt("attempt_t5", "job_t5", "qvina_dock_batch", {}, units=1)
    assert caught.value.gate == "expensive_first_call"


def _hooked_run(base, tmp_path, monkeypatch, goal: str):
    """A fresh API run whose batch selection is the real one from the world (labeled internal hooks, N = 1)."""
    world, _root = _world(base, tmp_path, "world")
    args = _args(base, IDS[:1])
    selection = BJ.submission(world, args)
    root = tmp_path / "runs"
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    rid = client.post("/runs", json={"goal": goal, "dry_run": False}).json()["run_id"]
    monkeypatch.setattr(BJ, "submission", lambda _run, _args: selection)
    monkeypatch.setattr(BJ, "reuse_plan", lambda _run, selected, _pins: [None] * len(selected["rows"]))
    return client, rid, args, root / rid / "events.jsonl"


def test_the_decision_and_the_raise_use_the_same_budget_snapshot(base, tmp_path, monkeypatch):
    """The need is decided on the snapshot the raise plans with (taken under the run owner, without the in-flight
    active time of an attempt that has not been charged yet): no shortfall there, nothing changes and the answer
    agrees with itself."""
    _client, rid, args, events_path = _hooked_run(base, tmp_path, monkeypatch, "M19 snapshot")
    run = api_module._run(rid)
    run.update_limits(BudgetLimits(expensive_calls=8, wall_clock_s=400), by="test")   # N = 1 needs 600 s
    run._refresh()
    left = 400 - run.budget.snapshot()["wall_clock_s"]["used"]
    run.update_limits(BudgetLimits(expensive_calls=8, wall_clock_s=400 + (600 - left) + 30), by="test")
    run._refresh()
    raw = events_path.read_bytes()
    run._active_started = run.monotonic() - 120   # labeled fault: 120 s of uncharged active time in flight
    try:
        assert run.budget_snapshot()["wall_clock_s"]["used"] > run.budget.snapshot()["wall_clock_s"]["used"] + 100
        body = BJ.limit_approval(run, args)
    finally:
        run._active_started = None
    assert body["raised"] is False and body["event_seq"] is None
    assert body["shortfall_before"] == body["shortfall_after"] == {"expensive_calls": 0, "wall_clock_s": 0}
    assert body["increase"] == {"expensive_calls": 0, "wall_clock_s": 0}
    assert events_path.read_bytes() == raw


def test_a_cancelled_run_refuses_the_raise_and_writes_nothing(base, tmp_path, monkeypatch):
    client, rid, args, events_path = _hooked_run(base, tmp_path, monkeypatch, "M19 cancelled")
    run = api_module._run(rid)
    run.update_limits(BudgetLimits(expensive_calls=0, wall_clock_s=100), by="test")   # short on both axes
    run.cancel()
    raw = events_path.read_bytes()
    refused = client.post(ROUTE.format(rid=rid), json=args)
    assert refused.status_code == 409, refused.text
    assert refused.json() == {"ok": False, "error": "cancelled", "message": "run cancelled"}
    assert not [e for e in run.events.read() if e["type"] == "budget_limit_updated" and e.get("by") == "human"]
    assert events_path.read_bytes() == raw


def _limits(run) -> dict:
    snapshot = run.budget_snapshot()
    return {axis: snapshot[axis]["limit"] for axis in BI.AXES}


def test_approval_raises_only_the_shortfall_once_and_the_batch_then_runs(base, tmp_path, monkeypatch):
    run, root = _world(base, tmp_path)
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    events_path = root / RID / "events.jsonl"
    route = ROUTE.format(rid=RID)
    args = _args(base, IDS[:2])   # N = 2: needs 2 units and 900 s
    needed = {"expensive_calls": 2, "wall_clock_s": 900}

    # Malformed request: refused like a submission, nothing written.
    raw = events_path.read_bytes()
    bad = client.post(route, json={**args, "timeout_s": 60})
    assert bad.status_code == 422 and bad.json()["detail"]["reason_code"] == "invalid_job_arguments"
    assert events_path.read_bytes() == raw

    # Defaults (8 units, 1800 s) already cover N = 2: nothing changes and no event is written.
    unchanged = client.post(route, json=args)
    assert unchanged.status_code == 200, unchanged.text
    body = unchanged.json()
    assert set(body) == RESPONSE_KEYS and body["raised"] is False and body["event_seq"] is None
    assert body["new_dockings"] == 2 and body["needed"] == needed
    assert body["shortfall_before"] == body["shortfall_after"] == {"expensive_calls": 0, "wall_clock_s": 0}
    assert body["increase"] == {"expensive_calls": 0, "wall_clock_s": 0}
    assert body["limits_before"] == body["limits_after"] == {"expensive_calls": 8, "wall_clock_s": 1800}
    assert events_path.read_bytes() == raw

    # Make the run short on both axes (a test-only limit update), then submission is refused with zero spend.
    run = api_module._run(RID)
    run._refresh()
    used = run.budget_snapshot()
    run.update_limits(BudgetLimits(expensive_calls=used["expensive_calls"]["used"] + 1,
                                   wall_clock_s=used["wall_clock_s"]["used"] + 200), by="test")
    refused = client.post(f"/runs/{RID}/jobs", json={"protocol_id": PROTOCOL, "args": args, "timeout_s": 7800})
    assert refused.status_code == 429 and refused.json()["detail"]["reason_code"] == "batch_limit_raise_required"
    run._refresh()
    before_limits, before_used = _limits(run), run.budget_snapshot()["expensive_calls"]["used"]
    count = len(list(run.events.read()))

    # The approval: exactly the shortfall (+ 60 s on the wall axis), one human event with the batch context.
    approved = client.post(route, json=args)
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert set(body) == RESPONSE_KEYS and body["raised"] is True
    events = list(run.events.read())
    new_events = events[count:]
    limit_events = [e for e in new_events if e["type"] == "budget_limit_updated"]
    assert len(limit_events) == 1 and limit_events[0]["seq"] == body["event_seq"]
    assert {e["type"] for e in new_events} <= {"budget_limit_updated", "wall_charged"}   # + runtime overhead
    assert not [e for e in new_events if e["type"] in {"approval_resolved", "budget_reserved", "job_submitted"}]
    event = limit_events[0]
    assert event["by"] == "human" and set(event["context"]) == CONTEXT_KEYS
    context = event["context"]
    assert context["purpose"] == "docking_batch_limit_raise" and context["new_dockings"] == 2
    assert context["needed"] == needed and context["shortfall"]["expensive_calls"] == 1
    short_wall = context["shortfall"]["wall_clock_s"]
    assert 700 <= short_wall < 705   # 900 needed, 200 s left minus the runtime overhead charged meanwhile
    assert context["increase"] == {"expensive_calls": 1, "wall_clock_s": short_wall + 60}
    assert context["limits_before"] == before_limits
    assert context["limits_after"] == {"expensive_calls": before_limits["expensive_calls"] + 1,
                                       "wall_clock_s": before_limits["wall_clock_s"] + short_wall + 60}
    assert context["batch_input_sha256"] == body["batch_input_sha256"] == BJ.submission(run, args)[0][
        "batch_input_sha256"]
    assert event["limits"] == {**BudgetLimits().model_dump(), **context["limits_after"]}
    assert body["shortfall_before"] == context["shortfall"] and body["increase"] == context["increase"]
    assert body["limits_before"] == before_limits and body["limits_after"] == context["limits_after"]
    assert body["shortfall_after"] == {"expensive_calls": 0, "wall_clock_s": 0}
    assert _limits(run) == context["limits_after"] and client.get(f"/runs/{RID}/budget").json() == body["budget"]
    assert run.budget_snapshot()["expensive_calls"]["used"] == before_used   # nothing refilled or charged

    # Idempotent: a second approval changes nothing and writes no event.
    raw = events_path.read_bytes()
    again = client.post(route, json=args).json()
    assert again["raised"] is False and again["event_seq"] is None and events_path.read_bytes() == raw
    assert again["limits_before"] == again["limits_after"] == context["limits_after"]

    # The same batch is now admitted and runs (this run's first expensive approval came from its M17 jobs).
    submitted = client.post(f"/runs/{RID}/jobs", json={"protocol_id": PROTOCOL, "args": args, "timeout_s": 7800})
    assert submitted.status_code == 200, submitted.text
    job = submitted.json()
    done = client.post(f"/runs/{RID}/jobs/{job['job_id']}/start").json()
    assert done["status"] == "done", done
    run = api_module._run(RID)
    _handle, content = _summary(run, done)
    assert content["status"] == "complete" and len(content["rows"]) == 2
    _check_rows_against_results(run, content)
    assert _reserved(run, job["job_id"]) == [2]
    _no_strays(run)

    # The raised limits stay: the budget display, a report's budget snapshot and an events-only reopen show them.
    assert _limits(run) == context["limits_after"]
    built = build_docking_report(run, content["rows"][0]["result_handle"])
    snapshot = built["manifest"]["snapshot"]["budget"]
    assert {axis: snapshot[axis]["limit"] for axis in BI.AXES} == context["limits_after"]
    replay = tmp_path / "events_only"
    (replay / RID).mkdir(parents=True)
    shutil.copyfile(events_path, replay / RID / "events.jsonl")
    reopened = new_ligand_run(replay, RID)
    reopened._refresh()
    assert _limits(reopened) == context["limits_after"]
    assert reopened.budget_snapshot()["expensive_calls"]["used"] == run.budget_snapshot()["expensive_calls"]["used"]
