"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type ResidueList } from "@/lib/api";
import type { ReactionKnowledgeCapability, ReactionKnowledgeDetail, ReactionKnowledgeListItem,
  ReactionKnowledgeReportArtifact, ReactionPdbEntries, ReactionReferenceStatus } from "@/lib/contracts";
import type { NumberingMapListRow, PdbIdHint } from "@/lib/numbering";
import { accessionSuggestions, applySuggestions, AREA_STATE_LABEL, checkReactionForm, DEFAULT_DETAIL_PAGING,
  emptyReactionForm, formForStructure, LINK_BUTTON_TEXT, LIST_LIMIT_MAX, listSnapshotBadge, MAP_NOTE, mapPrefill,
  mapsForStructure, nextOffset, normalizedPdbId, NULL_TEXT, PANEL_TITLE, PDB_ID_NOTE, pdbIdSuggestion, pdbLookupMatches,
  pdbLookupText, POSITION_NOTE, previousOffset, REACTION_AREAS, reactionCommandOutcome, reactionDetailMatches,
  reactionDetailQuery, reactionListItemText, reactionPanelState, reactionRefusal, reactionReportMatches,
  reactionReportSavedForRun, reactionResponseCurrent, reactionResultView, reactionSnapshotView, reactionStatusMatches,
  reactionStructures, REFERENCE_COLUMN_LABEL, REFERENCE_NOTE, requestUnavailableReason, RESPONSE_SHAPE_TEXT,
  setChainAccession, setChainSelected, snapshotBadgeText, STRUCTURE_NOTE, SUGGESTION_NOTE, USE_SUGGESTION_TEXT,
  type ChainView, type ReactionDetailPaging, type ReactionFieldError, type ReactionForm, type ReactionFormField,
  type ReactionRefusal, type ReactionSnapshotBadge, type ReactionStamp } from "@/lib/reaction-knowledge";
import { Button } from "./primitives";

/**
 * M26 "효소 반응 지식" area of the 지식·보고서 tab (spec section 10.1), a separate area below the residue numbering
 * screen. Catalytic residues, UniProt sites and reactions are reference values of the pinned snapshot ("참조값, 계산 아님");
 * every value and count shown is a stored backend value read through the M26 read routes, and the request checks,
 * wording and currentness come from `lib/reaction-knowledge.ts`. The page mounts it only while the tab is shown and
 * keys it by run, so entering the tab re-reads the snapshot status, the run's structures and numbering maps and the
 * result list (GET only). Late answers are applied only while run + opened result handle + the area's request number
 * all match. Nothing is chosen, confirmed or submitted by itself; there is no viewer display.
 */
export interface ReactionKnowledgePanelProps {
  /** Current run of the structure analysis screen (run selection lives only there); null when none. */
  runId: string | null;
  /** `methods.reaction_knowledge`: undefined while capabilities are read; null when the backend reports no such method.
   * A missing or invalid snapshot is not the area's "사용할 수 없음": stored results still open from events alone. */
  capability: ReactionKnowledgeCapability | null | undefined;
  /** After a report was created: the page re-reads the knowledge-tab report list (it drops another run's call). */
  onReportCreated: (runId: string) => void;
}

type Load<T> = { status: "idle" } | { status: "loading" } | { status: "ready"; value: T } | { status: "error"; message: string };
type Area = (typeof REACTION_AREAS)[number];
type CommandState = { status: "idle" } | { status: "loading" } | { status: "done"; handle: string } |
  { status: "refused"; refusal: ReactionRefusal };
type StructureOption = ReturnType<typeof reactionStructures>[number];
const RESULT_AREAS = new Set<Area>(["detail", "report"]);
const TIMEOUT_MS = 30000;
const LINK_TIMEOUT_MS = 120000;
const STRUCTURE_KIND_TEXT: Record<string, string> = { prepared_structure: "전처리 구조", structure: "업로드 원본 구조" };
const STATUS_FAILED_REQUEST_TEXT = "반응 참조 스냅샷 상태를 읽지 못해 요청할 수 없습니다. 위 스냅샷 블록에서 다시 읽으세요.";
const LINK_NOTE = "연결하기는 값싼 도구 호출(link_reaction_knowledge)이며 승인이나 비싼 계산 단위를 쓰지 않습니다.";

const shortHandle = (handle: string) => handle.split("/").at(-1)?.slice(0, 12) ?? handle;

function readErrorText(e: unknown): string {
  if (e instanceof ApiError) return reactionRefusal(e).text;
  return e instanceof Error ? e.message : String(e);
}

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
  return <section className="mw-reaction-section" data-reaction-area={area} data-state={state} aria-label={title}>
    <h3 className="mw-reaction-title">{title}</h3>
    {children}
  </section>;
}

function ErrorLine({ message, onRetry, testId }: { message: string; onRetry?: () => void; testId?: string }) {
  return <div className="mw-reaction-error" role="alert" data-testid={testId}>
    <span>{message}</span>
    {onRetry && <Button size="sm" onClick={onRetry}>다시 읽기</Button>}
  </div>;
}

function Loading({ text = "불러오는 중" }: { text?: string }) {
  return <p className="mw-reaction-note" aria-busy="true">{text}</p>;
}

function SnapshotMark({ badge, title }: { badge: ReactionSnapshotBadge; title?: string }) {
  const text = snapshotBadgeText(badge);
  return text ? <span className="mw-reaction-badge mw-reaction-badge--stale" data-testid="reaction-snapshot-mark"
    data-stale={badge === "stale" || undefined} data-no-active-set={badge === "no_active_set" || undefined}
    title={title}>{text}</span> : null;
}

export function ReactionKnowledgePanel(p: ReactionKnowledgePanelProps) {
  if (p.runId === null || p.capability === undefined || p.capability === null) {
    const gate = reactionPanelState({ runId: p.runId, capability: p.capability });
    return <section className="mw-reaction" aria-label={PANEL_TITLE} data-testid="reaction-panel"
      data-reaction-state={gate.state}>
      <h2 className="mw-reaction-heading">{PANEL_TITLE}</h2>
      {gate.state === "unavailable" ? <p className="mw-reaction-unavailable" role="status"
        data-testid={p.runId === null ? "reaction-no-run" : "reaction-unavailable"}>
        <b>{AREA_STATE_LABEL.unavailable}</b>: {gate.reason}</p>
        : <p className="mw-reaction-note" aria-busy="true">방법 상태(capabilities)를 읽는 중</p>}
    </section>;
  }
  return <ReactionWorkspace runId={p.runId} capability={p.capability} onReportCreated={p.onReportCreated} />;
}

