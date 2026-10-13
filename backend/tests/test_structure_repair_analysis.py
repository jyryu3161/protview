"""M29 T4: the defect analysis (spec 2) on the local public structures (both water policies) and the labelled
SYNTHETIC fixtures.

Expected values come from two places that are not the product:
- ``TABLE``: the T1 / T3b independent classification (``docs/qa/m29-repair-20261013/preflight.md`` (a) and
  ``t3b-classification.tsv``: gemmi + the template XML only), verdict, classes per water policy and protein heavy
  atoms after repair;
- ``oracle()``: computed here from each ORIGINAL file's own ``_pdbx_poly_seq_scheme`` (internal gap residues and chain
  ends), ``_pdbx_unobs_or_zero_occ_atoms`` (missing side-chain atoms), ``_atom_site`` (OXT, heavy atoms) and the
  template XML read in ``test_structure_repair_common``.
"""
from __future__ import annotations

from itertools import pairwise

import gemmi
import pytest
import test_structure_repair_common as C

from mw import structure_repair as sr
from mw import structure_repair_constants as K

CHAIN, SIDE, OXT, GAP, MSE = ("chain_parts_merged", "side_chain_atoms_added", "terminal_oxt_added",
                              "internal_gap_filled", "nonstandard_replaced")
# name: (verdict strip_all, verdict keep_all, classes strip_all, classes keep_all, protein heavy atoms after repair)
TABLE = {
    "8vf6": ("in_scope", "in_scope", [CHAIN, SIDE, OXT, GAP], [CHAIN, SIDE, OXT, GAP], 4538),
    "1m17": ("in_scope", "in_scope", [OXT, GAP], [OXT, GAP], 2594),
    "1mq4": ("in_scope", "in_scope", [SIDE, OXT, GAP], [SIDE, OXT, GAP], 2160),
    "1a30": ("in_scope", "in_scope", [SIDE], [CHAIN, SIDE], 1542),
    "1a4i": ("in_scope", "in_scope", [CHAIN, OXT, GAP], [CHAIN, OXT, GAP], 4476),
    "1hsg": ("in_scope", "in_scope", [OXT], [CHAIN, OXT], 1516),
    "1s9i": ("gap_too_long", "gap_too_long", [CHAIN, OXT, GAP], [CHAIN, OXT, GAP], 5205),
    "1fin": ("atom_limit_exceeded", "atom_limit_exceeded", [CHAIN], [CHAIN], 8998),
    "1ubq": ("nothing_to_repair", "nothing_to_repair", [], [], 602),
    "1rnh": ("in_scope", "in_scope", [OXT, MSE], [OXT, MSE], 1207),
    "4ins": ("in_scope", "in_scope", [CHAIN], [CHAIN], 806),
    "1ay7": ("nothing_to_repair", "in_scope", [], [CHAIN], 1466),
    "1cll": ("in_scope", "in_scope", [SIDE, OXT], [SIDE, OXT], 1135),
}
ZERO_OCCUPANCY = {"1m17": 37, "1a4i": 20}   # T1 (a); every other structure has none


@pytest.fixture(scope="module", autouse=True)
def _root(tmp_path_factory):
    C.use_root(tmp_path_factory.mktemp("m29_t4_analysis"))


def _null(value: str) -> bool:
    return gemmi.cif.is_null(value)


