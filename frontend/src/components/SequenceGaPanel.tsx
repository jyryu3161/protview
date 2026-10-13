"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type RunSummary, type SavedReportRef } from "@/lib/api";
import type { DockingPrerequisites, DockingResultDetail, MutationCandidateSetListRow, SequenceGaArgs,
  SequenceGaCapability, SequenceGaDetail, SequenceGaIndividualRead, SequenceGaJob, SequenceGaKey,
  SequenceGaLimitApproval, SequenceGaListRow, SequenceGaPreflight, SequenceGaReportArtifact } from "@/lib/contracts";
import { boxText, dockingCancelEnabled, dockingJobActive, dockingSummaryRows, importsOfKind, modeTableCells,
  modeTableHeaders, nullResultText, SEED_MAX, SEED_MIN } from "@/lib/docking";
import { LIGAND_APPROVAL_NOTICE, ligandNoticeAfterJob, ligandStartProgressed } from "@/lib/ligand";
import { AREA_TITLE, BUDGET_NOTE, candidateSetOptions, checkGaInput, CONFIRMATION_LABEL, evaluationText, GA_AREAS,
  GA_PARAMETERS, GA_PROTOCOL, GA_STATE_TEXT, GA_TOOL, gaActiveJob, gaApprovalRequired, gaArgs, gaArgsKey, gaAreaState,
  gaExistingJobText, gaJobPhase, gaJobResult, gaJobText, gaLimitApprovalOffered, gaLimitApprovalText, gaListRowText,
  gaParameterLines, gaPreflightLines, gaPreflightRefusalText, gaProgressText, gaRangeText, gaReasonText,
  gaReportMatches, gaReportSavedForRun, gaRequestErrorText, gaResponseCurrent, gaSpaceLines, gaStampHandle,
  gaStartBlockedReason, gaStatusText, gaSummaryLines, gaSwitchBlockedReason, generationRangeText, generationTabText,
  individualAriaSort, individualDetailView, individualReasonText, individualRows, initialGaCounters, initialGaForm,
  LIMIT_RAISE_LABEL, ligandSourceDisabledReason, MODE_NOTE, MODEL_NOTE, mutationFieldLines, mutationsText,
  nextGaRequest, nextIndividualSort, ORDER_NOTE, originText, parentsText, patchGaForm, PROTONATION_DIFFERENCE_HEADERS,
  PROTONATION_DIFFERENCE_HEADING, REFERENCE_KEY, referenceRowView, REPORT_TYPE, resetGaDefaults, SCORE_LABEL,
  scoreCellText, scoreHeaderText, SEED_NOTE, sortIndividuals, SPACE_PENDING_TEXT, stateText, UNITS_PER_EVALUATION,
  type GaArea, type GaForm, type GaPreflightState, type GaRequestCounters, type GaStamp, type IndividualSort,
  type IndividualSortKey } from "@/lib/sequence-ga";
import { catalyticBadge } from "@/lib/mutations";
import { decimalHalfUp } from "@/lib/site-annotation";
import { PairInputs } from "./MutationModelPanel";
import { Button } from "./primitives";

/**
 * M23 "서열 GA 설계" area of the 단백질 공학 tab (`.dryforge/spec.md` section 10), mounted after the M21 modeling area.
 * Every score, potential, count, budget figure, space size and sentence shown is a server value (the preflight read,
 * the job record, the stored `sequence_ga_result@1`, its rows' `mutation_set_model@1` and their M18 result detail);
 * request checks, wording and rounding come from `lib/sequence-ga.ts` (the docking inputs from the M21 area's
 * `PairInputs`, the M18 rules from `lib/docking.ts`). The page mounts it only while the tab is shown and keys it by
 * run, so every list is read again on entering the tab. Late responses are dropped on two layers: the reads made by
 * effects (candidate sets, ligand imports, summary list, job list, a summary's report list) are aborted on unmount or
 * re-read; every response, clicked requests included (those only time out), is applied only while the panel is
 * mounted and run + opened summary handle + per-area request number still match (`gaResponseCurrent`). Nothing is
 * chosen, submitted or approved automatically; there is no viewer display.
 */
export interface SequenceGaPanelProps {
  /** Current run of the structure analysis screen (run selection lives only there); null when none. */
  run: RunSummary | null;
  /** `methods.sequence_ga_design`: undefined while capabilities are read; null when the backend reports none. */
  capability: SequenceGaCapability | null | undefined;
  /** After a report was created: the page re-reads the knowledge-tab report list. */
  onReportCreated: (runId: string) => void;
  /** M29: "보완 기록 열기" of a GA on a repaired structure (screen only; the M23 report is unchanged). */
  onOpenRepairRecord?: (runId: string, record: string) => void;
}

type Load<T> = { status: "idle" } | { status: "loading" } | { status: "ready"; value: T } | { status: "error"; message: string };
type M18Detail = Omit<DockingResultDetail, "meta">;
const TIMEOUT_MS = 30000;
const POLL_MS = 2000;
const LIST_LIMIT = 100;

function errorText(e: unknown): string {
  if (e instanceof ApiError) return gaRequestErrorText({ message: e.message, code: e.code ?? null, detail: e.detail ?? null });
  return e instanceof Error ? e.message : String(e);
}
const shortHandle = (handle: string) => handle.split("/").at(-1)?.slice(0, 12) ?? handle;

function Section({ area, title, state, children }: { area: string; title: string; state?: string; children: ReactNode }) {
  return <section className="mw-mutation-section" data-sequence-ga-area={area} data-state={state} aria-label={title}>
    <h3 className="mw-mutation-title">{title}</h3>
    {children}
  </section>;
}

function ErrorLine({ message, onRetry, testId }: { message: string; onRetry?: () => void; testId?: string }) {
  return <div className="mw-mutation-error" role="alert" data-testid={testId}>
    <span>{message}</span>
    {onRetry && <Button size="sm" onClick={onRetry}>다시 읽기</Button>}
  </div>;
}

/** [label, value] lines of stored or server values; each line carries its label in `data-line`. */
function Facts({ lines, testId }: { lines: [string, string][]; testId?: string }) {
  return <dl className="mw-ligand-facts mw-docking-summary" data-testid={testId}>
    {lines.map(([label, value]) => <div key={label} className="mw-ligand-fact" data-line={label}>
      <dt>{label}</dt><dd className="mw-mono">{value}</dd></div>)}
  </dl>;
}

export function SequenceGaPanel(p: SequenceGaPanelProps) {
  const runId = p.run?.run_id ?? null;
  if (!p.run || p.capability === undefined || p.capability === null || !p.capability.available) {
    const gate = gaAreaState({ runId, capability: p.capability });
    return <section className="mw-mutation mw-seqga" aria-label={AREA_TITLE} data-testid="sequence-ga-panel"
      data-ga-state={gate.state}>
      <h2 className="mw-mutation-heading">단백질 공학 · {AREA_TITLE}</h2>
      {gate.state === "unavailable" ? <p className="mw-mutation-unavailable" role="status"
        data-testid={runId === null ? "sequence-ga-no-run" : "sequence-ga-unavailable"}
        data-reason-code={p.capability?.reason_code ?? undefined}>
        <b>{GA_STATE_TEXT.unavailable}</b>: {gate.reason}</p>
        : <p className="mw-mutation-note" aria-busy="true">기능 상태를 확인하는 중</p>}
    </section>;
  }
  return <GaWorkspace run={p.run} capability={p.capability} onReportCreated={p.onReportCreated}
    onOpenRepairRecord={p.onOpenRepairRecord} />;
}

