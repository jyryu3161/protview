import type { ReactNode } from "react";
import type { BudgetSnapshot, CostClass, DecisionSource, Fix, Handle, ResultClass, StepState } from "@/lib/contracts";
import { Button, Eyebrow, HandleChip } from "./primitives";
import { CostMark, DecisionTag, FailureBadge, STEP_GLYPH } from "./status";

/* StepRow ------------------------------------------------------------------ */
export interface Step {
  n: number;
  tool: string;
  state: StepState;
  decidedBy?: DecisionSource;
  result?: ResultClass;         // failure class, or scientific_null on a done step
  cost?: CostClass;
  meta?: string;                // "2.1s", "2:41 / ~3:00", "retry 1/1"
  cached?: boolean;
  sub?: ReactNode;              // handles, one-line note
  callId?: string;
}
export function StepRow({ step, selected, onSelect }: { step: Step; selected?: boolean; onSelect?: (s: Step) => void }) {
  return (
    <li className="mw-step" aria-selected={selected} onClick={() => onSelect?.(step)}>
      <span className="mw-step__n">#{String(step.n).padStart(2, "0")}</span>
      <span className={`mw-step__g mw-s-${step.state}`}>{STEP_GLYPH[step.state]}</span>
      <span className={`mw-step__tool${step.state === "pending" ? " mw-muted" : ""}`}>{step.tool}</span>
      <span className="mw-step__meta">
        {step.decidedBy && step.decidedBy !== "rule" && !step.result && <DecisionTag source={step.decidedBy} />}
        {step.result && <FailureBadge cls={step.result} short={step.result === "scientific_null" ? "null" : undefined} />}
        {step.cost && <CostMark cost={step.cost} />}
        {step.cached ? "↺ cached" : step.meta}
      </span>
      {step.sub && <span className="mw-step__sub">{step.sub}</span>}
    </li>
  );
}
export function StepList({ steps, selected, onSelect }: { steps: Step[]; selected?: number; onSelect?: (s: Step) => void }) {
  return <ol className="mw-steps">{steps.map((s) => <StepRow key={s.n} step={s} selected={s.n === selected} onSelect={onSelect} />)}</ol>;
}

