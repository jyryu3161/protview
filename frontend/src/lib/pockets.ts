/** M12 fpocket candidate cavities: API shapes and pure UI state decisions (no React, no Mol*). */
import type { ResidueRef } from "./contracts";
import type { AtomRefV1 } from "./comparison";

export type PocketSourceKind = "prepared_structure" | "chemical_structure" | "openmm_minimized_structure";
export type PocketCapabilityStatus = "ready" | "not_installed" | "unreviewed_build" | "handshake_failed" | "unsupported_platform";
export type PocketUiState = "loading" | "ready" | "scientific_null" | "failed" | "unavailable";
export type PocketPanelKind = "main" | "chemical";

export interface PocketCapability {
  schema: "pocket_capability@1"; status: PocketCapabilityStatus; available: boolean;
  reason_code: string | null; reason: string | null; protocol_id: string; tool_id: string;
  engine: string; release: string; build: string; parser_version: string; argv: string[];
  limits: Record<string, number>; determinism: { seed_control: string; fresh_execution_deterministic: boolean; note: string };
  limitations: string[];
}
export interface PocketDescriptor { native_name: string; native_text?: string; value: number; unit: string;
  detector_specific_note?: string }
export type PocketDescriptorKey = "score" | "druggability_score" | "alpha_sphere_count" | "total_sasa_A2" | "volume_A3";
export const DESCRIPTOR_KEYS: PocketDescriptorKey[] = ["score", "druggability_score", "alpha_sphere_count",
  "total_sasa_A2", "volume_A3"];
export interface PocketReject { failure_class: string; reason_code: string | null; message: string; stage: string;
  detail: Record<string, unknown> }
export interface PocketPreflight {
  schema: "pocket_input_preflight@1"; source_handle: string; source_kind: PocketSourceKind | null;
  model_number: number | null; preparation_handle: string | null;
  available_chains: { chain_auth: string; has_protein: boolean; protein_residues: number; protein_heavy_atoms: number }[];
  selected_chains: string[]; excluded_counts: Record<string, number> | null;
  projected_atom_count: number | null; projected_residue_count: number | null;
  resname_mapping: { residue: ResidueRef; original_resname: string; transport_resname: string }[];
  ready: boolean; reject: PocketReject | null; status: PocketCapabilityStatus | "unsupported_input";
  available: boolean; capability: PocketCapability;
  retention: { limit_bytes: number; used_bytes: number; remaining_bytes: number };
  budget: Record<string, { used: number; limit: number }>;
  limits: Record<string, number>; determinism: PocketCapability["determinism"]; limitations: string[];
  timeout_s: number; starts_job: false;
}
export interface PocketSetRow { handle: string; source_handle: string | null; source_kind: PocketSourceKind | null;
  model_number: number | null; selected_chains: string[] | null; total_count: number | null;
  null_result: boolean | null; job_id: string; created_seq: number; published_seq: number }
export interface PocketSetList { schema: "pocket_set_list@1"; total: number; offset: number; limit: number; rows: PocketSetRow[] }
export interface PocketSummaryRow { rank: number; descriptors: Partial<Record<PocketDescriptorKey, PocketDescriptor>>;
  native_fields: Record<string, string>; alpha_sphere_count: number; lining_atom_count: number;
  lining_residue_count: number; display_center: { x_A: number; y_A: number; z_A: number; method: string } }