function ReactionWorkspace({ runId, capability, onReportCreated }: { runId: string;
  capability: ReactionKnowledgeCapability; onReportCreated: (runId: string) => void }) {
  // ---- run-wide reads (on mount = on entering the tab, and on retry) ----
  const [status, setStatus] = useState<Load<ReactionReferenceStatus>>({ status: "idle" });
  const [statusReload, setStatusReload] = useState(0);
  const [structures, setStructures] = useState<Load<StructureOption[]>>({ status: "idle" });
  const [structuresReload, setStructuresReload] = useState(0);
  const [maps, setMaps] = useState<Load<NumberingMapListRow[]>>({ status: "idle" });
  const [mapsReload, setMapsReload] = useState(0);
  const [results, setResults] = useState<Load<ReactionKnowledgeListItem[]>>({ status: "idle" });
  const [resultsReload, setResultsReload] = useState(0);
  // ---- request ----
  const [form, setForm] = useState<ReactionForm>(emptyReactionForm);
  const [residues, setResidues] = useState<{ structure: string; load: Load<ResidueList> } | null>(null);
  const [hint, setHint] = useState<{ structure: string; load: Load<PdbIdHint> } | null>(null);
  const [lookup, setLookup] = useState<{ pdbId: string; load: Load<ReactionPdbEntries> } | null>(null);
  const [command, setCommand] = useState<CommandState>({ status: "idle" });
  // ---- opened result ----
  const [opened, setOpened] = useState<string | null>(null);
  const [paging, setPaging] = useState<ReactionDetailPaging>(DEFAULT_DETAIL_PAGING);
  const [detail, setDetail] = useState<{ key: string; load: Load<ReactionKnowledgeDetail> } | null>(null);
  const [detailRetry, setDetailRetry] = useState(0);
  const [report, setReport] = useState<{ handle: string; load: Load<ReactionKnowledgeReportArtifact> } | null>(null);

  // Late responses: run (page key) + opened result handle + per-area request number; abort on unmount.
  const mounted = useRef(true);
  const seqs = useRef<Record<Area, number>>(Object.fromEntries(REACTION_AREAS.map(area => [area, 0])) as Record<Area, number>);
  const live = useRef<{ handle: string | null }>({ handle: opened });
  live.current = { handle: opened };
  useEffect(() => {
    mounted.current = true;
    const counters = seqs.current;
    return () => { mounted.current = false; for (const area of REACTION_AREAS) counters[area] += 1; };
  }, []);
  const handleOf = (area: Area): string | null => RESULT_AREAS.has(area) ? live.current.handle : null;
  const stamp = (area: Area): ReactionStamp => ({ runId, handle: handleOf(area), seq: ++seqs.current[area] });
  const current = (area: Area, captured: ReactionStamp) => mounted.current &&
    reactionResponseCurrent(captured, { runId, handle: handleOf(area), seq: seqs.current[area] });
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
  useEffect(() => listRead("status", setStatus, signal => api.reactionReferenceStatus(signal).then(value => {
    if (!reactionStatusMatches(value)) throw new Error(RESPONSE_SHAPE_TEXT);
    return value;
  }), "반응 참조 스냅샷 상태 읽기 실패"), [statusReload]);
  useEffect(() => listRead("structures", setStructures, signal => api.allEvents(runId, signal).then(reactionStructures),
    "run 기록 읽기 실패"), [structuresReload]);
  useEffect(() => listRead("maps", setMaps, signal => allPages(offset => api.numberingMaps(runId, offset, LIST_LIMIT_MAX,
    signal).then(page => ({ total: page.total, rows: page.rows })), "번호 대응"), "번호 대응 목록 읽기 실패"), [mapsReload]);
  useEffect(() => listRead("list", setResults, signal => allPages(offset => api.reactionKnowledgeResults(runId, offset,
    LIST_LIMIT_MAX, signal).then(page => ({ total: page.total, rows: page.items })), "효소 반응 지식 결과"),
    "효소 반응 지식 결과 목록 읽기 실패"), [resultsReload]);
  /* eslint-enable react-hooks/exhaustive-deps */

  const statusValue = status.status === "ready" ? status.value : null;
  const snapshotView = statusValue ? reactionSnapshotView(statusValue) : null;
  const installed = snapshotView === null ? null : snapshotView.state === "ready";
  const structureRows = structures.status === "ready" ? structures.value : undefined;
  const mapRows = maps.status === "ready" ? maps.value : [];
  const listsReady = structures.status === "ready" && maps.status === "ready";

  // ---- request: structure → chains, PDB ID, accession suggestions (applied only to empty fields or on a click) ----
  function chooseStructure(handle: string | null) {
    drop("residues"); drop("hint"); drop("pdb"); drop("command");
    setResidues(null); setHint(null); setLookup(null); setCommand({ status: "idle" });
    setForm(formForStructure(handle, []));
    if (handle === null) return;
    const residuesStamp = stamp("residues");
    setResidues({ structure: handle, load: { status: "loading" } });
    api.residues(runId, handle).then(value => {
      if (current("residues", residuesStamp)) setResidues({ structure: handle, load: { status: "ready", value } });
    }).catch(e => { if (current("residues", residuesStamp))
      setResidues({ structure: handle, load: { status: "error", message: `구조 잔기 목록 읽기 실패: ${readErrorText(e)}` } }); });
    const hintStamp = stamp("hint");
    setHint({ structure: handle, load: { status: "loading" } });
    api.pdbIdHint(runId, handle, AbortSignal.timeout(TIMEOUT_MS)).then(value => {
      if (current("hint", hintStamp)) setHint({ structure: handle, load: { status: "ready", value } });
    }).catch(e => { if (current("hint", hintStamp))
      setHint({ structure: handle, load: { status: "error", message: `PDB ID 제안 읽기 실패: ${readErrorText(e)}` } }); });
  }

  const prefill = form.structure === null ? null
    : mapPrefill(mapRows, form.structure, form.chains.map(choice => choice.chain_auth));
  const fileHint = hint && hint.structure === form.structure && hint.load.status === "ready" ? hint.load.value : null;

  /* eslint-disable react-hooks/exhaustive-deps */
  // Residues of the chosen structure → chain rows (none selected); the newest same-structure map's accessions fill
  // empty accession fields only, and its PDB ID (else the file's) fills an empty, unconfirmed PDB ID only.
  useEffect(() => {
    if (!residues || residues.load.status !== "ready") return;
    const structure = residues.structure, list = residues.load.value;
    setForm(previous => {
      if (previous.structure !== structure) return previous;
      const base = { ...previous, chains: formForStructure(structure, list.residues).chains };
      const offered = mapPrefill(mapRows, structure, base.chains.map(choice => choice.chain_auth));
      const hinted = hint && hint.structure === structure && hint.load.status === "ready" ? hint.load.value.pdb_id : null;
      return applySuggestions(base, pdbIdSuggestion(offered, hinted), offered);
    });
  }, [residues]);
  useEffect(() => {
    if (!hint || hint.load.status !== "ready") return;
    const structure = hint.structure, hinted = hint.load.value.pdb_id;
    setForm(previous => previous.structure !== structure ? previous
      : applySuggestions(previous, pdbIdSuggestion(mapPrefill(mapRows, structure, []), hinted), null));
  }, [hint]);
  /* eslint-enable react-hooks/exhaustive-deps */

  function readLookup(pdbId: string) {
    const captured = stamp("pdb");
    setLookup({ pdbId, load: { status: "loading" } });
    api.reactionReferencePdb(pdbId, AbortSignal.timeout(TIMEOUT_MS)).then(value => {
      if (!current("pdb", captured)) return;
      if (!pdbLookupMatches(value, pdbId)) throw new Error(RESPONSE_SHAPE_TEXT);
      setLookup({ pdbId, load: { status: "ready", value } });
    }).catch(e => { if (current("pdb", captured))
      setLookup({ pdbId, load: { status: "error", message: `M-CSA 항목 제안 읽기 실패: ${readErrorText(e)}` } }); });
  }

  function setConfirmed(checked: boolean) {
    drop("pdb"); setLookup(null);
    setForm(previous => ({ ...previous, pdbIdConfirmed: checked }));
    const pdbId = normalizedPdbId(form.pdbId);
    if (checked && pdbId !== null && installed) readLookup(pdbId);
  }

  function editPdbId(value: string) {
    drop("pdb"); setLookup(null);
    setForm(previous => ({ ...previous, pdbId: value, pdbIdConfirmed: false }));
  }

  const check = checkReactionForm(form, { snapshot: statusValue, structures: structureRows ?? [], maps: mapRows });
  const fieldErrors = check.ok ? [] : check.errors;
  const errorsFor = (field: ReactionFormField, chain: string | null = null) =>
    fieldErrors.filter(error => error.field === field && error.chain === chain);
  const refusal = command.status === "refused" ? command.refusal : null;
  const refusedAt = (field: ReactionRefusal["field"]) => refusal && refusal.field === field ? refusal : null;
  const shownLookup = form.pdbIdConfirmed && lookup && lookup.pdbId === normalizedPdbId(form.pdbId) ? lookup : null;
  const lookupValue = shownLookup?.load.status === "ready" ? shownLookup.load.value : null;

  async function link() {
    if (!check.ok || command.status === "loading") return;
    const args = check.args, captured = stamp("command");
    setCommand({ status: "loading" });
    try {
      const outcome = reactionCommandOutcome(await api.linkReactionKnowledge(runId, args, AbortSignal.timeout(LINK_TIMEOUT_MS)));
      if (outcome.ok && mounted.current) setResultsReload(value => value + 1);   // stored even when no longer shown
      if (!current("command", captured)) return;
      if (!outcome.ok) { setCommand({ status: "refused", refusal: outcome.refusal }); return; }
      setCommand({ status: "done", handle: outcome.handle });
      openResult(outcome.handle);
    } catch (e) {
      if (current("command", captured)) setCommand({ status: "refused", refusal: reactionRefusal(e) });
    }
  }

  // ---- opened result: detail pages (chains, M-CSA rows, UniProt sites) and report ----
  function openResult(handle: string) {
    const same = handle === live.current.handle;
    setOpened(handle); live.current = { handle };
    setPaging(DEFAULT_DETAIL_PAGING); setReport(null);
    // The same handle again (the same request returns the stored result): read it again instead of waiting forever.
    if (same) setDetailRetry(value => value + 1); else setDetail(null);
  }

  const detailQuery = reactionDetailQuery(paging);
  const detailKey = opened === null ? null : `${opened}?${detailQuery}`;
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    if (opened === null || detailKey === null) return;
    const handle = opened, key = detailKey, asked = paging, captured = stamp("detail"), controller = new AbortController();
    setDetail({ key, load: { status: "loading" } });
    api.reactionKnowledgeResult(runId, handle, detailQuery, AbortSignal.any([controller.signal,
      AbortSignal.timeout(TIMEOUT_MS)])).then(value => {
      if (!current("detail", captured)) return;
      if (!reactionDetailMatches(value) || value.page.chain_offset !== asked.chain_offset ||
          value.page.row_offset !== asked.row_offset || value.page.feature_offset !== asked.feature_offset)
        throw new Error(RESPONSE_SHAPE_TEXT);
      setDetail({ key, load: { status: "ready", value } });
    }).catch(e => { if (current("detail", captured) && !controller.signal.aborted)
      setDetail({ key, load: { status: "error", message: `효소 반응 지식 결과 읽기 실패: ${readErrorText(e)}` } }); });
    return () => controller.abort();
  }, [detailKey, detailRetry]);
  /* eslint-enable react-hooks/exhaustive-deps */
  const detailLoad = detail && detail.key === detailKey ? detail.load : null;
  const detailValue = detailLoad?.status === "ready" ? detailLoad.value : null;

  async function makeReport() {
    if (opened === null || detailValue === null || report?.load.status === "loading") return;
    const handle = opened, captured = stamp("report");
    setReport({ handle, load: { status: "loading" } });
    try {
      const artifact = await api.createReactionKnowledgeReport(runId, handle, AbortSignal.timeout(60000));
      if (reactionReportSavedForRun(captured, runId) && mounted.current) onReportCreated(runId);
      if (!current("report", captured)) return;
      if (!reactionReportMatches(artifact, handle)) throw new Error(RESPONSE_SHAPE_TEXT);
      setReport({ handle, load: { status: "ready", value: artifact } });
    } catch (e) { if (current("report", captured))
      setReport({ handle, load: { status: "error", message: `보고서 만들기 실패: ${readErrorText(e)}` } }); }
  }

  // ---- area state (five states) ----
  const reads = [status, structures, maps, results];
  const readError = reads.map(load => load.status === "error" ? load.message : null).find(message => message !== null)
    ?? (detailLoad?.status === "error" ? detailLoad.message : null);
  const panel = reactionPanelState({ runId, capability,
    loading: reads.some(load => load.status === "idle" || load.status === "loading") || detailLoad?.status === "loading",
    error: readError, detail: detailValue });
  const requestReason = status.status === "error" ? STATUS_FAILED_REQUEST_TEXT
    : requestUnavailableReason({ snapshot: statusValue, structures: structureRows })
      ?? (snapshotView?.state === "unavailable" ? `${AREA_STATE_LABEL.unavailable}: ${snapshotView.reasonText}` : null);
  const resultRows = results.status === "ready" ? results.value : [];

  return <section className="mw-reaction" aria-label={PANEL_TITLE} data-testid="reaction-panel"
    data-reaction-state={panel.state}>
    <div className="mw-reaction-head">
      <h2 className="mw-reaction-heading">{PANEL_TITLE}</h2>
      <span className="mw-badge" data-testid="reaction-state">{AREA_STATE_LABEL[panel.state]}</span>
    </div>
    {panel.state === "failed" && <p role="alert" className="mw-reaction-error" data-testid="reaction-failure">{panel.message}</p>}

    <Section area="snapshot" title="① 반응 참조 스냅샷" state={snapshotView?.state ?? status.status}>
      {(status.status === "idle" || status.status === "loading") && <Loading />}
      {status.status === "error" && <ErrorLine message={status.message} testId="reaction-status-error"
        onRetry={() => setStatusReload(value => value + 1)} />}
      {snapshotView?.state === "unavailable" && <div className="mw-reaction-unavailable" data-testid="reaction-snapshot-unavailable"
        data-reason-code={snapshotView.reasonCode ?? undefined}>
        <p><b>{AREA_STATE_LABEL.unavailable}</b>: {snapshotView.reasonText}</p>
        <p>{snapshotView.hint}</p>
        <pre className="mw-reaction-command" data-testid="reaction-import-command">{snapshotView.command}</pre>
      </div>}
      {snapshotView?.state === "ready" && <div className="mw-reaction-snapshot" data-testid="reaction-snapshot-ready">
        {snapshotView.notes.map((line, index) => <p key={index} className="mw-reaction-notice"
          data-testid={index === 0 ? "reaction-note-rk1" : "reaction-note-uk1"}>{line}</p>)}
        <dl className="mw-reaction-facts">
          <dt>세트 해시</dt><dd><code data-testid="reaction-set-hash" title={snapshotView.setHash}>{snapshotView.setHashShort}</code></dd>
          <dt>가져온 시각</dt><dd data-testid="reaction-imported-at">{snapshotView.importedAt}</dd>
          <dt>가공본</dt><dd data-testid="reaction-processed-label">{snapshotView.processedLabel}</dd>
          <dt>직접 지정</dt><dd data-testid="reaction-user-named">{snapshotView.userNamedText}</dd>
          <dt>건너뜀</dt><dd data-testid="reaction-skipped">{snapshotView.skippedText}</dd>
        </dl>
        <p className="mw-reaction-note" data-testid="reaction-note-rk6">{snapshotView.licenseNote}</p>
        <div className="mw-reaction-table-wrap"><table className="mw-reaction-table" data-testid="reaction-snapshot-sources">
          <thead><tr><th>출처</th><th>스냅샷 날짜</th><th>라이선스</th><th>가공 행</th><th>가져온 곳</th></tr></thead>
          <tbody>{snapshotView.sources.map(source => <tr key={source.source} data-snapshot-source={source.source}>
            <td>{source.label}</td><td>{source.date}</td><td>{source.licenseText}</td><td className="mw-mono">{source.rowsText}</td>
            <td>{source.origin}</td></tr>)}</tbody>
        </table></div>
        {snapshotView.skipped.length > 0 && <details className="mw-reaction-details" data-testid="reaction-skipped-list">
          <summary>가져올 때 건너뛴 accession 목록</summary>
          <ul className="mw-reaction-list">{snapshotView.skipped.map(item => <li key={item.accession}
            data-skipped-accession={item.accession}><code>{item.accession}</code> · {item.reasonText} · {item.targetsText}</li>)}</ul>
        </details>}
      </div>}
    </Section>

    <Section area="request" title="② 연결 요청">
      {requestReason !== null ? <p className="mw-reaction-unavailable" role="status" data-testid="reaction-request-unavailable">
        {requestReason}</p>
        : !listsReady ? <>
          {(structures.status === "idle" || structures.status === "loading" || maps.status === "idle" ||
            maps.status === "loading") && <Loading text="구조·번호 대응 목록을 읽는 중" />}
          {structures.status === "error" && <ErrorLine message={structures.message} testId="reaction-structures-error"
            onRetry={() => setStructuresReload(value => value + 1)} />}
          {maps.status === "error" && <ErrorLine message={maps.message} testId="reaction-maps-error"
            onRetry={() => setMapsReload(value => value + 1)} />}
        </>
        : <RequestForm form={form} structures={structureRows ?? []} residues={residues} hint={hint} fileHint={fileHint}
          prefill={prefill} lookup={shownLookup} lookupValue={lookupValue} maps={mapsForStructure(mapRows, form.structure)}
          errorsFor={errorsFor} refusedAt={refusedAt} command={command} canLink={check.ok}
          onStructure={chooseStructure} onPdbId={editPdbId} onConfirm={setConfirmed}
          onRetryResidues={() => form.structure && chooseStructure(form.structure)}
          onRetryLookup={() => { const pdbId = normalizedPdbId(form.pdbId); if (pdbId !== null) readLookup(pdbId); }}
          onChain={(chain, selected) => setForm(previous => setChainSelected(previous, chain, selected))}
          onAccession={(chain, accession) => setForm(previous => setChainAccession(previous, chain, accession))}
          onMap={handle => setForm(previous => ({ ...previous, numberingMap: handle }))}
          onLink={() => void link()} />}
    </Section>

    <Section area="results" title="③ 저장된 결과" state={results.status}>
      {(results.status === "idle" || results.status === "loading") && <Loading text="결과 목록을 읽는 중" />}
      {results.status === "error" && <ErrorLine message={results.message} testId="reaction-results-error"
        onRetry={() => setResultsReload(value => value + 1)} />}
      {results.status === "ready" && (!resultRows.length
        ? <p className="mw-reaction-note" data-testid="reaction-no-results">이 run에 효소 반응 지식 결과가 없습니다.</p>
        : <fieldset className="mw-reaction-choices" data-testid="reaction-results">
          <legend>결과 선택 (최신 순, 자동으로 고르지 않음)</legend>
          {resultRows.map(item => {
            const badge = listSnapshotBadge(item, installed);
            return <label key={item.handle} data-reaction-result={item.handle} data-null-result={item.null_result}
              data-stale={badge === "stale" || undefined} data-no-active-set={badge === "no_active_set" || undefined}>
              <input type="radio" name={`reaction-result-${runId}`} data-testid="reaction-result" data-reaction-result={item.handle}
                checked={opened === item.handle} aria-label={`결과 ${shortHandle(item.handle)}`}
                onChange={() => openResult(item.handle)} />
              <span className="mw-mono">{STRUCTURE_KIND_TEXT[item.structure_kind] ?? item.structure_kind}{" "}
                {shortHandle(item.structure_handle)} · {reactionListItemText(item)} · {shortHandle(item.handle)}</span>
              <SnapshotMark badge={badge} title={item.set_hash} />
            </label>;
          })}
        </fieldset>)}
      {results.status !== "loading" && <Button size="sm" data-testid="reaction-results-refresh"
        onClick={() => setResultsReload(value => value + 1)}>결과 목록 다시 읽기</Button>}
    </Section>

    {opened !== null && <Section area="detail" title="④ 결과 상세" state={detailLoad?.status}>
      {(detailLoad === null || detailLoad.status === "loading" || detailLoad.status === "idle") && <Loading text="결과를 읽는 중" />}
      {detailLoad?.status === "error" && <ErrorLine message={detailLoad.message} testId="reaction-detail-error"
        onRetry={() => setDetailRetry(value => value + 1)} />}
      {detailValue && <ResultDetail handle={opened} detail={detailValue} paging={paging} onPaging={setPaging} />}
    </Section>}

    {opened !== null && detailValue && <Section area="report" title="⑤ 보고서">
      <div className="mw-reaction-inline">
        <Button size="sm" data-testid="reaction-report" disabled={report?.handle === opened && report.load.status === "loading"}
          onClick={() => void makeReport()}>보고서 만들기</Button>
        {report?.handle === opened && report.load.status === "loading" && <span className="mw-reaction-note" aria-busy="true">
          보고서를 만드는 중</span>}
      </div>
      <p className="mw-reaction-note">보고서는 저장된 결과로만 만들며 연결을 다시 계산하지 않습니다. 지식·보고서 탭의 보고서 목록에도 보입니다.</p>
      {report?.handle === opened && report.load.status === "ready" && <div className="mw-reaction-inline" role="status"
        data-testid="reaction-report-done" data-report-handle={report.load.value.handle}>
        <span className="mw-reaction-note">보고서를 저장했습니다 · {shortHandle(report.load.value.handle)}</span>
        <a className="mw-btn mw-btn--sm" data-testid="reaction-report-markdown"
          href={api.reportDownload(runId, report.load.value.handle, "markdown")} download>Markdown 내려받기</a>
        <a className="mw-btn mw-btn--sm" data-testid="reaction-report-json"
          href={api.reportDownload(runId, report.load.value.handle, "json")} download>JSON 내려받기</a>
      </div>}
      {report?.handle === opened && report.load.status === "error" && <ErrorLine message={report.load.message}
        testId="reaction-report-error" />}
    </Section>}
  </section>;
}

