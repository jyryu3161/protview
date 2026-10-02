"""M19 T4: the qvina batch docking job lane (registration, timeout bound, N-unit reservation, admission budget, staging,
per-row publication + summary in every end state, reuse, duplicates, recovery, events-only reopen, dry-run).

Jobs run the real batch worker (``.deps/docking/venv-locked`` + ``.deps/qvina/env/bin/qvina2``) through ``JobQueue``
and the guardian. They FAIL, never skip, when an environment is absent. The server test process never imports RDKit,
Meeko or MDAnalysis. Inputs: the public prepared docking example receptor (``fixtures/chemical``, not experimental
validation), the public-derived parent SDF and a candidate set made here by real M17 jobs (same ids as the committed
``m17-enumerate-result-record0-nmethyl.json``). Engine values are only checked for consistency with the stored
per-row results (the numeric oracle is test_docking_worker.py). Faults (cancel, kill, parent death, a short job
deadline) are applied through internal test hooks or process signals, never through request fields. Rows use small
boxes and exhaustiveness 1 for time unless a test needs a slow row.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest
from fastapi.testclient import TestClient
from ligand_job_fixture import import_file, new_ligand_run, run_job

from mw import docking_batch_inputs as BI
from mw import docking_batch_jobs as BJ
from mw import docking_bundle, docking_reads
from mw import docking_constants as C
from mw.api import app as api_module
from mw.core.errors import ToolFailure
from mw.docking_reports import build_docking_report, saved_docking_report
from mw.jobs import guardian as guardian_module
from mw.jobs import process_identity
from mw.jobs.queue import GO_WAIT_GRACE_S, MAX_GO_WAIT_S, JobQueue, _guardian_argv
from mw.runtime.guards import BudgetLimits
from mw.runtime.orchestrator import ApprovalRequired, Run
from mw.tools.energetic import JOB_ONLY_TOOLS, JOB_PROTOCOLS

MW = Path(__file__).resolve().parents[1] / "mw"
ROOT = MW.parents[1]
CHEM = Path(__file__).parent / "fixtures/chemical"
FIX = Path(__file__).parent / "fixtures/docking"
EXPECTED = json.loads((FIX / "expected.json").read_text())
ENUM = json.loads((FIX / "m17-enumerate-result-record0-nmethyl.json").read_text())
REC = (CHEM / "prolif-vina-rec.pdb").read_bytes()
PARENT = (FIX / "public-derived-parent-record0.sdf").read_bytes()
BLOCKS = (FIX / "synthetic-docking-blocks.smi").read_bytes()
IDS = [row["id"] for row in ENUM["candidates"]]
CENTER = EXPECTED["public_example_box"]["center_A"]
SMALL_BOX = {"source": "manual", "center_A": CENTER, "size_A": [12.0, 12.0, 12.0]}
SLOW_BOX = {"source": "manual", "center_A": CENTER, "size_A": [20.0, 20.0, 20.0]}
FAST = {"seed": 1, "exhaustiveness": 1, "num_modes": 2}
SLOW = {"seed": 3, "exhaustiveness": 8, "num_modes": 9}
ACK = {key: True for key in C.ACKNOWLEDGEMENT_KEYS}
RID = "run_m19_batch"
PROTOCOL = "qvina_batch_dock_v1"
FORBIDDEN_MODULES = ("rdkit", "meeko", "MDAnalysis")


class _Forbidden(AssertionError):
    pass


# ----------------------------------------------------------------- world (real M17 jobs once, copied per test)
@pytest.fixture(scope="module")
def base(tmp_path_factory):
    root = tmp_path_factory.mktemp("m19_base")
    run = new_ligand_run(root, RID)
    receptor = import_file(run, "receptor", "rec.pdb", REC)
    parent = import_file(run, "ligand_sdf", "parent.sdf", PARENT)
    blocks = import_file(run, "building_blocks_smiles", "blocks.smi", BLOCKS)
    inspected = run_job(run, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [blocks]})
    assert inspected["status"] == "done", inspected
    enumerated = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": inspected["output_handles"][0],
                                                     "site_atoms": [22], "use_fixed": True})
    assert enumerated["status"] == "done", enumerated
    candidate_set = enumerated["output_handles"][0]
    assert [row["id"] for row in run.store.load(candidate_set)["candidates"]] == IDS
    return {"root": root, "receptor": receptor, "parent": parent, "candidate_set": candidate_set}


def _world(base: dict, tmp_path: Path, name: str = "runs") -> tuple[Run, Path]:
    """A fresh runs root holding only the base run's events (events-only reopen; same handles)."""
    root = tmp_path / name
    (root / RID).mkdir(parents=True)
    shutil.copyfile(base["root"] / RID / "events.jsonl", root / RID / "events.jsonl")
    run = new_ligand_run(root, RID)
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
    return run, root


