"""Engine-free, strict validation of the fixed OpenMM evidence bundle.

This checks internal consistency and provenance, not experimental authenticity of
arbitrary mutually forged energies. It deliberately never imports OpenMM.
"""
from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from typing import Any

import gemmi

from .core.handles import canonical_json
from .tools.registry import ToolContext
from .tools.structural import _parse, _res_ref

# Frozen with the approved OpenMM 8.6.0 built-in force field dependency set.
# A changed XML distribution needs a new method version, not a trusted claim.
FORCEFIELD_SHA256 = {
    "amber14-all.xml": "96d635545c36ce248e37d23ea82fa05ce4d2e1a6a42cd6d0ec5db3cfe30ca44c",
    "amber14/protein.ff14SB.xml": "d9f9779c09d67cd5f8bc657692f174ffab14c469dfd06d560ac1899fa7e976b8",
    "amber14/DNA.OL15.xml": "200e7cd116481fb47ed50bfd29deefb84a1e488d73d262c3f3f278b36b80ffa5",
    "amber14/RNA.OL3.xml": "61b793a49ded3c9c3bd9fbab328bc1b20b2b4ce7bc2358d537892ca64b085127",
    "amber14/lipid17.xml": "f974506df14202973637cf5e1d094af5e6098eb04afd2b68c523589ffcf2e780",
    "implicit/gbn2.xml": "172fe56b43343e26f5483f55a276dbcf351b759f3abca2a12891778bf08e560b",
}


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def topology_sha256(atoms: list[dict], bonds: list[list[int]]) -> str:
    return _sha(json.dumps({"atoms": atoms, "bonds": bonds}, sort_keys=True, separators=(",", ":")).encode())


def _selected_source(store: Any, selected: dict) -> None:
    """Bind selected heavy atoms and exclusions to immutable prepared/source bytes."""
    prepared = store.load(selected["structure"])
    manifest = store.load(prepared["manifest"])
    original_meta = store.meta(manifest["input"])
    source_meta = store.meta(selected["source_handle"])
    prepared_coords_meta = store.meta(prepared["coordinates"])
    original = store.load(manifest["input"])
    _require((original_meta["kind"], original_meta["schema"]) == ("structure", "structure_selection@2") and
             (source_meta["kind"], source_meta["schema"]) == ("structure_source", "structure_source@1") and
             (prepared_coords_meta["kind"], prepared_coords_meta["schema"]) ==
             ("prepared_coordinates", "prepared_coordinates@1") and
             original["source"] == selected["source_handle"] and
             original["model_index"] == manifest["model_index"] == prepared["model_index"],
             "source selection type/model mismatch")
    _require(prepared["manifest"] == selected["preparation_manifest"] and
             manifest["source_handle"] == selected["source_handle"] and
             prepared["model_number"] == selected["model_number"], "prepared/source link mismatch")
    model = _parse(ToolContext(store=store, call_id="openmm_validate"), selected["structure"])[0]
    source = _parse(ToolContext(store=store, call_id="openmm_validate_source"), manifest["input"])[0]
    _require(model.num == source.num == selected["model_number"], "model identity mismatch")
    expected_protein: list[dict] = []
    expected_excluded: list[dict] = []
    if manifest["waters"] == "strip_all":
        for chain in source:
            for residue in chain:
                if residue.is_water():
                    expected_excluded.append({"residue": _res_ref(chain, residue, source.num),
                                              "atom_count": len(residue), "reason": "water_removed_during_preparation"})
    expected_removed: list[dict] = []
    if manifest["hydrogens"] == "strip":
        for chain in source:
            for residue in chain:
                if residue.het_flag != "A" and residue.label_seq is None:
                    continue
                ref = _res_ref(chain, residue, source.num)
                for atom in residue:
                    if atom.element.name in {"H", "D"}:
                        expected_removed.append({"residue": ref, "atom_name": atom.name,
                                                 "element": atom.element.name, "source_serial": atom.serial,
                                                 "coordinates_A": [atom.pos.x, atom.pos.y, atom.pos.z]})
    for chain in model:
        residues = []
        for residue in chain:
            ref = _res_ref(chain, residue, model.num)
            if residue.het_flag != "A" and residue.label_seq is None:
                expected_excluded.append({"residue": ref, "atom_count": len(residue),
                                          "reason": "water" if residue.is_water() else "nonprotein"})
                continue
            atoms = []
            for atom in residue:
                entry = {"residue": ref, "atom_name": atom.name.strip(), "element": atom.element.name,
                         "source_serial": atom.serial, "coordinates_A": [atom.pos.x, atom.pos.y, atom.pos.z]}
                if atom.element.name in {"H", "D"}:
                    expected_removed.append(entry)
                else:
                    atoms.append(entry)
            residues.append({"residue": ref, "atoms": atoms})
        if residues:
            expected_protein.append({"chain_auth": chain.name, "residues": residues})
    _require(selected["protein"] == expected_protein and selected["excluded"] == expected_excluded and
             selected["source_hydrogens_removed"] == expected_removed, "selected source/exclusion mismatch")
    _require(all(_integer(item["atom_count"]) for item in selected["excluded"]), "exclusion count invalid")
    count = sum(len(r["atoms"]) for c in expected_protein for r in c["residues"])
    _require(_integer(selected["heavy_atom_count"], 1) and selected["heavy_atom_count"] == count and
             _integer(selected["seed"]), "selected counts/seed mismatch")


