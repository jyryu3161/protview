"use client";

import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type RunSummary } from "@/lib/api";
import type { DockingAcknowledgementKey, DockingBoxSource, DockingPrerequisites, DockingReceptorInstances,
  DockingResultDetail, JevLoopBranch, JevLoopCapability, JevLoopComputeRequest, JevLoopListRow, JevLoopPreviewV1,
  JevLoopProjectionSummary, JevLoopRef, JevLoopReportArtifact, JevLoopSendDetail, JevLoopV1, JevSendV1, JevStatusV1,
  LigandCandidatePage, MutationCandidatePage, MutationCandidateSetListRow } from "@/lib/contracts";
import { ACKNOWLEDGEMENT_KEYS, ACKNOWLEDGEMENT_LABEL, BOX_FRAME_NOTE, BOX_SIDE_MAX_A, BOX_SIDE_MIN_A, BOX_SOURCES,
  boxSourceDisabledReason, boxSourceLabel, dockingSummaryRows, ENERGY_RANGE_MAX, ENERGY_RANGE_MIN, EXHAUSTIVENESS_MAX,
  EXHAUSTIVENESS_MIN, exactResidue, importsOfKind, MARGIN_MAX_A, MARGIN_MIN_A, modelInstances, modeTableCells,
  modeTableHeaders, nullResultText, NUM_MODES_MAX, NUM_MODES_MIN, parentSdfMissingReason, removedInstanceText,
  sameResidue, SEED_MAX, SEED_MIN, type DockingForm } from "@/lib/docking";
import { CONFIRM_CHECK_TEXT, CONSENT_SWITCH_LABEL, EMPTY_SOURCE_REASON, INVALID_SOURCE_REASON, JEV_TEXT, NULL_TEXT,
  RESPONSE_SHAPE_TEXT, REQUEST_FAILED_TEXT, SELECTION_FULL_REASON, SEND_BUTTON_TEXT, SOURCE_KIND_LABEL,
  consentSwitchDisabledReason, emptyJevSelection, jevAttemptAfter, jevCandidateBlockedReason, jevCandidateChecked,
  jevConfirmed, jevFilterConflicts, jevSendAttempt, jevSendRequest, jevSendResponseMatches, jevStatusMatches,
  jevStatusView, ligandCandidateOption, mutationCandidateOption, mutationSourceOptions, residueText, sendReasonText,
  sendStatusText, toggleJevCandidate, type JevCandidateOption, type JevSelection, type JevSendAttempt,
  type JevSourceOption } from "@/lib/jev";
import { BRANCH_LABEL, CANCEL_BEFORE_START_NOTE, FREE_DOCKING_NOTE, GOAL_LABEL, GOAL_MEANING, ITERATION_CAP_DEFAULT,
  ITERATION_CAP_MAX, ITERATION_CAP_MIN, LIST_POSITION_LABEL, LOOP_AREA_TITLE, LOOP_GOALS, LOOP_KIND_FOR_BRANCH,
  LOOP_MAX_POOL, LOOP_POLL_MS, LOOP_SCREEN_NOTES, LOOP_SEED_MAX, LOOP_SEED_MIN, LOOP_SEED_NOTE, ORDER_NOTE, POOL_FIXED_NOTE,
  PROTEIN_SCREEN_NOTE, PROTEIN_SEED_NOTE, SCORE_COLUMN_LABEL, SCORE_LABEL, initialLigandLoopSetupForm,
  initialLoopReadQueue, initialLoopSettings, initialProteinLoopSetupForm, jevLoopCanSend, jevLoopDetailMatches,
  jevLoopPreviewMatches, loopAwaitedSend, jevLoopPreviewView, jevLoopProjectionOutcome, jevLoopReportMatches, jevLoopSendBlockers, ligandLoopSetup,
  createReasonText, loopAbandonRequest, loopActionView, loopAriaSort, loopCandidateComputeRequest, loopCandidateRows,
  loopChoiceView, loopCreateAttempt, loopCreateAttemptAfter, loopCreateBlockedReason, loopCreateBody,
  loopCreateRefusal, loopCreateRequest, loopCurrentIteration, loopDockRequest, loopErrorInfo, loopIterationRows,
  loopIterationSelection, loopListRows, loopPanelState, loopPoolArgs, loopPoolCountText, loopProjectionArgs,
  loopProposalComputeRequest, loopReadRequest, loopReadSettled, loopRecordMatches, loopRecordReflectsSend,
  loopResponseCurrent, loopResumeRequest, loopSelectableCandidates,
  loopStatusView, loopSwitchBlockedReason, nextLoopSort, patchLigandLoopSetupForm, patchProteinLoopSetupForm,
  proteinLoopSetup, sortLoopCandidates, type LoopButtonState, type LoopChoiceView, type LoopCreateAttempt,
  type LoopCreateField, type LoopSettingsForm, type LoopSort, type LoopSortKey, type LoopStamp,
  type ProteinLoopSetupForm } from "@/lib/jev-loop";
import { CANDIDATE_PAGE_LIMIT, candidateCountText, candidateRowsQuery, checkFilterInput, emptyAppliedFilter,
  emptyFilterInput, LIGAND_APPROVAL_NOTICE, passText, type AppliedFilter, type LigandFilterInput } from "@/lib/ligand";
import { candidateQuery, catalyticBadge, EMPTY_CANDIDATE_FILTERS, pageRangeText } from "@/lib/mutations";
import { CONFIRMATION_LABEL, CONTACT_CUTOFF_DEFAULT_A, CONTACT_CUTOFF_RANGE_A } from "@/lib/mutation-model";
import { FilterForm } from "./LigandPanel";
import { PairInputs } from "./MutationModelPanel";
import { Button, shortSha } from "./primitives";

/**
 * M25 "JEV 루프" area (`.dryforge/spec.md` 2, 3, 4.5, 5.3, 6, 7, 8, 9.3, 10): mounted after the M22 GA area of the
 * 리간드 설계·탐색 tab (`branch="ligand"`) and after the M23 sequence GA area of the 단백질 공학 tab (`branch="protein"`).
 * Both branches share every part (loop list, progress, preview, approval, proposal card, candidate and iteration
 * tables, end, summary, report); only the create inputs and the candidate notation differ. Every number, state, phase,
 * need, shortfall, order, choice and sentence shown is the server's (`jev_loop@1`, the loop projection's
 * `jev_preview@1`, the send record with its `jev_loop_choice@1`, the stored M18 result detail); every decision and
 * wording of the area comes from `lib/jev-loop.ts` (and the M24 / M18 / M21 libs it reuses): nothing here computes a
 * score, an aggregate, a shortfall, an order or whether a candidate is computed.
 *
 * Mounting (entering the tab) only reads. Each write is one press of a person: create, the projection command, the
 * one send of an exactly previewed and confirmed body, a compute start (the server holds its answer until the job
 * ends; the record is read again every 2 s meanwhile), the first expensive-call approval and a cancel on the shared
 * job routes, abandon, end, a report and the consent switch (the same run-level `POST /jev/consent` as the 지식·보고서
 * tab; no per-loop consent). Nothing is chosen, opened, sent or started automatically. The page mounts it only while
 * its tab is shown and keys it by branch and run; late answers are applied only while run + opened loop + iteration +
 * per-area request number are all current (`loopResponseCurrent`). One loop is opened at a time.
 *
 * The M24 preview and approval markup is repeated here with `jev-loop-` test ids instead of being moved out of
 * `JevPanel`: that component's source and DOM are pinned by its unit tests (`tests/jev.test.cjs` compiles it with a
 * fixed import map and checks its source text), so it is left exactly as it was.
 */
export interface JevLoopPanelProps {
  branch: JevLoopBranch;
  /** Current run of the structure analysis screen (run selection lives only there); null when none. */
  run: RunSummary | null;
  /** `/capabilities` `methods.jev_loop` (per branch): undefined while capabilities are read, null when absent. */
  capability: JevLoopCapability | null | undefined;
  /** After a report was created: the page re-reads the report library (it drops another run's call). */
  onReportCreated: (runId: string) => void;
  /** Every science-send status this area reads or sets: the page's global "과학 전송 허용" mark follows it. */
  onStatus?: (runId: string, status: JevStatusV1) => void;
  /** M29: "보완 기록 열기" of a protein loop on a repaired structure (the page opens it in the repair area). */
  onOpenRepairRecord?: (runId: string, record: string) => void;
}

type Load<T> = { status: "idle" } | { status: "loading" } | { status: "ready"; value: T } | { status: "error"; message: string };
type Area = "status" | "consent" | "list" | "prereq" | "sets" | "rows" | "instances" | "create" | "detail" | "projection" |
  "preview" | "send" | "compute" | "approve" | "cancel" | "abandon" | "end" | "report" | "m18";
/** What a stamp of each area carries besides the run: the opened loop, and the current iteration for the steps. */
const AREA_SCOPE: Record<Area, "run" | "loop" | "iteration"> = { status: "run", consent: "run", list: "run",
  prereq: "run", sets: "run", rows: "run", instances: "run", create: "run", detail: "loop", projection: "iteration",
  preview: "iteration", send: "iteration", compute: "iteration", approve: "loop", cancel: "loop", abandon: "iteration",
  end: "loop", report: "loop", m18: "loop" };
const AREAS = Object.keys(AREA_SCOPE) as Area[];
const TIMEOUT_MS = 30000;
const LONG_TIMEOUT_MS = 120000;
const LIST_LIMIT = 100;
const AXES = ["x", "y", "z"] as const;
const CONSENT_SHARED_NOTE = "과학 전송 동의는 run 하나에 하나입니다. 지식·보고서 탭 JEV 판정 영역의 동의와 같으며 루프마다 따로 " +
  "켜지 않습니다. 동의만으로는 아무것도 보내지 않습니다.";
const PROTEIN_SDF_ONLY_REASON = "JEV 루프의 단백질 갈래는 가져온 3D SDF 리간드만 씁니다 (setup ligand.source = sdf).";
const COMPUTE_WAIT_NOTE = "작업이 끝날 때까지 이 요청은 응답을 기다립니다. 진행은 2초마다 루프 기록을 다시 읽어 보입니다(읽기만).";
const COMPUTE_ERROR_NOTE = "요청이 끝나지 않았거나 거절되었습니다. 루프 기록을 다시 읽어 실제 상태를 보입니다.";

