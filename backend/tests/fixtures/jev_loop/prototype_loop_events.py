"""PROTOTYPE (M25 T1 measurement only, never product code): the four new loop event types and replay / settlement.

Preflight item (g) of the M25 plan. Two events-only copies (A, B) of one real run (``--source-run``: the ligand run
``prototype_engine_calls.py --keep`` leaves, with real M17 / M18 / M19 jobs and reservations) go through the same
steps with the UNMODIFIED product code: science consent on, a real ``build_jev_projection`` call, one approved science
send through ``jev_sends.run_send`` with a fixture ``httpx.MockTransport`` gate (``jev_send_fixture.Fake``, inert
sentinel credential, fixture reply), then a simulated crash with an unsettled science reservation (reserved, audited
``prepared`` / ``dispatch_started``, no reply). Copy B additionally gets the spec 3.1 / 6.1 / 6.3 / 8.1 shaped events
``jev_loop_created``, ``jev_loop_compute_approved``, ``jev_loop_docking_abandoned`` and ``jev_loop_ended`` between the
steps (``EventLog.append`` takes any type name at run time; ``EventType`` is a typing ``Literal``). The derived states
of A and B are compared: replay (``_refresh``), settlement (``_settle_egress`` through the send), the crash
reconciliation (``_reconcile_egress`` through ``_mutation``), the job queue, the M18 reuse index, the M24 send records
and status, an events-only store rebuild and the HTTP status codes of the run's GET routes.

No network, no credential. Runs live under ``--work`` (default ``runs/m25-t1-preflight/events``), deleted at the end
unless ``--keep``. Prints one JSON report.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[1]
BACKEND = TESTS.parent
REPO = BACKEND.parent
for extra in (str(BACKEND), str(TESTS)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from fastapi.testclient import TestClient
from jev_send_fixture import SENTINEL, Fake, reply

from mw import docking_batch_inputs, docking_bundle
from mw import jev_constants as J
from mw import jev_projection as P
from mw import jev_sends as S
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.jobs.queue import JobQueue
from mw.workspace import new_run

GET_ROUTES = ("", "/events", "/budget", "/jobs", "/reports", "/jev/status", "/jev/sends", "/docking/results",
              "/docking/batches", "/ligand/candidate_sets", "/ligand/inspections", "/ligand/ga/results",
              "/sequence_ga/results", "/mutation_models", "/mutation_candidate_sets", "/analysis/executions",
              "/analysis/plans", "/viewer/online", "/viewer/intents", "/viewer/scenes", "/viewer/figures",
              "/numbering_maps", "/site_annotations", "/pockets")
LOOP_ID = "00000000-0000-4000-8000-0000000000aa"


def loop_events(run: Any, candidate_set: str, ids: list[str], stage: str) -> list[str]:
    """Spec-shaped loop events (payloads per spec 3.1, 6.1, 6.3, 8.1); only the type names matter for replay."""
    if stage == "created":
        pins = docking_bundle.require_ready()
        setup = {"receptor_handle": "obj://x/chemical_import/" + "0" * 64, "box": {"source": "ligand_range",
                                                                                  "margin_A": 8.0}}
        payload = {"loop_id": LOOP_ID, "branch": "ligand",
                   "pool": {"source": {"handle": candidate_set, "schema": "ligand_candidate_set@1"},
                            "structure": None, "candidates": ids[:5], "filter": None},
                   "goal": "explore", "loop_seed": 123456789, "iteration_cap": 5, "setup": setup,
                   "setup_sha256": "1" * 64, "pins": pins}
        run.events.append("jev_loop_created", **payload)
        return ["jev_loop_created"]
    if stage == "approved":
        run.events.append("jev_loop_compute_approved", loop_id=LOOP_ID, iteration=1, step="ligand_dock",
                          candidate_ref=ids[0], decided_by="human", proposal_handle=None, call_key="2" * 64,
                          units=1, approved_by="human")
        run.events.append("jev_loop_docking_abandoned", loop_id=LOOP_ID, iteration=1, candidate_ref=17)
        return ["jev_loop_compute_approved", "jev_loop_docking_abandoned"]
    run.events.append("jev_loop_ended", loop_id=LOOP_ID, end_reason="ended_by_user", result_handle=None)
    return ["jev_loop_ended"]


def derived(run: Any) -> dict[str, Any]:
    events = list(run.events.read())
    snapshot = run.budget.snapshot()
    jobs = {job["job_id"]: job["status"] for job in JobQueue(run).list()}
    # audit ids are random per send and the proposal handle hashes its content (which holds the audit id)
    sends = [{k: v for k, v in record.items() if not k.endswith("_event_seq") and k not in ("audit_id",
                                                                                           "choice_handle")}
             for record in S.list_sends(events)]
    status = S.status_for(run, events)
    return {"budget": {axis: snapshot[axis] for axis in ("expensive_calls", "external_tokens", "usd")},
            "wall_clock_used_s": snapshot["wall_clock_s"]["used"], "egress_stop_reason": run.egress_stop_reason,
            "egress_unknown": run.egress_unknown, "approved_expensive": run.approved_expensive,
            "cancelled": run.cancelled, "jobs": jobs,
            "reuse_index": docking_batch_inputs.published_m18_results(events),
            "sends": sends, "status": {k: v for k, v in status.items() if k != "budget"},
            "status_budget": status["budget"]}


def scenario(root: Path, source: Path, with_loop: bool) -> dict[str, Any]:
    rid = source.name
    (root / rid).mkdir(parents=True)
    shutil.copyfile(source / "events.jsonl", root / rid / "events.jsonl")
    run = new_run(root, run_id=rid, dry_run=False)
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
    candidate_set = next(e["handle"] for e in run.events.read() if e["type"] == "object_created"
                         and e.get("kind") == "ligand_candidate_set")
    ids = [row["id"] for row in run.store.load(candidate_set)["candidates"]]
    appended: list[str] = []
    S.set_consent(run, True)
    if with_loop:
        appended += loop_events(run, candidate_set, ids, "created")
    projection = run.call(J.TOOL, {"source": candidate_set, "candidates": ids[:3]}).handle
    content = run.store.load(projection)
    fake = Fake(lambda request: reply("c01"))
    record = asyncio.run(S.run_send(run, fake.gate, send_id="00000000-0000-4000-8000-0000000000bb",
                                    projection=projection, body_sha256=P.body_sha256(P.projection_body(content)[1]),
                                    confirm=J.CONFIRM))
    if with_loop:
        appended += loop_events(run, candidate_set, ids, "approved")
    after_send = derived(new_run(root, run_id=rid, dry_run=False))
    # simulated crash: an unsettled science reservation with prepared / dispatch_started audits and no reply
    audit_id = f"eg_{uuid.uuid4().hex}"
    with run._mutation(), run._transition():
        run.events.append("budget_reserved", audit_id=audit_id, send_id="00000000-0000-4000-8000-0000000000cc",
                          external_tokens=J.reserve_tokens(content["body_bytes"]), usd=J.RESERVE_USD)
        run.events.append("egress", stage="prepared", audit_id=audit_id, scope=J.AUDIT_SCOPE, sent=False,
                          transport_invoked=False)
        run.events.append("egress", stage="dispatch_started", audit_id=audit_id, scope=J.AUDIT_SCOPE,
                          remaining_wall_s=100.0, transport_invoked=True, sent="unknown")
        run.events.append(J.EVENT_DISPATCH, send_id="00000000-0000-4000-8000-0000000000cc", audit_id=audit_id)
    if with_loop:
        appended += loop_events(run, candidate_set, ids, "ended")
    before = sum(1 for _ in run.events.read())
    reopened = new_run(root, run_id=rid, dry_run=False)
    with reopened._mutation():   # replay + _reconcile_orphans/_reconcile_egress, as every owner entry does
        pass
    added = [e["type"] + (f":{e.get('reason')}" if e["type"] == "wall_charged" else "")
             for e in list(reopened.events.read())[before:]]
    after_crash = derived(new_run(root, run_id=rid, dry_run=False))
    # events-only store rebuild in a fresh root
    copy_root = root.parent / (root.name + "_eventsonly")
    (copy_root / rid).mkdir(parents=True)
    shutil.copyfile(root / rid / "events.jsonl", copy_root / rid / "events.jsonl")
    copy = new_run(copy_root, run_id=rid, dry_run=False)
    with copy._owner():
        copy.store.rebuild_from_events()
    rebuilt_equal = canonical_json(copy.store.load(projection)) == canonical_json(content)
    # GET routes through the product app
    api_module.RUNS_DIR = root
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    codes = {route or "/": client.get(f"/runs/{rid}{route}").status_code for route in GET_ROUTES}
    codes["/capabilities"] = client.get("/capabilities").status_code
    text = b"".join(path.read_bytes() for path in (root / rid).rglob("*") if path.is_file())
    return {"send_status": record["status"], "appended_loop_events": appended,
            "reopen_added_event_types": added, "after_send": after_send, "after_crash": after_crash,
            "events_only_rebuild_projection_equal": rebuilt_equal, "get_status_codes": codes,
            "sentinel_in_run_files": SENTINEL.encode() in text}


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for phase in ("after_send", "after_crash"):
        for key in a[phase]:
            if key == "wall_clock_used_s":
                out[f"{phase}.{key}_abs_diff_s"] = round(abs(a[phase][key] - b[phase][key]), 3)
            else:
                out[f"{phase}.{key}_equal"] = canonical_json(a[phase][key]) == canonical_json(b[phase][key])
    out["reopen_added_event_types_equal"] = a["reopen_added_event_types"] == b["reopen_added_event_types"]
    out["get_status_codes_equal"] = a["get_status_codes"] == b["get_status_codes"]
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=REPO / "runs/m25-t1-preflight/events")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if args.work.exists():
        shutil.rmtree(args.work)
    args.work.mkdir(parents=True)
    saved = api_module.RUNS_DIR
    try:
        a = scenario(args.work / "A", args.source_run, with_loop=False)
        b = scenario(args.work / "B", args.source_run, with_loop=True)
        report = {"A_without_loop_events": {k: a[k] for k in ("send_status", "reopen_added_event_types",
                                                               "events_only_rebuild_projection_equal",
                                                               "get_status_codes", "sentinel_in_run_files")},
                  "B_with_loop_events": {k: b[k] for k in ("send_status", "appended_loop_events",
                                                           "reopen_added_event_types",
                                                           "events_only_rebuild_projection_equal",
                                                           "sentinel_in_run_files")},
                  "A_after_crash": {k: a["after_crash"][k] for k in ("budget", "egress_stop_reason",
                                                                     "egress_unknown", "approved_expensive")},
                  "A_vs_B": compare(a, b)}
        print(json.dumps(report, indent=1, ensure_ascii=False))
    finally:
        api_module.RUNS_DIR = saved
        api_module.RUNS.clear()
        if not args.keep:
            shutil.rmtree(args.work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
