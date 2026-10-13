"""M29 T4: closed sets, order, fixed sentences and mirrored M7 values of ``structure_repair_constants`` (spec 2-4,
3.7, 6.2). The expected strings below are copied from .dryforge/spec.md by hand; a mismatch of one character fails."""
from __future__ import annotations

from pathlib import Path

import pytest

from mw import structure_repair as sr
from mw import structure_repair_constants as K
from mw.openmm_bundle import FORCEFIELD_SHA256
from mw.tools import openmm_method
from mw.tools.sasa import AMINO

MW = Path(__file__).resolve().parents[1] / "mw"


def test_closed_sets_and_their_order():
    assert K.REPAIR_CLASSES == ("chain_parts_merged", "side_chain_atoms_added", "terminal_oxt_added",
                                "internal_gap_filled", "nonstandard_replaced")
    assert K.REFUSAL_REASONS == ("chain_identity_duplicate", "unsupported_residue", "unexpected_atoms",
                                 "backbone_atoms_missing", "gap_listing_missing", "gap_too_long",
                                 "m7_condition_unsupported", "atom_limit_exceeded", "nothing_to_repair")
    assert K.ADMISSION_REASON_CODES == ("unknown_field", "confirmation_missing", "argument_invalid",
                                        "structure_invalid", "already_repaired")
    assert K.UNAVAILABLE_REASON_CODES == ("process_identity_unavailable", "openmm_unavailable", "pdbfixer_unavailable")
    assert K.FAILURE_REASON_CODES == ("repair_incomplete", "repair_modeling_failed", "coordinates_changed",
                                      "unexpected_atoms_added", "repair_identity_mismatch", "repair_record_mismatch",
                                      "resource_exceeded", "engine_failed")
    assert K.ADDED_ATOM_ORIGINS == ("side_chain", "oxt", "gap_residue")
    assert K.COLLISION_CLASSES == ("protein", "ligand", "metal", "water", "other")
    assert K.RECORD_KEYS == ("schema", "method_version", "source", "result", "parameters", "method", "classes_applied",
                             "chain_parts", "chain_ends", "side_chain_repairs", "terminal_oxt", "gaps", "replaced",
                             "added_atoms", "counts", "unchanged", "new_atom_rounding", "zero_occupancy_input_atoms",
                             "collisions", "limitations")
    assert K.COUNT_KEYS == ("added_residues", "added_atoms", "side_chain_residues", "terminal_oxt", "gaps", "replaced",
                            "chain_parts_merged", "protein_heavy_atoms")
    assert K.REPORT_STATEMENT_IDS == ("repair_scope", "added_residue_count", "added_atom_count",
                                      "side_chain_residue_count", "terminal_oxt_count", "gap_count", "replaced_count",
                                      "chain_parts_merged_count", "unchanged_atom_count", "collision_min_distance",
                                      "zero_occupancy_input_atom_count")


def test_names_values_and_limits():
    assert (K.TOOL, K.PROTOCOL, K.KIND, K.SCHEMA) == ("repair_structure", "pdbfixer_repair_v1", "structure_repair",
                                                      "structure_repair@1")
    assert (K.METHOD_VERSION, K.REPAIR_POLICY, K.EVENT_PUBLISHED) == (
        "mw.structure_repair/v1", "complete_missing_atoms_v1", "structure_repair_published")
    assert K.EVENT_HANDLE_KEYS == ("record", "prepared_structure", "coordinates", "manifest")
    assert (K.REPAIR_SEED, K.MAX_GAP_RESIDUES, K.NEW_ATOM_DECIMALS) == (1, 20, 4)
    assert (K.MAX_STAGED_INPUT_BYTES, K.MAX_RECORD_BYTES, K.STAGED_INPUT_LIMIT) == (4_000_000, 4_000_000,
                                                                                   "staged_input_bytes")
    assert (K.TIMEOUT_DEFAULT_S, K.TIMEOUT_MAX_S, K.ATOM_PAGE_DEFAULT, K.ATOM_PAGE_RANGE) == (120, 240, 100, (1, 200))
    assert (K.MISSING_RESIDUES_LEFT, K.MISSING_RESIDUES_FILLED) == ("leave_gaps", "modeled_internal_gaps")
    assert K.MANIFEST_REPAIR_KEY == "repair" and K.MANIFEST_REPAIR_KEYS == ("record", "source")
    assert (K.REPAIRED_NOT_ACCEPTED, K.REPAIRED_NOT_ACCEPTED_MESSAGE) == ("repaired_structure_not_accepted",
                                                                         "보완 구조는 모델링 경로에서만 쓴다")
    assert (K.REPORT_ANALYSIS_TYPE, K.REPORT_RENDER, K.REPORT_LIST_NAME) == (
        "structure_repair", "structure_repair_markdown@1", "구조 보완 보고서")
    assert K.ORIGIN_STATEMENT_IDS == ("repair_added_residue_count", "repair_added_atom_count")
    assert K.NONSTANDARD_REPLACEMENT == {"MSE": "MET"} and K.REPLACED_ATOM_NAMES == {"MSE": {"SE": "SD"}}


