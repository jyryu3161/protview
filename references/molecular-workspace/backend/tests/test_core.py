"""M0 invariants: handles, contracts, pipeline baseline, replay/resume."""
import pytest

from mw.core.errors import FailureClass, ToolFailure
from mw.core.handles import ObjectStore
from mw.runtime.orchestrator import replay
from mw.workspace import build_registry


def test_same_content_same_handle(tmp_path):
    s = ObjectStore(tmp_path, "r1")
    a = s.put("thing", "thing@1", [{"a": 1, "b": 2}])
    b = s.put("thing", "thing@1", [{"b": 2, "a": 1}])       # key order must not matter
    c = s.put("thing", "thing@1", [{"a": 1, "b": 3}])
    assert a.handle == b.handle != c.handle
    assert a.handle.startswith("obj://r1/thing/")


def test_materialize_projection_and_parquet(tmp_path):
    s = ObjectStore(tmp_path, "r1")
    rows = [{"i": i, "v": i * 0.5, "note": "x"} for i in range(20)]
    h = s.put("table", "table@1", rows, fmt="parquet")
    assert s.materialize(h.handle, ["i"], offset=3, limit=2) == [{"i": 3}, {"i": 4}]
    assert len(h.preview) == 5


def test_contract_rejects_before_execution(run, pdb_path):
    s = run.call("load_structure", {"source": pdb_path})
    with pytest.raises(ToolFailure) as e:
        run.call("relax_structure", {"structure": s.handle})       # needs prepared_structure
    assert e.value.cls == FailureClass.precondition
    assert e.value.fix and e.value.fix.tool == "prepare_structure"
    with pytest.raises(ToolFailure) as e:
        run.call("prepare_structure", {"structure": s.handle, "waters": "some"})
    assert e.value.cls == FailureClass.input_invalid
    assert not any(ev["type"] == "tool_called" and ev["tool"] == "relax_structure" for ev in run.events.read())


def test_pipeline_baseline_and_icode(run, pdb_path):
    s = run.call("load_structure", {"source": pdb_path})
    p = run.call("prepare_structure", {"structure": s.handle})
    i = run.call("compute_interactions", {"structure": p.handle})
    rows = run.store.materialize(i.handle)
    types = {r["type"] for r in rows}
    assert {"salt_bridge", "hydrophobic", "metal"} <= types
    asp = next(r for r in rows if r["residue"]["resname"] == "ASP")
    assert asp["residue"]["seq_auth"] == 100 and asp["residue"]["icode"] == "A"   # insertion code kept
    assert "coords" not in str(rows)
    m = run.store.meta(p.summary["manifest"])
    assert m["kind"] == "preparation_manifest"


def test_empty_result_is_not_a_failure(run, pdb_path):
    s = run.call("load_structure", {"source": pdb_path})
    p = run.call("prepare_structure", {"structure": s.handle})
    i = run.call("compute_interactions", {"structure": p.handle, "cutoff_A": 2.5, "types": ["hydrophobic"]})
    assert i.null_result is True
    last = [e for e in run.events.read() if e["type"] == "tool_succeeded"][-1]
    assert last["null_result"] is True


def _full_dry_run(run, pdb_path):
    s = run.call("load_structure", {"source": pdb_path})
    p = run.call("prepare_structure", {"structure": s.handle})
    r = run.call("relax_structure", {"structure": p.handle})             # dry_run stub
    m = run.call("define_mutations", {"structure": r.handle,
                                      "mutations": [{"chain_auth": "A", "seq_auth": 101, "from": "L", "to": "A"}]})
    e = run.call("estimate_stability", {"structure": r.handle, "mutations": m.handle})
    run.call("compile_state", {"inputs": [p.handle, e.handle]})
    return e


def test_resume_skips_done_steps(run, pdb_path):
    _full_dry_run(run, pdb_path)
    n_called = sum(e["type"] == "tool_called" for e in run.events.read())
    _full_dry_run(run, pdb_path)                                          # same calls again
    assert sum(e["type"] == "tool_called" for e in run.events.read()) == n_called


def test_replay_from_events_only(run, pdb_path, tmp_path):
    e = _full_dry_run(run, pdb_path)
    assert run.store.load(e.handle)[0]["rounds_REU"]
    original = run.store.handles()
    replayed = replay(run.run_dir / "events.jsonl", tmp_path / "replay" / run.run_id, build_registry(), run.run_id)
    assert replayed == original