export interface PocketSummary {
  schema: "pocket_set_summary@1"; handle: string; job_id: string; source_handle: string; source_kind: PocketSourceKind;
  model_number: number; preparation_handle: string | null; detector_input_handle: string; native_output_handle: string;
  method: Record<string, unknown> & { engine: string; release: string; build: string; seed_control: string;
    fresh_execution_deterministic: boolean };
  total_count: number; null_result: boolean; completeness: string; limitations: string[]; units: Record<string, string>;
  selected_chains: string[]; excluded_counts: Record<string, number>;
  resname_mapping: PocketPreflight["resname_mapping"]; quantization: Record<string, unknown>;
  counts: Record<string, number>; pockets: PocketSummaryRow[];
}
export interface PocketGeometry {
  schema: "pocket_geometry@1"; handle: string; rank: number; source_handle: string; model_number: number;
  units: Record<string, string>; descriptors: PocketSummaryRow["descriptors"];
  spheres: { x_A: number; y_A: number; z_A: number; radius_A: number }[];
  lining_atoms: { transport_indices: number[]; atoms: AtomRefV1[]; native_record_count: number; dedup_policy?: string };
  lining_residues: ResidueRef[]; display_center: PocketSummaryRow["display_center"];
}
export interface PocketJob { job_id: string; run_id: string; protocol_id: string; status: string;
  blocked_reason: string | null; failure: { error: string; message: string; reason_code?: string } | null;
  input_handles: string[]; output_handles: string[]; attempt_ordinal: number; cancel_requested: boolean;
  timeout_s: number; artifacts?: { pocket_set?: string } }
export interface PocketReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "pocket_detection"; result_handle: string;
  snapshot: { event_seq: number } } & Record<string, unknown>; markdown: string }

/** What the viewer is asked to draw: stored alpha spheres of one pocket, unchanged. */
export interface PocketOverlayRequest {
  key: string; runId: string; setHandle: string; sourceHandle: string; modelNumber: number; rank: number;
  /** [x_A, y_A, z_A, radius_A] exactly as stored in the pocket_set. */
  spheres: [number, number, number, number][];
  liningAtoms: AtomRefV1[]; liningResidues: ResidueRef[];
  showSpheres: boolean; showLining: boolean; opacity: number; focusToken: number;
  /** Display-only focus: stored display_center plus the farthest stored sphere surface. Not a scientific value. */
  focus: { center: [number, number, number]; radius: number };
}
/** Read-only observation of what Mol* actually holds (never used to create success). */
export interface PocketOverlayReadback {
  key: string; setHandle: string; sourceHandle: string; rank: number;
  sphereCount: number; centers: number[][]; radii: number[];
  /** Read from the sphere render object's state (never a literal). */
  spheresVisible: boolean; pickable: boolean; opacity: number;
  liningAtomCount: number; liningResidueCount: number; liningVisible: boolean;
  liningNativeSourceIndices: number[];
  focusToken: number; focusedTarget: number[] | null;
  /** focused: the native camera target reached the display center for this focus token; not_converged: it did not
   * within the frame budget; interrupted: a manual camera action happened first. */
  focusStatus: PocketFocusStatus;
}
export type PocketFocusStatus = "focused" | "not_converged" | "interrupted";

export const OVERLAY_LABEL = "fpocket 후보 공동";
export const DEFAULT_TOP_K = 10;
export const MAX_TOP_K = 50;
export const DEFAULT_OPACITY = 0.4;
export const POCKET_TIMEOUT_S = 120;
export const DRUGGABILITY_WARNING = "Druggability Score는 fpocket 고유의 무차원 점수이며 약물성(druggability) 증거가 아닙니다.";
export const LIMITATION_NOTE = "fpocket 후보 공동과 순위는 확인된 결합 부위, 친화도 추정, 입증된 druggability가 아닙니다.";
export const RELATIVE_SCORE_NOTE = "Score와 Druggability Score는 같은 실행의 포켓 사이에서만 비교되는 상대 점수이며 다른 실행·구조와 비교할 수 없습니다.";
export const NONDETERMINISM_NOTE = "새로 실행하면 결과가 달라질 수 있습니다(엔진이 시각으로 난수를 초기화하고 부피를 몬테카를로로 추정합니다). 같은 호출은 저장된 결과를 돌려줍니다.";
const OVERLAY_REASON = "포켓 오버레이가 켜져 있습니다. 포켓 오버레이를 지우면 다시 사용할 수 있습니다.";
const CHEMICAL_REASON = "화학 구조는 M8 프롬프트, M9 보기·PNG, M10 측정·비교 입력으로 쓸 수 없습니다. 포켓 주석을 지워도 제한은 유지됩니다. 지원되는 보기를 복원하거나 원본·전처리·최소화 구조로 돌아가세요.";
const COMPARISON_REASON = "두 구조 비교 중에는 포켓 검출과 오버레이를 사용할 수 없습니다. 단일 구조로 돌아가면 사용할 수 있습니다.";

