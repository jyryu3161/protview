"""M25 JEV design loop: closed sets, caps, names, question wording, wire field lists and fixed sentences.

Spec .dryforge/spec.md 3 (loop record, admission), 4 (projection tool, projection object, order, wire, questions and
body), 5 (loop send refusals, proposal keys), 6 (compute refusals, steps), 7 (axes), 8 (end refusals, end reasons,
summary limitation ids, report names), 9.3 (LJ1-LJ8, UL1-UL3) and 11. Standard library only (``hashlib``, ``uuid``)
so the loop, projection, tool, send-branch and report modules share one copy. The M24 values the loop keeps as they
are (question key, type and criterion template, the two base ``values_note`` strings, J7, the choice label) are
written out here on purpose, and a test checks they equal ``mw.jev_constants``; the M24 nested wire allow lists
(parent, candidate, position, residue, ...) are not copied: the loop wire check runs the M24 ``check_wire`` on them.

Changing any closed set, cap, question id, instruction text, wire field list, ``values_note``, the order algorithm or a
fixed sentence needs a user decision (spec 11, handoff absolute condition 8). The step time limits, the screen
iteration default, the protein contact cutoff default and the read polling interval are adjustable defaults.
"""
from __future__ import annotations

import hashlib
import uuid

# --- branches, goals, kinds (spec 3.1, 4.2) --------------------------------------------------------------------------
BRANCHES = ("ligand", "protein")
GOALS = ("explore", "exploit")
KINDS = ("ligand", "mutation")                       # the projection / wire kind, as in M24
KIND_FOR_BRANCH = {"ligand": "ligand", "protein": "mutation"}

# --- caps (closed; reaching one is refused, never truncated) -------------------------------------------------------
MIN_POOL = 2
MAX_POOL = 20
MIN_ITERATION_CAP = 1
MAX_ITERATION_CAP = 8
MIN_LOOP_SEED = 0
MAX_LOOP_SEED = 2_147_483_647
MIN_PENDING_TO_SEND = 2                              # spec 3.3: one pending candidate or none -> no send
MAX_BODY_BYTES = 65_536
MAX_OBJECT_BYTES = 1_048_576                         # jev_loop_projection@1 / jev_loop_choice@1 / jev_loop_result@1
MAX_CREATE_REQUEST_BYTES = 16_384                    # POST /runs/{rid}/jev_loops
MAX_ACTION_REQUEST_BYTES = 4_096                     # .../compute, .../abandon_docking, .../end

# --- adjustable defaults (spec 6.1, 10, 11) --------------------------------------------------------------------------
DEFAULT_ITERATION_CAP = 5                            # screen default
STEP_TIMEOUT_DEFAULTS_S = {"ligand_dock": 300, "model": 120, "dock": 300}
UNITS_PER_STEP = 1                                   # every step is one expensive job
DEFAULT_CONTACT_CUTOFF_A = 4.0
READ_POLL_INTERVAL_S = 2

# --- tool, objects, events, capability, report (spec 4.1, 4.2, 5.3, 8.2, 8.3, 9.2) ---------------------------------
TOOL = "build_jev_loop_projection"
TOOL_VERSION = "1"
TOOL_ARGUMENTS = ("loop_id", "iteration")
LOOP_SCHEMA = "jev_loop@1"                           # read-only record, never stored
PROJECTION_KIND = "jev_loop_projection"
PROJECTION_SCHEMA = "jev_loop_projection@1"
PROJECTION_METHOD_VERSION = "mw.jev_loop_projection/v1"
CHOICE_KIND = "jev_loop_choice"
CHOICE_SCHEMA = "jev_loop_choice@1"
CHOICE_METHOD_VERSION = "mw.jev_loop_choice/v1"
RESULT_KIND = "jev_loop_result"
RESULT_SCHEMA = "jev_loop_result@1"
RESULT_METHOD_VERSION = "mw.jev_loop_result/v1"
EVENT_CREATED = "jev_loop_created"
EVENT_COMPUTE_APPROVED = "jev_loop_compute_approved"
EVENT_DOCKING_ABANDONED = "jev_loop_docking_abandoned"
EVENT_ENDED = "jev_loop_ended"
EVENT_TYPES = (EVENT_CREATED, EVENT_COMPUTE_APPROVED, EVENT_DOCKING_ABANDONED, EVENT_ENDED)
CAPABILITY_METHOD = "jev_loop"
APPROVED_BY = "human"
REPORT_ANALYSIS_TYPE = "jev_loop"
REPORT_RENDER = "jev_loop_markdown@1"
REPORT_RENDER_V2 = "jev_loop_markdown@2"   # M29: a protein loop on a repaired structure (구조 출처 section)
REPORT_LABEL = "JEV 루프 보고서"
REPORT_GENERATION_MODE = "local_rules_no_egress"
REPORT_EVIDENCE_KINDS = ("computed", "model_response")

