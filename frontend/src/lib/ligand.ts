/**
 * Pure logic of the M17 "리간드 설계·탐색" tab (M17 spec sections 3–9, `.dryforge/spec.md`).
 *
 * Every property, PAINS match, count and pass/fail comes from stored backend objects (`ligand_inspection@1`,
 * `ligand_candidate_set@1`, the server-evaluated candidate page); this module never computes a scientific value
 * and never re-checks filter bounds. It decides panel state, request bodies and query strings, display strings
 * (decimal-string ROUND_HALF_UP, units, "한국어 (code)"), the one-job-at-a-time rule and late-response keys.
 * Wording: properties are "RDKit 추정값", PAINS is "구조 경고 일치"; no word implies activity, drug-likeness,
 * toxicity, safety or synthesis.
 */
import type { LigandCapability, LigandEnumerateArgs, LigandFilterSpec, LigandInspectArgs, LigandJob,
  LigandPropertyName, LigandProtocol, LigandRuleRow, LigandSitePreview, LigandSortDirection,
  LigandSortKey } from "./contracts";
import { decimalHalfUp } from "./site-annotation";

// ---- closed sets (same values and order as backend/mw/ligand_constants.py; tests compare them) ----
export const PARENT_REJECT_REASONS = ["unparseable", "record_count", "multiple_fragments", "element_not_allowed",
  "too_many_atoms"] as const;
export const BLOCK_REJECT_REASONS = ["unparseable", "empty", "multiple_fragments", "element_not_allowed",
  "too_many_atoms", "duplicate_name"] as const;
export const SITE_REASONS = ["site_empty", "core_empty", "crossing_bond_count", "crossing_bond_not_single",
  "site_atom_unknown"] as const;
export const RULE_VALID = "valid";
export const RULE_REASONS = ["reaction_parse_failed", "reactant_count", "product_count", "no_mapped_atom", "too_large",
  "duplicate_rule"] as const;
export const PRODUCT_REJECT_REASONS = ["sanitize_failed", "element_not_allowed", "too_many_atoms", "equals_parent",
  "outside_site"] as const;
export const STOP_REASONS = ["candidate_limit", "attempt_limit"] as const;
export const STEREO_FLAGS = ["none", "parent_stereo_lost", "new_unspecified_center"] as const;
export const PROPERTY_NAMES: readonly LigandPropertyName[] = ["mol_weight", "crippen_logp", "hbd", "hba", "tpsa",
  "rotatable_bonds", "heavy_atoms", "formal_charge"];
export const SORT_KEYS: readonly LigandSortKey[] = ["generation_order", ...PROPERTY_NAMES];
export const LIGAND_TOOLS: Record<LigandProtocol, string> = { rdkit_inspect_v1: "rdkit_inspect_ligand",
  rdkit_enumerate_v1: "rdkit_enumerate_ligands" };
export const LIGAND_TIMEOUT_S = 120;
/** Candidate rows per page (backend default 50, maximum 100). */
export const CANDIDATE_PAGE_LIMIT = 50;
export const MAX_RULES = 10;

// ---- fixed wording ----
export const PROPERTY_NOTE = "속성값은 RDKit 추정값입니다(측정값이 아닙니다).";
export const PAINS_HEADER = "PAINS 구조 경고 일치";
export const PAINS_NOTE = "PAINS 일치는 구조 경고일 뿐 화합물에 대한 판정이 아닙니다.";
export const CANDIDATE_2D_NOTE = "후보는 2D 그래프(SMILES)이며 3D 배치·점수는 계산하지 않았습니다.";
export const NULL_RESULT_TEXT = "후보가 0개입니다. 실패가 아닙니다: 거부 이유별 개수와 규칙별 적용 불가 개수를 확인하세요.";
export const NO_RUN_REASON = "구조 분석 탭에서 run을 먼저 고르세요.";
const UNAVAILABLE_DEFAULT = "리간드 후보 생성 기능을 사용할 수 없습니다.";

