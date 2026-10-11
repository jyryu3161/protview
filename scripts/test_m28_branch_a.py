"""Independent expectations and case judgement of the M28 branch A module (scripts/m28_branch_a.py); no service.

The counts of the real inputs are checked on the local files themselves (public structures of this repository, the
archived M26 reaction set .deps/reaction_qa/import2 and the local kbase_kinase checkout): a missing file is a failure,
never a skip (.dryforge/spec.md R1, plan T6).
"""

import ast
import json
import os
import shutil
from pathlib import Path

import pytest

from scripts import m28_branch_a as a
from scripts import m28_common as c

REPO = Path(a.__file__).resolve().parents[1]
FIXTURES = REPO / "backend/tests/fixtures"
KBASE_DIST = REPO.parent / "kbase_kinase" / "dist"
REACTION_ARCHIVE = REPO / ".deps/reaction_qa/import2"


def _need(path: Path) -> Path:
    assert path.exists(), f"required local input is missing (no skip): {path}"
    return path


def _cif(rows: list[str], entity: str = "") -> str:
    head = ["data_TEST", "#", entity, "loop_", *[f"_atom_site.{name}" for name in (
        "group_PDB", "id", "type_symbol", "label_atom_id", "label_alt_id", "label_comp_id", "label_asym_id",
        "label_entity_id", "label_seq_id", "pdbx_PDB_ins_code", "Cartn_x", "Cartn_y", "Cartn_z", "occupancy",
        "B_iso_or_equiv", "pdbx_formal_charge", "auth_seq_id", "auth_comp_id", "auth_asym_id", "auth_atom_id",
        "pdbx_PDB_model_num")]]
    return "\n".join([*head, *rows, "#", ""])


def _atom(i, group, element, name, alt, comp, asym, entity, seq, x, y, z, occ, auth_seq, chain="A", model=1, ins="?"):
    return (f"{group} {i} {element} {name} {alt} {comp} {asym} {entity} {seq} {ins} {x} {y} {z} {occ} 10.0 ? "
            f"{auth_seq} {comp} {chain} {name} {model}")


# ---------------------------------------------------------------------------------------------------- mmCIF reading
def test_cif_tokens_unquote_and_join_text_fields():
    text = "_a.b 'it''s' \"x y\" plain # comment\n;line one\nline two\n;\n_c.d 'C1\\''"
    tokens = list(a.cif_tokens(text))
    assert tokens[:4] == ["_a.b", "it''s", "x y", "plain"]
    assert tokens[4] == "line one\nline two"
    assert tokens[5:] == ["_c.d", "C1\\'"]


def test_cif_category_reads_wrapped_loops_and_single_items():
    text = ("data_X\nloop_\n_entity.id\n_entity.type\n_entity.details\n1 polymer\n'long name' 2 water\n?\n"
            "#\n_other.x 1\n")
    assert a.cif_category(text, "_entity") == [{"id": "1", "type": "polymer", "details": "long name"},
                                               {"id": "2", "type": "water", "details": "?"}]
    single = "data_X\n_entity.id 1\n_entity.type polymer\n#\n"
    assert a.cif_category(single, "_entity") == [{"id": "1", "type": "polymer"}]
    with pytest.raises(ValueError):
        a.cif_category("data_X\nloop_\n_entity.id\n_entity.type\n1\n", "_entity")


def test_residue_key_is_the_harness_json_form():
    assert a.residue_key(a.LIGAND) == '[1,"A","B",999,null,"","AQ4"]'


