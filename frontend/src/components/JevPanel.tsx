"use client";

import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type RunSummary } from "@/lib/api";
import type { JevKind, JevPreviewV1, JevProjectionSummary, JevReportArtifact, JevSendDetail, JevSendV1, JevStatusV1,
  LigandCandidatePage, LigandCandidateSetListRow, MutationCandidatePage, MutationCandidateSetListRow } from "@/lib/contracts";
import { ALIAS_TABLE_NOTE, BUILD_BUTTON_TEXT, CONFIRM_CHECK_TEXT, CONSENT_NOTICE, CONSENT_SWITCH_LABEL, JEV_AREAS,
  JEV_MAX_CANDIDATES, JEV_PANEL_TITLE, JEV_POLL_MS, JEV_SCREEN_NOTES, JEV_TEXT, NO_SOURCE_REASON, NULL_TEXT,
  PROBABILITY_NOTE, RESPONSE_SHAPE_TEXT, SCIENCE_BADGE_NOTE, SELECTION_FULL_REASON, SEND_BUTTON_TEXT, SOURCE_KIND_LABEL,
  consentSwitchDisabledReason, emptyJevSelection, jevAttemptAfter, jevBuildBlockers, jevCandidateBlockedReason,
  jevCandidateChecked, jevConfirmed, jevDetailMatches, jevErrorInfo, jevFilterConflicts, jevPanelState,
  jevPreviewMatches, jevPreviewView, jevProjectionArgs, jevProjectionOutcome, jevReportMatches, jevResponseCurrent,
  jevResultView, jevSelectionCountText, jevSendAttempt, jevSendBlockers, jevSendListMatches, jevSendRequest,
  jevSendResponseMatches, jevSendRows, jevSendsPending, jevStatusMatches, jevStatusView, ligandCandidateOption,
  ligandSourceOptions, mutationCandidateOption, mutationSourceOptions, projectionSummaryText,
  residueText, sendReasonText, sendStatusText, toggleJevCandidate, type JevCandidateOption, type JevSelection,
  type JevSendAttempt, type JevStamp } from "@/lib/jev";
import { CANDIDATE_PAGE_LIMIT, candidateCountText, candidateRowsQuery, checkFilterInput, emptyAppliedFilter,
  emptyFilterInput, passText, type AppliedFilter, type LigandFilterInput } from "@/lib/ligand";
import { candidateQuery, EMPTY_CANDIDATE_FILTERS, pageRangeText } from "@/lib/mutations";
import { FilterForm } from "./LigandPanel";
import { Button, shortSha } from "./primitives";

/**
 * M24 "JEV 판정(외부 모델)" area of the 지식·보고서 tab (spec `.dryforge/spec.md` 9), mounted between the residue
 * numbering screen and the report library. The answer is a proposal, never a computed value: every number shown is a
 * stored server value (status, preview, send record, `jev_choice@1`) and every wording, guard and view model comes
 * from `lib/jev.ts`. The one external send is the person's click on the approval button for one exact previewed body
 * (`api.jevSend`); mounting (entering the tab) only reads. The page mounts it only while the tab is shown and keys it
 * by run; late answers are dropped by run + projection/send handle + per-area request number (`jevResponseCurrent`).
 */
export interface JevPanelProps {
  /** Current run of the structure analysis screen (run selection lives only there); null when none. */
  run: RunSummary | null;
  /** `/capabilities` `methods.jev_choice`: undefined while capabilities are read, null when absent. */
  capability: JevCapability | null | undefined;
  /** After a report was created: the page re-reads the report library (it drops another run's call). */
  onReportCreated: (runId: string) => void;
  /** Every status this area reads or sets: the page's global "과학 전송 허용" mark follows it (same run only). */
  onStatus?: (runId: string, status: JevStatusV1) => void;
}

type JevCapability = { available: boolean; reason_code: string | null; reason: string | null };
type Load<T> = { status: "idle" } | { status: "loading" } | { status: "ready"; value: T } | { status: "error"; message: string };
type Area = (typeof JEV_AREAS)[number];
const TIMEOUT_MS = 30000;
const LONG_TIMEOUT_MS = 120000;
const LIST_LIMIT = 100;
const KINDS = Object.keys(SOURCE_KIND_LABEL) as JevKind[];

function errorText(e: unknown): string { return jevErrorInfo(e).text; }

async function allLigandSets(runId: string, signal: AbortSignal): Promise<LigandCandidateSetListRow[]> {
  const first = await api.ligandCandidateSets(runId, null, 0, LIST_LIMIT, signal);
  if (first.schema !== "ligand_candidate_set_list@1") throw new Error(RESPONSE_SHAPE_TEXT);
  const rows = [...first.rows];
  while (rows.length < first.total) {
    const page = await api.ligandCandidateSets(runId, null, rows.length, LIST_LIMIT, signal);
    if (page.schema !== first.schema || page.total !== first.total || !page.rows.length) throw new Error(RESPONSE_SHAPE_TEXT);
    rows.push(...page.rows);
  }
  return rows;
}

async function allMutationSets(runId: string, signal: AbortSignal): Promise<MutationCandidateSetListRow[]> {
  const first = await api.mutationCandidateSets(runId, 0, LIST_LIMIT, signal);
  if (first.schema !== "mutation_candidate_set_list@1") throw new Error(RESPONSE_SHAPE_TEXT);
  const rows = [...first.rows];
  while (rows.length < first.total) {
    const page = await api.mutationCandidateSets(runId, rows.length, LIST_LIMIT, signal);
    if (page.schema !== first.schema || page.total !== first.total || !page.rows.length) throw new Error(RESPONSE_SHAPE_TEXT);
    rows.push(...page.rows);
  }
  return rows;
}

function Section({ area, title, state, children }: { area: string; title: string; state?: string; children: ReactNode }) {
  return <section className="mw-jev-section" data-jev-area={area} data-state={state} aria-label={title}>
    <h3 className="mw-jev-title">{title}</h3>
    {children}
  </section>;
}

function ErrorLine({ message, onRetry, testId }: { message: string; onRetry?: () => void; testId?: string }) {
  return <div className="mw-jev-error" role="alert" data-testid={testId}>
    <span>{message}</span>
    {onRetry && <Button size="sm" onClick={onRetry}>{JEV_TEXT.retry}</Button>}
  </div>;
}