function Section({ area, title, state, children }: { area: string; title: string; state?: string; children: ReactNode }) {
  return <section className="mw-jev-section" data-jev-loop-area={area} data-state={state} aria-label={title}>
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

/** The reasons a button is closed, from `loopActionView` (or the area's own guard), listed under it. */
function Reasons({ reasons, testId }: { reasons: readonly string[]; testId: string }) {
  if (!reasons.length) return null;
  return <ul className="mw-jev-errors" data-testid={testId} data-count={reasons.length}>
    {reasons.map(text => <li key={text}>{text}</li>)}</ul>;
}

export function JevLoopPanel(p: JevLoopPanelProps) {
  const runId = p.run?.run_id ?? null;
  const gate = loopPanelState({ runId, branch: p.branch, capability: p.capability });
  const title = `${LOOP_AREA_TITLE} · ${BRANCH_LABEL[p.branch]}`;
  if (p.run === null || gate.state === "unavailable" || p.capability === undefined || p.capability === null) {
    const reason = gate.state === "unavailable" ? gate.reason : null;
    return <section className="mw-jev mw-jev-loop" aria-label={title} data-testid="jev-loop-panel" data-branch={p.branch}
      data-jev-loop-state={reason === null ? "loading" : "unavailable"}>
      <h2 className="mw-jev-heading">{title}</h2>
      {reason !== null ? <p className="mw-jev-unavailable" role="status"
        data-testid={runId === null ? "jev-loop-no-run" : "jev-loop-unavailable"}
        data-reason-code={p.capability?.[p.branch]?.reason_code ?? undefined}><b>{JEV_TEXT.unavailable}</b>: {reason}</p>
        : <Loading text={JEV_TEXT.loadingCapability} />}
    </section>;
  }
  return <LoopWorkspace branch={p.branch} run={p.run} capability={p.capability} title={title}
    onReportCreated={p.onReportCreated} onStatus={p.onStatus} onOpenRepairRecord={p.onOpenRepairRecord} />;
}

function LoopWorkspace({ branch, run, capability, title, onReportCreated, onStatus, onOpenRepairRecord }: {
  branch: JevLoopBranch; run: RunSummary; capability: JevLoopCapability; title: string;
  onReportCreated: (runId: string) => void; onStatus?: (runId: string, status: JevStatusV1) => void;
  onOpenRepairRecord?: (runId: string, record: string) => void }) {
  const runId = run.run_id;
  const kind = LOOP_KIND_FOR_BRANCH[branch];
  // ---- run-wide reads ----
  const [status, setStatus] = useState<Load<JevStatusV1>>({ status: "idle" });
  /** Number of status answers applied so far; a preview keeps the number it was read at (`laterStatus`). */
  const statusTick = useRef(0);
  const [statusAt, setStatusAt] = useState(0);
  const [consentBusy, setConsentBusy] = useState(false);
  const [consentError, setConsentError] = useState<string | null>(null);
  const [list, setList] = useState<Load<JevLoopListRow[]>>({ status: "idle" });
  const [prereq, setPrereq] = useState<Load<DockingPrerequisites>>({ status: "idle" });
  const [prereqReload, setPrereqReload] = useState(0);
  const [sets, setSets] = useState<Load<MutationCandidateSetListRow[]>>({ status: "idle" });
  const [setsReload, setSetsReload] = useState(0);
  // ---- the create form (pool, goal, loop seed, iteration cap, computation setup) ----
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
  const [settings, setSettings] = useState<LoopSettingsForm>(initialLoopSettings);
  const [ligandSetup, setLigandSetup] = useState<DockingForm>(initialLigandLoopSetupForm);
  const [proteinSetup, setProteinSetup] = useState<ProteinLoopSetupForm>(initialProteinLoopSetupForm);
  const [instances, setInstances] = useState<{ handle: string; load: Load<DockingReceptorInstances> } | null>(null);
  const [creating, setCreating] = useState(false);
  const [createRefusal, setCreateRefusal] = useState<{ field: LoopCreateField; reasonCode: string | null;
    text: string } | null>(null);
  // ---- the opened loop ----
  const [openedId, setOpenedId] = useState<string | null>(null);
  const [record, setRecord] = useState<{ loopId: string; load: Load<JevLoopV1> } | null>(null);
  const [recordError, setRecordError] = useState<string | null>(null);
  const [projection, setProjection] = useState<{ loopId: string; iteration: number; handle: string;
    summary: JevLoopProjectionSummary } | null>(null);
  const [build, setBuild] = useState<Load<true>>({ status: "idle" });
  const [preview, setPreview] = useState<{ handle: string; load: Load<JevLoopPreviewV1>; statusAt: number } | null>(null);
  const [confirmedFor, setConfirmedFor] = useState<string | null>(null);
  /** The send id of the one send in flight (null = none). */
  const [inFlight, setInFlight] = useState<string | null>(null);
  /** The send id an unanswered attempt keeps for its retry (shown on the button). */
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [lastRecord, setLastRecord] = useState<JevSendV1 | null>(null);
  /** The last send answered with a record: the loop record is read again until it shows that send ended. */
  const [awaitedSend, setAwaitedSend] = useState<{ sendId: string; status: string } | null>(null);
  /** Send details of the opened loop by send id: the iteration's JEV selection and the sends a person opened. */
  const [details, setDetails] = useState<Record<string, Load<JevLoopSendDetail>>>({});
  const [openedSend, setOpenedSend] = useState<string | null>(null);
  const [computeConfirmedFor, setComputeConfirmedFor] = useState<string | null>(null);
  const [designated, setDesignated] = useState<JevLoopRef | null>(null);
  const [computeBusy, setComputeBusy] = useState(false);
  const [computeError, setComputeError] = useState<string | null>(null);
  const [jobBusy, setJobBusy] = useState(false);
  const [jobNotice, setJobNotice] = useState<string | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState<"abandon" | "end" | null>(null);
  const [actionError, setActionError] = useState<{ action: "abandon" | "end"; text: string } | null>(null);
  const [sort, setSort] = useState<LoopSort>(null);
  const [m18, setM18] = useState<{ handle: string; load: Load<DockingResultDetail> } | null>(null);
  const [report, setReport] = useState<{ handle: string; load: Load<JevLoopReportArtifact> } | null>(null);

  const mounted = useRef(true);
  const readAbort = useRef<AbortController | null>(null);
  const seqs = useRef(Object.fromEntries(AREAS.map(area => [area, 0])) as Record<Area, number>);
  /** Request numbers of the send detail reads, one counter per send id (two reads never drop each other). */
  const detailSeqs = useRef<Record<string, number>>({});
  const live = useRef({ loopId: null as string | null, iteration: null as number | null });
  /** One record read at a time; a request while one is in flight is kept and read once more (`loopReadRequest`). */
  const readQueue = useRef(initialLoopReadQueue());
  const sendingRef = useRef(false);
  const computeRef = useRef(false);
  const attemptRef = useRef<JevSendAttempt | null>(null);
  const createAttempt = useRef<LoopCreateAttempt | null>(null);
  const statusCallback = useRef(onStatus);
  statusCallback.current = onStatus;
  const recordValue = record && record.loopId === openedId && record.load.status === "ready" ? record.load.value : null;
  live.current = { loopId: openedId, iteration: recordValue?.current.iteration ?? null };
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    readAbort.current = controller;
    const counters = seqs.current;
    return () => { mounted.current = false; controller.abort(); for (const area of AREAS) counters[area] += 1; };
  }, []);
  const liveStamp = (area: Area, seq: number): LoopStamp => ({ runId,
    loopId: AREA_SCOPE[area] === "run" ? null : live.current.loopId,
    iteration: AREA_SCOPE[area] === "iteration" ? live.current.iteration : null, seq });
  const stamp = (area: Area): LoopStamp => liveStamp(area, ++seqs.current[area]);
  const current = (area: Area, captured: LoopStamp) => mounted.current &&
    loopResponseCurrent(captured, liveStamp(area, seqs.current[area]));
  /** Reads end with the mount (leaving the tab) or after the time limit. */
  const readSignal = (ms = TIMEOUT_MS) =>
    AbortSignal.any([readAbort.current?.signal ?? new AbortController().signal, AbortSignal.timeout(ms)]);
  function errorText(e: unknown): string {
    if (e instanceof Error && e.message === RESPONSE_SHAPE_TEXT) return `${REQUEST_FAILED_TEXT}: ${RESPONSE_SHAPE_TEXT}`;
    return loopErrorInfo(e, branch).text;
  }

  // ---- reads (entering the tab reads the status, the loop list and the inputs; nothing is chosen or sent) ----
  function applyStatus(value: JevStatusV1) {
    statusTick.current += 1;
    setStatusAt(statusTick.current);
    setStatus({ status: "ready", value });
    statusCallback.current?.(runId, value);
  }

  function readStatus() {
    const captured = stamp("status");
    setStatus(previous => previous.status === "ready" ? previous : { status: "loading" });
    api.jevStatus(runId, readSignal()).then(value => {
      if (!current("status", captured)) return;
      if (!jevStatusMatches(value)) throw new Error(RESPONSE_SHAPE_TEXT);
      applyStatus(value);
    }).catch(e => { if (current("status", captured)) setStatus({ status: "error", message: errorText(e) }); });
  }

  function readList() {
    const captured = stamp("list");
    setList(previous => previous.status === "ready" ? previous : { status: "loading" });
    api.jevLoops(runId, readSignal()).then(value => {
      if (!current("list", captured)) return;
      if (!Array.isArray(value) || !value.every(row => typeof row?.loop_id === "string")) throw new Error(RESPONSE_SHAPE_TEXT);
      setList({ status: "ready", value });
    }).catch(e => { if (current("list", captured)) setList({ status: "error", message: errorText(e) }); });
  }

  function applyRecord(loopId: string, value: JevLoopV1) {
    seqs.current.detail += 1;   // a record read still in flight is older than this answer
    setRecord({ loopId, load: { status: "ready", value } });
    setRecordError(null);
  }

  function readRecord(loopId = live.current.loopId) {
    if (loopId === null || loopId !== live.current.loopId) return;   // only the opened loop's record is read
    const request = loopReadRequest(readQueue.current, loopId);
    readQueue.current = request.queue;
    if (!request.start) return;   // kept: read once more as soon as the read in flight ends (never skipped)
    const captured = stamp("detail");
    setRecord(previous => previous?.loopId === loopId ? previous : { loopId, load: { status: "loading" } });
    api.jevLoop(runId, loopId, readSignal()).then(value => {
      if (!current("detail", captured)) return;
      if (!loopRecordMatches(value, loopId) || value.branch !== branch) throw new Error(RESPONSE_SHAPE_TEXT);
      setRecord({ loopId, load: { status: "ready", value } });
      setRecordError(null);
    }).catch(e => {
      if (!current("detail", captured)) return;
      const message = errorText(e);
      setRecordError(message);
      setRecord(previous => previous?.loopId === loopId && previous.load.status === "ready" ? previous
        : { loopId, load: { status: "error", message } });
    }).finally(() => {
      const settled = loopReadSettled(readQueue.current, loopId, live.current.loopId);
      readQueue.current = settled.queue;
      if (settled.again !== null && mounted.current) readRecord(settled.again);
    });
  }

  function readDetail(sendId: string) {
    const loopId = live.current.loopId;
    if (loopId === null) return;
    const seq = (detailSeqs.current[sendId] ?? 0) + 1;
    detailSeqs.current[sendId] = seq;
    const captured: LoopStamp = { runId, loopId, iteration: null, seq };
    const isCurrent = () => mounted.current && loopResponseCurrent(captured,
      { runId, loopId: live.current.loopId, iteration: null, seq: detailSeqs.current[sendId] ?? 0 });
    setDetails(previous => ({ ...previous,
      [sendId]: previous[sendId]?.status === "ready" ? previous[sendId] : { status: "loading" } }));
    api.jevSendDetail(runId, sendId, readSignal()).then((value: unknown) => {
      if (!isCurrent()) return;
      if (!jevLoopDetailMatches(value, sendId, loopId)) throw new Error(RESPONSE_SHAPE_TEXT);
      setDetails(previous => ({ ...previous, [sendId]: { status: "ready", value } }));
    }).catch(e => { if (isCurrent()) setDetails(previous => ({ ...previous,
      [sendId]: { status: "error", message: errorText(e) } })); });
  }

  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => { readStatus(); readList(); }, [runId]);

  // Inputs of the create form: the docking imports and (ligand) the candidate sets with their parent SDFs.
  useEffect(() => {
    const captured = stamp("prereq");
    setPrereq({ status: "loading" });
    api.dockingPrerequisites(runId, readSignal()).then(value => {
      if (!current("prereq", captured)) return;
      if (value.schema !== "docking_prerequisites@1") throw new Error(RESPONSE_SHAPE_TEXT);
      setPrereq({ status: "ready", value });
    }).catch(e => { if (current("prereq", captured)) setPrereq({ status: "error", message: errorText(e) }); });
  }, [runId, prereqReload]);

  // Protein: this run's M20 candidate sets (every page; nothing is chosen).
  useEffect(() => {
    if (branch !== "protein") return;
    const captured = stamp("sets"), signal = readSignal();
    setSets({ status: "loading" });
    (async () => {
      const first = await api.mutationCandidateSets(runId, 0, LIST_LIMIT, signal);
      if (first.schema !== "mutation_candidate_set_list@1") throw new Error(RESPONSE_SHAPE_TEXT);
      const rows = [...first.rows];
      while (rows.length < first.total) {
        const page = await api.mutationCandidateSets(runId, rows.length, LIST_LIMIT, signal);
        if (page.schema !== first.schema || page.total !== first.total || !page.rows.length) throw new Error(RESPONSE_SHAPE_TEXT);
        rows.push(...page.rows);
      }
      return rows;
    })().then(rows => { if (current("sets", captured)) setSets({ status: "ready", value: rows }); })
      .catch(e => { if (current("sets", captured)) setSets({ status: "error", message: errorText(e) }); });
  }, [runId, setsReload]);

  // Candidate rows of the chosen set (ligand: M17 filter evaluated by the server, generation order; mutation: index).
  const ligandKey = selection?.kind === "ligand" ? candidateRowsQuery(selection.source, applied, { sort: "generation_order",
    direction: "asc", offset, limit: CANDIDATE_PAGE_LIMIT, passesOnly }) : null;
  const mutationQuery = candidateQuery(EMPTY_CANDIDATE_FILTERS, offset);
  const mutationKey = selection?.kind === "mutation" ? `${selection.source}|${mutationQuery}` : null;
  useEffect(() => {
    if (ligandKey === null || selection === null) return;
    const key = ligandKey, handle = selection.source, captured = stamp("rows");
    setLigandRows({ key, load: { status: "loading" } });
    api.ligandCandidateRows(runId, key, readSignal()).then(value => {
      if (!current("rows", captured)) return;
      if (value.schema !== "ligand_candidate_page@1" || value.handle !== handle) throw new Error(RESPONSE_SHAPE_TEXT);
      setLigandRows({ key, load: { status: "ready", value } });
    }).catch(e => { if (current("rows", captured)) setLigandRows({ key, load: { status: "error", message: errorText(e) } }); });
  }, [ligandKey, rowsRetry]);
  useEffect(() => {
    if (mutationKey === null || selection === null) return;
    const key = mutationKey, handle = selection.source, captured = stamp("rows");
    setMutationRows({ key, load: { status: "loading" } });
    api.mutationCandidates(runId, handle, mutationQuery, readSignal()).then(value => {
      if (!current("rows", captured)) return;
      if (value.schema !== "mutation_candidate_page@1" || value.handle !== handle) throw new Error(RESPONSE_SHAPE_TEXT);
      setMutationRows({ key, load: { status: "ready", value } });
    }).catch(e => { if (current("rows", captured)) setMutationRows({ key, load: { status: "error", message: errorText(e) } }); });
  }, [mutationKey, rowsRetry]);

  // Ligand: the instances of the chosen receptor import (a selection aid; the server checks the choice again).
  const receptorHandle = branch === "ligand" ? ligandSetup.receptorHandle : null;
  useEffect(() => {
    if (!receptorHandle) return;
    const handle = receptorHandle, captured = stamp("instances");
    setInstances({ handle, load: { status: "loading" } });
    api.dockingReceptorInstances(runId, handle, readSignal()).then(value => {
      if (!current("instances", captured)) return;
      if (value.schema !== "docking_receptor_instances@1" || value.handle !== handle) throw new Error(RESPONSE_SHAPE_TEXT);
      setInstances({ handle, load: { status: "ready", value } });
    }).catch(e => { if (current("instances", captured)) setInstances({ handle, load: { status: "error", message: errorText(e) } }); });
  }, [receptorHandle]);
  /* eslint-enable react-hooks/exhaustive-deps */
  const ligandLoad = ligandRows && ligandRows.key === ligandKey ? ligandRows.load : null;
  const mutationLoad = mutationRows && mutationRows.key === mutationKey ? mutationRows.load : null;

  // ---- derived state of the opened loop ----
  const statusValue = status.status === "ready" ? status.value : null;
  const sending = inFlight !== null;
  const busy = creating || build.status === "loading" || sending || computeBusy || jobBusy || actionBusy !== null ||
    consentBusy || report?.load.status === "loading";
  const switchBlocked = loopSwitchBlockedReason(busy);
  const listRows = list.status === "ready" ? list.value : null;
  const selectionRef = recordValue && recordValue.status === "active" && recordValue.current.action === "compute"
    ? loopIterationSelection(loopCurrentIteration(recordValue)) : null;
  const selectionLoad = selectionRef ? details[selectionRef.sendId] : undefined;
  const selectionView: LoopChoiceView | null = selectionLoad?.status === "ready" && recordValue
    ? loopChoiceView(selectionLoad.value, recordValue) : null;
  // The chosen candidate of the iteration's JEV selection, read from its proposal (undefined = not read yet).
  const proposalRef: JevLoopRef | null | undefined = selectionRef === null || selectionLoad === undefined ||
    selectionLoad.status === "idle" || selectionLoad.status === "loading" ? undefined
    : selectionLoad.status === "error" ? null
      : selectionView?.state === "completed" && selectionView.card.isSelection &&
        selectionView.card.proposalHandle === selectionRef.proposalHandle ? selectionView.card.ref : null;
  const view = recordValue ? loopActionView(recordValue, { busy, proposalRef }) : null;

  /* eslint-disable react-hooks/exhaustive-deps */
  // The iteration's JEV selection is read (its proposal names the chosen candidate); a read only.
  useEffect(() => { if (selectionRef && details[selectionRef.sendId] === undefined) readDetail(selectionRef.sendId); },
    [openedId, selectionRef?.sendId]);

  // While a job of the opened loop waits or runs, a compute answer is held, or a science send is in flight, the record
  // (and, for a send, the status) is read again: reads only; nothing is written or started by the timer.
  const sendPolling = sending || statusValue?.send_in_progress === true;
  const pollStatus = useRef(sendPolling);
  pollStatus.current = sendPolling;
  // A send that answered is followed until the record shows it ended (a status read saying no send is in progress does
  // not stop the reads before that).
  const sendUnseen = awaitedSend !== null && recordValue !== null &&
    !loopRecordReflectsSend(recordValue, awaitedSend.sendId, awaitedSend.status);
  const pollNeeded = recordValue !== null && recordValue.status === "active" &&
    (recordValue.current.action === "wait_job" || computeBusy || sendPolling || sendUnseen);
  useEffect(() => {
    if (!pollNeeded) return;
    const timer = window.setInterval(() => { readRecord(); if (pollStatus.current) readStatus(); }, LOOP_POLL_MS);
    return () => window.clearInterval(timer);
  }, [pollNeeded, openedId]);
  /* eslint-enable react-hooks/exhaustive-deps */

  // ---- consent (the run-level switch; turning it off is always possible) ----
  const statusView = statusValue ? jevStatusView(statusValue) : null;
  const switchReason = statusView ? consentSwitchDisabledReason(statusValue, !statusView.enabled) : null;
  const projectionShown = projection !== null && recordValue !== null && projection.loopId === recordValue.loop_id &&
    recordValue.status === "active" && recordValue.current.action === "select" &&
    projection.iteration === recordValue.current.iteration ? projection : null;

  async function changeConsent(next: boolean) {
    if (consentBusy || consentSwitchDisabledReason(statusValue, next) !== null) return;
    const captured = stamp("consent");
    setConsentBusy(true); setConsentError(null);
    try {
      const value = await api.jevSetConsent(runId, next, AbortSignal.timeout(TIMEOUT_MS));
      if (!current("consent", captured)) return;
      if (!jevStatusMatches(value)) throw new Error(RESPONSE_SHAPE_TEXT);
      seqs.current.status += 1;   // the answer is the new status: a status read in flight is superseded
      applyStatus(value);
      if (projectionShown) readPreview(projectionShown.handle);
    } catch (e) {
      if (!current("consent", captured)) return;
      setConsentError(errorText(e));
      readStatus();
    } finally { if (mounted.current) setConsentBusy(false); }
  }

  // ---- the create form ----
  const prereqValue = prereq.status === "ready" ? prereq.value : null;
  const ligandSets = prereqValue?.candidate_sets ?? [];
  const sourceOptions: JevSourceOption[] = branch === "ligand"
    ? ligandSets.map(set => ({ handle: set.handle,
      text: `${SOURCE_KIND_LABEL.ligand} · ${set.candidates === null ? `후보 수 ${NULL_TEXT}` : `후보 ${set.candidates}개`}`,
      disabledReason: !set.valid ? INVALID_SOURCE_REASON : set.candidates === 0 ? EMPTY_SOURCE_REASON : null }))
    : sets.status === "ready" ? mutationSourceOptions(sets.value) : [];
  const sourceLoad: Load<unknown> = branch === "ligand" ? prereq : sets;
  const chosenSet = branch === "ligand" ? ligandSets.find(set => set.handle === selection?.source) ?? null : null;
  const filterSpec = selection?.kind === "ligand" ? applied.spec : null;
  const conflicts = selection && ligandLoad?.status === "ready" ? jevFilterConflicts(selection, ligandLoad.value.rows) : [];
  const poolCheck = loopPoolArgs(branch, selection, filterSpec, conflicts);
  const setupCheck = branch === "ligand" ? ligandLoopSetup(ligandSetup, selection?.source ?? null)
    : proteinLoopSetup(proteinSetup);
  const createCheck = loopCreateRequest({ branch, pool: poolCheck, settings, setup: setupCheck });
  const createBlocked = listRows ? loopCreateBlockedReason(listRows, branch) : null;
  const dryRunReason = run.dry_run ? createReasonText("dry_run") : null;
  // The create button opens only with every field accepted, no unended loop of this branch, a real run and the list read.
  const createDisabled = !createCheck.ok || createBlocked !== null || dryRunReason !== null || listRows === null || busy;
  const fieldErrors = (field: LoopCreateField): string[] => createCheck.ok ? [] : createCheck.fields[field];

  function resetCandidates() {
    setRefused(null); setFilterInput(emptyFilterInput()); setFilterErrors([]); setApplied(emptyAppliedFilter());
    setPassesOnly(false); setOffset(0); setLigandRows(null); setMutationRows(null);
  }

  function chooseSource(handle: string) {
    if (selection?.source === handle) return;
    setSelection(emptyJevSelection(kind, handle)); resetCandidates(); setCreateRefusal(null);
    if (branch === "ligand") setLigandSetup(previous => patchLigandLoopSetupForm(previous, { parentSdfHandle: null }));
  }

  function toggle(option: JevCandidateOption, checked: boolean) {
    if (selection === null) return;
    const out = toggleJevCandidate(selection, option, checked);
    setRefused(out.refused);
    if (out.selection !== selection) setSelection(out.selection);
  }

  function applyFilters() {
    const check = checkFilterInput(filterInput);
    if (!check.ok) { setFilterErrors(check.errors); return; }
    setFilterErrors([]); setApplied({ spec: check.spec, bounds: check.bounds }); setOffset(0);
  }

  function clearFilters() {
    setFilterInput(emptyFilterInput()); setFilterErrors([]); setApplied(emptyAppliedFilter()); setOffset(0);
  }

  const updateLigand = (patch: Partial<DockingForm>) =>
    setLigandSetup(previous => patchLigandLoopSetupForm(previous, patch));
  const updateProtein = (patch: Partial<ProteinLoopSetupForm>) =>
    setProteinSetup(previous => patchProteinLoopSetupForm(previous, patch));

  async function createLoop() {
    if (!createCheck.ok || createDisabled) return;
    const request = createCheck.request;
    const attempt = loopCreateAttempt(createAttempt.current, request);
    createAttempt.current = attempt;
    setCreating(true); setCreateRefusal(null);
    const captured = stamp("create");
    try {
      const value: unknown = await api.createJevLoop(runId, loopCreateBody(attempt, request),
        AbortSignal.timeout(TIMEOUT_MS));
      if (!current("create", captured)) return;
      if (!loopRecordMatches(value, attempt.loopId)) throw new Error(RESPONSE_SHAPE_TEXT);
      createAttempt.current = loopCreateAttemptAfter(attempt, { record: true });
      showLoop(value.loop_id, value);   // the loop this press created
      readList();
    } catch (e) {
      if (!current("create", captured)) return;
      const refusal = e instanceof Error && e.message === RESPONSE_SHAPE_TEXT
        ? { field: "general" as const, reasonCode: null, text: errorText(e) } : loopCreateRefusal(e, branch);
      createAttempt.current = loopCreateAttemptAfter(attempt, { record: false,
        code: refusal.reasonCode ?? loopErrorInfo(e, branch).code });
      setCreateRefusal(refusal);
    } finally { if (mounted.current) setCreating(false); }
  }

  // ---- open one loop (one at a time) ----
  function resetLoopState() {
    for (const area of AREAS) if (AREA_SCOPE[area] !== "run") seqs.current[area] += 1;
    detailSeqs.current = {};
    attemptRef.current = null;
    setProjection(null); setBuild({ status: "idle" }); setPreview(null); setConfirmedFor(null); setPendingId(null);
    setSendError(null); setLastRecord(null); setAwaitedSend(null); setDetails({}); setOpenedSend(null);
    setComputeConfirmedFor(null);
    setDesignated(null); setComputeError(null); setJobNotice(null); setJobError(null); setActionError(null);
    setSort(null); setM18(null); setReport(null); setRecordError(null);
  }

  function showLoop(loopId: string, value: JevLoopV1 | null) {
    if (loopId !== openedId) resetLoopState();
    live.current = { loopId, iteration: value?.current.iteration ?? null };
    setOpenedId(loopId);
    if (value !== null) applyRecord(loopId, value);
    else readRecord(loopId);
  }

  function openLoop(loopId: string) {
    if (loopId !== openedId && switchBlocked) return;
    showLoop(loopId, null);
  }

  // ---- the loop projection (build_jev_loop_projection) and its preview ----
  function withdrawProjection() {
    seqs.current.projection += 1;
    seqs.current.preview += 1;
    setProjection(null); setPreview(null); setBuild({ status: "idle" }); setConfirmedFor(null);
  }

  async function buildProjection() {
    if (recordValue === null || view === null || !view.buttons.build.enabled || sendingRef.current) return;
    const args = loopProjectionArgs(recordValue);
    if (args === null) return;
    withdrawProjection();
    const captured = stamp("projection");
    setBuild({ status: "loading" });
    try {
      const result = await api.buildJevLoopProjection(runId, args, readSignal(LONG_TIMEOUT_MS));
      if (!current("projection", captured)) return;
      const outcome = jevLoopProjectionOutcome(result, branch);
      if (!outcome.ok) { setBuild({ status: "error", message: outcome.text }); return; }
      if (outcome.summary.loop_id !== args.loop_id || outcome.summary.iteration !== args.iteration)
        throw new Error(RESPONSE_SHAPE_TEXT);
      setProjection({ loopId: args.loop_id, iteration: args.iteration, handle: outcome.handle, summary: outcome.summary });
      setBuild({ status: "ready", value: true });
      readPreview(outcome.handle);
    } catch (e) { if (current("projection", captured)) setBuild({ status: "error", message: errorText(e) }); }
  }

  function readPreview(handle: string) {
    const loopId = live.current.loopId;
    if (loopId === null) return;
    const captured = stamp("preview");
    setPreview(previous => previous?.handle === handle && previous.load.status === "ready" ? previous
      : { handle, load: { status: "loading" }, statusAt: statusTick.current });
    api.jevPreview(runId, handle, readSignal()).then((value: unknown) => {
      if (!current("preview", captured)) return;
      if (!jevLoopPreviewMatches(value, handle, loopId)) throw new Error(RESPONSE_SHAPE_TEXT);
      setPreview({ handle, load: { status: "ready", value }, statusAt: statusTick.current });
    }).catch(e => { if (current("preview", captured))
      setPreview({ handle, load: { status: "error", message: errorText(e) }, statusAt: statusTick.current }); });
  }

  const previewLoad = projectionShown && preview && preview.handle === projectionShown.handle ? preview.load : null;
  const previewValue = previewLoad?.status === "ready" ? previewLoad.value : null;
  // A status answer applied after the preview arrived (e.g. the polling saw the other send end): only it can mark the
  // preview's send_in_progress as stale; the preview itself is re-read only when the person presses its button.
  const laterStatus = previewValue !== null && preview !== null && statusValue !== null && statusAt > preview.statusAt
    ? statusValue : null;
  const confirmed = jevConfirmed(confirmedFor, previewValue);
  const sendBlockers = jevLoopSendBlockers({ preview: previewValue, confirmed, sending, laterStatus });
  const canSend = jevLoopCanSend({ preview: previewValue, confirmed, sending, laterStatus });

  // ---- the one send: the person's approval of exactly the previewed loop body (the M24 send route) ----
  async function sendLoopBody() {
    if (sendingRef.current || previewValue === null || !canSend) return;
    const attempt = jevSendAttempt(attemptRef.current, previewValue);
    attemptRef.current = attempt;
    sendingRef.current = true;
    setInFlight(attempt.sendId); setPendingId(attempt.sendId); setSendError(null); setLastRecord(null);
    const captured = stamp("send");
    try {
      // No abort signal: the server bounds its one HTTP call; leaving the tab must not cut an approved send short.
      const sent = await api.jevSend(runId, jevSendRequest(attempt));
      if (!current("send", captured)) return;
      if (!jevSendResponseMatches(sent, attempt)) throw new Error(RESPONSE_SHAPE_TEXT);
      attemptRef.current = jevAttemptAfter(attempt, { record: true });
      setPendingId(null); setLastRecord(sent); setConfirmedFor(null);
      setAwaitedSend(loopAwaitedSend(sent));
      setOpenedSend(sent.send_id);
      readDetail(sent.send_id);
    } catch (e) {
      if (!current("send", captured)) return;
      const info = loopErrorInfo(e, branch);
      attemptRef.current = jevAttemptAfter(attempt, { record: false, code: info.code });
      setPendingId(attemptRef.current?.sendId ?? null);
      setSendError(errorText(e));
    } finally {
      sendingRef.current = false;
      if (mounted.current) {
        setInFlight(null);
        readStatus(); readRecord(); readList();
        if (projectionShown) readPreview(projectionShown.handle);
      }
    }
  }

  function openSend(sendId: string) {
    setOpenedSend(sendId);
    readDetail(sendId);
  }

  // ---- compute, the first expensive-call approval, cancel, abandon, end (each a person's press) ----
  const computeKey = recordValue ? `${recordValue.loop_id}|${recordValue.current.iteration}|` +
    `${recordValue.current.action}|${recordValue.current.step}` : null;
  const computeConfirmed = computeKey !== null && computeConfirmedFor === computeKey;
  const confirmReason = computeConfirmed ? [] : ["계산 시작 확인 체크를 켜세요."];
  const selectable = recordValue ? loopSelectableCandidates(recordValue) : [];
  const designatedRow = selectable.find(row => row.ref === designated) ?? null;

  async function computeWith(body: JevLoopComputeRequest | null) {
    const loopId = live.current.loopId;
    if (body === null || loopId === null || computeRef.current) return;
    computeRef.current = true;
    setComputeBusy(true); setComputeError(null); setJobNotice(null); setJobError(null);
    const captured = stamp("compute");
    try {
      // No abort signal: the server holds the answer until the job ends; leaving the tab must not cut a started step.
      const value: unknown = await api.jevLoopCompute(runId, loopId, body);
      if (!current("compute", captured)) return;
      if (!loopRecordMatches(value, loopId)) throw new Error(RESPONSE_SHAPE_TEXT);
      applyRecord(loopId, value);
    } catch (e) {
      if (current("compute", captured)) setComputeError(errorText(e));
    } finally {
      computeRef.current = false;
      if (mounted.current) {
        setComputeBusy(false); setComputeConfirmedFor(null);
        if (live.current.loopId === loopId) readRecord(loopId);
        readList();
      }
    }
  }

  function computeProposal() {
    if (recordValue === null || view === null || selectionRef === null || !view.buttons.computeProposal.enabled ||
      !computeConfirmed) return;
    void computeWith(loopProposalComputeRequest(recordValue, selectionRef.proposalHandle));
  }

  function computeDesignated() {
    if (recordValue === null || view === null || designatedRow === null || !view.buttons.designate.enabled ||
      !computeConfirmed) return;
    void computeWith(loopCandidateComputeRequest(recordValue, designatedRow.ref));
  }

  function computeDock() {
    if (recordValue === null || view === null || !view.buttons.dock.enabled || !computeConfirmed) return;
    void computeWith(loopDockRequest(recordValue));
  }

  /** The same step again for its waiting job (after the first expensive-call approval): the server's idempotent path. */
  function resumeJob() {
    if (recordValue === null || view === null || !view.buttons.startJob.enabled) return;
    void computeWith(loopResumeRequest(recordValue));
  }

  // The run's first expensive computation is approved on the shared job route (M7 way), only after the server asked.
  async function approveFirstCall() {
    if (view === null || view.approvalGuide === null || busy) return;
    const loopId = live.current.loopId, captured = stamp("approve");
    setJobBusy(true); setJobError(null); setJobNotice(null);
    try {
      await api.approveOpenmm(runId);
      if (!current("approve", captured)) return;
      setJobNotice(LIGAND_APPROVAL_NOTICE);
    } catch (e) { if (current("approve", captured)) setJobError(errorText(e)); }
    finally { if (mounted.current) { setJobBusy(false); if (loopId) readRecord(loopId); } }
  }

  async function cancelJob() {
    const job = recordValue?.current.job ?? null;
    if (job === null || view === null || !view.buttons.cancelJob.enabled) return;
    const loopId = live.current.loopId, captured = stamp("cancel");
    setJobBusy(true); setJobError(null); setJobNotice(null);
    try {
      await api.cancelJob(runId, job.job_id);
      if (!current("cancel", captured)) return;
    } catch (e) { if (current("cancel", captured)) setJobError(errorText(e)); }
    finally { if (mounted.current) { setJobBusy(false); if (loopId) readRecord(loopId); readList(); } }
  }

  async function abandonDocking() {
    const loopId = live.current.loopId;
    const body = recordValue ? loopAbandonRequest(recordValue) : null;
    if (loopId === null || body === null || view === null || !view.buttons.abandon.enabled) return;
    const captured = stamp("abandon");
    setActionBusy("abandon"); setActionError(null);
    try {
      const value: unknown = await api.jevLoopAbandonDocking(runId, loopId, body, AbortSignal.timeout(TIMEOUT_MS));
      if (!current("abandon", captured)) return;
      if (!loopRecordMatches(value, loopId)) throw new Error(RESPONSE_SHAPE_TEXT);
      applyRecord(loopId, value);
    } catch (e) { if (current("abandon", captured)) setActionError({ action: "abandon", text: errorText(e) }); }
    finally { if (mounted.current) { setActionBusy(null); readList(); } }
  }

  async function endLoop() {
    const loopId = live.current.loopId;
    if (loopId === null || view === null || !view.buttons.end.enabled) return;
    const captured = stamp("end");
    setActionBusy("end"); setActionError(null);
    try {
      const value: unknown = await api.jevLoopEnd(runId, loopId, AbortSignal.timeout(LONG_TIMEOUT_MS));
      if (!current("end", captured)) return;
      if (!loopRecordMatches(value, loopId)) throw new Error(RESPONSE_SHAPE_TEXT);
      applyRecord(loopId, value);
    } catch (e) { if (current("end", captured)) setActionError({ action: "end", text: errorText(e) }); }
    finally { if (mounted.current) { setActionBusy(null); readList(); } }
  }

  // ---- results: the stored M18 detail of a candidate this loop computed, the summary report ----
  function openResult(handle: string) {
    const captured = stamp("m18");
    setM18({ handle, load: { status: "loading" } });
    api.dockingResult(runId, handle, readSignal()).then(value => {
      if (!current("m18", captured)) return;
      if (value.schema !== "docking_result_detail@1" || value.handle !== handle) throw new Error(RESPONSE_SHAPE_TEXT);
      setM18({ handle, load: { status: "ready", value } });
    }).catch(e => { if (current("m18", captured)) setM18({ handle, load: { status: "error", message: errorText(e) } }); });
  }

  async function makeReport() {
    const statusOfLoop = recordValue ? loopStatusView(recordValue) : null;
    const handle = statusOfLoop?.resultHandle ?? null;
    if (handle === null || statusOfLoop?.reportBlockedReason !== null || report?.load.status === "loading") return;
    const captured = stamp("report");
    setReport({ handle, load: { status: "loading" } });
    try {
      const artifact = await api.createJevLoopReport(runId, handle, AbortSignal.timeout(LONG_TIMEOUT_MS));
      if (!jevLoopReportMatches(artifact, handle)) throw new Error(RESPONSE_SHAPE_TEXT);
      onReportCreated(runId);   // saved even when this answer is no longer shown; the page checks the run
      if (current("report", captured)) setReport({ handle, load: { status: "ready", value: artifact } });
    } catch (e) { if (current("report", captured)) setReport({ handle, load: { status: "error", message: errorText(e) } }); }
  }

  // ---- render ----
  const panel = loopPanelState({ runId, branch, capability, rows: listRows,
    error: list.status === "error" ? list.message : null });
  const loopRows = listRows ? loopListRows(listRows, branch) : [];
  const recordLoad = record && record.loopId === openedId ? record.load : null;
  const statusOfLoop = recordValue ? loopStatusView(recordValue) : null;
  const active = recordValue?.status === "active";
  const openedLoad = openedSend !== null && openedSend !== selectionRef?.sendId ? details[openedSend] : undefined;

  return <section className="mw-jev mw-jev-loop" aria-label={title} data-testid="jev-loop-panel" data-branch={branch}
    data-jev-loop-state={panel.state} data-busy={busy}>
    <h2 className="mw-jev-heading">{title}</h2>
    {panel.state === "failed" && <ErrorLine message={panel.message} onRetry={readList} testId="jev-loop-failure" />}

    <Section area="status" title="① 과학 전송 동의 (이 run)" state={status.status}>
      <p className="mw-jev-note" data-testid="jev-loop-note-ul1">{LOOP_SCREEN_NOTES.UL1}</p>
      <p className="mw-jev-note" data-testid="jev-loop-note-ul3">{LOOP_SCREEN_NOTES.UL3}</p>
      {branch === "protein" && <p className="mw-jev-note" data-testid="jev-loop-note-u3">{PROTEIN_SCREEN_NOTE}</p>}
      <p className="mw-jev-note" data-testid="jev-loop-consent-note">{CONSENT_SHARED_NOTE}</p>
      {(status.status === "idle" || status.status === "loading") && <Loading />}
      {status.status === "error" && <ErrorLine message={status.message} onRetry={readStatus} testId="jev-loop-status-error" />}
      {statusView && <>
        <div className="mw-jev-inline">
          <label className="mw-jev-check" data-testid="jev-loop-consent-label" data-consent={statusView.enabled ? "on" : "off"}
            data-disabled-reason={switchReason ?? undefined}>
            <input type="checkbox" role="switch" data-testid="jev-loop-consent" aria-label={CONSENT_SWITCH_LABEL}
              checked={statusView.enabled} disabled={consentBusy || switchReason !== null}
              onChange={event => void changeConsent(event.target.checked)} />
            {statusView.switchText}</label>
          {consentBusy && <span className="mw-jev-note" aria-busy="true">{JEV_TEXT.consentBusy}</span>}
        </div>
        {switchReason && <p className="mw-jev-note" data-testid="jev-loop-consent-blocked">{switchReason}</p>}
        {consentError && <ErrorLine message={consentError} testId="jev-loop-consent-error" />}
        {statusView.notes.length > 0 && <ul className="mw-jev-list" data-testid="jev-loop-status-notes">
          {statusView.notes.map(text => <li key={text}>{text}</li>)}</ul>}
        {statusView.capText !== null && <p data-testid="jev-loop-cap" data-used={statusValue?.used}
          data-remaining={statusValue?.remaining}>{statusView.capText}</p>}
        {statusView.budgetText !== null && <p data-testid="jev-loop-budget">{statusView.budgetText}</p>}
      </>}
    </Section>

    <Section area="create" title="② 루프 만들기" state={creating ? "loading" : undefined}>
      <p className="mw-jev-note">{POOL_FIXED_NOTE}</p>
      {createBlocked && <p className="mw-jev-unavailable" role="status" data-testid="jev-loop-create-blocked">{createBlocked}</p>}
      {dryRunReason && <p className="mw-jev-unavailable" role="status" data-testid="jev-loop-dry-run">{dryRunReason}</p>}

      <div className="mw-jev-loop-field" data-jev-loop-field="pool">
        <span className="mw-eyebrow">풀 (후보 집합 하나, 후보 2–20개, 자동으로 고르지 않음)</span>
        {sourceLoad.status === "loading" && <Loading />}
        {sourceLoad.status === "error" && <ErrorLine message={sourceLoad.message} testId="jev-loop-sources-error"
          onRetry={() => branch === "ligand" ? setPrereqReload(value => value + 1) : setSetsReload(value => value + 1)} />}
        {sourceLoad.status === "ready" && (!sourceOptions.length
          ? <p className="mw-jev-unavailable" role="status" data-testid="jev-loop-no-sets"><b>{JEV_TEXT.unavailable}</b>:{" "}
            {branch === "ligand" ? "이 run에 리간드 후보 집합이 없습니다. 위 리간드 후보 영역에서 먼저 만드세요."
              : "이 run에 변이 후보 집합이 없습니다. 위 변이 후보 영역에서 먼저 만드세요."}</p>
          : <fieldset className="mw-jev-choices" data-testid="jev-loop-sources">
            <legend>{SOURCE_KIND_LABEL[kind]} (자동으로 고르지 않음)</legend>
            {sourceOptions.map(option => {
              // M26: a mutation set whose catalytic check is not `checked` carries the shared mark and its own detail.
              const badge = branch === "protein" && sets.status === "ready"
                ? catalyticBadge(sets.value.find(row => row.handle === option.handle)?.catalytic_status) : null;
              return <label key={option.handle} data-jev-loop-source={option.handle}
                data-disabled-reason={option.disabledReason ?? undefined}>
                <input type="radio" name={`jev-loop-source-${branch}-${runId}`} data-testid="jev-loop-source"
                  data-jev-loop-source={option.handle} checked={selection?.source === option.handle}
                  disabled={option.disabledReason !== null} onChange={() => chooseSource(option.handle)} />
                <span className="mw-mono" title={option.handle}>{option.text} · {shortSha(option.handle)}</span>
                {option.disabledReason && <span className="mw-jev-note">{option.disabledReason}</span>}
                {badge && <span className="mw-catalytic-mark" data-testid="jev-loop-source-catalytic">
                  <span className="mw-catalytic-badge">{badge.text}</span>
                  <span className="mw-catalytic-detail" data-testid="jev-loop-source-catalytic-detail">{badge.detail}</span></span>}
                {branch === "protein" && sets.status === "ready" &&
                  sets.value.find(row => row.handle === option.handle)?.structure_origin &&
                  <span className="mw-catalytic-mark" data-testid="jev-loop-source-repaired">
                    <span className="mw-catalytic-badge">보완 구조</span></span>}
              </label>;
            })}
          </fieldset>)}
        {sourceLoad.status !== "loading" && <Button size="sm" data-testid="jev-loop-sources-reload"
          onClick={() => branch === "ligand" ? setPrereqReload(value => value + 1) : setSetsReload(value => value + 1)}>
          {JEV_TEXT.setsReload}</Button>}
        {selection !== null && <>
          <p className="mw-jev-note" data-testid="jev-loop-pool-count" data-selected={selection.items.length}>
            {loopPoolCountText(selection)}</p>
          {selection.items.length >= LOOP_MAX_POOL && <p className="mw-jev-note" role="status" data-testid="jev-loop-pool-full">
            {SELECTION_FULL_REASON}</p>}
          {refused && <p className="mw-jev-unavailable" role="status" data-testid="jev-loop-pool-refused">{refused}</p>}
          {selection.kind === "ligand" ? <>
            <p className="mw-jev-note">{JEV_TEXT.ligandFilterNote}</p>
            <FilterForm idPrefix="jev-loop" input={filterInput} errors={filterErrors} applied={applied.spec}
              onInput={setFilterInput} onApply={applyFilters} onClear={clearFilters} />
            <label className="mw-jev-check"><input type="checkbox" data-testid="jev-loop-passes-only" checked={passesOnly}
              onChange={event => { setPassesOnly(event.target.checked); setOffset(0); }} /> {JEV_TEXT.passesOnly}</label>
            {ligandLoad?.status === "loading" && <Loading text={JEV_TEXT.rowsLoading} />}
            {ligandLoad?.status === "error" && <ErrorLine message={ligandLoad.message}
              onRetry={() => setRowsRetry(value => value + 1)} testId="jev-loop-candidates-error" />}
            {ligandLoad?.status === "ready" && <LigandTable page={ligandLoad.value} selection={selection} onToggle={toggle}
              onPage={setOffset} />}
          </> : <>
            {mutationLoad?.status === "loading" && <Loading text={JEV_TEXT.rowsLoading} />}
            {mutationLoad?.status === "error" && <ErrorLine message={mutationLoad.message}
              onRetry={() => setRowsRetry(value => value + 1)} testId="jev-loop-candidates-error" />}
            {mutationLoad?.status === "ready" && <MutationTable page={mutationLoad.value} selection={selection}
              onToggle={toggle} onPage={setOffset} />}
          </>}
        </>}
        <FieldErrors field="pool" errors={fieldErrors("pool")} refusal={createRefusal} />
      </div>

      <div className="mw-jev-loop-field" data-jev-loop-field="goal">
        <fieldset className="mw-jev-choices" data-testid="jev-loop-goal">
          <legend>목표 (루프 내내 고정, 자동으로 고르지 않음)</legend>
          {LOOP_GOALS.map(goal => <label key={goal} data-jev-loop-goal={goal}>
            <input type="radio" name={`jev-loop-goal-${branch}-${runId}`} data-testid={`jev-loop-goal-${goal}`}
              checked={settings.goal === goal} onChange={() => setSettings(previous => ({ ...previous, goal }))} />
            <b>{GOAL_LABEL[goal]}</b> <span className="mw-jev-note">{GOAL_MEANING[goal]}</span></label>)}
        </fieldset>
        <FieldErrors field="goal" errors={fieldErrors("goal")} refusal={createRefusal} />
      </div>

      <div className="mw-jev-loop-field mw-jev-loop-grid">
        <div data-jev-loop-field="loop_seed">
          <label className="mw-jev-check">루프 seed (필수, {LOOP_SEED_MIN}–{LOOP_SEED_MAX})
            <input className="mw-ligand-input" data-testid="jev-loop-seed" inputMode="numeric" value={settings.loopSeed}
              onChange={event => setSettings(previous => ({ ...previous, loopSeed: event.target.value }))} /></label>
          <p className="mw-jev-note">{LOOP_SEED_NOTE}</p>
          <FieldErrors field="loop_seed" errors={fieldErrors("loop_seed")} refusal={createRefusal} />
        </div>
        <div data-jev-loop-field="iteration_cap">
          <label className="mw-jev-check">반복 상한 ({ITERATION_CAP_MIN}–{ITERATION_CAP_MAX}, 기본 {ITERATION_CAP_DEFAULT})
            <input className="mw-ligand-input" data-testid="jev-loop-iteration-cap" inputMode="numeric"
              value={settings.iterationCap}
              onChange={event => setSettings(previous => ({ ...previous, iterationCap: event.target.value }))} /></label>
          <p className="mw-jev-note">유효 반복 상한은 서버가 반복 상한과 풀 크기 가운데 작은 값으로 정합니다.</p>
          <FieldErrors field="iteration_cap" errors={fieldErrors("iteration_cap")} refusal={createRefusal} />
        </div>
      </div>

      <div className="mw-jev-loop-field" data-jev-loop-field="setup">
        <span className="mw-eyebrow">계산 조건 (루프 내내 고정)</span>
        <p className="mw-jev-note" data-testid="jev-loop-free-note">{FREE_DOCKING_NOTE}</p>
        {prereq.status === "loading" && <Loading />}
        {prereq.status === "error" && <ErrorLine message={prereq.message} testId="jev-loop-prereq-error"
          onRetry={() => setPrereqReload(value => value + 1)} />}
        {branch === "ligand"
          ? <LigandSetupInputs form={ligandSetup} update={updateLigand} runId={runId} prereq={prereqValue}
            chosenSet={chosenSet} hasSource={selection !== null}
            instances={instances && instances.handle === ligandSetup.receptorHandle ? instances.load : null}
            onReloadPrereq={() => setPrereqReload(value => value + 1)} />
          : <ProteinSetupInputs form={proteinSetup} update={updateProtein} runId={runId} prereq={prereq}
            onReloadPrereq={() => setPrereqReload(value => value + 1)} />}
        <FieldErrors field="setup" errors={fieldErrors("setup")} refusal={createRefusal} />
      </div>

      <FieldErrors field="general" errors={fieldErrors("general")} refusal={createRefusal} />
      <div className="mw-jev-inline">
        <Button size="sm" variant="primary" data-testid="jev-loop-create"
          disabled={createDisabled} onClick={() => void createLoop()}>루프 만들기</Button>
        {creating && <span className="mw-jev-note" aria-busy="true" data-testid="jev-loop-creating">루프를 만드는 중</span>}
        {listRows === null && <span className="mw-jev-note" data-testid="jev-loop-create-wait">루프 목록을 읽은 뒤 만들 수
          있습니다.</span>}
      </div>
    </Section>

    <Section area="loops" title="③ 이 run의 JEV 루프" state={list.status}>
      {(list.status === "idle" || list.status === "loading") && <Loading />}
      {panel.state === "empty" && <p className="mw-jev-note" data-testid="jev-loop-none">{panel.message}</p>}
      {loopRows.length > 0 && <fieldset className="mw-jev-choices" data-testid="jev-loop-list">
        <legend>루프 (최신 순, 자동으로 열지 않음, 한 번에 하나)</legend>
        {loopRows.map(row => <label key={row.loopId} data-loop-id={row.loopId} data-active={row.active}
          data-disabled-reason={row.loopId !== openedId && switchBlocked ? switchBlocked : undefined}>
          <input type="radio" name={`jev-loop-open-${branch}-${runId}`} data-testid="jev-loop-open"
            data-loop-id={row.loopId} checked={openedId === row.loopId}
            disabled={row.loopId !== openedId && switchBlocked !== null} onChange={() => openLoop(row.loopId)} />
          <span>{row.text}</span>
          {listRows?.find(item => item.loop_id === row.loopId)?.structure_origin &&
            <span className="mw-catalytic-mark" data-testid="jev-loop-list-repaired">
              <span className="mw-catalytic-badge">보완 구조</span></span>}</label>)}
      </fieldset>}
      {switchBlocked && openedId !== null && loopRows.length > 1 &&
        <p className="mw-jev-note" data-testid="jev-loop-switch-blocked">{switchBlocked}</p>}
      {list.status !== "loading" && <Button size="sm" data-testid="jev-loop-list-reload" onClick={readList}>
        루프 목록 다시 읽기</Button>}
      {openedId === null && loopRows.length > 0 && <p className="mw-jev-note">진행하거나 볼 루프를 위 목록에서 고르세요.</p>}
      {openedId !== null && recordLoad?.status === "loading" && <Loading text="루프 기록을 읽는 중" />}
      {openedId !== null && recordLoad?.status === "error" && <ErrorLine message={recordLoad.message}
        onRetry={() => readRecord(openedId)} testId="jev-loop-record-error" />}
    </Section>

    {recordValue && view && statusOfLoop && <>
      <Section area="progress" title="④ 루프 진행">
        {recordValue.structure_origin && <div className="mw-jev-note" role="status" data-testid="jev-loop-repair-origin"
          data-repair-record={recordValue.structure_origin.repair_record}
          data-repaired-structure={recordValue.structure_origin.repaired_structure}>
          <span className="mw-catalytic-badge">보완 구조</span>
          {recordValue.structure_origin.statements.map(item => <p key={item.id} data-statement={item.id}>{item.text}</p>)}
          <p className="mw-mono">보완 기록 {shortSha(recordValue.structure_origin.repair_record)} · 원본{" "}
            {shortSha(recordValue.structure_origin.source_structure)}</p>
          {onOpenRepairRecord && <Button size="sm" data-testid="jev-loop-repair-origin-open"
            onClick={() => recordValue.structure_origin &&
              onOpenRepairRecord(runId, recordValue.structure_origin.repair_record)}>보완 기록 열기</Button>}
        </div>}
        <div className="mw-jev-loop-record" data-testid="jev-loop-record" data-loop-id={recordValue.loop_id}
          data-status={recordValue.status} data-action={view.action} data-phase={recordValue.current.phase ?? undefined}
          data-iteration={view.iteration ?? undefined} data-step={recordValue.current.step ?? undefined}
          data-goal={recordValue.goal}>
          <dl className="mw-jev-facts">
            <dt>상태</dt><dd data-testid="jev-loop-status">{view.statusText}</dd>
            <dt>목표</dt><dd>{GOAL_LABEL[recordValue.goal]} · {GOAL_MEANING[recordValue.goal]}</dd>
            <dt>진행</dt><dd data-testid="jev-loop-progress">{view.progressText}</dd>
            <dt>지금 바퀴</dt><dd data-testid="jev-loop-iteration">{view.iterationText}</dd>
            <dt>바퀴 단계</dt><dd data-testid="jev-loop-phase">{view.phaseText ?? NULL_TEXT}</dd>
            <dt>계산 단계</dt><dd>{view.stepText ?? NULL_TEXT}</dd>
            <dt>다음 동작</dt><dd data-testid="jev-loop-action">{view.actionText}</dd>
          </dl>
          {view.exhaustedText && <p className="mw-jev-unavailable" role="status" data-testid="jev-loop-exhausted">
            {view.exhaustedText}</p>}
        </div>
        {active && <AxisTable rows={view.axisRows} testId="jev-loop-axes" />}
        <Reasons reasons={view.computeBlockedTexts} testId="jev-loop-compute-blocked" />
        <Reasons reasons={view.sendBlockedTexts} testId="jev-loop-send-blocked-axes" />
        {view.jobText !== null && <div className="mw-jev-loop-job" data-testid="jev-loop-job"
          data-job-id={recordValue.current.job?.job_id} data-job-status={recordValue.current.job?.status}
          data-start-blocked={recordValue.current.job?.start_blocked ?? undefined}>
          <p className="mw-jev-note mw-mono">{view.jobText}</p>
          {view.approvalGuide && <p className="mw-jev-unavailable" role="status" data-testid="jev-loop-approval-guide">
            {view.approvalGuide}</p>}
          {view.cancelNote && <p className="mw-jev-note" data-testid="jev-loop-cancel-note">{view.cancelNote}</p>}
          <div className="mw-jev-inline">
            {view.approvalGuide && <Button size="sm" data-testid="jev-loop-approve-first" disabled={busy}
              onClick={() => void approveFirstCall()}>비싼 계산 승인</Button>}
            <ButtonWithReasons state={view.buttons.startJob} testId="jev-loop-job-start" label="작업 시작"
              onPress={resumeJob} />
            <ButtonWithReasons state={view.buttons.cancelJob} testId="jev-loop-job-cancel" label="작업 취소"
              onPress={() => void cancelJob()} />
          </div>
        </div>}
        {computeBusy && <p className="mw-jev-note" aria-busy="true" data-testid="jev-loop-computing">{COMPUTE_WAIT_NOTE}</p>}
        {jobNotice && <p className="mw-jev-note" role="status" data-testid="jev-loop-job-notice">{jobNotice}</p>}
        {jobError && <ErrorLine message={jobError} testId="jev-loop-job-error" />}
        {computeError && <ErrorLine message={`${computeError} · ${COMPUTE_ERROR_NOTE}`} testId="jev-loop-compute-error" />}
        {recordError && <ErrorLine message={recordError} onRetry={() => readRecord(recordValue.loop_id)}
          testId="jev-loop-record-reread-error" />}
        <div className="mw-jev-inline">
          <Button size="sm" data-testid="jev-loop-record-reload" onClick={() => readRecord(recordValue.loop_id)}>
            루프 기록 다시 읽기</Button>
        </div>
      </Section>

      {active && (view.action === "select" || view.action === "compute" || sending) &&
        <Section area="send" title="⑤ 보낼 내용·미리보기·승인 (JEV에 묻기)" state={sending ? "loading" : build.status}>
        <p className="mw-jev-note" data-testid="jev-loop-note-ul2">{LOOP_SCREEN_NOTES.UL2}</p>
        <div className="mw-jev-inline">
          <Button size="sm" variant="primary" data-testid="jev-loop-build" disabled={!view.buttons.build.enabled}
            onClick={() => void buildProjection()}>보낼 내용 만들기</Button>
          {build.status === "loading" && <span className="mw-jev-note" aria-busy="true">{JEV_TEXT.building}</span>}
        </div>
        <Reasons reasons={view.buttons.build.reasons} testId="jev-loop-build-blocked" />
        {build.status === "error" && <ErrorLine message={build.message} testId="jev-loop-build-error" />}
        {projectionShown && <>
          <p className="mw-jev-note" data-testid="jev-loop-projection" data-projection-handle={projectionShown.handle}
            data-send-ordinal={projectionShown.summary.send_ordinal}>
            보낼 내용(jev_loop_projection@1)을 저장했습니다 · 후보 {projectionShown.summary.selection_count}개 · 본문{" "}
            {projectionShown.summary.body_bytes} 바이트 · <code title={projectionShown.handle}>
              {shortSha(projectionShown.handle)}</code></p>
          {previewLoad?.status === "loading" && <Loading text={JEV_TEXT.previewLoading} />}
          {previewLoad?.status === "error" && <ErrorLine message={previewLoad.message}
            onRetry={() => readPreview(projectionShown.handle)} testId="jev-loop-preview-error" />}
          {previewValue && <LoopPreview preview={previewValue} record={recordValue} laterStatus={laterStatus}
            onReload={() => readPreview(projectionShown.handle)} />}
          {previewValue?.repair_warning && <p className="mw-jev-unavailable" role="status"
            data-testid="jev-loop-preview-repair-warning" data-statement={previewValue.repair_warning.id}>
            {previewValue.repair_warning.text}</p>}
        </>}
        {previewValue?.repair_warning && <p className="mw-jev-unavailable" role="status"
          data-testid="jev-loop-approval-repair-warning" data-statement={previewValue.repair_warning.id}>
          {previewValue.repair_warning.text}</p>}
        <label className="mw-jev-check">
          <input type="checkbox" data-testid="jev-loop-confirm" checked={confirmed} disabled={previewValue === null || sending}
            onChange={event => setConfirmedFor(event.target.checked && previewValue ? previewValue.body_sha256 : null)} />
          {CONFIRM_CHECK_TEXT}</label>
        <div className="mw-jev-inline">
          <Button size="sm" variant="primary" data-testid="jev-loop-send" disabled={!canSend}
            data-send-id={pendingId ?? undefined} onClick={() => void sendLoopBody()}>{SEND_BUTTON_TEXT}</Button>
          {sending && <span className="mw-jev-note" aria-busy="true" data-testid="jev-loop-sending">{JEV_TEXT.sendingNow}</span>}
        </div>
        {sendBlockers.length > 0 && <div data-testid="jev-loop-send-blockers" data-count={sendBlockers.length}>
          <span className="mw-eyebrow">{JEV_TEXT.sendBlockers}</span>
          <ul className="mw-jev-errors">{sendBlockers.map(text => <li key={text}>{text}</li>)}</ul>
        </div>}
        {sendError && <ErrorLine message={sendError} testId="jev-loop-send-error" />}
        {lastRecord && <p className="mw-jev-note" role="status" data-testid="jev-loop-send-record"
          data-send-id={lastRecord.send_id} data-status={lastRecord.status} data-reason-code={lastRecord.reason_code ?? undefined}>
          {JEV_TEXT.sendRecorded}: {sendStatusText(lastRecord.status)}
          {sendReasonText(lastRecord.status, lastRecord.reason_code) ? ` · ${sendReasonText(lastRecord.status,
            lastRecord.reason_code)}` : ""}</p>}
        {lastRecord?.repair_warning && <p className="mw-jev-unavailable" role="status"
          data-testid="jev-loop-send-repair-warning" data-statement={lastRecord.repair_warning.id}>
          {lastRecord.repair_warning.text}</p>}
      </Section>}

      {(selectionRef !== null || openedSend !== null) && <Section area="choice" title="⑥ JEV 판정(모델 선택)">
        {selectionRef !== null && <div className="mw-jev-loop-field" data-testid="jev-loop-selection"
          data-send-id={selectionRef.sendId}>
          <span className="mw-eyebrow">이 바퀴의 JEV 선택 (처음 완료된 늦지 않은 응답)</span>
          <SendResult load={selectionLoad} record={recordValue} onRetry={() => readDetail(selectionRef.sendId)} />
        </div>}
        {openedSend !== null && openedSend !== selectionRef?.sendId && <div className="mw-jev-loop-field"
          data-testid="jev-loop-opened-send" data-send-id={openedSend}>
          <span className="mw-eyebrow">연 전송의 결과</span>
          <SendResult load={openedLoad} record={recordValue} onRetry={() => readDetail(openedSend)} />
        </div>}
      </Section>}

      {active && (view.action === "select" || view.action === "compute" || view.action === "dock") &&
        <Section area="compute" title="⑦ 계산 시작 (사람의 승인)" state={computeBusy ? "loading" : undefined}>
          <label className="mw-jev-check" data-testid="jev-loop-compute-confirm-label">
            <input type="checkbox" data-testid="jev-loop-compute-confirm" checked={computeConfirmed} disabled={busy}
              onChange={event => setComputeConfirmedFor(event.target.checked ? computeKey : null)} />
            {`계산 시작 확인: 기존 작업 큐로 계산합니다. 서버가 알린 이 단계의 필요량은 ` +
              `${view.axisRows.find(row => row.axis === "expensive_units")?.needText ?? NULL_TEXT} · 활동 시간 ` +
              `${view.axisRows.find(row => row.axis === "wall_clock_s")?.needText ?? NULL_TEXT}입니다(후보마다 다를 수 있음).`}
          </label>
          {view.action === "dock" ? <>
            <p className="mw-jev-note">모델링이 끝난 후보입니다. 변이 구조에 같은 조건으로 자유 도킹하거나, 도킹하지 않고 이 바퀴를 끝냅니다
              (모델링 단위는 되돌리지 않습니다).</p>
            <div className="mw-jev-inline">
              <ButtonWithReasons state={view.buttons.dock} extra={confirmReason} testId="jev-loop-dock" label="도킹 시작"
                onPress={computeDock} primary />
              <ButtonWithReasons state={view.buttons.abandon} testId="jev-loop-abandon" label="도킹 포기"
                onPress={() => void abandonDocking()} />
            </div>
            {actionError?.action === "abandon" && <ErrorLine message={actionError.text} testId="jev-loop-abandon-error" />}
          </> : <>
            {view.action === "compute" && <div className="mw-jev-inline">
              <ButtonWithReasons state={view.buttons.computeProposal} extra={confirmReason}
                testId="jev-loop-compute-proposal" label="이 선택으로 계산 시작 (JEV 판정 사용)" onPress={computeProposal}
                primary />
            </div>}
            <fieldset className="mw-jev-choices" data-testid="jev-loop-designate-choices">
              <legend>직접 지정 (계산하지 않은 후보, 전송 없이도 가능, 자동으로 고르지 않음)</legend>
              {!selectable.length && <p className="mw-jev-note">직접 지정할 수 있는 후보가 없습니다.</p>}
              {selectable.map(row => <label key={String(row.ref)} data-ref={String(row.ref)}>
                <input type="radio" name={`jev-loop-designate-${branch}-${runId}`} data-testid="jev-loop-designate-option"
                  data-ref={String(row.ref)} checked={designated === row.ref} disabled={busy}
                  onChange={() => setDesignated(row.ref)} />
                <span className="mw-mono">{row.refText}</span> <span className="mw-mono mw-jev-smiles">{row.displayText}</span>
              </label>)}
            </fieldset>
            <div className="mw-jev-inline">
              <ButtonWithReasons state={view.buttons.designate}
                extra={[...(designatedRow === null ? ["직접 지정할 후보를 고르세요."] : []), ...confirmReason]}
                testId="jev-loop-designate" label="고른 후보로 계산 시작 (직접 지정)" onPress={computeDesignated} />
            </div>
          </>}
          <p className="mw-jev-note">{CANCEL_BEFORE_START_NOTE}</p>
        </Section>}

      <Section area="candidates" title="⑧ 풀 후보 (저장값만)">
        <CandidateTable record={recordValue} sort={sort} onSort={key => setSort(previous => nextLoopSort(previous, key))}
          onOpen={openResult} />
        {m18 && <div className="mw-jev-loop-field" data-testid="jev-loop-m18-area">
          <span className="mw-eyebrow">M18 도킹 결과 (저장된 결과 상세 읽기 값)</span>
          {m18.load.status === "loading" && <Loading />}
          {m18.load.status === "error" && <ErrorLine message={m18.load.message} onRetry={() => openResult(m18.handle)}
            testId="jev-loop-m18-error" />}
          {m18.load.status === "ready" && <M18Detail detail={m18.load.value} />}
        </div>}
      </Section>

      <Section area="iterations" title="⑨ 바퀴 기록">
        <IterationTable record={recordValue} onOpenSend={openSend} openedSend={openedSend} />
      </Section>

      <Section area="end" title="⑩ 끝내기·요약·보고서" state={actionBusy === "end" ? "loading" : undefined}>
        <Facts testId="jev-loop-counts" lines={[["시작한 바퀴", String(recordValue.counts.started)],
          ["끝난 바퀴", String(recordValue.counts.done)], ["JEV가 고른 바퀴", String(recordValue.counts.jev_decided)],
          ["사람이 지정한 바퀴", String(recordValue.counts.human_decided)],
          ["보낸 전송(dispatch)", String(recordValue.counts.sends_dispatched)],
          ["과금된 비싼 계산 단위", String(recordValue.counts.units_charged)],
          ["저장된 결과 재사용 후보", String(recordValue.counts.reused_count)]]} />
        {active ? <>
          <div className="mw-jev-inline">
            <ButtonWithReasons state={view.buttons.end} testId="jev-loop-end" label="루프 끝내기"
              onPress={() => void endLoop()} />
          </div>
          <p className="mw-jev-note">끝낸 루프는 다시 열 수 없습니다. 끝내면 서버가 요약(jev_loop_result@1)을 저장합니다.</p>
          {actionError?.action === "end" && <ErrorLine message={actionError.text} testId="jev-loop-end-error" />}
        </> : <div data-testid="jev-loop-ended" data-end-reason={recordValue.end_reason ?? undefined}
          data-result-handle={statusOfLoop.resultHandle ?? undefined}>
          <p role="status" data-testid="jev-loop-ended-status">{statusOfLoop.statusText}</p>
          {statusOfLoop.resultHandle && <p className="mw-jev-note">요약 jev_loop_result@1 · <code
            title={statusOfLoop.resultHandle}>{shortSha(statusOfLoop.resultHandle)}</code></p>}
          <div className="mw-jev-inline">
            <Button size="sm" data-testid="jev-loop-report"
              disabled={statusOfLoop.reportBlockedReason !== null || report?.load.status === "loading"}
              onClick={() => void makeReport()}>보고서 만들기 (JEV 루프 보고서)</Button>
          </div>
          {statusOfLoop.reportBlockedReason && <p className="mw-jev-note" data-testid="jev-loop-report-blocked">
            {statusOfLoop.reportBlockedReason}</p>}
          {report?.load.status === "loading" && <Loading text={JEV_TEXT.reportLoading} />}
          {report?.load.status === "ready" && <p className="mw-jev-note" role="status" data-testid="jev-loop-report-done"
            data-report-handle={report.load.value.handle}>
            JEV 루프 보고서를 저장했습니다 · <code title={report.load.value.handle}>{shortSha(report.load.value.handle)}</code>
            . 지식·보고서 탭의 보고서 목록에서 열고 받을 수 있습니다.</p>}
          {report?.load.status === "error" && <ErrorLine message={report.load.message} testId="jev-loop-report-error" />}
        </div>}
      </Section>

      <Section area="limitations" title="⑪ 고정 문장 (서버가 저장한 문장 그대로)">
        <ul className="mw-jev-list" data-testid="jev-loop-limitations">
          {recordValue.limitations.map((text, index) => <li key={index} data-limitation={index}>{text}</li>)}</ul>
      </Section>
    </>}
  </section>;
}

