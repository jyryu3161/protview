"""M23 T5: the sequence GA job lane (registration, the 15000 s bound, admission order, the reserved_units reservation
without refund, staging, publication of the reference row, individuals and summary in every end state, the M18
receptor source on ``mutation_set_model@1``, reuse, duplicates, recovery, events-only reopen, dry-run, golden keys).

Jobs run the real GA worker (``.deps/docking/venv-locked`` + ``.deps/qvina/env/bin/qvina2``) with the real modeling
child (project ``.venv``: OpenMM 8.6.0, PDBFixer 1.12.0) through ``JobQueue`` and the guardian. They FAIL, never skip,
when an environment is absent. The server test process never imports RDKit, Meeko, MDAnalysis or PDBFixer. Inputs:
public 1UBQ (not experimental validation of anything here) through the product HTTP path, the real tiny M20 set of
``fixtures/sequence_ga`` and the labeled synthetic phenol SDF (``fixtures/mutation_model``).

References for the GA path: the INDEPENDENT T1 oracle ``fixtures/sequence_ga/independent_sequence_ga_oracle.py``
(standard library only, written before any product GA code) fed with the T1 real-engine observations
``s4_tiny_observed`` (same structure, set, ligand, box and docking values as here; observations, never product
code). Every individual's docking result is compared with a standalone M18 ``qvina_dock_v1`` job on the same
``receptor_source`` (handle, call key and worker output bytes). Faults (cancel, kill, parent death, a short run
budget, a size limit) are applied through internal test hooks or process signals, never through request fields.
"""
from __future__ import annotations

import ast
import hashlib
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

import psutil
import pytest
from fastapi.testclient import TestClient
from ligand_job_fixture import run_job
from sequence_ga_fixture import EXPECTED, FIX, GA_FIX, args_for, real_world

from mw import docking_batch_inputs as BI
from mw import docking_bundle, docking_reads
from mw import sequence_ga_constants as SC
from mw import sequence_ga_inputs as GI
from mw import sequence_ga_jobs as SJ
from mw import sequence_model_bundle as SM
from mw.api import app as api_module
from mw.core.errors import ToolFailure
from mw.core.handles import canonical_json
from mw.docking_reports import build_docking_report
from mw.jobs import guardian as guardian_module
from mw.jobs import process_identity
from mw.jobs.queue import SEQUENCE_GA_TIMEOUT_MAX_S, JobQueue
from mw.runtime.guards import BudgetLimits
from mw.runtime.orchestrator import ApprovalRequired, Run
from mw.sequence_ga_bundle import SequenceGaEvidenceError
from mw.tools import openmm_method
from mw.tools.energetic import JOB_ONLY_TOOLS, JOB_PROTOCOLS
from mw.workspace import new_run

MW = Path(__file__).resolve().parents[1] / "mw"
ROOT = MW.parents[1]
PROTOCOL, TOOL = SC.PROTOCOL, SC.TOOL
FORBIDDEN_MODULES = ("rdkit", "meeko", "MDAnalysis", "pdbfixer")
IMPLICIT_H = (FIX / "docking/synthetic-ligand-implicit-h.sdf").read_bytes()
TINY_SPACE = EXPECTED["spaces"]["s4_tiny_1ubq"]
OBSERVED = EXPECTED["vectors"]["s4_tiny_observed"]["scores"]     # T1 real-engine first-mode table (observations)
DOCK = {"seed": 20261004, "exhaustiveness": 4, "num_modes": 5}    # the T1 (g) docking values
GA = {"seed": 21, "population_size": 4, "generations": 2, "elite_count": 1, "tournament_size": 2,
      "crossover_fraction": 0.5, "random_fraction": 0.25, "max_mutations": 3, "patience": 2,
      "max_new_evaluations": 7, "total_s": 600}
RECORD_KEYS = ("key", "origin", "parents", "edit_op", "evaluation", "pick_index", "eval_index")
PATH_KEYS = (*RECORD_KEYS, "state", "reason_code", "score")


