"""Full HTTP durable-chemistry integration with public fixture bytes."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest
from fastapi.testclient import TestClient

from mw import chemical_bundle
from mw.api import app as api_module
from mw.chemical_reports import _markdown as chemical_report_markdown
from mw.chemical_reports import _provenance as chemical_provenance
from mw.core.errors import FailureClass, ToolFailure
from mw.core.handles import canonical_json
from mw.jobs import queue as queue_module
from mw.jobs.process_identity import matches
from mw.jobs.queue import JobQueue, _global_worker_slot, chemical_capability, require_completed_chemical_handle
from mw.runtime.orchestrator import Run
from mw.workspace import new_run

FIX = Path(__file__).parent / "fixtures" / "chemical"


def test_job_capability_uses_scientific_dependency_validation(monkeypatch):
    expected = {"versions": {"prolif": "2.2.2"}, "worker_sha256": "w" * 64,
                "lock_sha256": "l" * 64}
    monkeypatch.setattr(chemical_bundle, "dependency", lambda: expected)
    available = chemical_capability()
    assert available["available"] is True
    assert available["ligand_sdf_variant"] == "V2000"
    assert available["worker_sha256"] == expected["worker_sha256"]
    assert available["dependency_manifest_sha256"] == expected["lock_sha256"]
    public = TestClient(api_module.app).get("/capabilities")
    assert public.status_code == 200
    assert public.json()["methods"]["chemical_interactions"]["ligand_sdf_variant"] == "V2000"

    def invalid_native_method():
        raise ToolFailure(FailureClass.precondition, "pinned native method mismatch",
                          detail={"reason_code": "chemical_worker_unavailable"})

    monkeypatch.setattr(chemical_bundle, "dependency", invalid_native_method)
    denied = chemical_capability()
    assert denied["available"] is False
    assert denied["ligand_sdf_variant"] == "V2000"
    assert denied["reason_code"] == "worker_version_invalid"
    assert "native method" in denied["reason"]


def test_identical_sdf_import_under_alternate_filename_keeps_immutable_handle(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path)
    api_module.RUNS.clear()
    client = TestClient(api_module.app)
    rid = client.post("/runs", json={"goal": "reimport selected SDF", "dry_run": False}).json()["run_id"]
    raw = (FIX / "prolif-vina-output.sdf").read_bytes()
    first = client.post(f"/runs/{rid}/chemical/imports",
                        params={"kind": "ligand_sdf", "filename": "public-prepared-ligands.sdf"},
                        content=raw, headers={"content-type": "application/octet-stream"})
    assert first.status_code == 201, first.text
    handle = first.json()["handle"]
    run = api_module._run(rid)
    before_meta = run.store.meta(handle)
    before_events = (tmp_path / rid / "events.jsonl").read_bytes()
    second = client.post(f"/runs/{rid}/chemical/imports",
                         params={"kind": "ligand_sdf", "filename": "m11-attach-ligand.sdf"},
                         content=raw, headers={"content-type": "application/octet-stream"})
    assert second.status_code == 201, second.text
    assert second.json()["handle"] == handle
    assert run.store.load(handle) == raw
    assert run.store.meta(handle) == before_meta
    assert (tmp_path / rid / "events.jsonl").read_bytes() == before_events


def test_preparation_manifest_reader_rejects_wrong_kind_and_foreign_source(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path)
    api_module.RUNS.clear()
    client = TestClient(api_module.app)
    first = client.post("/runs", json={"goal": "read own source", "dry_run": False}).json()["run_id"]
    second = client.post("/runs", json={"goal": "read foreign source", "dry_run": False}).json()["run_id"]
    store = api_module._run(first).store
    wrong = store.put("chemical_graph", "chemical_graph@1", {"fixture": True})
    source = store.put("chemical_structure", "chemical_structure@1", {"fixture": True})
    before_first = (tmp_path / first / "events.jsonl").read_bytes()
    before_second = (tmp_path / second / "events.jsonl").read_bytes()
    wrong_kind = client.get(f"/runs/{first}/chemical/preparation-manifests",
                            params={"source_handle": wrong.handle})
    foreign = client.get(f"/runs/{second}/chemical/preparation-manifests",
                         params={"source_handle": source.handle})
    malformed = client.get(f"/runs/{first}/chemical/preparation-manifests",
                           params={"source_handle": source.handle})
    assert [wrong_kind.status_code, foreign.status_code, malformed.status_code] == [422, 422, 422]
    unknown = "obj://" + first + "/chemical_raw_input/" + "0" * 64
    assert client.get(f"/runs/{first}/chemical/imports/inspect", params={"handle": unknown}).status_code == 422
    assert client.get(f"/runs/{second}/chemical/imports/atoms", params={
        "handle": source.handle, "model_number": 1}).status_code == 422
    assert client.get(f"/runs/{first}/chemical/graphs", params={"handle": unknown}).status_code == 422
    assert client.post(f"/runs/{first}/chemical/preview", json={"schema": "chemical_prepare_request@1",
                                                                        "mode": "create_new"}).status_code == 422
    assert (tmp_path / first / "events.jsonl").read_bytes() == before_first
    assert (tmp_path / second / "events.jsonl").read_bytes() == before_second


def test_identical_candidate_becomes_public_only_after_later_successful_attempt(tmp_path, monkeypatch):
    """Synthetic event fixture for ObjectStore's preserved first-creator identity."""
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path)
    api_module.RUNS.clear()
    run = new_run(tmp_path, run_id="run_candidate_retry", dry_run=False)
    api_module.RUNS[run.run_id] = run
    receptor = run.store.put("chemical_raw_input", "chemical_raw_input@1", b"receptor", fmt="raw")
    ligand = run.store.put("chemical_raw_input", "chemical_raw_input@1", b"ligand", fmt="raw")
    params = {"schema": "chemical_prepare_request@1", "mode": "create_new",
              "receptor_input_handle": receptor.handle, "ligand_sdf_handle": ligand.handle}
    attempt_a, attempt_b = "attempt_original", "attempt_retry"
    manifest = run.store.put("chemical_preparation_manifest", "chemical_preparation_manifest@1",
                             {"schema": "chemical_preparation_manifest@1", "request": params,
                              "source_handle": receptor.handle}, produced_by=attempt_a)
    source = run.store.put("chemical_structure", "chemical_structure@1", {"fixture": True},
                           produced_by=attempt_a)
    graph = run.store.put("chemical_graph", "chemical_graph@1", {"fixture": True},
                          produced_by=attempt_a)
    outputs = [manifest.handle, source.handle, graph.handle]

    def published(job_id: str, attempt_id: str, status: str) -> None:
        run.events.append("job_submitted", job={"job_id": job_id, "protocol_id": "prolif_prepare_v1",
                           "tool_id": "prepare_chemical_structure", "parameters": params,
                           "input_handles": [receptor.handle, ligand.handle]})
        run.events.append("budget_reserved", attempt_id=attempt_id, root_call_id=job_id,
                          tool="prepare_chemical_structure")
        run.events.append("job_dispatch_intent", job_id=job_id, attempt_id=attempt_id)
        run.events.append("job_cleanup_verified", job_id=job_id, attempt_id=attempt_id, group_empty=True)
        run.events.append("job_result_candidate", job_id=job_id, attempt_id=attempt_id,
                          output_handles=outputs)
        run.events.append("job_terminal", job_id=job_id, attempt_id=attempt_id,
                          status=status, output_handles=outputs if status == "done" else [])

    client = TestClient(api_module.app)
    published("job_original", attempt_a, "cancelled")
    assert client.get(f"/runs/{run.run_id}/objects/meta", params={"handle": source.handle}).status_code == 422
    with pytest.raises(ToolFailure):
        require_completed_chemical_handle(run, source.handle)
    published("job_retry", attempt_b, "done")
    admitted = require_completed_chemical_handle(run, source.handle)
    assert admitted["first_creator_attempt_id"] == attempt_a
    assert admitted["successful_publisher_attempt_id"] == attempt_b
    assert client.get(f"/runs/{run.run_id}/objects/meta", params={"handle": source.handle}).status_code == 200
    before = (run.run_dir / "events.jsonl").read_bytes()
    # Keep the small SQLite metadata but replace the physical source with a
    # larger file: the source-linked reader must bound the descriptor read.
    physical = run.run_dir / "objects" / f"{source.sha}.json"
    original_bytes = physical.read_bytes()
    physical.write_bytes(b" " * (api_module.CHEMICAL_SOURCE_READ_LIMIT + 1))
    oversized = client.get(f"/runs/{run.run_id}/chemical/preparation-manifests",
                           params={"source_handle": source.handle})
    assert oversized.status_code == 422
    assert client.get(f"/runs/{run.run_id}/chemical/structures/atoms",
                      params={"handle": source.handle, "limit": 1000}).status_code == 422
    assert (run.run_dir / "events.jsonl").read_bytes() == before
    physical.write_bytes(original_bytes)
    run.store.rebuild_from_events()
    assert require_completed_chemical_handle(run, source.handle)["successful_publisher_attempt_id"] == attempt_b
    assert (run.run_dir / "events.jsonl").read_bytes() == before

    # A detection result may likewise reuse bytes from an interrupted first
    # publication. Report provenance names both the immutable first creator
    # and the later successful publishing attempt.
    result = run.store.put("chemical_interaction_set", "chemical_interaction_set@1",
                           {"graph_handle": graph.handle}, produced_by="attempt_detect_first")
    for job_id, attempt_id, status in (("job_detect_first", "attempt_detect_first", "interrupted"),
                                       ("job_detect_retry", "attempt_detect_retry", "done")):
        run.events.append("job_submitted", job={"job_id": job_id, "protocol_id": "prolif_detect_v1",
                           "tool_id": "compute_chemical_interactions", "parameters": {
                               "graph_handle": graph.handle}, "input_handles": [graph.handle]})
        run.events.append("budget_reserved", attempt_id=attempt_id, root_call_id=job_id,
                          tool="compute_chemical_interactions")
        run.events.append("job_dispatch_intent", job_id=job_id, attempt_id=attempt_id)
        run.events.append("job_cleanup_verified", job_id=job_id, attempt_id=attempt_id, group_empty=True)
        run.events.append("job_result_candidate", job_id=job_id, attempt_id=attempt_id,
                          output_handles=[result.handle])
        run.events.append("job_terminal", job_id=job_id, attempt_id=attempt_id,
                          status=status, output_handles=[result.handle] if status == "done" else [])
        if status != "done":
            with pytest.raises(ToolFailure):
                require_completed_chemical_handle(run, result.handle)
    publication = require_completed_chemical_handle(run, result.handle)
    proof = chemical_provenance(list(run.events.read()), result.handle, publication)
    assert proof["first_creator_attempt_id"] == "attempt_detect_first"
    assert proof["attempt_id"] == "attempt_detect_retry"