function Loading({ text = JEV_TEXT.loading }: { text?: string }) {
  return <p className="mw-jev-note" aria-busy="true">{text}</p>;
}

export function JevPanel(p: JevPanelProps) {
  const runId = p.run?.run_id ?? null;
  const gate = jevPanelState({ runId, capability: p.capability, status: null });
  if (p.run === null || gate.state === "unavailable" || p.capability === undefined || p.capability === null) {
    const reason = gate.state !== "unavailable" ? null
      : runId !== null && p.capability?.reason_code ? `${gate.reason} (${p.capability.reason_code})` : gate.reason;
    return <section className="mw-jev" aria-label={JEV_PANEL_TITLE} data-testid="jev-panel"
      data-jev-state={reason === null ? "loading" : "unavailable"}>
      <h2 className="mw-jev-heading">{JEV_PANEL_TITLE}</h2>
      {reason !== null ? <p className="mw-jev-unavailable" role="status"
        data-testid={runId === null ? "jev-no-run" : "jev-unavailable"}><b>{JEV_TEXT.unavailable}</b>: {reason}</p>
        : <Loading text={JEV_TEXT.loadingCapability} />}
    </section>;
  }
  return <JevWorkspace run={p.run} onReportCreated={p.onReportCreated} onStatus={p.onStatus} />;
}

