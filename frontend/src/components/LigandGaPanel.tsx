"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type RunSummary } from "@/lib/api";
import type { DockingAcknowledgementKey, DockingBoxSource, DockingPrerequisites, DockingReceptorInstances, LigandGaArgs,
  LigandGaCapability, LigandGaDetail, LigandGaJob, LigandGaKey, LigandGaLimitApproval, LigandGaList,
  LigandGaPreflight, LigandGaReportArtifact } from "@/lib/contracts";
import { ACKNOWLEDGEMENT_KEYS, ACKNOWLEDGEMENT_LABEL, BOX_FRAME_NOTE, BOX_SIDE_MAX_A, BOX_SIDE_MIN_A, BOX_SOURCES,
  boxSourceDisabledReason, boxSourceLabel, boxText, dockingCancelEnabled, dockingCapabilityText, dockingJobActive,
  dockingJobPhase, dockingRequestErrorText, dockingResponseCurrent, ENERGY_RANGE_MAX, ENERGY_RANGE_MIN,
  EXHAUSTIVENESS_MAX, EXHAUSTIVENESS_MIN, exactResidue, importsOfKind, MARGIN_MAX_A, MARGIN_MIN_A, modelInstances,
  NO_RUN_REASON, NUM_MODES_MAX, NUM_MODES_MIN, parentSdfMissingReason, removedInstanceText, sameResidue, SEED_MAX,
  SEED_MIN, type DockingStamp } from "@/lib/docking";
import { checkFilterInput, emptyAppliedFilter, emptyFilterInput, LIGAND_APPROVAL_NOTICE, ligandNoticeAfterJob,
  ligandStartProgressed, type AppliedFilter, type LigandFilterInput } from "@/lib/ligand";
import { checkGaInput, evaluationText, GA_PARAMETERS, GA_TOOL, gaActiveJob, gaApprovalRequired, gaArgs, gaArgsKey,
  gaExistingJobText, gaJobText, gaLimitApprovalOffered, gaLimitApprovalText, gaListRowText, gaParameterLines,
  gaPreflightLines, gaPreflightRefusalList, gaPreflightRefusalText, gaProgressText, gaRangeText, gaReasonText,
  gaReportMatches, gaStartBlockedReason, gaStatementTexts, gaStatusText, gaSummaryLines, gaTimeAdvice,
  generationRangeText, generationTabText, individualAriaSort, individualDetailHandle, individualReasonText,
  individualRows, individualScoreText, initialGaForm, LIMIT_RAISE_LABEL, lineageText, MODE_NOTE, nextIndividualSort,
  ORDER_NOTE, originText, patchGaForm, resetGaDefaults, SCORE_LABEL, scoreHeaderText, SEED_NOTE, SIMILARITY_NOTE,
  sortIndividuals, stateText, type GaForm, type GaPreflightState, type IndividualSort,
  type IndividualSortKey } from "@/lib/ligand-ga";
import { decimalHalfUp } from "@/lib/site-annotation";
import { RefusalList } from "./DockingPanel";
import { FilterForm } from "./LigandPanel";
import { Button } from "./primitives";

/**
 * M22 GA design area of the "리간드 설계·탐색" tab (`.dryforge/spec.md` section 9), mounted after the M19 batch
 * docking area. Every score, count, budget figure and sentence shown is a server value (preflight read, job record,
 * stored `ligand_ga_result@1`); decisions and wording come from `lib/ligand-ga.ts`. The page mounts it only while the
 * tab is shown and keys it by run; late responses are dropped by run + selection key + per-area request sequence
 * (`dockingResponseCurrent`). Individual rows open the stored M18 result in the docking area above.
 */
export interface LigandGaPanelProps {
  run: RunSummary | null;
  /** undefined while capabilities are being read; null when the backend reports no GA method. */
  capability: LigandGaCapability | null | undefined;
  onReportCreated: (runId: string) => void;
  /** "상세 열기": the page hands the individual's M18 result handle to the M18 docking area above. */
  onOpenResult: (runId: string, handle: string) => void;
}

type Load<T> = { status: "idle" } | { status: "loading" } | { status: "ready"; value: T } | { status: "error"; message: string };
type Area = "prereq" | "instances" | "preflight" | "approval" | "job" | "cancel" | "results" | "detail" | "report";
const AXES = ["x", "y", "z"] as const;
const POLL_MS = 2000;

function errorText(e: unknown): string {
  if (e instanceof ApiError) return dockingRequestErrorText(e);
  return e instanceof Error ? e.message : String(e);
}
const shortHandle = (handle: string) => handle.split("/").at(-1)?.slice(0, 12) ?? handle;

function Section({ area, title, state, children }: { area: string; title: string; state?: string; children: ReactNode }) {
  return <section className="mw-ligand-section mw-docking-section" data-ga-area={area} data-state={state} aria-label={title}>
    <h3 className="mw-ligand-title">{title}</h3>
    {children}
  </section>;
}

function ErrorLine({ message, onRetry, testId }: { message: string; onRetry?: () => void; testId?: string }) {
  return <div className="mw-ligand-error" role="alert" data-testid={testId}>
    <span>{message}</span>
    {onRetry && <Button size="sm" onClick={onRetry}>다시 읽기</Button>}
  </div>;
}

export function LigandGaPanel(p: LigandGaPanelProps) {
  const heading = <h2 className="mw-ligand-heading">GA 설계 (qvina 도킹 탐색)</h2>;
  if (!p.run || p.capability === null || p.capability?.available === false) {
    const reason = !p.run ? NO_RUN_REASON : dockingCapabilityText(p.capability ?? null);
    return <section className="mw-ligand mw-docking" aria-label="GA 설계" data-testid="ligand-ga-panel"
      data-ga-state="unavailable">
      {heading}
      <p className="mw-ligand-unavailable" role="status" data-testid={!p.run ? "ligand-ga-no-run" : "ligand-ga-unavailable"}>
        <b>사용할 수 없음</b>: {reason}</p>
    </section>;
  }
  if (p.capability === undefined) return <section className="mw-ligand mw-docking" aria-label="GA 설계"
    data-testid="ligand-ga-panel" data-ga-state="loading">
    {heading}<p className="mw-ligand-note" aria-busy="true">기능 상태를 확인하는 중</p></section>;
  return <GaWorkspace run={p.run} capability={p.capability} onReportCreated={p.onReportCreated}
    onOpenResult={p.onOpenResult} />;
}

