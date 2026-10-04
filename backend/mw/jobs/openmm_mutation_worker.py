"""Fixed M21 mutation-model worker (``openmm_mutation_model_v1``), launched by the authenticated local guardian.

Runs in the project ``.venv`` like the M7 worker (``openmm_worker.py``, whose method check and mmCIF writer it reuses
unchanged). It is the only module that imports PDBFixer; server modules never import it.

Launch: cwd = the private attempt directory with ``input.json`` (control; ``input_sha256`` = SHA-256 of the
``structure.json`` bytes, other keys ignored) and ``structure.json`` (the staged payload, ``INPUT_SCHEMA``):

    schema            "openmm_mutation_model_input@1"
    method            openmm_method.dependencies() + {"pdbfixer_version": importlib.metadata.version("pdbfixer")}
                      (exactly ``mutation_model_constants.METHOD_KEYS``; rechecked here with the M7 fingerprint check)
    model_number      int, the prepared structure's model number (M7 preflight ``model_number``)
    protein           the M7 preflight heavy-atom projection ``preflight(...)["protein"]``, unchanged
    seed              int (the request seed)
    residue           the original 7 residue fields of the candidate position (must resolve to one projection residue)
    mutant_resname    standard three-letter name of the candidate ``to`` residue
    contact_cutoff_A  float, the normalized request cutoff

Both structures go through the same code path (``_prepare`` -> ``_minimize`` -> ``_entry``): M7 topology (chain id
``str(chain_index)``, residue id ``str(global index + 1)``, Å), ``createStandardBonds`` + ``createDisulfideBonds``,
``Modeller.addHydrogens`` at pH 7.0 on CPU with Threads=1, Amber14-all + GBn2 System (only its SHA-256 is kept), the
potential before and after at most 50 minimization iterations and the M7 energy sanity check; Python and NumPy RNGs
are seeded with ``seed`` before each structure, exactly as M7 seeds them before its one structure.

Only the mutant goes through PDBFixer 1.12.0 (public API, measured in T1): the M7 topology written as PDBx text ->
``PDBFixer(pdbxfile=...)`` -> ``findMissingResidues`` (must find none) -> ``applyMutations`` (atoms whose names exist in
the new template are kept by PDBFixer) -> ``findMissingAtoms`` (only the mutated residue may miss atoms) ->
``addMissingAtoms(seed)``. Then the graft (``_graft``): every residue outside the mutated one must come back with the
same name, atom names, elements and order and coordinates within ``GRAFT_TOLERANCE_A`` (PDBFixer stores nm, so values
differ in the last bit); the input coordinates are restored for every atom that existed in the input (inside the
mutated residue too, including an OXT that PDBFixer re-places on a C-terminal mutation); only atoms PDBFixer added keep
its coordinates. The mutated residue's heavy-atom names must equal the fixed force-field template.

Success writes ``result.json`` (sorted keys, compact separators, no NaN, at most ``MAX_OUTPUT_BYTES``):

    schema                    "mutation_model_worker_output@1"
    method                    the verified payload method
    structures                {wild_type_reference, mutant}: every ``mutation_model@1`` structure-entry key except
                              ``structure_object`` (the server stores the mmCIF and adds that handle)
    structure_cifs            {wild_type_reference, mutant}: the final mmCIF text (standard HIS/CYS names; the
                              OpenMM variant names are only in ``protonation_variants``); ``structure_sha256`` is the
                              SHA-256 of its UTF-8 bytes
    comparison, protonation_differences, limitations    as in ``mutation_model@1``

No energy difference, change or delta is computed or written anywhere. Failure writes ``error.json``
``{"reason_code", "message", "detail"}`` with a reason from ``FAILURE_REASON_CODES`` and exits 1.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import random
from importlib.metadata import version
from pathlib import Path
from typing import Any

import freesasa
import gemmi
import numpy as np
import openmm
from openmm import app, unit
from pdbfixer import PDBFixer

from mw import mutation_model_constants as K
from mw import mutation_model_math as mm
from mw.core.errors import ToolFailure
from mw.jobs.openmm_worker import _coordinates, _verify_method
from mw.mutation_candidates import identity, seven
from mw.tools.openmm_method import _template_heavy

INPUT_SCHEMA = "openmm_mutation_model_input@1"
OUTPUT_SCHEMA = "mutation_model_worker_output@1"
PAYLOAD_KEYS = frozenset({"schema", "method", "model_number", "protein", "seed", "residue", "mutant_resname",
                          "contact_cutoff_A"})
MAX_OUTPUT_BYTES = 64_000_000   # spec 5; 1UBQ measures about 0.6 MB (T1 (c))
GRAFT_TOLERANCE_A = 1e-9        # PDBFixer nm round trip differs by at most ~7.1e-15 Å (T1 B2)


class ModelFailure(Exception):
    """A closed job failure (``reason_code`` in ``FAILURE_REASON_CODES``)."""

    def __init__(self, reason_code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        if reason_code not in K.FAILURE_REASON_CODES:
            raise ValueError(f"unknown failure reason {reason_code}")
        super().__init__(message)
        self.reason_code = reason_code
        self.detail = {"reason_code": reason_code, **(detail or {})}


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _cpu() -> openmm.Platform:
    platform = openmm.Platform.getPlatformByName("CPU")
    platform.setPropertyDefaultValue("Threads", "1")
    return platform


def _seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed % (2**32))


# --- input ---------------------------------------------------------------------------------------------------------

def _verify_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_KEYS or payload["schema"] != INPUT_SCHEMA:
        raise ValueError("fixed mutation-model payload mismatch")
    method = payload["method"]
    if not isinstance(method, dict) or set(method) != set(K.METHOD_KEYS):
        raise ValueError("fixed mutation-model method keys mismatch")
    fixed = {**K.M7_METHOD_FIXED, **K.MUTATION_METHOD_FIXED}
    if any(json.dumps(method[k], sort_keys=True) != json.dumps(v, sort_keys=True) for k, v in fixed.items()):
        raise ValueError("fixed mutation-model method mismatch")
    if version("pdbfixer") != K.PDBFIXER_VERSION:
        raise ValueError("PDBFixer distribution version differs from pinned 1.12.0")
    if version("freesasa") != K.SASA_PARAMETERS["engine_version"]:
        raise ValueError("FreeSASA distribution version differs from the M6 parameters")
    _verify_method(method)
    low, high = K.CONTACT_CUTOFF_RANGE_A
    if (type(payload["seed"]) is not int or type(payload["model_number"]) is not int
            or type(payload["contact_cutoff_A"]) is not float or not low <= payload["contact_cutoff_A"] <= high
            or payload["mutant_resname"] not in K.THREE_LETTER.values()
            or payload["mutant_resname"] == payload["residue"]["resname"]):
        raise ValueError("invalid mutation-model arguments")


def _flatten(protein: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Projection residues in structure order: chain index/auth, residue ref and heavy atoms."""
    return [{"chain_index": chain_index, "chain_auth": chain["chain_auth"], "ref": residue["residue"],
             "atoms": [{"atom_name": a["atom_name"], "element": a["element"], "coordinates_A": a["coordinates_A"]}
                       for a in residue["atoms"]]}
            for chain_index, chain in enumerate(protein) for residue in chain["residues"]]


