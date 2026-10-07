"""M25 T2 constants of the JEV design loop: closed sets, caps, names, question ids and instructions, wire field lists,
``values_note``, the order algorithm id, fixed sentences LJ1-LJ8 / UL1-UL3 and their linkage, adjustable defaults
(spec .dryforge/spec.md 3, 4, 5, 6, 7, 8, 9.3, 11).

Expected sets, sentences and numbers are typed from the spec text, never copied from the module under test. The M24
values the loop reuses (question key, type, criterion template, base ``values_note`` strings, J7, the choice label)
are compared with ``mw.jev_constants`` itself.
"""
from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from mw import jev_constants as J
from mw import jev_loop_constants as L

MW = Path(__file__).resolve().parents[1] / "mw"

# --- spec 9.3, verbatim ---------------------------------------------------------------------------------------------
SPEC_LJ = {
    "LJ1": "JEV 루프는 사람이 바퀴마다 보낼 내용과 계산 시작을 승인하며, JEV 판정은 외부 모델이 계산 대기열에 먼저 둘 후보로 "
           "고른 하나일 뿐 계산 결과가 아니라 제안으로 따로 기록한 것이다. 순위·추천·예측이 아니고 고른 이유는 알 수 없다.",
    "LJ2": "점수는 저장된 qvina 도킹 결과의 첫 모드 값(kcal/mol, Vina 계열 스코어링 함수 값, 친화도가 아님)이며, 점수 "
           "없음은 0이 아니다. 바퀴 순서·표 정렬·선택 표시는 순위나 개선이 아니다.",
    "LJ3": "후보 순서와 별칭은 전송마다 기록된 seed로 섞은 것이며 의미가 없다. 모델 선택은 목록 위치의 영향을 받을 수 있어 "
           "고른 위치를 값으로 기록했고, 이 기록은 효과를 뜻하지 않는다.",
    "LJ4": "활용형은 점수가 낮게 나온 후보와 구조가 비슷한 후보를 고르게 하는 질문이며 점수 예측이 아니고 후보를 줄 세우지 "
           "않는다.",
    "LJ5": "탐색형은 이미 계산한 후보와 가장 다른 후보를 고르게 하는 질문이며 점수를 보내지 않았다.",
    "LJ6": "후보는 2D 그래프이고 점수는 사용자가 정한 수용체·상자에서 자유 도킹한 qvina 값이며 결합·활성·합성 가능성이 "
           "아니다. JEV에는 수용체 정보를 보내지 않았다.",
    "LJ7": "점수는 후보마다 다른 변이 구조(PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 단백질만의 "
           "모델)에 사용자 리간드를 자유 도킹한 값이라 같은 수용체 안의 비교가 아니며 변이의 효과나 친화도가 아니다. 야생형 "
           "기준은 계산하지 않았다.",
    "LJ8": "이 루프는 계산하지 않은 후보를 남기고 끝났으며 계산하지 않은 후보는 점수가 없다(0이 아니다).",
}
SPEC_UL = {
    "UL1": "JEV 루프는 바퀴마다 보낼 내용 승인과 계산 시작 승인을 따로 받는다. JEV가 고른 후보도 사람이 승인해야 계산된다.",
    "UL2": "한 바퀴에 JEV 응답이 한 번 완료되면 다시 묻지 않는다. 다른 후보를 원하면 직접 지정한다.",
    "UL3": "루프 전송은 뷰어 모델 명령·지식·보고서 탭의 전송과 같은 외부 토큰·USD 예산, 같은 run 10회 전송 상한, 같은 "
           "'사용량 모름' 중지 상태를 쓴다.",
}

# --- spec 4.5 instruction fragments, verbatim ----------------------------------------------------------------------
C = ("Choose exactly one candidate from the candidates listed in the criteria to place first in a local computation "
     "queue. This is a queue-order choice only; it is not a prediction of binding, activity, affinity, stability, "
     "synthesizability, safety or the effect of a substitution. ")
