"""M1 HTTP contracts exercised with actual structure bytes."""
from __future__ import annotations

import hashlib
import math
import shutil
from pathlib import Path

import gemmi
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api(tmp_path, monkeypatch):
    import mw.api.app as appmod
    monkeypatch.setattr(appmod, "RUNS_DIR", tmp_path / "runs")
    appmod.RUNS.clear()
    return TestClient(appmod.app, base_url="http://127.0.0.1"), appmod


def new_run(client):
    response = client.post("/runs", json={"goal": "inspect locally"})
    assert response.status_code == 201
    return response.json()["run_id"]


def upload(client, rid, raw, name="fixture.pdb"):
    return client.post(f"/runs/{rid}/uploads", params={"filename": name},
                       content=raw, headers={"content-type": "application/octet-stream"})


def call(client, rid, tool, args):
    return client.post(f"/runs/{rid}/commands", json={"tool": tool, "args": args})


def imported(client, rid, raw, name="fixture.pdb"):
    received = upload(client, rid, raw, name)
    assert received.status_code == 201, received.text
    result = call(client, rid, "load_structure", {"source": received.json()["upload_id"]})
    assert result.status_code == 200, result.text
    return result.json()["handle"]


def prepared(client, rid, raw, name="fixture.pdb"):
    source = imported(client, rid, raw, name)
    result = call(client, rid, "prepare_structure", {"structure": source["handle"]})
    assert result.status_code == 200, result.text
    return source, result.json()["handle"]


def _tiny(distance: float) -> bytes:
    return (f"ATOM      1  N   ALA A 100A      {0.0:8.3f}{0.0:8.3f}{0.0:8.3f}"
            f"{1.0:6.2f}{20.0:6.2f}           N\n"
            f"HETATM    2  O1  LIG B 301      {distance:8.3f}{0.0:8.3f}{0.0:8.3f}"
            f"{1.0:6.2f}{20.0:6.2f}           O\nEND\n").encode()


def test_upload_run_commands_bytes_and_reopen(api, pdb_path):
    client, appmod = api
    rid = new_run(client)
    raw = Path(pdb_path).read_bytes()
    source, prep = prepared(client, rid, raw)
    result = call(client, rid, "compute_interactions", {"structure": prep["handle"]})
    assert result.status_code == 200
    interaction = result.json()["handle"]
    assert interaction["kind"] == "interaction_set"
    assert interaction["summary"]["n_edges"] > 0
    assert interaction["preview"] and len(interaction["preview"]) <= 5
    rows = client.get(f"/runs/{rid}/objects", params={"handle": interaction["handle"],
                      "columns": "residue,distance_A", "offset": 1, "limit": 2}).json()
    assert rows["total"] == interaction["summary"]["n_edges"]
    assert len(rows["rows"]) == 2 and set(rows["rows"][0]) == {"residue", "distance_A"}
    assert rows["meta"]["null_result"] is False and "path" not in rows["meta"]
    assert client.get(f"/runs/{rid}/objects", params={"handle": interaction["handle"],
                      "columns": "made_up"}).status_code == 422
    data = client.get(f"/runs/{rid}/structures/bytes", params={"handle": prep["handle"]})
    assert data.status_code == 200 and data.content
    assert gemmi.read_pdb_string(data.text)[0].count_atom_sites() > 0
    residues = client.get(f"/runs/{rid}/structures/residues", params={"handle": prep["handle"]}).json()
    assert residues["ligands"][0]["chain_auth"] == "B"
    asp = next(item for item in residues["residues"] if item["resname"] == "ASP")
    assert asp["seq_auth"] == 100 and asp["icode"] == "A" and asp["model_number"] == 1
    events = client.get(f"/runs/{rid}/events", params={"after": 0}).json()
    assert any(event["type"] == "upload_received" for event in events)
    assert any(event["type"] == "tool_called" and event["decided_by"] == "human" for event in events)
    assert client.get(f"/runs/{rid}/events", params={"after": events[-1]["seq"]}).json() == []
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 0
    assert any(entry["run_id"] == rid for entry in client.get("/runs").json())
    shutil.rmtree(appmod.RUNS[rid].run_dir / "uploads")
    appmod.RUNS.clear()
    assert client.get(f"/runs/{rid}").json()["goal"] == "inspect locally"
    assert client.get(f"/runs/{rid}/objects/meta",
                      params={"handle": interaction["handle"]}).json()["summary"] == interaction["summary"]
    assert client.get(f"/runs/{rid}/structures/bytes", params={"handle": source["handle"]}).status_code == 200
    assert client.get(f"/runs/{rid}/structures/bytes", params={"handle": prep["handle"]}).content == data.content


