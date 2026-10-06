"""M24 T2 pure projection module ``mw.jev_projection`` (spec .dryforge/spec.md 3, 4; plan "T1 확정 사항").

Inputs:
* REAL M17 sets: the committed real product output ``fixtures/ligand_ga/m17-candidate-set-small-pool.json`` and a set
  made in this module by real M17 jobs (``ligand_job_fixture.standard_run``: labelled synthetic methacetin parent,
  fixed + user rules, one PAINS row). The RDKit worker FAILS, never skips, when its environment is missing.
* REAL M20 sets made here by the unmodified cheap tool through ``Run.call`` (``load_structure`` ->
  ``prepare_structure`` -> ``generate_mutation_candidates``) on public 1UBQ, public 1MQ4 (+ ADP shell, the M15 map and
  M16 annotation from the reference FIXTURE set) and the labelled synthetic M20 structures (null labels, insertion
  code, multi-letter chain, HID / MSE / SEP).
* LABELLED SYNTHETIC dicts derived from those real shapes (``synthetic_*`` helpers / ``# SYNTHETIC`` comments): made-up
  SMILES-like strings, PAINS names and field changes used only to reach boundaries and refusals; not chemistry.
* LABELLED SYNTHETIC PDB text built in ``_synthetic_geometry_pdb`` (hand-placed atoms; expected neighbors and windows
  computed by hand in the comments).

Oracle for neighbors / windows / distances: the independent T1 oracle ``fixtures/jev/independent_neighbors.py``
(gemmi + math only) and its ``expected.json``; distances compared with ``abs <= 1e-9`` (preflight C8).
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import gemmi
import pytest
from ligand_job_fixture import standard_run
from reference_fixture_set import build_fixture_set

from mw import jev_constants as J
from mw import jev_projection as P
from mw import ligand_bundle, ligand_filters
from mw import reference_snapshots as rs
from mw.tools.registry import ToolContext
from mw.tools.structural import _parse, structure_residues
from mw.workspace import new_run

FIX = Path(__file__).resolve().parent / "fixtures"
TOL = 1e-9
_spec = importlib.util.spec_from_file_location("jev_independent_neighbors", FIX / "jev/independent_neighbors.py")
ORACLE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ORACLE)
EXPECTED = json.loads((FIX / "jev/expected.json").read_text())["structures"]
SMALL_POOL = json.loads((FIX / "ligand_ga/m17-candidate-set-small-pool.json").read_text())
SET_HANDLE = {"ligand": "obj://run_x/ligand_candidate_set/" + "a" * 64,
              "mutation": "obj://run_x/mutation_candidate_set/" + "b" * 64}
STRUCTURE_REF = {"handle": "obj://run_x/prepared_structure/" + "c" * 64, "model_number": 1}
ADP = {"model_number": 1, "chain_auth": "A", "seq_auth": 2001, "icode": "", "resname": "ADP"}


def res(seq_auth: int, resname: str, chain_auth: str = "A", icode: str = "") -> dict:
    return {"model_number": 1, "chain_auth": chain_auth, "seq_auth": seq_auth, "icode": icode, "resname": resname}


def _reason(fn, *args, **kwargs) -> str:
    with pytest.raises(P.JevProjectionError) as caught:
        fn(*args, **kwargs)
    assert caught.value.detail["reason_code"] == caught.value.reason_code
    return caught.value.reason_code


def _keys(value) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(key)
            found |= _keys(item)
    elif isinstance(value, list):
        for item in value:
            found |= _keys(item)
    return found


def _text(value) -> str:
    return json.dumps(value, sort_keys=True)


# ---------------------------------------------------------------- real worlds (module scoped)


def _structure(run, prepared):
    return _parse(ToolContext(store=run.store, call_id="jev_t2_test"), prepared)


def _mutation_world(root: Path, run_id: str, cif: Path, args: dict, *, numbering=False) -> dict:
    run = new_run(root, run_id=run_id, dry_run=False)
    loaded = run.call("load_structure", {"source": str(cif), "model_index": 0}).handle
    prepared = run.call("prepare_structure", {"structure": loaded}).handle
    extra = {}
    if numbering:
        numbering_map = run.call("map_residue_numbering", {"structure": prepared, "pdb_id": "1MQ4",
                                                           "chains": [{"chain_auth": "A"}]}).handle
        annotation = run.call("annotate_reference_sites", {"numbering_map": numbering_map}).handle
        extra = {"numbering_map": numbering_map, "annotation": annotation}
    handle = run.call("generate_mutation_candidates", {"structure": prepared, **args, **extra}).handle
    return {"run": run, "prepared": prepared, "handle": handle, "content": run.store.load(handle),
            "structure": _structure(run, prepared), "extra": extra}


@pytest.fixture(scope="module")
def ubq(tmp_path_factory):
    user = [res(p["residue"]["seq_auth"], p["residue"]["resname"]) for p in EXPECTED["1UBQ"]["positions"]]
    return _mutation_world(tmp_path_factory.mktemp("jev_ubq"), "run_jev_ubq", FIX / "public_1ubq.cif",
                           {"sources": {"pocket": None, "ligand_shell": None, "residues": user}})


@pytest.fixture(scope="module")
def mq4(tmp_path_factory):
    root = tmp_path_factory.mktemp("jev_mq4")
    reference = root / "reference"
    reference.mkdir()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(rs.ENV_VAR, str(reference))
        build_fixture_set(reference)
        user = [res(p["residue"]["seq_auth"], p["residue"]["resname"]) for p in EXPECTED["1MQ4"]["positions"]]
        released = [res(162, "LYS"), res(211, "GLU"), res(274, "ASP")]
        return _mutation_world(root / "runs", "run_jev_mq4", FIX / "public_1mq4.cif",
                               {"sources": {"pocket": None, "ligand_shell": {"radius_A": 5.0}, "residues": user},
                                "ligand": ADP, "released_residues": released}, numbering=True)


@pytest.fixture(scope="module")
def synthetic_m20(tmp_path_factory):
    root = tmp_path_factory.mktemp("jev_syn")
    cif_user = [res(6, "HID"), res(9, "MSE"), res(10, "ILE", icode="A"), res(10, "SEP", "CC"), res(11, "ALA", "CC")]
    pdb_user = [res(10, "LEU"), res(10, "ILE", icode="A"), res(1, "GLY", "B")]
    cif = _mutation_world(root, "run_jev_syn_cif", FIX / "mutation/synthetic-mutation-fixture.cif",
                          {"sources": {"pocket": None, "ligand_shell": None, "residues": cif_user}})
    pdb = _mutation_world(root, "run_jev_syn_pdb", FIX / "mutation/synthetic-mutation-fixture-nolabel.pdb",
                          {"sources": {"pocket": None, "ligand_shell": None, "residues": pdb_user}})
    return {"cif": cif, "pdb": pdb}


@pytest.fixture(scope="module")
def ligand_world(tmp_path_factory):
    world = standard_run(tmp_path_factory.mktemp("jev_lig"), "run_jev_ligand")
    content, inspection = ligand_bundle.validated_candidate_set(world["run"], world["candidate_set"])
    return {"content": content, "inspection": inspection, "world": world}


def _first_candidates(content: dict) -> list[int]:
    first: dict[int, int] = {}
    for candidate in content["candidates"]:
        first.setdefault(candidate["position_index"], candidate["index"])
    return list(first.values())


# ---------------------------------------------------------------- LABELLED SYNTHETIC ligand sets


def synthetic_ligand_set(lengths: list[int], *, pains: int = 0) -> dict:
    """SYNTHETIC: the committed real M17 set's top-level fields with made-up rows (``N...C`` strings of the given
    lengths, unique per row; ``pains`` made-up 64-character PAINS-shaped names per row). Shape only, not chemistry."""
    content = copy.deepcopy(SMALL_POOL)
    template = content["candidates"][0]
    rows = []
    for i, length in enumerate(lengths):
        smiles = "N" * (i + 1) + "C" * (length - i - 1)
        row = copy.deepcopy(template)
        row["smiles"] = smiles
        row["id"] = "c_" + hashlib.sha256(smiles.encode()).hexdigest()[:16]
        row["pains"] = {"matches": [{"catalog": "PAINS_C", "name": f"synthetic_{j:03d}_".ljust(64, "n")}
                                    for j in range(pains)]}
        rows.append(row)
    content["candidates"] = rows
    return content


def _ids(content: dict, positions=None) -> list[str]:
    rows = content["candidates"]
    return [rows[i]["id"] for i in (positions if positions is not None else range(len(rows)))]


def _ligand_body_bytes(content: dict) -> int:
    wire, selection = P.build_ligand_wire(content, _ids(content))
    return len(P.encode_body(wire, J.LIGAND_QUESTION_ID, [s["alias"] for s in selection]))


def _tuned_ligand_set(target: int) -> dict:
    """SYNTHETIC: 20 rows whose spec-4 body is exactly ``target`` bytes (one SMILES character = one body byte)."""
    for pains in range(80):
        lengths = [1024] * 19 + [1000]   # the last row always has room for one more character
        size = _ligand_body_bytes(synthetic_ligand_set(lengths, pains=pains))
        if size >= target:
            break
    excess, row = size - target, 19
    while excess:
        cut = min(excess, lengths[row] - 40)
        lengths[row] -= cut
        excess -= cut
        row -= 1
    content = synthetic_ligand_set(lengths, pains=pains)
    assert _ligand_body_bytes(content) == target
    return content


# ---------------------------------------------------------------- selection (selection_invalid, candidate_unknown)


def test_ligand_selection_is_normalized_to_the_stored_row_order():
    ids = _ids(SMALL_POOL)
    assert P.normalize_selection("ligand", SMALL_POOL, [ids[7], ids[2], ids[5]]) == [2, 5, 7]
    assert P.normalize_selection("ligand", SMALL_POOL, ids[::-1]) == list(range(10))
    # stored order is generation order, not id string order (preflight b: ids are not in string order)
    assert sorted(ids) != ids


@pytest.mark.parametrize("candidates", [
    [], "c_0000000000000000", ("c_1afb7cd3e603456c",), None, ["c_1afb7cd3e603456c", "c_1afb7cd3e603456c"],
    ["c_XYZ"], ["C_1afb7cd3e603456c"], ["c_1afb7cd3e603456"], [5], ["c_1afb7cd3e603456c "]])
def test_ligand_selection_invalid(candidates):
    assert _reason(P.normalize_selection, "ligand", SMALL_POOL, candidates) == "selection_invalid"


def test_ligand_selection_count_boundaries_and_unknown_ids():
    content = synthetic_ligand_set([30 + i for i in range(25)])  # SYNTHETIC rows
    ids = _ids(content)
    assert P.normalize_selection("ligand", content, ids[:20]) == list(range(20))
    assert P.normalize_selection("ligand", content, ids[:1]) == [0]
    assert _reason(P.normalize_selection, "ligand", content, ids[:21]) == "selection_invalid"
    assert _reason(P.normalize_selection, "ligand", content, [ids[0], "c_" + "0" * 16]) == "candidate_unknown"


def test_mutation_selection_is_index_ascending_and_typed(ubq):
    content = ubq["content"]
    count = len(content["candidates"])
    assert P.normalize_selection("mutation", content, [40, 3, 17]) == [3, 17, 40]
    for bad in ([], [True], ["3"], [1.0], [3, 3], list(range(21)), None, (1, 2)):
        assert _reason(P.normalize_selection, "mutation", content, bad) == "selection_invalid", bad
    for unknown in ([-1], [count], [0, 10**6]):
        assert _reason(P.normalize_selection, "mutation", content, unknown) == "candidate_unknown", unknown
    with pytest.raises(ValueError):
        P.normalize_selection("protein", content, [0])


# ---------------------------------------------------------------- ligand wire


def test_ligand_wire_from_the_committed_real_set():
    ids = _ids(SMALL_POOL)
    wire, selection = P.build_ligand_wire(SMALL_POOL, [ids[4], ids[0], ids[9]])
    rows = [SMALL_POOL["candidates"][i] for i in (0, 4, 9)]
    assert selection == [{"alias": "c01", "candidate_id": ids[0]}, {"alias": "c02", "candidate_id": ids[4]},
                         {"alias": "c03", "candidate_id": ids[9]}]
    assert list(wire) == list(J.ALLOWED_LIGAND_TOP)
    assert (wire["schema"], wire["task"]) == ("jev_ligand_candidates@1", "choose_one_candidate")
    assert wire["parent"] == {"smiles": SMALL_POOL["parent_canonical_smiles"],
                              "properties": SMALL_POOL["parent_properties"]}
    assert wire["property_methods"] == SMALL_POOL["property_methods"] == J.PROPERTY_METHODS
    assert wire["values_note"] == J.LIGAND_VALUES_NOTE
    for alias, candidate, row in zip(("c01", "c02", "c03"), wire["candidates"], rows, strict=True):
        assert candidate == {"alias": alias, "smiles": row["smiles"], "generation_kinds": ["fixed_replace"],
                             "stereo_flag": row["stereo_flag"], "properties": row["properties"],
                             "pains_matches": []}
        for name in J.PROPERTY_NAMES:   # stored numbers, same type, never rounded
            assert type(candidate["properties"][name]) is type(row["properties"][name])
            assert candidate["properties"][name] == row["properties"][name]
    text = _text(wire)
    for row in SMALL_POOL["candidates"]:
        for value in (row["id"], *(o["block_name"] for o in row["origins"])):
            assert json.dumps(value) not in text, value
    for forbidden in ("obj://", "block", "rule_id", "\"fixed\"", "retained", "inspection", "parent_handle", "sha256",
                      SMALL_POOL["parent_sha256"]):
        assert forbidden not in text, forbidden
    assert not _keys(wire) & {"handle", "run_id", "path", "id", "origins", "receptor", "pocket", "pockets"}


def test_ligand_wire_is_independent_of_the_request_order():
    ids = _ids(SMALL_POOL)
    assert P.build_ligand_wire(SMALL_POOL, ids[:6]) == P.build_ligand_wire(SMALL_POOL, ids[:6][::-1])


def test_ligand_wire_from_a_real_m17_job(ligand_world):
    content, inspection = ligand_world["content"], ligand_world["inspection"]
    ids = _ids(content)
    wire, selection = P.build_ligand_wire(content, ids, inspection=inspection)
    assert [s["candidate_id"] for s in selection] == ids
    expected_kinds = [sorted({"fixed_replace" if o["rule_id"] == "fixed" else "user_rule" for o in row["origins"]})
                      for row in content["candidates"]]
    assert [c["generation_kinds"] for c in wire["candidates"]] == expected_kinds
    assert ["fixed_replace", "user_rule"] in expected_kinds and ["user_rule"] in expected_kinds
    assert [c["pains_matches"] for c in wire["candidates"]] == [
        [{"catalog": m["catalog"], "name": m["name"]} for m in row["pains"]["matches"]] for row in content["candidates"]]
    assert any(c["pains_matches"] for c in wire["candidates"])
    assert wire["parent"]["smiles"] == content["parent_canonical_smiles"] == inspection["parent"]["canonical_smiles"]
    text = _text(wire)
    leaked = {o["block_name"] for row in content["candidates"] for o in row["origins"]} | set(ids)
    leaked |= {rule["text"] for rule in content["rules_used"] if rule["text"]}
    leaked |= {o["rule_id"] for row in content["candidates"] for o in row["origins"]}
    for value in leaked:
        assert json.dumps(value) not in text, value
    assert "obj://" not in text and not _keys(wire) & {"handle", "run_id", "path", "id", "origins", "block_name"}


def test_ligand_parent_falls_back_to_the_inspection_then_is_omitted(ligand_world):
    content, inspection = copy.deepcopy(ligand_world["content"]), ligand_world["inspection"]
    ids = _ids(content)[:2]
    del content["parent_canonical_smiles"]   # SYNTHETIC: a set without the stored parent SMILES
    wire, _ = P.build_ligand_wire(content, ids, inspection=inspection)
    assert wire["parent"]["smiles"] == inspection["parent"]["canonical_smiles"]
    wire, _ = P.build_ligand_wire(content, ids)
    assert wire["parent"] == {"properties": content["parent_properties"]}
    P.check_wire(wire, "ligand")


def _row_change(change):
    def apply(content):
        change(content["candidates"][1])
    return apply


UNSAFE_LIGAND = {   # SYNTHETIC field changes of the committed real set
    "smiles_space": _row_change(lambda r: r.update(smiles="CC O")),
    "smiles_too_long": _row_change(lambda r: r.update(smiles="C" * 1025)),
    "smiles_handle": _row_change(lambda r: r.update(smiles="obj://run_x/ligand_sdf/abc")),
    "smiles_absolute_path": _row_change(lambda r: r.update(smiles="/Users/me/ligand.sdf")),
    "smiles_relative_path": _row_change(lambda r: r.update(smiles="../runs/run_x/events.jsonl")),
    "smiles_file_name": _row_change(lambda r: r.update(smiles="CCO.sdf")),
    "smiles_not_a_string": _row_change(lambda r: r.update(smiles=["CCO"])),
    "property_nan": _row_change(lambda r: r["properties"].update(tpsa=float("nan"))),
    "property_inf": _row_change(lambda r: r["properties"].update(mol_weight=float("inf"))),
    "property_bool": _row_change(lambda r: r["properties"].update(hbd=True)),
    "property_string": _row_change(lambda r: r["properties"].update(hba="10")),
    "property_missing": _row_change(lambda r: r["properties"].pop("tpsa")),
    "stereo_unknown": _row_change(lambda r: r.update(stereo_flag="racemic")),
    "pains_catalog": _row_change(lambda r: r["pains"].update(matches=[{"catalog": "BRENK", "name": "x"}])),
    "pains_name_space": _row_change(lambda r: r["pains"].update(matches=[{"catalog": "PAINS_A", "name": "a b"}])),
    "pains_name_slash": _row_change(lambda r: r["pains"].update(matches=[{"catalog": "PAINS_A", "name": "a/b"}])),
    "pains_name_long": _row_change(lambda r: r["pains"].update(matches=[{"catalog": "PAINS_A", "name": "n" * 65}])),
    "origins_missing": _row_change(lambda r: r.pop("origins")),
    "origins_empty": _row_change(lambda r: r.update(origins=[])),
    "parent_smiles_unsafe": lambda c: c.update(parent_canonical_smiles="C C"),
    "parent_property_nan": lambda c: c["parent_properties"].update(crippen_logp=float("nan")),
    "property_methods_changed": lambda c: c["property_methods"].update(tpsa="rdkit CalcTPSA"),
    "property_methods_missing": lambda c: c["property_methods"].pop("hbd"),
}


@pytest.mark.parametrize("name", sorted(UNSAFE_LIGAND))
def test_ligand_wire_refuses_unsafe_or_unknown_values(name):
    content = copy.deepcopy(SMALL_POOL)
    UNSAFE_LIGAND[name](content)
    ids = _ids(content)
    assert _reason(P.build_ligand_wire, content, ids[:3]) == "wire_field_invalid"


def test_ligand_extra_stored_fields_are_never_copied():
    content = copy.deepcopy(SMALL_POOL)   # SYNTHETIC: extra stored keys the wire builder must not read
    content["candidates"][0]["properties"]["qed"] = 0.5
    content["candidates"][0]["score"] = 1
    content["candidates"][0]["pains"]["matches"] = [{"catalog": "PAINS_A", "name": "ene_rhod_A(235)", "smarts": "x"}]
    content["receptor"] = {"handle": "obj://x"}
    wire, _ = P.build_ligand_wire(content, _ids(content)[:1])
    assert set(wire["candidates"][0]["properties"]) == set(J.PROPERTY_NAMES)
    assert wire["candidates"][0]["pains_matches"] == [{"catalog": "PAINS_A", "name": "ene_rhod_A(235)"}]
    assert "score" not in _keys(wire) and "smarts" not in _text(wire) and "obj://" not in _text(wire)


# ---------------------------------------------------------------- neighbors and windows: oracle on public structures


@pytest.mark.parametrize("name", ["1UBQ", "1MQ4"])
def test_neighbors_and_windows_equal_the_independent_oracle(name, ubq, mq4):
    world = ubq if name == "1UBQ" else mq4
    st = world["structure"]
    for position in EXPECTED[name]["positions"]:
        target = position["residue"]
        assert P.neighbors_of(st, target) == position["neighbors"], target
        window = {k: position["window"][k] for k in J.ALLOWED_WINDOW}
        assert P.window_of(st, target) == window, target
    counts = {(c, s, i): n for c, s, i, _, n in EXPECTED[name]["neighbor_counts"]}
    walked = [r for r in structure_residues(world["run"].store, world["prepared"])["residues"]
              if r["category"] == "polymer"]
    assert len(walked) == len(counts) == EXPECTED[name]["protein_residues"]
    for residue in walked:
        seven = {k: residue[k] for k in J.ALLOWED_RESIDUE}
        assert len(P.neighbors_of(st, seven)) == counts[(residue["chain_auth"], residue["seq_auth"],
                                                         residue["icode"])], seven


def test_1mq4_gap_and_chain_end_windows(mq4):
    st = mq4["structure"]
    assert P.window_of(st, res(285, "ARG")) == {"chain_auth": "A", "first_seq_auth": 280,
                                                "residues": "HAPSSRTLCGT", "contiguous": False}
    assert P.window_of(st, res(126, "ARG"))["residues"] == "RQWALE"     # cut at the chain start
    assert P.window_of(st, res(388, "SER"))["residues"] == "ITANSS"     # cut at the chain end
    assert P.window_of(st, res(143, "LYS"))["contiguous"] is True


@pytest.mark.parametrize("which", ["cif", "pdb"])
def test_synthetic_m20_structures_agree_with_the_oracle_functions(which, synthetic_m20):
    world = synthetic_m20[which]
    st = world["structure"]
    oracle_residues = ORACLE.residues(st)
    for entry in oracle_residues:
        if not entry["protein"]:
            continue
        target = ORACLE.ident(entry)
        assert P.neighbors_of(st, target) == ORACLE.neighbors(oracle_residues, entry)[0], target
        expected = ORACLE.window(oracle_residues, entry)
        assert P.window_of(st, target) == {k: expected[k] for k in J.ALLOWED_WINDOW}, target


def _atom(serial, record, name, resname, chain, seq, icode, xyz, element):
    x, y, z = xyz
    return (f"{record:<6}{serial:>5} {name:<4} {resname:>3} {chain}{seq:>4}{icode or ' '}   "
            f"{x:>8.3f}{y:>8.3f}{z:>8.3f}{1.0:>6.2f}{0.0:>6.2f}          {element:>2}")


def _synthetic_geometry_pdb() -> str:
    """SYNTHETIC hand-placed atoms. Target ALA A1 heavy atom CA at the origin (its own H at (0, -1, 0)).

    Expected neighbors of A1 (heavy-atom minimum distance <= 5.0 A, protein, any chain, structure order):
    GLY A2 (exactly 5.0, inclusive), ALA B1 (4.0, other chain). Not neighbors: SER A3 (5.001), THR A4 (heavy 10.0;
    its H at 4.0 does not count), VAL A5 (heavy 10.0; its D at 4.0 does not count), LEU A6 (5.9 from CA; 4.9 only from
    A1's own H), HOH / ZN / LIG (HETATM, never neighbors), A1 itself. GLY E1 has only an H atom (no heavy atom).
    Chain C (far away) tests windows: C1 ALA, C2 HID (H: one of the ten M20 mapped names), C3 GLY, C3A GLY (insertion
    code), C4 MSE as ATOM (X: neither standard nor mapped), C5 SER .. C12 GLU; chain D: 1, 2, 5 (a numbering gap).
    """
    rows = [
        ("ATOM", "CA", "ALA", "A", 1, "", (0, 0, 0), "C"), ("ATOM", "H", "ALA", "A", 1, "", (0, -1, 0), "H"),
        ("ATOM", "CA", "GLY", "A", 2, "", (5, 0, 0), "C"), ("ATOM", "CA", "SER", "A", 3, "", (5.001, 0, 0), "C"),
        ("ATOM", "CA", "THR", "A", 4, "", (0, 10, 0), "C"), ("ATOM", "HA", "THR", "A", 4, "", (0, 4, 0), "H"),
        ("ATOM", "CA", "VAL", "A", 5, "", (0, 0, 10), "C"), ("ATOM", "D", "VAL", "A", 5, "", (0, 0, 4), "D"),
        ("ATOM", "CA", "LEU", "A", 6, "", (0, -5.9, 0), "C"),
        ("ATOM", "CA", "ALA", "B", 1, "", (0, 0, -4), "C"),
        ("ATOM", "H", "GLY", "E", 1, "", (60, 60, 60), "H"),
    ]
    for i, (seq, icode, name) in enumerate([(1, "", "ALA"), (2, "", "HID"), (3, "", "GLY"), (3, "A", "GLY"),
                                            (4, "", "MSE"), (5, "", "SER"), (6, "", "THR"), (7, "", "VAL"),
                                            (8, "", "TRP"), (9, "", "TYR"), (10, "", "LYS"), (11, "", "ARG"),
                                            (12, "", "GLU")]):
        rows.append(("ATOM", "CA", name, "C", seq, icode, (100 + 10 * i, 0, 0), "C"))
    for i, seq in enumerate((1, 2, 5)):
        rows.append(("ATOM", "CA", "GLY", "D", seq, "", (0, 300 + 10 * i, 0), "C"))
    rows += [("HETATM", "O", "HOH", "A", 101, "", (1, 0, 0), "O"), ("HETATM", "ZN", "ZN", "A", 201, "", (0, 1, 0), "ZN"),
             ("HETATM", "C1", "LIG", "A", 301, "", (0, 0, 1), "C")]
    lines = [_atom(n, *row) for n, row in enumerate(rows, 1)]
    return "\n".join([*lines, "END", ""])


@pytest.fixture(scope="module")
def geometry():
    return gemmi.read_pdb_string(_synthetic_geometry_pdb())


def test_neighbor_boundary_hydrogens_self_and_non_protein(geometry):
    neighbors = P.neighbors_of(geometry, res(1, "ALA"))
    assert neighbors == [{"chain_auth": "A", "seq_auth": 2, "icode": "", "resname": "GLY"},
                         {"chain_auth": "B", "seq_auth": 1, "icode": "", "resname": "ALA"}]
    assert P.neighbors_of(geometry, res(2, "GLY"))[0] == {"chain_auth": "A", "seq_auth": 1, "icode": "",
                                                          "resname": "ALA"}
    assert P.neighbors_of(geometry, res(1, "GLY", "E")) is None   # no heavy atom: not computed, never []
    assert P.window_of(geometry, res(1, "GLY", "E")) == {"chain_auth": "E", "first_seq_auth": 1, "residues": "G",
                                                         "contiguous": True}


def test_windows_letters_insertion_codes_gaps_and_chain_ends(geometry):
    # the M20 letter rule: 20 standard names + the ten mapped names (HID -> H); any other name (MSE) -> X
    assert P.window_of(geometry, res(1, "ALA", "C")) == {"chain_auth": "C", "first_seq_auth": 1,
                                                         "residues": "AHGGXS", "contiguous": False}
    assert P.window_of(geometry, res(4, "MSE", "C")) == {"chain_auth": "C", "first_seq_auth": 1,
                                                         "residues": "AHGGXSTVWY", "contiguous": False}
    assert P.window_of(geometry, res(10, "LYS", "C")) == {"chain_auth": "C", "first_seq_auth": 5,
                                                          "residues": "STVWYKRE", "contiguous": True}
    assert P.window_of(geometry, res(3, "GLY", "C", icode="A"))["residues"] == "AHGGXSTVW"
    assert P.window_of(geometry, res(2, "GLY", "D")) == {"chain_auth": "D", "first_seq_auth": 1, "residues": "GGG",
                                                         "contiguous": False}


def test_window_letters_follow_the_m20_name_rule():
    # every mapped name gets its standard letter, any other non-standard name X (same rule as M20 one_letter)
    mapped = {"HID": "H", "HIE": "H", "HIP": "H", "HSD": "H", "HSE": "H", "HSP": "H", "CYX": "C", "ASH": "D",
              "GLH": "E", "LYN": "K"}
    names = [*J.ONE_LETTER, *mapped, "MSE", "SEP", "UNK"]
    rows = [("ATOM", "CA", name, "A", seq, "", (4.0 * seq, 0, 0), "C") for seq, name in enumerate(names, 1)]
    st = gemmi.read_pdb_string("\n".join([*(_atom(n, *row) for n, row in enumerate(rows, 1)), "END", ""]))
    expected = {**J.ONE_LETTER, **mapped, "MSE": "X", "SEP": "X", "UNK": "X"}
    for seq, name in enumerate(names, 1):   # SYNTHETIC: one CA per residue, 4 A apart
        window = P.window_of(st, res(seq, name))
        before = min(seq - 1, J.WINDOW_FLANK)
        assert window["residues"][before] == expected[name], name


def test_hand_geometry_agrees_with_the_independent_oracle(geometry):
    # the oracle's W2 (window letters) and N3 (no heavy atom: neighbors null, never []) readings equal the module's
    entries = ORACLE.residues(geometry)
    for entry in entries:
        if not entry["protein"]:
            continue
        target = ORACLE.ident(entry)
        assert P.neighbors_of(geometry, target) == ORACLE.neighbors(entries, entry)[0], target
        expected = ORACLE.window(entries, entry)
        assert P.window_of(geometry, target) == {k: expected[k] for k in J.ALLOWED_WINDOW}, target
    no_heavy = next(entry for entry in entries if entry["chain_auth"] == "E")
    assert ORACLE.neighbors(entries, no_heavy) == (None, {"largest_included_A": None, "smallest_excluded_A": None})


def test_unresolvable_residue_is_structure_unavailable(geometry):
    for target in (res(99, "ALA"), res(1, "GLY"), res(101, "HOH"), res(1, "ALA", "Z"),
                   {**res(1, "ALA"), "chain_label": "A"}, {**res(1, "ALA"), "model_number": 2}):
        assert _reason(P.neighbors_of, geometry, target) == "structure_unavailable", target
        assert _reason(P.window_of, geometry, target) == "structure_unavailable", target


# ---------------------------------------------------------------- mutation wire


def test_mutation_wire_on_real_1mq4_matches_the_oracle_and_hides_reference_values(mq4):
    content, st = mq4["content"], mq4["structure"]
    oracle_seq = {p["residue"]["seq_auth"] for p in EXPECTED["1MQ4"]["positions"]}
    chosen = [index for index in _first_candidates(content)
              if content["positions"][content["candidates"][index]["position_index"]]["residue"]["seq_auth"]
              in oracle_seq]
    assert 5 <= len(chosen) <= 10
    chosen.append(next(c["index"] for c in content["candidates"]
                        if c["position_index"] == content["candidates"][chosen[0]]["position_index"]
                        and c["index"] != chosen[0]))
    wire, selection = P.build_mutation_wire(content, chosen, st)
    assert wire == P.build_mutation_wire(content, chosen[::-1], st)[0]
    order = sorted(chosen)
    assert [s["candidate_index"] for s in selection] == order
    assert [s["alias"] for s in selection] == [f"m{n:02d}" for n in range(1, len(order) + 1)]
    assert [s["position_index"] for s in selection] == [content["candidates"][i]["position_index"] for i in order]
    assert list(wire) == ["schema", "task", "positions", "candidates", "protection_checks", "values_note"]
    assert (wire["schema"], wire["task"], wire["values_note"]) == ("jev_mutation_candidates@1",
                                                                   "choose_one_candidate", J.MUTATION_VALUES_NOTE)
    # position aliases in first-appearance order of the index-ascending candidates
    first_seen = list(dict.fromkeys(c["pos"] for c in wire["candidates"]))
    assert first_seen == [p["pos"] for p in wire["positions"]] == [f"p{n:02d}" for n in range(1, len(first_seen) + 1)]
    by_pos = {p["pos"]: p for p in wire["positions"]}
    oracle = {p["residue"]["seq_auth"]: p for p in EXPECTED["1MQ4"]["positions"]}
    stored_positions = content["positions"]
    for item, candidate in zip(selection, wire["candidates"], strict=True):
        stored = content["candidates"][item["candidate_index"]]
        position = by_pos[candidate["pos"]]
        source = stored_positions[stored["position_index"]]
        assert candidate == {"alias": item["alias"], "pos": candidate["pos"], "from": stored["from"],
                             "to": stored["to"]}
        assert position["residue"] == source["residue"] and position["one_letter"] == source["one_letter"]
        assert position["sources"] == [k for k in J.SOURCE_NAMES if any(s["kind"] == k for s in source["sources"])]
        assert position["protection_released"] is source["protection"]["released"]
        assert position["ligand_min_distance_A"] == source["ligand_min_distance_A"]
        seq = source["residue"]["seq_auth"]
        if seq in oracle:
            assert position["neighbors"] == oracle[seq]["neighbors"]
            assert position["window"] == {k: oracle[seq]["window"][k] for k in J.ALLOWED_WINDOW}
            assert abs(position["ligand_min_distance_A"] - oracle[seq]["ligand_min_distance_A"]) <= TOL
    released = {p["residue"]["seq_auth"] for p in wire["positions"] if p["protection_released"]}
    assert released == {162, 211, 274}
    assert wire["protection_checks"] == {key: content["protection_checks"][key]["status"]
                                         for key in J.PROTECTION_CHECK_KEYS}
    assert wire["protection_checks"]["klifs_key_sites"] == "checked"
    assert wire["protection_checks"]["catalytic_residue_database"] == "not_available"
    allowed = (set(J.ALLOWED_MUTATION_TOP) | set(J.ALLOWED_MUTATION_POSITION) | set(J.ALLOWED_RESIDUE)
               | set(J.ALLOWED_WINDOW) | set(J.ALLOWED_NEIGHBOR) | set(J.ALLOWED_MUTATION_CANDIDATE)
               | set(J.PROTECTION_CHECK_KEYS))
    assert _keys(wire) <= allowed
    text = _text(wire)
    numbering_values = {v for p in stored_positions if p["numbering"] for k, v in p["numbering"].items()
                        if k in ("uniprot_accession", "klifs_label") and v}
    klifs_labels = {label for p in stored_positions for label in (p["protection"]["klifs_sites"] or [])}
    assert numbering_values and klifs_labels
    for value in numbering_values | klifs_labels | {"user_protected", "klifs_key_site", "disulfide_cys",
                                                    "annotation_not_given", "not_implemented", "MG"}:
        assert json.dumps(value) not in text, value
    assert "obj://" not in text and mq4["extra"]["numbering_map"] not in text and "threshold" not in text


def test_mutation_wire_on_real_1ubq_matches_the_oracle(ubq):
    content, st = ubq["content"], ubq["structure"]
    wire, _ = P.build_mutation_wire(content, _first_candidates(content), st)
    oracle = {p["residue"]["seq_auth"]: p for p in EXPECTED["1UBQ"]["positions"]}
    assert [p["residue"]["seq_auth"] for p in wire["positions"]] == sorted(oracle)
    for position in wire["positions"]:
        expected = oracle[position["residue"]["seq_auth"]]
        assert position["neighbors"] == expected["neighbors"]
        assert position["window"] == {k: expected["window"][k] for k in J.ALLOWED_WINDOW}
        assert position["ligand_min_distance_A"] is None and position["sources"] == ["user"]
    assert wire["protection_checks"] == {"user_list": "checked", "klifs_key_sites": "not_checked",
                                         "metal_contact": "checked", "disulfide": "checked",
                                         "catalytic_residue_database": "not_available"}
    assert "pockets" not in wire


def test_mutation_wire_keeps_null_labels_insertion_codes_and_multi_letter_chains(synthetic_m20):
    cif = synthetic_m20["cif"]
    wire, _ = P.build_mutation_wire(cif["content"], _first_candidates(cif["content"]), cif["structure"])
    residues = {(p["residue"]["chain_auth"], p["residue"]["seq_auth"], p["residue"]["icode"]): p["residue"]
                for p in wire["positions"]}
    assert ("A", 10, "A") in residues and ("CC", 11, "") in residues and ("A", 6, "") in residues
    assert residues[("CC", 11, "")]["seq_label"] is None and residues[("CC", 11, "")]["chain_label"] == "C"
    assert residues[("A", 6, "")]["resname"] == "HID"
    one_letter = {(p["residue"]["chain_auth"], p["residue"]["seq_auth"]): p["one_letter"] for p in wire["positions"]}
    assert one_letter[("A", 6)] == "H"   # the M20 mapped letter, stored value
    windows = {(p["residue"]["chain_auth"], p["residue"]["seq_auth"], p["residue"]["icode"]): p["window"]
               for p in wire["positions"]}
    assert windows[("A", 10, "A")]["contiguous"] is False
    # HID -> H and CYX -> C (M20 mapped names, the position's own one_letter rule), MSE -> X
    assert windows[("A", 6, "")]["residues"] == "GASTCHVCXLI"
    # chain CC: HSP/ASH/GLH/LYN mapped, CC9 MSE is HETATM (not a protein residue), SEP -> X
    assert windows[("CC", 11, "")]["residues"] == "HDEKXA"
    chains = {}
    for residue in structure_residues(cif["run"].store, cif["prepared"])["residues"]:
        if residue["category"] == "polymer":
            chains.setdefault(residue["chain_auth"], []).append((residue["seq_auth"], residue["icode"]))
    for position in wire["positions"]:   # the window letter at the target equals the stored one_letter
        residue = position["residue"]
        before = min(chains[residue["chain_auth"]].index((residue["seq_auth"], residue["icode"])), J.WINDOW_FLANK)
        assert position["window"]["residues"][before] == position["one_letter"], residue
    pdb = synthetic_m20["pdb"]
    wire, _ = P.build_mutation_wire(pdb["content"], _first_candidates(pdb["content"]), pdb["structure"])
    assert wire["positions"] and all(p["residue"]["chain_label"] is None and p["residue"]["seq_label"] is None
                                     for p in wire["positions"])
    assert any(p["residue"]["icode"] == "A" for p in wire["positions"])
    assert any(p["residue"]["icode"] == "" for p in wire["positions"])
    P.check_wire(wire, "mutation")


def test_pockets_are_copied_without_the_pocket_set_handle(ubq):
    content = copy.deepcopy(ubq["content"])   # SYNTHETIC: a pocket source added to the real 1UBQ set
    content["pockets"] = {"pocket_set": "obj://run_jev_ubq/pocket_set/" + "d" * 64, "ranks": [1, 3],
                          "lining_residue_count": 17}
    content["positions"][0]["sources"] = [{"kind": "pocket", "pocket_rank": 1}, {"kind": "pocket", "pocket_rank": 3},
                                          {"kind": "user"}]
    wire, _ = P.build_mutation_wire(content, [0], ubq["structure"])
    assert wire["pockets"] == {"ranks": [1, 3], "lining_residue_count": 17}
    assert wire["positions"][0]["sources"] == ["pocket", "user"]
    assert list(wire) == list(J.ALLOWED_MUTATION_TOP)
    assert "obj://" not in _text(wire) and "pocket_set" not in _keys(wire) and "pocket_rank" not in _keys(wire)


def test_structure_mismatch_is_structure_unavailable(ubq, mq4):
    assert _reason(P.build_mutation_wire, ubq["content"], [0], mq4["structure"]) == "structure_unavailable"
    content = copy.deepcopy(ubq["content"])   # SYNTHETIC: stored model number differs from the structure's
    content["structure"]["model_number"] = 2
    assert _reason(P.build_mutation_wire, content, [0], ubq["structure"]) == "structure_unavailable"


def test_unsafe_structure_identifiers_are_wire_field_invalid(ubq):
    st = ubq["structure"].clone()   # SYNTHETIC: chain renamed to an identifier the wire refuses
    content = copy.deepcopy(ubq["content"])
    for name in ("A" * 17, "A B", "A.B"):
        st[0][0].name = name
        for position in content["positions"]:
            position["residue"]["chain_auth"] = name
        assert _reason(P.build_mutation_wire, content, [0], st) == "wire_field_invalid", name


def test_mutation_extra_stored_fields_and_unknown_source_kinds(ubq):
    content = copy.deepcopy(ubq["content"])   # SYNTHETIC field changes of the real 1UBQ set
    content["positions"][0]["score"] = 3
    content["positions"][0]["protection"]["reasons"] = ["user_protected"]
    wire, _ = P.build_mutation_wire(content, [0], ubq["structure"])
    assert "score" not in _keys(wire) and "user_protected" not in _text(wire)
    content["positions"][0]["sources"] = [{"kind": "ranked"}]
    assert _reason(P.build_mutation_wire, content, [0], ubq["structure"]) == "wire_field_invalid"
    content = copy.deepcopy(ubq["content"])
    content["protection_checks"]["disulfide"]["status"] = "skipped"
    assert _reason(P.build_mutation_wire, content, [0], ubq["structure"]) == "wire_field_invalid"
    content = copy.deepcopy(ubq["content"])
    content["positions"][0]["protection"]["released"] = 1
    assert _reason(P.build_mutation_wire, content, [0], ubq["structure"]) == "wire_field_invalid"


# ---------------------------------------------------------------- check_wire on tampered wires


@pytest.fixture(scope="module")
def mutation_wire(ubq):
    return P.build_mutation_wire(ubq["content"], _first_candidates(ubq["content"])[:3], ubq["structure"])[0]


@pytest.fixture(scope="module")
def ligand_wire():
    return P.build_ligand_wire(SMALL_POOL, _ids(SMALL_POOL)[:3])[0]


LIGAND_TAMPER = {   # SYNTHETIC wire changes
    "top_unknown": lambda w: w.update(rank=1),
    "top_handle": lambda w: w.update(handle="obj://x"),
    "parent_unknown": lambda w: w["parent"].update(id="c_0"),
    "candidate_unknown": lambda w: w["candidates"][0].update(score=-7.1),
    "candidate_run_id": lambda w: w["candidates"][0].update(run_id="run_x"),
    "candidate_path": lambda w: w["candidates"][0].update(path="a"),
    "pains_unknown": lambda w: w["candidates"][0].update(pains_matches=[{"catalog": "PAINS_A", "name": "x",
                                                                         "handle": "h"}]),
    "missing_values_note": lambda w: w.pop("values_note"),
    "values_note_changed": lambda w: w.update(values_note="RDKit estimates"),
    "schema": lambda w: w.update(schema="jev_mutation_candidates@1"),
    "task": lambda w: w.update(task="rank_candidates"),
    "alias_gap": lambda w: w["candidates"][1].update(alias="c03"),
    "alias_prefix": lambda w: w["candidates"][0].update(alias="m01"),
    "kinds_unsorted": lambda w: w["candidates"][0].update(generation_kinds=["user_rule", "fixed_replace"]),
    "kinds_empty": lambda w: w["candidates"][0].update(generation_kinds=[]),
    "kinds_unknown": lambda w: w["candidates"][0].update(generation_kinds=["fixed"]),
    "smiles_handle": lambda w: w["candidates"][0].update(smiles="obj://run/x"),
    "smiles_home": lambda w: w["candidates"][0].update(smiles="~CC"),
    "property_nan": lambda w: w["candidates"][0]["properties"].update(tpsa=math.nan),
    "property_extra": lambda w: w["candidates"][0]["properties"].update(qed=0.1),
    "methods_extra": lambda w: w["property_methods"].update(qed="x"),
    "no_candidates": lambda w: w.update(candidates=[]),
    "twenty_one": lambda w: w.update(candidates=[{**w["candidates"][0], "alias": f"c{n:02d}"}
                                                 for n in range(1, 22)]),
    "parent_missing_properties": lambda w: w["parent"].pop("properties"),
}


@pytest.mark.parametrize("name", sorted(LIGAND_TAMPER))
def test_check_wire_refuses_tampered_ligand_wires(name, ligand_wire):
    wire = copy.deepcopy(ligand_wire)
    P.check_wire(wire, "ligand")
    LIGAND_TAMPER[name](wire)
    with pytest.raises(P.WireFieldInvalid):
        P.check_wire(wire, "ligand")


MUTATION_TAMPER = {   # SYNTHETIC wire changes
    "top_unknown": lambda w: w.update(scores=[]),
    "position_unknown": lambda w: w["positions"][0].update(numbering={"uniprot_accession": "P00000"}),
    "position_reasons": lambda w: w["positions"][0].update(protection_reasons=["user_protected"]),
    "residue_unknown": lambda w: w["positions"][0]["residue"].update(path="x"),
    "residue_missing": lambda w: w["positions"][0]["residue"].pop("chain_label"),
    "residue_chain_space": lambda w: w["positions"][0]["residue"].update(chain_auth="A B"),
    "residue_chain_long": lambda w: w["positions"][0]["residue"].update(chain_auth="A" * 17),
    "residue_resname_empty": lambda w: w["positions"][0]["residue"].update(resname=""),
    "residue_seq_float": lambda w: w["positions"][0]["residue"].update(seq_auth=1.0),
    "residue_seq_bool": lambda w: w["positions"][0]["residue"].update(seq_auth=True),
    "residue_label_handle": lambda w: w["positions"][0]["residue"].update(chain_label="obj://x"),
    "window_unknown": lambda w: w["positions"][0]["window"].update(members=[]),
    "window_letters": lambda w: w["positions"][0]["window"].update(residues="MQ-IF"),
    "neighbor_unknown": lambda w: w["positions"][0]["neighbors"][0].update(distance_A=3.2),
    "neighbor_resname_bad": lambda w: w["positions"][0]["neighbors"][0].update(resname="A+B"),
    "distance_nan": lambda w: w["positions"][0].update(ligand_min_distance_A=math.nan),
    "distance_inf": lambda w: w["positions"][0].update(ligand_min_distance_A=math.inf),
    "distance_negative": lambda w: w["positions"][0].update(ligand_min_distance_A=-1.0),
    "released_int": lambda w: w["positions"][0].update(protection_released=0),
    "sources_order": lambda w: w["positions"][0].update(sources=["user", "pocket"]),
    "sources_unknown": lambda w: w["positions"][0].update(sources=["ranked"]),
    "sources_empty": lambda w: w["positions"][0].update(sources=[]),
    "one_letter_bad": lambda w: w["positions"][0].update(one_letter="X"),
    "candidate_unknown": lambda w: w["candidates"][0].update(predicted_ddg=1.2),
    "candidate_to_equals_from": lambda w: w["candidates"][0].update(to=w["candidates"][0]["from"]),
    "candidate_from_mismatch": lambda w: w["candidates"][0].update(
        **{"from": "W" if w["candidates"][0]["from"] != "W" else "A"}),
    "candidate_pos_unknown": lambda w: w["candidates"][0].update(pos="p99"),
    "candidate_alias_prefix": lambda w: w["candidates"][0].update(alias="c01"),
    "checks_count": lambda w: w["protection_checks"].update(user_list={"status": "checked", "protected": 0}),
    "checks_missing": lambda w: w["protection_checks"].pop("disulfide"),
    "checks_status": lambda w: w["protection_checks"].update(disulfide="none"),
    "pockets_handle": lambda w: w.update(pockets={"ranks": [1], "lining_residue_count": 3,
                                                  "pocket_set": "obj://x"}),
    "pockets_ranks": lambda w: w.update(pockets={"ranks": [], "lining_residue_count": 3}),
    "unused_position": lambda w: w["positions"].append({**copy.deepcopy(w["positions"][0]), "pos": "p04"}),
    "positions_out_of_order": lambda w: _swap_first_use(w),
}


def _swap_first_use(wire: dict) -> None:
    """SYNTHETIC: m01 uses p02 and m02 uses p01 (codes kept consistent), so only the first-use order rule fails."""
    first, second = wire["candidates"][0], wire["candidates"][1]
    letters = {p["pos"]: p["one_letter"] for p in wire["positions"]}
    first["pos"], second["pos"] = second["pos"], first["pos"]
    for candidate in (first, second):
        candidate["from"] = letters[candidate["pos"]]
        if candidate["to"] == candidate["from"]:
            candidate["to"] = next(code for code in J.ONE_LETTER_CODES if code != candidate["from"])


@pytest.mark.parametrize("name", sorted(MUTATION_TAMPER))
def test_check_wire_refuses_tampered_mutation_wires(name, mutation_wire):
    wire = copy.deepcopy(mutation_wire)
    P.check_wire(wire, "mutation")
    assert len(wire["positions"]) == 3 and wire["positions"][0]["neighbors"]
    MUTATION_TAMPER[name](wire)
    with pytest.raises(P.WireFieldInvalid):
        P.check_wire(wire, "mutation")


def test_check_wire_keeps_null_and_empty_identifiers(mutation_wire):
    wire = copy.deepcopy(mutation_wire)   # SYNTHETIC: null labels / empty icode are stored values, kept as such
    wire["positions"][0]["residue"].update(chain_label=None, seq_label=None, icode="")
    wire["positions"][0]["window"] = None
    wire["positions"][0]["neighbors"] = None
    wire["positions"][0]["ligand_min_distance_A"] = None
    P.check_wire(wire, "mutation")
    wire["positions"][1]["residue"].update(chain_auth=None, icode=None)   # spec 3: null identifiers go as null
    wire["positions"][1]["window"] = None
    P.check_wire(wire, "mutation")
    wire["positions"][1]["window"] = {"chain_auth": "A", "first_seq_auth": 1, "residues": "M", "contiguous": True}
    with pytest.raises(P.WireFieldInvalid):   # a window needs the target's chain
        P.check_wire(wire, "mutation")
    wire["positions"][1]["window"] = None
    wire["positions"][1]["residue"]["resname"] = None
    with pytest.raises(P.WireFieldInvalid):   # a residue name is never empty or null
        P.check_wire(wire, "mutation")
    with pytest.raises(ValueError):
        P.check_wire(wire, "protein")


# ---------------------------------------------------------------- body encoding


def test_body_encoding_is_deterministic_ascii_and_spec_shaped(ligand_wire):
    aliases = ["c01", "c02", "c03"]
    body = P.encode_body(ligand_wire, J.LIGAND_QUESTION_ID, aliases)
    reordered = json.loads(json.dumps(ligand_wire, sort_keys=True))
    reordered = dict(reversed(list(reordered.items())))
    assert P.encode_body(reordered, J.LIGAND_QUESTION_ID, aliases) == body
    assert P.encode_body(ligand_wire, J.LIGAND_QUESTION_ID, aliases) == body and body.isascii()
    decoded = json.loads(body)
    assert set(decoded) == set(J.ALLOWED_BODY_KEYS)
    assert decoded["model"] == J.REQUEST_MODEL and decoded["provider"] == J.PROVIDER
    assert decoded["state"] == ligand_wire
    assert decoded["questions"] == {"candidate_choice": {
        "type": "choice", "instructions": J.INSTRUCTIONS[J.LIGAND_QUESTION_ID],
        "criteria": {"c01": "Candidate c01.", "c02": "Candidate c02.", "c03": "Candidate c03."}}}
    assert body == json.dumps(decoded, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    assert P.body_sha256(body) == hashlib.sha256(body).hexdigest()
    assert P.body_object(ligand_wire, J.LIGAND_QUESTION_ID, aliases) == decoded
    assert P.canonical_ascii(decoded) == body
    with pytest.raises(KeyError):
        P.encode_body(ligand_wire, "inspection_view@1", aliases)


def test_body_object_does_not_share_the_provider_constant(ligand_wire):
    body = P.body_object(ligand_wire, J.LIGAND_QUESTION_ID, ["c01"])
    body["provider"]["zdr"] = False
    assert J.PROVIDER["zdr"] is True


def test_body_size_boundary_64_kib():
    exact = _tuned_ligand_set(J.MAX_BODY_BYTES)
    wire, selection = P.build_ligand_wire(exact, _ids(exact))
    content = P.build_projection_content("ligand", SET_HANDLE["ligand"], wire, selection)
    assert content["body_bytes"] == J.MAX_BODY_BYTES == 65_536
    over = copy.deepcopy(exact)
    last = over["candidates"][-1]
    assert len(last["smiles"]) < 1024
    last["smiles"] += "C"   # SYNTHETIC: one more body byte, still a 1-1024 character SMILES-shaped string
    last["id"] = "c_" + hashlib.sha256(last["smiles"].encode()).hexdigest()[:16]
    wire, selection = P.build_ligand_wire(over, _ids(over))
    with pytest.raises(P.PayloadTooLarge) as caught:
        P.build_projection_content("ligand", SET_HANDLE["ligand"], wire, selection)
    assert caught.value.reason_code == "payload_too_large"
    assert caught.value.detail == {"reason_code": "payload_too_large", "body_bytes": 65_537, "limit": 65_536}


def test_twenty_candidates_fit_and_twenty_one_never_reach_the_wire():
    content = synthetic_ligand_set([60 + i for i in range(21)])   # SYNTHETIC rows
    wire, selection = P.build_ligand_wire(content, _ids(content)[:20])
    projection = P.build_projection_content("ligand", SET_HANDLE["ligand"], wire, selection)
    assert len(projection["selection"]) == len(projection["wire"]["candidates"]) == 20
    assert _reason(P.build_ligand_wire, content, _ids(content)) == "selection_invalid"


# ---------------------------------------------------------------- projection content and validated_projection


def _ligand_projection(**kw) -> dict:
    wire, selection = P.build_ligand_wire(SMALL_POOL, _ids(SMALL_POOL)[:4])
    return P.build_projection_content("ligand", SET_HANDLE["ligand"], wire, selection, **kw)


@pytest.fixture(scope="module")
def mutation_projection(ubq):
    wire, selection = P.build_mutation_wire(ubq["content"], _first_candidates(ubq["content"]), ubq["structure"])
    return P.build_projection_content("mutation", SET_HANDLE["mutation"], wire, selection, structure=STRUCTURE_REF)


def test_ligand_projection_content():
    content = _ligand_projection()
    assert list(content) == list(J.PROJECTION_KEYS)
    assert (content["schema"], content["method_version"], content["kind"]) == (
        "jev_projection@1", "mw.jev_projection/v1", "ligand")
    assert content["source"] == {"handle": SET_HANDLE["ligand"], "schema": "ligand_candidate_set@1"}
    assert content["structure"] is None and content["filter"] is None
    assert content["question"] == {"id": "ligand_candidate_choice@1", "key": "candidate_choice"}
    body = P.encode_body(content["wire"], J.LIGAND_QUESTION_ID, [s["alias"] for s in content["selection"]])
    assert content["body_sha256"] == hashlib.sha256(body).hexdigest() and content["body_bytes"] == len(body)
    assert content["wire_sha256"] == hashlib.sha256(
        json.dumps(content["wire"], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert content["limitations"] == J.limitations_for("ligand", False)
    assert P.projection_body(content) == (json.loads(body), body)
    assert P.validated_projection(content) is content
    assert _ligand_projection() == content   # same input, same content (no time, no call id)
    for word in ("time", "created", "call_id", "seq", "uuid"):
        assert word not in _keys(content)
    stored = json.loads(json.dumps(content, sort_keys=True))   # a store round trip still validates
    assert P.validated_projection(stored) == content


def test_mutation_projection_content(mutation_projection):
    content = mutation_projection
    assert content["kind"] == "mutation" and content["structure"] == STRUCTURE_REF and content["filter"] is None
    assert content["question"] == {"id": "mutation_candidate_choice@1", "key": "candidate_choice"}
    assert content["limitations"] == J.limitations_for("mutation", False)
    assert content["source"]["schema"] == "mutation_candidate_set@1"
    P.validated_projection(json.loads(json.dumps(content, sort_keys=True)))


def test_projection_with_a_normalized_ligand_filter():
    spec = ligand_filters.normalize_filter_spec({"ranges": {"mol_weight": {"max": 600}, "hbd": {"min": 1}},
                                                 "pains_exclude": True})
    content = _ligand_projection(filter_spec=spec)
    assert content["filter"] == spec
    for raw in ({"ranges": {"mol_weight": {"max": 600}}}, {"pains_exclude": True},
                {"ranges": {"mol_weight": {"min": None, "max": None}}, "pains_exclude": False},
                {"ranges": {"qed": {"min": 0, "max": 1}}, "pains_exclude": False},
                {"ranges": {"tpsa": {"min": 5, "max": 1}}, "pains_exclude": False},
                {"ranges": {"tpsa": {"min": math.nan, "max": None}}, "pains_exclude": False},
                {"ranges": {}, "pains_exclude": 0}, []):
        with pytest.raises(P.ProjectionInvalid):
            _ligand_projection(filter_spec=raw)
    assert _ligand_projection(filter_spec={"ranges": {}, "pains_exclude": False})["filter"] == \
        ligand_filters.normalize_filter_spec({})


def _rehash(content: dict) -> dict:
    """Recompute the hashes so that only the tampered rule fails (uses the module encoder on purpose)."""
    aliases = [s["alias"] for s in content["selection"]]
    body = P.encode_body(content["wire"], content["question"]["id"], aliases)
    content["wire_sha256"] = hashlib.sha256(P.canonical_ascii(content["wire"])).hexdigest()
    content["body_sha256"], content["body_bytes"] = hashlib.sha256(body).hexdigest(), len(body)
    return content


PROJECTION_TAMPER = {   # SYNTHETIC tampering of a valid stored projection
    "rank_field": lambda c: c.update(rank=[1, 2]),
    "score_in_wire": lambda c: c["wire"]["candidates"][0].update(score=1.0),
    "best_in_selection": lambda c: c["selection"][0].update(best=True),
    "schema": lambda c: c.update(schema="jev_projection@2"),
    "method_version": lambda c: c.update(method_version="mw.jev_projection/v2"),
    "kind": lambda c: c.update(kind="protein"),
    "kind_mutation_for_ligand_wire": lambda c: c.update(kind="mutation"),
    "question_id": lambda c: c["question"].update(id="mutation_candidate_choice@1"),
    "question_key": lambda c: c["question"].update(key="inspection_view"),
    "source_schema": lambda c: c["source"].update(schema="mutation_candidate_set@1"),
    "source_handle": lambda c: c["source"].update(handle="/Users/me/set.json"),
    "structure_on_ligand": lambda c: c.update(structure=STRUCTURE_REF),
    "alias_mismatch": lambda c: c["selection"].reverse(),
    "selection_alias_renamed": lambda c: c["selection"][0].update(alias="c09"),
    "selection_bad_id": lambda c: c["selection"][0].update(candidate_id="obj://x"),
    "selection_duplicate_id": lambda c: c["selection"][1].update(candidate_id=c["selection"][0]["candidate_id"]),
    "limitations_with_j7": lambda c: c["limitations"].append(J.J7),
    "limitations_mutation": lambda c: c.update(limitations=J.limitations_for("mutation", False)),
    "wire_handle_key": lambda c: c["wire"]["parent"].update(handle="obj://x"),
    "wire_obj_string": lambda c: c["wire"]["candidates"][0].update(smiles="obj://run_x/a"),
    "wire_nan": lambda c: c["wire"]["candidates"][0]["properties"].update(tpsa=math.nan),
}
HASH_TAMPER = {
    "wire_sha256": lambda c: c.update(wire_sha256="0" * 64),
    "body_sha256": lambda c: c.update(body_sha256="0" * 64),
    "body_bytes": lambda c: c.update(body_bytes=c["body_bytes"] + 1),
    "body_bytes_bool": lambda c: c.update(body_bytes=True),
    "wire_changed_without_rehash": lambda c: c["wire"]["candidates"][0]["properties"].update(tpsa=1.5),
}


@pytest.mark.parametrize("name", sorted(PROJECTION_TAMPER))
def test_validated_projection_refuses_tampering(name):
    content = copy.deepcopy(_ligand_projection())
    PROJECTION_TAMPER[name](content)
    if name not in ("wire_nan",):
        _rehash(content)
    with pytest.raises(P.ProjectionInvalid) as caught:
        P.validated_projection(content)
    assert caught.value.reason_code == "projection_invalid"


@pytest.mark.parametrize("name", sorted(HASH_TAMPER))
def test_validated_projection_recomputes_hashes_and_length(name):
    content = copy.deepcopy(_ligand_projection())
    HASH_TAMPER[name](content)
    with pytest.raises(P.ProjectionInvalid):
        P.validated_projection(content)


def test_validated_projection_count_and_kind_rules(mutation_projection):
    content = copy.deepcopy(_ligand_projection())   # SYNTHETIC: 21 candidates with consistent hashes
    template = content["wire"]["candidates"][0]
    content["wire"]["candidates"] = [{**template, "alias": f"c{n:02d}"} for n in range(1, 22)]
    content["selection"] = [{"alias": f"c{n:02d}", "candidate_id": "c_" + f"{n:016x}"} for n in range(1, 22)]
    with pytest.raises(P.ProjectionInvalid):
        P.validated_projection(_rehash(content))
    content = copy.deepcopy(mutation_projection)
    for change in (lambda c: c.update(structure=None), lambda c: c.update(structure={"handle": "x"}),
                   lambda c: c.update(filter={"ranges": {}, "pains_exclude": False}),
                   lambda c: c["selection"][1].update(position_index=c["selection"][0]["position_index"]),
                   lambda c: c["selection"][0].update(position_index=-1),
                   lambda c: c["selection"].__setitem__(1, {**c["selection"][1],
                                                            "candidate_index": c["selection"][0]["candidate_index"]}),
                   lambda c: c["selection"][0].pop("position_index")):
        tampered = copy.deepcopy(content)
        change(tampered)
        with pytest.raises(P.ProjectionInvalid):
            P.validated_projection(_rehash(tampered))
    for not_a_dict in (None, [], "jev_projection@1"):
        with pytest.raises(P.ProjectionInvalid):
            P.validated_projection(not_a_dict)
    wire, selection = copy.deepcopy(content["wire"]), copy.deepcopy(content["selection"])
    for structure in ("obj://x", ["handle", 1], {"handle": STRUCTURE_REF["handle"]}):
        with pytest.raises(P.ProjectionInvalid):
            P.build_projection_content("mutation", SET_HANDLE["mutation"], wire, selection, structure=structure)


def test_error_classes():
    error = P.WireFieldInvalid("smiles not allowed", field="candidates[0].smiles")
    assert isinstance(error, P.JevProjectionError) and error.reason_code == "wire_field_invalid"
    assert error.detail == {"reason_code": "wire_field_invalid", "field": "candidates[0].smiles"}
    assert P.ProjectionInvalid("x").reason_code == "projection_invalid"
    assert P.PayloadTooLarge("x", body_bytes=2, limit=1).detail == {"reason_code": "payload_too_large",
                                                                    "body_bytes": 2, "limit": 1}
    assert P.JevProjectionError("structure_unavailable", "x").detail == {"reason_code": "structure_unavailable"}


# ---------------------------------------------------------------- parse_choice


ALIASES = ["c01", "c02", "c03"]
_DEFAULT = object()


def _response(answer=_DEFAULT, **top) -> dict:
    answer = {"type": "choice", "choice": "c02"} if answer is _DEFAULT else answer
    return {"model": J.SERVED_SNAPSHOT, "answers": {"candidate_choice": answer},
            "usage": {"input_tokens": 10, "output_tokens": 2, "cost": 0.001}, **top}


def test_parse_choice_accepts_choice_alone_and_with_confidence_and_probabilities():
    assert P.parse_choice(_response(), ALIASES) == (
        {"choice_alias": "c02", "confidence": None, "probabilities": None}, None)
    probabilities = {"c03": 0.25, "c01": 0.05, "c02": 0.7}
    answer = {"type": "choice", "choice": "c02", "confidence": 0.7, "probabilities": probabilities}
    parsed, reason = P.parse_choice(_response(answer), ALIASES)
    assert reason is None and parsed == {"choice_alias": "c02", "confidence": 0.7, "probabilities": probabilities}
    assert list(parsed["probabilities"]) == ["c03", "c01", "c02"]   # received order, no sorting
    assert parsed["probabilities"] is not probabilities
    for edge in (0, 1, 0.0, 1.0):
        assert P.parse_choice(_response({"type": "choice", "choice": "c01", "confidence": edge}), ALIASES)[1] is None
    assert P.parse_choice(_response({"type": "choice", "choice": "c01", "probabilities": {"c01": 1}}),
                          ALIASES)[0]["probabilities"] == {"c01": 1}


@pytest.mark.parametrize("answer", [
    {"type": "choice", "choice": "c04"}, {"type": "choice", "choice": 1}, {"type": "choice", "choice": None},
    {"type": "choice"}, {"type": "rank", "choice": "c01"}, {"choice": "c01"},
    {"type": "choice", "choice": "c01", "reason": "most promising"},
    {"type": "choice", "choice": "c01", "confidence": 1.0000001}, {"type": "choice", "choice": "c01", "confidence": -0.1},
    {"type": "choice", "choice": "c01", "confidence": math.nan}, {"type": "choice", "choice": "c01", "confidence": True},
    {"type": "choice", "choice": "c01", "confidence": "0.5"}, {"type": "choice", "choice": "c01", "confidence": None},
    {"type": "choice", "choice": "c01", "confidence": 2}, {"type": "choice", "choice": "c01", "confidence": 10**400},
    {"type": "choice", "choice": "c01", "probabilities": {"c01": -1}},
    {"type": "choice", "choice": "c01", "probabilities": {"c09": 0.5}},
    {"type": "choice", "choice": "c01", "probabilities": {"c01": 1.5}},
    {"type": "choice", "choice": "c01", "probabilities": {"c01": math.nan}},
    {"type": "choice", "choice": "c01", "probabilities": {"c01": math.inf}},
    {"type": "choice", "choice": "c01", "probabilities": {"c01": False}},
    {"type": "choice", "choice": "c01", "probabilities": [0.5, 0.5]},
    {"type": "choice", "choice": "c01", "probabilities": None},
    {"type": "choice", "choice": "c01", "probabilities": {"c01": 0.2, "c02": 0.2, "c03": 0.2, "c04": 0.4}},
    "c01", None, ["c01"]])
def test_parse_choice_response_invalid(answer):
    assert P.parse_choice(_response(answer), ALIASES) == (None, "response_invalid")


def test_parse_choice_model_and_answers_rules():
    assert P.parse_choice({"answers": _response()["answers"]}, ALIASES) == (None, "missing_model")
    assert P.parse_choice({**_response(), "model": None}, ALIASES) == (None, "missing_model")
    assert P.parse_choice({"model": None, "answers": "broken"}, ALIASES) == (None, "missing_model")
    for model in (J.REQUEST_MODEL, "typesafe/jev-1.14-20261001", 5, ""):
        assert P.parse_choice({**_response(), "model": model}, ALIASES) == (None, "model_mismatch"), model
    other = _response()
    other["answers"]["inspection_view"] = {"type": "choice", "choice": "summary"}
    assert P.parse_choice(other, ALIASES) == (None, "response_invalid")
    assert P.parse_choice({"model": J.SERVED_SNAPSHOT}, ALIASES) == (None, "response_invalid")
    assert P.parse_choice({"model": J.SERVED_SNAPSHOT, "answers": []}, ALIASES) == (None, "response_invalid")
    assert P.parse_choice({"model": J.SERVED_SNAPSHOT, "answers": {}}, ALIASES) == (None, "response_invalid")
    for data in (None, [], "x", 1):
        assert P.parse_choice(data, ALIASES) == (None, "response_invalid")
    # top-level extras of the provider response (id, usage, created) are not answer keys
    assert P.parse_choice(_response(id="r1", created=1), ALIASES)[1] is None
