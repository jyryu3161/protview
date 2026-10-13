/**
 * Pure logic and wording of the M29 "구조 보완" area in the 단백질 공학 tab and of the M29 marks other screens show
 * (`.dryforge/spec.md` 3–8).
 *
 * Every number shown comes from the server (the preflight read, the stored `structure_repair@1` record, its atom pages)
 * and is shown as stored: this module never measures, counts, rounds or recomputes a value. The fixed sentences
 * (RP1–RP6, SO1–SO3, JW1) are copies of `backend/mw/structure_repair_constants.py` (a test compares them); the screens
 * show the sentences the server put in a response, never a sentence of their own. A repaired structure is only a
 * modelling input: it is offered to the M20 request and filtered out of every other structure list (viewer source,
 * comparison, analysis workflows, pockets, chemistry, numbering, reaction knowledge, the repair input itself).
 */
import type { RepairClass, RepairCollisionClass, RepairAddedAtomOrigin, RepairReferenceField, RepairResidue,
  StructureRepairBlocker, StructureRepairCapability, StructureRepairCollision, StructureRepairGap,
  StructureRepairJob, StructureRepairListRow, StructureRepairPreflight, StructureRepairRecord,
  StructureRepairReportArtifact, StructureRepairSubmission } from "./contracts";

// ---- names, closed sets, limits and fixed sentences (backend/mw/structure_repair_constants.py; change both) ----

export const REPAIR_TOOL = "repair_structure";
export const REPAIR_PROTOCOL = "pdbfixer_repair_v1";
export const REPAIR_KIND = "structure_repair";
export const REPAIR_SCHEMA = "structure_repair@1";
export const REPAIR_EVENT = "structure_repair_published";
export const REPAIR_PREFLIGHT_SCHEMA = "structure_repair_preflight@1";
export const REPAIR_POLICY = "complete_missing_atoms_v1";
export const REPAIR_REPORT_TYPE = "structure_repair";
export const REPAIR_REPORT_NAME = "구조 보완 보고서";
/** `POST /jobs` `timeout_s` (not an argument, not in the call key); the screen always sends the default. */
export const REPAIR_TIMEOUT_DEFAULT_S = 120;
export const REPAIR_TIMEOUT_MAX_S = 240;
export const MAX_GAP_RESIDUES = 20;
export const ATOM_PAGE_DEFAULT = 100;
export const ATOM_PAGE_RANGE: readonly [number, number] = [1, 200];
export const REPAIR_CLASSES: readonly RepairClass[] = ["chain_parts_merged", "side_chain_atoms_added",
  "terminal_oxt_added", "internal_gap_filled", "nonstandard_replaced"];
export const REFUSAL_REASONS = ["chain_identity_duplicate", "unsupported_residue", "unexpected_atoms",
  "backbone_atoms_missing", "gap_listing_missing", "gap_too_long", "m7_condition_unsupported", "atom_limit_exceeded",
  "nothing_to_repair"] as const;
export const ADMISSION_REASON_CODES = ["unknown_field", "confirmation_missing", "argument_invalid", "structure_invalid",
  "already_repaired"] as const;
export const UNAVAILABLE_REASON_CODES = ["process_identity_unavailable", "openmm_unavailable",
  "pdbfixer_unavailable"] as const;
export const FAILURE_REASON_CODES = ["repair_incomplete", "repair_modeling_failed", "coordinates_changed",
  "unexpected_atoms_added", "repair_identity_mismatch", "repair_record_mismatch", "resource_exceeded",
  "engine_failed"] as const;
export const REPAIRED_NOT_ACCEPTED = "repaired_structure_not_accepted";
export const COLLISION_CLASSES: readonly RepairCollisionClass[] = ["protein", "ligand", "metal", "water", "other"];
export const ADDED_ATOM_ORIGINS: readonly RepairAddedAtomOrigin[] = ["side_chain", "oxt", "gap_residue"];

export const RP1 = "보완 구조의 추가 원자는 PDBFixer가 만든 모델링 좌표이며 실험으로 관측한 좌표가 아니다.";
export const RP2 = "실험으로 관측한 원자의 좌표는 입력 그대로이며 추가·치환·원자 순서 변경만 기록했다.";
export const RP3 = "메운 틈 구간은 단순한 기하로 놓은 가상 좌표이며 실제 구조가 아니다.";
export const RP4 = "사슬의 관측된 끝이 서열의 끝과 다른 곳에도 말단 원자를 두었으므로 그 끝의 화학은 실제와 다를 수 있다.";
export const RP5 = "MSE는 MET로 바꾸었고 셀레늄 원자는 황 원자로 대체했다. 원래 이름은 보완 기록에 있다.";
export const RP6 = "같은 저자 체인 이름의 조각을 한 체인으로 합쳐 원자 순서가 바뀌었다. 잔기 식별자와 좌표는 그대로이다.";
export const LIMITATION_ORDER: readonly string[] = [RP1, RP2, RP3, RP4, RP5, RP6];
export const SO1 = "이 결과의 구조는 보완 구조이다. 일부 잔기와 원자는 PDBFixer가 만든 모델링 좌표이며 실험으로 관측한 좌표가 아니다.";
export const SO2 = "이 위치·보호 판정에는 모델링 원자 또는 잔기가 들어 있다.";
export const SO3 = "번호 대응·참조 주석·촉매 연결·포켓 결과는 보완 전 원본 구조에서 만든 것이며 잔기 식별자 일치로 이었다. " +
  "모델링한 잔기는 검사하지 않았다.";