O = "The order of the candidate list and the alias numbers were shuffled for this request and carry no meaning."
E = "The computed field lists the aliases of the candidates that have already been computed. "
S = ("Computed candidates are listed with their stored qvina score (Vina-family scoring function value in kcal/mol, "
     "not an affinity); a candidate without a score is listed without one, which is not zero. ")
RDK = "Property values are RDKit estimates, not measurements or interactions. "
GEO = "Distances and neighbor lists are geometry from stored coordinates, not measurements or interactions. "
NC = "Each score belongs to the modelled structure of its own mutation, so scores are not like-for-like comparisons. "
LIGAND_EXPLORE = ("Prefer the candidate whose structure (SMILES) is most different from all the computed candidates; "
                  "if no candidate is computed, choose any one. ")
LIGAND_EXPLOIT = ("Prefer the candidate whose structure (SMILES) is most similar to the one computed candidate with the "
                  "lowest listed score; if no candidate has a listed score, choose any one. This is a judgment of "
                  "structural similarity only, not a prediction of any score. ")
MUTATION_EXPLORE = ("Prefer the candidate whose position and substitution (from, to) are most different from all the "
                    "computed candidates; if no candidate is computed, choose any one. ")
MUTATION_EXPLOIT = ("Prefer the candidate whose position and substitution (from, to) are most similar to the one "
                    "computed candidate with the lowest listed score; if no candidate has a listed score, choose any "
                    "one. This is a judgment of similarity of position and substitution only, not a prediction of any "
                    "score or of the effect of a mutation. ")
SPEC_INSTRUCTIONS = {
    ("ligand", "explore"): C + LIGAND_EXPLORE + E + RDK + O,
    ("ligand", "exploit"): C + LIGAND_EXPLOIT + S + RDK + O,
    ("mutation", "explore"): C + MUTATION_EXPLORE + E + GEO + O,
    ("mutation", "exploit"): C + MUTATION_EXPLOIT + S + NC + GEO + O,
}
# --- spec 4.4 values_note -------------------------------------------------------------------------------------------
LIGAND_NOTE = ("RDKit estimates, not measurements; PAINS matches are structural alerts only; no receptor or pocket "
               "information is included")
MUTATION_NOTE = ("Distances and neighbor lists are geometry from stored coordinates, not interactions; "
                 "protection_released=false means no performed check applied, not that a residue is unimportant; "
                 "checks that are not_checked or not_available were not performed")
SPEC_NOTES = {
    ("ligand", "explore"): LIGAND_NOTE,
    ("ligand", "exploit"): LIGAND_NOTE + "; scores are stored qvina values from one fixed receptor and box",
    ("mutation", "explore"): MUTATION_NOTE,
    ("mutation", "exploit"): MUTATION_NOTE + "; each score belongs to the modelled structure of its own mutation",
}


# ---------------------------------------------------------------- closed sets (spec 3, 6, 7, 8, 11)


def test_branches_goals_kinds_and_pool_caps():
    assert L.BRANCHES == ("ligand", "protein") and L.GOALS == ("explore", "exploit")
    assert L.KINDS == ("ligand", "mutation") == J.KINDS
    assert L.KIND_FOR_BRANCH == {"ligand": "ligand", "protein": "mutation"}
    assert (L.MIN_POOL, L.MAX_POOL) == (2, 20) and L.MAX_POOL == J.MAX_CANDIDATES
    assert (L.MIN_ITERATION_CAP, L.MAX_ITERATION_CAP, L.DEFAULT_ITERATION_CAP) == (1, 8, 5)
    assert (L.MIN_LOOP_SEED, L.MAX_LOOP_SEED) == (0, 2_147_483_647)
    assert L.MIN_PENDING_TO_SEND == 2
    assert (L.MAX_BODY_BYTES, L.MAX_OBJECT_BYTES) == (65_536, 1_048_576) == (J.MAX_BODY_BYTES, J.MAX_OBJECT_BYTES)
    assert (L.MAX_CREATE_REQUEST_BYTES, L.MAX_ACTION_REQUEST_BYTES) == (16_384, 4_096)


