"""PROTOTYPE (M25 T1 measurement only, never product code): job-queue semantics the loop relies on.

Preflight items (a), (e) (locks) and (l) of the M25 plan, measured on the UNMODIFIED queue with real M21
``openmm_mutation_model_v1`` jobs (project ``.venv``: OpenMM 8.6.0, PDBFixer 1.12.0) on public 1UBQ (I44, the cheap
M20 tool through ``Run.call``). Each case uses another candidate index of the same M20 set, so its call key is its own:

1. ``cancel_before_start``: submit -> cancel (queued) -> submit again (other ``timeout_s``) -> start / retry.
2. ``approval_blocked_cancel``: first expensive call -> ``ApprovalRequired`` (claimed, blocked) -> cancel.
3. ``approval_blocked_restart``: blocked as in 2 -> a fresh ``Run`` object + ``reconcile_run`` (server restart) ->
   retry (outside any loop) -> cancel.
4. ``approval_blocked_then_done``: blocked as in 2 -> approve -> start again -> done (the full event order); while it
   runs, the run owner / mutation / submit / cancel are tried from another thread.
5. ``cancel_after_reservation``: a measurement-process wrapper on this ``Run`` instance's ``reserve_attempt`` cancels
   the job right after the reservation returns (the window between ``budget_reserved`` and ``job_dispatch_intent``).
6. ``timeout_failed``: ``timeout_s`` 1 -> failed after the reservation -> retry accepted -> cancel.
7. Lock reentrancy: ``_owner`` inside ``_owner``, ``submit`` / ``start`` inside ``_mutation``, ``_transition``.

Runs live under ``--work`` (default ``runs/m25-t1-preflight/queue``, Git-excluded), deleted at the end unless
``--keep``. No network, no credential. Prints one JSON report.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[1]
BACKEND = TESTS.parent
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import psutil

from mw import mutation_model_bundle
from mw.core.errors import ToolFailure
from mw.jobs import process_identity
from mw.jobs.queue import JobQueue
from mw.runtime import orchestrator
from mw.runtime.orchestrator import ApprovalRequired, RunCancelled
from mw.workspace import new_run

FIX = TESTS / "fixtures"
I44 = {"model_number": 1, "chain_auth": "A", "seq_auth": 44, "icode": "", "resname": "ILE"}
SEED = 20261007
RUN_ID = "m25_t1_queue"
PROTOCOL = mutation_model_bundle.PROTOCOL


def events(run: Any) -> list[dict[str, Any]]:
    return list(run.events.read())


def outcome(call: Any) -> str:
    try:
        value = call()
    except ToolFailure as exc:
        return f"ToolFailure {exc.cls.value}: {exc.message}" + (" (busy)" if exc.detail.get("busy") else "")
    except ApprovalRequired as exc:
        return f"ApprovalRequired {exc.gate}"
    except RunCancelled as exc:
        return f"RunCancelled: {exc}"
    if isinstance(value, dict) and "status" in value:
        return f"accepted -> {value['status']}"
    return "accepted"


def trace(run: Any, job_id: str) -> list[str]:
    """Event types of one job in log order. A reservation carries no job_id: it is linked by root_call_id = job_id."""
    attempts: set[str] = set()
    out = []
    for event in events(run):
        kind = event["type"]
        if kind == "budget_reserved" and event.get("root_call_id") == job_id:
            attempts.add(event["attempt_id"])
        linked = (event.get("job_id") == job_id or event.get("root_call_id") == job_id or
                  (kind == "job_submitted" and event["job"]["job_id"] == job_id) or
                  (kind == "wall_charged" and event.get("call_id") in attempts) or
                  (kind in ("approval_requested", "approval_resolved") and event.get("gate") == "expensive_first_call"))
        if linked:
            extra = (f":{event['status']}:attempt={'set' if event.get('attempt_id') else 'None'}"
                     if kind == "job_terminal" else f":{event['reason']}" if kind in ("job_blocked",) else
                     f":units={event['expensive_calls']}" if kind == "budget_reserved" else "")
            out.append(kind + extra)
    return out


def reservations(run: Any, job_id: str) -> list[dict[str, Any]]:
    return [{k: e[k] for k in ("attempt_id", "root_call_id", "tool", "expensive_calls")} | {"has_job_id": "job_id" in e}
            for e in events(run) if e["type"] == "budget_reserved" and e.get("root_call_id") == job_id]


def kill_leftovers(run: Any) -> int:
    killed = 0
    for event in events(run):
        if event["type"] == "job_worker_started" and process_identity.matches(event["pid"], event["start_identity"]):
            try:
                psutil.Process(event["pid"]).kill()
                killed += 1
            except psutil.Error:
                pass
    return killed


def state(queue: JobQueue, job_id: str) -> dict[str, Any]:
    job = queue.get(job_id)
    return {key: job.get(key) for key in ("status", "blocked_reason", "attempt_id", "attempt_ordinal",
                                          "cancel_requested", "timeout_s")} | {
        "attempt_id": None if job.get("attempt_id") is None else "set"}


def measure(work: Path) -> dict[str, Any]:
    run = new_run(work, run_id=RUN_ID, dry_run=False)
    loaded = run.call("load_structure", {"source": str(FIX / "public_1ubq.cif"), "model_index": 0}).handle
    prepared = run.call("prepare_structure", {"structure": loaded}).handle
    candidate_set = run.call("generate_mutation_candidates", {
        "structure": prepared, "sources": {"pocket": None, "ligand_shell": None, "residues": [I44]}}).handle
    rows = run.store.load(candidate_set)["candidates"]
    by_to = {row["to"]: row["index"] for row in rows}

    def args(to: str) -> dict[str, Any]:
        return {"candidate_set": candidate_set, "candidate_index": by_to[to], "seed": SEED,
                "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}

    queue = JobQueue(run)
    out: dict[str, Any] = {"candidate_count": len(rows)}

    # 1. cancel before start
    first = queue.submit(PROTOCOL, args("A"), timeout_s=120)
    cancel = queue.request_cancel(first["job_id"])
    again = queue.submit(PROTOCOL, args("A"), timeout_s=240)
    out["1_cancel_before_start"] = {
        "cancel": cancel["status"], "after_cancel": state(queue, first["job_id"]),
        "resubmit_same_job_id": again["job_id"] == first["job_id"], "resubmit_status": again["status"],
        "resubmit_timeout_s_kept": again["timeout_s"],
        "start": outcome(lambda: queue.start(first["job_id"])), "retry": outcome(lambda: queue.retry(first["job_id"])),
        "reservations": reservations(run, first["job_id"]), "trace": trace(run, first["job_id"])}

    # 2. first expensive call blocked for approval, then cancelled
    blocked = queue.submit(PROTOCOL, args("C"), timeout_s=120)
    start_blocked = outcome(lambda: queue.start(blocked["job_id"]))
    while_blocked = state(queue, blocked["job_id"])
    cancel = queue.request_cancel(blocked["job_id"])
    out["2_approval_blocked_cancel"] = {
        "start": start_blocked, "while_blocked": while_blocked, "cancel": cancel["status"],
        "after_cancel": state(queue, blocked["job_id"]),
        "resubmit_same_job_id": queue.submit(PROTOCOL, args("C"), timeout_s=120)["job_id"] == blocked["job_id"],
        "reservations": reservations(run, blocked["job_id"]), "trace": trace(run, blocked["job_id"])}

    # 3. blocked, then a server restart (fresh Run object + reconcile_run), then a retry outside any loop
    restart = queue.submit(PROTOCOL, args("D"), timeout_s=120)
    start_blocked = outcome(lambda: queue.start(restart["job_id"]))
    reopened = new_run(work, run_id=RUN_ID, dry_run=False)
    JobQueue(reopened).reconcile_run()
    queue = JobQueue(reopened)
    after = state(queue, restart["job_id"])
    terminal = next(e for e in events(reopened) if e["type"] == "job_terminal" and e["job_id"] == restart["job_id"])
    retry = outcome(lambda: queue.retry(restart["job_id"]))
    resubmit = queue.submit(PROTOCOL, args("D"), timeout_s=120)
    out["3_approval_blocked_restart"] = {
        "start": start_blocked, "after_reconcile": after, "terminal_failure": terminal.get("failure"),
        "retry": retry, "after_retry": state(queue, restart["job_id"]),
        "resubmit_same_job_id": resubmit["job_id"] == restart["job_id"], "resubmit_status": resubmit["status"],
        "reservations": reservations(reopened, restart["job_id"])}
    queue.request_cancel(restart["job_id"])
    out["3_approval_blocked_restart"]["trace"] = trace(reopened, restart["job_id"])
    run = reopened

    # 4. blocked, approve, start again (claimed + approval_or_cancel restarts) -> done; probe locks while it runs
    main = queue.submit(PROTOCOL, args("W"), timeout_s=120)
    start_blocked = outcome(lambda: queue.start(main["job_id"]))
    run.approve("expensive_first_call", by="test")
    result: dict[str, Any] = {}

    def worker() -> None:
        began = time.monotonic()
        result["job"] = queue.start(main["job_id"])
        result["seconds"] = round(time.monotonic() - began, 2)

    thread = threading.Thread(target=worker)
    thread.start()
    while state(JobQueue(run), main["job_id"])["status"] != "running" and thread.is_alive():
        time.sleep(0.05)
    probe = JobQueue(run)

    def hold_owner() -> None:
        with run._owner():
            pass

    def hold_mutation() -> None:
        with run._mutation():
            pass

    probe_job = probe.submit(PROTOCOL, args("Y"), timeout_s=120)
    probes = {"status_seen": state(probe, main["job_id"])["status"],
              "run_owner_from_other_thread": outcome(hold_owner),
              "run_mutation_from_other_thread": outcome(hold_mutation),
              "submit_other_job_while_running": f"accepted -> {probe_job['status']}",
              "start_other_job_while_running": outcome(lambda: probe.start(probe_job["job_id"])),
              "cancel_other_job_while_running": probe.request_cancel(probe_job["job_id"])["status"],
              "get_and_list_while_running": len(probe.list()) > 0}
    thread.join()
    out["4_approval_blocked_then_done"] = {
        "first_start": start_blocked, "second_start_seconds": result.get("seconds"),
        "status": result["job"]["status"], "probes_while_running": probes,
        "start_done_job": outcome(lambda: queue.start(main["job_id"])),
        "retry_done_job": outcome(lambda: queue.retry(main["job_id"])),
        "cancel_done_job": queue.request_cancel(main["job_id"])["status"],
        "reservations": reservations(run, main["job_id"]), "trace": trace(run, main["job_id"])}

    # 5. cancel in the window after the reservation and before job_dispatch_intent
    window = queue.submit(PROTOCOL, args("F"), timeout_s=120)
    original = run.reserve_attempt

    def reserve_then_cancel(*a: Any, **k: Any) -> Any:
        event = original(*a, **k)
        JobQueue(run).request_cancel(window["job_id"])
        return event

    run.reserve_attempt = reserve_then_cancel   # this Run instance only, in this measurement process
    used_before = run.budget_snapshot()["expensive_calls"]["used"]
    try:
        window_start = outcome(lambda: queue.start(window["job_id"]))
    finally:
        del run.reserve_attempt
    out["5_cancel_after_reservation"] = {
        "start": window_start, "after": state(queue, window["job_id"]),
        "expensive_used_delta": run.budget_snapshot()["expensive_calls"]["used"] - used_before,
        "dispatch_intents": sum(e["type"] == "job_dispatch_intent" and e.get("job_id") == window["job_id"]
                                for e in events(run)),
        "reservations": reservations(run, window["job_id"]), "trace": trace(run, window["job_id"])}

    # 6. failure after the process started (timeout 1 s), retry accepted outside any loop
    slow = queue.submit(PROTOCOL, args("G"), timeout_s=1)
    slow_start = outcome(lambda: queue.start(slow["job_id"]))
    failed = state(queue, slow["job_id"])
    failure = queue.get(slow["job_id"]).get("failure")
    retry = outcome(lambda: queue.retry(slow["job_id"]))
    resubmit = queue.submit(PROTOCOL, args("G"), timeout_s=120)
    out["6_timeout_failed"] = {
        "start": slow_start, "after": failed, "failure": failure, "retry": retry,
        "after_retry": state(queue, slow["job_id"]), "resubmit_same_job_id": resubmit["job_id"] == slow["job_id"],
        "reservations": reservations(run, slow["job_id"])}
    queue.request_cancel(slow["job_id"])
    out["6_timeout_failed"]["trace"] = trace(run, slow["job_id"])

    # 7. lock reentrancy and nesting (no job is started)
    nest = queue.submit(PROTOCOL, args("H"), timeout_s=120)
    with run._owner():
        owner_inside_owner = outcome(hold_owner)
    with run._mutation():
        submit_inside = outcome(lambda: JobQueue(run).submit(PROTOCOL, args("K"), timeout_s=120))
        start_inside = outcome(lambda: JobQueue(run).start(nest["job_id"]))
    path = str(run.run_dir.resolve()) + ":transition"
    with run._transition():
        transition_lock = orchestrator._LOCAL_LOCKS[path]
        reacquire = transition_lock.acquire(blocking=False)
        if reacquire:
            transition_lock.release()
    out["7_locks"] = {"owner_inside_owner": owner_inside_owner, "submit_inside_mutation": submit_inside,
                      "start_inside_mutation": start_inside,
                      "transition_reacquire_same_thread_nonblocking": reacquire,
                      "nest_job_status_after": state(queue, nest["job_id"])["status"]}
    for job in queue.list():
        if job["status"] not in ("done", "failed", "cancelled", "interrupted"):
            queue.request_cancel(job["job_id"])
    out["budget_after"] = {axis: run.budget_snapshot()[axis] for axis in ("expensive_calls", "wall_clock_s")}
    out["killed_leftovers"] = kill_leftovers(run)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, default=REPO / "runs/m25-t1-preflight/queue")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if args.work.exists():
        shutil.rmtree(args.work)
    args.work.mkdir(parents=True)
    started = time.monotonic()
    try:
        report = measure(args.work)
        report["total_seconds"] = round(time.monotonic() - started, 1)
        print(json.dumps(report, indent=1, ensure_ascii=False))
    finally:
        if not args.keep:
            shutil.rmtree(args.work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