def _oracle():
    spec = importlib.util.spec_from_file_location("independent_sequence_ga_oracle_t5",
                                                  GA_FIX / "independent_sequence_ga_oracle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ORACLE = _oracle()


def oracle_path(ga: dict, reusable=()) -> dict:
    return ORACLE.run_ga(TINY_SPACE, OBSERVED, list(reusable), ga)


def path(content: dict) -> list[list[tuple]]:
    return [[tuple(entry[key] for key in PATH_KEYS) for entry in g["individuals"]] for g in content["generations"]]


def evaluated(content: dict) -> list[dict]:
    return [e for g in content["generations"] for e in g["individuals"] if e["origin"] != "carried"]


# ----------------------------------------------------------------- world (product HTTP path once, copied per test)
@pytest.fixture(scope="module")
def base(tmp_path_factory):
    for path_ in (docking_bundle.WORKER_PYTHON, docking_bundle.QVINA, SJ.PROJECT_PYTHON):
        assert path_.is_file(), f"pinned environment missing at {path_} (no skip)"
    root = tmp_path_factory.mktemp("m23_base") / "runs"
    return {**real_world(root), "root": root}


def world(base: dict, tmp_path: Path, name: str = "runs") -> tuple[Run, Path]:
    """A fresh runs root holding only the base run's events (events-only reopen; same handles)."""
    root = tmp_path / name
    (root / base["rid"]).mkdir(parents=True)
    shutil.copyfile(base["root"] / base["rid"] / "events.jsonl", root / base["rid"] / "events.jsonl")
    run = new_run(root, run_id=base["rid"], dry_run=False)
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
    return run, root


def raise_limits(run: Run, calls: int = 120, wall: float = 30000) -> None:
    run.update_limits(BudgetLimits(expensive_calls=calls, wall_clock_s=wall), by="test")   # test-only path


def ga_args(base: dict, **ga) -> dict:
    return args_for(base, ga={**GA, **ga}, parameters=dict(DOCK))


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
    published = of(run, job["job_id"], SC.SUMMARY_EVENT)
    assert len(published) == 1, published
    handle = published[0]["summary_handle"]
    assert JobQueue(run).get(job["job_id"])["sequence_ga_summary_handle"] == handle
    return handle, SJ.validated_summary(run, handle)


def attempt_dir(run: Run, job: dict) -> Path:
    job = JobQueue(run).get(job["job_id"])
    return run.run_dir / "jobs" / job["job_id"] / job["attempt_id"]


def no_strays(run: Run) -> None:
    """No worker of this run, no modeling child and no qvina2 under its job directories survives the job."""
    for event in events(run):
        if event["type"] == "job_worker_started" and process_identity.matches(event["pid"], event["start_identity"]):
            assert psutil.Process(event["pid"]).status() == psutil.STATUS_ZOMBIE, "worker survived"
    jobs = str(run.run_dir / "jobs")
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.pid != os.getpid() and proc.cwd().startswith(jobs) and proc.status() != psutil.STATUS_ZOMBIE:
                raise AssertionError(f"stray process {proc.pid} {proc.info['name']} under the job directories")
        except (psutil.Error, OSError):
            continue


def check_rows(run: Run, job: dict, content: dict) -> None:
    """Every row with a model or a result: the stored model validates in full (mutants against the reference row's
    model) and is its key's; every result is the model side's own M18 request; scores are the stored first mode;
    every newly published model was announced once by this job with its result handle."""
    published = {e["key"]: e for e in of(run, job["job_id"], SC.INDIVIDUAL_EVENT)}
    reference = content["reference"]
    reference_model = (None if reference["model_handle"] is None else
                       SJ.validated_set_model(run, reference["model_handle"]))
    rows = [("wild_type", reference)] + [(e["key"], e) for e in evaluated(content)]
    for key, entry in rows:
        if entry["model_handle"] is not None:
            model = SJ.validated_set_model(run, entry["model_handle"], reference_model)
            assert SM.side(model["mutations"]) == (SC.REFERENCE_SIDE if key == "wild_type" else SC.MUTANT_SIDE)
            assert model["mutations"] == ([] if key == "wild_type" else SM.model_mutations(
                SJ.candidate_set(run, content["candidate_set"]), key))
        if entry["result_handle"] is None:
            assert entry["score"] is None
            continue
        result = docking_bundle.validated_result(run, entry["result_handle"])
        assert result["inputs"]["receptor"]["source"]["mutation_model"] == entry["model_handle"]
        assert entry["score"] == (result["modes"][0]["score_kcal_mol"] if result["modes"] else None)
        if entry["evaluation"] == "computed":
            event = published[key]
            assert (event["model_handle"], event["result_handle"]) == (entry["model_handle"], entry["result_handle"])
            assert event["conditions_sha256"] == content["conditions_sha256"]


# ----------------------------------------------------------------- registration, capability, bounds, isolation
def test_registration_capability_and_protocol_timeout_bound(tmp_path, monkeypatch):
    assert JOB_PROTOCOLS[PROTOCOL] == (TOOL, "qvina")
    assert TOOL in JOB_ONLY_TOOLS and TOOL not in api_module.SUPPORTED_TOOLS
    spec = api_module.REGISTRY.specs[TOOL]
    assert spec.cost_class == "expensive" and spec.emits == SC.OUTPUT_KIND and spec.level == "L3"
    assert TOOL in api_module.REGISTRY.unavailable
    assert guardian_module.SEQUENCE_GA == MW / "jobs/sequence_ga_worker.py" == SJ.GA_WORKER
    assert guardian_module.SEQUENCE_GA_ADAPTER == PROTOCOL in guardian_module.MONITORED_ADAPTERS
    assert PROTOCOL in guardian_module.DOCKING_ADAPTERS and PROTOCOL not in guardian_module.PINNED_PYTHON_ADAPTERS
    assert guardian_module.SEQUENCE_GA_OUTPUT_LIMIT == SJ.MAX_END_BYTES == 64 * 1024
    assert SEQUENCE_GA_TIMEOUT_MAX_S == SC.TIMEOUT_MAX_S == 15000
    assert SJ.PROJECT_PYTHON == ROOT / ".venv/bin/python" and SJ.PROJECT_PYTHON.is_symlink()  # the link, unresolved
    for name in ("sequence_ga_jobs.py", "sequence_ga_bundle.py", "sequence_ga_inputs.py", "sequence_ga_constants.py",
                 "sequence_model_bundle.py", "docking_bundle.py", "docking_batch_inputs.py", "jobs/queue.py",
                 "jobs/guardian.py", "api/app.py"):
        tree = ast.parse((MW / name).read_text())
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert not any(m == top or m.startswith(top + ".") for m in imported for top in FORBIDDEN_MODULES), name
    script = ("import sys, mw.api.app, mw.sequence_ga_jobs, mw.jobs.queue; "
              "print([m for m in ('rdkit', 'meeko', 'MDAnalysis', 'pdbfixer') if m in sys.modules])")
    probe = subprocess.run([sys.executable, "-c", script], cwd=MW.parent, capture_output=True, text=True,
                           check=True, timeout=120)
    assert probe.stdout.strip() == "[]"   # a fresh server process (this test process may hold oracle imports)
    capability = SJ.capability()
    assert capability["available"] is True, capability["reason"]
    assert capability["pins"]["docking"] == docking_bundle.capability()["pins"]
    assert capability["pins"]["modules"] == GI.module_pins()
    assert capability["pins"]["model_method"]["multi_mutation"] == "sequential_structure_order_round4"
    assert capability["timeout_s"] == {"max": 15000, "finish_margin": 600}
    assert capability["ga_ranges"]["population_size"] == {"min": 4, "max": 16, "default": 8}
    assert capability["statements"] == SC.STATEMENTS and capability["score_label"] == SC.SCORE_LABEL
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path / "runs")
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    methods = client.get("/capabilities").json()["methods"]
    assert methods["sequence_ga_design"] == capability
    assert TOOL not in {tool["name"] for tool in client.get("/tools", params={"levels": "L3"}).json()}
    for patch_target, value, reason in (
            (docking_bundle, ("QVINA", tmp_path / "missing/qvina2"), "engine_missing"),
            (SJ, ("GA_WORKER", tmp_path / "missing/sequence_ga_worker.py"), "worker_missing"),
            (SJ, ("PROJECT_PYTHON", tmp_path / "missing/python"), "worker_missing")):
        with monkeypatch.context() as patch:   # unavailable: the reason only, no pins, versions, ranges or limits
            patch.setattr(patch_target, *value)
            if patch_target is SJ and value[0] == "GA_WORKER":
                patch.setitem(GI.GA_MODULES, "ga_worker_sha256", value[1])
            down = SJ.capability()
            assert (down["available"], down["reason_code"], down["pins"], down["versions"]) == (
                False, reason, None, None)
            assert "limits" not in down and "ga_ranges" not in down
    with monkeypatch.context() as patch:   # M21 engines first (admission step 5 order)
        patch.setattr(SJ.mmb, "_pdbfixer_version", lambda: "1.11")
        assert SJ.capability()["reason_code"] == "pdbfixer_unavailable"
    with monkeypatch.context() as patch:
        patch.setattr(SJ, "_HANDSHAKE_CACHE", {})
        good = SJ._handshake()
        patch.setattr(SJ, "_handshake", lambda: {**good, "project_python": "/usr/bin/python3"})
        assert SJ.capability()["reason_code"] == "handshake_failed"
    # Protocol-only timeout bound: 15000 s for this protocol (checked with its arguments, no default).
    queue = JobQueue(new_run(tmp_path / "bounds", run_id="run_bounds", dry_run=False))
    for timeout in (15000, 15001, None):
        with pytest.raises(ToolFailure) as refused:
            queue.submit(PROTOCOL, {}, timeout_s=timeout)
        assert refused.value.detail["reason_code"] == "invalid_job_arguments"
    for protocol, timeout in (("qvina_batch_dock_v1", 7801), ("qvina_dock_v1", 901)):
        with pytest.raises(ToolFailure) as refused:
            queue.submit(protocol, {}, timeout_s=timeout)
        assert refused.value.message == "invalid job timeout"
    rid = client.post("/runs", json={"goal": "M23 bounds", "dry_run": False}).json()["run_id"]
    for body in ({"protocol_id": PROTOCOL, "args": {}, "timeout_s": 15001}, {"protocol_id": PROTOCOL, "args": {}}):
        refused = client.post(f"/runs/{rid}/jobs", json=body)
        assert refused.status_code == 422 and refused.json()["detail"]["reason_code"] == "invalid_job_arguments"


