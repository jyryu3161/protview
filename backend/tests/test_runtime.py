"""M2 behavioral gates: physical attempts, durable recovery, and branch observations."""
from __future__ import annotations

import multiprocessing
import os
import time

import pytest

from mw.core.contracts import ToolSpec
from mw.core.errors import FailureClass, Fix, ToolFailure
from mw.core.events import EventLog
from mw.runtime.guards import Budget, BudgetLimits, LoopGuard, LoopStop
from mw.runtime.orchestrator import ApprovalRequired, Run, RunCancelled
from mw.tools.registry import ToolRegistry
from mw.workspace import build_registry


def registry(*specs: ToolSpec) -> ToolRegistry:
    return ToolRegistry({spec.name: spec for spec in specs})


def thing(ctx, **kwargs):
    return ctx.store.put("thing", "thing@1", {"value": kwargs.get("value", 1)})


def make_run(tmp_path, *, spec=None, fn=thing, **kwargs):
    spec = spec or ToolSpec(name="make", level="L2", emits="thing",
                           params={"value": {"type": "int", "default": 1}})
    reg = registry(spec)
    reg.impls[spec.name] = fn
    return Run("r", tmp_path / "r", reg, **kwargs)


class Clock:
    def __init__(self):
        self.mono = 0.0
        self.utc = 1000.0
        self.sleeps = []

    def tick(self, seconds):
        self.mono += seconds
        self.utc += seconds

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.tick(seconds)


def test_invalid_contracts_before_execution(tmp_path):
    calls = []
    spec = ToolSpec(name="needs", level="L2", emits="thing",
                    accepts={"structure": ["prepared_structure"]},
                    params={"policy": {"type": "str", "enum": ["keep"]},
                            "cutoff": {"type": "float", "min": 0}})
    run = make_run(tmp_path, spec=spec, fn=lambda ctx, **kw: calls.append(kw))
    structure = run.store.put("structure", "structure@1", b"fixture", fmt="pdb")
    cases = [
        ("unknown", {}, FailureClass.input_invalid),
        ("needs", {"structure": [structure.handle]}, FailureClass.input_invalid),
        ("needs", {"structure": structure.handle}, FailureClass.precondition),
        ("needs", {"structure": structure.handle, "policy": "discard"}, FailureClass.precondition),
        ("needs", {"structure": "obj://r/thing/" + "0" * 64}, FailureClass.input_invalid),
    ]
    for tool, args, expected in cases:
        with pytest.raises(ToolFailure) as exc:
            run.call(tool, args)
        assert exc.value.cls == expected
    prepared = run.store.put("prepared_structure", "structure@1", b"fixture", fmt="pdb")
    for args in ({"structure": prepared.handle, "policy": "discard"},
                 {"structure": prepared.handle, "cutoff": float("nan")},
                 {"structure": prepared.handle, "cutoff": float("inf")},
                 {"structure": prepared.handle, "policy": {"nested": [float("nan")]}},
                 {"structure": prepared.handle, "bad": 1}):
        with pytest.raises(ToolFailure) as exc:
            run.call("needs", args)
        assert exc.value.cls == FailureClass.input_invalid
    assert calls == []
    assert sum(e["type"] == "proposal_rejected" for e in run.events.read()) == 10


def test_unimplemented_and_collection_shape(tmp_path):
    spec = ToolSpec(name="collect", level="L2", emits="thing",
                    accepts={"items": ["thing"]}, handle_cardinality={"items": "collection"})
    reg = registry(spec, ToolSpec(name="missing", level="L2", emits="thing"))
    reg.impls["collect"] = thing
    run = Run("r", tmp_path / "r", reg)
    handle = run.store.put("thing", "thing@1", {"fixture": True})
    for tool, args in (("missing", {}), ("collect", {"items": handle.handle}),
                       ("collect", {"items": []})):
        with pytest.raises(ToolFailure) as exc:
            run.call(tool, args)
        assert exc.value.cls == FailureClass.input_invalid


