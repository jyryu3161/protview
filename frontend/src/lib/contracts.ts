// Mirrors backend/mw (docs/contracts.md). Change BOTH sides together.
import type { SavedFigure, SavedScene } from "./saved-scene";

export type FailureClass = "transient" | "input_invalid" | "precondition" | "resource_exceeded" | "fatal";
/** UI-only: an empty scientific result shown next to failure classes. Never an error. */
export type ResultClass = FailureClass | "scientific_null";
export type DecisionSource = "rule" | "jev" | "frontier" | "human";
export type StepState = "pending" | "running" | "done" | "failed";
export type CostClass = "cheap" | "moderate" | "expensive";
export type EgressMode = "online" | "local_only" | "dry_run";
export type InteractionType =
  | "hbond" | "hydrophobic" | "salt_bridge" | "pi_stack" | "cation_pi" | "metal" | "water_bridge";
export type GeometricContactType = "contact" | "polar_contact" | "hydrophobic_contact";

export interface Handle {
  handle: string;           // "obj://<run_id>/<kind>/<sha256>" — opaque; never parse beyond display
  kind: string;
  schema: string;           // e.g. "interaction_set@1"
  summary: Record<string, unknown>;
  preview: Record<string, unknown>[];
  produced_by?: string | null;
  null_result?: boolean;
}

export interface Fix { tool: string; args: Record<string, unknown> }
export interface ToolError { error: FailureClass; message: string; fix?: Fix | null; detail?: Record<string, unknown> }

export interface ResidueRef {
  model_number?: number;
  chain_auth: string; seq_auth: number; icode: string;
  chain_label: string | null; seq_label: number | null; resname: string;
}
export const residueUid = (r: ResidueRef) => `${r.chain_auth}/${r.seq_auth}${r.icode ?? ""}`;

export interface InteractionRow {
  residue: ResidueRef; ligand?: ResidueRef; type: InteractionType | GeometricContactType; distance_A: number;
  protein_atom?: string; ligand_atom?: string; engine: string;
  method?: string; unit?: string; limitations?: string;
}

export interface BudgetAxis { used: number; limit: number }
export type BudgetSnapshot = Record<"wall_clock_s" | "expensive_calls" | "external_tokens" | "usd", BudgetAxis>;

export type RunEvent =
  | { seq: number; ts: number; type: "run_started"; run_id: string; dry_run: boolean; seed: number }
  | { seq: number; ts: number; type: "goal"; text: string; context: string[]; egress: EgressMode }
  | { seq: number; ts: number; type: "upload_received"; upload_id: string; sha256: string; size: number; format: string }
  | { seq: number; ts: number; type: "object_created"; handle: string; kind: string }
  | { seq: number; ts: number; type: "job_terminal"; job_id: string; attempt_id: string | null;
      status: string; output_handles: string[]; failure?: { error: string; message: string } | null }
  | { seq: number; ts: number; type: "tool_called"; tool: string; key: string; call_id: string;
      args: Record<string, unknown>; decided_by: DecisionSource; attempt: number; version: string }
  | { seq: number; ts: number; type: "tool_succeeded"; tool: string; key: string; call_id: string;
      output: Handle; duration_s?: number; null_result?: boolean; cached?: boolean }
  | { seq: number; ts: number; type: "cache_hit"; observation_id: string; proposal_id: string;
      tool: string; key: string; args: Record<string, unknown>; output: Handle;
      source_call_id: string; branch_id?: string | null }
  | ({ seq: number; ts: number; type: "tool_failed"; tool: string; key: string; call_id: string } & ToolError)
  | { seq: number; ts: number; type: "decision"; source: DecisionSource; question: string; answer: unknown }
  | { seq: number; ts: number; type: "approval_requested"; gate: string; tool: string; args: Record<string, unknown> }
  | { seq: number; ts: number; type: "approval_resolved"; gate: string; approved: boolean; by: string }
  | { seq: number; ts: number; type: "checkpoint"; reason: string; axis?: string; budget?: BudgetSnapshot }
  | { seq: number; ts: number; type: "branch_proposed" | "branch_observed" | "proposal_rejected" |
      "budget_reserved" | "wall_charged" | "tool_interrupted" | "clock_anomaly" |
      "budget_limit_updated" | "cancel_requested" | "run_cancelled"; [key: string]: unknown }
  | { seq: number; ts: number; type: "llm_call"; role: string; prompt_ref: string; prompt_sha: string;
      requested_model: string; served_model: string; tokens: number; cached: boolean }
  | { seq: number; ts: number; type: "egress"; destination: string; blocked_fields: string[] }
  | { seq: number; ts: number; type: "run_finished" };

export interface ToolSpec {
  name: string; level: "L1" | "L2" | "L3" | "L4" | "L5"; version: string;
  accepts: Record<string, string[]>;
  params: Record<string, { type: string; enum?: string[]; min?: number; max?: number; default?: unknown; required?: boolean }>;
  emits: string; cost_class: CostClass; idempotent: boolean; read_only: boolean; typical_runtime_s: number; description: string;
}

// ---- M13 analysis workflows (backend/mw/analysis_plans.py, analysis_executions.py) ----
export type AnalysisGoal = "inspect_ligand" | "measure_atoms" | "compare_structures" | "chemical_interactions" |
  "find_cavities" | "minimize_protein";
export type AnalysisLane = "run_call" | "durable_job" | "report";
export type AnalysisExecutionStatus = "plan_only" | "awaiting_approval" | "ready" | "executing" | "waiting_job" |
  "awaiting_scientific_approval" | "blocked" | "failed" | "cancelled" | "complete";
export type AnalysisStepStatus = "pending" | "dispatched" | "waiting_job" | "completed" | "failed" | "interrupted" |
  "cancelled" | "blocked";
export type AnalysisAction = "approve" | "revoke" | "advance" | "retry" | "cancel" | "scientific_approval";

export interface AnalysisTemplateRow { goal: AnalysisGoal; template_version: string; required_inputs: string[];
  steps: string[]; available: boolean; method: string | null; reason_code: string | null; reason: string | null;
  fixed?: { categories?: string[] } }
export interface AnalysisTemplates { schema: "analysis_templates@1"; planner: string; source: string;
  templates: AnalysisTemplateRow[]; natural_language_planning: { available: boolean; reason: string };
  limits: Record<string, number> }
export interface AnalysisWorkflowsCapability { available: boolean; planner?: string; source?: string;
  templates?: Record<string, { available: boolean; method: string | null; reason_code: string | null; reason: string | null }>;
  natural_language_planning?: { available: boolean; reason: string } }

export interface AnalysisBinding { kind: "existing" | "step_output"; handle?: string; step_id?: string;
  output_name?: string; expected_kind: string; expected_schema: string }
export interface AnalysisPlanStep { step_id: string; operation: string; operation_version: string; lane: AnalysisLane;
  bindings: Record<string, AnalysisBinding>; params: Record<string, unknown>;
  outputs: { name: string; kind: string; schema: string }[]; depends_on: string[] }
export interface AnalysisPrerequisite { code: string; message: string; detail: Record<string, unknown> }
export interface AnalysisPlan { schema: "analysis_plan@1"; planner: "local_rules@1"; source: "local_rules"; plan_only: true;
  goal: AnalysisGoal; template_version: string; inputs: Record<string, unknown>; compatibility: Record<string, unknown>;
  steps: AnalysisPlanStep[]; limits: Record<string, number>; unmet_prerequisites: AnalysisPrerequisite[];
  deferred_bindings: { step_id: string; output_name: string; kind: string; schema: string }[] }
export interface AnalysisPlanRecord { handle: string; plan: AnalysisPlan; plan_sha256: string; executable: boolean;
  ordinal: number; replayed?: boolean }
export interface AnalysisPlanList { schema: "analysis_plan_list@1"; total: number;
  rows: { handle: string; goal: AnalysisGoal; ordinal: number; created_seq: number; executable: boolean }[] }

export interface AnalysisStepFailure { status: string | null; error: string | null; reason_code: string | null;
  message: string | null; retryable: boolean | null }
export interface AnalysisStepRecord { step_id: string; operation: string; lane: AnalysisLane; status: AnalysisStepStatus;
  null_result: boolean | null; operation_id: string | null; dispatch_seqs: number[]; completed_seq: number | null;
  attempts: number; retries_used: number; outputs: Record<string, string>; report_handle: string | null;
  child_call_ids: string[]; job_id: string | null; job_ownership: "owned" | "observed_shared" | null;
  job_status: string | null; job_cleanup_status: string | null; job_blocked_reason: string | null;
  job_cancel_requested: boolean | null; shared_job_notice: string | null; deferred_reason: string | null;
  failure: AnalysisStepFailure | null }
export interface AnalysisExecution { schema: string; execution_id: string; run_id: string; plan_handle: string;
  plan_sha256: string; goal: AnalysisGoal; template_version: string; source: "local_rules"; planner: string;
  dry_run: boolean; status: AnalysisExecutionStatus; retryable_step: string | null; revision: number;
  created_seq: number; current_step: string | null;
  plan_approval: { approved: boolean; event_seq: number | null; plan_sha256: string | null;
    revocations: { seq: number; outcome: string }[] };
  scientific_approval: { required: boolean; run_approved: boolean;
    state: "not_required" | "already_approved_in_run" | "pending" | "not_yet_requested";
    pending_tool: string | null; recorded_seqs: number[] };
  blocked_reason: { reason_code: string; message: string; step_id: string | null; detail: Record<string, unknown> } | null;
  stop: { seq: number; reason: "stop" | "revoke" } | null;
  notice: { code: string; step_id: string | null; message: string | null } | null;
  driver: { in_progress: boolean; request_ids: string[] }; recovery_pending: boolean;
  steps: AnalysisStepRecord[]; physical_attempts: number; active_wall_s: number; limits: Record<string, number>;
  summary_handle: string | null; event_seqs: number[]; jobs_readable: boolean }
// total counts every created execution; rows are capped at 100. A row whose record cannot be read carries
// error {code:"execution_record_invalid"} and null goal/status/revision/dry_run/current_step/summary_handle.
export interface AnalysisExecutionListRow { execution_id: string; plan_handle: string | null; goal: AnalysisGoal | null;
  status: AnalysisExecutionStatus | null; revision: number | null; created_seq: number | null; dry_run: boolean | null;
  current_step: string | null; summary_handle: string | null; error: { code: string; message: string } | null }
export interface AnalysisExecutionList { schema: "analysis_execution_list@1"; total: number; rows: AnalysisExecutionListRow[] }
export interface AnalysisEnvelope { execution: AnalysisExecution; replayed: boolean;
  request: { request_id: string; action: string; state: "completed" | "pending"; outcome: string } }
export interface AnalysisSummary { handle: string; summary: { schema: string; plan_handle: string; plan_hash: string;
  execution_id: string; goal: AnalysisGoal; source: string; approval_event_seq: number | null;
  first_event_seq: number | null; last_event_seq: number | null;
  steps: { step_id: string; operation: string; status: string; null_result: boolean | null;
    output_handles: string[]; report_handle: string | null; child_call_ids: string[];
    job_ids: string[]; job_ownership: string | null; attempts: number }[];
  physical_attempts: number; note?: string } }

// ---- M16 reference site annotation (backend/mw/site_annotation.py, saved_scenes.py) ----
/** Residue identity with all 7 fields (null kept); compared exactly, never rebuilt from a display string. */
export type ExactResidueRef = ResidueRef & { model_number: number };
export type SiteStatus = "annotated" | "absent";
export type SiteAbsentReason = "klifs_not_applied" | "pocket_gap" | "region_unresolved" | "no_mapped_residue";
export type SiteGroupAbsentReason = "accession_not_in_klifs" | "klifs_pocket_empty" | "klifs_multiple_entries" |
  "uniprot_sequence_unavailable" | "no_mapped_accession";
export interface SiteTypeCount { computed: boolean; count: number | null }
export interface SitePolarPair { contact_row_index: number; protein_atom: string; ligand_atom: string; distance_A: number }
export interface SiteContact {
  assessed: boolean; not_assessed_reason: "residue_not_checked_by_contact_method" | null;
  by_type: Record<GeometricContactType, SiteTypeCount>;
  min_distance_A: number | null; min_distance_row_index: number | null;
  /** null when polar_contact was not computed (or the residue is not assessed); [] when computed with no rows. */
  polar_pairs: SitePolarPair[] | null;
}
export interface AnnotationSite {
  klifs_index: number; klifs_label: string; status: SiteStatus; absent_reason: SiteAbsentReason | null;
  residue: ExactResidueRef | null; map_row_index: number | null; residue_match: boolean | null;
  klifs_match: "contiguous" | "gapped_unique" | null;
  /** Server-built label (`Met318 (hinge.47)`); shown as is. */
  display_label: string | null;
  contact: SiteContact | null;
}
export interface AnnotationGroup { chain_auth: string; accession: string | null; klifs_applied: boolean;
  klifs_absent_reason: SiteGroupAbsentReason | null; sites: AnnotationSite[] }
export interface AnnotationContacts { handle: string; ligand: ExactResidueRef; cutoff_A: number; types: GeometricContactType[] }
export interface ReferenceSiteAnnotation {
  schema: "reference_site_annotation@1";
  method_version: string;
  site_set: { id: "kinase_key_sites@1"; sites: { klifs_index: number; klifs_label: string }[] };
  numbering_map: string;
  snapshot_set_hash: string;
  structure: { handle: string; structure_kind: "structure" | "prepared_structure"; model_number: number };
  contacts: AnnotationContacts | null;
  groups: AnnotationGroup[];
  other_contact_residues: { residue: ExactResidueRef; row_indexes: number[] }[] | null;
  null_result: boolean;
  limitations: string[];
}
export interface SiteAnnotationListRow {
  handle: string; structure: string; structure_kind: "structure" | "prepared_structure"; model_number: number;
  numbering_map: string; contacts: string | null; ligand: ExactResidueRef | null; set_hash: string;
  groups: { chain_auth: string; accession: string | null }[]; counts: Record<SiteStatus, number>;
  null_result: boolean; created_seq: number;
  /** True also when no active reference set exists; decide the badge with `snapshotBadge` (numbering.ts). */
  stale_snapshot: boolean;
}
/** Newest first. */
export interface SiteAnnotationList { schema: "reference_site_annotation_list@1"; active_set_hash: string | null;
  total: number; offset: number; limit: number; rows: SiteAnnotationListRow[] }

/** `viewer_scene@2`: every `viewer_scene@1` field plus the shown annotation. */
export interface SceneAnnotationRef { handle: string; legend: boolean }
export type SavedSceneV2 = Omit<SavedScene, "schema"> & { schema: "viewer_scene@2"; annotation: SceneAnnotationRef };
export type AnySavedScene = SavedScene | SavedSceneV2;
export interface AnySavedSceneDetail { handle: string; value: AnySavedScene }
export type FigureCaptureMethod = "molstar_image_pass" | "molstar_image_pass+legend";
export interface FigureAnnotationProvenance { handle: string; legend: boolean; numbering_map: string;
  contacts: string | null; snapshot_set_hash: string; display_labels: string[] }
export type SavedFigureV2 = Omit<SavedFigure, "schema" | "capture_method"> & { schema: "viewer_figure@2";
  capture_method: FigureCaptureMethod; annotation: FigureAnnotationProvenance };
export type AnySavedFigure = SavedFigure | SavedFigureV2;
export interface AnySavedFigureDetail { handle: string; value: AnySavedFigure }

// ---- M17 ligand candidates (backend/mw/ligand_reads.py, ligand_bundle.py, ligand_filters.py) ----
export type LigandImportKind = "ligand_sdf" | "building_blocks_sdf" | "building_blocks_smiles";
export type LigandPropertyName = "mol_weight" | "crippen_logp" | "hbd" | "hba" | "tpsa" | "rotatable_bonds" |
  "heavy_atoms" | "formal_charge";