function FieldErrors({ field, errors, refusal }: { field: LoopCreateField; errors: readonly string[];
  refusal: { field: LoopCreateField; reasonCode: string | null; text: string } | null }) {
  const server = refusal !== null && refusal.field === field ? refusal : null;
  if (!errors.length && server === null) return null;
  return <div data-testid={`jev-loop-errors-${field}`} data-field={field}>
    {errors.length > 0 && <ul className="mw-jev-errors">{errors.map(text => <li key={text}>{text}</li>)}</ul>}
    {server && <p className="mw-jev-error" role="alert" data-testid="jev-loop-create-refusal" data-field={field}
      data-reason-code={server.reasonCode ?? undefined}>{server.text}</p>}
  </div>;
}

/** A button of the opened loop: enabled only by `loopActionView` (and the area's extra guard), its reasons below. */
function ButtonWithReasons({ state, extra = [], testId, label, onPress, primary = false }: { state: LoopButtonState;
  extra?: readonly string[]; testId: string; label: string; onPress: () => void; primary?: boolean }) {
  const reasons = [...state.reasons, ...extra];
  return <div className="mw-jev-loop-button">
    <Button size="sm" variant={primary ? "primary" : "default"} data-testid={testId} disabled={reasons.length > 0}
      onClick={onPress}>{label}</Button>
    <Reasons reasons={reasons} testId={`${testId}-blocked`} />
  </div>;
}

