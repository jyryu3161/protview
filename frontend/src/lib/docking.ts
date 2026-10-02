/**
 * Pure logic of the M18 docking area of the "리간드 설계·탐색" tab (M18 spec sections 3–5, 8; `.dryforge/spec.md`).
 *
 * Every score, contact, distance, box and count comes from the stored `docking_result@1` object (qvina, RDKit and
 * Meeko run in the isolated job worker); this module never computes a scientific value. It decides panel state,
 * input compatibility, the exact job-argument shape (`docking_inputs.validate_arguments`), display strings
 * (decimal-string ROUND_HALF_UP, "한국어 (code)"), the one-job-at-a-time rule and late-response keys.
 * Wording: the score is "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)"; free-docking rows are
 * "모드 n(엔진 출력 순서)", core-fixed rows "샘플 n(점수 오름차순 나열)". No word implies rank, best, improvement or
 * binding strength (`dockingForbiddenWords`).
 */
import type { DockingAcknowledgementKey, DockingArgs, DockingBoxSource, DockingCapability, DockingContact,
  DockingJob, DockingLigandSource, DockingMode, DockingModeSummary, DockingReceptorAtom, DockingReceptorInstance,
  DockingResult, ExactResidueRef, GeometricContactType } from "./contracts";
import { CONTACT_TYPE_LABEL, decimalHalfUp } from "./site-annotation";

// ---- closed sets (same values and order as backend/mw/docking_constants.py; tests compare them) ----
export const DOCKING_PROTOCOL = "qvina_dock_v1";
export const DOCKING_TOOL = "qvina_dock_ligand";
export const RECEPTOR_REASONS = ["receptor_invalid", "receptor_hydrogens_missing", "receptor_unsupported_residue",
  "receptor_altloc_present", "receptor_instance_unknown", "receptor_instance_ambiguous", "receptor_instance_covalent",
  "receptor_prep_failed"] as const;
export const LIGAND_REASONS = ["ligand_unparseable", "ligand_record_count", "ligand_multiple_fragments",
  "ligand_element_not_allowed", "ligand_too_many_atoms", "ligand_too_many_torsions", "ligand_not_3d",
  "ligand_hydrogens_missing", "ligand_prep_failed"] as const;
export const CANDIDATE_REASONS = ["candidate_unknown", "parent_mismatch", "parent_not_3d", "core_match_failed",
  "core_match_ambiguous", "embed_failed"] as const;
export const BOX_REASONS = ["box_invalid", "box_too_large", "box_no_receptor_atoms"] as const;
export const ENGINE_REASONS = ["engine_failed", "engine_output_invalid", "resource_exceeded"] as const;
export const ADMISSION_ONLY_REASONS = ["invalid_job_arguments", "mode_source_mismatch", "acknowledgement_missing"] as const;
export const CAPABILITY_REASONS = ["worker_missing", "engine_missing", "engine_hash_mismatch", "handshake_failed",
  "version_mismatch"] as const;
export const MODES: readonly DockingMode[] = ["free", "core_fixed"];
export const LIGAND_SOURCES: readonly DockingLigandSource[] = ["sdf", "candidate"];
export const BOX_SOURCES: readonly DockingBoxSource[] = ["ligand_range", "instance_range", "manual"];
export const CONTACT_KINDS: readonly GeometricContactType[] = ["polar_contact", "hydrophobic_contact", "contact"];
export const ACKNOWLEDGEMENT_KEYS: readonly DockingAcknowledgementKey[] = ["keep_input_protonation",
  "tool_assigned_types_charges", "rigid_no_optimization"];

// ---- value ranges (inclusive) and defaults (docking_constants.py) ----
export const SEED_MIN = 0, SEED_MAX = 2147483647;
export const EXHAUSTIVENESS_MIN = 1, EXHAUSTIVENESS_MAX = 32, EXHAUSTIVENESS_DEFAULT = 8;
export const NUM_MODES_MIN = 1, NUM_MODES_MAX = 20, NUM_MODES_DEFAULT = 9;
export const ENERGY_RANGE_MIN = 1, ENERGY_RANGE_MAX = 5, ENERGY_RANGE_DEFAULT = 3;
export const CONFORMERS_MIN = 1, CONFORMERS_MAX = 200, CONFORMERS_DEFAULT = 50;
export const MARGIN_MIN_A = 0, MARGIN_MAX_A = 20, MARGIN_DEFAULT_A = 8;
export const BOX_SIDE_MIN_A = 8, BOX_SIDE_MAX_A = 40;
export const MAX_BOX_CENTER_ABS_A = 100000;
/** Contact rows per page (backend default 100, maximum 500). */
export const CONTACT_PAGE_LIMIT = 100;

// ---- fixed wording ----
export const SCORE_LABEL = "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)";
export const SCORE_COLUMN_LABEL = "qvina 점수(kcal/mol)";
/** spec 5.4, verbatim and in order (index i is sentence i + 1). The screen shows the stored `limitations`. */
export const DOCKING_LIMITATIONS: readonly string[] = [
  "점수는 qvina 2.1(Vina 계열 스코어링 함수)이 낸 값(kcal/mol)이며 결합 친화도·결합 자유 에너지가 아니다.",
  "같은 수용체·상자·seed·방식(자유/코어 고정)·값에서 나온 점수끼리만 나란히 볼 수 있다.",
  "수용체는 입력 그대로의 강체이며 수소·양성자화·토토머를 바꾸지 않았고, AutoDock4 원자 유형·부분 전하는 Meeko가 정한 값이다.",
  "리간드 고리 형태는 입력 형태(후보는 RDKit이 만든 형태)로 고정되어 탐색하지 않았다.",
  "접촉은 거리만으로 센 기하 접촉이며 수소결합 등 상호작용 판정이 아니다.",
  "포즈는 엔진이 낸 배치이며 실험으로 확인한 결합 자세가 아니다.",
  "후보의 3D 좌표와 수소는 RDKit이 만든 것이며 입력 구조가 아니다.",
  "코어 중원자 좌표만 부모 값으로 고정했고 나머지는 RDKit 구속 형태 샘플이며, 점수만 매기고 구조는 최적화하지 않았다. " +
    "이 배치는 실험으로 확인한 결합 자세가 아니다.",
  "수용체에서 지정한 리간드 인스턴스 하나만 뺐고 그 밖의 요소는 바꾸지 않았다.",
  "자유 도킹은 RDKit 형태 하나를 시작점으로 썼다.",
  "미지정 입체 중심의 입체는 RDKit이 임의로 정한 것이다.",
];
export const BOX_FRAME_NOTE = "리간드 좌표가 수용체와 같은 좌표계에 있다고 가정합니다. 도구는 상자 안에 수용체 중원자가 " +
  "하나라도 있는지만 검사하며, 그 밖의 좌표계 어긋남은 검증하지 못합니다.";