def _target(residues: list[dict[str, Any]], residue: dict[str, Any]) -> int:
    found = [i for i, item in enumerate(residues) if identity(item["ref"]) == identity(residue)]
    if len(found) != 1:
        raise ValueError("the candidate residue does not resolve to one projection residue")
    return found[0]


def _terminal(residues: list[dict[str, Any]], index: int) -> bool:
    return index == len(residues) - 1 or residues[index + 1]["chain_index"] != residues[index]["chain_index"]


def _topology(residues: list[dict[str, Any]]) -> tuple[app.Topology, Any]:
    """As the M7 worker: chain id ``str(chain index)``, residue id ``str(global index + 1)``, positions in Å."""
    topology = app.Topology()
    positions = []
    chains: dict[int, Any] = {}
    for index, residue in enumerate(residues):
        if residue["chain_index"] not in chains:
            chains[residue["chain_index"]] = topology.addChain(str(residue["chain_index"]))
        added = topology.addResidue(residue["ref"]["resname"], chains[residue["chain_index"]], id=str(index + 1))
        for atom in residue["atoms"]:
            topology.addAtom(atom["atom_name"], app.element.get_by_symbol(atom["element"]), added)
            positions.append(openmm.Vec3(*atom["coordinates_A"]))
    return topology, unit.Quantity(positions, unit.angstrom)


