/**
 * Pure logic of the M23 "서열 GA 설계" area of the 단백질 공학 tab (`.dryforge/spec.md` sections 2–5, 7, 9, 10).
 *
 * Every score, potential, count, budget figure, combination-space size and sentence shown comes from the server (the
 * stored `sequence_ga_result@1`, its individuals' `mutation_set_model@1` and `docking_result@1`, the preflight read or
 * the job record); this module never computes a score, a potential, a difference, an aggregate or the space size. It
 * holds the GA parameter definitions (same ranges and defaults as `backend/mw/sequence_ga_constants.py`, tests
 * compare), the per-field validator and cross rules, the exact job-argument shape (the M18 ligand / box / value /
 * acknowledgement rules of `lib/docking.ts` with the M21 receptor-source limits of `lib/mutation-model.ts`: 3D SDF
 * only, free docking only, no instance-range box, no receptor key), the preflight / progress / result / individual
 * view models, the display order of the individuals table (a display order only: rows without a score stay last and
 * are never treated as 0), the separate wild-type reference row and the wording ("한국어 (code)"). GA is a search over
 * the combination space; nothing here calls an individual, a mutation or a score good, and nothing sets an individual
 * beside the wild-type reference row.
 */
import type { ExactResidueRef, MutationCandidateSetListRow, MutationModelSide, SequenceGaArgs, SequenceGaEditOp,
  SequenceGaEvaluation, SequenceGaGeneration, SequenceGaIndividual, SequenceGaIndividualRead, SequenceGaKey,
  SequenceGaLimitApproval, SequenceGaMutation, SequenceGaOrigin, SequenceGaParameters, SequenceGaPreflight,
  SequenceGaProgress, SequenceGaReference, SequenceGaSpace, SequenceGaState, SequenceGaStatement, SequenceGaStatus,
  SequenceGaStopReason } from "./contracts";
import { type ArgsCheck, DOCKING_LIMITATIONS, DOCKING_REASON_LABEL, RECEPTOR_SIDE_LABEL, SCORE_COLUMN_LABEL, SCORE_LABEL,
  dockingCapabilityText, dockingConditionArgs, dockingJobPhase, scoreText } from "./docking";
import { CONFIRMATION_LABEL, ENERGY_LABEL, MODEL_REASON_LABEL, type PairDockingForm, disulfideText, energyText,
  initialPairDockingForm, pairBoxSourceDisabledReason, patchPairDockingForm, residueFieldsText, residueShortText,
  variantText } from "./mutation-model";
import { decimalHalfUp } from "./site-annotation";

export { CONFIRMATION_LABEL, SCORE_COLUMN_LABEL, SCORE_LABEL };

// ---- closed sets, ranges and limits (same values and order as backend/mw/sequence_ga_constants.py; tests compare) ----
export const GA_PROTOCOL = "sequence_ga_dock_v1";
export const GA_TOOL = "sequence_ga_design";
export const REPORT_TYPE = "sequence_ga";
/** The wild-type reference row is found by this key only (never an individual). */
export const REFERENCE_KEY = "wild_type";
/** Individual key = candidate indices ascending joined by "-" (e.g. "12-57-203"). */
export const KEY_SEPARATOR = "-";
export const SELECTION_POLICY = "protein_only";
export const HYDROGEN_POLICY = "rebuild_pH7";
export const GA_KEYS: readonly SequenceGaKey[] = ["seed", "population_size", "generations", "elite_count",
  "tournament_size", "crossover_fraction", "random_fraction", "max_mutations", "patience", "max_new_evaluations",
  "total_s"];
/** [min, max, default]; `seed` has no default (required). `max_new_evaluations` min is also `population_size`. */
export const GA_RANGES: Record<SequenceGaKey, readonly [number, number, number | null]> = {
  seed: [0, 2147483647, null],
  population_size: [4, 16, 8],
  generations: [1, 8, 5],
  elite_count: [0, 4, 2],
  tournament_size: [2, 4, 2],
  crossover_fraction: [0.0, 1.0, 0.5],
  random_fraction: [0.0, 0.5, 0.2],
  max_mutations: [1, 4, 3],
  patience: [1, 8, 3],
  max_new_evaluations: [4, 64, 32],
  total_s: [600, 14400, 7200],
};
export const GA_FLOAT_KEYS: readonly SequenceGaKey[] = ["crossover_fraction", "random_fraction"];
/** `population_size - elite_count >= 2`. */
export const MIN_NEW_SLOTS = 2;
/** The job `timeout_s` is always `ga.total_s + FINISH_MARGIN_S` (the screen sends it; the server sets no default). */
export const FINISH_MARGIN_S = 600;
export const TOTAL_S_MAX = 14400;
export const TIMEOUT_MAX_S = 15000;
export const MODEL_STEP_S = 240;
export const DOCKING_STEP_S = 300;
export const SECONDS_PER_UNIT = 270;
export const UNITS_PER_EVALUATION = 2;
export const CONSECUTIVE_FAILURE_LIMIT = 5;
export const M18_HEAVY_ATOM_ESTIMATE = 4890;

/** Admission reasons (spec 2), in the server's check order. */
export const ADMISSION_REASONS = ["invalid_job_arguments", "confirmation_missing", "acknowledgement_missing",
  "candidate_set_invalid", "structure_invalid", "ligand_record_count", "ligand_unparseable",
  "ligand_multiple_fragments", "ligand_element_not_allowed", "ligand_too_many_atoms", "ligand_not_3d", "box_invalid",
  "box_too_large", "process_identity_unavailable", "openmm_unavailable", "pdbfixer_unavailable", "worker_missing",
  "engine_missing", "engine_hash_mismatch", "handshake_failed", "version_mismatch", "openmm_preflight_failed",
  "residue_mismatch", "box_no_receptor_atoms", "ga_space_too_small", "staged_input_bytes",
  "ga_limit_raise_required"] as const;
export const STOP_REASONS: readonly SequenceGaStopReason[] = ["generations_complete", "no_change", "space_exhausted",
  "evaluation_limit", "time_exhausted", "cancelled", "worker_failed", "resource_exceeded", "reference_failed",
  "repeated_failure"];
export const GA_STATUSES: readonly SequenceGaStatus[] = ["complete", "partial"];
export const STATUS_BY_STOP_REASON: Record<SequenceGaStopReason, SequenceGaStatus> = {
  generations_complete: "complete", no_change: "complete", space_exhausted: "complete", evaluation_limit: "partial",
  time_exhausted: "partial", cancelled: "partial", worker_failed: "partial", resource_exceeded: "partial",
  reference_failed: "partial", repeated_failure: "partial",
};
export const ORIGINS: readonly SequenceGaOrigin[] = ["initial", "carried", "crossover", "edit", "random"];
export const EDIT_OPERATIONS: readonly SequenceGaEditOp[] = ["add", "change", "move", "remove"];
export const EVALUATIONS: readonly SequenceGaEvaluation[] = ["reused", "computed"];
export const STATES: readonly SequenceGaState[] = ["scored", "null_result", "failed"];
/** M21 modeling failures; a failed individual's reason is one of these, an M18 worker reason or an extra reason. */
export const MODEL_FAILURE_REASONS = ["mutation_modeling_failed", "unexpected_atoms_added", "coordinates_changed",
  "topology_unsupported", "energy_invalid", "engine_failed", "resource_exceeded"] as const;
export const FAILED_EXTRA_REASONS = ["model_timeout", "docking_timeout", "worker_failed"] as const;