export type LigandSortKey = "generation_order" | LigandPropertyName;
export type LigandSortDirection = "asc" | "desc";
export type LigandBondOrder = "single" | "double" | "triple" | "aromatic";
export type LigandStereoFlag = "none" | "parent_stereo_lost" | "new_unspecified_center";
export type LigandStopReason = "candidate_limit" | "attempt_limit";
/** RDKit values as stored (never null); rounding happens only for display. */
export type LigandProperties = Record<LigandPropertyName, number>;

/** `POST /runs/{id}/chemical/imports` answer for the three ligand kinds. */
export interface LigandImport { schema: "chemical_raw_input@1"; handle: string; kind: LigandImportKind; format: string;
  sha256: string; size: number }
/** `methods.ligand_candidates` of `/capabilities` and `capability` of the prerequisites read. */
export interface LigandCapability { schema: "ligand_capability@1"; available: boolean; status: string;
  reason_code: string | null; reason: string | null; engine: "rdkit"; rdkit_version_expected: string;
  protocols: string[]; tools: Record<string, string>; execution_lane: string; timeout_s: number;
  limits: Record<string, number>; limitations: string[]; pins: Record<string, string> | null;
  pains_catalog_entries: Record<string, number> | null }
export interface LigandPrerequisites { schema: "ligand_prerequisites@1"; capability: LigandCapability;
  import_counts: Record<LigandImportKind, number>;
  imports: { handle: string; input_kind: LigandImportKind; sha256: string | null; created_seq: number }[];
  inspections: number; candidate_sets: number; requires: string[]; starts_job: false }

/** SDF 1-based atom-block serials (H lines included), heavy atoms only. */
export interface LigandAtom { serial: number; element: string; formal_charge: number; neighbors: number[] }
export interface LigandBond { a: number; b: number; order: LigandBondOrder }
export interface LigandParent { sha256: string; atoms_in_sdf: number; heavy_atom_count: number; canonical_smiles: string;
  atoms: LigandAtom[]; bonds: LigandBond[]; hydrogens: { serial: number; attached_to: number }[];
  /** RDKit 2D drawing; shown only as an `<img>` data URI, never inserted into the DOM. */
  svg: string; svg_bytes: number; properties: LigandProperties }
export interface LigandBlockLibrary { kind: "building_blocks_sdf" | "building_blocks_smiles"; input_format: string;
  sha256: string; records_total: number; records_read: number; block_limit_reached: boolean; accepted: number;
  rejected: { ordinal: number; name: string; reason: string }[]; rejected_total: number;
  rejected_counts: Record<string, number>; fixed_targets: number; rule_targets: number }
/** `status` is "valid" or a rule reason code; `text` is null when the rule was `too_large`. */
export interface LigandRuleRow { rule_id: string; status: string; text: string | null; text_sha256: string }
export interface LigandInspection { schema: "ligand_inspection@1"; protocol: "rdkit_inspect_v1";
  method: Record<string, string>; parent_handle: string; block_handles: string[];
  input_sha256: { parent: string; blocks: string[]; rules: string[] }; parent: LigandParent;
  property_methods: Record<LigandPropertyName, string>; block_libraries: LigandBlockLibrary[]; rules: LigandRuleRow[] }
export interface LigandInspectionDetail { schema: "ligand_inspection_detail@1"; handle: string; job_id: string;
  inspection: LigandInspection; meta: Record<string, unknown> }
/** Creation order (oldest first). A row that does not validate has `valid: false` and null fields. */
export interface LigandInspectionListRow { handle: string; created_seq: number; valid: boolean; reason_code: string | null;
  job_id: string | null; parent_handle: string | null; parent_sha256: string | null;
  parent_canonical_smiles: string | null; heavy_atom_count: number | null; block_handles: string[] | null;
  blocks_accepted: number | null; rules_total: number | null; rules_valid: number | null }
export interface LigandInspectionList { schema: "ligand_inspection_list@1"; total: number; offset: number; limit: number;
  rows: LigandInspectionListRow[] }

export interface LigandRuleUsed { rule_id: string; method: string; text: string | null }
export interface LigandCrossingBond { core_atom: number; site_atom: number; order: LigandBondOrder }
export interface LigandCounts { blocks_accepted: number; raw_products: number; candidates: number;
  duplicate_products: number; rejected: Record<string, number>; not_applicable: Record<string, number> }
export interface LigandCandidate { id: string; smiles: string; origins: { rule_id: string; block_name: string }[];
  retained_parent_atoms: number[]; stereo_flag: LigandStereoFlag; properties: LigandProperties;
  pains: { matches: { catalog: string; name: string }[] } }
export interface LigandCandidateSet { schema: "ligand_candidate_set@1"; protocol: "rdkit_enumerate_v1";
  method: Record<string, string>; inspection_handle: string; parent_handle: string; block_handles: string[];
  input_sha256: Record<string, unknown>; parent_sha256: string; parent_canonical_smiles: string;
  parent_properties: LigandProperties; property_methods: Record<LigandPropertyName, string>; site_atoms: number[];
  retained_parent_atoms: number[]; crossing_bond: LigandCrossingBond; use_fixed: boolean; rules_used: LigandRuleUsed[];
  methods: string[]; block_libraries: LigandBlockLibrary[]; counts: LigandCounts;
  limits: { max_candidates: number; max_attempts: number }; limit_reached: boolean;
  stop_reason: LigandStopReason | null; limitations: string[] }
/** Detail read: the set without its rows (`candidate_count` rows are paged by the rows read). */
export interface LigandCandidateSetDetail { schema: "ligand_candidate_set_detail@1"; handle: string; job_id: string;
  candidate_count: number; candidate_set: LigandCandidateSet; meta: Record<string, unknown> }
export interface LigandCandidateSetListRow { handle: string; created_seq: number; valid: boolean;
  reason_code: string | null; job_id: string | null; inspection_handle: string | null; site_atoms: number[] | null;
  use_fixed: boolean | null; rule_ids: string[] | null; candidates: number | null; raw_products: number | null;
  null_result: boolean | null; limit_reached: boolean | null; stop_reason: LigandStopReason | null }
export interface LigandCandidateSetList { schema: "ligand_candidate_set_list@1"; inspection_handle: string | null;
  total: number; offset: number; limit: number; rows: LigandCandidateSetListRow[] }

/** Normalized filter spec (server form; also what a report records). Bounds are inclusive. */
export interface LigandFilterSpec { ranges: Partial<Record<LigandPropertyName, { min: number | null; max: number | null }>>;
  pains_exclude: boolean }
export interface LigandCandidatePageRow { generation_order: number; candidate: LigandCandidate;
  /** Per applied filter (range names and `pains_exclude`) pass/fail, decided by the server. */
  filters: Record<string, boolean>; passes_all: boolean | null }
export interface LigandCandidatePage { schema: "ligand_candidate_page@1"; handle: string; inspection_handle: string;
  parent_handle: string; parent_canonical_smiles: string; parent_properties: LigandProperties;
  property_methods: Record<LigandPropertyName, string>; site_atoms: number[]; retained_parent_atoms: number[];
  crossing_bond: LigandCrossingBond; use_fixed: boolean; rules_used: LigandRuleUsed[]; counts: LigandCounts;
  limits: { max_candidates: number; max_attempts: number }; limit_reached: boolean;
  stop_reason: LigandStopReason | null; limitations: string[];
  /** null when no filter is applied (as `passing`). */
  failing: number | null; total: number; passing: number | null; filter_pass_counts: Record<string, number>;
  matched: number; hidden_by_filter: number; sort: LigandSortKey; direction: LigandSortDirection; offset: number;
  limit: number; passes_only: boolean; filter_spec: LigandFilterSpec; rows: LigandCandidatePageRow[] }

export interface LigandSiteCheck { schema: "ligand_site_check@1"; valid: boolean; reason: string | null;
  site_atoms: number[]; unknown_atoms: number[] | null; core_atoms: number[] | null;
  crossing_bonds: LigandCrossingBond[] | null; site_hydrogens: number[] | null; retained_parent_atoms: number[] | null }
/** `POST /runs/{id}/ligand/preview` body (also the enumeration job args). */
export interface LigandEnumerateArgs { inspection_handle: string; site_atoms: number[]; use_fixed: boolean;
  rule_ids: string[] }
export interface LigandSitePreview { schema: "ligand_site_preview@1"; inspection_handle: string;
  site_check: LigandSiteCheck; use_fixed: boolean;
  rules: { rule_id: string; status: string | null; usable: boolean }[]; generation_method_selected: boolean;
  ready: boolean; blocking_reasons: string[]; starts_job: false }

export interface LigandInspectArgs { parent_sdf_handle: string; block_handles: string[]; rules: string[] }
export type LigandProtocol = "rdkit_inspect_v1" | "rdkit_enumerate_v1";
export interface LigandJob { job_id: string; run_id: string; protocol_id: LigandProtocol; tool_id: string;
  status: string; blocked_reason: string | null;
  failure: { error: string; message: string; reason_code?: string } | null; input_handles: string[];
  output_handles: string[]; attempt_ordinal: number; cancel_requested: boolean; timeout_s: number;
  artifacts: { ligand_inspection?: string; ligand_candidate_set?: string } }
/** Dry-run submission: a plan only, no job and no result object. */
export interface LigandPlanOnly { plan_only: true; protocol_id: LigandProtocol; reason_code: "dry_run"; available: false;
  output_handles: []; normalized_parameters: Record<string, unknown> }
export type LigandSubmission = LigandJob | LigandPlanOnly;
export interface LigandReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "ligand_candidates"; result_handle: string;
  filter_spec: LigandFilterSpec; null_result: boolean; snapshot: { event_seq: number } } & Record<string, unknown>;
  markdown: string }

// ---- M18 ligand docking (backend/mw/docking_inputs.py, docking_bundle.py, docking_reads.py) ----
export type DockingMode = "free" | "core_fixed";
export type DockingLigandSource = "sdf" | "candidate";
export type DockingBoxSource = "ligand_range" | "instance_range" | "manual";
export type DockingMethod = "qvina_free_v1" | "qvina_core_fixed_score_only_v1";
export type DockingAcknowledgementKey = "keep_input_protonation" | "tool_assigned_types_charges" | "rigid_no_optimization";
export type DockingTriple = [number, number, number];

/** `qvina_dock_v1` job arguments (fixed shape; the server refuses unknown keys). `conformers` only for `core_fixed`. */
export interface DockingArgs {
  receptor_handle: string;
  receptor_model_number: number;
  connectivity: { kind: "pdb_conect"; sidecar_handle: null } | { kind: "sidecar"; sidecar_handle: string };
  /** Exactly the seven residue fields (nulls kept); null = protein only, no instance removed. */
  receptor_instance: ExactResidueRef | null;
  ligand: { source: "sdf"; sdf_handle: string } |
    { source: "candidate"; candidate_set_handle: string; candidate_id: string; parent_sdf_handle: string };
  mode: DockingMode;
  box: { source: "ligand_range" | "instance_range"; margin_A: number } |
    { source: "manual"; center_A: DockingTriple; size_A: DockingTriple };
  parameters: { seed: number; exhaustiveness: number; num_modes: number; energy_range: number; conformers?: number };
  acknowledgement: Record<DockingAcknowledgementKey, true>;
}

/**
 * M21 `qvina_dock_v1` arguments with `receptor_source` instead of the four imported receptor keys (spec 7). No
 * receptor instance exists in a protein-only model, so an `instance_range` box is refused (`box_invalid`).
 */
export interface DockingSourceArgs {
  receptor_source: DockingReceptorSource;
  ligand: DockingArgs["ligand"];
  mode: DockingMode;
  box: { source: "ligand_range"; margin_A: number } | { source: "manual"; center_A: DockingTriple; size_A: DockingTriple };
  parameters: DockingArgs["parameters"];
  acknowledgement: Record<DockingAcknowledgementKey, true>;
}

/** `methods.ligand_docking` of `/capabilities` and `capability` of the prerequisites read. */
export interface DockingCapability { schema: "docking_capability@1"; protocol_id: "qvina_dock_v1";
  tool_id: "qvina_dock_ligand"; engine: "qvina"; execution_lane: string; methods: Record<DockingMode, DockingMethod>;
  timeout_s: { default: number; max: number };
  limits: { input_bytes_per_file: number; receptor_atoms: number; ligand_heavy_atoms: number; active_torsions: number;
    box_side_A: [number, number]; result_bytes: number; contacts_per_mode: number };
  score_label: string; limitations: string[]; available: boolean; status: string; reason_code: string | null;
  reason: string | null; pins: Record<string, unknown> | null; versions: Record<string, string> | null }

export type DockingImportKind = "receptor" | "receptor_bonds" | "ligand_sdf";
export interface DockingPrerequisites { schema: "docking_prerequisites@1"; capability: DockingCapability;
  import_counts: Record<DockingImportKind, number>;
  imports: { handle: string; input_kind: DockingImportKind; input_format: string | null; size: number;
    sha256: string | null; created_seq: number }[];
  /** A set that does not validate has `valid: false` and null fields. */
  candidate_sets: { handle: string; valid: boolean; candidates: number | null; parent_handle: string | null;
    parent_sha256: string | null; parent_sdf_handles: string[] | null }[];
  docking_results: number; starts_job: false }

export interface DockingReceptorInstance { residue: ExactResidueRef; atom_count: number;
  element_counts: Record<string, number> }
/** Selection aid only (gemmi read of one receptor import); admission and the worker check the choice again. */
export interface DockingReceptorInstances { schema: "docking_receptor_instances@1"; handle: string;
  sha256: string | null; format: "pdb" | "cif"; model_numbers: number[];
  models: { model_number: number; water_residue_count: number; instances: DockingReceptorInstance[] }[];
  selection_aid_only: true; starts_job: false }

export interface DockingReceptorAtom { residue: ExactResidueRef; atom_name: string; altloc: string; element: string;
  site_index: number }
/** Geometric contact (distance only, 4.0 Å); not a hydrogen bond or any interaction call. */
export interface DockingContact { ligand_serial: number; ligand_element: string; ligand_parent_serial: number | null;
  receptor_atom: DockingReceptorAtom; distance_A: number; kind: GeometricContactType }
interface DockingModeFields { mode: number; score_kcal_mol: number; engine_rmsd_lb_A: number | null;
  engine_rmsd_ub_A: number | null; conformer_index: number | null; core_max_deviation_A: number | null;
  atoms_outside_box: number; min_heavy_atom_distance_A: number }
/** One stored mode row of `docking_result@1`. */
export interface DockingModeRow extends DockingModeFields { pose_sdf: string; contacts: DockingContact[] }
/** Mode row of the detail read: no pose SDF and no contact rows, the stored contact count instead. */
export interface DockingModeSummary extends DockingModeFields { contact_count: number }
/** `inputs.receptor` of an imported receptor (M18; the only kind an M19 batch takes). */
export interface DockingImportedReceptor { handle: string; sha256: string; model_number: number;
  connectivity: { kind: "pdb_conect" | "sidecar"; sidecar_handle: string | null };
  removed_instance: DockingReceptorInstance | null; acknowledgement: Record<DockingAcknowledgementKey, true> }
/**
 * M21 `receptor_source` (single M18 only): one side of a published same-run `mutation_model@1`. The four imported
 * receptor keys (`receptor_handle`, `receptor_model_number`, `connectivity`, `receptor_instance`) are then absent.
 */
export interface DockingReceptorSource { kind: "mutation_model"; mutation_model: string; side: MutationModelSide }
/** M21 `inputs.receptor` of a mutation-model receptor: no import handle, bonds from the stored OpenMM topology. */
export interface DockingMutationModelReceptor { source: DockingReceptorSource; sha256: string; model_number: number;
  connectivity: { kind: "mutation_model_topology" }; removed_instance: null;
  acknowledgement: Record<DockingAcknowledgementKey, true> }
