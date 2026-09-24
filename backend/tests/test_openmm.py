"""Real public inputs; the queue publication test simulates guardian control only."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import gemmi
import pytest
from fastapi.testclient import TestClient

from mw.core.errors import ToolFailure
from mw.jobs.openmm_worker import run as engine_run
from mw.jobs.openmm_worker import write_preparation
from mw.jobs.process_identity import KIND, VERSION, IdentityUnavailable, matches
from mw.jobs.queue import JobQueue
from mw.openmm_reports import (
    build_openmm_report,
    saved_openmm_report,
    validate_openmm_claim,
    validated_minimized_structure,
    validated_openmm,
)
from mw.reports import EvidenceError
from mw.runtime.orchestrator import ApprovalRequired
from mw.tools.openmm_method import capability, dependencies, preflight
from mw.workspace import new_run

FIXTURES = Path(__file__).parent / "fixtures"


def _prepared(tmp_path: Path, name: str = "public_1ubq.cif", waters: str = "keep_all"):
    run = new_run(tmp_path, dry_run=False, run_id="run_openmm")
    source = run.call("load_structure", {"source": name, "model_index": 0},
                      source_bytes=(FIXTURES / name).read_bytes(), source_format="cif")
    prepared = run.call("prepare_structure", {
        "structure": source.handle, "altloc": "highest_occupancy", "waters": waters,
        "hydrogens": "strip", "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
    return run, prepared.handle


def test_engine_mapping_and_potential_on_public_1ubq(tmp_path: Path):
    run, structure = _prepared(tmp_path)
    selected = preflight(run.store, structure, seed=run.seed)
    assert selected["heavy_atom_count"] == 602
    assert len(selected["excluded"]) == 58
    assert selected["method"]["distribution_version"] == "8.6.0"
    assert selected["method"]["engine_build"].startswith("8.6.0")
    assert len(selected["method"]["forcefield_files_sha256"]) >= 5
    output = engine_run(selected)
    assert len(output["atom_mapping"]) == 1231
    assert len(output["added_hydrogens"]) == 629
    assert output["before_kJ_mol"] > output["after_kJ_mol"]
    assert output["potential_change_kJ_mol"] == pytest.approx(output["after_kJ_mol"] - output["before_kJ_mol"])
    assert output["iterations"] is None and output["convergence"] == "convergence_not_claimed"
    assert output["input_cif"] != output["final_cif"]


def test_fsynced_preparation_exists_before_first_protocol_energy_call(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace

    import mw.jobs.openmm_worker as worker
    from mw.openmm_bundle import validate_preparation

    run, structure = _prepared(tmp_path)
    selected = preflight(run.store, structure, seed=run.seed)
    attempt = tmp_path / "private_attempt"
    attempt.mkdir()
    fsyncs = []
    real_fsync = os.fsync

    def fsync(fd):
        fsyncs.append(fd)
        return real_fsync(fd)

    def first_potential(*args, **kwargs):
        assert kwargs.get("getEnergy") is True
        checkpoint = attempt / "preparation.json"
        assert checkpoint.is_file() and not (attempt / "preparation.tmp").exists()
        data = json.loads(checkpoint.read_bytes())
        validate_preparation(run.store, selected, data, data["system_xml"].encode())
        assert len(fsyncs) >= 2  # complete file and containing directory
        assert not any(key.endswith("kJ_mol") for key in data)
        raise RuntimeError("controlled failure before protocol potential evaluation")

    monkeypatch.setattr(worker.os, "fsync", fsync)
    monkeypatch.setattr(worker.app, "Simulation", lambda *a, **k: SimpleNamespace(
        context=SimpleNamespace(setPositions=lambda *_: None, getState=first_potential)))
    with pytest.raises(RuntimeError, match="controlled failure"):
        engine_run(selected, on_prepared=lambda item: write_preparation(item, attempt))
    assert (attempt / "preparation.json").is_file()
    assert not (attempt / "result.json").exists()


@pytest.mark.parametrize("checkpoint", ["complete", "missing", "tampered"])
def test_failed_attempt_retains_only_complete_preparation(tmp_path: Path, monkeypatch, checkpoint: str):
    import mw.jobs.openmm_worker as worker

    run, structure = _prepared(tmp_path)
    queue = JobQueue(run)
    job = queue.submit("openmm_protein_minimize", {"structure": structure,
                       "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"})
    run.approve("expensive_first_call")

    def stop_before_energy(*args, **kwargs):
        raise RuntimeError("controlled energy-stage failure")

    def supervise(record, attempt_id, nonce, directory, deadline, dispatch):
        if checkpoint != "missing":
            monkeypatch.setattr(worker.app, "Simulation", stop_before_energy)
            with pytest.raises(RuntimeError, match="controlled energy-stage failure"):
                engine_run(record["selected"], on_prepared=lambda item: write_preparation(item, directory))
            if checkpoint == "tampered":
                (directory / "preparation.json").write_bytes(b"{\"schema\":\"incomplete\"}")
        return {"kind": "RESULT", "reason": "timeout", "clean": True,
                "direct_child_reaped": True}, None

    monkeypatch.setattr(queue, "_supervise", supervise)
    failed = queue.start(job["job_id"])
    assert failed["status"] == "failed" and failed["output_handles"] == []
    assert failed["failure"]["error"] == "resource_exceeded"
    prep_events = [e for e in run.events.read() if e["type"] == "job_preparation_recorded"]
    assert len(prep_events) == (1 if checkpoint == "complete" else 0)
    assert failed["preparation_handle"] == (prep_events[0]["handles"]["manifest"] if prep_events else None)
    assert run.budget.expensive_calls == 1
    if checkpoint == "complete":
        saved = {name: run.store.load(handle) for name, handle in prep_events[0]["handles"].items()}
        shutil.rmtree(run.run_dir / "objects")
        shutil.rmtree(run.run_dir / "jobs")
        (run.run_dir / "index.sqlite").unlink(missing_ok=True)
        (run.run_dir / "jobs.sqlite").unlink(missing_ok=True)
        reopened = new_run(tmp_path, dry_run=False, run_id=run.run_id)
        monkeypatch.setattr("mw.tools.openmm_method.dependencies", lambda: (_ for _ in ()).throw(AssertionError("engine initialized")))
        monkeypatch.setitem(sys.modules, "openmm", None)
        monkeypatch.setitem(sys.modules, "openmm.app", None)
        recovered = JobQueue(reopened, popen=lambda *a, **k: (_ for _ in ()).throw(AssertionError("process launched")))
        assert recovered.get(job["job_id"])["preparation_handle"] == failed["preparation_handle"]
        assert all(reopened.store.load(prep_events[0]["handles"][name]) == value for name, value in saved.items())
        recovered.reconcile_run()
        recovered.reconcile_run()
        assert len([e for e in reopened.events.read() if e["type"] == "job_preparation_recorded"]) == 1


@pytest.mark.parametrize("checkpoint,terminal", [
    ({}, "failed"),
    ({"system_xml": None}, "cancelled"),
    ({"system_xml": []}, "interrupted"),
    ({"schema": "openmm_preparation_checkpoint@1", "method": {}, "selected_sha256": "x",
      "input_cif": "data_bad", "input_positions_A": [], "system_xml": "<System/>",
      "system_xml_sha256": "x", "topology_sha256": "x", "heavy_atoms": 1,
      "added_hydrogens": [], "atom_mapping": [None], "residue_mapping": [],
      "source_bonds": [], "final_bonds": [], "protonation_variants": [],
      "disulfide_bonds": []}, "failed"),
])
def test_malformed_preparation_checkpoint_keeps_terminal_and_charge(
        tmp_path: Path, monkeypatch, checkpoint: dict, terminal: str):
    from mw.core.handles import canonical_json

    run, structure = _prepared(tmp_path)
    queue = JobQueue(run)
    job = queue.submit("openmm_protein_minimize", {"structure": structure,
                       "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"})
    run.approve("expensive_first_call")

    def supervise(record, attempt_id, nonce, directory, deadline, dispatch):
        (directory / "preparation.json").write_bytes(canonical_json(checkpoint))
        if terminal == "interrupted":
            raise SystemExit("injected parent loss after malformed checkpoint")
        return {"kind": "RESULT", "reason": "cancelled" if terminal == "cancelled" else "timeout",
                "clean": True, "direct_child_reaped": True}, None

    monkeypatch.setattr(queue, "_supervise", supervise)
    if terminal == "interrupted":
        with pytest.raises(SystemExit, match="injected parent loss"):
            queue.start(job["job_id"])
        monkeypatch.setattr(queue, "_read_receipt", lambda record: {"pgid": 99999999})
        monkeypatch.setattr("mw.jobs.queue._same_identity", lambda identity: False)
        monkeypatch.setattr("mw.jobs.queue._members", lambda pgid: [])
        result = queue.reconcile_run()[0]
    else:
        result = queue.start(job["job_id"])
    assert result["status"] == terminal and result["output_handles"] == []
    assert result["preparation_handle"] is None
    events = list(run.events.read())
    assert len([e for e in events if e["type"] == "job_cleanup_verified" and
                e.get("job_id") == job["job_id"] and e.get("group_empty") is True]) == 1
    assert not any(e["type"] == "job_preparation_recorded" for e in events)
    assert run.budget.expensive_calls == 1


def test_orphan_reconciliation_ingests_checkpoint_once_without_engine_or_launch(tmp_path: Path, monkeypatch):
    """Unit-level owner-loss injection; physical parent-loss is tested separately."""
    import mw.jobs.openmm_worker as worker

    run, structure = _prepared(tmp_path)
    queue = JobQueue(run)
    job = queue.submit("openmm_protein_minimize", {"structure": structure,
                       "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"})
    run.approve("expensive_first_call")

    def stop_before_energy(*args, **kwargs):
        raise RuntimeError("controlled energy-stage failure")

    def lose_owner(record, attempt_id, nonce, directory, deadline, dispatch):
        monkeypatch.setattr(worker.app, "Simulation", stop_before_energy)
        with pytest.raises(RuntimeError, match="controlled energy-stage failure"):
            engine_run(record["selected"], on_prepared=lambda item: write_preparation(item, directory))
        raise SystemExit("injected parent loss after complete checkpoint")

    monkeypatch.setattr(queue, "_supervise", lose_owner)
    with pytest.raises(SystemExit, match="injected parent loss"):
        queue.start(job["job_id"])
    assert queue.get(job["job_id"])["status"] == "running"
    monkeypatch.setattr(queue, "_read_receipt", lambda record: {"pgid": 99999999})
    monkeypatch.setattr("mw.jobs.queue._same_identity", lambda identity: False)
    monkeypatch.setattr("mw.jobs.queue._members", lambda pgid: [])
    monkeypatch.setattr(queue, "_popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("process launched")))
    first = queue.reconcile_run()[0]
    assert first["status"] == "interrupted" and first["output_handles"] == []
    event = next(e for e in run.events.read() if e["type"] == "job_preparation_recorded")
    assert first["preparation_handle"] == event["handles"]["manifest"]
    before = list(run.events.read())
    queue.reconcile_run()
    assert len([e for e in run.events.read() if e["type"] == "job_preparation_recorded"]) == 1
    assert len([e for e in run.events.read() if e["type"] == "job_terminal"]) == 1
    assert len(list(run.events.read())) == len(before)
    shutil.rmtree(run.run_dir / "objects")
    shutil.rmtree(run.run_dir / "jobs")
    (run.run_dir / "index.sqlite").unlink(missing_ok=True)
    (run.run_dir / "jobs.sqlite").unlink(missing_ok=True)
    reopened = new_run(tmp_path, dry_run=False, run_id=run.run_id)
    monkeypatch.setitem(sys.modules, "openmm", None)
    monkeypatch.setitem(sys.modules, "openmm.app", None)
    restored = JobQueue(reopened, popen=lambda *a, **k: (_ for _ in ()).throw(AssertionError("process launched")))
    assert restored.get(job["job_id"])["preparation_handle"] == first["preparation_handle"]
    assert reopened.store.load(event["handles"]["system_xml"])
    assert reopened.store.load(event["handles"]["input_coordinates"])


def test_missing_oxt_and_invalid_policy_do_not_launch(tmp_path: Path):
    run, structure = _prepared(tmp_path, "public_1hsg.cif")
    queue = JobQueue(run)
    with pytest.raises(Exception, match="missing terminal OXT"):
        queue.submit("openmm_protein_minimize", {"structure": structure,
                     "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"})
    with pytest.raises(Exception, match="one of"):
        queue.submit("openmm_protein_minimize", {"structure": structure,
                     "selection_policy": "all_atoms", "hydrogen_policy": "rebuild_pH7"})
    assert run.budget.expensive_calls == 0 and queue.list() == []


def test_water_removed_by_earlier_preparation_remains_disclosed(tmp_path: Path):
    run, structure = _prepared(tmp_path, waters="strip_all")
    selected = preflight(run.store, structure, seed=run.seed)
    assert len(selected["excluded"]) == 58
    assert all(item["reason"] == "water_removed_during_preparation" for item in selected["excluded"])


@pytest.mark.parametrize("change,reason", [("modified", "unsupported polymer"),
                                            ("missing_sidechain", "heavy atoms do not match")])
def test_modified_or_missing_heavy_atom_rejected_before_launch(tmp_path: Path, change: str, reason: str):
    st = gemmi.make_structure_from_block(gemmi.cif.read_file(str(FIXTURES / "public_1ubq.cif")).sole_block())
    first = st[0][0][0]
    if change == "modified":
        first.name = "MSE"
    else:
        del first[4]  # MET CB heavy atom
    raw = st.make_mmcif_document().as_string().encode()
    run = new_run(tmp_path, dry_run=False, run_id="run_modified")
    source = run.call("load_structure", {"source": "fixture.cif", "model_index": 0},
                      source_bytes=raw, source_format="cif")
    prepared = run.call("prepare_structure", {"structure": source.handle,
                        "altloc": "highest_occupancy", "waters": "keep_all", "hydrogens": "strip",
                        "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
    with pytest.raises(Exception, match=reason):
        JobQueue(run).submit("openmm_protein_minimize", {"structure": prepared.handle,
                             "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"})
    assert run.budget.expensive_calls == 0


def test_queue_report_replay_with_simulated_supervisor(tmp_path: Path, monkeypatch):
    import copy

    run, structure = _prepared(tmp_path)
    queue = JobQueue(run)
    args = {"structure": structure, "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}
    job = queue.submit("openmm_protein_minimize", args)
    assert queue.submit("openmm_protein_minimize", args)["job_id"] == job["job_id"]
    with pytest.raises(ApprovalRequired):
        queue.start(job["job_id"])
    assert run.budget.expensive_calls == 0
    run.approve("expensive_first_call")

    def supervise(record, attempt_id, nonce, directory, deadline, dispatch):
        control = json.loads((directory / "input.json").read_text())
        raw = (directory / "structure.json").read_bytes()
        assert control["input_sha256"] == hashlib.sha256(raw).hexdigest()
        output = engine_run(json.loads(raw), on_prepared=lambda item: write_preparation(item, directory))
        result = json.dumps(output, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        (directory / "result.json").write_bytes(result)
        with pytest.raises(ValueError, match="hash mismatch"):
            queue._publish_openmm(record, attempt_id, directory,
                                  {"output_sha256": "0" * 64, "output_bytes": len(result)})
        malformed = {**output, "heavy_atoms": 1}
        wrong = json.dumps(malformed, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        (directory / "result.json").write_bytes(wrong)
        with pytest.raises(ValueError, match="mismatch"):
            queue._publish_openmm(record, attempt_id, directory,
                                  {"output_sha256": hashlib.sha256(wrong).hexdigest(), "output_bytes": len(wrong)})
        (directory / "result.json").write_bytes(result)
        return {"kind": "RESULT", "nonce": nonce, "job_id": record["job_id"],
                "attempt_id": attempt_id, "reason": "completed", "returncode": 0,
                "unexpected_members": False, "clean": True, "direct_child_reaped": True,
                "payload": {"output_sha256": hashlib.sha256(result).hexdigest(), "output_bytes": len(result)}}, None

    monkeypatch.setattr(queue, "_supervise", supervise)
    done = queue.start(job["job_id"])
    assert done["status"] == "done"
    preparation_event = next(e for e in run.events.read() if e["type"] == "job_preparation_recorded")
    assert done["preparation_handle"] == preparation_event["handles"]["manifest"]
    assert run.budget.expensive_calls == 1
    result = validated_openmm(run, done["output_handles"][0])
    assert result["preparation_manifest"] == preparation_event["handles"]["manifest"]
    assert result["system_xml"] == preparation_event["handles"]["system_xml"]
    assert result["input_coordinates"] == preparation_event["handles"]["input_coordinates"]
    assert result["atom_count"] == 1231 and len(result["excluded"]) == 58
    assert validated_minimized_structure(run, result["minimized_structure"]) == result
    report = build_openmm_report(run, done["output_handles"][0])
    assert saved_openmm_report(run, report["handle"])["markdown"] == report["markdown"]
    for field, replacement in (("system_xml_sha256", "0" * 64), ("topology_sha256", "0" * 64),
                               ("atom_count", 1231.0), ("source_handle", "foreign"),
                               ("excluded", []), ("job_id", "foreign"), ("seed", False)):
        altered = {**result, field: replacement}
        candidate = run.store.put("openmm_minimization", "openmm_protein_minimization@1", altered,
                                  produced_by="test_malformed_saved")
        with pytest.raises(EvidenceError):
            validated_openmm(run, candidate.handle)
    bad_cif = run.store.put("openmm_final_coordinates", "openmm_final_coordinates@1",
                            b"data_not_a_molecule\n", fmt="cif", produced_by="test_malformed_saved")
    bad_structure = run.store.put("openmm_minimized_structure", "openmm_minimized_structure@1",
                                  {**run.store.load(result["minimized_structure"]), "coordinates": bad_cif.handle},
                                  produced_by="test_malformed_saved")
    candidate = run.store.put("openmm_minimization", "openmm_protein_minimization@1",
                              {**result, "final_coordinates": bad_cif.handle,
                               "minimized_structure": bad_structure.handle}, produced_by="test_malformed_saved")
    with pytest.raises(EvidenceError):
        validated_openmm(run, candidate.handle)
    for field, replacement in (("system_xml_sha256", "0" * 64), ("topology_sha256", "0" * 64),
                               ("excluded", []), ("protonation_variants", []),
                               ("source_hydrogens_removed", ["foreign"]), ("attempt_id", "foreign"),
                               ("preparation_manifest", "foreign"), ("seed", -1)):
        altered_report = copy.deepcopy(report["manifest"])
        altered_report[field] = replacement
        bogus = run.store.put("method_report_manifest", "method_report_manifest@1", altered_report,
                              produced_by="test_malformed_saved")
        run.events.append("method_report_created", report_handle=bogus.handle,
                          markdown_handle=report["markdown_handle"], result_handle=done["output_handles"][0],
                          snapshot_event_seq=altered_report["snapshot"]["event_seq"])
        with pytest.raises(EvidenceError):
            saved_openmm_report(run, bogus.handle)
    evidence = report["manifest"]["claims"][0]
    assert validate_openmm_claim(run, evidence) == evidence
    for key, value in (("unit", "A2"), ("field_path", "after_kJ_mol"), ("rendered_value", "0.00"),
                       ("source_kind", "job_lifecycle"), ("subject", {**evidence["subject"], "job_id": "foreign"})):
        with pytest.raises(EvidenceError):
            validate_openmm_claim(run, {**evidence, key: value})
    assert queue.submit("openmm_protein_minimize", args)["status"] == "done"
    assert run.budget.expensive_calls == 1
    shutil.rmtree(run.run_dir / "objects")
    shutil.rmtree(run.run_dir / "jobs")
    (run.run_dir / "index.sqlite").unlink(missing_ok=True)
    (run.run_dir / "jobs.sqlite").unlink(missing_ok=True)
    reopened = new_run(tmp_path, dry_run=False, run_id=run.run_id)
    monkeypatch.setattr("mw.jobs.openmm_worker.run", lambda _: (_ for _ in ()).throw(AssertionError("engine reran")))
    monkeypatch.setattr("mw.tools.openmm_method.dependencies", lambda: (_ for _ in ()).throw(AssertionError("engine initialized")))
    monkeypatch.setitem(sys.modules, "openmm", None)
    monkeypatch.setitem(sys.modules, "openmm.app", None)
    assert saved_openmm_report(reopened, report["handle"])["markdown"] == report["markdown"]
    assert validated_minimized_structure(reopened, result["minimized_structure"]) == result
    restored = JobQueue(reopened, popen=lambda *a, **k: (_ for _ in ()).throw(AssertionError("process launched"))).get(job["job_id"])
    assert restored["status"] == "done" and restored["preparation_handle"] == result["preparation_manifest"]
    assert reopened.store.load(preparation_event["handles"]["input_coordinates"])
    assert reopened.store.load(preparation_event["handles"]["system_xml"])


def test_dependencies_and_public_fixture_hashes():
    dep = dependencies()
    assert dep["platform"] == "CPU" and dep["platform_properties"] == {"Threads": "1"}
    assert dep["forcefield_files_sha256"]["amber14-all.xml"]
    assert hashlib.sha256((FIXTURES / "public_1ubq.cif").read_bytes()).hexdigest() == "056f98710cb2b36f633c45e41902a02eb446e82871da21ff2dd44f74a56ca0f6"
    assert hashlib.sha256((FIXTURES / "public_1hsg.cif").read_bytes()).hexdigest() == "d2ba73b5c4be05c45275571bbb4dd042347927f91c6c05038c0df5d1ce23c268"


def test_unavailable_raw_identity_removes_openmm_capability_before_dispatch(tmp_path: Path, monkeypatch):
    import mw.jobs.queue as queue_module
    import mw.tools.openmm_method as method

    run, structure = _prepared(tmp_path)
    queue = JobQueue(run)
    job = queue.submit("openmm_protein_minimize", {"structure": structure,
                       "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"})
    run.approve("expensive_first_call")
    queue.claim_next("owner")

    def unavailable():
        raise IdentityUnavailable("fixture unsupported raw process identity")

    monkeypatch.setattr(method, "supported", unavailable)
    assert capability()["available"] is False
    assert capability()["reason_code"] == "process_identity_unavailable"
    with pytest.raises(ToolFailure, match="fixture unsupported raw process identity") as preflight_error:
        preflight(run.store, structure, seed=run.seed)
    assert preflight_error.value.detail["reason_code"] == "process_identity_unavailable"
    monkeypatch.setattr(queue_module, "supported", unavailable)
    queue._popen = lambda *args, **kwargs: pytest.fail("unsupported identity launched a process")
    with pytest.raises(ToolFailure, match="fixture unsupported raw process identity") as launch_error:
        queue.execute_claim(job["job_id"], "owner")
    assert launch_error.value.detail["reason_code"] == "process_identity_unavailable"
    assert run.budget.expensive_calls == 0


def test_api_preflight_approval_timeout_and_cancel(tmp_path: Path, monkeypatch):
    import mw.api.app as api_module

    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path / "runs")
    api_module.RUNS.clear()
    client = TestClient(api_module.app)
    tool = next(item for item in client.get("/tools", params={"levels": "L3"}).json()
                if item["name"] == "openmm_protein_minimize")
    assert tool["execution_lane"] == "durable_job"
    rid = client.post("/runs", json={}).json()["run_id"]
    raw = (FIXTURES / "public_1ubq.cif").read_bytes()
    uploaded = client.post(f"/runs/{rid}/uploads", params={"filename": "public_1ubq.cif"}, content=raw).json()
    source = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure",
                         "args": {"source": uploaded["upload_id"], "model_index": 0}}).json()["handle"]["handle"]
    prepared = client.post(f"/runs/{rid}/commands", json={"tool": "prepare_structure", "args": {
        "structure": source, "altloc": "highest_occupancy", "waters": "keep_all", "hydrogens": "strip",
        "missing_residues": "leave_gaps", "symmetry_mates": "ignore"}}).json()["handle"]["handle"]
    assert client.get(f"/runs/{rid}/jobs/preflight", params={"structure": prepared}).json()["excluded"]
    assert client.post(f"/runs/{rid}/jobs/approve").status_code == 412
    body = {"protocol_id": "openmm_protein_minimize", "args": {"structure": prepared,
            "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}, "timeout_s": 60}
    assert client.post(f"/runs/{rid}/jobs", json={**body, "args": {**body["args"], "argv": ["bad"]}}).status_code == 422
    job = client.post(f"/runs/{rid}/jobs", json=body).json()
    assert job["status"] == "queued" and job["input_handles"] == [prepared]
    assert client.get(f"/runs/{rid}/jobs").json()[0]["input_handles"] == [prepared]
    assert client.get(f"/runs/{rid}/jobs/{job['job_id']}").json()["input_handles"] == [prepared]
    assert client.post(f"/runs/{rid}/jobs/{job['job_id']}/start").status_code == 409
    assert client.post(f"/runs/{rid}/jobs/approve").json()["approved"] is True

    def timeout(*args):
        return {"kind": "RESULT", "reason": "timeout", "clean": True, "direct_child_reaped": True}, None

    monkeypatch.setattr(JobQueue, "_supervise", timeout)
    failed = client.post(f"/runs/{rid}/jobs/{job['job_id']}/start").json()
    assert failed["status"] == "failed" and failed["failure"]["error"] == "resource_exceeded"
    assert failed["input_handles"] == [prepared]
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 1
    assert client.get(f"/runs/{rid}/jobs/{job['job_id']}").json()["status"] == "failed"
    assert client.post(f"/runs/{rid}/method_reports", json={"result_handle": source}).status_code == 422

    new_job = client.post(f"/runs/{rid}/jobs", json={**body, "timeout_s": 61}).json()
    assert new_job["job_id"] == job["job_id"] and new_job["status"] == "failed"
    retried = client.post(f"/runs/{rid}/jobs/{job['job_id']}/retry").json()
    assert retried["status"] == "queued" and retried["input_handles"] == [prepared]
    cancelled = client.post(f"/runs/{rid}/jobs/{job['job_id']}/cancel").json()
    assert cancelled["job"]["input_handles"] == [prepared]


def test_absent_openmm_is_http_precondition_without_reservation_or_launch(tmp_path: Path, monkeypatch):
    import mw.api.app as api_module

    runs_root = tmp_path / "runs"
    run, structure = _prepared(runs_root)
    monkeypatch.setattr(api_module, "RUNS_DIR", runs_root)
    api_module.RUNS.clear()
    monkeypatch.setitem(sys.modules, "openmm", None)
    monkeypatch.setattr("mw.tools.openmm_method._template_heavy",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("template imported")))
    monkeypatch.setattr(JobQueue, "_supervise",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("worker launched")))
    client = TestClient(api_module.app)
    preflight_response = client.get(f"/runs/{run.run_id}/jobs/preflight", params={"structure": structure})
    submit_response = client.post(f"/runs/{run.run_id}/jobs", json={
        "protocol_id": "openmm_protein_minimize", "args": {"structure": structure,
        "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}})
    for response in (preflight_response, submit_response):
        assert response.status_code == 412
        assert response.json()["detail"]["reason_code"] == "openmm_unavailable"
    assert JobQueue(run).list() == [] and run.budget.expensive_calls == 0


def test_preflight_rejects_internal_gap_and_broken_peptide_without_budget(tmp_path: Path):
    original = gemmi.make_structure_from_block(gemmi.cif.read_file(str(FIXTURES / "public_1ubq.cif")).sole_block())
    for mutation, reason in (("gap", "sequence gap"), ("geometry", "peptide C-N distance")):
        st = original.clone()
        chain = st[0][0]
        if mutation == "gap":
            for index, residue in enumerate(chain):
                if residue.seqid.num == 10:
                    del chain[index]
                    break
        else:
            residue = next(item for item in chain if item.seqid.num == 10)
            atom = next(item for item in residue if item.name == "N")
            atom.pos = gemmi.Position(atom.pos.x + 4, atom.pos.y, atom.pos.z)
        run = new_run(tmp_path / mutation, dry_run=False, run_id="run_gap")
        source = run.call("load_structure", {"source": "modified_fixture.cif"},
                          source_bytes=st.make_mmcif_document().as_string().encode(), source_format="cif")
        prepared = run.call("prepare_structure", {"structure": source.handle,
                            "waters": "keep_all", "hydrogens": "strip"})
        with pytest.raises(Exception, match=reason):
            JobQueue(run).submit("openmm_protein_minimize", {"structure": prepared.handle,
                                 "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"})
        assert run.budget.expensive_calls == 0


def test_native_bundle_rejects_malformed_worker_publication(tmp_path: Path):
    import copy

    from mw.openmm_bundle import validate_native

    run, structure = _prepared(tmp_path)
    selected = preflight(run.store, structure, seed=run.seed)
    output = engine_run(selected)
    system = output["system_xml"].encode()
    validate_native(run.store, selected, output, system)
    mutations = {
        "system_hash": lambda d: d.update(system_xml_sha256="0" * 64),
        "topology_hash": lambda d: d.update(topology_sha256="0" * 64),
        "empty_bonds": lambda d: d.update(final_bonds=[]),
        "foreign_residue": lambda d: d["residue_mapping"][0].update(seq_auth=9999),
        "not_a_cif": lambda d: d.update(final_cif="data_not_a_molecule\n"),
        "swapped_cif": lambda d: d.update(final_cif=d["input_cif"]),
        "float_count": lambda d: d.update(heavy_atoms=float(d["heavy_atoms"])),
        "false_count": lambda d: d.update(heavy_atoms=False),
        "wrong_variant": lambda d: d["protonation_variants"].__setitem__(0, "HIP"),
        "wrong_source_heavy": lambda d: d["atom_mapping"][0]["coordinates_A"].__setitem__(0, 999.0),
        "wrong_atom_index": lambda d: d["atom_mapping"][0].update(topology_index=1),
        "empty_forcefield_hashes": lambda d: d["method"].update(forcefield_files_sha256={}),
        "nonhex_forcefield_hash": lambda d: d["method"]["forcefield_files_sha256"].update({
            "amber14-all.xml": "z" * 64}),
    }
    queue = JobQueue(run)
    job = queue.submit("openmm_protein_minimize", {"structure": structure,
                       "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"})
    for name, mutate in mutations.items():
        bad = copy.deepcopy(output)
        mutate(bad)
        candidate_selected = copy.deepcopy(selected)
        if name in {"empty_forcefield_hashes", "nonhex_forcefield_hash"}:
            candidate_selected["method"] = copy.deepcopy(bad["method"])
        with pytest.raises((ValueError, TypeError, KeyError, IndexError), match=".+"):
            validate_native(run.store, candidate_selected, bad, bad["system_xml"].encode())
        folder = tmp_path / name
        folder.mkdir()
        raw = json.dumps(bad, allow_nan=False).encode()
        (folder / "result.json").write_bytes(raw)
        with pytest.raises((ValueError, TypeError, KeyError, IndexError), match=".+"):
            queue._publish_openmm(job, "attempt_fixture", folder,
                                  {"output_sha256": hashlib.sha256(raw).hexdigest(), "output_bytes": len(raw)})


@pytest.mark.skipif(__import__("test_jobs").os_enumeration() is False,
                    reason="Darwin sysctl process enumeration denied")
def test_real_openmm_guardian_success_timeout_and_midworker_cancel(tmp_path: Path):
    import threading
    import time

    from test_jobs import cleanup_fixture

    from mw.jobs.queue import _members

    for mode in ("success", "timeout", "cancel"):
        run, structure = _prepared(tmp_path / mode)
        queue = JobQueue(run)
        job = queue.submit("openmm_protein_minimize", {"structure": structure,
                           "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"},
                           timeout_s=3 if mode == "timeout" else 60)
        assert run.budget.expensive_calls == 0
        with pytest.raises(ApprovalRequired):
            queue.start(job["job_id"])
        run.approve("expensive_first_call")
        finished: list[dict] = []
        thread = threading.Thread(target=lambda q=queue, j=job, out=finished: out.append(q.start(j["job_id"])))
        thread.start()
        try:
            if mode == "cancel":
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline and not any(
                    e["type"] == "job_worker_started" and e.get("job_id") == job["job_id"] for e in run.events.read()
                ):
                    time.sleep(0.02)
                assert any(e["type"] == "job_worker_started" and e.get("job_id") == job["job_id"]
                           for e in run.events.read())
                assert queue.request_cancel(job["job_id"])["status"] == "accepted"
            thread.join(timeout=75)
            assert not thread.is_alive()
            result = finished[0]
            assert result["status"] == {"success": "done", "timeout": "failed", "cancel": "cancelled"}[mode]
            events = list(run.events.read())
            assert len([e for e in events if e["type"] == "budget_reserved" and
                        e.get("root_call_id") == job["job_id"]]) == 1
            assert any(e["type"] == "job_worker_started" and e.get("job_id") == job["job_id"] for e in events)
            assert result["cleanup_status"] == "verified" and _members(result["identity"]["pgid"]) == []
            if mode == "success":
                assert validated_openmm(run, result["output_handles"][0])["atom_count"] > 0
                assert build_openmm_report(run, result["output_handles"][0])["manifest"]["claims"]
                assert queue.submit("openmm_protein_minimize", {"structure": structure,
                    "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"})["job_id"] == job["job_id"]
            else:
                assert result["output_handles"] == []
        finally:
            if thread.is_alive():
                queue.request_cancel(job["job_id"])
                thread.join(timeout=5)
            cleanup_fixture(queue, job["job_id"])


@pytest.mark.skipif(__import__("test_jobs").os_enumeration() is False,
                    reason="Darwin sysctl process enumeration denied")
def test_real_worker_cancellation_after_durable_preparation(tmp_path: Path):
    import signal
    import threading
    import time

    import psutil
    from test_jobs import cleanup_fixture

    from mw.jobs.queue import _members
    from mw.openmm_bundle import validate_preparation

    run, structure = _prepared(tmp_path)
    started = threading.Event()
    release = threading.Event()

    def barrier(stage):
        if stage == "after_worker_started":
            started.set()
            assert release.wait(30)

    queue = JobQueue(run, barrier=barrier)
    job = queue.submit("openmm_protein_minimize", {"structure": structure,
                       "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}, timeout_s=60)
    run.approve("expensive_first_call")
    finished = []
    thread = threading.Thread(target=lambda: finished.append(queue.start(job["job_id"])))
    thread.start()
    try:
        assert started.wait(15)
        deadline = time.monotonic() + 20
        checkpoint = None
        while time.monotonic() < deadline:
            paths = list((run.run_dir / "jobs" / job["job_id"]).glob("attempt_*/preparation.json"))
            if paths:
                checkpoint = paths[0]
                break
            time.sleep(0.01)
        assert checkpoint is not None
        data = json.loads(checkpoint.read_bytes())
        validate_preparation(run.store, job["selected"], data, data["system_xml"].encode())
        observation = next(e for e in run.events.read() if e["type"] == "job_worker_started" and
                           e.get("job_id") == job["job_id"])
        owned = queue.get(job["job_id"])["identity"]
        worker = psutil.Process(observation["pid"])
        assert matches(worker.pid, observation["start_identity"])
        assert worker.uids().real == os.getuid() and os.getpgid(worker.pid) == owned["pgid"]
        os.kill(worker.pid, signal.SIGSTOP)
        assert queue.request_cancel(job["job_id"])["status"] == "accepted"
        release.set()
        thread.join(timeout=20)
        assert not thread.is_alive()
        stopped = finished[0]
        assert stopped["status"] == "cancelled" and stopped["output_handles"] == []
        assert stopped["preparation_handle"] is not None
        assert len([e for e in run.events.read() if e["type"] == "job_preparation_recorded"]) == 1
        assert run.budget.expensive_calls == 1 and _members(stopped["identity"]["pgid"]) == []
    finally:
        release.set()
        if thread.is_alive():
            queue.request_cancel(job["job_id"])
            thread.join(timeout=5)
        cleanup_fixture(queue, job["job_id"])


@pytest.mark.skipif(__import__("test_jobs").os_enumeration() is False,
                    reason="Darwin sysctl process enumeration denied")
def test_real_openmm_parent_loss_reconciles_after_worker_started(tmp_path: Path):
    import subprocess
    import sys
    import time

    from test_jobs import cleanup_fixture

    from mw.jobs.queue import _members

    run, structure = _prepared(tmp_path)
    queue = JobQueue(run)
    job = queue.submit("openmm_protein_minimize", {"structure": structure,
                       "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"})
    run.approve("expensive_first_call")
    script = '''import sys,time
from pathlib import Path
from mw.workspace import new_run
from mw.jobs.process_identity import matches, KIND, VERSION
from mw.jobs.queue import JobQueue
root=Path(sys.argv[1]); job_id=sys.argv[2]
def barrier(stage):
    if stage=="after_worker_started":
        marker=root/"openmm_parent_barrier"
        private_marker=root/f".openmm_parent_barrier.{job_id}.tmp"
        with private_marker.open("w") as stream:
            stream.write(stage)
        private_marker.replace(marker)
        while True: time.sleep(.02)
run=new_run(root,run_id="run_openmm",dry_run=False)
queue=JobQueue(run,barrier=barrier)
queue.start(job_id)
'''
    child = subprocess.Popen([sys.executable, "-c", script, str(tmp_path), job["job_id"]],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 15
        marker = tmp_path / "openmm_parent_barrier"
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.02)
        assert marker.read_text() == "after_worker_started"
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not any(e["type"] == "job_worker_started" for e in run.events.read()):
            time.sleep(0.02)
        assert any(e["type"] == "job_worker_started" for e in run.events.read())
        at_barrier = queue.get(job["job_id"])
        identity = at_barrier["identity"]
        assert _members(identity["pgid"])
        child.kill()
        child.wait(timeout=3)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = queue.reconcile_run()[0]
            if state["status"] in {"interrupted", "failed", "cancelled"}:
                break
            time.sleep(0.05)
        assert state["status"] == "interrupted" and state["output_handles"] == []
        assert _members(identity["pgid"]) == []
        assert run.budget.expensive_calls == 1
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3)
        cleanup_fixture(queue, job["job_id"])


def test_author_numbering_gaps_do_not_override_contiguous_label_and_geometry(tmp_path: Path):
    st = gemmi.make_structure_from_block(gemmi.cif.read_file(str(FIXTURES / "public_1ubq.cif")).sole_block())
    for residue in st[0][0]:
        residue.seqid = gemmi.SeqId(residue.seqid.num * 10, residue.seqid.icode)
    run = new_run(tmp_path, dry_run=False, run_id="run_auth_gap")
    source = run.call("load_structure", {"source": "renumbered_fixture.cif"},
                      source_bytes=st.make_mmcif_document().as_string().encode(), source_format="cif")
    prepared = run.call("prepare_structure", {"structure": source.handle,
                        "waters": "keep_all", "hydrogens": "strip"})
    selected = preflight(run.store, prepared.handle, seed=run.seed)
    refs = [r["residue"] for c in selected["protein"] for r in c["residues"]]
    assert refs[0]["seq_auth"] == 10 and refs[1]["seq_auth"] == 20
    assert refs[0]["seq_label"] == 1 and refs[1]["seq_label"] == 2


def test_worker_started_barrier_follows_durable_start_event(tmp_path: Path):
    run = new_run(tmp_path, dry_run=False, run_id="run_barrier")
    observed = []

    def barrier(stage: str) -> None:
        observed.append((stage, any(e["type"] == "job_worker_started" for e in run.events.read())))

    queue = JobQueue(run, barrier=barrier)
    assert queue._record_control({"kind": "STARTED", "nonce": "n", "job_id": "job_probe",
                                  "attempt_id": "attempt_probe", "pid": 123,
                                  "start_identity": {"kind": KIND, "platform": sys.platform, "psutil_version": VERSION, "value": 1.0}}, "job_probe", "attempt_probe", "n") is False
    assert observed == [("after_worker_started", True)]
