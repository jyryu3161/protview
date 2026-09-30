/**
 * Pure logic of the M16 "참조 주석" panel on the main structure screen (M16 spec sections 5, 6 and 9).
 *
 * Every number shown comes from the stored `reference_site_annotation@1` object (which quotes the stored numbering
 * map rows and contact rows); this module never measures, counts or recomputes a scientific value. It decides panel
 * state, which stored results belong to the displayed structure handle, display strings that keep "not computed",
 * "not assessed" and "no contact result" apart from 0, reason text, feature exclusivity, late-response keys, save
 * bodies, and the exact atom resolution of polar pair ends through a validated atom catalog.
 */
import type { AnnotationSite, ExactResidueRef, GeometricContactType, ReferenceSiteAnnotation, RunEvent,
  SceneAnnotationRef, SiteAnnotationListRow, SitePolarPair } from "./contracts";
import type { AtomCatalog, AtomRow } from "./comparison";
import type { NumberingMapListRow } from "./numbering";
import { sameResidueRef } from "./comparison";
import { REASON_LABEL } from "./numbering";
import { resultEvents } from "./event-model";

export const SITE_ANNOTATION_TOOL = "annotate_reference_sites";
export const SITE_ANNOTATION_REPORT_TYPE = "reference_site_annotation";
export const CONTACT_TYPES: readonly GeometricContactType[] = ["contact", "polar_contact", "hydrophobic_contact"];
export const CONTACT_TYPE_LABEL: Record<GeometricContactType, string> = {
  contact: "기타 접촉(contact)", polar_contact: "극성 접촉(polar_contact)", hydrophobic_contact: "소수성 접촉(hydrophobic_contact)" };

/** Text composited into a PNG figure when the legend is on (spec 5.4). */
export const FIGURE_LEGEND_TEXT = "점선: 기하 극성 접촉(원자 거리), 수소결합 판정 아님";
/** Panel legend (spec 5.1). */
export const PANEL_LEGEND_TEXT = "점선: 기하 극성 접촉(N/O–N/O 원자 거리, cutoff 이내). 수소결합 판정 아님.";
export const KLIFS_REFERENCE_NOTE = "KLIFS 번호는 참조 스냅샷 값이며 계산값이 아니고 잔기의 역할을 뜻하지 않습니다.";
export const MIN_DISTANCE_NOTE = "최소 거리는 계산한 접촉 종류·cutoff 안의 최소입니다.";
export const NULL_RESULT_TEXT = "이 대응에는 주요 부위에 번호가 붙은 잔기가 없습니다";
export const NO_MAP_PREREQUISITE = "이 구조로 지식 탭에서 번호 대응을 먼저 만드세요";
export const MINIMIZED_REASON = "최소화 구조에는 번호 대응이 없어 주석할 수 없음";
export const CHEMICAL_REASON = "화학 구조 보기에는 참조 주석을 쓸 수 없습니다. 원본·전처리 구조로 돌아가세요.";
export const NO_SOURCE_REASON = "표시 중인 구조가 없습니다. 원본 또는 전처리 구조를 먼저 불러오세요.";
export const UNSUPPORTED_SOURCE_REASON = "이 표시 소스에는 참조 주석을 쓸 수 없습니다(원본·전처리 구조만).";
export const POCKET_OVERLAY_BLOCKS_ANNOTATION = "포켓 오버레이가 켜져 있어 참조 주석을 켤 수 없습니다. 두 표시는 동시에 켜지지 않으므로 포켓 오버레이를 먼저 끄세요.";
export const ANNOTATION_BLOCKS_POCKET_OVERLAY = "참조 주석이 켜져 있어 포켓 오버레이를 켤 수 없습니다. 두 표시는 동시에 켜지지 않으므로 참조 주석을 먼저 끄세요.";
export const COMPARISON_BLOCKS_ANNOTATION = "두 구조 비교(겹쳐 보기) 중에는 참조 주석을 켤 수 없습니다. 단일 구조로 돌아가면 사용할 수 있습니다.";
export const ANNOTATION_BLOCKS_M8 = "참조 주석이 켜진 동안에는 자연어 뷰어 요청을 보낼 수 없습니다(주석 내용을 외부로 보내는 길이 없음). 로컬 뷰어 명령은 그대로 쓸 수 있습니다.";
export const RESTORE_BLOCKED_POCKET = "포켓 오버레이가 켜져 있어 참조 주석 보기를 복원하지 않았습니다. 포켓 오버레이를 끈 뒤 다시 복원하세요.";
export const RESTORE_BLOCKED_COMPARISON = "두 구조 비교 중이라 참조 주석 보기를 복원하지 않았습니다. 비교를 끝낸 뒤 다시 복원하세요.";

