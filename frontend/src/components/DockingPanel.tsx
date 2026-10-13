"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type RunSummary } from "@/lib/api";
import type { ChemicalImport } from "@/lib/chemical";
import type { BudgetSnapshot, DockingAcknowledgementKey, DockingBoxSource, DockingCapability, DockingContactPage,
  DockingJob, DockingLigandSource, DockingMode, DockingPrerequisites, DockingReceptorInstances, DockingReportArtifact,
  DockingResultDetail, DockingResultList, LigandCandidatePage } from "@/lib/contracts";
import { ACKNOWLEDGEMENT_KEYS, ACKNOWLEDGEMENT_LABEL, BOX_FRAME_NOTE, BOX_SIDE_MAX_A, BOX_SIDE_MIN_A, BOX_SOURCES,
  boxSourceDisabledReason, boxSourceLabel, CANDIDATE_SOURCE_NOTES, CONFORMERS_MAX, CONFORMERS_MIN, CONTACT_NOTE, CONTACT_PAGE_LIMIT,
  contactKindText, contactPageText, distanceText, DOCKING_STATE_TEXT, DOCKING_TOOL, dockingActiveJob, dockingApprovalRequired,
  dockingArgs, dockingCancelEnabled, dockingJobActive, dockingJobRefusalList, dockingJobPhase, dockingJobText, dockingPanelState, dockingReasonText,
  dockingReportMatches, dockingRequestErrorText, dockingRequestRefusalList, dockingResponseCurrent, dockingResultRowText, dockingSubmitBlockedReason,
  dockingSubmitText, dockingSummaryRows, ENERGY_RANGE_MAX, ENERGY_RANGE_MIN, EXHAUSTIVENESS_MAX, EXHAUSTIVENESS_MIN,
  exactResidue, importsOfKind, initialDockingForm, LIGAND_SOURCES, ligandAtomText, MARGIN_MAX_A, MARGIN_MIN_A, MODE_LABEL,
  modeDisabledReason, modelInstances, modeRowLabel, MODES, modeTableCells, modeTableHeaders, NUM_MODES_MAX, NUM_MODES_MIN,
  parentSdfMissingReason, patchDockingForm, receptorAtomText, removedInstanceText, sameResidue, SCORE_LABEL, SEED_MAX,
  SEED_MIN, stereoFlagText, type DockingForm, type DockingRefusalList, type DockingStamp } from "@/lib/docking";
import { CANDIDATE_PAGE_LIMIT, candidateRowsQuery, emptyAppliedFilter, LIGAND_APPROVAL_NOTICE, ligandNoticeAfterJob,
  ligandStartProgressed } from "@/lib/ligand";
import { Button } from "./primitives";
import { RepairOriginNote } from "./StructureRepairPanel";

/**
 * M18 docking area of the "리간드 설계·탐색" tab (spec section 8), mounted next to the candidate area (`LigandPanel`).
 * Every score, contact, distance, box and count shown is a stored `docking_result@1` value read from the backend;
 * decisions, wording and rounding come from `lib/docking.ts`. The page mounts it only while the tab is shown and keys
 * it by run; late responses are dropped by run + selection key + per-area request sequence (`dockingResponseCurrent`).
 */
export interface DockingPanelProps {
  /** Current run of the structure analysis screen (run selection lives only there); null when none. */
  run: RunSummary | null;
  /** undefined while capabilities are being read; null when the backend reports no docking method. */
  capability: DockingCapability | null | undefined;
  /** After a report was created: the page re-reads the knowledge-tab report list (it drops another run's call). */
  onReportCreated: (runId: string) => void;
  /** M19: "상세 열기" of a batch row opens that stored result here (a new `seq` per click; same run only). */
  openRequest?: { runId: string; handle: string; seq: number } | null;
  /** M29: "보완 기록 열기" of a result whose receptor is a model on a repaired structure (opened in the repair area). */
  onOpenRepairRecord?: (runId: string, record: string) => void;
}

type Load<T> = { status: "idle" } | { status: "loading" } | { status: "ready"; value: T } | { status: "error"; message: string };
type Area = "prereq" | "imports" | "instances" | "candidates" | "job" | "cancel" | "budget" | "results" | "detail" | "contacts" |
  "report";
type Slot = "receptor" | "bonds" | "ligand";
const SLOT_KIND: Record<Slot, ChemicalImport["kind"]> = { receptor: "receptor", bonds: "receptor_bonds", ligand: "ligand_sdf" };
const SLOT_LABEL: Record<Slot, string> = { receptor: "수용체 (PDB·mmCIF, 명시적 수소와 연결 정보 포함)",
  bonds: "결합 사이드카 (receptor_bonds@1 JSON, 선택)", ligand: "리간드 3D SDF (V2000, 분자 1개, 명시적 수소)" };
const SLOT_ACCEPT: Record<Slot, string> = { receptor: ".pdb,.cif,.mmcif", bonds: ".json", ligand: ".sdf" };
const SLOTS: readonly Slot[] = ["receptor", "bonds", "ligand"];
const SOURCE_LABEL: Record<DockingLigandSource, string> = { sdf: "3D SDF 가져오기", candidate: "M17 후보 + 부모 3D SDF" };
const LIST_LIMIT = 100;
const AXES = ["x", "y", "z"] as const;

function errorText(e: unknown): string {
  if (e instanceof ApiError) return dockingRequestErrorText(e);
  return e instanceof Error ? e.message : String(e);
}
const shortHandle = (handle: string) => handle.split("/").at(-1)?.slice(0, 12) ?? handle;