def test_transient_ceiling_sleep_and_reopen(tmp_path):
    clock = Clock()
    attempts = []

    def transient(ctx):
        attempts.append(ctx.call_id)
        raise ToolFailure(FailureClass.transient, "retryable")

    run = make_run(tmp_path, spec=ToolSpec(name="make", level="L2", emits="thing"),
                   fn=transient, sleep=clock.sleep, monotonic=lambda: clock.mono,
                   utc=lambda: clock.utc)
    with pytest.raises(ToolFailure) as exc:
        run.call("make", {})
    assert exc.value.cls == FailureClass.transient
    assert clock.sleeps == [2, 4, 8]
    assert len(attempts) == len(set(attempts)) == 4
    assert run.budget.wall_clock_s == 14
    reopened = Run("r", run.run_dir, run.registry, sleep=clock.sleep,
                   monotonic=lambda: clock.mono, utc=lambda: clock.utc)
    assert reopened.budget.wall_clock_s == 14
    with pytest.raises(ToolFailure):
        reopened.repair_call(attempts[-1], {})
    assert sum(e["type"] == "tool_called" for e in reopened.events.read()) == 4


def test_changed_argument_repair_once(tmp_path):
    def fail_one(ctx, value):
        if value == 1:
            raise ToolFailure(FailureClass.input_invalid, "change value")
        return thing(ctx, value=value)

    run = make_run(tmp_path, fn=fail_one)
    with pytest.raises(ToolFailure):
        run.call("make", {"value": 1})
    failed = next(e["call_id"] for e in run.events.read() if e["type"] == "tool_failed")
    with pytest.raises(ToolFailure, match="change effective"):
        run.repair_call(failed, {"value": 1})
    out = run.repair_call(failed, {"value": 2})
    assert run.store.load(out.handle) == {"value": 2}
    reopened = Run("r", run.run_dir, run.registry)
    with pytest.raises(ToolFailure, match="already used"):
        reopened.repair_call(failed, {"value": 3})
    calls = [e for e in run.events.read() if e["type"] == "tool_called"]
    assert [e["attempt_kind"] for e in calls] == ["initial", "argument_repair"]
    assert calls[1]["parent_call_id"] == failed


def test_prerequisite_binds_real_handle_once_and_rejects_missing(tmp_path):
    needs = ToolSpec(name="needs", level="L2", emits="thing",
                     accepts={"structure": ["prepared_structure"]})
    prep = ToolSpec(name="prepare_structure", level="L2", emits="prepared_structure",
                    accepts={"structure": ["structure"]})
    reg = registry(needs, prep)
    seen = []
    reg.impls["needs"] = lambda ctx, structure: (seen.append(structure) or thing(ctx))
    reg.impls["prepare_structure"] = lambda ctx, structure: ctx.store.put(
        "prepared_structure", "structure@1", b"prepared fixture", fmt="pdb")
    run = Run("r", tmp_path / "r", reg)
    raw = run.store.put("structure", "structure@1", b"raw fixture", fmt="pdb")
    with pytest.raises(ToolFailure) as exc:
        run.call("needs", {"structure": raw.handle})
    assert exc.value.cls == FailureClass.precondition
    failed = next(e["proposal_id"] for e in run.events.read() if e["type"] == "proposal_rejected")
    run.satisfy_precondition(failed)
    assert len(seen) == 1 and run.store.kind_of(seen[0]) == "prepared_structure"
    with pytest.raises(ToolFailure, match="already used"):
        run.satisfy_precondition(failed)
    evidence = [e for e in run.events.read() if e["type"] == "decision" and
                e["question"] == "prerequisite_evidence"]
    assert evidence[0]["answer"]["output_handle"] == seen[0]
    assert [e["attempt_kind"] for e in run.events.read() if e["type"] == "tool_called"] == [
        "prerequisite", "prerequisite_retry"]