def oracle(name: str) -> dict:
    block = gemmi.cif.read_string((C.FIX / f"public_{name}.cif").read_text()).sole_block()
    scheme: dict[str, list] = {}
    for row in block.find("_pdbx_poly_seq_scheme.", ["asym_id", "seq_id", "pdb_seq_num", "auth_seq_num",
                                                      "pdb_ins_code", "mon_id", "pdb_strand_id"]):
        scheme.setdefault(row[0], []).append({"label": int(row[1]), "auth": int(row[2]), "seen": not _null(row[3]),
                                              "icode": "" if _null(row[4]) else row[4], "name": row[5],
                                              "chain": row[6]})
    gaps, ends, last_observed = [], {}, []
    for asym, rows in scheme.items():
        seen = [i for i, row in enumerate(rows) if row["seen"]]
        if not seen:
            continue
        ends[rows[0]["chain"]] = (seen[0] == 0, seen[-1] == len(rows) - 1)
        last_observed.append((rows[seen[-1]]["chain"], rows[seen[-1]]["auth"], rows[seen[-1]]["icode"]))
        for a, b in pairwise(seen):
            if b - a > 1:
                gaps.append((rows[a]["chain"], rows[b]["auth"], [(row["auth"], row["icode"], asym, row["label"],
                                                                  row["name"]) for row in rows[a + 1:b]]))
    side: dict[tuple, set] = {}
    for row in block.find("_pdbx_unobs_or_zero_occ_atoms.", ["polymer_flag", "occupancy_flag", "auth_asym_id",
                                                             "auth_seq_id", "PDB_ins_code", "auth_atom_id"]):
        if row[0] == "Y" and row[1] == "1":
            side.setdefault((row[2], int(row[3]), "" if _null(row[4]) else row[4]), set()).add(row[5])
    polymer = set(scheme)
    atoms: dict[tuple, set] = {}
    for row in block.find("_atom_site.", ["label_asym_id", "auth_asym_id", "auth_seq_id", "pdbx_PDB_ins_code",
                                          "label_atom_id", "type_symbol", "pdbx_PDB_model_num"]):
        if row[0] in polymer and row[5] not in ("H", "D") and row[6] == "1":
            atoms.setdefault((row[1], int(row[2]), "" if _null(row[3]) else row[3]), set()).add(row[4])
    oxt = [end for end in last_observed if "OXT" not in atoms[end]]
    gap_heavy = sum(len(C.template_heavy_names(r[4])) for _, _, residues in gaps for r in residues)
    heavy = sum(len(names) for names in atoms.values())
    return {"gaps": gaps, "ends": ends, "side": side, "oxt": sorted(oxt),
            "after": heavy + sum(len(v) for v in side.values()) + len(oxt) + gap_heavy}


@pytest.mark.parametrize("waters", C.WATERS)
@pytest.mark.parametrize("name", C.PUBLIC)
def test_public_structures_classify_as_the_independent_table_and_oracle(name, waters):
    analysis = sr.analyze(C.public(name, waters))
    verdict_strip, verdict_keep, classes_strip, classes_keep, after = TABLE[name]
    verdict = verdict_strip if waters == "strip_all" else verdict_keep
    assert analysis["reason_code"] == (None if verdict == "in_scope" else verdict)
    assert analysis["repairable"] is (verdict == "in_scope")
    assert analysis["classes"] == (classes_strip if waters == "strip_all" else classes_keep)
    assert analysis["protein_heavy_atoms_after"] == after
    assert analysis["zero_occupancy_input_atoms"]["count"] == ZERO_OCCUPANCY.get(name, 0)
    expected = oracle(name)
    assert expected["after"] == after
    got_gaps = [(gap["chain_auth"], gap["before_residue"]["seq_auth"],
                 [(r["seq_auth"], r["icode"], r["chain_label"], r["seq_label"], r["resname"]) for r in gap["residues"]])
                for gap in analysis["defects"]["gaps"]]
    assert got_gaps == expected["gaps"]
    assert all(gap["length"] == len(gap["residues"]) for gap in analysis["defects"]["gaps"])
    assert analysis["expected_added_residues"] == sum(len(g[2]) for g in expected["gaps"])
    got_side = {(item["residue"]["chain_auth"], item["residue"]["seq_auth"], item["residue"]["icode"]):
                set(item["missing_atoms"]) for item in analysis["defects"]["side_chain_residues"]}
    assert got_side == expected["side"]
    assert sorted((item["residue"]["chain_auth"], item["residue"]["seq_auth"], item["residue"]["icode"])
                  for item in analysis["defects"]["terminal_oxt"]) == expected["oxt"]
    assert {end["chain_auth"]: (end["first_is_sequence_start"], end["last_is_sequence_end"])
            for end in analysis["chain_ends"]} == expected["ends"]
    differs = any(False in pair for pair in expected["ends"].values())
    assert (K.RP4 in analysis["statements"]) is differs
    assert analysis["statements"][:2] == [K.RP1, K.RP2]


