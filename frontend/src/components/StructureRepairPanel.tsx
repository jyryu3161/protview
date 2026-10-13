"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type RunSummary, type SavedReportRef } from "@/lib/api";
import type { RepairWarning, RunEvent, StructureOrigin, StructureRepairAtomPage, StructureRepairCapability,
  StructureRepairDetail, StructureRepairJob, StructureRepairListRow, StructureRepairPreflight,
  StructureRepairReportArtifact } from "@/lib/contracts";
import { preparedStructures } from "@/lib/mutations";
import { atomPageCount, atomPageText, atomQuery, ATOM_PAGE_DEFAULT, BUDGET_NOTE, chainEndRows, collisionRows,
  COLLISION_NOTE, CONFIRM_TEXT, coordinatesText, detailMatches, gapRowText, METHOD_NOTE, NO_AUTO_NOTE, NULL_TEXT,
  NUMBER_NOTE, OPEN_RECORD_TEXT, ORIGIN_LABEL, PANEL_TITLE, preflightMatches, preflightView, RECORD_LABEL,
  repairActiveJob, repairApprovalRequired, repairCancelEnabled, repairClassRows, repairInputStructures,
  repairJobActive, repairJobResult, repairJobText, repairListRowText, repairOpenPending, repairPanelState,
  repairReasonText, repairReportMatches, repairReportSavedForRun, repairResponseCurrent, repairStartProgressed,
  repairSubmitBlockedReason, repairSubmitText, repairSummaryText, REPAIR_AREAS, REPAIR_REPORT_TYPE,
  REPAIR_TIMEOUT_DEFAULT_S, REPAIRED_BADGE, replacedRows, residueText, shortHandle, STATE_TEXT,
  TIMEOUT_NOTE, unchangedText, valueText, zeroOccupancyText, type RepairArea, type RepairOpenRequest,
  type RepairStamp } from "@/lib/structure-repair";
import { Button } from "./primitives";

/**
 * M29 "구조 보완" area at the top of the 단백질 공학 tab (`.dryforge/spec.md` 8). Every number shown is a stored server
 * value (the preflight read, the stored `structure_repair@1` record and its atom pages); wording, guards and view models
 * come from `lib/structure-repair.ts`. Nothing is chosen, approved or opened by itself. Late responses are dropped on two
 * layers: abort on unmount / re-key, and run + structure or record handle + per-area request number. No viewer, saved
 * view or bridge: a repaired structure is never shown in Mol*.
 */
export interface StructureRepairPanelProps {
  /** Current run of the structure analysis screen (run selection lives only there); null when none. */
  run: RunSummary | null;
  /** undefined while capabilities are being read; null when the backend reports no such method. */
  capability: StructureRepairCapability | null | undefined;
  /** After a new repaired structure: the page re-reads the run's event log. */
  onObjectsChanged: (runId: string) => void;
  /** After a report was created: the page re-reads the knowledge-tab report list (it drops another run's call). */
  onReportCreated: (runId: string) => void;
  /** "보완 기록 열기" pressed in another area: opened once (when this run's and not handled yet). */
  openRequest?: RepairOpenRequest | null;
  onOpenHandled?: (seq: number) => void;
}

const TIMEOUT_MS = 30000;
const LIST_LIMIT_MAX = 100;
type Load<T> = { status: "idle" } | { status: "loading" } | { status: "ready"; value: T } | { status: "error"; message: string };

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const reason = typeof e.detail?.reason_code === "string" ? e.detail.reason_code : e.code ?? null;
    const blockers = Array.isArray(e.detail?.blockers) ? ` · 걸림돌 ${e.detail.blockers.length}개(사전 검사 표 참고)` : "";
    return `${reason ? repairReasonText(reason) : `HTTP ${e.status}`}: ${e.message}${blockers}`;
  }
  return e instanceof Error ? e.message : String(e);
}

