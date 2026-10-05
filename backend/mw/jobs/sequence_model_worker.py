"""M23 modeling program (spec .dryforge/spec.md 4 (1), 8 "child contract"): one sequence GA individual, or the
wild-type reference row, as a ``mutation_set_model@1`` structure model.

A child process of the M23 GA worker, never imported by a server module: ``[<repo>/.venv/bin/python, "-I", this
file]`` with cwd = the individual's private work folder, stdin closed and the environment the guardian gives the M21
worker (``PATH=/usr/bin:/bin``, ``LANG``, ``PYTHONUTF8``, ``PYTHONUNBUFFERED``, ``TMPDIR``, ``OMP_NUM_THREADS``,
``OPENBLAS_NUM_THREADS``). Project ``.venv`` only. OpenMM 8.6.0 and PDBFixer 1.12.0 are used through the UNMODIFIED
M21 worker ``openmm_mutation_worker.py`` (``mutant_projection``, ``_prepare``, ``_minimize``; its graft and energy
checks are called, never copied) and the M7 mmCIF writer; RDKit, Meeko and MDAnalysis are never imported; no network.

Input ``model_input.json`` (strict JSON, NaN/Infinity refused): exactly ``{"input_sha256", "payload"}`` where
``input_sha256`` is the SHA-256 of ``canonical_json(payload)`` (sorted keys, ``(",", ":")`` separators,
``ensure_ascii=False``, as ``core.handles.canonical_json`` / ``docking_worker.canonical_json``). Payload keys, exactly:

    schema          "sequence_model_input@1"
    run_id          the run id; the mmCIF object handle is computed in it (``core/handles.py`` formula)
    candidate_set   the M20 candidate set handle (copied into the model)
    structure       the set's ``{handle, model_number, structure_kind: "prepared_structure"}`` (copied)
    method          the M21 method record (exactly ``mutation_model_constants.METHOD_KEYS``), checked here with the
                    M21 method rules, the M7 installed-engine check and the installed PDBFixer 1.12.0
    model_number    int, the M7 preflight model number (= ``structure.model_number``)
    protein         the M7 preflight heavy-atom projection ``preflight(...)["protein"]``, unchanged
    seed            int 0-2147483647: the evaluation seed (= the GA ``parameters.seed``), for PDBFixer and OpenMM
    mutations       0-4 rows ``{candidate_index, residue (7 fields), from, to, mutant_resname}`` in structure order
                    (= ascending candidate index), distinct positions; ``[]`` is the wild-type reference row
    reference       null without mutations; with mutations the stored wild-type reference model's
                    ``{structure_sha256, protonation_variants, disulfide_bonds}`` (the comparison basis)

Computation. The mutations are applied one at a time in structure order with M21 ``mutant_projection`` (PDBFixer +
graft, same ``seed``; each step refuses atoms added or coordinates changed outside its residue with the M21 reasons).
Between two steps the atoms the previous step placed are rounded to 4 decimals (``round_placed``): M21 hands PDBFixer
a PDBx text with 4 decimals, so without it the next step's graft sees changes up to 5e-5 A (``coordinates_changed``,
T1 (a)); atoms that were in the input keep their input coordinates. The final projection goes through M21
``_prepare`` -> ``_minimize`` (M7 topology, pH 7 hydrogens, Amber14-all + GBn2, at most 50 iterations, the M7 energy
check) and the M7 mmCIF writer. The wild-type reference is the same path without PDBFixer. Same input, same bytes.

Success (exit 0); each file is written atomically (``<name>.tmp`` then rename), ``model.json`` last:

    model.cif            the final mmCIF bytes (standard HIS/CYS names; variants only in ``protonation_variants``)
    receptor_bonds.json  the M18 ``receptor_bonds@1`` sidecar the server builds for this model
                         (``docking_inputs.receptor_rows`` + ``mutation_model_sidecar``), whose ``source_handle`` is
                         the handle the server's store will give ``model.cif``
    receptor_error.json  instead of the sidecar, only when ``docking_inputs.receptor_rows`` refuses the model as an M18
                         receptor (``receptor_invalid``, e.g. above 10,000 atoms): ``{reason_code, message, detail}``
                         with that M18 reason. The model is still written (spec 2: the docking step fails).
    model.json           the ``mutation_set_model@1`` content exactly as ``sequence_model_bundle.model_content`` builds
                         it (canonical JSON, at most ``MAX_MODEL_OBJECT_BYTES``): the M21 structure entry without
                         ``sasa`` and ``contacts`` under ``mutant`` or ``wild_type_reference``, ``added_heavy_atoms``
                         with the 7 residue fields (mutant name), ``protonation_differences`` and
                         ``new_disulfide_in_mutant`` against ``reference``, ``reference_structure_sha256``, the method
                         with ``multi_mutation: "sequential_structure_order_round4"`` and the limitation sentences.
                         The server rebuilds and validates it before storing anything.

Failure (exit 1): ``error.json`` ``{"reason_code", "message", "detail"}`` (``detail.reason_code`` = the reason,
message 1-300 characters) with a reason from M21 ``FAILURE_REASON_CODES`` (``resource_exceeded`` includes a model
object above 16 MiB, never truncated); the engine and input exception families the M21 worker maps (including a
refused input) are ``engine_failed``. No difference, change, ΔΔG, score or rank is computed or written anywhere.
"""
from __future__ import annotations

