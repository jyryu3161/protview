"""M22 T4: the qvina GA design job lane (registration, timeout bound, reserved_units reservation without refund,
admission, staging, per-individual publication + summary in every end state, reuse in both directions with M18/M19,
duplicates, recovery, events-only reopen, dry-run).

Jobs run the real GA worker (``.deps/docking/venv-locked`` + ``.deps/qvina/env/bin/qvina2``) through ``JobQueue`` and
the guardian. They FAIL, never skip, when an environment is absent. The server test process never imports RDKit,
Meeko or MDAnalysis. Inputs: the public prepared docking example receptor (``fixtures/chemical``, not experimental
validation), the public-derived parent SDF and the labeled synthetic small pool blocks
(``fixtures/ligand_ga/SYNTHETIC-PROVENANCE.md``); the ten candidates are made here by real M17 jobs (same ids and
order as the committed ``m17-candidate-set-small-pool.json``).

Reference for the GA path: the independent standard-library oracle ``fixtures/ligand_ga/independent_ga_oracle.py``
(written in T1 from spec 3 before any product GA code) fed with the T1 real-qvina observations
``t1_observations.small_pool_docking`` (same receptor, parent, box and values as here; observations, never product
code). Engine values are otherwise only checked for consistency with the stored per-individual M18 results. Faults
(cancel, kill, parent death, a short run budget) are applied through internal test hooks or process signals, never
through request fields.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import engine_hold as EH
import pytest
from fastapi.testclient import TestClient
from ligand_job_fixture import import_file, new_ligand_run, run_job
from test_docking_batch_jobs import _no_strays

from mw import docking_batch_inputs as BI
from mw import docking_bundle, docking_reads, ligand_ga_inputs
from mw import docking_constants as C
from mw import ligand_ga_constants as GC
from mw import ligand_ga_jobs as LJ
from mw.api import app as api_module
from mw.core.errors import ToolFailure
from mw.docking_reports import build_docking_report
from mw.jobs import guardian as guardian_module
from mw.jobs.queue import GA_TIMEOUT_MAX_S, JobQueue
from mw.ligand_ga_bundle import LigandGaEvidenceError
from mw.runtime.guards import BudgetLimits
from mw.runtime.orchestrator import ApprovalRequired, Run
from mw.tools.energetic import JOB_ONLY_TOOLS, JOB_PROTOCOLS

MW = Path(__file__).resolve().parents[1] / "mw"
CHEM = Path(__file__).parent / "fixtures/chemical"
FIX = Path(__file__).parent / "fixtures/docking"
GA_FIX = Path(__file__).parent / "fixtures/ligand_ga"
REC = (CHEM / "prolif-vina-rec.pdb").read_bytes()
PARENT = (FIX / "public-derived-parent-record0.sdf").read_bytes()
BLOCKS = (GA_FIX / "synthetic-ga-small-blocks.smi").read_bytes()
EXPECTED = json.loads((GA_FIX / "expected.json").read_text())
IDS = [row["id"] for row in json.loads((GA_FIX / "m17-candidate-set-small-pool.json").read_text())["candidates"]]
OBS = EXPECTED["t1_observations"]["small_pool_docking"]
OBS_SCORES = {row["candidate_id"]: row["first_mode_score_kcal_mol"] for row in OBS["rows"]}
BITS = {row["candidate_id"]: frozenset(row["morgan_r2_2048_on_bits"]) for row in EXPECTED["pools"]["small"]["candidates"]}
BOX = {"source": "manual", "center_A": OBS["box"]["center_A"], "size_A": OBS["box"]["size_A"]}
FAST = dict(OBS["parameters"])      # seed 1, exhaustiveness 1, num_modes 2 (= the T1 observations)
ACK = {key: True for key in C.ACKNOWLEDGEMENT_KEYS}
RID = "run_m22_ga"
PROTOCOL = "qvina_ga_dock_v1"
TOOL = "qvina_ga_design"
FORBIDDEN_MODULES = ("rdkit", "meeko", "MDAnalysis")
GA = {"seed": 7, "population_size": 4, "generations": 2, "elite_count": 2, "tournament_size": 2, "neighbor_count": 3,
      "random_fraction": 0.25, "patience": 2, "max_new_dockings": 6, "total_s": 600}


def _oracle():
    spec = importlib.util.spec_from_file_location("independent_ga_oracle_t4", GA_FIX / "independent_ga_oracle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ORACLE = _oracle()


def oracle_path(ga: dict, reusable=()) -> dict:
    return ORACLE.run_ga(IDS, [True] * len(IDS), BITS, OBS_SCORES, set(reusable), ga, None)


# ----------------------------------------------------------------- world (real M17 jobs once, copied per test)
@pytest.fixture(scope="module")
def base(tmp_path_factory):
    root = tmp_path_factory.mktemp("m22_base")
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


def world(base: dict, tmp_path: Path, name: str = "runs") -> tuple[Run, Path]:
    """A fresh runs root holding only the base run's events (events-only reopen; same handles)."""
    root = tmp_path / name
    (root / RID).mkdir(parents=True)
    shutil.copyfile(base["root"] / RID / "events.jsonl", root / RID / "events.jsonl")
    run = new_ligand_run(root, RID)
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
    return run, root