# --- request keys (spec 3.1, 6.1, 6.3; anything else is unknown_field) ---------------------------------------------
CREATE_KEYS = ("loop_id", "branch", "pool", "goal", "loop_seed", "iteration_cap", "setup")
POOL_KEYS = ("source", "candidates", "filter")
COMPUTE_KEYS = ("iteration", "proposal", "candidate")
ABANDON_KEYS = ("iteration",)

# --- loop record states (spec 3.2, 3.3, 6.4, 7) ----------------------------------------------------------------------
LOOP_STATUSES = ("active", "ended")
CANDIDATE_STATES = ("pending", "scored", "null_result", "failed", "not_run", "unavailable")
EVALUATIONS = ("computed", "reused")
STEPS = ("ligand_dock", "model", "dock")
BRANCH_STEPS = {"ligand": ("ligand_dock",), "protein": ("model", "dock")}
STEP_STATES = ("waiting_start", "running", "completed", "failed", "unavailable", "reused")
ITERATION_STATES = ("in_progress", "scored", "null_result", "failed", "not_run", "unavailable")
PHASES = ("awaiting_selection", "awaiting_compute", "running", "awaiting_docking", "done")
ACTIONS = ("select", "compute", "wait_job", "dock", "end", "none")
DECIDED_BY = ("jev", "human")
EXHAUSTED_REASONS = ("iteration_cap", "pool_exhausted")
END_REASONS = ("iteration_cap", "pool_exhausted", "ended_by_user", "budget_exhausted", "run_cancelled")
START_BLOCKED = "approval_required"                  # current.job.start_blocked
NOT_RUN_REASON = "docking_not_run"
AXES = ("expensive_units", "wall_clock_s", "external_tokens", "usd", "sends")
COMPUTE_AXES = ("expensive_units", "wall_clock_s")
SEND_AXES = ("external_tokens", "usd", "sends")

# --- refusals (each in spec check order; first failure only) -------------------------------------------------------
CREATE_REASONS = ("unknown_field", "loop_id_invalid", "dry_run", "branch_invalid", "capability_unavailable",
                  "loop_active", "pool_invalid", "goal_invalid", "seed_invalid", "iteration_cap_invalid",
                  "setup_invalid")
LOOP_ID_CONFLICT = "loop_id_conflict"                # same loop_id, other body (409)
PROJECTION_REASON_CODES = ("unknown_field", "loop_not_found", "loop_ended", "iteration_mismatch", "selection_done",
                           "phase_invalid", "cap_reached", "too_few_candidates", "source_invalid",
                           "structure_unavailable", "wire_field_invalid", "payload_too_large")
PROJECTION_INVALID = "projection_invalid"
LOOP_SEND_INVALID = "loop_send_invalid"
LOOP_SEND_REASONS = ("loop_not_found", "loop_ended", "iteration_mismatch", "selection_done", "phase_invalid",
                     "cap_reached", "too_few_candidates", "state_changed", "ordinal_mismatch")
COMPUTE_REASONS = ("unknown_field", "loop_not_found", "cancelled", "loop_ended", "send_in_progress",
                   "iteration_invalid", "phase_invalid", "iteration_cap_reached", "proposal_invalid", "proposal_late",
                   "candidate_invalid", "candidate_unavailable", "candidate_computed", "capability_unavailable",
                   "budget_blocked")
