"""M4 queue, ledger and POSIX lifecycle evidence. Fixture payloads are not energy."""
from __future__ import annotations

import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest
from fastapi.testclient import TestClient

from mw.api import app as api_module
from mw.core.errors import FailureClass, ToolFailure
from mw.jobs.queue import JobQueue, _guardian_argv, _members, _message, _same_identity, _send, _worker_environment
from mw.runtime.guards import Budget, BudgetLimits
from mw.runtime.orchestrator import ApprovalRequired, Run, RunCancelled
from mw.tools import energetic
from mw.workspace import build_registry, new_run


def run_at(tmp_path: Path, *, dry_run: bool = False) -> Run:
    return new_run(tmp_path, run_id="run_jobs", registry=build_registry(), dry_run=dry_run)


def queue_at(tmp_path: Path, mode: str = "normal") -> tuple[Run, JobQueue]:
    run = run_at(tmp_path)
    return run, JobQueue(run, fixture_mode=mode)


def os_enumeration() -> bool:
    try:
        psutil.pids()
        return True
    except PermissionError:
        return False


needs_process_table = pytest.mark.skipif(not os_enumeration(), reason="Darwin sysctl process enumeration denied")


def wait_ready(run: Run, job_id: str, timeout: float = 3) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        paths = list((run.run_dir / "jobs" / job_id).glob("*/grandchild.ready"))
        if paths:
            try:
                reported = json.loads(paths[0].read_text())
                proc = psutil.Process(reported["pid"])
                assert proc.create_time() == reported["create_time"]
                assert proc.status() != psutil.STATUS_ZOMBIE
                return {"pid": proc.pid, "create_time": proc.create_time(),
                        "uid": proc.uids().real, "pgid": os.getpgid(proc.pid)}
            except (json.JSONDecodeError, OSError, psutil.NoSuchProcess):
                pass
        time.sleep(0.01)
    pytest.fail("SIGTERM-ignoring grandchild never became ready")


def assert_not_running(member: dict) -> None:
    try:
        proc = psutil.Process(member["pid"])
        assert proc.create_time() != member["create_time"] or proc.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        pass


def cleanup_test_owned(members: list[dict]) -> None:
    # Test-only teardown keeps the original observed PID/create_time/UID/group tuple.
    # It can clean a verified grandchild after its guardian has already exited.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for member in members:
            try:
                proc = psutil.Process(member["pid"])
                if (proc.create_time() == member["create_time"] and
                        proc.uids().real == member["uid"] == os.getuid() and
                        os.getpgid(proc.pid) == member["pgid"] and
                        proc.status() != psutil.STATUS_ZOMBIE):
                    os.kill(proc.pid, sig)
            except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError, PermissionError):
                pass
        end = time.monotonic() + 0.3
        while time.monotonic() < end:
            if all(not member_running(member) for member in members):
                break
            time.sleep(0.01)


def member_running(member: dict) -> bool:
    try:
        proc = psutil.Process(member["pid"])
        return proc.create_time() == member["create_time"] and proc.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError, PermissionError):
        return False


def cleanup_fixture(queue: JobQueue, job_id: str, observed: list[dict] | None = None) -> None:
    known = list(observed or [])
    events = list(queue.run.events.read())
    identities = [(e["attempt_id"], e["identity"]) for e in events if e["type"] == "job_launch_identity" and
                  e.get("job_id") == job_id]
    for attempt_id, identity in identities:
        pgid = identity["pgid"]
        if _same_identity(identity):
            known.extend({**member, "pgid": pgid} for member in _members(pgid))
        for event in events:
            if (event["type"] == "job_worker_started" and event.get("job_id") == job_id and
                    event.get("attempt_id") == attempt_id):
                known.append({"pid": event["pid"], "create_time": event["create_time"],
                              "uid": identity["uid"], "pgid": pgid})
        for ready in (queue.run.run_dir / "jobs" / job_id / attempt_id).glob("grandchild.ready"):
            try:
                value = json.loads(ready.read_text())
                known.append({"pid": value["pid"], "create_time": value["create_time"],
                              "uid": identity["uid"], "pgid": pgid})
            except (OSError, ValueError, KeyError):
                pass
    cleanup_test_owned(known)
    for _, identity in identities:
        if _same_identity(identity):
            queue._cleanup_owned(identity)


def test_capability_matrix_missing_detectable_unimplemented_and_unknown(monkeypatch, tmp_path):
    matrix = energetic.protocol_capabilities()
    assert set(matrix["protocols"]) == set(energetic.PROTOCOLS)
    assert all(not entry["available"] and entry["validation_status"] == "not_validated"
               and entry["implementation_status"] == "unimplemented"
               for entry in matrix["protocols"].values())
    monkeypatch.setattr(energetic.importlib.util, "find_spec", lambda name: object())
    detectable = energetic.protocol_capabilities()
    assert all(entry["engine_detected"] and entry["reason_code"] == "protocol_unimplemented"
               and not entry["available"] for entry in detectable["protocols"].values())
    run = run_at(tmp_path)
    queue = JobQueue(run)
    with pytest.raises(ToolFailure) as exc:
        queue.submit("unknown", {})
    assert exc.value.cls == FailureClass.input_invalid
    with pytest.raises(ValueError):
        queue.submit_fixture()
    assert queue.list() == []


def test_production_boundary_dry_run_and_api(tmp_path, monkeypatch):
    run = run_at(tmp_path)
    queue = JobQueue(run)
    prepared = run.store.put("prepared_structure", "prepared_structure@1", b"fixture", fmt="pdb")
    args = {"structure": prepared.handle}
    for unsafe in ("argv", "executable", "module", "env", "path", "cwd", "fixture"):
        with pytest.raises(ToolFailure) as exc:
            queue.submit("relax", {**args, unsafe: "injected"})
        assert exc.value.cls == FailureClass.input_invalid
    with pytest.raises(ToolFailure) as exc:
        queue.submit("relax", args)
    assert exc.value.cls == FailureClass.precondition
    assert exc.value.detail["reason_code"] in {"engine_missing", "protocol_unimplemented"}
    assert run.budget.expensive_calls == 0 and queue.list() == []
    dry = new_run(tmp_path, run_id="run_dry", registry=build_registry(), dry_run=True)
    dry_prepared = dry.store.put("prepared_structure", "prepared_structure@1", b"fixture", fmt="pdb")
    plan = JobQueue(dry).submit("relax", {"structure": dry_prepared.handle})
    assert plan["plan_only"] and plan["output_handles"] == []
    assert dry.budget.expensive_calls == 0
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path)
    api_module.RUNS.clear()
    client = TestClient(api_module.app)
    cap = client.get("/capabilities").json()
    assert len(cap["energy_protocols"]["protocols"]) == 4
    assert "jobs" in cap["supported"] and "jobs" not in cap["unavailable"]
    assert client.get("/runs/run_jobs/jobs").json() == []
    assert client.post("/runs/run_jobs/jobs", json={"protocol_id": "relax", "args": args}).status_code == 412
    assert client.post("/runs/run_jobs/jobs", json={"protocol_id": "relax", "args": args,
                                                      "executable": "/bin/sh"}).status_code == 422


