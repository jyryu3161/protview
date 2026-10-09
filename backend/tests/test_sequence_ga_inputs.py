"""M23 T2 server pure modules: sequence GA constants, admission (reason by reason, in the spec order), GA parameter
normalization and cross rules, combination space and individual keys, the RDKit-free ligand SDF / box partial check
(cross-checked against the unmodified docking worker in its own interpreter), individual M18 arguments, pins, hashes,
the call key, reuse records and the budget arithmetic (spec .dryforge/spec.md 2, 3, 4, 7).

Expected sets, sentences and numbers are typed from the spec text, computed by hand, or taken from the independent
T1 oracle (``fixtures/sequence_ga/expected.json``), never copied from the module under test. Store-dependent
admission uses a real run built through the product HTTP path on public 1UBQ (``sequence_ga_fixture.real_world``).
The worker cross-check runs ``.deps/docking/venv-locked/bin/python`` (fails, never skips, when it is missing).
"""
from __future__ import annotations

import ast
import base64
import copy
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import m20_v2_fixture as V2
import pytest
import sequence_ga_fixture as SF

from mw import docking_batch_constants as BC
from mw import docking_constants as C
from mw import docking_inputs
from mw import mutation_model_constants as MK
from mw import sequence_ga_constants as SC
from mw import sequence_ga_inputs as GI
from mw.core.errors import FailureClass, ToolFailure

MW = Path(__file__).resolve().parents[1] / "mw"
ROOT = Path(__file__).resolve().parents[2]
DOCKING_PYTHON = ROOT / ".deps/docking/venv-locked/bin/python"
DOCKING_WORKER = MW / "jobs/docking_worker.py"
EXPECTED = SF.EXPECTED
TINY = SF.TINY["content"]
EIGHT = SF.EIGHT["content"]
SET_HANDLE = "obj://run_x/mutation_candidate_set/" + "a" * 64
SDF_HANDLE = "obj://run_x/chemical_raw_input/" + "b" * 64


def _reason(fn, *args, cls=FailureClass.input_invalid, **kwargs) -> str:
    with pytest.raises(ToolFailure) as caught:
        fn(*args, **kwargs)
    assert caught.value.cls is cls
    return caught.value.detail["reason_code"]


def _args(**changes) -> dict:
    args = {"candidate_set": SET_HANDLE, "ligand": {"source": "sdf", "sdf_handle": SDF_HANDLE},
            "box": {"source": "ligand_range", "margin_A": 8}, "parameters": {"seed": 42},
            "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7", "acknowledgement": dict(SF.ACK),
            "ga": dict(SF.DEFAULT_GA)}
    args.update(changes)
    return args


def _validate(args, timeout_s=7800):
    return GI.validate_arguments(args, timeout_s)


# ---------------------------------------------------------------- closed constants (spec 2, 3, 4, 6, 7, 11)


def test_constants_match_spec():
    assert (SC.PROTOCOL, SC.TOOL, SC.ENGINE) == ("sequence_ga_dock_v1", "sequence_ga_design", "qvina")
    assert (SC.SUMMARY_SCHEMA, SC.SELECTION_SCHEMA) == ("sequence_ga_result@1", "sequence_ga_selection@1")
    assert (SC.MODEL_SCHEMA, SC.STRUCTURE_OBJECT_SCHEMA) == ("mutation_set_model@1",
                                                             "mutation_set_model_structure@1")
    assert (SC.MODEL_KIND, SC.STRUCTURE_OBJECT_KIND) == ("mutation_set_model", "mutation_set_model_structure")
    assert SC.MODEL_METHOD_VERSION == "mw.mutation_set_model/v1"
    assert (SC.INDIVIDUAL_EVENT, SC.SUMMARY_EVENT) == ("sequence_ga_individual_published", "sequence_ga_published")
    assert (SC.WORKER_INPUT_SCHEMA, SC.WORKER_OUTPUT_SCHEMA) == ("sequence_ga_worker_input@1",
                                                                 "sequence_ga_worker_output@1")
    assert SC.MULTI_MUTATION_METHOD == {"multi_mutation": "sequential_structure_order_round4"}
    assert SC.GA_KEYS == ("seed", "population_size", "generations", "elite_count", "tournament_size",
                          "crossover_fraction", "random_fraction", "max_mutations", "patience",
                          "max_new_evaluations", "total_s")
    assert SC.GA_RANGES == {"seed": (0, 2147483647, None), "population_size": (4, 16, 8), "generations": (1, 8, 5),
                            "elite_count": (0, 4, 2), "tournament_size": (2, 4, 2),
                            "crossover_fraction": (0.0, 1.0, 0.5), "random_fraction": (0.0, 0.5, 0.2),
                            "max_mutations": (1, 4, 3), "patience": (1, 8, 3), "max_new_evaluations": (4, 64, 32),
                            "total_s": (600, 14400, 7200)}
    assert (SC.MAX_POSITIONS, SC.MAX_CANDIDATES, SC.MAX_POPULATION, SC.MAX_GENERATIONS, SC.MAX_NEW_EVALUATIONS) == \
        (400, 7600, 16, 8, 64)
    assert (SC.MODEL_STEP_S, SC.DOCKING_STEP_S, SC.TOTAL_S_MAX, SC.FINISH_MARGIN_S, SC.TIMEOUT_MAX_S) == \
        (240, 300, 14400, 600, 15000)
    assert SC.DOCKING_STEP_S == BC.PER_CANDIDATE_S and SC.MODEL_STEP_S == MK.TIMEOUT_MAX_S
    assert (SC.MAX_MODEL_OBJECT_BYTES, SC.MAX_OUTPUT_BYTES, SC.PER_INDIVIDUAL_OUTPUT_MAX, SC.MAX_SUMMARY_BYTES,
            SC.MAX_STAGED_BYTES) == (16 * 2**20, 256 * 2**20, 32 * 2**20, 2**20, 16 * 2**20)
    assert (SC.NEED_MARGIN_S, SC.RAISE_MARGIN_S, SC.MAX_RAISE_EXPENSIVE_CALLS, SC.MAX_RAISE_WALL_CLOCK_S) == \
        (300, 60, 140, 15000)
    assert (SC.SECONDS_PER_UNIT, SC.UNITS_PER_EVALUATION, SC.CONSECUTIVE_FAILURE_LIMIT,
            SC.M18_HEAVY_ATOM_ESTIMATE) == (270, 2, 5, 4890)
    assert (SC.DRAW_RETRIES, SC.CHILD_RETRIES, SC.B_RETRIES) == (50, 20, 3) == \
        tuple(EXPECTED["constants"][k] for k in ("DRAW_RETRIES", "CHILD_RETRIES", "B_RETRIES"))
    assert SC.ADMISSION_STEPS == (
        ("invalid_job_arguments",), ("confirmation_missing", "acknowledgement_missing"),
        ("candidate_set_invalid", "structure_invalid"),
        ("ligand_record_count", "ligand_unparseable", "ligand_multiple_fragments", "ligand_element_not_allowed",
         "ligand_too_many_atoms", "ligand_not_3d", "box_invalid", "box_too_large"),
        ("process_identity_unavailable", "openmm_unavailable", "pdbfixer_unavailable", "worker_missing",
         "engine_missing", "engine_hash_mismatch", "handshake_failed", "version_mismatch"),
        ("openmm_preflight_failed", "residue_mismatch", "box_no_receptor_atoms"), ("ga_space_too_small",),
        ("staged_input_bytes",), ("ga_limit_raise_required",))
    assert set(SC.LIGAND_BOX_REASONS) <= set(C.REASONS)
    assert SC.STOP_REASONS == ("generations_complete", "no_change", "space_exhausted", "evaluation_limit",
                               "time_exhausted", "cancelled", "worker_failed", "resource_exceeded",
                               "reference_failed", "repeated_failure")
    assert {r for r, s in SC.STATUS_BY_STOP_REASON.items() if s == "complete"} == \
        {"generations_complete", "no_change", "space_exhausted"}
    assert {r for r, s in SC.STATUS_BY_STOP_REASON.items() if s == "partial"} == \
        {"evaluation_limit", "time_exhausted", "cancelled", "worker_failed", "resource_exceeded",
         "reference_failed", "repeated_failure"}
    assert SC.ORIGINS == ("initial", "carried", "crossover", "edit", "random")
    assert SC.EDIT_OPERATIONS == ("add", "change", "move", "remove")
    assert SC.EVALUATIONS == ("reused", "computed") and SC.STATES == ("scored", "null_result", "failed")
    assert SC.FAILED_EXTRA_REASONS == ("model_timeout", "docking_timeout", "worker_failed")