def test_the_two_t1_findings_on_8vf6_and_the_mse_of_1rnh():
    eight = sr.analyze(C.public("8vf6", "keep_all"))
    assert eight["defects"]["chain_parts"] == [{"chain_auth": "A", "parts": 3}, {"chain_auth": "B", "parts": 3}]
    assert [(g["chain_auth"], g["after_residue"]["seq_auth"], g["before_residue"]["seq_auth"], g["length"])
            for g in eight["defects"]["gaps"]] == [("A", 272, 286, 13), ("B", 273, 285, 11)]
    assert (eight["expected_added_residues"], eight["expected_added_heavy_atoms"]) == (24, 266)
    assert eight["statements"] == [K.RP1, K.RP2, K.RP3, K.RP4, K.RP6]
    rnh = sr.analyze(C.public("1rnh"))
    assert [(n["residue"]["seq_auth"], n["residue"]["resname"], n["to_resname"])
            for n in rnh["defects"]["nonstandard"]] == [(47, "MSE", "MET"), (50, "MSE", "MET"), (142, "MSE", "MET")]
    assert rnh["statements"] == [K.RP1, K.RP2, K.RP4, K.RP5]


def test_refusals_list_every_blocker_and_report_the_first():
    s9i = sr.analyze(C.public("1s9i"))
    assert [(b["reason_code"], b["chain_auth"], b["residue"]["seq_auth"], b["detail"]["length"])
            for b in s9i["blockers"]] == [("gap_too_long", "A", 313, 27), ("gap_too_long", "B", 316, 34)]
    assert sr.refusal(s9i) == {"reason_code": "gap_too_long", "blockers": s9i["blockers"]}
    fin = sr.analyze(C.public("1fin"))
    assert fin["blockers"] == [{"reason_code": "atom_limit_exceeded",
                                "detail": {"protein_heavy_atoms_after": 8998, "limit": 6000}}]
    ubq = sr.analyze(C.public("1ubq"))
    assert ubq["blockers"] == [{"reason_code": "nothing_to_repair", "detail": {}}] and ubq["classes"] == []
    assert sr.refusal(sr.analyze(C.public("8vf6"))) is None


SYNTHETIC_REFUSALS = {
    "synthetic-chain-identity-duplicate.cif": ("chain_identity_duplicate", None),
    "synthetic-unsupported-residue.cif": ("unsupported_residue", 20),
    "synthetic-unexpected-atoms.cif": ("unexpected_atoms", 12),
    "synthetic-backbone-atoms-missing.cif": ("backbone_atoms_missing", 30),
    "synthetic-gap-listing-missing.cif": ("gap_listing_missing", 33),
    "synthetic-chain-break.pdb": ("m7_condition_unsupported", 40),
}


@pytest.mark.parametrize("file", sorted(SYNTHETIC_REFUSALS))
def test_synthetic_fixtures_reach_their_refusal(file):
    analysis = sr.analyze(C.synthetic(file))
    code, residue = SYNTHETIC_REFUSALS[file]
    first = analysis["blockers"][0]
    assert (analysis["repairable"], analysis["reason_code"], first["reason_code"]) == (False, code, code)
    assert (first.get("residue") or {}).get("seq_auth") == residue
    order = [K.REFUSAL_REASONS.index(b["reason_code"]) for b in analysis["blockers"]]
    assert order == sorted(order)


