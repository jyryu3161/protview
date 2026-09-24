/** Loopback-only M1 API client. See docs/M1_API.md. */
import type { BudgetSnapshot, EgressMode, Handle, InteractionRow, ResidueRef, RunEvent, ToolError } from "./contracts";
import type { ViewerSource } from "@/components/MolstarViewer";

export interface RunSummary { run_id: string; goal: string; context: string[]; dry_run: boolean; egress: EgressMode; last_seq: number }
export function displayedEgressMode(run: RunSummary | null): EgressMode {
  return run?.dry_run ? "dry_run" : run?.egress ?? "local_only";
}
export interface UploadResult { upload_id: string; sha256: string; size: number; format: "pdb" | "cif" | "mmcif"; n_models: number; model_numbers: number[] }
export interface ResidueItem extends ResidueRef { atom_count: number; category: "polymer" | "nonpolymer" | "water" }
export interface ResidueList { model_number: number; residues: ResidueItem[]; ligands: ResidueRef[] }
export interface ObjectMeta { handle: string; kind: string; schema: string; fmt: string; size: number; produced_by: string | null; summary: Record<string, unknown>; null_result: boolean }
export interface Page<T> { meta: ObjectMeta; rows: T[]; total: number; offset: number; limit: number }
export interface Capabilities { mode: "local_only"; supported: Record<string, string>; unavailable: Record<string, string> }
export interface SavedReportRef { handle: string; interaction_handle: string; markdown_handle: string; created_seq: number; snapshot_event_seq: number }
export interface ReportArtifact { handle: string; markdown_handle: string; manifest: {
  interaction_handle: string; prepared_handle: string; source_handle: string;
  counts: { atom_pairs: number; contacting_residues: number; by_type: Record<string, number> };
  minimum_distance_A: number | null; scientific_null: boolean;
  snapshot: { event_seq: number }; capabilities: { protocols: Record<string, { available: boolean; reason_code: string; explanation: string }> };
}; markdown: string }
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
  capabilities: () => request<Capabilities>("/capabilities"),
  runs: () => request<RunSummary[]>("/runs"),
  run: (id: string) => request<RunSummary>(runPath(id)),
  createRun: () => request<RunSummary>("/runs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ goal: "로컬 구조 검사", context: [], dry_run: false, egress: "local_only" }) }),
  upload: (id: string, file: File) => request<UploadResult>(runPath(id, `/uploads?filename=${encodeURIComponent(file.name)}`), { method: "POST", headers: { "content-type": "application/octet-stream" }, body: file }),
  command: (id: string, tool: "load_structure" | "prepare_structure" | "compute_interactions", args: Record<string, unknown>) =>
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
  reports: (id: string) => request<SavedReportRef[]>(runPath(id, "/reports")),
  report: (id: string, handle: string) => request<ReportArtifact>(runPath(id, `/reports/selected?${handleParam(handle)}`)),
  createReport: (id: string, interactionHandle: string) => request<ReportArtifact>(runPath(id, "/reports"), {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ interaction_handle: interactionHandle }),
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
