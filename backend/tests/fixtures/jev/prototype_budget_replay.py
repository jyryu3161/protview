"""PROTOTYPE (M24 T1 measurement only, never product code): does the existing ``Run`` reserve / settle / replay ledger
accept a science egress reservation that has NO ``expensive_calls`` axis, and new ``jev_*`` event types?

Each scenario writes events the way spec 5 describes ``request_science`` (with the real ``Run`` methods
``_mutation``, ``_transition``, ``events.append``, ``budget.charge`` and ``_settle_egress``; no HTTP, no credential),
then reopens the run from its event log with a fresh ``Run`` and records the replayed budget and egress stop state.
Event names ``jev_*`` and their fields are the spec 5 names, used here only to test replay tolerance. Runs live in
``_work_budget`` next to this file and are deleted at the end. Prints one JSON report.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient

from mw.api import app as api_module
from mw.workspace import new_run

WORK = HERE / "_work_budget"
BODY_BYTES = 29_828   # the measured 1MQ4 20-position body (prototype_body_size.py)
TOKENS = min(40_000, 4_096 + math.ceil(BODY_BYTES / 2))
USD = 0.10
GET_ROUTES = ("", "/events", "/budget", "/viewer/online", "/viewer/intents", "/reports", "/jobs", "/objects",
              "/analysis/executions", "/analysis/plans", "/mutation_candidate_sets", "/ligand/candidate_sets",
              "/ligand/inspections", "/docking/results", "/docking/batches", "/ligand/ga/results",
              "/sequence_ga/results", "/mutation_models", "/pockets", "/numbering_maps", "/site_annotations",
              "/viewer/scenes", "/viewer/figures", "/interface_sasa", "/openmm_minimization")


def fresh(name: str):
    return new_run(WORK, run_id=name, dry_run=False)


def audit(run, stage: str, audit_id: str, **fields: Any) -> None:
    run.events.append("egress", stage=stage, audit_id=audit_id, **fields)


def reserve(run, send_id: str) -> str:
    audit_id = f"eg_{uuid.uuid4().hex}"
    with run._transition():
        run.events.append("jev_send_approved", send_id=send_id, projection_handle="obj://x/jev_projection/0",
                          body_sha256="0" * 64, question_id="mutation_candidate_choice@1",
                          source_handle="obj://x/mutation_candidate_set/0", selection_count=20, approved_by="human")
        run.events.append("budget_reserved", audit_id=audit_id, external_tokens=TOKENS, usd=USD)
        run.budget.charge(external_tokens=TOKENS, usd=USD)
        audit(run, "prepared", audit_id, scope="science", send_id=send_id, payload_sha256="0" * 64,
              reservation={"external_tokens": TOKENS, "usd": USD}, transport_invoked=False, sent=False)
    return audit_id


def dispatch(run, audit_id: str, send_id: str) -> None:
    with run._transition():
        audit(run, "dispatch_started", audit_id, remaining_wall_s=900.0, transport_invoked=True, sent="unknown")
        run.events.append("jev_science_dispatch_started", send_id=send_id, audit_id=audit_id)


def refund(run, audit_id: str, *, skipped_audit: bool = True) -> None:
    delta = {"external_tokens": -TOKENS, "usd": -USD}
    run.events.append("egress_budget_settled", audit_id=audit_id, delta=delta,
                      actual={"external_tokens": 0, "usd": 0}, unknown_axes=[])
    run.budget.charge(**delta)
    if skipped_audit:
        audit(run, "dispatch_skipped", audit_id, reason_code="cancelled_or_deadline", transport_invoked=False,
              sent=False)


def respond(run, audit_id: str, usage: dict[str, Any]) -> tuple[list[str], bool]:
    run.events.append("wall_charged", audit_id=audit_id, seconds=0.5, reason="egress")
    run.budget.charge(wall_clock_s=0.5)
    audit(run, "response_received", audit_id, http_status=200, served_model="typesafe/jev-1.13-20260917",
          usage=usage, transport_invoked=True, sent=True)
    unknown, overrun = run._settle_egress(audit_id, usage)
    audit(run, "settled", audit_id, unknown_axes=unknown, overrun=overrun, transport_invoked=True, sent=True)
    return unknown, overrun


def outcome(run, send_id: str, audit_id: str, status: str, reason: str | None) -> None:
    run.events.append("jev_send_outcome", send_id=send_id, status=status, reason_code=reason, audit_id=audit_id,
                      requested_model="typesafe/jev-1.13", served_model=None, choice_handle=None, usage=None,
                      late=False, late_reason=None)


def state(run) -> dict[str, Any]:
    snap = run.budget.snapshot()
    return {"expensive_calls_used": snap["expensive_calls"]["used"],
            "external_tokens_used": snap["external_tokens"]["used"], "usd_used": round(snap["usd"]["used"], 12),
            "egress_unknown": run.egress_unknown, "egress_stop_reason": run.egress_stop_reason}


def reopened(name: str) -> dict[str, Any]:
    log = WORK / name / "events.jsonl"
    before = sum(1 for line in log.read_text(encoding="utf-8").splitlines() if line.strip())
    run = new_run(WORK, run_id=name, dry_run=False)   # construction already runs _refresh + _reconcile_egress
    opened = state(run)
    with run._mutation():
        pass
    added = [event["type"] + (f":{event.get('reason')}" if event["type"] == "wall_charged" else "")
             for event in list(run.events.read())[before:]]
    return {"on_open": opened, "after_mutation": state(run), "events_added_by_open_and_mutation": added}


USAGE_KNOWN = {"input_tokens": 9000, "output_tokens": 40, "external_tokens": 9040, "cost": 0.0123}
USAGE_UNKNOWN = {"input_tokens": None, "output_tokens": None, "external_tokens": None, "cost": None}


def scenario(name: str) -> dict[str, Any]:
    run = fresh(name)
    send = str(uuid.uuid4())
    live: dict[str, Any] = {}
    with run._mutation():
        run.events.append("jev_science_consent_changed", enabled=True, policy="jev_science@1", send_cap=10,
                          request_model="typesafe/jev-1.13", allowed_served_model="typesafe/jev-1.13-20260917",
                          destination="https://openrouter.ai/api/alpha/decisions")
        live["would_exceed_before"] = run.budget.would_exceed(external_tokens=TOKENS, usd=USD)
        audit_id = reserve(run, send)
        live["after_reserve"] = state(run)
        if name == "known_usage":
            dispatch(run, audit_id, send)
            live["settle"] = respond(run, audit_id, USAGE_KNOWN)
            outcome(run, send, audit_id, "completed", None)
        elif name == "refund_before_dispatch":
            refund(run, audit_id)
            outcome(run, send, audit_id, "rejected", "cancelled")
        elif name == "refund_after_dispatch_audit":
            audit(run, "dispatch_started", audit_id, remaining_wall_s=900.0, transport_invoked=True, sent="unknown")
            refund(run, audit_id)
            outcome(run, send, audit_id, "rejected", "cancelled")
        elif name == "crash_between_refund_and_skip_audit":
            audit(run, "dispatch_started", audit_id, remaining_wall_s=900.0, transport_invoked=True, sent="unknown")
            refund(run, audit_id, skipped_audit=False)
        elif name == "unknown_usage":
            dispatch(run, audit_id, send)
            live["settle"] = respond(run, audit_id, USAGE_UNKNOWN)
            outcome(run, send, audit_id, "failed", "response_invalid")
        elif name == "crash_after_dispatch_no_response":
            dispatch(run, audit_id, send)
        elif name == "overrun":
            dispatch(run, audit_id, send)
            live["settle"] = respond(run, audit_id, {**USAGE_KNOWN, "external_tokens": TOKENS + 1})
            outcome(run, send, audit_id, "completed", None)
        elif name == "shared_with_viewer_reservation":
            dispatch(run, audit_id, send)
            respond(run, audit_id, USAGE_KNOWN)
            viewer = f"eg_{uuid.uuid4().hex}"
            run.events.append("budget_reserved", audit_id=viewer, viewer_intent_id=str(uuid.uuid4()),
                              expensive_calls=1, external_tokens=16_384, usd=0.05)
            run.budget.charge(expensive_calls=1, external_tokens=16_384, usd=0.05)
            respond(run, viewer, USAGE_KNOWN)
        live["end"] = state(run)
    return {"live": live, "replay": reopened(name)}


def would_exceed_boundary() -> dict[str, Any]:
    run = fresh("would_exceed_boundary")
    out = {}
    with run._mutation():
        limit = run.budget.limits.external_tokens
        run.budget.external_tokens = limit - TOKENS
        out["exactly_at_limit"] = run.budget.would_exceed(external_tokens=TOKENS, usd=USD)
        run.budget.external_tokens = limit - TOKENS + 1
        out["one_token_over"] = run.budget.would_exceed(external_tokens=TOKENS, usd=USD)
        run.budget.external_tokens = 0
        run.budget.usd = run.budget.limits.usd - USD + 1e-9
        out["usd_over"] = run.budget.would_exceed(external_tokens=TOKENS, usd=USD)
        run._refresh()
    return out


def api_routes() -> dict[str, Any]:
    api_module.RUNS_DIR = WORK
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    plain = fresh("plain_baseline")
    with plain._mutation():
        pass
    statuses = {}
    for rid in ("plain_baseline", "known_usage", "unknown_usage"):
        api_module.RUNS.clear()
        statuses[rid] = {route or "/": client.get(f"/runs/{rid}{route}").status_code for route in GET_ROUTES}
    listed = client.get("/runs")
    return {"statuses": statuses,
            "same_status_codes_as_baseline": {rid: statuses[rid] == statuses["plain_baseline"]
                                              for rid in ("known_usage", "unknown_usage")},
            "list_runs_status": listed.status_code, "list_runs_count": len(listed.json())}


def main() -> int:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()
    try:
        report: dict[str, Any] = {"reservation": {"external_tokens": TOKENS, "usd": USD, "body_bytes": BODY_BYTES}}
        for name in ("known_usage", "refund_before_dispatch", "refund_after_dispatch_audit",
                     "crash_between_refund_and_skip_audit", "unknown_usage", "crash_after_dispatch_no_response",
                     "overrun", "shared_with_viewer_reservation"):
            report[name] = scenario(name)
        report["would_exceed_boundary"] = would_exceed_boundary()
        report["api_get_routes"] = api_routes()
        print(json.dumps(report, indent=1, default=list))
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