function Section({ area, title, state, children }: { area: string; title: string; state?: string; children: ReactNode }) {
  return <section className="mw-mutation-section" data-repair-area={area} data-state={state} aria-label={title}>
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

/** SO1 (the server's sentence) beside the record handle and "보완 기록 열기" (other areas pass their own test id). */
export function RepairOriginNote({ origin, testId, onOpenRecord }: { origin: StructureOrigin | undefined | null;
  testId: string; onOpenRecord?: (record: string) => void }) {
  if (!origin) return null;
  return <div className="mw-mutation-notice" role="status" data-testid={testId} data-repair-record={origin.repair_record}
    data-repaired-structure={origin.repaired_structure} data-source-structure={origin.source_structure}>
    <span className="mw-catalytic-badge">{REPAIRED_BADGE}</span>
    {origin.statements.map(item => <p key={item.id} data-statement={item.id}>{item.text}</p>)}
    <p className="mw-mono">{RECORD_LABEL} {shortHandle(origin.repair_record)} · 원본 {shortHandle(origin.source_structure)}
      {" "}→ {REPAIRED_BADGE} {shortHandle(origin.repaired_structure)}</p>
    {onOpenRecord && <Button size="sm" data-testid={`${testId}-open`} onClick={() => onOpenRecord(origin.repair_record)}>
      {OPEN_RECORD_TEXT}</Button>}
  </div>;
}

/** JW1 as the server gave it on a JEV preview or approval answer. */
export function RepairWarningNote({ warning, testId }: { warning: RepairWarning | undefined | null; testId: string }) {
  if (!warning) return null;
  return <p className="mw-mutation-notice" role="status" data-testid={testId} data-statement={warning.id}>{warning.text}</p>;
}

export function StructureRepairPanel(p: StructureRepairPanelProps) {
  const runId = p.run?.run_id ?? null;
  if (!p.run || p.capability === undefined || p.capability === null || !p.capability.available) {
    const gate = repairPanelState({ runId, capability: p.capability });
    return <section className="mw-mutation" aria-label={PANEL_TITLE} data-testid="repair-panel"
      data-repair-state={gate.state}>
      <h2 className="mw-mutation-heading">단백질 공학 · {PANEL_TITLE}</h2>
      {gate.state === "unavailable" ? <p className="mw-mutation-unavailable" role="status"
        data-testid={runId === null ? "repair-no-run" : "repair-unavailable"}
        data-reason-code={p.capability?.reason_code ?? undefined}><b>{STATE_TEXT.unavailable}</b>: {gate.reason}</p>
        : <p className="mw-mutation-note" aria-busy="true">기능 상태를 확인하는 중</p>}
    </section>;
  }
  return <RepairWorkspace run={p.run} capability={p.capability} onObjectsChanged={p.onObjectsChanged}
    onReportCreated={p.onReportCreated} openRequest={p.openRequest ?? null} onOpenHandled={p.onOpenHandled} />;
}

function RepairWorkspace({ run, capability, onObjectsChanged, onReportCreated, openRequest, onOpenHandled }: {
  run: RunSummary; capability: StructureRepairCapability; onObjectsChanged: (runId: string) => void;
  onReportCreated: (runId: string) => void; openRequest: RepairOpenRequest | null;
  onOpenHandled?: (seq: number) => void }) {
  const runId = run.run_id;
  const [events, setEvents] = useState<Load<RunEvent[]>>({ status: "idle" });
  const [eventsReload, setEventsReload] = useState(0);
  const [repairs, setRepairs] = useState<Load<StructureRepairListRow[]>>({ status: "idle" });
  const [repairsReload, setRepairsReload] = useState(0);
  // ---- input, preflight and job ----
  const [structure, setStructure] = useState<string | null>(null);
  const [preflight, setPreflight] = useState<{ structure: string; load: Load<StructureRepairPreflight> } | null>(null);
  const [preflightRetry, setPreflightRetry] = useState(0);
  const [confirmed, setConfirmed] = useState(false);
  const [job, setJob] = useState<StructureRepairJob | null>(null);
  const [approvalPending, setApprovalPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [jobError, setJobError] = useState<{ message: string; reasonCode?: string } | null>(null);
  const [notice, setNotice] = useState("");
  const [newRecord, setNewRecord] = useState<string | null>(null);
  // ---- opened record ----
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ handle: string; load: Load<StructureRepairDetail> } | null>(null);
  const [atomPage, setAtomPage] = useState(1);
  const [atoms, setAtoms] = useState<{ key: string; load: Load<StructureRepairAtomPage> } | null>(null);
  const [atomsRetry, setAtomsRetry] = useState(0);
  const [report, setReport] = useState<{ handle: string; load: Load<StructureRepairReportArtifact> } | null>(null);
  const [reportList, setReportList] = useState<{ handle: string; load: Load<SavedReportRef[]> } | null>(null);
  const [reportListReload, setReportListReload] = useState(0);

  // Late responses: run (page key) + structure / record handle + per-area request number, and abort on unmount.
  const mounted = useRef(true);
  const seqs = useRef<Record<RepairArea, number>>(Object.fromEntries(REPAIR_AREAS.map(area => [area, 0])) as
    Record<RepairArea, number>);
  const live = useRef({ structure, selected });
  live.current = { structure, selected };
  useEffect(() => {
    mounted.current = true;
    const counters = seqs.current;
    return () => { mounted.current = false; for (const area of REPAIR_AREAS) counters[area] += 1; };
  }, []);
  const handleOf = (area: RepairArea): string | null => area === "preflight" ? live.current.structure
    : area === "detail" || area === "atoms" || area === "report" || area === "reports" ? live.current.selected : null;
  const stamp = (area: RepairArea): RepairStamp => ({ runId, handle: handleOf(area), seq: ++seqs.current[area] });
  const current = (area: RepairArea, captured: RepairStamp) => mounted.current &&
    repairResponseCurrent(captured, { runId, handle: handleOf(area), seq: seqs.current[area] });

  // ---- run-wide reads (on mount = on entering the tab, and on retry) ----
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    const captured = stamp("events"), controller = new AbortController();
    setEvents({ status: "loading" });
    api.allEvents(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)])).then(value => {
      if (current("events", captured)) setEvents({ status: "ready", value });
    }).catch(e => { if (current("events", captured) && !controller.signal.aborted)
      setEvents({ status: "error", message: `run 기록 읽기 실패: ${errorText(e)}` }); });
    return () => controller.abort();
  }, [runId, eventsReload]);

  useEffect(() => {
    const captured = stamp("list"), controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)]);
    setRepairs({ status: "loading" });
    (async () => {
      const first = await api.structureRepairs(runId, 0, LIST_LIMIT_MAX, signal);
      if (first.schema !== "structure_repair_list@1") throw new Error("보완 기록 목록 형식이 다릅니다.");
      const rows = [...first.rows];
      while (rows.length < first.total) {
        const page = await api.structureRepairs(runId, rows.length, LIST_LIMIT_MAX, signal);
        if (page.total !== first.total || !page.rows.length) throw new Error("보완 기록 목록이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
        rows.push(...page.rows);
      }
      return rows;
    })().then(rows => { if (current("list", captured)) setRepairs({ status: "ready", value: rows }); })
      .catch(e => { if (current("list", captured) && !controller.signal.aborted)
        setRepairs({ status: "error", message: `보완 기록 목록 읽기 실패: ${errorText(e)}` }); });
    return () => controller.abort();
  }, [runId, repairsReload]);

  // After a remount the durable job list tells whether a repair job of this run is still queued or running.
  useEffect(() => {
    const captured = stamp("job"), controller = new AbortController();
    api.structureRepairJobs(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)])).then(list => {
      if (!current("job", captured)) return;
      const running = repairActiveJob(list, runId);
      if (running) setJob(previous => previous ?? running);
    }).catch(() => undefined);
    return () => controller.abort();
  }, [runId]);

  // Polling reads only, while the repair job is queued, claimed or running.
  useEffect(() => {
    if (!job || !repairJobActive(job)) return;
    let active = true;
    const jobId = job.job_id;
    const timer = window.setInterval(() => {
      void api.structureRepairJob(runId, jobId).then(value => {
        if (active && mounted.current && value.run_id === runId && value.job_id === jobId)
          setJob(previous => previous?.job_id === jobId ? value : previous);
      }).catch(() => undefined);
    }, 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [runId, job?.job_id, job?.status]);

  // A finished job refreshes the lists; its record is not opened by itself (the person clicks it).
  useEffect(() => {
    const handle = repairJobResult(job);
    if (handle) {
      setNewRecord(handle); setRepairsReload(value => value + 1); setEventsReload(value => value + 1);
      onObjectsChanged(runId);
    }
  }, [job?.job_id, job?.status]);

  // The preflight of the chosen structure (a free read: no event, tool or job).
  useEffect(() => {
    if (structure === null) return;
    const chosen = structure, captured = stamp("preflight"), controller = new AbortController();
    setPreflight({ structure: chosen, load: { status: "loading" } });
    api.structureRepairPreflight(runId, chosen, AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)]))
      .then(value => {
        if (!current("preflight", captured)) return;
        if (!preflightMatches(value, chosen)) throw new Error("사전 검사 응답이 고른 구조와 다릅니다.");
        setPreflight({ structure: chosen, load: { status: "ready", value } });
      }).catch(e => { if (current("preflight", captured) && !controller.signal.aborted)
        setPreflight({ structure: chosen, load: { status: "error", message: `사전 검사 읽기 실패: ${errorText(e)}` } }); });
    return () => controller.abort();
  }, [structure, preflightRetry]);
  /* eslint-enable react-hooks/exhaustive-deps */

  // ---- opened record: detail, atom pages, reports ----
  function openRecord(handle: string) {
    setSelected(handle); live.current = { ...live.current, selected: handle };
    setAtomPage(1); setAtoms(null); setReport(null); setReportList(null);
    const captured = stamp("detail");
    setDetail({ handle, load: { status: "loading" } });
    api.structureRepair(runId, handle, AbortSignal.timeout(TIMEOUT_MS)).then(value => {
      if (!current("detail", captured)) return;
      if (!detailMatches(value, handle)) throw new Error("보완 기록이 고른 handle과 다릅니다.");
      setDetail({ handle, load: { status: "ready", value } });
    }).catch(e => { if (current("detail", captured))
      setDetail({ handle, load: { status: "error", message: `보완 기록 읽기 실패: ${errorText(e)}` } }); });
  }

  // "보완 기록 열기" from another area: once per request of this run (never replayed after it was handled).
  const pendingOpen = repairOpenPending(openRequest, runId);
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    if (pendingOpen === null || openRequest === null) return;
    onOpenHandled?.(openRequest.seq);
    openRecord(pendingOpen);
    document.querySelector('[data-testid="repair-panel"] [data-repair-area="results"]')?.scrollIntoView({ block: "start" });
  }, [openRequest?.seq, pendingOpen]);
  /* eslint-enable react-hooks/exhaustive-deps */

  const opened = detail && detail.handle === selected && detail.load.status === "ready" ? detail.load.value : null;
  const openedHandle = opened?.handle ?? null;
  const atomsKey = openedHandle ? JSON.stringify([openedHandle, atomPage]) : null;
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    if (!openedHandle || atomsKey === null) return;
    const key = atomsKey, handle = openedHandle, captured = stamp("atoms"), controller = new AbortController();
    setAtoms({ key, load: { status: "loading" } });
    api.structureRepairAtoms(runId, handle, atomQuery(atomPage, ATOM_PAGE_DEFAULT),
      AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)])).then(value => {
      if (!current("atoms", captured)) return;
      if (value.schema !== "structure_repair_atom_page@1" || value.handle !== handle)
        throw new Error("추가 원자 페이지가 고른 기록과 다릅니다.");
      setAtoms({ key, load: { status: "ready", value } });
    }).catch(e => { if (current("atoms", captured) && !controller.signal.aborted)
      setAtoms({ key, load: { status: "error", message: `추가 원자 읽기 실패: ${errorText(e)}` } }); });
    return () => controller.abort();
  }, [atomsKey, atomsRetry]);

  useEffect(() => {
    if (!openedHandle) return;
    const handle = openedHandle, captured = stamp("reports"), controller = new AbortController();
    setReportList({ handle, load: { status: "loading" } });
    api.reports(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)])).then(rows => {
      if (!current("reports", captured)) return;
      setReportList({ handle, load: { status: "ready", value: rows.filter(row =>
        row.analysis_type === REPAIR_REPORT_TYPE && row.result_handle === handle) } });
    }).catch(e => { if (current("reports", captured) && !controller.signal.aborted)
      setReportList({ handle, load: { status: "error", message: `보고서 목록 읽기 실패: ${errorText(e)}` } }); });
    return () => controller.abort();
  }, [openedHandle, reportListReload]);
  /* eslint-enable react-hooks/exhaustive-deps */
  const atomsLoad = atoms && atoms.key === atomsKey ? atoms.load : null;
  const reportListLoad = reportList && reportList.handle === openedHandle ? reportList.load : null;

  // ---- actions (each a person's press) ----
  const shownPreflight = preflight && preflight.structure === structure && preflight.load.status === "ready"
    ? preflight.load.value : null;
  const submitBlocked = repairSubmitBlockedReason({ capability, busy, activeJob: job, structure,
    preflight: shownPreflight, confirmed });

  function chooseStructure(handle: string) {
    setStructure(handle); live.current = { ...live.current, structure: handle };
    setConfirmed(false); setJobError(null); setNotice("");
  }

  async function start(before: StructureRepairJob) {
    const captured = stamp("job");
    setBusy(true); setJobError(null); setNotice("");
    try {
      const value = await api.startJob(runId, before.job_id) as unknown as StructureRepairJob;
      if (!current("job", captured)) return;
      if (value.run_id !== runId || value.job_id !== before.job_id) throw new Error("시작 응답이 이 작업과 다릅니다.");
      setApprovalPending(false); setJob(value);
    } catch (e) {
      if (!current("job", captured)) return;
      if (e instanceof ApiError && repairApprovalRequired(e.status, e.approval)) { setApprovalPending(true); return; }
      // The start may have taken effect although its answer was lost: the stored job decides.
      const stored = await api.structureRepairJob(runId, before.job_id).catch(() => null);
      if (!current("job", captured)) return;
      if (stored && stored.run_id === runId && stored.job_id === before.job_id) setJob(stored);
      if (!stored || !repairStartProgressed(before, stored)) setJobError({ message: `작업 시작 실패: ${errorText(e)}` });
    } finally { if (mounted.current) setBusy(false); }
  }

  async function submit() {
    if (submitBlocked || structure === null) return;
    const chosen = structure, captured = stamp("job");
    setBusy(true); setJobError(null); setNotice(""); setNewRecord(null); setApprovalPending(false);
    try {
      const result = await api.submitStructureRepair(runId, chosen, REPAIR_TIMEOUT_DEFAULT_S);
      if (!current("job", captured)) return;
      if ("plan_only" in result) { setNotice(repairSubmitText(result)); return; }
      if (result.run_id !== runId || result.protocol_id !== "pdbfixer_repair_v1") throw new Error("제출 응답이 요청과 다릅니다.");
      setJob(result);
      if (result.status !== "queued") { setNotice(repairSubmitText(result)); return; }
      await start(result);
    } catch (e) {
      if (!current("job", captured)) return;
      const reasonCode = e instanceof ApiError && typeof e.detail?.reason_code === "string" ? e.detail.reason_code
        : e instanceof ApiError ? e.code : undefined;
      setJobError({ message: `작업 제출 거절: ${errorText(e)}`, reasonCode });
    } finally { if (mounted.current) setBusy(false); }
  }

  async function approve() {
    if (!job) return;
    const captured = stamp("job");
    setBusy(true); setJobError(null);
    try {
      await api.approveOpenmm(runId);
      if (!current("job", captured)) return;
      setApprovalPending(false); setNotice(APPROVED_NOTICE);
    } catch (e) { if (current("job", captured)) setJobError({ message: `승인 실패: ${errorText(e)}` }); }
    finally { if (mounted.current) setBusy(false); }
  }

  // Not tied to the job request number or `busy`: a held start request keeps its own answer.
  async function cancelJob() {
    if (!job || !repairCancelEnabled({ job, cancelling })) return;
    const captured = stamp("cancel"), jobId = job.job_id;
    setCancelling(true);
    try {
      const value = (await api.cancelJob(runId, jobId)).job as unknown as StructureRepairJob;
      if (current("cancel", captured) && value.run_id === runId && value.job_id === jobId)
        setJob(previous => previous?.job_id === jobId ? value : previous);
    } catch (e) { if (current("cancel", captured)) setJobError({ message: `작업 취소 실패: ${errorText(e)}` }); }
    finally { if (mounted.current) setCancelling(false); }
  }

  async function makeReport() {
    if (!opened || !selected || report?.load.status === "loading") return;
    const handle = selected, captured = stamp("report");
    setReport({ handle, load: { status: "loading" } });
    try {
      const artifact = await api.createStructureRepairReport(runId, handle, AbortSignal.timeout(60000));
      if (repairReportSavedForRun(captured, runId) && mounted.current) {
        onReportCreated(runId); setReportListReload(value => value + 1);
      }
      if (!current("report", captured)) return;
      if (!repairReportMatches(artifact, handle)) throw new Error("보고서가 고른 보완 기록과 다릅니다.");
      setReport({ handle, load: { status: "ready", value: artifact } });
    } catch (e) { if (current("report", captured))
      setReport({ handle, load: { status: "error", message: `보고서 만들기 실패: ${errorText(e)}` } }); }
  }

  // ---- states ----
  const eventValue = events.status === "ready" ? events.value : null;
  const inputs = eventValue ? repairInputStructures(preparedStructures(eventValue), eventValue) : undefined;
  const repairRows = repairs.status === "ready" ? repairs.value : undefined;
  const readError = (events.status === "error" ? events.message : null) ??
    (repairs.status === "error" ? repairs.message : null) ??
    (detail?.handle === selected && detail?.load.status === "error" ? detail.load.message : null);
  const panel = repairPanelState({ runId, capability, error: readError, structures: inputs, repairs: repairRows,
    loading: events.status === "loading" || events.status === "idle" || repairs.status === "loading" ||
      repairs.status === "idle" });
  const preflightLoad = preflight && preflight.structure === structure ? preflight.load : null;
  const view = shownPreflight ? preflightView(shownPreflight) : null;
  const awaitingApproval = !!job && approvalPending && job.status === "queued";

  return <section className="mw-mutation" aria-label={PANEL_TITLE} data-testid="repair-panel"
    data-repair-state={panel.state}>
    <div className="mw-mutation-head">
      <h2 className="mw-mutation-heading">단백질 공학 · {PANEL_TITLE}</h2>
      <span className="mw-badge" data-testid="repair-state">{STATE_TEXT[panel.state]}</span>
    </div>
    {panel.state === "failed" && <p role="alert" className="mw-mutation-error" data-testid="repair-failure">
      {panel.message}</p>}
    {panel.state === "empty" && <p role="status" className="mw-mutation-null" data-testid="repair-empty">{panel.message}</p>}
    <p className="mw-mutation-note">{METHOD_NOTE}</p>
    <p className="mw-mutation-note mw-mono" data-testid="repair-capability">
      {capability.tool_id} · {capability.protocol_id} · OpenMM {capability.versions?.openmm ?? NULL_TEXT} · PDBFixer{" "}
      {capability.versions?.pdbfixer ?? NULL_TEXT}</p>
    {run.dry_run && <p role="status" className="mw-mutation-unavailable" data-testid="repair-dry-run">
      dry-run run: 보완 작업을 제출하면 계획만 만들며 실제 계산과 결과 객체는 없습니다.</p>}

    <Section area="input" title="① 전처리 구조" state={events.status}>
      <p className="mw-mutation-note">{NO_AUTO_NOTE}</p>
      {(events.status === "idle" || events.status === "loading") && <p className="mw-mutation-note" aria-busy="true">
        run 기록을 읽는 중</p>}
      {events.status === "error" && <ErrorLine message={events.message} testId="repair-events-error"
        onRetry={() => setEventsReload(value => value + 1)} />}
      {inputs && (!inputs.length ? <p className="mw-mutation-note" data-testid="repair-no-structures">
        이 run에 전처리 구조가 없습니다(보완 구조는 다시 보완하지 않음). 구조 분석 탭에서 먼저 전처리하세요.</p>
        : <fieldset className="mw-mutation-choices" data-testid="repair-structures">
          <legend>보완할 전처리 구조 (이 run, 보완 구조 제외, 자동으로 고르지 않음)</legend>
          {inputs.map(row => {
            const existing = (repairRows ?? []).filter(item => item.valid && item.source_structure === row.handle);
            return <label key={row.handle} data-repair-structure={row.handle}>
              <input type="radio" name={`repair-structure-${runId}`} checked={structure === row.handle}
                data-testid="repair-structure" data-repair-structure={row.handle}
                aria-label={`전처리 구조 ${shortHandle(row.handle)}`} onChange={() => chooseStructure(row.handle)} />
              <span className="mw-mono">prepared_structure · 이벤트 #{row.seq} · {shortHandle(row.handle)}</span>
              {existing.map(item => <span key={item.handle} className="mw-mutation-note" data-testid="repair-structure-existing"
                data-repair-record={item.handle}> · 이 구조의 {RECORD_LABEL} {shortHandle(item.handle)}{" "}
                <Button size="sm" data-testid="repair-structure-existing-open" onClick={() => openRecord(item.handle)}>
                  {OPEN_RECORD_TEXT}</Button></span>)}
            </label>;
          })}
        </fieldset>)}
    </Section>

    <Section area="preflight" title="② 사전 검사 (무료 읽기)" state={preflightLoad?.status}>
      {structure === null ? <p className="mw-mutation-note" data-testid="repair-preflight-none">
        위에서 전처리 구조를 고르면 사전 검사 결과를 읽습니다(작업·이벤트를 만들지 않음).</p> : <>
        {preflightLoad?.status === "loading" && <p className="mw-mutation-note" aria-busy="true">사전 검사를 읽는 중</p>}
        {preflightLoad?.status === "error" && <ErrorLine message={preflightLoad.message} testId="repair-preflight-error"
          onRetry={() => setPreflightRetry(value => value + 1)} />}
        {shownPreflight && view && <PreflightBlock preflight={shownPreflight} view={view} />}
      </>}
    </Section>

    <Section area="start" title="③ 보완 작업" state={job?.status}>
      <p className="mw-mutation-notice" data-testid="repair-budget-note">{BUDGET_NOTE}</p>
      <p className="mw-mutation-note" data-testid="repair-timeout-note">{TIMEOUT_NOTE}</p>
      <label className="mw-mutation-check"><input type="checkbox" data-testid="repair-confirm" checked={confirmed}
        disabled={structure === null} onChange={event => setConfirmed(event.target.checked)} /> {CONFIRM_TEXT}</label>
      <div className="mw-mutation-inline">
        <Button size="sm" variant="primary" data-testid="repair-submit" disabled={!!submitBlocked}
          title={submitBlocked ?? undefined} onClick={() => void submit()}>보완 작업 제출</Button>
        {submitBlocked && <span className="mw-mutation-note" data-testid="repair-submit-blocked">{submitBlocked}</span>}
      </div>
      {(job || notice || jobError || newRecord) && <div className="mw-mutation-group" data-testid="repair-job-area">
        {job && <div data-testid="repair-job" data-job-status={job.status} data-job-id={job.job_id}
          data-approval-pending={awaitingApproval || undefined}>
          <p className="mw-mutation-note" role="status" data-testid="repair-job-text">{repairJobText(job, approvalPending)}</p>
          <p className="mw-mutation-note mw-mono">{capability.tool_id} · 작업 {job.status} · 시도 {job.attempt_ordinal} · {job.job_id}</p>
          {job.blocked_reason && <p className="mw-mutation-note">시작 대기 이유: {repairReasonText(job.blocked_reason)}</p>}
          <div className="mw-mutation-inline">
            {awaitingApproval && <Button size="sm" data-testid="repair-job-approve" disabled={busy}
              onClick={() => void approve()}>비싼 계산 승인</Button>}
            {job.status === "queued" && !awaitingApproval && <Button size="sm" data-testid="repair-job-start"
              disabled={busy || run.dry_run} onClick={() => void start(job)}>작업 시작</Button>}
            {repairJobActive(job) && <Button size="sm" data-testid="repair-job-cancel"
              disabled={!repairCancelEnabled({ job, cancelling })} onClick={() => void cancelJob()}>작업 취소</Button>}
          </div>
        </div>}
        {notice && <p role="status" className="mw-mutation-note" data-testid="repair-notice">{notice}</p>}
        {jobError && <ErrorLine message={jobError.message} testId="repair-job-error" reasonCode={jobError.reasonCode} />}
        {newRecord && <div className="mw-mutation-inline" data-testid="repair-new" data-repair-record={newRecord}>
          <span className="mw-mutation-note" role="status">{RECORD_LABEL}과 {REPAIRED_BADGE}를 저장했습니다 · {shortHandle(newRecord)}</span>
          <Button size="sm" data-testid="repair-open-new" onClick={() => openRecord(newRecord)}>이 기록 열기</Button>
        </div>}
      </div>}
    </Section>

    <Section area="results" title="④ 저장된 보완 기록" state={repairs.status}>
      {repairs.status === "loading" && <p className="mw-mutation-note" aria-busy="true">보완 기록 목록을 읽는 중</p>}
      {repairs.status === "error" && <ErrorLine message={repairs.message} testId="repair-list-error"
        onRetry={() => setRepairsReload(value => value + 1)} />}
      {repairRows && (!repairRows.length ? <p className="mw-mutation-note" data-testid="repair-list-empty">
        이 run에 보완 기록이 없습니다.</p>
        : <fieldset className="mw-mutation-choices" data-testid="repair-records">
          <legend>보완 기록 (최신 순, 자동으로 열지 않음)</legend>
          {repairRows.map(row => <label key={row.handle} data-repair-record={row.handle} data-valid={row.valid}>
            <input type="radio" name={`repair-record-${runId}`} checked={selected === row.handle} disabled={!row.valid}
              data-testid="repair-record" data-repair-record={row.handle}
              aria-label={`보완 기록 ${shortHandle(row.handle)}`} onChange={() => openRecord(row.handle)} />
            <span className="mw-mono">{repairListRowText(row)} · {shortHandle(row.handle)}</span>
          </label>)}
        </fieldset>)}
      {repairs.status !== "loading" && <Button size="sm" data-testid="repair-list-refresh"
        onClick={() => setRepairsReload(value => value + 1)}>보완 기록 목록 다시 읽기</Button>}
      {detail?.handle === selected && detail.load.status === "loading" && <p className="mw-mutation-note" aria-busy="true">
        보완 기록을 읽는 중</p>}
      {detail?.handle === selected && detail.load.status === "error" && <ErrorLine message={detail.load.message}
        testId="repair-detail-error" onRetry={() => selected && openRecord(selected)} />}
    </Section>

    {opened && <Section area="detail" title="⑤ 보완 결과">
      <RecordView detail={opened} runId={runId} atomsLoad={atomsLoad} onAtomPage={setAtomPage}
        onAtomsRetry={() => setAtomsRetry(value => value + 1)} />
      <div className="mw-mutation-group" aria-label="보고서" data-testid="repair-report-area">
        <span className="mw-eyebrow">{RECORD_LABEL} 보고서 (보완을 다시 하지 않음)</span>
        <div className="mw-mutation-inline">
          <Button size="sm" data-testid="repair-report" disabled={report?.handle === selected && report.load.status === "loading"}
            onClick={() => void makeReport()}>보고서 만들기</Button>
        </div>
        {report?.handle === selected && report.load.status === "loading" && <p className="mw-mutation-note" aria-busy="true">
          보고서를 만드는 중</p>}
        {report?.handle === selected && report.load.status === "ready" && <p role="status" className="mw-mutation-note"
          data-testid="repair-report-done" data-report-handle={report.load.value.handle}>
          보고서를 저장했습니다 · {shortHandle(report.load.value.handle)}. 지식·보고서 탭의 보고서 목록에서도 볼 수 있습니다.</p>}
        {report?.handle === selected && report.load.status === "error" && <ErrorLine message={report.load.message}
          testId="repair-report-error" />}
        {reportListLoad?.status === "loading" && <p className="mw-mutation-note" aria-busy="true">보고서 목록을 읽는 중</p>}
        {reportListLoad?.status === "error" && <ErrorLine message={reportListLoad.message} testId="repair-report-list-error"
          onRetry={() => setReportListReload(value => value + 1)} />}
        {reportListLoad?.status === "ready" && (!reportListLoad.value.length
          ? <p className="mw-mutation-note" data-testid="repair-report-list-empty">이 기록의 저장된 보고서가 없습니다.</p>
          : <ul className="mw-mutation-list" data-testid="repair-report-list">
            {reportListLoad.value.map(row => <li key={row.handle} data-report-handle={row.handle}>
              <span className="mw-mono">이벤트 #{row.created_seq} · {shortHandle(row.handle)}</span>{" "}
              <a className="mw-btn mw-btn--sm" data-testid="repair-report-markdown"
                href={api.reportDownload(runId, row.handle, "markdown")} download>Markdown 내려받기</a>{" "}
              <a className="mw-btn mw-btn--sm" data-testid="repair-report-json"
                href={api.reportDownload(runId, row.handle, "json")} download>JSON 내려받기</a>
            </li>)}
          </ul>)}
      </div>
    </Section>}
  </section>;
}

const APPROVED_NOTICE = "승인을 기록했습니다. 작업 시작을 누르면 실제 계산이 실행됩니다.";

function Table({ testId, head, rows, empty }: { testId: string; head: string[]; rows: (string | ReactNode)[][];
  empty: string }) {
  if (!rows.length) return <p className="mw-mutation-note" data-testid={`${testId}-empty`}>{empty}</p>;
  return <div className="mw-mutation-table-wrap"><table className="mw-mutation-table" data-testid={testId}
    data-count={rows.length}>
    <thead><tr>{head.map(text => <th key={text}>{text}</th>)}</tr></thead>
    <tbody>{rows.map((cells, index) => <tr key={index} data-row={index}>
      {cells.map((cell, column) => <td key={column} className="mw-mono">{cell}</td>)}</tr>)}</tbody>
  </table></div>;
}

function PreflightBlock({ preflight, view }: { preflight: StructureRepairPreflight; view: ReturnType<typeof preflightView> }) {
  const admissionCode = preflight.admission?.reason_code ?? preflight.admission?.error ?? undefined;
  return <div className="mw-mutation-group" data-testid="repair-preflight" data-structure={preflight.structure}
    data-repairable={preflight.repairable === null ? "null" : String(preflight.repairable)}
    data-admitted={String(view.admitted)} data-reason-code={view.admitted ? undefined : admissionCode}>
    <p data-testid="repair-preflight-repairable">{view.repairableText}</p>
    <p className={view.admitted ? "mw-mutation-note" : "mw-mutation-notice"} role="status"
      data-testid="repair-preflight-admission">{view.admissionText}</p>
    <span className="mw-eyebrow">걸림돌 ({view.blockers.length}개)</span>
    <Table testId="repair-blockers" head={["이유", "위치", "내용"]} empty="걸림돌 없음 (0개)"
      rows={view.blockers.map(item => [<span key="r" data-reason-code={item.code}>{item.reason}</span>, item.where,
        item.detail || NULL_TEXT])} />
    <span className="mw-eyebrow">결함 (사전 검사 목록 그대로)</span>
    <p className="mw-mutation-note" data-testid="repair-preflight-expected">{view.expectedText}</p>
    <Table testId="repair-defect-chain-parts" head={["저자 체인", "조각 수"]} empty="조각으로 나뉜 체인 0개"
      rows={view.chainParts.map(item => [item.chain, item.parts])} />
    <Table testId="repair-defect-side-chain" head={["잔기", "잔기 7필드", "빠진 곁사슬 원자"]} empty="곁사슬 결손 잔기 0개"
      rows={view.sideChain.map(item => [item.residue, item.fields, item.missing])} />
    <Table testId="repair-defect-oxt" head={["C 말단 잔기 (OXT 없음)", "잔기 7필드"]} empty="OXT 없는 C 말단 0개"
      rows={view.oxt.map(item => [item.residue, item.fields])} />
    <Table testId="repair-defect-gaps" head={["체인", "앞 잔기", "뒤 잔기", "길이 (잔기)", "틈 잔기 (파일 목록)"]}
      empty="내부 틈 0개" rows={view.gaps.map(item => [item.chain, item.after, item.before, item.length, item.residues])} />
    <Table testId="repair-defect-nonstandard" head={["MSE 잔기", "잔기 7필드", "바꿀 이름"]} empty="MSE 잔기 0개"
      rows={view.nonstandard.map(item => [item.residue, item.fields, item.to])} />
    {view.statements.length > 0 && <div data-testid="repair-preflight-statements">
      <span className="mw-eyebrow">한계 (고정 문장, 보완하면 기록에 들어감)</span>
      {view.statements.map(text => <p key={text} className="mw-mutation-note">{text}</p>)}
    </div>}
    <p className="mw-mutation-note" data-testid="repair-preflight-budget">{view.budgetText}</p>
    {view.shortfallText && <p className="mw-mutation-notice" role="status" data-testid="repair-preflight-shortfall">
      {view.shortfallText}</p>}
  </div>;
}

function RecordView({ detail, runId, atomsLoad, onAtomPage, onAtomsRetry }: { detail: StructureRepairDetail;
  runId: string; atomsLoad: Load<StructureRepairAtomPage> | null; onAtomPage: (page: number) => void;
  onAtomsRetry: () => void }) {
  const record = detail.result;
  const atomPageValue = atomsLoad?.status === "ready" ? atomsLoad.value : null;
  return <div className="mw-mutation-group" data-testid="repair-detail" data-repair-record={detail.handle}
    data-repaired-structure={detail.prepared_structure} data-source-structure={detail.source_structure}>
    <p data-testid="repair-summary" data-protein-heavy-atoms={record.counts.protein_heavy_atoms}
      data-added-residues={record.counts.added_residues} data-added-atoms={record.counts.added_atoms}>
      {repairSummaryText(record)}</p>
    <p className="mw-mutation-note">{NUMBER_NOTE}</p>
    <dl className="mw-mutation-facts" data-testid="repair-facts">
      <dt>{RECORD_LABEL}</dt><dd className="mw-mono">{detail.handle}</dd>
      <dt>원본 전처리 구조</dt><dd className="mw-mono">{detail.source_structure} (모델 {record.source.model_number})</dd>
      <dt>{REPAIRED_BADGE}</dt><dd className="mw-mono">{detail.prepared_structure}</dd>
      <dt>방법</dt><dd className="mw-mono">{record.method_version} · {record.method.engine} {record.method.pdbfixer_version}
        {" "}· OpenMM {record.method.openmm_distribution_version} · seed {record.parameters.seed} · {record.parameters.repair_policy}</dd>
      <dt>정책</dt><dd className="mw-mono">물 {record.parameters.waters} · 수소 {record.parameters.hydrogens} · 틈 상한{" "}
        {record.parameters.max_gap_residues}잔기</dd>
    </dl>

    <span className="mw-eyebrow">보완 종류</span>
    <Table testId="repair-classes" head={["보완 종류", "적용", "기록된 개수"]} empty={NULL_TEXT}
      rows={repairClassRows(record).map(row => [<span key="c" data-class={row.key} data-applied={row.applied}>{row.label}
        {" "}({row.key})</span>, row.appliedText, row.countText])} />

    <span className="mw-eyebrow">추가 잔기 (메운 틈, 파일의 서열·미관측 잔기 목록 그대로)</span>
    <Table testId="repair-gaps" head={["체인", "앞 잔기", "뒤 잔기", "길이 (잔기)", "추가 잔기"]} empty="메운 틈 0개"
      rows={record.gaps.map(gap => { const row = gapRowText(gap); return [row.chain, row.after, row.before, row.length,
        row.residues]; })} />

    <span className="mw-eyebrow">체인 조각</span>
    <Table testId="repair-chain-parts" head={["저자 체인", "조각 수", "합침"]} empty={NULL_TEXT}
      rows={record.chain_parts.map(item => [item.chain_auth, valueText(item.parts), item.merged ? "합침" : "합치지 않음"])} />

    <span className="mw-eyebrow">추가 원자 (PDBFixer 모델링 좌표, 구조 순서)</span>
    <div data-testid="repair-atoms-area">
      {atomsLoad?.status === "loading" && <p className="mw-mutation-note" aria-busy="true">추가 원자를 읽는 중</p>}
      {atomsLoad?.status === "error" && <ErrorLine message={atomsLoad.message} testId="repair-atoms-error" onRetry={onAtomsRetry} />}
      {atomPageValue && <>
        <Table testId="repair-atoms" head={["순서", "잔기", "원자", "원소", "좌표 (Å, 저장값)", "출처"]} empty="추가 원자 0개"
          rows={atomPageValue.rows.map(atom => [valueText(atom.index), residueText(atom.residue), atom.atom_name, atom.element,
            coordinatesText(atom.coordinates_A), ORIGIN_LABEL[atom.origin] ?? atom.origin])} />
        <div className="mw-mutation-inline" data-testid="repair-atoms-pager" data-total={atomPageValue.total}
          data-page={atomPageValue.page}>
          <span className="mw-mutation-note">{atomPageText(atomPageValue)}</span>
          <Button size="sm" data-testid="repair-atoms-prev" disabled={atomPageValue.page <= 1}
            onClick={() => onAtomPage(atomPageValue.page - 1)}>이전</Button>
          <Button size="sm" data-testid="repair-atoms-next" disabled={atomPageValue.page >= atomPageCount(atomPageValue)}
            onClick={() => onAtomPage(atomPageValue.page + 1)}>다음</Button>
        </div>
      </>}
    </div>

    <span className="mw-eyebrow">치환 잔기 (MSE→MET, 원래 7필드와 새 7필드)</span>
    <Table testId="repair-replaced" head={["원래 잔기", "원래 7필드", "새 잔기", "새 7필드", "원자 이름", "레코드"]}
      empty="치환 잔기 0개" rows={replacedRows(record).map(row => [row.from, row.fromFields, row.to, row.toFields, row.atoms,
        row.recordType])} />

    <span className="mw-eyebrow">체인 끝 (관측된 끝과 서열 끝)</span>
    <Table testId="repair-chain-ends" head={["체인", "관측 첫 잔기", "관측 끝 잔기", "첫 잔기 = 서열 시작", "끝 잔기 = 서열 끝"]}
      empty={NULL_TEXT} rows={chainEndRows(record).map(row => [row.chain, row.first, row.last, row.start, row.end])} />

    <span className="mw-eyebrow">충돌 기록 (분류별, 기록만)</span>
    <p className="mw-mutation-note">{COLLISION_NOTE}</p>
    <Table testId="repair-collisions" head={["상대 분류", "최소 거리", "2.0 Å 미만 새 원자 수", "1.5 Å 미만 새 원자 수",
      "최소 거리 쌍"]} empty={NULL_TEXT} rows={collisionRows(record).map(row => [<span key="k" data-collision={row.key}
        data-has-partner={row.hasPartner}>{row.label}</span>, row.min, row.lt20, row.lt15, row.pair])} />

    <span className="mw-eyebrow">점유율 0 입력 원자</span>
    <p className="mw-mutation-note" data-testid="repair-zero-occupancy" data-count={record.zero_occupancy_input_atoms.count}>
      {zeroOccupancyText(record.zero_occupancy_input_atoms)}</p>
    <p className="mw-mutation-note mw-mono" data-testid="repair-unchanged">{unchangedText(record)}</p>

    <div className="mw-mutation-group" aria-label="한계" data-testid="repair-limitations">
      <span className="mw-eyebrow">한계 (고정 문장)</span>
      {record.limitations.map((sentence, index) => <p key={index} className="mw-mutation-note" data-limitation={index}>
        {sentence}</p>)}
    </div>

    <div className="mw-mutation-inline">
      <a className="mw-btn mw-btn--sm" data-testid="repair-download" href={api.structureRepairStructureUrl(runId, detail.handle)}
        download>{REPAIRED_BADGE} mmCIF 내려받기 (저장된 바이트)</a>
    </div>
    <p className="mw-mutation-note">{REPAIRED_BADGE}는 뷰어에 올리지 않습니다. 원자 하나하나는 위 표와 내려받은 mmCIF의
      calc_flag(새 원자 c)로 확인합니다.</p>
    {chainEndRows(record).some(row => row.differs) && <p className="mw-mutation-note" data-testid="repair-chain-end-note">
      관측 끝이 서열 끝과 다른 체인이 있습니다(위 표의 &quot;다름&quot;).</p>}
  </div>;
}