def test_policy_altloc_ties_hydrogens_waters_and_models(tmp_path):
    rows = [
        _atom(1, "ATOM", "N", "N", "A", "CYS", "A", 1, 1, 0, 0, 0, "0.50", 10),
        _atom(2, "ATOM", "N", "N", "B", "CYS", "A", 1, 1, 0, 0, 0.1, "0.50", 10),
        _atom(3, "ATOM", "C", "CA", ".", "CYS", "A", 1, 1, 1, 0, 0, "1.00", 10),
        _atom(4, "ATOM", "H", "H", ".", "CYS", "A", 1, 1, 1, 1, 0, "1.00", 10),
        _atom(5, "ATOM", "O", "O", "A", "SER", "A", 1, 2, 2, 0, 0, "0.30", 11, ins="B"),
        _atom(6, "ATOM", "O", "O", "B", "SER", "A", 1, 2, 2, 0, 0.2, "0.70", 11, ins="B"),
        _atom(7, "HETATM", "O", "O", ".", "HOH", "C", 3, ".", 9, 9, 9, "1.00", 101),
        _atom(8, "ATOM", "C", "CA", ".", "GLY", "A", 1, 3, 5, 5, 5, "1.00", 12, model=2),
    ]
    path = tmp_path / "t.cif"
    path.write_text(_cif(rows))
    atoms = a.atom_records(path)
    assert len(atoms) == 7                                    # the second model is not read
    assert atoms[4]["residue"] == {"model_number": 1, "chain_auth": "A", "chain_label": "A", "seq_auth": 11,
                                   "seq_label": 2, "icode": "B", "resname": "SER"}
    assert atoms[6]["residue"]["seq_label"] is None and atoms[0]["residue"]["icode"] == ""
    kept, removed = a.apply_policy(atoms)
    assert removed == {"waters": 1, "hydrogens": 1, "altlocs": 2}
    assert [atom["id"] for atom in kept] == ["1", "3", "6"]   # tie → A; higher mean occupancy → B
    kept_first, _ = a.apply_policy(atoms, altloc="first", waters="keep_all", hydrogens="keep")
    assert [atom["id"] for atom in kept_first] == ["1", "3", "4", "5", "7"]
    with pytest.raises(ValueError):
        a.apply_policy(atoms, waters="some")


# ---------------------------------------------------------------------------------------------------- A1 / A2 / A6
def test_a1_counts_of_public_1m17_after_the_screen_defaults():
    path = _need(FIXTURES / "public_1m17.cif")
    expected = a.a1_expectation(path)
    assert expected["input"] == {"residues": 333, "atoms": 2560}
    assert (expected["residues"], expected["atoms"]) == (313, 2526)
    assert expected["removed"] == {"waters": 20, "hydrogens": 0, "altlocs": 14}
    assert expected["policy"] == {"altloc": "highest_occupancy", "waters": "strip_all", "hydrogens": "strip"}
    kept_waters = a.a1_expectation(path, {"altloc": "highest_occupancy", "waters": "keep_all", "hydrogens": "strip"})
    assert (kept_waters["residues"], kept_waters["atoms"]) == (333, 2546)


def test_aq4_contacts_of_public_1m17_come_from_the_coordinates():
    path = _need(FIXTURES / "public_1m17.cif")
    ligands = {a.residue_key(atom["residue"]) for atom in a.atom_records(path) if atom["residue"]["resname"] == "AQ4"}
    assert ligands == {a.residue_key(a.LIGAND)}               # one instance, exactly the 7 fields of decision 2
    pairs = a.contact_pairs(path)
    summary = a.contact_summary(pairs)
    assert summary["rows"] == 65 and summary["residues"] == 15
    assert summary["byType"] == {"contact": 33, "polar_contact": 7, "hydrophobic_contact": 25}
    assert all(0 < pair["distance_A"] <= a.CUTOFF_A for pair in pairs)
    assert summary["minimumDistance"] == min(pair["distance_A"] for pair in pairs)
    oracle = a.site_oracle(pairs)
    keys = {key: json.loads(key) for key in oracle}
    met = [oracle[key] for key, k in keys.items() if (k[1], k[3], k[6]) == ("A", 769, "MET")]
    assert len(met) == 1 and {(p["protein_atom"], p["ligand_atom"]) for p in met[0]["polar"]} >= {("N", "N2")}
    assert sum(len(entry["polar"]) for entry in oracle.values()) == 7


def test_site_oracle_counts_kinds_minimum_and_polar_pairs():
    residue = dict(a.LIGAND, resname="LYS", chain_label="A", seq_auth=10, seq_label=5)
    pairs = [{"residue": residue, "protein_atom": "NZ", "ligand_atom": "O1", "type": "polar_contact",
              "distance_A": 3.1},
             {"residue": residue, "protein_atom": "CE", "ligand_atom": "C2", "type": "hydrophobic_contact",
              "distance_A": 3.9},
             {"residue": residue, "protein_atom": "CD", "ligand_atom": "O1", "type": "contact", "distance_A": 2.9}]
    entry = a.site_oracle(pairs)[a.residue_key(residue)]
    assert entry["counts"] == {"contact": 1, "polar_contact": 1, "hydrophobic_contact": 1}
    assert entry["min"] == 2.9
    assert entry["polar"] == [{"protein_atom": "NZ", "ligand_atom": "O1", "distance_A": 3.1}]


