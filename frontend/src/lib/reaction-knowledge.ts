/**
 * Pure logic of the M26 "효소 반응 지식" area in the 지식·보고서 tab (M26 spec `.dryforge/spec.md` 2, 5, 6, 10.1, 11).
 *
 * Catalytic residues, UniProt sites and reactions are reference values copied verbatim from the pinned snapshot
 * (M-CSA · UniProt · Rhea, "참조값, 계산 아님"); the only computed values are the counts the server stored. This module
 * never computes, counts, ranks, sorts, filters by role or recomputes a scientific value: it builds and checks the
 * request (mirroring the server admission so the screen can say why a request is blocked; the server checks
 * everything again), turns server answers into display models that keep "not checked", "not available" and "not
 * computed" apart from 0 and from "none" (always "—" with the reason), names every closed code as "한국어 (code)",
 * keeps late responses out and checks the module's own wording. Rows, sites and entries keep the order the server
 * stored; M-CSA role text is shown as written (never translated, summarized or interpreted).
 */
import type { CommandResult } from "./api";
import type { ExactResidueRef, ReactionKnowledgeArgs, ReactionKnowledgeDetail, ReactionKnowledgeDetailChain,
  ReactionKnowledgeListItem, ReactionMcsaRole, ReactionMcsaRow, ReactionPdbEntries, ReactionReferenceStatus,
  ReactionRheaReferenceRow, ReactionRowStatus, ReactionUniprotFeature, ReactionUniprotLink, RunEvent } from "./contracts";
import type { NumberingMapListRow } from "./numbering";
import { numberingStructures, PDB_ID_PATTERN, polymerChains } from "./numbering";

// ---- closed sets, limits and fixed wording (backend/mw/reaction_knowledge_constants.py; change both sides) ----

export const REACTION_TOOL = "link_reaction_knowledge";
export const REACTION_KIND = "reaction_knowledge";
export const REACTION_SCHEMA = "reaction_knowledge@1";
export const REACTION_METHOD_VERSION = "mw.reaction_knowledge/v1";
export const REACTION_STATUS_SCHEMA = "reaction_reference_status@1";
export const REACTION_REPORT_TYPE = "reaction_knowledge";
export const REACTION_REPORT_LABEL = "효소 반응 지식 보고서";
export const REACTION_SOURCES = ["mcsa", "uniprot_function", "rhea"] as const;
export const SNAPSHOT_REASON_CODES = ["not_installed", "snapshot_invalid"] as const;
/** `link_reaction_knowledge` admission reasons (`detail.reason_code`, 422), in the server's check order. */
export const ADMISSION_REASON_CODES = ["unknown_field", "structure_invalid", "pdb_id_invalid", "chains_invalid",
  "chain_not_found", "accession_invalid", "numbering_map_invalid", "structure_mismatch", "map_pdb_mismatch"] as const;
export const RESULT_INVALID_REASON = "result_invalid";
export const RESULT_TOO_LARGE_REASON = "result_too_large";
export const TOO_MANY_LINKS_REASON = "too_many_links";
export const MCSA_STATUSES = ["checked", "not_checked"] as const;
export const MCSA_NOT_CHECKED_REASON = "pdb_id_not_given";
export const COVERAGE = ["covered", "chain_not_listed", "pdb_not_in_snapshot"] as const;
export const ROW_STATUSES = ["matched", "unmatched", "conflict"] as const;
export const UNMATCHED_REASONS = ["non_standard_code", "no_author_number", "residue_not_in_structure",
  "ambiguous_residue_number", "insertion_code_present"] as const;
export const CONFLICT_REASONS = ["residue_name_differs", "mcsa_rows_disagree"] as const;
export const UNIPROT_STATUSES = ["checked", "not_checked", "not_available"] as const;
export const UNIPROT_REASONS = ["accession_not_given", "accession_not_in_snapshot", "accession_skipped_at_import"] as const;
export const LINK_STATUSES = ["mapped", "not_in_map"] as const;
export const LINK_REASONS = ["numbering_map_not_given", "chain_not_in_map", "map_accession_differs"] as const;
export const REACTIONS_STATUSES = ["checked", "not_checked"] as const;
export const REACTIONS_NOT_CHECKED_REASON = "no_source";
export const ACCESSION_SOURCES = ["user", "numbering_map"] as const;
export const CHAIN_FLAGS = ["accession_differs_from_mcsa"] as const;
export const SITE_TYPES = ["Active site", "Binding site", "Site"] as const;
export const SKIP_REASONS = ["obsolete", "merged", "demerged", "not_found", "fetch_failed"] as const;
export const RESIDUE_FIELDS = ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode",
  "resname"] as const;
export const STRUCTURE_KINDS = ["structure", "prepared_structure"] as const;
/** Caps of one result (refused with 429, never truncated). */
export const MAX_RESULT_BYTES = 1024 * 1024;
export const MAX_LINKS = 2000;
/** UniProt accession format of the request (spec 4.1; `UNIPROT_ACCESSION_PATTERN` of the backend, case as is). */
export const UNIPROT_ACCESSION_PATTERN_SOURCE =
  "(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})";
const ACCESSION_RE = new RegExp(`^${UNIPROT_ACCESSION_PATTERN_SOURCE}$`);
/** Read page limits (backend/mw/reaction_knowledge_reads.py). */
export const LIST_LIMIT_DEFAULT = 50;
export const LIST_LIMIT_MAX = 100;
export const CHAIN_LIMIT_DEFAULT = 10;
export const CHAIN_LIMIT_MAX = 10;
export const ROW_LIMIT_DEFAULT = 50;
export const ROW_LIMIT_MAX = 200;
export const FEATURE_LIMIT_DEFAULT = 50;
export const FEATURE_LIMIT_MAX = 200;

/** Fixed sentences RK1–RK6 (spec 11.1), verbatim and in order; the result stores RK1–RK5 as `limitations`. */
export const REACTION_STATEMENTS = {
  RK1: "촉매 잔기·부위·반응은 참조 스냅샷(M-CSA·UniProt·Rhea)에 적힌 값이며 ProtView가 계산하거나 판정한 것이 아니다.",
  RK2: "대응됨은 M-CSA가 적은 PDB·체인·번호와 이 구조의 잔기 이름이 모두 같다는 뜻이며 잔기의 역할이나 활성을 " +
    "뜻하지 않는다.",
  RK3: "대응 없음·충돌·검사하지 않음은 이 스냅샷과 방법으로 확실하지 않다는 뜻이며 촉매 잔기가 없다는 뜻이 아니다.",
  RK4: "UniProt 부위는 번호 대응이 있는 체인에서만 구조 잔기에 연결했고 그 밖에는 단백질 서열 위치로만 보여 준다.",
  RK5: "반응 정보는 효소 활성·속도·특이성이나 반응 메커니즘이 유지된다는 뜻이 아니다.",
  RK6: "M-CSA·UniProt·Rhea 자료는 CC BY 4.0이며 출처·스냅샷 날짜는 아래에 있다.",
} as const;
export const REACTION_LIMITATIONS: readonly string[] = [REACTION_STATEMENTS.RK1, REACTION_STATEMENTS.RK2,
  REACTION_STATEMENTS.RK3, REACTION_STATEMENTS.RK4, REACTION_STATEMENTS.RK5];
/** Fixed screen notes UK1–UK4 (spec 11.1), verbatim. UK2 / UK3 are shown by the M20 area (`lib/mutations.ts`). */
export const REACTION_SCREEN_NOTES = {
  UK1: "촉매 잔기·부위·반응은 M-CSA·UniProt·Rhea가 적은 참조값이며 ProtView가 계산한 값이 아니다. 가져온 " +
    "스냅샷 날짜 기준이다.",
  UK2: "촉매 잔기 검사 안 함: 이 집합은 M-CSA 촉매 잔기 주석 없이 만들었거나 일부 체인만 검사했다.",
  UK3: "UniProt 부위 정보는 지식 탭에서만 보이며 보호에 쓰지 않음.",
  UK4: "이 체인을 M-CSA가 다루지 않았다는 것은 촉매 잔기가 없다는 뜻이 아니다.",
} as const;

