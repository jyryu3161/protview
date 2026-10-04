/**
 * Pure logic of the M22 GA design area of the "리간드 설계·탐색" tab (`.dryforge/spec.md` sections 2, 4, 5, 6, 8, 9).
 *
 * Every score, count, budget figure and sentence shown comes from the server (the stored `ligand_ga_result@1`, its
 * individuals' `docking_result@1`, the preflight read or the job record); this module never computes a score, a
 * difference or an aggregate. It holds the GA parameter definitions (same ranges and defaults as
 * `backend/mw/ligand_ga_constants.py`), the per-field validator and cross rules, the exact job-argument shape, the
 * preflight / progress / result view models, the display order of the individuals table (a display order only: rows
 * without a score stay last and are never treated as 0) and wording ("한국어 (code)"). M18 rules and texts are reused
 * from `lib/docking.ts`. GA is a search over the candidate pool; nothing here calls an individual or a score good.
 */
import type { LigandFilterSpec, LigandGaArgs, LigandGaEvaluation, LigandGaGeneration, LigandGaIndividual,
  LigandGaKey, LigandGaLimitApproval, LigandGaOrigin, LigandGaParameters, LigandGaPreflight, LigandGaProgress,
  LigandGaState, LigandGaStatement, LigandGaStatus, LigandGaStopReason } from "./contracts";
import { type ArgsCheck, DOCKING_LIMITATIONS, dockingArgs, dockingCapabilityText, dockingFailureText,
  dockingForbiddenWords, dockingJobPhase, dockingReasonText, dockingRefusalList, type DockingForm,
  type DockingRefusalList, initialDockingForm, patchDockingForm, SCORE_COLUMN_LABEL, SCORE_LABEL,
  scoreText } from "./docking";
import { decimalHalfUp } from "./site-annotation";

export { SCORE_COLUMN_LABEL, SCORE_LABEL };

// ---- closed sets, ranges and limits (same values and order as backend/mw/ligand_ga_constants.py; tests compare) ----
export const GA_PROTOCOL = "qvina_ga_dock_v1";
export const GA_TOOL = "qvina_ga_design";
export const GA_KEYS: readonly LigandGaKey[] = ["seed", "population_size", "generations", "elite_count",
  "tournament_size", "neighbor_count", "random_fraction", "patience", "max_new_dockings", "total_s"];
/** [min, max, default]; `seed` has no default (required). `max_new_dockings` min is also `population_size`. */
export const GA_RANGES: Record<LigandGaKey, readonly [number, number, number | null]> = {
  seed: [0, 2147483647, null],
  population_size: [4, 24, 12],
  generations: [1, 8, 5],
  elite_count: [0, 4, 2],
  tournament_size: [2, 4, 2],
  neighbor_count: [3, 30, 10],
  random_fraction: [0.0, 0.5, 0.2],
  patience: [1, 8, 3],
  max_new_dockings: [4, 100, 60],
  total_s: [600, 14400, 7200],
};
export const GA_FLOAT_KEYS: readonly LigandGaKey[] = ["random_fraction"];
/** `population_size - elite_count >= 2`. */
export const MIN_NEW_SLOTS = 2;
export const PER_CANDIDATE_S = 300;
export const MAX_NEW_DOCKINGS = 100;
export const TOTAL_S_MAX = 14400;
/** The job `timeout_s` is always `ga.total_s + FINISH_MARGIN_S` (the screen sends it; the server sets no default). */
export const FINISH_MARGIN_S = 600;
export const TIMEOUT_MAX_S = 15000;
export const MAX_POOL = 2000;

export const ADMISSION_REASONS = ["ga_pool_too_small", "ga_reuse_too_large", "ga_limit_raise_required"] as const;
export const STOP_REASONS: readonly LigandGaStopReason[] = ["generations_complete", "no_change", "pool_exhausted",
  "docking_limit", "time_exhausted", "cancelled", "worker_failed", "resource_exceeded"];
export const GA_STATUSES: readonly LigandGaStatus[] = ["complete", "partial"];
export const STATUS_BY_STOP_REASON: Record<LigandGaStopReason, LigandGaStatus> = {
  generations_complete: "complete", no_change: "complete", pool_exhausted: "complete", docking_limit: "partial",
  time_exhausted: "partial", cancelled: "partial", worker_failed: "partial", resource_exceeded: "partial",
};
export const ORIGINS: readonly LigandGaOrigin[] = ["initial", "carried", "similar", "random"];
export const EVALUATIONS: readonly LigandGaEvaluation[] = ["reused", "docked"];
export const STATES: readonly LigandGaState[] = ["scored", "null_result", "failed"];
export const FAILED_EXTRA_REASONS = ["candidate_timeout", "worker_failed"] as const;