def raise_limits(run: Run, calls: int = 80, wall: float = 30000) -> None:
    run.update_limits(BudgetLimits(expensive_calls=calls, wall_clock_s=wall), by="test")


def ga_args(base: dict, **ga) -> dict:
    return {"receptor_handle": base["receptor"], "receptor_model_number": 1,
            "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
            "candidate_set_handle": base["candidate_set"], "parent_sdf_handle": base["parent"], "box": BOX,
            "parameters": FAST, "acknowledgement": ACK, "ga": {**GA, **ga}}


def start(queue: JobQueue, job_id: str) -> dict:
    try:
        return queue.start(job_id)
    except ApprovalRequired:
        queue.run.approve("expensive_first_call", by="test")
        return queue.start(job_id)


def run_ga(run: Run, args: dict, timeout_s: float | None = None) -> dict:
    queue = JobQueue(run)
    job = queue.submit(PROTOCOL, args, timeout_s=timeout_s or args["ga"]["total_s"] + 600)
    return job if job["status"] != "queued" else start(queue, job["job_id"])


def events(run: Run) -> list[dict]:
    return list(run.events.read())


def of(run: Run, job_id: str, kind: str) -> list[dict]:
    return [e for e in events(run) if e["type"] == kind and e.get("job_id") == job_id]


def reserved(run: Run, job_id: str) -> list[int]:
    attempts = {e["attempt_id"] for e in of(run, job_id, "job_dispatch_intent")}
    return [e["expensive_calls"] for e in events(run) if e["type"] == "budget_reserved" and
            e.get("attempt_id") in attempts]


def summary(run: Run, job: dict) -> tuple[str, dict]:
    published = of(run, job["job_id"], "ligand_ga_published")
    assert len(published) == 1, published
    handle = published[0]["summary_handle"]
    assert JobQueue(run).get(job["job_id"])["ga_summary_handle"] == handle
    return handle, LJ.validated_summary(run, handle)


def path(content: dict) -> list[list[tuple]]:
    keys = ("candidate_id", "origin", "parent_candidate_id", "similarity", "evaluation", "eval_index", "score")
    return [[tuple(entry[key] for key in keys) for entry in g["individuals"]] for g in content["generations"]]


def evaluated(content: dict) -> list[dict]:
    return [e for g in content["generations"] for e in g["individuals"] if e["origin"] != "carried"]


def check_individuals(run: Run, job: dict, content: dict) -> None:
    """Every evaluated individual's result is a validated M18 result of its own candidate; every newly docked one was
    published once by this job (eval_index, candidate id, handle); scores are the stored first mode."""
    published = {e["eval_index"]: e for e in of(run, job["job_id"], "ligand_ga_individual_published")}
    docked = [e for e in evaluated(content) if e["evaluation"] == "docked" and e["result_handle"] is not None]
    assert sorted(published) == sorted(e["eval_index"] for e in docked)
    for entry in evaluated(content):
        if entry["result_handle"] is None:
            assert entry["state"] == "failed" and entry["score"] is None
            continue
        result = docking_bundle.validated_result(run, entry["result_handle"])
        assert result["inputs"]["ligand"]["candidate_id"] == entry["candidate_id"]
        assert entry["score"] == (result["modes"][0]["score_kcal_mol"] if result["modes"] else None)
        if entry["evaluation"] == "docked":
            event = published[entry["eval_index"]]
            assert (event["candidate_id"], event["handle"]) == (entry["candidate_id"], entry["result_handle"])


