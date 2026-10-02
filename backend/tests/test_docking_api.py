"""M18 T6: docking read API (spec 3.1, 7): prerequisites, receptor instances, result list/detail, contact pages and
pose SDF downloads. No read creates an event, a job or a tool call.

Results are made once per module by the real product path (chemical imports -> POST /jobs -> approve -> start) with
the pinned docking worker (``.deps/docking/venv-locked`` + ``.deps/qvina/env``); a missing environment FAILS, never
skips. The receptor is the public ProLIF example (a public prepared docking example, not experimental validation)
and the ligand the labeled public-derived parent record; a small manual box and exhaustiveness 1 keep it short.
Expected read values are the stored object's own values; the server never recomputes a score or contact.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mw import docking_bundle
from mw import docking_constants as C
from mw.api import app as api_module
from mw.core.handles import canonical_json

MW = Path(__file__).resolve().parents[1] / "mw"
CHEM = Path(__file__).parent / "fixtures/chemical"
FIX = Path(__file__).parent / "fixtures/docking"
EXPECTED = json.loads((FIX / "expected.json").read_text())
REC = (CHEM / "prolif-vina-rec.pdb").read_bytes()
PARENT = (FIX / "public-derived-parent-record0.sdf").read_bytes()
COMPLEX = (FIX / "synthetic-complex-receptor-lig.pdb").read_bytes()
WATER_ZINC = (FIX / "synthetic-receptor-water-zinc.pdb").read_bytes()
BLOCKS = (FIX / "synthetic-docking-blocks.smi").read_bytes()
INSTANCE = EXPECTED["receptor_fixtures"]["instance"]
COMPLEX_EXPECTED = EXPECTED["receptor_fixtures"]["synthetic-complex-receptor-lig.pdb"]
CENTER = EXPECTED["public_example_box"]["center_A"]
ACK = {key: True for key in C.ACKNOWLEDGEMENT_KEYS}
FORBIDDEN_MODULES = ("rdkit", "meeko", "MDAnalysis")
SDF_MEDIA = "chemical/x-mdl-sdfile"


# ----------------------------------------------------------------- shared world (real jobs, built once)
def _import(client: TestClient, rid: str, kind: str, filename: str, raw: bytes) -> str:
    response = client.post(f"/runs/{rid}/chemical/imports", params={"kind": kind, "filename": filename},
                           content=raw, headers={"content-type": "application/octet-stream"})
    assert response.status_code == 201, response.text
    return response.json()["handle"]


def _run_job(client: TestClient, rid: str, protocol: str, args: dict, timeout_s: float = 600) -> dict:
    submitted = client.post(f"/runs/{rid}/jobs", json={"protocol_id": protocol, "args": args,
                                                       "timeout_s": timeout_s})
    assert submitted.status_code == 200, submitted.text
    job_id = submitted.json()["job_id"]
    started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    if started.status_code == 409:
        assert client.post(f"/runs/{rid}/jobs/approve").status_code == 200
        started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    assert started.status_code == 200, started.text
    done = started.json()
    assert done["status"] == "done", done
    return done


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("docking_api") / "runs"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(api_module, "RUNS_DIR", root)
        api_module.RUNS.clear()
        client = TestClient(api_module.app, base_url="http://127.0.0.1")
        rid = client.post("/runs", json={"goal": "M18 docking reads", "dry_run": False}).json()["run_id"]
        receptor = _import(client, rid, "receptor", "rec.pdb", REC)
        ligand = _import(client, rid, "ligand_sdf", "parent.sdf", PARENT)
        complex_receptor = _import(client, rid, "receptor", "complex.pdb", COMPLEX)
        water_zinc = _import(client, rid, "receptor", "water-zinc.pdb", WATER_ZINC)
        blocks = _import(client, rid, "building_blocks_smiles", "blocks.smi", BLOCKS)
        inspected = _run_job(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": ligand, "block_handles": [blocks]},
                             120)
        enumerated = _run_job(client, rid, "rdkit_enumerate_v1",
                              {"inspection_handle": inspected["output_handles"][0], "site_atoms": [22],
                               "use_fixed": True}, 120)
        args = {"receptor_handle": receptor, "receptor_model_number": 1,
                "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
                "ligand": {"source": "sdf", "sdf_handle": ligand}, "mode": "free",
                "box": {"source": "manual", "center_A": CENTER, "size_A": [12.0, 12.0, 12.0]},
                "parameters": {"seed": 1, "exhaustiveness": 1, "num_modes": 3}, "acknowledgement": ACK}
        docked = _run_job(client, rid, "qvina_dock_v1", args)
        result = docked["artifacts"]["docking_result"]
        other = client.post("/runs", json={"goal": "M18 docking reads other", "dry_run": False}).json()["run_id"]
        other_receptor = _import(client, other, "receptor", "rec.pdb", REC)
        stored = api_module._run(rid).store.load(result)
    assert stored["modes"], "the shared free docking result must have modes to exercise the reads"
    assert any(row["contacts"] for row in stored["modes"]), "the shared result must have contacts"
    return {"root": root, "rid": rid, "other_rid": other, "receptor": receptor, "ligand": ligand,
            "complex": complex_receptor, "water_zinc": water_zinc, "blocks": blocks,
            "candidate_set": enumerated["output_handles"][0], "result": result, "job_id": docked["job_id"],
            "stored": stored, "other_receptor": other_receptor}


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", world["root"])
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _events(world, rid: str | None = None) -> list[dict]:
    path = world["root"] / (rid or world["rid"]) / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def _get(client, world, path: str, **params):
    return client.get(f"/runs/{world['rid']}/docking/{path}", params=params)


# ----------------------------------------------------------------- reads write no event and start no job
def test_every_read_leaves_events_and_jobs_unchanged(client, world):
    handle = world["result"]
    _get(client, world, "prerequisites")  # first touch reopens the run (job reconcile happens here)
    before = _events(world)
    reads = [("prerequisites", {}), ("receptor_instances", {"handle": world["complex"]}),
             ("receptor_instances", {"handle": world["receptor"]}), ("results", {}),
             ("results/detail", {"handle": handle}), ("results/contacts", {"handle": handle, "mode": 1}),
             ("results/pose_sdf", {"handle": handle, "mode": 1}), ("results/poses_sdf", {"handle": handle})]
    for path, params in reads:
        response = _get(client, world, path, **params)
        assert response.status_code == 200, (path, response.text)
    refused = [("prerequisites", {"x": "1"}), ("receptor_instances", {"handle": world["ligand"]}),
               ("results", {"bogus": "1"}), ("results/contacts", {"handle": handle, "mode": 1, "sort": "x"}),
               ("results/detail", {"handle": world["receptor"]}), ("results/pose_sdf", {"handle": handle, "mode": 99})]
    for path, params in refused:
        assert _get(client, world, path, **params).status_code in (404, 422), path
    assert client.get("/capabilities").status_code == 200
    after = _events(world)
    assert after == before
    assert sum(e["type"] == "job_submitted" for e in after) == 3  # inspect, enumerate, dock only


# ----------------------------------------------------------------- prerequisites
def test_prerequisites_lists_imports_candidate_sets_and_capability(client, world):
    body = _get(client, world, "prerequisites").json()
    assert body["schema"] == "docking_prerequisites@1" and body["starts_job"] is False
    assert body["import_counts"] == {"receptor": 3, "receptor_bonds": 0, "ligand_sdf": 1}
    expected = [(world["receptor"], "receptor", REC), (world["ligand"], "ligand_sdf", PARENT),
                (world["complex"], "receptor", COMPLEX), (world["water_zinc"], "receptor", WATER_ZINC)]
    assert [(row["handle"], row["input_kind"], row["size"], row["sha256"]) for row in body["imports"]] == [
        (handle, kind, len(raw), hashlib.sha256(raw).hexdigest()) for handle, kind, raw in expected]
    assert all(row["handle"] != world["blocks"] for row in body["imports"])  # M17 block libraries are not inputs
    stored_set = api_module._run(world["rid"]).store.load(world["candidate_set"])
    assert body["candidate_sets"] == [{"handle": world["candidate_set"], "valid": True,
                                       "candidates": len(stored_set["candidates"]),
                                       "parent_handle": world["ligand"],
                                       "parent_sha256": hashlib.sha256(PARENT).hexdigest(),
                                       "parent_sdf_handles": [world["ligand"]]}]
    assert body["docking_results"] == 1
    capability = body["capability"]
    assert capability["schema"] == "docking_capability@1" and capability["available"] is True
    assert capability["limitations"] == list(C.LIMITATIONS)
    other = client.get(f"/runs/{world['other_rid']}/docking/prerequisites").json()
    assert other["import_counts"] == {"receptor": 1, "receptor_bonds": 0, "ligand_sdf": 0}
    assert other["candidate_sets"] == [] and other["docking_results"] == 0


def test_capability_unavailable_reads_show_a_reason_without_numbers(client, world, tmp_path, monkeypatch):
    monkeypatch.setattr(docking_bundle, "QVINA", tmp_path / "missing/qvina2")
    capability = _get(client, world, "prerequisites").json()["capability"]
    assert capability["available"] is False and capability["reason_code"] == "engine_missing"
    assert capability["reason"] == docking_bundle.REASONS["engine_missing"]
    assert capability["pins"] is None and capability["versions"] is None
    # Stored, validated results stay readable (evidence, not a new computation); nothing is started.
    before = _events(world)
    assert _get(client, world, "results/detail", handle=world["result"]).status_code == 200
    assert _get(client, world, "results").json()["rows"][0]["valid"] is True
    assert _events(world) == before


# ----------------------------------------------------------------- receptor instances
def test_receptor_instances_keep_the_seven_fields(client, world):
    body = _get(client, world, "receptor_instances", handle=world["complex"]).json()
    assert body["schema"] == "docking_receptor_instances@1" and body["handle"] == world["complex"]
    assert body["sha256"] == hashlib.sha256(COMPLEX).hexdigest() and body["format"] == "pdb"
    assert body["model_numbers"] == [1] and body["selection_aid_only"] is True and body["starts_job"] is False
    assert body["models"] == [{"model_number": 1, "water_residue_count": 0, "instances": [
        {"residue": INSTANCE, "atom_count": COMPLEX_EXPECTED["instance_atoms"],
         "element_counts": COMPLEX_EXPECTED["instance_element_counts"]}]}]
    residue = body["models"][0]["instances"][0]["residue"]
    assert set(residue) == {"model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"}
    assert residue["chain_label"] is None and residue["seq_label"] is None  # nulls kept as read
    plain = _get(client, world, "receptor_instances", handle=world["receptor"]).json()
    assert plain["models"] == [{"model_number": 1, "water_residue_count": 0, "instances": []}]
    # Water is only counted; the zinc ion is a listed instance.
    wet = _get(client, world, "receptor_instances", handle=world["water_zinc"]).json()["models"][0]
    assert wet["water_residue_count"] == 1
    assert [(row["residue"]["resname"], row["residue"]["chain_auth"], row["residue"]["seq_auth"],
             row["atom_count"], row["element_counts"]) for row in wet["instances"]] == [("ZN", "Z", 1, 1, {"Zn": 1})]


def test_receptor_instances_refuse_wrong_kind_foreign_and_unknown_params(client, world):
    for handle in (world["ligand"], world["result"], world["candidate_set"], world["other_receptor"],
                   "obj://nope", f"obj://{world['rid']}/chemical_raw_input/{'0' * 64}"):
        response = _get(client, world, "receptor_instances", handle=handle)
        assert response.status_code == 422 and response.json()["detail"]["error"] == "input_invalid", handle
    assert _get(client, world, "receptor_instances").status_code == 422
    assert _get(client, world, "receptor_instances", handle=world["complex"], model=1).status_code == 422


# ----------------------------------------------------------------- result list and detail
def test_result_list_and_detail(client, world):
    stored = world["stored"]
    listed = _get(client, world, "results").json()
    assert listed["schema"] == "docking_result_list@1" and listed["total"] == 1
    assert listed["rows"] == [{"handle": world["result"], "created_seq": listed["rows"][0]["created_seq"],
                               "valid": True, "reason_code": None, "job_id": world["job_id"],
                               "method": "qvina_free_v1", "mode": "free", "ligand_source": "sdf",
                               "candidate_id": None, "receptor_handle": world["receptor"], "seed": 1,
                               "box_source": "manual", "modes": len(stored["modes"]), "null_result": False}]
    assert _get(client, world, "results", offset=1).json()["rows"] == []
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "x"}, {"what": "1"}):
        assert _get(client, world, "results", **params).status_code == 422, params
    assert client.get(f"/runs/{world['other_rid']}/docking/results").json()["total"] == 0
    detail = _get(client, world, "results/detail", handle=world["result"]).json()
    assert detail["schema"] == "docking_result_detail@1" and detail["job_id"] == world["job_id"]
    assert detail["score_label"] == C.SCORE_LABEL
    result = detail["result"]
    assert {key: value for key, value in result.items() if key != "modes"} == {
        key: value for key, value in stored.items() if key != "modes"}
    assert "pose_sdf" not in json.dumps(result) and "receptor_atom" not in json.dumps(result)
    for row, original in zip(result["modes"], stored["modes"], strict=True):
        assert row == {**{key: original[key] for key in original if key not in ("pose_sdf", "contacts")},
                       "contact_count": len(original["contacts"])}
    assert [row["contact_count"] for row in result["modes"]] == stored["counts"]["contacts_by_mode"]
    assert result["limitations"] == list(C.applicable_limitations(mode="free", source="sdf", removed_instance=False,
                                                                   unspecified_stereo_centers=None))


def test_result_reads_refuse_wrong_kind_and_foreign_handles(client, world):
    foreign = world["result"].replace(world["rid"], world["other_rid"])
    for path, extra in (("results/detail", {}), ("results/contacts", {"mode": 1}),
                        ("results/pose_sdf", {"mode": 1}), ("results/poses_sdf", {})):
        for handle in (world["receptor"], world["candidate_set"]):
            response = _get(client, world, path, handle=handle, **extra)
            assert response.status_code == 422 and response.json()["detail"]["error"] == "input_invalid"
        assert _get(client, world, path, handle=foreign, **extra).status_code == 404
        assert _get(client, world, path, **extra).status_code == 422  # handle required
        assert _get(client, world, path, handle=world["result"], extra="1", **extra).status_code == 422


# ----------------------------------------------------------------- contact pages
def test_contact_pages_bounds_and_order(client, world):
    stored = world["stored"]
    for number, mode in enumerate(stored["modes"], start=1):
        total = len(mode["contacts"])
        page = _get(client, world, "results/contacts", handle=world["result"], mode=number, limit=500).json()
        assert page["schema"] == "docking_contact_page@1" and page["mode"] == number and page["total"] == total
        assert page["cutoff_A"] == 4.0 and page["rows"] == mode["contacts"]
        keys = [(row["ligand_serial"], row["receptor_atom"]["site_index"]) for row in page["rows"]]
        assert keys == sorted(keys)
    rows = stored["modes"][0]["contacts"]
    total = len(rows)
    assert total >= 2
    default = _get(client, world, "results/contacts", handle=world["result"], mode=1).json()
    assert default["offset"] == 0 and default["limit"] == 100 and default["rows"] == rows[:100]
    last = _get(client, world, "results/contacts", handle=world["result"], mode=1, offset=total - 1, limit=1).json()
    assert last["rows"] == rows[-1:] and last["total"] == total
    tail = _get(client, world, "results/contacts", handle=world["result"], mode=1, offset=total - 1, limit=5).json()
    assert tail["rows"] == rows[-1:]
    for offset in (total, total + 10):
        assert _get(client, world, "results/contacts", handle=world["result"], mode=1,
                    offset=offset).json()["rows"] == []
    middle = _get(client, world, "results/contacts", handle=world["result"], mode=1, offset=1, limit=1).json()
    assert middle["rows"] == rows[1:2]
    for params in ({"limit": 0}, {"limit": 501}, {"offset": -1}, {"mode": 0}, {"mode": "x"}, {"mode": 21}):
        query = {"handle": world["result"], "mode": 1, **params}
        assert _get(client, world, "results/contacts", **query).status_code == 422, params
    assert _get(client, world, "results/contacts", handle=world["result"]).status_code == 422  # mode required
    beyond = _get(client, world, "results/contacts", handle=world["result"], mode=len(stored["modes"]) + 1)
    assert beyond.status_code == 404 and beyond.json()["detail"]["error"] == "not_found"


# ----------------------------------------------------------------- pose SDF downloads
def test_pose_sdf_downloads_are_the_stored_bytes(client, world):
    stored = world["stored"]
    stem = "protview-docking-" + world["result"].rsplit("/", 1)[-1][:12]
    for number, mode in enumerate(stored["modes"], start=1):
        response = _get(client, world, "results/pose_sdf", handle=world["result"], mode=number)
        assert response.status_code == 200
        assert response.content == mode["pose_sdf"].encode("utf-8")
        assert b"$$$$" not in response.content and response.content.splitlines()[0] == f"mode_{number}".encode()
        assert response.headers["content-type"].startswith(SDF_MEDIA)
        assert response.headers["content-disposition"] == f'attachment; filename="{stem}-mode_{number}.sdf"'
        assert response.headers["cache-control"] == "private, no-store"
    every = _get(client, world, "results/poses_sdf", handle=world["result"])
    assert every.status_code == 200
    assert every.headers["content-disposition"] == f'attachment; filename="{stem}-modes.sdf"'
    text = every.content.decode("utf-8")
    assert text.endswith("$$$$\n")
    records = text.split("$$$$\n")[:-1]
    assert len(records) == len(stored["modes"])
    for number, (record, mode) in enumerate(zip(records, stored["modes"], strict=True), start=1):
        expected = mode["pose_sdf"] if mode["pose_sdf"].endswith("\n") else mode["pose_sdf"] + "\n"
        assert record == expected and record.splitlines()[0] == f"mode_{number}"
    assert re.fullmatch(r"protview-docking-[0-9a-f]{12}", stem)
    for params in ({"mode": 0}, {"mode": "1x"}, {"mode": 1, "name": "evil.sdf"}):
        assert _get(client, world, "results/pose_sdf", handle=world["result"], **params).status_code == 422
    assert _get(client, world, "results/poses_sdf", handle=world["result"], mode=1).status_code == 422
    assert _get(client, world, "results/pose_sdf", handle=world["result"],
                mode=len(stored["modes"]) + 1).status_code == 404


# ----------------------------------------------------------------- tampered objects never read
def test_tampered_result_lists_invalid_and_refuses_reads(world, monkeypatch, tmp_path):
    """A copy of the run whose stored result bytes were edited in place (labeled fault injection)."""
    root = tmp_path / "runs"
    shutil.copytree(world["root"] / world["rid"], root / world["rid"])
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    rid, handle = world["rid"], world["result"]
    assert client.get(f"/runs/{rid}/docking/prerequisites").status_code == 200  # reopen before the edit
    path = root / rid / "objects" / f"{handle.rsplit('/', 1)[-1]}.json"
    content = json.loads(path.read_bytes())
    content["modes"][0]["score_kcal_mol"] = -99.0
    path.write_bytes(canonical_json(content))
    before = (root / rid / "events.jsonl").read_bytes()
    row = client.get(f"/runs/{rid}/docking/results").json()["rows"][0]
    assert row["handle"] == handle and row["valid"] is False and row["reason_code"] == "evidence_invalid"
    assert all(row[key] is None for key in ("job_id", "method", "mode", "ligand_source", "candidate_id",
                                            "receptor_handle", "seed", "box_source", "modes", "null_result"))
    for path_name, extra in (("results/detail", {}), ("results/contacts", {"mode": 1}),
                             ("results/pose_sdf", {"mode": 1}), ("results/poses_sdf", {})):
        response = client.get(f"/runs/{rid}/docking/{path_name}", params={"handle": handle, **extra})
        assert response.status_code == 422 and response.json()["detail"]["error"] == "method_evidence_invalid"
        assert "-99" not in response.text
    assert (root / rid / "events.jsonl").read_bytes() == before


# ----------------------------------------------------------------- isolation
def test_server_reads_never_import_rdkit_or_meeko():
    for name in ("docking_reads.py", "api/app.py"):
        tree = ast.parse((MW / name).read_text())
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert not any(module == top or module.startswith(top + ".") for module in imported
                       for top in FORBIDDEN_MODULES), name
    code = ("import sys; import mw.api.app, mw.docking_reads; "
            "print(sorted(m for m in sys.modules if m.split('.')[0] in ('rdkit', 'meeko', 'MDAnalysis')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                         cwd=str(MW.parent), check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"
    assert not any(name.split(".")[0] in FORBIDDEN_MODULES for name in sys.modules)