def test_record_state_sets_match_spec():
    assert L.LOOP_STATUSES == ("active", "ended")
    assert L.CANDIDATE_STATES == ("pending", "scored", "null_result", "failed", "not_run", "unavailable")
    assert L.EVALUATIONS == ("computed", "reused")
    assert L.STEPS == ("ligand_dock", "model", "dock")
    assert L.BRANCH_STEPS == {"ligand": ("ligand_dock",), "protein": ("model", "dock")}
    assert L.STEP_STATES == ("waiting_start", "running", "completed", "failed", "unavailable", "reused")
    assert L.ITERATION_STATES == ("in_progress", "scored", "null_result", "failed", "not_run", "unavailable")
    assert L.PHASES == ("awaiting_selection", "awaiting_compute", "running", "awaiting_docking", "done")
    assert L.ACTIONS == ("select", "compute", "wait_job", "dock", "end", "none")
    assert L.DECIDED_BY == ("jev", "human")
    assert L.EXHAUSTED_REASONS == ("iteration_cap", "pool_exhausted")
    assert L.END_REASONS == ("iteration_cap", "pool_exhausted", "ended_by_user", "budget_exhausted", "run_cancelled")
    assert set(L.EXHAUSTED_REASONS) < set(L.END_REASONS)
    assert (L.START_BLOCKED, L.NOT_RUN_REASON, L.APPROVED_BY) == ("approval_required", "docking_not_run", "human")


def test_axes_match_spec():
    assert L.AXES == ("expensive_units", "wall_clock_s", "external_tokens", "usd", "sends")
    assert L.COMPUTE_AXES == ("expensive_units", "wall_clock_s")
    assert L.SEND_AXES == ("external_tokens", "usd", "sends")
    assert set(L.COMPUTE_AXES) | set(L.SEND_AXES) == set(L.AXES) and not set(L.COMPUTE_AXES) & set(L.SEND_AXES)


def test_refusal_sets_in_spec_order():
    assert L.CREATE_REASONS == ("unknown_field", "loop_id_invalid", "dry_run", "branch_invalid",
                                "capability_unavailable", "loop_active", "pool_invalid", "goal_invalid",
                                "seed_invalid", "iteration_cap_invalid", "setup_invalid")
    assert L.LOOP_ID_CONFLICT == "loop_id_conflict"
    assert L.PROJECTION_REASON_CODES == ("unknown_field", "loop_not_found", "loop_ended", "iteration_mismatch",
                                         "selection_done", "phase_invalid", "cap_reached", "too_few_candidates",
                                         "source_invalid", "structure_unavailable", "wire_field_invalid",
                                         "payload_too_large")
    assert L.PROJECTION_INVALID == "projection_invalid"
    assert L.LOOP_SEND_INVALID == "loop_send_invalid"
    assert L.LOOP_SEND_REASONS == ("loop_not_found", "loop_ended", "iteration_mismatch", "selection_done",
                                   "phase_invalid", "cap_reached", "too_few_candidates", "state_changed",
                                   "ordinal_mismatch")
    assert L.COMPUTE_REASONS == ("unknown_field", "loop_not_found", "cancelled", "loop_ended", "send_in_progress",
                                 "iteration_invalid", "phase_invalid", "iteration_cap_reached", "proposal_invalid",
                                 "proposal_late", "candidate_invalid", "candidate_unavailable", "candidate_computed",
                                 "capability_unavailable", "budget_blocked")
    assert L.STEP_UNAVAILABLE == "step_unavailable"
    assert L.END_REFUSAL_REASONS == ("loop_not_found", "cancelled", "loop_ended", "send_in_progress", "job_running",
                                     "docking_pending")
    # the projection refusals that are not about the loop state are the M24 projection names
    shared = set(L.PROJECTION_REASON_CODES) & set(J.PROJECTION_REASON_CODES)
    assert shared == {"unknown_field", "source_invalid", "structure_unavailable", "wire_field_invalid",
                      "payload_too_large"}