// ---- fixed wording ----
/** Score target of each individual: the first mode of its M18 result (= M19 `SCORE_ROW_LABELS.free`). */
export const SCORE_ROW_LABEL = "모드 1(엔진 출력 순서)";
/** spec 4, verbatim and in order: G1 always, G2 when partial, G3 when any individual was reused. */
export const GA_STATEMENTS = {
  G1: "GA는 후보 풀에서 어디를 도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 순위나 추천이 아니다. " +
    "부모·유사 후보 연결은 작업 모듈 기록이며 서버가 다시 계산하지 않았다.",
  G2: "이 실행은 시간·도킹 상한·취소 등으로 일부 세대만 계산되었다. 계산하지 않은 개체는 점수가 없으며 0이 아니고, " +
    "한도 도달로 멈춘 실행은 같은 설정으로 다시 해도 같은 경로를 보장하지 않는다.",
  G3: "재사용한 개체는 같은 수용체·상자·seed·방식·값으로 이전에 저장된 도킹 결과를 가져온 것이며, " +
    "저장된 결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있다.",
} as const;
export const REUSED_LABEL = "저장된 결과 재사용";
export const DOCKED_LABEL = "새 도킹";
export const CARRIED_EVALUATION_LABEL = "다시 도킹하지 않음(이전 세대 결과 인용)";
export const LIMIT_RAISE_LABEL = "이 GA에 필요한 만큼 한도를 올림";
export const SEED_NOTE = "GA seed는 후보 선택 순서의 난수이고, 도킹 값의 seed는 qvina 난수입니다. 두 값은 따로 입력하며 " +
  "같은 숫자여도 됩니다.";
export const MODE_NOTE = "GA의 개체 도킹은 자유 도킹으로 고정됩니다(코어 고정 없음).";
/** Shown when the server says `full_run_may_be_partial` (reserved_units × 300 s > total_s). */
export const PARTIAL_RISK_NOTE = "끝까지 못 갈 수 있음: 예약 단위 × 300초가 GA 전체 시간 상한보다 깁니다. 시간 상한에 닿으면 그때까지 " +
  "평가한 개체만 남습니다.";
export const WAIT_NOTE = "GA가 도는 동안 이 run의 다른 계산·보고서 호출과 다른 비싼 작업이 기다립니다.";
export const ORDER_NOTE = "표의 정렬은 표시 순서일 뿐입니다. 점수 없는 개체는 0이 아니며 늘 끝에 둡니다.";
export const SIMILARITY_NOTE = "유사도는 저장 SMILES의 Morgan 지문 Tanimoto(작업 모듈 기록, 서버가 다시 계산하지 않음)이며 " +
  "점수나 활성이 아닙니다.";

export function chargeNote(units: number): string {
  return `시작하면 ${units}단위가 예약·소진되고 중간에 멈추거나 재사용이 있어도 돌려받지 않음`;
}

// ---- parameter definitions ----

export interface GaParameterDef { key: LigandGaKey; label: string; unit: string; min: number; max: number;
  default: number | null; integer: boolean }

const GA_LABELS: Record<LigandGaKey, [string, string]> = {
  seed: ["GA seed(후보 선택 난수)", ""],
  population_size: ["세대당 개체 수", "개"],
  generations: ["세대 수 상한(첫 세대 = 세대 1)", "세대"],
  elite_count: ["다음 세대로 이어받는 개체 수", "개"],
  tournament_size: ["부모 선택 토너먼트 크기", "개"],
  neighbor_count: ["유사 후보를 뽑을 가까운 미평가 후보 수", "개"],
  random_fraction: ["새 자리 중 무작위 후보 비율", ""],
  patience: ["점수 최솟값이 내려가지 않는 연속 세대 수(이만큼이면 중단)", "세대"],
  max_new_dockings: ["새 도킹 건수 상한(재사용은 세지 않음)", "건"],
  total_s: ["GA 전체 시간 상한(수용체 준비 포함)", "초"],
};

export const GA_PARAMETERS: readonly GaParameterDef[] = GA_KEYS.map(key => ({ key, label: GA_LABELS[key][0],
  unit: GA_LABELS[key][1], min: GA_RANGES[key][0], max: GA_RANGES[key][1], default: GA_RANGES[key][2],
  integer: !GA_FLOAT_KEYS.includes(key) }));

function plainNumber(value: number): string { return String(value); }

/** "4–24 개 · 기본 12"; seed "0–2147483647 · 기본 없음(필수)"; max_new_dockings min is the population size. */
export function gaRangeText(key: LigandGaKey): string {
  const [low, high, fallback] = GA_RANGES[key];
  const unit = GA_LABELS[key][1];
  const lowText = key === "max_new_dockings" ? "세대당 개체 수" : plainNumber(low);
  return `${lowText}–${plainNumber(high)}${unit ? ` ${unit}` : ""} · 기본 ${fallback === null ? "없음(필수)" :
    plainNumber(fallback)}`;
}

