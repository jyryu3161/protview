"use client";

import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";
import type { KinasePrecedentsCapability, KinasePrecedentsDetail, KinasePrecedentsListItem,
  KinasePrecedentsReportArtifact, PrecedentJsonValue, PrecedentReferenceStatus, PrecedentSortKey, PrecedentSortOrder,
  PrecedentTagAxis } from "@/lib/contracts";
import { ROW_PAGE_LIMIT, type NumberingMapListRow, type NumberingRow } from "@/lib/numbering";
import { AREA_STATE_LABEL, CHAIN_NOTE, chainPreviews, checkPrecedentForm, checkPrecedentQuery, defaultPrecedentQuery,
  EMPTY_LIST_TEXT, emptyFilters, emptyPrecedentForm, filterOptions, FLAGGED_TOGGLE_LABEL, FLAGGED_TOGGLE_NOTE,
  formForMap, isSortKey, LINK_BUTTON_TEXT, LINK_NOTE, listSnapshotBadge, mapChoiceText, MAP_NOTE, newestMap, nextOffset,
  NULL_TEXT, ORDER_LABEL, PAGE_LIMIT_MAX, PANEL_TITLE, PRECEDENT_AREAS, precedentAreaState, precedentCommandOutcome,
  precedentDetailMatches, precedentListItemText, precedentPanelState, precedentRefusal, precedentReportMatches,
  precedentReportSavedForRun, precedentResponseCurrent, precedentResultView, precedentSnapshotView,
  precedentStatusMatches, previousOffset, recordDetailView, reportSnapshotBadge, requestUnavailableReason,
  RESPONSE_SHAPE_TEXT, setIncludeFlagged, setPrecedentChainSelected, snapshotBadgeText, SORT_OPTIONS, SORT_ORDERS,
  TAG_AXES, TAG_AXIS_LABEL, toggleTagTerm, verbatimText, withFilters, withOffset, withSort, withTarget, type ChainPreview,
  type FieldView, type PrecedentAreaStateName, type PrecedentFieldError, type PrecedentFilters, type PrecedentForm,
  type PrecedentFormField, type PrecedentQuery, type PrecedentRefusal, type PrecedentSnapshotBadge,
  type PrecedentStamp, type QuoteView, type RecordDetailView, type TargetView } from "@/lib/kinase-precedents";
import { Button } from "./primitives";

/**
 * M27 "키나아제 전례" area of the 지식·보고서 tab (spec section 8), a separate area below the enzyme reaction knowledge
 * area. Precedents are kbase_kinase records machine-extracted from papers and never reviewed; every value and count shown
 * is a stored backend value read through the M27 read routes, and the request checks, wording, display models and
 * currentness all come from `lib/kinase-precedents.ts` (nothing is computed, sorted, filtered or worded here beyond
 * labels). The page mounts it only while the tab is shown and keys it by run, so entering the tab re-reads the snapshot
 * status, the run's numbering maps and the result list (GET only). The newest numbering map is pre-selected, never
 * submitted; filters, search, the five sort keys and pages are GET queries the server answers. Late answers are applied
 * only while run + opened result handle + the area's request number all match. External strings (quotes, titles) are
 * rendered as text only. There is no viewer display.
 *
 * Test ids (all `kinase-precedents-`): panel, no-run, unavailable, state, failure; snapshot: status-error,
 * snapshot-unavailable, import-command, snapshot-ready, set-hash, imported-at, kbase-commit, dist-commit,
 * dist-commit-date, dirty, kb-version, versions, files, bibliography-snapshot, processed-label, kt1, snapshot-up5,
 * unresolved-names, unresolved-other, bases; request: request-unavailable, maps-error, request-form, numbering-map,
 * chains, chain-<chain_auth>, chain-preview-<chain_auth>, rows-error, include-flagged, flagged-note, link, link-done,
 * field-error, refusal, size-advice; results: results-error, no-results, results, result, results-refresh,
 * snapshot-mark; detail: detail-error, query-error, detail, detail-set, counts, null-result, chain-table, chain-up5,
 * no-target, target-tabs, target-tab ([data-accession]), target, target-status, up2, references, no-references,
 * target-counts, variants, tags, target-bases, up3, filters, filter-file, filter-term ([data-axis][data-term]),
 * filter-variant, search, search-apply, search-error, filters-clear, sort, order, pager, page-text, page-prev, page-next,
 * records, record-row / record-toggle / record-detail ([data-move-id]), check-badge, detail-bibliography,
 * detail-no-bibliography, detail-target, detail-locations, detail-observation, detail-tradeoffs, detail-change,
 * measures, measures-note, detail-structure, up4, detail-interactions, kbase-checks, kp3, integrity, extraction,
 * content-hash, other-fields, kbase-fields (closed `details`, rows `dd[data-kbase-path]`), up1, limitations; report:
 * report, report-done, report-mark, report-markdown, report-json, report-error. Areas:
 * `[data-precedent-area=snapshot|request|results|detail|report]` with `data-state` one of the five.
 */
export interface KinasePrecedentsPanelProps {
  /** Current run of the structure analysis screen (run selection lives only there); null when none. */
  runId: string | null;
  /** `methods.kinase_precedents`: undefined while capabilities are read; null when the backend reports no such method.
   * A missing or invalid snapshot is not the area's "사용할 수 없음": stored results still open from events alone. */
  capability: KinasePrecedentsCapability | null | undefined;
  /** After a report was created: the page re-reads the knowledge-tab report list (it drops another run's call). */
  onReportCreated: (runId: string) => void;
}

type Load<T> = { status: "idle" } | { status: "loading" } | { status: "ready"; value: T } | { status: "error"; message: string };
type Area = (typeof PRECEDENT_AREAS)[number];
type CommandState = { status: "idle" } | { status: "loading" } | { status: "done"; handle: string } |
  { status: "refused"; refusal: PrecedentRefusal };
const RESULT_AREAS = new Set<Area>(["detail", "report"]);
const TIMEOUT_MS = 30000;
const ROWS_TIMEOUT_MS = 60000;
const LINK_TIMEOUT_MS = 120000;
const REPORT_TIMEOUT_MS = 60000;
const STATUS_FAILED_REQUEST_TEXT = "키나아제 전례 참조 스냅샷 상태를 읽지 못해 요청할 수 없습니다. 위 스냅샷 블록에서 다시 읽으세요.";

const shortHandle = (handle: string) => handle.split("/").at(-1)?.slice(0, 12) ?? handle;
const pending = (load: Load<unknown>) => load.status === "idle" || load.status === "loading";

function readErrorText(e: unknown): string {
  if (e instanceof ApiError) return precedentRefusal(e).text;
  return e instanceof Error ? e.message : String(e);
}

/** Every page of a run-wide list (the routes return at most one page of `limit` rows per call). */
async function allPages<T>(read: (offset: number) => Promise<{ total: number; rows: T[] }>, what: string): Promise<T[]> {
  const first = await read(0);
  const rows = [...first.rows];
  while (rows.length < first.total) {
    const page = await read(rows.length);
    if (page.total !== first.total || !page.rows.length) throw new Error(`${what} 목록이 읽는 동안 바뀌었습니다. 다시 읽으세요.`);
    rows.push(...page.rows);
  }
  return rows;
}