export const JW1 = "이 후보는 보완 구조 기준이며, 전송 본문은 이 사실을 담지 않는다.";
/** Every fixed sentence (a screen line equal to one of these is exempt from the wording check). */
export const REPAIR_FIXED_LINES: readonly string[] = [...LIMITATION_ORDER, SO1, SO2, SO3, JW1];

// ---- screen wording (Korean; identifiers are not translated) ----

export const PANEL_TITLE = "구조 보완";
export const NULL_TEXT = "—";
export const REPAIRED_BADGE = "보완 구조";
export const RECORD_LABEL = "보완 기록";
export const OPEN_RECORD_TEXT = "보완 기록 열기";
export const MODELED_NOT_CHECKED_TEXT = "검사 안 함(모델링 잔기)";
export const UNDETERMINED_TEXT = "—(판정 불가)";
export const STATE_TEXT = { loading: "불러오는 중", ready: "준비", empty: "빈 결과", failed: "실패",
  unavailable: "사용할 수 없음" } as const;
export const METHOD_NOTE = "PDBFixer가 승인된 결손(체인 조각 합치기·곁사슬 원자·C 말단 OXT·내부 틈·MSE→MET)만 보완한 새 " +
  "전처리 구조를 만듭니다. 실험으로 관측한 원자는 바꾸지 않습니다. 보완 구조는 변이 후보·변이 구조 모델링·서열 GA·단백질 " +
  "JEV 루프와 그 도킹에서만 쓰고, 구조 분석 탭의 뷰어·접촉·포켓·화학·번호 대응·참조 주석에는 쓰지 않습니다.";
export const BUDGET_NOTE = "보완 작업 하나는 비싼 계산 1단위입니다. 이 run의 첫 비싼 계산이면 승인이 필요합니다. 실패·취소·시간 " +
  "초과로 끝난 작업은 결과를 남기지 않습니다.";
export const CONFIRM_TEXT = `보완 정책 ${REPAIR_POLICY}: 빠진 원자와 틈 잔기를 PDBFixer가 만든 모델링 좌표로 채운 구조가 ` +
  "만들어짐을 확인했습니다.";
export const TIMEOUT_NOTE = `작업 시간 상한 ${REPAIR_TIMEOUT_DEFAULT_S}초 (고정값으로 보냄)`;
export const NO_AUTO_NOTE = "전처리 구조·보완 기록은 자동으로 고르거나 열지 않습니다.";
export const COLLISION_NOTE = "새 중원자마다 같은 잔기·바로 이웃 잔기를 뺀 가장 가까운 중원자까지의 거리입니다(기록만 하며 " +
  "보완을 거절하지 않음). 상대 원자가 없는 분류는 거리가 없을 뿐이며 충돌이 없다는 뜻이 아닙니다.";
export const NUMBER_NOTE = "숫자는 저장된 서버 값 그대로이며 화면은 계산·반올림하지 않습니다.";
export const REPAIRED_POCKET_NOTE = "보완 구조로는 포켓을 검출하지 않으므로(모델링 경로 밖) 같은 구조 포켓 결과는 없습니다. " +
  "보완 전 원본 구조의 포켓 결과만 고를 수 있습니다.";
export const REPAIRED_REFERENCE_NOTE = "보완 구조를 고르면 번호 대응·참조 주석·효소 반응 지식·포켓 결과는 이 구조와 보완 전 원본 " +
  "구조의 것을 고를 수 있습니다(잔기 식별자 일치로 잇고, 모델링한 잔기는 검사하지 않음).";

export const CLASS_LABEL: Record<RepairClass, string> = { chain_parts_merged: "체인 조각 합치기",
  side_chain_atoms_added: "곁사슬 원자 더하기", terminal_oxt_added: "C 말단 OXT 더하기",
  internal_gap_filled: "내부 틈 메우기", nonstandard_replaced: "MSE→MET 치환" };
export const COLLISION_LABEL: Record<RepairCollisionClass, string> = { protein: "단백질", ligand: "리간드",
  metal: "금속", water: "물", other: "기타" };
export const ORIGIN_LABEL: Record<RepairAddedAtomOrigin, string> = { side_chain: "곁사슬", oxt: "C 말단 OXT",
  gap_residue: "틈 잔기" };