# ---------------------------------------------------------------------------------------------------- A7 precedents
def test_precedent_counts_of_the_local_kbase_dist():
    moves = a.read_jsonl(_need(KBASE_DIST / "moves.jsonl"))
    flagged = a.read_jsonl(_need(KBASE_DIST / "moves_flagged.jsonl"))
    references = a.read_jsonl(_need(KBASE_DIST / "references.jsonl"))
    egfr = a.precedent_counts(moves, flagged, references, "P00533")
    assert (egfr["status"], egfr["moves"], egfr["movesFlagged"], egfr["excluded"], egfr["references"]) == \
        ("precedents_found", 76, None, 66, 1)
    assert egfr["variants"] == {"L834R": 1, "L858R": 15, "T790M": 4, "WT": 3, "not_reported": 53}
    cdk2 = a.precedent_counts(moves, flagged, references, "P24941")
    assert (cdk2["moves"], cdk2["excluded"], cdk2["references"]) == (32, 24, 1)
    included = a.precedent_counts(moves, flagged, references, "P24941", include_flagged=True)
    assert (included["movesFlagged"], included["excluded"]) == (24, None)
    aurka = a.precedent_counts(moves, flagged, references, "O14965")
    assert (aurka["status"], aurka["moves"], aurka["excluded"]) == ("none_in_included_files", 0, 0)
    assert a.precedent_counts([], [], [], "Q00000")["status"] == "not_in_kbase_references"


def test_precedent_expectations_read_the_installed_set_layout(tmp_path):
    set_dir = tmp_path / "sets" / ("d" * 64)
    (set_dir / "files/dist").mkdir(parents=True)

    def record(accession, variant):
        return json.dumps({"target": {"uniprot": accession, "variant": variant}}) + "\n"
    (set_dir / "files/dist/moves.jsonl").write_text(record("P1", "WT") + record("P1", "X1") + record(None, "WT"))
    (set_dir / "files/dist/moves_flagged.jsonl").write_text(record("P1", "WT"))
    (set_dir / "files/dist/references.jsonl").write_text(json.dumps({"uniprot": "P1"}) + "\n")
    (set_dir / "manifest.json").write_text(json.dumps({"files": [
        {"name": f"dist/{name}.jsonl", "path": f"files/dist/{name}.jsonl"} for name in
        ("moves", "moves_flagged", "references")]}))
    links = [{"id": "l", "map": "m", "chains": None, "includeFlagged": False, "accessions": {"A": "P1", "B": "P1"}}]
    [plan] = a.precedent_expectations(set_dir, links)
    assert plan["expect"] == {"nullResult": False, "chains": {"A": ["linked", None, "P1"], "B": ["linked", None, "P1"]},
                              "targets": {"P1": {"status": "precedents_found", "moves": 2, "movesFlagged": None,
                                                 "excluded": 1, "references": 1, "variants": {"WT": 1, "X1": 1},
                                                 "chains": ["A", "B"]}}}


# ---------------------------------------------------------------------------------------------------- A8 reaction
def _entry(mcsa_id, residues, reference="P1"):
    return {"mcsa_id": mcsa_id, "reference_uniprot_id": reference, "residues": [
        {"residue_chains": [{"pdb_id": pdb, "chain_name": chain, "auth_resid": auth, "code": code} for
                            pdb, chain, auth, code in members]} for members in residues]}