/** Every row of one numbering map (as the residue numbering screen reads them), for the chain previews. */
async function allMapRows(runId: string, handle: string, signal: AbortSignal): Promise<NumberingRow[]> {
  const first = await api.numberingRows(runId, handle, 0, ROW_PAGE_LIMIT, signal);
  const rows = [...first.rows];
  while (rows.length < first.total) {
    const page = await api.numberingRows(runId, handle, rows.length, ROW_PAGE_LIMIT, signal);
    if (page.meta.handle !== handle || page.total !== first.total || !page.rows.length)
      throw new Error("번호 대응 행이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
    rows.push(...page.rows);
  }
  return rows;
}

function Section({ area, title, state, children }: { area: string; title: string; state: PrecedentAreaStateName;
  children: ReactNode }) {
  return <section className="mw-precedent-section" data-precedent-area={area} data-state={state} aria-label={title}>
    <h3 className="mw-precedent-title">{title}</h3>
    {children}
  </section>;
}

function ErrorLine({ message, onRetry, testId }: { message: string; onRetry?: () => void; testId?: string }) {
  return <div className="mw-precedent-error" role="alert" data-testid={testId}>
    <span>{message}</span>
    {onRetry && <Button size="sm" onClick={onRetry}>다시 읽기</Button>}
  </div>;
}

function Loading({ text = "불러오는 중" }: { text?: string }) {
  return <p className="mw-precedent-note" aria-busy="true">{text}</p>;
}

function SnapshotMark({ badge, title, testId = "kinase-precedents-snapshot-mark" }: { badge: PrecedentSnapshotBadge;
  title?: string; testId?: string }) {
  const text = snapshotBadgeText(badge);
  return text ? <span className="mw-precedent-badge mw-precedent-badge--stale" data-testid={testId}
    data-stale={badge === "stale" || undefined} data-no-active-set={badge === "no_active_set" || undefined}
    title={title}>{text}</span> : null;
}

export function KinasePrecedentsPanel(p: KinasePrecedentsPanelProps) {
  if (p.runId === null || p.capability === undefined || p.capability === null) {
    const gate = precedentPanelState({ runId: p.runId, capability: p.capability });
    return <section className="mw-precedent" aria-label={PANEL_TITLE} data-testid="kinase-precedents-panel"
      data-precedent-state={gate.state}>
      <h2 className="mw-precedent-heading">{PANEL_TITLE}</h2>
      {gate.state === "unavailable" ? <p className="mw-precedent-unavailable" role="status"
        data-testid={p.runId === null ? "kinase-precedents-no-run" : "kinase-precedents-unavailable"}>
        <b>{AREA_STATE_LABEL.unavailable}</b>: {gate.reason}</p>
        : <p className="mw-precedent-note" aria-busy="true">방법 상태(capabilities)를 읽는 중</p>}
    </section>;
  }
  return <PrecedentWorkspace runId={p.runId} capability={p.capability} onReportCreated={p.onReportCreated} />;
}

function PrecedentWorkspace({ runId, capability, onReportCreated }: { runId: string;
  capability: KinasePrecedentsCapability; onReportCreated: (runId: string) => void }) {
  // ---- run-wide reads (on mount = on entering the tab, and on retry) ----
  const [status, setStatus] = useState<Load<PrecedentReferenceStatus>>({ status: "idle" });
  const [statusReload, setStatusReload] = useState(0);
  const [maps, setMaps] = useState<Load<NumberingMapListRow[]>>({ status: "idle" });
  const [mapsReload, setMapsReload] = useState(0);
  const [results, setResults] = useState<Load<KinasePrecedentsListItem[]>>({ status: "idle" });
  const [resultsReload, setResultsReload] = useState(0);
  // ---- request ----
  const [form, setForm] = useState<PrecedentForm>(emptyPrecedentForm);
  const preselected = useRef(false);
  const [rows, setRows] = useState<{ map: string; load: Load<NumberingRow[]> } | null>(null);
  const [rowsReload, setRowsReload] = useState(0);
  const [command, setCommand] = useState<CommandState>({ status: "idle" });
  // ---- opened result ----
  const [opened, setOpened] = useState<string | null>(null);
  const [query, setQuery] = useState<PrecedentQuery>(() => defaultPrecedentQuery());
  const [searchDraft, setSearchDraft] = useState("");
  const [searchErrors, setSearchErrors] = useState<string[]>([]);
  const [detail, setDetail] = useState<{ key: string; load: Load<KinasePrecedentsDetail> } | null>(null);
  const [detailRetry, setDetailRetry] = useState(0);
  const [expanded, setExpanded] = useState<{ key: string; moveIds: string[] } | null>(null);
  const [report, setReport] = useState<{ handle: string; load: Load<KinasePrecedentsReportArtifact> } | null>(null);

  // Late responses: run (page key) + opened result handle + per-area request number; abort on unmount.
  const mounted = useRef(true);
  const seqs = useRef<Record<Area, number>>(Object.fromEntries(PRECEDENT_AREAS.map(area => [area, 0])) as Record<Area, number>);
  const live = useRef<{ handle: string | null }>({ handle: opened });
  live.current = { handle: opened };
  useEffect(() => {
    mounted.current = true;
    const counters = seqs.current;
    return () => { mounted.current = false; for (const area of PRECEDENT_AREAS) counters[area] += 1; };
  }, []);
  const handleOf = (area: Area): string | null => RESULT_AREAS.has(area) ? live.current.handle : null;
  const stamp = (area: Area): PrecedentStamp => ({ runId, handle: handleOf(area), seq: ++seqs.current[area] });
  const current = (area: Area, captured: PrecedentStamp) => mounted.current &&
    precedentResponseCurrent(captured, { runId, handle: handleOf(area), seq: seqs.current[area] });
  const drop = (area: Area) => { seqs.current[area] += 1; };

  function listRead<T>(area: Area, setter: (load: Load<T>) => void, read: (signal: AbortSignal) => Promise<T>,
                       failure: string) {
    const captured = stamp(area), controller = new AbortController();
    setter({ status: "loading" });
    read(AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)])).then(value => {
      if (current(area, captured)) setter({ status: "ready", value });
    }).catch(e => { if (current(area, captured) && !controller.signal.aborted)
      setter({ status: "error", message: `${failure}: ${readErrorText(e)}` }); });
    return () => controller.abort();
  }

  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => listRead("status", setStatus, signal => api.precedentReferenceStatus(signal).then(value => {
    if (!precedentStatusMatches(value)) throw new Error(RESPONSE_SHAPE_TEXT);
    return value;
  }), "키나아제 전례 참조 스냅샷 상태 읽기 실패"), [statusReload]);
  useEffect(() => listRead("maps", setMaps, signal => allPages(offset => api.numberingMaps(runId, offset, ROW_PAGE_LIMIT,
    signal).then(page => ({ total: page.total, rows: page.rows })), "번호 대응"), "번호 대응 목록 읽기 실패"), [mapsReload]);
  useEffect(() => listRead("list", setResults, signal => allPages(offset => api.kinasePrecedentsResults(runId, offset,
    PAGE_LIMIT_MAX, signal).then(page => ({ total: page.total, rows: page.items })), "키나아제 전례 결과"),
    "키나아제 전례 결과 목록 읽기 실패"), [resultsReload]);
  // The newest map of this run is pre-selected once (a choice the person can change); nothing is submitted.
  useEffect(() => {
    if (maps.status !== "ready" || preselected.current) return;
    preselected.current = true;
    const newest = newestMap(maps.value);
    setForm(previous => previous.numberingMap !== null ? previous : formForMap(newest, previous.includeFlagged));
  }, [maps]);
  // The chosen map's rows (GET only), so the chain previews can name the server's decision before the request.
  useEffect(() => {
    const handle = form.numberingMap;
    if (handle === null) { drop("rows"); setRows(null); return; }
    const captured = stamp("rows"), controller = new AbortController();
    setRows({ map: handle, load: { status: "loading" } });
    allMapRows(runId, handle, AbortSignal.any([controller.signal, AbortSignal.timeout(ROWS_TIMEOUT_MS)])).then(value => {
      if (current("rows", captured)) setRows({ map: handle, load: { status: "ready", value } });
    }).catch(e => { if (current("rows", captured) && !controller.signal.aborted)
      setRows({ map: handle, load: { status: "error", message: `번호 대응 행 읽기 실패: ${readErrorText(e)}` } }); });
    return () => controller.abort();
  }, [form.numberingMap, rowsReload]);
  /* eslint-enable react-hooks/exhaustive-deps */

  const statusValue = status.status === "ready" ? status.value : null;
  const snapshotView = statusValue ? precedentSnapshotView(statusValue) : null;
  const installed = snapshotView === null ? null : snapshotView.state === "ready";
  const mapRows = maps.status === "ready" ? maps.value : [];

  // ---- request: numbering map (pre-selected newest) → chains (default all, previews) → moves_flagged toggle ----
  function chooseMap(handle: string | null) {
    drop("command"); setCommand({ status: "idle" });
    const map = handle === null ? null : mapRows.find(row => row.handle === handle) ?? null;
    setForm(previous => formForMap(map, previous.includeFlagged));
  }

  // A settled refusal belongs to the request it answered: changing chains or the toggle clears it (a call in flight stays).
  const clearRefusal = () => setCommand(previous => previous.status === "refused" ? { status: "idle" } : previous);

  const selectedMap = form.numberingMap === null ? null : mapRows.find(row => row.handle === form.numberingMap) ?? null;
  const rowsLoad = rows && rows.map === form.numberingMap ? rows.load : null;
  const previews = selectedMap === null ? []
    : chainPreviews(selectedMap, rowsLoad?.status === "ready" ? rowsLoad.value : null);
  const check = checkPrecedentForm(form, { snapshot: statusValue, maps: mapRows });
  const fieldErrors = check.ok ? [] : check.errors;
  const errorsFor = (field: PrecedentFormField, chain: string | null = null) =>
    fieldErrors.filter(error => error.field === field && error.chain === chain);
  const refusal = command.status === "refused" ? command.refusal : null;
  const refusedAt = (field: PrecedentRefusal["field"]) => refusal && refusal.field === field ? refusal : null;

  async function link() {
    if (!check.ok || command.status === "loading") return;
    const args = check.args, captured = stamp("command");
    setCommand({ status: "loading" });
    try {
      const outcome = precedentCommandOutcome(await api.linkKinasePrecedents(runId, args, AbortSignal.timeout(LINK_TIMEOUT_MS)));
      if (outcome.ok && mounted.current) setResultsReload(value => value + 1);   // stored even when no longer shown
      if (!current("command", captured)) return;
      if (!outcome.ok) { setCommand({ status: "refused", refusal: outcome.refusal }); return; }
      setCommand({ status: "done", handle: outcome.handle });
      openResult(outcome.handle);
    } catch (e) {
      if (current("command", captured)) setCommand({ status: "refused", refusal: precedentRefusal(e) });
    }
  }

  // ---- opened result: one target's server page (filters, search, sort, page) and the report ----
  function openResult(handle: string) {
    const same = handle === live.current.handle;
    setOpened(handle); live.current = { handle };
    setQuery(defaultPrecedentQuery()); setSearchDraft(""); setSearchErrors([]); setReport(null);
    // The same handle again (the same request returns the stored result): read it again instead of waiting forever.
    if (same) setDetailRetry(value => value + 1); else setDetail(null);
  }

  const queryCheck = checkPrecedentQuery(query);
  const queryString = queryCheck.ok ? queryCheck.query : null;
  const detailKey = opened === null || queryString === null ? null : `${opened}?${queryString}`;
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    if (opened === null || detailKey === null || queryString === null) return;
    const handle = opened, key = detailKey, asked = query, captured = stamp("detail"), controller = new AbortController();
    setDetail({ key, load: { status: "loading" } });
    api.kinasePrecedentsResult(runId, handle, queryString, AbortSignal.any([controller.signal,
      AbortSignal.timeout(TIMEOUT_MS)])).then(value => {
      if (!current("detail", captured)) return;
      if (!precedentDetailMatches(value) || value.handle !== handle || value.page.offset !== asked.offset ||
          value.page.limit !== asked.limit || (asked.target !== null && value.page.target !== asked.target))
        throw new Error(RESPONSE_SHAPE_TEXT);
      setDetail({ key, load: { status: "ready", value } });
    }).catch(e => { if (current("detail", captured) && !controller.signal.aborted)
      setDetail({ key, load: { status: "error", message: `키나아제 전례 결과 읽기 실패: ${readErrorText(e)}` } }); });
    return () => controller.abort();
  }, [detailKey, detailRetry]);
  /* eslint-enable react-hooks/exhaustive-deps */
  const detailLoad = detail && detail.key === detailKey ? detail.load : null;
  const detailValue = detailLoad?.status === "ready" ? detailLoad.value : null;
  const shownExpanded = expanded && expanded.key === detailKey ? expanded.moveIds : [];

  function toggleRecord(moveId: string) {
    if (detailKey === null) return;
    const key = detailKey;
    setExpanded(previous => {
      const ids = previous && previous.key === key ? previous.moveIds : [];
      return { key, moveIds: ids.includes(moveId) ? ids.filter(id => id !== moveId) : [...ids, moveId] };
    });
  }

  function applySearch() {
    const next = withFilters(query, { ...query.filters, q: searchDraft });
    const checked = checkPrecedentQuery(next);
    if (!checked.ok) { setSearchErrors(checked.errors); return; }
    setSearchErrors([]);
    setQuery(next);
  }

  async function makeReport() {
    if (opened === null || detailValue === null || report?.load.status === "loading") return;
    const handle = opened, captured = stamp("report");
    setReport({ handle, load: { status: "loading" } });
    try {
      const artifact = await api.createKinasePrecedentsReport(runId, handle, AbortSignal.timeout(REPORT_TIMEOUT_MS));
      if (precedentReportSavedForRun(captured, runId) && mounted.current) onReportCreated(runId);
      if (!current("report", captured)) return;
      if (!precedentReportMatches(artifact, handle)) throw new Error(RESPONSE_SHAPE_TEXT);
      setReport({ handle, load: { status: "ready", value: artifact } });
    } catch (e) { if (current("report", captured))
      setReport({ handle, load: { status: "error", message: `보고서 만들기 실패: ${readErrorText(e)}` } }); }
  }

  // ---- area states (five each) and the panel state ----
  const reads = [status, maps, results];
  const readError = reads.map(load => load.status === "error" ? load.message : null).find(message => message !== null)
    ?? (detailLoad?.status === "error" ? detailLoad.message : null);
  const panel = precedentPanelState({ runId, capability,
    loading: reads.some(pending) || detailLoad?.status === "loading", error: readError, detail: detailValue });
  const requestReason = status.status === "error" ? STATUS_FAILED_REQUEST_TEXT
    : requestUnavailableReason({ snapshot: statusValue, maps: maps.status === "ready" ? maps.value : undefined })
      ?? (snapshotView?.state === "unavailable" ? `${AREA_STATE_LABEL.unavailable}: ${snapshotView.reasonText}` : null);
  const snapshotState = precedentAreaState({ unavailable: snapshotView?.state === "unavailable",
    failed: status.status === "error", loading: pending(status) });
  const requestState = precedentAreaState({
    unavailable: snapshotView?.state === "unavailable" || (maps.status === "ready" && !maps.value.length),
    failed: status.status === "error" || maps.status === "error", loading: pending(status) || pending(maps) });
  const resultRows = results.status === "ready" ? results.value : [];
  const resultsState = precedentAreaState({ failed: results.status === "error", loading: pending(results),
    empty: results.status === "ready" && !resultRows.length });
  const detailState = precedentAreaState({ failed: detailLoad?.status === "error" || !queryCheck.ok,
    loading: detailLoad === null || pending(detailLoad), empty: detailValue?.null_result === true });
  const reportLoad = report?.handle === opened ? report.load : null;
  const reportState = precedentAreaState({ failed: reportLoad?.status === "error", loading: reportLoad?.status === "loading" });

  return <section className="mw-precedent" aria-label={PANEL_TITLE} data-testid="kinase-precedents-panel"
    data-precedent-state={panel.state}>
    <div className="mw-precedent-head">
      <h2 className="mw-precedent-heading">{PANEL_TITLE}</h2>
      <span className="mw-badge" data-testid="kinase-precedents-state">{AREA_STATE_LABEL[panel.state]}</span>
    </div>
    {panel.state === "failed" && <p role="alert" className="mw-precedent-error" data-testid="kinase-precedents-failure">
      {panel.message}</p>}

    <Section area="snapshot" title="① 전례 참조 스냅샷" state={snapshotState}>
      {pending(status) && <Loading />}
      {status.status === "error" && <ErrorLine message={status.message} testId="kinase-precedents-status-error"
        onRetry={() => setStatusReload(value => value + 1)} />}
      {snapshotView?.state === "unavailable" && <div className="mw-precedent-unavailable"
        data-testid="kinase-precedents-snapshot-unavailable" data-reason-code={snapshotView.reasonCode ?? undefined}>
        <p><b>{AREA_STATE_LABEL.unavailable}</b>: {snapshotView.reasonText}</p>
        <p>{snapshotView.hint}</p>
        <pre className="mw-precedent-command" data-testid="kinase-precedents-import-command">{snapshotView.command}</pre>
      </div>}
      {snapshotView?.state === "ready" && <div className="mw-precedent-snapshot" data-testid="kinase-precedents-snapshot-ready">
        <p className="mw-precedent-notice" data-testid="kinase-precedents-processed-label">{snapshotView.processedLabel}</p>
        <p className="mw-precedent-note" data-testid="kinase-precedents-kt1">{snapshotView.licenseNote}</p>
        <dl className="mw-precedent-facts">
          <dt>세트 해시</dt><dd><code data-testid="kinase-precedents-set-hash" title={snapshotView.setHash}>
            {snapshotView.setHashShort}</code></dd>
          <dt>가져온 날짜</dt><dd data-testid="kinase-precedents-imported-at">{snapshotView.importedAt}</dd>
          <dt>kbase 커밋(HEAD)</dt><dd><code data-testid="kinase-precedents-kbase-commit">{snapshotView.kbaseCommitShort}</code></dd>
          <dt>dist 커밋</dt><dd><code data-testid="kinase-precedents-dist-commit">{snapshotView.distCommitText}</code></dd>
          <dt>dist 커밋 날짜</dt><dd data-testid="kinase-precedents-dist-commit-date">{snapshotView.distCommitDateText}</dd>
          <dt>커밋되지 않은 변경</dt><dd data-testid="kinase-precedents-dirty">{snapshotView.dirtyText}</dd>
          <dt>kb_version</dt><dd className="mw-mono" data-testid="kinase-precedents-kb-version">{snapshotView.kbVersion}</dd>
        </dl>
        <dl className="mw-precedent-facts" data-testid="kinase-precedents-versions">
          {snapshotView.versions.map(item => <div key={item.key} className="mw-precedent-fact" data-version={item.key}>
            <dt>{item.key}</dt><dd className="mw-mono">{item.value}</dd></div>)}
        </dl>
        <div className="mw-precedent-table-wrap"><table className="mw-precedent-table" data-testid="kinase-precedents-files">
          <thead><tr><th>가져온 파일</th><th>행 수</th></tr></thead>
          <tbody>{snapshotView.files.map(file => <tr key={file.name} data-file={file.name}>
            <td className="mw-mono">{file.name}</td><td className="mw-mono">{file.rowsText}</td></tr>)}</tbody>
        </table></div>
        <dl className="mw-precedent-facts" data-testid="kinase-precedents-bibliography-snapshot">
          <dt>서지 스냅샷</dt><dd className="mw-mono">{snapshotView.bibliography.snapshotId}</dd>
          <dt>서지 스냅샷 날짜</dt><dd>{snapshotView.bibliography.date}</dd>
          <dt>서지 라이선스</dt><dd>{snapshotView.bibliography.license}</dd>
          <dt>서지 행 수</dt><dd className="mw-mono">{snapshotView.bibliography.rowsText}</dd>
        </dl>
        <p className="mw-precedent-notice" data-testid="kinase-precedents-snapshot-up5">{snapshotView.summary.unresolvedNote}</p>
        <details className="mw-precedent-details" data-testid="kinase-precedents-unresolved-names">
          <summary>{snapshotView.summary.unresolvedNamesText}</summary>
          <div className="mw-precedent-table-wrap"><table className="mw-precedent-table">
            <thead><tr><th>name_as_written (kbase 기록 그대로)</th><th>파일별 전례 수</th></tr></thead>
            <tbody>{snapshotView.summary.unresolvedNames.map((item, index) => <tr key={index}>
              <td className="mw-precedent-ref">{item.nameText}</td><td>{item.text}</td></tr>)}</tbody>
          </table></div>
          {snapshotView.summary.otherNamesText && <p className="mw-precedent-note" data-testid="kinase-precedents-unresolved-other">
            {snapshotView.summary.otherNamesText}</p>}
        </details>
        <div className="mw-precedent-group" data-testid="kinase-precedents-bases">
          <span className="mw-eyebrow">표적 해석 근거(resolution_basis)별 전례 수 (세트 전체, 표적이 해석된 전례)</span>
          {snapshotView.summary.bases.length ? <ul className="mw-precedent-list">{snapshotView.summary.bases.map(item =>
            <li key={item.basis} data-basis={item.basis}><code>{item.basis}</code> · {item.text}</li>)}</ul>
            : <p className="mw-precedent-note">{EMPTY_LIST_TEXT}</p>}
        </div>
      </div>}
    </Section>

    <Section area="request" title="② 전례 연결 요청" state={requestState}>
      {requestReason !== null ? <p className="mw-precedent-unavailable" role="status"
        data-testid="kinase-precedents-request-unavailable">{requestReason}</p>
        : maps.status !== "ready" ? <>
          {pending(maps) && <Loading text="번호 대응 목록을 읽는 중" />}
          {maps.status === "error" && <ErrorLine message={maps.message} testId="kinase-precedents-maps-error"
            onRetry={() => setMapsReload(value => value + 1)} />}
        </>
        : <RequestForm form={form} maps={mapRows} previews={previews} rowsLoad={rowsLoad} errorsFor={errorsFor}
          refusedAt={refusedAt} refusal={refusal} command={command} canLink={check.ok} onMap={chooseMap}
          onRetryRows={() => setRowsReload(value => value + 1)}
          onChain={(chain, selected) => { clearRefusal(); setForm(previous => setPrecedentChainSelected(previous, chain, selected)); }}
          onFlagged={checked => { clearRefusal(); setForm(previous => setIncludeFlagged(previous, checked)); }}
          onLink={() => void link()} />}
    </Section>

    <Section area="results" title="③ 저장된 결과" state={resultsState}>
      {pending(results) && <Loading text="결과 목록을 읽는 중" />}
      {results.status === "error" && <ErrorLine message={results.message} testId="kinase-precedents-results-error"
        onRetry={() => setResultsReload(value => value + 1)} />}
      {results.status === "ready" && (!resultRows.length
        ? <p className="mw-precedent-note" data-testid="kinase-precedents-no-results">이 run에 키나아제 전례 결과가 없습니다.</p>
        : <fieldset className="mw-precedent-choices" data-testid="kinase-precedents-results">
          <legend>결과 선택 (최신 순, 자동으로 고르지 않음)</legend>
          {resultRows.map(item => {
            const badge = listSnapshotBadge(item, installed);
            return <label key={item.handle} data-precedent-result={item.handle} data-null-result={item.null_result}
              data-include-flagged={item.include_flagged} data-stale={badge === "stale" || undefined}
              data-no-active-set={badge === "no_active_set" || undefined}>
              <input type="radio" name={`kinase-precedents-result-${runId}`} data-testid="kinase-precedents-result"
                data-precedent-result={item.handle} checked={opened === item.handle}
                aria-label={`결과 ${shortHandle(item.handle)}`} onChange={() => openResult(item.handle)} />
              <span className="mw-mono">{precedentListItemText(item)} · {shortHandle(item.handle)}</span>
              <SnapshotMark badge={badge} title={item.set_hash} />
            </label>;
          })}
        </fieldset>)}
      {!pending(results) && <Button size="sm" data-testid="kinase-precedents-results-refresh"
        onClick={() => setResultsReload(value => value + 1)}>전례 결과 목록 다시 읽기</Button>}
    </Section>

    {opened !== null && <Section area="detail" title="④ 결과 상세" state={detailState}>
      {!queryCheck.ok && <ul className="mw-precedent-errors" data-testid="kinase-precedents-query-error">
        {queryCheck.errors.map(text => <li key={text}>{text}</li>)}</ul>}
      {queryCheck.ok && (detailLoad === null || pending(detailLoad)) && <Loading text="결과를 읽는 중" />}
      {detailLoad?.status === "error" && <ErrorLine message={detailLoad.message} testId="kinase-precedents-detail-error"
        onRetry={() => setDetailRetry(value => value + 1)} />}
      {detailValue && <ResultDetail handle={opened} detail={detailValue} query={query} searchDraft={searchDraft}
        searchErrors={searchErrors} expanded={shownExpanded} onToggle={toggleRecord}
        onTarget={accession => { setSearchDraft(""); setSearchErrors([]); setQuery(previous => withTarget(previous, accession)); }}
        onFilters={filters => setQuery(previous => withFilters(previous, filters))}
        onTerm={(axis, term) => setQuery(previous => withFilters(previous, toggleTagTerm(previous.filters, axis, term)))}
        onSearchDraft={setSearchDraft} onSearch={applySearch}
        onClear={() => { setSearchDraft(""); setSearchErrors([]); setQuery(previous => withFilters(previous, emptyFilters())); }}
        onSort={(sort, order) => setQuery(previous => withSort(previous, sort, order))}
        onOffset={offset => setQuery(previous => withOffset(previous, offset))} />}
    </Section>}

    {opened !== null && detailValue && <Section area="report" title="⑤ 보고서" state={reportState}>
      <div className="mw-precedent-inline">
        <Button size="sm" data-testid="kinase-precedents-report" disabled={reportLoad?.status === "loading"}
          onClick={() => void makeReport()}>보고서 만들기</Button>
        {reportLoad?.status === "loading" && <span className="mw-precedent-note" aria-busy="true">보고서를 만드는 중</span>}
      </div>
      <p className="mw-precedent-note">보고서는 저장된 결과로만 만들며(요약과 출처 목록) 연결을 다시 계산하지 않습니다.
        지식·보고서 탭의 보고서 목록에도 보입니다.</p>
      {reportLoad?.status === "ready" && <div className="mw-precedent-inline" role="status"
        data-testid="kinase-precedents-report-done" data-report-handle={reportLoad.value.handle}>
        <span className="mw-precedent-note">보고서를 저장했습니다 · {shortHandle(reportLoad.value.handle)}</span>
        <SnapshotMark badge={reportSnapshotBadge(reportLoad.value.manifest)} testId="kinase-precedents-report-mark"
          title={reportLoad.value.manifest.snapshot.active_set_hash ?? undefined} />
        <a className="mw-btn mw-btn--sm" data-testid="kinase-precedents-report-markdown"
          href={api.reportDownload(runId, reportLoad.value.handle, "markdown")} download>Markdown 내려받기</a>
        <a className="mw-btn mw-btn--sm" data-testid="kinase-precedents-report-json"
          href={api.reportDownload(runId, reportLoad.value.handle, "json")} download>JSON 내려받기</a>
      </div>}
      {reportLoad?.status === "error" && <ErrorLine message={reportLoad.message} testId="kinase-precedents-report-error" />}
    </Section>}
  </section>;
}