/** Inputs as typed (strings, trimmed before checking). */
export type GaInput = Record<LigandGaKey, string>;

/** Every default prefilled; the GA seed is empty (required). */
export function initialGaInput(): GaInput {
  return Object.fromEntries(GA_KEYS.map(key => [key, GA_RANGES[key][2] === null ? "" :
    plainNumber(GA_RANGES[key][2] as number)])) as GaInput;
}

/** "기본값으로": every default back, the typed GA seed kept (it has no default). */
export function resetGaDefaults(input: GaInput): GaInput { return { ...initialGaInput(), seed: input.seed }; }

const INT_RE = /^(?:0|[1-9][0-9]*)$/;
/** Plain decimal syntax (same as the M18 numbers); no hexadecimal, no "Infinity", no blanks. */
const NUMBER_RE = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/;

function parseField(key: LigandGaKey, text: string): number | null {
  const trimmed = text.trim();
  const [low, high] = GA_RANGES[key];
  const value = Number(trimmed);
  if (GA_FLOAT_KEYS.includes(key))
    return NUMBER_RE.test(trimmed) && Number.isFinite(value) && value >= low && value <= high ? value + 0 : null;
  return INT_RE.test(trimmed) && Number.isSafeInteger(value) && value >= low && value <= high ? value : null;
}

function fieldError(key: LigandGaKey): string {
  const [low, high] = GA_RANGES[key];
  const kind = GA_FLOAT_KEYS.includes(key) ? "숫자" : "정수";
  const required = key === "seed" ? "(필수)" : "";
  return `${GA_LABELS[key][0]}: ${plainNumber(low)}–${plainNumber(high)} 사이의 ${kind}를 입력하세요${required} ` +
    "(invalid_job_arguments).";
}

export type GaCheck = { ok: true; ga: LigandGaParameters; fields: Record<LigandGaKey, null>; errors: [] } |
  { ok: false; ga: null; fields: Record<LigandGaKey, string | null>; errors: string[] };

/**
 * Per-field errors (format and range of the spec 2 table) and the cross rules: `population_size - elite_count >= 2`
 * (shown at `elite_count`) and `max_new_dockings >= population_size` (shown at `max_new_dockings`). The server
 * checks everything again; these checks keep an impossible request from being sent and show why.
 */
export function checkGaInput(input: GaInput): GaCheck {
  const fields = Object.fromEntries(GA_KEYS.map(key => [key, null])) as Record<LigandGaKey, string | null>;
  const values: Partial<LigandGaParameters> = {};
  for (const key of GA_KEYS) {
    const value = parseField(key, input[key] ?? "");
    if (value === null) fields[key] = fieldError(key);
    else values[key] = value;
  }
  const { population_size: population, elite_count: elite, max_new_dockings: maxNew } = values;
  if (fields.elite_count === null && population !== undefined && elite !== undefined &&
      population - elite < MIN_NEW_SLOTS)
    fields.elite_count = `${GA_LABELS.elite_count[0]}: 세대당 개체 수 − 이어받는 개체 수가 ${MIN_NEW_SLOTS} 이상이어야 ` +
      "합니다 (invalid_job_arguments).";
  if (fields.max_new_dockings === null && population !== undefined && maxNew !== undefined && maxNew < population)
    fields.max_new_dockings = `${GA_LABELS.max_new_dockings[0]}: 세대당 개체 수(${population}) 이상이어야 합니다 ` +
      "(invalid_job_arguments).";
  const errors = GA_KEYS.map(key => fields[key]).filter((text): text is string => text !== null);
  if (errors.length) return { ok: false, ga: null, fields, errors };
  return { ok: true, ga: values as LigandGaParameters, fields: fields as Record<LigandGaKey, null>, errors: [] };
}

/** The job `timeout_s` the screen always sends. */
export function gaTimeoutS(totalS: number): number { return totalS + FINISH_MARGIN_S; }

/**
 * Advice before the preflight (input arithmetic only, no science value): the docking cap times the per-docking
 * limit is longer than the GA time limit, so the run may stop at the time limit. null when it fits.
 */
export function gaTimeAdvice(ga: Pick<LigandGaParameters, "max_new_dockings" | "total_s">): string | null {
  const longest = ga.max_new_dockings * PER_CANDIDATE_S;
  if (longest <= ga.total_s) return null;
  return `끝까지 못 갈 수 있음: 새 도킹 상한 ${ga.max_new_dockings}건 × ${PER_CANDIDATE_S}초 = ${longest}초가 GA 전체 ` +
    `시간 상한 ${ga.total_s}초보다 깁니다. 시간 상한을 늘리거나 새 도킹 상한을 줄일 수 있습니다.`;
}

