"""M23 T5: the sequence GA budget at admission and the human-approved limit raise for one sequence GA (spec
.dryforge/spec.md 7, 11).

``POST /runs/{id}/sequence_ga/limit_approval`` (body = the GA job arguments) recomputes the GA's need from the request
and the current budget, raises only the shortfall, records ``budget_limit_updated`` (by "human") with the GA context
and changes nothing (no event) when nothing is short. Rules typed here from spec 7, never copied from the module
under test:

    reserved_evaluations = min(max_new_evaluations, P + (G - 1) * (P - E))
    reserved_units       = 2 * (reserved_evaluations + 1)        reserved once at the start, never refunded
    need                 = {expensive_calls: reserved_units,
                            wall_clock_s: min(total_s + 600, reserved_units * 270 + 300)}
    increase calls       = min(shortfall_calls, need_calls, 140)
    increase wall        = 0 if shortfall_wall == 0 else min(shortfall_wall, need_wall, 15000) + 60

where shortfall = max(0, need - (limit - used)). Reused individuals never change the need (spec 7). No GA is run here
(the job lane is ``test_sequence_ga_jobs.py``); the world is the product HTTP path (public 1UBQ, the real tiny M20
set, the labeled synthetic phenol SDF). The server test process never imports RDKit, Meeko, MDAnalysis or PDBFixer.
"""
from __future__ import annotations

import ast
import copy
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_sequence_ga_jobs import PROTOCOL, TOOL, base, ga_args, world  # noqa: F401 (module fixture)

from mw import analysis_executions, analysis_plans, workflows
from mw import sequence_ga_inputs as GI
from mw import sequence_ga_jobs as SJ
from mw.api import app as api_module
from mw.jobs.queue import JobQueue
from mw.runtime.guards import BudgetLimits
from mw.runtime.orchestrator import ApprovalRequired
from mw.tools.energetic import JOB_ONLY_TOOLS, JOB_PROTOCOLS
from mw.workspace import new_run

MW = Path(__file__).resolve().parents[1] / "mw"
ROUTE = "/runs/{rid}/sequence_ga/limit_approval"
M19_ROUTE = "/runs/{rid}/docking/batches/limit_approval"
M22_ROUTE = "/runs/{rid}/ligand/ga/limit_approval"
AXES = ("expensive_calls", "wall_clock_s")
CONTEXT_KEYS = {"purpose", "selection_sha256", "reserved_evaluations", "reserved_units", "needed", "shortfall",
                "increase", "limits_before", "limits_after"}
RESPONSE_KEYS = {"raised", "selection_sha256", "reserved_evaluations", "reserved_units", "needed", "shortfall_before",
                 "increase", "limits_before", "limits_after", "shortfall_after", "event_seq", "budget"}
DEFAULT = {"seed": 1, "population_size": 8, "generations": 5, "elite_count": 2, "tournament_size": 2,
           "crossover_fraction": 0.5, "random_fraction": 0.2, "max_mutations": 3, "patience": 3,
           "max_new_evaluations": 32, "total_s": 7200}
LARGEST = {**DEFAULT, "population_size": 16, "generations": 8, "elite_count": 0, "max_new_evaluations": 64,
           "total_s": 14400}


def _budget(calls_used=0, wall_used=0.0, calls_limit=8, wall_limit=1800.0) -> dict:
    return {"expensive_calls": {"used": calls_used, "limit": calls_limit},
            "wall_clock_s": {"used": wall_used, "limit": wall_limit}}


def _apply(snapshot: dict, increase: dict) -> dict:
    out = copy.deepcopy(snapshot)
    for axis, amount in increase.items():
        out[axis]["limit"] += amount
    return out


