"""M20 T2 pure mutation-candidate module (``mw.mutation_candidates``, ``mw.mutation_constants``).

Inputs: the SYNTHETIC fixtures in ``fixtures/mutation/`` (hand-placed coordinates; see SYNTHETIC-PROVENANCE.md) with
their independent oracle ``expected.json`` (built by parsing the written bytes and brute-force ``math.dist``; no gemmi,
no ``mw`` code), the public 1MQ4 (+ ADP, a reference FIXTURE set for the M15 map and M16 annotation) and 1HSG (+ MK1)
structures with the numpy values recorded in docs/qa/m20-mutations-20261003/preflight.txt, and SYNTHETIC
pocket_set / numbering map / annotation contents built here (function names contain ``synthetic``).

Structures go through the product path (``load_structure`` -> ``prepare_structure`` with config defaults ->
``structural._parse``) so the pure module sees exactly what the tool will see. The module itself never touches the
store. Oracle distances are compared with ``abs <= 1e-9``; shell / metal / disulfide boundary membership is exact.
"""
from __future__ import annotations

import ast
import copy
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest
from reference_fixture_set import build_fixture_set

from mw import mutation_candidates as mc
from mw import mutation_constants as K
from mw import reaction_knowledge_constants as RKC
from mw import reference_snapshots as rs
from mw.core.handles import canonical_json
from mw.tools.registry import ToolContext
from mw.tools.structural import _parse, structure_residues
from mw.workspace import build_registry, new_run

FIX = Path(__file__).resolve().parent / "fixtures"
MUT = FIX / "mutation"
CIF = MUT / "synthetic-mutation-fixture.cif"
PDB = MUT / "synthetic-mutation-fixture-nolabel.pdb"
ORACLE = json.loads((MUT / "expected.json").read_text())["files"]
TOL = 1e-9
REPO = Path(__file__).resolve().parents[2]

# spec 11, copied here verbatim (not imported) so a drift in the constants module fails.
SPEC_LIMITATIONS = [
    "후보는 위치와 바꿀 잔기의 조합 목록이며 구조 모델링·에너지·점수를 계산하지 않았다.",
    "이 목록은 변이의 효과(안정성·결합·활성)를 뜻하지 않으며 순위나 추천이 아니다.",
    ("보호 잔기는 사용자 지정·KLIFS 주요 부위·금속 근접·이황화 결합 기준으로만 판정했고 촉매 잔기 데이터베이스는 "
     "사용하지 않았다(없음)."),
    "거리는 준비된 구조의 저장 좌표에서 계산한 중원자 사이 최소 거리(Å)이며 결합이나 상호작용을 뜻하지 않는다.",
    "바꿀 히스티딘의 양성자 상태와 변이 구조의 형태는 정하지 않았다.",
]


# --- helpers ---------------------------------------------------------------------------------------------------------

class Prepared:
    """A prepared structure loaded through the product path, plus its parsed model and residue lists."""

    def __init__(self, tmp_path: Path, path: Path, name: str) -> None:
        self.run = new_run(tmp_path / "runs", run_id=name, registry=build_registry())
        structure = self.run.call("load_structure", {"source": str(path), "model_index": 0}).handle
        self.handle = self.run.call("prepare_structure", {"structure": structure}).handle
        self.st = _parse(ToolContext(store=self.run.store, call_id="test"), self.handle)
        listing = structure_residues(self.run.store, self.handle)
        self.residues, self.ligands = listing["residues"], listing["ligands"]
        self.polymer = [r for r in self.residues if r["category"] == "polymer"]

    def args(self, **kw):
        sources = kw.pop("sources", {})
        return {"structure": self.handle,
                "sources": {"pocket": sources.get("pocket"), "ligand_shell": sources.get("ligand_shell"),
                            "residues": sources.get("residues", [])}, **kw}

    def normalize(self, args):
        return mc.normalize_request(args, self.residues, self.ligands)

    def build(self, args, **objects):
        content = mc.build_candidate_set(self.handle, self.st, self.normalize(args), **objects)
        assert mc.validated_set(content) is content
        return content

    def ref(self, label: str, *, labels: bool = False) -> dict:
        """Residue reference from a ``"RES CHAINSEQ[ICODE]"`` oracle label (5 fields, or all 7 with ``labels``)."""
        found = [r for r in self.residues if name(r) == label]
        assert len(found) == 1, label
        keys = K.IDENTITY_FIELDS if labels else K.REFERENCE_REQUIRED
        return {k: found[0][k] for k in keys}


def name(residue: dict) -> str:
    return f"{residue['resname']} {residue['chain_auth']}{residue['seq_auth']}{residue['icode']}"


def names(content, predicate=lambda p: True) -> list[str]:
    return [name(p["residue"]) for p in content["positions"] if predicate(p)]


def position(content, label):
    found = [p for p in content["positions"] if name(p["residue"]) == label]
    assert len(found) == 1, label
    return found[0]


def rejected(fn, reason_code: str):
    with pytest.raises(mc.MutationInvalid) as info:
        fn()
    assert info.value.reason_code == reason_code, info.value.message
    assert info.value.detail["reason_code"] == reason_code
    return info.value


def oracle_rows(file: str) -> dict[str, dict]:
    return {name(row["residue"]): row for row in ORACLE[file]["polymer_residues"]}


@pytest.fixture
def cif(tmp_path):
    return Prepared(tmp_path, CIF, "run_cif")


@pytest.fixture
def pdb(tmp_path):
    return Prepared(tmp_path, PDB, "run_pdb")


LIG_A = {"model_number": 1, "chain_auth": "A", "seq_auth": 101, "icode": "", "resname": "LIG"}
LIG_B = {"model_number": 1, "chain_auth": "B", "seq_auth": 101, "icode": "", "resname": "LIG"}


def every_polymer(prep: Prepared) -> list[dict]:
    return [{k: r[k] for k in K.REFERENCE_REQUIRED} for r in prep.polymer]


# --- constants -------------------------------------------------------------------------------------------------------

def test_closed_sets_limits_and_sentences_match_the_spec():
    assert list(K.LIMITATIONS) == SPEC_LIMITATIONS      # v1 (stored v1 sets): byte for byte unchanged
    assert K.SOURCE_KINDS == ("pocket", "ligand_shell", "user")
    assert K.PROTECTION_REASONS == ("user_protected", "klifs_key_site", "metal_contact", "disulfide_cys")
    assert K.EXCLUSION_REASONS == ("non_standard_residue", "user_protected", "klifs_key_site", "metal_contact",
                                   "disulfide_cys", "no_allowed_alternative")
    assert K.ADMISSION_REASON_CODES == (
        "unknown_field", "structure_invalid", "no_position_source", "argument_invalid", "allowed_residues_invalid",
        "residue_invalid", "duplicate_residue", "protect_release_conflict", "ligand_required", "ligand_invalid",
        "pocket_set_invalid", "structure_mismatch", "pocket_rank_invalid", "pocket_residue_mismatch",
        "numbering_map_invalid", "annotation_invalid", "catalytic_annotation_invalid", "annotation_map_mismatch")
    assert (K.MAX_POSITIONS, K.MAX_LIST) == (400, 400)
    assert (K.LIGAND_SHELL_RADIUS_DEFAULT_A, K.LIGAND_SHELL_RADIUS_RANGE_A) == (5.0, (1.0, 12.0))
    assert (K.METAL_CONTACT_DEFAULT_A, K.METAL_CONTACT_RANGE_A, K.DISULFIDE_SG_A) == (3.0, (1.0, 5.0), 2.5)
    assert K.PROTECTION_CHECK_KEYS == ("user_list", "klifs_key_sites", "metal_contact", "disulfide",
                                       "catalytic_residue_database")
    assert K.ONE_LETTER_ORDER == "ACDEFGHIKLMNPQRSTVWY"
    assert sorted(K.STANDARD_ONE_LETTER.values()) == list(K.ONE_LETTER_ORDER)
    assert K.MAPPED_RESNAMES == {"HID": "HIS", "HIE": "HIS", "HIP": "HIS", "HSD": "HIS", "HSE": "HIS", "HSP": "HIS",
                                 "CYX": "CYS", "ASH": "ASP", "GLH": "GLU", "LYN": "LYS"}


