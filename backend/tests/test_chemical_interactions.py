"""M11 public prepared fixture: actual isolated native inference and strict maps.

The files are ProLIF's licensed tutorial fixtures; see chemical/PROVENANCE.json.
No observed assignment is treated as experimental validation.
"""
from __future__ import annotations

import collections
import hashlib
import json
import math
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from mw.chemical_bundle import (
    WORKER,
    WORKER_PYTHON,
    _cif_row_matches,
    _cif_rows,
    _generated_label_asym,
    _tetrahedral_determinant,
    atom_catalog,
    dependency,
    detect_selected,
    prepare_selected,
    publish_detect,
    publish_prepare,
    validated_graph,
    validated_result,
    validated_source,
)
from mw.chemical_inputs import (
    _bonds,
    _protein_graph_blockers,
    _sdf_records,
    _source_rows,
    import_raw,
    inspect,
    preview,
    receptor_atom_page,
    receptor_atoms,
)
from mw.core.errors import ToolFailure
from mw.core.handles import ObjectStore, canonical_json

FIXTURES = Path(__file__).parent / "fixtures/chemical"


def _store(tmp_path: Path, suffix: str = "new") -> ObjectStore:
    return ObjectStore(tmp_path / suffix, f"run_m11_{suffix}")


def _ack() -> dict:
    return {"schema": "chemical_preparation_ack@1", "supplied_graph_complete": True,
            "supplied_hydrogens_complete": True, "use_supplied_protonation_tautomer": True,
            "infer_receptor_orders_charges": True, "description": "licensed tutorial fixture", "ph_annotation": None}


def _create(store: ObjectStore) -> dict:
    rec = import_raw(store, "receptor", "rec.pdb", (FIXTURES / "prolif-vina-rec.pdb").read_bytes())
    lig = import_raw(store, "ligand_sdf", "lig.sdf", (FIXTURES / "prolif-vina-output.sdf").read_bytes())
    assert rec["sha256"] == "745bd4726ba956e27da5cf4da10189f2bbe937db59ff08f302bca9d2cdbc62cc"
    assert lig["sha256"] == "810b8c714edd3140585664f980c8e6644ba9c76372029cb3abbfa4d13b5899e0"
    req = {"schema": "chemical_prepare_request@1", "mode": "create_new",
           "receptor_input_handle": rec["handle"], "receptor_model_number": 1,
           "connectivity": {"kind": "pdb_conect", "sidecar_handle": None},
           "ligand_sdf_handle": lig["handle"], "sdf_record_index": 0,
           "ligand_instance": {"model_number": 1, "chain_auth": "L", "chain_label": None,
                               "seq_auth": 1, "seq_label": None, "icode": "", "resname": "LIG"},
           "terminal_extensions": [], "acknowledgement": _ack()}
    first = preview(store, req)
    assert {b["code"] for b in first["blockers"]} == {"terminal_extension_undeclared"}
    assert len(first["terminal_extensions"]) == 2
    req["terminal_extensions"] = [{"residue": x["residue"], "atom_names": x["atom_names"],
                                    "approve_supplied_graph": True} for x in first["terminal_extensions"]]
    assert preview(store, req, strict=True)["ready"]
    return req


def _run_worker(tmp_path: Path, adapter: str, selected: dict) -> dict:
    root = tmp_path / adapter
    root.mkdir(parents=True)
    raw = json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()
    (root / "structure.json").write_bytes(raw)
    (root / "input.json").write_text(json.dumps({"adapter": adapter,
                                                "input_sha256": hashlib.sha256(raw).hexdigest()}))
    proc = subprocess.run([str(WORKER_PYTHON), "-I", str(WORKER)], cwd=root,
                          capture_output=True, timeout=120, check=False,
                          env={"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1",
                               "PYTHONUNBUFFERED": "1", "TMPDIR": str(root)})
    assert proc.returncode == 0, (proc.stderr[-1000:], (root / "error.json").read_text()
                                  if (root / "error.json").exists() else "")
    return json.loads((root / "result.json").read_text())


def _run_worker_failure(tmp_path: Path, adapter: str, selected: dict) -> dict:
    root = tmp_path / adapter
    root.mkdir(parents=True)
    raw = json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()
    (root / "structure.json").write_bytes(raw)
    (root / "input.json").write_text(json.dumps({"adapter": adapter,
                                                "input_sha256": hashlib.sha256(raw).hexdigest()}))
    proc = subprocess.run([str(WORKER_PYTHON), "-I", str(WORKER)], cwd=root,
                          capture_output=True, timeout=120, check=False,
                          env={"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1",
                               "PYTHONUNBUFFERED": "1", "TMPDIR": str(root)})
    assert proc.returncode != 0 and not (root / "result.json").exists()
    return json.loads((root / "error.json").read_text())


def _native_protein_graph_error(tmp_path: Path, prepared: dict, residue: dict, variant: str) -> dict:
    """Exercise the pinned worker's actual RDKit graph validator on one source residue."""
    source_indices = [i for i, atom in enumerate(prepared["receptor_atoms"])
                      if atom["source_ref"]["residue"] == residue]
    remap = {source: local for local, source in enumerate(source_indices)}
    payload = {"atoms": [prepared["receptor_atoms"][i] for i in source_indices],
               "bonds": [{"first": remap[b["first"]], "second": remap[b["second"]],
                          "order": b["order"]} for b in prepared["receptor_bonds"]
                         if b["first"] in remap and b["second"] in remap]}
    source = tmp_path / f"histidine-{variant}.json"
    source.write_text(json.dumps(payload))
    script = """
import importlib.util, json, sys
from rdkit import Chem
spec = importlib.util.spec_from_file_location('chemical_worker_probe', sys.argv[1])
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
data = json.load(open(sys.argv[2]))
builder = Chem.RWMol()
for row in data['atoms']:
    atom = Chem.Atom(row['element'].capitalize())
    atom.SetFormalCharge(row['formal_charge'])
    atom.SetIsAromatic(row['aromatic'])
    builder.AddAtom(atom)
for row in data['bonds']:
    kind = getattr(Chem.BondType, row['order'])
    builder.AddBond(row['first'], row['second'], kind)
    builder.GetBondBetweenAtoms(row['first'], row['second']).SetIsAromatic(row['order'] == 'AROMATIC')
names = {row['source_ref']['atom_name']: i for i, row in enumerate(data['atoms'])}
if sys.argv[3] == 'ring':
    edge = builder.GetBondBetweenAtoms(names['CG'], names['ND1'])
    edge.SetBondType(Chem.BondType.SINGLE)
    edge.SetIsAromatic(False)
elif sys.argv[3] == 'charge':
    builder.GetAtomWithIdx(names['ND1']).SetFormalCharge(1)
elif sys.argv[3] == 'amide':
    builder.GetAtomWithIdx(names['ND2']).SetFormalCharge(1)
elif sys.argv[3] == 'cap':
    cap = names['CAY']
    hydrogen = next(atom.GetIdx() for atom in builder.GetAtomWithIdx(cap).GetNeighbors()
                    if atom.GetSymbol() == 'H')
    builder.RemoveBond(cap, hydrogen)
try:
    worker._protein_chemistry([{'source_ref': row['source_ref']} for row in data['atoms']], builder.GetMol())
except worker.NativeChemicalInputError as error:
    print(json.dumps(error.envelope(), sort_keys=True))
else:
    raise AssertionError('invalid native histidine graph was accepted')
"""
    proc = subprocess.run([str(WORKER_PYTHON), "-I", "-c", script, str(WORKER), str(source), variant],
                          capture_output=True, text=True, timeout=30, check=False,
                          env={"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1"})
    assert proc.returncode == 0, proc.stderr[-1000:]
    return json.loads(proc.stdout)