export interface DockingResult { schema: "docking_result@1"; protocol: "qvina_dock_v1"; method: DockingMethod;
  input_sha256: string;
  inputs: {
    receptor: DockingImportedReceptor | DockingMutationModelReceptor;
    ligand: { source: DockingLigandSource; sdf_handle: string | null; sdf_sha256: string | null;
      candidate_set_handle: string | null; candidate_id: string | null; parent_sdf_handle: string | null;
      parent_sdf_sha256: string | null; generated: { hydrogens: boolean; coordinates: boolean };
      stereo_flag: LigandStereoFlag | null; unspecified_stereo_centers: number | null };
    mode: DockingMode };
  box: { center_A: DockingTriple; size_A: DockingTriple; source: DockingBoxSource; margin_A: number | null };
  parameters: { seed: number; exhaustiveness: number; num_modes: number; energy_range: number;
    conformers: number | null; cpu: 1 };
  engine: { name: "qvina"; version: string; binary_sha256: string; package: string };
  preparation: { tool: "Meeko"; version: string; rdkit_version: string; atom_typing: string; charges: string };
  modes: DockingModeRow[];
  counts: { modes: number; contacts_by_mode: number[]; null_result: boolean; samples_generated: number | null;
    samples_scored: number | null };
  limitations: string[] }
export interface DockingResultDetail { schema: "docking_result_detail@1"; handle: string; job_id: string;
  score_label: string; result: Omit<DockingResult, "modes"> & { modes: DockingModeSummary[] };
  meta: Record<string, unknown>;
  /** M29: only when the receptor is a model on a repaired structure. */
  structure_origin?: StructureOrigin }
/** Creation order (oldest first). A row that does not validate has `valid: false` and null fields. */
export interface DockingResultListRow { handle: string; created_seq: number; valid: boolean; reason_code: string | null;
  job_id: string | null; method: DockingMethod | null; mode: DockingMode | null;
  ligand_source: DockingLigandSource | null; candidate_id: string | null; receptor_handle: string | null;
  seed: number | null; box_source: DockingBoxSource | null; modes: number | null; null_result: boolean | null;
  /** M29: only when the receptor is a model on a repaired structure. */
  structure_origin?: StructureOrigin }
export interface DockingResultList { schema: "docking_result_list@1"; total: number; offset: number; limit: number;
  rows: DockingResultListRow[] }
export interface DockingContactPage { schema: "docking_contact_page@1"; handle: string; mode: number;
  method: DockingMethod; cutoff_A: number; total: number; offset: number; limit: number; rows: DockingContact[] }

export interface DockingJob { job_id: string; run_id: string; protocol_id: "qvina_dock_v1"; tool_id: string;
  status: string; blocked_reason: string | null;
  /** `detail` is the worker's typed refusal detail (e.g. the receptor leftover list); never a science value. */
  failure: { error: string; message: string; reason_code?: string; detail?: Record<string, unknown> } | null;
  input_handles: string[]; output_handles: string[]; attempt_ordinal: number; cancel_requested: boolean; timeout_s: number;
  artifacts: { docking_result?: string } }
/** Dry-run submission: a plan only, no job and no result object. */
export interface DockingPlanOnly { plan_only: true; protocol_id: "qvina_dock_v1"; reason_code: "dry_run";
  available: false; output_handles: []; normalized_parameters: Record<string, unknown> }
export type DockingSubmission = DockingJob | DockingPlanOnly;
export interface DockingReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "ligand_docking"; result_handle: string; null_result: boolean;
  snapshot: { event_seq: number } } & Record<string, unknown>; markdown: string }

// ---- M19 batch docking (backend/mw/docking_batch_inputs.py, docking_batch_jobs.py, docking_batch_reads.py) ----
export type DockingBatchRowKind = "parent" | "candidate";
export type DockingBatchRowState = "scored" | "null_result" | "failed" | "cancelled" | "not_run";
export type DockingBatchStatus = "complete" | "partial";
export type DockingBatchStopReason = "cancelled" | "time_exhausted" | "worker_failed" | "resource_exceeded";
type BudgetPair = { expensive_calls: number; wall_clock_s: number };

/**
 * `qvina_batch_dock_v1` job arguments (fixed shape; unknown keys refused). The M18 receptor, box, parameter and
 * acknowledgement fields plus the candidate set, its parent SDF, the chosen ids and the parent row; no `ligand` key.
 */
export interface DockingBatchArgs extends Omit<DockingArgs, "ligand"> {
  candidate_set_handle: string;
  parent_sdf_handle: string;
  /** 1–50 distinct ids, in candidate-set order. */
  candidate_ids: string[];
  include_parent: boolean;
}

/** `methods.ligand_docking_batch` of `/capabilities` (and the preflight's `capability`). */
export interface DockingBatchCapability { schema: "docking_batch_capability@1"; protocol_id: "qvina_batch_dock_v1";
  tool_id: "qvina_dock_batch"; engine: "qvina"; execution_lane: string; available: boolean; status: string;
  reason_code: string | null; reason: string | null; pins: Record<string, unknown> | null;
  batch_pins: Record<string, string> | null; methods?: Record<DockingMode, DockingMethod>; timeout_s?: { max: number };
  limits?: { max_candidates: number; per_candidate_s: number; total_s: number; output_bytes: number;
    summary_bytes: number }; score_label?: string; batch_statements?: Record<string, string> }

export interface DockingBatchStatements { batch: { id: string; text: string }[]; m18: { number: number; text: string }[] }

/** `POST /runs/{id}/docking/batches/preflight` (a read). A refused request has null numbers and rows. */
export interface DockingBatchPreflight { schema: "docking_batch_preflight@1"; starts_job: false;
  capability: DockingBatchCapability; score_label: string; budget: Record<"expensive_calls" | "wall_clock_s", BudgetAxis>;
  admission: { admitted: boolean; error: string | null; reason_code: string | null; message: string | null;
    detail: Record<string, unknown> | null };
  batch_input_sha256: string | null; mode: DockingMode | null; include_parent: boolean | null;
  candidate_ids: string[] | null;
  rows: { row_index: number; kind: DockingBatchRowKind; candidate_id: string | null; reuse: boolean;
    reused_handle: string | null; new_docking: boolean }[] | null;
  new_dockings: number | null; reused_rows: number | null; needed: BudgetPair | null; remaining: BudgetPair;
  shortfall: BudgetPair | null; full_batch_may_be_partial: boolean | null; statements: DockingBatchStatements | null;
  existing_job: { job_id: string; status: string; summary_handle: string | null } | null }

/** `POST /runs/{id}/docking/batches/limit_approval` (the person's explicit approval; idempotent). */
export interface DockingBatchLimitApproval { raised: boolean; batch_input_sha256: string; new_dockings: number;
  needed: BudgetPair; shortfall_before: BudgetPair; increase: BudgetPair; limits_before: BudgetPair;
  limits_after: BudgetPair; shortfall_after: BudgetPair; event_seq: number | null; budget: BudgetSnapshot }

/** One stored summary row (spec 5.2): score only for `scored`, reason only for failed / cancelled / not_run. */
export interface DockingBatchRow { row_index: number; kind: DockingBatchRowKind; candidate_id: string | null;
  state: DockingBatchRowState; reason_code: string | null; result_handle: string | null;
  score_kcal_mol: number | null; score_row_label: string | null }
export interface DockingBatchResult { schema: "docking_batch_result@1"; protocol: "qvina_batch_dock_v1";
  method: DockingMethod; batch_input_sha256: string;
  inputs: { receptor: DockingImportedReceptor;
    candidate_set: { handle: string; parent_sdf_handle: string; parent_sdf_sha256: string };
    candidate_ids: string[]; include_parent: boolean; mode: DockingMode };
  box: DockingResult["box"]; parameters: DockingResult["parameters"]; engine: DockingResult["engine"];
  preparation: DockingResult["preparation"]; limits: { max_candidates: number; per_candidate_s: number; total_s: number };
  status: DockingBatchStatus; stop_reason: DockingBatchStopReason | null; rows: DockingBatchRow[];
  counts: Record<"rows" | DockingBatchRowState, number>;
  limitations: { batch_statements: string[]; m18_sentences: number[] } }
/** Detail read: the validated summary, each row with `reused` (publication record) and `detail_available`. */
export interface DockingBatchDetail { schema: "docking_batch_detail@1"; handle: string; job_id: string;
  attempt_id: string; published_seq: number; reused_rows: number[]; score_label: string; score_column_label: string;
  statements: DockingBatchStatements; summary: DockingBatchResult;
  rows: (DockingBatchRow & { reused: boolean; detail_available: boolean })[]; meta: Record<string, unknown> }
/** Publication order. A summary that does not validate has `valid: false` and null fields. */
export interface DockingBatchListRow { handle: string; published_seq: number; valid: boolean; reason_code: string | null;
  job_id: string | null; attempt_id: string | null; reused_rows: number[] | null; method: DockingMethod | null;
  mode: DockingMode | null; status: DockingBatchStatus | null; stop_reason: DockingBatchStopReason | null;
  batch_input_sha256: string | null; include_parent: boolean | null; candidate_set_handle: string | null;
  counts: DockingBatchResult["counts"] | null }
export interface DockingBatchList { schema: "docking_batch_list@1"; total: number; offset: number; limit: number;
  rows: DockingBatchListRow[] }

/** Job progress (`batch` of the job record): finished = rows with a status file; reused rows are not run. Once a
 * summary is published, its validated `status`/`stop_reason` (null when it does not validate). */
export interface DockingBatchProgress { rows: number; reused_rows: number[]; finished_rows: number;
  summary_handle: string | null; summary_status: DockingBatchStatus | null;
  summary_stop_reason: DockingBatchStopReason | null }
export interface DockingBatchJob extends Omit<DockingJob, "protocol_id" | "artifacts"> {
  protocol_id: "qvina_batch_dock_v1"; artifacts: { docking_batch_result?: string }; batch: DockingBatchProgress }
export interface DockingBatchPlanOnly { plan_only: true; protocol_id: "qvina_batch_dock_v1"; reason_code: "dry_run";
  available: false; output_handles: []; normalized_parameters: Record<string, unknown> }
export type DockingBatchSubmission = DockingBatchJob | DockingBatchPlanOnly;
export interface DockingBatchReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "ligand_docking_batch"; result_handle: string;
  batch_status: DockingBatchStatus; snapshot: { event_seq: number } } & Record<string, unknown>; markdown: string }

// ---- M22 ligand GA design (backend/mw/ligand_ga_constants.py, ligand_ga_inputs.py, ligand_ga_jobs.py,
// ligand_ga_reads.py) ----
export type LigandGaKey = "seed" | "population_size" | "generations" | "elite_count" | "tournament_size" |
  "neighbor_count" | "random_fraction" | "patience" | "max_new_dockings" | "total_s";
export type LigandGaParameters = Record<LigandGaKey, number>;
export type LigandGaStatus = "complete" | "partial";
export type LigandGaStopReason = "generations_complete" | "no_change" | "pool_exhausted" | "docking_limit" |
  "time_exhausted" | "cancelled" | "worker_failed" | "resource_exceeded";
export type LigandGaOrigin = "initial" | "carried" | "similar" | "random";
export type LigandGaEvaluation = "reused" | "docked";
export type LigandGaState = "scored" | "null_result" | "failed";

/**
 * `qvina_ga_dock_v1` job arguments (fixed shape; unknown keys refused). The M18 receptor, box, parameter and
 * acknowledgement fields, the candidate set, its parent SDF, the M17 filter spec and every GA parameter. No `mode`
 * key (free docking is fixed) and no `ligand` key. `parameters.seed` is the docking seed; `ga.seed` the GA seed.
 */
export interface LigandGaArgs extends Omit<DockingArgs, "ligand" | "mode"> {
  candidate_set_handle: string;
  parent_sdf_handle: string;
  filter: LigandFilterSpec;
  ga: LigandGaParameters;
}

/** `methods.ligand_ga_design` of `/capabilities` (and the preflight's `capability`). */
export interface LigandGaCapability { schema: "ligand_ga_capability@1"; protocol_id: "qvina_ga_dock_v1";
  tool_id: "qvina_ga_design"; engine: "qvina"; execution_lane: string; available: boolean; status: string;
  reason_code: string | null; reason: string | null; pins: Record<string, unknown> | null;
  ga_pins: Record<string, string> | null; method?: DockingMethod;
  ga_ranges?: Record<LigandGaKey, { min: number; max: number; default: number | null }>;
  timeout_s?: { max: number; finish_margin: number };
  limits?: { max_pool: number; per_candidate_s: number; max_new_dockings: number; total_s_max: number;
    output_bytes: number; summary_bytes: number; reuse_staging_bytes: number };
  score_label?: string; score_row_label?: string; statements?: Record<string, string> }

export interface LigandGaStatement { id: string; text: string }
export interface LigandGaPoolCounts { size: number; eligible_count: number; filter_excluded_count: number }

/** `POST /runs/{id}/ligand/ga/preflight` (a read). A refused request has null numbers. */
export interface LigandGaPreflight { schema: "ligand_ga_preflight@1"; starts_job: false;
  capability: LigandGaCapability; score_label: string; budget: Record<"expensive_calls" | "wall_clock_s", BudgetAxis>;
  admission: { admitted: boolean; error: string | null; reason_code: string | null; message: string | null;
    detail: Record<string, unknown> | null };
  selection_sha256: string | null; pool: LigandGaPoolCounts | null; reusable_count: number | null;
  reserved_units: number | null; max_new_dockings_expected: number | null; needed: BudgetPair | null;
  remaining: BudgetPair; shortfall: BudgetPair | null; full_run_may_be_partial: boolean | null;
  ga: LigandGaParameters | null; statements: LigandGaStatement[] | null;
  existing_job: { job_id: string; status: string; summary_handle: string | null } | null }

/** `POST /runs/{id}/ligand/ga/limit_approval` (the person's explicit approval; idempotent). */
export interface LigandGaLimitApproval { raised: boolean; selection_sha256: string; reserved_units: number;
  needed: BudgetPair; shortfall_before: BudgetPair; increase: BudgetPair; limits_before: BudgetPair;
  limits_after: BudgetPair; shortfall_after: BudgetPair; event_seq: number | null; budget: BudgetSnapshot }

/** One individual of a generation (stored values; `carried` cites its first evaluation). */
export interface LigandGaIndividual { candidate_id: string; origin: LigandGaOrigin; parent_candidate_id: string | null;
  similarity: string | number | null; evaluation: LigandGaEvaluation | null; eval_index: number | null; state: LigandGaState;
  reason_code: string | null; score: number | null; result_handle: string | null }
export interface LigandGaGeneration { index: number; complete: boolean; individuals: LigandGaIndividual[];
  min_score: number | null; max_score: number | null }
export interface LigandGaResult { schema: "ligand_ga_result@1"; protocol: "qvina_ga_dock_v1"; engine: "qvina";
  candidate_set_handle: string; parent_sdf_handle: string; receptor: Record<string, unknown>;
  pins: Record<string, unknown>; call_key: string; selection_sha256: string; box: DockingResult["box"];
  parameters: DockingResult["parameters"]; filter: LigandFilterSpec; ga: LigandGaParameters;
  pool: LigandGaPoolCounts; status: LigandGaStatus; stop_reason: LigandGaStopReason; generations_done: number;
  new_dockings_used: number; reused_count: number; reserved_units: number; generations: LigandGaGeneration[];
  limitations: string[] }
/** Detail read: the validated summary; each individual carries `detail_available` (an M18 result handle). */
export interface LigandGaDetail { schema: "ligand_ga_detail@1"; handle: string; job_id: string; attempt_id: string;
  published_seq: number; score_label: string; score_column_label: string; score_row_label: string;
  statements: LigandGaStatement[]; summary: LigandGaResult;
  generations: (Omit<LigandGaGeneration, "individuals"> & {
    individuals: (LigandGaIndividual & { detail_available: boolean })[] })[];
  meta: Record<string, unknown> }
