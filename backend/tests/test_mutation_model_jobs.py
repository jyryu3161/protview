"""M21 T4: the ``openmm_mutation_model_v1`` job lane (registration, admission and unavailability at submission, real
worker processes, approval, budget, cache, publication guards, size limit, events-only recovery, dry-run,
capability).

Jobs run the real worker ``mw/jobs/openmm_mutation_worker.py`` (project ``.venv``: OpenMM 8.6.0, PDBFixer 1.12.0,
FreeSASA 2.2.1) through the product path (upload -> ``load_structure`` -> ``prepare_structure`` ->
``generate_mutation_candidates`` -> POST /jobs -> approve -> start). They FAIL, never skip, when an engine or the
process table is unavailable. Inputs: public 1UBQ (I44; public structure, not experimentally validated here) and
public 1HSG (missing terminal OXT, the M7 preflight refusal). Engine values are checked for shape, closed sets and
consistency only; the numeric oracles are in test_mutation_model_worker.py. Fault injections are labeled and applied
only through internal test hooks (monkeypatched functions), never through request fields. Publication-guard tests
reuse one genuine worker output with a **simulated guardian result** (labeled); the real process lifecycle (success,
timeout, cancellation, cleanup) is covered by the tests that launch the worker.
"""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
import time
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import psutil
import pytest
from fastapi.testclient import TestClient

from mw import mutation_model_bundle as bundle
from mw import mutation_model_constants as K
from mw import mutation_model_math as mm
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.jobs import guardian as guardian_module
from mw.jobs import process_identity
from mw.jobs import queue as queue_module
from mw.jobs.queue import JobQueue
from mw.runtime.orchestrator import Run
from mw.tools import openmm_method
from mw.tools.energetic import JOB_ONLY_TOOLS, JOB_PROTOCOLS
from mw.workspace import new_run

MW = Path(__file__).resolve().parents[1] / "mw"
ROOT = MW.parents[1]
FIX = Path(__file__).parent / "fixtures"
UBQ = (FIX / "public_1ubq.cif").read_bytes()
HSG = (FIX / "public_1hsg.cif").read_bytes()
I44 = {"model_number": 1, "chain_auth": "A", "seq_auth": 44, "icode": "", "resname": "ILE"}
D25 = {"model_number": 1, "chain_auth": "A", "seq_auth": 25, "icode": "", "resname": "ASP"}
ORDER = "ACDEFGHKLMNPQRSTVWY"     # M20 candidate order for I44 (19 candidates, I excluded)
TRP = ORDER.index("W")
ALA = ORDER.index("A")
SEED = 20261004
SIDES = ("wild_type_reference", "mutant")
FORBIDDEN_SERVER_MODULES = ("pdbfixer",)


