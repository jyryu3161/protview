# PROTOTYPE (M23 T1 measurement only; never product code, never imported by mw). Project .venv only.
"""Sequential multi-site mutant modeling with the UNMODIFIED M21 worker functions (spec 4 (1)), as measured in T1.

Each mutation is applied in structure order with ``openmm_mutation_worker.mutant_projection`` (PDBFixer 1.12.0 + the
M21 graft and its checks, unchanged). Between steps the atoms PDBFixer added in the previous step are rounded to four
decimals (``round(x, 4)``, equal to the ``%10.4f`` text the M21 PDBx writer gives PDBFixer); with ``round_between``
False the second step fails with ``coordinates_changed`` (T1 (a)). The final projection then goes through the M21
``_prepare`` -> ``_minimize`` path; the entry is the M21 structure entry WITHOUT ``sasa`` and ``contacts``.

Child mode (T1 (b), launched as ``[<repo>/.venv/bin/python, "-I", this file, "child"]`` with the guardian worker
environment): reads ``model_input.json`` in the cwd and writes ``model.json``, ``model.cif`` and ``receptor_bonds.json``
(sidecar whose ``source_handle`` is the mmCIF handle computed before storage) or ``error.json`` (exit 1).
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from mw import docking_inputs
from mw import mutation_model_math as mm
from mw.core.handles import HANDLE_PREFIX, canonical_json, object_sha
from mw.jobs import openmm_mutation_worker as W
from mw.mutation_candidates import identity, seven

SET_STRUCTURE_KIND = "mutation_set_model_structure"         # spec 4 (new object; M21 uses mutation_model_structure)
SET_STRUCTURE_SCHEMA = "mutation_set_model_structure@1"
SET_MODEL_SCHEMA = "mutation_set_model@1"
ROUND_DECIMALS = 4


def structure_handle(run_id: str, raw: bytes, kind: str = SET_STRUCTURE_KIND, schema: str = SET_STRUCTURE_SCHEMA
                     ) -> str:
    """The handle ``ObjectStore.put(kind, schema, raw, fmt="cif")`` will give (``core/handles.py``)."""
    return f"{HANDLE_PREFIX}{run_id}/{kind}/{object_sha(kind, schema, raw)}"


def target_index(residues: list[dict[str, Any]], residue: dict[str, Any]) -> int:
    found = [i for i, item in enumerate(residues) if identity(item["ref"]) == identity(residue)]
    if len(found) != 1:
        raise ValueError("mutation residue does not resolve to one projection residue")
    return found[0]


def sequential_projection(residues: list[dict[str, Any]], steps: list[tuple[int, str]], seed: int, *,
                          round_between: bool = True) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict]:
    """Apply ``steps`` = [(projection index, mutant resname)] in the given order. Returns the final projection, the
    added heavy atoms with their residue (7 fields) and a report of the rounding (max shift, atoms rounded)."""
    current = residues
    added_all: list[dict[str, Any]] = []
    report = {"rounded_atoms": 0, "max_round_shift_A": 0.0, "steps": []}
    for number, (index, mutant) in enumerate(steps):
        started = time.monotonic()
        projection, added = W.mutant_projection(current, index, mutant, seed)
        report["steps"].append({"index": index, "mutant": mutant, "seconds": time.monotonic() - started,
                                "added": len(added)})
        renamed = projection[index]["ref"]
        added_all.extend({"residue": seven(renamed), "atom_name": a["atom_name"], "element": a["element"]}
                         for a in added)
        if round_between and number < len(steps) - 1:
            names = {a["atom_name"] for a in added}
            atoms = []
            for atom in projection[index]["atoms"]:
                if atom["atom_name"] in names:
                    rounded = [round(x, ROUND_DECIMALS) for x in atom["coordinates_A"]]
                    shift = max(abs(p - q) for p, q in zip(rounded, atom["coordinates_A"], strict=True))
                    report["max_round_shift_A"] = max(report["max_round_shift_A"], shift)
                    report["rounded_atoms"] += 1
                    atom = {**atom, "coordinates_A": rounded}
                atoms.append(atom)
            projection = [*projection[:index], {**projection[index], "atoms": atoms}, *projection[index + 1:]]
        current = projection
    return current, added_all, report


def structure_entry(residues: list[dict[str, Any]], method: dict[str, Any], seed: int, model_number: int,
                    added: list[dict[str, Any]]) -> tuple[dict[str, Any], str, dict[str, float]]:
    """The M21 ``_prepare`` -> ``_minimize`` path; the M21 entry keys minus ``sasa``/``contacts``; the mmCIF text."""
    times = {}
    started = time.monotonic()
    prepared = W._prepare(residues, method, seed)
    times["prepare_s"] = time.monotonic() - started
    started = time.monotonic()
    before, after, final_positions = W._minimize(prepared)
    times["minimize_s"] = time.monotonic() - started
    model = prepared["model"]
    cif = W._coordinates(W.app.Modeller(model.topology, final_positions), prepared["mappings"], model_number).decode()
    final = [[float(x) for x in p.value_in_unit(W.unit.angstrom)] for p in final_positions]
    atoms = [{"residue": seven(m["residue"]), "atom_name": m["atom_name"], "element": m["element"],
              "coordinates_A": xyz} for m, xyz in zip(prepared["mappings"], final, strict=True)]
    bonds = [[a.index, b.index] for a, b in model.topology.bonds()]
    heavy = sum(a["element"] not in W.K.HYDROGEN_ELEMENTS for a in atoms)
    entry = {"structure_sha256": hashlib.sha256(cif.encode()).hexdigest(),
             "system_xml_sha256": hashlib.sha256(prepared["system_xml"]).hexdigest(),
             "topology_sha256": mm.topology_sha256(atoms, bonds), "heavy_atoms": heavy,
             "added_hydrogens": len(atoms) - heavy, "added_heavy_atoms": added,
             "protonation_variants": mm.protonation_variants(atoms, prepared["variants"]),
             "disulfide_bonds": mm.disulfide_bonds(atoms, bonds), "final_bonds": bonds, "atom_mapping": atoms,
             "energy": {"before_kJ_mol": before, "after_kJ_mol": after, **W.K.ENERGY_FIXED}}
    return entry, cif, times


def protonation_differences(entry: dict[str, Any], reference: dict[str, Any], mutated: set) -> list[dict[str, Any]]:
    """Residues outside the mutated ones whose HIS/CYS variant differs from the reference entry (prototype)."""
    ref = {identity(row["residue"]): row["variant"] for row in reference["protonation_variants"]}
    out = []
    for row in entry["protonation_variants"]:
        key = identity(row["residue"])
        if key not in mutated and key in ref and ref[key] != row["variant"]:
            out.append({"residue": row["residue"], "wild_type_reference": ref[key], "mutant": row["variant"]})
    return out


def model_individual(payload: dict[str, Any]) -> dict[str, Any]:
    """One individual (or the reference when ``mutations`` is empty): content dict + mmCIF text + sidecar bytes."""
    residues = W._flatten(payload["protein"])
    steps = sorted((target_index(residues, m["residue"]), m["mutant_resname"]) for m in payload["mutations"])
    started = time.monotonic()
    projection, added, report = sequential_projection(residues, steps, payload["seed"])
    entry, cif, times = structure_entry(projection, payload["method"], payload["seed"], payload["model_number"], added)
    times["pdbfixer_s"] = time.monotonic() - started - times["prepare_s"] - times["minimize_s"]
    raw = cif.encode()
    # T1 (c) only: ``t1_structure_kind`` names the M21 mmCIF kind to compare with a published M21 model.
    kind = payload.get("t1_structure_kind", SET_STRUCTURE_KIND)
    handle = structure_handle(payload["run_id"], raw, kind, f"{kind}@1")
    side = "mutant" if steps else "wild_type_reference"
    rows = docking_inputs.receptor_rows(raw, "cif", handle, payload["model_number"])
    sidecar = docking_inputs.mutation_model_sidecar(rows, entry["atom_mapping"], entry["final_bonds"], handle)
    mutated = {identity({**projection[i]["ref"]}) for i, _ in steps}
    reference = payload.get("reference_entry")
    content = {"schema": SET_MODEL_SCHEMA, "method_version": "mw.mutation_set_model/v1",
               "candidate_set": payload.get("candidate_set"), "structure": payload.get("structure"),
               "mutations": payload.get("mutation_rows", []), "seed": payload["seed"], "method": payload["method"],
               "structures": {side: {"structure_object": handle, **entry}},
               "protonation_differences": ([] if not steps or reference is None else
                                           protonation_differences(entry, reference, mutated)),
               "new_disulfide_in_mutant": False if reference is None else
               bool(entry["disulfide_bonds"]) and not reference["disulfide_bonds"],
               "reference_structure_sha256": None if not steps or reference is None else
               reference["structure_sha256"],
               "limitations": [W.K.L1, W.K.L3]}
    return {"content": content, "cif": cif, "sidecar": sidecar, "handle": handle, "side": side,
            "report": report, "times": times}


def _environment() -> dict[str, Any]:
    import os
    from importlib.metadata import version

    import openmm

    import mw

    return {"python": sys.executable, "prefix": sys.prefix, "mw": mw.__file__, "openmm": openmm.__version__,
            "pdbfixer": version("pdbfixer"), "environment_keys": sorted(os.environ), "flags_isolated":
            sys.flags.isolated, "chemistry_modules": sorted(m for m in ("rdkit", "meeko", "MDAnalysis")
                                                           if m in sys.modules)}


def child() -> int:
    started = time.monotonic()
    payload = json.loads(Path("model_input.json").read_text())
    try:
        out = model_individual(payload)
    except W.ModelFailure as exc:
        Path("error.json").write_text(json.dumps({"reason_code": exc.reason_code, "message": str(exc)[:300],
                                                  "detail": exc.detail}, default=str))
        return 1
    Path("model.cif").write_text(out["cif"])
    Path("receptor_bonds.json").write_bytes(out["sidecar"])
    Path("model.json").write_bytes(canonical_json(out["content"]))
    Path("t1_child.json").write_text(json.dumps({"handle": out["handle"], "side": out["side"], "times": out["times"],
                                                 "report": out["report"], "environment": _environment(),
                                                 "in_child_s": time.monotonic() - started}, sort_keys=True))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["child"]:
        raise SystemExit(2)
    raise SystemExit(child())
