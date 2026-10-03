/**
 * Pure logic of the M20 "변이 후보" panel in the 단백질 공학 tab (M20 spec sections 2, 6, 8, 10 and 11).
 *
 * Every number shown comes from the stored `mutation_candidate_set@1` object through the read API; this module never
 * measures, counts, ranks or recomputes a scientific value. It builds and checks the request draft (mirroring the
 * server admission rules so the screen can say why a request is blocked; the server checks everything again), picks
 * the same-structure pocket sets / numbering maps / annotations, pre-selects the newest same-structure annotation with
 * its own numbering map, decides the five panel states, builds read queries, keeps late responses out, and gives
 * display text that keeps "not given", "not checked" and "not available" apart from 0. The list order is the
 * structure's file order (or the distance sort the person picked), never a ranking.
 */
import type { ExactResidueRef, MutationCandidateSet, MutationCandidateSetListRow, MutationCounts,
  MutationExclusionReason, MutationNumbering, MutationPosition, MutationPositionSort, MutationPositionSource,
  MutationPositionStatus, MutationProtectionChecks, MutationProtectionReason, MutationReportArtifact,
  MutationRequestArgs, MutationSourceKind, RunEvent, SiteAnnotationListRow } from "./contracts";
import type { NumberingMapListRow } from "./numbering";
import type { PocketSetRow } from "./pockets";
import { resultEvents } from "./event-model";
import { decimalHalfUp } from "./site-annotation";

// ---- closed sets, limits and defaults (backend/mw/mutation_constants.py; change both sides together) ----

export const MUTATION_TOOL = "generate_mutation_candidates";
export const MUTATION_REPORT_TYPE = "mutation_candidates";
export const ONE_LETTER_ORDER = "ACDEFGHIKLMNPQRSTVWY";
export const ONE_LETTER_RESNAME: Record<string, string> = {
  A: "ALA", C: "CYS", D: "ASP", E: "GLU", F: "PHE", G: "GLY", H: "HIS", I: "ILE", K: "LYS", L: "LEU", M: "MET",
  N: "ASN", P: "PRO", Q: "GLN", R: "ARG", S: "SER", T: "THR", V: "VAL", W: "TRP", Y: "TYR" };
export const MAX_POSITIONS = 400;
export const MAX_LIST = 400;
export const LIGAND_SHELL_RADIUS_DEFAULT_A = 5.0;
export const LIGAND_SHELL_RADIUS_RANGE_A: readonly [number, number] = [1.0, 12.0];
export const METAL_CONTACT_DEFAULT_A = 3.0;
export const METAL_CONTACT_RANGE_A: readonly [number, number] = [1.0, 5.0];
export const DISULFIDE_SG_A = 2.5;
export const SOURCE_KINDS: readonly MutationSourceKind[] = ["pocket", "ligand_shell", "user"];
export const PROTECTION_REASONS: readonly MutationProtectionReason[] = ["user_protected", "klifs_key_site",
  "metal_contact", "disulfide_cys"];
export const EXCLUSION_REASONS: readonly MutationExclusionReason[] = ["non_standard_residue", "user_protected",
  "klifs_key_site", "metal_contact", "disulfide_cys", "no_allowed_alternative"];
export const POSITION_STATUSES: readonly MutationPositionStatus[] = ["candidate", "excluded"];
export const POSITION_SORTS: readonly MutationPositionSort[] = ["order", "ligand_distance"];
export const PROTECTION_CHECK_KEYS: readonly (keyof MutationProtectionChecks)[] = ["user_list", "klifs_key_sites",
  "metal_contact", "disulfide", "catalytic_residue_database"];
export const ADMISSION_REASON_CODES = [
  "unknown_field", "structure_invalid", "no_position_source", "argument_invalid", "allowed_residues_invalid",
  "residue_invalid", "duplicate_residue", "protect_release_conflict", "ligand_required", "ligand_invalid",
  "pocket_set_invalid", "structure_mismatch", "pocket_rank_invalid", "pocket_residue_mismatch",
  "numbering_map_invalid", "annotation_invalid", "annotation_map_mismatch",
] as const;
export const TOO_MANY_POSITIONS = "too_many_positions";
/** Read page limits (backend/mw/mutation_reads.py). */
export const LIST_LIMIT_MAX = 100;
export const POSITION_LIMIT_DEFAULT = 50;
export const POSITION_LIMIT_MAX = 100;
export const CANDIDATE_LIMIT_DEFAULT = 100;
export const CANDIDATE_LIMIT_MAX = 200;
const IDENTITY_FIELDS = ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"] as const;