def test_mcsa_expectation_follows_the_business_rule_order():
    structure = {"A": [{"seq_auth": 10, "icode": "", "resname": "ASP"}, {"seq_auth": 11, "icode": "", "resname": "GLU"},
                       {"seq_auth": 12, "icode": "A", "resname": "SER"},
                       {"seq_auth": 13, "icode": "", "resname": "HIS"},
                       {"seq_auth": 13, "icode": "B", "resname": "HIS"},
                       {"seq_auth": 14, "icode": "", "resname": "MSE"}],
                 "B": [{"seq_auth": 10, "icode": "", "resname": "ASP"}]}
    entries = [_entry(7, [[("9xyz", "A", 10, "Asp")], [("9XYZ", "A", 11, "Asp")], [("9xyz", "A", 12, "Ser")],
                          [("9xyz", "A", 13, "His")], [("9xyz", "A", 99, "Lys")], [("9xyz", "A", None, "Lys")],
                          [("9xyz", "A", 10, "Sec")], [("9xyz", "A", 10, "Asp"), ("9xyz", "A", 10, "Glu")],
                          [("9xyz", "A", 14, "Met")]])]
    out = a.mcsa_expectation(entries, "9XYZ", structure)
    assert out["lookupEntries"] == [7]
    chain = out["chains"]["A"]
    assert chain["coverage"] == "covered" and chain["entries"] == [7]
    assert chain["rows"] == {"7/0": "matched", "7/1": "conflict:residue_name_differs",
                             "7/2": "unmatched:insertion_code_present", "7/3": "unmatched:ambiguous_residue_number",
                             "7/4": "unmatched:residue_not_in_structure", "7/5": "unmatched:no_author_number",
                             "7/6": "unmatched:non_standard_code", "7/7": "conflict:mcsa_rows_disagree",
                             "7/8": "unknown"}
    assert chain["unknownRows"] == ["7/8"]
    assert out["chains"]["B"] == {"coverage": "chain_not_listed", "counts": None}
    other = a.mcsa_expectation(entries, "1ABC", {"A": []})
    assert other == {"lookupEntries": [], "chains": {"A": {"coverage": "pdb_not_in_snapshot", "counts": None}}}


def test_reaction_expectations_of_the_archived_set_and_public_structures():
    active = json.loads(_need(REACTION_ARCHIVE / "active.json").read_text())
    set_dir = REACTION_ARCHIVE / "sets" / active["set_hash"]
    structures = {key: _need(FIXTURES / name) for key, (name, _label) in a.INPUTS.items()}
    plans = {item["id"]: item for item in a.reaction_expectations(set_dir, structures)}
    s9i, a30, a4i = plans["s9i"], plans["a30"], plans["a4i"]
    assert s9i["lookupEntries"] == [282] and a30["lookupEntries"] == [175] and a4i["lookupEntries"] == [389, 458]
    assert s9i["chains"] == [{"chain": "A", "accession": {"suggestion": "P36507"}}, {"chain": "B", "accession": None}]
    assert s9i["expect"]["chains"] == {
        "A": {"coverage": "covered", "entries": [282], "rows": {"282/0": "matched", "282/1": "matched"},
              "uniprot": ["checked", None]},
        "B": {"coverage": "chain_not_listed", "uniprot": ["not_checked", "accession_not_given"]}}
    assert a30["expect"]["chains"]["A"]["rows"] == {"175/1": "matched", "175/2": "matched", "175/4": "matched"}
    assert a30["expect"]["chains"]["B"]["rows"] == {"175/0": "matched", "175/3": "matched", "175/5": "matched"}
    assert a4i["counts"] == {"A": {"matched": 6, "unmatched": 0, "conflict": 0}, "B": None}
    assert not any(item["unknownRows"] for item in plans.values())
    assert all(item["expect"]["nullResult"] is False for item in plans.values())


def test_reaction_expectations_refuse_a_chain_the_file_does_not_have(tmp_path):
    active = json.loads(_need(REACTION_ARCHIVE / "active.json").read_text())
    structures = {key: FIXTURES / name for key, (name, _label) in a.INPUTS.items()}
    links = [{"id": "x", "structure": "a30", "pdbId": "1A30", "chains": ("A", "Z"), "suggest": set()}]
    with pytest.raises(ValueError, match="no polymer chain"):
        a.reaction_expectations(REACTION_ARCHIVE / "sets" / active["set_hash"], structures, links)


def test_reaction_copy_is_checked_against_the_source(tmp_path):
    source = tmp_path / "source"
    (source / "sets/abc").mkdir(parents=True)
    (source / "active.json").write_text(json.dumps({"schema": "reaction_active@1", "set_hash": "abc"}))
    (source / "sets/abc/manifest.json").write_text("{}")
    empty = tmp_path / "empty"
    empty.mkdir()
    copied = a.ensure_reaction_copy(source, empty)
    assert copied["status"] == "pass" and copied["copiedBy"] == "branch" and copied["setHash"] == "abc"
    assert copied["sourceDigestBefore"] == copied["sourceDigestAfter"] == copied["copyDigest"]
    assert a.ensure_reaction_copy(source, empty)["copiedBy"] == "runner"      # already a copy: nothing written
    (empty / "sets/abc/manifest.json").chmod(0o644)
    (empty / "sets/abc/manifest.json").write_text('{"changed": true}')
    assert a.ensure_reaction_copy(source, empty)["status"] == "fail"
    other = tmp_path / "other"
    other.mkdir()
    (other / "stray.txt").write_text("x")
    assert a.ensure_reaction_copy(source, other)["status"] == "fail"