STEP_UNAVAILABLE = "step_unavailable"                # a same-key job appeared between the read and the submit (409)
END_REFUSAL_REASONS = ("loop_not_found", "cancelled", "loop_ended", "send_in_progress", "job_running",
                       "docking_pending")


def is_loop_id(value: object) -> bool:
    """A client loop_id is a canonical (lower-case, hyphenated) version 4 UUID string, as the M24 send_id."""
    if type(value) is not str:
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value


# --- questions (spec 4.5) --------------------------------------------------------------------------------------------
LIGAND_QUESTION_ID = "ligand_loop_choice@1"
MUTATION_QUESTION_ID = "mutation_loop_choice@1"
QUESTION_IDS = (LIGAND_QUESTION_ID, MUTATION_QUESTION_ID)
QUESTION_FOR_KIND = {"ligand": LIGAND_QUESTION_ID, "mutation": MUTATION_QUESTION_ID}
QUESTION_KEY = "candidate_choice"                    # = jev_constants.QUESTION_KEY
QUESTION_TYPE = "choice"                             # = jev_constants.QUESTION_TYPE
CRITERION_TEMPLATE = "Candidate {alias}."            # = jev_constants.CRITERION_TEMPLATE
_C = ("Choose exactly one candidate from the candidates listed in the criteria to place first in a local computation "
      "queue. This is a queue-order choice only; it is not a prediction of binding, activity, affinity, stability, "
      "synthesizability, safety or the effect of a substitution. ")
_O = "The order of the candidate list and the alias numbers were shuffled for this request and carry no meaning."
_E = "The computed field lists the aliases of the candidates that have already been computed. "
_S = ("Computed candidates are listed with their stored qvina score (Vina-family scoring function value in kcal/mol, "
      "not an affinity); a candidate without a score is listed without one, which is not zero. ")
_RDK = "Property values are RDKit estimates, not measurements or interactions. "
_GEO = "Distances and neighbor lists are geometry from stored coordinates, not measurements or interactions. "
_NC = "Each score belongs to the modelled structure of its own mutation, so scores are not like-for-like comparisons. "
INSTRUCTIONS = {
    ("ligand", "explore"): (_C + "Prefer the candidate whose structure (SMILES) is most different from all the "
                            "computed candidates; if no candidate is computed, choose any one. " + _E + _RDK + _O),
    ("ligand", "exploit"): (_C + "Prefer the candidate whose structure (SMILES) is most similar to the one computed "
                            "candidate with the lowest listed score; if no candidate has a listed score, choose any "
                            "one. This is a judgment of structural similarity only, not a prediction of any score. "
                            + _S + _RDK + _O),
    ("mutation", "explore"): (_C + "Prefer the candidate whose position and substitution (from, to) are most "
                              "different from all the computed candidates; if no candidate is computed, choose any "
                              "one. " + _E + _GEO + _O),
    ("mutation", "exploit"): (_C + "Prefer the candidate whose position and substitution (from, to) are most similar "
                              "to the one computed candidate with the lowest listed score; if no candidate has a "
                              "listed score, choose any one. This is a judgment of similarity of position and "
                              "substitution only, not a prediction of any score or of the effect of a mutation. "
                              + _S + _NC + _GEO + _O),
}


def instructions_sha256(kind: str, goal: str) -> str:
    """SHA-256 (hex) of the fixed instructions of (kind, goal) (``KeyError`` for any other pair)."""
    return hashlib.sha256(INSTRUCTIONS[(kind, goal)].encode("ascii")).hexdigest()


