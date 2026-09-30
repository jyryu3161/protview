"""M15 T5 fixtures: provenance of the public 1MQ4 entry, the reference row fixtures, the derived structure fixtures,
and the importer-layout FIXTURE set builder (``reference_fixture_set.py``)."""

import hashlib
import importlib.util
import json
from pathlib import Path

import gemmi
import pytest
import reference_fixture_set as rfs

from mw import reference_snapshots as rs
from mw import sifts_mapping as sm
from mw.klifs_numbering import index_kinases_by_uniprot, klifs_table
from mw.sequence_alignment import align_global, to_one_letter

FIX = Path(__file__).resolve().parent / "fixtures"
STRUCT = FIX / "structures_m15"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_public_1mq4_matches_provenance():
    prov = json.loads((FIX / "public_1mq4.provenance.json").read_text())
    data = (FIX / prov["file"]).read_bytes()
    assert prov["source_url"] == "https://files.rcsb.org/download/1MQ4.cif" and prov["modified"] is False
    assert _sha(data) == prov["sha256"] and len(data) == prov["bytes"]
    assert data.startswith(b"data_1MQ4\n")


@pytest.mark.parametrize("source", ["uniprot", "klifs"])
def test_reference_row_fixtures_match_provenance(source):
    prov = json.loads((FIX / "reference" / source / "provenance_fixture.json").read_text())
    assert "fixture" in prov["label"]
    for entry in prov["files"]:
        assert "fixture" in entry["file"]
        data = (FIX / "reference" / source / entry["file"]).read_bytes()
        assert _sha(data) == entry["sha256"] and len(data) == entry["bytes"]
        lines = [line for line in data.split(b"\n") if line]
        assert [str(json.loads(line)[entry["id_field"]]) for line in lines] == entry["extracted_ids"]
        for row_id, line in zip(entry["extracted_ids"], lines, strict=True):
            assert _sha(line) == entry["extracted_line_sha256"][row_id]


def _load_generator():
    spec = importlib.util.spec_from_file_location("make_structures_m15", STRUCT / "make_structures_m15.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_derived_structures_regenerate_and_match_provenance():
    prov = json.loads((STRUCT / "provenance_fixture.json").read_text())
    assert "fixture" in prov["label"]
    assert prov["source_sha256"] == _sha((FIX / "public_1mq4.cif").read_bytes())
    built = _load_generator().build_all()
    assert sorted(built) == sorted(entry["file"] for entry in prov["files"])
    for entry in prov["files"]:
        assert "fixture" in entry["file"]
        data = (STRUCT / entry["file"]).read_bytes()
        assert data == built[entry["file"]]
        assert _sha(data) == entry["sha256"] and len(data) == entry["bytes"]


def _chains(name: str) -> list[tuple[int, str, list[gemmi.Residue]]]:
    st = gemmi.read_structure(str(STRUCT / name))
    return [(i + 1, ch.name, list(ch)) for i, model in enumerate(st) for ch in model]


def _o14965() -> str:
    rows = [json.loads(line) for line in (FIX / "reference" / "uniprot" / "entries_fixture.jsonl").read_text().splitlines()]
    return next(r for r in rows if r["id"] == "O14965")["data"]["sequence"]


@pytest.mark.parametrize("name, expected", [
    ("derived_1mq4_a200_285_fixture.pdb", [(1, "A", 200, 285, 86)]),
    ("derived_1mq4_a200_285_icode_fixture.pdb", [(1, "A", 200, 285, 86)]),
    ("derived_1mq4_a288_360_mse_fixture.cif", [(1, "A", 288, 360, 73)]),
    ("derived_1mq4_a288_360_mse_fixture.pdb", [(1, "A", 288, 360, 73)]),
    ("derived_1mq4_two_chain_fixture.pdb", [(1, "A", 200, 285, 86), (1, "B", 126, 199, 74)]),
    ("derived_1mq4_two_model_fixture.pdb", [(1, "A", 126, 199, 74), (2, "A", 200, 285, 86)]),
])
def test_derived_structures_shape_and_alignment(name, expected):
    uniprot = _o14965()
    chains = _chains(name)
    assert [(m, c, rs_[0].seqid.num, rs_[-1].seqid.num, len(rs_)) for m, c, rs_ in chains] == expected
    for _model, _chain, residues in chains:
        aln = align_global("".join(to_one_letter(r.name) for r in residues), uniprot)
        # 1MQ4 author numbers equal O14965 positions (SIFTS segment pdbe 6-272 -> 125-391, author = pdbe + 119).
        assert list(aln.structure_to_uniprot) == [r.seqid.num if r.seqid.icode == " " else 241 for r in residues]
        assert aln.coverage_pct == 100.0 and aln.identity_pct >= 98.0


def test_derived_structure_special_residues():
    pdb_only = _chains("derived_1mq4_a200_285_fixture.pdb")[0][2]
    assert all(r.label_seq is None for r in pdb_only)
    icode = [(r.seqid.num, r.seqid.icode) for r in _chains("derived_1mq4_a200_285_icode_fixture.pdb")[0][2]]
    assert (240, "A") in icode and (241, " ") not in icode
    for name in ("derived_1mq4_a288_360_mse_fixture.cif", "derived_1mq4_a288_360_mse_fixture.pdb"):
        residues = _chains(name)[0][2]
        mse = [r for r in residues if r.name == "MSE"]
        assert [(r.seqid.num, r.het_flag) for r in mse] == [(300, "H")]
        assert [a.name for a in mse[0] if a.element.name == "Se"] == ["SE"]
    cif = _chains("derived_1mq4_a288_360_mse_fixture.cif")[0][2]
    assert [(r.seqid.num, r.label_seq) for r in cif][:2] == [(288, 169), (289, 170)]
    st = gemmi.read_structure(str(STRUCT / "derived_1mq4_a288_360_mse_fixture.pdb"))
    st.setup_entities()
    assert len(st.entities[0].full_sequence) == 272 and st.entities[0].full_sequence[180] == "MSE"


@pytest.fixture
def ref_root(tmp_path, monkeypatch):
    root = tmp_path / "reference"
    monkeypatch.setenv(rs.ENV_VAR, str(root))
    rs._VERIFIED.clear()
    return root


def test_fixture_set_is_accepted_by_pin_active_set(ref_root):
    set_hash = rfs.build_fixture_set(ref_root)
    pinned = rs.pin_active_set()
    assert pinned.set_hash == set_hash
    assert rs.capability()["available"] is True
    with pytest.raises(rs.SnapshotAccessError):
        pinned.read_bytes("klifs", "match_residues.jsonl")
    rows = list(pinned.iter_jsonl("klifs", "match_residues.jsonl", allow_comparison_only=True))
    assert [r["pdb_id"] for r in rows] == ["1MQ4", "6T6F", "5JGA", "1AD5"]
    chain = sm.index_for_set(pinned).lookup("1MQ4", "A")
    assert isinstance(chain, sm.SiftsChain) and chain.accessions == {"O14965"}
    kinases = index_kinases_by_uniprot(pinned.iter_jsonl("klifs", "kinases.jsonl"))
    table = klifs_table("O14965", kinases["O14965"], _o14965())
    assert table["absent_reason"] is None and table["positions"]


def test_fixture_set_replace_and_second_build_get_new_hash(ref_root):
    first = rfs.build_fixture_set(ref_root, tag="one")
    second = rfs.build_fixture_set(ref_root, tag="two", replace={("klifs", "kinases.jsonl"): b""})
    assert first != second and rs.pin_active_set().set_hash == second
    assert list(rs.pin_active_set().iter_jsonl("klifs", "kinases.jsonl")) == []
