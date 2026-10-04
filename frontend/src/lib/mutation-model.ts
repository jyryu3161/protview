/**
 * Pure logic of the M21 "변이 구조 모델링" area of the 단백질 공학 tab (`.dryforge/spec.md` 2, 4, 6, 7, 9).
 *
 * Every potential, SASA, contact, score and count comes from the stored `mutation_model@1` object (OpenMM, PDBFixer
 * and FreeSASA run in the job worker) or from the server's `docking_pairs` read (qvina results); this module never
 * computes a scientific value. It builds the model job request (seed required, both confirmations literal, cutoff
 * 2.5–6.0 Å, the M20 candidate by its integer index, nothing chosen automatically), builds the two same-condition M18
 * requests that differ only in `receptor_source.side` (ligand/box/value/acknowledgement rules are the M18 ones in
 * `docking.ts`), tracks the two submissions independently, decides the five area states, keeps late responses out
 * (run + handle + per-area request number) and gives display text: values side by side as stored (two decimals,
 * decimal-string ROUND_HALF_UP), null as "—" with a reason. No difference, change, rank or "better" is computed or
 * worded anywhere (`modelForbiddenWords`); no cross-structure bars or colours.
 */
import type { DockingSourceArgs, DockingSubmission, ExactResidueRef, MutationModelCandidate, MutationModelCapability,
  MutationModelContactPage, MutationModelContactRow, MutationModelDockingPairs, MutationModelListRow, MutationModelPair,
  MutationModelPairCondition, MutationModelPairReason, MutationModelArgs, MutationModelReportArtifact,
  MutationModelResult, MutationModelSide, MutationModelSubmission } from "./contracts";
import { type ArgsCheck, type DockingConditionForm, DOCKING_TOOL, MODE_LABEL, SCORE_COLUMN_LABEL, SCORE_LABEL,
  boxSourceLabel, dockingConditionArgs, dockingJobPhase, dockingJobText, initialDockingForm, modeRowLabel,
  receptorResidueFieldsText, scoreText } from "./docking";
import { decimalHalfUp } from "./site-annotation";

// ---- closed sets, limits and defaults (backend/mw/mutation_model_constants.py; tests compare them) ----

export const MODEL_PROTOCOL = "openmm_mutation_model_v1";
export const MODEL_TOOL = "openmm_mutation_model";
export const MODEL_REPORT_TYPE = "mutation_model";
export const SELECTION_POLICY = "protein_only";
export const HYDROGEN_POLICY = "rebuild_pH7";
export const CONTACT_CUTOFF_DEFAULT_A = 4.0;
export const CONTACT_CUTOFF_RANGE_A: readonly [number, number] = [2.5, 6.0];
export const SEED_RANGE: readonly [number, number] = [0, 2147483647];
export const TIMEOUT_DEFAULT_S = 120;
export const TIMEOUT_MAX_S = 240;
export const MAX_CONTACT_ROWS = 2000;
export const EXCLUDED_BOND_DISTANCE = 3;
export const STRUCTURE_SIDES: readonly MutationModelSide[] = ["wild_type_reference", "mutant"];
/** Admission reasons (422 `input_invalid`), in the server's check order. */
export const ADMISSION_REASON_CODES = ["unknown_field", "confirmation_missing", "argument_invalid",
  "candidate_set_invalid", "candidate_unknown", "structure_invalid", "residue_mismatch", "openmm_preflight_failed"] as const;
/** Precondition reasons (412), returned before any reservation or charge; also the capability reasons. */
export const UNAVAILABLE_REASON_CODES = ["openmm_unavailable", "pdbfixer_unavailable", "process_identity_unavailable"] as const;
/** Closed job failure reasons (`failure.reason_code`). */
export const FAILURE_REASON_CODES = ["mutation_modeling_failed", "unexpected_atoms_added", "coordinates_changed",
  "topology_unsupported", "energy_invalid", "engine_failed", "resource_exceeded"] as const;
export const TOO_MANY_CONTACTS = "too_many_contacts";
/** Read limits (backend/mw/mutation_model_reads.py). */
export const LIST_LIMIT_DEFAULT = 50;
export const LIST_LIMIT_MAX = 100;
export const CONTACT_PAGE_SIZE_DEFAULT = 100;
export const CONTACT_PAGE_SIZE_MAX = 200;
/** Reason codes of a docking-pair side without a score (mutation_model_reads.PAIR_REASONS keys, in order). */
export const PAIR_REASON_CODES: readonly MutationModelPairReason[] = ["not_submitted", "job_not_finished", "job_failed",
  "job_cancelled", "job_interrupted", "result_invalid", "other_side_missing", "no_modes"];
/** Same-condition docking: one action submits one M18 job per structure, in this order. */
export const PAIR_SUBMIT_ORDER: readonly MutationModelSide[] = STRUCTURE_SIDES;
/** Expensive-call units of one same-condition docking action (one per job, each approved on its own path). */
export const PAIR_DOCKING_UNITS = 2;

/**
 * Fixed limitation sentences, verbatim, in the stored order L1, L2, L3, L4, L7, L5, L6 (L5/L6 only when their
 * condition holds). The screen shows the stored `limitations` as they are; this copy only exempts them from the
 * wording check and lets tests compare with the backend.
 */
export const MODEL_LIMITATIONS: readonly string[] = [
  "변이 구조는 PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 모델이며 회전이성질체 탐색과 수렴을 주장하지 않는다.",
  "OpenMM 전위는 각 구조의 Amber14-all + GBn2 암시 용매 값(kJ/mol)이며 서열이 다른 두 구조의 값은 서로 비교할 수 없고 " +
    "ΔΔG·안정성·친화도가 아니다.",
  "모델은 단백질만 포함하며 리간드·금속 이온·물·보조인자는 제외했다.",
  "SASA는 리간드가 없는 단백질 모델의 변이 위치 잔기 값이다.",
  "접촉은 중원자 사이 거리(Å)이며 수소결합이나 상호작용의 종류를 뜻하지 않는다.",
  "변이한 잔기 밖에서 히스티딘·시스테인 양성자 상태가 두 구조에서 다르게 지정되었으므로 두 구조의 차이는 변이 하나만이 아니다.",
  "변이형에는 야생형 기준에 없는 이황화 결합이 거리 기준으로 만들어졌다.",
];