// ---- fixed screen text ----

export const PANEL_TITLE = "효소 반응 지식";
export const NULL_TEXT = "—";
export const REFERENCE_COLUMN_LABEL = "M-CSA 원문, 계산 아님";
export const REFERENCE_NOTE = "참조값, 계산 아님";
export const PROCESSED_LABEL = "공개 서버에서 가져온 가공본";
export const LICENSE_LABEL = "CC BY 4.0";
/** The user-run import command (the only network use of M26; docs/operations.md names the same command). */
export const REACTION_IMPORT_COMMAND = ".venv/bin/python scripts/import_reaction_references.py";
export const IMPORT_HINT = "반응 참조 스냅샷은 사용자가 터미널에서 가져오기 명령으로 설치합니다(이 명령만 공개 서버에 " +
  "읽기 요청을 보냅니다):";
export const NO_RUN_REASON = "run이 없습니다. 구조 분석 탭에서 run을 먼저 고르세요.";
export const CAPABILITY_REASON = "효소 반응 지식 영역을 사용할 수 없습니다(서버가 이 방법을 알리지 않음).";
export const NO_STRUCTURE_REASON = "이 run에 구조가 없습니다. 구조 분석 탭에서 구조를 먼저 불러오세요.";
export const STATUS_LOADING_REASON = "반응 참조 스냅샷 상태를 읽는 중입니다.";
export const STRUCTURE_NOTE = "전처리 구조를 권장합니다. 구조는 자동으로 고르지 않습니다.";
export const PDB_ID_NOTE = "PDB ID는 제안일 뿐이며 확인해야 보냅니다. 확인하지 않으면 M-CSA를 검사하지 않습니다.";
export const SUGGESTION_NOTE = "M-CSA가 적은 accession은 제안이며 '이 accession 쓰기'를 누를 때만 칸에 들어갑니다.";
export const USE_SUGGESTION_TEXT = "이 accession 쓰기";
export const MAP_NOTE = "번호 대응은 선택 사항이며 같은 구조의 것만 고를 수 있습니다. UniProt 부위는 번호 대응이 있는 " +
  "체인에서만 구조 잔기에 연결됩니다.";
export const LINK_BUTTON_TEXT = "연결하기";
export const STALE_TEXT = "이전 스냅샷 기준";
export const NO_ACTIVE_SET_TEXT = "사용 중 스냅샷 없음";
export const RESPONSE_SHAPE_TEXT = "응답 형식이나 대상이 요청과 다릅니다.";
export const NOT_A_RESULT_TEXT = "도구 결과가 효소 반응 지식 결과(reaction_knowledge@1)가 아닙니다.";
export const REQUEST_FAILED_TEXT = "요청 실패";
export const POSITION_NOTE = "UniProt 부위 위치는 UniProt 서열 위치(1부터)입니다.";
export const NULL_RESULT_TEXT = "빈 결과(scientific_null): 어느 체인도 M-CSA가 다루지 않았고 UniProt 부위와 반응 정보도 " +
  "없습니다. 촉매 잔기가 없다는 뜻이 아닙니다.";
/** The five area states (spec 10.1). */
export const AREA_STATE_LABEL = { loading: "불러오는 중", ready: "준비", scientific_null: "빈 결과", failed: "실패",
  unavailable: "사용할 수 없음" } as const;

export const SOURCE_LABEL: Record<(typeof REACTION_SOURCES)[number], string> = {
  mcsa: "M-CSA", uniprot_function: "UniProt", rhea: "Rhea" };
export const SECTION_STATUS_LABEL: Record<string, string> = {
  checked: "검사함", not_checked: "검사하지 않음", not_available: "사용할 수 없음" };
export const COVERAGE_LABEL: Record<(typeof COVERAGE)[number], string> = {
  covered: "M-CSA가 이 체인을 다룸", chain_not_listed: "이 체인은 M-CSA 행에 없음",
  pdb_not_in_snapshot: "이 PDB ID는 스냅샷에 없음" };
export const ROW_STATUS_LABEL: Record<ReactionRowStatus, string> = { matched: "대응됨", unmatched: "대응 없음",
  conflict: "충돌" };
export const LINK_STATUS_LABEL: Record<(typeof LINK_STATUSES)[number], string> = { mapped: "번호 대응 행 있음",
  not_in_map: "번호 대응에 없음" };
export const ACCESSION_SOURCE_LABEL: Record<(typeof ACCESSION_SOURCES)[number], string> = { user: "사용자 입력",
  numbering_map: "번호 대응에서 가져옴" };
export const FLAG_LABEL: Record<(typeof CHAIN_FLAGS)[number], string> = {
  accession_differs_from_mcsa: "체인 accession이 M-CSA 항목이 적은 accession과 다름(표시만 하며 M-CSA 대응은 PDB 기준 " +
    "그대로)" };
export const IN_SNAPSHOT_LABEL = { true: "스냅샷에 있음", false: "스냅샷에 없음" } as const;

/**
 * Korean names of every code this area can show: the nine admission reasons, the two snapshot reasons, the result
 * refusals, the section / row / link / skip reasons of a stored result, and the failure classes and read errors.
 */
export const REACTION_REASON_LABEL: Record<string, string> = {
  unknown_field: "알 수 없는 요청 항목",
  structure_invalid: "이 run의 구조·전처리 구조가 아니거나 읽을 수 없음",
  pdb_id_invalid: "PDB ID 형식 오류(숫자 하나와 영숫자 셋)",
  chains_invalid: "체인 목록 오류(비었음·모양·중복·알 수 없는 키)",
  chain_not_found: "구조가 가리키는 모델에 이 체인의 사슬 잔기가 없음",
  accession_invalid: "UniProt accession 형식이 아님",
  numbering_map_invalid: "이 run의 번호 대응이 아님",
  structure_mismatch: "다른 구조의 번호 대응",
  map_pdb_mismatch: "번호 대응의 PDB ID가 요청 PDB ID와 다름",
  not_installed: "반응 참조 스냅샷이 설치되지 않음",
  snapshot_invalid: "반응 참조 스냅샷의 매니페스트·파일 해시나 형식이 맞지 않음",
  result_invalid: "만든 결과가 검증을 통과하지 못해 저장하지 않음",
  result_too_large: "결과 크기 상한 초과로 저장하지 않음",
  too_many_links: "연결 위치 수 상한 초과로 저장하지 않음",
  pdb_id_not_given: "PDB ID를 주지 않음",
  accession_not_given: "accession을 주지 않음",
  accession_not_in_snapshot: "스냅샷에 없는 accession",
  accession_skipped_at_import: "가져올 때 건너뛴 accession",
  no_source: "반응 정보를 준 출처가 없음",
  non_standard_code: "M-CSA 잔기 이름이 표준 20종이 아님",
  no_author_number: "M-CSA에 저자 번호가 없음",
  residue_not_in_structure: "이 번호의 사슬 잔기가 구조에 없음",
  ambiguous_residue_number: "같은 번호의 사슬 잔기가 여럿",
  insertion_code_present: "구조 잔기에 삽입 코드가 있음",
  residue_name_differs: "구조 잔기 이름이 M-CSA 잔기 이름과 다름",
  mcsa_rows_disagree: "M-CSA 행끼리 잔기 이름이 다름",
  numbering_map_not_given: "번호 대응을 주지 않아 연결하지 않음",
  chain_not_in_map: "번호 대응에 이 체인이 없어 연결하지 않음",
  map_accession_differs: "번호 대응에서 정한 accession이 없거나 체인 accession과 달라 연결하지 않음",
  input_invalid: "요청 오류",
  precondition: "선행 조건이 없음",
  resource_exceeded: "상한 초과",
  transient: "일시 오류",
  fatal: "서버 오류",
  not_found: "찾을 수 없음(이 run의 효소 반응 지식 결과가 아님)",
  run_corrupt: "run 기록 오류",
  method_evidence_invalid: "저장된 결과가 검증되지 않음",
  report_evidence_invalid: "보고서 근거가 검증되지 않음",
  cancelled: "run이 취소됨",
};

