/**
 * Pure logic of the M25 "JEV 루프" areas of the 리간드 설계·탐색 and 단백질 공학 tabs (`.dryforge/spec.md` 2, 3, 4.5,
 * 5.1, 5.3, 6.1, 7, 8, 9.3, 10).
 *
 * Every number, state, phase, need, shortfall, order and sentence shown comes from the server (`jev_loop@1`, the
 * `jev_preview@1` of a loop projection, the `jev_loop_choice@1` proposal, the list rows); this module never computes a
 * score, an aggregate, a shortfall, a shuffle or whether a candidate is computed. It decides the pool guard (2–20; the
 * M24 candidate guard of `jev.ts` is reused), the create request with its per-field reasons, the buttons each phase
 * opens, the candidate table rows and their display order (rows without a score stay last in every order and are never
 * 0), the loop preview and approval view (the M24 `send_id` rule), the JEV proposal card (probabilities in the sent
 * order, values only) and the wording check. A JEV choice is "JEV 판정(모델 선택)", a proposal: never a rank,
 * recommendation or prediction. The fixed sentences LJ1–LJ8 are the server's stored `limitations`, shown as given and
 * never re-written here; UL1–UL3 (and the M24 note U3 in the protein area) are the screen's own fixed notes.
 */
import type { CommandResult } from "./api";
import type { JevKind, JevLocalDisplay, JevLoopAbandonRequest, JevLoopAction, JevLoopAmounts, JevLoopAxis,
  JevLoopBranch, JevLoopCandidateState, JevLoopCapability, JevLoopComputeRequest, JevLoopCreateRequest,
  JevLoopDecidedBy, JevLoopEndReason, JevLoopEvaluation, JevLoopExhaustedReason, JevLoopGoal, JevLoopIteration,
  JevLoopIterationSend, JevLoopIterationState, JevLoopLigandSetup, JevLoopListRow, JevLoopPhase, JevLoopPoolArgs,
  JevLoopPreviewV1, JevLoopProjectionArgs, JevLoopProjectionSummary, JevLoopProteinSetup, JevLoopRef,
  JevLoopReportArtifact, JevLoopSendDetail, JevLoopSendLoopRef, JevLoopStep, JevLoopStepState, JevLoopV1, JevStatusV1,
  LigandFilterSpec } from "./contracts";
import { type ArgsCheck, type DockingForm, DOCKING_REASON_LABEL, SCORE_COLUMN_LABEL, SCORE_LABEL, dockingArgs,
  dockingConditionArgs, initialDockingForm, patchDockingForm, scoreText } from "./docking";
import { CHOICE_REASON_TEXT, CONFIRM_CHECK_TEXT, JEV_CHOICE_LABEL, JEV_CONFIDENCE_LABEL, JEV_SCREEN_NOTES,
  JEV_STATEMENTS, KIND_LABEL, NOT_REPORTED_TEXT, NOT_SENT_TEXT, NULL_TEXT, PROBABILITY_NOTE, REQUEST_FAILED_TEXT,
  SEND_ERROR_CODES, UNKNOWN_CODE_TEXT, type JevPreviewBlocker, type JevSelection, type JevUsageRow,
  activeJevFilter, confidenceText, errorCodeText, jevCapText, jevPreviewBlockers, jevPreviewMatches,
  jevSelectedCandidates, lateReasonText, localDisplayText, newSendId, sendReasonText, sendStatusText, usageRows,
  usdText } from "./jev";
import { CONTACT_CUTOFF_DEFAULT_A, CONTACT_CUTOFF_RANGE_A, HYDROGEN_POLICY, MODEL_REASON_LABEL,
  PAIR_INSTANCE_RANGE_REASON, type PairDockingForm, SELECTION_POLICY, cutoffValue, initialPairDockingForm,
  pairBoxSourceDisabledReason, patchPairDockingForm } from "./mutation-model";

export { SCORE_COLUMN_LABEL, SCORE_LABEL };

// ---- closed sets, caps and defaults (backend/mw/jev_loop_constants.py, verbatim; tests read that file) ----

export const LOOP_BRANCHES: readonly JevLoopBranch[] = ["ligand", "protein"];
export const LOOP_GOALS: readonly JevLoopGoal[] = ["explore", "exploit"];
export const LOOP_KIND_FOR_BRANCH: Record<JevLoopBranch, JevKind> = { ligand: "ligand", protein: "mutation" };
export const LOOP_MIN_POOL = 2;
export const LOOP_MAX_POOL = 20;
export const ITERATION_CAP_MIN = 1;
export const ITERATION_CAP_MAX = 8;
/** Adjustable screen default of the iteration cap (spec 11). */
export const ITERATION_CAP_DEFAULT = 5;
export const LOOP_SEED_MIN = 0;
export const LOOP_SEED_MAX = 2147483647;
/** One pending candidate or none: no send is offered (spec 3.3). */
export const MIN_PENDING_TO_SEND = 2;
export const LOOP_TOOL = "build_jev_loop_projection";
export const LOOP_SCHEMA = "jev_loop@1";
export const LOOP_PROJECTION_KIND = "jev_loop_projection";
export const LOOP_PROJECTION_SCHEMA = "jev_loop_projection@1";
export const LOOP_CHOICE_SCHEMA = "jev_loop_choice@1";
export const LOOP_RESULT_SCHEMA = "jev_loop_result@1";
export const LOOP_REPORT_TYPE = "jev_loop";
export const LOOP_REPORT_LABEL = "JEV 루프 보고서";
export const ORDER_ALGORITHM = "sha256_order_v1";
export const LOOP_QUESTION_IDS = ["ligand_loop_choice@1", "mutation_loop_choice@1"] as const;
export const LOOP_CANDIDATE_STATES: readonly JevLoopCandidateState[] = ["pending", "scored", "null_result", "failed",
  "not_run", "unavailable"];
export const LOOP_EVALUATIONS: readonly JevLoopEvaluation[] = ["computed", "reused"];
export const LOOP_STEPS: readonly JevLoopStep[] = ["ligand_dock", "model", "dock"];
export const LOOP_STEP_STATES: readonly JevLoopStepState[] = ["waiting_start", "running", "completed", "failed",
  "unavailable", "reused"];
export const LOOP_ITERATION_STATES: readonly JevLoopIterationState[] = ["in_progress", "scored", "null_result", "failed",
  "not_run", "unavailable"];
export const LOOP_PHASES: readonly JevLoopPhase[] = ["awaiting_selection", "awaiting_compute", "running",
  "awaiting_docking", "done"];
export const LOOP_ACTIONS: readonly JevLoopAction[] = ["select", "compute", "wait_job", "dock", "end", "none"];
export const LOOP_DECIDED_BY: readonly JevLoopDecidedBy[] = ["jev", "human"];
export const LOOP_EXHAUSTED_REASONS: readonly JevLoopExhaustedReason[] = ["iteration_cap", "pool_exhausted"];
export const LOOP_END_REASONS: readonly JevLoopEndReason[] = ["iteration_cap", "pool_exhausted", "ended_by_user",
  "budget_exhausted", "run_cancelled"];
export const LOOP_AXES: readonly JevLoopAxis[] = ["expensive_units", "wall_clock_s", "external_tokens", "usd", "sends"];
export const LOOP_START_BLOCKED = "approval_required";
export const LOOP_NOT_RUN_REASON = "docking_not_run";
/** `POST /runs/{id}/jev_loops` admission reasons, in check order (first failure only). */
export const LOOP_CREATE_REASONS = ["unknown_field", "loop_id_invalid", "dry_run", "branch_invalid",
  "capability_unavailable", "loop_active", "pool_invalid", "goal_invalid", "seed_invalid", "iteration_cap_invalid",
  "setup_invalid"] as const;
/** Same `loop_id`, another body (409). */
export const LOOP_ID_CONFLICT = "loop_id_conflict";
/** `build_jev_loop_projection` admission reasons in check order, then the read refusal `projection_invalid`. */
export const LOOP_PROJECTION_REASON_CODES = ["unknown_field", "loop_not_found", "loop_ended", "iteration_mismatch",
  "selection_done", "phase_invalid", "cap_reached", "too_few_candidates", "source_invalid", "structure_unavailable",
  "wire_field_invalid", "payload_too_large", "projection_invalid"] as const;
/** The send route's 409 error code of a refused loop send; its `detail.reason` is one of `LOOP_SEND_REASONS`. */
export const LOOP_SEND_INVALID = "loop_send_invalid";
export const LOOP_SEND_REASONS = ["loop_not_found", "loop_ended", "iteration_mismatch", "selection_done",
  "phase_invalid", "cap_reached", "too_few_candidates", "state_changed", "ordinal_mismatch"] as const;
/** `.../compute` refusals in check order; `step_unavailable` is the race refusal after them. */
export const LOOP_COMPUTE_REASONS = ["unknown_field", "loop_not_found", "cancelled", "loop_ended", "send_in_progress",
  "iteration_invalid", "phase_invalid", "iteration_cap_reached", "proposal_invalid", "proposal_late",
  "candidate_invalid", "candidate_unavailable", "candidate_computed", "capability_unavailable",
  "budget_blocked"] as const;
export const LOOP_STEP_UNAVAILABLE = "step_unavailable";
export const LOOP_END_REFUSAL_REASONS = ["loop_not_found", "cancelled", "loop_ended", "send_in_progress",
  "job_running", "docking_pending"] as const;
/** Reads are polled at this interval while a job or a send of the open loop is in progress (reads only). */
export const LOOP_POLL_MS = 2000;

// ---- fixed screen notes (spec 9.3, verbatim; never sent) ----

export const LOOP_SCREEN_NOTES = {
  UL1: "JEV 루프는 바퀴마다 보낼 내용 승인과 계산 시작 승인을 따로 받는다. JEV가 고른 후보도 사람이 승인해야 계산된다.",
  UL2: "한 바퀴에 JEV 응답이 한 번 완료되면 다시 묻지 않는다. 다른 후보를 원하면 직접 지정한다.",
  UL3: "루프 전송은 뷰어 모델 명령·지식·보고서 탭의 전송과 같은 외부 토큰·USD 예산, 같은 run 10회 전송 상한, 같은 " +
    "'사용량 모름' 중지 상태를 쓴다.",
} as const;
/** The protein area also shows the M24 note U3, verbatim. */
export const PROTEIN_SCREEN_NOTE = JEV_SCREEN_NOTES.U3;

// ---- fixed screen text ----

