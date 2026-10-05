"""M23 sequence GA design closed sets, parameter ranges, limits, budget constants and fixed wording
(spec .dryforge/spec.md 2, 3, 4, 6, 7, 11).

Dependency-free on purpose (standard library only, no imports at all), like ``ligand_ga_constants``, so the server
modules, the GA worker (docking environment) and the modeling program (project environment) can share one copy by
file path. Strings copied from ``mutation_model_constants`` (M21 failure reasons and sentences L1, L3, L6),
``docking_constants`` (M18 worker reasons, score label) and ``docking_batch_constants`` (score row label) are copies,
not imports; ``backend/tests/test_sequence_ga_inputs.py`` checks every copy against its original. Changing any reason,
stop reason, status, origin, edit operation, evaluation, state, parameter range or default, limit, budget constant or
S sentence needs a user decision (spec 6, 11; handoff absolute condition 5).
"""
from __future__ import annotations

PROTOCOL = "sequence_ga_dock_v1"
TOOL = "sequence_ga_design"
ENGINE = "qvina"
IMPLEMENTATION = "sequence_ga_dock_v1@1"
SUMMARY_SCHEMA = "sequence_ga_result@1"
OUTPUT_KIND = "sequence_ga_result"
SELECTION_SCHEMA = "sequence_ga_selection@1"
WORKER_INPUT_SCHEMA = "sequence_ga_worker_input@1"
WORKER_OUTPUT_SCHEMA = "sequence_ga_worker_output@1"
INDIVIDUAL_EVENT = "sequence_ga_individual_published"
SUMMARY_EVENT = "sequence_ga_published"
MODE = "free"                    # fixed: the request has no mode key (spec 2)
SELECTION_POLICY = "protein_only"
HYDROGEN_POLICY = "rebuild_pH7"

# 4 the multi-mutation structure model (a new object; the M21 ``mutation_model@1`` is unchanged).
MODEL_KIND = "mutation_set_model"
MODEL_SCHEMA = "mutation_set_model@1"
MODEL_METHOD_VERSION = "mw.mutation_set_model/v1"
STRUCTURE_OBJECT_KIND = "mutation_set_model_structure"
STRUCTURE_OBJECT_SCHEMA = "mutation_set_model_structure@1"
MUTANT_SIDE = "mutant"                           # = M21 / M18 side names (docking_constants.MUTATION_MODEL_SIDES)
REFERENCE_SIDE = "wild_type_reference"
MULTI_MUTATION_METHOD = {"multi_mutation": "sequential_structure_order_round4"}
ROUND_DECIMALS = 4                               # PDBFixer-placed atoms rounded between steps (spec 4 (1))

# 3 individual keys: candidate indices ascending joined by "-" ("12-57-203"); the reference row is "wild_type".
KEY_SEPARATOR = "-"
REFERENCE_KEY = "wild_type"

# 2 GA parameters ``ga``: every key required, in this order. (min, max, default); ``seed`` has no default.
# ``max_new_evaluations`` min is ``population_size`` (cross rule); the two fractions are finite reals.
GA_KEYS = ("seed", "population_size", "generations", "elite_count", "tournament_size", "crossover_fraction",
           "random_fraction", "max_mutations", "patience", "max_new_evaluations", "total_s")
GA_RANGES = {
    "seed": (0, 2147483647, None),
    "population_size": (4, 16, 8),
    "generations": (1, 8, 5),
    "elite_count": (0, 4, 2),
    "tournament_size": (2, 4, 2),
    "crossover_fraction": (0.0, 1.0, 0.5),
    "random_fraction": (0.0, 0.5, 0.2),
    "max_mutations": (1, 4, 3),
    "patience": (1, 8, 3),
    "max_new_evaluations": (4, 64, 32),
    "total_s": (600, 14400, 7200),
}
GA_FLOAT_KEYS = ("crossover_fraction", "random_fraction")
MIN_NEW_SLOTS = 2                # population_size - elite_count >= 2

# 3 procedure constants (the worker's; first try plus at most this many more, spec 3 "detail" 1).
DRAW_RETRIES = 50
CHILD_RETRIES = 20
B_RETRIES = 3
CONSECUTIVE_FAILURE_LIMIT = 5