// ---- fixed screen text ----

export const AREA_TITLE = "변이 구조 모델링";
export const NULL_TEXT = "—";
export const SIDE_LABEL: Record<MutationModelSide, string> = { wild_type_reference: "야생형 기준", mutant: "변이형" };
export const ENERGY_LABEL = "OpenMM Amber14-all + GBn2 전위(kJ/mol)";
export const SASA_LABEL = "변이 위치 잔기 SASA(Å², FreeSASA)";
export const CONFIRMATION_LABEL = {
  selection_policy: "protein_only: 단백질만 남기고 물·리간드·이온·비단백질을 제외합니다.",
  hydrogen_policy: "rebuild_pH7: 기존 수소 제거 후 pH 7.0에서 수소를 다시 만듭니다.",
} as const;
export const MODEL_METHOD_NOTE = "PDBFixer 1.12.0이 변이 잔기의 곁사슬만 한 가지 형태로 놓고, 야생형 기준 구조와 변이 구조를 " +
  "같은 설정(OpenMM Amber14-all + GBn2, CPU 1스레드, NoCutoff, 최대 50회)으로 각각 최소화합니다.";
export const MODEL_BUDGET_NOTE = "변이 구조 모델링은 작업 하나에 비싼 계산 예산 1단위입니다(두 구조를 한 작업에서 만듭니다). " +
  "첫 실제 계산은 화면에서 승인해야 시작됩니다.";
export const SIDE_BY_SIDE_NOTE = "두 구조의 저장값을 나란히 놓을 뿐이며 화면은 값을 다시 계산하거나 서로 빼지 않습니다.";
export const NO_RUN_REASON = "run이 없습니다. 구조 분석 탭에서 run을 먼저 고르세요.";
export const CAPABILITY_REASON = "변이 구조 모델링 기능을 사용할 수 없습니다.";
export const NO_MODELS_TEXT = "이 run에 변이 구조 모델이 없습니다. 변이 후보 표의 후보 행에서 시작하세요.";
export const PAIR_AREA_TITLE = "같은 조건 도킹";
export const PAIR_UNITS_NOTICE = `같은 조건 도킹은 야생형 기준 구조와 변이 구조에 도킹 작업 ${PAIR_DOCKING_UNITS}개를 각각 제출합니다. ` +
  `비싼 계산 예산은 작업마다 1단위, 합쳐서 ${PAIR_DOCKING_UNITS}단위이며 각 작업의 첫 실제 계산 승인은 따로 합니다.`;
export const PAIR_CONDITION_NOTE = "같은 리간드·상자·seed·값으로 자유 도킹을 두 구조에 각각 실행합니다. 리간드 좌표는 사용자가 준 " +
  "그대로이며 두 구조에 맞춰 바꾸지 않습니다.";
export const PAIR_SCORE_NOTE = "두 구조의 도킹 결과가 모두 게시된 짝만 점수를 나란히 보입니다. 짝은 제출 순서대로 나열하며 " +
  "어느 쪽이 낫다는 뜻이 아닙니다.";
export const NO_PAIRS_TEXT = "이 모델로 제출한 같은 조건 도킹이 없습니다.";
export const PAIR_MODE_ONLY = "같은 조건 도킹은 자유 도킹만 씁니다.";
export const PAIR_INSTANCE_RANGE_REASON = "변이 구조 모델은 단백질만 담고 있어 뺄 리간드 인스턴스가 없으므로 수용체 안 인스턴스 " +
  "범위 상자를 쓸 수 없습니다.";

/** Korean names of every code the area can show (admission, precondition, failure, job queue and read codes). */
export const MODEL_REASON_LABEL: Record<string, string> = {
  unknown_field: "알 수 없는 요청 항목",
  confirmation_missing: "두 확인(protein_only, rebuild_pH7) 중 하나가 없음",
  argument_invalid: "요청 값의 형식·범위 오류",
  candidate_set_invalid: "이 run의 게시된 변이 후보 집합이 아님",
  candidate_unknown: "후보 집합에 없는 후보 번호",
  structure_invalid: "후보 집합의 구조가 이 run의 전처리 구조가 아님",
  residue_mismatch: "후보 위치 잔기가 구조의 잔기와 맞지 않음",
  openmm_preflight_failed: "OpenMM(M7) 사전 검사 실패",
  openmm_unavailable: "고정 OpenMM 엔진을 사용할 수 없음",
  pdbfixer_unavailable: "고정 PDBFixer를 사용할 수 없음",
  process_identity_unavailable: "작업 프로세스 신원을 확인할 수 없음",
  mutation_modeling_failed: "PDBFixer가 변이 잔기를 만들지 못함",
  unexpected_atoms_added: "변이 잔기 밖에 원자가 더해짐",
  coordinates_changed: "변이 잔기 밖의 좌표가 바뀜",
  topology_unsupported: "OpenMM 위상을 만들 수 없음",
  energy_invalid: "OpenMM 전위가 유효하지 않음",
  engine_failed: "엔진 실행 실패",
  resource_exceeded: "크기·행 상한 초과",
  worker_version_invalid: "작업 환경 버전 확인 실패",
  global_concurrency_busy: "다른 작업이 실행 중",
  global_job_cleanup_pending: "이전 작업 정리 대기 중",
  global_job_ledger_unavailable: "작업 기록을 읽을 수 없음",
  dry_run: "dry-run run(계획만 만듦)",
  input_invalid: "요청 오류",
  method_evidence_invalid: "저장된 결과가 검증되지 않음",
};

const own = (table: Record<string, string>, code: string) =>
  Object.prototype.hasOwnProperty.call(table, code) ? table[code] : undefined;

/** "한국어 (code)"; unknown codes are shown as is. */
export function modelReasonText(code: string): string {
  const label = own(MODEL_REASON_LABEL, code);
  return label ? `${label} (${code})` : code;
}

/** Capability reason as given by the server, with its code; never a number. */
export function modelCapabilityText(capability: Pick<MutationModelCapability, "reason" | "reason_code"> | null): string {
  if (!capability) return CAPABILITY_REASON;
  if (capability.reason) return capability.reason_code ? `${capability.reason} (${capability.reason_code})` : capability.reason;
  return capability.reason_code ? modelReasonText(capability.reason_code) : CAPABILITY_REASON;
}

