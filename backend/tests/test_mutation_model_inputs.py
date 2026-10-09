"""M21 T2 pure modules (``mw.mutation_model_constants``, ``mw.mutation_model_inputs``, ``mw.mutation_model_math``).

Oracles: the SYNTHETIC hand-derived contact example in ``fixtures/mutation_model/expected.json`` (closed-form values
written by ``build_mutation_model_fixtures.py`` without engine or implementation calls; cross-checked in
docs/qa/m21-mutations-20261004/preflight.txt (f)), the spec 4 limitation sentences copied here verbatim, and
SYNTHETIC ``mutation_model@1`` contents built here by hand (function names contain ``synthetic``; expected comparison
values are written out, not derived with the module). Admission uses the public 1UBQ structure (public structure, not
experimentally validated here) through the product path ``load_structure`` -> ``prepare_structure`` ->
``generate_mutation_candidates`` so the candidate set is a real stored M20 result.
"""
from __future__ import annotations

import ast
import copy
import json
import math
import subprocess
import sys
from pathlib import Path

import m20_v2_fixture as V2
import pytest

from mw import mutation_model_constants as K
from mw import mutation_model_inputs as mi
from mw import mutation_model_math as mm
from mw.core.errors import FailureClass, ToolFailure
from mw.openmm_bundle import FORCEFIELD_SHA256
from mw.tools.structural import structure_residues
from mw.workspace import build_registry, new_run

FIX = Path(__file__).resolve().parent / "fixtures"
ORACLE = json.loads((FIX / "mutation_model" / "expected.json").read_text())["contacts"]
REPO = Path(__file__).resolve().parents[2]

# spec 4, copied verbatim (not imported) so a drift in the constants module fails.
SPEC_L1 = "변이 구조는 PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 모델이며 회전이성질체 탐색과 수렴을 주장하지 않는다."
SPEC_L2 = ("OpenMM 전위는 각 구조의 Amber14-all + GBn2 암시 용매 값(kJ/mol)이며 서열이 다른 두 구조의 값은 서로 비교할 수 "
           "없고 ΔΔG·안정성·친화도가 아니다.")
SPEC_L3 = "모델은 단백질만 포함하며 리간드·금속 이온·물·보조인자는 제외했다."
SPEC_L4 = "SASA는 리간드가 없는 단백질 모델의 변이 위치 잔기 값이다."
SPEC_L5 = ("변이한 잔기 밖에서 히스티딘·시스테인 양성자 상태가 두 구조에서 다르게 지정되었으므로 두 구조의 차이는 변이 "
           "하나만이 아니다.")
SPEC_L6 = "변이형에는 야생형 기준에 없는 이황화 결합이 거리 기준으로 만들어졌다."
SPEC_L7 = "접촉은 중원자 사이 거리(Å)이며 수소결합이나 상호작용의 종류를 뜻하지 않는다."
I44 = {"model_number": 1, "chain_auth": "A", "seq_auth": 44, "icode": "", "resname": "ILE"}


def _rejected(reason_code, fn, *args, cls=FailureClass.input_invalid, **kwargs):
    with pytest.raises(ToolFailure) as caught:
        fn(*args, **kwargs)
    assert caught.value.cls is cls
    assert caught.value.detail["reason_code"] == reason_code, caught.value.detail
    return caught.value


# --- constants -------------------------------------------------------------------------------------------------------

def test_limitation_sentences_are_verbatim_and_in_fixed_order():
    assert (K.L1, K.L2, K.L3, K.L4, K.L5, K.L6, K.L7) == (SPEC_L1, SPEC_L2, SPEC_L3, SPEC_L4, SPEC_L5, SPEC_L6,
                                                          SPEC_L7)
    assert K.LIMITATION_ORDER == (SPEC_L1, SPEC_L2, SPEC_L3, SPEC_L4, SPEC_L7, SPEC_L5, SPEC_L6)
    base = (SPEC_L1, SPEC_L2, SPEC_L3, SPEC_L4, SPEC_L7)
    assert K.applicable_limitations(protonation_difference_count=0, new_disulfide_in_mutant=False) == base
    assert K.applicable_limitations(protonation_difference_count=2, new_disulfide_in_mutant=False) == (*base, SPEC_L5)
    assert K.applicable_limitations(protonation_difference_count=0, new_disulfide_in_mutant=True) == (*base, SPEC_L6)
    assert K.applicable_limitations(protonation_difference_count=1, new_disulfide_in_mutant=True) == (
        *base, SPEC_L5, SPEC_L6)
    for bad in ({"protonation_difference_count": -1, "new_disulfide_in_mutant": False},
                {"protonation_difference_count": True, "new_disulfide_in_mutant": False},
                {"protonation_difference_count": 0, "new_disulfide_in_mutant": 0}):
        with pytest.raises(ValueError):
            K.applicable_limitations(**bad)


def test_closed_sets_ranges_and_defaults_match_the_spec():
    assert K.PROTOCOL == "openmm_mutation_model_v1" and K.TOOL == "openmm_mutation_model"
    assert K.SCHEMA == "mutation_model@1" and K.METHOD_VERSION == "mw.mutation_model/v1"
    assert K.ARG_KEYS == ("candidate_set", "candidate_index", "seed", "selection_policy", "hydrogen_policy",
                          "contact_cutoff_A")
    assert K.ADMISSION_REASON_CODES == ("unknown_field", "confirmation_missing", "argument_invalid",
                                        "candidate_set_invalid", "candidate_unknown", "structure_invalid",
                                        "residue_mismatch", "openmm_preflight_failed")
    assert K.UNAVAILABLE_REASON_CODES == ("openmm_unavailable", "pdbfixer_unavailable", "process_identity_unavailable")
    assert K.FAILURE_REASON_CODES == ("mutation_modeling_failed", "unexpected_atoms_added", "coordinates_changed",
                                      "topology_unsupported", "energy_invalid", "engine_failed", "resource_exceeded")
    assert K.CONTACT_CUTOFF_DEFAULT_A == 4.0 and K.CONTACT_CUTOFF_RANGE_A == (2.5, 6.0)
    assert (K.TIMEOUT_DEFAULT_S, K.TIMEOUT_MAX_S) == (120, 240)
    assert K.MAX_CONTACT_ROWS == 2000 and K.EXCLUDED_BOND_DISTANCE == 3
    assert K.PDBFIXER_VERSION == "1.12.0" and K.OPENMM_VERSION == "8.6.0"
    assert K.STRUCTURE_SIDES == ("wild_type_reference", "mutant")
    assert sorted(K.THREE_LETTER) == list("ACDEFGHIKLMNPQRSTVWY")