def when_started(index: int, action) -> object:
    """Wrap _record_control: on STARTED, a thread waits for individuals/<index>.started of this attempt, then acts."""
    original = JobQueue._record_control

    def record(self, message, job_id, attempt_id, nonce):
        done = original(self, message, job_id, attempt_id, nonce)
        if message and message.get("kind") == "STARTED":
            marker = self.run.run_dir / "jobs" / job_id / attempt_id / "individuals" / f"{index}.started"

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
    assert JOB_PROTOCOLS[PROTOCOL] == (TOOL, "qvina")
    assert TOOL in JOB_ONLY_TOOLS and TOOL not in api_module.SUPPORTED_TOOLS
    spec = api_module.REGISTRY.specs[TOOL]
    assert spec.cost_class == "expensive" and spec.emits == "ligand_ga_result"
    assert TOOL in api_module.REGISTRY.unavailable
    assert guardian_module.LIGAND_GA == MW / "jobs/ligand_ga_worker.py" == LJ.GA_WORKER
    assert guardian_module.LIGAND_GA_ADAPTER == PROTOCOL in guardian_module.MONITORED_ADAPTERS
    assert PROTOCOL not in guardian_module.PINNED_PYTHON_ADAPTERS and PROTOCOL in guardian_module.DOCKING_ADAPTERS
    assert GA_TIMEOUT_MAX_S == GC.TIMEOUT_MAX_S == 15000
    for name in ("ligand_ga_jobs.py", "ligand_ga_bundle.py", "ligand_ga_inputs.py", "ligand_ga_constants.py",
                 "docking_bundle.py", "docking_batch_inputs.py", "jobs/queue.py", "jobs/guardian.py", "api/app.py"):
        tree = ast.parse((MW / name).read_text())
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert not any(m == top or m.startswith(top + ".") for m in imported for top in FORBIDDEN_MODULES), name
    capability = LJ.capability()
    assert capability["available"] is True, capability["reason"]
    assert capability["pins"] == docking_bundle.capability()["pins"]
    assert capability["ga_pins"] == LJ.ga_pins() and set(capability["ga_pins"]) == {"ga_worker_sha256",
                                                                                     "ga_constants_sha256"}
    assert capability["timeout_s"]["max"] == 15000 and capability["ga_ranges"]["population_size"] == {
        "min": 4, "max": 24, "default": 12}
    assert capability["statements"] == GC.STATEMENTS and capability["score_label"] == C.SCORE_LABEL
    root = tmp_path / "runs"
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    methods = client.get("/capabilities").json()["methods"]
    assert methods["ligand_ga_design"] == capability
    with monkeypatch.context() as patch:   # unavailable: reason only, the M18 set; no pins or limits
        patch.setattr(docking_bundle, "QVINA", tmp_path / "missing/qvina2")
        down = LJ.capability()
        assert (down["available"], down["reason_code"], down["pins"], down["ga_pins"]) == (
            False, "engine_missing", None, None)
        assert "limits" not in down and down["reason"] == docking_bundle.REASONS["engine_missing"]
    with monkeypatch.context() as patch:
        patch.setattr(LJ, "GA_WORKER", tmp_path / "missing/ligand_ga_worker.py")
        assert LJ.capability()["reason_code"] == "worker_missing"
    with monkeypatch.context() as patch:
        patch.setattr(LJ, "_HANDSHAKE_CACHE", {})
        good = LJ._handshake()
        patch.setattr(LJ, "_handshake", lambda: {**good, "ga_constants_sha256": "0" * 64})
        assert LJ.capability()["reason_code"] == "handshake_failed"
    # Protocol-only timeout bound: 15000 s for the GA (checked with its arguments), every other protocol keeps its own.
    queue = JobQueue(new_ligand_run(tmp_path / "bounds", "run_bounds"))
    for protocol, timeout in (("qvina_batch_dock_v1", 7801), ("qvina_dock_v1", 901), ("rdkit_inspect_v1", 121)):
        with pytest.raises(ToolFailure) as refused:
            queue.submit(protocol, {}, timeout_s=timeout)
        assert refused.value.message == "invalid job timeout"
    for timeout in (15000, 15001, None):   # the GA's own admission refuses (empty arguments first)
        with pytest.raises(ToolFailure) as refused:
            queue.submit(PROTOCOL, {}, timeout_s=timeout)
        assert refused.value.detail["reason_code"] == "invalid_job_arguments"
    rid = client.post("/runs", json={"goal": "M22 bounds", "dry_run": False}).json()["run_id"]
    over = client.post(f"/runs/{rid}/jobs", json={"protocol_id": PROTOCOL, "args": {}, "timeout_s": 15001})
    assert over.status_code == 422 and over.json()["detail"]["reason_code"] == "invalid_job_arguments"
    batch = client.post(f"/runs/{rid}/jobs", json={"protocol_id": "qvina_batch_dock_v1", "args": {},
                                                   "timeout_s": 7801})
    m18 = client.post(f"/runs/{rid}/jobs", json={"protocol_id": "qvina_dock_v1", "args": {}, "timeout_s": 7800})
    assert batch.status_code == 422 and batch.json()["message"] == "invalid job timeout"
    assert m18.status_code == 422 and m18.json()["message"] == "invalid job timeout"
    absent = client.post(f"/runs/{rid}/jobs", json={"protocol_id": PROTOCOL, "args": {}})
    assert absent.status_code == 422 and absent.json()["detail"]["reason_code"] == "invalid_job_arguments"