/**
 * Refused request (`ApiError` of `POST /jobs` or a read): "한국어 (reason_code) · message". An M7 preflight refusal
 * also names M7's own reason code (or that M7 gave none) and its message as the server sent them.
 */
export function modelRequestErrorText(error: { message: string; code?: string; detail?: Record<string, unknown> }): string {
  const reason = typeof error.detail?.reason_code === "string" ? error.detail.reason_code : null;
  const head = reason ? modelReasonText(reason) : error.code ? modelReasonText(error.code) : "요청 실패";
  if (reason === "openmm_preflight_failed") {
    const m7 = typeof error.detail?.m7_reason === "string" ? error.detail.m7_reason : "M7 이유 코드 없음";
    const m7Message = typeof error.detail?.m7_message === "string" ? error.detail.m7_message : error.message;
    return `${head} · M7: ${m7} · ${m7Message}`;
  }
  return `${head} · ${error.message}`;
}

type FailureLike = { error: string; message: string; reason_code?: string; detail?: Record<string, unknown> } | null;

/** Job failure "한국어 (code) · message"; too many contact rows names the stored row count and the limit. */
export function modelFailureText(failure: FailureLike): string {
  if (!failure) return "이유 없음";
  const head = failure.reason_code ? modelReasonText(failure.reason_code) : failure.error;
  const detail = failure.detail;
  const contacts = failure.reason_code === "resource_exceeded" && detail?.limit === TOO_MANY_CONTACTS &&
    typeof detail.rows === "number"
    ? ` · 접촉 행 ${detail.rows}개가 구조당 상한 ${MAX_CONTACT_ROWS}개를 넘어 저장하지 않았습니다(자르지 않음). cutoff를 줄여 다시 시도하세요.`
    : "";
  return `${head} · ${failure.message}${contacts}`;
}

// ---- model request (seed required, both confirmations literal, the candidate by its integer index) ----

export interface ModelForm {
  candidateSet: string | null;
  /** `candidates[].index` of the chosen M20 row; never found from the from/to letters. */
  candidateIndex: number | null;
  seed: string;
  selectionConfirmed: boolean;
  hydrogenConfirmed: boolean;
  cutoff: string;
  timeout: string;
}

/** No candidate, empty seed, confirmations unchecked; adjustable values show their defaults. */
export function initialModelForm(): ModelForm {
  return { candidateSet: null, candidateIndex: null, seed: "", selectionConfirmed: false, hydrogenConfirmed: false,
    cutoff: CONTACT_CUTOFF_DEFAULT_A.toFixed(1), timeout: String(TIMEOUT_DEFAULT_S) };
}

/**
 * The person started from one M20 candidate row. A different candidate unchecks both confirmations (each request is
 * confirmed on its own); seed, cutoff and time stay as typed. Nothing else is chosen.
 */
export function modelFormForCandidate(form: ModelForm, candidateSet: string, candidateIndex: number): ModelForm {
  const same = form.candidateSet === candidateSet && form.candidateIndex === candidateIndex;
  return { ...form, candidateSet, candidateIndex, selectionConfirmed: same && form.selectionConfirmed,
    hydrogenConfirmed: same && form.hydrogenConfirmed };
}

const INT_RE = /^(?:0|[1-9][0-9]*)$/;
const DECIMAL_RE = /^\d+(?:\.\d+)?$/;