def test_synthetic_blocker_details():
    duplicate = sr.analyze(C.synthetic("synthetic-chain-identity-duplicate.cif"))
    assert duplicate["blockers"][0] == {"reason_code": "chain_identity_duplicate", "chain_auth": "A",
                                        "detail": {"label_chains": ["A", "B"]}}
    unexpected = sr.analyze(C.synthetic("synthetic-unexpected-atoms.cif"))
    assert [(b["residue"]["seq_auth"], b["detail"]["atoms"]) for b in unexpected["blockers"]] == [
        (12, ["XG2"]), (14, ["OG1"])]
    unsupported = sr.analyze(C.synthetic("synthetic-unsupported-residue.cif"))["blockers"][0]
    assert (unsupported["residue"]["resname"], unsupported["detail"]) == ("SEP", {"resname": "SEP", "in_gap": False})
    backbone = sr.analyze(C.synthetic("synthetic-backbone-atoms-missing.cif"))["blockers"][0]
    assert backbone["detail"] == {"missing": ["O"]}
    listing = sr.analyze(C.synthetic("synthetic-gap-listing-missing.cif"))["blockers"][0]
    assert (listing["detail"]["after_residue"]["seq_auth"], listing["detail"]["missing_label_positions"]) == (
        29, [30, 31, 32])
    broken = sr.analyze(C.synthetic("synthetic-chain-break.pdb"))
    assert broken["blockers"][0]["detail"]["m7_reason"] == "peptide_geometry"
    assert sr.refusal(broken)["m7_reason"] == "peptide_geometry"


STANDARD_NAMES = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS", "MET", "PHE",
                  "PRO", "SER", "THR", "TRP", "TYR", "VAL"}   # spec 2.2 (20 standard names), copied
SPEC_ORDER = ("chain_identity_duplicate", "unsupported_residue", "unexpected_atoms", "backbone_atoms_missing",
              "gap_listing_missing", "gap_too_long", "m7_condition_unsupported", "atom_limit_exceeded")


def _file_view(file: str) -> dict:
    """From the SYNTHETIC mmCIF text only: the listed internal gap (rows between the first and last observed label),
    the polymer residues whose name is not standard, and whether the file carries _entity_poly_seq."""
    block = gemmi.cif.read_string((C.SR_FIX / file).read_text()).sole_block()
    observed, unsupported = set(), set()
    for row in block.find("_atom_site.", ["group_PDB", "label_seq_id", "label_comp_id", "auth_seq_id"]):
        if row[0] == "ATOM" and not _null(row[1]):
            observed.add(int(row[1]))
            if row[2] not in STANDARD_NAMES:
                unsupported.add((int(row[3]), row[2]))
    listed = [(int(r[0]), r[1], int(r[2])) for r in block.find("_pdbx_unobs_or_zero_occ_residues.",
                                                                 ["auth_seq_id", "label_comp_id", "label_seq_id"])]
    gap = [row for row in listed if min(observed) < row[2] < max(observed)]
    return {"gap": gap, "unsupported": sorted(unsupported), "after_gap": min(n for n in observed if n > gap[-1][2])
            if gap else None, "sequence_rows": len(block.find("_entity_poly_seq.", ["num"]))}


@pytest.mark.parametrize("file", ["synthetic-gap-20.cif", "synthetic-gap-21.cif",
                                  "synthetic-gap-21-before-unsupported.cif"])
def test_gap_length_boundary_and_a_gap_before_an_unsupported_residue_are_listed(file):
    view = _file_view(file)
    expected_codes = [code for code in SPEC_ORDER
                      if (code == "unsupported_residue" and view["unsupported"])
                      or (code == "gap_too_long" and len(view["gap"]) > 20)]
    analysis = sr.analyze(C.synthetic(file))
    assert [b["reason_code"] for b in analysis["blockers"] if b["reason_code"] != "nothing_to_repair"] == expected_codes
    assert analysis["reason_code"] == (expected_codes[0] if expected_codes else None)
    assert analysis["repairable"] is (not expected_codes)
    (gap,) = analysis["defects"]["gaps"]
    assert [(r["seq_auth"], r["resname"], r["seq_label"]) for r in gap["residues"]] == view["gap"]
    assert (gap["length"], gap["before_residue"]["seq_auth"]) == (len(view["gap"]), view["after_gap"])
    if len(view["gap"]) > 20:
        too_long = next(b for b in analysis["blockers"] if b["reason_code"] == "gap_too_long")
        assert (too_long["residue"]["seq_auth"], too_long["detail"]["length"]) == (view["after_gap"], len(view["gap"]))
    else:
        assert analysis["classes"] == [GAP]
    assert [(b["residue"]["seq_auth"], b["residue"]["resname"]) for b in analysis["blockers"]
            if b["reason_code"] == "unsupported_residue"] == view["unsupported"]