# --- mutant side chain (PDBFixer) ----------------------------------------------------------------------------------

def _pdbfixer(residues: list[dict[str, Any]], index: int, mutant_resname: str, seed: int) -> list[dict[str, Any]]:
    """PDBFixer's residues after mutating ``residues[index]``: ``{chain_id, id, resname, atoms: [{atom_name,
    element, coordinates_A}]}``. Refuses before ``addMissingAtoms`` if PDBFixer would add anything elsewhere."""
    topology, positions = _topology(residues)
    topology.createStandardBonds()
    topology.createDisulfideBonds(positions)
    text = io.StringIO()
    app.PDBxFile.writeFile(topology, positions, text, keepIds=True)
    target = (str(residues[index]["chain_index"]), str(index + 1))
    try:
        fixer = PDBFixer(pdbxfile=io.StringIO(text.getvalue()), platform=_cpu())
        fixer.findMissingResidues()
        if fixer.missingResidues:
            raise ModelFailure("unexpected_atoms_added", "PDBFixer would add missing residues")
        fixer.applyMutations([f"{residues[index]['ref']['resname']}-{index + 1}-{mutant_resname}"], target[0])
        fixer.findMissingAtoms()
        flagged = {(r.chain.id, r.id) for r in (*fixer.missingAtoms, *fixer.missingTerminals)}
        if flagged - {target} or fixer.missingResidues:
            raise ModelFailure("unexpected_atoms_added", "PDBFixer would add atoms outside the mutated residue",
                               {"residues": sorted(f"{c}:{r}" for c, r in flagged - {target})})
        fixer.addMissingAtoms(seed=seed)
    except ModelFailure:
        raise
    except Exception as exc:   # PDBFixer has no closed error set; any refusal is a modeling failure
        raise ModelFailure("mutation_modeling_failed", f"PDBFixer could not model the mutation: "
                                                       f"{type(exc).__name__}: {str(exc)[:200]}") from exc
    return [{"chain_id": r.chain.id, "id": r.id, "resname": r.name,
             "atoms": [{"atom_name": a.name, "element": a.element.symbol if a.element is not None else None,
                        "coordinates_A": [float(x) for x in fixer.positions[a.index].value_in_unit(unit.angstrom)]}
                       for a in r.atoms()]}
            for r in fixer.topology.residues()]


