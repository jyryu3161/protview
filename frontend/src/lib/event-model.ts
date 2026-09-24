import type { Handle, RunEvent } from "./contracts";

export type SuccessEvent = Extract<RunEvent, { type: "tool_succeeded" }>;
export type CacheEvent = Extract<RunEvent, { type: "cache_hit" }>;
export type ResultEvent = SuccessEvent | CacheEvent;
export type PipelineHandles = { loaded?: Handle; prepared?: Handle; interactions?: Handle; sasa?: Handle };

function canonicalJson(value: unknown): string | null {
  try {
    return JSON.stringify(value, (_key, item: unknown) => {
      if (item === undefined || typeof item === "function" || typeof item === "symbol" ||
          typeof item === "bigint" || (typeof item === "number" && !Number.isFinite(item))) {
        throw new Error("Not normalized JSON");
      }
      return item && typeof item === "object" && !Array.isArray(item)
        ? Object.fromEntries(Object.entries(item).sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0))
        : item;
    }) ?? null;
  } catch {
    return null;
  }
}

/** A cache observation is usable only with its original physical call and output. */
export function resultEvents(events: RunEvent[]): ResultEvent[] {
  const calls = events.filter((event): event is Extract<RunEvent, { type: "tool_called" }> => event.type === "tool_called");
  const successes = events.filter((event): event is SuccessEvent => event.type === "tool_succeeded");
  const observationCounts = new Map<string, number>();
  for (const event of events) {
    if (event.type === "cache_hit") {
      observationCounts.set(event.observation_id, (observationCounts.get(event.observation_id) ?? 0) + 1);
    }
  }
  const otherResultIds = new Set([...calls.map(call => call.call_id), ...successes.map(resultId)]);
  const validCache = (event: CacheEvent): boolean => {
    if (typeof event.observation_id !== "string" || !event.observation_id ||
        typeof event.source_call_id !== "string" || !event.source_call_id ||
        observationCounts.get(event.observation_id) !== 1 || otherResultIds.has(event.observation_id)) return false;
    const sourceCalls = calls.filter(call => call.call_id === event.source_call_id);
    const physicalSuccesses = successes.filter(success => !success.cached && success.call_id === event.source_call_id);
    if (sourceCalls.length !== 1 || physicalSuccesses.length !== 1) return false;
    const [call] = sourceCalls;
    const [success] = physicalSuccesses;
    const args = canonicalJson(event.args);
    const output = canonicalJson(event.output);
    return call.tool === event.tool && success.tool === event.tool &&
      !!call.key && call.key === success.key && success.key === event.key &&
      Number.isInteger(call.seq) && Number.isInteger(success.seq) && Number.isInteger(event.seq) &&
      call.seq < success.seq && success.seq < event.seq &&
      typeof event.output?.handle === "string" && !!event.output.handle &&
      typeof success.output?.handle === "string" && !!success.output.handle &&
      args !== null && args === canonicalJson(call.args) &&
      output !== null && output === canonicalJson(success.output);
  };
  return events.filter((event): event is ResultEvent =>
    event.type === "tool_succeeded" || (event.type === "cache_hit" && validCache(event)));
}

export function resultId(event: ResultEvent): string {
  return event.type === "cache_hit" ? event.observation_id
    : event.cached ? `legacy_cache_${event.seq}` : event.call_id;
}

/** Observation order chooses intent; original call args preserve scientific lineage. */
export function latestHandles(events: RunEvent[]): PipelineHandles {
  const calls = events.filter((e): e is Extract<RunEvent, { type: "tool_called" }> => e.type === "tool_called");
  const results = resultEvents(events);
  const inputOf = (result: ResultEvent) => calls.find(call =>
    call.call_id === (result.type === "cache_hit" ? result.source_call_id : result.call_id) &&
    call.tool === result.tool && call.seq < result.seq)?.args.structure;
  const loaded = [...results].reverse().find(e => e.tool === "load_structure" && e.output.kind === "structure");
  const prepared = loaded && [...results].reverse().find(e => e.tool === "prepare_structure" &&
    e.output.kind === "prepared_structure" && inputOf(e) === loaded.output.handle);
  const interactions = prepared && [...results].reverse().find(e => e.tool === "compute_interactions" &&
    e.output.kind === "interaction_set" && inputOf(e) === prepared.output.handle);
  const sasa = prepared && [...results].reverse().find(e => e.tool === "compute_interface_sasa" &&
    e.output.kind === "interface_sasa" && inputOf(e) === prepared.output.handle);
  return { loaded: loaded?.output, prepared: prepared?.output, interactions: interactions?.output, sasa: sasa?.output };
}