// ---- reason text ----

/** Korean names of the site / group / contact reason codes of `mw.site_annotation`; M15 KLIFS codes reuse M15 names. */
export const SITE_REASON_LABEL: Record<string, string> = {
  klifs_not_applied: "KLIFS 번호를 적용하지 않은 그룹",
  pocket_gap: "KLIFS 포켓 서열에서 이 자리가 gap",
  region_unresolved: "이 자리의 KLIFS 구역을 정하지 못함",
  no_mapped_residue: "이 번호가 붙은 대응된 잔기 없음",
  no_mapped_accession: "대응된 UniProt 항목 없음",
  residue_not_checked_by_contact_method: "접촉 도구가 검사하지 않는 잔기",
};

const own = (table: Record<string, string>, code: string) =>
  Object.prototype.hasOwnProperty.call(table, code) ? table[code] : undefined;

/** "한국어 (code)"; unknown codes are shown as is. */
export function siteReasonText(code: string): string {
  const label = own(SITE_REASON_LABEL, code) ?? own(REASON_LABEL, code);
  return label ? `${label} (${code})` : code;
}

// ---- numbers as stored ----

/**
 * The value's decimal string (JS shortest repr, equal to Python `repr(float)` here) quantized with ROUND_HALF_UP
 * (away from zero at a tie). Exponent forms are returned exactly.
 */
export function decimalHalfUp(value: number, digits: number): string {
  const text = String(value);
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match || !Number.isInteger(digits) || digits < 0) return text;
  const [, sign, whole, frac = ""] = match;
  let scaled = BigInt(whole + frac.slice(0, digits).padEnd(digits, "0"));
  if (frac.length > digits && frac[digits] >= "5") scaled += 1n;
  if (scaled === 0n) return digits ? `0.${"0".repeat(digits)}` : "0";
  const body = scaled.toString().padStart(digits + 1, "0");
  return digits ? `${sign}${body.slice(0, -digits)}.${body.slice(-digits)}` : `${sign}${body}`;
}

/** Stored `distance_A` shown with two decimals, e.g. 2.9349 -> "2.93 Å", 2.935 -> "2.94 Å". */
export function distanceText(value: number): string { return `${decimalHalfUp(value, 2)} Å`; }

export const NOT_COMPUTED_TEXT = "계산하지 않음";
export const NOT_ASSESSED_TEXT = "접촉 도구가 검사하지 않는 잔기";
export const NO_CONTACT_RESULT_TEXT = "접촉 결과 없음";
export const ABSENT_SITE_TEXT = "—";

/**
 * Count cell of one site and one contact type. A number (0 included) only when the type was computed for an
 * assessed residue; otherwise a text that is never a number.
 */
export function contactCountText(annotation: Pick<ReferenceSiteAnnotation, "contacts">, site: AnnotationSite,
                                 type: GeometricContactType): string {
  if (site.status !== "annotated") return ABSENT_SITE_TEXT;
  if (!annotation.contacts || !site.contact) return NO_CONTACT_RESULT_TEXT;
  if (!site.contact.assessed) return NOT_ASSESSED_TEXT;
  const entry = site.contact.by_type[type];
  if (!entry || !entry.computed || entry.count === null) return NOT_COMPUTED_TEXT;
  return String(entry.count);
}