function Facts({ lines, testId }: { lines: [string, string][]; testId?: string }) {
  return <dl className="mw-jev-facts" data-testid={testId}>
    {lines.map(([label, value]) => <Fragment key={label}><dt>{label}</dt><dd className="mw-mono" data-line={label}>{value}</dd>
    </Fragment>)}
  </dl>;
}

function AxisTable({ rows, testId }: { rows: { axis: string; label: string; needText: string; remainingText: string;
  blocked: boolean }[]; testId: string }) {
  return <div className="mw-jev-table-wrap"><table className="mw-jev-table" data-testid={testId}>
    <caption className="mw-jev-note">다음 동작에 필요한 양과 남은 양 (서버 값)</caption>
    <thead><tr><th>축</th><th>필요</th><th>남은 양</th><th>막힘</th></tr></thead>
    <tbody>{rows.map(row => <tr key={row.axis} data-axis={row.axis} data-blocked={row.blocked}>
      <td>{row.label}</td><td className="mw-mono">{row.needText}</td><td className="mw-mono">{row.remainingText}</td>
      <td>{row.blocked ? "모자람" : NULL_TEXT}</td>
    </tr>)}</tbody>
  </table></div>;
}

function CandidateCheck({ selection, option, onToggle }: { selection: JevSelection; option: JevCandidateOption;
  onToggle: (option: JevCandidateOption, checked: boolean) => void }) {
  const checked = jevCandidateChecked(selection, option);
  const blocked = jevCandidateBlockedReason(selection, option);
  // A candidate the applied filter refuses can never be checked; at 20 the click is refused with its reason.
  const filteredOut = option.kind === "ligand" && option.passesAll === false && !checked;
  return <input type="checkbox" data-testid="jev-loop-candidate" data-jev-loop-candidate={String(option.key)}
    aria-label={`${JEV_TEXT.candidateCheck} ${option.key}`} checked={checked} disabled={filteredOut}
    title={blocked ?? undefined} onChange={event => onToggle(option, event.target.checked)} />;
}

