"""M17 ligand job lane: registration, admission, real worker processes, budget, cache, failures, dry-run.

Jobs run the pinned RDKit worker (``.deps/prolif/venv-locked``) through the product path (chemical imports ->
POST /jobs -> approve -> start). They FAIL, never skip, when the environment is absent. The server process
never imports RDKit. Inputs are the labeled synthetic fixtures in ``fixtures/ligand``; fault injections are
labeled and applied only through internal test hooks, never through request fields.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest
from fastapi.testclient import TestClient
from ligand_job_fixture import EXPECTED, NO_H, RULES, SDF, SMI, VALID_RULE_IDS, import_file, new_ligand_run

from mw import ligand_bundle
from mw import ligand_constants as C
from mw.api import app as api_module
from mw.jobs import guardian as guardian_module
from mw.jobs.queue import JobQueue
from mw.tools.energetic import JOB_ONLY_TOOLS, JOB_PROTOCOLS

MW = Path(__file__).resolve().parents[1] / "mw"
CHEM_FIX = Path(__file__).parent / "fixtures/chemical"
LIGAND_KINDS = {"ligand_inspection", "ligand_candidate_set"}


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


def _submit(client: TestClient, rid: str, protocol: str, args: dict, timeout_s: float = 120):
    return client.post(f"/runs/{rid}/jobs", json={"protocol_id": protocol, "args": args, "timeout_s": timeout_s})


def _approve_start(client: TestClient, rid: str, job_id: str, tool: str):
    started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    if started.status_code == 409:
        assert started.json()["approval"] == {"gate": "expensive_first_call", "tool": tool,
                                              "reason": "first expensive call needs approval"}
        approved = client.post(f"/runs/{rid}/jobs/approve")
        assert approved.status_code == 200, approved.text
        started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    return started


def _run_job(client: TestClient, rid: str, protocol: str, args: dict, timeout_s: float = 120) -> dict:
    submitted = _submit(client, rid, protocol, args, timeout_s)
    assert submitted.status_code == 200, submitted.text
    job = submitted.json()
    assert job["status"] == "queued" and job["protocol_id"] == protocol
    started = _approve_start(client, rid, job["job_id"], ligand_bundle.TOOLS[protocol])
    assert started.status_code == 200, started.text
    return started.json()


def _events(root: Path, rid: str) -> list[dict]:
    return [json.loads(line) for line in (root / rid / "events.jsonl").read_text().splitlines()]


def _used(client: TestClient, rid: str) -> int:
    return client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"]


def _ligand_objects(root: Path, rid: str) -> list[dict]:
    return [e for e in _events(root, rid) if e["type"] == "object_created" and e["kind"] in LIGAND_KINDS]


def _workers_gone(root: Path, rid: str) -> None:
    for event in _events(root, rid):
        if event["type"] == "job_worker_started":
            try:
                process = psutil.Process(event["pid"])
                assert process.status() == psutil.STATUS_ZOMBIE or not process.is_running()
            except psutil.NoSuchProcess:
                pass


def _imports(client: TestClient, rid: str) -> tuple[str, str, str]:
    return (_import(client, rid, "ligand_sdf", "parent.sdf", NO_H),
            _import(client, rid, "building_blocks_smiles", "blocks.smi", SMI),
            _import(client, rid, "building_blocks_sdf", "blocks.sdf", SDF))


# ----------------------------------------------------------------- registration and capability
def test_registration_dispatch_table_and_capability():
    assert JOB_PROTOCOLS["rdkit_inspect_v1"] == ("rdkit_inspect_ligand", "rdkit")
    assert JOB_PROTOCOLS["rdkit_enumerate_v1"] == ("rdkit_enumerate_ligands", "rdkit")
    assert {"rdkit_inspect_ligand", "rdkit_enumerate_ligands"} <= JOB_ONLY_TOOLS
    for tool in ("rdkit_inspect_ligand", "rdkit_enumerate_ligands"):
        assert tool not in api_module.SUPPORTED_TOOLS
        assert tool in api_module.REGISTRY.impls and tool in api_module.REGISTRY.unavailable
        assert api_module.REGISTRY.specs[tool].cost_class == "expensive"
    # Code-owned dispatch: fixed worker module and pinned interpreter per adapter; no request field selects them.
    assert guardian_module.LIGAND_ADAPTERS == {"rdkit_inspect_v1", "rdkit_enumerate_v1"}
    assert guardian_module.LIGAND == MW / "jobs/ligand_worker.py"
    assert guardian_module.LIGAND_ADAPTERS <= guardian_module.MONITORED_ADAPTERS
    assert ligand_bundle.WORKER == MW / "jobs/ligand_worker.py"
    assert ligand_bundle.WORKER_PYTHON == guardian_module.CHEMICAL_PYTHON
    capability = ligand_bundle.capability()
    assert capability["available"] is True, f"pinned RDKit environment must be installed: {capability['reason']}"
    assert capability["pins"]["rdkit_version"] == "2026.03.6" and capability["pins"]["engine"] == "rdkit"
    assert capability["pains_catalog_entries"] == {"PAINS_A": 16, "PAINS_B": 55, "PAINS_C": 409}


def test_server_process_never_imports_rdkit():
    for name in ("ligand_bundle.py", "jobs/queue.py", "jobs/guardian.py", "api/app.py"):
        tree = ast.parse((MW / name).read_text())
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert not any(module == "rdkit" or module.startswith("rdkit.") for module in imported), name
    code = ("import sys; import mw.api.app, mw.ligand_bundle, mw.jobs.queue; from mw import ligand_bundle; "
            "ligand_bundle.capability(); print(any(m == 'rdkit' or m.startswith('rdkit.') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                         cwd=str(MW.parent), check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
    assert "rdkit" not in sys.modules


# ----------------------------------------------------------------- full product path
def test_inspect_then_enumerate_product_path_budget_and_cache(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M17 inspect and enumerate (synthetic methacetin)")
    parent, smiles, sdf = _imports(client, rid)
    assert client.post(f"/runs/{rid}/jobs/approve").status_code == 412
    inspect_args = {"parent_sdf_handle": parent, "block_handles": [sdf, smiles], "rules": RULES}
    inspected = _run_job(client, rid, "rdkit_inspect_v1", inspect_args)
    assert inspected["status"] == "done", inspected
    assert inspected["input_handles"] == [parent, smiles, sdf]  # blocks in import order
    inspection = inspected["artifacts"]["ligand_inspection"]
    assert inspected["output_handles"] == [inspection] and _used(client, rid) == 1
    run = api_module._run(rid)
    stored = ligand_bundle.validated_inspection(run, inspection)
    assert stored == run.store.load(inspection)
    assert [row["serial"] for row in stored["parent"]["atoms"]] == list(range(1, 13))
    assert [(r["rule_id"], r["status"]) for r in stored["rules"]] == [
        (r["rule_id"], r["status"]) for r in EXPECTED["rules"]["results"]]
    assert [lib["kind"] for lib in stored["block_libraries"]] == ["building_blocks_smiles", "building_blocks_sdf"]
    assert stored["method"]["rdkit_version"] == "2026.03.6"
    assert "job_id" not in json.dumps(stored) and inspected["job_id"] not in json.dumps(stored)

    enumerate_args = {"inspection_handle": inspection, "site_atoms": [12, 11], "use_fixed": True,
                      "rule_ids": VALID_RULE_IDS}
    enumerated = _run_job(client, rid, "rdkit_enumerate_v1", enumerate_args)
    assert enumerated["status"] == "done", enumerated
    handle = enumerated["artifacts"]["ligand_candidate_set"]
    assert enumerated["input_handles"] == [inspection, parent, smiles, sdf] and _used(client, rid) == 2
    content, _ = ligand_bundle.validated_candidate_set(run, handle)
    union = EXPECTED["generation_with_site_methoxy"]["union_unique_candidates_fixed_plus_valid_rules_both_libraries"]
    assert content["counts"]["candidates"] == len(union) == 10 and content["site_atoms"] == [11, 12]
    assert content["counts"]["raw_products"] == 17 and content["limit_reached"] is False
    assert content["inspection_handle"] == inspection and content["limitations"] == list(C.LIMITATIONS)
    events = _events(root, rid)
    assert [e["type"] for e in events if e["type"] in {"approval_requested", "approval_resolved"}] == [
        "approval_requested", "approval_resolved"]
    assert len([e for e in events if e["type"] == "budget_reserved"]) == 2
    _workers_gone(root, rid)

    # Same input -> same call key -> the stored job (no new job, no charge), whatever spelling is used.
    for args in ({"parent_sdf_handle": parent, "block_handles": [smiles, sdf], "rules": RULES}, inspect_args):
        again = _submit(client, rid, "rdkit_inspect_v1", args, timeout_s=60).json()
        assert again["job_id"] == inspected["job_id"] and again["status"] == "done"
    for site in ([11, 12], [12, 11]):
        again = _submit(client, rid, "rdkit_enumerate_v1", {**enumerate_args, "site_atoms": site}).json()
        assert again["job_id"] == enumerated["job_id"] and again["output_handles"] == [handle]
    reordered = _submit(client, rid, "rdkit_enumerate_v1", {**enumerate_args, "rule_ids": VALID_RULE_IDS[::-1]})
    assert reordered.json()["job_id"] != enumerated["job_id"]  # rule order is generation order (spec 6.1)
    assert _used(client, rid) == 2
    assert len([e for e in _events(root, rid) if e["type"] == "job_submitted"]) == 3


# ----------------------------------------------------------------- admission refusals (no job is created)
def test_admission_refusals_never_create_a_job(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M17 admission")
    parent, smiles, sdf = _imports(client, rid)
    other = _new_run(client, "M17 foreign run")
    foreign_parent = _import(client, other, "ligand_sdf", "parent.sdf", NO_H)
    inspection = _run_job(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [smiles],
                                                            "rules": RULES})["output_handles"][0]
    foreign_inspection = _run_job(client, other, "rdkit_inspect_v1",
                                  {"parent_sdf_handle": foreign_parent})["output_handles"][0]
    before = _events(root, rid)
    jobs_before = len([e for e in before if e["type"] == "job_submitted"])
    inspect_cases = [
        ({"parent_sdf_handle": parent, "engine": "x"}, "invalid_job_arguments"),
        ({"block_handles": [smiles]}, "invalid_job_arguments"),
        ({"parent_sdf_handle": smiles}, "parent_import_invalid"),
        ({"parent_sdf_handle": foreign_parent}, "parent_import_invalid"),
        ({"parent_sdf_handle": inspection}, "parent_import_invalid"),
        ({"parent_sdf_handle": parent, "block_handles": [parent]}, "block_import_invalid"),
        ({"parent_sdf_handle": parent, "block_handles": [smiles, smiles]}, "invalid_job_arguments"),
        ({"parent_sdf_handle": parent, "block_handles": [smiles, sdf, parent]}, "invalid_job_arguments"),
        ({"parent_sdf_handle": parent, "rules": ["x"] * 11}, "rule_text_invalid"),
        ({"parent_sdf_handle": parent, "rules": [7]}, "rule_text_invalid"),
    ]
    site = EXPECTED["parents"]["no_h"]["site_methoxy"]
    enumerate_cases = [
        ({"inspection_handle": inspection, "site_atoms": [], "use_fixed": True}, "site_empty"),
        ({"inspection_handle": inspection, "site_atoms": [99], "use_fixed": True}, "site_atom_unknown"),
        ({"inspection_handle": inspection, "site_atoms": list(range(1, 13)), "use_fixed": True}, "core_empty"),
        ({"inspection_handle": inspection, "site_atoms": [5], "use_fixed": True}, "crossing_bond_count"),
        ({"inspection_handle": inspection, "site_atoms": [3], "use_fixed": True}, "crossing_bond_not_single"),
        ({"inspection_handle": inspection, "site_atoms": ["11"], "use_fixed": True}, "site_atoms_invalid"),
        ({"inspection_handle": inspection, "site_atoms": site, "use_fixed": False}, "no_generation_method"),
        ({"inspection_handle": inspection, "site_atoms": site, "use_fixed": True, "rule_ids": ["user_4"]},
         "rule_invalid"),
        ({"inspection_handle": inspection, "site_atoms": site, "use_fixed": True, "rule_ids": ["user_99"]},
         "rule_invalid"),
        ({"inspection_handle": inspection, "site_atoms": site, "use_fixed": True, "rule_ids": ["user_9"]},
         "rule_invalid"),
        ({"inspection_handle": inspection, "site_atoms": site, "use_fixed": "yes"}, "invalid_job_arguments"),
        ({"inspection_handle": inspection, "site_atoms": site, "use_fixed": True, "limits": {}},
         "invalid_job_arguments"),
        ({"inspection_handle": parent, "site_atoms": site, "use_fixed": True}, "inspection_invalid"),
        ({"inspection_handle": foreign_inspection, "site_atoms": site, "use_fixed": True}, "inspection_invalid"),
        ({"inspection_handle": f"obj://{rid}/ligand_inspection/{'0' * 64}", "site_atoms": site, "use_fixed": True},
         "inspection_invalid"),
    ]
    for protocol, cases in (("rdkit_inspect_v1", inspect_cases), ("rdkit_enumerate_v1", enumerate_cases)):
        for args, reason in cases:
            response = _submit(client, rid, protocol, args)
            assert response.status_code == 422, (args, response.text)
            assert response.json()["detail"]["reason_code"] == reason, (args, response.json())
    site_refusal = _submit(client, rid, "rdkit_enumerate_v1",
                           {"inspection_handle": inspection, "site_atoms": [5], "use_fixed": True}).json()
    assert site_refusal["detail"]["site_check"]["crossing_bonds"] and site_refusal["detail"]["site_check"]["valid"] is False
    for unsafe in ("module", "executable", "argv", "env"):
        response = _submit(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": parent, unsafe: "x"})
        assert response.status_code == 422
    assert _submit(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": parent}, timeout_s=121).status_code == 422
    for tool in ("rdkit_inspect_ligand", "rdkit_enumerate_ligands"):
        assert client.post(f"/runs/{rid}/commands", json={"tool": tool, "args": {}}).status_code in {412, 422}
    after = _events(root, rid)
    assert len([e for e in after if e["type"] == "job_submitted"]) == jobs_before
    assert [e for e in after if e["type"] == "budget_reserved"] == [e for e in before if e["type"] == "budget_reserved"]


def test_wrong_or_foreign_handles_never_reach_the_worker(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M17 no implementation call")
    parent, smiles, _ = _imports(client, rid)
    other = _new_run(client, "M17 other")
    foreign = _import(client, other, "building_blocks_smiles", "blocks.smi", SMI)
    calls = []
    monkeypatch.setattr(ligand_bundle, "stage", lambda *a, **k: calls.append("stage"))
    monkeypatch.setattr(ligand_bundle, "publish", lambda *a, **k: calls.append("publish"))
    monkeypatch.setattr(JobQueue, "_supervise", lambda *a, **k: calls.append("supervise"))
    monkeypatch.setattr(ligand_bundle, "_handshake", lambda: calls.append("handshake"))
    for args in ({"parent_sdf_handle": parent, "block_handles": [foreign]}, {"parent_sdf_handle": smiles}):
        assert _submit(client, rid, "rdkit_inspect_v1", args).status_code == 422
    assert _submit(client, rid, "rdkit_enumerate_v1", {"inspection_handle": parent, "site_atoms": [11, 12],
                                                       "use_fixed": True}).status_code == 422
    assert calls == []
    assert not any(e["type"] == "job_submitted" for e in _events(root, rid))


# ----------------------------------------------------------------- typed worker failures
@pytest.mark.parametrize("case,reason", [("disconnected", "multiple_fragments"), ("two_records", "record_count")])
def test_parent_rejection_is_a_typed_charged_failure_without_objects(tmp_path, monkeypatch, case, reason):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, f"M17 parent rejection {case}")
    raw = (CHEM_FIX / "synthetic-disconnected-methane-water.sdf").read_bytes() if case == "disconnected" else NO_H + NO_H
    parent = _import(client, rid, "ligand_sdf", "parent.sdf", raw)
    failed = _run_job(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": parent})
    assert failed["status"] == "failed" and failed["output_handles"] == []
    assert failed["failure"]["error"] == "input_invalid" and failed["failure"]["reason_code"] == reason
    assert failed["cleanup_status"] == "verified" and _used(client, rid) == 1
    assert _ligand_objects(root, rid) == []
    _workers_gone(root, rid)


def test_cancel_during_worker_and_timeout_store_nothing(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M17 cancel and timeout")
    parent, smiles, sdf = _imports(client, rid)
    original = JobQueue._record_control
    seen: list[int] = []

    def cancel_when_started(self, message, job_id, attempt_id, nonce):
        done = original(self, message, job_id, attempt_id, nonce)
        if message and message.get("kind") == "STARTED" and not seen:
            seen.append(message["pid"])
            self.request_cancel(job_id)
        return done

    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_record_control", cancel_when_started)
        cancelled = _run_job(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [smiles]})
    assert cancelled["status"] == "cancelled" and cancelled["output_handles"] == [] and seen
    assert cancelled["cleanup_status"] == "verified"
    timed_out = _run_job(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [sdf]},
                         timeout_s=0.2)
    assert timed_out["status"] == "failed" and timed_out["failure"]["error"] == "resource_exceeded"
    assert timed_out["failure"]["message"] == "job timeout" and timed_out["output_handles"] == []
    assert _used(client, rid) == 2 and _ligand_objects(root, rid) == []
    time.sleep(0.1)
    _workers_gone(root, rid)


def test_cancel_after_genuine_worker_or_tampered_output_publishes_nothing(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M17 publication guards")
    parent, smiles, _ = _imports(client, rid)
    original = JobQueue._supervise

    def cancel_after(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch):
        result, identity = original(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch)
        assert result and result.get("returncode") == 0
        self.request_cancel(job["job_id"])
        return result, identity

    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_supervise", cancel_after)
        response = _run_job(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": parent})
    assert response["status"] == "cancelled" and _ligand_objects(root, rid) == []

    def tamper(mutate):
        def supervise(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch):
            result, identity = original(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch)
            data = json.loads((attempt_dir / "result.json").read_bytes())
            mutate(data)  # labeled fault: genuine worker output altered after the run, descriptor re-signed
            raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            (attempt_dir / "result.json").write_bytes(raw)
            import hashlib
            result["payload"] = {"output_sha256": hashlib.sha256(raw).hexdigest(), "output_bytes": len(raw)}
            return result, identity
        return supervise

    faults = [lambda d: d.update(attempt_id="attempt_other"),
              lambda d: d["parent"]["properties"].update(hbd=-1),
              lambda d: d["rules"].append({"rule_id": "user_1", "status": "valid", "text": "x", "text_sha256": "0"}),
              lambda d: d["parent"].update(svg=d["parent"]["svg"] + "<script>x</script>")]
    for index, fault in enumerate(faults):
        with monkeypatch.context() as patch:
            patch.setattr(JobQueue, "_supervise", tamper(fault))
            failed = _run_job(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [smiles],
                                                                "rules": RULES[:index + 1]})
        assert failed["status"] == "failed" and failed["failure"]["message"] == "invalid scientific output", failed
    assert _ligand_objects(root, rid) == []


# ----------------------------------------------------------------- caps, dry-run, capability
@pytest.mark.parametrize("limits,stop", [({"max_candidates": 3, "max_attempts": C.MAX_ATTEMPTS}, "candidate_limit"),
                                         ({"max_candidates": C.MAX_CANDIDATES, "max_attempts": 5}, "attempt_limit")])
def test_cap_reached_is_the_only_partial_result_stored(tmp_path, monkeypatch, limits, stop):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, f"M17 {stop}")
    parent, smiles, _ = _imports(client, rid)
    inspection = _run_job(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": parent,
                                                            "block_handles": [smiles]})["output_handles"][0]
    monkeypatch.setattr(ligand_bundle, "ENUMERATE_LIMITS", limits)  # labeled internal hook (not a request field)
    done = _run_job(client, rid, "rdkit_enumerate_v1", {"inspection_handle": inspection, "site_atoms": [11, 12],
                                                        "use_fixed": True})
    assert done["status"] == "done", done
    content, _ = ligand_bundle.validated_candidate_set(api_module._run(rid), done["output_handles"][0])
    assert content["limit_reached"] is True and content["stop_reason"] == stop and content["limits"] == limits
    assert content["counts"]["candidates"] == (3 if stop == "candidate_limit" else 4)
    assert content["counts"]["raw_products"] == (4 if stop == "candidate_limit" else 5)


def test_large_imports_stage_above_the_generic_lane_bound(tmp_path, monkeypatch):
    """Two ~9.9 MiB block files (labeled synthetic padding: comment lines / trailing blank lines) stage ~26 MiB."""
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M17 large staged input")
    parent = _import(client, rid, "ligand_sdf", "parent.sdf", NO_H)
    pad = 10 * 1024 * 1024 - 4096
    smiles_raw = b"*C big_methyl\n" + b"#" + b"x" * (pad - 16) + b"\n"
    sdf_raw = SDF.split(b"$$$$")[0] + b"$$$$\n" + b"\n" * (pad - len(SDF.split(b"$$$$")[0]) - 5)
    smiles = _import(client, rid, "building_blocks_smiles", "big.smi", smiles_raw)
    sdf = _import(client, rid, "building_blocks_sdf", "big.sdf", sdf_raw)
    done = _run_job(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [smiles, sdf]})
    assert done["status"] == "done", done
    staged = root / rid / "jobs" / done["job_id"] / done["attempt_id"] / "structure.json"
    assert 4_000_000 < staged.stat().st_size <= ligand_bundle.STAGED_LIMIT
    libraries = ligand_bundle.validated_inspection(api_module._run(rid), done["output_handles"][0])["block_libraries"]
    assert [(lib["records_total"], lib["accepted"]) for lib in libraries] == [(1, 1), (1, 1)]


def test_inspection_over_its_size_bound_is_a_typed_failure(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M17 inspection size bound")
    parent, _, _ = _imports(client, rid)
    monkeypatch.setattr(ligand_bundle, "MAX_INSPECTION_BYTES", 1000)  # labeled internal hook: bound lowered
    failed = _run_job(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": parent})
    assert failed["status"] == "failed" and failed["output_handles"] == []
    assert (failed["failure"]["error"], failed["failure"]["reason_code"]) == ("resource_exceeded",
                                                                            "inspection_size_limit")
    assert _ligand_objects(root, rid) == [] and _used(client, rid) == 1


def test_dry_run_plans_only_without_objects(tmp_path):
    run = new_ligand_run(tmp_path / "dry", "run_dry_ligand", dry_run=True)
    parent = import_file(run, "ligand_sdf", "parent.sdf", NO_H)
    blocks = import_file(run, "building_blocks_smiles", "blocks.smi", SMI)
    plan = JobQueue(run).submit("rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [blocks]},
                                timeout_s=120)
    assert plan["plan_only"] is True and plan["reason_code"] == "dry_run" and plan["output_handles"] == []
    assert plan["normalized_parameters"] == {"parent_sdf_handle": parent, "block_handles": [blocks], "rules": []}
    events = list(run.events.read())
    assert not any(e["type"] in {"job_submitted", "budget_reserved"} for e in events)
    assert not any(e["type"] == "object_created" and e["kind"] in LIGAND_KINDS for e in events)


def test_unavailable_environment_refuses_without_charge(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M17 environment missing")
    parent, _, _ = _imports(client, rid)
    queued = _submit(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": parent}).json()
    monkeypatch.setattr(ligand_bundle, "WORKER_PYTHON", tmp_path / "missing/python")
    missing = ligand_bundle.capability()
    assert missing["available"] is False and missing["reason_code"] == "worker_missing" and missing["pins"] is None
    refused = _submit(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "rules": ["[C:1]>>[C:1]"]})
    assert refused.status_code == 412 and refused.json()["detail"]["reason_code"] == "worker_missing"
    blocked = _approve_start(client, rid, queued["job_id"], "rdkit_inspect_ligand")
    assert blocked.status_code == 412
    assert _used(client, rid) == 0 and not any(e["type"] == "job_dispatch_intent" for e in _events(root, rid))
    monkeypatch.undo()
    ligand_bundle._HANDSHAKE_CACHE.clear()
    monkeypatch.setattr(ligand_bundle, "_handshake", lambda: _fake_handshake("2026.03.5"))
    assert ligand_bundle.capability()["reason_code"] == "rdkit_version_mismatch"
    monkeypatch.setattr(ligand_bundle, "_handshake", lambda: _fake_handshake("2026.03.6", pains={"PAINS_A": 0}))
    assert ligand_bundle.capability()["reason_code"] == "pains_catalog_unavailable"
    monkeypatch.setattr(ligand_bundle, "_handshake", lambda: (_ for _ in ()).throw(ValueError("bad")))
    assert ligand_bundle.capability()["reason_code"] == "handshake_failed"
    monkeypatch.undo()
    ligand_bundle._HANDSHAKE_CACHE.clear()
    assert ligand_bundle.capability()["available"] is True


def _fake_handshake(version: str, pains: dict | None = None) -> dict:
    """Labeled fake handshake record for capability-state tests (never a scientific result)."""
    return {"schema": "ligand_worker_handshake@1", "rdkit_version": version, "rdkit_version_expected": "2026.03.6",
            "pains_catalog_entries": pains or {"PAINS_A": 16, "PAINS_B": 55, "PAINS_C": 409},
            "protocols": ["rdkit_inspect_v1", "rdkit_enumerate_v1"], "worker_sha256": "0" * 64, "python": "3.11.11"}