function FieldErrors({ errors, refusal, testId = "reaction-field-error" }: { errors: readonly ReactionFieldError[];
  refusal: ReactionRefusal | null; testId?: string }) {
  if (!errors.length && !refusal) return null;
  return <ul className="mw-reaction-errors">
    {errors.map(error => <li key={error.text} data-testid={testId} data-field={error.field}
      data-chain={error.chain ?? undefined}>{error.text}</li>)}
    {refusal && <li data-testid="reaction-refusal" data-field={refusal.field} data-chain={refusal.chain ?? undefined}
      data-reason-code={refusal.code ?? undefined}>{refusal.text}</li>}
  </ul>;
}

function RequestForm(p: { form: ReactionForm; structures: readonly StructureOption[];
  residues: { structure: string; load: Load<ResidueList> } | null; hint: { structure: string; load: Load<PdbIdHint> } | null;
  fileHint: PdbIdHint | null; prefill: ReturnType<typeof mapPrefill>;
  lookup: { pdbId: string; load: Load<ReactionPdbEntries> } | null; lookupValue: ReactionPdbEntries | null;
  maps: readonly NumberingMapListRow[];
  errorsFor: (field: ReactionFormField, chain?: string | null) => ReactionFieldError[];
  refusedAt: (field: ReactionRefusal["field"]) => ReactionRefusal | null;
  command: CommandState; canLink: boolean;
  onStructure: (handle: string | null) => void; onPdbId: (value: string) => void; onConfirm: (checked: boolean) => void;
  onRetryResidues: () => void; onRetryLookup: () => void; onChain: (chain: string, selected: boolean) => void;
  onAccession: (chain: string, accession: string) => void; onMap: (handle: string | null) => void; onLink: () => void }) {
  const form = p.form;
  const residuesLoad = p.residues && p.residues.structure === form.structure ? p.residues.load : null;
  const hintLoad = p.hint && p.hint.structure === form.structure ? p.hint.load : null;
  const chainRefusal = p.refusedAt("chains");
  const chainNames = new Set(form.chains.map(choice => choice.chain_auth));
  const requestRefusal = p.refusedAt("request") ?? p.refusedAt("result") ?? p.refusedAt("snapshot");
  return <div className="mw-reaction-form" data-testid="reaction-request-form">
    <div className="mw-reaction-field" data-reaction-field="structure">
      <label className="mw-reaction-check">구조
        <select className="mw-select" data-testid="reaction-structure" aria-label="구조 선택" value={form.structure ?? ""}
          onChange={event => p.onStructure(event.target.value || null)}>
          <option value="">구조를 고르세요</option>
          {p.structures.map(option => <option key={option.handle} value={option.handle} title={option.handle}>
            {STRUCTURE_KIND_TEXT[option.kind] ?? option.kind} ({option.kind}) · {shortHandle(option.handle)}</option>)}
        </select></label>
      <p className="mw-reaction-note">{STRUCTURE_NOTE}</p>
      <FieldErrors errors={p.errorsFor("structure")} refusal={p.refusedAt("structure")} />
    </div>

    {form.structure && <>
      <div className="mw-reaction-field" data-reaction-field="pdb_id">
        <span className="mw-eyebrow">PDB ID</span>
        <p className="mw-reaction-note" data-testid="reaction-pdb-hint">
          {p.prefill?.pdbId ? `같은 구조의 가장 최근 번호 대응에 적힌 PDB ID: ${p.prefill.pdbId}`
            : hintLoad?.status === "loading" ? "구조 파일의 PDB ID 제안을 읽는 중"
            : hintLoad?.status === "error" ? hintLoad.message
            : p.fileHint?.pdb_id ? `구조 파일의 제안: ${p.fileHint.pdb_id} (${p.fileHint.origin ?? NULL_TEXT})`
            : hintLoad?.status === "ready" ? "구조 파일에 PDB ID가 없습니다." : ""}</p>
        <div className="mw-reaction-inline">
          <input className="mw-reaction-input" data-testid="reaction-pdb-id" aria-label="PDB ID" value={form.pdbId} maxLength={4}
            placeholder="예: 1S9I" onChange={event => p.onPdbId(event.target.value)} />
          <label className="mw-reaction-check">
            <input type="checkbox" data-testid="reaction-pdb-confirm" checked={form.pdbIdConfirmed} disabled={!form.pdbId.trim()}
              onChange={event => p.onConfirm(event.target.checked)} />
            이 PDB ID가 맞습니다</label>
        </div>
        <p className="mw-reaction-note">{PDB_ID_NOTE}</p>
        {p.lookup?.load.status === "loading" && <Loading text="M-CSA 항목 제안을 읽는 중" />}
        {p.lookup?.load.status === "error" && <ErrorLine message={p.lookup.load.message} testId="reaction-pdb-lookup-error"
          onRetry={p.onRetryLookup} />}
        {p.lookupValue && <p className="mw-reaction-note" data-testid="reaction-pdb-lookup"
          data-entries={p.lookupValue.entries.length}>{pdbLookupText(p.lookupValue)} {SUGGESTION_NOTE}</p>}
        <FieldErrors errors={p.errorsFor("pdb_id")} refusal={p.refusedAt("pdb_id")} />
      </div>

      <fieldset className="mw-reaction-choices" data-testid="reaction-chains" data-reaction-field="chains">
        <legend>체인 (polymer 잔기가 있는 체인, 자동으로 고르지 않음)</legend>
        {(residuesLoad === null || residuesLoad.status === "loading") && <Loading text="구조 잔기 목록을 읽는 중" />}
        {residuesLoad?.status === "error" && <ErrorLine message={residuesLoad.message} testId="reaction-residues-error"
          onRetry={p.onRetryResidues} />}
        {residuesLoad?.status === "ready" && !form.chains.length && <p className="mw-reaction-note">
          polymer 잔기가 있는 체인이 없습니다.</p>}
        {form.chains.map(choice => {
          const suggestions = accessionSuggestions(p.lookupValue, choice.chain_auth);
          const mapAccession = p.prefill?.accessions[choice.chain_auth] ?? null;
          return <div key={choice.chain_auth} className="mw-reaction-chain-row" data-reaction-chain={choice.chain_auth}
            data-selected={choice.selected}>
            <label className="mw-reaction-check">
              <input type="checkbox" data-testid={`reaction-chain-${choice.chain_auth}`} checked={choice.selected}
                onChange={event => p.onChain(choice.chain_auth, event.target.checked)} />
              체인 <code>{choice.chain_auth}</code></label>
            <label className="mw-reaction-check">UniProt accession (비우면 보내지 않음)
              <input className="mw-reaction-input mw-reaction-input--accession" data-testid={`reaction-accession-${choice.chain_auth}`}
                aria-label={`체인 ${choice.chain_auth} UniProt accession`} value={choice.accession} maxLength={10}
                onChange={event => p.onAccession(choice.chain_auth, event.target.value)} /></label>
            {mapAccession && <span className="mw-reaction-note" data-testid={`reaction-map-accession-${choice.chain_auth}`}>
              번호 대응의 accession: <code>{mapAccession}</code> (빈 칸에만 미리 채움, 고칠 수 있음)</span>}
            {suggestions.length > 0 && <div className="mw-reaction-inline" data-testid={`reaction-suggestions-${choice.chain_auth}`}>
              {suggestions.map(suggestion => <Button key={suggestion.accession} size="sm"
                data-testid={`reaction-use-accession-${choice.chain_auth}-${suggestion.accession}`}
                data-accession={suggestion.accession} title={suggestion.text}
                onClick={() => p.onAccession(choice.chain_auth, suggestion.accession)}>
                {USE_SUGGESTION_TEXT}: {suggestion.text}</Button>)}
            </div>}
            <FieldErrors errors={p.errorsFor("chains", choice.chain_auth)}
              refusal={chainRefusal && chainRefusal.chain === choice.chain_auth ? chainRefusal : null} />
          </div>;
        })}
        <FieldErrors errors={p.errorsFor("chains")}
          refusal={chainRefusal && (chainRefusal.chain === null || !chainNames.has(chainRefusal.chain)) ? chainRefusal : null} />
      </fieldset>

      <div className="mw-reaction-field" data-reaction-field="numbering_map">
        <label className="mw-reaction-check">번호 대응 (선택 사항, 같은 구조)
          <select className="mw-select" data-testid="reaction-numbering-map" aria-label="번호 대응 선택"
            value={form.numberingMap ?? ""} onChange={event => p.onMap(event.target.value || null)}>
            <option value="">고르지 않음</option>
            {p.maps.map(row => <option key={row.handle} value={row.handle}>
              {row.structure_kind} · 체인 {row.chains.join(", ")} · PDB {row.pdb_id ?? NULL_TEXT} · 이벤트 #{row.created_seq} ·{" "}
              {shortHandle(row.handle)}</option>)}
          </select></label>
        <p className="mw-reaction-note">{MAP_NOTE}</p>
        {!p.maps.length && <p className="mw-reaction-note" data-testid="reaction-no-maps">이 구조의 번호 대응이 없습니다(지식·보고서 탭의
          잔기 번호 대응 화면에서 만들 수 있음).</p>}
        <FieldErrors errors={p.errorsFor("numbering_map")} refusal={p.refusedAt("numbering_map")} />
      </div>
    </>}

    <p className="mw-reaction-note">{LINK_NOTE}</p>
    <div className="mw-reaction-inline">
      <Button size="sm" variant="primary" data-testid="reaction-link" disabled={!p.canLink || p.command.status === "loading"}
        onClick={p.onLink}>{LINK_BUTTON_TEXT}</Button>
      {p.command.status === "loading" && <span className="mw-reaction-note" aria-busy="true">link_reaction_knowledge 실행 중</span>}
    </div>
    <FieldErrors errors={p.errorsFor("snapshot")} refusal={requestRefusal} />
    {p.command.status === "done" && <p role="status" className="mw-reaction-note" data-testid="reaction-link-done"
      data-reaction-new-result={p.command.handle}>결과를 저장했습니다 · {shortHandle(p.command.handle)}</p>}
  </div>;
}

