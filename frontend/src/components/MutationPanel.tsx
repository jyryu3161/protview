"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type ResidueList, type RunSummary } from "@/lib/api";
import type { ExactResidueRef, MutationCandidatePage, MutationCandidateRow, MutationCandidateSetDetail, MutationCandidateSetList,
  MutationExclusionReason, MutationPosition, MutationPositionPage, MutationPositionSort, MutationPositionStatus,
  MutationReportArtifact, MutationSourceKind, RunEvent, SiteAnnotationListRow } from "@/lib/contracts";
import type { NumberingMapListRow } from "@/lib/numbering";
import type { PocketSetRow, PocketSummary } from "@/lib/pockets";
import { annotationMapConflict, annotationsForStructure, candidateQuery, candidateText, CATALYTIC_NOTE, chainOptions,
  countsText, disulfideText, draftForStructure, EMPTY_CANDIDATE_FILTERS, EMPTY_POSITION_FILTERS, EXCLUSION_REASON_LABEL,
  EXCLUSION_REASONS, exactResidue, exclusionReasonsText, initialMutationDraft, klifsNotice, klifsSitesText,
  LIGAND_SHELL_RADIUS_RANGE_A, ligandDistanceText, ligandOptions, LIST_LIMIT_MAX, LIST_ORDER_NOTE, mapsForStructure,
  METAL_CONTACT_RANGE_A, metalText, MODELING_NOTE, mutationErrorText, mutationPanelState, mutationReasonText,
  mutationReportMatches, mutationReportSavedForRun, mutationRequestArgs, mutationResponseCurrent, nextOffset, NULL_TEXT, numberingText,
  ONE_LETTER_ORDER, ONE_LETTER_RESNAME, PANEL_TITLE, pageRangeText, pocketSetsForStructure, POSITION_SORT_LABEL,
  POSITION_SORTS, POSITION_STATUS_LABEL, POSITION_STATUSES, positionQuery, preparedStructures, previousOffset, protectionCheckRows,
  protectionText, proteinResidueOptions, releaseEffectText, residueKey, residueLabelText, residueText, setRowText,
  SOURCE_KINDS, SOURCE_LABEL, sourcesText, toggleResidue, type CandidateFilters, type MutationDraft, type MutationStamp,
  type PositionFilters } from "@/lib/mutations";
import { Button } from "./primitives";

/**
 * M20 "단백질 공학" tab body: 변이 후보 (spec section 10). Every number shown is a stored backend value read through
 * the M20 read routes; request checks, wording, rounding and currentness come from `lib/mutations.ts`. The page
 * mounts it only while the tab is shown and keys it by run, so entering the tab re-reads every list. Late responses
 * are dropped on two layers: abort on unmount / re-key, and run + result handle + per-area request number.
 */
export interface MutationPanelProps {
  /** Current run of the structure analysis screen (run selection lives only there); null when none. */
  run: RunSummary | null;
  /** undefined while capabilities are being read; null when the backend reports no such method. */
  capability: { available: boolean; reason: string | null } | null | undefined;
  /** After a new result: the page re-reads the run's event log (structure screen timeline). */
  onObjectsChanged: (runId: string) => void;
  /** After a report was created: the page re-reads the knowledge-tab report list (it drops another run's call). */
  onReportCreated: (runId: string) => void;
  /** M21: "변이 구조 모델링" of a candidate row hands that candidate (by its integer index) to the model area. */
  onModelCandidate?: (pick: { runId: string; candidateSet: string; candidate: MutationCandidateRow }) => void;
}

const STATE_TEXT = { loading: "불러오는 중", ready: "준비", scientific_null: "빈 결과 (후보 0개)", failed: "실패",
  unavailable: "사용할 수 없음" } as const;
const TIMEOUT_MS = 30000;

type Load<T> = { status: "idle" } | { status: "loading" } | { status: "ready"; value: T } | { status: "error"; message: string };
type Area = "events" | "pockets" | "maps" | "annotations" | "sets" | "create" | "detail" | "positions" | "excluded" |
  "candidates" | "report";
const AREAS: readonly Area[] = ["events", "pockets", "maps", "annotations", "sets", "create", "detail", "positions",
  "excluded", "candidates", "report"];
const SET_AREAS = new Set<Area>(["detail", "positions", "excluded", "candidates", "report"]);

function errorText(e: unknown): string {
  if (e instanceof ApiError) return mutationErrorText({ message: e.message, code: e.code, detail: e.detail });
  return e instanceof Error ? e.message : String(e);
}
const shortHandle = (handle: string) => handle.split("/").at(-1)?.slice(0, 12) ?? handle;

/** Every page of a run-wide list (the routes return at most `LIST_LIMIT_MAX` rows per page). */
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

function Section({ area, title, state, children }: { area: string; title: string; state?: string; children: ReactNode }) {
  return <section className="mw-mutation-section" data-mutation-area={area} data-state={state} aria-label={title}>
    <h3 className="mw-mutation-title">{title}</h3>
    {children}
  </section>;
}

function ErrorLine({ message, onRetry, testId, reasonCode }: { message: string; onRetry?: () => void; testId?: string;
  reasonCode?: string }) {
  return <div className="mw-mutation-error" role="alert" data-testid={testId} data-reason-code={reasonCode}>
    <span>{message}</span>
    {onRetry && <Button size="sm" onClick={onRetry}>다시 읽기</Button>}
  </div>;
}

export function MutationPanel(p: MutationPanelProps) {
  const runId = p.run?.run_id ?? null;
  if (!p.run || p.capability === undefined || p.capability === null || !p.capability.available) {
    const gate = mutationPanelState({ runId, capability: p.capability });
    return <section className="mw-mutation" aria-label={PANEL_TITLE} data-testid="mutation-panel" data-mutation-state={gate.state}>
      <h2 className="mw-mutation-heading">단백질 공학 · {PANEL_TITLE}</h2>
      <p className="mw-mutation-note" data-testid="mutation-modeling-note">{MODELING_NOTE}</p>
      {gate.state === "unavailable" ? <p className="mw-mutation-unavailable" role="status"
        data-testid={runId === null ? "mutation-no-run" : "mutation-unavailable"}><b>{STATE_TEXT.unavailable}</b>: {gate.reason}</p>
        : <p className="mw-mutation-note" aria-busy="true">기능 상태를 확인하는 중</p>}
    </section>;
  }
  return <MutationWorkspace run={p.run} capability={p.capability} onObjectsChanged={p.onObjectsChanged}
    onReportCreated={p.onReportCreated} onModelCandidate={p.onModelCandidate} />;
}

