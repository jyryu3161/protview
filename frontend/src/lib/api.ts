/** Loopback-only M1 API client. See docs/M1_API.md. */
import type { AnalysisAction, AnalysisEnvelope, AnalysisExecution, AnalysisExecutionList, AnalysisGoal, AnalysisPlanList,
  AnalysisPlanRecord, AnalysisSummary, AnalysisTemplates, AnalysisWorkflowsCapability, BudgetSnapshot, DockingArgs,
  DockingBatchArgs, DockingBatchCapability, DockingBatchDetail, DockingBatchJob, DockingBatchLimitApproval,
  DockingBatchList, DockingBatchPreflight, DockingBatchReportArtifact, DockingBatchSubmission,
  LigandGaArgs, LigandGaCapability, LigandGaDetail, LigandGaIndividualRead, LigandGaJob, LigandGaLimitApproval,
  LigandGaList, LigandGaPreflight, LigandGaReportArtifact, LigandGaSubmission,
  DockingCapability, DockingContactPage, DockingJob, DockingPrerequisites, DockingReceptorInstances,
  DockingReportArtifact, DockingResultDetail, DockingResultList, DockingSubmission, EgressMode, Handle,
  InteractionRow, JevPreviewV1, JevProjectionArgs, JevReportArtifact, JevSendDetail, JevSendRequest, JevSendV1,
  JevStatusV1, LigandCandidatePage, LigandCandidateSetDetail, LigandCandidateSetList, LigandCapability,
  LigandEnumerateArgs, LigandFilterSpec, LigandImport, LigandImportKind, LigandInspectArgs, LigandInspectionDetail,
  LigandInspectionList, LigandJob, LigandPrerequisites, LigandReportArtifact, LigandSitePreview, LigandSubmission,
  MutationCandidatePage, MutationCandidateSetDetail, MutationCandidateSetList, MutationPositionPage,
  MutationModelArgs, MutationModelCapability, MutationModelContactPage, MutationModelDetail, MutationModelDockingPairs,
  MutationModelJob, MutationModelList, MutationModelReportArtifact, MutationModelSide, MutationModelSubmission,
  DockingSourceArgs, MutationReportArtifact, MutationRequestArgs, ReferenceSiteAnnotation, ResidueRef, RunEvent, SceneAnnotationRef, SiteAnnotationList,
  SequenceGaArgs, SequenceGaCapability, SequenceGaDetail, SequenceGaIndividualRead, SequenceGaJob,
  SequenceGaLimitApproval, SequenceGaList, SequenceGaPreflight, SequenceGaReportArtifact, SequenceGaSubmission,
  ToolError, JevLoopAbandonRequest, JevLoopCapability, JevLoopComputeRequest, JevLoopCreateRequest, JevLoopListRow,
  JevLoopProjectionArgs, JevLoopReportArtifact, JevLoopV1, ReactionKnowledgeArgs, ReactionKnowledgeCapability,
  ReactionKnowledgeDetail, ReactionKnowledgeList, ReactionKnowledgeReportArtifact, ReactionPdbEntries,
  ReactionReferenceStatus } from "./contracts";
import type { ViewerSource } from "@/components/MolstarViewer";
import type { ViewerIntent, ViewerOnlineStatus, ViewerSession, ViewerRepresentationValue } from "./viewer-agent";
import type { NativeSceneState, SavedFigureDetail, SavedPage, SavedSceneDetail } from "./saved-scene";
import type { AtomCatalog, AtomRefV1, MeasurementResult } from "./comparison";
import type { ChemicalCapability, ChemicalImport, ChemicalInspect, ChemicalJob,
  ChemicalPreparationManifest, ChemicalPrepareArgs, ChemicalPreview, ChemicalResult, ChemicalResultPage,
  ChemicalView } from "./chemical";
import type { PocketCapability, PocketGeometry, PocketJob, PocketPreflight, PocketReportArtifact, PocketSetList,
  PocketSummary } from "./pockets";
import type { NumberingMapList, NumberingRow, PdbIdHint, ReferenceSnapshots, SiftsChains,
  UniprotSearch } from "./numbering";

