"""Only fixed OpenMM worker, launched by the authenticated local guardian."""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import xml.etree.ElementTree as ET
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

import gemmi
import openmm
from openmm import app, unit
from openmm.app import forcefield

from mw.core.handles import canonical_json

MAX_PREPARATION_BYTES = 64_000_000


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _verify_method(method: dict) -> None:
    if (version("openmm") != "8.6.0" or method["distribution_version"] != "8.6.0" or
            method["engine_build"] != openmm.version.full_version or
            method["platform"] != "CPU" or method["platform_properties"] != {"Threads": "1"} or
            method["hydrogen_platform"] != "CPU" or method["hydrogen_platform_properties"] != {"Threads": "1"} or
            method["forcefield_files"] != ["amber14-all.xml", "implicit/gbn2.xml"] or
            method["nonbonded_method"] != "NoCutoff" or method["constraints"] is not None or
            method["pH"] != 7.0 or method["tolerance_kJ_mol_nm"] != 10.0 or
            method["max_iterations"] != 50 or method["selection_policy"] != "protein_only" or
            method["hydrogen_policy"] != "rebuild_pH7"):
        raise ValueError("fixed OpenMM method mismatch")
    root = (Path(forcefield.__file__).parent / "data").resolve()
    found: dict[str, str] = {}

    def visit(relative: str) -> None:
        if relative in found:
            return
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("invalid built-in force-field path")
        raw = path.read_bytes()
        found[relative] = _digest(raw)
        for node in ET.fromstring(raw).findall("Include"):
            candidate = (path.parent / node.attrib["file"]).resolve()
            if not candidate.is_file():
                candidate = (root / node.attrib["file"]).resolve()
            visit(str(candidate.relative_to(root)))

    for name in method["forcefield_files"]:
        visit(name)
    if found != method["forcefield_files_sha256"]:
        raise ValueError("force-field file fingerprint changed")


def _coordinates(model: app.Modeller, mappings: list[dict], model_number: int) -> bytes:
    structure = gemmi.Structure()
    structure.name = "ProtView OpenMM protein-only"
    gm = gemmi.Model(str(model_number))
    structure.add_model(gm)
    gm = structure[0]
    by_residue: dict[int, gemmi.Residue] = {}
    for atom, pos, mapped in zip(model.topology.atoms(), model.positions, mappings, strict=True):
        source = mapped["residue"]
        chain_index = mapped["chain_index"]
        while len(gm) <= chain_index:
            gm.add_chain(gemmi.Chain(mapped["chain_auth"]))
        idx = mapped["residue_index"]
        if idx not in by_residue:
            residue = gemmi.Residue()
            residue.name = source["resname"]
            residue.seqid = gemmi.SeqId(source["seq_auth"], source["icode"] or " ")
            residue.label_seq = source["seq_label"]
            residue.subchain = source["chain_label"] or ""
            residue.het_flag = "A"
            gm[chain_index].add_residue(residue)
            by_residue[idx] = gm[chain_index][-1]
        ga = gemmi.Atom()
        ga.name = atom.name
        ga.element = gemmi.Element(atom.element.symbol)
        xyz = pos.value_in_unit(unit.angstrom)
        ga.pos = gemmi.Position(*xyz)
        ga.occ = 1.0
        by_residue[idx].add_atom(ga)
    return structure.make_mmcif_document().as_string().encode()