def _raise(run: Run, calls: int = 40, wall: float = 7200) -> None:
    run.update_limits(BudgetLimits(expensive_calls=calls, wall_clock_s=wall), by="test")


def _args(base: dict, ids: list[str], *, mode: str = "free", include_parent: bool = False,
          box: dict | None = None, params: dict | None = None) -> dict:
    return {"receptor_handle": base["receptor"], "receptor_model_number": 1,
            "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
            "candidate_set_handle": base["candidate_set"], "parent_sdf_handle": base["parent"],
            "candidate_ids": ids, "include_parent": include_parent, "mode": mode, "box": box or SMALL_BOX,
            "parameters": params or FAST, "acknowledgement": ACK}


def _start(queue: JobQueue, job_id: str) -> dict:
    try:
        return queue.start(job_id)
    except ApprovalRequired:
        queue.run.approve("expensive_first_call", by="test")
        return queue.start(job_id)


def _batch(run: Run, args: dict, timeout_s: float = 1200) -> dict:
    queue = JobQueue(run)
    job = queue.submit(PROTOCOL, args, timeout_s=timeout_s)
    return job if job["status"] != "queued" else _start(queue, job["job_id"])


def _events(run: Run) -> list[dict]:
    return list(run.events.read())


def _of(run: Run, job_id: str, kind: str) -> list[dict]:
    return [e for e in _events(run) if e["type"] == kind and e.get("job_id") == job_id]


def _reserved(run: Run, job_id: str) -> list[int]:
    attempts = {e["attempt_id"] for e in _of(run, job_id, "job_dispatch_intent")}
    return [e["expensive_calls"] for e in _events(run) if e["type"] == "budget_reserved" and
            e.get("attempt_id") in attempts]


def _summary(run: Run, job: dict) -> tuple[str, dict]:
    published = _of(run, job["job_id"], "docking_batch_published")
    assert len(published) == 1, published
    handle = published[0]["summary_handle"]
    assert JobQueue(run).get(job["job_id"])["batch_summary_handle"] == handle
    return handle, BJ.validated_summary(run, handle)


def _states(content: dict) -> list[list]:
    return [[row["state"], row["reason_code"]] for row in content["rows"]]


def _computed(content: dict) -> list[str]:
    return [row["state"] for row in content["rows"]]


def _attempt_dir(run: Run, job: dict) -> Path:
    return run.run_dir / "jobs" / job["job_id"] / job["attempt_id"]


def _no_strays(run: Run) -> None:
    """No worker of this run and no qvina2 under its job directories survives the job."""
    for event in _events(run):
        if event["type"] == "job_worker_started" and process_identity.matches(event["pid"], event["start_identity"]):
            assert psutil.Process(event["pid"]).status() == psutil.STATUS_ZOMBIE, "worker survived"
    jobs = str(run.run_dir / "jobs")
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] == "qvina2" and proc.cwd().startswith(jobs):
                raise AssertionError(f"stray qvina2 {proc.pid}")
        except (psutil.Error, OSError):
            continue