// ---- fixed wording ----
/** Score target of each individual: the first mode of its M18 result (= M19 `SCORE_ROW_LABELS.free`). */
export const SCORE_ROW_LABEL = "모드 1(엔진 출력 순서)";
/** spec 4, verbatim and in order. The summary stores the ids; the screen shows the server's texts. */
export const STATEMENTS = {
  S1: "서열 GA는 변이 조합 공간에서 어떤 조합을 모델링·도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 " +
    "순위나 추천이 아니다. 교차·편집의 부모 선택은 작업 모듈 기록이며 서버가 다시 계산하지 않았고 변이 목록의 " +
    "부모–자식 관계만 검증했다.",
  S2: "이 실행은 시간·평가 상한·취소·기준 행 실패·연속 실패 등으로 일부만 계산되었다. 계산하지 않은 개체는 점수가 " +
    "없으며 0이 아니고, 한도 도달로 멈춘 실행은 같은 설정으로 다시 해도 같은 경로를 보장하지 않는다.",
  S3: "재사용한 개체는 같은 후보 집합·구조·리간드·상자·seed·값으로 이전에 저장된 모델링·도킹 결과를 가져온 것이며, " +
    "저장된 결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있다.",
  S4: "점수는 각 개체의 변이 구조(PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 단백질만의 " +
    "모델)에 사용자가 준 리간드 좌표를 그대로 두고 자유 도킹한 qvina 점수이며, 변이의 효과나 결합 친화도를 뜻하지 " +
    "않는다.",
  S5: "OpenMM 전위는 각 구조의 Amber14-all + GBn2 값(kJ/mol)이며 서열이 다른 구조의 값은 서로 비교할 수 없고 " +
    "ΔΔG·안정성이 아니다.",
  S6: "여러 곳 변이는 구조 순서대로 한 곳씩 PDBFixer로 연속 적용한 모델이며(앞 단계에서 놓은 원자 좌표는 다음 단계 " +
    "전에 소수 넷째 자리로 반올림했다) 적용 순서와 곁사슬 크기에 따라 모델이 달라질 수 있다. 구조의 충돌·전위는 " +
    "점수나 선택에 쓰지 않았고(전위가 늘거나 유한하지 않은 모델만 실패로 처리), 개체마다 수용체가 다르므로 개체 " +
    "점수를 나란히 두는 것은 같은 수용체 안의 비교가 아니며(개체 도킹 결과의 M18 둘째 한계 문장이 말하는 조건과 " +
    "다르다) 순위나 '더 잘 결합'을 뜻하지 않는다.",
} as const;
/**
 * Model limitation sentences of `mutation_set_model@1`, verbatim, in the stored order L1, L3, SL5, L6 (L1, L3 always;
 * SL5 with protonation differences; L6 with a new disulfide). The screen shows the stored `limitations`; this copy
 * only exempts them from the wording check and flags a stored sentence that is not one of them.
 */
export const MODEL_LIMITATIONS: readonly string[] = [
  "변이 구조는 PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 모델이며 회전이성질체 탐색과 수렴을 주장하지 않는다.",
  "모델은 단백질만 포함하며 리간드·금속 이온·물·보조인자는 제외했다.",
  "변이한 잔기 밖에서 히스티딘·시스테인 양성자 상태가 야생형 기준 구조와 다르게 지정되었으므로 두 구조의 차이는 " +
    "지정한 변이만이 아니다.",
  "변이형에는 야생형 기준에 없는 이황화 결합이 거리 기준으로 만들어졌다.",
];

export const AREA_TITLE = "서열 GA 설계";
export const REFERENCE_TITLE = "야생형 기준(참고)";
export const REUSED_LABEL = "재사용";
export const COMPUTED_LABEL = "계산";
export const CARRIED_EVALUATION_LABEL = "다시 평가하지 않음(이전 세대 결과 인용)";
export const LIMIT_RAISE_LABEL = "이 서열 GA에 필요한 만큼 한도를 올림";
export const SEED_NOTE = "GA seed는 조합 선택 순서의 난수이고, 도킹 값의 seed(평가 seed)는 개체 모델링과 qvina 도킹이 " +
  "함께 쓰는 난수입니다. 두 값은 따로 입력하며 같은 숫자여도 됩니다.";
export const MODE_NOTE = "서열 GA의 개체 도킹은 자유 도킹으로 고정됩니다(코어 고정 없음).";
export const MODEL_NOTE = "개체마다 변이 구조를 단백질만으로 모델링합니다(PDBFixer 1.12.0이 변이 잔기의 곁사슬을 놓고, " +
  "수소는 pH 7.0에서 다시 만든 뒤 OpenMM Amber14-all + GBn2로 최대 50회 최소화). 그 구조에 가져온 3D SDF 리간드를 " +
  "같은 상자·seed·값으로 자유 도킹합니다.";
export const SDF_ONLY_REASON = "서열 GA는 가져온 3D SDF 리간드만 씁니다. 개체 도킹 결과의 한계 문장 \"리간드 좌표는 " +
  "사용자가 준 SDF 그대로\"가 M17 후보(RDKit이 만든 좌표)에는 맞지 않기 때문입니다.";
export const CONFIRMATION_ERROR = "protein_only와 rebuild_pH7 확인을 모두 체크하세요 (confirmation_missing).";
export const BUDGET_NOTE = `새 평가 1건 = 비싼 계산 ${UNITS_PER_EVALUATION}단위(모델링 1 + 도킹 1)입니다. 시작 전에 예약 ` +
  "단위를 한 번에 예약하고 중간에 멈추거나 재사용이 있어도 돌려받지 않습니다. 재사용 개체는 단위를 쓰지 않습니다.";
/** Shown when the server says `full_run_may_be_partial` (reserved_units × 270 s > total_s). */
export const PARTIAL_RISK_NOTE = `끝까지 못 갈 수 있음: 예약 단위 × ${SECONDS_PER_UNIT}초가 GA 전체 시간 상한보다 깁니다. ` +
  "시간 상한에 닿으면 그때까지 평가한 개체만 남습니다.";
export const WAIT_NOTE = "서열 GA가 도는 동안 이 run의 다른 계산·보고서 호출과 다른 비싼 작업이 기다립니다.";
export const ORDER_NOTE = "표의 정렬은 표시 순서일 뿐입니다. 점수 없는 개체는 0이 아니며 늘 끝에 둡니다.";
export const REFERENCE_NOTE = "야생형 기준 행은 값만 보이는 참고 행입니다. 개체 표와 함께 정렬하지 않고 선택·종료 판단에 " +
  "쓰지 않습니다.";
export const REFERENCE_REUSED_TEXT = "저장된 결과를 재사용합니다(야생형 기준 행의 2단위는 그대로 예약·소진되며 돌려받지 않음).";
export const REFERENCE_NEW_TEXT = "새로 평가합니다(모델링 + 도킹, 2단위).";
export const NO_RUN_REASON = "run이 없습니다. 구조 분석 탭에서 run을 먼저 고르세요.";
export const CAPABILITY_REASON = "서열 GA 설계 기능을 사용할 수 없습니다.";
export const NO_CANDIDATE_SET_REASON = "이 run에 읽을 수 있는 변이 후보 집합이 없습니다. 위 변이 후보 영역에서 먼저 " +
  "만드세요.";
export const PROTONATION_DIFFERENCE_HEADING = "변이한 잔기 밖에서 야생형 기준 구조와 양성자 상태가 다르게 지정된 " +
  "히스티딘·시스테인";
export const PROTONATION_DIFFERENCE_HEADERS = ["잔기", "잔기 7필드", "야생형 기준 구조", "이 구조"] as const;

export function chargeNote(units: number): string {
  return `시작하면 ${units}단위가 예약·소진되고 중간에 멈추거나 재사용이 있어도 돌려받지 않음`;
}