export const LOOP_AREA_TITLE = "JEV 루프";
export const BRANCH_LABEL: Record<JevLoopBranch, string> = { ligand: "리간드", protein: "단백질" };
export const GOAL_LABEL: Record<JevLoopGoal, string> = { explore: "탐색형", exploit: "활용형" };
/** One line per goal beside the radio (nothing is chosen automatically). */
export const GOAL_MEANING: Record<JevLoopGoal, string> = {
  explore: "이미 계산한 후보와 가장 다른 후보를 고르게 묻습니다(계산된 후보의 별칭만 보내고 점수는 보내지 않음).",
  exploit: "점수가 낮게 나온 계산된 후보와 비슷한 후보를 고르게 묻습니다(계산된 후보의 저장된 qvina 점수 값을 함께 보냄).",
};
export const LOOP_SEED_NOTE = "루프 seed는 전송마다 후보 순서와 별칭을 섞는 데만 쓰며 도킹·모델링 seed와 별개입니다.";
export const FREE_DOCKING_NOTE = "루프의 도킹은 자유 도킹으로 고정됩니다(코어 고정 없음).";
export const PROTEIN_SEED_NOTE = "단백질 루프는 도킹 값의 seed를 변이 구조 모델링 seed로도 같은 값으로 씁니다.";
export const POOL_FIXED_NOTE = "풀과 계산 조건은 루프를 만들 때 고정되며 바퀴 중에 바꿀 수 없습니다.";
export const ORDER_NOTE = "표의 정렬은 표시 순서일 뿐입니다. 점수 없는 후보는 0이 아니며 어떤 정렬에서도 끝에 둡니다.";
export const LIST_POSITION_LABEL = "목록 위치(보낸 목록에서 계산하지 않은 후보 가운데 순번/개수)";
export const ALIAS_TABLE_NOTE = "별칭 ↔ 로컬 후보 대응은 이 화면에만 있으며 외부로 보내지 않습니다. 계산된 후보는 JEV가 고를 수 " +
  "없습니다.";
export const CANCEL_BEFORE_START_NOTE = "시작 전에 취소하면 이 후보는 이 run에서 다시 계산할 수 없게 됩니다(unavailable). " +
  "그 뒤 다른 후보를 직접 지정하거나 루프를 끝낼 수 있습니다.";
export const FIRST_APPROVAL_GUIDE = "이 run의 첫 비싼 계산은 승인해야 시작됩니다. 비싼 계산을 승인한 뒤 작업 시작을 다시 " +
  "누르세요 (approval_required).";
export const LATE_CHOICE_NOTE = "늦게 도착한 JEV 판정은 이 바퀴의 선택이 아닙니다. 같은 후보를 직접 지정할 수는 있습니다.";
export const NO_RUN_REASON = "run이 없습니다. 구조 분석 탭에서 run을 먼저 고르세요.";
export const CAPABILITY_REASON = "JEV 루프 기능을 사용할 수 없습니다.";
export const NO_LOOPS_TEXT = "이 run에 이 갈래의 JEV 루프가 없습니다. 아래에서 만들 수 있습니다.";
export const BUSY_REASON = "요청을 처리하는 중입니다.";
export const LOOP_SWITCH_BUSY_REASON = "진행 중인 요청이 끝난 뒤 다른 루프를 열 수 있습니다(한 번에 한 루프).";
export const CHOICE_MISMATCH_TEXT = "저장된 JEV 판정을 이 루프·전송과 맞출 수 없어 보이지 않습니다.";
export const NOT_A_LOOP_PROJECTION_TEXT = "도구 결과가 JEV 루프 투영(jev_loop_projection@1)이 아닙니다.";
export const CONFIRMATION_ERROR = "protein_only와 rebuild_pH7 확인을 모두 체크하세요 (confirmation_missing).";

// ---- closed labels ("한국어 (code)"; anything outside a set is UNKNOWN_CODE_TEXT) ----

const CANDIDATE_STATE_LABEL: Record<JevLoopCandidateState, string> = {
  pending: "계산하지 않음", scored: "점수 있음", null_result: "빈 결과(모드 0개)", failed: "실패",
  not_run: "도킹하지 않음(모델만 있음)", unavailable: "이 run에서 계산할 수 없음",
};
const EVALUATION_LABEL: Record<JevLoopEvaluation, string> = { computed: "새 계산", reused: "저장된 결과 재사용" };
const DECIDED_BY_LABEL: Record<JevLoopDecidedBy, string> = { jev: "JEV", human: "사람" };
const PHASE_LABEL: Record<JevLoopPhase, string> = {
  awaiting_selection: "선택 대기(보내거나 직접 지정)", awaiting_compute: "계산 시작 대기(JEV 선택 승인 또는 직접 지정)",
  running: "작업 진행 중", awaiting_docking: "도킹 대기(시작 또는 포기)", done: "끝난 바퀴",
};
const ACTION_LABEL: Record<JevLoopAction, string> = {
  select: "보낼 내용 만들기 또는 직접 지정", compute: "이 선택으로 계산 시작 또는 직접 지정", wait_job: "작업 진행 중(읽기만)",
  dock: "도킹 시작 또는 포기", end: "더 시작할 바퀴가 없음(루프 끝내기)", none: "끝난 루프",
};
const STEP_LABEL: Record<JevLoopStep, string> = {
  ligand_dock: "리간드 도킹(M18 자유 도킹)", model: "변이 구조 모델링(M21)", dock: "변이 구조 도킹(M18 자유 도킹)",
};
const STEP_STATE_LABEL: Record<JevLoopStepState, string> = {
  waiting_start: "대기열(아직 시작하지 않음)", running: "실행 중", completed: "완료(결과 게시)",
  failed: "실패(시작한 뒤)", unavailable: "시작 전에 끝남(이 run에서 다시 만들 수 없음)", reused: "저장된 결과 재사용",
};
const ITERATION_STATE_LABEL: Record<JevLoopIterationState, string> = {
  in_progress: "진행 중", scored: "점수 있음", null_result: "빈 결과(모드 0개)", failed: "실패", not_run: "도킹하지 않음",
  unavailable: "시작하지 못함",
};
const EXHAUSTED_LABEL: Record<JevLoopExhaustedReason, string> = {
  iteration_cap: "유효 반복 상한만큼 바퀴를 끝냄", pool_exhausted: "계산하지 않은 후보가 남지 않음",
};
const END_REASON_LABEL: Record<JevLoopEndReason, string> = {
  iteration_cap: "유효 반복 상한만큼 바퀴를 끝냄", pool_exhausted: "계산하지 않은 후보가 남지 않음",
  ended_by_user: "사람이 끝냄", budget_exhausted: "계산을 시작할 예산이 모자람", run_cancelled: "run이 취소됨(요약 없음)",
};
const AXIS_LABEL: Record<JevLoopAxis, string> = {
  expensive_units: "비싼 계산 단위", wall_clock_s: "활동 시간", external_tokens: "외부 토큰", usd: "USD",
  sends: "과학 전송 횟수",
};
const JOB_STATUS_LABEL: Record<string, string> = {
  queued: "대기열", claimed: "시작 준비(승인·자원 대기)", running: "실행 중", done: "끝남", failed: "실패",
  cancelled: "취소됨", interrupted: "중단됨",
};
/** Every loop refusal name of every loop route, the projection tool and the loop send check (one label each). */
const LOOP_REASON_LABEL: Record<string, string> = {
  unknown_field: "알 수 없는 요청 항목",
  loop_id_invalid: "루프 id 형식 오류(소문자 v4 UUID)",
  dry_run: "dry-run run에서는 루프를 만들 수 없음",
  branch_invalid: "갈래(ligand·protein) 형식 오류",
  capability_unavailable: "이 갈래의 계산 엔진을 사용할 수 없음",
  loop_active: "이 run에 끝나지 않은 같은 갈래의 루프가 있음",
  pool_invalid: `풀 오류(이 run의 게시된 후보 집합 하나, ${LOOP_MIN_POOL}–${LOOP_MAX_POOL}개, 중복 없음, 집합 안의 후보, ` +
    "적용한 필터 통과)",
  goal_invalid: "목표(탐색형·활용형)를 고르지 않음",
  seed_invalid: `루프 seed는 ${LOOP_SEED_MIN}–${LOOP_SEED_MAX} 정수(필수)`,
  iteration_cap_invalid: `반복 상한은 ${ITERATION_CAP_MIN}–${ITERATION_CAP_MAX} 정수`,
  setup_invalid: "계산 조건 오류",
  loop_id_conflict: "같은 루프 id로 다른 내용의 루프가 이미 있음(루프 만들기를 다시 누르세요)",
  loop_not_found: "이 run에 없는 루프",
  loop_ended: "루프가 끝남",
  cancelled: "run이 취소됨",
  send_in_progress: "이 run의 과학 전송이 진행 중",
  iteration_mismatch: "바퀴 번호가 지금 바퀴와 다름(다시 읽기 필요)",
  iteration_invalid: "바퀴 번호가 지금 바퀴와 다름(다시 읽기 필요)",
  selection_done: "이 바퀴에는 JEV 응답이 이미 완료됨(다시 묻지 않음)",
  phase_invalid: "지금 바퀴 단계에서 받을 수 없는 동작",
  cap_reached: "유효 반복 상한만큼 바퀴를 시작함",
  iteration_cap_reached: "유효 반복 상한만큼 바퀴를 시작함",
  too_few_candidates: `계산하지 않은 후보가 ${MIN_PENDING_TO_SEND}개 미만이라 보낼 수 없음(직접 지정하거나 루프를 끝내세요)`,
  source_invalid: "루프의 후보 집합이 검증되지 않음",
  structure_unavailable: "후보 집합의 전처리 구조를 읽을 수 없거나 위치 잔기가 구조와 맞지 않음",
  wire_field_invalid: "보낼 수 있는 값의 형식 규칙에 맞지 않는 값이 있음",
  payload_too_large: "본문이 64 KiB를 넘음(자르지 않고 저장하지 않음)",
  projection_invalid: "저장된 루프 투영이 검증되지 않음",
  state_changed: "보낼 내용을 만든 뒤 후보의 계산 상태나 점수가 바뀜(보낼 내용을 다시 만드세요)",
  ordinal_mismatch: "보낼 내용을 만든 뒤 이 바퀴의 전송 수가 바뀜(보낼 내용을 다시 만드세요)",
  proposal_invalid: "이 바퀴의 처음 완료된 늦지 않은 JEV 판정이 아님",
  proposal_late: "늦게 도착한 JEV 판정이라 이 바퀴의 선택이 아님(직접 지정은 가능)",
  candidate_invalid: "풀에 없는 후보",
  candidate_unavailable: "같은 호출 키의 작업이 이 run에서 쓸 수 없는 상태로 남아 계산할 수 없는 후보",
  candidate_computed: "이미 계산된 후보(이 루프가 계산했거나 같은 조건의 저장 결과가 있음, 다른 후보를 직접 지정하세요)",
  budget_blocked: "남은 계산 예산이 이 후보에 필요한 양보다 적음",
  step_unavailable: "같은 호출 키의 작업이 루프 밖에서 생겨 이 단계를 시작할 수 없음",
  job_running: "이 루프가 승인한 작업이 대기열에 있거나 실행 중",
  docking_pending: "모델링을 마친 후보가 도킹 시작 또는 포기를 기다림",
};
/** Error classes of the loop routes and the command route that are not reason names. */
const LOOP_ERROR_LABEL: Record<string, string> = {
  loop_send_invalid: "JEV 루프가 지금 이 내용을 보낼 수 없음(아무것도 기록하지 않음)",
  busy: "run이 다른 작업 중(아무것도 기록하지 않음)",
  internal_error: "루프 기록을 이 run의 이벤트에서 다시 만들 수 없음",
  unsupported_media_type: "요청 형식이 JSON이 아님",
  approval_required: "실행 승인이 필요함",
};