def test_timeout_must_cover_total_s_plus_600_and_reaches_15000(base, tmp_path):
    run, _root = world(base, tmp_path)
    queue = JobQueue(run)
    before = events(run)
    for total, timeout in ((600, 1199), (600, None), (14400, 14999), (14400, 15000.5)):
        with pytest.raises(ToolFailure) as refused:
            queue.submit(PROTOCOL, ga_args(base, total_s=total), timeout_s=timeout)
        assert refused.value.detail["reason_code"] == "invalid_job_arguments", (total, timeout)
    assert events(run) == before   # nothing recorded or charged
    raise_limits(run)
    accepted = queue.submit(PROTOCOL, ga_args(base, total_s=14400), timeout_s=15000)
    assert accepted["status"] == "queued" and accepted["timeout_s"] == 15000 and accepted["tool_id"] == TOOL
    # job_submitted stays small: the GA record, never a per-candidate M18 selection (spec 7).
    record = next(e["job"] for e in events(run) if e["type"] == "job_submitted" and
                  e["job"]["job_id"] == accepted["job_id"])
    assert set(record["selected"]) == {"schema", "arguments", "receptor", "sidecar", "candidate_set", "parent_sdf",
                                       "pool", "pool_sha256", "selection_sha256"}
    assert [item["candidate_id"] for item in record["selected"]["pool"]] == IDS
    assert "docking_selection@1" not in json.dumps(record)
    assert set(record["ga_method"]) == {"ga_worker_sha256", "ga_constants_sha256"}
    assert record["method"] == docking_bundle.capability()["pins"]
    JobQueue(run).request_cancel(accepted["job_id"])