def test_chemical_report_discloses_attached_source_coordinates():
    original = {"structure_handle": "obj://run_fixture/structure/original", "residue": {
        "model_number": 2, "chain_auth": "L", "chain_label": None, "seq_auth": 902,
        "seq_label": None, "icode": "A", "resname": "LIG"},
        "atom_name": "X1", "altloc": "", "element": "C", "site_index": 5010}
    provenance = {"source_manifest_handle": "obj://run_fixture/chemical_preparation_manifest/fixture",
                  "derived_coordinate_policy": "selected SDF conformer coordinates; never aligns",
                  "attached_source_sites": [{"sdf_atom_index": 0, "source_atom": original,
                                             "source_coordinate_A": [1.25, -2.5, 3.75],
                                             "discrepancy_A": 0.0015}],
                  "maximum_attachment_discrepancy_A": 0.0015}
    graph_states = {"histidine_states": [{"residue": original["residue"],
                                          "ring_h_sites": ["ND1"],
                                          "ring_formal_charge": 0, "ring_n_charges": {"ND1": 0, "NE2": 0},
                                          "represented_state": "graph-derived fixture",
                                          "annotation": "graph-derived supplied state; not a pH prediction"}],
                    "stereochemistry_audit": [], "terminal_extension_inventory": [], "field_citations": [],
                    "stereochemistry_policy": "3D coordinates supersede wedge/dash depiction"}
    markdown = chemical_report_markdown(
        {"rows": [], "total": 0, "limitations": [],
         "criteria": {"Hbond_distance_A": 3.5, "Hbond_DHA_angle_deg": [130, 180],
                      "Hydrophobic_distance_A": 4.5, "Cationic_distance_A": 4.5,
                      "Anionic_distance_A": 4.5, "vicinity_cutoff_A": 6.0,
                      "native_smarts_sha256": "a" * 64}}, [], provenance, graph_states)
    assert "model 2 L:902A LIG/X1 site 5010" in markdown
    assert "1.250000, -2.500000, 3.750000" in markdown
    assert "0.001500" in markdown and "never aligns" in markdown
    assert "supplied ring-H sites ND1" in markdown and "not a pH prediction" in markdown
    assert "3D coordinates supersede wedge/dash depiction" in markdown
    assert "SDF V2000 only; V3000 input is rejected" in markdown


def _import(client: TestClient, rid: str, kind: str, path: Path) -> str:
    response = client.post(f"/runs/{rid}/chemical/imports",
                           params={"kind": kind, "filename": path.name}, content=path.read_bytes(),
                           headers={"content-type": "application/octet-stream"})
    assert response.status_code == 201, response.text
    handle = response.json()["handle"]
    inspected = client.get(f"/runs/{rid}/chemical/imports/inspect", params={"handle": handle})
    assert inspected.status_code == 200, inspected.text
    return handle


def _prepare_request(client: TestClient, rid: str) -> dict:
    receptor = _import(client, rid, "receptor", FIX / "prolif-vina-rec.pdb")
    ligand = _import(client, rid, "ligand_sdf", FIX / "prolif-vina-output.sdf")
    request = {"schema": "chemical_prepare_request@1", "mode": "create_new",
               "receptor_input_handle": receptor, "receptor_model_number": 1,
               "connectivity": {"kind": "pdb_conect", "sidecar_handle": None},
               "ligand_sdf_handle": ligand, "sdf_record_index": 0,
               "ligand_instance": {"model_number": 1, "chain_auth": "L", "chain_label": None,
                                   "seq_auth": 1, "seq_label": None, "icode": "", "resname": "LIG"},
               "terminal_extensions": [],
               "acknowledgement": {"schema": "chemical_preparation_ack@1",
                                   "supplied_graph_complete": True, "supplied_hydrogens_complete": True,
                                   "use_supplied_protonation_tautomer": True,
                                   "infer_receptor_orders_charges": True,
                                   "description": "public ProLIF fixture, user-supplied prepared graph",
                                   "ph_annotation": None}}
    first = client.post(f"/runs/{rid}/chemical/preview", json=request)
    assert first.status_code == 200, first.text
    extensions = first.json()["terminal_extensions"]
    assert len(extensions) == 2
    request["terminal_extensions"] = [
        {"residue": item["residue"], "atom_names": item["atom_names"],
         "approve_supplied_graph": True} for item in extensions]
    ready = client.post(f"/runs/{rid}/chemical/preview", json=request)
    assert ready.status_code == 200 and ready.json()["ready"] is True, ready.text
    return request