// ---- reason text ----

/**
 * Korean names of every ligand code (parent/block/site/rule/product reasons, stop reasons, stereo flags, preview,
 * admission, worker and capability codes). The code list is duplicated in tests/ligand.test.cjs (REASON_CODES),
 * which also reads the backend closed sets; change them together.
 */
export const LIGAND_REASON_LABEL: Record<string, string> = {
  unparseable: "읽을 수 없음",
  record_count: "레코드가 정확히 1개가 아님",
  multiple_fragments: "분리된 조각이 여러 개",
  element_not_allowed: "허용 원소(H C N O S P F Cl Br I) 밖의 원소",
  too_many_atoms: "중원자 수 상한 초과",
  empty: "빈 레코드",
  duplicate_name: "이미 쓰인 이름",
  site_empty: "부위가 비어 있음",
  core_empty: "부위 밖에 남는 원자가 없음",
  crossing_bond_count: "부위와 나머지를 잇는 결합이 정확히 1개가 아님",
  crossing_bond_not_single: "부위와 나머지를 잇는 결합이 단일 결합이 아님",
  site_atom_unknown: "점검 원자 표에 없는 원자 번호",
  valid: "검증 통과",
  reaction_parse_failed: "반응 SMARTS를 읽지 못함",
  reactant_count: "반응물 템플릿이 2개가 아님",
  product_count: "생성물 템플릿이 1개가 아님",
  no_mapped_atom: "첫째 반응물에 원자 맵 번호가 붙은 원자가 없음",
  too_large: "규칙 텍스트 크기 상한 초과",
  duplicate_rule: "앞 규칙과 같은 텍스트",
  sanitize_failed: "생성물 정리(sanitize) 실패",
  equals_parent: "부모와 같은 분자",
  outside_site: "규칙이 부위 밖 원자를 맞춤",
  candidate_limit: "후보 수 상한 도달",
  attempt_limit: "생성 시도 상한 도달",
  none: "입체 표시 없음",
  parent_stereo_lost: "부모 코어의 입체 지정이 사라짐",
  new_unspecified_center: "새로 생긴 미지정 입체 중심",
  no_generation_method: "생성 방법(고정 교체·규칙)을 하나도 고르지 않음",
  rule_invalid: "점검에서 통과하지 않은 규칙",
  inspection_required: "이 run에 완료된 점검 결과가 없음",
  inspection_invalid: "같은 run의 완료된 점검 결과가 아님",
  site_atoms_invalid: "부위 원자 번호 형식 오류",
  invalid_preview_request: "부위 검사 요청 형식 오류",
  invalid_job_arguments: "작업 인자 형식 오류",
  rule_text_invalid: "규칙 텍스트 형식 오류",
  parent_import_invalid: "부모 SDF 가져오기가 아님",
  block_import_invalid: "building block 가져오기가 아님",
  svg_limit: "2D 그림 크기 상한 초과",
  output_limit: "작업 출력 크기 상한 초과",
  inspection_size_limit: "점검 결과 크기 상한 초과",
  staged_input_invalid: "작업 입력 검증 실패",
  rdkit_version_mismatch: "RDKit 버전이 고정 버전과 다름",
  worker_internal_error: "작업 프로세스 내부 오류",
  worker_missing: "RDKit 작업 환경 없음",
  handshake_failed: "RDKit 작업 프로세스 확인 실패",
  pains_catalog_unavailable: "PAINS 카탈로그를 불러오지 못함",
  evidence_invalid: "저장된 결과 검증 실패",
};

/** "한국어 (code)" so the identifier stays visible; unknown codes are shown as is. */
export function ligandReasonText(code: string): string {
  const label = Object.prototype.hasOwnProperty.call(LIGAND_REASON_LABEL, code) ? LIGAND_REASON_LABEL[code] : undefined;
  return label ? `${label} (${code})` : code;
}