function FieldErrors({ errors, refusal }: { errors: readonly PrecedentFieldError[]; refusal: PrecedentRefusal | null }) {
  if (!errors.length && !refusal) return null;
  return <ul className="mw-precedent-errors">
    {errors.map(error => <li key={`${error.field}-${error.chain ?? ""}-${error.text}`} data-testid="kinase-precedents-field-error"
      data-field={error.field} data-chain={error.chain ?? undefined}>{error.text}</li>)}
    {refusal && <li data-testid="kinase-precedents-refusal" data-field={refusal.field} data-chain={refusal.chain ?? undefined}
      data-reason-code={refusal.code ?? undefined}>{refusal.text}</li>}
  </ul>;
}

function RequestForm(p: { form: PrecedentForm; maps: readonly NumberingMapListRow[]; previews: readonly ChainPreview[];
  rowsLoad: Load<NumberingRow[]> | null; errorsFor: (field: PrecedentFormField, chain?: string | null) => PrecedentFieldError[];
  refusedAt: (field: PrecedentRefusal["field"]) => PrecedentRefusal | null; refusal: PrecedentRefusal | null;
  command: CommandState; canLink: boolean; onMap: (handle: string | null) => void; onRetryRows: () => void;
  onChain: (chain: string, selected: boolean) => void; onFlagged: (checked: boolean) => void; onLink: () => void }) {
  const form = p.form;
  const chainRefusal = p.refusedAt("chains");
  const chainNames = new Set(form.chains.map(choice => choice.chain_auth));
  const requestRefusal = p.refusedAt("request") ?? p.refusedAt("result") ?? p.refusedAt("snapshot");
  const advice = p.refusal?.sizeAdvice ?? null;
  return <div className="mw-precedent-form" data-testid="kinase-precedents-request-form">
    <div className="mw-precedent-field" data-precedent-field="numbering_map">
      <label className="mw-precedent-check">번호 대응 결과 (이 run)
        <select className="mw-select" data-testid="kinase-precedents-numbering-map" aria-label="번호 대응 결과 선택"
          value={form.numberingMap ?? ""} onChange={event => p.onMap(event.target.value || null)}>
          <option value="">고르지 않음</option>
          {p.maps.map(row => <option key={row.handle} value={row.handle} title={row.handle}>
            {mapChoiceText(row)} · {shortHandle(row.handle)}</option>)}
        </select></label>
      <p className="mw-precedent-note">{MAP_NOTE}</p>
      <FieldErrors errors={p.errorsFor("numbering_map")} refusal={p.refusedAt("numbering_map")} />
    </div>

    {form.numberingMap !== null && <fieldset className="mw-precedent-choices" data-testid="kinase-precedents-chains"
      data-precedent-field="chains">
      <legend>체인</legend>
      <p className="mw-precedent-note">{CHAIN_NOTE}</p>
      {p.rowsLoad?.status === "loading" && <Loading text="번호 대응 행을 읽는 중" />}
      {p.rowsLoad?.status === "error" && <ErrorLine message={p.rowsLoad.message} testId="kinase-precedents-rows-error"
        onRetry={p.onRetryRows} />}
      {form.chains.map(choice => {
        const preview = p.previews.find(item => item.chainAuth === choice.chain_auth) ?? null;
        return <div key={choice.chain_auth} className="mw-precedent-chain-row" data-precedent-chain={choice.chain_auth}
          data-selected={choice.selected} data-preview-status={preview?.status ?? undefined}
          data-preview-reason={preview?.reason ?? undefined}>
          <label className="mw-precedent-check">
            <input type="checkbox" data-testid={`kinase-precedents-chain-${choice.chain_auth}`} checked={choice.selected}
              onChange={event => p.onChain(choice.chain_auth, event.target.checked)} />
            체인 <code>{choice.chain_auth}</code></label>
          {preview && <span className="mw-precedent-note" data-testid={`kinase-precedents-chain-preview-${choice.chain_auth}`}>
            {preview.text} · {preview.mappedText}</span>}
          <FieldErrors errors={p.errorsFor("chains", choice.chain_auth)}
            refusal={chainRefusal && chainRefusal.chain === choice.chain_auth ? chainRefusal : null} />
        </div>;
      })}
      <FieldErrors errors={p.errorsFor("chains")}
        refusal={chainRefusal && (chainRefusal.chain === null || !chainNames.has(chainRefusal.chain)) ? chainRefusal : null} />
    </fieldset>}

    <div className="mw-precedent-field" data-precedent-field="include_flagged">
      <label className="mw-precedent-check">
        <input type="checkbox" data-testid="kinase-precedents-include-flagged" checked={form.includeFlagged}
          onChange={event => p.onFlagged(event.target.checked)} />
        {FLAGGED_TOGGLE_LABEL}</label>
      {form.includeFlagged && <p className="mw-precedent-notice" data-testid="kinase-precedents-flagged-note">
        {FLAGGED_TOGGLE_NOTE}</p>}
      <FieldErrors errors={p.errorsFor("include_flagged")} refusal={p.refusedAt("include_flagged")} />
    </div>

    <p className="mw-precedent-note">{LINK_NOTE}</p>
    <div className="mw-precedent-inline">
      <Button size="sm" variant="primary" data-testid="kinase-precedents-link"
        disabled={!p.canLink || p.command.status === "loading"} onClick={p.onLink}>{LINK_BUTTON_TEXT}</Button>
      {p.command.status === "loading" && <span className="mw-precedent-note" aria-busy="true">link_kinase_precedents 실행 중</span>}
    </div>
    <FieldErrors errors={p.errorsFor("snapshot")} refusal={requestRefusal} />
    {advice && <ul className="mw-precedent-list" data-testid="kinase-precedents-size-advice">
      {advice.withoutFlagged && <li data-advice="without_flagged" data-fits={advice.withoutFlagged.fits}>
        {advice.withoutFlagged.text}</li>}
      {advice.targets.map(item => <li key={item.accession} data-advice="target" data-accession={item.accession}
        data-fits={item.fits}>{item.text}</li>)}
    </ul>}
    {p.command.status === "done" && <p role="status" className="mw-precedent-note" data-testid="kinase-precedents-link-done"
      data-precedent-new-result={p.command.handle}>결과를 저장했습니다 · {shortHandle(p.command.handle)}</p>}
  </div>;
}

