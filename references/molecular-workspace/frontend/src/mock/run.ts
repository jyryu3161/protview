// Mock data for the static workspace and the gallery. Replace with api.ts calls milestone by milestone.
import type { BudgetSnapshot, InteractionRow, ResidueRef, ToolSpec } from "@/lib/contracts";
import type { DdgRow, Job, MaskState, ModelItem, Step, TrackBin } from "@/components";

export const RUN_ID = "run_20260923_a91";
const H = (kind: string, sha: string) => ({ handle: `obj://${RUN_ID}/${kind}/${sha}`, kind });
export const handles = {
  structure: { ...H("structure", "04be11c2aa90e77d"), schema: "structure@1" },
  prepared: { ...H("prepared_structure", "7a10fe3399c1d0e2"), schema: "structure@1" },
  interactions: { ...H("interaction_set", "9f3c55e0b7120ba1"), schema: "interaction_set@1" },
  selection: { ...H("selection", "p1aa00000000cc14"), schema: "selection@1" },
};

export const steps: Step[] = [
  { n: 1, tool: "load_structure", state: "done", cached: true },
  { n: 2, tool: "prepare_structure", state: "done", meta: "1.2s" },
  { n: 3, tool: "compute_interactions", state: "done", meta: "2.1s" },
  { n: 4, tool: "compile_state", state: "done", decidedBy: "jev" },
  { n: 5, tool: "detect_pockets", state: "done", result: "scientific_null" },
  { n: 6, tool: "plan", state: "done", decidedBy: "frontier" },
  { n: 7, tool: "estimate_stability", state: "failed", result: "precondition" },
  { n: 8, tool: "relax_structure", state: "pending", cost: "expensive" },
];

const r = (chain: string, seq: number, resname: string, icode = "", label?: [string, number]): ResidueRef =>
  ({ chain_auth: chain, seq_auth: seq, icode, chain_label: label?.[0] ?? chain, seq_label: label?.[1] ?? seq, resname });
export const interactions: InteractionRow[] = [
  { residue: r("A", 100, "ASP", "A", ["B", 97]), type: "hbond", distance_A: 2.8, engine: "consensus" },
  { residue: r("A", 48, "LEU"), type: "hydrophobic", distance_A: 3.91, engine: "prolif" },
  { residue: r("A", 45, "HIS"), type: "metal", distance_A: 2.05, engine: "plip" },
  { residue: r("B", 212, "TYR"), type: "hbond", distance_A: 3.02, engine: "consensus" },
  { residue: r("A", 52, "VAL"), type: "hydrophobic", distance_A: 4.12, engine: "prolif" },
];

export const budget: BudgetSnapshot = {
  wall_clock_s: { used: 684, limit: 1800 }, expensive_calls: { used: 6, limit: 8 },
  external_tokens: { used: 26400, limit: 120000 }, usd: { used: 2, limit: 2 },
};

export const models: ModelItem[] = [
  { id: "#1", name: "7XYZ crystal · prepared", handle: handles.prepared.handle, color: "model-a", visible: true, meta: "ref" },
  { id: "#2", name: "AF3 rank_1", handle: "obj://x/structure/2", color: "model-b", visible: true, meta: "pLDDT 88 · 0.9 Å" },
  { id: "#2.1", name: "relaxed · ref2015_cart", handle: "obj://x/relaxed_structure/21", color: "model-b", visible: false, meta: "−812.4 REU", child: true },
  { id: "#3", name: "AF3 rank_2", handle: "obj://x/structure/3", color: "model-c", visible: false, meta: "pLDDT 84 · 1.6 Å" },
  { id: "#4", name: "L48A mutant", handle: "obj://x/structure/4", color: "model-d", visible: false, meta: "ΔΔG +0.42" },
];

