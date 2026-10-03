// M14 top-level workspace tabs. Tab switching is in-page state only (no URL change).
// Labels must not start with the rail tab names "run"/"models" (offscreen locators use ^run / ^models).

export type WorkspaceTabId = "structure" | "protein" | "ligand" | "knowledge";

export interface WorkspaceTab { id: WorkspaceTabId; label: string }

export const WORKSPACE_TABS: readonly WorkspaceTab[] = [
  { id: "structure", label: "구조 분석" },
  { id: "protein", label: "단백질 공학" },
  { id: "ligand", label: "리간드 설계·탐색" },
  { id: "knowledge", label: "지식·보고서" },
];

export const DEFAULT_WORKSPACE_TAB: WorkspaceTabId = "structure";

export function isWorkspaceTabId(value: unknown): value is WorkspaceTabId {
  return typeof value === "string" && WORKSPACE_TABS.some(tab => tab.id === value);
}

export const UNAVAILABLE_STATUS = "사용할 수 없음";

export interface UnavailableNotice {
  title: string;
  reason: string;
  opens: { stage: string; feature: string }[];
  note?: string;
}

// Notices only: no numbers, placeholder values or controls. These tabs make no backend calls.
// No tab has a notice any more: the knowledge tab since M15 (residue numbering screen and report library), the ligand
// tab since M17 (ligand partial-replacement candidate screen) and the protein tab since M20 (mutation candidate
// screen). The type and the shared "사용할 수 없음" wording stay for a later tab without a feature.
export const UNAVAILABLE_NOTICES: Record<never, UnavailableNotice> = {};