/** Minimum distance cell: stored value or the reason it has none (never 0). */
export function minDistanceText(annotation: Pick<ReferenceSiteAnnotation, "contacts">, site: AnnotationSite): string {
  if (site.status !== "annotated") return ABSENT_SITE_TEXT;
  if (!annotation.contacts || !site.contact) return NO_CONTACT_RESULT_TEXT;
  if (!site.contact.assessed) return NOT_ASSESSED_TEXT;
  if (site.contact.min_distance_A === null) return "계산한 종류·cutoff 안 접촉 없음";
  return distanceText(site.contact.min_distance_A);
}

/** Polar pair list state of a site: null polar_pairs is "not computed", never an empty list. */
export function polarPairsText(annotation: Pick<ReferenceSiteAnnotation, "contacts">, site: AnnotationSite): string | null {
  if (site.status !== "annotated") return ABSENT_SITE_TEXT;
  if (!annotation.contacts || !site.contact) return NO_CONTACT_RESULT_TEXT;
  if (!site.contact.assessed) return NOT_ASSESSED_TEXT;
  if (site.contact.polar_pairs === null) return NOT_COMPUTED_TEXT;
  return site.contact.polar_pairs.length ? null : "극성 접촉 0";
}

/** Status cell: "주석됨" or "없음: 한국어 (code)". */
export function siteStatusText(site: AnnotationSite): string {
  return site.status === "annotated" ? "주석됨" : `없음: ${site.absent_reason ? siteReasonText(site.absent_reason) : "이유 없음"}`;
}

export type SiteRegion = "III" | "αC" | "GK" | "hinge" | "xDFG";
/** KLIFS region of a fixed `kinase_key_sites@1` index (colour group); null for any other index. */
export function siteRegion(klifsIndex: number): SiteRegion | null {
  if (klifsIndex === 17) return "III";
  if (klifsIndex === 24) return "αC";
  if (klifsIndex === 45) return "GK";
  if (klifsIndex >= 46 && klifsIndex <= 48) return "hinge";
  if (klifsIndex >= 80 && klifsIndex <= 83) return "xDFG";
  return null;
}

// ---- panel state ----

export type AnnotationPanelState =
  | { state: "loading" } | { state: "ready" } | { state: "scientific_null"; message: string }
  | { state: "failure"; message: string } | { state: "unavailable"; reason: string };

export const ANNOTATABLE_SOURCE_KINDS = ["structure", "prepared_structure"] as const;

/** Why the displayed source cannot carry an annotation (null = it can). */
export function sourceUnavailableReason(sourceKind: string | null): string | null {
  if (sourceKind === null) return NO_SOURCE_REASON;
  if ((ANNOTATABLE_SOURCE_KINDS as readonly string[]).includes(sourceKind)) return null;
  if (sourceKind === "openmm_minimized_structure") return MINIMIZED_REASON;
  if (sourceKind === "chemical_structure") return CHEMICAL_REASON;
  return UNSUPPORTED_SOURCE_REASON;
}

/**
 * Five panel states. `capability` undefined = not read yet; null = the backend reports no such method.
 * `annotation` is the currently opened stored annotation (if any).
 */
