/**
 * Pure logic of the M27 "키나아제 전례" area in the 지식·보고서 tab (M27 spec `.dryforge/spec.md` 2, 5, 6, 8, 9.1).
 *
 * Precedents are records that kbase_kinase extracted by machine from papers and nobody reviewed; every precedent field
 * is a kbase value shown as written (directions stay the English kbase words, never translated, summarized or
 * coloured). The only counts on screen are the ones the server stored, plus the few the spec defines from them (UP5's
 * N, "전례 N건", "그 밖 N개") and the fail / lookup_failed badge of one record's ten kbase checks. This module never
 * ranks, sorts, filters precedent values, computes fold changes, differences or averages: the server filters, searches,
 * sorts and pages (GET query built here, sort keys exactly the five of spec 6). It builds and checks the request
 * (mirroring the server admission so the screen can say why a request is blocked; the server checks everything
 * again), turns server answers into display models that keep "not included", "no bibliography", "not computed" and
 * "not checked" apart from 0 and from a bare "없음" (always "—" with the reason), names every closed code as
 * "한국어 (code)", keeps late responses out and checks the module's own wording. External strings (quotes, titles) are
 * returned as plain text for text-only rendering.
 */
import type { CommandResult } from "./api";
import type { KinasePrecedentsArgs, KinasePrecedentsCounts, KinasePrecedentsDetail, KinasePrecedentsListItem,
  KinasePrecedentsTargetOverview, PrecedentBibliographyEntry, PrecedentChain, PrecedentEffect, PrecedentFacets,
  PrecedentFileCounts, PrecedentJsonValue, PrecedentMeasure, PrecedentRecordItem, PrecedentReferenceStatus,
  PrecedentSetSummary, PrecedentSortKey, PrecedentSortOrder, PrecedentTagAxis, PrecedentTargetCounts,
  PrecedentTooLargeDetail } from "./contracts";
import type { NumberingMapListRow, NumberingRow } from "./numbering";
import { reasonText as numberingReasonText } from "./numbering";

// ---- closed sets, limits and fixed wording (backend/mw/precedent_constants.py; change both sides) ----

export const PRECEDENT_TOOL = "link_kinase_precedents";
export const PRECEDENT_KIND = "kinase_precedents";
export const PRECEDENT_SCHEMA = "kinase_precedents@1";
export const PRECEDENT_METHOD_VERSION = "mw.kinase_precedents/v1";
export const PRECEDENT_STATUS_SCHEMA = "precedent_reference_status@1";
export const PRECEDENT_DETAIL_SCHEMA = "kinase_precedents_detail@1";
export const PRECEDENT_RECORD_FORMAT = "kbase_record_minus_2_paths@1";
export const PRECEDENT_REPORT_TYPE = "kinase_precedents";
export const PRECEDENT_REPORT_LABEL = "키나아제 전례 보고서";
export const SNAPSHOT_REASON_CODES = ["not_installed", "snapshot_invalid"] as const;
/** `link_kinase_precedents` admission reasons (`detail.reason_code`, 422), in the server's check order. */
export const ADMISSION_REASON_CODES = ["unknown_field", "numbering_map_invalid", "include_flagged_invalid",
  "chains_invalid", "chain_not_in_map"] as const;
export const RESULT_TOO_LARGE_REASON = "result_too_large";
export const RESULT_INVALID_REASON = "result_invalid";
export const FILE_SOURCES = ["moves", "moves_flagged"] as const;
export const CHAIN_STATUSES = ["linked", "not_linked"] as const;
export const CHAIN_REASONS = ["no_mapped_residues", "multiple_accessions"] as const;
export const TARGET_STATUSES = ["precedents_found", "none_in_included_files", "not_in_kbase_references"] as const;
/** Detail read filter keys (spec 6) and the five sort keys: never an effect, direction or magnitude value. */
export const FILTER_KEYS = ["file", "site", "goal", "tactic", "variant", "q"] as const;
export const SORT_KEYS = ["move_id", "pmid", "year", "variant", "file"] as const;
export const SORT_ORDERS = ["asc", "desc"] as const;
export const TAG_AXES = ["site", "goal", "tactic"] as const;
export const CHECK_NAMES = ["qualifier_consistency", "tag_vocab", "schema", "target_in_reference", "quote_in_source",
  "cross_parser_numbers", "chembl_crosscheck", "pmid_exists", "structure_ref_exists", "duplicate"] as const;
export const LOCATION_KINDS = ["table", "figure", "text"] as const;
/** The two paths the stored record copy leaves out (spec 5.5). */
export const REMOVED_PATHS = ["source.parser", "checks.cross_parser_numbers.measurements"] as const;
/** Caps (spec 9.2): result size (refused with 429, never truncated), search text, read page sizes. */
export const MAX_RESULT_BYTES = 1024 * 1024;
export const MAX_QUERY_CHARS = 100;
export const PAGE_LIMIT_MIN = 1;
export const PAGE_LIMIT_MAX = 100;
export const RECORDS_PAGE_DEFAULT = 25;
export const LIST_PAGE_DEFAULT = 50;
export const MAX_UNRESOLVED_NAMES = 100;

/** Fixed sentences KP1–KP6 and KT1 (spec 9.1), verbatim and in order; the result stores KP1–KP6 as `limitations`. */
export const PRECEDENT_STATEMENTS = {
  KP1: "전례는 kbase_kinase가 논문에서 기계로 추출한 미검수 기록이며 ProtView가 계산하거나 판정한 것이 아니다.",
  KP2: "방향과 크기는 kbase 규칙 v1이 숫자 또는 본문에서 산출한 값이며 논문의 결론도 ProtView의 판정도 아니고, " +
    "측정 변화마다 대상 역할(on_target·off_target·not_applicable)이 함께 있다.",
  KP3: "kbase 기계 검사는 kbase가 만들 때 한 결과를 그대로 보인 것이며 ProtView는 논문 원문과 대조하지 않았다. " +
    "파일 이름(moves·moves_flagged)은 모든 검사의 통과 여부를 뜻하지 않는다.",
  KP4: "전례가 없다는 표시는 포함한 파일에 기록이 없다는 뜻이며 선행 연구가 없다는 뜻이 아니다. 포함하지 않은 " +
    "파일의 전례와 표적이 해석되지 않은 전례는 이 결과에 연결하지 않았다.",
  KP5: "표적(UniProt)이 같은 전례만 연결했다. 다른 키나아제의 전례는 연결하지 않았고, 변이·리간드·구조와의 " +
    "일치는 판단하지 않았다.",
  KP6: "전례 개수와 목록 순서는 순위·추천·유망도·성공률을 뜻하지 않는다.",
  KT1: "kbase_kinase 비공개 저장소 자료 · 이용 조건 명시 없음 · ChEMBL 유래 필드 포함 · 외부 공개 전 확인",
} as const;
export const PRECEDENT_LIMITATIONS: readonly string[] = [PRECEDENT_STATEMENTS.KP1, PRECEDENT_STATEMENTS.KP2,
  PRECEDENT_STATEMENTS.KP3, PRECEDENT_STATEMENTS.KP4, PRECEDENT_STATEMENTS.KP5, PRECEDENT_STATEMENTS.KP6];
/** Fixed screen notes UP1–UP5 (spec 9.1), verbatim; UP2 / UP5 carry "N건" filled by `screenNote`. */
export const PRECEDENT_SCREEN_NOTES = {
  UP1: "원문 대조 안 함: ProtView에는 논문 원문이 없어 인용이 원문과 같은지 확인하지 않았다. " +
    "'ProtView 무결성 확인'은 가져온 파일과 레코드의 해시, 인용 길이, 논문 쪽 위치 존재만 뜻한다.",
  UP2: "moves_flagged 파일의 전례 N건은 포함하지 않았다.",
  UP3: "변이 표기는 kbase 기록 그대로이며 이 구조의 서열과 대조하지 않았다.",
  UP4: "PDB 언급은 kbase가 기록한 것(근거 수준 포함)이며 이 구조와의 일치를 판단하지 않았다.",
  UP5: "표적이 해석되지 않은 전례 N건(세트 전체)이 있어 어느 체인에도 연결하지 못했다.",
} as const;
export type PrecedentScreenNoteKey = keyof typeof PRECEDENT_SCREEN_NOTES;
const NUMBERED_NOTES: readonly PrecedentScreenNoteKey[] = ["UP2", "UP5"];

/** The screen note verbatim; UP2 / UP5 with "N건" replaced by the non-negative integer `n` (server `screen_note`). */
export function screenNote(key: PrecedentScreenNoteKey, n?: number): string {
  const text = PRECEDENT_SCREEN_NOTES[key];
  if (NUMBERED_NOTES.includes(key)) {
    if (typeof n !== "number" || !Number.isInteger(n) || n < 0) throw new Error(`${key} needs a non-negative integer`);
    return text.replace("N건", `${n}건`);
  }
  if (n !== undefined) throw new Error(`${key} takes no number`);
  return text;
}