# ----------------------------------------------------------------- full product path, reuse both ways, identity
def test_product_path_reuse_duplicates_identity_and_events_only(base, tmp_path, monkeypatch):
    run, root = world(base, tmp_path)
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    raise_limits(run)
    # A standalone M18 result first: the GA reuses it (same call key), unchanged and unpublished again.
    shared = ligand_ga_inputs.m18_shared(ligand_ga_inputs.validate_arguments(ga_args(base), 1200))
    single = run_job(run, "qvina_dock_v1", BI.row_request(shared, "candidate", IDS[5]), timeout_s=600)
    assert single["status"] == "done", single
    m18_handle = single["output_handles"][0]
    args = ga_args(base)
    expected = oracle_path(GA, reusable={IDS[5]})
    assert expected["stop_reason"] == "generations_complete" and expected["reused_count"] == 1
    used = run.budget.expensive_calls
    submitted = client.post(f"/runs/{RID}/jobs", json={"protocol_id": PROTOCOL, "args": args, "timeout_s": 1200})
    assert submitted.status_code == 200, submitted.text
    job = submitted.json()
    assert job["status"] == "queued" and job["timeout_s"] == 1200
    done = client.post(f"/runs/{RID}/jobs/{job['job_id']}/start").json()
    assert done["status"] == "done", done
    handle = done["artifacts"]["ligand_ga_result"]
    assert done["output_handles"] == [handle]   # the summary only; individuals are reached through it
    run = api_module._run(RID)
    content = LJ.validated_summary(run, handle)
    # The path is the oracle's (T1 real-qvina observations as scores); the stored result scores agree.
    assert path(content) == path(expected)
    assert (content["status"], content["stop_reason"], content["generations_done"]) == (
        "complete", "generations_complete", 2)
    assert (content["new_dockings_used"], content["reused_count"], content["reserved_units"]) == (5, 1, 6)
    assert content["limitations"] == ["G1", "G3"]
    assert next(e for e in evaluated(content) if e["candidate_id"] == IDS[5])["result_handle"] == m18_handle
    check_individuals(run, job, content)
    # reserved_units at the start, never refunded although one individual was reused and 5 docked.
    assert reserved(run, job["job_id"]) == [6] and run.budget.expensive_calls == used + 6
    intent = of(run, job["job_id"], "job_dispatch_intent")[0]
    assert intent["ga_reused"] == [{"candidate_id": IDS[5], "handle": m18_handle}]
    assert done["ga"] == {"pool": {"size": 10, "eligible_count": 10, "filter_excluded_count": 0},
                          "reserved_units": 6, "reused_planned": 1, "individuals_started": 5,
                          "individuals_result_files": 5, "individuals_finished": 5, "generation_records": 2, "generations_complete": 2,
                          "summary_handle": handle, "summary_status": "complete",
                          "summary_stop_reason": "generations_complete"}
    # Publication order: reservation < verified cleanup < every individual < summary < candidate < terminal.
    seq = {kind: [e["seq"] for e in of(run, job["job_id"], kind)]
           for kind in ("job_cleanup_verified", "ligand_ga_individual_published", "ligand_ga_published",
                        "job_result_candidate", "job_terminal")}
    assert len(seq["ligand_ga_individual_published"]) == 5
    assert (seq["job_cleanup_verified"][0] < min(seq["ligand_ga_individual_published"]) <
            max(seq["ligand_ga_individual_published"]) < seq["ligand_ga_published"][0] <
            seq["job_result_candidate"][0] < seq["job_terminal"][0])
    # An individual is an M18 result everywhere: producer, reads, M18 report; the earlier M18 job stays producer.
    first = next(e for e in evaluated(content) if e["evaluation"] == "docked")
    source = docking_bundle.producer(run, first["result_handle"])
    assert source["job"]["protocol_id"] == PROTOCOL and source["candidate_id"] == first["candidate_id"]
    assert source["job"]["selected"]["schema"] == "docking_selection@1"
    assert source["job"]["selected"]["ligand"]["candidate"]["id"] == first["candidate_id"]
    assert docking_bundle.producer(run, m18_handle)["job_id"] == single["job_id"]
    assert docking_reads.result_detail(run, first["result_handle"])["job_id"] == job["job_id"]
    built = build_docking_report(run, first["result_handle"])
    assert built["manifest"]["provenance"]["docking"]["protocol_id"] == PROTOCOL
    # Individual = standalone M18: the same input as a single M18 job gives the same handle and bytes.
    record = JobQueue(run).get(job["job_id"])
    again_single = run_job(run, "qvina_dock_v1", BI.row_request(ligand_ga_inputs.m18_shared(record["parameters"]),
                                                                "candidate", first["candidate_id"]), timeout_s=600)
    assert again_single["status"] == "done" and again_single["output_handles"] == [first["result_handle"]]
    assert docking_bundle.producer(run, first["result_handle"])["job_id"] == job["job_id"]   # earliest stays
    # The reuse index now holds every GA individual under its M18 call key.
    index = BI.published_m18_results(run.events.read())
    for entry in evaluated(content):
        key = docking_bundle.call_key(ligand_ga_inputs.row_arguments(record["parameters"], entry["candidate_id"]),
                                      record["method"])
        assert index[key] == entry["result_handle"]
    # Same request again: the complete GA job itself (no new job, no charge).
    used = run.budget.expensive_calls
    again = client.post(f"/runs/{RID}/jobs", json={"protocol_id": PROTOCOL, "args": args, "timeout_s": 1300}).json()
    assert again["job_id"] == job["job_id"] and again["output_handles"] == [handle]
    assert run.budget.expensive_calls == used
    # A different GA seed: a new call key; every candidate evaluated before is reused (no new docking for it).
    seen = {e["candidate_id"] for e in evaluated(content)}
    other_expected = oracle_path({**GA, "seed": 8}, reusable=seen)
    other = run_ga(run, ga_args(base, seed=8))
    assert other["status"] == "done" and other["job_id"] != job["job_id"] and other["call_key"] != job["call_key"]
    _, other_content = summary(run, other)
    assert path(other_content) == path(other_expected)
    assert other_content["reused_count"] == other_expected["reused_count"] >= 1
    assert reserved(run, other["job_id"]) == [6]
    for entry in evaluated(other_content):
        if entry["evaluation"] == "reused":
            assert entry["result_handle"] in {e["result_handle"] for e in evaluated(content)}
    check_individuals(run, other, other_content)
    _no_strays(run)

    # Events-only reopen: no staged files, no engine, no worker; the same summary and individuals validate.
    replay = tmp_path / "events_only"
    (replay / RID).mkdir(parents=True)
    shutil.copyfile(root / RID / "events.jsonl", replay / RID / "events.jsonl")

    def forbidden(*_a, **_k):
        raise AssertionError("events-only reads must not execute scientific work")

    with monkeypatch.context() as patch:
        patch.setattr(docking_bundle, "WORKER_PYTHON", tmp_path / "removed/python")
        patch.setattr(docking_bundle, "QVINA", tmp_path / "removed/qvina2")
        patch.setattr(docking_bundle, "_handshake", forbidden)
        patch.setattr(LJ, "_handshake", forbidden)
        patch.setattr(docking_bundle, "stage", forbidden)
        patch.setattr(JobQueue, "_supervise", forbidden)
        patch.setattr(Run, "call", forbidden)
        recovered = new_ligand_run(replay, RID)
        with recovered._owner():
            recovered.store.rebuild_from_events()
        assert LJ.validated_summary(recovered, handle) == content
        for entry in evaluated(content):
            assert docking_bundle.validated_result(recovered, entry["result_handle"]) == run.store.load(
                entry["result_handle"])
        stored = replay / RID / recovered.store.meta(handle)["path"]
        tampered = {**content, "generations": content["generations"][:1], "generations_done": 1}
        stored.write_text(json.dumps(tampered))   # labeled fault: a tampered summary
        with pytest.raises(LigandGaEvidenceError):
            LJ.validated_summary(recovered, handle)
    for wrong in (base["receptor"], first["result_handle"], None, f"obj://{RID}/ligand_ga_result/{'1' * 64}"):
        with pytest.raises(LigandGaEvidenceError):
            LJ.validated_summary(run, wrong)