/** Newest first. A summary that does not validate has `valid: false` and null fields. */
export interface LigandGaListRow { handle: string; published_seq: number; valid: boolean; reason_code: string | null;
  job_id: string | null; attempt_id: string | null; status: LigandGaStatus | null;
  stop_reason: LigandGaStopReason | null; generations_done: number | null; new_dockings_used: number | null;
  reused_count: number | null; reserved_units: number | null; pool: LigandGaPoolCounts | null;
  candidate_set_handle: string | null; selection_sha256: string | null; ga: LigandGaParameters | null }
export interface LigandGaList { schema: "ligand_ga_list@1"; total: number; offset: number; limit: number;
  rows: LigandGaListRow[] }
/** `GET /runs/{id}/ligand/ga/results/{handle}/individual?candidate_id=…`: one individual and its M18 detail read. */
export interface LigandGaIndividualRead { schema: "ligand_ga_individual@1"; summary_handle: string;
  candidate_id: string; evaluation: LigandGaEvaluation | null; eval_index: number | null; state: LigandGaState;
  reason_code: string | null; score: number | null; result_handle: string | null;
  appearances: { generation: number; position: number; origin: LigandGaOrigin }[]; score_label: string;
  score_row_label: string; m18_detail: DockingResultDetail | null }

/** Job progress (`ga` of the job record): staged file counts only; the summary handle once published, with its
 * validated `status`/`stop_reason` (null when it does not validate). */
export interface LigandGaProgress { pool: LigandGaPoolCounts; reserved_units: number; reused_planned: number;
  individuals_started: number; individuals_result_files: number; individuals_finished: number; generation_records: number;
  generations_complete: number; summary_handle: string | null; summary_status: LigandGaStatus | null;
  summary_stop_reason: LigandGaStopReason | null }
export interface LigandGaJob extends Omit<DockingJob, "protocol_id" | "artifacts"> {
  protocol_id: "qvina_ga_dock_v1"; artifacts: { ligand_ga_result?: string }; ga: LigandGaProgress }
export interface LigandGaPlanOnly { plan_only: true; protocol_id: "qvina_ga_dock_v1"; reason_code: "dry_run";
  available: false; output_handles: []; normalized_parameters: Record<string, unknown> }
export type LigandGaSubmission = LigandGaJob | LigandGaPlanOnly;
export interface LigandGaReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "ligand_ga"; result_handle: string;
  ga_status: LigandGaStatus; snapshot: { event_seq: number } } & Record<string, unknown>; markdown: string }

// ---- M20 mutation candidates (backend/mw/mutation_constants.py, mutation_candidates.py, mutation_reads.py) ----
// M26 (spec 8): every new set is v2 (`mw.mutation_candidates/v2`); stored v1 sets stay valid byte for byte. The v2
// additions are the `catalytic_residue` reason, `parameters.catalytic_annotation`, `protection.catalytic` and the
// `catalytic_residue_database` check below; a v1 set has none of these keys (the check is `not_available`).
export type MutationSourceKind = "pocket" | "ligand_shell" | "user";
export type MutationProtectionReasonV1 = "user_protected" | "klifs_key_site" | "metal_contact" | "disulfide_cys";
export type MutationProtectionReason = MutationProtectionReasonV1 | "catalytic_residue";
export type MutationExclusionReason = "non_standard_residue" | MutationProtectionReason | "no_allowed_alternative";
export type MutationExclusionReasonV1 = Exclude<MutationExclusionReason, "catalytic_residue">;
export type MutationPositionStatus = "candidate" | "excluded";
export type MutationNumberingStatus = "mapped" | "unmapped" | "conflict" | "not_in_map";
export type MutationCheckStatus = "checked" | "not_checked" | "not_available";
/** `catalytic_residue_database.status`: `not_available` only for v1 sets, `not_checked` / `checked` for v2. */
export type MutationCatalyticStatus = "checked" | "not_checked" | "not_available";
/** `uncovered_chains[].coverage` (closed, M26 spec 8.3). */
export type MutationUncoveredCoverage = "chain_not_listed" | "pdb_not_in_snapshot" | "not_checked" | "not_in_annotation";
export type MutationPositionSort = "order" | "ligand_distance";

/**
 * `generate_mutation_candidates` arguments (spec 2). Residue references and the ligand selector carry all 7 identity
 * fields as listed by the structure (null kept); the server resolves them again and refuses unknown keys.
 */
export interface MutationRequestArgs {
  structure: string;
  sources: { pocket: { pocket_set: string; ranks: number[] } | null; ligand_shell: { radius_A: number } | null;
    residues: ExactResidueRef[] };
  ligand: ExactResidueRef | null;
  /** One-letter codes in "ACDEFGHIKLMNPQRSTVWY" order. */
  allowed_residues: string;
  protected_residues: ExactResidueRef[];
  released_residues: ExactResidueRef[];
  metal_contact_A: number;
  numbering_map: string | null;
  annotation: string | null;
  /** M26: null or a same-run `reaction_knowledge@1` handle of the same structure (always sent; null = not given). */
  catalytic_annotation: string | null;
}

export type MutationPositionSource = { kind: "pocket"; pocket_rank: number } | { kind: "ligand_shell"; radius_A: number } |
  { kind: "user" };
/** Stored numbering map row values (reference values, not computed); null when no map was given. */
export interface MutationNumbering { status: MutationNumberingStatus; uniprot_accession: string | null;
  uniprot_position: number | null; uniprot_residue: string | null; klifs_index: number | null; klifs_label: string | null }
export interface MutationPosition {
  index: number; residue: ExactResidueRef; standard_resname: string | null; one_letter: string | null;
  sources: MutationPositionSource[];
  /** null when no ligand was given (never 0). */
  ligand_min_distance_A: number | null;
  numbering: MutationNumbering | null;
  protection: { reasons: MutationProtectionReason[]; released: boolean;
    /** null = KLIFS key sites not checked (no annotation); [] = checked, none. */
    klifs_sites: string[] | null;
    metal: { min_distance_A: number; metal_residue: ExactResidueRef } | null;
    disulfide_partner: ExactResidueRef | null;
    /** v2 only (absent in v1): null = this chain was not checked; [] = checked, no `matched` M-CSA row names it. */
    catalytic?: MutationCatalyticEntry[] | null };
  exclusion_reasons: MutationExclusionReason[]; status: MutationPositionStatus; candidate_count: number;
  /** M29 page rows of a set on a repaired structure only (read layer, never stored). */
  modeled_basis?: boolean; reference_not_checked?: RepairReferenceField[];
}
export interface MutationCandidate { index: number; position_index: number; from: string; to: string }
/** One `matched` M-CSA row protecting a v2 position (reference identifiers, not computed). */
export interface MutationCatalyticEntry { mcsa_id: number; residue_index: number; is_reference: boolean }
/** One conflict / unmatched M-CSA row of a covered chain (`residue` null when the structure lookup found none). */
export interface MutationCatalyticItem { chain_auth: string; mcsa_id: number; residue_index: number; reason: string;
  residue: ExactResidueRef | null;
  listed: { chain_name: string; resid: number | null; auth_resid: number | null; code: string } }
/** v2 check with an annotation (`checked`, or `not_checked` / `chains_not_covered`). Row counts are the covered
 * chains' M-CSA counts summed; the server stores 0 when no chain is covered (that 0 is never shown as a count). */
export interface MutationCatalyticAnnotated { status: "checked" | "not_checked"; reason: "chains_not_covered" | null;
  annotation: string; covered_chains: string[];
  uncovered_chains: { chain_auth: string; coverage: MutationUncoveredCoverage }[];
  matched_rows: number; conflict_rows: number; unmatched_rows: number;
  conflicts: MutationCatalyticItem[]; unmatched: MutationCatalyticItem[] }
export type MutationCatalyticCheck =
  | { status: "not_available"; reason: "not_implemented" }
  | { status: "not_checked"; reason: "annotation_not_given"; annotation: null }
  | MutationCatalyticAnnotated;
export interface MutationProtectionChecks {
  user_list: { status: "checked"; protected: number; released: number };
  klifs_key_sites: { status: "checked" | "not_checked"; reason: "annotation_not_given" | null; annotation: string | null;
    annotated_sites: number | null; absent_sites: number | null };
  metal_contact: { status: "checked"; threshold_A: number; metal_residues: number; metal_names: string[] };
  disulfide: { status: "checked"; threshold_A: number; pairs: number };
  catalytic_residue_database: MutationCatalyticCheck;
}
export interface MutationCounts { positions: number; candidate_positions: number; excluded_positions: number;
  released_positions: number; candidates: number;
  /** v1: the six v1 reasons; v2: those plus `catalytic_residue`. */
  exclusion_reason_counts: Record<MutationExclusionReasonV1, number> & { catalytic_residue?: number };
  source_counts: Record<MutationSourceKind, number> }
/** `mutation_candidate_set@1` (spec 6). */
export interface MutationCandidateSet {
  schema: "mutation_candidate_set@1"; method_version: string;
  structure: { handle: string; model_number: number; structure_kind: "prepared_structure" };
  parameters: { sources: { pocket: { pocket_set: string; ranks: number[] } | null; ligand_shell: { radius_A: number } | null;
      residues: ExactResidueRef[] };
    ligand: ExactResidueRef | null; allowed_residues: string; protected_residues: ExactResidueRef[];
    released_residues: ExactResidueRef[]; metal_contact_A: number; disulfide_sg_A: number;
    numbering_map: string | null; annotation: string | null;
    /** v2 only (absent in v1). */
    catalytic_annotation?: string | null };
  ligand: { residue: ExactResidueRef; heavy_atom_count: number } | null;
  pockets: { pocket_set: string; ranks: number[]; lining_residue_count: number } | null;
  protection_checks: MutationProtectionChecks;
  released_residues: { residue: ExactResidueRef; effect: "released" | "none" }[];
  positions: MutationPosition[];
  candidates: MutationCandidate[];
  counts: MutationCounts;
  null_result: boolean;
  limitations: string[];
}
/** `GET /runs/{id}/mutation_candidate_sets` row, newest first. A row that does not validate: `valid: false`, nulls. */
export interface MutationCandidateSetListRow { handle: string; created_seq: number; valid: boolean;
  structure: string | null; model_number: number | null; ligand: MutationCandidateSet["ligand"];
  sources_used: Record<MutationSourceKind, boolean> | null; klifs_status: "checked" | "not_checked" | null;
  numbering_map: string | null; annotation: string | null; counts: MutationCounts | null; null_result: boolean | null;
  /** M26 spec 8.5: the stored catalytic check status (v1 `not_available`); null for a row that does not validate. */
  catalytic_status: MutationCatalyticStatus | null;
  /** M29: only for a valid row whose structure is a repaired structure. */
  structure_origin?: StructureOrigin }
export interface MutationCandidateSetList { schema: "mutation_candidate_set_list@1"; total: number; offset: number;
  limit: number; rows: MutationCandidateSetListRow[] }
/** `GET /runs/{id}/mutation_candidate_sets/{handle}`: the validated set without positions and candidates. */
export interface MutationCandidateSetDetail { schema: "mutation_candidate_set_detail@1"; handle: string;
  result: Omit<MutationCandidateSet, "positions" | "candidates">; total_positions: number; total_candidates: number;
  meta: Record<string, unknown>; catalytic_status: MutationCatalyticStatus;
  /** M29: only for a set on a repaired structure. */
  structure_origin?: StructureOrigin; repair_handoff?: RepairHandoff }
export interface MutationPositionPage { schema: "mutation_position_page@1"; handle: string;
  filters: { status: MutationPositionStatus | null; source: MutationSourceKind | null;
    exclusion_reason: MutationExclusionReason | null; chain_auth: string | null };
  sort: MutationPositionSort; total: number; offset: number; limit: number; rows: MutationPosition[];
  /** M29: only for a set on a repaired structure. */
  structure_origin?: StructureOrigin; repair_handoff?: RepairHandoff }
export interface MutationCandidateRow { index: number; position_index: number; residue: ExactResidueRef;
  standard_resname: string | null; from: string; to: string }
export interface MutationCandidatePage { schema: "mutation_candidate_page@1"; handle: string;
  filters: { position_index: number | null; to: string | null }; total: number; offset: number; limit: number;
  rows: MutationCandidateRow[]; structure_origin?: StructureOrigin }
export interface MutationReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "mutation_candidates"; result_handle: string;
  snapshot: { event_seq: number } } & Record<string, unknown>; markdown: string }

// ---- M21 mutation structure model (backend/mw/mutation_model_constants.py, mutation_model_bundle.py,
// mutation_model_reads.py, mutation_model_reports.py; `.dryforge/spec.md` 2, 4, 6, 7, 8) ----
export type MutationModelSide = "wild_type_reference" | "mutant";

/** `openmm_mutation_model_v1` job arguments (spec 2; unknown keys refused). `timeout_s` is a top-level job field. */
export interface MutationModelArgs {
  candidate_set: string;
  /** `candidates[].index` of the M20 set (never found by from/to letters). */
  candidate_index: number;
  seed: number;
  selection_policy: "protein_only";
  hydrogen_policy: "rebuild_pH7";
  contact_cutoff_A: number;
}

/** `methods.mutation_model` of `/capabilities`: unavailable carries the closed reason and no versions. */
export interface MutationModelCapability { schema: "mutation_model_capability@1"; protocol_id: "openmm_mutation_model_v1";
  tool_id: "openmm_mutation_model"; execution_lane: string; result_schema: "mutation_model@1"; method_version: string;
  timeout_s: { default: number; max: number }; contact_cutoff_A: { default: number; min: number; max: number };
  limits: { protein_heavy_atoms: number; contact_rows_per_structure: number; output_bytes: number };
  available: boolean; reason_code: string | null; reason: string | null;
  versions: { openmm: string; openmm_engine_build: string; pdbfixer: string } | null }

/** The M20 candidate a model was built from: original 7 fields of the position residue, letters, mutant name. */
export interface MutationModelCandidate { candidate_set: string; candidate_index: number; position_index: number;
  from: string; to: string; residue: ExactResidueRef; mutant_resname: string }
export interface MutationModelParameters { seed: number; contact_cutoff_A: number; selection_policy: "protein_only";
  hydrogen_policy: "rebuild_pH7" }
/** Stored OpenMM potential of one structure (kJ/mol, engine values; no change or difference is stored). */
export interface MutationModelEnergy { before_kJ_mol: number; after_kJ_mol: number; unit: "kJ/mol"; engine: "OpenMM";
  force_field: "amber14-all + implicit/gbn2"; convergence: "convergence_not_claimed" }
/** One structure entry of the detail read (no contact rows, `final_bonds` or `atom_mapping`). */
export interface MutationModelStructureSummary { structure_object: string; structure_sha256: string;
  system_xml_sha256: string; topology_sha256: string; heavy_atoms: number; added_hydrogens: number;
  added_heavy_atoms: { atom_name: string; element: string }[];
  protonation_variants: { residue: ExactResidueRef; variant: string | null }[];
  disulfide_bonds: [ExactResidueRef, ExactResidueRef][];
  energy: MutationModelEnergy;
  sasa: { residue: ExactResidueRef; engine: "FreeSASA"; value_A2: number; parameters: Record<string, unknown> };
  contacts: { cutoff_A: number; excluded_bond_distance: number; count: number; residue_count: number } }
export interface MutationModelComparison { mutated_residue: ExactResidueRef;
  resnames: Record<MutationModelSide, string>; new_disulfide_in_mutant: boolean; protonation_difference_count: number }
/** `mutation_model@1` as the detail read returns it (validated; rows left out). */
export interface MutationModelResult { schema: "mutation_model@1"; method_version: string;
  candidate: MutationModelCandidate;
  structure: { handle: string; model_number: number; structure_kind: "prepared_structure" };
  parameters: MutationModelParameters; method: Record<string, unknown>;
  excluded_components: { reason: string; residue_count: number; atom_count: number }[];
  structures: Record<MutationModelSide, MutationModelStructureSummary>;
  comparison: MutationModelComparison;
  protonation_differences: { residue: ExactResidueRef; wild_type_reference: string | null; mutant: string | null }[];
  limitations: string[] }