def test_staging_atom_page_1000_shape_bounds_and_oversized_blob(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path)
    api_module.RUNS.clear()
    client = TestClient(api_module.app)
    rid = client.post("/runs", json={"goal": "bounded M11 staging catalog",
                                      "dry_run": False}).json()["run_id"]
    handle = _import(client, rid, "receptor", FIX / "prolif-vina-rec.pdb")
    run = api_module._run(rid)
    before = (run.run_dir / "events.jsonl").read_bytes()
    default_page = client.get(f"/runs/{rid}/chemical/imports/atoms", params={
        "handle": handle, "model_number": 1})
    assert default_page.status_code == 200 and default_page.json()["limit"] == 100
    rows = []
    for offset in range(0, 4988, 1000):
        response = client.get(f"/runs/{rid}/chemical/imports/atoms",
                              params={"handle": handle, "model_number": 1,
                                      "offset": offset, "limit": 1000})
        assert response.status_code == 200, response.text
        page = response.json()
        assert {key: page[key] for key in ("schema", "input_handle", "model_number", "total",
                                             "offset", "limit")} == {
            "schema": "chemical_staging_atom_page@1", "input_handle": handle,
            "model_number": 1, "total": 4988, "offset": offset, "limit": 1000}
        assert len(page["rows"]) == min(1000, 4988 - offset)
        for index, row in enumerate(page["rows"], offset):
            assert set(row) == {"ref", "coordinate_A", "element", "water"}
            assert set(row["ref"]) == {"structure_handle", "residue", "atom_name", "altloc",
                                       "element", "site_index"}
            assert row["ref"]["structure_handle"] == handle
            assert row["ref"]["site_index"] == index
            assert set(row["ref"]["residue"]) == {"chain_auth", "chain_label", "seq_auth",
                                                  "seq_label", "icode", "model_number", "resname"}
            assert len(row["coordinate_A"]) == 3
            assert row["element"] == row["ref"]["element"]
            assert type(row["water"]) is bool
        rows.extend(page["rows"])
    assert len(rows) == 4988 and [row["ref"]["site_index"] for row in rows] == list(range(4988))
    assert client.get(f"/runs/{rid}/chemical/imports/atoms", params={
        "handle": handle, "model_number": 1, "limit": 1001}).status_code == 422
    other = client.post("/runs", json={"goal": "foreign staging catalog",
                                      "dry_run": False}).json()["run_id"]
    assert client.get(f"/runs/{other}/chemical/imports/atoms", params={
        "handle": handle, "model_number": 1, "limit": 1000}).status_code == 422
    assert client.get(f"/runs/{rid}/chemical/imports/atoms", params={
        "handle": handle, "model_number": 2, "limit": 1000}).status_code == 422
    meta = run.store.meta(handle)
    physical = run.run_dir / "objects" / f"{handle.rsplit('/', 1)[-1]}.{meta['fmt']}"
    original = physical.read_bytes()
    physical.write_bytes(b" " * (10 * 1024 * 1024 + 1))
    try:
        assert client.get(f"/runs/{rid}/chemical/imports/atoms", params={
            "handle": handle, "model_number": 1, "limit": 1000}).status_code == 422
    finally:
        physical.write_bytes(original)
    assert (run.run_dir / "events.jsonl").read_bytes() == before


def _start(client: TestClient, rid: str, protocol: str, args: dict) -> dict:
    response = client.post(f"/runs/{rid}/jobs", json={"protocol_id": protocol, "args": args,
                                                    "timeout_s": 120})
    assert response.status_code == 200, response.text
    submitted = response.json()
    assert submitted["status"] == "queued" and submitted["protocol_id"] == protocol
    started = client.post(f"/runs/{rid}/jobs/{submitted['job_id']}/start")
    if started.status_code == 409:
        assert started.json()["approval"]["tool"] == (
            "prepare_chemical_structure" if protocol == "prolif_prepare_v1" else
            "compute_chemical_interactions")
        approval = client.post(f"/runs/{rid}/jobs/approve")
        assert approval.status_code == 200, approval.text
        started = client.post(f"/runs/{rid}/jobs/{submitted['job_id']}/start")
    assert started.status_code == 200, started.text
    result = started.json()
    assert result["status"] == "done" and result["attempt_ordinal"] == 1
    return result


