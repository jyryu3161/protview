"use client";

import { useCallback, useEffect, useReducer, useRef, useState, type ReactNode } from "react";
import { api, type RunSummary } from "@/lib/api";
import { errorDetail, initialLibraryState, libraryReducer, readAllFigurePages, reportKindLabel,
  type ContentState, type LibraryError, type LibraryItem, type LibraryListKind, type ListState } from "@/lib/report-library";
import { Button } from "./primitives";

/**
 * Reports part of the "지식·보고서" tab (M14 spec section 7): three independent read-only lists of the
 * current run and the selected item's saved content. It never creates reports, never opens the
 * structure analysis tab and never computes or renames values. Late responses are dropped by the
 * reducer (run id + request sequence); downloads happen only through user-clicked links.
 */
export interface ReportLibraryPanelProps {
  /** Current run owned by the structure analysis screen; null when no run is selected. */
  run: RunSummary | null;
  /** True while the tab is visible; lists are (re)read when it turns true and on run change while true. */
  active: boolean;
  /** Incremented by another panel after it created a report; the reports list is re-read on each change. */
  reloadToken?: number;
}

const LIST_KINDS: LibraryListKind[] = ["reports", "figures", "summaries"];
const LIST_LABELS: Record<LibraryListKind, string> = { reports: "저장된 보고서", figures: "저장된 그림", summaries: "분석 흐름 요약" };

function ErrorLine({ error, onRetry }: { error: LibraryError; onRetry: () => void }) {
  return <div className="mw-library-error" role="alert">
    <span>읽지 못했습니다: {error.message}{error.code ? ` (${error.code})` : ""}</span>
    <Button size="sm" onClick={onRetry}>다시 시도</Button>
  </div>;
}

function ListBody<T>({ state, onRetry, render }: { state: ListState<T>; onRetry: () => void; render: (rows: T[]) => ReactNode }) {
  switch (state.status) {
    case "idle": return <p className="mw-library-note">아직 읽지 않았습니다.</p>;
    case "loading": return <p className="mw-library-note" aria-busy="true">불러오는 중</p>;
    case "error": return <ErrorLine error={state} onRetry={onRetry} />;
    case "ready": return state.rows.length ? <ul className="mw-library-rows">{render(state.rows)}</ul>
      : <p className="mw-library-note">아직 없음</p>;
  }
}

function sameItem(a: LibraryItem | null, b: LibraryItem): boolean {
  if (!a || a.kind !== b.kind) return false;
  if (a.kind === "summary") return b.kind === "summary" && a.executionId === b.executionId;
  return b.kind !== "summary" && a.handle === b.handle;
}

