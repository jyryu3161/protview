"""M18 T5: the qvina docking job lane (registration, admission, real worker processes, budget, cache, failures,
publication guards, events-only recovery, dry-run, capability).

Jobs run the real docking worker (``.deps/docking/venv-locked`` + ``.deps/qvina/env/bin/qvina2``) through the product
path (chemical imports -> POST /jobs -> approve -> start). They FAIL, never skip, when an environment is absent. The
server test process never imports RDKit, Meeko or MDAnalysis. Inputs are the labeled public-derived/synthetic
fixtures in ``fixtures/docking`` and the public ProLIF example receptor in ``fixtures/chemical`` (a public prepared
docking example, not experimental validation). Engine values are only checked for shape, closed sets and
consistency (the numeric oracle is test_docking_worker.py); fault injections are labeled and applied only through
internal test hooks, never through request fields. Docking runs use small boxes and exhaustiveness 1 for time.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest
from fastapi.testclient import TestClient
from ligand_job_fixture import import_file, new_ligand_run

from mw import docking_bundle, docking_inputs
from mw import docking_constants as C
from mw.api import app as api_module
from mw.jobs import guardian as guardian_module
from mw.jobs import process_identity
from mw.jobs.queue import JobQueue
from mw.runtime.orchestrator import Run
from mw.tools.energetic import JOB_ONLY_TOOLS, JOB_PROTOCOLS

MW = Path(__file__).resolve().parents[1] / "mw"
ROOT = MW.parents[1]
CHEM = Path(__file__).parent / "fixtures/chemical"
FIX = Path(__file__).parent / "fixtures/docking"
EXPECTED = json.loads((FIX / "expected.json").read_text())
REC = (CHEM / "prolif-vina-rec.pdb").read_bytes()
PARENT = (FIX / "public-derived-parent-record0.sdf").read_bytes()
PLANAR = (FIX / "synthetic-ligand-planar-z0.sdf").read_bytes()
BLOCKS = (FIX / "synthetic-docking-blocks.smi").read_bytes()
CANDIDATE_ID = EXPECTED["m17_candidate"]["fixed_candidate_id"]
INSTANCE = EXPECTED["receptor_fixtures"]["instance"]
CENTER = EXPECTED["public_example_box"]["center_A"]
SMALL_BOX = {"source": "manual", "center_A": CENTER, "size_A": [12.0, 12.0, 12.0]}
ACK = {key: True for key in C.ACKNOWLEDGEMENT_KEYS}
FORBIDDEN_MODULES = ("rdkit", "meeko", "MDAnalysis")
RESULT_KEYS = {"schema", "protocol", "method", "input_sha256", "inputs", "box", "parameters", "engine", "preparation",
               "modes", "counts", "limitations"}


# ----------------------------------------------------------------- helpers
def _client(root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _new_run(client: TestClient, goal: str) -> str:
    created = client.post("/runs", json={"goal": goal, "dry_run": False})
    assert created.status_code == 201, created.text
    return created.json()["run_id"]


def _import(client: TestClient, rid: str, kind: str, filename: str, raw: bytes) -> str:
    response = client.post(f"/runs/{rid}/chemical/imports", params={"kind": kind, "filename": filename},
                           content=raw, headers={"content-type": "application/octet-stream"})
    assert response.status_code == 201, response.text
    return response.json()["handle"]


def _submit(client: TestClient, rid: str, args: dict, timeout_s: float = 600, protocol: str = "qvina_dock_v1"):
    return client.post(f"/runs/{rid}/jobs", json={"protocol_id": protocol, "args": args, "timeout_s": timeout_s})


def _approve_start(client: TestClient, rid: str, job_id: str, tool: str = "qvina_dock_ligand"):
    started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    if started.status_code == 409:
        assert started.json()["approval"] == {"gate": "expensive_first_call", "tool": tool,
                                              "reason": "first expensive call needs approval"}
        approved = client.post(f"/runs/{rid}/jobs/approve")
        assert approved.status_code == 200, approved.text
        started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    return started


def _run_job(client: TestClient, rid: str, args: dict, timeout_s: float = 600,
             protocol: str = "qvina_dock_v1") -> dict:
    submitted = _submit(client, rid, args, timeout_s, protocol)
    assert submitted.status_code == 200, submitted.text
    job = submitted.json()
    assert job["status"] == "queued" and job["protocol_id"] == protocol, job
    tool = JOB_PROTOCOLS[protocol][0]
    started = _approve_start(client, rid, job["job_id"], tool)
    assert started.status_code == 200, started.text
    return started.json()


def _events(root: Path, rid: str) -> list[dict]:
    return [json.loads(line) for line in (root / rid / "events.jsonl").read_text().splitlines()]


def _used(client: TestClient, rid: str) -> int:
    return client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"]


def _docking_objects(root: Path, rid: str) -> list[dict]:
    return [e for e in _events(root, rid) if e["type"] == "object_created" and e["kind"] == "docking_result"]


def _workers_gone(root: Path, rid: str) -> None:
    for event in _events(root, rid):
        if event["type"] == "job_worker_started":
            try:
                process = psutil.Process(event["pid"])
                assert process.status() == psutil.STATUS_ZOMBIE or not process.is_running()
            except psutil.NoSuchProcess:
                pass


def _args(receptor: str, ligand: dict, *, mode: str = "free", box: dict | None = None, seed: int = 1,
          instance: dict | None = None, params: dict | None = None, ack: dict | None = None,
          connectivity: dict | None = None) -> dict:
    out = {"receptor_handle": receptor, "receptor_model_number": 1,
           "connectivity": connectivity or {"kind": "pdb_conect", "sidecar_handle": None},
           "receptor_instance": instance, "ligand": ligand, "mode": mode, "box": box or SMALL_BOX,
           "parameters": params or {"seed": seed, "exhaustiveness": 1, "num_modes": 2},
           "acknowledgement": ACK if ack is None else ack}
    return out


def _sdf_ligand(handle: str) -> dict:
    return {"source": "sdf", "sdf_handle": handle}


def _strip_hydrogens(raw: bytes) -> bytes:
    """Labeled synthetic negative: the public receptor with every H atom and every CONECT reference to it removed."""
    lines = raw.decode().splitlines()
    removed = {int(line[6:11]) for line in lines if line.startswith(("ATOM", "HETATM")) and
               line[76:78].strip() == "H"}
    out = []
    for line in lines:
        if line.startswith(("ATOM", "HETATM")) and int(line[6:11]) in removed:
            continue
        if line.startswith("CONECT"):
            serials = [int(line[i:i + 5]) for i in range(6, len(line), 5) if line[i:i + 5].strip()]
            if serials[0] in removed:
                continue
            kept = [s for s in serials[1:] if s not in removed]
            if not kept:
                continue
            line = "CONECT" + "".join(f"{s:5d}" for s in [serials[0], *kept])
        out.append(line)
    return ("\n".join(out) + "\n").encode()


def _candidate_set(client: TestClient, rid: str, parent: str) -> str:
    """Real M17 jobs (unmodified worker): inspect the public-derived parent, then the fixed N-methyl replacement."""
    blocks = _import(client, rid, "building_blocks_smiles", "blocks.smi", BLOCKS)
    inspected = _run_job(client, rid, {"parent_sdf_handle": parent, "block_handles": [blocks]}, 120,
                         "rdkit_inspect_v1")
    assert inspected["status"] == "done", inspected
    enumerated = _run_job(client, rid, {"inspection_handle": inspected["output_handles"][0], "site_atoms": [22],
                                        "use_fixed": True}, 120, "rdkit_enumerate_v1")
    assert enumerated["status"] == "done", enumerated
    return enumerated["output_handles"][0]


def _check_spec_keys(content: dict) -> None:
    assert set(content) == RESULT_KEYS
    assert set(content["inputs"]) == {"receptor", "ligand", "mode"}
    assert set(content["inputs"]["receptor"]) == {"handle", "sha256", "model_number", "connectivity",
                                                  "removed_instance", "acknowledgement"}
    assert set(content["inputs"]["ligand"]) == {"source", "sdf_handle", "sdf_sha256", "candidate_set_handle",
                                                "candidate_id", "parent_sdf_handle", "parent_sdf_sha256",
                                                "generated", "stereo_flag", "unspecified_stereo_centers"}
    assert set(content["box"]) == {"center_A", "size_A", "source", "margin_A"}
    assert set(content["parameters"]) == {"seed", "exhaustiveness", "num_modes", "energy_range", "conformers", "cpu"}
    assert set(content["engine"]) == {"name", "version", "binary_sha256", "package"}
    assert set(content["preparation"]) == {"tool", "version", "rdkit_version", "atom_typing", "charges"}
    assert set(content["counts"]) == {"modes", "contacts_by_mode", "null_result", "samples_generated",
                                      "samples_scored"}
    for row in content["modes"]:
        assert set(row) == {"mode", "score_kcal_mol", "engine_rmsd_lb_A", "engine_rmsd_ub_A", "conformer_index",
                            "core_max_deviation_A", "atoms_outside_box", "min_heavy_atom_distance_A", "pose_sdf",
                            "contacts"}


# ----------------------------------------------------------------- registration, isolation, capability
def test_registration_dispatch_table_and_capability(tmp_path, monkeypatch):
    assert JOB_PROTOCOLS["qvina_dock_v1"] == ("qvina_dock_ligand", "qvina")
    assert "qvina_dock_ligand" in JOB_ONLY_TOOLS and "qvina_dock_ligand" not in api_module.SUPPORTED_TOOLS
    assert "qvina_dock_ligand" in api_module.REGISTRY.impls and "qvina_dock_ligand" in api_module.REGISTRY.unavailable
    spec = api_module.REGISTRY.specs["qvina_dock_ligand"]
    assert spec.cost_class == "expensive" and spec.emits == "docking_result"
    # Code-owned dispatch: fixed worker module, pinned interpreter and engine; no request field selects them.
    assert guardian_module.DOCKING_ADAPTER == "qvina_dock_v1"
    assert guardian_module.DOCKING == MW / "jobs/docking_worker.py"
    assert guardian_module.DOCKING_PYTHON == ROOT / ".deps/docking/venv-locked/bin/python"
    assert "qvina_dock_v1" in guardian_module.MONITORED_ADAPTERS
    assert "qvina_dock_v1" not in guardian_module.PINNED_PYTHON_ADAPTERS  # the prolif interpreter is not used
    assert guardian_module.DOCKING_OUTPUT_LIMIT == C.MAX_RESULT_BYTES
    assert docking_bundle.WORKER == guardian_module.DOCKING
    assert docking_bundle.WORKER_PYTHON == guardian_module.DOCKING_PYTHON
    assert docking_bundle.QVINA == ROOT / ".deps/qvina/env/bin/qvina2"
    worker_text = (MW / "jobs/docking_worker.py").read_text()
    pinned = re.search(r'^QVINA_SHA256 = "([0-9a-f]{64})"', worker_text, re.MULTILINE)
    assert pinned and pinned.group(1) == docking_bundle.QVINA_SHA256
    capability = docking_bundle.capability()
    assert capability["available"] is True, f"pinned docking environments must be installed: {capability['reason']}"
    assert capability["reason_code"] is None and capability["pins"]["engine"] == "qvina"
    assert capability["pins"]["versions"] == {"meeko": "0.8.0", "rdkit": "2026.03.6", "MDAnalysis": "2.10.0",
                                              "gemmi": "0.7.5"}
    assert capability["pins"]["qvina_sha256"] == docking_bundle.QVINA_SHA256
    assert capability["limitations"] == list(C.LIMITATIONS)
    client = _client(tmp_path / "runs", monkeypatch)
    method = client.get("/capabilities").json()["methods"]["ligand_docking"]
    assert method["available"] is True and method["protocol_id"] == "qvina_dock_v1"


def test_server_process_never_imports_rdkit_meeko_or_mdanalysis():
    for name in ("docking_bundle.py", "docking_inputs.py", "docking_constants.py", "jobs/queue.py",
                 "jobs/guardian.py", "api/app.py", "tools/energetic.py"):
        tree = ast.parse((MW / name).read_text())
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert not any(module == top or module.startswith(top + ".") for module in imported
                       for top in FORBIDDEN_MODULES), name
    code = ("import sys; import mw.api.app, mw.docking_bundle, mw.jobs.queue; from mw import docking_bundle; "
            "docking_bundle.capability(); "
            "print(sorted(m for m in sys.modules if m.split('.')[0] in ('rdkit', 'meeko', 'MDAnalysis')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                         cwd=str(MW.parent), check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"
    assert not any(name.split(".")[0] in FORBIDDEN_MODULES for name in sys.modules)


def _fake_handshake(**overrides) -> dict:
    """Labeled fake handshake record for capability-state tests (never a scientific result)."""
    sha = docking_bundle.QVINA_SHA256
    value = {"schema": "docking_worker_handshake@1", "protocols": ["qvina_dock_v1"],
             "versions": dict(docking_bundle.PINNED_VERSIONS),
             "versions_expected": dict(docking_bundle.PINNED_VERSIONS),
             "engine": {"name": "qvina", "present": True, "binary_sha256": sha, "record_sha256": sha,
                        "pinned_sha256": sha, "package": "qvina-2.1.0-h4a521e9_8", "hash_match": True},
             "worker_sha256": hashlib.sha256(docking_bundle.WORKER.read_bytes()).hexdigest(), "python": "3.11.11"}
    value.update(overrides)
    return value


def test_capability_unavailable_paths_refuse_without_charge(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M18 environment missing")
    receptor = _import(client, rid, "receptor", "rec.pdb", REC)
    ligand = _import(client, rid, "ligand_sdf", "lig.sdf", PARENT)
    queued = _submit(client, rid, _args(receptor, _sdf_ligand(ligand))).json()
    assert queued["status"] == "queued"

    def state(**patches) -> dict:
        with monkeypatch.context() as patch:
            patch.setattr(docking_bundle, "_HANDSHAKE_CACHE", {})  # each state starts without a cached handshake
            for name, value in patches.items():
                patch.setattr(docking_bundle, name, value)
            value = docking_bundle.capability()
            if not value["available"]:
                assert value["pins"] is None and value["versions"] is None
                assert value["reason"] == docking_bundle.REASONS[value["reason_code"]]
                assert value["reason_code"] in C.CAPABILITY_REASONS
            return value

    assert state(WORKER_PYTHON=tmp_path / "missing/python")["reason_code"] == "worker_missing"
    assert state(WORKER=tmp_path / "missing/docking_worker.py")["reason_code"] == "worker_missing"
    assert state(QVINA=tmp_path / "missing/qvina2")["reason_code"] == "engine_missing"
    assert state(QVINA_RECORD=tmp_path / "missing/install-record.json")["reason_code"] == "engine_missing"
    tampered = tmp_path / "qvina2-tampered"
    tampered.write_bytes(docking_bundle.QVINA.read_bytes() + b"\0")  # labeled fault: a changed engine binary
    assert state(QVINA=tampered)["reason_code"] == "engine_hash_mismatch"
    record = json.loads(docking_bundle.QVINA_RECORD.read_text())
    record["executable"]["sha256"] = "0" * 64  # labeled fault: install record disagrees with the binary
    forged = tmp_path / "install-record.json"
    forged.write_text(json.dumps(record))
    assert state(QVINA_RECORD=forged)["reason_code"] == "engine_hash_mismatch"
    wrong = dict(docking_bundle.PINNED_VERSIONS, meeko="0.7.0")
    assert state(PINNED_VERSIONS=wrong)["reason_code"] == "version_mismatch"
    older = {**docking_bundle.PINNED_VERSIONS, "rdkit": "2026.03.5"}
    assert state(_handshake=lambda: _fake_handshake(versions=older))["reason_code"] == "version_mismatch"
    engine = {**_fake_handshake()["engine"], "hash_match": False}
    assert state(_handshake=lambda: _fake_handshake(engine=engine))["reason_code"] == "engine_hash_mismatch"
    assert state(_handshake=lambda: _fake_handshake(worker_sha256="0" * 64))["reason_code"] == "handshake_failed"
    assert state(_handshake=lambda: (_ for _ in ()).throw(ValueError("bad")))["reason_code"] == "handshake_failed"

    # Unavailable: a new submission is refused before any job, a queued job cannot start; nothing is charged.
    with monkeypatch.context() as patch:
        patch.setattr(docking_bundle, "QVINA", tmp_path / "missing/qvina2")
        method = client.get("/capabilities").json()["methods"]["ligand_docking"]
        assert method["available"] is False and method["reason_code"] == "engine_missing" and method["pins"] is None
        refused = _submit(client, rid, _args(receptor, _sdf_ligand(ligand), seed=2))
        assert refused.status_code == 412 and refused.json()["detail"]["reason_code"] == "engine_missing"
        blocked = _approve_start(client, rid, queued["job_id"])
        assert blocked.status_code == 412
    assert _used(client, rid) == 0 and not any(e["type"] == "job_dispatch_intent" for e in _events(root, rid))
    assert len([e for e in _events(root, rid) if e["type"] == "job_submitted"]) == 1
    assert docking_bundle.capability()["available"] is True


# ----------------------------------------------------------------- full product path
def test_free_docking_product_path_budget_cache_seed_and_keys(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M18 free docking (public prepared example, not experimental validation)")
    receptor = _import(client, rid, "receptor", "rec.pdb", REC)
    ligand = _import(client, rid, "ligand_sdf", "lig.sdf", PARENT)
    assert client.post(f"/runs/{rid}/jobs/approve").status_code == 412
    args = _args(receptor, _sdf_ligand(ligand))
    submitted = _submit(client, rid, args).json()
    first = client.post(f"/runs/{rid}/jobs/{submitted['job_id']}/start")
    assert first.status_code == 409 and first.json()["approval"]["tool"] == "qvina_dock_ligand"
    assert _used(client, rid) == 0
    assert client.post(f"/runs/{rid}/jobs/approve").status_code == 200
    done = client.post(f"/runs/{rid}/jobs/{submitted['job_id']}/start").json()
    assert done["status"] == "done", done
    assert done["timeout_s"] == 600 and done["input_handles"] == [receptor, ligand]
    handle = done["artifacts"]["docking_result"]
    assert done["output_handles"] == [handle] and _used(client, rid) == 1
    assert done["cleanup_status"] == "verified"
    run = api_module._run(rid)
    content = docking_bundle.validated_result(run, handle)
    assert content == run.store.load(handle)
    _check_spec_keys(content)
    assert content["schema"] == "docking_result@1" and content["protocol"] == "qvina_dock_v1"
    assert content["method"] == "qvina_free_v1"
    normalized = docking_inputs.validate_arguments(args)
    assert content["input_sha256"] == docking_inputs.input_sha256(normalized)
    assert content["inputs"]["receptor"] == {
        "handle": receptor, "sha256": hashlib.sha256(REC).hexdigest(), "model_number": 1,
        "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "removed_instance": None,
        "acknowledgement": ACK}
    assert content["inputs"]["ligand"] == {
        "source": "sdf", "sdf_handle": ligand, "sdf_sha256": hashlib.sha256(PARENT).hexdigest(),
        "candidate_set_handle": None, "candidate_id": None, "parent_sdf_handle": None, "parent_sdf_sha256": None,
        "generated": {"hydrogens": False, "coordinates": False}, "stereo_flag": None,
        "unspecified_stereo_centers": None}
    assert content["box"] == {"center_A": CENTER, "size_A": [12.0, 12.0, 12.0], "source": "manual", "margin_A": None}
    assert content["parameters"] == {"seed": 1, "exhaustiveness": 1, "num_modes": 2, "energy_range": 3.0,
                                     "conformers": None, "cpu": 1}
    assert content["engine"]["name"] == "qvina" and content["engine"]["binary_sha256"] == docking_bundle.QVINA_SHA256
    assert content["preparation"]["tool"] == "Meeko" and content["preparation"]["version"] == "0.8.0"
    assert 1 <= len(content["modes"]) <= 2 and [m["mode"] for m in content["modes"]] == list(
        range(1, len(content["modes"]) + 1))
    assert content["counts"]["modes"] == len(content["modes"]) and content["counts"]["null_result"] is False
    assert content["limitations"] == list(C.applicable_limitations(mode="free", source="sdf", removed_instance=False,
                                                                     unspecified_stereo_centers=None))
    text = json.dumps(content)
    assert done["job_id"] not in text and done["attempt_id"] not in text and "job_id" not in text
    events = _events(root, rid)
    assert [e["type"] for e in events if e["type"] in {"approval_requested", "approval_resolved"}] == [
        "approval_requested", "approval_resolved"]
    assert len([e for e in events if e["type"] == "budget_reserved"]) == 1
    _workers_gone(root, rid)

    # Same normalized input (defaults spelled out, acknowledgement repeated) -> same call key -> the stored job.
    spelled = _args(receptor, _sdf_ligand(ligand), params={"seed": 1, "exhaustiveness": 1, "num_modes": 2,
                                                           "energy_range": 3})
    for again_args in (args, spelled):
        again = _submit(client, rid, again_args, timeout_s=300).json()
        assert again["job_id"] == done["job_id"] and again["output_handles"] == [handle]
    # Another seed is another call key (a new queued job); nothing is charged by submission.
    other = _submit(client, rid, _args(receptor, _sdf_ligand(ligand), seed=2)).json()
    assert other["job_id"] != done["job_id"] and other["call_key"] != done["call_key"] and other["status"] == "queued"
    assert _used(client, rid) == 1
    assert len([e for e in _events(root, rid) if e["type"] == "job_submitted"]) == 2

    # The object content never carries time, job or attempt identities: rebuilding it from the same worker output
    # under other identities gives the same bytes (same input -> same handle).
    job = JobQueue(run).get(done["job_id"])
    raw = (root / rid / "jobs" / done["job_id"] / done["attempt_id"] / "result.json").read_bytes()
    output = json.loads(raw)
    rebuilt = docking_bundle.result_content(job, {**output, "job_id": "job_other", "attempt_id": "attempt_other"})
    assert rebuilt == content

    # Events-only recovery: a new root holding only events.jsonl reopens the identical object without any engine.
    before = (root / rid / "events.jsonl").read_bytes()
    original = (root / rid / run.store.meta(handle)["path"]).read_bytes()
    replay = tmp_path / "events_only"
    (replay / rid).mkdir(parents=True)
    (replay / rid / "events.jsonl").write_bytes(before)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("events-only reads must not execute scientific work")

    with monkeypatch.context() as patch:
        patch.setattr(docking_bundle, "WORKER_PYTHON", tmp_path / "docking_removed/python")
        patch.setattr(docking_bundle, "QVINA", tmp_path / "qvina_removed/qvina2")
        patch.setattr(docking_bundle, "_handshake", forbidden)
        patch.setattr(docking_bundle, "stage", forbidden)
        patch.setattr(JobQueue, "_supervise", forbidden)
        patch.setattr(Run, "call", forbidden)
        recovered = new_ligand_run(replay, rid)
        assert docking_bundle.validated_result(recovered, handle) == content
        assert (replay / rid / recovered.store.meta(handle)["path"]).read_bytes() == original
        assert (replay / rid / "events.jsonl").read_bytes() == before
        # A tampered recovered object never reads.
        path = replay / rid / recovered.store.meta(handle)["path"]
        path.write_text(json.dumps({**content, "limitations": content["limitations"][:-1]}))
        with pytest.raises(docking_bundle.DockingEvidenceError):
            docking_bundle.validated_result(recovered, handle)
    for wrong in (receptor, ligand, None, f"obj://{rid}/docking_result/{'1' * 64}"):
        with pytest.raises(docking_bundle.DockingEvidenceError):
            docking_bundle.validated_result(run, wrong)


def test_candidate_core_fixed_path_records_generated_inputs(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M18 core-fixed candidate (public-derived parent, synthetic blocks)")
    receptor = _import(client, rid, "receptor", "rec.pdb", REC)
    parent = _import(client, rid, "ligand_sdf", "parent.sdf", PARENT)
    candidate_set = _candidate_set(client, rid, parent)
    ligand = {"source": "candidate", "candidate_set_handle": candidate_set, "candidate_id": CANDIDATE_ID,
              "parent_sdf_handle": parent}
    args = _args(receptor, ligand, mode="core_fixed", box={"source": "ligand_range", "margin_A": 8.0},
                 params={"seed": 7, "exhaustiveness": 1, "num_modes": 2, "conformers": 2})
    done = _run_job(client, rid, args)
    assert done["status"] == "done", done
    assert done["input_handles"] == [receptor, candidate_set, parent] and _used(client, rid) == 3
    content = docking_bundle.validated_result(api_module._run(rid), done["artifacts"]["docking_result"])
    _check_spec_keys(content)
    assert content["method"] == "qvina_core_fixed_score_only_v1" and content["inputs"]["mode"] == "core_fixed"
    lig = content["inputs"]["ligand"]
    assert lig["source"] == "candidate" and lig["candidate_id"] == CANDIDATE_ID
    assert lig["candidate_set_handle"] == candidate_set and lig["parent_sdf_handle"] == parent
    assert lig["parent_sdf_sha256"] == EXPECTED["m17_candidate"]["parent_sha256"] and lig["sdf_handle"] is None
    assert lig["generated"] == {"hydrogens": True, "coordinates": True} and lig["stereo_flag"] == "none"
    assert content["counts"]["samples_generated"] == 2 and content["counts"]["samples_scored"] == 2
    assert all(m["conformer_index"] is not None and m["engine_rmsd_lb_A"] is None for m in content["modes"])
    assert content["limitations"] == list(C.applicable_limitations(
        mode="core_fixed", source="candidate", removed_instance=False,
        unspecified_stereo_centers=lig["unspecified_stereo_centers"]))
    assert content["box"]["source"] == "ligand_range" and content["box"]["margin_A"] == 8.0
    _workers_gone(root, rid)


# ----------------------------------------------------------------- admission refusals (no job is created)
def test_admission_refusals_never_create_a_job_or_charge(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M18 admission")
    receptor = _import(client, rid, "receptor", "rec.pdb", REC)
    parent = _import(client, rid, "ligand_sdf", "parent.sdf", PARENT)
    planar = _import(client, rid, "ligand_sdf", "planar.sdf", PLANAR)
    candidate_set = _candidate_set(client, rid, parent)
    rec_fix = {name: _import(client, rid, "receptor", name, (FIX / name).read_bytes()) for name in (
        "synthetic-complex-receptor-lig.pdb", "synthetic-complex-duplicate-instance.pdb",
        "synthetic-complex-covalent-instance.pdb", "synthetic-receptor-water-zinc.pdb",
        "synthetic-receptor-altloc.pdb")}
    no_h = _import(client, rid, "receptor", "no-h.pdb", _strip_hydrogens(REC))
    other = _new_run(client, "M18 foreign run")
    foreign_receptor = _import(client, other, "receptor", "rec.pdb", REC)
    foreign_ligand = _import(client, other, "ligand_sdf", "lig.sdf", PARENT)
    before = _events(root, rid)
    jobs_before = len([e for e in before if e["type"] == "job_submitted"])
    sdf = _sdf_ligand(parent)

    def cand(**overrides) -> dict:
        return {"source": "candidate", "candidate_set_handle": candidate_set, "candidate_id": CANDIDATE_ID,
                "parent_sdf_handle": parent, **overrides}

    complex_handle = rec_fix["synthetic-complex-receptor-lig.pdb"]
    cases = [
        ({**_args(receptor, sdf), "engine": "vina"}, "invalid_job_arguments"),
        (_args(receptor, sdf, ack={**ACK, "rigid_no_optimization": False}), "acknowledgement_missing"),
        ({k: v for k, v in _args(receptor, sdf).items() if k != "acknowledgement"}, "acknowledgement_missing"),
        (_args(receptor, sdf, mode="core_fixed", params={"seed": 1, "conformers": 2}), "mode_source_mismatch"),
        (_args(receptor, sdf, params={"seed": -1}), "invalid_job_arguments"),
        (_args(receptor, sdf, params={"exhaustiveness": 8}), "invalid_job_arguments"),
        (_args(receptor, sdf, box={"source": "manual", "center_A": CENTER, "size_A": [5.0, 12.0, 12.0]}),
         "box_invalid"),
        (_args(receptor, sdf, box={"source": "manual", "center_A": CENTER, "size_A": [41.0, 12.0, 12.0]}),
         "box_too_large"),
        (_args(receptor, sdf, box={"source": "instance_range", "margin_A": 8.0}), "box_invalid"),
        # wrong kind or foreign run handles
        (_args(parent, sdf), "invalid_job_arguments"),
        (_args(foreign_receptor, sdf), "invalid_job_arguments"),
        (_args(receptor, _sdf_ligand(receptor)), "invalid_job_arguments"),
        (_args(receptor, _sdf_ligand(foreign_ligand)), "invalid_job_arguments"),
        (_args(receptor, _sdf_ligand(candidate_set)), "invalid_job_arguments"),
        (_args(receptor, sdf, connectivity={"kind": "sidecar", "sidecar_handle": parent}), "invalid_job_arguments"),
        (_args(receptor, cand(candidate_set_handle=parent)), "invalid_job_arguments"),
        (_args(receptor, cand(candidate_set_handle=f"obj://{rid}/ligand_candidate_set/{'0' * 64}")),
         "invalid_job_arguments"),
        (_args(receptor, cand(parent_sdf_handle=receptor)), "invalid_job_arguments"),
        # candidate source
        (_args(receptor, cand(candidate_id="c_0000000000000000")), "candidate_unknown"),
        (_args(receptor, cand(parent_sdf_handle=planar)), "parent_mismatch"),
        # receptor (server-side pure checks, same rules as M11)
        (_args(receptor, sdf, instance=INSTANCE), "receptor_instance_unknown"),
        (_args(complex_handle, sdf), "receptor_unsupported_residue"),
        (_args(complex_handle, sdf, instance={**INSTANCE, "seq_auth": 2}), "receptor_instance_unknown"),
        (_args(rec_fix["synthetic-complex-duplicate-instance.pdb"], sdf, instance=INSTANCE),
         "receptor_instance_ambiguous"),
        (_args(rec_fix["synthetic-complex-covalent-instance.pdb"], sdf, instance=INSTANCE),
         "receptor_instance_covalent"),
        (_args(rec_fix["synthetic-receptor-water-zinc.pdb"], sdf), "receptor_unsupported_residue"),
        (_args(rec_fix["synthetic-receptor-altloc.pdb"], sdf), "receptor_altloc_present"),
        (_args(no_h, sdf), "receptor_hydrogens_missing"),
        ({**_args(receptor, sdf), "receptor_model_number": 2}, "receptor_invalid"),
    ]
    for args, reason in cases:
        response = _submit(client, rid, args)
        assert response.status_code == 422, (args, response.text)
        assert response.json()["detail"]["reason_code"] == reason, (reason, response.json())
    for unsafe in ("module", "executable", "argv", "env", "path", "cwd", "fixture"):
        assert _submit(client, rid, {**_args(receptor, sdf), unsafe: "x"}).status_code == 422
    assert _submit(client, rid, _args(receptor, sdf), timeout_s=901).status_code == 422
    assert client.post(f"/runs/{rid}/commands", json={"tool": "qvina_dock_ligand", "args": {}}).status_code in {
        412, 422}
    after = _events(root, rid)
    assert len([e for e in after if e["type"] == "job_submitted"]) == jobs_before
    assert [e for e in after if e["type"] == "budget_reserved"] == [e for e in before if e["type"] == "budget_reserved"]
    # The complex receptor with its one instance named is admitted (the job is created, not started).
    admitted = _submit(client, rid, _args(complex_handle, sdf, instance=INSTANCE,
                                          box={"source": "instance_range", "margin_A": 8.0}))
    assert admitted.status_code == 200 and admitted.json()["status"] == "queued", admitted.text


def test_wrong_or_foreign_handles_never_reach_the_worker(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M18 no implementation call")
    receptor = _import(client, rid, "receptor", "rec.pdb", REC)
    ligand = _import(client, rid, "ligand_sdf", "lig.sdf", PARENT)
    other = _new_run(client, "M18 other")
    foreign = _import(client, other, "receptor", "rec.pdb", REC)
    calls = []
    monkeypatch.setattr(docking_bundle, "stage", lambda *a, **k: calls.append("stage"))
    monkeypatch.setattr(docking_bundle, "publish", lambda *a, **k: calls.append("publish"))
    monkeypatch.setattr(docking_bundle, "_handshake", lambda: calls.append("handshake"))
    monkeypatch.setattr(JobQueue, "_supervise", lambda *a, **k: calls.append("supervise"))
    for args in (_args(foreign, _sdf_ligand(ligand)), _args(ligand, _sdf_ligand(ligand)),
                 _args(receptor, _sdf_ligand(receptor)),
                 _args(receptor, {"source": "candidate", "candidate_set_handle": ligand, "candidate_id": "c_1",
                                  "parent_sdf_handle": ligand})):
        assert _submit(client, rid, args).status_code == 422
    assert calls == []
    assert not any(e["type"] == "job_submitted" for e in _events(root, rid))


def test_dry_run_plans_only_without_objects(tmp_path):
    run = new_ligand_run(tmp_path / "dry", "run_dry_docking", dry_run=True)
    receptor = import_file(run, "receptor", "rec.pdb", REC)
    ligand = import_file(run, "ligand_sdf", "lig.sdf", PARENT)
    args = _args(receptor, _sdf_ligand(ligand))
    plan = JobQueue(run).submit("qvina_dock_v1", args, timeout_s=600)
    assert plan["plan_only"] is True and plan["reason_code"] == "dry_run" and plan["output_handles"] == []
    assert plan["normalized_parameters"] == docking_inputs.validate_arguments(args)
    events = list(run.events.read())
    assert not any(e["type"] in {"job_submitted", "budget_reserved"} for e in events)
    assert not any(e["type"] == "object_created" and e["kind"] == "docking_result" for e in events)


# ----------------------------------------------------------------- typed failures, publication guards, limits
def test_worker_refusal_is_a_typed_charged_failure_without_objects(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M18 typed worker refusal (synthetic planar SDF)")
    receptor = _import(client, rid, "receptor", "rec.pdb", REC)
    planar = _import(client, rid, "ligand_sdf", "planar.sdf", PLANAR)
    failed = _run_job(client, rid, _args(receptor, _sdf_ligand(planar)))
    assert failed["status"] == "failed" and failed["output_handles"] == []
    assert failed["failure"]["error"] == "input_invalid" and failed["failure"]["reason_code"] == "ligand_not_3d"
    assert failed["cleanup_status"] == "verified" and _used(client, rid) == 1
    assert _docking_objects(root, rid) == []
    _workers_gone(root, rid)


def test_tampered_output_or_cancel_after_worker_publishes_nothing(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M18 publication guards")
    receptor = _import(client, rid, "receptor", "rec.pdb", REC)
    ligand = _import(client, rid, "ligand_sdf", "lig.sdf", PARENT)
    original = JobQueue._supervise

    def cancel_after(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch):
        result, identity = original(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch)
        assert result and result.get("returncode") == 0
        self.request_cancel(job["job_id"])
        return result, identity

    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_supervise", cancel_after)
        response = _run_job(client, rid, _args(receptor, _sdf_ligand(ligand), seed=11))
    assert response["status"] == "cancelled" and _docking_objects(root, rid) == []

    def tamper(mutate):
        def supervise(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch):
            result, identity = original(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch)
            data = json.loads((attempt_dir / "result.json").read_bytes())
            mutate(data)  # labeled fault: genuine worker output altered after the run, descriptor re-signed
            raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            (attempt_dir / "result.json").write_bytes(raw)
            result["payload"] = {"output_sha256": hashlib.sha256(raw).hexdigest(), "output_bytes": len(raw)}
            return result, identity
        return supervise

    def contact(data: dict) -> dict:
        return next(row for mode in data["modes"] for row in mode["contacts"])

    faults = [(lambda d: d.update(attempt_id="attempt_other"), "ValueError"),
              (lambda d: d["modes"][0].update(mode=5), "DockingEvidenceError"),
              (lambda d: contact(d).update(kind="polar_contact" if contact(d)["kind"] != "polar_contact" else
                                           "contact"), "DockingEvidenceError"),
              (lambda d: contact(d)["receptor_atom"].update(site_index=contact(d)["receptor_atom"]["site_index"] + 1),
               "DockingEvidenceError")]
    for index, (fault, diagnostic) in enumerate(faults):
        with monkeypatch.context() as patch:
            patch.setattr(JobQueue, "_supervise", tamper(fault))
            failed = _run_job(client, rid, _args(receptor, _sdf_ligand(ligand), seed=20 + index))
        assert failed["status"] == "failed" and failed["failure"]["message"] == "invalid scientific output", failed
        assert failed["failure"]["diagnostic"] == diagnostic, failed
    assert _docking_objects(root, rid) == [] and _used(client, rid) == 5


def test_result_over_its_size_bound_is_resource_exceeded(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M18 result size bound")
    receptor = _import(client, rid, "receptor", "rec.pdb", REC)
    ligand = _import(client, rid, "ligand_sdf", "lig.sdf", PARENT)
    monkeypatch.setattr(docking_bundle, "MAX_RESULT_BYTES", 2000)  # labeled internal hook: bound lowered
    failed = _run_job(client, rid, _args(receptor, _sdf_ligand(ligand)))
    assert failed["status"] == "failed" and failed["output_handles"] == []
    assert (failed["failure"]["error"], failed["failure"]["reason_code"]) == ("resource_exceeded",
                                                                            "resource_exceeded")
    assert _docking_objects(root, rid) == [] and _used(client, rid) == 1


# ----------------------------------------------------------------- cancellation and timeout kill qvina too
def _qvina_watcher(found: list) -> object:
    """Wrap _record_control: on STARTED, record the live qvina2 child of the real worker (pid + raw identity)."""
    original = JobQueue._record_control

    def watch(worker_pid: int) -> None:
        end = time.monotonic() + 60
        while time.monotonic() < end and not found:
            try:
                for child in psutil.Process(worker_pid).children(recursive=True):
                    if child.name() == "qvina2":
                        found.append({"pid": child.pid, "start_identity": process_identity.capture(child.pid),
                                      "pgid": os.getpgid(child.pid)})
                        return
            except psutil.Error:
                return
            time.sleep(0.05)

    def record(self, message, job_id, attempt_id, nonce):
        done = original(self, message, job_id, attempt_id, nonce)
        if message and message.get("kind") == "STARTED":
            threading.Thread(target=watch, args=(message["pid"],), daemon=True).start()
        return done

    return record


def _gone(entry: dict) -> bool:
    try:
        process = psutil.Process(entry["pid"])
        return (process.status() == psutil.STATUS_ZOMBIE or
                not process_identity.matches(entry["pid"], entry["start_identity"]))
    except psutil.NoSuchProcess:
        return True


def test_cancel_and_timeout_store_nothing_and_stop_the_qvina_child(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M18 cancel and timeout")
    receptor = _import(client, rid, "receptor", "rec.pdb", REC)
    ligand = _import(client, rid, "ligand_sdf", "lig.sdf", PARENT)
    slow = {"seed": 3, "exhaustiveness": 8, "num_modes": 9}
    box = {"source": "manual", "center_A": CENTER, "size_A": [20.0, 20.0, 20.0]}
    found: list[dict] = []
    try:
        record = _qvina_watcher(found)
        original = record

        def cancel_on_qvina(self, message, job_id, attempt_id, nonce):
            done = original(self, message, job_id, attempt_id, nonce)
            if message and message.get("kind") == "STARTED":
                end = time.monotonic() + 60
                while time.monotonic() < end and not found:
                    time.sleep(0.05)
                assert found, "the real worker never started qvina2"
                self.request_cancel(job_id)
            return done

        with monkeypatch.context() as patch:
            patch.setattr(JobQueue, "_record_control", cancel_on_qvina)
            cancelled = _run_job(client, rid, _args(receptor, _sdf_ligand(ligand), box=box, params=slow))
        assert cancelled["status"] == "cancelled" and cancelled["output_handles"] == []
        assert cancelled["cleanup_status"] == "verified" and _used(client, rid) == 1
        cancelled_qvina = found.pop()
        assert cancelled_qvina["pgid"] != os.getpgrp()  # inside the guardian's own process group
        assert _gone(cancelled_qvina), "qvina2 survived cancellation"

        with monkeypatch.context() as patch:
            patch.setattr(JobQueue, "_record_control", _qvina_watcher(found))
            timed_out = _run_job(client, rid, _args(receptor, _sdf_ligand(ligand), box=box,
                                                    params={**slow, "seed": 4}), timeout_s=15)
        assert timed_out["status"] == "failed" and timed_out["failure"]["error"] == "resource_exceeded"
        assert timed_out["failure"]["message"] == "job timeout" and timed_out["output_handles"] == []
        assert found, "qvina2 was not running at the deadline"
        assert _gone(found[0]), "qvina2 survived the timeout"
        assert _used(client, rid) == 2 and _docking_objects(root, rid) == []
        time.sleep(0.1)
        _workers_gone(root, rid)
    finally:  # a process left by a failed assertion is killed only when its recorded start identity still matches
        leftovers = [{"pid": e["pid"], "start_identity": e["start_identity"]} for e in _events(root, rid)
                     if e["type"] == "job_worker_started"] + found
        for entry in leftovers:
            if process_identity.matches(entry["pid"], entry["start_identity"]):
                try:
                    psutil.Process(entry["pid"]).kill()
                except psutil.Error:
                    pass


def test_worker_error_envelope_is_closed(tmp_path):
    """Only the worker's typed envelope with a closed reason maps to a failure; anything else is fatal."""
    def read(value) -> dict:
        path = tmp_path / "error.json"
        path.write_bytes(value if isinstance(value, bytes) else
                         json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
        return docking_bundle.worker_error(tmp_path)

    good = {"schema": "docking_worker_error@1", "error_class": "input_invalid", "reason_code": "ligand_not_3d",
            "message": "planar", "detail": {"items": [1]}}
    assert read(good) == {"error": "input_invalid", "reason_code": "ligand_not_3d", "message": "planar",
                          "detail": {"items": [1]}}
    fatal = {"error": "fatal", "message": "worker exit or invalid docking error envelope"}
    for bad in ({**good, "reason_code": "not_a_reason"}, {**good, "error_class": "transient"},
                {**good, "extra": 1}, {**good, "message": ""}, {**good, "schema": "x"}, b"{not json",
                {**good, "detail": []}):
        assert read(bad) == fatal, bad
    (tmp_path / "error.json").unlink()
    assert docking_bundle.worker_error(tmp_path) == fatal