# ----------------------------------------------------------------- helpers
def _client(root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _command(client: TestClient, rid: str, tool: str, args: dict) -> str:
    response = client.post(f"/runs/{rid}/commands", json={"tool": tool, "args": args})
    assert response.status_code == 200, response.text
    return response.json()["handle"]["handle"]


def _world(client: TestClient, label: str, *, raw: bytes = UBQ, name: str = "public_1ubq.cif",
           residue: dict = I44, dry_run: bool = False) -> dict:
    created = client.post("/runs", json={"goal": label, "dry_run": dry_run})
    assert created.status_code == 201, created.text
    rid = created.json()["run_id"]
    uploaded = client.post(f"/runs/{rid}/uploads", params={"filename": name}, content=raw)
    assert uploaded.status_code in (200, 201), uploaded.text
    source = _command(client, rid, "load_structure", {"source": uploaded.json()["upload_id"], "model_index": 0})
    prepared = _command(client, rid, "prepare_structure", {
        "structure": source, "altloc": "highest_occupancy", "waters": "strip_all", "hydrogens": "strip",
        "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
    candidate_set = _command(client, rid, "generate_mutation_candidates", {
        "structure": prepared, "sources": {"pocket": None, "ligand_shell": None, "residues": [residue]}})
    return {"rid": rid, "source": source, "structure": prepared, "candidate_set": candidate_set}


def _args(candidate_set: str, index: int = TRP, seed: int = SEED, **extra) -> dict:
    return {"candidate_set": candidate_set, "candidate_index": index, "seed": seed,
            "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7", **extra}


def _submit(client: TestClient, rid: str, args: dict, timeout_s: float | None = 120):
    body = {"protocol_id": K.PROTOCOL, "args": args}
    if timeout_s is not None:
        body["timeout_s"] = timeout_s
    return client.post(f"/runs/{rid}/jobs", json=body)


def _approve_start(client: TestClient, rid: str, job_id: str):
    started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    if started.status_code == 409:
        assert started.json()["approval"] == {"gate": "expensive_first_call", "tool": K.TOOL,
                                              "reason": "first expensive call needs approval"}
        approved = client.post(f"/runs/{rid}/jobs/approve")
        assert approved.status_code == 200, approved.text
        started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    return started


def _run_job(client: TestClient, rid: str, args: dict, timeout_s: float = 120) -> dict:
    submitted = _submit(client, rid, args, timeout_s)
    assert submitted.status_code == 200, submitted.text
    job = submitted.json()
    assert job["status"] == "queued" and job["protocol_id"] == K.PROTOCOL, job
    started = _approve_start(client, rid, job["job_id"])
    assert started.status_code == 200, started.text
    return started.json()


def _events(root: Path, rid: str) -> list[dict]:
    return [json.loads(line) for line in (root / rid / "events.jsonl").read_text().splitlines()]


def _used(client: TestClient, rid: str) -> int:
    return client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"]


def _model_objects(root: Path, rid: str) -> list[dict]:
    return [e for e in _events(root, rid) if e["type"] == "object_created" and
            e["kind"] in (K.KIND, bundle.STRUCTURE_OBJECT_KIND)]


def _workers_gone(root: Path, rid: str) -> None:
    for event in _events(root, rid):
        if event["type"] == "job_worker_started":
            try:
                process = psutil.Process(event["pid"])
                assert (process.status() == psutil.STATUS_ZOMBIE or
                        not process_identity.matches(event["pid"], event["start_identity"]))
            except psutil.NoSuchProcess:
                pass


def _kill_leftovers(root: Path, rid: str) -> None:
    """A process left by a failed assertion is killed only when its recorded start identity still matches."""
    for event in _events(root, rid):
        if event["type"] == "job_worker_started" and process_identity.matches(event["pid"], event["start_identity"]):
            try:
                psutil.Process(event["pid"]).kill()
            except psutil.Error:
                pass


def _forbid(*_args, **_kwargs):
    raise AssertionError("this path must not run scientific work or launch a process")


# ----------------------------------------------------------------- one genuine worker run (shared)
@pytest.fixture(scope="module")
def real(tmp_path_factory):
    """The full product path once with the real worker; the genuine ``result.json`` bytes are reused (labeled
    simulated guardian results) by the publication-guard tests."""
    root = tmp_path_factory.mktemp("m21_real") / "runs"
    patch = pytest.MonkeyPatch()
    try:
        patch.setattr(api_module, "RUNS_DIR", root)
        api_module.RUNS.clear()
        client = TestClient(api_module.app, base_url="http://127.0.0.1")
        world = _world(client, "M21 I44W mutation model (public 1UBQ, not experimental validation)")
        rid = world["rid"]
        assert client.post(f"/runs/{rid}/jobs/approve").status_code == 412   # nothing pending yet
        submitted = _submit(client, rid, _args(world["candidate_set"]))
        assert submitted.status_code == 200, submitted.text
        job = submitted.json()
        first = client.post(f"/runs/{rid}/jobs/{job['job_id']}/start")
        assert first.status_code == 409 and first.json()["approval"]["tool"] == K.TOOL
        used_before_approval = _used(client, rid)
        assert client.post(f"/runs/{rid}/jobs/approve").status_code == 200
        try:
            done = client.post(f"/runs/{rid}/jobs/{job['job_id']}/start").json()
        finally:
            _kill_leftovers(root, rid)
        raw = (root / rid / "jobs" / done["job_id"] / done["attempt_id"] / "result.json").read_bytes()
        return {"root": root, "world": world, "submitted": job, "done": done, "raw": raw,
                "used_before_approval": used_before_approval, "used": _used(client, rid)}
    finally:
        patch.undo()
        api_module.RUNS.clear()


# ----------------------------------------------------------------- registration, isolation, capability
def test_registration_dispatch_table_bounds_and_capability(tmp_path, monkeypatch):
    assert JOB_PROTOCOLS[K.PROTOCOL] == (K.TOOL, "openmm")
    assert K.TOOL in JOB_ONLY_TOOLS and K.TOOL not in api_module.SUPPORTED_TOOLS
    assert K.TOOL in api_module.REGISTRY.impls and K.TOOL in api_module.REGISTRY.unavailable
    spec = api_module.REGISTRY.specs[K.TOOL]
    assert spec.cost_class == "expensive" and spec.emits == K.KIND and spec.level == "L3"
    # Code-owned dispatch: fixed worker module in the project interpreter (as M7), monitored, 64 MB output bound.
    assert guardian_module.MUTATION_MODEL_ADAPTER == K.PROTOCOL
    assert guardian_module.MUTATION_MODEL == MW / "jobs/openmm_mutation_worker.py"
    assert K.PROTOCOL not in guardian_module.PINNED_PYTHON_ADAPTERS | guardian_module.DOCKING_ADAPTERS
    assert K.PROTOCOL in guardian_module.MONITORED_ADAPTERS
    assert guardian_module.MUTATION_MODEL_OUTPUT_LIMIT == bundle.OUTPUT_LIMIT == 64_000_000
    assert bundle.WORKER == guardian_module.MUTATION_MODEL
    # Explicit queue time bound 240 s (not the unknown-protocol 900 s) and default 120 s.
    assert queue_module.MUTATION_MODEL_PROTOCOL == K.PROTOCOL
    assert queue_module.MUTATION_TIMEOUT_MAX_S == K.TIMEOUT_MAX_S == 240
    assert queue_module.MUTATION_TIMEOUT_DEFAULT_S == K.TIMEOUT_DEFAULT_S == 120
    capability = bundle.capability()
    assert capability["available"] is True, f"OpenMM 8.6.0 + PDBFixer 1.12.0 must be installed: {capability}"
    assert capability["reason_code"] is None and capability["reason"] is None
    assert capability["versions"]["openmm"] == "8.6.0" and capability["versions"]["pdbfixer"] == "1.12.0"
    assert capability["versions"]["openmm_engine_build"].startswith("8.6.0")
    assert capability["protocol_id"] == K.PROTOCOL and capability["tool_id"] == K.TOOL
    assert capability["timeout_s"] == {"default": 120, "max": 240}
    client = _client(tmp_path / "runs", monkeypatch)
    methods = client.get("/capabilities").json()["methods"]
    assert methods["mutation_model"] == capability
    # Existing methods are unchanged by the new entry.
    assert methods["openmm_protein_minimize"] == openmm_method.capability()


def test_server_process_never_imports_pdbfixer():
    for name in ("mutation_model_bundle.py", "mutation_model_inputs.py", "mutation_model_math.py",
                 "mutation_model_constants.py", "jobs/queue.py", "jobs/guardian.py", "api/app.py",
                 "tools/energetic.py"):
        tree = ast.parse((MW / name).read_text())
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert not any(module == top or module.startswith(top + ".") for module in imported
                       for top in FORBIDDEN_SERVER_MODULES), name
        assert "openmm_mutation_worker" not in " ".join(imported), name
        if name.startswith("mutation_model_"):
            assert not any(module == "openmm" or module.startswith("openmm.") for module in imported), name
    code = ("import sys; import mw.api.app, mw.mutation_model_bundle, mw.jobs.queue; "
            "from mw import mutation_model_bundle as b; assert b.capability()['available']; "
            "print(sorted(m for m in sys.modules if m.split('.')[0] == 'pdbfixer'))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180,
                         cwd=str(MW.parent), check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


# ----------------------------------------------------------------- full product path (real worker)
def test_product_path_approval_budget_result_and_reads(real, monkeypatch):
    root, world, done = real["root"], real["world"], real["done"]
    rid = world["rid"]
    assert real["used_before_approval"] == 0 and real["used"] == 1
    assert done["status"] == "done", done
    assert done["timeout_s"] == 120 and done["cleanup_status"] == "verified"
    assert done["input_handles"] == [world["candidate_set"], world["structure"]]
    handle = done["artifacts"]["mutation_model"]
    assert done["output_handles"] == [handle]
    client = _client(root, monkeypatch)
    run = api_module._run(rid)
    content = bundle.validated_result(run, handle)
    assert content == run.store.load(handle) and mm.validated_model(content) == content
    assert content["schema"] == K.SCHEMA and content["method_version"] == K.METHOD_VERSION
    assert content["candidate"] == {
        "candidate_set": world["candidate_set"], "candidate_index": TRP, "position_index": 0, "from": "I",
        "to": "W", "residue": {**I44, "chain_label": "A", "seq_label": 44}, "mutant_resname": "TRP"}
    assert content["structure"] == {"handle": world["structure"], "model_number": 1,
                                    "structure_kind": "prepared_structure"}
    assert content["parameters"] == {"seed": SEED, "contact_cutoff_A": 4.0, "selection_policy": "protein_only",
                                     "hydrogen_policy": "rebuild_pH7"}
    assert content["method"]["pdbfixer_version"] == "1.12.0" and content["method"]["distribution_version"] == "8.6.0"
    assert content["excluded_components"] == [
        {"reason": "water_removed_during_preparation", "residue_count": 58, "atom_count": 58},
        {"reason": "water", "residue_count": 0, "atom_count": 0},
        {"reason": "nonprotein", "residue_count": 0, "atom_count": 0}]
    assert content["limitations"][:5] == [K.L1, K.L2, K.L3, K.L4, K.L7]
    # The two mmCIF objects: typed, same run, bytes = the recorded SHA-256, readable through the bundle.
    for side in SIDES:
        entry = content["structures"][side]
        meta = run.store.meta(entry["structure_object"])
        assert (meta["kind"], meta["schema"], meta["fmt"]) == (bundle.STRUCTURE_OBJECT_KIND,
                                                              bundle.STRUCTURE_OBJECT_SCHEMA, "cif")
        raw = bundle.structure_bytes(run, handle, side)
        assert raw == run.store.load(entry["structure_object"])
        assert hashlib.sha256(raw).hexdigest() == entry["structure_sha256"] and raw.startswith(b"data_")
    with pytest.raises(bundle.MutationEvidenceError):
        bundle.structure_bytes(run, handle, "both")
    # No time, job or attempt identity in the content: rebuilt from the same worker output -> same bytes.
    text = canonical_json(content).decode()
    assert done["job_id"] not in text and done["attempt_id"] not in text and "job_id" not in text
    job = JobQueue(run).get(done["job_id"])
    assert bundle.model_content(run, job, json.loads(real["raw"]))[0] == content
    # Approval was requested once and resolved by the human route; one reservation.
    events = _events(root, rid)
    assert [e["type"] for e in events if e["type"] in {"approval_requested", "approval_resolved"}] == [
        "approval_requested", "approval_resolved"]
    assert len([e for e in events if e["type"] == "budget_reserved"]) == 1
    assert job["method"] == {"worker_sha256": hashlib.sha256(bundle.WORKER.read_bytes()).hexdigest(),
                             "method": content["method"]}
    _workers_gone(root, rid)
    # Reads never write events.
    before = (root / rid / "events.jsonl").read_bytes()
    bundle.validated_result(run, handle)
    client.get(f"/runs/{rid}/jobs/{done['job_id']}")
    assert (root / rid / "events.jsonl").read_bytes() == before


def test_same_input_same_job_and_handle_other_seed_new_key(real, monkeypatch):
    root, world, done = real["root"], real["world"], real["done"]
    rid = world["rid"]
    client = _client(root, monkeypatch)
    used = _used(client, rid)
    # Spelled-out default cutoff, an int cutoff and another timeout (not in the call key) -> the stored job.
    for args, timeout_s in ((_args(world["candidate_set"]), 120),
                            (_args(world["candidate_set"], contact_cutoff_A=4.0), 200),
                            (_args(world["candidate_set"], contact_cutoff_A=4), None)):
        again = _submit(client, rid, args, timeout_s)
        assert again.status_code == 200, again.text
        assert again.json()["job_id"] == done["job_id"] and again.json()["output_handles"] == done["output_handles"]
        assert again.json()["call_key"] == done["call_key"]
    # Another seed, another cutoff or another candidate is another call key (queued; nothing charged).
    keys = {done["call_key"]}
    for args in (_args(world["candidate_set"], seed=SEED + 1), _args(world["candidate_set"], contact_cutoff_A=6.0),
                 _args(world["candidate_set"], index=ALA)):
        other = _submit(client, rid, args).json()
        assert other["status"] == "queued" and other["call_key"] not in keys, other
        keys.add(other["call_key"])
    assert _used(client, rid) == used
    # The call key binds the normalized arguments, the worker SHA-256 and the fixed method record.
    run = api_module._run(rid)
    job = JobQueue(run).get(done["job_id"])
    assert bundle.call_key(job["parameters"], job["method"]) == done["call_key"]
    assert bundle.call_key(job["parameters"], {**job["method"], "worker_sha256": "0" * 64}) != done["call_key"]
    assert job["parameters"] == {"candidate_set": world["candidate_set"], "candidate_index": TRP, "seed": SEED,
                                 "contact_cutoff_A": 4.0, "selection_policy": "protein_only",
                                 "hydrogen_policy": "rebuild_pH7"}


def test_events_only_recovery_without_engines_or_processes(real, tmp_path, monkeypatch):
    root, world, done = real["root"], real["world"], real["done"]
    rid = world["rid"]
    handle = done["output_handles"][0]
    original = new_run(root, run_id=rid, dry_run=False)
    content = bundle.validated_result(original, handle)
    cifs = {side: bundle.structure_bytes(original, handle, side) for side in SIDES}
    before = (root / rid / "events.jsonl").read_bytes()
    replay = tmp_path / "events_only"
    (replay / rid).mkdir(parents=True)
    (replay / rid / "events.jsonl").write_bytes(before)
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "openmm", None)       # labeled: engines cannot be imported
        patch.setitem(sys.modules, "pdbfixer", None)
        patch.setattr(openmm_method, "dependencies", _forbid)
        patch.setattr(openmm_method, "preflight", _forbid)
        patch.setattr(bundle, "require_ready", _forbid)
        patch.setattr(bundle, "stage", _forbid)
        patch.setattr(JobQueue, "_supervise", _forbid)
        patch.setattr(subprocess, "Popen", _forbid)
        patch.setattr(Run, "call", _forbid)
        recovered = new_run(replay, run_id=rid, dry_run=False)
        assert bundle.validated_result(recovered, handle) == content
        for side in SIDES:
            assert bundle.structure_bytes(recovered, handle, side) == cifs[side]
            path = replay / rid / recovered.store.meta(content["structures"][side]["structure_object"])["path"]
            assert path.read_bytes() == cifs[side]
        assert JobQueue(recovered).get(done["job_id"])["status"] == "done"
        assert (replay / rid / "events.jsonl").read_bytes() == before
        # A tampered recovered object never reads.
        path = replay / rid / recovered.store.meta(handle)["path"]
        path.write_text(json.dumps({**content, "limitations": content["limitations"][:-1]}))
        with pytest.raises(bundle.MutationEvidenceError):
            bundle.validated_result(recovered, handle)


def test_read_validation_refuses_wrong_handles_and_changed_bytes(real, tmp_path):
    root, world, done = real["root"], real["world"], real["done"]
    rid = world["rid"]
    run = new_run(root, run_id=rid, dry_run=False)
    handle = done["output_handles"][0]
    content = bundle.validated_result(run, handle)
    for wrong in (world["structure"], world["candidate_set"], content["structures"]["mutant"]["structure_object"],
                  None, f"obj://{rid}/{K.KIND}/{'1' * 64}", f"obj://run_other/{K.KIND}/{'1' * 64}"):
        with pytest.raises(bundle.MutationEvidenceError):
            bundle.validated_result(run, wrong)
    # A copy of the run (events only) for the forgeries, so the shared run stays untouched.
    copy_root = tmp_path / "copy"
    (copy_root / rid).mkdir(parents=True)
    (copy_root / rid / "events.jsonl").write_bytes((root / rid / "events.jsonl").read_bytes())
    copied = new_run(copy_root, run_id=rid, dry_run=False)
    # A forged object with the right kind but no completed publication never reads.
    forged = copied.store.put(K.KIND, K.SCHEMA, {**content, "parameters": {**content["parameters"], "seed": 7}})
    with pytest.raises(bundle.MutationEvidenceError):
        bundle.validated_result(copied, forged.handle)
    # A changed structure object file is refused (the recorded SHA-256 binds the stored bytes).
    side_handle = content["structures"]["wild_type_reference"]["structure_object"]
    (copy_root / rid / copied.store.meta(side_handle)["path"]).write_bytes(b"data_changed\n")
    with pytest.raises(bundle.MutationEvidenceError):
        bundle.structure_bytes(copied, handle, "wild_type_reference")
    with pytest.raises(bundle.MutationEvidenceError):
        bundle.validated_result(copied, handle)


# ----------------------------------------------------------------- dry-run, unavailability, admission
def test_dry_run_plans_only_as_m7(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    world = _world(client, "M21 dry run", dry_run=True)
    run = api_module._run(world["rid"])
    assert run.dry_run is True
    with monkeypatch.context() as patch:   # as M7: the plan is returned before the engine preflight
        patch.setattr(openmm_method, "preflight", _forbid)
        patch.setattr(bundle, "require_ready", _forbid)
        plan = JobQueue(run).submit(K.PROTOCOL, _args(world["candidate_set"]), timeout_s=120)
    assert plan["plan_only"] is True and plan["reason_code"] == "dry_run" and plan["output_handles"] == []
    assert plan["normalized_parameters"] == {"candidate_set": world["candidate_set"], "candidate_index": TRP,
                                             "seed": SEED, "contact_cutoff_A": 4.0,
                                             "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}
    over = _submit(client, world["rid"], _args(world["candidate_set"], extra=1))
    assert over.status_code == 422 and over.json()["detail"]["reason_code"] == "unknown_field"
    events = _events(root, world["rid"])
    assert not any(e["type"] in {"job_submitted", "budget_reserved"} for e in events)
    assert not any(e["type"] == "object_created" and e["kind"] == K.KIND for e in events)


def test_unavailable_engine_pdbfixer_or_identity_is_412_without_reservation(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    world = _world(client, "M21 unavailable")
    rid = world["rid"]

    def missing_pdbfixer():
        raise PackageNotFoundError("pdbfixer")

    def unsupported():
        raise process_identity.IdentityUnavailable("labeled fixture: unsupported raw process identity")

    states = {
        "openmm_unavailable": lambda patch: patch.setitem(sys.modules, "openmm", None),
        "pdbfixer_unavailable": lambda patch: patch.setattr(bundle, "_pdbfixer_version", missing_pdbfixer),
        "pdbfixer_version": lambda patch: patch.setattr(bundle, "_pdbfixer_version", lambda: "1.11"),
        "process_identity_unavailable": lambda patch: patch.setattr(openmm_method, "supported", unsupported),
    }
    for ordinal, (name, apply) in enumerate(states.items()):
        expected = "pdbfixer_unavailable" if name == "pdbfixer_version" else name
        # A job queued while everything was available cannot start once the engine is gone (one job per state:
        # a refused start leaves the job claimed).
        queued = _submit(client, rid, _args(world["candidate_set"], seed=ordinal)).json()
        assert queued["status"] == "queued"
        with monkeypatch.context() as patch:
            apply(patch)
            if expected == "process_identity_unavailable":
                patch.setattr(queue_module, "supported", unsupported)
            patch.setattr(JobQueue, "_supervise", _forbid)
            capability = client.get("/capabilities").json()["methods"]["mutation_model"]
            assert capability["available"] is False and capability["reason_code"] == expected, capability
            assert capability["reason"] == bundle.REASONS[expected] and capability["versions"] is None
            refused = _submit(client, rid, _args(world["candidate_set"], seed=SEED + 50))
            assert refused.status_code == 412, refused.text
            assert refused.json()["detail"]["reason_code"] == expected
            blocked = _approve_start(client, rid, queued["job_id"])
            assert blocked.status_code == 412 and blocked.json()["detail"]["reason_code"] == expected
    events = _events(root, rid)
    assert _used(client, rid) == 0
    assert not any(e["type"] in {"budget_reserved", "job_dispatch_intent"} for e in events)
    assert len([e for e in events if e["type"] == "job_submitted"]) == len(states)
    assert bundle.capability()["available"] is True


def test_every_admission_reason_reaches_the_api_as_422_without_a_job(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    world = _world(client, "M21 admission")
    other = _world(client, "M21 other run")
    hsg = _world(client, "M21 1HSG (public, missing OXT)", raw=HSG, name="public_1hsg.cif", residue=D25)
    rid, cset = world["rid"], world["candidate_set"]

    def refused(args, reason, *, run_id=rid, timeout_s=120, **detail):
        response = _submit(client, run_id, args, timeout_s)
        assert response.status_code == 422, (reason, response.text)
        body = response.json()["detail"]
        assert body["reason_code"] == reason, (reason, body)
        for key, value in detail.items():
            assert body[key] == value, (key, body)
        return body

    refused({**_args(cset), "argv": ["x"]}, "unknown_field")
    refused({**_args(cset), "structure": world["structure"]}, "unknown_field")
    refused(_args(cset, selection_policy="all"), "confirmation_missing")
    refused({k: v for k, v in _args(cset).items() if k != "hydrogen_policy"}, "confirmation_missing")
    for bad in ({"seed": True}, {"seed": -1}, {"candidate_index": 1.0}, {"contact_cutoff_A": 6.5},
                {"contact_cutoff_A": "4"}):
        refused(_args(cset, **bad), "argument_invalid")
    for timeout_s in (241, 900, 7800):   # inside the wider JobSubmit model bound; the queue bound is 240
        refused(_args(cset), "argument_invalid", timeout_s=timeout_s)
    for timeout_s in (0, -1, float("nan"), True):   # the API model refuses these before the queue; the queue too
        with pytest.raises(queue_module.ToolFailure) as caught:
            JobQueue(api_module._run(rid)).submit(K.PROTOCOL, _args(cset), timeout_s=timeout_s)
        assert caught.value.detail["reason_code"] == "argument_invalid"
    for wrong in (world["structure"], other["candidate_set"], "obj://nope", f"obj://{rid}/mutation_candidate_set/"
                  + "0" * 64):
        refused(_args(wrong), "candidate_set_invalid")
    refused(_args(cset, index=19), "candidate_unknown")
    # Labeled fault injections for the two checks a product path cannot reach (store metadata / residue listing).
    with monkeypatch.context() as patch:
        real_meta = bundle._meta
        patch.setattr(bundle, "_meta", lambda run, h: None if h == world["structure"] else real_meta(run, h))
        refused(_args(cset), "structure_invalid")
    with monkeypatch.context() as patch:
        patch.setattr(bundle, "_residues", lambda run, h: [])
        refused(_args(cset), "residue_mismatch")
    # The M7 preflight: 1HSG lacks the terminal OXT (no repair); the 6,000-atom limit is also a 422.
    body = refused(_args(hsg["candidate_set"], index=0), "openmm_preflight_failed", run_id=hsg["rid"],
                   m7_reason="missing_terminal_oxt")
    assert isinstance(body["m7_message"], str) and body["m7_message"]
    with monkeypatch.context() as patch:
        patch.setattr(openmm_method, "ATOM_CAP", 100)   # labeled internal hook: the M7 atom limit lowered
        refused(_args(cset), "openmm_preflight_failed", m7_reason=None)
    for run_id in (rid, hsg["rid"]):
        events = _events(root, run_id)
        assert not any(e["type"] in {"job_submitted", "budget_reserved"} for e in events)
        assert _used(client, run_id) == 0
    assert set(K.ADMISSION_REASON_CODES) == {"unknown_field", "confirmation_missing", "argument_invalid",
                                             "candidate_set_invalid", "candidate_unknown", "structure_invalid",
                                             "residue_mismatch", "openmm_preflight_failed"}


def test_default_timeout_is_120_when_the_field_is_absent(tmp_path, monkeypatch):
    client = _client(tmp_path / "runs", monkeypatch)
    world = _world(client, "M21 default timeout")
    job = _submit(client, world["rid"], _args(world["candidate_set"]), timeout_s=None).json()
    assert job["status"] == "queued" and job["timeout_s"] == 120
    run = api_module._run(world["rid"])
    assert JobQueue(run).submit(K.PROTOCOL, _args(world["candidate_set"], seed=1))["timeout_s"] == 120
    assert JobQueue(run).submit(K.PROTOCOL, _args(world["candidate_set"], seed=2), timeout_s=240)["timeout_s"] == 240


# ----------------------------------------------------------------- real worker: timeout and cancellation
def test_timeout_and_cancel_publish_nothing_and_charge_once(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    world = _world(client, "M21 timeout and cancel")
    rid = world["rid"]
    original = JobQueue._record_control
    started_pids: list[int] = []

    def cancel_on_start(self, message, job_id, attempt_id, nonce):
        done = original(self, message, job_id, attempt_id, nonce)
        if message and message.get("kind") == "STARTED":
            started_pids.append(message["pid"])
            time.sleep(1.0)       # the worker is inside OpenMM/PDBFixer now
            self.request_cancel(job_id)
        return done

    try:
        with monkeypatch.context() as patch:
            patch.setattr(JobQueue, "_record_control", cancel_on_start)
            cancelled = _run_job(client, rid, _args(world["candidate_set"], seed=1))
        assert cancelled["status"] == "cancelled" and cancelled["output_handles"] == [], cancelled
        assert cancelled["cleanup_status"] == "verified" and _used(client, rid) == 1
        assert started_pids
        timed_out = _run_job(client, rid, _args(world["candidate_set"], seed=2), timeout_s=3)
        assert timed_out["status"] == "failed" and timed_out["output_handles"] == []
        assert timed_out["failure"]["error"] == "resource_exceeded" and timed_out["failure"]["message"] == "job timeout"
        assert timed_out["cleanup_status"] == "verified" and _used(client, rid) == 2
        assert any(e["type"] == "job_worker_started" and e["job_id"] == timed_out["job_id"]
                   for e in _events(root, rid))
        assert _model_objects(root, rid) == []
        time.sleep(0.1)
        _workers_gone(root, rid)
        reserved = [e for e in _events(root, rid) if e["type"] == "budget_reserved"]
        assert [e["root_call_id"] for e in reserved] == [cancelled["job_id"], timed_out["job_id"]]
    finally:
        _kill_leftovers(root, rid)


# ----------------------------------------------------------------- publication guards (simulated guardian result)
def _simulated(raw: bytes | None = None, *, error: dict | None = None, returncode: int = 0):
    """Labeled simulated guardian: writes the genuine worker output (or an error envelope) into the attempt
    directory and reports a clean RESULT without launching any process."""
    def supervise(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch):
        payload = None
        if raw is not None:
            (attempt_dir / "result.json").write_bytes(raw)
            payload = {"output_sha256": hashlib.sha256(raw).hexdigest(), "output_bytes": len(raw)}
        if error is not None:
            (attempt_dir / "error.json").write_text(json.dumps(error))
        return {"kind": "RESULT", "reason": "completed", "returncode": returncode, "clean": True,
                "direct_child_reaped": True, "unexpected_members": False, "payload": payload}, None
    return supervise


def _tampered(raw: bytes, mutate) -> bytes:
    data = json.loads(raw)
    mutate(data)
    return json.dumps(data, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def test_genuine_output_through_a_simulated_guardian_publishes_the_same_handle(real, tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    world = _world(client, "M21 simulated guardian")
    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_supervise", _simulated(real["raw"]))
        done = _run_job(client, world["rid"], _args(world["candidate_set"]))
    assert done["status"] == "done", done
    run = api_module._run(world["rid"])
    content = bundle.validated_result(run, done["output_handles"][0])
    reference = new_run(real["root"], run_id=real["world"]["rid"], dry_run=False).store.load(
        real["done"]["output_handles"][0])
    # Same worker output, another run: identical content apart from the run-scoped handles.
    for side in SIDES:
        content["structures"][side].pop("structure_object")
        reference["structures"][side].pop("structure_object")
    content["candidate"].pop("candidate_set")
    reference["candidate"].pop("candidate_set")
    content["structure"].pop("handle")
    reference["structure"].pop("handle")
    assert content == reference


def test_tampered_output_typed_errors_size_limit_and_late_cancel_publish_nothing(real, tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    world = _world(client, "M21 publication guards")
    rid, cset = world["rid"], world["candidate_set"]
    raw = real["raw"]
    seed = iter(range(1, 100))

    def run_with(supervise, **limits) -> dict:
        with monkeypatch.context() as patch:
            patch.setattr(JobQueue, "_supervise", supervise)
            for name, value in limits.items():
                patch.setattr(bundle, name, value)
            return _run_job(client, rid, _args(cset, seed=next(seed)))

    # Each fault alone makes the genuine output unpublishable (seeds only make distinct call keys; the run's budget
    # of 8 expensive calls bounds the number of charged attempts in this test).
    faults = [
        lambda d: d["structures"]["mutant"]["contacts"]["rows"].pop(),
        lambda d: d["structure_cifs"].update(mutant=d["structure_cifs"]["mutant"] + "#"),
        lambda d: d["method"].update(engine_build="8.6.0.forged"),
        lambda d: d["structures"]["wild_type_reference"]["atom_mapping"][0].update(atom_name="CA"),
        lambda d: d.update(extra=1),
    ]
    for fault in faults:
        failed = run_with(_simulated(_tampered(raw, fault)))
        assert failed["status"] == "failed" and failed["failure"]["message"] == "invalid scientific output", failed
    # Typed worker refusal envelope -> a charged typed failure with the closed reason.
    failed = run_with(_simulated(error={"reason_code": "mutation_modeling_failed", "message": "labeled fixture",
                                        "detail": {"reason_code": "mutation_modeling_failed"}}, returncode=1))
    assert failed["status"] == "failed" and failed["failure"]["reason_code"] == "mutation_modeling_failed"
    assert failed["failure"]["detail"]["reason_code"] == "mutation_modeling_failed"
    assert _model_objects(root, rid) == []
    used = _used(client, rid)
    assert used == len(faults) + 1

    # Size bound: the stored object over its bound is resource_exceeded, never truncated, nothing stored.
    job_args = _args(cset, seed=SEED)
    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_supervise", _simulated(raw))
        patch.setattr(bundle, "MAX_MODEL_BYTES", 10_000)     # labeled internal hook: bound lowered
        failed = _run_job(client, rid, job_args)
    assert failed["status"] == "failed" and failed["output_handles"] == []
    assert (failed["failure"]["error"], failed["failure"]["reason_code"]) == ("resource_exceeded",
                                                                            "resource_exceeded")
    assert _model_objects(root, rid) == [] and _used(client, rid) == used + 1

    # Cancellation accepted after the worker finished -> cancelled, nothing published (retry of the same job).
    def cancel_after(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch):
        result = _simulated(raw)(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch)
        self.request_cancel(job["job_id"])
        return result

    retried = client.post(f"/runs/{rid}/jobs/{failed['job_id']}/retry")
    assert retried.status_code == 200, retried.text
    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_supervise", cancel_after)
        cancelled = client.post(f"/runs/{rid}/jobs/{failed['job_id']}/start").json()
    assert cancelled["status"] == "cancelled" and _model_objects(root, rid) == []
    assert _used(client, rid) == used + 2

    # The same genuine output for its own input publishes (the guards above were the only refusals).
    other = _world(client, "M21 publication guards: genuine")
    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_supervise", _simulated(raw))
        done = _run_job(client, other["rid"], _args(other["candidate_set"]))
    assert done["status"] == "done", done


def test_worker_error_envelope_is_closed(tmp_path):
    def read(value) -> dict:
        path = tmp_path / "error.json"
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        return bundle.worker_error(tmp_path)

    good = {"reason_code": "coordinates_changed", "message": "moved",
            "detail": {"reason_code": "coordinates_changed", "max_abs_shift_A": 0.2}}
    assert read(good) == {"error": "input_invalid", "reason_code": "coordinates_changed", "message": "moved",
                          "detail": good["detail"]}
    assert read({**good, "reason_code": "resource_exceeded", "detail": {"reason_code": "resource_exceeded"}})[
        "error"] == "resource_exceeded"
    assert read({**good, "reason_code": "engine_failed", "detail": {"reason_code": "engine_failed"}})[
        "error"] == "fatal"
    fatal = {"error": "fatal", "message": "worker exit or invalid mutation-model error envelope"}
    for bad in ({**good, "reason_code": "not_a_reason"}, {**good, "extra": 1}, {**good, "message": ""},
                {**good, "detail": []}, {**good, "detail": {"reason_code": "engine_failed"}}, b"{not json",
                {**good, "message": "x" * 400}):
        assert read(bad) == fatal, bad
    (tmp_path / "error.json").unlink()
    assert bundle.worker_error(tmp_path) == fatal