/** Fixed limitation sentences (spec 11), verbatim and in order; the result, the report and the screen show the same. */
export const MUTATION_LIMITATIONS: readonly string[] = [
  "후보는 위치와 바꿀 잔기의 조합 목록이며 구조 모델링·에너지·점수를 계산하지 않았다.",
  "이 목록은 변이의 효과(안정성·결합·활성)를 뜻하지 않으며 순위나 추천이 아니다.",
  "보호 잔기는 사용자 지정·KLIFS 주요 부위·금속 근접·이황화 결합 기준으로만 판정했고 촉매 잔기 데이터베이스는 사용하지 않았다(없음).",
  "거리는 준비된 구조의 저장 좌표에서 계산한 중원자 사이 최소 거리(Å)이며 결합이나 상호작용을 뜻하지 않는다.",
  "바꿀 히스티딘의 양성자 상태와 변이 구조의 형태는 정하지 않았다.",
];

// ---- fixed screen text ----

export const PANEL_TITLE = "변이 후보";
export const MODELING_NOTE = "변이 구조 모델링은 아직 구현하지 않았습니다. 이 화면은 위치와 바꿀 잔기의 조합 목록만 보여 줍니다.";
export const NO_RUN_REASON = "run이 없습니다. 구조 분석 탭에서 run을 먼저 고르세요.";
export const NO_PREPARED_REASON = "이 run에 전처리 구조가 없습니다. 구조 분석 탭에서 구조를 먼저 전처리하세요.";
export const CAPABILITY_REASON = "변이 후보 기능을 사용할 수 없습니다.";
export const KLIFS_NOT_CHECKED_NOTICE = "KLIFS 주요 부위 보호를 검사하지 않음: 같은 구조의 참조 주석을 고르지 않았습니다. 이 요청에서는 KLIFS 주요 부위가 제외 목록에 들어가지 않습니다.";
export const MAP_CONFLICT_TEXT = "고른 번호 대응이 고른 참조 주석이 기록한 번호 대응과 다릅니다. 주석의 번호 대응을 고르거나 번호 대응을 비우세요.";
export const CATALYTIC_NOTE = "촉매 잔기 데이터베이스는 사용할 수 없음(구현하지 않음). 촉매 잔기는 판정하지 않았습니다.";
export const LIST_ORDER_NOTE = "표의 순서는 구조 파일 순서(또는 고른 거리 정렬)일 뿐 위치·후보의 우열을 뜻하지 않습니다.";
export const NULL_TEXT = "—";

export const SOURCE_LABEL: Record<MutationSourceKind, string> = {
  pocket: "포켓 검출", ligand_shell: "리간드 껍질", user: "직접 선택" };
export const EXCLUSION_REASON_LABEL: Record<MutationExclusionReason, string> = {
  non_standard_residue: "표준 잔기가 아님",
  user_protected: "사용자 보호",
  klifs_key_site: "KLIFS 주요 부위",
  metal_contact: "금속 근접",
  disulfide_cys: "이황화 Cys",
  no_allowed_alternative: "허용 목록에 바꿀 잔기 없음",
};
export const POSITION_STATUS_LABEL: Record<MutationPositionStatus, string> = { candidate: "후보 위치", excluded: "제외" };
export const POSITION_SORT_LABEL: Record<MutationPositionSort, string> = {
  order: "구조 파일 순서",
  ligand_distance: "리간드까지 최소 거리 오름차순(값 없는 위치는 끝)",
};
export const PROTECTION_CHECK_LABEL: Record<keyof MutationProtectionChecks, string> = {
  user_list: "사용자 보호·해제 목록",
  klifs_key_sites: "KLIFS 주요 부위",
  metal_contact: "금속 근접",
  disulfide: "이황화 Cys",
  catalytic_residue_database: "촉매 잔기 데이터베이스",
};
export const CHECK_STATUS_LABEL: Record<string, string> = {
  checked: "검사함", not_checked: "검사하지 않음", not_available: "사용할 수 없음" };
export const RELEASE_EFFECT_LABEL: Record<"released" | "none", string> = {
  released: "보호 해제됨", none: "보호 사유가 없어 영향 없음" };
export const NUMBERING_STATUS_LABEL: Record<MutationNumbering["status"], string> = {
  mapped: "대응됨", unmapped: "대응 없음", conflict: "충돌", not_in_map: "지도에 없음" };