def test_v2_closed_sets_orders_and_sentences_match_the_m26_spec():
    # M26 spec 8.1-8.4 / 8.6, copied here verbatim (not imported) so a drift in the constants module fails.
    assert (K.METHOD_VERSION, K.METHOD_VERSION_V2) == ("mw.mutation_candidates/v1", "mw.mutation_candidates/v2")
    assert K.ARG_KEYS == ("structure", "sources", "ligand", "allowed_residues", "protected_residues",
                          "released_residues", "metal_contact_A", "numbering_map", "annotation", "catalytic_annotation")
    assert K.PROTECTION_REASONS_V2 == ("user_protected", "klifs_key_site", "metal_contact", "disulfide_cys",
                                       "catalytic_residue")
    assert K.EXCLUSION_REASONS_V2 == ("non_standard_residue", "user_protected", "klifs_key_site", "metal_contact",
                                      "disulfide_cys", "catalytic_residue", "no_allowed_alternative")
    assert (len(K.EXCLUSION_REASONS), len(K.EXCLUSION_REASONS_V2)) == (6, 7)
    third = {"checked": "보호 잔기는 사용자 지정·KLIFS 주요 부위·금속 근접·이황화 결합·M-CSA 촉매 잔기 주석 기준으로만 판정했다.",
             "not_checked": ("보호 잔기는 사용자 지정·KLIFS 주요 부위·금속 근접·이황화 결합 기준으로만 판정했고 M-CSA 촉매 "
                             "잔기 주석은 주지 않았거나 일부 체인만 다뤘다(검사하지 않은 부분은 '없음'이 아니다).")}
    assert set(K.LIMITATIONS_V2) == {"checked", "not_checked"}
    for status, sentence in third.items():
        assert list(K.LIMITATIONS_V2[status]) == [*SPEC_LIMITATIONS[:2], sentence, *SPEC_LIMITATIONS[3:]]
    assert K.CATALYTIC_CHECK_KEYS == ("status", "reason", "annotation", "covered_chains", "uncovered_chains",
                                      "matched_rows", "conflict_rows", "unmatched_rows", "conflicts", "unmatched")
    assert K.CATALYTIC_ITEM_KEYS == ("chain_auth", "mcsa_id", "residue_index", "reason", "residue", "listed")
    assert K.CATALYTIC_LISTED_KEYS == ("chain_name", "resid", "auth_resid", "code")
    assert K.CATALYTIC_ENTRY_KEYS == ("mcsa_id", "residue_index", "is_reference")
    assert (K.CATALYTIC_NOT_GIVEN_REASON, K.CATALYTIC_NOT_COVERED_REASON) == ("annotation_not_given",
                                                                              "chains_not_covered")
    assert K.CATALYTIC_LIST_TOO_LONG == "catalytic_list_too_long"
    # the copies of the M26 closed sets equal the M26 constants module (mutation_constants imports nothing)
    assert K.CATALYTIC_UNCOVERED_COVERAGE == RKC.M20_UNCOVERED_COVERAGE == (
        "chain_not_listed", "pdb_not_in_snapshot", "not_checked", "not_in_annotation")
    assert K.MAX_CATALYTIC_LIST == RKC.MAX_M20_CATALYTIC_LIST == 400
    assert K.CATALYTIC_CONFLICT_REASONS == RKC.CONFLICT_REASONS
    assert K.CATALYTIC_UNMATCHED_REASONS == RKC.UNMATCHED_REASONS
    assert (K.CATALYTIC_MATCHED, K.CATALYTIC_UNMATCHED, K.CATALYTIC_CONFLICT) == RKC.ROW_STATUSES
    assert K.CATALYTIC_COVERED == RKC.COVERED and set(RKC.COVERAGE) - {RKC.COVERED} < set(
        K.CATALYTIC_UNCOVERED_COVERAGE)
    assert K.IDENTITY_FIELDS == RKC.RESIDUE_FIELDS