function MutationWorkspace({ run, capability, onObjectsChanged, onReportCreated, onModelCandidate }: { run: RunSummary;
  capability: { available: boolean; reason: string | null }; onObjectsChanged: (runId: string) => void;
  onReportCreated: (runId: string) => void; onModelCandidate?: MutationPanelProps["onModelCandidate"] }) {
  const runId = run.run_id;
  const [events, setEvents] = useState<Load<RunEvent[]>>({ status: "idle" });
  const [eventsReload, setEventsReload] = useState(0);
  const [pocketSets, setPocketSets] = useState<Load<PocketSetRow[]>>({ status: "idle" });
  const [pocketsReload, setPocketsReload] = useState(0);
  const [maps, setMaps] = useState<Load<NumberingMapListRow[]>>({ status: "idle" });
  const [mapsReload, setMapsReload] = useState(0);
  const [annotations, setAnnotations] = useState<Load<SiteAnnotationListRow[]>>({ status: "idle" });
  const [annotationsReload, setAnnotationsReload] = useState(0);
  const [sets, setSets] = useState<Load<MutationCandidateSetList["rows"]>>({ status: "idle" });
  const [setsReload, setSetsReload] = useState(0);
  // Stored objects never change under a handle, so residue lists and pocket summaries are cached by handle.
  const [residueCache, setResidueCache] = useState<Record<string, Load<ResidueList>>>({});
  const [pocketCache, setPocketCache] = useState<Record<string, Load<PocketSummary>>>({});
  const [draft, setDraft] = useState<MutationDraft>(() => initialMutationDraft(null));
  const [createState, setCreateState] = useState<Load<string> & { reasonCode?: string }>({ status: "idle" });
  const [selectedSet, setSelectedSet] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ handle: string; load: Load<MutationCandidateSetDetail> } | null>(null);
  const [posFilters, setPosFilters] = useState<PositionFilters>(EMPTY_POSITION_FILTERS);
  const [posSort, setPosSort] = useState<MutationPositionSort>("order");
  const [posOffset, setPosOffset] = useState(0);
  const [positions, setPositions] = useState<{ key: string; load: Load<MutationPositionPage> } | null>(null);
  const [positionsRetry, setPositionsRetry] = useState(0);
  const [excludedOffset, setExcludedOffset] = useState(0);
  const [excluded, setExcluded] = useState<{ key: string; load: Load<MutationPositionPage> } | null>(null);
  const [excludedRetry, setExcludedRetry] = useState(0);
  const [candFilters, setCandFilters] = useState<CandidateFilters>(EMPTY_CANDIDATE_FILTERS);
  const [candOffset, setCandOffset] = useState(0);
  const [candidates, setCandidates] = useState<{ key: string; load: Load<MutationCandidatePage> } | null>(null);
  const [candidatesRetry, setCandidatesRetry] = useState(0);
  const [report, setReport] = useState<{ handle: string; load: Load<MutationReportArtifact> } | null>(null);

  // Late responses: keyed by run (page key), opened result handle and the area's request number.
  const mounted = useRef(true);
  const seqs = useRef<Record<Area, number>>(Object.fromEntries(AREAS.map(area => [area, 0])) as Record<Area, number>);
  const live = useRef({ set: selectedSet, run: runId });
  live.current = { set: selectedSet, run: runId };
  useEffect(() => {
    mounted.current = true;
    const counters = seqs.current;
    return () => { mounted.current = false; for (const area of AREAS) counters[area] += 1; };
  }, []);
  const handleOf = (area: Area): string | null => SET_AREAS.has(area) ? live.current.set : null;
  const stamp = (area: Area): MutationStamp => ({ runId, handle: handleOf(area), seq: ++seqs.current[area] });
  const current = (area: Area, captured: MutationStamp) => mounted.current &&
    mutationResponseCurrent(captured, { runId, handle: handleOf(area), seq: seqs.current[area] });

  function listRead<T>(area: Area, setter: (load: Load<T>) => void, read: (signal: AbortSignal) => Promise<T>,
                       failure: string) {
    const captured = stamp(area), controller = new AbortController();
    setter({ status: "loading" });
    read(AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)])).then(value => {
      if (current(area, captured)) setter({ status: "ready", value });
    }).catch(e => { if (current(area, captured)) setter({ status: "error", message: `${failure}: ${errorText(e)}` }); });
    return () => controller.abort();
  }

  // ---- run-wide lists (read on mount, i.e. every time the tab is entered, and on retry) ----
  // stamp/current read live refs; each read is keyed by run and its reload counter.
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => listRead("events", setEvents, signal => api.allEvents(runId, signal), "run 기록 읽기 실패"),
    [runId, eventsReload]);
  useEffect(() => listRead("pockets", setPocketSets, signal => api.allPocketSets(runId, signal).then(list => list.rows),
    "포켓 결과 목록 읽기 실패"), [runId, pocketsReload]);
  useEffect(() => listRead("maps", setMaps, signal => allPages(offset => api.numberingMaps(runId, offset, LIST_LIMIT_MAX,
    signal), "번호 대응"), "번호 대응 목록 읽기 실패"), [runId, mapsReload]);
  useEffect(() => listRead("annotations", setAnnotations, signal => allPages(offset => api.siteAnnotations(runId, null,
    offset, LIST_LIMIT_MAX, signal), "참조 주석"), "참조 주석 목록 읽기 실패"), [runId, annotationsReload]);
  useEffect(() => listRead("sets", setSets, signal => allPages(offset => api.mutationCandidateSets(runId, offset,
    LIST_LIMIT_MAX, signal).then(page => {
    if (page.schema !== "mutation_candidate_set_list@1") throw new Error("변이 후보 결과 목록 형식이 다릅니다.");
    return page;
  }), "변이 후보 결과"), "변이 후보 결과 목록 읽기 실패"), [runId, setsReload]);
  /* eslint-enable react-hooks/exhaustive-deps */

  function ensureResidues(handle: string, retry = false) {
    const cached = residueCache[handle];
    if (cached && (cached.status === "loading" || cached.status === "ready") && !retry) return;
    setResidueCache(previous => ({ ...previous, [handle]: { status: "loading" } }));
    api.residues(runId, handle).then(value => {
      if (mounted.current) setResidueCache(previous => ({ ...previous, [handle]: { status: "ready", value } }));
    }).catch(e => { if (mounted.current) setResidueCache(previous => ({ ...previous,
      [handle]: { status: "error", message: `구조 잔기 목록 읽기 실패: ${errorText(e)}` } })); });
  }

  function ensurePocket(handle: string, retry = false) {
    const cached = pocketCache[handle];
    if (cached && (cached.status === "loading" || cached.status === "ready") && !retry) return;
    setPocketCache(previous => ({ ...previous, [handle]: { status: "loading" } }));
    api.pocketResult(runId, handle, AbortSignal.timeout(TIMEOUT_MS)).then(value => {
      if (value.schema !== "pocket_set_summary@1" || value.handle !== handle) throw new Error("포켓 결과가 고른 handle과 다릅니다.");
      if (mounted.current) setPocketCache(previous => ({ ...previous, [handle]: { status: "ready", value } }));
    }).catch(e => { if (mounted.current) setPocketCache(previous => ({ ...previous,
      [handle]: { status: "error", message: `포켓 결과 읽기 실패: ${errorText(e)}` } })); });
  }

  const structures = events.status === "ready" ? preparedStructures(events.value) : undefined;
  const pocketRows = pocketSets.status === "ready" ? pocketSets.value : [];
  const mapRows = maps.status === "ready" ? maps.value : [];
  const annotationRows = annotations.status === "ready" ? annotations.value : [];
  const listsReady = maps.status === "ready" && annotations.status === "ready" && pocketSets.status === "ready";
  const structureResidues = draft.structure ? residueCache[draft.structure] ?? null : null;
  const residueList = structureResidues?.status === "ready" ? structureResidues.value : null;
  const proteinOptions = residueList ? proteinResidueOptions(residueList) : [];
  const ligandChoices = residueList ? ligandOptions(residueList) : [];
  const offeredPockets = pocketSetsForStructure(pocketRows, draft.structure);
  const offeredMaps = mapsForStructure(mapRows, draft.structure);
  const offeredAnnotations = annotationsForStructure(annotationRows, draft.structure);
  const pocketSummary = draft.pocketSet ? pocketCache[draft.pocketSet] ?? null : null;
  const check = mutationRequestArgs(draft, { pocketSets: pocketRows, maps: mapRows, annotations: annotationRows,
    ligands: ligandChoices });
  const conflict = annotationMapConflict(draft.annotation, draft.numberingMap, annotationRows);
  const notice = draft.structure ? klifsNotice(draft.annotation) : null;

  function chooseStructure(handle: string) {
    setDraft(previous => draftForStructure(previous, handle, annotationRows, mapRows));
    setCreateState({ status: "idle" });
    ensureResidues(handle);
  }

  function chooseAnnotation(handle: string | null) {
    const row = handle === null ? null : annotationRows.find(item => item.handle === handle) ?? null;
    setDraft(previous => ({ ...previous, annotation: handle,
      numberingMap: row && offeredMaps.some(item => item.handle === row.numbering_map) ? row.numbering_map : previous.numberingMap }));
  }

  // ---- opened result: detail, position pages, excluded list, candidate pages ----
  function openSet(handle: string) {
    setSelectedSet(handle); live.current = { set: handle, run: runId };
    setPosFilters(EMPTY_POSITION_FILTERS); setPosSort("order"); setPosOffset(0); setExcludedOffset(0);
    setCandFilters(EMPTY_CANDIDATE_FILTERS); setCandOffset(0);
    setPositions(null); setExcluded(null); setCandidates(null); setReport(null);
    const captured = stamp("detail");
    setDetail({ handle, load: { status: "loading" } });
    api.mutationCandidateSet(runId, handle, AbortSignal.timeout(TIMEOUT_MS)).then(value => {
      if (!current("detail", captured)) return;
      if (value.schema !== "mutation_candidate_set_detail@1" || value.handle !== handle)
        throw new Error("변이 후보 결과가 고른 handle과 다릅니다.");
      setDetail({ handle, load: { status: "ready", value } });
      ensureResidues(value.result.structure.handle);
    }).catch(e => { if (current("detail", captured)) setDetail({ handle, load: { status: "error", message: `변이 후보 결과 읽기 실패: ${errorText(e)}` } }); });
  }

  const opened = detail && detail.handle === selectedSet && detail.load.status === "ready" ? detail.load.value : null;
  const openedHandle = opened ? opened.handle : null;

  function pageRead<T extends { schema: string; handle: string }>(area: Area, key: string, schema: string,
    setter: (value: { key: string; load: Load<T> }) => void, read: (handle: string, signal: AbortSignal) => Promise<T>,
    failure: string) {
    if (!openedHandle) return;
    const handle = openedHandle, captured = stamp(area), controller = new AbortController();
    setter({ key, load: { status: "loading" } });
    read(handle, AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)])).then(value => {
      if (!current(area, captured)) return;
      if (value.schema !== schema || value.handle !== handle) throw new Error(`${failure}: 응답이 고른 결과와 다릅니다.`);
      setter({ key, load: { status: "ready", value } });
    }).catch(e => { if (current(area, captured) && !controller.signal.aborted)
      setter({ key, load: { status: "error", message: `${failure}: ${errorText(e)}` } }); });
    return () => controller.abort();
  }

  const positionsKey = openedHandle ? `${openedHandle}|${positionQuery(posFilters, posSort, posOffset)}` : null;
  const excludedKey = openedHandle ? `${openedHandle}|${positionQuery({ ...EMPTY_POSITION_FILTERS, status: "excluded" }, "order", excludedOffset)}` : null;
  const candidatesKey = openedHandle ? `${openedHandle}|${candidateQuery(candFilters, candOffset)}` : null;
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => positionsKey === null ? undefined : pageRead("positions", positionsKey, "mutation_position_page@1",
    setPositions, (handle, signal) => api.mutationPositions(runId, handle, positionQuery(posFilters, posSort, posOffset), signal),
    "위치 표 읽기 실패"), [positionsKey, positionsRetry]);
  useEffect(() => excludedKey === null ? undefined : pageRead("excluded", excludedKey, "mutation_position_page@1",
    setExcluded, (handle, signal) => api.mutationPositions(runId, handle,
      positionQuery({ ...EMPTY_POSITION_FILTERS, status: "excluded" }, "order", excludedOffset), signal),
    "제외 목록 읽기 실패"), [excludedKey, excludedRetry]);
  useEffect(() => candidatesKey === null ? undefined : pageRead("candidates", candidatesKey, "mutation_candidate_page@1",
    setCandidates, (handle, signal) => api.mutationCandidates(runId, handle, candidateQuery(candFilters, candOffset), signal),
    "후보 표 읽기 실패"), [candidatesKey, candidatesRetry]);
  /* eslint-enable react-hooks/exhaustive-deps */
  const positionsLoad = positions && positions.key === positionsKey ? positions.load : null;
  const excludedLoad = excluded && excluded.key === excludedKey ? excluded.load : null;
  const candidatesLoad = candidates && candidates.key === candidatesKey ? candidates.load : null;

  // ---- actions ----
  async function generate() {
    if (!check.ok || createState.status === "loading") return;
    const args = check.args, captured = stamp("create");
    setCreateState({ status: "loading" });
    try {
      const result = await api.generateMutationCandidates(runId, args, AbortSignal.timeout(120000));
      if (!current("create", captured)) return;
      if (!result.ok) {
        const reasonCode = "detail" in result && typeof result.detail?.reason_code === "string" ? result.detail.reason_code : undefined;
        const message = "message" in result ? mutationErrorText({ message: result.message, code: result.error, detail: result.detail })
          : "approval" in result ? result.approval.reason : result.loop_stop.reason;
        setCreateState({ status: "error", message: `후보 만들기 거절: ${message}`, reasonCode });
        return;
      }
      if (result.handle.kind !== "mutation_candidate_set") throw new Error("도구 결과가 변이 후보 결과가 아닙니다.");
      setCreateState({ status: "ready", value: result.handle.handle });
      onObjectsChanged(runId);
      setSetsReload(value => value + 1);
      openSet(result.handle.handle);
    } catch (e) {
      if (!current("create", captured)) return;
      const reasonCode = e instanceof ApiError && typeof e.detail?.reason_code === "string" ? e.detail.reason_code
        : e instanceof ApiError ? e.code : undefined;
      setCreateState({ status: "error", message: `후보 만들기 거절: ${errorText(e)}`, reasonCode });
    }
  }

  async function makeReport() {
    if (!opened || !selectedSet || report?.load.status === "loading") return;
    const handle = selectedSet, captured = stamp("report");
    setReport({ handle, load: { status: "loading" } });
    try {
      const artifact = await api.createMutationReport(runId, handle, AbortSignal.timeout(60000));
      if (mutationReportSavedForRun(captured, live.current.run)) onReportCreated(runId);
      if (!current("report", captured)) return;
      if (!mutationReportMatches(artifact, handle)) throw new Error("보고서가 고른 변이 후보 결과와 다릅니다.");
      setReport({ handle, load: { status: "ready", value: artifact } });
    } catch (e) { if (current("report", captured)) setReport({ handle, load: { status: "error", message: `보고서 만들기 실패: ${errorText(e)}` } }); }
  }

  // ---- panel state ----
  const readError = (detail?.handle === selectedSet && detail?.load.status === "error" ? detail.load.message : null)
    ?? (positionsLoad?.status === "error" ? positionsLoad.message : null)
    ?? (excludedLoad?.status === "error" ? excludedLoad.message : null)
    ?? (candidatesLoad?.status === "error" ? candidatesLoad.message : null)
    ?? [events, pocketSets, maps, annotations, sets].map(load => load.status === "error" ? load.message : null)
      .find(message => message !== null) ?? null;
  const panelState = mutationPanelState({ runId, capability, structures,
    loading: [events, pocketSets, maps, annotations, sets].some(load => load.status === "loading" || load.status === "idle") ||
      detail?.load.status === "loading",
    error: readError, detail: opened ? { null_result: opened.result.null_result, counts: opened.result.counts } : null });

  const head = <div className="mw-mutation-head">
    <h2 className="mw-mutation-heading">단백질 공학 · {PANEL_TITLE}</h2>
    <span className="mw-badge" data-testid="mutation-state">{STATE_TEXT[panelState.state]}</span>
  </div>;

  if (panelState.state === "unavailable" || structures === undefined) {
    return <section className="mw-mutation" aria-label={PANEL_TITLE} data-testid="mutation-panel" data-mutation-state={panelState.state}>
      {head}
      <p className="mw-mutation-note" data-testid="mutation-modeling-note">{MODELING_NOTE}</p>
      {panelState.state === "unavailable" && <p className="mw-mutation-unavailable" role="status"
        data-testid="mutation-unavailable"><b>{STATE_TEXT.unavailable}</b>: {panelState.reason}</p>}
      {panelState.state === "failed" && <ErrorLine message={panelState.message} testId="mutation-failure"
        onRetry={() => setEventsReload(value => value + 1)} />}
      {panelState.state === "loading" && <p className="mw-mutation-note" aria-busy="true">run 기록을 읽는 중</p>}
    </section>;
  }

  const shellRange = `${LIGAND_SHELL_RADIUS_RANGE_A[0].toFixed(1)}–${LIGAND_SHELL_RADIUS_RANGE_A[1].toFixed(1)} Å`;
  const metalRange = `${METAL_CONTACT_RANGE_A[0].toFixed(1)}–${METAL_CONTACT_RANGE_A[1].toFixed(1)} Å`;
  const patch = (over: Partial<MutationDraft>) => setDraft(previous => ({ ...previous, ...over }));

  return <section className="mw-mutation" aria-label={PANEL_TITLE} data-testid="mutation-panel" data-mutation-state={panelState.state}>
    {head}
    <p className="mw-mutation-note" data-testid="mutation-modeling-note">{MODELING_NOTE}</p>
    {panelState.state === "failed" && <p role="alert" className="mw-mutation-error" data-testid="mutation-failure">{panelState.message}</p>}
    {panelState.state === "scientific_null" && <p role="status" className="mw-mutation-null" data-testid="mutation-null-result">{panelState.message}</p>}

    <Section area="request" title="① 요청">
      <fieldset className="mw-mutation-choices" data-testid="mutation-structures">
        <legend>전처리 구조 (이 run, 자동으로 고르지 않음)</legend>
        {!listsReady && <p className="mw-mutation-note" aria-busy="true">포켓·번호 대응·참조 주석 목록을 읽은 뒤 고를 수 있습니다.</p>}
        {structures.map(row => <label key={row.handle} data-mutation-structure={row.handle}>
          <input type="radio" name={`mutation-structure-${runId}`} checked={draft.structure === row.handle} disabled={!listsReady}
            aria-label={`전처리 구조 ${shortHandle(row.handle)}`} onChange={() => chooseStructure(row.handle)} />
          <span className="mw-mono">prepared_structure · 이벤트 #{row.seq} · {shortHandle(row.handle)}</span>
        </label>)}
      </fieldset>
      {[pocketSets, maps, annotations].map((load, index) => load.status === "error" ? <ErrorLine key={index} message={load.message}
        onRetry={() => [setPocketsReload, setMapsReload, setAnnotationsReload][index](value => value + 1)} /> : null)}

      {draft.structure && <>
        {structureResidues?.status === "loading" && <p className="mw-mutation-note" aria-busy="true">구조 잔기 목록을 읽는 중</p>}
        {structureResidues?.status === "error" && <ErrorLine message={structureResidues.message}
          onRetry={() => draft.structure && ensureResidues(draft.structure, true)} />}

        <div className="mw-mutation-group" aria-label="위치 출처">
          <span className="mw-eyebrow">위치 출처 (켠 출처의 합집합)</span>
          <label className="mw-mutation-check"><input type="checkbox" data-testid="mutation-source-pocket" checked={draft.pocketOn}
            onChange={event => patch({ pocketOn: event.target.checked })} /> {SOURCE_LABEL.pocket}: 저장된 포켓 결과의 안쪽 잔기</label>
          {draft.pocketOn && <div className="mw-mutation-sub" data-testid="mutation-pocket-area">
            {!offeredPockets.length ? <p className="mw-mutation-note" data-testid="mutation-no-pockets">
              이 구조로 검출한 포켓 있는 결과가 없습니다. 구조 분석 탭에서 포켓 검출을 먼저 실행하세요.</p>
              : <fieldset className="mw-mutation-choices" data-testid="mutation-pocket-sets">
                <legend>포켓 결과 (같은 구조, 자동으로 고르지 않음)</legend>
                {offeredPockets.map(row => <label key={row.handle} data-mutation-pocket-set={row.handle}>
                  <input type="radio" name={`mutation-pocket-set-${runId}`} checked={draft.pocketSet === row.handle}
                    onChange={() => { patch({ pocketSet: row.handle, pocketRanks: [] }); ensurePocket(row.handle); }} />
                  <span className="mw-mono">이벤트 #{row.created_seq} · 포켓 {nullableCount(row.total_count)}개 · 체인 {row.selected_chains?.join(", ") ?? NULL_TEXT} · {shortHandle(row.handle)}</span>
                </label>)}
              </fieldset>}
            {pocketSummary?.status === "loading" && <p className="mw-mutation-note" aria-busy="true">포켓 결과를 읽는 중</p>}
            {pocketSummary?.status === "error" && <ErrorLine message={pocketSummary.message}
              onRetry={() => draft.pocketSet && ensurePocket(draft.pocketSet, true)} />}
            {pocketSummary?.status === "ready" && <fieldset className="mw-mutation-choices" data-testid="mutation-pocket-numbers">
              <legend>포켓 번호 (fpocket 출력 번호, 여러 개 고를 수 있음)</legend>
              {pocketSummary.value.pockets.map(pocket => <label key={pocket.rank} data-mutation-pocket={pocket.rank}>
                <input type="checkbox" aria-label={`포켓 ${pocket.rank}`} checked={draft.pocketRanks.includes(pocket.rank)}
                  onChange={event => patch({ pocketRanks: event.target.checked ? [...draft.pocketRanks, pocket.rank]
                    : draft.pocketRanks.filter(item => item !== pocket.rank) })} />
                <span className="mw-mono">포켓 {pocket.rank} · 안쪽 잔기 {pocket.lining_residue_count}개</span>
              </label>)}
            </fieldset>}
          </div>}

          <label className="mw-mutation-check"><input type="checkbox" data-testid="mutation-source-ligand-shell" checked={draft.ligandShellOn}
            onChange={event => patch({ ligandShellOn: event.target.checked })} /> {SOURCE_LABEL.ligand_shell}: 고른 리간드 중원자에서 반경 안의 단백질 잔기</label>
          {draft.ligandShellOn && <label className="mw-mutation-check mw-mutation-sub">반경 (Å, {shellRange})
            <input className="mw-mutation-input" data-testid="mutation-radius" aria-label="리간드 껍질 반경" inputMode="decimal"
              value={draft.radiusText} onChange={event => patch({ radiusText: event.target.value })} /></label>}

          <label className="mw-mutation-check"><input type="checkbox" data-testid="mutation-source-user" checked={draft.userOn}
            onChange={event => patch({ userOn: event.target.checked })} /> {SOURCE_LABEL.user}: 구조 잔기를 직접 고름</label>
          {draft.userOn && <ResiduePicker id="user" label="직접 고른 위치" options={proteinOptions} chosen={draft.residues}
            onChange={residues => patch({ residues })} />}
        </div>

        <div className="mw-mutation-group" aria-label="리간드">
          <label className="mw-mutation-check">리간드 (리간드 껍질에 필요, 고르면 모든 위치에 리간드까지 최소 거리를 계산)
            <select className="mw-select" data-testid="mutation-ligand" aria-label="리간드 선택"
              value={draft.ligand ? String(ligandChoices.findIndex(item => residueKey(item) === residueKey(draft.ligand as ExactResidueRef))) : ""}
              onChange={event => patch({ ligand: event.target.value === "" ? null : exactResidue(ligandChoices[Number(event.target.value)]) })}>
              <option value="">고르지 않음</option>
              {ligandChoices.map((ref, index) => <option key={residueKey(ref)} value={String(index)}>{residueText(ref)} · {residueLabelText(ref)}</option>)}
            </select></label>
          {residueList && !ligandChoices.length && <p className="mw-mutation-note" data-testid="mutation-no-ligands">이 구조에 리간드가 없습니다.</p>}
          {ligandChoices.length > 0 && <p className="mw-mutation-note">리간드는 하나뿐이어도 자동으로 고르지 않습니다.</p>}
        </div>

        <div className="mw-mutation-group" aria-label="허용 잔기">
          <span className="mw-eyebrow">바꿀 수 있는 잔기 (표준 20종, 기본 전부)</span>
          <div className="mw-mutation-allowed" data-testid="mutation-allowed">
            {[...ONE_LETTER_ORDER].map(code => <label key={code} className="mw-mutation-check" data-mutation-allowed={code}>
              <input type="checkbox" aria-label={`허용 잔기 ${code}`} checked={draft.allowed.includes(code)}
                onChange={event => patch({ allowed: event.target.checked ? [...draft.allowed, code] : draft.allowed.filter(item => item !== code) })} />
              <span className="mw-mono">{code} {ONE_LETTER_RESNAME[code]}</span></label>)}
          </div>
          <div className="mw-mutation-inline">
            <Button size="sm" data-testid="mutation-allowed-all" onClick={() => patch({ allowed: [...ONE_LETTER_ORDER] })}>20종 모두 고르기</Button>
            <Button size="sm" data-testid="mutation-allowed-none" onClick={() => patch({ allowed: [] })}>모두 해제</Button>
          </div>
        </div>

        <div className="mw-mutation-group" aria-label="보호와 해제">
          <span className="mw-eyebrow">보호 (기본: 사용자 지정·KLIFS 주요 부위·금속 근접·이황화 Cys 위치는 제외 목록으로)</span>
          <ResiduePicker id="protect" label="보호 목록" options={proteinOptions} chosen={draft.protectedResidues}
            onChange={protectedResidues => patch({ protectedResidues })} />
          <ResiduePicker id="release" label="해제 목록 (그 잔기의 보호 사유 전부를 해제)" options={proteinOptions}
            chosen={draft.releasedResidues} onChange={releasedResidues => patch({ releasedResidues })} />
          <label className="mw-mutation-check">금속 근접 거리 (Å, {metalRange})
            <input className="mw-mutation-input" data-testid="mutation-metal" aria-label="금속 근접 거리" inputMode="decimal"
              value={draft.metalText} onChange={event => patch({ metalText: event.target.value })} /></label>
          <p className="mw-mutation-note">{CATALYTIC_NOTE}</p>
        </div>

        <div className="mw-mutation-group" aria-label="번호 대응과 참조 주석">
          <label className="mw-mutation-check">참조 주석 (같은 구조)
            <select className="mw-select" data-testid="mutation-annotation" aria-label="참조 주석 선택" value={draft.annotation ?? ""}
              onChange={event => chooseAnnotation(event.target.value || null)}>
              <option value="">고르지 않음</option>
              {offeredAnnotations.map(row => <option key={row.handle} value={row.handle}>
                이벤트 #{row.created_seq} · 주석됨 {row.counts.annotated} · 대응 {shortHandle(row.numbering_map)} · {shortHandle(row.handle)}</option>)}
            </select></label>
          <label className="mw-mutation-check">번호 대응 (같은 구조)
            <select className="mw-select" data-testid="mutation-numbering-map" aria-label="번호 대응 선택" value={draft.numberingMap ?? ""}
              onChange={event => patch({ numberingMap: event.target.value || null })}>
              <option value="">고르지 않음</option>
              {offeredMaps.map(row => <option key={row.handle} value={row.handle}>
                {row.structure_kind} · 체인 {row.chains.join(", ")} · 이벤트 #{row.created_seq} · {shortHandle(row.handle)}</option>)}
            </select></label>
          {notice && <p className="mw-mutation-notice" role="status" data-testid="mutation-klifs-notice">{notice}</p>}
          {conflict && <p className="mw-mutation-error" role="alert" data-testid="mutation-map-conflict">{conflict}</p>}
        </div>
      </>}

      <div className="mw-mutation-inline">
        <Button size="sm" variant="primary" data-testid="mutation-create" disabled={!check.ok || createState.status === "loading"}
          title={check.ok ? undefined : check.errors.join(" ")} onClick={() => void generate()}>후보 만들기</Button>
        {createState.status === "loading" && <span className="mw-mutation-note" aria-busy="true">generate_mutation_candidates 실행 중</span>}
      </div>
      {!check.ok && <ul className="mw-mutation-errors" data-testid="mutation-request-errors">
        {check.errors.map(error => <li key={error}>{error}</li>)}</ul>}
      {createState.status === "error" && <ErrorLine message={createState.message} testId="mutation-create-error"
        reasonCode={createState.reasonCode} />}
      {createState.status === "ready" && <p role="status" className="mw-mutation-note" data-testid="mutation-create-done"
        data-mutation-new-set={createState.value}>결과를 저장했습니다 · {shortHandle(createState.value)}</p>}
    </Section>

    <Section area="sets" title="② 저장된 결과" state={sets.status}>
      {sets.status === "loading" && <p className="mw-mutation-note" aria-busy="true">결과 목록을 읽는 중</p>}
      {sets.status === "error" && <ErrorLine message={sets.message} onRetry={() => setSetsReload(value => value + 1)} />}
      {sets.status === "ready" && (!sets.value.length ? <p className="mw-mutation-note" data-testid="mutation-no-sets">이 run에 변이 후보 결과가 없습니다.</p>
        : <fieldset className="mw-mutation-choices" data-testid="mutation-sets">
          <legend>결과 선택 (최신 순, 자동으로 고르지 않음)</legend>
          {sets.value.map(row => <label key={row.handle} data-mutation-set={row.handle} data-valid={row.valid}
            data-null-result={row.null_result ?? undefined} data-klifs-status={row.klifs_status ?? undefined}>
            <input type="radio" name={`mutation-set-${runId}`} checked={selectedSet === row.handle} disabled={!row.valid}
              aria-label={`결과 ${shortHandle(row.handle)}`} onChange={() => openSet(row.handle)} />
            <span className="mw-mono">이벤트 #{row.created_seq} · 구조 {row.structure ? shortHandle(row.structure) : NULL_TEXT} · {setRowText(row)}
              {row.null_result ? " · 후보 0개 (빈 결과)" : ""} · {shortHandle(row.handle)}</span>
          </label>)}
        </fieldset>)}
      {sets.status !== "loading" && <Button size="sm" data-testid="mutation-sets-refresh" onClick={() => setSetsReload(value => value + 1)}>결과 목록 다시 읽기</Button>}
      {detail?.handle === selectedSet && detail.load.status === "loading" && <p className="mw-mutation-note" aria-busy="true">결과를 읽는 중</p>}
      {detail?.handle === selectedSet && detail.load.status === "error" &&
        <ErrorLine message={detail.load.message} onRetry={() => selectedSet && openSet(selectedSet)} />}
    </Section>

    {opened && <Section area="detail" title="③ 상세">
      <SetSummary detail={opened} />

      <div className="mw-mutation-group" aria-label="위치 표" data-testid="mutation-positions-area">
        <span className="mw-eyebrow">위치 표</span>
        <p className="mw-mutation-note">{LIST_ORDER_NOTE}</p>
        <div className="mw-mutation-inline">
          <FilterSelect testId="mutation-filter-status" label="상태" value={posFilters.status}
            options={POSITION_STATUSES.map(value => [value, POSITION_STATUS_LABEL[value]])}
            onChange={value => { setPosFilters(previous => ({ ...previous, status: value as MutationPositionStatus | "" })); setPosOffset(0); }} />
          <FilterSelect testId="mutation-filter-source" label="출처" value={posFilters.source}
            options={SOURCE_KINDS.map(value => [value, SOURCE_LABEL[value]])}
            onChange={value => { setPosFilters(previous => ({ ...previous, source: value as MutationSourceKind | "" })); setPosOffset(0); }} />
          <FilterSelect testId="mutation-filter-reason" label="제외 사유" value={posFilters.exclusion_reason}
            options={EXCLUSION_REASONS.map(value => [value, mutationReasonText(value)])}
            onChange={value => { setPosFilters(previous => ({ ...previous, exclusion_reason: value as MutationExclusionReason | "" })); setPosOffset(0); }} />
          <FilterSelect testId="mutation-filter-chain" label="체인 (auth)" value={posFilters.chain_auth}
            options={chainChoices(residueCache[opened.result.structure.handle]).map(value => [value, value])}
            onChange={value => { setPosFilters(previous => ({ ...previous, chain_auth: value })); setPosOffset(0); }} />
          <label className="mw-mutation-check">정렬
            <select className="mw-select" data-testid="mutation-sort" aria-label="위치 표 정렬" value={posSort}
              onChange={event => { setPosSort(event.target.value as MutationPositionSort); setPosOffset(0); }}>
              {POSITION_SORTS.map(value => <option key={value} value={value}>{POSITION_SORT_LABEL[value]}</option>)}
            </select></label>
        </div>
        {positionsLoad?.status === "loading" && <p className="mw-mutation-note" aria-busy="true">위치 표를 읽는 중</p>}
        {positionsLoad?.status === "error" && <ErrorLine message={positionsLoad.message} testId="mutation-positions-error"
          onRetry={() => setPositionsRetry(value => value + 1)} />}
        {positionsLoad?.status === "ready" && <PositionTable page={positionsLoad.value} ligandGiven={opened.result.ligand !== null}
          onCandidates={index => { setCandFilters(previous => ({ ...previous, position_index: index })); setCandOffset(0); }} />}
        {positionsLoad?.status === "ready" && <Pager testId="mutation-positions" page={positionsLoad.value} onPage={setPosOffset} />}
      </div>

      <div className="mw-mutation-group" aria-label="제외 목록" data-testid="mutation-excluded-area">
        <span className="mw-eyebrow">제외 목록 (제외된 위치와 이유)</span>
        {excludedLoad?.status === "loading" && <p className="mw-mutation-note" aria-busy="true">제외 목록을 읽는 중</p>}
        {excludedLoad?.status === "error" && <ErrorLine message={excludedLoad.message} testId="mutation-excluded-error"
          onRetry={() => setExcludedRetry(value => value + 1)} />}
        {excludedLoad?.status === "ready" && (!excludedLoad.value.total
          ? <p className="mw-mutation-note" data-testid="mutation-excluded-empty">제외된 위치 없음</p>
          : <ul className="mw-mutation-list" data-testid="mutation-excluded">
            {excludedLoad.value.rows.map(row => <li key={row.index} data-mutation-excluded={row.index}
              data-exclusion-reasons={row.exclusion_reasons.join(",")}>
              <span className="mw-mono">{residueText(row.residue)}</span> · {exclusionReasonsText(row.exclusion_reasons)}
              {row.protection.released ? " · 보호 해제됨" : ""}</li>)}
          </ul>)}
        {excludedLoad?.status === "ready" && <Pager testId="mutation-excluded" page={excludedLoad.value} onPage={setExcludedOffset} />}
      </div>

      <div className="mw-mutation-group" aria-label="후보 표" data-testid="mutation-candidates-area">
        <span className="mw-eyebrow">후보 표 (단일 치환)</span>
        <div className="mw-mutation-inline">
          <span className="mw-mutation-note" data-testid="mutation-candidate-position" data-position-index={candFilters.position_index ?? ""}>
            위치: {candFilters.position_index === null ? "전체" : `파일 순서 번호 ${candFilters.position_index}`}</span>
          {candFilters.position_index !== null && <Button size="sm" data-testid="mutation-candidate-position-clear"
            onClick={() => { setCandFilters(previous => ({ ...previous, position_index: null })); setCandOffset(0); }}>전체 위치 보기</Button>}
          <FilterSelect testId="mutation-candidate-to" label="바꿀 잔기" value={candFilters.to}
            options={[...ONE_LETTER_ORDER].map(code => [code, `${code} ${ONE_LETTER_RESNAME[code]}`])}
            onChange={value => { setCandFilters(previous => ({ ...previous, to: value })); setCandOffset(0); }} />
        </div>
        {candidatesLoad?.status === "loading" && <p className="mw-mutation-note" aria-busy="true">후보 표를 읽는 중</p>}
        {candidatesLoad?.status === "error" && <ErrorLine message={candidatesLoad.message} testId="mutation-candidates-error"
          onRetry={() => setCandidatesRetry(value => value + 1)} />}
        {candidatesLoad?.status === "ready" && (!candidatesLoad.value.rows.length
          ? <p className="mw-mutation-note" data-testid="mutation-candidates-empty">{opened.result.null_result
            ? "후보 0개 (빈 결과): 모든 위치가 제외되었거나 위치가 없습니다." : "이 조건에 맞는 후보 없음"}</p>
          : <div className="mw-mutation-table-wrap"><table className="mw-mutation-table" data-testid="mutation-candidates">
            <thead><tr><th>후보 번호 (생성 순서)</th><th>위치 (파일 순서 번호)</th><th>잔기</th><th>치환</th>
              {onModelCandidate && <th>구조 모델</th>}</tr></thead>
            <tbody>{candidatesLoad.value.rows.map(row => <tr key={row.index} data-mutation-candidate={row.index}
              data-position-index={row.position_index} data-from={row.from} data-to={row.to}>
              <td className="mw-mono">{row.index}</td><td className="mw-mono">{row.position_index}</td>
              <td className="mw-mono">{residueText(row.residue)}</td><td className="mw-mono">{candidateText(row)}</td>
              {onModelCandidate && <td><Button size="sm" data-testid="mutation-candidate-model" data-candidate-index={row.index}
                aria-label={`후보 ${row.index} 변이 구조 모델링`}
                onClick={() => onModelCandidate({ runId, candidateSet: opened.handle, candidate: row })}>변이 구조 모델링</Button></td>}
            </tr>)}</tbody></table></div>)}
        {candidatesLoad?.status === "ready" && <Pager testId="mutation-candidates" page={candidatesLoad.value} onPage={setCandOffset} />}
      </div>

      <div className="mw-mutation-group" aria-label="한계" data-testid="mutation-limitations">
        <span className="mw-eyebrow">한계 (고정 문장)</span>
        {opened.result.limitations.map((sentence, index) => <p key={index} className="mw-mutation-note" data-limitation={index}>{sentence}</p>)}
      </div>
    </Section>}

    {opened && <Section area="report" title="④ 보고서">
      <div className="mw-mutation-inline">
        <Button size="sm" data-testid="mutation-report" disabled={report?.handle === selectedSet && report.load.status === "loading"}
          onClick={() => void makeReport()}>보고서 만들기</Button>
      </div>
      {report?.handle === selectedSet && report.load.status === "loading" && <p className="mw-mutation-note" aria-busy="true">보고서를 만드는 중</p>}
      {report?.handle === selectedSet && report.load.status === "ready" && <p role="status" className="mw-mutation-note"
        data-testid="mutation-report-done" data-report-handle={report.load.value.handle}>
        보고서를 저장했습니다 · {shortHandle(report.load.value.handle)}. 지식·보고서 탭의 보고서 목록에서 내용을 보고 내려받을 수 있습니다.</p>}
      {report?.handle === selectedSet && report.load.status === "error" && <ErrorLine message={report.load.message} testId="mutation-report-error" />}
    </Section>}
  </section>;
}

function nullableCount(value: number | null): string { return value === null ? NULL_TEXT : String(value); }

function chainChoices(load: Load<ResidueList> | undefined): string[] {
  return load?.status === "ready" ? chainOptions(proteinResidueOptions(load.value)) : [];
}

function FilterSelect({ testId, label, value, options, onChange }: { testId: string; label: string; value: string;
  options: [string, string][]; onChange: (value: string) => void }) {
  return <label className="mw-mutation-check">{label}
    <select className="mw-select" data-testid={testId} aria-label={label} value={value} onChange={event => onChange(event.target.value)}>
      <option value="">전체</option>
      {options.map(([code, text]) => <option key={code} value={code}>{text}</option>)}
    </select></label>;
}

function Pager({ testId, page, onPage }: { testId: string; page: { total: number; offset: number; limit: number;
  rows: readonly unknown[] }; onPage: (offset: number) => void }) {
  const previous = previousOffset(page.offset, page.limit), next = nextOffset(page);
  return <div className="mw-mutation-inline" data-testid={`${testId}-pager`} data-total={page.total} data-offset={page.offset}>
    <span className="mw-mutation-note">{pageRangeText(page)}</span>
    <Button size="sm" data-testid={`${testId}-prev`} disabled={previous === null} onClick={() => previous !== null && onPage(previous)}>이전</Button>
    <Button size="sm" data-testid={`${testId}-next`} disabled={next === null} onClick={() => next !== null && onPage(next)}>다음</Button>
  </div>;
}

function ResiduePicker({ id, label, options, chosen, onChange }: { id: string; label: string;
  options: readonly ExactResidueRef[]; chosen: readonly ExactResidueRef[]; onChange: (list: ExactResidueRef[]) => void }) {
  const [pick, setPick] = useState("");
  const chosenKeys = new Set(chosen.map(residueKey));
  return <div className="mw-mutation-picker" data-testid={`mutation-picker-${id}`} data-count={chosen.length}>
    <div className="mw-mutation-inline">
      <label className="mw-mutation-check">{label}
        <select className="mw-select" data-testid={`mutation-pick-${id}`} aria-label={`${label}에 넣을 잔기`} value={pick}
          onChange={event => setPick(event.target.value)}>
          <option value="">잔기 고르기</option>
          {options.map((ref, index) => <option key={residueKey(ref)} value={String(index)} disabled={chosenKeys.has(residueKey(ref))}>
            {residueText(ref)} · {residueLabelText(ref)}</option>)}
        </select></label>
      <Button size="sm" data-testid={`mutation-add-${id}`} disabled={pick === ""} onClick={() => {
        const ref = options[Number(pick)];
        if (ref && !chosenKeys.has(residueKey(ref))) onChange(toggleResidue(chosen, ref));
        setPick("");
      }}>넣기</Button>
    </div>
    {!options.length && <p className="mw-mutation-note">구조 잔기 목록을 읽은 뒤 고를 수 있습니다.</p>}
    {chosen.length > 0 && <ul className="mw-mutation-list" data-testid={`mutation-chosen-${id}`}>
      {chosen.map(ref => <li key={residueKey(ref)} data-mutation-residue={residueText(ref)}>
        <span className="mw-mono">{residueText(ref)} · {residueLabelText(ref)}</span>
        <Button size="sm" data-testid={`mutation-remove-${id}`} aria-label={`${label}에서 ${residueText(ref)} 빼기`}
          onClick={() => onChange(toggleResidue(chosen, ref))}>빼기</Button>
      </li>)}
    </ul>}
  </div>;
}

function SetSummary({ detail }: { detail: MutationCandidateSetDetail }) {
  const result = detail.result, counts = result.counts, parameters = result.parameters;
  return <div className="mw-mutation-group" data-testid="mutation-detail" data-mutation-detail={detail.handle}
    data-null-result={result.null_result}>
    <p className="mw-mono">결과 {shortHandle(detail.handle)} · 구조 {shortHandle(result.structure.handle)} (prepared_structure, 모델 {result.structure.model_number}) · {result.method_version}</p>
    <p data-testid="mutation-counts">{countsText(counts)}</p>
    <p className="mw-mutation-note" data-testid="mutation-source-counts">출처별 위치 수: {SOURCE_KINDS.map(kind =>
      `${SOURCE_LABEL[kind]} ${counts.source_counts[kind]}개`).join(" · ")}</p>
    <p className="mw-mutation-note" data-testid="mutation-reason-counts">제외 사유별 위치 수: {EXCLUSION_REASONS.map(reason =>
      `${EXCLUSION_REASON_LABEL[reason]} ${counts.exclusion_reason_counts[reason]}개`).join(" · ")}</p>
    <p className="mw-mutation-note" data-testid="mutation-ligand-summary">리간드: {result.ligand
      ? `${residueText(result.ligand.residue)} · ${residueLabelText(result.ligand.residue)} · 중원자 ${result.ligand.heavy_atom_count}개`
      : `${NULL_TEXT} (고르지 않음, 리간드까지 거리는 계산하지 않음)`}</p>
    <p className="mw-mutation-note">포켓: {result.pockets ? `${shortHandle(result.pockets.pocket_set)} · 포켓 ${result.pockets.ranks.join(", ")} · 안쪽 잔기 ${result.pockets.lining_residue_count}개`
      : `${NULL_TEXT} (포켓 출처를 쓰지 않음)`}
      {" · "}리간드 껍질: {parameters.sources.ligand_shell ? `반경 ${parameters.sources.ligand_shell.radius_A} Å` : `${NULL_TEXT} (쓰지 않음)`}
      {" · "}직접 고른 위치 {parameters.sources.residues.length}개</p>
    <p className="mw-mutation-note mw-mono">허용 잔기 {parameters.allowed_residues} · 금속 근접 {parameters.metal_contact_A} Å · 이황화 SG–SG {parameters.disulfide_sg_A} Å
      · 번호 대응 {parameters.numbering_map ? shortHandle(parameters.numbering_map) : NULL_TEXT} · 참조 주석 {parameters.annotation ? shortHandle(parameters.annotation) : NULL_TEXT}</p>

    <span className="mw-eyebrow">보호 검사 상태</span>
    <div className="mw-mutation-table-wrap"><table className="mw-mutation-table" data-testid="mutation-checks">
      <thead><tr><th>검사</th><th>상태</th><th>내용</th></tr></thead>
      <tbody>{protectionCheckRows(result.protection_checks).map(row => <tr key={row.key} data-mutation-check={row.key}
        data-check-status={result.protection_checks[row.key].status}>
        <td>{row.label}</td><td>{row.status}</td><td>{row.detail}</td></tr>)}</tbody>
    </table></div>
    {result.released_residues.length > 0 && <ul className="mw-mutation-list" data-testid="mutation-released">
      {result.released_residues.map(item => <li key={residueKey(item.residue)} data-release-effect={item.effect}>{releaseEffectText(item)}</li>)}
    </ul>}
  </div>;
}

function PositionTable({ page, ligandGiven, onCandidates }: { page: MutationPositionPage; ligandGiven: boolean;
  onCandidates: (index: number) => void }) {
  if (!page.rows.length) return <p className="mw-mutation-note" data-testid="mutation-positions-empty">이 조건에 맞는 위치 없음</p>;
  return <div className="mw-mutation-table-wrap"><table className="mw-mutation-table" data-testid="mutation-positions">
    <thead><tr><th>파일 순서 번호</th><th>잔기 (auth)</th><th>label</th><th>표준 이름</th><th>출처</th><th>리간드까지 최소 거리</th>
      <th>번호 대응 (참조값)</th><th>보호 사유</th><th>KLIFS 주요 부위</th><th>금속</th><th>이황화 짝</th><th>제외 사유</th><th>상태</th><th>후보 수</th><th /></tr></thead>
    <tbody>{page.rows.map((row: MutationPosition) => <tr key={row.index} data-mutation-position={row.index} data-status={row.status}
      data-exclusion-reasons={row.exclusion_reasons.join(",")} data-residue={residueText(row.residue)}
      data-ligand-distance={row.ligand_min_distance_A ?? ""}>
      <td className="mw-mono">{row.index}</td>
      <td className="mw-mono">{residueText(row.residue)}</td>
      <td className="mw-mono">{residueLabelText(row.residue)}</td>
      <td className="mw-mono">{row.standard_resname ?? NULL_TEXT} / {row.one_letter ?? NULL_TEXT}</td>
      <td>{sourcesText(row.sources)}</td>
      <td className="mw-mono" data-cell="ligand-distance">{ligandDistanceText(row.ligand_min_distance_A, ligandGiven)}</td>
      <td>{numberingText(row.numbering)}</td>
      <td>{protectionText(row.protection)}</td>
      <td>{klifsSitesText(row.protection.klifs_sites)}</td>
      <td className="mw-mono">{metalText(row.protection.metal)}</td>
      <td className="mw-mono">{disulfideText(row.protection.disulfide_partner)}</td>
      <td>{exclusionReasonsText(row.exclusion_reasons)}</td>
      <td>{POSITION_STATUS_LABEL[row.status]}</td>
      <td className="mw-mono">{row.candidate_count}</td>
      <td>{row.status === "candidate" && <Button size="sm" data-testid="mutation-position-candidates" data-position-index={row.index}
        aria-label={`${residueText(row.residue)} 위치의 후보 보기`} onClick={() => onCandidates(row.index)}>후보 보기</Button>}</td>
    </tr>)}</tbody>
  </table></div>;
}