/** Why an accession was skipped at import (manifest `skipped_accessions[].reason`, shown with its targets). */
export const SKIP_REASON_LABEL: Record<(typeof SKIP_REASONS)[number], string> = {
  obsolete: "UniProt에서 폐기된 accession", merged: "다른 accession으로 병합됨", demerged: "여러 accession으로 분할됨",
  not_found: "UniProt에서 찾지 못함", fetch_failed: "가져올 때 받지 못함" };

const own = (table: Record<string, string>, code: string) =>
  Object.prototype.hasOwnProperty.call(table, code) ? table[code] : undefined;

/** "한국어 (code)" so the identifier stays visible; unknown codes are shown as is. */
export function reactionReasonText(code: string): string {
  const label = own(REACTION_REASON_LABEL, code);
  return label ? `${label} (${code})` : code;
}

/** "한국어 (code)" of an import skip reason; unknown codes are shown as is. */
export function skipReasonText(code: string): string {
  const label = own(SKIP_REASON_LABEL, code);
  return label ? `${label} (${code})` : code;
}

/** "—" with the reason: every value that was not checked, is not available or was not computed. */
export function notShownText(reason: string): string {
  return `${NULL_TEXT} (${reason})`;
}

function statusText(code: string): string {
  const label = own(SECTION_STATUS_LABEL, code);
  return label ? `${label} (${code})` : code;
}

function coverageText(code: string | null): string {
  if (code === null) return NULL_TEXT;
  const label = own(COVERAGE_LABEL, code);
  return label ? `${label} (${code})` : code;
}

export function licenseText(license: string): string {
  return license === "CC-BY-4.0" ? `${LICENSE_LABEL} (${license})` : license;
}

// ---- request: structure, PDB ID, chains, numbering map (same structure only; nothing auto-picked) ----

/** This run's `structure` / `prepared_structure` handles in creation order (the tool's accepted kinds). */
export function reactionStructures(events: RunEvent[]): { handle: string; kind: (typeof STRUCTURE_KINDS)[number] }[] {
  return numberingStructures(events);
}

export function isAccession(value: string): boolean {
  return ACCESSION_RE.test(value);
}

export function normalizedPdbId(text: string): string | null {
  const value = text.trim();
  return PDB_ID_PATTERN.test(value) ? value.toUpperCase() : null;
}

export interface ReactionChainChoice { chain_auth: string; selected: boolean;
  /** The typed accession, kept as typed; blank = none (sent as null). */
  accession: string }
export interface ReactionForm {
  structure: string | null;
  /** Suggested or typed PDB ID; sent only when `pdbIdConfirmed` (otherwise `pdb_id: null`). */
  pdbId: string;
  pdbIdConfirmed: boolean;
  chains: ReactionChainChoice[];
  numberingMap: string | null;
}

export function emptyReactionForm(): ReactionForm {
  return { structure: null, pdbId: "", pdbIdConfirmed: false, chains: [], numberingMap: null };
}

/**
 * A new structure clears everything tied to the old one. Chain rows are the structure's polymer chains in file order
 * (from the residue list's `category`; the tool's chain residue rule decides on the server), none selected.
 */
export function formForStructure(structure: string | null,
                                 residues: readonly { chain_auth: string; category: string }[]): ReactionForm {
  return { ...emptyReactionForm(), structure,
    chains: polymerChains([...residues]).map(chain_auth => ({ chain_auth, selected: false, accession: "" })) };
}

export function mapsForStructure(rows: readonly NumberingMapListRow[], structure: string | null): NumberingMapListRow[] {
  return structure === null ? [] : rows.filter(row => row.structure === structure);
}

/** The newest same-structure numbering map (highest `created_seq`), or null. */
export function newestMapForStructure(rows: readonly NumberingMapListRow[], structure: string | null):
  NumberingMapListRow | null {
  const offered = mapsForStructure(rows, structure);
  return offered.length ? offered.reduce((best, row) => row.created_seq > best.created_seq ? row : best) : null;
}

/**
 * The accession a numbering map states for one chain: the accession the person requested there, else the single
 * SIFTS accession; several (fused) or none -> null. A suggestion only; the server derives the map accession itself.
 */
export function mapChainAccession(row: NumberingMapListRow, chain: string): string | null {
  const detail = row.chain_details.find(item => item.chain_auth === chain);
  if (!detail) return null;
  if (detail.requested_uniprot_accession) return detail.requested_uniprot_accession;
  return detail.sifts && detail.sifts.accessions.length === 1 ? detail.sifts.accessions[0] : null;
}

export interface MapPrefill { map: string; pdbId: string | null; accessions: Record<string, string> }

/** Suggestions from the newest same-structure numbering map (its PDB ID and chain accessions), or null. */
export function mapPrefill(rows: readonly NumberingMapListRow[], structure: string | null,
                           chains: readonly string[]): MapPrefill | null {
  const newest = newestMapForStructure(rows, structure);
  if (!newest) return null;
  const accessions: Record<string, string> = {};
  for (const chain of chains) {
    const accession = mapChainAccession(newest, chain);
    if (accession !== null) accessions[chain] = accession;
  }
  return { map: newest.handle, pdbId: newest.pdb_id, accessions };
}

/** The PDB ID to suggest: the newest same-structure map's (a value the person confirmed in M15), else the file's. */
export function pdbIdSuggestion(prefill: MapPrefill | null, fileHint: string | null): string | null {
  return prefill?.pdbId ?? fileHint ?? null;
}

/**
 * Fills the suggestions into empty fields only: the PDB ID while it is empty and unconfirmed, and the accession of
 * each chain whose field is empty. Never selects a chain, confirms the PDB ID or chooses the numbering map.
 */
export function applySuggestions(form: ReactionForm, pdbId: string | null,
                                 prefill: MapPrefill | null): ReactionForm {
  return { ...form,
    pdbId: !form.pdbId.trim() && !form.pdbIdConfirmed && pdbId !== null ? pdbId : form.pdbId,
    chains: form.chains.map(choice => choice.accession.trim() || !prefill ||
      !Object.prototype.hasOwnProperty.call(prefill.accessions, choice.chain_auth) ? choice
      : { ...choice, accession: prefill.accessions[choice.chain_auth] }) };
}

export function setChainSelected(form: ReactionForm, chain: string, selected: boolean): ReactionForm {
  return { ...form, chains: form.chains.map(choice => choice.chain_auth === chain ? { ...choice, selected } : choice) };
}

export function setChainAccession(form: ReactionForm, chain: string, accession: string): ReactionForm {
  return { ...form, chains: form.chains.map(choice => choice.chain_auth === chain ? { ...choice, accession } : choice) };
}

/** A PDB lookup answer for exactly this (confirmed, normalized) PDB ID. */
export function pdbLookupMatches(value: unknown, pdbId: string): value is ReactionPdbEntries {
  if (typeof value !== "object" || value === null) return false;
  const lookup = value as Partial<ReactionPdbEntries>;
  return lookup.pdb_id === pdbId && Array.isArray(lookup.entries);
}