export interface MutationModelDetail { schema: "mutation_model_detail@1"; handle: string; result: MutationModelResult;
  meta: Record<string, unknown>;
  /** M29: only for a model on a repaired structure. */
  structure_origin?: StructureOrigin }
/** `GET /runs/{id}/mutation_models` row, newest first; a row that does not validate: `valid: false`, nulls. */
export interface MutationModelListRow { handle: string; created_seq: number; valid: boolean;
  candidate: Omit<MutationModelCandidate, "position_index"> | null;
  structure: MutationModelResult["structure"] | null; parameters: MutationModelParameters | null;
  structure_origin?: StructureOrigin }
export interface MutationModelList { schema: "mutation_model_list@1"; total: number; offset: number; limit: number;
  rows: MutationModelListRow[] }
/** One stored contact row (heavy atoms, distance in Å, float64 as stored; not a hydrogen bond). */
export interface MutationModelContactRow { index: number; atom_name: string; element: string;
  partner_residue: ExactResidueRef; partner_atom_name: string; partner_element: string; distance_A: number }
export interface MutationModelContactPage { schema: "mutation_model_contact_page@1"; handle: string;
  structure: MutationModelSide; mutated_residue: ExactResidueRef; cutoff_A: number; excluded_bond_distance: number;
  total: number; page: number; page_size: number; rows: MutationModelContactRow[] }

/** Closed reason set of a docking pair side that shows no score (mutation_model_reads.PAIR_REASONS). */
export type MutationModelPairReason = "not_submitted" | "job_not_finished" | "job_failed" | "job_cancelled" |
  "job_interrupted" | "result_invalid" | "other_side_missing" | "no_modes";
export interface MutationModelPairSide { side: MutationModelSide; job_id: string | null; job_status: string;
  submitted_seq: number | null; result_handle: string | null;
  /** Stored first mode row score; non-null only when both sides are published, validated results. */
  score_kcal_mol: number | null; score_mode: number | null;
  reason_code: MutationModelPairReason | null; reason: string | null }
export interface MutationModelPairCondition { ligand: DockingArgs["ligand"]; mode: DockingMode;
  box: DockingSourceArgs["box"] | { source: "instance_range"; margin_A: number };
  parameters: { seed: number; exhaustiveness: number; num_modes: number; energy_range: number; conformers: number | null };
  method_pins_sha256: string }
export interface MutationModelPair { index: number; first_submitted_seq: number; condition: MutationModelPairCondition;
  both_published: boolean; sides: Record<MutationModelSide, MutationModelPairSide> }
/** `GET /runs/{id}/mutation_models/{handle}/docking_pairs` (spec 7): every condition group, none picked. */
export interface MutationModelDockingPairs { schema: "mutation_model_docking_pairs@1"; handle: string;
  score_label: string; total: number; pairs: MutationModelPair[]; starts_job: false }

export interface MutationModelJob { job_id: string; run_id: string; protocol_id: "openmm_mutation_model_v1";
  tool_id: string; status: string; blocked_reason: string | null;
  failure: { error: string; message: string; reason_code?: string; detail?: Record<string, unknown> } | null;
  input_handles: string[]; output_handles: string[]; attempt_ordinal: number; cancel_requested: boolean;
  timeout_s: number; artifacts?: { mutation_model?: string } }
/** Dry-run submission: a plan only, no job and no result object. */
export interface MutationModelPlanOnly { plan_only: true; protocol_id: "openmm_mutation_model_v1"; reason_code: "dry_run";
  available: false; output_handles: []; normalized_parameters: Record<string, unknown> }
export type MutationModelSubmission = MutationModelJob | MutationModelPlanOnly;
export interface MutationModelReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "mutation_model"; result_handle: string;
  snapshot: { event_seq: number } } & Record<string, unknown>; markdown: string }

// ---- M23 sequence GA design (backend/mw/sequence_ga_constants.py, sequence_ga_inputs.py, sequence_ga_jobs.py,
// sequence_ga_reads.py, sequence_model_bundle.py; `.dryforge/spec.md` 2, 3, 4, 7, 9) ----
export type SequenceGaKey = "seed" | "population_size" | "generations" | "elite_count" | "tournament_size" |
  "crossover_fraction" | "random_fraction" | "max_mutations" | "patience" | "max_new_evaluations" | "total_s";
export type SequenceGaParameters = Record<SequenceGaKey, number>;
export type SequenceGaStatus = "complete" | "partial";
export type SequenceGaStopReason = "generations_complete" | "no_change" | "space_exhausted" | "evaluation_limit" |
  "time_exhausted" | "cancelled" | "worker_failed" | "resource_exceeded" | "reference_failed" | "repeated_failure";
export type SequenceGaOrigin = "initial" | "carried" | "crossover" | "edit" | "random";
export type SequenceGaEditOp = "add" | "change" | "move" | "remove";
export type SequenceGaEvaluation = "reused" | "computed";
export type SequenceGaState = "scored" | "null_result" | "failed";

/**
 * `sequence_ga_dock_v1` job arguments (fixed shape; unknown keys refused). No `mode` (free docking is fixed), no
 * receptor key (each individual's receptor is its own model) and no candidate ligand source. `parameters.seed` is the
 * evaluation seed (modeling and docking); `ga.seed` the GA seed. `timeout_s` (= `ga.total_s + 600`) is the top-level
 * `POST /jobs` field.
 */
export interface SequenceGaArgs {
  candidate_set: string;
  ligand: { source: "sdf"; sdf_handle: string };
  box: DockingSourceArgs["box"];
  parameters: { seed: number; exhaustiveness: number; num_modes: number; energy_range: number };
  selection_policy: "protein_only";
  hydrogen_policy: "rebuild_pH7";
  acknowledgement: Record<DockingAcknowledgementKey, true>;
  ga: SequenceGaParameters;
}

/** `methods.sequence_ga_design` of `/capabilities` (and the preflight's `capability`); unavailable: reason only. */
export interface SequenceGaCapability { schema: "sequence_ga_capability@1"; protocol_id: "sequence_ga_dock_v1";
  tool_id: "sequence_ga_design"; engine: "qvina"; execution_lane: string; result_schema: "sequence_ga_result@1";
  model_schema: "mutation_set_model@1"; available: boolean; status: string; reason_code: string | null;
  reason: string | null; pins: Record<string, unknown> | null; versions: Record<string, unknown> | null;
  ga_ranges?: Record<SequenceGaKey, { min: number; max: number; default: number | null }>;
  timeout_s?: { max: number; finish_margin: number }; limits?: Record<string, number>; units_per_evaluation?: number;
  score_label?: string; score_row_label?: string; statements?: Record<string, string>; model_limitations?: string[] }

export interface SequenceGaStatement { id: string; text: string }
/** The combination space (server values: `size` is the exact count N; `effective_max_mutations` = min(cap, P)). */
export interface SequenceGaSpace { positions: number; candidates: number; effective_max_mutations: number; size: number }

/** `POST /runs/{id}/sequence_ga/preflight` (a read). A refused request (steps 1-8) has null numbers. */
export interface SequenceGaPreflight { schema: "sequence_ga_preflight@1"; starts_job: false;
  capability: SequenceGaCapability; score_label: string; budget: Record<"expensive_calls" | "wall_clock_s", BudgetAxis>;
  remaining: BudgetPair;
  admission: { admitted: boolean; error: string | null; reason_code: string | null; message: string | null;
    detail: Record<string, unknown> | null };
  selection_sha256: string | null; conditions_sha256: string | null; space: SequenceGaSpace | null;
  projection_heavy_atoms: number | null; heavy_atom_warning: boolean | null; reusable_count: number | null;
  reference_reusable: boolean | null; reserved_evaluations: number | null; reserved_units: number | null;
  needed: BudgetPair | null; shortfall: BudgetPair | null; full_run_may_be_partial: boolean | null;
  ga: SequenceGaParameters | null; statements: SequenceGaStatement[] | null;
  existing_job: { job_id: string; status: string; summary_handle: string | null } | null }

/** `POST /runs/{id}/sequence_ga/limit_approval` (the person's explicit approval; idempotent). */
export interface SequenceGaLimitApproval { raised: boolean; selection_sha256: string; reserved_evaluations: number;
  reserved_units: number; needed: BudgetPair; shortfall_before: BudgetPair; increase: BudgetPair;
  limits_before: BudgetPair; limits_after: BudgetPair; shortfall_after: BudgetPair; event_seq: number | null;
  budget: BudgetSnapshot }

/** One mutation of an individual (the server fills it from the M20 candidate set; 7 fields as stored). */
export interface SequenceGaMutation { candidate_index: number; residue: ExactResidueRef; from: string; to: string }
/** One individual of a generation (stored values; `carried` cites its first evaluation). Key = candidate indices. */
export interface SequenceGaIndividual { key: string; mutations: SequenceGaMutation[]; origin: SequenceGaOrigin;
  parents: string[] | null; edit_op: SequenceGaEditOp | null; evaluation: SequenceGaEvaluation | null;
  pick_index: number; eval_index: number | null; state: SequenceGaState; reason_code: string | null;
  score: number | null; model_handle: string | null; result_handle: string | null }
/** The wild-type reference row (key `wild_type`): not an individual, never sorted with them. */
export interface SequenceGaReference { evaluation: SequenceGaEvaluation; state: SequenceGaState;
  reason_code: string | null; score: number | null; model_handle: string | null; result_handle: string | null }
export interface SequenceGaGeneration { index: number; complete: boolean; individuals: SequenceGaIndividual[];
  min_score: number | null; max_score: number | null }
/** `sequence_ga_result@1` (validated on every read). `limitations` holds the S sentence ids. */
export interface SequenceGaResult { schema: "sequence_ga_result@1"; protocol: "sequence_ga_dock_v1"; engine: "qvina";
  candidate_set: string; structure: { handle: string; model_number: number };
  ligand: { sdf_handle: string; sdf_sha256: string }; box: DockingResult["box"] | null;
  parameters: { seed: number; exhaustiveness: number; num_modes: number; energy_range: number; cpu: 1 };
  selection_policy: "protein_only"; hydrogen_policy: "rebuild_pH7";
  method: { model: Record<string, unknown>; docking: Record<string, unknown> }; pins: Record<string, unknown>;
  call_key: string; conditions_sha256: string; selection_sha256: string; ga: SequenceGaParameters;
  space: SequenceGaSpace; status: SequenceGaStatus; stop_reason: SequenceGaStopReason; generations_done: number;
  new_evaluations_used: number; reused_count: number; reserved_evaluations: number; reserved_units: number;
  reference: SequenceGaReference; generations: SequenceGaGeneration[]; limitations: string[] }
/** Detail read: the validated summary; each row carries `detail_available` (an M18 result handle exists). */
export interface SequenceGaDetail { schema: "sequence_ga_detail@1"; handle: string; job_id: string; attempt_id: string;
  published_seq: number; score_label: string; score_column_label: string; score_row_label: string;
  statements: SequenceGaStatement[]; summary: SequenceGaResult;
  generations: (Omit<SequenceGaGeneration, "individuals"> & {
    individuals: (SequenceGaIndividual & { detail_available: boolean })[] })[];
  reference: SequenceGaReference & { detail_available: boolean }; meta: Record<string, unknown>;
  /** M29: only when the GA's candidate set is on a repaired structure (screen only; the report is unchanged). */
  structure_origin?: StructureOrigin }
/** Newest first. A summary that does not validate has `valid: false` and null fields. */
export interface SequenceGaListRow { handle: string; published_seq: number; valid: boolean; reason_code: string | null;
  job_id: string | null; attempt_id: string | null; status: SequenceGaStatus | null;
  stop_reason: SequenceGaStopReason | null; generations_done: number | null; new_evaluations_used: number | null;
  reused_count: number | null; reserved_units: number | null; space: SequenceGaSpace | null;
  candidate_set: string | null; selection_sha256: string | null; ga: SequenceGaParameters | null;
  structure_origin?: StructureOrigin }
export interface SequenceGaList { schema: "sequence_ga_list@1"; total: number; offset: number; limit: number;
  rows: SequenceGaListRow[] }

/** One structure entry of `mutation_set_model@1` without its atom and bond rows (no SASA or contacts). */
export interface SequenceGaModelStructure { structure_object: string; structure_sha256: string;
  system_xml_sha256: string; topology_sha256: string; heavy_atoms: number; added_hydrogens: number;
  /** Per mutated residue, the residue's 7 fields (mutant name) with each PDBFixer-placed heavy atom. */
  added_heavy_atoms: { residue: ExactResidueRef; atom_name: string; element: string }[];
  protonation_variants: { residue: ExactResidueRef; variant: string | null }[];
  disulfide_bonds: [ExactResidueRef, ExactResidueRef][]; energy: MutationModelEnergy }
/** `mutation_set_model@1` as the individual read returns it (validated; rows left out). One structure key. */
export interface SequenceGaModel { schema: "mutation_set_model@1"; method_version: string; candidate_set: string;
  structure: { handle: string; model_number: number; structure_kind: "prepared_structure" };
  mutations: (SequenceGaMutation & { mutant_resname: string })[]; seed: number; method: Record<string, unknown>;
  structures: Partial<Record<MutationModelSide, SequenceGaModelStructure>>;
  protonation_differences: { residue: ExactResidueRef; wild_type_reference: string | null; mutant: string | null }[];
  new_disulfide_in_mutant: boolean; reference_structure_sha256: string | null; limitations: string[] }
/** `GET /runs/{id}/sequence_ga/results/{handle}/individual?key=…` (key `12-57-203` or `wild_type`). */
export interface SequenceGaIndividualRead { schema: "sequence_ga_individual@1"; summary_handle: string; key: string;
  mutations: SequenceGaMutation[]; is_reference: boolean; eval_index: number | null; pick_index: number | null;
  evaluation: SequenceGaEvaluation | null; state: SequenceGaState; reason_code: string | null; score: number | null;
  model_handle: string | null; result_handle: string | null;
  appearances: { generation: number; position: number; origin: SequenceGaOrigin }[]; model: SequenceGaModel | null;
  statements: SequenceGaStatement[]; score_label: string; score_row_label: string;
  m18_detail: Omit<DockingResultDetail, "meta"> | null }

/** Job progress (`sequence_ga` of the job record): staged file counts only; the summary handle once published, with
 * its validated `status`/`stop_reason` (null when it does not validate). */
export interface SequenceGaProgress { space: SequenceGaSpace; reserved_evaluations: number; reserved_units: number;
  reused_planned: number; reference_reuse_planned: boolean; reference_recorded: boolean; individuals_started: number;
  individuals_finished: number; generation_records: number; generations_complete: number;
  summary_handle: string | null; summary_status: SequenceGaStatus | null;
  summary_stop_reason: SequenceGaStopReason | null }
/** `sequence_ga` is in the job list, job read and start responses; submit, retry and cancel responses have none. */
export interface SequenceGaJob extends Omit<DockingJob, "protocol_id" | "artifacts"> {
  protocol_id: "sequence_ga_dock_v1"; artifacts: { sequence_ga_result?: string }; sequence_ga?: SequenceGaProgress }
export interface SequenceGaPlanOnly { plan_only: true; protocol_id: "sequence_ga_dock_v1"; reason_code: "dry_run";
  available: false; output_handles: []; normalized_parameters: Record<string, unknown> }
export type SequenceGaSubmission = SequenceGaJob | SequenceGaPlanOnly;
export interface SequenceGaReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "sequence_ga"; result_handle: string;
  ga_status: SequenceGaStatus; snapshot: { event_seq: number } } & Record<string, unknown>; markdown: string }