export const sequence = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAE";
export const mask: MaskState[] = sequence.split("").map((_, i) => ([8, 9, 12].includes(i) ? "design" : [5, 6, 7, 10, 11, 13, 14, 15].includes(i) ? "repack" : "fixed"));
export const plddtBins: TrackBin[] = sequence.split("").map((_, i) => (i > 4 && i < 30 ? "vh" : i < 38 ? "c" : i < 44 ? "l" : "vl"));
export const ddgBins: TrackBin[] = sequence.split("").map((_, i) => (({ 8: "us", 9: "f", 12: "fs", 5: "u", 13: "f" } as Record<number, TrackBin>)[i] ?? null));

export const pae: number[][] = Array.from({ length: 24 }, (_, i) => Array.from({ length: 24 }, (_, j) => {
  const same = (i < 14) === (j < 14);
  return same ? Math.abs(i - j) * 0.9 + (i >= 14 ? 2 : 0) : 20 + Math.abs(i - j) * 0.3;
}));

export const ddg: DdgRow[] = [
  { mutation: "L48A", ddg_REU: 0.42, sd_REU: 0.21, rounds_REU: [0.2, 0.5, 0.55], iterations: 3 },
  { mutation: "V52I", ddg_REU: -0.91, sd_REU: 0.18, rounds_REU: [-1.1, -0.8, -0.83], iterations: 3 },
  { mutation: "T61S", ddg_REU: -0.37, sd_REU: 0.4, rounds_REU: [-0.8, -0.1, -0.2], iterations: 3 },
  { mutation: "S75P", ddg_REU: 2.64, sd_REU: 0.55, rounds_REU: [2.1, 3.1, 2.7], iterations: 3 },
];

export const jobs: Job[] = [
  { id: "j_0142", protocol: "FastRelax cart · ref2015_cart", status: "running", progress: 0.62, elapsed: "2:41", seed: 1207, worker: "w2" },
  { id: "j_0143", protocol: "cartesian_ddg ×3 · L48A", status: "queued", seed: 1208 },
  { id: "j_0139", protocol: "InterfaceAnalyzer · A_B", status: "done", elapsed: "0:12", seed: 1204, worker: "w1" },
  { id: "j_0138", protocol: "FastRelax · ref2015", status: "failed", failure: "resource_exceeded", failureText: "timeout 900s", seed: 1203, worker: "w1" },
];

// Subset of config/tools.yaml for CommandBar autocompletion without a backend.
export const toolSpecs: ToolSpec[] = [
  { name: "compute_interactions", level: "L2", version: "0.1.0", accepts: { structure: ["prepared_structure", "relaxed_structure"] },
    params: { cutoff_A: { type: "float", default: 4.0, min: 2.5, max: 6 }, engine: { type: "str", enum: ["geometric", "prolif", "plip", "consensus"], default: "geometric" } },
    emits: "interaction_set", cost_class: "cheap", idempotent: true, read_only: false, typical_runtime_s: 2, description: "잔기–리간드 상호작용" },
  { name: "relax_structure", level: "L3", version: "0.1.0", accepts: { structure: ["prepared_structure"] },
    params: { scorefxn: { type: "str", enum: ["ref2015", "ref2015_cart"], default: "ref2015_cart" }, nstruct: { type: "int", default: 1 } },
    emits: "relaxed_structure", cost_class: "expensive", idempotent: true, read_only: false, typical_runtime_s: 180, description: "FastRelax (PyRosetta)" },
  { name: "prepare_structure", level: "L2", version: "0.1.0", accepts: { structure: ["structure"] },
    params: { waters: { type: "str", enum: ["strip_all", "keep_bridging", "keep_all"], default: "keep_bridging" } },
    emits: "prepared_structure", cost_class: "cheap", idempotent: true, read_only: false, typical_runtime_s: 1, description: "구조 준비 + manifest" },
];
export const resolveRef = (ref: string) =>
  ref === "#1" ? handles.prepared.handle : ref === "#2" ? "obj://x/structure/2" : ref === "P1" ? handles.selection.handle : undefined;