import hashlib
import json
from importlib.metadata import version
from pathlib import Path
from typing import Any

import openmm
from openmm import app, unit

from mw import docking_inputs
from mw import mutation_model_constants as MK
from mw import mutation_model_math as mm
from mw import sequence_ga_constants as SC
from mw import sequence_ga_inputs as GI
from mw import sequence_model_bundle as SB
from mw.core.errors import ToolFailure
from mw.core.handles import RUN_ID_RE, canonical_json
from mw.jobs import openmm_mutation_worker as W
from mw.jobs.openmm_worker import _coordinates, _verify_method
from mw.mutation_candidates import seven
from mw.mutation_constants import IDENTITY_FIELDS

INPUT_SCHEMA = "sequence_model_input@1"
INPUT_FILE = "model_input.json"
MODEL_FILE = "model.json"
CIF_FILE = "model.cif"
SIDECAR_FILE = "receptor_bonds.json"
RECEPTOR_ERROR_FILE = "receptor_error.json"
ERROR_FILE = "error.json"
PAYLOAD_KEYS = frozenset({"schema", "run_id", "candidate_set", "structure", "method", "model_number", "protein", "seed",
                          "mutations", "reference"})
STRUCTURE_KEYS = frozenset({"handle", "model_number", "structure_kind"})
REFERENCE_KEYS = frozenset({"structure_sha256", "protonation_variants", "disulfide_bonds"})
ModelFailure = W.ModelFailure


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _int(value: Any, low: int, high: int | None = None) -> bool:
    return type(value) is int and low <= value and (high is None or value <= high)


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


# --- input ---------------------------------------------------------------------------------------------------------

def read_input(raw: bytes) -> dict[str, Any]:
    """The payload of ``model_input.json`` after the checksum comparison."""
    data = json.loads(raw, parse_constant=_reject_constant)
    _require(type(data) is dict and set(data) == {"input_sha256", "payload"}, "model input keys")
    _require(hashlib.sha256(canonical_json(data["payload"])).hexdigest() == data["input_sha256"],
             "model input checksum mismatch")
    return data["payload"]


def _check_mutation(row: Any) -> None:
    _require(type(row) is dict and set(row) == SB.MUTATION_KEYS and type(row["residue"]) is dict and
             set(row["residue"]) == set(IDENTITY_FIELDS) and _int(row["candidate_index"], 0) and
             row["from"] in MK.THREE_LETTER and row["to"] in MK.THREE_LETTER and row["from"] != row["to"] and
             row["mutant_resname"] == MK.THREE_LETTER[row["to"]], "mutation row")


def verify_payload(payload: Any) -> None:
    """Keys, the fixed method against the installed engines, and the argument shapes (ValueError otherwise)."""
    _require(type(payload) is dict and set(payload) == PAYLOAD_KEYS and payload["schema"] == INPUT_SCHEMA,
             "sequence model payload keys")
    method = payload["method"]
    _require(type(method) is dict and set(method) == set(MK.METHOD_KEYS), "method keys")
    mm._validate_method(method)
    _verify_method(method)
    _require(version("pdbfixer") == MK.PDBFIXER_VERSION, "PDBFixer distribution version differs from 1.12.0")
    structure = payload["structure"]
    _require(type(payload["run_id"]) is str and RUN_ID_RE.fullmatch(payload["run_id"]) and
             type(payload["candidate_set"]) is str and payload["candidate_set"] and
             _int(payload["model_number"], 1) and type(structure) is dict and set(structure) == STRUCTURE_KEYS and
             type(structure["handle"]) is str and structure["model_number"] == payload["model_number"] and
             structure["structure_kind"] == MK.STRUCTURE_KIND and _int(payload["seed"], *MK.SEED_RANGE) and
             type(payload["protein"]) is list, "sequence model arguments")
    mutations, reference = payload["mutations"], payload["reference"]
    _require(type(mutations) is list and len(mutations) <= SC.MAX_MUTATIONS, "mutation count")
    for row in mutations:
        _check_mutation(row)
    indices = [row["candidate_index"] for row in mutations]
    _require(indices == sorted(set(indices)), "candidate indices are not ascending")
    if mutations:
        _require(type(reference) is dict and set(reference) == REFERENCE_KEYS and
                 type(reference["structure_sha256"]) is str and GI.SHA_RE.fullmatch(reference["structure_sha256"])
                 and type(reference["protonation_variants"]) is list and
                 type(reference["disulfide_bonds"]) is list, "reference summary")
    else:
        _require(reference is None, "the wild-type reference row has no reference")


