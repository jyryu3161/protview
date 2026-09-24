// Thin client for backend/mw/api/app.py (proxied at /api by next.config.mjs).
import type { BudgetSnapshot, Handle, RunEvent, ToolError, ToolSpec } from "./contracts";

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, { ...init, headers: { "content-type": "application/json", ...(init?.headers ?? {}) } });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json() as Promise<T>;
}

export type CommandResult =
  | { ok: true; handle: Handle }
  | ({ ok: false } & ToolError)
  | { ok: false; approval: { gate: string; tool: string; reason: string } }
  | { ok: false; loop_stop: { reason: string } };

export const api = {
  tools: (levels = "L1,L2,L3,L4,L5") => j<ToolSpec[]>(`/tools?levels=${levels}`),
  createRun: (goal: string, context: string[], dry_run = true, egress = "local_only") =>
    j<{ run_id: string }>("/runs", { method: "POST", body: JSON.stringify({ goal, context, dry_run, egress }) }),
  command: (runId: string, tool: string, args: Record<string, unknown>, decided_by = "human") =>
    j<CommandResult>(`/runs/${runId}/commands`, { method: "POST", body: JSON.stringify({ tool, args, decided_by }) }),
  approve: (runId: string, gate: string) => j<{ ok: true }>(`/runs/${runId}/approvals/${gate}`, { method: "POST" }),
  events: (runId: string, after = 0) => j<RunEvent[]>(`/runs/${runId}/events?after=${after}`),
  budget: (runId: string) => j<BudgetSnapshot>(`/runs/${runId}/budget`),
  materialize: (runId: string, handle: string, columns?: string[], offset = 0, limit = 50) =>
    j<{ meta: Record<string, unknown>; rows: Record<string, unknown>[] }>(
      `/runs/${runId}/objects?handle=${encodeURIComponent(handle)}${columns ? `&columns=${columns.join(",")}` : ""}&offset=${offset}&limit=${limit}`),
};

/** Poll events (M2 may replace with a WebSocket; keep this signature). */
export function pollEvents(runId: string, onEvents: (e: RunEvent[]) => void, everyMs = 1000) {
  let after = 0, stop = false;
  const tick = async () => {
    if (stop) return;
    try { const ev = await api.events(runId, after); if (ev.length) { after = ev[ev.length - 1].seq; onEvents(ev); } } catch { /* backend down: keep polling */ }
    setTimeout(tick, everyMs);
  };
  tick();
  return () => { stop = true; };
}