def test_copied_strings_equal_their_originals():
    assert SC.MODEL_FAILURE_REASONS == MK.FAILURE_REASON_CODES
    assert SC.DOCKING_FAILURE_REASONS == C.REASONS
    assert set(SC.FAILURE_REASONS) == set(MK.FAILURE_REASON_CODES) | set(C.REASONS) | \
        {"model_timeout", "docking_timeout", "worker_failed"}
    assert len(SC.FAILURE_REASONS) == len(set(SC.FAILURE_REASONS))
    # T10: the failure reasons of one step only, from the originals (both steps: engine_failed, resource_exceeded,
    # worker_failed)
    shared = set(MK.FAILURE_REASON_CODES) & set(C.REASONS)
    assert shared == {"engine_failed", "resource_exceeded"}
    assert set(SC.MODEL_ONLY_FAILURE_REASONS) == (set(MK.FAILURE_REASON_CODES) - shared) | {"model_timeout"} == {
        "mutation_modeling_failed", "unexpected_atoms_added", "coordinates_changed", "topology_unsupported",
        "energy_invalid", "model_timeout"}
    assert set(SC.DOCKING_ONLY_FAILURE_REASONS) == (set(C.REASONS) - shared) | {"docking_timeout"}
    assert not set(SC.MODEL_ONLY_FAILURE_REASONS) & set(SC.DOCKING_ONLY_FAILURE_REASONS)
    assert set(SC.FAILURE_REASONS) - set(SC.MODEL_ONLY_FAILURE_REASONS) - set(SC.DOCKING_ONLY_FAILURE_REASONS) == \
        shared | {"worker_failed"}
    assert SC.SCORE_LABEL == C.SCORE_LABEL and SC.SCORE_ROW_LABEL == BC.SCORE_ROW_LABELS["free"]
    assert (SC.L1, SC.L3, SC.L6) == (MK.L1, MK.L3, MK.L6)
    assert (SC.MUTANT_SIDE, SC.REFERENCE_SIDE) == ("mutant", "wild_type_reference")
    assert {SC.MUTANT_SIDE, SC.REFERENCE_SIDE} == set(C.MUTATION_MODEL_SIDES) == set(MK.STRUCTURE_SIDES)
    assert (SC.SELECTION_POLICY, SC.HYDROGEN_POLICY) == (MK.SELECTION_POLICY, MK.HYDROGEN_POLICY)


def test_s_sentences_verbatim_and_in_order():
    assert SC.STATEMENTS == {
        "S1": "서열 GA는 변이 조합 공간에서 어떤 조합을 모델링·도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 "
              "순위나 추천이 아니다. 교차·편집의 부모 선택은 작업 모듈 기록이며 서버가 다시 계산하지 않았고 변이 목록의 "
              "부모–자식 관계만 검증했다.",
        "S2": "이 실행은 시간·평가 상한·취소·기준 행 실패·연속 실패 등으로 일부만 계산되었다. 계산하지 않은 개체는 점수가 "
              "없으며 0이 아니고, 한도 도달로 멈춘 실행은 같은 설정으로 다시 해도 같은 경로를 보장하지 않는다.",
        "S3": "재사용한 개체는 같은 후보 집합·구조·리간드·상자·seed·값으로 이전에 저장된 모델링·도킹 결과를 가져온 것이며, "
              "저장된 결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있다.",
        "S4": "점수는 각 개체의 변이 구조(PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 "
              "단백질만의 모델)에 사용자가 준 리간드 좌표를 그대로 두고 자유 도킹한 qvina 점수이며, 변이의 효과나 결합 "
              "친화도를 뜻하지 않는다.",
        "S5": "OpenMM 전위는 각 구조의 Amber14-all + GBn2 값(kJ/mol)이며 서열이 다른 구조의 값은 서로 비교할 수 없고 "
              "ΔΔG·안정성이 아니다.",
        "S6": "여러 곳 변이는 구조 순서대로 한 곳씩 PDBFixer로 연속 적용한 모델이며(앞 단계에서 놓은 원자 좌표는 다음 단계 "
              "전에 소수 넷째 자리로 반올림했다) 적용 순서와 곁사슬 크기에 따라 모델이 달라질 수 있다. 구조의 충돌·전위는 "
              "점수나 선택에 쓰지 않았고(전위가 늘거나 유한하지 않은 모델만 실패로 처리), 개체마다 수용체가 다르므로 개체 "
              "점수를 나란히 두는 것은 같은 수용체 안의 비교가 아니며(개체 도킹 결과의 M18 둘째 한계 문장이 말하는 조건과 "
              "다르다) 순위나 '더 잘 결합'을 뜻하지 않는다.",
    }
    assert list(SC.STATEMENTS) == ["S1", "S2", "S3", "S4", "S5", "S6"]
    assert SC.SL5 == ("변이한 잔기 밖에서 히스티딘·시스테인 양성자 상태가 야생형 기준 구조와 다르게 지정되었으므로 두 구조의 "
                      "차이는 지정한 변이만이 아니다.")
    assert SC.MODEL_LIMITATION_ORDER == (MK.L1, MK.L3, SC.SL5, MK.L6)


def test_constants_module_has_no_imports():
    tree = ast.parse((MW / "sequence_ga_constants.py").read_text())
    assert not [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                and not (isinstance(node, ast.ImportFrom) and node.module == "__future__")]


# ---------------------------------------------------------------- step 1: argument shape and GA parameters


def test_valid_arguments_normalize():
    out = _validate(_args())
    assert out["ga"] == {**SF.DEFAULT_GA, "crossover_fraction": 0.5, "random_fraction": 0.2}
    assert out["parameters"] == {"seed": 42, "exhaustiveness": 8, "num_modes": 9, "energy_range": 3.0,
                                 "conformers": None}
    assert out["ligand"] == {"source": "sdf", "sdf_handle": SDF_HANDLE}
    assert out["box"] == {"source": "ligand_range", "margin_A": 8}          # values are step 4
    assert (out["selection_policy"], out["hydrogen_policy"]) == ("protein_only", "rebuild_pH7")
    assert out["acknowledgement"] == SF.ACK
    assert type(out["ga"]["crossover_fraction"]) is float


@pytest.mark.parametrize("key", ["receptor_handle", "receptor_model_number", "connectivity", "receptor_instance",
                                 "receptor_source", "mode", "contact_cutoff_A", "filter", "candidate_index",
                                 "seed", "anything"])
def test_unknown_keys_including_receptor_mode_cutoff_and_filter_are_refused(key):
    assert _reason(_validate, _args(**{key: None})) == "invalid_job_arguments"


@pytest.mark.parametrize("key", ["candidate_set", "ligand", "box", "parameters", "ga"])
def test_missing_required_key_refused(key):
    args = _args()
    del args[key]
    assert _reason(_validate, args) == "invalid_job_arguments"


@pytest.mark.parametrize("ligand", [{"source": "candidate", "candidate_set_handle": "h", "candidate_id": "c",
                                     "parent_sdf_handle": "p"}, {"source": "sdf"}, {"source": "sdf", "sdf_handle": ""},
                                    {"source": "sdf", "sdf_handle": 5}, {"source": "sdf", "sdf_handle": "h", "x": 1},
                                    "h", None])
def test_ligand_is_sdf_only(ligand):
    assert _reason(_validate, _args(ligand=ligand)) == "invalid_job_arguments"


@pytest.mark.parametrize("box", [{"source": "pocket"}, {"source": "manual", "center_A": [0, 0, 0]},
                                 {"source": "manual", "center_A": [0, 0, 0], "size_A": [10, 10, 10], "margin_A": 1},
                                 {"source": "ligand_range", "margin_A": 8, "center_A": [0, 0, 0]}, None, []])
def test_box_shape_is_step_one(box):
    assert _reason(_validate, _args(box=box)) == "invalid_job_arguments"


@pytest.mark.parametrize("parameters", [{}, {"seed": True}, {"seed": -1}, {"seed": 2147483648}, {"seed": 1.0},
                                        {"seed": 1, "conformers": 5}, {"seed": 1, "exhaustiveness": 33},
                                        {"seed": 1, "num_modes": 0}, {"seed": 1, "energy_range": float("nan")},
                                        {"seed": 1, "energy_range": 6}, {"seed": 1, "unknown": 1}])