export function annotationPanelState(input: { sourceKind: string | null;
  capability?: { available: boolean; reason: string | null } | null; loading?: boolean; error?: string | null;
  annotation?: Pick<ReferenceSiteAnnotation, "null_result" | "groups"> | null }): AnnotationPanelState {
  const unavailable = sourceUnavailableReason(input.sourceKind);
  if (unavailable) return { state: "unavailable", reason: unavailable };
  if (input.capability === null || input.capability?.available === false)
    return { state: "unavailable", reason: input.capability?.reason ?? "참조 주석 기능을 사용할 수 없습니다." };
  if (input.error) return { state: "failure", message: input.error };
  if (input.loading || input.capability === undefined) return { state: "loading" };
  const annotation = input.annotation;
  if (annotation) {
    const annotated = annotation.groups.some(group => group.sites.some(site => site.status === "annotated"));
    if (annotation.null_result === annotated) return { state: "failure", message: "주석 결과의 null_result가 부위 상태와 맞지 않습니다." };
    if (annotation.null_result) return { state: "scientific_null", message: NULL_RESULT_TEXT };
  }
  return { state: "ready" };
}

// ---- same structure handle only ----

export function mapsForSource(rows: readonly NumberingMapListRow[], sourceHandle: string | null): NumberingMapListRow[] {
  return sourceHandle === null ? [] : rows.filter(row => row.structure === sourceHandle);
}

export function annotationsForSource(rows: readonly SiteAnnotationListRow[], sourceHandle: string | null): SiteAnnotationListRow[] {
  return sourceHandle === null ? [] : rows.filter(row => row.structure === sourceHandle);
}

export interface ContactSetOption { handle: string; structure: string; ligand: ExactResidueRef; cutoff_A: number;
  types: GeometricContactType[]; n_edges: number | null; null_result: boolean; seq: number }

/**
 * Stored `interaction_set@1` results of this run whose structure is the displayed source handle, read from the
 * result events (successful calls and valid cache observations) with the tool's own summary; once per handle.
 */
export function contactSetsForSource(events: RunEvent[], sourceHandle: string | null): ContactSetOption[] {
  if (sourceHandle === null) return [];
  const seen = new Set<string>();
  const options: ContactSetOption[] = [];
  for (const event of resultEvents(events)) {
    const output = event.output;
    if (event.tool !== "compute_interactions" || output.kind !== "interaction_set" || output.schema !== "interaction_set@1" ||
        seen.has(output.handle)) continue;
    const summary = output.summary as { structure?: unknown; ligand?: unknown; cutoff_A?: unknown; types?: unknown; n_edges?: unknown };
    if (summary.structure !== sourceHandle || typeof summary.ligand !== "object" || summary.ligand === null ||
        typeof summary.cutoff_A !== "number" || !Array.isArray(summary.types)) continue;
    seen.add(output.handle);
    options.push({ handle: output.handle, structure: sourceHandle, ligand: summary.ligand as ExactResidueRef,
      cutoff_A: summary.cutoff_A, types: summary.types as GeometricContactType[],
      n_edges: typeof summary.n_edges === "number" ? summary.n_edges : null, null_result: !!output.null_result,
      seq: event.seq });
  }
  return options;
}

/** Contact choice: "unset" until the user picks (never auto-selected, even with a single option). */
export type ContactChoice = { kind: "unset" } | { kind: "none" } | { kind: "set"; handle: string };
export const INITIAL_CONTACT_CHOICE: ContactChoice = { kind: "unset" };

/** A chosen contact result that is no longer offered goes back to "unset" (never to another option). */
export function reconcileContactChoice(choice: ContactChoice, options: readonly { handle: string }[]): ContactChoice {
  if (choice.kind !== "set") return choice;
  return options.some(option => option.handle === choice.handle) ? choice : INITIAL_CONTACT_CHOICE;
}

/** A chosen map that is no longer offered for the source is dropped (never replaced automatically). */
export function reconcileMapChoice(handle: string | null, maps: readonly { handle: string }[]): string | null {
  return handle !== null && maps.some(row => row.handle === handle) ? handle : null;
}

export type CreateCheck = { ok: true; args: { numbering_map: string; contacts: string | null } } | { ok: false; errors: string[] };