export function clampTopK(value: number, total: number): number {
  if (!(total > 0)) return 0;
  const wanted = Number.isFinite(value) ? Math.trunc(value) : DEFAULT_TOP_K;
  return Math.min(Math.max(1, Math.min(MAX_TOP_K, wanted)), total);
}

export function pocketDisplay<T>(pockets: T[], totalCount: number, topK: number) {
  const shown = clampTopK(topK, totalCount);
  const rows = pockets.slice(0, shown);
  return { rows, displayed_count: rows.length, total_count: totalCount, truncated: rows.length < totalCount };
}

/** `capability` undefined = capabilities not read yet (loading); null = the backend reports no pocket capability. */
export function pocketUiState(input: { capability?: { available: boolean } | null; jobStatus?: string | null;
  summaryPending?: boolean; readError?: string | null;
  summary?: { null_result: boolean; total_count: number } | null }): PocketUiState {
  const { capability, jobStatus, summaryPending, readError, summary } = input;
  if (readError) return "failed";
  if (summary) {
    if (summary.null_result !== (summary.total_count === 0)) return "failed";
    return summary.null_result ? "scientific_null" : "ready";
  }
  if (summaryPending) return "loading";
  if (jobStatus && ["queued", "claimed", "running"].includes(jobStatus)) return "loading";
  if (jobStatus && ["failed", "interrupted", "cancelled"].includes(jobStatus)) return "failed";
  if (capability === undefined) return "loading";
  if (!capability?.available) return "unavailable";
  return "ready";
}

export function featureGates(input: { sourceKind: string | null; overlayActive: boolean; comparisonActive: boolean }) {
  const chemical = input.sourceKind === "chemical_structure";
  const blocked = chemical ? CHEMICAL_REASON : input.overlayActive ? OVERLAY_REASON : null;
  return { m8: blocked, m9: blocked, m10Measure: chemical ? CHEMICAL_REASON : null,
    pocket: input.comparisonActive ? COMPARISON_REASON : null };
}

export function reopenDecision(panel: PocketPanelKind, sourceKind: string | null): { allowed: boolean; reason: string | null } {
  const main = sourceKind === "prepared_structure" || sourceKind === "openmm_minimized_structure";
  const chemical = sourceKind === "chemical_structure";
  if (panel === "main" ? main : chemical) return { allowed: true, reason: null };
  if (panel === "main" && chemical) return { allowed: false, reason: "화학 작업 화면에서 열기: 화학 구조의 포켓 결과는 화학 작업 화면에서 다시 엽니다." };
  if (panel === "chemical" && main) return { allowed: false, reason: "메인 작업 화면에서 열기: 전처리·최소화 구조의 포켓 결과는 메인 작업 화면에서 다시 엽니다." };
  return { allowed: false, reason: "이 소스 종류의 포켓 결과는 다시 열 수 없습니다." };
}

export function cancelRerunNotice(job: { status: string; protocol_id: string } | null): string | null {
  if (!job || job.protocol_id !== "fpocket_detect_v1" || job.status !== "cancelled") return null;
  return "같은 소스·체인 선택의 검출은 이 run에서 이미 취소되었습니다. 같은 호출은 취소된 작업을 그대로 돌려주므로 다시 실행되지 않습니다. 다른 체인 조합을 고르거나 새 run에서 실행하세요.";
}

