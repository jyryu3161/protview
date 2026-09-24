"""Hand-checkable structure identity and preparation fixtures."""
from __future__ import annotations

import hashlib
import json
import shutil

import gemmi
import pytest

from mw.core.errors import FailureClass, ToolFailure
from mw.core.events import idempotency_key
from mw.core.residue import ResidueRef
from mw.runtime.orchestrator import replay
from mw.workspace import build_registry, new_run


def atom(serial: int, name: str, alt: str, x: float, occ: float, *, model: int) -> str:
    return (f"ATOM  {serial:5d} {name:<4s}{alt:1s}ALA A 100A   "
            f"{x:8.3f}{0.0:8.3f}{0.0:8.3f}{occ:6.2f}{20.0:6.2f}"
            f"          {name[0]:>2s}\n")


def multimodel_pdb() -> bytes:
    return ("MODEL        1\n" + atom(1, "CA", " ", 0, 1, model=1)
            + atom(2, "CB", "A", 1, 0.2, model=1)
            + atom(3, "CB", "B", 2, 0.8, model=1)
            + "ENDMDL\nMODEL        2\n" + atom(4, "CA", " ", 10, 1, model=2)
            + atom(5, "CB", "A", 11, 0.2, model=2)
            + atom(6, "CB", "B", 12, 0.8, model=2)
            + "ENDMDL\nEND\n").encode()