function own(table: Record<string, string>, code: string): string | undefined {
  return Object.prototype.hasOwnProperty.call(table, code) ? table[code] : undefined;
}

function labelled(codes: readonly string[], table: Record<string, string>, code: unknown): string {
  if (typeof code !== "string" || !codes.includes(code)) return UNKNOWN_CODE_TEXT;
  const label = own(table, code);
  return label ? `${label} (${code})` : UNKNOWN_CODE_TEXT;
}

export function candidateStateText(state: unknown): string {
  return labelled(LOOP_CANDIDATE_STATES, CANDIDATE_STATE_LABEL, state);
}
export function evaluationText(value: JevLoopEvaluation | null): string {
  return value === null ? NULL_TEXT : labelled(LOOP_EVALUATIONS, EVALUATION_LABEL, value);
}
/** "JEV" / "사람" (who chose the candidate of an iteration); null is "—". */
export function decidedByText(value: JevLoopDecidedBy | null): string {
  return value === null ? NULL_TEXT : own(DECIDED_BY_LABEL, value) ?? UNKNOWN_CODE_TEXT;
}
export function phaseText(phase: unknown): string { return labelled(LOOP_PHASES, PHASE_LABEL, phase); }
export function actionText(action: unknown): string { return labelled(LOOP_ACTIONS, ACTION_LABEL, action); }
export function stepText(step: unknown): string { return labelled(LOOP_STEPS, STEP_LABEL, step); }
export function stepStateText(state: unknown): string { return labelled(LOOP_STEP_STATES, STEP_STATE_LABEL, state); }
export function iterationStateText(state: unknown): string {
  return labelled(LOOP_ITERATION_STATES, ITERATION_STATE_LABEL, state);
}
export function exhaustedReasonText(reason: unknown): string {
  return labelled(LOOP_EXHAUSTED_REASONS, EXHAUSTED_LABEL, reason);
}
export function endReasonText(reason: unknown): string { return labelled(LOOP_END_REASONS, END_REASON_LABEL, reason); }
export function axisText(axis: unknown): string { return labelled(LOOP_AXES, AXIS_LABEL, axis); }
export function goalText(goal: unknown): string { return labelled(LOOP_GOALS, GOAL_LABEL, goal); }
export function createReasonText(code: unknown): string {
  return labelled([...LOOP_CREATE_REASONS, LOOP_ID_CONFLICT], LOOP_REASON_LABEL, code);
}
export function computeReasonText(code: unknown): string {
  return labelled([...LOOP_COMPUTE_REASONS, LOOP_STEP_UNAVAILABLE], LOOP_REASON_LABEL, code);
}
export function endRefusalText(code: unknown): string {
  return labelled(LOOP_END_REFUSAL_REASONS, LOOP_REASON_LABEL, code);
}
export function loopProjectionReasonText(code: unknown): string {
  return labelled(LOOP_PROJECTION_REASON_CODES, LOOP_REASON_LABEL, code);
}
export function loopSendReasonText(code: unknown): string {
  return labelled(LOOP_SEND_REASONS, LOOP_REASON_LABEL, code);
}
/** Job status of `current.job` ("대기열 (queued)" …). */
export function loopJobStatusText(status: unknown): string {
  return labelled(Object.keys(JOB_STATUS_LABEL), JOB_STATUS_LABEL, status);
}

/** An M18 / M21 closed name (setup refusal, job admission refusal, step failure); protein prefers the M21 name. */
export function engineReasonText(code: unknown, preferModel = false): string {
  if (typeof code !== "string") return UNKNOWN_CODE_TEXT;
  const model = own(MODEL_REASON_LABEL, code), docking = own(DOCKING_REASON_LABEL, code);
  const label = preferModel ? model ?? docking : docking ?? model;
  return label ? `${label} (${code})` : UNKNOWN_CODE_TEXT;
}

/** A step's closed reason: the M21 name for the model step, the M18 name for docking, `docking_not_run` its own. */
export function stepReasonText(step: JevLoopStep, code: string | null): string | null {
  if (code === null) return null;
  if (code === LOOP_NOT_RUN_REASON) return `도킹하지 않음 (${LOOP_NOT_RUN_REASON})`;
  return engineReasonText(code, step === "model");
}

// ---- errors (loop routes, the command route, the M24 send route's loop refusal, the M18 / M21 job admission) ----

export interface LoopErrorInfo { status: number | null; code: string | null; reasonCode: string | null; text: string }

function amountText(axis: JevLoopAxis, value: number | null): string {
  if (value === null) return NULL_TEXT;
  if (axis === "expensive_units") return `${value}단위`;
  if (axis === "wall_clock_s") return `${value}초`;
  if (axis === "usd") return usdText(value);
  if (axis === "sends") return `${value}회`;
  return String(value);
}

function detailExtra(reason: string, detail: Record<string, unknown>, branch: JevLoopBranch | null): string {
  if (reason === "setup_invalid") return `: ${engineReasonText(detail.setup_reason, branch === "protein")}`;
  if (reason === "capability_unavailable") {
    const capability = detail.capability as { reason_code?: unknown; reason?: unknown } | undefined;
    if (capability && typeof capability.reason === "string")
      return `: ${capability.reason}${typeof capability.reason_code === "string" ? ` (${capability.reason_code})` : ""}`;
    return "";
  }
  if (reason === "pool_invalid" && Array.isArray(detail.candidates) && detail.candidates.length)
    return ` · 해당 후보: ${detail.candidates.map(item => String(item)).join(", ")}`;
  if (reason === "budget_blocked" && Array.isArray(detail.blocked_axes)) {
    const needs = (detail.needs ?? {}) as Record<string, unknown>;
    return " · " + detail.blocked_axes.map(axis => {
      const need = typeof needs[axis as string] === "number" ? needs[axis as string] as number : null;
      return `${axisText(axis)} 필요 ${(LOOP_AXES as readonly string[]).includes(axis as string)
        ? amountText(axis as JevLoopAxis, need) : NULL_TEXT}`;
    }).join(" · ");
  }
  if (reason === LOOP_STEP_UNAVAILABLE) {
    const job = detail.job as { id?: unknown; status?: unknown } | undefined;
    if (job && typeof job.id === "string") return ` · 작업 ${job.id} (${loopJobStatusText(job.status)})`;
  }
  return "";
}

/**
 * An `ApiError` (or any thrown value) of a loop call as status, code, reason and text "한국어 (code)". Loop routes
 * answer `{"detail": {error, reason_code, message, ...}}`, the command route `{"ok": false, error, message, detail:
 * {reason_code}}`, the M24 send route's loop refusal `{"detail": {error: "loop_send_invalid", reason}}`, the compute
 * route's M18 / M21 job admission refusal `{"ok": false, error, message, detail: {reason_code}}`. The server's English
 * `message` is never shown; a value outside every closed set is the fixed default text.
 */
export function loopErrorInfo(error: unknown, branch: JevLoopBranch | null = null): LoopErrorInfo {
  if (typeof error !== "object" || error === null)
    return { status: null, code: null, reasonCode: null, text: REQUEST_FAILED_TEXT };
  const { status, code, detail, approval } = error as { status?: unknown; code?: unknown;
    detail?: Record<string, unknown> | null; approval?: { gate?: unknown } | null };
  const codeText = typeof code === "string" ? code : null;
  const info = (reasonCode: string | null, text: string): LoopErrorInfo =>
    ({ status: typeof status === "number" ? status : null, code: codeText, reasonCode, text });
  const body = detail ?? {};
  if (codeText === LOOP_SEND_INVALID)
    return info(typeof body.reason === "string" ? body.reason : null,
      `${own(LOOP_ERROR_LABEL, LOOP_SEND_INVALID)} (${LOOP_SEND_INVALID}): ${loopSendReasonText(body.reason)}`);
  const reason = typeof body.reason_code === "string" ? body.reason_code : null;
  if (reason !== null) {
    const loop = own(LOOP_REASON_LABEL, reason);
    if (loop) return info(reason, `${loop} (${reason})${detailExtra(reason, body, branch)}`);
    return info(reason, engineReasonText(reason, branch === "protein"));
  }
  if (approval && typeof approval.gate === "string")
    return info(null, `${own(LOOP_ERROR_LABEL, "approval_required")} (${approval.gate})`);
  if (codeText !== null) {
    const label = own(LOOP_ERROR_LABEL, codeText);
    if (label) return info(null, `${label} (${codeText})`);
    if ((SEND_ERROR_CODES as readonly string[]).includes(codeText)) return info(null, errorCodeText(codeText));
    return info(null, UNKNOWN_CODE_TEXT);
  }
  return info(null, REQUEST_FAILED_TEXT);
}

// ---- panel state, capability, list ----

export type LoopPanelState = { state: "loading" } | { state: "ready" } | { state: "empty"; message: string } |
  { state: "failed"; message: string } | { state: "unavailable"; reason: string };

/**
 * Five states of one branch's area. `capability` undefined = not read yet, null = absent from `/capabilities`; `rows`
 * undefined or null = the loop list is not read yet. No loop of this branch is the empty state (the create form is
 * still shown); a failure is never shown as empty.
 */
export function loopPanelState(input: { runId: string | null; branch: JevLoopBranch;
  capability?: JevLoopCapability | null; rows?: readonly Pick<JevLoopListRow, "branch">[] | null;
  error?: string | null }): LoopPanelState {
  if (input.runId === null) return { state: "unavailable", reason: NO_RUN_REASON };
  if (input.capability === null) return { state: "unavailable", reason: CAPABILITY_REASON };
  const branch = input.capability?.[input.branch];
  if (input.capability !== undefined && (!branch || branch.available !== true))
    return { state: "unavailable", reason: branch?.reason
      ? `${branch.reason}${branch.reason_code ? ` (${branch.reason_code})` : ""}` : CAPABILITY_REASON };
  if (input.error) return { state: "failed", message: input.error };
  if (input.capability === undefined || input.rows === undefined || input.rows === null) return { state: "loading" };
  if (!input.rows.some(row => row.branch === input.branch)) return { state: "empty", message: NO_LOOPS_TEXT };
  return { state: "ready" };
}

export interface LoopListRowView { loopId: string; active: boolean; text: string; createdSeq: number }

/** This branch's loops in the server order (newest first); nothing is opened automatically. */
export function loopListRows(rows: readonly JevLoopListRow[], branch: JevLoopBranch): LoopListRowView[] {
  return rows.filter(row => row.branch === branch).map(row => ({
    loopId: row.loop_id, active: row.status === "active", createdSeq: row.created_seq,
    text: `${own(GOAL_LABEL, row.goal) ?? UNKNOWN_CODE_TEXT} · 풀 ${row.pool_size}개 · 시작한 바퀴 ${row.counts.started} · ` +
      (row.status === "active" ? "진행 중" : `끝남: ${endReasonText(row.end_reason)}`),
  }));
}