def mutation_steps(residues: list[dict[str, Any]], mutations: list[dict[str, Any]]) -> list[tuple[int, str]]:
    """``[(projection index, mutant name)]``: each residue resolves to one projection residue (M21 ``_target``), the
    mutant name differs from it, and the rows are in strictly ascending structure order (distinct positions)."""
    steps = [(W._target(residues, row["residue"]), row["mutant_resname"]) for row in mutations]
    _require(all(residues[index]["ref"]["resname"] != name for index, name in steps), "mutant name is the residue's")
    _require([index for index, _name in steps] == sorted({index for index, _name in steps}),
             "mutations are not in structure order at distinct positions")
    return steps


# --- the mutant projection -----------------------------------------------------------------------------------------

def round_placed(residue: dict[str, Any], added: list[dict[str, str]]) -> dict[str, Any]:
    """``residue`` with the atoms PDBFixer placed in this step (``added``) rounded to ``ROUND_DECIMALS`` decimals,
    the precision of the PDBx text the next step hands PDBFixer; every other atom is kept as it is."""
    placed = {atom["atom_name"] for atom in added}
    return {**residue, "atoms": [{**atom, "coordinates_A": [round(x, SC.ROUND_DECIMALS) for x in atom["coordinates_A"]]}
                                 if atom["atom_name"] in placed else atom for atom in residue["atoms"]]}


