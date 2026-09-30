"""M15 T7 read API: residue numbering capability, reference snapshot reads, PDB ID hint, numbering map list.

Reference data is the FIXTURE set built by ``reference_fixture_set.build_fixture_set`` under a temporary
``MW_REFERENCE_DIR``. The PDB file with a HEADER record is SYNTHETIC: it is written by ``_synthetic_header_pdb`` from the
committed derived fixture with one added HEADER line and is named ``*_fixture.pdb``. Every read route is checked to
write no event.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reference_fixture_set import FIXTURES as REF
from reference_fixture_set import build_fixture_set

from mw import reference_snapshots as rs

FIX = Path(__file__).resolve().parent / "fixtures"
CIF_1MQ4 = FIX / "public_1mq4.cif"
PDB_A200 = FIX / "structures_m15" / "derived_1mq4_a200_285_fixture.pdb"
CIF_MSE = FIX / "structures_m15" / "derived_1mq4_a288_360_mse_fixture.cif"
TOOL = "map_residue_numbering"


@pytest.fixture
def refroot(tmp_path, monkeypatch):
    root = tmp_path / "reference"
    root.mkdir()
    monkeypatch.setenv(rs.ENV_VAR, str(root))
    return root


@pytest.fixture
def client(tmp_path, monkeypatch):
    import mw.api.app as appmod
    monkeypatch.setattr(appmod, "RUNS_DIR", tmp_path / "runs")
    appmod.RUNS.clear()
    return TestClient(appmod.app, base_url="http://127.0.0.1")


def _new_run(client) -> str:
    return client.post("/runs", json={"goal": "numbering reads"}).json()["run_id"]


def _upload_and_load(client, rid: str, raw: bytes, filename: str) -> str:
    upload = client.post(f"/runs/{rid}/uploads", params={"filename": filename}, content=raw,
                         headers={"content-type": "application/octet-stream"})
    assert upload.status_code == 201, upload.text
    loaded = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure",
                                                         "args": {"source": upload.json()["upload_id"]}})
    assert loaded.status_code == 200, loaded.text
    return loaded.json()["handle"]["handle"]


def _prepare(client, rid: str, structure: str) -> str:
    prepared = client.post(f"/runs/{rid}/commands", json={"tool": "prepare_structure", "args": {
        "structure": structure, "altloc": "highest_occupancy", "waters": "strip_all", "hydrogens": "keep",
        "missing_residues": "leave_gaps", "symmetry_mates": "ignore"}})
    assert prepared.status_code == 200, prepared.text
    return prepared.json()["handle"]["handle"]


def _event_count(client, rid: str) -> int:
    return client.get(f"/runs/{rid}").json()["last_seq"]


def _synthetic_header_pdb(tmp_path: Path, idcode: str) -> bytes:
    """SYNTHETIC: the derived 1MQ4 A200-285 fixture with a HEADER record whose idcode (cols 63-66) is ``idcode``."""
    header = "HEADER    TRANSFERASE" + " " * 29 + "01-JAN-26" + "   " + idcode
    assert len(header) == 66 and header[62:66] == idcode
    raw = (header + "\n").encode() + PDB_A200.read_bytes()
    (tmp_path / f"synthetic_header_{idcode}_fixture.pdb").write_bytes(raw)
    return raw


# --- /capabilities ------------------------------------------------------------------------------------------------

def test_capability_three_states_and_templates_unaffected(client, refroot):
    missing = client.get("/capabilities").json()["methods"]
    numbering = missing["residue_numbering"]
    assert numbering == {"available": False, "reason_code": "not_installed", "reason": rs.REASONS["not_installed"],
                         "set_hash": None, "sources": []}
    templates_before = missing["analysis_workflows"]["templates"]

    set_hash = build_fixture_set(refroot)
    ready = client.get("/capabilities").json()["methods"]
    assert ready["residue_numbering"]["available"] is True
    assert ready["residue_numbering"]["reason_code"] is None and ready["residue_numbering"]["reason"] is None
    assert ready["residue_numbering"]["set_hash"] == set_hash
    assert [s["source"] for s in ready["residue_numbering"]["sources"]] == ["uniprot", "sifts", "klifs"]
    assert {s["license"] for s in ready["residue_numbering"]["sources"]} == {"CC-BY-4.0", "EMBL-EBI-terms",
                                                                              "none-stated"}
    assert ready["analysis_workflows"]["templates"] == templates_before

    entries = next(refroot.glob("sets/*/files/uniprot/*/entries.jsonl"))
    entries.write_bytes(entries.read_bytes() + b"\n")
    invalid = client.get("/capabilities").json()["methods"]
    assert invalid["residue_numbering"]["available"] is False
    assert invalid["residue_numbering"]["reason_code"] == "snapshot_invalid"
    assert invalid["residue_numbering"]["set_hash"] is None
    assert invalid["analysis_workflows"]["templates"] == templates_before


# --- /reference/snapshots -----------------------------------------------------------------------------------------

def test_reference_snapshots_available_and_unavailable(client, refroot):
    missing = client.get("/reference/snapshots")
    assert missing.status_code == 200
    assert missing.json() == {"schema": "reference_snapshots@1", "available": False, "reason_code": "not_installed",
                              "reason": rs.REASONS["not_installed"], "set_hash": None, "origin": None,
                              "imported_at": None, "kbase_repo": None, "sources": []}
    set_hash = build_fixture_set(refroot)
    body = client.get("/reference/snapshots").json()
    manifest = json.loads((refroot / "sets" / set_hash / "manifest.json").read_bytes())
    assert body["available"] is True and body["reason_code"] is None and body["set_hash"] == set_hash
    assert body["origin"] == "kbase_kinase processed snapshot"
    assert body["imported_at"] == manifest["imported_at"] and body["kbase_repo"] == manifest["kbase_repo"]
    assert body["sources"] == manifest["sources"]
    uniprot = body["sources"][0]
    assert uniprot["source"] == "uniprot" and uniprot["version_hint"] == "2026_03"
    assert uniprot["files"][0]["sha256"] and uniprot["files"][0]["bytes"] > 0 and uniprot["files"][0]["rows"] == 3
    (refroot / "active.json").write_bytes(b"{}")
    invalid = client.get("/reference/snapshots").json()
    assert invalid["available"] is False and invalid["reason_code"] == "snapshot_invalid" and invalid["sources"] == []


# --- /runs/{id}/reference/pdb_id_hint -----------------------------------------------------------------------------

def test_pdb_id_hint_sources_and_no_events(client, refroot, tmp_path):
    rid = _new_run(client)
    cif = _upload_and_load(client, rid, CIF_1MQ4.read_bytes(), "1mq4.cif")
    header = _upload_and_load(client, rid, _synthetic_header_pdb(tmp_path, "9xyz"), "header.pdb")
    plain = _upload_and_load(client, rid, PDB_A200.read_bytes(), "a200.pdb")
    derived_cif = _upload_and_load(client, rid, CIF_MSE.read_bytes(), "mse.cif")
    invalid_header = _upload_and_load(client, rid, _synthetic_header_pdb(tmp_path, "ABCD"), "bad.pdb")
    prepared = _prepare(client, rid, cif)
    before = _event_count(client, rid)

    def hint(handle):
        response = client.get(f"/runs/{rid}/reference/pdb_id_hint", params={"structure": handle})
        assert response.status_code == 200, response.text
        return response.json()

    assert hint(cif) == {"structure": cif, "structure_kind": "structure", "format": "cif",
                         "pdb_id": "1MQ4", "origin": "mmcif_entry_id"}
    assert hint(header) | {"structure": None} == {"structure": None, "structure_kind": "structure",
                                                  "format": "pdb", "pdb_id": "9XYZ", "origin": "pdb_header"}
    assert (hint(plain)["pdb_id"], hint(plain)["origin"]) == (None, None)
    assert (hint(derived_cif)["pdb_id"], hint(derived_cif)["origin"]) == (None, None)  # "1MQ4_DERIVED_..." id
    assert (hint(invalid_header)["pdb_id"], hint(invalid_header)["origin"]) == (None, None)
    traced = hint(prepared)
    assert traced["structure_kind"] == "prepared_structure"
    assert (traced["pdb_id"], traced["origin"]) == ("1MQ4", "mmcif_entry_id")

    coordinates = client.get(f"/runs/{rid}/objects/meta", params={"handle": prepared}).json()["summary"]["coordinates"]
    wrong_kind = client.get(f"/runs/{rid}/reference/pdb_id_hint", params={"structure": coordinates})
    assert wrong_kind.status_code == 422 and wrong_kind.json()["detail"]["error"] == "input_invalid"
    unknown = client.get(f"/runs/{rid}/reference/pdb_id_hint",
                         params={"structure": cif.rsplit("/", 1)[0] + "/" + "0" * 64})
    assert unknown.status_code == 404
    assert client.get(f"/runs/{rid}/reference/pdb_id_hint").status_code == 422
    assert _event_count(client, rid) == before


# --- /reference/sifts_chains --------------------------------------------------------------------------------------

def test_sifts_chains_prefill(client, refroot):
    unavailable = client.get("/reference/sifts_chains", params={"pdb_id": "1MQ4"})
    assert unavailable.status_code == 200
    assert unavailable.json() == {"schema": "reference_sifts_chains@1", "available": False,
                                  "reason_code": "not_installed", "reason": rs.REASONS["not_installed"],
                                  "set_hash": None, "pdb_id": "1MQ4", "chains": []}
    set_hash = build_fixture_set(refroot)
    body = client.get("/reference/sifts_chains", params={"pdb_id": "1mq4"}).json()
    assert body["available"] is True and body["set_hash"] == set_hash and body["pdb_id"] == "1MQ4"
    chain_a = next(c for c in body["chains"] if c["chain_auth"] == "A")
    assert chain_a == {"chain_auth": "A", "accessions": ["O14965"], "reason_code": None, "reason": None}
    assert client.get("/reference/sifts_chains", params={"pdb_id": "9ZZZ"}).json()["chains"] == []
    for bad in ("MQ41", "1MQ", "1MQ4X", "1-Q4"):
        response = client.get("/reference/sifts_chains", params={"pdb_id": bad})
        assert response.status_code == 422 and response.json()["detail"]["error"] == "input_invalid"
    assert client.get("/reference/sifts_chains").status_code == 422


def test_sifts_chains_reports_unusable_chain_reason(client, refroot):
    """SYNTHETIC variant: the 1MQ4 residue row's status becomes ``lookup_failed``."""
    rows = [json.loads(line) for line in (REF / "sifts/residues_fixture.jsonl").read_bytes().splitlines() if line]
    for row in rows:
        if row["pdb_id"].upper() == "1MQ4" and row["chain"] == "A":
            row["status"] = "lookup_failed"
            row["reason"] = "synthetic fixture"
    data = b"".join(json.dumps(row).encode() + b"\n" for row in rows)
    build_fixture_set(refroot, tag="failed", replace={("sifts", "residues.jsonl"): data})
    chain_a = next(c for c in client.get("/reference/sifts_chains", params={"pdb_id": "1MQ4"}).json()["chains"]
                   if c["chain_auth"] == "A")
    assert chain_a["accessions"] == [] and chain_a["reason_code"] == "sifts_chain_lookup_failed"
    assert chain_a["reason"]