def test_signed_tetrahedral_determinant_is_not_tetrahedron_volume() -> None:
    """Unit orthogonal tetrahedron has determinant 1 Å³ and volume 1/6 Å³."""
    points = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
              [0.0, 0.0, 1.0], [0.0, 0.0, 0.0]]
    determinant = _tetrahedral_determinant(points)
    assert determinant == pytest.approx(1.0)
    assert abs(determinant) / 6 == pytest.approx(1 / 6)
    assert _tetrahedral_determinant([points[1], points[0], points[2], points[3]]) == pytest.approx(-1.0)


def test_raw_import_reuses_exact_bytes_across_filenames_and_old_metadata(tmp_path: Path) -> None:
    raw = (FIXTURES / "prolif-vina-output.sdf").read_bytes()
    store = _store(tmp_path, "raw_idempotent")
    first = import_raw(store, "ligand_sdf", "original.sdf", raw)
    original_meta = store.meta(first["handle"])
    assert "filename" not in original_meta["summary"]
    assert import_raw(store, "ligand_sdf", "original.sdf", raw) == first
    assert import_raw(store, "ligand_sdf", "renamed.sdf", raw) == first
    assert store.handles() == {first["handle"]}
    assert store.meta(first["handle"]) == original_meta and store.load(first["handle"]) == raw

    historical = _store(tmp_path, "raw_historical")
    old = historical.put("chemical_raw_input", "chemical_raw_input@1", raw, fmt="sdf",
                         summary={"input_kind": "ligand_sdf", "filename": "old.sdf",
                                  "input_format": "sdf", "sha256": hashlib.sha256(raw).hexdigest()})
    old_meta = historical.meta(old.handle)
    again = import_raw(historical, "ligand_sdf", "new.sdf", raw)
    assert again["handle"] == old.handle and historical.meta(old.handle) == old_meta
    assert historical.load(old.handle) == raw

    mislabeled = _store(tmp_path, "raw_mislabeled")
    mislabeled.put("chemical_raw_input", "chemical_raw_input@1", raw, fmt="sdf",
                   summary={"input_kind": "receptor", "input_format": "sdf",
                            "sha256": hashlib.sha256(raw).hexdigest()})
    with pytest.raises(ToolFailure, match="incompatible imported kind"):
        import_raw(mislabeled, "ligand_sdf", "lig.sdf", raw)


def test_import_preview_and_exact_cap_declaration(tmp_path: Path) -> None:
    store = _store(tmp_path)
    req = _create(store)
    rec = inspect(store, req["receptor_input_handle"])
    lig = inspect(store, req["ligand_sdf_handle"])
    assert rec["models"] == [{"model_number": 1, "atom_count": 4988, "water_atoms": 0,
                               "hydrogen_atoms": rec["models"][0]["hydrogen_atoms"]}]
    assert len(lig["records"]) == 9 and lig["records"][0]["atom_count"] == 79
    assert lig["records"][1]["has_3d"]
    page = receptor_atom_page(store, req["receptor_input_handle"], 1, 0, 1)
    assert page["total"] == 4988 and page["rows"][0]["ref"]["atom_name"] == "CAY"
    first_lig = _sdf_records(store.load(req["ligand_sdf_handle"]).decode())[0]["atoms"][0]
    assert first_lig["name_generated"] is True and first_lig["atom_map_tag"] is None
    assert prepare_selected(store, req)["receptor_bonds"] and len(prepare_selected(store, req)["receptor_bonds"]) == 5053
    req["acknowledgement"]["supplied_hydrogens_complete"] = False
    assert "supplied_hydrogens_complete" in {x["code"] for x in preview(store, req)["blockers"]}
    with pytest.raises(ToolFailure):
        preview(store, req, strict=True)