/** Tool arguments of "주석 만들기"; the server re-validates everything (kind, run, structure_mismatch). */
export function createAnnotationArgs(input: { sourceHandle: string | null; mapHandle: string | null;
  contactChoice: ContactChoice; maps: readonly NumberingMapListRow[]; contactSets: readonly ContactSetOption[] }): CreateCheck {
  const errors: string[] = [];
  const maps = mapsForSource(input.maps, input.sourceHandle);
  if (!maps.length) errors.push(NO_MAP_PREREQUISITE);
  else if (!input.mapHandle) errors.push("번호 대응을 고르세요.");
  else if (!maps.some(row => row.handle === input.mapHandle)) errors.push("고른 번호 대응이 표시 중인 구조의 것이 아닙니다.");
  let contacts: string | null = null;
  if (input.contactChoice.kind === "unset") errors.push("접촉 결과를 고르거나 \"접촉 결과 없이\"를 고르세요.");
  else if (input.contactChoice.kind === "set") {
    const handle = input.contactChoice.handle;
    if (!input.contactSets.some(option => option.handle === handle && option.structure === input.sourceHandle))
      errors.push("고른 접촉 결과가 표시 중인 구조의 것이 아닙니다.");
    contacts = handle;
  }
  if (errors.length || !input.mapHandle) return { ok: false, errors };
  return { ok: true, args: { numbering_map: input.mapHandle, contacts } };
}

/** An opened annotation may be drawn only on its own structure handle. */
export function annotationMatchesSource(annotation: Pick<ReferenceSiteAnnotation, "structure">, sourceHandle: string | null): boolean {
  return sourceHandle !== null && annotation.structure.handle === sourceHandle;
}

// ---- exclusivity (spec 5.3) ----

export interface AnnotationGates {
  /** Reason the annotation cannot be turned on (null = allowed). */
  annotation: string | null;
  /** Reason the pocket overlay cannot be turned on because of the annotation. */
  pocketOverlay: string | null;
  /** Reason M8 natural-language viewer requests are blocked by the annotation. */
  m8: string | null;
  /** M9 scene save / PNG are never blocked by the annotation (other rules such as the pocket overlay still apply). */
  m9: null;
}

export function annotationGates(input: { sourceKind: string | null; annotationOn: boolean;
  pocketOverlayActive: boolean; comparisonActive: boolean }): AnnotationGates {
  const annotation = sourceUnavailableReason(input.sourceKind) ??
    (input.comparisonActive ? COMPARISON_BLOCKS_ANNOTATION : input.pocketOverlayActive ? POCKET_OVERLAY_BLOCKS_ANNOTATION : null);
  return { annotation, pocketOverlay: input.annotationOn ? ANNOTATION_BLOCKS_POCKET_OVERLAY : null,
    m8: input.annotationOn ? ANNOTATION_BLOCKS_M8 : null, m9: null };
}

/**
 * Whether a shown annotation must be turned off: a run or source change, a comparison start, or a source that
 * cannot carry an annotation.
 */
export function annotationMustTurnOff(previous: { runId: string | null; sourceHandle: string | null },
                                      next: { runId: string | null; sourceHandle: string | null; sourceKind: string | null;
                                        comparisonActive: boolean }): boolean {
  return previous.runId !== next.runId || previous.sourceHandle !== next.sourceHandle || next.comparisonActive ||
    sourceUnavailableReason(next.sourceKind) !== null;
}

/** `viewer_scene@2` restore is refused (with reason) while a pocket overlay or a comparison is active. */
export function sceneRestoreDecision(scene: { schema: string },
                                     state: { pocketOverlayActive: boolean; comparisonActive: boolean }):
  { allowed: boolean; reason: string | null } {
  if (scene.schema !== "viewer_scene@2") return { allowed: true, reason: null };
  if (state.comparisonActive) return { allowed: false, reason: RESTORE_BLOCKED_COMPARISON };
  if (state.pocketOverlayActive) return { allowed: false, reason: RESTORE_BLOCKED_POCKET };
  return { allowed: true, reason: null };
}