# ----------------------------------------------------------------- docking limit, partial rerun, reuse not charged
def test_docking_limit_partial_then_a_rerun_reuses_and_completes(base, tmp_path):
    run, _root = world(base, tmp_path)
    raise_limits(run)
    ga = {**GA, "seed": 3, "max_new_dockings": 4}   # reserved_units = min(4, 4 + 1 x 2) = 4
    expected = oracle_path(ga)
    assert expected["stop_reason"] == "docking_limit"
    used = run.budget.expensive_calls
    limited = run_ga(run, ga_args(base, **ga))
    assert limited["status"] == "done", limited   # the worker ended by itself: the job is done, the summary partial
    _, content = summary(run, limited)
    assert path(content) == path(expected)
    assert (content["status"], content["stop_reason"], content["generations_done"]) == ("partial", "docking_limit", 1)
    assert content["generations"][-1]["complete"] is False and content["limitations"] == ["G1", "G2"]
    assert (content["new_dockings_used"], content["reserved_units"]) == (4, 4)
    check_individuals(run, limited, content)
    assert reserved(run, limited["job_id"]) == [4] and run.budget.expensive_calls == used + 4
    # A partial GA never deduplicates: the same request is a new job; the four results are reused (no new docking).
    rerun = run_ga(run, ga_args(base, **ga))
    assert rerun["job_id"] != limited["job_id"] and rerun["status"] == "done"
    rerun_expected = oracle_path(ga, reusable={e["candidate_id"] for e in evaluated(content)})
    _, complete = summary(run, rerun)
    assert path(complete) == path(rerun_expected)
    assert (complete["status"], complete["stop_reason"]) == ("complete", "generations_complete")
    assert (complete["reused_count"], complete["new_dockings_used"]) == (4, 2)
    assert complete["limitations"] == ["G1", "G3"]
    assert reserved(run, rerun["job_id"]) == [4] and run.budget.expensive_calls == used + 8   # no refund
    assert len(of(run, rerun["job_id"], "ligand_ga_individual_published")) == 2
    check_individuals(run, rerun, complete)
    _no_strays(run)


# ----------------------------------------------------------------- cancel, deadline, kill, restart
def test_cancel_mid_run_keeps_published_individuals_and_a_partial_summary(base, tmp_path, monkeypatch):
    run, _root = world(base, tmp_path)
    raise_limits(run)
    used = run.budget.expensive_calls
    held: list[dict] = []
    with monkeypatch.context() as patch:
        # M29 T2: individual 1's qvina2 is held until the cancel reaches the worker
        # (engine_hold.cancel_when_engine_runs): its docking (exhaustiveness 1) is short, and under Stop-hook load
        # the cancel can take longer to reach the worker.
        patch.setattr(JobQueue, "_record_control", EH.cancel_when_engine_runs(
            JobQueue._record_control, "qvina2", "individuals/1.started", "individuals/1.status.json", held))
        cancelled = run_ga(run, ga_args(base, seed=3))
    assert len(held) == 1 and "error" not in held[0], (held, cancelled)
    assert cancelled["status"] == "cancelled" and cancelled["output_handles"] == [], cancelled
    _, content = summary(run, cancelled)
    assert (content["status"], content["stop_reason"], content["generations_done"]) == ("partial", "cancelled", 0)
    first = oracle_path({**GA, "seed": 3})["generations"][0]["individuals"][0]
    assert [e["candidate_id"] for e in evaluated(content)] == [first["candidate_id"]]   # #1 interrupted: not listed
    assert content["generations"][0]["complete"] is False and content["limitations"] == ["G1", "G2"]
    check_individuals(run, cancelled, content)
    assert len(of(run, cancelled["job_id"], "ligand_ga_individual_published")) == 1
    assert reserved(run, cancelled["job_id"]) == [6] and run.budget.expensive_calls == used + 6   # no refund
    _no_strays(run)