export const CONTACT_NOTE = "접촉은 거리 4.0 Å 이하로 센 기하 접촉이며 수소결합 등 상호작용 판정이 아닙니다.";
export const NO_RUN_REASON = "구조 분석 탭에서 run을 먼저 고르세요.";
export const RESOURCE_EXCEEDED_HINT = "모드 수를 줄여 다시 시도하세요.";
export const ACKNOWLEDGEMENT_LABEL: Record<DockingAcknowledgementKey, string> = {
  keep_input_protonation: "입력 수용체의 protonation·수소를 그대로 씁니다.",
  tool_assigned_types_charges: "AutoDock4 원자 유형·부분 전하는 도구(Meeko)가 정합니다.",
  rigid_no_optimization: "수용체는 강체이며 protonation·최적화는 하지 않습니다.",
};
const UNAVAILABLE_DEFAULT = "리간드 도킹 기능을 사용할 수 없습니다.";

// ---- reason text ----

/**
 * Korean names of every code the docking area can show: the closed worker/admission sets, the capability reasons,
 * the job-queue reasons that a docking submission or start can return, and the list read's `evidence_invalid`.
 * The code list is duplicated in tests/docking.test.cjs (REASON_CODES), which also reads the backend closed sets.
 */
export const DOCKING_REASON_LABEL: Record<string, string> = {
  receptor_invalid: "수용체 입력 오류(모델·원자·좌표·연결 정보)",
  receptor_hydrogens_missing: "수용체에 명시적 수소 좌표가 없음",
  receptor_unsupported_residue: "수용체에 물·금속 이온·보조인자·다른 리간드·지원하지 않는 잔기가 남아 있음",
  receptor_altloc_present: "수용체에 대체 위치(altloc)가 있음",
  receptor_instance_unknown: "지정한 잔기 7필드와 일치하는 인스턴스가 수용체에 없음",
  receptor_instance_ambiguous: "지정한 잔기 7필드와 일치하는 인스턴스가 둘 이상",
  receptor_instance_covalent: "지정한 인스턴스가 수용체 나머지와 공유 결합으로 이어져 있음",
  receptor_prep_failed: "수용체 PDBQT 변환(Meeko) 실패",
  ligand_unparseable: "리간드 SDF를 읽을 수 없음",
  ligand_record_count: "리간드 SDF 레코드가 정확히 1개가 아님",
  ligand_multiple_fragments: "리간드가 분리된 조각 여러 개로 되어 있음",
  ligand_element_not_allowed: "허용 원소(H C N O S P F Cl Br I) 밖의 원소",
  ligand_too_many_atoms: "리간드 중원자 수 상한 초과",
  ligand_too_many_torsions: "능동 비틀림 수 상한(32) 초과",
  ligand_not_3d: "리간드 좌표가 3D가 아님(모든 원자의 z가 같음)",
  ligand_hydrogens_missing: "리간드에 명시적 수소가 없음(암시 수소가 남아 있음)",
  ligand_prep_failed: "리간드 PDBQT 변환(Meeko) 실패",
  candidate_unknown: "후보 집합에 없는 후보 id",
  parent_mismatch: "부모 SDF의 SHA-256이 후보 집합의 부모와 다름",
  parent_not_3d: "부모 SDF 좌표가 3D가 아님",
  core_match_failed: "후보에서 부모 코어 부분 그래프를 찾지 못함",
  core_match_ambiguous: "서로 다른 좌표를 주는 코어 일치가 둘 이상",
  embed_failed: "코어 구속 형태 생성이 하나도 성공하지 못함",
  box_invalid: "상자 입력 오류",
  box_too_large: "상자 한 변이 40 Å 초과",
  box_no_receptor_atoms: "상자 안에 수용체 중원자가 없음(좌표계를 확인하세요)",
  engine_failed: "qvina 실행 실패",
  engine_output_invalid: "qvina 출력 형식 오류",
  resource_exceeded: "결과 크기 상한 초과",
  invalid_job_arguments: "작업 인자 형식·값 범위 오류",
  mode_source_mismatch: "코어 고정은 후보 출처에서만 쓸 수 있음",
  acknowledgement_missing: "확인 세 항목이 모두 체크되지 않음",
  worker_missing: "도킹 작업 환경이 없음",
  engine_missing: "qvina 엔진 환경이 없음",
  engine_hash_mismatch: "qvina 실행 파일 해시가 설치 기록과 다름",
  handshake_failed: "도킹 작업 프로세스 확인 실패",
  version_mismatch: "작업 환경 패키지 버전이 고정 버전과 다름",
  worker_version_invalid: "작업 환경 버전 확인 실패",
  process_identity_unavailable: "작업 프로세스 신원을 확인할 수 없음",
  global_concurrency_busy: "다른 작업이 실행 중",
  global_job_cleanup_pending: "이전 작업 정리 대기 중",
  global_job_ledger_unavailable: "작업 기록을 읽을 수 없음",
  dry_run: "dry-run run(계획만 만듦)",
  evidence_invalid: "저장된 결과 검증 실패",
};

/** "한국어 (code)" so the identifier stays visible; unknown codes are shown as is. */
export function dockingReasonText(code: string): string {
  const label = Object.prototype.hasOwnProperty.call(DOCKING_REASON_LABEL, code) ? DOCKING_REASON_LABEL[code] : undefined;
  return label ? `${label} (${code})` : code;
}