def test_public_fixture_jobs_report_and_events_only_recovery(tmp_path, monkeypatch):
    root = tmp_path / "original"
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app)
    created = client.post("/runs", json={"goal": "public ProLIF fixture integration", "dry_run": False})
    assert created.status_code == 201
    rid = created.json()["run_id"]
    request = _prepare_request(client, rid)
    prepared = _start(client, rid, "prolif_prepare_v1", request)
    assert list(prepared["artifacts"]) == ["preparation_manifest", "chemical_structure", "chemical_graph"]
    source = prepared["artifacts"]["chemical_structure"]
    graph = prepared["artifacts"]["chemical_graph"]
    view = client.get(f"/runs/{rid}/chemical/structures/view", params={"handle": source})
    assert view.status_code == 200 and "_atom_site" in view.json()["text"]
    manifest_read = client.get(f"/runs/{rid}/chemical/preparation-manifests",
                               params={"source_handle": source})
    assert manifest_read.status_code == 200, manifest_read.text
    assert manifest_read.json()["meta"]["handle"] == prepared["artifacts"]["preparation_manifest"]
    saved_request = manifest_read.json()["manifest"]["request"]
    assert saved_request["ligand_instance"] == request["ligand_instance"]
    assert saved_request["sdf_record_index"] == request["sdf_record_index"]
    assert saved_request["acknowledgement"]["ph_annotation"] is None
    assert saved_request["terminal_extensions"] == request["terminal_extensions"]
    assert view.json()["manifest_sha256"] == hashlib.sha256(
        canonical_json(manifest_read.json()["manifest"])).hexdigest()
    wrong_kind = client.get(f"/runs/{rid}/chemical/preparation-manifests",
                            params={"source_handle": graph})
    assert wrong_kind.status_code == 422
    other = client.post("/runs", json={"goal": "foreign chemical read", "dry_run": False}).json()["run_id"]
    cross_run = client.get(f"/runs/{other}/chemical/preparation-manifests",
                           params={"source_handle": source})
    assert cross_run.status_code == 422
    monkeypatch.setattr(api_module, "CHEMICAL_MANIFEST_READ_LIMIT", 1)
    oversized_read = client.get(f"/runs/{rid}/chemical/preparation-manifests",
                                params={"source_handle": source})
    assert oversized_read.status_code == 422
    monkeypatch.setattr(api_module, "CHEMICAL_MANIFEST_READ_LIMIT", 8 * 1024 * 1024)
    catalog = client.get(f"/runs/{rid}/chemical/structures/atoms", params={"handle": source})
    assert catalog.status_code == 200 and catalog.json()["total"] == 4988 + 79
    assert catalog.json()["limit"] == 100
    assert catalog.json()["viewer_source_sha256"] == view.json()["viewer_source_sha256"]
    # M11's larger page still validates the completed same-run source on every read.
    rows = []
    for offset in range(0, catalog.json()["total"], 1000):
        page = client.get(f"/runs/{rid}/chemical/structures/atoms",
                          params={"handle": source, "offset": offset, "limit": 1000})
        assert page.status_code == 200, page.text
        value = page.json()
        assert {key: value[key] for key in ("schema", "structure_handle", "viewer_source_sha256",
                                              "model_number", "total", "offset", "limit")} == {
            "schema": "atom_catalog@1", "structure_handle": source,
            "viewer_source_sha256": view.json()["viewer_source_sha256"],
            "model_number": view.json()["model_number"], "total": 4988 + 79,
            "offset": offset, "limit": 1000}
        assert len(value["rows"]) == min(1000, value["total"] - offset)
        for index, row in enumerate(value["rows"], offset):
            assert set(row) == {"ref", "coordinate_A", "protein", "viewer_source_index"}
            assert row["viewer_source_index"] == row["ref"]["site_index"] == index
            assert row["ref"]["structure_handle"] == source
            assert set(row["ref"]) == {"structure_handle", "residue", "atom_name", "altloc",
                                       "element", "site_index"}
            assert set(row["ref"]["residue"]) == {"chain_auth", "chain_label", "seq_auth",
                                                  "seq_label", "icode", "model_number", "resname"}
            assert len(row["coordinate_A"]) == 3
            assert type(row["protein"]) is bool
        rows.extend(value["rows"])
    assert len(rows) == 5067 and [row["viewer_source_index"] for row in rows] == list(range(5067))
    assert client.get(f"/runs/{rid}/chemical/structures/atoms",
                      params={"handle": source, "limit": 1001}).status_code == 422
    assert client.get(f"/runs/{rid}/chemical/graphs", params={"handle": graph}).status_code == 200
    # M8/M10 deliberately retain their closed source-kind contracts.
    assert client.get(f"/runs/{rid}/structures/atoms", params={"handle": source}).status_code == 422
    assert client.get(f"/runs/{rid}/structures/bytes", params={"handle": source}).status_code == 422

    detect = {"schema": "chemical_detect_request@1", "graph_handle": graph,
              "categories": ["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"]}
    detected = _start(client, rid, "prolif_detect_v1", detect)
    handle = detected["artifacts"]["chemical_interaction_set"]
    result = client.get(f"/runs/{rid}/chemical/results", params={"handle": handle})
    assert result.status_code == 200, result.text
    assert result.json()["result"]["total"] == 36
    page = client.get(f"/runs/{rid}/chemical/results/rows", params={"handle": handle,
                        "category": "HBDonor", "offset": 0, "limit": 100})
    assert page.status_code == 200 and all(row["category"] == "HBDonor" for row in page.json()["rows"])
    report = client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle})
    assert report.status_code == 201, report.text
    report_handle = report.json()["handle"]
    downloads = {fmt: client.get(f"/runs/{rid}/reports/download",
                                 params={"handle": report_handle, "format": fmt}).content
                 for fmt in ("markdown", "json")}
    assert b"36 assignments" in downloads["markdown"]
    report_json = json.loads(downloads["json"])
    assert report_json["result_handle"] == handle
    coordinate_provenance = report_json["coordinate_provenance"]
    assert coordinate_provenance["source_manifest_handle"] == prepared["artifacts"]["preparation_manifest"]
    assert "selected SDF conformer coordinates" in coordinate_provenance["derived_coordinate_policy"]
    assert coordinate_provenance["attached_source_sites"] == []
    assert coordinate_provenance["maximum_attachment_discrepancy_A"] is None
    assert coordinate_provenance["field_citations"] == [
        {"source_handle": coordinate_provenance["source_manifest_handle"],
         "field_path": "derived_coordinate_policy",
         "exact_value": coordinate_provenance["derived_coordinate_policy"]}]
    assert b"Derived source coordinates" in downloads["markdown"]
    assert any("SDF V2000 only" in item for item in report_json["limitations"])
    graph_states = report_json["preparation_graph_states"]
    assert graph_states["source_manifest_handle"] == prepared["artifacts"]["preparation_manifest"]
    assert "tetrahedral atom parity" in graph_states["stereochemistry_policy"]
    assert graph_states["field_citations"] == [
        {"source_handle": graph_states["source_manifest_handle"],
         "field_path": "stereochemistry_policy",
         "exact_value": graph_states["stereochemistry_policy"]}] + [
        {"source_handle": graph_states["source_manifest_handle"],
         "field_path": f"histidine_states.{index}", "exact_value": row}
        for index, row in enumerate(graph_states["histidine_states"])] + [
        {"source_handle": graph_states["source_manifest_handle"],
         "field_path": f"stereochemistry_audit.{index}", "exact_value": row}
        for index, row in enumerate(graph_states["stereochemistry_audit"])] + [
        {"source_handle": graph_states["source_manifest_handle"],
         "field_path": f"terminal_extension_inventory.{index}", "exact_value": row}
        for index, row in enumerate(graph_states["terminal_extension_inventory"])]
    budget = client.get(f"/runs/{rid}/budget").json()
    assert budget["expensive_calls"]["used"] == 2
    before = (root / rid / "events.jsonl").read_bytes()

    replay = tmp_path / "events_only"
    (replay / rid).mkdir(parents=True)
    (replay / rid / "events.jsonl").write_bytes(before)
    def recomputation_forbidden(*_args, **_kwargs):
        raise AssertionError("events-only report/source reads must not execute scientific work")

    monkeypatch.setattr(JobQueue, "_supervise", recomputation_forbidden)
    monkeypatch.setattr(Run, "call", recomputation_forbidden)
    monkeypatch.setattr(chemical_bundle, "dependency", recomputation_forbidden)
    monkeypatch.setattr(chemical_bundle, "publish_prepare", recomputation_forbidden)
    monkeypatch.setattr(chemical_bundle, "publish_detect", recomputation_forbidden)
    monkeypatch.setattr(api_module, "RUNS_DIR", replay)
    api_module.RUNS.clear()
    selected = client.get(f"/runs/{rid}/reports/selected", params={"handle": report_handle})
    assert selected.status_code == 200, selected.text
    for fmt, expected in downloads.items():
        actual = client.get(f"/runs/{rid}/reports/download",
                            params={"handle": report_handle, "format": fmt})
        assert actual.status_code == 200 and actual.content == expected
    assert client.get(f"/runs/{rid}/chemical/results", params={"handle": handle}).json() == result.json()
    assert client.get(f"/runs/{rid}/chemical/structures/view", params={"handle": source}).json() == view.json()
    assert client.get(f"/runs/{rid}/chemical/preparation-manifests",
                      params={"source_handle": source}).json() == manifest_read.json()
    assert client.get(f"/runs/{rid}/budget").json() == budget
    assert (replay / rid / "events.jsonl").read_bytes() == before
    manifest_sha = manifest_read.json()["meta"]["handle"].rsplit("/", 1)[-1]
    (replay / rid / "objects" / f"{manifest_sha}.json").write_text("{}")
    tampered = client.get(f"/runs/{rid}/chemical/preparation-manifests",
                          params={"source_handle": source})
    assert tampered.status_code == 422