def test_server_modules_import_no_heavy_chemistry_package():
    allowed = {"__future__", "math", "typing", "numpy", "mutation_constants", "tools.structural"}
    for module in ("mutation_constants.py", "mutation_candidates.py"):
        tree = ast.parse((REPO / "backend" / "mw" / module).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert {alias.name for alias in node.names} <= allowed, module
            elif isinstance(node, ast.ImportFrom):
                assert node.module in allowed, (module, node.module)
    code = ("import sys, mw.mutation_candidates, mw.mutation_constants; "
            "print(sorted(m for m in ('rdkit', 'meeko', 'MDAnalysis', 'openmm', 'prolif') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO / "backend", capture_output=True, text=True,
                         check=True)
    assert out.stdout.strip() == "[]"
    constants = ast.parse((REPO / "backend" / "mw" / "mutation_constants.py").read_text())
    assert [n.module for n in ast.walk(constants) if isinstance(n, ast.ImportFrom)] == ["__future__"]


# --- ligand shell and distances (oracle: expected.json) ---------------------------------------------------------------

@pytest.mark.parametrize("radius", [1.0, 4.0, 5.0, 12.0])
def test_ligand_shell_matches_the_brute_force_oracle_inclusive(cif, radius):
    content = cif.build(cif.args(sources={"ligand_shell": {"radius_A": radius}}, ligand=LIG_A))
    assert names(content) == ORACLE[CIF.name]["derived"]["shell"]["LIG A101"][f"{radius}"]
    rows = oracle_rows(CIF.name)
    for p in content["positions"]:
        assert p["sources"] == [{"kind": "ligand_shell", "radius_A": radius}]
        assert abs(p["ligand_min_distance_A"] - rows[name(p["residue"])]["ligand_min_distance_A"]["LIG A101"]) <= TOL
    assert content["null_result"] is (not content["positions"])


def test_shell_boundaries_hydrogens_and_hetatm_residues(cif):
    content = cif.build(cif.args(sources={"ligand_shell": {}}, ligand=LIG_A))   # default 5.0
    assert content["parameters"]["sources"]["ligand_shell"] == {"radius_A": 5.0}
    assert position(content, "HID A6")["ligand_min_distance_A"] == 5.0          # exactly the radius: inside
    assert "VAL A7" not in names(content)                                       # 5.001
    assert abs(position(content, "PHE A15")["ligand_min_distance_A"] - 4.5) <= TOL   # its H at 2.0 does not count
    assert "THR A16" not in names(content)                                      # LIG H4 at 4.4 does not count
    assert "MSE CC9" not in names(content)                                      # HETATM: never a position
    assert content["ligand"] == {"residue": cif.ref("LIG A101", labels=True), "heavy_atom_count": 3}


def test_ligand_distance_on_every_position_and_null_without_ligand(cif):
    user = [cif.ref("GLY A1"), cif.ref("LEU B10"), cif.ref("ASN B13")]
    rows = oracle_rows(CIF.name)
    content = cif.build(cif.args(sources={"residues": user}, ligand=LIG_B))
    for p in content["positions"]:
        assert abs(p["ligand_min_distance_A"] - rows[name(p["residue"])]["ligand_min_distance_A"]["LIG B101"]) <= TOL
    bare = cif.build(cif.args(sources={"residues": user}))
    assert [p["ligand_min_distance_A"] for p in bare["positions"]] == [None, None, None]
    assert bare["ligand"] is None and bare["parameters"]["ligand"] is None


# --- protection -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("prep_name", ["cif", "pdb"])
@pytest.mark.parametrize("threshold", [1.0, 3.0, 5.0])
def test_metal_contact_matches_the_oracle(request, prep_name, threshold):
    prep = request.getfixturevalue(prep_name)
    oracle = ORACLE[CIF.name if prep_name == "cif" else PDB.name]
    content = prep.build(prep.args(sources={"residues": every_polymer(prep)}, metal_contact_A=threshold))
    assert names(content, lambda p: "metal_contact" in p["protection"]["reasons"]) == \
        oracle["derived"]["metal_contact"][f"{threshold}"]
    rows = {name(r["residue"]): r for r in oracle["polymer_residues"]}
    for p in content["positions"]:
        metal = p["protection"]["metal"]
        if metal is None:
            assert rows[name(p["residue"])]["nearest_metal"]["min_distance_A"] > threshold
            continue
        expected = rows[name(p["residue"])]["nearest_metal"]
        assert abs(metal["min_distance_A"] - expected["min_distance_A"]) <= TOL
        assert metal["metal_residue"] == expected["metal_residue"]
    check = content["protection_checks"]["metal_contact"]
    assert check == {"status": "checked", "threshold_A": threshold, "metal_residues": 2, "metal_names": ["NA", "ZN"]}
    if threshold == 3.0:
        assert position(content, "SER A3")["protection"]["metal"]["min_distance_A"] == 3.0   # inclusive
        assert "metal_contact" not in position(content, "LYS A11")["protection"]["reasons"]  # altloc B 3.5 kept
        assert "metal_contact" not in position(content, "ASN A13")["protection"]["reasons"]  # CD is not a metal
        assert "metal_contact" not in position(content, "GLN A14")["protection"]["reasons"]  # water


@pytest.mark.parametrize("prep_name", ["cif", "pdb"])
def test_disulfide_matches_the_oracle_including_tie_and_variant_name(request, prep_name):
    prep = request.getfixturevalue(prep_name)
    oracle = ORACLE[CIF.name if prep_name == "cif" else PDB.name]
    content = prep.build(prep.args(sources={"residues": every_polymer(prep)}))
    flagged = names(content, lambda p: "disulfide_cys" in p["protection"]["reasons"])
    assert sorted(flagged) == sorted(oracle["derived"]["disulfide_cys_residues"])
    for p in content["positions"]:
        expected = {name(r["residue"]): r for r in oracle["polymer_residues"]}[name(p["residue"])]
        partner = expected["disulfide_partner"]
        assert p["protection"]["disulfide_partner"] == (partner["residue"] if partner else None)
    assert position(content, "CYS B22")["protection"]["disulfide_partner"]["chain_auth"] == "A"   # tie: file order
    assert "disulfide_cys" not in position(content, "CYX B8")["protection"]["reasons"]
    assert content["protection_checks"]["disulfide"] == {"status": "checked", "threshold_A": 2.5,
                                                         "pairs": len(oracle["disulfide_pairs_le_2.5A"])}


def test_standard_names_mapped_names_and_non_standard(cif):
    content = cif.build(cif.args(sources={"residues": every_polymer(cif)}))
    rows = oracle_rows(CIF.name)
    for p in content["positions"]:
        assert (p["standard_resname"], p["one_letter"]) == (rows[name(p["residue"])]["standard_resname"],
                                                            rows[name(p["residue"])]["one_letter"])
    mapped = {p["residue"]["resname"]: p["standard_resname"] for p in content["positions"]
              if p["residue"]["resname"] in K.MAPPED_RESNAMES}
    assert mapped == K.MAPPED_RESNAMES      # all ten are in the fixture and keep their original resname
    non_standard = names(content, lambda p: p["one_letter"] is None)
    assert non_standard == ORACLE[CIF.name]["derived"]["non_standard_polymer"]
    for label in non_standard:
        p = position(content, label)
        assert p["exclusion_reasons"] == ["non_standard_residue"] and p["status"] == "excluded"
        assert p["candidate_count"] == 0 and p["standard_resname"] is None


def test_user_protection_simultaneous_reasons_and_release(cif):
    args = cif.args(sources={"residues": [cif.ref("ALA A2"), cif.ref("SER A3"), cif.ref("GLY A1"),
                                          cif.ref("CYS A5"), cif.ref("MSE A9")]},
                    protected_residues=[cif.ref("ALA A2"), cif.ref("CYS A5"), cif.ref("THR A4")],
                    released_residues=[cif.ref("SER A3"), cif.ref("GLY A1"), cif.ref("CYX A8"), cif.ref("MSE A9"),
                                       cif.ref("TRP A17")])
    rejected(lambda: cif.normalize({**args, "released_residues": [cif.ref("CYS A5")]}),
             "protect_release_conflict")
    content = cif.build(args)
    a2 = position(content, "ALA A2")
    assert a2["protection"]["reasons"] == ["user_protected", "metal_contact"]
    assert a2["exclusion_reasons"] == ["user_protected", "metal_contact"] and a2["status"] == "excluded"
    a3 = position(content, "SER A3")                  # metal at exactly 3.0, released
    assert a3["protection"]["reasons"] == ["metal_contact"] and a3["protection"]["released"] is True
    assert a3["protection"]["metal"]["min_distance_A"] == 3.0
    assert a3["exclusion_reasons"] == [] and a3["status"] == "candidate" and a3["candidate_count"] == 19
    a5 = position(content, "CYS A5")
    assert a5["protection"]["reasons"] == ["user_protected", "disulfide_cys"]
    assert a5["protection"]["released"] is False
    mse = position(content, "MSE A9")                 # released but nothing to release; non-standard stays
    assert mse["protection"]["released"] is False and mse["exclusion_reasons"] == ["non_standard_residue"]
    effects = {name(item["residue"]): item["effect"] for item in content["released_residues"]}
    assert effects == {"GLY A1": "none", "SER A3": "released", "CYX A8": "none", "MSE A9": "none",
                       "TRP A17": "none"}     # CYX A8 and TRP A17 are not positions
    assert content["protection_checks"]["user_list"] == {"status": "checked", "protected": 3, "released": 5}
    assert content["counts"]["released_positions"] == 1
    assert content["counts"]["exclusion_reason_counts"] == {   # v2: seven keys (M26 8.2)
        "non_standard_residue": 1, "user_protected": 2, "klifs_key_site": 0, "metal_contact": 1,
        "disulfide_cys": 1, "catalytic_residue": 0, "no_allowed_alternative": 0}


def test_release_clears_every_reason_at_once(cif):
    # CYS A20: disulfide (2.5 boundary) + user protected; release clears both reasons together.
    args = cif.args(sources={"residues": [cif.ref("CYS A20")]}, protected_residues=[cif.ref("CYS B20")],
                    released_residues=[cif.ref("CYS A20")])
    p = cif.build(args)["positions"][0]
    assert p["protection"]["reasons"] == ["disulfide_cys"] and p["protection"]["released"] is True
    assert p["exclusion_reasons"] == [] and p["candidate_count"] == 19


def synthetic_annotation(sites: list[tuple[dict, str, int, str]]) -> dict:
    """SYNTHETIC reference_site_annotation@1-shaped content (only the fields the module reads)."""
    return {"groups": [{"sites": [{"residue": residue, "klifs_label": label, "klifs_index": index, "status": status}
                                  for residue, label, index, status in sites]}]}


def test_klifs_key_sites_checked_and_not_checked(cif):
    annotation = synthetic_annotation([
        (cif.ref("HID A6", labels=True), "hinge.46", 46, "annotated"),
        (cif.ref("HID A6", labels=True), "III.17", 17, "annotated"),
        (cif.ref("ALA A2", labels=True), "xDFG.81", 81, "annotated"),
        ({**cif.ref("LEU A10", labels=True), "chain_label": None}, "GK.45", 45, "annotated"),   # 7 fields differ
        (None, "αC.24", 24, "absent")])
    args = cif.args(sources={"residues": [cif.ref("ALA A2"), cif.ref("HID A6"), cif.ref("LEU A10")]},
                    annotation="obj://reference_site_annotation/synthetic")
    content = cif.build(args, annotation_content=annotation)
    assert position(content, "HID A6")["protection"]["klifs_sites"] == ["III.17", "hinge.46"]   # site order
    a2 = position(content, "ALA A2")
    assert a2["protection"]["reasons"] == ["klifs_key_site", "metal_contact"]   # two reasons at once
    assert position(content, "LEU A10")["protection"]["klifs_sites"] == []      # checked, none
    assert content["protection_checks"]["klifs_key_sites"] == {
        "status": "checked", "reason": None, "annotation": "obj://reference_site_annotation/synthetic",
        "annotated_sites": 4, "absent_sites": 1}
    bare = cif.build({**args, "annotation": None})
    assert all(p["protection"]["klifs_sites"] is None for p in bare["positions"])
    assert bare["protection_checks"]["klifs_key_sites"] == {
        "status": "not_checked", "reason": "annotation_not_given", "annotation": None, "annotated_sites": None,
        "absent_sites": None}
    # every new set is v2: no catalytic annotation -> not checked (never "not_available", never a number)
    assert bare["protection_checks"]["catalytic_residue_database"] == {"status": "not_checked",
                                                                       "reason": "annotation_not_given",
                                                                       "annotation": None}
    assert all(p["protection"]["catalytic"] is None for p in bare["positions"])


def test_numbering_copied_and_not_in_map(cif):
    row = {"residue": cif.ref("HID A6", labels=True), "status": "mapped", "uniprot_accession": "P0SYN1",
           "uniprot_position": 60, "uniprot_residue": "H", "klifs_index": 46, "klifs_label": "hinge.46",
           "alignment": None}
    conflict = {"residue": cif.ref("LEU A10", labels=True), "status": "conflict", "uniprot_accession": None,
                "uniprot_position": None, "uniprot_residue": None, "klifs_index": None, "klifs_label": None}
    numbering = {"rows": [row, conflict]}   # SYNTHETIC map rows
    args = cif.args(sources={"residues": [cif.ref("HID A6"), cif.ref("LEU A10"), cif.ref("ILE A10A")]},
                    numbering_map="obj://residue_numbering_map/synthetic")
    content = cif.build(args, numbering_content=numbering)
    assert position(content, "HID A6")["numbering"] == {k: row[k] for k in ("status", *K.NUMBERING_FIELDS)}
    assert position(content, "LEU A10")["numbering"]["status"] == "conflict"
    assert position(content, "ILE A10A")["numbering"] == {"status": "not_in_map", **dict.fromkeys(
        K.NUMBERING_FIELDS)}
    assert all(p["numbering"] is None for p in cif.build({**args, "numbering_map": None})["positions"])


# --- M26 v2: catalytic residue protection (spec 8.2-8.4) ----------------------------------------------------------------
# The pure module gets the plain per-chain values the tool layer takes from a validated reaction_knowledge@1 result
# (M26 spec 8.1): {chain_auth: {coverage, counts, rows}}. The rows below are SYNTHETIC (hand-written M-CSA-shaped
# rows on the synthetic fixture's residues); the expected protection is written out by hand from the spec rules.

CAT = "obj://run_cif/reaction_knowledge/" + "c" * 64      # synthetic handle string (the pure module never loads it)


def cat_row(mcsa_id, index, status, reason=None, residue=None, *, chain="A", auth=None, code="Xaa",
            is_reference=True):
    return {"mcsa_id": mcsa_id, "residue_index": index, "is_reference": is_reference, "status": status,
            "reason": reason, "residue": residue, "listed": {"chain_name": chain, "resid": auth, "auth_resid": auth,
                                                             "code": code}}


def covered(*rows):
    counts = {status: sum(r["status"] == status for r in rows) for status in ("matched", "unmatched", "conflict")}
    return {"coverage": "covered", "counts": counts, "rows": list(rows)}


def uncovered(coverage):
    return {"coverage": coverage, "counts": None, "rows": None}


def synthetic_catalytic(prep):
    """Chain A and B covered: matched rows on HID A6 (two entries), ALA A2, CYS A5, ASP A26 (not a position), HID B6,
    ALA B2, VAL B7 (not a position); a name conflict on MSE A9, an ambiguous number (A10), a disagreeing group (B13)."""
    seven_ = {label: prep.ref(label, labels=True) for label in ("HID A6", "ASP A26", "MSE A9", "CYS A5", "ALA A2",
                                                                "HID B6", "ALA B2", "VAL B7")}
    chain_a = covered(
        cat_row(601, 0, "matched", residue=seven_["HID A6"], auth=6, code="His"),
        cat_row(601, 1, "matched", residue=seven_["ASP A26"], auth=26, code="Asp", is_reference=False),
        cat_row(601, 2, "conflict", "residue_name_differs", seven_["MSE A9"], auth=9, code="Met"),
        cat_row(601, 3, "unmatched", "ambiguous_residue_number", auth=10, code="Leu"),
        cat_row(601, 6, "matched", residue=seven_["CYS A5"], auth=5, code="Cys"),
        cat_row(601, 7, "matched", residue=seven_["ALA A2"], auth=2, code="Ala"),
        cat_row(602, 0, "matched", residue=seven_["HID A6"], auth=6, code="His", is_reference=False))
    chain_b = covered(
        cat_row(601, 8, "matched", residue=seven_["HID B6"], chain="B", auth=6, code="His"),
        cat_row(601, 9, "matched", residue=seven_["ALA B2"], chain="B", auth=2, code="Ala"),
        cat_row(601, 10, "conflict", "mcsa_rows_disagree", chain="B", auth=13, code="Asn/Asp"),
        cat_row(602, 2, "matched", residue=seven_["VAL B7"], chain="B", auth=7, code="Val"))
    return {"A": chain_a, "B": chain_b}


CAT_LABELS = ["ALA A2", "CYS A5", "HID A6", "LEU A10", "ALA B2", "HID B6"]


def cat_args(prep, labels=CAT_LABELS, annotation=CAT, **kw):
    return prep.args(sources={"residues": [prep.ref(label) for label in labels]}, catalytic_annotation=annotation, **kw)


def item(row, chain):
    return {"chain_auth": chain, "mcsa_id": row["mcsa_id"], "residue_index": row["residue_index"],
            "reason": row["reason"], "residue": row["residue"],
            "listed": {k: row["listed"][k] for k in ("chain_name", "resid", "auth_resid", "code")}}


def test_catalytic_protection_all_chains_covered(cif):
    catalytic = synthetic_catalytic(cif)
    args = cat_args(cif, protected_residues=[cif.ref("CYS A5")])
    content = cif.build(args, catalytic_content=catalytic)
    assert content["method_version"] == "mw.mutation_candidates/v2"
    assert content["parameters"]["catalytic_annotation"] == CAT
    entry = {"mcsa_id": 601, "residue_index": 0, "is_reference": True}
    expected = {   # every matched row of the residue's 7 fields, (mcsa_id, residue_index) ascending; [] = checked, none
        "ALA A2": [{"mcsa_id": 601, "residue_index": 7, "is_reference": True}],
        "CYS A5": [{"mcsa_id": 601, "residue_index": 6, "is_reference": True}],
        "HID A6": [entry, {"mcsa_id": 602, "residue_index": 0, "is_reference": False}],
        "LEU A10": [],                                           # only an unmatched row names number 10
        "ALA B2": [{"mcsa_id": 601, "residue_index": 9, "is_reference": True}],
        "HID B6": [{"mcsa_id": 601, "residue_index": 8, "is_reference": True}],
    }
    assert names(content) == CAT_LABELS
    for label, entries in expected.items():
        assert position(content, label)["protection"]["catalytic"] == entries, label
    assert position(content, "ALA A2")["protection"]["reasons"] == ["metal_contact", "catalytic_residue"]
    assert position(content, "CYS A5")["protection"]["reasons"] == ["user_protected", "disulfide_cys",
                                                                    "catalytic_residue"]
    assert position(content, "CYS A5")["exclusion_reasons"] == ["user_protected", "disulfide_cys", "catalytic_residue"]
    assert position(content, "HID A6")["protection"]["reasons"] == ["catalytic_residue"]
    assert position(content, "HID A6")["status"] == "excluded"
    assert position(content, "LEU A10")["protection"]["reasons"] == [] and position(content, "LEU A10")["status"] == \
        "candidate"
    assert content["protection_checks"]["catalytic_residue_database"] == {
        "status": "checked", "reason": None, "annotation": CAT, "covered_chains": ["A", "B"], "uncovered_chains": [],
        "matched_rows": 8, "conflict_rows": 2, "unmatched_rows": 1,
        "conflicts": [item(catalytic["A"]["rows"][2], "A"), item(catalytic["B"]["rows"][2], "B")],
        "unmatched": [item(catalytic["A"]["rows"][3], "A")]}
    assert content["counts"]["exclusion_reason_counts"] == {
        "non_standard_residue": 0, "user_protected": 1, "klifs_key_site": 0, "metal_contact": 1, "disulfide_cys": 1,
        "catalytic_residue": 5, "no_allowed_alternative": 0}
    assert content["limitations"] == list(K.LIMITATIONS_V2["checked"])
    assert content["limitations"][2] == K.LIMITATION_3_CHECKED


def test_catalytic_reason_and_exclusion_order_with_no_allowed_alternative(cif):
    content = cif.build(cat_args(cif, allowed_residues="A"), catalytic_content=synthetic_catalytic(cif))
    assert position(content, "ALA A2")["exclusion_reasons"] == ["metal_contact", "catalytic_residue",
                                                                "no_allowed_alternative"]
    assert position(content, "ALA B2")["exclusion_reasons"] == ["catalytic_residue", "no_allowed_alternative"]
    assert position(content, "LEU A10")["exclusion_reasons"] == [] and position(content, "LEU A10")[
        "candidate_count"] == 1
    assert list(content["counts"]["exclusion_reason_counts"]) == list(K.EXCLUSION_REASONS_V2)
    assert content["counts"]["exclusion_reason_counts"]["no_allowed_alternative"] == 2


def test_catalytic_release_lifts_the_protection_and_keeps_the_reason(cif):
    args = cat_args(cif, released_residues=[cif.ref("HID A6"), cif.ref("ALA A2")])
    content = cif.build(args, catalytic_content=synthetic_catalytic(cif))
    for label in ("HID A6", "ALA A2"):   # every reason of the residue at once (A2: metal + catalytic)
        p = position(content, label)
        assert "catalytic_residue" in p["protection"]["reasons"] and p["protection"]["released"] is True
        assert p["protection"]["catalytic"]                       # the M-CSA entries stay on the row
        assert p["exclusion_reasons"] == [] and p["status"] == "candidate" and p["candidate_count"] == 19
    assert [r["effect"] for r in content["released_residues"]] == ["released", "released"]
    assert content["counts"]["exclusion_reason_counts"]["catalytic_residue"] == 3


@pytest.mark.parametrize("coverage", ["chain_not_listed", "pdb_not_in_snapshot", "not_checked", "not_in_annotation"])
def test_catalytic_partial_coverage_is_not_checked_and_still_protects_covered_chains(cif, coverage):
    catalytic = synthetic_catalytic(cif)
    if coverage != "not_in_annotation":
        catalytic["CC"] = uncovered(coverage)
    content = cif.build(cat_args(cif, labels=[*CAT_LABELS, "HIE CC1"]), catalytic_content=catalytic)
    check = content["protection_checks"]["catalytic_residue_database"]
    assert (check["status"], check["reason"]) == ("not_checked", "chains_not_covered")
    assert check["covered_chains"] == ["A", "B"]
    assert check["uncovered_chains"] == [{"chain_auth": "CC", "coverage": coverage}]
    assert (check["matched_rows"], check["conflict_rows"], check["unmatched_rows"]) == (8, 2, 1)
    assert position(content, "HIE CC1")["protection"]["catalytic"] is None          # not checked, never []
    assert position(content, "HID A6")["protection"]["reasons"] == ["catalytic_residue"]   # covered chains protect
    assert content["limitations"] == list(K.LIMITATIONS_V2["not_checked"])
    assert content["limitations"][2] == K.LIMITATION_3_NOT_CHECKED


def test_catalytic_no_covered_chain_and_zero_positions_are_not_checked(cif):
    catalytic = {"A": uncovered("pdb_not_in_snapshot"), "B": uncovered("pdb_not_in_snapshot")}
    content = cif.build(cat_args(cif), catalytic_content=catalytic)
    assert content["protection_checks"]["catalytic_residue_database"] == {
        "status": "not_checked", "reason": "chains_not_covered", "annotation": CAT, "covered_chains": [],
        "uncovered_chains": [{"chain_auth": "A", "coverage": "pdb_not_in_snapshot"},
                             {"chain_auth": "B", "coverage": "pdb_not_in_snapshot"}],
        "matched_rows": 0, "conflict_rows": 0, "unmatched_rows": 0, "conflicts": [], "unmatched": []}
    assert all(p["protection"]["catalytic"] is None for p in content["positions"])
    assert not any("catalytic_residue" in p["protection"]["reasons"] for p in content["positions"])
    # a set without positions checked nothing: not "checked" even with every chain of the annotation covered
    empty = cif.build(cif.args(sources={"ligand_shell": {"radius_A": 1.0}}, ligand=LIG_A, catalytic_annotation=CAT),
                      catalytic_content=synthetic_catalytic(cif))
    assert empty["positions"] == [] and empty["null_result"] is True
    assert empty["protection_checks"]["catalytic_residue_database"] == {
        "status": "not_checked", "reason": "chains_not_covered", "annotation": CAT, "covered_chains": [],
        "uncovered_chains": [], "matched_rows": 0, "conflict_rows": 0, "unmatched_rows": 0, "conflicts": [],
        "unmatched": []}
    assert empty["limitations"][2] == K.LIMITATION_3_NOT_CHECKED


def test_catalytic_annotation_not_given_has_three_keys_and_null_everywhere(cif):
    content = cif.build(cat_args(cif, annotation=None))
    assert content["parameters"]["catalytic_annotation"] is None
    assert content["protection_checks"]["catalytic_residue_database"] == {
        "status": "not_checked", "reason": "annotation_not_given", "annotation": None}
    assert all(p["protection"]["catalytic"] is None for p in content["positions"])
    assert content["limitations"][2] == K.LIMITATION_3_NOT_CHECKED
    assert "catalytic_annotation" in cif.normalize(cif.args(sources={"residues": [cif.ref("GLY A1")]}))


@pytest.mark.parametrize("which", ["conflicts", "unmatched"])
def test_catalytic_lists_above_the_limit_are_refused_not_truncated(cif, monkeypatch, which):
    catalytic = synthetic_catalytic(cif)
    status = "conflict" if which == "conflicts" else "unmatched"
    reason = "residue_name_differs" if which == "conflicts" else "residue_not_in_structure"
    residue = cif.ref("MSE A9", labels=True) if which == "conflicts" else None
    extra = [cat_row(603, i, status, reason, residue, auth=9 if residue else 500 + i, code="Met") for i in range(3)]
    catalytic["A"] = covered(*catalytic["A"]["rows"], *extra)
    total = sum(r["status"] == status for r in [*catalytic["A"]["rows"], *catalytic["B"]["rows"]])
    monkeypatch.setattr(mc, "MAX_CATALYTIC_LIST", total)
    assert len(cif.build(cat_args(cif), catalytic_content=catalytic)["protection_checks"][
        "catalytic_residue_database"][which]) == total                                   # at the limit: fine
    monkeypatch.setattr(mc, "MAX_CATALYTIC_LIST", total - 1)
    error = rejected(lambda: mc.build_candidate_set(cif.handle, cif.st, cif.normalize(cat_args(cif)),
                                                    catalytic_content=catalytic), "catalytic_list_too_long")
    assert error.detail == {"reason_code": "catalytic_list_too_long", "list": which, "count": total,
                            "limit": total - 1}


def test_v2_stored_format_changes_only_the_m26_fields(cif):
    """M26 spec 8.6: v2 = v1 + catalytic_annotation, protection.catalytic, the catalytic check, seven exclusion counts
    and the third limitation sentence; every other key set is the v1 one (the stored v1 fixture is the reference)."""
    v1 = json.loads((FIX / "sequence_ga" / "m20-candidate-set-1ubq-8pos.json").read_text())["content"]
    v2 = cif.build(cat_args(cif), catalytic_content=synthetic_catalytic(cif))
    assert v1["method_version"] == "mw.mutation_candidates/v1" and v2["method_version"] == "mw.mutation_candidates/v2"
    assert set(v2) == set(v1)
    assert set(v2["parameters"]) == set(v1["parameters"]) | {"catalytic_annotation"}
    assert set(v2["positions"][0]) == set(v1["positions"][0])
    assert set(v2["positions"][0]["protection"]) == set(v1["positions"][0]["protection"]) | {"catalytic"}
    assert set(v2["protection_checks"]) == set(v1["protection_checks"])
    assert list(v2["protection_checks"]["catalytic_residue_database"]) == list(K.CATALYTIC_CHECK_KEYS)
    assert set(v2["counts"]) == set(v1["counts"])
    assert set(v2["counts"]["exclusion_reason_counts"]) == set(v1["counts"]["exclusion_reason_counts"]) | {
        "catalytic_residue"}
    assert [a == b for a, b in zip(v2["limitations"], v1["limitations"], strict=True)] == [True, True, False, True,
                                                                                           True]
    assert v1["protection_checks"]["catalytic_residue_database"] == {"status": "not_available",
                                                                     "reason": "not_implemented"}


# --- sources -------------------------------------------------------------------------------------------------------

def synthetic_pocket_set(prep: Prepared, pockets: dict[int, list[str]]) -> dict:
    """SYNTHETIC pocket_set@1-shaped content; lining lists are deliberately not in file order."""
    return {"source_handle": prep.handle, "null_result": False,
            "pockets": [{"rank": rank, "lining_residues": [prep.ref(label, labels=True) for label in labels]}
                        for rank, labels in pockets.items()]}


def test_source_union_one_row_per_residue_in_file_order(cif):
    pocket = synthetic_pocket_set(cif, {1: ["LEU A10", "HID A6", "GLY B1"], 2: ["HID A6", "ALA CC11"],
                                        3: ["TRP A17"]})
    args = cif.args(sources={"pocket": {"pocket_set": "obj://pocket_set/synthetic", "ranks": [2, 1]},
                             "ligand_shell": {"radius_A": 5.0}, "residues": [cif.ref("GLY B1"), cif.ref("HID A6")]},
                    ligand=LIG_A)
    content = cif.build(args, pocket_content=pocket)
    assert content["parameters"]["sources"]["pocket"]["ranks"] == [1, 2]
    assert names(content) == ["HID A6", "MSE A9", "LEU A10", "PHE A15", "GLY B1", "SEP CC10", "ALA CC11"]
    assert [p["index"] for p in content["positions"]] == list(range(7))
    assert position(content, "HID A6")["sources"] == [{"kind": "pocket", "pocket_rank": 1},
                                                      {"kind": "pocket", "pocket_rank": 2},
                                                      {"kind": "ligand_shell", "radius_A": 5.0}, {"kind": "user"}]
    assert position(content, "GLY B1")["sources"] == [{"kind": "pocket", "pocket_rank": 1}, {"kind": "user"}]
    assert position(content, "ALA CC11")["residue"]["seq_label"] is None     # null label kept
    assert content["pockets"] == {"pocket_set": "obj://pocket_set/synthetic", "ranks": [1, 2],
                                  "lining_residue_count": 4}
    assert content["counts"]["source_counts"] == {"pocket": 4, "ligand_shell": 5, "user": 2}
    assert "TRP A17" not in names(content)     # rank 3 was not selected


def test_pocket_rank_and_lining_checks(cif):
    pocket = synthetic_pocket_set(cif, {1: ["HID A6"], 2: ["LEU A10"]})
    rejected(lambda: mc.pocket_lining(pocket, [1, 3], cif.residues), "pocket_rank_invalid")
    rejected(lambda: mc.pocket_lining(pocket, [1, 1], cif.residues), "pocket_rank_invalid")
    assert mc.pocket_lining(pocket, [2], cif.residues) == {2: [cif.ref("LEU A10", labels=True)]}
    wrong_label = copy.deepcopy(pocket)
    wrong_label["pockets"][0]["lining_residues"][0]["chain_label"] = None
    rejected(lambda: mc.pocket_lining(wrong_label, [1], cif.residues), "pocket_residue_mismatch")
    hetatm = copy.deepcopy(pocket)
    hetatm["pockets"][1]["lining_residues"] = [cif.ref("MSE CC9", labels=True)]
    rejected(lambda: mc.pocket_lining(hetatm, [2], cif.residues), "pocket_residue_mismatch")


# --- candidates ------------------------------------------------------------------------------------------------------

def test_candidate_order_numbering_and_allowed_list(cif):
    args = cif.args(sources={"residues": [cif.ref("TRP A17"), cif.ref("ALA A2"), cif.ref("GLY A1")]},
                    allowed_residues=["W", "A", "C"], metal_contact_A=1.0)
    content = cif.build(args)
    assert content["parameters"]["allowed_residues"] == "ACW"
    assert [(c["index"], c["position_index"], c["from"], c["to"]) for c in content["candidates"]] == [
        (0, 0, "G", "A"), (1, 0, "G", "C"), (2, 0, "G", "W"), (3, 1, "A", "C"), (4, 1, "A", "W"),
        (5, 2, "W", "A"), (6, 2, "W", "C")]
    assert [p["candidate_count"] for p in content["positions"]] == [3, 2, 2]
    full = cif.build(cif.args(sources={"residues": [cif.ref("GLY A1")]}))
    assert "".join(c["to"] for c in full["candidates"]) == K.ONE_LETTER_ORDER.replace("G", "")


def test_no_allowed_alternative_and_zero_candidates_null_result(cif):
    args = cif.args(sources={"residues": [cif.ref("ALA B2"), cif.ref("MSE A9"), cif.ref("ALA CC11")]},
                    allowed_residues="A")
    content = cif.build(args)
    assert names(content) == ["MSE A9", "ALA B2", "ALA CC11"]                    # file order
    assert [p["exclusion_reasons"] for p in content["positions"]] == [
        ["non_standard_residue"], ["no_allowed_alternative"], ["no_allowed_alternative"]]
    assert content["candidates"] == [] and content["null_result"] is True
    assert content["counts"]["candidates"] == 0 and content["counts"]["excluded_positions"] == 3
    one = cif.build({**args, "allowed_residues": "AG"})
    assert [(c["from"], c["to"]) for c in one["candidates"]] == [("A", "G"), ("A", "G")]
    assert one["null_result"] is False


def test_too_many_positions_is_refused_not_truncated(cif, monkeypatch):
    args = cif.args(sources={"residues": every_polymer(cif)[:6]})
    monkeypatch.setattr(mc, "MAX_POSITIONS", 6)
    assert len(cif.build(args)["positions"]) == 6                  # at the limit: fine
    monkeypatch.setattr(mc, "MAX_POSITIONS", 5)
    error = rejected(lambda: mc.build_candidate_set(cif.handle, cif.st, cif.normalize(args)), "too_many_positions")
    assert error.detail == {"reason_code": "too_many_positions", "positions": 6, "limit": 5}


# --- identities ------------------------------------------------------------------------------------------------------

def test_null_labels_insertion_code_multi_letter_chain_and_identical_chains(cif, pdb):
    refs = [pdb.ref("LEU A10"), pdb.ref("ILE A10A"), pdb.ref("LEU B10"), pdb.ref("ILE B10A")]
    content = pdb.build(pdb.args(sources={"residues": refs}))
    assert all(p["residue"]["chain_label"] is None and p["residue"]["seq_label"] is None
               for p in content["positions"])
    assert names(content) == ["LEU A10", "ILE A10A", "LEU B10", "ILE B10A"]      # chains never merged
    assert content["positions"][1]["residue"]["icode"] == "A"
    # labels given explicitly: null is a value and must match
    pdb.normalize(pdb.args(sources={"residues": [{**pdb.ref("LEU A10"), "chain_label": None, "seq_label": None}]}))
    rejected(lambda: pdb.normalize(pdb.args(sources={"residues": [{**pdb.ref("LEU A10"), "chain_label": "A"}]})),
             "residue_invalid")
    cc = cif.build(cif.args(sources={"residues": [cif.ref("HIE CC1"), cif.ref("ALA CC11")]}))
    assert [p["residue"]["chain_auth"] for p in cc["positions"]] == ["CC", "CC"]
    assert cc["positions"][1]["residue"]["seq_label"] is None and cc["positions"][1]["residue"]["chain_label"] == "C"
    assert cc["positions"][0]["residue"] == cif.ref("HIE CC1", labels=True)


def test_normalization_is_order_and_spelling_insensitive(cif):
    pocket = synthetic_pocket_set(cif, {1: ["HID A6"], 2: ["LEU A10"], 3: ["GLY B1"]})
    a = cif.args(sources={"pocket": {"pocket_set": "obj://pocket_set/synthetic", "ranks": [3, 1]},
                          "ligand_shell": {"radius_A": 5}, "residues": [cif.ref("GLY B1"), cif.ref("ALA A2")]},
                 ligand=LIG_A, allowed_residues="WCA", protected_residues=[cif.ref("SER B3"), cif.ref("SER A3")],
                 released_residues=[cif.ref("THR B4"), cif.ref("THR A4", labels=True)], metal_contact_A=3)
    b = cif.args(sources={"pocket": {"ranks": [1, 3], "pocket_set": "obj://pocket_set/synthetic"},
                          "ligand_shell": {"radius_A": 5.0},
                          "residues": [cif.ref("ALA A2", labels=True), cif.ref("GLY B1")]},
                 ligand={**LIG_A, "chain_label": "D"}, allowed_residues=["A", "C", "W"],
                 protected_residues=[cif.ref("SER A3"), cif.ref("SER B3")],
                 released_residues=[cif.ref("THR A4"), cif.ref("THR B4")], metal_contact_A=3.0)
    na, nb = cif.normalize(a), cif.normalize(b)
    assert canonical_json(na) == canonical_json(nb)
    assert na["sources"]["residues"] == [cif.ref("ALA A2", labels=True), cif.ref("GLY B1", labels=True)]
    assert na["protected_residues"] == [cif.ref("SER A3", labels=True), cif.ref("SER B3", labels=True)]
    assert na["ligand"] == cif.ref("LIG A101", labels=True)
    assert type(na["metal_contact_A"]) is float and type(na["sources"]["ligand_shell"]["radius_A"]) is float
    first = cif.build(a, pocket_content=pocket)
    assert canonical_json(first) == canonical_json(cif.build(b, pocket_content=pocket))
    assert canonical_json(first) == canonical_json(cif.build(a, pocket_content=pocket))   # same input, same content
    assert cif.normalize(cif.args(sources={"residues": [cif.ref("GLY A1")]}))["allowed_residues"] == \
        K.ONE_LETTER_ORDER
    other = cif.normalize({**a, "allowed_residues": "AC"})
    assert canonical_json(other) != canonical_json(na)


# --- admission checks that need no store ------------------------------------------------------------------------------

def test_unknown_fields_at_each_level(cif):
    base = cif.args(sources={"residues": [cif.ref("GLY A1")]})
    rejected(lambda: mc.check_fields({**base, "extra": 1}), "unknown_field")
    rejected(lambda: mc.check_fields({**base, "sources": {**base["sources"], "atoms": []}}), "unknown_field")
    rejected(lambda: mc.check_fields({**base, "sources": {**base["sources"], "pocket": {"pocket_set": "x",
                                                                                     "ranks": [1], "x": 1}}}),
             "unknown_field")
    rejected(lambda: mc.check_fields({**base, "sources": {**base["sources"], "ligand_shell": {"radius": 5}}}),
             "unknown_field")
    rejected(lambda: cif.normalize({**base, "extra": 1, "allowed_residues": "B"}), "unknown_field")
    mc.check_fields(base)


@pytest.mark.parametrize("change", [
    {"metal_contact_A": float("nan")}, {"metal_contact_A": float("inf")}, {"metal_contact_A": True},
    {"metal_contact_A": 0.999}, {"metal_contact_A": 5.001}, {"metal_contact_A": None}, {"metal_contact_A": "3"},
    {"sources": {"ligand_shell": {"radius_A": 12.0001}}}, {"sources": {"ligand_shell": {"radius_A": 0.5}}},
    {"sources": {"ligand_shell": {"radius_A": False}}}, {"sources": {"ligand_shell": {"radius_A": None}}},
    {"sources": {"ligand_shell": 5.0}},
    {"sources": {"pocket": {"pocket_set": "x", "ranks": []}}}, {"sources": {"pocket": {"pocket_set": "x"}}},
    {"sources": {"pocket": {"pocket_set": "x", "ranks": [True]}}}, {"sources": {"pocket": [1]}},
    {"sources": {"residues": "GLY A1"}}, {"sources": {"residues": [{"chain_auth": "A"}]}},
    {"sources": {"residues": [{**LIG_A, "seq_auth": "101"}]}}, {"sources": {"residues": [{**LIG_A, "seq_auth": True}]}},
    {"sources": {"residues": [{**LIG_A, "name": "x"}]}},
    {"protected_residues": None}, {"released_residues": [LIG_A] * 401},
    {"ligand": {"chain_auth": "A"}}, {"allowed_residues": 5}, {"allowed_residues": None},
    {"sources": None},
])
def test_argument_invalid(cif, change):
    args = cif.args(sources={"residues": [cif.ref("GLY A1")]}, ligand=LIG_A)
    if "sources" in change and isinstance(change["sources"], dict):
        args["sources"] = {**args["sources"], **change.pop("sources")}
    args.update(change)
    rejected(lambda: cif.normalize(args), "argument_invalid")


def test_range_ends_are_inclusive(cif):
    for radius in (1.0, 12.0):
        cif.normalize(cif.args(sources={"ligand_shell": {"radius_A": radius}}, ligand=LIG_A))
    for metal in (1.0, 5.0):
        cif.normalize(cif.args(sources={"residues": [cif.ref("GLY A1")]}, metal_contact_A=metal))
    cif.normalize(cif.args(sources={"residues": every_polymer(cif)}, protected_residues=[], released_residues=[]))


def test_no_position_source_comes_before_argument_invalid(cif):
    rejected(lambda: cif.normalize(cif.args(metal_contact_A=float("nan"))), "no_position_source")
    rejected(lambda: cif.normalize({"structure": cif.handle, "sources": {}}), "no_position_source")


@pytest.mark.parametrize("value", ["", [], "B", "AAC", ["A", "A"], "a", ["AC"], ["A", 1]])
def test_allowed_residues_invalid(cif, value):
    rejected(lambda: cif.normalize(cif.args(sources={"residues": [cif.ref("GLY A1")]}, allowed_residues=value)),
             "allowed_residues_invalid")


def test_residue_resolution_duplicates_conflicts_and_ligand_checks(cif, tmp_path):
    def norm(**kw):
        return lambda: cif.normalize(cif.args(**kw))

    rejected(norm(sources={"residues": [{**cif.ref("GLY A1"), "seq_auth": 99}]}), "residue_invalid")
    rejected(norm(sources={"residues": [cif.ref("MSE CC9")]}), "residue_invalid")     # HETATM, not polymer
    rejected(norm(sources={"residues": [LIG_A]}), "residue_invalid")
    rejected(norm(sources={"residues": [cif.ref("GLY A1")]}, protected_residues=[{**LIG_B, "resname": "ZN"}]),
             "residue_invalid")
    rejected(norm(sources={"residues": [cif.ref("GLY A1"), cif.ref("GLY A1", labels=True)]}), "duplicate_residue")
    rejected(norm(sources={"residues": [cif.ref("GLY A1")]}, released_residues=[cif.ref("ALA A2")] * 2),
             "duplicate_residue")
    rejected(norm(sources={"residues": [cif.ref("GLY A1")]}, protected_residues=[cif.ref("ALA A2")],
                  released_residues=[cif.ref("ALA A2", labels=True)]), "protect_release_conflict")
    # ligand_required before ligand_invalid; no automatic choice even with a single ligand (1HSG has only MK1)
    rejected(norm(sources={"ligand_shell": {"radius_A": 5.0}}), "ligand_required")
    hsg = Prepared(tmp_path, FIX / "public_1hsg.cif", "run_hsg")
    assert len(hsg.ligands) == 1
    rejected(lambda: hsg.normalize(hsg.args(sources={"ligand_shell": {}})), "ligand_required")
    rejected(norm(sources={"residues": [cif.ref("GLY A1")]}, ligand={**LIG_A, "seq_auth": 999}), "ligand_invalid")
    rejected(norm(sources={"residues": [cif.ref("GLY A1")]}, ligand={**LIG_A, "chain_label": "Z"}), "ligand_invalid")
    rejected(norm(sources={"residues": [cif.ref("GLY A1")]}, ligand=cif.ref("GLY A1")), "ligand_invalid")
    rejected(norm(sources={"residues": [cif.ref("GLY A1")]},
                  ligand={"model_number": 1, "chain_auth": "A", "seq_auth": 201, "icode": "", "resname": "ZN"}),
             "ligand_invalid")                                                       # metals are not ligands
    # order: residue_invalid wins over a later ligand problem; argument_invalid over residue_invalid
    rejected(norm(sources={"residues": [LIG_A]}, ligand={**LIG_A, "seq_auth": 999}), "residue_invalid")
    rejected(norm(sources={"residues": [LIG_A]}, metal_contact_A=9.0), "argument_invalid")
    rejected(norm(sources={"residues": [LIG_A]}, allowed_residues="B"), "allowed_residues_invalid")
    assert cif.normalize(cif.args(sources={"residues": [cif.ref("GLY A1")]}, ligand=LIG_B))["ligand"] == \
        cif.ref("LIG B101", labels=True)


# --- public structures (oracle: preflight.txt numpy values) ------------------------------------------------------------

ADP = {"model_number": 1, "chain_auth": "A", "seq_auth": 2001, "icode": "", "resname": "ADP"}
ADP_SHELL_5 = {
    139: 3.6335530820396684, 140: 3.4748130884984305, 141: 3.5587813925556007, 142: 3.05630381343217,
    143: 2.6283578523481124, 144: 4.43855528297215, 147: 3.5023984639101227, 160: 3.613476304059567,
    162: 2.6428630308814687, 181: 4.647095114154647, 194: 3.424981313817638, 210: 3.912459584455801,
    211: 2.695699723633924, 212: 4.1012362770267154, 213: 3.167315109047404, 217: 3.297842476529162,
    260: 2.598733152903544, 261: 2.9617780132886407, 263: 3.4190263233850664, 274: 2.853779599058067}
KLIFS_1MQ4 = {162: ["III.17"], 181: ["αC.24"], 210: ["GK.45"], 211: ["hinge.46"], 212: ["hinge.47"],
              213: ["hinge.48"], 274: ["xDFG.81"]}
MG_1MQ4_3 = {261: (2.035529660800842, 2088), 274: (1.916987219571373, 2088)}


@pytest.fixture
def refroot(tmp_path, monkeypatch):
    root = tmp_path / "reference"
    root.mkdir()
    monkeypatch.setenv(rs.ENV_VAR, str(root))
    build_fixture_set(root)
    return root


def test_1mq4_adp_shell_with_real_map_and_annotation(tmp_path, refroot):
    prep = Prepared(tmp_path, FIX / "public_1mq4.cif", "run_1mq4")
    run = prep.run
    numbering_map = run.call("map_residue_numbering", {"structure": prep.handle, "pdb_id": "1MQ4",
                                                       "chains": [{"chain_auth": "A"}]}).handle
    annotation = run.call("annotate_reference_sites", {"numbering_map": numbering_map}).handle
    map_content, annotation_content = run.store.load(numbering_map), run.store.load(annotation)
    rejected(lambda: prep.normalize(prep.args(sources={"ligand_shell": {}})), "ligand_required")
    rejected(lambda: prep.normalize(prep.args(sources={"residues": [prep.polymer[0]]})),   # extra keys
             "argument_invalid")
    args = prep.args(sources={"ligand_shell": {}}, ligand=ADP, numbering_map=numbering_map, annotation=annotation)
    content = prep.build(args, numbering_content=map_content, annotation_content=annotation_content)
    assert [p["residue"]["seq_auth"] for p in content["positions"]] == sorted(ADP_SHELL_5)
    for p in content["positions"]:
        seq = p["residue"]["seq_auth"]
        assert abs(p["ligand_min_distance_A"] - ADP_SHELL_5[seq]) <= TOL
        assert p["protection"]["klifs_sites"] == KLIFS_1MQ4.get(seq, [])
        metal = p["protection"]["metal"]
        if seq in MG_1MQ4_3:
            assert abs(metal["min_distance_A"] - MG_1MQ4_3[seq][0]) <= TOL
            assert (metal["metal_residue"]["resname"], metal["metal_residue"]["seq_auth"]) == ("MG", MG_1MQ4_3[seq][1])
        else:
            assert metal is None
        row = next(r for r in map_content["rows"] if r["residue"] == p["residue"])
        assert p["numbering"] == {k: row[k] for k in ("status", *K.NUMBERING_FIELDS)}   # copied verbatim
    asp = next(p for p in content["positions"] if p["residue"]["seq_auth"] == 274)
    assert asp["protection"]["reasons"] == ["klifs_key_site", "metal_contact"]          # real simultaneous case
    assert content["protection_checks"]["klifs_key_sites"]["annotated_sites"] == 10
    assert content["protection_checks"]["klifs_key_sites"]["absent_sites"] == 0
    assert content["protection_checks"]["metal_contact"]["metal_residues"] == 2
    assert content["protection_checks"]["disulfide"]["pairs"] == 0
    assert content["counts"]["exclusion_reason_counts"]["klifs_key_site"] == 7
    assert content["counts"]["exclusion_reason_counts"]["metal_contact"] == 2
    assert content["counts"]["candidate_positions"] == 20 - 8                      # 7 KLIFS + ASN261
    assert content["counts"]["candidates"] == 12 * 19


def test_1hsg_mk1_shell_two_identical_chains(tmp_path):
    prep = Prepared(tmp_path, FIX / "public_1hsg.cif", "run_1hsg")
    mk1 = {"model_number": 1, "chain_auth": "B", "seq_auth": 902, "icode": "", "resname": "MK1"}
    content = prep.build(prep.args(sources={"ligand_shell": {"radius_A": 5.0}}, ligand=mk1))
    expected = {("A", 8): 3.509653829083433, ("A", 23): 3.850918851391182, ("A", 25): 2.7725354821895407,
                ("A", 27): 3.5758727605998506, ("A", 28): 3.814587002546933, ("A", 29): 4.366473863428016,
                ("A", 30): 4.160849192172191, ("A", 32): 3.7654888128900343, ("A", 47): 3.7289841780302586,
                ("A", 48): 3.1489072707845818, ("A", 49): 3.5479883032501665, ("A", 50): 4.21055032032631,
                ("A", 53): 4.679039217617223, ("A", 81): 3.917820439989561, ("A", 82): 3.634973177342577,
                ("A", 84): 3.9277345887928807, ("B", 8): 3.4612600306824675, ("B", 23): 4.414569061641239,
                ("B", 25): 2.6264474104767457, ("B", 27): 3.0256997537759758, ("B", 28): 3.6552217442995167,
                ("B", 29): 3.060997713164777, ("B", 30): 3.3994808427170167, ("B", 31): 4.9255977302252365,
                ("B", 32): 3.324938796429191, ("B", 47): 3.8063119945690205, ("B", 48): 3.535432222515373,
                ("B", 49): 3.367740637281915, ("B", 50): 3.6821072770901178, ("B", 76): 4.95573445616288,
                ("B", 81): 3.686316047221128, ("B", 82): 3.9052613228822466, ("B", 84): 3.711161273779409}
    got = {(p["residue"]["chain_auth"], p["residue"]["seq_auth"]): p["ligand_min_distance_A"]
           for p in content["positions"]}
    assert list(got) == list(expected)          # file order: chain A then chain B, never merged
    assert all(abs(got[k] - expected[k]) <= TOL for k in expected)
    assert content["protection_checks"]["metal_contact"] == {"status": "checked", "threshold_A": 3.0,
                                                             "metal_residues": 0, "metal_names": []}
    assert content["protection_checks"]["disulfide"]["pairs"] == 0
    assert content["counts"]["positions"] == 33 and content["null_result"] is False


# --- validated_set ---------------------------------------------------------------------------------------------------

def tamperings():
    def setp(path, value):
        def apply(c):
            target = c
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
        return apply

    return {
        "schema": setp(["schema"], "mutation_candidate_set@2"),
        "extra_key": lambda c: c.update(extra=1),
        "count": lambda c: c["counts"].update(candidates=c["counts"]["candidates"] + 1),
        "reason_count": lambda c: c["counts"]["exclusion_reason_counts"].update(metal_contact=99),
        "null_result": setp(["null_result"], True),
        "limitation": lambda c: c["limitations"].__setitem__(1, "이 목록은 추천이다."),
        "limitation_missing": lambda c: c["limitations"].pop(),
        "candidate_from": setp(["candidates", 0, "from"], "W"),
        "candidate_to_self": lambda c: c["candidates"][0].update(to=c["candidates"][0]["from"]),
        "candidate_position": setp(["candidates", 0, "position_index"], 99),
        "candidate_dropped": lambda c: c["candidates"].pop(),
        "candidate_on_excluded": lambda c: c["candidates"].append(
            {"index": len(c["candidates"]), "position_index": 0, "from": "A", "to": "C"}),
        "status": setp(["positions", 1, "status"], "excluded"),
        "unknown_reason": setp(["positions", 0, "exclusion_reasons"], ["unsafe"]),
        "dropped_reason": setp(["positions", 0, "exclusion_reasons"], []),
        "unknown_source": setp(["positions", 1, "sources"], [{"kind": "model"}]),
        "zero_distance": setp(["positions", 1, "ligand_min_distance_A"], 0.0),
        "klifs_not_checked_empty": setp(["positions", 1, "protection", "klifs_sites"], []),
        "released_flag": setp(["positions", 1, "protection", "released"], True),
        "residue_shape": lambda c: c["positions"][1]["residue"].pop("seq_label"),
        "residue_type": setp(["positions", 1, "residue", "seq_auth"], "2"),
        "check_key": lambda c: c["protection_checks"].pop("catalytic_residue_database"),
        "catalytic": setp(["protection_checks", "catalytic_residue_database", "status"], "checked"),
        "klifs_status": setp(["protection_checks", "klifs_key_sites", "status"], "checked"),
        "metal_threshold": setp(["protection_checks", "metal_contact", "threshold_A"], 5.0),
        "effect": setp(["released_residues", 0, "effect"], "released"),
        "position_index": setp(["positions", 1, "index"], 7),
        "candidate_count": setp(["positions", 1, "candidate_count"], 0),
        "metal_missing": setp(["positions", 0, "protection", "metal"], None),
        "standard_name": setp(["positions", 1, "one_letter"], "X"),
    }


@pytest.mark.parametrize("case", sorted(tamperings()))
def test_validated_set_rejects_tampered_content(cif, case):
    # positions in file order: ALA A2 (metal 2.9, excluded), HID A6, LEU A10; GLY A1 released but not a position
    content = cif.build(cif.args(sources={"residues": [cif.ref("ALA A2"), cif.ref("LEU A10"), cif.ref("HID A6")]},
                                 released_residues=[cif.ref("GLY A1")]))
    assert content["positions"][0]["exclusion_reasons"] == ["metal_contact"]
    if case == "zero_distance":
        assert content["positions"][1]["ligand_min_distance_A"] is None
    mc.validated_set(content)
    bad = copy.deepcopy(content)
    tamperings()[case](bad)
    with pytest.raises(mc.MutationSetInvalid):
        mc.validated_set(bad)


def test_validated_set_accepts_a_json_round_trip_and_rejects_non_objects(cif):
    content = cif.build(cif.args(sources={"ligand_shell": {}}, ligand=LIG_A, annotation=None))
    assert mc.validated_set(json.loads(canonical_json(content))) == content
    for value in (None, [], "x", {}):
        with pytest.raises(mc.MutationSetInvalid):
            mc.validated_set(value)


def test_result_has_no_time_or_call_fields_and_every_float_is_finite(cif):
    content = cif.build(cif.args(sources={"residues": every_polymer(cif)}, ligand=LIG_A))
    text = canonical_json(content).decode()
    for word in ("time", "call_id", "created", "uuid"):
        assert word not in text
    floats = []

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, float):
            floats.append(value)

    walk(content)
    assert floats and all(math.isfinite(v) for v in floats)