def test_m18_free_parameters_are_step_one(parameters):
    assert _reason(_validate, _args(parameters=parameters)) == "invalid_job_arguments"


def test_acknowledgement_unknown_key_is_step_one():
    assert _reason(_validate, _args(acknowledgement={**SF.ACK, "other": True})) == "invalid_job_arguments"


@pytest.mark.parametrize("key", SC.GA_KEYS)
def test_every_ga_key_is_required(key):
    ga = dict(SF.DEFAULT_GA)
    del ga[key]
    assert _reason(_validate, _args(ga=ga)) == "invalid_job_arguments"


def test_ga_unknown_key_and_shape_refused():
    assert _reason(_validate, _args(ga={**SF.DEFAULT_GA, "neighbor_count": 3})) == "invalid_job_arguments"
    assert _reason(_validate, _args(ga=[1, 2])) == "invalid_job_arguments"


INT_BOUNDS = [("seed", 0, 2147483647), ("population_size", 4, 16), ("generations", 1, 8), ("elite_count", 0, 4),
              ("tournament_size", 2, 4), ("max_mutations", 1, 4), ("patience", 1, 8)]


@pytest.mark.parametrize("key,low,high", INT_BOUNDS)
def test_integer_parameter_boundaries(key, low, high):
    for value in (low, high):
        assert _validate(_args(ga={**SF.DEFAULT_GA, key: value}))["ga"][key] == value
    for value in (low - 1, high + 1, True, float(low), str(low), None):
        assert _reason(_validate, _args(ga={**SF.DEFAULT_GA, key: value})) == "invalid_job_arguments", value


def test_population_and_new_evaluation_bounds():
    for size in (4, 16):
        ga = {**SF.DEFAULT_GA, "population_size": size, "max_new_evaluations": max(size, 32)}
        assert _validate(_args(ga=ga))["ga"]["population_size"] == size
    assert _reason(_validate, _args(ga={**SF.DEFAULT_GA, "population_size": 17, "max_new_evaluations": 64})) == \
        "invalid_job_arguments"
    assert _validate(_args(ga={**SF.DEFAULT_GA, "max_new_evaluations": 64}))["ga"]["max_new_evaluations"] == 64
    assert _reason(_validate, _args(ga={**SF.DEFAULT_GA, "max_new_evaluations": 65})) == "invalid_job_arguments"


@pytest.mark.parametrize("key,low,high", [("crossover_fraction", 0.0, 1.0), ("random_fraction", 0.0, 0.5)])
def test_fractions_are_finite_reals_in_range(key, low, high):
    for value in (low, high, 0, int(high) if high == 1.0 else high):
        out = _validate(_args(ga={**SF.DEFAULT_GA, key: value}))["ga"][key]
        assert out == value and type(out) is float
    for value in (-0.0001, high + 0.0001, float("nan"), float("inf"), float("-inf"), True, False, None, "0.1"):
        assert _reason(_validate, _args(ga={**SF.DEFAULT_GA, key: value})) == "invalid_job_arguments", value


def test_negative_zero_fraction_folds_to_zero():
    out = _validate(_args(ga={**SF.DEFAULT_GA, "random_fraction": -0.0}))["ga"]["random_fraction"]
    assert out == 0.0 and math.copysign(1.0, out) == 1.0


def test_elite_cross_rule_population_minus_elite_at_least_two():
    assert _validate(_args(ga={**SF.DEFAULT_GA, "population_size": 4, "elite_count": 2}))["ga"]["elite_count"] == 2
    assert _reason(_validate, _args(ga={**SF.DEFAULT_GA, "population_size": 4, "elite_count": 3})) == \
        "invalid_job_arguments"
    assert _validate(_args(ga={**SF.DEFAULT_GA, "population_size": 6, "elite_count": 4}))["ga"]["elite_count"] == 4


def test_max_new_evaluations_at_least_population_size():
    ga = {**SF.DEFAULT_GA, "population_size": 12, "max_new_evaluations": 12}
    assert _validate(_args(ga=ga))["ga"]["max_new_evaluations"] == 12
    assert _reason(_validate, _args(ga={**ga, "max_new_evaluations": 11})) == "invalid_job_arguments"


def test_total_s_bounds_and_timeout_rule():
    for total in (600, 14400):
        assert _validate(_args(ga={**SF.DEFAULT_GA, "total_s": total}), total + 600)["ga"]["total_s"] == total
    for total in (599, 14401):
        assert _reason(_validate, _args(ga={**SF.DEFAULT_GA, "total_s": total}), 15000) == "invalid_job_arguments"
    # timeout_s in [total_s + 600, 15000]; no server default
    assert _validate(_args(), 7800) and _validate(_args(), 15000) and _validate(_args(), 7800.5)
    for timeout in (7799, 7799.99, 15001, None, True, float("nan"), float("inf"), "7800"):
        assert _reason(_validate, _args(), timeout) == "invalid_job_arguments", timeout


def test_validation_does_not_mutate_input():
    args = _args(box={"source": "manual", "center_A": [1, 2, 3], "size_A": [10, 10, 10]})
    before = copy.deepcopy(args)
    out = _validate(args)
    out["box"]["center_A"][0] = 99
    assert args == before


# ---------------------------------------------------------------- step 2: the two literals and the M18 items


@pytest.mark.parametrize("change", [{"selection_policy": "protein"}, {"hydrogen_policy": "keep"},
                                    {"selection_policy": None}, {"hydrogen_policy": 7},
                                    {"selection_policy": "PROTEIN_ONLY"}])
def test_literals_must_match_exactly(change):
    assert _reason(GI.check_confirmations, _args(**change)) == "confirmation_missing"


@pytest.mark.parametrize("key", ["selection_policy", "hydrogen_policy"])
def test_a_missing_literal_is_confirmation_missing(key):
    args = _args()
    del args[key]
    _validate(args)                                             # not a step 1 missing key (M21 precedent)
    assert _reason(GI.check_confirmations, args) == "confirmation_missing"


@pytest.mark.parametrize("ack", [None, {}, {**SF.ACK, "rigid_no_optimization": False},
                                 {**SF.ACK, "keep_input_protonation": 1}, "yes", [True]])
def test_acknowledgement_must_be_three_trues(ack):
    args = _args(acknowledgement=ack)
    if ack is None:
        del args["acknowledgement"]
    assert _reason(GI.check_confirmations, args) == "acknowledgement_missing"


def test_literal_before_acknowledgement():
    args = _args(selection_policy="x", acknowledgement={})
    assert _reason(GI.check_confirmations, args) == "confirmation_missing"


# ---------------------------------------------------------------- combination space (spec 3)


@pytest.mark.parametrize("row", EXPECTED["arithmetic"]["space_size"],
                         ids=lambda r: f"{len(r['counts'])}pos-M{r['max_mutations']}")
def test_space_size_matches_the_independent_oracle(row):
    assert GI.space_size(row["counts"], row["max_mutations"]) == row["size"]
    assert [GI.elementary(row["counts"], k) for k in range(1, len(row["elementary"]) + 1)] == row["elementary"]


def test_space_size_by_hand():
    # counts (2, 3, 1, 2): e1 = 8, e2 = 6 + 2 + 4 + 3 + 6 + 2 = 23, e3 = 6 + 12 + 4 + 6 = 28, e4 = 12
    assert [GI.elementary([2, 3, 1, 2], k) for k in range(5)] == [1, 8, 23, 28, 12]
    assert GI.space_size([2, 3, 1, 2], 3) == 59 and GI.space_size([2, 3, 1, 2], 4) == 71
    assert GI.space_size([2, 3, 1, 2], 9) == 71                                # M = min(max_mutations, P)
    assert GI.space_size([], 3) == 0 and GI.space_size([5], 4) == 5
    # the real eight-position set: 8 positions x 5 alternatives (AFHWY without the own letter)
    assert GI.space_size([5] * 8, 3) == 40 + 28 * 25 + 56 * 125 == 7740
    assert GI.space_size([5] * 8, 4) == 7740 + 70 * 625 == 51490
    assert GI.space_size([19] * 400, 4) < 2**53                                 # exact JSON integer