/** Why a new loop of this branch cannot be created now (null = it can): one unended loop per branch and run. */
export function loopCreateBlockedReason(rows: readonly Pick<JevLoopListRow, "branch" | "status">[],
                                        branch: JevLoopBranch): string | null {
  return rows.some(row => row.branch === branch && row.status === "active") ? createReasonText("loop_active") : null;
}

/** One loop is opened and driven at a time: another loop opens only when no request of the area is in flight. */
export function loopSwitchBlockedReason(busy: boolean): string | null { return busy ? LOOP_SWITCH_BUSY_REASON : null; }

// ---- pool guard (the M24 candidate guard of jev.ts: one set, stored order, at most 20, ligand only passing) ----

/** "선택 n/20 · 최소 2". */
export function loopPoolCountText(selection: JevSelection | null): string {
  return `선택 ${selection?.items.length ?? 0}/${LOOP_MAX_POOL} · 최소 ${LOOP_MIN_POOL}`;
}

/**
 * The create request's `pool` (source, candidates in the set's stored order, the applied filter for a ligand pool or
 * null), or every reason it is closed: no set, another branch's set, fewer than 2 or more than 20 candidates, a filter
 * on a protein pool, chosen ligand candidates the current filter refuses (`conflicts`, from `jevFilterConflicts`).
 */
export function loopPoolArgs(branch: JevLoopBranch, selection: JevSelection | null, filter: LigandFilterSpec | null,
                             conflicts: readonly string[] = []): ArgsCheck<JevLoopPoolArgs> {
  if (selection === null) return { ok: false, errors: ["후보 집합을 먼저 고르세요."] };
  const errors: string[] = [];
  if (selection.kind !== LOOP_KIND_FOR_BRANCH[branch]) errors.push("이 갈래의 후보 집합이 아닙니다 (pool_invalid).");
  const count = selection.items.length;
  if (count < LOOP_MIN_POOL) errors.push(`풀에는 후보를 ${LOOP_MIN_POOL}개 이상 고르세요 (pool_invalid).`);
  if (count > LOOP_MAX_POOL) errors.push(`풀에는 후보를 ${LOOP_MAX_POOL}개까지 고를 수 있습니다 (pool_invalid).`);
  const active = activeJevFilter(filter);
  if (branch === "protein" && active !== null) errors.push("변이 후보 풀에는 필터를 줄 수 없습니다 (pool_invalid).");
  if (branch === "ligand" && conflicts.length)
    errors.push(`적용한 필터를 통과하지 못한 후보가 풀에 있습니다: ${conflicts.join(", ")} (pool_invalid).`);
  if (errors.length) return { ok: false, errors };
  return { ok: true, args: { source: selection.source, candidates: jevSelectedCandidates(selection),
    filter: branch === "ligand" ? active : null } };
}

// ---- loop settings (goal, loop seed, iteration cap) ----

export interface LoopSettingsForm { goal: JevLoopGoal | null; loopSeed: string; iterationCap: string }

/** No goal chosen, the loop seed empty (required), the iteration cap at its screen default. */
export function initialLoopSettings(): LoopSettingsForm {
  return { goal: null, loopSeed: "", iterationCap: String(ITERATION_CAP_DEFAULT) };
}

export type LoopSettingsField = "goal" | "loop_seed" | "iteration_cap";
export type LoopSettingsCheck =
  | { ok: true; goal: JevLoopGoal; loopSeed: number; iterationCap: number; fields: Record<LoopSettingsField, null> }
  | { ok: false; fields: Record<LoopSettingsField, string | null> };

const INT_RE = /^(?:0|[1-9][0-9]*)$/;