/** Korean names of every reason / status code the panel can show (admission, read and check reasons). */
export const MUTATION_REASON_LABEL: Record<string, string> = {
  unknown_field: "알 수 없는 요청 항목",
  structure_invalid: "이 run의 전처리 구조가 아님",
  no_position_source: "위치 출처가 하나도 없음",
  argument_invalid: "요청 값의 형식·범위 오류",
  allowed_residues_invalid: "허용 잔기 목록 오류",
  residue_invalid: "구조의 단백질 잔기 하나로 정해지지 않는 잔기",
  duplicate_residue: "한 목록 안에 같은 잔기가 두 번",
  protect_release_conflict: "같은 잔기가 보호 목록과 해제 목록에 모두 있음",
  ligand_required: "리간드 껍질에는 리간드 선택이 필요함",
  ligand_invalid: "리간드 하나로 정해지지 않는 선택",
  pocket_set_invalid: "이 run의 게시된 포켓 결과가 아니거나 포켓 없음 결과",
  structure_mismatch: "다른 구조의 결과",
  pocket_rank_invalid: "포켓 결과에 없는 포켓 번호",
  pocket_residue_mismatch: "포켓 안쪽 잔기가 구조 잔기와 맞지 않음",
  numbering_map_invalid: "이 run의 번호 대응이 아님",
  annotation_invalid: "이 run의 참조 주석이 아님",
  annotation_map_mismatch: "주석이 다른 번호 대응으로 만들어짐",
  too_many_positions: "위치 수 상한 초과",
  annotation_not_given: "참조 주석을 고르지 않음",
  not_implemented: "구현하지 않음",
  method_evidence_invalid: "저장된 결과가 검증되지 않음",
  input_invalid: "요청 오류",
  resource_exceeded: "상한 초과",
  ...EXCLUSION_REASON_LABEL,
};

const own = (table: Record<string, string>, code: string) =>
  Object.prototype.hasOwnProperty.call(table, code) ? table[code] : undefined;

/** "한국어 (code)"; unknown codes are shown as is. */
export function mutationReasonText(code: string): string {
  const label = own(MUTATION_REASON_LABEL, code);
  return label ? `${label} (${code})` : code;
}

// ---- residues (identity = the 7 fields, null kept; never rebuilt from a display string) ----

export function exactResidue(ref: ExactResidueRef): ExactResidueRef {
  return { model_number: ref.model_number, chain_auth: ref.chain_auth, chain_label: ref.chain_label,
    seq_auth: ref.seq_auth, seq_label: ref.seq_label, icode: ref.icode, resname: ref.resname };
}

export function residueKey(ref: ExactResidueRef): string {
  return JSON.stringify(IDENTITY_FIELDS.map(field => ref[field] ?? null));
}

/** "ILE A:10A" (auth numbering) — display only. */
export function residueText(ref: ExactResidueRef): string {
  return `${ref.resname} ${ref.chain_auth}:${ref.seq_auth}${ref.icode}`;
}

/** Label numbering of a residue; null labels are shown as "—", never as 0 or as the auth value. */
export function residueLabelText(ref: ExactResidueRef): string {
  return `label ${ref.chain_label ?? NULL_TEXT}:${ref.seq_label ?? NULL_TEXT}`;
}

interface ResidueListLike { model_number: number;
  residues: (Omit<ExactResidueRef, "model_number"> & { model_number?: number; category: string })[];
  ligands: (Omit<ExactResidueRef, "model_number"> & { model_number?: number })[] }

/** Protein residues (`category` polymer) of the listed first model, in file order, as exact 7-field references. */
export function proteinResidueOptions(list: ResidueListLike): ExactResidueRef[] {
  return list.residues.filter(item => item.category === "polymer" && (item.model_number ?? list.model_number) === list.model_number)
    .map(item => exactResidue({ ...item, model_number: item.model_number ?? list.model_number }));
}

/** Ligand residues as listed by the server (non-polymer, non-water, non-metal); never auto-selected. */
export function ligandOptions(list: ResidueListLike): ExactResidueRef[] {
  return list.ligands.map(item => exactResidue({ ...item, model_number: item.model_number ?? list.model_number }));
}

/** Distinct `chain_auth` values of the protein residues, in file order (position filter choices). */
export function chainOptions(residues: readonly ExactResidueRef[]): string[] {
  return [...new Set(residues.map(item => item.chain_auth))];
}

/** Toggle one residue in a list by its 7-field identity (order of the list is kept; the server re-sorts). */
export function toggleResidue(list: readonly ExactResidueRef[], ref: ExactResidueRef): ExactResidueRef[] {
  const key = residueKey(ref);
  return list.some(item => residueKey(item) === key) ? list.filter(item => residueKey(item) !== key)
    : [...list, exactResidue(ref)];
}

// ---- same structure only ----

/** Prepared structures of the run (from result events), oldest first, once per handle. */
export function preparedStructures(events: RunEvent[]): { handle: string; seq: number }[] {
  const seen = new Set<string>();
  const rows: { handle: string; seq: number }[] = [];
  for (const event of resultEvents(events)) {
    if (event.tool !== "prepare_structure" || event.output.kind !== "prepared_structure" || seen.has(event.output.handle))
      continue;
    seen.add(event.output.handle);
    rows.push({ handle: event.output.handle, seq: event.seq });
  }
  return rows;
}

/** Published pocket sets detected on this structure that have pockets (a null result is refused by the server). */
export function pocketSetsForStructure(rows: readonly PocketSetRow[], structure: string | null): PocketSetRow[] {
  return structure === null ? [] : rows.filter(row => row.source_handle === structure && row.null_result === false);
}