# ---------------------------------------------------------------------------------------------------- plan and setup
def test_import_argv_runs_the_user_command_under_the_network_guard(tmp_path):
    argv = a.import_argv(Path("/py"), Path("/code"), Path("/kbase"), tmp_path / "precedent")
    assert argv[:4] == ["/py", "-I", "-c", a.m27.NETWORK_GUARD]
    assert argv[4] == "/code/scripts/import_precedent_snapshots.py"
    assert argv[5:] == ["--from", "/kbase", "--dest", str(tmp_path / "precedent"), "--yes"]
    assert "socket.getaddrinfo = refuse" in a.m27.NETWORK_GUARD


def test_plan_is_json_without_core_forbidden_words():
    active = json.loads(_need(REACTION_ARCHIVE / "active.json").read_text())
    plan = a.build_plan(REPO, None, REACTION_ARCHIVE / "sets" / active["set_hash"])
    text = json.dumps(plan, ensure_ascii=False)
    assert json.loads(text)["schema"] == a.PLAN_SCHEMA
    assert plan["precedent"] is None and len(plan["reaction"]["links"]) == 3
    assert plan["a1"]["atoms"] == 2526 and plan["contacts"]["summary"]["rows"] == 65
    assert {key: plan["inputs"][key]["name"] for key in plan["inputs"]} == {
        key: name for key, (name, _label) in a.INPUTS.items()}
    assert not c.CORE_FORBIDDEN.search(text), "the plan would add X4 hits to the evidence"


# ---------------------------------------------------------------------------------------------------- judgement
def _plan():
    return {"a1": {"residues": 313, "atoms": 2526},
            "contacts": {"summary": {"rows": 65, "byType": {"contact": 33, "polar_contact": 7,
                                                             "hydrophobic_contact": 25}}},
            "precedent": {"links": [{"id": "l-m17", "expect": {"targets": {"P00533": {
                "status": "precedents_found", "moves": 76, "movesFlagged": None, "excluded": 66, "references": 1,
                "variants": {"WT": 3}}}}}]},
            "reaction": {"links": [{"id": "s9i", "counts": {"A": {"matched": 2, "unmatched": 0, "conflict": 0},
                                                             "B": None},
                                    "expect": {"chains": {"A": {"coverage": "covered"},
                                                          "B": {"coverage": "chain_not_listed"}}}}]}}


def _observed():
    return {"A1": {"residues": 313, "atoms": 2526},
            "A2": {"rows": 65, "byType": {"contact": 33, "polar_contact": 7, "hydrophobic_contact": 25},
                   "unmatchedRows": 0},
            "A7": {"links": {"l-m17": {"targets": {"P00533": {"status": "precedents_found", "moves": 76,
                                                              "movesFlagged": None, "excluded": 66, "references": 1,
                                                              "variants": {"WT": 3}}}}}},
            "A8": {"links": {"s9i": {"chains": {"A": {"coverage": "covered", "counts": {
                "matched": 2, "unmatched": 0, "conflict": 0}},
                "B": {"coverage": "chain_not_listed", "counts": None}}}}}}


def _row(**change):
    return {"status": "pass", "offscreenComplete": True, "externalRequestCount": 0, "providerCallsZero": True,
            **change}


def _evidence(**parts):
    names = list(a.PART_CASE)
    states = {name: {"status": "pass"} for name in names}
    states.update(parts)
    return {"parts": states, "observed": _observed()}


def _by_id(records):
    return {record["id"]: record for record in records}


def test_compare_observed_flags_each_independent_mismatch():
    assert a.compare_observed(_plan(), _observed()) == {}
    bad = _observed()
    bad["A1"]["atoms"] = 2546
    bad["A2"]["unmatchedRows"] = 1
    bad["A7"]["links"]["l-m17"]["targets"]["P00533"]["excluded"] = 0
    bad["A8"]["links"]["s9i"]["chains"]["A"]["counts"]["matched"] = 1
    problems = a.compare_observed(_plan(), bad)
    assert set(problems) == {"A1", "A2", "A7", "A8"}
    assert a.compare_observed(_plan(), {}) == {}            # nothing observed: the harness case decides