/** [label, value] lines of the effective parameters (every key, defaults included) and the job time limit. */
export function gaParameterLines(ga: LigandGaParameters): [string, string][] {
  return [...GA_KEYS.map((key): [string, string] => [GA_LABELS[key][0],
    `${plainNumber(ga[key])}${GA_LABELS[key][1] ? ` ${GA_LABELS[key][1]}` : ""}`]),
  ["작업 시간 한도", `${gaTimeoutS(ga.total_s)}초 (GA 전체 시간 상한 + 마무리 ${FINISH_MARGIN_S}초)`]];
}

// ---- form and job arguments ----

/** The M18 form fields (ligand source fixed to the candidate source, mode fixed to free) plus the GA choices. */
export interface GaForm extends DockingForm { filter: LigandFilterSpec; ga: GaInput }

export function emptyFilterSpec(): LigandFilterSpec { return { ranges: {}, pains_exclude: false }; }

export function initialGaForm(): GaForm {
  return { ...initialDockingForm(), ligandSource: "candidate", mode: "free", filter: emptyFilterSpec(),
    ga: initialGaInput() };
}

/** The M18 edit rules (`patchDockingForm`); the source stays the candidate source and the mode stays free. */
export function patchGaForm(form: GaForm, patch: Partial<GaForm>): GaForm {
  const next = patchDockingForm(form, { ...patch, ligandSource: "candidate", mode: "free" });
  return { ...next, ligandSource: "candidate", mode: "free", candidateId: null, filter: patch.filter ?? form.filter,
    ga: patch.ga ?? form.ga };
}

/** Shape-only stand-in candidate id for the shared M18 check (= backend `PLACEHOLDER_ID`; never sent). */
const POOL_STAND_IN = "ga_pool";

/**
 * The `qvina_ga_dock_v1` arguments exactly as `ligand_ga_inputs.validate_arguments` accepts them: the M18 receptor,
 * box, parameter and acknowledgement fields checked by `dockingArgs` (free docking, the pool stands in for the
 * candidate), no `ligand` and no `mode` key, the candidate set and parent SDF, the M17 filter spec and every GA key.
 */
export function gaArgs(form: GaForm): ArgsCheck<LigandGaArgs> {
  const shared = dockingArgs({ ...form, ligandSource: "candidate", mode: "free", sdfHandle: null,
    candidateId: POOL_STAND_IN });
  const ga = checkGaInput(form.ga);
  const errors = [...(shared.ok ? [] : shared.errors), ...ga.errors];
  if (errors.length || !shared.ok || !ga.ok) return { ok: false, errors };
  const { ligand, mode: _mode, ...rest } = shared.args;
  if (ligand.source !== "candidate") return { ok: false, errors: ["리간드 출처가 후보 집합이 아닙니다."] };
  return { ok: true, args: { ...rest, candidate_set_handle: ligand.candidate_set_handle,
    parent_sdf_handle: ligand.parent_sdf_handle, filter: form.filter, ga: ga.ga } };
}

/** Identity of one argument set: a preflight answer applies only to the exact arguments it was asked for. */
export function gaArgsKey(args: LigandGaArgs): string { return JSON.stringify(args); }

// ---- reasons, stop reasons, status ----

/** Korean names of the reasons M22 adds; every other code uses the M18 names. */
export const GA_REASON_LABEL: Record<string, string> = {
  ga_pool_too_small: "필터를 통과한 적격 후보 수가 세대당 개체 수보다 적음",
  ga_reuse_too_large: "재사용할 저장 결과의 크기 합이 128 MiB를 넘음",
  ga_limit_raise_required: "이 GA에 필요한 예산이 남은 예산보다 큼(한도 증액 승인 필요)",
  candidate_timeout: `개체 도킹 한 건의 시간 상한(${PER_CANDIDATE_S}초) 초과`,
  worker_failed: "작업 프로세스 중단",
};

/** "한국어 (code)"; M18 codes keep their M18 names; unknown codes are shown as is. */
export function gaReasonText(code: string): string {
  const label = Object.prototype.hasOwnProperty.call(GA_REASON_LABEL, code) ? GA_REASON_LABEL[code] : undefined;
  return label ? `${label} (${code})` : dockingReasonText(code);
}

export const STOP_REASON_LABEL: Record<LigandGaStopReason, string> = {
  generations_complete: "세대 수 상한까지 계산함",
  no_change: "점수 최솟값 변화 없음",
  pool_exhausted: "뽑을 적격 후보가 남지 않음",
  docking_limit: "새 도킹 예약 단위에 닿음",
  time_exhausted: "GA 전체 시간 상한 소진",
  cancelled: "사용자 취소",
  worker_failed: "작업 프로세스 중단",
  resource_exceeded: "자원 한도 초과",
};