# --- wire (spec 4.3, 4.4) --------------------------------------------------------------------------------------------
ORDER_ALGORITHM = "sha256_order_v1"
WIRE_SCHEMAS = {"ligand": "jev_loop_ligand_candidates@1", "mutation": "jev_loop_mutation_candidates@1"}
WIRE_TASK = "choose_one_candidate"
ALLOWED_TOP = {   # the M24 top-level fields plus goal and computed; nested fields are the M24 allow lists
    "ligand": ("schema", "task", "goal", "parent", "property_methods", "candidates", "computed", "values_note"),
    "mutation": ("schema", "task", "goal", "positions", "candidates", "protection_checks", "pockets", "computed",
                 "values_note"),
}
OPTIONAL_TOP = {"ligand": (), "mutation": ("pockets",)}
ALLOWED_COMPUTED = {"explore": ("alias",), "exploit": ("alias", "state", "score_kcal_mol")}
COMPUTED_STATES = ("scored", "no_score")
COMPUTED_STATE_FOR = {"scored": "scored", "null_result": "no_score", "failed": "no_score", "not_run": "no_score"}
_LIGAND_NOTE = ("RDKit estimates, not measurements; PAINS matches are structural alerts only; no receptor or pocket "
                "information is included")                       # = jev_constants.LIGAND_VALUES_NOTE
_MUTATION_NOTE = ("Distances and neighbor lists are geometry from stored coordinates, not interactions; "
                  "protection_released=false means no performed check applied, not that a residue is unimportant; "
                  "checks that are not_checked or not_available were not performed")   # = MUTATION_VALUES_NOTE
VALUES_NOTES = {
    ("ligand", "explore"): _LIGAND_NOTE,
    ("ligand", "exploit"): _LIGAND_NOTE + "; scores are stored qvina values from one fixed receptor and box",
    ("mutation", "explore"): _MUTATION_NOTE,
    ("mutation", "exploit"): _MUTATION_NOTE + "; each score belongs to the modelled structure of its own mutation",
}

# --- projection object (spec 4.2) ------------------------------------------------------------------------------------
PROJECTION_KEYS = ("schema", "method_version", "kind", "loop", "goal", "source", "structure", "question", "order",
                   "selection", "wire", "wire_sha256", "body_sha256", "body_bytes", "limitations")
LOOP_REF_KEYS = ("loop_id", "iteration", "send_ordinal")
ORDER_KEYS = ("algorithm", "loop_seed", "iteration", "send_ordinal")
SELECTION_KEYS = ("alias", "ref", "state")
SELECTION_STATES = ("pending", "scored", "null_result", "failed", "not_run")   # unavailable is never listed

# --- proposal object (spec 5.3) --------------------------------------------------------------------------------------
CHOICE_LABEL = "JEV 판정(모델 선택)"                  # = jev_constants.CHOICE_LABEL
CHOICE_KEYS = ("schema", "method_version", "label", "scientific_result", "loop", "goal", "send", "source",
               "projection", "question", "requested_model", "served_model", "selection", "answer", "usage", "arrival",
               "limitations")
CHOICE_SEND_KEYS = ("send_id", "audit_id")
CHOICE_PROJECTION_KEYS = ("handle", "wire_sha256", "body_sha256", "body_bytes")
CHOICE_QUESTION_KEYS = ("id", "key", "instructions_sha256")
ANSWER_KEYS = ("choice_alias", "list_position", "list_size", "local_ref", "local_display", "confidence",
               "probabilities")
LOCAL_REF_KEYS = {"ligand": ("candidate_id",), "mutation": ("candidate_index", "position_index")}
DISPLAY_KEYS = {"ligand": ("smiles",), "mutation": ("residue", "from", "to")}
USAGE_KEYS = ("input_tokens", "output_tokens", "external_tokens", "cost")
ARRIVAL_KEYS = ("late", "late_reason")

# --- fixed sentences (spec 9.3, verbatim, order fixed) ---------------------------------------------------------------
LJ1 = ("JEV 루프는 사람이 바퀴마다 보낼 내용과 계산 시작을 승인하며, JEV 판정은 외부 모델이 계산 대기열에 먼저 둘 후보로 "
       "고른 하나일 뿐 계산 결과가 아니라 제안으로 따로 기록한 것이다. 순위·추천·예측이 아니고 고른 이유는 알 수 없다.")