function intIn(text: string, low: number, high: number): number | null {
  const trimmed = text.trim();
  if (!INT_RE.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isSafeInteger(value) && value >= low && value <= high ? value : null;
}

/** Per-field reasons with the server's admission names (goal_invalid, seed_invalid, iteration_cap_invalid). */
export function checkLoopSettings(form: LoopSettingsForm): LoopSettingsCheck {
  const goal = form.goal !== null && (LOOP_GOALS as readonly string[]).includes(form.goal) ? form.goal : null;
  const seed = intIn(form.loopSeed, LOOP_SEED_MIN, LOOP_SEED_MAX);
  const cap = intIn(form.iterationCap, ITERATION_CAP_MIN, ITERATION_CAP_MAX);
  const fields: Record<LoopSettingsField, string | null> = {
    goal: goal === null ? "목표를 고르세요: 탐색형 또는 활용형(자동으로 고르지 않음) (goal_invalid)." : null,
    loop_seed: seed === null ? `루프 seed: ${LOOP_SEED_MIN}–${LOOP_SEED_MAX} 사이의 정수를 입력하세요(필수, 기본값 없음) ` +
      "(seed_invalid)." : null,
    iteration_cap: cap === null ? `반복 상한: ${ITERATION_CAP_MIN}–${ITERATION_CAP_MAX} 사이의 정수를 입력하세요(기본 ` +
      `${ITERATION_CAP_DEFAULT}) (iteration_cap_invalid).` : null,
  };
  if (goal === null || seed === null || cap === null) return { ok: false, fields };
  return { ok: true, goal, loopSeed: seed, iterationCap: cap, fields: { goal: null, loop_seed: null, iteration_cap: null } };
}

// ---- computation setup (M22 / M18 rules for ligand, M21 / M18 rules for protein; free docking only) ----

/** Shape-only stand-in candidate id for the shared M18 check (= backend `PLACEHOLDER_CANDIDATE`; never sent). */
const POOL_STAND_IN = "jev_loop_pool";

/** The M18 docking form; the ligand is the pool's candidate set and the docking is free. */
export function initialLigandLoopSetupForm(): DockingForm {
  return { ...initialDockingForm(), ligandSource: "candidate", mode: "free" };
}

/** The M18 edit rules (`patchDockingForm`); the ligand stays the candidate source and the mode stays free. */
export function patchLigandLoopSetupForm(form: DockingForm, patch: Partial<DockingForm>): DockingForm {
  const next = patchDockingForm(form, { ...patch, ligandSource: "candidate", mode: "free" });
  return { ...next, ligandSource: "candidate", mode: "free", candidateId: null };
}

/**
 * The ligand `setup` exactly as the server admits it (the M22 shared fields: receptor, model, connectivity, instance,
 * box, free values and the three acknowledgements, checked by `dockingArgs` with the pool standing in for the
 * candidate; no `ligand` or `mode` key) plus the candidate set's parent SDF. `source` is the pool's candidate set.
 */
export function ligandLoopSetup(form: DockingForm, source: string | null): ArgsCheck<JevLoopLigandSetup> {
  const shared = dockingArgs({ ...form, ligandSource: "candidate", mode: "free", sdfHandle: null,
    candidateSetHandle: source, candidateId: POOL_STAND_IN });
  if (!shared.ok) return shared;
  const { ligand, mode: _mode, ...rest } = shared.args;
  if (ligand.source !== "candidate") return { ok: false, errors: ["리간드 출처가 후보 집합이 아닙니다."] };
  return { ok: true, args: { ...rest, parent_sdf_handle: ligand.parent_sdf_handle } };
}

/** The M21 `PairInputs` fields (3D SDF ligand, box, free values, acknowledgements), the two literals and the cutoff. */
export interface ProteinLoopSetupForm extends PairDockingForm { selectionConfirmed: boolean; hydrogenConfirmed: boolean;
  cutoff: string }

/** Nothing chosen or confirmed; the cutoff at its default 4.0 Å. */
export function initialProteinLoopSetupForm(): ProteinLoopSetupForm {
  return { ...initialPairDockingForm(), ligandSource: "sdf", mode: "free", selectionConfirmed: false,
    hydrogenConfirmed: false, cutoff: CONTACT_CUTOFF_DEFAULT_A.toFixed(1) };
}

/** The M21 edit rules (`patchPairDockingForm`: no instance-range box); the ligand stays the 3D SDF, docking free. */
export function patchProteinLoopSetupForm(form: ProteinLoopSetupForm, patch: Partial<ProteinLoopSetupForm>):
  ProteinLoopSetupForm {
  const next = patchPairDockingForm(form, { ...patch, ligandSource: "sdf", mode: "free" });
  return { ...next, ligandSource: "sdf", mode: "free",
    selectionConfirmed: patch.selectionConfirmed ?? form.selectionConfirmed,
    hydrogenConfirmed: patch.hydrogenConfirmed ?? form.hydrogenConfirmed, cutoff: patch.cutoff ?? form.cutoff };
}

/**
 * The protein `setup` exactly as the server admits it: the 3D SDF ligand, the M18 box (ligand range or manual) and
 * free values and acknowledgements (`dockingConditionArgs`), `protein_only`, `rebuild_pH7` and the contact cutoff
 * (2.5–6.0 Å). The docking seed is also the modelling seed (spec 3.1).
 */
export function proteinLoopSetup(form: ProteinLoopSetupForm): ArgsCheck<JevLoopProteinSetup> {
  const errors: string[] = [];
  const condition = dockingConditionArgs({ ...form, ligandSource: "sdf", mode: "free" },
    form.boxSource === null ? null : pairBoxSourceDisabledReason(form.boxSource));
  if (!condition.ok) errors.push(...condition.errors);
  if (!form.selectionConfirmed || !form.hydrogenConfirmed) errors.push(CONFIRMATION_ERROR);
  const cutoff = cutoffValue(form.cutoff);
  if (cutoff === null) errors.push(`접촉 cutoff: ${CONTACT_CUTOFF_RANGE_A[0].toFixed(1)}–` +
    `${CONTACT_CUTOFF_RANGE_A[1].toFixed(1)} Å 사이의 숫자를 입력하세요(양끝 포함) (argument_invalid).`);
  if (errors.length || !condition.ok || cutoff === null) return { ok: false, errors };
  const { ligand, box: given, parameters, acknowledgement } = condition.args;
  const box: JevLoopProteinSetup["box"] | null = given.source === "manual" ? given
    : given.source === "ligand_range" ? { source: "ligand_range", margin_A: given.margin_A } : null;
  if (ligand.source !== "sdf" || box === null) return { ok: false, errors: [`${PAIR_INSTANCE_RANGE_REASON} (box_invalid)`] };
  return { ok: true, args: { ligand: { source: "sdf", sdf_handle: ligand.sdf_handle }, box,
    parameters: { seed: parameters.seed, exhaustiveness: parameters.exhaustiveness, num_modes: parameters.num_modes,
      energy_range: parameters.energy_range },
    selection_policy: SELECTION_POLICY, hydrogen_policy: HYDROGEN_POLICY, acknowledgement, contact_cutoff_A: cutoff } };
}

// ---- the create request and its refusals ----

/** Where a reason is shown: one area per input of the create form, `general` for the rest. */
export type LoopCreateField = "general" | "pool" | "goal" | "loop_seed" | "iteration_cap" | "setup";
export const LOOP_CREATE_FIELDS: readonly LoopCreateField[] = ["general", "pool", "goal", "loop_seed", "iteration_cap",
  "setup"];
/** The area of each server admission reason (spec 3.1) and of `loop_id_conflict`. */
export const CREATE_REASON_FIELD: Record<string, LoopCreateField> = {
  unknown_field: "general", loop_id_invalid: "general", dry_run: "general", branch_invalid: "general",
  capability_unavailable: "general", loop_active: "general", pool_invalid: "pool", goal_invalid: "goal",
  seed_invalid: "loop_seed", iteration_cap_invalid: "iteration_cap", setup_invalid: "setup",
  loop_id_conflict: "general",
};

export type LoopFieldErrors = Record<LoopCreateField, string[]>;
export type LoopCreateBody = Omit<JevLoopCreateRequest, "loop_id">;
export type LoopCreateCheck = { ok: true; request: LoopCreateBody } | { ok: false; fields: LoopFieldErrors };

function emptyFieldErrors(): LoopFieldErrors {
  return { general: [], pool: [], goal: [], loop_seed: [], iteration_cap: [], setup: [] };
}

/** The create request without its `loop_id`, or every reason it is closed, per field (nothing is sent then). */
export function loopCreateRequest(input: { branch: JevLoopBranch; pool: ArgsCheck<JevLoopPoolArgs>;
  settings: LoopSettingsForm; setup: ArgsCheck<JevLoopLigandSetup | JevLoopProteinSetup> }): LoopCreateCheck {
  const fields = emptyFieldErrors();
  if (!input.pool.ok) fields.pool.push(...input.pool.errors);
  const settings = checkLoopSettings(input.settings);
  for (const key of ["goal", "loop_seed", "iteration_cap"] as const) {
    const text = settings.fields[key];
    if (text !== null) fields[key].push(text);
  }
  if (!input.setup.ok) fields.setup.push(...input.setup.errors);
  if (!input.pool.ok || !settings.ok || !input.setup.ok) return { ok: false, fields };
  return { ok: true, request: { branch: input.branch, pool: input.pool.args, goal: settings.goal,
    loop_seed: settings.loopSeed, iteration_cap: settings.iterationCap, setup: input.setup.args } };
}

/** One create attempt: the body pressed and the `loop_id` every retry of that body reuses. */
export interface LoopCreateAttempt { loopId: string; key: string }

/** The attempt for this body: the current one when the body is the same, else a new v4 `loop_id`. */
export function loopCreateAttempt(current: LoopCreateAttempt | null, request: LoopCreateBody,
                                  make: () => string = newLoopId): LoopCreateAttempt {
  const key = JSON.stringify(request);
  if (current !== null && current.key === key) return current;
  return { loopId: make(), key };
}

/** A record or a `loop_id_conflict` ends the attempt; any other answer keeps the id (a retry is the same loop). */
export function loopCreateAttemptAfter(current: LoopCreateAttempt | null,
                                       outcome: { record: true } | { record: false; code: string | null }):
  LoopCreateAttempt | null {
  if (outcome.record || outcome.code === LOOP_ID_CONFLICT) return null;
  return current;
}

export function loopCreateBody(attempt: LoopCreateAttempt, request: LoopCreateBody): JevLoopCreateRequest {
  return { loop_id: attempt.loopId, ...request };
}

/** A refused create as the field it belongs to and its text (`detail.reason_code`, `setup_reason`, `candidates`). */
export function loopCreateRefusal(error: unknown, branch: JevLoopBranch):
  { field: LoopCreateField; reasonCode: string | null; text: string } {
  const info = loopErrorInfo(error, branch);
  const field = info.reasonCode !== null ? own(CREATE_REASON_FIELD as Record<string, string>, info.reasonCode) : null;
  return { field: (field ?? "general") as LoopCreateField, reasonCode: info.reasonCode, text: info.text };
}

/** A `jev_loop@1` answer, for exactly this loop when `loopId` is given. */
export function loopRecordMatches(value: unknown, loopId: string | null = null): value is JevLoopV1 {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Partial<JevLoopV1>;
  return record.schema === LOOP_SCHEMA && typeof record.loop_id === "string" &&
    (loopId === null || record.loop_id === loopId) && typeof record.current === "object" && record.current !== null &&
    Array.isArray(record.candidates) && Array.isArray(record.iterations);
}

// ---- record views: candidates ----

/** "후보 c_…" or "후보 번호 12" (local references, never sent). */
export function loopRefText(ref: JevLoopRef): string {
  return typeof ref === "number" ? `후보 번호 ${ref}` : `후보 ${ref}`;
}

function displayOf(record: Pick<JevLoopV1, "pool">, ref: JevLoopRef | null): JevLocalDisplay | null {
  if (ref === null) return null;
  return record.pool.candidates.find(item => item.ref === ref)?.display ?? null;
}

/** The pool notation of a candidate (ligand SMILES, mutation residue · from→to); "—" when it is not in the pool. */
export function loopDisplayText(record: Pick<JevLoopV1, "pool">, ref: JevLoopRef | null): string {
  const display = displayOf(record, ref);
  return display === null ? NULL_TEXT : localDisplayText(display);
}

function iterationOf(record: Pick<JevLoopV1, "iterations">, index: number | null): JevLoopIteration | null {
  return index === null ? null : record.iterations.find(item => item.index === index) ?? null;
}

const NO_SCORE_REASON: Record<Exclude<JevLoopCandidateState, "scored">, string> = {
  pending: "계산하지 않음", null_result: "도킹 모드 0개(빈 결과)", failed: "작업 실패",
  not_run: `도킹하지 않음 (${LOOP_NOT_RUN_REASON})`, unavailable: "이 run에서 계산할 수 없음",
};

export interface LoopCandidateRow {
  position: number; ref: JevLoopRef; refText: string; displayText: string; state: JevLoopCandidateState;
  stateText: string; evaluation: JevLoopEvaluation | null; evaluationText: string;
  /** The stored first-mode qvina score (kcal/mol) of a `scored` candidate only; never 0 for a candidate without one. */
  score: number | null; scoreText: string; noScoreReason: string | null; iteration: number | null;
  iterationText: string; decidedBy: JevLoopDecidedBy | null; decidedByText: string;
  /** The M18 `docking_result@1` of a candidate this loop computed (for "상세 열기"); null otherwise. */
  resultHandle: string | null; selectable: boolean;
}

/** The record's candidates in pool order, each as stored (state, evaluation, score, iteration) plus who chose it. */
export function loopCandidateRows(record: JevLoopV1): LoopCandidateRow[] {
  const choosing = record.status === "active" && (record.current.action === "select" ||
    record.current.action === "compute");
  return record.candidates.map((row, position) => {
    const it = iterationOf(record, row.iteration);
    const steps = it?.steps.filter(step => step.candidate_ref === row.ref) ?? [];
    const scored = row.state === "scored" && row.score_kcal_mol !== null;
    let reason: string | null = null;
    if (!scored) {
      reason = own(NO_SCORE_REASON as Record<string, string>, row.state) ?? UNKNOWN_CODE_TEXT;
      const failed = steps.find(step => step.state === "failed");
      const failedText = failed ? stepReasonText(failed.step, failed.reason_code) : null;
      if (row.state === "failed" && failedText) reason = `${reason}: ${failedText}`;
    }
    const docked = steps.find(step => (step.step === "ligand_dock" || step.step === "dock") && step.result_handle);
    const decidedBy = it?.decided_by ?? null;
    return {
      position, ref: row.ref, refText: loopRefText(row.ref), displayText: localDisplayText(row.display),
      state: row.state, stateText: candidateStateText(row.state), evaluation: row.evaluation,
      evaluationText: evaluationText(row.evaluation), score: scored ? row.score_kcal_mol : null,
      scoreText: scored ? scoreText(row.score_kcal_mol as number) : `${NULL_TEXT} (${reason})`,
      noScoreReason: reason, iteration: row.iteration,
      iterationText: row.iteration === null ? NULL_TEXT : `바퀴 ${row.iteration}`, decidedBy,
      decidedByText: decidedByText(decidedBy), resultHandle: row.evaluation === "computed" && docked
        ? docked.result_handle : null,
      selectable: choosing && row.state === "pending",
    };
  });
}

/** The candidates a person can name now ("직접 지정"): pending pool candidates while a first step can be approved. */
export function loopSelectableCandidates(record: JevLoopV1): LoopCandidateRow[] {
  return loopCandidateRows(record).filter(row => row.selectable);
}

export type LoopSortKey = "pool" | "candidate" | "score" | "iteration";
export type LoopSort = { key: LoopSortKey; direction: "asc" | "desc" } | null;

function compareRefs(a: JevLoopRef, b: JevLoopRef): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  const left = String(a), right = String(b);
  return left < right ? -1 : left > right ? 1 : 0;
}

/**
 * Display order only: rows with a score first, ordered by the column (ties in pool order), then every row without a
 * score in pool order, whatever the column and direction (never treated as 0). No rank is made or shown.
 */
export function sortLoopCandidates<T extends Pick<LoopCandidateRow, "position" | "ref" | "score" | "iteration">>(
  rows: readonly T[], sort: LoopSort): T[] {
  const byPool = [...rows].sort((a, b) => a.position - b.position);
  const head = byPool.filter(row => row.score !== null), tail = byPool.filter(row => row.score === null);
  if (sort === null || (sort.key === "pool" && sort.direction === "asc")) return [...head, ...tail];
  if (sort.key === "pool") return [...head.reverse(), ...tail];
  const sign = sort.direction === "asc" ? 1 : -1;
  const compare = (a: T, b: T): number => {
    if (sort.key === "candidate") return sign * compareRefs(a.ref, b.ref);
    if (sort.key === "score") return sign * ((a.score as number) - (b.score as number));
    if (a.iteration === null || b.iteration === null)   // a stored result adopted without an iteration stays after
      return a.iteration === b.iteration ? 0 : a.iteration === null ? 1 : -1;
    return sign * (a.iteration - b.iteration);
  };
  return [...head.sort((a, b) => compare(a, b) || a.position - b.position), ...tail];
}

/** Header click: a new column starts ascending; the same column toggles its direction. */
export function nextLoopSort(current: LoopSort, key: LoopSortKey): LoopSort {
  if (current && current.key === key) return { key, direction: current.direction === "asc" ? "desc" : "asc" };
  return { key, direction: "asc" };
}

export function loopAriaSort(sort: LoopSort, key: LoopSortKey): "ascending" | "descending" | "none" {
  return sort && sort.key === key ? sort.direction === "asc" ? "ascending" : "descending" : "none";
}

// ---- record views: iterations ----

export interface LoopIterationStepView { stepText: string; stateText: string; reasonText: string | null;
  jobId: string | null; resultHandle: string | null; candidateText: string }