function capabilityReason(capability: Pick<LigandCapability, "reason" | "reason_code"> | null): string {
  const reason = capability?.reason ?? UNAVAILABLE_DEFAULT;
  return capability?.reason_code ? `${reason} (${capability.reason_code})` : reason;
}

function failureText(failure: { error: string; message: string; reason_code?: string } | null): string {
  if (!failure) return "이유 없음";
  return `${failure.reason_code ? ligandReasonText(failure.reason_code) : failure.error} · ${failure.message}`;
}

// ---- panel state ----

export type LigandPanelState =
  | { state: "loading" } | { state: "ready" } | { state: "scientific_null"; message: string }
  | { state: "failure"; message: string } | { state: "unavailable"; reason: string };

type CapabilityLike = Pick<LigandCapability, "available" | "reason" | "reason_code">;
type JobLike = { status: string; failure: { error: string; message: string; reason_code?: string } | null };

const ACTIVE_STATUSES = ["queued", "claimed", "running"];
const FAILED_STATUSES = ["failed", "interrupted", "cancelled"];

/**
 * Five states. `capability` undefined = not read yet; null = the backend reports no ligand method. `job` is the
 * panel's current job (pass null when the user opened a stored result instead); `candidates` is the stored
 * candidate count of the opened set (0 = an empty scientific result, never a failure).
 */
export function ligandPanelState(input: { runId: string | null; capability?: CapabilityLike | null; loading?: boolean;
  error?: string | null; job?: JobLike | null; candidates?: number | null }): LigandPanelState {
  if (input.runId === null) return { state: "unavailable", reason: NO_RUN_REASON };
  if (input.capability === null || input.capability?.available === false)
    return { state: "unavailable", reason: capabilityReason(input.capability ?? null) };
  if (input.error) return { state: "failure", message: input.error };
  const job = input.job;
  if (job && FAILED_STATUSES.includes(job.status))
    return { state: "failure", message: job.status === "cancelled" ? "작업이 취소되어 결과를 저장하지 않았습니다."
      : `작업 실패: ${failureText(job.failure)}` };
  if (input.loading || input.capability === undefined || (job && ACTIVE_STATUSES.includes(job.status)))
    return { state: "loading" };
  if (input.candidates === 0) return { state: "scientific_null", message: NULL_RESULT_TEXT };
  return { state: "ready" };
}

// ---- site selection (SDF serials of one inspection) ----

export interface SiteSelection { inspectionHandle: string | null; atoms: number[] }

export function emptySiteSelection(inspectionHandle: string | null): SiteSelection {
  return { inspectionHandle, atoms: [] };
}

/** Toggles one SDF serial; a different inspection starts a new empty selection. Atoms stay ascending. */
export function toggleSiteAtom(selection: SiteSelection, inspectionHandle: string, serial: number): SiteSelection {
  const atoms = selection.inspectionHandle === inspectionHandle ? selection.atoms : [];
  const next = atoms.includes(serial) ? atoms.filter(atom => atom !== serial) : [...atoms, serial];
  return { inspectionHandle, atoms: next.sort((a, b) => a - b) };
}

export function siteAtomChecked(selection: SiteSelection, inspectionHandle: string | null, serial: number): boolean {
  return selection.inspectionHandle === inspectionHandle && selection.atoms.includes(serial);
}

/** Why the atom check boxes are off (null = usable): the site check needs a loaded inspection. */
export function siteSelectionDisabledReason(input: { inspectionHandle: string | null; inspectionLoaded: boolean }):
  string | null {
  if (!input.inspectionHandle)
    return "점검 작업을 먼저 끝내고 점검 결과를 고르세요. 부위 검사는 점검 결과의 원자 표·결합 목록으로만 할 수 있습니다.";
  if (!input.inspectionLoaded) return "점검 결과를 읽는 중입니다.";
  return null;
}

// ---- numbers and units (display only) ----