# --- /reference/uniprot -------------------------------------------------------------------------------------------

def _synthetic_uniprot_with_failed_row() -> bytes:
    """SYNTHETIC: entries_fixture.jsonl plus one ``lookup_failed`` row (accession P99999, no data)."""
    raw = (REF / "uniprot/entries_fixture.jsonl").read_bytes()
    failed = {"id": "P99999", "status": "lookup_failed", "reason": "synthetic fixture AURKA-like"}
    return raw + json.dumps(failed).encode() + b"\n"


def test_uniprot_search_fields_paging_and_no_sequence(client, refroot):
    unavailable = client.get("/reference/uniprot", params={"query": "aurk"}).json()
    assert unavailable["available"] is False and unavailable["entries"] == [] and unavailable["total"] == 0
    build_fixture_set(refroot, tag="search",
                      replace={("uniprot", "entries.jsonl"): _synthetic_uniprot_with_failed_row()})

    def search(**params):
        response = client.get("/reference/uniprot", params=params)
        assert response.status_code == 200, response.text
        assert "sequence" not in response.text.lower().replace("sequence_length", "")
        return response.json()

    aurka = search(query="aurk")
    assert aurka["total"] == 1 and aurka["offset"] == 0 and aurka["limit"] == 20
    assert aurka["entries"] == [{"accession": "O14965", "entry_name": "AURKA_HUMAN", "gene": "AURKA",
                                 "protein_name": "Aurora kinase A", "organism": "Homo sapiens",
                                 "sequence_length": 403}]
    assert [e["accession"] for e in search(query="o14965")["entries"]] == ["O14965"]
    assert [e["accession"] for e in search(query="kcc1d_")["entries"]] == ["Q8IU85"]
    assert [e["accession"] for e in search(query="CALMODULIN")["entries"]] == ["Q8IU85"]
    assert search(query="P99999")["total"] == 0  # lookup_failed rows are never offered
    everything = search()
    assert everything["total"] == 3
    page = search(query="", offset=1, limit=1)
    assert page["total"] == 3 and page["entries"] == everything["entries"][1:2]
    assert search(query="kinase", offset=10)["entries"] == []
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"query": "x" * 101}):
        assert client.get("/reference/uniprot", params=params).status_code == 422