/** A stored non-negative integer with thousands separators (display only). */
function countText(value: number): string { return String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ","); }

// ---- parameter definitions ----

export interface GaParameterDef { key: SequenceGaKey; label: string; unit: string; min: number; max: number;
  default: number | null; integer: boolean }

const GA_LABELS: Record<SequenceGaKey, [string, string]> = {
  seed: ["GA seed(조합 선택 난수)", ""],
  population_size: ["세대당 개체 수", "개"],
  generations: ["세대 수 상한(첫 세대 = 세대 1)", "세대"],
  elite_count: ["다음 세대로 이어받는 개체 수", "개"],
  tournament_size: ["부모 선택 토너먼트 크기", "개"],
  crossover_fraction: ["무작위가 아닌 새 자리 중 교차 비율(나머지는 편집)", ""],
  random_fraction: ["새 자리 중 무작위 조합 비율", ""],
  max_mutations: ["한 개체의 동시 변이 수 상한", "개"],
  patience: ["점수 최솟값이 내려가지 않는 연속 세대 수(이만큼이면 중단)", "세대"],
  max_new_evaluations: ["새 평가(모델링 + 도킹) 건수 상한(재사용은 세지 않음)", "건"],
  total_s: ["GA 전체 시간 상한(준비·야생형 기준 행 포함)", "초"],
};

export const GA_PARAMETERS: readonly GaParameterDef[] = GA_KEYS.map(key => ({ key, label: GA_LABELS[key][0],
  unit: GA_LABELS[key][1], min: GA_RANGES[key][0], max: GA_RANGES[key][1], default: GA_RANGES[key][2],
  integer: !GA_FLOAT_KEYS.includes(key) }));

function plainNumber(value: number): string { return String(value); }

/** "4–16 개 · 기본 8"; seed "0–2147483647 · 기본 없음(필수)"; max_new_evaluations min is the population size. */
export function gaRangeText(key: SequenceGaKey): string {
  const [low, high, fallback] = GA_RANGES[key];
  const unit = GA_LABELS[key][1];
  const lowText = key === "max_new_evaluations" ? "세대당 개체 수" : plainNumber(low);
  return `${lowText}–${plainNumber(high)}${unit ? ` ${unit}` : ""} · 기본 ${fallback === null ? "없음(필수)" :
    plainNumber(fallback)}`;
}

/** Inputs as typed (strings, trimmed before checking). */
export type GaInput = Record<SequenceGaKey, string>;

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

function parseField(key: SequenceGaKey, text: string): number | null {
  const trimmed = text.trim();
  const [low, high] = GA_RANGES[key];
  const value = Number(trimmed);
  if (GA_FLOAT_KEYS.includes(key))
    return NUMBER_RE.test(trimmed) && Number.isFinite(value) && value >= low && value <= high ? value + 0 : null;
  return INT_RE.test(trimmed) && Number.isSafeInteger(value) && value >= low && value <= high ? value : null;
}

function fieldError(key: SequenceGaKey): string {
  const [low, high] = GA_RANGES[key];
  const kind = GA_FLOAT_KEYS.includes(key) ? "숫자" : "정수";
  const required = key === "seed" ? "(필수)" : "";
  return `${GA_LABELS[key][0]}: ${plainNumber(low)}–${plainNumber(high)} 사이의 ${kind}를 입력하세요${required} ` +
    "(invalid_job_arguments).";
}

export type GaCheck = { ok: true; ga: SequenceGaParameters; fields: Record<SequenceGaKey, null>; errors: [] } |
  { ok: false; ga: null; fields: Record<SequenceGaKey, string | null>; errors: string[] };

/**
 * Per-field errors (format and range of the spec 2 table) and the cross rules: `population_size - elite_count >= 2`
 * (shown at `elite_count`) and `max_new_evaluations >= population_size` (shown at `max_new_evaluations`). The server
 * checks everything again; these checks keep an impossible request from being sent and show why.
 */
export function checkGaInput(input: GaInput): GaCheck {
  const fields = Object.fromEntries(GA_KEYS.map(key => [key, null])) as Record<SequenceGaKey, string | null>;
  const values: Partial<SequenceGaParameters> = {};
  for (const key of GA_KEYS) {
    const value = parseField(key, input[key] ?? "");
    if (value === null) fields[key] = fieldError(key);
    else values[key] = value;
  }
  const { population_size: population, elite_count: elite, max_new_evaluations: maxNew } = values;
  if (fields.elite_count === null && population !== undefined && elite !== undefined &&
      population - elite < MIN_NEW_SLOTS)
    fields.elite_count = `${GA_LABELS.elite_count[0]}: 세대당 개체 수 − 이어받는 개체 수가 ${MIN_NEW_SLOTS} 이상이어야 ` +
      "합니다 (invalid_job_arguments).";
  if (fields.max_new_evaluations === null && population !== undefined && maxNew !== undefined && maxNew < population)
    fields.max_new_evaluations = `${GA_LABELS.max_new_evaluations[0]}: 세대당 개체 수(${population}) 이상이어야 ` +
      "합니다 (invalid_job_arguments).";
  const errors = GA_KEYS.map(key => fields[key]).filter((text): text is string => text !== null);
  if (errors.length) return { ok: false, ga: null, fields, errors };
  return { ok: true, ga: values as SequenceGaParameters, fields: fields as Record<SequenceGaKey, null>, errors: [] };
}

/** The job `timeout_s` the screen always sends. */
export function gaTimeoutS(totalS: number): number { return totalS + FINISH_MARGIN_S; }

/** [label, value] lines of the effective parameters (every key, defaults included) and the job time limit. */
export function gaParameterLines(ga: SequenceGaParameters): [string, string][] {
  return [...GA_KEYS.map((key): [string, string] => [GA_LABELS[key][0],
    `${plainNumber(ga[key])}${GA_LABELS[key][1] ? ` ${GA_LABELS[key][1]}` : ""}`]),
  ["작업 시간 한도", `${gaTimeoutS(ga.total_s)}초 (GA 전체 시간 상한 + 마무리 ${FINISH_MARGIN_S}초)`]];
}

// ---- form and job arguments ----

/** The M18 condition fields (3D SDF ligand, free docking) plus the M20 candidate set, the two literals and GA. */
export interface GaForm extends PairDockingForm { candidateSet: string | null; selectionConfirmed: boolean;
  hydrogenConfirmed: boolean; ga: GaInput }

/** Nothing chosen: no candidate set, SDF or box, confirmations unchecked, GA defaults with an empty GA seed. */
export function initialGaForm(): GaForm {
  return { ...initialPairDockingForm(), ligandSource: "sdf", mode: "free", candidateSet: null,
    selectionConfirmed: false, hydrogenConfirmed: false, ga: initialGaInput() };
}

/** The M21 edit rules (`patchPairDockingForm`: no instance-range box); the ligand stays the 3D SDF, the mode free. */
export function patchGaForm(form: GaForm, patch: Partial<GaForm>): GaForm {
  const next = patchPairDockingForm(form, { ...patch, ligandSource: "sdf", mode: "free" });
  return { ...next, ligandSource: "sdf", mode: "free",
    candidateSet: "candidateSet" in patch ? patch.candidateSet ?? null : form.candidateSet,
    selectionConfirmed: patch.selectionConfirmed ?? form.selectionConfirmed,
    hydrogenConfirmed: patch.hydrogenConfirmed ?? form.hydrogenConfirmed, ga: patch.ga ?? form.ga };
}

/** Why a box source cannot be chosen (null = usable): a protein-only model has no instance to remove. */
export function boxSourceDisabledReason(source: string): string | null { return pairBoxSourceDisabledReason(source); }

