"""Fixed M29 structure-repair worker (``pdbfixer_repair_v1``), launched by the authenticated local guardian.

Runs in the project ``.venv`` like the M7 and M21 workers. It is the only M29 module that imports PDBFixer; server
modules never import it. It returns the atoms PDBFixer ADDS and nothing else: the server splices them into the
prepared structure (``structure_repair.build_repaired``), so no observed atom ever comes from this process.

Launch: cwd = the private attempt directory with ``input.json`` (control; ``input_sha256`` = SHA-256 of the
``structure.json`` bytes) and ``structure.json`` (the staged payload, ``INPUT_SCHEMA``):

    schema        "structure_repair_worker_input@1"
    method        the job's pinned method record: ``openmm_method.dependencies()`` + ``pdbfixer_version`` (exactly
                  ``mutation_model_constants.METHOD_KEYS``; rechecked here with the M7 fingerprint check)
    seed          ``REPAIR_SEED`` (1, a constant, never an argument)
    model_number  int, the prepared structure's model number
    chains        the protein polymer residues of the prepared structure, chain parts merged by author chain (order
                  of first appearance, parts in input order), heavy atoms only, INPUT identities (an MSE residue is
                  still MSE with its SE atom): ``[{chain_auth, residues: [{ref (7 fields), atoms: [{atom_name,
                  element, coordinates_A}]}], gaps: [{before_index, residues: [7 fields + resname]}]}]``; a gap's
                  residues go in front of ``residues[before_index]`` (the server analysis decided them from the
                  file's sequence and unobserved-residue listing; nothing here guesses an identity)

Procedure (the T1 measurement, ``docs/qa/m29-repair-20261013/probe/pdbfixer_measure.py``):
1. MSE -> MET before PDBFixer sees the residue: the residue name and the SE atom's name and element only (SE -> SD,
   Se -> S, coordinates kept). PDBFixer's own replacement re-places SD on the template, so it is never used.
2. M21 topology (chain id ``str(chain index)``, residue id ``str(global index + 1)``, Å) -> ``createStandardBonds`` +
   ``createDisulfideBonds`` -> ``PDBxFile.writeFile(keepIds=True)`` -> ``PDBFixer(pdbxfile=..., platform=CPU
   Threads=1)``.
3. ``missingResidues`` is SET from the staged gaps (``findMissingResidues`` is never called: it matches the sequence
   by author number and label chain id) -> ``findMissingAtoms`` -> ``addMissingAtoms(seed=1)``.
4. PDBFixer's residues are walked against the planned order (gap residues in front of their ``before_index``): every
   observed atom must come back with its name and element within ``COORDINATE_TOLERANCE_A`` (1e-9 Å), else
   ``coordinates_changed``; a residue count, chain, order or name that is not the plan is
   ``repair_identity_mismatch``; the remaining atoms are the added atoms, ``origin`` ``gap_residue`` (every atom of a
   gap residue), ``oxt`` or ``side_chain``, at PDBFixer precision (the server rounds them to four decimals).

Success writes ``result.json`` (sorted keys, compact separators, no NaN, at most ``MAX_OUTPUT_BYTES``):

    schema       "structure_repair_worker_output@1"
    method       the verified payload method
    engine       {pdbfixer_version, openmm_distribution_version, forcefield_files_sha256} as this process found them
    added_atoms  [{residue (7 fields, MET for an MSE residue; a gap residue's staged identity), atom_name, element,
                   coordinates_A, origin}] in PDBFixer output (structure) order
    diagnostics  {observed_atoms, observed_max_delta_A, residues_with_missing_atoms, missing_terminals,
                  added_residues} (not stored by the server)

Failure writes ``error.json`` ``{"reason_code", "message", "detail"}`` with a reason from
``structure_repair_constants.FAILURE_REASON_CODES`` and exits 1 (PDBFixer exceptions are ``repair_modeling_failed``;
payload, engine and runtime errors are ``engine_failed``).
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from importlib.metadata import version
from pathlib import Path
from typing import Any

import openmm
from openmm import app, unit
from pdbfixer import PDBFixer

from mw import structure_repair_constants as K
from mw.jobs.openmm_worker import _verify_method
from mw.mutation_model_constants import METHOD_KEYS

INPUT_SCHEMA = "structure_repair_worker_input@1"
OUTPUT_SCHEMA = "structure_repair_worker_output@1"
PAYLOAD_KEYS = frozenset({"schema", "method", "seed", "model_number", "chains"})
CHAIN_KEYS = frozenset({"chain_auth", "residues", "gaps"})
MAX_OUTPUT_BYTES = 4_000_000   # = structure_repair_jobs.OUTPUT_LIMIT = the guardian's read bound


class RepairFailure(Exception):
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


# --- input ---------------------------------------------------------------------------------------------------------

def _verify_payload(payload: Any) -> None:
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_KEYS or payload["schema"] != INPUT_SCHEMA:
        raise ValueError("fixed structure-repair payload mismatch")
    method = payload["method"]
    if not isinstance(method, dict) or set(method) != set(METHOD_KEYS):
        raise ValueError("fixed structure-repair method keys mismatch")
    if method["pdbfixer_version"] != K.PDBFIXER_VERSION or version("pdbfixer") != K.PDBFIXER_VERSION:
        raise ValueError("PDBFixer distribution version differs from pinned 1.12.0")
    _verify_method(method)
    if payload["seed"] != K.REPAIR_SEED or type(payload["seed"]) is not int or type(payload["model_number"]) is not int:
        raise ValueError("invalid structure-repair seed or model number")
    chains = payload["chains"]
    if not isinstance(chains, list) or not chains:
        raise ValueError("no protein chain staged")
    for chain in chains:
        if not isinstance(chain, dict) or set(chain) != CHAIN_KEYS or not chain["residues"]:
            raise ValueError("invalid staged chain")
        for residue in chain["residues"]:
            if set(residue) != {"ref", "atoms"} or set(residue["ref"]) != set(K.IDENTITY_FIELDS):
                raise ValueError("invalid staged residue")
            for atom in residue["atoms"]:
                if (set(atom) != {"atom_name", "element", "coordinates_A"} or len(atom["coordinates_A"]) != 3 or
                        atom["element"] in K.HYDROGEN_ELEMENTS or
                        not all(type(x) in (int, float) and math.isfinite(x) for x in atom["coordinates_A"])):
                    raise ValueError("invalid staged atom")
        for gap in chain["gaps"]:
            if (set(gap) != {"before_index", "residues"} or type(gap["before_index"]) is not int or
                    not 0 < gap["before_index"] < len(chain["residues"]) or not gap["residues"] or
                    any(set(ref) != set(K.IDENTITY_FIELDS) for ref in gap["residues"])):
                raise ValueError("invalid staged gap")


def _fixer_view(residue: dict[str, Any]) -> tuple[str, list[dict[str, Any]], bool]:
    """Step 1: the residue name and atoms PDBFixer sees (MSE -> MET, SE -> SD, Se -> S, coordinates kept)."""
    name = residue["ref"]["resname"]
    mse = name in K.NONSTANDARD_REPLACEMENT
    if not mse:
        return name, residue["atoms"], False
    names = K.REPLACED_ATOM_NAMES[name]
    elements = K.REPLACED_ATOM_ELEMENTS[name]
    atoms = []
    for atom in residue["atoms"]:
        renamed = names.get(atom["atom_name"])
        if renamed is None:
            atoms.append(atom)
            continue
        source, target = elements[atom["atom_name"]]
        element = target if atom["element"] in (source, target) else atom["element"]
        atoms.append({**atom, "atom_name": renamed, "element": element})
    return K.NONSTANDARD_REPLACEMENT[name], atoms, True


# --- PDBFixer --------------------------------------------------------------------------------------------------------

def _pdbfixer(views: list[list[tuple[str, list[dict[str, Any]]]]], chains: list[dict[str, Any]],
              seed: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Steps 2-3: PDBFixer's residues ``{chain_id, resname, atoms: [{atom_name, element, coordinates_A}]}``."""
    topology = app.Topology()
    positions = []
    index = 0
    for chain_index, residues in enumerate(views):
        chain = topology.addChain(str(chain_index))
        for name, atoms in residues:
            added = topology.addResidue(name, chain, id=str(index + 1))
            index += 1
            for atom in atoms:
                topology.addAtom(atom["atom_name"], app.element.get_by_symbol(atom["element"]), added)
                positions.append(openmm.Vec3(*atom["coordinates_A"]))
    quantity = unit.Quantity(positions, unit.angstrom)
    topology.createStandardBonds()
    topology.createDisulfideBonds(quantity)
    text = io.StringIO()
    app.PDBxFile.writeFile(topology, quantity, text, keepIds=True)
    try:
        fixer = PDBFixer(pdbxfile=io.StringIO(text.getvalue()), platform=_cpu())
        fixer.missingResidues = {(chain_index, gap["before_index"]): [ref["resname"] for ref in gap["residues"]]
                                 for chain_index, chain in enumerate(chains) for gap in chain["gaps"]}
        fixer.findMissingAtoms()
        flagged = {"residues_with_missing_atoms": len(fixer.missingAtoms),
                   "missing_terminals": len(fixer.missingTerminals)}
        fixer.addMissingAtoms(seed=seed)
    except Exception as exc:   # PDBFixer has no closed error set; any refusal is a modeling failure
        raise RepairFailure("repair_modeling_failed", f"PDBFixer could not complete the structure: "
                                                      f"{type(exc).__name__}: {str(exc)[:200]}") from exc
    out = [{"chain_id": r.chain.id, "resname": r.name,
            "atoms": [{"atom_name": a.name, "element": a.element.symbol if a.element is not None else None,
                       "coordinates_A": [float(x) for x in fixer.positions[a.index].value_in_unit(unit.angstrom)]}
                      for a in r.atoms()]}
           for r in fixer.topology.residues()]
    return out, flagged