# --- /runs/{id}/numbering_maps and object rows ----------------------------------------------------------------------

def test_numbering_maps_list_stale_flag_and_row_paging(client, refroot):
    first_hash = build_fixture_set(refroot)
    rid = _new_run(client)
    structure = _upload_and_load(client, rid, CIF_1MQ4.read_bytes(), "1mq4.cif")
    assert client.get(f"/runs/{rid}/numbering_maps").json() == {
        "schema": "residue_numbering_map_list@1", "active_set_hash": first_hash, "snapshot_available": True,
        "total": 0, "offset": 0, "limit": 50, "rows": []}
    made = client.post(f"/runs/{rid}/commands", json={"tool": TOOL, "args": {
        "structure": structure, "pdb_id": "1mq4", "chains": [{"chain_auth": "A"}]}})
    assert made.status_code == 200, made.text
    handle = made.json()["handle"]["handle"]
    prepared = _prepare(client, rid, structure)
    second = client.post(f"/runs/{rid}/commands", json={"tool": TOOL, "args": {
        "structure": prepared, "pdb_id": None, "chains": [{"chain_auth": "A", "uniprot_accession": "O14965"}]}})
    assert second.status_code == 200, second.text
    second_handle = second.json()["handle"]["handle"]
    before = _event_count(client, rid)

    listed = client.get(f"/runs/{rid}/numbering_maps").json()
    assert listed["total"] == 2 and [r["handle"] for r in listed["rows"]] == [second_handle, handle]  # newest first
    row = listed["rows"][1]
    content = client.get(f"/runs/{rid}/objects/meta", params={"handle": handle}).json()["summary"]
    assert row["structure"] == structure and row["structure_kind"] == "structure" and row["pdb_id"] == "1MQ4"
    assert row["chains"] == ["A"] and row["set_hash"] == first_hash and row["stale_snapshot"] is False
    assert [c["chain_auth"] for c in row["chain_details"]] == ["A"] and "counts" in row["chain_details"][0]
    assert row["counts"] == {k: content[k] for k in ("mapped", "unmapped", "conflict")}
    assert row["row_count"] == sum(row["counts"].values()) and row["null_result"] is False
    assert row["created_seq"] > 0 and listed["rows"][0]["created_seq"] > row["created_seq"]
    assert listed["rows"][0]["structure_kind"] == "prepared_structure" and listed["rows"][0]["pdb_id"] is None
    paged = client.get(f"/runs/{rid}/numbering_maps", params={"offset": 1, "limit": 1}).json()
    assert paged["total"] == 2 and [r["handle"] for r in paged["rows"]] == [handle]
    assert client.get(f"/runs/{rid}/numbering_maps", params={"limit": 101}).status_code == 422

    # Full rows through the generic object route, paged.
    rows = client.get(f"/runs/{rid}/objects", params={"handle": handle, "offset": 5, "limit": 3})
    assert rows.status_code == 200, rows.text
    body = rows.json()
    assert body["total"] == row["row_count"] and body["offset"] == 5 and len(body["rows"]) == 3
    assert body["meta"]["kind"] == "residue_numbering_map"
    assert set(body["rows"][0]) >= {"residue", "status", "uniprot_position", "sifts", "alignment"}
    projected = client.get(f"/runs/{rid}/objects", params={"handle": handle, "columns": "residue,status",
                                                            "limit": 2}).json()
    assert projected["rows"] == [{"residue": r["residue"], "status": r["status"]}
                                 for r in client.get(f"/runs/{rid}/objects",
                                                     params={"handle": handle, "limit": 2}).json()["rows"]]
    bad_column = client.get(f"/runs/{rid}/objects", params={"handle": handle, "columns": "sequence"})
    assert bad_column.status_code == 422

    # Swap the active set: every existing map is now based on an earlier snapshot.
    new_hash = build_fixture_set(refroot, tag="swapped")
    assert new_hash != first_hash
    swapped = client.get(f"/runs/{rid}/numbering_maps").json()
    assert swapped["active_set_hash"] == new_hash
    assert [r["stale_snapshot"] for r in swapped["rows"]] == [True, True]
    (refroot / "active.json").unlink()
    gone = client.get(f"/runs/{rid}/numbering_maps").json()
    assert gone["snapshot_available"] is False and gone["active_set_hash"] is None
    assert [r["stale_snapshot"] for r in gone["rows"]] == [True, True]
    assert _event_count(client, rid) == before


def test_reference_reads_do_not_touch_runs(client, refroot):
    build_fixture_set(refroot)
    rid = _new_run(client)
    before = _event_count(client, rid)
    for path, params in (("/reference/snapshots", {}), ("/reference/sifts_chains", {"pdb_id": "1MQ4"}),
                         ("/reference/uniprot", {"query": "kinase"}), ("/capabilities", {}),
                         (f"/runs/{rid}/numbering_maps", {})):
        assert client.get(path, params=params).status_code == 200
    assert _event_count(client, rid) == before


def test_run_routes_reject_bad_run(client, refroot):
    assert client.get("/runs/run_" + "0" * 32 + "/numbering_maps").status_code == 404
    assert client.get("/runs/_bad/reference/pdb_id_hint", params={"structure": "x"}).status_code == 400