// ---- M24 JEV science sends (backend/mw/jev_constants.py, jev_sends.py, jev_reports.py, tools/jev.py;
// `.dryforge/spec.md` 3, 5-9). Every route is under `/runs/{id}/jev/...`; errors are `{"detail": {error, message, ...}}`.
export type JevKind = "ligand" | "mutation";
export type JevQuestionId = "ligand_candidate_choice@1" | "mutation_candidate_choice@1";
/** `jev_preview@1.blocked_by` (closed, in this order). */
export type JevPreviewBlockReason = "dry_run" | "consent_off" | "cancelled" | "egress_stopped" | "send_cap_exhausted" |
  "budget_exhausted" | "send_in_progress";
export type JevRejectedReason = "dry_run" | "consent_off" | "cancelled" | "egress_stopped" | "send_cap_exhausted" |
  "budget_exhausted" | "missing_configuration" | "missing_credential";
export type JevFailedReason = "external_timeout" | "transport_error" | "provider_http_error" | "response_invalid" |
  "missing_model" | "model_mismatch" | "delivery_unknown" | "outcome_not_recorded";
export type JevLateReason = "run_cancelled" | "consent_off";
/** Stored statuses plus the read-only derived `in_progress` (never stored). */
export type JevSendStatus = "completed" | "rejected" | "failed" | "in_progress";
/** `build_jev_projection` admission reasons (`detail.reason_code`, in check order) and the read refusal. */
export type JevProjectionReason = "unknown_field" | "source_invalid" | "selection_invalid" | "candidate_unknown" |
  "filter_invalid" | "candidate_filtered_out" | "structure_unavailable" | "wire_field_invalid" | "payload_too_large" |
  "projection_invalid";

export interface JevBudgetAxis { used: number; limit: number; remaining: number }
/** `GET /runs/{id}/jev/status` and the `POST .../jev/consent` answer (no key is read). */
export interface JevStatusV1 { schema: "jev_status@1"; enabled: boolean; policy: "jev_science@1"; send_cap: number;
  used: number; remaining: number; budget: { external_tokens: JevBudgetAxis; usd: JevBudgetAxis };
  egress_stop_reason: string | null; dry_run: boolean; cancelled: boolean; question_ids: JevQuestionId[];
  send_in_progress: boolean; request_model: string; allowed_served_model: string; destination: string }
/** Alias of the sent list -> local reference (local only, never sent). */
export type JevSelectionItem = { alias: string; candidate_id: string } |
  { alias: string; candidate_index: number; position_index: number };
/** `POST /runs/{id}/jev/preview {projection}`: the exact body string the approved send would carry. */
export interface JevPreviewV1 { schema: "jev_preview@1"; projection_handle: string; kind: JevKind;
  source: { handle: string; schema: string };
  question: { id: JevQuestionId; key: "candidate_choice"; type: "choice"; instructions: string;
    instructions_sha256: string };
  body: string; body_sha256: string; body_bytes: number; selection: JevSelectionItem[]; selection_sent: false;
  reservation: { external_tokens: number; usd: number }; send_cap: number; used: number; remaining: number;
  budget_remaining: { external_tokens: number; usd: number }; blocked_by: JevPreviewBlockReason[];
  previous_sends: number;
  /** M29: mutation candidates on a repaired structure only (never in the body). */
  structure_origin?: StructureOrigin; repair_warning?: RepairWarning }
/** Reported usage; every value null when the reply did not report it (never 0). */
export interface JevUsage { input_tokens: number | null; output_tokens: number | null; external_tokens: number | null;
  cost: number | null }
/** `POST /runs/{id}/jev/sends` body (unknown keys refused, at most 4 KiB). */
export interface JevSendRequest { send_id: string; projection: string; body_sha256: string; confirm: "send_to_jev" }
/** One send record (`POST .../jev/sends` answer, list row, detail base); refusals and failures are HTTP 200 too. */
export interface JevSendV1 { schema: "jev_send@1"; send_id: string; status: JevSendStatus;
  reason_code: JevRejectedReason | JevFailedReason | null; projection_handle: string;
  source: { handle: string; schema: string }; kind: JevKind; question_id: JevQuestionId; selection_count: number;
  body_sha256: string; body_bytes: number | null; audit_id: string | null; requested_model: string | null;
  served_model: string | null; usage: JevUsage | null; choice_handle: string | null; late: boolean;
  late_reason: JevLateReason | null; approved_event_seq: number; outcome_event_seq: number | null;
  /** M29: reads of a mutation send on a repaired structure; JW1 on the approval answer only. */
  structure_origin?: StructureOrigin; repair_warning?: RepairWarning }
/** The 7 identity fields as stored (null kept; an empty insertion code stays ""). */
export interface JevResidue { model_number: number; chain_auth: string | null; chain_label: string | null;
  seq_auth: number; seq_label: number | null; icode: string | null; resname: string }
export type JevLocalRef = { candidate_id: string } | { candidate_index: number; position_index: number };
/** The chosen candidate's local notation copied from the stored candidate set. */
export type JevLocalDisplay = { smiles: string } | { residue: JevResidue; from: string; to: string };
/** `jev_choice@1`: a proposal, never a scientific result; the answer exactly as received (no reorder, no rounding). */
export interface JevChoiceV1 { schema: "jev_choice@1"; method_version: "mw.jev_choice/v1"; label: string;
  scientific_result: false; send: { send_id: string; audit_id: string }; source: { handle: string; schema: string };
  projection: { handle: string; wire_sha256: string; body_sha256: string; body_bytes: number };
  question: { id: JevQuestionId; key: "candidate_choice"; instructions_sha256: string };
  requested_model: string; served_model: string; selection: JevSelectionItem[];
  answer: { choice_alias: string; local_ref: JevLocalRef; local_display: JevLocalDisplay; confidence: number | null;
    probabilities: Record<string, number> | null };
  usage: JevUsage | null; arrival: { late: boolean; late_reason: JevLateReason | null }; limitations: string[] }
/** `GET /runs/{id}/jev/sends/{send_id}`: the record plus the re-validated proposal (null unless completed). */
export interface JevSendDetail extends JevSendV1 { choice: JevChoiceV1 | null; local_display: JevLocalDisplay | null }
/** `build_jev_projection` arguments: ligand candidate ids "c_" + 16 hex | mutation candidate indices (1-20). */
export interface JevProjectionArgs { source: string; candidates: string[] | number[]; filter: LigandFilterSpec | null }
/** Summary of a stored `jev_projection@1` (the command envelope's `handle.summary`). */
export interface JevProjectionSummary { kind: JevKind; source: string; selection_count: number; body_bytes: number;
  body_sha256: string }
export interface JevReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "jev_choice"; result_handle: string;
  snapshot: { event_seq: number } } & Record<string, unknown>; markdown: string }

// ---- M25 JEV design loop (backend/mw/jev_loop_constants.py, jev_loops.py, jev_loop_store.py, tools/jev_loop.py,
// jev_loop_projection.py, jev_sends.py loop branch, jev_loop_reports.py; `.dryforge/spec.md` 3-10). Loop routes are
// under `/runs/{id}/jev_loops`; their errors are `{"detail": {error, reason_code, message, ...}}`. The preview, the
// send and the send records are the M24 routes (a loop projection handle is accepted there).
export type JevLoopBranch = "ligand" | "protein";
export type JevLoopGoal = "explore" | "exploit";
/** A pool candidate: the ligand candidate id ("c_" + 16 hex) or the mutation candidate `index` (never a name). */
export type JevLoopRef = string | number;
export type JevLoopCandidateState = "pending" | "scored" | "null_result" | "failed" | "not_run" | "unavailable";
export type JevLoopEvaluation = "computed" | "reused";
export type JevLoopStep = "ligand_dock" | "model" | "dock";
export type JevLoopStepState = "waiting_start" | "running" | "completed" | "failed" | "unavailable" | "reused";
export type JevLoopIterationState = "in_progress" | "scored" | "null_result" | "failed" | "not_run" | "unavailable";
export type JevLoopPhase = "awaiting_selection" | "awaiting_compute" | "running" | "awaiting_docking" | "done";
export type JevLoopAction = "select" | "compute" | "wait_job" | "dock" | "end" | "none";
export type JevLoopDecidedBy = "jev" | "human";
export type JevLoopExhaustedReason = "iteration_cap" | "pool_exhausted";
export type JevLoopEndReason = "iteration_cap" | "pool_exhausted" | "ended_by_user" | "budget_exhausted" | "run_cancelled";
export type JevLoopComputeAxis = "expensive_units" | "wall_clock_s";
export type JevLoopSendAxis = "external_tokens" | "usd" | "sends";
export type JevLoopAxis = JevLoopComputeAxis | JevLoopSendAxis;
export type JevLoopQuestionId = "ligand_loop_choice@1" | "mutation_loop_choice@1";
/** `loop_send_invalid` `detail.reason` (closed, in check order) and the preview's `loop_blocks`. */
export type JevLoopSendReason = "loop_not_found" | "loop_ended" | "iteration_mismatch" | "selection_done" |
  "phase_invalid" | "cap_reached" | "too_few_candidates" | "state_changed" | "ordinal_mismatch";
/** Needs and remaining amounts of the next action (server values; tokens and USD only with a preview reservation). */
export interface JevLoopAmounts { expensive_units: number; wall_clock_s: number; external_tokens: number | null;
  usd: number | null; sends: number }
export interface JevLoopCandidate { ref: JevLoopRef; display: JevLocalDisplay; state: JevLoopCandidateState;
  evaluation: JevLoopEvaluation | null; score_kcal_mol: number | null; iteration: number | null }
export interface JevLoopApproval { step: JevLoopStep; candidate_ref: JevLoopRef; decided_by: JevLoopDecidedBy;
  proposal_handle: string | null; call_key: string }
export interface JevLoopIterationSend { send_id: string; status: JevSendStatus; send_ordinal: number;
  proposal_handle: string | null; late: boolean }
export interface JevLoopStepRow { step: JevLoopStep; candidate_ref: JevLoopRef; job_id: string | null; call_key: string;
  result_handle: string | null; state: JevLoopStepState; reason_code: string | null;
  evaluation: JevLoopEvaluation | null }
export interface JevLoopIteration { index: number; phase: JevLoopPhase; decided_by: JevLoopDecidedBy | null;
  candidate_ref: JevLoopRef | null; proposal_handle: string | null; list_position: number | null;
  list_size: number | null; approvals: JevLoopApproval[]; sends: JevLoopIterationSend[]; steps: JevLoopStepRow[];
  state: JevLoopIterationState; score_kcal_mol: number | null }
export interface JevLoopJob { job_id: string; step: JevLoopStep; status: string; start_blocked: "approval_required" | null }
export interface JevLoopCurrent { iteration: number | null; phase: JevLoopPhase | null; step: JevLoopStep | null;
  action: JevLoopAction; needs: JevLoopAmounts; remaining: JevLoopAmounts; blocked_axes: JevLoopComputeAxis[];
  send_blocked_axes: JevLoopSendAxis[]; can_end: boolean; job: JevLoopJob | null }
export interface JevLoopCounts { started: number; done: number; jev_decided: number; human_decided: number;
  sends_dispatched: number; units_charged: number; reused_count: number }
export interface JevLoopPool { source: { handle: string; schema: string };
  structure: { handle: string; model_number: number } | null; filter: LigandFilterSpec | null;
  candidates: { ref: JevLoopRef; display: JevLocalDisplay }[] }
/** `jev_loop@1` (read-only, never stored): `GET /runs/{id}/jev_loops/{loop_id}` and every loop write's answer. */
export interface JevLoopV1 { schema: "jev_loop@1"; loop_id: string; branch: JevLoopBranch; status: "active" | "ended";
  end_reason: JevLoopEndReason | null; exhausted_reason: JevLoopExhaustedReason | null; goal: JevLoopGoal;
  loop_seed: number; iteration_cap: number; effective_cap: number; pool: JevLoopPool; setup: Record<string, unknown>;
  setup_sha256: string; pins: Record<string, unknown>; counts: JevLoopCounts; candidates: JevLoopCandidate[];
  iterations: JevLoopIteration[]; current: JevLoopCurrent; result_handle: string | null; limitations: string[];
  /** M29: a protein loop whose candidate set is on a repaired structure. */
  structure_origin?: StructureOrigin }
/** `GET /runs/{id}/jev_loops` row (newest first). */
export interface JevLoopListRow { loop_id: string; branch: JevLoopBranch; status: "active" | "ended";
  end_reason: JevLoopEndReason | null; goal: JevLoopGoal; pool_size: number; counts: JevLoopCounts; created_seq: number;
  structure_origin?: StructureOrigin }
/** `methods.jev_loop` of `/capabilities`: per branch, reasons only when unavailable. */
export type JevLoopCapability = Record<JevLoopBranch, { available: boolean; reason_code: string | null;
  reason: string | null }>;
/** Ligand setup: the M22 shared M18 fields (free docking, no `ligand` / `mode`) and the candidate set's parent SDF. */
export interface JevLoopLigandSetup extends Omit<DockingArgs, "ligand" | "mode"> { parent_sdf_handle: string }
/** Protein setup: the 3D SDF ligand, the M18 box / free values / acknowledgements, the two M21 literals, the cutoff. */
export interface JevLoopProteinSetup { ligand: { source: "sdf"; sdf_handle: string }; box: DockingSourceArgs["box"];
  parameters: { seed: number; exhaustiveness: number; num_modes: number; energy_range: number };
  selection_policy: "protein_only"; hydrogen_policy: "rebuild_pH7";
  acknowledgement: Record<DockingAcknowledgementKey, true>; contact_cutoff_A: number }
export interface JevLoopPoolArgs { source: string; candidates: string[] | number[]; filter: LigandFilterSpec | null }
/** `POST /runs/{id}/jev_loops` body (closed keys, at most 16 KiB). */
export interface JevLoopCreateRequest { loop_id: string; branch: JevLoopBranch; pool: JevLoopPoolArgs; goal: JevLoopGoal;
  loop_seed: number; iteration_cap: number; setup: JevLoopLigandSetup | JevLoopProteinSetup }
/** `POST .../compute`: a first step names exactly one of proposal or candidate; the docking step names neither. */
export type JevLoopComputeRequest = { iteration: number } | { iteration: number; proposal: string } |
  { iteration: number; candidate: JevLoopRef };
export interface JevLoopAbandonRequest { iteration: number }
/** `build_jev_loop_projection` arguments (everything else is read from the loop record by the server). */
export interface JevLoopProjectionArgs { loop_id: string; iteration: number }
/** Summary of a stored `jev_loop_projection@1` (the command envelope's `handle.summary`). */
export interface JevLoopProjectionSummary { kind: JevKind; loop_id: string; iteration: number; send_ordinal: number;
  selection_count: number; body_bytes: number; body_sha256: string }
/** Local alias table of a loop projection (never sent); `unavailable` candidates are never listed. */
export interface JevLoopSelectionItem { alias: string; ref: JevLoopRef;
  state: Exclude<JevLoopCandidateState, "unavailable"> }
export interface JevLoopSendLoopRef { loop_id: string; iteration: number; send_ordinal: number }
/** The `jev_preview@1` of a loop projection: the M24 fields plus `loop` (send-side amounts) and `loop_blocks`. */
export interface JevLoopPreviewV1 extends Omit<JevPreviewV1, "question" | "selection"> {
  question: { id: JevLoopQuestionId; key: "candidate_choice"; type: "choice"; instructions: string;
    instructions_sha256: string };
  selection: JevLoopSelectionItem[];
  loop: JevLoopSendLoopRef & { needs: JevLoopAmounts | null; remaining: JevLoopAmounts | null;
    send_blocked_axes: JevLoopSendAxis[] | null };
  loop_blocks: JevLoopSendReason[] }
/** `jev_loop_choice@1`: a proposal, never a scientific result; the answer exactly as received. */
export interface JevLoopChoiceV1 { schema: "jev_loop_choice@1"; method_version: "mw.jev_loop_choice/v1"; label: string;
  scientific_result: false; loop: JevLoopSendLoopRef; goal: JevLoopGoal; send: { send_id: string; audit_id: string };
  source: { handle: string; schema: string };
  projection: { handle: string; wire_sha256: string; body_sha256: string; body_bytes: number };
  question: { id: JevLoopQuestionId; key: "candidate_choice"; instructions_sha256: string };
  requested_model: string; served_model: string; selection: JevLoopSelectionItem[];
  answer: { choice_alias: string; list_position: number; list_size: number; local_ref: JevLocalRef;
    local_display: JevLocalDisplay; confidence: number | null; probabilities: Record<string, number> | null };
  usage: JevUsage | null; arrival: { late: boolean; late_reason: JevLateReason | null }; limitations: string[] }