def _check_rows_against_results(run: Run, content: dict) -> None:
    for row in content["rows"]:
        if row["state"] in ("scored", "null_result"):
            result = docking_bundle.validated_result(run, row["result_handle"])
            assert row["score_kcal_mol"] == (result["modes"][0]["score_kcal_mol"] if result["modes"] else None)
            assert result["inputs"]["ligand"]["candidate_id"] == row["candidate_id"]
        else:
            assert row["result_handle"] is None and row["score_kcal_mol"] is None


def _when_row_starts(index: int, action) -> object:
    """Wrap _record_control: on STARTED, a thread waits for rows/<index>.started of this attempt, then acts."""
    original = JobQueue._record_control

    def record(self, message, job_id, attempt_id, nonce):
        done = original(self, message, job_id, attempt_id, nonce)
        if message and message.get("kind") == "STARTED":
            marker = self.run.run_dir / "jobs" / job_id / attempt_id / "rows" / f"{index}.started"

            def watch() -> None:
                end = time.monotonic() + 300
                while time.monotonic() < end and not marker.exists():
                    time.sleep(0.02)
                if marker.exists():
                    action(self, job_id, message["pid"])
            threading.Thread(target=watch, daemon=True).start()
        return done

    return record


# ----------------------------------------------------------------- registration, capability, bounds, isolation
def test_registration_capability_and_protocol_timeout_bound(tmp_path, monkeypatch):
    assert JOB_PROTOCOLS[PROTOCOL] == ("qvina_dock_batch", "qvina")
    assert "qvina_dock_batch" in JOB_ONLY_TOOLS and "qvina_dock_batch" not in api_module.SUPPORTED_TOOLS
    spec = api_module.REGISTRY.specs["qvina_dock_batch"]
    assert spec.cost_class == "expensive" and spec.emits == "docking_batch_result"
    assert "qvina_dock_batch" in api_module.REGISTRY.unavailable
    assert guardian_module.DOCKING_BATCH == MW / "jobs/docking_batch_worker.py" == BJ.BATCH_WORKER
    assert guardian_module.DOCKING_BATCH_ADAPTER == PROTOCOL in guardian_module.MONITORED_ADAPTERS
    assert PROTOCOL not in guardian_module.PINNED_PYTHON_ADAPTERS and PROTOCOL in guardian_module.DOCKING_ADAPTERS
    for name in ("docking_batch_jobs.py", "docking_batch_bundle.py", "docking_batch_inputs.py", "jobs/queue.py",
                 "jobs/guardian.py", "api/app.py"):
        tree = ast.parse((MW / name).read_text())
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert not any(m == top or m.startswith(top + ".") for m in imported for top in FORBIDDEN_MODULES), name
    capability = BJ.capability()
    assert capability["available"] is True, capability["reason"]
    assert capability["pins"] == docking_bundle.capability()["pins"]
    assert capability["timeout_s"] == {"max": 7800} and capability["limits"]["max_candidates"] == 50
    root = tmp_path / "runs"
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    methods = client.get("/capabilities").json()["methods"]
    assert methods["ligand_docking_batch"] == capability
    with monkeypatch.context() as patch:   # unavailable: reason only, the M18 set; no pins, no limits
        patch.setattr(docking_bundle, "QVINA", tmp_path / "missing/qvina2")
        down = BJ.capability()
        assert (down["available"], down["reason_code"], down["pins"]) == (False, "engine_missing", None)
        assert "limits" not in down and down["reason"] == docking_bundle.REASONS["engine_missing"]
    with monkeypatch.context() as patch:
        patch.setattr(BJ, "BATCH_WORKER", tmp_path / "missing/docking_batch_worker.py")
        assert BJ.capability()["reason_code"] == "worker_missing"
    # Protocol-only timeout bound: 7800 s for the batch, every other protocol keeps its own (M18: 900 s).
    queue = JobQueue(new_ligand_run(tmp_path / "bounds", "run_bounds"))
    for protocol, timeout in ((PROTOCOL, 7801), ("qvina_dock_v1", 901), ("rdkit_inspect_v1", 121)):
        with pytest.raises(ToolFailure) as refused:
            queue.submit(protocol, {}, timeout_s=timeout)
        assert refused.value.message == "invalid job timeout"
    with pytest.raises(ToolFailure) as admitted:   # 7800 passes the bound; admission then refuses the empty args
        queue.submit(PROTOCOL, {}, timeout_s=7800)
    assert admitted.value.detail["reason_code"] == "invalid_job_arguments"
    rid = client.post("/runs", json={"goal": "M19 bounds", "dry_run": False}).json()["run_id"]
    over = client.post(f"/runs/{rid}/jobs", json={"protocol_id": PROTOCOL, "args": {}, "timeout_s": 7801})
    m18 = client.post(f"/runs/{rid}/jobs", json={"protocol_id": "qvina_dock_v1", "args": {}, "timeout_s": 7800})
    assert over.status_code == 422 and m18.status_code == 422 and m18.json()["message"] == "invalid job timeout"
    # A 2-hour attempt: the guardian GO wait stays capped and valid; process identity records have no age.
    argv = _guardian_argv(3, go_wait_s=min(MAX_GO_WAIT_S, 7800 + GO_WAIT_GRACE_S))
    assert guardian_module.parse_argv(argv[3:]) == (3, None, MAX_GO_WAIT_S)