export const PROPERTY_LABEL: Record<LigandPropertyName, string> = {
  mol_weight: "분자량(평균)", crippen_logp: "Crippen logP", hbd: "HBD(Lipinski)", hba: "HBA(Lipinski)", tpsa: "TPSA",
  rotatable_bonds: "회전 가능 결합 수", heavy_atoms: "중원자 수", formal_charge: "형식 전하 합" };
export const PROPERTY_UNIT: Record<LigandPropertyName, string> = {
  mol_weight: "Da", crippen_logp: "무차원", hbd: "개", hba: "개", tpsa: "Å²", rotatable_bonds: "개",
  heavy_atoms: "개", formal_charge: "무차원" };
const DECIMAL_PROPERTIES: readonly LigandPropertyName[] = ["mol_weight", "crippen_logp", "tpsa"];

export function propertyHeader(name: LigandPropertyName): string {
  return `${PROPERTY_LABEL[name]} (${PROPERTY_UNIT[name]}, RDKit 추정값)`;
}

/**
 * Stored value as shown: mol_weight/crippen_logp/tpsa with two decimals (ROUND_HALF_UP on the decimal string),
 * Da and Å² appended; counts and the charge as integers.
 */
export function propertyText(name: LigandPropertyName, value: number): string {
  if (!DECIMAL_PROPERTIES.includes(name)) return String(value);
  const text = decimalHalfUp(value, 2);
  return name === "mol_weight" ? `${text} Da` : name === "tpsa" ? `${text} Å²` : text;
}

export function countText(value: number): string { return String(value); }

export function painsText(matches: readonly { catalog: string; name: string }[]): string {
  if (!matches.length) return "구조 경고 일치 없음";
  return `구조 경고 일치 ${matches.length}건: ${matches.map(match => `${match.catalog} ${match.name}`).join(", ")}`;
}

export function passText(value: boolean | null): string {
  return value === null ? "—" : value ? "통과" : "실패";
}

// ---- filters (the server evaluates; the screen only builds the spec) ----

export interface LigandFilterInput { ranges: Record<LigandPropertyName, { min: string; max: string }>;
  painsExclude: boolean }

/** No range and PAINS exclusion off (nothing is prefilled). */
export function emptyFilterInput(): LigandFilterInput {
  return { ranges: Object.fromEntries(PROPERTY_NAMES.map(name => [name, { min: "", max: "" }])) as
    LigandFilterInput["ranges"], painsExclude: false };
}

/** Same number syntax as the backend query parser (`ligand_reads._NUMBER_RE`). */
const NUMBER_RE = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/;

export type FilterCheck = { ok: true; spec: LigandFilterSpec } | { ok: false; errors: string[] };

/** Empty bound = none; otherwise a finite decimal number; min must not exceed max. */
export function checkFilterInput(input: LigandFilterInput): FilterCheck {
  const errors: string[] = [];
  const ranges: LigandFilterSpec["ranges"] = {};
  for (const name of PROPERTY_NAMES) {
    const bounds: { min: number | null; max: number | null } = { min: null, max: null };
    for (const side of ["min", "max"] as const) {
      const text = input.ranges[name][side].trim();
      if (!text) continue;
      const value = Number(text);
      if (!NUMBER_RE.test(text) || !Number.isFinite(value)) {
        errors.push(`${PROPERTY_LABEL[name]} ${side === "min" ? "최솟값" : "최댓값"}: 숫자만 입력하세요(예: 250, 2.5, -1).`);
        continue;
      }
      bounds[side] = value;
    }
    if (bounds.min !== null && bounds.max !== null && bounds.min > bounds.max)
      errors.push(`${PROPERTY_LABEL[name]}: 최솟값이 최댓값보다 큽니다.`);
    if (bounds.min !== null || bounds.max !== null) ranges[name] = bounds;
  }
  return errors.length ? { ok: false, errors } : { ok: true, spec: { ranges, pains_exclude: input.painsExclude } };
}