def test_prerequisite_missing_wrong_kind_and_undeclared_do_not_recurse(tmp_path):
    needs = ToolSpec(name="needs", level="L2", emits="thing",
                     accepts={"structure": ["prepared_structure"]})
    prep = ToolSpec(name="prepare_structure", level="L2", emits="prepared_structure",
                    accepts={"structure": ["structure"]})
    reg = registry(needs, prep)
    reg.impls["needs"] = lambda ctx, structure: thing(ctx)
    reg.impls["prepare_structure"] = lambda ctx, structure: ctx.store.put(
        "thing", "thing@1", {"wrong": True})
    run = Run("r", tmp_path / "wrong", reg)
    raw = run.store.put("structure", "structure@1", b"fixture", fmt="pdb")
    with pytest.raises(ToolFailure):
        run.call("needs", {"structure": raw.handle})
    failed = next(e["proposal_id"] for e in run.events.read() if e["type"] == "proposal_rejected")
    with pytest.raises(ToolFailure) as exc:
        run.satisfy_precondition(failed)
    assert exc.value.cls == FailureClass.fatal
    assert sum(e["tool"] == "needs" for e in run.events.read() if e["type"] == "tool_called") == 0
    with pytest.raises(ToolFailure, match="already used"):
        run.satisfy_precondition(failed)
    reg.impls["prepare_structure"] = lambda ctx, structure: (_ for _ in ()).throw(
        ToolFailure(FailureClass.input_invalid, "bad prerequisite input"))
    nested = Run("r", tmp_path / "nested", reg)
    nested_raw = nested.store.put("structure", "structure@1", b"fixture", fmt="pdb")
    with pytest.raises(ToolFailure):
        nested.call("needs", {"structure": nested_raw.handle})
    proposal = next(e["proposal_id"] for e in nested.events.read() if e["type"] == "proposal_rejected")
    with pytest.raises(ToolFailure):
        nested.satisfy_precondition(proposal)
    pre_failed = next(e["call_id"] for e in nested.events.read() if e["type"] == "tool_failed")
    with pytest.raises(ToolFailure, match="no nested repair"):
        nested.repair_call(pre_failed, {"structure": nested_raw.handle})
    no_fix = ToolSpec(name="no_fix", level="L2", emits="thing")
    reg = registry(no_fix, prep)
    reg.impls["no_fix"] = lambda ctx: (_ for _ in ()).throw(
        ToolFailure(FailureClass.precondition, "missing"))
    reg.impls["prepare_structure"] = lambda ctx, structure: thing(ctx)
    run = Run("r", tmp_path / "missing", reg)
    with pytest.raises(ToolFailure):
        run.call("no_fix", {})
    failed = next(e["call_id"] for e in run.events.read() if e["type"] == "tool_failed")
    with pytest.raises(ToolFailure, match="no allowlisted"):
        run.satisfy_precondition(failed)
    assert sum(e["type"] == "tool_called" for e in run.events.read()) == 1
    reg.impls["no_fix"] = lambda ctx: (_ for _ in ()).throw(
        ToolFailure(FailureClass.precondition, "undeclared",
                    fix=Fix(tool="prepare_structure", args={"structure": raw.handle})))
    run = Run("r", tmp_path / "undeclared", reg)
    with pytest.raises(ToolFailure):
        run.call("no_fix", {})
    failed = next(e["call_id"] for e in run.events.read() if e["type"] == "tool_failed")
    with pytest.raises(ToolFailure, match="undeclared"):
        run.satisfy_precondition(failed)


def test_terminal_failures_fatal_exception_and_scientific_null(tmp_path):
    for failure_class in (FailureClass.resource_exceeded, FailureClass.fatal):
        count = []

        def fails(ctx, records=count, cls=failure_class):
            records.append(ctx.call_id)
            raise ToolFailure(cls, "stop")

        run = make_run(tmp_path / failure_class.value,
                       spec=ToolSpec(name="make", level="L2", emits="thing"), fn=fails)
        with pytest.raises(ToolFailure) as exc:
            run.call("make", {})
        assert exc.value.cls == failure_class and len(count) == 1
    run = make_run(tmp_path / "exception", spec=ToolSpec(name="make", level="L2", emits="thing"),
                   fn=lambda ctx: 1 / 0)
    with pytest.raises(ToolFailure) as exc:
        run.call("make", {})
    assert exc.value.cls == FailureClass.fatal
    assert "ZeroDivisionError" in next(e for e in run.events.read() if e["type"] == "tool_failed")["detail"]["diagnostic"]
    run = make_run(tmp_path / "null", spec=ToolSpec(name="make", level="L2", emits="thing"),
                   fn=lambda ctx: ctx.store.put("thing", "thing@1", [], null_result=True))
    out = run.call("make", {})
    assert out.null_result and sum(e["type"] == "tool_called" for e in run.events.read()) == 1


def test_human_cache_observation_and_autonomous_repeat_after_reopen(tmp_path):
    run = make_run(tmp_path)
    first = run.call("make", {})
    assert run.call("make", {}).handle == first.handle
    assert run.call("make", {}).handle == first.handle
    cache = [e for e in run.events.read() if e["type"] == "cache_hit"]
    assert len(cache) == 2 and len({e["observation_id"] for e in cache}) == 2
    physical_id = next(e["call_id"] for e in run.events.read() if e["type"] == "tool_called")
    assert all(e["source_call_id"] == physical_id for e in cache)
    assert cache[0]["args"] == {"value": 1}
    assert sum(e["type"] == "tool_called" for e in run.events.read()) == 1
    run.call("make", {}, execution_mode="autonomous", branch_id="b")
    reopened = Run("r", run.run_dir, run.registry)
    reopened.call("make", {}, execution_mode="autonomous", branch_id="b")
    with pytest.raises(LoopStop) as exc:
        reopened.call("make", {}, execution_mode="autonomous", branch_id="b")
    assert exc.value.reason == "repeated_call_hash"
    assert sum(e["type"] == "tool_called" for e in reopened.events.read()) == 1