function GaWorkspace({ run, capability, onReportCreated, onOpenRepairRecord }: { run: RunSummary;
  capability: SequenceGaCapability; onReportCreated: (runId: string) => void;
  onOpenRepairRecord?: (runId: string, record: string) => void }) {
  const runId = run.run_id;
  // ---- inputs ----
  const [form, setForm] = useState<GaForm>(initialGaForm);
  const [sets, setSets] = useState<Load<MutationCandidateSetListRow[]>>({ status: "idle" });
  const [setsReload, setSetsReload] = useState(0);
  const [prereq, setPrereq] = useState<Load<DockingPrerequisites>>({ status: "idle" });
  const [prereqReload, setPrereqReload] = useState(0);
  // ---- preflight, limit approval, job ----
  const [preflight, setPreflight] = useState<{ key: string; load: Load<SequenceGaPreflight> } | null>(null);
  const [approval, setApproval] = useState<{ key: string; load: Load<SequenceGaLimitApproval> } | null>(null);
  const [job, setJob] = useState<SequenceGaJob | null>(null);
  const [approvalPending, setApprovalPending] = useState(false);
  const [busy, setBusy] = useState(false);
  // The start request is held until the job ends: cancel has its own flag and request number.
  const [cancelling, setCancelling] = useState(false);
  const [jobError, setJobError] = useState("");
  const [notice, setNotice] = useState("");
  // ---- stored summaries ----
  const [results, setResults] = useState<Load<SequenceGaListRow[]>>({ status: "idle" });
  const [resultsReload, setResultsReload] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ handle: string; load: Load<SequenceGaDetail> } | null>(null);
  const [generation, setGeneration] = useState(0);
  const [sort, setSort] = useState<IndividualSort>(null);
  const [individual, setIndividual] = useState<{ handle: string; key: string; load: Load<SequenceGaIndividualRead> } |
    null>(null);
  const [report, setReport] = useState<{ handle: string; load: Load<SequenceGaReportArtifact> } | null>(null);
  const [reportList, setReportList] = useState<{ handle: string; load: Load<SavedReportRef[]> } | null>(null);
  const [reportListReload, setReportListReload] = useState(0);

  // Late responses: mounted + run (page key) + opened summary handle + per-area request number (lib); the effect
  // reads are also aborted on unmount.
  const mounted = useRef(true);
  const counters = useRef<GaRequestCounters>(initialGaCounters());
  // The existing job identical arguments returned (and its status then): its notice outlives the job-end notice.
  const redisplayed = useRef<{ jobId: string; status: string } | null>(null);
  const live = useRef({ summary: selected });
  live.current = { summary: selected };
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const bumped = { ...counters.current };
      for (const area of GA_AREAS) bumped[area] += 1;
      counters.current = bumped;
    };
  }, []);
  const stamp = (area: GaArea): GaStamp => {
    const next = nextGaRequest(counters.current, area, runId, gaStampHandle(area, live.current.summary));
    counters.current = next.counters;
    return next.stamp;
  };
  const current = (area: GaArea, captured: GaStamp) => mounted.current && gaResponseCurrent(captured,
    { runId, handle: gaStampHandle(area, live.current.summary), area, seq: counters.current[area] });
  const update = (patch: Partial<GaForm>) => setForm(previous => patchGaForm(previous, patch));
  const setGa = (key: SequenceGaKey, value: string) =>
    setForm(previous => patchGaForm(previous, { ga: { ...previous.ga, [key]: value } }));

  // ---- run-wide reads (on mount = on entering the tab, and on retry); GET only ----
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    const captured = stamp("candidate_sets"), controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)]);
    setSets({ status: "loading" });
    (async () => {
      const first = await api.mutationCandidateSets(runId, 0, LIST_LIMIT, signal);
      if (first.schema !== "mutation_candidate_set_list@1") throw new Error("변이 후보 집합 목록 형식이 다릅니다.");
      const rows = [...first.rows];
      while (rows.length < first.total) {
        const page = await api.mutationCandidateSets(runId, rows.length, LIST_LIMIT, signal);
        if (page.total !== first.total || !page.rows.length) throw new Error("후보 집합 목록이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
        rows.push(...page.rows);
      }
      return rows;
    })().then(rows => { if (current("candidate_sets", captured)) setSets({ status: "ready", value: rows }); })
      .catch(e => { if (current("candidate_sets", captured) && !controller.signal.aborted)
        setSets({ status: "error", message: `변이 후보 집합 목록 읽기 실패: ${errorText(e)}` }); });
    return () => controller.abort();
  }, [runId, setsReload]);

  // Ligand 3D SDF imports (made in the ligand tab's docking area).
  useEffect(() => {
    const captured = stamp("prereq"), controller = new AbortController();
    setPrereq({ status: "loading" });
    api.dockingPrerequisites(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)])).then(value => {
      if (!current("prereq", captured)) return;
      if (value.schema !== "docking_prerequisites@1") throw new Error("도킹 입력 목록 형식이 다릅니다.");
      setPrereq({ status: "ready", value });
    }).catch(e => { if (current("prereq", captured) && !controller.signal.aborted)
      setPrereq({ status: "error", message: `도킹 입력 목록 읽기 실패: ${errorText(e)}` }); });
    return () => controller.abort();
  }, [runId, prereqReload]);

  useEffect(() => {
    const captured = stamp("list"), controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)]);
    setResults({ status: "loading" });
    (async () => {
      const first = await api.sequenceGaResults(runId, 0, LIST_LIMIT, signal);
      if (first.schema !== "sequence_ga_list@1") throw new Error("서열 GA 요약 목록 형식이 다릅니다.");
      const rows = [...first.rows];
      while (rows.length < first.total) {
        const page = await api.sequenceGaResults(runId, rows.length, LIST_LIMIT, signal);
        if (page.total !== first.total || !page.rows.length) throw new Error("요약 목록이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
        rows.push(...page.rows);
      }
      return rows;
    })().then(rows => { if (current("list", captured)) setResults({ status: "ready", value: rows }); })
      .catch(e => { if (current("list", captured) && !controller.signal.aborted)
        setResults({ status: "error", message: `서열 GA 요약 목록 읽기 실패: ${errorText(e)}` }); });
    return () => controller.abort();
  }, [runId, resultsReload]);

  // After a remount the durable job list tells whether a sequence GA job of this run is still queued or running.
  useEffect(() => {
    const captured = stamp("job"), controller = new AbortController();
    api.sequenceGaJobs(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)])).then(list => {
      if (!current("job", captured)) return;
      const running = gaActiveJob<SequenceGaJob>(list, runId);
      if (running) setJob(previous => previous ?? running);
    }).catch(() => undefined);
    return () => controller.abort();
  }, [runId]);

  // Stored job state (status and staged counts) is read again while the job is queued, claimed or running.
  useEffect(() => {
    if (!job || !dockingJobActive(job)) return;
    let active = true;
    const jobId = job.job_id;
    const timer = window.setInterval(() => {
      void api.sequenceGaJob(runId, jobId).then(value => {
        if (active && mounted.current && value.run_id === runId && value.job_id === jobId)
          setJob(previous => previous?.job_id === jobId ? value : previous);
      }).catch(() => undefined);
    }, POLL_MS);
    return () => { active = false; window.clearInterval(timer); };
  }, [runId, job?.job_id, job?.status]);

  // A finished job (any end state) refreshes the summary list; no summary is opened automatically. An existing job
  // shown again for identical arguments keeps its own notice while it has the status it had then.
  useEffect(() => {
    if (!job) return;
    setNotice(previous => ligandNoticeAfterJob(previous, job.status));
    if (!dockingJobActive(job)) {
      setResultsReload(value => value + 1);
      const handle = job.sequence_ga?.summary_handle ?? gaJobResult(job);
      const shownAgain = redisplayed.current?.jobId === job.job_id && redisplayed.current.status === job.status;
      if (handle && !shownAgain)
        setNotice(`서열 GA 요약이 저장되었습니다 (${shortHandle(handle)}). 아래 서열 GA 결과 목록에서 직접 고르세요.`);
    }
  }, [job?.job_id, job?.status]);
  /* eslint-enable react-hooks/exhaustive-deps */

  // ---- opened summary, one row's detail, reports ----
  const switchBlocked = gaSwitchBlockedReason({ busy, job });
  function openSummary(handle: string) {
    if (switchBlocked && handle !== selected) return;
    setSelected(handle); live.current = { summary: handle };
    setGeneration(0); setSort(null); setReport(null); setIndividual(null);
    const captured = stamp("detail");
    setDetail({ handle, load: { status: "loading" } });
    api.sequenceGaResult(runId, handle, AbortSignal.timeout(TIMEOUT_MS)).then(value => {
      if (!current("detail", captured)) return;
      if (value.schema !== "sequence_ga_detail@1" || value.handle !== handle)
        throw new Error("서열 GA 요약이 고른 handle과 다릅니다.");
      setDetail({ handle, load: { status: "ready", value } });
    }).catch(e => { if (current("detail", captured))
      setDetail({ handle, load: { status: "error", message: `서열 GA 요약 읽기 실패: ${errorText(e)}` } }); });
  }
  const opened = detail && detail.handle === selected && detail.load.status === "ready" ? detail.load.value : null;
  const openedHandle = opened?.handle ?? null;

  /** One individual (its key) or the wild-type reference row (`wild_type`) of the opened summary; keys only. */
  function openIndividual(key: string) {
    if (!openedHandle) return;
    const handle = openedHandle, captured = stamp("individual");
    setIndividual({ handle, key, load: { status: "loading" } });
    api.sequenceGaIndividual(runId, handle, key, AbortSignal.timeout(TIMEOUT_MS)).then(value => {
      if (!current("individual", captured)) return;
      if (value.schema !== "sequence_ga_individual@1" || value.summary_handle !== handle || value.key !== key)
        throw new Error("개체 상세가 고른 요약·키와 다릅니다.");
      setIndividual({ handle, key, load: { status: "ready", value } });
    }).catch(e => { if (current("individual", captured))
      setIndividual({ handle, key, load: { status: "error", message: `개체 상세 읽기 실패: ${errorText(e)}` } }); });
  }
  const shownIndividual = individual && individual.handle === openedHandle ? individual : null;
  const individualKey = shownIndividual ? `${shownIndividual.handle} ${shownIndividual.key}` : null;
  useEffect(() => {
    if (individualKey) document.querySelector('[data-testid="sequence-ga-panel"] [data-sequence-ga-area="individual"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [individualKey]);

  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    if (!openedHandle) return;
    const handle = openedHandle, captured = stamp("report_list"), controller = new AbortController();
    setReportList({ handle, load: { status: "loading" } });
    api.reports(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)])).then(rows => {
      if (!current("report_list", captured)) return;
      setReportList({ handle, load: { status: "ready", value: rows.filter(row =>
        row.analysis_type === REPORT_TYPE && row.result_handle === handle) } });
    }).catch(e => { if (current("report_list", captured) && !controller.signal.aborted)
      setReportList({ handle, load: { status: "error", message: `보고서 목록 읽기 실패: ${errorText(e)}` } }); });
    return () => controller.abort();
  }, [openedHandle, reportListReload]);
  /* eslint-enable react-hooks/exhaustive-deps */
  const reportListLoad = reportList && reportList.handle === openedHandle ? reportList.load : null;

  // ---- preflight, limit approval, job actions ----
  const gaCheck = checkGaInput(form.ga);
  const check = gaArgs(form);
  const argsKey = check.ok ? gaArgsKey(check.args) : null;
  const preflightState: GaPreflightState = preflight && preflight.load.status === "ready" && preflight.key === argsKey
    ? { key: preflight.key, value: preflight.load.value } : null;
  const shownPreflight = preflightState?.value ?? null;
  const startBlocked = gaStartBlockedReason({ capability, busy, activeJob: job, check, preflight: preflightState,
    dryRun: run.dry_run });

  async function runPreflight(args: SequenceGaArgs) {
    const key = gaArgsKey(args), captured = stamp("preflight");
    setPreflight({ key, load: { status: "loading" } });
    try {
      const value = await api.sequenceGaPreflight(runId, args, AbortSignal.timeout(TIMEOUT_MS));
      if (!current("preflight", captured)) return;
      if (value.schema !== "sequence_ga_preflight@1" || value.starts_job !== false)
        throw new Error("시작 전 확인 응답 형식이 다릅니다.");
      setPreflight({ key, load: { status: "ready", value } });
    } catch (e) {
      if (current("preflight", captured))
        setPreflight({ key, load: { status: "error", message: `시작 전 확인 실패: ${errorText(e)}` } });
    }
  }

  // The only caller of the sequence GA limit approval route: a person's click on the button below.
  async function approveLimits() {
    if (!check.ok || !gaLimitApprovalOffered(shownPreflight, run.dry_run)) return;
    const args = check.args, key = gaArgsKey(args), captured = stamp("limit");
    setApproval({ key, load: { status: "loading" } });
    try {
      const value = await api.sequenceGaLimitApproval(runId, args);
      if (!current("limit", captured)) return;
      setApproval({ key, load: { status: "ready", value } });
      await runPreflight(args);
    } catch (e) {
      if (current("limit", captured)) setApproval({ key, load: { status: "error", message: `한도 증액 실패: ${errorText(e)}` } });
    }
  }

  async function start(before: SequenceGaJob) {
    const captured = stamp("job");
    setBusy(true); setJobError(""); setNotice("");
    try {
      const value = await api.startJob(runId, before.job_id) as unknown as SequenceGaJob;
      if (!current("job", captured)) return;
      if (value.run_id !== runId || value.job_id !== before.job_id) throw new Error("시작 응답이 이 작업과 다릅니다.");
      setApprovalPending(false); setJob(value);
    } catch (e) {
      if (!current("job", captured)) return;
      if (e instanceof ApiError && gaApprovalRequired(e.status, e.approval)) { setApprovalPending(true); return; }
      // The start may have taken effect although its response was lost (proxy limit): the stored job decides.
      const stored = await api.sequenceGaJob(runId, before.job_id).catch(() => null);
      if (!current("job", captured)) return;
      if (stored && stored.run_id === runId && stored.job_id === before.job_id) setJob(stored);
      if (!stored || !ligandStartProgressed(before, stored)) setJobError(`작업 시작 실패: ${errorText(e)}`);
    } finally { if (mounted.current) setBusy(false); }
  }

  // "서열 GA 시작": one click submits these exact arguments and starts the saved job (never by itself).
  async function submit() {
    if (startBlocked || !check.ok) return;
    const captured = stamp("job");
    setBusy(true); setJobError(""); setNotice(""); setApprovalPending(false);
    try {
      const result = await api.submitSequenceGa(runId, check.args);
      if (!current("job", captured)) return;
      if ("plan_only" in result) { setNotice("dry-run run이라 계획만 만들었습니다. 실제 계산과 결과 객체는 없습니다."); return; }
      if (result.run_id !== runId || result.protocol_id !== GA_PROTOCOL) throw new Error("제출 응답이 요청과 다릅니다.");
      setJob(result);
      if (result.status !== "queued") {
        redisplayed.current = { jobId: result.job_id, status: result.status };
        setNotice(`같은 입력의 기존 서열 GA 작업을 다시 표시합니다 · ${result.job_id} · ${result.status} (새 작업을 만들지 않았습니다)`);
        return;
      }
      await start(result);
    } catch (e) { if (current("job", captured)) setJobError(`서열 GA 작업 제출 실패: ${errorText(e)}`); }
    finally { if (mounted.current) setBusy(false); }
  }

  // The run's first expensive computation is approved here (M7 way), only after the server asked for it.
  async function approveFirstCall() {
    if (!job) return;
    const captured = stamp("job");
    setBusy(true); setJobError("");
    try {
      await api.approveOpenmm(runId);
      if (!current("job", captured)) return;
      setApprovalPending(false); setNotice(LIGAND_APPROVAL_NOTICE);
    } catch (e) { if (current("job", captured)) setJobError(`승인 실패: ${errorText(e)}`); }
    finally { if (mounted.current) setBusy(false); }
  }

  // Not tied to the job request number or `busy`: a held start request keeps its own answer.
  async function cancelJob() {
    if (!job || !dockingCancelEnabled({ job, cancelling })) return;
    const captured = stamp("cancel"), jobId = job.job_id;
    setCancelling(true);
    try {
      const value = (await api.cancelJob(runId, jobId)).job as unknown as SequenceGaJob;
      if (current("cancel", captured) && value.run_id === runId && value.job_id === jobId)
        setJob(previous => previous?.job_id === jobId ? value : previous);
    } catch (e) { if (current("cancel", captured)) setJobError(`작업 취소 실패: ${errorText(e)}`); }
    finally { if (mounted.current) setCancelling(false); }
  }

  async function makeReport() {
    if (!opened || !selected || report?.load.status === "loading") return;
    const handle = selected, captured = stamp("report");
    setReport({ handle, load: { status: "loading" } });
    try {
      const artifact = await api.createSequenceGaReport(runId, handle, AbortSignal.timeout(60000));
      if (gaReportSavedForRun(captured, runId) && mounted.current) {
        onReportCreated(runId); setReportListReload(value => value + 1);
      }
      if (!current("report", captured)) return;
      if (!gaReportMatches(artifact, handle)) throw new Error("보고서가 고른 서열 GA 요약과 다릅니다.");
      setReport({ handle, load: { status: "ready", value: artifact } });
    } catch (e) {
      if (current("report", captured)) setReport({ handle, load: { status: "error", message: `보고서 만들기 실패: ${errorText(e)}` } });
    }
  }

  // ---- derived ----
  const setRows = sets.status === "ready" ? sets.value : undefined;
  const summaryRows = results.status === "ready" ? results.value : undefined;
  const readError = (sets.status === "error" ? sets.message : null) ?? (results.status === "error" ? results.message : null)
    ?? (detail?.handle === selected && detail?.load.status === "error" ? detail.load.message : null);
  const areaState = gaAreaState({ runId, capability, candidateSets: setRows, summaries: summaryRows,
    loading: sets.status === "loading" || results.status === "loading" || detail?.load.status === "loading",
    error: readError, job, detailOpen: !!opened });
  const prereqValue = prereq.status === "ready" ? prereq.value : null;
  const ligandSdfs = prereqValue ? importsOfKind(prereqValue.imports, "ligand_sdf") : [];
  const options = setRows ? candidateSetOptions(setRows) : [];
  // M26: the chosen set's "촉매 잔기 검사 안 함" mark from its stored catalytic check status (nothing for `checked`).
  const chosenCatalytic = catalyticBadge(setRows?.find(row => row.handle === form.candidateSet)?.catalytic_status);
  // A `claimed` job blocked on a reason the queue's `start` accepts again (the first expensive-call approval, the
  // global concurrency / cleanup / ledger waits) waits for 작업 시작 like a saved job (lib `gaJobPhase`).
  const phase = gaJobPhase(job, approvalPending);
  const approvalLoad = approval && approval.key === argsKey ? approval.load : null;
  const preflightLoad = preflight && preflight.key === argsKey ? preflight.load : null;
  const spaceLines = gaSpaceLines(shownPreflight);
  const heading = <div className="mw-mutation-head">
    <h2 className="mw-mutation-heading">단백질 공학 · {AREA_TITLE}</h2>
    <span className="mw-badge" data-testid="sequence-ga-state">{GA_STATE_TEXT[areaState.state]}</span>
  </div>;

  // No readable M20 candidate set: the reason only (no numbers); the list can be read again after making one above.
  if (areaState.state === "unavailable") return <section className="mw-mutation mw-seqga" aria-label={AREA_TITLE}
    data-testid="sequence-ga-panel" data-ga-state="unavailable">
    {heading}
    <p className="mw-mutation-unavailable" role="status" data-testid="sequence-ga-no-candidate-set">
      <b>{GA_STATE_TEXT.unavailable}</b>: {areaState.reason}</p>
    <div className="mw-mutation-inline">
      <Button size="sm" data-testid="sequence-ga-candidate-sets-refresh" onClick={() => setSetsReload(value => value + 1)}>
        후보 집합 목록 다시 읽기</Button>
    </div>
  </section>;

  return <section className="mw-mutation mw-seqga" aria-label={AREA_TITLE} data-testid="sequence-ga-panel"
    data-ga-state={areaState.state}>
    {heading}
    {areaState.state === "failed" && <p role="alert" className="mw-mutation-error" data-testid="sequence-ga-failure">
      {areaState.message}</p>}
    {areaState.state === "empty" && <p role="status" className="mw-mutation-null" data-testid="sequence-ga-empty">
      {areaState.message}</p>}
    <p className="mw-mutation-note">고른 M20 변이 후보 집합의 위치와 허용 아미노산 안에서, 서로 다른 위치의 변이를 하나 이상 묶은
      개체를 유전 알고리즘(GA)이 세대마다 고릅니다. 개체마다 변이 구조를 모델링한 뒤 리간드를 자유 도킹하며 점수는 {SCORE_LABEL}입니다.
      화면은 저장된 값을 표시만 하며 점수·전위·조합 수·집계를 계산하지 않습니다.</p>
    <p className="mw-mutation-note mw-mono" data-testid="sequence-ga-capability">
      {capability.tool_id} · {capability.protocol_id} · {capability.engine} · 새 평가 1건마다 비싼 계산{" "}
      {UNITS_PER_EVALUATION}단위(시작 전에 한 번에 예약)</p>
    {run.dry_run && <p role="status" className="mw-mutation-unavailable" data-testid="sequence-ga-dry-run">
      dry-run run: 서열 GA를 시작하면 계획만 만들며 실제 계산과 결과 객체가 없습니다. 한도 증액도 하지 않습니다.</p>}

    <Section area="input" title="① 입력 (변이 후보 집합 · 모델링 확인 · 리간드 · 상자 · 도킹 값)">
      <div className="mw-mutation-inline">
        <label className="mw-mutation-check">변이 후보 집합 (M20)
          <select className="mw-select" data-testid="sequence-ga-candidate-set" value={form.candidateSet ?? ""}
            onChange={event => update({ candidateSet: event.target.value || null })}>
            <option value="">선택</option>
            {options.map(option => {
              const row = setRows?.find(item => item.handle === option.handle);
              const badge = catalyticBadge(row?.catalytic_status);
              return <option key={option.handle} value={option.handle} disabled={!option.selectable}>
                {`${shortHandle(option.handle)} · ${option.text}${badge ? ` · ${badge.text}` : ""}${row?.structure_origin
                  ? " · 보완 구조" : ""}`}</option>;
            })}
          </select></label>
        <Button size="sm" data-testid="sequence-ga-candidate-sets-refresh" disabled={sets.status === "loading"}
          onClick={() => setSetsReload(value => value + 1)}>후보 집합 목록 다시 읽기</Button>
      </div>
      {chosenCatalytic && <p className="mw-catalytic-mark" data-testid="sequence-ga-catalytic">
        <span className="mw-catalytic-badge">{chosenCatalytic.text}</span>
        <span className="mw-catalytic-detail" data-testid="sequence-ga-catalytic-detail">{chosenCatalytic.detail}</span></p>}
      <p className="mw-mutation-note">집합이 하나뿐이어도 자동으로 고르지 않습니다. 위치·보호 잔기·허용 아미노산은 고른 집합 그대로 쓰며 여기서
        바꾸지 않습니다(바꾸려면 위 변이 후보 영역에서 새 집합을 만드세요).</p>
      {sets.status === "loading" && <p className="mw-mutation-note" aria-busy="true">변이 후보 집합 목록을 읽는 중</p>}
      {sets.status === "error" && <ErrorLine message={sets.message} onRetry={() => setSetsReload(value => value + 1)}
        testId="sequence-ga-candidate-sets-error" />}
      <p className="mw-mutation-note" data-testid="sequence-ga-model-note">{MODEL_NOTE}</p>
      <fieldset className="mw-mutation-choices" data-testid="sequence-ga-confirmations">
        <legend>모델링 확인 (두 항목 모두)</legend>
        <label><input type="checkbox" data-testid="sequence-ga-confirm-selection" checked={form.selectionConfirmed}
          onChange={event => update({ selectionConfirmed: event.target.checked })} />
          {CONFIRMATION_LABEL.selection_policy}</label>
        <label><input type="checkbox" data-testid="sequence-ga-confirm-hydrogen" checked={form.hydrogenConfirmed}
          onChange={event => update({ hydrogenConfirmed: event.target.checked })} />
          {CONFIRMATION_LABEL.hydrogen_policy}</label>
      </fieldset>
      <p className="mw-mutation-note" data-testid="sequence-ga-mode-note">{MODE_NOTE}</p>
      <PairInputs form={form} update={update} runId={runId} prereq={prereq} ligandSdfs={ligandSdfs}
        onReloadPrereq={() => setPrereqReload(value => value + 1)} idPrefix="sequence-ga"
        ligandSourceReason={ligandSourceDisabledReason}
        seedLabel={`평가 seed (개체 모델링·qvina 도킹 공용, 필수, ${SEED_MIN}–${SEED_MAX})`}
        acknowledgementLegend="제출 전 확인 (세 항목 모두, 야생형 기준 행과 모든 개체 도킹에 같이 적용)" />
    </Section>

    <Section area="parameters" title="② GA 파라미터">
      <p className="mw-mutation-note">{SEED_NOTE}</p>
      <div className="mw-ga-params" data-testid="sequence-ga-parameters">
        {GA_PARAMETERS.map(item => {
          const error = gaCheck.fields[item.key];
          return <label key={item.key} className="mw-ga-param" data-ga-param={item.key} data-invalid={error ? true : undefined}>
            <span className="mw-ga-param__label">{item.label}</span>
            <input className="mw-mutation-input" data-testid={`sequence-ga-param-${item.key}`}
              inputMode={item.integer ? "numeric" : "decimal"} value={form.ga[item.key]} aria-invalid={!!error}
              onChange={event => setGa(item.key, event.target.value)} />
            <span className="mw-ga-param__range mw-mono" data-testid={`sequence-ga-range-${item.key}`}>{gaRangeText(item.key)}</span>
            {error && <span className="mw-ga-param__error" data-testid={`sequence-ga-error-${item.key}`}>{error}</span>}
          </label>;
        })}
      </div>
      <div className="mw-mutation-inline">
        <Button size="sm" data-testid="sequence-ga-defaults"
          onClick={() => setForm(previous => patchGaForm(previous, { ga: resetGaDefaults(previous.ga) }))}>기본값으로</Button>
        <span className="mw-mutation-note">GA seed는 기본값이 없어 입력한 값을 그대로 둡니다.</span>
      </div>
      {gaCheck.ok ? <Facts lines={gaParameterLines(gaCheck.ga)} testId="sequence-ga-effective" />
        : <p className="mw-mutation-note" data-testid="sequence-ga-effective-blocked">입력 오류를 고치면 유효 파라미터 요약이 보입니다.</p>}
      <div className="mw-mutation-group" data-testid="sequence-ga-space" data-space-size={shownPreflight?.space?.size}
        data-effective-max-mutations={shownPreflight?.space?.effective_max_mutations}>
        <span className="mw-eyebrow">조합 공간 (서버 시작 전 확인 값)</span>
        {spaceLines.length ? <Facts lines={spaceLines} />
          : <p className="mw-mutation-note" data-testid="sequence-ga-space-pending">{SPACE_PENDING_TEXT}</p>}
      </div>
      {!check.ok && <ul className="mw-mutation-errors" data-testid="sequence-ga-input-errors">
        {check.errors.map(error => <li key={error}>{error}</li>)}</ul>}
    </Section>

    <Section area="preflight" title="③ 시작 전 확인" state={preflightLoad?.status}>
      <p className="mw-mutation-notice" data-testid="sequence-ga-budget-note">{BUDGET_NOTE}</p>
      <div className="mw-mutation-inline">
        <Button size="sm" data-testid="sequence-ga-preflight" disabled={!check.ok || preflightLoad?.status === "loading"}
          onClick={() => { if (check.ok) void runPreflight(check.args); }}>시작 전 확인 보기</Button>
        {preflight && preflight.key !== argsKey && <span className="mw-mutation-note" data-testid="sequence-ga-preflight-stale">
          입력이 바뀌었습니다. 시작 전 확인을 다시 보세요.</span>}
      </div>
      {preflightLoad?.status === "loading" && <p className="mw-mutation-note" aria-busy="true">시작 전 확인을 읽는 중</p>}
      {preflightLoad?.status === "error" && <ErrorLine message={preflightLoad.message} testId="sequence-ga-preflight-error" />}
      {shownPreflight && <PreflightView preflight={shownPreflight} />}
      {gaLimitApprovalOffered(shownPreflight, run.dry_run) && <div className="mw-mutation-inline" data-testid="sequence-ga-limit-area">
        <Button size="sm" data-testid="sequence-ga-limit-approve" disabled={approvalLoad?.status === "loading"}
          onClick={() => void approveLimits()}>{LIMIT_RAISE_LABEL}</Button>
        <span className="mw-mutation-note">사람이 직접 하는 승인입니다. 서버가 누른 시점의 부족분만 올리며(활동 시간은 60초 여유 포함)
          되돌리지 않습니다. 계산 승인을 대신하지 않고, 올린 뒤 저절로 시작하지 않습니다.</span>
      </div>}
      {approvalLoad?.status === "loading" && <p className="mw-mutation-note" aria-busy="true">한도를 올리는 중</p>}
      {approvalLoad?.status === "ready" && <p role="status" className="mw-mutation-note" data-testid="sequence-ga-limit-done"
        data-raised={approvalLoad.value.raised}>{gaLimitApprovalText(approvalLoad.value)}</p>}
      {approvalLoad?.status === "error" && <ErrorLine message={approvalLoad.message} testId="sequence-ga-limit-error" />}
    </Section>

    <Section area="start" title="④ 서열 GA 시작 · 진행">
      <div className="mw-mutation-inline">
        <Button size="sm" variant="primary" data-testid="sequence-ga-start" disabled={!!startBlocked}
          title={startBlocked ?? undefined} onClick={() => void submit()}>서열 GA 시작</Button>
        {startBlocked && <span className="mw-mutation-note" data-testid="sequence-ga-start-blocked">{startBlocked}</span>}
      </div>
      {(job || notice || jobError) && <div className="mw-mutation-group" data-testid="sequence-ga-job-area">
        {job && <div data-testid="sequence-ga-job" data-ga-job-phase={phase} data-ga-job-status={job.status}
          data-ga-job-id={job.job_id} data-reference-recorded={job.sequence_ga?.reference_recorded}
          data-generations-complete={job.sequence_ga?.generations_complete}
          data-individuals-finished={job.sequence_ga?.individuals_finished}
          data-summary-handle={job.sequence_ga?.summary_handle ?? undefined}>
          <p className="mw-mutation-note" role="status">{gaJobText(job, approvalPending)}</p>
          <p className="mw-mutation-note mw-mono">{GA_TOOL} · 작업 {job.status} · {job.job_id}</p>
          {job.sequence_ga && <p className="mw-mutation-note" data-testid="sequence-ga-progress">{gaProgressText(job.sequence_ga)}</p>}
          {job.blocked_reason && <p className="mw-mutation-note">시작 대기 이유: {gaReasonText(job.blocked_reason)}</p>}
          <div className="mw-mutation-inline">
            {phase === "awaiting_approval" && <Button size="sm" data-testid="sequence-ga-job-approve" disabled={busy}
              onClick={() => void approveFirstCall()}>비싼 계산 승인</Button>}
            {phase === "saved" && <Button size="sm" data-testid="sequence-ga-job-start" disabled={busy || run.dry_run}
              onClick={() => void start(job)}>작업 시작</Button>}
            {dockingJobActive(job) && <Button size="sm" data-testid="sequence-ga-job-cancel"
              disabled={!dockingCancelEnabled({ job, cancelling })} onClick={() => void cancelJob()}>작업 취소</Button>}
          </div>
        </div>}
        {notice && <p role="status" className="mw-mutation-note" data-testid="sequence-ga-notice">{notice}</p>}
        {jobError && <ErrorLine message={jobError} testId="sequence-ga-job-error" />}
      </div>}
    </Section>

    <Section area="results" title="⑤ 서열 GA 결과" state={results.status}>
      {results.status === "loading" && <p className="mw-mutation-note" aria-busy="true">서열 GA 요약 목록을 읽는 중</p>}
      {results.status === "error" && <ErrorLine message={results.message} onRetry={() => setResultsReload(value => value + 1)}
        testId="sequence-ga-list-error" />}
      {results.status === "ready" && (!results.value.length
        ? <p className="mw-mutation-note" data-testid="sequence-ga-list-empty">이 run에 서열 GA 결과가 없습니다.</p>
        : <fieldset className="mw-mutation-choices" data-testid="sequence-ga-list">
          <legend>서열 GA 결과 선택 (최신 순, 자동으로 고르지 않음)</legend>
          {results.value.map(row => <label key={row.handle} data-ga-summary={row.handle} data-valid={row.valid}
            data-ga-status={row.status ?? undefined}>
            <input type="radio" name={`sequence-ga-summary-${runId}`} checked={selected === row.handle}
              disabled={!row.valid || (!!switchBlocked && selected !== row.handle)}
              aria-label={`서열 GA 요약 ${shortHandle(row.handle)}`} onChange={() => openSummary(row.handle)} />
            <span className="mw-mono">{shortHandle(row.handle)} · {gaListRowText(row)}</span>
            {row.structure_origin && <span className="mw-catalytic-mark" data-testid="sequence-ga-list-repaired"
              data-repair-record={row.structure_origin.repair_record}><span className="mw-catalytic-badge">보완 구조</span></span>}
          </label>)}
        </fieldset>)}
      {switchBlocked && results.status === "ready" && results.value.length > 0 && <p className="mw-mutation-note" role="status"
        data-testid="sequence-ga-switch-blocked">{switchBlocked}</p>}
      {results.status !== "loading" && <Button size="sm" data-testid="sequence-ga-list-refresh"
        onClick={() => setResultsReload(value => value + 1)}>서열 GA 결과 목록 다시 읽기</Button>}
      {detail?.handle === selected && detail.load.status === "loading" && <p className="mw-mutation-note" aria-busy="true">
        서열 GA 요약을 읽는 중</p>}
      {detail?.handle === selected && detail.load.status === "error" && <ErrorLine message={detail.load.message}
        onRetry={() => selected && openSummary(selected)} testId="sequence-ga-detail-error" />}
      {opened?.structure_origin && <div className="mw-mutation-notice" role="status" data-testid="sequence-ga-repair-origin"
        data-repair-record={opened.structure_origin.repair_record}
        data-repaired-structure={opened.structure_origin.repaired_structure}>
        <span className="mw-catalytic-badge">보완 구조</span>
        {opened.structure_origin.statements.map(item => <p key={item.id} data-statement={item.id}>{item.text}</p>)}
        <p className="mw-mono">보완 기록 {shortHandle(opened.structure_origin.repair_record)} · 원본{" "}
          {shortHandle(opened.structure_origin.source_structure)} (화면 표시만, 서열 GA 보고서에는 이 사실이 들어가지 않음)</p>
        {onOpenRepairRecord && <Button size="sm" data-testid="sequence-ga-repair-origin-open"
          onClick={() => opened.structure_origin && onOpenRepairRecord(runId, opened.structure_origin.repair_record)}>
          보완 기록 열기</Button>}
      </div>}
      {opened && <GaResult detail={opened} generation={generation}
        onGeneration={index => { setGeneration(index); setSort(null); }}
        sort={sort} onSort={key => setSort(previous => nextIndividualSort(previous, key))} onOpen={openIndividual}
        openKey={shownIndividual?.key ?? null} />}
      {opened && <div className="mw-mutation-group" aria-label="서열 GA 보고서" data-testid="sequence-ga-report-area">
        <span className="mw-eyebrow">보고서 (저장된 요약만 인용)</span>
        <div className="mw-mutation-inline">
          <Button size="sm" data-testid="sequence-ga-report" disabled={report?.handle === selected && report.load.status === "loading"}
            onClick={() => void makeReport()}>보고서 만들기</Button>
        </div>
        {report?.handle === selected && report.load.status === "loading" && <p className="mw-mutation-note" aria-busy="true">
          보고서를 만드는 중</p>}
        {report?.handle === selected && report.load.status === "ready" && <p role="status" className="mw-mutation-note"
          data-testid="sequence-ga-report-done" data-report-handle={report.load.value.handle}>
          서열 GA 보고서를 저장했습니다 · {shortHandle(report.load.value.handle)}. 지식·보고서 탭의 보고서 목록에서도 열고 받을 수 있습니다.</p>}
        {report?.handle === selected && report.load.status === "error" && <ErrorLine message={report.load.message}
          testId="sequence-ga-report-error" />}
        {reportListLoad?.status === "loading" && <p className="mw-mutation-note" aria-busy="true">보고서 목록을 읽는 중</p>}
        {reportListLoad?.status === "error" && <ErrorLine message={reportListLoad.message}
          onRetry={() => setReportListReload(value => value + 1)} testId="sequence-ga-report-list-error" />}
        {reportListLoad?.status === "ready" && (!reportListLoad.value.length
          ? <p className="mw-mutation-note" data-testid="sequence-ga-report-list-empty">이 요약의 저장된 보고서가 없습니다.</p>
          : <ul className="mw-mutation-list" data-testid="sequence-ga-report-list">
            {reportListLoad.value.map(row => <li key={row.handle} data-report-handle={row.handle}>
              <span className="mw-mono">이벤트 #{row.created_seq} · {shortHandle(row.handle)}</span>
              <a className="mw-btn mw-btn--sm" data-testid="sequence-ga-report-markdown"
                href={api.reportDownload(runId, row.handle, "markdown")} download>Markdown 내려받기</a>
              <a className="mw-btn mw-btn--sm" data-testid="sequence-ga-report-json"
                href={api.reportDownload(runId, row.handle, "json")} download>JSON 내려받기</a>
            </li>)}
          </ul>)}
      </div>}
    </Section>

    {opened && shownIndividual && <Section area="individual" title="⑥ 개체 상세 (저장된 모델 값과 M18 도킹 결과)"
      state={shownIndividual.load.status}>
      {shownIndividual.load.status === "loading" && <p className="mw-mutation-note" aria-busy="true">개체 상세를 읽는 중</p>}
      {shownIndividual.load.status === "error" && <ErrorLine message={shownIndividual.load.message}
        onRetry={() => openIndividual(shownIndividual.key)} testId="sequence-ga-individual-error" />}
      {shownIndividual.load.status === "ready" && <IndividualDetail read={shownIndividual.load.value} runId={runId}
        summaryHandle={shownIndividual.handle} />}
    </Section>}
  </section>;
}