/** The annotation of a stored scene or null for `viewer_scene@1`. */
export function sceneAnnotation(scene: { schema: string; annotation?: SceneAnnotationRef }): SceneAnnotationRef | null {
  return scene.schema === "viewer_scene@2" && scene.annotation ? scene.annotation : null;
}

// ---- late responses (run + source + request sequence) ----

export interface AnnotationStamp { runId: string | null; sourceHandle: string | null; seq: number }

/** A response is applied only when run, source and request sequence are all still the latest. */
export function annotationResponseCurrent(captured: AnnotationStamp, live: AnnotationStamp): boolean {
  return captured.runId !== null && captured.runId === live.runId && captured.sourceHandle === live.sourceHandle &&
    captured.seq === live.seq;
}

export function annotationRequestKey(stamp: AnnotationStamp): string {
  return JSON.stringify([stamp.runId, stamp.sourceHandle, stamp.seq]);
}

// ---- save bodies (spec 5.4) ----

/**
 * Scene save body: the `viewer_scene@1` body is returned unchanged (same object, same bytes) when no annotation is
 * shown; otherwise the same fields with `schema: "viewer_scene@2"` and the annotation.
 */
export function sceneSaveBody<T extends { schema: "viewer_scene@1" }>(body: T, annotation: SceneAnnotationRef | null):
  T | (Omit<T, "schema"> & { schema: "viewer_scene@2"; annotation: SceneAnnotationRef }) {
  if (!annotation) return body;
  return { ...body, schema: "viewer_scene@2", annotation: { handle: annotation.handle, legend: annotation.legend } };
}

/** Figure save body: follows its scene's schema; `legend_composited` only for `viewer_scene@2` scenes. */
export function figureSaveBody<T extends { schema: "viewer_figure@1" }>(body: T, sceneSchema: string, legendComposited: boolean):
  T | (Omit<T, "schema"> & { schema: "viewer_figure@2"; legend_composited: boolean }) {
  if (sceneSchema !== "viewer_scene@2") return body;
  return { ...body, schema: "viewer_figure@2", legend_composited: legendComposited };
}

/** Composite the legend only when the scene's legend is on and at least one dashed line is drawn. */
export function legendShouldComposite(legend: boolean, drawnPairCount: number): boolean {
  return legend && drawnPairCount > 0;
}

// ---- exact atom resolution (spec 5.2) ----

export type AtomResolution = { drawable: true; atom: AtomRow } | { drawable: false; reason: "none" | "ambiguous" };

/**
 * (residue 7 fields + atom name) -> exactly one row of a complete, validated catalog; 0 rows -> none, 2+ rows
 * (e.g. altlocs) -> ambiguous. Never by nearest coordinate, Mol* label or PDB serial.
 */
export function resolveAtom(catalog: AtomCatalog, residue: ExactResidueRef, atomName: string): AtomResolution {
  if (catalog.offset !== 0 || catalog.rows.length !== catalog.total) throw new Error("Incomplete atom catalog");
  const rows = catalog.rows.filter(row => row.ref.structure_handle === catalog.structure_handle &&
    row.ref.atom_name === atomName && sameResidueRef(row.ref.residue, residue));
  if (rows.length === 1) return { drawable: true, atom: rows[0] };
  return { drawable: false, reason: rows.length ? "ambiguous" : "none" };
}

export interface DrawnPair { site: AnnotationSite; pair: SitePolarPair; protein: AtomRow; ligand: AtomRow; label: string }
export interface UndrawnPair { site: AnnotationSite; pair: SitePolarPair; side: "protein" | "ligand";
  reason: "none" | "ambiguous"; text: string }

export function undrawnText(reason: "none" | "ambiguous"): string {
  return reason === "none" ? "그리지 못함(원자 대응 없음)" : "그리지 못함(원자 대응 모호)";
}