function intIn(text: string, low: number, high: number): number | null {
  const trimmed = text.trim();
  if (!INT_RE.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isSafeInteger(value) && value >= low && value <= high ? value : null;
}

/** Plain decimal only (no sign, exponent, hex, Infinity or NaN), inside the inclusive range. */
export function cutoffValue(text: string): number | null {
  const trimmed = text.trim();
  if (!DECIMAL_RE.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isFinite(value) && value >= CONTACT_CUTOFF_RANGE_A[0] && value <= CONTACT_CUTOFF_RANGE_A[1] ? value : null;
}

export interface ModelRequest { args: MutationModelArgs; timeout_s: number }

/**
 * `openmm_mutation_model_v1` arguments exactly as the server admits them (all six keys, the two literal policies,
 * the cutoff always sent) and the top-level `timeout_s`, or every reason the request is blocked. The server checks
 * everything again (candidate set, index, structure, residue, M7 preflight).
 */
export function modelRequest(form: ModelForm): ArgsCheck<ModelRequest> {
  const errors: string[] = [];
  if (form.candidateSet === null || form.candidateIndex === null || !Number.isSafeInteger(form.candidateIndex) ||
      form.candidateIndex < 0) errors.push("변이 후보 표의 후보 행에서 시작하세요(자동으로 고르지 않음).");
  const seed = intIn(form.seed, SEED_RANGE[0], SEED_RANGE[1]);
  if (seed === null) errors.push(`seed: ${SEED_RANGE[0]}–${SEED_RANGE[1]} 사이의 정수를 입력하세요(필수).`);
  if (!form.selectionConfirmed || !form.hydrogenConfirmed)
    errors.push("protein_only와 rebuild_pH7 확인을 모두 체크하세요 (confirmation_missing).");
  const cutoff = cutoffValue(form.cutoff);
  if (cutoff === null) errors.push(`접촉 cutoff: ${CONTACT_CUTOFF_RANGE_A[0].toFixed(1)}–` +
    `${CONTACT_CUTOFF_RANGE_A[1].toFixed(1)} Å 사이의 숫자를 입력하세요(양끝 포함) (argument_invalid).`);
  const timeout = intIn(form.timeout, 1, TIMEOUT_MAX_S);
  if (timeout === null) errors.push(`시간 상한: 1–${TIMEOUT_MAX_S}초 사이의 정수를 입력하세요 (argument_invalid).`);
  if (errors.length || form.candidateSet === null || form.candidateIndex === null || seed === null || cutoff === null ||
      timeout === null) return { ok: false, errors };
  return { ok: true, args: { args: { candidate_set: form.candidateSet, candidate_index: form.candidateIndex, seed,
    selection_policy: SELECTION_POLICY, hydrogen_policy: HYDROGEN_POLICY, contact_cutoff_A: cutoff }, timeout_s: timeout } };
}

type CapabilityLike = Pick<MutationModelCapability, "available" | "reason" | "reason_code">;
const ACTIVE_STATUSES = ["queued", "claimed", "running"];
const FAILED_STATUSES = ["failed", "interrupted", "cancelled"];

/** One model job at a time: null = a model job may be submitted. */
export function modelSubmitBlockedReason(input: { capability: CapabilityLike | null | undefined; busy: boolean;
  activeJob: { status: string } | null; check: ArgsCheck<ModelRequest> }): string | null {
  if (!input.capability?.available) return modelCapabilityText(input.capability ?? null);
  if (input.busy) return "요청을 처리하는 중입니다.";
  if (input.activeJob && ACTIVE_STATUSES.includes(input.activeJob.status))
    return "진행 중인 작업이 끝난 뒤 시작할 수 있습니다(한 번에 한 작업).";
  if (!input.check.ok) return input.check.errors.join(" ");
  return null;
}

// ---- model job (POST /jobs → /start → 409 approval → /jobs/approve → /start → GET /jobs/{id}) ----

export function modelJobText(job: { status: string; cancel_requested: boolean; failure: FailureLike } | null,
  approvalPending: boolean): string {
  switch (dockingJobPhase(job, approvalPending)) {
    case "none": return "변이 구조 모델링 작업 없음";
    case "saved": return "변이 구조 모델링 작업이 저장되었습니다. 시작을 누르면 실제 계산이 실행됩니다(비싼 계산 예산 1단위).";
    case "awaiting_approval": return "비용이 드는 실제 계산 승인이 필요합니다(비싼 계산 예산 1단위). 승인한 뒤 시작을 다시 누르세요.";
    case "running": return `변이 구조 모델링 실행 중${job?.cancel_requested ? " · 취소 요청됨" : ""}`;
    case "done": return "변이 구조 모델링 완료";
    case "cancelled": return "변이 구조 모델링 취소됨 (결과를 저장하지 않았습니다)";
    default:
      return job && ["failed", "interrupted"].includes(job.status) ? `변이 구조 모델링 실패: ${modelFailureText(job.failure)}`
        : `변이 구조 모델링 실패: 알 수 없는 작업 상태 (${job?.status})`;
  }
}

/** Submission is idempotent: identical inputs return the existing job; a dry-run run returns a plan only. */
export function modelSubmitText(result: { plan_only: true } | { job_id: string; status: string }): string {
  if ("plan_only" in result) return "dry-run run이라 계획만 만들었습니다. 실제 계산과 결과 객체는 없습니다.";
  if (result.status === "queued") return modelJobText({ status: "queued", cancel_requested: false, failure: null }, false);
  return `같은 입력의 기존 작업을 다시 표시합니다 · ${result.job_id} · ${result.status} (새 작업을 만들지 않았습니다)`;
}

export function modelApprovalRequired(status: number, approval: { gate: string; tool: string } | undefined): boolean {
  return status === 409 && approval?.gate === "expensive_first_call" && approval.tool === MODEL_TOOL;
}

/** This run's model job that is still queued or running (the latest one), for re-attaching after a remount. */
export function modelActiveJob<T extends { run_id: string; protocol_id: string; status: string }>(jobs: unknown,
  runId: string): T | null {
  if (!Array.isArray(jobs)) return null;
  return (jobs as T[]).filter(job => job && job.run_id === runId && job.protocol_id === MODEL_PROTOCOL &&
    ACTIVE_STATUSES.includes(job.status)).at(-1) ?? null;
}

/** The published model handle of a finished job (null until it is done). */
export function modelJobResult(job: { status: string; artifacts?: { mutation_model?: string } } | null): string | null {
  return job?.status === "done" && typeof job.artifacts?.mutation_model === "string" ? job.artifacts.mutation_model : null;
}

/** A dry-run submission answer (a plan only: no job, no result object). */
export function isPlanOnly(result: MutationModelSubmission | DockingSubmission): boolean {
  return "plan_only" in result && result.plan_only === true;
}

// ---- five states ----

export type ModelAreaState =
  | { state: "loading" } | { state: "ready" } | { state: "empty"; message: string }
  | { state: "failed"; message: string } | { state: "unavailable"; reason: string };

export const MODEL_STATE_TEXT: Record<ModelAreaState["state"], string> = { loading: "불러오는 중", ready: "준비",
  empty: "빈 결과", failed: "실패", unavailable: "사용할 수 없음" };

/**
 * Model area. `capability` undefined = not read yet, null = absent. `models` undefined = list not read yet. A failed,
 * interrupted or cancelled job is a failure (never an empty result); an empty list is "empty" unless a model is open.
 */
export function modelAreaState(input: { runId: string | null; capability?: CapabilityLike | null; loading?: boolean;
  error?: string | null; job?: { status: string; failure: FailureLike } | null; models?: readonly unknown[];
  detail?: unknown | null }): ModelAreaState {
  if (input.runId === null) return { state: "unavailable", reason: NO_RUN_REASON };
  if (input.capability === null || input.capability?.available === false)
    return { state: "unavailable", reason: modelCapabilityText(input.capability ?? null) };
  if (input.error) return { state: "failed", message: input.error };
  const job = input.job;
  if (job && FAILED_STATUSES.includes(job.status))
    return { state: "failed", message: job.status === "cancelled" ? "작업이 취소되어 결과를 저장하지 않았습니다."
      : `작업 실패: ${modelFailureText(job.failure)}` };
  if (input.loading || input.capability === undefined || input.models === undefined ||
      (job && ACTIVE_STATUSES.includes(job.status))) return { state: "loading" };
  if (!input.models.length && !input.detail) return { state: "empty", message: NO_MODELS_TEXT };
  return { state: "ready" };
}

/** Docking-pair area: needs the M18 docking capability; no group yet is "empty" (never a failure). */
export function pairAreaState(input: { runId: string | null; capability?: { available: boolean; reason: string | null;
  reason_code: string | null } | null; loading?: boolean; error?: string | null;
  pairs?: Pick<MutationModelDockingPairs, "total"> | null }): ModelAreaState {
  if (input.runId === null) return { state: "unavailable", reason: NO_RUN_REASON };
  if (input.capability === null || input.capability?.available === false)
    return { state: "unavailable", reason: input.capability?.reason ?? "리간드 도킹 기능을 사용할 수 없습니다." };
  if (input.error) return { state: "failed", message: input.error };
  if (input.loading || input.capability === undefined || input.pairs === undefined || input.pairs === null)
    return { state: "loading" };
  if (input.pairs.total === 0) return { state: "empty", message: NO_PAIRS_TEXT };
  return { state: "ready" };
}

// ---- late responses (run + model handle + per-area request number) ----

export type ModelArea = "list" | "detail" | "contacts" | "pairs" | "report" | "model_job" | "pair_jobs";
export interface ModelStamp { runId: string | null; handle: string | null; area: ModelArea; seq: number }
export type ModelRequestCounters = Record<ModelArea, number>;

export function initialModelCounters(): ModelRequestCounters {
  return { list: 0, detail: 0, contacts: 0, pairs: 0, report: 0, model_job: 0, pair_jobs: 0 };
}

/** A new request in one area: its number goes up (older responses of that area become stale); others unchanged. */
export function nextModelRequest(counters: ModelRequestCounters, area: ModelArea, runId: string | null,
  handle: string | null): { counters: ModelRequestCounters; stamp: ModelStamp } {
  const next = { ...counters, [area]: counters[area] + 1 };
  return { counters: next, stamp: { runId, handle, area, seq: next[area] } };
}

/** Applied only when run, model handle, area and that area's request number are all still current. */
export function modelResponseCurrent(captured: ModelStamp, live: ModelStamp): boolean {
  return captured.runId !== null && captured.runId === live.runId && captured.handle === live.handle &&
    captured.area === live.area && captured.seq === live.seq;
}

/** A created report was saved: announce it while the run is unchanged, even when the late inline display is dropped. */
export function modelReportSavedForRun(captured: ModelStamp, liveRunId: string | null): boolean {
  return captured.runId !== null && captured.runId === liveRunId;
}

// ---- display (values as stored; null is "—" with a reason, never 0) ----

export function nullText(reason: string): string { return `${NULL_TEXT} (${reason})`; }

/** Stored OpenMM potential with two decimals (decimal-string ROUND_HALF_UP); the unit is in `ENERGY_LABEL`. */
export function energyText(value: number | null, reason = "값 없음"): string {
  return value === null ? nullText(reason) : decimalHalfUp(value, 2);
}

/** Stored residue SASA with two decimals, e.g. 12.345 → "12.35 Å²". */
export function sasaText(value: number | null, reason = "값 없음"): string {
  return value === null ? nullText(reason) : `${decimalHalfUp(value, 2)} Å²`;
}

/** Stored distance (Å) with two decimals, e.g. 3.005 → "3.01 Å". */
export function distanceText(value: number | null, reason = "값 없음"): string {
  return value === null ? nullText(reason) : `${decimalHalfUp(value, 2)} Å`;
}

export function countText(value: number | null, reason = "값 없음"): string {
  return value === null ? nullText(reason) : String(value);
}

/** The seven residue fields exactly as stored (identity display; never parsed back). */
export function residueFieldsText(residue: ExactResidueRef): string { return receptorResidueFieldsText(residue); }

/** "ILE A:10A" (auth numbering), display only. */
export function residueShortText(residue: ExactResidueRef): string {
  return `${residue.resname} ${residue.chain_auth}:${residue.seq_auth}${residue.icode}`;
}

/** One-line summary of the modelled mutation: original position (7 fields) and from → to. */
export function mutationSummaryText(candidate: Pick<MutationModelCandidate, "candidate_set" | "candidate_index" |
  "residue" | "from" | "to" | "mutant_resname">): string {
  return `${residueShortText(candidate.residue)} · ${candidate.from} → ${candidate.to} ` +
    `(${candidate.residue.resname} → ${candidate.mutant_resname}) · 위치 ${residueFieldsText(candidate.residue)} · ` +
    `후보 집합 ${candidate.candidate_set} · 후보 번호 ${candidate.candidate_index}`;
}

export interface SideBySideRow { key: string; label: string; values: Record<MutationModelSide, string> }

function perSide(result: Pick<MutationModelResult, "structures">,
  pick: (entry: MutationModelResult["structures"][MutationModelSide], side: MutationModelSide) => string) {
  return { wild_type_reference: pick(result.structures.wild_type_reference, "wild_type_reference"),
    mutant: pick(result.structures.mutant, "mutant") };
}

/**
 * The side-by-side table: each row is one stored value per structure, nothing else (no difference, change or rank
 * column; the browser computes nothing).
 */
export function sideBySideRows(result: Pick<MutationModelResult, "structures" | "comparison" | "parameters">): SideBySideRow[] {
  const cutoff = decimalHalfUp(result.parameters.contact_cutoff_A, 2);
  return [
    { key: "resname", label: "변이 위치 잔기 이름", values: { ...result.comparison.resnames } },
    { key: "energy_before", label: `${ENERGY_LABEL} · 최소화 전`, values: perSide(result, e => energyText(e.energy.before_kJ_mol)) },
    { key: "energy_after", label: `${ENERGY_LABEL} · 최소화 후`, values: perSide(result, e => energyText(e.energy.after_kJ_mol)) },
    { key: "sasa", label: SASA_LABEL, values: perSide(result, e => sasaText(e.sasa.value_A2)) },
    { key: "contacts", label: `변이 위치 잔기 주변 중원자 접촉 수(${cutoff} Å 이하, ${EXCLUDED_BOND_DISTANCE}결합 이내 제외)`,
      values: perSide(result, e => countText(e.contacts.count)) },
    { key: "contact_residues", label: "접촉 상대 잔기 수", values: perSide(result, e => countText(e.contacts.residue_count)) },
    { key: "added_heavy_atoms", label: "PDBFixer가 놓은 중원자(변이 잔기)", values: perSide(result, e => addedAtomsText(e.added_heavy_atoms)) },
    { key: "disulfide_bonds", label: "이황화 결합 수", values: perSide(result, e => countText(e.disulfide_bonds.length)) },
    { key: "heavy_atoms", label: "중원자 수", values: perSide(result, e => countText(e.heavy_atoms)) },
    { key: "added_hydrogens", label: "pH 7.0에서 만든 수소 수", values: perSide(result, e => countText(e.added_hydrogens)) },
  ];
}

/** PDBFixer-placed heavy atoms of the mutated residue ("0개" is a real count: the wild-type reference adds none). */
export function addedAtomsText(atoms: readonly { atom_name: string; element: string }[]): string {
  return atoms.length ? `${atoms.length}개 (${atoms.map(atom => `${atom.atom_name} ${atom.element}`).join(", ")})` : "0개";
}

/** OpenMM variant name; null means the default template (not a missing value). */
export function variantText(variant: string | null): string { return variant === null ? "기본 템플릿 (null)" : variant; }

/** Rows of the protonation-state table (residues outside the mutated one whose states the two structures differ in). */
export function protonationRows(result: Pick<MutationModelResult, "protonation_differences">):
  { residue: string; fields: string; values: Record<MutationModelSide, string> }[] {
  return result.protonation_differences.map(row => ({ residue: residueShortText(row.residue),
    fields: residueFieldsText(row.residue), values: { wild_type_reference: variantText(row.wild_type_reference),
      mutant: variantText(row.mutant) } }));
}

/** Disulfide bonds of one structure as residue pairs, or "0개". */
export function disulfideText(bonds: readonly (readonly [ExactResidueRef, ExactResidueRef])[]): string {
  return bonds.length ? bonds.map(([a, b]) => `${residueShortText(a)}–${residueShortText(b)}`).join(", ") : "0개";
}

/** The stored limitation sentences, verbatim and in the stored order (never re-chosen or re-ordered here). */
export function modelLimitations(result: Pick<MutationModelResult, "limitations">): readonly string[] {
  return result.limitations;
}

/** Stored sentences that are not one of the fixed ones (a non-empty answer means the screen must not trust them). */
export function unknownLimitations(sentences: readonly string[]): string[] {
  return sentences.filter(sentence => !MODEL_LIMITATIONS.includes(sentence));
}

/** Query of one contact page: `structure` side, 1-based `page`, `page_size` 1–200. */
export function modelContactQuery(side: MutationModelSide, page: number, pageSize = CONTACT_PAGE_SIZE_DEFAULT): string {
  const params = new URLSearchParams();
  params.set("structure", side);
  params.set("page", String(Math.max(1, Math.trunc(page))));
  params.set("page_size", String(Math.min(CONTACT_PAGE_SIZE_MAX, Math.max(1, Math.trunc(pageSize)))));
  return params.toString();
}

export const CONTACT_TABLE_HEADERS = ["행", "변이 잔기 원자", "상대 잔기", "상대 원자", "거리"] as const;

/** One stored contact row as displayed (the 7 partner fields stay the identity; the short text is display only). */
export function contactRowCells(row: MutationModelContactRow): string[] {
  return [String(row.index + 1), `${row.atom_name} (${row.element})`, residueShortText(row.partner_residue),
    `${row.partner_atom_name} (${row.partner_element})`, distanceText(row.distance_A)];
}

/** "중원자 접촉 n개 중 a–b"; zero contacts is a computed result, never "not computed". */
export function contactPageText(page: Pick<MutationModelContactPage, "structure" | "cutoff_A" | "total" | "page" |
  "page_size" | "rows">): string {
  const cutoff = decimalHalfUp(page.cutoff_A, 2);
  if (page.total === 0)
    return `${SIDE_LABEL[page.structure]}: 변이 위치 잔기 주변 중원자 접촉은 0개입니다(${cutoff} Å 안, ` +
      `${EXCLUDED_BOND_DISTANCE}결합 이내 제외). 계산한 결과이며 빈 값이 아닙니다.`;
  const first = (page.page - 1) * page.page_size + 1;
  if (!page.rows.length) return `${SIDE_LABEL[page.structure]}: 중원자 접촉 ${page.total}개 · 이 페이지에 행 없음`;
  return `${SIDE_LABEL[page.structure]}: 중원자 접촉 ${page.total}개 중 ${first}–${first + page.rows.length - 1}`;
}

export function contactPageCount(total: number, pageSize = CONTACT_PAGE_SIZE_DEFAULT): number {
  return Math.max(1, Math.ceil(total / pageSize));
}

/** One stored model in the list; a row that does not validate shows no values. */
export function modelListRowText(row: MutationModelListRow): string {
  if (!row.valid || !row.candidate || !row.parameters)
    return `생성 순번 ${row.created_seq} · 읽을 수 없음: ${modelReasonText("method_evidence_invalid")}`;
  return `생성 순번 ${row.created_seq} · ${residueShortText(row.candidate.residue)} ${row.candidate.from} → ` +
    `${row.candidate.to} · seed ${row.parameters.seed} · cutoff ${decimalHalfUp(row.parameters.contact_cutoff_A, 2)} Å`;
}

export function structureDownloadLabel(side: MutationModelSide): string {
  return `${SIDE_LABEL[side]} 구조 mmCIF 내려받기`;
}

/** The report answer belongs to the opened model. */
export function modelReportMatches(artifact: Pick<MutationModelReportArtifact, "manifest">, modelHandle: string): boolean {
  return artifact.manifest.schema === "method_report_manifest@1" &&
    artifact.manifest.analysis_type === MODEL_REPORT_TYPE && artifact.manifest.result_handle === modelHandle;
}

// ---- same-condition docking requests (two M18 jobs differing only in receptor_source.side) ----

/** Ligand, box, values and acknowledgements of the M18 form; the mode is always free docking. */
export type PairDockingForm = DockingConditionForm;
export const PAIR_BOX_SOURCES = ["ligand_range", "manual"] as const;

export function initialPairDockingForm(): PairDockingForm {
  const base = initialDockingForm();
  return { ligandSource: base.ligandSource, sdfHandle: base.sdfHandle, candidateSetHandle: base.candidateSetHandle,
    candidateId: base.candidateId, parentSdfHandle: base.parentSdfHandle, mode: "free", boxSource: base.boxSource,
    margin: base.margin, center: base.center, size: base.size, seed: base.seed, exhaustiveness: base.exhaustiveness,
    numModes: base.numModes, energyRange: base.energyRange, conformers: base.conformers,
    acknowledgement: { ...base.acknowledgement } };
}

/**
 * Applies an edit and clears what it invalidates (a new candidate set clears the candidate and its parent SDF); the
 * mode stays free docking and an instance-range box is dropped (a protein-only model has no instance to remove).
 */
export function patchPairDockingForm(form: PairDockingForm, patch: Partial<PairDockingForm>): PairDockingForm {
  const next: PairDockingForm = { ...form, ...patch, mode: "free" };
  if (next.candidateSetHandle !== form.candidateSetHandle) {
    if (!("candidateId" in patch)) next.candidateId = null;
    if (!("parentSdfHandle" in patch)) next.parentSdfHandle = null;
  }
  if (next.boxSource === "instance_range") next.boxSource = null;
  return next;
}

/** Why a box source cannot be chosen for a mutation-model receptor (null = usable). */
export function pairBoxSourceDisabledReason(source: string): string | null {
  return source === "instance_range" ? PAIR_INSTANCE_RANGE_REASON : null;
}

/**
 * The two `qvina_dock_v1` requests of one same-condition action, keyed by side. They are identical except
 * `receptor_source.side`; the ligand, box, values and acknowledgements follow the M18 rules (`dockingConditionArgs`)
 * and no imported-receptor key (`receptor_handle`, `receptor_model_number`, `connectivity`, `receptor_instance`) is
 * present.
 */
export function pairDockingRequests(form: PairDockingForm, modelHandle: string | null):
  ArgsCheck<Record<MutationModelSide, DockingSourceArgs>> {
  const errors: string[] = [];
  if (!modelHandle) errors.push("변이 구조 모델을 먼저 여세요.");
  if (form.mode !== "free") errors.push(PAIR_MODE_ONLY);
  const condition = dockingConditionArgs({ ...form, mode: "free" },
    form.boxSource === null ? null : pairBoxSourceDisabledReason(form.boxSource));
  if (!condition.ok) errors.push(...condition.errors);
  if (errors.length || !condition.ok || !modelHandle) return { ok: false, errors };
  const given = condition.args.box;
  const box: DockingSourceArgs["box"] | null = given.source === "manual" ? given
    : given.source === "ligand_range" ? { source: "ligand_range", margin_A: given.margin_A } : null;
  if (box === null) return { ok: false, errors: [`${PAIR_INSTANCE_RANGE_REASON} (box_invalid)`] };
  const build = (side: MutationModelSide): DockingSourceArgs => ({
    receptor_source: { kind: "mutation_model", mutation_model: modelHandle, side },
    ligand: condition.args.ligand, mode: condition.args.mode, box, parameters: condition.args.parameters,
    acknowledgement: condition.args.acknowledgement });
  return { ok: true, args: { wild_type_reference: build("wild_type_reference"), mutant: build("mutant") } };
}

/** Why the same-condition action is blocked (null = both requests may be submitted). */
export function pairSubmitBlockedReason(input: { capability: { available: boolean; reason: string | null } | null |
  undefined; busy: boolean; unitsConfirmed: boolean; activeJobs: readonly { status: string }[];
  check: ArgsCheck<Record<MutationModelSide, DockingSourceArgs>> }): string | null {
  if (!input.capability?.available) return input.capability?.reason ?? "리간드 도킹 기능을 사용할 수 없습니다.";
  if (input.busy) return "요청을 처리하는 중입니다.";
  if (input.activeJobs.some(job => ACTIVE_STATUSES.includes(job.status)))
    return "진행 중인 도킹 작업이 끝난 뒤 시작할 수 있습니다.";
  if (!input.check.ok) return input.check.errors.join(" ");
  if (!input.unitsConfirmed) return `도킹 작업 ${PAIR_DOCKING_UNITS}개, 합쳐서 비싼 계산 ${PAIR_DOCKING_UNITS}단위임을 확인하세요.`;
  return null;
}

// ---- the two submissions (independent: one side failing never hides or stops the other) ----

export type PairSubmitStatus = "pending" | "submitting" | "submitted" | "plan_only" | "refused";
export interface PairSideSubmit { side: MutationModelSide; status: PairSubmitStatus; jobId: string | null;
  jobStatus: string | null; error: string | null }
export type PairSubmission = Record<MutationModelSide, PairSideSubmit>;

export function initialPairSubmission(): PairSubmission {
  const one = (side: MutationModelSide): PairSideSubmit => ({ side, status: "pending", jobId: null, jobStatus: null,
    error: null });
  return { wild_type_reference: one("wild_type_reference"), mutant: one("mutant") };
}

/** The next side to submit, in `PAIR_SUBMIT_ORDER` (null while one is being submitted or when both are answered). */
export function nextPairSubmitSide(submission: PairSubmission): MutationModelSide | null {
  if (PAIR_SUBMIT_ORDER.some(side => submission[side].status === "submitting")) return null;
  return PAIR_SUBMIT_ORDER.find(side => submission[side].status === "pending") ?? null;
}

export function pairSubmitStarted(submission: PairSubmission, side: MutationModelSide): PairSubmission {
  return { ...submission, [side]: { ...submission[side], status: "submitting", error: null } };
}

/** Records one side's answer; the other side's entry is never touched. */
export function pairSubmitAnswered(submission: PairSubmission, side: MutationModelSide,
  outcome: { ok: true; result: DockingSubmission } | { ok: false; error: string }): PairSubmission {
  const entry: PairSideSubmit = !outcome.ok
    ? { side, status: "refused", jobId: null, jobStatus: null, error: outcome.error }
    : "plan_only" in outcome.result ? { side, status: "plan_only", jobId: null, jobStatus: null, error: null }
      : { side, status: "submitted", jobId: outcome.result.job_id, jobStatus: outcome.result.status, error: null };
  return { ...submission, [side]: entry };
}

/** Both sides answered (submitted, plan only or refused). */
export function pairSubmissionDone(submission: PairSubmission): boolean {
  return PAIR_SUBMIT_ORDER.every(side => !["pending", "submitting"].includes(submission[side].status));
}

/** Per-side submission text; a refusal shows its reason without hiding the other side. */
export function pairSubmitText(entry: PairSideSubmit): string {
  const head = `${SIDE_LABEL[entry.side]}: `;
  switch (entry.status) {
    case "pending": return `${head}제출 전`;
    case "submitting": return `${head}제출 중`;
    case "plan_only": return `${head}dry-run run이라 계획만 만들었습니다(작업·결과 없음).`;
    case "refused": return `${head}제출 거절 · ${entry.error ?? "이유 없음"}`;
    default: return `${head}작업 ${entry.jobId} · ${entry.jobStatus}`;
  }
}

/**
 * The side whose saved job should be started next, in submission order: only when no docking job of the pair is
 * claimed or running (the server holds a start until its job ends). A side whose job is not queued is skipped.
 */
export function nextPairStartSide(jobs: Record<MutationModelSide, { status: string } | null>): MutationModelSide | null {
  if (PAIR_SUBMIT_ORDER.some(side => ["claimed", "running"].includes(jobs[side]?.status ?? ""))) return null;
  return PAIR_SUBMIT_ORDER.find(side => jobs[side]?.status === "queued") ?? null;
}

/** One side's docking job state (M18 wording), prefixed with the structure name. */
export function pairJobText(side: MutationModelSide, job: { status: string; cancel_requested: boolean;
  failure: FailureLike } | null,
  approvalPending: boolean): string {
  return `${SIDE_LABEL[side]}: ${dockingJobText(job, approvalPending)}`;
}

export function pairApprovalRequired(status: number, approval: { gate: string; tool: string } | undefined): boolean {
  return status === 409 && approval?.gate === "expensive_first_call" && approval.tool === DOCKING_TOOL;
}

// ---- docking pair display (`docking_pairs` exactly as the server gives it) ----

const JOB_STATUS_LABEL: Record<string, string> = { not_submitted: "제출하지 않음", queued: "대기", claimed: "실행 중",
  running: "실행 중", done: "완료", failed: "실패", cancelled: "취소됨", interrupted: "중단됨" };

export function pairJobStatusText(status: string): string {
  return own(JOB_STATUS_LABEL, status) ? `${JOB_STATUS_LABEL[status]} (${status})` : status;
}

/** The docking condition of one group: ligand, mode, requested box and every value. */
export function pairConditionText(condition: MutationModelPairCondition): string {
  const ligand = condition.ligand.source === "sdf" ? `3D SDF ${condition.ligand.sdf_handle}`
    : `M17 후보 ${condition.ligand.candidate_id} · 후보 집합 ${condition.ligand.candidate_set_handle} · 부모 SDF ` +
      condition.ligand.parent_sdf_handle;
  const box = condition.box.source === "manual"
    ? `중심 (${condition.box.center_A.map(v => decimalHalfUp(v, 2)).join(", ")}) Å · 크기 ` +
      `(${condition.box.size_A.map(v => decimalHalfUp(v, 2)).join(", ")}) Å · ${boxSourceLabel("manual")}`
    : `${boxSourceLabel(condition.box.source)} · 여백 ${decimalHalfUp(condition.box.margin_A, 2)} Å`;
  const values = condition.parameters;
  return `${ligand} · ${MODE_LABEL[condition.mode]} · 상자 ${box} · seed ${values.seed} · exhaustiveness ` +
    `${values.exhaustiveness} · num_modes ${values.num_modes} · energy_range ${decimalHalfUp(values.energy_range, 2)} kcal/mol` +
    (values.conformers === null ? "" : ` · conformers ${values.conformers}`);
}

export interface PairSideCell { side: MutationModelSide; job: string; score: string | null; text: string;
  resultHandle: string | null }

/**
 * One side of a pair: the stored score (one decimal, with its mode row name) only when the server says both sides
 * are published results; otherwise no number, "없음(reason)" with the server's reason sentence.
 */
export function pairSideCell(pair: Pick<MutationModelPair, "both_published" | "condition" | "sides">,
  side: MutationModelSide): PairSideCell {
  const entry = pair.sides[side];
  const job = pairJobStatusText(entry.job_status);
  if (pair.both_published && entry.score_kcal_mol !== null && entry.score_mode !== null) {
    const score = scoreText(entry.score_kcal_mol);
    return { side, job, score, text: `${score} · ${modeRowLabel(pair.condition.mode, entry.score_mode)}`,
      resultHandle: entry.result_handle };
  }
  const reason = entry.reason ?? (entry.reason_code ? entry.reason_code : "이유 없음");
  return { side, job, score: null, text: `없음(${reason})`, resultHandle: pair.both_published ? entry.result_handle : null };
}

export interface PairRow { index: number; condition: string; cells: Record<MutationModelSide, PairSideCell> }

/** Every group in the server's order (first submission), none picked or re-ordered. */
export function pairRows(pairs: Pick<MutationModelDockingPairs, "pairs">): PairRow[] {
  return pairs.pairs.map(pair => ({ index: pair.index, condition: pairConditionText(pair.condition),
    cells: { wild_type_reference: pairSideCell(pair, "wild_type_reference"), mutant: pairSideCell(pair, "mutant") } }));
}

/** Pair table header; the score name is the server's `score_label` (the M18 wording). */
export function pairTableHeaders(scoreLabel: string): string[] {
  return ["짝", "도킹 조건", `${SIDE_LABEL.wild_type_reference} · ${scoreLabel}`, `${SIDE_LABEL.mutant} · ${scoreLabel}`];
}

// ---- wording check (no difference, change, rank, recommendation, stability or "better" anywhere on screen) ----

const FORBIDDEN = new RegExp(["순위", "추천", "개선", "증가", "감소", "안정성", "ΔΔG", "Δ", "차이", "변화량", "최적(?!화)", "최고",
  "유망", "좋은", "나쁜", "친화", "\\brank", "\\bbest", "improv", "recommend", "optimal", "stabili", "delta",
  "differen"].join("|"), "gi");

/**
 * Forbidden words in screen text, line by line. A line equal to a fixed limitation sentence (M21 L1–L7) is exempt;
 * on other lines only the exact M18 score names are removed before the check.
 */
export function modelForbiddenWords(text: string): string[] {
  const found: string[] = [];
  for (const line of text.split("\n")) {
    if (MODEL_LIMITATIONS.includes(line)) continue;
    const checked = line.split(SCORE_LABEL).join("").split(SCORE_COLUMN_LABEL).join("");
    for (const match of checked.matchAll(FORBIDDEN)) found.push(match[0]);
  }
  return found;
}
