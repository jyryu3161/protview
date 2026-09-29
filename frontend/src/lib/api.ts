/** Loopback-only M1 API client. See docs/M1_API.md. */
import type { AnalysisAction, AnalysisEnvelope, AnalysisExecution, AnalysisExecutionList, AnalysisGoal, AnalysisPlanList,
  AnalysisPlanRecord, AnalysisSummary, AnalysisTemplates, AnalysisWorkflowsCapability, BudgetSnapshot, EgressMode, Handle,
  InteractionRow, ResidueRef, RunEvent, ToolError } from "./contracts";
import type { ViewerSource } from "@/components/MolstarViewer";
import type { ViewerIntent, ViewerOnlineStatus, ViewerSession, ViewerRepresentationValue } from "./viewer-agent";
import type { NativeSceneState, SavedFigureDetail, SavedPage, SavedSceneDetail } from "./saved-scene";
import type { AtomCatalog, AtomRefV1, MeasurementResult } from "./comparison";
import type { ChemicalCapability, ChemicalImport, ChemicalInspect, ChemicalJob,
  ChemicalPreparationManifest, ChemicalPrepareArgs, ChemicalPreview, ChemicalResult, ChemicalResultPage,
  ChemicalView } from "./chemical";
import type { PocketCapability, PocketGeometry, PocketJob, PocketPreflight, PocketReportArtifact, PocketSetList,
  PocketSummary } from "./pockets";

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
    engine_version?: string; unit?: string; limitations?: string; explanation?: string };
    chemical_interactions?: ChemicalCapability; pocket_detection?: PocketCapability;
    analysis_workflows?: AnalysisWorkflowsCapability } }
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
  schema: "method_report_manifest@1";
  analysis_type: "interface_sasa" | "atom_distance" | "rigid_alignment" | "chemical_interactions" | "pocket_detection";
  result_handle: string;
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
  constructor(public status: number, message: string, public code?: string,
    public approval?: { gate: string; tool: string; reason: string },
    /** Typed error detail of the JSON body (e.g. M13 `revision`, `retryable_step`); never used for science. */
    public detail?: Record<string, unknown>) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { cache: "no-store", ...init });
  if (!response.ok) {
    let data: { detail?: { message?: string; error?: string;
      approval?: { gate: string; tool: string; reason: string } } | string;
      message?: string; error?: string;
      approval?: { gate: string; tool: string; reason: string } } = {};
    try { data = await response.json(); } catch { /* non-JSON server failure */ }
    const detail = typeof data.detail === "object" ? data.detail : undefined;
    const approval = detail?.approval ?? data.approval;
    throw new ApiError(response.status,
      detail?.message ?? data.message ?? approval?.reason ?? (typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`),
      detail?.error ?? data.error, approval, detail as Record<string, unknown> | undefined);
  }
  return response.json() as Promise<T>;
}

function runPath(runId: string, tail = "") { return `/runs/${encodeURIComponent(runId)}${tail}`; }
function analysisPath(runId: string, executionId: string, tail = "") {
  return runPath(runId, `/analysis/executions/${encodeURIComponent(executionId)}${tail}`);
}
const ANALYSIS_ACTION_PATH: Record<AnalysisAction, string> = { approve: "/approve", revoke: "/revoke", advance: "/advance",
  retry: "/retry", cancel: "/cancel", scientific_approval: "/scientific-approval" };
const jsonPost = (body: unknown, signal?: AbortSignal): RequestInit =>
  ({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal });
function handleParam(handle: string) { return `handle=${encodeURIComponent(handle)}`; }

export const api = {
  chemicalImport: (id: string, kind: ChemicalImport["kind"], file: File, signal?: AbortSignal) =>
    request<ChemicalImport>(runPath(id, `/chemical/imports?kind=${kind}&filename=${encodeURIComponent(file.name)}`),
      { method: "POST", headers: { "content-type": "application/octet-stream" }, body: file, signal }),
  chemicalInspect: (id: string, handle: string, signal?: AbortSignal) =>
    request<ChemicalInspect>(runPath(id, `/chemical/imports/inspect?${handleParam(handle)}`), { signal }),
  async chemicalStagingAtoms(id: string, handle: string, modelNumber: number, signal?: AbortSignal) {
    const limit = 1000;
    const path = (offset: number) => runPath(id, `/chemical/imports/atoms?${handleParam(handle)}&model_number=${modelNumber}&offset=${offset}&limit=${limit}`);
    const first = await request<{ schema: "chemical_staging_atom_page@1"; input_handle: string;
      model_number: number; total: number; offset: number; limit: number;
      rows: { ref: AtomRefV1; coordinate_A: number[]; element: string; water: boolean }[] }>(path(0), { signal });
    if (first.schema !== "chemical_staging_atom_page@1" || first.input_handle !== handle ||
        first.model_number !== modelNumber || first.offset !== 0 || first.limit !== limit ||
        !Number.isInteger(first.total) || first.total < 1 || first.total > 10000)
      throw new Error("수용체 원자 목록의 첫 페이지 출처·크기가 다릅니다.");
    const rows = [...first.rows];
    const check = (page: typeof first, offset: number) => {
      if (page.schema !== "chemical_staging_atom_page@1" || page.input_handle !== handle ||
          page.model_number !== modelNumber || page.total !== first.total ||
          page.offset !== offset || page.limit !== limit ||
          page.rows.length !== Math.min(limit, first.total - offset) ||
          page.rows.some(row => row.ref.structure_handle !== handle ||
            row.ref.residue.model_number !== modelNumber || !Number.isInteger(row.ref.site_index) ||
            row.ref.site_index < 0 || row.ref.site_index >= first.total || row.coordinate_A.length !== 3 ||
            !row.coordinate_A.every(Number.isFinite)))
        throw new Error("수용체 원자 목록의 페이지 출처·원자 좌표가 다릅니다.");
    };
    check(first, 0);
    while (rows.length < first.total) {
      const next = await request<typeof first>(path(rows.length), { signal });
      check(next, rows.length);
      rows.push(...next.rows);
    }
    if (new Set(rows.map(row => row.ref.site_index)).size !== first.total ||
        new Set(rows.map(row => JSON.stringify(row.ref))).size !== first.total)
      throw new Error("수용체 원자 목록의 출처 또는 site가 다릅니다.");
    return rows;
  },
  chemicalPreview: (id: string, args: ChemicalPrepareArgs, signal?: AbortSignal) =>
    request<ChemicalPreview>(runPath(id, "/chemical/preview"), {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(args), signal }),
  chemicalPrepareJob: (id: string, args: ChemicalPrepareArgs) =>
    request<ChemicalJob>(runPath(id, "/jobs"), { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ protocol_id: "prolif_prepare_v1", args, timeout_s: 120 }) }),
  chemicalDetectJob: (id: string, graph: string) =>
    request<ChemicalJob>(runPath(id, "/jobs"), { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ protocol_id: "prolif_detect_v1", args: { schema: "chemical_detect_request@1",
        graph_handle: graph, categories: ["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"] }, timeout_s: 120 }) }),
  chemicalView: (id: string, handle: string, signal?: AbortSignal) =>
    request<ChemicalView>(runPath(id, `/chemical/structures/view?${handleParam(handle)}`), { signal }),
  chemicalPreparationManifest: (id: string, sourceHandle: string, signal?: AbortSignal) =>
    request<{ meta: ObjectMeta; manifest: ChemicalPreparationManifest }>(
      runPath(id, `/chemical/preparation-manifests?source_handle=${encodeURIComponent(sourceHandle)}`), { signal }),
  chemicalAtoms: (id: string, handle: string, offset = 0, limit = 1000, signal?: AbortSignal) =>
    request<AtomCatalog>(runPath(id, `/chemical/structures/atoms?${handleParam(handle)}&offset=${offset}&limit=${limit}`), { signal }),
  chemicalGraph: (id: string, handle: string, signal?: AbortSignal) =>
    request<{ meta: ObjectMeta; graph: Record<string, unknown> }>(runPath(id, `/chemical/graphs?${handleParam(handle)}`), { signal }),
  chemicalResult: (id: string, handle: string, signal?: AbortSignal) =>
    request<{ meta: ObjectMeta; result: ChemicalResult }>(runPath(id, `/chemical/results?${handleParam(handle)}`), { signal }),
  chemicalRows: (id: string, handle: string, offset: number, category: string, limit = 50, signal?: AbortSignal) =>
    request<ChemicalResultPage>(runPath(id, `/chemical/results/rows?${handleParam(handle)}&offset=${offset}&limit=${limit}${category ? `&category=${encodeURIComponent(category)}` : ""}`), { signal }),
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
  command: (id: string, tool: "load_structure" | "prepare_structure" | "compute_interactions" | "compute_interface_sasa" | "measure_distance" | "align_structures", args: Record<string, unknown>, signal?: AbortSignal) =>
    request<CommandResult>(runPath(id, "/commands"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ tool, args, decided_by: "human", execution_mode: "human" }), signal }),
  events: (id: string, after = 0, limit = 500, signal?: AbortSignal) => request<RunEvent[]>(runPath(id, `/events?after=${after}&limit=${limit}`), { signal }),
  async allEvents(id: string, signal?: AbortSignal): Promise<RunEvent[]> {
    const all: RunEvent[] = [];
    for (;;) {
      const page = await api.events(id, all.at(-1)?.seq ?? 0, 500, signal);
      all.push(...page);
      if (page.length < 500) return all;
    }
  },
  budget: (id: string) => request<BudgetSnapshot>(runPath(id, "/budget")),
  meta: (id: string, handle: string) => request<ObjectMeta>(runPath(id, `/objects/meta?${handleParam(handle)}`)),
  residues: (id: string, handle: string) => request<ResidueList>(runPath(id, `/structures/residues?${handleParam(handle)}`)),
  atoms: (id: string, handle: string, offset = 0, limit = 500, signal?: AbortSignal) =>
    request<AtomCatalog>(runPath(id, `/structures/atoms?${handleParam(handle)}&offset=${offset}&limit=${limit}`), { signal }),
  async allAtoms(id: string, handle: string, signal?: AbortSignal): Promise<AtomCatalog> {
    const first = await api.atoms(id, handle, 0, 500, signal);
    const rows = [...first.rows];
    while (rows.length < first.total) {
      const next = await api.atoms(id, handle, rows.length, 500, signal);
      if (next.viewer_source_sha256 !== first.viewer_source_sha256 || next.structure_handle !== handle ||
          next.offset !== rows.length || !next.rows.length) throw new Error("원자 목록이 읽는 동안 변경되었습니다.");
      rows.push(...next.rows);
    }
    return { ...first, rows };
  },
  measurement: (id: string, handle: string, signal?: AbortSignal) =>
    request<{ meta: ObjectMeta; result: MeasurementResult }>(runPath(id, `/objects/measurement?${handleParam(handle)}`), { signal }),
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
  reports: (id: string, signal?: AbortSignal) => request<SavedReportRef[]>(runPath(id, "/reports"), { signal }),
  report: (id: string, handle: string) => request<ReportArtifact>(runPath(id, `/reports/selected?${handleParam(handle)}`)),
  createReport: (id: string, interactionHandle: string) => request<ReportArtifact>(runPath(id, "/reports"), {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ interaction_handle: interactionHandle }),
  }),
  openmmReport: (id: string, handle: string) => request<OpenmmReportArtifact>(runPath(id, `/reports/selected?${handleParam(handle)}`)),
  methodReport: (id: string, handle: string, signal?: AbortSignal) => request<MethodReportArtifact>(runPath(id, `/reports/selected?${handleParam(handle)}`), { signal }),
  createOpenmmReport: (id: string, resultHandle: string) => request<OpenmmReportArtifact>(runPath(id, "/method_reports"), {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ result_handle: resultHandle }),
  }),
  createMethodReport: (id: string, resultHandle: string, signal?: AbortSignal) => request<MethodReportArtifact>(runPath(id, "/method_reports"), {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ result_handle: resultHandle }), signal,
  }),
  pocketPreflight: (id: string, structure: string, chains: string[], signal?: AbortSignal) =>
    request<PocketPreflight>(runPath(id, `/pockets/preflight?structure=${encodeURIComponent(structure)}${
      chains.map(chain => `&chains=${encodeURIComponent(chain)}`).join("")}`), { signal }),
  pocketSets: (id: string, offset = 0, limit = 100, signal?: AbortSignal) =>
    request<PocketSetList>(runPath(id, `/pockets?offset=${offset}&limit=${limit}`), { signal }),
  /** Every stored pocket_set of the run, read page by page (the route returns at most 100 rows per page). */
  async allPocketSets(id: string, signal?: AbortSignal): Promise<PocketSetList> {
    const first = await api.pocketSets(id, 0, 100, signal);
    const rows = [...first.rows];
    while (rows.length < first.total) {
      const page = await api.pocketSets(id, rows.length, 100, signal);
      if (page.schema !== first.schema || page.total !== first.total || !page.rows.length)
        throw new Error("포켓 결과 목록이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
      rows.push(...page.rows);
    }
    return { ...first, offset: 0, limit: rows.length, rows };
  },
  pocketResult: (id: string, handle: string, signal?: AbortSignal) =>
    request<PocketSummary>(runPath(id, `/pockets/result?${handleParam(handle)}`), { signal }),
  pocketGeometry: (id: string, handle: string, rank: number, signal?: AbortSignal) =>
    request<PocketGeometry>(runPath(id, `/pockets/geometry?${handleParam(handle)}&rank=${rank}`), { signal }),
  /** chains: [] means every protein chain of the source (the server resolves the default into the call key). */
  submitPockets: (id: string, structure: string, chains: string[]) => request<PocketJob>(runPath(id, "/jobs"), {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ protocol_id: "fpocket_detect_v1", args: { structure, chains }, timeout_s: 120 }) }),
  pocketJob: (id: string, jobId: string, signal?: AbortSignal) =>
    request<PocketJob>(runPath(id, `/jobs/${encodeURIComponent(jobId)}`), { signal }),
  pocketJobs: (id: string, signal?: AbortSignal) => request<PocketJob[]>(runPath(id, "/jobs"), { signal }),
  createPocketReport: (id: string, setHandle: string, signal?: AbortSignal) =>
    request<PocketReportArtifact>(runPath(id, "/method_reports"), { method: "POST",
      headers: { "content-type": "application/json" }, body: JSON.stringify({ result_handle: setHandle }), signal }),
  pocketReport: (id: string, handle: string, signal?: AbortSignal) =>
    request<PocketReportArtifact>(runPath(id, `/reports/selected?${handleParam(handle)}`), { signal }),
  // ---- M13 analysis workflows (loopback only; reads never run a tool, job or report) ----
  analysisTemplates: (id: string, signal?: AbortSignal) =>
    request<AnalysisTemplates>(runPath(id, "/analysis/templates"), { signal }),
  analysisPlans: (id: string, signal?: AbortSignal) => request<AnalysisPlanList>(runPath(id, "/analysis/plans"), { signal }),
  analysisPlan: (id: string, handle: string, signal?: AbortSignal) =>
    request<AnalysisPlanRecord>(runPath(id, `/analysis/plans/detail?${handleParam(handle)}`), { signal }),
  createAnalysisPlan: (id: string, body: { request_id: string; goal: AnalysisGoal; inputs: Record<string, unknown> },
    signal?: AbortSignal) => request<AnalysisPlanRecord>(runPath(id, "/analysis/plans"), jsonPost(body, signal)),
  analysisExecutions: (id: string, signal?: AbortSignal) =>
    request<AnalysisExecutionList>(runPath(id, "/analysis/executions"), { signal }),
  analysisExecution: (id: string, executionId: string, signal?: AbortSignal) =>
    request<AnalysisExecution>(analysisPath(id, executionId), { signal }),
  createAnalysisExecution: (id: string, body: { request_id: string; plan_handle: string }, signal?: AbortSignal) =>
    request<AnalysisEnvelope>(runPath(id, "/analysis/executions"), jsonPost(body, signal)),
  analysisAction: (id: string, executionId: string, action: AnalysisAction,
    body: { request_id: string; expected_revision: number; plan_hash?: string; step_id?: string }, signal?: AbortSignal) =>
    request<AnalysisEnvelope>(analysisPath(id, executionId, ANALYSIS_ACTION_PATH[action]), jsonPost(body, signal)),
  analysisSummary: (id: string, executionId: string, signal?: AbortSignal) =>
    request<AnalysisSummary>(analysisPath(id, executionId, "/summary"), { signal }),
  analysisSummaryDownload: (id: string, executionId: string) => `/api${analysisPath(id, executionId, "/summary?download=json")}`,
  reportDownload: (id: string, handle: string, format: "markdown" | "json") =>
    `/api${runPath(id, `/reports/download?${handleParam(handle)}&format=${format}`)}`,
  async structure(id: string, handle: string, signal?: AbortSignal): Promise<ViewerSource> {
    const response = await fetch(`/api${runPath(id, `/structures/bytes?${handleParam(handle)}`)}`, { cache: "no-store", signal });
    if (!response.ok) throw new ApiError(response.status, `구조 바이트 요청 실패: HTTP ${response.status}`);
    const rawFormat = response.headers.get("X-Structure-Format");
    if (rawFormat !== "pdb" && rawFormat !== "cif" && rawFormat !== "mmcif") throw new ApiError(500, "구조 형식 헤더가 없습니다.");
    return { handle, text: await response.text(), format: rawFormat === "pdb" ? "pdb" : "mmcif", modelIndex: 0 };
  },
};