// ---- fixed screen text ----

export const PANEL_TITLE = "키나아제 전례";
export const NULL_TEXT = "—";
export const EMPTY_LIST_TEXT = "빈 목록 ([])";
export const PROCESSED_LABEL = "kbase_kinase 가공본 · 미검수 · 기계 추출";
export const REFERENCE_NOTE = "kbase 가공본 값, 계산 아님";
/** The measured-change table heading (spec 2): the kbase field name, never a claim. */
export const EFFECTS_HEADER = "측정 변화(kbase 추출 effects)";
export const KBASE_CHECKS_HEADER = "kbase 기계 검사";
export const INTEGRITY_HEADER = "ProtView 무결성 확인";
export const CONTENT_HASH_NOTE = "해시는 원본 레코드의 것(저장된 사본은 source.parser·" +
  "checks.cross_parser_numbers.measurements 두 경로를 뺀 kbase_record_minus_2_paths@1이며 ProtView는 이 해시를 " +
  "사본에서 다시 계산하지 않음)";
/** The user-run import command (local files and read-only git only; docs/operations.md names the same command). */
export const PRECEDENT_IMPORT_COMMAND = ".venv/bin/python scripts/import_precedent_snapshots.py --from <kbase_kinase 경로>";
export const IMPORT_HINT = "키나아제 전례 참조 스냅샷은 사용자가 터미널에서 가져오기 명령으로 설치합니다(로컬 파일과 " +
  "읽기 전용 git만 쓰며 네트워크를 쓰지 않습니다):";
export const NO_RUN_REASON = "run이 없습니다. 구조 분석 탭에서 run을 먼저 고르세요.";
export const CAPABILITY_REASON = "키나아제 전례 영역을 사용할 수 없습니다(서버가 이 방법을 알리지 않음).";
export const STATUS_LOADING_REASON = "키나아제 전례 참조 스냅샷 상태를 읽는 중입니다.";
export const NO_MAP_REASON = "이 run에 번호 대응 결과가 없습니다. 번호 대응 화면에서 먼저 만드세요.";
export const MAP_NOTE = "번호 대응 결과는 자동으로 정하지 않습니다. 마지막으로 만든 것을 미리 골라 두지만 연결은 " +
  "사람이 누를 때만 합니다.";
export const CHAIN_NOTE = "체인은 기본으로 모두 고릅니다. 연결 안 함으로 미리 보이는 체인도 고를 수 있고, 그때는 " +
  "서버가 결과로 이유를 돌려줍니다.";
export const FLAGGED_TOGGLE_LABEL = "moves_flagged 파일 전례 포함";
export const FLAGGED_TOGGLE_NOTE = "켜면 moves_flagged 파일의 전례도 담아 결과가 커질 수 있습니다. 결과가 정규 JSON " +
  "1 MiB를 넘으면 저장하지 않고 거절합니다(자르지 않음).";
export const LINK_BUTTON_TEXT = "전례 연결";
export const LINK_NOTE = "값싼 도구라 승인·예산 단위가 없습니다.";
export const STALE_TEXT = "이전 스냅샷 기준";
export const NO_ACTIVE_SET_TEXT = "사용 중 스냅샷 없음";
export const RESPONSE_SHAPE_TEXT = "응답 형식이나 대상이 요청과 다릅니다.";
export const NOT_A_RESULT_TEXT = "도구 결과가 키나아제 전례 결과(kinase_precedents@1)가 아닙니다.";
export const REQUEST_FAILED_TEXT = "요청 실패";
export const NO_TARGET_TEXT = "연결된 표적이 없어 전례 목록이 없습니다(연결한 체인이 없음).";
export const NULL_RESULT_TEXT = "빈 결과: 포함한 파일에 연결된 표적의 전례 기록이 없습니다. 선행 연구가 없다는 뜻이 " +
  "아닙니다.";
export const PREVIEW_PENDING_TEXT = "번호 대응 행을 다 읽은 뒤 미리 보입니다(연결 여부는 서버가 결과로 정함).";
/** The five area states (spec 8). */
export const AREA_STATE_LABEL = { loading: "불러오는 중", ready: "준비", empty: "빈 결과", failed: "실패",
  unavailable: "사용할 수 없음" } as const;

export const CHAIN_STATUS_LABEL: Record<(typeof CHAIN_STATUSES)[number], string> = { linked: "연결",
  not_linked: "연결 안 함" };
export const TARGET_STATUS_LABEL: Record<(typeof TARGET_STATUSES)[number], string> = {
  precedents_found: "전례 N건",
  none_in_included_files: "포함한 파일에 이 표적의 전례 기록 없음",
  not_in_kbase_references: "kbase에 이 표적 참조가 없음(전례 없음과 다름)" };
export const LOCATION_KIND_LABEL: Record<(typeof LOCATION_KINDS)[number], string> = { table: "표", figure: "그림",
  text: "본문" };
export const TAG_AXIS_LABEL: Record<PrecedentTagAxis, string> = { site: "site", goal: "goal", tactic: "tactic" };
export const SORT_LABEL: Record<PrecedentSortKey, string> = {
  move_id: "move_id(숫자 부분)", pmid: "PMID", year: "서지 연도(정수가 아니거나 서지 없음은 늘 끝)",
  variant: "변이 표기", file: "파일" };
export const ORDER_LABEL: Record<PrecedentSortOrder, string> = { asc: "오름차순 (asc)", desc: "내림차순 (desc)" };

/**
 * Korean names of every code this area can show: the five admission reasons, the two snapshot reasons, the result
 * refusals, the chain reasons, the failure classes and the read errors.
 */
export const PRECEDENT_REASON_LABEL: Record<string, string> = {
  unknown_field: "알 수 없는 요청 항목",
  numbering_map_invalid: "이 run의 번호 대응이 아니거나 도구가 읽는 항목이 없음",
  include_flagged_invalid: "moves_flagged 파일 전례 포함 여부가 true/false가 아님",
  chains_invalid: "체인 목록 오류(비었음·문자열 아님·중복)",
  chain_not_in_map: "번호 대응에 없는 체인",
  not_installed: "키나아제 전례 참조 스냅샷이 설치되지 않음",
  snapshot_invalid: "키나아제 전례 참조 스냅샷의 매니페스트·파일·레코드 해시나 형식이 맞지 않음",
  result_too_large: "결과 크기 상한 초과로 저장하지 않음",
  result_invalid: "만든 결과가 형식 검사에 맞지 않아 저장하지 않음",
  no_mapped_residues: "번호 대응에 mapped 잔기 행이 없음",
  multiple_accessions: "mapped 잔기의 accession이 둘 이상(융합 단백질 등)",
  input_invalid: "요청 오류",
  precondition: "선행 조건이 없음",
  resource_exceeded: "상한 초과",
  transient: "일시 오류",
  fatal: "서버 오류",
  not_found: "찾을 수 없음(이 run의 키나아제 전례 결과가 아님)",
  run_corrupt: "run 기록 오류",
  method_evidence_invalid: "저장된 결과가 검증되지 않음",
  report_evidence_invalid: "보고서 근거가 검증되지 않음",
  cancelled: "run이 취소됨",
};

const own = <T>(table: Record<string, T>, code: string): T | undefined =>
  Object.prototype.hasOwnProperty.call(table, code) ? table[code] : undefined;

/** "한국어 (code)" so the identifier stays visible; unknown codes are shown as is. */
export function precedentReasonText(code: string): string {
  const label = own(PRECEDENT_REASON_LABEL, code);
  return label ? `${label} (${code})` : code;
}

/** "—" with the reason: every value that was not included, not computed, not checked or is not available. */
export function notShownText(reason: string): string {
  return `${NULL_TEXT} (${reason})`;
}