# ----------------------------------------------------------------- reservation and need (pure, hand computed)
@pytest.mark.parametrize(("ga", "evaluations", "units", "wall", "partial"), [
    (DEFAULT, 32, 66, 7800, True),                   # min(32, 8 + 4 x 6 = 32); 2 x 33; min(7800, 18120)
    (LARGEST, 64, 130, 15000, True),                 # min(64, 16 + 7 x 16); 2 x 65; min(15000, 35400)
    ({**DEFAULT, "population_size": 4, "generations": 1, "max_new_evaluations": 4, "total_s": 600}, 4, 10, 1200,
     True),                                          # 2 x 5 = 10; min(1200, 2 970); 2700 > 600
    ({**DEFAULT, "population_size": 12, "generations": 1, "max_new_evaluations": 64}, 12, 26, 7320, False),
    ({**DEFAULT, "population_size": 6, "generations": 8, "elite_count": 4, "max_new_evaluations": 64,
      "total_s": 14400}, 20, 42, 11640, False),     # min(64, 6 + 7 x 2); 42 x 270 + 300 = 11640
])
def test_reserved_units_need_and_may_be_partial(ga, evaluations, units, wall, partial):
    assert GI.reserved_evaluations(ga) == evaluations
    assert GI.reserved_units(ga) == units == 2 * (evaluations + 1)
    assert GI.needed_budget(ga) == {"expensive_calls": units, "wall_clock_s": wall}
    assert GI.full_run_may_be_partial(ga) is partial


@pytest.mark.parametrize(("ga", "snapshot", "expected"), [
    (DEFAULT, _budget(0, 0.0, 66, 7800.0), {"expensive_calls": 0, "wall_clock_s": 0}),          # nothing short
    (DEFAULT, _budget(0, 0.0), {"expensive_calls": 58, "wall_clock_s": 6060.0}),                # 66 - 8; 7800 - 1800
    (LARGEST, _budget(0, 0.0, 0, 0.0), {"expensive_calls": 130, "wall_clock_s": 15060.0}),     # need-capped
    (LARGEST, _budget(10, 100.0, 0, 0.0), {"expensive_calls": 130, "wall_clock_s": 15060.0}),  # shortfall > need
])
def test_limit_increase_is_the_shortfall_with_the_wall_margin(ga, snapshot, expected):
    needed = GI.needed_budget(ga)
    increase = GI.limit_increase(needed, snapshot)
    assert increase == expected
    raised = _apply(snapshot, increase)
    if snapshot["expensive_calls"]["used"] <= snapshot["expensive_calls"]["limit"]:
        assert GI.shortfall(needed, raised)["expensive_calls"] == 0
    if snapshot["wall_clock_s"]["used"] - snapshot["wall_clock_s"]["limit"] <= 60:   # the margin absorbs <= 60 s
        assert GI.shortfall(needed, raised)["wall_clock_s"] == 0
    if GI.shortfall(needed, raised) == dict.fromkeys(AXES, 0):   # idempotent: nothing short, nothing raised
        assert GI.limit_increase(needed, raised) == dict.fromkeys(AXES, 0)


# ----------------------------------------------------------------- not a tool, plan step, workflow or model action
def _callers(tree: ast.AST, attribute: str) -> set[str]:
    return {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for call in ast.walk(node) if isinstance(call, ast.Attribute) and call.attr == attribute}