/** Fixed `POST /jobs` time limit of a docking job (spec 4.1/5.1: not a job argument, not shown on screen). */
export const DOCKING_TIMEOUT_S = 600;
/** Fixed `POST /jobs` time limit of a batch docking job (the protocol's own maximum, spec 4.2/7.1; not shown). */
export const DOCKING_BATCH_TIMEOUT_S = 7800;
/** `POST /jobs` time limit of a GA job = `ga.total_s` + this finishing margin (M22 spec 2; the screen always sends it). */
export const LIGAND_GA_FINISH_MARGIN_S = 600;
/** `POST /jobs` time limit of a sequence GA job = `ga.total_s` + this finishing margin (M23 spec 2; always sent). */
export const SEQUENCE_GA_FINISH_MARGIN_S = 600;

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
    analysis_workflows?: AnalysisWorkflowsCapability;
    residue_numbering?: { available: boolean; reason_code: string | null; reason: string | null; set_hash: string | null };
    reference_site_annotation?: { available: boolean; reason_code: string | null; reason: string | null };
    ligand_candidates?: LigandCapability; ligand_docking?: DockingCapability;
    ligand_docking_batch?: DockingBatchCapability;
    ligand_ga_design?: LigandGaCapability;
    mutation_candidates?: { available: boolean; reason_code: string | null; reason: string | null };
    mutation_model?: MutationModelCapability;
    sequence_ga_design?: SequenceGaCapability;
    /** M24: local conditions only (projection tool, model pins); no key and no run consent is read. */
    jev_choice?: { available: boolean; reason_code: string | null; reason: string | null };
    /** M25: per branch (projection tool, science pins, then the branch's engines); reasons only. */
    jev_loop?: JevLoopCapability;
    /** M26: the pinned + decoded local reaction reference set (no network); same five keys as residue_numbering. */
    reaction_knowledge?: ReactionKnowledgeCapability } }
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
  analysis_type: "interface_sasa" | "atom_distance" | "rigid_alignment" | "chemical_interactions" | "pocket_detection"
    | "residue_numbering" | "reference_site_annotation" | "ligand_candidates" | "ligand_docking" | "ligand_docking_batch"
    | "mutation_candidates" | "jev_choice" | "reaction_knowledge";
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

/** M16 `GET /runs/{id}/site_annotations/detail`: the stored annotation as written by the tool. */
export interface SiteAnnotationDetail { meta: ObjectMeta; annotation: ReferenceSiteAnnotation }
type SceneSaveBase = SceneBindingRequest & NativeSceneState & { name: string };
/** `viewer_scene@1` (annotation off, unchanged) or `viewer_scene@2` (annotation shown). */
export type SceneSaveBody = (SceneSaveBase & { schema: "viewer_scene@1" }) |
  (SceneSaveBase & { schema: "viewer_scene@2"; annotation: SceneAnnotationRef });