/** Why a ligand source cannot be chosen (null = usable; only the 3D SDF is). */
export function ligandSourceDisabledReason(source: string): string | null {
  return source === "sdf" ? null : SDF_ONLY_REASON;
}

/**
 * The `sequence_ga_dock_v1` arguments exactly as `sequence_ga_inputs.validate_arguments` accepts them: the M20
 * candidate set, the 3D SDF ligand, the M18 box / free-docking values / acknowledgements checked by
 * `dockingConditionArgs`, the two literal policies and every GA key; no `mode`, receptor or filter key. Every reason
 * the request is blocked is listed; nothing is chosen or confirmed automatically.
 */
export function gaArgs(form: GaForm): ArgsCheck<SequenceGaArgs> {
  const errors: string[] = [];
  if (!form.candidateSet) errors.push("변이 후보 집합을 고르세요(자동으로 고르지 않음).");
  const condition = dockingConditionArgs({ ...form, ligandSource: "sdf", mode: "free" },
    form.boxSource === null ? null : boxSourceDisabledReason(form.boxSource));
  if (!condition.ok) errors.push(...condition.errors);
  if (!form.selectionConfirmed || !form.hydrogenConfirmed) errors.push(CONFIRMATION_ERROR);
  const ga = checkGaInput(form.ga);
  errors.push(...ga.errors);
  if (errors.length || !form.candidateSet || !condition.ok || !ga.ok) return { ok: false, errors };
  const { ligand, box: given, parameters, acknowledgement } = condition.args;
  const box: SequenceGaArgs["box"] | null = given.source === "manual" ? given
    : given.source === "ligand_range" ? { source: "ligand_range", margin_A: given.margin_A } : null;
  if (ligand.source !== "sdf" || box === null) return { ok: false, errors: [`${SDF_ONLY_REASON} (box_invalid)`] };
  return { ok: true, args: { candidate_set: form.candidateSet, ligand: { source: "sdf", sdf_handle: ligand.sdf_handle },
    box, parameters: { seed: parameters.seed, exhaustiveness: parameters.exhaustiveness,
      num_modes: parameters.num_modes, energy_range: parameters.energy_range },
    selection_policy: SELECTION_POLICY, hydrogen_policy: HYDROGEN_POLICY, acknowledgement, ga: ga.ga } };
}

/** Identity of one argument set: a preflight answer applies only to the exact arguments it was asked for. */
export function gaArgsKey(args: SequenceGaArgs): string { return JSON.stringify(args); }

// ---- candidate sets and availability (server values; nothing preselected) ----

export interface CandidateSetOption { handle: string; selectable: boolean; text: string }

/** The run's M20 candidate sets in the server's order; a set that does not validate is listed but not selectable. */
export function candidateSetOptions(rows: readonly Pick<MutationCandidateSetListRow, "handle" | "created_seq" | "valid" |
  "counts">[]): CandidateSetOption[] {
  return rows.map(row => row.valid && row.counts
    ? { handle: row.handle, selectable: true, text: `생성 순번 ${row.created_seq} · 후보 위치 ` +
      `${countText(row.counts.candidate_positions)}개 · 후보 ${countText(row.counts.candidates)}개` }
    : { handle: row.handle, selectable: false,
      text: `생성 순번 ${row.created_seq} · 읽을 수 없음: ${gaReasonText("evidence_invalid")}` });
}

/**
 * Why the area shows a reason only (no numbers, no controls), or null. `capability` null = absent;
 * `candidateSets` undefined = not read yet (no reason from it).
 */
export function gaUnavailableReason(input: { runId: string | null; capability: { available: boolean;
  reason: string | null; reason_code: string | null } | null | undefined;
  candidateSets?: readonly { valid: boolean }[] | null }): string | null {
  if (input.runId === null) return NO_RUN_REASON;
  if (!input.capability) return CAPABILITY_REASON;
  if (!input.capability.available) return dockingCapabilityText(input.capability);
  if (Array.isArray(input.candidateSets) && !input.candidateSets.some(row => row.valid)) return NO_CANDIDATE_SET_REASON;
  return null;
}

// ---- reasons, stop reasons, status ----

/** Korean names of the codes M23 adds or names apart; every other code uses the M21 then the M18 names. */
export const GA_REASON_LABEL: Record<string, string> = {
  ga_space_too_small: "조합 공간의 조합 수가 세대당 개체 수보다 적음",
  staged_input_bytes: "스테이징 입력이 16 MiB를 넘음",
  ga_limit_raise_required: "이 서열 GA에 필요한 예산이 남은 예산보다 큼(한도 증액 승인 필요)",
  model_timeout: `개체 모델링 시간 상한(${MODEL_STEP_S}초) 초과`,
  docking_timeout: `개체 도킹 시간 상한(${DOCKING_STEP_S}초, 수용체 준비 포함) 초과`,
  worker_failed: "작업 프로세스 중단",
  engine_failed: "엔진 실행 실패(OpenMM 또는 qvina)",
  resource_exceeded: "크기 상한 초과",
};

const own = (table: Record<string, string>, code: string) =>
  Object.prototype.hasOwnProperty.call(table, code) ? table[code] : undefined;

/** "한국어 (code)"; unknown codes are shown as is. */
export function gaReasonText(code: string): string {
  const label = own(GA_REASON_LABEL, code) ?? own(MODEL_REASON_LABEL, code) ?? own(DOCKING_REASON_LABEL, code);
  return label ? `${label} (${code})` : code;
}

export const STOP_REASON_LABEL: Record<SequenceGaStopReason, string> = {
  generations_complete: "세대 수 상한까지 계산함",
  no_change: "점수 최솟값 변화 없음",
  space_exhausted: "뽑을 조합이 남지 않음(조합 공간 소진)",
  evaluation_limit: "새 평가 예약 건수에 닿음",
  time_exhausted: "GA 전체 시간 상한 소진",
  cancelled: "사용자 취소",
  worker_failed: "작업 프로세스 중단",
  resource_exceeded: "자원 한도 초과(출력 총량 등)",
  reference_failed: "야생형 기준 행 평가 실패(개체를 평가하지 않음)",
  repeated_failure: `개체 평가 연속 ${CONSECUTIVE_FAILURE_LIMIT}건 실패`,
};

export function stopReasonText(reason: SequenceGaStopReason | string): string {
  return Object.prototype.hasOwnProperty.call(STOP_REASON_LABEL, reason)
    ? `${STOP_REASON_LABEL[reason as SequenceGaStopReason]} (${reason})` : reason;
}

export const STATUS_LABEL: Record<SequenceGaStatus, string> = { complete: "완료", partial: "일부만 계산됨" };

/** "완료 (complete) · 종료 이유: …" or "일부만 계산됨 (partial) · 종료 이유: …". */
export function gaStatusText(summary: { status: SequenceGaStatus; stop_reason: SequenceGaStopReason | null }): string {
  return `${STATUS_LABEL[summary.status]} (${summary.status}) · 종료 이유: ` +
    `${summary.stop_reason ? stopReasonText(summary.stop_reason) : "기록 없음"}`;
}

/** The fixed sentences to show: the server's stored texts, verbatim and in the stored order. */
export function gaStatementTexts(statements: readonly SequenceGaStatement[] | null | undefined): string[] {
  return (statements ?? []).map(item => item.text);
}

type FailureLike = { error: string; message: string; reason_code?: string; detail?: unknown } | null;

/** Job failure "한국어 (code) · message". */
export function gaFailureText(failure: FailureLike): string {
  if (!failure) return "이유 없음";
  return `${failure.reason_code ? gaReasonText(failure.reason_code) : failure.error} · ${failure.message}`;
}