def test_run_budget_deadline_is_time_exhausted_with_a_partial_summary(base, tmp_path):
    run, _root = world(base, tmp_path)
    raise_limits(run)
    queue = JobQueue(run)
    job = queue.submit(PROTOCOL, ga_args(base, seed=3), timeout_s=1200)
    run._refresh()
    left = 25.0   # labeled internal fault: a test-only limit update leaves 25 s of run wall time for the attempt
    run.update_limits(BudgetLimits(expensive_calls=80, wall_clock_s=run.budget.snapshot()["wall_clock_s"]["used"] +
                                   left), by="test")
    failed = start(queue, job["job_id"])
    assert failed["status"] == "failed" and failed["failure"] == {"error": "resource_exceeded",
                                                                  "message": "job timeout"}, failed
    _, content = summary(run, failed)
    assert (content["status"], content["stop_reason"]) == ("partial", "time_exhausted")
    assert content["generations"] and content["generations"][-1]["complete"] is False
    check_individuals(run, failed, content)
    progress = LJ.progress(run, JobQueue(run).get(failed["job_id"]))
    assert (progress["summary_status"], progress["summary_stop_reason"]) == ("partial", "time_exhausted")
    assert reserved(run, failed["job_id"]) == [6]
    _no_strays(run)


def test_hard_kill_of_the_worker_is_worker_failed_and_has_no_retry(base, tmp_path, monkeypatch):
    run, _root = world(base, tmp_path)
    raise_limits(run)
    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_record_control",
                      when_started(1, lambda _queue, _job_id, pid: os.kill(pid, signal.SIGKILL)))
        failed = run_ga(run, ga_args(base, seed=3))
    assert failed["status"] == "failed" and failed["output_handles"] == [], failed
    _, content = summary(run, failed)
    assert (content["status"], content["stop_reason"]) == ("partial", "worker_failed")
    assert len(evaluated(content)) == 1 and evaluated(content)[0]["state"] in ("scored", "null_result")
    check_individuals(run, failed, content)
    with pytest.raises(ToolFailure) as retry:   # one attempt per GA: a new run is a new job
        JobQueue(run).retry(failed["job_id"])
    assert retry.value.cls.value == "precondition"
    _no_strays(run)


def test_a_refusal_before_the_first_individual_fails_the_job_without_a_summary(base, tmp_path):
    run, _root = world(base, tmp_path)
    raise_limits(run)
    far = {"source": "manual", "center_A": [500.0, 500.0, 500.0], "size_A": [12.0, 12.0, 12.0]}  # admitted shape
    failed = run_ga(run, {**ga_args(base), "box": far})
    assert failed["status"] == "failed" and failed["output_handles"] == [], failed
    assert (failed["failure"]["error"], failed["failure"]["reason_code"]) == ("input_invalid", "box_no_receptor_atoms")
    assert not of(run, failed["job_id"], "ligand_ga_published")
    assert not of(run, failed["job_id"], "ligand_ga_individual_published")
    assert reserved(run, failed["job_id"]) == [6]   # charged at start, never refunded
    _no_strays(run)


DRIVER = r'''
import json, sys
from pathlib import Path
from mw.jobs.queue import JobQueue
from mw.workspace import new_run
root, rid, args = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
run = new_run(root, run_id=rid, dry_run=False)
queue = JobQueue(run)
job = queue.submit("qvina_ga_dock_v1", args, timeout_s=1200)
(root / "job_id").write_text(job["job_id"])
queue.start(job["job_id"])
'''