export function stopReasonText(reason: LigandGaStopReason | string): string {
  return Object.prototype.hasOwnProperty.call(STOP_REASON_LABEL, reason)
    ? `${STOP_REASON_LABEL[reason as LigandGaStopReason]} (${reason})` : reason;
}

export const STATUS_LABEL: Record<LigandGaStatus, string> = { complete: "완료", partial: "일부 세대만 계산됨" };

/** "완료 (complete) · 종료 이유: …" or "일부 세대만 계산됨 (partial) · 종료 이유: …". */
export function gaStatusText(summary: { status: LigandGaStatus; stop_reason: LigandGaStopReason | null }): string {
  return `${STATUS_LABEL[summary.status]} (${summary.status}) · 종료 이유: ` +
    `${summary.stop_reason ? stopReasonText(summary.stop_reason) : "기록 없음"}`;
}

/**
 * The fixed sentences to show, verbatim: the server's stored ids and texts when given (a loaded detail), else the
 * local copies of G1, G2 when partial and G3 when anything was reused (the spec 4 rule).
 */
export function gaStatementTexts(summary: { status: LigandGaStatus; reused_count: number },
  statements?: readonly LigandGaStatement[] | null): string[] {
  if (statements && statements.length) return statements.map(item => item.text);
  return [GA_STATEMENTS.G1, ...(summary.status === "partial" ? [GA_STATEMENTS.G2] : []),
    ...(summary.reused_count > 0 ? [GA_STATEMENTS.G3] : [])];
}

// ---- preflight and limit approval (server numbers, shown as given) ----

type Pair = { expensive_calls: number; wall_clock_s: number };

function secondsText(value: number): string { return `${decimalHalfUp(value, 1)}초`; }

function pairText(pair: Pair): string {
  return `비싼 계산 ${pair.expensive_calls}단위 · 활동 시간 ${secondsText(pair.wall_clock_s)}`;
}

function hasShortfall(preflight: LigandGaPreflight): boolean {
  return !!preflight.shortfall && (preflight.shortfall.expensive_calls > 0 || preflight.shortfall.wall_clock_s > 0);
}

/** Admitted preflight with a shortfall on either axis, outside dry-run: the explicit approval button is shown. */
export function gaLimitApprovalOffered(preflight: LigandGaPreflight | null, dryRun: boolean): boolean {
  return !!preflight && !dryRun && preflight.admission.admitted && hasShortfall(preflight);
}

/** [label, value] lines of an admitted preflight (empty for a refused one). Every number is the server's. */
export function gaPreflightLines(preflight: LigandGaPreflight): [string, string][] {
  if (!preflight.admission.admitted || !preflight.pool || preflight.reserved_units === null || !preflight.needed ||
      !preflight.shortfall || preflight.max_new_dockings_expected === null) return [];
  const pool = preflight.pool;
  const lines: [string, string][] = [
    ["후보 풀", `${pool.size}개 · 적격 ${pool.eligible_count}개 · 필터 제외 ${pool.filter_excluded_count}개(도킹하지 않음)`],
    ["재사용 가능", `${REUSED_LABEL} 가능 후보 ${preflight.reusable_count ?? 0}개 (과금하지 않음, 새 도킹 상한에 세지 않음)`],
    ["예약 단위", `${preflight.reserved_units}단위`],
    ["예상 최대 새 도킹", `${preflight.max_new_dockings_expected}건`],
    ["예상 시간 상한", secondsText(preflight.needed.wall_clock_s)],
    ["필요", `${pairText(preflight.needed)} (최대)`],
    ["현재 잔여", pairText(preflight.remaining)],
    ["부족분", pairText(preflight.shortfall)],
    ["과금", chargeNote(preflight.reserved_units)],
  ];
  if (preflight.full_run_may_be_partial) lines.push(["시간 상한", PARTIAL_RISK_NOTE]);
  lines.push(["대기", WAIT_NOTE]);
  return lines;
}

/** Refusal text: the closed reason "한국어 (code)" and the server message; the pool numbers of `ga_pool_too_small`
 * come from the server's detail. */
export function gaPreflightRefusalText(preflight: LigandGaPreflight): string {
  const admission = preflight.admission;
  const head = admission.reason_code ? gaReasonText(admission.reason_code) : admission.error ?? "거절";
  const detail = admission.detail ?? {};
  const pool = admission.reason_code === "ga_pool_too_small" && typeof detail.eligible_count === "number" &&
    typeof detail.population_size === "number"
    ? ` · 적격 ${detail.eligible_count}개, 세대당 개체 수 ${detail.population_size}` : "";
  return `${head}${pool}${admission.message ? ` · ${admission.message}` : ""}`;
}

