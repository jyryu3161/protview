import type { ResidueRef } from "./contracts";

export type ViewerRepresentationValue = "cartoon" | "ball_and_stick" | "surface";
export interface ViewerCatalogEntry {
  alias: string; category: "polymer" | "nonpolymer" | "water";
  model_number?: number; chain_auth?: string; seq_auth?: number; icode?: string;
  chain_label?: string; seq_label?: number;
}
export interface ViewerSession {
  viewer_session_id: string; client_instance_id: string; scene_generation: number;
  structure_handle: string; catalog_hash: string; catalog: ViewerCatalogEntry[];
  targets: { alias: string; residue: ResidueRef }[];
  representation: ViewerRepresentationValue; selected_alias: string | null;
  action_revision: number; current: boolean; scope_complete: boolean;
  projection: { schema: "viewer_intent@1"; representation: ViewerRepresentationValue;
    selected_target: string | null; scope_complete: boolean; catalog: ViewerCatalogEntry[] };
}
export interface ViewerOnlineStatus {
  enabled: boolean; mode: "local_only" | "online"; policy: string;
  request_cap: number; used: number; remaining: number; scientific_job_approved: boolean;
}
export interface ViewerCommand {
  schema: "viewer_plan@1"; command_id: string; intent_id: string;
  viewer_session_id: string; client_instance_id: string; scene_generation: number;
  structure_handle: string; catalog_hash: string; action_revision: number;
  axis: "representation" | "selection" | "camera";
  value: "cartoon" | "ball_and_stick" | "surface" | "select" | "clear" |
    "focus_selected" | "zoom_in" | "zoom_out" | "reset";
  target?: ResidueRef;
}
export interface ViewerIntent {
  intent_id: string; status: "interpreting" | "planned" | "applying" | "applied" |
    "partial" | "no_change" | "clarification" | "unsupported" | "rejected" |
    "cancelled" | "failed" | "detached";
  source: "jev" | "local_command"; viewer_session_id: string;
  scene_generation: number; structure_handle: string; catalog_hash: string;
  prompt_sha256: string; projection_sha256: string | null;
  question_version: string | null; requested_model: string | null;
  served_model: string | null; audit_id: string | null; reason_code: string | null;
  commands: ViewerCommand[];
  acks: { command_id: string; status: "applied" | "no_change" | "failed"; reason_code: string | null }[];
}
