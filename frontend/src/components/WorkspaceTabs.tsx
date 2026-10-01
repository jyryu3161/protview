"use client";
import type { ReactNode } from "react";
import type { BudgetSnapshot } from "@/lib/contracts";
import { UNAVAILABLE_NOTICES, UNAVAILABLE_STATUS, WORKSPACE_TABS, type UnavailableNotice, type WorkspaceTabId } from "@/lib/workspace-tabs";

export interface WorkspaceTabsProps {
  active: WorkspaceTabId;
  onSelect: (id: WorkspaceTabId) => void;
  runId?: string | null;          // read-only view of the page's current run
  budget?: BudgetSnapshot | null; // read-only view of the page's budget state
  structure: ReactNode;           // existing structure screen; stays mounted while another tab is shown
  reports?: ReactNode;            // 지식·보고서 tab report body (rendered only while that tab is shown)
  numbering?: ReactNode;          // 지식·보고서 tab residue numbering screen (rendered only while that tab is shown)
  ligand?: ReactNode;             // 리간드 설계·탐색 tab body (M17; rendered only while that tab is shown)
}

function UnavailableSection({ notice }: { notice: UnavailableNotice }) {
  return (
    <section className="mw-unavailable" aria-label={`${notice.title} ${UNAVAILABLE_STATUS}`}>
      <h2 className="mw-unavailable__title">{notice.title}</h2>
      <p className="mw-unavailable__status">{UNAVAILABLE_STATUS}</p>
      <p>{notice.reason}</p>
      <ul className="mw-unavailable__opens">
        {notice.opens.map(item => <li key={item.stage}>{item.feature}: {item.stage}에서 열립니다.</li>)}
      </ul>
      {notice.note && <p className="mw-unavailable__note">{notice.note}</p>}
    </section>
  );
}

export function WorkspaceTabs(p: WorkspaceTabsProps) {
  const structureShown = p.active === "structure";
  return (
    <div className="mw-root mw-app">
      <header className="mw-app-bar">
        <div className="mw-app-tabs" role="tablist" aria-label="작업 영역">
          {WORKSPACE_TABS.map(tab => (
            <button key={tab.id} type="button" role="tab" id={`mw-app-tab-${tab.id}`} aria-controls={tab.id === "structure" || p.active === tab.id ? `mw-app-panel-${tab.id}` : undefined}
              aria-selected={p.active === tab.id} onClick={() => { if (p.active !== tab.id) p.onSelect(tab.id); }}>
              {tab.label}
            </button>
          ))}
        </div>
        <span style={{ flex: 1 }} />
        <span className="mw-mono mw-app-run" aria-label="현재 run" data-global-run={p.runId ?? ""}>{p.runId ?? "run 없음"}</span>
        {p.budget && <span className="mw-mono mw-muted mw-app-budget" aria-label="이 run의 예산">
          expensive {p.budget.expensive_calls.used}/{p.budget.expensive_calls.limit}</span>}
      </header>
      <div className="mw-app-body">
        {/* Hidden with visibility (not display:none/unmount) so the viewer keeps its size, state and polling. */}
        <div role="tabpanel" id="mw-app-panel-structure" aria-labelledby="mw-app-tab-structure"
          className="mw-app-panel mw-app-panel--structure" data-shown={structureShown} inert={!structureShown}>
          {p.structure}
        </div>
        {p.active === "protein" && <div role="tabpanel" id="mw-app-panel-protein" aria-labelledby="mw-app-tab-protein" className="mw-app-panel">
          <UnavailableSection notice={UNAVAILABLE_NOTICES.protein} />
        </div>}
        {p.active === "ligand" && <div role="tabpanel" id="mw-app-panel-ligand" aria-labelledby="mw-app-tab-ligand" className="mw-app-panel">
          {p.ligand != null && <div className="mw-app-ligand">{p.ligand}</div>}
        </div>}
        {p.active === "knowledge" && <div role="tabpanel" id="mw-app-panel-knowledge" aria-labelledby="mw-app-tab-knowledge" className="mw-app-panel">
          {p.numbering != null && <div className="mw-app-numbering">{p.numbering}</div>}
          {p.reports != null && <div className="mw-app-reports">{p.reports}</div>}
        </div>}
      </div>
    </div>
  );
}