export interface AccessionSuggestion { accession: string; mcsaId: number; enzymeName: string; text: string }

/**
 * "이 accession 쓰기" choices of one chain: for each M-CSA entry (server order) that lists this chain for the PDB ID,
 * each accession of its `reference_uniprot_id` (split on "," and trimmed, accession format only, first time only).
 * Nothing is applied: the person presses the button (`setChainAccession`).
 */
export function accessionSuggestions(lookup: ReactionPdbEntries | null, chain: string): AccessionSuggestion[] {
  if (!lookup) return [];
  const seen = new Set<string>();
  const out: AccessionSuggestion[] = [];
  for (const entry of lookup.entries) {
    if (!entry.chains.includes(chain)) continue;
    for (const part of entry.reference_uniprot_id.split(",")) {
      const accession = part.trim();
      if (!isAccession(accession) || seen.has(accession)) continue;
      seen.add(accession);
      out.push({ accession, mcsaId: entry.mcsa_id, enzymeName: entry.enzyme_name,
        text: `${accession} · M-CSA ${entry.mcsa_id} ${entry.enzyme_name} (${REFERENCE_NOTE})` });
    }
  }
  return out;
}

/** What the PDB lookup says, without numbers that could read as "no catalytic residue". */
export function pdbLookupText(lookup: ReactionPdbEntries): string {
  return lookup.entries.length
    ? `M-CSA 항목 ${lookup.entries.length}개가 PDB ${lookup.pdb_id}를 적었습니다(${REFERENCE_NOTE}).`
    : `PDB ${lookup.pdb_id}를 적은 M-CSA 항목이 이 스냅샷에 없습니다. 촉매 잔기가 없다는 뜻이 아닙니다.`;
}

export type ReactionFormField = "snapshot" | "structure" | "pdb_id" | "chains" | "numbering_map";
export interface ReactionFieldError { field: ReactionFormField; chain: string | null; text: string }
export interface ReactionFormOptions {
  /** `reaction_reference_status@1` (null = not read yet). */
  snapshot: Pick<ReactionReferenceStatus, "installed" | "reason"> | null;
  structures: readonly { handle: string; kind: string }[];
  maps: readonly NumberingMapListRow[];
}
export type ReactionFormCheck = { ok: true; args: ReactionKnowledgeArgs } | { ok: false; errors: ReactionFieldError[] };

/** Why the request block shows a reason only (no controls), or null. */
export function requestUnavailableReason(input: { snapshot: Pick<ReactionReferenceStatus, "installed" | "reason"> | null;
  structures: readonly unknown[] | undefined }): string | null {
  if (input.snapshot === null) return STATUS_LOADING_REASON;
  if (!input.snapshot.installed)
    return `사용할 수 없음: ${reactionReasonText(input.snapshot.reason ?? "not_installed")}. ${IMPORT_HINT} ` +
      REACTION_IMPORT_COMMAND;
  if (input.structures !== undefined && !input.structures.length) return NO_STRUCTURE_REASON;
  return null;
}

/**
 * The tool arguments of "연결하기", or every reason (with its field) the request is blocked, in the server's admission
 * order where the screen can know it. The PDB ID is sent only after confirmation; an empty accession is null.
 */
export function checkReactionForm(form: ReactionForm, options: ReactionFormOptions): ReactionFormCheck {
  const errors: ReactionFieldError[] = [];
  const add = (field: ReactionFormField, text: string, chain: string | null = null) => errors.push({ field, chain, text });
  if (options.snapshot === null) add("snapshot", STATUS_LOADING_REASON);
  else if (!options.snapshot.installed)
    add("snapshot", `${reactionReasonText(options.snapshot.reason ?? "not_installed")}: 가져오기 명령으로 스냅샷을 먼저 ` +
      "설치하세요.");
  const structure = form.structure;
  if (structure === null) add("structure", "구조를 고르세요.");
  else if (!options.structures.some(item => item.handle === structure &&
           (STRUCTURE_KINDS as readonly string[]).includes(item.kind)))
    add("structure", "고른 구조가 이 run의 구조·전처리 구조가 아닙니다.");
  const pdbId = form.pdbIdConfirmed ? normalizedPdbId(form.pdbId) : null;
  if (form.pdbIdConfirmed && pdbId === null)
    add("pdb_id", "PDB ID 형식이 올바르지 않습니다(숫자 하나와 영숫자 셋, 예: 1S9I).");
  const selected = form.chains.filter(choice => choice.selected);
  if (!selected.length) add("chains", "체인을 하나 이상 고르세요.");
  const names = selected.map(choice => choice.chain_auth);
  for (const chain of new Set(names.filter((name, i) => names.indexOf(name) !== i)))
    add("chains", "같은 체인이 두 번 있습니다.", chain);
  for (const choice of selected) {
    if (!choice.chain_auth) add("chains", "체인 이름이 비었습니다.", choice.chain_auth);
    const accession = choice.accession.trim();
    if (accession && !isAccession(accession))
      add("chains", `UniProt accession 형식이 아닙니다: ${accession} (대문자, 예: P36507).`, choice.chain_auth);
  }
  const map = form.numberingMap === null ? null
    : mapsForStructure(options.maps, structure).find(row => row.handle === form.numberingMap) ?? null;
  if (form.numberingMap !== null && map === null) add("numbering_map", "고른 번호 대응이 이 구조의 것이 아닙니다.");
  if (map !== null && map.pdb_id !== null && pdbId !== null && map.pdb_id.toUpperCase() !== pdbId)
    add("numbering_map", `번호 대응의 PDB ID(${map.pdb_id})가 확인한 PDB ID(${pdbId})와 다릅니다.`);
  if (errors.length || structure === null) return { ok: false, errors };
  return { ok: true, args: { structure, pdb_id: pdbId,
    chains: selected.map(choice => ({ chain_auth: choice.chain_auth, uniprot_accession: choice.accession.trim() || null })),
    numbering_map: form.numberingMap } };
}

// ---- server refusals ("한국어 (code)" beside the field) ----

const REFUSAL_FIELD: Record<string, ReactionFormField | "request" | "result"> = {
  not_installed: "snapshot", snapshot_invalid: "snapshot", unknown_field: "request", structure_invalid: "structure",
  pdb_id_invalid: "pdb_id", chains_invalid: "chains", chain_not_found: "chains", accession_invalid: "chains",
  numbering_map_invalid: "numbering_map", structure_mismatch: "numbering_map", map_pdb_mismatch: "numbering_map",
  result_invalid: "result", result_too_large: "result", too_many_links: "result",
};

export interface ReactionRefusal { field: ReactionFormField | "request" | "result"; chain: string | null;
  code: string | null; text: string }

/** A refused `link_reaction_knowledge` call (an `ApiError`: `code`, `message`, `detail.reason_code` …) as shown. */
export function reactionRefusal(error: unknown): ReactionRefusal {
  if (typeof error !== "object" || error === null)
    return { field: "request", chain: null, code: null, text: String(error) };
  const { message, code, detail } = error as { message?: unknown; code?: unknown; detail?: Record<string, unknown> };
  const reason = typeof detail?.reason_code === "string" ? detail.reason_code : null;
  const chain = typeof detail?.chain_auth === "string" ? detail.chain_auth : null;
  const field = (reason && own(REFUSAL_FIELD as Record<string, string>, reason) as ReactionRefusal["field"]) || "request";
  const limit = typeof detail?.limit === "number" ? detail.limit : null;
  let text: string;
  if (reason === TOO_MANY_LINKS_REASON && limit !== null)
    text = `${reactionReasonText(reason)}: 연결 위치가 상한 ${limit}개를 넘어 저장하지 않았습니다(자르지 않음). ` +
      "번호 대응을 빼거나 체인을 줄여 다시 요청하세요.";
  else if (reason === RESULT_TOO_LARGE_REASON && limit !== null)
    text = `${reactionReasonText(reason)}: 결과가 ${typeof detail?.actual === "number" ? `${detail.actual} 바이트로 ` : ""}` +
      `상한 ${limit} 바이트를 넘어 저장하지 않았습니다(자르지 않음). 체인을 줄여 다시 요청하세요.`;
  else {
    const head = reason ? reactionReasonText(reason) : typeof code === "string" ? reactionReasonText(code)
      : REQUEST_FAILED_TEXT;
    text = typeof message === "string" && message ? `${head}: ${message}` : head;
  }
  return { field, chain, code: reason ?? (typeof code === "string" ? code : null), text };
}