export function appliedFilterCount(spec: LigandFilterSpec): number {
  return Object.keys(spec.ranges).length + (spec.pains_exclude ? 1 : 0);
}

export function filterSummaryText(spec: LigandFilterSpec): string {
  const count = appliedFilterCount(spec);
  return count ? `적용한 필터 ${count}개` : "적용한 필터 없음";
}

export interface CandidateView { sort: LigandSortKey; direction: LigandSortDirection; offset: number; limit: number;
  passesOnly: boolean }

/** Query string of `GET …/ligand/candidate_sets/rows` (only known parameters; defaults left out). */
export function candidateRowsQuery(handle: string, spec: LigandFilterSpec, view: CandidateView): string {
  const params: [string, string][] = [["handle", handle]];
  for (const name of PROPERTY_NAMES) {
    const bounds = spec.ranges[name];
    if (bounds?.min != null) params.push([`${name}_min`, String(bounds.min)]);
    if (bounds?.max != null) params.push([`${name}_max`, String(bounds.max)]);
  }
  if (spec.pains_exclude) params.push(["pains_exclude", "true"]);
  if (view.passesOnly) params.push(["passes_only", "true"]);
  params.push(["sort", view.sort], ["direction", view.direction], ["offset", String(view.offset)],
    ["limit", String(view.limit)]);
  return params.map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join("&");
}

/** Full total next to the filter result, and how many rows the "필터 통과만 보기" choice hides. */
export function candidateCountText(page: { total: number; passing: number | null; failing: number | null;
  hidden_by_filter: number; passes_only: boolean }): string {
  const head = `전체 후보 ${page.total}개`;
  if (page.passing === null) return `${head} · 적용한 필터 없음`;
  const tail = page.hidden_by_filter ? `필터 때문에 보이지 않는 후보 ${page.hidden_by_filter}개` : "모두 표시";
  return `${head} · 필터 통과 ${page.passing}개 · 필터 실패 ${page.failing ?? page.total - page.passing}개 · ${tail}`;
}

/** Where generation stopped (null when no cap was reached); the cap values come from the stored object. */
export function limitReachedText(set: { limit_reached: boolean; stop_reason: string | null;
  limits: { max_candidates: number; max_attempts: number } }): string | null {
  if (!set.limit_reached || !set.stop_reason) return null;
  const where = set.stop_reason === "candidate_limit" ? `후보 ${set.limits.max_candidates}개`
    : set.stop_reason === "attempt_limit" ? `생성 시도 ${set.limits.max_attempts}회` : "상한";
  return `상한 도달: ${ligandReasonText(set.stop_reason)} · ${where}에서 정해진 순서대로 멈췄습니다. ` +
    "이후 순서의 후보는 만들지 않았습니다.";
}

export function blockLimitText(libraries: readonly { records_read: number; block_limit_reached: boolean }[]):
  string | null {
  if (!libraries.some(library => library.block_limit_reached)) return null;
  const read = libraries.reduce((sum, library) => sum + library.records_read, 0);
  return `building block 상한 도달: 입력 순서대로 처음 ${read}개 레코드만 읽었습니다.`;
}

// ---- late responses (run + handle + request sequence) ----

export interface LigandStamp { runId: string | null; handle: string | null; seq: number }

/** Applied only when run, selected handle (inspection or candidate set) and request sequence are still current. */
export function ligandResponseCurrent(captured: LigandStamp, live: LigandStamp): boolean {
  return captured.runId !== null && captured.runId === live.runId && captured.handle === live.handle &&
    captured.seq === live.seq;
}

// ---- jobs (POST /jobs → /start → 409 approval → /jobs/approve → /start → GET /jobs/{id}) ----