def _cif(raw: str, mappings: list[dict], positions: list[list[float]], model_number: int) -> None:
    _require(isinstance(raw, str) and raw.startswith("data_"), "invalid coordinate CIF")
    parsed = gemmi.make_structure_from_block(gemmi.cif.read_string(raw).sole_block())
    _require(len(parsed) == 1 and parsed[0].num == model_number, "CIF model mismatch")
    atoms = [(chain, residue, atom) for chain in parsed[0] for residue in chain for atom in residue]
    _require(len(atoms) == len(mappings), "CIF atom count mismatch")
    for mapped, (chain, residue, atom), exact in zip(mappings, atoms, positions, strict=True):
        ref = _res_ref(chain, residue, parsed[0].num)
        _require(ref == mapped["residue"] and atom.name == mapped["atom_name"] and
                 atom.element.name == mapped["element"], "CIF atom identity mismatch")
        _require(all(abs(a - b) <= 0.001 for a, b in zip((atom.pos.x, atom.pos.y, atom.pos.z), exact, strict=True)),
                 "CIF coordinate mismatch")


PREPARATION_FIELDS = frozenset({"method", "selected_sha256", "input_cif", "input_positions_A",
                                "system_xml", "system_xml_sha256", "topology_sha256", "heavy_atoms",
                                "added_hydrogens", "atom_mapping", "residue_mapping", "source_bonds",
                                "final_bonds", "protonation_variants", "disulfide_bonds"})