def test_candidate_space_of_the_real_sets():
    tiny = GI.candidate_space(TINY, 3)
    space = EXPECTED["spaces"]["s4_tiny_1ubq"]
    assert tiny["positions"] == space["positions"] == [1, 2, 3]                 # I3 is excluded (user-protected)
    assert tiny["alts"] == [space["alts"][str(p)] for p in space["positions"]] == [[0, 1], [2, 3], [4, 5]]
    assert tiny["size"] == space["size_at_cap"] == 26 and tiny["effective_max_mutations"] == 3
    assert GI.space_counts(tiny) == {"positions": 3, "candidates": 6, "effective_max_mutations": 3, "size": 26}
    assert GI.candidate_space(TINY, 1)["size"] == 6 and GI.candidate_space(TINY, 4)["effective_max_mutations"] == 3
    eight = GI.candidate_space(EIGHT, 3)
    assert eight["positions"] == list(range(8)) and [len(a) for a in eight["alts"]] == [5] * 8
    assert eight["size"] == 7740 and GI.candidate_space(EIGHT, 4)["size"] == 51490


def test_space_too_small_boundary():
    space = GI.candidate_space(TINY, 1)                                         # N = 6
    GI.require_space(space, 6)
    assert _reason(GI.require_space, space, 7) == "ga_space_too_small"
    empty = {"positions": [], "alts": [], "effective_max_mutations": 0, "size": 0}
    assert _reason(GI.require_space, empty, 4) == "ga_space_too_small"


# ---------------------------------------------------------------- individual keys (spec 3)


def test_key_text_and_parse_round_trip():
    assert GI.key_text([12, 57, 203]) == "12-57-203"
    assert GI.parse_key("12-57-203") == (12, 57, 203) and GI.parse_key("0") == (0,)
    for key in EXPECTED["spaces"]["s1_4pos_2312"]["canonical_at_cap"]:
        assert GI.key_text(GI.parse_key(key)) == key


@pytest.mark.parametrize("text", ["", "wild_type", "01", "1-01", "2-1", "1-1", "+1", "-1", "1-", "1--2", " 1",
                                  "1 ", "1-2-3-4-5", "a", "1.0", 1, None, ["1"]])
def test_malformed_keys_are_refused(text):
    with pytest.raises(ValueError):
        GI.parse_key(text)


def test_key_mutations_are_filled_from_the_candidate_set():
    space = GI.candidate_space(TINY, 3)
    rows = GI.key_mutations(TINY, space, "1-3-5")
    assert [row["candidate_index"] for row in rows] == [1, 3, 5]
    assert [(row["from"], row["to"]) for row in rows] == [("K", "W"), ("I", "W"), ("G", "W")]
    assert [row["residue"]["seq_auth"] for row in rows] == [6, 44, 76]
    assert rows[0]["residue"] == {"model_number": 1, "chain_auth": "A", "chain_label": "A", "seq_auth": 6,
                                  "seq_label": 6, "icode": "", "resname": "LYS"}
    for bad in ("0-1", "6", "2-3", "0-2-4-6"):                 # same position twice, outside the space, too many
        with pytest.raises(ValueError):
            GI.key_mutations(TINY, space, bad)
    with pytest.raises(ValueError):
        GI.key_mutations(TINY, GI.candidate_space(TINY, 2), "0-2-4")            # over the effective cap


# ---------------------------------------------------------------- step 4: ligand SDF / box partial check


def _atom_line(symbol: str, x: float, y: float, z: float) -> str:
    return f"{x:10.4f}{y:10.4f}{z:10.4f} {symbol:<3} 0  0  0  0  0  0  0  0  0  0  0  0"


def molblock(atoms: list[tuple[str, float, float, float]], bonds: list[tuple[int, int, int]],
             title: str = "SYNTHETIC-FIXTURE T2 ligand") -> str:
    lines = [title, "  T2 synthetic", "", f"{len(atoms):3d}{len(bonds):3d}  0  0  0  0  0  0  0  0999 V2000"]
    lines += [_atom_line(*atom) for atom in atoms]
    lines += [f"{a:3d}{b:3d}{order:3d}  0" for a, b, order in bonds]
    return "\n".join([*lines, "M  END", "$$$$", ""])


def alkane(carbons: int) -> str:
    """A zig-zag n-alkane with explicit hydrogens (SYNTHETIC-FIXTURE geometry, valence-correct)."""
    atoms, bonds = [], []
    for i in range(carbons):
        atoms.append(("C", 1.25 * i, 0.8 * (i % 2), 0.1 * (i % 3)))
        if i:
            bonds.append((i, i + 1, 1))
    for i in range(carbons):
        hydrogens = 3 if i in (0, carbons - 1) else 2
        for h in range(hydrogens):
            atoms.append(("H", 1.25 * i + 0.3 * (h == 2), 0.8 * (i % 2) + (1.0 if h == 0 else -0.5),
                          0.1 * (i % 3) + (0.9 if h == 1 else -0.9 if h == 2 else 0.0)))
            bonds.append((i + 1, len(atoms), 1))
    return molblock(atoms, bonds)


PHENOL = SF.PHENOL.decode()
PHENOL_LINES = PHENOL.split("$$$$")[0].rstrip("\n").split("\n")


def _phenol(edit) -> str:
    lines = list(PHENOL_LINES)
    edit(lines)
    return "\n".join(lines) + "\n$$$$\n"


def _set_symbol(index: int, symbol: str):
    return lambda lines: lines.__setitem__(index, lines[index][:31] + f"{symbol:<3}" + lines[index][34:])


PHENOL_ATOMS = [(line[31:34].strip(), float(line[0:10]), float(line[10:20]), float(line[20:30]))
                for line in PHENOL_LINES[4:17]]
PHENOL_BONDS = [(int(line[0:3]), int(line[3:6]), int(line[6:9])) for line in PHENOL_LINES[17:30]]
METHANE = [("C", 30.0, 30.0, 30.0), ("H", 31.0, 30.0, 30.5), ("H", 29.0, 30.0, 30.5), ("H", 30.0, 31.0, 29.5),
           ("H", 30.0, 29.0, 29.5)]
TWO_FRAGMENTS = molblock(PHENOL_ATOMS + METHANE, PHENOL_BONDS + [(14, n, 1) for n in (15, 16, 17, 18)])
# Two fragments where the second holds a five-bond carbon: RDKit sanitization refuses it (ligand_unparseable)
# before the worker counts fragments; the server cannot see valence (documented divergence, both refuse).
TWO_FRAGMENTS_BAD_VALENCE = molblock(PHENOL_ATOMS + METHANE + [("H", 30.0, 30.5, 31.5)],
                                     PHENOL_BONDS + [(14, n, 1) for n in (15, 16, 17, 18, 19)])
SE_PHENOL = _phenol(_set_symbol(10, "Se"))
D_PHENOL = _phenol(_set_symbol(16, "D"))
R_PHENOL = _phenol(_set_symbol(16, "R#"))
CL_UPPER = _phenol(_set_symbol(16, "CL"))
NO_M_END = _phenol(lambda lines: lines.remove("M  END"))
BAD_COUNTS = _phenol(lambda lines: lines.__setitem__(3, "abc"))
FAR_X = _phenol(lambda lines: lines.__setitem__(4, "999999.999" + lines[4][10:]))
V3000 = _phenol(lambda lines: lines.__setitem__(3, lines[3].replace("V2000", "V3000")))
H2 = molblock([("H", 0.0, 0.0, 0.0), ("H", 0.74, 0.0, 0.3)], [(1, 2, 1)])
FLAT_X = molblock([("C", 1.0, 0.0, 0.0), ("O", 1.0, 1.4, 0.2), ("H", 1.0, -0.5, 0.9), ("H", 1.0, -0.5, -0.9),
                   ("H", 1.0, -1.0, 0.1), ("H", 1.0, 1.9, -0.6)],
                  [(1, 2, 1), (1, 3, 1), (1, 4, 1), (1, 5, 1), (2, 6, 1)])