def test_case_records_map_parts_to_spec_cases():
    records = _by_id(a.case_records(_row(), _evidence(), _plan(), {}, ["x"]))
    assert list(records) == list(a.CASES) and all(r["status"] == "pass" for r in records.values())
    assert all(not c.case_problems(r) for r in records.values())
    split = _by_id(a.case_records(_row(), _evidence(**{"A5-others": {"status": "fail"},
                                                        "A7": {"status": "not_run", "blockedBy": ["A5-others"]}}),
                                  _plan(), {}, []))
    assert split["A5"]["status"] == "fail" and split["A6"]["status"] == "pass"
    assert (split["A7"]["status"], split["A7"]["reason"]) == ("not_observed", "prerequisite_failed:A5")
    assert c.cascade(split, c.FIXTURE_CASES)["A7"] == split["A7"]


def test_a_case_with_one_part_blocked_by_an_earlier_case_is_not_observed():
    """R5: A1 failed, A5-others (loaded 1FIN / 1MQ4) passed and A5-m17 (prepared 1M17) was not run for want of A1:
    A5 is not_observed prerequisite_failed:A1, never a fail of its own."""
    blocked = {name: {"status": "not_run", "blockedBy": ["A1"]} for name in ("A2", "A3", "A4", "A5-m17")}
    records = _by_id(a.case_records(_row(), _evidence(A1={"status": "fail"}, **blocked,
                                                      A6={"status": "not_run", "blockedBy": ["A1", "A5-m17"]},
                                                      A7={"status": "not_run", "blockedBy": ["A5-m17"]}),
                                    _plan(), {}, []))
    assert records["A1"]["status"] == "fail"
    for case in ("A2", "A3", "A4", "A5", "A6"):
        assert (records[case]["status"], records[case]["reason"]) == ("not_observed", "prerequisite_failed:A1"), case
    assert records["A7"]["reason"] == "prerequisite_failed:A5"           # the part name maps to its case
    assert records["A8"]["status"] == "pass"
    failed = _by_id(a.case_records(_row(), _evidence(**{"A5-m17": {"status": "not_run", "blockedBy": ["A1"]},
                                                        "A5-others": {"status": "fail"}}), _plan(), {}, []))
    assert failed["A5"]["status"] == "fail"                              # a part that failed is a fail


def test_case_records_fail_on_mismatch_unclean_row_setup_and_missing_parts():
    bad = _evidence()
    bad["observed"]["A1"]["residues"] = 333
    assert _by_id(a.case_records(_row(), bad, _plan(), {}, []))["A1"]["reason"] == "independent_expectation_mismatch"
    unclean = _by_id(a.case_records(_row(externalRequestCount=1), _evidence(), _plan(), {}, []))
    assert {r["reason"] for r in unclean.values()} == {"harness_row_not_clean"}
    setup = _by_id(a.case_records(_row(), _evidence(), _plan(),
                                  {"A7": {"status": "fail", "reason": "precedent_set_install_failed"}}, []))
    assert setup["A7"]["status"] == "fail" and setup["A7"]["reason"] == "precedent_set_install_failed"
    nothing = _by_id(a.case_records(None, None, _plan(), {}, []))
    assert {r["status"] for r in nothing.values()} == {"fail"}
    assert {r["reason"] for r in nothing.values()} == {"case_not_completed"}


def test_observations_and_tab_texts(tmp_path):
    (tmp_path / "texts").mkdir()
    (tmp_path / "texts/k.tabtext").write_text("panel text")
    evidence = {"x5": [{"ok": True, "detail": "d1"}, {"ok": False, "detail": "d2"}],
                "texts": {"knowledge@A5": "texts/k.tabtext", "gone": "texts/none.tabtext"}}
    assert a.observations(evidence) == [(True, "d1"), (False, "d2")]
    assert a.observations(None) == []
    assert a.tab_texts(tmp_path, evidence) == {"knowledge@A5": "panel text"}


def test_step_folder_is_the_folder_the_row_names_only(tmp_path):
    first, second = tmp_path / a.STEP, tmp_path / f"{a.STEP}-20261011T000000"
    for folder in (first, second):
        folder.mkdir()
        (folder / a.EVIDENCE_FILE).write_text("{}")
    assert a.step_folder({"artifacts": str(first)}) == first
    os.utime(first, (1, 1))
    assert a.step_folder({}) is None and a.step_folder(None) is None     # never another attempt's folder
    assert a.step_folder({"artifacts": str(tmp_path / "gone")}) is None