def _preparation_shape(data: Any) -> None:
    """Reject malformed JSON containers before following checkpoint fields."""
    _require(isinstance(data, dict) and set(data) == PREPARATION_FIELDS | {"schema"},
             "preparation checkpoint fields invalid")
    _require(all(isinstance(data[name], str) for name in
                 ("schema", "selected_sha256", "input_cif", "system_xml",
                  "system_xml_sha256", "topology_sha256")), "preparation text field invalid")
    _require(isinstance(data["method"], dict) and
             all(isinstance(data[name], list) for name in
                 ("input_positions_A", "added_hydrogens", "atom_mapping", "residue_mapping",
                  "source_bonds", "final_bonds", "protonation_variants", "disulfide_bonds")),
             "preparation container invalid")
    _require(all(isinstance(atom, dict) and isinstance(atom.get("residue"), dict) and
                 isinstance(atom.get("atom_name"), str) and isinstance(atom.get("element"), str) and
                 isinstance(atom.get("chain_auth"), str) and
                 isinstance(atom.get("added_hydrogen"), bool) and
                 isinstance(atom.get("coordinates_A", []), list)
                 for atom in data["atom_mapping"]), "atom mapping shape invalid")
    _require(all(isinstance(atom, dict) for atom in data["added_hydrogens"]) and
             all(isinstance(residue, dict) and isinstance(residue.get("resname"), str)
                 for residue in data["residue_mapping"]) and
             all(variant is None or isinstance(variant, str) for variant in data["protonation_variants"]),
             "residue mapping shape invalid")
    _require(all(isinstance(pair, list) and len(pair) == 2 and all(_integer(v) for v in pair)
                 for name in ("source_bonds", "final_bonds", "disulfide_bonds") for pair in data[name]),
             "bond shape invalid")
    _require(all(isinstance(point, list) and len(point) == 3 and
                 all(type(value) in (int, float) and math.isfinite(value) for value in point)
                 for point in data["input_positions_A"]), "position shape invalid")