def test_no_progress_and_ab_oscillation_are_by_key_and_handle(tmp_path):
    run = make_run(tmp_path / "no_progress", guard=LoopGuard(repeated_call_hash=10),
                   fn=lambda ctx, value: ctx.store.put("thing", "thing@1", {"same": True}))
    for value in range(1, 5):
        run.call("make", {"value": value}, execution_mode="autonomous", branch_id="b")
    with pytest.raises(LoopStop) as exc:
        run.call("make", {"value": 5}, execution_mode="autonomous", branch_id="b")
    assert exc.value.reason == "no_progress"
    reopened = Run("r", run.run_dir, run.registry)
    with pytest.raises(LoopStop):
        reopened.call("make", {"value": 6}, execution_mode="autonomous", branch_id="b")
    run = make_run(tmp_path / "ab", guard=LoopGuard(no_progress_steps=10, repeated_call_hash=10),
                   fn=lambda ctx, value: ctx.store.put("thing", "thing@1", {"same": True}))
    for value in [1, 2, 1, 2, 1, 2]:
        run.call("make", {"value": value}, execution_mode="autonomous", branch_id="b")
    with pytest.raises(LoopStop) as exc:
        run.call("make", {"value": 1}, execution_mode="autonomous", branch_id="b")
    assert exc.value.reason == "oscillation"
    useful = make_run(tmp_path / "useful", guard=LoopGuard(no_progress_steps=10, repeated_call_hash=10),
                      spec=ToolSpec(name="make", level="L2", emits="thing", idempotent=False,
                                    params={"value": {"type": "int", "default": 1}}),
                      fn=lambda ctx, value: ctx.store.put("thing", "thing@1", {"call": ctx.call_id}))
    for value in [1, 2, 1, 2, 1, 2, 1]:
        useful.call("make", {"value": value}, execution_mode="autonomous", branch_id="b")


def test_expense_failure_approval_budget_reopen_and_denial(tmp_path):
    count = []

    def costly(ctx, value):
        count.append(value)
        raise ToolFailure(FailureClass.resource_exceeded, "fixture timeout")

    spec = ToolSpec(name="make", level="L3", emits="thing", cost_class="expensive",
                    params={"value": {"type": "int", "required": True}})
    run = make_run(tmp_path, spec=spec, fn=costly,
                   budget=Budget(limits=BudgetLimits(expensive_calls=2)))
    with pytest.raises(ToolFailure):
        run.call("make", {"value": "invalid"})
    with pytest.raises(ApprovalRequired) as exc:
        run.call("make", {"value": 1})
    assert exc.value.gate == "expensive_first_call" and run.budget.expensive_calls == 0
    run.approve("expensive_first_call")
    for value in (1, 2):
        with pytest.raises(ToolFailure):
            run.call("make", {"value": value})
    reopened = Run("r", run.run_dir, run.registry)
    assert reopened.approved_expensive and reopened.budget.expensive_calls == 2
    with pytest.raises(ApprovalRequired) as exc:
        reopened.call("make", {"value": 3})
    assert exc.value.gate == "budget" and count == [1, 2]
    reopened.update_limits(BudgetLimits(expensive_calls=3))
    assert Run("r", run.run_dir, run.registry).budget.limits.expensive_calls == 3
    with pytest.raises(ValueError, match="incompatible"):
        Run("r", run.run_dir, run.registry, budget=Budget(limits=BudgetLimits(expensive_calls=7)))
    with pytest.raises(ValueError, match="incompatible"):
        Run("r", run.run_dir, run.registry, guard=LoopGuard(no_progress_steps=9))


def test_expensive_transient_charges_before_each_attempt_and_skips_unfunded_backoff(tmp_path):
    clock = Clock()
    attempts = []

    def fails(ctx):
        attempts.append(ctx.call_id)
        raise ToolFailure(FailureClass.transient, "fixture")

    run = make_run(tmp_path, spec=ToolSpec(name="make", level="L3", emits="thing",
                                           cost_class="expensive"),
                   fn=fails, budget=Budget(limits=BudgetLimits(expensive_calls=2)),
                   sleep=clock.sleep, monotonic=lambda: clock.mono, utc=lambda: clock.utc)
    run.approve("expensive_first_call")
    with pytest.raises(ApprovalRequired) as exc:
        run.call("make", {})
    assert exc.value.gate == "budget"
    assert len(attempts) == run.budget.expensive_calls == 2
    assert clock.sleeps == [2]