type CapabilityLike = Pick<DockingCapability, "available" | "reason" | "reason_code">;

/** Capability reason as given by the server, with its code; never a number. */
export function dockingCapabilityText(capability: Pick<DockingCapability, "reason" | "reason_code"> | null): string {
  if (!capability) return UNAVAILABLE_DEFAULT;
  if (capability.reason) return capability.reason_code ? `${capability.reason} (${capability.reason_code})` : capability.reason;
  return capability.reason_code ? dockingReasonText(capability.reason_code) : UNAVAILABLE_DEFAULT;
}

type FailureLike = { error: string; message: string; reason_code?: string } | null;

/** Job failure "한국어 (code) · message"; `resource_exceeded` adds the "reduce the mode count" hint. */
export function dockingFailureText(failure: FailureLike): string {
  if (!failure) return "이유 없음";
  const head = failure.reason_code ? dockingReasonText(failure.reason_code) : failure.error;
  const exceeded = failure.reason_code === "resource_exceeded" || failure.error === "resource_exceeded";
  return `${head} · ${failure.message}${exceeded ? ` · ${RESOURCE_EXCEEDED_HINT}` : ""}`;
}

/**
 * Text of a refused request (`ApiError` of `POST /jobs`, a read, a report): the closed `detail.reason_code` when
 * present, else the error class. Listed receptor items (`detail.items`, at most 20) are counted against `total`.
 */
export function dockingRequestErrorText(error: { message: string; code?: string;
  detail?: Record<string, unknown> }): string {
  const reason = typeof error.detail?.reason_code === "string" ? error.detail.reason_code : null;
  const head = reason ? dockingReasonText(reason) : error.code ?? "요청 실패";
  const items = Array.isArray(error.detail?.items) ? error.detail.items.length : null;
  const total = typeof error.detail?.total === "number" ? error.detail.total : null;
  const listed = items !== null && total !== null ? ` · 목록 ${total}개 중 ${items}개 표시` : "";
  return `${head} · ${error.message}${reason === "resource_exceeded" ? ` · ${RESOURCE_EXCEEDED_HINT}` : ""}${listed}`;
}

// ---- panel state ----

export type DockingPanelState =
  | { state: "loading" } | { state: "ready" } | { state: "scientific_null"; message: string }
  | { state: "failure"; message: string } | { state: "unavailable"; reason: string };

type JobLike = { status: string; failure: FailureLike };

const ACTIVE_STATUSES = ["queued", "claimed", "running"];
const FAILED_STATUSES = ["failed", "interrupted", "cancelled"];

export function nullResultText(mode: DockingMode): string {
  return mode === "core_fixed"
    ? "점수를 매긴 샘플이 0개입니다. 빈 과학 결과이며 실패가 아닙니다(만든 형태 수·점수를 매긴 수를 확인하세요)."
    : "qvina가 모드를 하나도 내지 않았습니다. 빈 과학 결과이며 실패가 아닙니다.";
}

/**
 * Five states. `capability` undefined = not read yet; null = the backend reports no docking method. `job` is the
 * area's current job (null when a stored result was opened instead). `result` is the opened result's stored mode
 * count and mode: 0 modes is an empty scientific result, never a failure; a failed job is never an empty result.
 */
export function dockingPanelState(input: { runId: string | null; capability?: CapabilityLike | null;
  loading?: boolean; error?: string | null; job?: JobLike | null;
  result?: { modes: number; mode: DockingMode } | null }): DockingPanelState {
  if (input.runId === null) return { state: "unavailable", reason: NO_RUN_REASON };
  if (input.capability === null || input.capability?.available === false)
    return { state: "unavailable", reason: dockingCapabilityText(input.capability ?? null) };
  if (input.error) return { state: "failure", message: input.error };
  const job = input.job;
  if (job && FAILED_STATUSES.includes(job.status))
    return { state: "failure", message: job.status === "cancelled" ? "작업이 취소되어 결과를 저장하지 않았습니다."
      : `작업 실패: ${dockingFailureText(job.failure)}` };
  if (input.loading || input.capability === undefined || (job && ACTIVE_STATUSES.includes(job.status)))
    return { state: "loading" };
  if (input.result && input.result.modes === 0)
    return { state: "scientific_null", message: nullResultText(input.result.mode) };
  return { state: "ready" };
}

// ---- input compatibility ----

/** Why a mode cannot be chosen (null = usable): core-fixed needs the candidate source. */
export function modeDisabledReason(source: DockingLigandSource | null, mode: DockingMode): string | null {
  if (source === null) return "리간드 출처를 먼저 고르세요.";
  if (mode === "core_fixed" && source !== "candidate")
    return `코어 고정은 M17 후보 출처에서만 쓸 수 있습니다: ${dockingReasonText("mode_source_mismatch")}`;
  return null;
}

/** Receptor instance choice: not chosen yet, explicitly none (protein only), or one listed instance. */
export type InstanceChoice = { kind: "unset" } | { kind: "none" } | { kind: "instance"; residue: ExactResidueRef };

/** Why a box source cannot be chosen (null = usable): the instance range needs a chosen instance. */
export function boxSourceDisabledReason(boxSource: DockingBoxSource, instance: InstanceChoice): string | null {
  if (boxSource === "instance_range" && instance.kind !== "instance")
    return "수용체 안 인스턴스 범위는 뺄 리간드 인스턴스를 골랐을 때만 쓸 수 있습니다.";
  return null;
}

/** The seven residue fields only, in the server's order (nulls kept, never rebuilt from a display string). */
export function exactResidue(residue: ExactResidueRef): ExactResidueRef {
  return { model_number: residue.model_number, chain_auth: residue.chain_auth, chain_label: residue.chain_label,
    seq_auth: residue.seq_auth, seq_label: residue.seq_label, icode: residue.icode, resname: residue.resname };
}

export function sameResidue(a: ExactResidueRef, b: ExactResidueRef): boolean {
  return a.model_number === b.model_number && a.chain_auth === b.chain_auth && a.chain_label === b.chain_label &&
    a.seq_auth === b.seq_auth && a.seq_label === b.seq_label && a.icode === b.icode && a.resname === b.resname;
}

