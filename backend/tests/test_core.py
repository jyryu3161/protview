"""M0 invariants: handles, contracts, pipeline baseline, replay/resume."""
import multiprocessing
import threading

import pytest

from mw.core.errors import FailureClass, ToolFailure
from mw.core.handles import ObjectStore
from mw.runtime.orchestrator import replay
from mw.workspace import build_registry, new_run


def _read_during_rebuild(run_dir, handle, result):
    try:
        result.put(ObjectStore(run_dir, "r1").load(handle))
    except Exception as exc:  # noqa: BLE001 - return any child failure to the parent test
        result.put(type(exc).__name__)


def test_rebuild_publishes_index_atomically_to_other_connections_and_processes(tmp_path):
    store = ObjectStore(tmp_path, "r1")
    output = store.put("thing", "thing@1", {"fixture": "durable"})
    observer = ObjectStore(tmp_path, "r1")
    entered, release = threading.Event(), threading.Event()
    errors = []
    original_install = store._install

    def delayed_install(*args, **kwargs):
        entered.set()
        if not release.wait(10):
            raise TimeoutError("rebuild barrier expired")
        return original_install(*args, **kwargs)

    store._install = delayed_install

    def rebuild():
        try:
            store.rebuild_from_events()
        except Exception as exc:  # noqa: BLE001 - propagate thread failure to the parent test
            errors.append(exc)

    worker = threading.Thread(target=rebuild)
    worker.start()
    try:
        assert entered.wait(5)
        assert observer.load(output.handle) == {"fixture": "durable"}
        ctx = multiprocessing.get_context("spawn")
        result = ctx.Queue()
        reader = ctx.Process(target=_read_during_rebuild, args=(tmp_path, output.handle, result))
        reader.start()
        assert result.get(timeout=8) == {"fixture": "durable"}
        reader.join(5)
        assert reader.exitcode == 0
    finally:
        release.set()
        worker.join(10)
    assert not errors
    assert observer.load(output.handle) == {"fixture": "durable"}


def test_corrupt_rebuild_keeps_previously_published_index(tmp_path):
    store = ObjectStore(tmp_path, "r1")
    output = store.put("thing", "thing@1", {"fixture": "durable"})
    observer = ObjectStore(tmp_path, "r1")
    store.events.append("object_created", handle="obj://r1/thing/" + "0" * 64,
                        kind="thing", schema="thing@1", fmt="json", payload_b64="!!!")
    with pytest.raises(ValueError, match="corrupt object event payload"):
        store.rebuild_from_events()
    assert observer.load(output.handle) == {"fixture": "durable"}
    assert store.load(output.handle) == {"fixture": "durable"}


def test_same_content_same_handle(tmp_path):
    s = ObjectStore(tmp_path, "r1")
    a = s.put("thing", "thing@1", [{"a": 1, "b": 2}])
    b = s.put("thing", "thing@1", [{"b": 2, "a": 1}])       # key order must not matter
    c = s.put("thing", "thing@1", [{"a": 1, "b": 3}])
    assert a.handle == b.handle != c.handle
    assert a.handle.startswith("obj://r1/thing/")
    assert len(a.sha) == 64


def test_same_content_conflicting_metadata_is_rejected(tmp_path):
    s = ObjectStore(tmp_path, "r1")
    s.put("thing", "thing@1", {"a": 1}, summary={"policy": "keep"})
    with pytest.raises(ValueError, match="conflicting metadata"):
        s.put("thing", "thing@1", {"a": 1}, summary={"policy": "strip"})


def test_object_directory_and_payload_symlinks_cannot_escape(tmp_path):
    run_dir = tmp_path / "run"
    s = ObjectStore(run_dir, "r1")
    h = s.put("thing", "thing@1", {"a": 1})
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"unchanged")
    payload = run_dir / "objects" / f"{h.sha}.json"
    payload.unlink()
    payload.symlink_to(sentinel)
    with pytest.raises(ValueError):
        s.load(h.handle)
    payload.unlink()
    (run_dir / "objects").rename(run_dir / "old_objects")
    (run_dir / "objects").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe object directory"):
        s.put("thing", "thing@1", {"a": 2})
    assert sentinel.read_bytes() == b"unchanged"
    assert {p.name for p in outside.iterdir()} == {"sentinel"}


def test_bounded_json_read_checks_actual_file_before_decoding(tmp_path):
    store = ObjectStore(tmp_path, "r1")
    saved = store.put("thing", "thing@1", {"fixture": "bounded"})
    raw_path = tmp_path / "objects" / f"{saved.sha}.json"
    original = raw_path.read_bytes()
    assert store.load_bounded_json(saved.handle, len(original)) == {"fixture": "bounded"}
    with pytest.raises(ValueError, match="oversized"):
        store.load_bounded_json(saved.handle, len(original) - 1)
    # The SQLite row still advertises the original small size. A replaced
    # on-disk object must be rejected before a potentially large read/parse.
    raw_path.write_bytes(b" " * 100_000)
    assert store.meta(saved.handle)["size"] == len(original)
    with pytest.raises(ValueError, match="oversized"):
        store.load_bounded_json(saved.handle, 1024)
    raw_path.write_bytes(original[:-1] + b" ")
    with pytest.raises(ValueError, match="hash"):
        store.load_bounded_json(saved.handle, 1024)
    raw_path.unlink()
    raw_path.symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="unsafe object path"):
        store.load_bounded_json(saved.handle, 1024)