def test_reserve_attempt_takes_a_unit_count_and_replays_it(tmp_path):
    run = new_ligand_run(tmp_path, "run_units")
    with pytest.raises(ApprovalRequired):   # zero units still needs the run's first expensive approval
        run.reserve_attempt("attempt_zero", "job_zero", "qvina_dock_batch", {}, units=0)
    run.approve("expensive_first_call", by="test")
    first = run.reserve_attempt("attempt_a", "job_a", "qvina_dock_batch", {}, units=3)
    assert first["expensive_calls"] == 3 and run.budget.expensive_calls == 3
    assert run.reserve_attempt("attempt_a", "job_a", "qvina_dock_batch", {}, units=3) == first   # idempotent
    with pytest.raises(ValueError):
        run.reserve_attempt("attempt_a", "job_a", "qvina_dock_batch", {}, units=1)
    zero = run.reserve_attempt("attempt_b", "job_b", "qvina_dock_batch", {}, units=0)
    assert zero["expensive_calls"] == 0 and run.budget.expensive_calls == 3
    default = run.reserve_attempt("attempt_c", "job_c", "qvina_dock_ligand", {})
    assert default["expensive_calls"] == 1 and run.budget.expensive_calls == 4
    with pytest.raises(ApprovalRequired) as short:   # 4 used of 8: five more units exceed the limit
        run.reserve_attempt("attempt_d", "job_d", "qvina_dock_batch", {}, units=5)
    assert short.value.gate == "budget"
    for bad in (-1, 1.0, True):
        with pytest.raises(ValueError):
            run.reserve_attempt("attempt_e", "job_e", "qvina_dock_batch", {}, units=bad)
    run._refresh()   # replay adds each reservation's own unit count
    assert run.budget.expensive_calls == 4
    reopened = new_ligand_run(tmp_path, "run_units")
    reopened._refresh()
    assert reopened.budget.expensive_calls == 4