def test_request_keys_match_spec():
    assert L.CREATE_KEYS == ("loop_id", "branch", "pool", "goal", "loop_seed", "iteration_cap", "setup")
    assert L.POOL_KEYS == ("source", "candidates", "filter")
    assert L.COMPUTE_KEYS == ("iteration", "proposal", "candidate")
    assert L.ABANDON_KEYS == ("iteration",)
    assert L.TOOL_ARGUMENTS == ("loop_id", "iteration")


def test_names_match_spec_and_never_reuse_the_m24_names():
    assert (L.TOOL, L.TOOL_VERSION) == ("build_jev_loop_projection", "1")
    assert L.LOOP_SCHEMA == "jev_loop@1"
    assert (L.PROJECTION_KIND, L.PROJECTION_SCHEMA, L.PROJECTION_METHOD_VERSION) == (
        "jev_loop_projection", "jev_loop_projection@1", "mw.jev_loop_projection/v1")
    assert (L.CHOICE_KIND, L.CHOICE_SCHEMA, L.CHOICE_METHOD_VERSION) == (
        "jev_loop_choice", "jev_loop_choice@1", "mw.jev_loop_choice/v1")
    assert (L.RESULT_KIND, L.RESULT_SCHEMA, L.RESULT_METHOD_VERSION) == (
        "jev_loop_result", "jev_loop_result@1", "mw.jev_loop_result/v1")
    assert L.EVENT_TYPES == ("jev_loop_created", "jev_loop_compute_approved", "jev_loop_docking_abandoned",
                             "jev_loop_ended")
    assert (L.EVENT_CREATED, L.EVENT_COMPUTE_APPROVED, L.EVENT_DOCKING_ABANDONED, L.EVENT_ENDED) == L.EVENT_TYPES
    assert L.CAPABILITY_METHOD == "jev_loop"
    assert (L.REPORT_ANALYSIS_TYPE, L.REPORT_RENDER, L.REPORT_LABEL, L.REPORT_GENERATION_MODE) == (
        "jev_loop", "jev_loop_markdown@1", "JEV 루프 보고서", "local_rules_no_egress")
    assert L.REPORT_EVIDENCE_KINDS == ("computed", "model_response")
    m24 = {J.EVENT_CONSENT, J.EVENT_APPROVED, J.EVENT_DISPATCH, J.EVENT_OUTCOME, J.TOOL, J.PROJECTION_SCHEMA,
           J.CHOICE_SCHEMA, J.PROJECTION_KIND, J.CHOICE_KIND}
    assert not m24 & {L.TOOL, L.PROJECTION_SCHEMA, L.CHOICE_SCHEMA, L.RESULT_SCHEMA, L.PROJECTION_KIND,
                      L.CHOICE_KIND, L.RESULT_KIND, *L.EVENT_TYPES}


def test_adjustable_defaults():
    assert L.STEP_TIMEOUT_DEFAULTS_S == {"ligand_dock": 300, "model": 120, "dock": 300}
    assert set(L.STEP_TIMEOUT_DEFAULTS_S) == set(L.STEPS)
    assert L.UNITS_PER_STEP == 1
    assert L.DEFAULT_CONTACT_CUTOFF_A == 4.0 and type(L.DEFAULT_CONTACT_CUTOFF_A) is float
    assert L.READ_POLL_INTERVAL_S == 2
    # spec 7: the whole-iteration need of a first step (ligand 1 unit / 300 s, protein 2 units / 420 s)
    need = {branch: (L.UNITS_PER_STEP * len(steps), sum(L.STEP_TIMEOUT_DEFAULTS_S[s] for s in steps))
            for branch, steps in L.BRANCH_STEPS.items()}
    assert need == {"ligand": (1, 300), "protein": (2, 420)}