export interface PocketActionStamp { runId: string | null; action: number; source: string | null;
  setHandle: string | null; rank: number | null }
/** `mounted` is false once the panel that issued the action unmounted (e.g. run switch); its frozen stamp is never current. */
export function pocketActionCurrent(captured: PocketActionStamp, live: PocketActionStamp, mounted = true): boolean {
  return mounted && captured.runId === live.runId && captured.action === live.action && captured.source === live.source &&
    captured.setHandle === live.setHandle && captured.rank === live.rank;
}

/** Host-side guard: a late overlay/show-source request from another run or for a source the current run does not
 * offer is rejected. A null request (clear) is always accepted. */
export function pocketRequestAccepted(request: { runId: string; sourceHandle: string } | null,
                                      current: { runId: string | null; sourceHandles: readonly string[] }): boolean {
  if (!request) return true;
  return current.runId !== null && request.runId === current.runId && current.sourceHandles.includes(request.sourceHandle);
}

export function overlayContextDecision(request: { sourceHandle: string } | null, boundContext: string | null,
                                       currentContext: string | null, displayedSource: string | null,
                                       viewerReady: boolean): { action: "none" | "wait" | "bind" | "keep" | "clear"; reason: string | null } {
  if (!request) return { action: "none", reason: null };
  if (boundContext === null)
    return viewerReady && displayedSource === request.sourceHandle ? { action: "bind", reason: null } : { action: "wait", reason: null };
  if (boundContext === currentContext && displayedSource === request.sourceHandle) return { action: "keep", reason: null };
  return { action: "clear", reason: "표시 구조가 바뀌어 포켓 오버레이를 지웠습니다. 다시 표시하려면 포켓을 다시 선택하세요." };
}

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

export function geometryError(geometry: PocketGeometry, expected: { handle: string; rank: number; sourceHandle: string }): string | null {
  if (geometry.schema !== "pocket_geometry@1" || geometry.handle !== expected.handle) return "포켓 기하의 handle이 선택한 결과와 다릅니다.";
  if (geometry.rank !== expected.rank) return "포켓 기하의 rank가 선택한 포켓과 다릅니다.";
  if (geometry.source_handle !== expected.sourceHandle) return "포켓 기하의 소스가 선택한 결과와 다릅니다.";
  if (!Array.isArray(geometry.spheres) || !geometry.spheres.length ||
      geometry.spheres.some(s => ![s.x_A, s.y_A, s.z_A, s.radius_A].every(finite) || !(s.radius_A > 0)))
    return "저장된 알파 구가 없거나 유한하지 않습니다.";
  const atoms = geometry.lining_atoms?.atoms;
  if (!Array.isArray(atoms) || !atoms.length || atoms.some(ref => ref.structure_handle !== expected.sourceHandle))
    return "주변 원자가 없거나 다른 소스의 원자입니다.";
  return null;
}

export function clampOpacity(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_OPACITY;
  return Math.min(1, Math.max(0.1, value));
}

export function overlayRequest(runId: string, geometry: PocketGeometry, view: { showSpheres: boolean;
  showLining: boolean; opacity: number; focusToken: number }): PocketOverlayRequest {
  const spheres = geometry.spheres.map(s => [s.x_A, s.y_A, s.z_A, s.radius_A] as [number, number, number, number]);
  const center: [number, number, number] = [geometry.display_center.x_A, geometry.display_center.y_A, geometry.display_center.z_A];
  const radius = Math.max(...spheres.map(s => Math.hypot(s[0] - center[0], s[1] - center[1], s[2] - center[2]) + s[3]));
  return { key: JSON.stringify([runId, geometry.handle, geometry.rank]), runId, setHandle: geometry.handle,
    sourceHandle: geometry.source_handle, modelNumber: geometry.model_number, rank: geometry.rank, spheres,
    liningAtoms: geometry.lining_atoms.atoms, liningResidues: geometry.lining_residues,
    showSpheres: view.showSpheres, showLining: view.showLining, opacity: clampOpacity(view.opacity),
    focusToken: view.focusToken, focus: { center, radius } };
}