def test_submit_claim_cancel_and_replay_without_sqlite(tmp_path):
    run, queue = queue_at(tmp_path)
    first = queue.submit_fixture()
    second = queue.submit_fixture()
    assert first["status"] == second["status"] == "queued"
    assert queue.claim_next("owner")["job_id"] == first["job_id"]
    assert queue.request_cancel(second["job_id"])["job"]["status"] == "cancelled"
    assert queue.request_cancel(second["job_id"])["status"] == "already_terminal"
    assert run.budget.expensive_calls == 0
    queue.path.unlink()
    reopened = JobQueue(run)
    assert reopened.get(first["job_id"])["status"] == "claimed"
    assert reopened.get(second["job_id"])["status"] == "cancelled"
    assert reopened.claim_next("other") is None


def test_simultaneous_claim_only_one(tmp_path):
    _, queue = queue_at(tmp_path)
    job = queue.submit_fixture()
    found = []

    def claim(token: int) -> None:
        try:
            found.append(JobQueue(queue.run).claim_next(str(token)))
        except ToolFailure as exc:
            assert exc.detail.get("busy")
            found.append(None)

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(item is not None for item in found) == 1
    assert queue.get(job["job_id"])["status"] == "claimed"


def test_approval_reservation_failed_launch_retry_and_reopen(tmp_path):
    run = run_at(tmp_path)

    def denied_launch(*args, **kwargs):
        raise OSError("fixed launch failure")

    queue = JobQueue(run, fixture_mode="normal", popen=denied_launch)
    job = queue.submit_fixture()
    queue.claim_next("one")
    with pytest.raises(ApprovalRequired):
        queue.execute_claim(job["job_id"], "one")
    assert run.budget.expensive_calls == 0
    run.approve("expensive_first_call")
    assert queue.execute_claim(job["job_id"], "one")["status"] == "failed"
    assert run.budget.expensive_calls == 1
    queue.retry(job["job_id"])
    queue.claim_next("two")
    assert queue.execute_claim(job["job_id"], "two")["status"] == "failed"
    reopened = run_at(tmp_path)
    assert reopened.approved_expensive and reopened.budget.expensive_calls == 2
    assert JobQueue(reopened).get(job["job_id"])["attempt_ordinal"] == 2
    reservations = [e for e in reopened.events.read() if e["type"] == "budget_reserved" and
                    e.get("root_call_id") == job["job_id"]]
    assert len(reservations) == len({e["attempt_id"] for e in reservations}) == 2
    assert not any(e["type"] == "object_created" and e["kind"] == "energy_table"
                   for e in reopened.events.read())


def test_claim_event_survives_row_update_failure(tmp_path):
    run, queue = queue_at(tmp_path)
    job = queue.submit_fixture()
    with sqlite3.connect(queue.path) as db:
        db.execute("CREATE TRIGGER deny_claim BEFORE UPDATE ON jobs BEGIN SELECT RAISE(ABORT, 'injected'); END")
    with pytest.raises(sqlite3.DatabaseError):
        queue.claim_next("owner")
    with sqlite3.connect(queue.path) as db:
        db.execute("DROP TRIGGER deny_claim")
    assert JobQueue(run).get(job["job_id"])["status"] == "claimed"
    assert queue.claim_next("other") is None


def test_reservation_crash_before_intent_and_terminal_candidate_integrity(tmp_path):
    run, queue = queue_at(tmp_path)
    job = queue.submit_fixture()
    queue.claim_next("owner")
    run.approve("expensive_first_call")
    with run._owner():
        run.reserve_attempt("attempt_crash", job["job_id"], "lifecycle_fixture", {})
    assert run.budget.expensive_calls == 1
    assert queue.reconcile_run()[0]["status"] == "interrupted"
    assert run_at(tmp_path).budget.expensive_calls == 1
    assert JobQueue(run).get(job["job_id"])["attempt_ordinal"] == 1
    with pytest.raises(ValueError):
        run.events.append("job_terminal", job_id=job["job_id"], attempt_id=None, status="done",
                          output_handles=["obj://run_jobs/job_lifecycle/" + "0" * 64])
        queue.get(job["job_id"])


def test_four_reservation_only_interruptions_exhaust_root_allowance(tmp_path):
    run, queue = queue_at(tmp_path)
    run.approve("expensive_first_call")
    job = queue.submit_fixture()
    for ordinal in range(4):
        if ordinal:
            queue.retry(job["job_id"])
        queue.claim_next(f"owner_{ordinal}")
        with run._owner():
            run.reserve_attempt(f"attempt_{ordinal}", job["job_id"], "lifecycle_fixture", {},
                                job_id=job["job_id"])
            if ordinal == 3:
                with pytest.raises(ToolFailure) as denial:
                    run.reserve_attempt("attempt_fifth", job["job_id"], "lifecycle_fixture", {},
                                        job_id=job["job_id"])
                assert denial.value.cls == FailureClass.resource_exceeded
        assert queue.reconcile_run()[0]["status"] == "interrupted"
        assert queue.get(job["job_id"])["attempt_ordinal"] == ordinal + 1
    reopened = run_at(tmp_path)
    persisted = JobQueue(reopened)
    assert persisted.get(job["job_id"])["attempt_ordinal"] == 4
    with pytest.raises(ToolFailure):
        persisted.retry(job["job_id"])
    reservations = [e for e in reopened.events.read() if e["type"] == "budget_reserved" and
                    e.get("root_call_id") == job["job_id"]]
    assert len(reservations) == len({e["attempt_id"] for e in reservations}) == 4
    assert reopened.budget.expensive_calls == 4