export interface LoopIterationSendView { sendId: string; statusText: string; ordinalText: string; lateText: string | null;
  proposalHandle: string | null }
export interface LoopIterationRow {
  index: number; phaseText: string; stateText: string; decidedByText: string; candidateText: string;
  /** "n/m": the chosen alias' place among the not-yet-computed candidates of that send (a recorded value only). */
  listPositionText: string; scoreText: string; steps: LoopIterationStepView[]; sends: LoopIterationSendView[];
}

/** One row per listed iteration, in number order; each send on its own (never merged or counted across sends). */
export function loopIterationRows(record: JevLoopV1): LoopIterationRow[] {
  return [...record.iterations].sort((a, b) => a.index - b.index).map(it => ({
    index: it.index, phaseText: phaseText(it.phase), stateText: iterationStateText(it.state),
    decidedByText: decidedByText(it.decided_by), candidateText: loopDisplayText(record, it.candidate_ref),
    listPositionText: it.list_position !== null && it.list_size !== null ? `${it.list_position}/${it.list_size}`
      : NULL_TEXT,
    scoreText: it.state === "scored" && it.score_kcal_mol !== null ? scoreText(it.score_kcal_mol)
      : `${NULL_TEXT} (${iterationStateText(it.state)})`,
    steps: it.steps.map(step => ({ stepText: stepText(step.step), stateText: stepStateText(step.state),
      reasonText: stepReasonText(step.step, step.reason_code), jobId: step.job_id, resultHandle: step.result_handle,
      candidateText: loopDisplayText(record, step.candidate_ref) })),
    sends: it.sends.map(send => ({ sendId: send.send_id, statusText: sendStatusText(send.status),
      ordinalText: `전송 순번 ${send.send_ordinal}`,
      lateText: send.late ? "늦은 응답(이 바퀴의 선택이 아님)" : null, proposalHandle: send.proposal_handle })),
  }));
}

/** The record's current iteration row (null when there is none: not listed yet, exhausted or ended). */
export function loopCurrentIteration(record: JevLoopV1): JevLoopIteration | null {
  return iterationOf(record, record.current.iteration);
}

/**
 * The iteration's JEV selection: its one send that is `completed`, not late and carries a `proposal_handle` (the
 * server leaves the handle null for a proposal that does not validate or belong to its send). Null when there is none
 * (or, against the spec, more than one).
 */
export function loopIterationSelection(iteration: JevLoopIteration | null): { sendId: string; proposalHandle: string } |
  null {
  const found = iteration?.sends.filter(send => send.status === "completed" && send.late === false &&
    send.proposal_handle !== null) ?? [];
  return found.length === 1 ? { sendId: found[0].send_id, proposalHandle: found[0].proposal_handle as string } : null;
}

// ---- record views: amounts, phase actions and buttons ----

export interface LoopAxisRow { axis: JevLoopAxis; label: string; needText: string; remainingText: string; blocked: boolean }

/** One row per axis with the server's need and remaining amounts; `blocked` = the server named the axis. */
export function loopAxisRows(needs: JevLoopAmounts | null, remaining: JevLoopAmounts | null,
                             blocked: readonly string[]): LoopAxisRow[] {
  return LOOP_AXES.map(axis => ({ axis, label: axisText(axis),
    needText: needs === null ? NULL_TEXT : amountText(axis, needs[axis]),
    remainingText: remaining === null ? NULL_TEXT : amountText(axis, remaining[axis]), blocked: blocked.includes(axis) }));
}

/** "비싼 계산 단위 (expensive_units) 모자람: 필요 1단위 · 남은 0단위" (server values). */
export function loopAxisReason(axis: string, needs: JevLoopAmounts | null, remaining: JevLoopAmounts | null): string {
  if (!(LOOP_AXES as readonly string[]).includes(axis)) return UNKNOWN_CODE_TEXT;
  const key = axis as JevLoopAxis;
  return `${axisText(key)} 모자람: 필요 ${needs === null ? NULL_TEXT : amountText(key, needs[key])} · 남은 ` +
    `${remaining === null ? NULL_TEXT : amountText(key, remaining[key])}`;
}

export type LoopButton = "build" | "computeProposal" | "designate" | "startJob" | "cancelJob" | "dock" | "abandon" |
  "end";
export const LOOP_BUTTONS: readonly LoopButton[] = ["build", "computeProposal", "designate", "startJob", "cancelJob",
  "dock", "abandon", "end"];
export interface LoopButtonState { enabled: boolean; reasons: string[] }

export interface LoopActionView {
  action: JevLoopAction; actionText: string; iteration: number | null; iterationText: string;
  phaseText: string | null; stepText: string | null; statusText: string; progressText: string;
  exhaustedText: string | null; computeBlockedTexts: string[]; sendBlockedTexts: string[]; axisRows: LoopAxisRow[];
  jobText: string | null; approvalGuide: string | null; cancelNote: string | null;
  selection: { sendId: string; proposalHandle: string } | null; buttons: Record<LoopButton, LoopButtonState>;
}

const LIVE_JOB = ["queued", "claimed"];

/**
 * What the current phase lets the person do and why each button is closed, from the record alone (spec 3.2 `current`,
 * 6.1, 6.3, 7, 8.1): the server's action, needs, remaining amounts, blocked axes, `can_end` and job. `proposalRef` is
 * the chosen candidate of the iteration's JEV selection read from its proposal object (undefined = not read yet, null
 * = unreadable); `busy` = a request of the area is in flight. Nothing is computed: the server decides every amount.
 */
export function loopActionView(record: JevLoopV1, input: { busy: boolean; proposalRef?: JevLoopRef | null }):
  LoopActionView {
  const cur = record.current, ended = record.status === "ended";
  const computeBlocked = cur.blocked_axes.map(axis => loopAxisReason(axis, cur.needs, cur.remaining));
  const sendBlocked = cur.send_blocked_axes.map(axis => loopAxisReason(axis, cur.needs, cur.remaining));
  const it = loopCurrentIteration(record);
  const selection = cur.action === "compute" ? loopIterationSelection(it) : null;
  const job = cur.job;
  const live = cur.action === "wait_job" && job !== null && LIVE_JOB.includes(job.status);
  const notNow = (wanted: string): string => `지금은 ${wanted} 차례가 아님: ${actionText(cur.action)}`;
  const finish = (reasons: string[]): LoopButtonState => {
    const all = input.busy ? [...reasons, BUSY_REASON] : reasons;
    return { enabled: all.length === 0, reasons: all };
  };
  const endedReason = ended ? [endRefusalText("loop_ended")] : null;
  const rows = loopCandidateRows(record);

  let build: string[];
  if (endedReason) build = endedReason;
  else if (cur.action === "compute") build = [loopProjectionReasonText("selection_done")];
  else if (cur.action !== "select") build = [notNow("보낼")];
  else build = cur.needs.sends >= 1 ? [] : [loopProjectionReasonText("too_few_candidates")];

  let computeProposal: string[];
  if (endedReason) computeProposal = endedReason;
  else if (cur.action !== "compute") computeProposal = [notNow("JEV 선택으로 계산할")];
  else if (selection === null) computeProposal = [computeReasonText("proposal_invalid")];
  else if (input.proposalRef === undefined) computeProposal = ["JEV 판정을 읽는 중입니다."];
  else if (input.proposalRef === null) computeProposal = [CHOICE_MISMATCH_TEXT];
  else {
    const chosen = rows.find(row => row.ref === input.proposalRef);
    computeProposal = !chosen ? [computeReasonText("candidate_invalid")]
      : chosen.state === "unavailable" ? [computeReasonText("candidate_unavailable")]
        : chosen.state !== "pending" ? [computeReasonText("candidate_computed")] : [...computeBlocked];
  }

  let designate: string[];
  if (endedReason) designate = endedReason;
  else if (cur.action !== "select" && cur.action !== "compute") designate = [notNow("직접 지정할")];
  else designate = rows.some(row => row.selectable) ? [...computeBlocked]
    : ["직접 지정할 수 있는 계산하지 않은 후보가 없음"];

  const jobReasons = endedReason ?? (live ? [] : [notNow("대기 중인 작업을 다룰")]);
  const dock = endedReason ?? (cur.action === "dock" ? [...computeBlocked] : [notNow("도킹할")]);
  const abandon = endedReason ?? (cur.action === "dock" ? [] : [notNow("도킹을 포기할")]);
  let end: string[];
  if (endedReason) end = endedReason;
  else if (cur.can_end) end = [];
  else if (cur.action === "wait_job") end = [endRefusalText("job_running")];
  else if (cur.action === "dock") end = [endRefusalText("docking_pending")];
  else end = [endRefusalText("send_in_progress")];

  return {
    action: cur.action, actionText: actionText(cur.action), iteration: cur.iteration,
    iterationText: cur.iteration === null ? NULL_TEXT : `바퀴 ${cur.iteration}`,
    phaseText: cur.phase === null ? null : phaseText(cur.phase), stepText: cur.step === null ? null : stepText(cur.step),
    statusText: ended ? `끝남 (ended) · ${endReasonText(record.end_reason)}` : "진행 중 (active)",
    progressText: `시작한 바퀴 ${record.counts.started} · 끝난 바퀴 ${record.counts.done} · 유효 반복 상한 ` +
      `${record.effective_cap}(반복 상한 ${record.iteration_cap}, 풀 ${record.pool.candidates.length}개)`,
    exhaustedText: record.exhausted_reason === null ? null
      : `${exhaustedReasonText(record.exhausted_reason)}: 루프 끝내기를 누르면 요약을 만듭니다.`,
    computeBlockedTexts: computeBlocked, sendBlockedTexts: sendBlocked,
    axisRows: loopAxisRows(cur.needs, cur.remaining, [...cur.blocked_axes, ...cur.send_blocked_axes]),
    jobText: job === null ? null : `작업 ${job.job_id} · ${stepText(job.step)} · ${loopJobStatusText(job.status)}`,
    approvalGuide: job?.start_blocked === LOOP_START_BLOCKED ? FIRST_APPROVAL_GUIDE : null,
    cancelNote: live ? CANCEL_BEFORE_START_NOTE : null, selection,
    buttons: { build: finish(build), computeProposal: finish(computeProposal), designate: finish(designate),
      startJob: finish(jobReasons), cancelJob: finish([...jobReasons]), dock: finish(dock), abandon: finish(abandon),
      end: finish(end) },
  };
}

/** The status of a loop: active, or ended with its reason and the summary to report on (null after a run cancel). */
export function loopStatusView(record: JevLoopV1): { ended: boolean; statusText: string; resultHandle: string | null;
  reportBlockedReason: string | null } {
  const ended = record.status === "ended";
  return { ended, resultHandle: ended ? record.result_handle : null,
    statusText: ended ? `끝남 (ended) · ${endReasonText(record.end_reason)}` : "진행 중 (active)",
    reportBlockedReason: !ended ? "루프를 끝낸 뒤 보고서를 만들 수 있습니다."
      : record.result_handle === null ? `요약이 없어 보고서를 만들 수 없습니다: ${endReasonText(record.end_reason)}` : null };
}