def run(payload: dict, on_prepared: Callable[[dict], None] | None = None) -> dict:
    method = payload["method"]
    if (payload["schema"] != "openmm_preparation_input@1" or method["method_id"] != "openmm_protein_minimize_v1" or
            method["forcefield_files"] != ["amber14-all.xml", "implicit/gbn2.xml"] or
            method["platform"] != "CPU" or method["max_iterations"] != 50):
        raise ValueError("fixed protocol mismatch")
    _verify_method(method)
    seed = payload["seed"]
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed % (2**32))
    except ImportError:
        pass
    topology = app.Topology()
    positions = []
    heavy_map = []
    residue_map = []
    for chain_index, source_chain in enumerate(payload["protein"]):
        chain = topology.addChain(str(chain_index))
        for source_residue in source_chain["residues"]:
            ref = source_residue["residue"]
            residue_index = len(residue_map)
            residue_map.append(ref)
            residue = topology.addResidue(ref["resname"], chain, id=str(residue_index + 1))
            for source_atom in source_residue["atoms"]:
                atom = topology.addAtom(source_atom["atom_name"],
                                        app.element.get_by_symbol(source_atom["element"]), residue)
                heavy_map.append({**source_atom, "topology_index": atom.index,
                                  "chain_index": chain_index, "chain_auth": source_chain["chain_auth"],
                                  "residue_index": residue_index, "added_hydrogen": False})
                positions.append(openmm.Vec3(*source_atom["coordinates_A"]))
    positions = unit.Quantity(positions, unit.angstrom)
    topology.createStandardBonds()
    topology.createDisulfideBonds(positions)
    bonds = [[a.index, b.index] for a, b in topology.bonds()]
    if not bonds:
        raise ValueError("no standard protein bonds")
    model = app.Modeller(topology, positions)
    ff = app.ForceField(*method["forcefield_files"])
    platform = openmm.Platform.getPlatformByName("CPU")
    platform.setPropertyDefaultValue("Threads", "1")
    variants = model.addHydrogens(ff, pH=method["pH"], platform=platform)
    mappings = []
    heavy_by_identity = {(item["residue_index"], item["atom_name"]): item for item in heavy_map}
    added = []
    for atom in model.topology.atoms():
        residue_index = int(atom.residue.id) - 1
        source = residue_map[residue_index]
        original = heavy_by_identity.get((residue_index, atom.name))
        if original is not None:
            if atom.element.symbol != original["element"]:
                raise ValueError("heavy atom mapping changed")
            mappings.append({**original, "topology_index": atom.index})
        else:
            item = {"residue": source, "atom_name": atom.name, "element": atom.element.symbol,
                    "topology_index": atom.index, "chain_index": int(atom.residue.chain.id),
                    "chain_auth": payload["protein"][int(atom.residue.chain.id)]["chain_auth"],
                    "residue_index": residue_index, "added_hydrogen": True}
            mappings.append(item)
            added.append(item)
    if len(mappings) != model.topology.getNumAtoms() or len(heavy_map) + len(added) != len(mappings):
        raise ValueError("atom mapping count mismatch")
    if len({(item["residue_index"], item["atom_name"]) for item in mappings}) != len(mappings):
        raise ValueError("ambiguous final atom mapping")
    input_bytes = _coordinates(model, mappings, payload["model_number"])
    system = ff.createSystem(model.topology, nonbondedMethod=app.NoCutoff, constraints=None)
    system_xml = openmm.XmlSerializer.serialize(system).encode()
    initial_exact = [[float(x) for x in point.value_in_unit(unit.angstrom)] for point in model.positions]
    final_bonds = [[a.index, b.index] for a, b in model.topology.bonds()]
    preparation = {"schema": "openmm_preparation_checkpoint@1", "method": method,
                   "selected_sha256": _digest(canonical_json(payload)),
                   "input_cif": input_bytes.decode(), "input_positions_A": initial_exact,
                   "system_xml": system_xml.decode(), "system_xml_sha256": _digest(system_xml),
                   "topology_sha256": _digest(canonical_json({"atoms": mappings, "bonds": final_bonds})),
                   "heavy_atoms": len(heavy_map), "added_hydrogens": added,
                   "atom_mapping": mappings, "residue_mapping": residue_map, "source_bonds": bonds,
                   "final_bonds": final_bonds, "protonation_variants": variants,
                   "disulfide_bonds": [[a.index, b.index] for a, b in topology.bonds()
                                         if a.name == b.name == "SG"]}
    if on_prepared is not None:
        on_prepared(preparation)
    integrator = openmm.VerletIntegrator(0.001 * unit.picoseconds)
    simulation = app.Simulation(model.topology, system, integrator, platform, {"Threads": "1"})
    simulation.context.setPositions(model.positions)
    before = simulation.context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    simulation.minimizeEnergy(tolerance=10 * unit.kilojoule_per_mole / unit.nanometer, maxIterations=50)
    state = simulation.context.getState(getEnergy=True, getPositions=True)
    after = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    if not all(math.isfinite(v) for v in (before, after)) or after > before + 1e-4:
        raise ValueError("nonfinite or substantially increased potential")
    final_model = app.Modeller(model.topology, state.getPositions())
    final_bytes = _coordinates(final_model, mappings, payload["model_number"])
    final_exact = [[float(x) for x in point.value_in_unit(unit.angstrom)] for point in state.getPositions()]
    return {**preparation, "schema": "openmm_worker_output@1",
            "before_kJ_mol": before, "after_kJ_mol": after, "potential_change_kJ_mol": after - before,
            "final_cif": final_bytes.decode(), "final_positions_A": final_exact,
            "convergence": "convergence_not_claimed", "iterations": None}


def write_preparation(preparation: dict, directory: Path = Path(".")) -> None:
    """Publish a complete private checkpoint before protocol potential evaluation."""
    raw = canonical_json(preparation)
    if not 0 < len(raw) <= MAX_PREPARATION_BYTES:
        raise ValueError("preparation checkpoint exceeds fixed limit")
    with (directory / "preparation.tmp").open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    (directory / "preparation.tmp").replace(directory / "preparation.json")
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def main() -> int:
    control = json.loads(Path("input.json").read_text())
    raw = Path("structure.json").read_bytes()
    if _digest(raw) != control["input_sha256"]:
        raise ValueError("input checksum mismatch")
    result = run(json.loads(raw), on_prepared=write_preparation)
    output = json.dumps(result, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    with Path("result.tmp").open("xb") as stream:
        stream.write(output)
        stream.flush()
    Path("result.tmp").replace("result.json")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, TypeError, KeyError, OSError, RuntimeError, ImportError) as exc:
        Path("error.json").write_text(json.dumps({"error": type(exc).__name__, "message": str(exc)[:300]}))
        raise SystemExit(1)