def test_reopened_cache_reads_preserve_physical_lineage_with_real_bytes(api, pdb_path):
    client, appmod = api
    rid = new_run(client)
    token = upload(client, rid, Path(pdb_path).read_bytes()).json()["upload_id"]
    loaded = call(client, rid, "load_structure", {"source": token}).json()["handle"]
    prep_args = {"structure": loaded["handle"]}
    prepared_handle = call(client, rid, "prepare_structure", prep_args).json()["handle"]
    interaction_args = {"structure": prepared_handle["handle"]}
    interaction = call(client, rid, "compute_interactions", interaction_args).json()["handle"]
    original = list(appmod.RUNS[rid].events.read())
    physical = {event["tool"]: event["call_id"] for event in original
                if event["type"] == "tool_called"}
    appmod.RUNS.clear()
    for tool, args, expected in (
        ("load_structure", {"source": token}, loaded),
        ("prepare_structure", prep_args, prepared_handle),
        ("compute_interactions", interaction_args, interaction),
    ):
        reply = call(client, rid, tool, args)
        assert reply.status_code == 200 and reply.json()["handle"]["handle"] == expected["handle"]
    events = client.get(f"/runs/{rid}/events", params={"limit": 500}).json()
    reads = [event for event in events if event["type"] == "cache_hit"]
    assert len(reads) == 3
    assert len({event["observation_id"] for event in reads}) == 3
    assert [(event["tool"], event["source_call_id"]) for event in reads] == list(physical.items())
    assert reads[1]["args"]["structure"] == loaded["handle"]
    assert reads[2]["args"]["structure"] == prepared_handle["handle"]
    assert all("duration_s" not in event and "cached" not in event for event in reads)
    assert sum(event["type"] == "tool_called" for event in events) == 3


def test_geometry_changes_with_coordinates_and_matches_distance(api):
    client, _ = api
    rid = new_run(client)
    _, near = prepared(client, rid, _tiny(3.5))
    first = call(client, rid, "compute_interactions", {"structure": near["handle"], "cutoff_A": 4.0})
    assert first.status_code == 200, first.text
    rows = client.get(f"/runs/{rid}/objects", params={"handle": first.json()["handle"]["handle"]}).json()["rows"]
    assert len(rows) == 1 and math.isclose(rows[0]["distance_A"], 3.5)
    assert rows[0]["type"] == "polar_contact" and rows[0]["unit"] == "angstrom"
    _, far = prepared(client, rid, _tiny(4.5))
    second = call(client, rid, "compute_interactions", {"structure": far["handle"], "cutoff_A": 4.0})
    assert second.status_code == 200
    assert second.json()["handle"]["null_result"] is True
    assert second.json()["handle"]["summary"]["n_edges"] == 0


def test_interaction_identity_includes_cutoff_input_and_empty_rows(api):
    client, appmod = api
    rid = new_run(client)
    source, prep = prepared(client, rid, _tiny(3.5))
    handles = {}
    for cutoff in (4.0, 5.0, 2.5, 3.0):
        response = call(client, rid, "compute_interactions", {"structure": prep["handle"], "cutoff_A": cutoff})
        assert response.status_code == 200, response.text
        handles[cutoff] = response.json()["handle"]
    assert handles[4.0]["handle"] != handles[5.0]["handle"]
    assert handles[2.5]["handle"] != handles[3.0]["handle"]
    assert handles[2.5]["null_result"] and handles[3.0]["null_result"]
    first = appmod.RUNS[rid].store.load(handles[4.0]["handle"])
    second = appmod.RUNS[rid].store.load(handles[5.0]["handle"])
    assert first["rows"] == second["rows"]
    assert first["parameters"]["cutoff_A"] == 4.0 and second["parameters"]["cutoff_A"] == 5.0
    stripped = call(client, rid, "prepare_structure",
                    {"structure": source["handle"], "waters": "strip_all"}).json()["handle"]
    assert stripped["handle"] != prep["handle"]
    same_rows = call(client, rid, "compute_interactions",
                     {"structure": stripped["handle"], "cutoff_A": 4.0}).json()["handle"]
    assert same_rows["handle"] != handles[4.0]["handle"]
    assert appmod.RUNS[rid].store.load(same_rows["handle"])["rows"] == first["rows"]
    _, other = prepared(client, rid, _tiny(9.0))
    empty = call(client, rid, "compute_interactions", {"structure": other["handle"], "cutoff_A": 3.0})
    assert empty.status_code == 200
    assert empty.json()["handle"]["handle"] != handles[3.0]["handle"]
    assert appmod.RUNS[rid].store.load(empty.json()["handle"]["handle"])["structure"] == other["handle"]
    compact = call(client, rid, "compile_state", {"inputs": [handles[4.0]["handle"]]})
    assert compact.status_code == 200
    state = appmod.RUNS[rid].store.load(compact.json()["handle"]["handle"])
    assert state["items"][0]["preview"] == first["rows"][:5]