@pytest.mark.parametrize("cleanup_ok", [True, False])
def test_attempt_charges_supervision_cleanup_and_finalization_once(tmp_path, monkeypatch, cleanup_ok):
    run = Run("run_jobs", tmp_path / "run_jobs", build_registry(),
              budget=Budget(limits=BudgetLimits(wall_clock_s=4)))
    run.approve("expensive_first_call")
    clock = [0.0]
    run.monotonic = lambda: clock[0]
    queue = JobQueue(run, fixture_mode="grandchild")
    job = queue.submit_fixture()
    queue.claim_next("owner")
    before = run.budget.wall_clock_s
    identity = {"pid": 999999, "pgid": 999999, "session": 999999,
                "create_time": 1.0, "uid": os.getuid()}
    calls = []

    def supervise(*args):
        args[-1].update(spawned=True, authorized=True, reaped=True)
        clock[0] += 2
        return {"kind": "RESULT", "reason": "timeout", "clean": False,
                "direct_child_reaped": True}, identity

    def cleanup(_identity):
        calls.append("cleanup")
        clock[0] += 3
        return cleanup_ok

    original_terminal = queue._terminal

    def terminal(*args, **kwargs):
        clock[0] += 1
        return original_terminal(*args, **kwargs)

    monkeypatch.setattr(queue, "_supervise", supervise)
    monkeypatch.setattr(queue, "_cleanup_owned", cleanup)
    monkeypatch.setattr(queue, "_terminal", terminal)
    monkeypatch.setattr("mw.jobs.queue._members", lambda pgid: [{"pid": 999999}])
    result = queue.execute_claim(job["job_id"], "owner")
    assert calls == ["cleanup"]
    assert result["status"] == ("failed" if cleanup_ok else "running")
    assert run.budget.wall_clock_s - before == (6 if cleanup_ok else 5)
    charges = [e for e in run.events.read() if e["type"] == "wall_charged" and
               e.get("reason") == "job_attempt"]
    assert len(charges) == 1 and charges[0]["seconds"] == run.budget.wall_clock_s - before
    assert any(e["type"] == "checkpoint" and e.get("axis") == "wall_clock_s"
               for e in run.events.read())


def test_terminal_before_wall_charge_crash_reconciles_once(tmp_path):
    run, queue = queue_at(tmp_path)
    run.approve("expensive_first_call")
    job = queue.submit_fixture()
    queue.claim_next("owner")
    with run._owner():
        run.reserve_attempt("attempt_crash", job["job_id"], "lifecycle_fixture", {}, job_id=job["job_id"])
    run.events.append("job_dispatch_intent", job_id=job["job_id"], attempt_id="attempt_crash",
                      launch_nonce="private", ordinal=1, remaining_wall_s=10, timeout_s=10)
    time.sleep(0.01)
    run.events.append("job_cleanup_verified", job_id=job["job_id"], attempt_id="attempt_crash",
                      group_empty=True, source="injected_no_launch_fixture")
    run.events.append("job_terminal", job_id=job["job_id"], attempt_id="attempt_crash",
                      status="failed", failure={"error": "fatal"}, output_handles=[])
    reopened = run_at(tmp_path)
    replay = JobQueue(reopened)
    assert replay.get(job["job_id"])["status"] == "failed"
    before = reopened.budget.wall_clock_s
    replay.reconcile_run()
    after = reopened.budget.wall_clock_s
    assert after > before
    replay.reconcile_run()
    assert reopened.budget.wall_clock_s == after
    assert len([e for e in reopened.events.read() if e["type"] == "wall_charged" and
                e.get("call_id") == "attempt_crash"]) == 1


def test_missing_bootstrap_identity_stays_cleanup_pending(tmp_path):
    run, queue = queue_at(tmp_path)
    run.approve("expensive_first_call")
    job = queue.submit_fixture()
    queue.claim_next("owner")
    with run._owner():
        run.reserve_attempt("attempt_unknown", job["job_id"], "lifecycle_fixture", {}, job_id=job["job_id"])
    run.events.append("job_dispatch_intent", job_id=job["job_id"], attempt_id="attempt_unknown",
                      launch_nonce="private", ordinal=1, remaining_wall_s=10, timeout_s=10)
    result = queue.reconcile_run()[0]
    assert result["status"] == "running" and result["blocked_reason"] == "launch_identity_unknown"
    assert result["attempt_ordinal"] == 1 and run.budget.expensive_calls == 1
    with pytest.raises(ToolFailure):
        queue.retry(job["job_id"])
    assert not any(e["type"] == "job_cleanup_verified" for e in run.events.read())


def test_supervision_error_and_terminal_work_charged_once(tmp_path, monkeypatch):
    run, queue = queue_at(tmp_path)
    run.approve("expensive_first_call")
    clock = [0.0]
    run.monotonic = lambda: clock[0]
    job = queue.submit_fixture()
    queue.claim_next("owner")
    before = run.budget.wall_clock_s

    def supervise(*args):
        clock[0] += 2
        raise ToolFailure(FailureClass.fatal, "synthetic supervisor failure")

    original_terminal = queue._terminal

    def terminal(*args, **kwargs):
        clock[0] += 1
        return original_terminal(*args, **kwargs)

    monkeypatch.setattr(queue, "_supervise", supervise)
    monkeypatch.setattr(queue, "_terminal", terminal)
    assert queue.execute_claim(job["job_id"], "owner")["status"] == "failed"
    assert run.budget.wall_clock_s - before == 3
    assert len([e for e in run.events.read() if e["type"] == "wall_charged" and
                e.get("reason") == "job_attempt"]) == 1


def test_success_candidate_and_terminal_work_charged_once(tmp_path, monkeypatch):
    run, queue = queue_at(tmp_path)
    run.approve("expensive_first_call")
    clock = [0.0]
    run.monotonic = lambda: clock[0]
    job = queue.submit_fixture()
    queue.claim_next("owner")
    before = run.budget.wall_clock_s

    def supervise(job_record, attempt_id, nonce, attempt_dir, deadline, dispatch):
        clock[0] += 2
        return {"kind": "RESULT", "reason": "completed", "clean": True,
                "direct_child_reaped": True, "returncode": 0, "unexpected_members": False,
                "payload": {"schema": "lifecycle_fixture@1", "attempt_id": attempt_id,
                            "job_id": job_record["job_id"], "fixture": True, "ok": True}}, None

    queue._barrier = lambda stage: clock.__setitem__(0, clock[0] + 1) if stage == "before_terminal" else None
    monkeypatch.setattr(queue, "_supervise", supervise)
    result = queue.execute_claim(job["job_id"], "owner")
    assert result["status"] == "done" and len(result["output_handles"]) == 1
    assert run.budget.wall_clock_s - before == 3
    assert len([e for e in run.events.read() if e["type"] == "wall_charged" and
                e.get("reason") == "job_attempt"]) == 1


