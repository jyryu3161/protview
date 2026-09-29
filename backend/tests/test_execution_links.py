"""M13 T2: narrow internal execution links on Run.call, JobQueue and report publication.

Fixture tools here return synthetic ``thing`` payloads for lifecycle checks only; they are not science.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mw.comparison_reports import build_comparison_report
from mw.core.contracts import ToolSpec
from mw.core.errors import FailureClass, ToolFailure
from mw.jobs.queue import JobQueue
from mw.method_reports import build_method_report
from mw.reports import EvidenceError, build_inspection_report
from mw.runtime.guards import Budget, BudgetLimits
from mw.runtime.orchestrator import ExecutionLink, ExecutionStopped, Run
from mw.tools.comparison import atom_rows
from mw.tools.registry import ToolRegistry
from mw.tools.structural import structure_residues
from mw.workflows import inspect_complex
from mw.workspace import build_registry, new_run

FIXTURES = Path(__file__).parent / "fixtures"
M10 = Path(__file__).parents[2] / "frontend/tests/offscreen/fixtures"
LINK_FIELD = "execution_link"


def link(op: str = "op_1", *, execution: str = "exec_a", step: str = "s01", **callbacks) -> ExecutionLink:
    return ExecutionLink(execution_id=execution, step_id=step, operation_id=op, **callbacks)


def record(value: ExecutionLink) -> dict:
    return {"execution_id": value.execution_id, "step_id": value.step_id, "operation_id": value.operation_id}


class Clock:
    def __init__(self):
        self.mono, self.utc, self.sleeps, self.on_sleep = 0.0, 1000.0, [], None

    def tick(self, seconds):
        self.mono += seconds
        self.utc += seconds

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.tick(seconds)
        if self.on_sleep:
            self.on_sleep()


def make_run(tmp_path, fn, *, cost_class: str = "cheap", clock: Clock | None = None, **kwargs) -> Run:
    spec = ToolSpec(name="make", level="L2", emits="thing", cost_class=cost_class,
                    params={"value": {"type": "int", "default": 1}})
    reg = ToolRegistry({"make": spec})
    reg.impls["make"] = fn
    if clock is not None:
        kwargs.update(sleep=clock.sleep, monotonic=lambda: clock.mono, utc=lambda: clock.utc)
    return Run("r", tmp_path / "r", reg, **kwargs)


def thing(ctx, value=1):
    return ctx.store.put("thing", "thing@1", {"value": value})


def events(run: Run) -> list[dict]:
    return list(run.events.read())


def linked(run: Run) -> list[dict]:
    return [e for e in events(run) if LINK_FIELD in e]


# ---------------------------------------------------------------- Run.call


def test_link_is_typed_and_ids_are_bounded(tmp_path):
    run = make_run(tmp_path, thing)
    with pytest.raises(TypeError):
        run.call("make", {}, execution_link={"execution_id": "exec_a", "step_id": "s01", "operation_id": "op"})
    for bad in ("", "x" * 200, "has space", "slash/x", None, 5):
        with pytest.raises((TypeError, ValueError)):
            ExecutionLink(execution_id=bad, step_id="s01", operation_id="op")
    assert not any(e["type"] == "tool_called" for e in events(run))


def test_unlinked_call_writes_no_link_and_no_new_event_types(tmp_path):
    run = make_run(tmp_path, thing)
    run.call("make", {"value": 2})
    run.call("make", {"value": 2})
    types = [e["type"] for e in events(run)]
    assert not linked(run)
    assert "execution_call_admitted" not in types and "execution_call_stopped" not in types
    assert types.count("tool_called") == 1 and types.count("cache_hit") == 1


def test_linked_call_carries_link_in_admission_call_success_and_cache_hit(tmp_path):
    seen: list[dict] = []
    attempts: list[dict] = []

    def admit(info):
        # The admission callback runs before any child event exists for this proposal.
        assert not any(e.get("proposal_id") == info["proposal_id"] or
                       e.get("root_call_id") == info["proposal_id"] for e in run.events.read())
        seen.append(info)

    def before_attempt(info):
        assert not any(e.get("call_id") == info["call_id"] for e in run.events.read())
        attempts.append(info)

    run = make_run(tmp_path, thing)
    first = link("op_1", admit=admit, before_attempt=before_attempt)
    out = run.call("make", {"value": 3}, decided_by="rule", execution_mode="autonomous",
                   branch_id="analysis_exec_a", execution_link=first)
    assert seen[0]["tool"] == "make" and seen[0]["args"] == {"value": 3} and seen[0]["lane"] == "run_call"
    assert len(attempts) == 1 and attempts[0]["execution_link"] == record(first)
    by_type = {e["type"]: e for e in linked(run)}
    assert set(by_type) == {"execution_call_admitted", "tool_called", "tool_succeeded"}
    assert all(e[LINK_FIELD] == record(first) for e in by_type.values())
    assert by_type["tool_called"]["call_id"] == attempts[0]["call_id"]
    assert by_type["execution_call_admitted"]["key"] == by_type["tool_called"]["key"]
    # Same call key under a different operation is a cache hit attributed to the new operation.
    second = link("op_2", admit=admit)
    again = run.call("make", {"value": 3}, decided_by="rule", execution_mode="autonomous",
                     branch_id="analysis_exec_a", execution_link=second)
    assert again.handle == out.handle
    hit = [e for e in events(run) if e["type"] == "cache_hit"]
    assert len(hit) == 1 and hit[0][LINK_FIELD] == record(second)
    assert sum(e["type"] == "tool_called" for e in events(run)) == 1
    # Links never change the call key or cache identity.
    run.call("make", {"value": 3})
    assert sum(e["type"] == "tool_called" for e in events(run)) == 1


def test_admission_refusal_starts_no_child(tmp_path):
    calls = []

    def fn(ctx, value=1):
        calls.append(value)
        return thing(ctx, value)

    def refuse(info):
        raise ToolFailure(FailureClass.precondition, "step not admitted", detail={"reason_code": "stale"})

    for cost in ("cheap", "expensive"):
        run = make_run(tmp_path / cost, fn, cost_class=cost)
        if cost == "expensive":
            run.approve("expensive_first_call")
        before = events(run)
        hooks = []
        with pytest.raises(ToolFailure) as exc:
            run.call("make", {"value": 1}, execution_mode="autonomous", branch_id="b",
                     execution_link=link(admit=refuse, before_attempt=hooks.append))
        assert exc.value.detail["reason_code"] == "stale"
        new = events(run)[len(before):]
        assert not any(e["type"] in {"tool_called", "budget_reserved", "branch_proposed", "cache_hit",
                                     "execution_call_admitted", "tool_succeeded"} for e in new)
        assert calls == [] and hooks == [] and run.budget.expensive_calls == 0


def test_failure_events_carry_link(tmp_path):
    def fatal(ctx, value=1):
        raise ToolFailure(FailureClass.fatal, "fixture failure")

    run = make_run(tmp_path, fatal)
    current = link()
    with pytest.raises(ToolFailure):
        run.call("make", {"value": 1}, execution_link=current)
    failed = [e for e in events(run) if e["type"] == "tool_failed"]
    assert failed and failed[0][LINK_FIELD] == record(current)
    with pytest.raises(ToolFailure):
        run.call("make", {"value": "bad"}, execution_link=current)
    rejected = [e for e in events(run) if e["type"] == "proposal_rejected"]
    assert rejected and rejected[0][LINK_FIELD] == record(current)


def test_linked_call_without_stop_callback_keeps_transient_schedule(tmp_path):
    clock = Clock()
    attempts = []

    def transient(ctx, value=1):
        attempts.append(ctx.call_id)
        raise ToolFailure(FailureClass.transient, "retryable")

    run = make_run(tmp_path, transient, clock=clock)
    with pytest.raises(ToolFailure) as exc:
        run.call("make", {}, execution_link=link())
    assert exc.value.cls == FailureClass.transient
    assert clock.sleeps == [2, 4, 8] and len(attempts) == 4
    assert run.budget.wall_clock_s == 14


def _assert_not_run_cancelled(run: Run) -> None:
    assert not run._cancel_path.exists() and not run.cancelled
    assert not any(e["type"] in {"cancel_requested", "run_cancelled"} for e in events(run))


def test_scoped_stop_before_backoff_ends_without_retry_or_run_cancel(tmp_path):
    clock = Clock()
    stop = {"flag": False}
    attempts = []

    def transient(ctx, value=1):
        attempts.append(ctx.call_id)
        stop["flag"] = True  # Stop arrives while the physical attempt is in flight.
        clock.tick(1.5)
        raise ToolFailure(FailureClass.transient, "retryable")

    run = make_run(tmp_path, transient, clock=clock)
    current = link(stopped=lambda: stop["flag"])
    with pytest.raises(ExecutionStopped) as exc:
        run.call("make", {}, execution_link=current)
    assert exc.value.stage == "before_backoff"
    assert len(attempts) == 1 and clock.sleeps == []
    log = events(run)
    assert not any(e["type"] == "backoff_started" for e in log)
    # The in-flight attempt is recorded and charged normally.
    failed = [e for e in log if e["type"] == "tool_failed"]
    assert len(failed) == 1 and failed[0]["call_id"] == attempts[0]
    assert any(e["type"] == "wall_charged" and e.get("reason") == "attempt" and
               e.get("call_id") == attempts[0] and e["seconds"] == 1.5 for e in log)
    stopped = [e for e in log if e["type"] == "execution_call_stopped"]
    assert len(stopped) == 1 and stopped[0][LINK_FIELD] == record(current)
    assert stopped[0]["after_call_id"] == attempts[0]
    _assert_not_run_cancelled(run)
    # The run itself remains usable for other work.
    assert Run("r", run.run_dir, run.registry, sleep=clock.sleep, monotonic=lambda: clock.mono,
               utc=lambda: clock.utc).cancelled is False


def test_scoped_stop_during_backoff_prevents_the_retry(tmp_path):
    clock = Clock()
    stop = {"flag": False}
    attempts = []
    hooks = []

    def transient(ctx, value=1):
        attempts.append(ctx.call_id)
        raise ToolFailure(FailureClass.transient, "retryable")

    clock.on_sleep = lambda: stop.update(flag=True)
    run = make_run(tmp_path, transient, clock=clock)
    with pytest.raises(ExecutionStopped) as exc:
        run.call("make", {}, execution_link=link(stopped=lambda: stop["flag"], before_attempt=hooks.append))
    assert exc.value.stage == "before_attempt"
    assert clock.sleeps == [2] and len(attempts) == 1 and len(hooks) == 1
    log = events(run)
    assert [e["type"] for e in log if e["type"].startswith("backoff_")] == ["backoff_started",
                                                                            "backoff_completed"]
    assert run.budget.wall_clock_s == 2  # backoff was active time, charged once
    _assert_not_run_cancelled(run)


def test_stop_during_successful_attempt_keeps_the_result(tmp_path):
    stop = {"flag": False}

    def fn(ctx, value=1):
        stop["flag"] = True
        return thing(ctx, value)

    run = make_run(tmp_path, fn)
    out = run.call("make", {"value": 4}, execution_link=link(stopped=lambda: stop["flag"]))
    succeeded = [e for e in events(run) if e["type"] == "tool_succeeded"]
    assert len(succeeded) == 1 and succeeded[0]["output"]["handle"] == out.handle
    assert not any(e["type"] == "execution_call_stopped" for e in events(run))


def test_attempt_hook_runs_before_every_physical_start_and_can_refuse(tmp_path):
    clock = Clock()
    outcomes = iter([ToolFailure(FailureClass.transient, "a"), ToolFailure(FailureClass.transient, "b"), None])
    hooks = []

    def flaky(ctx, value=1):
        failure = next(outcomes)
        if failure:
            raise failure
        return thing(ctx, value)

    def before_attempt(info):
        assert not any(e.get("call_id") == info["call_id"] for e in run.events.read())
        hooks.append(info)

    run = make_run(tmp_path, flaky, clock=clock)
    run.call("make", {}, execution_link=link(before_attempt=before_attempt))
    called = [e["call_id"] for e in events(run) if e["type"] == "tool_called"]
    assert [h["call_id"] for h in hooks] == called and len(called) == 3
    assert [h["attempt_kind"] for h in hooks] == ["initial", "transient_retry", "transient_retry"]
    assert all(e.get(LINK_FIELD) == record(link()) for e in events(run) if e["type"] == "tool_called")

    refused_calls = []

    def transient(ctx, value=1):
        refused_calls.append(ctx.call_id)
        raise ToolFailure(FailureClass.transient, "retryable")

    def limit(info):
        if info["attempt_kind"] != "initial":
            raise ToolFailure(FailureClass.resource_exceeded, "workflow attempt ceiling")

    other = make_run(tmp_path / "other", transient, clock=Clock())
    with pytest.raises(ToolFailure) as exc:
        other.call("make", {}, execution_link=link(before_attempt=limit))
    assert exc.value.cls == FailureClass.resource_exceeded
    assert len(refused_calls) == 1
    assert sum(e["type"] == "tool_called" for e in events(other)) == 1


def test_expensive_attempt_hook_precedes_reservation(tmp_path):
    hooks = []

    def before_attempt(info):
        assert not any(e["type"] == "budget_reserved" for e in run.events.read())
        hooks.append(info)

    run = make_run(tmp_path, thing, cost_class="expensive")
    run.approve("expensive_first_call")
    run.call("make", {}, execution_link=link(before_attempt=before_attempt))
    assert len(hooks) == 1 and run.budget.expensive_calls == 1


def test_orphaned_linked_call_interruption_keeps_link(tmp_path):
    current = link()
    run = make_run(tmp_path, thing)
    run.events.append("tool_called", tool="make", key="k", call_id="call_orphan", root_call_id="p",
                      parent_call_id=None, args={}, attempt_kind="initial", decided_by="rule",
                      execution_mode="human", branch_id=None, version="1", remaining_wall_s=10,
                      ts=run.utc(), execution_link=record(current))
    run.call("make", {"value": 9})
    interrupted = [e for e in events(run) if e["type"] == "tool_interrupted"]
    assert interrupted and interrupted[0][LINK_FIELD] == record(current)


# ---------------------------------------------------------------- JobQueue


def _jobs_run(tmp_path: Path, run_id: str = "run_jobs") -> Run:
    return new_run(tmp_path, run_id=run_id, registry=build_registry(), dry_run=False)


def denied_launch(*args, **kwargs):
    raise OSError("fixed launch failure")


def test_unlinked_fixture_submission_is_unchanged(tmp_path):
    run = _jobs_run(tmp_path)
    job = JobQueue(run, fixture_mode="normal").submit_fixture()
    assert "execution_ownership" not in job and "execution_link" not in job
    assert not linked(run)


def test_owned_job_link_in_submission_and_attempt_events_with_hook(tmp_path):
    run = _jobs_run(tmp_path)
    run.approve("expensive_first_call")
    queue = JobQueue(run, fixture_mode="normal", popen=denied_launch)
    current = link()
    hooks = []

    def before_attempt(info):
        assert not any(e["type"] == "budget_reserved" for e in run.events.read())
        hooks.append(info)

    job = queue.submit_fixture(execution_link=current)
    assert job["execution_ownership"] == "owned"
    submitted = [e for e in events(run) if e["type"] == "job_submitted"]
    assert submitted[0][LINK_FIELD] == record(current)
    starter = link(before_attempt=before_attempt)
    result = queue.start(job["job_id"], execution_link=starter)
    assert result["status"] == "failed"
    assert len(hooks) == 1 and hooks[0]["job_id"] == job["job_id"] and hooks[0]["lane"] == "job"
    reserved = [e for e in events(run) if e["type"] == "budget_reserved"]
    assert hooks[0]["attempt_id"] == reserved[0]["attempt_id"]
    for kind in ("job_claimed", "job_dispatch_intent", "job_terminal"):
        found = [e for e in events(run) if e["type"] == kind]
        assert found and found[-1][LINK_FIELD] == record(current), kind
    # Explicit retry under the same owner link is recorded with the link.
    queue.retry(job["job_id"], execution_link=current)
    retried = [e for e in events(run) if e["type"] == "job_retry_queued"]
    assert retried[0][LINK_FIELD] == record(current)


def test_attempt_hook_refusal_prevents_reservation_and_dispatch(tmp_path):
    run = _jobs_run(tmp_path)
    run.approve("expensive_first_call")
    queue = JobQueue(run, fixture_mode="normal", popen=denied_launch)
    current = link()
    job = queue.submit_fixture(execution_link=current)

    def ceiling(info):
        raise ToolFailure(FailureClass.resource_exceeded, "workflow attempt ceiling")

    with pytest.raises(ToolFailure) as exc:
        queue.start(job["job_id"], execution_link=link(before_attempt=ceiling))
    assert exc.value.cls == FailureClass.resource_exceeded
    assert run.budget.expensive_calls == 0
    assert not any(e["type"] in {"budget_reserved", "job_dispatch_intent"} for e in events(run))


def test_scoped_stop_refuses_start_and_scoped_cancel_is_owner_only(tmp_path):
    run = _jobs_run(tmp_path)
    run.approve("expensive_first_call")
    queue = JobQueue(run, fixture_mode="normal", popen=denied_launch)
    current = link()
    job = queue.submit_fixture(execution_link=current)
    with pytest.raises(ExecutionStopped):
        queue.start(job["job_id"], execution_link=link(stopped=lambda: True))
    assert queue.get(job["job_id"])["status"] == "queued"
    assert not any(e["type"] in {"job_claimed", "budget_reserved"} for e in events(run))
    stranger = link(execution="exec_b")
    with pytest.raises(ToolFailure) as exc:
        queue.start(job["job_id"], execution_link=stranger)
    assert exc.value.detail["reason_code"] == "job_not_owned"
    with pytest.raises(ToolFailure) as exc:
        queue.request_cancel(job["job_id"], execution_link=stranger)
    assert exc.value.detail["reason_code"] == "job_not_owned"
    assert queue.get(job["job_id"])["status"] == "queued"
    outcome = queue.request_cancel(job["job_id"], execution_link=current)
    assert outcome["status"] == "accepted" and outcome["job"]["status"] == "cancelled"
    cancel = [e for e in events(run) if e["type"] == "job_cancel_requested"]
    assert cancel[0][LINK_FIELD] == record(current)
    _assert_not_run_cancelled(run)
    assert run.budget.expensive_calls == 0
    # Unlinked jobs cannot be cancelled through a link either.
    plain = queue.submit_fixture()
    with pytest.raises(ToolFailure):
        queue.request_cancel(plain["job_id"], execution_link=current)


def _openmm_run(tmp_path: Path) -> tuple[Run, dict]:
    run = new_run(tmp_path, dry_run=False, run_id="run_openmm")
    name = "public_1ubq.cif"
    source = run.call("load_structure", {"source": name, "model_index": 0},
                      source_bytes=(FIXTURES / name).read_bytes(), source_format="cif")
    prepared = run.call("prepare_structure", {
        "structure": source.handle, "altloc": "highest_occupancy", "waters": "keep_all",
        "hydrogens": "strip", "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
    return run, {"structure": prepared.handle, "selection_policy": "protein_only",
                 "hydrogen_policy": "rebuild_pH7"}


def test_submit_records_owned_versus_observed_shared_atomically(tmp_path):
    run, args = _openmm_run(tmp_path)
    queue = JobQueue(run)
    admitted = []
    owner = link("op_1", admit=admitted.append)
    job = queue.submit("openmm_protein_minimize", args, execution_link=owner)
    assert job["execution_ownership"] == "owned"
    assert admitted[0]["lane"] == "job" and admitted[0]["existing_job_id"] is None
    submitted = [e for e in events(run) if e["type"] == "job_submitted"]
    assert len(submitted) == 1 and submitted[0][LINK_FIELD] == record(owner)
    # Same link again (crash recovery of the same operation) is still owned, with no new event.
    count = len(events(run))
    assert queue.submit("openmm_protein_minimize", args, execution_link=owner)["execution_ownership"] == "owned"
    assert len(events(run)) == count
    # Another execution reaching the same call key only observes the existing job.
    observer = link("op_9", execution="exec_b", admit=admitted.append)
    shared = queue.submit("openmm_protein_minimize", args, execution_link=observer)
    assert shared["job_id"] == job["job_id"] and shared["execution_ownership"] == "observed_shared"
    assert admitted[-1]["existing_job_id"] == job["job_id"]
    observed = [e for e in events(run) if e["type"] == "job_observed"]
    assert len(observed) == 1 and observed[0][LINK_FIELD] == record(observer)
    assert observed[0]["job_id"] == job["job_id"] and observed[0]["ownership"] == "observed_shared"
    count = len(events(run))
    assert queue.submit("openmm_protein_minimize", args,
                        execution_link=observer)["execution_ownership"] == "observed_shared"
    assert len(events(run)) == count
    # The observer can never start or cancel the shared job.
    with pytest.raises(ToolFailure):
        queue.start(job["job_id"], execution_link=observer)
    with pytest.raises(ToolFailure):
        queue.request_cancel(job["job_id"], execution_link=observer)
    # Unlinked dedup is byte-for-byte the historical behavior.
    plain = queue.submit("openmm_protein_minimize", args)
    assert plain["job_id"] == job["job_id"] and "execution_ownership" not in plain
    assert len(events(run)) == count
    assert sum(e["type"] == "job_submitted" for e in events(run)) == 1


def test_submit_admission_refusal_creates_no_job(tmp_path):
    run, args = _openmm_run(tmp_path)

    def refuse(info):
        raise ToolFailure(FailureClass.precondition, "not next step")

    with pytest.raises(ToolFailure):
        JobQueue(run).submit("openmm_protein_minimize", args, execution_link=link(admit=refuse))
    assert not any(e["type"] in {"job_submitted", "job_observed"} for e in events(run))


def test_manual_submission_first_makes_workflow_an_observer(tmp_path):
    run, args = _openmm_run(tmp_path)
    queue = JobQueue(run)
    manual = queue.submit("openmm_protein_minimize", args)
    shared = queue.submit("openmm_protein_minimize", args, execution_link=link())
    assert shared["job_id"] == manual["job_id"] and shared["execution_ownership"] == "observed_shared"


# ---------------------------------------------------------------- reports


def _report_events(run: Run) -> list[dict]:
    return [e for e in events(run) if e["type"] in {"report_created", "method_report_created"}]


def test_inspection_report_link_and_idempotent_publication(tmp_path):
    run = new_run(tmp_path, run_id="run_report", dry_run=False)
    raw = (FIXTURES / "mini_complex.pdb").read_bytes()
    outcome = inspect_complex(run, {"upload_id": f"upload://run_report/{hashlib.sha256(raw).hexdigest()}.pdb",
                                    "model_index": 0}, source_bytes=raw, source_format="pdb")
    interaction = outcome["outputs"]["interactions"]
    before = len(_report_events(run))
    admitted = []
    current = link(admit=admitted.append)
    first = build_inspection_report(run, interaction, execution_link=current)
    created = _report_events(run)[before:]
    assert len(created) == 1 and created[0][LINK_FIELD] == record(current) and len(admitted) == 1
    count = len(events(run))
    again = build_inspection_report(run, interaction, execution_link=current)
    assert again["handle"] == first["handle"] and again["markdown"] == first["markdown"]
    assert len(events(run)) == count and len(admitted) == 1
    # A link reused for a different source fails closed instead of republishing.
    with pytest.raises(EvidenceError):
        build_inspection_report(run, "obj://run_report/interaction_set/" + "0" * 64, execution_link=current)
    # Unlinked calls keep publishing a new report event without a link.
    build_inspection_report(run, interaction)
    assert LINK_FIELD not in _report_events(run)[-1]


def test_report_admission_refusal_publishes_nothing(tmp_path):
    run = new_run(tmp_path, run_id="cmp")
    ref = run.call("load_structure", {"source": str(M10 / "m10-reference.pdb"), "model_index": 0}).handle
    rows = atom_rows(run.store, ref)
    pick = [row["ref"] for row in rows["rows"]][:2]
    distance = run.call("measure_distance", {"structure": ref, "first": pick[0], "second": pick[1]}).handle

    def refuse(info):
        raise ToolFailure(FailureClass.precondition, "cancelled execution")

    count = len(events(run))
    with pytest.raises(ToolFailure):
        build_comparison_report(run, distance, execution_link=link(admit=refuse))
    assert len(events(run)) == count
    current = link()
    first = build_comparison_report(run, distance, execution_link=current)
    assert _report_events(run)[-1][LINK_FIELD] == record(current)
    count = len(events(run))
    assert build_comparison_report(run, distance, execution_link=current)["handle"] == first["handle"]
    assert len(events(run)) == count


def test_method_report_link_idempotency(tmp_path):
    run = new_run(tmp_path, run_id="run_sasa", dry_run=False)
    source = run.call("load_structure", {"source": str(tmp_path / "removed_source.pdb")},
                      source_bytes=(FIXTURES / "mini_complex.pdb").read_bytes(), source_format="pdb")
    prepared = run.call("prepare_structure", {"structure": source.handle})
    ligand = structure_residues(run.store, prepared.handle)["ligands"][0]
    result = run.call("compute_interface_sasa", {"structure": prepared.handle, "ligand": ligand})
    current = link()
    first = build_method_report(run, result.handle, execution_link=current)
    assert _report_events(run)[-1][LINK_FIELD] == record(current)
    count = len(events(run))
    assert build_method_report(run, result.handle, execution_link=current)["handle"] == first["handle"]
    assert len(events(run)) == count
    plain = build_method_report(run, result.handle)
    assert LINK_FIELD not in _report_events(run)[-1] and plain["manifest"]["result_handle"] == result.handle


def test_budget_limits_unchanged_by_links(tmp_path):
    run = make_run(tmp_path, thing, budget=Budget(limits=BudgetLimits(expensive_calls=3)))
    run.call("make", {"value": 5}, execution_link=link())
    assert run.budget.expensive_calls == 0