def sequential_projection(residues: list[dict[str, Any]], steps: list[tuple[int, str]],
                          seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply ``steps`` in order with the unmodified M21 ``mutant_projection``, rounding the atoms each step placed
    before the next step. Returns the final heavy-atom projection and the added heavy atoms ``{residue (7 fields,
    mutant name), atom_name, element}`` in structure order."""
    current = residues
    added_all: list[dict[str, Any]] = []
    for number, (index, mutant) in enumerate(steps):
        projection, added = W.mutant_projection(current, index, mutant, seed)
        residue = seven(projection[index]["ref"])
        added_all += [{"residue": residue, "atom_name": atom["atom_name"], "element": atom["element"]}
                      for atom in added]
        if number < len(steps) - 1:
            projection = [*projection[:index], round_placed(projection[index], added), *projection[index + 1:]]
        current = projection
    return current, added_all


# --- one structure (the M21 path) ----------------------------------------------------------------------------------

def structure_entry(residues: list[dict[str, Any]], added: list[dict[str, Any]], method: dict[str, Any], seed: int,
                    model_number: int) -> tuple[dict[str, Any], bytes]:
    """M21 ``_prepare`` -> ``_minimize`` and the M7 mmCIF writer; the M21 structure entry without
    ``structure_object``, ``sasa`` and ``contacts``, and the mmCIF bytes."""
    prepared = W._prepare(residues, method, seed)
    before, after, final_positions = W._minimize(prepared)
    model = prepared["model"]
    cif = _coordinates(app.Modeller(model.topology, final_positions), prepared["mappings"], model_number)
    final = [[float(x) for x in p.value_in_unit(unit.angstrom)] for p in final_positions]
    atoms = [{"residue": seven(m["residue"]), "atom_name": m["atom_name"], "element": m["element"],
              "coordinates_A": xyz} for m, xyz in zip(prepared["mappings"], final, strict=True)]
    bonds = [[a.index, b.index] for a, b in model.topology.bonds()]
    heavy = sum(a["element"] not in MK.HYDROGEN_ELEMENTS for a in atoms)
    entry = {"structure_sha256": hashlib.sha256(cif).hexdigest(),
             "system_xml_sha256": hashlib.sha256(prepared["system_xml"]).hexdigest(),
             "topology_sha256": mm.topology_sha256(atoms, bonds), "heavy_atoms": heavy,
             "added_hydrogens": len(atoms) - heavy, "added_heavy_atoms": added,
             "protonation_variants": mm.protonation_variants(atoms, prepared["variants"]),
             "disulfide_bonds": mm.disulfide_bonds(atoms, bonds), "final_bonds": bonds, "atom_mapping": atoms,
             "energy": {"before_kJ_mol": before, "after_kJ_mol": after, **MK.ENERGY_FIXED}}
    return entry, cif


def encode_model(content: dict[str, Any]) -> bytes:
    raw = canonical_json(content)
    if len(raw) > SC.MAX_MODEL_OBJECT_BYTES:
        raise ModelFailure("resource_exceeded", "the model object exceeds its fixed limit; never truncated",
                           {"limit": "model_object_bytes", "bytes": len(raw), "max_bytes": SC.MAX_MODEL_OBJECT_BYTES})
    return raw


def receptor_sidecar(cif: bytes, entry: dict[str, Any], handle: str,
                     model_number: int) -> tuple[bytes | None, dict[str, Any] | None]:
    """The sidecar the server makes for this model as an M18 receptor, or None and the M18 refusal of
    ``receptor_rows`` (a docking reason; the model itself is valid)."""
    try:
        rows = docking_inputs.receptor_rows(cif, "cif", handle, model_number)
    except ToolFailure as exc:
        reason = exc.detail.get("reason_code")
        if reason not in SC.DOCKING_FAILURE_REASONS:
            raise
        return None, {"reason_code": reason, "message": exc.message, "detail": exc.detail}
    return docking_inputs.mutation_model_sidecar(rows, entry["atom_mapping"], entry["final_bonds"], handle), None


def run(payload: dict[str, Any]) -> dict[str, Any]:
    verify_payload(payload)
    residues = W._flatten(payload["protein"])
    steps = mutation_steps(residues, payload["mutations"])
    projection, added = sequential_projection(residues, steps, payload["seed"])
    entry, cif = structure_entry(projection, added, payload["method"], payload["seed"], payload["model_number"])
    reference = {"structures": {SC.REFERENCE_SIDE: payload["reference"]}} if payload["mutations"] else None
    content = SB.model_content(run_id=payload["run_id"], candidate_set_handle=payload["candidate_set"],
                               structure=payload["structure"], mutations=payload["mutations"], seed=payload["seed"],
                               method=GI.model_method(payload["method"]), entry=entry, cif_raw=cif,
                               reference=reference)
    model = encode_model(content)
    handle = content["structures"][SB.side(payload["mutations"])]["structure_object"]
    sidecar, refusal = receptor_sidecar(cif, entry, handle, payload["model_number"])
    return {"model": model, "cif": cif, "sidecar": sidecar, "receptor_error": refusal}


# --- files ---------------------------------------------------------------------------------------------------------

def _write(name: str, raw: bytes) -> None:
    temporary = Path(f"{name}.tmp")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
    temporary.replace(name)


def envelope(reason_code: str, message: str, detail: dict[str, Any]) -> bytes:
    """``{reason_code, message, detail}`` as canonical JSON (a detail that is not plain JSON keeps only the reason)."""
    text = message[:300] or reason_code
    try:
        return canonical_json({"reason_code": reason_code, "message": text,
                               "detail": {**detail, "reason_code": reason_code}})
    except (TypeError, ValueError):
        return canonical_json({"reason_code": reason_code, "message": text, "detail": {"reason_code": reason_code}})


def main() -> int:
    try:
        out = run(read_input(Path(INPUT_FILE).read_bytes()))
        _write(CIF_FILE, out["cif"])
        if out["sidecar"] is not None:
            _write(SIDECAR_FILE, out["sidecar"])
        else:
            _write(RECEPTOR_ERROR_FILE, envelope(**out["receptor_error"]))
        _write(MODEL_FILE, out["model"])
    except ModelFailure as exc:
        _write(ERROR_FILE, envelope(exc.reason_code, str(exc), exc.detail))
        return 1
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, ArithmeticError, OSError, RuntimeError,
            ImportError, ToolFailure, openmm.OpenMMException) as exc:   # as the M21 worker: the closed engine failure
        _write(ERROR_FILE, envelope("engine_failed", f"{type(exc).__name__}: {str(exc)[:200]}", {}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
