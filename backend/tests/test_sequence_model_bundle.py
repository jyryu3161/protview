"""M23 T2 ``mutation_set_model@1`` construction and the pure ``validated_model`` (spec .dryforge/spec.md 4).

Models are LABELED SYNTHETIC contents (``sequence_ga_fixture.synthetic_entry``: standard PDB atom names on a small
made-up protein holding the real tiny M20 set's positions; coordinates, energies and hashes are made up) checked
against the REAL tiny M20 candidate set. Expected added atoms, protonation differences, disulfide flags, handles and
sentences are worked out by hand from the synthetic residues, never read back from the module under test. The real
PDBFixer path is T3's (``test_sequence_model_worker.py``).
"""
from __future__ import annotations

import copy
import hashlib

import pytest
import sequence_ga_fixture as SF

from mw import mutation_model_constants as MK
from mw import sequence_ga_constants as SC
from mw import sequence_ga_inputs as GI
from mw import sequence_model_bundle as SM
from mw.core.handles import object_sha

TINY = SF.TINY["content"]
TINY_HANDLE = SF.TINY["handle"]
SEED = 42
K6, I44, G76, H68, C20, C30 = (SF.seven(6, "LYS"), SF.seven(44, "ILE"), SF.seven(76, "GLY"), SF.seven(68, "HIS"),
                               SF.seven(20, "CYS"), SF.seven(30, "CYS"))


def _content(key: str | None, reference=None, **entry_options):
    mutations = [] if key is None else SM.model_mutations(TINY, key)
    mutated = {row["residue"]["seq_auth"]: row["mutant_resname"] for row in mutations}
    entry, cif = SF.synthetic_entry(mutated, **entry_options)
    content = SM.model_content(run_id=SF.RUN_ID, candidate_set_handle=TINY_HANDLE,
                               structure=SF.structure_record(), mutations=mutations, seed=SEED,
                               method=SF.model_method(), entry=entry, cif_raw=cif, reference=reference)
    return content, cif


@pytest.fixture(scope="module")
def reference():
    return _content(None)


def _validated(content, cif, reference=None, **changes):
    options = {"run_id": SF.RUN_ID, "candidate_set_handle": TINY_HANDLE, "candidate_set": TINY,
               "structure_cif": cif, "reference": reference, **changes}
    return SM.validated_model(content, **options)


def _refused(content, cif, reference=None, **changes):
    with pytest.raises(SM.ModelInvalid):
        _validated(content, cif, reference, **changes)


# ---------------------------------------------------------------- construction


def test_structure_handle_is_the_store_formula():
    raw = b"data_x\n"
    sha = hashlib.sha256(b"mutation_set_model_structure\0mutation_set_model_structure@1\0" + raw).hexdigest()
    assert SM.structure_handle("run_a", raw) == f"obj://run_a/mutation_set_model_structure/{sha}"
    assert sha == object_sha("mutation_set_model_structure", "mutation_set_model_structure@1", raw)


def test_model_mutations_are_the_candidate_rows_in_structure_order():
    rows = SM.model_mutations(TINY, "1-3-5")
    assert rows == [{"candidate_index": 1, "residue": K6, "from": "K", "to": "W", "mutant_resname": "TRP"},
                    {"candidate_index": 3, "residue": I44, "from": "I", "to": "W", "mutant_resname": "TRP"},
                    {"candidate_index": 5, "residue": G76, "from": "G", "to": "W", "mutant_resname": "TRP"}]
    assert SM.model_mutations(TINY, "0")[0]["mutant_resname"] == "ALA"
    for key in ("0-1", "7", "5-3", "wild_type"):
        with pytest.raises(ValueError):
            SM.model_mutations(TINY, key)


def test_wild_type_reference_model(reference):
    content, cif = reference
    assert set(content) == {"schema", "method_version", "candidate_set", "structure", "mutations", "seed", "method",
                            "structures", "protonation_differences", "new_disulfide_in_mutant",
                            "reference_structure_sha256", "limitations"}
    assert (content["schema"], content["method_version"]) == ("mutation_set_model@1", "mw.mutation_set_model/v1")
    assert content["mutations"] == [] and list(content["structures"]) == ["wild_type_reference"]
    entry = content["structures"]["wild_type_reference"]
    assert entry["structure_object"] == SM.structure_handle(SF.RUN_ID, cif)
    assert entry["structure_sha256"] == hashlib.sha256(cif).hexdigest() and entry["added_heavy_atoms"] == []
    assert "sasa" not in entry and "contacts" not in entry
    assert (content["protonation_differences"], content["new_disulfide_in_mutant"],
            content["reference_structure_sha256"]) == ([], False, None)
    assert content["limitations"] == [MK.L1, MK.L3]
    assert content["method"]["multi_mutation"] == "sequential_structure_order_round4"
    assert _validated(content, cif) is content


