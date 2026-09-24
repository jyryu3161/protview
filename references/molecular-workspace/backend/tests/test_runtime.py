"""M2 invariants: retry by class, loop guards, approval gates, budget."""
import pytest

from mw.core.errors import FailureClass, ToolFailure
from mw.runtime.guards import LoopGuard, LoopStop
from mw.runtime.orchestrator import ApprovalRequired, Run


def _thing(ctx, **kw):
    return ctx.store.put("thing", "thing@1", {"kw": kw, "call": ctx.call_id if kw.get("unique") else None})


def test_transient_retries_then_succeeds(tmp_path, fake_registry):
    n = {"i": 0}

    def flaky(ctx):
        n["i"] += 1
        if n["i"] < 3:
            raise ToolFailure(FailureClass.transient, "503")
        return ctx.store.put("thing", "thing@1", {"ok": True})
    fake_registry.impls["flaky"] = flaky
    slept = []
    run = Run("r", tmp_path, fake_registry, sleep=slept.append)
    run.call("flaky", {})
    assert slept == [2, 4]
    assert sum(e["type"] == "tool_failed" for e in run.events.read()) == 2


def test_non_transient_is_not_retried(tmp_path, fake_registry):
    def bad(ctx):
        raise ToolFailure(FailureClass.resource_exceeded, "timeout")
    fake_registry.impls["bad"] = bad
    run = Run("r", tmp_path, fake_registry, sleep=lambda s: None)
    with pytest.raises(ToolFailure):
        run.call("bad", {})
    assert sum(e["type"] == "tool_called" for e in run.events.read()) == 1


def test_repeated_call_hash_stops_the_branch(tmp_path, fake_registry):
    def bad(ctx):
        raise ToolFailure(FailureClass.input_invalid, "nope")
    fake_registry.impls["bad"] = bad
    run = Run("r", tmp_path, fake_registry)
    for _ in range(2):
        with pytest.raises(ToolFailure):
            run.call("bad", {})
    with pytest.raises(LoopStop) as e:
        run.call("bad", {})
    assert e.value.reason == "repeated_call_hash"


def test_oscillation_and_no_progress():
    g = LoopGuard(oscillation_window=6)
    with pytest.raises(LoopStop) as e:
        for i in range(6):
            g.before_call(f"h{i}", "A" if i % 2 == 0 else "B")
    assert e.value.reason == "oscillation"
    g = LoopGuard(no_progress_steps=3)
    g.after_call({"obj://x"})
    with pytest.raises(LoopStop):
        for _ in range(3):
            g.after_call({"obj://x"})


def test_expensive_first_call_needs_approval_then_budget(tmp_path, fake_registry):
    fake_registry.impls["costly"] = lambda ctx, **kw: ctx.store.put("thing", "thing@1", {"n": ctx.call_id})
    fake_registry.specs["costly"].params = {"n": {"type": "int"}}
    run = Run("r", tmp_path, fake_registry)
    run.budget.limits.expensive_calls = 2
    with pytest.raises(ApprovalRequired) as a:
        run.call("costly", {"n": 1})
    assert a.value.gate == "expensive_first_call"
    run.approve("expensive_first_call")
    run.call("costly", {"n": 1})
    run.call("costly", {"n": 2})
    with pytest.raises(ApprovalRequired) as a:
        run.call("costly", {"n": 3})
    assert a.value.gate == "budget"
    assert any(e["type"] == "checkpoint" for e in run.events.read())


def test_dry_run_never_asks_and_never_charges(tmp_path, fake_registry):
    fake_registry.impls["costly"] = lambda ctx: ctx.store.put("thing", "thing@1", {"real": True})
    fake_registry.stubs["costly"] = lambda ctx: ctx.store.put("thing", "thing@1", {"stub": True})
    run = Run("r", tmp_path, fake_registry, dry_run=True)
    h = run.call("costly", {})
    assert run.store.load(h.handle) == {"stub": True}
    assert run.budget.expensive_calls == 0
