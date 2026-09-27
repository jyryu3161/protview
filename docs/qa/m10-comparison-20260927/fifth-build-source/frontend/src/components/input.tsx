"use client";
import { useMemo, useState } from "react";
import type { EgressMode, Handle, ToolSpec } from "@/lib/contracts";
import { Button, HandleChip, Kbd } from "./primitives";

/* GoalComposer -------------------------------------------------------------- */
export interface GoalSubmit { goal: string; context: string[]; pipeline: string; budget: string; egress: EgressMode; dryRun: boolean }
export interface GoalComposerProps {
  context: (Pick<Handle, "handle" | "kind"> & { label?: string })[];
  pipelines?: string[];
  budgets?: string[];
  egress?: EgressMode;
  estimateTokens?: (goal: string) => number;
  onAddContext?: () => void;
  onSubmit: (s: GoalSubmit) => void;
}
export function GoalComposer({ context, pipelines = ["auto"], budgets = ["standard"], egress = "local_only",
  estimateTokens, onAddContext, onSubmit }: GoalComposerProps) {
  const [goal, setGoal] = useState("");
  const [pipeline, setPipeline] = useState(pipelines[0]);
  const [budget, setBudget] = useState(budgets[0]);
  const [mode, setMode] = useState<EgressMode>(egress);
  const submit = (dryRun: boolean) => goal.trim() && onSubmit({ goal, context: context.map((c) => c.handle), pipeline, budget, egress: mode, dryRun });
  return (
    <div className="mw-composer">
      <div className="mw-composer__ctx">
        {context.map((c) => <HandleChip key={c.handle} handle={c} label={c.label} />)}
        <Button size="sm" variant="ghost" onClick={onAddContext}>+ 컨텍스트</Button>
      </div>
      <textarea aria-label="목표" placeholder="무엇을 알고 싶은지 적으세요" value={goal}
        onChange={(e) => setGoal(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(false); }} />
      <div className="mw-composer__bar">
        <select className="mw-select" value={pipeline} onChange={(e) => setPipeline(e.target.value)} aria-label="pipeline">
          {pipelines.map((p) => <option key={p} value={p}>pipeline: {p}</option>)}
        </select>
        <select className="mw-select" value={budget} onChange={(e) => setBudget(e.target.value)} aria-label="budget">
          {budgets.map((b) => <option key={b} value={b}>budget: {b}</option>)}
        </select>
        <select className="mw-select" value={mode} onChange={(e) => setMode(e.target.value as EgressMode)} aria-label="egress">
          {(["local_only", "online", "dry_run"] as EgressMode[]).map((m) => <option key={m} value={m}>egress: {m}</option>)}
        </select>
        <span style={{ flex: 1 }} />
        {estimateTokens && <span className="mw-muted mw-mono" style={{ fontSize: 12 }}>≈{(estimateTokens(goal) / 1000).toFixed(1)}k tok</span>}
        <Button onClick={() => submit(true)}>계획만</Button>
        <Button variant="primary" onClick={() => submit(false)}>▶ 실행 <Kbd>⌘↵</Kbd></Button>
      </div>
    </div>
  );
}

/* CommandBar ----------------------------------------------------------------- */
/** Parses `tool key=value ...` against ToolSpecs. Short refs (#2, P1) are resolved via `resolveRef`
 *  BEFORE execution and the full JSON is shown. The DSL string itself never reaches a tool. */
export interface ParsedCommand { tool: string; args: Record<string, unknown>; errors: string[] }
export function parseCommand(input: string, specs: ToolSpec[], resolveRef: (ref: string) => string | undefined): ParsedCommand {
  const [tool, ...parts] = input.trim().split(/\s+/);
  const spec = specs.find((s) => s.name === tool);
  const errors: string[] = [];
  const args: Record<string, unknown> = {};
  if (!spec) return { tool: tool ?? "", args, errors: tool ? [`unknown tool ${tool}`] : [] };
  for (const p of parts) {
    const [k, raw] = p.split("=");
    if (!raw) continue;
    if (k in spec.accepts) {
      const h = raw.startsWith("obj://") ? raw : resolveRef(raw);
      if (!h) errors.push(`cannot resolve ${raw}`); else args[k] = h;
    } else if (k in spec.params) {
      const t = spec.params[k].type;
      const v = t === "int" ? parseInt(raw, 10) : t === "float" ? parseFloat(raw) : t === "bool" ? raw === "true" : t === "list" ? raw.split(",") : raw;
      if (spec.params[k].enum && ![v].flat().every((x) => spec.params[k].enum!.includes(String(x)))) errors.push(`${k}: not in enum`);
      args[k] = v;
    } else errors.push(`unknown arg ${k}`);
  }
  return { tool, args, errors };
}

export interface CommandBarProps {
  specs: ToolSpec[];
  resolveRef: (ref: string) => string | undefined;
  onRun: (cmd: ParsedCommand) => void;
  history?: string[];
}
export function CommandBar({ specs, resolveRef, onRun, history = [] }: CommandBarProps) {
  const [value, setValue] = useState("");
  const [hi, setHi] = useState(history.length);
  const parsed = useMemo(() => parseCommand(value, specs, resolveRef), [value, specs, resolveRef]);
  const spec = specs.find((s) => s.name === parsed.tool);
  const typedToolOnly = !value.includes(" ");
  const suggestions = typedToolOnly
    ? specs.filter((s) => s.name.startsWith(value)).slice(0, 5).map((s) => ({ k: s.name, d: s.description || s.emits, c: s.cost_class }))
    : spec ? [...Object.keys(spec.accepts).map((k) => ({ k: `${k}: handle`, d: spec.accepts[k].join(" · "), c: "" })),
              ...Object.entries(spec.params).map(([k, p]) => ({ k: `${k}: ${p.type}`, d: p.enum ? p.enum.join(" · ") : `기본 ${String(p.default ?? "—")}`, c: "" }))]
              .filter((s) => !value.includes(s.k.split(":")[0] + "=")).slice(0, 5) : [];
  return (
    <div className="mw-cmd">
      <div className="mw-cmd__input">
        <span className="mw-cmd__prompt">›</span>
        <input aria-label="명령" value={value} spellCheck={false}
          style={{ flex: 1, background: "transparent", border: 0, outline: 0, color: "var(--ink)", font: "inherit" }}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && spec && !parsed.errors.length) { onRun(parsed); setValue(""); }
            if (e.key === "ArrowUp" && history.length) { const i = Math.max(0, hi - 1); setHi(i); setValue(history[i]); }
            if (e.key === "ArrowDown" && history.length) { const i = Math.min(history.length, hi + 1); setHi(i); setValue(history[i] ?? ""); }
          }} />
      </div>
      {value && suggestions.length > 0 && (
        <ul className="mw-cmd__menu">
          {suggestions.map((s, i) => (
            <li key={s.k} aria-selected={i === 0}><span>{s.k}</span><span className="desc">{s.d}</span><span className="mw-cost">{s.c || "—"}</span></li>
          ))}
        </ul>
      )}
      {spec && (
        <div className="mw-cmd__preview">{parsed.errors.length ? `✎ ${parsed.errors.join(" · ")}` : JSON.stringify({ tool: parsed.tool, args: parsed.args })}</div>
      )}
    </div>
  );
}