// ---- preflight and limit approval (server numbers, shown as given) ----

type Pair = { expensive_calls: number; wall_clock_s: number };

function secondsText(value: number): string { return `${decimalHalfUp(value, 1)}초`; }

function pairText(pair: Pair): string {
  return `비싼 계산 ${pair.expensive_calls}단위 · 활동 시간 ${secondsText(pair.wall_clock_s)}`;
}

function hasShortfall(preflight: SequenceGaPreflight): boolean {
  return !!preflight.shortfall && (preflight.shortfall.expensive_calls > 0 || preflight.shortfall.wall_clock_s > 0);
}

/** The 4,890 warning (the server's flag) with the server's projected heavy-atom count. */
export function heavyAtomWarningText(heavyAtoms: number): string {
  return `투영 단백질 중원자 ${countText(heavyAtoms)}개가 약 ${countText(M18_HEAVY_ATOM_ESTIMATE)}개를 넘습니다. M18 수용체 ` +
    "원자 수 한도(수소 포함 10,000원자) 때문에 야생형 기준 행이 수용체 입력 오류(receptor_invalid)로 실패할 수 " +
    "있습니다. 입장에서 걸러지지 않으며 예약 단위는 돌려받지 않습니다.";
}

/** Admitted preflight with a shortfall on either axis, outside dry-run: the explicit approval button is shown. */
export function gaLimitApprovalOffered(preflight: SequenceGaPreflight | null, dryRun: boolean): boolean {
  return !!preflight && !dryRun && preflight.admission.admitted && hasShortfall(preflight);
}

/**
 * [label, value] lines of an admitted preflight (empty for a refused one). Every number is the server's: the
 * combination-space size and the effective `max_mutations` are never computed here.
 */
export function gaPreflightLines(preflight: SequenceGaPreflight): [string, string][] {
  const { space, ga, needed, shortfall } = preflight;
  if (!preflight.admission.admitted || !space || !ga || !needed || !shortfall || preflight.reserved_units === null ||
      preflight.reserved_evaluations === null || preflight.projection_heavy_atoms === null ||
      preflight.reusable_count === null || preflight.reference_reusable === null) return [];
  const units = preflight.reserved_units;
  const lines: [string, string][] = [
    ["조합 공간", `위치 ${countText(space.positions)}개 · 후보 ${countText(space.candidates)}개 · 조합 ` +
      `${countText(space.size)}개 (서버 계산)`],
    ["유효 동시 변이 수 상한", `${space.effective_max_mutations}개 (입력 ${ga.max_mutations}개, 서버 값)`],
    ["투영 단백질 중원자", `${countText(preflight.projection_heavy_atoms)}개`],
    ["재사용 가능 개체", `${preflight.reusable_count}개 (모델링·도킹 없이 저장된 결과를 가져옴, 과금하지 않음, 새 평가 ` +
      "상한에 세지 않음)"],
    ["야생형 기준 행", preflight.reference_reusable ? REFERENCE_REUSED_TEXT : REFERENCE_NEW_TEXT],
    ["예약 단위", `${units}단위 (새 평가 최대 ${preflight.reserved_evaluations}건 × ${UNITS_PER_EVALUATION}단위 + ` +
      `야생형 기준 행 ${UNITS_PER_EVALUATION}단위)`],
    ["예상 시간 상한", secondsText(needed.wall_clock_s)],
    ["필요", `${pairText(needed)} (최대)`],
    ["현재 잔여", pairText(preflight.remaining)],
    ["부족분", pairText(shortfall)],
    ["과금", chargeNote(units)],
  ];
  if (preflight.full_run_may_be_partial) lines.push(["시간 상한", PARTIAL_RISK_NOTE]);
  if (preflight.heavy_atom_warning) lines.push(["중원자 경고", heavyAtomWarningText(preflight.projection_heavy_atoms)]);
  lines.push(["대기", WAIT_NOTE]);
  return lines;
}

function residueShape(value: unknown): value is ExactResidueRef {
  if (!value || typeof value !== "object") return false;
  const r = value as Record<string, unknown>;
  return Number.isInteger(r.model_number) && typeof r.chain_auth === "string" && Number.isInteger(r.seq_auth) &&
    typeof r.icode === "string" && typeof r.resname === "string";
}

/** Typed detail of a refusal (server values only), or "" when there is none to show. */
function refusalDetailText(code: string | null, detail: Record<string, unknown> | null | undefined): string {
  const d = detail ?? {};
  if (code === "ga_space_too_small" && typeof d.size === "number" && typeof d.population_size === "number")
    return ` · 조합 ${countText(d.size)}개, 세대당 개체 수 ${d.population_size}`;
  if (code === "residue_mismatch" && residueShape(d.residue)) return ` · 위치 ${residueFieldsText(d.residue)}`;
  if (code === "staged_input_bytes" && typeof d.bytes === "number" && typeof d.max_bytes === "number")
    return ` · 스테이징 입력 ${d.bytes} 바이트 · 상한 ${d.max_bytes} 바이트`;
  return "";
}

/**
 * Refused request: "한국어 (reason_code)", the typed detail and the server message. An M7 preflight refusal names M7's
 * own reason code (or that M7 gave none) and its message instead.
 */
export function gaRequestErrorText(error: { message: string; code?: string | null;
  detail?: Record<string, unknown> | null }): string {
  const reason = typeof error.detail?.reason_code === "string" ? error.detail.reason_code : null;
  const head = reason ? gaReasonText(reason) : error.code ? gaReasonText(error.code) : "요청 실패";
  if (reason === "openmm_preflight_failed") {
    const m7 = typeof error.detail?.m7_reason === "string" ? error.detail.m7_reason : "M7 이유 코드 없음";
    const m7Message = typeof error.detail?.m7_message === "string" ? error.detail.m7_message : error.message;
    return `${head} · M7: ${m7} · ${m7Message}`;
  }
  return `${head}${refusalDetailText(reason, error.detail)}${error.message ? ` · ${error.message}` : ""}`;
}

/** Refusal text of a preflight (admission steps 1-8, the environment included). */
export function gaPreflightRefusalText(preflight: SequenceGaPreflight): string {
  const admission = preflight.admission;
  return gaRequestErrorText({ message: admission.message ?? "", code: admission.error,
    detail: { ...(admission.detail ?? {}), reason_code: admission.reason_code ?? admission.detail?.reason_code } });
}

export function gaExistingJobText(existing: { job_id: string; status: string }): string {
  return `같은 입력의 서열 GA 작업이 이미 있습니다 · ${existing.job_id} · ${existing.status}. 시작하면 새 작업을 만들지 ` +
    "않고 그 작업을 다시 표시합니다.";
}

export function gaLimitApprovalText(result: Pick<SequenceGaLimitApproval, "raised" | "increase" | "limits_after">):
  string {
  if (!result.raised) return "이미 충분해 한도를 바꾸지 않았습니다.";
  return `한도를 올렸습니다 · 올린 양 ${pairText(result.increase)} · 새 한도 ${pairText(result.limits_after)} ` +
    "(되돌리지 않음, run 끝까지 유지)";
}

// ---- jobs ----

const ACTIVE_STATUSES = ["queued", "claimed", "running"];

export type GaPreflightState = { key: string; value: SequenceGaPreflight } | null;