export type ReactionCommandOutcome = { ok: true; handle: string } | { ok: false; refusal: ReactionRefusal };

/** The command envelope of `link_reaction_knowledge`: a stored `reaction_knowledge@1` handle, or the refusal. */
export function reactionCommandOutcome(result: CommandResult): ReactionCommandOutcome {
  if (!result.ok) {
    if ("message" in result)
      return { ok: false, refusal: reactionRefusal({ code: result.error, message: result.message, detail: result.detail }) };
    return { ok: false, refusal: { field: "request", chain: null, code: null, text: REQUEST_FAILED_TEXT } };
  }
  if (result.handle.kind !== REACTION_KIND || result.handle.schema !== REACTION_SCHEMA)
    return { ok: false, refusal: { field: "result", chain: null, code: null, text: NOT_A_RESULT_TEXT } };
  return { ok: true, handle: result.handle.handle };
}

// ---- reads: detail paging ----

export interface ReactionDetailPaging { chain_offset: number; chain_limit: number; row_offset: number;
  row_limit: number; feature_offset: number; feature_limit: number }
export const DEFAULT_DETAIL_PAGING: ReactionDetailPaging = { chain_offset: 0, chain_limit: CHAIN_LIMIT_DEFAULT,
  row_offset: 0, row_limit: ROW_LIMIT_DEFAULT, feature_offset: 0, feature_limit: FEATURE_LIMIT_DEFAULT };

/** The six paging parameters of the detail read, in a fixed order. */
export function reactionDetailQuery(paging: ReactionDetailPaging = DEFAULT_DETAIL_PAGING): string {
  const params = new URLSearchParams();
  for (const key of ["chain_offset", "chain_limit", "row_offset", "row_limit", "feature_offset", "feature_limit"] as const)
    params.set(key, String(paging[key]));
  return params.toString();
}

/** "전체 N개 중 a–b번째" of one server page (`total` from the server, never recounted). */
export function pageText(total: number | null, offset: number, shown: number): string {
  if (total === null) return NULL_TEXT;
  if (!total || !shown) return `전체 ${total}개 · 이 쪽에 없음`;
  return `전체 ${total}개 중 ${offset + 1}–${offset + shown}번째`;
}

export function nextOffset(total: number | null, offset: number, limit: number): number | null {
  return total !== null && offset + limit < total ? offset + limit : null;
}

export function previousOffset(offset: number, limit: number): number | null {
  return offset > 0 ? Math.max(0, offset - limit) : null;
}

/** A `reaction_knowledge@1` detail answer (paged, with `active_set`); which result it is comes from the stamp. */
export function reactionDetailMatches(value: unknown): value is ReactionKnowledgeDetail {
  if (typeof value !== "object" || value === null) return false;
  const detail = value as Partial<ReactionKnowledgeDetail>;
  return detail.schema === REACTION_SCHEMA && Array.isArray(detail.chains) && typeof detail.page === "object" &&
    detail.page !== null && typeof detail.active_set === "object" && detail.active_set !== null;
}

// ---- snapshot block (no numbers or controls when not installed / invalid) ----

export type ReactionSnapshotView =
  | { state: "unavailable"; reasonCode: string | null; reasonText: string; hint: string; command: string }
  | { state: "ready"; setHash: string; setHashShort: string; importedAt: string; processedLabel: string;
      sources: { source: string; label: string; date: string; licenseText: string; rowsText: string; origin: string }[];
      userNamedText: string; skippedText: string;
      skipped: { accession: string; reasonText: string; targetsText: string }[];
      notes: readonly string[]; licenseNote: string };

export function reactionStatusMatches(value: unknown): value is ReactionReferenceStatus {
  return typeof value === "object" && value !== null &&
    (value as { schema?: unknown }).schema === REACTION_STATUS_SCHEMA &&
    typeof (value as { installed?: unknown }).installed === "boolean";
}

export function reactionSnapshotView(status: ReactionReferenceStatus): ReactionSnapshotView {
  const unavailable = (code: string | null): ReactionSnapshotView => ({ state: "unavailable", reasonCode: code,
    reasonText: code ? reactionReasonText(code) : RESPONSE_SHAPE_TEXT, hint: IMPORT_HINT, command: REACTION_IMPORT_COMMAND });
  if (!status.installed) return unavailable(status.reason ?? "not_installed");
  if (status.set_hash === null || status.imported_at === null || status.sources === null ||
      status.requested_accessions === null || status.skipped_accessions === null) return unavailable(null);
  return { state: "ready", setHash: status.set_hash, setHashShort: status.set_hash.slice(0, 12),
    importedAt: status.imported_at, processedLabel: PROCESSED_LABEL,
    sources: status.sources.map(item => ({ source: item.source, label: own(SOURCE_LABEL, item.source) ?? item.source,
      date: item.date, licenseText: licenseText(item.license), rowsText: `${item.rows}행`, origin: item.origin })),
    userNamedText: `직접 지정한 accession ${status.requested_accessions.user_named.length}개`,
    skippedText: `가져올 때 건너뛴 accession ${status.skipped_accessions.length}개`,
    skipped: status.skipped_accessions.map(item => ({ accession: item.accession,
      reasonText: skipReasonText(item.reason),
      targetsText: item.target_accessions.length ? `대상 ${item.target_accessions.join(", ")}` : NULL_TEXT })),
    notes: [REACTION_STATEMENTS.RK1, REACTION_SCREEN_NOTES.UK1], licenseNote: REACTION_STATEMENTS.RK6 };
}

// ---- "이전 스냅샷 기준" / "사용 중 스냅샷 없음" (never recomputed) ----

export type ReactionSnapshotBadge = "stale" | "no_active_set" | null;

/** Detail: no usable active set -> "사용 중 스냅샷 없음"; another active set -> "이전 스냅샷 기준". */
export function resultSnapshotBadge(activeSet: { set_hash: string | null; same: boolean }): ReactionSnapshotBadge {
  if (activeSet.set_hash === null) return "no_active_set";
  return activeSet.same ? null : "stale";
}

/** List item (`active` is false both without an active set and with another one): needs the status read. */
export function listSnapshotBadge(item: Pick<ReactionKnowledgeListItem, "active">,
                                  installed: boolean | null): ReactionSnapshotBadge {
  if (installed === null) return null;
  if (!installed) return "no_active_set";
  return item.active ? null : "stale";
}

export function snapshotBadgeText(badge: ReactionSnapshotBadge): string | null {
  return badge === "stale" ? STALE_TEXT : badge === "no_active_set" ? NO_ACTIVE_SET_TEXT : null;
}

// ---- result list (newest first, as the server gave) ----

export function resultsForStructure(items: readonly ReactionKnowledgeListItem[],
                                    structure: string | null): ReactionKnowledgeListItem[] {
  return structure === null ? [] : items.filter(item => item.structure_handle === structure);
}

function countsByStatus(counts: Record<ReactionRowStatus, number>): string {
  return ROW_STATUSES.map(status => `${ROW_STATUS_LABEL[status]} ${counts[status]}`).join(" · ");
}

