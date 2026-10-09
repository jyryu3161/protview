/**
 * Pure logic of the report library in the "지식·보고서" tab (M14 spec section 7).
 *
 * Three independent lists of the current run (saved reports, saved figures, completed workflow
 * summaries) and one selected item's content. Every response is keyed by run id and a request
 * sequence; a response is applied only when its run is still current and no newer request for the
 * same list (or a newer selection) exists. The component owns the fetches and the sequence counter
 * (one monotonic counter is enough); this module never calls the network and never computes values.
 */
import type { SavedReportRef } from "./api";
import type { AnalysisExecutionList, AnalysisGoal, AnalysisSummary } from "./contracts";
import type { SavedFigureDetail, SavedPage } from "./saved-scene";

/** Backend cap of saved figures per run (`MAX_FIGURES`). */
export const RUN_FIGURE_LIMIT = 100;
/** Kind id of interaction reports (`report_manifest@1`); method reports use their `analysis_type`. */
export const INTERACTION_REPORT_KIND = "interaction_report";

export type LibraryListKind = "reports" | "figures" | "summaries";

export interface ReportLibraryRow { kind: string; handle: string; target_handle: string | null; created_seq: number }
export interface FigureLibraryRow { handle: string; scene_handle: string }
export interface SummaryLibraryRow { execution_id: string; goal: AnalysisGoal | null; summary_handle: string; created_seq: number | null }

export interface LibraryError { message: string; code: string | null }
export type ListState<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; rows: T[] }
  | ({ status: "error" } & LibraryError);

export type LibraryItem =
  | { kind: "report"; handle: string }
  | { kind: "figure"; handle: string }
  | { kind: "summary"; executionId: string; summaryHandle: string };

/** Report content is the saved Markdown text as-is; a figure is shown from its PNG download URL. */
export type LibraryContent =
  | { kind: "report"; handle: string; markdown: string }
  | { kind: "figure"; handle: string }
  | { kind: "summary"; executionId: string; summary: AnalysisSummary };

export type ContentState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; content: LibraryContent }
  | ({ status: "error" } & LibraryError);

export interface LibraryState {
  runId: string | null;
  lists: { reports: ListState<ReportLibraryRow>; figures: ListState<FigureLibraryRow>; summaries: ListState<SummaryLibraryRow> };
  /** Latest request sequence per list; kept across run switches so an old response can never match. */
  listSeq: Record<LibraryListKind, number>;
  selection: LibraryItem | null;
  selectionSeq: number;
  content: ContentState;
}

/** Raw responses per list: `/reports` rows, all figure pages concatenated, `/analysis/executions`. */
export interface ListResponses { reports: SavedReportRef[]; figures: SavedFigureDetail[]; summaries: AnalysisExecutionList }

export type LibraryAction =
  | { type: "run_changed"; runId: string | null }
  | { type: "list_request"; kind: LibraryListKind; runId: string | null; seq: number }
  | { [K in LibraryListKind]: { type: "list_loaded"; kind: K; runId: string; seq: number; response: ListResponses[K] } }[LibraryListKind]
  | ({ type: "list_failed"; kind: LibraryListKind; runId: string; seq: number } & LibraryError)
  | { type: "select"; runId: string | null; seq: number; item: LibraryItem }
  | { type: "content_loaded"; runId: string; seq: number; content: LibraryContent }
  | ({ type: "content_failed"; runId: string; seq: number } & LibraryError);

const IDLE = { status: "idle" } as const;

export function initialLibraryState(runId: string | null): LibraryState {
  return { runId, lists: { reports: IDLE, figures: IDLE, summaries: IDLE },
    listSeq: { reports: 0, figures: 0, summaries: 0 }, selection: null, selectionSeq: 0, content: IDLE };
}

/** No current run: show the "select a run first" guidance and send no request. */
export function isNoRun(state: LibraryState): boolean { return state.runId === null; }

export function buildReportRows(refs: SavedReportRef[]): ReportLibraryRow[] {
  return refs.map(ref => ({ kind: ref.analysis_type ?? INTERACTION_REPORT_KIND, handle: ref.handle,
    target_handle: ref.interaction_handle ?? ref.result_handle ?? null, created_seq: ref.created_seq }))
    .sort((a, b) => a.created_seq - b.created_seq);
}

export function reportKindLabel(row: ReportLibraryRow): string {
  if (row.kind === INTERACTION_REPORT_KIND) return "상호작용 보고서";
  if (row.kind === "residue_numbering") return "잔기 번호 대응 보고서";
  if (row.kind === "ligand_candidates") return "리간드 후보 보고서";
  if (row.kind === "ligand_docking") return "리간드 도킹 보고서";
  if (row.kind === "ligand_docking_batch") return "리간드 도킹 일괄 보고서";
  if (row.kind === "ligand_ga") return "리간드 GA 설계 보고서";
  if (row.kind === "mutation_candidates") return "변이 후보 보고서";
  if (row.kind === "mutation_model") return "변이 구조 모델 보고서";
  if (row.kind === "sequence_ga") return "서열 GA 보고서";
  if (row.kind === "jev_choice") return "JEV 판정 보고서";
  if (row.kind === "jev_loop") return "JEV 루프 보고서";
  if (row.kind === "reaction_knowledge") return "효소 반응 지식 보고서";
  return row.kind === "reference_site_annotation" ? "참조 주석 보고서" : row.kind;
}

