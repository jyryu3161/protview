"""M12 fpocket durable job lane, objects, capability, read API and events-only replay.

These tests run the real installed fpocket 4.2.3 build through the product path (upload → load →
prepare → preflight → submit → approve → start). They FAIL, never skip, when the engine is absent.
No expected pocket counts or descriptor values are hard-coded: every stored value is checked against
an independent re-read of the stored native evidence bytes and of the stored transport coordinates.

Inputs: ``public_1hsg.cif`` (public PDB entry) and the labeled derived fixture
``derived_1hsg_first10_fixture.cif``. Inputs generated below are DERIVED from public_1hsg.cif
(translated or replicated copies, named ``derived_*`` and not experimental structures). Fault
injections are labeled and applied only through internal test hooks, never through request fields.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import gemmi
import numpy as np
import psutil
import pytest
from fastapi.testclient import TestClient

from mw import pocket_bundle, pocket_output
from mw.api import app as api_module
from mw.jobs import guardian as guardian_module
from mw.jobs import pocket_worker
from mw.jobs.queue import JobQueue
from mw.runtime.orchestrator import Run
from mw.tools.comparison import atom_rows
from mw.workspace import new_run

FIXTURES = Path(__file__).parent / "fixtures"
HSG = FIXTURES / "public_1hsg.cif"
DERIVED_FIRST10 = FIXTURES / "derived_1hsg_first10_fixture.cif"
PREPARE = {"altloc": "highest_occupancy", "waters": "keep_all", "hydrogens": "strip",
           "missing_residues": "leave_gaps", "symmetry_mates": "ignore"}
SENTINELS = ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
             "http_proxy", "https_proxy", "PYTHONPATH", "DYLD_INSERT_LIBRARIES", "LD_PRELOAD")
TRANSLATION = (7.125, -3.5, 11.25)  # exactly representable; keeps 3-decimal source coordinates exact


# ----------------------------------------------------------------- engine requirement (fail, never skip)
def test_installed_engine_is_ready_and_capabilities_replace_old_entry():
    capability = pocket_bundle.capability()
    assert capability["status"] == "ready", (
        f"fpocket 4.2.3 must be installed for M12 acceptance: {capability['status']} {capability['reason']}")
    assert capability["available"] is True and capability["reason"] is None
    assert capability["executable_sha256"] == pocket_worker.EXECUTABLE_SHA256
    assert capability["package_sha256"] == pocket_worker.PACKAGE_SHA256
    assert capability["build"] == "hb88c64c_2" and capability["release"] == "4.2.3"
    assert capability["observed_banner"] == "fpocket 4.0"
    assert capability["recipe_provenance"]["package"]["build"] == "hb88c64c_2"
    assert capability["argv"] == ["fpocket", "-f", "protein.pdb", "-m", "3.4", "-M", "6.2", "-D", "2.4", "-C",
                                  "s", "-e", "e", "-i", "15", "-p", "0.0", "--number_apol_asph_pocket", "3", "-v",
                                  "300", "-w", "p"]
    assert capability["determinism"]["seed_control"] == "unsupported"
    assert capability["determinism"]["fresh_execution_deterministic"] is False
    public = TestClient(api_module.app, base_url="http://127.0.0.1").get("/capabilities").json()
    assert public["methods"]["pocket_detection"]["status"] == "ready"
    assert "pocket_detection" not in public["unavailable"]
    assert "detect_pockets" not in api_module.SUPPORTED_TOOLS
    assert "detect_pockets" in api_module.REGISTRY.impls and "detect_pockets" in api_module.REGISTRY.unavailable
    spec = api_module.REGISTRY.specs["detect_pockets"]
    assert spec.accepts == {"structure": ["prepared_structure", "chemical_structure", "openmm_minimized_structure"]}
    assert set(spec.params) == {"chains"} and spec.cost_class == "expensive"


# ----------------------------------------------------------------- helpers
def _client(root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _new_run(client: TestClient, goal: str) -> str:
    created = client.post("/runs", json={"goal": goal, "dry_run": False})
    assert created.status_code == 201, created.text
    return created.json()["run_id"]


def _prepared(client: TestClient, rid: str, raw: bytes, filename: str) -> tuple[str, str]:
    uploaded = client.post(f"/runs/{rid}/uploads", params={"filename": filename}, content=raw)
    assert uploaded.status_code == 201, uploaded.text
    source = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure", "args": {
        "source": uploaded.json()["upload_id"], "model_index": 0}})
    assert source.status_code == 200, source.text
    source_handle = source.json()["handle"]["handle"]
    prepared = client.post(f"/runs/{rid}/commands", json={"tool": "prepare_structure", "args": {
        "structure": source_handle, **PREPARE}})
    assert prepared.status_code == 200, prepared.text
    return source_handle, prepared.json()["handle"]["handle"]


def _submit(client: TestClient, rid: str, structure: str, chains=None, timeout_s: float = 120) -> dict:
    args = {"structure": structure} if chains is None else {"structure": structure, "chains": chains}
    response = client.post(f"/runs/{rid}/jobs", json={"protocol_id": "fpocket_detect_v1", "args": args,
                                                    "timeout_s": timeout_s})
    assert response.status_code == 200, response.text
    return response.json()


def _approve_start(client: TestClient, rid: str, job_id: str):
    started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    if started.status_code == 409:
        assert started.json()["approval"]["tool"] == "detect_pockets"
        assert started.json()["approval"]["gate"] == "expensive_first_call"
        approved = client.post(f"/runs/{rid}/jobs/approve")
        assert approved.status_code == 200, approved.text
        started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    return started


def _detect(client: TestClient, rid: str, structure: str, chains=None) -> dict:
    job = _submit(client, rid, structure, chains)
    assert job["status"] == "queued" and job["protocol_id"] == "fpocket_detect_v1"
    started = _approve_start(client, rid, job["job_id"])
    assert started.status_code == 200, started.text
    done = started.json()
    assert done["status"] == "done", done
    assert list(done["artifacts"]) == ["pocket_set"] and done["output_handles"] == [done["artifacts"]["pocket_set"]]
    return done


def _events(root: Path, rid: str) -> list[dict]:
    return [json.loads(line) for line in (root / rid / "events.jsonl").read_text().splitlines()]


def _derived_translated(shift=TRANSLATION) -> bytes:
    """DERIVED fixture: every public_1hsg.cif coordinate translated by ``shift`` (not an experiment)."""
    doc = gemmi.cif.read(str(HSG))
    block = doc.sole_block()
    table = block.find("_atom_site.", ["Cartn_x", "Cartn_y", "Cartn_z"])
    for row in table:
        for index, delta in enumerate(shift):
            row[index] = f"{float(row[index]) + delta:.3f}"
    block.name = "1HSG_DERIVED_TRANSLATED"
    return doc.as_string().encode()


def _derived_replicated(copies: int = 5, spacing: float = 70.0) -> bytes:
    """DERIVED fixture: public_1hsg protein chains plus translated copies (a larger engine workload)."""
    st = gemmi.read_structure(str(HSG))
    st.remove_ligands_and_waters()
    st.remove_hydrogens()
    model = st[0]
    base = [chain.clone() for chain in model]
    names = iter("CDEFGHIJKLMNOPQRSTUVWXYZ")
    for copy_index in range(1, copies + 1):
        for chain in base:
            clone = chain.clone()
            clone.name = next(names)
            for residue in clone:
                for atom in residue:
                    atom.pos = gemmi.Position(atom.pos.x + spacing * copy_index, atom.pos.y, atom.pos.z)
            model.add_chain(clone)
    st.setup_entities()
    return st.make_mmcif_document().as_string().encode()


# ----------------------------------------------------------------- independent evidence readers
def _native_files(run: Run, handle: str) -> tuple[dict, dict[str, bytes]]:
    native = run.store.load(handle)
    files = {item["path"]: base64.b64decode(item["content_b64"]) for item in native["files"] if item["retained"]}
    return native, files


def _info_blocks(text: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for line in text.splitlines():
        header = re.fullmatch(r"Pocket (\d+) :", line)
        if header:
            blocks.append({"rank": header.group(1)})
        elif line.strip():
            name, value = line.split(":", 1)
            blocks[-1][name.strip()] = value.strip()
    return blocks


def _pqr(text: str) -> list[dict]:
    return [{"x_A": float(line[30:38]), "y_A": float(line[38:46]), "z_A": float(line[46:54]),
             "radius_A": float(line[65:71]), "resid": int(line[22:26])}
            for line in text.splitlines() if line.startswith("ATOM")]


def _pdb_atoms(text: str) -> list[dict]:
    return [{"name": line[12:16].strip(), "resname": line[17:20], "chain": line[21], "resseq": int(line[22:26]),
             "xyz": [float(line[30:38]), float(line[38:46]), float(line[46:54])], "element": line[76:78].strip()}
            for line in text.splitlines() if line.startswith("ATOM")]


def _verify_pocket_set(client: TestClient, rid: str, handle: str) -> dict:
    """Check every rank/sphere/lining atom against independent re-reads of stored bytes."""
    run = api_module._run(rid)
    stored = run.store.load(handle)
    manifest = run.store.load(stored["detector_input_handle"])
    pdb = run.store.load(manifest["transport_pdb_handle"])
    assert hashlib.sha256(pdb).hexdigest() == manifest["transport_pdb_sha256"]
    native, files = _native_files(run, stored["native_output_handle"])
    assert stored["raw_file_hashes"] == {path: hashlib.sha256(raw).hexdigest() for path, raw in files.items()}
    assert set(files) == ({"protein_info.txt", "protein_pockets.pqr"} |
                          {f"pockets/pocket{r}_{s}" for r in range(1, stored["total_count"] + 1)
                           for s in ("vert.pqr", "atm.pdb")})
    hashed_only = {item["path"] for item in native["files"] if not item["retained"]}
    assert hashed_only == {"protein_out.pdb", "protein.pml", "protein.tcl", "protein_PYMOL.sh", "protein_VMD.sh"}
    # Transport table re-read independently and tied to the source catalog coordinates.
    transport = _pdb_atoms(pdb.decode("ascii"))
    assert len(transport) == len(manifest["atoms"])
    catalog = {row["ref"]["site_index"]: row for row in atom_rows(run.store, stored["source_handle"])["rows"]} \
        if stored["source_kind"] != "chemical_structure" else None
    by_key = {}
    for index, (line, atom) in enumerate(zip(transport, manifest["atoms"], strict=True)):
        key = (line["chain"], line["resseq"], line["name"], line["element"])
        assert key not in by_key
        by_key[key] = index
        assert atom["transport_index"] == index and line["name"] == atom["ref"]["atom_name"]
        if catalog is not None:
            source = catalog[atom["ref"]["site_index"]]
            assert source["ref"] == atom["ref"]
            assert all(abs(a - b) <= 0.0005 + 1e-9 for a, b in zip(line["xyz"], source["coordinate_A"], strict=True))
    blocks = _info_blocks(files["protein_info.txt"].decode("ascii"))
    assert stored["total_count"] == len(blocks) == len(stored["pockets"])
    assert stored["null_result"] is (not blocks)
    all_spheres = Counter((s["resid"], s["x_A"], s["y_A"], s["z_A"], s["radius_A"])
                          for s in _pqr(files["protein_pockets.pqr"].decode("ascii")))
    for block, pocket in zip(blocks, stored["pockets"], strict=True):
        rank = int(block["rank"])
        assert pocket["rank"] == rank
        descriptors = pocket["descriptors"]
        assert descriptors["score"]["value"] == float(block["Score"]) and descriptors["score"]["unit"] == "dimensionless"
        assert descriptors["druggability_score"]["value"] == float(block["Druggability Score"])
        assert descriptors["druggability_score"]["unit"] == "dimensionless"
        assert descriptors["druggability_score"]["detector_specific_note"] == "fpocket 고유 점수이며 약물성 증거가 아님"
        assert descriptors["alpha_sphere_count"]["value"] == int(block["Number of Alpha Spheres"])
        assert descriptors["total_sasa_A2"]["value"] == float(block["Total SASA"])
        assert descriptors["total_sasa_A2"]["unit"] == "A2"
        assert descriptors["volume_A3"]["value"] == float(block["Volume"]) and descriptors["volume_A3"]["unit"] == "A3"
        spheres = _pqr(files[f"pockets/pocket{rank}_vert.pqr"].decode("ascii"))
        assert len(spheres) == int(block["Number of Alpha Spheres"]) == len(pocket["spheres"])
        assert pocket["spheres"] == [{k: s[k] for k in ("x_A", "y_A", "z_A", "radius_A")} for s in spheres]
        assert all(s["resid"] == rank for s in spheres)
        assert Counter((rank, s["x_A"], s["y_A"], s["z_A"], s["radius_A"]) for s in spheres) == Counter(
            {key: count for key, count in all_spheres.items() if key[0] == rank})
        assert all(3.4 - 0.005 - 1e-9 <= s["radius_A"] <= 6.2 + 0.005 + 1e-9 for s in spheres)
        center = np.mean([[s["x_A"], s["y_A"], s["z_A"]] for s in spheres], axis=0)
        shown = pocket["display_center"]
        assert shown["method"] == "arithmetic_mean_of_stored_sphere_centers"
        assert np.allclose([shown["x_A"], shown["y_A"], shown["z_A"]], center, rtol=0, atol=1e-9)
        records = _pdb_atoms(files[f"pockets/pocket{rank}_atm.pdb"].decode("ascii"))
        assert pocket["lining_atoms"]["native_record_count"] == len(records)
        order: list[int] = []
        for record in records:
            index = by_key[(record["chain"], record["resseq"], record["name"], record["element"])]
            assert all(abs(a - b) <= 0.0005 + 1e-9 for a, b in zip(record["xyz"], transport[index]["xyz"], strict=True))
            if index not in order:
                order.append(index)
        assert pocket["lining_atoms"]["transport_indices"] == order
        assert pocket["lining_atoms"]["atoms"] == [manifest["atoms"][i]["ref"] for i in order]
        residues: list[dict] = []
        for index in order:
            residue = manifest["atoms"][index]["ref"]["residue"]
            if residue not in residues:
                residues.append(residue)
        assert pocket["lining_residues"] == residues
        assert all(set(r) == {"model_number", "chain_auth", "seq_auth", "icode", "chain_label", "seq_label",
                              "resname"} for r in residues)
        geometry = client.get(f"/runs/{rid}/pockets/geometry", params={"handle": handle, "rank": rank})
        assert geometry.status_code == 200, geometry.text
        assert geometry.json()["spheres"] == pocket["spheres"]
        assert geometry.json()["lining_atoms"] == pocket["lining_atoms"]
        assert geometry.json()["lining_residues"] == pocket["lining_residues"]
    return stored


# ----------------------------------------------------------------- full product path on public_1hsg
def test_public_1hsg_full_product_path_and_events_only_replay(tmp_path, monkeypatch):
    for key in SENTINELS:
        monkeypatch.setenv(key, f"synthetic_{key}")
    root = tmp_path / "original"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M12 public 1hsg fpocket product path")
    source, prepared = _prepared(client, rid, HSG.read_bytes(), "public_1hsg.cif")
    preflight = client.get(f"/runs/{rid}/pockets/preflight", params={"structure": prepared})
    assert preflight.status_code == 200, preflight.text
    summary = preflight.json()
    assert summary["status"] == "ready" and summary["available"] is True and summary["starts_job"] is False
    assert summary["capability"]["status"] == "ready"
    assert summary["selected_chains"] == ["A", "B"] and summary["reject"] is None
    assert summary["retention"] == {"limit_bytes": 64 * 1024 * 1024, "used_bytes": 0,
                                    "remaining_bytes": 64 * 1024 * 1024}
    assert summary["budget"]["expensive_calls"]["used"] == 0
    assert summary["determinism"]["fresh_execution_deterministic"] is False
    raw_preflight = client.get(f"/runs/{rid}/pockets/preflight", params={"structure": source}).json()
    assert raw_preflight["status"] == "unsupported_input"
    assert raw_preflight["reject"]["reason_code"] == "raw_structure_requires_preparation"
    assert not any(e["type"] in {"job_submitted", "budget_reserved"} for e in _events(root, rid))
    assert client.post(f"/runs/{rid}/jobs/approve").status_code == 412

    done = _detect(client, rid, prepared)
    handle = done["artifacts"]["pocket_set"]
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 1
    events = _events(root, rid)
    assert [e["type"] for e in events if e["type"] in {"approval_requested", "approval_resolved"}] == [
        "approval_requested", "approval_resolved"]
    started = [e for e in events if e["type"] == "job_worker_started"]
    assert len(started) == 1
    attempt_dir = root / rid / "jobs" / done["job_id"] / done["attempt_id"]
    worker = json.loads((attempt_dir / "result.json").read_text())
    # Egress: only the allowlisted environment reaches the engine even with sentinels in the parent.
    assert worker["engine_environment_keys"] == ["LANG", "LC_ALL", "PATH", "TMPDIR"]
    assert (attempt_dir / "stdout.log").read_bytes() == b"" and (attempt_dir / "stderr.log").read_bytes() == b""
    for key in SENTINELS:
        assert f"synthetic_{key}".encode() not in (root / rid / "events.jsonl").read_bytes()

    stored = _verify_pocket_set(client, rid, handle)
    assert stored["total_count"] >= 1 and stored["null_result"] is False
    assert set(stored) == pocket_bundle.SET_KEYS and set(stored["method"]) == pocket_bundle.METHOD_KEYS
    method = stored["method"]
    assert method["argv"][0] == "fpocket" and method["parser_version"] == "fpocket_4_2_3_output@1"
    assert method["seed_control"] == "unsupported" and method["fresh_execution_deterministic"] is False
    assert method["observed_banner"] == "fpocket 4.0" and method["transport_precision_A"] == 0.001
    assert method["effective_parameters"]["argv"][1:] == method["argv"][1:]
    assert any("relative within one run" in item for item in stored["limitations"])
    assert any("not binding-site, affinity or druggability evidence" in item for item in stored["limitations"])
    manifest = api_module._run(rid).store.load(stored["detector_input_handle"])
    assert manifest["schema"] == "pocket_detector_input@1" and manifest["source_handle"] == prepared
    assert stored["preparation_handle"] == api_module._run(rid).store.load(prepared)["manifest"]

    listing = client.get(f"/runs/{rid}/pockets").json()
    assert listing["total"] == 1
    row = listing["rows"][0]
    assert {key: row[key] for key in ("handle", "source_handle", "selected_chains", "total_count",
                                      "null_result", "job_id")} == {
        "handle": handle, "source_handle": prepared, "selected_chains": ["A", "B"],
        "total_count": stored["total_count"], "null_result": False, "job_id": done["job_id"]}
    result = client.get(f"/runs/{rid}/pockets/result", params={"handle": handle})
    assert result.status_code == 200, result.text
    result_json = result.json()
    assert result_json["total_count"] == stored["total_count"] and result_json["method"] == stored["method"]
    assert [p["rank"] for p in result_json["pockets"]] == list(range(1, stored["total_count"] + 1))
    for pocket, full in zip(result_json["pockets"], stored["pockets"], strict=True):
        assert "spheres" not in pocket and "lining_atoms" not in pocket
        assert pocket["descriptors"] == full["descriptors"]
        assert pocket["lining_residue_count"] == len(full["lining_residues"])
        assert pocket["display_center"] == full["display_center"]
    assert client.get(f"/runs/{rid}/pockets/geometry",
                      params={"handle": handle, "rank": stored["total_count"] + 1}).status_code == 404
    for wrong in (stored["detector_input_handle"], stored["native_output_handle"], prepared,
                  f"obj://{rid}/pocket_set/{'0' * 64}"):
        response = client.get(f"/runs/{rid}/pockets/result", params={"handle": wrong})
        assert response.status_code == 422 and response.json()["detail"]["error"] == "method_evidence_invalid"
    other = _new_run(client, "foreign pocket read")
    assert client.get(f"/runs/{other}/pockets/result", params={"handle": handle}).status_code == 422
    assert client.get(f"/runs/{rid}/pockets/preflight", params={"structure": prepared}).json()["retention"][
        "used_bytes"] == api_module._run(rid).store.meta(stored["native_output_handle"])["size"]

    # Same call key returns the stored job, whatever chain spelling or timeout is used.
    for chains, timeout_s in (([], 120), (["B", "A"], 60), (None, 30)):
        again = _submit(client, rid, prepared, chains, timeout_s)
        assert again["job_id"] == done["job_id"] and again["status"] == "done"
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 1

    # Events-only replay with the engine and original upload/objects/SQLite absent.
    before = (root / rid / "events.jsonl").read_bytes()
    replay = tmp_path / "events_only"
    (replay / rid).mkdir(parents=True)
    (replay / rid / "events.jsonl").write_bytes(before)
    monkeypatch.setattr(pocket_bundle, "ENGINE_ROOT", tmp_path / "engine_removed")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("events-only reads must not execute scientific work")

    monkeypatch.setattr(JobQueue, "_supervise", forbidden)
    monkeypatch.setattr(Run, "call", forbidden)
    monkeypatch.setattr(pocket_bundle, "publish", forbidden)
    monkeypatch.setattr(pocket_bundle, "project", forbidden)
    monkeypatch.setattr(api_module, "RUNS_DIR", replay)
    api_module.RUNS.clear()
    assert client.get("/capabilities").json()["methods"]["pocket_detection"]["status"] == "not_installed"
    assert client.get(f"/runs/{rid}/pockets/result", params={"handle": handle}).json() == result_json
    assert client.get(f"/runs/{rid}/pockets").json() == listing
    for rank in range(1, stored["total_count"] + 1):
        reopened = client.get(f"/runs/{rid}/pockets/geometry", params={"handle": handle, "rank": rank})
        assert reopened.status_code == 200 and reopened.json()["spheres"] == stored["pockets"][rank - 1]["spheres"]
    assert api_module._run(rid).store.load(handle) == stored
    assert (replay / rid / "events.jsonl").read_bytes() == before
    tampered = replay / rid / "objects" / (stored["native_output_handle"].rsplit("/", 1)[-1] + ".json")
    tampered.write_text("{}")
    assert client.get(f"/runs/{rid}/pockets/result", params={"handle": handle}).status_code == 422


# ----------------------------------------------------------------- derived small fixture: real empty path
def test_derived_first10_fixture_runs_through_the_real_engine(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M12 derived first10 fixture")
    _, prepared = _prepared(client, rid, DERIVED_FIRST10.read_bytes(), "derived_1hsg_first10_fixture.cif")
    preflight = client.get(f"/runs/{rid}/pockets/preflight", params={"structure": prepared}).json()
    assert preflight["projected_atom_count"] == 88 and preflight["projected_residue_count"] == 10
    done = _detect(client, rid, prepared)
    handle = done["artifacts"]["pocket_set"]
    stored = _verify_pocket_set(client, rid, handle)
    run = api_module._run(rid)
    native, files = _native_files(run, stored["native_output_handle"])
    if stored["total_count"] == 0:
        # The supported scientific_null convention, observed from this real execution.
        assert stored["null_result"] is True and stored["pockets"] == [] and run.store.meta(handle)["null_result"]
        assert files["protein_info.txt"] == b""
        assert not _pqr(files["protein_pockets.pqr"].decode("ascii"))
        stderr = base64.b64decode(native["stderr"]["content_b64"]).decode("ascii")
        assert set(stderr.splitlines()) == {"! No Pockets Found while refining", "! No pocket to reindex."}
        result = client.get(f"/runs/{rid}/pockets/result", params={"handle": handle}).json()
        assert result["null_result"] is True and result["pockets"] == []
    else:  # pragma: no cover - preserved, not forced: a real pocket here is reported, never overwritten
        print(f"derived first10 fixture produced {stored['total_count']} pockets; preserved for investigation")


# ----------------------------------------------------------------- translation invariance
def _matches(reference: dict, moved: dict) -> bool:
    """Same sphere multiset after subtracting the translation (0.001 Å output precision each side)."""
    a = sorted((s["x_A"], s["y_A"], s["z_A"], s["radius_A"]) for s in reference["spheres"])
    b = sorted((s["x_A"] - TRANSLATION[0], s["y_A"] - TRANSLATION[1], s["z_A"] - TRANSLATION[2], s["radius_A"])
               for s in moved["spheres"])
    return len(a) == len(b) and all(p[3] == q[3] and all(abs(x - y) <= 0.0011 for x, y in zip(p[:3], q[:3]))
                                    for p, q in zip(a, b, strict=True))


def test_translated_source_moves_sphere_geometry_by_the_translation(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M12 translation invariance (derived translated input)")
    _, original = _prepared(client, rid, HSG.read_bytes(), "public_1hsg.cif")
    _, moved = _prepared(client, rid, _derived_translated(), "derived_1hsg_translated_fixture.cif")
    first = _verify_pocket_set(client, rid, _detect(client, rid, original)["artifacts"]["pocket_set"])
    second = _verify_pocket_set(client, rid, _detect(client, rid, moved)["artifacts"]["pocket_set"])
    # Pocket geometry is compared pocket by pocket (native ranks, scores and volumes may differ). The
    # engine's floating-point filters can keep or drop a boundary pocket in one frame only, so a small
    # unmatched remainder is tolerated, never the bulk of the geometry.
    pairs, used = [], set()
    for pocket in first["pockets"]:
        hit = [other for other in second["pockets"] if other["rank"] not in used and _matches(pocket, other)]
        if hit:
            used.add(hit[0]["rank"])
            pairs.append((pocket, hit[0]))
    largest = max(first["pockets"], key=lambda pocket: len(pocket["spheres"]))
    assert any(pocket is largest for pocket, _ in pairs)
    for stored in (first, second):
        total = sum(len(p["spheres"]) for p in stored["pockets"])
        matched = sum(len(p["spheres"]) for pair in pairs for p in pair if p in stored["pockets"])
        assert total and matched >= 0.9 * total, (matched, total)
    for pocket, other in pairs:
        # Same source residues (7 fields); native record order is not a geometric property.
        assert (sorted(json.dumps(r, sort_keys=True) for r in pocket["lining_residues"]) ==
                sorted(json.dumps(r, sort_keys=True) for r in other["lining_residues"]))
        assert abs(pocket["display_center"]["x_A"] + TRANSLATION[0] - other["display_center"]["x_A"]) <= 0.0011


# ----------------------------------------------------------------- submission validation and reuse
def test_submission_validation_dry_run_and_cancelled_call_key_reuse(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M12 submission rules")
    source, prepared = _prepared(client, rid, HSG.read_bytes(), "public_1hsg.cif")
    bad = [({"structure": prepared, "engine": "p2rank"}, 422), ({"structure": prepared, "top_k": 3}, 422),
           ({"structure": prepared, "argv": ["x"]}, 422), ({"structure": prepared, "executable": "/bin/sh"}, 422),
           ({"structure": prepared, "chains": "A"}, 422), ({"structure": prepared, "chains": ["Z"]}, 422),
           ({"chains": []}, 422), ({"structure": source}, 412), ({"structure": 3}, 422)]
    for args, status in bad:
        response = client.post(f"/runs/{rid}/jobs", json={"protocol_id": "fpocket_detect_v1", "args": args,
                                                        "timeout_s": 120})
        assert response.status_code == status, (args, response.text)
    too_long = client.post(f"/runs/{rid}/jobs", json={"protocol_id": "fpocket_detect_v1",
                                                    "args": {"structure": prepared}, "timeout_s": 121})
    assert too_long.status_code == 422
    assert client.post(f"/runs/{rid}/commands", json={"tool": "detect_pockets",
                                                      "args": {"structure": prepared}}).status_code in {412, 422}
    assert not any(e["type"] in {"job_submitted", "budget_reserved"} for e in _events(root, rid))

    chosen = client.get(f"/runs/{rid}/pockets/preflight", params={"structure": prepared, "chains": ["A"]}).json()
    assert chosen["selected_chains"] == ["A"] and chosen["status"] == "ready"
    unknown = client.get(f"/runs/{rid}/pockets/preflight", params={"structure": prepared, "chains": ["Z"]}).json()
    assert unknown["status"] == "unsupported_input" and unknown["reject"]["reason_code"] == "unknown_chain"
    job = _submit(client, rid, prepared, [])
    assert job["timeout_s"] == 120 and job["input_handles"] == [prepared]
    cancelled = client.post(f"/runs/{rid}/jobs/{job['job_id']}/cancel").json()
    assert cancelled["job"]["status"] == "cancelled"
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 0
    for chains in (["A", "B"], ["B", "A"], None):
        again = _submit(client, rid, prepared, chains)
        assert again["job_id"] == job["job_id"] and again["status"] == "cancelled"
    subset = _submit(client, rid, prepared, ["A"])
    assert subset["job_id"] != job["job_id"] and subset["status"] == "queued"
    run = api_module._run(rid)
    assert JobQueue(run).get(subset["job_id"])["selected"]["selected_chains"] == ["A"]
    dry = new_run(tmp_path / "dry", dry_run=True, run_id="run_dry_pockets")
    handle = dry.call("prepare_structure", {"structure": dry.call("load_structure", {
        "source": "public_1hsg.cif"}, source_bytes=HSG.read_bytes(), source_format="cif").handle, **PREPARE}).handle
    plan = JobQueue(dry).submit("fpocket_detect_v1", {"structure": handle}, timeout_s=120)
    assert plan["plan_only"] is True and plan["normalized_parameters"]["chains"] == ["A", "B"]


# ----------------------------------------------------------------- capability states
def _fake_engine(root: Path, *, executable: bytes | None = None, record_patch: dict | None = None) -> Path:
    """Labeled fake engine root for capability-state tests (never executed)."""
    real = pocket_bundle.ROOT / ".deps/fpocket"
    (root / "env/bin").mkdir(parents=True)
    if executable is None:
        shutil.copyfile(real / "env/bin/fpocket", root / "env/bin/fpocket")
    else:
        (root / "env/bin/fpocket").write_bytes(executable)
    record = json.loads((real / "install-record.json").read_text())
    record.update(record_patch or {})
    (root / "install-record.json").write_text(json.dumps(record))
    return root


def test_capability_states_and_unavailable_submit_is_uncharged(tmp_path, monkeypatch):
    calls = []
    original = pocket_bundle._handshake
    monkeypatch.setattr(pocket_bundle, "_handshake", lambda root: calls.append(root) or original(root))
    pocket_bundle._HANDSHAKE_CACHE.clear()
    monkeypatch.setattr(pocket_bundle, "ENGINE_ROOT", tmp_path / "missing")
    missing = pocket_bundle.capability()
    assert missing["status"] == "not_installed" and missing["available"] is False and missing["reason"]
    assert calls == []
    monkeypatch.setattr(pocket_bundle, "ENGINE_ROOT", _fake_engine(tmp_path / "hash", executable=b"fake fpocket\n"))
    mismatch = pocket_bundle.capability()
    assert mismatch["status"] == "unreviewed_build" and mismatch["reason_code"] == "executable_hash_mismatch"
    monkeypatch.setattr(pocket_bundle, "ENGINE_ROOT", _fake_engine(tmp_path / "build",
                                                                   record_patch={"build": "hb88c64c_1"}))
    assert pocket_bundle.capability()["reason_code"] == "install_record_mismatch"
    pocket_bundle.capability()
    assert len(calls) == 3  # failed handshakes are never cached
    monkeypatch.setattr(pocket_bundle, "ENGINE_ROOT", _fake_engine(tmp_path / "copy"))
    assert pocket_bundle.capability()["status"] == "ready"
    assert pocket_bundle.capability()["status"] == "ready"
    assert len(calls) == 4  # a verified handshake is reused while its key is unchanged
    record = pocket_bundle.ENGINE_ROOT / "install-record.json"
    record.write_text(record.read_text() + "\n")
    assert pocket_bundle.capability()["status"] == "ready" and len(calls) == 5
    broken = tmp_path / "broken_handshake_worker.py"  # labeled fake worker for the handshake-failed state
    broken.write_text("print('not json')\n")
    monkeypatch.setattr(pocket_bundle, "WORKER", broken)
    assert pocket_bundle.capability()["status"] == "handshake_failed"
    monkeypatch.setattr(pocket_bundle, "WORKER", Path(pocket_worker.__file__).resolve())
    monkeypatch.setattr(pocket_bundle.platform, "machine", lambda: "x86_64")
    assert pocket_bundle.capability()["status"] == "unsupported_platform"
    monkeypatch.undo()
    pocket_bundle._HANDSHAKE_CACHE.clear()

    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M12 engine unavailable")
    _, prepared = _prepared(client, rid, HSG.read_bytes(), "public_1hsg.cif")
    job = _submit(client, rid, prepared)
    monkeypatch.setattr(pocket_bundle, "ENGINE_ROOT", tmp_path / "missing")
    preflight = client.get(f"/runs/{rid}/pockets/preflight", params={"structure": prepared}).json()
    assert preflight["status"] == "not_installed" and preflight["available"] is False
    refused = client.post(f"/runs/{rid}/jobs", json={"protocol_id": "fpocket_detect_v1",
                                                    "args": {"structure": prepared, "chains": ["A"]}})
    assert refused.status_code == 412 and refused.json()["detail"]["reason_code"] == "not_installed"
    blocked = _approve_start(client, rid, job["job_id"])
    assert blocked.status_code == 412 and blocked.json()["detail"]["reason_code"] == "not_installed"
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 0
    assert not any(e["type"] == "job_dispatch_intent" for e in _events(root, rid))


# ----------------------------------------------------------------- failures, retry and publication guards
def test_failed_attempt_is_charged_retry_then_succeeds(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M12 charged failure then retry")
    _, prepared = _prepared(client, rid, HSG.read_bytes(), "public_1hsg.cif")
    job = _submit(client, rid, prepared)
    original = pocket_bundle.stage

    def broken_stage(run, job_record, attempt_id):  # labeled fault: staged atom table emptied
        staged = json.loads(original(run, job_record, attempt_id))
        staged["atoms"] = []
        return json.dumps(staged, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    with monkeypatch.context() as patch:
        patch.setattr(pocket_bundle, "stage", broken_stage)
        failed = _approve_start(client, rid, job["job_id"]).json()
    assert failed["status"] == "failed" and failed["failure"]["reason_code"] == "staged_input_invalid"
    assert failed["output_handles"] == []
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 1
    retried = client.post(f"/runs/{rid}/jobs/{job['job_id']}/retry").json()
    assert retried["status"] == "queued"
    done = _approve_start(client, rid, job["job_id"]).json()
    assert done["status"] == "done" and done["attempt_ordinal"] == 2
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 2
    _verify_pocket_set(client, rid, done["artifacts"]["pocket_set"])
    # An exhausted expensive budget blocks the next attempt before any reservation or launch.
    run = api_module._run(rid)
    run.update_limits(run.budget.limits.model_copy(update={"expensive_calls": 2}))
    extra = _submit(client, rid, prepared, ["A"])
    blocked = client.post(f"/runs/{rid}/jobs/{extra['job_id']}/start")
    assert blocked.status_code == 409 and blocked.json()["approval"]["gate"] == "budget"
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 2
    assert client.get(f"/runs/{rid}/jobs/{extra['job_id']}").json()["attempt_id"] is None


def test_cancel_or_stale_completion_never_publishes(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M12 cancel before publication")
    _, prepared = _prepared(client, rid, HSG.read_bytes(), "public_1hsg.cif")
    first = _submit(client, rid, prepared, ["A"])
    original = JobQueue._supervise

    def cancel_after_genuine_worker(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch):
        result, identity = original(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch)
        assert result and result.get("returncode") == 0
        self.request_cancel(job["job_id"])
        return result, identity

    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_supervise", cancel_after_genuine_worker)
        response = _approve_start(client, rid, first["job_id"]).json()
    assert response["status"] == "cancelled" and response["output_handles"] == []
    assert not any(e["type"] == "object_created" and e.get("kind", "").startswith("pocket_")
                   for e in _events(root, rid))
    # Cancelled between candidate and terminal: objects exist in the log but are never readable.
    second = _submit(client, rid, prepared, ["B"])
    run = api_module._run(rid)
    queue = JobQueue(run, barrier=lambda stage: stage == "before_terminal" and JobQueue(run).request_cancel(
        second["job_id"]))
    queue.start(second["job_id"])
    assert JobQueue(run).get(second["job_id"])["status"] == "cancelled"
    written = [e["handle"] for e in _events(root, rid) if e["type"] == "object_created" and e["kind"] == "pocket_set"]
    assert len(written) == 1
    assert client.get(f"/runs/{rid}/pockets/result", params={"handle": written[0]}).status_code == 422
    assert client.get(f"/runs/{rid}/pockets").json()["total"] == 0
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 2


def test_stream_and_retention_limits_fail_charged_without_partial_objects(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M12 native evidence limits")
    _, prepared = _prepared(client, rid, HSG.read_bytes(), "public_1hsg.cif")
    first = _submit(client, rid, prepared, ["A"])
    original = JobQueue._supervise

    def oversized_stream(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch):
        result, identity = original(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch)
        (attempt_dir / "engine.stdout").write_bytes(b"X" * (1024 * 1024 + 1))  # labeled fault after the real run
        return result, identity

    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_supervise", oversized_stream)
        failed = _approve_start(client, rid, first["job_id"]).json()
    assert failed["status"] == "failed"
    assert failed["failure"]["error"] == "resource_exceeded" and failed["failure"]["reason_code"] == "stdout_limit"
    done = _detect(client, rid, prepared, ["B"])
    used = client.get(f"/runs/{rid}/pockets/preflight", params={"structure": prepared}).json()["retention"]
    assert used["used_bytes"] > 0
    monkeypatch.setattr(pocket_bundle, "MAX_RETAINED_NATIVE_BYTES", used["used_bytes"] + 1)
    before = [e for e in _events(root, rid) if e["type"] == "object_created"]
    third = _submit(client, rid, prepared)
    over = _approve_start(client, rid, third["job_id"]).json()
    assert over["status"] == "failed" and over["failure"]["reason_code"] == "native_output_retention_limit"
    assert over["failure"]["error"] == "resource_exceeded"
    assert [e for e in _events(root, rid) if e["type"] == "object_created"] == before
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 3
    remaining = client.get(f"/runs/{rid}/pockets/preflight", params={"structure": prepared}).json()["retention"]
    assert remaining["remaining_bytes"] == 1
    assert client.get(f"/runs/{rid}/pockets").json()["rows"][0]["handle"] == done["artifacts"]["pocket_set"]


# ----------------------------------------------------------------- running engine: cancel, timeout, caps, restart
def _engine_child(worker_pid: int, timeout: float = 20) -> psutil.Process:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            for child in psutil.Process(worker_pid).children():
                if child.name() == "fpocket":
                    return child
        except psutil.NoSuchProcess:
            break
        time.sleep(0.005)
    pytest.fail("the real fpocket process never started")


def _gone(process: psutil.Process) -> bool:
    try:
        return process.status() == psutil.STATUS_ZOMBIE or not process.is_running()
    except psutil.NoSuchProcess:
        return True


@pytest.mark.parametrize("fault", ["cancel", "output_files", "output_bytes", "stderr"])
def test_running_engine_is_stopped_with_its_process_group(tmp_path, monkeypatch, fault):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, f"M12 running engine {fault} (derived replicated input)")
    _, prepared = _prepared(client, rid, _derived_replicated(), "derived_1hsg_replicated_fixture.cif")
    job = _submit(client, rid, prepared)
    seen: list[psutil.Process] = []
    original = JobQueue._record_control

    def act_on_running_engine(self, message, job_id, attempt_id, nonce):
        done = original(self, message, job_id, attempt_id, nonce)
        if message and message.get("kind") == "STARTED" and not seen:
            engine = _engine_child(message["pid"])
            seen.append(engine)
            attempt_dir = self.run.run_dir / "jobs" / job_id / attempt_id
            if fault == "cancel":
                self.request_cancel(job_id)
            elif fault == "output_files":  # labeled fault: output tree grows past 1000 files
                for index in range(1001):
                    (attempt_dir / "fpocket_tmp" / f"injected_{index}").write_bytes(b"")
            elif fault == "output_bytes":  # labeled fault: output tree grows past 30 MiB
                (attempt_dir / "fpocket_tmp" / "injected.bin").write_bytes(b"\0" * (30 * 1024 * 1024 + 1))
            else:  # labeled fault: engine stderr grows past 1 MiB
                with (attempt_dir / "engine.stderr").open("ab") as stream:
                    stream.write(b"E" * (1024 * 1024 + 1))
        return done

    with monkeypatch.context() as patch:
        patch.setattr(JobQueue, "_record_control", act_on_running_engine)
        response = _approve_start(client, rid, job["job_id"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert seen and _gone(seen[0])
    if fault == "cancel":
        assert result["status"] == "cancelled"
    else:
        assert result["status"] == "failed" and result["failure"]["error"] == "resource_exceeded"
    assert result["output_handles"] == [] and result["cleanup_status"] == "verified"
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 1
    assert not any(e["type"] == "object_created" and e.get("kind", "").startswith("pocket_")
                   for e in _events(root, rid))


def test_timeout_stops_the_attempt_and_is_charged(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M12 timeout (derived replicated input)")
    _, prepared = _prepared(client, rid, _derived_replicated(), "derived_1hsg_replicated_fixture.cif")
    job = _submit(client, rid, prepared, timeout_s=0.5)
    response = _approve_start(client, rid, job["job_id"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "failed" and result["failure"]["error"] == "resource_exceeded"
    assert result["output_handles"] == [] and result["cleanup_status"] == "verified"
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 1
    for event in _events(root, rid):
        if event["type"] == "job_worker_started":
            try:
                assert _gone(psutil.Process(event["pid"]))
            except psutil.NoSuchProcess:
                pass


def test_owner_death_is_reconciled_and_engine_group_stopped(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    fixture = tmp_path / "derived_1hsg_replicated_fixture.cif"
    fixture.write_bytes(_derived_replicated())
    script = r'''
import json, sys, time
from pathlib import Path
import psutil
from mw.workspace import new_run
from mw.jobs.queue import JobQueue
root, fixture = Path(sys.argv[1]), Path(sys.argv[2])
run = new_run(root, run_id="run_pocket_restart", dry_run=False)
source = run.call("load_structure", {"source": fixture.name}, source_bytes=fixture.read_bytes(), source_format="cif")
prepared = run.call("prepare_structure", {"structure": source.handle, "altloc": "highest_occupancy",
                    "waters": "keep_all", "hydrogens": "strip", "missing_residues": "leave_gaps",
                    "symmetry_mates": "ignore"})
run.approve("expensive_first_call")
state = {}
def barrier(stage):
    if stage == "after_worker_started":
        worker = [e for e in run.events.read() if e["type"] == "job_worker_started"][-1]["pid"]
        while True:
            engines = [c for c in psutil.Process(worker).children() if c.name() == "fpocket"]
            if engines:
                break
            time.sleep(0.005)
        (root / "engine.json").write_text(json.dumps({"pid": engines[0].pid, "job_id": state["job_id"]}))
        while True:
            time.sleep(1)
queue = JobQueue(run, barrier=barrier)
job = queue.submit("fpocket_detect_v1", {"structure": prepared.handle}, timeout_s=120)
state["job_id"] = job["job_id"]
queue.start(job["job_id"])
'''
    owner = subprocess.Popen([sys.executable, "-c", script, str(runs), str(fixture)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        end = time.monotonic() + 60
        while time.monotonic() < end and not (runs / "engine.json").exists():
            assert owner.poll() is None, owner.stderr.read().decode()
            time.sleep(0.02)
        marker = json.loads((runs / "engine.json").read_text())
        engine = psutil.Process(marker["pid"])
        owner.kill()
        owner.wait(timeout=5)
        end = time.monotonic() + 10
        while time.monotonic() < end and not _gone(engine):
            time.sleep(0.02)
        assert _gone(engine), "guardian must stop the owned engine group when its owner disappears"
        run = new_run(runs, run_id="run_pocket_restart", dry_run=False)
        queue = JobQueue(run)
        end = time.monotonic() + 10
        while time.monotonic() < end:
            state = next(job for job in queue.reconcile_run() if job["job_id"] == marker["job_id"])
            if state["status"] == "interrupted":
                break
            time.sleep(0.05)
        assert state["status"] == "interrupted" and state["output_handles"] == []
        assert run.budget.expensive_calls == 1
        assert JobQueue(run).retry(marker["job_id"])["status"] == "queued"
        done = JobQueue(run).start(marker["job_id"])
        assert done["status"] == "done" and done["attempt_ordinal"] == 2, done["failure"]
        assert run.budget.expensive_calls == 2
        client = _client(runs, monkeypatch)
        _verify_pocket_set(client, "run_pocket_restart", done["output_handles"][0])
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)


def test_concurrent_attempts_use_isolated_job_roots(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rids = [_new_run(client, f"M12 concurrent root {index}") for index in range(2)]
    jobs = []
    for rid in rids:
        _, prepared = _prepared(client, rid, HSG.read_bytes(), "public_1hsg.cif")
        job = _submit(client, rid, prepared)
        blocked = client.post(f"/runs/{rid}/jobs/{job['job_id']}/start")
        assert blocked.status_code == 409 and client.post(f"/runs/{rid}/jobs/approve").status_code == 200
        jobs.append((rid, job["job_id"]))
    responses: dict[str, object] = {}

    def start(rid: str, job_id: str) -> None:
        responses[rid] = client.post(f"/runs/{rid}/jobs/{job_id}/start")

    threads = [threading.Thread(target=start, args=item) for item in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    for rid, job_id in jobs:
        response = responses[rid]
        if response.status_code == 409:  # the global heavy-worker gate admitted the other run first
            assert response.json()["detail"]["reason_code"] == "global_concurrency_busy"
            response = client.post(f"/runs/{rid}/jobs/{job_id}/start")
        assert response.status_code == 200 and response.json()["status"] == "done", response.text
        responses[rid] = response
    roots = []
    for rid, job_id in jobs:
        done = responses[rid].json()
        attempt = root / rid / "jobs" / job_id / done["attempt_id"]
        roots.append(attempt / "fpocket")
        stored = api_module._run(rid).store.load(done["artifacts"]["pocket_set"])
        info = (attempt / "fpocket/protein_out/protein_info.txt").read_bytes()
        assert stored["raw_file_hashes"]["protein_info.txt"] == hashlib.sha256(info).hexdigest()
        assert list((attempt / "fpocket_tmp").iterdir()) == []
    assert roots[0] != roots[1] and roots[0].resolve() != roots[1].resolve()


# ----------------------------------------------------------------- guardian monitor and worker isolation
def test_guardian_pocket_output_monitor_counts_engine_output_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "fpocket/protein_out/pockets").mkdir(parents=True)
    (tmp_path / "fpocket_tmp").mkdir()
    (tmp_path / "fpocket/protein.pdb").write_bytes(b"X" * 4096)  # staged input is not output
    assert guardian_module.pocket_output_exceeded() is False
    monkeypatch.setattr(guardian_module, "POCKET_OUTPUT_BYTES", 100)
    monkeypatch.setattr(guardian_module, "POCKET_OUTPUT_FILES", 3)
    (tmp_path / "fpocket/protein_out/protein_info.txt").write_bytes(b"x" * 60)
    assert guardian_module.pocket_output_exceeded() is False
    (tmp_path / "fpocket_tmp/scratch").write_bytes(b"x" * 41)
    assert guardian_module.pocket_output_exceeded() is True
    (tmp_path / "fpocket_tmp/scratch").write_bytes(b"")
    for index in range(3):
        (tmp_path / f"fpocket/protein_out/pockets/pocket{index + 1}_atm.pdb").write_bytes(b"")
    assert guardian_module.pocket_output_exceeded() is True
    for path in (tmp_path / "fpocket/protein_out/pockets").iterdir():
        path.unlink()
    (tmp_path / "engine.stdout").write_bytes(b"x" * (1024 * 1024 + 1))
    assert guardian_module.pocket_output_exceeded() is True


def test_worker_has_no_network_or_shell_path_and_fixed_argv():
    source = Path(pocket_worker.__file__).read_text()
    for forbidden in ("import socket", "urllib", "http.client", "import requests", "httpx", "shell=True",
                      "os.system", "_PYMOL.sh", "_VMD.sh", "protein.pml", "protein.tcl"):
        assert forbidden not in source
    assert pocket_worker.engine_environment() == {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
                                                  "TMPDIR": "../fpocket_tmp"}
    assert pocket_bundle.ARGV == ["fpocket", *pocket_worker.ARGV_TAIL]
    parameters = json.loads(pocket_bundle.PARAMETERS.read_text())
    assert parameters["argv"] == ["<fpocket>", *pocket_worker.ARGV_TAIL]
    assert pocket_output.PARSER_VERSION == "fpocket_4_2_3_output@1"


def test_lining_records_accept_four_digit_transport_residue_numbers():
    """Transport residues are numbered 1..3000, so records past 999 must parse (SYNTHETIC lines)."""
    lines = ["ATOM   8370    O TRP L1095     359.192  38.404   0.903  0.00  0.00           O 0",
             "ATOM   9999   CA ALA a3000      -1.000   2.000  -3.500  1.00 10.00           C 0",
             "ATOM     12   CA ALA A   7       1.000   2.000   3.000  1.00 10.00           C 0", "TER", "END"]
    records = pocket_output._parse_atm(("\n".join(lines) + "\n").encode(), "pockets/pocket1_atm.pdb")
    assert [record["key"] for record in records] == [("L", 1095, "O", "O"), ("a", 3000, "CA", "C"), ("A", 7, "CA", "C")]
    with pytest.raises(pocket_output.PocketOutputFailure):
        pocket_output._parse_atm(("\n".join([lines[0].replace("L1095", "L1-95"), "TER", "END"]) + "\n").encode(),
                                 "pockets/pocket1_atm.pdb")


def test_chemical_and_minimized_sources_run_through_the_job_lane(tmp_path, monkeypatch):
    """Real ProLIF-prepared chemical source (public fixture) and real OpenMM-minimized public_1ubq."""
    from test_m11_job_api import _prepare_request
    from test_m11_job_api import _start as start_chemical

    from mw.jobs.openmm_worker import run as openmm_run
    from mw.jobs.openmm_worker import write_preparation

    root = tmp_path / "runs"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M12 chemical source pockets")
    prepared = start_chemical(client, rid, "prolif_prepare_v1", _prepare_request(client, rid))
    chemical = prepared["artifacts"]["chemical_structure"]
    preflight = client.get(f"/runs/{rid}/pockets/preflight", params={"structure": chemical}).json()
    assert preflight["status"] == "ready" and preflight["source_kind"] == "chemical_structure"
    assert preflight["excluded_counts"]["hydrogen"] > 0 and preflight["resname_mapping"]
    done = _detect(client, rid, chemical)
    stored = _verify_pocket_set(client, rid, done["artifacts"]["pocket_set"])
    manifest = api_module._run(rid).store.load(stored["detector_input_handle"])
    assert stored["source_kind"] == "chemical_structure" and manifest["resname_mapping"] == preflight["resname_mapping"]
    for pocket in stored["pockets"]:  # aliases travel as HIS; result identities keep the original names
        for index, ref in zip(pocket["lining_atoms"]["transport_indices"], pocket["lining_atoms"]["atoms"],
                              strict=True):
            if ref["residue"]["resname"] in {"HID", "HIE", "HIP", "HSD", "HSE", "HSP"}:
                assert manifest["atoms"][index]["transport_resname"] == "HIS"

    run = api_module._run(_new_run(client, "M12 minimized source pockets"))
    _, prepared_1ubq = _prepared(client, run.run_id, (FIXTURES / "public_1ubq.cif").read_bytes(), "public_1ubq.cif")
    queue = JobQueue(run)
    job = queue.submit("openmm_protein_minimize", {"structure": prepared_1ubq, "selection_policy": "protein_only",
                                                   "hydrogen_policy": "rebuild_pH7"})
    run.approve("expensive_first_call")

    def in_process_openmm(record, attempt_id, nonce, directory, deadline, dispatch):
        output = openmm_run(json.loads((directory / "structure.json").read_bytes()),
                            on_prepared=lambda item: write_preparation(item, directory))
        result = json.dumps(output, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        (directory / "result.json").write_bytes(result)
        return {"kind": "RESULT", "nonce": nonce, "job_id": record["job_id"], "attempt_id": attempt_id,
                "reason": "completed", "returncode": 0, "unexpected_members": False, "clean": True,
                "direct_child_reaped": True,
                "payload": {"output_sha256": hashlib.sha256(result).hexdigest(), "output_bytes": len(result)}}, None

    with monkeypatch.context() as patch:
        patch.setattr(queue, "_supervise", in_process_openmm)
        minimized_job = queue.start(job["job_id"])
    assert minimized_job["status"] == "done"
    minimized = run.store.load(minimized_job["output_handles"][0])["minimized_structure"]
    done = _detect(client, run.run_id, minimized)
    stored = _verify_pocket_set(client, run.run_id, done["artifacts"]["pocket_set"])
    assert stored["source_kind"] == "openmm_minimized_structure" and stored["source_handle"] == minimized
    assert api_module._run(run.run_id).store.load(stored["detector_input_handle"])["excluded_counts"]["hydrogen"] > 0
    assert done["job_id"] != _submit(client, run.run_id, prepared_1ubq)["job_id"]  # distinct source, distinct call