def test_mutant_model_added_atoms_per_residue(reference):
    content, cif = _content("1-3", reference[0])                         # K6W, I44W
    entry = content["structures"]["mutant"]
    assert list(content["structures"]) == ["mutant"]
    # TRP heavy atoms minus the input residue's: LYS keeps N CA C O CB CG; ILE keeps N CA C O CB CD1
    trp6 = ["CD1", "CD2", "NE1", "CE2", "CE3", "CZ2", "CZ3", "CH2"]
    trp44 = ["CG", "CD2", "NE1", "CE2", "CE3", "CZ2", "CZ3", "CH2"]
    expected = ([{"residue": SF.seven(6, "TRP"), "atom_name": n, "element": n[0]} for n in trp6] +
                [{"residue": SF.seven(44, "TRP"), "atom_name": n, "element": n[0]} for n in trp44])
    assert entry["added_heavy_atoms"] == expected
    assert SM.expected_added_atoms(entry, reference[0]["structures"]["wild_type_reference"],
                                   content["mutations"]) == expected
    assert content["reference_structure_sha256"] == \
        reference[0]["structures"]["wild_type_reference"]["structure_sha256"]
    assert content["protonation_differences"] == [] and content["new_disulfide_in_mutant"] is False
    assert content["limitations"] == [MK.L1, MK.L3]
    _validated(content, cif, reference[0])


def test_mutation_to_alanine_adds_nothing_and_the_c_terminal_oxt_is_kept(reference):
    content, cif = _content("4", reference[0])                           # G76A: ALA adds CB only
    assert content["structures"]["mutant"]["added_heavy_atoms"] == [
        {"residue": SF.seven(76, "ALA"), "atom_name": "CB", "element": "C"}]
    _validated(content, cif, reference[0])
    content, cif = _content("0", reference[0])                           # K6A: nothing added
    assert content["structures"]["mutant"]["added_heavy_atoms"] == []
    _validated(content, cif, reference[0])


def test_protonation_difference_outside_the_mutated_residues_adds_sl5(reference):
    content, cif = _content("1", reference[0], variants={68: "HID"})
    assert content["protonation_differences"] == [{"residue": H68, "wild_type_reference": "HIE", "mutant": "HID"}]
    assert content["limitations"] == [MK.L1, MK.L3, SC.SL5]
    _validated(content, cif, reference[0])


def test_new_disulfide_in_the_mutant_adds_both_rows_and_l6(reference):
    content, cif = _content("1-3", reference[0], disulfide=True)
    assert content["new_disulfide_in_mutant"] is True
    assert content["protonation_differences"] == [
        {"residue": C20, "wild_type_reference": None, "mutant": "CYX"},
        {"residue": C30, "wild_type_reference": None, "mutant": "CYX"}]
    assert content["limitations"] == [MK.L1, MK.L3, SC.SL5, MK.L6]
    _validated(content, cif, reference[0])


def test_rules_exclude_the_mutated_residues_themselves():
    """Pure helpers on hand-made rows: a mutated residue that was a His/Cys is not a difference, and a disulfide
    through a renamed residue is matched back to its original identity."""
    his = {**SF.seven(6, "HIS")}
    mutations = [{"candidate_index": 0, "residue": his, "from": "H", "to": "C", "mutant_resname": "CYS"}]
    reference = {"protonation_variants": [{"residue": his, "variant": "HIE"}, {"residue": H68, "variant": "HIE"}],
                 "disulfide_bonds": [[SF.seven(6, "HIS"), C30]], "atom_mapping": []}
    mutant = {"protonation_variants": [{"residue": SF.seven(6, "CYS"), "variant": "CYX"},
                                       {"residue": H68, "variant": "HIE"}],
              "disulfide_bonds": [[SF.seven(6, "CYS"), C30]], "atom_mapping": []}
    assert SM.protonation_differences(mutant, reference, mutations) == []
    assert SM.new_disulfide(mutant, reference, mutations) is False
    mutant["disulfide_bonds"] = [[C20, C30]]
    assert SM.new_disulfide(mutant, reference, mutations) is True


# ---------------------------------------------------------------- refusals (changed contents)


def _mutant(reference, key="1-3", **options):
    return _content(key, reference[0], **options)