/* BudgetMeter -------------------------------------------------------------- */
const AXIS_LABEL: Record<keyof BudgetSnapshot, string> = {
  wall_clock_s: "wall_clock", expensive_calls: "expensive", external_tokens: "ext_tokens", usd: "usd",
};
function fmtAxis(k: keyof BudgetSnapshot, v: number) {
  if (k === "wall_clock_s") return `${Math.floor(v / 60)}:${String(Math.round(v % 60)).padStart(2, "0")}`;
  if (k === "external_tokens") return v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k` : String(v);
  if (k === "usd") return `$${v.toFixed(2)}`;
  return String(v);
}
export function BudgetMeter({ budget }: { budget: BudgetSnapshot }) {
  return (
    <div className="mw-budget">
      {(Object.keys(AXIS_LABEL) as (keyof BudgetSnapshot)[]).map((k) => {
        const { used, limit } = budget[k];
        const r = limit ? used / limit : 0;
        const cls = r >= 1 ? "mw-bar mw-bar--out" : r >= 0.75 ? "mw-bar mw-bar--warn" : "mw-bar";
        return [
          <span key={k + "k"} className="mw-budget__k">{AXIS_LABEL[k]}</span>,
          <span key={k + "b"} className={cls}><i style={{ width: `${Math.min(100, r * 100)}%` }} /></span>,
          <span key={k + "v"} className="mw-budget__v">{fmtAxis(k, used)} / {fmtAxis(k, limit)}</span>,
        ];
      })}
    </div>
  );
}

/* ApprovalGate ------------------------------------------------------------- */
export type GateKind = "expensive_first_call" | "write_outside_run_dir" | "egress_l2_plus" | "final_selection" | "budget";
export interface ApprovalGateProps {
  gate: GateKind;
  question: string;             // "relax_structure를 실행할까요?"
  why?: string;
  plan?: string[];              // ≤ 5 mono lines
  planSource?: DecisionSource;
  compact?: boolean;
  primaryLabel?: string;        // defaults to "실행"
  onApprove?: () => void;
  onDryRun?: () => void;
  onStop?: () => void;
}
export function ApprovalGate(p: ApprovalGateProps) {
  return (
    <div className="mw-gate" style={p.compact ? { boxShadow: "none", padding: "var(--space-3)", gap: "var(--space-2)" } : undefined}>
      <div className="mw-row">
        <Eyebrow>checkpoint_and_ask</Eyebrow>
        {p.gate === "expensive_first_call" && <CostMark cost="expensive" text="$$$ expensive · 첫 호출" />}
        {p.gate === "budget" && <CostMark cost="expensive" text="예산 소진" />}
      </div>
      <h3 className="mw-gate__title" style={p.compact ? { fontSize: 14, lineHeight: "20px" } : undefined}>{p.question}</h3>
      {p.why && <p className="mw-gate__why">{p.why}</p>}
      {p.plan && !p.compact && (
        <pre className="mw-gate__plan">{`다음 계획${p.planSource ? " " + { rule: "≡", jev: "◆", frontier: "✦", human: "●" }[p.planSource] + " " + p.planSource : ""}\n` +
          p.plan.slice(0, 5).map((l, i) => ` ${i + 1}  ${l}`).join("\n")}</pre>
      )}
      <div className="mw-gate__actions">
        <Button variant="ghost" size={p.compact ? "sm" : "md"} onClick={p.onStop}>여기서 멈춤</Button>
        {!p.compact && p.onDryRun && <Button onClick={p.onDryRun}>드라이런으로</Button>}
        <Button variant="primary" size={p.compact ? "sm" : "md"} onClick={p.onApprove}>{p.primaryLabel ?? "실행"}</Button>
      </div>
    </div>
  );
}

/* ToolErrorCard ------------------------------------------------------------ */
export function ToolErrorCard({ tool, message, cls, fix, fixKind, onFix }: {
  tool: string; message: string; cls: ResultClass; fix?: Fix | null; fixKind?: string; onFix?: (f: Fix) => void;
}) {
  const handleArg = fix && Object.entries(fix.args).find(([, v]) => typeof v === "string" && v.startsWith("obj://"));
  return (
    <div className="mw-err">
      <p className="mw-err__msg"><span className="mw-mono">{tool}</span> — {message}</p>
      <FailureBadge cls={cls} />
      {fix && (
        <div className="mw-err__fix">
          <span>fix</span>
          {handleArg
            ? <HandleChip handle={{ handle: String(handleArg[1]), kind: fix.tool }} label={`${handleArg[0]}: ${String(handleArg[1]).split("/").pop()?.slice(0, 4)}…`} />
            : <span className="mw-mono">{fix.tool}</span>}
          <Button size="sm" onClick={() => onFix?.(fix)}>선행 실행</Button>
          {fixKind && <span className="mw-muted">→ {fixKind}</span>}
        </div>
      )}
    </div>
  );
}

/* EgressGateView ----------------------------------------------------------- */
export function EgressGateView({ destination, tokens, fields, logRef, mode, onShowPayload }: {
  destination: string; tokens?: number; fields: { name: string; blocked: boolean }[];
  logRef?: string; mode: "online" | "local_only" | "dry_run"; onShowPayload?: () => void;
}) {
  if (mode !== "online") {
    return <div className="mw-egress"><span className="mw-muted" style={{ fontSize: 12 }}>외부 호출 없음 · rule 폴백 ({mode})</span></div>;
  }
  return (
    <div className="mw-egress">
      <div className="mw-row" style={{ justifyContent: "space-between" }}>
        <Eyebrow>egress · {destination}</Eyebrow>
        {tokens != null && <span className="mw-muted mw-mono" style={{ fontSize: 12 }}>{tokens.toLocaleString()} tokens</span>}
      </div>
      <div className="mw-egress__fields">
        {fields.map((f) => <span key={f.name} className={`mw-field${f.blocked ? " mw-field--blocked" : ""}`}>{f.name}</span>)}
      </div>
      {logRef && (
        <div className="mw-row mw-muted" style={{ fontSize: 12 }}>
          egress.jsonl {logRef} 에 전문 기록됨
          <Button size="sm" variant="ghost" onClick={onShowPayload}>페이로드 보기</Button>
        </div>
      )}
    </div>
  );
}

export type { Handle };