/** One GA at a time; start needs an admitted preflight of exactly these arguments without a shortfall (dry-run plans). */
export function gaStartBlockedReason(input: { capability: { available: boolean; reason: string | null;
  reason_code: string | null } | null | undefined; busy: boolean; activeJob: { status: string } | null;
  check: ArgsCheck<SequenceGaArgs>; preflight: GaPreflightState; dryRun: boolean }): string | null {
  if (!input.capability?.available) return input.capability ? dockingCapabilityText(input.capability) : CAPABILITY_REASON;
  if (input.busy) return "요청을 처리하는 중입니다.";
  if (input.activeJob && ACTIVE_STATUSES.includes(input.activeJob.status))
    return "진행 중인 작업이 끝난 뒤 시작할 수 있습니다(한 번에 한 서열 GA).";
  if (!input.check.ok) return input.check.errors.join(" ");
  if (!input.preflight || input.preflight.key !== gaArgsKey(input.check.args))
    return "지금 입력으로 \"시작 전 확인 보기\"를 먼저 누르세요.";
  if (!input.preflight.value.admission.admitted) return gaPreflightRefusalText(input.preflight.value);
  if (!input.dryRun && hasShortfall(input.preflight.value))
    return "예산이 부족합니다. 한도를 먼저 올리고 시작 전 확인을 다시 보세요 (ga_limit_raise_required).";
  return null;
}

/**
 * Progress from the stored job record (staged file counts only; no score): the reference row's status file, then
 * new evaluations (started / status files); reused individuals have no file and are named apart.
 */
export function gaProgressText(progress: SequenceGaProgress): string {
  return `야생형 기준 행 ${progress.reference_recorded ? "기록됨" : "아직 기록 없음"}` +
    `(${progress.reference_reuse_planned ? "재사용 예정" : "새 평가"}) · 완료한 세대 ${progress.generations_complete}개` +
    `(세대 기록 ${progress.generation_records}개) · 새 평가 시작 ${progress.individuals_started}건 · 새 평가 끝 ` +
    `${progress.individuals_finished}건 · 재사용 예정 개체 ${progress.reused_planned}개(파일이 없어 새 평가 수에 들지 ` +
    `않음) · 예약 ${progress.reserved_units}단위`;
}

/**
 * A failed or interrupted job that still published a summary shows the job record status with the summary's own
 * outcome (server values), never a bare failure message.
 */
export function gaJobText(job: { status: string; cancel_requested: boolean; failure: FailureLike;
  sequence_ga?: Pick<SequenceGaProgress, "summary_handle" | "summary_status" | "summary_stop_reason"> | null } | null,
  approvalPending: boolean): string {
  switch (dockingJobPhase(job, approvalPending)) {
    case "none": return "서열 GA 작업 없음";
    case "saved": return "서열 GA 작업이 저장되었습니다. 시작을 누르면 실제 계산이 실행됩니다.";
    case "awaiting_approval": return "비용이 드는 실제 계산 승인이 필요합니다(run의 첫 비싼 계산). 승인한 뒤 시작을 다시 " +
      "누르세요.";
    case "running": return `서열 GA 작업 실행 중${job?.cancel_requested ? " · 취소 요청됨" : ""}`;
    case "done": return "서열 GA 작업 끝남";
    case "cancelled": return "서열 GA 작업 취소됨 (야생형 기준 행이 기록된 뒤였다면 평가를 끝낸 개체와 요약이 아래 목록에 " +
      "나옴)";
    default:
      if (job && ["failed", "interrupted"].includes(job.status) && job.sequence_ga?.summary_handle &&
          job.sequence_ga.summary_status)
        return `서열 GA 작업 끝남 · 작업 기록 ${job.status} · 서열 GA 요약 ${gaStatusText({
          status: job.sequence_ga.summary_status, stop_reason: job.sequence_ga.summary_stop_reason })}`;
      return job && ["failed", "interrupted"].includes(job.status) ? `서열 GA 작업 실패: ${gaFailureText(job.failure)}`
        : `서열 GA 작업 실패: 알 수 없는 작업 상태 (${job?.status})`;
  }
}

export function gaApprovalRequired(status: number, approval: { gate: string; tool: string } | undefined): boolean {
  return status === 409 && approval?.gate === "expensive_first_call" && approval.tool === GA_TOOL;
}

/** The sequence GA job of this run that is still queued or running (the latest one), for re-attaching after a remount. */
export function gaActiveJob<T extends { run_id: string; protocol_id: string; status: string }>(jobs: unknown,
  runId: string): T | null {
  if (!Array.isArray(jobs)) return null;
  return (jobs as T[]).filter(job => job && job.run_id === runId && job.protocol_id === GA_PROTOCOL &&
    ACTIVE_STATUSES.includes(job.status)).at(-1) ?? null;
}

/** The published summary handle of a finished job (null until it is done). */
export function gaJobResult(job: { status: string; artifacts?: { sequence_ga_result?: string } } | null): string | null {
  return job?.status === "done" && typeof job.artifacts?.sequence_ga_result === "string"
    ? job.artifacts.sequence_ga_result : null;
}

export function gaReportMatches(artifact: { manifest: { schema: string; analysis_type: string; result_handle: string } },
  summaryHandle: string): boolean {
  return artifact.manifest.schema === "method_report_manifest@1" && artifact.manifest.analysis_type === REPORT_TYPE &&
    artifact.manifest.result_handle === summaryHandle;
}

/** One stored summary in the list (or why it cannot be read). */
export function gaListRowText(row: { published_seq: number; valid: boolean; reason_code: string | null;
  status: SequenceGaStatus | null; stop_reason: SequenceGaStopReason | null; generations_done: number | null;
  new_evaluations_used: number | null; reused_count: number | null }): string {
  if (!row.valid || !row.status || row.generations_done === null || row.new_evaluations_used === null ||
      row.reused_count === null)
    return `게시 순번 ${row.published_seq} · 읽을 수 없음: ${gaReasonText(row.reason_code ?? "evidence_invalid")}`;
  return `게시 순번 ${row.published_seq} · 완료한 세대 ${row.generations_done}개 · 새 평가 ${row.new_evaluations_used}건 · ` +
    `${REUSED_LABEL} ${row.reused_count}개 · ${gaStatusText({ status: row.status, stop_reason: row.stop_reason })}`;
}

/** [label, value] lines of a stored summary (server values). */
export function gaSummaryLines(summary: { status: SequenceGaStatus; stop_reason: SequenceGaStopReason;
  generations_done: number; new_evaluations_used: number; reused_count: number; reserved_evaluations: number;
  reserved_units: number; space: SequenceGaSpace }): [string, string][] {
  const space = summary.space;
  return [
    ["상태", gaStatusText(summary)],
    ["완료한 세대", `${summary.generations_done}개`],
    ["새 평가", `${summary.new_evaluations_used}건 (예약 ${summary.reserved_evaluations}건 · ${summary.reserved_units}단위)`],
    [REUSED_LABEL, `${summary.reused_count}개 (과금하지 않음)`],
    ["조합 공간", `위치 ${countText(space.positions)}개 · 후보 ${countText(space.candidates)}개 · 조합 ` +
      `${countText(space.size)}개 · 유효 동시 변이 수 상한 ${space.effective_max_mutations}개`],
  ];
}

// ---- late responses (run + summary handle + per-area request number) ----

export const GA_AREAS = ["candidate_sets", "preflight", "limit", "job", "list", "detail", "individual",
  "report"] as const;
export type GaArea = typeof GA_AREAS[number];
export interface GaStamp { runId: string | null; handle: string | null; area: GaArea; seq: number }
export type GaRequestCounters = Record<GaArea, number>;

export function initialGaCounters(): GaRequestCounters {
  return Object.fromEntries(GA_AREAS.map(area => [area, 0])) as GaRequestCounters;
}

/** A new request in one area: its number goes up (older responses of that area become stale); others unchanged. */
export function nextGaRequest(counters: GaRequestCounters, area: GaArea, runId: string | null, handle: string | null):
  { counters: GaRequestCounters; stamp: GaStamp } {
  const next = { ...counters, [area]: counters[area] + 1 };
  return { counters: next, stamp: { runId, handle, area, seq: next[area] } };
}