# --- validated_set: v2 iff-rules (M26 spec 8.6) and the unchanged v1 path ----------------------------------------------

def _v2_bases(cif):
    """checked (A, B covered), partial (CC chain_not_listed), uncovered (no covered chain) and not-given v2 sets.
    Positions in file order: ALA A2, CYS A5, HID A6, LEU A10, ALA B2, HID B6 (+ HIE CC1 in partial)."""
    full = cif.build(cat_args(cif), catalytic_content=synthetic_catalytic(cif))
    partial_input = {**synthetic_catalytic(cif), "CC": uncovered("chain_not_listed")}
    partial = cif.build(cat_args(cif, labels=[*CAT_LABELS, "HIE CC1"]), catalytic_content=partial_input)
    none = cif.build(cat_args(cif), catalytic_content={"A": uncovered("pdb_not_in_snapshot"),
                                                       "B": uncovered("pdb_not_in_snapshot")})
    given_not = cif.build(cat_args(cif, annotation=None))
    return {"full": full, "partial": partial, "none": none, "not_given": given_not}


def _check(c):
    return c["protection_checks"]["catalytic_residue_database"]


def _not_checked_status(c):
    _check(c).update(status="not_checked", reason="chains_not_covered")
    c["limitations"][2] = K.LIMITATION_3_NOT_CHECKED