function PreflightView({ preflight }: { preflight: SequenceGaPreflight }) {
  if (!preflight.admission.admitted)
    return <p className="mw-mutation-error" role="alert" data-testid="sequence-ga-preflight-refused"
      data-reason-code={preflight.admission.reason_code ?? undefined}>시작할 수 없습니다: {gaPreflightRefusalText(preflight)}</p>;
  return <div className="mw-docking-result" data-testid="sequence-ga-preflight-view"
    data-reserved-units={preflight.reserved_units ?? undefined}
    data-reserved-evaluations={preflight.reserved_evaluations ?? undefined}
    data-reusable={preflight.reusable_count ?? undefined} data-reference-reusable={preflight.reference_reusable ?? undefined}
    data-shortfall-calls={preflight.shortfall?.expensive_calls} data-shortfall-wall={preflight.shortfall?.wall_clock_s}
    data-may-be-partial={preflight.full_run_may_be_partial ?? undefined}
    data-heavy-atom-warning={preflight.heavy_atom_warning ?? undefined} data-space-size={preflight.space?.size}>
    <dl className="mw-ligand-facts mw-docking-summary">
      {gaPreflightLines(preflight).map(([label, value]) => <div key={label} className="mw-ligand-fact"
        data-preflight-line={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
    {preflight.existing_job && <p className="mw-mutation-note" role="status" data-testid="sequence-ga-existing-job"
      data-job-id={preflight.existing_job.job_id}>{gaExistingJobText(preflight.existing_job)}</p>}
    {preflight.statements && preflight.statements.length > 0 && <ul className="mw-mutation-list"
      data-testid="sequence-ga-preflight-statements">
      {preflight.statements.map(item => <li key={item.id} data-statement={item.id}>{item.text}</li>)}</ul>}
  </div>;
}

const SORT_HEADERS: { key: IndividualSortKey; label: string }[] = [{ key: "slot", label: "자리" },
  { key: "key", label: "개체 키" }];

function GaResult({ detail, generation, onGeneration, sort, onSort, onOpen, openKey }: { detail: SequenceGaDetail;
  generation: number; onGeneration: (index: number) => void; sort: IndividualSort;
  onSort: (key: IndividualSortKey) => void; onOpen: (key: string) => void; openKey: string | null }) {
  const summary = detail.summary, values = summary.parameters;
  const generations = detail.generations;
  const shown = generations[generation] ?? generations[0] ?? null;
  const rows = shown ? sortIndividuals(individualRows(shown), sort) : [];
  const reference = referenceRowView(detail.reference);
  const header = (key: IndividualSortKey, label: string) => <th key={key} aria-sort={individualAriaSort(sort, key)}>
    <button type="button" className="mw-docking-sort" data-testid={`sequence-ga-sort-${key}`}
      onClick={() => onSort(key)}>{label}</button></th>;
  return <div className="mw-docking-result" data-testid="sequence-ga-result" data-ga-handle={detail.handle}
    data-ga-status={summary.status} data-stop-reason={summary.stop_reason} data-generations-done={summary.generations_done}>
    <p className="mw-mutation-note mw-mono">서열 GA 요약 {shortHandle(detail.handle)} · 작업 {detail.job_id} · 게시 순번{" "}
      {detail.published_seq}</p>
    <p role="status" className={summary.status === "partial" ? "mw-mutation-unavailable" : "mw-mutation-note"}
      data-testid="sequence-ga-status">서열 GA 상태: {gaStatusText(summary)}</p>
    <ul className="mw-mutation-list" data-testid="sequence-ga-statements">
      {detail.statements.map(item => <li key={item.id} data-statement={item.id}>{item.text}</li>)}</ul>
    <Facts testId="sequence-ga-summary" lines={[...gaSummaryLines(summary),
      ["평가 seed", String(values.seed)],
      ["도킹 값", `exhaustiveness ${values.exhaustiveness} · num_modes ${values.num_modes} · energy_range ` +
        `${decimalHalfUp(values.energy_range, 2)} kcal/mol · cpu ${values.cpu}`],
      ["상자", summary.box ? boxText(summary.box) : "기록 없음"],
      ["후보 집합", summary.candidate_set],
      ["구조", `${summary.structure.handle} · 모델 ${summary.structure.model_number}`],
      ["리간드 SDF", `${summary.ligand.sdf_handle} · SHA-256 ${summary.ligand.sdf_sha256}`],
      ["모델링 정책", `${summary.selection_policy} · ${summary.hydrogen_policy}`]]} />
    <details data-testid="sequence-ga-stored-parameters"><summary>GA 파라미터 (저장값)</summary>
      <Facts lines={gaParameterLines(summary.ga)} /></details>

    <div className="mw-seqga-reference" data-testid="sequence-ga-reference" aria-label={reference.title}
      data-state={detail.reference.state} data-evaluation={detail.reference.evaluation}>
      <span className="mw-eyebrow">{reference.title}</span>
      <p className="mw-mutation-note">{reference.note}</p>
      <dl className="mw-ligand-facts mw-docking-summary">
        <div className="mw-ligand-fact"><dt>키</dt><dd className="mw-mono">{reference.key}</dd></div>
        <div className="mw-ligand-fact"><dt>평가</dt><dd>{reference.evaluation}</dd></div>
        <div className="mw-ligand-fact"><dt>상태</dt><dd>{reference.state}</dd></div>
        <div className="mw-ligand-fact"><dt>{scoreHeaderText()}</dt>
          <dd className="mw-mono" data-testid="sequence-ga-reference-score">{scoreCellText(detail.reference)}</dd></div>
        <div className="mw-ligand-fact"><dt>이유</dt><dd>{reference.reason || "해당 없음"}</dd></div>
      </dl>
      <div className="mw-mutation-inline">
        <Button size="sm" data-testid="sequence-ga-reference-open" aria-pressed={openKey === REFERENCE_KEY}
          onClick={() => onOpen(REFERENCE_KEY)}>야생형 기준 상세 보기</Button>
      </div>
    </div>

    {!generations.length ? <p className="mw-mutation-note" data-testid="sequence-ga-no-generations">
      기록된 세대가 없습니다(야생형 기준 행 평가가 실패했거나 개체를 평가하기 전에 멈춤).</p> : <>
      <div className="mw-ga-tabs" role="tablist" aria-label="세대" data-testid="sequence-ga-generation-tabs">
        {generations.map((item, index) => <button key={item.index} type="button" role="tab"
          aria-selected={shown?.index === item.index} data-testid={`sequence-ga-generation-${item.index}`}
          data-complete={item.complete} onClick={() => onGeneration(index)}>{generationTabText(item)}</button>)}
      </div>
      {shown && <div role="tabpanel" aria-label={generationTabText(shown)} className="mw-docking-result"
        data-testid="sequence-ga-generation-panel" data-generation={shown.index}>
        <p className="mw-mutation-note mw-mono" data-testid="sequence-ga-generation-range">{generationRangeText(shown)}</p>
        <p className="mw-mutation-note">{ORDER_NOTE} 변이 칸을 펼치면 위치마다 후보 번호와 잔기 7필드가 보이고, &quot;개체 상세&quot;는
          아래에 저장된 모델 값과 M18 도킹 결과를 엽니다.</p>
        <div className="mw-mutation-table-wrap">
          <table className="mw-mutation-table" data-testid="sequence-ga-individuals">
            <caption className="mw-mutation-note">{detail.score_label}</caption>
            <thead><tr>
              {SORT_HEADERS.map(item => header(item.key, item.label))}
              <th>변이 (구조 순서)</th><th>출처</th><th>부모</th><th>평가</th><th>상태</th>
              {header("score", scoreHeaderText())}
              <th>이유</th><th>상세</th>
            </tr></thead>
            <tbody>{rows.map(row => <tr key={`${row.position}-${row.key}`} data-position={row.position} data-key={row.key}
              data-origin={row.origin} data-evaluation={row.evaluation ?? "carried"} data-state={row.state}>
              <td className="mw-mono">{row.position + 1}</td>
              <td className="mw-mono">{row.key}</td>
              <td><details className="mw-seqga-mutations" data-testid={`sequence-ga-mutations-${shown.index}-${row.position}`}>
                <summary className="mw-mono">{mutationsText(row.mutations)}</summary>
                <ul className="mw-mutation-list mw-mono">{mutationFieldLines(row.mutations).map(line => <li key={line}>{line}</li>)}</ul>
              </details></td>
              <td>{originText(row)}</td>
              <td className="mw-mono">{parentsText(row)}</td>
              <td>{evaluationText(row.evaluation)}</td>
              <td>{stateText(row.state)}</td>
              <td className="mw-mono" data-score-cell>{scoreCellText(row)}</td>
              <td>{individualReasonText(row)}</td>
              <td><Button size="sm" data-testid={`sequence-ga-open-${shown.index}-${row.position}`}
                aria-pressed={openKey === row.key} onClick={() => onOpen(row.key)}>개체 상세</Button></td>
            </tr>)}</tbody>
          </table>
        </div>
      </div>}
    </>}
  </div>;
}

function IndividualDetail({ read, runId, summaryHandle }: { read: SequenceGaIndividualRead; runId: string;
  summaryHandle: string }) {
  const view = individualDetailView(read);
  // A stored sentence that is not one of the fixed ones: the model values are not shown (never trusted silently).
  if (view.unknownLimitations.length) return <p className="mw-mutation-error" role="alert"
    data-testid="sequence-ga-individual-untrusted" data-key={view.key}>
    저장된 모델 한계 문장이 고정 문장과 다릅니다(값을 보이지 않음): {gaReasonText("evidence_invalid")}</p>;
  return <div className="mw-seqga-detail" data-testid="sequence-ga-individual" data-key={view.key}
    data-is-reference={read.is_reference} data-state={read.state}>
    <p className="mw-mutation-title">{view.title}</p>
    <p className="mw-mutation-note mw-mono">키 {view.key} · 요약 {shortHandle(summaryHandle)}
      {read.pick_index !== null ? ` · pick_index ${read.pick_index}` : ""}
      {read.eval_index !== null ? ` · eval_index ${read.eval_index}` : ""}</p>
    <dl className="mw-ligand-facts mw-docking-summary" data-testid="sequence-ga-detail-facts">
      <div className="mw-ligand-fact"><dt>평가</dt><dd>{view.evaluation}</dd></div>
      <div className="mw-ligand-fact"><dt>상태</dt><dd>{view.state}</dd></div>
      <div className="mw-ligand-fact"><dt>{scoreHeaderText()}</dt>
        <dd className="mw-mono" data-testid="sequence-ga-detail-score">{scoreCellText(read)}</dd></div>
      <div className="mw-ligand-fact"><dt>이유</dt><dd>{view.reason || "해당 없음"}</dd></div>
    </dl>

    <span className="mw-eyebrow">변이 (구조 순서, 후보 번호와 잔기 7필드)</span>
    {view.mutationLines.length ? <ul className="mw-mutation-list mw-mono" data-testid="sequence-ga-detail-mutations">
      {view.mutationLines.map(line => <li key={line}>{line}</li>)}</ul>
      : <p className="mw-mutation-note" data-testid="sequence-ga-detail-mutations-none">변이 없음 (야생형 기준 행)</p>}
    {view.appearanceLines.length > 0 && <>
      <span className="mw-eyebrow">이 요약에서 나온 세대·자리</span>
      <ul className="mw-mutation-list" data-testid="sequence-ga-detail-appearances">
        {view.appearanceLines.map(line => <li key={line}>{line}</li>)}</ul>
    </>}
    {view.missingModelText && <p className="mw-mutation-null" data-testid="sequence-ga-detail-no-model">{view.missingModelText}</p>}

    {view.structureLabel && <div className="mw-mutation-group" data-testid="sequence-ga-detail-model">
      <span className="mw-eyebrow">저장된 모델 값 · {view.structureLabel}</span>
      <Facts lines={view.energyRows} testId="sequence-ga-detail-energy" />
      <ul className="mw-mutation-list" data-testid="sequence-ga-detail-energy-statements">
        {view.energyStatements.map(text => <li key={text}>{text}</li>)}</ul>
      <Facts lines={view.countLines} testId="sequence-ga-detail-counts" />
      <span className="mw-eyebrow">히스티딘·시스테인 양성자 상태 (이 구조에서 pH 7.0으로 자동 지정한 저장값)</span>
      {view.protonationVariantLines.length ? <ul className="mw-mutation-list mw-mono" data-testid="sequence-ga-detail-variants">
        {view.protonationVariantLines.map(line => <li key={line}>{line}</li>)}</ul>
        : <p className="mw-mutation-note" data-testid="sequence-ga-detail-variants-none">해당 잔기 0개 (저장값)</p>}
      <span className="mw-eyebrow">{PROTONATION_DIFFERENCE_HEADING}</span>
      {view.protonationDifferenceRows.length
        ? <div className="mw-mutation-table-wrap"><table className="mw-mutation-table" data-testid="sequence-ga-detail-protonation-outside">
          <thead><tr>{PROTONATION_DIFFERENCE_HEADERS.map(item => <th key={item}>{item}</th>)}</tr></thead>
          <tbody>{view.protonationDifferenceRows.map(row => <tr key={row.fields}>
            <td className="mw-mono">{row.residue}</td><td className="mw-mono">{row.fields}</td>
            <td className="mw-mono">{row.wild_type_reference}</td><td className="mw-mono">{row.mutant}</td>
          </tr>)}</tbody>
        </table></div>
        : <p className="mw-mutation-note" data-testid="sequence-ga-detail-protonation-outside-none">{view.protonationDifferenceText}</p>}
      <span className="mw-eyebrow">이황화 결합 (거리 기준, 잔기 쌍)</span>
      <p className="mw-mutation-note mw-mono" data-testid="sequence-ga-detail-disulfides">{view.disulfideText}</p>
      <p className="mw-mutation-note" data-testid="sequence-ga-detail-new-disulfide">
        야생형 기준 구조에 없는 이황화 결합이 이 구조에 있음: {view.newDisulfideText}</p>
      <span className="mw-eyebrow">PDBFixer가 놓은 중원자 (변이 잔기별)</span>
      <ul className="mw-mutation-list mw-mono" data-testid="sequence-ga-detail-added-atoms">
        {view.addedAtomLines.map(line => <li key={line}>{line}</li>)}</ul>
      <span className="mw-eyebrow">모델 한계 (고정 문장)</span>
      <ul className="mw-mutation-list" data-testid="sequence-ga-detail-limitations">
        {view.modelLimitations.map(text => <li key={text}>{text}</li>)}</ul>
      {view.structureAvailable && <div className="mw-mutation-inline">
        <a className="mw-btn mw-btn--sm" data-testid="sequence-ga-detail-download"
          href={api.sequenceGaStructureUrl(runId, summaryHandle, view.key)} download>구조 mmCIF 내려받기 (저장된 바이트)</a>
      </div>}
    </div>}

    <div className="mw-mutation-group" data-testid="sequence-ga-detail-m18-area">
      <span className="mw-eyebrow">M18 도킹 결과 (저장된 단독 M18 결과 상세 읽기 값)</span>
      {read.m18_detail ? <M18DetailView detail={read.m18_detail} runId={runId} />
        : <p className="mw-mutation-note" data-testid="sequence-ga-detail-no-m18">
          저장된 M18 도킹 결과 없음{view.reason ? ` · 이유: ${view.reason}` : ""}</p>}
    </div>
  </div>;
}

/** The stored M18 result detail of one row, as the M18 detail read returns it (nothing recomputed). */
function M18DetailView({ detail, runId }: { detail: M18Detail; runId: string }) {
  const result = detail.result, mode = result.inputs.mode;
  const headers = modeTableHeaders(mode);
  return <div className="mw-docking-result" data-testid="sequence-ga-m18" data-docking-result-handle={detail.handle}
    data-null-result={result.counts.null_result}>
    <p className="mw-mutation-note mw-mono">결과 {detail.handle} · 작업 {detail.job_id}</p>
    <Facts lines={dockingSummaryRows(result)} testId="sequence-ga-m18-summary" />
    {result.modes.length > 0 ? <>
      <div className="mw-mutation-inline">
        <a className="mw-btn mw-btn--sm" data-testid="sequence-ga-m18-download-all"
          href={api.dockingPosesSdfUrl(runId, detail.handle)} download>포즈 SDF 전체 내려받기</a>
      </div>
      <div className="mw-mutation-table-wrap">
        <table className="mw-mutation-table" data-testid="sequence-ga-m18-modes">
          <caption className="mw-mutation-note">{detail.score_label} · 모드 n(엔진 출력 순서)</caption>
          <thead><tr>{headers.map(item => <th key={item}>{item}</th>)}<th>포즈 SDF</th></tr></thead>
          <tbody>{result.modes.map(row => <tr key={row.mode} data-mode={row.mode}>
            {modeTableCells(mode, row).map((cell, i) => <td key={headers[i]} className={i ? "mw-mono" : undefined}>{cell}</td>)}
            <td><a className="mw-btn mw-btn--sm" data-testid={`sequence-ga-m18-download-${row.mode}`}
              href={api.dockingPoseSdfUrl(runId, detail.handle, row.mode)} download>내려받기</a></td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="mw-mutation-note">모드별 기하 접촉 표는 리간드 설계·탐색 탭 도킹 영역의 도킹 결과 목록에서 같은 결과 handle로 볼 수
        있습니다.</p>
    </> : <p className="mw-mutation-note" data-testid="sequence-ga-m18-null">{nullResultText(mode)}</p>}
    <span className="mw-eyebrow">M18 한계 (저장된 문장)</span>
    <ul className="mw-mutation-list" data-testid="sequence-ga-m18-limitations">
      {result.limitations.map(text => <li key={text}>{text}</li>)}</ul>
  </div>;
}