type FigureSaveBase = SceneBindingRequest & NativeSceneState & { scene_handle: string; png_base64: string };
/** The figure schema must match its scene's schema (server: 409 scene_mismatch otherwise). */
export type FigureSaveBody = (FigureSaveBase & { schema: "viewer_figure@1" }) |
  (FigureSaveBase & { schema: "viewer_figure@2"; legend_composited: boolean });

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
  saveScene: (id: string, body: SceneSaveBody) =>
    request<SavedSceneDetail>(runPath(id, "/viewer/scenes"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  savedFigures: (id: string, offset = 0) => request<SavedPage<SavedFigureDetail>>(runPath(id, `/viewer/figures?offset=${offset}&limit=50`)),
  savedFigure: (id: string, handle: string) => request<SavedFigureDetail>(runPath(id, `/viewer/figures/selected?${handleParam(handle)}`)),
  saveFigure: (id: string, body: FigureSaveBody) => request<SavedFigureDetail>(runPath(id, "/viewer/figures"),
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
  command: (id: string, tool: "load_structure" | "prepare_structure" | "compute_interactions" | "compute_interface_sasa" | "measure_distance" | "align_structures" | "map_residue_numbering" | "annotate_reference_sites" | "generate_mutation_candidates" | "build_jev_projection" | "build_jev_loop_projection" | "link_reaction_knowledge", args: Record<string, unknown>, signal?: AbortSignal) =>
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
  referenceSnapshots: (signal?: AbortSignal) => request<ReferenceSnapshots>("/reference/snapshots", { signal }),
  siftsChains: (pdbId: string, signal?: AbortSignal) =>
    request<SiftsChains>(`/reference/sifts_chains?pdb_id=${encodeURIComponent(pdbId)}`, { signal }),
  uniprotSearch: (query: string, offset = 0, limit = 20, signal?: AbortSignal) =>
    request<UniprotSearch>(`/reference/uniprot?query=${encodeURIComponent(query)}&offset=${offset}&limit=${limit}`, { signal }),
  pdbIdHint: (id: string, structure: string, signal?: AbortSignal) =>
    request<PdbIdHint>(runPath(id, `/reference/pdb_id_hint?structure=${encodeURIComponent(structure)}`), { signal }),
  numberingMaps: (id: string, offset = 0, limit = 100, signal?: AbortSignal) =>
    request<NumberingMapList>(runPath(id, `/numbering_maps?offset=${offset}&limit=${limit}`), { signal }),
  numberingRows: (id: string, handle: string, offset: number, limit: number, signal?: AbortSignal) =>
    request<Page<NumberingRow>>(runPath(id, `/objects?${handleParam(handle)}&offset=${offset}&limit=${limit}`), { signal }),
  // ---- M16 reference site annotations (reads write no event and run no tool) ----
  /** Runs `annotate_reference_sites` through the ordinary Run.call command route. `contacts: null` = no contacts. */
  annotateReferenceSites: (id: string, numberingMap: string, contacts: string | null, signal?: AbortSignal) =>
    api.command(id, "annotate_reference_sites", { numbering_map: numberingMap, contacts }, signal),
  siteAnnotations: (id: string, structure: string | null, offset = 0, limit = 100, signal?: AbortSignal) =>
    request<SiteAnnotationList>(runPath(id, `/site_annotations?${structure === null ? ""
      : `structure=${encodeURIComponent(structure)}&`}offset=${offset}&limit=${limit}`), { signal }),
  siteAnnotation: (id: string, handle: string, signal?: AbortSignal) =>
    request<SiteAnnotationDetail>(runPath(id, `/site_annotations/detail?${handleParam(handle)}`), { signal }),
  /** Method report `analysis_type: "reference_site_annotation"` of one stored annotation (nothing recomputed). */
  createSiteAnnotationReport: (id: string, annotationHandle: string, signal?: AbortSignal) =>
    api.createMethodReport(id, annotationHandle, signal),
  // ---- M17 ligand candidates (reads and the preview write no event and start no job) ----
  /** Parent SDF (`ligand_sdf`, the M11 kind) or a building-block library; octet-stream, at most 10 MiB. */
  ligandImport: (id: string, kind: LigandImportKind, file: File, signal?: AbortSignal) =>
    request<LigandImport>(runPath(id, `/chemical/imports?kind=${kind}&filename=${encodeURIComponent(file.name)}`),
      { method: "POST", headers: { "content-type": "application/octet-stream" }, body: file, signal }),
  ligandPrerequisites: (id: string, signal?: AbortSignal) =>
    request<LigandPrerequisites>(runPath(id, "/ligand/prerequisites"), { signal }),
  ligandInspections: (id: string, offset = 0, limit = 100, signal?: AbortSignal) =>
    request<LigandInspectionList>(runPath(id, `/ligand/inspections?offset=${offset}&limit=${limit}`), { signal }),
  ligandInspection: (id: string, handle: string, signal?: AbortSignal) =>
    request<LigandInspectionDetail>(runPath(id, `/ligand/inspections/detail?${handleParam(handle)}`), { signal }),
  /** `inspection` null = every candidate set of the run. */
  ligandCandidateSets: (id: string, inspection: string | null, offset = 0, limit = 100, signal?: AbortSignal) =>
    request<LigandCandidateSetList>(runPath(id, `/ligand/candidate_sets?${inspection === null ? ""
      : `inspection=${encodeURIComponent(inspection)}&`}offset=${offset}&limit=${limit}`), { signal }),
  ligandCandidateSet: (id: string, handle: string, signal?: AbortSignal) =>
    request<LigandCandidateSetDetail>(runPath(id, `/ligand/candidate_sets/detail?${handleParam(handle)}`), { signal }),
  /** `query` comes from `candidateRowsQuery` (ligand.ts); the server evaluates filters on stored values. */
  ligandCandidateRows: (id: string, query: string, signal?: AbortSignal) =>
    request<LigandCandidatePage>(runPath(id, `/ligand/candidate_sets/rows?${query}`), { signal }),
  ligandPreview: (id: string, body: LigandEnumerateArgs, signal?: AbortSignal) =>
    request<LigandSitePreview>(runPath(id, "/ligand/preview"), jsonPost(body, signal)),
  /** Start, approval (`approveOpenmm`), retry and cancel use the shared job routes (`startJob` etc.). */
  submitLigandInspect: (id: string, args: LigandInspectArgs) =>
    request<LigandSubmission>(runPath(id, "/jobs"), jsonPost({ protocol_id: "rdkit_inspect_v1", args, timeout_s: 120 })),
  submitLigandEnumerate: (id: string, args: LigandEnumerateArgs) =>
    request<LigandSubmission>(runPath(id, "/jobs"), jsonPost({ protocol_id: "rdkit_enumerate_v1", args, timeout_s: 120 })),
  ligandJob: (id: string, jobId: string, signal?: AbortSignal) =>
    request<LigandJob>(runPath(id, `/jobs/${encodeURIComponent(jobId)}`), { signal }),
  /** Every job of the run (read only); the ligand tab re-attaches to its own queued or running job after a remount. */
  ligandJobs: (id: string, signal?: AbortSignal) => request<LigandJob[]>(runPath(id, "/jobs"), { signal }),
  /** Report of one stored candidate set; `filters` null sends no filter spec (nothing is generated again). */
  createLigandReport: (id: string, setHandle: string, filters: LigandFilterSpec | null, signal?: AbortSignal) =>
    request<LigandReportArtifact>(runPath(id, "/method_reports"),
      jsonPost(filters === null ? { result_handle: setHandle } : { result_handle: setHandle, filters }, signal)),
  // ---- M18 ligand docking (reads write no event and start no job; imports reuse `chemicalImport`) ----
  dockingPrerequisites: (id: string, signal?: AbortSignal) =>
    request<DockingPrerequisites>(runPath(id, "/docking/prerequisites"), { signal }),
  /** Nonstandard residue instances of one receptor import (a selection aid; admission checks the choice again). */
  dockingReceptorInstances: (id: string, receptorHandle: string, signal?: AbortSignal) =>
    request<DockingReceptorInstances>(runPath(id, `/docking/receptor_instances?${handleParam(receptorHandle)}`),
      { signal }),
  /** Start, approval (`approveOpenmm`), retry and cancel use the shared job routes. `timeout_s` is fixed (not shown). */
  /** M21: also takes `receptor_source` arguments (same-condition docking on one side of a mutation model). */
  submitDocking: (id: string, args: DockingArgs | DockingSourceArgs) =>
    request<DockingSubmission>(runPath(id, "/jobs"), jsonPost({ protocol_id: "qvina_dock_v1", args,
      timeout_s: DOCKING_TIMEOUT_S })),
  dockingJob: (id: string, jobId: string, signal?: AbortSignal) =>
    request<DockingJob>(runPath(id, `/jobs/${encodeURIComponent(jobId)}`), { signal }),
  /** Every job of the run (read only); the docking area re-attaches to its own queued or running job. */
  dockingJobs: (id: string, signal?: AbortSignal) => request<DockingJob[]>(runPath(id, "/jobs"), { signal }),
  dockingResults: (id: string, offset = 0, limit = 100, signal?: AbortSignal) =>
    request<DockingResultList>(runPath(id, `/docking/results?offset=${offset}&limit=${limit}`), { signal }),
  dockingResult: (id: string, handle: string, signal?: AbortSignal) =>
    request<DockingResultDetail>(runPath(id, `/docking/results/detail?${handleParam(handle)}`), { signal }),
  dockingContacts: (id: string, handle: string, mode: number, offset = 0, limit = 100, signal?: AbortSignal) =>
    request<DockingContactPage>(runPath(id, `/docking/results/contacts?${handleParam(handle)}&mode=${mode}` +
      `&offset=${offset}&limit=${limit}`), { signal }),
  /** Stored pose SDF of one mode (one record). */
  dockingPoseSdfUrl: (id: string, handle: string, mode: number) =>
    `/api${runPath(id, `/docking/results/pose_sdf?${handleParam(handle)}&mode=${mode}`)}`,
  /** Stored pose SDF of every mode in one file (`$$$$` separated, titles `mode_<n>`). */
  dockingPosesSdfUrl: (id: string, handle: string) =>
    `/api${runPath(id, `/docking/results/poses_sdf?${handleParam(handle)}`)}`,
  /** Report `analysis_type: "ligand_docking"` of one stored docking result (nothing is docked again). */
  createDockingReport: (id: string, resultHandle: string, signal?: AbortSignal) =>
    request<DockingReportArtifact>(runPath(id, "/method_reports"), jsonPost({ result_handle: resultHandle }, signal)),
  // ---- M19 batch docking (preflight and list/detail are reads; start, approval and cancel use the job routes) ----
  /** Admission, reuse per row, N, need, remaining budget and shortfall for exactly these arguments (no event). */
  dockingBatchPreflight: (id: string, args: DockingBatchArgs, signal?: AbortSignal) =>
    request<DockingBatchPreflight>(runPath(id, "/docking/batches/preflight"), jsonPost(args, signal)),
  /** The person's explicit approval: the server raises each limit by this batch's current shortfall only. */
  dockingBatchLimitApproval: (id: string, args: DockingBatchArgs) =>
    request<DockingBatchLimitApproval>(runPath(id, "/docking/batches/limit_approval"), jsonPost(args)),
  submitDockingBatch: (id: string, args: DockingBatchArgs) =>
    request<DockingBatchSubmission>(runPath(id, "/jobs"), jsonPost({ protocol_id: "qvina_batch_dock_v1", args,
      timeout_s: DOCKING_BATCH_TIMEOUT_S })),
  /** Stored job record with `batch` progress (rows, reused rows, finished rows, summary handle). */
  dockingBatchJob: (id: string, jobId: string, signal?: AbortSignal) =>
    request<DockingBatchJob>(runPath(id, `/jobs/${encodeURIComponent(jobId)}`), { signal }),
  dockingBatchJobs: (id: string, signal?: AbortSignal) => request<DockingBatchJob[]>(runPath(id, "/jobs"), { signal }),
  dockingBatches: (id: string, offset = 0, limit = 100, signal?: AbortSignal) =>
    request<DockingBatchList>(runPath(id, `/docking/batches?offset=${offset}&limit=${limit}`), { signal }),
  dockingBatch: (id: string, handle: string, signal?: AbortSignal) =>
    request<DockingBatchDetail>(runPath(id, `/docking/batches/detail?${handleParam(handle)}`), { signal }),
  /** Report `analysis_type: "ligand_docking_batch"` of one stored batch summary (nothing is docked again). */
  createDockingBatchReport: (id: string, summaryHandle: string, signal?: AbortSignal) =>
    request<DockingBatchReportArtifact>(runPath(id, "/method_reports"), jsonPost({ result_handle: summaryHandle }, signal)),
  // ---- M22 ligand GA design (preflight, list, detail and individual are reads; the handle goes in the path) ----
  /** Admission, pool counts, reusable count, reserved units, need, remaining budget and shortfall (no event). */
  ligandGaPreflight: (id: string, args: LigandGaArgs, signal?: AbortSignal) =>
    request<LigandGaPreflight>(runPath(id, "/ligand/ga/preflight"), jsonPost(args, signal)),
  /** The person's explicit approval: the server raises each limit by this GA's current shortfall only. */
  ligandGaLimitApproval: (id: string, args: LigandGaArgs) =>
    request<LigandGaLimitApproval>(runPath(id, "/ligand/ga/limit_approval"), jsonPost(args)),
  submitLigandGa: (id: string, args: LigandGaArgs) =>
    request<LigandGaSubmission>(runPath(id, "/jobs"), jsonPost({ protocol_id: "qvina_ga_dock_v1", args,
      timeout_s: args.ga.total_s + LIGAND_GA_FINISH_MARGIN_S })),
  /** Stored job record with `ga` progress (staged file counts, summary handle). */
  ligandGaJob: (id: string, jobId: string, signal?: AbortSignal) =>
    request<LigandGaJob>(runPath(id, `/jobs/${encodeURIComponent(jobId)}`), { signal }),
  ligandGaJobs: (id: string, signal?: AbortSignal) => request<LigandGaJob[]>(runPath(id, "/jobs"), { signal }),
  /** Newest first; `limit` 1–100. */
  ligandGaResults: (id: string, offset = 0, limit = 100, signal?: AbortSignal) =>
    request<LigandGaList>(runPath(id, `/ligand/ga/results?offset=${offset}&limit=${limit}`), { signal }),
  ligandGaResult: (id: string, handle: string, signal?: AbortSignal) =>
    request<LigandGaDetail>(runPath(id, `/ligand/ga/results/${encodeURIComponent(handle)}`), { signal }),
  ligandGaIndividual: (id: string, handle: string, candidateId: string, signal?: AbortSignal) =>
    request<LigandGaIndividualRead>(runPath(id, `/ligand/ga/results/${encodeURIComponent(handle)}/individual` +
      `?candidate_id=${encodeURIComponent(candidateId)}`), { signal }),
  /** Report `analysis_type: "ligand_ga"` of one stored GA summary (nothing is docked again). */
  createLigandGaReport: (id: string, summaryHandle: string, signal?: AbortSignal) =>
    request<LigandGaReportArtifact>(runPath(id, "/method_reports"), jsonPost({ result_handle: summaryHandle }, signal)),
  // ---- M20 mutation candidates (reads write no event and run no tool; the handle goes in the path) ----
  /** Runs `generate_mutation_candidates` through the ordinary Run.call command route (no job, approval or budget). */
  generateMutationCandidates: (id: string, args: MutationRequestArgs, signal?: AbortSignal) =>
    api.command(id, "generate_mutation_candidates", args as unknown as Record<string, unknown>, signal),
  /** Newest first; `limit` 1–100. */
  mutationCandidateSets: (id: string, offset = 0, limit = 100, signal?: AbortSignal) =>
    request<MutationCandidateSetList>(runPath(id, `/mutation_candidate_sets?offset=${offset}&limit=${limit}`), { signal }),
  mutationCandidateSet: (id: string, handle: string, signal?: AbortSignal) =>
    request<MutationCandidateSetDetail>(runPath(id, `/mutation_candidate_sets/${encodeURIComponent(handle)}`), { signal }),
  /** `query` comes from `positionQuery` (mutations.ts); the server filters and sorts the stored rows. */
  mutationPositions: (id: string, handle: string, query: string, signal?: AbortSignal) =>
    request<MutationPositionPage>(runPath(id, `/mutation_candidate_sets/${encodeURIComponent(handle)}/positions?${query}`),
      { signal }),
  /** `query` comes from `candidateQuery` (mutations.ts). */
  mutationCandidates: (id: string, handle: string, query: string, signal?: AbortSignal) =>
    request<MutationCandidatePage>(runPath(id, `/mutation_candidate_sets/${encodeURIComponent(handle)}/candidates?${query}`),
      { signal }),
  /** Report `analysis_type: "mutation_candidates"` of one stored set (nothing is generated again). */
  createMutationReport: (id: string, setHandle: string, signal?: AbortSignal) =>
    request<MutationReportArtifact>(runPath(id, "/method_reports"), jsonPost({ result_handle: setHandle }, signal)),
  // ---- M21 mutation structure model (reads write no event and start no job; the handle goes in the path) ----
  /** Start, approval (`approveOpenmm`), retry and cancel use the shared job routes; `timeoutS` is the top-level
   * `POST /jobs` field (not an argument, not in the call key). */
  submitMutationModel: (id: string, args: MutationModelArgs, timeoutS: number) =>
    request<MutationModelSubmission>(runPath(id, "/jobs"), jsonPost({ protocol_id: "openmm_mutation_model_v1", args,
      timeout_s: timeoutS })),
  mutationModelJob: (id: string, jobId: string, signal?: AbortSignal) =>
    request<MutationModelJob>(runPath(id, `/jobs/${encodeURIComponent(jobId)}`), { signal }),
  /** Every job of the run (read only); the model area re-attaches to its own queued or running job. */
  mutationModelJobs: (id: string, signal?: AbortSignal) => request<MutationModelJob[]>(runPath(id, "/jobs"), { signal }),
  /** Newest first; `limit` 1–100. */
  mutationModels: (id: string, offset = 0, limit = 50, signal?: AbortSignal) =>
    request<MutationModelList>(runPath(id, `/mutation_models?offset=${offset}&limit=${limit}`), { signal }),
  mutationModel: (id: string, handle: string, signal?: AbortSignal) =>
    request<MutationModelDetail>(runPath(id, `/mutation_models/${encodeURIComponent(handle)}`), { signal }),
  /** `query` comes from `modelContactQuery` (mutation-model.ts): structure, page (1-based), page_size 1–200. */
  mutationModelContacts: (id: string, handle: string, query: string, signal?: AbortSignal) =>
    request<MutationModelContactPage>(runPath(id, `/mutation_models/${encodeURIComponent(handle)}/contacts?${query}`),
      { signal }),
  /** Stored mmCIF of one side, byte for byte (a link the person clicks; never fetched automatically). */
  mutationModelStructureUrl: (id: string, handle: string, side: MutationModelSide) =>
    `/api${runPath(id, `/mutation_models/${encodeURIComponent(handle)}/structure?side=${side}`)}`,
  mutationModelDockingPairs: (id: string, handle: string, signal?: AbortSignal) =>
    request<MutationModelDockingPairs>(runPath(id, `/mutation_models/${encodeURIComponent(handle)}/docking_pairs`),
      { signal }),
  /** Report `analysis_type: "mutation_model"` of one stored model (nothing is modelled again; no docking score). */
  createMutationModelReport: (id: string, modelHandle: string, signal?: AbortSignal) =>
    request<MutationModelReportArtifact>(runPath(id, "/method_reports"), jsonPost({ result_handle: modelHandle }, signal)),
  // ---- M23 sequence GA design (preflight, list, detail, individual and structure are reads; the handle goes in the
  // path; start, approval and cancel use the shared job routes) ----
  /** Admission, space, heavy atoms, reuse, reserved figures, need, remaining budget and shortfall (no event). */
  sequenceGaPreflight: (id: string, args: SequenceGaArgs, signal?: AbortSignal) =>
    request<SequenceGaPreflight>(runPath(id, "/sequence_ga/preflight"), jsonPost(args, signal)),
  /** The person's explicit approval: the server raises each limit by this GA's current shortfall only. */
  sequenceGaLimitApproval: (id: string, args: SequenceGaArgs) =>
    request<SequenceGaLimitApproval>(runPath(id, "/sequence_ga/limit_approval"), jsonPost(args)),
  submitSequenceGa: (id: string, args: SequenceGaArgs) =>
    request<SequenceGaSubmission>(runPath(id, "/jobs"), jsonPost({ protocol_id: "sequence_ga_dock_v1", args,
      timeout_s: args.ga.total_s + SEQUENCE_GA_FINISH_MARGIN_S })),
  /** Stored job record with `sequence_ga` progress (staged file counts, summary handle). */
  sequenceGaJob: (id: string, jobId: string, signal?: AbortSignal) =>
    request<SequenceGaJob>(runPath(id, `/jobs/${encodeURIComponent(jobId)}`), { signal }),
  sequenceGaJobs: (id: string, signal?: AbortSignal) => request<SequenceGaJob[]>(runPath(id, "/jobs"), { signal }),
  /** Newest first; `limit` 1–100. */
  sequenceGaResults: (id: string, offset = 0, limit = 100, signal?: AbortSignal) =>
    request<SequenceGaList>(runPath(id, `/sequence_ga/results?offset=${offset}&limit=${limit}`), { signal }),
  sequenceGaResult: (id: string, handle: string, signal?: AbortSignal) =>
    request<SequenceGaDetail>(runPath(id, `/sequence_ga/results/${encodeURIComponent(handle)}`), { signal }),
  /** One individual (`key` "12-57-203") or the wild-type reference row (`key` "wild_type"); keys only, never names. */
  sequenceGaIndividual: (id: string, handle: string, key: string, signal?: AbortSignal) =>
    request<SequenceGaIndividualRead>(runPath(id, `/sequence_ga/results/${encodeURIComponent(handle)}/individual` +
      `?key=${encodeURIComponent(key)}`), { signal }),
  /** Stored mmCIF of one row's model, byte for byte (a link the person clicks; never fetched automatically). */
  sequenceGaStructureUrl: (id: string, handle: string, key: string) =>
    `/api${runPath(id, `/sequence_ga/results/${encodeURIComponent(handle)}/structure?key=${encodeURIComponent(key)}`)}`,
  /** Report `analysis_type: "sequence_ga"` of one stored GA summary (nothing is modelled or docked again). */
  createSequenceGaReport: (id: string, summaryHandle: string, signal?: AbortSignal) =>
    request<SequenceGaReportArtifact>(runPath(id, "/method_reports"), jsonPost({ result_handle: summaryHandle }, signal)),
  // ---- M24 JEV science sends (status, preview and the send list/detail write no event and send nothing; the one
  // external send is `jevSend`, the person's approval of one exact preview body) ----
  /** Runs `build_jev_projection` through the ordinary Run.call command route (no job, approval or budget). */
  buildJevProjection: (id: string, args: JevProjectionArgs, signal?: AbortSignal) =>
    api.command(id, "build_jev_projection", args as unknown as Record<string, unknown>, signal),
  jevStatus: (id: string, signal?: AbortSignal) => request<JevStatusV1>(runPath(id, "/jev/status"), { signal }),
  /** The run-level science consent (412 `dry_run` when turning it on in a dry-run run). */
  jevSetConsent: (id: string, enabled: boolean, signal?: AbortSignal) =>
    request<JevStatusV1>(runPath(id, "/jev/consent"), jsonPost({ enabled }, signal)),
  jevPreview: (id: string, projection: string, signal?: AbortSignal) =>
    request<JevPreviewV1>(runPath(id, "/jev/preview"), jsonPost({ projection }, signal)),
  /** Approve and send one previewed body; refusals and failures also answer 200 with their `jev_send@1` record. */
  jevSend: (id: string, body: JevSendRequest, signal?: AbortSignal) =>
    request<JevSendV1>(runPath(id, "/jev/sends"), jsonPost(body, signal)),
  /** This run's sends, oldest first. */
  jevSends: (id: string, signal?: AbortSignal) => request<JevSendV1[]>(runPath(id, "/jev/sends"), { signal }),
  jevSendDetail: (id: string, sendId: string, signal?: AbortSignal) =>
    request<JevSendDetail>(runPath(id, `/jev/sends/${encodeURIComponent(sendId)}`), { signal }),
  /** Report `analysis_type: "jev_choice"` of one stored proposal (nothing is sent or chosen again). */
  createJevReport: (id: string, choiceHandle: string, signal?: AbortSignal) =>
    request<JevReportArtifact>(runPath(id, "/method_reports"), jsonPost({ result_handle: choiceHandle }, signal)),
  // ---- M25 JEV design loops (list and detail are reads; create, compute, abandon_docking and end are the person's
  // presses; the projection is the ordinary command route; preview, send and send records are the M24 calls above,
  // which take a `jev_loop_projection@1` handle too) ----
  /** `jev_loop@1` of a new loop; the same `loop_id` and body answer the existing record. */
  createJevLoop: (id: string, body: JevLoopCreateRequest, signal?: AbortSignal) =>
    request<JevLoopV1>(runPath(id, "/jev_loops"), jsonPost(body, signal)),
  /** This run's loops, newest first. */
  jevLoops: (id: string, signal?: AbortSignal) => request<JevLoopListRow[]>(runPath(id, "/jev_loops"), { signal }),
  jevLoop: (id: string, loopId: string, signal?: AbortSignal) =>
    request<JevLoopV1>(runPath(id, `/jev_loops/${encodeURIComponent(loopId)}`), { signal }),
  /** The person's start of one loop step (the answer waits for the job; the record is re-read meanwhile). */
  jevLoopCompute: (id: string, loopId: string, body: JevLoopComputeRequest, signal?: AbortSignal) =>
    request<JevLoopV1>(runPath(id, `/jev_loops/${encodeURIComponent(loopId)}/compute`), jsonPost(body, signal)),
  jevLoopAbandonDocking: (id: string, loopId: string, body: JevLoopAbandonRequest, signal?: AbortSignal) =>
    request<JevLoopV1>(runPath(id, `/jev_loops/${encodeURIComponent(loopId)}/abandon_docking`),
      jsonPost(body, signal)),
  /** The person's end of a loop (the body is an empty JSON object). */
  jevLoopEnd: (id: string, loopId: string, signal?: AbortSignal) =>
    request<JevLoopV1>(runPath(id, `/jev_loops/${encodeURIComponent(loopId)}/end`), jsonPost({}, signal)),
  /** Runs `build_jev_loop_projection` through the ordinary Run.call command route (no job, approval or budget). */
  buildJevLoopProjection: (id: string, args: JevLoopProjectionArgs, signal?: AbortSignal) =>
    api.command(id, "build_jev_loop_projection", args as unknown as Record<string, unknown>, signal),
  /** Report `analysis_type: "jev_loop"` of one stored `jev_loop_result@1` (nothing is computed or sent again). */
  createJevLoopReport: (id: string, resultHandle: string, signal?: AbortSignal) =>
    request<JevLoopReportArtifact>(runPath(id, "/method_reports"), jsonPost({ result_handle: resultHandle }, signal)),
  // ---- M26 reaction knowledge (reads write no event and run no tool; the result handle goes in the path) ----
  /** The active local reaction reference set, or `installed: false` and the reason (run independent). */
  reactionReferenceStatus: (signal?: AbortSignal) =>
    request<ReactionReferenceStatus>("/reaction_reference/status", { signal }),
  /** M-CSA entries naming this PDB ID (422 for a malformed ID, 412 without a usable set); a suggestion source only. */
  reactionReferencePdb: (pdbId: string, signal?: AbortSignal) =>
    request<ReactionPdbEntries>(`/reaction_reference/pdb/${encodeURIComponent(pdbId)}`, { signal }),
  /** Runs `link_reaction_knowledge` through the ordinary Run.call command route (no job, approval or budget). */
  linkReactionKnowledge: (id: string, args: ReactionKnowledgeArgs, signal?: AbortSignal) =>
    api.command(id, "link_reaction_knowledge", args as unknown as Record<string, unknown>, signal),
  /** This run's results, newest first; `limit` 1–100 (default 50). */
  reactionKnowledgeResults: (id: string, offset = 0, limit = 50, signal?: AbortSignal) =>
    request<ReactionKnowledgeList>(runPath(id, `/reaction_knowledge?offset=${offset}&limit=${limit}`), { signal }),
  /** `query` comes from `reactionDetailQuery` (reaction-knowledge.ts): the six chain / row / feature page values. */
  reactionKnowledgeResult: (id: string, handle: string, query: string, signal?: AbortSignal) =>
    request<ReactionKnowledgeDetail>(runPath(id, `/reaction_knowledge/${encodeURIComponent(handle)}?${query}`),
      { signal }),
  /** Method report `analysis_type: "reaction_knowledge"` of one stored result through the method report route
   * (`POST /method_reports`, the same body as `createMethodReport`); the linking is not run again. */
  createReactionKnowledgeReport: (id: string, resultHandle: string, signal?: AbortSignal) =>
    request<ReactionKnowledgeReportArtifact>(runPath(id, "/method_reports"), jsonPost({ result_handle: resultHandle }, signal)),
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
