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

export interface Handle {
  handle: string;           // "obj://<run_id>/<kind>/<sha16>" — opaque; never parse beyond display
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
  chain_auth: string; seq_auth: number; icode: string;
  chain_label: string; seq_label: number | null; resname: string;
}
export const residueUid = (r: ResidueRef) => `${r.chain_auth}/${r.seq_auth}${r.icode ?? ""}`;

export interface InteractionRow {
  residue: ResidueRef; type: InteractionType; distance_A: number;
  protein_atom?: string; ligand_atom?: string; engine: string;
}

export interface BudgetAxis { used: number; limit: number }
export type BudgetSnapshot = Record<"wall_clock_s" | "expensive_calls" | "external_tokens" | "usd", BudgetAxis>;

export type RunEvent =
  | { seq: number; ts: number; type: "run_started"; run_id: string; dry_run: boolean; seed: number }
  | { seq: number; ts: number; type: "goal"; text: string; context: string[]; egress: EgressMode }
  | { seq: number; ts: number; type: "tool_called"; tool: string; key: string; call_id: string;
      args: Record<string, unknown>; decided_by: DecisionSource; attempt: number; version: string }
  | { seq: number; ts: number; type: "tool_succeeded"; tool: string; key: string; call_id: string;
      output: Handle; duration_s?: number; null_result?: boolean; cached?: boolean }
  | ({ seq: number; ts: number; type: "tool_failed"; tool: string; key: string; call_id: string } & ToolError)
  | { seq: number; ts: number; type: "decision"; source: DecisionSource; question: string; answer: unknown }
  | { seq: number; ts: number; type: "approval_requested"; gate: string; tool: string; args: Record<string, unknown> }
  | { seq: number; ts: number; type: "approval_resolved"; gate: string; approved: boolean; by: string }
  | { seq: number; ts: number; type: "checkpoint"; reason: string; axis?: string; budget?: BudgetSnapshot }
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