def _add_reason(c, index):
    p = c["positions"][index]
    p["protection"]["reasons"].append("catalytic_residue")
    p["exclusion_reasons"] = ["catalytic_residue"]
    p["status"], p["candidate_count"] = "excluded", 0


def v2_tamperings():
    return {
        # covered / uncovered chains: disjoint, together exactly the chains with positions, in file order
        "overlap": ("full", lambda c: (_check(c)["uncovered_chains"].append({"chain_auth": "B",
                                                                             "coverage": "chain_not_listed"}),
                                       _not_checked_status(c))),
        "union_missing": ("full", lambda c: _check(c)["covered_chains"].remove("B")),
        "union_missing_only": ("partial", lambda c: (_check(c)["uncovered_chains"].clear(),
                                                     _check(c).update(status="checked", reason=None),
                                                     c["limitations"].__setitem__(2, K.LIMITATION_3_CHECKED))),
        "extra_chain": ("full", lambda c: (_check(c)["uncovered_chains"].append({"chain_auth": "Z",
                                                                                 "coverage": "not_in_annotation"}),
                                           _not_checked_status(c))),
        "chain_order": ("full", lambda c: _check(c)["covered_chains"].reverse()),
        "duplicate_covered": ("full", lambda c: _check(c)["covered_chains"].append("A")),
        # per-chain nullness of protection.catalytic
        "covered_null": ("full", lambda c: c["positions"][3]["protection"].update(catalytic=None)),
        "uncovered_list": ("partial", lambda c: c["positions"][6]["protection"].update(catalytic=[])),
        "not_given_list": ("not_given", lambda c: c["positions"][3]["protection"].update(catalytic=[])),
        "none_list": ("none", lambda c: c["positions"][3]["protection"].update(catalytic=[])),
        # reason list <-> non-empty catalytic
        "reason_without_entries": ("full", lambda c: c["positions"][1]["protection"].update(catalytic=[])),
        "entries_without_reason": ("full", lambda c: c["positions"][3]["protection"].update(
            catalytic=[{"mcsa_id": 601, "residue_index": 5, "is_reference": True}])),
        "reason_dropped": ("full", lambda c: c["positions"][2]["protection"]["reasons"].remove("catalytic_residue")),
        "reason_not_given": ("not_given", lambda c: _add_reason(c, 3)),
        # status / reason <-> chains
        "checked_partial": ("partial", lambda c: (_check(c).update(status="checked", reason=None),
                                                  c["limitations"].__setitem__(2, K.LIMITATION_3_CHECKED))),
        "not_checked_full": ("full", _not_checked_status),
        "checked_without_cover": ("none", lambda c: (_check(c).update(status="checked", reason=None),
                                                     c["limitations"].__setitem__(2, K.LIMITATION_3_CHECKED))),
        "reason_word": ("full", lambda c: _check(c).update(reason="chains_not_covered")),
        "not_given_reason": ("not_given", lambda c: _check(c).update(reason="chains_not_covered")),
        "not_given_extra_key": ("not_given", lambda c: _check(c).update(covered_chains=[])),
        "status_unknown": ("partial", lambda c: _check(c).update(status="not_available")),
        # counts <-> list lengths, zero without a covered chain, matched rows >= the protected entries
        "conflict_count": ("full", lambda c: _check(c).update(conflict_rows=3)),
        "unmatched_count": ("full", lambda c: _check(c).update(unmatched_rows=0)),
        "matched_short": ("full", lambda c: _check(c).update(matched_rows=1)),
        "matched_bool": ("full", lambda c: _check(c).update(matched_rows=True)),
        "counts_without_cover": ("none", lambda c: _check(c).update(matched_rows=1)),
        "list_too_long": ("full", lambda c: (_check(c)["conflicts"].__setitem__(slice(0, 0),
                                                                                [_check(c)["conflicts"][0]] * 400),
                                             _check(c).update(conflict_rows=402))),
        # list items
        "item_reason": ("full", lambda c: _check(c)["conflicts"][0].update(reason="no_author_number")),
        "unmatched_item_reason": ("full", lambda c: _check(c)["unmatched"][0].update(reason="residue_name_differs")),
        "item_chain": ("full", lambda c: _check(c)["conflicts"][0].update(chain_auth="CC")),
        "item_order": ("full", lambda c: _check(c)["conflicts"].reverse()),
        "item_residue_null": ("full", lambda c: _check(c)["conflicts"][0].update(residue=None)),
        "item_residue_given": ("full", lambda c: _check(c)["conflicts"][1].update(
            residue=c["positions"][4]["residue"])),
        "item_listed_keys": ("full", lambda c: _check(c)["conflicts"][0]["listed"].pop("resid")),
        "item_keys": ("full", lambda c: _check(c)["unmatched"][0].update(note="x")),
        # protection.catalytic entries
        "entry_order": ("full", lambda c: c["positions"][2]["protection"]["catalytic"].reverse()),
        "entry_type": ("full", lambda c: c["positions"][2]["protection"]["catalytic"][0].update(is_reference=1)),
        "entry_keys": ("full", lambda c: c["positions"][2]["protection"]["catalytic"][0].update(note="x")),
        # exclusion order and the seven counts
        "exclusion_order": ("full", lambda c: c["positions"][0].update(exclusion_reasons=["catalytic_residue",
                                                                                         "metal_contact"])),
        "six_counts": ("full", lambda c: c["counts"]["exclusion_reason_counts"].pop("catalytic_residue")),
        "count_value": ("full", lambda c: c["counts"]["exclusion_reason_counts"].update(catalytic_residue=0)),
        # the limitation variant follows the status
        "limitation_variant": ("full", lambda c: c["limitations"].__setitem__(2, K.LIMITATION_3_NOT_CHECKED)),
        "limitation_v1": ("partial", lambda c: c["limitations"].__setitem__(2, K.LIMITATIONS[2])),
        # keys and generations
        "annotation_field": ("full", lambda c: _check(c).update(annotation="obj://other/reaction_knowledge/x")),
        "parameter_missing": ("full", lambda c: c["parameters"].pop("catalytic_annotation")),
        "protection_key_missing": ("full", lambda c: c["positions"][0]["protection"].pop("catalytic")),
        "check_extra_key": ("full", lambda c: _check(c).update(extra=1)),
        "uncovered_coverage": ("partial", lambda c: _check(c)["uncovered_chains"][0].update(coverage="covered")),
        "v1_label": ("full", lambda c: c.update(method_version="mw.mutation_candidates/v1")),
        "v1_check_in_v2": ("not_given", lambda c: c["protection_checks"].update(
            catalytic_residue_database={"status": "not_available", "reason": "not_implemented"})),
    }