def test_raise_limits_is_called_only_by_the_three_limit_approvals_from_their_routes():
    names = {"limit_approval", "sequence_ga_limit_approval", "raise_limits", "sequence_ga_design_limit_approval"}
    for name in names:
        assert name not in api_module.REGISTRY.specs and name not in api_module.SUPPORTED_TOOLS
        assert name not in JOB_ONLY_TOOLS and name not in JOB_PROTOCOLS
        assert name not in analysis_plans.OPERATIONS and name not in analysis_executions.JOB_TOOLS
        assert name not in workflows._STEP_TO_TOOL.values()
    assert TOOL not in analysis_executions.JOB_TOOLS and PROTOCOL not in {
        spec.get("protocol") for spec in analysis_plans.OPERATIONS.values()}
    assert all(spec.get("tool") != TOOL for spec in analysis_plans.OPERATIONS.values())
    mentions = {str(path.relative_to(MW)) for path in MW.rglob("*.py")
                if any(name in path.read_text() for name in ("raise_limits", "limit_approval"))}
    assert mentions == {"runtime/orchestrator.py", "docking_batch_jobs.py", "ligand_ga_jobs.py", "sequence_ga_jobs.py",
                        "api/app.py"}
    lanes = {"docking_batch_jobs": ast.parse((MW / "docking_batch_jobs.py").read_text()),
             "ligand_ga_jobs": ast.parse((MW / "ligand_ga_jobs.py").read_text()),
             "sequence_ga_jobs": ast.parse((MW / "sequence_ga_jobs.py").read_text())}
    # Run.raise_limits: exactly the M19, M22 and M23 limit approvals, and they never call or import each other.
    for module, tree in lanes.items():
        assert _callers(tree, "raise_limits") == {"limit_approval"}, module
        approval = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and
                        node.name == "limit_approval")
        called = {call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", None)
                  for call in ast.walk(approval) if isinstance(call, ast.Call)}
        assert "limit_approval" not in called
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
        assert "limit_approval" not in imported
        modules = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        names_ = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                  for alias in node.names}
        for other in set(lanes) - {module}:
            assert other not in names_ and not any(item.endswith(other) for item in modules), (module, other)
    # Each limit approval is reached from its own route only.
    app_tree = ast.parse((MW / "api/app.py").read_text())
    assert _callers(app_tree, "limit_approval") == {"docking_batch_limit_approval", "ligand_ga_limit_approval",
                                                    "sequence_ga_limit_approval"}
    for name, module in (("docking_batch_limit_approval", "docking_batch_jobs"),
                         ("ligand_ga_limit_approval", "ligand_ga_jobs"),
                         ("sequence_ga_limit_approval", "sequence_ga_jobs")):
        route = next(node for node in ast.walk(app_tree) if isinstance(node, ast.AsyncFunctionDef) and
                     node.name == name)
        owners = {call.value.id for call in ast.walk(route) if isinstance(call, ast.Attribute) and
                  call.attr == "limit_approval" and isinstance(call.value, ast.Name)}
        assert owners == {module}
    assert _callers(app_tree, "raise_limits") == set()
    routes = sorted((route.path, sorted(route.methods)) for route in api_module.app.routes
                    if getattr(route, "path", "").endswith("limit_approval"))
    assert routes == sorted([(M19_ROUTE, ["POST"]), (M22_ROUTE, ["POST"]), (ROUTE, ["POST"])])


def test_dry_run_permits_no_raise_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path / "runs")
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    rid = client.post("/runs", json={"goal": "M23 dry", "dry_run": True}).json()["run_id"]
    raw = (tmp_path / "runs" / rid / "events.jsonl").read_bytes()
    refused = client.post(ROUTE.format(rid=rid), json={})
    assert refused.status_code == 412 and refused.json()["detail"]["reason_code"] == "dry_run"
    assert (tmp_path / "runs" / rid / "events.jsonl").read_bytes() == raw
    unknown = client.post(ROUTE.format(rid=rid), params={"x": 1}, json={})
    assert unknown.status_code == 422 and (tmp_path / "runs" / rid / "events.jsonl").read_bytes() == raw