/** A loop send's `jev_send@1` record: the M24 fields plus `loop` (null when its projection does not read back). */
export interface JevLoopSendRecord extends Omit<JevSendV1, "question_id"> { question_id: JevLoopQuestionId;
  loop: JevLoopSendLoopRef | null }
/** `GET /runs/{id}/jev/sends/{send_id}` of a loop send: the record plus its re-validated `jev_loop_choice@1`. */
export interface JevLoopSendDetail extends JevLoopSendRecord { choice: JevLoopChoiceV1 | null;
  local_display: JevLocalDisplay | null }
export interface JevLoopReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "jev_loop"; result_handle: string;
  snapshot: { event_seq: number } } & Record<string, unknown>; markdown: string }

// ---- M26 reaction knowledge (backend/mw/reaction_knowledge_constants.py, reaction_knowledge.py,
// reaction_knowledge_reads.py, tools/reaction_knowledge.py, reaction_knowledge_reports.py; `.dryforge/spec.md` 3, 5-7).
// Every value inside M-CSA / UniProt / Rhea rows is a reference value copied verbatim from the pinned snapshot set
// (never computed); the only computed values are the counts. A section that was not checked is null, never 0 or [].
export type ReactionSnapshotReason = "not_installed" | "snapshot_invalid";
export type ReactionSource = "mcsa" | "uniprot_function" | "rhea";
export type ReactionSkipReason = "obsolete" | "merged" | "demerged" | "not_found" | "fetch_failed";
export type ReactionSiteType = "Active site" | "Binding site" | "Site";
export type ReactionMcsaCoverage = "covered" | "chain_not_listed" | "pdb_not_in_snapshot";
export type ReactionRowStatus = "matched" | "unmatched" | "conflict";
export type ReactionUnmatchedReason = "non_standard_code" | "no_author_number" | "residue_not_in_structure" |
  "ambiguous_residue_number" | "insertion_code_present";
export type ReactionConflictReason = "residue_name_differs" | "mcsa_rows_disagree";
export type ReactionUniprotStatus = "checked" | "not_checked" | "not_available";
export type ReactionUniprotReason = "accession_not_given" | "accession_not_in_snapshot" | "accession_skipped_at_import";
export type ReactionLinkStatus = "mapped" | "not_in_map";
export type ReactionLinkReason = "numbering_map_not_given" | "chain_not_in_map" | "map_accession_differs";
export type ReactionAccessionSource = "user" | "numbering_map";
export type ReactionChainFlag = "accession_differs_from_mcsa";

/** `requested_accessions` of the set manifest, as stored (spec 3.2). */
export interface ReactionRequestedAccessions { from_mcsa: number; from_m15_kinase_set: { set_hash: string | null;
  count: number }; m15_kinase_list: "present" | "absent" | "disabled"; user_named: string[];
  dropped_previous_user_named: string[]; union_count: number }
export interface ReactionSkippedAccession { accession: string; reason: ReactionSkipReason; target_accessions: string[] }
/** Per source: `rows` = the source's processed file rows summed (manifest values). */
export interface ReactionSourceSummary { source: ReactionSource; date: string; license: string; origin: string;
  rows: number }
/** `GET /reaction_reference/status` (run independent). Not installed / invalid: `installed: false`, the reason, nulls. */
export interface ReactionReferenceStatus { schema: "reaction_reference_status@1"; installed: boolean;
  reason: ReactionSnapshotReason | null; set_hash: string | null; imported_at: string | null;
  sources: ReactionSourceSummary[] | null; requested_accessions: ReactionRequestedAccessions | null;
  skipped_accessions: ReactionSkippedAccession[] | null }
/** `GET /reaction_reference/pdb/{pdb_id}`: M-CSA entries naming this PDB ID (a suggestion source; the person picks). */
export interface ReactionPdbEntries { pdb_id: string; entries: { mcsa_id: number; enzyme_name: string;
  reference_uniprot_id: string; chains: string[] }[] }
/** `link_reaction_knowledge` arguments (spec 5.1; unknown keys refused), in the server's normalized key order. */
export interface ReactionKnowledgeArgs { structure: string; pdb_id: string | null;
  chains: { chain_auth: string; uniprot_accession: string | null }[]; numbering_map: string | null }
/** `/capabilities` `methods.reaction_knowledge` (same five keys as `residue_numbering`). */
export interface ReactionKnowledgeCapability { available: boolean; reason_code: ReactionSnapshotReason | null;
  reason: string | null; set_hash: string | null; sources: ReactionSourceSummary[] }

export interface ReactionMcsaRole { group_function: string; function_type: string; function: string; emo: string }
/** One M-CSA row of a covered chain (spec 5.3). `listed` and `reference` are M-CSA values as written. */
export interface ReactionMcsaRow { mcsa_id: number; residue_index: number; is_reference: boolean;
  listed: { pdb_id: string; chain_name: string; resid: number | null; auth_resid: number | null; code: string;
    assemblies: number[] };
  status: ReactionRowStatus; reason: ReactionUnmatchedReason | ReactionConflictReason | null;
  residue: ExactResidueRef | null; structure_resname: string | null;
  reference: { roles_summary: string; function_location_abv: string; ptm: string; roles: ReactionMcsaRole[] | null } }
export interface ReactionMcsaEntrySummary { mcsa_id: number; enzyme_name: string; reference_uniprot_id: string;
  all_ecs: string[] }
/** `not_checked` (no PDB ID) and an uncovered chain have null entries/rows/counts; `covered` has lists and counts. */
export interface ReactionMcsaSection { status: "checked" | "not_checked"; reason: "pdb_id_not_given" | null;
  coverage: ReactionMcsaCoverage | null; entries: ReactionMcsaEntrySummary[] | null; rows: ReactionMcsaRow[] | null;
  counts: Record<ReactionRowStatus, number> | null }
export interface ReactionUniprotLink { position: number; status: ReactionLinkStatus; residue: ExactResidueRef | null;
  uniprot_residue: string | null; residue_match: boolean | null }
/** A UniProt site (positions are UniProt sequence positions); `links` null when the chain is not linked. */
export interface ReactionUniprotFeature { type: ReactionSiteType; start: number; end: number; description: string;
  ligand_name: string | null; ligand_id: string | null; links: ReactionUniprotLink[] | null }
export interface ReactionUniprotSection { status: ReactionUniprotStatus; reason: ReactionUniprotReason | null;
  skipped: { reason: ReactionSkipReason; target_accessions: string[] } | null;
  entry: { accession: string; entry_name: string; protein_name: string | null; organism: string;
    sequence_length: number } | null;
  linked_via: "numbering_map" | null; link_reason: ReactionLinkReason | null; features: ReactionUniprotFeature[] | null }
export interface ReactionCompound { type: string; chebi_id: string; name: string }
/** Each source list is null when that source did not contribute ([] when it contributed nothing). */
export interface ReactionReactionsSection { status: "checked" | "not_checked"; reason: "no_source" | null;
  ecs: { mcsa: string[] | null; uniprot: string[] | null } | null;
  mcsa_compounds: { mcsa_id: number; ec: string | null; compounds: ReactionCompound[] }[] | null;
  uniprot_activities: { reaction_name: string; ec_number: string | null;
    rhea: { rhea_id: string; in_snapshot: boolean }[] }[] | null }
export interface ReactionKnowledgeChain { chain_auth: string; polymer_residue_count: number; accession: string | null;
  accession_source: ReactionAccessionSource | null; mcsa: ReactionMcsaSection; uniprot: ReactionUniprotSection;
  reactions: ReactionReactionsSection; flags: ReactionChainFlag[] }
/** Processed snapshot rows the result used, stored verbatim (spec 3.3). */
export interface ReactionMcsaReferenceRow { mcsa_id: number; enzyme_name: string; reference_uniprot_id: string;
  all_ecs: string[]; reaction: { ec: string | null; compounds: ReactionCompound[] };
  residues: { roles_summary: string; function_location_abv: string; ptm: string; roles: ReactionMcsaRole[];
    residue_chains: { pdb_id: string; chain_name: string; assembly_chain_name: string; assembly: number | null;
      code: string; resid: number | null; auth_resid: number | null; is_reference: boolean }[];
    residue_sequences: { uniprot_id: string; code: string; is_reference: boolean }[] }[] }
export interface ReactionUniprotReferenceRow { accession: string; entry_name: string; protein_name: string | null;
  organism: string; sequence_length: number; ec_numbers: string[];
  catalytic_activities: { reaction_name: string; ec_number: string | null; rhea_ids: string[]; chebi_ids: string[] }[];
  features: Omit<ReactionUniprotFeature, "links">[] }
export interface ReactionRheaReferenceRow { rhea_id: string; equation: string; ec_numbers: string[];
  participants: { chebi_id: string; name: string }[] }
export interface ReactionSnapshotSetRecord { set_hash: string; imported_at: string; importer_version: string;
  sources: { source: ReactionSource; date: string; license: string; origin: string;
    files: { name: string; sha256: string; bytes: number; rows: number }[] }[];
  requested_accessions: ReactionRequestedAccessions; skipped_accessions: ReactionSkippedAccession[] }
/** Counts ProtView made; a part that was not checked is null (never 0). */
export interface ReactionKnowledgeCounts { chains: number; covered_chains: number;
  mcsa_rows: Record<ReactionRowStatus, number> | null; mcsa_entries: number | null;
  uniprot_features: Record<ReactionSiteType, number> | null; linked_positions: Record<ReactionLinkStatus, number> | null;
  rhea: { in_snapshot: number; not_in_snapshot: number } | null }
/** `reaction_knowledge@1` (spec 5.6), immutable. */
export interface ReactionKnowledgeResult { schema: "reaction_knowledge@1"; method_version: "mw.reaction_knowledge/v1";
  structure: { handle: string; structure_kind: "structure" | "prepared_structure"; model_number: number };
  pdb_id: string | null; numbering_map: { handle: string; pdb_id: string | null } | null;
  snapshot_set: ReactionSnapshotSetRecord; chains: ReactionKnowledgeChain[];
  reference_rows: { mcsa: ReactionMcsaReferenceRow[]; uniprot: ReactionUniprotReferenceRow[];
    rhea: ReactionRheaReferenceRow[] };
  counts: ReactionKnowledgeCounts; null_result: boolean; limitations: string[] }
/** A chain of the detail read: rows and features cut to their page, with the full lengths (null when null). */
export type ReactionKnowledgeDetailChain = Omit<ReactionKnowledgeChain, "mcsa" | "uniprot"> & {
  mcsa: ReactionMcsaSection & { row_total: number | null };
  uniprot: ReactionUniprotSection & { feature_total: number | null } };
export interface ReactionKnowledgePage { chain_total: number; chain_offset: number; chain_limit: number;
  row_offset: number; row_limit: number; feature_offset: number; feature_limit: number }
/** `GET /runs/{id}/reaction_knowledge/{handle}?chain_offset=…`: the re-validated stored result, paged. */
export interface ReactionKnowledgeDetail extends Omit<ReactionKnowledgeResult, "chains"> {
  chains: ReactionKnowledgeDetailChain[]; page: ReactionKnowledgePage;
  /** The active set now (null when none is usable) and whether it is the result's set. */
  active_set: { set_hash: string | null; same: boolean } }
/** `GET /runs/{id}/reaction_knowledge` item, newest first; `active` = same set as the active one now. */
export interface ReactionKnowledgeListItem { handle: string; structure_handle: string;
  structure_kind: "structure" | "prepared_structure"; pdb_id: string | null; chain_count: number;
  covered_chain_count: number; mcsa_rows: Record<ReactionRowStatus, number> | null;
  uniprot_feature_count: number | null; null_result: boolean; set_hash: string; active: boolean }
export interface ReactionKnowledgeList { items: ReactionKnowledgeListItem[]; total: number }
export interface ReactionKnowledgeReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "reaction_knowledge"; result_handle: string;
  snapshot: { event_seq: number } } & Record<string, unknown>; markdown: string }

// ---- M27 kinase precedents (backend/mw/precedent_constants.py, kinase_precedents.py, kinase_precedents_reads.py,
// tools/kinase_precedents.py, kinase_precedents_reports.py; `.dryforge/spec.md` 3, 5-7).
// Every precedent field is a kbase_kinase value copied as it is (machine-extracted, unreviewed; never computed); the
// only computed values are counts. A file that was not included has a null count (never 0) and the number of records
// it was not including is the separate `excluded_flagged`.
export type PrecedentJsonValue = string | number | boolean | null | PrecedentJsonValue[] |
  { [key: string]: PrecedentJsonValue };
export type PrecedentSnapshotReason = "not_installed" | "snapshot_invalid";
export type PrecedentFile = "moves" | "moves_flagged";
export type PrecedentChainStatus = "linked" | "not_linked";
export type PrecedentChainReason = "no_mapped_residues" | "multiple_accessions";
export type PrecedentTargetStatus = "precedents_found" | "none_in_included_files" | "not_in_kbase_references";
export type PrecedentTagAxis = "site" | "goal" | "tactic";
/** The detail read's five sort keys (spec 6): never an effect, direction or magnitude value. */
export type PrecedentSortKey = "move_id" | "pmid" | "year" | "variant" | "file";
export type PrecedentSortOrder = "asc" | "desc";
export type PrecedentCheckName = "qualifier_consistency" | "tag_vocab" | "schema" | "target_in_reference" |
  "quote_in_source" | "cross_parser_numbers" | "chembl_crosscheck" | "pmid_exists" | "structure_ref_exists" |
  "duplicate";

/** The set manifest `kbase` block (spec 3.2), as stored. */
export interface PrecedentKbaseBlock { commit: string; dist_commit: string | null; dist_commit_date: string | null;
  dirty: boolean; kb_version: string; schema_version: string; effect_rules_version: string; vocab_version: string;
  source_snapshots: string[]; origin: string }
export interface PrecedentFileCounts { moves: number; moves_flagged: number }
/** Set-wide summary (spec 5.6), independent of any chain. */
export interface PrecedentSetSummary { records: PrecedentFileCounts; references: number;
  unresolved_target_records: PrecedentFileCounts;
  unresolved_names: ({ name_as_written: string | null } & PrecedentFileCounts)[]; unresolved_names_total: number;
  resolution_basis_counts: ({ basis: string } & PrecedentFileCounts)[] }
/** `GET /precedent_reference/status` (run independent). Not installed / invalid: `installed: false`, the reason, nulls.
 * `files` are the three dist files; the bibliography row count is `bibliography.rows`. */
export interface PrecedentReferenceStatus { schema: "precedent_reference_status@1"; installed: boolean;
  reason: PrecedentSnapshotReason | null; set_hash: string | null; imported_at: string | null;
  importer_version: string | null; kbase: PrecedentKbaseBlock | null;
  files: { name: string; rows: number; bytes: number }[] | null;
  bibliography: { snapshot_id: string; date: string; license: string; rows: number } | null;
  set_summary: PrecedentSetSummary | null }
export interface PrecedentCapabilitySource { source: "kbase_dist" | "kbase_pubmed"; date: string | null; license: string;
  origin: string; rows: number }
/** `/capabilities` `methods.kinase_precedents` (same five keys as `reaction_knowledge`). */
export interface KinasePrecedentsCapability { available: boolean; reason_code: PrecedentSnapshotReason | null;
  reason: string | null; set_hash: string | null; sources: PrecedentCapabilitySource[] }