/** Applied only when run, summary handle, area and that area's request number are all still current. */
export function gaResponseCurrent(captured: GaStamp, live: GaStamp): boolean {
  return captured.runId !== null && captured.runId === live.runId && captured.handle === live.handle &&
    captured.area === live.area && captured.seq === live.seq;
}

/** A created report was saved: announce it while the run is unchanged, even when the late inline display is dropped. */
export function gaReportSavedForRun(captured: GaStamp, liveRunId: string | null): boolean {
  return captured.runId !== null && captured.runId === liveRunId;
}

// ---- results (display only; stored values) ----

export const ORIGIN_LABEL: Record<SequenceGaOrigin, string> = { initial: "초기", carried: "이어받음", crossover: "교차",
  edit: "편집", random: "무작위" };
export const EDIT_OP_LABEL: Record<SequenceGaEditOp, string> = { add: "추가", change: "교체", move: "이동",
  remove: "삭제" };
export const EVALUATION_LABEL: Record<SequenceGaEvaluation, string> = { reused: REUSED_LABEL, computed: COMPUTED_LABEL };
export const STATE_TEXT: Record<SequenceGaState, string> = { scored: "점수 있음", null_result: "빈 과학 결과(모드 0개)",
  failed: "실패" };

/** "초기" … "편집(삭제)": an edit individual names its stored operation. */
export function originText(row: Pick<SequenceGaIndividual, "origin" | "edit_op">): string {
  return row.origin === "edit" && row.edit_op ? `${ORIGIN_LABEL.edit}(${EDIT_OP_LABEL[row.edit_op]})`
    : ORIGIN_LABEL[row.origin];
}

/** Stored parent keys (worker record, not recomputed by the server: S1); empty for other origins. */
export function parentsText(row: Pick<SequenceGaIndividual, "parents">): string {
  return row.parents?.length ? `부모 ${row.parents.join(" · ")}` : "";
}

/** "재사용" | "계산"; a carried individual (null) cites its first evaluation. */
export function evaluationText(evaluation: SequenceGaEvaluation | null): string {
  return evaluation === null ? CARRIED_EVALUATION_LABEL : EVALUATION_LABEL[evaluation];
}

export function stateText(state: SequenceGaState): string { return `${STATE_TEXT[state]} (${state})`; }

/** "ILE A:44A I→W": chain, auth number, insertion code and name kept from the 7 stored fields (display only). */
export function mutationText(mutation: Pick<SequenceGaMutation, "residue" | "from" | "to">): string {
  return `${residueShortText(mutation.residue)} ${mutation.from}→${mutation.to}`;
}

/** One line for the whole individual, in the stored (structure) order. */
export function mutationsText(mutations: readonly Pick<SequenceGaMutation, "residue" | "from" | "to">[]): string {
  return mutations.map(mutationText).join(", ");
}

/** Expanded view: the candidate index and all 7 stored fields of each position (nulls kept). */
export function mutationFieldLines(mutations: readonly SequenceGaMutation[]): string[] {
  return mutations.map(m => `후보 번호 ${m.candidate_index} · ${mutationText(m)} · ${residueFieldsText(m.residue)}`);
}

/** Score column header with its target (the first mode of each individual's M18 result). */
export function scoreHeaderText(): string { return `${SCORE_COLUMN_LABEL} · ${SCORE_ROW_LABEL}`; }

function hasScore(row: { state: SequenceGaState; score: number | null }): boolean {
  return row.state === "scored" && typeof row.score === "number";
}

/** Stored score with one decimal for `scored` rows; empty for every other state (never "0"). */
export function individualScoreText(row: { state: SequenceGaState; score: number | null }): string {
  return hasScore(row) ? scoreText(row.score as number) : "";
}

export function individualReasonText(row: { reason_code: string | null }): string {
  return row.reason_code ? gaReasonText(row.reason_code) : "";
}

/** The row's stored M18 result opens in the M18 detail; rows without one (`detail_available` false) have none. */
export function individualDetailHandle(row: { result_handle: string | null; detail_available: boolean }): string | null {
  return row.detail_available && typeof row.result_handle === "string" && row.result_handle.length > 0
    ? row.result_handle : null;
}

/** Score values of one generation as stored (minimum and maximum only, nothing derived); no score → the reason. */
export function generationRangeText(generation: Pick<SequenceGaGeneration, "min_score" | "max_score">): string {
  if (generation.min_score === null || generation.max_score === null) return "이 세대에 점수 있는 개체 없음";
  return `점수 최솟값 ${scoreText(generation.min_score)} · 점수 최댓값 ${scoreText(generation.max_score)} (kcal/mol)`;
}

export function generationTabText(generation: Pick<SequenceGaGeneration, "index" | "complete">): string {
  return `세대 ${generation.index}${generation.complete ? "" : " (중간에 멈춤, 평가를 끝낸 개체만)"}`;
}

type IndividualLike = Pick<SequenceGaIndividual, "key" | "state" | "score">;

/** Table row: the stored individual with its slot position in the generation (display order key). */
export type IndividualRow<T extends IndividualLike = IndividualLike> = T & { position: number };

export function individualRows<T extends IndividualLike>(generation: { individuals: readonly T[] }): IndividualRow<T>[] {
  return generation.individuals.map((entry, position) => ({ ...entry, position }));
}

export type IndividualSortKey = "slot" | "key" | "score";
export type IndividualSort = { key: IndividualSortKey; direction: "asc" | "desc" } | null;

/** Keys compare as candidate-index integer lists (never as strings). */
function compareKeys(a: string, b: string): number {
  const left = a.split(KEY_SEPARATOR).map(Number), right = b.split(KEY_SEPARATOR).map(Number);
  for (let i = 0; i < Math.min(left.length, right.length); i += 1) if (left[i] !== right[i]) return left[i] - right[i];
  return left.length - right.length;
}

/**
 * Display order (spec 5, 10: rows without a score always last). In every order, null (= stored slot order) included,
 * the `scored` individuals come first, ordered by the key (slot, individual key or stored score, both ways; ties keep
 * slot order), then the individuals without a score in slot order whatever the key or direction, never compared as
 * 0. The wild-type reference row is never part of these rows. Returns a new array; the rows are not changed.
 */