def test_admission_order_refusals_record_and_charge_nothing(base, tmp_path, monkeypatch):
    run, _root = world(base, tmp_path)
    queue = JobQueue(run)
    before = events(run)
    far = {"source": "manual", "center_A": [500.0, 500.0, 500.0], "size_A": [20.0, 20.0, 20.0]}
    cases = [
        (ga_args(base, total_s=600), 1199, "invalid_job_arguments"),          # timeout < total_s + 600
        (ga_args(base, elite_count=3), 1200, "invalid_job_arguments"),          # population - elite < 2
        ({**ga_args(base), "mode": "free"}, 1200, "invalid_job_arguments"),     # no mode key
        ({**ga_args(base), "receptor_source": {}}, 1200, "invalid_job_arguments"),
        ({**ga_args(base), "hydrogen_policy": "keep"}, 1200, "confirmation_missing"),
        ({**ga_args(base), "acknowledgement": {}}, 1200, "acknowledgement_missing"),
        ({**ga_args(base), "candidate_set": base["structure"]}, 1200, "candidate_set_invalid"),
        ({**ga_args(base), "ligand": {"source": "sdf", "sdf_handle": base["planar"]}}, 1200, "ligand_not_3d"),
        ({**ga_args(base), "box": {"source": "instance_range"}}, 1200, "box_invalid"),
        ({**ga_args(base), "box": far}, 1200, "box_no_receptor_atoms"),
        ({**ga_args(base), "candidate_set": base["empty"]}, 1200, "ga_space_too_small"),
        (ga_args(base, population_size=16, elite_count=0, max_new_evaluations=64, max_mutations=1), 1200,
         "ga_space_too_small"),
    ]
    for args, timeout, reason in cases:
        with pytest.raises(ToolFailure) as refused:
            queue.submit(PROTOCOL, args, timeout_s=timeout)
        assert refused.value.detail["reason_code"] == reason, (reason, refused.value.detail)
    with monkeypatch.context() as patch:   # 412 before the M7 preflight, after the pure checks
        patch.setattr(SJ.mmb, "_pdbfixer_version", lambda: "1.11")
        with pytest.raises(ToolFailure) as refused:
            queue.submit(PROTOCOL, ga_args(base), timeout_s=1200)
        assert refused.value.cls.value == "precondition" and refused.value.detail["reason_code"] == \
            "pdbfixer_unavailable"
        with pytest.raises(ToolFailure) as refused:   # a step 1-4 refusal is still the 422 first
            queue.submit(PROTOCOL, {**ga_args(base), "ligand": {"source": "sdf", "sdf_handle": base["planar"]}},
                         timeout_s=1200)
        assert refused.value.detail["reason_code"] == "ligand_not_3d"
    with monkeypatch.context() as patch:   # labeled internal hook: the 16 MiB staging bound reached
        patch.setattr(SC, "MAX_STAGED_BYTES", 1000)
        with pytest.raises(ToolFailure) as refused:
            queue.submit(PROTOCOL, ga_args(base), timeout_s=1200)
        assert refused.value.cls.value == "resource_exceeded"
        assert refused.value.detail["reason_code"] == "staged_input_bytes"
    with pytest.raises(ToolFailure) as refused:   # the default run budget is short (spec 7): 429, nothing charged
        queue.submit(PROTOCOL, ga_args(base), timeout_s=1200)
    assert refused.value.cls.value == "resource_exceeded"
    assert refused.value.detail["reason_code"] == "ga_limit_raise_required"
    assert refused.value.detail["needed"] == {"expensive_calls": 16, "wall_clock_s": 1200}
    assert [e for e in events(run)[len(before):] if e["type"] in {"job_submitted", "budget_reserved"}] == []
    # Admitted with a raised budget: the job record is small (no candidate rows, no M18 selection, no projection).
    raise_limits(run)
    admitted = queue.submit(PROTOCOL, ga_args(base, total_s=14400), timeout_s=15000)
    assert admitted["status"] == "queued" and admitted["timeout_s"] == 15000 and admitted["tool_id"] == TOOL
    record = next(e["job"] for e in events(run) if e["type"] == "job_submitted" and
                  e["job"]["job_id"] == admitted["job_id"])
    assert set(record["selected"]) == {"schema", "arguments", "structure", "ligand", "space", "selection_sha256"}
    assert record["selected"]["space"] == {"positions": 3, "candidates": 6, "effective_max_mutations": 3, "size": 26}
    assert "docking_selection@1" not in json.dumps(record) and len(json.dumps(record)) < 16_000
    assert record["method"] == docking_bundle.capability()["pins"]
    assert record["ga_method"] == {"modules": GI.module_pins(), "model_method": SJ.require_ready()["model_method"]}
    assert record["call_key"] == GI.call_key(record["selected"], SJ.job_pins(record))
    assert record["input_handles"] == [base["tiny"], base["structure"], base["phenol"]]
    # The start re-checks the staged bytes with the reuse set of that moment: 429 before any reservation.
    used = run.budget.expensive_calls
    with monkeypatch.context() as patch:
        patch.setattr(SC, "MAX_STAGED_BYTES", 1000)
        with pytest.raises(ToolFailure) as refused:
            queue.start(admitted["job_id"])
        assert refused.value.detail["reason_code"] == "staged_input_bytes"
    assert reserved(run, admitted["job_id"]) == [] and run.budget.expensive_calls == used
    queue.request_cancel(admitted["job_id"])
    # Pinned start: a changed module is worker_version_invalid before any reservation.
    other = queue.submit(PROTOCOL, ga_args(base, total_s=14000), timeout_s=14600)
    assert other["job_id"] != admitted["job_id"] and other["call_key"] != admitted["call_key"]
    with monkeypatch.context() as patch:
        patch.setattr(SJ, "require_ready", lambda: {**SJ.job_pins(record), "modules": {
            **record["ga_method"]["modules"], "ga_worker_sha256": "0" * 64}})
        with pytest.raises(ToolFailure) as refused:
            queue.start(other["job_id"])
        assert refused.value.detail["reason_code"] == "worker_version_invalid"
    assert reserved(run, other["job_id"]) == [] and not of(run, other["job_id"], "job_dispatch_intent")
    assert run.budget.expensive_calls == used
    queue.request_cancel(other["job_id"])