@pytest.mark.parametrize("case", sorted(v2_tamperings()))
def test_validated_set_v2_rejects_each_broken_rule(cif, case):
    bases = _v2_bases(cif)
    base_name, edit = v2_tamperings()[case]
    content = bases[base_name]
    assert mc.validated_set(content) is content
    bad = copy.deepcopy(content)
    edit(bad)
    with pytest.raises(mc.MutationSetInvalid):
        mc.validated_set(bad)


def test_validated_set_v2_accepts_its_json_round_trip(cif):
    for content in _v2_bases(cif).values():
        assert mc.validated_set(json.loads(canonical_json(content))) == content


V1_FIXTURES = sorted([*(FIX / "sequence_ga").glob("m20-candidate-set-*.json"),
                      *(FIX / "reaction" / "t1").glob("m20-v1-candidate-set-*.json")])


@pytest.mark.parametrize("path", V1_FIXTURES, ids=lambda p: p.name)
def test_every_stored_v1_set_still_validates_unchanged(path):
    stored = json.loads(path.read_text())["content"]
    before = canonical_json(stored)
    assert stored["method_version"] == "mw.mutation_candidates/v1"
    assert stored["protection_checks"]["catalytic_residue_database"] == {"status": "not_available",
                                                                         "reason": "not_implemented"}
    assert mc.validated_set(stored) is stored and canonical_json(stored) == before
    assert sorted(stored["counts"]["exclusion_reason_counts"]) == sorted(K.EXCLUSION_REASONS)   # six keys
    assert stored["limitations"] == list(K.LIMITATIONS)