# ----------------------------------------------------------------- the product path (no GA is run here)
def _client(root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _limits(run) -> dict:
    snapshot = run.budget_snapshot()
    return {axis: snapshot[axis]["limit"] for axis in AXES}


def test_admission_429_charges_nothing_then_the_raise_is_the_shortfall_once(base, tmp_path, monkeypatch):  # noqa: F811
    run, root = world(base, tmp_path)
    rid = base["rid"]
    client = _client(root, monkeypatch)
    events_path = root / rid / "events.jsonl"
    route = ROUTE.format(rid=rid)
    args = ga_args(base)   # reserved min(7, 4 + 3) = 7 -> 16 units; wall min(1200, 16 x 270 + 300 = 4620) = 1200
    needed = {"expensive_calls": 16, "wall_clock_s": 1200}
    body = {"protocol_id": PROTOCOL, "args": args, "timeout_s": 1200}

    # Malformed request: refused like a submission, nothing written.
    raw = events_path.read_bytes()
    bad = client.post(route, json={**args, "timeout_s": 60})
    assert bad.status_code == 422 and bad.json()["detail"]["reason_code"] == "invalid_job_arguments"
    assert events_path.read_bytes() == raw

    # Short on both axes (a test-only limit update): 429 ga_limit_raise_required, no job, nothing charged.
    run = api_module._run(rid)
    run._refresh()
    used = run.budget_snapshot()
    run.update_limits(BudgetLimits(expensive_calls=used["expensive_calls"]["used"] + 5,
                                   wall_clock_s=used["wall_clock_s"]["used"] + 300), by="test")
    run._refresh()
    count, calls_before = len(list(run.events.read())), run.budget_snapshot()["expensive_calls"]["used"]
    refused = client.post(f"/runs/{rid}/jobs", json=body)
    assert refused.status_code == 429, refused.text
    detail = refused.json()["detail"]
    assert detail["reason_code"] == "ga_limit_raise_required" and detail["needed"] == needed
    assert detail["shortfall"]["expensive_calls"] == 11 and detail["shortfall"]["wall_clock_s"] > 0
    new = list(run.events.read())[count:]
    assert not [e for e in new if e["type"] in {"job_submitted", "budget_reserved", "budget_limit_updated"}]
    run._refresh()
    assert run.budget_snapshot()["expensive_calls"]["used"] == calls_before
    before_limits = _limits(run)
    count = len(list(run.events.read()))

    # The approval: exactly the shortfall (+ 60 s on the wall axis), one human event with the GA context.
    approved = client.post(route, json=args)
    assert approved.status_code == 200, approved.text
    answer = approved.json()
    assert set(answer) == RESPONSE_KEYS and answer["raised"] is True
    assert (answer["reserved_units"], answer["reserved_evaluations"]) == (16, 7)
    new = list(run.events.read())[count:]
    limit_events = [e for e in new if e["type"] == "budget_limit_updated"]
    assert len(limit_events) == 1 and limit_events[0]["seq"] == answer["event_seq"]
    assert {e["type"] for e in new} <= {"budget_limit_updated", "wall_charged"}   # + runtime overhead
    event = limit_events[0]
    assert event["by"] == "human" and set(event["context"]) == CONTEXT_KEYS
    context = event["context"]
    assert context["purpose"] == "sequence_ga_limit_raise" and context["reserved_units"] == 16
    assert context["needed"] == needed and context["shortfall"]["expensive_calls"] == 11
    short_wall = context["shortfall"]["wall_clock_s"]
    assert 900 <= short_wall < 905   # 1200 needed, 300 s left minus the runtime overhead charged meanwhile
    assert context["increase"] == {"expensive_calls": 11, "wall_clock_s": short_wall + 60}
    assert context["limits_before"] == before_limits
    assert context["limits_after"] == {"expensive_calls": before_limits["expensive_calls"] + 11,
                                       "wall_clock_s": before_limits["wall_clock_s"] + short_wall + 60}
    assert context["selection_sha256"] == answer["selection_sha256"] == SJ.submission(run, args, 1200)[0][
        "selection_sha256"]
    assert answer["shortfall_after"] == {"expensive_calls": 0, "wall_clock_s": 0}
    assert _limits(run) == context["limits_after"]

    # Idempotent: a second approval changes nothing and writes no event.
    raw = events_path.read_bytes()
    again = client.post(route, json=args).json()
    assert again["raised"] is False and again["event_seq"] is None and events_path.read_bytes() == raw
    assert again["increase"] == {"expensive_calls": 0, "wall_clock_s": 0}
    assert again["limits_before"] == again["limits_after"] == context["limits_after"]

    # The same GA is now admitted (queued; not started here) and the raised limits replay events-only.
    submitted = client.post(f"/runs/{rid}/jobs", json=body)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "queued"
    JobQueue(api_module._run(rid)).request_cancel(submitted.json()["job_id"])
    replay = tmp_path / "events_only"
    (replay / rid).mkdir(parents=True)
    shutil.copyfile(events_path, replay / rid / "events.jsonl")
    reopened = new_run(replay, run_id=rid, dry_run=False)
    reopened._refresh()
    assert _limits(reopened) == context["limits_after"]


def test_the_need_ignores_reuse_and_nothing_short_writes_nothing(base, tmp_path, monkeypatch):  # noqa: F811
    run, root = world(base, tmp_path)
    rid = base["rid"]
    run.update_limits(BudgetLimits(expensive_calls=40, wall_clock_s=9000), by="test")   # nothing short
    client = _client(root, monkeypatch)
    events_path = root / rid / "events.jsonl"
    args = ga_args(base)
    raw = events_path.read_bytes()
    unchanged = client.post(ROUTE.format(rid=rid), json=args)
    assert unchanged.status_code == 200, unchanged.text
    body = unchanged.json()
    assert body["raised"] is False and body["event_seq"] is None and body["reserved_units"] == 16
    assert body["needed"] == {"expensive_calls": 16, "wall_clock_s": 1200}
    assert body["shortfall_before"] == body["shortfall_after"] == {"expensive_calls": 0, "wall_clock_s": 0}
    assert events_path.read_bytes() == raw
    # A reuse plan covering the reference row and every key (labeled internal hook) leaves the need unchanged.
    monkeypatch.setattr(SJ, "reuse_plan", lambda *_a: {"records": [{"key": "0"}] * 26,
                                                       "reference": {"key": "wild_type"}})
    assert client.post(ROUTE.format(rid=rid), json=args).json()["needed"] == body["needed"]


def test_a_cancelled_run_refuses_the_raise_and_writes_nothing(base, tmp_path, monkeypatch):  # noqa: F811
    _run, root = world(base, tmp_path)
    rid = base["rid"]
    client = _client(root, monkeypatch)
    run = api_module._run(rid)
    run.update_limits(BudgetLimits(expensive_calls=0, wall_clock_s=100), by="test")   # short on both axes
    run.cancel()
    events_path = root / rid / "events.jsonl"
    raw = events_path.read_bytes()
    refused = client.post(ROUTE.format(rid=rid), json=ga_args(base))
    assert refused.status_code == 409, refused.text
    assert refused.json() == {"ok": False, "error": "cancelled", "message": "run cancelled"}
    assert events_path.read_bytes() == raw


def test_the_raise_never_grants_the_first_expensive_approval(base, tmp_path, monkeypatch):  # noqa: F811
    """A run without the first expensive approval: the raise adds limits only; the GA still needs the approval."""
    _run, root = world(base, tmp_path)
    rid = base["rid"]
    client = _client(root, monkeypatch)
    run = api_module._run(rid)
    run.update_limits(BudgetLimits(expensive_calls=0, wall_clock_s=100), by="test")
    body = client.post(ROUTE.format(rid=rid), json=ga_args(base)).json()
    assert body["raised"] is True and body["increase"]["expensive_calls"] == 16
    assert body["limits_after"]["expensive_calls"] == 16 and body["shortfall_after"]["wall_clock_s"] == 0
    kinds = [e["type"] for e in run.events.read()]
    assert "approval_resolved" not in kinds and "approval_requested" not in kinds
    run._refresh()
    assert run.approved_expensive is False
    with pytest.raises(ApprovalRequired) as caught:
        run.reserve_attempt("attempt_m23", "job_m23", TOOL, {}, units=16)
    assert caught.value.gate == "expensive_first_call"
