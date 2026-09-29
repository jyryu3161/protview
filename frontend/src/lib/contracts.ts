// Mirrors backend/mw (docs/contracts.md). Change BOTH sides together.

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
