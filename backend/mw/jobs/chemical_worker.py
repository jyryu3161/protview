"""Fixed, isolated ProLIF 2.2.2 worker. JSON files only; no imports from the server.

The authenticated guardian launches this script in its pinned Python 3.11
environment. The parent validates every output before durable publication.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import socket
import sys
from importlib.metadata import version
from pathlib import Path


def _deny_network() -> None:
    """Deny Python socket egress before importing native chemistry packages.

    This is a fixed defense in depth within the Python worker, not an OS
    network sandbox. The local guardian uses inherited Unix IPC separately;
    this worker itself exchanges only private files with the parent.
    """
    def blocked(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("external network is disabled for the chemical worker")

    def audit(event: str, _args: tuple[object, ...]) -> None:
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
            blocked()

    sys.addaudithook(audit)
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.socket.bind = blocked
    socket.socket.sendto = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked


_deny_network()

import MDAnalysis as mda
import prolif as plf
from MDAnalysis.converters.RDKitInferring import MDAnalysisInferrer
from rdkit import Chem

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "config/chemical/prolif-wheel-hashes-macos-arm64-py311.json"
CATEGORIES = ["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"]
MAX_OUTPUT = 30 * 1024 * 1024
ENGINE_SOURCE_HASHES = {
    "interactions.py": "9b891c16eae1340269b6860131b9bef6f8d9676a54171e0b9c48b6c7aa1b6798",
    "base.py": "3c10fe88839767db22eb43e7b535e087af1d98e60e07a21a2b1708e0727aad91",
}


class NativeChemicalInputError(ValueError):
    def __init__(self, reason_code: str, message: str, *, source_residues: list[dict] | None = None,
                 source_atoms: list[dict] | None = None, sdf_atom_indices: list[int] | None = None):
        super().__init__(message)
        self.reason_code = reason_code
        self.source_residues = source_residues or []
        self.source_atoms = source_atoms or []
        self.sdf_atom_indices = sdf_atom_indices or []

    def envelope(self) -> dict:
        return {"schema": "chemical_worker_error@1", "error_class": "input_invalid",
                "reason_code": self.reason_code, "message": str(self)[:240],
                "source_residues": self.source_residues[:8],
                "source_atoms": self.source_atoms[:8],
                "sdf_atom_indices": self.sdf_atom_indices[:8]}


def _graph_input_error(label: str, message: str, indices: list[int], *,
                       source_refs: list[dict] | None = None,
                       selected_ligand: bool = False) -> None:
    """Report only sites whose staged/native index bijection is established."""
    if source_refs is not None:
        atoms = list(dict.fromkeys(indices))[:8]
        references = [source_refs[index] for index in atoms]
        residues = list({json.dumps(ref["residue"], sort_keys=True): ref["residue"]
                         for ref in references}.values())[:8]
        raise NativeChemicalInputError("receptor_graph_invalid", message,
                                       source_residues=residues, source_atoms=references)
    if selected_ligand:
        raise NativeChemicalInputError("ligand_graph_invalid", message,
                                       sdf_atom_indices=list(dict.fromkeys(indices))[:8])
    raise ValueError(f"{label}: {message}")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def native_method() -> dict:
    from prolif.interactions import base as interaction_base
    from prolif.interactions import interactions as interaction_rules

    files = {"interactions.py": Path(interaction_rules.__file__),
             "base.py": Path(interaction_base.__file__)}
    actual_hashes = {name: digest(path.read_bytes()) for name, path in files.items()}
    if actual_hashes != ENGINE_SOURCE_HASHES:
        raise ValueError("installed native interaction source differs from the locked method")
    fp = plf.Fingerprint(interactions=CATEGORIES, count=True)
    expected_distances = {"HBDonor": 3.5, "HBAcceptor": 3.5,
                          "Hydrophobic": 4.5, "Cationic": 4.5, "Anionic": 4.5}
    if (fp.vicinity_cutoff != 6.0 or not fp.count or list(fp.interactions) != CATEGORIES or
            any(getattr(fp, name.lower()).distance != limit for name, limit in expected_distances.items()) or
            any(tuple(math.degrees(x) for x in getattr(fp, name.lower()).angle) != (130.0, 180.0)
                for name in ("HBDonor", "HBAcceptor"))):
        raise ValueError("installed native interaction criteria differ from selected fixed method")
    smarts = {name: {"ligand": Chem.MolToSmarts(getattr(fp, name.lower()).lig_pattern),
                     "protein": Chem.MolToSmarts(getattr(fp, name.lower()).prot_pattern)}
              for name in CATEGORIES}
    return {"schema": "chemical_native_method@1", "source_sha256": actual_hashes,
            "native_smarts": smarts, "native_smarts_sha256": digest(canonical(smarts)),
            "criteria": {"categories": CATEGORIES, "Hbond_distance_A": 3.5,
                         "Hbond_DHA_angle_deg": [130, 180], "Hydrophobic_distance_A": 4.5,
                         "Cationic_distance_A": 4.5, "Anionic_distance_A": 4.5,
                         "vicinity_cutoff_A": 6.0}}


def handshake() -> dict:
    required = {"prolif": "2.2.2", "rdkit": "2026.3.6", "MDAnalysis": "2.10.0", "gemmi": "0.7.5"}
    installed = {name: version(name) for name in required}
    if installed != required or not LOCK.is_file():
        raise ValueError("pinned ProLIF worker dependencies unavailable")
    return {"schema": "chemical_worker_handshake@1", "versions": installed,
            "native_rdkit_version": Chem.rdBase.rdkitVersion,
            "native_method": native_method(),
            "lock_sha256": digest(LOCK.read_bytes()),
            "worker_sha256": digest(Path(__file__).read_bytes()),
            "python": sys.version.split()[0], "platform": sys.platform}


def _finite(coords: object) -> list[float]:
    if (type(coords) is not list or len(coords) != 3 or
            any(type(x) not in (float, int) or not math.isfinite(x) or abs(x) > 100_000 for x in coords)):
        raise ValueError("nonfinite or out-of-range coordinate")
    return [float(x) for x in coords]


def _graph_checks(mol: Chem.Mol, supplied_edges: set[tuple[int, int]], label: str, *,
                  source_refs: list[dict] | None = None, selected_ligand: bool = False) -> None:
    if mol.GetNumAtoms() < 1 or mol.GetNumBonds() != len(supplied_edges):
        raise ValueError(f"{label}: atom/bond count mismatch")
    actual = {tuple(sorted((b.GetBeginAtomIdx(), b.GetEndAtomIdx()))) for b in mol.GetBonds()}
    if actual != supplied_edges:
        raise ValueError(f"{label}: inferred graph edge set differs from supplied bonds")
    if label == "ligand":
        fragments = Chem.GetMolFrags(mol, asMols=False, sanitizeFrags=False)
        if len(fragments) != 1:
            if selected_ligand:
                raise NativeChemicalInputError("ligand_disconnected", "Ligand has multiple covalent components",
                                               sdf_atom_indices=[fragment[0] for fragment in fragments[:8]])
            raise ValueError("reconstructed ligand graph has multiple covalent components")
    Chem.SanitizeMol(mol)
    for atom in mol.GetAtoms():
        idx = atom.GetIdx()
        if (atom.GetNumRadicalElectrons() or atom.GetNumImplicitHs() or atom.GetNumExplicitHs() or
                atom.GetIsotope() != 0 or atom.GetDegree() == 0):
            _graph_input_error(label, "Unsupported radical, implicit/bracket H, isotope or isolated atom",
                               [idx], source_refs=source_refs, selected_ligand=selected_ligand)
        if atom.GetSymbol() == "H" and (atom.GetDegree() != 1 or
                                         atom.GetNeighbors()[0].GetSymbol() not in {"C", "N", "O", "S", "P"}):
            _graph_input_error(label, "Invalid explicit H neighbor", [idx] +
                               [neighbor.GetIdx() for neighbor in atom.GetNeighbors()][:7],
                               source_refs=source_refs, selected_ligand=selected_ligand)
    conf = mol.GetConformer()
    if not conf.Is3D():
        _graph_input_error(label, "Missing 3D conformer", [], source_refs=source_refs,
                           selected_ligand=selected_ligand)
    for bond in mol.GetBonds():
        first, second = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        if math.dist(list(conf.GetAtomPosition(first)), list(conf.GetAtomPosition(second))) <= 1e-7:
            _graph_input_error(label, "Zero-length bonded vector", [first, second],
                               source_refs=source_refs, selected_ligand=selected_ligand)


def _protein_chemistry(rows: list[dict], mol: Chem.Mol) -> list[dict]:
    """Assert only graph features the selected prepared-protein lane promises.

    The output describes supplied/inferred chemistry. It is not a claim that a
    missing proton or side-chain atom could always be detected.
    """
    residues: dict[str, tuple[dict, dict[str, int]]] = {}
    source_refs = [row["source_ref"] for row in rows]
    for index, row in enumerate(rows):
        residue = row["source_ref"]["residue"]
        key = json.dumps(residue, sort_keys=True)
        if key not in residues:
            residues[key] = (residue, {})
        names = residues[key][1]
        name = row["source_ref"]["atom_name"]
        if name in names:
            _graph_input_error("receptor", "Duplicate protein atom name in exact residue",
                               [names[name], index], source_refs=source_refs)
        names[name] = index

    def bond(a: int, b: int) -> Chem.Bond:
        found = mol.GetBondBetweenAtoms(a, b)
        if found is None:
            _graph_input_error("receptor", "Required protein bond missing", [a, b],
                               source_refs=source_refs)
        return found

    states = []
    for residue, names in residues.values():
        if not {"N", "CA", "C", "O"} <= names.keys():
            _graph_input_error("receptor", "Protein backbone atom inventory incomplete",
                               list(names.values())[:8], source_refs=source_refs)
        for a, b in (("N", "CA"), ("CA", "C")):
            if bond(names[a], names[b]).GetBondType() != Chem.BondType.SINGLE:
                _graph_input_error("receptor", f"Backbone {a}-{b} inferred bond order invalid",
                                   [names[a], names[b]], source_refs=source_refs)
        if bond(names["C"], names["O"]).GetBondType() != Chem.BondType.DOUBLE:
            _graph_input_error("receptor", "Backbone carbonyl C=O inferred bond order invalid",
                               [names["C"], names["O"]], source_refs=source_refs)
        if set(names) & {"CAY", "CY", "OY"}:
            if not {"CAY", "CY", "OY"} <= names.keys():
                _graph_input_error("receptor", "Merged terminal cap atom inventory incomplete",
                                   [names[name] for name in ("CAY", "CY", "OY") if name in names],
                                   source_refs=source_refs)
            for a, b, expected in (("CAY", "CY", Chem.BondType.SINGLE),
                                   ("CY", "OY", Chem.BondType.DOUBLE),
                                   ("CY", "N", Chem.BondType.SINGLE)):
                if bond(names[a], names[b]).GetBondType() != expected:
                    _graph_input_error("receptor", "Merged terminal cap inferred bond order invalid",
                                       [names[a], names[b]], source_refs=source_refs)
            c_cap = mol.GetAtomWithIdx(names["CAY"])
            if sum(neighbor.GetSymbol() == "H" for neighbor in c_cap.GetNeighbors()) != 3:
                _graph_input_error("receptor", "Merged terminal cap requires three actual H vertices",
                                   [names["CAY"]] + [neighbor.GetIdx() for neighbor in c_cap.GetNeighbors()
                                                     if neighbor.GetSymbol() == "H"][:7],
                                   source_refs=source_refs)
        acid = {"ASP": ("CG", "OD1", "OD2"), "GLU": ("CD", "OE1", "OE2")}.get(residue["resname"])
        if acid and all(x in names for x in acid):
            carbon, oxygen1, oxygen2 = acid
            orders = [bond(names[carbon], names[x]).GetBondType() for x in (oxygen1, oxygen2)]
            if orders.count(Chem.BondType.SINGLE) != 1 or orders.count(Chem.BondType.DOUBLE) != 1:
                _graph_input_error("receptor", "Acid oxygens lack one inferred single and one double bond",
                                   [names[carbon], names[oxygen1], names[oxygen2]], source_refs=source_refs)
        amide = {"ASN": ("CG", "OD1", "ND2"), "GLN": ("CD", "OE1", "NE2")}.get(residue["resname"])
        if amide and all(x in names for x in amide):
            carbon, oxygen, nitrogen = amide
            if (bond(names[carbon], names[oxygen]).GetBondType() != Chem.BondType.DOUBLE or
                    bond(names[carbon], names[nitrogen]).GetBondType() != Chem.BondType.SINGLE or
                    mol.GetAtomWithIdx(names[nitrogen]).GetFormalCharge() != 0):
                _graph_input_error("receptor", "Amide graph contradicts nonacceptor amide nitrogen",
                                   [names[carbon], names[oxygen], names[nitrogen]], source_refs=source_refs)
        if residue["resname"] in {"HSD", "HID", "HSE", "HIE", "HSP", "HIP", "HIS"}:
            ring = ("CG", "ND1", "CE1", "NE2", "CD2")
            def histidine_error(reason: str, message: str, sites: tuple[str, ...] = ("ND1", "NE2"),
                                residue_ref: dict = residue, site_map: dict = names) -> None:
                raise NativeChemicalInputError(
                    reason, message, source_residues=[residue_ref],
                    source_atoms=[rows[site_map[name]]["source_ref"] for name in sites if name in site_map])

            if not {"CB", *ring} <= names.keys():
                histidine_error("histidine_ring_graph", "Supplied histidine ring atom inventory incomplete",
                                ("CB", *ring))
            ring_edges = tuple(zip(ring, ring[1:] + ring[:1]))
            for first, second in ring_edges:
                edge = mol.GetBondBetweenAtoms(names[first], names[second])
                if edge is None:
                    histidine_error("histidine_ring_graph", "Supplied histidine ring edge missing",
                                    (first, second))
                if edge.GetBondType() != Chem.BondType.AROMATIC or not edge.GetIsAromatic():
                    histidine_error("histidine_ring_graph", "Histidine ring edge is not aromatic",
                                    (first, second))
            cb_cg = mol.GetBondBetweenAtoms(names["CB"], names["CG"])
            if cb_cg is None or cb_cg.GetBondType() != Chem.BondType.SINGLE:
                histidine_error("histidine_ring_graph", "Histidine CB-CG attachment is not single",
                                ("CB", "CG"))
            expected_heavy = {"CG": {"CB", "ND1", "CD2"}, "ND1": {"CG", "CE1"},
                              "CE1": {"ND1", "NE2"}, "NE2": {"CE1", "CD2"},
                              "CD2": {"NE2", "CG"}}
            for name in ring:
                atom = mol.GetAtomWithIdx(names[name])
                neighbors = {n.GetIdx() for n in atom.GetNeighbors() if n.GetSymbol() != "H"}
                if (not atom.GetIsAromatic() or
                        neighbors != {names[other] for other in expected_heavy[name]}):
                    histidine_error("histidine_ring_graph", "Histidine ring connectivity/aromaticity invalid",
                                    (name,))
            protonated = []
            for atom_name in ("ND1", "NE2"):
                atom = mol.GetAtomWithIdx(names[atom_name])
                hydrogens = [neighbor for neighbor in atom.GetNeighbors() if neighbor.GetSymbol() == "H"]
                if len(hydrogens) > 1:
                    histidine_error("histidine_ring_graph", "Multiple histidine ring H on one nitrogen",
                                    (atom_name,))
                if hydrogens:
                    protonated.append(atom_name)
            expected = {"HSD": ["ND1"], "HID": ["ND1"], "HSE": ["NE2"],
                        "HIE": ["NE2"], "HSP": ["ND1", "NE2"], "HIP": ["ND1", "NE2"]}.get(residue["resname"])
            if expected is not None and protonated != expected:
                histidine_error("histidine_alias_state", "Histidine alias conflicts with supplied ring-H graph")
            if protonated not in (["ND1"], ["NE2"], ["ND1", "NE2"]):
                histidine_error("histidine_alias_state", "Unsupported histidine ring-H state")
            ring_charges = {name: mol.GetAtomWithIdx(names[name]).GetFormalCharge() for name in ring}
            nitrogen_charges = {name: ring_charges[name] for name in ("ND1", "NE2")}
            if (any(ring_charges[name] != 0 for name in ("CG", "CE1", "CD2")) or
                    (protonated == ["ND1", "NE2"] and sorted(nitrogen_charges.values()) != [0, 1]) or
                    (protonated != ["ND1", "NE2"] and any(nitrogen_charges.values()))):
                histidine_error("histidine_charge_state",
                                "Histidine inferred ring charge contradicts supplied ring-H state")
            represented = ({("ND1",): "neutral_ND1_H", ("NE2",): "neutral_NE2_H",
                            ("ND1", "NE2"): "cationic_ND1_NE2_H"}[tuple(protonated)])
            states.append({"residue": residue, "ring_h_sites": protonated,
                           "ring_formal_charge": sum(ring_charges.values()),
                           "ring_n_charges": nitrogen_charges, "represented_state": represented,
                           "annotation": "graph-derived supplied state; not a pH prediction"})
    return states


def _receptor(payload: dict) -> tuple[plf.Molecule, list[dict], list[dict], list[dict]]:
    rows = payload["receptor_atoms"]
    edges = payload["receptor_bonds"]
    if not 1 <= len(rows) <= 10_000 or len(edges) > 20_000:
        raise ValueError("receptor atom or bond limit")
    residue_keys: dict[str, int] = {}
    residues: list[dict] = []
    atom_resindex: list[int] = []
    for i, row in enumerate(rows):
        if type(row) is not dict or row["element"].upper() not in {"H", "C", "N", "O", "S"}:
            raise ValueError(f"unsupported receptor element at {i}")
        ref = row["source_ref"]
        key = json.dumps(ref["residue"], sort_keys=True)
        if key not in residue_keys:
            residue_keys[key] = len(residues)
            residues.append(ref["residue"])
        atom_resindex.append(residue_keys[key])
        _finite(row["coordinate_A"])
    supplied: set[tuple[int, int]] = set()
    for item in edges:
        if (type(item) is not list or len(item) != 2 or any(type(x) is not int or not 0 <= x < len(rows) for x in item)
                or item[0] == item[1]):
            raise ValueError("invalid receptor bond endpoint")
        pair = tuple(sorted(item))
        if pair in supplied:
            raise ValueError("duplicate receptor bond")
        supplied.add(pair)
    source_refs = [row["source_ref"] for row in rows]
    neighbors = [set() for _ in rows]
    for first, second in supplied:
        neighbors[first].add(second)
        neighbors[second].add(first)
        if math.dist(rows[first]["coordinate_A"], rows[second]["coordinate_A"]) <= 1e-7:
            _graph_input_error("receptor", "Zero-length supplied covalent bond vector",
                               [first, second], source_refs=source_refs)
    for index, row in enumerate(rows):
        if row["element"].upper() == "H" and (len(neighbors[index]) != 1 or
                rows[next(iter(neighbors[index]))]["element"].upper() not in {"C", "N", "O", "S"}):
            _graph_input_error("receptor", "Explicit H must have one allowed covalent neighbor",
                               [index, *sorted(neighbors[index])[:7]], source_refs=source_refs)
    u = mda.Universe.empty(len(rows), n_residues=len(residues), atom_resindex=atom_resindex, trajectory=True)
    u.add_TopologyAttr("names", [r["source_ref"]["atom_name"] for r in rows])
    u.add_TopologyAttr("elements", [r["element"] for r in rows])
    u.add_TopologyAttr("resnames", [r["resname"] for r in residues])
    # Synthetic backend IDs are deliberately unique, independent of auth/label
    # chains, insertion codes, and duplicated author residue numbers.
    u.add_TopologyAttr("resids", list(range(1, len(residues) + 1)))
    u.add_TopologyAttr("chainIDs", ["X"] * len(rows))
    u.add_TopologyAttr("segids", ["X"])
    u.add_TopologyAttr("bonds", sorted(supplied))
    u.atoms.positions = [r["coordinate_A"] for r in rows]
    mol = plf.Molecule.from_mda(u.atoms, use_segid=False, cache=False,
                                implicit_hydrogens=False, force=False,
                                inferrer=MDAnalysisInferrer(max_iter=200, sanitize=True))
    if [a.GetIntProp("_MDAnalysis_index") for a in mol.GetAtoms()] != list(range(len(rows))):
        raise ValueError("receptor native parent index bijection failed")
    _graph_checks(mol, supplied, "receptor", source_refs=source_refs)
    histidine_states = _protein_chemistry(rows, mol)
    graph_rows = []
    for i, (source, atom) in enumerate(zip(rows, mol.GetAtoms(), strict=True)):
        position = list(mol.GetConformer().GetAtomPosition(i))
        if math.dist(position, source["coordinate_A"]) > 1e-4:
            raise ValueError("receptor float32 coordinate drift exceeds 1e-4 A")
        graph_rows.append({"local_site_index": i, "source_ref": source["source_ref"],
                           "coordinate_A": source["coordinate_A"], "engine_coordinate_A": position,
                           "element": atom.GetSymbol(), "formal_charge": atom.GetFormalCharge(),
                           "aromatic": atom.GetIsAromatic(), "synthetic_residue_index": atom_resindex[i],
                           "native_parent_index": i, "atom_name": source["source_ref"]["atom_name"]})
    graph_bonds = [{"first": b.GetBeginAtomIdx(), "second": b.GetEndAtomIdx(),
                    "order": str(b.GetBondType())} for b in mol.GetBonds()]
    return mol, graph_rows, graph_bonds, histidine_states


def _signed_tetrahedral_determinant(mol: Chem.Mol, index: int) -> float:
    neighbors = sorted(atom.GetIdx() for atom in mol.GetAtomWithIdx(index).GetNeighbors())
    if len(neighbors) != 4:
        raise ValueError("unsupported tetrahedral neighbor count")
    points = [mol.GetConformer().GetAtomPosition(i) for i in neighbors]
    vectors = [[float(p[k] - points[3][k]) for k in range(3)] for p in points[:3]]
    return (vectors[0][0] * (vectors[1][1] * vectors[2][2] - vectors[1][2] * vectors[2][1]) -
            vectors[0][1] * (vectors[1][0] * vectors[2][2] - vectors[1][2] * vectors[2][0]) +
            vectors[0][2] * (vectors[1][0] * vectors[2][1] - vectors[1][1] * vectors[2][0]))


def _declared_tetrahedral_stereo(mol: Chem.Mol) -> list[dict]:
    """Compare explicit V2000 tetrahedral parity with independently perceived 3D.

    RDKit's 3D molfile rule intentionally ignores wedge/dash depiction when
    nonplanar coordinates are supplied. Atom parity is an additional explicit
    declaration; a contradiction cannot be silently replaced by 3D inference.
    """
    if not mol.GetConformer().Is3D():
        raise ValueError("selected ligand requires an actual 3D conformer")
    for bond in mol.GetBonds():
        if bond.GetStereo() != Chem.BondStereo.STEREONONE:
            raise NativeChemicalInputError(
                "stereo_unsupported", "Unsupported ligand bond stereochemistry",
                sdf_atom_indices=[bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()])
    declared = Chem.Mol(mol)
    Chem.RemoveStereochemistry(declared)
    Chem.AssignAtomChiralTagsFromMolParity(declared)
    Chem.AssignStereochemistry(declared, force=True, cleanIt=True)
    geometric = Chem.Mol(mol)
    Chem.RemoveStereochemistry(geometric)
    Chem.AssignStereochemistryFrom3D(geometric)
    audit = []
    for source in mol.GetAtoms():
        if not source.HasProp("molParity"):
            continue
        index = source.GetIdx()
        if source.GetIntProp("molParity") not in {1, 2} or source.GetDegree() != 4:
            raise NativeChemicalInputError("stereo_unsupported", "Unsupported declared tetrahedral parity",
                                           sdf_atom_indices=[index])
        expected = declared.GetAtomWithIdx(index)
        observed = geometric.GetAtomWithIdx(index)
        if (not expected.HasProp("_CIPCode") or not observed.HasProp("_CIPCode") or
                expected.GetProp("_CIPCode") not in {"R", "S"} or
                expected.GetProp("_CIPCode") != observed.GetProp("_CIPCode")):
            raise NativeChemicalInputError("stereo_conflict",
                                           "Declared tetrahedral parity contradicts selected 3D coordinates",
                                           sdf_atom_indices=[index])
        determinant = _signed_tetrahedral_determinant(mol, index)
        if not math.isfinite(determinant) or abs(determinant) <= 1e-8:
            raise NativeChemicalInputError("stereo_unsupported", "Ambiguous tetrahedral 3D geometry",
                                           sdf_atom_indices=[index])
        audit.append({"sdf_atom_index": index, "declared_parity": source.GetIntProp("molParity"),
                      "declared_CIP": expected.GetProp("_CIPCode"),
                      "observed_CIP": observed.GetProp("_CIPCode"),
                      "signed_tetrahedral_determinant_A3": determinant,
                      "method": "rdkit_v2000_parity_vs_3d@1", "outcome": "match"})
    return audit


def _ligand(payload: dict) -> tuple[plf.Molecule, list[dict], list[dict], list[dict]]:
    raw = base64.b64decode(payload["ligand_sdf_b64"], validate=True)
    if len(raw) > 10 * 1024 * 1024 or digest(raw) != payload["ligand_sdf_sha256"]:
        raise ValueError("ligand SDF bytes/hash mismatch")
    supplier = Chem.ForwardSDMolSupplier(io.BytesIO(raw), removeHs=False, sanitize=True)
    selected = None
    for i, mol in enumerate(supplier):
        if i == payload["sdf_record_index"]:
            selected = mol
            break
    if selected is None or selected.GetNumConformers() != 1 or not 1 <= selected.GetNumAtoms() <= 256:
        raise NativeChemicalInputError("ligand_chemistry_invalid",
                                       "Selected ligand SDF record cannot be sanitized as supplied")
    stereo_audit = _declared_tetrahedral_stereo(selected)
    mol = plf.Molecule.from_rdkit(selected, resname="LIG", resnumber=1, chain="L")
    names = payload["ligand_atom_names"]
    if (type(names) is not list or len(names) != mol.GetNumAtoms() or
            any(type(name) is not str or not name or len(name) > 32 for name in names)):
        raise ValueError("selected ligand atom names unavailable")
    supplied = {tuple(sorted((b.GetBeginAtomIdx(), b.GetEndAtomIdx()))) for b in mol.GetBonds()}
    _graph_checks(mol, supplied, "ligand", selected_ligand=True)
    if len(supplied) > 20_000:
        raise ValueError("ligand bond limit")
    rows = []
    for i, atom in enumerate(mol.GetAtoms()):
        position = list(mol.GetConformer().GetAtomPosition(i))
        _finite(position)
        rows.append({"local_site_index": i, "sdf_atom_index": i,
                     "coordinate_A": position, "engine_coordinate_A": position,
                     "element": atom.GetSymbol().upper(), "formal_charge": atom.GetFormalCharge(),
                     "aromatic": atom.GetIsAromatic(), "synthetic_residue_index": 0,
                     "native_parent_index": i, "atom_name": names[i]})
    bonds = [{"first": b.GetBeginAtomIdx(), "second": b.GetEndAtomIdx(),
              "order": str(b.GetBondType())} for b in mol.GetBonds()]
    return mol, rows, bonds, stereo_audit


def prepare(payload: dict) -> dict:
    if payload.get("schema") != "chemical_prepare_worker_input@1":
        raise ValueError("invalid fixed preparation schema")
    receptor, r_atoms, r_bonds, histidine_states = _receptor(payload)
    ligand, l_atoms, l_bonds, stereo_audit = _ligand(payload)
    if len(r_bonds) + len(l_bonds) > 20_000:
        raise ValueError("combined bond limit")
    return {"schema": "chemical_prepare_worker_output@1", "dependency": handshake(),
            "receptor_atoms": r_atoms, "receptor_bonds": r_bonds,
            "ligand_atoms": l_atoms, "ligand_bonds": l_bonds,
            "receptor_atom_count": receptor.GetNumAtoms(), "ligand_atom_count": ligand.GetNumAtoms(),
            "supplied_graph_edge_count": len(r_bonds) + len(l_bonds),
            "histidine_states": histidine_states, "stereochemistry_audit": stereo_audit,
            "coordinate_policy": "source float64; receptor MDAnalysis float32 and ligand SDF conformer retained"}


def _molecule_from_graph(graph: dict, side: str) -> plf.Molecule:
    atoms, bonds = graph[f"{side}_atoms"], graph[f"{side}_bonds"]
    builder = Chem.RWMol()
    for row in atoms:
        atom = Chem.Atom(row["element"].capitalize())
        atom.SetFormalCharge(row["formal_charge"])
        atom.SetNoImplicit(True)
        atom.SetIsAromatic(row["aromatic"])
        res_idx = row["synthetic_residue_index"]
        # Keep the entire supplied or disclosed generated atom name. Native
        # parent indices remain authoritative even for duplicate names.
        info = Chem.AtomPDBResidueInfo(row["atom_name"],
                                        residueName="LIG" if side == "ligand" else row["source_ref"]["residue"]["resname"],
                                        residueNumber=res_idx + 1, chainId="L" if side == "ligand" else "X")
        atom.SetMonomerInfo(info)
        atom.SetIntProp("_MDAnalysis_index", row["native_parent_index"])
        builder.AddAtom(atom)
    for bond in bonds:
        typ = {"SINGLE": Chem.BondType.SINGLE, "DOUBLE": Chem.BondType.DOUBLE,
               "TRIPLE": Chem.BondType.TRIPLE, "AROMATIC": Chem.BondType.AROMATIC}[bond["order"]]
        builder.AddBond(bond["first"], bond["second"], typ)
    mol = builder.GetMol()
    conf = Chem.Conformer(len(atoms))
    conf.Set3D(True)
    for i, row in enumerate(atoms):
        conf.SetAtomPosition(i, _finite(row["engine_coordinate_A"]))
    mol.AddConformer(conf)
    _graph_checks(mol, {tuple(sorted((b["first"], b["second"]))) for b in bonds}, side)
    return plf.Molecule.from_rdkit(mol, use_segid=False)


def detect(payload: dict) -> dict:
    if payload.get("schema") != "chemical_detect_worker_input@1":
        raise ValueError("invalid fixed detection schema")
    graph = payload["graph"]
    lig = _molecule_from_graph(graph, "ligand")
    prot = _molecule_from_graph(graph, "receptor")
    native_method()  # Reject changed installed default rules before any assignment.
    fp = plf.Fingerprint(interactions=CATEGORIES, count=True)
    native = fp.generate(lig, prot, metadata=True)
    rows = []
    for pair, by_category in native.items():
        for category, assignments in by_category.items():
            if category not in CATEGORIES:
                raise ValueError("unexpected native category")
            for item in assignments:
                if len(rows) >= 20_000:
                    raise ValueError("native assignment count exceeds limit")
                indices = item["parent_indices"]
                local = item["indices"]
                for side, mol, resid in (("ligand", lig, pair[0]), ("protein", prot, pair[1])):
                    if len(indices[side]) != len(local[side]):
                        raise ValueError("native local/parent index cardinality mismatch")
                    residue = mol[resid]
                    for parent, within in zip(indices[side], local[side], strict=True):
                        if (type(parent) is not int or type(within) is not int or parent < 0 or
                                parent >= mol.GetNumAtoms() or within < 0 or within >= residue.GetNumAtoms() or
                                residue.GetAtomWithIdx(within).GetIntProp("_MDAnalysis_index") != parent):
                            raise ValueError("native local-to-parent mapping mismatch")
                rows.append({"category": category, "parent_indices": indices,
                             "within_residue_indices": local, "native_metadata":
                             {key: value for key, value in item.items() if key not in {"indices", "parent_indices"}}})
    return {"schema": "chemical_detect_worker_output@1", "dependency": handshake(),
            "native_rows": rows, "native_total": len(rows), "null_result": not rows}


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--handshake":
        print(json.dumps(handshake(), sort_keys=True, separators=(",", ":")))
        return 0
    control = json.loads(Path("input.json").read_text())
    raw = Path("structure.json").read_bytes()
    if digest(raw) != control["input_sha256"]:
        raise ValueError("worker input hash mismatch")
    payload = json.loads(raw)
    if control["adapter"] == "prolif_prepare_v1":
        result = prepare(payload)
    elif control["adapter"] == "prolif_detect_v1":
        result = detect(payload)
    else:
        raise ValueError("unsupported fixed worker adapter")
    output = canonical(result)
    if not 0 < len(output) <= MAX_OUTPUT:
        raise ValueError("bounded worker output exceeded")
    with Path("result.tmp").open("xb") as stream:
        stream.write(output)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace("result.tmp", "result.json")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except NativeChemicalInputError as exc:
        payload = canonical(exc.envelope())
        if len(payload) > 4096:
            payload = canonical({"schema": "chemical_worker_error@1", "error_class": "fatal",
                                 "reason_code": "native_internal_error", "message": "bounded native diagnostic exceeded",
                                 "source_residues": [], "source_atoms": [], "sdf_atom_indices": []})
        Path("error.json").write_bytes(payload)
        raise SystemExit(1)
    except (ValueError, TypeError, KeyError, IndexError, OSError, RuntimeError, ImportError) as exc:
        Path("error.json").write_bytes(canonical(
            {"schema": "chemical_worker_error@1", "error_class": "fatal",
             "reason_code": "native_internal_error", "message": type(exc).__name__[:80],
             "source_residues": [], "source_atoms": [], "sdf_atom_indices": []}))
        raise SystemExit(1)