def test_is_loop_id_accepts_canonical_v4_uuids_only():
    good = str(uuid.uuid4())
    assert L.is_loop_id(good)
    for bad in (good.upper(), good.replace("-", ""), "{" + good + "}", str(uuid.uuid1()), str(uuid.UUID(int=0)),
                "loop-1", "", None, 5, uuid.uuid4()):
        assert not L.is_loop_id(bad), bad


# ---------------------------------------------------------------- questions, instructions, wire lists


def test_question_ids_and_the_m24_question_shape():
    assert (L.LIGAND_QUESTION_ID, L.MUTATION_QUESTION_ID) == ("ligand_loop_choice@1", "mutation_loop_choice@1")
    assert L.QUESTION_IDS == ("ligand_loop_choice@1", "mutation_loop_choice@1")
    assert L.QUESTION_FOR_KIND == {"ligand": "ligand_loop_choice@1", "mutation": "mutation_loop_choice@1"}
    assert not set(L.QUESTION_IDS) & set(J.QUESTION_IDS)
    assert (L.QUESTION_KEY, L.QUESTION_TYPE, L.CRITERION_TEMPLATE) == (J.QUESTION_KEY, J.QUESTION_TYPE,
                                                                        J.CRITERION_TEMPLATE)
    assert L.QUESTION_KEY == "candidate_choice" and L.QUESTION_TYPE == "choice"
    assert L.CRITERION_TEMPLATE.format(alias="m07") == "Candidate m07."


def test_instructions_are_the_spec_text_verbatim():
    assert L.INSTRUCTIONS == SPEC_INSTRUCTIONS
    assert list(L.INSTRUCTIONS) == list(SPEC_INSTRUCTIONS)
    for (kind, goal), text in SPEC_INSTRUCTIONS.items():
        assert text.isascii() and "\n" not in text and text.endswith("carry no meaning.")
        assert L.instructions_sha256(kind, goal) == hashlib.sha256(text.encode("ascii")).hexdigest()
    with pytest.raises(KeyError):
        L.instructions_sha256("protein", "explore")
    with pytest.raises(KeyError):
        L.instructions_sha256("ligand", "neutral")


def test_instructions_never_mix_with_the_m24_instructions():
    for text in L.INSTRUCTIONS.values():
        assert text not in J.INSTRUCTIONS.values()
        assert "local stored order only" not in text   # the M24 order sentence
        assert text.startswith(C) and not any(text.startswith(m24) for m24 in J.INSTRUCTIONS.values())
    for m24 in J.INSTRUCTIONS.values():
        assert "shuffled" not in m24 and "computed" not in m24
    # explore never mentions a score; exploit carries S; only the mutation exploit carries NC
    assert "score" not in L.INSTRUCTIONS[("ligand", "explore")] + L.INSTRUCTIONS[("mutation", "explore")]
    assert all(S in L.INSTRUCTIONS[(kind, "exploit")] for kind in L.KINDS)
    assert NC in L.INSTRUCTIONS[("mutation", "exploit")] and NC not in L.INSTRUCTIONS[("ligand", "exploit")]


# Forbidden interpretation words may appear only inside the fixed spec phrases that negate them.
FORBIDDEN_WORDS = ("best", "optimal", "optimiz", "improv", "promising", "rank", "recommend", "winner", "better",
                   "good", "predict", "affinity", "stability", "activity", "binding", "effect", "likely", "should",
                   "highest", "top ")
NEGATING_PHRASES = (
    ("it is not a prediction of binding, activity, affinity, stability, synthesizability, safety or the effect of a "
     "substitution"),
    "not an affinity",
    "not a prediction of any score or of the effect of a mutation",
    "not a prediction of any score",
)


@pytest.mark.parametrize("key", list(SPEC_INSTRUCTIONS))
def test_forbidden_words_appear_only_inside_the_negating_spec_phrases(key):
    text = L.INSTRUCTIONS[key]
    for phrase in NEGATING_PHRASES:
        text = text.replace(phrase, " ")
    lowered = text.lower()
    for word in FORBIDDEN_WORDS:
        assert word not in lowered, (key, word)