@pytest.mark.parametrize("change", [
    lambda e: e["added_heavy_atoms"].pop(),
    lambda e: e["added_heavy_atoms"].append({"residue": SF.seven(6, "TRP"), "atom_name": "N", "element": "N"}),
    lambda e: e["added_heavy_atoms"].reverse(),
    lambda e: e["added_heavy_atoms"].__setitem__(0, {**e["added_heavy_atoms"][0], "residue": K6}),
    lambda e: e["added_heavy_atoms"].__setitem__(0, {**e["added_heavy_atoms"][0], "element": "N"}),
    lambda e: e["added_heavy_atoms"].__setitem__(0, {"atom_name": "CD1", "element": "C"}),   # M21 shape
])
def test_added_atom_records_must_be_template_minus_input_per_residue(reference, change):
    content, cif = _mutant(reference)
    change(content["structures"]["mutant"])
    _refused(content, cif, reference[0])


@pytest.mark.parametrize("change", [
    lambda c: c["protonation_differences"].clear(),
    lambda c: c["protonation_differences"][0].__setitem__("mutant", "HIP"),
    lambda c: c["protonation_differences"].append(copy.deepcopy(c["protonation_differences"][0])),
    lambda c: c.__setitem__("new_disulfide_in_mutant", True),
    lambda c: c.__setitem__("limitations", [MK.L1, MK.L3]),
    lambda c: c.__setitem__("limitations", [MK.L1, MK.L3, SC.SL5, MK.L6]),
    lambda c: c.__setitem__("limitations", [MK.L1, MK.L3, MK.L5]),                 # the M21 single-mutation L5
])
def test_differences_and_sentences_are_recomputed_from_both_models(reference, change):
    content, cif = _mutant(reference, key="1", variants={68: "HID"})
    change(content)
    _refused(content, cif, reference[0])


def test_a_dropped_disulfide_flag_is_refused(reference):
    content, cif = _mutant(reference, disulfide=True)
    content["new_disulfide_in_mutant"] = False
    _refused(content, cif, reference[0])


@pytest.mark.parametrize("where,key", [(None, "ddg_kJ_mol"), (None, "energy_difference"), (None, "rank"),
                                       (None, "score"), (None, "best"), ("entry", "delta_kJ_mol"),
                                       ("entry", "sasa"), ("entry", "contacts"), ("energy", "change_kJ_mol"),
                                       ("energy", "difference")])
def test_difference_rank_and_score_fields_are_refused(reference, where, key):
    content, cif = _mutant(reference)
    target = {None: content, "entry": content["structures"]["mutant"],
              "energy": content["structures"]["mutant"]["energy"]}[where]
    target[key] = 0.0
    _refused(content, cif, reference[0])


@pytest.mark.parametrize("change", [
    lambda c: c["structures"].__setitem__("wild_type_reference", c["structures"]["mutant"]),
    lambda c: c.__setitem__("structures", {"wild_type_reference": c["structures"]["mutant"]}),
    lambda c: c["mutations"].reverse(),
    lambda c: c["mutations"][0].__setitem__("residue", {**K6, "chain_label": None}),
    lambda c: c["mutations"][0].__setitem__("to", "A"),
    lambda c: c["mutations"][0].__setitem__("mutant_resname", "PHE"),
    lambda c: c["mutations"][0].__setitem__("candidate_index", 0),
    lambda c: c["mutations"].append({"candidate_index": 0, "residue": K6, "from": "K", "to": "A",
                                     "mutant_resname": "ALA"}),
    lambda c: c.__setitem__("candidate_set", "obj://run_x/mutation_candidate_set/" + "0" * 64),
    lambda c: c.__setitem__("structure", {**c["structure"], "model_number": 2}),
    lambda c: c.__setitem__("schema", "mutation_model@1"),
    lambda c: c.__setitem__("method_version", "mw.mutation_model/v1"),
    lambda c: c.__setitem__("seed", True),
    lambda c: c.__setitem__("seed", 2147483648),
    lambda c: c["method"].pop("multi_mutation"),
    lambda c: c["method"].__setitem__("max_iterations", 100),
    lambda c: c.__setitem__("reference_structure_sha256", "0" * 64),
    lambda c: c.__setitem__("reference_structure_sha256", None),
])
def test_identity_method_and_relation_changes_are_refused(reference, change):
    content, cif = _mutant(reference)
    change(content)
    _refused(content, cif, reference[0])


@pytest.mark.parametrize("change", [
    lambda e: e.__setitem__("topology_sha256", "0" * 64),
    lambda e: e.__setitem__("heavy_atoms", e["heavy_atoms"] + 1),
    lambda e: e.__setitem__("added_hydrogens", e["added_hydrogens"] - 1),
    lambda e: e["energy"].__setitem__("after_kJ_mol", e["energy"]["before_kJ_mol"] + 0.01),
    lambda e: e["energy"].__setitem__("before_kJ_mol", float("nan")),
    lambda e: e["energy"].__setitem__("unit", "kcal/mol"),
    lambda e: e["protonation_variants"][-1].__setitem__("variant", "HIX"),
    lambda e: e.__setitem__("disulfide_bonds", [[C20, C30]]),
    lambda e: e.__setitem__("structure_sha256", "0" * 64),
    lambda e: e.__setitem__("structure_object", e["structure_object"].replace(SF.RUN_ID, "run_other")),
    lambda e: e.__setitem__("structure_object", e["structure_object"].replace("mutation_set_model_structure",
                                                                              "mutation_model_structure")),
])
def test_structure_entry_changes_are_refused(reference, change):
    content, cif = _mutant(reference)
    change(content["structures"]["mutant"])
    _refused(content, cif, reference[0])


