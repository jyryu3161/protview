/** Loopback-only M1 API client. See docs/M1_API.md. */
import type { BudgetSnapshot, EgressMode, Handle, InteractionRow, ResidueRef, RunEvent, ToolError } from "./contracts";
import type { ViewerSource } from "@/components/MolstarViewer";
import type { ViewerIntent, ViewerOnlineStatus, ViewerSession, ViewerRepresentationValue } from "./viewer-agent";
import type { NativeSceneState, SavedFigureDetail, SavedPage, SavedSceneDetail } from "./saved-scene";

export interface SceneBindingRequest { client_instance_id: string; viewer_session_id: string;
  scene_generation: number; action_revision: number; request_id: string }

export interface RunSummary { run_id: string; goal: string; context: string[]; dry_run: boolean; egress: EgressMode; last_seq: number }
export function displayedEgressMode(run: RunSummary | null): EgressMode {
  return run?.dry_run ? "dry_run" : run?.egress ?? "local_only";
}
export interface UploadResult { upload_id: string; sha256: string; size: number; format: "pdb" | "cif" | "mmcif"; n_models: number; model_numbers: number[] }
export interface ResidueItem extends ResidueRef { atom_count: number; category: "polymer" | "nonpolymer" | "water" }
export interface ResidueList { model_number: number; residues: ResidueItem[]; ligands: ResidueRef[] }
export interface ObjectMeta { handle: string; kind: string; schema: string; fmt: string; size: number; produced_by: string | null; summary: Record<string, unknown>; null_result: boolean }
export interface Page<T> { meta: ObjectMeta; rows: T[]; total: number; offset: number; limit: number }
export interface Capabilities { mode: "local_only"; supported: Record<string, string>; unavailable: Record<string, string>;
  methods?: { openmm_protein_minimize?: { available: boolean; method_id?: string; distribution_version?: string; engine_build?: string; unit?: string; limitations?: string; explanation?: string }; interface_sasa?: { available: boolean; method_id?: string; algorithm?: string; n_slices?: number;
    engine_version?: string; unit?: string; limitations?: string; explanation?: string } } }
export interface SavedReportRef { handle: string; interaction_handle?: string; result_handle?: string; analysis_type?: string;
  markdown_handle: string; created_seq: number; snapshot_event_seq: number }
export interface ReportArtifact { handle: string; markdown_handle: string; manifest: {
  interaction_handle: string; prepared_handle: string; source_handle: string;
  counts: { atom_pairs: number; contacting_residues: number; by_type: Record<string, number> };
  minimum_distance_A: number | null; scientific_null: boolean;
  snapshot: { event_seq: number }; capabilities: { protocols: Record<string, { available: boolean; reason_code: string; explanation: string }> };
}; markdown: string }
export interface SasaResidueRow { residue: ResidueRef; atom_indices: number[]; isolated_A2: number; bound_A2: number; buried_A2: number }
export interface SasaResult { schema: "interface_sasa@1"; structure: string; ligand: ResidueRef;
  selection: { excluded: { residue: ResidueRef; atom_count: number; reason: string }[]; hydrogen_policy: string };
  method: { method_id: string; algorithm: string; n_slices: number; engine_version: string; probe_radius_A: number; threads: number };
  atom_counts: { protein: number; ligand: number; excluded_residues: number };
  summary: Record<"protein_sasa_isolated_A2" | "ligand_sasa_isolated_A2" | "complex_sasa_A2" |
    "protein_sasa_bound_A2" | "ligand_sasa_bound_A2" | "protein_burial_A2" |
    "ligand_burial_A2" | "total_sasa_loss_A2", number>;
  residues: SasaResidueRow[] }
export interface MethodReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "interface_sasa"; result_handle: string;
  prepared_handle: string; snapshot: { event_seq: number }; summary: SasaResult["summary"];
}; markdown: string }
export interface OpenmmJob { job_id: string; run_id: string; protocol_id: string; status: string; blocked_reason: string | null;
  failure: { error: string; message: string } | null; input_handles: string[]; output_handles: string[];
  attempt_ordinal: number; cancel_requested: boolean; timeout_s: number }
export interface OpenmmPlanOnly { plan_only: true; protocol_id: "openmm_protein_minimize";
  reason_code: "dry_run"; available: false; output_handles: []; normalized_parameters: { structure: string; [key: string]: unknown } }
export type OpenmmSubmission = OpenmmJob | OpenmmPlanOnly;
export interface OpenmmResult { schema: "openmm_protein_minimization@1"; structure: string; minimized_structure: string;
  before_kJ_mol: number; after_kJ_mol: number; potential_change_kJ_mol: number; job_id: string;
  atom_count: number; heavy_atom_count: number; added_hydrogen_count: number;
  excluded: { residue: ResidueRef; atom_count: number; reason: string }[]; convergence: string }
export interface OpenmmReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "openmm_protein_minimize"; result_handle: string;
  prepared_handle: string; snapshot: { event_seq: number } }; markdown: string }

