"use client";
import type { ReactNode } from "react";
import { useState } from "react";
import type { EgressMode } from "@/lib/contracts";
import { Button, Eyebrow, Kbd, Segmented } from "./primitives";

export type RailTab = "run" | "models" | "jobs";

export interface WorkspaceShellProps {
  runId?: string;
  pipeline?: string;
  egress: EgressMode;
  onEgressChange?: (m: EgressMode) => void;
  budgetShort?: ReactNode;      // e.g. <CostMark cost="expensive" text="expensive 6/8" />
  onStop?: () => void;
  onPalette?: () => void;
  onToggleTheme?: () => void;
  railCounts?: Partial<Record<RailTab, number>>;
  rail: Record<RailTab, ReactNode>;
  tabs?: RailTab[];
  railFooter?: ReactNode;        // ApprovalGate (or GoalComposer when no run)
  canvas: ReactNode;             // <MolstarViewer/>
  canvasOverlayTopLeft?: ReactNode;
  canvasLegend?: ReactNode;
  strip?: ReactNode;             // SequenceTrack + CommandBar
  inspectorTitle: string;
  inspectorAction?: ReactNode;
  inspector: ReactNode;
}

export function WorkspaceShell(p: WorkspaceShellProps) {
  const [tab, setTab] = useState<RailTab>("run");
  return (
    <div className="mw-root mw-shell" style={{ height: "100vh" }}>
      <header className="mw-topbar">
        <span className="mw-mono" style={{ fontWeight: 500 }}>{p.runId ?? "no run"}</span>
        {p.pipeline && <span className="mw-muted" style={{ fontSize: 13 }}>{p.pipeline}</span>}
        <span style={{ flex: 1 }} />
        {p.onEgressChange ? <Segmented label="egress mode" value={p.egress} onChange={p.onEgressChange} options={[
          { value: "online", dotColor: "var(--egress-online)" },
          { value: "local_only", dotColor: "var(--egress-local)" },
          { value: "dry_run" },
        ]} /> : <span className="mw-badge">● {p.egress}</span>}
        {p.budgetShort}
        {p.onPalette && <Button variant="ghost" onClick={p.onPalette}>명령 <Kbd>⌘K</Kbd></Button>}
        {p.onToggleTheme && <Button variant="ghost" onClick={p.onToggleTheme} aria-label="테마 전환">◐</Button>}
        {p.onStop && <Button variant="stop" onClick={p.onStop}>■ 중단</Button>}
      </header>

      <aside className="mw-panel">
        <div className="mw-tabs" role="tablist">
          {(p.tabs ?? ["run", "models", "jobs"]).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
              {t}{p.railCounts?.[t] != null && ` · ${p.railCounts[t]}`}
            </button>
          ))}
        </div>
        <div style={{ overflow: "auto", minHeight: 0, flex: 1 }}>{p.rail[tab]}</div>
        {p.railFooter && <div style={{ padding: "var(--space-3)" }}>{p.railFooter}</div>}
      </aside>

      <div style={{ display: "flex", flexDirection: "column", minHeight: 0, gap: 1, background: "var(--surface-000)" }}>
        <main className="mw-canvas" style={{ flex: 1 }}>
          {p.canvas}
          {p.canvasOverlayTopLeft && <div style={{ position: "absolute", left: "var(--space-3)", top: "var(--space-3)", display: "flex", gap: "var(--space-2)" }}>{p.canvasOverlayTopLeft}</div>}
          {p.canvasLegend && (
            <div style={{ position: "absolute", right: "var(--space-3)", bottom: "var(--space-3)", background: "var(--surface-100)", border: "1px solid var(--line)", borderRadius: "var(--radius-md)", padding: "var(--space-2) var(--space-3)", display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
              {p.canvasLegend}
            </div>
          )}
        </main>
        {p.strip && <div style={{ background: "var(--surface-100)", padding: "var(--space-2) var(--space-3)", display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>{p.strip}</div>}
      </div>

      <aside className="mw-panel">
        <div className="mw-panel__head"><Eyebrow>{p.inspectorTitle}</Eyebrow>{p.inspectorAction}</div>
        <div style={{ overflow: "auto", minHeight: 0, flex: 1 }}>{p.inspector}</div>
      </aside>
    </div>
  );
}

export function InspectorSection({ children, flush }: { children: ReactNode; flush?: boolean }) {
  return <div style={{ padding: flush ? 0 : "var(--space-3)", borderBottom: "1px solid var(--line)", display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>{children}</div>;
}