def test_new_modules_import_no_engine_or_heavy_chemistry_package():
    allowed = {"__future__", "math", "typing", "collections.abc", "hashlib", "numpy", "core.errors",
               "core.handles", "mutation_candidates", "mutation_constants", "mutation_model_constants",
               "openmm_bundle"}
    for module in ("mutation_model_constants.py", "mutation_model_inputs.py", "mutation_model_math.py"):
        tree = ast.parse((REPO / "backend" / "mw" / module).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) or (isinstance(node, ast.ImportFrom) and node.module is None):
                assert {alias.name for alias in node.names} <= allowed, module   # import x / from . import x
            elif isinstance(node, ast.ImportFrom):
                assert node.module in allowed, (module, node.module)
    constants = ast.parse((REPO / "backend" / "mw" / "mutation_model_constants.py").read_text())
    assert [n.module for n in ast.walk(constants) if isinstance(n, (ast.Import, ast.ImportFrom))] == ["__future__"]
    code = ("import sys, mw.mutation_model_constants, mw.mutation_model_inputs, mw.mutation_model_math; "
            "print(sorted(m for m in ('openmm', 'pdbfixer', 'rdkit', 'meeko', 'MDAnalysis', 'prolif', 'freesasa') "
            "if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO / "backend", capture_output=True, text=True,
                         check=True)
    assert out.stdout.strip() == "[]"


# --- request arguments -----------------------------------------------------------------------------------------------