async function allResults(runId: string, signal: AbortSignal): Promise<DockingResultList> {
  const first = await api.dockingResults(runId, 0, LIST_LIMIT, signal);
  if (first.schema !== "docking_result_list@1") throw new Error("도킹 결과 목록 형식이 다릅니다.");
  const rows = [...first.rows];
  while (rows.length < first.total) {
    const page = await api.dockingResults(runId, rows.length, LIST_LIMIT, signal);
    if (page.total !== first.total || !page.rows.length) throw new Error("도킹 결과 목록이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
    rows.push(...page.rows);
  }
  return { ...first, offset: 0, limit: rows.length, rows };
}

function Section({ area, title, state, children }: { area: string; title: string; state?: string; children: ReactNode }) {
  return <section className="mw-ligand-section mw-docking-section" data-docking-area={area} data-state={state} aria-label={title}>
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

export function DockingPanel(p: DockingPanelProps) {
  const runId = p.run?.run_id ?? null;
  const gate = dockingPanelState({ runId, capability: p.capability });
  if (!p.run || gate.state === "unavailable" || p.capability === undefined || p.capability === null) {
    const state = gate.state === "unavailable" ? "unavailable" : "loading";
    return <section className="mw-ligand mw-docking" aria-label="리간드 도킹" data-testid="docking-panel" data-docking-state={state}>
      <h2 className="mw-ligand-heading">리간드 도킹 (qvina)</h2>
      {gate.state === "unavailable" ? <p className="mw-ligand-unavailable" role="status"
        data-testid={runId === null ? "docking-no-run" : "docking-unavailable"}><b>{DOCKING_STATE_TEXT.unavailable}</b>: {gate.reason}</p>
        : <p className="mw-ligand-note" aria-busy="true">기능 상태를 확인하는 중</p>}
    </section>;
  }
  return <DockingWorkspace run={p.run} capability={p.capability} onReportCreated={p.onReportCreated}
    openRequest={p.openRequest ?? null} onOpenRepairRecord={p.onOpenRepairRecord} />;
}

function DockingWorkspace({ run, capability, onReportCreated, openRequest, onOpenRepairRecord }: { run: RunSummary;
  capability: DockingCapability; onReportCreated: (runId: string) => void;
  openRequest: DockingPanelProps["openRequest"]; onOpenRepairRecord?: DockingPanelProps["onOpenRepairRecord"] }) {
  const runId = run.run_id;
  const [form, setForm] = useState<DockingForm>(initialDockingForm);
  const [files, setFiles] = useState<Record<Slot, File | null>>({ receptor: null, bonds: null, ligand: null });
  const [importState, setImportState] = useState<Load<string[]>>({ status: "idle" });
  const [prereq, setPrereq] = useState<Load<DockingPrerequisites>>({ status: "idle" });
  const [prereqReload, setPrereqReload] = useState(0);
  const [instances, setInstances] = useState<{ handle: string; load: Load<DockingReceptorInstances> } | null>(null);
  const [candidateOffset, setCandidateOffset] = useState(0);
  const [candidates, setCandidates] = useState<{ key: string; load: Load<LigandCandidatePage> } | null>(null);
  const [job, setJob] = useState<DockingJob | null>(null);
  const [jobFocus, setJobFocus] = useState(false);
  const [approvalPending, setApprovalPending] = useState(false);
  const [busy, setBusy] = useState(false);
  // Cancel has its own flag: the start request is held until the job ends, so `busy` must not block cancelling.
  const [cancelling, setCancelling] = useState(false);
  const [jobError, setJobError] = useState("");
  /** Receptor leftover list of the last refused submission (422 detail), shown with `jobError`. */
  const [refusal, setRefusal] = useState<DockingRefusalList | null>(null);
  const [notice, setNotice] = useState("");
  const [resultNotice, setResultNotice] = useState<{ text: string; handle: string | null } | null>(null);
  const [budget, setBudget] = useState<BudgetSnapshot | null>(null);
  const [budgetReload, setBudgetReload] = useState(0);
  const [results, setResults] = useState<Load<DockingResultList>>({ status: "idle" });
  const [resultsReload, setResultsReload] = useState(0);
  const [selectedResult, setSelectedResult] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ handle: string; load: Load<DockingResultDetail> } | null>(null);
  const [selectedMode, setSelectedMode] = useState<number | null>(null);
  const [contactOffset, setContactOffset] = useState(0);
  const [contacts, setContacts] = useState<{ key: string; load: Load<DockingContactPage> } | null>(null);
  const [contactsRetry, setContactsRetry] = useState(0);
  const [report, setReport] = useState<{ handle: string; load: Load<DockingReportArtifact> } | null>(null);

  // Late responses: keyed by run (page key), the area's selection key and the area's request sequence.
  const mounted = useRef(true);
  const seqs = useRef<Record<Area, number>>({ prereq: 0, imports: 0, instances: 0, candidates: 0, job: 0, cancel: 0,
    budget: 0, results: 0, detail: 0, contacts: 0, report: 0 });
  const live = useRef({ receptor: form.receptorHandle, set: form.candidateSetHandle, result: selectedResult });
  live.current = { receptor: form.receptorHandle, set: form.candidateSetHandle, result: selectedResult };
  useEffect(() => {
    mounted.current = true;
    const counters = seqs.current;
    return () => { mounted.current = false; for (const area of Object.keys(counters) as Area[]) counters[area] += 1; };
  }, []);
  const keyOf = (area: Area): string | null => area === "instances" ? live.current.receptor
    : area === "candidates" ? live.current.set
      : area === "detail" || area === "contacts" || area === "report" ? live.current.result : null;
  const stamp = (area: Area): DockingStamp => ({ runId, key: keyOf(area), seq: ++seqs.current[area] });
  const current = (area: Area, captured: DockingStamp) => mounted.current &&
    dockingResponseCurrent(captured, { runId, key: keyOf(area), seq: seqs.current[area] });
  const update = (patch: Partial<DockingForm>) => setForm(previous => {
    const next = patchDockingForm(previous, patch);
    // Same rule for the refs read by the late-response check (before the next render).
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
  // stamp/current read live refs; the read is keyed by run and its reload counter.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, prereqReload]);

  useEffect(() => {
    const captured = stamp("results"), controller = new AbortController();
    setResults({ status: "loading" });
    allResults(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(value => {
      if (current("results", captured)) setResults({ status: "ready", value });
    }).catch(e => { if (current("results", captured) && !controller.signal.aborted)
      setResults({ status: "error", message: `도킹 결과 목록 읽기 실패: ${errorText(e)}` }); });
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, resultsReload]);

  useEffect(() => {
    const captured = stamp("budget");
    api.budget(runId).then(value => { if (current("budget", captured)) setBudget(value); }).catch(() => undefined);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, budgetReload]);

  // After a remount the durable job list tells whether this area's job is still queued or running.
  useEffect(() => {
    const captured = stamp("job"), controller = new AbortController();
    api.dockingJobs(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(list => {
      if (!current("job", captured)) return;
      const running = dockingActiveJob<DockingJob>(list, runId);
      if (running) { setJob(previous => previous ?? running); setJobFocus(true); }
    }).catch(() => undefined);
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // Polling reads only, while this area's job is queued, claimed or running.
  useEffect(() => {
    if (!job || !dockingJobActive(job)) return;
    let active = true;
    const jobId = job.job_id;
    const timer = window.setInterval(() => {
      void api.dockingJob(runId, jobId).then(value => {
        if (active && mounted.current && value.run_id === runId && value.job_id === jobId)
          setJob(previous => previous?.job_id === jobId ? value : previous);
      }).catch(() => undefined);
    }, 1000);
    return () => { active = false; window.clearInterval(timer); };
  // Restarted only when the job id or status changes (each poll answer is a new object).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, job?.job_id, job?.status]);

  // A finished job refreshes the result list; its result is never opened automatically (the user picks it).
  useEffect(() => {
    if (!job) return;
    setNotice(previous => ligandNoticeAfterJob(previous, job.status));
    if (job.status === "done") {
      const handle = job.artifacts.docking_result ?? null;
      setResultsReload(value => value + 1);
      setResultNotice({ text: `도킹 결과가 저장되었습니다${handle ? ` (${shortHandle(handle)})` : ""}. 아래 도킹 결과 목록에서 직접 고르세요.`, handle });
    }
    if (!dockingJobActive(job)) setBudgetReload(value => value + 1);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.job_id, job?.status]);

  // Receptor instance listing (selection aid; the server checks the choice again), keyed by the chosen receptor.
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

  // Candidate rows of the chosen set (M17 rows read, generation order, no filter).
  const candidateSet = form.ligandSource === "candidate" ? form.candidateSetHandle : null;
  const candidatesKey = candidateSet ? candidateRowsQuery(candidateSet, emptyAppliedFilter(), { sort: "generation_order",
    direction: "asc", offset: candidateOffset, limit: CANDIDATE_PAGE_LIMIT, passesOnly: false }) : null;
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

  // Contact rows of the chosen mode (page read).
  const contactsKey = selectedResult && selectedMode !== null ? JSON.stringify([selectedResult, selectedMode, contactOffset]) : null;
  useEffect(() => {
    if (!selectedResult || selectedMode === null || contactsKey === null) return;
    const key = contactsKey, handle = selectedResult, mode = selectedMode, captured = stamp("contacts");
    const controller = new AbortController();
    setContacts({ key, load: { status: "loading" } });
    api.dockingContacts(runId, handle, mode, contactOffset, CONTACT_PAGE_LIMIT,
      AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(value => {
      if (!current("contacts", captured)) return;
      if (value.schema !== "docking_contact_page@1" || value.handle !== handle || value.mode !== mode)
        throw new Error("접촉 행이 고른 결과·모드와 다릅니다.");
      setContacts({ key, load: { status: "ready", value } });
    }).catch(e => { if (current("contacts", captured) && !controller.signal.aborted)
      setContacts({ key, load: { status: "error", message: `접촉 행 읽기 실패: ${errorText(e)}` } }); });
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contactsKey, contactsRetry]);
  const contactLoad = contacts && contacts.key === contactsKey ? contacts.load : null;

  function openResult(handle: string) {
    setSelectedResult(handle); live.current = { ...live.current, result: handle };
    setSelectedMode(null); setContactOffset(0); setContacts(null); setReport(null); setJobFocus(false);
    const captured = stamp("detail");
    setDetail({ handle, load: { status: "loading" } });
    api.dockingResult(runId, handle, AbortSignal.timeout(30000)).then(value => {
      if (!current("detail", captured)) return;
      if (value.schema !== "docking_result_detail@1" || value.handle !== handle) throw new Error("도킹 결과가 고른 handle과 다릅니다.");
      setDetail({ handle, load: { status: "ready", value } });
    }).catch(e => { if (current("detail", captured))
      setDetail({ handle, load: { status: "error", message: `도킹 결과 읽기 실패: ${errorText(e)}` } }); });
  }
  const opened = detail && detail.handle === selectedResult && detail.load.status === "ready" ? detail.load.value : null;

  // A batch row's "상세 열기": the same detail read as choosing the result here; the list is re-read so it shows.
  // A request made before this mount (e.g. before the tab was left) is not replayed: nothing opens by itself.
  const seenOpen = useRef(openRequest?.seq ?? 0);
  useEffect(() => {
    if (!openRequest || openRequest.seq === seenOpen.current || openRequest.runId !== runId) return;
    seenOpen.current = openRequest.seq;
    openResult(openRequest.handle);
    setResultsReload(value => value + 1);
    document.querySelector('[data-testid="docking-panel"] [data-docking-area="results"]')?.scrollIntoView({ block: "start" });
  // Each click is a new seq; openResult reads live refs.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openRequest?.seq]);

  // ---- imports and jobs ----
  const chosenFiles = SLOTS.filter(slot => files[slot]);
  async function importFiles() {
    if (!chosenFiles.length || importState.status === "loading") return;
    const captured = stamp("imports"), done: string[] = [];
    setImportState({ status: "loading" });
    try {
      for (const slot of chosenFiles) {
        const value = await api.chemicalImport(runId, SLOT_KIND[slot], files[slot]!, AbortSignal.timeout(60000));
        if (!current("imports", captured)) return;
        if (value.kind !== SLOT_KIND[slot] || value.schema !== "chemical_raw_input@1") throw new Error("가져오기 응답의 종류가 다릅니다.");
        done.push(value.handle);
        setFiles(previous => ({ ...previous, [slot]: null }));
      }
      setImportState({ status: "ready", value: done });
    } catch (e) { if (current("imports", captured)) setImportState({ status: "error", message: `가져오기 실패: ${errorText(e)}` }); }
    finally { if (mounted.current && done.length) setPrereqReload(value => value + 1); }
  }

  function chooseFile(slot: Slot, file: File | null) {
    seqs.current.imports += 1;
    setFiles(previous => ({ ...previous, [slot]: file }));
    setImportState({ status: "idle" });
  }

  const check = dockingArgs(form);
  const submitBlocked = dockingSubmitBlockedReason({ capability, busy, activeJob: job, check });

  async function start(before: DockingJob) {
    const captured = stamp("job");
    setBusy(true); setJobError(""); setRefusal(null); setNotice(""); setJobFocus(true);
    try {
      const value = await api.startJob(runId, before.job_id) as unknown as DockingJob;
      if (!current("job", captured)) return;
      if (value.run_id !== runId || value.job_id !== before.job_id) throw new Error("시작 응답이 이 작업과 다릅니다.");
      setApprovalPending(false); setJob(value);
    } catch (e) {
      if (!current("job", captured)) return;
      if (e instanceof ApiError && dockingApprovalRequired(e.status, e.approval)) {
        setApprovalPending(true); setBudgetReload(value => value + 1);
        return;
      }
      // The start may have taken effect although its response was lost: the stored job decides.
      const stored = await api.dockingJob(runId, before.job_id).catch(() => null);
      if (!current("job", captured)) return;
      if (stored && stored.run_id === runId && stored.job_id === before.job_id) setJob(stored);
      if (!stored || !ligandStartProgressed(before, stored)) setJobError(`작업 시작 실패: ${errorText(e)}`);
    } finally { if (mounted.current) setBusy(false); }
  }

  async function submit() {
    if (submitBlocked || !check.ok) return;
    const captured = stamp("job");
    setBusy(true); setJobError(""); setRefusal(null); setNotice(""); setResultNotice(null); setApprovalPending(false);
    setJobFocus(true);
    try {
      const result = await api.submitDocking(runId, check.args);
      if (!current("job", captured)) return;
      if ("plan_only" in result) { setNotice(dockingSubmitText(result)); return; }
      if (result.run_id !== runId || result.protocol_id !== "qvina_dock_v1") throw new Error("제출 응답이 요청과 다릅니다.");
      setJob(result);
      if (result.status !== "queued") { setNotice(dockingSubmitText(result)); return; }
      await start(result);
    } catch (e) {
      if (!current("job", captured)) return;
      setJobError(`작업 제출 실패: ${errorText(e)}`);
      setRefusal(e instanceof ApiError ? dockingRequestRefusalList(e) : null);
    }
    finally { if (mounted.current) setBusy(false); }
  }

  async function approve() {
    if (!job) return;
    const captured = stamp("job");
    setBusy(true); setJobError(""); setRefusal(null);
    try {
      await api.approveOpenmm(runId);
      if (!current("job", captured)) return;
      setApprovalPending(false); setBudgetReload(value => value + 1);
      setNotice(LIGAND_APPROVAL_NOTICE);
    } catch (e) { if (current("job", captured)) setJobError(`승인 실패: ${errorText(e)}`); }
    finally { if (mounted.current) setBusy(false); }
  }

  async function retryJob() {
    if (!job) return;
    const captured = stamp("job"), jobId = job.job_id;
    setBusy(true); setJobError(""); setRefusal(null);
    try {
      const value = await api.retryJob(runId, jobId) as unknown as DockingJob;
      if (current("job", captured) && value.run_id === runId && value.job_id === jobId) setJob(value);
    } catch (e) { if (current("job", captured)) setJobError(`작업 재시도 실패: ${errorText(e)}`); }
    finally { if (mounted.current) setBusy(false); }
  }

  // Not tied to the "job" sequence or `busy`: a held start request stays current and keeps its own answer.
  async function cancelJob() {
    if (!job || !dockingCancelEnabled({ job, cancelling })) return;
    const captured = stamp("cancel"), jobId = job.job_id;
    setCancelling(true);
    try {
      const value = (await api.cancelJob(runId, jobId)).job as unknown as DockingJob;
      if (current("cancel", captured) && value.run_id === runId && value.job_id === jobId)
        setJob(previous => previous?.job_id === jobId ? value : previous);
    } catch (e) { if (current("cancel", captured)) setJobError(`작업 취소 실패: ${errorText(e)}`); }
    finally { if (mounted.current) setCancelling(false); }
  }

  async function makeReport() {
    if (!opened || !selectedResult || report?.load.status === "loading") return;
    const handle = selectedResult, captured = stamp("report");
    setReport({ handle, load: { status: "loading" } });
    try {
      const artifact = await api.createDockingReport(runId, handle, AbortSignal.timeout(60000));
      if (!current("report", captured)) return;
      if (!dockingReportMatches(artifact, handle)) throw new Error("보고서가 고른 도킹 결과와 다릅니다.");
      setReport({ handle, load: { status: "ready", value: artifact } });
      onReportCreated(runId);
    } catch (e) { if (current("report", captured)) setReport({ handle, load: { status: "error", message: `보고서 만들기 실패: ${errorText(e)}` } }); }
  }

  // ---- panel state ----
  const instancesError = instances?.handle === receptorHandle && instances?.load.status === "error" ? instances.load.message : null;
  const readError = (detail?.handle === selectedResult && detail?.load.status === "error" ? detail.load.message : null)
    ?? (contactLoad?.status === "error" ? contactLoad.message : null) ?? instancesError
    ?? (prereq.status === "error" ? prereq.message : null) ?? (results.status === "error" ? results.message : null)
    ?? (jobError || null);
  const panelState = dockingPanelState({ runId, capability,
    loading: prereq.status === "loading" || results.status === "loading" || detail?.load.status === "loading" ||
      contactLoad?.status === "loading",
    error: readError, job: jobFocus ? job : null,
    result: opened ? { modes: opened.result.counts.modes, mode: opened.result.inputs.mode } : null });
  const phase = dockingJobPhase(job, approvalPending);
  const jobRefusal = dockingJobRefusalList(job);
  const prereqValue = prereq.status === "ready" ? prereq.value : null;
  const receptors = prereqValue ? importsOfKind(prereqValue.imports, "receptor") : [];
  const sidecars = prereqValue ? importsOfKind(prereqValue.imports, "receptor_bonds") : [];
  const ligandSdfs = prereqValue ? importsOfKind(prereqValue.imports, "ligand_sdf") : [];
  const sets = prereqValue?.candidate_sets ?? [];
  const chosenSet = sets.find(set => set.handle === form.candidateSetHandle) ?? null;
  const parentReason = parentSdfMissingReason(chosenSet);
  const modelList = listing ? modelInstances(listing, form.receptorModelNumber) : [];
  const waterCount = listing?.models.find(model => model.model_number === form.receptorModelNumber)?.water_residue_count ?? null;

  return <section className="mw-ligand mw-docking" aria-label="리간드 도킹" data-testid="docking-panel" data-docking-state={panelState.state}>
    <div className="mw-ligand-head">
      <h2 className="mw-ligand-heading">리간드 도킹 (qvina)</h2>
      <span className="mw-badge" data-testid="docking-state">{DOCKING_STATE_TEXT[panelState.state]}</span>
    </div>
    {panelState.state === "failure" && <p role="alert" className="mw-ligand-error" data-testid="docking-failure">{panelState.message}</p>}
    {panelState.state === "scientific_null" && <p role="status" className="mw-ligand-null" data-testid="docking-null-result">{panelState.message}</p>}
    <p className="mw-ligand-note">점수는 {SCORE_LABEL}입니다. 화면은 저장된 결과 값을 표시만 하며 점수·접촉을 다시 계산하지 않습니다.</p>
    {run.dry_run && <p role="status" className="mw-ligand-unavailable" data-testid="docking-dry-run">
      dry-run run: 도킹 작업을 제출하면 계획만 만들며 실제 계산과 결과 객체가 없습니다.</p>}
    <p className="mw-ligand-note mw-mono" data-testid="docking-capability">
      {capability.engine} · {capability.tool_id} · 작업마다 비싼 계산 예산 1단위
      {budget ? <span data-testid="docking-budget" data-used={budget.expensive_calls.used} data-limit={budget.expensive_calls.limit}>
        {` · 비싼 계산 ${budget.expensive_calls.used}/${budget.expensive_calls.limit}`}</span> : null}</p>

    <Section area="imports" title="가져오기" state={importState.status}>
      <div className="mw-ligand-form">
        {SLOTS.map(slot => <label key={slot} className="mw-ligand-field">
          <span>{SLOT_LABEL[slot]}</span>
          <input type="file" accept={SLOT_ACCEPT[slot]} data-testid={`docking-file-${slot}`} disabled={importState.status === "loading"}
            onChange={event => chooseFile(slot, event.target.files?.[0] ?? null)} />
        </label>)}
        <div className="mw-ligand-inline">
          <Button size="sm" data-testid="docking-import" disabled={!chosenFiles.length || importState.status === "loading"}
            onClick={() => void importFiles()}>가져오기</Button>
          {importState.status === "loading" && <span className="mw-ligand-note" aria-busy="true">가져오는 중</span>}
          {importState.status === "ready" && <span className="mw-ligand-note" role="status" data-testid="docking-import-done">
            가져온 파일은 아래 목록에서 직접 고르세요(자동으로 고르지 않음).</span>}
        </div>
        {importState.status === "error" && <ErrorLine message={importState.message} testId="docking-import-error" />}
        {/* Candidate sets and parent SDFs made in the candidate area above appear here only after a re-read. */}
        {prereq.status !== "loading" && <div className="mw-ligand-inline">
          <Button size="sm" data-testid="docking-prereq-refresh" onClick={() => setPrereqReload(value => value + 1)}>
            입력 목록 다시 읽기</Button>
          <span className="mw-ligand-note">위 후보 영역에서 만든 후보 집합·가져온 부모 SDF는 다시 읽어야 보입니다.</span></div>}
        {prereq.status === "loading" && <p className="mw-ligand-note" aria-busy="true">입력 준비 목록을 읽는 중</p>}
        {prereq.status === "error" && <ErrorLine message={prereq.message} onRetry={() => setPrereqReload(value => value + 1)} />}
      </div>
    </Section>

    <Section area="receptor" title="① 수용체">
      <label className="mw-ligand-check">수용체 가져오기
        <select className="mw-select" data-testid="docking-receptor" value={form.receptorHandle ?? ""}
          onChange={event => update({ receptorHandle: event.target.value || null })}>
          <option value="">선택</option>
          {receptors.map(row => <option key={row.handle} value={row.handle}>
            {`생성 순번 ${row.created_seq} · ${row.input_format ?? ""} · ${row.size} B · ${shortHandle(row.handle)}`}</option>)}
        </select></label>
      {prereqValue && !receptors.length && <p className="mw-ligand-note">가져온 수용체가 없습니다.</p>}
      {instances?.handle === receptorHandle && instances?.load.status === "loading" &&
        <p className="mw-ligand-note" aria-busy="true">수용체 인스턴스 목록을 읽는 중</p>}
      {instancesError && <ErrorLine message={instancesError} testId="docking-instances-error" />}
      {listing && <>
        <label className="mw-ligand-check">모델 (암묵적으로 첫 모델을 쓰지 않음)
          <select className="mw-select" data-testid="docking-model" value={form.receptorModelNumber ?? ""}
            onChange={event => update({ receptorModelNumber: event.target.value === "" ? null : Number(event.target.value) })}>
            <option value="">선택</option>
            {listing.model_numbers.map(number => <option key={number} value={number}>{`모델 ${number}`}</option>)}
          </select></label>
        {form.receptorModelNumber !== null && <fieldset className="mw-ligand-choices" data-testid="docking-instances">
          <legend>수용체에서 뺄 리간드 인스턴스 (하나만, 자동으로 고르지 않음)</legend>
          <label data-docking-instance="none">
            <input type="radio" name={`docking-instance-${runId}`} checked={form.instance.kind === "none"}
              onChange={() => update({ instance: { kind: "none" } })} />
            <span>없음(단백질만)</span></label>
          {modelList.map(item => <label key={JSON.stringify(exactResidue(item.residue))}
            data-docking-instance={JSON.stringify(exactResidue(item.residue))}>
            <input type="radio" name={`docking-instance-${runId}`}
              checked={form.instance.kind === "instance" && sameResidue(form.instance.residue, item.residue)}
              onChange={() => update({ instance: { kind: "instance", residue: exactResidue(item.residue) } })} />
            <span className="mw-mono">{removedInstanceText(item)}</span></label>)}
          {!modelList.length && <p className="mw-ligand-note">이 모델에는 물 밖의 비표준 잔기 인스턴스가 없습니다.</p>}
          {waterCount !== null && <p className="mw-ligand-note">물 잔기 {waterCount}개 (목록에서 제외, 개수만 표시. 남아 있으면 작업이 거부합니다)</p>}
        </fieldset>}
      </>}
      <fieldset className="mw-ligand-choices" data-testid="docking-connectivity">
        <legend>연결 정보</legend>
        <label><input type="radio" name={`docking-connectivity-${runId}`} checked={form.connectivity === "pdb_conect"}
          onChange={() => update({ connectivity: "pdb_conect" })} /> PDB CONECT (파일 안의 완전한 연결 정보)</label>
        <label><input type="radio" name={`docking-connectivity-${runId}`} checked={form.connectivity === "sidecar"}
          onChange={() => update({ connectivity: "sidecar" })} /> 결합 사이드카 (receptor_bonds@1)</label>
        {form.connectivity === "sidecar" && <label className="mw-ligand-check">사이드카 가져오기
          <select className="mw-select" data-testid="docking-sidecar" value={form.sidecarHandle ?? ""}
            onChange={event => update({ sidecarHandle: event.target.value || null })}>
            <option value="">선택</option>
            {sidecars.map(row => <option key={row.handle} value={row.handle}>
              {`생성 순번 ${row.created_seq} · ${row.size} B · ${shortHandle(row.handle)}`}</option>)}
          </select></label>}
      </fieldset>
    </Section>

    <Section area="ligand" title="② 리간드 출처">
      <fieldset className="mw-ligand-choices" data-testid="docking-ligand-source">
        <legend>출처 (한 번에 하나)</legend>
        {LIGAND_SOURCES.map(source => <label key={source} data-docking-source={source}>
          <input type="radio" name={`docking-source-${runId}`} checked={form.ligandSource === source}
            onChange={() => update({ ligandSource: source })} /> {SOURCE_LABEL[source]}</label>)}
      </fieldset>
      {form.ligandSource === "sdf" && <label className="mw-ligand-check">리간드 SDF 가져오기
        <select className="mw-select" data-testid="docking-sdf" value={form.sdfHandle ?? ""}
          onChange={event => update({ sdfHandle: event.target.value || null })}>
          <option value="">선택</option>
          {ligandSdfs.map(row => <option key={row.handle} value={row.handle}>
            {`생성 순번 ${row.created_seq} · ${row.size} B · ${shortHandle(row.handle)}`}</option>)}
        </select></label>}
      {form.ligandSource === "candidate" && <>
        <p className="mw-ligand-note">후보는 2D 그래프입니다. 도킹 입력의 3D 좌표와 수소는 작업에서 RDKit이 만들며 결과에 "생성됨"으로 표시됩니다.</p>
        <ul className="mw-ligand-list" data-testid="docking-candidate-notes" aria-label="후보 출처 안내 (제출 전)">
          {CANDIDATE_SOURCE_NOTES.map(sentence => <li key={sentence}>{sentence}</li>)}</ul>
        <label className="mw-ligand-check">후보 집합
          <select className="mw-select" data-testid="docking-candidate-set" value={form.candidateSetHandle ?? ""}
            onChange={event => { setCandidateOffset(0); update({ candidateSetHandle: event.target.value || null }); }}>
            <option value="">선택</option>
            {sets.map(set => <option key={set.handle} value={set.handle} disabled={!set.valid}>
              {set.valid ? `${shortHandle(set.handle)} · 후보 ${set.candidates}개` : `${shortHandle(set.handle)} · 읽을 수 없음`}</option>)}
          </select></label>
        {prereqValue && !sets.length && <p className="mw-ligand-note">이 run에 후보 집합이 없습니다(위 후보 영역에서 만듭니다).</p>}
        {candidateLoad?.status === "loading" && <p className="mw-ligand-note" aria-busy="true">후보 행을 읽는 중</p>}
        {candidateLoad?.status === "error" && <ErrorLine message={candidateLoad.message} testId="docking-candidates-error" />}
        {candidateLoad?.status === "ready" && <CandidateChoices page={candidateLoad.value} runId={runId}
          chosen={form.candidateId} onChoose={id => update({ candidateId: id })} onPage={setCandidateOffset} />}
        {chosenSet && <>
          {parentReason ? <p className="mw-ligand-unavailable" data-testid="docking-parent-missing">{parentReason}</p>
            : <label className="mw-ligand-check">부모 3D SDF 가져오기 (SHA-256이 후보 집합의 부모와 같은 것만)
              <select className="mw-select" data-testid="docking-parent-sdf" value={form.parentSdfHandle ?? ""}
                onChange={event => update({ parentSdfHandle: event.target.value || null })}>
                <option value="">선택</option>
                {chosenSet.parent_sdf_handles!.map(handle => <option key={handle} value={handle}>{shortHandle(handle)}</option>)}
              </select></label>}
        </>}
      </>}
    </Section>

    <Section area="mode" title="③ 방식">
      <fieldset className="mw-ligand-choices" data-testid="docking-mode">
        <legend>방식</legend>
        {MODES.map(mode => {
          const reason = modeDisabledReason(form.ligandSource, mode);
          return <label key={mode} data-docking-mode={mode} data-disabled-reason={reason ?? undefined}>
            <input type="radio" name={`docking-mode-${runId}`} checked={form.mode === mode} disabled={!!reason}
              onChange={() => update({ mode })} /> {MODE_LABEL[mode]}
            {reason && <span className="mw-ligand-note">{reason}</span>}</label>;
        })}
      </fieldset>
    </Section>

    <Section area="box" title="④ 상자">
      <p className="mw-ligand-note" data-testid="docking-frame-note">{BOX_FRAME_NOTE}</p>
      <fieldset className="mw-ligand-choices" data-testid="docking-box-source">
        <legend>상자 출처 (자동으로 고르지 않음)</legend>
        {BOX_SOURCES.map((source: DockingBoxSource) => {
          const reason = boxSourceDisabledReason(source, form.instance);
          return <label key={source} data-docking-box={source} data-disabled-reason={reason ?? undefined}>
            <input type="radio" name={`docking-box-${runId}`} checked={form.boxSource === source} disabled={!!reason}
              onChange={() => update({ boxSource: source })} /> {boxSourceLabel(source)}
            {reason && <span className="mw-ligand-note">{reason}</span>}</label>;
        })}
      </fieldset>
      {(form.boxSource === "ligand_range" || form.boxSource === "instance_range") && <label className="mw-ligand-check">
        여백 (Å, {MARGIN_MIN_A}–{MARGIN_MAX_A})
        <input className="mw-ligand-input" data-testid="docking-margin" inputMode="decimal" value={form.margin}
          onChange={event => update({ margin: event.target.value })} /></label>}
      {form.boxSource === "manual" && <div className="mw-docking-grid" data-testid="docking-manual-box">
        {AXES.map((axis, i) => <label key={`c${axis}`} className="mw-ligand-check">중심 {axis} (Å)
          <input className="mw-ligand-input" data-testid={`docking-center-${axis}`} inputMode="decimal" value={form.center[i]}
            onChange={event => update({ center: form.center.map((value, j) => j === i ? event.target.value : value) as DockingForm["center"] })} />
        </label>)}
        {AXES.map((axis, i) => <label key={`s${axis}`} className="mw-ligand-check">크기 {axis} (Å, {BOX_SIDE_MIN_A}–{BOX_SIDE_MAX_A})
          <input className="mw-ligand-input" data-testid={`docking-size-${axis}`} inputMode="decimal" value={form.size[i]}
            onChange={event => update({ size: form.size.map((value, j) => j === i ? event.target.value : value) as DockingForm["size"] })} />
        </label>)}
      </div>}
    </Section>

    <Section area="values" title="⑤ 값과 확인">
      <div className="mw-docking-grid">
        <label className="mw-ligand-check">seed (필수, {SEED_MIN}–{SEED_MAX})
          <input className="mw-ligand-input" data-testid="docking-seed" inputMode="numeric" value={form.seed}
            onChange={event => update({ seed: event.target.value })} /></label>
        <label className="mw-ligand-check">exhaustiveness ({EXHAUSTIVENESS_MIN}–{EXHAUSTIVENESS_MAX})
          <input className="mw-ligand-input" data-testid="docking-exhaustiveness" inputMode="numeric" value={form.exhaustiveness}
            onChange={event => update({ exhaustiveness: event.target.value })} /></label>
        <label className="mw-ligand-check">num_modes ({NUM_MODES_MIN}–{NUM_MODES_MAX})
          <input className="mw-ligand-input" data-testid="docking-num-modes" inputMode="numeric" value={form.numModes}
            onChange={event => update({ numModes: event.target.value })} /></label>
        <label className="mw-ligand-check">energy_range (kcal/mol, {ENERGY_RANGE_MIN}–{ENERGY_RANGE_MAX})
          <input className="mw-ligand-input" data-testid="docking-energy-range" inputMode="decimal" value={form.energyRange}
            onChange={event => update({ energyRange: event.target.value })} /></label>
        {form.mode === "core_fixed" && <label className="mw-ligand-check">conformers ({CONFORMERS_MIN}–{CONFORMERS_MAX}, 코어 고정만)
          <input className="mw-ligand-input" data-testid="docking-conformers" inputMode="numeric" value={form.conformers}
            onChange={event => update({ conformers: event.target.value })} /></label>}
      </div>
      <p className="mw-ligand-note">cpu는 1로 고정됩니다.</p>
      <fieldset className="mw-ligand-choices" data-testid="docking-acknowledgement">
        <legend>제출 전 확인 (세 항목 모두)</legend>
        {ACKNOWLEDGEMENT_KEYS.map((key: DockingAcknowledgementKey) => <label key={key} data-docking-ack={key}>
          <input type="checkbox" checked={form.acknowledgement[key]}
            onChange={event => update({ acknowledgement: { ...form.acknowledgement, [key]: event.target.checked } })} />
          {ACKNOWLEDGEMENT_LABEL[key]}</label>)}
      </fieldset>
      {!check.ok && <ul className="mw-ligand-errors" data-testid="docking-input-errors">
        {check.errors.map(error => <li key={error}>{error}</li>)}</ul>}
    </Section>

    <Section area="start" title="⑥ 작업 시작">
      <div className="mw-ligand-inline">
        <Button size="sm" variant="primary" data-testid="docking-start" disabled={!!submitBlocked}
          title={submitBlocked ?? undefined} onClick={() => void submit()}>도킹 작업 시작</Button>
        {submitBlocked && <span className="mw-ligand-note" data-testid="docking-start-blocked">{submitBlocked}</span>}
      </div>
      {(job || notice || resultNotice || jobError) && <div className="mw-ligand-job" data-testid="docking-job-area">
        {job && <div className="mw-ligand-job" data-testid="docking-job" data-docking-job-phase={phase}
          data-docking-job-status={job.status} data-docking-job-id={job.job_id}>
          <p className="mw-ligand-note" role="status">{dockingJobText(job, approvalPending)}</p>
          <p className="mw-ligand-note mw-mono">{DOCKING_TOOL} · 작업 {job.status} · 시도 {job.attempt_ordinal} · {job.job_id}</p>
          {job.blocked_reason && <p className="mw-ligand-note">시작 대기 이유: {dockingReasonText(job.blocked_reason)}</p>}
          <div className="mw-ligand-inline">
            {phase === "awaiting_approval" && <Button size="sm" data-testid="docking-job-approve" disabled={busy}
              onClick={() => void approve()}>비싼 계산 승인</Button>}
            {phase === "saved" && <Button size="sm" data-testid="docking-job-start" disabled={busy || run.dry_run}
              onClick={() => void start(job)}>작업 시작</Button>}
            {dockingJobActive(job) && <Button size="sm" data-testid="docking-job-cancel"
              disabled={!dockingCancelEnabled({ job, cancelling })} onClick={() => void cancelJob()}>작업 취소</Button>}
            {["failed", "interrupted"].includes(job.status) && job.attempt_ordinal < 4 && <Button size="sm"
              data-testid="docking-job-retry" disabled={busy} onClick={() => void retryJob()}>작업 재시도</Button>}
          </div>
          {jobRefusal && <RefusalList list={jobRefusal} source="job" />}
        </div>}
        {notice && <p role="status" className="mw-ligand-note" data-testid="docking-notice">{notice}</p>}
        {resultNotice && <p role="status" className="mw-ligand-note" data-testid="docking-result-notice"
          data-docking-new-result={resultNotice.handle ?? undefined}>{resultNotice.text}</p>}
        {jobError && <ErrorLine message={jobError} testId="docking-job-error" />}
        {jobError && refusal && <RefusalList list={refusal} source="admission" />}
      </div>}
    </Section>

    <Section area="results" title="⑦ 도킹 결과" state={results.status}>
      {results.status === "loading" && <p className="mw-ligand-note" aria-busy="true">도킹 결과 목록을 읽는 중</p>}
      {results.status === "error" && <ErrorLine message={results.message} onRetry={() => setResultsReload(value => value + 1)} />}
      {results.status === "ready" && (!results.value.rows.length ? <p className="mw-ligand-note">이 run에 도킹 결과가 없습니다.</p>
        : <fieldset className="mw-ligand-choices" data-testid="docking-results">
          <legend>도킹 결과 선택 (자동으로 고르지 않음)</legend>
          {results.value.rows.map(row => <label key={row.handle} data-docking-result={row.handle} data-valid={row.valid}
            data-null-result={row.null_result ?? undefined}>
            <input type="radio" name={`docking-result-${runId}`} checked={selectedResult === row.handle} disabled={!row.valid}
              onChange={() => openResult(row.handle)} />
            <span className="mw-mono">{shortHandle(row.handle)} · {dockingResultRowText(row)}</span>
            {row.structure_origin && <span className="mw-catalytic-mark" data-testid="docking-result-repaired"
              data-repair-record={row.structure_origin.repair_record}><span className="mw-catalytic-badge">보완 구조</span></span>}
          </label>)}
        </fieldset>)}
      {results.status !== "loading" && <Button size="sm" data-testid="docking-results-refresh"
        onClick={() => setResultsReload(value => value + 1)}>도킹 결과 목록 다시 읽기</Button>}
      {detail?.handle === selectedResult && detail.load.status === "loading" && <p className="mw-ligand-note" aria-busy="true">도킹 결과를 읽는 중</p>}
      {detail?.handle === selectedResult && detail.load.status === "error" &&
        <ErrorLine message={detail.load.message} onRetry={() => selectedResult && openResult(selectedResult)} />}
      {opened && <RepairOriginNote origin={opened.structure_origin} testId="docking-repair-origin"
        onOpenRecord={onOpenRepairRecord ? record => onOpenRepairRecord(runId, record) : undefined} />}
      {opened && <ResultView detail={opened} runId={runId} selectedMode={selectedMode}
        onMode={mode => { setSelectedMode(mode); setContactOffset(0); }} />}
      {opened && selectedMode !== null && <div className="mw-docking-contacts" data-testid="docking-contacts" data-mode={selectedMode}>
        <span className="mw-eyebrow">{`접촉 표 · ${modeRowLabel(opened.result.inputs.mode, selectedMode)}`}</span>
        <p className="mw-ligand-note">{CONTACT_NOTE}</p>
        {contactLoad?.status === "loading" && <p className="mw-ligand-note" aria-busy="true">접촉 행을 읽는 중</p>}
        {contactLoad?.status === "error" && <ErrorLine message={contactLoad.message} onRetry={() => setContactsRetry(value => value + 1)}
          testId="docking-contacts-error" />}
        {contactLoad?.status === "ready" && <ContactTable page={contactLoad.value} onPage={setContactOffset} />}
      </div>}
      {opened && <>
        <div className="mw-ligand-inline" aria-label="도킹 보고서">
          <Button size="sm" data-testid="docking-report" disabled={report?.handle === selectedResult && report.load.status === "loading"}
            onClick={() => void makeReport()}>보고서 만들기</Button>
        </div>
        {report?.handle === selectedResult && report.load.status === "loading" && <p className="mw-ligand-note" aria-busy="true">보고서를 만드는 중</p>}
        {report?.handle === selectedResult && report.load.status === "ready" && <p role="status" className="mw-ligand-note"
          data-testid="docking-report-done" data-report-handle={report.load.value.handle}>
          보고서를 저장했습니다 · {shortHandle(report.load.value.handle)}. 지식·보고서 탭의 보고서 목록에서 열고 받을 수 있습니다.</p>}
        {report?.handle === selectedResult && report.load.status === "error" && <ErrorLine message={report.load.message} testId="docking-report-error" />}
      </>}
    </Section>
  </section>;
}

/** Listed receptor leftovers of a refusal (spec 3.2): seven residue fields (nulls kept), atom names, altloc. */
export function RefusalList({ list, source }: { list: DockingRefusalList; source: "admission" | "job" }) {
  return <div className="mw-ligand-error" data-testid="docking-refusal-list" data-docking-refusal-source={source}
    data-reason-code={list.reason_code} data-total={list.total ?? undefined} data-shown={list.shown}>
    <span>{list.heading} · {dockingReasonText(list.reason_code)}</span>
    <ul className="mw-ligand-list mw-mono">{list.lines.map((line, i) => <li key={i} data-refusal-item={i}>{line}</li>)}</ul>
  </div>;
}

function CandidateChoices({ page, runId, chosen, onChoose, onPage }: { page: LigandCandidatePage; runId: string;
  chosen: string | null; onChoose: (id: string) => void; onPage: (offset: number) => void }) {
  const last = page.offset + page.rows.length;
  return <fieldset className="mw-ligand-choices" data-testid="docking-candidates">
    <legend>후보 선택 (자동으로 고르지 않음) · 전체 {page.total}개 중 {page.rows.length ? `${page.offset + 1}–${last}` : "0"}</legend>
    {page.rows.map(row => <label key={row.candidate.id} data-docking-candidate={row.candidate.id}
      data-stereo-flag={row.candidate.stereo_flag}>
      <input type="radio" name={`docking-candidate-${runId}`} checked={chosen === row.candidate.id}
        onChange={() => onChoose(row.candidate.id)} />
      <span className="mw-mono">{row.candidate.id} · {row.candidate.smiles} · {stereoFlagText(row.candidate.stereo_flag)}</span>
    </label>)}
    <div className="mw-ligand-inline">
      <Button size="sm" disabled={page.offset === 0} onClick={() => onPage(Math.max(0, page.offset - page.limit))}>이전</Button>
      <Button size="sm" disabled={last >= page.total} onClick={() => onPage(last)}>다음</Button>
    </div>
  </fieldset>;
}

function ResultView({ detail, runId, selectedMode, onMode }: { detail: DockingResultDetail; runId: string;
  selectedMode: number | null; onMode: (mode: number) => void }) {
  const result = detail.result, mode: DockingMode = result.inputs.mode;
  const headers = modeTableHeaders(mode);
  return <div className="mw-docking-result" data-testid="docking-result" data-docking-result-handle={detail.handle}
    data-docking-mode={mode} data-null-result={result.counts.null_result}>
    <p className="mw-ligand-note mw-mono">결과 {shortHandle(detail.handle)} · 작업 {detail.job_id}</p>
    <dl className="mw-ligand-facts mw-docking-summary" data-testid="docking-summary">
      {dockingSummaryRows(result).map(([label, value]) => <div key={label} className="mw-ligand-fact">
        <dt>{label}</dt><dd className="mw-mono">{value}</dd></div>)}
    </dl>
    {result.modes.length > 0 && <>
      <div className="mw-ligand-inline">
        <a className="mw-btn mw-btn--sm" data-testid="docking-download-all" href={api.dockingPosesSdfUrl(runId, detail.handle)} download>
          포즈 SDF 전체 내려받기</a>
      </div>
      <div className="mw-ligand-table-wrap">
        <table className="mw-ligand-table" data-testid="docking-modes">
          <caption className="mw-ligand-note">{SCORE_LABEL} · {mode === "core_fixed" ? "샘플 n(점수 오름차순 나열)" : "모드 n(엔진 출력 순서)"}</caption>
          <thead><tr>{headers.map(header => <th key={header}>{header}</th>)}<th>접촉 표</th><th>포즈 SDF</th></tr></thead>
          <tbody>{result.modes.map(row => <tr key={row.mode} data-mode={row.mode} data-selected={selectedMode === row.mode}
            className={selectedMode === row.mode ? "mw-docking-row--selected" : undefined}>
            {modeTableCells(mode, row).map((cell, i) => <td key={headers[i]} className={i ? "mw-mono" : undefined}>{cell}</td>)}
            <td><Button size="sm" data-testid={`docking-mode-contacts-${row.mode}`} aria-pressed={selectedMode === row.mode}
              onClick={() => onMode(row.mode)}>접촉 보기</Button></td>
            <td><a className="mw-btn mw-btn--sm" data-testid={`docking-download-${row.mode}`}
              href={api.dockingPoseSdfUrl(runId, detail.handle, row.mode)} download>내려받기</a></td>
          </tr>)}</tbody>
        </table>
      </div>
    </>}
    <span className="mw-eyebrow">한계</span>
    <ul className="mw-ligand-list" data-testid="docking-limitations">
      {result.limitations.map(sentence => <li key={sentence}>{sentence}</li>)}</ul>
  </div>;
}

function ContactTable({ page, onPage }: { page: DockingContactPage; onPage: (offset: number) => void }) {
  const last = page.offset + page.rows.length;
  return <div className="mw-docking-contact-page" data-total={page.total} data-offset={page.offset}>
    <p className="mw-ligand-note" data-testid="docking-contacts-count">{contactPageText(page)} · 기준 {distanceText(page.cutoff_A)}</p>
    {page.rows.length > 0 && <div className="mw-ligand-table-wrap">
      <table className="mw-ligand-table">
        <thead><tr><th>리간드 원자</th><th>수용체 원자</th><th>거리</th><th>종류(기하)</th></tr></thead>
        <tbody>{page.rows.map(row => <tr key={`${row.ligand_serial}-${row.receptor_atom.site_index}`}
          data-ligand-serial={row.ligand_serial} data-site-index={row.receptor_atom.site_index}>
          <td className="mw-mono">{ligandAtomText(row)}</td><td className="mw-mono">{receptorAtomText(row.receptor_atom)}</td>
          <td className="mw-mono">{distanceText(row.distance_A)}</td><td>{contactKindText(row.kind)}</td>
        </tr>)}</tbody>
      </table>
    </div>}
    {page.total > page.limit && <div className="mw-ligand-inline">
      <Button size="sm" disabled={page.offset === 0} onClick={() => onPage(Math.max(0, page.offset - page.limit))}>이전</Button>
      <Button size="sm" disabled={last >= page.total} onClick={() => onPage(last)}>다음</Button>
    </div>}
  </div>;
}