def test_dry_run_plans_only(base, tmp_path, monkeypatch):
    run, _root = world(base, tmp_path, "real")
    args = ga_args(base)
    selection = SJ.submission(run, args, 1200)   # the real selection, computed on the non-dry world
    dry = new_run(tmp_path / "dry", run_id="run_dry_sequence_ga", dry_run=True)
    monkeypatch.setattr(SJ, "submission", lambda _run, _args, _timeout: selection)   # labeled internal hook
    called = []
    monkeypatch.setattr(SJ, "selection", lambda *a: called.append(a))
    plan = JobQueue(dry).submit(PROTOCOL, args, timeout_s=1200)
    assert plan["plan_only"] is True and plan["reason_code"] == "dry_run" and plan["output_handles"] == []
    assert plan["normalized_parameters"] == selection[1] and called == []   # no engine check, no preflight
    assert not any(e["type"] in {"job_submitted", "budget_reserved", "object_created"} for e in events(dry))


# ----------------------------------------------------------------- the product path (real engines)
def test_product_path_publication_m18_identity_reuse_duplicates_and_events_only(base, tmp_path, monkeypatch):
    run, root = world(base, tmp_path)
    rid = base["rid"]
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    raise_limits(run)
    used = run.budget.expensive_calls
    args = ga_args(base)
    expected = oracle_path(GA)
    assert (expected["stop_reason"], expected["new_evaluations_used"]) == ("generations_complete", 7)
    submitted = client.post(f"/runs/{rid}/jobs", json={"protocol_id": PROTOCOL, "args": args, "timeout_s": 1200})
    assert submitted.status_code == 200, submitted.text
    job = submitted.json()
    assert job["status"] == "queued"
    pending = client.post(f"/runs/{rid}/jobs/{job['job_id']}/start")
    assert pending.status_code == 409 and pending.json()["approval"]["tool"] == TOOL   # the first expensive call
    assert client.post(f"/runs/{rid}/jobs/approve").status_code == 200
    done = client.post(f"/runs/{rid}/jobs/{job['job_id']}/start").json()
    assert done["status"] == "done", done
    handle = done["artifacts"]["sequence_ga_result"]
    assert done["output_handles"] == [handle]   # the summary only; rows are reached through it
    run = api_module._run(rid)
    content = SJ.validated_summary(run, handle)
    assert path(content) == path(expected)   # the T1 observed engine scores give the independent oracle's path
    assert (content["status"], content["stop_reason"], content["generations_done"]) == (
        "complete", "generations_complete", 2)
    assert (content["new_evaluations_used"], content["reused_count"], content["reserved_evaluations"],
            content["reserved_units"]) == (7, 0, 7, 16)
    assert content["reference"] == {"evaluation": "computed", "state": "scored", "reason_code": None,
                                    "score": OBSERVED["wild_type"]["score"],
                                    "model_handle": content["reference"]["model_handle"],
                                    "result_handle": content["reference"]["result_handle"]}
    assert content["limitations"] == ["S1", "S4", "S5", "S6"]
    check_rows(run, job, content)
    # reserved_units = 2 x (reserved_evaluations + 1) at the start, never refunded.
    assert reserved(run, job["job_id"]) == [16] and run.budget.expensive_calls == used + 16
    assert done["sequence_ga"] == {"space": {"positions": 3, "candidates": 6, "effective_max_mutations": 3,
                                             "size": 26}, "reserved_evaluations": 7, "reserved_units": 16,
                                   "reused_planned": 0, "reference_reuse_planned": False,
                                   "reference_recorded": True, "individuals_started": 7, "individuals_finished": 7,
                                   "generation_records": 2, "generations_complete": 2, "summary_handle": handle,
                                   "summary_status": "complete", "summary_stop_reason": "generations_complete"}
    # Progress reads write nothing (no event, job or tool).
    raw = (root / rid / "events.jsonl").read_bytes()
    listed = client.get(f"/runs/{rid}/jobs").json()
    polled = client.get(f"/runs/{rid}/jobs/{job['job_id']}").json()
    assert next(item for item in listed if item["job_id"] == job["job_id"])["sequence_ga"] == polled["sequence_ga"] \
        == done["sequence_ga"]
    assert (root / rid / "events.jsonl").read_bytes() == raw
    # Publication order: cleanup < reference row < every individual < summary < candidate < terminal.
    seq = {kind: [e["seq"] for e in of(run, job["job_id"], kind)]
           for kind in ("job_cleanup_verified", SC.INDIVIDUAL_EVENT, SC.SUMMARY_EVENT, "job_result_candidate",
                        "job_terminal")}
    keys = [e["key"] for e in of(run, job["job_id"], SC.INDIVIDUAL_EVENT)]
    assert keys == ["wild_type", *[e["key"] for e in evaluated(content)]]
    assert (seq["job_cleanup_verified"][0] < min(seq[SC.INDIVIDUAL_EVENT]) < max(seq[SC.INDIVIDUAL_EVENT]) <
            seq[SC.SUMMARY_EVENT][0] < seq["job_result_candidate"][0] < seq["job_terminal"][0])
    for event in of(run, job["job_id"], SC.INDIVIDUAL_EVENT):   # mmCIF -> model -> result -> event
        created = {e["handle"]: e["seq"] for e in events(run) if e["type"] == "object_created"}
        model = run.store.load(event["model_handle"])
        (entry,) = model["structures"].values()
        assert created[entry["structure_object"]] < created[event["model_handle"]] < \
            created[event["result_handle"]] < event["seq"]
    # Every docked row = the standalone M18 job on the same receptor_source: handle, call key, worker bytes.
    record = JobQueue(run).get(job["job_id"])
    directory = attempt_dir(run, job)
    rows = [("wild_type", content["reference"], "reference.")] + [
        (e["key"], e, f"individuals/{e['eval_index']}.") for e in evaluated(content)]
    for key, entry, prefix in rows:
        side = SC.REFERENCE_SIDE if key == "wild_type" else SC.MUTANT_SIDE
        request = SJ.m18_request(record["parameters"], entry["model_handle"], side)
        assert GI.individual_arguments(record["parameters"], entry["model_handle"], side) == \
            docking_bundle.docking_inputs.validate_arguments(request)
        single = run_job(run, "qvina_dock_v1", request, timeout_s=600)
        assert single["status"] == "done", single
        assert single["output_handles"] == [entry["result_handle"]], key
        assert single["call_key"] == docking_bundle.call_key(
            GI.individual_arguments(record["parameters"], entry["model_handle"], side), record["method"])
        ga_bytes = json.loads((directory / f"{prefix}result.json").read_bytes())
        single_dir = run.run_dir / "jobs" / single["job_id"] / single["attempt_id"]
        single_bytes = json.loads((single_dir / "result.json").read_bytes())
        for data in (ga_bytes, single_bytes):
            data.pop("job_id"), data.pop("attempt_id")
        assert canonical_json(ga_bytes) == canonical_json(single_bytes), key
        assert docking_bundle.producer(run, entry["result_handle"])["job_id"] == job["job_id"]   # earliest stays
    first = evaluated(content)[1]
    source = docking_bundle.producer(run, first["result_handle"])
    assert source["job"]["protocol_id"] == PROTOCOL and source["key"] == first["key"]
    assert source["job"]["selected"]["schema"] == "docking_selection@1"
    assert docking_reads.result_detail(run, first["result_handle"])["job_id"] == job["job_id"]
    built = build_docking_report(run, first["result_handle"])
    assert built["manifest"]["provenance"]["docking"]["protocol_id"] == PROTOCOL
    index = BI.published_m18_results(run.events.read())
    for key, entry, _prefix in rows:
        side = SC.REFERENCE_SIDE if key == "wild_type" else SC.MUTANT_SIDE
        assert index[docking_bundle.call_key(GI.individual_arguments(record["parameters"], entry["model_handle"],
                                                                     side), record["method"])] == \
            entry["result_handle"]
    # Same request again: the complete job itself (no new job, no charge).
    used = run.budget.expensive_calls
    again = client.post(f"/runs/{rid}/jobs", json={"protocol_id": PROTOCOL, "args": args, "timeout_s": 1300}).json()
    assert again["job_id"] == job["job_id"] and again["output_handles"] == [handle]
    assert run.budget.expensive_calls == used
    # Another GA seed, same evaluation seed: stored rows are reused (no modeling, no docking, no charge for them).
    seen = [e["key"] for e in evaluated(content)]
    second_expected = oracle_path({**GA, "seed": 5, "max_new_evaluations": 4}, reusable=[*seen, "wild_type"])
    assert second_expected["reused_count"] == 4 and second_expected["new_evaluations_used"] == 3
    second = run_ga(run, ga_args(base, seed=5, max_new_evaluations=4))
    assert second["status"] == "done" and second["call_key"] != job["call_key"]
    _, second_content = summary(run, second)
    assert path(second_content) == path(second_expected)
    assert second_content["reference"]["evaluation"] == "reused"
    assert second_content["reference"]["result_handle"] == content["reference"]["result_handle"]
    assert second_content["limitations"] == ["S1", "S3", "S4", "S5", "S6"]
    assert reserved(run, second["job_id"]) == [10]   # 2 x (min(4, 4 + 3) + 1): reuse never lowers it
    second_dir = attempt_dir(run, second)
    assert sorted(p.name for p in second_dir.glob("reference.*")) == ["reference.status.json"]
    assert len(list((second_dir / "individuals").glob("*.started"))) == 3
    assert [e["key"] for e in of(run, second["job_id"], SC.INDIVIDUAL_EVENT)] == [
        e["key"] for e in evaluated(second_content) if e["evaluation"] == "computed"]
    intent = of(run, second["job_id"], "job_dispatch_intent")[0]["sequence_reuse"]
    assert {r["key"] for r in intent["records"]} == set(seen) and intent["reference"]["key"] == "wild_type"
    check_rows(run, second, second_content)
    # A partial run (evaluation_limit) with reuse from both earlier runs; then nothing deduplicates on it.
    both = [*seen, *(e["key"] for e in evaluated(second_content)), "wild_type"]
    third_expected = oracle_path({**GA, "seed": 4, "max_new_evaluations": 4}, reusable=both)
    assert (third_expected["stop_reason"], third_expected["reused_count"]) == ("evaluation_limit", 2)
    third = run_ga(run, ga_args(base, seed=4, max_new_evaluations=4))
    assert third["status"] == "done", third   # the worker ended by itself: done, the summary is partial
    _, third_content = summary(run, third)
    assert path(third_content) == path(third_expected)
    assert (third_content["status"], third_content["stop_reason"], third_content["new_evaluations_used"]) == (
        "partial", "evaluation_limit", 4)
    assert third_content["generations"][-1]["complete"] is False
    assert third_content["limitations"] == ["S1", "S2", "S3", "S4", "S5", "S6"]
    check_rows(run, third, third_content)
    again = run_ga(run, ga_args(base, seed=4, max_new_evaluations=4))   # a partial summary never deduplicates
    assert again["job_id"] != third["job_id"] and again["status"] == "done"
    no_strays(run)

    # Events-only reopen: no staged files, engine, worker or preflight; every new object recovers and validates.
    replay = tmp_path / "events_only"
    (replay / rid).mkdir(parents=True)
    shutil.copyfile(root / rid / "events.jsonl", replay / rid / "events.jsonl")

    def forbidden(*_a, **_k):
        raise AssertionError("events-only reads must not execute scientific work")

    with monkeypatch.context() as patch:
        patch.setattr(docking_bundle, "WORKER_PYTHON", tmp_path / "removed/python")
        patch.setattr(docking_bundle, "QVINA", tmp_path / "removed/qvina2")
        patch.setattr(docking_bundle, "_handshake", forbidden)
        patch.setattr(SJ, "_handshake", forbidden)
        patch.setattr(openmm_method, "preflight", forbidden)
        patch.setattr(JobQueue, "_supervise", forbidden)
        patch.setattr(Run, "call", forbidden)
        recovered = new_run(replay, run_id=rid, dry_run=False)
        with recovered._owner():
            recovered.store.rebuild_from_events()
        assert SJ.validated_summary(recovered, handle) == content
        for kind in (SC.MODEL_KIND, SC.STRUCTURE_OBJECT_KIND, SC.OUTPUT_KIND):
            stored = [e["handle"] for e in events(run) if e["type"] == "object_created" and e["kind"] == kind]
            assert stored
            for item in stored:
                raw = (root / rid / run.store.meta(item)["path"]).read_bytes()
                assert (replay / rid / recovered.store.meta(item)["path"]).read_bytes() == raw
        check_rows(recovered, job, content)
        stored_path = replay / rid / recovered.store.meta(handle)["path"]
        tampered = {**content, "generations": content["generations"][:1], "generations_done": 1}
        stored_path.write_text(json.dumps(tampered))   # labeled fault: a tampered summary
        with pytest.raises(SequenceGaEvidenceError):
            SJ.validated_summary(recovered, handle)
    for wrong in (base["tiny"], first["result_handle"], first["model_handle"], None,
                  f"obj://{rid}/sequence_ga_result/{'1' * 64}"):
        with pytest.raises(SequenceGaEvidenceError):
            SJ.validated_summary(run, wrong)