# 11 limits.
MAX_POSITIONS = 400              # = M20 position cap
MAX_CANDIDATES = 7600            # = 400 positions x 19 alternatives
MAX_POPULATION = 16
MAX_GENERATIONS = 8
MAX_NEW_EVALUATIONS = 64
MAX_MUTATIONS = 4
MODEL_STEP_S = 240               # one individual's modeling (= M21 maximum)
DOCKING_STEP_S = 300             # one individual's receptor preparation + docking (= M19 PER_CANDIDATE_S)
TOTAL_S_MAX = 14400
FINISH_MARGIN_S = 600            # job timeout_s >= total_s + 600
TIMEOUT_MAX_S = 15000            # = TOTAL_S_MAX + FINISH_MARGIN_S
MAX_MODEL_OBJECT_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
PER_INDIVIDUAL_OUTPUT_MAX = 32 * 1024 * 1024
MAX_SUMMARY_BYTES = 1024 * 1024
MAX_STAGED_BYTES = 16 * 1024 * 1024
M18_HEAVY_ATOM_ESTIMATE = 4890   # M18 10,000-atom receptor cap at the 1UBQ hydrogen ratio (decision 0029)

# 7 budget: a new evaluation costs 2 expensive units (modeling 1 + docking 1); reserved_evaluations =
# min(max_new_evaluations, P + (G - 1) * (P - E)); reserved_units = 2 * (reserved_evaluations + 1) (the wild-type
# reference row always reserves its 2 units); needed wall = min(total_s + FINISH_MARGIN_S,
# reserved_units * SECONDS_PER_UNIT + NEED_MARGIN_S). A raise is the M19 ``limit_increase`` formula with these values.
UNITS_PER_EVALUATION = 2
SECONDS_PER_UNIT = 270
NEED_MARGIN_S = 300
RAISE_MARGIN_S = 60
MAX_RAISE_EXPENSIVE_CALLS = 140
MAX_RAISE_WALL_CLOCK_S = 15000

# 2 admission, in this order, first failure only. Steps 1-4 and 6-7 are input_invalid (HTTP 422), 5 precondition
# (HTTP 412), 8-9 resource_exceeded (HTTP 429). Step 4 is the subset of the M18 ligand/box reasons a server can
# decide without RDKit.
LIGAND_BOX_REASONS = ("ligand_record_count", "ligand_unparseable", "ligand_multiple_fragments",
                      "ligand_element_not_allowed", "ligand_too_many_atoms", "ligand_not_3d", "box_invalid",
                      "box_too_large")
ADMISSION_STEPS = (
    ("invalid_job_arguments",),
    ("confirmation_missing", "acknowledgement_missing"),
    ("candidate_set_invalid", "structure_invalid"),
    LIGAND_BOX_REASONS,
    ("process_identity_unavailable", "openmm_unavailable", "pdbfixer_unavailable", "worker_missing",
     "engine_missing", "engine_hash_mismatch", "handshake_failed", "version_mismatch"),
    ("openmm_preflight_failed", "residue_mismatch", "box_no_receptor_atoms"),
    ("ga_space_too_small",),
    ("staged_input_bytes",),
    ("ga_limit_raise_required",),
)
ADMISSION_REASONS = tuple(reason for step in ADMISSION_STEPS for reason in step)

# 3 stop reasons (closed) and the status each one gives.
STOP_REASONS = ("generations_complete", "no_change", "space_exhausted", "evaluation_limit", "time_exhausted",
                "cancelled", "worker_failed", "resource_exceeded", "reference_failed", "repeated_failure")
STATUSES = ("complete", "partial")
STATUS_BY_STOP_REASON = {
    "generations_complete": "complete", "no_change": "complete", "space_exhausted": "complete",
    "evaluation_limit": "partial", "time_exhausted": "partial", "cancelled": "partial", "worker_failed": "partial",
    "resource_exceeded": "partial", "reference_failed": "partial", "repeated_failure": "partial",
}

# 4, 6 individual closed sets. ``failed`` takes one FAILURE_REASONS value; the other states take none.
ORIGINS = ("initial", "carried", "crossover", "edit", "random")
EDIT_OPERATIONS = ("add", "change", "move", "remove")
EVALUATIONS = ("reused", "computed")        # carried individuals: null
STATES = ("scored", "null_result", "failed")
STAGES = ("model", "docking")               # ``individuals/<k>.status.json`` stage
# Copy of mutation_model_constants.FAILURE_REASON_CODES (M21 modeling failures).
MODEL_FAILURE_REASONS = ("mutation_modeling_failed", "unexpected_atoms_added", "coordinates_changed",
                         "topology_unsupported", "energy_invalid", "engine_failed", "resource_exceeded")