def test_actual_native_create_detect_and_tamper_rejection(tmp_path: Path) -> None:
    store = _store(tmp_path)
    selected = prepare_selected(store, _create(store))
    assert selected["dependency"] == dependency()
    prepared = _run_worker(tmp_path, "prolif_prepare_v1", selected)
    assert (prepared["receptor_atom_count"], prepared["ligand_atom_count"],
            prepared["supplied_graph_edge_count"]) == (4988, 79, 5139)
    assert [a["native_parent_index"] for a in prepared["receptor_atoms"]] == list(range(4988))
    assert len(prepared["stereochemistry_audit"]) == 7
    assert all(row["declared_CIP"] == row["observed_CIP"] and row["outcome"] == "match"
               for row in prepared["stereochemistry_audit"])
    adjacency = {tuple(sorted((bond["first"], bond["second"]))): bond["order"]
                 for bond in prepared["receptor_bonds"]}
    for resname, carbon, first_o, second_o in (("ASP", "CG", "OD1", "OD2"),
                                                ("GLU", "CD", "OE1", "OE2")):
        residue = next(atom["source_ref"]["residue"] for atom in prepared["receptor_atoms"]
                       if atom["source_ref"]["residue"]["resname"] == resname)
        sites = {atom["atom_name"]: i for i, atom in enumerate(prepared["receptor_atoms"])
                 if atom["source_ref"]["residue"] == residue}
        oxygen_indices = (sites[first_o], sites[second_o])
        assert sorted(prepared["receptor_atoms"][i]["formal_charge"] for i in oxygen_indices) == [-1, 0]
        assert {adjacency[tuple(sorted((sites[carbon], i)))] for i in oxygen_indices} == {
            "SINGLE", "DOUBLE"}
    assert {tuple(state["ring_h_sites"]) for state in prepared["histidine_states"]} >= {
        ("ND1",), ("NE2",)}
    assert {state["represented_state"] for state in prepared["histidine_states"]} >= {
        "neutral_ND1_H", "neutral_NE2_H"}
    assert all(state["ring_formal_charge"] == 0 and
               state["ring_n_charges"] == {"ND1": 0, "NE2": 0}
               for state in prepared["histidine_states"])
    before = store.handles()
    missing_stereo = json.loads(json.dumps(prepared))
    missing_stereo["stereochemistry_audit"].pop()
    with pytest.raises(ValueError, match="stereo"):
        publish_prepare(SimpleNamespace(store=store), {"selected": selected},
                        "attempt_missing_stereo", missing_stereo)
    assert store.handles() == before
    histidine_residue = next(state["residue"] for state in prepared["histidine_states"]
                             if state["ring_h_sites"] == ["ND1"])
    for variant, reason in (("ring", "histidine_ring_graph"),
                            ("charge", "histidine_charge_state")):
        native_error = _native_protein_graph_error(tmp_path, prepared, histidine_residue, variant)
        assert native_error["error_class"] == "input_invalid"
        assert native_error["reason_code"] == reason
        assert native_error["source_residues"] == [histidine_residue]
        assert native_error["source_atoms"]
        assert all(ref["residue"] == histidine_residue for ref in native_error["source_atoms"])
    for variant, residue_name in (("amide", "ASN"), ("cap", None)):
        residue = next(atom["source_ref"]["residue"] for atom in prepared["receptor_atoms"]
                       if ((variant == "cap" and atom["atom_name"] == "CAY") or
                           (variant == "amide" and atom["source_ref"]["residue"]["resname"] == residue_name)))
        native_error = _native_protein_graph_error(tmp_path, prepared, residue, variant)
        assert native_error["reason_code"] == "receptor_graph_invalid"
        assert native_error["source_residues"] == [residue]
        assert native_error["source_atoms"]
        assert all(ref["residue"] == residue for ref in native_error["source_atoms"])
    histidine_sites = {atom["atom_name"]: i for i, atom in enumerate(prepared["receptor_atoms"])
                       if atom["source_ref"]["residue"] == histidine_residue}
    wrong_ring = json.loads(json.dumps(prepared))
    ring_edge = next(b for b in wrong_ring["receptor_bonds"]
                     if {b["first"], b["second"]} ==
                     {histidine_sites["CG"], histidine_sites["ND1"]})
    ring_edge["order"] = "SINGLE"
    with pytest.raises(ValueError, match="histidine"):
        publish_prepare(SimpleNamespace(store=store), {"selected": selected},
                        "attempt_wrong_histidine_ring", wrong_ring)
    wrong_charge = json.loads(json.dumps(prepared))
    wrong_charge["receptor_atoms"][histidine_sites["ND1"]]["formal_charge"] = 1
    with pytest.raises(ValueError, match="histidine"):
        publish_prepare(SimpleNamespace(store=store), {"selected": selected},
                        "attempt_wrong_histidine_charge", wrong_charge)
    assert store.handles() == before
    bad = json.loads(json.dumps(prepared))
    bad["ligand_bonds"][0]["first"] = bad["ligand_bonds"][0]["second"]
    with pytest.raises(ValueError):
        publish_prepare(SimpleNamespace(store=store), {"selected": selected}, "attempt_bad", bad)
    assert store.handles() == before  # invalid late graph field publishes nothing
    charge_bad = json.loads(json.dumps(prepared))
    charge_bad["ligand_atoms"][20]["formal_charge"] = 0
    with pytest.raises(ValueError, match="mapping"):
        publish_prepare(SimpleNamespace(store=store), {"selected": selected}, "attempt_bad_charge", charge_bad)
    assert store.handles() == before
    order_bad = json.loads(json.dumps(prepared))
    order_bad["ligand_bonds"][0]["order"] = "TRIPLE"
    with pytest.raises(ValueError, match="bond order"):
        publish_prepare(SimpleNamespace(store=store), {"selected": selected}, "attempt_bad_order", order_bad)
    assert store.handles() == before
    manifest, source, graph = publish_prepare(SimpleNamespace(store=store),
                                              {"selected": selected}, "attempt_native", prepared)
    assert validated_source(store, source)["manifest_handle"] == manifest
    assert len(atom_catalog(store, source, 0, 100)["rows"]) == 100
    assert validated_graph(store, graph)["chemical_structure_handle"] == source
    detect_input = detect_selected(store, {"schema": "chemical_detect_request@1", "graph_handle": graph,
                                           "categories": ["HBDonor", "HBAcceptor", "Hydrophobic",
                                                          "Cationic", "Anionic"]})
    detected = _run_worker(tmp_path, "prolif_detect_v1", detect_input)
    assert detected["native_total"] == 36
    assert collections.Counter(x["category"] for x in detected["native_rows"]) == {
        "Hydrophobic": 32, "HBDonor": 1, "HBAcceptor": 1, "Cationic": 2}
    assert all(not (prepared["receptor_atoms"][row["parent_indices"]["protein"][0]]["source_ref"]
                    ["residue"]["resname"] in {"ASN", "GLN"} and
                    prepared["receptor_atoms"][row["parent_indices"]["protein"][0]]["atom_name"]
                    in {"ND2", "NE2"})
               for row in detected["native_rows"] if row["category"] == "HBDonor")
    result_handle = publish_detect(SimpleNamespace(store=store), {"selected": detect_input},
                                   "attempt_detect", detected)[0]
    result = validated_result(store, result_handle)
    assert result["total"] == 36 and not result["null_result"]
    donor = next(x for x in result["rows"] if x["category"] == "HBDonor")
    acceptor = next(x for x in result["rows"] if x["category"] == "HBAcceptor")
    assert donor["native_parent_indices"] == {"ligand": [20, 58], "protein": [1489]}
    assert acceptor["native_parent_indices"] == {"ligand": [11], "protein": [2626, 2627]}
    assert donor["roles"]["hydrogen"]["element"] == "H"
    assert result["criteria"]["native_smarts_sha256"] == dependency()["native_method"]["native_smarts_sha256"]
    assert result["criteria"]["native_smarts"]["HBDonor"]["ligand"]
    bad_detect = json.loads(json.dumps(detected))
    bad_detect["native_rows"][0]["parent_indices"]["protein"][0] = 999999
    with pytest.raises((ValueError, IndexError)):
        publish_detect(SimpleNamespace(store=store), {"selected": detect_input}, "attempt_bad_detect", bad_detect)