def test_set_model_receptor_source_needs_publication_evidence(base, tmp_path):
    """A stored mutation_set_model@1 without its sequence GA publication is not an M18 receptor (and not readable),
    while an M21 or unknown handle keeps the M21 path and reasons."""
    run, _root = world(base, tmp_path)
    raise_limits(run)
    # A model stored by hand (labeled fault: no GA attempt published it) is refused everywhere.
    content = {"schema": SC.MODEL_SCHEMA, "note": "SYNTHETIC unpublished"}
    with run._owner(), run._transition():
        stray = run.store.put(SC.MODEL_KIND, SC.MODEL_SCHEMA, content, produced_by="test_unpublished").handle
    request = SJ.m18_request(SJ.submission(run, ga_args(base), 1200)[0]["arguments"], stray, SC.MUTANT_SIDE)
    for handle in (stray, base["tiny"], f"obj://{base['rid']}/mutation_model/{'2' * 64}"):
        with pytest.raises(ToolFailure) as refused:
            JobQueue(run).submit("qvina_dock_v1", {**request, "receptor_source": {
                **request["receptor_source"], "mutation_model": handle}}, timeout_s=600)
        assert refused.value.detail["reason_code"] == "mutation_model_invalid"
    with pytest.raises(SequenceGaEvidenceError):
        SJ.set_model(run, stray)