NEAR = [[24.0, 36.5, 24.9], [22.0, 36.0, 25.0]]       # receptor points near the phenol
FAR = [[200.0, 200.0, 200.0]]
RANGE8 = {"source": "ligand_range", "margin_A": 8}
MANUAL = {"source": "manual", "center_A": [23.5, 36.5, 24.9], "size_A": [20, 20, 20]}
# (name, sdf, box, receptor points, expected server reason, expected worker reason). "m18_rule": the server reason
# is the M18 argument rule the standalone M18 server also applies before any worker (checked separately below).
CASES = [
    ("phenol", PHENOL, RANGE8, NEAR, None, None),
    ("phenol_manual", PHENOL, MANUAL, NEAR, None, None),
    ("two_records", PHENOL + PHENOL, RANGE8, NEAR, "ligand_record_count", "ligand_record_count"),
    ("v3000", V3000, RANGE8, NEAR, "ligand_unparseable", "ligand_unparseable"),
    ("nul_byte", PHENOL.replace("SYNTHETIC", "SYN\x00THETIC", 1), RANGE8, NEAR, "ligand_unparseable",
     "ligand_unparseable"),
    ("two_fragments", TWO_FRAGMENTS, RANGE8, NEAR, "ligand_multiple_fragments", "ligand_multiple_fragments"),
    ("selenium", SE_PHENOL, RANGE8, NEAR, "ligand_element_not_allowed", "ligand_element_not_allowed"),
    ("alkane_100", alkane(100), MANUAL, NEAR, None, None),
    ("alkane_101", alkane(101), MANUAL, NEAR, "ligand_too_many_atoms", "ligand_too_many_atoms"),
    ("planar", SF.PLANAR.decode(), RANGE8, NEAR, "ligand_not_3d", "ligand_not_3d"),
    ("hydrogen_only", H2, MANUAL, NEAR, "ligand_unparseable", "ligand_unparseable"),
    ("coordinate_range", FAR_X, RANGE8, NEAR, "ligand_unparseable", "ligand_unparseable"),
    ("deuterium", D_PHENOL, RANGE8, NEAR, None, None),
    # the server leaves these to the worker (never stricter)
    ("implicit_h", (SF.FIX / "docking/synthetic-ligand-implicit-h.sdf").read_text(), MANUAL, NEAR, None,
     "ligand_hydrogens_missing"),
    ("bad_counts", BAD_COUNTS, RANGE8, NEAR, None, "ligand_unparseable"),
    ("no_m_end", NO_M_END, RANGE8, NEAR, None, "ligand_unparseable"),
    ("upper_case_symbol", CL_UPPER, RANGE8, NEAR, None, None),          # RDKit reads "CL" as Cl; server: unread
    ("query_atom", R_PHENOL, RANGE8, NEAR, None, "ligand_element_not_allowed"),
    # box
    ("manual_41", PHENOL, {**MANUAL, "size_A": [41, 20, 20]}, NEAR, "box_too_large", "box_too_large"),
    ("range_margin_20", PHENOL, {"source": "ligand_range", "margin_A": 20}, NEAR, "box_too_large",
     "box_too_large"),
    ("range_zero_side", FLAT_X, {"source": "ligand_range", "margin_A": 0}, [[1.0, 0.0, 0.0]], "box_invalid",
     "box_invalid"),
    ("instance_range", PHENOL, {"source": "instance_range", "margin_A": 8}, NEAR, "box_invalid", "box_invalid"),
    ("far_manual", PHENOL, MANUAL, FAR, "box_no_receptor_atoms", "box_no_receptor_atoms"),
    ("ligand_before_box", SE_PHENOL, {**MANUAL, "size_A": [41, 20, 20]}, FAR, "ligand_element_not_allowed",
     "ligand_element_not_allowed"),
    ("manual_side_5", PHENOL, {**MANUAL, "size_A": [5, 20, 20]}, NEAR, "m18_rule", None),
    ("margin_21", PHENOL, {"source": "ligand_range", "margin_A": 21}, NEAR, "m18_rule", "box_too_large"),
    # documented divergence (multi-defect: a valence error RDKit reports first; both refuse)
    ("fragments_and_bad_valence", TWO_FRAGMENTS_BAD_VALENCE, RANGE8, NEAR, "ligand_multiple_fragments",
     "ligand_unparseable"),
]


def _projection(points: list[list[float]]) -> dict:
    return {"protein": [{"chain_auth": "A", "residues": [{"residue": {}, "atoms": [
        {"atom_name": "CA", "element": "C", "coordinates_A": point} for point in points]}]}]}


def server_check(raw: bytes, box: dict, points: list[list[float]]) -> tuple[str | None, dict | None]:
    try:
        ligand = GI.check_ligand_sdf(raw)
        request = GI.request_box(copy.deepcopy(box))
        computed = GI.ligand_box(request, ligand)
        GI.check_box_receptor(computed, _projection(points))
    except ToolFailure as exc:
        return exc.detail["reason_code"], None
    return None, computed