/** Receptor leftovers of a refused preflight (M18 rule), else null. */
export function gaPreflightRefusalList(preflight: LigandGaPreflight): DockingRefusalList | null {
  if (preflight.admission.admitted) return null;
  return dockingRefusalList(preflight.admission.reason_code, preflight.admission.detail);
}

export function gaExistingJobText(existing: { job_id: string; status: string }): string {
  return `같은 입력의 GA 작업이 이미 있습니다 · ${existing.job_id} · ${existing.status}. 시작하면 새 작업을 만들지 않고 그 작업을 ` +
    "다시 표시합니다.";
}

export function gaLimitApprovalText(result: Pick<LigandGaLimitApproval, "raised" | "increase" | "limits_after">): string {
  if (!result.raised) return "이미 충분해 한도를 바꾸지 않았습니다.";
  return `한도를 올렸습니다 · 증가분 ${pairText(result.increase)} · 새 한도 ${pairText(result.limits_after)} ` +
    "(되돌리지 않음, run 끝까지 유지)";
}

// ---- jobs ----

const ACTIVE_STATUSES = ["queued", "claimed", "running"];

export type GaPreflightState = { key: string; value: LigandGaPreflight } | null;

/** One job at a time; start needs an admitted preflight of exactly these arguments without a shortfall (dry-run plans). */
export function gaStartBlockedReason(input: { capability: { available: boolean; reason: string | null;
  reason_code: string | null } | null | undefined; busy: boolean; activeJob: { status: string } | null;
  check: ArgsCheck<LigandGaArgs>; preflight: GaPreflightState; dryRun: boolean }): string | null {
  if (!input.capability?.available) return dockingCapabilityText(input.capability ?? null);
  if (input.busy) return "요청을 처리하는 중입니다.";
  if (input.activeJob && ACTIVE_STATUSES.includes(input.activeJob.status))
    return "진행 중인 작업이 끝난 뒤 시작할 수 있습니다(한 번에 한 작업).";
  if (!input.check.ok) return input.check.errors.join(" ");
  if (!input.preflight || input.preflight.key !== gaArgsKey(input.check.args))
    return "지금 입력으로 \"시작 전 확인 보기\"를 먼저 누르세요.";
  if (!input.preflight.value.admission.admitted) return gaPreflightRefusalText(input.preflight.value);
  if (!input.dryRun && hasShortfall(input.preflight.value))
    return "예산이 부족합니다. 한도를 먼저 올리고 시작 전 확인을 다시 보세요 (ga_limit_raise_required).";
  return null;
}

/** Progress from the stored job record (staged file counts only; no score). */
export function gaProgressText(progress: LigandGaProgress): string {
  return `완료한 세대 ${progress.generations_complete}개(세대 기록 ${progress.generation_records}개) · 평가 시작 ` +
    `${progress.individuals_started}개 · 평가 끝 ${progress.individuals_finished}개 · ${REUSED_LABEL} 예정 ` +
    `${progress.reused_planned}개 · 예약 ${progress.reserved_units}단위`;
}

/**
 * A failed or interrupted job that still published a summary shows the job record status with the summary's own
 * outcome (server values), never a bare failure message.
 */
export function gaJobText(job: { status: string; cancel_requested: boolean;
  failure: Parameters<typeof dockingFailureText>[0];
  ga?: Pick<LigandGaProgress, "summary_handle" | "summary_status" | "summary_stop_reason"> | null } | null,
  approvalPending: boolean): string {
  switch (dockingJobPhase(job, approvalPending)) {
    case "none": return "GA 작업 없음";
    case "saved": return "GA 작업이 저장되었습니다. 시작을 누르면 실제 계산이 실행됩니다.";
    case "awaiting_approval": return "비용이 드는 실제 계산 승인이 필요합니다(run의 첫 비싼 계산). 승인한 뒤 시작을 다시 누르세요.";
    case "running": return `GA 작업 실행 중${job?.cancel_requested ? " · 취소 요청됨" : ""}`;
    case "done": return "GA 작업 끝남";
    case "cancelled": return "GA 작업 취소됨 (평가를 끝낸 개체는 보관, 요약이 있으면 아래 목록에 나옴)";
    default:
      if (job && ["failed", "interrupted"].includes(job.status) && job.ga?.summary_handle && job.ga.summary_status)
        return `GA 작업 끝남 · 작업 기록 ${job.status} · GA 요약 ${gaStatusText({ status: job.ga.summary_status,
          stop_reason: job.ga.summary_stop_reason })}`;
      return job && ["failed", "interrupted"].includes(job.status) ? `GA 작업 실패: ${dockingFailureText(job.failure)}`
        : `GA 작업 실패: 알 수 없는 작업 상태 (${job?.status})`;
  }
}