function JevWorkspace({ run, onReportCreated, onStatus }: { run: RunSummary; onReportCreated: (runId: string) => void;
  onStatus?: (runId: string, status: JevStatusV1) => void }) {
  const runId = run.run_id;
  const [status, setStatus] = useState<Load<JevStatusV1>>({ status: "idle" });
  const [consentBusy, setConsentBusy] = useState(false);
  const [consentError, setConsentError] = useState<string | null>(null);
  const [ligandSets, setLigandSets] = useState<Load<LigandCandidateSetListRow[]>>({ status: "idle" });
  const [mutationSets, setMutationSets] = useState<Load<MutationCandidateSetListRow[]>>({ status: "idle" });
  const [kind, setKind] = useState<JevKind | null>(null);
  const [selection, setSelection] = useState<JevSelection | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [filterInput, setFilterInput] = useState<LigandFilterInput>(emptyFilterInput);
  const [filterErrors, setFilterErrors] = useState<string[]>([]);
  const [applied, setApplied] = useState<AppliedFilter>(emptyAppliedFilter);
  const [passesOnly, setPassesOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [rowsRetry, setRowsRetry] = useState(0);
  const [ligandRows, setLigandRows] = useState<{ key: string; load: Load<LigandCandidatePage> } | null>(null);
  const [mutationRows, setMutationRows] = useState<{ key: string; load: Load<MutationCandidatePage> } | null>(null);
  const [projection, setProjection] = useState<{ handle: string; summary: JevProjectionSummary } | null>(null);
  const [build, setBuild] = useState<Load<true>>({ status: "idle" });
  const [preview, setPreview] = useState<{ handle: string; load: Load<JevPreviewV1> } | null>(null);
  const [confirmedFor, setConfirmedFor] = useState<string | null>(null);
  /** The send id of the one send in flight (null = none). */
  const [inFlight, setInFlight] = useState<string | null>(null);
  /** The send id an unanswered attempt keeps for its retry (shown on the button). */
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [lastRecord, setLastRecord] = useState<JevSendV1 | null>(null);
  const [sends, setSends] = useState<Load<JevSendV1[]>>({ status: "idle" });
  const [opened, setOpened] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ sendId: string; load: Load<JevSendDetail> } | null>(null);
  const [report, setReport] = useState<{ handle: string; load: Load<JevReportArtifact> } | null>(null);

  const mounted = useRef(true);
  const readAbort = useRef<AbortController | null>(null);
  const sendingRef = useRef(false);
  const attemptRef = useRef<JevSendAttempt | null>(null);
  const statusCallback = useRef(onStatus);
  statusCallback.current = onStatus;
  const seqs = useRef(Object.fromEntries(JEV_AREAS.map(area => [area, 0])) as Record<Area, number>);
  const live = useRef({ source: null as string | null, projection: null as string | null, send: null as string | null,
    detail: null as string | null, report: null as string | null });
  live.current = { source: selection?.source ?? null, projection: projection?.handle ?? null, send: inFlight,
    detail: opened, report: report?.handle ?? null };
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    readAbort.current = controller;
    const counters = seqs.current;
    return () => { mounted.current = false; controller.abort(); for (const area of JEV_AREAS) counters[area] += 1; };
  }, []);
  const keyOf = (area: Area): string | null => area === "candidates" || area === "projection" ? live.current.source
    : area === "preview" ? live.current.projection : area === "send" ? live.current.send
      : area === "detail" ? live.current.detail : area === "report" ? live.current.report : null;
  const stamp = (area: Area): JevStamp => ({ runId, handle: keyOf(area), seq: ++seqs.current[area] });
  const current = (area: Area, captured: JevStamp) => mounted.current &&
    jevResponseCurrent(captured, { runId, handle: keyOf(area), seq: seqs.current[area] });
  /** Reads end with the mount (leaving the tab) or after the time limit. */
  const readSignal = (ms = TIMEOUT_MS) =>
    AbortSignal.any([readAbort.current?.signal ?? new AbortController().signal, AbortSignal.timeout(ms)]);

  // ---- reads (entering the tab reads status, this run's candidate sets and sends; nothing is chosen or sent) ----
  function readStatus() {
    const captured = stamp("status");
    setStatus(previous => previous.status === "ready" ? previous : { status: "loading" });
    api.jevStatus(runId, readSignal()).then(value => {
      if (!current("status", captured)) return;
      if (!jevStatusMatches(value)) throw new Error(RESPONSE_SHAPE_TEXT);
      setStatus({ status: "ready", value });
      statusCallback.current?.(runId, value);
    }).catch(e => { if (current("status", captured)) setStatus({ status: "error", message: errorText(e) }); });
  }

  function readSources() {
    const captured = stamp("sources"), signal = readSignal();
    setLigandSets({ status: "loading" });
    setMutationSets({ status: "loading" });
    allLigandSets(runId, signal).then(value => { if (current("sources", captured)) setLigandSets({ status: "ready", value }); })
      .catch(e => { if (current("sources", captured)) setLigandSets({ status: "error", message: errorText(e) }); });
    allMutationSets(runId, signal).then(value => { if (current("sources", captured)) setMutationSets({ status: "ready", value }); })
      .catch(e => { if (current("sources", captured)) setMutationSets({ status: "error", message: errorText(e) }); });
  }

  function readSends() {
    const captured = stamp("sends");
    setSends(previous => previous.status === "ready" ? previous : { status: "loading" });
    api.jevSends(runId, readSignal()).then(value => {
      if (!current("sends", captured)) return;
      if (!jevSendListMatches(value)) throw new Error(RESPONSE_SHAPE_TEXT);
      setSends({ status: "ready", value });
    }).catch(e => { if (current("sends", captured)) setSends({ status: "error", message: errorText(e) }); });
  }

  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => { readStatus(); readSources(); readSends(); }, [runId]);

  // A listed send still in progress (e.g. started before a remount): the list and status are read again, reads only.
  const pending = sends.status === "ready" && jevSendsPending(sends.value);
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => { readSends(); readStatus(); }, JEV_POLL_MS);
    return () => window.clearInterval(timer);
  }, [pending]);

  // Candidate rows of the chosen set (ligand: M17 filter evaluated by the server, generation order; mutation: index order).
  const ligandKey = selection?.kind === "ligand" ? candidateRowsQuery(selection.source, applied, { sort: "generation_order",
    direction: "asc", offset, limit: CANDIDATE_PAGE_LIMIT, passesOnly }) : null;
  const mutationQuery = candidateQuery(EMPTY_CANDIDATE_FILTERS, offset);
  const mutationKey = selection?.kind === "mutation" ? `${selection.source}|${mutationQuery}` : null;
  useEffect(() => {
    if (ligandKey === null || selection === null) return;
    const key = ligandKey, handle = selection.source, captured = stamp("candidates");
    setLigandRows({ key, load: { status: "loading" } });
    api.ligandCandidateRows(runId, key, readSignal()).then(value => {
      if (!current("candidates", captured)) return;
      if (value.schema !== "ligand_candidate_page@1" || value.handle !== handle) throw new Error(RESPONSE_SHAPE_TEXT);
      setLigandRows({ key, load: { status: "ready", value } });
    }).catch(e => { if (current("candidates", captured))
      setLigandRows({ key, load: { status: "error", message: errorText(e) } }); });
  }, [ligandKey, rowsRetry]);
  useEffect(() => {
    if (mutationKey === null || selection === null) return;
    const key = mutationKey, handle = selection.source, captured = stamp("candidates");
    setMutationRows({ key, load: { status: "loading" } });
    api.mutationCandidates(runId, handle, mutationQuery, readSignal()).then(value => {
      if (!current("candidates", captured)) return;
      if (value.schema !== "mutation_candidate_page@1" || value.handle !== handle) throw new Error(RESPONSE_SHAPE_TEXT);
      setMutationRows({ key, load: { status: "ready", value } });
    }).catch(e => { if (current("candidates", captured))
      setMutationRows({ key, load: { status: "error", message: errorText(e) } }); });
  }, [mutationKey, rowsRetry]);
  /* eslint-enable react-hooks/exhaustive-deps */
  const ligandLoad = ligandRows && ligandRows.key === ligandKey ? ligandRows.load : null;
  const mutationLoad = mutationRows && mutationRows.key === mutationKey ? mutationRows.load : null;

  // ---- choices (any change of source, selection or applied filter withdraws the built body and its preview) ----
  function withdrawProjection() {
    seqs.current.projection += 1;
    seqs.current.preview += 1;
    live.current.projection = null;
    setProjection(null); setPreview(null); setBuild({ status: "idle" }); setConfirmedFor(null);
  }

  function resetCandidates() {
    setRefused(null); setFilterInput(emptyFilterInput()); setFilterErrors([]); setApplied(emptyAppliedFilter());
    setPassesOnly(false); setOffset(0); setLigandRows(null); setMutationRows(null);
  }

  function chooseKind(next: JevKind) {
    if (next === kind) return;
    live.current.source = null;
    setKind(next); setSelection(null); resetCandidates(); withdrawProjection();
  }

  function chooseSource(handle: string) {
    if (kind === null || selection?.source === handle) return;
    live.current.source = handle;
    setSelection(emptyJevSelection(kind, handle)); resetCandidates(); withdrawProjection();
  }

  function toggle(option: JevCandidateOption, checked: boolean) {
    if (selection === null) return;
    const out = toggleJevCandidate(selection, option, checked);
    setRefused(out.refused);
    if (out.selection !== selection) { setSelection(out.selection); withdrawProjection(); }
  }

  function applyFilters() {
    const check = checkFilterInput(filterInput);
    if (!check.ok) { setFilterErrors(check.errors); return; }
    setFilterErrors([]); setApplied({ spec: check.spec, bounds: check.bounds }); setOffset(0); withdrawProjection();
  }

  function clearFilters() {
    setFilterInput(emptyFilterInput()); setFilterErrors([]); setApplied(emptyAppliedFilter()); setOffset(0);
    withdrawProjection();
  }

  // ---- consent (the person's switch; turning it off is always possible) ----
  const statusValue = status.status === "ready" ? status.value : null;
  const statusView = statusValue ? jevStatusView(statusValue) : null;
  const switchReason = statusView ? consentSwitchDisabledReason(statusValue, !statusView.enabled) : null;

  async function changeConsent(next: boolean) {
    if (consentBusy || consentSwitchDisabledReason(statusValue, next) !== null) return;
    const captured = stamp("consent");
    setConsentBusy(true); setConsentError(null);
    try {
      const value = await api.jevSetConsent(runId, next, AbortSignal.timeout(TIMEOUT_MS));
      if (!current("consent", captured)) return;
      if (!jevStatusMatches(value)) throw new Error(RESPONSE_SHAPE_TEXT);
      seqs.current.status += 1;   // the answer is the new status: a status read in flight is superseded
      setStatus({ status: "ready", value });
      statusCallback.current?.(runId, value);
      if (live.current.projection) readPreview(live.current.projection);
    } catch (e) {
      if (!current("consent", captured)) return;
      setConsentError(errorText(e));
      readStatus();
    } finally { if (mounted.current) setConsentBusy(false); }
  }

  // ---- body (build_jev_projection) and its preview ----
  const filterSpec = selection?.kind === "ligand" ? applied.spec : null;
  const sending = inFlight !== null;
  const buildBlockers = jevBuildBlockers({ selection, filter: filterSpec, building: build.status === "loading", sending });

  async function buildProjection() {
    const check = jevProjectionArgs(selection, filterSpec);
    if (!check.ok || build.status === "loading" || sendingRef.current) return;
    withdrawProjection();
    const args = check.args, captured = stamp("projection");
    setBuild({ status: "loading" });
    try {
      const result = await api.buildJevProjection(runId, args, readSignal(LONG_TIMEOUT_MS));
      if (!current("projection", captured)) return;
      const outcome = jevProjectionOutcome(result);
      if (!outcome.ok) { setBuild({ status: "error", message: outcome.text }); return; }
      if (outcome.summary.source !== args.source) throw new Error(RESPONSE_SHAPE_TEXT);
      live.current.projection = outcome.handle;
      setProjection({ handle: outcome.handle, summary: outcome.summary });
      setBuild({ status: "ready", value: true });
      readPreview(outcome.handle);
    } catch (e) { if (current("projection", captured)) setBuild({ status: "error", message: errorText(e) }); }
  }

  function readPreview(handle: string) {
    const captured = stamp("preview");
    setPreview(previous => previous?.handle === handle && previous.load.status === "ready" ? previous
      : { handle, load: { status: "loading" } });
    api.jevPreview(runId, handle, readSignal()).then(value => {
      if (!current("preview", captured)) return;
      if (!jevPreviewMatches(value, handle)) throw new Error(RESPONSE_SHAPE_TEXT);
      setPreview({ handle, load: { status: "ready", value } });
    }).catch(e => { if (current("preview", captured))
      setPreview({ handle, load: { status: "error", message: errorText(e) } }); });
  }

  const previewLoad = projection && preview && preview.handle === projection.handle ? preview.load : null;
  const previewValue = previewLoad?.status === "ready" ? previewLoad.value : null;
  const confirmed = jevConfirmed(confirmedFor, previewValue);
  const sendBlockers = jevSendBlockers({ preview: previewValue, confirmed, sending });

  // ---- the one send: the person's approval of exactly the previewed body ----
  async function send() {
    if (sendingRef.current || previewValue === null || sendBlockers.length) return;
    const attempt = jevSendAttempt(attemptRef.current, previewValue);
    attemptRef.current = attempt;
    sendingRef.current = true;
    live.current.send = attempt.sendId;
    setInFlight(attempt.sendId); setPendingId(attempt.sendId); setSendError(null); setLastRecord(null);
    const captured = stamp("send");
    try {
      // No abort signal: the server bounds its one HTTP call; leaving the tab must not cut an approved send short.
      const record = await api.jevSend(runId, jevSendRequest(attempt));
      if (!current("send", captured)) return;
      if (!jevSendResponseMatches(record, attempt)) throw new Error(RESPONSE_SHAPE_TEXT);
      attemptRef.current = jevAttemptAfter(attempt, { record: true });
      setPendingId(null); setLastRecord(record); setConfirmedFor(null);
      openSend(record.send_id);
    } catch (e) {
      if (!current("send", captured)) return;
      const info = jevErrorInfo(e);
      attemptRef.current = jevAttemptAfter(attempt, { record: false, code: info.code });
      setPendingId(attemptRef.current?.sendId ?? null);
      setSendError(info.text);
    } finally {
      sendingRef.current = false;
      if (mounted.current) {
        live.current.send = null;
        setInFlight(null);
        readSends(); readStatus();
        if (live.current.projection) readPreview(live.current.projection);
      }
    }
  }

  // ---- results and reports ----
  function openSend(sendId: string) {
    live.current.detail = sendId;
    setOpened(sendId);
    const captured = stamp("detail");
    setDetail({ sendId, load: { status: "loading" } });
    api.jevSendDetail(runId, sendId, readSignal()).then(value => {
      if (!current("detail", captured)) return;
      if (!jevDetailMatches(value, sendId)) throw new Error(RESPONSE_SHAPE_TEXT);
      setDetail({ sendId, load: { status: "ready", value } });
    }).catch(e => { if (current("detail", captured))
      setDetail({ sendId, load: { status: "error", message: errorText(e) } }); });
  }

  async function makeReport(choiceHandle: string) {
    if (report?.load.status === "loading") return;
    live.current.report = choiceHandle;
    const captured = stamp("report");
    setReport({ handle: choiceHandle, load: { status: "loading" } });
    try {
      const artifact = await api.createJevReport(runId, choiceHandle, AbortSignal.timeout(LONG_TIMEOUT_MS));
      if (!jevReportMatches(artifact, choiceHandle)) throw new Error(RESPONSE_SHAPE_TEXT);
      onReportCreated(runId);   // saved even when this answer is no longer shown; the page checks the run
      if (current("report", captured)) setReport({ handle: choiceHandle, load: { status: "ready", value: artifact } });
    } catch (e) { if (current("report", captured))
      setReport({ handle: choiceHandle, load: { status: "error", message: errorText(e) } }); }
  }

  const panel = jevPanelState({ runId, capability: { available: true, reason: null }, status: statusValue,
    error: status.status === "error" ? status.message : null });
  const sourceLoad = kind === "ligand" ? ligandSets : kind === "mutation" ? mutationSets : null;
  const sourceOptions = kind === "ligand" && ligandSets.status === "ready" ? ligandSourceOptions(ligandSets.value)
    : kind === "mutation" && mutationSets.status === "ready" ? mutationSourceOptions(mutationSets.value) : [];
  const detailLoad = detail && detail.sendId === opened ? detail.load : null;
  const reportBusy = report?.load.status === "loading";
  const recordReason = lastRecord ? sendReasonText(lastRecord.status, lastRecord.reason_code) : null;

  return <section className="mw-jev" aria-label={JEV_PANEL_TITLE} data-testid="jev-panel" data-jev-state={panel.state}
    data-sending={sending}>
    <h2 className="mw-jev-heading">{JEV_PANEL_TITLE}</h2>

    <Section area="status" title={JEV_TEXT.areaStatus} state={status.status}>
      <div className="mw-jev-notice" data-testid="jev-consent-notice">
        {CONSENT_NOTICE.map((line, index) => <p key={index}>{line}</p>)}
      </div>
      <p className="mw-jev-note" data-testid="jev-note-u2">{JEV_SCREEN_NOTES.U2}</p>
      <p className="mw-jev-note" data-testid="jev-note-u3">{JEV_SCREEN_NOTES.U3}</p>
      <p className="mw-jev-note">{SCIENCE_BADGE_NOTE}</p>
      {(status.status === "idle" || status.status === "loading") && <Loading />}
      {status.status === "error" && <ErrorLine message={status.message} onRetry={readStatus} testId="jev-status-error" />}
      {statusView && <>
        <div className="mw-jev-inline">
          <label className="mw-jev-check" data-testid="jev-consent-label" data-consent={statusView.enabled ? "on" : "off"}
            data-disabled-reason={switchReason ?? undefined}>
            <input type="checkbox" role="switch" data-testid="jev-consent" aria-label={CONSENT_SWITCH_LABEL}
              checked={statusView.enabled} disabled={consentBusy || switchReason !== null}
              onChange={event => void changeConsent(event.target.checked)} />
            {statusView.switchText}</label>
          {consentBusy && <span className="mw-jev-note" aria-busy="true">{JEV_TEXT.consentBusy}</span>}
        </div>
        {switchReason && <p className="mw-jev-note" data-testid="jev-consent-blocked">{switchReason}</p>}
        {consentError && <ErrorLine message={consentError} testId="jev-consent-error" />}
        {statusView.notes.length > 0 && <ul className="mw-jev-list" data-testid="jev-status-notes">
          {statusView.notes.map(text => <li key={text}>{text}</li>)}</ul>}
        {statusView.capText !== null && <p data-testid="jev-cap" data-used={statusValue?.used}
          data-remaining={statusValue?.remaining}>{statusView.capText}</p>}
        {statusView.budgetText !== null && <p data-testid="jev-budget">{statusView.budgetText}</p>}
        <p className="mw-jev-note mw-mono" data-testid="jev-destination">{statusView.destinationText} · {statusView.modelText}</p>
      </>}
    </Section>

    <Section area="source" title={JEV_TEXT.areaSource} state={sourceLoad?.status}>
      <fieldset className="mw-jev-choices" data-testid="jev-kind">
        <legend>{JEV_TEXT.kindLegend}</legend>
        {KINDS.map(option => <label key={option} data-jev-kind={option}>
          <input type="radio" name={`jev-kind-${runId}`} data-testid={`jev-kind-${option}`} checked={kind === option}
            onChange={() => chooseKind(option)} /> {SOURCE_KIND_LABEL[option]}</label>)}
      </fieldset>
      {kind === null ? <p className="mw-jev-note">{JEV_TEXT.chooseKind}</p> : <>
        {sourceLoad?.status === "loading" && <Loading />}
        {sourceLoad?.status === "error" && <ErrorLine message={sourceLoad.message} onRetry={readSources}
          testId="jev-sources-error" />}
        {sourceLoad?.status === "ready" && (!sourceOptions.length ? <p className="mw-jev-note">{JEV_TEXT.noSets}</p>
          : <fieldset className="mw-jev-choices" data-testid="jev-sources">
            <legend>{JEV_TEXT.sourceLegend}</legend>
            {sourceOptions.map(option => <label key={option.handle} data-jev-source={option.handle}
              data-disabled-reason={option.disabledReason ?? undefined}>
              <input type="radio" name={`jev-source-${runId}`} data-testid="jev-source" data-jev-source={option.handle}
                checked={selection?.source === option.handle} disabled={option.disabledReason !== null}
                onChange={() => chooseSource(option.handle)} />
              <span className="mw-mono" title={option.handle}>{option.text} · {shortSha(option.handle)}</span>
              {option.disabledReason && <span className="mw-jev-note">{option.disabledReason}</span>}
            </label>)}
          </fieldset>)}
      </>}
      {sourceLoad?.status !== "loading" && <Button size="sm" data-testid="jev-sources-reload" onClick={readSources}>
        {JEV_TEXT.setsReload}</Button>}
    </Section>

    <Section area="candidates" title={JEV_TEXT.areaCandidates} state={(ligandLoad ?? mutationLoad)?.status}>
      {selection === null ? <p className="mw-jev-note">{NO_SOURCE_REASON}</p> : <>
        <p className="mw-jev-note">{JEV_TEXT.orderNote}</p>
        <p className="mw-jev-note" data-testid="jev-selection-count" data-selected={selection.items.length}>
          {jevSelectionCountText(selection)}</p>
        {selection.items.length >= JEV_MAX_CANDIDATES && <p className="mw-jev-note" role="status"
          data-testid="jev-selection-full">{SELECTION_FULL_REASON}</p>}
        {refused && <p className="mw-jev-unavailable" role="status" data-testid="jev-selection-refused">{refused}</p>}
        {selection.kind === "ligand" ? <>
          <p className="mw-jev-note">{JEV_TEXT.ligandFilterNote}</p>
          <FilterForm idPrefix="jev" input={filterInput} errors={filterErrors} applied={applied.spec}
            onInput={setFilterInput} onApply={applyFilters} onClear={clearFilters} />
          <label className="mw-jev-check"><input type="checkbox" data-testid="jev-passes-only" checked={passesOnly}
            onChange={event => { setPassesOnly(event.target.checked); setOffset(0); }} /> {JEV_TEXT.passesOnly}</label>
          {ligandLoad?.status === "loading" && <Loading text={JEV_TEXT.rowsLoading} />}
          {ligandLoad?.status === "error" && <ErrorLine message={ligandLoad.message}
            onRetry={() => setRowsRetry(value => value + 1)} testId="jev-candidates-error" />}
          {ligandLoad?.status === "ready" && <LigandTable page={ligandLoad.value} selection={selection} onToggle={toggle}
            onPage={setOffset} />}
        </> : <>
          {mutationLoad?.status === "loading" && <Loading text={JEV_TEXT.rowsLoading} />}
          {mutationLoad?.status === "error" && <ErrorLine message={mutationLoad.message}
            onRetry={() => setRowsRetry(value => value + 1)} testId="jev-candidates-error" />}
          {mutationLoad?.status === "ready" && <MutationTable page={mutationLoad.value} selection={selection}
            onToggle={toggle} onPage={setOffset} />}
        </>}
      </>}
    </Section>

    <Section area="build" title={JEV_TEXT.areaBuild} state={build.status}>
      <div className="mw-jev-inline">
        <Button size="sm" variant="primary" data-testid="jev-build" disabled={buildBlockers.length > 0}
          onClick={() => void buildProjection()}>{BUILD_BUTTON_TEXT}</Button>
        {build.status === "loading" && <span className="mw-jev-note" aria-busy="true">{JEV_TEXT.building}</span>}
      </div>
      {buildBlockers.length > 0 && <ul className="mw-jev-errors" data-testid="jev-build-blocked">
        {buildBlockers.map(text => <li key={text}>{text}</li>)}</ul>}
      {build.status === "error" && <ErrorLine message={build.message} testId="jev-build-error" />}
      {projection && <>
        <p className="mw-jev-note" data-testid="jev-projection" data-projection-handle={projection.handle}>
          {JEV_TEXT.projectionMade} · {projectionSummaryText(projection.summary)} · <code title={projection.handle}>
            {shortSha(projection.handle)}</code></p>
        {previewLoad?.status === "loading" && <Loading text={JEV_TEXT.previewLoading} />}
        {previewLoad?.status === "error" && <ErrorLine message={previewLoad.message}
          onRetry={() => readPreview(projection.handle)} testId="jev-preview-error" />}
        {previewValue && <PreviewView preview={previewValue} onReload={() => readPreview(projection.handle)} />}
      </>}
    </Section>

    <Section area="approval" title={JEV_TEXT.areaApproval} state={sending ? "loading" : undefined}>
      <label className="mw-jev-check">
        <input type="checkbox" data-testid="jev-confirm" checked={confirmed} disabled={previewValue === null || sending}
          onChange={event => setConfirmedFor(event.target.checked && previewValue ? previewValue.body_sha256 : null)} />
        {CONFIRM_CHECK_TEXT}</label>
      <div className="mw-jev-inline">
        <Button size="sm" variant="primary" data-testid="jev-send" disabled={sendBlockers.length > 0}
          data-send-id={pendingId ?? undefined} onClick={() => void send()}>{SEND_BUTTON_TEXT}</Button>
        {sending && <span className="mw-jev-note" aria-busy="true" data-testid="jev-sending">{JEV_TEXT.sendingNow}</span>}
      </div>
      {sendBlockers.length > 0 && <div data-testid="jev-send-blocked" data-count={sendBlockers.length}>
        <span className="mw-eyebrow">{JEV_TEXT.sendBlockers}</span>
        <ul className="mw-jev-errors">{sendBlockers.map(text => <li key={text}>{text}</li>)}</ul>
      </div>}
      {sendError && <ErrorLine message={sendError} testId="jev-send-error" />}
      {lastRecord && <p className="mw-jev-note" role="status" data-testid="jev-send-record" data-send-id={lastRecord.send_id}
        data-status={lastRecord.status} data-reason-code={lastRecord.reason_code ?? undefined}>
        {JEV_TEXT.sendRecorded}: {sendStatusText(lastRecord.status)}{recordReason ? ` · ${recordReason}` : ""} · {JEV_TEXT.sendId}{" "}
        <code>{lastRecord.send_id}</code></p>}
    </Section>

    <Section area="result" title={JEV_TEXT.areaResult} state={detailLoad?.status}>
      {opened === null ? <p className="mw-jev-note">{JEV_TEXT.resultNone}</p>
        : detailLoad?.status === "error" ? <ErrorLine message={detailLoad.message} onRetry={() => openSend(opened)}
          testId="jev-result-error" />
        : detailLoad?.status === "ready" ? <ResultView detail={detailLoad.value} reportBusy={reportBusy}
          onReport={handle => void makeReport(handle)} />
        : <Loading text={JEV_TEXT.resultLoading} />}
    </Section>

    <Section area="history" title={JEV_TEXT.areaHistory} state={sends.status}>
      <p className="mw-jev-note" data-testid="jev-note-u1">{JEV_SCREEN_NOTES.U1}</p>
      {(sends.status === "idle" || sends.status === "loading") && <Loading />}
      {sends.status === "error" && <ErrorLine message={sends.message} onRetry={readSends} testId="jev-sends-error" />}
      {sends.status === "ready" && (!sends.value.length ? <p className="mw-jev-note">{JEV_TEXT.noSends}</p>
        : <div className="mw-jev-table-wrap"><table className="mw-jev-table" data-testid="jev-sends">
          <thead><tr><th>{JEV_TEXT.headerApproved}</th><th>{JEV_TEXT.headerStatus}</th><th>{JEV_TEXT.headerKind}</th>
            <th>{JEV_TEXT.headerCount}</th><th>{JEV_TEXT.headerHash}</th><th>{JEV_TEXT.headerLate}</th>
            <th>{JEV_TEXT.headerActions}</th></tr></thead>
          <tbody>{jevSendRows(sends.value).map(row => {
            const choiceHandle = row.choiceHandle;
            return <tr key={row.sendId} data-jev-send={row.sendId} data-status={row.status} data-late={row.lateText !== null}
              data-opened={opened === row.sendId}>
              <td className="mw-mono">{row.approvedSeq}</td>
              <td>{row.statusText}{row.reasonText ? ` · ${row.reasonText}` : ""}</td>
              <td>{row.kindText}</td><td>{row.countText}</td><td className="mw-mono">{row.bodyHashText}</td>
              <td>{row.lateText ?? NULL_TEXT}</td>
              <td><div className="mw-jev-inline">
                {row.canOpen && <Button size="sm" data-testid="jev-send-open" data-send-id={row.sendId}
                  onClick={() => openSend(row.sendId)}>{JEV_TEXT.open}</Button>}
                {row.canReport && choiceHandle !== null && <Button size="sm" data-testid="jev-send-report"
                  data-choice-handle={choiceHandle} disabled={reportBusy}
                  onClick={() => void makeReport(choiceHandle)}>{JEV_TEXT.report}</Button>}
              </div></td>
            </tr>;
          })}</tbody>
        </table></div>)}
      {sends.status !== "loading" && <Button size="sm" data-testid="jev-sends-reload" onClick={readSends}>
        {JEV_TEXT.historyReload}</Button>}
      {report?.load.status === "loading" && <Loading text={JEV_TEXT.reportLoading} />}
      {report?.load.status === "ready" && <p className="mw-jev-note" role="status" data-testid="jev-report-done"
        data-report-handle={report.load.value.handle} data-choice-handle={report.handle}>
        {JEV_TEXT.reportDone} · <code title={report.load.value.handle}>{shortSha(report.load.value.handle)}</code></p>}
      {report?.load.status === "error" && <ErrorLine message={report.load.message} testId="jev-report-error" />}
    </Section>
  </section>;
}