def test_duplicate_ligand_requires_explicit_instance(api, pdb_path):
    client, _ = api
    raw = Path(pdb_path).read_text()
    added = "HETATM   21  O1  LIG D 302      30.000  30.000  30.000  1.00 20.00           O\n"
    rid = new_run(client)
    _, prep = prepared(client, rid, raw.replace("END\n", added + "END\n").encode())
    ligands = client.get(f"/runs/{rid}/structures/residues",
                         params={"handle": prep["handle"]}).json()["ligands"]
    assert len(ligands) == 2 and {x["chain_auth"] for x in ligands} == {"B", "D"}
    missing = call(client, rid, "compute_interactions", {"structure": prep["handle"]})
    assert missing.status_code == 422 and "ambiguous" in missing.json()["message"]
    selected = {}
    for ligand in ligands:
        result = call(client, rid, "compute_interactions", {"structure": prep["handle"], "ligand": ligand})
        assert result.status_code == 200, result.text
        selected[ligand["chain_auth"]] = result.json()["handle"]
    assert selected["B"]["summary"]["n_edges"] > 0
    assert selected["D"]["null_result"] is True
    assert selected["B"]["handle"] != selected["D"]["handle"]
    invalid = call(client, rid, "compute_interactions",
                   {"structure": prep["handle"], "ligand": {**ligands[0], "seq_auth": 999}})
    assert invalid.status_code == 422 and invalid.json()["error"] == "input_invalid"


def test_mmcif_identity_and_bytes(api):
    client, _ = api
    raw = b"""data_test
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.B_iso_or_equiv
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_atom_id
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA . ALA L 1 97 A 0 0 0 1 20 100 ALA X CA 1
HETATM 2 O O1 . LIG M 2 . ? 2 0 0 1 20 301 LIG Y O1 1
"""
    rid = new_run(client)
    _, prep = prepared(client, rid, raw, "fixture.cif")
    info = client.get(f"/runs/{rid}/structures/residues", params={"handle": prep["handle"]}).json()
    protein = info["residues"][0]
    ligand = info["ligands"][0]
    assert (protein["chain_auth"], protein["chain_label"], protein["seq_auth"],
            protein["seq_label"], protein["icode"]) == ("X", "L", 100, 97, "A")
    assert ligand["chain_auth"] == "Y" and ligand["chain_label"] == "M" and ligand["seq_label"] is None
    result = call(client, rid, "compute_interactions", {"structure": prep["handle"], "ligand": ligand})
    assert result.status_code == 200, result.text
    data = client.get(f"/runs/{rid}/structures/bytes", params={"handle": prep["handle"]})
    assert data.status_code == 200 and data.headers["x-structure-format"] == "cif"
    st = gemmi.make_structure_from_block(gemmi.cif.read_string(data.text).sole_block())
    assert st[0][0][0].subchain == "L"


def test_invalid_upload_command_handle_and_run(api, pdb_path, monkeypatch):
    client, appmod = api
    rid = new_run(client)
    raw = Path(pdb_path).read_bytes()
    other = new_run(client)
    token = upload(client, rid, raw).json()["upload_id"]
    for source in (pdb_path, "../etc/passwd", "/etc/passwd", "pdb:1HSG",
                   token.replace(rid, other)):
        response = call(client, other, "load_structure", {"source": source})
        assert response.status_code == 422 and response.json()["error"] == "input_invalid"
    assert upload(client, rid, raw, "wrong.cif").status_code == 422
    assert upload(client, rid, b"invalid", "bad.pdb").status_code == 422
    assert upload(client, rid, raw, "bad.xyz").status_code == 422
    monkeypatch.setattr(appmod, "MAX_UPLOAD_BYTES", 10)
    assert upload(client, rid, raw).status_code == 413
    monkeypatch.setattr(appmod, "MAX_UPLOAD_BYTES", 25 * 1024 * 1024)
    source = call(client, rid, "load_structure", {"source": token}).json()["handle"]
    assert call(client, rid, "unknown_tool", {}).status_code == 422
    assert call(client, other, "prepare_structure", {"structure": source["handle"]}).status_code == 422
    assert call(client, rid, "compute_interactions", {"structure": source["handle"]}).status_code == 412
    assert call(client, rid, "prepare_structure",
                {"structure": source["handle"], "waters": "model"}).status_code == 422
    assert call(client, rid, "compile_state", {"inputs": source["handle"]}).status_code == 422
    assert client.get(f"/runs/{other}/objects/meta", params={"handle": source["handle"]}).status_code == 404
    assert client.get(f"/runs/{rid}/structures/bytes", params={"handle": source["summary"]["source_handle"]}).status_code == 422
    assert client.get(f"/runs/{rid}/objects", params={"handle": source["handle"]}).status_code == 422
    assert client.get(f"/runs/{rid}/objects", params={"handle": source["handle"], "limit": 101}).status_code == 422
    assert client.get("/runs/..").status_code in {400, 404}
    assert client.get("/runs/not_there").status_code == 404
    (appmod.RUNS_DIR / "linked_run").symlink_to(appmod.RUNS_DIR.parent, target_is_directory=True)
    assert client.get("/runs/linked_run").status_code == 400
    assert client.get("/capabilities").json()["mode"] == "local_only"
    assert {tool["name"] for tool in client.get("/tools", params={"levels": "L1,L2,L3,L4,L5"}).json()} == {
            "load_structure", "prepare_structure", "compute_interactions", "compute_interface_sasa",
            "openmm_protein_minimize", "measure_distance", "align_structures", "compile_state",
            "map_residue_numbering", "annotate_reference_sites"}