def _args(**kw):
    args = {"candidate_set": "obj://run/mutation_candidate_set/aa", "candidate_index": 0, "seed": 20261004,
            "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}
    args.update(kw)
    return {k: v for k, v in args.items() if v is not _DROP}


_DROP = object()


def test_normalized_arguments_fill_the_default_cutoff_and_keep_exact_values():
    assert mi.normalize_arguments(_args()) == {
        "candidate_set": "obj://run/mutation_candidate_set/aa", "candidate_index": 0, "seed": 20261004,
        "contact_cutoff_A": 4.0, "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7"}
    for value, expected in ((2.5, 2.5), (6.0, 6.0), (3, 3.0), (-0.0 + 4, 4.0)):
        out = mi.normalize_arguments(_args(contact_cutoff_A=value))["contact_cutoff_A"]
        assert out == expected and type(out) is float
    assert mi.normalize_arguments(_args(seed=0, candidate_index=7))["seed"] == 0
    assert mi.normalize_arguments(_args(seed=2147483647))["seed"] == 2147483647


@pytest.mark.parametrize("args, reason", [
    ({"bogus": 1}, "unknown_field"),
    ({"bogus": 1, "selection_policy": "all"}, "unknown_field"),
    ({"selection_policy": "all"}, "confirmation_missing"),
    ({"hydrogen_policy": _DROP}, "confirmation_missing"),
    ({"selection_policy": None}, "confirmation_missing"),
    ({"hydrogen_policy": "rebuild_pH7 "}, "confirmation_missing"),
    ({"selection_policy": "all", "seed": "x"}, "confirmation_missing"),
    ({"seed": _DROP}, "argument_invalid"),
    ({"seed": True}, "argument_invalid"),
    ({"seed": 1.0}, "argument_invalid"),
    ({"seed": -1}, "argument_invalid"),
    ({"seed": 2147483648}, "argument_invalid"),
    ({"candidate_index": _DROP}, "argument_invalid"),
    ({"candidate_index": False}, "argument_invalid"),
    ({"candidate_index": -1}, "argument_invalid"),
    ({"candidate_index": "0"}, "argument_invalid"),
    ({"contact_cutoff_A": float("nan")}, "argument_invalid"),
    ({"contact_cutoff_A": float("inf")}, "argument_invalid"),
    ({"contact_cutoff_A": True}, "argument_invalid"),
    ({"contact_cutoff_A": None}, "argument_invalid"),
    ({"contact_cutoff_A": "4"}, "argument_invalid"),
    ({"contact_cutoff_A": 2.4999999}, "argument_invalid"),
    ({"contact_cutoff_A": 6.0000001}, "argument_invalid"),
    ({"contact_cutoff_A": 7.0, "candidate_set": 5}, "argument_invalid"),
    ({"candidate_set": _DROP}, "candidate_set_invalid"),
    ({"candidate_set": ""}, "candidate_set_invalid"),
    ({"candidate_set": ["obj://x"]}, "candidate_set_invalid"),
])
def test_argument_refusals_follow_the_spec_order(args, reason):
    _rejected(reason, mi.normalize_arguments, _args(**args))


def test_non_object_arguments_are_refused():
    _rejected("argument_invalid", mi.normalize_arguments, [1, 2])


def test_timeout_is_a_job_field_with_default_120_and_max_240():
    assert mi.normalize_timeout(None) == 120.0
    assert mi.normalize_timeout(240) == 240.0 and mi.normalize_timeout(0.5) == 0.5
    for bad in (0, -1, 240.0001, float("nan"), float("inf"), True, "60"):
        _rejected("argument_invalid", mi.normalize_timeout, bad)


# --- admission against a real stored M20 candidate set -----------------------------------------------------------------

class Ubq:
    """Public 1UBQ through the product path, with an M20 candidate set for I44 (19 candidates)."""

    def __init__(self, tmp_path: Path) -> None:
        self.run = new_run(tmp_path / "runs", run_id="run_m21", registry=build_registry())
        loaded = self.run.call("load_structure", {"source": str(FIX / "public_1ubq.cif"), "model_index": 0}).handle
        self.structure = self.run.call("prepare_structure", {"structure": loaded}).handle
        self.loaded = loaded
        self.candidate_set = self._set([I44])
        self.empty_set = self._set([I44], allowed_residues="I")

    def _set(self, residues, **kw):
        args = {"structure": self.structure, "sources": {"pocket": None, "ligand_shell": None,
                                                         "residues": residues}, **kw}
        return self.run.call("generate_mutation_candidates", args).handle

    def meta(self, handle):
        try:
            return self.run.store.meta(handle)
        except (KeyError, ValueError, TypeError):
            return None

    def residues(self, handle):
        return structure_residues(self.run.store, handle)["residues"]

    def admit(self, args, *, meta=None, load=None, residues=None):
        return mi.admit(args, meta=meta or self.meta, load=load or self.run.store.load,
                        residues=residues or self.residues)


@pytest.fixture(scope="module")
def ubq(tmp_path_factory):
    return Ubq(tmp_path_factory.mktemp("m21_admission"))


def test_admission_selects_the_candidate_by_index_and_resolves_the_residue(ubq):
    content = ubq.run.store.load(ubq.candidate_set)
    assert [c["to"] for c in content["candidates"]] == list("ACDEFGHKLMNPQRSTVWY")
    admitted = ubq.admit(_args(candidate_set=ubq.candidate_set, candidate_index=18, contact_cutoff_A=6))
    assert admitted["arguments"]["contact_cutoff_A"] == 6.0 and admitted["arguments"]["candidate_index"] == 18
    assert admitted["candidate"] == {"index": 18, "position_index": 0, "from": "I", "to": "Y"}
    assert admitted["structure"] == ubq.structure and admitted["model_number"] == 1
    assert admitted["residue"] == {"model_number": 1, "chain_auth": "A", "chain_label": "A", "seq_auth": 44,
                                   "seq_label": 44, "icode": "", "resname": "ILE"}
    assert admitted["mutant_resname"] == "TYR"
    assert admitted["candidate_set_content"] == content


def test_candidate_set_refusals(ubq):
    _rejected("candidate_set_invalid", ubq.admit, _args(candidate_set="obj://other/mutation_candidate_set/00"))
    _rejected("candidate_set_invalid", ubq.admit, _args(candidate_set=ubq.structure))   # wrong kind
    _rejected("candidate_set_invalid", ubq.admit, _args(candidate_set=ubq.candidate_set),
              meta=lambda handle: None)                                                   # other run / unpublished

    def tampered(handle):
        content = copy.deepcopy(ubq.run.store.load(handle))
        content["candidates"][0]["to"] = "Z"
        return content

    _rejected("candidate_set_invalid", ubq.admit, _args(candidate_set=ubq.candidate_set), load=tampered)


def test_candidate_unknown_includes_the_zero_candidate_set(ubq):
    _rejected("candidate_unknown", ubq.admit, _args(candidate_set=ubq.candidate_set, candidate_index=19))
    assert ubq.run.store.load(ubq.empty_set)["candidates"] == []
    _rejected("candidate_unknown", ubq.admit, _args(candidate_set=ubq.empty_set, candidate_index=0))


def test_structure_invalid_when_the_set_structure_is_not_a_prepared_structure_of_this_run(ubq):
    def meta(handle):
        return None if handle == ubq.structure else ubq.meta(handle)

    _rejected("structure_invalid", ubq.admit, _args(candidate_set=ubq.candidate_set), meta=meta)

    def wrong_kind(handle):
        return ubq.meta(ubq.loaded) if handle == ubq.structure else ubq.meta(handle)

    _rejected("structure_invalid", ubq.admit, _args(candidate_set=ubq.candidate_set), meta=wrong_kind)


def test_residue_mismatch_when_the_seven_fields_do_not_resolve_to_exactly_one_residue(ubq):
    listing = ubq.residues(ubq.structure)
    target = next(r for r in listing if r["seq_auth"] == 44)
    without = [r for r in listing if r is not target]
    _rejected("residue_mismatch", ubq.admit, _args(candidate_set=ubq.candidate_set), residues=lambda h: without)
    twice = [*listing, dict(target)]
    _rejected("residue_mismatch", ubq.admit, _args(candidate_set=ubq.candidate_set), residues=lambda h: twice)
    null_label = [{**r, "chain_label": None} if r is target else r for r in listing]   # null is not "A"
    _rejected("residue_mismatch", ubq.admit, _args(candidate_set=ubq.candidate_set), residues=lambda h: null_label)


def test_residue_mismatch_when_from_differs_from_the_structure_residue():
    residue = {"model_number": 1, "chain_auth": "A", "chain_label": None, "seq_auth": 5, "seq_label": None,
               "icode": "", "resname": "ILE"}
    position = {"residue": residue}
    listing = [{**residue, "category": "polymer", "atom_count": 8}]
    assert mi.check_residue({"from": "I", "to": "A"}, position, listing) == residue
    _rejected("residue_mismatch", mi.check_residue, {"from": "V", "to": "A"}, position, listing)
    mse = {**residue, "resname": "MSE"}
    _rejected("residue_mismatch", mi.check_residue, {"from": "M", "to": "A"}, {"residue": mse},
              [{**mse, "category": "polymer", "atom_count": 8}])


@pytest.mark.parametrize(("name", "index", "excluded"), [("not_checked", 3, []), ("checked", 1, [6])])
def test_admission_takes_stored_v2_candidate_sets(name, index, excluded, tmp_path):
    """M26 spec 9: a STORED v2 set (fixtures/reaction/t6, SYNTHETIC-PROVENANCE-t6b.md) is admitted like a v1 set; the
    checked one names K6 a catalytic_residue position (no candidate), I44W is a candidate of both."""
    world = V2.stored_world(tmp_path / "runs")
    run = world["run"]
    content = run.store.load(world[name])
    assert content["method_version"] == "mw.mutation_candidates/v2"
    assert content["protection_checks"]["catalytic_residue_database"]["status"] == name
    assert [p["residue"]["seq_auth"] for p in content["positions"] if "catalytic_residue" in p["exclusion_reasons"]] \
        == excluded

    def meta(handle):
        try:
            return run.store.meta(handle)
        except (KeyError, ValueError, TypeError):
            return None

    admitted = mi.admit(_args(candidate_set=world[name], candidate_index=index), meta=meta, load=run.store.load,
                        residues=lambda handle: structure_residues(run.store, handle)["residues"])
    assert admitted["candidate_set_content"] == content and admitted["structure"] == world["prepared"]
    assert (admitted["candidate"]["from"], admitted["candidate"]["to"], admitted["mutant_resname"]) == ("I", "W",
                                                                                                    "TRP")
    assert admitted["residue"] == {"model_number": 1, "chain_auth": "A", "chain_label": "A", "seq_auth": 44,
                                   "seq_label": 44, "icode": "", "resname": "ILE"}


def test_admission_check_order_is_arguments_first(ubq):
    calls = []

    def meta(handle):
        calls.append(handle)
        return ubq.meta(handle)

    _rejected("confirmation_missing", ubq.admit, _args(candidate_set="nope", selection_policy="x"), meta=meta)
    assert calls == []


def test_m7_preflight_failures_become_openmm_preflight_failed_and_unavailability_stays_412():
    precondition = ToolFailure(FailureClass.precondition, "missing terminal OXT; heavy-atom repair is unsupported",
                               detail={"residue": I44, "reason_code": "missing_terminal_oxt"})
    mapped = mi.preflight_failure(precondition)
    assert mapped.cls is FailureClass.input_invalid
    assert mapped.detail == {"reason_code": "openmm_preflight_failed", "m7_reason": "missing_terminal_oxt",
                             "m7_message": "missing terminal OXT; heavy-atom repair is unsupported"}
    no_code = mi.preflight_failure(ToolFailure(FailureClass.precondition, "modified or unsupported polymer residue",
                                               detail={"residue": I44}))
    assert no_code.detail == {"reason_code": "openmm_preflight_failed", "m7_reason": None,
                              "m7_message": "modified or unsupported polymer residue"}
    too_big = mi.preflight_failure(ToolFailure(FailureClass.resource_exceeded,
                                               "protein atom count is empty or exceeds fixed limit"))
    assert too_big.cls is FailureClass.input_invalid and too_big.detail["reason_code"] == "openmm_preflight_failed"
    for code in ("openmm_unavailable", "process_identity_unavailable"):
        original = ToolFailure(FailureClass.precondition, "unavailable", detail={"reason_code": code})
        assert mi.preflight_failure(original) is original


def test_excluded_components_lists_every_m7_category_with_counts():
    ref = dict(I44, chain_label="A", seq_label=None)
    excluded = [{"residue": ref, "atom_count": 1, "reason": "water_removed_during_preparation"},
                {"residue": ref, "atom_count": 1, "reason": "water_removed_during_preparation"},
                {"residue": ref, "atom_count": 21, "reason": "nonprotein"}]
    assert mi.excluded_components(excluded) == [
        {"reason": "water_removed_during_preparation", "residue_count": 2, "atom_count": 2},
        {"reason": "water", "residue_count": 0, "atom_count": 0},
        {"reason": "nonprotein", "residue_count": 1, "atom_count": 21}]
    assert mi.excluded_components([]) == [{"reason": r, "residue_count": 0, "atom_count": 0}
                                          for r in K.EXCLUDED_CATEGORIES]
    with pytest.raises(ValueError):
        mi.excluded_components([{"residue": ref, "atom_count": 1, "reason": "ligand"}])


# --- contacts (oracle: expected.json) -------------------------------------------------------------------------------

def _oracle_atoms():
    def residue(ordinal, resname):
        return {"model_number": 1, "chain_auth": "A", "chain_label": "A", "seq_auth": ordinal, "seq_label": ordinal,
                "icode": "", "resname": resname}

    return [{"residue": residue(a["residue_ordinal"], a["resname"]), "atom_name": a["atom_name"],
             "element": a["element"], "coordinates_A": [float(x) for x in a["xyz_A"]]} for a in ORACLE["atoms"]]


def _row(atoms, mutated_index, partner_index, distance):
    mine, partner = atoms[mutated_index], atoms[partner_index]
    return {"atom_name": mine["atom_name"], "element": mine["element"], "partner_residue": partner["residue"],
            "partner_atom_name": partner["atom_name"], "partner_element": partner["element"], "distance_A": distance}


@pytest.mark.parametrize("cutoff", ["4.0", "3.0", "2.5"])
def test_contacts_match_the_hand_oracle_with_inclusive_boundary_and_bond_exclusion(cutoff):
    atoms = _oracle_atoms()
    mutated = atoms[2]["residue"]
    out = mm.contacts(atoms, ORACLE["bonds"], mutated, float(cutoff))
    expected = ORACLE["expected"][cutoff]
    assert out == {"cutoff_A": float(cutoff), "excluded_bond_distance": 3,
                   "rows": [_row(atoms, r["mutated_atom"], r["partner_atom"], r["distance_A"])
                            for r in expected["rows"]],
                   "count": expected["count"], "residue_count": expected["residue_count"]}
    assert all(type(row["distance_A"]) is float for row in out["rows"])


def test_contacts_zero_is_a_computed_result_not_null():
    out = mm.contacts(_oracle_atoms(), ORACLE["bonds"], _oracle_atoms()[2]["residue"], 2.5)
    assert out["rows"] == [] and out["count"] == 0 and out["residue_count"] == 0


def test_bonded_pairs_within_three_bonds_and_hydrogens_are_never_contacts():
    atoms = _oracle_atoms()
    out = mm.contacts(atoms, ORACLE["bonds"], atoms[2]["residue"], 4.0)
    seen = {(r["atom_name"], r["partner_residue"]["seq_auth"], r["partner_atom_name"]) for r in out["rows"]}
    for pair in ORACLE["excluded_close_pairs_4A"]:
        mine, partner = atoms[pair["mutated_atom"]], atoms[pair["partner_atom"]]
        assert math.dist(mine["coordinates_A"], partner["coordinates_A"]) <= 4.0
        assert (mine["atom_name"], partner["residue"]["seq_auth"], partner["atom_name"]) not in seen
    assert all(r["partner_element"] != "H" and r["element"] != "H" for r in out["rows"])
    # H1 (atom 10) is 1.0 A from the mutated N and bonded to nothing of the mutated residue: still not a contact.
    assert math.dist(atoms[10]["coordinates_A"], atoms[2]["coordinates_A"]) == 1.0
    # Without the bond graph the 1-3 bonded pairs would appear: the exclusion is topological, not geometric.
    unbonded = mm.contacts(atoms, [], atoms[2]["residue"], 4.0)
    assert unbonded["count"] == 5 + len(ORACLE["excluded_close_pairs_4A"])


def test_contacts_cover_other_chains_keep_null_labels_and_order_by_structure():
    atoms = _oracle_atoms()
    other = {"model_number": 1, "chain_auth": "BB", "chain_label": None, "seq_auth": 1, "seq_label": None,
             "icode": "A", "resname": "LYS"}
    atoms.insert(0, {"residue": other, "atom_name": "NZ", "element": "N", "coordinates_A": [1.5, 0.0, -3.5]})
    bonds = [[a + 1, b + 1] for a, b in ORACLE["bonds"]]
    out = mm.contacts(atoms, bonds, atoms[3]["residue"], 4.0)
    keys = [(r["atom_name"], r["partner_residue"]["chain_auth"], r["partner_residue"]["seq_auth"],
             r["partner_atom_name"]) for r in out["rows"]]
    # NZ (1.5,0,-3.5): N sqrt(14.5), CA 3.5, CB sqrt(14.5); its residue is first in structure order.
    assert keys == [("N", "BB", 1, "NZ"), ("N", "A", 3, "CB"), ("N", "A", 4, "SD"),
                    ("CA", "BB", 1, "NZ"), ("CA", "A", 4, "SD"),
                    ("CB", "BB", 1, "NZ"), ("CB", "A", 1, "CA"), ("CB", "A", 3, "CB")]
    assert [r["distance_A"] for r in out["rows"]] == [math.sqrt(14.5), 3.0, 3.0, 3.5, math.sqrt(11.25),
                                                      math.sqrt(14.5), 4.0, math.sqrt(13.5)]
    assert out["rows"][0]["partner_residue"] == other and out["rows"][0]["partner_residue"]["chain_label"] is None
    assert out["count"] == 8 and out["residue_count"] == 4


def _crowd(n):
    mutated = {"model_number": 1, "chain_auth": "A", "chain_label": "A", "seq_auth": 1, "seq_label": 1,
               "icode": "", "resname": "ALA"}
    atoms = [{"residue": mutated, "atom_name": "CA", "element": "C", "coordinates_A": [0.0, 0.0, 0.0]}]
    for i in range(n):
        theta = 2 * math.pi * i / n
        residue = {**mutated, "seq_auth": 2 + i, "seq_label": 2 + i}
        atoms.append({"residue": residue, "atom_name": "O", "element": "O",
                      "coordinates_A": [3.0 * math.cos(theta), 3.0 * math.sin(theta), 0.0]})
    return atoms, mutated


def test_contact_row_cap_is_2000_and_more_rows_fail_without_truncation():
    atoms, mutated = _crowd(2000)
    assert mm.contacts(atoms, [], mutated, 4.0)["count"] == 2000
    atoms, mutated = _crowd(2001)
    with pytest.raises(mm.ContactLimitExceeded) as caught:
        mm.contacts(atoms, [], mutated, 4.0)
    assert caught.value.reason_code == "resource_exceeded"
    assert caught.value.detail == {"reason_code": "resource_exceeded", "limit": "too_many_contacts", "rows": 2001,
                                   "max_rows": 2000}


def test_contacts_need_the_mutated_residue_heavy_atoms():
    atoms = _oracle_atoms()
    missing = {**atoms[2]["residue"], "seq_auth": 99}
    with pytest.raises(ValueError):
        mm.contacts(atoms, ORACLE["bonds"], missing, 4.0)


# --- validated_model -------------------------------------------------------------------------------------------------

def _res(seq, resname, chain="A", label=True):
    return {"model_number": 1, "chain_auth": chain, "chain_label": chain if label else None, "seq_auth": seq,
            "seq_label": seq if label else None, "icode": "", "resname": resname}


R1, R3, R4, R5 = _res(1, "ALA"), _res(3, "GLY", label=False), _res(4, "HIS"), _res(5, "CYS")
R6 = _res(1, "TRP", chain="B")
WT2, MUT2 = _res(2, "SER"), _res(2, "CYS")
HEX = "0123456789abcdef" * 4


def _synthetic_side(mutant: bool, *, his_variant: str, new_ss: bool):
    """Hand-placed SYNTHETIC atoms: residue 2 is SER (wild type) or CYS (mutant, SG added by 'PDBFixer')."""
    r2 = MUT2 if mutant else WT2
    side = [
        (R1, "CA", "C", [-3.0, 0.0, 0.0]), (R1, "C", "C", [-1.5, 0.0, 0.0]),
        (r2, "N", "N", [0.0, 0.0, 0.0]), (r2, "CA", "C", [1.5, 0.0, 0.0]), (r2, "CB", "C", [1.5, 1.5, 0.0]),
        (r2, "SG" if mutant else "OG", "S" if mutant else "O", [1.5, 3.0, 0.0]), (r2, "H", "H", [0.0, 0.0, -1.0]),
        (R3, "N", "N", [3.0, 0.0, 0.0]), (R3, "CA", "C", [4.5, 0.0, 0.0]),
        (R4, "CG", "C", [0.0, 3.5, 2.0]), (R4, "ND1", "N", [0.0, 4.5, 2.5]), (R4, "HD1", "H", [0.0, 5.5, 2.5]),
        (R5, "SG", "S", [1.5, 5.0, 0.0]),
        (R6, "CZ2", "C", [1.5, 1.5, -3.5]),
    ]
    atoms = [{"residue": r, "atom_name": n, "element": e, "coordinates_A": xyz} for r, n, e, xyz in side]
    bonds = [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [2, 6], [3, 7], [7, 8], [9, 10], [10, 11]]
    if mutant and new_ss:
        bonds.append([5, 12])
    return {
        "structure_object": f"obj://run/mutation_model_structure/{'2' if mutant else '1'}",
        "structure_sha256": HEX[:-1] + ("b" if mutant else "a"),
        "system_xml_sha256": HEX[:-1] + ("d" if mutant else "c"),
        "topology_sha256": mm.topology_sha256(atoms, bonds),
        "heavy_atoms": 12, "added_hydrogens": 2,
        "added_heavy_atoms": [{"atom_name": "SG", "element": "S"}] if mutant else [],
        "protonation_variants": ([{"residue": MUT2, "variant": "CYX" if new_ss else None}] if mutant else []) + [
            {"residue": R4, "variant": his_variant}, {"residue": R5, "variant": "CYX" if mutant and new_ss else None}],
        "disulfide_bonds": [[MUT2, R5]] if mutant and new_ss else [],
        "final_bonds": bonds, "atom_mapping": atoms,
        "energy": {"before_kJ_mol": -100.5 if mutant else -120.25, "after_kJ_mol": -150.0 if mutant else -160.0,
                   "unit": "kJ/mol", "engine": "OpenMM", "force_field": "amber14-all + implicit/gbn2",
                   "convergence": "convergence_not_claimed"},
        "sasa": {"residue": r2, "engine": "FreeSASA", "value_A2": 30.5 if mutant else 25.0,
                 "parameters": {"engine_version": "2.2.1", "algorithm": "LeeRichards", "n_slices": 100,
                                "probe_radius_A": 1.4, "threads": 1, "radius_policy": "gemmi_vdw_elements_v1"}},
        "contacts": mm.contacts(atoms, bonds, r2, 4.0),
    }


def synthetic_model(*, protonation_difference=False, new_ss=False):
    wild = _synthetic_side(False, his_variant="HID", new_ss=new_ss)
    mutant = _synthetic_side(True, his_variant="HIE" if protonation_difference else "HID", new_ss=new_ss)
    differences = []
    if protonation_difference:
        differences.append({"residue": R4, "wild_type_reference": "HID", "mutant": "HIE"})
    if new_ss:
        differences.append({"residue": R5, "wild_type_reference": None, "mutant": "CYX"})
    limitations = [SPEC_L1, SPEC_L2, SPEC_L3, SPEC_L4, SPEC_L7]
    if differences:
        limitations.append(SPEC_L5)
    if new_ss:
        limitations.append(SPEC_L6)
    return copy.deepcopy({   # tampering must never reach the shared residue dicts above
        "schema": "mutation_model@1", "method_version": "mw.mutation_model/v1",
        "candidate": {"candidate_set": "obj://run/mutation_candidate_set/cc", "candidate_index": 3,
                      "position_index": 0, "from": "S", "to": "C", "residue": WT2, "mutant_resname": "CYS"},
        "structure": {"handle": "obj://run/prepared_structure/ps", "model_number": 1,
                      "structure_kind": "prepared_structure"},
        "parameters": {"seed": 20261004, "contact_cutoff_A": 4.0, "selection_policy": "protein_only",
                       "hydrogen_policy": "rebuild_pH7"},
        "method": {"method_id": "openmm_protein_minimize_v1", "schema": "openmm_protein_minimization@1",
                   "distribution_version": "8.6.0", "engine_build": "8.6.0.dev-c6173db", "platform": "CPU",
                   "platform_properties": {"Threads": "1"}, "hydrogen_platform": "CPU",
                   "hydrogen_platform_properties": {"Threads": "1"}, "forcefield_files_sha256": dict(FORCEFIELD_SHA256),
                   "forcefield_files": ["amber14-all.xml", "implicit/gbn2.xml"], "nonbonded_method": "NoCutoff",
                   "constraints": None, "pH": 7.0, "tolerance_kJ_mol_nm": 10.0, "max_iterations": 50,
                   "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7", "pdbfixer_version": "1.12.0"},
        "excluded_components": [{"reason": "water_removed_during_preparation", "residue_count": 58,
                                 "atom_count": 58}, {"reason": "water", "residue_count": 0, "atom_count": 0},
                                {"reason": "nonprotein", "residue_count": 0, "atom_count": 0}],
        "structures": {"wild_type_reference": wild, "mutant": mutant},
        "comparison": {"mutated_residue": WT2, "resnames": {"wild_type_reference": "SER", "mutant": "CYS"},
                       "new_disulfide_in_mutant": new_ss, "protonation_difference_count": len(differences)},
        "protonation_differences": differences,
        "limitations": limitations,
    })


@pytest.mark.parametrize("difference, new_ss", [(False, False), (True, False), (False, True), (True, True)])
def test_valid_synthetic_models_pass_with_conditional_l5_l6(difference, new_ss):
    content = synthetic_model(protonation_difference=difference, new_ss=new_ss)
    assert mm.validated_model(content) is content
    assert json.loads(json.dumps(content)) == content   # JSON round trip keeps every float bit
    assert mm.validated_model(json.loads(json.dumps(content))) is not None
    rows = content["structures"]["mutant"]["contacts"]["rows"]
    assert {r["partner_residue"]["chain_auth"] for r in rows} == {"A", "B"}


def test_synthetic_contact_rows_have_the_hand_derived_values():
    """Wild type, 4.0 A. Excluded by bonds although within 4 A: N/CA -> ALA1 CA, C and GLY3 N, CA (<= 3 bonds).
    Outside 4 A: N -> HIS4 CG sqrt(16.25), N -> TRP CZ2 sqrt(16.75), CB -> HIS4 ND1 sqrt(17.5)."""
    contacts = synthetic_model()["structures"]["wild_type_reference"]["contacts"]
    got = [(r["atom_name"], r["partner_residue"]["chain_auth"], r["partner_residue"]["seq_auth"],
            r["partner_atom_name"], r["distance_A"]) for r in contacts["rows"]]
    assert got == [("CA", "B", 1, "CZ2", math.sqrt(14.5)),
                   ("CB", "A", 4, "CG", math.sqrt(10.25)), ("CB", "A", 5, "SG", 3.5), ("CB", "B", 1, "CZ2", 3.5),
                   ("OG", "A", 4, "CG", math.sqrt(6.5)), ("OG", "A", 4, "ND1", math.sqrt(10.75)),
                   ("OG", "A", 5, "SG", 2.0), ("OG", "B", 1, "CZ2", math.sqrt(14.5))]
    assert (contacts["count"], contacts["residue_count"], contacts["cutoff_A"]) == (8, 3, 4.0)
    assert contacts["rows"][0]["partner_residue"] == R6
    # GLY3 has null labels; none of its atoms is a contact here, but the residue identity keeps them in the mapping.
    mapping = synthetic_model()["structures"]["wild_type_reference"]["atom_mapping"]
    assert mapping[7]["residue"]["chain_label"] is None and mapping[7]["residue"]["seq_label"] is None


def _set(content, path, value):
    target = content
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return content


def _drop(content, path):
    target = content
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    return content


def _rehash_mutant(content, edit, heavy=0):
    """Edit the mutant atoms and keep its topology hash / heavy count consistent, so a later check must refuse."""
    mutant = content["structures"]["mutant"]
    mutant["atom_mapping"] = copy.deepcopy(mutant["atom_mapping"])
    edit(mutant["atom_mapping"])
    mutant["topology_sha256"] = mm.topology_sha256(mutant["atom_mapping"], mutant["final_bonds"])
    mutant["heavy_atoms"] += heavy
    return content


M = ("structures", "mutant")
W = ("structures", "wild_type_reference")
TAMPER = [
    ("difference field at top level", lambda c: _set(c, ("energy_difference_kJ_mol",), 10.0)),
    ("difference field in comparison", lambda c: _set(c, ("comparison", "sasa_difference_A2"), 5.5)),
    ("delta field in an energy", lambda c: _set(c, (*M, "energy", "potential_change_kJ_mol"), -49.5)),
    ("contact count difference", lambda c: _set(c, ("comparison", "contact_count_delta"), 1)),
    ("missing structure key on one side", lambda c: _drop(c, (*M, "sasa"))),
    ("extra structure key on one side", lambda c: _set(c, (*W, "iterations"), 50)),
    ("schema", lambda c: _set(c, ("schema",), "mutation_model@2")),
    ("limitation reworded", lambda c: _set(c, ("limitations",), [*c["limitations"][:-1], "다른 문장"])),
    ("limitation order", lambda c: _set(c, ("limitations",), [SPEC_L1, SPEC_L2, SPEC_L3, SPEC_L7, SPEC_L4])),
    ("L5 without a difference", lambda c: _set(c, ("limitations",), [*c["limitations"], SPEC_L5])),
    ("L6 without a new disulfide", lambda c: _set(c, ("limitations",), [*c["limitations"], SPEC_L6])),
    ("NaN energy", lambda c: _set(c, (*W, "energy", "after_kJ_mol"), float("nan"))),
    ("energy went up", lambda c: _set(c, (*W, "energy", "after_kJ_mol"), -120.0)),
    ("integer energy", lambda c: _set(c, (*W, "energy", "before_kJ_mol"), -120)),
    ("energy wording", lambda c: _set(c, (*W, "energy", "unit"), "kcal/mol")),
    ("convergence claim", lambda c: _set(c, (*W, "energy", "convergence"), "converged")),
    ("negative SASA", lambda c: _set(c, (*W, "sasa", "value_A2"), -1.0)),
    ("SASA of another residue", lambda c: _set(c, (*W, "sasa", "residue"), R1)),
    ("SASA parameters", lambda c: _set(c, (*W, "sasa", "parameters", "n_slices"), 20)),
    ("contact distance changed", lambda c: _set(c, (*W, "contacts", "rows", 0, "distance_A"), 3.0)),
    ("contact row dropped", lambda c: c[M[0]][M[1]]["contacts"]["rows"].pop() and c),
    ("contact count", lambda c: _set(c, (*W, "contacts", "count"), 0)),
    ("contact cutoff", lambda c: _set(c, (*W, "contacts", "cutoff_A"), 4.5)),
    ("cutoff out of range", lambda c: _set(c, ("parameters", "contact_cutoff_A"), 7.0)),
    ("excluded bond distance", lambda c: _set(c, (*W, "contacts", "excluded_bond_distance"), 2)),
    ("moved atom without new contacts", lambda c: _set(c, (*W, "atom_mapping", 13, "coordinates_A"),
                                                        [1.5, 1.5, -9.0])),
    ("topology hash", lambda c: _set(c, (*W, "topology_sha256"), HEX)),
    ("bad hex", lambda c: _set(c, (*W, "structure_sha256"), "XYZ")),
    ("same structure bytes on both sides", lambda c: _set(c, (*M, "structure_sha256"),
                                                          c["structures"]["wild_type_reference"]["structure_sha256"])),
    ("same object on both sides", lambda c: _set(c, (*M, "structure_object"),
                                                 c["structures"]["wild_type_reference"]["structure_object"])),
    ("heavy atom count", lambda c: _set(c, (*W, "heavy_atoms"), 11)),
    ("added hydrogen count", lambda c: _set(c, (*W, "added_hydrogens"), 3)),
    ("wild type with added heavy atoms", lambda c: _set(c, (*W, "added_heavy_atoms"),
                                                        [{"atom_name": "OG", "element": "O"}])),
    ("added atom outside the mutated residue", lambda c: _set(c, (*M, "added_heavy_atoms"),
                                                              [{"atom_name": "CZ2", "element": "C"}])),
    ("extra atom outside the mutated residue", lambda c: _rehash_mutant(c, lambda atoms: atoms.append(
        {"residue": R6, "atom_name": "CH2", "element": "C", "coordinates_A": [9.0, 9.0, 9.0]}), heavy=1)),
    ("other residue renamed in the mutant only", lambda c: _rehash_mutant(c, lambda atoms: [
        a.update(residue={**a["residue"], "resname": "ALA"}) for a in atoms if a["residue"]["seq_auth"] == 3
        and a["residue"]["chain_auth"] == "A"])),
    ("protonation variant outside the closed set", lambda c: _set(c, (*W, "protonation_variants", 0, "variant"),
                                                                  "HSD")),
    ("protonation variant row missing", lambda c: c[W[0]][W[1]]["protonation_variants"].pop() and c),
    ("protonation difference invented", lambda c: _set(c, ("protonation_differences",), [
        {"residue": R4, "wild_type_reference": "HID", "mutant": "HIE"}])),
    ("disulfide recorded without a bond", lambda c: _set(c, (*W, "disulfide_bonds"), [[R5, R5]])),
    ("new disulfide flag", lambda c: _set(c, ("comparison", "new_disulfide_in_mutant"), True)),
    ("comparison resnames", lambda c: _set(c, ("comparison", "resnames", "mutant"), "SER")),
    ("mutant resname vs to", lambda c: _set(c, ("candidate", "mutant_resname"), "ALA")),
    ("from letter vs residue", lambda c: _set(c, ("candidate", "from"), "T")),
    ("from equals to", lambda c: _set(c, ("candidate", "to"), "S")),
    ("null label replaced by empty string", lambda c: _set(c, ("candidate", "residue"),
                                                           {**c["candidate"]["residue"], "chain_label": ""})),
    ("model number", lambda c: _set(c, ("structure", "model_number"), 2)),
    ("structure kind", lambda c: _set(c, ("structure", "structure_kind"), "structure")),
    ("seed bool", lambda c: _set(c, ("parameters", "seed"), True)),
    ("policy", lambda c: _set(c, ("parameters", "hydrogen_policy"), "keep")),
    ("pdbfixer version", lambda c: _set(c, ("method", "pdbfixer_version"), "1.11")),
    ("force field fingerprint", lambda c: _set(c, ("method", "forcefield_files_sha256", "implicit/gbn2.xml"), HEX)),
    ("engine build", lambda c: _set(c, ("method", "engine_build"), "8.5.0")),
    ("excluded category order", lambda c: _set(c, ("excluded_components",),
                                               list(reversed(c["excluded_components"])))),
    ("atoms reordered without fixing bonds", lambda c: _set(
        c, (*M, "atom_mapping"), [*c["structures"]["mutant"]["atom_mapping"][12:13],
                                  *c["structures"]["mutant"]["atom_mapping"][:12],
                                  *c["structures"]["mutant"]["atom_mapping"][13:]])),
]


@pytest.mark.parametrize("name, tamper", TAMPER, ids=[t[0] for t in TAMPER])
def test_tampered_models_are_refused(name, tamper):
    content = tamper(synthetic_model(protonation_difference=False, new_ss=False))
    with pytest.raises(mm.ModelInvalid):
        mm.validated_model(content)


def test_l5_and_l6_are_required_when_their_conditions_hold():
    content = synthetic_model(protonation_difference=True, new_ss=True)
    content["limitations"] = content["limitations"][:-1]
    with pytest.raises(mm.ModelInvalid):
        mm.validated_model(content)
    content = synthetic_model(protonation_difference=True)
    content["comparison"]["protonation_difference_count"] = 0
    with pytest.raises(mm.ModelInvalid):
        mm.validated_model(content)


def test_comparison_pairs_rows_by_seven_fields_and_the_mutated_residue_by_its_original_fields():
    r7 = _res(7, "CYS")
    candidate = {"residue": WT2, "mutant_resname": "CYS"}

    def side(pairs, variants):
        return {"disulfide_bonds": pairs, "protonation_variants": variants}

    same = mm.compare_structures(candidate, side([[R5, r7]], [{"residue": R5, "variant": "CYX"}]),
                                 side([[r7, R5]], [{"residue": R5, "variant": "CYX"}]))
    assert same == ({"mutated_residue": WT2, "resnames": {"wild_type_reference": "SER", "mutant": "CYS"},
                     "new_disulfide_in_mutant": False, "protonation_difference_count": 0}, [])
    new, differences = mm.compare_structures(
        candidate, side([], [{"residue": R4, "variant": "HID"}, {"residue": R5, "variant": None}]),
        side([[MUT2, R5]], [{"residue": MUT2, "variant": "CYX"}, {"residue": R4, "variant": "HID"},
                            {"residue": R5, "variant": "CYX"}]))
    assert new["new_disulfide_in_mutant"] is True and new["protonation_difference_count"] == 1
    # the mutated residue itself never counts as a protonation difference
    assert differences == [{"residue": R5, "wild_type_reference": None, "mutant": "CYX"}]
    # a disulfide of the mutated position that exists on both sides (by original identity) is not new
    kept, _ = mm.compare_structures({"residue": _res(2, "CYS"), "mutant_resname": "SER"},
                                    side([[_res(2, "CYS"), R5]], []), side([[_res(2, "SER"), R5]], []))
    assert kept["new_disulfide_in_mutant"] is False


def test_the_method_record_is_m7_dependencies_plus_the_pdbfixer_version():
    """M7 ``dependencies()`` runs in a separate interpreter so OpenMM never enters this test process."""
    code = ("import json; from mw.tools.openmm_method import dependencies; "
            "print(json.dumps({**dependencies(), 'pdbfixer_version': '1.12.0'}))")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO / "backend", capture_output=True, text=True,
                         check=True)
    method = json.loads(out.stdout)
    content = synthetic_model()
    content["method"] = method
    assert mm.validated_model(content) is content
    assert set(method) == set(K.METHOD_KEYS)