export function ReportLibraryPanel({ run, active, reloadToken = 0 }: ReportLibraryPanelProps) {
  const runId = run?.run_id ?? null;
  const [state, dispatch] = useReducer(libraryReducer, runId, initialLibraryState);
  const seqRef = useRef(0);
  const listAborts = useRef<Partial<Record<LibraryListKind, AbortController>>>({});
  const contentAbort = useRef<AbortController | null>(null);

  const abortAll = useCallback(() => {
    for (const kind of LIST_KINDS) listAborts.current[kind]?.abort();
    listAborts.current = {};
    contentAbort.current?.abort();
    contentAbort.current = null;
  }, []);

  // Declared before the loading effect so run_changed is dispatched before the new run's list requests.
  useEffect(() => {
    dispatch({ type: "run_changed", runId });
    return abortAll;
  }, [runId, abortAll]);

  const loadList = useCallback((kind: LibraryListKind) => {
    if (runId === null) return;
    const seq = ++seqRef.current;
    listAborts.current[kind]?.abort();
    const controller = new AbortController();
    listAborts.current[kind] = controller;
    const signal = controller.signal;
    dispatch({ type: "list_request", kind, runId, seq });
    const fail = (error: unknown) => dispatch({ type: "list_failed", kind, runId, seq, ...errorDetail(error) });
    if (kind === "reports") {
      api.reports(runId, signal).then(response => dispatch({ type: "list_loaded", kind, runId, seq, response }), fail);
    } else if (kind === "figures") {
      readAllFigurePages(offset => api.savedFigures(runId, offset))
        .then(response => dispatch({ type: "list_loaded", kind, runId, seq, response }), fail);
    } else {
      api.analysisExecutions(runId, signal).then(response => dispatch({ type: "list_loaded", kind, runId, seq, response }), fail);
    }
  }, [runId]);

  const loadAll = useCallback(() => { for (const kind of LIST_KINDS) loadList(kind); }, [loadList]);

  useEffect(() => { if (active && runId !== null) loadAll(); }, [active, runId, loadAll]);

  const seenReloadToken = useRef(reloadToken);
  useEffect(() => {
    if (seenReloadToken.current === reloadToken) return;
    seenReloadToken.current = reloadToken;
    if (active && runId !== null) loadList("reports");
  }, [reloadToken, active, runId, loadList]);

  const select = useCallback((item: LibraryItem) => {
    if (runId === null) return;
    const seq = ++seqRef.current;
    contentAbort.current?.abort();
    contentAbort.current = null;
    dispatch({ type: "select", runId, seq, item });
    if (item.kind === "figure") return;
    const controller = new AbortController();
    contentAbort.current = controller;
    const fail = (error: unknown) => dispatch({ type: "content_failed", runId, seq, ...errorDetail(error) });
    if (item.kind === "report") {
      api.methodReport(runId, item.handle, controller.signal).then(artifact => dispatch({ type: "content_loaded", runId, seq,
        content: { kind: "report", handle: item.handle, markdown: artifact.markdown } }), fail);
    } else {
      api.analysisSummary(runId, item.executionId, controller.signal).then(summary => dispatch({ type: "content_loaded", runId, seq,
        content: { kind: "summary", executionId: item.executionId, summary } }), fail);
    }
  }, [runId]);

  if (runId === null) {
    return <section className="mw-library" aria-label="보고서 보관함">
      <p className="mw-library-note">구조 분석 탭에서 run을 먼저 선택하세요</p>
    </section>;
  }
  // One render can precede the run_changed dispatch; never show the previous run's lists meanwhile.
  const current = state.runId === runId;
  const lists = current ? state.lists : { reports: { status: "idle" as const }, figures: { status: "idle" as const }, summaries: { status: "idle" as const } };
  const selection = current ? state.selection : null;
  const content: ContentState = current ? state.content : { status: "idle" };

  return <section className="mw-library" aria-label="보고서 보관함">
    <div className="mw-library-toolbar">
      <span className="mw-library-run">run <code>{runId}</code></span>
      <Button size="sm" onClick={loadAll}>새로 고침</Button>
    </div>
    <div className="mw-library-lists">
      <section className="mw-library-list" role="region" aria-label={LIST_LABELS.reports}>
        <h3 className="mw-library-title">{LIST_LABELS.reports}</h3>
        <ListBody state={lists.reports} onRetry={() => loadList("reports")} render={rows => rows.map(row => {
          const item: LibraryItem = { kind: "report", handle: row.handle };
          return <li key={row.handle}><button type="button" className="mw-library-row" aria-pressed={sameItem(selection, item)}
            onClick={() => select(item)}>
            <span className="mw-library-kind">{reportKindLabel(row)}</span>
            <span className="mw-library-field">보고서 <code>{row.handle}</code></span>
            <span className="mw-library-field">대상 <code>{row.target_handle ?? "없음"}</code></span>
            <span className="mw-library-field">생성 순번 {row.created_seq}</span>
          </button></li>;
        })} />
      </section>
      <section className="mw-library-list" role="region" aria-label={LIST_LABELS.figures}>
        <h3 className="mw-library-title">{LIST_LABELS.figures}</h3>
        <ListBody state={lists.figures} onRetry={() => loadList("figures")} render={rows => rows.map(row => {
          const item: LibraryItem = { kind: "figure", handle: row.handle };
          return <li key={row.handle}><button type="button" className="mw-library-row" aria-pressed={sameItem(selection, item)}
            onClick={() => select(item)}>
            <span className="mw-library-field">그림 <code>{row.handle}</code></span>
            <span className="mw-library-field">원본 보기 <code>{row.scene_handle}</code></span>
          </button></li>;
        })} />
      </section>
      <section className="mw-library-list" role="region" aria-label={LIST_LABELS.summaries}>
        <h3 className="mw-library-title">{LIST_LABELS.summaries}</h3>
        <ListBody state={lists.summaries} onRetry={() => loadList("summaries")} render={rows => rows.map(row => {
          const item: LibraryItem = { kind: "summary", executionId: row.execution_id, summaryHandle: row.summary_handle };
          return <li key={row.execution_id}><button type="button" className="mw-library-row" aria-pressed={sameItem(selection, item)}
            onClick={() => select(item)}>
            <span className="mw-library-kind">{row.goal ?? "goal 없음"}</span>
            <span className="mw-library-field">실행 <code>{row.execution_id}</code></span>
            <span className="mw-library-field">요약 <code>{row.summary_handle}</code></span>
            <span className="mw-library-field">생성 순번 {row.created_seq ?? "없음"}</span>
          </button></li>;
        })} />
      </section>
    </div>
    <section className="mw-library-content" role="region" aria-label="선택한 항목 내용">
      <ContentView runId={runId} selection={selection} content={content} onRetry={() => { if (selection) select(selection); }} />
    </section>
  </section>;
}