def test_fixed_sentences_verbatim():
    assert K.RP1 == "보완 구조의 추가 원자는 PDBFixer가 만든 모델링 좌표이며 실험으로 관측한 좌표가 아니다."
    assert K.RP2 == "실험으로 관측한 원자의 좌표는 입력 그대로이며 추가·치환·원자 순서 변경만 기록했다."
    assert K.RP3 == "메운 틈 구간은 단순한 기하로 놓은 가상 좌표이며 실제 구조가 아니다."
    assert K.RP4 == "사슬의 관측된 끝이 서열의 끝과 다른 곳에도 말단 원자를 두었으므로 그 끝의 화학은 실제와 다를 수 있다."
    assert K.RP5 == "MSE는 MET로 바꾸었고 셀레늄 원자는 황 원자로 대체했다. 원래 이름은 보완 기록에 있다."
    assert K.RP6 == "같은 저자 체인 이름의 조각을 한 체인으로 합쳐 원자 순서가 바뀌었다. 잔기 식별자와 좌표는 그대로이다."
    assert K.SO1 == ("이 결과의 구조는 보완 구조이다. 일부 잔기와 원자는 PDBFixer가 만든 모델링 좌표이며 실험으로 관측한 "
                     "좌표가 아니다.")
    assert K.SO2 == "이 위치·보호 판정에는 모델링 원자 또는 잔기가 들어 있다."
    assert K.SO3 == ("번호 대응·참조 주석·촉매 연결·포켓 결과는 보완 전 원본 구조에서 만든 것이며 잔기 식별자 일치로 "
                     "이었다. 모델링한 잔기는 검사하지 않았다.")
    assert K.JW1 == "이 후보는 보완 구조 기준이며, 전송 본문은 이 사실을 담지 않는다."
    assert K.LIMITATION_ORDER == (K.RP1, K.RP2, K.RP3, K.RP4, K.RP5, K.RP6)


@pytest.mark.parametrize(("classes", "differs", "expected"), [
    ((), False, ("RP1", "RP2")),
    (("chain_parts_merged",), False, ("RP1", "RP2", "RP6")),
    (("internal_gap_filled",), True, ("RP1", "RP2", "RP3", "RP4")),
    (K.REPAIR_CLASSES, True, ("RP1", "RP2", "RP3", "RP4", "RP5", "RP6")),
    (("nonstandard_replaced", "terminal_oxt_added"), False, ("RP1", "RP2", "RP5")),
])
def test_limitations_follow_their_conditions_in_the_fixed_order(classes, differs, expected):
    got = K.applicable_limitations(classes_applied=classes, chain_end_differs=differs)
    assert got == tuple(getattr(K, name) for name in expected)


def test_limitations_refuse_unknown_conditions():
    with pytest.raises(ValueError):
        K.applicable_limitations(classes_applied=("unknown",), chain_end_differs=False)
    with pytest.raises(ValueError):
        K.applicable_limitations(classes_applied=(), chain_end_differs=None)


def test_mirrored_values_match_the_m7_code_and_the_pinned_force_field():
    assert set(K.STANDARD_RESIDUES) == set(AMINO) and len(K.STANDARD_RESIDUES) == 20
    assert K.M7_ATOM_CAP == openmm_method.ATOM_CAP
    source = (MW / "tools" / "openmm_method.py").read_text()
    assert "1.1 <= distance <= 1.7" in source and K.PEPTIDE_CN_RANGE_A == (1.1, 1.7)
    assert 'abs(x) > 1e6' in source and K.COORDINATE_ABS_MAX_A == 1e6
    assert '{"N", "CA", "C", "O"}' in source and set(K.BACKBONE_ATOMS) == {"N", "CA", "C", "O"}
    assert '{"C", "N", "O", "S"}' in source and set(K.HEAVY_ELEMENTS) == {"C", "N", "O", "S"}
    assert K.TEMPLATE_FILE in FORCEFIELD_SHA256 and K.TEMPLATE_FILE in source.replace('" / "', "/")
    for reason in (sr.M7_SEQUENCE_GAP, sr.M7_PEPTIDE_GEOMETRY, sr.M7_ALTLOC, sr.M7_ATOM_IDENTITY,
                   sr.M7_RESIDUE_IDENTITY, sr.M7_COORDINATE, sr.M7_NO_PROTEIN):
        assert f'"{reason}"' in source, reason


def test_m7_reason_is_the_code_or_else_the_message():
    from mw.core.errors import FailureClass, ToolFailure
    coded = ToolFailure(FailureClass.precondition, "unsupported peptide C-N distance",
                        detail={"reason_code": "peptide_geometry"})
    plain = ToolFailure(FailureClass.input_invalid, "ambiguous atom identity", detail={"residue": {}})
    assert (sr.m7_reason(coded), sr.m7_reason(plain)) == ("peptide_geometry", "ambiguous atom identity")


def test_the_fixed_method_is_the_pinned_one():
    assert sr.fixed_method() == {"engine": "PDBFixer", "pdbfixer_version": "1.12.0",
                                 "openmm_distribution_version": "8.6.0", "forcefield_files_sha256": FORCEFIELD_SHA256}
    assert tuple(sr.fixed_method()) == K.METHOD_KEYS
