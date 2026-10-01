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