LJ2 = ("점수는 저장된 qvina 도킹 결과의 첫 모드 값(kcal/mol, Vina 계열 스코어링 함수 값, 친화도가 아님)이며, 점수 없음은 "
       "0이 아니다. 바퀴 순서·표 정렬·선택 표시는 순위나 개선이 아니다.")
LJ3 = ("후보 순서와 별칭은 전송마다 기록된 seed로 섞은 것이며 의미가 없다. 모델 선택은 목록 위치의 영향을 받을 수 있어 "
       "고른 위치를 값으로 기록했고, 이 기록은 효과를 뜻하지 않는다.")
LJ4 = "활용형은 점수가 낮게 나온 후보와 구조가 비슷한 후보를 고르게 하는 질문이며 점수 예측이 아니고 후보를 줄 세우지 않는다."
LJ5 = "탐색형은 이미 계산한 후보와 가장 다른 후보를 고르게 하는 질문이며 점수를 보내지 않았다."
LJ6 = ("후보는 2D 그래프이고 점수는 사용자가 정한 수용체·상자에서 자유 도킹한 qvina 값이며 결합·활성·합성 가능성이 아니다. "
       "JEV에는 수용체 정보를 보내지 않았다.")
LJ7 = ("점수는 후보마다 다른 변이 구조(PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 단백질만의 "
       "모델)에 사용자 리간드를 자유 도킹한 값이라 같은 수용체 안의 비교가 아니며 변이의 효과나 친화도가 아니다. 야생형 "
       "기준은 계산하지 않았다.")
LJ8 = "이 루프는 계산하지 않은 후보를 남기고 끝났으며 계산하지 않은 후보는 점수가 없다(0이 아니다)."
STATEMENTS = {"LJ1": LJ1, "LJ2": LJ2, "LJ3": LJ3, "LJ4": LJ4, "LJ5": LJ5, "LJ6": LJ6, "LJ7": LJ7, "LJ8": LJ8}
J7 = "이 응답은 run 취소 또는 과학 전송 동의 끄기 뒤에 도착했으며 어떤 작업도 일으키지 않았다."   # = jev_constants.J7
UL1 = "JEV 루프는 바퀴마다 보낼 내용 승인과 계산 시작 승인을 따로 받는다. JEV가 고른 후보도 사람이 승인해야 계산된다."
UL2 = "한 바퀴에 JEV 응답이 한 번 완료되면 다시 묻지 않는다. 다른 후보를 원하면 직접 지정한다."
UL3 = ("루프 전송은 뷰어 모델 명령·지식·보고서 탭의 전송과 같은 외부 토큰·USD 예산, 같은 run 10회 전송 상한, 같은 "
       "'사용량 모름' 중지 상태를 쓴다.")
SCREEN_NOTES = {"UL1": UL1, "UL2": UL2, "UL3": UL3}


def limitation_ids(kind: str, goal: str, *, uncomputed_left: bool) -> list[str]:
    """LJ1-LJ3, LJ4 (exploit) or LJ5 (explore), LJ6 (ligand) or LJ7 (mutation), then LJ8 when the loop ended with a
    pending or unavailable candidate (summary and report, spec 9.3). A fresh list, order fixed."""
    if kind not in KINDS or goal not in GOALS or type(uncomputed_left) is not bool:
        raise ValueError("kind must be ligand or mutation, goal explore or exploit, uncomputed_left a boolean")
    return ["LJ1", "LJ2", "LJ3", "LJ4" if goal == "exploit" else "LJ5", "LJ6" if kind == "ligand" else "LJ7",
            *(["LJ8"] if uncomputed_left else [])]


def limitations_for(kind: str, goal: str, late: bool) -> list[str]:
    """The sentences of a projection or a proposal: LJ1-LJ3, LJ4 | LJ5, LJ6 | LJ7, then J7 when ``late``."""
    if type(late) is not bool:
        raise ValueError("late must be a boolean")
    return [STATEMENTS[name] for name in limitation_ids(kind, goal, uncomputed_left=False)] + ([J7] if late else [])