function Pager({ offset, limit, shown, total, onPage }: { offset: number; limit: number; shown: number; total: number;
  onPage: (offset: number) => void }) {
  const last = offset + shown;
  return <div className="mw-jev-inline" data-testid="jev-loop-candidates-pager" data-offset={offset} data-total={total}>
    <Button size="sm" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - limit))}>{JEV_TEXT.previous}</Button>
    <Button size="sm" disabled={last >= total} onClick={() => onPage(last)}>{JEV_TEXT.next}</Button>
  </div>;
}

function LigandTable({ page, selection, onToggle, onPage }: { page: LigandCandidatePage; selection: JevSelection;
  onToggle: (option: JevCandidateOption, checked: boolean) => void; onPage: (offset: number) => void }) {
  const conflicts = jevFilterConflicts(selection, page.rows);
  return <div className="mw-jev-candidates">
    <p className="mw-jev-note" data-testid="jev-loop-candidate-count" data-total={page.total}
      data-passing={page.passing ?? undefined} data-hidden={page.hidden_by_filter}>{candidateCountText(page)}</p>
    {conflicts.length > 0 && <p className="mw-jev-unavailable" role="status" data-testid="jev-loop-filter-conflicts">
      {JEV_TEXT.conflictNote} <span className="mw-mono">{conflicts.join(", ")}</span></p>}
    {!page.rows.length ? <p className="mw-jev-note">{JEV_TEXT.noRows}</p> : <div className="mw-jev-table-wrap">
      <table className="mw-jev-table" data-testid="jev-loop-candidates" data-kind="ligand">
        <thead><tr><th>{JEV_TEXT.headerPick}</th><th>{JEV_TEXT.headerOrder}</th><th>{JEV_TEXT.headerCandidateId}</th>
          <th>{JEV_TEXT.headerSmiles}</th><th>{JEV_TEXT.headerFilter}</th></tr></thead>
        <tbody>{page.rows.map(row => {
          const option = ligandCandidateOption(selection.source, row);
          return <tr key={row.candidate.id} data-jev-loop-candidate-row={row.candidate.id}
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
    <Pager offset={page.offset} limit={page.limit} shown={page.rows.length} total={page.matched} onPage={onPage} />
  </div>;
}

function MutationTable({ page, selection, onToggle, onPage }: { page: MutationCandidatePage; selection: JevSelection;
  onToggle: (option: JevCandidateOption, checked: boolean) => void; onPage: (offset: number) => void }) {
  return <div className="mw-jev-candidates">
    <p className="mw-jev-note" data-testid="jev-loop-candidate-count" data-total={page.total}>{pageRangeText(page)}</p>
    {!page.rows.length ? <p className="mw-jev-note">{JEV_TEXT.noRows}</p> : <div className="mw-jev-table-wrap">
      <table className="mw-jev-table" data-testid="jev-loop-candidates" data-kind="mutation">
        <thead><tr><th>{JEV_TEXT.headerPick}</th><th>{JEV_TEXT.headerIndex}</th><th>{JEV_TEXT.headerPosition}</th>
          <th>{JEV_TEXT.headerResidue}</th><th>{JEV_TEXT.headerChange}</th></tr></thead>
        <tbody>{page.rows.map(row => {
          const option = mutationCandidateOption(selection.source, row);
          return <tr key={row.index} data-jev-loop-candidate-row={row.index}
            data-checked={jevCandidateChecked(selection, option)}
            data-blocked-reason={jevCandidateBlockedReason(selection, option) ?? undefined}>
            <td><CandidateCheck selection={selection} option={option} onToggle={onToggle} /></td>
            <td className="mw-mono">{row.index}</td><td className="mw-mono">{row.position_index}</td>
            <td className="mw-mono">{residueText(row.residue)}</td><td className="mw-mono">{row.from}→{row.to}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>}
    <Pager offset={page.offset} limit={page.limit} shown={page.rows.length} total={page.total} onPage={onPage} />
  </div>;
}

/** Ligand computation setup: the M22 inputs (receptor, model, instance, connectivity, parent SDF, box, free values). */
function LigandSetupInputs({ form, update, runId, prereq, chosenSet, hasSource, instances, onReloadPrereq }: {
  form: DockingForm; update: (patch: Partial<DockingForm>) => void; runId: string; prereq: DockingPrerequisites | null;
  chosenSet: DockingPrerequisites["candidate_sets"][number] | null; hasSource: boolean;
  instances: Load<DockingReceptorInstances> | null; onReloadPrereq: () => void }) {
  const receptors = prereq ? importsOfKind(prereq.imports, "receptor") : [];
  const sidecars = prereq ? importsOfKind(prereq.imports, "receptor_bonds") : [];
  const parentReason = hasSource ? parentSdfMissingReason(chosenSet) : "풀의 후보 집합을 먼저 고르세요.";
  const listing = instances?.status === "ready" ? instances.value : null;
  const modelList = listing ? modelInstances(listing, form.receptorModelNumber) : [];
  return <div className="mw-jev-loop-setup" data-testid="jev-loop-setup-form">
    <div className="mw-jev-inline">
      <Button size="sm" data-testid="jev-loop-prereq-refresh" onClick={onReloadPrereq}>입력 목록 다시 읽기</Button>
      <span className="mw-jev-note">수용체·사이드카·부모 SDF 가져오기는 위 도킹 영역에서 합니다.</span>
    </div>
    {parentReason ? <p className="mw-jev-note" data-testid="jev-loop-parent-missing">{parentReason}</p>
      : <label className="mw-jev-check">부모 3D SDF 가져오기 (SHA-256이 후보 집합의 부모와 같은 것만)
        <select className="mw-select" data-testid="jev-loop-parent-sdf" value={form.parentSdfHandle ?? ""}
          onChange={event => update({ parentSdfHandle: event.target.value || null })}>
          <option value="">선택</option>
          {(chosenSet?.parent_sdf_handles ?? []).map(handle => <option key={handle} value={handle}>{shortSha(handle)}</option>)}
        </select></label>}
    <label className="mw-jev-check">수용체 가져오기
      <select className="mw-select" data-testid="jev-loop-receptor" value={form.receptorHandle ?? ""}
        onChange={event => update({ receptorHandle: event.target.value || null })}>
        <option value="">선택</option>
        {receptors.map(row => <option key={row.handle} value={row.handle}>
          {`생성 순번 ${row.created_seq} · ${row.input_format ?? ""} · ${row.size} B · ${shortSha(row.handle)}`}</option>)}
      </select></label>
    {prereq && !receptors.length && <p className="mw-jev-note">가져온 수용체가 없습니다.</p>}
    {instances?.status === "loading" && <Loading text="수용체 인스턴스 목록을 읽는 중" />}
    {instances?.status === "error" && <ErrorLine message={instances.message} testId="jev-loop-instances-error" />}
    {listing && <>
      <label className="mw-jev-check">모델 (암묵적으로 첫 모델을 쓰지 않음)
        <select className="mw-select" data-testid="jev-loop-model" value={form.receptorModelNumber ?? ""}
          onChange={event => update({ receptorModelNumber: event.target.value === "" ? null : Number(event.target.value) })}>
          <option value="">선택</option>
          {listing.model_numbers.map(number => <option key={number} value={number}>{`모델 ${number}`}</option>)}
        </select></label>
      {form.receptorModelNumber !== null && <fieldset className="mw-jev-choices" data-testid="jev-loop-instances">
        <legend>수용체에서 뺄 리간드 인스턴스 (하나만, 자동으로 고르지 않음)</legend>
        <label data-jev-loop-instance="none">
          <input type="radio" name={`jev-loop-instance-${runId}`} checked={form.instance.kind === "none"}
            onChange={() => update({ instance: { kind: "none" } })} />
          <span>없음(단백질만)</span></label>
        {modelList.map(item => <label key={JSON.stringify(exactResidue(item.residue))}
          data-jev-loop-instance={JSON.stringify(exactResidue(item.residue))}>
          <input type="radio" name={`jev-loop-instance-${runId}`}
            checked={form.instance.kind === "instance" && sameResidue(form.instance.residue, item.residue)}
            onChange={() => update({ instance: { kind: "instance", residue: exactResidue(item.residue) } })} />
          <span className="mw-mono">{removedInstanceText(item)}</span></label>)}
        {!modelList.length && <p className="mw-jev-note">이 모델에는 물 밖의 비표준 잔기 인스턴스가 없습니다.</p>}
      </fieldset>}
    </>}
    <fieldset className="mw-jev-choices" data-testid="jev-loop-connectivity">
      <legend>연결 정보</legend>
      <label><input type="radio" name={`jev-loop-connectivity-${runId}`} checked={form.connectivity === "pdb_conect"}
        onChange={() => update({ connectivity: "pdb_conect" })} /> PDB CONECT (파일 안의 완전한 연결 정보)</label>
      <label><input type="radio" name={`jev-loop-connectivity-${runId}`} checked={form.connectivity === "sidecar"}
        onChange={() => update({ connectivity: "sidecar" })} /> 결합 사이드카 (receptor_bonds@1)</label>
      {form.connectivity === "sidecar" && <label className="mw-jev-check">사이드카 가져오기
        <select className="mw-select" data-testid="jev-loop-sidecar" value={form.sidecarHandle ?? ""}
          onChange={event => update({ sidecarHandle: event.target.value || null })}>
          <option value="">선택</option>
          {sidecars.map(row => <option key={row.handle} value={row.handle}>
            {`생성 순번 ${row.created_seq} · ${row.size} B · ${shortSha(row.handle)}`}</option>)}
        </select></label>}
    </fieldset>
    <p className="mw-jev-note">{BOX_FRAME_NOTE}</p>
    <fieldset className="mw-jev-choices" data-testid="jev-loop-box-source">
      <legend>상자 출처 (루프 전체에 하나, 자동으로 고르지 않음)</legend>
      {BOX_SOURCES.map((source: DockingBoxSource) => {
        const reason = boxSourceDisabledReason(source, form.instance);
        return <label key={source} data-jev-loop-box={source} data-disabled-reason={reason ?? undefined}>
          <input type="radio" name={`jev-loop-box-${runId}`} checked={form.boxSource === source} disabled={!!reason}
            onChange={() => update({ boxSource: source })} /> {boxSourceLabel(source)}
          {reason && <span className="mw-jev-note">{reason}</span>}</label>;
      })}
    </fieldset>
    {(form.boxSource === "ligand_range" || form.boxSource === "instance_range") && <label className="mw-jev-check">
      여백 (Å, {MARGIN_MIN_A}–{MARGIN_MAX_A}{form.boxSource === "ligand_range" ? ", 부모 SDF 중원자 범위" : ""})
      <input className="mw-ligand-input" data-testid="jev-loop-margin" inputMode="decimal" value={form.margin}
        onChange={event => update({ margin: event.target.value })} /></label>}
    {form.boxSource === "manual" && <div className="mw-docking-grid" data-testid="jev-loop-manual-box">
      {AXES.map((axis, i) => <label key={`c${axis}`} className="mw-jev-check">중심 {axis} (Å)
        <input className="mw-ligand-input" data-testid={`jev-loop-center-${axis}`} inputMode="decimal" value={form.center[i]}
          onChange={event => update({ center: form.center.map((value, j) => j === i ? event.target.value : value) as
            DockingForm["center"] })} /></label>)}
      {AXES.map((axis, i) => <label key={`s${axis}`} className="mw-jev-check">크기 {axis} (Å, {BOX_SIDE_MIN_A}–{BOX_SIDE_MAX_A})
        <input className="mw-ligand-input" data-testid={`jev-loop-size-${axis}`} inputMode="decimal" value={form.size[i]}
          onChange={event => update({ size: form.size.map((value, j) => j === i ? event.target.value : value) as
            DockingForm["size"] })} /></label>)}
    </div>}
    <div className="mw-docking-grid">
      <label className="mw-jev-check">도킹 seed (qvina 난수, 필수, {SEED_MIN}–{SEED_MAX})
        <input className="mw-ligand-input" data-testid="jev-loop-docking-seed" inputMode="numeric" value={form.seed}
          onChange={event => update({ seed: event.target.value })} /></label>
      <label className="mw-jev-check">exhaustiveness ({EXHAUSTIVENESS_MIN}–{EXHAUSTIVENESS_MAX})
        <input className="mw-ligand-input" data-testid="jev-loop-exhaustiveness" inputMode="numeric"
          value={form.exhaustiveness} onChange={event => update({ exhaustiveness: event.target.value })} /></label>
      <label className="mw-jev-check">num_modes ({NUM_MODES_MIN}–{NUM_MODES_MAX})
        <input className="mw-ligand-input" data-testid="jev-loop-num-modes" inputMode="numeric" value={form.numModes}
          onChange={event => update({ numModes: event.target.value })} /></label>
      <label className="mw-jev-check">energy_range (kcal/mol, {ENERGY_RANGE_MIN}–{ENERGY_RANGE_MAX})
        <input className="mw-ligand-input" data-testid="jev-loop-energy-range" inputMode="decimal" value={form.energyRange}
          onChange={event => update({ energyRange: event.target.value })} /></label>
    </div>
    <p className="mw-jev-note">cpu는 1로 고정됩니다.</p>
    <fieldset className="mw-jev-choices" data-testid="jev-loop-acknowledgement">
      <legend>제출 전 확인 (세 항목 모두, 루프의 모든 도킹에 같이 적용)</legend>
      {ACKNOWLEDGEMENT_KEYS.map((key: DockingAcknowledgementKey) => <label key={key} data-jev-loop-ack={key}>
        <input type="checkbox" checked={form.acknowledgement[key]}
          onChange={event => update({ acknowledgement: { ...form.acknowledgement, [key]: event.target.checked } })} />
        {ACKNOWLEDGEMENT_LABEL[key]}</label>)}
    </fieldset>
  </div>;
}

/** Protein computation setup: the M21 `PairInputs` (3D SDF, box, free values), the two literals and the cutoff. */
function ProteinSetupInputs({ form, update, runId, prereq, onReloadPrereq }: { form: ProteinLoopSetupForm;
  update: (patch: Partial<ProteinLoopSetupForm>) => void; runId: string; prereq: Load<DockingPrerequisites>;
  onReloadPrereq: () => void }) {
  const ligandSdfs = prereq.status === "ready" ? importsOfKind(prereq.value.imports, "ligand_sdf") : [];
  return <div className="mw-jev-loop-setup">
    <fieldset className="mw-jev-choices" data-testid="jev-loop-confirmations">
      <legend>변이 구조 모델링 확인 (두 항목 모두)</legend>
      <label><input type="checkbox" data-testid="jev-loop-confirm-selection" checked={form.selectionConfirmed}
        onChange={event => update({ selectionConfirmed: event.target.checked })} />
        {CONFIRMATION_LABEL.selection_policy}</label>
      <label><input type="checkbox" data-testid="jev-loop-confirm-hydrogen" checked={form.hydrogenConfirmed}
        onChange={event => update({ hydrogenConfirmed: event.target.checked })} />
        {CONFIRMATION_LABEL.hydrogen_policy}</label>
    </fieldset>
    <label className="mw-jev-check">접촉 cutoff (Å, M21 모델링 입력, {CONTACT_CUTOFF_RANGE_A[0].toFixed(1)}–
      {CONTACT_CUTOFF_RANGE_A[1].toFixed(1)}, 기본 {CONTACT_CUTOFF_DEFAULT_A.toFixed(1)})
      <input className="mw-ligand-input" data-testid="jev-loop-cutoff" inputMode="decimal" value={form.cutoff}
        onChange={event => update({ cutoff: event.target.value })} /></label>
    <p className="mw-jev-note">{PROTEIN_SEED_NOTE}</p>
    <PairInputs form={form} update={update} runId={runId} prereq={prereq} ligandSdfs={ligandSdfs}
      onReloadPrereq={onReloadPrereq} idPrefix="jev-loop-setup" ligandSourceReason={proteinLigandSourceReason}
      seedLabel={`도킹·모델링 seed (필수, ${SEED_MIN}–${SEED_MAX})`}
      acknowledgementLegend="제출 전 확인 (세 항목 모두, 루프의 모든 변이 구조 도킹에 같이 적용)" />
  </div>;
}

function proteinLigandSourceReason(source: string): string | null {
  return source === "sdf" ? null : PROTEIN_SDF_ONLY_REASON;
}

/** The loop preview as shown: the exact body (collapsed `pre`), the alias table (not sent), shuffle and reservation. */
function LoopPreview({ preview, record, laterStatus, onReload }: { preview: JevLoopPreviewV1; record: JevLoopV1;
  laterStatus: JevStatusV1 | null; onReload: () => void }) {
  const view = jevLoopPreviewView(preview, record, laterStatus);
  return <div className="mw-jev-preview" data-testid="jev-loop-preview" data-projection-handle={view.projectionHandle}
    data-body-sha256={view.bodySha256} data-body-bytes={preview.body_bytes}
    data-blocked={view.blocked.length + view.loopBlocks.length > 0}>
    <dl className="mw-jev-facts">
      <dt>{JEV_TEXT.kind}</dt><dd>{view.kindText} · <code>{view.questionId}</code></dd>
      <dt>{JEV_TEXT.bytes}</dt><dd className="mw-mono" data-testid="jev-loop-preview-bytes">{view.bodyBytesText}</dd>
      <dt>{JEV_TEXT.sha256}</dt><dd><code data-testid="jev-loop-preview-sha256">{view.bodySha256}</code></dd>
    </dl>
    <details data-testid="jev-loop-preview-body-details">
      <summary>{JEV_TEXT.bodySummary}</summary>
      <pre className="mw-jev-body" data-testid="jev-loop-preview-body">{view.body}</pre>
    </details>
    <p className="mw-jev-note">{JEV_TEXT.question}</p>
    <p className="mw-jev-quote" data-testid="jev-loop-preview-question">{view.instructions}</p>
    <p className="mw-jev-note">{view.aliasNote}</p>
    <div className="mw-jev-table-wrap"><table className="mw-jev-table" data-testid="jev-loop-alias-table">
      <thead><tr><th>{JEV_TEXT.aliasAlias}</th><th>{JEV_TEXT.aliasLocal}</th><th>로컬 표기</th><th>계산 상태</th>
        <th>JEV 선택 가능</th><th>{JEV_TEXT.aliasSent}</th></tr></thead>
      <tbody>{view.aliasRows.map(row => <tr key={row.alias} data-alias={row.alias}>
        <td className="mw-mono">{row.alias}</td><td className="mw-mono">{row.refText}</td>
        <td className="mw-mono mw-jev-smiles">{row.displayText}</td><td>{row.stateText}</td><td>{row.choosableText}</td>
        <td>{row.sentText}</td>
      </tr>)}</tbody>
    </table></div>
    <p className="mw-jev-note" data-testid="jev-loop-preview-order">{view.orderText}</p>
    <p data-testid="jev-loop-preview-reservation">{view.reservationText}</p>
    <p data-testid="jev-loop-preview-cap">{view.capText}</p>
    <p data-testid="jev-loop-preview-budget">{view.budgetRemainingText}</p>
    <AxisTable rows={view.axisRows} testId="jev-loop-preview-axes" />
    <p data-testid="jev-loop-preview-previous" data-previous-sends={preview.previous_sends}>{view.previousSendsText}</p>
    <div data-testid="jev-loop-preview-blocked" data-count={view.blocked.length + view.loopBlocks.length}>
      <span className="mw-eyebrow">{JEV_TEXT.serverBlockers}</span>
      {view.blocked.length + view.loopBlocks.length ? <ul className="mw-jev-errors">
        {view.blocked.map(item => <li key={item.code} data-block-reason={item.code}
          data-stale={item.stale ? "true" : undefined}>{item.text}</li>)}
        {view.loopBlocks.map(item => <li key={`loop-${item.code}`} data-loop-block={item.code}>{item.text}</li>)}
      </ul> : <p className="mw-jev-note">{JEV_TEXT.noServerBlockers}</p>}
    </div>
    <div className="mw-jev-inline">
      <Button size="sm" data-testid="jev-loop-preview-reload" onClick={onReload}>{JEV_TEXT.previewReload}</Button>
    </div>
  </div>;
}

/** One loop send's result: the proposal card ("JEV 판정(모델 선택)") when completed, else its reason only. */
function SendResult({ load, record, onRetry }: { load: Load<JevLoopSendDetail> | undefined; record: JevLoopV1;
  onRetry: () => void }) {
  if (load === undefined || load.status === "idle" || load.status === "loading") return <Loading text={JEV_TEXT.resultLoading} />;
  if (load.status === "error") return <ErrorLine message={load.message} onRetry={onRetry} testId="jev-loop-choice-error" />;
  const view = loopChoiceView(load.value, record);
  if (view.state === "confirming") return <p className="mw-jev-note" role="status" aria-busy="true"
    data-testid="jev-loop-choice-confirming" data-send-id={load.value.send_id}>{view.statusText}: {view.message}</p>;
  if (view.state !== "completed") {
    const reason = view.state === "rejected" || view.state === "failed" ? view.reasonText
      : view.state === "invalid" ? view.message : null;
    return <p className={view.state === "in_progress" ? "mw-jev-note" : "mw-jev-unavailable"} role="status"
      data-testid="jev-loop-choice-reason" data-send-id={load.value.send_id} data-status={load.value.status}
      data-reason-code={load.value.reason_code ?? undefined}>{view.statusText}{reason ? `: ${reason}` : ""}</p>;
  }
  const card = view.card;
  return <div className="mw-jev-card" data-testid="jev-loop-choice-card" data-send-id={card.sendId}
    data-proposal-handle={card.proposalHandle} data-chosen-alias={card.chosenAlias} data-late={card.lateText !== null}
    data-selection={card.isSelection} data-role={card.role} data-list-position={card.listPositionText}>
    <p className="mw-jev-title">{card.label}</p>
    <p className="mw-jev-note" data-testid="jev-loop-choice-role">{card.roleText}</p>
    {card.lateText !== null && <p className="mw-jev-unavailable" role="status" data-testid="jev-loop-choice-late">
      {JEV_TEXT.lateMark}: {card.lateText}</p>}
    {card.lateNote !== null && <p className="mw-jev-note" data-testid="jev-loop-choice-late-note">{card.lateNote}</p>}
    <dl className="mw-jev-facts">
      <dt>{JEV_TEXT.chosenAlias}</dt><dd className="mw-mono" data-testid="jev-loop-choice-alias">{card.chosenAlias}</dd>
      <dt>{JEV_TEXT.localRef}</dt><dd className="mw-mono">{card.refText}</dd>
      <dt>{JEV_TEXT.localDisplay}</dt><dd className="mw-mono" data-testid="jev-loop-choice-local">{card.localDisplayText}</dd>
      <dt>{card.listPositionLabel}</dt><dd className="mw-mono" data-testid="jev-loop-choice-position">
        {card.listPositionText}</dd>
      <dt>{card.confidenceLabel}</dt><dd className="mw-mono" data-testid="jev-loop-choice-confidence">{card.confidenceText}</dd>
      <dt>{JEV_TEXT.requestedModel}</dt><dd className="mw-mono">{card.requestedModel}</dd>
      <dt>{JEV_TEXT.servedModel}</dt><dd className="mw-mono" data-testid="jev-loop-choice-model">{card.servedModel}</dd>
      {card.usageRows.map(row => <Fragment key={row.key}><dt>{row.label}</dt>
        <dd className="mw-mono" data-usage={row.key}>{row.text}</dd></Fragment>)}
    </dl>
    <p className="mw-jev-note">{card.reasonText}</p>
    <details data-testid="jev-loop-choice-probabilities" data-reported={card.probabilitiesReported}>
      <summary>{JEV_TEXT.probabilities}</summary>
      <p className="mw-jev-note">{card.probabilityNote}</p>
      {card.probabilityText !== null ? <p className="mw-jev-note">{card.probabilityText}</p>
        : <ul className="mw-jev-list">{card.probabilityRows.map(row => <li key={row.alias} data-alias={row.alias}>
          <span className="mw-mono">{row.alias}</span> · {row.refText} · <span className="mw-mono">{row.displayText}</span> ·{" "}
          <span className="mw-mono">{row.text}</span>
        </li>)}</ul>}
    </details>
    <div data-testid="jev-loop-choice-limitations">
      <span className="mw-eyebrow">{JEV_TEXT.fixedSentences}</span>
      {card.limitations.map((text, index) => <p key={index} className="mw-jev-note" data-limitation={index}>{text}</p>)}
    </div>
  </div>;
}

const SORT_HEADERS: { key: LoopSortKey; label: string }[] = [{ key: "pool", label: "풀 순서" },
  { key: "candidate", label: "후보" }];

/** The pool's candidates as stored; sorting changes the display order only (no-score rows always last). */
function CandidateTable({ record, sort, onSort, onOpen }: { record: JevLoopV1; sort: LoopSort;
  onSort: (key: LoopSortKey) => void; onOpen: (handle: string) => void }) {
  const rows = sortLoopCandidates(loopCandidateRows(record), sort);
  const header = (key: LoopSortKey, label: string) => <th key={key} aria-sort={loopAriaSort(sort, key)}>
    <button type="button" className="mw-docking-sort" data-testid={`jev-loop-sort-${key}`}
      onClick={() => onSort(key)}>{label}</button></th>;
  return <>
    <p className="mw-jev-note" data-testid="jev-loop-order-note">{ORDER_NOTE}</p>
    <div className="mw-jev-table-wrap"><table className="mw-jev-table" data-testid="jev-loop-candidate-table"
      data-total={rows.length}>
      <caption className="mw-jev-note">{SCORE_LABEL}</caption>
      <thead><tr>
        {SORT_HEADERS.map(item => header(item.key, item.label))}
        <th>표기</th><th>상태</th>
        {header("score", SCORE_COLUMN_LABEL)}
        {header("iteration", "바퀴")}
        <th>선택 주체</th><th>평가</th><th>상세</th>
      </tr></thead>
      <tbody>{rows.map(row => <tr key={String(row.ref)} data-ref={String(row.ref)} data-state={row.state}
        data-evaluation={row.evaluation ?? undefined} data-has-score={row.score !== null}
        data-iteration={row.iteration ?? undefined}>
        <td className="mw-mono">{row.position + 1}</td>
        <td className="mw-mono">{row.refText}</td>
        <td className="mw-mono mw-jev-smiles">{row.displayText}</td>
        <td>{row.stateText}</td>
        <td className="mw-mono" data-score-cell>{row.scoreText}</td>
        <td>{row.iterationText}</td>
        <td>{row.decidedByText}</td>
        <td>{row.evaluationText}</td>
        <td><Button size="sm" data-testid={`jev-loop-open-result-${row.position}`} disabled={row.resultHandle === null}
          onClick={() => { if (row.resultHandle !== null) onOpen(row.resultHandle); }}>상세 열기</Button></td>
      </tr>)}</tbody>
    </table></div>
  </>;
}

/** One row per listed iteration (number order): who chose, the recorded list position, its steps and its sends. */
function IterationTable({ record, onOpenSend, openedSend }: { record: JevLoopV1; onOpenSend: (sendId: string) => void;
  openedSend: string | null }) {
  const rows = loopIterationRows(record);
  if (!rows.length) return <p className="mw-jev-note" data-testid="jev-loop-no-iterations">아직 기록된 바퀴가 없습니다.</p>;
  return <div className="mw-jev-table-wrap"><table className="mw-jev-table" data-testid="jev-loop-iterations">
    <thead><tr><th>바퀴</th><th>바퀴 단계</th><th>상태</th><th>선택 주체</th><th>후보</th><th>{LIST_POSITION_LABEL}</th>
      <th>{SCORE_COLUMN_LABEL}</th><th>계산 단계</th><th>전송</th></tr></thead>
    <tbody>{rows.map(row => {
      const raw = record.iterations.find(item => item.index === row.index);
      return <tr key={row.index} data-iteration={row.index}>
        <td className="mw-mono">{row.index}</td><td>{row.phaseText}</td><td>{row.stateText}</td>
        <td>{row.decidedByText}</td><td className="mw-mono mw-jev-smiles">{row.candidateText}</td>
        <td className="mw-mono" data-testid="jev-loop-iteration-position">{row.listPositionText}</td>
        <td className="mw-mono">{row.scoreText}</td>
        <td>{row.steps.length ? <ul className="mw-jev-list">{row.steps.map((step, index) => <li key={index}
          data-job-id={step.jobId ?? undefined} data-result-handle={step.resultHandle ?? undefined}>
          {step.stepText} · {step.stateText}{step.reasonText ? ` · ${step.reasonText}` : ""}</li>)}</ul> : NULL_TEXT}</td>
        <td>{row.sends.length ? <ul className="mw-jev-list">{row.sends.map((send, index) => {
          const status = raw?.sends[index]?.status;
          return <li key={send.sendId} data-send-id={send.sendId} data-status={status}>
            {send.ordinalText} · {send.statusText}{send.lateText ? ` · ${send.lateText}` : ""}{" "}
            {status !== undefined && status !== "in_progress" && <Button size="sm" data-testid="jev-loop-send-open"
              data-send-id={send.sendId} disabled={openedSend === send.sendId}
              onClick={() => onOpenSend(send.sendId)}>{JEV_TEXT.open}</Button>}
          </li>;
        })}</ul> : NULL_TEXT}</td>
      </tr>;
    })}</tbody>
  </table></div>;
}

/** The stored M18 result detail of one candidate this loop computed (nothing recomputed). */
function M18Detail({ detail }: { detail: DockingResultDetail }) {
  const result = detail.result, mode = result.inputs.mode;
  const headers = modeTableHeaders(mode);
  return <div className="mw-docking-result" data-testid="jev-loop-m18" data-docking-result-handle={detail.handle}
    data-null-result={result.counts.null_result}>
    <p className="mw-jev-note mw-mono">결과 <code title={detail.handle}>{shortSha(detail.handle)}</code></p>
    <Facts lines={dockingSummaryRows(result)} testId="jev-loop-m18-summary" />
    {result.modes.length > 0 ? <div className="mw-jev-table-wrap">
      <table className="mw-jev-table" data-testid="jev-loop-m18-modes">
        <caption className="mw-jev-note">{detail.score_label}</caption>
        <thead><tr>{headers.map(item => <th key={item}>{item}</th>)}</tr></thead>
        <tbody>{result.modes.map(row => <tr key={row.mode} data-mode={row.mode}>
          {modeTableCells(mode, row).map((cell, i) => <td key={headers[i]} className={i ? "mw-mono" : undefined}>{cell}</td>)}
        </tr>)}</tbody>
      </table>
    </div> : <p className="mw-jev-note" data-testid="jev-loop-m18-null">{nullResultText(mode)}</p>}
    <p className="mw-jev-note">모드별 기하 접촉 표와 포즈 SDF는 리간드 설계·탐색 탭 도킹 영역의 도킹 결과 목록에서 같은 결과로 볼 수 있습니다.</p>
    <span className="mw-eyebrow">M18 한계 (저장된 문장)</span>
    <ul className="mw-jev-list" data-testid="jev-loop-m18-limitations">
      {result.limitations.map(text => <li key={text}>{text}</li>)}</ul>
  </div>;
}