/** `link_kinase_precedents` arguments (spec 5.1; unknown keys refused), in the server's normalized key order. */
export interface KinasePrecedentsArgs { numbering_map: string; chains: string[] | null; include_flagged: boolean }
/** 429 `resource_exceeded` detail of a result above 1 MiB (nothing stored, nothing truncated). */
export interface PrecedentTooLargeDetail { reason_code: "result_too_large"; limit: number; actual: number;
  size_without_flagged: number | null; target_sizes: { accession: string; chains: string[]; bytes: number }[] }

export interface PrecedentSetFile { name: string; path: string; sha256: string; bytes: number; rows: number }
/** The result's `precedent_set` (spec 5.6): reopens from events alone, without the reference folder. */
export interface PrecedentSetRecord { set_hash: string; imported_at: string; importer_version: string;
  kbase: PrecedentKbaseBlock; files: PrecedentSetFile[];
  bibliography_snapshot: { snapshot_id: string; date: string; license: string; origin: string; file: PrecedentSetFile } }
/** One chain of the numbering map (spec 5.3), in the map's order. */
export interface PrecedentChain { chain_auth: string; total_residue_count: number; mapped_residue_count: number;
  cross_check: boolean; cross_check_absent_reason: string | null; status: PrecedentChainStatus;
  reason: PrecedentChainReason | null; accession: string | null; accessions: string[] }
/** A kbase reference of the target (kbase values as written). */
export interface PrecedentReference { ref_id: string; gene: PrecedentJsonValue; klifs_name: PrecedentJsonValue;
  group: PrecedentJsonValue; family: PrecedentJsonValue; coverage: PrecedentJsonValue; content_hash: string | null }
/** Counts ProtView made from the included records; `moves_flagged` is null when that file was not included. */
export interface PrecedentTargetCounts { moves: number; moves_flagged: number | null;
  variants: { variant: string; count: number }[];
  tags: Record<PrecedentTagAxis, { term: string; count: number }[]>;
  resolution_basis: { basis: string; count: number }[] }
export interface PrecedentMeasure { qualifier: PrecedentJsonValue; value: PrecedentJsonValue; unit: PrecedentJsonValue }
/** One measured change as kbase extracted it; direction / magnitude are kbase rule v1 values, never ProtView's. */
export interface PrecedentEffect { metric: PrecedentJsonValue; assay: PrecedentJsonValue; assay_context: PrecedentJsonValue;
  target_ref: PrecedentJsonValue; target_role: string; before: PrecedentMeasure | PrecedentJsonValue;
  after: PrecedentMeasure | PrecedentJsonValue; direction: string; direction_basis: string; magnitude_bucket: string;
  comparable: PrecedentJsonValue; comparability_reason: PrecedentJsonValue; fold_change: number | null;
  chembl_crosscheck: PrecedentJsonValue; evidence: PrecedentJsonValue }
export interface PrecedentLocation { kind: string; page: number; [key: string]: PrecedentJsonValue }
export interface PrecedentCheck { status: string; [key: string]: PrecedentJsonValue }
/** The stored record copy (`kbase_record_minus_2_paths@1`): the kbase record minus `source.parser` and
 * `checks.cross_parser_numbers.measurements`; `content_hash` is the original record's hash. */
export interface PrecedentRecord { review_status: string; schema_version: number; move_id: string;
  source: { pmid: string; locations: PrecedentLocation[] };
  target: { gene: PrecedentJsonValue; uniprot: string | null; name_as_written: string | null; resolution_basis: string;
    candidates: PrecedentJsonValue; variant: string };
  structure_ref: PrecedentJsonValue; structure_link_reason: PrecedentJsonValue; structure_ref_from: PrecedentJsonValue;
  structure_links: { basis: string; [key: string]: PrecedentJsonValue }[];
  interactions: { [key: string]: PrecedentJsonValue }[];
  observation: { text: PrecedentJsonValue; quote: string; quote_truncated: PrecedentJsonValue;
    evidence: PrecedentJsonValue };
  change: PrecedentJsonValue; effects: PrecedentEffect[];
  tradeoffs: { text: PrecedentJsonValue; quote: string | null; quote_truncated: PrecedentJsonValue;
    evidence: PrecedentJsonValue }[];
  mutations: PrecedentJsonValue; tags: Record<PrecedentTagAxis, string[]>; proposed_tags: PrecedentJsonValue;
  figures: PrecedentJsonValue; checks: Record<PrecedentCheckName, PrecedentCheck>;
  extraction: { model: PrecedentJsonValue; provider: PrecedentJsonValue; prompt_version: PrecedentJsonValue;
    run_at: PrecedentJsonValue; [key: string]: PrecedentJsonValue };
  content_hash: string }
/** ProtView's own checks at link time (spec 5.5): not a comparison with the paper. */
export interface PrecedentIntegrity { hash_verified: boolean; observation_quote_words: number;
  tradeoff_quote_words: (number | null)[]; quotes_within_limit: boolean; locations_have_page: boolean }
export interface PrecedentRecordItem { file: PrecedentFile; integrity: PrecedentIntegrity; record: PrecedentRecord }
/** Bibliography snapshot row values as they are (null = no bibliography for that PMID). */
export interface PrecedentBibliographyEntry { title: string | null; journal: string | null; year: string | null;
  doi: string | null; pmc: string | null }
export interface PrecedentFacetValue { value: string; count: number }
/** Value counts of the selected target's records before any filter (server order). */
export interface PrecedentFacets { file: PrecedentFacetValue[]; site: PrecedentFacetValue[]; goal: PrecedentFacetValue[];
  tactic: PrecedentFacetValue[]; variant: PrecedentFacetValue[] }
export interface KinasePrecedentsTargetOverview { accession: string; chains: string[]; status: PrecedentTargetStatus;
  references: PrecedentReference[]; excluded_flagged: number | null; counts: PrecedentTargetCounts }
/** Included counts are null when `moves_flagged` was not included; `excluded_moves_flagged` is null when it was. */
export interface KinasePrecedentsCounts { chains: number; linked_chains: number; not_linked_chains: number;
  targets: number; records: { moves: number; moves_flagged: number | null }; excluded_moves_flagged: number | null }
/** No target: `target`, `total`, `filtered_total` null (offset / limit still carry the request's values). */
export interface KinasePrecedentsPage { target: string | null; total: number | null; filtered_total: number | null;
  offset: number; limit: number }
/** `GET /runs/{id}/kinase_precedents/{handle}?target=&file=&site=…`: the re-validated stored result plus one target's
 * filtered, sorted page (spec 6). */
export interface KinasePrecedentsDetail { schema: "kinase_precedents_detail@1"; handle: string;
  method_version: "mw.kinase_precedents/v1"; numbering_map: { handle: string };
  structure: { handle: string; structure_kind: "structure" | "prepared_structure"; model_number: number };
  pdb_id: string | null; include_flagged: boolean; record_format: "kbase_record_minus_2_paths@1";
  precedent_set: PrecedentSetRecord; chains: PrecedentChain[]; targets_overview: KinasePrecedentsTargetOverview[];
  set_summary: PrecedentSetSummary; counts: KinasePrecedentsCounts; null_result: boolean; limitations: string[];
  page: KinasePrecedentsPage; facets: PrecedentFacets | null; records: PrecedentRecordItem[];
  /** This page's PMIDs only. */
  bibliography: Record<string, PrecedentBibliographyEntry | null>;
  /** The active set now (null when none is usable) and whether it is the result's set. */
  active_set: { set_hash: string | null; same: boolean } }
/** `GET /runs/{id}/kinase_precedents` item, newest first; `active` = same set as the active one now. */
export interface KinasePrecedentsListItem { handle: string; numbering_map_handle: string; pdb_id: string | null;
  include_flagged: boolean; chain_count: number; linked_chain_count: number; target_count: number;
  records: { moves: number; moves_flagged: number | null }; null_result: boolean; set_hash: string; active: boolean }
export interface KinasePrecedentsList { items: KinasePrecedentsListItem[]; total: number }
/** Report `analysis_type: "kinase_precedents"`; the snapshot records the active set at creation. */
export interface KinasePrecedentsReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "kinase_precedents"; result_handle: string;
  precedent_set: PrecedentSetRecord; snapshot: { event_seq: number; active_set_hash: string | null } } &
  Record<string, unknown>; markdown: string }

// ---- M29 structure repair (backend/mw/structure_repair_constants.py, structure_repair_reads.py,
// tools/structure_repair.py, structure_origin_reads.py, mutation_handoff.py; `.dryforge/spec.md` 3–8) ----
/** The 7 identity fields as stored in a repair record (null kept; the insertion code as stored). */
export interface RepairResidue { model_number: number; chain_auth: string; chain_label: string | null; seq_auth: number;
  seq_label: number | null; icode: string | null; resname: string }
export type RepairClass = "chain_parts_merged" | "side_chain_atoms_added" | "terminal_oxt_added" | "internal_gap_filled" |
  "nonstandard_replaced";
export type RepairCollisionClass = "protein" | "ligand" | "metal" | "water" | "other";
export type RepairAddedAtomOrigin = "side_chain" | "oxt" | "gap_residue";
/** A fixed sentence the server chose for this read (shown verbatim; the browser never words it). */
export interface RepairStatement { id: string; text: string }
/** Read-only field of a result on a repaired structure (never stored; absent for any other structure). */
export interface StructureOrigin { repair_record: string; repaired_structure: string; source_structure: string;
  counts: StructureRepairCounts; statements: RepairStatement[] }
/** JW1 on the JEV preview and approval answers of candidates on a repaired structure. */
export interface RepairWarning { id: "JW1"; text: string }
/** M20 reads of a set on a repaired structure: reference results made on the original structure and SO2 / SO3. */
export interface RepairHandoff { references: ("pocket_set" | "numbering_map" | "annotation" | "catalytic_annotation")[];
  statements: RepairStatement[] }
export type RepairReferenceField = "numbering" | "klifs_sites" | "catalytic";
/** `methods.structure_repair` of `/capabilities`: reasons only when unavailable (no versions). */
export interface StructureRepairCapability { schema: "structure_repair_capability@1"; protocol_id: "pdbfixer_repair_v1";
  tool_id: "repair_structure"; execution_lane: string; result_schema: "structure_repair@1"; method_version: string;
  timeout_s: { default: number; max: number };
  limits: { max_gap_residues: number; protein_heavy_atoms: number; staged_input_bytes: number; record_bytes: number };
  available: boolean; reason_code: string | null; reason: string | null;
  versions: { openmm: string; openmm_engine_build: string; pdbfixer: string } | null }
export interface StructureRepairBlocker { reason_code: string; residue?: RepairResidue; chain_auth?: string;
  detail: Record<string, unknown> }
export interface StructureRepairGap { chain_auth: string; after_residue: RepairResidue; before_residue: RepairResidue;
  length: number; residues: RepairResidue[] }
/** `GET /runs/{id}/structure_repair/preflight?structure=`: a free read (no event, tool or job); refusals are 200. */
export interface StructureRepairPreflight { schema: "structure_repair_preflight@1"; starts_job: false;
  capability: StructureRepairCapability; structure: string; repairable: boolean | null;
  blockers: StructureRepairBlocker[];
  defects: { chain_parts: { chain_auth: string; parts: number }[];
    side_chain_residues: { residue: RepairResidue; missing_atoms: string[] }[]; terminal_oxt: { residue: RepairResidue }[];
    gaps: StructureRepairGap[]; nonstandard: { residue: RepairResidue; to_resname: string }[] } | null;
  expected_added_residues: number | null; expected_added_heavy_atoms: number | null;
  budget: Record<string, { limit: number; used: number }>; remaining: Record<string, number>;
  shortfall: { expensive_calls: number };
  admission: { admitted: boolean; error: string | null; reason_code: string | null; message: string | null;
    detail: Record<string, unknown> | null } | null;
  /** The RP sentences whose condition holds (plain strings). */
  statements: string[] }
export interface StructureRepairCounts { added_residues: number; added_atoms: number; side_chain_residues: number;
  terminal_oxt: number; gaps: number; replaced: number; chain_parts_merged: number; protein_heavy_atoms: number }
export interface StructureRepairCollision { min_distance_A: number | null; count_lt_2_0: number; count_lt_1_5: number;
  min_pair: { new_residue: RepairResidue; new_atom: string; partner_residue: RepairResidue; partner_atom: string } | null }
export interface StructureRepairAddedAtom { residue: RepairResidue; atom_name: string; element: string;
  coordinates_A: [number, number, number]; origin: RepairAddedAtomOrigin }
/** `structure_repair@1` without `added_atoms` (the detail read; atoms come by page). */
export interface StructureRepairRecord { schema: "structure_repair@1"; method_version: string;
  source: { prepared_structure: string; model_number: number };
  result: { coordinates: string; coordinates_sha256: string };
  parameters: { repair_policy: string; seed: number; max_gap_residues: number; waters: string; hydrogens: string;
    new_atom_coordinate_decimals: number };
  method: { engine: string; pdbfixer_version: string; openmm_distribution_version: string;
    forcefield_files_sha256: Record<string, string> };
  classes_applied: RepairClass[];
  chain_parts: { chain_auth: string; parts: number; merged: boolean }[];
  chain_ends: { chain_auth: string; observed_first: RepairResidue; observed_last: RepairResidue;
    first_is_sequence_start: boolean | null; last_is_sequence_end: boolean | null }[];
  side_chain_repairs: { residue: RepairResidue; added_atoms: string[] }[];
  terminal_oxt: { residue: RepairResidue }[];
  gaps: StructureRepairGap[];
  replaced: { from: RepairResidue; to: RepairResidue; atom_map: { from: string; to: string }[];
    record_type: { from: string; to: string } }[];
  counts: StructureRepairCounts;
  unchanged: { atom_count: number; max_delta_A: number; input_calc_flag_cleared: number };
  new_atom_rounding: { decimals: number; max_abs_delta_A: number };
  zero_occupancy_input_atoms: { count: number; residues: RepairResidue[] };
  collisions: Record<RepairCollisionClass, StructureRepairCollision>;
  limitations: string[] }
/** `GET /runs/{id}/structure_repairs` row, newest first; a row that does not validate: `valid: false`, nulls. */
export interface StructureRepairListRow { handle: string; created_seq: number; valid: boolean;
  prepared_structure: string | null; source_structure: string | null; classes_applied: RepairClass[] | null;
  counts: StructureRepairCounts | null }
export interface StructureRepairList { schema: "structure_repair_list@1"; total: number; offset: number; limit: number;
  rows: StructureRepairListRow[] }
export interface StructureRepairDetail { schema: "structure_repair_detail@1"; handle: string; prepared_structure: string;
  source_structure: string; coordinates: string; manifest: string; published_seq: number; added_atom_count: number;
  result: StructureRepairRecord; meta: Record<string, unknown> }
export interface StructureRepairAtomPage { schema: "structure_repair_atom_page@1"; handle: string; total: number;
  page: number; page_size: number; rows: (StructureRepairAddedAtom & { index: number })[] }
export interface StructureRepairJob { job_id: string; run_id: string; protocol_id: "pdbfixer_repair_v1"; tool_id: string;
  status: string; blocked_reason: string | null;
  failure: { error: string; message: string; reason_code?: string; detail?: Record<string, unknown> } | null;
  input_handles: string[]; output_handles: string[]; attempt_ordinal: number; cancel_requested: boolean;
  timeout_s: number; artifacts?: { structure_repair?: string; prepared_structure?: string } }
/** Dry-run submission: a plan only, no job and no result object. */
export interface StructureRepairPlanOnly { plan_only: true; protocol_id: "pdbfixer_repair_v1"; reason_code: "dry_run";
  available: false; output_handles: []; normalized_parameters: Record<string, unknown> }
export type StructureRepairSubmission = StructureRepairJob | StructureRepairPlanOnly;
export interface StructureRepairReportArtifact { handle: string; markdown_handle: string; manifest: {
  schema: "method_report_manifest@1"; analysis_type: "structure_repair"; result_handle: string } &
  Record<string, unknown>; markdown: string }