/** Instances of the chosen model only (a selection aid; the server checks the choice again). */
export function modelInstances(listing: { models: { model_number: number; instances: DockingReceptorInstance[] }[] },
  modelNumber: number | null): DockingReceptorInstance[] {
  return listing.models.find(model => model.model_number === modelNumber)?.instances ?? [];
}

// ---- form and job arguments ----

export interface DockingForm {
  receptorHandle: string | null;
  receptorModelNumber: number | null;
  connectivity: "pdb_conect" | "sidecar" | null;
  sidecarHandle: string | null;
  instance: InstanceChoice;
  ligandSource: DockingLigandSource | null;
  sdfHandle: string | null;
  candidateSetHandle: string | null;
  candidateId: string | null;
  parentSdfHandle: string | null;
  mode: DockingMode | null;
  boxSource: DockingBoxSource | null;
  /** Numbers as typed (trimmed before checking). */
  margin: string;
  center: [string, string, string];
  size: [string, string, string];
  seed: string;
  exhaustiveness: string;
  numModes: string;
  energyRange: string;
  conformers: string;
  acknowledgement: Record<DockingAcknowledgementKey, boolean>;
}

/** Nothing chosen; adjustable values show their defaults; the seed is empty (required); no box/mode preselected. */
export function initialDockingForm(): DockingForm {
  return { receptorHandle: null, receptorModelNumber: null, connectivity: null, sidecarHandle: null,
    instance: { kind: "unset" }, ligandSource: null, sdfHandle: null, candidateSetHandle: null, candidateId: null,
    parentSdfHandle: null, mode: null, boxSource: null, margin: String(MARGIN_DEFAULT_A), center: ["", "", ""],
    size: ["", "", ""], seed: "", exhaustiveness: String(EXHAUSTIVENESS_DEFAULT), numModes: String(NUM_MODES_DEFAULT),
    energyRange: String(ENERGY_RANGE_DEFAULT), conformers: String(CONFORMERS_DEFAULT),
    acknowledgement: { keep_input_protonation: false, tool_assigned_types_charges: false, rigid_no_optimization: false } };
}

export function acknowledgementComplete(ack: Record<DockingAcknowledgementKey, boolean>): boolean {
  return ACKNOWLEDGEMENT_KEYS.every(key => ack[key] === true);
}

const INT_RE = /^(?:0|[1-9][0-9]*)$/;
/** Plain decimal syntax (same as the M17 filter bounds); no hexadecimal, no "Infinity", no blanks. */
const NUMBER_RE = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/;