/** A kbase value as plain text: strings as written ("" stays ""), null "—", other JSON values as JSON text. */
export function verbatimText(value: PrecedentJsonValue | undefined): string {
  if (value === null || value === undefined) return NULL_TEXT;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function fileText(file: string): string {
  return `${file} 파일`;
}

function listOrEmpty(values: readonly string[]): string {
  return values.length ? values.join(", ") : EMPTY_LIST_TEXT;
}

// ---- spec-defined counts from server counts (the only arithmetic of this module) ----

/** UP5's N (spec 9.1): the sum of the set-wide `unresolved_target_records` of both files. */
export function unresolvedRecordTotal(summary: Pick<PrecedentSetSummary, "unresolved_target_records">): number {
  return summary.unresolved_target_records.moves + summary.unresolved_target_records.moves_flagged;
}

/** "전례 N건": the included records of one target (`moves`, plus `moves_flagged` only when that file was included). */
export function includedRecordCount(counts: Pick<PrecedentTargetCounts, "moves" | "moves_flagged">): number {
  return counts.moves_flagged === null ? counts.moves : counts.moves + counts.moves_flagged;
}

/** "그 밖 N개" of the unresolved-name table: distinct names the server counted but did not list (null when none). */
export function unlistedNameCount(summary: Pick<PrecedentSetSummary, "unresolved_names" | "unresolved_names_total">):
  number | null {
  return summary.unresolved_names_total > summary.unresolved_names.length
    ? summary.unresolved_names_total - summary.unresolved_names.length : null;
}

// ---- request: numbering map (this run, newest preselected, never submitted), chains (default all), toggle ----

export interface PrecedentChainChoice { chain_auth: string; selected: boolean }
export interface PrecedentForm { numberingMap: string | null; chains: PrecedentChainChoice[]; includeFlagged: boolean }

export function emptyPrecedentForm(): PrecedentForm {
  return { numberingMap: null, chains: [], includeFlagged: false };
}

/** The newest numbering map of this run (highest `created_seq`), or null; a preselection only (never submitted). */
export function newestMap(rows: readonly NumberingMapListRow[]): NumberingMapListRow | null {
  return rows.length ? rows.reduce((best, row) => row.created_seq > best.created_seq ? row : best) : null;
}

/** A form for one map: its chains in the map's order, all selected; `moves_flagged` off unless kept by the person. */
export function formForMap(map: NumberingMapListRow | null, includeFlagged = false): PrecedentForm {
  return { numberingMap: map === null ? null : map.handle, includeFlagged,
    chains: map === null ? [] : map.chains.map(chain_auth => ({ chain_auth, selected: true })) };
}

export function setPrecedentChainSelected(form: PrecedentForm, chain: string, selected: boolean): PrecedentForm {
  return { ...form, chains: form.chains.map(choice => choice.chain_auth === chain ? { ...choice, selected } : choice) };
}

export function setIncludeFlagged(form: PrecedentForm, includeFlagged: boolean): PrecedentForm {
  return { ...form, includeFlagged };
}

export type PrecedentPreviewStatus = (typeof CHAIN_STATUSES)[number] | null;
export interface ChainPreview { chainAuth: string; status: PrecedentPreviewStatus;
  reason: (typeof CHAIN_REASONS)[number] | null; accessions: string[] | null; mappedText: string; text: string }

/**
 * What the server will decide for each chain of a map (spec 5.3), shown before the request: no `mapped` row ->
 * "연결 안 함 (no_mapped_residues)"; with the map's rows read completely (`rows.length === row_count`), the distinct
 * accessions of the chain's `mapped` rows (first-seen order): one -> linked, two or more (fused) -> "연결 안 함
 * (multiple_accessions)". Without the complete rows a chain with mapped rows is not prejudged. The server decides.
 */
export function chainPreviews(map: NumberingMapListRow,
                              rows: readonly Pick<NumberingRow, "residue" | "status" | "uniprot_accession">[] | null):
  ChainPreview[] {
  const complete = rows !== null && rows.length === map.row_count ? rows : null;
  return map.chain_details.map(detail => {
    const chainAuth = detail.chain_auth;
    const mappedText = `mapped 잔기 행 ${detail.counts.mapped}개`;
    if (detail.counts.mapped === 0)
      return { chainAuth, status: "not_linked", reason: "no_mapped_residues", accessions: [], mappedText,
        text: `${CHAIN_STATUS_LABEL.not_linked} (${precedentReasonText("no_mapped_residues")})` };
    if (complete === null) return { chainAuth, status: null, reason: null, accessions: null, mappedText,
      text: PREVIEW_PENDING_TEXT };
    const accessions: string[] = [];
    for (const row of complete)
      if (row.residue.chain_auth === chainAuth && row.status === "mapped" && row.uniprot_accession !== null &&
          !accessions.includes(row.uniprot_accession)) accessions.push(row.uniprot_accession);
    if (accessions.length === 1)
      return { chainAuth, status: "linked", reason: null, accessions, mappedText,
        text: `${CHAIN_STATUS_LABEL.linked} 예정: accession ${accessions[0]} (서버가 결과로 정함)` };
    if (!accessions.length)
      return { chainAuth, status: "not_linked", reason: "no_mapped_residues", accessions, mappedText,
        text: `${CHAIN_STATUS_LABEL.not_linked} (${precedentReasonText("no_mapped_residues")})` };
    return { chainAuth, status: "not_linked", reason: "multiple_accessions", accessions, mappedText,
      text: `${CHAIN_STATUS_LABEL.not_linked} (${precedentReasonText("multiple_accessions")}: ${accessions.join(", ")})` };
  });
}

export type PrecedentFormField = "snapshot" | "numbering_map" | "include_flagged" | "chains";
export interface PrecedentFieldError { field: PrecedentFormField; chain: string | null; text: string }
export interface PrecedentFormOptions {
  /** `precedent_reference_status@1` (null = not read yet). */
  snapshot: Pick<PrecedentReferenceStatus, "installed" | "reason"> | null;
  maps: readonly NumberingMapListRow[];
}
export type PrecedentFormCheck = { ok: true; args: KinasePrecedentsArgs } | { ok: false; errors: PrecedentFieldError[] };

/** Why the request block shows a reason only (no controls), or null. */
export function requestUnavailableReason(input: { snapshot: Pick<PrecedentReferenceStatus, "installed" | "reason"> | null;
  maps: readonly unknown[] | undefined }): string | null {
  if (input.snapshot === null) return STATUS_LOADING_REASON;
  if (!input.snapshot.installed)
    return `사용할 수 없음: ${precedentReasonText(input.snapshot.reason ?? "not_installed")}. ${IMPORT_HINT} ` +
      PRECEDENT_IMPORT_COMMAND;
  if (input.maps !== undefined && !input.maps.length) return NO_MAP_REASON;
  return null;
}

/**
 * The tool arguments of "전례 연결", or every reason (with its field) the request is blocked, in the server's
 * admission order where the screen can know it. Every chain of the map selected -> `chains: null` (the server's
 * normalized call is the same either way); otherwise the selected chains in the map's order.
 */
export function checkPrecedentForm(form: PrecedentForm, options: PrecedentFormOptions): PrecedentFormCheck {
  const errors: PrecedentFieldError[] = [];
  const add = (field: PrecedentFormField, text: string, chain: string | null = null) =>
    errors.push({ field, chain, text });
  if (options.snapshot === null) add("snapshot", STATUS_LOADING_REASON);
  else if (!options.snapshot.installed)
    add("snapshot", `${precedentReasonText(options.snapshot.reason ?? "not_installed")}: 가져오기 명령으로 스냅샷을 ` +
      "먼저 설치하세요.");
  const map = form.numberingMap === null ? null : options.maps.find(row => row.handle === form.numberingMap) ?? null;
  if (form.numberingMap === null) add("numbering_map", "번호 대응 결과를 고르세요.");
  else if (map === null) add("numbering_map", "고른 번호 대응이 이 run의 것이 아닙니다.");
  else if (!map.chains.length) add("numbering_map", "고른 번호 대응에 체인이 없습니다.");
  if (typeof form.includeFlagged !== "boolean")
    add("include_flagged", "moves_flagged 파일 전례 포함 여부는 켬 또는 끔이어야 합니다.");
  const selected = form.chains.filter(choice => choice.selected).map(choice => choice.chain_auth);
  if (!selected.length) add("chains", "체인을 하나 이상 고르세요.");
  for (const chain of new Set(selected.filter((name, i) => selected.indexOf(name) !== i)))
    add("chains", "같은 체인이 두 번 있습니다.", chain);
  if (map !== null)
    for (const chain of selected)
      if (!map.chains.includes(chain)) add("chains", "고른 번호 대응에 없는 체인입니다.", chain);
  if (errors.length || map === null) return { ok: false, errors };
  const every = map.chains.every(chain => selected.includes(chain));
  return { ok: true, args: { numbering_map: map.handle,
    chains: every ? null : map.chains.filter(chain => selected.includes(chain)), include_flagged: form.includeFlagged } };
}

// ---- server refusals ("한국어 (code)" beside the field; 429 with the size advice) ----

const REFUSAL_FIELD: Record<string, PrecedentFormField | "request" | "result"> = {
  not_installed: "snapshot", snapshot_invalid: "snapshot", unknown_field: "request",
  numbering_map_invalid: "numbering_map", include_flagged_invalid: "include_flagged", chains_invalid: "chains",
  chain_not_in_map: "chains", result_invalid: "result", result_too_large: "result",
};

export interface PrecedentSizeAdvice {
  limitText: string; actualText: string;
  /** null when `moves_flagged` was already off. */
  withoutFlagged: { bytesText: string; fits: boolean; text: string } | null;
  targets: { accession: string; chainsText: string; bytesText: string; fits: boolean; text: string }[];
}
export interface PrecedentRefusal { field: PrecedentFormField | "request" | "result"; chain: string | null;
  code: string | null; text: string; sizeAdvice: PrecedentSizeAdvice | null }

function tooLargeDetail(detail: Record<string, unknown> | undefined): PrecedentTooLargeDetail | null {
  if (!detail || detail.reason_code !== RESULT_TOO_LARGE_REASON || typeof detail.limit !== "number" ||
      typeof detail.actual !== "number" || !(detail.size_without_flagged === null ||
      typeof detail.size_without_flagged === "number") || !Array.isArray(detail.target_sizes)) return null;
  const sizes = detail.target_sizes as unknown[];
  if (!sizes.every(item => typeof item === "object" && item !== null &&
      typeof (item as { accession?: unknown }).accession === "string" &&
      Array.isArray((item as { chains?: unknown }).chains) && typeof (item as { bytes?: unknown }).bytes === "number"))
    return null;
  return detail as unknown as PrecedentTooLargeDetail;
}

/** Which targets fit alone and whether turning `moves_flagged` off fits (server sizes, compared with the cap only). */
export function sizeAdvice(detail: PrecedentTooLargeDetail): PrecedentSizeAdvice {
  const fitsText = (bytes: number) => bytes <= detail.limit ? "상한 안" : "상한 초과";
  return {
    limitText: `${detail.limit} B`, actualText: `${detail.actual} B`,
    withoutFlagged: detail.size_without_flagged === null ? null : { bytesText: `${detail.size_without_flagged} B`,
      fits: detail.size_without_flagged <= detail.limit,
      text: `${FLAGGED_TOGGLE_LABEL}을 끄면 ${detail.size_without_flagged} B(${fitsText(detail.size_without_flagged)})` },
    targets: detail.target_sizes.map(item => ({ accession: item.accession, chainsText: `체인 ${item.chains.join(", ")}`,
      bytesText: `${item.bytes} B`, fits: item.bytes <= detail.limit,
      text: `${item.accession}(체인 ${item.chains.join(", ")})만 요청하면 ${item.bytes} B(${fitsText(item.bytes)})` })),
  };
}

/** A refused `link_kinase_precedents` call (an `ApiError`: `code`, `message`, `detail.reason_code` …) as shown. */
export function precedentRefusal(error: unknown): PrecedentRefusal {
  if (typeof error !== "object" || error === null)
    return { field: "request", chain: null, code: null, text: String(error), sizeAdvice: null };
  const { message, code, detail } = error as { message?: unknown; code?: unknown; detail?: Record<string, unknown> };
  const reason = typeof detail?.reason_code === "string" ? detail.reason_code : null;
  const chain = typeof detail?.chain_auth === "string" ? detail.chain_auth : null;
  const field = (reason && own(REFUSAL_FIELD, reason)) || "request";
  const large = tooLargeDetail(detail);
  if (large !== null) {
    const advice = sizeAdvice(large);
    const parts = [`${precedentReasonText(RESULT_TOO_LARGE_REASON)}: 결과 정규 JSON ${advice.actualText}가 상한 ` +
      `${advice.limitText}를 넘어 저장하지 않았습니다(자르지 않음).`];
    if (advice.withoutFlagged !== null) parts.push(`${advice.withoutFlagged.text}.`);
    if (advice.targets.length) parts.push(`표적별 단독 요청: ${advice.targets.map(item => item.text).join("; ")}.`);
    parts.push(`체인을 나눠 요청하거나 ${FLAGGED_TOGGLE_LABEL}을 끄세요.`);
    return { field: "result", chain: null, code: RESULT_TOO_LARGE_REASON, text: parts.join(" "), sizeAdvice: advice };
  }
  const head = reason ? precedentReasonText(reason) : typeof code === "string" ? precedentReasonText(code)
    : REQUEST_FAILED_TEXT;
  const text = typeof message === "string" && message ? `${head}: ${message}` : head;
  return { field, chain, code: reason ?? (typeof code === "string" ? code : null), text, sizeAdvice: null };
}

export type PrecedentCommandOutcome = { ok: true; handle: string } | { ok: false; refusal: PrecedentRefusal };

/** The command envelope of `link_kinase_precedents`: a stored `kinase_precedents@1` handle, or the refusal. */
export function precedentCommandOutcome(result: CommandResult): PrecedentCommandOutcome {
  if (!result.ok) {
    if ("message" in result)
      return { ok: false, refusal: precedentRefusal({ code: result.error, message: result.message,
        detail: result.detail }) };
    return { ok: false, refusal: { field: "request", chain: null, code: null, text: REQUEST_FAILED_TEXT,
      sizeAdvice: null } };
  }
  if (result.handle.kind !== PRECEDENT_KIND || result.handle.schema !== PRECEDENT_SCHEMA)
    return { ok: false, refusal: { field: "result", chain: null, code: null, text: NOT_A_RESULT_TEXT,
      sizeAdvice: null } };
  return { ok: true, handle: result.handle.handle };
}

// ---- detail read: target, filters (options from the result's facets), the five sort keys, page ----

export interface PrecedentFilters { file: string | null; site: string[]; goal: string[]; tactic: string[];
  variant: string | null; q: string }
export interface PrecedentQuery { target: string | null; filters: PrecedentFilters; sort: PrecedentSortKey;
  order: PrecedentSortOrder; limit: number; offset: number }

export function emptyFilters(): PrecedentFilters {
  return { file: null, site: [], goal: [], tactic: [], variant: null, q: "" };
}

export function defaultPrecedentQuery(target: string | null = null): PrecedentQuery {
  return { target, filters: emptyFilters(), sort: "move_id", order: "asc", limit: RECORDS_PAGE_DEFAULT, offset: 0 };
}

export function isSortKey(value: string): value is PrecedentSortKey {
  return (SORT_KEYS as readonly string[]).includes(value);
}

/** The five sort choices (spec 6), in the server's order; nothing else can be chosen. */
export const SORT_OPTIONS: readonly { value: PrecedentSortKey; label: string }[] =
  SORT_KEYS.map(value => ({ value, label: SORT_LABEL[value] }));

/** Another target: its own facets, so every filter is cleared and the page starts over. */
export function withTarget(query: PrecedentQuery, target: string | null): PrecedentQuery {
  return { ...query, target, filters: emptyFilters(), offset: 0 };
}

export function withFilters(query: PrecedentQuery, filters: PrecedentFilters): PrecedentQuery {
  return { ...query, filters, offset: 0 };
}

export function withSort(query: PrecedentQuery, sort: PrecedentSortKey, order: PrecedentSortOrder): PrecedentQuery {
  return { ...query, sort, order, offset: 0 };
}

export function withOffset(query: PrecedentQuery, offset: number): PrecedentQuery {
  return { ...query, offset };
}

/** One tag term on or off (OR inside a key on the server); the term list keeps the clicking order. */
export function toggleTagTerm(filters: PrecedentFilters, axis: PrecedentTagAxis, term: string): PrecedentFilters {
  const terms = filters[axis];
  return { ...filters, [axis]: terms.includes(term) ? terms.filter(item => item !== term) : [...terms, term] };
}

export type PrecedentQueryCheck = { ok: true; query: string } | { ok: false; errors: string[] };

/**
 * The detail GET query in a fixed key order (target, file, site*, goal*, tactic*, variant, q, sort, order, limit,
 * offset), or why it cannot be sent. The sort key must be one of the five of spec 6 and the order asc|desc; the
 * search text is at most 100 characters (code points, as the server counts) and is sent trimmed (blank -> no search).
 */
export function checkPrecedentQuery(query: PrecedentQuery): PrecedentQueryCheck {
  const errors: string[] = [];
  if (!isSortKey(query.sort)) errors.push(`정렬은 ${SORT_KEYS.join("·")} 다섯 가지 중 하나만 고를 수 있습니다.`);
  if (!(SORT_ORDERS as readonly string[]).includes(query.order)) errors.push("정렬 방향은 asc 또는 desc입니다.");
  if (!Number.isInteger(query.limit) || query.limit < PAGE_LIMIT_MIN || query.limit > PAGE_LIMIT_MAX)
    errors.push(`쪽 크기는 ${PAGE_LIMIT_MIN}–${PAGE_LIMIT_MAX}입니다.`);
  if (!Number.isInteger(query.offset) || query.offset < 0) errors.push("쪽 시작 위치는 0 이상의 정수입니다.");
  if (query.filters.file !== null && !(FILE_SOURCES as readonly string[]).includes(query.filters.file))
    errors.push("파일 필터는 moves 또는 moves_flagged입니다.");
  if ([...query.filters.q].length > MAX_QUERY_CHARS) errors.push(`검색어는 ${MAX_QUERY_CHARS}자 이하입니다.`);
  if (errors.length) return { ok: false, errors };
  const params = new URLSearchParams();
  if (query.target !== null) params.append("target", query.target);
  if (query.filters.file !== null) params.append("file", query.filters.file);
  for (const axis of TAG_AXES) for (const term of query.filters[axis]) params.append(axis, term);
  if (query.filters.variant !== null) params.append("variant", query.filters.variant);
  const q = query.filters.q.trim();
  if (q) params.append("q", q);
  params.append("sort", query.sort);
  params.append("order", query.order);
  params.append("limit", String(query.limit));
  params.append("offset", String(query.offset));
  return { ok: true, query: params.toString() };
}

export interface FilterOption { value: string; text: string }
export type FilterOptions = Record<keyof PrecedentFacets, FilterOption[]>;

/** Filter choices of the selected target: the values the result's `facets` list (server order and counts), or null. */
export function filterOptions(facets: PrecedentFacets | null): FilterOptions | null {
  if (facets === null) return null;
  const options = (items: PrecedentFacets["file"], label: (value: string) => string) =>
    items.map(item => ({ value: item.value, text: `${label(item.value)} (${item.count}건)` }));
  return { file: options(facets.file, fileText), site: options(facets.site, value => value),
    goal: options(facets.goal, value => value), tactic: options(facets.tactic, value => value),
    variant: options(facets.variant, value => value) };
}

/** "전체 N건 · 필터 결과 M건 · a–b번째" of one server page (totals from the server); no target -> "—" with the reason. */
export function recordPageText(page: KinasePrecedentsDetail["page"], shown: number): string {
  if (page.target === null || page.total === null || page.filtered_total === null)
    return notShownText("연결된 표적 없음");
  const head = `전체 ${page.total}건 · 필터 결과 ${page.filtered_total}건`;
  return shown ? `${head} · ${page.offset + 1}–${page.offset + shown}번째` : `${head} · 이 쪽에 없음`;
}

export function nextOffset(page: KinasePrecedentsDetail["page"]): number | null {
  return page.filtered_total !== null && page.offset + page.limit < page.filtered_total
    ? page.offset + page.limit : null;
}

export function previousOffset(page: KinasePrecedentsDetail["page"]): number | null {
  return page.offset > 0 ? Math.max(0, page.offset - page.limit) : null;
}

/** A `kinase_precedents_detail@1` answer (paged, with `active_set`); which result it is comes from the stamp. */
export function precedentDetailMatches(value: unknown): value is KinasePrecedentsDetail {
  if (typeof value !== "object" || value === null) return false;
  const detail = value as Partial<KinasePrecedentsDetail>;
  return detail.schema === PRECEDENT_DETAIL_SCHEMA && Array.isArray(detail.chains) &&
    Array.isArray(detail.targets_overview) && Array.isArray(detail.records) && typeof detail.page === "object" &&
    detail.page !== null && typeof detail.active_set === "object" && detail.active_set !== null;
}

// ---- snapshot block (no numbers or controls when not installed / invalid) ----

export interface SetSummaryView {
  unresolvedNote: string;
  unresolvedNames: { nameText: string; text: string }[];
  unresolvedNamesText: string; otherNamesText: string | null;
  bases: { basis: string; text: string }[];
}

export type PrecedentSnapshotView =
  | { state: "unavailable"; reasonCode: string | null; reasonText: string; hint: string; command: string }
  | { state: "ready"; setHash: string; setHashShort: string; importedAt: string; processedLabel: string;
      licenseNote: string; kbaseCommitShort: string; distCommitText: string; distCommitDateText: string;
      dirtyText: string; kbVersion: string; versions: { key: string; value: string }[];
      files: { name: string; rowsText: string }[];
      bibliography: { snapshotId: string; date: string; license: string; rowsText: string };
      summary: SetSummaryView };

export function precedentStatusMatches(value: unknown): value is PrecedentReferenceStatus {
  return typeof value === "object" && value !== null &&
    (value as { schema?: unknown }).schema === PRECEDENT_STATUS_SCHEMA &&
    typeof (value as { installed?: unknown }).installed === "boolean";
}

function pairText(counts: PrecedentFileCounts): string {
  return `moves ${counts.moves}건 · moves_flagged ${counts.moves_flagged}건`;
}

/** The set-wide summary (both files of the whole set, never one result's chains): UP5, unresolved names, bases. */
export function setSummaryView(summary: PrecedentSetSummary): SetSummaryView {
  const other = unlistedNameCount(summary);
  return {
    unresolvedNote: screenNote("UP5", unresolvedRecordTotal(summary)),
    unresolvedNames: summary.unresolved_names.map(item => ({
      nameText: item.name_as_written === null ? notShownText("kbase 기록에 이름 없음") : item.name_as_written,
      text: pairText(item) })),
    unresolvedNamesText: `표적이 해석되지 않은 전례의 서로 다른 이름 ${summary.unresolved_names_total}개(세트 전체)`,
    otherNamesText: other === null ? null : `그 밖 ${other}개(목록 상한 ${MAX_UNRESOLVED_NAMES}개)`,
    bases: summary.resolution_basis_counts.map(item => ({ basis: item.basis, text: pairText(item) })),
  };
}

export function precedentSnapshotView(status: PrecedentReferenceStatus): PrecedentSnapshotView {
  const unavailable = (code: string | null): PrecedentSnapshotView => ({ state: "unavailable", reasonCode: code,
    reasonText: code ? precedentReasonText(code) : RESPONSE_SHAPE_TEXT, hint: IMPORT_HINT,
    command: PRECEDENT_IMPORT_COMMAND });
  if (!status.installed) return unavailable(status.reason ?? "not_installed");
  if (status.set_hash === null || status.imported_at === null || status.kbase === null || status.files === null ||
      status.bibliography === null || status.set_summary === null) return unavailable(null);
  const kbase = status.kbase;
  return {
    state: "ready", setHash: status.set_hash, setHashShort: status.set_hash.slice(0, 12),
    importedAt: status.imported_at, processedLabel: PROCESSED_LABEL, licenseNote: PRECEDENT_STATEMENTS.KT1,
    kbaseCommitShort: kbase.commit.slice(0, 12),
    distCommitText: kbase.dist_commit === null ? notShownText("dist를 추적하는 커밋 없음") : kbase.dist_commit.slice(0, 12),
    distCommitDateText: kbase.dist_commit_date ?? "날짜 없음",
    dirtyText: kbase.dirty ? "커밋되지 않은 변경 있음 (dirty true)" : "커밋되지 않은 변경 없음 (dirty false)",
    kbVersion: kbase.kb_version,
    versions: [{ key: "schema_version", value: kbase.schema_version },
      { key: "effect_rules_version", value: kbase.effect_rules_version },
      { key: "vocab_version", value: kbase.vocab_version }],
    files: status.files.map(item => ({ name: item.name, rowsText: `${item.rows}행` })),
    bibliography: { snapshotId: status.bibliography.snapshot_id, date: status.bibliography.date,
      license: status.bibliography.license, rowsText: `${status.bibliography.rows}행` },
    summary: setSummaryView(status.set_summary),
  };
}

// ---- "이전 스냅샷 기준" / "사용 중 스냅샷 없음" (never recomputed) ----

export type PrecedentSnapshotBadge = "stale" | "no_active_set" | null;

/** Detail: no usable active set -> "사용 중 스냅샷 없음"; another active set -> "이전 스냅샷 기준". */
export function resultSnapshotBadge(activeSet: { set_hash: string | null; same: boolean }): PrecedentSnapshotBadge {
  if (activeSet.set_hash === null) return "no_active_set";
  return activeSet.same ? null : "stale";
}

/** List item (`active` is false both without an active set and with another one): needs the status read. */
export function listSnapshotBadge(item: Pick<KinasePrecedentsListItem, "active">,
                                  installed: boolean | null): PrecedentSnapshotBadge {
  if (installed === null) return null;
  if (!installed) return "no_active_set";
  return item.active ? null : "stale";
}

/** A reopened report: the active set it recorded at creation against the result's set. */
export function reportSnapshotBadge(manifest: { precedent_set: { set_hash: string };
  snapshot: { active_set_hash: string | null } }): PrecedentSnapshotBadge {
  if (manifest.snapshot.active_set_hash === null) return "no_active_set";
  return manifest.snapshot.active_set_hash === manifest.precedent_set.set_hash ? null : "stale";
}

export function snapshotBadgeText(badge: PrecedentSnapshotBadge): string | null {
  return badge === "stale" ? STALE_TEXT : badge === "no_active_set" ? NO_ACTIVE_SET_TEXT : null;
}

// ---- result list (newest first, as the server gave) ----

function recordsText(records: { moves: number; moves_flagged: number | null }): string {
  return `${fileText("moves")} ${records.moves}건 · ${fileText("moves_flagged")} ` +
    (records.moves_flagged === null ? notShownText("포함하지 않음") : `${records.moves_flagged}건`);
}

/** One stored result in the list; a file that was not included is "—" with the reason (never 0). */
export function precedentListItemText(item: KinasePrecedentsListItem): string {
  const pdb = item.pdb_id === null ? `PDB ID ${notShownText("번호 대응에 PDB ID가 없음")}` : `PDB ${item.pdb_id}`;
  return [pdb, `체인 ${item.chain_count}개(연결 ${item.linked_chain_count}개)`, `표적 ${item.target_count}개`,
    recordsText(item.records), item.null_result ? AREA_STATE_LABEL.empty : null]
    .filter((part): part is string => part !== null).join(" · ");
}

// ---- result display model (server order, verbatim kbase values, "—" with reasons) ----

export interface ChainView {
  chainAuth: string; status: string; statusText: string; reasonText: string; accessionText: string;
  accessionsText: string; residuesText: string; crossCheckText: string;
}

function crossCheckText(chain: Pick<PrecedentChain, "cross_check" | "cross_check_absent_reason">): string {
  if (chain.cross_check) return "두 방법 교차 확인함 (cross_check true)";
  return "교차 확인 안 함 (cross_check false)" + (chain.cross_check_absent_reason === null ? ""
    : `: ${numberingReasonText(chain.cross_check_absent_reason)}`);
}

export function chainView(chain: PrecedentChain): ChainView {
  const label = own(CHAIN_STATUS_LABEL, chain.status) ?? chain.status;
  return {
    chainAuth: chain.chain_auth, status: chain.status, statusText: `${label} (${chain.status})`,
    reasonText: chain.reason === null ? NULL_TEXT : precedentReasonText(chain.reason),
    accessionText: chain.accession ?? notShownText(chain.reason === null ? "연결하지 않음"
      : precedentReasonText(chain.reason)),
    accessionsText: listOrEmpty(chain.accessions),
    residuesText: `mapped ${chain.mapped_residue_count} / 전체 ${chain.total_residue_count}`,
    crossCheckText: crossCheckText(chain),
  };
}

export interface CountItemView { value: string; text: string }
export interface TargetView {
  accession: string; chainsText: string; status: string; statusText: string;
  /** UP2 right under the status phrase whenever `excluded_flagged` is an integer (also for 0). */
  excludedNote: string | null;
  references: { refId: string; gene: string; klifsName: string; group: string; family: string; coverage: string;
    contentHash: string }[];
  referencesText: string | null;
  movesText: string; movesFlaggedText: string;
  variants: CountItemView[]; variantsText: string | null; variantNote: string;
  tags: { axis: PrecedentTagAxis; label: string; items: CountItemView[]; text: string | null }[];
  bases: CountItemView[]; basesText: string | null;
}

/** The status phrase of one target (spec 8); never 0 or a bare "없음". */
export function targetStatusText(target: Pick<KinasePrecedentsTargetOverview, "status" | "counts">): string {
  if (target.status === "precedents_found") return `전례 ${includedRecordCount(target.counts)}건`;
  return own(TARGET_STATUS_LABEL, target.status) ?? target.status;
}

function countItems<T>(items: readonly T[], value: (item: T) => string, count: (item: T) => number): CountItemView[] {
  return items.map(item => ({ value: value(item), text: `${value(item)} ${count(item)}건` }));
}

export function targetView(target: KinasePrecedentsTargetOverview): TargetView {
  const counts = target.counts;
  const variants = countItems(counts.variants, item => item.variant, item => item.count);
  const bases = countItems(counts.resolution_basis, item => item.basis, item => item.count);
  return {
    accession: target.accession, chainsText: `체인 ${target.chains.join(", ")}`, status: target.status,
    statusText: targetStatusText(target),
    excludedNote: target.excluded_flagged === null ? null : screenNote("UP2", target.excluded_flagged),
    references: target.references.map(ref => ({ refId: ref.ref_id, gene: verbatimText(ref.gene),
      klifsName: verbatimText(ref.klifs_name), group: verbatimText(ref.group), family: verbatimText(ref.family),
      coverage: verbatimText(ref.coverage), contentHash: verbatimText(ref.content_hash) })),
    referencesText: target.references.length ? null : notShownText("kbase에 이 표적 참조가 없음"),
    movesText: `${fileText("moves")} ${counts.moves}건`,
    movesFlaggedText: `${fileText("moves_flagged")} ` +
      (counts.moves_flagged === null ? notShownText("포함하지 않음") : `${counts.moves_flagged}건`),
    variants, variantsText: variants.length ? null : EMPTY_LIST_TEXT, variantNote: PRECEDENT_SCREEN_NOTES.UP3,
    tags: TAG_AXES.map(axis => {
      const items = countItems(counts.tags[axis], item => item.term, item => item.count);
      return { axis, label: TAG_AXIS_LABEL[axis], items, text: items.length ? null : EMPTY_LIST_TEXT };
    }),
    bases, basesText: bases.length ? null : EMPTY_LIST_TEXT,
  };
}

function bibliographyOf(bibliography: KinasePrecedentsDetail["bibliography"], pmid: string):
  PrecedentBibliographyEntry | null {
  return own(bibliography, pmid) ?? null;
}

function locationSummary(location: { kind: string; page: number }): string {
  const label = own(LOCATION_KIND_LABEL, location.kind);
  return `${label ? `${label}(${location.kind})` : location.kind} ${location.page}쪽`;
}

export interface RecordRowView {
  moveId: string; file: string; fileText: string; variant: string;
  tags: { axis: PrecedentTagAxis; text: string }[];
  resolutionBasis: string; pmid: string; bibliographyText: string; locationsText: string;
  checks: { failNames: string[]; lookupFailedNames: string[]; text: string };
}

/** One precedent table row: kbase values verbatim, the stored order of the page (never re-sorted here). */
export function recordRowView(item: PrecedentRecordItem, bibliography: KinasePrecedentsDetail["bibliography"]):
  RecordRowView {
  const record = item.record;
  const book = bibliographyOf(bibliography, record.source.pmid);
  const failNames = CHECK_NAMES.filter(name => record.checks[name]?.status === "fail");
  const lookupFailedNames = CHECK_NAMES.filter(name => record.checks[name]?.status === "lookup_failed");
  return {
    moveId: record.move_id, file: item.file, fileText: fileText(item.file), variant: record.target.variant,
    tags: TAG_AXES.map(axis => ({ axis, text: listOrEmpty(record.tags[axis]) })),
    resolutionBasis: record.target.resolution_basis, pmid: record.source.pmid,
    bibliographyText: `PMID ${record.source.pmid} · ` + (book === null ? notShownText("서지 없음")
      : [book.title, book.journal, book.year].map(value => value ?? NULL_TEXT).join(" · ")),
    locationsText: record.source.locations.map(locationSummary).join(", "),
    checks: { failNames, lookupFailedNames,
      text: `${KBASE_CHECKS_HEADER} fail ${failNames.length} · lookup_failed ${lookupFailedNames.length}` },
  };
}

export interface FieldView { key: string; text: string }
export interface QuoteView { text: string; quote: string; wordsText: string; truncatedText: string;
  assembledText: string | null }
export interface EffectView {
  metric: string; assay: string; beforeText: string; afterText: string; targetRef: string; targetRole: string;
  /** kbase English value as written (improved / worsened / unchanged / unknown); no translation or tone. */
  direction: string; directionBasis: string; basisText: string; magnitudeBucket: string; comparableText: string;
  comparabilityReasonText: string; foldChangeText: string;
}
export interface RecordDetailView {
  moveId: string; fileText: string;
  bibliography: FieldView[] | null; bibliographyText: string | null;
  target: FieldView[];
  locations: FieldView[][];
  observation: QuoteView;
  tradeoffs: QuoteView[]; tradeoffsText: string | null;
  change: FieldView[];
  effectsHeader: string; effectsNote: string; effects: EffectView[];
  structure: { fields: FieldView[]; links: FieldView[][]; linksText: string | null; note: string };
  interactions: FieldView[][]; interactionsText: string | null;
  checksHeader: string; checksNote: string; checks: { name: string; status: string }[];
  integrityHeader: string; integrity: FieldView[];
  extraction: FieldView[];
  contentHash: string; contentHashNote: string; recordFormat: string;
  otherFields: FieldView[];
  /** UP1 ("원문 대조 안 함: …"). */
  sourceNote: string;
}

type JsonObject = { [key: string]: PrecedentJsonValue };

/** Every key of a kbase object: the listed keys first (in that order, when present), then the rest as stored. */
function fieldViews(value: PrecedentJsonValue | undefined, order: readonly string[], skip: readonly string[] = []):
  FieldView[] {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return [];
  const object = value as JsonObject;
  const keys = [...order.filter(key => Object.prototype.hasOwnProperty.call(object, key)),
    ...Object.keys(object).filter(key => !order.includes(key))].filter(key => !skip.includes(key));
  return keys.map(key => ({ key, text: verbatimText(object[key]) }));
}

function measureText(value: PrecedentMeasure | PrecedentJsonValue): string {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return verbatimText(value);
  const measure = value as PrecedentMeasure;
  if (measure.value === null || measure.value === undefined) return notShownText("kbase 기록에 값 없음");
  return [measure.qualifier, measure.value, measure.unit]
    .filter(part => part !== null && part !== undefined && part !== "").map(part => verbatimText(part)).join(" ");
}

function flagText(name: string, value: PrecedentJsonValue | undefined, on: string, off: string): string {
  if (value === true) return `${on} (${name} true)`;
  if (value === false) return `${off} (${name} false)`;
  return `${name} ${verbatimText(value)}`;
}

function assembledText(checks: PrecedentRecordItem["record"]["checks"], path: readonly (string | number)[]):
  string | null {
  const entries = checks.quote_in_source?.quote_assembled;
  if (!Array.isArray(entries)) return null;
  const wanted = path.map(String).join(".");
  const found = entries.filter(entry => typeof entry === "object" && entry !== null && !Array.isArray(entry) &&
    Array.isArray((entry as JsonObject).path) && ((entry as JsonObject).path as PrecedentJsonValue[]).map(String)
      .join(".") === wanted) as JsonObject[];
  if (!found.length) return null;
  return "조합된 인용 표시 (quote_assembled): " + found.map(entry =>
    `조각 ${verbatimText(entry.fragment_count)}개 · ${verbatimText(entry.page)}쪽`).join("; ");
}

function quoteView(source: { text?: PrecedentJsonValue; quote?: PrecedentJsonValue;
  quote_truncated?: PrecedentJsonValue }, words: number | null, assembled: string | null): QuoteView {
  return {
    text: verbatimText(source.text),
    quote: source.quote === null || source.quote === undefined ? notShownText("kbase 기록에 인용 없음")
      : verbatimText(source.quote),
    wordsText: words === null ? notShownText("인용 없음") : `${words}단어`,
    truncatedText: flagText("quote_truncated", source.quote_truncated, "인용 잘림 표시", "인용 잘림 표시 없음"),
    assembledText: assembled,
  };
}

export function effectView(effect: PrecedentEffect): EffectView {
  return {
    metric: verbatimText(effect.metric), assay: verbatimText(effect.assay),
    beforeText: measureText(effect.before), afterText: measureText(effect.after),
    targetRef: verbatimText(effect.target_ref), targetRole: verbatimText(effect.target_role),
    direction: verbatimText(effect.direction), directionBasis: verbatimText(effect.direction_basis),
    basisText: `kbase 규칙 v1 산출 (${verbatimText(effect.direction_basis)})`,
    magnitudeBucket: verbatimText(effect.magnitude_bucket), comparableText: verbatimText(effect.comparable),
    comparabilityReasonText: verbatimText(effect.comparability_reason),
    foldChangeText: effect.fold_change === null || effect.fold_change === undefined
      ? notShownText("kbase 기록에 값 없음, ProtView는 계산하지 않음") : verbatimText(effect.fold_change),
  };
}

const LOCATION_ORDER = ["kind", "page", "table_index", "row", "figure_id", "panel"];
const BIBLIOGRAPHY_ORDER = ["title", "journal", "year", "doi", "pmc"];
const TARGET_ORDER = ["gene", "uniprot", "name_as_written", "resolution_basis", "variant", "candidates"];
const CHANGE_ORDER = ["description", "from_compound", "to_compound", "smiles_from", "smiles_to"];
const LINK_ORDER = ["pdb_id", "chain", "ligand", "basis", "confidence_note", "structure_id", "candidates"];
const INTERACTION_ORDER = ["interaction", "aa", "uniprot_resnum", "klifs_position", "change", "before_distance_a",
  "after_distance_a", "anchor", "anchor_basis", "vocabulary", "source"];
const EXTRACTION_KEYS = ["model", "provider", "prompt_version", "run_at"];
const OTHER_KEYS = ["review_status", "schema_version", "mutations", "proposed_tags", "figures"];

/** The expanded precedent: every kbase field shown as written, the two check channels apart, UP1 and UP4. */
export function recordDetailView(item: PrecedentRecordItem, bibliography: KinasePrecedentsDetail["bibliography"]):
  RecordDetailView {
  const record = item.record;
  const integrity = item.integrity;
  const book = bibliographyOf(bibliography, record.source.pmid);
  return {
    moveId: record.move_id, fileText: fileText(item.file),
    bibliography: book === null ? null : fieldViews(book as unknown as JsonObject, BIBLIOGRAPHY_ORDER),
    bibliographyText: book === null ? notShownText("서지 없음: 서지 스냅샷에 이 PMID의 행이 없음") : null,
    target: fieldViews(record.target as unknown as JsonObject, TARGET_ORDER),
    locations: record.source.locations.map(location => fieldViews(location as unknown as JsonObject, LOCATION_ORDER)),
    observation: quoteView(record.observation, integrity.observation_quote_words,
      assembledText(record.checks, ["observation", "quote"])),
    tradeoffs: record.tradeoffs.map((tradeoff, i) => quoteView(tradeoff, integrity.tradeoff_quote_words[i] ?? null,
      assembledText(record.checks, ["tradeoffs", i, "quote"]))),
    tradeoffsText: record.tradeoffs.length ? null : EMPTY_LIST_TEXT,
    change: fieldViews(record.change, CHANGE_ORDER),
    effectsHeader: EFFECTS_HEADER, effectsNote: PRECEDENT_STATEMENTS.KP2, effects: record.effects.map(effectView),
    structure: {
      fields: [{ key: "structure_ref", text: verbatimText(record.structure_ref) },
        { key: "structure_link_reason", text: verbatimText(record.structure_link_reason) },
        { key: "structure_ref_from", text: verbatimText(record.structure_ref_from) }],
      links: record.structure_links.map(link => fieldViews(link as unknown as JsonObject, LINK_ORDER)),
      linksText: record.structure_links.length ? null : EMPTY_LIST_TEXT, note: PRECEDENT_SCREEN_NOTES.UP4 },
    interactions: record.interactions.map(entry => fieldViews(entry, INTERACTION_ORDER)),
    interactionsText: record.interactions.length ? null : EMPTY_LIST_TEXT,
    checksHeader: KBASE_CHECKS_HEADER, checksNote: PRECEDENT_STATEMENTS.KP3,
    checks: CHECK_NAMES.map(name => ({ name, status: verbatimText(record.checks[name]?.status) })),
    integrityHeader: INTEGRITY_HEADER,
    integrity: [
      { key: "hash_verified", text: flagText("hash_verified", integrity.hash_verified, "레코드 해시 일치",
        "레코드 해시 불일치") },
      { key: "observation_quote_words", text: `관찰 인용 ${integrity.observation_quote_words}단어` },
      { key: "tradeoff_quote_words", text: integrity.tradeoff_quote_words.length
        ? "교환 인용 " + integrity.tradeoff_quote_words.map(words => words === null ? notShownText("인용 없음")
          : `${words}단어`).join(", ") : `교환 인용 ${EMPTY_LIST_TEXT}` },
      { key: "quotes_within_limit", text: flagText("quotes_within_limit", integrity.quotes_within_limit,
        "모든 인용 25단어 이하", "25단어를 넘는 인용 있음") },
      { key: "locations_have_page", text: flagText("locations_have_page", integrity.locations_have_page,
        "논문 쪽 위치 있음", "쪽 없는 논문 위치 있음") }],
    extraction: fieldViews(record.extraction as unknown as JsonObject, EXTRACTION_KEYS)
      .filter(field => EXTRACTION_KEYS.includes(field.key)),
    contentHash: record.content_hash, contentHashNote: CONTENT_HASH_NOTE, recordFormat: PRECEDENT_RECORD_FORMAT,
    otherFields: fieldViews(record as unknown as JsonObject, OTHER_KEYS).filter(field => OTHER_KEYS.includes(field.key)),
    sourceNote: PRECEDENT_SCREEN_NOTES.UP1,
  };
}

export interface PrecedentResultView {
  numberingMapText: string; structureText: string; pdbIdText: string; includeFlaggedText: string;
  recordFormatText: string; setHashShort: string; importedAt: string; kbVersion: string; processedLabel: string;
  licenseNote: string; badge: PrecedentSnapshotBadge; badgeText: string | null;
  countRows: { key: string; label: string; text: string }[];
  chains: ChainView[];
  /** UP5 under the chain table: a set-wide number, not tied to these chains. */
  unresolvedNote: string;
  targets: TargetView[]; selectedTarget: string | null; noTargetText: string | null;
  nullResult: boolean; nullResultText: string | null;
  pageText: string; records: RecordRowView[];
  /** The stored `limitations` (KP1–KP6), verbatim. */
  limitations: readonly string[];
}

function countRows(counts: KinasePrecedentsCounts): { key: string; label: string; text: string }[] {
  return [
    { key: "chains", label: "체인", text: `${counts.chains}개` },
    { key: "linked_chains", label: "연결한 체인", text: `${counts.linked_chains}개` },
    { key: "not_linked_chains", label: "연결하지 않은 체인", text: `${counts.not_linked_chains}개` },
    { key: "targets", label: "표적", text: `${counts.targets}개` },
    { key: "records_moves", label: "포함한 moves 파일 전례", text: `${counts.records.moves}건` },
    { key: "records_moves_flagged", label: "포함한 moves_flagged 파일 전례",
      text: counts.records.moves_flagged === null ? notShownText("포함하지 않음") : `${counts.records.moves_flagged}건` },
    { key: "excluded_moves_flagged", label: "포함하지 않은 moves_flagged 파일 전례",
      text: counts.excluded_moves_flagged === null ? notShownText("moves_flagged 파일을 포함해 미포함 수 없음")
        : `${counts.excluded_moves_flagged}건` },
  ];
}

/** Display model of one detail answer. Numbers are the server's stored counts; nothing is recounted or sorted. */
export function precedentResultView(detail: KinasePrecedentsDetail): PrecedentResultView {
  const badge = resultSnapshotBadge(detail.active_set);
  const noTarget = detail.page.target === null;
  return {
    numberingMapText: detail.numbering_map.handle,
    structureText: `${detail.structure.handle} (${detail.structure.structure_kind}, 모델 ${detail.structure.model_number})`,
    pdbIdText: detail.pdb_id ?? notShownText("번호 대응에 PDB ID가 없음"),
    includeFlaggedText: detail.include_flagged ? `${FLAGGED_TOGGLE_LABEL}함 (include_flagged true)`
      : `${FLAGGED_TOGGLE_LABEL}하지 않음 (include_flagged false)`,
    recordFormatText: `전례 사본 형식 ${detail.record_format}`,
    setHashShort: detail.precedent_set.set_hash.slice(0, 12), importedAt: detail.precedent_set.imported_at,
    kbVersion: detail.precedent_set.kbase.kb_version, processedLabel: PROCESSED_LABEL,
    licenseNote: PRECEDENT_STATEMENTS.KT1, badge, badgeText: snapshotBadgeText(badge),
    countRows: countRows(detail.counts),
    chains: detail.chains.map(chainView),
    unresolvedNote: screenNote("UP5", unresolvedRecordTotal(detail.set_summary)),
    targets: detail.targets_overview.map(targetView), selectedTarget: detail.page.target,
    noTargetText: noTarget ? NO_TARGET_TEXT : null,
    nullResult: detail.null_result, nullResultText: detail.null_result ? NULL_RESULT_TEXT : null,
    pageText: recordPageText(detail.page, detail.records.length),
    records: detail.records.map(item => recordRowView(item, detail.bibliography)),
    limitations: detail.limitations,
  };
}

// ---- area state (five states) ----

export type PrecedentPanelState =
  | { state: "loading" } | { state: "ready" } | { state: "empty"; message: string }
  | { state: "failed"; message: string } | { state: "unavailable"; reason: string };

/**
 * Five states. `capability` undefined = not read yet, null = absent (the area shows the reason only). A missing or
 * invalid snapshot is NOT the area's "unavailable": stored results still open from events alone; the snapshot block
 * shows its reason and the request block is closed (`requestUnavailableReason`). An empty result is not a failure.
 */
export function precedentPanelState(input: { runId: string | null;
  capability?: { available: boolean; reason: string | null } | null; loading?: boolean; error?: string | null;
  detail?: { null_result: boolean } | null }): PrecedentPanelState {
  if (input.runId === null) return { state: "unavailable", reason: NO_RUN_REASON };
  if (input.capability === null) return { state: "unavailable", reason: CAPABILITY_REASON };
  if (input.error) return { state: "failed", message: input.error };
  if (input.loading || input.capability === undefined) return { state: "loading" };
  if (input.detail?.null_result) return { state: "empty", message: NULL_RESULT_TEXT };
  return { state: "ready" };
}

// ---- late responses (run + result handle + request number per area) ----

export const PRECEDENT_AREAS = ["status", "maps", "rows", "command", "list", "detail", "report"] as const;
export interface PrecedentStamp { runId: string | null; handle: string | null; seq: number }

/** Applied only when run, result handle and request number are all still current. */
export function precedentResponseCurrent(captured: PrecedentStamp, live: PrecedentStamp): boolean {
  return captured.runId !== null && captured.runId === live.runId && captured.handle === live.handle &&
    captured.seq === live.seq;
}

/** A created report was saved: announce it while the run is unchanged, even when the late inline display is dropped. */
export function precedentReportSavedForRun(captured: PrecedentStamp, liveRunId: string | null): boolean {
  return captured.runId !== null && captured.runId === liveRunId;
}

/** The report belongs to the opened result. */
export function precedentReportMatches(artifact: { manifest: { schema?: unknown; analysis_type?: unknown;
  result_handle?: unknown } }, resultHandle: string): boolean {
  return artifact.manifest.schema === "method_report_manifest@1" &&
    artifact.manifest.analysis_type === PRECEDENT_REPORT_TYPE && artifact.manifest.result_handle === resultHandle;
}

// ---- wording check (precedents are never ranked, recommended, verified, aggregated or called an effect) ----

/** Lines exempt from the check: exactly a fixed sentence KP1–KP6 / KT1 or a screen note UP1–UP5 (KP6 names 순위 …). */
export const PRECEDENT_FIXED_LINES: readonly string[] = [...Object.values(PRECEDENT_STATEMENTS),
  ...Object.values(PRECEDENT_SCREEN_NOTES)];
/** Terms removed before the check: the spec's measured-change heading, which names the kbase field `effects`. */
export const PRECEDENT_EXEMPT_TERMS: readonly string[] = [EFFECTS_HEADER];
/**
 * The interpretive wording of the M27 report check (M15 + M20 + M26 lists with their English counterparts, plus
 * 성공률·검증됨·신뢰·효과·승자) and 최고·우수·악화. kbase values (tag terms, directions, titles, quotes) are server
 * values shown as written, never this module's wording, and are not checked here.
 */
export const PRECEDENT_FORBIDDEN = new RegExp([
  "important", "critical", "essential", "key residue", "binding", "binds", "affinity", "stabili[sz]", "druggab",
  "inhibit", "selectiv", "potency", "functional", "중요", "결합", "친화", "안정화", "억제", "선택성", "핵심", "기능",
  "안정성", "ΔΔG", "ddG", "delta\\s*delta", "순위", "추천", "최적", "개선", "활성", "예측", "유망", "좋은", "나쁜", "안전",
  "점수", "에너지", "수소\\s*결합", "\\brank", "\\bbest\\b", "recommend", "optimal", "improv", "predict", "promising",
  "\\bgood\\b", "\\bsafe", "\\bactiv(?:e|ity)\\b", "\\bscor(?:e|ing)\\b", "energ", "hydrogen[\\s_-]?bond", "\\bh-?bond",
  "필수", "메커니즘이\\s*유지", "mechanism\\W+(?:is\\W+)?(?:preserved|maintained|retained|conserved)",
  "성공률", "검증됨", "신뢰", "효과", "승자", "success[\\s_-]*rate", "\\bverified\\b", "\\bvalidated\\b", "\\btrust",
  "\\breliab", "\\beffects?\\b", "\\bwinner", "최고", "우수", "악화", "highest", "stabilit",
].join("|"), "gi");

/** Forbidden words in screen text, line by line; fixed lines are exempt, the exempt terms are removed first. */
export function precedentForbiddenWords(text: string): string[] {
  const found: string[] = [];
  for (const line of text.split("\n")) {
    if (PRECEDENT_FIXED_LINES.includes(line)) continue;
    let checked = line;
    for (const term of PRECEDENT_EXEMPT_TERMS) checked = checked.split(term).join(" ");
    for (const match of checked.matchAll(PRECEDENT_FORBIDDEN)) found.push(match[0]);
  }
  return found;
}