def test_wall_backoff_idle_orphan_and_clock_anomaly(tmp_path):
    clock = Clock()

    def transient(ctx):
        clock.tick(1)
        raise ToolFailure(FailureClass.transient, "fixture")

    run = make_run(tmp_path / "backoff", spec=ToolSpec(name="make", level="L2", emits="thing"),
                   fn=transient, budget=Budget(limits=BudgetLimits(wall_clock_s=5)),
                   sleep=clock.sleep, monotonic=lambda: clock.mono, utc=lambda: clock.utc)
    with pytest.raises(ApprovalRequired) as exc:
        run.call("make", {})
    assert exc.value.gate == "budget" and clock.sleeps == [2]
    assert run.budget.wall_clock_s == 4
    clock.tick(1000)
    reopened = Run("r", run.run_dir, run.registry, monotonic=lambda: clock.mono,
                   utc=lambda: clock.utc)
    assert reopened.budget.wall_clock_s == 4
    orphan = make_run(tmp_path / "orphan", spec=ToolSpec(name="make", level="L2", emits="thing"),
                      monotonic=lambda: clock.mono, utc=lambda: clock.utc)
    orphan.events.append("tool_called", tool="make", key="orphan", call_id="orphan",
                         root_call_id="orphan", args={}, attempt_kind="initial",
                         remaining_wall_s=7, ts=clock.utc)
    clock.tick(20)
    observed = Run("r", orphan.run_dir, orphan.registry, monotonic=lambda: clock.mono,
                   utc=lambda: clock.utc)
    assert not any(e["type"] == "tool_interrupted" for e in observed.events.read())
    observed.call("make", {})
    assert any(e["type"] == "wall_charged" and e.get("reason") == "orphan_recovery" and
               e["seconds"] == 7 for e in observed.events.read())
    assert any(e["type"] == "tool_interrupted" for e in observed.events.read())
    anomaly = make_run(tmp_path / "anomaly", monotonic=lambda: clock.mono, utc=lambda: clock.utc)
    anomaly.events.append("tool_called", tool="make", key="future", call_id="future",
                          root_call_id="future", args={}, attempt_kind="initial",
                          remaining_wall_s=7, ts=clock.utc + 10)
    anomaly.call("make", {})
    assert any(e["type"] == "clock_anomaly" for e in anomaly.events.read())


def test_active_wall_snapshot_and_cooperative_deadline(tmp_path):
    clock = Clock()
    observed = []
    holder = {}

    def work(ctx):
        clock.tick(2)
        observed.append((ctx.remaining_s(), holder["run"].budget_snapshot()["wall_clock_s"]["used"]))
        ctx.check_cancelled()
        return thing(ctx)

    run = make_run(tmp_path, spec=ToolSpec(name="make", level="L2", emits="thing"),
                   fn=work, budget=Budget(limits=BudgetLimits(wall_clock_s=5)),
                   monotonic=lambda: clock.mono, utc=lambda: clock.utc)
    holder["run"] = run
    run.call("make", {})
    assert observed == [(3, 2)]
    assert run.budget.wall_clock_s == 2


def test_keyboard_interrupt_escapes_and_next_owner_reconciles(tmp_path):
    clock = Clock()

    def interrupt(ctx):
        clock.tick(2)
        raise KeyboardInterrupt

    run = make_run(tmp_path, spec=ToolSpec(name="make", level="L2", emits="thing"),
                   fn=interrupt, monotonic=lambda: clock.mono, utc=lambda: clock.utc)
    with pytest.raises(KeyboardInterrupt):
        run.call("make", {})
    assert not any(e["type"] == "tool_failed" for e in run.events.read())
    clock.tick(3)
    reopened = Run("r", run.run_dir, run.registry, monotonic=lambda: clock.mono,
                   utc=lambda: clock.utc)
    assert not any(e["type"] == "tool_interrupted" for e in reopened.events.read())
    reopened.decide("rule", "fixture", "reconcile")
    assert any(e["type"] == "tool_interrupted" and e["reason"] == "owner_lost"
               for e in reopened.events.read())
    assert reopened.budget.wall_clock_s == 5