interface DetailActions {
  onToggle: (moveId: string) => void; onTarget: (accession: string) => void;
  onFilters: (filters: PrecedentFilters) => void; onTerm: (axis: PrecedentTagAxis, term: string) => void;
  onSearchDraft: (value: string) => void; onSearch: () => void; onClear: () => void;
  onSort: (sort: PrecedentSortKey, order: PrecedentSortOrder) => void; onOffset: (offset: number) => void;
}

function ResultDetail(p: { handle: string; detail: KinasePrecedentsDetail; query: PrecedentQuery; searchDraft: string;
  searchErrors: readonly string[]; expanded: readonly string[] } & DetailActions) {
  const detail = p.detail;
  const view = precedentResultView(detail);
  const target = view.targets.find(item => item.accession === view.selectedTarget) ?? null;
  return <div className="mw-precedent-detail" data-testid="kinase-precedents-detail" data-precedent-detail={p.handle}
    data-null-result={detail.null_result} data-include-flagged={detail.include_flagged}>
    <p className="mw-mono">결과 {shortHandle(p.handle)} · 구조 {view.structureText}</p>
    <dl className="mw-precedent-facts" data-testid="kinase-precedents-detail-set">
      <dt>번호 대응</dt><dd className="mw-mono">{view.numberingMapText}</dd>
      <dt>PDB ID</dt><dd>{view.pdbIdText}</dd>
      <dt>{FLAGGED_TOGGLE_LABEL}</dt><dd>{view.includeFlaggedText}</dd>
      <dt>사본 형식</dt><dd className="mw-mono">{view.recordFormatText}</dd>
      <dt>스냅샷 세트</dt><dd><code title={detail.precedent_set.set_hash}>{view.setHashShort}</code> · {view.importedAt}{" "}
        <SnapshotMark badge={view.badge} title={detail.active_set.set_hash ?? undefined} /></dd>
      <dt>kb_version</dt><dd className="mw-mono">{view.kbVersion}</dd>
    </dl>
    <p className="mw-precedent-notice">{view.processedLabel}</p>
    <p className="mw-precedent-note">{view.licenseNote}</p>
    <span className="mw-eyebrow">개수 (ProtView가 센 계산값)</span>
    <dl className="mw-precedent-facts" data-testid="kinase-precedents-counts">
      {view.countRows.map(row => <div key={row.key} className="mw-precedent-fact" data-precedent-count={row.key}>
        <dt>{row.label}</dt><dd>{row.text}</dd></div>)}
    </dl>
    {view.nullResultText && <p role="status" className="mw-precedent-null" data-testid="kinase-precedents-null-result">
      {view.nullResultText}</p>}

    <div className="mw-precedent-group">
      <span className="mw-eyebrow">체인 (번호 대응의 순서)</span>
      <div className="mw-precedent-table-wrap"><table className="mw-precedent-table" data-testid="kinase-precedents-chain-table">
        <thead><tr><th>체인</th><th>상태</th><th>이유</th><th>accession</th><th>mapped 잔기의 accession</th>
          <th>잔기 수</th><th>교차 확인</th></tr></thead>
        <tbody>{view.chains.map(chain => <tr key={chain.chainAuth} data-chain={chain.chainAuth} data-chain-status={chain.status}>
          <td><code>{chain.chainAuth}</code></td><td>{chain.statusText}</td><td>{chain.reasonText}</td>
          <td className="mw-mono">{chain.accessionText}</td><td className="mw-mono">{chain.accessionsText}</td>
          <td className="mw-mono">{chain.residuesText}</td><td>{chain.crossCheckText}</td></tr>)}</tbody>
      </table></div>
      <p className="mw-precedent-note" data-testid="kinase-precedents-chain-up5">{view.unresolvedNote}</p>
    </div>

    {view.noTargetText ? <p className="mw-precedent-note" data-testid="kinase-precedents-no-target">{view.noTargetText}</p> : <>
      <div className="mw-precedent-tabs" role="tablist" aria-label="표적(accession)" data-testid="kinase-precedents-target-tabs">
        {view.targets.map(item => <button key={item.accession} type="button" role="tab"
          aria-selected={item.accession === view.selectedTarget} data-testid="kinase-precedents-target-tab"
          data-accession={item.accession} data-target-status={item.status}
          onClick={() => { if (item.accession !== view.selectedTarget) p.onTarget(item.accession); }}>
          <code>{item.accession}</code> · {item.chainsText}</button>)}
      </div>
      {target && <TargetBlock target={target} />}
      <RecordsArea detail={detail} view={view} query={p.query} searchDraft={p.searchDraft} searchErrors={p.searchErrors}
        expanded={p.expanded} actions={p} />
    </>}

    <div className="mw-precedent-group" data-testid="kinase-precedents-limitations">
      <span className="mw-eyebrow">한계 (고정 문장, 저장된 그대로)</span>
      {view.limitations.map((sentence, index) => <p key={index} className="mw-precedent-note" data-limitation={index}>{sentence}</p>)}
    </div>
  </div>;
}

