"""M17 T2 building-block imports: light server checks and the shared chemical import route (spec 3.1)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mw.api import app as api_module
from mw.chemical_inputs import _bytes, import_raw
from mw.core.errors import FailureClass, ToolFailure
from mw.ligand_inputs import check_block_bytes, smiles_record_lines, split_sdf_records
from mw.workspace import new_run

FIX = Path(__file__).parent / "fixtures" / "ligand"
CHEM = Path(__file__).parent / "fixtures" / "chemical"
OCTET = {"content-type": "application/octet-stream"}
TINY_RECORD = "t\n  SYNTHETIC-FIXTURE\n\n  1  0  0  0  0  0  0  0  0  0999 V2000\n" \
              "    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\nM  END\n$$$$\n"


def _invalid(fn, *args):
    with pytest.raises(ToolFailure) as caught:
        fn(*args)
    assert caught.value.cls is FailureClass.input_invalid
    return caught.value


# ---------------------------------------------------------------- pure checks


def test_fixture_libraries_pass_light_checks_with_expected_record_counts():
    sdf = (FIX / "synthetic-blocks.sdf").read_bytes()
    smi = (FIX / "synthetic-blocks.smi").read_bytes()
    assert check_block_bytes("building_blocks_sdf", "synthetic-blocks.sdf", sdf) == "sdf_multi"
    assert check_block_bytes("building_blocks_smiles", "synthetic-blocks.smi", smi) == "smiles_list"
    assert check_block_bytes("building_blocks_smiles", "library.TXT", smi) == "smiles_list"
    # Record ordinals: SDF records split on $$$$ lines; SMILES skip blank and '#' lines (spec 3.3).
    assert len(split_sdf_records(sdf.decode())) == 10
    lines = smiles_record_lines(smi.decode())
    assert len(lines) == 18
    assert lines[14] == "*O"            # ordinal 15 -> block_15 in the hand oracle (file line 18)
    assert lines[0] == "*C methyl"


def test_sdf_record_split_counts_zero_atom_record_and_trailing_text():
    assert len(split_sdf_records(TINY_RECORD * 3)) == 3
    assert len(split_sdf_records(TINY_RECORD.removesuffix("$$$$\n"))) == 1   # last record without delimiter
    assert len(split_sdf_records(TINY_RECORD + "\n  \n")) == 1               # whitespace after last $$$$
    assert len(split_sdf_records(TINY_RECORD.replace("\n", "\r\n") * 2)) == 2


@pytest.mark.parametrize("kind,filename", [
    ("building_blocks_sdf", "blocks.smi"), ("building_blocks_sdf", "blocks.txt"),
    ("building_blocks_smiles", "blocks.sdf"), ("building_blocks_smiles", "blocks"),
    ("building_blocks_sdf", "dir/blocks.sdf"), ("building_blocks_sdf", ""),
])
def test_extension_mismatch_rejected(kind, filename):
    _invalid(check_block_bytes, kind, filename, TINY_RECORD.encode())


@pytest.mark.parametrize("raw", [b"", b"   \n", b"\n$$$$\n\n", b"*C\x00 methyl\n", b"\xff\xfe*C\n"])
def test_empty_nul_and_non_utf8_sdf_rejected(raw):
    _invalid(check_block_bytes, "building_blocks_sdf", "b.sdf", raw)


@pytest.mark.parametrize("raw", [b"", b"\n\n  \n", b"# only comments\n#\n", b"*C\x00x\n", b"\xc3(\n"])
def test_empty_nul_and_non_utf8_smiles_rejected(raw):
    _invalid(check_block_bytes, "building_blocks_smiles", "b.smi", raw)


def test_sdf_record_cap_1000_inclusive():
    assert check_block_bytes("building_blocks_sdf", "b.sdf", (TINY_RECORD * 1000).encode()) == "sdf_multi"
    error = _invalid(check_block_bytes, "building_blocks_sdf", "b.sdf", (TINY_RECORD * 1001).encode())
    assert "1,000" in error.message or "1000" in error.message


def test_smiles_list_has_no_import_record_cap():
    # block_limit_reached is decided by the worker (spec 3.3); import only checks size and lines.
    assert check_block_bytes("building_blocks_smiles", "b.smi", b"*C\n" * 1500) == "smiles_list"


def test_size_cap_10_mib():
    limit = 10 * 1024 * 1024
    line = b"*C x\n"
    at_cap = line * (limit // len(line)) + b"C" * (limit % len(line))
    assert len(at_cap) == limit
    assert check_block_bytes("building_blocks_smiles", "b.smi", at_cap) == "smiles_list"
    _invalid(check_block_bytes, "building_blocks_smiles", "b.smi", at_cap + b"\n")


def test_unknown_kind_rejected():
    _invalid(check_block_bytes, "ligand_sdf", "b.sdf", TINY_RECORD.encode())
    _invalid(check_block_bytes, "building_blocks", "b.sdf", TINY_RECORD.encode())


# ---------------------------------------------------------------- storage


def test_import_raw_stores_new_kinds_with_input_format_and_kind_conflict_guard(tmp_path):
    run = new_run(tmp_path, dry_run=False, run_id="run_ligand_import")
    sdf = (FIX / "synthetic-blocks.sdf").read_bytes()
    smi = (FIX / "synthetic-blocks.smi").read_bytes()
    first = import_raw(run.store, "building_blocks_sdf", "synthetic-blocks.sdf", sdf)
    assert first["kind"] == "building_blocks_sdf" and first["format"] == "sdf_multi"
    assert first["schema"] == "chemical_raw_input@1" and first["size"] == len(sdf)
    meta = run.store.meta(first["handle"])
    assert meta["kind"] == "chemical_raw_input" and meta["schema"] == "chemical_raw_input@1"
    assert meta["summary"]["input_kind"] == "building_blocks_sdf"
    assert meta["summary"]["input_format"] == "sdf_multi"
    assert run.store.load(first["handle"]) == sdf
    assert _bytes(run.store, first["handle"], "building_blocks_sdf") == (sdf, "sdf_multi")
    _invalid(_bytes, run.store, first["handle"], "ligand_sdf")
    events_before = len(list(run.events.read()))
    again = import_raw(run.store, "building_blocks_sdf", "renamed.sdf", sdf)
    assert again == first and len(list(run.events.read())) == events_before
    smiles = import_raw(run.store, "building_blocks_smiles", "blocks.txt", smi)
    assert smiles["format"] == "smiles_list"
    assert import_raw(run.store, "building_blocks_smiles", "blocks.smi", smi) == smiles
    # Same bytes under another kind are refused in both directions (existing _bytes/import rule).
    parent = (FIX / "synthetic-parent-methacetin-no-h.sdf").read_bytes()
    import_raw(run.store, "ligand_sdf", "parent.sdf", parent)
    _invalid(import_raw, run.store, "building_blocks_sdf", "parent.sdf", parent)
    other = (FIX / "synthetic-parent-methacetin-explicit-h.sdf").read_bytes()
    import_raw(run.store, "building_blocks_sdf", "one-block.sdf", other)
    _invalid(import_raw, run.store, "ligand_sdf", "parent-h.sdf", other)


def test_m11_kinds_unchanged_for_block_files(tmp_path):
    run = new_run(tmp_path, dry_run=False, run_id="run_ligand_m11")
    # The M11 parent kind keeps its own element check: an SDF '*' marker is refused there.
    _invalid(import_raw, run.store, "ligand_sdf", "blocks.sdf", (FIX / "synthetic-blocks.sdf").read_bytes())
    # And the M11 kind still accepts its own fixture.
    parent = import_raw(run.store, "ligand_sdf", "parent.sdf",
                        (FIX / "synthetic-parent-methacetin-explicit-h.sdf").read_bytes())
    assert parent["kind"] == "ligand_sdf" and parent["format"] == "sdf"


# ---------------------------------------------------------------- route


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path)
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _post(client, rid, kind, filename, raw):
    return client.post(f"/runs/{rid}/chemical/imports", params={"kind": kind, "filename": filename},
                       content=raw, headers=OCTET)


def test_route_accepts_new_kinds_and_rejects_bad_inputs_without_objects(client):
    rid = client.post("/runs", json={"goal": "ligand block imports", "dry_run": False}).json()["run_id"]
    run = api_module._run(rid)
    sdf = (FIX / "synthetic-blocks.sdf").read_bytes()
    smi = (FIX / "synthetic-blocks.smi").read_bytes()
    created = _post(client, rid, "building_blocks_sdf", "synthetic-blocks.sdf", sdf)
    assert created.status_code == 201, created.text
    assert created.json()["kind"] == "building_blocks_sdf" and created.json()["format"] == "sdf_multi"
    created = _post(client, rid, "building_blocks_smiles", "synthetic-blocks.smi", smi)
    assert created.status_code == 201 and created.json()["format"] == "smiles_list"
    parent = (FIX / "synthetic-parent-methacetin-no-h.sdf").read_bytes()
    assert _post(client, rid, "ligand_sdf", "parent.sdf", parent).status_code == 201
    count = sum(e["type"] == "object_created" for e in run.events.read())
    bad = [
        _post(client, rid, "building_blocks_sdf", "blocks.smi", sdf),             # extension
        _post(client, rid, "building_blocks_smiles", "blocks.sdf", smi),          # extension
        _post(client, rid, "building_blocks_smiles", "blocks.smi", b"\n# x\n"),   # no records
        _post(client, rid, "building_blocks_sdf", "blocks.sdf", (TINY_RECORD * 1001).encode()),
        _post(client, rid, "building_blocks_smiles", "blocks.smi", b"*C\x00\n"),  # NUL
        _post(client, rid, "building_blocks_sdf", "parent.sdf", parent),           # kind/bytes conflict
        _post(client, rid, "ligand_sdf", "blocks.sdf", sdf),                       # kind/bytes conflict
    ]
    assert [r.status_code for r in bad] == [422] * 7
    empty = _post(client, rid, "building_blocks_sdf", "blocks.sdf", b"")
    assert empty.status_code == 422
    unknown_kind = _post(client, rid, "building_blocks", "blocks.sdf", sdf)
    assert unknown_kind.status_code == 422
    oversized = _post(client, rid, "building_blocks_smiles", "big.smi", b"C" * (10 * 1024 * 1024 + 1))
    assert oversized.status_code == 413
    assert sum(e["type"] == "object_created" for e in run.events.read()) == count


def test_route_existing_m11_prerequisites_counts_stay_m11_kinds(client):
    rid = client.post("/runs", json={"goal": "prerequisites untouched", "dry_run": False}).json()["run_id"]
    assert _post(client, rid, "building_blocks_smiles", "b.smi", b"*C methyl\n").status_code == 201
    body = client.get(f"/runs/{rid}/chemical/prerequisites", params={"mode": "create_new"}).json()
    assert body["import_counts"] == {"receptor": 0, "ligand_sdf": 0, "receptor_bonds": 0}
    assert _post(client, rid, "ligand_sdf", "x.sdf",
                 (CHEM / "prolif-vina-output.sdf").read_bytes()).status_code == 201