def test_evidence_of_another_plan_fails_every_case(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "install_precedent_set", lambda ctx: {"status": "fail", "networkAttempts": 0})
    monkeypatch.setattr(a, "ensure_reaction_copy", lambda source, target: {"status": "fail"})

    def flow(step, harness, mode, extra, limit=None):
        folder = tmp_path / "artifacts" / step
        folder.mkdir(parents=True)
        (folder / a.EVIDENCE_FILE).write_text(json.dumps({"planSha256": "0" * 64, "mode": mode, "run": "run_a",
                                                          "parts": {name: {"status": "pass"} for name in a.PART_CASE}}))
        return {"artifacts": str(folder), "offscreenComplete": True, "externalRequestCount": 0,
                "providerCallsZero": True}
    result = a.run(_ctx(tmp_path, flow=flow))
    reasons = {record["id"]: record["reason"] for record in result.cases}
    assert {reasons[case] for case in ("A1", "A2", "A3", "A4", "A5", "A6")} == {"evidence_not_of_this_step"}
    assert result.notes["evidenceCheck"] == {"planSha256": False, "mode": True}


def _ctx(tmp_path, phase="fixture", flow=None):
    return c.BranchContext(
        phase=phase, rehearse=False, branch="a", code=REPO, root=tmp_path, stage=tmp_path / phase,
        runs=tmp_path / "runs", reference=tmp_path / "reference", precedent=tmp_path / "precedent",
        reaction=tmp_path / "reaction", artifacts=tmp_path / "artifacts" / "a", kbase=tmp_path / "kbase",
        m15_reference=tmp_path / "m15", reaction_set=tmp_path / "set", python=Path("/py"),
        api=c.Api(), flow=flow or (lambda *args, **kwargs: None), record=lambda *args, **kwargs: None,
        child_env=lambda extra=None: {})


def test_run_has_no_live_phase(tmp_path):
    result = a.run(_ctx(tmp_path, phase="live"))
    assert result.cases == [] and result.runs == [] and "fixture phase only" in result.notes["error"]


def test_run_reports_every_case_failed_when_the_harness_leaves_no_row(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(a, "install_precedent_set", lambda ctx: {"status": "fail", "networkAttempts": 0})
    monkeypatch.setattr(a, "ensure_reaction_copy", lambda source, target: {"status": "fail"})

    def flow(step, harness, mode, extra, limit=None):
        calls.append((step, harness, mode, extra))
    result = a.run(_ctx(tmp_path, flow=flow))
    assert calls == [(a.STEP, a.HARNESS, "fixture", ["--plan", str(tmp_path / "artifacts/a/plan.json")])]
    plan = json.loads((tmp_path / "artifacts/a/plan.json").read_text())
    assert plan["precedent"] is None and plan["reaction"] is None
    statuses = {record["id"]: (record["status"], record["reason"]) for record in result.cases}
    assert statuses["A7"] == ("fail", "precedent_set_install_failed")
    assert statuses["A8"] == ("fail", "reaction_set_copy_failed")
    assert {statuses[case] for case in ("A1", "A2", "A3", "A4", "A5", "A6")} == {("fail", "case_not_completed")}
    assert result.runs == [] and result.reports_created is None and result.observations == {"X5": []}
    assert result.notes["defaultFoldersBefore"] == result.notes["defaultFoldersAfter"]


def test_branch_module_never_imports_mw_or_calls_limit_routes():
    source = Path(a.__file__).read_text()
    tree = ast.parse(source)
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "mw" not in imported
    assert "limit_approval" not in source and "raise_limits" not in source
    assert "/jev" not in source


def test_harness_file_is_present_with_its_sources_named():
    harness = REPO / "frontend/tests/offscreen" / a.HARNESS
    text = harness.read_text()
    for source in ("annotation-flow.cjs", "pocket-flow.cjs", "kinase-precedents-flow.cjs",
                   "reaction-knowledge-flow.cjs", "normal-flow.cjs"):
        assert f"copied from {source}" in text.lower(), source
    assert "m28_branch_a_plan@1" in text and "ledger-row.json" in text
    assert shutil.which("node"), "node is needed by the offscreen harness"