/** One job at a time: null = a new inspection/enumeration may be submitted or started. */
export function ligandStartBlockedReason(input: { capability: CapabilityLike | null | undefined; dryRun: boolean;
  busy: boolean; activeJob: { status: string } | null }): string | null {
  if (!input.capability?.available) return capabilityReason(input.capability ?? null);
  if (input.dryRun) return "dry-run run에서는 계획만 만들며 실제 계산을 시작하지 않습니다.";
  if (input.busy) return "요청을 처리하는 중입니다.";
  if (input.activeJob && ACTIVE_STATUSES.includes(input.activeJob.status))
    return "진행 중인 작업이 끝난 뒤 시작할 수 있습니다(한 번에 한 작업).";
  return null;
}

export type LigandJobPhase = "none" | "saved" | "awaiting_approval" | "running" | "done" | "failed" | "cancelled";

/** `approvalPending`: the last start answered 409 with this protocol's approval request. */
export function ligandJobPhase(job: { status: string } | null, approvalPending: boolean): LigandJobPhase {
  if (!job) return "none";
  if (approvalPending && ACTIVE_STATUSES.includes(job.status)) return "awaiting_approval";
  if (job.status === "queued") return "saved";
  if (job.status === "claimed" || job.status === "running") return "running";
  if (job.status === "done") return "done";
  if (job.status === "cancelled") return "cancelled";
  return "failed";
}

const JOB_LABEL: Record<LigandProtocol, string> = { rdkit_inspect_v1: "점검 작업", rdkit_enumerate_v1: "생성 작업" };

export function ligandJobText(protocol: LigandProtocol, job: { status: string; cancel_requested: boolean;
  failure: { error: string; message: string; reason_code?: string } | null } | null, approvalPending: boolean): string {
  const label = JOB_LABEL[protocol];
  switch (ligandJobPhase(job, approvalPending)) {
    case "none": return `${label} 없음`;
    case "saved": return `${label}이 저장되었습니다. 시작을 누르면 실제 계산이 실행됩니다(비싼 계산 예산 1단위).`;
    case "awaiting_approval": return "비용이 드는 실제 계산 승인이 필요합니다(비싼 계산 예산 1단위). 승인한 뒤 시작을 다시 누르세요.";
    case "running": return `${label} 실행 중${job?.cancel_requested ? " · 취소 요청됨" : ""}`;
    case "done": return `${label} 완료`;
    case "cancelled": return `${label} 취소됨 (결과를 저장하지 않았습니다)`;
    default:
      return job && ["failed", "interrupted"].includes(job.status) ? `${label} 실패: ${failureText(job.failure)}`
        : `${label} 실패: 알 수 없는 작업 상태 (${job?.status})`;
  }
}

/** Submission is idempotent: identical inputs return the existing job; a dry-run run returns a plan only. */
export function ligandSubmitText(result: { plan_only: true; protocol_id: LigandProtocol } |
  Pick<LigandJob, "job_id" | "status" | "protocol_id">): string {
  if ("plan_only" in result) return "dry-run run이라 계획만 만들었습니다. 실제 계산과 결과 객체는 없습니다.";
  if (result.status === "queued") return ligandJobText(result.protocol_id, { status: "queued", cancel_requested: false,
    failure: null }, false);
  return `같은 입력의 기존 작업을 다시 표시합니다 · ${result.job_id} · ${result.status} (새 작업을 만들지 않았습니다)`;
}

export function ligandApprovalRequired(status: number, approval: { gate: string; tool: string } | undefined,
  protocol: LigandProtocol): boolean {
  return status === 409 && approval?.gate === "expensive_first_call" && approval.tool === LIGAND_TOOLS[protocol];
}

/** A start whose HTTP response was lost still took effect when the same stored job moved past queued. */
export function ligandStartProgressed(before: { run_id: string; job_id: string; protocol_id: string;
  attempt_ordinal: number }, stored: { run_id: string; job_id: string; protocol_id: string; status: string;
  attempt_ordinal: number }): boolean {
  return stored.run_id === before.run_id && stored.job_id === before.job_id &&
    stored.protocol_id === before.protocol_id &&
    (!["queued", "claimed"].includes(stored.status) || stored.attempt_ordinal > before.attempt_ordinal);
}