WORKER_PROBE = r"""
import base64, hashlib, importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("docking_worker_t2_probe", sys.argv[1])
dw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dw)
from rdkit import Chem
request = json.load(sys.stdin)
missing = Path(sys.argv[2])
out = {"cases": [], "symbols": {}}
for case in request["cases"]:
    raw = base64.b64decode(case["sdf"])
    payload = {"receptor": {"handle": "h", "format": "cif", "model_number": 1, "instance": None,
                            "connectivity": {"kind": "sidecar", "sidecar": None}, "source": "mutation_model"},
               "ligand": {"source": "sdf", "sdf": {"b64": case["sdf"], "sha256": hashlib.sha256(raw).hexdigest()}},
               "mode": "free", "box": case["box"],
               "parameters": {"seed": 1, "exhaustiveness": 1, "num_modes": 1, "energy_range": 3.0, "conformers": None}}
    shared = {"raw": b"", "sidecar_raw": None, "heavy": [{"xyz": p} for p in case["points"]],
              "checked": {"rows": [], "instance_sites": [], "removed_instance": None}}
    try:
        dw.dock_row(payload, missing, shared, ("", {}))
        reason = "not_refused_and_not_stopped"
    except dw.DockingWorkerError as exc:
        reason = exc.reason_code
    except OSError:
        reason = None        # every check before the receptor PDBQT write passed
    box = None
    if case["box"]["source"] == "ligand_range":
        try:
            box = dw.range_box(dw._heavy_points(dw.read_sdf(raw)), float(case["box"]["margin_A"]))
        except dw.DockingWorkerError:
            pass
    out["cases"].append({"reason": reason, "box": box})
table = Chem.GetPeriodicTable()
for symbol in request["symbols"]:
    block = "x\n  probe\n\n  1  0  0  0  0  0  0  0  0  0999 V2000\n" + \
        "    0.0000    0.0000    0.0000 %-3s 0  0  0  0  0  0  0  0  0  0  0  0\nM  END\n" % symbol
    mol = Chem.MolFromMolBlock(block, sanitize=True, removeHs=False, strictParsing=True)
    out["symbols"][symbol] = None if mol is None else mol.GetAtomWithIdx(0).GetAtomicNum()
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def worker_verdicts(tmp_path_factory):
    assert DOCKING_PYTHON.exists(), "the docking environment is required (never skipped)"
    request = {"cases": [{"sdf": base64.b64encode(sdf.encode("utf-8", "surrogateescape")).decode(),
                          "box": copy.deepcopy(box if box["source"] != "manual" else
                                               {**box, "center_A": [float(x) for x in box["center_A"]],
                                                "size_A": [float(x) for x in box["size_A"]]}),
                          "points": points} for _name, sdf, box, points, _s, _w in CASES],
               "symbols": sorted(GI.ATOMIC_NUMBERS)}
    proc = subprocess.run([str(DOCKING_PYTHON), "-I", "-c", WORKER_PROBE, str(DOCKING_WORKER),
                           str(tmp_path_factory.mktemp("probe") / "missing")],
                          input=json.dumps(request), capture_output=True, text=True, timeout=300, check=False,
                          env={"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1"})
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def test_server_partial_check_against_the_docking_worker(worker_verdicts):
    """Same SDF and box: the server refuses only with the worker's own reason (or the M18 argument rule), and when
    the server passes, the worker passes too or refuses with a reason the server cannot decide."""
    assert len(worker_verdicts["cases"]) == len(CASES)
    for (name, sdf, box, points, expected_server, expected_worker), verdict in zip(CASES, worker_verdicts["cases"],
                                                                                   strict=True):
        server, computed = server_check(sdf.encode("utf-8", "surrogateescape"), box, points)
        assert verdict["reason"] == expected_worker, (name, verdict)
        if expected_server == "m18_rule":
            assert server == "box_invalid", name
            continue
        assert server == expected_server, (name, server)
        if name != "fragments_and_bad_valence":
            assert server is None or server == verdict["reason"], name          # never a different reason
        if verdict["box"] is not None and computed is not None:
            assert computed["center_A"] == verdict["box"]["center_A"], name     # bit-identical range box
            assert computed["size_A"] == verdict["box"]["size_A"], name


def test_the_m18_argument_box_rules_are_the_standalone_m18_admission(worker_verdicts):
    for name, _sdf, box, _points, expected_server, _worker in CASES:
        if expected_server != "m18_rule":
            continue
        args = {"receptor_source": {"kind": "mutation_model", "mutation_model": "h", "side": "mutant"},
                "ligand": {"source": "sdf", "sdf_handle": "s"}, "mode": "free", "box": box,
                "parameters": {"seed": 1}, "acknowledgement": dict(SF.ACK)}
        assert _reason(docking_inputs.validate_arguments, args) == "box_invalid", name


def test_element_symbols_read_as_rdkit_reads_them(worker_verdicts):
    assert worker_verdicts["symbols"] == {symbol: number for symbol, number in GI.ATOMIC_NUMBERS.items()}


def test_server_reads_without_doubt_or_leaves_it_to_the_worker():
    assert GI.check_ligand_sdf(SF.PHENOL) == {
        "read": True, "heavy_atoms": 7, "heavy_points": [
            [24.3466, 36.9891, 24.912], [23.9833, 35.8276, 24.2405], [22.6573, 35.4106, 24.2405],
            [21.6946, 36.1551, 24.912], [22.0579, 37.3167, 25.5836], [23.3839, 37.7337, 25.5836],
            [25.6439, 37.3971, 24.912]]}
    for text in (BAD_COUNTS, NO_M_END, CL_UPPER, R_PHENOL):
        assert GI.check_ligand_sdf(text.encode())["read"] is False
    assert _reason(GI.check_ligand_sdf, b"\xff\xfe") == "ligand_unparseable"
    assert _reason(GI.check_ligand_sdf, b"   \n$$$$\n") == "ligand_record_count"          # zero records
    assert _reason(GI.check_ligand_sdf, b"title\n\n\n") == "ligand_unparseable"
    zero = molblock([], [])
    assert _reason(GI.check_ligand_sdf, zero.encode()) == "ligand_unparseable"


def test_phenol_range_box_by_hand():
    # heavy x 21.6946..25.6439, y 35.4106..37.7337, z 24.2405..25.5836; center = (min + max) / 2,
    # side = (max - min) + 2 * 8, rounded to 1e-6
    box = GI.ligand_box(GI.request_box({"source": "ligand_range", "margin_A": 8}), GI.check_ligand_sdf(SF.PHENOL))
    assert box == {"center_A": [23.66925, 36.57215, 24.91205], "size_A": [19.9493, 18.3231, 17.3431],
                   "source": "ligand_range", "margin_A": 8.0}
    manual = GI.ligand_box(GI.request_box({"source": "manual", "center_A": [1, -0.0, 2], "size_A": [10, 12, 14]}),
                           {"read": False, "heavy_points": None, "heavy_atoms": None})
    assert manual == {"center_A": [1.0, 0.0, 2.0], "size_A": [10.0, 12.0, 14.0], "source": "manual",
                      "margin_A": None}
    assert GI.ligand_box({"source": "ligand_range", "margin_A": 8.0},
                         {"read": False, "heavy_points": None, "heavy_atoms": None}) is None


def test_box_receptor_inside_is_inclusive():
    box = {"center_A": [0.0, 0.0, 0.0], "size_A": [10.0, 10.0, 10.0], "source": "manual", "margin_A": None}
    GI.check_box_receptor(box, _projection([[5.0, 5.0, -5.0]]))                 # on the face counts
    assert _reason(GI.check_box_receptor, box, _projection([[5.0001, 0.0, 0.0]])) == "box_no_receptor_atoms"
    hydrogen_only = {"protein": [{"chain_auth": "A", "residues": [{"residue": {}, "atoms": [
        {"atom_name": "H", "element": "H", "coordinates_A": [0.0, 0.0, 0.0]}]}]}]}
    assert _reason(GI.check_box_receptor, box, hydrogen_only) == "box_no_receptor_atoms"
    GI.check_box_receptor(None, _projection([]))                                 # unread SDF: left to the worker


# ---------------------------------------------------------------- store-dependent admission (real run)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return SF.real_world(tmp_path_factory.mktemp("seqga_inputs"))


def _admit(world, timeout_s=1200, **changes):
    return GI.admission(world["run"], SF.args_for(world, **changes), timeout_s)


def test_admission_of_a_valid_request(world):
    admitted = _admit(world)
    content = admitted["candidate_set"]
    # the world's set is tool-built, so v2 since M26 (no catalytic annotation): it equals the stored v1 TINY set
    # except the v2 position field protection.catalytic, which is null (not checked) on every position
    assert (content["method_version"], TINY["method_version"]) == ("mw.mutation_candidates/v2",
                                                                    "mw.mutation_candidates/v1")
    assert all(position["protection"]["catalytic"] is None for position in content["positions"])
    assert [{**p, "protection": {k: v for k, v in p["protection"].items() if k != "catalytic"}}
            for p in content["positions"]] == TINY["positions"]
    assert content["candidates"] == TINY["candidates"]
    assert admitted["structure"] == {"handle": world["structure"], "model_number": 1,
                                     "structure_kind": "prepared_structure"}
    assert admitted["ligand"] == {"sdf_handle": world["phenol"], "sdf_sha256": hashlib.sha256(SF.PHENOL).hexdigest()}
    assert admitted["arguments"]["box"] == {"source": "ligand_range", "margin_A": 8.0}
    assert admitted["box"]["center_A"] == [23.66925, 36.57215, 24.91205]
    assert admitted["space"]["size"] == 26 and admitted["space"]["positions"] == [1, 2, 3]
    assert admitted["arguments"]["parameters"] == {"seed": 42, "exhaustiveness": 4, "num_modes": 5,
                                                   "energy_range": 3.0, "conformers": None}


@pytest.fixture(scope="module")
def checked_world(tmp_path_factory):
    """M26 spec 9: a fresh world plus a v2 set of the TINY positions built by the M20 tool with a catalytic annotation
    (``link_reaction_knowledge`` over the LABELLED SYNTHETIC 0SY8 reaction set of ``m20_v2_fixture``: made-up rows
    naming 1UBQ chain A, K6 matched)."""
    root = tmp_path_factory.mktemp("seqga_inputs_v2")
    world = SF.real_world(root / "runs")
    run = world["run"]
    with pytest.MonkeyPatch.context() as patch:
        V2.activate_ubq(root / "reaction_reference", patch)
        try:
            knowledge = V2.link_ubq(run, world["structure"])
            world["checked"] = run.call("generate_mutation_candidates", {
                "structure": world["structure"], **V2.TINY_ARGS, "catalytic_annotation": knowledge}).handle
        finally:
            V2.CF.reset_caches()
    return world


def test_admission_of_a_v2_set_with_a_checked_catalytic_annotation(checked_world):
    admitted = _admit(checked_world, candidate_set=checked_world["checked"])
    content = admitted["candidate_set"]
    assert content["method_version"] == "mw.mutation_candidates/v2"
    assert content["protection_checks"]["catalytic_residue_database"]["status"] == "checked"
    by = {p["residue"]["seq_auth"]: p for p in content["positions"]}
    assert (by[6]["status"], by[6]["protection"]["reasons"]) == ("excluded", ["catalytic_residue"])
    # the GA space is the positions with candidates: I3 (user_protected) and K6 (catalytic_residue) are not in it
    assert admitted["space"]["positions"] == [2, 3]
    assert admitted["structure"]["handle"] == checked_world["structure"]


class _HidingStore:
    """The run's store with one handle unknown (a structure that is not a prepared structure of this run)."""

    def __init__(self, store, hidden: str) -> None:
        self._store, self._hidden = store, hidden

    def meta(self, handle):
        if handle == self._hidden:
            raise KeyError(handle)
        return self._store.meta(handle)

    def __getattr__(self, name):
        return getattr(self._store, name)


class _RunView:
    def __init__(self, run, hidden: str) -> None:
        self.store, self.run_id = _HidingStore(run.store, hidden), run.run_id


