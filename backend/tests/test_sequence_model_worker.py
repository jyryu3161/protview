"""M23 T3 modeling program ``mw/jobs/sequence_model_worker.py`` with the real engines (OpenMM 8.6.0 and PDBFixer 1.12.0
through the unmodified M21 worker). Nothing is skipped when an engine is missing: the imports below fail the module.

Inputs: public 1UBQ (``fixtures/public_1ubq.cif``; a public structure, not experimental validation of anything here)
with the real eight-position M20 set of ``fixtures/sequence_ga`` (user-selected test positions, not a design
proposal), and the two DERIVED SYNTHETIC Cys structures of ``fixtures/mutation_model`` (SYNTHETIC-PROVENANCE.md) for
the disulfide rules; each through ``load_structure`` -> ``prepare_structure`` -> M7 ``preflight``. Modeling cases run
as real child processes the way the GA worker launches them (``[<repo>/.venv/bin/python, "-I", program]`` in a
private folder holding only ``model_input.json``, the guardian worker environment), in parallel.

Independent checks (none reads the value it checks back from the program's own computation): the stored M21 structure
handles of ``golden_call_keys.json`` (wild type and I44W), the input coordinates before minimization, the Amber
template read here from ``protein.ff14SB.xml``, the store formula recomputed with ``hashlib`` and a real
``ObjectStore.put``, the server's own ``docking_inputs`` sidecar functions, protonation differences recomputed here
from the two stored entries and the T2 server validator ``sequence_model_bundle.validated_model``. Energies are only
checked for being finite and not increased; they are per-structure values and are never compared between structures.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import subprocess
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
from pathlib import Path

import openmm
import pytest
from openmm.app import forcefield

from mw import docking_inputs
from mw import mutation_model_constants as MK
from mw import sequence_ga_constants as SC
from mw import sequence_ga_inputs as GI
from mw import sequence_model_bundle as SB
from mw.core.handles import canonical_json
from mw.jobs import openmm_mutation_worker as W
from mw.jobs import sequence_model_worker as smw
from mw.tools.openmm_method import preflight
from mw.workspace import new_run

REPO = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"
PROGRAM = REPO / "backend/mw/jobs/sequence_model_worker.py"
PROJECT_PYTHON = REPO / ".venv/bin/python"           # spec 8: the venv link, never resolved
GOLDEN = json.loads((FIX / "sequence_ga/golden_call_keys.json").read_text())
EIGHT = json.loads((FIX / "sequence_ga/m20-candidate-set-1ubq-8pos.json").read_text())
RUN_ID = GOLDEN["run_id"]                             # the golden run: its M21 structure handles are compared below
SEED = 20261004                                       # the golden M21 request seed (= the evaluation seed here)
GUARDIAN_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1",
                "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
OUTPUTS = ["model.cif", "model.json", "model_input.json", "receptor_bonds.json"]
STRUCTURES = {"ubq": "public_1ubq.cif", "ss": "mutation_model/derived_1ubq_f4c_t66c_disulfide_fixture.cif",
              "single": "mutation_model/derived_1ubq_f4c_single_cys_fixture.cif"}
WILD = {"wt": "ubq", "wt_repeat": "ubq", "ss_wt": "ss", "single_wt": "single"}
# name: (structure, mutations). 1UBQ rows are the eight-position set's candidates ("I44W" = I44 -> W): k = 1-4,
# adjacent positions, N terminus (M1) and C terminus (G75-G76), as T1 (a). The two SYNTHETIC Cys cases use their own
# residue rows (C4A removes the C4-C66 disulfide, T66C makes a new one).
MUTANTS = {"i44w": ("ubq", ["I44W"]), "k2_k6h_i44w": ("ubq", ["K6H", "I44W"]),
           "k2_q2y_i3f": ("ubq", ["Q2Y", "I3F"]), "k2_g75f_g76w": ("ubq", ["G75F", "G76W"]),
           "k3_m1w_q2y_i3f": ("ubq", ["M1W", "Q2Y", "I3F"]),
           "k4_ends": ("ubq", ["M1W", "I44W", "G75F", "G76W"]),
           "k4_ends_repeat": ("ubq", ["M1W", "I44W", "G75F", "G76W"]),
           "k4_q2y_i3f_k6h_l8w": ("ubq", ["Q2Y", "I3F", "K6H", "L8W"]),
           "ss_c4a": ("ss", ["C4A"]), "single_t66c": ("single", ["T66C"])}
UBQ_MUTANTS = [name for name, (structure, _labels) in MUTANTS.items() if structure == "ubq"]


# --------------------------------------------------------------------------------------------------- inputs

def _selected(tmp: Path, name: str) -> dict:
    run = new_run(tmp, dry_run=False, run_id=f"run_m23_t3_{tmp.name}"[:60])
    source = run.call("load_structure", {"source": Path(name).name, "model_index": 0},
                      source_bytes=(FIX / name).read_bytes(), source_format="cif")
    prepared = run.call("prepare_structure", {"structure": source.handle, "altloc": "highest_occupancy",
                                              "waters": "strip_all", "hydrogens": "strip",
                                              "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
    selected = preflight(run.store, prepared.handle, seed=run.seed)
    return {"selected": selected, "run_id": run.run_id, "structure": prepared.handle}


def _eight_key(labels: list[str]) -> str:
    content = EIGHT["content"]
    indices = []
    for label in labels:
        seq, to = int(label[1:-1]), label[-1]
        found = [c["index"] for c in content["candidates"]
                 if c["to"] == to and content["positions"][c["position_index"]]["residue"]["seq_auth"] == seq]
        assert len(found) == 1, label
        indices.append(found[0])
    return GI.key_text(sorted(indices))


def _own_rows(selected: dict, labels: list[str]) -> list[dict]:
    """SYNTHETIC-structure rows (no M20 set): the projection residue, its letters and a placeholder index."""
    residues = [r["residue"] for c in selected["protein"] for r in c["residues"]]
    rows = []
    for number, label in enumerate(labels):
        residue = next(r for r in residues if r["seq_auth"] == int(label[1:-1]))
        assert MK.THREE_LETTER[label[0]] == residue["resname"]
        rows.append({"candidate_index": number, "residue": dict(residue), "from": label[0], "to": label[-1],
                     "mutant_resname": MK.THREE_LETTER[label[-1]]})
    return rows


def _payload(world: dict, rows: list[dict], reference: dict | None, *, eight: bool) -> dict:
    selected = world["selected"]
    if eight:
        run_id, candidate_set, structure = RUN_ID, EIGHT["handle"], dict(EIGHT["content"]["structure"])
    else:   # LABELED placeholder candidate-set handle: the SYNTHETIC Cys structures have no M20 set
        run_id = world["run_id"]
        candidate_set = f"obj://{run_id}/mutation_candidate_set/" + "0" * 64
        structure = {"handle": world["structure"], "model_number": selected["model_number"],
                     "structure_kind": "prepared_structure"}
    return {"schema": smw.INPUT_SCHEMA, "run_id": run_id, "candidate_set": candidate_set, "structure": structure,
            "method": {**selected["method"], "pdbfixer_version": version("pdbfixer")},
            "model_number": selected["model_number"], "protein": selected["protein"], "seed": SEED,
            "mutations": rows, "reference": reference}


def _input_bytes(payload: dict) -> bytes:
    return canonical_json({"input_sha256": hashlib.sha256(canonical_json(payload)).hexdigest(), "payload": payload})


def _summary(model: dict) -> dict:
    entry = model["structures"]["wild_type_reference"]
    return {key: entry[key] for key in ("structure_sha256", "protonation_variants", "disulfide_bonds")}


def _launch(folder: Path, raw: bytes) -> subprocess.CompletedProcess:
    folder.mkdir(parents=True)
    (folder / "model_input.json").write_bytes(raw)
    return subprocess.run([str(PROJECT_PYTHON), "-I", str(PROGRAM)], cwd=folder, stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=600, check=False, env={**GUARDIAN_ENV, "TMPDIR": str(folder)})


def _run_all(root: Path, payloads: dict[str, dict]) -> dict[str, dict]:
    def one(name: str):
        folder = root / name
        done = _launch(folder, _input_bytes(payloads[name]))
        assert done.returncode == 0, (name, done.stderr.decode()[-2000:], (folder / "error.json").read_text()
                                      if (folder / "error.json").exists() else None)
        raw = {path.name: path.read_bytes() for path in folder.iterdir()}
        return name, {"payload": payloads[name], "folder": folder, "done": done, "raw": raw,
                      "model": json.loads(raw["model.json"])}

    with ThreadPoolExecutor(max_workers=min(len(payloads), os.cpu_count() or 1)) as pool:
        return dict(pool.map(one, payloads))


@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    return {key: _selected(tmp_path_factory.mktemp(key), name) for key, name in STRUCTURES.items()}


@pytest.fixture(scope="module")
def models(worlds, tmp_path_factory):
    """Every case as a real child process: the wild-type references first, then the mutants with their summary."""
    root = tmp_path_factory.mktemp("children")
    out = _run_all(root, {name: _payload(worlds[structure], [], None, eight=structure == "ubq")
                          for name, structure in WILD.items()})
    references = {"ubq": out["wt"], "ss": out["ss_wt"], "single": out["single_wt"]}
    mutants = {}
    for name, (structure, labels) in MUTANTS.items():
        world = worlds[structure]
        rows = (SB.model_mutations(EIGHT["content"], _eight_key(labels)) if structure == "ubq" else
                _own_rows(world["selected"], labels))
        mutants[name] = _payload(world, rows, _summary(references[structure]["model"]), eight=structure == "ubq")
    return {**out, **_run_all(root, mutants)}


def _side(model: dict) -> str:
    (side,) = model["structures"]
    return side


def _entry(model: dict) -> dict:
    return model["structures"][_side(model)]


def _ident(residue: dict) -> tuple:
    return tuple((type(residue[k]), residue[k]) for k in
                 ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"))


def _refuse_constant(value):
    raise ValueError(value)


# --------------------------------------------------------------------------------------------------- M21 identity

def test_wild_type_and_one_mutation_are_the_stored_m21_structures(models):
    """k = 0 and k = 1 take exactly the M21 path: the mmCIF bytes give the golden M21 structure handles."""
    stored = GOLDEN["requests"]["m21_mutation_model"]
    assert stored["candidate_index"] == int(_eight_key(["I44W"])) and stored["parameters"]["seed"] == SEED
    for name, side in (("wt", "wild_type_reference"), ("i44w", "mutant")):
        cif = models[name]["raw"]["model.cif"]
        sha = hashlib.sha256(b"mutation_model_structure\0mutation_model_structure@1\0" + cif).hexdigest()
        assert f"obj://{RUN_ID}/mutation_model_structure/{sha}" == stored["structure_objects"][side], name
        assert _entry(models[name]["model"])["structure_sha256"] == hashlib.sha256(cif).hexdigest()
        assert _side(models[name]["model"]) == side


# --------------------------------------------------------------------------------------------------- outputs

def test_every_child_exits_zero_and_writes_only_its_outputs(models):
    for name, out in models.items():
        assert out["done"].returncode == 0 and out["done"].stdout == b"" and out["done"].stderr == b"", name
        assert sorted(out["raw"]) == OUTPUTS, name
        assert out["raw"]["model.json"] == canonical_json(out["model"])
        assert len(out["raw"]["model.json"]) <= SC.MAX_MODEL_OBJECT_BYTES == 16 * 1024 * 1024
        model = out["model"]
        assert model["method"] == {**out["payload"]["method"], "multi_mutation": "sequential_structure_order_round4"}
        assert model["seed"] == SEED and model["mutations"] == out["payload"]["mutations"]
        assert model["candidate_set"] == out["payload"]["candidate_set"]
        assert model["structure"] == out["payload"]["structure"]
        assert set(_entry(model)) == {"structure_object", "structure_sha256", "system_xml_sha256", "topology_sha256",
                                      "heavy_atoms", "added_hydrogens", "added_heavy_atoms", "protonation_variants",
                                      "disulfide_bonds", "final_bonds", "atom_mapping", "energy"}   # no SASA/contacts


def test_same_input_gives_the_same_bytes(models):
    for first, second in (("wt", "wt_repeat"), ("k4_ends", "k4_ends_repeat")):
        assert models[first]["raw"] == models[second]["raw"]


def test_potentials_are_finite_and_not_increased(models):
    for name, out in models.items():
        energy = _entry(out["model"])["energy"]
        assert math.isfinite(energy["before_kJ_mol"]) and math.isfinite(energy["after_kJ_mol"]), name
        assert energy["after_kJ_mol"] <= energy["before_kJ_mol"] + MK.ENERGY_INCREASE_TOLERANCE_KJ_MOL, name
        assert {k: energy[k] for k in MK.ENERGY_FIXED} == MK.ENERGY_FIXED


# --------------------------------------------------------------------------------------------------- M21 rules

def _amber_heavy(resname: str, terminal: bool) -> set[str]:
    root = ET.parse(Path(forcefield.__file__).parent / "data" / "amber14" / "protein.ff14SB.xml").getroot()
    elements = {node.attrib["name"]: node.attrib["element"] for node in root.findall("./AtomTypes/Type")}
    name = {"HIS": "HID"}.get(resname, resname)
    name = ("C" + name) if terminal else name
    node = next(n for n in root.findall("./Residues/Residue") if n.attrib["name"] == name)
    return {a.attrib["name"] for a in node.findall("Atom") if elements[a.attrib["type"]] != "H"}


@pytest.mark.parametrize("name", [n for n in UBQ_MUTANTS if not n.endswith("_repeat")] + ["ss_c4a", "single_t66c"])
def test_outside_the_mutated_residues_nothing_is_added_or_moved(name, models):
    out = models[name]
    payload = out["payload"]
    residues = W._flatten(payload["protein"])
    steps = [(W._target(residues, row["residue"]), row["mutant_resname"]) for row in payload["mutations"]]
    projection, added = smw.sequential_projection(residues, steps, SEED)
    mutated = dict(steps)
    last = steps[-1][0]
    for k, (before, after) in enumerate(zip(residues, projection, strict=True)):
        if k not in mutated:
            assert after == before, k                                   # same refs, names, order, exact floats
            continue
        kept = {a["atom_name"]: a for a in before["atoms"]}
        for atom in after["atoms"]:
            if atom["atom_name"] in kept:                              # incl. N CA C O and OXT: input coordinates
                assert atom["coordinates_A"] == kept[atom["atom_name"]]["coordinates_A"]
                assert atom["element"] == kept[atom["atom_name"]]["element"]
            elif k != last:                                            # placed by an earlier step: 4 decimals
                assert all(round(x, 4) == x for x in atom["coordinates_A"]), (k, atom["atom_name"])
        terminal = k == len(residues) - 1 or residues[k + 1]["chain_index"] != residues[k]["chain_index"]
        assert {a["atom_name"] for a in after["atoms"]} == _amber_heavy(mutated[k], terminal)
        assert after["ref"]["resname"] == mutated[k]
    assert added == _entry(out["model"])["added_heavy_atoms"]
    # the model's heavy atoms are this projection's, in order; outside the mutated residues the wild type's
    heavy = [(_ident(a["residue"]), a["atom_name"], a["element"]) for a in _entry(out["model"])["atom_mapping"]
             if a["element"] != "H"]
    assert heavy == [(_ident(r["ref"]), a["atom_name"], a["element"]) for r in projection for a in r["atoms"]]
    reference = models[{"ubq": "wt", "ss": "ss_wt", "single": "single_wt"}[MUTANTS[name][0]]]["model"]
    renamed = {_ident({**row["residue"], "resname": row["mutant_resname"]}) for row in payload["mutations"]}
    original = {_ident(row["residue"]) for row in payload["mutations"]}
    assert [h for h in heavy if h[0] not in renamed] == [
        (_ident(a["residue"]), a["atom_name"], a["element"]) for a in _entry(reference)["atom_mapping"]
        if a["element"] != "H" and _ident(a["residue"]) not in original]


def test_rounding_between_steps_is_what_makes_the_second_step_pass(worlds, monkeypatch):
    residues = W._flatten(worlds["ubq"]["selected"]["protein"])
    rows = SB.model_mutations(EIGHT["content"], _eight_key(["Q2Y", "I3F"]))
    steps = [(W._target(residues, row["residue"]), row["mutant_resname"]) for row in rows]
    first, added = W.mutant_projection(residues, steps[0][0], steps[0][1], SEED)
    rounded = smw.round_placed(first[steps[0][0]], added)
    names = {a["atom_name"] for a in added}
    shifts = [abs(p - q) for a, b in zip(first[steps[0][0]]["atoms"], rounded["atoms"], strict=True)
              for p, q in zip(a["coordinates_A"], b["coordinates_A"], strict=True) if a["atom_name"] in names]
    assert names and 0 < max(shifts) <= 5e-5
    assert [a for a in rounded["atoms"] if a["atom_name"] not in names] == [
        a for a in first[steps[0][0]]["atoms"] if a["atom_name"] not in names]
    smw.sequential_projection(residues, steps, SEED)                   # passes with the rule
    monkeypatch.setattr(smw, "round_placed", lambda residue, placed: residue)
    with pytest.raises(W.ModelFailure) as caught:
        smw.sequential_projection(residues, steps, SEED)
    assert caught.value.reason_code == "coordinates_changed"
    assert caught.value.detail["residue"]["seq_auth"] == 2 and caught.value.detail["residue"]["resname"] == "TYR"


# --------------------------------------------------------------------------------------------------- server parity

def test_handle_and_sidecar_are_the_servers(models, tmp_path):
    for name in ("wt", "k4_ends", "single_t66c"):
        out = models[name]
        run_id = out["payload"]["run_id"]
        cif, entry = out["raw"]["model.cif"], _entry(out["model"])
        sha = hashlib.sha256(b"mutation_set_model_structure\0mutation_set_model_structure@1\0" + cif).hexdigest()
        handle = f"obj://{run_id}/mutation_set_model_structure/{sha}"
        assert entry["structure_object"] == handle
        stored = new_run(tmp_path / name, dry_run=False, run_id=run_id).store.put(
            SC.STRUCTURE_OBJECT_KIND, SC.STRUCTURE_OBJECT_SCHEMA, cif, fmt="cif")
        assert stored.handle == handle
        rows = docking_inputs.receptor_rows(cif, "cif", handle, out["payload"]["model_number"])
        sidecar = out["raw"]["receptor_bonds.json"]
        assert sidecar == docking_inputs.mutation_model_sidecar(rows, entry["atom_mapping"], entry["final_bonds"],
                                                                handle)
        assert json.loads(sidecar)["source_handle"] == handle
        bonds = docking_inputs.receptor_bonds(rows, {"kind": "sidecar"}, cif, "cif", handle, sidecar)
        assert sorted(map(sorted, entry["final_bonds"])) == bonds


def test_real_outputs_pass_the_server_validator_and_rebuild_byte_identically(models):
    reference = models["wt"]["model"]
    common = {"run_id": RUN_ID, "candidate_set_handle": EIGHT["handle"], "candidate_set": EIGHT["content"]}
    assert SB.validated_model(reference, structure_cif=models["wt"]["raw"]["model.cif"], **common) is reference
    for name in ["wt", *UBQ_MUTANTS]:
        out = models[name]
        model, mutations = out["model"], out["payload"]["mutations"]
        if mutations:
            assert SB.validated_model(model, structure_cif=out["raw"]["model.cif"], reference=reference,
                                      **common) is model
        entry = {k: v for k, v in _entry(model).items() if k != "structure_object"}
        rebuilt = SB.model_content(run_id=RUN_ID, candidate_set_handle=EIGHT["handle"],
                                   structure=EIGHT["content"]["structure"], mutations=mutations, seed=SEED,
                                   method=GI.model_method(out["payload"]["method"]), entry=entry,
                                   cif_raw=out["raw"]["model.cif"], reference=reference if mutations else None)
        assert canonical_json(rebuilt) == out["raw"]["model.json"], name


def _differences(reference: dict, model: dict, mutations: list[dict]) -> list[dict]:
    """Recomputed here: HIS/CYS variants outside the mutated residues that differ from the reference entry."""
    original = {_ident(m["residue"]) for m in mutations}
    renamed = {_ident({**m["residue"], "resname": m["mutant_resname"]}) for m in mutations}
    variants = {_ident(v["residue"]): v["variant"] for v in _entry(model)["protonation_variants"]
                if _ident(v["residue"]) not in renamed}
    return [{"residue": v["residue"], "wild_type_reference": v["variant"], "mutant": variants[_ident(v["residue"])]}
            for v in _entry(reference)["protonation_variants"]
            if _ident(v["residue"]) not in original and _ident(v["residue"]) in variants
            and variants[_ident(v["residue"])] != v["variant"]]


def test_protonation_and_disulfide_records_are_against_the_reference(models):
    for name, (structure, _labels) in MUTANTS.items():
        reference = models[{"ubq": "wt", "ss": "ss_wt", "single": "single_wt"}[structure]]["model"]
        model = models[name]["model"]
        assert model["protonation_differences"] == _differences(reference, model, model["mutations"]), name
        assert model["reference_structure_sha256"] == _entry(reference)["structure_sha256"]
    for name in WILD:
        model = models[name]["model"]
        assert (model["protonation_differences"], model["new_disulfide_in_mutant"],
                model["reference_structure_sha256"], model["limitations"]) == ([], False, None, [SC.L1, SC.L3])
        assert _entry(model)["added_heavy_atoms"] == []
    # SYNTHETIC derived Cys structures (M21 cases c4a / t66c, now as one-mutation set models)
    removed = models["ss_c4a"]["model"]
    assert [(d["residue"]["seq_auth"], d["wild_type_reference"], d["mutant"])
            for d in removed["protonation_differences"]] == [(66, "CYX", None)]
    assert removed["new_disulfide_in_mutant"] is False and removed["limitations"] == [SC.L1, SC.L3, SC.SL5]
    made = models["single_t66c"]["model"]
    assert sorted(r["seq_auth"] for pair in _entry(made)["disulfide_bonds"] for r in pair) == [4, 66]
    assert [(d["residue"]["seq_auth"], d["wild_type_reference"], d["mutant"])
            for d in made["protonation_differences"]] == [(4, None, "CYX")]
    assert made["new_disulfide_in_mutant"] is True and made["limitations"] == [SC.L1, SC.L3, SC.SL5, SC.L6]


# --------------------------------------------------------------------------------------------------- failures

def _main(folder: Path, raw: bytes, monkeypatch) -> tuple[int, list[str]]:
    folder.mkdir()
    (folder / "model_input.json").write_bytes(raw)
    monkeypatch.chdir(folder)
    code = smw.main()
    return code, sorted(path.name for path in folder.iterdir())


def _closed_error(folder: Path, code: int, files: list[str], reason: str) -> dict:
    assert code == 1 and files == ["error.json", "model_input.json"], (code, files)
    error = json.loads((folder / "error.json").read_bytes(), parse_constant=_refuse_constant)
    assert set(error) == {"reason_code", "message", "detail"} and error["reason_code"] == reason, error
    assert error["detail"]["reason_code"] == reason and 0 < len(error["message"]) <= 300
    return error


def _ubq_payload(worlds, models, labels: list[str]) -> dict:
    rows = SB.model_mutations(EIGHT["content"], _eight_key(labels)) if labels else []
    return _payload(worlds["ubq"], rows, _summary(models["wt"]["model"]) if labels else None, eight=True)


def _engine_fault(prepared):
    raise openmm.OpenMMException("labeled test fault")


FAILURES = {
    # reason: (mutations, how) -- real inputs where the M21 functions refuse them, monkeypatched M21 functions
    # (a ModelFailure raised inside the unmodified M21 code path) where a real input is impractical.
    "unexpected_atoms_added": (["I44W"], "damage_g10_o"),
    "coordinates_changed": (["Q2Y", "I3F"], "no_rounding"),
    "mutation_modeling_failed": (["I44W"], "apply_mutations_refuses"),
    "topology_unsupported": ([], "unknown_residue_name"),
    "energy_invalid": ([], "nonfinite_potential"),
    "engine_failed": ([], "engine_exception"),
    "resource_exceeded": ([], "model_object_limit"),
}


@pytest.mark.parametrize("reason", sorted(FAILURES))
def test_closed_failure_reasons_write_error_json_and_exit_1(reason, worlds, models, tmp_path, monkeypatch):
    labels, how = FAILURES[reason]
    payload = _ubq_payload(worlds, models, labels)
    if how == "damage_g10_o":
        payload = json.loads(json.dumps(payload))
        payload["protein"][0]["residues"][9]["atoms"] = [a for a in payload["protein"][0]["residues"][9]["atoms"]
                                                         if a["atom_name"] != "O"]
    elif how == "no_rounding":
        monkeypatch.setattr(smw, "round_placed", lambda residue, placed: residue)
    elif how == "apply_mutations_refuses":
        def refuse(self, mutations, chain_id):
            raise KeyError("labeled test refusal")
        monkeypatch.setattr(W.PDBFixer, "applyMutations", refuse)
    elif how == "unknown_residue_name":
        payload = json.loads(json.dumps(payload))
        payload["protein"][0]["residues"][9]["residue"]["resname"] = "XXX"
    elif how == "nonfinite_potential":
        monkeypatch.setattr(W, "_minimize", lambda prepared: W._check_energy(-1.0, float("nan")))
    elif how == "engine_exception":
        monkeypatch.setattr(W, "_minimize", _engine_fault)
    elif how == "model_object_limit":
        monkeypatch.setattr(SC, "MAX_MODEL_OBJECT_BYTES", 100_000)
    code, files = _main(tmp_path / "work", _input_bytes(payload), monkeypatch)
    error = _closed_error(tmp_path / "work", code, files, reason)
    if reason == "resource_exceeded":
        assert error["detail"]["limit"] == "model_object_bytes" and error["detail"]["max_bytes"] == 100_000
        assert error["detail"]["bytes"] > 100_000
    if reason == "unexpected_atoms_added":
        assert error["detail"]["residues"] == ["0:10"]


def _mutate(payload: dict, change) -> dict:
    copy = json.loads(json.dumps(payload))
    change(copy)
    return copy


def _set(path: list, value):
    def change(payload):
        target = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return change


REFUSED_PAYLOADS = {
    "extra payload key": lambda p: p.update(contact_cutoff_A=4.0),
    "missing reference key": lambda p: p.pop("reference"),
    "schema": _set(["schema"], "openmm_mutation_model_input@1"),
    "method value": _set(["method", "max_iterations"], 51),
    "method extra key": _set(["method", "multi_mutation"], "sequential_structure_order_round4"),
    "pdbfixer pin": _set(["method", "pdbfixer_version"], "1.11"),
    "run id": _set(["run_id"], "../outside"),
    "seed bool": _set(["seed"], True),
    "seed range": _set(["seed"], -1),
    "structure kind": _set(["structure", "structure_kind"], "mutation_model"),
    "structure model number": _set(["structure", "model_number"], 2),
    "mutation extra key": _set(["mutations", 0, "score"], -7.0),
    "mutation residue unknown": _set(["mutations", 0, "residue", "seq_auth"], 999),
    "mutant name not the to residue": _set(["mutations", 0, "mutant_resname"], "PHE"),
    "same from and to": lambda p: p["mutations"][0].update({"to": "K", "mutant_resname": "LYS"}),
    "not in structure order": lambda p: p.update(mutations=p["mutations"][::-1]),
    "reference missing": _set(["reference"], None),
    "reference extra key": _set(["reference", "atom_mapping"], []),
}


def test_the_refusal_bases_are_valid_inputs(worlds, models):
    for labels in (["K6H", "I44W"], ["I44W"]):
        payload = _ubq_payload(worlds, models, labels)
        smw.verify_payload(payload)
        assert len(smw.mutation_steps(W._flatten(payload["protein"]), payload["mutations"])) == len(labels)
        assert smw.read_input(_input_bytes(payload)) == payload


@pytest.mark.parametrize("name", sorted(REFUSED_PAYLOADS))
def test_refused_inputs_are_engine_failed_before_any_modeling(name, worlds, models, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(W, "mutant_projection", lambda *args: calls.append(args))
    monkeypatch.setattr(W, "_prepare", lambda *args: calls.append(args))
    payload = _mutate(_ubq_payload(worlds, models, ["K6H", "I44W"]), REFUSED_PAYLOADS[name])
    code, files = _main(tmp_path / "work", _input_bytes(payload), monkeypatch)
    _closed_error(tmp_path / "work", code, files, "engine_failed")
    assert calls == []


@pytest.mark.parametrize("name", ["checksum", "extra top key", "nan", "five mutations", "duplicate position",
                                  "wild type with a reference"])
def test_refused_input_files_are_engine_failed(name, worlds, models, tmp_path, monkeypatch):
    monkeypatch.setattr(W, "_prepare", lambda *args: pytest.fail("modeled a refused input"))
    payload = _ubq_payload(worlds, models, ["I44W"])
    raw = _input_bytes(payload)
    if name == "checksum":
        raw = canonical_json({"input_sha256": "0" * 64, "payload": payload})
    elif name == "extra top key":
        raw = canonical_json({**json.loads(raw), "job_id": "job"})
    elif name == "nan":
        raw = raw.replace(b'"seed":20261004', b'"seed":NaN')
    elif name == "five mutations":
        rows = SB.model_mutations(EIGHT["content"], _eight_key(["M1W", "Q2Y", "I3F", "K6H"]))
        extra = SB.model_mutations(EIGHT["content"], _eight_key(["L8W"]))
        raw = _input_bytes({**payload, "mutations": rows + extra})
    elif name == "duplicate position":           # ascending candidate indices (I44F 26, I44W 28), one residue
        rows = SB.model_mutations(EIGHT["content"], _eight_key(["I44F"])) + \
            SB.model_mutations(EIGHT["content"], _eight_key(["I44W"]))
        assert [row["candidate_index"] for row in rows] == [26, 28]
        raw = _input_bytes({**payload, "mutations": rows})
    elif name == "wild type with a reference":
        raw = _input_bytes({**payload, "mutations": []})
    code, files = _main(tmp_path / "work", raw, monkeypatch)
    _closed_error(tmp_path / "work", code, files, "engine_failed")


def test_a_refused_input_in_a_real_child_process(worlds, models, tmp_path):
    payload = _ubq_payload(worlds, models, ["I44W"])
    done = _launch(tmp_path / "work", canonical_json({"input_sha256": "f" * 64, "payload": payload}))
    assert done.returncode == 1 and done.stdout == b"" and done.stderr == b""
    _closed_error(tmp_path / "work", 1, sorted(p.name for p in (tmp_path / "work").iterdir()), "engine_failed")


def test_a_model_the_m18_receptor_rules_refuse_is_still_written(worlds, models, tmp_path, monkeypatch):
    """Spec 2: a model above the M18 receptor atom cap fails the docking step (``receptor_invalid``), not the
    modeling; the program writes the model and the M18 refusal instead of a sidecar (cap lowered for the test)."""
    monkeypatch.setattr(docking_inputs.C, "MAX_RECEPTOR_ATOMS", 1000)
    code, files = _main(tmp_path / "work", _input_bytes(_ubq_payload(worlds, models, [])), monkeypatch)
    assert code == 0 and files == ["model.cif", "model.json", "model_input.json", "receptor_error.json"]
    refusal = json.loads((tmp_path / "work" / "receptor_error.json").read_bytes(), parse_constant=_refuse_constant)
    assert set(refusal) == {"reason_code", "message", "detail"} and refusal["reason_code"] == "receptor_invalid"
    assert refusal["detail"]["reason_code"] == "receptor_invalid" and 0 < len(refusal["message"]) <= 300
    assert (tmp_path / "work" / "model.json").read_bytes() == models["wt"]["raw"]["model.json"]
    assert (tmp_path / "work" / "model.cif").read_bytes() == models["wt"]["raw"]["model.cif"]


def test_model_object_limit_is_the_fixed_constant():
    assert SC.MAX_MODEL_OBJECT_BYTES == 16 * 1024 * 1024
    with pytest.raises(W.ModelFailure) as caught:
        smw.encode_model({"x": "y" * SC.MAX_MODEL_OBJECT_BYTES})
    assert caught.value.reason_code == "resource_exceeded"
    assert smw.encode_model({"x": "y"}) == b'{"x":"y"}'


# --------------------------------------------------------------------------------------------------- isolation

def test_the_program_imports_no_docking_chemistry_and_nothing_imports_it():
    text = PROGRAM.read_text()
    tree = ast.parse(text)
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    names = imported | {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                        for alias in node.names}
    forbidden = {"rdkit", "meeko", "MDAnalysis", "pdbfixer", "subprocess", "socket", "urllib", "httpx", "requests"}
    assert not {m for m in imported if m.split(".")[0] in forbidden}, imported
    assert {m for m in imported if m.split(".")[0] == "importlib"} <= {"importlib.metadata"}   # PDBFixer version
    assert "__import__" not in text and "import_module" not in text and "spec_from_file_location" not in text
    assert "openmm_mutation_worker" in names                    # the unmodified M21 module, imported by name
    importers = []
    for path in sorted((REPO / "backend/mw").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [node.module or ""] + [a.name for a in node.names] if isinstance(node, ast.ImportFrom) else [])
            if any("sequence_model_worker" in n for n in names):
                importers.append(path)
    assert importers == []
    code = ("import json, sys; import mw, mw.jobs.sequence_model_worker; print(json.dumps([mw.__file__, sorted("
            "m for m in ('rdkit', 'meeko', 'MDAnalysis', 'openmm', 'pdbfixer') if m in sys.modules)]))")
    done = subprocess.run([str(PROJECT_PYTHON), "-I", "-c", code], capture_output=True, text=True, timeout=120,
                          check=False, cwd=REPO, env={**GUARDIAN_ENV, "TMPDIR": str(REPO)})
    assert done.returncode == 0, done.stderr
    location, modules = json.loads(done.stdout)
    assert Path(location) == REPO / "backend/mw/__init__.py" and modules == ["openmm", "pdbfixer"]


def test_hashed_files_are_unchanged():
    files = {**GOLDEN["hashed_files"], **{k: v for k, v in GOLDEN["also_hashed_files"].items()
                                          if k.endswith(("openmm_worker.py", "openmm_method.py"))}}
    assert len(files) == 8
    for name, sha in files.items():
        assert hashlib.sha256((REPO / name).read_bytes()).hexdigest() == sha, name


def test_module_pins_name_this_program_and_the_model_bundle():
    assert GI.GA_MODULES["model_worker_sha256"] == PROGRAM
    assert GI.GA_MODULES["model_bundle_sha256"] == REPO / "backend/mw/sequence_model_bundle.py"
    ga_worker = GI.GA_MODULES["ga_worker_sha256"]
    if not ga_worker.is_file():                       # T4 adds the GA worker; until then only it is missing
        with pytest.raises(FileNotFoundError) as caught:
            GI.module_pins()
        assert str(caught.value) == f"sequence GA module missing: {ga_worker}"
    else:
        pins = GI.module_pins()
        assert pins["model_worker_sha256"] == hashlib.sha256(PROGRAM.read_bytes()).hexdigest()