# Copy of docking_constants.REASONS (the M18 worker reason set).
DOCKING_FAILURE_REASONS = (
    "receptor_invalid", "receptor_hydrogens_missing", "receptor_unsupported_residue", "receptor_altloc_present",
    "receptor_instance_unknown", "receptor_instance_ambiguous", "receptor_instance_covalent", "receptor_prep_failed",
    "ligand_unparseable", "ligand_record_count", "ligand_multiple_fragments", "ligand_element_not_allowed",
    "ligand_too_many_atoms", "ligand_too_many_torsions", "ligand_not_3d", "ligand_hydrogens_missing",
    "ligand_prep_failed", "candidate_unknown", "parent_mismatch", "parent_not_3d", "core_match_failed",
    "core_match_ambiguous", "embed_failed", "box_invalid", "box_too_large", "box_no_receptor_atoms",
    "engine_failed", "engine_output_invalid", "resource_exceeded")
FAILED_EXTRA_REASONS = ("model_timeout", "docking_timeout", "worker_failed")
FAILURE_REASONS = tuple(dict.fromkeys(MODEL_FAILURE_REASONS + DOCKING_FAILURE_REASONS + FAILED_EXTRA_REASONS))

# 4 score wording: copies of docking_constants.SCORE_LABEL and docking_batch_constants.SCORE_ROW_LABELS["free"]
# (the first mode of each individual's M18 result).
SCORE_LABEL = "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)"
SCORE_ROW_LABEL = "모드 1(엔진 출력 순서)"

# 4 model limitation sentences, verbatim, in this order: L1 and L3 always (copies of mutation_model_constants.L1/L3),
# SL5 when ``protonation_differences`` is not empty, L6 (copy of mutation_model_constants.L6) when
# ``new_disulfide_in_mutant``.
L1 = "변이 구조는 PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 모델이며 회전이성질체 탐색과 수렴을 주장하지 않는다."
L3 = "모델은 단백질만 포함하며 리간드·금속 이온·물·보조인자는 제외했다."
SL5 = ("변이한 잔기 밖에서 히스티딘·시스테인 양성자 상태가 야생형 기준 구조와 다르게 지정되었으므로 두 구조의 차이는 "
       "지정한 변이만이 아니다.")
L6 = "변이형에는 야생형 기준에 없는 이황화 결합이 거리 기준으로 만들어졌다."
MODEL_LIMITATION_ORDER = (L1, L3, SL5, L6)

# 4 summary sentences, verbatim and in order. S1 always, S2 when partial, S3 when any individual was reused,
# S4-S6 always. The summary stores the ids; screens and reports print the text.
STATEMENTS = {
    "S1": "서열 GA는 변이 조합 공간에서 어떤 조합을 모델링·도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 "
          "순위나 추천이 아니다. 교차·편집의 부모 선택은 작업 모듈 기록이며 서버가 다시 계산하지 않았고 변이 목록의 "
          "부모–자식 관계만 검증했다.",
    "S2": "이 실행은 시간·평가 상한·취소·기준 행 실패·연속 실패 등으로 일부만 계산되었다. 계산하지 않은 개체는 점수가 "
          "없으며 0이 아니고, 한도 도달로 멈춘 실행은 같은 설정으로 다시 해도 같은 경로를 보장하지 않는다.",
    "S3": "재사용한 개체는 같은 후보 집합·구조·리간드·상자·seed·값으로 이전에 저장된 모델링·도킹 결과를 가져온 것이며, "
          "저장된 결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있다.",
    "S4": "점수는 각 개체의 변이 구조(PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 단백질만의 "
          "모델)에 사용자가 준 리간드 좌표를 그대로 두고 자유 도킹한 qvina 점수이며, 변이의 효과나 결합 친화도를 뜻하지 "
          "않는다.",
    "S5": "OpenMM 전위는 각 구조의 Amber14-all + GBn2 값(kJ/mol)이며 서열이 다른 구조의 값은 서로 비교할 수 없고 "
          "ΔΔG·안정성이 아니다.",
    "S6": "여러 곳 변이는 구조 순서대로 한 곳씩 PDBFixer로 연속 적용한 모델이며(앞 단계에서 놓은 원자 좌표는 다음 단계 "
          "전에 소수 넷째 자리로 반올림했다) 적용 순서와 곁사슬 크기에 따라 모델이 달라질 수 있다. 구조의 충돌·전위는 "
          "점수나 선택에 쓰지 않았고(전위가 늘거나 유한하지 않은 모델만 실패로 처리), 개체마다 수용체가 다르므로 개체 "
          "점수를 나란히 두는 것은 같은 수용체 안의 비교가 아니며(개체 도킹 결과의 M18 둘째 한계 문장이 말하는 조건과 "
          "다르다) 순위나 '더 잘 결합'을 뜻하지 않는다.",
}