def test_admission_reasons_in_order(world):
    run = world["run"]
    foreign = "obj://other_run/mutation_candidate_set/" + "0" * 64
    bad_ga = {**SF.SMALL_GA, "elite_count": 3}
    # 1 before everything (ga, timeout, ligand handle kind)
    assert _reason(_admit, world, ga=bad_ga, selection_policy="x", candidate_set=foreign,
                   ligand={"source": "sdf", "sdf_handle": world["planar"]}) == "invalid_job_arguments"
    assert _reason(_admit, world, 1199, selection_policy="x") == "invalid_job_arguments"
    assert _reason(_admit, world, selection_policy="x",
                   ligand={"source": "sdf", "sdf_handle": world["receptor"]}) == "invalid_job_arguments"
    assert _reason(_admit, world, ligand={"source": "sdf", "sdf_handle": world["tiny"]}) == "invalid_job_arguments"
    # 2 before 3
    assert _reason(_admit, world, selection_policy="x", candidate_set=foreign) == "confirmation_missing"
    assert _reason(_admit, world, acknowledgement={}, candidate_set=foreign) == "acknowledgement_missing"
    # 3 before 4
    for handle in (foreign, world["structure"], world["phenol"], "", 7, None):
        assert _reason(_admit, world, candidate_set=handle,
                       ligand={"source": "sdf", "sdf_handle": world["planar"]}) == "candidate_set_invalid", handle
    hidden = _RunView(run, world["structure"])
    assert _reason(GI.admission, hidden, SF.args_for(world, ligand={"source": "sdf", "sdf_handle": world["planar"]}),
                   1200) == "structure_invalid"
    # 4: the ligand before the box
    planar = {"source": "sdf", "sdf_handle": world["planar"]}
    assert _reason(_admit, world, ligand=planar, box={"source": "instance_range", "margin_A": 8}) == "ligand_not_3d"
    assert _reason(_admit, world, box={"source": "instance_range", "margin_A": 8}) == "box_invalid"
    assert _reason(_admit, world, box={"source": "manual", "center_A": [0, 0, 0], "size_A": [5, 10, 10]}) == \
        "box_invalid"
    assert _reason(_admit, world, box={"source": "ligand_range", "margin_A": 20}) == "box_too_large"
    # a set without candidates is admitted here; step 7 refuses it
    assert _admit(world, candidate_set=world["empty"])["space"]["size"] == 0


def test_admission_creates_no_events(world):
    run = world["run"]
    before = len(list(run.events.read()))
    _admit(world)
    with pytest.raises(ToolFailure):
        _admit(world, selection_policy="x")
    assert len(list(run.events.read())) == before


@pytest.fixture(scope="module")
def projection(world):
    from mw.tools import openmm_method

    return openmm_method.preflight(world["run"].store, world["structure"], seed=1)


def test_steps_after_the_preflight(world, projection):
    admitted = _admit(world)
    assert GI.after_preflight(admitted, projection) == {"projection_heavy_atoms": 602, "heavy_atom_warning": False}
    assert GI.projection_heavy_atoms(projection) == projection["heavy_atom_count"] == 602        # T1 (a)
    assert (GI.heavy_atom_warning(4890), GI.heavy_atom_warning(4891)) == (False, True)
    # 6 residue_mismatch: a position not one projected residue, or a 'from' letter that is not the residue's
    moved = copy.deepcopy(projection)
    for chain in moved["protein"]:
        for residue in chain["residues"]:
            if residue["residue"]["seq_auth"] == 44:
                residue["residue"] = {**residue["residue"], "icode": "A"}
    assert _reason(GI.after_preflight, admitted, moved) == "residue_mismatch"
    doubled = copy.deepcopy(projection)
    doubled["protein"].append(copy.deepcopy(doubled["protein"][0]))
    assert _reason(GI.after_preflight, admitted, doubled) == "residue_mismatch"
    letters = copy.deepcopy(admitted)
    for candidate in letters["candidate_set"]["candidates"]:
        if candidate["position_index"] == 2:
            candidate["from"] = "V"
    assert _reason(GI.after_preflight, letters, projection) == "residue_mismatch"
    # 6 box_no_receptor_atoms after residue_mismatch
    far = _admit(world, box={"source": "manual", "center_A": [500, 500, 500], "size_A": [20, 20, 20]})
    assert _reason(GI.after_preflight, far, projection) == "box_no_receptor_atoms"
    assert _reason(GI.after_preflight, far, moved) == "residue_mismatch"
    # 7 ga_space_too_small after step 6
    small = _admit(world, ga={**SF.SMALL_GA, "max_mutations": 1, "population_size": 8, "elite_count": 2})
    assert small["space"]["size"] == 6
    assert _reason(GI.after_preflight, small, projection) == "ga_space_too_small"
    far_small = _admit(world, ga={**SF.SMALL_GA, "max_mutations": 1, "population_size": 8, "elite_count": 2},
                       box={"source": "manual", "center_A": [500, 500, 500], "size_A": [20, 20, 20]})
    assert _reason(GI.after_preflight, far_small, projection) == "box_no_receptor_atoms"
    assert _reason(GI.after_preflight, _admit(world, candidate_set=world["empty"]), projection) == \
        "ga_space_too_small"


def test_staged_input_bound():
    GI.require_staged(16 * 1024 * 1024)
    assert _reason(GI.require_staged, 16 * 1024 * 1024 + 1, cls=FailureClass.resource_exceeded) == \
        "staged_input_bytes"


def test_individual_arguments_are_a_standalone_m18_request(world):
    normalized = _admit(world)["arguments"]
    handle = "obj://" + world["rid"] + "/mutation_set_model/" + "e" * 64
    args = GI.individual_arguments(normalized, handle, "mutant")
    assert args == {"receptor_source": {"kind": "mutation_model", "mutation_model": handle, "side": "mutant"},
                    "ligand": {"source": "sdf", "sdf_handle": world["phenol"]}, "mode": "free",
                    "box": normalized["box"], "parameters": normalized["parameters"],
                    "acknowledgement": SF.ACK}
    assert docking_inputs.input_sha256(args) != docking_inputs.input_sha256(
        GI.individual_arguments(normalized, handle, "wild_type_reference"))


# ---------------------------------------------------------------- pins, hashes, call key (spec 4, 7)


def _selected(**changes) -> dict:
    args = _validate(_args(candidate_set=SF.TINY["handle"]))
    args["box"] = GI.request_box(args["box"])
    selected = {"schema": SC.SELECTION_SCHEMA, "arguments": args,
                "structure": SF.structure_record(),
                "ligand": {"sdf_handle": SDF_HANDLE, "sdf_sha256": "d" * 64}}
    selected.update(changes)
    return selected


def test_module_pins_fail_until_the_t3_t4_modules_exist(tmp_path, monkeypatch):
    if not all(path.is_file() for path in GI.GA_MODULES.values()):
        with pytest.raises(FileNotFoundError, match="sequence GA module missing"):
            GI.module_pins()
    fakes = {}
    for key in GI.GA_MODULES:
        path = tmp_path / f"{key}.py"
        path.write_bytes(key.encode())
        fakes[key] = path
    monkeypatch.setattr(GI, "GA_MODULES", fakes)
    pins = GI.module_pins()
    assert pins["ga_worker_sha256"] == hashlib.sha256(b"ga_worker_sha256").hexdigest()
    assert set(pins["m21_sha256"]) == {"mw/jobs/openmm_mutation_worker.py", "mw/mutation_model_math.py",
                                       "mw/mutation_model_constants.py", "mw/jobs/openmm_worker.py",
                                       "mw/tools/openmm_method.py", "mw/mutation_candidates.py"}
    assert pins["m21_sha256"]["mw/mutation_candidates.py"] == \
        hashlib.sha256((MW / "mutation_candidates.py").read_bytes()).hexdigest()


def test_pins_shape_is_checked():
    pins = SF.pins()
    assert GI.check_pins(pins) is pins
    bad = [{**pins, "extra": 1}, {**pins, "modules": {**pins["modules"], "ga_worker_sha256": "x"}},
           {**pins, "model_method": {**pins["model_method"], "multi_mutation": "sequential"}},
           {**pins, "model_method": {k: v for k, v in pins["model_method"].items() if k != "multi_mutation"}},
           {**pins, "model_method": {**pins["model_method"], "max_iterations": 100}},
           {**pins, "docking": {**pins["docking"], "qvina_sha256": "0" * 64}}]
    for value in bad:
        with pytest.raises(ValueError):
            GI.check_pins(value)


def test_model_method_is_the_m21_method_plus_the_multi_mutation_record():
    m21 = {k: v for k, v in SF.model_method().items() if k != "multi_mutation"}
    assert set(m21) == set(MK.METHOD_KEYS)
    assert GI.model_method(m21) == {**m21, "multi_mutation": "sequential_structure_order_round4"}


