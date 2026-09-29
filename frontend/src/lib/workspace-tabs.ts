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
export const UNAVAILABLE_NOTICES: Record<"protein" | "ligand" | "knowledge", UnavailableNotice> = {
  protein: {
    title: "단백질 공학",
    reason: "아직 구현하지 않았습니다.",
    opens: [{ stage: "M20", feature: "변이 후보 생성" }, { stage: "M21", feature: "변이 구조 모델링" }],
  },
  ligand: {
    title: "리간드 설계·탐색",
    reason: "아직 구현하지 않았습니다.",
    opens: [{ stage: "M17", feature: "결합 부위 지정·후보 생성·필터" }, { stage: "M18", feature: "도킹" }],
    note: "M11 화학 상호작용 계산은 구조 분석 탭의 화학 상호작용 작업 화면에 있습니다.",
  },
  knowledge: {
    title: "지식",
    reason: "아직 구현하지 않았습니다.",
    opens: [{ stage: "M15", feature: "참조 스냅샷과 잔기 번호 대응" }],
  },
};
