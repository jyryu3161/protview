"""Shared M23 T2 test world and SYNTHETIC-FIXTURE builders (no engine run here).

``real_world``: one run built through the unmodified product HTTP path (upload public 1UBQ -> ``load_structure`` ->
``prepare_structure`` -> the cheap M20 ``generate_mutation_candidates`` for the two position sets of
``fixtures/sequence_ga``) plus same-run ligand SDF imports (the labeled synthetic phenol and planar SDFs). 1UBQ is a
public structure, not experimental validation of anything here.

The ``synthetic_*`` builders make LABELED SYNTHETIC ``mutation_set_model@1`` contents and ``docking_result@1``-shaped
dicts for the pure validators: residues and atom names follow the standard PDB names, but coordinates, energies,
hashes and scores are made-up selection-logic inputs, never modeling or docking values.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from mw import docking_constants as C
from mw import mutation_model_constants as MK
from mw import mutation_model_math as mm
from mw import sequence_ga_constants as SC
from mw import sequence_ga_inputs as GI
from mw.api import app as api_module
from mw.core.handles import HANDLE_PREFIX, canonical_json, object_sha
from mw.docking_batch_bundle import PREPARATION
from mw.openmm_bundle import FORCEFIELD_SHA256

FIX = Path(__file__).parent / "fixtures"
GA_FIX = FIX / "sequence_ga"
UBQ = (FIX / "public_1ubq.cif").read_bytes()
PHENOL = (FIX / "mutation_model" / "synthetic-phenol-ligand.sdf").read_bytes()
PLANAR = (FIX / "docking" / "synthetic-ligand-planar-z0.sdf").read_bytes()
TINY = json.loads((GA_FIX / "m20-candidate-set-1ubq-tiny.json").read_text())
EIGHT = json.loads((GA_FIX / "m20-candidate-set-1ubq-8pos.json").read_text())
EXPECTED = json.loads((GA_FIX / "expected.json").read_text())
ACK = {key: True for key in C.ACKNOWLEDGEMENT_KEYS}
DEFAULT_GA = {"seed": 11, "population_size": 8, "generations": 5, "elite_count": 2, "tournament_size": 2,
              "crossover_fraction": 0.5, "random_fraction": 0.2, "max_mutations": 3, "patience": 3,
              "max_new_evaluations": 32, "total_s": 7200}
SMALL_GA = {**DEFAULT_GA, "population_size": 4, "elite_count": 1, "max_new_evaluations": 16, "total_s": 600}
# The positions and allowed residues of the two committed M20 sets (build_sequence_ga_fixtures.py).
SETS = {"tiny": {"residues": [(3, "ILE"), (6, "LYS"), (44, "ILE"), (76, "GLY")], "protected": [(3, "ILE")],
                 "allowed": "AW"},
        "eight": {"residues": [(1, "MET"), (2, "GLN"), (3, "ILE"), (6, "LYS"), (8, "LEU"), (44, "ILE"),
                               (75, "GLY"), (76, "GLY")], "protected": [], "allowed": "AFHWY"}}


def _residue(seq: int, name: str) -> dict:
    return {"model_number": 1, "chain_auth": "A", "seq_auth": seq, "icode": "", "resname": name}


def _command(client: TestClient, rid: str, tool: str, args: dict) -> str:
    response = client.post(f"/runs/{rid}/commands", json={"tool": tool, "args": args})
    assert response.status_code == 200, response.text
    return response.json()["handle"]["handle"]


def _import(client: TestClient, rid: str, kind: str, filename: str, raw: bytes) -> str:
    response = client.post(f"/runs/{rid}/chemical/imports", params={"kind": kind, "filename": filename},
                           content=raw, headers={"content-type": "application/octet-stream"})
    assert response.status_code == 201, response.text
    return response.json()["handle"]


def real_world(root: Path) -> dict[str, Any]:
    """The run, its prepared 1UBQ, the two M20 sets and the SDF imports; the HTTP client is closed afterwards."""
    saved = api_module.RUNS_DIR
    api_module.RUNS_DIR = root
    api_module.RUNS.clear()
    try:
        client = TestClient(api_module.app, base_url="http://127.0.0.1")
        created = client.post("/runs", json={"goal": "M23 T2 sequence GA admission"})
        assert created.status_code == 201, created.text
        rid = created.json()["run_id"]
        uploaded = client.post(f"/runs/{rid}/uploads", params={"filename": "public_1ubq.cif"}, content=UBQ)
        assert uploaded.status_code in (200, 201), uploaded.text
        source = _command(client, rid, "load_structure", {"source": uploaded.json()["upload_id"], "model_index": 0})
        prepared = _command(client, rid, "prepare_structure", {
            "structure": source, "altloc": "highest_occupancy", "waters": "strip_all", "hydrogens": "strip",
            "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
        sets = {}
        for name, spec in SETS.items():
            sets[name] = _command(client, rid, "generate_mutation_candidates", {
                "structure": prepared,
                "sources": {"pocket": None, "ligand_shell": None,
                            "residues": [_residue(seq, res) for seq, res in spec["residues"]]},
                "protected_residues": [_residue(seq, res) for seq, res in spec["protected"]],
                "allowed_residues": spec["allowed"]})
        empty = _command(client, rid, "generate_mutation_candidates", {
            "structure": prepared, "sources": {"pocket": None, "ligand_shell": None, "residues": [_residue(3, "ILE")]},
            "protected_residues": [_residue(3, "ILE")], "allowed_residues": "AW"})
        phenol = _import(client, rid, "ligand_sdf", "phenol.sdf", PHENOL)
        planar = _import(client, rid, "ligand_sdf", "planar.sdf", PLANAR)
        receptor = _import(client, rid, "receptor", "ubq.cif", UBQ)
        run = api_module._run(rid)
        return {"run": run, "rid": rid, "structure": prepared, "source": source, "tiny": sets["tiny"],
                "eight": sets["eight"], "empty": empty, "phenol": phenol, "planar": planar, "receptor": receptor}
    finally:
        api_module.RUNS_DIR = saved
        api_module.RUNS.clear()


def args_for(world: dict[str, Any], **changes: Any) -> dict[str, Any]:
    args = {"candidate_set": world["tiny"], "ligand": {"source": "sdf", "sdf_handle": world["phenol"]},
            "box": {"source": "ligand_range", "margin_A": 8}, "parameters": {"seed": 42, "exhaustiveness": 4,
                                                                            "num_modes": 5},
            "selection_policy": SC.SELECTION_POLICY, "hydrogen_policy": SC.HYDROGEN_POLICY,
            "acknowledgement": dict(ACK), "ga": dict(SMALL_GA)}
    args.update(changes)
    return args


# ---------------------------------------------------------------- SYNTHETIC-FIXTURE model / result builders
HEAVY_NAMES = {   # standard PDB heavy-atom names (synthetic structures only; never a force-field claim)
    "ALA": ("N", "CA", "C", "O", "CB"),
    "CYS": ("N", "CA", "C", "O", "CB", "SG"),
    "GLY": ("N", "CA", "C", "O"),
    "HIS": ("N", "CA", "C", "O", "CB", "CG", "ND1", "CD2", "CE1", "NE2"),
    "ILE": ("N", "CA", "C", "O", "CB", "CG1", "CG2", "CD1"),
    "LYS": ("N", "CA", "C", "O", "CB", "CG", "CD", "CE", "NZ"),
    "TRP": ("N", "CA", "C", "O", "CB", "CG", "CD1", "CD2", "NE1", "CE2", "CE3", "CZ2", "CZ3", "CH2"),
}
# A synthetic protein holding the tiny set's positions (I3, K6, I44, G76 with the 1UBQ label fields) plus two
# SYNTHETIC cysteines and the 1UBQ His68 for the protonation and disulfide rules.
SYNTHETIC_RESIDUES = [(3, "ILE"), (6, "LYS"), (20, "CYS"), (30, "CYS"), (44, "ILE"), (68, "HIS"), (76, "GLY")]
RUN_ID = "run_m23_t2_synthetic"
SYNTHETIC_CANDIDATE_SET = f"{HANDLE_PREFIX}{RUN_ID}/mutation_candidate_set/" + "c" * 64


def seven(seq: int, resname: str) -> dict[str, Any]:
    return {"model_number": 1, "chain_auth": "A", "chain_label": "A", "seq_auth": seq, "seq_label": seq, "icode": "",
            "resname": resname}


def model_method() -> dict[str, Any]:
    """A method record shaped like the M21 one (fixed values, the pinned force-field fingerprint) + multi-mutation."""
    return {**MK.M7_METHOD_FIXED, "engine_build": "8.6.0.dev-synthetic", "forcefield_files_sha256": FORCEFIELD_SHA256,
            **MK.MUTATION_METHOD_FIXED, **SC.MULTI_MUTATION_METHOD}


def structure_record(content: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict((content or TINY["content"])["structure"])


def synthetic_entry(mutated: dict[int, str], *, variants: dict[int, str | None] | None = None,
                    disulfide: bool = False, label: str = "") -> tuple[dict[str, Any], bytes]:
    """(structure entry without ``structure_object``, fake mmCIF bytes). ``mutated``: seq -> mutant resname; kept
    atoms keep their names and order, atoms the input residue lacked are appended (the M21 graft)."""
    atoms: list[dict[str, Any]] = []
    bonds: list[list[int]] = []
    sg: list[int] = []
    added: list[dict[str, Any]] = []
    previous_c = None
    for order, (seq, resname) in enumerate(SYNTHETIC_RESIDUES):
        name = mutated.get(seq, resname)
        original = list(HEAVY_NAMES[resname]) + (["OXT"] if seq == 76 else [])
        template = list(HEAVY_NAMES[name]) + (["OXT"] if seq == 76 else [])
        heavy = [n for n in original if n in template] + [n for n in template if n not in original]
        if seq in mutated:      # the worker's record: atoms the input residue lacked, in atom order
            added += [{"residue": seven(seq, name), "atom_name": n, "element": "S" if n == "SG" else n[0]}
                      for n in heavy if n not in original]
        start = len(atoms)
        for index, atom_name in enumerate([*heavy, "H", "HA"]):
            element = "H" if atom_name in ("H", "HA") else ("S" if atom_name == "SG" else atom_name[0])
            atoms.append({"residue": seven(seq, name), "atom_name": atom_name, "element": element,
                          "coordinates_A": [order * 3.5 + index * 0.25, 1.0 + index * 0.5, -2.0 + order * 0.125]})
        for index in range(start, len(atoms) - 1):
            bonds.append([index, index + 1])
        if previous_c is not None:
            bonds.append([previous_c, start])
        previous_c = start + heavy.index("C")
        if name == "CYS":
            sg.append(start + heavy.index("SG"))
    if disulfide:
        bonds.append(sg[:2])
    heavy_count = sum(a["element"] not in MK.HYDROGEN_ELEMENTS for a in atoms)
    rows = []
    for seq, resname in SYNTHETIC_RESIDUES:
        name = mutated.get(seq, resname)
        if name in MK.PROTONATION_VARIANTS:
            default = {"HIS": "HIE", "CYS": "CYX" if disulfide else None}[name]
            rows.append({"residue": seven(seq, name), "variant": (variants or {}).get(seq, default)})
    tag = canonical_json({"mutated": mutated, "variants": variants, "disulfide": disulfide, "label": label})
    cif = b"data_SYNTHETIC_FIXTURE\n# not a structure file\n" + tag + b"\n"
    entry = {"structure_sha256": hashlib.sha256(cif).hexdigest(),
             "system_xml_sha256": hashlib.sha256(b"synthetic system " + tag).hexdigest(),
             "topology_sha256": mm.topology_sha256(atoms, bonds), "heavy_atoms": heavy_count,
             "added_hydrogens": len(atoms) - heavy_count, "added_heavy_atoms": added,
             "protonation_variants": rows, "disulfide_bonds": mm.disulfide_bonds(atoms, bonds), "final_bonds": bonds,
             "atom_mapping": atoms,
             "energy": {"before_kJ_mol": -1000.5, "after_kJ_mol": -1010.25, **MK.ENERGY_FIXED}}
    return entry, cif


def object_handle(kind: str, schema: str, content: Any, run_id: str = RUN_ID) -> str:
    raw = content if isinstance(content, bytes) else canonical_json(content)
    return f"{HANDLE_PREFIX}{run_id}/{kind}/{object_sha(kind, schema, raw)}"


def model_handle(content: dict[str, Any], run_id: str = RUN_ID) -> str:
    return object_handle(SC.MODEL_KIND, SC.MODEL_SCHEMA, content, run_id)


DOCKING_PINS = {"engine": "qvina", "qvina_sha256": "caf5f22a3928be8adf3cb017508eaacbdcecf68ef29c5bca24fceea016c5f79c",
                "qvina_package": "qvina-2.1.0-x", "versions": {"meeko": "0.8.0", "rdkit": "2026.03.6",
                                                               "MDAnalysis": "2.10.0", "gemmi": "0.7.5"},
                "worker_sha256": "2" * 64, "constants_sha256": "3" * 64, "lock_sha256": "4" * 64,
                "qvina_lock_sha256": "5" * 64}


def synthetic_result(normalized: dict[str, Any], model_handle_: str, model: dict[str, Any], side: str,
                     box: dict[str, Any], score: float | None, sdf_sha256: str) -> dict[str, Any]:
    """A SYNTHETIC-FIXTURE ``docking_result@1``-shaped dict for one model side (score = selection-logic input)."""
    args = GI.individual_arguments(normalized, model_handle_, side)
    entry = model["structures"][side]
    modes = [] if score is None else [{"mode": 1, "score_kcal_mol": score}]
    return {"schema": C.RESULT_SCHEMA, "protocol": C.PROTOCOL, "method": C.METHODS["free"],
            "input_sha256": GI.docking_inputs.input_sha256(args),
            "inputs": {"receptor": {"source": {"kind": "mutation_model", "mutation_model": model_handle_,
                                               "side": side},
                                    "sha256": entry["structure_sha256"],
                                    "model_number": model["structure"]["model_number"],
                                    "connectivity": {"kind": C.MUTATION_MODEL_CONNECTIVITY},
                                    "removed_instance": None, "acknowledgement": dict(ACK)},
                       "ligand": {"source": "sdf", "sdf_handle": normalized["ligand"]["sdf_handle"],
                                  "sdf_sha256": sdf_sha256},
                       "mode": "free"},
            "box": dict(box), "parameters": {**normalized["parameters"], "cpu": C.CPU},
            "engine": {"name": "qvina", "version": "2.1.0", "binary_sha256": DOCKING_PINS["qvina_sha256"],
                       "package": DOCKING_PINS["qvina_package"]},
            "preparation": dict(PREPARATION), "modes": modes,
            "counts": {"modes": len(modes), "contacts_by_mode": [0] * len(modes), "null_result": not modes,
                       "samples_generated": None, "samples_scored": None},
            "limitations": list(C.applicable_limitations(mode="free", source="sdf", removed_instance=False,
                                                         unspecified_stereo_centers=None,
                                                         receptor_source="mutation_model"))}





def pins() -> dict[str, Any]:
    """SYNTHETIC pins in the checked shape (module hashes are placeholders, not the files' hashes)."""
    modules = {"ga_worker_sha256": "6" * 64, "ga_constants_sha256": "7" * 64, "model_worker_sha256": "8" * 64,
               "m21_sha256": {name: "9" * 64 for name in GI.M21_MODULES}}
    return {"modules": modules, "model_method": model_method(), "docking": dict(DOCKING_PINS)}