function ContentView({ runId, selection, content, onRetry }: { runId: string; selection: LibraryItem | null;
  content: ContentState; onRetry: () => void }) {
  if (!selection) return <p className="mw-library-note">목록에서 항목을 고르면 내용이 여기에 보입니다.</p>;
  if (content.status === "idle") return null;
  if (content.status === "loading") return <p className="mw-library-note" aria-busy="true">내용을 불러오는 중</p>;
  if (content.status === "error") return <ErrorLine error={content} onRetry={onRetry} />;
  const shown = content.content;
  if (shown.kind === "report") return <>
    <div className="mw-library-links">
      <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, shown.handle, "markdown")} download>Markdown 다운로드</a>
      <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, shown.handle, "json")} download>JSON 다운로드</a>
    </div>
    <pre className="mw-report-preview" aria-label={`저장된 보고서 ${shown.handle}`}>{shown.markdown}</pre>
  </>;
  if (shown.kind === "figure") return <>
    <div className="mw-library-links">
      <a className="mw-btn mw-btn--sm" href={api.figureDownload(runId, shown.handle, "png")} download>PNG</a>
      <a className="mw-btn mw-btn--sm" href={api.figureDownload(runId, shown.handle, "json")} download>출처 JSON</a>
    </div>
    <FigureImage key={shown.handle} src={api.figureDownload(runId, shown.handle, "png")} handle={shown.handle} />
  </>;
  return <>
    <div className="mw-library-links">
      <a className="mw-btn mw-btn--sm" href={api.analysisSummaryDownload(runId, shown.executionId)} download>JSON 다운로드</a>
    </div>
    <pre className="mw-report-preview" aria-label={`분석 흐름 요약 ${shown.executionId}`}>{JSON.stringify(shown.summary, null, 2)}</pre>
  </>;
}

/** The saved PNG is read by the browser; a failed load shows an error and retries by remounting the image. */
function FigureImage({ src, handle }: { src: string; handle: string }) {
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  if (failed) return <ErrorLine error={{ message: "저장된 그림 PNG를 불러오지 못했습니다.", code: null }}
    onRetry={() => { setFailed(false); setAttempt(n => n + 1); }} />;
  return <img key={attempt} className="mw-library-figure" src={src} alt={`저장된 그림 ${handle}`} onError={() => setFailed(true)} />;
}