def test_selection_and_conditions_hashes_and_call_key():
    selected, pins = _selected(), SF.pins()
    base = (GI.selection_sha256(selected), GI.conditions_sha256(selected, pins), GI.call_key(selected, pins))
    assert all(len(value) == 64 for value in base)
    # acknowledgement is not part of either hash
    other = copy.deepcopy(selected)
    other["arguments"]["acknowledgement"] = {}
    assert GI.selection_sha256(other) == base[0] and GI.conditions_sha256(other, pins) == base[1]
    # the GA parameters change the selection and call key but not the reuse conditions (another GA seed reuses)
    seeded = copy.deepcopy(selected)
    seeded["arguments"]["ga"]["seed"] = 12
    assert GI.selection_sha256(seeded) != base[0] and GI.call_key(seeded, pins) != base[2]
    assert GI.conditions_sha256(seeded, pins) == base[1]
    # every reuse condition changes the conditions hash
    for path, value in ((("arguments", "parameters", "seed"), 43), (("arguments", "box", "margin_A"), 7.0),
                        (("ligand", "sdf_sha256"), "e" * 64), (("structure", "model_number"), 2),
                        (("arguments", "candidate_set"), SET_HANDLE)):
        changed = copy.deepcopy(selected)
        target = changed
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
        assert GI.conditions_sha256(changed, pins) != base[1], path
    for part in ("modules", "model_method", "docking"):
        changed = copy.deepcopy(pins)
        key = next(iter(changed[part]))
        changed[part][key] = "0" * 64 if part != "model_method" else "x"
        assert GI.conditions_sha256(selected, changed) != base[1] and GI.call_key(selected, changed) != base[2]


# ---------------------------------------------------------------- reuse index (spec 4)


def test_reuse_record_from_a_stored_result():
    scored = GI.reuse_record("1-3", model_handle="m", result_handle="r",
                             result={"modes": [{"score_kcal_mol": -3.6}, {"score_kcal_mol": -3.0}]})
    assert scored == {"key": "1-3", "state": "scored", "reason_code": None, "score": -3.6, "model_handle": "m",
                      "result_handle": "r"}
    empty = GI.reuse_record("wild_type", model_handle="m", result_handle="r", result={"modes": []})
    assert (empty["state"], empty["score"]) == ("null_result", None)
    for key, model, result, modes in (("01", "m", "r", []), ("1", None, "r", []), ("1", "m", "", []),
                                      ("1", "m", "r", [{"score_kcal_mol": float("nan")}]),
                                      ("1", "m", "r", [{"score_kcal_mol": -3}])):
        with pytest.raises(ValueError):
            GI.reuse_record(key, model_handle=model, result_handle=result, result={"modes": modes})


def test_reuse_index_first_record_wins():
    first = {"key": "1", "model_handle": "a"}
    index = GI.reuse_index([first, {"key": "1", "model_handle": "b"}, {"key": "2", "model_handle": "c"}])
    assert index == {"1": first, "2": {"key": "2", "model_handle": "c"}}


# ---------------------------------------------------------------- budget arithmetic (spec 7)


@pytest.mark.parametrize("row", EXPECTED["arithmetic"]["reservation"], ids=lambda r: r["name"])
def test_reservation_matches_the_independent_oracle(row):
    ga = row["ga"]
    assert GI.reserved_evaluations(ga) == row["reserved_evaluations"]
    assert GI.reserved_units(ga) == row["reserved_units"]
    assert GI.needed_budget(ga) == {"expensive_calls": row["reserved_units"], "wall_clock_s": row["wall_clock_s"]}
    assert GI.full_run_may_be_partial(ga) is row["full_run_may_be_partial"]


def test_reservation_by_hand():
    ga = dict(SF.DEFAULT_GA)                      # min(32, 8 + 4 * 6) = 32 evaluations, 2 * 33 = 66 units
    assert (GI.reserved_evaluations(ga), GI.reserved_units(ga)) == (32, 66)
    assert GI.needed_budget(ga) == {"expensive_calls": 66, "wall_clock_s": min(7800, 66 * 270 + 300)} == \
        {"expensive_calls": 66, "wall_clock_s": 7800}
    ga = {**ga, "population_size": 10, "generations": 3, "elite_count": 0}       # 10 + 2 * 10 = 30
    assert [GI.reserved_evaluations({**ga, "max_new_evaluations": n}) for n in (29, 30, 31)] == [29, 30, 30]
    assert GI.reserved_units({**ga, "max_new_evaluations": 31}) == 62


def test_needed_wall_and_partial_boundaries():
    ga = {**SF.DEFAULT_GA, "population_size": 4, "generations": 1, "elite_count": 0, "max_new_evaluations": 4}
    # units 10: wall = min(total + 600, 10 * 270 + 300 = 3000), partial when 2700 > total
    assert GI.needed_budget({**ga, "total_s": 2400})["wall_clock_s"] == 3000
    assert GI.needed_budget({**ga, "total_s": 2399})["wall_clock_s"] == 2999
    assert GI.full_run_may_be_partial({**ga, "total_s": 2700}) is False
    assert GI.full_run_may_be_partial({**ga, "total_s": 2699}) is True


def _budget(calls_used=0, wall_used=0.0, calls_limit=8, wall_limit=1800.0) -> dict:
    return {"expensive_calls": {"used": calls_used, "limit": calls_limit},
            "wall_clock_s": {"used": wall_used, "limit": wall_limit}}


def test_default_ga_is_short_on_the_default_run_budget_and_raise_covers_the_shortfall():
    needed = GI.needed_budget(SF.DEFAULT_GA)
    assert GI.shortfall(needed, _budget()) == {"expensive_calls": 58, "wall_clock_s": 6000}
    assert _reason(GI.require_budget, needed, _budget(), cls=FailureClass.resource_exceeded) == \
        "ga_limit_raise_required"
    increase = GI.limit_increase(needed, _budget())
    assert increase == {"expensive_calls": 58, "wall_clock_s": 6060}
    raised = _budget(calls_limit=8 + 58, wall_limit=1800 + 6060)
    GI.require_budget(needed, raised)
    assert GI.limit_increase(needed, raised) == {"expensive_calls": 0, "wall_clock_s": 0}


def test_limit_increase_caps():
    big = GI.needed_budget({**SF.DEFAULT_GA, "population_size": 16, "generations": 8, "elite_count": 0,
                            "max_new_evaluations": 64, "total_s": 14400})
    assert big == {"expensive_calls": 130, "wall_clock_s": 15000}
    assert GI.limit_increase(big, _budget(500, 90_000, 8, 1800)) == {"expensive_calls": 130, "wall_clock_s": 15060}
    needed = GI.needed_budget(SF.DEFAULT_GA)
    assert GI.limit_increase(needed, _budget(0, 1, 66, 7800)) == {"expensive_calls": 0, "wall_clock_s": 61}
    assert GI.limit_increase(needed, _budget(0, 0, 65, 7800)) == {"expensive_calls": 1, "wall_clock_s": 0}
    assert GI.budget_figures(SF.DEFAULT_GA, _budget(6, 600)) == {
        "reserved_evaluations": 32, "reserved_units": 66, "needed": needed,
        "remaining": {"expensive_calls": 2, "wall_clock_s": 1200.0},
        "shortfall": {"expensive_calls": 64, "wall_clock_s": 6600.0}, "full_run_may_be_partial": True}


# ---------------------------------------------------------------- isolation


NEW_MODULES = ["sequence_ga_constants.py", "sequence_ga_inputs.py", "sequence_model_bundle.py",
               "sequence_ga_bundle.py"]


@pytest.mark.parametrize("name", NEW_MODULES)
def test_new_server_modules_import_no_heavy_packages(name):
    tree = ast.parse((MW / name).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(m.split(".")[0] in {"rdkit", "meeko", "MDAnalysis", "openmm", "pdbfixer"} for m in imported), name
    text = (MW / name).read_text()
    assert "__import__" not in text and "importlib" not in text and "subprocess" not in text and "qvina2" not in text


def test_new_server_modules_load_without_heavy_packages():
    code = ("import sys; import mw.sequence_ga_constants, mw.sequence_ga_inputs, mw.sequence_model_bundle, "
            "mw.sequence_ga_bundle; print(sorted({m.split('.')[0] for m in sys.modules} & "
            "{'rdkit', 'meeko', 'MDAnalysis', 'openmm', 'pdbfixer'}))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                         cwd=str(MW.parent), check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"