function CandidateCheck({ selection, option, onToggle }: { selection: JevSelection; option: JevCandidateOption;
  onToggle: (option: JevCandidateOption, checked: boolean) => void }) {
  const checked = jevCandidateChecked(selection, option);
  const blocked = jevCandidateBlockedReason(selection, option);
  // A candidate the applied filter refuses can never be checked; at 20 the click is refused with its reason.
  const filteredOut = option.kind === "ligand" && option.passesAll === false && !checked;
  return <input type="checkbox" data-testid="jev-candidate" data-jev-candidate={String(option.key)}
    aria-label={`${JEV_TEXT.candidateCheck} ${option.key}`} checked={checked} disabled={filteredOut}
    title={blocked ?? undefined} onChange={event => onToggle(option, event.target.checked)} />;
}

function Pager({ offset, limit, shown, total, onPage, testId }: { offset: number; limit: number; shown: number;
  total: number; onPage: (offset: number) => void; testId: string }) {
  const last = offset + shown;
  return <div className="mw-jev-inline" data-testid={testId} data-offset={offset} data-total={total}>
    <Button size="sm" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}>{JEV_TEXT.previous}</Button>
    <Button size="sm" disabled={last >= total} onClick={() => onPage(last)}>{JEV_TEXT.next}</Button>
  </div>;
}