function ResultDetail({ handle, detail, paging, onPaging }: { handle: string; detail: ReactionKnowledgeDetail;
  paging: ReactionDetailPaging; onPaging: (paging: ReactionDetailPaging) => void }) {
  const view = reactionResultView(detail);
  const page = detail.page;
  const chainPrev = previousOffset(page.chain_offset, page.chain_limit);
  const chainNext = nextOffset(page.chain_total, page.chain_offset, page.chain_limit);
  // One row / site offset applies to every chain of the page: "다음" while any chain on it has more (server totals).
  const rowPrev = previousOffset(page.row_offset, page.row_limit);
  const rowNext = detail.chains.map(chain => nextOffset(chain.mcsa.row_total, page.row_offset, page.row_limit))
    .find(offset => offset !== null) ?? null;
  const featurePrev = previousOffset(page.feature_offset, page.feature_limit);
  const featureNext = detail.chains.map(chain => nextOffset(chain.uniprot.feature_total, page.feature_offset,
    page.feature_limit)).find(offset => offset !== null) ?? null;
  return <div className="mw-reaction-detail" data-testid="reaction-detail" data-reaction-detail={handle}
    data-null-result={detail.null_result}>
    <p className="mw-mono">결과 {shortHandle(handle)} · 구조 {view.structureText}</p>
    <dl className="mw-reaction-facts">
      <dt>PDB ID</dt><dd data-testid="reaction-detail-pdb">{view.pdbIdText}</dd>
      <dt>번호 대응</dt><dd data-testid="reaction-detail-map">{view.numberingMapText}</dd>
      <dt>스냅샷 세트</dt><dd><code title={detail.snapshot_set.set_hash}>{view.setHashShort}</code> · {view.importedAt}{" "}
        <SnapshotMark badge={view.badge} title={detail.active_set.set_hash ?? undefined} /></dd>
    </dl>
    <p className="mw-reaction-note">{REFERENCE_NOTE}: M-CSA·UniProt·Rhea 값은 스냅샷에 적힌 그대로이며, ProtView가 센 것은 아래 개수뿐입니다.</p>
    <div className="mw-reaction-table-wrap"><table className="mw-reaction-table" data-testid="reaction-detail-sources">
      <thead><tr><th>출처</th><th>스냅샷 날짜</th><th>라이선스</th></tr></thead>
      <tbody>{view.sources.map(source => <tr key={source.label}><td>{source.label}</td><td>{source.date}</td>
        <td>{source.licenseText}</td></tr>)}</tbody>
    </table></div>
    <span className="mw-eyebrow">개수 (ProtView가 센 계산값)</span>
    <dl className="mw-reaction-facts" data-testid="reaction-counts">
      {view.countRows.map(row => <div key={row.key} className="mw-reaction-fact" data-reaction-count={row.key}>
        <dt>{row.label}</dt><dd>{row.text}</dd></div>)}
    </dl>
    {view.nullResultText && <p role="status" className="mw-reaction-null" data-testid="reaction-null-result">
      {view.nullResultText}</p>}

    <div className="mw-reaction-inline" data-testid="reaction-pager">
      <span className="mw-reaction-note" data-testid="reaction-chains-page">체인 {view.chainPageText}</span>
      <Button size="sm" data-testid="reaction-chains-prev" disabled={chainPrev === null}
        onClick={() => chainPrev !== null && onPaging({ ...paging, chain_offset: chainPrev })}>체인 이전</Button>
      <Button size="sm" data-testid="reaction-chains-next" disabled={chainNext === null}
        onClick={() => chainNext !== null && onPaging({ ...paging, chain_offset: chainNext })}>체인 다음</Button>
      <Button size="sm" data-testid="reaction-rows-prev" disabled={rowPrev === null}
        onClick={() => rowPrev !== null && onPaging({ ...paging, row_offset: rowPrev })}>M-CSA 행 이전</Button>
      <Button size="sm" data-testid="reaction-rows-next" disabled={rowNext === null}
        onClick={() => rowNext !== null && onPaging({ ...paging, row_offset: rowNext })}>M-CSA 행 다음</Button>
      <Button size="sm" data-testid="reaction-features-prev" disabled={featurePrev === null}
        onClick={() => featurePrev !== null && onPaging({ ...paging, feature_offset: featurePrev })}>UniProt 부위 이전</Button>
      <Button size="sm" data-testid="reaction-features-next" disabled={featureNext === null}
        onClick={() => featureNext !== null && onPaging({ ...paging, feature_offset: featureNext })}>UniProt 부위 다음</Button>
    </div>

    {view.chains.map(chain => <ChainBlock key={chain.chainAuth} chain={chain} />)}

    <div className="mw-reaction-group" data-testid="reaction-limitations">
      <span className="mw-eyebrow">한계 (고정 문장, 저장된 그대로)</span>
      {view.limitations.map((sentence, index) => <p key={index} className="mw-reaction-note" data-limitation={index}>{sentence}</p>)}
    </div>
  </div>;
}