def test_chain_ends_stay_null_without_a_sequence_and_rp4_is_not_added():
    file = "synthetic-no-sequence-c-tail.cif"
    view = _file_view(file)
    assert view["sequence_rows"] == 0   # the file carries no _entity_poly_seq
    inputs = C.synthetic(file)
    analysis = sr.analyze(inputs)
    assert (analysis["repairable"], analysis["classes"]) == (True, [OXT])
    assert [(e["observed_last"]["seq_auth"], e["first_is_sequence_start"], e["last_is_sequence_end"])
            for e in analysis["chain_ends"]] == [(74, None, None)]
    assert K.RP4 not in analysis["statements"]
    # the record path keeps the same null flags and no RP4 (built without new atoms: only the record rule is tested)
    _raw, record = sr.build_repaired(inputs, [])
    assert [(e["first_is_sequence_start"], e["last_is_sequence_end"]) for e in record["chain_ends"]] == [(None, None)]
    assert K.RP4 not in record["limitations"]


def test_pdb_format_gap_is_determined_from_remark_465_seqres_and_cn_distance():
    analysis = sr.analyze(C.synthetic("synthetic-gap.pdb"))
    assert (analysis["repairable"], analysis["classes"]) == (True, [GAP])
    (gap,) = analysis["defects"]["gaps"]
    assert [(r["seq_auth"], r["icode"], r["chain_label"], r["seq_label"], r["resname"]) for r in gap["residues"]] == [
        (30, "", "Axp", None, "ILE"), (31, "", "Axp", None, "GLN"), (32, "", "Axp", None, "ASP")]
    assert (gap["after_residue"]["seq_auth"], gap["before_residue"]["seq_auth"]) == (29, 33)
    assert [(e["first_is_sequence_start"], e["last_is_sequence_end"]) for e in analysis["chain_ends"]] == [(True, True)]


@pytest.mark.parametrize("edit", ["no_listing", "listing_differs_from_seqres"])
def test_pdb_format_gap_without_a_matching_listing_is_gap_listing_missing(edit):
    text = (C.SR_FIX / "synthetic-gap.pdb").read_text()
    lines = text.splitlines()
    if edit == "no_listing":
        lines = [line for line in lines if not line.startswith("REMARK 465")]
    else:
        lines = [line.replace("GLN A    31", "GLY A    31") for line in lines]
    inputs = C.prepared(("\n".join(lines) + "\n").encode(), "pdb")[0]
    analysis = sr.analyze(inputs)
    assert analysis["reason_code"] == "gap_listing_missing"
    assert analysis["blockers"][0]["residue"]["seq_auth"] == 33


def test_pdb_format_rendering_of_1rnh_reads_its_hetatm_mse_as_polymer():
    """The real 1RNH written as PDB text by gemmi in this test (no REMARK 465): MSE is HETATM in a polymer entity."""
    raw = C.structure((C.FIX / "public_1rnh.cif").read_bytes()).make_pdb_string().encode()
    analysis = sr.analyze(C.prepared(raw, "pdb")[0])
    assert analysis["repairable"] and analysis["classes"] == [OXT, MSE]
    assert [n["residue"]["chain_label"] for n in analysis["defects"]["nonstandard"]] == ["Axp"] * 3
    # without REMARK 465 the file does not determine the chain ends: no claim either way
    assert [(e["first_is_sequence_start"], e["last_is_sequence_end"]) for e in analysis["chain_ends"]] == [(None, None)]
    assert K.RP4 not in analysis["statements"]


def test_load_inputs_refuses_other_objects():
    inputs, run = C.prepared((C.FIX / "public_1hsg.cif").read_bytes(), "cif")
    selection = run.store.load(inputs.prepared_structure)["coordinates"]
    for handle in (selection, "obj://run_other/prepared_structure/" + "0" * 64):
        with pytest.raises(sr.ToolFailure) as caught:
            sr.load_inputs(run.store, handle)
        assert caught.value.detail["reason_code"] == "structure_invalid"