def test_guardian_uses_venv_and_minimal_environment_with_sentinels(tmp_path, monkeypatch):
    for key in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "HTTP_PROXY", "HTTPS_PROXY",
                "PYTHONPATH", "DYLD_INSERT_LIBRARIES", "LD_PRELOAD"):
        monkeypatch.setenv(key, f"synthetic_{key}")
    nonce = "a" * 32
    (tmp_path / "input.json").write_text(json.dumps({
        "nonce": nonce, "job_id": "job_probe", "attempt_id": "attempt_probe",
        "adapter": "internal_lifecycle_fixture", "fixture_mode": "normal",
    }))
    parent, child = socket.socketpair()
    proc = subprocess.Popen(_guardian_argv(child.fileno()), cwd=tmp_path,
                            env=_worker_environment(tmp_path), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            shell=False, close_fds=True, pass_fds=(child.fileno(),),
                            start_new_session=True)
    child.close()
    try:
        hello = _message(parent, 3)
        assert hello and hello["kind"] == "HELLO" and hello["nonce"] == nonce
        assert hello["pid"] == proc.pid == hello["pgid"] == hello["session"]
        assert json.loads((tmp_path / "bootstrap.receipt").read_text()) == {
            key: hello[key] for key in ("nonce", "pid", "pgid", "session", "create_time", "uid")}
        assert _same_identity(hello)
        runtime = hello["runtime"]
        assert runtime["prefix"] == sys.prefix
        assert runtime["executable"] == os.path.abspath(sys.executable)
        assert runtime["psutil_version"] == psutil.__version__
        assert set(runtime["environment_keys"]) <= (set(_worker_environment(tmp_path)) |
                                                    {"LC_CTYPE", "__CF_USER_TEXT_ENCODING"})
        assert not set(runtime["environment_keys"]) & {
            "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "HTTP_PROXY", "HTTPS_PROXY",
            "PYTHONPATH", "DYLD_INSERT_LIBRARIES", "LD_PRELOAD"}
        parent.close()  # no GO: the guardian cannot start the fixture
        assert proc.wait(timeout=3) == 0
        assert not (tmp_path / "fixture_runtime.json").exists()
    finally:
        parent.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)


@pytest.mark.parametrize("reason", ["timeout", "cancelled"])
def test_stopped_control_drains_queued_started_before_real_result(tmp_path, reason):
    _, queue = queue_at(tmp_path)
    parent, child = socket.socketpair()
    try:
        common = {"nonce": "private", "job_id": "job_probe", "attempt_id": "attempt_probe"}
        _send(child, {"kind": "STARTED", **common, "pid": 123, "create_time": 1.0})
        _send(child, {"kind": "RESULT", **common, "reason": "stopped", "clean": False,
                      "direct_child_reaped": True, "returncode": None})
        result = queue._stopped_result(parent, "job_probe", "attempt_probe", "private",
                                       reason, time.monotonic() + 0.5)
        assert result and result["reason"] == reason and result["direct_child_reaped"] is True
        assert any(e["type"] == "job_worker_started" and e["pid"] == 123
                   for e in queue.run.events.read())
    finally:
        parent.close()
        child.close()


@pytest.mark.parametrize("messages", [[], [{"kind": "RESULT", "clean": True,
                                             "direct_child_reaped": True}]])
def test_stopped_control_needs_matching_real_result(tmp_path, messages):
    _, queue = queue_at(tmp_path)
    parent, child = socket.socketpair()
    try:
        for message in messages:
            _send(child, message)
        child.close()
        if messages:
            with pytest.raises(ValueError, match="identity"):
                queue._stopped_result(parent, "job_probe", "attempt_probe", "private",
                                      "timeout", time.monotonic() + 0.2)
        else:
            assert queue._stopped_result(parent, "job_probe", "attempt_probe", "private",
                                         "timeout", time.monotonic() + 0.2) is None
    finally:
        parent.close()
        child.close()


def test_stopped_control_rejects_malformed_result_and_partial_frame(tmp_path):
    _, queue = queue_at(tmp_path)
    parent, child = socket.socketpair()
    try:
        _send(child, {"kind": "RESULT", "nonce": "private", "job_id": "job_probe",
                      "attempt_id": "attempt_probe", "clean": True})
        with pytest.raises(ValueError, match="invalid guardian control"):
            queue._stopped_result(parent, "job_probe", "attempt_probe", "private",
                                  "cancelled", time.monotonic() + 0.2)
        child.sendall(b'{"kind":')
        with pytest.raises(ValueError, match="incomplete guardian message"):
            _message(parent, 0.02)
    finally:
        parent.close()
        child.close()


def test_mismatched_identity_never_signalled(monkeypatch, tmp_path):
    _, queue = queue_at(tmp_path)
    identity = {"pid": os.getpid(), "pgid": os.getpgrp(), "session": os.getsid(0),
                "create_time": psutil.Process(os.getpid()).create_time() + 100,
                "uid": os.getuid()}
    assert not _same_identity(identity)
    monkeypatch.setattr("mw.jobs.queue._members", lambda pgid: [{
        "pid": os.getpid(), "create_time": identity["create_time"], "uid": os.getuid()}])
    called = []
    monkeypatch.setattr(os, "kill", lambda *args: called.append(args))
    assert not queue._cleanup_owned(identity)
    assert called == []


@pytest.mark.parametrize("mode", ["stranger", "known_survivor", "loss_during_scan",
                                  "reused_member_pid"])
def test_cleanup_cohort_survives_anchor_loss_without_signalling_strangers(monkeypatch, mode):
    """All process observations and signals are fixtures; no OS signal is sent."""
    uid = os.getuid()
    anchor = {"pid": 410001, "pgid": 410001, "session": 410001,
              "create_time": 100.0, "uid": uid}
    leader = {"pid": 410001, "create_time": 100.0, "uid": uid}
    helper = {"pid": 410002, "create_time": 101.0, "uid": uid}
    stranger = {"pid": 410003, "create_time": 200.0, "uid": uid}
    reused = {"pid": helper["pid"], "create_time": 202.0, "uid": uid}
    state = {"anchor_alive": True, "clock": 0.0, "scans": 0, "signals": [], "killed": set()}

    def same_identity(_identity):
        return state["anchor_alive"]

    def members(_pgid):
        state["scans"] += 1
        if mode == "loss_during_scan" and state["scans"] == 2:
            state["anchor_alive"] = False
        if state["anchor_alive"]:
            found = [leader, helper] if mode != "stranger" else [leader]
        else:
            found = [helper, stranger] if mode == "loss_during_scan" else (
                [helper] if mode == "known_survivor" else (
                    [reused] if mode == "reused_member_pid" else [stranger]))
        return [dict(member) for member in found
                if (member["pid"], member["create_time"]) not in state["killed"]]

    def signal_member(member, _pgid, sig):
        state["signals"].append((member["pid"], sig))
        if mode != "loss_during_scan":
            state["anchor_alive"] = False
        if sig == signal.SIGKILL:
            state["killed"].add((member["pid"], member["create_time"]))

    def monotonic():
        state["clock"] += 0.005
        assert state["clock"] < 10, "cleanup must be bounded"
        return state["clock"]

    def sleep(seconds):
        state["clock"] += seconds

    monkeypatch.setattr("mw.jobs.queue._same_identity", same_identity)
    monkeypatch.setattr("mw.jobs.queue._members", members)
    monkeypatch.setattr("mw.jobs.queue._signal_member", signal_member)
    monkeypatch.setattr("mw.jobs.queue.time.monotonic", monotonic)
    monkeypatch.setattr("mw.jobs.queue.time.sleep", sleep)
    monkeypatch.setattr(os, "kill", lambda *_args: pytest.fail("unexpected OS signal"))
    monkeypatch.setattr(os, "killpg", lambda *_args: pytest.fail("unexpected OS group signal"))

    clean = JobQueue._cleanup_owned(object.__new__(JobQueue), anchor)
    assert all(pid != stranger["pid"] for pid, _ in state["signals"])
    if mode == "stranger":
        assert not clean
    elif mode == "reused_member_pid":
        assert state["signals"] == [(helper["pid"], signal.SIGTERM)]
        assert not clean
    else:
        assert (helper["pid"], signal.SIGTERM) in state["signals"]
        assert (helper["pid"], signal.SIGKILL) in state["signals"]
        assert not clean if mode == "loss_during_scan" else clean