def test_bounded_raw_read_rejects_replaced_oversized_import(tmp_path):
    store = ObjectStore(tmp_path, "r1")
    saved = store.put("chemical_raw_input", "chemical_raw_input@1", b"fixture", fmt="raw")
    assert store.load_bounded_bytes(saved.handle, 7) == b"fixture"
    raw_path = tmp_path / "objects" / f"{saved.sha}.raw"
    raw_path.write_bytes(b"x" * 10_000)
    with pytest.raises(ValueError, match="oversized"):
        store.load_bounded_bytes(saved.handle, 1024)


def test_fresh_run_reopen_and_identical_put_reject_replaced_large_blob_before_read(tmp_path):
    run = new_run(tmp_path, run_id="run_replaced", dry_run=False)
    saved = run.store.put("chemical_structure", "chemical_structure@1", {"fixture": "small"})
    physical = run.run_dir / "objects" / f"{saved.sha}.json"
    original = physical.read_bytes()
    physical.write_bytes(b" " * 2_000_000)
    with pytest.raises(ValueError, match="payload size"):
        run.store.put("chemical_structure", "chemical_structure@1", {"fixture": "small"})
    with pytest.raises(ValueError, match="payload size"):
        new_run(tmp_path, run_id="run_replaced", dry_run=False)
    physical.write_bytes(original)
    reopened = new_run(tmp_path, run_id="run_replaced", dry_run=False)
    assert reopened.store.load_bounded_json(saved.handle, 1024) == {"fixture": "small"}


def test_materialize_projection_and_parquet(tmp_path):
    s = ObjectStore(tmp_path, "r1")
    rows = [{"i": i, "v": i * 0.5, "note": "x"} for i in range(20)]
    h = s.put("table", "table@1", rows, fmt="parquet")
    assert s.materialize(h.handle, ["i"], offset=3, limit=2) == [{"i": 3}, {"i": 4}]
    assert len(h.preview) == 5


def test_parquet_sparse_rows_normalize_without_losing_columns(tmp_path):
    s = ObjectStore(tmp_path, "r1")
    h = s.put("table", "table@1", [{"a": 1}, {"b": 2}], fmt="parquet")
    assert s.load(h.handle) == [{"a": 1, "b": None}, {"a": None, "b": 2}]
    assert s.rebuild_from_events() == {h.handle}
    assert s.load(h.handle) == [{"a": 1, "b": None}, {"a": None, "b": 2}]


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
    assert "polar_contact" in types
    assert "salt_bridge" not in types and "hbond" not in types
    asp = next(r for r in rows if r["residue"]["resname"] == "ASP")
    assert asp["residue"]["seq_auth"] == 100 and asp["residue"]["icode"] == "A"   # insertion code kept
    assert "coords" not in str(rows)
    m = run.store.meta(p.summary["manifest"])
    assert m["kind"] == "preparation_manifest"


def test_empty_result_is_not_a_failure(run, pdb_path):
    s = run.call("load_structure", {"source": pdb_path})
    p = run.call("prepare_structure", {"structure": s.handle})
    i = run.call("compute_interactions", {"structure": p.handle, "cutoff_A": 2.5,
                                          "types": ["hydrophobic_contact"]})
    assert i.null_result is True
    last = [e for e in run.events.read() if e["type"] == "tool_succeeded"][-1]
    assert last["null_result"] is True


def _full_dry_run(run, pdb_path):
    s = run.call("load_structure", {"source": pdb_path})
    p = run.call("prepare_structure", {"structure": s.handle})
    plan = run.call("relax_structure", {"structure": p.handle})
    assert plan.kind == "planned_call"
    with pytest.raises(ToolFailure) as exc:
        run.call("define_mutations", {"structure": plan.handle,
                                      "mutations": [{"chain_auth": "A", "seq_auth": 101, "to": "A"}]})
    assert exc.value.cls == FailureClass.precondition
    mutations = run.call("define_mutations", {"structure": p.handle,
                                              "mutations": [{"chain_auth": "A", "seq_auth": 101, "to": "A"}]})
    with pytest.raises(ToolFailure) as exc:
        run.call("estimate_stability", {"structure": plan.handle, "mutations": mutations.handle})
    assert exc.value.cls == FailureClass.precondition
    return plan


def test_resume_skips_done_steps(run, pdb_path):
    _full_dry_run(run, pdb_path)
    n_called = sum(e["type"] == "tool_called" for e in run.events.read())
    _full_dry_run(run, pdb_path)                                          # same calls again
    assert sum(e["type"] == "tool_called" for e in run.events.read()) == n_called


def test_replay_from_events_only(run, pdb_path, tmp_path):
    e = _full_dry_run(run, pdb_path)
    assert run.store.load(e.handle)["plan_only"] is True
    assert "REU" not in str(run.store.load(e.handle))
    original = run.store.handles()
    replayed = replay(run.run_dir / "events.jsonl", tmp_path / "replay" / run.run_id, build_registry(), run.run_id)
    assert replayed == original