def test_attach_explicit_bijection_and_sidecar(tmp_path: Path) -> None:
    store = _store(tmp_path, "attach")
    receptor = (FIXTURES / "prolif-vina-rec.pdb").read_text()
    sdf = (FIXTURES / "prolif-vina-output.sdf").read_bytes()
    lig_atoms = _sdf_records(sdf.decode())[0]["atoms"]
    appended = []
    for i, atom in enumerate(lig_atoms):
        x, y, z = atom["coordinate_A"]
        appended.append(f'HETATM{4989+i:5d} {f"X{i + 1}":<4s} LIG L   1    '
                        f'{x:8.3f}{y:8.3f}{z:8.3f}{1.00:6.2f}{0.00:6.2f}'
                        f'          {atom["element"].upper():>2s}  ')
    combined = (receptor.split("CONECT")[0] + "\n".join(appended) + "\nEND\n").encode()
    raw_source = store.put("structure_source", "structure_source@1", combined, fmt="pdb")
    complex_source = store.put("structure", "structure_selection@2",
                               {"source": raw_source.handle, "format": "pdb", "model_index": 0})
    ligand = import_raw(store, "ligand_sdf", "lig.sdf", sdf)
    original = import_raw(store, "receptor", "rec.pdb", receptor.encode())
    original_rows = receptor_atoms(store, original["handle"], 1)
    original_bonds = _bonds(store, {"connectivity": {"kind": "pdb_conect", "sidecar_handle": None}},
                            original_rows, receptor.encode(), original["handle"])
    ligand_identity = {"model_number": 1, "chain_auth": "L", "chain_label": None,
                       "seq_auth": 1, "seq_label": None, "icode": "", "resname": "LIG"}
    req = {"schema": "chemical_prepare_request@1", "mode": "attach_existing",
           "complex_handle": complex_source.handle, "complex_model_number": 1,
           "selected_ligand": ligand_identity, "connectivity": {"kind": "sidecar", "sidecar_handle": None},
           "ligand_sdf_handle": ligand["handle"], "sdf_record_index": 0,
           "hydrogen_policy": "map_existing", "mapping": [], "terminal_extensions": [],
           "acknowledgement": _ack()}
    rows, _, _ = _source_rows(store, req)
    assert len(rows) == 5067
    sidecar = {"schema": "receptor_bonds@1", "source_handle": complex_source.handle, "complete": True,
               "bonds": [{"first": rows[a]["ref"], "second": rows[b]["ref"]} for a, b in original_bonds]}
    imported = import_raw(store, "receptor_bonds", "bonds.json", json.dumps(sidecar).encode())
    req["connectivity"]["sidecar_handle"] = imported["handle"]
    partial = preview(store, req)
    assert "ligand_mapping_incomplete" in {x["code"] for x in partial["blockers"]}
    req["mapping"] = [{"sdf_atom_index": i, "source_atom": rows[4988 + i]["ref"]}
                      for i in range(len(lig_atoms))]
    cap = preview(store, req)
    assert "selected SDF conformer coordinates" in cap["derived_coordinate_policy"]
    req["terminal_extensions"] = [{"residue": x["residue"], "atom_names": x["atom_names"],
                                    "approve_supplied_graph": True} for x in cap["terminal_extensions"]]
    assert preview(store, req, strict=True)["ready"]
    bad = json.loads(json.dumps(req))
    bad["mapping"][0]["source_atom"] = bad["mapping"][1]["source_atom"]
    with pytest.raises(ToolFailure):
        preview(store, bad, strict=True)
    selected = prepare_selected(store, req)
    assert len(selected["receptor_atoms"]) == 4988 and len(selected["receptor_bonds"]) == 5053
    prepared = _run_worker(tmp_path, "prolif_prepare_v1", selected)
    duplicate_provenance = json.loads(json.dumps(selected))
    duplicate_provenance["attached_source_sites"][1] = duplicate_provenance["attached_source_sites"][0]
    with pytest.raises(ValueError, match="provenance incomplete"):
        publish_prepare(SimpleNamespace(store=store), {"selected": duplicate_provenance},
                        "attempt_duplicate_provenance", prepared)
    manifest, source, graph = publish_prepare(SimpleNamespace(store=store),
                                              {"selected": selected}, "attempt_attach", prepared)
    assert validated_graph(store, graph)["manifest_handle"] == manifest
    actual_source = validated_source(store, source)
    assert actual_source["atoms"][4988]["ref"]["residue"] == ligand_identity
    assert actual_source["atoms"][4988]["ref"]["atom_name"] == "X1"
    assert actual_source["atoms"][4988]["protein"] is False
    assert actual_source["atoms"][4988]["ref"]["residue"]["chain_label"] is None
    block = __import__("gemmi").cif.read_string(actual_source["text"]).sole_block()
    category = block.get_mmcif_category("_atom_site.")
    assert category["label_asym_id"][4988].startswith("PV")
    saved_manifest = store.load(manifest)
    assert saved_manifest["attached_source_sites"][0]["source_atom"]["atom_name"] == "X1"
    assert saved_manifest["attached_source_sites"][0]["discrepancy_A"] <= .002
    assert "selected SDF conformer coordinates" in saved_manifest["derived_coordinate_policy"]
    replace_req = json.loads(json.dumps(req))
    replace_req["hydrogen_policy"] = "replace_from_sdf"
    replace_req["mapping"] = [entry for entry in req["mapping"]
                              if lig_atoms[entry["sdf_atom_index"]]["element"] != "H"]
    replaced = preview(store, replace_req, strict=True)
    assert len(replaced["excluded_original_ligand_hydrogens"]) == sum(
        atom["element"] == "H" for atom in lig_atoms)

    # A source with one additional heavy ligand site must fail even though
    # every SDF index is still mapped. This is the reverse side of the bijection.
    extra = (f'HETATM{5068:5d} {"EX1":<4s} LIG L   1    '
             f'{0.0:8.3f}{0.0:8.3f}{0.0:8.3f}{1.00:6.2f}{0.00:6.2f}'
             '          C  ')
    expanded = combined.replace(b"END\n", (extra + "\nEND\n").encode())
    extra_source = store.put("structure_source", "structure_source@1", expanded, fmt="pdb")
    extra_complex = store.put("structure", "structure_selection@2",
                              {"source": extra_source.handle, "format": "pdb", "model_index": 0})
    extra_req = json.loads(json.dumps(req))
    extra_req["complex_handle"] = extra_complex.handle
    extra_rows, _, _ = _source_rows(store, extra_req)
    extra_sidecar = {"schema": "receptor_bonds@1", "source_handle": extra_complex.handle,
                     "complete": True,
                     "bonds": [{"first": extra_rows[a]["ref"], "second": extra_rows[b]["ref"]}
                               for a, b in original_bonds]}
    extra_import = import_raw(store, "receptor_bonds", "extra-bonds.json",
                              json.dumps(extra_sidecar).encode())
    extra_req["connectivity"]["sidecar_handle"] = extra_import["handle"]
    extra_req["mapping"] = [{"sdf_atom_index": i, "source_atom": extra_rows[4988 + i]["ref"]}
                            for i in range(len(lig_atoms))]
    mismatch = preview(store, extra_req)
    assert "ligand_source_inventory_mismatch" in {item["code"] for item in mismatch["blockers"]}


def test_chemical_view_preserves_quoted_and_blank_authoritative_identifiers(tmp_path: Path) -> None:
    store = _store(tmp_path, "quoted")
    first = {"model_number": 2, "chain_auth": "", "chain_label": None, "seq_auth": 42,
             "seq_label": None, "icode": "A", "resname": "ALA"}
    second = {"model_number": 2, "chain_auth": "A B", "chain_label": "L B", "seq_auth": 43,
              "seq_label": 17, "icode": "B", "resname": "ASP"}
    local = [{"local_site_index": 0, "residue": first, "atom_name": "C A", "altloc": "",
              "element": "C", "coordinate_A": [1.23456789, 2.0, 3.0], "protein": True,
              "viewer_source_index": 0},
             {"local_site_index": 1, "residue": second, "atom_name": "O'1", "altloc": "",
              "element": "O", "coordinate_A": [4.0, 5.0, 6.0], "protein": True,
              "viewer_source_index": 1}]
    # A valid synthetic connected explicit-H ligand supplies an exact raw SDF
    # and a zero-center stereo audit. This exercises the complete source reader,
    # including provenance, rather than only the mmCIF serializer.
    methane = [(0.0, 0.0, 0.0, "C"), (0.63, 0.63, 0.63, "H"),
               (-0.63, -0.63, 0.63, "H"), (-0.63, 0.63, -0.63, "H"),
               (0.63, -0.63, -0.63, "H")]
    sdf_lines = ["SYNTHETIC METHANE", " " * 20 + "3D", "",
                 "  5  4  0  0  0  0            999 V2000"]
    sdf_lines += [f"{x:10.4f}{y:10.4f}{z:10.4f} {element:<3s} 0  0  0  0  0  0  0  0  0  0  0  0"
                  for x, y, z, element in methane]
    sdf_lines += [f"{1:3d}{index:3d}{1:3d}  0  0  0  0" for index in range(2, 6)]
    sdf_lines += ["M  END", "$$$$", ""]
    sdf_raw = "\n".join(sdf_lines).encode()
    sdf_import = import_raw(store, "ligand_sdf", "synthetic-methane.sdf", sdf_raw)
    record = _sdf_records(sdf_raw.decode())[0]
    assert len(record["atoms"]) == 5 and all(atom["declared_parity"] not in {1, 2}
                                              for atom in record["atoms"])
    ligand_residue = {"model_number": 2, "chain_auth": "L", "chain_label": "L", "seq_auth": 1,
                      "seq_label": 1, "icode": "", "resname": "LIG"}
    for atom in record["atoms"]:
        index = len(local)
        local.append({"local_site_index": index, "residue": ligand_residue,
                      "atom_name": atom["atom_name"], "altloc": "", "element": atom["element"],
                      "coordinate_A": atom["coordinate_A"], "protein": False,
                      "viewer_source_index": index})
    labels = _generated_label_asym(local)
    assert labels == {"": "PV1"}
    manifest = {"schema": "chemical_preparation_manifest@1", "model_number": 2,
                "generated_label_asym_by_auth_chain": labels,
                "ligand_sdf_handle": sdf_import["handle"], "request": {"sdf_record_index": 0},
                "receptor_local_sites": [first, second], "stereochemistry_audit": []}
    manifest_handle = store.put("chemical_preparation_manifest", "chemical_preparation_manifest@1", manifest)
    viewed = [{"ref": {"structure_handle": "LOCAL", "residue": x["residue"],
                       "atom_name": x["atom_name"], "altloc": "", "element": x["element"],
                       "site_index": i}, "coordinate_A": x["coordinate_A"],
              "protein": x["protein"]}
              for i, x in enumerate(local)]
    text = _cif_rows(viewed[:2], viewed[2:], 2, labels)
    source_payload = {"schema": "chemical_structure@1", "manifest_handle": manifest_handle.handle,
                      "manifest_sha256": hashlib.sha256(canonical_json(manifest)).hexdigest(),
                      "model_number": 2, "format": "mmcif", "text": text,
                      "viewer_source_sha256": hashlib.sha256(text.encode()).hexdigest(), "atoms": local}
    source = store.put("chemical_structure", "chemical_structure@1", source_payload)
    checked = validated_source(store, source.handle)
    assert [row["ref"]["residue"] for row in checked["atoms"][:2]] == [first, second]
    assert [row["ref"]["atom_name"] for row in checked["atoms"][:2]] == ["C A", "O'1"]
    assert len(checked["atoms"]) == 7
    import gemmi
    block = gemmi.cif.read_string(text).sole_block()
    cols = block.get_mmcif_category("_atom_site.")
    assert all(_cif_row_matches(cols, i, row, labels, 2) for i, row in enumerate(local))
    assert cols["auth_asym_id"][:2] == ["", "A B"]
    assert cols["label_asym_id"][:2] == ["PV1", "L B"]
    assert cols["auth_atom_id"][:2] == ["C A", "O'1"]
    assert cols["pdbx_PDB_ins_code"][:2] == ["A", "B"]
    assert gemmi.make_structure_from_block(block)[0].count_atom_sites() == 7