/** One stored result in the list; counts that were not made are "—" with the reason (never 0). */
export function reactionListItemText(item: ReactionKnowledgeListItem): string {
  const pdb = item.pdb_id === null ? `PDB ID ${notShownText("주지 않음")}` : `PDB ${item.pdb_id}`;
  const covered = item.pdb_id === null ? `M-CSA ${notShownText("PDB ID를 주지 않아 검사하지 않음")}`
    : `M-CSA가 다룬 체인 ${item.covered_chain_count}개`;
  const rows = item.mcsa_rows === null
    ? (item.pdb_id === null ? null : `M-CSA 행 ${notShownText("M-CSA가 다룬 체인 없음")}`)
    : `M-CSA 행 ${countsByStatus(item.mcsa_rows)}`;
  const sites = item.uniprot_feature_count === null ? `UniProt 부위 ${notShownText("UniProt 절을 검사한 체인 없음")}`
    : `UniProt 부위 ${item.uniprot_feature_count}개`;
  return [pdb, `체인 ${item.chain_count}개`, covered, rows, sites, item.null_result ? AREA_STATE_LABEL.scientific_null : null]
    .filter((part): part is string => part !== null).join(" · ");
}

// ---- result display model (server order, verbatim reference values, "—" with reasons) ----

export type ResidueFieldsView = Record<(typeof RESIDUE_FIELDS)[number], string>;

/** The 7 identity fields as shown: null is "—"; an empty insertion code stays "" (it is a value, not null). */
export function residueFields(residue: ExactResidueRef | null): ResidueFieldsView | null {
  if (residue === null) return null;
  return { model_number: String(residue.model_number), chain_auth: residue.chain_auth,
    chain_label: residue.chain_label ?? NULL_TEXT, seq_auth: String(residue.seq_auth),
    seq_label: residue.seq_label === null ? NULL_TEXT : String(residue.seq_label), icode: residue.icode,
    resname: residue.resname };
}

/** "GLU auth A/99 icode \"\" label A/97 모델 1" (all 7 fields, null kept as "—"). */
export function residueIdentityText(residue: ExactResidueRef | null, nullReason = "구조 잔기 없음"): string {
  const fields = residueFields(residue);
  if (fields === null) return notShownText(nullReason);
  return `${fields.resname} auth ${fields.chain_auth}/${fields.seq_auth} icode "${fields.icode}" label ` +
    `${fields.chain_label}/${fields.seq_label} 모델 ${fields.model_number}`;
}

/** One M-CSA role, its four fields as written (no translation). */
export function roleText(role: ReactionMcsaRole): string {
  return [role.group_function, role.function_type, role.function, role.emo].join(" / ");
}

export interface McsaRowView {
  mcsaId: number; residueIndex: number; status: ReactionRowStatus; statusText: string; reasonText: string;
  residue: ResidueFieldsView | null; residueText: string; structureResnameText: string;
  listed: { pdbId: string; chainName: string; residText: string; authResidText: string; code: string;
    assembliesText: string };
  isReference: boolean; isReferenceText: string;
  /** M-CSA text exactly as stored (an empty string stays empty); shown under `REFERENCE_COLUMN_LABEL`. */
  reference: { roles_summary: string; function_location_abv: string; ptm: string; roles: ReactionMcsaRole[] | null };
  rolesText: string[] | null;
}

export interface McsaSectionView {
  status: string; statusText: string; reasonText: string | null; coverage: string | null; coverageText: string;
  entries: { mcsaId: number; text: string; ecsText: string }[] | null; entriesText: string | null;
  rows: McsaRowView[] | null; rowsText: string | null; rowPageText: string; countsText: string;
}

export interface FeatureView {
  type: string; rangeText: string; description: string; ligandText: string; linked: boolean; linkText: string;
  links: { position: number; status: string; statusText: string; residue: ResidueFieldsView | null; residueText: string;
    uniprotResidueText: string; residueMatchText: string }[] | null;
}

export interface UniprotSectionView {
  status: string; statusText: string; reasonText: string | null; skippedText: string | null;
  entry: { accession: string; entryName: string; proteinName: string; organism: string; sequenceLengthText: string } | null;
  linkText: string; features: FeatureView[] | null; featuresText: string | null; featurePageText: string;
}

export interface ReactionsSectionView {
  status: string; statusText: string; reasonText: string | null; ecMcsaText: string; ecUniprotText: string;
  compounds: { mcsaId: number; ecText: string; items: { type: string; chebiId: string; name: string }[] }[] | null;
  compoundsText: string | null;
  activities: { reactionName: string; ecText: string; rhea: { rheaId: string; inSnapshot: boolean;
    inSnapshotText: string; equationText: string }[] }[] | null;
  activitiesText: string | null;
}

export interface ChainView {
  chainAuth: string; chainNote: string | null; residueCountText: string; accessionText: string; flags: string[];
  mcsa: McsaSectionView; uniprot: UniprotSectionView; reactions: ReactionsSectionView;
}

function nullableText(value: string | number | null): string {
  return value === null ? NULL_TEXT : String(value);
}

function listText(values: readonly string[] | null, nullReason: string): string {
  if (values === null) return notShownText(nullReason);
  return values.length ? values.join(", ") : "빈 목록 ([])";
}

function mcsaRowView(row: ReactionMcsaRow): McsaRowView {
  return {
    mcsaId: row.mcsa_id, residueIndex: row.residue_index, status: row.status,
    statusText: `${ROW_STATUS_LABEL[row.status] ?? row.status} (${row.status})`,
    reasonText: row.reason === null ? NULL_TEXT : reactionReasonText(row.reason),
    residue: residueFields(row.residue), residueText: residueIdentityText(row.residue),
    structureResnameText: nullableText(row.structure_resname),
    listed: { pdbId: row.listed.pdb_id, chainName: row.listed.chain_name, residText: nullableText(row.listed.resid),
      authResidText: nullableText(row.listed.auth_resid), code: row.listed.code,
      assembliesText: row.listed.assemblies.length ? row.listed.assemblies.join(", ") : NULL_TEXT },
    isReference: row.is_reference,
    isReferenceText: row.is_reference ? "기준 구조 (is_reference true)" : "기준 구조 아님 (is_reference false)",
    reference: row.reference, rolesText: row.reference.roles === null ? null : row.reference.roles.map(roleText),
  };
}

function mcsaView(mcsa: ReactionKnowledgeDetailChain["mcsa"], rowOffset: number): McsaSectionView {
  const covered = mcsa.coverage === "covered";
  const reasonWhy = mcsa.status === "not_checked" ? reactionReasonText(mcsa.reason ?? MCSA_NOT_CHECKED_REASON)
    : coverageText(mcsa.coverage);
  return {
    status: mcsa.status, statusText: statusText(mcsa.status),
    reasonText: mcsa.reason === null ? null : reactionReasonText(mcsa.reason),
    coverage: mcsa.coverage, coverageText: mcsa.status === "not_checked" ? notShownText("검사하지 않음")
      : coverageText(mcsa.coverage),
    entries: mcsa.entries === null ? null : mcsa.entries.map(entry => ({ mcsaId: entry.mcsa_id,
      text: `M-CSA ${entry.mcsa_id} · ${entry.enzyme_name} · UniProt ${entry.reference_uniprot_id || NULL_TEXT}`,
      ecsText: entry.all_ecs.length ? `EC ${entry.all_ecs.join(", ")}` : `EC ${NULL_TEXT}` })),
    entriesText: mcsa.entries === null ? notShownText(reasonWhy) : null,
    rows: mcsa.rows === null ? null : mcsa.rows.map(mcsaRowView),
    rowsText: mcsa.rows === null ? notShownText(reasonWhy) : null,
    rowPageText: mcsa.rows === null ? notShownText(reasonWhy) : pageText(mcsa.row_total, rowOffset, mcsa.rows.length),
    countsText: covered && mcsa.counts !== null ? countsByStatus(mcsa.counts) : notShownText(reasonWhy),
  };
}