function ReferenceText({ value }: { value: string }) {
  return value ? <span className="mw-reaction-ref">{value}</span>
    : <span className="mw-reaction-ref mw-reaction-ref--empty" data-empty="true">&quot;&quot;</span>;
}

function ChainBlock({ chain }: { chain: ChainView }) {
  const mcsa = chain.mcsa, uniprot = chain.uniprot, reactions = chain.reactions;
  return <div className="mw-reaction-chain" data-reaction-chain-view={chain.chainAuth} data-coverage={mcsa.coverage ?? undefined}
    data-mcsa-status={mcsa.status} data-uniprot-status={uniprot.status} data-reactions-status={reactions.status}>
    <div className="mw-reaction-chain-head">
      <h4>체인 <code>{chain.chainAuth}</code></h4>
      <span className="mw-reaction-badge" data-testid="reaction-chain-coverage">{mcsa.coverageText}</span>
      {chain.chainNote && <span className="mw-reaction-note" data-testid="reaction-chain-uk4">{chain.chainNote}</span>}
    </div>
    <p className="mw-reaction-note">{chain.residueCountText} · accession {chain.accessionText}</p>
    {chain.flags.map(flag => <p key={flag} className="mw-reaction-note" data-testid="reaction-chain-flag">{flag}</p>)}

    <div className="mw-reaction-group" data-reaction-section="mcsa">
      <span className="mw-eyebrow">M-CSA 촉매 잔기 ({REFERENCE_NOTE})</span>
      <p data-testid="reaction-mcsa-status">상태 {mcsa.statusText} · {mcsa.coverageText}{mcsa.reasonText ? ` · ${mcsa.reasonText}` : ""}</p>
      {mcsa.entries === null ? <p className="mw-reaction-note" data-testid="reaction-mcsa-entries-none">M-CSA 항목 {mcsa.entriesText}</p>
        : <ul className="mw-reaction-list" data-testid="reaction-mcsa-entries">
          {mcsa.entries.map(entry => <li key={entry.mcsaId} data-mcsa-id={entry.mcsaId}>{entry.text} · {entry.ecsText}</li>)}</ul>}
      <p className="mw-reaction-note" data-testid="reaction-mcsa-counts">행 개수(계산값): {mcsa.countsText}</p>
      {mcsa.rows === null ? <p className="mw-reaction-note" data-testid="reaction-mcsa-rows-none">M-CSA 행 {mcsa.rowsText}</p> : <>
        <p className="mw-reaction-note" data-testid="reaction-mcsa-rows-page">M-CSA 행 {mcsa.rowPageText}</p>
        <div className="mw-reaction-table-wrap"><table className="mw-reaction-table" data-testid="reaction-mcsa-rows">
          <thead><tr><th>상태</th><th>M-CSA 항목 · 잔기 순번</th><th>구조 잔기 (7필드)</th><th>구조 잔기 이름</th>
            <th>M-CSA가 적은 PDB · 체인 · 번호 · 이름</th><th>기준 구조 여부</th><th>{REFERENCE_COLUMN_LABEL}</th><th>이유</th></tr></thead>
          <tbody>{mcsa.rows.map((row, index) => <tr key={`${row.mcsaId}-${row.residueIndex}-${index}`} data-mcsa-row-status={row.status}
            data-mcsa-id={row.mcsaId} data-residue-index={row.residueIndex}>
            <td>{row.statusText}</td>
            <td className="mw-mono">M-CSA {row.mcsaId} · {row.residueIndex}</td>
            <td className="mw-mono" data-cell="residue">{row.residueText}</td>
            <td className="mw-mono">{row.structureResnameText}</td>
            <td className="mw-mono">{row.listed.pdbId} · {row.listed.chainName} · resid {row.listed.residText} · auth_resid{" "}
              {row.listed.authResidText} · {row.listed.code} · assembly {row.listed.assembliesText}</td>
            <td>{row.isReferenceText}</td>
            <td className="mw-reaction-ref-cell" data-cell="reference">
              <dl className="mw-reaction-ref-list">
                <dt>roles_summary</dt><dd><ReferenceText value={row.reference.roles_summary} /></dd>
                <dt>function_location_abv</dt><dd><ReferenceText value={row.reference.function_location_abv} /></dd>
                <dt>ptm</dt><dd><ReferenceText value={row.reference.ptm} /></dd>
                <dt>roles</dt><dd>{row.rolesText === null ? NULL_TEXT
                  : row.rolesText.length ? <ul className="mw-reaction-list">{row.rolesText.map((text, roleIndex) =>
                    <li key={roleIndex}><ReferenceText value={text} /></li>)}</ul> : "빈 목록 ([])"}</dd>
              </dl>
            </td>
            <td>{row.reasonText}</td>
          </tr>)}</tbody>
        </table></div>
      </>}
    </div>

    <div className="mw-reaction-group" data-reaction-section="uniprot">
      <span className="mw-eyebrow">UniProt 부위 ({REFERENCE_NOTE})</span>
      <p data-testid="reaction-uniprot-status">상태 {uniprot.statusText}{uniprot.reasonText ? ` · ${uniprot.reasonText}` : ""}</p>
      {uniprot.skippedText && <p className="mw-reaction-note" data-testid="reaction-uniprot-skipped">{uniprot.skippedText}</p>}
      {uniprot.entry && <p className="mw-reaction-note" data-testid="reaction-uniprot-entry"><code>{uniprot.entry.accession}</code>{" "}
        · {uniprot.entry.entryName} · {uniprot.entry.proteinName} · {uniprot.entry.organism} · {uniprot.entry.sequenceLengthText}</p>}
      <p className="mw-reaction-note" data-testid="reaction-uniprot-link">구조 잔기 연결: {uniprot.linkText}</p>
      {uniprot.features === null ? <p className="mw-reaction-note" data-testid="reaction-features-none">UniProt 부위 {uniprot.featuresText}</p>
        : <>
          <p className="mw-reaction-note">{POSITION_NOTE} · UniProt 부위 {uniprot.featurePageText}</p>
          {uniprot.featuresText !== null ? <p className="mw-reaction-note" data-testid="reaction-features-empty">{uniprot.featuresText}</p>
            : <div className="mw-reaction-table-wrap"><table className="mw-reaction-table" data-testid="reaction-features">
              <thead><tr><th>종류</th><th>UniProt 서열 위치</th><th>설명</th><th>리간드 (UniProt 원문)</th><th>구조 잔기 연결</th></tr></thead>
              <tbody>{uniprot.features.map((feature, index) => <tr key={index} data-feature-type={feature.type}
                data-linked={feature.linked}>
                <td>{feature.type}</td><td className="mw-mono">{feature.rangeText}</td>
                <td><ReferenceText value={feature.description} /></td><td>{feature.ligandText}</td>
                <td>{feature.links === null ? feature.linkText
                  : <ul className="mw-reaction-list" data-testid="reaction-feature-links">{feature.links.map((link, linkIndex) =>
                    <li key={linkIndex} data-link-status={link.status} data-position={link.position}>
                      위치 {link.position} · {link.statusText} · {link.residueText} · UniProt 잔기 {link.uniprotResidueText} ·{" "}
                      {link.residueMatchText}</li>)}</ul>}</td>
              </tr>)}</tbody>
            </table></div>}
        </>}
    </div>

    <div className="mw-reaction-group" data-reaction-section="reactions">
      <span className="mw-eyebrow">반응 ({REFERENCE_NOTE})</span>
      <p data-testid="reaction-reactions-status">상태 {reactions.statusText}{reactions.reasonText ? ` · ${reactions.reasonText}` : ""}</p>
      <p className="mw-reaction-note" data-testid="reaction-ec-mcsa">EC (M-CSA): {reactions.ecMcsaText}</p>
      <p className="mw-reaction-note" data-testid="reaction-ec-uniprot">EC (UniProt): {reactions.ecUniprotText}</p>
      <span className="mw-eyebrow">M-CSA 반응 화합물</span>
      {reactions.compounds === null || reactions.compoundsText !== null
        ? <p className="mw-reaction-note" data-testid="reaction-compounds-none">{reactions.compoundsText}</p>
        : <ul className="mw-reaction-list" data-testid="reaction-compounds">{reactions.compounds.map(item =>
          <li key={item.mcsaId} data-mcsa-id={item.mcsaId}>M-CSA {item.mcsaId} · EC {item.ecText}
            {item.items.length ? <ul className="mw-reaction-list">{item.items.map((compound, index) => <li key={index}>
              {compound.type} · {compound.chebiId} · <ReferenceText value={compound.name} /></li>)}</ul>
              : <span className="mw-reaction-note"> · 빈 목록 ([])</span>}</li>)}</ul>}
      <span className="mw-eyebrow">UniProt 촉매 활동과 Rhea 반응식</span>
      {reactions.activities === null || reactions.activitiesText !== null
        ? <p className="mw-reaction-note" data-testid="reaction-activities-none">{reactions.activitiesText}</p>
        : <ul className="mw-reaction-list" data-testid="reaction-activities">{reactions.activities.map((activity, index) =>
          <li key={index}><ReferenceText value={activity.reactionName} /> · EC {activity.ecText}
            {activity.rhea.length > 0 && <ul className="mw-reaction-list">{activity.rhea.map(link => <li key={link.rheaId}
              data-rhea-id={link.rheaId} data-in-snapshot={link.inSnapshot}>
              <code>{link.rheaId}</code> · {link.inSnapshotText} · {link.inSnapshot
                ? <ReferenceText value={link.equationText} /> : link.equationText}</li>)}</ul>}</li>)}</ul>}
    </div>
  </div>;
}