/** Server order (newest first) is kept as-is. */
export function buildFigureRows(details: SavedFigureDetail[]): FigureLibraryRow[] {
  return details.map(detail => ({ handle: detail.handle, scene_handle: detail.value.scene_handle }));
}

/** Only complete executions that have a summary handle; damaged rows (`error`) are excluded. */
export function buildSummaryRows(list: AnalysisExecutionList): SummaryLibraryRow[] {
  const rows: SummaryLibraryRow[] = [];
  for (const row of list.rows) {
    if (row.status !== "complete" || !row.summary_handle || row.error) continue;
    rows.push({ execution_id: row.execution_id, goal: row.goal, summary_handle: row.summary_handle, created_seq: row.created_seq });
  }
  return rows.sort((a, b) => (a.created_seq ?? Infinity) - (b.created_seq ?? Infinity));
}

/** Reads every figure page and concatenates them; throws instead of returning a partial list. */
export async function readAllFigurePages(fetchPage: (offset: number) => Promise<SavedPage<SavedFigureDetail>>): Promise<SavedFigureDetail[]> {
  const first = await fetchPage(0);
  if (first.total > RUN_FIGURE_LIMIT) throw new Error(`저장된 그림 수(${first.total})가 run 한도 ${RUN_FIGURE_LIMIT}를 넘습니다.`);
  const rows = [...first.rows];
  while (rows.length < first.total) {
    const page = await fetchPage(rows.length);
    if (page.total !== first.total || !page.rows.length) throw new Error("그림 목록이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
    rows.push(...page.rows);
  }
  if (rows.length !== first.total) throw new Error("그림 목록이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
  return rows;
}

/** Server reason of a failed read (ApiError message and typed code); never invents a code. */
export function errorDetail(error: unknown): LibraryError {
  if (typeof error === "object" && error !== null && typeof (error as { message?: unknown }).message === "string") {
    const { message, code } = error as { message: string; code?: unknown };
    return { message, code: typeof code === "string" ? code : null };
  }
  return { message: String(error), code: null };
}

function buildRows(action: Extract<LibraryAction, { type: "list_loaded" }>) {
  switch (action.kind) {
    case "reports": return buildReportRows(action.response);
    case "figures": return buildFigureRows(action.response);
    case "summaries": return buildSummaryRows(action.response);
  }
}

function contentMatches(item: LibraryItem, content: LibraryContent): boolean {
  if (item.kind !== content.kind) return false;
  if (item.kind === "summary") return content.kind === "summary" && content.executionId === item.executionId;
  return content.kind !== "summary" && content.handle === item.handle;
}

export function libraryReducer(state: LibraryState, action: LibraryAction): LibraryState {
  switch (action.type) {
    case "run_changed":
      if (action.runId === state.runId) return state;
      return { ...initialLibraryState(action.runId), listSeq: state.listSeq, selectionSeq: state.selectionSeq };
    case "list_request":
      if (action.runId === null || action.runId !== state.runId || action.seq <= state.listSeq[action.kind]) return state;
      return { ...state, listSeq: { ...state.listSeq, [action.kind]: action.seq },
        lists: { ...state.lists, [action.kind]: { status: "loading" } } };
    case "list_loaded":
    case "list_failed": {
      if (action.runId !== state.runId || action.seq !== state.listSeq[action.kind]) return state;
      const next = action.type === "list_loaded" ? { status: "ready" as const, rows: buildRows(action) }
        : { status: "error" as const, message: action.message, code: action.code };
      return { ...state, lists: { ...state.lists, [action.kind]: next } };
    }
    case "select":
      if (action.runId === null || action.runId !== state.runId || action.seq <= state.selectionSeq) return state;
      return { ...state, selection: action.item, selectionSeq: action.seq,
        content: action.item.kind === "figure" ? { status: "ready", content: { kind: "figure", handle: action.item.handle } }
          : { status: "loading" } };
    case "content_loaded":
      if (action.runId !== state.runId || action.seq !== state.selectionSeq || !state.selection ||
          !contentMatches(state.selection, action.content)) return state;
      return { ...state, content: { status: "ready", content: action.content } };
    case "content_failed":
      if (action.runId !== state.runId || action.seq !== state.selectionSeq || !state.selection) return state;
      return { ...state, content: { status: "error", message: action.message, code: action.code } };
  }
}