# ----------------------------------------------------------------- full product path, reuse, N = 0, identity
def test_free_batch_product_path_reuse_n0_duplicates_identity_and_events_only(base, tmp_path, monkeypatch):
    run, root = _world(base, tmp_path)
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    args = _args(base, [IDS[1], IDS[0]], include_parent=True)   # click order; rows follow the set order
    used = run.budget.expensive_calls
    # Shortfall: refused before any job (429 batch_limit_raise_required), nothing charged or recorded.
    run.update_limits(BudgetLimits(expensive_calls=used + 2), by="test")
    before = _events(run)
    refused = client.post(f"/runs/{RID}/jobs", json={"protocol_id": PROTOCOL, "args": args, "timeout_s": 7800})
    assert refused.status_code == 429, refused.text
    detail = refused.json()["detail"]
    assert detail["reason_code"] == "batch_limit_raise_required"
    assert detail["needed"] == {"expensive_calls": 3, "wall_clock_s": 1200}
    assert detail["shortfall"]["expensive_calls"] == 1
    after = _events(run)
    assert not [e for e in after[len(before):] if e["type"] in {"job_submitted", "budget_reserved"}]
    _raise(run)
    submitted = client.post(f"/runs/{RID}/jobs", json={"protocol_id": PROTOCOL, "args": args, "timeout_s": 7800})
    assert submitted.status_code == 200, submitted.text
    job = submitted.json()
    assert job["status"] == "queued" and job["timeout_s"] == 7800 and job["tool_id"] == "qvina_dock_batch"
    done = client.post(f"/runs/{RID}/jobs/{job['job_id']}/start").json()
    assert done["status"] == "done", done
    summary = done["artifacts"]["docking_batch_result"]
    assert done["output_handles"] == [summary]   # the summary only; rows are reached through it
    assert done["batch"] == {"rows": 3, "reused_rows": [], "finished_rows": 3, "summary_handle": summary}
    run = api_module._run(RID)
    record = JobQueue(run).get(job["job_id"])
    assert [row["selected"]["schema"] for row in record["selected"]["rows"]] == ["docking_selection@1"] * 3
    content = BJ.validated_summary(run, summary)
    assert content["status"] == "complete" and content["stop_reason"] is None
    assert [(r["kind"], r["candidate_id"]) for r in content["rows"]] == [("parent", None), ("candidate", IDS[0]),
                                                                         ("candidate", IDS[1])]
    assert set(_computed(content)) <= {"scored", "null_result"}
    assert content["limitations"]["batch_statements"] == ["B1", "B3"]
    _check_rows_against_results(run, content)
    assert _reserved(run, job["job_id"]) == [3] and run.budget.expensive_calls == used + 3
    # Publication order: reservation < verified cleanup < every row < summary < candidate < terminal.
    events = _events(run)
    seq = {kind: [e["seq"] for e in events if e["type"] == kind and e.get("job_id") == job["job_id"]]
           for kind in ("job_cleanup_verified", "docking_batch_row_published", "docking_batch_published",
                        "job_result_candidate", "job_terminal")}
    assert len(seq["docking_batch_row_published"]) == 3
    assert (seq["job_cleanup_verified"][0] < min(seq["docking_batch_row_published"]) <
            max(seq["docking_batch_row_published"]) < seq["docking_batch_published"][0] <
            seq["job_result_candidate"][0] < seq["job_terminal"][0])
    # Wall-clock: the attempt is charged its actual elapsed time (well under the 7800 s bound).
    intent = _of(run, job["job_id"], "job_dispatch_intent")[0]
    charged = [e["seconds"] for e in events if e["type"] == "wall_charged" and e.get("call_id") == intent["attempt_id"]]
    terminal = _of(run, job["job_id"], "job_terminal")[0]
    assert len(charged) == 1 and abs(charged[0] - (terminal["ts"] - intent["ts"])) < 5.0 and charged[0] < 600
    # A batch row is an M18 result everywhere: reads, producer, M18 report.
    row = content["rows"][1]
    source = docking_bundle.producer(run, row["result_handle"])
    assert source["job"]["protocol_id"] == PROTOCOL and source["row_index"] == 1
    assert source["job"]["selected"]["ligand"]["candidate"]["id"] == IDS[0]
    assert docking_reads.result_detail(run, row["result_handle"])["job_id"] == job["job_id"]
    built = build_docking_report(run, row["result_handle"])
    assert built["manifest"]["provenance"]["docking"]["protocol_id"] == PROTOCOL
    assert saved_docking_report(run, built["handle"])["manifest"]["analysis_type"] == "ligand_docking"
    # Same input again: the complete batch job itself (no new job, no charge).
    again = client.post(f"/runs/{RID}/jobs", json={"protocol_id": PROTOCOL, "args": args, "timeout_s": 600}).json()
    assert again["job_id"] == job["job_id"] and again["output_handles"] == [summary]
    assert len([e for e in _events(run) if e["type"] == "job_submitted" and
                e["job"]["protocol_id"] == PROTOCOL]) == 1
    # Row = standalone M18: the same input as a single M18 job gives the same handle and bytes.
    single = run_job(run, "qvina_dock_v1", BI.row_request(record["parameters"], "candidate", IDS[0]), timeout_s=600)
    assert single["status"] == "done" and single["output_handles"] == [row["result_handle"]]
    assert docking_bundle.producer(run, row["result_handle"])["job_id"] == job["job_id"]   # earliest stays
    assert saved_docking_report(run, built["handle"])["manifest"] == built["manifest"]
    # N = 0: every row is a stored result -> a 0-unit job, no worker, only the summary.
    used = run.budget.expensive_calls
    zero = _batch(run, _args(base, [IDS[0]]))
    assert zero["status"] == "done" and zero["job_id"] != job["job_id"]
    assert _reserved(run, zero["job_id"]) == [0] and run.budget.expensive_calls == used
    assert not _of(run, zero["job_id"], "job_worker_started") and not _of(run, zero["job_id"], "job_launch_identity")
    _, zero_content = _summary(run, zero)
    assert zero_content["status"] == "complete" and zero_content["rows"][0]["result_handle"] == row["result_handle"]
    assert _of(run, zero["job_id"], "docking_batch_published")[0]["reused_rows"] == [0]
    assert _batch(run, _args(base, [IDS[0]]))["job_id"] == zero["job_id"]
    # Reuse: one stored row is not charged; only the new row runs.
    mixed = _batch(run, _args(base, [IDS[2], IDS[0]]))
    assert mixed["status"] == "done" and _reserved(run, mixed["job_id"]) == [1]
    assert run.budget.expensive_calls == used + 1
    _, mixed_content = _summary(run, mixed)
    assert mixed_content["rows"][0]["result_handle"] == row["result_handle"]
    assert mixed_content["status"] == "complete" and not (_attempt_dir(run, mixed) / "rows/0.started").exists()
    _no_strays(run)

    # Events-only reopen: no staged files, no engine, no worker; the same summary and rows validate.
    replay = tmp_path / "events_only"
    (replay / RID).mkdir(parents=True)
    shutil.copyfile(root / RID / "events.jsonl", replay / RID / "events.jsonl")

    def forbidden(*_a, **_k):
        raise _Forbidden("events-only reads must not execute scientific work")

    with monkeypatch.context() as patch:
        patch.setattr(docking_bundle, "WORKER_PYTHON", tmp_path / "removed/python")
        patch.setattr(docking_bundle, "QVINA", tmp_path / "removed/qvina2")
        patch.setattr(docking_bundle, "_handshake", forbidden)
        patch.setattr(docking_bundle, "stage", forbidden)
        patch.setattr(JobQueue, "_supervise", forbidden)
        patch.setattr(Run, "call", forbidden)
        recovered = new_ligand_run(replay, RID)
        with recovered._owner():
            recovered.store.rebuild_from_events()
        assert BJ.validated_summary(recovered, summary) == content
        for item in content["rows"]:
            assert docking_bundle.validated_result(recovered, item["result_handle"]) == run.store.load(
                item["result_handle"])
        path = replay / RID / recovered.store.meta(summary)["path"]
        path.write_text(json.dumps({**content, "status": "partial"}))   # labeled fault: a tampered summary
        with pytest.raises(BJ.DockingBatchEvidenceError):
            BJ.validated_summary(recovered, summary)
    for wrong in (base["receptor"], row["result_handle"], None, f"obj://{RID}/docking_batch_result/{'1' * 64}"):
        with pytest.raises(BJ.DockingBatchEvidenceError):
            BJ.validated_summary(run, wrong)