// ---- request bodies of the person's presses ----

/** `build_jev_loop_projection` arguments of the current iteration (null when the loop is not awaiting a selection). */
export function loopProjectionArgs(record: JevLoopV1): JevLoopProjectionArgs | null {
  return record.status === "active" && record.current.action === "select" && record.current.iteration !== null
    ? { loop_id: record.loop_id, iteration: record.current.iteration } : null;
}

/** The first step with the iteration's JEV selection (`decided_by: "jev"`). */
export function loopProposalComputeRequest(record: JevLoopV1, proposalHandle: string): JevLoopComputeRequest | null {
  return record.current.iteration === null ? null : { iteration: record.current.iteration, proposal: proposalHandle };
}

/** The first step with a candidate the person names (`decided_by: "human"`; ligand id or mutation index). */
export function loopCandidateComputeRequest(record: JevLoopV1, ref: JevLoopRef): JevLoopComputeRequest | null {
  return record.current.iteration === null ? null : { iteration: record.current.iteration, candidate: ref };
}

/** The docking step of a modelled candidate (protein; neither proposal nor candidate). */
export function loopDockRequest(record: JevLoopV1): JevLoopComputeRequest | null {
  return record.current.iteration === null ? null : { iteration: record.current.iteration };
}

export function loopAbandonRequest(record: JevLoopV1): JevLoopAbandonRequest | null {
  return record.current.iteration === null ? null : { iteration: record.current.iteration };
}

/**
 * The same press again for the step whose job waits (first expensive-call approval, a queued job): the arguments of
 * that step's latest approval, so the server takes its idempotent path (no new event or job, only the start).
 */
export function loopResumeRequest(record: JevLoopV1): JevLoopComputeRequest | null {
  const cur = record.current, it = loopCurrentIteration(record);
  if (cur.action !== "wait_job" || cur.job === null || cur.iteration === null || it === null) return null;
  if (cur.job.step === "dock") return { iteration: cur.iteration };
  if (it.decided_by === "jev" && it.proposal_handle !== null)
    return { iteration: cur.iteration, proposal: it.proposal_handle };
  if (it.decided_by === "human" && it.candidate_ref !== null)
    return { iteration: cur.iteration, candidate: it.candidate_ref };
  return null;
}

// ---- the projection command ----

export type LoopProjectionOutcome = { ok: true; handle: string; summary: JevLoopProjectionSummary } |
  { ok: false; text: string; reasonCode: string | null };

/** The command envelope of `build_jev_loop_projection`: a stored `jev_loop_projection@1` handle, or the refusal. */
export function jevLoopProjectionOutcome(result: CommandResult, branch: JevLoopBranch | null = null):
  LoopProjectionOutcome {
  if (!result.ok) {
    if ("message" in result) {
      const info = loopErrorInfo({ code: result.error, detail: result.detail }, branch);
      return { ok: false, text: info.text, reasonCode: info.reasonCode };
    }
    return { ok: false, text: REQUEST_FAILED_TEXT, reasonCode: null };
  }
  if (result.handle.kind !== LOOP_PROJECTION_KIND || result.handle.schema !== LOOP_PROJECTION_SCHEMA)
    return { ok: false, text: NOT_A_LOOP_PROJECTION_TEXT, reasonCode: null };
  return { ok: true, handle: result.handle.handle,
    summary: result.handle.summary as unknown as JevLoopProjectionSummary };
}

// ---- preview and approval (the M24 preview, approval and send_id rules of jev.ts) ----

/** A `jev_preview@1` of exactly this loop projection and loop (with its `loop` block and `loop_blocks`). */
export function jevLoopPreviewMatches(value: unknown, projectionHandle: string, loopId: string):
  value is JevLoopPreviewV1 {
  if (!jevPreviewMatches(value, projectionHandle)) return false;
  const preview = value as unknown as Partial<JevLoopPreviewV1>;
  return typeof preview.loop === "object" && preview.loop !== null && preview.loop.loop_id === loopId &&
    Array.isArray(preview.loop_blocks) && Array.isArray(preview.selection) &&
    (LOOP_QUESTION_IDS as readonly string[]).includes(preview.question?.id ?? "");
}

export interface LoopAliasRow { alias: string; refText: string; displayText: string; stateText: string;
  choosableText: string; sentText: string }
export interface LoopPreviewView {
  projectionHandle: string; kindText: string; questionId: string;
  /** The fixed question wording and the exact body, verbatim from the server (never parsed or re-serialized). */
  instructions: string; body: string; bodyBytesText: string; bodySha256: string;
  aliasNote: string; aliasRows: LoopAliasRow[]; orderText: string; reservationText: string; capText: string;
  budgetRemainingText: string; axisRows: LoopAxisRow[]; blocked: JevPreviewBlocker[];
  loopBlocks: { code: string; text: string }[]; previousSendsText: string; confirmText: string;
}

/** The loop preview as shown: the M24 parts plus the alias table (not sent), the shuffle record and the loop blocks. */
export function jevLoopPreviewView(preview: JevLoopPreviewV1, record: JevLoopV1,
                                   laterStatus: Pick<JevStatusV1, "send_in_progress"> | null = null): LoopPreviewView {
  const block = preview.loop;
  return {
    projectionHandle: preview.projection_handle, kindText: KIND_LABEL[preview.kind] ?? UNKNOWN_CODE_TEXT,
    questionId: preview.question.id, instructions: preview.question.instructions, body: preview.body,
    bodyBytesText: `${preview.body_bytes} 바이트`, bodySha256: preview.body_sha256, aliasNote: ALIAS_TABLE_NOTE,
    aliasRows: preview.selection.map(item => ({ alias: item.alias, refText: loopRefText(item.ref),
      displayText: loopDisplayText(record, item.ref), stateText: candidateStateText(item.state),
      choosableText: item.state === "pending" ? "JEV가 고를 수 있음" : "계산됨(JEV가 고를 수 없음)",
      sentText: NOT_SENT_TEXT })),
    orderText: `후보 순서·별칭: ${ORDER_ALGORITHM}로 섞음 · 루프 seed ${record.loop_seed} · 바퀴 ${block.iteration} · ` +
      `전송 순번 ${block.send_ordinal}`,
    reservationText: `예약: 외부 토큰 ${preview.reservation.external_tokens} · ${usdText(preview.reservation.usd)}`,
    capText: jevCapText(preview),
    budgetRemainingText: `남은 외부 토큰 ${preview.budget_remaining.external_tokens} · 남은 ` +
      usdText(preview.budget_remaining.usd),
    axisRows: loopAxisRows(block.needs, block.remaining, block.send_blocked_axes ?? []),
    blocked: jevPreviewBlockers(preview, laterStatus),
    loopBlocks: preview.loop_blocks.map(code => ({ code, text: loopSendReasonText(code) })),
    previousSendsText: `같은 투영으로 이전에 보낸 수: ${preview.previous_sends}회`, confirmText: CONFIRM_CHECK_TEXT,
  };
}

export interface LoopSendGuardInput {
  preview: JevLoopPreviewV1 | null; confirmed: boolean; sending: boolean;
  laterStatus?: Pick<JevStatusV1, "send_in_progress"> | null;
}

/** Every reason the send button is closed: M24 refusals, loop refusals, a send in flight, the unchecked confirmation. */
export function jevLoopSendBlockers(input: LoopSendGuardInput): string[] {
  if (input.preview === null) return ["먼저 보낼 내용을 만들고 미리보기를 읽으세요."];
  const reasons = jevPreviewBlockers(input.preview, input.laterStatus ?? null).map(item => item.text);
  reasons.push(...input.preview.loop_blocks.map(code => loopSendReasonText(code)));
  if (input.sending) reasons.push("전송 중입니다. 응답이 올 때까지 기다리세요(한 번에 한 전송).");
  if (!input.confirmed) reasons.push(`확인 체크를 켜세요: "${CONFIRM_CHECK_TEXT}".`);
  return reasons;
}

export function jevLoopCanSend(input: LoopSendGuardInput): boolean { return jevLoopSendBlockers(input).length === 0; }

// ---- the JEV proposal card (a proposal, shown as stored) ----

/** A send detail answer for exactly this send of this loop. */
export function jevLoopDetailMatches(detail: unknown, sendId: string, loopId: string): detail is JevLoopSendDetail {
  if (typeof detail !== "object" || detail === null) return false;
  const value = detail as Partial<JevLoopSendDetail>;
  return value.schema === "jev_send@1" && value.send_id === sendId && typeof value.loop === "object" &&
    value.loop !== null && value.loop.loop_id === loopId;
}

export interface LoopProbabilityRow { alias: string; refText: string; displayText: string; value: number | null;
  text: string }
/** Whether the card is the iteration's JEV selection, judged from a record that already shows the send completed. */
export type LoopChoiceRole = "selection" | "not_selection";
/**
 * Shown instead of the card while the loop record does not yet show the send completed (the send answer arrived before
 * a record read that knows it): no number and no judgment of whether it is the iteration's selection.
 */
export const CHOICE_CONFIRMING_TEXT = "루프 기록이 이 전송의 완료를 아직 보이지 않습니다. 기록을 다시 읽어 이 바퀴의 선택인지 확인하는 " +
  "중입니다.";
export interface LoopChoiceCard {
  sendId: string; proposalHandle: string; label: string; iteration: number;
  /**
   * True only when the record shows this send completed and as the iteration's selection (its one completed, not-late
   * send with a proposal handle, this proposal); a late proposal is never one.
   */
  isSelection: boolean; role: LoopChoiceRole; roleText: string; chosenAlias: string; ref: JevLoopRef; refText: string; localDisplayText: string;
  listPositionLabel: string; listPositionText: string; confidenceLabel: string; confidence: number | null;
  confidenceText: string; probabilitiesReported: boolean; probabilityNote: string;
  probabilityRows: LoopProbabilityRow[]; probabilityText: string | null; reasonText: string; requestedModel: string;
  servedModel: string; usageRows: JevUsageRow[]; lateText: string | null; lateNote: string | null;
  /** The server's stored sentences (LJ1–LJ3, LJ4 | LJ5, LJ6 | LJ7, then J7 when late), verbatim. */
  limitations: readonly string[];
}

export type LoopChoiceView =
  | { state: "in_progress"; statusText: string }
  | { state: "rejected" | "failed"; statusText: string; reasonText: string }
  | { state: "confirming"; statusText: string; message: string }
  | { state: "completed"; statusText: string; card: LoopChoiceCard }
  | { state: "invalid"; statusText: string; message: string };

/** The record's row of one send with its iteration number (null when the record does not list the send). */
export function loopRecordSend(record: Pick<JevLoopV1, "iterations">, sendId: string):
  (JevLoopIterationSend & { iteration: number }) | null {
  for (const it of record.iterations) {
    const send = it.sends.find(item => item.send_id === sendId);
    if (send) return { ...send, iteration: it.index };
  }
  return null;
}