function featureView(feature: ReactionUniprotFeature, linkReason: string | null): FeatureView {
  const links = feature.links;
  return {
    type: feature.type, rangeText: feature.start === feature.end ? String(feature.start) : `${feature.start}–${feature.end}`,
    description: feature.description,
    ligandText: feature.ligand_name === null && feature.ligand_id === null ? NULL_TEXT
      : `${feature.ligand_name ?? NULL_TEXT} (${feature.ligand_id ?? NULL_TEXT})`,
    linked: links !== null,
    linkText: links !== null ? `번호 대응으로 구조 잔기에 연결함 (numbering_map)`
      : notShownText(linkReason ? reactionReasonText(linkReason) : "연결하지 않음"),
    links: links === null ? null : links.map((link: ReactionUniprotLink) => ({ position: link.position, status: link.status,
      statusText: `${own(LINK_STATUS_LABEL, link.status) ?? link.status} (${link.status})`,
      residue: residueFields(link.residue), residueText: residueIdentityText(link.residue, "번호 대응에 없음"),
      uniprotResidueText: nullableText(link.uniprot_residue),
      residueMatchText: link.residue_match === null ? NULL_TEXT
        : link.residue_match ? "잔기 이름 같음 (residue_match true)" : "잔기 이름 다름 (residue_match false)" })),
  };
}

function uniprotView(uniprot: ReactionKnowledgeDetailChain["uniprot"], featureOffset: number): UniprotSectionView {
  const why = uniprot.reason === null ? statusText(uniprot.status) : reactionReasonText(uniprot.reason);
  return {
    status: uniprot.status, statusText: statusText(uniprot.status),
    reasonText: uniprot.reason === null ? null : reactionReasonText(uniprot.reason),
    skippedText: uniprot.skipped === null ? null : `가져올 때 건너뜀: ${skipReasonText(uniprot.skipped.reason)}` +
      (uniprot.skipped.target_accessions.length ? ` · 대상 ${uniprot.skipped.target_accessions.join(", ")}` : ""),
    entry: uniprot.entry === null ? null : { accession: uniprot.entry.accession, entryName: uniprot.entry.entry_name,
      proteinName: nullableText(uniprot.entry.protein_name), organism: uniprot.entry.organism,
      sequenceLengthText: `서열 길이 ${uniprot.entry.sequence_length}` },
    linkText: uniprot.status !== "checked" ? notShownText(why)
      : uniprot.linked_via !== null ? "번호 대응으로 구조 잔기에 연결함 (numbering_map)"
        : notShownText(uniprot.link_reason ? reactionReasonText(uniprot.link_reason) : "연결하지 않음"),
    features: uniprot.features === null ? null
      : uniprot.features.map(feature => featureView(feature, uniprot.link_reason)),
    featuresText: uniprot.features === null ? notShownText(why) : uniprot.features.length ? null : "빈 목록 ([])",
    featurePageText: uniprot.features === null ? notShownText(why)
      : pageText(uniprot.feature_total, featureOffset, uniprot.features.length),
  };
}

function reactionsView(reactions: ReactionKnowledgeDetailChain["reactions"],
                       rhea: readonly ReactionRheaReferenceRow[]): ReactionsSectionView {
  const why = reactions.reason === null ? statusText(reactions.status) : reactionReasonText(reactions.reason);
  const equation = (rheaId: string, inSnapshot: boolean) => {
    if (!inSnapshot) return notShownText("스냅샷에 없는 Rhea ID");
    const row = rhea.find(item => item.rhea_id === rheaId);
    return row ? row.equation : notShownText("참조 행 없음");
  };
  return {
    status: reactions.status, statusText: statusText(reactions.status),
    reasonText: reactions.reason === null ? null : reactionReasonText(reactions.reason),
    ecMcsaText: reactions.ecs === null ? notShownText(why) : listText(reactions.ecs.mcsa, "M-CSA가 이 체인을 다루지 않음"),
    ecUniprotText: reactions.ecs === null ? notShownText(why)
      : listText(reactions.ecs.uniprot, "UniProt 절을 검사하지 않음"),
    compounds: reactions.mcsa_compounds === null ? null : reactions.mcsa_compounds.map(item => ({ mcsaId: item.mcsa_id,
      ecText: nullableText(item.ec),
      items: item.compounds.map(compound => ({ type: compound.type, chebiId: compound.chebi_id, name: compound.name })) })),
    compoundsText: reactions.mcsa_compounds === null
      ? notShownText(reactions.ecs === null ? why : "M-CSA가 이 체인을 다루지 않음")
      : reactions.mcsa_compounds.length ? null : "빈 목록 ([])",
    activities: reactions.uniprot_activities === null ? null : reactions.uniprot_activities.map(item => ({
      reactionName: item.reaction_name, ecText: nullableText(item.ec_number),
      rhea: item.rhea.map(link => ({ rheaId: link.rhea_id, inSnapshot: link.in_snapshot,
        inSnapshotText: `${IN_SNAPSHOT_LABEL[link.in_snapshot ? "true" : "false"]} (in_snapshot ${link.in_snapshot})`,
        equationText: equation(link.rhea_id, link.in_snapshot) })) })),
    activitiesText: reactions.uniprot_activities === null
      ? notShownText(reactions.ecs === null ? why : "UniProt 절을 검사하지 않음")
      : reactions.uniprot_activities.length ? null : "빈 목록 ([])",
  };
}

export function chainView(chain: ReactionKnowledgeDetailChain, page: { row_offset: number; feature_offset: number },
                          rhea: readonly ReactionRheaReferenceRow[]): ChainView {
  return {
    chainAuth: chain.chain_auth,
    chainNote: chain.mcsa.coverage === "covered" ? null : REACTION_SCREEN_NOTES.UK4,
    residueCountText: `사슬 잔기 ${chain.polymer_residue_count}개`,
    accessionText: chain.accession === null ? notShownText(reactionReasonText("accession_not_given"))
      : `${chain.accession} (${chain.accession_source === null ? NULL_TEXT
        : own(ACCESSION_SOURCE_LABEL, chain.accession_source) ?? chain.accession_source})`,
    flags: chain.flags.map(flag => `${own(FLAG_LABEL, flag) ?? flag} (${flag})`),
    mcsa: mcsaView(chain.mcsa, page.row_offset),
    uniprot: uniprotView(chain.uniprot, page.feature_offset),
    reactions: reactionsView(chain.reactions, rhea),
  };
}

export interface ReactionResultView {
  structureText: string; pdbIdText: string; numberingMapText: string; setHashShort: string; importedAt: string;
  badge: ReactionSnapshotBadge; badgeText: string | null;
  sources: { label: string; date: string; licenseText: string }[];
  countRows: { key: string; label: string; text: string }[];
  nullResult: boolean; nullResultText: string | null; chainPageText: string; chains: ChainView[];
  /** The stored `limitations` (RK1–RK5), verbatim. */
  limitations: readonly string[];
}