def test_worker_denies_python_socket_egress_before_chemistry_import() -> None:
    code = ("import runpy,socket; runpy.run_path(" + repr(str(WORKER)) + "); "
            "assert all(_blocked(fn) for fn in "
            "[lambda: socket.create_connection(('127.0.0.1',9)), "
            "lambda: socket.getaddrinfo('example.invalid',443), "
            "lambda: socket.socket().connect(('127.0.0.1',9))])")
    # Define the assertion helper before executing the worker module.
    code = ("def _blocked(fn):\n"
            "  try: fn()\n"
            "  except PermissionError: return True\n"
            "  return False\n" + code)
    proc = subprocess.run([str(WORKER_PYTHON), "-I", "-c", code], capture_output=True,
                          timeout=10, check=False,
                          env={"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1"})
    assert proc.returncode == 0, proc.stderr[-1000:]


def test_preflight_rejects_incomplete_backbone_and_histidine_alias(tmp_path: Path) -> None:
    store = _store(tmp_path, "chemistry_negative")
    req = _create(store)
    raw = (FIXTURES / "prolif-vina-rec.pdb").read_bytes()
    rows = receptor_atoms(store, req["receptor_input_handle"], 1)
    bonds = _bonds(store, req, rows, raw, req["receptor_input_handle"])
    by_name = {row["ref"]["atom_name"]: i for i, row in enumerate(rows)
               if row["ref"]["residue"]["seq_auth"] == 39 and row["ref"]["residue"]["chain_auth"] == "A"}
    backbone = {by_name["N"], by_name["CA"]}
    truncated = [pair for pair in bonds if set(pair) != backbone]
    assert "missing_backbone_bond" in {x["code"] for x in _protein_graph_blockers(rows, truncated, None)}
    mutated = raw.replace(b"HSD A 139", b"HSE A 139")
    assert mutated != raw
    changed = import_raw(store, "receptor", "wrong-histidine.pdb", mutated)
    req["receptor_input_handle"] = changed["handle"]
    result = preview(store, req)
    assert "histidine_alias_graph" in {x["code"] for x in result["blockers"]}
    with pytest.raises(ToolFailure):
        preview(store, req, strict=True)


def test_custom_terminal_cap_uses_exact_graph_and_h_vertices_not_name_template(tmp_path: Path) -> None:
    """The public N-terminal cap graph survives synthetic atom-name renaming."""
    store = _store(tmp_path, "custom_cap")
    req = _create(store)
    rename = {"CAY": "CZA", "CY": "CZX", "OY": "OZX",
              "HY1": "Q1", "HY2": "Q2", "HY3": "Q3"}
    original = (FIXTURES / "prolif-vina-rec.pdb").read_text()
    lines = []
    for line in original.splitlines():
        if (line.startswith(("ATOM", "HETATM")) and line[21] == "A" and
                line[22:26].strip() == "38" and line[12:16].strip() in rename):
            line = line[:12] + f"{rename[line[12:16].strip()]:<4s}" + line[16:]
        lines.append(line)
    changed = import_raw(store, "receptor", "custom-cap.pdb", ("\n".join(lines) + "\n").encode())
    req["receptor_input_handle"] = changed["handle"]
    first = next(item for item in req["terminal_extensions"] if item["residue"]["chain_auth"] == "A")
    first["atom_names"] = ["CZA", "CZX", "OZX"]
    check = preview(store, req, strict=True)
    assert check["ready"]
    extension = next(item for item in check["terminal_extensions"]
                     if item["residue"]["chain_auth"] == "A")
    assert extension["terminal_anchor"] == "N"
    assert len(extension["attachment_bonds"]) == 1
    assert {x["atom_name"] for x in extension["resolved_atoms"]} == {
        "CZA", "CZX", "OZX", "Q1", "Q2", "Q3"}
    selected = prepare_selected(store, req)
    prepared = _run_worker(tmp_path / "custom_native", "prolif_prepare_v1", selected)
    manifest, _, graph = publish_prepare(SimpleNamespace(store=store),
                                         {"selected": selected}, "attempt_custom_cap", prepared)
    assert validated_graph(store, graph)["manifest_handle"] == manifest
    assert store.load(manifest)["terminal_extension_inventory"] == check["terminal_extensions"]
    invalid_req = json.loads(json.dumps(req))
    invalid_req["terminal_extensions"].append(
        {"residue": next(x["ref"]["residue"] for x in receptor_atoms(store, changed["handle"], 1)
                         if x["ref"]["residue"]["chain_auth"] == "A" and
                         x["ref"]["residue"]["seq_auth"] == 39),
         "atom_names": ["CB"], "approve_supplied_graph": True})
    with pytest.raises(ToolFailure):
        preview(store, invalid_req)


def test_v2000_only_and_isotope_radical_input_rejection(tmp_path: Path) -> None:
    store = _store(tmp_path, "sdf_negative")
    raw = (FIXTURES / "prolif-vina-output.sdf").read_text()
    variants = {"v3000": raw.replace("V2000", "V3000", 1)}
    for label, start, stop, value in (("isotope", 34, 36, " 1"), ("radical", 36, 39, "  4")):
        lines = raw.splitlines(keepends=True)
        atom = lines[4]
        lines[4] = atom[:start] + value + atom[stop:]
        variants[label] = "".join(lines)
    for label, mutated in variants.items():
        with pytest.raises(ToolFailure):
            import_raw(store, "ligand_sdf", f"{label}.sdf", mutated.encode())