export function mapsForStructure(rows: readonly NumberingMapListRow[], structure: string | null): NumberingMapListRow[] {
  return structure === null ? [] : rows.filter(row => row.structure === structure);
}

export function annotationsForStructure(rows: readonly SiteAnnotationListRow[], structure: string | null): SiteAnnotationListRow[] {
  return structure === null ? [] : rows.filter(row => row.structure === structure);
}

/**
 * Pre-selection when a structure is chosen: the newest same-structure annotation (highest `created_seq`) with the
 * numbering map that annotation recorded (only when that map is among the same-structure maps). None → both null.
 */
export function preselectAnnotation(annotations: readonly SiteAnnotationListRow[], maps: readonly NumberingMapListRow[],
                                    structure: string | null): { annotation: string | null; numbering_map: string | null } {
  const offered = annotationsForStructure(annotations, structure);
  if (!offered.length) return { annotation: null, numbering_map: null };
  const newest = offered.reduce((best, row) => row.created_seq > best.created_seq ? row : best);
  const mapOffered = mapsForStructure(maps, structure).some(row => row.handle === newest.numbering_map);
  return { annotation: newest.handle, numbering_map: mapOffered ? newest.numbering_map : null };
}

/** Conflict text when both are chosen and the annotation was made from another map (the request is blocked). */
export function annotationMapConflict(annotation: string | null, numberingMap: string | null,
                                      annotations: readonly SiteAnnotationListRow[]): string | null {
  if (annotation === null || numberingMap === null) return null;
  const row = annotations.find(item => item.handle === annotation);
  return row && row.numbering_map !== numberingMap ? MAP_CONFLICT_TEXT : null;
}

/** Shown prominently in the request area while no annotation is chosen. */
export function klifsNotice(annotation: string | null): string | null {
  return annotation === null ? KLIFS_NOT_CHECKED_NOTICE : null;
}

// ---- request draft ----

export interface MutationDraft {
  structure: string | null;
  pocketOn: boolean; pocketSet: string | null; pocketRanks: number[];
  ligandShellOn: boolean; radiusText: string;
  userOn: boolean; residues: ExactResidueRef[];
  ligand: ExactResidueRef | null;
  /** Checked one-letter codes (any order; sent in ONE_LETTER_ORDER). */
  allowed: string[];
  protectedResidues: ExactResidueRef[];
  releasedResidues: ExactResidueRef[];
  metalText: string;
  numberingMap: string | null;
  annotation: string | null;
}

/** Defaults: no source on, radius 5, metal 3, all 20 residues allowed, nothing protected or released. */
export function initialMutationDraft(structure: string | null = null): MutationDraft {
  return { structure, pocketOn: false, pocketSet: null, pocketRanks: [], ligandShellOn: false,
    radiusText: String(LIGAND_SHELL_RADIUS_DEFAULT_A), userOn: false, residues: [], ligand: null,
    allowed: [...ONE_LETTER_ORDER], protectedResidues: [], releasedResidues: [],
    metalText: String(METAL_CONTACT_DEFAULT_A), numberingMap: null, annotation: null };
}

/** A new structure clears everything tied to the old one and pre-selects that structure's newest annotation. */
export function draftForStructure(draft: MutationDraft, structure: string | null,
                                  annotations: readonly SiteAnnotationListRow[], maps: readonly NumberingMapListRow[]): MutationDraft {
  const picked = preselectAnnotation(annotations, maps, structure);
  return { ...draft, structure, pocketSet: null, pocketRanks: [], residues: [], ligand: null, protectedResidues: [],
    releasedResidues: [], annotation: picked.annotation, numberingMap: picked.numbering_map };
}