const REASON_TEXT: Record<string, string> = {
  chain_identity_duplicate: "서로 다른 단백질 체인이 같은 저자 체인 이름을 씀",
  unsupported_residue: "지원하지 않는 잔기",
  unexpected_atoms: "표준 템플릿에 없는 관측 원자",
  backbone_atoms_missing: "뼈대 원자(N·CA·C·O) 결손",
  gap_listing_missing: "파일의 서열·미관측 잔기 목록으로 틈 잔기를 확정할 수 없음",
  gap_too_long: `틈 하나가 ${MAX_GAP_RESIDUES}잔기를 넘음`,
  m7_condition_unsupported: "보완으로 풀리지 않는 M7 사전 검사 조건",
  atom_limit_exceeded: "보완 뒤 단백질 중원자가 M7 상한을 넘음",
  nothing_to_repair: "보완할 것이 없음",
  unknown_field: "알 수 없는 인자",
  confirmation_missing: "보완 정책 확인 없음",
  argument_invalid: "인자 값이 올바르지 않음",
  structure_invalid: "이 run의 전처리 구조가 아님",
  already_repaired: "이미 보완한 구조",
  process_identity_unavailable: "프로세스 신원 확인 장치를 쓸 수 없음",
  openmm_unavailable: "고정 OpenMM 환경을 쓸 수 없음",
  pdbfixer_unavailable: "고정 PDBFixer를 쓸 수 없음",
  repair_not_possible: "보완할 수 없음",
  repair_incomplete: "보완 구조가 M7 사전 검사를 통과하지 못함",
  repair_modeling_failed: "PDBFixer 모델링 실패",
  coordinates_changed: "관측 원자의 값이 입력과 다름",
  unexpected_atoms_added: "허용 밖 원자가 더해짐",
  repair_identity_mismatch: "새 잔기 식별자가 목록과 다름",
  repair_record_mismatch: "보완 기록이 저장값과 다름",
  resource_exceeded: "크기 상한 초과",
  engine_failed: "엔진 실패",
  worker_version_invalid: "작업 모듈 고정값이 바뀜",
  repaired_structure_not_accepted: "보완 구조는 모델링 경로에서만 쓴다",
  method_evidence_invalid: "저장된 증거가 검증되지 않음",
  input_invalid: "입력 거절",
  precondition: "실행 조건 없음",
  fatal: "잘못된 오류 응답",
};

/** "한국어 (code)"; an unknown code is shown as itself. */
export function repairReasonText(code: string): string {
  return REASON_TEXT[code] ? `${REASON_TEXT[code]} (${code})` : code;
}

// ---- small value texts (stored values as they are; "—" with a reason for none) ----

/** A stored number as stored: never rounded, never re-formatted. */
export function valueText(value: number | null | undefined, reason?: string): string {
  if (value === null || value === undefined) return reason ? `${NULL_TEXT} (${reason})` : NULL_TEXT;
  return String(value);
}

/** Author notation of a residue: chain/number+icode/name (the stored values; null kept as "null"). */
export function residueText(ref: RepairResidue): string {
  return `${ref.chain_auth}/${ref.seq_auth}${ref.icode ?? ""}/${ref.resname}`;
}

/** The 7 identity fields as stored; a null field is shown as "null", never as 0 or as the author value. */
export function residueFieldsText(ref: RepairResidue): string {
  const show = (value: string | number | null) => value === null ? "null" : String(value);
  return `모델 ${ref.model_number} · auth ${ref.chain_auth}/${ref.seq_auth} · icode ${ref.icode === null ? "null"
    : JSON.stringify(ref.icode)} · label ${show(ref.chain_label)}/${show(ref.seq_label)} · ${ref.resname}`;
}

function isResidue(value: unknown): value is RepairResidue {
  return typeof value === "object" && value !== null && "chain_auth" in value && "seq_auth" in value &&
    "resname" in value;
}