def test_wire_names_and_allow_lists():
    assert L.WIRE_SCHEMAS == {"ligand": "jev_loop_ligand_candidates@1", "mutation": "jev_loop_mutation_candidates@1"}
    assert L.WIRE_TASK == "choose_one_candidate" == J.WIRE_TASK
    assert L.ALLOWED_TOP == {
        "ligand": ("schema", "task", "goal", "parent", "property_methods", "candidates", "computed", "values_note"),
        "mutation": ("schema", "task", "goal", "positions", "candidates", "protection_checks", "pockets", "computed",
                     "values_note")}
    assert L.OPTIONAL_TOP == {"ligand": (), "mutation": ("pockets",)}
    # the loop wire is the M24 wire plus goal and computed, nothing else (spec 4.4)
    assert set(L.ALLOWED_TOP["ligand"]) == set(J.ALLOWED_LIGAND_TOP) | {"goal", "computed"}
    assert set(L.ALLOWED_TOP["mutation"]) == set(J.ALLOWED_MUTATION_TOP) | {"goal", "computed"}
    assert L.ALLOWED_COMPUTED == {"explore": ("alias",), "exploit": ("alias", "state", "score_kcal_mol")}
    assert L.COMPUTED_STATES == ("scored", "no_score")
    assert L.COMPUTED_STATE_FOR == {"scored": "scored", "null_result": "no_score", "failed": "no_score",
                                    "not_run": "no_score"}
    assert L.ORDER_ALGORITHM == "sha256_order_v1"


def test_values_notes_are_the_spec_strings():
    assert L.VALUES_NOTES == SPEC_NOTES and list(L.VALUES_NOTES) == list(SPEC_NOTES)
    assert L.VALUES_NOTES[("ligand", "explore")] == J.LIGAND_VALUES_NOTE
    assert L.VALUES_NOTES[("mutation", "explore")] == J.MUTATION_VALUES_NOTE
    assert L.VALUES_NOTES[("ligand", "exploit")].startswith(J.LIGAND_VALUES_NOTE + "; ")
    assert L.VALUES_NOTES[("mutation", "exploit")].startswith(J.MUTATION_VALUES_NOTE + "; ")


def test_projection_and_choice_key_lists():
    assert L.PROJECTION_KEYS == ("schema", "method_version", "kind", "loop", "goal", "source", "structure",
                                 "question", "order", "selection", "wire", "wire_sha256", "body_sha256",
                                 "body_bytes", "limitations")
    assert L.LOOP_REF_KEYS == ("loop_id", "iteration", "send_ordinal")
    assert L.ORDER_KEYS == ("algorithm", "loop_seed", "iteration", "send_ordinal")
    assert L.SELECTION_KEYS == ("alias", "ref", "state")
    assert L.SELECTION_STATES == ("pending", "scored", "null_result", "failed", "not_run")
    assert set(L.SELECTION_STATES) == set(L.CANDIDATE_STATES) - {"unavailable"}
    assert L.CHOICE_LABEL == "JEV 판정(모델 선택)" == J.CHOICE_LABEL
    assert L.CHOICE_KEYS == ("schema", "method_version", "label", "scientific_result", "loop", "goal", "send",
                             "source", "projection", "question", "requested_model", "served_model", "selection",
                             "answer", "usage", "arrival", "limitations")
    assert L.CHOICE_SEND_KEYS == ("send_id", "audit_id")
    assert L.CHOICE_PROJECTION_KEYS == ("handle", "wire_sha256", "body_sha256", "body_bytes")
    assert L.CHOICE_QUESTION_KEYS == ("id", "key", "instructions_sha256")
    assert L.ANSWER_KEYS == ("choice_alias", "list_position", "list_size", "local_ref", "local_display",
                             "confidence", "probabilities")
    assert L.LOCAL_REF_KEYS == {"ligand": ("candidate_id",), "mutation": ("candidate_index", "position_index")}
    assert L.DISPLAY_KEYS == {"ligand": ("smiles",), "mutation": ("residue", "from", "to")}
    assert L.USAGE_KEYS == ("input_tokens", "output_tokens", "external_tokens", "cost")
    assert L.ARRIVAL_KEYS == ("late", "late_reason")
    for keys in (L.CHOICE_KEYS, L.ANSWER_KEYS, L.PROJECTION_KEYS):
        lowered = " ".join(keys).lower()
        assert not any(word in lowered for word in ("rank", "best", "recommend", "score", "improv", "winner"))