def test_dry_run_is_plan_only_and_separate_from_real_cache(tmp_path):
    count = []
    spec = ToolSpec(name="make", level="L3", emits="energy_table", cost_class="expensive")
    reg = registry(spec)
    reg.impls["make"] = lambda ctx: count.append(1)
    run = Run("r", tmp_path / "r", reg, dry_run=True)
    plan = run.call("make", {})
    assert plan.kind == "planned_call"
    assert run.store.load(plan.handle)["plan_only"] is True
    assert count == [] and run.budget.expensive_calls == 0
    assert run.call("make", {}).handle == plan.handle
    assert any(e["type"] == "cache_hit" and e["output"]["kind"] == "planned_call" for e in run.events.read())
    with pytest.raises(ValueError, match="incompatible"):
        Run("r", run.run_dir, reg, dry_run=False)


def test_unavailable_energy_protocol_is_rejected_before_approval_or_charge(tmp_path):
    run = Run("r", tmp_path / "r", build_registry())
    prepared = run.store.put("prepared_structure", "structure@1", b"fixture", fmt="pdb")
    with pytest.raises(ToolFailure) as exc:
        run.call("relax_structure", {"structure": prepared.handle})
    assert exc.value.cls == FailureClass.precondition
    assert "M4 energy backend" in exc.value.message
    assert run.budget.expensive_calls == 0
    assert not any(e["type"] in ("approval_requested", "tool_called")
                   for e in run.events.read())


def test_cache_verifies_payload_and_defaults_key(tmp_path):
    run = make_run(tmp_path)
    out = run.call("make", {})
    assert run.call("make", {"value": 1}).handle == out.handle
    payload = run.run_dir / "objects" / f"{out.sha}.json"
    payload.write_text('{"tampered":true}')
    with pytest.raises(ValueError, match="corrupt"):
        run.call("make", {})


def test_legacy_m1_start_uses_explicit_default_limits_and_ignores_cached_duration(tmp_path):
    directory = tmp_path / "r"
    log = EventLog(directory / "events.jsonl")
    log.append("run_started", run_id="r", dry_run=False, seed=0)
    log.append("tool_succeeded", call_id="old", tool="make", key="old",
               duration_s=2.0, cached=False)
    log.append("tool_succeeded", call_id="old", tool="make", key="old",
               duration_s=900.0, cached=True)
    run = Run("r", directory, registry(), dry_run=False, seed=0)
    assert run.budget.wall_clock_s == 2
    assert run.budget.limits.expensive_calls == 8
    assert run.guard.no_progress_steps == 4


def test_legacy_and_new_attempt_time_reopens_without_duplicate_charge(tmp_path):
    directory = tmp_path / "r"
    log = EventLog(directory / "events.jsonl")
    log.append("run_started", run_id="r", dry_run=False, seed=0)
    log.append("tool_succeeded", call_id="old", tool="make", key="old",
               duration_s=2.0, cached=False)
    log.append("tool_succeeded", call_id="old", tool="make", key="old",
               duration_s=100.0, cached=True)
    clock = Clock()
    reg = registry(ToolSpec(name="make", level="L2", emits="thing"),
                   ToolSpec(name="fail", level="L2", emits="thing"))

    def success(ctx):
        clock.tick(3)
        return thing(ctx)

    def failure(ctx):
        clock.tick(1)
        raise ToolFailure(FailureClass.fatal, "fixture")

    reg.impls.update(make=success, fail=failure)
    run = Run("r", directory, reg, monotonic=lambda: clock.mono, utc=lambda: clock.utc)
    assert run.budget.wall_clock_s == 2
    run.call("make", {})
    with pytest.raises(ToolFailure):
        run.call("fail", {})
    assert run.budget.wall_clock_s == 6
    for _ in range(3):
        reopened = Run("r", directory, reg, monotonic=lambda: clock.mono,
                       utc=lambda: clock.utc)
        assert reopened.budget.wall_clock_s == 6
    assert sum(e["seconds"] for e in log.read() if e["type"] == "wall_charged"
               and e.get("reason") == "attempt") == 4


def _killed_during_backoff(directory, ready):
    reg = registry(ToolSpec(name="make", level="L2", emits="thing"))

    def fail(ctx):
        raise ToolFailure(FailureClass.transient, "fixture")

    def wait_for_kill(seconds):
        ready.set()
        time.sleep(30)

    reg.impls["make"] = fail
    Run("r", directory, reg, budget=Budget(limits=BudgetLimits(wall_clock_s=5)),
        sleep=wait_for_kill).call("make", {})