function TargetBlock({ target }: { target: TargetView }) {
  return <div className="mw-precedent-target" data-testid="kinase-precedents-target" data-accession={target.accession}
    data-target-status={target.status}>
    <p className="mw-mono"><code>{target.accession}</code> · {target.chainsText}</p>
    <p className="mw-precedent-status" data-testid="kinase-precedents-target-status">{target.statusText}</p>
    {target.excludedNote && <p className="mw-precedent-notice" data-testid="kinase-precedents-up2">{target.excludedNote}</p>}
    <div className="mw-precedent-group">
      <span className="mw-eyebrow">kbase 참조 (kbase 가공본 값, 계산 아님)</span>
      {target.referencesText ? <p className="mw-precedent-note" data-testid="kinase-precedents-no-references">
        {target.referencesText}</p>
        : <div className="mw-precedent-table-wrap"><table className="mw-precedent-table" data-testid="kinase-precedents-references">
          <thead><tr><th>ref_id</th><th>gene</th><th>klifs_name</th><th>group</th><th>family</th><th>coverage</th></tr></thead>
          <tbody>{target.references.map(ref => <tr key={ref.refId} data-ref-id={ref.refId}>
            <td className="mw-mono">{ref.refId}</td><td>{ref.gene}</td><td>{ref.klifsName}</td><td>{ref.group}</td>
            <td>{ref.family}</td><td>{ref.coverage}</td></tr>)}</tbody>
        </table></div>}
    </div>
    <div className="mw-precedent-group" data-testid="kinase-precedents-target-counts">
      <span className="mw-eyebrow">포함한 전례 개수 (ProtView가 센 계산값)</span>
      <p>{target.movesText} · {target.movesFlaggedText}</p>
      <div data-testid="kinase-precedents-variants">
        <span className="mw-precedent-axis">변이 표기(variant)별</span>{" "}
        {target.variantsText ?? target.variants.map(item => item.text).join(" · ")}
      </div>
      <div data-testid="kinase-precedents-tags">
        {target.tags.map(tag => <div key={tag.axis} data-tag-axis={tag.axis}>
          <span className="mw-precedent-axis">{tag.label}별</span> {tag.text ?? tag.items.map(item => item.text).join(" · ")}</div>)}
      </div>
      <div data-testid="kinase-precedents-target-bases">
        <span className="mw-precedent-axis">표적 해석 근거별</span>{" "}
        {target.basesText ?? target.bases.map(item => item.text).join(" · ")}
      </div>
      <p className="mw-precedent-note" data-testid="kinase-precedents-up3">{target.variantNote}</p>
    </div>
  </div>;
}