function GaWorkspace({ run, capability, onReportCreated, onOpenResult }: { run: RunSummary;
  capability: LigandGaCapability; onReportCreated: (runId: string) => void;
  onOpenResult: (runId: string, handle: string) => void }) {
  const runId = run.run_id;
  const [form, setForm] = useState<GaForm>(initialGaForm);
  const [prereq, setPrereq] = useState<Load<DockingPrerequisites>>({ status: "idle" });
  const [prereqReload, setPrereqReload] = useState(0);
  const [instances, setInstances] = useState<{ handle: string; load: Load<DockingReceptorInstances> } | null>(null);
  const [filterInput, setFilterInput] = useState<LigandFilterInput>(emptyFilterInput);
  const [filterErrors, setFilterErrors] = useState<string[]>([]);
  const [applied, setApplied] = useState<AppliedFilter>(emptyAppliedFilter);
  const [preflight, setPreflight] = useState<{ key: string; load: Load<LigandGaPreflight> } | null>(null);
  const [approval, setApproval] = useState<{ key: string; load: Load<LigandGaLimitApproval> } | null>(null);
  const [job, setJob] = useState<LigandGaJob | null>(null);
  const [approvalPending, setApprovalPending] = useState(false);
  const [busy, setBusy] = useState(false);
  // The start request is held until the job ends: cancel has its own flag and request sequence.
  const [cancelling, setCancelling] = useState(false);
  const [jobError, setJobError] = useState("");
  const [notice, setNotice] = useState("");
  const [results, setResults] = useState<Load<LigandGaList>>({ status: "idle" });
  const [resultsReload, setResultsReload] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ handle: string; load: Load<LigandGaDetail> } | null>(null);
  const [generation, setGeneration] = useState(0);
  const [sort, setSort] = useState<IndividualSort>(null);
  const [report, setReport] = useState<{ handle: string; load: Load<LigandGaReportArtifact> } | null>(null);

  const mounted = useRef(true);
  const seqs = useRef<Record<Area, number>>({ prereq: 0, instances: 0, preflight: 0, approval: 0, job: 0, cancel: 0,
    results: 0, detail: 0, report: 0 });
  const live = useRef({ receptor: form.receptorHandle, summary: selected });
  live.current = { receptor: form.receptorHandle, summary: selected };
  useEffect(() => {
    mounted.current = true;
    const counters = seqs.current;
    return () => { mounted.current = false; for (const area of Object.keys(counters) as Area[]) counters[area] += 1; };
  }, []);
  const keyOf = (area: Area): string | null => area === "instances" ? live.current.receptor
    : area === "detail" || area === "report" ? live.current.summary : null;
  const stamp = (area: Area): DockingStamp => ({ runId, key: keyOf(area), seq: ++seqs.current[area] });
  const current = (area: Area, captured: DockingStamp) => mounted.current &&
    dockingResponseCurrent(captured, { runId, key: keyOf(area), seq: seqs.current[area] });
  const update = (patch: Partial<GaForm>) => setForm(previous => {
    const next = patchGaForm(previous, patch);
    live.current = { ...live.current, receptor: next.receptorHandle };
    return next;
  });
  const setGa = (key: LigandGaKey, value: string) => update({ ga: { ...form.ga, [key]: value } });

  // ---- reads ----
  useEffect(() => {
    const captured = stamp("prereq"), controller = new AbortController();
    setPrereq({ status: "loading" });
    api.dockingPrerequisites(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(value => {
      if (!current("prereq", captured)) return;
      if (value.schema !== "docking_prerequisites@1") throw new Error("입력 준비 응답 형식이 다릅니다.");
      setPrereq({ status: "ready", value });
    }).catch(e => { if (current("prereq", captured) && !controller.signal.aborted)
      setPrereq({ status: "error", message: `입력 준비 읽기 실패: ${errorText(e)}` }); });
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, prereqReload]);

  useEffect(() => {
    const captured = stamp("results"), controller = new AbortController();
    setResults({ status: "loading" });
    api.ligandGaResults(runId, 0, 100, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(value => {
      if (!current("results", captured)) return;
      if (value.schema !== "ligand_ga_list@1") throw new Error("GA 요약 목록 형식이 다릅니다.");
      setResults({ status: "ready", value });
    }).catch(e => { if (current("results", captured) && !controller.signal.aborted)
      setResults({ status: "error", message: `GA 요약 목록 읽기 실패: ${errorText(e)}` }); });
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, resultsReload]);

  // After a remount the durable job list tells whether a GA job is still queued or running.
  useEffect(() => {
    const captured = stamp("job"), controller = new AbortController();
    api.ligandGaJobs(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(list => {
      if (!current("job", captured)) return;
      const running = gaActiveJob<LigandGaJob>(list, runId);
      if (running) setJob(previous => previous ?? running);
    }).catch(() => undefined);
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // Stored job state (status and staged counts) is read again while the job is queued, claimed or running.
  useEffect(() => {
    if (!job || !dockingJobActive(job)) return;
    let active = true;
    const jobId = job.job_id;
    const timer = window.setInterval(() => {
      void api.ligandGaJob(runId, jobId).then(value => {
        if (active && mounted.current && value.run_id === runId && value.job_id === jobId)
          setJob(previous => previous?.job_id === jobId ? value : previous);
      }).catch(() => undefined);
    }, POLL_MS);
    return () => { active = false; window.clearInterval(timer); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, job?.job_id, job?.status]);

  // A finished job (any end state) refreshes the summary list; no summary is opened automatically.
  useEffect(() => {
    if (!job) return;
    setNotice(previous => ligandNoticeAfterJob(previous, job.status));
    if (!dockingJobActive(job)) {
      setResultsReload(value => value + 1);
      const handle = job.ga?.summary_handle ?? null;
      if (handle) setNotice(`GA 요약이 저장되었습니다 (${shortHandle(handle)}). 아래 GA 결과 목록에서 직접 고르세요.`);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.job_id, job?.status]);

  const receptorHandle = form.receptorHandle;
  useEffect(() => {
    if (!receptorHandle) return;
    const handle = receptorHandle, captured = stamp("instances"), controller = new AbortController();
    setInstances({ handle, load: { status: "loading" } });
    api.dockingReceptorInstances(runId, handle, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(value => {
      if (!current("instances", captured)) return;
      if (value.schema !== "docking_receptor_instances@1" || value.handle !== handle) throw new Error("인스턴스 목록이 고른 수용체와 다릅니다.");
      setInstances({ handle, load: { status: "ready", value } });
    }).catch(e => { if (current("instances", captured) && !controller.signal.aborted)
      setInstances({ handle, load: { status: "error", message: `수용체 인스턴스 목록 읽기 실패: ${errorText(e)}` } }); });
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [receptorHandle]);
  const listing = instances && instances.handle === receptorHandle && instances.load.status === "ready" ? instances.load.value : null;

  // The M17 filter spec goes into the request as applied (the server evaluates it on the stored values).
  function applyFilters() {
    const filterCheck = checkFilterInput(filterInput);
    if (!filterCheck.ok) { setFilterErrors(filterCheck.errors); return; }
    setFilterErrors([]); setApplied({ spec: filterCheck.spec, bounds: filterCheck.bounds });
    update({ filter: filterCheck.spec });
  }
  function clearFilters() {
    const empty = emptyAppliedFilter();
    setFilterInput(emptyFilterInput()); setFilterErrors([]); setApplied(empty); update({ filter: empty.spec });
  }

  function openSummary(handle: string) {
    setSelected(handle); live.current = { ...live.current, summary: handle };
    setGeneration(0); setSort(null); setReport(null);
    const captured = stamp("detail");
    setDetail({ handle, load: { status: "loading" } });
    api.ligandGaResult(runId, handle, AbortSignal.timeout(30000)).then(value => {
      if (!current("detail", captured)) return;
      if (value.schema !== "ligand_ga_detail@1" || value.handle !== handle) throw new Error("GA 요약이 고른 handle과 다릅니다.");
      setDetail({ handle, load: { status: "ready", value } });
    }).catch(e => { if (current("detail", captured))
      setDetail({ handle, load: { status: "error", message: `GA 요약 읽기 실패: ${errorText(e)}` } }); });
  }
  const opened = detail && detail.handle === selected && detail.load.status === "ready" ? detail.load.value : null;

  // ---- preflight, limit approval, job ----
  const gaCheck = checkGaInput(form.ga);
  const check = gaArgs(form);
  const argsKey = check.ok ? gaArgsKey(check.args) : null;
  const preflightState: GaPreflightState = preflight && preflight.load.status === "ready" && preflight.key === argsKey
    ? { key: preflight.key, value: preflight.load.value } : null;
  const shownPreflight = preflightState?.value ?? null;
  const startBlocked = gaStartBlockedReason({ capability, busy, activeJob: job, check, preflight: preflightState,
    dryRun: run.dry_run });

  async function runPreflight(args: LigandGaArgs) {
    const key = gaArgsKey(args), captured = stamp("preflight");
    setPreflight({ key, load: { status: "loading" } });
    try {
      const value = await api.ligandGaPreflight(runId, args, AbortSignal.timeout(30000));
      if (!current("preflight", captured)) return;
      if (value.schema !== "ligand_ga_preflight@1") throw new Error("시작 전 확인 응답 형식이 다릅니다.");
      setPreflight({ key, load: { status: "ready", value } });
    } catch (e) { if (current("preflight", captured)) setPreflight({ key, load: { status: "error", message: `시작 전 확인 실패: ${errorText(e)}` } }); }
  }

  // The only caller of the GA limit approval route: a person's click on the button below.
  async function approveLimits() {
    if (!check.ok || !gaLimitApprovalOffered(shownPreflight, run.dry_run)) return;
    const args = check.args, key = gaArgsKey(args), captured = stamp("approval");
    setApproval({ key, load: { status: "loading" } });
    try {
      const value = await api.ligandGaLimitApproval(runId, args);
      if (!current("approval", captured)) return;
      setApproval({ key, load: { status: "ready", value } });
      await runPreflight(args);
    } catch (e) { if (current("approval", captured)) setApproval({ key, load: { status: "error", message: `한도 증액 실패: ${errorText(e)}` } }); }
  }

  async function start(before: LigandGaJob) {
    const captured = stamp("job");
    setBusy(true); setJobError(""); setNotice("");
    try {
      const value = await api.startJob(runId, before.job_id) as unknown as LigandGaJob;
      if (!current("job", captured)) return;
      if (value.run_id !== runId || value.job_id !== before.job_id) throw new Error("시작 응답이 이 작업과 다릅니다.");
      setApprovalPending(false); setJob(value);
    } catch (e) {
      if (!current("job", captured)) return;
      if (e instanceof ApiError && gaApprovalRequired(e.status, e.approval)) { setApprovalPending(true); return; }
      // The start may have taken effect although its response was lost (proxy limit): the stored job decides.
      const stored = await api.ligandGaJob(runId, before.job_id).catch(() => null);
      if (!current("job", captured)) return;
      if (stored && stored.run_id === runId && stored.job_id === before.job_id) setJob(stored);
      if (!stored || !ligandStartProgressed(before, stored)) setJobError(`작업 시작 실패: ${errorText(e)}`);
    } finally { if (mounted.current) setBusy(false); }
  }

  async function submit() {
    if (startBlocked || !check.ok) return;
    const captured = stamp("job");
    setBusy(true); setJobError(""); setNotice(""); setApprovalPending(false);
    try {
      const result = await api.submitLigandGa(runId, check.args);
      if (!current("job", captured)) return;
      if ("plan_only" in result) { setNotice("dry-run run이라 계획만 만들었습니다. 실제 계산과 결과 객체는 없습니다."); return; }
      if (result.run_id !== runId || result.protocol_id !== "qvina_ga_dock_v1") throw new Error("제출 응답이 요청과 다릅니다.");
      setJob(result);
      if (result.status !== "queued") {
        setNotice(`같은 입력의 기존 GA 작업을 다시 표시합니다 · ${result.job_id} · ${result.status} (새 작업을 만들지 않았습니다)`);
        return;
      }
      await start(result);
    } catch (e) { if (current("job", captured)) setJobError(`GA 작업 제출 실패: ${errorText(e)}`); }
    finally { if (mounted.current) setBusy(false); }
  }

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

  async function cancelJob() {
    if (!job || !dockingCancelEnabled({ job, cancelling })) return;
    const captured = stamp("cancel"), jobId = job.job_id;
    setCancelling(true);
    try {
      const value = (await api.cancelJob(runId, jobId)).job as unknown as LigandGaJob;
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
      const artifact = await api.createLigandGaReport(runId, handle, AbortSignal.timeout(60000));
      if (!current("report", captured)) return;
      if (!gaReportMatches(artifact, handle)) throw new Error("보고서가 고른 GA 요약과 다릅니다.");
      setReport({ handle, load: { status: "ready", value: artifact } });
      onReportCreated(runId);
    } catch (e) { if (current("report", captured)) setReport({ handle, load: { status: "error", message: `보고서 만들기 실패: ${errorText(e)}` } }); }
  }

  // ---- derived ----
  const prereqValue = prereq.status === "ready" ? prereq.value : null;
  const receptors = prereqValue ? importsOfKind(prereqValue.imports, "receptor") : [];
  const sidecars = prereqValue ? importsOfKind(prereqValue.imports, "receptor_bonds") : [];
  const sets = prereqValue?.candidate_sets ?? [];
  const chosenSet = sets.find(set => set.handle === form.candidateSetHandle) ?? null;
  const parentReason = parentSdfMissingReason(chosenSet);
  const modelList = listing ? modelInstances(listing, form.receptorModelNumber) : [];
  const instancesError = instances?.handle === receptorHandle && instances?.load.status === "error" ? instances.load.message : null;
  const phase = dockingJobPhase(job, approvalPending);
  const approvalLoad = approval && approval.key === argsKey ? approval.load : null;
  const preflightLoad = preflight && preflight.key === argsKey ? preflight.load : null;
  const timeAdvice = gaCheck.ok ? gaTimeAdvice(gaCheck.ga) : null;

  return <section className="mw-ligand mw-docking" aria-label="GA 설계" data-testid="ligand-ga-panel" data-ga-state="ready">
    <div className="mw-ligand-head">
      <h2 className="mw-ligand-heading">GA 설계 (qvina 도킹 탐색)</h2>
    </div>
    <p className="mw-ligand-note">게시된 후보 집합 하나를 후보 풀로 삼아, 유전 알고리즘(GA)이 세대마다 어느 후보를 도킹할지 정합니다.
      개체마다 같은 수용체·상자·값으로 자유 도킹하며 점수는 {SCORE_LABEL}입니다. 화면은 저장된 값을 표시만 하며 점수·집계를 계산하지 않습니다.</p>
    {run.dry_run && <p role="status" className="mw-ligand-unavailable" data-testid="ligand-ga-dry-run">
      dry-run run: GA를 시작하면 계획만 만들며 실제 계산과 결과 객체가 없습니다. 한도 증액도 하지 않습니다.</p>}
    <p className="mw-ligand-note mw-mono" data-testid="ligand-ga-capability">
      {capability.engine} · {GA_TOOL} · 새로 도킹하는 개체마다 비싼 계산 예산 1단위(시작 전에 한 번에 예약)</p>
    <div className="mw-ligand-inline">
      <Button size="sm" data-testid="ligand-ga-prereq-refresh" disabled={prereq.status === "loading"}
        onClick={() => setPrereqReload(value => value + 1)}>입력 목록 다시 읽기</Button>
      <span className="mw-ligand-note">가져오기는 위 도킹 영역에서 합니다. 위에서 가져온 파일·만든 후보 집합은 다시 읽어야 보입니다.</span>
    </div>
    {prereq.status === "loading" && <p className="mw-ligand-note" aria-busy="true">입력 준비 목록을 읽는 중</p>}
    {prereq.status === "error" && <ErrorLine message={prereq.message} onRetry={() => setPrereqReload(value => value + 1)}
      testId="ligand-ga-prereq-error" />}

    <Section area="pool" title="① 후보 풀(후보 집합)과 부모 SDF">
      <label className="mw-ligand-check">후보 집합
        <select className="mw-select" data-testid="ligand-ga-candidate-set" value={form.candidateSetHandle ?? ""}
          onChange={event => update({ candidateSetHandle: event.target.value || null })}>
          <option value="">선택</option>
          {sets.map(set => <option key={set.handle} value={set.handle} disabled={!set.valid}>
            {set.valid ? `${shortHandle(set.handle)} · 후보 ${set.candidates}개` : `${shortHandle(set.handle)} · 읽을 수 없음`}</option>)}
        </select></label>
      {prereqValue && !sets.length && <p className="mw-ligand-unavailable" role="status" data-testid="ligand-ga-no-candidate-set">
        <b>사용할 수 없음</b>: 이 run에 후보 집합이 없습니다. 위 리간드 후보 영역에서 후보 집합을 먼저 만드세요.</p>}
      {chosenSet && (parentReason ? <p className="mw-ligand-unavailable" data-testid="ligand-ga-parent-missing">{parentReason}</p>
        : <label className="mw-ligand-check">부모 3D SDF 가져오기 (SHA-256이 후보 집합의 부모와 같은 것만)
          <select className="mw-select" data-testid="ligand-ga-parent-sdf" value={form.parentSdfHandle ?? ""}
            onChange={event => update({ parentSdfHandle: event.target.value || null })}>
            <option value="">선택</option>
            {chosenSet.parent_sdf_handles!.map(handle => <option key={handle} value={handle}>{shortHandle(handle)}</option>)}
          </select></label>)}
      {form.candidateSetHandle && <>
        <p className="mw-ligand-note">선택 사항: M17 필터를 적용하면 통과한 후보만 적격 후보가 됩니다(필터 탈락 후보는 도킹하지 않음).
          적용한 필터 사양이 요청에 들어갑니다.</p>
        <FilterForm idPrefix="ligand-ga" input={filterInput} errors={filterErrors} applied={applied.spec}
          onInput={setFilterInput} onApply={applyFilters} onClear={clearFilters} />
      </>}
    </Section>

    <Section area="receptor" title="② 수용체와 뺄 인스턴스">
      <label className="mw-ligand-check">수용체 가져오기
        <select className="mw-select" data-testid="ligand-ga-receptor" value={form.receptorHandle ?? ""}
          onChange={event => update({ receptorHandle: event.target.value || null })}>
          <option value="">선택</option>
          {receptors.map(row => <option key={row.handle} value={row.handle}>
            {`생성 순번 ${row.created_seq} · ${row.input_format ?? ""} · ${row.size} B · ${shortHandle(row.handle)}`}</option>)}
        </select></label>
      {prereqValue && !receptors.length && <p className="mw-ligand-note">가져온 수용체가 없습니다.</p>}
      {instances?.handle === receptorHandle && instances?.load.status === "loading" &&
        <p className="mw-ligand-note" aria-busy="true">수용체 인스턴스 목록을 읽는 중</p>}
      {instancesError && <ErrorLine message={instancesError} testId="ligand-ga-instances-error" />}
      {listing && <>
        <label className="mw-ligand-check">모델 (암묵적으로 첫 모델을 쓰지 않음)
          <select className="mw-select" data-testid="ligand-ga-model" value={form.receptorModelNumber ?? ""}
            onChange={event => update({ receptorModelNumber: event.target.value === "" ? null : Number(event.target.value) })}>
            <option value="">선택</option>
            {listing.model_numbers.map(number => <option key={number} value={number}>{`모델 ${number}`}</option>)}
          </select></label>
        {form.receptorModelNumber !== null && <fieldset className="mw-ligand-choices" data-testid="ligand-ga-instances">
          <legend>수용체에서 뺄 리간드 인스턴스 (하나만, 자동으로 고르지 않음)</legend>
          <label data-ga-instance="none">
            <input type="radio" name={`ga-instance-${runId}`} checked={form.instance.kind === "none"}
              onChange={() => update({ instance: { kind: "none" } })} />
            <span>없음(단백질만)</span></label>
          {modelList.map(item => <label key={JSON.stringify(exactResidue(item.residue))}
            data-ga-instance={JSON.stringify(exactResidue(item.residue))}>
            <input type="radio" name={`ga-instance-${runId}`}
              checked={form.instance.kind === "instance" && sameResidue(form.instance.residue, item.residue)}
              onChange={() => update({ instance: { kind: "instance", residue: exactResidue(item.residue) } })} />
            <span className="mw-mono">{removedInstanceText(item)}</span></label>)}
          {!modelList.length && <p className="mw-ligand-note">이 모델에는 물 밖의 비표준 잔기 인스턴스가 없습니다.</p>}
        </fieldset>}
      </>}
      <fieldset className="mw-ligand-choices" data-testid="ligand-ga-connectivity">
        <legend>연결 정보</legend>
        <label><input type="radio" name={`ga-connectivity-${runId}`} checked={form.connectivity === "pdb_conect"}
          onChange={() => update({ connectivity: "pdb_conect" })} /> PDB CONECT (파일 안의 완전한 연결 정보)</label>
        <label><input type="radio" name={`ga-connectivity-${runId}`} checked={form.connectivity === "sidecar"}
          onChange={() => update({ connectivity: "sidecar" })} /> 결합 사이드카 (receptor_bonds@1)</label>
        {form.connectivity === "sidecar" && <label className="mw-ligand-check">사이드카 가져오기
          <select className="mw-select" data-testid="ligand-ga-sidecar" value={form.sidecarHandle ?? ""}
            onChange={event => update({ sidecarHandle: event.target.value || null })}>
            <option value="">선택</option>
            {sidecars.map(row => <option key={row.handle} value={row.handle}>
              {`생성 순번 ${row.created_seq} · ${row.size} B · ${shortHandle(row.handle)}`}</option>)}
          </select></label>}
      </fieldset>
    </Section>

    <Section area="box" title="③ 상자 (GA 전체에 하나)">
      <p className="mw-ligand-note">{BOX_FRAME_NOTE}</p>
      <fieldset className="mw-ligand-choices" data-testid="ligand-ga-box-source">
        <legend>상자 출처 (자동으로 고르지 않음)</legend>
        {BOX_SOURCES.map((source: DockingBoxSource) => {
          const reason = boxSourceDisabledReason(source, form.instance);
          return <label key={source} data-ga-box={source} data-disabled-reason={reason ?? undefined}>
            <input type="radio" name={`ga-box-${runId}`} checked={form.boxSource === source} disabled={!!reason}
              onChange={() => update({ boxSource: source })} /> {boxSourceLabel(source)}
            {reason && <span className="mw-ligand-note">{reason}</span>}</label>;
        })}
      </fieldset>
      {(form.boxSource === "ligand_range" || form.boxSource === "instance_range") && <label className="mw-ligand-check">
        여백 (Å, {MARGIN_MIN_A}–{MARGIN_MAX_A}{form.boxSource === "ligand_range" ? ", 부모 SDF 중원자 범위" : ""})
        <input className="mw-ligand-input" data-testid="ligand-ga-margin" inputMode="decimal" value={form.margin}
          onChange={event => update({ margin: event.target.value })} /></label>}
      {form.boxSource === "manual" && <div className="mw-docking-grid" data-testid="ligand-ga-manual-box">
        {AXES.map((axis, i) => <label key={`c${axis}`} className="mw-ligand-check">중심 {axis} (Å)
          <input className="mw-ligand-input" data-testid={`ligand-ga-center-${axis}`} inputMode="decimal" value={form.center[i]}
            onChange={event => update({ center: form.center.map((value, j) => j === i ? event.target.value : value) as GaForm["center"] })} />
        </label>)}
        {AXES.map((axis, i) => <label key={`s${axis}`} className="mw-ligand-check">크기 {axis} (Å, {BOX_SIDE_MIN_A}–{BOX_SIDE_MAX_A})
          <input className="mw-ligand-input" data-testid={`ligand-ga-size-${axis}`} inputMode="decimal" value={form.size[i]}
            onChange={event => update({ size: form.size.map((value, j) => j === i ? event.target.value : value) as GaForm["size"] })} />
        </label>)}
      </div>}
    </Section>

    <Section area="docking" title="④ 도킹 값과 확인">
      <p className="mw-ligand-note">{MODE_NOTE}</p>
      <div className="mw-docking-grid">
        <label className="mw-ligand-check">도킹 seed (qvina 난수, 필수, {SEED_MIN}–{SEED_MAX})
          <input className="mw-ligand-input" data-testid="ligand-ga-docking-seed" inputMode="numeric" value={form.seed}
            onChange={event => update({ seed: event.target.value })} /></label>
        <label className="mw-ligand-check">exhaustiveness ({EXHAUSTIVENESS_MIN}–{EXHAUSTIVENESS_MAX})
          <input className="mw-ligand-input" data-testid="ligand-ga-exhaustiveness" inputMode="numeric" value={form.exhaustiveness}
            onChange={event => update({ exhaustiveness: event.target.value })} /></label>
        <label className="mw-ligand-check">num_modes ({NUM_MODES_MIN}–{NUM_MODES_MAX})
          <input className="mw-ligand-input" data-testid="ligand-ga-num-modes" inputMode="numeric" value={form.numModes}
            onChange={event => update({ numModes: event.target.value })} /></label>
        <label className="mw-ligand-check">energy_range (kcal/mol, {ENERGY_RANGE_MIN}–{ENERGY_RANGE_MAX})
          <input className="mw-ligand-input" data-testid="ligand-ga-energy-range" inputMode="decimal" value={form.energyRange}
            onChange={event => update({ energyRange: event.target.value })} /></label>
      </div>
      <p className="mw-ligand-note">cpu는 1로 고정됩니다.</p>
      <fieldset className="mw-ligand-choices" data-testid="ligand-ga-acknowledgement">
        <legend>제출 전 확인 (세 항목 모두)</legend>
        {ACKNOWLEDGEMENT_KEYS.map((key: DockingAcknowledgementKey) => <label key={key} data-ga-ack={key}>
          <input type="checkbox" checked={form.acknowledgement[key]}
            onChange={event => update({ acknowledgement: { ...form.acknowledgement, [key]: event.target.checked } })} />
          {ACKNOWLEDGEMENT_LABEL[key]}</label>)}
      </fieldset>
    </Section>

    <Section area="parameters" title="⑤ GA 파라미터">
      <p className="mw-ligand-note">{SEED_NOTE}</p>
      <div className="mw-ga-params" data-testid="ligand-ga-parameters">
        {GA_PARAMETERS.map(item => {
          const error = gaCheck.fields[item.key];
          return <label key={item.key} className="mw-ga-param" data-ga-param={item.key} data-invalid={error ? true : undefined}>
            <span className="mw-ga-param__label">{item.label}</span>
            <input className="mw-ligand-input" data-testid={`ligand-ga-param-${item.key}`}
              inputMode={item.integer ? "numeric" : "decimal"} value={form.ga[item.key]} aria-invalid={!!error}
              onChange={event => setGa(item.key, event.target.value)} />
            <span className="mw-ga-param__range mw-mono" data-testid={`ligand-ga-range-${item.key}`}>{gaRangeText(item.key)}</span>
            {error && <span className="mw-ga-param__error" data-testid={`ligand-ga-error-${item.key}`}>{error}</span>}
          </label>;
        })}
      </div>
      <div className="mw-ligand-inline">
        <Button size="sm" data-testid="ligand-ga-defaults" onClick={() => update({ ga: resetGaDefaults(form.ga) })}>기본값으로</Button>
        <span className="mw-ligand-note">GA seed는 기본값이 없어 입력한 값을 그대로 둡니다.</span>
      </div>
      {gaCheck.ok ? <dl className="mw-ligand-facts mw-docking-summary" data-testid="ligand-ga-effective">
        {gaParameterLines(gaCheck.ga).map(([label, value]) => <div key={label} className="mw-ligand-fact" data-ga-line={label}>
          <dt>{label}</dt><dd className="mw-mono">{value}</dd></div>)}
      </dl> : <p className="mw-ligand-note" data-testid="ligand-ga-effective-blocked">입력 오류를 고치면 유효 파라미터 요약이 보입니다.</p>}
      {timeAdvice && <p className="mw-ligand-unavailable" role="status" data-testid="ligand-ga-time-advice">{timeAdvice}</p>}
      {!check.ok && <ul className="mw-ligand-errors" data-testid="ligand-ga-input-errors">
        {check.errors.map(error => <li key={error}>{error}</li>)}</ul>}
    </Section>

    <Section area="preflight" title="⑥ 시작 전 확인" state={preflightLoad?.status}>
      <div className="mw-ligand-inline">
        <Button size="sm" data-testid="ligand-ga-preflight" disabled={!check.ok || preflightLoad?.status === "loading"}
          onClick={() => { if (check.ok) void runPreflight(check.args); }}>시작 전 확인 보기</Button>
        {preflight && preflight.key !== argsKey && <span className="mw-ligand-note" data-testid="ligand-ga-preflight-stale">
          입력이 바뀌었습니다. 시작 전 확인을 다시 보세요.</span>}
      </div>
      {preflightLoad?.status === "loading" && <p className="mw-ligand-note" aria-busy="true">시작 전 확인을 읽는 중</p>}
      {preflightLoad?.status === "error" && <ErrorLine message={preflightLoad.message} testId="ligand-ga-preflight-error" />}
      {shownPreflight && <PreflightView preflight={shownPreflight} />}
      {gaLimitApprovalOffered(shownPreflight, run.dry_run) && <div className="mw-ligand-inline" data-testid="ligand-ga-limit-area">
        <Button size="sm" data-testid="ligand-ga-limit-approve" disabled={approvalLoad?.status === "loading"}
          onClick={() => void approveLimits()}>{LIMIT_RAISE_LABEL}</Button>
        <span className="mw-ligand-note">사람이 직접 하는 승인입니다. 서버가 누른 시점의 부족분만 올리며(활동 시간은 60초 여유 포함) 되돌리지 않습니다.
          계산 승인을 대신하지 않습니다.</span>
      </div>}
      {approvalLoad?.status === "loading" && <p className="mw-ligand-note" aria-busy="true">한도를 올리는 중</p>}
      {approvalLoad?.status === "ready" && <p role="status" className="mw-ligand-note" data-testid="ligand-ga-limit-done"
        data-raised={approvalLoad.value.raised}>{gaLimitApprovalText(approvalLoad.value)}</p>}
      {approvalLoad?.status === "error" && <ErrorLine message={approvalLoad.message} testId="ligand-ga-limit-error" />}
    </Section>

    <Section area="start" title="⑦ GA 시작">
      <div className="mw-ligand-inline">
        <Button size="sm" variant="primary" data-testid="ligand-ga-start" disabled={!!startBlocked}
          title={startBlocked ?? undefined} onClick={() => void submit()}>GA 시작</Button>
        {startBlocked && <span className="mw-ligand-note" data-testid="ligand-ga-start-blocked">{startBlocked}</span>}
      </div>
      {(job || notice || jobError) && <div className="mw-ligand-job" data-testid="ligand-ga-job-area">
        {job && <div className="mw-ligand-job" data-testid="ligand-ga-job" data-ga-job-phase={phase}
          data-ga-job-status={job.status} data-ga-job-id={job.job_id}
          data-generations-complete={job.ga?.generations_complete} data-individuals-finished={job.ga?.individuals_finished}>
          <p className="mw-ligand-note" role="status">{gaJobText(job, approvalPending)}</p>
          <p className="mw-ligand-note mw-mono">{GA_TOOL} · 작업 {job.status} · {job.job_id}</p>
          {job.ga && <p className="mw-ligand-note" data-testid="ligand-ga-progress">{gaProgressText(job.ga)}</p>}
          {job.blocked_reason && <p className="mw-ligand-note">시작 대기 이유: {gaReasonText(job.blocked_reason)}</p>}
          <div className="mw-ligand-inline">
            {phase === "awaiting_approval" && <Button size="sm" data-testid="ligand-ga-job-approve" disabled={busy}
              onClick={() => void approveFirstCall()}>비싼 계산 승인</Button>}
            {phase === "saved" && <Button size="sm" data-testid="ligand-ga-job-start" disabled={busy || run.dry_run}
              onClick={() => void start(job)}>작업 시작</Button>}
            {dockingJobActive(job) && <Button size="sm" data-testid="ligand-ga-job-cancel"
              disabled={!dockingCancelEnabled({ job, cancelling })} onClick={() => void cancelJob()}>작업 취소</Button>}
          </div>
        </div>}
        {notice && <p role="status" className="mw-ligand-note" data-testid="ligand-ga-notice">{notice}</p>}
        {jobError && <ErrorLine message={jobError} testId="ligand-ga-job-error" />}
      </div>}
    </Section>

    <Section area="results" title="⑧ GA 결과" state={results.status}>
      {results.status === "loading" && <p className="mw-ligand-note" aria-busy="true">GA 요약 목록을 읽는 중</p>}
      {results.status === "error" && <ErrorLine message={results.message} onRetry={() => setResultsReload(value => value + 1)} />}
      {results.status === "ready" && (!results.value.rows.length ? <p className="mw-ligand-note">이 run에 GA 결과가 없습니다.</p>
        : <fieldset className="mw-ligand-choices" data-testid="ligand-ga-list">
          <legend>GA 결과 선택 (자동으로 고르지 않음)</legend>
          {results.value.rows.map(row => <label key={row.handle} data-ga-summary={row.handle} data-valid={row.valid}
            data-ga-status={row.status ?? undefined}>
            <input type="radio" name={`ga-summary-${runId}`} checked={selected === row.handle} disabled={!row.valid}
              onChange={() => openSummary(row.handle)} />
            <span className="mw-mono">{shortHandle(row.handle)} · {gaListRowText(row)}</span></label>)}
        </fieldset>)}
      {results.status !== "loading" && <Button size="sm" data-testid="ligand-ga-list-refresh"
        onClick={() => setResultsReload(value => value + 1)}>GA 결과 목록 다시 읽기</Button>}
      {detail?.handle === selected && detail.load.status === "loading" && <p className="mw-ligand-note" aria-busy="true">GA 요약을 읽는 중</p>}
      {detail?.handle === selected && detail.load.status === "error" &&
        <ErrorLine message={detail.load.message} onRetry={() => selected && openSummary(selected)} testId="ligand-ga-detail-error" />}
      {opened && <GaResult detail={opened} generation={generation} onGeneration={index => { setGeneration(index); setSort(null); }}
        sort={sort} onSort={key => setSort(previous => nextIndividualSort(previous, key))}
        onOpen={handle => onOpenResult(runId, handle)} />}
      {opened && <>
        <div className="mw-ligand-inline" aria-label="GA 보고서">
          <Button size="sm" data-testid="ligand-ga-report" disabled={report?.handle === selected && report.load.status === "loading"}
            onClick={() => void makeReport()}>보고서 만들기</Button>
        </div>
        {report?.handle === selected && report.load.status === "loading" && <p className="mw-ligand-note" aria-busy="true">보고서를 만드는 중</p>}
        {report?.handle === selected && report.load.status === "ready" && <p role="status" className="mw-ligand-note"
          data-testid="ligand-ga-report-done" data-report-handle={report.load.value.handle}>
          GA 설계 보고서를 저장했습니다 · {shortHandle(report.load.value.handle)}. 지식·보고서 탭의 보고서 목록에서 열고 받을 수 있습니다.</p>}
        {report?.handle === selected && report.load.status === "error" && <ErrorLine message={report.load.message} testId="ligand-ga-report-error" />}
      </>}
    </Section>
  </section>;
}

function PreflightView({ preflight }: { preflight: LigandGaPreflight }) {
  if (!preflight.admission.admitted) {
    const refusal = gaPreflightRefusalList(preflight);
    return <>
      <p className="mw-ligand-error" role="alert" data-testid="ligand-ga-preflight-refused"
        data-reason-code={preflight.admission.reason_code ?? undefined}>시작할 수 없습니다: {gaPreflightRefusalText(preflight)}</p>
      {refusal && <RefusalList list={refusal} source="admission" />}
    </>;
  }
  return <div className="mw-docking-result" data-testid="ligand-ga-preflight-view"
    data-reserved-units={preflight.reserved_units ?? undefined} data-reusable={preflight.reusable_count ?? undefined}
    data-shortfall-calls={preflight.shortfall?.expensive_calls} data-shortfall-wall={preflight.shortfall?.wall_clock_s}
    data-may-be-partial={preflight.full_run_may_be_partial ?? undefined}>
    <dl className="mw-ligand-facts mw-docking-summary">
      {gaPreflightLines(preflight).map(([label, value]) => <div key={label} className="mw-ligand-fact" data-preflight-line={label}>
        <dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
    {preflight.existing_job && <p className="mw-ligand-note" role="status" data-testid="ligand-ga-existing-job"
      data-job-id={preflight.existing_job.job_id}>{gaExistingJobText(preflight.existing_job)}</p>}
    {preflight.statements && preflight.statements.length > 0 && <ul className="mw-ligand-list" data-testid="ligand-ga-preflight-statements">
      {preflight.statements.map(item => <li key={item.id} data-statement={item.id}>{item.text}</li>)}</ul>}
  </div>;
}

const SORT_HEADERS: { key: IndividualSortKey; label: string }[] = [{ key: "slot", label: "자리" },
  { key: "candidate", label: "후보 id" }];

function GaResult({ detail, generation, onGeneration, sort, onSort, onOpen }: { detail: LigandGaDetail;
  generation: number; onGeneration: (index: number) => void; sort: IndividualSort; onSort: (key: IndividualSortKey) => void;
  onOpen: (handle: string) => void }) {
  const summary = detail.summary, values = summary.parameters;
  const statements = detail.statements.length ? detail.statements
    : gaStatementTexts(summary).map((text, index) => ({ id: `local-${index}`, text }));
  const generations = detail.generations;
  const shown = generations[generation] ?? generations[0] ?? null;
  const rows = shown ? sortIndividuals(individualRows(shown), sort) : [];
  const header = (key: IndividualSortKey, label: string) => <th key={key} aria-sort={individualAriaSort(sort, key)}>
    <button type="button" className="mw-docking-sort" data-testid={`ligand-ga-sort-${key}`}
      onClick={() => onSort(key)}>{label}</button></th>;
  return <div className="mw-docking-result" data-testid="ligand-ga-result" data-ga-handle={detail.handle}
    data-ga-status={summary.status} data-stop-reason={summary.stop_reason}>
    <p className="mw-ligand-note mw-mono">GA 요약 {shortHandle(detail.handle)} · 작업 {detail.job_id}</p>
    <p role="status" className={summary.status === "partial" ? "mw-ligand-unavailable" : "mw-ligand-note"}
      data-testid="ligand-ga-status">GA 상태: {gaStatusText(summary)}</p>
    <ul className="mw-ligand-list" data-testid="ligand-ga-statements">
      {statements.map(item => <li key={item.id} data-statement={item.id}>{item.text}</li>)}</ul>
    <dl className="mw-ligand-facts mw-docking-summary" data-testid="ligand-ga-summary">
      {gaSummaryLines(summary).map(([label, value]) => <div key={label} className="mw-ligand-fact" data-summary-line={label}>
        <dt>{label}</dt><dd className="mw-mono">{value}</dd></div>)}
      <div className="mw-ligand-fact"><dt>도킹 seed</dt><dd className="mw-mono">{values.seed}</dd></div>
      <div className="mw-ligand-fact"><dt>도킹 값</dt><dd className="mw-mono">{`exhaustiveness ${values.exhaustiveness} · num_modes ` +
        `${values.num_modes} · energy_range ${decimalHalfUp(values.energy_range, 2)} kcal/mol · cpu ${values.cpu}`}</dd></div>
      <div className="mw-ligand-fact"><dt>상자</dt><dd className="mw-mono">{boxText(summary.box)}</dd></div>
      <div className="mw-ligand-fact"><dt>후보 집합</dt><dd className="mw-mono">{`${summary.candidate_set_handle} · 부모 SDF ` +
        `${summary.parent_sdf_handle}`}</dd></div>
    </dl>
    <details data-testid="ligand-ga-stored-parameters"><summary>GA 파라미터 (저장값)</summary>
      <dl className="mw-ligand-facts mw-docking-summary">
        {gaParameterLines(summary.ga).map(([label, value]) => <div key={label} className="mw-ligand-fact">
          <dt>{label}</dt><dd className="mw-mono">{value}</dd></div>)}
      </dl></details>
    {!generations.length ? <p className="mw-ligand-note" data-testid="ligand-ga-no-generations">기록된 세대가 없습니다.</p> : <>
      <div className="mw-ga-tabs" role="tablist" aria-label="세대" data-testid="ligand-ga-generation-tabs">
        {generations.map((item, index) => <button key={item.index} type="button" role="tab"
          aria-selected={shown?.index === item.index} data-testid={`ligand-ga-generation-${item.index}`}
          data-complete={item.complete} onClick={() => onGeneration(index)}>{generationTabText(item)}</button>)}
      </div>
      {shown && <div role="tabpanel" aria-label={generationTabText(shown)} className="mw-docking-result"
        data-testid="ligand-ga-generation-panel" data-generation={shown.index}>
        <p className="mw-ligand-note mw-mono" data-testid="ligand-ga-generation-range">{generationRangeText(shown)}</p>
        <p className="mw-ligand-note">{ORDER_NOTE} {SIMILARITY_NOTE} 상세는 위 도킹 영역의 도킹 결과에 열립니다.</p>
        <div className="mw-ligand-table-wrap">
          <table className="mw-ligand-table" data-testid="ligand-ga-individuals">
            <caption className="mw-ligand-note">{detail.score_label}</caption>
            <thead><tr>
              {SORT_HEADERS.map(item => header(item.key, item.label))}
              <th>출처</th><th>부모 · 유사도</th><th>평가</th><th>상태</th>
              {header("score", scoreHeaderText())}
              <th>이유</th><th>상세</th>
            </tr></thead>
            <tbody>{rows.map(row => {
              const handle = row.detail_available ? individualDetailHandle(row) : null;
              return <tr key={`${row.position}-${row.candidate_id}`} data-position={row.position}
                data-candidate-id={row.candidate_id} data-origin={row.origin} data-evaluation={row.evaluation ?? "carried"}
                data-state={row.state}>
                <td className="mw-mono">{row.position}</td>
                <td className="mw-mono">{row.candidate_id}</td>
                <td>{originText(row.origin)}</td>
                <td className="mw-mono">{lineageText(row)}</td>
                <td>{evaluationText(row.evaluation)}</td>
                <td>{stateText(row.state)}</td>
                <td className="mw-mono" data-score-cell>{individualScoreText(row)}</td>
                <td>{individualReasonText(row)}</td>
                <td><Button size="sm" data-testid={`ligand-ga-open-${shown.index}-${row.position}`} disabled={!handle}
                  onClick={() => { if (handle) onOpen(handle); }}>상세 열기</Button></td>
              </tr>;
            })}</tbody>
          </table>
        </div>
      </div>}
    </>}
  </div>;
}