def test_upload_parent_symlink_never_reads_or_writes_outside(api, pdb_path, tmp_path):
    client, appmod = api
    rid = new_run(client)
    raw = Path(pdb_path).read_bytes()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"unchanged")
    name = f"{hashlib.sha256(raw).hexdigest()}.pdb"
    (outside / name).write_bytes(raw)
    before = {p.name: p.read_bytes() for p in outside.iterdir()}
    (appmod.RUNS[rid].run_dir / "uploads").symlink_to(outside, target_is_directory=True)
    rejected = upload(client, rid, raw)
    assert rejected.status_code == 422 and rejected.json()["detail"]["error"] == "input_invalid"
    token = f"upload://{rid}/{name}"
    rejected = call(client, rid, "load_structure", {"source": token})
    assert rejected.status_code == 422 and rejected.json()["error"] == "input_invalid"
    assert {p.name: p.read_bytes() for p in outside.iterdir()} == before


def test_upload_file_symlink_rejected_and_identical_reuse_preserved(api, pdb_path, tmp_path):
    client, appmod = api
    rid = new_run(client)
    raw = Path(pdb_path).read_bytes()
    first = upload(client, rid, raw)
    assert first.status_code == 201
    assert upload(client, rid, raw).json()["upload_id"] == first.json()["upload_id"]
    source = call(client, rid, "load_structure", {"source": first.json()["upload_id"]})
    assert source.status_code == 200
    repeated = call(client, rid, "load_structure", {"source": first.json()["upload_id"]})
    assert repeated.status_code == 200 and repeated.json()["handle"]["handle"] == source.json()["handle"]["handle"]
    assert sum(e["type"] == "tool_called" and e["tool"] == "load_structure"
               for e in appmod.RUNS[rid].events.read()) == 1
    outside = tmp_path / "outside.pdb"
    outside.write_bytes(raw)
    name = first.json()["upload_id"].rsplit("/", 1)[-1]
    path = appmod.RUNS[rid].run_dir / "uploads" / name
    path.unlink()
    path.symlink_to(outside)
    assert upload(client, rid, raw).status_code == 422
    rejected = call(client, rid, "load_structure", {"source": first.json()["upload_id"]})
    assert rejected.status_code == 422 and rejected.json()["error"] == "input_invalid"
    assert outside.read_bytes() == raw


def test_handle_cardinality_rejected_before_tool_invocation(api, pdb_path):
    client, appmod = api
    rid = new_run(client)
    source = imported(client, rid, Path(pdb_path).read_bytes())
    wrong_scalar = call(client, rid, "prepare_structure", {"structure": [source["handle"]]})
    wrong_collection = call(client, rid, "compile_state", {"inputs": source["handle"]})
    assert wrong_scalar.status_code == 422 and wrong_scalar.json()["error"] == "input_invalid"
    assert wrong_collection.status_code == 422 and wrong_collection.json()["error"] == "input_invalid"
    assert not any(e["type"] == "tool_called" and e["tool"] in {"prepare_structure", "compile_state"}
                   for e in appmod.RUNS[rid].events.read())
    accepted = call(client, rid, "compile_state", {"inputs": [source["handle"]]})
    assert accepted.status_code == 200 and accepted.json()["handle"]["kind"] == "compact_state"