function RecordsArea({ detail, view, query, searchDraft, searchErrors, expanded, actions }: { detail: KinasePrecedentsDetail;
  view: ReturnType<typeof precedentResultView>; query: PrecedentQuery; searchDraft: string; searchErrors: readonly string[];
  expanded: readonly string[]; actions: DetailActions }) {
  const options = filterOptions(detail.facets);
  const prev = previousOffset(detail.page), next = nextOffset(detail.page);
  const filters = query.filters;
  return <div className="mw-precedent-group" data-precedent-section="records">
    <span className="mw-eyebrow">전례 목록 (선택한 표적, 서버가 거르고 정렬한 한 쪽)</span>
    {options && <div className="mw-precedent-filters" data-testid="kinase-precedents-filters">
      <label className="mw-precedent-check">파일
        <select className="mw-select" data-testid="kinase-precedents-filter-file" aria-label="파일 필터"
          value={filters.file ?? ""} onChange={event => actions.onFilters({ ...filters, file: event.target.value || null })}>
          <option value="">모든 파일</option>
          {options.file.map(option => <option key={option.value} value={option.value}>{option.text}</option>)}
        </select></label>
      {TAG_AXES.map(axis => <fieldset key={axis} className="mw-precedent-choices" data-filter-axis={axis}>
        <legend>{TAG_AXIS_LABEL[axis]} 태그 (같은 축 안은 하나라도 일치)</legend>
        {options[axis].length ? options[axis].map(option => <label key={option.value} className="mw-precedent-check">
          <input type="checkbox" data-testid="kinase-precedents-filter-term" data-axis={axis} data-term={option.value}
            checked={filters[axis].includes(option.value)} onChange={() => actions.onTerm(axis, option.value)} />
          <span className="mw-mono">{option.text}</span></label>)
          : <span className="mw-precedent-note">{EMPTY_LIST_TEXT}</span>}
      </fieldset>)}
      <label className="mw-precedent-check">변이 표기
        <select className="mw-select" data-testid="kinase-precedents-filter-variant" aria-label="변이 표기 필터"
          value={filters.variant ?? ""} onChange={event => actions.onFilters({ ...filters, variant: event.target.value || null })}>
          <option value="">모든 변이 표기</option>
          {options.variant.map(option => <option key={option.value} value={option.value}>{option.text}</option>)}
        </select></label>
      <div className="mw-precedent-inline">
        <input className="mw-precedent-input" data-testid="kinase-precedents-search" aria-label="글자 검색"
          value={searchDraft} placeholder="move_id·PMID·이름·변이·관찰·변형·교환·서지 제목"
          onChange={event => actions.onSearchDraft(event.target.value)}
          onKeyDown={event => { if (event.key === "Enter") actions.onSearch(); }} />
        <Button size="sm" data-testid="kinase-precedents-search-apply" onClick={actions.onSearch}>검색</Button>
        <Button size="sm" data-testid="kinase-precedents-filters-clear" onClick={actions.onClear}>필터·검색 지우기</Button>
      </div>
      {searchErrors.length > 0 && <ul className="mw-precedent-errors">{searchErrors.map(text =>
        <li key={text} data-testid="kinase-precedents-search-error">{text}</li>)}</ul>}
      <p className="mw-precedent-note">적용한 글자 검색: {filters.q.trim() || NULL_TEXT}. 필터·검색·정렬·쪽 나눔은 서버가 저장된
        결과에서 합니다(같은 축 안은 하나라도 일치, 축 사이는 모두 일치).</p>
    </div>}
    <div className="mw-precedent-inline">
      <label className="mw-precedent-check">열 정렬
        <select className="mw-select" data-testid="kinase-precedents-sort" aria-label="정렬 기준" value={query.sort}
          onChange={event => { if (isSortKey(event.target.value)) actions.onSort(event.target.value, query.order); }}>
          {SORT_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select></label>
      <label className="mw-precedent-check">방향
        <select className="mw-select" data-testid="kinase-precedents-order" aria-label="정렬 방향" value={query.order}
          onChange={event => { const order = SORT_ORDERS.find(item => item === event.target.value);
            if (order) actions.onSort(query.sort, order); }}>
          {SORT_ORDERS.map(order => <option key={order} value={order}>{ORDER_LABEL[order]}</option>)}
        </select></label>
    </div>
    <div className="mw-precedent-inline" data-testid="kinase-precedents-pager">
      <span className="mw-precedent-note" data-testid="kinase-precedents-page-text">{view.pageText}</span>
      <Button size="sm" data-testid="kinase-precedents-page-prev" disabled={prev === null}
        onClick={() => { if (prev !== null) actions.onOffset(prev); }}>이전 쪽</Button>
      <Button size="sm" data-testid="kinase-precedents-page-next" disabled={next === null}
        onClick={() => { if (next !== null) actions.onOffset(next); }}>다음 쪽</Button>
    </div>
    {view.records.length > 0 && <div className="mw-precedent-table-wrap mw-precedent-table-wrap--records">
      <table className="mw-precedent-table" data-testid="kinase-precedents-records">
        <thead><tr><th>move_id</th><th>파일</th><th>변이 표기</th><th>태그 (site / goal / tactic)</th><th>표적 해석 근거</th>
          <th>PMID · 서지</th><th>논문 위치</th><th>kbase 기계 검사</th><th>상세</th></tr></thead>
        <tbody>{view.records.map((row, index) => {
          const open = expanded.includes(row.moveId);
          const item = detail.records[index];
          return <Fragment key={row.moveId}>
            <tr data-testid="kinase-precedents-record-row" data-move-id={row.moveId} data-file={row.file}>
              <td className="mw-mono">{row.moveId}</td>
              <td className="mw-mono">{row.fileText}</td>
              <td className="mw-mono mw-precedent-ref">{row.variant}</td>
              <td>{row.tags.map(tag => <div key={tag.axis} data-tag-axis={tag.axis}>
                <span className="mw-precedent-axis">{TAG_AXIS_LABEL[tag.axis]}</span> <span className="mw-mono">{tag.text}</span></div>)}</td>
              <td className="mw-mono">{row.resolutionBasis}</td>
              <td className="mw-precedent-ref">{row.bibliographyText}</td>
              <td>{row.locationsText}</td>
              <td><span className="mw-precedent-badge" data-testid="kinase-precedents-check-badge"
                data-fail-names={row.checks.failNames.join(" ")}
                data-lookup-failed-names={row.checks.lookupFailedNames.join(" ")}>{row.checks.text}</span></td>
              <td><Button size="sm" data-testid="kinase-precedents-record-toggle" data-move-id={row.moveId} aria-expanded={open}
                onClick={() => actions.onToggle(row.moveId)}>{open ? "상세 접기" : "상세 펼치기"}</Button></td>
            </tr>
            {open && item && <tr className="mw-precedent-detail-row"><td colSpan={9}>
              <RecordDetail view={recordDetailView(item, detail.bibliography)} change={item.record.change} />
            </td></tr>}
          </Fragment>;
        })}</tbody>
      </table>
    </div>}
  </div>;
}

/** A kbase string as written: React text only (never parsed as HTML), whitespace kept. */
function Verbatim({ text }: { text: string }) {
  return <span className="mw-precedent-ref">{text}</span>;
}

function Fields({ fields, empty, testId }: { fields: readonly FieldView[]; empty?: string; testId?: string }) {
  if (!fields.length) return <p className="mw-precedent-note" data-testid={testId}>{empty ?? NULL_TEXT}</p>;
  return <dl className="mw-precedent-fields" data-testid={testId}>
    {fields.map(field => <Fragment key={field.key}><dt>{field.key}</dt><dd><Verbatim text={field.text} /></dd></Fragment>)}
  </dl>;
}

function QuoteBlock({ quote, kind }: { quote: QuoteView; kind: string }) {
  return <div className="mw-precedent-quote" data-quote={kind}>
    <dl className="mw-precedent-fields">
      <dt>text</dt><dd><Verbatim text={quote.text} /></dd>
      <dt>quote</dt><dd><Verbatim text={quote.quote} /></dd>
      <dt>인용 단어 수</dt><dd>{quote.wordsText}</dd>
      <dt>quote_truncated</dt><dd data-quote-flag="truncated">{quote.truncatedText}</dd>
      {quote.assembledText && <><dt>quote_assembled</dt><dd data-quote-flag="assembled">{quote.assembledText}</dd></>}
    </dl>
  </div>;
}

function RecordDetail({ view, change }: { view: RecordDetailView; change: PrecedentJsonValue }) {
  return <div className="mw-precedent-record" data-testid="kinase-precedents-record-detail" data-move-id={view.moveId}>
    <p className="mw-mono">{view.moveId} · {view.fileText}</p>
    <p className="mw-precedent-notice" data-testid="kinase-precedents-up1">{view.sourceNote}</p>

    <div className="mw-precedent-group">
      <span className="mw-eyebrow">서지 (서지 스냅샷 행 그대로)</span>
      {view.bibliography ? <Fields fields={view.bibliography} testId="kinase-precedents-detail-bibliography" />
        : <p className="mw-precedent-note" data-testid="kinase-precedents-detail-no-bibliography">{view.bibliographyText}</p>}
    </div>
    <div className="mw-precedent-group">
      <span className="mw-eyebrow">표적 (kbase 기록 그대로)</span>
      <Fields fields={view.target} testId="kinase-precedents-detail-target" />
    </div>
    <div className="mw-precedent-group" data-testid="kinase-precedents-detail-locations">
      <span className="mw-eyebrow">논문 위치 (전부)</span>
      {view.locations.map((fields, index) => <Fields key={index} fields={fields} />)}
    </div>
    <div className="mw-precedent-group" data-testid="kinase-precedents-detail-observation">
      <span className="mw-eyebrow">관찰 문장·인용문 (observation)</span>
      <QuoteBlock quote={view.observation} kind="observation" />
    </div>
    <div className="mw-precedent-group" data-testid="kinase-precedents-detail-tradeoffs">
      <span className="mw-eyebrow">교환 문장·인용문 (tradeoffs)</span>
      {view.tradeoffsText ? <p className="mw-precedent-note">{view.tradeoffsText}</p>
        : view.tradeoffs.map((quote, index) => <QuoteBlock key={index} quote={quote} kind={`tradeoff-${index}`} />)}
    </div>
    <div className="mw-precedent-group">
      <span className="mw-eyebrow">변형 설명 (change)</span>
      <Fields fields={view.change} empty={verbatimText(change)} testId="kinase-precedents-detail-change" />
    </div>
    <div className="mw-precedent-group">
      <span className="mw-eyebrow">{view.effectsHeader}</span>
      <p className="mw-precedent-note" data-testid="kinase-precedents-measures-note">{view.effectsNote}</p>
      <div className="mw-precedent-table-wrap"><table className="mw-precedent-table" data-testid="kinase-precedents-measures">
        <thead><tr><th>metric</th><th>assay</th><th>before</th><th>after</th><th>target_ref</th><th>target_role</th>
          <th>direction</th><th>direction_basis</th><th>magnitude_bucket</th><th>comparable</th><th>comparability_reason</th>
          <th>fold_change</th></tr></thead>
        <tbody>{view.effects.map((row, index) => <tr key={index} data-target-role={row.targetRole}
          data-direction-basis={row.directionBasis}>
          <td><Verbatim text={row.metric} /></td><td><Verbatim text={row.assay} /></td>
          <td className="mw-mono">{row.beforeText}</td><td className="mw-mono">{row.afterText}</td>
          <td><Verbatim text={row.targetRef} /></td><td className="mw-mono">{row.targetRole}</td>
          <td className="mw-mono">{row.direction}</td><td>{row.basisText}</td>
          <td className="mw-mono">{row.magnitudeBucket}</td><td className="mw-mono">{row.comparableText}</td>
          <td><Verbatim text={row.comparabilityReasonText} /></td>
          <td className="mw-mono" data-cell="fold_change">{row.foldChangeText}</td></tr>)}</tbody>
      </table></div>
    </div>
    <div className="mw-precedent-group" data-testid="kinase-precedents-detail-structure">
      <span className="mw-eyebrow">구조 연결·PDB 언급 (kbase 기록 그대로)</span>
      <Fields fields={view.structure.fields} />
      {view.structure.linksText ? <p className="mw-precedent-note">structure_links {view.structure.linksText}</p>
        : view.structure.links.map((fields, index) => <Fields key={index} fields={fields} />)}
      <p className="mw-precedent-note" data-testid="kinase-precedents-up4">{view.structure.note}</p>
    </div>
    <div className="mw-precedent-group" data-testid="kinase-precedents-detail-interactions">
      <span className="mw-eyebrow">상호작용 기록 (interactions, kbase 기록 그대로)</span>
      {view.interactionsText ? <p className="mw-precedent-note">{view.interactionsText}</p>
        : view.interactions.map((fields, index) => <Fields key={index} fields={fields} />)}
    </div>
    <div className="mw-precedent-group" data-testid="kinase-precedents-kbase-checks">
      <span className="mw-eyebrow">{view.checksHeader}</span>
      <p className="mw-precedent-note" data-testid="kinase-precedents-kp3">{view.checksNote}</p>
      <dl className="mw-precedent-fields">
        {view.checks.map(item => <Fragment key={item.name}><dt>{item.name}</dt>
          <dd className="mw-mono" data-check={item.name}>{item.status}</dd></Fragment>)}
      </dl>
    </div>
    <div className="mw-precedent-group" data-testid="kinase-precedents-integrity">
      <span className="mw-eyebrow">{view.integrityHeader}</span>
      <dl className="mw-precedent-fields">
        {view.integrity.map(field => <Fragment key={field.key}><dt>{field.key}</dt>
          <dd data-integrity={field.key}>{field.text}</dd></Fragment>)}
      </dl>
    </div>
    <div className="mw-precedent-group">
      <span className="mw-eyebrow">추출 정보 (extraction)</span>
      <Fields fields={view.extraction} testId="kinase-precedents-extraction" />
    </div>
    <div className="mw-precedent-group" data-testid="kinase-precedents-content-hash">
      <span className="mw-eyebrow">원본 content_hash</span>
      <code>{view.contentHash}</code>
      <p className="mw-precedent-note">{view.contentHashNote}</p>
      <p className="mw-precedent-note mw-mono">{view.recordFormat}</p>
    </div>
    <div className="mw-precedent-group">
      <span className="mw-eyebrow">그 밖의 필드 (kbase 기록 그대로)</span>
      <Fields fields={view.otherFields} testId="kinase-precedents-other-fields" />
    </div>
    <div className="mw-precedent-group">
      <details className="mw-precedent-details" data-testid="kinase-precedents-kbase-fields">
        <summary>{view.kbaseFieldsHeader}</summary>
        <p className="mw-precedent-note">{view.kbaseFieldsNote}</p>
        {view.kbaseFieldsText ? <p className="mw-precedent-note">{view.kbaseFieldsText}</p>
          : <dl className="mw-precedent-fields">
            {view.kbaseFields.map(field => <Fragment key={field.path}><dt>{field.path}</dt>
              <dd data-kbase-path={field.path}><Verbatim text={field.value} /></dd></Fragment>)}
          </dl>}
      </details>
    </div>
  </div>;
}