# ---------------------------------------------------------------- fixed sentences and their linkage


def test_lj_and_ul_sentences_verbatim():
    assert (L.LJ1, L.LJ2, L.LJ3, L.LJ4, L.LJ5, L.LJ6, L.LJ7, L.LJ8) == tuple(SPEC_LJ.values())
    assert L.STATEMENTS == SPEC_LJ and list(L.STATEMENTS) == [f"LJ{n}" for n in range(1, 9)]
    assert (L.UL1, L.UL2, L.UL3) == tuple(SPEC_UL.values())
    assert L.SCREEN_NOTES == SPEC_UL and list(L.SCREEN_NOTES) == ["UL1", "UL2", "UL3"]
    assert L.J7 == J.J7   # late proposals use the M24 J7 as it is


@pytest.mark.parametrize(("kind", "goal", "middle", "last"), [
    ("ligand", "explore", "LJ5", "LJ6"), ("ligand", "exploit", "LJ4", "LJ6"),
    ("mutation", "explore", "LJ5", "LJ7"), ("mutation", "exploit", "LJ4", "LJ7")])
def test_limitations_for_projections_and_proposals(kind, goal, middle, last):
    expected = [SPEC_LJ["LJ1"], SPEC_LJ["LJ2"], SPEC_LJ["LJ3"], SPEC_LJ[middle], SPEC_LJ[last]]
    assert L.limitations_for(kind, goal, False) == expected
    assert L.limitations_for(kind, goal, True) == [*expected, J.J7]
    assert L.limitations_for(kind, goal, False) is not L.limitations_for(kind, goal, False)
    assert L.limitation_ids(kind, goal, uncomputed_left=False) == ["LJ1", "LJ2", "LJ3", middle, last]
    assert L.limitation_ids(kind, goal, uncomputed_left=True) == ["LJ1", "LJ2", "LJ3", middle, last, "LJ8"]


def test_limitation_functions_refuse_unknown_input():
    for args in (("protein", "explore", False), ("ligand", "neutral", False), ("ligand", "explore", 1),
                 ("ligand", "explore", None)):
        with pytest.raises(ValueError):
            L.limitations_for(*args)
    for kind, goal, left in (("protein", "explore", False), ("ligand", "x", True), ("mutation", "exploit", 0)):
        with pytest.raises(ValueError):
            L.limitation_ids(kind, goal, uncomputed_left=left)


# ---------------------------------------------------------------- module hygiene


def _imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
    return found


def test_constants_module_imports_only_the_standard_library():
    assert _imports(MW / "jev_loop_constants.py") <= {"__future__", "hashlib", "uuid"}


def test_constants_module_never_names_the_limit_raise_functions_or_the_m24_event_strings():
    text = (MW / "jev_loop_constants.py").read_text()
    assert "raise_limits" not in text and "limit_approval" not in text
    for name in (J.EVENT_CONSENT, J.EVENT_APPROVED, J.EVENT_DISPATCH, J.EVENT_OUTCOME):
        assert name not in text, name
    assert not re.search(r"\bjev_sends\b", text)


def test_importing_the_constants_module_loads_nothing_else_of_mw():
    code = ("import sys, mw.jev_loop_constants\n"
            "print(sorted(m for m in sys.modules if m.startswith('mw.') and m != 'mw.jev_loop_constants'))\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=str(MW.parent))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr
