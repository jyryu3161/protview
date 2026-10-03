"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type RunSummary } from "@/lib/api";
import type { DockingAcknowledgementKey, DockingBatchArgs, DockingBatchCapability, DockingBatchDetail, DockingBatchJob,
  DockingBatchLimitApproval, DockingBatchList, DockingBatchPreflight, DockingBatchReportArtifact, DockingBoxSource,
  DockingPrerequisites, DockingReceptorInstances, LigandCandidatePage } from "@/lib/contracts";
import { ACKNOWLEDGEMENT_KEYS, ACKNOWLEDGEMENT_LABEL, BOX_FRAME_NOTE, BOX_SIDE_MAX_A, BOX_SIDE_MIN_A, BOX_SOURCES,
  boxSourceDisabledReason, boxSourceLabel, boxText, CONFORMERS_MAX, CONFORMERS_MIN, dockingCancelEnabled,
  dockingCapabilityText, dockingJobActive, dockingJobPhase, dockingRequestErrorText, dockingResponseCurrent,
  ENERGY_RANGE_MAX, ENERGY_RANGE_MIN, EXHAUSTIVENESS_MAX, EXHAUSTIVENESS_MIN, exactResidue, importsOfKind,
  MARGIN_MAX_A, MARGIN_MIN_A, MODE_LABEL, modelInstances, MODES, NO_RUN_REASON, NUM_MODES_MAX, NUM_MODES_MIN,
  parentSdfMissingReason, removedInstanceText, sameResidue, SCORE_LABEL, SEED_MAX, SEED_MIN, stereoFlagText,
  type DockingStamp } from "@/lib/docking";
import { ariaSort, BATCH_TOOL, batchActiveJob, batchApprovalRequired, batchArgs, batchArgsKey, batchJobText,
  batchListRowText, batchProgressText, batchReportMatches, batchStartBlockedReason, batchStatusText,
  candidateSelectable, existingJobText, LIMIT_RAISE_LABEL, limitApprovalOffered, limitApprovalText, MAX_CANDIDATES,
  nextBatchSort, orderedCandidateIds, parentDisabledReason, patchBatchForm, preflightLines, preflightRefusalText,
  reusedText, rowCandidateText, rowDetailAvailable, rowReasonText, rowScoreTargetText, rowScoreText, rowStateText,
  SCORE_COLUMN_LABEL, selectionCountText, sortBatchRows, toggleCandidate, initialBatchForm, type BatchForm,
  type BatchPreflightState, type BatchSort, type BatchSortKey } from "@/lib/docking-batch";
import { CANDIDATE_PAGE_LIMIT, candidateCountText, candidateRowsQuery, checkFilterInput, emptyAppliedFilter,
  emptyFilterInput, LIGAND_APPROVAL_NOTICE, ligandNoticeAfterJob, ligandStartProgressed, passText,
  type AppliedFilter, type LigandFilterInput } from "@/lib/ligand";
import { decimalHalfUp } from "@/lib/site-annotation";
import { FilterForm } from "./LigandPanel";
import { Button } from "./primitives";

/**
 * M19 batch docking area of the "리간드 설계·탐색" tab (spec section 9), mounted after the M18 docking area. Every score,
 * count, budget figure and sentence shown is a server value (preflight read, job record, stored `docking_batch_result@1`);
 * decisions and wording come from `lib/docking-batch.ts`. The page mounts it only while the tab is shown and keys it by
 * run; late responses are dropped by run + selection key + per-area request sequence (`dockingResponseCurrent`).
 */
export interface DockingBatchPanelProps {
  run: RunSummary | null;
  /** undefined while capabilities are being read; null when the backend reports no batch method. */
  capability: DockingBatchCapability | null | undefined;
  onReportCreated: (runId: string) => void;
  /** "상세 열기": the page hands the per-row result handle to the M18 docking area above (no new detail screen). */
  onOpenResult: (runId: string, handle: string) => void;
}

type Load<T> = { status: "idle" } | { status: "loading" } | { status: "ready"; value: T } | { status: "error"; message: string };
type Area = "prereq" | "instances" | "candidates" | "preflight" | "approval" | "job" | "cancel" | "batches" | "detail" |
  "report";
const AXES = ["x", "y", "z"] as const;
const POLL_MS = 2000;

function errorText(e: unknown): string {
  if (e instanceof ApiError) return dockingRequestErrorText(e);
  return e instanceof Error ? e.message : String(e);
}
const shortHandle = (handle: string) => handle.split("/").at(-1)?.slice(0, 12) ?? handle;

function Section({ area, title, state, children }: { area: string; title: string; state?: string; children: ReactNode }) {
  return <section className="mw-ligand-section mw-docking-section" data-batch-area={area} data-state={state} aria-label={title}>
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

export function DockingBatchPanel(p: DockingBatchPanelProps) {
  const heading = <h2 className="mw-ligand-heading">후보 일괄 도킹 (qvina)</h2>;
  if (!p.run || p.capability === null || p.capability?.available === false) {
    const reason = !p.run ? NO_RUN_REASON : dockingCapabilityText(p.capability ?? null);
    return <section className="mw-ligand mw-docking" aria-label="후보 일괄 도킹" data-testid="docking-batch-panel"
      data-batch-state="unavailable">
      {heading}
      <p className="mw-ligand-unavailable" role="status" data-testid={!p.run ? "docking-batch-no-run" : "docking-batch-unavailable"}>
        <b>사용할 수 없음</b>: {reason}</p>
    </section>;
  }
  if (p.capability === undefined) return <section className="mw-ligand mw-docking" aria-label="후보 일괄 도킹"
    data-testid="docking-batch-panel" data-batch-state="loading">
    {heading}<p className="mw-ligand-note" aria-busy="true">기능 상태를 확인하는 중</p></section>;
  return <BatchWorkspace run={p.run} capability={p.capability} onReportCreated={p.onReportCreated}
    onOpenResult={p.onOpenResult} />;
}

function BatchWorkspace({ run, capability, onReportCreated, onOpenResult }: { run: RunSummary;
  capability: DockingBatchCapability; onReportCreated: (runId: string) => void;
  onOpenResult: (runId: string, handle: string) => void }) {
  const runId = run.run_id;
  const [form, setForm] = useState<BatchForm>(initialBatchForm);
  const [prereq, setPrereq] = useState<Load<DockingPrerequisites>>({ status: "idle" });
  const [prereqReload, setPrereqReload] = useState(0);
  const [instances, setInstances] = useState<{ handle: string; load: Load<DockingReceptorInstances> } | null>(null);
  const [filterInput, setFilterInput] = useState<LigandFilterInput>(emptyFilterInput);
  const [filterErrors, setFilterErrors] = useState<string[]>([]);
  const [applied, setApplied] = useState<AppliedFilter>(emptyAppliedFilter);
  const [passesOnly, setPassesOnly] = useState(false);
  const [candidateOffset, setCandidateOffset] = useState(0);
  const [candidates, setCandidates] = useState<{ key: string; load: Load<LigandCandidatePage> } | null>(null);
  const [preflight, setPreflight] = useState<{ key: string; load: Load<DockingBatchPreflight> } | null>(null);
  const [approval, setApproval] = useState<{ key: string; load: Load<DockingBatchLimitApproval> } | null>(null);
  const [job, setJob] = useState<DockingBatchJob | null>(null);
  const [approvalPending, setApprovalPending] = useState(false);
  const [busy, setBusy] = useState(false);
  // The start request is held until the job ends: cancel has its own flag and request sequence.
  const [cancelling, setCancelling] = useState(false);
  const [jobError, setJobError] = useState("");
  const [notice, setNotice] = useState("");
  const [batches, setBatches] = useState<Load<DockingBatchList>>({ status: "idle" });
  const [batchesReload, setBatchesReload] = useState(0);
  const [selectedBatch, setSelectedBatch] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ handle: string; load: Load<DockingBatchDetail> } | null>(null);
  const [sort, setSort] = useState<BatchSort>(null);
  const [report, setReport] = useState<{ handle: string; load: Load<DockingBatchReportArtifact> } | null>(null);

  const mounted = useRef(true);
  const seqs = useRef<Record<Area, number>>({ prereq: 0, instances: 0, candidates: 0, preflight: 0, approval: 0, job: 0,
    cancel: 0, batches: 0, detail: 0, report: 0 });
  const live = useRef({ receptor: form.receptorHandle, set: form.candidateSetHandle, batch: selectedBatch });
  live.current = { receptor: form.receptorHandle, set: form.candidateSetHandle, batch: selectedBatch };
  useEffect(() => {
    mounted.current = true;
    const counters = seqs.current;
    return () => { mounted.current = false; for (const area of Object.keys(counters) as Area[]) counters[area] += 1; };
  }, []);
  const keyOf = (area: Area): string | null => area === "instances" ? live.current.receptor
    : area === "candidates" ? live.current.set : area === "detail" || area === "report" ? live.current.batch : null;
  const stamp = (area: Area): DockingStamp => ({ runId, key: keyOf(area), seq: ++seqs.current[area] });
  const current = (area: Area, captured: DockingStamp) => mounted.current &&
    dockingResponseCurrent(captured, { runId, key: keyOf(area), seq: seqs.current[area] });
  const update = (patch: Partial<BatchForm>) => setForm(previous => {
    const next = patchBatchForm(previous, patch);
    live.current = { ...live.current, receptor: next.receptorHandle, set: next.candidateSetHandle };
    return next;
  });

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
    const captured = stamp("batches"), controller = new AbortController();
    setBatches({ status: "loading" });
    api.dockingBatches(runId, 0, 100, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(value => {
      if (!current("batches", captured)) return;
      if (value.schema !== "docking_batch_list@1") throw new Error("일괄 요약 목록 형식이 다릅니다.");
      setBatches({ status: "ready", value });
    }).catch(e => { if (current("batches", captured) && !controller.signal.aborted)
      setBatches({ status: "error", message: `일괄 요약 목록 읽기 실패: ${errorText(e)}` }); });
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, batchesReload]);

  // After a remount the durable job list tells whether a batch job is still queued or running.
  useEffect(() => {
    const captured = stamp("job"), controller = new AbortController();
    api.dockingBatchJobs(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(list => {
      if (!current("job", captured)) return;
      const running = batchActiveJob<DockingBatchJob>(list, runId);
      if (running) setJob(previous => previous ?? running);
    }).catch(() => undefined);
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // Stored job state (status and finished rows) is read again while the job is queued, claimed or running.
  useEffect(() => {
    if (!job || !dockingJobActive(job)) return;
    let active = true;
    const jobId = job.job_id;
    const timer = window.setInterval(() => {
      void api.dockingBatchJob(runId, jobId).then(value => {
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
      setBatchesReload(value => value + 1);
      const handle = job.batch?.summary_handle ?? null;
      if (handle) setNotice(`일괄 요약이 저장되었습니다 (${shortHandle(handle)}). 아래 일괄 결과 목록에서 직접 고르세요.`);
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

  // Candidate rows of the chosen set with the M17 filter evaluated by the server (generation order).
  const candidateSet = form.candidateSetHandle;
  const candidatesKey = candidateSet ? candidateRowsQuery(candidateSet, applied, { sort: "generation_order",
    direction: "asc", offset: candidateOffset, limit: CANDIDATE_PAGE_LIMIT, passesOnly }) : null;
  useEffect(() => {
    if (!candidateSet || candidatesKey === null) return;
    const key = candidatesKey, handle = candidateSet, captured = stamp("candidates"), controller = new AbortController();
    setCandidates({ key, load: { status: "loading" } });
    api.ligandCandidateRows(runId, key, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(value => {
      if (!current("candidates", captured)) return;
      if (value.schema !== "ligand_candidate_page@1" || value.handle !== handle) throw new Error("후보 행이 고른 후보 집합과 다릅니다.");
      setCandidates({ key, load: { status: "ready", value } });
    }).catch(e => { if (current("candidates", captured) && !controller.signal.aborted)
      setCandidates({ key, load: { status: "error", message: `후보 행 읽기 실패: ${errorText(e)}` } }); });
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidatesKey]);
  const candidateLoad = candidates && candidates.key === candidatesKey ? candidates.load : null;

  function applyFilters() {
    const check = checkFilterInput(filterInput);
    if (!check.ok) { setFilterErrors(check.errors); return; }
    setFilterErrors([]); setApplied({ spec: check.spec, bounds: check.bounds }); setCandidateOffset(0);
  }
  function clearFilters() {
    setFilterInput(emptyFilterInput()); setFilterErrors([]); setApplied(emptyAppliedFilter()); setCandidateOffset(0);
  }

  function openBatch(handle: string) {
    setSelectedBatch(handle); live.current = { ...live.current, batch: handle };
    setSort(null); setReport(null);
    const captured = stamp("detail");
    setDetail({ handle, load: { status: "loading" } });
    api.dockingBatch(runId, handle, AbortSignal.timeout(30000)).then(value => {
      if (!current("detail", captured)) return;
      if (value.schema !== "docking_batch_detail@1" || value.handle !== handle) throw new Error("일괄 요약이 고른 handle과 다릅니다.");
      setDetail({ handle, load: { status: "ready", value } });
    }).catch(e => { if (current("detail", captured))
      setDetail({ handle, load: { status: "error", message: `일괄 요약 읽기 실패: ${errorText(e)}` } }); });
  }
  const opened = detail && detail.handle === selectedBatch && detail.load.status === "ready" ? detail.load.value : null;

  // ---- preflight, limit approval, job ----
  const check = batchArgs(form);
  const argsKey = check.ok ? batchArgsKey(check.args) : null;
  const preflightState: BatchPreflightState = preflight && preflight.load.status === "ready" && preflight.key === argsKey
    ? { key: preflight.key, value: preflight.load.value } : null;
  const shownPreflight = preflightState?.value ?? null;
  const startBlocked = batchStartBlockedReason({ capability, busy, activeJob: job, check, preflight: preflightState,
    dryRun: run.dry_run });

  async function runPreflight(args: DockingBatchArgs) {
    const key = batchArgsKey(args), captured = stamp("preflight");
    setPreflight({ key, load: { status: "loading" } });
    try {
      const value = await api.dockingBatchPreflight(runId, args, AbortSignal.timeout(30000));
      if (!current("preflight", captured)) return;
      if (value.schema !== "docking_batch_preflight@1") throw new Error("시작 전 확인 응답 형식이 다릅니다.");
      setPreflight({ key, load: { status: "ready", value } });
    } catch (e) { if (current("preflight", captured)) setPreflight({ key, load: { status: "error", message: `시작 전 확인 실패: ${errorText(e)}` } }); }
  }

  async function approveLimits() {
    if (!check.ok || !limitApprovalOffered(shownPreflight, run.dry_run)) return;
    const args = check.args, key = batchArgsKey(args), captured = stamp("approval");
    setApproval({ key, load: { status: "loading" } });
    try {
      const value = await api.dockingBatchLimitApproval(runId, args);
      if (!current("approval", captured)) return;
      setApproval({ key, load: { status: "ready", value } });
      await runPreflight(args);
    } catch (e) { if (current("approval", captured)) setApproval({ key, load: { status: "error", message: `한도 증액 실패: ${errorText(e)}` } }); }
  }

  async function start(before: DockingBatchJob) {
    const captured = stamp("job");
    setBusy(true); setJobError(""); setNotice("");
    try {
      const value = await api.startJob(runId, before.job_id) as unknown as DockingBatchJob;
      if (!current("job", captured)) return;
      if (value.run_id !== runId || value.job_id !== before.job_id) throw new Error("시작 응답이 이 작업과 다릅니다.");
      setApprovalPending(false); setJob(value);
    } catch (e) {
      if (!current("job", captured)) return;
      if (e instanceof ApiError && batchApprovalRequired(e.status, e.approval)) { setApprovalPending(true); return; }
      // The start may have taken effect although its response was lost (proxy limit): the stored job decides.
      const stored = await api.dockingBatchJob(runId, before.job_id).catch(() => null);
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
      const result = await api.submitDockingBatch(runId, check.args);
      if (!current("job", captured)) return;
      if ("plan_only" in result) { setNotice("dry-run run이라 계획만 만들었습니다. 실제 계산과 결과 객체는 없습니다."); return; }
      if (result.run_id !== runId || result.protocol_id !== "qvina_batch_dock_v1") throw new Error("제출 응답이 요청과 다릅니다.");
      setJob(result);
      if (result.status !== "queued") {
        setNotice(`같은 입력의 기존 일괄 작업을 다시 표시합니다 · ${result.job_id} · ${result.status} (새 작업을 만들지 않았습니다)`);
        return;
      }
      await start(result);
    } catch (e) { if (current("job", captured)) setJobError(`일괄 작업 제출 실패: ${errorText(e)}`); }
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
      const value = (await api.cancelJob(runId, jobId)).job as unknown as DockingBatchJob;
      if (current("cancel", captured) && value.run_id === runId && value.job_id === jobId)
        setJob(previous => previous?.job_id === jobId ? value : previous);
    } catch (e) { if (current("cancel", captured)) setJobError(`작업 취소 실패: ${errorText(e)}`); }
    finally { if (mounted.current) setCancelling(false); }
  }

  async function makeReport() {
    if (!opened || !selectedBatch || report?.load.status === "loading") return;
    const handle = selectedBatch, captured = stamp("report");
    setReport({ handle, load: { status: "loading" } });
    try {
      const artifact = await api.createDockingBatchReport(runId, handle, AbortSignal.timeout(60000));
      if (!current("report", captured)) return;
      if (!batchReportMatches(artifact, handle)) throw new Error("보고서가 고른 일괄 요약과 다릅니다.");
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
  const chosenCount = orderedCandidateIds(form.candidateOrder).length;
  const parentReasonText = parentDisabledReason(form.mode);
  const phase = dockingJobPhase(job, approvalPending);
  const approvalLoad = approval && approval.key === argsKey ? approval.load : null;
  const preflightLoad = preflight && preflight.key === argsKey ? preflight.load : null;

  return <section className="mw-ligand mw-docking" aria-label="후보 일괄 도킹" data-testid="docking-batch-panel"
    data-batch-state="ready">
    <div className="mw-ligand-head">
      <h2 className="mw-ligand-heading">후보 일괄 도킹 (qvina)</h2>
    </div>
    <p className="mw-ligand-note">한 수용체·한 후보 집합의 후보 {MAX_CANDIDATES}개까지를 같은 수용체·상자·seed·방식·값으로 차례로 도킹합니다.
      점수는 {SCORE_LABEL}입니다. 화면은 저장된 값을 표시만 하며 점수·집계를 계산하지 않습니다.</p>
    {run.dry_run && <p role="status" className="mw-ligand-unavailable" data-testid="docking-batch-dry-run">
      dry-run run: 일괄을 시작하면 계획만 만들며 실제 계산과 결과 객체가 없습니다. 한도 증액도 하지 않습니다.</p>}
    <p className="mw-ligand-note mw-mono" data-testid="docking-batch-capability">
      {capability.engine} · {BATCH_TOOL} · 새로 계산하는 행마다 비싼 계산 예산 1단위</p>
    <div className="mw-ligand-inline">
      <Button size="sm" data-testid="docking-batch-prereq-refresh" disabled={prereq.status === "loading"}
        onClick={() => setPrereqReload(value => value + 1)}>입력 목록 다시 읽기</Button>
      <span className="mw-ligand-note">가져오기는 위 도킹 영역에서 합니다. 위에서 가져온 파일·만든 후보 집합은 다시 읽어야 보입니다.</span>
    </div>
    {prereq.status === "loading" && <p className="mw-ligand-note" aria-busy="true">입력 준비 목록을 읽는 중</p>}
    {prereq.status === "error" && <ErrorLine message={prereq.message} onRetry={() => setPrereqReload(value => value + 1)}
      testId="docking-batch-prereq-error" />}

    <Section area="receptor" title="① 수용체와 뺄 인스턴스">
      <label className="mw-ligand-check">수용체 가져오기
        <select className="mw-select" data-testid="docking-batch-receptor" value={form.receptorHandle ?? ""}
          onChange={event => update({ receptorHandle: event.target.value || null })}>
          <option value="">선택</option>
          {receptors.map(row => <option key={row.handle} value={row.handle}>
            {`생성 순번 ${row.created_seq} · ${row.input_format ?? ""} · ${row.size} B · ${shortHandle(row.handle)}`}</option>)}
        </select></label>
      {prereqValue && !receptors.length && <p className="mw-ligand-note">가져온 수용체가 없습니다.</p>}
      {instances?.handle === receptorHandle && instances?.load.status === "loading" &&
        <p className="mw-ligand-note" aria-busy="true">수용체 인스턴스 목록을 읽는 중</p>}
      {instancesError && <ErrorLine message={instancesError} testId="docking-batch-instances-error" />}
      {listing && <>
        <label className="mw-ligand-check">모델 (암묵적으로 첫 모델을 쓰지 않음)
          <select className="mw-select" data-testid="docking-batch-model" value={form.receptorModelNumber ?? ""}
            onChange={event => update({ receptorModelNumber: event.target.value === "" ? null : Number(event.target.value) })}>
            <option value="">선택</option>
            {listing.model_numbers.map(number => <option key={number} value={number}>{`모델 ${number}`}</option>)}
          </select></label>
        {form.receptorModelNumber !== null && <fieldset className="mw-ligand-choices" data-testid="docking-batch-instances">
          <legend>수용체에서 뺄 리간드 인스턴스 (하나만, 자동으로 고르지 않음)</legend>
          <label data-batch-instance="none">
            <input type="radio" name={`batch-instance-${runId}`} checked={form.instance.kind === "none"}
              onChange={() => update({ instance: { kind: "none" } })} />
            <span>없음(단백질만)</span></label>
          {modelList.map(item => <label key={JSON.stringify(exactResidue(item.residue))}
            data-batch-instance={JSON.stringify(exactResidue(item.residue))}>
            <input type="radio" name={`batch-instance-${runId}`}
              checked={form.instance.kind === "instance" && sameResidue(form.instance.residue, item.residue)}
              onChange={() => update({ instance: { kind: "instance", residue: exactResidue(item.residue) } })} />
            <span className="mw-mono">{removedInstanceText(item)}</span></label>)}
          {!modelList.length && <p className="mw-ligand-note">이 모델에는 물 밖의 비표준 잔기 인스턴스가 없습니다.</p>}
        </fieldset>}
      </>}
      <fieldset className="mw-ligand-choices" data-testid="docking-batch-connectivity">
        <legend>연결 정보</legend>
        <label><input type="radio" name={`batch-connectivity-${runId}`} checked={form.connectivity === "pdb_conect"}
          onChange={() => update({ connectivity: "pdb_conect" })} /> PDB CONECT (파일 안의 완전한 연결 정보)</label>
        <label><input type="radio" name={`batch-connectivity-${runId}`} checked={form.connectivity === "sidecar"}
          onChange={() => update({ connectivity: "sidecar" })} /> 결합 사이드카 (receptor_bonds@1)</label>
        {form.connectivity === "sidecar" && <label className="mw-ligand-check">사이드카 가져오기
          <select className="mw-select" data-testid="docking-batch-sidecar" value={form.sidecarHandle ?? ""}
            onChange={event => update({ sidecarHandle: event.target.value || null })}>
            <option value="">선택</option>
            {sidecars.map(row => <option key={row.handle} value={row.handle}>
              {`생성 순번 ${row.created_seq} · ${row.size} B · ${shortHandle(row.handle)}`}</option>)}
          </select></label>}
      </fieldset>
    </Section>

    <Section area="candidates" title="② 후보 집합과 후보 선택">
      <label className="mw-ligand-check">후보 집합
        <select className="mw-select" data-testid="docking-batch-candidate-set" value={form.candidateSetHandle ?? ""}
          onChange={event => { setCandidateOffset(0); update({ candidateSetHandle: event.target.value || null }); }}>
          <option value="">선택</option>
          {sets.map(set => <option key={set.handle} value={set.handle} disabled={!set.valid}>
            {set.valid ? `${shortHandle(set.handle)} · 후보 ${set.candidates}개` : `${shortHandle(set.handle)} · 읽을 수 없음`}</option>)}
        </select></label>
      {prereqValue && !sets.length && <p className="mw-ligand-note">이 run에 후보 집합이 없습니다(위 후보 영역에서 만듭니다).</p>}
      {chosenSet && (parentReason ? <p className="mw-ligand-unavailable" data-testid="docking-batch-parent-missing">{parentReason}</p>
        : <label className="mw-ligand-check">부모 3D SDF 가져오기 (SHA-256이 후보 집합의 부모와 같은 것만)
          <select className="mw-select" data-testid="docking-batch-parent-sdf" value={form.parentSdfHandle ?? ""}
            onChange={event => update({ parentSdfHandle: event.target.value || null })}>
            <option value="">선택</option>
            {chosenSet.parent_sdf_handles!.map(handle => <option key={handle} value={handle}>{shortHandle(handle)}</option>)}
          </select></label>)}
      {candidateSet && <>
        <FilterForm idPrefix="docking-batch" input={filterInput} errors={filterErrors} applied={applied.spec}
          onInput={setFilterInput} onApply={applyFilters} onClear={clearFilters} />
        <label className="mw-ligand-check"><input type="checkbox" data-testid="docking-batch-passes-only" checked={passesOnly}
          onChange={event => { setPassesOnly(event.target.checked); setCandidateOffset(0); }} /> 필터 통과만 보기</label>
        <p className="mw-ligand-note" data-testid="docking-batch-selection-count" data-selected={chosenCount}>
          {selectionCountText(chosenCount)} · 일괄에는 고른 후보 id만 후보 집합 순서로 기록합니다(필터 조건은 기록하지 않음).</p>
        {chosenCount >= MAX_CANDIDATES && <p className="mw-ligand-note" role="status" data-testid="docking-batch-selection-full">
          후보 {MAX_CANDIDATES}개를 모두 골랐습니다. 다른 후보를 고르려면 먼저 하나를 해제하세요.</p>}
        {candidateLoad?.status === "loading" && <p className="mw-ligand-note" aria-busy="true">후보 행을 읽는 중</p>}
        {candidateLoad?.status === "error" && <ErrorLine message={candidateLoad.message} testId="docking-batch-candidates-error" />}
        {candidateLoad?.status === "ready" && <CandidateChecks page={candidateLoad.value} selection={form.candidateOrder}
          onToggle={(id, order, checked) => update({ candidateOrder: toggleCandidate(form.candidateOrder, id, order, checked) })}
          onPage={setCandidateOffset} />}
      </>}
    </Section>

    <Section area="mode" title="③ 방식과 부모 기준 행">
      <fieldset className="mw-ligand-choices" data-testid="docking-batch-mode">
        <legend>방식 (일괄마다 하나)</legend>
        {MODES.map(mode => <label key={mode} data-batch-mode={mode}>
          <input type="radio" name={`batch-mode-${runId}`} checked={form.mode === mode}
            onChange={() => update({ mode })} /> {MODE_LABEL[mode]}</label>)}
      </fieldset>
      <label className="mw-ligand-check" data-testid="docking-batch-parent-row" data-disabled-reason={parentReasonText ?? undefined}>
        <input type="checkbox" data-testid="docking-batch-include-parent" checked={form.includeParent} disabled={!!parentReasonText}
          onChange={event => update({ includeParent: event.target.checked })} />
        부모 기준 행 넣기 (후보와 같은 설정으로 부모 SDF를 도킹, 선택 사항, 첫 행)</label>
      {parentReasonText && <p className="mw-ligand-note" data-testid="docking-batch-parent-disabled">{parentReasonText}</p>}
    </Section>

    <Section area="box" title="④ 상자 (일괄 전체에 하나)">
      <p className="mw-ligand-note">{BOX_FRAME_NOTE}</p>
      <fieldset className="mw-ligand-choices" data-testid="docking-batch-box-source">
        <legend>상자 출처 (자동으로 고르지 않음)</legend>
        {BOX_SOURCES.map((source: DockingBoxSource) => {
          const reason = boxSourceDisabledReason(source, form.instance);
          return <label key={source} data-batch-box={source} data-disabled-reason={reason ?? undefined}>
            <input type="radio" name={`batch-box-${runId}`} checked={form.boxSource === source} disabled={!!reason}
              onChange={() => update({ boxSource: source })} /> {boxSourceLabel(source)}
            {reason && <span className="mw-ligand-note">{reason}</span>}</label>;
        })}
      </fieldset>
      {(form.boxSource === "ligand_range" || form.boxSource === "instance_range") && <label className="mw-ligand-check">
        여백 (Å, {MARGIN_MIN_A}–{MARGIN_MAX_A}{form.boxSource === "ligand_range" ? ", 부모 SDF 중원자 범위" : ""})
        <input className="mw-ligand-input" data-testid="docking-batch-margin" inputMode="decimal" value={form.margin}
          onChange={event => update({ margin: event.target.value })} /></label>}
      {form.boxSource === "manual" && <div className="mw-docking-grid" data-testid="docking-batch-manual-box">
        {AXES.map((axis, i) => <label key={`c${axis}`} className="mw-ligand-check">중심 {axis} (Å)
          <input className="mw-ligand-input" data-testid={`docking-batch-center-${axis}`} inputMode="decimal" value={form.center[i]}
            onChange={event => update({ center: form.center.map((value, j) => j === i ? event.target.value : value) as BatchForm["center"] })} />
        </label>)}
        {AXES.map((axis, i) => <label key={`s${axis}`} className="mw-ligand-check">크기 {axis} (Å, {BOX_SIDE_MIN_A}–{BOX_SIDE_MAX_A})
          <input className="mw-ligand-input" data-testid={`docking-batch-size-${axis}`} inputMode="decimal" value={form.size[i]}
            onChange={event => update({ size: form.size.map((value, j) => j === i ? event.target.value : value) as BatchForm["size"] })} />
        </label>)}
      </div>}
    </Section>

    <Section area="values" title="⑤ 값과 확인">
      <div className="mw-docking-grid">
        <label className="mw-ligand-check">seed (필수, {SEED_MIN}–{SEED_MAX})
          <input className="mw-ligand-input" data-testid="docking-batch-seed" inputMode="numeric" value={form.seed}
            onChange={event => update({ seed: event.target.value })} /></label>
        <label className="mw-ligand-check">exhaustiveness ({EXHAUSTIVENESS_MIN}–{EXHAUSTIVENESS_MAX})
          <input className="mw-ligand-input" data-testid="docking-batch-exhaustiveness" inputMode="numeric" value={form.exhaustiveness}
            onChange={event => update({ exhaustiveness: event.target.value })} /></label>
        <label className="mw-ligand-check">num_modes ({NUM_MODES_MIN}–{NUM_MODES_MAX})
          <input className="mw-ligand-input" data-testid="docking-batch-num-modes" inputMode="numeric" value={form.numModes}
            onChange={event => update({ numModes: event.target.value })} /></label>
        <label className="mw-ligand-check">energy_range (kcal/mol, {ENERGY_RANGE_MIN}–{ENERGY_RANGE_MAX})
          <input className="mw-ligand-input" data-testid="docking-batch-energy-range" inputMode="decimal" value={form.energyRange}
            onChange={event => update({ energyRange: event.target.value })} /></label>
        {form.mode === "core_fixed" && <label className="mw-ligand-check">conformers ({CONFORMERS_MIN}–{CONFORMERS_MAX}, 코어 고정만)
          <input className="mw-ligand-input" data-testid="docking-batch-conformers" inputMode="numeric" value={form.conformers}
            onChange={event => update({ conformers: event.target.value })} /></label>}
      </div>
      <p className="mw-ligand-note">cpu는 1로 고정됩니다.</p>
      <fieldset className="mw-ligand-choices" data-testid="docking-batch-acknowledgement">
        <legend>제출 전 확인 (세 항목 모두)</legend>
        {ACKNOWLEDGEMENT_KEYS.map((key: DockingAcknowledgementKey) => <label key={key} data-batch-ack={key}>
          <input type="checkbox" checked={form.acknowledgement[key]}
            onChange={event => update({ acknowledgement: { ...form.acknowledgement, [key]: event.target.checked } })} />
          {ACKNOWLEDGEMENT_LABEL[key]}</label>)}
      </fieldset>
      {!check.ok && <ul className="mw-ligand-errors" data-testid="docking-batch-input-errors">
        {check.errors.map(error => <li key={error}>{error}</li>)}</ul>}
    </Section>

    <Section area="preflight" title="⑥ 시작 전 확인" state={preflightLoad?.status}>
      <div className="mw-ligand-inline">
        <Button size="sm" data-testid="docking-batch-preflight" disabled={!check.ok || preflightLoad?.status === "loading"}
          onClick={() => { if (check.ok) void runPreflight(check.args); }}>시작 전 확인 보기</Button>
        {preflight && preflight.key !== argsKey && <span className="mw-ligand-note" data-testid="docking-batch-preflight-stale">
          입력이 바뀌었습니다. 시작 전 확인을 다시 보세요.</span>}
      </div>
      {preflightLoad?.status === "loading" && <p className="mw-ligand-note" aria-busy="true">시작 전 확인을 읽는 중</p>}
      {preflightLoad?.status === "error" && <ErrorLine message={preflightLoad.message} testId="docking-batch-preflight-error" />}
      {shownPreflight && <PreflightView preflight={shownPreflight} />}
      {limitApprovalOffered(shownPreflight, run.dry_run) && <div className="mw-ligand-inline" data-testid="docking-batch-limit-area">
        <Button size="sm" data-testid="docking-batch-limit-approve" disabled={approvalLoad?.status === "loading"}
          onClick={() => void approveLimits()}>{LIMIT_RAISE_LABEL}</Button>
        <span className="mw-ligand-note">사람이 직접 하는 승인입니다. 서버가 누른 시점의 부족분만 올리며(활동 시간은 60초 여유 포함) 되돌리지 않습니다.
          계산 승인을 대신하지 않습니다.</span>
      </div>}
      {approvalLoad?.status === "loading" && <p className="mw-ligand-note" aria-busy="true">한도를 올리는 중</p>}
      {approvalLoad?.status === "ready" && <p role="status" className="mw-ligand-note" data-testid="docking-batch-limit-done"
        data-raised={approvalLoad.value.raised}>{limitApprovalText(approvalLoad.value)}</p>}
      {approvalLoad?.status === "error" && <ErrorLine message={approvalLoad.message} testId="docking-batch-limit-error" />}
    </Section>

    <Section area="start" title="⑦ 일괄 시작">
      <div className="mw-ligand-inline">
        <Button size="sm" variant="primary" data-testid="docking-batch-start" disabled={!!startBlocked}
          title={startBlocked ?? undefined} onClick={() => void submit()}>일괄 시작</Button>
        {startBlocked && <span className="mw-ligand-note" data-testid="docking-batch-start-blocked">{startBlocked}</span>}
      </div>
      {(job || notice || jobError) && <div className="mw-ligand-job" data-testid="docking-batch-job-area">
        {job && <div className="mw-ligand-job" data-testid="docking-batch-job" data-batch-job-phase={phase}
          data-batch-job-status={job.status} data-batch-job-id={job.job_id}
          data-finished-rows={job.batch?.finished_rows} data-rows={job.batch?.rows}>
          <p className="mw-ligand-note" role="status">{batchJobText(job, approvalPending)}</p>
          <p className="mw-ligand-note mw-mono">{BATCH_TOOL} · 작업 {job.status} · {job.job_id}</p>
          {job.batch && <p className="mw-ligand-note" data-testid="docking-batch-progress">{batchProgressText(job.batch)}</p>}
          {job.blocked_reason && <p className="mw-ligand-note">시작 대기 이유: {rowReasonText({ reason_code: job.blocked_reason })}</p>}
          <div className="mw-ligand-inline">
            {phase === "awaiting_approval" && <Button size="sm" data-testid="docking-batch-job-approve" disabled={busy}
              onClick={() => void approveFirstCall()}>비싼 계산 승인</Button>}
            {phase === "saved" && <Button size="sm" data-testid="docking-batch-job-start" disabled={busy || run.dry_run}
              onClick={() => void start(job)}>작업 시작</Button>}
            {dockingJobActive(job) && <Button size="sm" data-testid="docking-batch-job-cancel"
              disabled={!dockingCancelEnabled({ job, cancelling })} onClick={() => void cancelJob()}>작업 취소</Button>}
          </div>
        </div>}
        {notice && <p role="status" className="mw-ligand-note" data-testid="docking-batch-notice">{notice}</p>}
        {jobError && <ErrorLine message={jobError} testId="docking-batch-job-error" />}
      </div>}
    </Section>

    <Section area="results" title="⑧ 일괄 결과" state={batches.status}>
      {batches.status === "loading" && <p className="mw-ligand-note" aria-busy="true">일괄 요약 목록을 읽는 중</p>}
      {batches.status === "error" && <ErrorLine message={batches.message} onRetry={() => setBatchesReload(value => value + 1)} />}
      {batches.status === "ready" && (!batches.value.rows.length ? <p className="mw-ligand-note">이 run에 일괄 결과가 없습니다.</p>
        : <fieldset className="mw-ligand-choices" data-testid="docking-batch-list">
          <legend>일괄 결과 선택 (자동으로 고르지 않음)</legend>
          {batches.value.rows.map(row => <label key={row.handle} data-batch-summary={row.handle} data-valid={row.valid}
            data-batch-status={row.status ?? undefined}>
            <input type="radio" name={`batch-summary-${runId}`} checked={selectedBatch === row.handle} disabled={!row.valid}
              onChange={() => openBatch(row.handle)} />
            <span className="mw-mono">{shortHandle(row.handle)} · {batchListRowText(row)}</span></label>)}
        </fieldset>)}
      {batches.status !== "loading" && <Button size="sm" data-testid="docking-batch-list-refresh"
        onClick={() => setBatchesReload(value => value + 1)}>일괄 결과 목록 다시 읽기</Button>}
      {detail?.handle === selectedBatch && detail.load.status === "loading" && <p className="mw-ligand-note" aria-busy="true">일괄 요약을 읽는 중</p>}
      {detail?.handle === selectedBatch && detail.load.status === "error" &&
        <ErrorLine message={detail.load.message} onRetry={() => selectedBatch && openBatch(selectedBatch)} testId="docking-batch-detail-error" />}
      {opened && <BatchResult detail={opened} sort={sort} onSort={key => setSort(previous => nextBatchSort(previous, key))}
        onOpen={handle => onOpenResult(runId, handle)} />}
      {opened && <>
        <div className="mw-ligand-inline" aria-label="일괄 보고서">
          <Button size="sm" data-testid="docking-batch-report" disabled={report?.handle === selectedBatch && report.load.status === "loading"}
            onClick={() => void makeReport()}>보고서 만들기</Button>
        </div>
        {report?.handle === selectedBatch && report.load.status === "loading" && <p className="mw-ligand-note" aria-busy="true">보고서를 만드는 중</p>}
        {report?.handle === selectedBatch && report.load.status === "ready" && <p role="status" className="mw-ligand-note"
          data-testid="docking-batch-report-done" data-report-handle={report.load.value.handle}>
          리간드 도킹 일괄 보고서를 저장했습니다 · {shortHandle(report.load.value.handle)}. 지식·보고서 탭의 보고서 목록에서 열고 받을 수 있습니다.</p>}
        {report?.handle === selectedBatch && report.load.status === "error" && <ErrorLine message={report.load.message} testId="docking-batch-report-error" />}
      </>}
    </Section>
  </section>;
}

function CandidateChecks({ page, selection, onToggle, onPage }: { page: LigandCandidatePage;
  selection: Record<string, number>; onToggle: (id: string, order: number, checked: boolean) => void;
  onPage: (offset: number) => void }) {
  const last = page.offset + page.rows.length;
  return <div className="mw-ligand-candidates">
    <p className="mw-ligand-note" data-testid="docking-batch-candidate-count" data-total={page.total}
      data-passing={page.passing ?? undefined} data-hidden={page.hidden_by_filter}>{candidateCountText(page)}</p>
    {page.rows.length === 0 ? <p className="mw-ligand-note">표시할 후보 행이 없습니다.</p> : <div className="mw-ligand-table-wrap">
      <table className="mw-ligand-table" data-testid="docking-batch-candidates">
        <thead><tr><th>고르기</th><th>생성 순서</th><th>후보 id</th><th>SMILES (2D)</th><th>입체 (stereo_flag)</th><th>모든 필터</th></tr></thead>
        <tbody>{page.rows.map(row => {
          const id = row.candidate.id, checked = Object.prototype.hasOwnProperty.call(selection, id);
          return <tr key={id} data-batch-candidate={id} data-checked={checked}>
            <td><input type="checkbox" aria-label={`후보 ${id} 고르기`} data-testid={`docking-batch-candidate-${id}`}
              checked={checked} disabled={!candidateSelectable(selection, id)}
              onChange={event => onToggle(id, row.generation_order, event.target.checked)} /></td>
            <td className="mw-mono">{row.generation_order}</td><td className="mw-mono">{id}</td>
            <td className="mw-mono">{row.candidate.smiles}</td><td>{stereoFlagText(row.candidate.stereo_flag)}</td>
            <td>{passText(row.passes_all)}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>}
    <div className="mw-ligand-inline">
      <Button size="sm" disabled={page.offset === 0} onClick={() => onPage(Math.max(0, page.offset - page.limit))}>이전</Button>
      <Button size="sm" disabled={last >= page.matched} onClick={() => onPage(last)}>다음</Button>
      <span className="mw-ligand-note">{page.rows.length ? `${page.offset + 1}–${last}` : "0"} 표시</span>
    </div>
  </div>;
}

function PreflightView({ preflight }: { preflight: DockingBatchPreflight }) {
  if (!preflight.admission.admitted) return <p className="mw-ligand-error" role="alert" data-testid="docking-batch-preflight-refused"
    data-reason-code={preflight.admission.reason_code ?? undefined}>시작할 수 없습니다: {preflightRefusalText(preflight)}</p>;
  return <div className="mw-docking-result" data-testid="docking-batch-preflight-view" data-new-dockings={preflight.new_dockings ?? undefined}
    data-reused-rows={preflight.reused_rows ?? undefined} data-shortfall-calls={preflight.shortfall?.expensive_calls}
    data-shortfall-wall={preflight.shortfall?.wall_clock_s} data-may-be-partial={preflight.full_batch_may_be_partial ?? undefined}>
    <dl className="mw-ligand-facts mw-docking-summary">
      {preflightLines(preflight).map(([label, value]) => <div key={label} className="mw-ligand-fact" data-preflight-line={label}>
        <dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
    {preflight.existing_job && <p className="mw-ligand-note" role="status" data-testid="docking-batch-existing-job"
      data-job-id={preflight.existing_job.job_id}>{existingJobText(preflight.existing_job)}</p>}
    {preflight.rows && <ul className="mw-ligand-list mw-mono" data-testid="docking-batch-preflight-rows">
      {preflight.rows.map(row => <li key={row.row_index} data-row-index={row.row_index} data-reuse={row.reuse}>
        {`행 ${row.row_index} · ${rowCandidateText(row)} · ${row.reuse ? reusedText(true) : "새로 계산"}`}</li>)}</ul>}
    <Statements statements={preflight.statements} testId="docking-batch-preflight-statements" />
  </div>;
}

function Statements({ statements, testId }: { statements: DockingBatchPreflight["statements"]; testId: string }) {
  if (!statements) return null;
  return <ul className="mw-ligand-list" data-testid={testId}>
    {statements.batch.map(item => <li key={item.id} data-statement={item.id}>{item.text}</li>)}
    {statements.m18.map(item => <li key={item.number} data-m18-sentence={item.number}>{item.text}</li>)}
  </ul>;
}

const SORT_HEADERS: { key: BatchSortKey; label: string }[] = [{ key: "row", label: "행 번호" },
  { key: "candidate", label: "후보 id" }];

function BatchResult({ detail, sort, onSort, onOpen }: { detail: DockingBatchDetail; sort: BatchSort;
  onSort: (key: BatchSortKey) => void; onOpen: (handle: string) => void }) {
  const summary = detail.summary, values = summary.parameters;
  const rows = sortBatchRows(detail.rows, sort);
  const header = (key: BatchSortKey, label: string) => <th key={key} aria-sort={ariaSort(sort, key)}>
    <button type="button" className="mw-docking-sort" data-testid={`docking-batch-sort-${key}`}
      onClick={() => onSort(key)}>{label}</button></th>;
  return <div className="mw-docking-result" data-testid="docking-batch-result" data-batch-handle={detail.handle}
    data-batch-status={summary.status} data-stop-reason={summary.stop_reason ?? undefined} data-batch-mode={summary.inputs.mode}>
    <p className="mw-ligand-note mw-mono">일괄 요약 {shortHandle(detail.handle)} · 작업 {detail.job_id}</p>
    <p role="status" className={summary.status === "partial" ? "mw-ligand-unavailable" : "mw-ligand-note"}
      data-testid="docking-batch-status">일괄 상태: {batchStatusText(summary)}</p>
    <ul className="mw-ligand-list" data-testid="docking-batch-statements">
      {detail.statements.batch.map(item => <li key={item.id} data-statement={item.id}>{item.text}</li>)}</ul>
    <dl className="mw-ligand-facts mw-docking-summary" data-testid="docking-batch-settings">
      <div className="mw-ligand-fact"><dt>방식</dt><dd className="mw-mono">{MODE_LABEL[summary.inputs.mode]} · {summary.method}</dd></div>
      <div className="mw-ligand-fact"><dt>seed</dt><dd className="mw-mono">{values.seed}</dd></div>
      <div className="mw-ligand-fact"><dt>값</dt><dd className="mw-mono">{`exhaustiveness ${values.exhaustiveness} · num_modes ` +
        `${values.num_modes} · energy_range ${decimalHalfUp(values.energy_range, 2)} kcal/mol · cpu ${values.cpu}` +
        (values.conformers === null ? "" : ` · conformers ${values.conformers}`)}</dd></div>
      <div className="mw-ligand-fact"><dt>상자</dt><dd className="mw-mono">{boxText(summary.box)}</dd></div>
      <div className="mw-ligand-fact"><dt>수용체</dt><dd className="mw-mono">{`${summary.inputs.receptor.handle} · 모델 ` +
        `${summary.inputs.receptor.model_number}`}</dd></div>
      <div className="mw-ligand-fact"><dt>뺀 인스턴스</dt><dd className="mw-mono">{removedInstanceText(summary.inputs.receptor.removed_instance)}</dd></div>
      <div className="mw-ligand-fact"><dt>후보 집합</dt><dd className="mw-mono">{`${summary.inputs.candidate_set.handle} · 부모 SDF ` +
        `${summary.inputs.candidate_set.parent_sdf_handle}`}</dd></div>
      <div className="mw-ligand-fact"><dt>행 수</dt><dd className="mw-mono">{`${summary.counts.rows} (점수 있음 ${summary.counts.scored} · ` +
        `빈 결과 ${summary.counts.null_result} · 실패 ${summary.counts.failed} · 중단 ${summary.counts.cancelled} · ` +
        `계산하지 않음 ${summary.counts.not_run})`}</dd></div>
    </dl>
    <p className="mw-ligand-note">열 머리를 누르면 표시 순서만 바뀝니다. 점수가 없는 행은 어느 방향이든 맨 아래에 둡니다.
      상세는 위 도킹 영역의 도킹 결과에 열립니다(모드·접촉 표·포즈 SDF 내려받기).</p>
    <div className="mw-ligand-table-wrap">
      <table className="mw-ligand-table" data-testid="docking-batch-rows">
        <caption className="mw-ligand-note">{detail.score_label}</caption>
        <thead><tr>
          {SORT_HEADERS.map(item => header(item.key, item.label))}
          <th>상태</th>
          {header("score", SCORE_COLUMN_LABEL)}
          <th>점수 대상</th><th>이유</th><th>재사용</th><th>상세</th>
        </tr></thead>
        <tbody>{rows.map(row => <tr key={row.row_index} data-row-index={row.row_index} data-row-kind={row.kind}
          data-state={row.state} data-reused={row.reused} data-candidate-id={row.candidate_id ?? undefined}>
          <td className="mw-mono">{row.row_index}</td>
          <td className="mw-mono">{rowCandidateText(row)}</td>
          <td>{rowStateText(row.state)}</td>
          <td className="mw-mono" data-score-cell>{rowScoreText(row)}</td>
          <td>{rowScoreTargetText(row)}</td>
          <td>{rowReasonText(row)}</td>
          <td>{reusedText(row.reused)}</td>
          <td><Button size="sm" data-testid={`docking-batch-open-${row.row_index}`} disabled={!rowDetailAvailable(row)}
            onClick={() => { if (row.result_handle) onOpen(row.result_handle); }}>상세 열기</Button></td>
        </tr>)}</tbody>
      </table>
    </div>
    {detail.statements.m18.length > 0 && <>
      <span className="mw-eyebrow">한계</span>
      <ul className="mw-ligand-list" data-testid="docking-batch-limitations">
        {detail.statements.m18.map(item => <li key={item.number} data-m18-sentence={item.number}>{item.text}</li>)}</ul>
    </>}
  </div>;
}