# ----------------------------------------------------------------- reference row failure, cancel, deadline, kill, restart
def test_a_failed_reference_row_ends_the_run_before_any_individual_with_a_summary(base, tmp_path):
    """The labeled synthetic implicit-H SDF passes the server's partial check; RDKit refuses it in the reference
    row's docking (reference_failed: summary with the reference reason, no generation, reserved units kept)."""
    run, _root = world(base, tmp_path)
    raise_limits(run)
    from ligand_job_fixture import import_file

    sdf = import_file(run, "ligand_sdf", "implicit-h.sdf", IMPLICIT_H)
    box = SJ._admitted(run, SJ.submission(run, ga_args(base), 1200)[0])["box"]
    manual = {"source": "manual", "center_A": box["center_A"], "size_A": [20.0, 20.0, 20.0]}
    used = run.budget.expensive_calls
    failed = run_ga(run, {**ga_args(base), "ligand": {"source": "sdf", "sdf_handle": sdf}, "box": manual})
    assert failed["status"] == "done", failed   # the worker ended by itself: done, the summary is partial
    _, content = summary(run, failed)
    assert (content["status"], content["stop_reason"], content["generations"]) == ("partial", "reference_failed", [])
    reference = content["reference"]
    assert reference["state"] == "failed" and reference["reason_code"].startswith("ligand_")
    assert reference["model_handle"] is not None and reference["result_handle"] is None and reference["score"] is None
    assert content["limitations"] == ["S1", "S2", "S4", "S5", "S6"]
    assert [(e["key"], e["result_handle"]) for e in of(run, failed["job_id"], SC.INDIVIDUAL_EVENT)] == [
        ("wild_type", None)]
    assert reserved(run, failed["job_id"]) == [16] and run.budget.expensive_calls == used + 16   # no refund
    check_rows(run, failed, content)
    no_strays(run)