/** Coordinates are compared at float32 display precision; radii at the PQR notation precision (2 decimals). */
export function readbackMismatch(spheres: number[][], centers: number[][], radii: number[]): string | null {
  if (centers.length !== spheres.length || radii.length !== spheres.length) return "Mol* 알파 구 개수가 저장된 결과와 다릅니다.";
  for (let i = 0; i < spheres.length; i++) {
    const expected = spheres[i], center = centers[i];
    if (center.length !== 3 || center.some((value, axis) => !finite(value) || Math.abs(value - expected[axis]) > 1e-3))
      return `Mol* 알파 구 ${i + 1}의 중심이 저장된 좌표와 다릅니다.`;
    if (!finite(radii[i]) || Math.abs(radii[i] - expected[3]) > 0.005)
      return `Mol* 알파 구 ${i + 1}의 반지름이 저장된 값과 다릅니다.`;
  }
  return null;
}

const UNIT_TEXT: Record<string, (text: string) => string> = {
  A2: text => `${text} Å²`, A3: text => `${text} Å³`, count: text => `${text}개`,
  dimensionless: text => `${text} (무차원)`,
};
export function descriptorText(descriptor: PocketDescriptor | undefined): string {
  if (!descriptor) return "—";
  const text = descriptor.native_text ?? String(descriptor.value);
  return (UNIT_TEXT[descriptor.unit] ?? (value => `${value} ${descriptor.unit}`))(text);
}

export function chemicalExclusive(action: "overlay_on" | "annotation_on",
                                  state: { annotationVisible: boolean; overlayActive: boolean }) {
  if (action === "overlay_on")
    return { annotationVisible: false, clearOverlay: false,
      notice: state.annotationVisible ? "포켓 오버레이를 켜서 M11 상호작용 주석(연결선·각도)을 숨겼습니다. 두 표시는 동시에 켜지지 않습니다." : null };
  return { annotationVisible: true, clearOverlay: state.overlayActive,
    notice: state.overlayActive ? "M11 상호작용 주석을 켜서 포켓 오버레이를 지웠습니다. 두 표시는 동시에 켜지지 않습니다." : null };
}

export const EMPTY_CHAIN_SELECTION = "체인을 하나 이상 고르세요.";
/** An explicit selection with every chain unchecked is not "all chains": detection stays disabled, no preflight. */
export function chainSelectionError(selection: string[] | null): string | null {
  return selection !== null && selection.length === 0 ? EMPTY_CHAIN_SELECTION : null;
}

/** Only for a non-empty selection (see chainSelectionError); [] means the default of every protein chain. */
export function chainArgument(selected: string[], defaults: string[]): string[] {
  if (!selected.length) throw new Error(EMPTY_CHAIN_SELECTION);
  const chosen = [...new Set(selected)].sort();
  const all = [...new Set(defaults)].sort();
  return chosen.length === all.length && chosen.every((chain, i) => chain === all[i]) ? [] : chosen;
}

export function capabilityStatusText(status: string | null | undefined): string {
  return ({ ready: "사용 가능", not_installed: "설치되지 않음", unreviewed_build: "검토되지 않은 빌드",
    handshake_failed: "작업 프로세스 확인 실패", unsupported_platform: "지원하지 않는 플랫폼",
    unsupported_input: "지원하지 않는 입력" } as Record<string, string>)[status ?? ""] ?? "확인할 수 없음";
}

export function focusStatusText(status: PocketFocusStatus | null | undefined): string {
  return status === "focused" ? "초점 확인됨" : status === "interrupted" ? "초점 이동이 수동 카메라 조작으로 중단됨"
    : status === "not_converged" ? "초점 확인 안 됨 (카메라가 포켓 중심에 도달하지 않음)" : "초점 확인 전";
}