/** Every stored polar pair of the annotated sites, split into drawable (both ends exact) and undrawable pairs. */
export function polarPairsForDrawing(annotation: ReferenceSiteAnnotation, catalog: AtomCatalog):
  { drawn: DrawnPair[]; undrawn: UndrawnPair[] } {
  const drawn: DrawnPair[] = [];
  const undrawn: UndrawnPair[] = [];
  if (!annotation.contacts || catalog.structure_handle !== annotation.structure.handle) return { drawn, undrawn };
  const ligand = annotation.contacts.ligand;
  for (const group of annotation.groups) for (const site of group.sites) {
    if (site.status !== "annotated" || !site.residue || !site.contact?.polar_pairs) continue;
    for (const pair of site.contact.polar_pairs) {
      const protein = resolveAtom(catalog, site.residue, pair.protein_atom);
      const other = resolveAtom(catalog, ligand, pair.ligand_atom);
      if (!protein.drawable) undrawn.push({ site, pair, side: "protein", reason: protein.reason, text: undrawnText(protein.reason) });
      else if (!other.drawable) undrawn.push({ site, pair, side: "ligand", reason: other.reason, text: undrawnText(other.reason) });
      else drawn.push({ site, pair, protein: protein.atom, ligand: other.atom, label: distanceText(pair.distance_A) });
    }
  }
  return { drawn, undrawn };
}

// ---- viewer bridge (MolstarViewer `siteAnnotation` prop, QA snapshot, scene restore) ----

/** Design token (CSS custom property name without `--`) of each site region colour; also used for panel swatches. */
export const SITE_REGION_TOKEN: Record<SiteRegion, string> = {
  III: "site-iii", "αC": "site-ac", GK: "site-gk", hinge: "site-hinge", xDFG: "site-xdfg" };
export const SITE_OTHER_CONTACT_TOKEN = "site-other-contact";
export const SITE_POLAR_LINE_TOKEN = "site-polar-line";

/** One stored annotation to draw on its own structure handle (spec 5.2). Any change of `key` redraws. */
export interface SiteAnnotationRequest {
  /** Revision key chosen by the page (e.g. run + annotation handle + source + toggle state). */
  key: string;
  handle: string;
  sourceHandle: string;
  annotation: ReferenceSiteAnnotation;
  visible: boolean;
  /** Recorded for the figure legend; drawing is the same either way. */
  legend: boolean;
}

/** What Mol* actually holds after drawing (read from native components, selections and shape transforms). */
export interface SiteAnnotationReadback {
  key: string; handle: string; sourceHandle: string; legend: boolean;
  drawnSiteCount: number;
  drawnLineCount: number;
  sites: { chain_auth: string; accession: string | null; klifs_label: string; region: SiteRegion;
    display_label: string; labelText: string; nativeSourceIndices: number[] }[];
  lines: { klifs_label: string; contact_row_index: number; protein_atom: string; ligand_atom: string;
    proteinSourceIndex: number; ligandSourceIndex: number; labelText: string; pickable: boolean }[];
  undrawnPairs: { klifs_label: string; display_label: string | null; contact_row_index: number;
    protein_atom: string; ligand_atom: string; side: "protein" | "ligand"; reason: "none" | "ambiguous"; text: string }[];
  /** Native label texts: site labels (in site order) then distance labels (in line order). */
  labelTexts: string[];
  otherContactResidueCount: number; otherContactNativeSourceIndices: number[];
  ligandVisible: boolean; ligandNativeSourceIndices: number[];
  /** Hex colours actually passed to Mol* for each drawn region, the other contact residues and the lines. */
  colors: Record<string, string>;
  /** State-tree refs of the label and distance shape representations. */
  nativeShapeRefs: string[];
  /** State-tree refs of the residue / ligand components. */
  nativeComponentRefs: string[];
}

/** Annotation part of a `viewer_scene@2` restore: applied (with native readback) or rejected with a reason. */
export type SiteAnnotationRestoreOutcome =
  | { status: "applied"; readback: SiteAnnotationReadback } | { status: "rejected"; reason: string };