def when_started(target: str, action) -> object:
    """Wrap _record_control: on STARTED, a thread waits for ``target`` (a path relative to the attempt directory),
    then acts."""
    original = JobQueue._record_control

    def record(self, message, job_id, attempt_id, nonce):
        done = original(self, message, job_id, attempt_id, nonce)
        if message and message.get("kind") == "STARTED":
            marker = self.run.run_dir / "jobs" / job_id / attempt_id / target

            def watch() -> None:
                end = time.monotonic() + 300
                while time.monotonic() < end and not marker.exists():
                    time.sleep(0.02)
                if marker.exists():
                    action(self, job_id, message["pid"])
            threading.Thread(target=watch, daemon=True).start()
        return done

    return record


def test_cancel_mid_run_keeps_published_rows_and_a_partial_summary(base, tmp_path, monkeypatch):
    run, _root = world(base, tmp_path)
    raise_limits(run)
    used = run.budget.expensive_calls
    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_record_control",
                      when_started("individuals/1.started", lambda queue, job_id, _pid: queue.request_cancel(job_id)))
        cancelled = run_ga(run, ga_args(base))
    assert cancelled["status"] == "cancelled" and cancelled["output_handles"] == [], cancelled
    _, content = summary(run, cancelled)
    assert (content["status"], content["stop_reason"], content["generations_done"]) == ("partial", "cancelled", 0)
    assert [e["key"] for e in evaluated(content)] == [oracle_path(GA)["generations"][0]["individuals"][0]["key"]]
    assert content["generations"][0]["complete"] is False and content["limitations"] == ["S1", "S2", "S4", "S5",
                                                                                         "S6"]
    check_rows(run, cancelled, content)
    assert [e["key"] for e in of(run, cancelled["job_id"], SC.INDIVIDUAL_EVENT)] == ["wild_type",
                                                                                   evaluated(content)[0]["key"]]
    assert reserved(run, cancelled["job_id"]) == [16] and run.budget.expensive_calls == used + 16   # no refund
    no_strays(run)


def test_a_cancel_before_the_reference_row_is_recorded_has_no_summary(base, tmp_path, monkeypatch):
    run, _root = world(base, tmp_path)
    raise_limits(run)
    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_record_control",
                      when_started("prepared.json", lambda queue, job_id, _pid: queue.request_cancel(job_id)))
        cancelled = run_ga(run, ga_args(base))
    assert cancelled["status"] == "cancelled" and cancelled["output_handles"] == [], cancelled
    assert not (attempt_dir(run, cancelled) / "reference.status.json").exists()
    assert not of(run, cancelled["job_id"], SC.SUMMARY_EVENT)
    assert not of(run, cancelled["job_id"], SC.INDIVIDUAL_EVENT)
    assert reserved(run, cancelled["job_id"]) == [16]
    assert JobQueue(run).get(cancelled["job_id"]).get("sequence_ga_summary_handle") is None
    no_strays(run)


def test_run_budget_deadline_is_time_exhausted_with_a_partial_summary(base, tmp_path):
    run, _root = world(base, tmp_path)
    raise_limits(run)
    queue = JobQueue(run)
    job = queue.submit(PROTOCOL, ga_args(base), timeout_s=1200)
    run._refresh()
    left = 36.0   # labeled internal fault: a test-only limit update leaves 36 s of run wall time for the attempt
    run.update_limits(BudgetLimits(expensive_calls=120,
                                   wall_clock_s=run.budget.snapshot()["wall_clock_s"]["used"] + left), by="test")
    failed = start(queue, job["job_id"])
    assert failed["status"] == "failed" and failed["failure"] == {"error": "resource_exceeded",
                                                                  "message": "job timeout"}, failed
    _, content = summary(run, failed)
    assert (content["status"], content["stop_reason"]) == ("partial", "time_exhausted")
    assert content["reference"]["state"] == "scored"
    check_rows(run, failed, content)
    progress = SJ.progress(run, JobQueue(run).get(failed["job_id"]))
    assert (progress["summary_status"], progress["summary_stop_reason"]) == ("partial", "time_exhausted")
    assert reserved(run, failed["job_id"]) == [16]
    no_strays(run)


def test_hard_kill_of_the_worker_is_worker_failed_and_has_no_retry(base, tmp_path, monkeypatch):
    run, _root = world(base, tmp_path)
    raise_limits(run)
    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_record_control",
                      when_started("individuals/1.started", lambda _queue, _job_id, pid: os.kill(pid, signal.SIGKILL)))
        failed = run_ga(run, ga_args(base))
    assert failed["status"] == "failed" and failed["output_handles"] == [], failed
    _, content = summary(run, failed)
    assert (content["status"], content["stop_reason"]) == ("partial", "worker_failed")
    assert len(evaluated(content)) == 1 and evaluated(content)[0]["state"] == "scored"
    check_rows(run, failed, content)
    with pytest.raises(ToolFailure) as retry:   # one attempt: a new run is a new job
        JobQueue(run).retry(failed["job_id"])
    assert retry.value.cls.value == "precondition"
    no_strays(run)