/** Display model of one detail answer. Numbers are the server's stored counts; nothing is recounted or sorted. */
export function reactionResultView(detail: ReactionKnowledgeDetail): ReactionResultView {
  const counts = detail.counts;
  const notChecked = detail.pdb_id === null;
  const mcsaWhy = notChecked ? "PDB ID를 주지 않아 M-CSA를 검사하지 않음" : "M-CSA가 다룬 체인 없음";
  const badge = resultSnapshotBadge(detail.active_set);
  return {
    structureText: `${detail.structure.handle} (${detail.structure.structure_kind}, 모델 ${detail.structure.model_number})`,
    pdbIdText: detail.pdb_id ?? notShownText(reactionReasonText(MCSA_NOT_CHECKED_REASON)),
    numberingMapText: detail.numbering_map === null ? notShownText(reactionReasonText("numbering_map_not_given"))
      : `${detail.numbering_map.handle} (PDB ${detail.numbering_map.pdb_id ?? NULL_TEXT})`,
    setHashShort: detail.snapshot_set.set_hash.slice(0, 12), importedAt: detail.snapshot_set.imported_at,
    badge, badgeText: snapshotBadgeText(badge),
    sources: detail.snapshot_set.sources.map(item => ({ label: own(SOURCE_LABEL, item.source) ?? item.source,
      date: item.date, licenseText: licenseText(item.license) })),
    countRows: [
      { key: "chains", label: "체인", text: `${counts.chains}개` },
      { key: "covered_chains", label: "M-CSA가 다룬 체인",
        text: notChecked ? notShownText(mcsaWhy) : `${counts.covered_chains}개` },
      { key: "mcsa_rows", label: "M-CSA 행",
        text: counts.mcsa_rows === null ? notShownText(mcsaWhy) : countsByStatus(counts.mcsa_rows) },
      { key: "mcsa_entries", label: "M-CSA 항목",
        text: counts.mcsa_entries === null ? notShownText(mcsaWhy) : `${counts.mcsa_entries}개` },
      { key: "uniprot_features", label: "UniProt 부위",
        text: counts.uniprot_features === null ? notShownText("UniProt 절을 검사한 체인 없음")
          : SITE_TYPES.map(type => `${type} ${counts.uniprot_features?.[type]}`).join(" · ") },
      { key: "linked_positions", label: "구조 잔기 연결 위치",
        text: counts.linked_positions === null ? notShownText("번호 대응으로 연결한 부위 없음")
          : LINK_STATUSES.map(status => `${LINK_STATUS_LABEL[status]} ${counts.linked_positions?.[status]}`).join(" · ") },
      { key: "rhea", label: "Rhea ID",
        text: counts.rhea === null ? notShownText("UniProt 촉매 활동이 있는 체인 없음")
          : `${IN_SNAPSHOT_LABEL.true} ${counts.rhea.in_snapshot} · ${IN_SNAPSHOT_LABEL.false} ${counts.rhea.not_in_snapshot}` },
    ],
    nullResult: detail.null_result, nullResultText: detail.null_result ? NULL_RESULT_TEXT : null,
    chainPageText: pageText(detail.page.chain_total, detail.page.chain_offset, detail.chains.length),
    chains: detail.chains.map(chain => chainView(chain, detail.page, detail.reference_rows.rhea)),
    limitations: detail.limitations,
  };
}

// ---- area state (five states) ----

export type ReactionPanelState =
  | { state: "loading" } | { state: "ready" } | { state: "scientific_null"; message: string }
  | { state: "failed"; message: string } | { state: "unavailable"; reason: string };

/**
 * Five states. `capability` undefined = not read yet, null = absent (the area shows the reason only). A missing or
 * invalid snapshot is NOT the area's "unavailable": stored results still open from events alone; the snapshot block
 * shows its reason and the request block is closed (`requestUnavailableReason`). An empty result is not a failure.
 */
export function reactionPanelState(input: { runId: string | null;
  capability?: { available: boolean; reason: string | null } | null; loading?: boolean; error?: string | null;
  detail?: { null_result: boolean } | null }): ReactionPanelState {
  if (input.runId === null) return { state: "unavailable", reason: NO_RUN_REASON };
  if (input.capability === null) return { state: "unavailable", reason: CAPABILITY_REASON };
  if (input.error) return { state: "failed", message: input.error };
  if (input.loading || input.capability === undefined) return { state: "loading" };
  if (input.detail?.null_result) return { state: "scientific_null", message: NULL_RESULT_TEXT };
  return { state: "ready" };
}

// ---- late responses (run + result handle + request number per area) ----

export const REACTION_AREAS = ["status", "structures", "residues", "hint", "maps", "pdb", "command", "list", "detail",
  "report"] as const;
export interface ReactionStamp { runId: string | null; handle: string | null; seq: number }

/** Applied only when run, result handle and request number are all still current. */
export function reactionResponseCurrent(captured: ReactionStamp, live: ReactionStamp): boolean {
  return captured.runId !== null && captured.runId === live.runId && captured.handle === live.handle &&
    captured.seq === live.seq;
}

/** A created report was saved: announce it while the run is unchanged, even when the late inline display is dropped. */
export function reactionReportSavedForRun(captured: ReactionStamp, liveRunId: string | null): boolean {
  return captured.runId !== null && captured.runId === liveRunId;
}

/** The report belongs to the opened result. */
export function reactionReportMatches(artifact: { manifest: { schema?: unknown; analysis_type?: unknown;
  result_handle?: unknown } }, resultHandle: string): boolean {
  return artifact.manifest.schema === "method_report_manifest@1" &&
    artifact.manifest.analysis_type === REACTION_REPORT_TYPE && artifact.manifest.result_handle === resultHandle;
}

// ---- wording check (reference values are never interpreted; nothing is called important, active or ranked) ----

/** Lines exempt from the check: exactly a fixed sentence RK1–RK6 or screen note UK1–UK4 (RK2 and RK5 say "활성"). */
export const REACTION_FIXED_LINES: readonly string[] = [...Object.values(REACTION_STATEMENTS),
  ...Object.values(REACTION_SCREEN_NOTES)];
/**
 * Quoted reference terms removed before the check: the UniProt site type names, shown verbatim ("Active site" and
 * "Binding site" would otherwise match `active` / `binding`). Reference strings of a result (role text, enzyme names,
 * descriptions, equations) are server values, never this module's wording, and are not checked here.
 */
export const REACTION_EXEMPT_TERMS: readonly string[] = SITE_TYPES;
/**
 * The interpretive wording of the M26 report check (M15 + M20 lists and `필수`·`핵심`·`중요`·"메커니즘이 유지", with
 * their English counterparts) plus `최고`·`우수`·winner·highest·stability. "촉매" is not forbidden.
 */
export const REACTION_FORBIDDEN = new RegExp([
  "important", "critical", "essential", "key residue", "binding", "binds", "affinity", "stabili[sz]", "druggab",
  "inhibit", "selectiv", "potency", "functional", "중요", "결합", "친화", "안정화", "억제", "선택성", "핵심", "기능",
  "안정성", "ΔΔG", "ddG", "delta\\s*delta", "순위", "추천", "최적", "개선", "활성", "예측", "유망", "좋은", "나쁜", "안전",
  "점수", "에너지", "수소\\s*결합", "\\brank", "\\bbest\\b", "recommend", "optimal", "improv", "predict", "promising",
  "\\bgood\\b", "\\bsafe", "\\bactiv(?:e|ity)\\b", "\\bscor(?:e|ing)\\b", "energ", "hydrogen[\\s_-]?bond", "\\bh-?bond",
  "필수", "메커니즘이\\s*유지", "mechanism\\W+(?:is\\W+)?(?:preserved|maintained|retained|conserved)",
  "최고", "우수", "\\bwinner", "highest", "stabilit",
].join("|"), "gi");

/** Forbidden words in screen text, line by line; fixed lines are exempt, quoted reference terms are removed first. */
export function reactionForbiddenWords(text: string): string[] {
  const found: string[] = [];
  for (const line of text.split("\n")) {
    if (REACTION_FIXED_LINES.includes(line)) continue;
    let checked = line;
    for (const term of REACTION_EXEMPT_TERMS) checked = checked.split(term).join(" ");
    for (const match of checked.matchAll(REACTION_FORBIDDEN)) found.push(match[0]);
  }
  return found;
}