/** Number typed by the person: plain decimal only (no exponent, sign, hex, Infinity or NaN). */
export function parseDistance(text: string): number | null {
  const trimmed = text.trim();
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

function rangeError(text: string, range: readonly [number, number], name: string): string | null {
  const value = parseDistance(text);
  return value === null || value < range[0] || value > range[1]
    ? `${name}는 ${range[0].toFixed(1)}–${range[1].toFixed(1)} Å 사이의 숫자여야 합니다(양끝 포함).` : null;
}

/** Allowed codes in ONE_LETTER_ORDER, or the reason they cannot be sent (empty, outside the 20, duplicated). */
export function allowedResiduesString(codes: readonly string[]): { ok: true; value: string } | { ok: false; error: string } {
  if (!codes.length) return { ok: false, error: "허용 잔기를 하나 이상 고르세요." };
  if (codes.some(code => code.length !== 1 || !ONE_LETTER_ORDER.includes(code)))
    return { ok: false, error: "허용 잔기는 표준 20종 한 글자 코드만 쓸 수 있습니다." };
  if (new Set(codes).size !== codes.length) return { ok: false, error: "허용 잔기에 같은 코드가 두 번 있습니다." };
  return { ok: true, value: [...ONE_LETTER_ORDER].filter(code => codes.includes(code)).join("") };
}

/** Residues present in both the protected and the released list (by 7-field identity). */
export function protectReleaseConflicts(protectedResidues: readonly ExactResidueRef[],
                                        releasedResidues: readonly ExactResidueRef[]): ExactResidueRef[] {
  const released = new Set(releasedResidues.map(residueKey));
  return protectedResidues.filter(item => released.has(residueKey(item)));
}

function listErrors(list: readonly ExactResidueRef[], name: string): string[] {
  const errors: string[] = [];
  if (list.length > MAX_LIST) errors.push(`${name}: 최대 ${MAX_LIST}개까지 보낼 수 있습니다.`);
  if (new Set(list.map(residueKey)).size !== list.length) errors.push(`${name}에 같은 잔기가 두 번 있습니다.`);
  return errors;
}

export interface DraftOptions { pocketSets: readonly PocketSetRow[]; maps: readonly NumberingMapListRow[];
  annotations: readonly SiteAnnotationListRow[]; ligands: readonly ExactResidueRef[] }
export type MutationArgsCheck = { ok: true; args: MutationRequestArgs } | { ok: false; errors: string[] };

/**
 * Tool arguments of "후보 만들기", or every reason the request is blocked. Mirrors the server admission order where
 * the screen can know it; the server re-validates everything (identity resolution, pocket ranks, structure match).
 */
export function mutationRequestArgs(draft: MutationDraft, options: DraftOptions): MutationArgsCheck {
  const errors: string[] = [];
  const structure = draft.structure;
  if (structure === null) errors.push("전처리 구조를 고르세요.");
  const pocketOn = draft.pocketOn, shellOn = draft.ligandShellOn, userOn = draft.userOn && draft.residues.length > 0;
  if (!pocketOn && !shellOn && !userOn)
    errors.push("위치 출처(포켓 검출·리간드 껍질·직접 선택)를 하나 이상 켜고 위치를 정하세요.");
  if (pocketOn) {
    if (draft.pocketSet === null) errors.push("포켓 결과를 고르세요.");
    else if (!pocketSetsForStructure(options.pocketSets, structure).some(row => row.handle === draft.pocketSet))
      errors.push("고른 포켓 결과가 이 구조의 포켓 있는 결과가 아닙니다.");
    if (!draft.pocketRanks.length) errors.push("포켓 번호를 하나 이상 고르세요.");
    else if (draft.pocketRanks.some(rank => !Number.isInteger(rank) || rank < 1) ||
             new Set(draft.pocketRanks).size !== draft.pocketRanks.length) errors.push("포켓 번호가 올바르지 않습니다.");
  }
  if (shellOn) {
    const error = rangeError(draft.radiusText, LIGAND_SHELL_RADIUS_RANGE_A, "리간드 껍질 반경");
    if (error) errors.push(error);
  }
  const metalError = rangeError(draft.metalText, METAL_CONTACT_RANGE_A, "금속 근접 거리");
  if (metalError) errors.push(metalError);
  const allowed = allowedResiduesString(draft.allowed);
  if (!allowed.ok) errors.push(allowed.error);
  if (draft.userOn) errors.push(...listErrors(draft.residues, "직접 고른 위치"));
  errors.push(...listErrors(draft.protectedResidues, "보호 목록"), ...listErrors(draft.releasedResidues, "해제 목록"));
  const conflicts = protectReleaseConflicts(draft.protectedResidues, draft.releasedResidues);
  if (conflicts.length)
    errors.push(`같은 잔기를 보호와 해제에 모두 넣을 수 없습니다: ${conflicts.map(residueText).join(", ")}`);
  if (shellOn && draft.ligand === null) errors.push("리간드 껍질을 쓰려면 리간드를 고르세요.");
  if (draft.ligand !== null && !options.ligands.some(item => residueKey(item) === residueKey(draft.ligand as ExactResidueRef)))
    errors.push("고른 리간드가 이 구조의 리간드 목록에 없습니다.");
  if (draft.numberingMap !== null && !mapsForStructure(options.maps, structure).some(row => row.handle === draft.numberingMap))
    errors.push("고른 번호 대응이 이 구조의 것이 아닙니다.");
  if (draft.annotation !== null && !annotationsForStructure(options.annotations, structure).some(row => row.handle === draft.annotation))
    errors.push("고른 참조 주석이 이 구조의 것이 아닙니다.");
  const conflict = annotationMapConflict(draft.annotation, draft.numberingMap, options.annotations);
  if (conflict) errors.push(conflict);
  if (errors.length || structure === null || !allowed.ok) return { ok: false, errors };
  return { ok: true, args: {
    structure,
    sources: {
      pocket: pocketOn && draft.pocketSet !== null
        ? { pocket_set: draft.pocketSet, ranks: [...draft.pocketRanks].sort((a, b) => a - b) } : null,
      ligand_shell: shellOn ? { radius_A: parseDistance(draft.radiusText) as number } : null,
      residues: draft.userOn ? draft.residues.map(exactResidue) : [],
    },
    ligand: draft.ligand === null ? null : exactResidue(draft.ligand),
    allowed_residues: allowed.value,
    protected_residues: draft.protectedResidues.map(exactResidue),
    released_residues: draft.releasedResidues.map(exactResidue),
    metal_contact_A: parseDistance(draft.metalText) as number,
    numbering_map: draft.numberingMap,
    annotation: draft.annotation,
  } };
}

/** Server refusal text: "한국어 (reason_code)" plus the server message; too many positions names the stored limit. */
export function mutationErrorText(error: unknown): string {
  if (typeof error !== "object" || error === null) return String(error);
  const { message, code, detail } = error as { message?: unknown; code?: unknown; detail?: Record<string, unknown> };
  const reason = typeof detail?.reason_code === "string" ? detail.reason_code : null;
  if (reason === TOO_MANY_POSITIONS && typeof detail?.positions === "number" && typeof detail?.limit === "number")
    return `${mutationReasonText(reason)}: 위치 ${detail.positions}개가 상한 ${detail.limit}개를 넘어 저장하지 않았습니다. ` +
      "출처를 줄여 다시 요청하세요.";
  const head = reason ? mutationReasonText(reason) : typeof code === "string" ? mutationReasonText(code) : "요청 실패";
  return typeof message === "string" && message ? `${head}: ${message}` : head;
}

// ---- panel state ----

export type MutationPanelState =
  | { state: "loading" } | { state: "ready" } | { state: "scientific_null"; message: string }
  | { state: "failed"; message: string } | { state: "unavailable"; reason: string };

/**
 * Five panel states. `structures` undefined = not read yet. `capability` undefined = not read yet, null = absent.
 * `detail` is the opened stored set (if any); zero candidates is an empty scientific result, never a failure.
 */
export function mutationPanelState(input: { runId: string | null;
  capability?: { available: boolean; reason: string | null } | null; structures?: readonly unknown[];
  loading?: boolean; error?: string | null;
  detail?: { null_result: boolean; counts: MutationCounts } | null }): MutationPanelState {
  if (input.runId === null) return { state: "unavailable", reason: NO_RUN_REASON };
  if (input.capability === null || input.capability?.available === false)
    return { state: "unavailable", reason: input.capability?.reason ?? CAPABILITY_REASON };
  if (input.error) return { state: "failed", message: input.error };
  if (input.loading || input.capability === undefined || input.structures === undefined) return { state: "loading" };
  if (!input.structures.length) return { state: "unavailable", reason: NO_PREPARED_REASON };
  const detail = input.detail;
  if (detail) {
    if (detail.null_result !== (detail.counts.candidates === 0))
      return { state: "failed", message: "저장된 결과의 null_result가 후보 수와 맞지 않습니다." };
    if (detail.null_result) return { state: "scientific_null", message: nullResultText(detail.counts) };
  }
  return { state: "ready" };
}

/** Empty result text with the stored exclusion reason counts (nothing counted here). */
export function nullResultText(counts: MutationCounts): string {
  const reasons = EXCLUSION_REASONS.filter(reason => counts.exclusion_reason_counts[reason] > 0)
    .map(reason => `${EXCLUSION_REASON_LABEL[reason]} ${counts.exclusion_reason_counts[reason]}개`);
  return `후보 0개(빈 결과, scientific_null): 위치 ${counts.positions}개 중 제외 ${counts.excluded_positions}개. ` +
    (reasons.length ? `제외 사유별 위치 수: ${reasons.join(", ")}.` : "제외 사유가 있는 위치 없음.");
}

// ---- reads: filters, sort, pages ----

export interface PositionFilters { status: MutationPositionStatus | ""; source: MutationSourceKind | "";
  exclusion_reason: MutationExclusionReason | ""; chain_auth: string }
export const EMPTY_POSITION_FILTERS: PositionFilters = { status: "", source: "", exclusion_reason: "", chain_auth: "" };

/** Query of the position page; empty filters are not sent. */
export function positionQuery(filters: PositionFilters, sort: MutationPositionSort, offset: number,
                              limit = POSITION_LIMIT_DEFAULT): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.source) params.set("source", filters.source);
  if (filters.exclusion_reason) params.set("exclusion_reason", filters.exclusion_reason);
  if (filters.chain_auth) params.set("chain_auth", filters.chain_auth);
  params.set("sort", sort);
  params.set("offset", String(offset));
  params.set("limit", String(limit));
  return params.toString();
}