export function sortIndividuals<T extends IndividualRow>(rows: readonly T[], sort: IndividualSort): T[] {
  const bySlot = [...rows].sort((a, b) => a.position - b.position);
  const head = bySlot.filter(row => hasScore(row)), tail = bySlot.filter(row => !hasScore(row));
  if (sort === null || (sort.key === "slot" && sort.direction === "asc")) return [...head, ...tail];
  if (sort.key === "slot") return [...head.reverse(), ...tail];
  const sign = sort.direction === "asc" ? 1 : -1;
  if (sort.key === "key")
    return [...head.sort((a, b) => sign * compareKeys(a.key, b.key) || a.position - b.position), ...tail];
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

export interface ReferenceRowView { title: string; key: string; evaluation: string; state: string; score: string;
  reason: string; detailHandle: string | null; note: string }

/** The wild-type reference row, shown apart from the individuals table ("야생형 기준(참고)"): its stored values only. */
export function referenceRowView(reference: SequenceGaReference & { detail_available: boolean }): ReferenceRowView {
  return { title: REFERENCE_TITLE, key: REFERENCE_KEY, evaluation: evaluationText(reference.evaluation),
    state: stateText(reference.state), score: individualScoreText(reference), reason: individualReasonText(reference),
    detailHandle: individualDetailHandle(reference), note: REFERENCE_NOTE };
}

// ---- individual detail (`sequence_ga_individual@1`: stored model values only) ----

export interface IndividualDetailView {
  title: string; key: string; mutationLines: string[]; appearanceLines: string[]; evaluation: string; state: string;
  score: string; reason: string;
  /** "변이 구조 (mutant)" | "야생형 기준 구조 (wild_type_reference)"; null without a stored model. */
  structureLabel: string | null;
  energyRows: [string, string][];
  /** The server's sentences that travel with the potentials (S5), verbatim; empty without potentials. */
  energyStatements: string[];
  protonationVariantLines: string[];
  protonationDifferenceRows: { residue: string; fields: string; wild_type_reference: string; mutant: string }[];
  /** Shown instead of the rows when there are none (or for the reference structure). */
  protonationDifferenceText: string;
  disulfideText: string; newDisulfideText: string; addedAtomLines: string[]; countLines: [string, string][];
  /** The stored model limitation sentences, verbatim and in order. */
  modelLimitations: readonly string[];
  /** Stored sentences that are not one of the fixed ones (a non-empty answer means the screen must not trust them). */
  unknownLimitations: string[];
  /** The stored mmCIF can be downloaded (`…/structure?key=`). */
  structureAvailable: boolean;
  /** The M18 result handle to open in the M18 detail, or null. */
  m18Handle: string | null;
  /** Why there are no model values (no stored model), or null. */
  missingModelText: string | null;
}

const NOT_APPLICABLE_REFERENCE = "해당 없음(야생형 기준 구조)";

/** PDBFixer-placed heavy atoms grouped by mutated residue (stored order); "0개" is a real count. */
function addedAtomLines(atoms: readonly { residue: ExactResidueRef; atom_name: string; element: string }[]): string[] {
  if (!atoms.length) return ["0개"];
  const groups = new Map<string, { residue: ExactResidueRef; atoms: string[] }>();
  for (const atom of atoms) {
    const id = residueFieldsText(atom.residue);
    const group = groups.get(id) ?? { residue: atom.residue, atoms: [] };
    group.atoms.push(`${atom.atom_name} ${atom.element}`);
    groups.set(id, group);
  }
  return [...groups.values()].map(group => `${residueShortText(group.residue)}: ${group.atoms.length}개 ` +
    `(${group.atoms.join(", ")})`);
}

/**
 * One individual or the wild-type reference row as the screen shows it: the stored row, every place it appears, and
 * its stored model's values only (no SASA or contacts, nothing set beside another structure). Potentials carry the
 * server's S5 sentence; values are rounded for display only (decimal-string ROUND_HALF_UP).
 */
export function individualDetailView(read: SequenceGaIndividualRead): IndividualDetailView {
  const model = read.model;
  const side = model ? (Object.keys(model.structures)[0] as MutationModelSide | undefined) ?? null : null;
  const entry = model && side ? model.structures[side] ?? null : null;
  const mutationLines = model
    ? model.mutations.map(m => `후보 번호 ${m.candidate_index} · ${mutationText(m)} (${m.residue.resname} → ` +
      `${m.mutant_resname}) · ${residueFieldsText(m.residue)}`)
    : mutationFieldLines(read.mutations);
  const differenceRows = model && !read.is_reference ? model.protonation_differences.map(row => ({
    residue: residueShortText(row.residue), fields: residueFieldsText(row.residue),
    wild_type_reference: variantText(row.wild_type_reference), mutant: variantText(row.mutant) })) : [];
  const limitations = model ? model.limitations : [];
  return {
    title: read.is_reference ? REFERENCE_TITLE : `개체 ${read.key}`, key: read.key, mutationLines,
    appearanceLines: read.appearances.map(item => `세대 ${item.generation} · 자리 ${item.position + 1} · ` +
      ORIGIN_LABEL[item.origin]),
    evaluation: evaluationText(read.evaluation), state: stateText(read.state), score: individualScoreText(read),
    reason: individualReasonText(read),
    structureLabel: entry && side ? `${RECEPTOR_SIDE_LABEL[side]} (${side})` : null,
    energyRows: entry ? [[`${ENERGY_LABEL} · 최소화 전`, energyText(entry.energy.before_kJ_mol)],
      [`${ENERGY_LABEL} · 최소화 후`, energyText(entry.energy.after_kJ_mol)]] : [],
    energyStatements: entry ? gaStatementTexts(read.statements) : [],
    protonationVariantLines: entry ? entry.protonation_variants.map(row => `${residueShortText(row.residue)} · ` +
      variantText(row.variant)) : [],
    protonationDifferenceRows: differenceRows,
    protonationDifferenceText: !model ? "" : read.is_reference ? NOT_APPLICABLE_REFERENCE
      : differenceRows.length ? "" : "없음(변이한 잔기 밖에서 야생형 기준 구조와 다르게 지정된 히스티딘·시스테인 없음)",
    disulfideText: entry ? disulfideText(entry.disulfide_bonds) : "",
    newDisulfideText: !model ? "" : read.is_reference ? NOT_APPLICABLE_REFERENCE
      : `${model.new_disulfide_in_mutant ? "예" : "아니요"} (new_disulfide_in_mutant)`,
    addedAtomLines: entry ? addedAtomLines(entry.added_heavy_atoms) : [],
    countLines: entry ? [["중원자 수", String(entry.heavy_atoms)], ["pH 7.0에서 만든 수소 수",
      String(entry.added_hydrogens)]] : [],
    modelLimitations: limitations,
    unknownLimitations: limitations.filter(sentence => !MODEL_LIMITATIONS.includes(sentence)),
    structureAvailable: entry !== null,
    m18Handle: read.m18_detail !== null && typeof read.result_handle === "string" ? read.result_handle : null,
    missingModelText: model ? null
      : `저장된 모델 없음${read.reason_code ? ` · 이유: ${gaReasonText(read.reason_code)}` : ""}`,
  };
}

// ---- wording check ----

const EXEMPT: readonly string[] = [...Object.values(STATEMENTS), ...MODEL_LIMITATIONS, ...DOCKING_LIMITATIONS];
// "최적화"/"최소화" (processes) are allowed; "변화 없음" (the stop reason) is allowed, "변화량" is not.
const FORBIDDEN = new RegExp(["순위", "최고", "최적(?!화)", "개선", "승자", "우승", "추천", "유망", "좋은", "나쁜", "우수",
  "우월", "상위", "하위", "향상", "악화", "대비", "차이", "증감", "증가", "감소", "변화량", "평균", "효과", "친화", "안정성",
  "ΔΔG", "Δ", "결합\\s*강도", "부분\\s*완료", "\\brank", "\\bbest", "improv", "winner", "recommend", "optimal",
  "stabili", "delta", "differen", "affinity", "better", "worse", "superior"].join("|"), "gi");

/**
 * Forbidden words in screen text, line by line: a line equal to a fixed S sentence, model limitation or M18
 * limitation is exempt; on any other line only the exact M18 score names are removed before the check (the score
 * label says 친화도가 아님). Banned: rank, best, optimal, improvement, winner, recommendation, any comparison with the
 * wild-type reference or a parent (대비, 차이, 증감, delta), averages, effects, affinity, stability, ΔΔG.
 */
export function gaForbiddenWords(text: string): string[] {
  const found: string[] = [];
  for (const line of text.split("\n")) {
    if (EXEMPT.includes(line)) continue;
    const checked = line.split(SCORE_LABEL).join("").split(SCORE_COLUMN_LABEL).join("");
    for (const match of checked.matchAll(FORBIDDEN)) found.push(match[0]);
  }
  return found;
}