def test_cancel_queued_and_run_cancel_do_not_charge(tmp_path):
    run, queue = queue_at(tmp_path)
    job = queue.submit_fixture()
    queue.request_cancel(job["job_id"])
    assert queue.claim_next("owner") is None
    run.cancel()
    assert run_at(tmp_path).cancelled
    assert run.budget.expensive_calls == 0


def test_budget_denial_retry_limit_and_idle_time(tmp_path):
    run = Run("run_jobs", tmp_path / "run_jobs", build_registry(),
              budget=Budget(limits=BudgetLimits(expensive_calls=0)))
    queue = JobQueue(run, fixture_mode="normal")
    job = queue.submit_fixture()
    queue.claim_next("owner")
    run.approve("expensive_first_call")
    idle_start = run.budget.wall_clock_s
    time.sleep(0.02)
    assert run.budget.wall_clock_s == idle_start  # queued idle was not an active owner interval
    with pytest.raises(ApprovalRequired):
        queue.execute_claim(job["job_id"], "owner")
    assert run.budget.expensive_calls == 0

    def failed_launch(*args, **kwargs):
        raise OSError("test launch failure")

    other = new_run(tmp_path, run_id="run_retries", dry_run=False)
    other.approve("expensive_first_call")
    q = JobQueue(other, fixture_mode="normal", popen=failed_launch)
    item = q.submit_fixture()
    for ordinal in range(4):
        if ordinal:
            q.retry(item["job_id"])
        q.claim_next(f"owner_{ordinal}")
        assert q.execute_claim(item["job_id"], f"owner_{ordinal}")["status"] == "failed"
        assert other.budget.expensive_calls == ordinal + 1
    with pytest.raises(ToolFailure):
        q.retry(item["job_id"])
    assert JobQueue(new_run(tmp_path, run_id="run_retries", dry_run=False)).get(item["job_id"])[
        "attempt_ordinal"] == 4


def test_job_cancel_wins_reservation_guard_and_terminal_cas(tmp_path):
    run, queue = queue_at(tmp_path)
    job = queue.submit_fixture()
    queue.claim_next("owner")
    run.approve("expensive_first_call")
    cancel_queue = JobQueue(run)
    queue._barrier = lambda stage: cancel_queue.request_cancel(job["job_id"]) if stage == "before_reservation" else None
    with pytest.raises(RunCancelled):
        queue.execute_claim(job["job_id"], "owner")
    assert run.budget.expensive_calls == 0
    assert queue.get(job["job_id"])["status"] == "cancelled"
    assert queue._terminal(job["job_id"], None, "done", handles=[])["status"] == "cancelled"
    assert len([e for e in run.events.read() if e["type"] == "job_terminal"]) == 1


def test_missing_terminal_output_and_private_api_events(tmp_path, monkeypatch):
    run, queue = queue_at(tmp_path)
    job = queue.submit_fixture()
    queue.claim_next("owner")
    run.events.append("budget_reserved", attempt_id="attempt_one", root_call_id=job["job_id"],
                      tool="lifecycle_fixture", expensive_calls=1)
    run.events.append("job_dispatch_intent", job_id=job["job_id"], attempt_id="attempt_one",
                      launch_nonce="private_nonce", ordinal=1, remaining_wall_s=1, timeout_s=1)
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path)
    api_module.RUNS.clear()
    response = TestClient(api_module.app).get("/runs/run_jobs/events").json()
    assert "private_nonce" not in json.dumps(response)
    missing = "obj://run_jobs/job_lifecycle/" + "0" * 64
    run.events.append("job_cleanup_verified", job_id=job["job_id"], attempt_id="attempt_one",
                      group_empty=True, source="test_fixture")
    run.events.append("job_result_candidate", job_id=job["job_id"], attempt_id="attempt_one",
                      output_handles=[missing])
    run.events.append("job_terminal", job_id=job["job_id"], attempt_id="attempt_one",
                      status="done", output_handles=[missing])
    with pytest.raises(KeyError):
        queue.get(job["job_id"])


def test_candidate_and_terminal_fault_windows_replay(tmp_path, monkeypatch):
    run, queue = queue_at(tmp_path)
    job = queue.submit_fixture()
    queue.claim_next("owner")
    run.approve("expensive_first_call")
    with run._owner():
        run.reserve_attempt("attempt_one", job["job_id"], "lifecycle_fixture", {}, job_id=job["job_id"])
    run.events.append("job_dispatch_intent", job_id=job["job_id"], attempt_id="attempt_one",
                      launch_nonce="private_nonce", ordinal=1, remaining_wall_s=1, timeout_s=1)
    run.events.append("job_cleanup_verified", job_id=job["job_id"], attempt_id="attempt_one",
                      group_empty=True, source="injected_no_launch_fixture")
    candidate = run.store.put("job_lifecycle", "job_lifecycle@1", {"fixture_only": True},
                              produced_by="attempt_one", summary={"fixture_only": True})
    with pytest.raises(ValueError, match="candidate"):
        queue._terminal(job["job_id"], "attempt_one", "done", handles=[candidate.handle])
    assert queue.get(job["job_id"])["status"] == "running"
    run.events.append("job_result_candidate", job_id=job["job_id"], attempt_id="attempt_one",
                      output_handles=[candidate.handle])
    original = queue._rebuild
    calls = 0

    def fail_after_terminal():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError("injected row failure")
        return original()

    monkeypatch.setattr(queue, "_rebuild", fail_after_terminal)
    with pytest.raises(sqlite3.OperationalError):
        queue._terminal(job["job_id"], "attempt_one", "done", handles=[candidate.handle])
    reopened = JobQueue(run)
    assert reopened.get(job["job_id"])["status"] == "done"
    assert reopened.get(job["job_id"])["output_handles"] == [candidate.handle]
    assert run.budget.expensive_calls == 1
    assert len([e for e in run.events.read() if e["type"] == "job_terminal"]) == 1