def test_killed_backoff_charges_bounded_interval_once_and_blocks_execution(tmp_path):
    directory = tmp_path / "r"
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    worker = ctx.Process(target=_killed_during_backoff, args=(directory, ready))
    worker.start()
    try:
        assert ready.wait(8)
        worker.kill()
        worker.join(8)
        assert worker.exitcode is not None and worker.exitcode != 0
        reg = registry(ToolSpec(name="make", level="L2", emits="thing"))
        calls = []
        reg.impls["make"] = lambda tool_ctx: calls.append(tool_ctx.call_id) or thing(tool_ctx)
        recovered = Run("r", directory, reg, utc=lambda: time.time() + 100)
        for _ in range(2):
            with pytest.raises(ApprovalRequired) as exc:
                recovered.call("make", {})
            assert exc.value.gate == "budget"
        records = list(recovered.events.read())
        starts = [e for e in records if e["type"] == "backoff_started"]
        assert len(starts) == 1 and starts[0]["retry_index"] == 1
        assert starts[0]["remaining_wall_s"] <= 5
        assert starts[0]["deadline_utc"] == pytest.approx(
            starts[0]["ts"] + starts[0]["remaining_wall_s"])
        assert len([e for e in records if e["type"] == "backoff_interrupted"]) == 1
        assert any(e["type"] == "checkpoint" and e.get("axis") == "wall_clock_s"
                   for e in records)
        charges = [e for e in records if e["type"] == "wall_charged"
                   and e.get("reason") == "orphan_backoff_recovery"]
        assert len(charges) == 1
        assert charges[0]["seconds"] > 4.9
        assert recovered.budget.wall_clock_s >= 5
        assert calls == []
        assert len([e for e in records if e["type"] == "tool_called"]) == 1
    finally:
        if worker.is_alive():
            worker.kill()
            worker.join(8)


def test_backoff_recovery_clock_anomaly_and_clean_idle(tmp_path):
    clock = Clock()
    run = make_run(tmp_path, spec=ToolSpec(name="make", level="L2", emits="thing"),
                   monotonic=lambda: clock.mono, utc=lambda: clock.utc)
    run.events.append("backoff_started", backoff_id="backoff_fixture", root_call_id="root",
                      after_call_id="failed", retry_index=1, delay_s=2,
                      remaining_wall_s=7, ts=clock.utc + 10)
    run.call("make", {})
    records = list(run.events.read())
    assert len([e for e in records if e["type"] == "clock_anomaly"
                and e.get("backoff_id") == "backoff_fixture"]) == 1
    assert len([e for e in records if e["type"] == "backoff_interrupted"]) == 1
    assert [e["seconds"] for e in records if e["type"] == "wall_charged"
            and e.get("reason") == "orphan_backoff_recovery"] == [0]
    clock.tick(100)
    reopened = Run("r", run.run_dir, run.registry, monotonic=lambda: clock.mono,
                   utc=lambda: clock.utc)
    assert reopened.budget.wall_clock_s == 0
    assert len([e for e in reopened.events.read() if e["type"] == "backoff_interrupted"]) == 1


def test_repaired_loader_binds_source_bytes_to_key_and_execution(tmp_path):
    spec = ToolSpec(name="load_structure", level="L2", emits="structure",
                    params={"source": {"type": "str", "required": True}})
    observations = []

    def loader(ctx, source):
        observations.append((ctx.source_bytes, ctx.source_format))
        path = tmp_path / "source.pdb"
        if source == str(path):
            path.write_bytes(b"B")
        return ctx.store.put("structure", "structure@1", ctx.source_bytes, fmt="pdb")

    run = make_run(tmp_path / "loader", spec=spec, fn=loader)
    for source in (tmp_path / "missing.pdb", tmp_path / "bad.txt"):
        with pytest.raises(ToolFailure) as exc:
            run.call("load_structure", {"source": str(source)})
        assert exc.value.cls == FailureClass.input_invalid
    with pytest.raises(ToolFailure) as exc:
        run.call("load_structure", {"source": str(tmp_path / "bad.txt")},
                 source_format="pdb")
    assert exc.value.cls == FailureClass.input_invalid
    rejected = [e for e in run.events.read() if e["type"] == "proposal_rejected"]
    path = tmp_path / "source.pdb"
    path.write_bytes(b"A")
    repaired = run.repair_call(rejected[0]["proposal_id"], {"source": str(path)})
    assert run.store.load(repaired.handle) == b"A"
    assert observations == [(b"A", "pdb")]
    path.write_bytes(b"A")
    assert run.call("load_structure", {"source": str(path)}).handle == repaired.handle
    assert observations == [(b"A", "pdb")]
    assert any(e["type"] == "cache_hit" for e in run.events.read())
    http = run.call("load_structure", {"source": "upload://r/fixture.pdb"},
                    source_bytes=b"verified", source_format="pdb")
    assert run.store.load(http.handle) == b"verified"
    assert observations[-1] == (b"verified", "pdb")