def added_atoms(chains: list[dict[str, Any]], views: list[list[tuple[str, list[dict[str, Any]]]]],
                fixed: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Step 4: the atoms PDBFixer added, in its output order, and the observed-atom check."""
    planned: list[tuple[str, int, Any, Any]] = []   # (kind, chain index, staged residue or gap ref, fixer view)
    for chain_index, chain in enumerate(chains):
        gaps = {gap["before_index"]: gap["residues"] for gap in chain["gaps"]}
        for position, (residue, view) in enumerate(zip(chain["residues"], views[chain_index], strict=True)):
            planned.extend(("gap", chain_index, ref, None) for ref in gaps.get(position, []))
            planned.append(("observed", chain_index, residue, view))
    if len(fixed) != len(planned):
        raise RepairFailure("repair_identity_mismatch", "PDBFixer returned another number of residues",
                            {"planned": len(planned), "returned": len(fixed)})
    added: list[dict[str, Any]] = []
    observed = 0
    max_delta = 0.0
    for out, (kind, chain_index, staged, view) in zip(fixed, planned, strict=True):
        names = [atom["atom_name"] for atom in out["atoms"]]
        if out["chain_id"] != str(chain_index) or len(set(names)) != len(names):
            raise RepairFailure("repair_identity_mismatch", "PDBFixer changed the chain order or an atom identity")
        if any(atom["element"] is None for atom in out["atoms"]):
            raise RepairFailure("unexpected_atoms_added", "PDBFixer added an atom without an element")
        if kind == "gap":
            if out["resname"] != staged["resname"]:
                raise RepairFailure("repair_identity_mismatch", "a gap residue is not the listed residue",
                                    {"residue": staged, "returned": out["resname"]})
            added.extend({"residue": staged, **atom, "origin": "gap_residue"} for atom in out["atoms"])
            continue
        name, atoms = view
        ref = staged["ref"]
        residue = {**ref, "resname": name}
        if out["resname"] != name:
            raise RepairFailure("repair_identity_mismatch", "PDBFixer renamed an observed residue", {"residue": ref})
        returned = {atom["atom_name"]: atom for atom in out["atoms"]}
        for atom in atoms:
            found = returned.get(atom["atom_name"])
            if found is None or found["element"] != atom["element"]:
                raise RepairFailure("coordinates_changed", "PDBFixer removed or changed an observed atom",
                                    {"residue": ref, "atom_name": atom["atom_name"]})
            shift = math.dist(found["coordinates_A"], atom["coordinates_A"])
            if not shift <= K.COORDINATE_TOLERANCE_A:
                raise RepairFailure("coordinates_changed", "PDBFixer moved an observed atom",
                                    {"residue": ref, "atom_name": atom["atom_name"], "shift_A": shift})
            max_delta = max(max_delta, shift)
            observed += 1
        kept = {atom["atom_name"] for atom in atoms}
        added.extend({"residue": residue, **atom, "origin": "oxt" if atom["atom_name"] == K.TERMINAL_OXT
                      else "side_chain"} for atom in out["atoms"] if atom["atom_name"] not in kept)
    return added, {"observed_atoms": observed, "observed_max_delta_A": max_delta,
                   "added_residues": sum(kind == "gap" for kind, *_ in planned)}


def run(payload: dict[str, Any]) -> dict[str, Any]:
    _verify_payload(payload)
    chains = payload["chains"]
    views: list[list[tuple[str, list[dict[str, Any]]]]] = []
    for chain in chains:
        views.append([_fixer_view(residue)[:2] for residue in chain["residues"]])
    fixed, flagged = _pdbfixer(views, chains, payload["seed"])
    rows, diagnostics = added_atoms(chains, views, fixed)
    method = payload["method"]
    return {"schema": OUTPUT_SCHEMA, "method": method,
            "engine": {"pdbfixer_version": version("pdbfixer"), "openmm_distribution_version": version("openmm"),
                       "forcefield_files_sha256": method["forcefield_files_sha256"]},
            "added_atoms": rows, "diagnostics": {**diagnostics, **flagged}}


def encode_output(result: dict[str, Any]) -> bytes:
    raw = json.dumps(result, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > MAX_OUTPUT_BYTES:
        raise RepairFailure("resource_exceeded", "worker output exceeds the fixed limit",
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
    except RepairFailure as exc:
        Path("error.json").write_text(json.dumps({"reason_code": exc.reason_code, "message": str(exc)[:300],
                                                  "detail": exc.detail}, allow_nan=False, default=str))
        raise SystemExit(1)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, ArithmeticError, OSError, RuntimeError,
            ImportError, openmm.OpenMMException) as exc:   # engines or payload: the closed engine failure
        Path("error.json").write_text(json.dumps({"reason_code": "engine_failed",
                                                  "message": f"{type(exc).__name__}: {str(exc)[:300]}",
                                                  "detail": {"reason_code": "engine_failed"}}))
        raise SystemExit(1)