def test_native_candidates_cancel_before_terminal_remain_inaccessible_after_events_only_replay(
        tmp_path, monkeypatch):
    """Actual fixed workers; replay prefixes are labeled interruption simulations."""
    root = tmp_path / "original"
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app)
    prep_rid = client.post("/runs", json={"goal": "native preparation late cancellation",
                                           "dry_run": False}).json()["run_id"]
    prep_request = _prepare_request(client, prep_rid)
    prep_run = api_module._run(prep_rid)
    prep_run.approve("expensive_first_call")
    prep_prefix: bytes | None = None
    prep_handles: list[str] = []
    prep_job_id = ""

    def cancel_preparation(stage: str) -> None:
        nonlocal prep_prefix, prep_handles
        if stage != "before_terminal":
            return
        candidate = [event for event in prep_run.events.read()
                     if event["type"] == "job_result_candidate" and event["job_id"] == prep_job_id][-1]
        prep_handles = candidate["output_handles"]
        assert len(prep_handles) == 3
        prep_prefix = (prep_run.run_dir / "events.jsonl").read_bytes()
        manifest, source, graph = prep_handles
        for route, params in (
                ("/objects/meta", {"handle": manifest}),
                ("/objects/meta", {"handle": source}),
                ("/objects/meta", {"handle": graph}),
                ("/chemical/preparation-manifests", {"source_handle": source}),
                ("/chemical/structures/view", {"handle": source}),
                ("/chemical/structures/atoms", {"handle": source}),
                ("/chemical/graphs", {"handle": graph})):
            assert client.get(f"/runs/{prep_rid}{route}", params=params).status_code == 422
        denied_detect = client.post(f"/runs/{prep_rid}/jobs", json={"protocol_id": "prolif_detect_v1",
            "args": {"schema": "chemical_detect_request@1", "graph_handle": graph,
                     "categories": ["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"]},
            "timeout_s": 120})
        assert denied_detect.status_code == 422
        cancelled = client.post(f"/runs/{prep_rid}/jobs/{prep_job_id}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "accepted"

    prep_queue = JobQueue(prep_run, barrier=cancel_preparation)
    prep_job_id = prep_queue.submit("prolif_prepare_v1", prep_request, timeout_s=120)["job_id"]
    prep_terminal = prep_queue.start(prep_job_id)
    assert prep_terminal["status"] == "cancelled" and prep_terminal["output_handles"] == []
    assert prep_prefix is not None
    prep_events = list(prep_run.events.read())
    prep_attempt = prep_terminal["attempt_id"]
    assert sum(e["type"] == "budget_reserved" and e.get("attempt_id") == prep_attempt
               for e in prep_events) == 1
    assert any(e["type"] == "job_cleanup_verified" and e.get("attempt_id") == prep_attempt and
               e.get("group_empty") is True for e in prep_events)

    # A second actual completed preparation supplies a valid graph for a
    # separate fixed detection worker, whose own candidate is cancelled.
    detect_rid = client.post("/runs", json={"goal": "native detection late cancellation",
                                             "dry_run": False}).json()["run_id"]
    detect_request = _prepare_request(client, detect_rid)
    done_prep = _start(client, detect_rid, "prolif_prepare_v1", detect_request)
    graph = done_prep["artifacts"]["chemical_graph"]
    detect_run = api_module._run(detect_rid)
    detect_prefix: bytes | None = None
    detect_handle = ""
    detect_job_id = ""

    def cancel_detection(stage: str) -> None:
        nonlocal detect_prefix, detect_handle
        if stage != "before_terminal":
            return
        candidate = [event for event in detect_run.events.read()
                     if event["type"] == "job_result_candidate" and event["job_id"] == detect_job_id][-1]
        assert len(candidate["output_handles"]) == 1
        detect_handle = candidate["output_handles"][0]
        detect_prefix = (detect_run.run_dir / "events.jsonl").read_bytes()
        for route in ("/objects/meta", "/chemical/results", "/chemical/results/rows"):
            assert client.get(f"/runs/{detect_rid}{route}", params={"handle": detect_handle}).status_code == 422
        assert client.post(f"/runs/{detect_rid}/method_reports",
                           json={"result_handle": detect_handle}).status_code == 422
        cancelled = client.post(f"/runs/{detect_rid}/jobs/{detect_job_id}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "accepted"

    detect_queue = JobQueue(detect_run, barrier=cancel_detection)
    detect_job_id = detect_queue.submit("prolif_detect_v1", {
        "schema": "chemical_detect_request@1", "graph_handle": graph,
        "categories": ["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"]},
        timeout_s=120)["job_id"]
    detect_terminal = detect_queue.start(detect_job_id)
    assert detect_terminal["status"] == "cancelled" and detect_terminal["output_handles"] == []
    assert detect_prefix is not None
    detect_events = list(detect_run.events.read())
    detect_attempt = detect_terminal["attempt_id"]
    assert sum(e["type"] == "budget_reserved" and e.get("attempt_id") == detect_attempt
               for e in detect_events) == 1
    assert any(e["type"] == "job_cleanup_verified" and e.get("attempt_id") == detect_attempt and
               e.get("group_empty") is True for e in detect_events)

    # Simulate a process stopping after the actual candidate event and before
    # its terminal event. Only those event prefixes enter the replay root.
    replay_root = tmp_path / "candidate_prefix_simulated_interruptions"
    for rid, prefix in ((prep_rid, prep_prefix), (detect_rid, detect_prefix)):
        target = replay_root / rid
        target.mkdir(parents=True)
        (target / "events.jsonl").write_bytes(prefix)
    monkeypatch.setattr(api_module, "RUNS_DIR", replay_root)
    api_module.RUNS.clear()
    for rid, handle, route in ((prep_rid, prep_handles[1], "/chemical/structures/view"),
                               (prep_rid, prep_handles[2], "/chemical/graphs"),
                               (detect_rid, detect_handle, "/chemical/results"),
                               (detect_rid, detect_handle, "/objects/meta")):
        assert client.get(f"/runs/{rid}{route}", params={"handle": handle}).status_code == 422
    assert client.post(f"/runs/{detect_rid}/method_reports",
                       json={"result_handle": detect_handle}).status_code == 422
    for rid, prefix in ((prep_rid, prep_prefix), (detect_rid, detect_prefix)):
        observed = (replay_root / rid / "events.jsonl").read_bytes()
        assert observed.startswith(prefix)
        recovered = [json.loads(line) for line in observed[len(prefix):].splitlines()]
        assert any(event["type"] == "job_terminal" and event["status"] == "interrupted" and
                   event["output_handles"] == [] for event in recovered)
        assert not any(event["type"] in {"object_created", "job_result_candidate", "job_dispatch_intent",
                                               "budget_reserved", "job_worker_started"} for event in recovered)


def test_native_worker_failure_charges_each_retry_without_publishing(tmp_path, monkeypatch):
    root = tmp_path / "failed"
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app)
    rid = client.post("/runs", json={"goal": "labeled invalid worker input fixture",
                                      "dry_run": False}).json()["run_id"]
    request = _prepare_request(client, rid)
    real_prepare = chemical_bundle.prepare_selected

    def invalid_worker_fixture(store, args):
        selected = real_prepare(store, args)
        # Preserve valid app preflight; corrupt only the test's immutable
        # worker-stage digest so the genuine child exits after dispatch.
        return {**selected, "ligand_sdf_sha256": "0" * 64}

    monkeypatch.setattr(chemical_bundle, "prepare_selected", invalid_worker_fixture)
    submitted = client.post(f"/runs/{rid}/jobs", json={"protocol_id": "prolif_prepare_v1",
                                                      "args": request, "timeout_s": 120})
    assert submitted.status_code == 200, submitted.text
    job_id = submitted.json()["job_id"]
    first = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    assert first.status_code == 409 and first.json()["approval"]["tool"] == "prepare_chemical_structure"
    assert client.post(f"/runs/{rid}/jobs/approve").status_code == 200
    first = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    assert first.status_code == 200 and first.json()["status"] == "failed", first.text
    assert first.json()["output_handles"] == []
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 1
    retry = client.post(f"/runs/{rid}/jobs/{job_id}/retry")
    assert retry.status_code == 200 and retry.json()["status"] == "queued"
    second = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    assert second.status_code == 200 and second.json()["status"] == "failed", second.text
    assert second.json()["attempt_ordinal"] == 2 and second.json()["output_handles"] == []
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 2
    events = [json.loads(line) for line in (root / rid / "events.jsonl").read_text().splitlines()]
    assert sum(e["type"] == "job_worker_started" for e in events) == 2
    assert sum(e["type"] == "budget_reserved" and e.get("tool") == "prepare_chemical_structure"
               for e in events) == 2
    assert not any(e["type"] == "object_created" and e.get("kind") in
                   {"chemical_preparation_manifest", "chemical_structure", "chemical_graph"} for e in events)


def test_native_receptor_graph_failure_is_typed_with_exact_uploaded_atom_refs(tmp_path, monkeypatch):
    root = tmp_path / "receptor_graph_failure"
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app)
    rid = client.post("/runs", json={"goal": "labeled zero-length receptor bond fixture",
                                     "dry_run": False}).json()["run_id"]
    request = _prepare_request(client, rid)
    run = api_module._run(rid)
    original_selected = chemical_bundle.prepare_selected(run.store, request)
    atoms = original_selected["receptor_atoms"]
    h_index = next(i for i, row in enumerate(atoms) if row["element"].upper() == "H")
    bond = next(pair for pair in original_selected["receptor_bonds"] if h_index in pair)
    heavy_index = next(i for i in bond if i != h_index)
    site_index = atoms[h_index]["source_ref"]["site_index"]
    original = (FIX / "prolif-vina-rec.pdb").read_text().splitlines(keepends=True)
    sites = [i for i, line in enumerate(original) if line.startswith(("ATOM  ", "HETATM"))]
    target_line = sites[site_index]
    assert original[target_line][12:16].strip() == atoms[h_index]["source_ref"]["atom_name"]
    coordinate = atoms[heavy_index]["coordinate_A"]
    original[target_line] = (original[target_line][:30] +
                             "".join(f"{value:8.3f}" for value in coordinate) +
                             original[target_line][54:])
    mutated = "".join(original).encode()
    imported = client.post(f"/runs/{rid}/chemical/imports",
                           params={"kind": "receptor", "filename": "zero-length-bond-fixture.pdb"},
                           content=mutated, headers={"content-type": "application/octet-stream"})
    assert imported.status_code == 201, imported.text
    request["receptor_input_handle"] = imported.json()["handle"]
    preview = client.post(f"/runs/{rid}/chemical/preview", json=request)
    assert preview.status_code == 200 and preview.json()["ready"] is True, preview.text
    selected = chemical_bundle.prepare_selected(run.store, request)
    expected_refs = {canonical_json(selected["receptor_atoms"][i]["source_ref"])
                     for i in (h_index, heavy_index)}
    submitted = client.post(f"/runs/{rid}/jobs", json={"protocol_id": "prolif_prepare_v1",
                                                     "args": request, "timeout_s": 120})
    assert submitted.status_code == 200, submitted.text
    job_id = submitted.json()["job_id"]
    assert client.post(f"/runs/{rid}/jobs/{job_id}/start").status_code == 409
    assert client.post(f"/runs/{rid}/jobs/approve").status_code == 200
    started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    assert started.status_code == 200 and started.json()["status"] == "failed", started.text
    failure = started.json()["failure"]
    assert failure["error"] == "input_invalid" and failure["reason_code"] == "receptor_graph_invalid"
    assert {canonical_json(ref) for ref in failure["source_atoms"]} == expected_refs
    assert failure["source_residues"] and failure["sdf_atom_indices"] == []
    assert started.json()["output_handles"] == []
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 1
    events = list(run.events.read())
    assert sum(event["type"] == "job_worker_started" and event["job_id"] == job_id
               for event in events) == 1
    assert not any(event["type"] == "object_created" and event.get("kind") in
                   {"chemical_preparation_manifest", "chemical_structure", "chemical_graph"}
                   for event in events)