def validate_preparation(store: Any, selected: dict, data: dict, system_xml: bytes) -> None:
    """Validate complete pre-energy evidence without importing the engine."""
    _preparation_shape(data)
    _require(data["schema"] == "openmm_preparation_checkpoint@1" and
             set(data) == PREPARATION_FIELDS | {"schema"} and
             data["selected_sha256"] == _sha(canonical_json(selected)) and
             data["method"] == selected["method"] and data["system_xml"].encode() == system_xml,
             "scientific output identity mismatch")
    method = selected["method"]
    fixed = {"method_id": "openmm_protein_minimize_v1", "schema": "openmm_protein_minimization@1",
             "distribution_version": "8.6.0", "platform": "CPU", "platform_properties": {"Threads": "1"},
             "hydrogen_platform": "CPU", "hydrogen_platform_properties": {"Threads": "1"},
             "forcefield_files": ["amber14-all.xml", "implicit/gbn2.xml"], "nonbonded_method": "NoCutoff",
             "constraints": None, "pH": 7.0, "tolerance_kJ_mol_nm": 10.0, "max_iterations": 50,
             "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}
    _require(all(method.get(k) == v for k, v in fixed.items()) and
             isinstance(method.get("engine_build"), str) and method["engine_build"].startswith("8.6.0") and
             method.get("forcefield_files_sha256") == FORCEFIELD_SHA256,
             "fixed method mismatch")
    _selected_source(store, selected)
    _require(isinstance(system_xml, bytes) and _sha(system_xml) == data["system_xml_sha256"],
             "System XML hash mismatch")
    root = ET.fromstring(system_xml)
    _require(root.tag == "System", "invalid System XML")
    particle_nodes = root.find("Particles")
    _require(particle_nodes is not None, "System particles missing")
    mappings = data["atom_mapping"]
    n = len(mappings)
    _require(n > 0 and len(particle_nodes) == n and _integer(data["heavy_atoms"], 1) and
             data["heavy_atoms"] == selected["heavy_atom_count"] and
             len(data["added_hydrogens"]) == n - data["heavy_atoms"], "System/atom count mismatch")
    _require(root.find("Constraints") is not None and len(root.find("Constraints")) == 0,
             "fixed protocol forbids constraints")
    residues = [r["residue"] for c in selected["protein"] for r in c["residues"]]
    _require(data["residue_mapping"] == residues and len(data["protonation_variants"]) == len(residues),
             "residue mapping/variants mismatch")
    variants = {"HIS": {None, "HID", "HIE", "HIP"}, "CYS": {None, "CYS", "CYX"},
                "ASP": {None, "ASP", "ASH"}, "GLU": {None, "GLU", "GLH"},
                "LYS": {None, "LYS", "LYN"}, "TYR": {None, "TYR", "TYM"}}
    _require(all(v in variants.get(r["resname"], {None}) for r, v in
                 zip(residues, data["protonation_variants"], strict=True)), "invalid protonation variant")
    originals = [a for c in selected["protein"] for r in c["residues"] for a in r["atoms"]]
    heavy = []
    added = []
    atom_ids = set()
    residue_chain = [i for i, c in enumerate(selected["protein"]) for _ in c["residues"]]
    for index, atom in enumerate(mappings):
        ri = atom["residue_index"]
        _require(_integer(atom["topology_index"]) and atom["topology_index"] == index and
                 _integer(ri) and ri < len(residues) and atom["residue"] == residues[ri] and
                 _integer(atom["chain_index"]) and atom["chain_index"] == residue_chain[ri] and
                 atom["chain_auth"] == residues[ri]["chain_auth"], "atom/residue index mismatch")
        ident = (ri, atom["atom_name"])
        _require(ident not in atom_ids, "duplicate atom identity")
        atom_ids.add(ident)
        if atom["added_hydrogen"] is True:
            _require(atom["element"] == "H" and set(atom) == {"residue", "atom_name", "element", "topology_index",
                "chain_index", "chain_auth", "residue_index", "added_hydrogen"}, "added atom is not hydrogen")
            added.append(atom)
        else:
            _require(atom["added_hydrogen"] is False, "invalid added-hydrogen flag")
            heavy.append(atom)
    _require(added == data["added_hydrogens"] and len(heavy) == len(originals), "added/heavy mapping mismatch")
    for index, (mapped, source) in enumerate(zip(heavy, originals, strict=True)):
        _require({k: mapped[k] for k in source} == source and
                 mapped["residue_index"] == next(i for i, r in enumerate(residues) if r == source["residue"]),
                 f"source heavy atom mapping mismatch at {index}")
    _require(topology_sha256(mappings, data["final_bonds"]) == data["topology_sha256"],
             "topology hash mismatch")
    def bonds(name: str, limit: int) -> set[tuple[int, int]]:
        raw = data[name]
        _require(isinstance(raw, list) and bool(raw), f"{name} empty")
        edges = set()
        for pair in raw:
            _require(isinstance(pair, list) and len(pair) == 2 and all(_integer(v) and v < limit for v in pair)
                     and pair[0] != pair[1], f"{name} endpoint invalid")
            edge = tuple(sorted(pair))
            _require(edge not in edges, f"{name} duplicate bond")
            edges.add(edge)
        return edges
    source_edges = bonds("source_bonds", len(heavy))
    final_edges = bonds("final_bonds", n)
    forces = root.find("Forces")
    _require(forces is not None, "System forces missing")
    harmonic = [node for node in forces if node.attrib.get("type") == "HarmonicBondForce"]
    nonbonded = [node for node in forces if node.attrib.get("type") == "NonbondedForce"]
    gb = [node for node in forces if node.attrib.get("type") == "CustomGBForce"]
    _require(len(harmonic) == len(nonbonded) == len(gb) == 1 and
             nonbonded[0].attrib.get("method") == "0" and
             nonbonded[0].find("Particles") is not None and gb[0].find("Particles") is not None and
             len(nonbonded[0].find("Particles")) == n and len(gb[0].find("Particles")) == n,
             "fixed System forces mismatch")
    xml_bonds = harmonic[0].find("Bonds")
    _require(xml_bonds is not None and len(xml_bonds) == len(final_edges), "System bond count mismatch")
    xml_edges = set()
    for node in xml_bonds:
        _require(node.tag == "Bond" and all(k in node.attrib for k in ("p1", "p2", "d", "k")),
                 "System bond invalid")
        a, b = int(node.attrib["p1"]), int(node.attrib["p2"])
        _require(0 <= a < n and 0 <= b < n and a != b, "System bond endpoint invalid")
        xml_edges.add(tuple(sorted((a, b))))
    _require(xml_edges == final_edges, "System/topology bond mismatch")
    heavy_indices = [a["topology_index"] for a in heavy]
    expected_heavy = {tuple(sorted((heavy_indices[a], heavy_indices[b]))) for a, b in source_edges}
    _require({edge for edge in final_edges if all(mappings[i]["added_hydrogen"] is False for i in edge)} == expected_heavy,
             "source/final heavy bonds mismatch")
    _require(all(sum(i in edge for edge in final_edges) == 1 for i in [a["topology_index"] for a in added]) and
             all(not (mappings[a]["added_hydrogen"] and mappings[b]["added_hydrogen"]) for a, b in final_edges),
             "added hydrogen bond mismatch")
    for chain in selected["protein"]:
        for left, right in zip(chain["residues"], chain["residues"][1:]):
            c = next(i for i, a in enumerate(originals) if a["residue"] == left["residue"] and a["atom_name"] == "C")
            nn = next(i for i, a in enumerate(originals) if a["residue"] == right["residue"] and a["atom_name"] == "N")
            _require(tuple(sorted((c, nn))) in source_edges, "peptide bond missing")
    for a, b in source_edges:
        left, right = originals[a], originals[b]
        if left["residue"] != right["residue"]:
            peptide = ({left["atom_name"], right["atom_name"]} == {"C", "N"} and
                       left["residue"]["chain_auth"] == right["residue"]["chain_auth"])
            disulfide = left["atom_name"] == right["atom_name"] == "SG"
            _require(peptide or disulfide, "unsupported inter-residue bond")
    sg_edges = [[a, b] for a, b in data["source_bonds"] if originals[a]["atom_name"] == originals[b]["atom_name"] == "SG"]
    _require(data["disulfide_bonds"] == sg_edges, "disulfide mapping mismatch")
    for field in ("input_positions_A",):
        points = data[field]
        _require(isinstance(points, list) and len(points) == n and all(isinstance(p, list) and len(p) == 3 and
                 all(type(x) in (int, float) and math.isfinite(x) for x in p) for p in points), "invalid position array")
    for mapped, point in zip(mappings, data["input_positions_A"], strict=True):
        if not mapped["added_hydrogen"]:
            _require(all(abs(a - b) <= 1e-5 for a, b in zip(mapped["coordinates_A"], point, strict=True)),
                     "source heavy coordinates changed")
    _cif(data["input_cif"], mappings, data["input_positions_A"], selected["model_number"])


def validate_native(store: Any, selected: dict, data: dict, system_xml: bytes) -> None:
    """Validate preparation plus completed potential/minimization evidence."""
    _require(data["schema"] == "openmm_worker_output@1", "scientific output schema mismatch")
    preparation = {key: data[key] for key in PREPARATION_FIELDS}
    validate_preparation(store, selected, {**preparation, "schema": "openmm_preparation_checkpoint@1"}, system_xml)
    mappings = data["atom_mapping"]
    n = len(mappings)
    points = data["final_positions_A"]
    _require(isinstance(points, list) and len(points) == n and all(isinstance(p, list) and len(p) == 3 and
             all(type(x) in (int, float) and math.isfinite(x) for x in p) for p in points), "invalid final positions")
    _cif(data["final_cif"], mappings, data["final_positions_A"], selected["model_number"])
    _require(any(any(abs(a - b) > 1e-5 for a, b in zip(p, q, strict=True)) for p, q in
                 zip(data["input_positions_A"], data["final_positions_A"], strict=True)), "unchanged positions")
    _require(data["convergence"] == "convergence_not_claimed" and data["iterations"] is None, "convergence claim invalid")
    for field in ("before_kJ_mol", "after_kJ_mol", "potential_change_kJ_mol"):
        _require(type(data[field]) in (int, float) and math.isfinite(data[field]), "nonfinite potential")
    _require(math.isclose(data["potential_change_kJ_mol"], data["after_kJ_mol"] - data["before_kJ_mol"],
                          rel_tol=0, abs_tol=1e-8) and data["after_kJ_mol"] <= data["before_kJ_mol"] + 1e-4,
             "potential arithmetic mismatch")