/**
 * Whether the record already shows this send ended (listed and no longer in progress; with `status`, ended with that
 * status). Until it does, the area keeps reading the record after the send answer (the answer can arrive before a
 * record read that knows it).
 */
export function loopRecordReflectsSend(record: Pick<JevLoopV1, "iterations">, sendId: string,
                                       status: string | null = null): boolean {
  const row = loopRecordSend(record, sendId);
  return row !== null && row.status !== "in_progress" && (status === null || row.status === status);
}

/**
 * The send the area keeps reading the record for after a send answer: an ended record (completed, rejected, failed)
 * until the record shows it; null for a record still in progress (a replayed send_id), which the usual polling rule
 * (a send in progress) covers, so the reads never wait for a status the record does not keep.
 */
export function loopAwaitedSend(record: { send_id: string; status: string }): { sendId: string; status: string } | null {
  return record.status === "in_progress" ? null : { sendId: record.send_id, status: record.status };
}

/**
 * One loop send's result: the proposal card when completed, the reason only when refused or failed. The chosen
 * candidate, its list position "n/m", the confidence and the probabilities are the stored values; probabilities are
 * listed in the sent order (the not-yet-computed aliases of the send), never sorted, ranked or compared. Whether the
 * proposal is the iteration's selection is judged only from a record that shows this send completed: before that the
 * view is `confirming` (no card, no number, no judgment).
 */
export function loopChoiceView(detail: JevLoopSendDetail, record: JevLoopV1): LoopChoiceView {
  const statusText = sendStatusText(detail.status);
  if (detail.status === "in_progress") return { state: "in_progress", statusText };
  if (detail.status === "rejected" || detail.status === "failed")   // the M24 closed send reasons and labels
    return { state: detail.status, statusText, reasonText: sendReasonText(detail.status, detail.reason_code) ?? "" };
  const choice = detail.choice;
  if (detail.status !== "completed" || choice === null || detail.choice_handle === null ||
      choice.schema !== LOOP_CHOICE_SCHEMA || choice.send.send_id !== detail.send_id ||
      choice.label !== JEV_CHOICE_LABEL || choice.scientific_result !== false || choice.loop.loop_id !== record.loop_id ||
      detail.loop === null || detail.loop.loop_id !== record.loop_id || detail.loop.iteration !== choice.loop.iteration)
    return { state: "invalid", statusText, message: CHOICE_MISMATCH_TEXT };
  const row = loopRecordSend(record, detail.send_id);
  if (row === null || row.iteration !== choice.loop.iteration || row.status !== "completed")
    return { state: "confirming", statusText, message: CHOICE_CONFIRMING_TEXT };
  const answer = choice.answer, late = choice.arrival.late;
  const ref: JevLoopRef = "candidate_id" in answer.local_ref ? answer.local_ref.candidate_id
    : answer.local_ref.candidate_index;
  const selection = loopIterationSelection(iterationOf(record, choice.loop.iteration));
  const isSelection = !late && !row.late && row.proposal_handle === detail.choice_handle &&
    selection?.sendId === detail.send_id && selection.proposalHandle === detail.choice_handle;
  const probabilities = answer.probabilities;
  return { state: "completed", statusText, card: {
    sendId: detail.send_id, proposalHandle: detail.choice_handle, label: JEV_CHOICE_LABEL,
    iteration: choice.loop.iteration, isSelection, role: isSelection ? "selection" : "not_selection",
    roleText: isSelection ? `바퀴 ${choice.loop.iteration}의 선택(계산은 사람이 승인해야 시작)`
      : `바퀴 ${choice.loop.iteration}의 선택이 아님`,
    chosenAlias: answer.choice_alias, ref, refText: loopRefText(ref),
    localDisplayText: localDisplayText(answer.local_display), listPositionLabel: LIST_POSITION_LABEL,
    listPositionText: `${answer.list_position}/${answer.list_size}`, confidenceLabel: JEV_CONFIDENCE_LABEL,
    confidence: answer.confidence, confidenceText: confidenceText(answer.confidence),
    probabilitiesReported: probabilities !== null, probabilityNote: PROBABILITY_NOTE,
    probabilityRows: probabilities === null ? [] : choice.selection.filter(item => item.state === "pending")
      .map(item => {
        const value = Object.prototype.hasOwnProperty.call(probabilities, item.alias) ? probabilities[item.alias] : null;
        return { alias: item.alias, refText: loopRefText(item.ref), displayText: loopDisplayText(record, item.ref), value,
          text: confidenceText(value) };
      }),
    probabilityText: probabilities === null ? NOT_REPORTED_TEXT : null, reasonText: CHOICE_REASON_TEXT,
    requestedModel: choice.requested_model, servedModel: choice.served_model, usageRows: usageRows(choice.usage),
    lateText: late ? lateReasonText(choice.arrival.late_reason) : null,
    lateNote: late ? `${LATE_CHOICE_NOTE}\n${JEV_STATEMENTS.J7}` : null, limitations: choice.limitations,
  } };
}

// ---- the knowledge tab's send history: a loop send is a read-only row pointing to its loop area ----

export interface LoopSendHistoryMark { text: string; guide: string; canOpen: false; canReport: false }

/** null for an M24 send (no `loop` key); a loop send's mark, read-only, with the M24 open and report buttons off. */
export function loopSendHistoryMark(record: { kind: JevKind; loop?: JevLoopSendLoopRef | null }):
  LoopSendHistoryMark | null {
  if (!("loop" in record) || record.loop === undefined) return null;
  const tab = record.kind === "mutation" ? "단백질 공학" : "리간드 설계·탐색";
  const where = record.loop === null ? NULL_TEXT
    : `바퀴 ${record.loop.iteration} · 전송 순번 ${record.loop.send_ordinal}`;
  return { text: `${LOOP_AREA_TITLE} · ${where}`, canOpen: false, canReport: false,
    guide: `이 전송은 JEV 루프 기록입니다. 결과와 계산은 ${tab} 탭의 JEV 루프 영역에서 봅니다.` };
}

// ---- reports ----

export function jevLoopReportMatches(artifact: Pick<JevLoopReportArtifact, "manifest">, resultHandle: string): boolean {
  return artifact.manifest.schema === "method_report_manifest@1" &&
    artifact.manifest.analysis_type === LOOP_REPORT_TYPE && artifact.manifest.result_handle === resultHandle;
}

// ---- record reads: one at a time, a request while one is in flight is kept and read once more ----

/** The record read in flight (its loop id) and whether another read was asked for meanwhile. */
export interface LoopReadQueue { inFlight: string | null; pending: boolean }

export function initialLoopReadQueue(): LoopReadQueue { return { inFlight: null, pending: false }; }

/**
 * A request to read `loopId`'s record: it starts now when no read of that loop is in flight (a read of another loop
 * still in flight is left to be dropped by its request number); otherwise it is never dropped but marked pending, and
 * any number of such requests are merged into one more read.
 */
export function loopReadRequest(queue: LoopReadQueue, loopId: string): { queue: LoopReadQueue; start: boolean } {
  if (queue.inFlight === loopId) return { queue: { inFlight: loopId, pending: true }, start: false };
  return { queue: { inFlight: loopId, pending: false }, start: true };
}

/**
 * The read of `loopId` ended (its answer applied or dropped by the request-number rule, or failed): `again` is the loop
 * to read once more right away when a request came while it was in flight and that loop is still the opened one
 * (`openedLoopId`), else null: a re-read of a loop no longer open would cover the opened loop's record. The end of an
 * older read of another loop changes nothing.
 */
export function loopReadSettled(queue: LoopReadQueue, loopId: string, openedLoopId: string | null):
  { queue: LoopReadQueue; again: string | null } {
  if (queue.inFlight !== loopId) return { queue, again: null };
  return { queue: { inFlight: null, pending: false }, again: queue.pending && loopId === openedLoopId ? loopId : null };
}

// ---- late responses (run + loop + iteration + request number per area) ----

export const LOOP_AREAS = ["list", "detail", "create", "projection", "preview", "send", "choice", "compute",
  "abandon", "end", "report"] as const;
export interface LoopStamp { runId: string | null; loopId: string | null; iteration: number | null; seq: number }

/** Applied only when run, loop, iteration and request number are all still current. */
export function loopResponseCurrent(captured: LoopStamp, live: LoopStamp): boolean {
  return captured.runId !== null && captured.runId === live.runId && captured.loopId === live.loopId &&
    captured.iteration === live.iteration && captured.seq === live.seq;
}

/** A new v4 `loop_id` (the M24 `send_id` maker). */
export function newLoopId(): string { return newSendId(); }

// ---- wording check (a proposal is never a rank, recommendation, prediction or effect; no comparison of scores) ----

/** Lines exempt by default: exactly UL1–UL3, the protein note U3 or J7 (the server's LJ lines are passed in). */
export const LOOP_FIXED_LINES: readonly string[] = [...Object.values(LOOP_SCREEN_NOTES), PROTEIN_SCREEN_NOTE,
  JEV_STATEMENTS.J7];
/**
 * Spec 2 wording plus the loop's own: rank, recommendation, best / lowest / highest, improvement, prediction, winner,
 * affinity, stability, ΔΔG, activity, any comparison, difference, average or change of scores, effect and energy.
 * "점수" is allowed (the qvina score is shown); "비활성" is not "활성"; "최소화"/"최적화" are processes.
 */
export const JEV_LOOP_FORBIDDEN = new RegExp(["순위", "추천", "최고", "최저", "최적(?!화)", "최솟값", "최댓값", "개선", "예측",
  "유망", "좋은", "나쁜", "좋아", "나아", "승자", "우승", "우수", "상위", "하위", "향상", "악화", "평균", "차이", "증감", "변화량",
  "대비", "비교", "효과", "친화", "안정성", "ΔΔG", "(?<!비)활성", "에너지", "안전", "가장\\s*(?:높|낮|좋|나)", "\\bbest",
  "\\brank", "recommend", "winner", "improv", "predict", "promising", "highest", "lowest", "better", "worse",
  "superior", "optimal", "affinity", "stabili", "average"].join("|"), "gi");

/**
 * Forbidden words in screen text, line by line. A line exactly equal to a default fixed line or to one of
 * `fixedLines` (the server's stored LJ sentences of the record) is exempt; on any other line only the exact qvina score
 * names are removed before the check (the score name says 친화도가 아님).
 */
export function jevLoopForbiddenWords(text: string, fixedLines: readonly string[] = []): string[] {
  const found: string[] = [];
  for (const line of text.split("\n")) {
    if (LOOP_FIXED_LINES.includes(line) || fixedLines.includes(line)) continue;
    const checked = line.split(SCORE_LABEL).join("").split(SCORE_COLUMN_LABEL).join("");
    for (const match of checked.matchAll(JEV_LOOP_FORBIDDEN)) found.push(match[0]);
  }
  return found;
}