function LigandTable({ page, selection, onToggle, onPage }: { page: LigandCandidatePage; selection: JevSelection;
  onToggle: (option: JevCandidateOption, checked: boolean) => void; onPage: (offset: number) => void }) {
  const conflicts = jevFilterConflicts(selection, page.rows);
  return <div className="mw-jev-candidates">
    <p className="mw-jev-note" data-testid="jev-candidate-count" data-total={page.total}
      data-passing={page.passing ?? undefined} data-hidden={page.hidden_by_filter}>{candidateCountText(page)}</p>
    {conflicts.length > 0 && <p className="mw-jev-unavailable" role="status" data-testid="jev-filter-conflicts">
      {JEV_TEXT.conflictNote} <span className="mw-mono">{conflicts.join(", ")}</span></p>}
    {!page.rows.length ? <p className="mw-jev-note">{JEV_TEXT.noRows}</p> : <div className="mw-jev-table-wrap">
      <table className="mw-jev-table" data-testid="jev-candidates" data-kind="ligand">
        <thead><tr><th>{JEV_TEXT.headerPick}</th><th>{JEV_TEXT.headerOrder}</th><th>{JEV_TEXT.headerCandidateId}</th>
          <th>{JEV_TEXT.headerSmiles}</th><th>{JEV_TEXT.headerFilter}</th></tr></thead>
        <tbody>{page.rows.map(row => {
          const option = ligandCandidateOption(selection.source, row);
          return <tr key={row.candidate.id} data-jev-candidate-row={row.candidate.id}
            data-checked={jevCandidateChecked(selection, option)}
            data-blocked-reason={jevCandidateBlockedReason(selection, option) ?? undefined}
            data-passes-all={row.passes_all === null ? "null" : String(row.passes_all)}>
            <td><CandidateCheck selection={selection} option={option} onToggle={onToggle} /></td>
            <td className="mw-mono">{row.generation_order}</td><td className="mw-mono">{row.candidate.id}</td>
            <td className="mw-mono mw-jev-smiles">{row.candidate.smiles}</td><td>{passText(row.passes_all)}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>}
    <Pager offset={page.offset} limit={page.limit} shown={page.rows.length} total={page.matched} onPage={onPage}
      testId="jev-candidates-pager" />
  </div>;
}

function MutationTable({ page, selection, onToggle, onPage }: { page: MutationCandidatePage; selection: JevSelection;
  onToggle: (option: JevCandidateOption, checked: boolean) => void; onPage: (offset: number) => void }) {
  return <div className="mw-jev-candidates">
    <p className="mw-jev-note" data-testid="jev-candidate-count" data-total={page.total}>{pageRangeText(page)}</p>
    {!page.rows.length ? <p className="mw-jev-note">{JEV_TEXT.noRows}</p> : <div className="mw-jev-table-wrap">
      <table className="mw-jev-table" data-testid="jev-candidates" data-kind="mutation">
        <thead><tr><th>{JEV_TEXT.headerPick}</th><th>{JEV_TEXT.headerIndex}</th><th>{JEV_TEXT.headerPosition}</th>
          <th>{JEV_TEXT.headerResidue}</th><th>{JEV_TEXT.headerChange}</th></tr></thead>
        <tbody>{page.rows.map(row => {
          const option = mutationCandidateOption(selection.source, row);
          return <tr key={row.index} data-jev-candidate-row={row.index} data-checked={jevCandidateChecked(selection, option)}
            data-blocked-reason={jevCandidateBlockedReason(selection, option) ?? undefined}>
            <td><CandidateCheck selection={selection} option={option} onToggle={onToggle} /></td>
            <td className="mw-mono">{row.index}</td><td className="mw-mono">{row.position_index}</td>
            <td className="mw-mono">{residueText(row.residue)}</td><td className="mw-mono">{row.from}→{row.to}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>}
    <Pager offset={page.offset} limit={page.limit} shown={page.rows.length} total={page.total} onPage={onPage}
      testId="jev-candidates-pager" />
  </div>;
}

function PreviewView({ preview, onReload }: { preview: JevPreviewV1; onReload: () => void }) {
  const view = jevPreviewView(preview);
  return <div className="mw-jev-preview" data-testid="jev-preview" data-projection-handle={view.projectionHandle}
    data-body-sha256={view.bodySha256} data-body-bytes={preview.body_bytes} data-blocked={view.blocked.length > 0}>
    <dl className="mw-jev-facts">
      <dt>{JEV_TEXT.kind}</dt><dd>{view.kindText} · <code>{view.questionId}</code></dd>
      <dt>{JEV_TEXT.bytes}</dt><dd className="mw-mono" data-testid="jev-preview-bytes">{view.bodyBytesText}</dd>
      <dt>{JEV_TEXT.sha256}</dt><dd><code data-testid="jev-preview-sha256">{view.bodySha256}</code></dd>
    </dl>
    <details data-testid="jev-preview-body-details">
      <summary>{JEV_TEXT.bodySummary}</summary>
      <pre className="mw-jev-body" data-testid="jev-preview-body">{view.body}</pre>
    </details>
    <p className="mw-jev-note">{JEV_TEXT.question}</p>
    <p className="mw-jev-quote" data-testid="jev-preview-question">{view.instructions}</p>
    <p className="mw-jev-note">{ALIAS_TABLE_NOTE}</p>
    <div className="mw-jev-table-wrap"><table className="mw-jev-table" data-testid="jev-alias-table">
      <thead><tr><th>{JEV_TEXT.aliasAlias}</th><th>{JEV_TEXT.aliasLocal}</th><th>{JEV_TEXT.aliasSent}</th></tr></thead>
      <tbody>{view.aliasRows.map(row => <tr key={row.alias} data-alias={row.alias}>
        <td className="mw-mono">{row.alias}</td><td className="mw-mono">{row.localRefText}</td><td>{row.sentText}</td>
      </tr>)}</tbody>
    </table></div>
    <p data-testid="jev-preview-reservation">{view.reservationText}</p>
    <p data-testid="jev-preview-cap">{view.capText}</p>
    <p data-testid="jev-preview-budget">{view.budgetRemainingText}</p>
    <p data-testid="jev-preview-previous" data-previous-sends={preview.previous_sends}>{view.previousSendsText}</p>
    <div data-testid="jev-preview-blocked" data-count={view.blocked.length}>
      <span className="mw-eyebrow">{JEV_TEXT.serverBlockers}</span>
      {view.blocked.length ? <ul className="mw-jev-errors">{view.blocked.map(item => <li key={item.code}
        data-block-reason={item.code}>{item.text}</li>)}</ul>
        : <p className="mw-jev-note">{JEV_TEXT.noServerBlockers}</p>}
    </div>
    <div className="mw-jev-inline">
      <Button size="sm" data-testid="jev-preview-reload" onClick={onReload}>{JEV_TEXT.previewReload}</Button>
    </div>
  </div>;
}

function ResultView({ detail, reportBusy, onReport }: { detail: JevSendDetail; reportBusy: boolean;
  onReport: (choiceHandle: string) => void }) {
  const view = jevResultView(detail);
  if (view.state !== "completed") {
    const reason = view.state === "rejected" || view.state === "failed" ? view.reasonText
      : view.state === "invalid" ? view.message : null;
    return <p className={view.state === "in_progress" ? "mw-jev-note" : "mw-jev-unavailable"} role="status"
      data-testid="jev-result-reason" data-send-id={detail.send_id} data-status={detail.status}
      data-reason-code={detail.reason_code ?? undefined}>{view.statusText}{reason ? `: ${reason}` : ""}</p>;
  }
  const card = view.card;
  return <div className="mw-jev-card" data-testid="jev-result-card" data-send-id={card.sendId}
    data-choice-handle={card.choiceHandle} data-chosen-alias={card.chosenAlias} data-late={card.lateText !== null}>
    <p className="mw-jev-title">{card.label}</p>
    {card.lateText !== null && <p className="mw-jev-unavailable" role="status" data-testid="jev-result-late">
      {JEV_TEXT.lateMark}: {card.lateText}</p>}
    <dl className="mw-jev-facts">
      <dt>{JEV_TEXT.chosenAlias}</dt><dd className="mw-mono" data-testid="jev-result-alias">{card.chosenAlias}</dd>
      <dt>{JEV_TEXT.localRef}</dt><dd className="mw-mono">{card.localRefText}</dd>
      <dt>{JEV_TEXT.localDisplay}</dt><dd className="mw-mono" data-testid="jev-result-local">{card.localDisplayText}</dd>
      <dt>{card.confidenceLabel}</dt><dd className="mw-mono" data-testid="jev-result-confidence">{card.confidenceText}</dd>
      <dt>{JEV_TEXT.requestedModel}</dt><dd className="mw-mono">{card.requestedModel}</dd>
      <dt>{JEV_TEXT.servedModel}</dt><dd className="mw-mono" data-testid="jev-result-model">{card.servedModel}</dd>
      {card.usageRows.map(row => <Fragment key={row.key}><dt>{row.label}</dt>
        <dd className="mw-mono" data-usage={row.key}>{row.text}</dd></Fragment>)}
    </dl>
    <p className="mw-jev-note">{card.reasonText}</p>
    <details data-testid="jev-result-probabilities" data-reported={card.probabilitiesReported}>
      <summary>{JEV_TEXT.probabilities}</summary>
      <p className="mw-jev-note">{PROBABILITY_NOTE}</p>
      {card.probabilityText !== null ? <p className="mw-jev-note">{card.probabilityText}</p>
        : <ul className="mw-jev-list">{card.probabilityRows.map(row => <li key={row.alias} data-alias={row.alias}>
          <span className="mw-mono">{row.alias}</span> · {row.localRefText} · <span className="mw-mono">{row.text}</span>
        </li>)}</ul>}
    </details>
    <div data-testid="jev-result-limitations">
      <span className="mw-eyebrow">{JEV_TEXT.fixedSentences}</span>
      {card.limitations.map((text, index) => <p key={index} className="mw-jev-note" data-limitation={index}>{text}</p>)}
    </div>
    <div className="mw-jev-inline">
      <Button size="sm" data-testid="jev-result-report" data-choice-handle={card.choiceHandle} disabled={reportBusy}
        onClick={() => onReport(card.choiceHandle)}>{JEV_TEXT.report}</Button>
    </div>
  </div>;
}