def test_cancel_before_retry_is_terminal_after_reopen(tmp_path):
    count = []
    holder = {}

    def transient(ctx):
        count.append(1)
        raise ToolFailure(FailureClass.transient, "retry")

    def sleeper(seconds):
        holder["run"].cancel()

    run = make_run(tmp_path, spec=ToolSpec(name="make", level="L2", emits="thing"),
                   fn=transient, sleep=sleeper)
    holder["run"] = run
    with pytest.raises(RunCancelled):
        run.call("make", {})
    assert len(count) == 1
    reopened = Run("r", run.run_dir, run.registry)
    with pytest.raises(RunCancelled):
        reopened.call("make", {})
    assert len(count) == 1


def _held_owner(path, ready, release):
    run = make_run(path)
    with run._owner():
        ready.set()
        release.wait(5)


def _last_unit_worker(path, start, output):
    spec = ToolSpec(name="make", level="L3", emits="thing", cost_class="expensive",
                    params={"value": {"type": "int", "required": True}})
    reg = registry(spec)
    reg.impls["make"] = thing
    run = Run("r", path / "r", reg)
    start.wait(5)
    try:
        run.call("make", {"value": os.getpid()})
        output.put("done")
    except (ToolFailure, ApprovalRequired) as exc:
        output.put("busy" if isinstance(exc, ToolFailure) else "budget")


def _same_key_worker(path, start, output):
    spec = ToolSpec(name="make", level="L2", emits="thing")
    reg = registry(spec)

    def slow(ctx):
        time.sleep(0.15)
        return thing(ctx)

    reg.impls["make"] = slow
    run = Run("r", path / "r", reg)
    start.wait(5)
    for _ in range(20):
        try:
            output.put(run.call("make", {}).handle)
            return
        except ToolFailure as exc:
            if not exc.detail.get("busy"):
                raise
            time.sleep(0.02)
    output.put("could_not_acquire")


def test_cross_process_owner_and_last_unit(tmp_path):
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    holder = context.Process(target=_held_owner, args=(tmp_path / "held", ready, release))
    holder.start()
    assert ready.wait(5)
    run = make_run(tmp_path / "held")
    with pytest.raises(ToolFailure) as exc:
        run.call("make", {})
    assert exc.value.detail["busy"] is True
    assert not any(e["type"] == "tool_interrupted" for e in run.events.read())
    release.set()
    holder.join(5)
    assert holder.exitcode == 0
    spec = ToolSpec(name="make", level="L3", emits="thing", cost_class="expensive",
                    params={"value": {"type": "int", "required": True}})
    reg = registry(spec)
    reg.impls["make"] = thing
    owner = Run("r", tmp_path / "unit" / "r", reg,
                budget=Budget(limits=BudgetLimits(expensive_calls=1)))
    owner.approve("expensive_first_call")
    start, output = context.Event(), context.Queue()
    workers = [context.Process(target=_last_unit_worker, args=(tmp_path / "unit", start, output))
               for _ in range(2)]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(5)
        assert worker.exitcode == 0
    assert sorted([output.get(timeout=2) for _ in workers]) in (["budget", "done"], ["busy", "done"])
    events = list(owner.events.read())
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert sum(e["type"] == "budget_reserved" for e in events) == 1
    assert sum(e["type"] == "tool_called" for e in events) == 1
    shared = tmp_path / "same_key"
    make_run(shared, spec=ToolSpec(name="make", level="L2", emits="thing"))
    start, output = context.Event(), context.Queue()
    workers = [context.Process(target=_same_key_worker, args=(shared, start, output))
               for _ in range(2)]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(5)
        assert worker.exitcode == 0
    results = [output.get(timeout=2) for _ in workers]
    assert results[0] == results[1] and results[0] != "could_not_acquire"
    events = list(Run("r", shared / "r", registry(ToolSpec(name="make", level="L2", emits="thing"))).events.read())
    assert sum(e["type"] == "tool_called" for e in events) == 1
    assert sum(e["type"] == "cache_hit" for e in events) == 1
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