MMCIF = b"""data_test
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


def parse_prepared(run, handle):
    coordinates = run.store.load(handle)["coordinates"]
    raw = run.store.load(coordinates).decode()
    fmt = run.store.meta(coordinates)["fmt"]
    return (gemmi.make_structure_from_block(gemmi.cif.read_string(raw).sole_block())
            if fmt == "cif" else gemmi.read_pdb_string(raw))


def test_model_choice_altloc_occupancy_and_auth_icode(tmp_path):
    path = tmp_path / "models.pdb"
    path.write_bytes(multimodel_pdb())
    run = new_run(tmp_path / "runs", run_id="models")
    first = run.call("load_structure", {"source": str(path), "model_index": 0})
    second = run.call("load_structure", {"source": str(path), "model_index": 1})
    assert first.handle != second.handle
    assert first.summary["source_handle"] == second.summary["source_handle"]
    prepared = run.call("prepare_structure", {"structure": second.handle})
    st = parse_prepared(run, prepared.handle)
    assert len(st) == 1 and st[0].num == 2
    residue = st[0][0][0]
    assert residue.seqid.num == 100 and residue.seqid.icode == "A"
    assert [(a.name, a.pos.x) for a in residue] == [("CA", 10.0), ("CB", 12.0)]
    assert prepared.summary["altlocs"] == 1
    manifest = run.store.load(prepared.summary["manifest"])
    assert manifest["altloc_choices"][0]["selected"] == "B"
    assert manifest["model_index"] == 1
    assert manifest["protonation"]["applied"] is False


def test_first_selected_model_keeps_nondefault_model_number(tmp_path):
    path = tmp_path / "model_five.pdb"
    path.write_bytes(multimodel_pdb().replace(b"MODEL        1", b"MODEL        5")
                     .replace(b"MODEL        2", b"MODEL        6"))
    run = new_run(tmp_path / "runs", run_id="model_five")
    imported = run.call("load_structure", {"source": str(path)})
    prepared = run.call("prepare_structure", {"structure": imported.handle})
    assert imported.summary["model_number"] == 5
    assert run.store.meta(run.store.load(prepared.handle)["coordinates"])["fmt"] == "cif"
    assert parse_prepared(run, prepared.handle)[0].num == 5


def test_residue_key_keeps_model_auth_and_icode_when_label_missing():
    base = {"model_number": 1, "chain_auth": "A", "seq_auth": 100,
            "icode": "A", "chain_label": None, "seq_label": None, "resname": "ALA"}
    first = ResidueRef(**base)
    assert first.key != ResidueRef(**{**base, "model_number": 2}).key
    assert first.key != ResidueRef(**{**base, "icode": "B"}).key
    assert first.key != ResidueRef(**{**base, "chain_auth": "B"}).key


def test_mmcif_label_and_author_ids_survive_preparation(tmp_path):
    path = tmp_path / "different_ids.cif"
    path.write_bytes(MMCIF)
    run = new_run(tmp_path / "runs", run_id="cif")
    imported = run.call("load_structure", {"source": str(path)})
    prepared = run.call("prepare_structure", {"structure": imported.handle})
    assert run.store.meta(run.store.load(prepared.handle)["coordinates"])["fmt"] == "cif"
    st = parse_prepared(run, prepared.handle)
    protein = st[0][0][0]
    ligand = st[0][1][0]
    assert st[0][0].name == "X" and protein.subchain == "L"
    assert protein.seqid.num == 100 and protein.seqid.icode == "A" and protein.label_seq == 97
    assert st[0][1].name == "Y" and ligand.subchain == "M" and ligand.label_seq is None


def test_repeated_gemmi_segments_have_unique_author_chain_summary(tmp_path):
    raw = MMCIF + (b"ATOM 3 C CA . GLY N 3 98 ? 3 0 0 1 20 101 GLY X CA 1\n"
                   b"HETATM 4 O O1 . LIG O 4 . ? 4 0 0 1 20 302 LIG Y O1 1\n")
    path = tmp_path / "segmented.cif"
    path.write_bytes(raw)
    parsed = gemmi.make_structure_from_block(gemmi.cif.read_string(raw.decode()).sole_block())
    assert [chain.name for chain in parsed[0]] == ["X", "Y", "X", "Y"]
    run = new_run(tmp_path / "runs", run_id="segments")
    source = run.store.put("structure_source", "structure_source@1", raw, fmt="cif")
    selection = {"source": source.handle, "model_index": 0, "format": "cif"}
    legacy = run.store.put("structure", "structure_selection@1", selection,
                           summary={"chains_auth": ["X", "Y", "X", "Y"]})
    legacy_key = idempotency_key("load_structure", "0.1.0",
                                 {"source": str(path), "model_index": 0,
                                  "source_sha256": hashlib.sha256(raw).hexdigest()})
    run.events.append("tool_succeeded", tool="load_structure", key=legacy_key,
                      call_id="legacy_fixture", output=legacy.model_dump(by_alias=True))
    imported = run.call("load_structure", {"source": str(path)})
    assert imported.summary["chains_auth"] == ["X", "Y"]
    assert imported.summary["n_residues"] == 4
    assert imported.summary["source_handle"] == source.handle
    assert imported.handle != legacy.handle
    assert any(e["type"] == "tool_called" and e["tool"] == "load_structure" for e in run.events.read())
    assert run.store.meta(legacy.handle)["summary"]["chains_auth"] == ["X", "Y", "X", "Y"]


def test_import_hash_tracks_bytes_even_when_path_is_reused(tmp_path):
    path = tmp_path / "mutable.pdb"
    original = multimodel_pdb()
    path.write_bytes(original)
    run = new_run(tmp_path / "runs", run_id="bytes")
    first = run.call("load_structure", {"source": str(path)})
    duplicate_path = tmp_path / "copy.pdb"
    duplicate_path.write_bytes(original)
    duplicate = run.call("load_structure", {"source": str(duplicate_path)})
    assert duplicate.handle == first.handle
    path.write_bytes(original.replace(b"  0.000", b"  3.000", 1))
    changed = run.call("load_structure", {"source": str(path)})
    assert changed.handle != first.handle


def test_same_coordinates_keep_distinct_preparation_policy_and_replay(tmp_path):
    path = tmp_path / "no_water.pdb"
    path.write_text(atom(1, "CA", " ", 0, 1, model=1) + "END\n")
    run = new_run(tmp_path / "runs", run_id="policy")
    imported = run.call("load_structure", {"source": str(path)})
    keep = run.call("prepare_structure", {"structure": imported.handle, "waters": "keep_all"})
    strip = run.call("prepare_structure", {"structure": imported.handle, "waters": "strip_all"})
    assert keep.handle != strip.handle
    assert run.store.load(keep.handle)["coordinates"] == run.store.load(strip.handle)["coordinates"]
    for result, policy in ((keep, "keep_all"), (strip, "strip_all")):
        assert run.store.meta(result.handle)["summary"]["manifest"] == result.summary["manifest"]
        assert run.store.load(result.summary["manifest"])["waters"] == policy
    run.store.db.close()
    restored = replay(run.run_dir / "events.jsonl", tmp_path / "replayed" / "policy",
                      build_registry(), "policy")
    assert keep.handle in restored and strip.handle in restored
    from mw.core.handles import ObjectStore
    store = ObjectStore(tmp_path / "replayed" / "policy", "policy")
    assert store.load(store.meta(strip.handle)["summary"]["manifest"])["waters"] == "strip_all"


def test_events_alone_restore_bytes_and_handles_without_source(tmp_path):
    path = tmp_path / "source.pdb"
    raw = multimodel_pdb()
    path.write_bytes(raw)
    run = new_run(tmp_path / "runs", run_id="recover")
    imported = run.call("load_structure", {"source": str(path), "model_index": 1})
    prepared = run.call("prepare_structure", {"structure": imported.handle})
    originals = run.store.handles()
    prepared_content = run.store.load(prepared.handle)
    prepared_bytes = run.store.load(prepared_content["coordinates"])
    source_handle = imported.summary["source_handle"]
    path.unlink()
    run.store.db.close()
    shutil.rmtree(run.run_dir / "objects")
    (run.run_dir / "index.sqlite").unlink()
    restored = replay(run.run_dir / "events.jsonl", tmp_path / "replayed" / "recover",
                      build_registry(), "recover")
    assert restored == originals
    from mw.core.handles import ObjectStore
    store = ObjectStore(tmp_path / "replayed" / "recover", "recover")
    assert store.load(source_handle) == raw
    assert store.load(prepared.handle) == prepared_content
    assert store.load(prepared_content["coordinates"]) == prepared_bytes


def test_bad_input_and_unsupported_policies_fail(tmp_path):
    path = tmp_path / "broken.pdb"
    path.write_text("not a structure")
    run = new_run(tmp_path / "runs", run_id="bad")
    with pytest.raises(ToolFailure) as error:
        run.call("load_structure", {"source": str(path)})
    assert error.value.cls == FailureClass.input_invalid
    path.write_text(atom(1, "CA", " ", float("nan"), 1.0, model=1) + "END\n")
    with pytest.raises(ToolFailure) as error:
        run.call("load_structure", {"source": str(path)})
    assert error.value.cls == FailureClass.input_invalid
    path.write_bytes(multimodel_pdb())
    imported = run.call("load_structure", {"source": str(path)})
    for args in ({"missing_residues": "model"}, {"symmetry_mates": "include_contacts"},
                 {"waters": "keep_bridging"}, {"protonation_ph": 7.4}):
        with pytest.raises(ToolFailure) as error:
            run.call("prepare_structure", {"structure": imported.handle, **args})
        assert error.value.cls in {FailureClass.input_invalid, FailureClass.precondition}


def test_corrupt_event_payload_rejected(tmp_path):
    run = new_run(tmp_path / "runs", run_id="tamper")
    run.store.put("thing", "thing@1", {"value": 1})
    source = run.run_dir / "events.jsonl"
    events = [json.loads(line) for line in source.read_text().splitlines()]
    event = next(event for event in events if event["type"] == "object_created")
    event["payload_b64"] = "e30="  # valid base64, wrong content hash
    corrupted = tmp_path / "corrupt.jsonl"
    corrupted.write_text("\n".join(json.dumps(event) for event in events) + "\n")
    with pytest.raises(ValueError, match="hash"):
        replay(corrupted, tmp_path / "restored" / "tamper", build_registry(), "tamper")
