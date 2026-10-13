"""M21 T3 worker ``mw/jobs/openmm_mutation_worker.py`` with the real engines (OpenMM 8.6.0, PDBFixer 1.12.0,
FreeSASA 2.2.1). Nothing is skipped when an engine is missing: the imports below fail the module instead.

Inputs: public 1UBQ (``fixtures/public_1ubq.cif``; public structure, not experimentally validated here) and the two
DERIVED SYNTHETIC Cys fixtures of ``fixtures/mutation_model/`` (SYNTHETIC-PROVENANCE.md), each through the product
path ``load_structure`` -> ``prepare_structure`` -> M7 ``preflight``. The modeling cases run as real worker processes
the way the guardian launches them (``python -I openmm_mutation_worker.py`` in a private directory with
``input.json`` + ``structure.json``, minimal environment), in parallel.

Independent oracles (spec 11), none of which calls the worker's own computation for the value it checks:
1. atoms outside the mutated residue (and every kept atom inside it) have exactly the input coordinates before
   minimization, in the projection and in the OpenMM positions;
2. mutated-residue heavy atoms == the Amber template read here directly from ``protein.ff14SB.xml``;
3. contact rows == a NumPy brute-force recomputation (own BFS over ``final_bonds``) from the stored coordinates;
4. SASA == FreeSASA recomputed here from the exported mmCIF (read with gemmi);
5. potentials == OpenMM recomputed here: topology read from the exported mmCIF by ``app.PDBxFile`` (its own bond
   perception must give exactly the stored bond set), System built from it (with the stored bond order its XML SHA-256
   equals the stored one), energy at the stored coordinates == ``after``; ``before`` at the pre-minimization
   positions.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import math
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
from pathlib import Path

import freesasa
import gemmi
import numpy as np
import openmm
import pytest
from openmm import app, unit
from openmm.app import forcefield

from mw import mutation_model_constants as K
from mw import mutation_model_math as mm
from mw.core.handles import canonical_json
from mw.jobs import openmm_mutation_worker as w
from mw.tools.openmm_method import preflight
from mw.workspace import new_run

FIX = Path(__file__).resolve().parent / "fixtures"
REPO = Path(__file__).resolve().parents[2]
WORKER = REPO / "backend/mw/jobs/openmm_mutation_worker.py"
SEED = 20261004
SIDES = ("wild_type_reference", "mutant")
STRUCTURES = {"ubq": "public_1ubq.cif", "ss": "mutation_model/derived_1ubq_f4c_t66c_disulfide_fixture.cif",
              "single": "mutation_model/derived_1ubq_f4c_single_cys_fixture.cif"}
# name: (structure, seq_auth, mutant name). Representative T1 matrix rows: substitutions with and without added
# atoms, kept same-name side-chain atoms (I44W keeps CD1), N-/C-terminal, Gly->X, X->Pro, Pro->X, HIS in and out,
# free Cys, disulfide Cys removed (partner CYX -> CYS) and a new distance-based disulfide.
CASES = {"i44w": ("ubq", 44, "TRP"), "i44w_repeat": ("ubq", 44, "TRP"), "i44a": ("ubq", 44, "ALA"),
         "i44c": ("ubq", 44, "CYS"), "m1p": ("ubq", 1, "PRO"), "g76p": ("ubq", 76, "PRO"), "g10a": ("ubq", 10, "ALA"),
         "p19a": ("ubq", 19, "ALA"), "k6h": ("ubq", 6, "HIS"), "h68a": ("ubq", 68, "ALA"), "c4a": ("ss", 4, "ALA"),
         "t66c": ("single", 66, "CYS")}
GUARDIAN_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1",
                "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}


def _selected(tmp: Path, name: str) -> dict:
    run = new_run(tmp, dry_run=False, run_id=f"run_m21_{tmp.name}")
    source = run.call("load_structure", {"source": Path(name).name, "model_index": 0},
                      source_bytes=(FIX / name).read_bytes(), source_format="cif")
    prepared = run.call("prepare_structure", {"structure": source.handle, "altloc": "highest_occupancy",
                                              "waters": "strip_all", "hydrogens": "strip",
                                              "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
    return preflight(run.store, prepared.handle, seed=run.seed)


def _payload(selected: dict, seq_auth: int, mutant: str, seed: int = SEED, cutoff: float = 4.0) -> dict:
    residue = next(r["residue"] for c in selected["protein"] for r in c["residues"]
                   if r["residue"]["seq_auth"] == seq_auth)
    return {"schema": w.INPUT_SCHEMA, "method": {**selected["method"], "pdbfixer_version": version("pdbfixer")},
            "model_number": selected["model_number"], "protein": selected["protein"], "seed": seed,
            "residue": residue, "mutant_resname": mutant, "contact_cutoff_A": cutoff}


def _launch(directory: Path, payload: dict, *, input_sha: str | None = None) -> subprocess.CompletedProcess:
    directory.mkdir(parents=True)
    raw = canonical_json(payload)
    (directory / "structure.json").write_bytes(raw)
    (directory / "input.json").write_text(json.dumps({"input_sha256": input_sha or hashlib.sha256(raw).hexdigest(),
                                                      "job_id": "job", "attempt_id": "attempt"}))
    return subprocess.run([sys.executable, "-I", str(WORKER)], cwd=directory, capture_output=True, timeout=600, check=False,
                          env={**GUARDIAN_ENV, "TMPDIR": str(directory)})


@pytest.fixture(scope="module")
def selected(tmp_path_factory):
    return {key: _selected(tmp_path_factory.mktemp(key), name) for key, name in STRUCTURES.items()}


@pytest.fixture(scope="module")
def results(selected, tmp_path_factory):
    """Every case as a real worker process (parallel); ``{name: (payload, result bytes, result)}``."""
    root = tmp_path_factory.mktemp("worker_runs")

    def one(name):
        structure, seq_auth, mutant = CASES[name]
        payload = _payload(selected[structure], seq_auth, mutant)
        done = _launch(root / name, payload)
        assert done.returncode == 0, (name, done.stderr.decode()[-2000:],
                                      (root / name / "error.json").read_text()
                                      if (root / name / "error.json").exists() else None)
        raw = (root / name / "result.json").read_bytes()
        return name, (payload, raw, json.loads(raw))

    with ThreadPoolExecutor(max_workers=min(len(CASES), os.cpu_count() or 1)) as pool:
        return dict(pool.map(one, CASES))


def _content(payload: dict, out: dict) -> dict:
    """The ``mutation_model@1`` content T4 publishes: server fields around the worker output (placeholder handles)."""
    one = {v: k for k, v in K.THREE_LETTER.items()}
    return {"schema": K.SCHEMA, "method_version": K.METHOD_VERSION,
            "candidate": {"candidate_set": "mutation_candidate_set_placeholder", "candidate_index": 0,
                          "position_index": 0, "from": one[payload["residue"]["resname"]],
                          "to": one[payload["mutant_resname"]], "residue": payload["residue"],
                          "mutant_resname": payload["mutant_resname"]},
            "structure": {"handle": "prepared_structure_placeholder", "model_number": payload["model_number"],
                          "structure_kind": K.STRUCTURE_KIND},
            "parameters": {"seed": payload["seed"], "contact_cutoff_A": payload["contact_cutoff_A"],
                           "selection_policy": K.SELECTION_POLICY, "hydrogen_policy": K.HYDROGEN_POLICY},
            "method": out["method"],
            "excluded_components": [{"reason": r, "residue_count": 0, "atom_count": 0} for r in K.EXCLUDED_CATEGORIES],
            "structures": {side: {"structure_object": f"mutation_model_structure_{side}", **out["structures"][side]}
                           for side in SIDES},
            "comparison": out["comparison"], "protonation_differences": out["protonation_differences"],
            "limitations": out["limitations"]}


def _key(residue: dict) -> tuple:
    return tuple((type(residue[k]), residue[k]) for k in
                 ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"))


def _mutated(payload: dict, side: str) -> dict:
    return payload["residue"] if side == "wild_type_reference" else {**payload["residue"],
                                                                       "resname": payload["mutant_resname"]}


# --- output contract ---------------------------------------------------------------------------------------------

def test_every_case_passes_the_pure_validator_and_has_no_difference_field(results):
    for name, (payload, raw, out) in results.items():
        assert set(out) == {"schema", "method", "structures", "structure_cifs", "comparison",
                            "protonation_differences", "limitations"}, name
        assert out["schema"] == w.OUTPUT_SCHEMA and out["method"] == payload["method"]
        assert mm.validated_model(_content(payload, out))
        assert len(raw) <= w.MAX_OUTPUT_BYTES
        for side in SIDES:
            entry = out["structures"][side]
            assert entry["structure_sha256"] == hashlib.sha256(out["structure_cifs"][side].encode()).hexdigest()
            assert entry["energy"]["convergence"] == "convergence_not_claimed"

        def keys(value):
            if isinstance(value, dict):
                for k, v in value.items():
                    yield k
                    yield from keys(v)
            elif isinstance(value, list):
                for v in value:
                    yield from keys(v)

        # spec keys: protonation_differences / protonation_difference_count (variant names, no values), and the M7
        # method record's max_iterations (the fixed cap of 50, not an iteration count)
        names = set(keys(out)) - {"protonation_differences", "protonation_difference_count", "max_iterations"}
        assert not {k for k in names if any(s in k.lower() for s in ("delta", "change", "diff", "ddg", "iteration"))}


def test_same_seed_reproduces_the_result_bytes(results):
    assert results["i44w"][1] == results["i44w_repeat"][1]


# --- oracle 1: no silent change outside the mutated residue --------------------------------------------------------

@pytest.mark.parametrize("name", ["i44w", "m1p", "g76p", "t66c", "c4a", "k6h"])
def test_oracle1_input_coordinates_kept_before_minimization(name, selected, results):
    payload = results[name][0]
    residues = w._flatten(payload["protein"])
    index = w._target(residues, payload["residue"])
    projection, added = w.mutant_projection(residues, index, payload["mutant_resname"], SEED)
    source_names = {a["atom_name"] for a in residues[index]["atoms"]}
    for k, (before, after) in enumerate(zip(residues, projection, strict=True)):
        if k != index:
            assert after["atoms"] == before["atoms"] and after["ref"] == before["ref"]   # exact floats
    kept = {a["atom_name"]: a["coordinates_A"] for a in residues[index]["atoms"]}
    for atom in projection[index]["atoms"]:
        if atom["atom_name"] in kept:
            assert atom["coordinates_A"] == kept[atom["atom_name"]], atom["atom_name"]   # incl. N CA C O, OXT
    assert [a["atom_name"] for a in added] == [a["atom_name"] for a in projection[index]["atoms"]
                                               if a["atom_name"] not in source_names]
    assert added == results[name][2]["structures"]["mutant"]["added_heavy_atoms"]
    if name == "g76p":
        assert "OXT" in kept and "OXT" not in {a["atom_name"] for a in added}
    # the OpenMM positions handed to the potential (after hydrogen construction) keep the input heavy coordinates
    prepared = w._prepare(projection, payload["method"], SEED)
    positions = prepared["input_positions_A"]
    flat = {(k, a["atom_name"]): a["coordinates_A"] for k, r in enumerate(projection) for a in r["atoms"]}
    heavy = [(m, xyz) for m, xyz in zip(prepared["mappings"], positions, strict=True) if m["element"] != "H"]
    assert len(heavy) == len(flat)
    for mapping, xyz in heavy:
        assert xyz == pytest.approx(flat[(mapping["residue_index"], mapping["atom_name"])], abs=1e-12)


def test_oracle1_mutant_heavy_atoms_outside_equal_wild_type_atoms(results):
    for name, (payload, _raw, out) in results.items():
        wild = out["structures"]["wild_type_reference"]["atom_mapping"]
        mutant = out["structures"]["mutant"]["atom_mapping"]
        original = _key(payload["residue"])
        renamed = _key(_mutated(payload, "mutant"))
        assert ([(_key(a["residue"]), a["atom_name"]) for a in wild if a["element"] != "H" and
                 _key(a["residue"]) != original] ==
                [(_key(a["residue"]), a["atom_name"]) for a in mutant if a["element"] != "H" and
                 _key(a["residue"]) != renamed]), name


# --- oracle 2: force-field template ------------------------------------------------------------------------------

def _amber_heavy(resname: str, terminal: bool) -> set[str]:
    root = ET.parse(Path(forcefield.__file__).parent / "data" / "amber14" / "protein.ff14SB.xml").getroot()
    elements = {node.attrib["name"]: node.attrib["element"] for node in root.findall("./AtomTypes/Type")}
    name = {"HIS": "HID"}.get(resname, resname)
    name = ("C" + name) if terminal else name
    node = next(n for n in root.findall("./Residues/Residue") if n.attrib["name"] == name)
    return {a.attrib["name"] for a in node.findall("Atom") if elements[a.attrib["type"]] != "H"}


def test_oracle2_mutated_residue_heavy_atoms_equal_the_template(results):
    for name, (payload, _raw, out) in results.items():
        last = max(r["residue"]["seq_auth"] for r in payload["protein"][0]["residues"])
        terminal = payload["residue"]["seq_auth"] == last
        for side in SIDES:
            mutated = _mutated(payload, side)
            got = {a["atom_name"] for a in out["structures"][side]["atom_mapping"]
                   if a["element"] != "H" and _key(a["residue"]) == _key(mutated)}
            assert got == _amber_heavy(mutated["resname"], terminal), (name, side)


# --- oracle 3: contacts ------------------------------------------------------------------------------------------

def _brute_contacts(atoms: list[dict], bonds: list[list[int]], mutated: dict, cutoff: float) -> list[tuple]:
    graph: dict[int, list[int]] = {}
    for a, b in bonds:
        graph.setdefault(a, []).append(b)
        graph.setdefault(b, []).append(a)
    xyz = np.array([a["coordinates_A"] for a in atoms], dtype=np.float64)
    order = {}
    for a in atoms:
        order.setdefault(_key(a["residue"]), len(order))
    rows = []
    for i, atom in enumerate(atoms):
        if atom["element"] == "H" or _key(atom["residue"]) != _key(mutated):
            continue
        depth = {i: 0}
        queue = [i]
        while queue:
            x = queue.pop(0)
            if depth[x] < 3:
                for y in graph.get(x, []):
                    if y not in depth:
                        depth[y] = depth[x] + 1
                        queue.append(y)
        for j, other in enumerate(atoms):
            if other["element"] == "H" or _key(other["residue"]) == _key(mutated) or j in depth:
                continue
            d = float(np.linalg.norm(xyz[i] - xyz[j]))
            if d <= cutoff:
                rows.append((i, order[_key(other["residue"])], j, d))
    rows.sort()
    return [(atoms[i]["atom_name"], atoms[j]["residue"], atoms[j]["atom_name"], d) for i, _o, j, d in rows]


def test_oracle3_contacts_equal_numpy_brute_force(results):
    for name, (payload, _raw, out) in results.items():
        for side in SIDES:
            entry = out["structures"][side]
            expected = _brute_contacts(entry["atom_mapping"], entry["final_bonds"], _mutated(payload, side),
                                       payload["contact_cutoff_A"])
            rows = entry["contacts"]["rows"]
            assert [(r["atom_name"], r["partner_residue"], r["partner_atom_name"]) for r in rows] == \
                   [e[:3] for e in expected], (name, side)
            assert all(math.isclose(r["distance_A"], e[3], rel_tol=0, abs_tol=1e-12) for r, e in zip(rows, expected))
            assert entry["contacts"]["count"] == len(expected), (name, side)
            assert entry["contacts"]["residue_count"] == len({_key(e[1]) for e in expected})
            assert entry["contacts"]["cutoff_A"] == 4.0 and entry["contacts"]["excluded_bond_distance"] == 3


# --- oracle 4: SASA from the exported mmCIF ----------------------------------------------------------------------

def test_oracle4_sasa_recomputed_from_the_exported_mmcif(results):
    for name, (payload, _raw, out) in results.items():
        for side in SIDES:
            structure = gemmi.make_structure_from_block(gemmi.cif.read_string(out["structure_cifs"][side]).sole_block())
            atoms = [(residue, atom) for chain in structure[0] for residue in chain for atom in residue
                     if atom.element.name not in ("H", "D")]
            origin = [min(a.pos.x for _, a in atoms), min(a.pos.y for _, a in atoms), min(a.pos.z for _, a in atoms)]
            coords = [v for _, a in atoms for v in (a.pos.x - origin[0], a.pos.y - origin[1], a.pos.z - origin[2])]
            params = freesasa.Parameters({"algorithm": freesasa.LeeRichards, "probe-radius": 1.4, "n-slices": 100,
                                          "n-threads": 1})
            result = freesasa.calcCoord(coords, [a.element.vdw_r for _, a in atoms], params)
            mutated = _mutated(payload, side)
            value = sum(result.atomArea(i) for i, (r, _a) in enumerate(atoms)
                        if r.seqid.num == mutated["seq_auth"] and r.name == mutated["resname"])
            sasa = out["structures"][side]["sasa"]
            # the mmCIF stores coordinates to 1e-3 Å, the worker uses the unrounded coordinates
            assert sasa["value_A2"] == pytest.approx(value, abs=1e-3), (name, side)
            assert sasa["residue"] == mutated and sasa["parameters"] == K.SASA_PARAMETERS


def test_exported_mmcif_keeps_identity_standard_names_and_coordinates(results):
    for name, (payload, _raw, out) in results.items():
        for side in SIDES:
            entry = out["structures"][side]
            structure = gemmi.make_structure_from_block(gemmi.cif.read_string(out["structure_cifs"][side]).sole_block())
            rows = [(chain.name, residue, atom) for chain in structure[0] for residue in chain for atom in residue]
            assert len(rows) == len(entry["atom_mapping"])
            for (chain, residue, atom), mapped in zip(rows, entry["atom_mapping"], strict=True):
                ref = mapped["residue"]
                assert (chain, residue.seqid.num, residue.seqid.icode.strip(), residue.label_seq, residue.name,
                        atom.name) == (ref["chain_auth"], ref["seq_auth"], ref["icode"], ref["seq_label"],
                                       ref["resname"], mapped["atom_name"])
                assert [atom.pos.x, atom.pos.y, atom.pos.z] == pytest.approx(mapped["coordinates_A"], abs=6e-4)
            assert not {r.name for _c, r, _a in rows} & {"HID", "HIE", "HIP", "CYX", "CYM"}, (name, side)


# --- oracle 5: potentials recomputed with OpenMM -----------------------------------------------------------------

def _independent_system(cif: str, bonds: list[list[int]] | None):
    """System from the exported mmCIF; with ``bonds`` the topology carries exactly those bonds in that order."""
    pdbx = app.PDBxFile(io.StringIO(cif))
    topology = pdbx.topology
    if bonds is None:
        # the mmCIF has no struct_conn, so PDBxFile perceives only the standard bonds; apply OpenMM's distance rule
        # for disulfides (spec 3.4) here, independently of the worker's bond list
        topology.createDisulfideBonds(pdbx.positions)
    else:
        topology = app.Topology()
        atoms = []
        for chain in pdbx.topology.chains():
            new_chain = topology.addChain(chain.id)
            for residue in chain.residues():
                new_residue = topology.addResidue(residue.name, new_chain, residue.id)
                atoms += [topology.addAtom(a.name, a.element, new_residue) for a in residue.atoms()]
        for a, b in bonds:
            topology.addBond(atoms[a], atoms[b])
    ff = app.ForceField("amber14-all.xml", "implicit/gbn2.xml")
    return pdbx, ff.createSystem(topology, nonbondedMethod=app.NoCutoff, constraints=None)


def _energy(system, coordinates_A: list[list[float]]) -> float:
    context = openmm.Context(system, openmm.VerletIntegrator(0.001), openmm.Platform.getPlatformByName("CPU"),
                             {"Threads": "1"})
    context.setPositions(unit.Quantity([openmm.Vec3(*xyz) for xyz in coordinates_A], unit.angstrom))
    return context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)


def test_oracle5_after_potential_and_system_recomputed_from_the_exported_structure(results):
    for name, (_payload, _raw, out) in results.items():
        for side in SIDES:
            entry, cif = out["structures"][side], out["structure_cifs"][side]
            pdbx, perceived = _independent_system(cif, None)
            assert ({frozenset((a.index, b.index)) for a, b in pdbx.topology.bonds()} ==
                    {frozenset(b) for b in entry["final_bonds"]}), (name, side)
            coordinates = [a["coordinates_A"] for a in entry["atom_mapping"]]
            assert _energy(perceived, coordinates) == pytest.approx(entry["energy"]["after_kJ_mol"], abs=1e-6)
            _pdbx, ordered = _independent_system(cif, entry["final_bonds"])
            assert (hashlib.sha256(openmm.XmlSerializer.serialize(ordered).encode()).hexdigest() ==
                    entry["system_xml_sha256"]), (name, side)


@pytest.mark.parametrize("name", ["i44w", "t66c"])
def test_oracle5_before_potential_recomputed_at_the_pre_minimization_positions(name, results):
    payload, _raw, out = results[name]
    residues = w._flatten(payload["protein"])
    index = w._target(residues, payload["residue"])
    projection, _added = w.mutant_projection(residues, index, payload["mutant_resname"], SEED)
    for side, source in (("wild_type_reference", residues), ("mutant", projection)):
        prepared = w._prepare(source, payload["method"], SEED)
        entry = out["structures"][side]
        _pdbx, system = _independent_system(out["structure_cifs"][side], None)
        assert _energy(system, prepared["input_positions_A"]) == pytest.approx(entry["energy"]["before_kJ_mol"],
                                                                                abs=1e-6)
        assert entry["energy"]["after_kJ_mol"] <= entry["energy"]["before_kJ_mol"] + 1e-4


# --- protonation, disulfides, cases ------------------------------------------------------------------------------

def _variants(entry: dict) -> dict:
    return {(r["residue"]["seq_auth"], r["residue"]["resname"]): r["variant"] for r in entry["protonation_variants"]}


def test_histidine_and_free_cysteine_variants_are_what_openmm_reports(results):
    wild = results["i44c"][2]["structures"]["wild_type_reference"]
    mutant = results["i44c"][2]["structures"]["mutant"]
    assert _variants(wild) == {(68, "HIS"): "HID"}
    assert _variants(mutant) == {(44, "CYS"): None, (68, "HIS"): "HID"}       # free Cys: OpenMM None, not "CYS"
    assert results["i44c"][2]["protonation_differences"] == [] and results["i44c"][2]["limitations"] == list(
        K.LIMITATION_ORDER[:5])
    assert _variants(results["h68a"][2]["structures"]["mutant"]) == {}
    assert _variants(results["k6h"][2]["structures"]["mutant"])[(6, "HIS")] in {"HID", "HIE", "HIP"}


def test_removed_disulfide_records_the_partner_difference_and_l5(results):
    out = results["c4a"][2]
    wild, mutant = out["structures"]["wild_type_reference"], out["structures"]["mutant"]
    assert [[a["seq_auth"], b["seq_auth"]] for a, b in wild["disulfide_bonds"]] in ([[4, 66]], [[66, 4]])
    assert mutant["disulfide_bonds"] == []
    assert [(d["residue"]["seq_auth"], d["wild_type_reference"], d["mutant"]) for d in out["protonation_differences"]] \
        == [(66, "CYX", None)]
    assert out["comparison"]["new_disulfide_in_mutant"] is False
    assert out["limitations"] == [K.L1, K.L2, K.L3, K.L4, K.L7, K.L5]


def test_new_disulfide_is_recorded_with_l5_and_l6(results):
    out = results["t66c"][2]
    wild, mutant = out["structures"]["wild_type_reference"], out["structures"]["mutant"]
    assert wild["disulfide_bonds"] == []
    assert sorted(r["seq_auth"] for pair in mutant["disulfide_bonds"] for r in pair) == [4, 66]
    assert _variants(mutant)[(66, "CYS")] == "CYX" and _variants(mutant)[(4, "CYS")] == "CYX"
    assert [(d["residue"]["seq_auth"], d["wild_type_reference"], d["mutant"]) for d in out["protonation_differences"]] \
        == [(4, None, "CYX")]
    assert out["comparison"]["new_disulfide_in_mutant"] is True
    assert out["limitations"] == [K.L1, K.L2, K.L3, K.L4, K.L7, K.L5, K.L6]


def test_case_shapes_kept_atoms_terminals_and_counts(results):
    i44w = results["i44w"][2]["structures"]["mutant"]
    assert [a["atom_name"] for a in i44w["added_heavy_atoms"]] == ["CG", "NE1", "CE2", "CZ2", "CH2", "CZ3", "CE3",
                                                                   "CD2"]   # CD1 kept by PDBFixer (T1 B1, A)
    assert results["i44a"][2]["structures"]["mutant"]["added_heavy_atoms"] == []
    assert results["g10a"][2]["structures"]["mutant"]["added_heavy_atoms"] == [{"atom_name": "CB", "element": "C"}]
    assert {a["atom_name"] for a in results["g76p"][2]["structures"]["mutant"]["added_heavy_atoms"]} == {"CB", "CG",
                                                                                                          "CD"}
    for name, (_payload, _raw, out) in results.items():
        wild = out["structures"]["wild_type_reference"]
        assert wild["added_heavy_atoms"] == [] and wild["heavy_atoms"] + wild["added_hydrogens"] == len(
            wild["atom_mapping"]), name
    # T1 measured (preflight.txt (b)): 1UBQ I44 27 rows at 4 Å, I44W (kept CD1) 21 rows; potentials as measured
    i44w_out = results["i44w"][2]["structures"]
    assert (i44w_out["wild_type_reference"]["contacts"]["count"], i44w_out["mutant"]["contacts"]["count"]) == (27, 21)
    assert i44w_out["wild_type_reference"]["energy"]["before_kJ_mol"] == pytest.approx(-10184.213905790195, abs=1e-6)
    assert i44w_out["mutant"]["sasa"]["value_A2"] == pytest.approx(88.13, abs=0.005)
    ubq = results["i44a"][2]["structures"]["wild_type_reference"]
    assert (ubq["heavy_atoms"], ubq["added_hydrogens"]) == (602, 629)       # M7 1UBQ counts
    # the wild-type reference is the same computation in every 1UBQ job with the same seed
    assert len({canonical_json(results[n][2]["structures"]["wild_type_reference"]) for n in
                ("i44w", "i44a", "i44c")}) == 1


# --- closed failures ---------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ubq_i44(selected):
    payload = _payload(selected["ubq"], 44, "TRP")
    residues = w._flatten(payload["protein"])
    index = w._target(residues, payload["residue"])
    return payload, residues, index, w._pdbfixer(residues, index, "TRP", SEED)


def _fails(reason: str, fn, *args):
    with pytest.raises(w.ModelFailure) as caught:
        fn(*args)
    assert caught.value.reason_code == reason and caught.value.detail["reason_code"] == reason
    return caught.value


def _copy(fixed):
    return json.loads(json.dumps(fixed))


def test_graft_refuses_coordinate_changes_and_added_atoms_outside(ubq_i44):
    _, residues, index, fixed = ubq_i44
    w._graft(residues, fixed, index, "TRP")                                   # the real output passes
    moved = _copy(fixed)
    moved[10]["atoms"][0]["coordinates_A"][0] += 1e-6
    assert _fails("coordinates_changed", w._graft, residues, moved, index, "TRP").detail["max_abs_shift_A"] > 1e-9
    extra = _copy(fixed)
    extra[10]["atoms"].append({"atom_name": "CZ9", "element": "C", "coordinates_A": [0.0, 0.0, 0.0]})
    _fails("unexpected_atoms_added", w._graft, residues, extra, index, "TRP")
    hydrogen = _copy(fixed)
    hydrogen[index]["atoms"].append({"atom_name": "HA", "element": "H", "coordinates_A": [0.0, 0.0, 0.0]})
    _fails("unexpected_atoms_added", w._graft, residues, hydrogen, index, "TRP")
    more = _copy(fixed) + [_copy(fixed[-1])]
    _fails("unexpected_atoms_added", w._graft, residues, more, index, "TRP")
    renamed = _copy(fixed)
    renamed[10]["atoms"][0]["atom_name"], renamed[10]["atoms"][1]["atom_name"] = (
        renamed[10]["atoms"][1]["atom_name"], renamed[10]["atoms"][0]["atom_name"])
    _fails("mutation_modeling_failed", w._graft, residues, renamed, index, "TRP")


def test_graft_refuses_a_mutated_residue_that_does_not_match_the_template(ubq_i44):
    _, residues, index, fixed = ubq_i44
    short = _copy(fixed)
    short[index]["atoms"] = [a for a in short[index]["atoms"] if a["atom_name"] != "CZ2"]
    assert _fails("mutation_modeling_failed", w._graft, residues, short, index, "TRP").detail["missing"] == ["CZ2"]
    _fails("mutation_modeling_failed", w._graft, residues, _copy(fixed), index, "PHE")


def test_pdbfixer_refuses_to_add_atoms_outside_the_mutated_residue(ubq_i44):
    _, residues, index, _fixed = ubq_i44
    damaged = [dict(r) for r in residues]
    damaged[9] = {**damaged[9], "atoms": [a for a in damaged[9]["atoms"] if a["atom_name"] != "O"]}   # G10 O
    failure = _fails("unexpected_atoms_added", w._pdbfixer, damaged, index, "TRP", SEED)
    assert failure.detail["residues"] == ["0:10"]


def test_pdbfixer_errors_are_mutation_modeling_failed(ubq_i44, monkeypatch):
    _, residues, index, _fixed = ubq_i44

    def refuse(self, mutations, chain_id):
        raise KeyError("no template")

    monkeypatch.setattr(w.PDBFixer, "applyMutations", refuse)
    _fails("mutation_modeling_failed", w._pdbfixer, residues, index, "TRP", SEED)


def test_energy_contact_and_output_limits_are_closed_failures(ubq_i44, monkeypatch):
    payload, residues, _index, _fixed = ubq_i44
    _fails("energy_invalid", w._check_energy, -10.0, -10.0 + 2e-4)
    _fails("energy_invalid", w._check_energy, float("nan"), -1.0)
    w._check_energy(-10.0, -10.0 + 1e-4)
    monkeypatch.setattr(w, "_minimize", lambda prepared: (0.0, 0.0, prepared["model"].positions))
    monkeypatch.setattr(mm.K, "MAX_CONTACT_ROWS", 3)
    failure = _fails("resource_exceeded", w.model_structure, residues, payload["residue"], [], payload)
    assert failure.detail["limit"] == K.TOO_MANY_CONTACTS and failure.detail["rows"] > 3
    monkeypatch.setattr(w, "MAX_OUTPUT_BYTES", 10)
    assert _fails("resource_exceeded", w.encode_output, {"x": "y" * 20}).detail["limit"] == "output_bytes"


def test_worker_process_failures_write_closed_error_json(selected, tmp_path):
    payload = _payload(selected["ubq"], 44, "TRP")
    done = _launch(tmp_path / "checksum", payload, input_sha="0" * 64)
    error = json.loads((tmp_path / "checksum" / "error.json").read_text())
    assert done.returncode == 1 and error["reason_code"] == "engine_failed"
    assert not (tmp_path / "checksum" / "result.json").exists()
    tampered = {**payload, "method": {**payload["method"], "max_iterations": 51}}
    done = _launch(tmp_path / "method", tampered)
    assert done.returncode == 1 and json.loads((tmp_path / "method" / "error.json").read_text())["reason_code"] == \
        "engine_failed"
    damaged = json.loads(json.dumps(payload))
    damaged["protein"][0]["residues"][9]["atoms"] = [a for a in damaged["protein"][0]["residues"][9]["atoms"]
                                                     if a["atom_name"] != "O"]
    done = _launch(tmp_path / "outside", damaged)
    error = json.loads((tmp_path / "outside" / "error.json").read_text())
    assert done.returncode == 1 and error["reason_code"] == "unexpected_atoms_added"
    assert not (tmp_path / "outside" / "result.json").exists()


# --- engine isolation --------------------------------------------------------------------------------------------

def test_only_the_worker_imports_pdbfixer_and_no_module_imports_the_worker():
    importers, worker_importers = [], []
    for path in sorted((REPO / "backend/mw").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [node.module or ""] + [a.name for a in node.names] if isinstance(node, ast.ImportFrom) else [])
            if any(n.split(".")[0] == "pdbfixer" for n in names):
                importers.append(path.relative_to(REPO).as_posix())
            if any("openmm_mutation_worker" in n for n in names):
                worker_importers.append(path.relative_to(REPO).as_posix())
    # M29: the structure-repair worker is the other PDBFixer importer (its own job module; nothing imports it).
    assert importers == ["backend/mw/jobs/openmm_mutation_worker.py", "backend/mw/jobs/structure_repair_worker.py"]
    # M23 (spec 4 (1)): the sequence GA modeling program, itself a project-environment child program that no module
    # imports (test_sequence_model_worker.py), calls the unmodified M21 functions; no server module imports either.
    assert worker_importers == ["backend/mw/jobs/sequence_model_worker.py"]


def test_server_side_mutation_modules_import_no_engine():
    code = ("import sys, mw.mutation_model_constants, mw.mutation_model_inputs, mw.mutation_model_math, "
            "mw.api.app; print(sorted(m for m in ('openmm', 'pdbfixer', 'freesasa') if m in sys.modules))")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO / "backend",
                          timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"