def test_preview_passes_but_native_rejects_synthetic_pentavalent_carbon(tmp_path: Path) -> None:
    store = _store(tmp_path, "valence_negative")
    req = _create(store)
    raw = (FIXTURES / "synthetic-pentavalent-carbon.sdf").read_bytes()
    imported = import_raw(store, "ligand_sdf", "synthetic-pentavalent-carbon.sdf", raw)
    req["ligand_sdf_handle"] = imported["handle"]
    assert preview(store, req, strict=True)["ready"]  # preflight is not an RDKit chemistry claim
    selected = prepare_selected(store, req)
    error = _run_worker_failure(tmp_path / "valence_worker", "prolif_prepare_v1", selected)
    assert error["schema"] == "chemical_worker_error@1"
    assert error["error_class"] == "input_invalid"
    assert error["reason_code"] == "ligand_chemistry_invalid"
    assert not any(store.meta(handle)["kind"] == "chemical_graph" for handle in store.handles())


@pytest.mark.parametrize("filename,reason", [
    ("synthetic-disconnected-methane-water.sdf", "ligand_disconnected"),
    ("synthetic-atrop-biaryl.sdf", "stereo_unsupported"),
])
def test_native_rejects_disconnected_or_atrop_ligand(tmp_path: Path, filename: str, reason: str) -> None:
    store = _store(tmp_path, reason)
    req = _create(store)
    imported = import_raw(store, "ligand_sdf", filename, (FIXTURES / filename).read_bytes())
    req["ligand_sdf_handle"] = imported["handle"]
    assert preview(store, req, strict=True)["ready"]
    selected = prepare_selected(store, req)
    before = store.handles()
    error = _run_worker_failure(tmp_path / reason, "prolif_prepare_v1", selected)
    assert error["schema"] == "chemical_worker_error@1"
    assert error["error_class"] == "input_invalid" and error["reason_code"] == reason
    assert error["sdf_atom_indices"] and store.handles() == before


def test_native_receptor_h_valence_and_zero_bond_diagnostics(tmp_path: Path) -> None:
    """Staged supplied graph faults identify exact immutable receptor sites."""
    store = _store(tmp_path, "receptor_diagnostic")
    selected = prepare_selected(store, _create(store))
    atoms = selected["receptor_atoms"]
    h_indices = [i for i, atom in enumerate(atoms) if atom["element"].upper() == "H"]
    first_h, second_h = h_indices[:2]
    first_bond = next(pair for pair in selected["receptor_bonds"] if first_h in pair)
    first_heavy = next(i for i in first_bond if i != first_h)
    before = store.handles()

    double_h = json.loads(json.dumps(selected))
    double_h["receptor_bonds"].append([first_h, second_h])
    error = _run_worker_failure(tmp_path / "double_h", "prolif_prepare_v1", double_h)
    assert error["reason_code"] == "receptor_graph_invalid"
    assert atoms[first_h]["source_ref"] in error["source_atoms"]
    assert atoms[second_h]["source_ref"] in error["source_atoms"]
    assert error["source_residues"]

    zero = json.loads(json.dumps(selected))
    zero["receptor_atoms"][first_h]["coordinate_A"] = atoms[first_heavy]["coordinate_A"][:]
    error = _run_worker_failure(tmp_path / "zero_vector", "prolif_prepare_v1", zero)
    assert error["reason_code"] == "receptor_graph_invalid"
    assert error["source_atoms"] == [atoms[min(first_h, first_heavy)]["source_ref"],
                                     atoms[max(first_h, first_heavy)]["source_ref"]]
    assert store.handles() == before


def test_native_ligand_zero_bond_diagnostic_uses_exact_sdf_indices(tmp_path: Path) -> None:
    store = _store(tmp_path, "ligand_zero_vector")
    req = _create(store)
    raw = (FIXTURES / "prolif-vina-output.sdf").read_text()
    record = _sdf_records(raw)[0]
    first, second, _ = next((a, b, order) for a, b, order in record["bonds"]
                            if ((record["atoms"][a]["element"] == "H" and
                                 record["atoms"][b]["declared_parity"] not in {1, 2}) or
                                (record["atoms"][b]["element"] == "H" and
                                 record["atoms"][a]["declared_parity"] not in {1, 2})))
    lines = raw.splitlines(keepends=True)
    assert lines[4 + first][:30] != lines[4 + second][:30]
    lines[4 + second] = lines[4 + first][:30] + lines[4 + second][30:]
    changed = import_raw(store, "ligand_sdf", "synthetic-zero-bond.sdf", "".join(lines).encode())
    req["ligand_sdf_handle"] = changed["handle"]
    assert preview(store, req, strict=True)["ready"]
    selected = prepare_selected(store, req)
    before = store.handles()
    error = _run_worker_failure(tmp_path, "prolif_prepare_v1", selected)
    assert error["reason_code"] == "ligand_graph_invalid"
    assert error["sdf_atom_indices"] == [first, second]
    assert store.handles() == before


def test_native_graph_derived_doubly_protonated_histidine(tmp_path: Path) -> None:
    """A labeled synthetic HSP variant must pass the real native inference path."""
    store = _store(tmp_path, "synthetic_hsp")
    selected = prepare_selected(store, _create(store))
    hsd = next(atom["source_ref"]["residue"] for atom in selected["receptor_atoms"]
               if atom["source_ref"]["residue"]["resname"] == "HSD")
    indices = [i for i, atom in enumerate(selected["receptor_atoms"])
               if atom["source_ref"]["residue"] == hsd]
    by_name = {selected["receptor_atoms"][i]["source_ref"]["atom_name"]: i for i in indices}
    ne2 = selected["receptor_atoms"][by_name["NE2"]]["coordinate_A"]
    ce1 = selected["receptor_atoms"][by_name["CE1"]]["coordinate_A"]
    cd2 = selected["receptor_atoms"][by_name["CD2"]]["coordinate_A"]
    outward = [ne2[axis] - (ce1[axis] + cd2[axis]) / 2 for axis in range(3)]
    length = math.sqrt(sum(value * value for value in outward))
    assert length > .5
    for i in indices:
        selected["receptor_atoms"][i]["source_ref"]["residue"]["resname"] = "HSP"
    h_ref = json.loads(json.dumps(selected["receptor_atoms"][by_name["NE2"]]["source_ref"]))
    h_ref["atom_name"] = "SYNTHETIC_H_NE2"
    h_ref["element"] = "H"
    h_ref["site_index"] = max(atom["source_ref"]["site_index"]
                              for atom in selected["receptor_atoms"]) + 1
    new_native_index = len(selected["receptor_atoms"])
    selected["receptor_atoms"].append(
        {"source_ref": h_ref,
         "coordinate_A": [ne2[axis] + outward[axis] / length for axis in range(3)],
         "element": "H"})
    selected["receptor_bonds"].append([by_name["NE2"], new_native_index])
    prepared = _run_worker(tmp_path, "prolif_prepare_v1", selected)
    state = next(item for item in prepared["histidine_states"]
                 if item["residue"]["chain_auth"] == hsd["chain_auth"] and
                 item["residue"]["seq_auth"] == hsd["seq_auth"])
    assert state["represented_state"] == "cationic_ND1_NE2_H"
    assert state["ring_h_sites"] == ["ND1", "NE2"]
    assert state["ring_formal_charge"] == 1