def v1_tamperings():
    first = K.REFERENCE_REQUIRED
    return {
        "catalytic_checked": lambda c: c["protection_checks"]["catalytic_residue_database"].update(status="checked"),
        "catalytic_v2_not_given": lambda c: c["protection_checks"].update(catalytic_residue_database={
            "status": "not_checked", "reason": "annotation_not_given", "annotation": None}),
        "v2_parameter": lambda c: c["parameters"].update(catalytic_annotation=None),
        "v2_protection_key": lambda c: c["positions"][0]["protection"].update(catalytic=None),
        "v2_reason": lambda c: c["positions"][0]["protection"]["reasons"].append("catalytic_residue"),
        "seventh_count": lambda c: c["counts"]["exclusion_reason_counts"].update(catalytic_residue=0),
        "v2_sentence": lambda c: c["limitations"].__setitem__(2, K.LIMITATION_3_NOT_CHECKED),
        "v2_label": lambda c: c.update(method_version="mw.mutation_candidates/v2"),
        "count": lambda c: c["counts"].update(candidates=c["counts"]["candidates"] + 1),
        "residue_shape": lambda c: c["positions"][0]["residue"].pop("seq_label"),
        "residue_identity": lambda c: c["positions"][0]["residue"].update(
            {first[1]: c["positions"][0]["residue"]["chain_auth"] + "X"}),
        "limitation": lambda c: c["limitations"].__setitem__(1, "이 목록은 추천이다."),
    }


@pytest.mark.parametrize("case", sorted(v1_tamperings()))
def test_validated_set_v1_path_still_rejects_tampering(case):
    stored = json.loads((FIX / "sequence_ga" / "m20-candidate-set-1ubq-8pos.json").read_text())["content"]
    mc.validated_set(stored)
    bad = copy.deepcopy(stored)
    v1_tamperings()[case](bad)
    with pytest.raises(mc.MutationSetInvalid):
        mc.validated_set(bad)