export interface CandidateFilters { position_index: number | null; to: string }
export const EMPTY_CANDIDATE_FILTERS: CandidateFilters = { position_index: null, to: "" };

export function candidateQuery(filters: CandidateFilters, offset: number, limit = CANDIDATE_LIMIT_DEFAULT): string {
  const params = new URLSearchParams();
  if (filters.position_index !== null) params.set("position_index", String(filters.position_index));
  if (filters.to) params.set("to", filters.to);
  params.set("offset", String(offset));
  params.set("limit", String(limit));
  return params.toString();
}

/** "전체 N개 중 a–b번째" of a server page (`total` after the filter). */
export function pageRangeText(page: { total: number; offset: number; rows: readonly unknown[] }): string {
  if (!page.total || !page.rows.length) return `전체 ${page.total}개 · 이 페이지에 행 없음`;
  return `전체 ${page.total}개 중 ${page.offset + 1}–${page.offset + page.rows.length}번째`;
}

export function previousOffset(offset: number, limit: number): number | null {
  return offset > 0 ? Math.max(0, offset - limit) : null;
}

export function nextOffset(page: { total: number; offset: number; limit: number }): number | null {
  return page.offset + page.limit < page.total ? page.offset + page.limit : null;
}

// ---- late responses (run + result handle + request number) ----