@pytest.mark.parametrize(("element", "bond_length"), [("Cl", 1.8), ("Br", 1.95)])
def test_v2000_supplied_alias_and_halogen_identity_in_native_source(
    tmp_path: Path, element: str, bond_length: float,
) -> None:
    """Synthetic CH3-halogen tests full alias and uppercase AtomRef convention."""
    store = _store(tmp_path, f"halogen_{element}")
    req = _create(store)
    atoms = [(0.0, 0.0, 0.0, "C"), (bond_length, 0.0, 0.0, element),
             (-.36, 1.03, 0.0, "H"), (-.36, -.515, .892, "H"),
             (-.36, -.515, -.892, "H")]
    lines = [f"SYNTHETIC METHYL {element.upper()}", " " * 20 + "3D", "",
             "  5  4  0  0  0  0            999 V2000"]
    lines += [f"{x:10.4f}{y:10.4f}{z:10.4f} {symbol:<3s} 0  0  0  0  0  0  0  0  0  0  0  0"
              for x, y, z, symbol in atoms]
    lines += [f"{a:3d}{b:3d}{1:3d}  0  0  0  0" for a, b in ((1, 2), (1, 3), (1, 4), (1, 5))]
    alias = f"{element.upper()}_ALIAS_LONG"
    lines += ["A    2", alias, "M  END", "$$$$", ""]
    raw = "\n".join(lines).encode()
    parsed = _sdf_records(raw.decode())[0]
    assert parsed["atoms"][1]["atom_name"] == alias
    assert parsed["atoms"][1]["name_generated"] is False
    assert parsed["atoms"][1]["element"] == element.upper()
    imported = import_raw(store, "ligand_sdf", f"synthetic-{element.lower()}.sdf", raw)
    req["ligand_sdf_handle"] = imported["handle"]
    selected = prepare_selected(store, req)
    prepared = _run_worker(tmp_path / "native", "prolif_prepare_v1", selected)
    assert prepared["ligand_atoms"][1]["atom_name"] == alias
    assert prepared["ligand_atoms"][1]["element"] == element.upper()
    _, source, graph = publish_prepare(SimpleNamespace(store=store),
                                       {"selected": selected}, "attempt_synthetic_halogen", prepared)
    assert validated_graph(store, graph)["ligand_atoms"][1]["ref"]["element"] == element.upper()
    viewed = validated_source(store, source)
    row = viewed["atoms"][4989]
    assert row["ref"]["element"] == element.upper() and row["ref"]["atom_name"] == alias
    category = __import__("gemmi").cif.read_string(viewed["text"]).sole_block().get_mmcif_category("_atom_site.")
    assert category["type_symbol"][4989] == element.upper()


def test_native_valid_empty_after_ligand_translation(tmp_path: Path) -> None:
    store = _store(tmp_path, "empty")
    req = _create(store)
    original = store.load(req["ligand_sdf_handle"]).decode()
    records = original.split("$$$$")
    first_lines = records[0].splitlines()
    count = int(first_lines[3][0:3])
    for i in range(4, 4 + count):
        line = first_lines[i]
        shifted = [float(line[j:j + 10]) + 1000.0 for j in (0, 10, 20)]
        first_lines[i] = "".join(f"{x:10.4f}" for x in shifted) + line[30:]
    records[0] = "\n".join(first_lines) + "\n"
    shifted_sdf = "$$$$".join(records).encode()
    moved = import_raw(store, "ligand_sdf", "moved.sdf", shifted_sdf)
    req["ligand_sdf_handle"] = moved["handle"]
    selected = prepare_selected(store, req)
    prepared = _run_worker(tmp_path, "prolif_prepare_v1", selected)
    _, _, graph = publish_prepare(SimpleNamespace(store=store),
                                  {"selected": selected}, "attempt_shifted", prepared)
    detect_input = detect_selected(store, {"schema": "chemical_detect_request@1", "graph_handle": graph,
                                           "categories": ["HBDonor", "HBAcceptor", "Hydrophobic",
                                                          "Cationic", "Anionic"]})
    detected = _run_worker(tmp_path, "prolif_detect_v1", detect_input)
    assert detected["native_total"] == 0 and detected["null_result"] is True
    handle = publish_detect(SimpleNamespace(store=store), {"selected": detect_input},
                            "attempt_shifted_detect", detected)[0]
    assert validated_result(store, handle)["rows"] == []
    assert store.meta(handle)["null_result"] is True


def test_synthetic_acetate_anion_uses_native_reverse_ionic_roles(tmp_path: Path) -> None:
    """Analytic charged ligand near a public lysine; no observed binding claim."""
    store = _store(tmp_path, "anionic")
    req = _create(store)
    receptor = receptor_atoms(store, req["receptor_input_handle"], 1)
    target = next(row for row in receptor if row["ref"]["residue"]["resname"] == "LYS" and
                  row["ref"]["atom_name"] == "NZ")
    x, y, z = target["coordinate_A"]
    coordinates = [(x, y, z + 5.77, "C"), (x, y, z + 4.27, "C"),
                   (x - 1.23, y, z + 4.27, "O"), (x, y, z + 3.0, "O"),
                   (x + 1.0, y, z + 6.20, "H"), (x - .5, y + .87, z + 6.20, "H"),
                   (x - .5, y - .87, z + 6.20, "H")]
    lines = ["SYNTHETIC ACETATE ANION", " " * 20 + "3D", "",
             "  7  6  0  0  0  0            999 V2000"]
    lines += [f"{a:10.4f}{b:10.4f}{c:10.4f} {element:<3s} 0  0  0  0  0  0  0  0  0  0  0  0"
              for a, b, c, element in coordinates]
    lines += [f"{a:3d}{b:3d}{order:3d}  0  0  0  0" for a, b, order in
              ((1, 2, 1), (2, 3, 2), (2, 4, 1), (1, 5, 1), (1, 6, 1), (1, 7, 1))]
    lines += ["M  CHG  1   4  -1", "M  END", "$$$$", ""]
    raw = "\n".join(lines).encode()
    parsed = _sdf_records(raw.decode())[0]
    assert parsed["has_3d"] and parsed["atoms"][3]["formal_charge"] == -1
    imported = import_raw(store, "ligand_sdf", "analytic-acetate.sdf", raw)
    req["ligand_sdf_handle"] = imported["handle"]
    selected = prepare_selected(store, req)
    prepared = _run_worker(tmp_path / "synthetic_prepare", "prolif_prepare_v1", selected)
    assert prepared["ligand_atoms"][3]["formal_charge"] == -1
    _, _, graph_handle = publish_prepare(SimpleNamespace(store=store),
                                         {"selected": selected}, "attempt_synthetic_anion", prepared)
    detect_input = detect_selected(store, {"schema": "chemical_detect_request@1", "graph_handle": graph_handle,
                                           "categories": ["HBDonor", "HBAcceptor", "Hydrophobic",
                                                          "Cationic", "Anionic"]})
    native = _run_worker(tmp_path / "synthetic_detect", "prolif_detect_v1", detect_input)
    assert any(row["category"] == "Anionic" for row in native["native_rows"])
    handle = publish_detect(SimpleNamespace(store=store), {"selected": detect_input},
                            "attempt_synthetic_anion_detect", native)[0]
    result = validated_result(store, handle)
    rows = [row for row in result["rows"] if row["category"] == "Anionic" and
            row["roles"]["anion_site"]["site_index"] == len(receptor) + 3 and
            row["roles"]["cation_site"]["site_index"] == target["ref"]["site_index"]]
    assert rows, "native ProLIF did not assign the constructed opposite-charge pair"
    assignment = rows[0]
    assert assignment["roles"]["anion_site"]["element"] == "O"
    assert assignment["roles"]["cation_site"]["atom_name"] == "NZ"
    assert assignment["distance_roles"] == ["cation_site", "anion_site"]
    assert abs(assignment["distance_A"] - 3.0) < 1e-4