/** One `detail` value of a blocker: residues by notation, lists joined, anything else as JSON text. */
export function detailValueText(value: unknown): string {
  if (isResidue(value)) return residueText(value);
  if (Array.isArray(value)) return value.map(detailValueText).join(", ");
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function detailText(detail: Record<string, unknown> | null | undefined): string {
  if (!detail) return "";
  return Object.entries(detail).map(([key, value]) => `${key}: ${detailValueText(value)}`).join(" · ");
}

export function blockerText(blocker: StructureRepairBlocker): { reason: string; where: string; detail: string } {
  const where = blocker.residue ? residueText(blocker.residue) : blocker.chain_auth !== undefined
    ? `체인 ${blocker.chain_auth}` : NULL_TEXT;
  return { reason: repairReasonText(blocker.reason_code), where, detail: detailText(blocker.detail) };
}

export function shortHandle(handle: string): string {
  return handle.split("/").at(-1)?.slice(0, 12) ?? handle;
}

// ---- repaired structures in the run's event log (published by the repair job; the mark is server-side) ----

export interface RepairLink {
  /** The repaired `prepared_structure@1` handle. */
  structure: string;
  /** Its `structure_repair@1` record. */
  record: string;
  /** The original prepared structure the job repaired (its submitted `structure`), null when the log does not say. */
  source: string | null;
  /** Sequence number of the publication event. */
  seq: number;
}

type LooseEvent = { type: string };
const field = (event: LooseEvent, key: string): unknown => (event as unknown as Record<string, unknown>)[key];

/** Every published repair of this run, in publication order (one row per repaired structure). */
export function repairLinks(events: readonly LooseEvent[]): RepairLink[] {
  const submitted = new Map<string, string>();
  for (const event of events) {
    if (event.type !== "job_submitted") continue;
    const job = field(event, "job") as { job_id?: unknown; protocol_id?: unknown; parameters?: { structure?: unknown } }
      | undefined;
    if (job && job.protocol_id === REPAIR_PROTOCOL && typeof job.job_id === "string" &&
        typeof job.parameters?.structure === "string") submitted.set(job.job_id, job.parameters.structure);
  }
  const rows: RepairLink[] = [];
  const seen = new Set<string>();
  for (const event of events) {
    if (event.type !== REPAIR_EVENT) continue;
    const structure = field(event, "prepared_structure"), record = field(event, "record");
    const jobId = field(event, "job_id"), seq = field(event, "seq");
    if (typeof structure !== "string" || typeof record !== "string" || seen.has(structure)) continue;
    seen.add(structure);
    rows.push({ structure, record, source: typeof jobId === "string" ? submitted.get(jobId) ?? null : null,
      seq: typeof seq === "number" ? seq : 0 });
  }
  return rows;
}

/** Handles of this run's repaired structures (the structures a viewer, chemistry, pocket or numbering list drops). */
export function repairedStructureHandles(events: readonly LooseEvent[]): Set<string> {
  return new Set(repairLinks(events).map(link => link.structure));
}

/** A structure list without the repaired structures (order kept). */
export function withoutRepaired<T extends { handle: string }>(items: readonly T[], repaired: ReadonlySet<string>): T[] {
  return items.filter(item => !repaired.has(item.handle));
}

/** The repair input: this run's prepared structures (the `prepare_structure` outputs) that are not repaired ones. */
export function repairInputStructures<T extends { handle: string }>(prepared: readonly T[],
                                                                   events: readonly LooseEvent[]): T[] {
  return withoutRepaired(prepared, repairedStructureHandles(events));
}

export interface MutationStructureRow { handle: string; seq: number; repair: RepairLink | null }

/** M20 structure choices: the prepared structures plus the repaired ones (badge "보완 구조"), in event order. */
export function mutationStructureRows(prepared: readonly { handle: string; seq: number }[],
                                      links: readonly RepairLink[]): MutationStructureRow[] {
  const repaired = new Map(links.map(link => [link.structure, link]));
  const rows: MutationStructureRow[] = prepared.filter(row => !repaired.has(row.handle))
    .map(row => ({ handle: row.handle, seq: row.seq, repair: null }));
  for (const link of links) rows.push({ handle: link.structure, seq: link.seq, repair: link });
  return rows.sort((a, b) => a.seq - b.seq);
}

/**
 * The structures whose reference results (pocket set, numbering map, annotation, reaction knowledge) an M20 request on
 * `structure` may name (spec 5.3): the structure itself and, for a repaired structure, its original prepared structure.
 */
export function referenceStructures(structure: string | null, links: readonly RepairLink[]): string[] {
  if (structure === null) return [];
  const source = links.find(link => link.structure === structure)?.source ?? null;
  return source === null ? [structure] : [structure, source];
}

// ---- M20 position marks (read layer of a set on a repaired structure) ----

/** "검사 안 함(모델링 잔기)" for a reference field the server marks as not checked; null otherwise (stored value shown). */
export function referenceNotCheckedText(row: { reference_not_checked?: readonly RepairReferenceField[] },
                                        fieldName: RepairReferenceField): string | null {
  return row.reference_not_checked?.includes(fieldName) ? MODELED_NOT_CHECKED_TEXT : null;
}

/** The `modeled_basis` cell: null when the row carries no mark (a set on any other structure). */
export function modeledBasisText(row: { modeled_basis?: boolean }): string | null {
  if (row.modeled_basis === undefined) return null;
  return row.modeled_basis ? "모델링 원자·잔기 포함" : "관측 원자만";
}

// ---- five states, late responses, open requests ----

export type RepairPanelState =
  | { state: "loading" } | { state: "ready" } | { state: "empty"; message: string }
  | { state: "failed"; message: string } | { state: "unavailable"; reason: string };

type CapabilityLike = Pick<StructureRepairCapability, "available" | "reason_code" | "reason">;

export function capabilityText(capability: CapabilityLike | null): string {
  if (capability === null) return "서버가 구조 보완 기능을 알리지 않습니다.";
  const code = capability.reason_code;
  return code ? `${capability.reason ?? repairReasonText(code)} (${code})` : capability.reason ?? "사용할 수 없습니다.";
}

export function repairPanelState(input: { runId: string | null; capability: CapabilityLike | null | undefined;
  loading?: boolean; error?: string | null; structures?: readonly unknown[]; repairs?: readonly unknown[] }):
  RepairPanelState {
  if (input.runId === null) return { state: "unavailable", reason: "현재 run이 없습니다. 구조 분석 탭에서 run을 고르세요." };
  if (input.capability === undefined) return { state: "loading" };
  if (input.capability === null || !input.capability.available)
    return { state: "unavailable", reason: capabilityText(input.capability) };
  if (input.error) return { state: "failed", message: input.error };
  if (input.loading || input.structures === undefined || input.repairs === undefined) return { state: "loading" };
  if (!input.repairs.length) return { state: "empty", message: input.structures.length
    ? "이 run에 보완 기록이 없습니다. 위에서 전처리 구조를 골라 사전 검사를 보세요."
    : "이 run에 전처리 구조가 없습니다. 구조 분석 탭에서 먼저 전처리하세요." };
  return { state: "ready" };
}

export const REPAIR_AREAS = ["events", "list", "preflight", "job", "cancel", "detail", "atoms", "report",
  "reports"] as const;
export type RepairArea = typeof REPAIR_AREAS[number];
export interface RepairStamp { runId: string | null; handle: string | null; seq: number }

/** Applied only when run, the area's handle (structure or record) and its request number are all still current. */
export function repairResponseCurrent(captured: RepairStamp, live: RepairStamp): boolean {
  return captured.runId !== null && captured.runId === live.runId && captured.handle === live.handle &&
    captured.seq === live.seq;
}

/** A report that was saved is announced while the run is unchanged, even when the late inline display is dropped. */
export function repairReportSavedForRun(captured: RepairStamp, liveRunId: string | null): boolean {
  return captured.runId !== null && captured.runId === liveRunId;
}

/** "보완 기록 열기" from another area: a request of this run that the area has not handled yet (never replayed). */
export interface RepairOpenRequest { runId: string; record: string; seq: number; handled: boolean }
export function repairOpenPending(request: RepairOpenRequest | null, runId: string | null): string | null {
  return request !== null && !request.handled && runId !== null && request.runId === runId ? request.record : null;
}

// ---- preflight (a free read) ----

export function preflightMatches(value: unknown, structure: string): value is StructureRepairPreflight {
  const preflight = value as Partial<StructureRepairPreflight> | null;
  return typeof preflight === "object" && preflight !== null && preflight.schema === REPAIR_PREFLIGHT_SCHEMA &&
    preflight.starts_job === false && preflight.structure === structure;
}

export interface PreflightView {
  admitted: boolean; admissionText: string; repairableText: string;
  blockers: { reason: string; where: string; detail: string; code: string }[];
  chainParts: { chain: string; parts: string }[];
  sideChain: { residue: string; fields: string; missing: string }[];
  oxt: { residue: string; fields: string }[];
  gaps: { chain: string; after: string; before: string; length: string; residues: string }[];
  nonstandard: { residue: string; fields: string; to: string }[];
  expectedText: string; budgetText: string; shortfallText: string | null; statements: string[];
}

export function gapRowText(gap: StructureRepairGap): { chain: string; after: string; before: string; length: string;
  residues: string } {
  return { chain: gap.chain_auth, after: residueText(gap.after_residue), before: residueText(gap.before_residue),
    length: valueText(gap.length), residues: gap.residues.map(residueText).join(", ") };
}

export function preflightView(preflight: StructureRepairPreflight): PreflightView {
  const admission = preflight.admission;
  const admitted = admission?.admitted === true;
  const admissionCode = admission?.reason_code ?? admission?.error ?? null;
  const admissionText = admission === null ? `${NULL_TEXT} (입장 판정을 받지 못함)`
    : admitted ? "입장 통과: 보완 작업을 제출할 수 있습니다."
      : `입장 거절: ${admissionCode ? repairReasonText(admissionCode) : NULL_TEXT}${admission.message
        ? ` · ${admission.message}` : ""}`;
  const repairableText = preflight.repairable === null ? `${NULL_TEXT} (결함 분석 없음)`
    : preflight.repairable ? "보완할 수 있음" : "보완할 수 없음";
  const defects = preflight.defects;
  const remaining = preflight.remaining.expensive_calls;
  const shortfall = preflight.shortfall.expensive_calls;
  return {
    admitted, admissionText, repairableText,
    blockers: preflight.blockers.map(blocker => ({ ...blockerText(blocker), code: blocker.reason_code })),
    chainParts: defects ? defects.chain_parts.map(item => ({ chain: item.chain_auth, parts: valueText(item.parts) })) : [],
    sideChain: defects ? defects.side_chain_residues.map(item => ({ residue: residueText(item.residue),
      fields: residueFieldsText(item.residue), missing: item.missing_atoms.join(", ") })) : [],
    oxt: defects ? defects.terminal_oxt.map(item => ({ residue: residueText(item.residue),
      fields: residueFieldsText(item.residue) })) : [],
    gaps: defects ? defects.gaps.map(gapRowText) : [],
    nonstandard: defects ? defects.nonstandard.map(item => ({ residue: residueText(item.residue),
      fields: residueFieldsText(item.residue), to: item.to_resname })) : [],
    expectedText: defects === null ? `${NULL_TEXT} (결함 분석 없음)`
      : `더할 잔기 ${valueText(preflight.expected_added_residues)}개 · 더할 중원자 ` +
        `${valueText(preflight.expected_added_heavy_atoms)}개 (사전 검사 값)`,
    budgetText: `비싼 계산 남은 예산 ${valueText(remaining)}단위`,
    shortfallText: shortfall > 0 ? `비싼 계산 예산이 ${shortfall}단위 부족합니다(서버 값).` : null,
    statements: [...preflight.statements],
  };
}

// ---- job (POST /jobs → /start → 409 approval → /jobs/approve → /start → GET /jobs/{id}) ----

export interface RepairJobBody { protocol_id: typeof REPAIR_PROTOCOL;
  args: { structure: string; repair_policy: typeof REPAIR_POLICY }; timeout_s: number }

/** The submission body: the structure and the literal policy, only after the explicit confirmation. */
export function repairJobBody(structure: string | null, confirmed: boolean):
  { ok: true; body: RepairJobBody } | { ok: false; errors: string[] } {
  const errors: string[] = [];
  if (structure === null) errors.push("전처리 구조를 고르세요.");
  if (!confirmed) errors.push(`보완 정책 확인(${REPAIR_POLICY})을 체크하세요.`);
  if (errors.length || structure === null) return { ok: false, errors };
  return { ok: true, body: { protocol_id: REPAIR_PROTOCOL, args: { structure, repair_policy: REPAIR_POLICY },
    timeout_s: REPAIR_TIMEOUT_DEFAULT_S } };
}

const ACTIVE_STATUSES = ["queued", "claimed", "running"];

export function repairJobActive(job: { status: string } | null): boolean {
  return !!job && ACTIVE_STATUSES.includes(job.status);
}

export function repairCancelEnabled(input: { job: { status: string; cancel_requested: boolean } | null;
  cancelling: boolean }): boolean {
  return repairJobActive(input.job) && !input.job!.cancel_requested && !input.cancelling;
}

/** Why the submit button is closed (null: open). The server checks everything again. */
export function repairSubmitBlockedReason(input: { capability: CapabilityLike | null | undefined; busy: boolean;
  activeJob: { status: string } | null; structure: string | null; preflight: StructureRepairPreflight | null;
  confirmed: boolean }): string | null {
  if (!input.capability?.available) return capabilityText(input.capability ?? null);
  if (input.busy) return "요청을 처리하는 중입니다.";
  if (repairJobActive(input.activeJob)) return "진행 중인 보완 작업이 끝난 뒤 제출할 수 있습니다(한 번에 한 작업).";
  if (input.structure === null) return "전처리 구조를 고르세요.";
  if (input.preflight === null || input.preflight.structure !== input.structure)
    return "고른 구조의 사전 검사 결과를 읽은 뒤 제출할 수 있습니다.";
  if (input.preflight.admission?.admitted !== true) {
    const code = input.preflight.admission?.reason_code ?? input.preflight.admission?.error ?? null;
    return `사전 검사가 입장을 거절했습니다: ${code ? repairReasonText(code) : NULL_TEXT}`;
  }
  if (!input.confirmed) return `보완 정책 확인(${REPAIR_POLICY})을 체크하세요.`;
  return null;
}

export function repairApprovalRequired(status: number, approval: { gate: string; tool: string } | undefined): boolean {
  return status === 409 && approval?.gate === "expensive_first_call" && approval.tool === REPAIR_TOOL;
}

/** This run's repair job that is still queued or running (the latest one), for re-attaching after a remount. */
export function repairActiveJob(jobs: unknown, runId: string): StructureRepairJob | null {
  if (!Array.isArray(jobs)) return null;
  return (jobs as StructureRepairJob[]).filter(job => job && job.run_id === runId && job.protocol_id === REPAIR_PROTOCOL &&
    ACTIVE_STATUSES.includes(job.status)).at(-1) ?? null;
}

/** The start may have taken effect although its answer was lost: the stored job decides. */
export function repairStartProgressed(before: { run_id: string; job_id: string; attempt_ordinal: number },
  stored: { run_id: string; job_id: string; protocol_id: string; status: string; attempt_ordinal: number }): boolean {
  return stored.run_id === before.run_id && stored.job_id === before.job_id && stored.protocol_id === REPAIR_PROTOCOL &&
    (!["queued", "claimed"].includes(stored.status) || stored.attempt_ordinal > before.attempt_ordinal);
}

/** The published record handle of a finished job (null until it is done). */
export function repairJobResult(job: { status: string; artifacts?: { structure_repair?: string } } | null): string | null {
  return job?.status === "done" && typeof job.artifacts?.structure_repair === "string" ? job.artifacts.structure_repair
    : null;
}

export function repairFailureText(failure: StructureRepairJob["failure"]): string {
  if (!failure) return "이유 없음";
  const code = failure.reason_code ?? (typeof failure.detail?.reason_code === "string" ? failure.detail.reason_code : null);
  const m7 = failure.detail?.m7_reason;
  return `${code ? repairReasonText(code) : failure.error} · ${failure.message}` +
    (typeof m7 === "string" ? ` · M7 사유 ${m7}` : "");
}

export function repairJobText(job: Pick<StructureRepairJob, "status" | "cancel_requested" | "failure"> | null,
  approvalPending: boolean): string {
  if (!job) return "구조 보완 작업 없음";
  if (approvalPending && ACTIVE_STATUSES.includes(job.status))
    return "비용이 드는 실제 계산 승인이 필요합니다(비싼 계산 예산 1단위). 승인한 뒤 시작을 다시 누르세요.";
  switch (job.status) {
    case "queued": return "구조 보완 작업이 저장되었습니다. 시작을 누르면 실제 계산이 실행됩니다(비싼 계산 예산 1단위).";
    case "claimed": case "running": return `구조 보완 실행 중${job.cancel_requested ? " · 취소 요청됨" : ""}`;
    case "done": return "구조 보완 완료";
    case "cancelled": return "구조 보완 취소됨 (결과를 저장하지 않았습니다)";
    case "failed": case "interrupted": return `구조 보완 실패 (결과를 저장하지 않았습니다): ${repairFailureText(job.failure)}`;
    default: return `구조 보완 상태를 알 수 없음 (${job.status})`;
  }
}

/** Submission is idempotent: identical inputs return the existing job; a dry-run run returns a plan only. */
export function repairSubmitText(result: StructureRepairSubmission): string {
  if ("plan_only" in result) return "dry-run run이라 계획만 만들었습니다. 실제 계산과 결과 객체는 없습니다.";
  if (result.status === "queued") return repairJobText({ status: "queued", cancel_requested: false, failure: null }, false);
  return `같은 입력의 기존 작업을 다시 표시합니다 · ${result.job_id} · ${result.status} (새 작업을 만들지 않았습니다)`;
}

// ---- results (the stored record, shown as stored) ----

export function repairListRowText(row: StructureRepairListRow): string {
  if (!row.valid || row.counts === null || row.classes_applied === null)
    return `이벤트 #${row.created_seq} · 검증되지 않는 기록 (값을 보이지 않음)`;
  return `이벤트 #${row.created_seq} · 원본 ${row.source_structure ? shortHandle(row.source_structure) : NULL_TEXT} → ` +
    `${REPAIRED_BADGE} ${row.prepared_structure ? shortHandle(row.prepared_structure) : NULL_TEXT} · ` +
    `${row.classes_applied.map(name => CLASS_LABEL[name] ?? name).join(", ")} · 추가 잔기 ${row.counts.added_residues}개 · ` +
    `추가 원자 ${row.counts.added_atoms}개 · 보완 뒤 단백질 중원자 ${row.counts.protein_heavy_atoms}개`;
}

/** The one-line summary of a record (stored counts only). */
export function repairSummaryText(record: Pick<StructureRepairRecord, "classes_applied" | "counts" | "unchanged">): string {
  const counts = record.counts;
  return `보완 종류 ${record.classes_applied.map(name => CLASS_LABEL[name] ?? name).join(", ") || NULL_TEXT} · ` +
    `추가 잔기 ${counts.added_residues}개 · 추가 원자 ${counts.added_atoms}개 · 보완 뒤 단백질 중원자 ` +
    `${counts.protein_heavy_atoms}개 · 입력 원자 ${record.unchanged.atom_count}개는 그대로`;
}

/** The five repair classes in their fixed order: applied or not, with the stored count of that class. */
export function repairClassRows(record: Pick<StructureRepairRecord, "classes_applied" | "counts">):
  { key: RepairClass; label: string; applied: boolean; appliedText: string; countText: string }[] {
  const counts = record.counts;
  const countText: Record<RepairClass, string> = {
    chain_parts_merged: `합친 체인 ${counts.chain_parts_merged}개`,
    side_chain_atoms_added: `잔기 ${counts.side_chain_residues}개`,
    terminal_oxt_added: `잔기 ${counts.terminal_oxt}개`,
    internal_gap_filled: `틈 ${counts.gaps}개 · 잔기 ${counts.added_residues}개`,
    nonstandard_replaced: `잔기 ${counts.replaced}개`,
  };
  return REPAIR_CLASSES.map(key => { const applied = record.classes_applied.includes(key);
    return { key, label: CLASS_LABEL[key], applied, appliedText: applied ? "적용" : "적용하지 않음",
      countText: countText[key] }; });
}

/** A chain-end flag: true "같음", false "다름", null "—(판정 불가)" (never "같음"). */
export function chainEndFlagText(value: boolean | null): string {
  return value === null ? UNDETERMINED_TEXT : value ? "같음" : "다름";
}

export function chainEndRows(record: Pick<StructureRepairRecord, "chain_ends">):
  { chain: string; first: string; last: string; start: string; end: string; differs: boolean }[] {
  return record.chain_ends.map(end => ({ chain: end.chain_auth, first: residueText(end.observed_first),
    last: residueText(end.observed_last), start: chainEndFlagText(end.first_is_sequence_start),
    end: chainEndFlagText(end.last_is_sequence_end),
    differs: end.first_is_sequence_start === false || end.last_is_sequence_end === false }));
}

export function collisionMinText(collision: StructureRepairCollision): string {
  return collision.min_distance_A === null ? `${NULL_TEXT} (이 분류의 상대 원자 없음)` : `${collision.min_distance_A} Å`;
}

export function collisionPairText(collision: StructureRepairCollision): string {
  const pair = collision.min_pair;
  return pair === null ? `${NULL_TEXT} (상대 원자 없음)`
    : `${residueText(pair.new_residue)} ${pair.new_atom} – ${residueText(pair.partner_residue)} ${pair.partner_atom}`;
}

/** The collision record per partner class (fixed order, no ordering by distance, no verdict). */
export function collisionRows(record: Pick<StructureRepairRecord, "collisions">):
  { key: RepairCollisionClass; label: string; min: string; lt20: string; lt15: string; pair: string;
    hasPartner: boolean }[] {
  return COLLISION_CLASSES.map(key => { const item = record.collisions[key];
    return { key, label: COLLISION_LABEL[key], min: collisionMinText(item), lt20: valueText(item.count_lt_2_0),
      lt15: valueText(item.count_lt_1_5), pair: collisionPairText(item), hasPartner: item.min_distance_A !== null }; });
}

export function replacedRows(record: Pick<StructureRepairRecord, "replaced">):
  { from: string; to: string; fromFields: string; toFields: string; atoms: string; recordType: string }[] {
  return record.replaced.map(item => ({ from: residueText(item.from), to: residueText(item.to),
    fromFields: residueFieldsText(item.from), toFields: residueFieldsText(item.to),
    atoms: item.atom_map.map(pair => `${pair.from}→${pair.to}`).join(", "),
    recordType: `${item.record_type.from}→${item.record_type.to}` }));
}

export function zeroOccupancyText(zero: StructureRepairRecord["zero_occupancy_input_atoms"]): string {
  return `${zero.count}개 (잔기 ${zero.residues.length}개${zero.residues.length
    ? `: ${zero.residues.map(residueText).join(", ")}` : ""}) · 좌표는 입력 그대로`;
}

export function unchangedText(record: Pick<StructureRepairRecord, "unchanged" | "new_atom_rounding">): string {
  return `입력 원자 ${record.unchanged.atom_count}개 · 입력과의 최대 좌표 거리 ${record.unchanged.max_delta_A} Å · ` +
    `정규화한 입력 calc_flag ${record.unchanged.input_calc_flag_cleared}개 · 새 원자 좌표 소수 ` +
    `${record.new_atom_rounding.decimals}자리 (PDBFixer 원값과의 최대 차 ${record.new_atom_rounding.max_abs_delta_A} Å)`;
}

export function coordinatesText(coordinates: readonly number[]): string {
  return coordinates.map(value => String(value)).join(", ");
}

export function atomQuery(page: number, pageSize: number = ATOM_PAGE_DEFAULT): string {
  const size = Math.min(ATOM_PAGE_RANGE[1], Math.max(ATOM_PAGE_RANGE[0], Math.trunc(pageSize)));
  return `page=${Math.max(1, Math.trunc(page))}&page_size=${size}`;
}

/** "n–m / 전체 t개" of an atom page (positions from the server's page numbers, not a count of values). */
export function atomPageText(page: { total: number; page: number; page_size: number; rows: readonly unknown[] }): string {
  if (!page.total || !page.rows.length) return `0 / 전체 ${page.total}개`;
  const first = (page.page - 1) * page.page_size + 1;
  return `${first}–${first + page.rows.length - 1} / 전체 ${page.total}개`;
}

export function atomPageCount(page: { total: number; page_size: number }): number {
  return Math.max(1, Math.ceil(page.total / page.page_size));
}

export function repairReportMatches(artifact: Pick<StructureRepairReportArtifact, "manifest">, record: string): boolean {
  return artifact.manifest.schema === "method_report_manifest@1" &&
    artifact.manifest.analysis_type === REPAIR_REPORT_TYPE && artifact.manifest.result_handle === record;
}

export function detailMatches(value: unknown, handle: string): boolean {
  const detail = value as { schema?: unknown; handle?: unknown } | null;
  return typeof detail === "object" && detail !== null && detail.schema === "structure_repair_detail@1" &&
    detail.handle === handle;
}

// ---- wording check (no rank, recommendation, verdict, score, energy, affinity, hydrogen bond, "no collision") ----

const FORBIDDEN = new RegExp(["순위", "추천", "최적(?!화)", "최고", "개선", "안정성", "ΔΔG", "점수", "에너지", "수소\\s*결합",
  "친화", "유망", "좋은", "나쁜", "안전", "예측", "(?<!비)활성", "승자", "충돌\\s*없음", "\\brank", "\\bbest", "optimal",
  "improv", "recommend", "affinity", "stabili", "predict", "hydrogen\\s*bond", "score", "energy"].join("|"), "gi");

/** Forbidden words in screen text, line by line; a line equal to a fixed sentence (RP / SO / JW1) is exempt. */
export function repairForbiddenWords(text: string): string[] {
  const found: string[] = [];
  for (const line of text.split("\n")) {
    if (REPAIR_FIXED_LINES.includes(line.trim())) continue;
    for (const match of line.matchAll(FORBIDDEN)) found.push(match[0]);
  }
  return found;
}