def test_unclosed_job_blocks_new_physical_tool_call(tmp_path):
    run, queue = queue_at(tmp_path)
    job = queue.submit_fixture()
    queue.claim_next("owner")
    run.approve("expensive_first_call")
    with run._owner():
        run.reserve_attempt("attempt_one", job["job_id"], "lifecycle_fixture", {}, job_id=job["job_id"])
    run.events.append("job_dispatch_intent", job_id=job["job_id"], attempt_id="attempt_one",
                      launch_nonce="private_nonce", ordinal=1, remaining_wall_s=1, timeout_s=1)
    prepared = run.store.put("prepared_structure", "prepared_structure@1", b"fixture", fmt="pdb")
    with pytest.raises(ToolFailure) as exc:
        run.call("define_mutations", {"structure": prepared.handle, "mutations": []})
    assert exc.value.detail["reason_code"] == "job_cleanup_pending"
    assert run.budget.expensive_calls == 1


@pytest.mark.parametrize("cleanup_pending", [False, True])
@pytest.mark.parametrize("reopen", [False, True])
def test_unclosed_prior_job_blocks_claim_until_verified_terminal(tmp_path, monkeypatch,
                                                                  cleanup_pending, reopen):
    launches = []

    def recorded_refusal(*args, **kwargs):
        launches.append("fake launch only")
        raise OSError("fixture launch refusal")

    def forbidden(*args, **kwargs):
        pytest.fail("unexpected real process launch or signal")

    run = run_at(tmp_path)
    run.approve("expensive_first_call")
    queue = JobQueue(run, fixture_mode="normal", popen=recorded_refusal)
    first = queue.submit_fixture()
    queue.claim_next("first")
    with run._owner():
        run.reserve_attempt("attempt_prior", first["job_id"], "lifecycle_fixture", {},
                            job_id=first["job_id"])
        with run._transition():
            run.events.append("job_dispatch_intent", job_id=first["job_id"],
                              attempt_id="attempt_prior", launch_nonce="fixture_only",
                              ordinal=1, remaining_wall_s=10, timeout_s=10)
            if cleanup_pending:
                run.events.append("job_cleanup_pending", job_id=first["job_id"],
                                  attempt_id="attempt_prior", reason="launch_identity_unknown")
    second = queue.submit_fixture()
    queue.claim_next("second")
    if reopen:
        queue.path.unlink()  # events, not the disposable index, govern admission
        run = run_at(tmp_path)
        queue = JobQueue(run, fixture_mode="normal", popen=recorded_refusal)
    before = list(run.events.read())
    before_wall = run.budget.wall_clock_s
    with monkeypatch.context() as guard:
        guard.setattr(subprocess, "Popen", forbidden)
        guard.setattr(os, "kill", forbidden)
        guard.setattr(os, "killpg", forbidden)
        with pytest.raises(ToolFailure) as denial:
            queue.execute_claim(second["job_id"], "second")
        assert denial.value.cls == FailureClass.precondition
        assert denial.value.detail == {"job_id": first["job_id"],
                                       "reason_code": "job_cleanup_pending"}
        blocked = queue.get(second["job_id"])
        assert blocked["status"] == "claimed" and blocked["blocked_reason"] == "job_cleanup_pending"
        assert blocked["attempt_ordinal"] == 0 and blocked["attempt_id"] is None
        assert run.budget.expensive_calls == 1 and run.budget.wall_clock_s == before_wall
        assert launches == []
        with run._owner(), pytest.raises(ToolFailure) as direct_denial:
            run.reserve_attempt("attempt_bypass", second["job_id"], "lifecycle_fixture", {},
                                job_id=second["job_id"])
        assert direct_denial.value.detail["reason_code"] == "job_cleanup_pending"
        new_events = list(run.events.read())[len(before):]
        assert [event["type"] for event in new_events] == ["job_blocked"]
        assert not (run.run_dir / "jobs" / second["job_id"]).exists()
        if reopen:
            queue.path.unlink()
            run = run_at(tmp_path)
            queue = JobQueue(run, fixture_mode="normal", popen=recorded_refusal)
            assert queue.get(second["job_id"])["blocked_reason"] == "job_cleanup_pending"
            with pytest.raises(ToolFailure) as repeated:
                queue.execute_claim(second["job_id"], "second")
            assert repeated.value.detail["reason_code"] == "job_cleanup_pending"
            assert launches == [] and run.budget.expensive_calls == 1
            assert len(list(run.events.read())) == len(before) + 1

        with run._owner(), run._transition():
            run.events.append("job_cleanup_verified", job_id=first["job_id"],
                              attempt_id="attempt_prior", group_empty=True,
                              source="test_fixture_no_process")
            run.events.append("job_terminal", job_id=first["job_id"],
                              attempt_id="attempt_prior", status="interrupted",
                              failure={"error": "interrupted"}, output_handles=[])
        result = queue.execute_claim(second["job_id"], "second")
        assert result["status"] == "failed" and result["blocked_reason"] is None
        assert launches == ["fake launch only"] and run.budget.expensive_calls == 2
        assert result["attempt_ordinal"] == 1
        reservations = [event for event in run.events.read()
                        if event["type"] == "budget_reserved" and
                        event.get("root_call_id") == second["job_id"]]
        assert len(reservations) == 1


def test_late_unclosed_job_recheck_and_cancellation_remain_available(tmp_path, monkeypatch):
    run, queue = queue_at(tmp_path)
    run.approve("expensive_first_call")
    first = queue.submit_fixture()
    queue.claim_next("first")
    second = queue.submit_fixture()
    queue.claim_next("second")

    def stage_prior(stage):
        assert stage == "before_reservation"
        run.reserve_attempt("attempt_prior", first["job_id"], "lifecycle_fixture", {},
                            job_id=first["job_id"])
        with run._transition():
            run.events.append("job_dispatch_intent", job_id=first["job_id"],
                              attempt_id="attempt_prior", launch_nonce="fixture_only",
                              ordinal=1, remaining_wall_s=10, timeout_s=10)
            run.events.append("job_cleanup_pending", job_id=first["job_id"],
                              attempt_id="attempt_prior", reason="launch_identity_unknown")

    def forbidden(*args, **kwargs):
        pytest.fail("unexpected real process launch or signal")

    queue._barrier = stage_prior
    queue._popen = forbidden
    with monkeypatch.context() as guard:
        guard.setattr(subprocess, "Popen", forbidden)
        guard.setattr(os, "kill", forbidden)
        guard.setattr(os, "killpg", forbidden)
        with pytest.raises(ToolFailure) as denial:
            queue.execute_claim(second["job_id"], "second")
        assert denial.value.detail["reason_code"] == "job_cleanup_pending"
        assert run.budget.expensive_calls == 1
        assert queue.get(second["job_id"])["status"] == "claimed"
        assert queue.request_cancel(second["job_id"])["job"]["status"] == "cancelled"
        run.cancel()
        assert run_at(tmp_path).cancelled and run.budget.expensive_calls == 1