def test_chemical_import_body_bound_and_queued_cancel(tmp_path, monkeypatch):
    root = tmp_path / "cancel"
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app)
    rid = client.post("/runs", json={"goal": "chemical request bounds", "dry_run": False}).json()["run_id"]
    too_big = client.post(f"/runs/{rid}/chemical/imports",
                          params={"kind": "ligand_sdf", "filename": "fixture.sdf"},
                          content=b"X" * (10 * 1024 * 1024 + 1),
                          headers={"content-type": "application/octet-stream"})
    assert too_big.status_code == 413
    assert not any(e["type"] == "object_created" for e in api_module.RUNS[rid].events.read())
    bad_json = client.post(f"/runs/{rid}/chemical/preview",
                           content=b'{"schema":"x","schema":"y"}',
                           headers={"content-type": "application/json"})
    assert bad_json.status_code == 422
    oversized_job = client.post(f"/runs/{rid}/jobs", content=b" " * (512 * 1024 + 1),
                                headers={"content-type": "application/json"})
    assert oversized_job.status_code == 413
    assert not any(e["type"] == "job_submitted" for e in api_module.RUNS[rid].events.read())
    request = _prepare_request(client, rid)
    submitted = client.post(f"/runs/{rid}/jobs", json={"protocol_id": "prolif_prepare_v1",
                                                      "args": request, "timeout_s": 120})
    assert submitted.status_code == 200
    job_id = submitted.json()["job_id"]
    cancelled = client.post(f"/runs/{rid}/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["job"]["status"] == "cancelled"
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 0
    assert client.post(f"/runs/{rid}/jobs/approve").status_code == 412


def _submitted_approved(client: TestClient, rid: str, request: dict,
                        timeout_s: float = 120) -> str:
    response = client.post(f"/runs/{rid}/jobs", json={"protocol_id": "prolif_prepare_v1",
                                                    "args": request, "timeout_s": timeout_s})
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    blocked = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    assert blocked.status_code == 409 and blocked.json()["approval"]["gate"] == "expensive_first_call"
    assert client.post(f"/runs/{rid}/jobs/approve").status_code == 200
    return job_id


def _assert_worker_reaped(root: Path, rid: str, job_id: str) -> list[dict]:
    events = [json.loads(line) for line in (root / rid / "events.jsonl").read_text().splitlines()]
    starts = [e for e in events if e["type"] == "job_worker_started" and e["job_id"] == job_id]
    assert starts, "the fixed native worker must really launch"
    for event in starts:
        try:
            process = psutil.Process(event["pid"])
            assert not matches(event["pid"], event["start_identity"]) or process.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            pass
        assert any(e["type"] == "job_cleanup_verified" and e.get("attempt_id") == event["attempt_id"]
                   for e in events)
    return events


def test_running_native_worker_cancel_and_timeout(tmp_path, monkeypatch):
    # These are separate real fixed-adapter launches, not a queued-only cancel.
    for mode in ("cancel", "timeout"):
        root = tmp_path / mode
        monkeypatch.setattr(api_module, "RUNS_DIR", root)
        api_module.RUNS.clear()
        client = TestClient(api_module.app)
        rid = client.post("/runs", json={"goal": f"labeled {mode} native lifecycle fixture",
                                          "dry_run": False}).json()["run_id"]
        request = _prepare_request(client, rid)
        job_id = _submitted_approved(client, rid, request, timeout_s=4 if mode == "timeout" else 120)
        if mode == "cancel":
            original = JobQueue._record_control
            fired = False

            def cancel_after_real_start(self, message, reported_job, attempt_id, nonce,
                                        original_record=original):
                nonlocal fired
                done = original_record(self, message, reported_job, attempt_id, nonce)
                if message and message.get("kind") == "STARTED" and not fired:
                    fired = True
                    self.request_cancel(reported_job)
                return done

            with monkeypatch.context() as patch:
                patch.setattr(JobQueue, "_record_control", cancel_after_real_start)
                response = client.post(f"/runs/{rid}/jobs/{job_id}/start")
            assert fired
            assert response.status_code == 200 and response.json()["status"] == "cancelled", response.text
        else:
            response = client.post(f"/runs/{rid}/jobs/{job_id}/start")
            assert response.status_code == 200 and response.json()["status"] == "failed", response.text
            assert response.json()["failure"]["error"] == "resource_exceeded"
        assert response.json()["output_handles"] == []
        assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 1
        events = _assert_worker_reaped(root, rid, job_id)
        assert not any(e["type"] == "object_created" and e.get("kind") in
                       {"chemical_preparation_manifest", "chemical_structure", "chemical_graph"} for e in events)


def test_fixed_adapter_rejects_malformed_and_oversized_output(tmp_path, monkeypatch):
    # Fault injection occurs only after the real pinned worker has exited and
    # its guardian has returned verified cleanup; no alternate executor runs.
    for mode in ("malformed", "oversized"):
        root = tmp_path / mode
        monkeypatch.setattr(api_module, "RUNS_DIR", root)
        api_module.RUNS.clear()
        client = TestClient(api_module.app)
        rid = client.post("/runs", json={"goal": f"labeled {mode} output fault fixture",
                                          "dry_run": False}).json()["run_id"]
        request = _prepare_request(client, rid)
        job_id = _submitted_approved(client, rid, request)
        original = JobQueue._supervise

        def corrupt_after_genuine_worker(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch,
                                         original_supervise=original, fault_mode=mode):
            result, identity = original_supervise(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch)
            assert result and result.get("clean") and result.get("returncode") == 0
            raw = b'{"schema":' if fault_mode == "malformed" else b"X" * (30 * 1024 * 1024 + 1)
            (attempt_dir / "result.json").write_bytes(raw)
            result["payload"] = {"output_sha256": hashlib.sha256(raw).hexdigest(),
                                 "output_bytes": len(raw)}
            return result, identity

        with monkeypatch.context() as patch:
            patch.setattr(JobQueue, "_supervise", corrupt_after_genuine_worker)
            response = client.post(f"/runs/{rid}/jobs/{job_id}/start")
        assert response.status_code == 200 and response.json()["status"] == "failed", response.text
        assert response.json()["failure"]["message"] == "invalid scientific output"
        assert response.json()["output_handles"] == []
        assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 1
        events = _assert_worker_reaped(root, rid, job_id)
        assert not any(e["type"] == "object_created" and e.get("kind") in
                       {"chemical_preparation_manifest", "chemical_structure", "chemical_graph"} for e in events)


def test_cross_run_busy_is_nonapproval_uncharged_and_resumable(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path)
    api_module.RUNS.clear()
    client = TestClient(api_module.app)
    first = client.post("/runs", json={"goal": "global slot holder fixture", "dry_run": False}).json()["run_id"]
    second = client.post("/runs", json={"goal": "public chemical contender", "dry_run": False}).json()["run_id"]
    request = _prepare_request(client, second)
    job_id = _submitted_approved(client, second, request)
    third = client.post("/runs", json={"goal": "cancel responsiveness fixture", "dry_run": False}).json()["run_id"]
    fixture_job = JobQueue(api_module.RUNS[third], fixture_mode="normal").submit_fixture()["job_id"]
    with _global_worker_slot(tmp_path / first):
        blocked = client.post(f"/runs/{second}/jobs/{job_id}/start")
        assert blocked.status_code == 409 and "approval" not in blocked.json()
        assert blocked.json()["detail"]["reason_code"] == "global_concurrency_busy"
        assert client.get(f"/runs/{second}/budget").json()["expensive_calls"]["used"] == 0
        assert client.get(f"/runs/{second}/jobs/{job_id}").json()["blocked_reason"] == "global_concurrency_busy"
        cancelled = client.post(f"/runs/{third}/jobs/{fixture_job}/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["job"]["status"] == "cancelled"
    resumed = client.post(f"/runs/{second}/jobs/{job_id}/start")
    assert resumed.status_code == 200 and resumed.json()["status"] == "done", resumed.text
    assert resumed.json()["attempt_ordinal"] == 1
    assert client.get(f"/runs/{second}/budget").json()["expensive_calls"]["used"] == 1


def test_locked_other_run_ledger_has_bounded_wait_and_resumable_claim(tmp_path):
    holder = new_run(tmp_path, run_id="run_ledger_holder", dry_run=False)
    run = new_run(tmp_path, run_id="run_ledger_contender", dry_run=False)
    run.approve("expensive_first_call")
    queue = JobQueue(run, fixture_mode="normal")
    job_id = queue.submit_fixture()["job_id"]
    lock = holder.run_dir / "events.lock"
    process = subprocess.Popen(
        [sys.executable, "-u", "-c",
         ("import fcntl,sys,time; f=open(sys.argv[1],'rb'); fcntl.flock(f,fcntl.LOCK_EX); "
          "print('locked',flush=True); time.sleep(10)"), str(lock)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "locked"
        started = time.monotonic()
        with pytest.raises(ToolFailure) as blocked:
            queue.start(job_id)
        assert time.monotonic() - started < 2
        assert blocked.value.detail["reason_code"] == "global_job_ledger_unavailable"
        assert queue.get(job_id)["blocked_reason"] == "global_job_ledger_unavailable"
        assert not any(event["type"] == "budget_reserved" for event in run.events.read())
    finally:
        process.terminate()
        process.communicate(timeout=3)
    assert queue.start(job_id)["status"] == "done"


def test_cancel_during_locked_other_ledger_releases_global_slot(tmp_path):
    holder = new_run(tmp_path, run_id="run_cancel_holder", dry_run=False)
    run = new_run(tmp_path, run_id="run_cancel_contender", dry_run=False)
    run.approve("expensive_first_call")
    queue = JobQueue(run, fixture_mode="normal")
    job_id = queue.submit_fixture()["job_id"]
    process = subprocess.Popen(
        [sys.executable, "-u", "-c",
         ("import fcntl,sys,time; f=open(sys.argv[1],'rb'); fcntl.flock(f,fcntl.LOCK_EX); "
          "print('locked',flush=True); time.sleep(10)"), str(holder.run_dir / "events.lock")],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    failures: list[Exception] = []
    try:
        assert process.stdout.readline().strip() == "locked"

        def start() -> None:
            try:
                queue.start(job_id)
            except Exception as exc:  # noqa: BLE001 - thread result checked below
                failures.append(exc)

        worker = threading.Thread(target=start)
        worker.start()
        time.sleep(0.08)
        assert queue.request_cancel(job_id)["job"]["status"] == "cancelled"
        worker.join(1)
        assert not worker.is_alive()
        assert failures and failures[0].__class__.__name__ == "RunCancelled"
        assert not any(event["type"] == "budget_reserved" for event in run.events.read())
    finally:
        process.terminate()
        process.communicate(timeout=3)


def test_typed_worker_error_requires_exact_staged_identity_and_small_canonical_envelope(tmp_path):
    run = new_run(tmp_path, run_id="run_worker_error", dry_run=False)
    queue = JobQueue(run)
    residue = {"model_number": 2, "chain_auth": "A", "chain_label": None,
               "seq_auth": 42, "seq_label": None, "icode": "A", "resname": "HIS"}
    atom = {"structure_handle": "obj://run_worker_error/structure/" + "0" * 64,
            "residue": residue, "atom_name": "ND1", "altloc": "", "element": "N", "site_index": 7}
    job = {"protocol_id": "prolif_prepare_v1", "selected": {
        "receptor_atoms": [{"source_ref": atom}], "ligand_atom_names": ["C1", "C2"]}}
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    envelope = {"schema": "chemical_worker_error@1", "error_class": "input_invalid",
                "reason_code": "histidine_ring_graph", "message": "supplied ring graph conflicts",
                "source_residues": [residue], "source_atoms": [atom], "sdf_atom_indices": []}
    (attempt / "error.json").write_bytes(canonical_json(envelope))
    assert queue._chemical_worker_error(job, attempt)["source_atoms"] == [atom]
    envelope["source_atoms"] = [{**atom, "site_index": 8}]
    (attempt / "error.json").write_bytes(canonical_json(envelope))
    assert queue._chemical_worker_error(job, attempt)["error"] == "fatal"
    envelope["source_atoms"] = [atom]
    envelope["sdf_atom_indices"] = [2]
    (attempt / "error.json").write_bytes(canonical_json(envelope))
    assert queue._chemical_worker_error(job, attempt)["error"] == "fatal"
    (attempt / "error.json").write_bytes(b" " * 4097)
    assert queue._chemical_worker_error(job, attempt)["error"] == "fatal"


def test_inherited_global_lock_and_orphan_ledger_fail_closed(tmp_path):
    (tmp_path / "run_holder").mkdir()
    (tmp_path / "run_contender").mkdir()
    marker = tmp_path / "child-ready"
    with _global_worker_slot(tmp_path / "run_holder") as descriptor:
        # Labeled process-lifetime fixture: the descendant inherits the locked
        # FD exactly as guardian/worker do, while the parent context exits.
        child = subprocess.Popen([sys.executable, "-c",
                                  "from pathlib import Path; import time; Path(__import__('sys').argv[1]).write_text('ready'); time.sleep(1)",
                                  str(marker)], pass_fds=(descriptor,), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        until = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < until:
            time.sleep(.01)
        assert marker.exists() and child.poll() is None
        with pytest.raises(ToolFailure) as busy, _global_worker_slot(tmp_path / "run_contender"):
            pass
        assert busy.value.detail["reason_code"] == "global_concurrency_busy"
    finally:
        child.wait(timeout=3)
    with _global_worker_slot(tmp_path / "run_contender"):
        pass


def test_global_ledger_rejects_symlink_and_aggregate_overflow(tmp_path, monkeypatch):
    contender = tmp_path / "run_contender"
    contender.mkdir()
    first = tmp_path / "run_first"
    first.mkdir()
    row = json.dumps({"seq": 1, "type": "run_started"}) + "\n"
    (first / "events.lock").touch()
    (first / "events.jsonl").write_text(row)
    symlink = tmp_path / "run_link"
    symlink.symlink_to(first, target_is_directory=True)
    with pytest.raises(ToolFailure) as unsafe, _global_worker_slot(contender):
        pass
    assert unsafe.value.detail["reason_code"] == "global_job_ledger_unavailable"
    symlink.unlink()

    second = tmp_path / "run_second"
    second.mkdir()
    (second / "events.lock").touch()
    (second / "events.jsonl").write_text(row)
    monkeypatch.setattr(queue_module, "MAX_GLOBAL_EVENT_SCAN", len(row.encode()) + 1)
    with pytest.raises(ToolFailure) as overflow, _global_worker_slot(contender):
        pass
    assert overflow.value.detail["reason_code"] == "global_job_ledger_unavailable"


def test_global_gate_remains_closed_after_real_owner_death_until_recovery(tmp_path):
    # Internal sleep fixture exercises the genuine guardian/worker FD chain;
    # it is lifecycle evidence, never chemical/scientific output.
    script = r'''
import sys,time
from pathlib import Path
from mw.jobs.queue import JobQueue
from mw.workspace import new_run
root=Path(sys.argv[1]);run=new_run(root,run_id='run_holder',dry_run=False)
run.approve('expensive_first_call')
def barrier(stage):
    if stage=='after_go':
        (root/'after_go').write_text('ready')
        while True: time.sleep(.02)
q=JobQueue(run,fixture_mode='sleep',barrier=barrier)
job=q.submit_fixture(timeout_s=10)
(root/'holder_job').write_text(job['job_id'])
q.claim_next('owner');q.execute_claim(job['job_id'],'owner')
'''
    child = subprocess.Popen([sys.executable, "-c", script, str(tmp_path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    contender = tmp_path / "run_contender"
    contender.mkdir()
    try:
        until = time.monotonic() + 6
        while not (tmp_path / "after_go").exists() and time.monotonic() < until:
            time.sleep(.02)
        assert (tmp_path / "after_go").exists()
        with pytest.raises(ToolFailure) as live, _global_worker_slot(contender):
            pass
        assert live.value.detail["reason_code"] == "global_concurrency_busy"
        child.kill()
        child.wait(timeout=2)
        with pytest.raises(ToolFailure) as orphaned, _global_worker_slot(contender):
            pass
        assert orphaned.value.detail["reason_code"] in {
            "global_concurrency_busy", "global_job_cleanup_pending"}
        run = new_run(tmp_path, run_id="run_holder", dry_run=False)
        queue = JobQueue(run)
        until = time.monotonic() + 6
        while time.monotonic() < until:
            try:
                if queue.reconcile_run()[0]["status"] == "interrupted":
                    break
            except ToolFailure:
                pass
            time.sleep(.05)
        assert queue.get((tmp_path / "holder_job").read_text())["status"] == "interrupted"
        with _global_worker_slot(contender):
            pass
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)

    # Synthetic orphan event ledger models a lost parent after dispatch. The
    # recovered terminal record is appended only after cleanup verification.
    orphan = tmp_path / "run_orphan"
    orphan.mkdir()
    path = orphan / "events.jsonl"
    (orphan / "events.lock").touch()
    records = [{"seq": 1, "type": "job_submitted", "job": {"job_id": "job_orphan"}},
               {"seq": 2, "type": "job_dispatch_intent", "job_id": "job_orphan"},
               {"seq": 3, "type": "job_cleanup_pending", "job_id": "job_orphan"}]
    path.write_text("".join(json.dumps(row) + "\n" for row in records))
    with pytest.raises(ToolFailure) as orphaned, _global_worker_slot(tmp_path / "run_contender"):
        pass
    assert orphaned.value.detail["reason_code"] == "global_job_cleanup_pending"
    assert orphaned.value.detail["jobs"] == ["run_orphan/job_orphan"]
    records.extend([{"seq": 4, "type": "job_cleanup_verified", "job_id": "job_orphan"},
                    {"seq": 5, "type": "job_terminal", "job_id": "job_orphan", "status": "interrupted"}])
    path.write_text("".join(json.dumps(row) + "\n" for row in records))
    with _global_worker_slot(tmp_path / "run_contender"):
        pass