export type CommandResult = { ok: true; handle: Handle } | ({ ok: false } & ToolError) | { ok: false; approval: { gate: string; tool: string; reason: string } } | { ok: false; loop_stop: { reason: string } };

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    let data: { detail?: { message?: string; error?: string } | string; message?: string; error?: string } = {};
    try { data = await response.json(); } catch { /* non-JSON server failure */ }
    const detail = typeof data.detail === "object" ? data.detail : undefined;
    throw new ApiError(response.status, detail?.message ?? data.message ?? (typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`), detail?.error ?? data.error);
  }
  return response.json() as Promise<T>;
}

function runPath(runId: string, tail = "") { return `/runs/${encodeURIComponent(runId)}${tail}`; }
function handleParam(handle: string) { return `handle=${encodeURIComponent(handle)}`; }

export const api = {
  savedScenes: (id: string, offset = 0) => request<SavedPage<SavedSceneDetail>>(runPath(id, `/viewer/scenes?offset=${offset}&limit=50`)),
  savedScene: (id: string, handle: string, signal?: AbortSignal) => request<SavedSceneDetail>(runPath(id, `/viewer/scenes/selected?${handleParam(handle)}`), { signal }),
  saveScene: (id: string, body: SceneBindingRequest & NativeSceneState & { schema: "viewer_scene@1"; name: string }) =>
    request<SavedSceneDetail>(runPath(id, "/viewer/scenes"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  savedFigures: (id: string, offset = 0) => request<SavedPage<SavedFigureDetail>>(runPath(id, `/viewer/figures?offset=${offset}&limit=50`)),
  savedFigure: (id: string, handle: string) => request<SavedFigureDetail>(runPath(id, `/viewer/figures/selected?${handleParam(handle)}`)),
  saveFigure: (id: string, body: SceneBindingRequest & NativeSceneState & { schema: "viewer_figure@1";
    scene_handle: string; png_base64: string }) => request<SavedFigureDetail>(runPath(id, "/viewer/figures"),
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  figureDownload: (id: string, handle: string, format: "png" | "json") =>
    `/api${runPath(id, `/viewer/figures/download?${handleParam(handle)}&format=${format}`)}`,
  viewerSession: (id: string, body: { client_instance_id: string; scene_generation: number;
    structure_handle: string; representation: ViewerRepresentationValue;
    scope_chain_auth?: string | null; scope_target?: ResidueRef | null; selected_target?: ResidueRef | null }) =>
    request<ViewerSession>(runPath(id, "/viewer/sessions"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  viewerSessionState: (id: string, sessionId: string, body: { representation: ViewerRepresentationValue;
    selected_alias: string | null; action_revision: number }) =>
    request<ViewerSession>(runPath(id, `/viewer/sessions/${encodeURIComponent(sessionId)}/state`),
      { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  viewerOnline: (id: string) => request<ViewerOnlineStatus>(runPath(id, "/viewer/online")),
  setViewerOnline: (id: string, enabled: boolean) => request<ViewerOnlineStatus>(runPath(id, "/viewer/online"),
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ enabled }) }),
  viewerIntent: (id: string, body: { client_instance_id: string; viewer_session_id: string;
    scene_generation: number; request_id: string; prompt: string }, signal?: AbortSignal) =>
    request<ViewerIntent>(runPath(id, "/viewer/intents"),
      { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal }),
  viewerIntentGet: (id: string, intentId: string) => request<ViewerIntent>(runPath(id, `/viewer/intents/${encodeURIComponent(intentId)}`)),
  viewerIntents: (id: string) => request<ViewerIntent[]>(runPath(id, "/viewer/intents")),
  viewerIntentCancel: (id: string, intentId: string, scope?: { client_instance_id: string;
    viewer_session_id: string; scene_generation: number }) => request<ViewerIntent>(runPath(id, `/viewer/intents/${encodeURIComponent(intentId)}/cancel`),
      { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(scope ?? null) }),
  viewerAck: (id: string, intentId: string, body: { command_id: string; status: "applied" | "no_change" | "failed";
    reason_code?: string | null; client_instance_id: string; viewer_session_id: string;
    scene_generation: number; action_revision: number }) =>
    request<ViewerIntent>(runPath(id, `/viewer/intents/${encodeURIComponent(intentId)}/ack`),
      { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  capabilities: () => request<Capabilities>("/capabilities"),
  runs: () => request<RunSummary[]>("/runs"),
  run: (id: string) => request<RunSummary>(runPath(id)),
  createRun: () => request<RunSummary>("/runs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ goal: "로컬 구조 검사", context: [], dry_run: false, egress: "local_only" }) }),
  upload: (id: string, file: File) => request<UploadResult>(runPath(id, `/uploads?filename=${encodeURIComponent(file.name)}`), { method: "POST", headers: { "content-type": "application/octet-stream" }, body: file }),
  command: (id: string, tool: "load_structure" | "prepare_structure" | "compute_interactions" | "compute_interface_sasa", args: Record<string, unknown>) =>
    request<CommandResult>(runPath(id, "/commands"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ tool, args, decided_by: "human", execution_mode: "human" }) }),
  events: (id: string, after = 0, limit = 500) => request<RunEvent[]>(runPath(id, `/events?after=${after}&limit=${limit}`)),
  async allEvents(id: string): Promise<RunEvent[]> {
    const all: RunEvent[] = [];
    for (;;) {
      const page = await api.events(id, all.at(-1)?.seq ?? 0);
      all.push(...page);
      if (page.length < 500) return all;
    }
  },
  budget: (id: string) => request<BudgetSnapshot>(runPath(id, "/budget")),
  meta: (id: string, handle: string) => request<ObjectMeta>(runPath(id, `/objects/meta?${handleParam(handle)}`)),
  residues: (id: string, handle: string) => request<ResidueList>(runPath(id, `/structures/residues?${handleParam(handle)}`)),
  interactions: (id: string, handle: string, offset = 0, limit = 50) =>
    request<Page<InteractionRow>>(runPath(id, `/objects?${handleParam(handle)}&offset=${offset}&limit=${limit}`)),
  openmmPreflight: (id: string, structure: string) => request<{ available: boolean; structure: string; heavy_atom_count: number;
    excluded: { residue: ResidueRef; atom_count: number; reason: string }[] }>(runPath(id, `/jobs/preflight?structure=${encodeURIComponent(structure)}`)),
  jobs: (id: string) => request<OpenmmJob[]>(runPath(id, "/jobs")),
  job: (id: string, jobId: string) => request<OpenmmJob>(runPath(id, `/jobs/${encodeURIComponent(jobId)}`)),
  submitOpenmm: (id: string, structure: string) => request<OpenmmSubmission>(runPath(id, "/jobs"), {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ protocol_id: "openmm_protein_minimize", args: { structure, selection_policy: "protein_only", hydrogen_policy: "rebuild_pH7" }, timeout_s: 60 }),
  }),
  startJob: (id: string, jobId: string) => request<OpenmmJob>(runPath(id, `/jobs/${encodeURIComponent(jobId)}/start`), { method: "POST" }),
  retryJob: (id: string, jobId: string) => request<OpenmmJob>(runPath(id, `/jobs/${encodeURIComponent(jobId)}/retry`), { method: "POST" }),
  approveOpenmm: (id: string) => request<{ approved: boolean }>(runPath(id, "/jobs/approve"), { method: "POST" }),
  cancelJob: (id: string, jobId: string) => request<{ status: string; job: OpenmmJob }>(runPath(id, `/jobs/${encodeURIComponent(jobId)}/cancel`), { method: "POST" }),
  openmm: (id: string, handle: string) => request<{ meta: ObjectMeta; result: OpenmmResult }>(runPath(id, `/openmm_minimization?${handleParam(handle)}`)),
  sasa: (id: string, handle: string) => request<{ meta: ObjectMeta; result: SasaResult }>(runPath(id, `/interface_sasa?${handleParam(handle)}`)),
  reports: (id: string) => request<SavedReportRef[]>(runPath(id, "/reports")),
  report: (id: string, handle: string) => request<ReportArtifact>(runPath(id, `/reports/selected?${handleParam(handle)}`)),
  createReport: (id: string, interactionHandle: string) => request<ReportArtifact>(runPath(id, "/reports"), {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ interaction_handle: interactionHandle }),
  }),
  openmmReport: (id: string, handle: string) => request<OpenmmReportArtifact>(runPath(id, `/reports/selected?${handleParam(handle)}`)),
  methodReport: (id: string, handle: string) => request<MethodReportArtifact>(runPath(id, `/reports/selected?${handleParam(handle)}`)),
  createOpenmmReport: (id: string, resultHandle: string) => request<OpenmmReportArtifact>(runPath(id, "/method_reports"), {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ result_handle: resultHandle }),
  }),
  createMethodReport: (id: string, resultHandle: string) => request<MethodReportArtifact>(runPath(id, "/method_reports"), {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ result_handle: resultHandle }),
  }),
  reportDownload: (id: string, handle: string, format: "markdown" | "json") =>
    `/api${runPath(id, `/reports/download?${handleParam(handle)}&format=${format}`)}`,
  async structure(id: string, handle: string): Promise<ViewerSource> {
    const response = await fetch(`/api${runPath(id, `/structures/bytes?${handleParam(handle)}`)}`, { cache: "no-store" });
    if (!response.ok) throw new ApiError(response.status, `구조 바이트 요청 실패: HTTP ${response.status}`);
    const rawFormat = response.headers.get("X-Structure-Format");
    if (rawFormat !== "pdb" && rawFormat !== "cif" && rawFormat !== "mmcif") throw new ApiError(500, "구조 형식 헤더가 없습니다.");
    return { handle, text: await response.text(), format: rawFormat === "pdb" ? "pdb" : "mmcif", modelIndex: 0 };
  },
};