def _graft(residues: list[dict[str, Any]], fixed: list[dict[str, Any]], index: int,
           mutant_resname: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """The mutant heavy-atom projection and the atoms PDBFixer added (spec 3.3).

    Outside the mutated residue PDBFixer must return the same residues, names, elements and order with coordinates
    within ``GRAFT_TOLERANCE_A``; the projection uses the input coordinates there and for every mutated-residue atom
    that existed in the input, and PDBFixer's coordinates only for the atoms it added."""
    if len(fixed) > len(residues) or any(a["element"] in K.HYDROGEN_ELEMENTS or a["element"] is None
                                         for r in fixed for a in r["atoms"]):
        raise ModelFailure("unexpected_atoms_added", "PDBFixer added residues or hydrogens")
    if len(fixed) != len(residues):
        raise ModelFailure("mutation_modeling_failed", "PDBFixer removed residues")
    for k, (source, out) in enumerate(zip(residues, fixed, strict=True)):
        if out["chain_id"] != str(source["chain_index"]) or out["id"] != str(k + 1):
            raise ModelFailure("mutation_modeling_failed", "PDBFixer changed the residue order")
        if k == index:
            continue
        names = [a["atom_name"] for a in source["atoms"]]
        got = [a["atom_name"] for a in out["atoms"]]
        if set(got) - set(names):
            raise ModelFailure("unexpected_atoms_added", "PDBFixer added atoms outside the mutated residue",
                               {"residue": seven(source["ref"]), "atoms": sorted(set(got) - set(names))})
        if (got != names or out["resname"] != source["ref"]["resname"]
                or [a["element"] for a in out["atoms"]] != [a["element"] for a in source["atoms"]]):
            raise ModelFailure("mutation_modeling_failed", "PDBFixer changed a residue outside the mutated residue",
                               {"residue": seven(source["ref"])})
        shift = max(abs(p - q) for a, b in zip(source["atoms"], out["atoms"], strict=True)
                    for p, q in zip(a["coordinates_A"], b["coordinates_A"], strict=True))
        if not shift <= GRAFT_TOLERANCE_A:
            raise ModelFailure("coordinates_changed", "PDBFixer moved an atom outside the mutated residue",
                               {"residue": seven(source["ref"]), "max_abs_shift_A": shift})
    mutated = fixed[index]
    names = [a["atom_name"] for a in mutated["atoms"]]
    try:
        template = _template_heavy(mutant_resname, terminal=_terminal(residues, index))
    except ToolFailure as exc:
        raise ModelFailure("mutation_modeling_failed", "no fixed force-field template for the mutant") from exc
    if mutated["resname"] != mutant_resname or len(set(names)) != len(names) or set(names) != template:
        raise ModelFailure("mutation_modeling_failed", "the mutated residue does not match the force-field template",
                           {"missing": sorted(template - set(names)), "extra": sorted(set(names) - template)})
    source_atoms = {a["atom_name"]: a for a in residues[index]["atoms"]}
    atoms, added = [], []
    for atom in mutated["atoms"]:
        kept = source_atoms.get(atom["atom_name"])
        if kept is not None and kept["element"] != atom["element"]:
            raise ModelFailure("mutation_modeling_failed", "a kept atom changed element")
        if kept is None:
            added.append({"atom_name": atom["atom_name"], "element": atom["element"]})
        atoms.append(kept if kept is not None else atom)
    projection = [dict(r) for r in residues]
    projection[index] = {**residues[index], "ref": {**residues[index]["ref"], "resname": mutant_resname},
                         "atoms": atoms}
    return projection, added


def mutant_projection(residues: list[dict[str, Any]], index: int, mutant_resname: str,
                      seed: int) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """PDBFixer + graft: the mutant heavy-atom projection and the PDBFixer-added atoms."""
    return _graft(residues, _pdbfixer(residues, index, mutant_resname, seed), index, mutant_resname)


# --- one structure (same path for both sides) ----------------------------------------------------------------------

def _prepare(residues: list[dict[str, Any]], method: dict[str, Any], seed: int) -> dict[str, Any]:
    """Bonds, hydrogens at pH 7 and the System, before any potential evaluation."""
    _seed(seed)
    topology, positions = _topology(residues)
    topology.createStandardBonds()
    topology.createDisulfideBonds(positions)
    if not any(True for _ in topology.bonds()):
        raise ModelFailure("topology_unsupported", "no standard protein bonds")
    model = app.Modeller(topology, positions)
    ff = app.ForceField(*method["forcefield_files"])
    platform = _cpu()
    try:
        variants = model.addHydrogens(ff, pH=method["pH"], platform=platform)
        system = ff.createSystem(model.topology, nonbondedMethod=app.NoCutoff, constraints=None)
    except ValueError as exc:   # no matching template
        raise ModelFailure("topology_unsupported", f"force-field template: {str(exc)[:200]}") from exc
    heavy = {(k, a["atom_name"]): a for k, r in enumerate(residues) for a in r["atoms"]}
    mappings, seen = [], set()
    for atom in model.topology.atoms():
        k = int(atom.residue.id) - 1
        source = heavy.get((k, atom.name))
        if (source is None and atom.element.symbol != "H") or (source is not None and
                                                                atom.element.symbol != source["element"]):
            raise ModelFailure("topology_unsupported", "hydrogen construction changed a heavy atom")
        if (k, atom.name) in seen:
            raise ModelFailure("topology_unsupported", "ambiguous final atom mapping")
        seen.add((k, atom.name))
        mappings.append({"residue": residues[k]["ref"], "atom_name": atom.name, "element": atom.element.symbol,
                         "chain_index": residues[k]["chain_index"], "chain_auth": residues[k]["chain_auth"],
                         "residue_index": k})
    if len(mappings) != model.topology.getNumAtoms() or len(seen & set(heavy)) != len(heavy):
        raise ModelFailure("topology_unsupported", "atom mapping count mismatch")
    by_residue = {identity(residues[k]["ref"]): v for k, v in enumerate(variants)}
    return {"model": model, "system": system, "platform": platform, "mappings": mappings, "variants": by_residue,
            "system_xml": openmm.XmlSerializer.serialize(system).encode(),
            "input_positions_A": [[float(x) for x in p.value_in_unit(unit.angstrom)] for p in model.positions]}


def _check_energy(before: float, after: float) -> None:
    if not (math.isfinite(before) and math.isfinite(after)) or after > before + K.ENERGY_INCREASE_TOLERANCE_KJ_MOL:
        raise ModelFailure("energy_invalid", "nonfinite or substantially increased potential")


def _minimize(prepared: dict[str, Any]) -> tuple[float, float, Any]:
    model = prepared["model"]
    integrator = openmm.VerletIntegrator(0.001 * unit.picoseconds)
    simulation = app.Simulation(model.topology, prepared["system"], integrator, prepared["platform"], {"Threads": "1"})
    simulation.context.setPositions(model.positions)
    before = simulation.context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    simulation.minimizeEnergy(tolerance=10 * unit.kilojoule_per_mole / unit.nanometer, maxIterations=50)
    state = simulation.context.getState(getEnergy=True, getPositions=True)
    after = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    _check_energy(before, after)
    return before, after, state.getPositions()


def residue_sasa(atoms: list[dict[str, Any]], residue: dict[str, Any]) -> float:
    """FreeSASA (M6 parameters) over every heavy atom of the model; the area of ``residue``'s atoms (Å²)."""
    heavy = [a for a in atoms if a["element"] not in K.HYDROGEN_ELEMENTS]
    origin = [min(a["coordinates_A"][axis] for a in heavy) for axis in range(3)]
    coordinates = [x - origin[axis] for a in heavy for axis, x in enumerate(a["coordinates_A"])]
    radii = [gemmi.Element(a["element"]).vdw_r for a in heavy]
    params = freesasa.Parameters({"algorithm": freesasa.LeeRichards, "probe-radius": K.SASA_PARAMETERS["probe_radius_A"],
                                  "n-slices": K.SASA_PARAMETERS["n_slices"], "n-threads": K.SASA_PARAMETERS["threads"]})
    result = freesasa.calcCoord(coordinates, radii, params)
    if result.nAtoms() != len(heavy):
        raise ModelFailure("engine_failed", "FreeSASA atom count mismatch")
    key = identity(residue)
    value = float(sum(result.atomArea(i) for i, a in enumerate(heavy) if identity(a["residue"]) == key))
    if not math.isfinite(value) or value < 0:
        raise ModelFailure("engine_failed", "invalid FreeSASA area")
    return value


def _entry(prepared: dict[str, Any], final_positions: Any, before: float, after: float, mutated: dict[str, Any],
           added: list[dict[str, str]], cutoff: float, model_number: int) -> tuple[dict[str, Any], str]:
    """One ``mutation_model@1`` structure entry (without ``structure_object``) and its mmCIF text."""
    model = prepared["model"]
    cif = _coordinates(app.Modeller(model.topology, final_positions), prepared["mappings"], model_number).decode()
    final = [[float(x) for x in p.value_in_unit(unit.angstrom)] for p in final_positions]
    atoms = [{"residue": seven(m["residue"]), "atom_name": m["atom_name"], "element": m["element"],
              "coordinates_A": xyz} for m, xyz in zip(prepared["mappings"], final, strict=True)]
    bonds = [[a.index, b.index] for a, b in model.topology.bonds()]
    try:
        contacts = mm.contacts(atoms, bonds, mutated, cutoff)
    except mm.ContactLimitExceeded as exc:
        raise ModelFailure("resource_exceeded", str(exc), exc.detail) from exc
    heavy = sum(a["element"] not in K.HYDROGEN_ELEMENTS for a in atoms)
    entry = {"structure_sha256": _digest(cif.encode()), "system_xml_sha256": _digest(prepared["system_xml"]),
             "topology_sha256": mm.topology_sha256(atoms, bonds), "heavy_atoms": heavy,
             "added_hydrogens": len(atoms) - heavy, "added_heavy_atoms": added,
             "protonation_variants": mm.protonation_variants(atoms, prepared["variants"]),
             "disulfide_bonds": mm.disulfide_bonds(atoms, bonds), "final_bonds": bonds, "atom_mapping": atoms,
             "energy": {"before_kJ_mol": before, "after_kJ_mol": after, **K.ENERGY_FIXED},
             "sasa": {"residue": seven(mutated), "engine": K.SASA_ENGINE, "value_A2": residue_sasa(atoms, mutated),
                      "parameters": dict(K.SASA_PARAMETERS)},
             "contacts": contacts}
    return entry, cif


def model_structure(residues: list[dict[str, Any]], mutated: dict[str, Any], added: list[dict[str, str]],
                    payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    prepared = _prepare(residues, payload["method"], payload["seed"])
    before, after, final_positions = _minimize(prepared)
    return _entry(prepared, final_positions, before, after, mutated, added, payload["contact_cutoff_A"],
                  payload["model_number"])


def run(payload: dict[str, Any]) -> dict[str, Any]:
    _verify_payload(payload)
    residues = _flatten(payload["protein"])
    index = _target(residues, payload["residue"])
    original = seven(payload["residue"])
    renamed = {**original, "resname": payload["mutant_resname"]}
    projection, added = mutant_projection(residues, index, payload["mutant_resname"], payload["seed"])
    wild, wild_cif = model_structure(residues, original, [], payload)
    mutant, mutant_cif = model_structure(projection, renamed, added, payload)
    comparison, differences = mm.compare_structures(
        {"residue": original, "mutant_resname": payload["mutant_resname"]}, wild, mutant)
    limitations = K.applicable_limitations(protonation_difference_count=comparison["protonation_difference_count"],
                                           new_disulfide_in_mutant=comparison["new_disulfide_in_mutant"])
    return {"schema": OUTPUT_SCHEMA, "method": payload["method"],
            "structures": {"wild_type_reference": wild, "mutant": mutant},
            "structure_cifs": {"wild_type_reference": wild_cif, "mutant": mutant_cif},
            "comparison": comparison, "protonation_differences": differences, "limitations": list(limitations)}


def encode_output(result: dict[str, Any]) -> bytes:
    raw = json.dumps(result, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > MAX_OUTPUT_BYTES:
        raise ModelFailure("resource_exceeded", "worker output exceeds the fixed limit",
                           {"limit": "output_bytes", "bytes": len(raw), "max_bytes": MAX_OUTPUT_BYTES})
    return raw


def main() -> int:
    control = json.loads(Path("input.json").read_text())
    raw = Path("structure.json").read_bytes()
    if _digest(raw) != control["input_sha256"]:
        raise ValueError("input checksum mismatch")
    output = encode_output(run(json.loads(raw)))
    with Path("result.tmp").open("xb") as stream:
        stream.write(output)
        stream.flush()
    Path("result.tmp").replace("result.json")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ModelFailure as exc:
        Path("error.json").write_text(json.dumps({"reason_code": exc.reason_code, "message": str(exc)[:300],
                                                  "detail": exc.detail}, allow_nan=False, default=str))
        raise SystemExit(1)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, ArithmeticError, OSError, RuntimeError,
            ImportError, openmm.OpenMMException) as exc:   # engines or payload: the closed engine failure
        Path("error.json").write_text(json.dumps({"reason_code": "engine_failed",
                                                  "message": f"{type(exc).__name__}: {str(exc)[:300]}",
                                                  "detail": {"reason_code": "engine_failed"}}))
        raise SystemExit(1)