# ----------------------------------------------------------------- cancel, partial rerun, deadline, kill, restart
def test_cancel_mid_batch_keeps_finished_rows_then_a_rerun_reuses_them(base, tmp_path, monkeypatch):
    run, _root = _world(base, tmp_path)
    _raise(run)
    used = run.budget.expensive_calls
    args = _args(base, IDS)
    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_record_control",
                      _when_row_starts(1, lambda queue, job_id, _pid: queue.request_cancel(job_id)))
        cancelled = _batch(run, args)
    assert cancelled["status"] == "cancelled" and cancelled["output_handles"] == [], cancelled
    _, content = _summary(run, cancelled)
    assert content["status"] == "partial" and content["stop_reason"] == "cancelled"
    assert _computed(content)[0] in ("scored", "null_result")
    assert _states(content)[1:] == [["cancelled", "cancelled"], ["not_run", "cancelled"]]
    assert content["limitations"]["batch_statements"] == ["B1", "B2"]
    _check_rows_against_results(run, content)
    assert _reserved(run, cancelled["job_id"]) == [3] and run.budget.expensive_calls == used + 3   # no refund
    first = content["rows"][0]["result_handle"]
    _no_strays(run)
    # A partial batch never blocks the same request: the finished row is reused, only two rows are charged.
    rerun = _batch(run, args)
    assert rerun["job_id"] != cancelled["job_id"] and rerun["status"] == "done"
    assert _reserved(run, rerun["job_id"]) == [2] and run.budget.expensive_calls == used + 5
    _, complete = _summary(run, rerun)
    assert complete["status"] == "complete" and complete["rows"][0]["result_handle"] == first
    assert JobQueue(run).get(rerun["job_id"])["dispatch_intent"]["batch_reused"] == [{"row_index": 0,
                                                                                      "handle": first}]
    _no_strays(run)