export interface MutationStamp { runId: string | null; handle: string | null; seq: number }

/** Applied only when run, result handle and request number are all still current. */
export function mutationResponseCurrent(captured: MutationStamp, live: MutationStamp): boolean {
  return captured.runId !== null && captured.runId === live.runId && captured.handle === live.handle &&
    captured.seq === live.seq;
}

/** A created report was saved: announce it while the run is unchanged, even when the late inline display is dropped. */
export function mutationReportSavedForRun(captured: MutationStamp, liveRunId: string | null): boolean {
  return captured.runId !== null && captured.runId === liveRunId;
}

// ---- display (values as stored; null is "—" with a reason, never 0) ----

export function nullableText(value: string | number | null | undefined): string {
  return value === null || value === undefined ? NULL_TEXT : String(value);
}

/** Stored distance with two decimals (ROUND_HALF_UP on the decimal string). */
export function distanceText(value: number | null): string {
  return value === null ? NULL_TEXT : `${decimalHalfUp(value, 2)} Å`;
}

/** Ligand distance cell: a value, or "—" with why there is none. */
export function ligandDistanceText(value: number | null, ligandGiven: boolean): string {
  if (value !== null) return distanceText(value);
  return ligandGiven ? `${NULL_TEXT} (중원자 없음)` : `${NULL_TEXT} (리간드를 고르지 않아 계산하지 않음)`;
}

export function sourceText(source: MutationPositionSource): string {
  if (source.kind === "pocket") return `${SOURCE_LABEL.pocket} #${source.pocket_rank}`;
  if (source.kind === "ligand_shell") return `${SOURCE_LABEL.ligand_shell} ${source.radius_A} Å`;
  return SOURCE_LABEL.user;
}

export function sourcesText(sources: readonly MutationPositionSource[]): string {
  return sources.map(sourceText).join(", ");
}

/** Sources a stored set used ("포켓 검출 · 직접 선택"); an invalid list row has none. */
export function sourcesUsedText(used: Record<MutationSourceKind, boolean> | null): string {
  if (!used) return NULL_TEXT;
  const names = SOURCE_KINDS.filter(kind => used[kind]).map(kind => SOURCE_LABEL[kind]);
  return names.length ? names.join(" · ") : NULL_TEXT;
}

export function numberingText(numbering: MutationNumbering | null): string {
  if (numbering === null) return `${NULL_TEXT} (번호 대응을 고르지 않음)`;
  if (numbering.status === "not_in_map") return `${NULL_TEXT} (${NUMBERING_STATUS_LABEL.not_in_map})`;
  const uniprot = numbering.uniprot_accession === null ? NULL_TEXT
    : `${numbering.uniprot_accession} ${numbering.uniprot_residue ?? NULL_TEXT}${numbering.uniprot_position ?? NULL_TEXT}`;
  return `${NUMBERING_STATUS_LABEL[numbering.status]} · UniProt ${uniprot} · KLIFS ${numbering.klifs_label ?? NULL_TEXT}`;
}

export function klifsSitesText(sites: readonly string[] | null): string {
  if (sites === null) return `${NULL_TEXT} (검사하지 않음)`;
  return sites.length ? sites.join(", ") : "해당 부위 없음";
}

export function metalText(metal: MutationPosition["protection"]["metal"]): string {
  return metal === null ? "기준 거리 안 금속 없음"
    : `${residueText(metal.metal_residue)} ${distanceText(metal.min_distance_A)}`;
}

export function disulfideText(partner: ExactResidueRef | null): string {
  return partner === null ? "기준 거리 안 짝 없음" : residueText(partner);
}

export function exclusionReasonsText(reasons: readonly MutationExclusionReason[]): string {
  return reasons.length ? reasons.map(reason => mutationReasonText(reason)).join(", ") : "없음";
}