// ---- request bodies ----

export type ArgsCheck<T> = { ok: true; args: T } | { ok: false; errors: string[] };

/**
 * Inspection job args. Rules: one reaction SMARTS per line, blank lines skipped, the text otherwise kept as typed
 * (only a Windows "\r" line end is removed); `user_<n>` follows this order. Rule errors are reported per rule by
 * the inspection itself, not here.
 */
export function inspectArgs(input: { parent: string | null; blockSdf: string | null; blockSmiles: string | null;
  rulesText: string }): ArgsCheck<LigandInspectArgs> {
  const errors: string[] = [];
  if (!input.parent) errors.push("부모 리간드 SDF를 먼저 가져오세요.");
  const rules = input.rulesText.split("\n").map(line => line.replace(/\r$/, "")).filter(line => line.trim() !== "");
  if (rules.length > MAX_RULES) errors.push(`반응 규칙은 한 번에 ${MAX_RULES}개까지입니다(지금 ${rules.length}개).`);
  if (errors.length || !input.parent) return { ok: false, errors };
  return { ok: true, args: { parent_sdf_handle: input.parent,
    block_handles: [input.blockSdf, input.blockSmiles].filter((handle): handle is string => !!handle), rules } };
}

export function usableRuleIds(rules: readonly LigandRuleRow[]): string[] {
  return rules.filter(rule => rule.status === RULE_VALID).map(rule => rule.rule_id);
}

export function ruleStatusText(rule: Pick<LigandRuleRow, "status">): string { return ligandReasonText(rule.status); }

/** Preview body and enumeration job args (site atoms ascending; the server re-checks everything). */
export function enumerateArgs(input: { inspectionHandle: string | null; siteAtoms: readonly number[];
  useFixed: boolean; ruleIds: readonly string[] }): ArgsCheck<LigandEnumerateArgs> {
  const errors: string[] = [];
  if (!input.inspectionHandle) errors.push("점검 결과를 고르세요.");
  if (!input.useFixed && !input.ruleIds.length)
    errors.push(`고정 교체나 반응 규칙을 하나 이상 고르세요: ${ligandReasonText("no_generation_method")}`);
  if (errors.length || !input.inspectionHandle) return { ok: false, errors };
  return { ok: true, args: { inspection_handle: input.inspectionHandle,
    site_atoms: [...input.siteAtoms].sort((a, b) => a - b), use_fixed: input.useFixed, rule_ids: [...input.ruleIds] } };
}

type PreviewLike = Pick<LigandSitePreview, "inspection_handle" | "use_fixed" | "rules" | "ready" | "blocking_reasons">
  & { site_check: { site_atoms: number[] } };

/** The preview answers exactly this request (a stale preview never enables the start). */
export function previewMatches(preview: PreviewLike | null, args: LigandEnumerateArgs): boolean {
  if (!preview) return false;
  const site = [...args.site_atoms].sort((a, b) => a - b);
  return preview.inspection_handle === args.inspection_handle && preview.use_fixed === args.use_fixed &&
    preview.site_check.site_atoms.length === site.length && preview.site_check.site_atoms.every((x, i) => x === site[i]) &&
    preview.rules.length === args.rule_ids.length && preview.rules.every((rule, i) => rule.rule_id === args.rule_ids[i]);
}

export function enumerateReady(preview: PreviewLike | null, args: LigandEnumerateArgs): boolean {
  return !!preview && preview.ready && previewMatches(preview, args);
}

export function previewBlockingText(preview: Pick<LigandSitePreview, "blocking_reasons">): string[] {
  return preview.blocking_reasons.map(ligandReasonText);
}

/** The stored RDKit SVG as an `<img>` source; the markup is never inserted into the DOM. */
export function svgDataUri(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