def test_job_directory_symlink_rejected(tmp_path):
    run, queue = queue_at(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (run.run_dir / "jobs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        queue._attempt_dir("job_safe", "attempt_safe")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("reaped", [True, False])
def test_parent_group_verification_requires_direct_child_reap_ack(tmp_path, monkeypatch, reaped):
    run, queue = queue_at(tmp_path, "grandchild")
    run.approve("expensive_first_call")
    job = queue.submit_fixture()
    queue.claim_next("owner")
    identity = {"pid": 999999, "pgid": 999999, "session": 999999,
                "create_time": 1.0, "uid": os.getuid()}

    def synthetic_guardian(job_record, attempt_id, nonce, attempt_dir, deadline, dispatch):
        dispatch.update(spawned=True, authorized=True, reaped=True)
        return {"kind": "RESULT", "reason": "timeout", "clean": False,
                "direct_child_reaped": reaped}, identity

    monkeypatch.setattr(queue, "_supervise", synthetic_guardian)
    monkeypatch.setattr("mw.jobs.queue._members", lambda pgid: [])
    result = queue.execute_claim(job["job_id"], "owner")
    assert result["status"] == ("failed" if reaped else "running")
    if reaped:
        assert result["failure"]["error"] == "resource_exceeded"
    else:
        assert result["blocked_reason"] == "guardian_reap_unconfirmed"


@needs_process_table
@pytest.mark.parametrize("mode", ["normal", "nonzero", "malformed", "oversize", "wrong_id", "invalid"])
def test_real_fixture_result_validation_and_reap(tmp_path, mode, monkeypatch):
    forbidden = {"OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "HTTP_PROXY", "HTTPS_PROXY",
                 "PYTHONPATH", "DYLD_INSERT_LIBRARIES", "LD_PRELOAD"}
    for key in forbidden:
        monkeypatch.setenv(key, f"synthetic_{key}")
    run, queue = queue_at(tmp_path, mode)
    run.approve("expensive_first_call")
    job = queue.submit_fixture()
    queue.claim_next("owner")
    try:
        result = queue.execute_claim(job["job_id"], "owner")
        assert result["status"] == ("done" if mode == "normal" else "failed")
        assert run.budget.expensive_calls == 1
        runtime_path = run.run_dir / "jobs" / job["job_id"] / result["attempt_id"] / "fixture_runtime.json"
        runtime = json.loads(runtime_path.read_text())
        assert runtime["prefix"] == sys.prefix
        assert runtime["executable"] == os.path.abspath(sys.executable)
        assert runtime["psutil_version"] == psutil.__version__
        assert not forbidden & set(runtime["environment_keys"])
        if mode == "normal":
            handle = result["output_handles"][0]
            assert run.store.kind_of(handle) == "job_lifecycle"
            assert JobQueue(run).get(job["job_id"])["status"] == "done"
            queue.path.unlink()
            assert JobQueue(run).get(job["job_id"])["output_handles"] == [handle]
        else:
            assert result["output_handles"] == []
    finally:
        cleanup_fixture(queue, job["job_id"])


@needs_process_table
@pytest.mark.parametrize("mode", ["grandchild", "leader_exit"])
def test_real_timeout_or_abandoned_grandchild_cleanup(tmp_path, mode):
    run, queue = queue_at(tmp_path, mode)
    seen = []
    queue._barrier = lambda stage: seen.append(wait_ready(run, job["job_id"])) if stage == "after_go" else None
    run.approve("expensive_first_call")
    job = queue.submit_fixture(timeout_s=0.5)
    queue.claim_next("owner")
    try:
        result = queue.execute_claim(job["job_id"], "owner")
        assert result["status"] == "failed"
        assert len(seen) == 1
        if mode == "grandchild":
            assert result["failure"]["error"] == "resource_exceeded"
        intent = result["dispatch_intent"]
        group = result["identity"]["pgid"]
        assert _members(group) == []
        with pytest.raises(ChildProcessError):
            os.waitpid(group, os.WNOHANG)  # retained guardian Popen was reaped
        ready = run.run_dir / "jobs" / job["job_id"] / intent["attempt_id"] / "grandchild.ready"
        assert ready.exists() and json.loads(ready.read_text())["pid"] == seen[0]["pid"]
        assert_not_running(seen[0])
    finally:
        cleanup_fixture(queue, job["job_id"], seen)


@needs_process_table
def test_running_cancel_is_prompt_and_terminal_cas(tmp_path):
    run, queue = queue_at(tmp_path, "grandchild")
    run.approve("expensive_first_call")
    job = queue.submit_fixture(timeout_s=5)
    queue.claim_next("owner")
    finished = []
    thread = threading.Thread(target=lambda: finished.append(queue.execute_claim(job["job_id"], "owner")))
    thread.start()
    seen = []
    try:
        end = time.monotonic() + 3
        while time.monotonic() < end and not any(e["type"] == "job_execution_authorized"
                                                   for e in run.events.read()):
            time.sleep(0.01)
        assert thread.is_alive()
        seen.append(wait_ready(run, job["job_id"]))
        begin = time.monotonic()
        assert JobQueue(run).request_cancel(job["job_id"])["status"] == "accepted"
        assert time.monotonic() - begin < 1
        thread.join(timeout=4)
        assert not thread.is_alive()
        assert finished[0]["status"] == "cancelled"
        assert _members(finished[0]["identity"]["pgid"]) == []
        assert_not_running(seen[0])
        assert queue.request_cancel(job["job_id"])["status"] == "already_terminal"
    finally:
        if thread.is_alive():
            run.cancel()
            thread.join(timeout=4)
        cleanup_fixture(queue, job["job_id"], seen)


@needs_process_table
def test_cancel_wins_after_candidate_before_terminal(tmp_path):
    gate = threading.Event()
    release = threading.Event()

    def barrier(stage: str) -> None:
        if stage == "before_terminal":
            gate.set()
            assert release.wait(3)

    run = run_at(tmp_path)
    run.approve("expensive_first_call")
    queue = JobQueue(run, fixture_mode="normal", barrier=barrier)
    job = queue.submit_fixture()
    queue.claim_next("owner")
    finished = []
    thread = threading.Thread(target=lambda: finished.append(queue.execute_claim(job["job_id"], "owner")))
    thread.start()
    try:
        assert gate.wait(3)
        assert any(e["type"] == "job_result_candidate" for e in run.events.read())
        assert queue.request_cancel(job["job_id"])["status"] == "accepted"
        release.set()
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert finished[0]["status"] == "cancelled" and finished[0]["output_handles"] == []
        assert len([e for e in run.events.read() if e["type"] == "job_terminal"]) == 1
    finally:
        release.set()
        thread.join(timeout=3)
        cleanup_fixture(queue, job["job_id"])


@needs_process_table
def test_actual_creation_mismatch_refuses_signal(tmp_path):
    _, queue = queue_at(tmp_path)
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
                               start_new_session=True, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        identity = {"pid": process.pid, "pgid": process.pid, "session": process.pid,
                    "create_time": psutil.Process(process.pid).create_time() + 1,
                    "uid": os.getuid()}
        assert not queue._cleanup_owned(identity)
        assert process.poll() is None
    finally:
        process.kill()
        process.wait(timeout=2)


@needs_process_table
def test_timeout_overrun_charges_cleanup_and_checkpoints(tmp_path):
    seen = []
    def barrier(stage: str) -> None:
        if stage == "after_go":
            seen.append(wait_ready(run, job["job_id"]))
            time.sleep(1.05)

    run = Run("run_jobs", tmp_path / "run_jobs", build_registry(),
              budget=Budget(limits=BudgetLimits(wall_clock_s=1.0)))
    run.approve("expensive_first_call")
    queue = JobQueue(run, fixture_mode="grandchild", barrier=barrier)
    job = queue.submit_fixture(timeout_s=5)
    queue.claim_next("owner")
    try:
        result = queue.execute_claim(job["job_id"], "owner")
        assert result["status"] == "failed" and result["failure"]["error"] == "resource_exceeded"
        assert len(seen) == 1
        assert_not_running(seen[0])
        assert run.budget.wall_clock_s > 1.0
        assert any(e["type"] == "checkpoint" and e.get("axis") == "wall_clock_s"
                   for e in run.events.read())
        queue.retry(job["job_id"])
        queue.claim_next("next")
        with pytest.raises(ApprovalRequired):
            queue.execute_claim(job["job_id"], "next")
        assert run.budget.expensive_calls == 1
    finally:
        cleanup_fixture(queue, job["job_id"], seen)


@needs_process_table
def test_live_second_owner_busy(tmp_path):
    run, queue = queue_at(tmp_path, "sleep")
    run.approve("expensive_first_call")
    job = queue.submit_fixture(timeout_s=4)
    queue.claim_next("owner")
    thread = threading.Thread(target=lambda: queue.execute_claim(job["job_id"], "owner"))
    thread.start()
    try:
        end = time.monotonic() + 3
        while time.monotonic() < end and not any(e["type"] == "job_execution_authorized"
                                                   for e in run.events.read()):
            time.sleep(0.01)
        with pytest.raises(ToolFailure) as exc:
            JobQueue(run).reconcile_run()
        assert exc.value.detail["busy"]
        probe = subprocess.run([sys.executable, "-c", """
import sys
from pathlib import Path
from mw.workspace import new_run
from mw.jobs.queue import JobQueue
from mw.core.errors import ToolFailure
try:
    JobQueue(new_run(Path(sys.argv[1]),run_id='run_jobs',dry_run=False)).reconcile_run()
except ToolFailure as exc:
    print('busy' if exc.detail.get('busy') else 'unexpected')
""", str(tmp_path)], capture_output=True, text=True, timeout=3, check=False)
        assert probe.stdout.strip() == "busy"
    finally:
        queue.request_cancel(job["job_id"])
        thread.join(timeout=5)
        cleanup_fixture(queue, job["job_id"])


@needs_process_table
@pytest.mark.parametrize("stage", ["before_hello", "after_hello", "after_go", "before_terminal"])
def test_actual_parent_death_handshake_recovery(tmp_path, stage):
    script = r'''
import sys,time
from pathlib import Path
from mw.workspace import new_run
from mw.jobs.queue import JobQueue
root=Path(sys.argv[1]); stage=sys.argv[2]
def barrier(name):
    if name==stage:
        (root/'barrier').write_text(name)
        while not (root/'release').exists(): time.sleep(.02)
run=new_run(root,run_id='run_jobs',dry_run=False)
run.approve('expensive_first_call')
queue=JobQueue(run,fixture_mode='normal' if stage=='before_terminal' else 'grandchild',barrier=barrier)
job=queue.submit_fixture(timeout_s=10)
(root/'job_id').write_text(job['job_id'])
queue.claim_next('owner')
queue.execute_claim(job['job_id'],'owner')
'''
    child = subprocess.Popen([sys.executable, "-c", script, str(tmp_path), stage],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    known: list[dict] = []
    receipt = None
    try:
        end = time.monotonic() + 5
        while time.monotonic() < end and not (tmp_path / "barrier").exists():
            time.sleep(0.02)
        assert (tmp_path / "barrier").read_text() == stage
        run = run_at(tmp_path)
        queue = JobQueue(run)
        job_id = (tmp_path / "job_id").read_text()
        at_barrier = queue.get(job_id)
        intent = at_barrier["dispatch_intent"]
        assert intent and intent["attempt_id"]
        receipt_path = run.run_dir / "jobs" / job_id / intent["attempt_id"] / "bootstrap.receipt"
        end = time.monotonic() + 2
        while time.monotonic() < end and not receipt_path.exists():
            time.sleep(0.01)
        receipt = json.loads(receipt_path.read_text())
        assert receipt["nonce"] == intent["launch_nonce"]
        assert receipt["pid"] == receipt["pgid"] == receipt["session"]
        assert receipt["uid"] == os.getuid()
        if stage != "before_terminal":
            assert _same_identity(receipt)
        assert queue._read_receipt(at_barrier) == receipt
        if stage in {"before_hello", "after_hello"}:
            assert at_barrier.get("identity") is None
            assert not at_barrier.get("authorized", False)
        else:
            assert at_barrier["identity"] == receipt
        if stage in {"after_go", "before_terminal"}:
            assert at_barrier["authorized"]
        if stage == "after_go":
            known.append(wait_ready(run, job_id))
        if stage == "before_terminal":
            assert any(e["type"] == "job_worker_started" and e.get("attempt_id") == intent["attempt_id"]
                       for e in run.events.read())
            assert any(e["type"] == "job_cleanup_verified" and e.get("attempt_id") == intent["attempt_id"]
                       for e in run.events.read())
            assert _members(receipt["pgid"]) == []
        known.extend({**member, "pgid": receipt["pgid"]} for member in _members(receipt["pgid"]))
        if stage != "before_terminal":
            assert any(member["pid"] == receipt["pid"] for member in known)
        child.kill()
        child.wait(timeout=2)
        end = time.monotonic() + 4
        while time.monotonic() < end:
            result = queue.reconcile_run()[0]
            if result["status"] == "interrupted":
                break
            time.sleep(0.05)
        assert result["status"] == "interrupted"
        assert run_at(tmp_path).budget.expensive_calls == 1
        assert any(e["type"] == "wall_charged" and e.get("reason") == "job_recovery_cleanup"
                   for e in run.events.read())
        if stage == "before_terminal":
            assert any(e["type"] == "job_result_candidate" for e in run.events.read())
            assert result["output_handles"] == []
        assert _members(receipt["pgid"]) == []
        assert all(not member_running(member) for member in known)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
        if (tmp_path / "job_id").exists():
            cleanup_fixture(JobQueue(run_at(tmp_path)), (tmp_path / "job_id").read_text(), known)
        else:
            cleanup_test_owned(known)
        if receipt and _same_identity(receipt):
            JobQueue(run_at(tmp_path))._cleanup_owned(receipt)