function intIn(text: string, low: number, high: number): number | null {
  const trimmed = text.trim();
  if (!INT_RE.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isSafeInteger(value) && value >= low && value <= high ? value : null;
}

function numberIn(text: string, low: number, high: number): number | null {
  const trimmed = text.trim();
  const value = Number(trimmed);
  return NUMBER_RE.test(trimmed) && Number.isFinite(value) && value >= low && value <= high ? value + 0 : null;
}

export type ArgsCheck<T> = { ok: true; args: T } | { ok: false; errors: string[] };

const AXES = ["x", "y", "z"] as const;

/**
 * The `qvina_dock_v1` job arguments exactly as `docking_inputs.validate_arguments` accepts them: every top-level key,
 * all values explicit, `conformers` only for `core_fixed` (left out for free docking), a range box `{source,
 * margin_A}` or a manual box `{source, center_A, size_A}`, and all three acknowledgements true. The server checks
 * everything again; these checks only keep an impossible request from being sent.
 */
export function dockingArgs(form: DockingForm): ArgsCheck<DockingArgs> {
  const errors: string[] = [];
  if (!form.receptorHandle) errors.push("수용체 가져오기를 고르세요.");
  if (form.receptorModelNumber === null || !Number.isSafeInteger(form.receptorModelNumber) ||
      form.receptorModelNumber < 1) errors.push("수용체 모델 번호를 고르세요.");
  if (form.connectivity === null) errors.push("연결 정보(PDB CONECT 또는 결합 사이드카)를 고르세요.");
  if (form.connectivity === "sidecar" && !form.sidecarHandle) errors.push("결합 사이드카 가져오기를 고르세요.");
  if (form.instance.kind === "unset") errors.push("뺄 리간드 인스턴스를 고르거나 \"없음(단백질만)\"을 고르세요.");
  if (form.ligandSource === null) errors.push("리간드 출처를 고르세요.");
  if (form.ligandSource === "sdf" && !form.sdfHandle) errors.push("리간드 3D SDF 가져오기를 고르세요.");
  if (form.ligandSource === "candidate") {
    if (!form.candidateSetHandle) errors.push("후보 집합을 고르세요.");
    if (!form.candidateId) errors.push("후보를 고르세요.");
    if (!form.parentSdfHandle) errors.push("후보 집합의 부모 3D SDF 가져오기를 고르세요.");
  }
  if (form.mode === null) errors.push("방식(자유 도킹 | 코어 고정)을 고르세요.");
  else {
    const reason = form.ligandSource === null ? null : modeDisabledReason(form.ligandSource, form.mode);
    if (reason) errors.push(reason);
  }
  if (form.boxSource === null) errors.push("상자 출처를 고르세요.");
  else {
    const reason = boxSourceDisabledReason(form.boxSource, form.instance);
    if (reason) errors.push(`${reason} (box_invalid)`);
  }
  let box: DockingArgs["box"] | null = null;
  if (form.boxSource === "manual") {
    const center = form.center.map(text => numberIn(text, -MAX_BOX_CENTER_ABS_A, MAX_BOX_CENTER_ABS_A));
    const size = form.size.map(text => numberIn(text, BOX_SIDE_MIN_A, BOX_SIDE_MAX_A));
    center.forEach((value, i) => { if (value === null)
      errors.push(`상자 중심 ${AXES[i]}: 유한한 숫자(Å)를 입력하세요 (box_invalid).`); });
    size.forEach((value, i) => {
      if (value !== null) return;
      const typed = Number(form.size[i].trim());
      errors.push(NUMBER_RE.test(form.size[i].trim()) && Number.isFinite(typed) && typed > BOX_SIDE_MAX_A
        ? `상자 크기 ${AXES[i]}: 한 변은 ${BOX_SIDE_MAX_A} Å 이하여야 합니다. 줄이지 않고 거부합니다 (box_too_large).`
        : `상자 크기 ${AXES[i]}: ${BOX_SIDE_MIN_A}–${BOX_SIDE_MAX_A} Å 사이의 숫자를 입력하세요 (box_invalid).`);
    });
    if (center.every(value => value !== null) && size.every(value => value !== null))
      box = { source: "manual", center_A: center as [number, number, number], size_A: size as [number, number, number] };
  } else if (form.boxSource !== null) {
    const margin = numberIn(form.margin, MARGIN_MIN_A, MARGIN_MAX_A);
    if (margin === null) errors.push(`상자 여백: ${MARGIN_MIN_A}–${MARGIN_MAX_A} Å 사이의 숫자를 입력하세요 (box_invalid).`);
    else box = { source: form.boxSource, margin_A: margin };
  }
  const seed = intIn(form.seed, SEED_MIN, SEED_MAX);
  if (seed === null) errors.push(`seed: ${SEED_MIN}–${SEED_MAX} 사이의 정수를 입력하세요(필수).`);
  const exhaustiveness = intIn(form.exhaustiveness, EXHAUSTIVENESS_MIN, EXHAUSTIVENESS_MAX);
  if (exhaustiveness === null)
    errors.push(`exhaustiveness: ${EXHAUSTIVENESS_MIN}–${EXHAUSTIVENESS_MAX} 사이의 정수를 입력하세요.`);
  const numModes = intIn(form.numModes, NUM_MODES_MIN, NUM_MODES_MAX);
  if (numModes === null) errors.push(`num_modes: ${NUM_MODES_MIN}–${NUM_MODES_MAX} 사이의 정수를 입력하세요.`);
  const energyRange = numberIn(form.energyRange, ENERGY_RANGE_MIN, ENERGY_RANGE_MAX);
  if (energyRange === null)
    errors.push(`energy_range: ${ENERGY_RANGE_MIN}–${ENERGY_RANGE_MAX} kcal/mol 사이의 숫자를 입력하세요.`);
  const conformers = form.mode === "core_fixed" ? intIn(form.conformers, CONFORMERS_MIN, CONFORMERS_MAX) : null;
  if (form.mode === "core_fixed" && conformers === null)
    errors.push(`conformers: ${CONFORMERS_MIN}–${CONFORMERS_MAX} 사이의 정수를 입력하세요.`);
  if (!acknowledgementComplete(form.acknowledgement))
    errors.push(`확인 세 항목을 모두 체크하세요 (acknowledgement_missing).`);
  if (errors.length || !form.receptorHandle || form.receptorModelNumber === null || form.instance.kind === "unset" ||
      form.ligandSource === null || form.mode === null || box === null || seed === null || exhaustiveness === null ||
      numModes === null || energyRange === null) return { ok: false, errors };
  const ligand: DockingArgs["ligand"] = form.ligandSource === "sdf"
    ? { source: "sdf", sdf_handle: form.sdfHandle as string }
    : { source: "candidate", candidate_set_handle: form.candidateSetHandle as string,
      candidate_id: form.candidateId as string, parent_sdf_handle: form.parentSdfHandle as string };
  const parameters: DockingArgs["parameters"] = { seed, exhaustiveness, num_modes: numModes, energy_range: energyRange };
  if (form.mode === "core_fixed") parameters.conformers = conformers as number;
  return { ok: true, args: {
    receptor_handle: form.receptorHandle,
    receptor_model_number: form.receptorModelNumber,
    connectivity: form.connectivity === "sidecar" ? { kind: "sidecar", sidecar_handle: form.sidecarHandle as string }
      : { kind: "pdb_conect", sidecar_handle: null },
    receptor_instance: form.instance.kind === "instance" ? exactResidue(form.instance.residue) : null,
    ligand, mode: form.mode, box, parameters,
    acknowledgement: { keep_input_protonation: true, tool_assigned_types_charges: true, rigid_no_optimization: true },
  } };
}

// ---- late responses (run + selection key + request sequence) ----

export interface DockingStamp { runId: string | null; key: string | null; seq: number }

/** Applied only when run, selection key and request sequence are all still current. */
export function dockingResponseCurrent(captured: DockingStamp, live: DockingStamp): boolean {
  return captured.runId !== null && captured.runId === live.runId && captured.key === live.key &&
    captured.seq === live.seq;
}

/** Key of the input selection (receptor, model, connectivity, instance, ligand handles and candidate). */
export function dockingInputKey(form: Pick<DockingForm, "receptorHandle" | "receptorModelNumber" | "connectivity" |
  "sidecarHandle" | "instance" | "ligandSource" | "sdfHandle" | "candidateSetHandle" | "candidateId" |
  "parentSdfHandle">): string {
  return JSON.stringify([form.receptorHandle, form.receptorModelNumber, form.connectivity, form.sidecarHandle,
    form.instance.kind === "instance" ? exactResidue(form.instance.residue) : form.instance.kind, form.ligandSource,
    form.sdfHandle, form.candidateSetHandle, form.candidateId, form.parentSdfHandle]);
}

// ---- jobs (POST /jobs → /start → 409 approval → /jobs/approve → /start → GET /jobs/{id}) ----

/** One job at a time: null = a docking job may be submitted. */
export function dockingSubmitBlockedReason(input: { capability: CapabilityLike | null | undefined; busy: boolean;
  activeJob: { status: string } | null; check: ArgsCheck<DockingArgs> }): string | null {
  if (!input.capability?.available) return dockingCapabilityText(input.capability ?? null);
  if (input.busy) return "요청을 처리하는 중입니다.";
  if (input.activeJob && ACTIVE_STATUSES.includes(input.activeJob.status))
    return "진행 중인 작업이 끝난 뒤 시작할 수 있습니다(한 번에 한 작업).";
  if (!input.check.ok) return input.check.errors.join(" ");
  return null;
}

export type DockingJobPhase = "none" | "saved" | "awaiting_approval" | "running" | "done" | "failed" | "cancelled";

/** `approvalPending`: the last start answered 409 with the docking approval request. */
export function dockingJobPhase(job: { status: string } | null, approvalPending: boolean): DockingJobPhase {
  if (!job) return "none";
  if (approvalPending && ACTIVE_STATUSES.includes(job.status)) return "awaiting_approval";
  if (job.status === "queued") return "saved";
  if (job.status === "claimed" || job.status === "running") return "running";
  if (job.status === "done") return "done";
  if (job.status === "cancelled") return "cancelled";
  return "failed";
}

export function dockingJobText(job: Pick<DockingJob, "status" | "cancel_requested" | "failure"> | null,
  approvalPending: boolean): string {
  switch (dockingJobPhase(job, approvalPending)) {
    case "none": return "도킹 작업 없음";
    case "saved": return "도킹 작업이 저장되었습니다. 시작을 누르면 실제 계산이 실행됩니다(비싼 계산 예산 1단위).";
    case "awaiting_approval": return "비용이 드는 실제 계산 승인이 필요합니다(비싼 계산 예산 1단위). 승인한 뒤 시작을 다시 누르세요.";
    case "running": return `도킹 작업 실행 중${job?.cancel_requested ? " · 취소 요청됨" : ""}`;
    case "done": return "도킹 작업 완료";
    case "cancelled": return "도킹 작업 취소됨 (결과를 저장하지 않았습니다)";
    default:
      return job && ["failed", "interrupted"].includes(job.status) ? `도킹 작업 실패: ${dockingFailureText(job.failure)}`
        : `도킹 작업 실패: 알 수 없는 작업 상태 (${job?.status})`;
  }
}

/** Submission is idempotent: identical inputs return the existing job; a dry-run run returns a plan only. */
export function dockingSubmitText(result: { plan_only: true } | Pick<DockingJob, "job_id" | "status">): string {
  if ("plan_only" in result) return "dry-run run이라 계획만 만들었습니다. 실제 계산과 결과 객체는 없습니다.";
  if (result.status === "queued") return dockingJobText({ status: "queued", cancel_requested: false, failure: null }, false);
  return `같은 입력의 기존 작업을 다시 표시합니다 · ${result.job_id} · ${result.status} (새 작업을 만들지 않았습니다)`;
}

export function dockingApprovalRequired(status: number, approval: { gate: string; tool: string } | undefined): boolean {
  return status === 409 && approval?.gate === "expensive_first_call" && approval.tool === DOCKING_TOOL;
}

// ---- numbers and labels (display only; stored values, decimal-string ROUND_HALF_UP, never toFixed) ----

/** Stored `score_kcal_mol` with one decimal, e.g. -7.25 -> "-7.3" (no unit: the label carries it). */
export function scoreText(value: number): string { return decimalHalfUp(value, 1); }

/** Stored distance (Å) with two decimals, e.g. 2.675 -> "2.68 Å". */
export function distanceText(value: number): string { return `${decimalHalfUp(value, 2)} Å`; }

/** Stored value or "해당 없음" when the field does not apply to this mode (never 0). */
export function optionalDistanceText(value: number | null): string {
  return value === null ? "해당 없음" : distanceText(value);
}

export function countText(value: number): string { return String(value); }

export function tripleText(values: readonly number[]): string {
  return `(${values.map(value => decimalHalfUp(value, 2)).join(", ")}) Å`;
}

const BOX_SOURCE_LABEL: Record<DockingBoxSource, string> = { ligand_range: "리간드 범위+여백",
  instance_range: "수용체 안 인스턴스 범위+여백", manual: "직접 입력" };

export function boxSourceLabel(source: DockingBoxSource): string { return BOX_SOURCE_LABEL[source]; }

/** Stored box: centre and size with two decimals, the source and its margin. */
export function boxText(box: DockingResult["box"]): string {
  const margin = box.margin_A === null ? "" : ` · 여백 ${decimalHalfUp(box.margin_A, 2)} Å`;
  return `중심 ${tripleText(box.center_A)} · 크기 ${tripleText(box.size_A)} · ${boxSourceLabel(box.source)}${margin}`;
}

export const MODE_LABEL: Record<DockingMode, string> = { free: "자유 도킹", core_fixed: "코어 고정(구속 샘플, 점수만)" };

/** Row name: free docking "모드 n(엔진 출력 순서)", core-fixed "샘플 n(점수 오름차순 나열)". */
export function modeRowLabel(mode: DockingMode, n: number): string {
  return mode === "core_fixed" ? `샘플 ${n}(점수 오름차순 나열)` : `모드 ${n}(엔진 출력 순서)`;
}

export function modeColumnLabel(mode: DockingMode): string { return mode === "core_fixed" ? "샘플" : "모드"; }

export function contactKindText(kind: GeometricContactType): string { return CONTACT_TYPE_LABEL[kind]; }

/** Display of one receptor residue (the seven stored fields stay the identity; this text is never parsed). */
export function residueText(residue: ExactResidueRef): string {
  return `모델 ${residue.model_number} · 체인 ${residue.chain_auth} · ${residue.resname} ${residue.seq_auth}${residue.icode}`;
}

export function receptorAtomText(atom: DockingReceptorAtom): string {
  return `${residueText(atom.residue)} · ${atom.atom_name}${atom.altloc ? ` (altloc ${atom.altloc})` : ""} · ` +
    `${atom.element} · site ${atom.site_index}`;
}

/** Ligand atom of a contact row: pose SDF serial, element and (core-fixed core atoms) the parent SDF serial. */
export function ligandAtomText(contact: Pick<DockingContact, "ligand_serial" | "ligand_element" |
  "ligand_parent_serial">): string {
  return `포즈 SDF ${contact.ligand_serial} · ${contact.ligand_element}` +
    (contact.ligand_parent_serial === null ? "" : ` · 부모 SDF ${contact.ligand_parent_serial}`);
}

/** Origin of the docked ligand's hydrogens and coordinates (candidate inputs are generated by RDKit). */
export function generatedText(generated: { hydrogens: boolean; coordinates: boolean }): string {
  const one = (value: boolean) => value ? "RDKit이 만든 것(생성됨)" : "입력 그대로";
  return `수소: ${one(generated.hydrogens)} · 3D 좌표: ${one(generated.coordinates)}`;
}

export function removedInstanceText(removed: DockingReceptorInstance | null): string {
  if (!removed) return "뺀 인스턴스 없음(단백질만)";
  const elements = Object.entries(removed.element_counts).map(([element, count]) => `${element} ${count}`).join(", ");
  return `${residueText(removed.residue)} · 원자 ${removed.atom_count}개(${elements})`;
}

// ---- screen wiring (T9: the panel keeps no decision of its own) ----

export const DOCKING_STATE_TEXT: Record<DockingPanelState["state"], string> = { loading: "불러오는 중", ready: "준비",
  scientific_null: "빈 과학 결과 (모드 0개)", failure: "실패", unavailable: "사용할 수 없음" };

/**
 * Applies a form edit and clears every choice the edit invalidates, so a stale choice is never sent: a new receptor
 * clears the model and the instance; a new model clears the instance; a new candidate set clears the candidate and
 * its parent SDF; leaving the sidecar clears its handle; core-fixed is dropped when the source is not a candidate;
 * the instance range is dropped when no instance is chosen. Nothing is chosen automatically in its place.
 */
export function patchDockingForm(form: DockingForm, patch: Partial<DockingForm>): DockingForm {
  const next: DockingForm = { ...form, ...patch };
  if (next.receptorHandle !== form.receptorHandle) {
    if (!("receptorModelNumber" in patch)) next.receptorModelNumber = null;
    if (!("instance" in patch)) next.instance = { kind: "unset" };
  }
  if (next.receptorModelNumber !== form.receptorModelNumber && !("instance" in patch)) next.instance = { kind: "unset" };
  if (next.candidateSetHandle !== form.candidateSetHandle) {
    if (!("candidateId" in patch)) next.candidateId = null;
    if (!("parentSdfHandle" in patch)) next.parentSdfHandle = null;
  }
  if (next.connectivity !== "sidecar") next.sidecarHandle = null;
  if (next.mode === "core_fixed" && next.ligandSource !== "candidate") next.mode = null;
  if (next.boxSource === "instance_range" && next.instance.kind !== "instance") next.boxSource = null;
  return next;
}

/** The docking job of this run that is still queued or running (the latest one), for re-attaching after a remount. */
export function dockingActiveJob<T extends { run_id: string; protocol_id: string; status: string }>(jobs: unknown,
  runId: string): T | null {
  if (!Array.isArray(jobs)) return null;
  return (jobs as T[]).filter(job => job && job.run_id === runId && job.protocol_id === DOCKING_PROTOCOL &&
    ACTIVE_STATUSES.includes(job.status)).at(-1) ?? null;
}

export function dockingJobActive(job: { status: string } | null): boolean {
  return !!job && ACTIVE_STATUSES.includes(job.status);
}

/** Imports of one kind, in creation order (the server's list); never filtered by name. */
export function importsOfKind<T extends { input_kind: string }>(imports: readonly T[], kind: string): T[] {
  return imports.filter(row => row.input_kind === kind);
}

/** Why no parent SDF can be chosen for a candidate set (null = at least one same-SHA ligand_sdf import exists). */
export function parentSdfMissingReason(set: { valid: boolean; parent_sdf_handles: string[] | null } | null): string | null {
  if (!set) return "후보 집합을 먼저 고르세요.";
  if (!set.valid) return `이 후보 집합은 읽을 수 없습니다: ${dockingReasonText("evidence_invalid")}`;
  if (!set.parent_sdf_handles?.length)
    return "후보 집합의 부모와 SHA-256이 같은 리간드 SDF 가져오기가 없습니다. 부모 3D SDF를 가져오세요 (parent_mismatch 방지).";
  return null;
}

const STEREO_FLAG_LABEL: Record<string, string> = { none: "입체 표시 없음", parent_stereo_lost: "부모 코어의 입체 지정이 사라짐",
  new_unspecified_center: "새로 생긴 미지정 입체 중심" };

/** M17 candidate `stereo_flag` as "한국어 (code)"; null when the ligand is not a candidate. */
export function stereoFlagText(flag: string | null): string {
  if (flag === null) return "해당 없음(SDF 출처)";
  return STEREO_FLAG_LABEL[flag] ? `${STEREO_FLAG_LABEL[flag]} (${flag})` : flag;
}

type SummaryResult = Pick<DockingResult, "method" | "inputs" | "box" | "parameters" | "engine" | "preparation" | "counts">;

/**
 * Summary lines of one stored result ([label, value]); every value is a stored field (rounded for display only).
 * The score name appears in full here; the table header uses `SCORE_COLUMN_LABEL`.
 */
export function dockingSummaryRows(result: SummaryResult): [string, string][] {
  const { inputs, parameters: values, engine, preparation, counts } = result;
  const ligand = inputs.ligand;
  const rows: [string, string][] = [
    ["점수", SCORE_LABEL],
    ["방식", `${MODE_LABEL[inputs.mode]} · ${result.method}`],
    ["엔진", `${engine.name} ${engine.version} · ${engine.package} · 실행 파일 SHA-256 ${engine.binary_sha256}`],
    ["입력 준비", `${preparation.tool} ${preparation.version} · RDKit ${preparation.rdkit_version} · 원자 유형 ` +
      `${preparation.atom_typing} · 부분 전하 ${preparation.charges}`],
    ["seed", String(values.seed)],
    ["값", `exhaustiveness ${values.exhaustiveness} · num_modes ${values.num_modes} · energy_range ` +
      `${decimalHalfUp(values.energy_range, 2)} kcal/mol · cpu ${values.cpu}` +
      (values.conformers === null ? "" : ` · conformers ${values.conformers}`)],
    ["상자", boxText(result.box)],
    ["수용체", `${inputs.receptor.handle} · SHA-256 ${inputs.receptor.sha256} · 모델 ${inputs.receptor.model_number} · ` +
      `연결 정보 ${inputs.receptor.connectivity.kind === "sidecar" ? `결합 사이드카 ${inputs.receptor.connectivity.sidecar_handle}`
        : "PDB CONECT"}`],
    ["뺀 인스턴스", removedInstanceText(inputs.receptor.removed_instance)],
    ["리간드 출처", ligand.source === "sdf" ? `3D SDF ${ligand.sdf_handle} · SHA-256 ${ligand.sdf_sha256}`
      : `M17 후보 ${ligand.candidate_id} · 후보 집합 ${ligand.candidate_set_handle} · 부모 SDF ${ligand.parent_sdf_handle} · ` +
        `부모 SHA-256 ${ligand.parent_sdf_sha256}`],
    ["생성 여부", generatedText(ligand.generated)],
    ["후보 stereo_flag", stereoFlagText(ligand.stereo_flag)],
    ["미지정 입체 중심 수", ligand.unspecified_stereo_centers === null ? "해당 없음(SDF 출처)"
      : countText(ligand.unspecified_stereo_centers)],
    [inputs.mode === "core_fixed" ? "샘플 수" : "모드 수", countText(counts.modes)],
  ];
  if (inputs.mode === "core_fixed")
    rows.push(["만든 형태 · 점수를 매긴 형태", `${counts.samples_generated === null ? "해당 없음" : countText(counts.samples_generated)}` +
      ` · ${counts.samples_scored === null ? "해당 없음" : countText(counts.samples_scored)}`]);
  return rows;
}

/** Mode table header for the result's mode (free docking has engine RMSD bounds; core-fixed the core deviation). */
export function modeTableHeaders(mode: DockingMode): string[] {
  const head = [modeColumnLabel(mode), SCORE_COLUMN_LABEL, "접촉 수(기하)", "최소 중원자 거리", "상자 밖 중원자 수"];
  return mode === "core_fixed" ? [...head, "코어 최대 이탈", "형태 번호"] : [...head, "엔진 RMSD 하한·상한(모드 1 기준)"];
}

/** One mode row as displayed (stored values only; `contact_count` is the server's count). */
export function modeTableCells(mode: DockingMode, row: DockingModeSummary): string[] {
  const head = [modeRowLabel(mode, row.mode), scoreText(row.score_kcal_mol), countText(row.contact_count),
    distanceText(row.min_heavy_atom_distance_A), countText(row.atoms_outside_box)];
  if (mode === "core_fixed")
    return [...head, optionalDistanceText(row.core_max_deviation_A),
      row.conformer_index === null ? "해당 없음" : String(row.conformer_index)];
  return [...head, row.engine_rmsd_lb_A === null || row.engine_rmsd_ub_A === null ? "해당 없음"
    : `${optionalDistanceText(row.engine_rmsd_lb_A)} · ${optionalDistanceText(row.engine_rmsd_ub_A)}`];
}

/** "접촉 n개 중 a–b" for a contact page; an empty mode says so (never shown as "not computed"). */
export function contactPageText(page: { total: number; offset: number; rows: readonly unknown[] }): string {
  if (page.total === 0) return "이 모드의 기하 접촉은 0개입니다(4.0 Å 안에 중원자 쌍 없음).";
  return `기하 접촉 ${page.total}개 중 ${page.offset + 1}–${page.offset + page.rows.length}`;
}

/** One stored result in the list (or why it cannot be read). */
export function dockingResultRowText(row: { created_seq: number; valid: boolean; reason_code: string | null;
  mode: DockingMode | null; ligand_source: DockingLigandSource | null; candidate_id: string | null; seed: number | null;
  box_source: DockingBoxSource | null; modes: number | null; null_result: boolean | null }): string {
  if (!row.valid) return `생성 순번 ${row.created_seq} · 읽을 수 없음: ${dockingReasonText(row.reason_code ?? "evidence_invalid")}`;
  const mode = row.mode ?? "free";
  const source = row.ligand_source === "candidate" ? `후보 ${row.candidate_id}` : "3D SDF";
  const count = row.null_result ? `${mode === "core_fixed" ? "샘플" : "모드"} 0개 (빈 과학 결과)`
    : `${mode === "core_fixed" ? "샘플" : "모드"} ${row.modes}개`;
  return `생성 순번 ${row.created_seq} · ${MODE_LABEL[mode]} · ${source} · seed ${row.seed} · ` +
    `${row.box_source ? boxSourceLabel(row.box_source) : ""} · ${count}`;
}

/** The report answer belongs to the chosen result (otherwise it is not shown as created). */
export function dockingReportMatches(artifact: { manifest: { schema: string; analysis_type: string; result_handle: string } },
  resultHandle: string): boolean {
  return artifact.manifest.schema === "method_report_manifest@1" && artifact.manifest.analysis_type === "ligand_docking" &&
    artifact.manifest.result_handle === resultHandle;
}

// ---- wording check (screen text never claims rank, best, improvement or binding strength) ----

// "최적화" (optimization, a process) is allowed: the spec's acknowledgement item says no optimization is done.
const FORBIDDEN = /순위|최고|최적(?!화)|개선|결합\s*강도|친화|ΔΔG|합성\s*가능|\brank|\bbest|optimal|improv|stronger|affinity/gi;

/**
 * Forbidden words found in screen text, line by line. A line exactly equal to a fixed limitation sentence is exempt;
 * on any other line only the exact score names are removed before the check (the rest of the line is checked).
 */
export function dockingForbiddenWords(text: string): string[] {
  const found: string[] = [];
  for (const line of text.split("\n")) {
    if (DOCKING_LIMITATIONS.includes(line)) continue;
    const checked = line.split(SCORE_LABEL).join("").split(SCORE_COLUMN_LABEL).join("");
    for (const match of checked.matchAll(FORBIDDEN)) found.push(match[0]);
  }
  return found;
}