export function protectionText(protection: MutationPosition["protection"]): string {
  if (!protection.reasons.length) return "보호 사유 없음";
  const names = protection.reasons.map(reason => EXCLUSION_REASON_LABEL[reason]).join(", ");
  return protection.released ? `${names} (보호 해제됨)` : names;
}

/** "ILE → A" style text of one candidate, from the stored one-letter codes. */
export function candidateText(row: { from: string; to: string }): string {
  return `${row.from}→${row.to} (${ONE_LETTER_RESNAME[row.from] ?? row.from}→${ONE_LETTER_RESNAME[row.to] ?? row.to})`;
}

/** Rows of the protection check table (status and stored detail of each of the five checks). */
export function protectionCheckRows(checks: MutationProtectionChecks): { key: keyof MutationProtectionChecks;
  label: string; status: string; detail: string }[] {
  const status = (value: string) => `${CHECK_STATUS_LABEL[value] ?? value} (${value})`;
  const klifs = checks.klifs_key_sites;
  return [
    { key: "user_list", label: PROTECTION_CHECK_LABEL.user_list, status: status(checks.user_list.status),
      detail: `보호 목록 ${checks.user_list.protected}개 · 해제 목록 ${checks.user_list.released}개` },
    { key: "klifs_key_sites", label: PROTECTION_CHECK_LABEL.klifs_key_sites, status: status(klifs.status),
      detail: klifs.status === "checked"
        ? `주석 ${klifs.annotation ?? NULL_TEXT} · 주석된 부위 ${nullableText(klifs.annotated_sites)}개 · 없는 부위 ${nullableText(klifs.absent_sites)}개`
        : `${NULL_TEXT} (${klifs.reason ? mutationReasonText(klifs.reason) : "이유 없음"})` },
    { key: "metal_contact", label: PROTECTION_CHECK_LABEL.metal_contact, status: status(checks.metal_contact.status),
      detail: `기준 ${checks.metal_contact.threshold_A} Å 이하 · 금속 잔기 ${checks.metal_contact.metal_residues}개` +
        (checks.metal_contact.metal_names.length ? ` (${checks.metal_contact.metal_names.join(", ")})` : "") },
    { key: "disulfide", label: PROTECTION_CHECK_LABEL.disulfide, status: status(checks.disulfide.status),
      detail: `SG–SG 기준 ${checks.disulfide.threshold_A} Å 이하 · 짝 ${checks.disulfide.pairs}개` },
    { key: "catalytic_residue_database", label: PROTECTION_CHECK_LABEL.catalytic_residue_database,
      status: status(checks.catalytic_residue_database.status),
      detail: `${NULL_TEXT} (${mutationReasonText(checks.catalytic_residue_database.reason)})` },
  ];
}

/** Stored counts of one set as text (positions, candidates, exclusions, releases). */
export function countsText(counts: MutationCounts): string {
  return `위치 ${counts.positions}개 · 후보 위치 ${counts.candidate_positions}개 · 제외 ${counts.excluded_positions}개 · ` +
    `해제 ${counts.released_positions}개 · 후보 ${counts.candidates}개`;
}

/** One stored set in the result list; a row that does not validate shows no numbers. */
export function setRowText(row: MutationCandidateSetListRow): string {
  if (!row.valid || !row.counts) return `저장된 결과를 검증하지 못함 (${mutationReasonText("method_evidence_invalid")})`;
  const klifs = row.klifs_status ? CHECK_STATUS_LABEL[row.klifs_status] ?? row.klifs_status : NULL_TEXT;
  return `${sourcesUsedText(row.sources_used)} · 후보 ${row.counts.candidates}개 · KLIFS 주요 부위 ${klifs}`;
}

export function releaseEffectText(item: MutationCandidateSet["released_residues"][number]): string {
  return `${residueText(item.residue)}: ${RELEASE_EFFECT_LABEL[item.effect]}`;
}

/** The report belongs to the opened set. */
export function mutationReportMatches(artifact: MutationReportArtifact, setHandle: string): boolean {
  return artifact.manifest.schema === "method_report_manifest@1" &&
    artifact.manifest.analysis_type === MUTATION_REPORT_TYPE && artifact.manifest.result_handle === setHandle;
}

// ---- wording check (screen text never claims effect, rank, recommendation or safety) ----

const FORBIDDEN = /친화|ΔΔG|안정성|순위|추천|최적|개선|활성|예측|좋은|유망|안전|\brank|\bbest|optimal|improv|recommend|affinity|stabili|predict/gi;

/** Forbidden words found in screen text, line by line; a line equal to a fixed limitation sentence is exempt. */
export function mutationForbiddenWords(text: string): string[] {
  const found: string[] = [];
  for (const line of text.split("\n")) {
    if (MUTATION_LIMITATIONS.includes(line)) continue;
    for (const match of line.matchAll(FORBIDDEN)) found.push(match[0]);
  }
  return found;
}