def test_server_death_recovery_publishes_staged_individuals_and_a_worker_failed_summary(base, tmp_path):
    run, root = world(base, tmp_path)
    raise_limits(run)
    used = run.budget.expensive_calls
    child = subprocess.Popen([sys.executable, "-c", DRIVER, str(root), RID, json.dumps(ga_args(base, seed=3))],
                             cwd=MW.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        end = time.monotonic() + 300
        while time.monotonic() < end and not list(root.glob(f"{RID}/jobs/*/*/individuals/1.started")):
            assert child.poll() is None, "the server process ended before individual 1 started"
            time.sleep(0.05)
        assert list(root.glob(f"{RID}/jobs/*/*/individuals/1.started")), "individual 1 never started"
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
        _, content = summary(reopened, state)
        assert (content["status"], content["stop_reason"]) == ("partial", "worker_failed")
        assert len(evaluated(content)) == 1
        check_individuals(reopened, state, content)
        reopened._refresh()
        assert reserved(reopened, job_id) == [6] and reopened.budget.expensive_calls == used + 6
        assert any(e.get("source") == "orphan_reconciliation" for e in of(reopened, job_id, "job_cleanup_verified"))
        _no_strays(reopened)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


# ----------------------------------------------------------------- dry-run, admission refusals
def test_dry_run_plans_only(base, tmp_path, monkeypatch):
    run, _root = world(base, tmp_path, "real")
    args = ga_args(base)
    selection = LJ.submission(run, args, 1200)   # the real selection, computed on the non-dry world
    dry = new_ligand_run(tmp_path / "dry", "run_dry_ga", dry_run=True)
    monkeypatch.setattr(LJ, "submission", lambda _run, _args, _timeout: selection)   # labeled internal hook
    plan = JobQueue(dry).submit(PROTOCOL, args, timeout_s=1200)
    assert plan["plan_only"] is True and plan["reason_code"] == "dry_run" and plan["output_handles"] == []
    assert plan["normalized_parameters"] == selection[1]
    assert not any(e["type"] in {"job_submitted", "budget_reserved", "object_created"} for e in events(dry))


def test_admission_refusals_record_and_charge_nothing(base, tmp_path, monkeypatch):
    run, _root = world(base, tmp_path)
    raise_limits(run)
    queue = JobQueue(run)
    before = events(run)
    cases = [(ga_args(base, population_size=12, max_new_dockings=12), "ga_pool_too_small"),
             ({**ga_args(base), "filter": {"ranges": {"heavy_atoms": {"max": 1}}}}, "ga_pool_too_small"),
             ({**ga_args(base), "mode": "free"}, "invalid_job_arguments"),
             (ga_args(base, elite_count=3), "invalid_job_arguments")]
    for args, reason in cases:
        with pytest.raises(ToolFailure) as refused:
            queue.submit(PROTOCOL, args, timeout_s=1200)
        assert refused.value.detail["reason_code"] == reason, args
    with monkeypatch.context() as patch:   # labeled internal hook: the size limit reached by the stored results
        patch.setattr(GC, "MAX_REUSE_STAGING_BYTES", -1)
        with pytest.raises(ToolFailure) as refused:
            queue.submit(PROTOCOL, ga_args(base), timeout_s=1200)
        assert refused.value.detail["reason_code"] == "ga_reuse_too_large"
    assert [e for e in events(run)[len(before):] if e["type"] in {"job_submitted", "budget_reserved"}] == []
    # The reuse set is decided again at the start: grown past the limit there, the start refuses before reserving.
    admitted = queue.submit(PROTOCOL, ga_args(base), timeout_s=1200)
    used = run.budget.expensive_calls
    with monkeypatch.context() as patch:   # labeled internal hook: the size limit reached at the start
        patch.setattr(GC, "MAX_REUSE_STAGING_BYTES", -1)
        with pytest.raises(ToolFailure) as refused:
            queue.start(admitted["job_id"])
        assert refused.value.detail["reason_code"] == "ga_reuse_too_large"
    assert reserved(run, admitted["job_id"]) == [] and run.budget.expensive_calls == used
    assert not of(run, admitted["job_id"], "job_dispatch_intent")
    assert not [e for e in events(run) if e["type"] == "budget_reserved" and e.get("tool") == TOOL]
    queue.request_cancel(admitted["job_id"])


# ----------------------------------------------------------------- staged records the worker did not end as recorded
def test_an_unreadable_generation_record_or_an_end_mismatch_publishes_then_is_worker_failed(base, tmp_path,
                                                                                            monkeypatch):
    run, _root = world(base, tmp_path)
    raise_limits(run)
    original = LJ.finish
    expected = oracle_path({**GA, "seed": 3})
    assert len(expected["generations"]) == 2

    def torn(run_, job, attempt_id, attempt_dir, server_cause):
        (attempt_dir / "generations" / "2.json").write_bytes(b"{torn")   # labeled fault: an unreadable record
        return original(run_, job, attempt_id, attempt_dir, server_cause)

    with monkeypatch.context() as patch:
        patch.setattr(LJ, "finish", torn)
        broken = run_ga(run, ga_args(base, seed=3))
    _, content = summary(run, broken)
    assert (content["status"], content["stop_reason"], content["generations_done"]) == ("partial", "worker_failed", 1)
    assert path(content) == path(expected)[:1]   # the readable record 1 is kept, record 2 is not part of it
    check_individuals(run, broken, content)
    assert len(of(run, broken["job_id"], "ligand_ga_individual_published")) == sum(
        e["evaluation"] == "docked" for e in evaluated(content)) >= 1

    end_record = LJ._end_record
    seen = {e["candidate_id"] for e in evaluated(content)}

    def disagreeing(attempt_dir, job, attempt_id):   # labeled fault: the end record miscounts its generations
        end = end_record(attempt_dir, job, attempt_id)
        return None if end is None else {**end, "generations_done": end["generations_done"] + 1}

    with monkeypatch.context() as patch:
        patch.setattr(LJ, "_end_record", disagreeing)
        miscounted = run_ga(run, ga_args(base, seed=4))
    other = oracle_path({**GA, "seed": 4}, reusable=seen)
    _, content = summary(run, miscounted)
    assert (content["status"], content["stop_reason"]) == ("partial", "worker_failed")
    assert path(content) == path(other) and content["generations_done"] == other["generations_done"]
    check_individuals(run, miscounted, content)
    _no_strays(run)