def test_job_deadline_is_time_exhausted_with_a_partial_summary(base, tmp_path):
    run, _root = _world(base, tmp_path)
    _raise(run)
    failed = _batch(run, _args(base, IDS[:2], box=SLOW_BOX, params=SLOW), timeout_s=12)
    assert failed["status"] == "failed" and failed["failure"] == {"error": "resource_exceeded",
                                                                  "message": "job timeout"}, failed
    assert failed["output_handles"] == []
    _, content = _summary(run, failed)
    assert content["status"] == "partial" and content["stop_reason"] == "time_exhausted"
    assert _states(content) == [["cancelled", "time_exhausted"], ["not_run", "time_exhausted"]]
    assert _reserved(run, failed["job_id"]) == [2]
    _no_strays(run)


def test_hard_kill_of_the_worker_is_worker_failed_and_has_no_retry(base, tmp_path, monkeypatch):
    run, _root = _world(base, tmp_path)
    _raise(run)
    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_record_control",
                      _when_row_starts(1, lambda _queue, _job_id, pid: os.kill(pid, signal.SIGKILL)))
        failed = _batch(run, _args(base, IDS))
    assert failed["status"] == "failed" and failed["output_handles"] == [], failed
    _, content = _summary(run, failed)
    assert content["status"] == "partial" and content["stop_reason"] == "worker_failed"
    assert _computed(content)[0] in ("scored", "null_result")
    assert _states(content)[1:] == [["failed", "worker_failed"], ["not_run", "worker_failed"]]
    _check_rows_against_results(run, content)
    with pytest.raises(ToolFailure) as retry:   # one attempt per batch: resume is a new batch (spec 6.1)
        JobQueue(run).retry(failed["job_id"])
    assert retry.value.cls.value == "precondition"
    _no_strays(run)