export function gaApprovalRequired(status: number, approval: { gate: string; tool: string } | undefined): boolean {
  return status === 409 && approval?.gate === "expensive_first_call" && approval.tool === GA_TOOL;
}

/** The GA job of this run that is still queued or running (the latest one), for re-attaching after a remount. */
export function gaActiveJob<T extends { run_id: string; protocol_id: string; status: string }>(jobs: unknown,
  runId: string): T | null {
  if (!Array.isArray(jobs)) return null;
  return (jobs as T[]).filter(job => job && job.run_id === runId && job.protocol_id === GA_PROTOCOL &&
    ACTIVE_STATUSES.includes(job.status)).at(-1) ?? null;
}

export function gaReportMatches(artifact: { manifest: { schema: string; analysis_type: string; result_handle: string } },
  summaryHandle: string): boolean {
  return artifact.manifest.schema === "method_report_manifest@1" && artifact.manifest.analysis_type === "ligand_ga" &&
    artifact.manifest.result_handle === summaryHandle;
}

/** One stored summary in the list (or why it cannot be read). */
export function gaListRowText(row: { published_seq: number; valid: boolean; reason_code: string | null;
  status: LigandGaStatus | null; stop_reason: LigandGaStopReason | null; generations_done: number | null;
  new_dockings_used: number | null; reused_count: number | null }): string {
  if (!row.valid || !row.status || row.generations_done === null || row.new_dockings_used === null ||
      row.reused_count === null)
    return `게시 순번 ${row.published_seq} · 읽을 수 없음: ${gaReasonText(row.reason_code ?? "evidence_invalid")}`;
  return `게시 순번 ${row.published_seq} · 완료한 세대 ${row.generations_done}개 · 새 도킹 ${row.new_dockings_used}건 · ` +
    `${REUSED_LABEL} ${row.reused_count}개 · ${gaStatusText({ status: row.status, stop_reason: row.stop_reason })}`;
}

// ---- results (display only; stored values) ----

export const ORIGIN_LABEL: Record<LigandGaOrigin, string> = { initial: "초기", carried: "이어받음", similar: "유사",
  random: "무작위" };
export const STATE_TEXT: Record<LigandGaState, string> = { scored: "점수 있음", null_result: "빈 과학 결과(모드 0개)",
  failed: "실패" };

export function originText(origin: LigandGaOrigin): string { return ORIGIN_LABEL[origin]; }

export function stateText(state: LigandGaState): string { return `${STATE_TEXT[state]} (${state})`; }

/** "저장된 결과 재사용" | "새 도킹"; a carried individual (null) cites its first evaluation. */
export function evaluationText(evaluation: LigandGaEvaluation | null): string {
  return evaluation === "reused" ? REUSED_LABEL : evaluation === "docked" ? DOCKED_LABEL : CARRIED_EVALUATION_LABEL;
}

/** Score column header with its target (the first mode of each individual's M18 result). */
export function scoreHeaderText(): string { return `${SCORE_COLUMN_LABEL} · ${SCORE_ROW_LABEL}`; }

type IndividualLike = Pick<LigandGaIndividual, "candidate_id" | "state" | "score" | "reason_code" | "result_handle" |
  "origin" | "parent_candidate_id" | "similarity" | "evaluation">;

function hasScore(row: Pick<LigandGaIndividual, "state" | "score">): boolean {
  return row.state === "scored" && typeof row.score === "number";
}

/** Stored score with one decimal for `scored` individuals; empty for every other state (never "0"). */
export function individualScoreText(row: Pick<LigandGaIndividual, "state" | "score">): string {
  return hasScore(row) ? scoreText(row.score as number) : "";
}

export function individualReasonText(row: Pick<LigandGaIndividual, "reason_code">): string {
  return row.reason_code ? gaReasonText(row.reason_code) : "";
}

/** Parent and Morgan Tanimoto of a similar slot (worker record, six decimals as stored); empty otherwise. */
export function lineageText(row: Pick<LigandGaIndividual, "origin" | "parent_candidate_id" | "similarity">): string {
  if (row.origin !== "similar" || row.parent_candidate_id === null) return "";
  const similarity = typeof row.similarity === "number" ? ` · 지문 Tanimoto ${decimalHalfUp(row.similarity, 6)}` : "";
  return `부모 ${row.parent_candidate_id}${similarity}`;
}

/** The individual's stored M18 result opens in the M18 detail; individuals without a result handle have none. */
export function individualDetailHandle(row: Pick<LigandGaIndividual, "result_handle">): string | null {
  return typeof row.result_handle === "string" && row.result_handle.length > 0 ? row.result_handle : null;
}