def test_stored_mmcif_bytes_and_handle_are_matched(reference):
    content, cif = _mutant(reference)
    _refused(content, cif + b" ", reference[0])
    _refused(content, cif, reference[0], run_id="run_other")


def test_atoms_outside_the_mutated_residues_must_be_the_reference_atoms(reference):
    content, cif = _mutant(reference)
    entry = content["structures"]["mutant"]
    renamed = next(i for i, a in enumerate(entry["atom_mapping"])
                   if a["residue"]["seq_auth"] == 68 and a["atom_name"] == "CE1")
    entry["atom_mapping"][renamed] = {**entry["atom_mapping"][renamed], "atom_name": "CE9"}
    entry["topology_sha256"] = GI.mm.topology_sha256(entry["atom_mapping"], entry["final_bonds"])
    _refused(content, cif, reference[0])


def test_an_unrenamed_mutated_residue_is_refused(reference):
    content, cif = _content(None)                       # wild-type atoms under a mutant's mutations
    mutant, _ = _mutant(reference, key="0")
    content.update({key: mutant[key] for key in ("mutations", "reference_structure_sha256", "limitations")})
    content["structures"] = {"mutant": content["structures"]["wild_type_reference"]}
    _refused(content, cif, reference[0])


def test_reference_relation_is_required_and_checked(reference):
    content, cif = _mutant(reference)
    _refused(content, cif, None)                                       # a mutant needs its reference
    other_seed = copy.deepcopy(reference[0])
    other_seed["seed"] = SEED + 1
    _refused(content, cif, other_seed)
    other_method = copy.deepcopy(reference[0])
    other_method["method"]["engine_build"] = "8.6.0.other"
    _refused(content, cif, other_method)
    _refused(content, cif, _mutant(reference, key="0")[0])             # the reference is the wild type
    _refused(reference[0], reference[1], reference[0])                 # the wild type takes no reference


def test_model_size_bound(reference, monkeypatch):
    content, cif = _mutant(reference)
    _validated(content, cif, reference[0])
    monkeypatch.setattr(SC, "MAX_MODEL_OBJECT_BYTES", 1000)
    _refused(content, cif, reference[0])


def test_validation_does_not_mutate_its_inputs(reference):
    content, cif = _mutant(reference)
    before, ref_before = copy.deepcopy(content), copy.deepcopy(reference[0])
    _validated(content, cif, reference[0])
    assert content == before and reference[0] == ref_before


# ---------------------------------------------------------------- T5: the check without the reference model (M18 path)
def _alone(content, cif, **changes):
    options = {"run_id": SF.RUN_ID, "candidate_set_handle": TINY_HANDLE, "candidate_set": TINY, "structure_cif": cif,
               **changes}
    return SM.validated_model_alone(content, **options)


def test_validated_model_alone_checks_everything_but_the_reference_relations(reference):
    content, cif = _mutant(reference, key="1", variants={68: "HID"})
    assert _alone(content, cif) == content == _validated(content, cif, reference[0])
    assert _alone(*reference) == reference[0]                           # a wild-type model: the full check
    # The relations to the reference model are what the full check adds (labeled: a recorded difference changed).
    changed = copy.deepcopy(content)
    changed["protonation_differences"][0]["mutant"] = "HIP"
    assert _alone(changed, cif) == changed
    _refused(changed, cif, reference[0])
    # Everything else is still refused without the reference.
    for change in (lambda c: c.__setitem__("reference_structure_sha256", None),
                   lambda c: c.__setitem__("limitations", [MK.L1, MK.L3]),
                   lambda c: c["mutations"][0].__setitem__("to", "A"),
                   lambda c: c["structures"]["mutant"].__setitem__("structure_sha256", "0" * 64),
                   lambda c: c["structures"]["mutant"].__setitem__("sasa", 0.0),
                   lambda c: c.__setitem__("score", 0.0)):
        bad = copy.deepcopy(content)
        change(bad)
        with pytest.raises(SM.ModelInvalid):
            _alone(bad, cif)
    with pytest.raises(SM.ModelInvalid):
        _alone(content, cif + b" ")