def test_a_refusal_before_the_first_row_fails_the_job_without_a_summary(base, tmp_path):
    run, _root = _world(base, tmp_path)
    _raise(run)
    far = {"source": "manual", "center_A": [500.0, 500.0, 500.0], "size_A": [12.0, 12.0, 12.0]}  # admitted shape
    failed = _batch(run, _args(base, IDS[:2], box=far))
    assert failed["status"] == "failed" and failed["output_handles"] == [], failed
    assert (failed["failure"]["error"], failed["failure"]["reason_code"]) == ("input_invalid", "box_no_receptor_atoms")
    assert not _of(run, failed["job_id"], "docking_batch_published")
    assert not _of(run, failed["job_id"], "docking_batch_row_published")
    assert not (_attempt_dir(run, failed) / "rows/0.started").exists()
    assert _reserved(run, failed["job_id"]) == [2]   # charged at start, never refunded (spec 6.1)
    _no_strays(run)


DRIVER = r'''
import json, sys
from pathlib import Path
from mw.jobs.queue import JobQueue
from mw.workspace import new_run
root, rid, args = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
run = new_run(root, run_id=rid, dry_run=False)
queue = JobQueue(run)
job = queue.submit("qvina_batch_dock_v1", args, timeout_s=1200)
(root / "job_id").write_text(job["job_id"])
queue.start(job["job_id"])
'''


def test_server_death_recovery_publishes_the_staged_rows_and_a_worker_failed_summary(base, tmp_path):
    run, root = _world(base, tmp_path)
    _raise(run)
    used = run.budget.expensive_calls
    child = subprocess.Popen([sys.executable, "-c", DRIVER, str(root), RID, json.dumps(_args(base, IDS))],
                             cwd=MW.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        end = time.monotonic() + 300
        while time.monotonic() < end and not list(root.glob(f"{RID}/jobs/*/*/rows/1.started")):
            assert child.poll() is None, "the server process ended before row 1 started"
            time.sleep(0.05)
        assert list(root.glob(f"{RID}/jobs/*/*/rows/1.started")), "row 1 never started"
        child.kill()   # the API process dies; the guardian sees EOF and stops its group
        child.wait(timeout=10)
        job_id = (root / "job_id").read_text()
        reopened = new_ligand_run(root, RID)
        queue = JobQueue(reopened)
        end = time.monotonic() + 30
        while time.monotonic() < end:
            state = next(job for job in queue.reconcile_run() if job["job_id"] == job_id)
            if state["status"] == "interrupted":
                break
            time.sleep(0.2)
        assert state["status"] == "interrupted" and state["output_handles"] == [], state
        _, content = _summary(reopened, state)
        assert content["status"] == "partial" and content["stop_reason"] == "worker_failed"
        assert _computed(content)[0] in ("scored", "null_result")
        assert _states(content)[1:] == [["failed", "worker_failed"], ["not_run", "worker_failed"]]
        _check_rows_against_results(reopened, content)
        reopened._refresh()
        assert _reserved(reopened, job_id) == [3] and reopened.budget.expensive_calls == used + 3
        assert any(e["type"] == "job_cleanup_verified" and e.get("source") == "orphan_reconciliation"
                   for e in _of(reopened, job_id, "job_cleanup_verified"))
        _no_strays(reopened)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


# ----------------------------------------------------------------- dry-run
def test_dry_run_plans_only(base, tmp_path, monkeypatch):
    run, _root = _world(base, tmp_path, "real")
    args = _args(base, IDS[:1])
    selection = BJ.submission(run, args)   # the real selection, computed on the non-dry world
    dry = new_ligand_run(tmp_path / "dry", "run_dry_batch", dry_run=True)
    monkeypatch.setattr(BJ, "submission", lambda _run, _args: selection)   # labeled internal hook
    plan = JobQueue(dry).submit(PROTOCOL, args, timeout_s=7800)
    assert plan["plan_only"] is True and plan["reason_code"] == "dry_run" and plan["output_handles"] == []
    assert plan["normalized_parameters"] == selection[1]
    assert not any(e["type"] in {"job_submitted", "budget_reserved", "object_created"} for e in _events(dry))