DRIVER = r'''
import json, sys
from pathlib import Path
from mw.jobs.queue import JobQueue
from mw.workspace import new_run
root, rid, args = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
run = new_run(root, run_id=rid, dry_run=False)
queue = JobQueue(run)
job = queue.submit("sequence_ga_dock_v1", args, timeout_s=1200)
(root / "job_id").write_text(job["job_id"])
run.approve("expensive_first_call", by="test")
queue.start(job["job_id"])
'''


def test_server_death_recovery_publishes_staged_rows_and_a_worker_failed_summary(base, tmp_path):
    run, root = world(base, tmp_path)
    raise_limits(run)
    rid = base["rid"]
    used = run.budget.expensive_calls
    child = subprocess.Popen([sys.executable, "-c", DRIVER, str(root), rid, json.dumps(ga_args(base))],
                             cwd=MW.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        end = time.monotonic() + 300
        while time.monotonic() < end and not list(root.glob(f"{rid}/jobs/*/*/individuals/1.started")):
            assert child.poll() is None, "the server process ended before individual 1 started"
            time.sleep(0.05)
        assert list(root.glob(f"{rid}/jobs/*/*/individuals/1.started")), "individual 1 never started"
        child.kill()   # the API process dies; the guardian sees EOF and stops its group (the modeling child too)
        child.wait(timeout=10)
        job_id = (root / "job_id").read_text()
        reopened = new_run(root, run_id=rid, dry_run=False)
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
        check_rows(reopened, state, content)
        reopened._refresh()
        assert reserved(reopened, job_id) == [16] and reopened.budget.expensive_calls == used + 16
        assert any(e.get("source") == "orphan_reconciliation" for e in of(reopened, job_id, "job_cleanup_verified"))
        no_strays(reopened)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


# ----------------------------------------------------------------- staged files the worker did not end as recorded
def test_contradicting_staged_files_fail_fatal_or_worker_failed(base, tmp_path, monkeypatch):
    """An end record that miscounts its generations is worker_failed (after every row is published); a prepared box
    that is not the server's is fatal (the job fails, no summary)."""
    run, _root = world(base, tmp_path)
    raise_limits(run)
    end_record = SJ._end_record

    def disagreeing(attempt_dir_, job, attempt_id):   # labeled fault: the end record miscounts its generations
        end = end_record(attempt_dir_, job, attempt_id)
        return None if end is None else {**end, "generations_done": end["generations_done"] + 1}

    small = {"generations": 1, "max_new_evaluations": 4}
    with monkeypatch.context() as patch:
        patch.setattr(SJ, "_end_record", disagreeing)
        miscounted = run_ga(run, ga_args(base, **small))
    _, content = summary(run, miscounted)
    assert (content["status"], content["stop_reason"]) == ("partial", "worker_failed")
    assert path(content) == path(oracle_path({**GA, **small}))
    check_rows(run, miscounted, content)
    original = SJ.finish

    def moved_box(run_, job, attempt_id, attempt_dir_, server_cause):   # labeled fault: another prepared box
        prepared = json.loads((attempt_dir_ / "prepared.json").read_bytes())
        prepared["box"]["center_A"][0] += 1.0
        (attempt_dir_ / "prepared.json").write_bytes(canonical_json(prepared))
        return original(run_, job, attempt_id, attempt_dir_, server_cause)

    with monkeypatch.context() as patch:
        patch.setattr(SJ, "finish", moved_box)
        fatal = run_ga(run, ga_args(base, total_s=900, **small))   # same rows: every one reused, nothing modeled
    assert fatal["status"] == "failed" and fatal["failure"]["diagnostic"] == "SequenceGaFatal", fatal
    assert not of(run, fatal["job_id"], SC.SUMMARY_EVENT)

    def other_receptor(run_, job, attempt_id, attempt_dir_, server_cause):   # labeled fault: another docked receptor
        result = json.loads((attempt_dir_ / "reference.result.json").read_bytes())
        result["inputs"]["receptor"]["sha256"] = "0" * 64
        (attempt_dir_ / "reference.result.json").write_bytes(canonical_json(result))
        return original(run_, job, attempt_id, attempt_dir_, server_cause)

    # Other docking values (new conditions: the reference row is computed); the worker is killed after the reference
    # row (a cancel would make the terminal cancelled whatever finish reports).
    args = {**ga_args(base, **small), "parameters": {**DOCK, "seed": DOCK["seed"] + 1}}
    with monkeypatch.context() as patch:
        patch.setattr(SJ, "finish", other_receptor)
        patch.setattr(JobQueue, "_record_control", when_started(
            "reference.status.json", lambda _queue, _job_id, pid: os.kill(pid, signal.SIGKILL)))
        receptor = run_ga(run, args)
    assert receptor["status"] == "failed" and receptor["failure"]["diagnostic"] == "SequenceGaFatal", receptor
    assert not of(run, receptor["job_id"], SC.SUMMARY_EVENT)
    assert not of(run, receptor["job_id"], SC.INDIVIDUAL_EVENT)   # the reference model is never announced
    no_strays(run)


# ----------------------------------------------------------------- golden M18 / M19 / M21 keys (spec 8, 12)
def test_golden_m18_m19_m21_call_keys_results_and_hashed_files_are_unchanged(tmp_path):
    """The T1 golden record (made before any M23 server change, ``fixtures/sequence_ga/golden_call_keys.json``) is
    rebuilt with the same fixed run id through the unmodified product paths and real engines: every call key, result
    handle, stored byte hash and hashed file SHA-256 is unchanged by the M23 additions."""
    golden = json.loads((GA_FIX / "golden_call_keys.json").read_text())
    spec = importlib.util.spec_from_file_location("prototype_golden_call_keys_t5",
                                                  GA_FIX / "prototype_golden_call_keys.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rebuilt = module.build(tmp_path / "golden")
    assert rebuilt == golden
    for rel, sha in {**golden["hashed_files"], **golden["also_hashed_files"]}.items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == sha, rel