/** Score values of one generation as stored (min and max only, no difference); no score → the reason. */
export function generationRangeText(generation: Pick<LigandGaGeneration, "min_score" | "max_score">): string {
  if (generation.min_score === null || generation.max_score === null) return "이 세대에 점수 있는 개체 없음";
  return `점수 최솟값 ${scoreText(generation.min_score)} · 점수 최댓값 ${scoreText(generation.max_score)} (kcal/mol)`;
}

export function generationTabText(generation: Pick<LigandGaGeneration, "index" | "complete">): string {
  return `세대 ${generation.index}${generation.complete ? "" : " (중간에 멈춤, 평가를 끝낸 개체만)"}`;
}

/** Table row: the stored individual with its slot position in the generation (display order key). */
export type IndividualRow<T extends IndividualLike = IndividualLike> = T & { position: number };

export function individualRows<T extends IndividualLike>(generation: { individuals: readonly T[] }):
  IndividualRow<T>[] {
  return generation.individuals.map((entry, position) => ({ ...entry, position }));
}

export type IndividualSortKey = "slot" | "candidate" | "score";
export type IndividualSort = { key: IndividualSortKey; direction: "asc" | "desc" } | null;

/**
 * Display order. null = stored slot order. Slot and candidate id sort both ways; the score sort orders `scored`
 * individuals by the stored score, and individuals without a score stay last in slot order whatever the direction,
 * never compared as 0. Ties keep slot order. Returns a new array; the rows themselves are not changed.
 */
export function sortIndividuals<T extends IndividualRow>(rows: readonly T[], sort: IndividualSort): T[] {
  const bySlot = [...rows].sort((a, b) => a.position - b.position);
  if (sort === null || (sort.key === "slot" && sort.direction === "asc")) return bySlot;
  if (sort.key === "slot") return bySlot.reverse();
  const sign = sort.direction === "asc" ? 1 : -1;
  if (sort.key === "candidate")
    return bySlot.sort((a, b) => sign * (a.candidate_id < b.candidate_id ? -1 : a.candidate_id > b.candidate_id ? 1 : 0)
      || a.position - b.position);
  const head = bySlot.filter(row => hasScore(row)), tail = bySlot.filter(row => !hasScore(row));
  return [...head.sort((a, b) => sign * ((a.score as number) - (b.score as number)) || a.position - b.position),
    ...tail];
}

/** Header click: a new column starts ascending; the same column toggles its direction. */
export function nextIndividualSort(current: IndividualSort, key: IndividualSortKey): IndividualSort {
  if (current && current.key === key) return { key, direction: current.direction === "asc" ? "desc" : "asc" };
  return { key, direction: "asc" };
}

export function individualAriaSort(sort: IndividualSort, key: IndividualSortKey):
  "ascending" | "descending" | "none" {
  return sort && sort.key === key ? sort.direction === "asc" ? "ascending" : "descending" : "none";
}

/** [label, value] lines of a stored summary (server values). */
export function gaSummaryLines(summary: { status: LigandGaStatus; stop_reason: LigandGaStopReason;
  generations_done: number; new_dockings_used: number; reused_count: number; reserved_units: number;
  pool: { size: number; eligible_count: number; filter_excluded_count: number } }): [string, string][] {
  return [
    ["상태", gaStatusText(summary)],
    ["완료한 세대", `${summary.generations_done}개`],
    ["새 도킹", `${summary.new_dockings_used}건 (예약 ${summary.reserved_units}단위)`],
    [REUSED_LABEL, `${summary.reused_count}개 (과금하지 않음)`],
    ["후보 풀", `${summary.pool.size}개 · 적격 ${summary.pool.eligible_count}개 · 필터 제외 ` +
      `${summary.pool.filter_excluded_count}개`],
  ];
}

// ---- wording check ----

const GA_SENTENCES: readonly string[] = Object.values(GA_STATEMENTS);
const GA_FORBIDDEN = /승자|추천|평균\s*비교|부분\s*완료|\bwinner|recommend/gi;

/**
 * Forbidden words in screen text, line by line: a line equal to a G sentence or an M18 limitation is exempt; any
 * other line goes through the M18 check (`dockingForbiddenWords`: rank, best, improvement, binding strength,
 * affinity outside the exact score names) and the GA words (winner, recommendation, average comparison, and
 * "부분 완료" which the GA screen does not use).
 */
export function gaForbiddenWords(text: string): string[] {
  return text.split("\n").flatMap(line => GA_SENTENCES.includes(line) || DOCKING_LIMITATIONS.includes(line) ? []
    : [...dockingForbiddenWords(line), ...[...line.split(SCORE_LABEL).join("").matchAll(GA_FORBIDDEN)]
      .map(match => match[0])]);
}