def test_native_public_geometry_on_both_sides_of_fixed_distance_cutoffs(tmp_path: Path) -> None:
    """Move an entire ligand rigidly; the native engine decides boundary inclusion.

    The public coordinates and graph are real, but each translated pose is a
    labeled analytic derivative, not an observed binding pose.
    """
    store = _store(tmp_path, "boundary")
    selected = prepare_selected(store, _create(store))
    prepared = _run_worker(tmp_path / "prepare", "prolif_prepare_v1", selected)
    _, _, graph_handle = publish_prepare(SimpleNamespace(store=store),
                                         {"selected": selected}, "attempt_boundary", prepared)
    base = detect_selected(store, {"schema": "chemical_detect_request@1", "graph_handle": graph_handle,
                                   "categories": ["HBDonor", "HBAcceptor", "Hydrophobic",
                                                  "Cationic", "Anionic"]})
    cases = [("HBDonor", 20, 1489, 3.49, True),
             ("HBDonor", 20, 1489, 3.51, False),
             ("Hydrophobic", 24, 4004, 4.49, True),
             ("Hydrophobic", 24, 4004, 4.51, False)]
    for iteration, (category, ligand_index, receptor_index, target, expected) in enumerate(cases):
        payload = json.loads(json.dumps(base))
        ligand = payload["graph"]["ligand_atoms"]
        receptor = payload["graph"]["receptor_atoms"]
        start = ligand[ligand_index]["engine_coordinate_A"]
        fixed = receptor[receptor_index]["engine_coordinate_A"]
        distance = math.dist(start, fixed)
        direction = [(a - b) / distance for a, b in zip(start, fixed, strict=True)]
        shift = [(target - distance) * component for component in direction]
        for row in ligand:
            for field in ("coordinate_A", "engine_coordinate_A"):
                row[field] = [a + b for a, b in zip(row[field], shift, strict=True)]
        assert abs(math.dist(ligand[ligand_index]["engine_coordinate_A"], fixed) - target) < 1e-10
        native = _run_worker(tmp_path / f"case{iteration}", "prolif_detect_v1", payload)
        matching = [row for row in native["native_rows"] if row["category"] == category and
                    ligand_index in row["parent_indices"]["ligand"] and
                    receptor_index in row["parent_indices"]["protein"]]
        assert bool(matching) is expected, (category, target, matching)


def test_native_bent_donor_hydrogen_rejects_short_donor_acceptor_pair(tmp_path: Path) -> None:
    """An analytic derivative keeps D-A short but bends D-H-A below 130 degrees."""
    store = _store(tmp_path, "bent")
    selected = prepare_selected(store, _create(store))
    prepared = _run_worker(tmp_path / "prepare", "prolif_prepare_v1", selected)
    _, _, graph_handle = publish_prepare(SimpleNamespace(store=store),
                                         {"selected": selected}, "attempt_bent", prepared)
    base = detect_selected(store, {"schema": "chemical_detect_request@1", "graph_handle": graph_handle,
                                   "categories": ["HBDonor", "HBAcceptor", "Hydrophobic",
                                                  "Cationic", "Anionic"]})
    straight = _run_worker(tmp_path / "straight", "prolif_detect_v1", base)
    def pair(rows: list[dict]) -> list[dict]:
        return [row for row in rows if row["category"] == "HBDonor" and
                row["parent_indices"]["ligand"] == [20, 58] and
                row["parent_indices"]["protein"] == [1489]]
    assert pair(straight["native_rows"])
    bent = json.loads(json.dumps(base))
    ligand = bent["graph"]["ligand_atoms"]
    receptor = bent["graph"]["receptor_atoms"]
    theta = .75
    for field in ("coordinate_A", "engine_coordinate_A"):
        donor = ligand[20][field]
        old_h = ligand[58][field]
        acceptor = receptor[1489][field]
        radius = math.dist(donor, old_h)
        da = math.dist(donor, acceptor)
        direction = [(a - d) / da for d, a in zip(donor, acceptor, strict=True)]
        old_direction = [(h - d) / radius for d, h in zip(donor, old_h, strict=True)]
        projection = sum(a * b for a, b in zip(direction, old_direction, strict=True))
        transverse = [a - projection * b for a, b in zip(old_direction, direction, strict=True)]
        length = math.sqrt(sum(x * x for x in transverse))
        assert length > .01
        ligand[58][field] = [d + radius * (math.cos(theta) * e + math.sin(theta) * f / length)
                             for d, e, f in zip(donor, direction, transverse, strict=True)]
    d = ligand[20]["engine_coordinate_A"]
    h = ligand[58]["engine_coordinate_A"]
    a = receptor[1489]["engine_coordinate_A"]
    angle = math.degrees(math.acos(sum((x - y) * (z - y)
                                       for x, y, z in zip(d, h, a, strict=True)) /
                                   (math.dist(d, h) * math.dist(a, h))))
    assert math.dist(d, a) < 3.5 and angle < 130
    native = _run_worker(tmp_path / "bent", "prolif_detect_v1", bent)
    assert not pair(native["native_rows"])


def test_declared_v2000_tetrahedral_parity_vs_3d_and_wedge_rule(tmp_path: Path) -> None:
    """A real parity contradiction fails; a flipped 3D wedge is only a depiction cue."""
    store = _store(tmp_path, "stereo")
    req = _create(store)
    public = (FIXTURES / "prolif-vina-output.sdf").read_text()
    lines = public.splitlines(keepends=True)
    assert lines[4][39:42] == "  2"  # selected record atom 0 has declared tetrahedral parity
    reversed_parity = lines.copy()
    reversed_parity[4] = lines[4][:39] + "  1" + lines[4][42:]
    parity_import = import_raw(store, "ligand_sdf", "parity-reversed.sdf",
                               "".join(reversed_parity).encode())
    parity_request = json.loads(json.dumps(req))
    parity_request["ligand_sdf_handle"] = parity_import["handle"]
    assert preview(store, parity_request, strict=True)["ready"]
    parity_failure = _run_worker_failure(tmp_path / "parity", "prolif_prepare_v1",
                                         prepare_selected(store, parity_request))
    assert parity_failure["reason_code"] == "stereo_conflict"
    assert "tetrahedral parity contradicts" in parity_failure["message"]

    wedge = lines.copy()
    first_bond = 4 + 79 + 3
    assert lines[first_bond][9:12] == "  6"
    wedge[first_bond] = lines[first_bond][:9] + "  1" + lines[first_bond][12:]
    wedge_import = import_raw(store, "ligand_sdf", "wedge-reversed.sdf", "".join(wedge).encode())
    wedge_request = json.loads(json.dumps(req))
    wedge_request["ligand_sdf_handle"] = wedge_import["handle"]
    assert preview(store, wedge_request, strict=True)["ready"]
    wedge_prepared = _run_worker(tmp_path / "wedge", "prolif_prepare_v1",
                                 prepare_selected(store, wedge_request))
    assert wedge_prepared["ligand_atom_count"] == 79

    ambiguous = lines.copy()
    ambiguous[first_bond] = lines[first_bond][:9] + "  4" + lines[first_bond][12:]
    with pytest.raises(ToolFailure):
        import_raw(store, "ligand_sdf", "ambiguous-wedge.sdf", "".join(ambiguous).encode())
