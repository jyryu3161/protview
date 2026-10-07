"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type RunSummary, type SavedReportRef } from "@/lib/api";
import type { DockingAcknowledgementKey, DockingBoxSource, DockingCapability, DockingJob, DockingLigandSource,
  DockingPrerequisites, MutationCandidateRow, MutationModelCapability,
  MutationModelContactPage, MutationModelDetail, MutationModelDockingPairs, MutationModelJob, MutationModelList,
  MutationModelReportArtifact, MutationModelSide } from "@/lib/contracts";
import { ACKNOWLEDGEMENT_KEYS, ACKNOWLEDGEMENT_LABEL, BOX_FRAME_NOTE, BOX_SIDE_MAX_A, BOX_SIDE_MIN_A, BOX_SOURCES,
  boxSourceLabel, dockingCancelEnabled, dockingJobActive, dockingRequestErrorText,
  dockingResponseCurrent, ENERGY_RANGE_MAX, ENERGY_RANGE_MIN, EXHAUSTIVENESS_MAX, EXHAUSTIVENESS_MIN, importsOfKind,
  LIGAND_SOURCES, MARGIN_MAX_A, MARGIN_MIN_A, NUM_MODES_MAX, NUM_MODES_MIN, SEED_MAX, SEED_MIN,
  type DockingStamp } from "@/lib/docking";
import { ligandStartProgressed } from "@/lib/ligand";
import { AREA_TITLE, CONFIRMATION_LABEL, CONTACT_CUTOFF_RANGE_A, CONTACT_PAGE_SIZE_DEFAULT, CONTACT_TABLE_HEADERS,
  contactPageCount, contactPageText, contactRowCells, disulfideText, initialModelCounters, initialModelForm,
  initialPairDockingForm, initialPairSubmission, LIST_LIMIT_MAX, MODEL_BUDGET_NOTE, MODEL_METHOD_NOTE,
  MODEL_REPORT_TYPE, MODEL_STATE_TEXT, modelActiveJob, modelApprovalRequired, modelAreaState, modelCapabilityText,
  modelContactQuery, modelFormForCandidate, modelJobResult, modelJobText, modelLimitations, modelListRowText,
  modelReasonText, modelReportMatches, modelReportSavedForRun, modelRequest, modelRequestErrorText, modelResponseCurrent,
  modelSubmitBlockedReason, modelSwitchBlockedReason, modelSubmitText, mutationSummaryText, nextModelRequest, nextPairStartSide,
  nextPairSubmitSide, NULL_TEXT, PAIR_AREA_TITLE, PAIR_BOX_SOURCES, PAIR_CONDITION_NOTE, PAIR_MODE_ONLY,
  PAIR_SCORE_NOTE, PAIR_UNITS_NOTICE, pairApprovalRequired, pairAreaState, pairBoxSourceDisabledReason,
  pairDockingRequests, pairLigandSourceDisabledReason, pairJobText, pairRows, pairSubmitAnswered, pairSubmitBlockedReason, pairSubmitStarted,
  pairSubmitText, pairTableHeaders, patchPairDockingForm, protonationRows, residueFieldsText, residueShortText,
  sideBySideRows, SIDE_BY_SIDE_NOTE, SIDE_LABEL, STRUCTURE_SIDES, structureDownloadLabel, TIMEOUT_MAX_S,
  unknownLimitations, type ModelArea, type ModelForm, type ModelRequestCounters, type ModelStamp, type PairDockingForm,
  type PairSubmission } from "@/lib/mutation-model";
import { Button } from "./primitives";

/**
 * M21 "변이 구조 모델링" area of the 단백질 공학 tab (spec section 9), mounted below the M20 candidate panel. Every
 * potential, SASA, contact, count and docking score shown is a stored backend value (the `mutation_model@1` reads and
 * the `docking_pairs` read); request checks, wording, rounding and currentness come from `lib/mutation-model.ts`
 * (the docking condition from `lib/docking.ts`). The page mounts it only while the tab is shown and keys it by run.
 * Late responses are dropped on two layers: abort on unmount, and run + model handle + per-area request number.
 * Nothing is chosen or approved automatically; there is no viewer display.
 */
export interface ModelStartRequest { runId: string; candidateSet: string; candidate: MutationCandidateRow; seq: number }

export interface MutationModelPanelProps {
  /** Current run of the structure analysis screen (run selection lives only there); null when none. */
  run: RunSummary | null;
  /** `methods.mutation_model`: undefined while capabilities are read; null when the backend reports no such method. */
  capability: MutationModelCapability | null | undefined;
  /** `methods.ligand_docking` (same-condition docking uses single M18 jobs). */
  dockingCapability: DockingCapability | null | undefined;
  /** "변이 구조 모델링" of an M20 candidate row (a new `seq` per click; same run only; never replayed on mount). */
  startRequest: ModelStartRequest | null;
  /** After a new model: the page re-reads the run's event log. */
  onObjectsChanged: (runId: string) => void;
  /** After a report was created: the page re-reads the knowledge-tab report list. */
  onReportCreated: (runId: string) => void;
}

type Load<T> = { status: "idle" } | { status: "loading" } | { status: "ready"; value: T } | { status: "error"; message: string };
type Extra = "prereq" | "report_list" | "model_cancel" | "pair_cancel";
const EXTRAS: readonly Extra[] = ["prereq", "report_list", "model_cancel", "pair_cancel"];
const MODEL_AREAS: readonly ModelArea[] = ["list", "detail", "contacts", "pairs", "report", "model_job", "pair_jobs"];
const TIMEOUT_MS = 30000;
const AXES = ["x", "y", "z"] as const;
const LIGAND_SOURCE_LABEL: Record<DockingLigandSource, string> = { sdf: "3D SDF 가져오기", candidate: "M17 후보 + 부모 3D SDF" };
type PairJobs = Record<MutationModelSide, DockingJob | null>;
const NO_PAIR_JOBS: PairJobs = { wild_type_reference: null, mutant: null };

function errorText(e: unknown): string {
  if (e instanceof ApiError) return modelRequestErrorText({ message: e.message, code: e.code, detail: e.detail });
  return e instanceof Error ? e.message : String(e);
}
function dockingErrorText(e: unknown): string {
  if (e instanceof ApiError) return dockingRequestErrorText(e);
  return e instanceof Error ? e.message : String(e);
}
const shortHandle = (handle: string) => handle.split("/").at(-1)?.slice(0, 12) ?? handle;

function Section({ area, title, state, children }: { area: string; title: string; state?: string; children: ReactNode }) {
  return <section className="mw-mutation-section" data-mutation-model-area={area} data-state={state} aria-label={title}>
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

export function MutationModelPanel(p: MutationModelPanelProps) {
  const runId = p.run?.run_id ?? null;
  if (!p.run || p.capability === undefined || p.capability === null || !p.capability.available) {
    const gate = modelAreaState({ runId, capability: p.capability });
    return <section className="mw-mutation" aria-label={AREA_TITLE} data-testid="mutation-model-panel"
      data-model-state={gate.state}>
      <h2 className="mw-mutation-heading">단백질 공학 · {AREA_TITLE}</h2>
      {gate.state === "unavailable" ? <p className="mw-mutation-unavailable" role="status"
        data-testid={runId === null ? "mutation-model-no-run" : "mutation-model-unavailable"}
        data-reason-code={p.capability?.reason_code ?? undefined}>
        <b>{MODEL_STATE_TEXT.unavailable}</b>: {gate.reason}</p>
        : <p className="mw-mutation-note" aria-busy="true">기능 상태를 확인하는 중</p>}
    </section>;
  }
  return <ModelWorkspace run={p.run} capability={p.capability} dockingCapability={p.dockingCapability}
    startRequest={p.startRequest} onObjectsChanged={p.onObjectsChanged} onReportCreated={p.onReportCreated} />;
}

function ModelWorkspace({ run, capability, dockingCapability, startRequest, onObjectsChanged, onReportCreated }: {
  run: RunSummary; capability: MutationModelCapability; dockingCapability: DockingCapability | null | undefined;
  startRequest: ModelStartRequest | null; onObjectsChanged: (runId: string) => void;
  onReportCreated: (runId: string) => void }) {
  const runId = run.run_id;
  // ---- model request and job ----
  const [form, setForm] = useState<ModelForm>(initialModelForm);
  const [picked, setPicked] = useState<MutationCandidateRow | null>(null);
  const [job, setJob] = useState<MutationModelJob | null>(null);
  const [jobFocus, setJobFocus] = useState(false);
  const [approvalPending, setApprovalPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [jobError, setJobError] = useState<{ message: string; reasonCode?: string } | null>(null);
  const [notice, setNotice] = useState("");
  const [newModel, setNewModel] = useState<string | null>(null);
  // ---- stored models ----
  const [models, setModels] = useState<Load<MutationModelList["rows"]>>({ status: "idle" });
  const [modelsReload, setModelsReload] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ handle: string; load: Load<MutationModelDetail> } | null>(null);
  const [contactSide, setContactSide] = useState<MutationModelSide>("wild_type_reference");
  const [contactPage, setContactPage] = useState(1);
  const [contacts, setContacts] = useState<{ key: string; load: Load<MutationModelContactPage> } | null>(null);
  const [contactsRetry, setContactsRetry] = useState(0);
  const [report, setReport] = useState<{ handle: string; load: Load<MutationModelReportArtifact> } | null>(null);
  const [reportList, setReportList] = useState<{ handle: string; load: Load<SavedReportRef[]> } | null>(null);
  const [reportListReload, setReportListReload] = useState(0);
  // ---- same-condition docking ----
  const [pairForm, setPairForm] = useState<PairDockingForm>(initialPairDockingForm);
  const [unitsConfirmed, setUnitsConfirmed] = useState(false);
  const [prereq, setPrereq] = useState<Load<DockingPrerequisites>>({ status: "idle" });
  const [prereqReload, setPrereqReload] = useState(0);
  const [submission, setSubmission] = useState<PairSubmission>(initialPairSubmission);
  const [pairJobs, setPairJobs] = useState<PairJobs>(NO_PAIR_JOBS);
  const [pairApproval, setPairApproval] = useState(false);
  const [pairBusy, setPairBusy] = useState(false);
  const [pairCancelling, setPairCancelling] = useState(false);
  const [pairStartError, setPairStartError] = useState<Partial<Record<MutationModelSide, string>>>({});
  const [pairNotice, setPairNotice] = useState("");
  const [pairs, setPairs] = useState<{ handle: string; load: Load<MutationModelDockingPairs> } | null>(null);
  const [pairsReload, setPairsReload] = useState(0);

  // Late responses: run (page key) + opened model handle + per-area request number (lib), and abort on unmount.
  const mounted = useRef(true);
  const counters = useRef<ModelRequestCounters>(initialModelCounters());
  const extras = useRef<Record<Extra, number>>(Object.fromEntries(EXTRAS.map(area => [area, 0])) as Record<Extra, number>);
  const live = useRef({ handle: selected });
  live.current = { handle: selected };
  useEffect(() => {
    mounted.current = true;
    const model = counters.current, extra = extras.current;
    return () => {
      mounted.current = false;
      for (const area of MODEL_AREAS) model[area] += 1;
      for (const area of EXTRAS) extra[area] += 1;
    };
  }, []);
  const handleOf = (area: ModelArea): string | null => area === "list" || area === "model_job" ? null : live.current.handle;
  const stamp = (area: ModelArea): ModelStamp => {
    const next = nextModelRequest(counters.current, area, runId, handleOf(area));
    counters.current = next.counters;
    return next.stamp;
  };
  const current = (area: ModelArea, captured: ModelStamp) => mounted.current &&
    modelResponseCurrent(captured, { runId, handle: handleOf(area), area, seq: counters.current[area] });
  const keyOf = (area: Extra): string | null => area === "report_list" || area === "pair_cancel" ? live.current.handle : null;
  const stampExtra = (area: Extra): DockingStamp => ({ runId, key: keyOf(area), seq: ++extras.current[area] });
  const currentExtra = (area: Extra, captured: DockingStamp) => mounted.current &&
    dockingResponseCurrent(captured, { runId, key: keyOf(area), seq: extras.current[area] });

  // ---- run-wide reads (on mount = on entering the tab, and on retry) ----
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    const captured = stamp("list"), controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)]);
    setModels({ status: "loading" });
    (async () => {
      const first = await api.mutationModels(runId, 0, LIST_LIMIT_MAX, signal);
      if (first.schema !== "mutation_model_list@1") throw new Error("변이 구조 모델 목록 형식이 다릅니다.");
      const rows = [...first.rows];
      while (rows.length < first.total) {
        const page = await api.mutationModels(runId, rows.length, LIST_LIMIT_MAX, signal);
        if (page.total !== first.total || !page.rows.length) throw new Error("모델 목록이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
        rows.push(...page.rows);
      }
      return rows;
    })().then(rows => { if (current("list", captured)) setModels({ status: "ready", value: rows }); })
      .catch(e => { if (current("list", captured) && !controller.signal.aborted)
        setModels({ status: "error", message: `변이 구조 모델 목록 읽기 실패: ${errorText(e)}` }); });
    return () => controller.abort();
  }, [runId, modelsReload]);

  // After a remount the durable job list tells whether a model job of this run is still queued or running.
  useEffect(() => {
    const captured = stamp("model_job"), controller = new AbortController();
    api.mutationModelJobs(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)])).then(list => {
      if (!current("model_job", captured)) return;
      const running = modelActiveJob<MutationModelJob>(list, runId);
      if (running) { setJob(previous => previous ?? running); setJobFocus(true); }
    }).catch(() => undefined);
    return () => controller.abort();
  }, [runId]);

  // Polling reads only, while the model job is queued, claimed or running.
  useEffect(() => {
    if (!job || !dockingJobActive(job)) return;
    let active = true;
    const jobId = job.job_id;
    const timer = window.setInterval(() => {
      void api.mutationModelJob(runId, jobId).then(value => {
        if (active && mounted.current && value.run_id === runId && value.job_id === jobId)
          setJob(previous => previous?.job_id === jobId ? value : previous);
      }).catch(() => undefined);
    }, 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [runId, job?.job_id, job?.status]);

  // A finished job refreshes the list; its model is not opened by itself (the person clicks it).
  useEffect(() => {
    if (!job) return;
    if (job.status !== "queued") setNotice(previous => previous === APPROVED_NOTICE ? "" : previous);
    const handle = modelJobResult(job);
    if (handle) { setNewModel(handle); setModelsReload(value => value + 1); onObjectsChanged(runId); }
  }, [job?.job_id, job?.status]);
  /* eslint-enable react-hooks/exhaustive-deps */

  // ---- the candidate handed over from an M20 row (a new seq per click; never replayed on mount) ----
  const seenStart = useRef(startRequest?.seq ?? 0);
  useEffect(() => {
    if (!startRequest || startRequest.seq === seenStart.current || startRequest.runId !== runId) return;
    seenStart.current = startRequest.seq;
    setForm(previous => modelFormForCandidate(previous, startRequest.candidateSet, startRequest.candidate.index));
    setPicked(startRequest.candidate);
    setJobError(null); setNotice("");
    document.querySelector('[data-testid="mutation-model-panel"] [data-mutation-model-area="request"]')
      ?.scrollIntoView({ block: "start" });
  // Each click is a new seq.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startRequest?.seq]);

  // ---- opened model: detail, contact pages, reports, docking pairs ----
  // Not while the same-condition action is mid-way: opening a model resets the pair area (the controls say why).
  const switchBlocked = modelSwitchBlockedReason(pairBusy);
  function openModel(handle: string) {
    if (switchBlocked) return;
    setSelected(handle); live.current = { ...live.current, handle };
    setContactSide("wild_type_reference"); setContactPage(1); setContacts(null); setReport(null);
    setSubmission(initialPairSubmission()); setPairJobs(NO_PAIR_JOBS); setPairApproval(false); setPairStartError({});
    setPairNotice(""); setUnitsConfirmed(false); setPairs(null);
    const captured = stamp("detail");
    setDetail({ handle, load: { status: "loading" } });
    api.mutationModel(runId, handle, AbortSignal.timeout(TIMEOUT_MS)).then(value => {
      if (!current("detail", captured)) return;
      if (value.schema !== "mutation_model_detail@1" || value.handle !== handle)
        throw new Error("변이 구조 모델이 고른 handle과 다릅니다.");
      setDetail({ handle, load: { status: "ready", value } });
    }).catch(e => { if (current("detail", captured))
      setDetail({ handle, load: { status: "error", message: `변이 구조 모델 읽기 실패: ${errorText(e)}` } }); });
  }
  const openedDetail = detail && detail.handle === selected && detail.load.status === "ready" ? detail.load.value : null;
  const strange = openedDetail ? unknownLimitations(modelLimitations(openedDetail.result)) : [];
  const opened = openedDetail && !strange.length ? openedDetail : null;
  const openedHandle = opened?.handle ?? null;

  const contactsKey = openedHandle ? JSON.stringify([openedHandle, contactSide, contactPage]) : null;
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    if (!openedHandle || contactsKey === null) return;
    const key = contactsKey, handle = openedHandle, side = contactSide, captured = stamp("contacts");
    const controller = new AbortController();
    setContacts({ key, load: { status: "loading" } });
    api.mutationModelContacts(runId, handle, modelContactQuery(side, contactPage, CONTACT_PAGE_SIZE_DEFAULT),
      AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)])).then(value => {
      if (!current("contacts", captured)) return;
      if (value.schema !== "mutation_model_contact_page@1" || value.handle !== handle || value.structure !== side)
        throw new Error("접촉 행이 고른 모델·구조와 다릅니다.");
      setContacts({ key, load: { status: "ready", value } });
    }).catch(e => { if (current("contacts", captured) && !controller.signal.aborted)
      setContacts({ key, load: { status: "error", message: `접촉 행 읽기 실패: ${errorText(e)}` } }); });
    return () => controller.abort();
  }, [contactsKey, contactsRetry]);
  const contactLoad = contacts && contacts.key === contactsKey ? contacts.load : null;

  useEffect(() => {
    if (!openedHandle) return;
    const handle = openedHandle, captured = stampExtra("report_list"), controller = new AbortController();
    setReportList({ handle, load: { status: "loading" } });
    api.reports(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)])).then(rows => {
      if (!currentExtra("report_list", captured)) return;
      setReportList({ handle, load: { status: "ready", value: rows.filter(row =>
        row.analysis_type === MODEL_REPORT_TYPE && row.result_handle === handle) } });
    }).catch(e => { if (currentExtra("report_list", captured) && !controller.signal.aborted)
      setReportList({ handle, load: { status: "error", message: `보고서 목록 읽기 실패: ${errorText(e)}` } }); });
    return () => controller.abort();
  }, [openedHandle, reportListReload]);
  const reportListLoad = reportList && reportList.handle === openedHandle ? reportList.load : null;

  useEffect(() => {
    if (!openedHandle) return;
    const handle = openedHandle, captured = stamp("pairs"), controller = new AbortController();
    setPairs(previous => previous?.handle === handle && previous.load.status === "ready" ? previous
      : { handle, load: { status: "loading" } });
    api.mutationModelDockingPairs(runId, handle, AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)]))
      .then(value => {
        if (!current("pairs", captured)) return;
        if (value.schema !== "mutation_model_docking_pairs@1" || value.handle !== handle)
          throw new Error("도킹 짝 응답이 고른 모델과 다릅니다.");
        setPairs({ handle, load: { status: "ready", value } });
      }).catch(e => { if (current("pairs", captured) && !controller.signal.aborted)
        setPairs({ handle, load: { status: "error", message: `같은 조건 도킹 짝 읽기 실패: ${dockingErrorText(e)}` } }); });
    return () => controller.abort();
  }, [openedHandle, pairsReload]);
  const pairsLoad = pairs && pairs.handle === openedHandle ? pairs.load : null;

  // Docking inputs (ligand SDF imports; SDF ligands only), read once a model is open.
  const wantsPrereq = openedHandle !== null;
  useEffect(() => {
    if (!wantsPrereq) return;
    const captured = stampExtra("prereq"), controller = new AbortController();
    setPrereq({ status: "loading" });
    api.dockingPrerequisites(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(TIMEOUT_MS)])).then(value => {
      if (!currentExtra("prereq", captured)) return;
      if (value.schema !== "docking_prerequisites@1") throw new Error("입력 준비 응답 형식이 다릅니다.");
      setPrereq({ status: "ready", value });
    }).catch(e => { if (currentExtra("prereq", captured) && !controller.signal.aborted)
      setPrereq({ status: "error", message: `도킹 입력 목록 읽기 실패: ${dockingErrorText(e)}` }); });
    return () => controller.abort();
  }, [runId, wantsPrereq, prereqReload]);

  // Polling reads of the two docking jobs while either is queued, claimed or running.
  const pairJobKey = STRUCTURE_SIDES.map(side => `${pairJobs[side]?.job_id ?? ""}:${pairJobs[side]?.status ?? ""}`).join("|");
  useEffect(() => {
    const activeIds = STRUCTURE_SIDES.flatMap(side => {
      const entry = pairJobs[side];
      return entry && dockingJobActive(entry) ? [[side, entry.job_id] as const] : [];
    });
    if (!activeIds.length) return;
    let active = true;
    const timer = window.setInterval(() => {
      for (const [side, jobId] of activeIds) void api.dockingJob(runId, jobId).then(value => {
        if (active && mounted.current && value.run_id === runId && value.job_id === jobId)
          setPairJobs(previous => previous[side]?.job_id === jobId ? { ...previous, [side]: value } : previous);
      }).catch(() => undefined);
    }, 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [runId, pairJobKey]);
  // A docking job that ends re-reads the pair table (the server groups and decides what may be shown).
  const pairEnded = STRUCTURE_SIDES.map(side => pairJobs[side] && !dockingJobActive(pairJobs[side]) ? pairJobs[side]!.job_id : "")
    .join("|");
  useEffect(() => { if (pairEnded.replace(/\|/g, "")) setPairsReload(value => value + 1); }, [pairEnded]);
  /* eslint-enable react-hooks/exhaustive-deps */

  // ---- model job actions (POST /jobs → start → 409 approval → approve → start) ----
  const check = modelRequest(form);
  const submitBlocked = modelSubmitBlockedReason({ capability, busy, activeJob: job, check });

  async function start(before: MutationModelJob) {
    const captured = stamp("model_job");
    setBusy(true); setJobError(null); setNotice(""); setJobFocus(true);
    try {
      const value = await api.startJob(runId, before.job_id) as unknown as MutationModelJob;
      if (!current("model_job", captured)) return;
      if (value.run_id !== runId || value.job_id !== before.job_id) throw new Error("시작 응답이 이 작업과 다릅니다.");
      setApprovalPending(false); setJob(value);
    } catch (e) {
      if (!current("model_job", captured)) return;
      if (e instanceof ApiError && modelApprovalRequired(e.status, e.approval)) { setApprovalPending(true); return; }
      // The start may have taken effect although its response was lost: the stored job decides.
      const stored = await api.mutationModelJob(runId, before.job_id).catch(() => null);
      if (!current("model_job", captured)) return;
      if (stored && stored.run_id === runId && stored.job_id === before.job_id) setJob(stored);
      if (!stored || !ligandStartProgressed(before, stored)) setJobError({ message: `작업 시작 실패: ${errorText(e)}` });
    } finally { if (mounted.current) setBusy(false); }
  }

  async function submit() {
    if (submitBlocked || !check.ok) return;
    const request = check.args, captured = stamp("model_job");
    setBusy(true); setJobError(null); setNotice(""); setNewModel(null); setApprovalPending(false); setJobFocus(true);
    try {
      const result = await api.submitMutationModel(runId, request.args, request.timeout_s);
      if (!current("model_job", captured)) return;
      if ("plan_only" in result) { setNotice(modelSubmitText(result)); return; }
      if (result.run_id !== runId || result.protocol_id !== "openmm_mutation_model_v1") throw new Error("제출 응답이 요청과 다릅니다.");
      setJob(result);
      if (result.status !== "queued") { setNotice(modelSubmitText(result)); return; }
      await start(result);
    } catch (e) {
      if (!current("model_job", captured)) return;
      const reasonCode = e instanceof ApiError && typeof e.detail?.reason_code === "string" ? e.detail.reason_code
        : e instanceof ApiError ? e.code : undefined;
      setJobError({ message: `작업 제출 거절: ${errorText(e)}`, reasonCode });
    } finally { if (mounted.current) setBusy(false); }
  }

  async function approve() {
    if (!job) return;
    const captured = stamp("model_job");
    setBusy(true); setJobError(null);
    try {
      await api.approveOpenmm(runId);
      if (!current("model_job", captured)) return;
      setApprovalPending(false); setNotice(APPROVED_NOTICE);
    } catch (e) { if (current("model_job", captured)) setJobError({ message: `승인 실패: ${errorText(e)}` }); }
    finally { if (mounted.current) setBusy(false); }
  }

  async function retryJob() {
    if (!job) return;
    const captured = stamp("model_job"), jobId = job.job_id;
    setBusy(true); setJobError(null);
    try {
      const value = await api.retryJob(runId, jobId) as unknown as MutationModelJob;
      if (current("model_job", captured) && value.run_id === runId && value.job_id === jobId) setJob(value);
    } catch (e) { if (current("model_job", captured)) setJobError({ message: `작업 재시도 실패: ${errorText(e)}` }); }
    finally { if (mounted.current) setBusy(false); }
  }

  // Not tied to the job request number or `busy`: a held start request keeps its own answer.
  async function cancelJob() {
    if (!job || !dockingCancelEnabled({ job, cancelling })) return;
    const captured = stampExtra("model_cancel"), jobId = job.job_id;
    setCancelling(true);
    try {
      const value = (await api.cancelJob(runId, jobId)).job as unknown as MutationModelJob;
      if (currentExtra("model_cancel", captured) && value.run_id === runId && value.job_id === jobId)
        setJob(previous => previous?.job_id === jobId ? value : previous);
    } catch (e) { if (currentExtra("model_cancel", captured)) setJobError({ message: `작업 취소 실패: ${errorText(e)}` }); }
    finally { if (mounted.current) setCancelling(false); }
  }

  async function makeReport() {
    if (!opened || !selected || report?.load.status === "loading") return;
    const handle = selected, captured = stamp("report");
    setReport({ handle, load: { status: "loading" } });
    try {
      const artifact = await api.createMutationModelReport(runId, handle, AbortSignal.timeout(60000));
      if (modelReportSavedForRun(captured, runId) && mounted.current) {
        onReportCreated(runId); setReportListReload(value => value + 1);
      }
      if (!current("report", captured)) return;
      if (!modelReportMatches(artifact, handle)) throw new Error("보고서가 고른 변이 구조 모델과 다릅니다.");
      setReport({ handle, load: { status: "ready", value: artifact } });
    } catch (e) { if (current("report", captured)) setReport({ handle, load: { status: "error", message: `보고서 만들기 실패: ${errorText(e)}` } }); }
  }

  // ---- same-condition docking actions (two single M18 jobs, one at a time) ----
  const pairCheck = pairDockingRequests(pairForm, openedHandle);
  const pairActive = STRUCTURE_SIDES.flatMap(side => pairJobs[side] ? [pairJobs[side]!] : []);
  const pairBlocked = pairSubmitBlockedReason({ capability: dockingCapability, busy: pairBusy, unitsConfirmed,
    activeJobs: pairActive, check: pairCheck });
  const updatePair = (patch: Partial<PairDockingForm>) => setPairForm(previous => patchPairDockingForm(previous, patch));

  /** Starts the saved sides in order; stops at an approval answer or while a side still runs (the person continues). */
  async function startPairJobs(initial: PairJobs, captured: ModelStamp) {
    let jobs = initial;
    const tried = new Set<MutationModelSide>();
    for (;;) {
      const view = { ...jobs };
      for (const side of tried) if (view[side] && !["claimed", "running"].includes(view[side]!.status)) view[side] = null;
      const side = nextPairStartSide(view);
      if (side === null) return;
      tried.add(side);
      const before = jobs[side]!;
      try {
        const value = await api.startJob(runId, before.job_id) as unknown as DockingJob;
        if (!current("pair_jobs", captured)) return;
        if (value.run_id !== runId || value.job_id !== before.job_id) throw new Error("시작 응답이 이 작업과 다릅니다.");
        jobs = { ...jobs, [side]: value };
        setPairJobs(previous => ({ ...previous, [side]: value }));
      } catch (e) {
        if (!current("pair_jobs", captured)) return;
        if (e instanceof ApiError && pairApprovalRequired(e.status, e.approval)) { setPairApproval(true); return; }
        const stored = await api.dockingJob(runId, before.job_id).catch(() => null);
        if (!current("pair_jobs", captured)) return;
        if (stored && stored.run_id === runId && stored.job_id === before.job_id) {
          jobs = { ...jobs, [side]: stored };
          setPairJobs(previous => ({ ...previous, [side]: stored }));
        }
        if (!stored || !ligandStartProgressed(before, stored))
          setPairStartError(previous => ({ ...previous, [side]: `작업 시작 실패: ${dockingErrorText(e)}` }));
        if (stored && dockingJobActive(stored) && stored.status !== "queued") return;
      }
    }
  }

  async function submitPair() {
    if (pairBlocked || !pairCheck.ok || !openedHandle) return;
    const requests = pairCheck.args, captured = stamp("pair_jobs");
    let state = initialPairSubmission(), jobs: PairJobs = NO_PAIR_JOBS;
    setPairBusy(true); setSubmission(state); setPairJobs(jobs); setPairApproval(false); setPairStartError({}); setPairNotice("");
    try {
      for (let side = nextPairSubmitSide(state); side !== null; side = nextPairSubmitSide(state)) {
        state = pairSubmitStarted(state, side);
        setSubmission(state);
        try {
          const result = await api.submitDocking(runId, requests[side]);
          if (!current("pair_jobs", captured)) return;
          if (!("plan_only" in result) && (result.run_id !== runId || result.protocol_id !== "qvina_dock_v1"))
            throw new Error("제출 응답이 요청과 다릅니다.");
          state = pairSubmitAnswered(state, side, { ok: true, result });
          if (!("plan_only" in result)) jobs = { ...jobs, [side]: result };
        } catch (e) {
          if (!current("pair_jobs", captured)) return;
          state = pairSubmitAnswered(state, side, { ok: false, error: dockingErrorText(e) });
        }
        setSubmission(state); setPairJobs(jobs);
      }
      setPairsReload(value => value + 1);
      setUnitsConfirmed(false);
      await startPairJobs(jobs, captured);
    } finally { if (mounted.current) setPairBusy(false); }
  }

  async function approvePair() {
    const captured = stamp("pair_jobs");
    setPairBusy(true);
    try {
      await api.approveOpenmm(runId);
      if (!current("pair_jobs", captured)) return;
      setPairApproval(false); setPairNotice(PAIR_APPROVED_NOTICE);
    } catch (e) { if (current("pair_jobs", captured)) setPairNotice(`승인 실패: ${dockingErrorText(e)}`); }
    finally { if (mounted.current) setPairBusy(false); }
  }

  async function continuePair() {
    const captured = stamp("pair_jobs");
    setPairBusy(true); setPairStartError({}); setPairNotice("");
    try { await startPairJobs(pairJobs, captured); } finally { if (mounted.current) setPairBusy(false); }
  }

  async function cancelPair(side: MutationModelSide) {
    const entry = pairJobs[side];
    if (!entry || !dockingCancelEnabled({ job: entry, cancelling: pairCancelling })) return;
    const captured = stampExtra("pair_cancel"), jobId = entry.job_id;
    setPairCancelling(true);
    try {
      const value = (await api.cancelJob(runId, jobId)).job as unknown as DockingJob;
      if (currentExtra("pair_cancel", captured) && value.run_id === runId && value.job_id === jobId)
        setPairJobs(previous => previous[side]?.job_id === jobId ? { ...previous, [side]: value } : previous);
    } catch (e) {
      if (currentExtra("pair_cancel", captured))
        setPairStartError(previous => ({ ...previous, [side]: `작업 취소 실패: ${dockingErrorText(e)}` }));
    } finally { if (mounted.current) setPairCancelling(false); }
  }

  // ---- area states ----
  const modelListValue = models.status === "ready" ? models.value : undefined;
  const readError = (detail?.handle === selected && detail?.load.status === "error" ? detail.load.message : null)
    ?? (strange.length ? `저장된 한계 문장이 고정 문장과 다릅니다(값을 보이지 않음): ${modelReasonText("method_evidence_invalid")}` : null)
    ?? (contactLoad?.status === "error" ? contactLoad.message : null)
    ?? (models.status === "error" ? models.message : null);
  const areaState = modelAreaState({ runId, capability,
    loading: models.status === "loading" || models.status === "idle" || detail?.load.status === "loading",
    error: readError, job: jobFocus ? job : null, models: modelListValue, detail: opened });
  const pairState = pairAreaState({ runId, capability: dockingCapability,
    loading: pairsLoad?.status === "loading", error: pairsLoad?.status === "error" ? pairsLoad.message : null,
    pairs: pairsLoad?.status === "ready" ? pairsLoad.value : null });
  const jobPhaseText = modelJobText(job, approvalPending);
  const awaitingApproval = !!job && approvalPending && job.status === "queued";
  const prereqValue = prereq.status === "ready" ? prereq.value : null;
  const ligandSdfs = prereqValue ? importsOfKind(prereqValue.imports, "ligand_sdf") : [];
  const pairQueued = STRUCTURE_SIDES.some(side => pairJobs[side]?.status === "queued");
  const pairRunning = STRUCTURE_SIDES.some(side => ["claimed", "running"].includes(pairJobs[side]?.status ?? ""));
  const pairSubmitted = STRUCTURE_SIDES.some(side => submission[side].status !== "pending");

  return <section className="mw-mutation" aria-label={AREA_TITLE} data-testid="mutation-model-panel"
    data-model-state={areaState.state}>
    <div className="mw-mutation-head">
      <h2 className="mw-mutation-heading">단백질 공학 · {AREA_TITLE}</h2>
      <span className="mw-badge" data-testid="mutation-model-state">{MODEL_STATE_TEXT[areaState.state]}</span>
    </div>
    {areaState.state === "failed" && <p role="alert" className="mw-mutation-error" data-testid="mutation-model-failure">
      {areaState.message}</p>}
    {areaState.state === "empty" && <p role="status" className="mw-mutation-null" data-testid="mutation-model-empty">
      {areaState.message}</p>}
    <p className="mw-mutation-note">{MODEL_METHOD_NOTE}</p>
    <p className="mw-mutation-note mw-mono" data-testid="mutation-model-capability">
      {capability.tool_id} · {capability.protocol_id} · OpenMM {capability.versions?.openmm ?? NULL_TEXT} · PDBFixer{" "}
      {capability.versions?.pdbfixer ?? NULL_TEXT}</p>
    {run.dry_run && <p role="status" className="mw-mutation-unavailable" data-testid="mutation-model-dry-run">
      dry-run run: 모델링 작업을 제출하면 계획만 만들며 실제 계산과 결과 객체가 없습니다.</p>}

    <Section area="request" title="① 모델링 요청">
      {picked && form.candidateSet && form.candidateIndex !== null
        ? <p className="mw-mono" data-testid="mutation-model-candidate" data-candidate-set={form.candidateSet}
          data-candidate-index={form.candidateIndex}>
          후보 번호 {picked.index} · {residueShortText(picked.residue)} · {picked.from} → {picked.to} · 위치{" "}
          {residueFieldsText(picked.residue)} · 후보 집합 {shortHandle(form.candidateSet)}</p>
        : <p className="mw-mutation-note" data-testid="mutation-model-no-candidate">
          위 변이 후보 표의 후보 행에서 &quot;변이 구조 모델링&quot;을 누르면 그 후보가 여기에 들어옵니다(자동으로 고르지 않음).</p>}
      <div className="mw-mutation-inline">
        <label className="mw-mutation-check">seed (필수, 정수)
          <input className="mw-mutation-input" data-testid="mutation-model-seed" aria-label="모델링 seed" inputMode="numeric"
            value={form.seed} onChange={event => setForm(previous => ({ ...previous, seed: event.target.value }))} /></label>
        <label className="mw-mutation-check">접촉 cutoff (Å, {CONTACT_CUTOFF_RANGE_A[0].toFixed(1)}–{CONTACT_CUTOFF_RANGE_A[1].toFixed(1)})
          <input className="mw-mutation-input" data-testid="mutation-model-cutoff" aria-label="접촉 cutoff" inputMode="decimal"
            value={form.cutoff} onChange={event => setForm(previous => ({ ...previous, cutoff: event.target.value }))} /></label>
        <label className="mw-mutation-check">시간 상한 (초, 최대 {TIMEOUT_MAX_S})
          <input className="mw-mutation-input" data-testid="mutation-model-timeout" aria-label="시간 상한" inputMode="numeric"
            value={form.timeout} onChange={event => setForm(previous => ({ ...previous, timeout: event.target.value }))} /></label>
      </div>
      <fieldset className="mw-mutation-choices" data-testid="mutation-model-confirmations">
        <legend>확인 (두 항목 모두, 요청마다 새로)</legend>
        <label><input type="checkbox" data-testid="mutation-model-confirm-selection" checked={form.selectionConfirmed}
          onChange={event => setForm(previous => ({ ...previous, selectionConfirmed: event.target.checked }))} />
          {CONFIRMATION_LABEL.selection_policy}</label>
        <label><input type="checkbox" data-testid="mutation-model-confirm-hydrogen" checked={form.hydrogenConfirmed}
          onChange={event => setForm(previous => ({ ...previous, hydrogenConfirmed: event.target.checked }))} />
          {CONFIRMATION_LABEL.hydrogen_policy}</label>
      </fieldset>
      <p className="mw-mutation-notice" data-testid="mutation-model-budget-note">{MODEL_BUDGET_NOTE}</p>
      {!check.ok && <ul className="mw-mutation-errors" data-testid="mutation-model-request-errors">
        {check.errors.map(error => <li key={error}>{error}</li>)}</ul>}
      <div className="mw-mutation-inline">
        <Button size="sm" variant="primary" data-testid="mutation-model-submit" disabled={!!submitBlocked}
          title={submitBlocked ?? undefined} onClick={() => void submit()}>모델링 작업 제출</Button>
        {submitBlocked && <span className="mw-mutation-note" data-testid="mutation-model-submit-blocked">{submitBlocked}</span>}
      </div>
      {(job || notice || jobError || newModel) && <div className="mw-mutation-group" data-testid="mutation-model-job-area">
        {job && <div data-testid="mutation-model-job" data-job-status={job.status} data-job-id={job.job_id}
          data-approval-pending={awaitingApproval || undefined}>
          <p className="mw-mutation-note" role="status">{jobPhaseText}</p>
          <p className="mw-mutation-note mw-mono">{capability.tool_id} · 작업 {job.status} · 시도 {job.attempt_ordinal} · {job.job_id}</p>
          {job.blocked_reason && <p className="mw-mutation-note">시작 대기 이유: {modelReasonText(job.blocked_reason)}</p>}
          <div className="mw-mutation-inline">
            {awaitingApproval && <Button size="sm" data-testid="mutation-model-job-approve" disabled={busy}
              onClick={() => void approve()}>비싼 계산 승인</Button>}
            {job.status === "queued" && !awaitingApproval && <Button size="sm" data-testid="mutation-model-job-start"
              disabled={busy || run.dry_run} onClick={() => void start(job)}>작업 시작</Button>}
            {dockingJobActive(job) && <Button size="sm" data-testid="mutation-model-job-cancel"
              disabled={!dockingCancelEnabled({ job, cancelling })} onClick={() => void cancelJob()}>작업 취소</Button>}
            {["failed", "interrupted"].includes(job.status) && job.attempt_ordinal < 4 && <Button size="sm"
              data-testid="mutation-model-job-retry" disabled={busy} onClick={() => void retryJob()}>작업 재시도</Button>}
          </div>
        </div>}
        {notice && <p role="status" className="mw-mutation-note" data-testid="mutation-model-notice">{notice}</p>}
        {jobError && <ErrorLine message={jobError.message} testId="mutation-model-job-error" reasonCode={jobError.reasonCode} />}
        {newModel && <div className="mw-mutation-inline" data-testid="mutation-model-new" data-model-handle={newModel}>
          <span className="mw-mutation-note" role="status">변이 구조 모델을 저장했습니다 · {shortHandle(newModel)}</span>
          <Button size="sm" data-testid="mutation-model-open-new" disabled={!!switchBlocked} title={switchBlocked ?? undefined}
            onClick={() => openModel(newModel)}>이 모델 열기</Button>
        </div>}
      </div>}
    </Section>

    <Section area="list" title="② 저장된 변이 구조 모델" state={models.status}>
      {models.status === "loading" && <p className="mw-mutation-note" aria-busy="true">모델 목록을 읽는 중</p>}
      {models.status === "error" && <ErrorLine message={models.message} onRetry={() => setModelsReload(value => value + 1)} />}
      {models.status === "ready" && (!models.value.length
        ? <p className="mw-mutation-note" data-testid="mutation-model-list-empty">이 run에 변이 구조 모델이 없습니다.</p>
        : <fieldset className="mw-mutation-choices" data-testid="mutation-model-list">
          <legend>모델 선택 (최신 순, 자동으로 고르지 않음)</legend>
          {models.value.map(row => <label key={row.handle} data-mutation-model={row.handle} data-valid={row.valid}>
            <input type="radio" name={`mutation-model-${runId}`} checked={selected === row.handle}
              disabled={!row.valid || !!switchBlocked}
              aria-label={`모델 ${shortHandle(row.handle)}`} onChange={() => openModel(row.handle)} />
            <span className="mw-mono">{modelListRowText(row)} · {shortHandle(row.handle)}</span>
          </label>)}
        </fieldset>)}
      {switchBlocked && <p className="mw-mutation-note" role="status" data-testid="mutation-model-switch-blocked">
        {switchBlocked}</p>}
      {models.status !== "loading" && <Button size="sm" data-testid="mutation-model-list-refresh"
        onClick={() => setModelsReload(value => value + 1)}>모델 목록 다시 읽기</Button>}
      {detail?.handle === selected && detail.load.status === "loading" && <p className="mw-mutation-note" aria-busy="true">모델을 읽는 중</p>}
      {detail?.handle === selected && detail.load.status === "error" &&
        <ErrorLine message={detail.load.message} onRetry={switchBlocked ? undefined : () => selected && openModel(selected)} />}
    </Section>

    {opened && <Section area="detail" title="③ 결과">
      <ModelSummary detail={opened} runId={runId} />

      <div className="mw-mutation-group" aria-label="접촉 행" data-testid="mutation-model-contacts-area">
        <span className="mw-eyebrow">변이 위치 잔기 주변 중원자 접촉 행</span>
        <fieldset className="mw-mutation-choices" data-testid="mutation-model-contacts-side">
          <legend>구조</legend>
          {STRUCTURE_SIDES.map(side => <label key={side} data-side={side}>
            <input type="radio" name={`mutation-model-contacts-${runId}`} checked={contactSide === side}
              data-testid={`mutation-model-contacts-side-${side}`}
              onChange={() => { setContactSide(side); setContactPage(1); }} /> {SIDE_LABEL[side]}</label>)}
        </fieldset>
        {contactLoad?.status === "loading" && <p className="mw-mutation-note" aria-busy="true">접촉 행을 읽는 중</p>}
        {contactLoad?.status === "error" && <ErrorLine message={contactLoad.message} testId="mutation-model-contacts-error"
          onRetry={() => setContactsRetry(value => value + 1)} />}
        {contactLoad?.status === "ready" && <ContactTable page={contactLoad.value} onPage={setContactPage} />}
      </div>

      <div className="mw-mutation-group" aria-label="한계" data-testid="mutation-model-limitations">
        <span className="mw-eyebrow">한계 (고정 문장)</span>
        {modelLimitations(opened.result).map((sentence, index) => <p key={index} className="mw-mutation-note"
          data-limitation={index}>{sentence}</p>)}
      </div>

      <div className="mw-mutation-group" aria-label="구조 내려받기">
        <span className="mw-eyebrow">구조 mmCIF (저장된 바이트, 누를 때만 내려받음)</span>
        <div className="mw-mutation-inline">
          {STRUCTURE_SIDES.map(side => <a key={side} className="mw-btn mw-btn--sm" data-testid={`mutation-model-download-${side}`}
            href={api.mutationModelStructureUrl(runId, opened.handle, side)} download>{structureDownloadLabel(side)}</a>)}
        </div>
      </div>

      <div className="mw-mutation-group" aria-label="보고서" data-testid="mutation-model-report-area">
        <span className="mw-eyebrow">보고서 (도킹 점수는 인용하지 않음)</span>
        <div className="mw-mutation-inline">
          <Button size="sm" data-testid="mutation-model-report" disabled={report?.handle === selected && report.load.status === "loading"}
            onClick={() => void makeReport()}>보고서 만들기</Button>
        </div>
        {report?.handle === selected && report.load.status === "loading" && <p className="mw-mutation-note" aria-busy="true">보고서를 만드는 중</p>}
        {report?.handle === selected && report.load.status === "ready" && <p role="status" className="mw-mutation-note"
          data-testid="mutation-model-report-done" data-report-handle={report.load.value.handle}>
          보고서를 저장했습니다 · {shortHandle(report.load.value.handle)}</p>}
        {report?.handle === selected && report.load.status === "error" && <ErrorLine message={report.load.message}
          testId="mutation-model-report-error" />}
        {reportListLoad?.status === "loading" && <p className="mw-mutation-note" aria-busy="true">보고서 목록을 읽는 중</p>}
        {reportListLoad?.status === "error" && <ErrorLine message={reportListLoad.message}
          onRetry={() => setReportListReload(value => value + 1)} />}
        {reportListLoad?.status === "ready" && (!reportListLoad.value.length
          ? <p className="mw-mutation-note" data-testid="mutation-model-report-list-empty">이 모델의 저장된 보고서가 없습니다.</p>
          : <ul className="mw-mutation-list" data-testid="mutation-model-report-list">
            {reportListLoad.value.map(row => <li key={row.handle} data-report-handle={row.handle}>
              <span className="mw-mono">이벤트 #{row.created_seq} · {shortHandle(row.handle)}</span>
              <a className="mw-btn mw-btn--sm" data-testid="mutation-model-report-markdown"
                href={api.reportDownload(runId, row.handle, "markdown")} download>Markdown 내려받기</a>
              <a className="mw-btn mw-btn--sm" data-testid="mutation-model-report-json"
                href={api.reportDownload(runId, row.handle, "json")} download>JSON 내려받기</a>
            </li>)}
          </ul>)}
      </div>
    </Section>}

    {opened && <Section area="pairs" title={`④ ${PAIR_AREA_TITLE}`} state={pairState.state}>
      <div data-testid="mutation-model-pairs-area" data-pair-state={pairState.state}>
        <span className="mw-badge" data-testid="mutation-model-pairs-state">{MODEL_STATE_TEXT[pairState.state]}</span>
      </div>
      {pairState.state === "unavailable" ? <p className="mw-mutation-unavailable" role="status"
        data-testid="mutation-model-pairs-unavailable"><b>{MODEL_STATE_TEXT.unavailable}</b>: {pairState.reason}</p> : <>
        <p className="mw-mutation-note">{PAIR_CONDITION_NOTE}</p>
        <p className="mw-mutation-note">{PAIR_MODE_ONLY}</p>
        <PairInputs form={pairForm} update={updatePair} runId={runId} prereq={prereq} ligandSdfs={ligandSdfs}
          onReloadPrereq={() => setPrereqReload(value => value + 1)} />
        <p className="mw-mutation-notice" data-testid="mutation-model-pair-units-notice">{PAIR_UNITS_NOTICE}</p>
        <label className="mw-mutation-check"><input type="checkbox" data-testid="mutation-model-pair-units"
          checked={unitsConfirmed} onChange={event => setUnitsConfirmed(event.target.checked)} />
          도킹 작업 두 개, 합쳐서 비싼 계산 두 단위임을 확인했습니다.</label>
        {!pairCheck.ok && <ul className="mw-mutation-errors" data-testid="mutation-model-pair-errors">
          {pairCheck.errors.map(error => <li key={error}>{error}</li>)}</ul>}
        <div className="mw-mutation-inline">
          <Button size="sm" variant="primary" data-testid="mutation-model-pair-submit" disabled={!!pairBlocked}
            title={pairBlocked ?? undefined} onClick={() => void submitPair()}>같은 조건 도킹 제출 (작업 두 개)</Button>
          {pairBlocked && <span className="mw-mutation-note" data-testid="mutation-model-pair-blocked">{pairBlocked}</span>}
        </div>
        {pairSubmitted && <div className="mw-mutation-group" data-testid="mutation-model-pair-jobs">
          {STRUCTURE_SIDES.map(side => {
            const entry = pairJobs[side];
            return <div key={side} data-testid={`mutation-model-pair-job-${side}`} data-side={side}
              data-submit-status={submission[side].status} data-job-status={entry?.status ?? undefined}
              data-job-id={entry?.job_id ?? undefined}>
              <p className="mw-mutation-note mw-mono">{pairSubmitText(submission[side])}</p>
              {entry && <p className="mw-mutation-note" role="status">
                {pairJobText(side, entry, pairApproval && entry.status === "queued")}</p>}
              {pairStartError[side] && <ErrorLine message={`${SIDE_LABEL[side]}: ${pairStartError[side]}`}
                testId={`mutation-model-pair-error-${side}`} />}
              {entry && dockingJobActive(entry) && <Button size="sm" data-testid={`mutation-model-pair-cancel-${side}`}
                disabled={!dockingCancelEnabled({ job: entry, cancelling: pairCancelling })}
                onClick={() => void cancelPair(side)}>{SIDE_LABEL[side]} 작업 취소</Button>}
            </div>;
          })}
          <div className="mw-mutation-inline">
            {pairApproval && <Button size="sm" data-testid="mutation-model-pair-approve" disabled={pairBusy}
              onClick={() => void approvePair()}>비싼 계산 승인</Button>}
            {!pairApproval && pairQueued && !pairRunning && <Button size="sm" data-testid="mutation-model-pair-continue"
              disabled={pairBusy || run.dry_run} onClick={() => void continuePair()}>남은 작업 차례로 시작</Button>}
          </div>
          {pairNotice && <p role="status" className="mw-mutation-note" data-testid="mutation-model-pair-notice">{pairNotice}</p>}
        </div>}

        <div className="mw-mutation-group" aria-label="같은 조건 도킹 짝">
          <span className="mw-eyebrow">같은 조건 도킹 짝</span>
          <p className="mw-mutation-note">{PAIR_SCORE_NOTE}</p>
          {pairState.state === "loading" && <p className="mw-mutation-note" aria-busy="true">짝 목록을 읽는 중</p>}
          {pairState.state === "failed" && <ErrorLine message={pairState.message} testId="mutation-model-pairs-error"
            onRetry={() => setPairsReload(value => value + 1)} />}
          {pairState.state === "empty" && <p className="mw-mutation-note" data-testid="mutation-model-pairs-empty">{pairState.message}</p>}
          {pairState.state === "ready" && pairsLoad?.status === "ready" && <PairTable pairs={pairsLoad.value} />}
          {pairsLoad?.status !== "loading" && <Button size="sm" data-testid="mutation-model-pairs-refresh"
            onClick={() => setPairsReload(value => value + 1)}>짝 목록 다시 읽기</Button>}
        </div>
      </>}
    </Section>}
  </section>;
}

const APPROVED_NOTICE = "승인을 기록했습니다. 작업 시작을 누르면 실제 계산이 실행됩니다.";
const PAIR_APPROVED_NOTICE = "승인을 기록했습니다. \"남은 작업 차례로 시작\"을 누르면 저장된 도킹 작업을 하나씩 시작합니다.";

function ModelSummary({ detail, runId }: { detail: MutationModelDetail; runId: string }) {
  const result = detail.result;
  const rows = sideBySideRows(result);
  const protonation = protonationRows(result);
  return <div className="mw-mutation-group" data-testid="mutation-model-detail" data-model-handle={detail.handle}
    data-run={runId}>
    <p className="mw-mono" data-testid="mutation-model-summary">{mutationSummaryText(result.candidate)}</p>
    <p className="mw-mutation-note mw-mono">모델 {shortHandle(detail.handle)} · 구조 {shortHandle(result.structure.handle)}
      {" "}({result.structure.structure_kind}, 모델 {result.structure.model_number}) · {result.method_version} · seed{" "}
      {result.parameters.seed} · {result.parameters.selection_policy} · {result.parameters.hydrogen_policy}</p>
    <p className="mw-mutation-note">{SIDE_BY_SIDE_NOTE}</p>
    <div className="mw-mutation-table-wrap"><table className="mw-mutation-table" data-testid="mutation-model-side-by-side">
      <thead><tr><th>항목</th>{STRUCTURE_SIDES.map(side => <th key={side} data-side={side}>{SIDE_LABEL[side]}</th>)}</tr></thead>
      <tbody>{rows.map(row => <tr key={row.key} data-row-key={row.key}>
        <td>{row.label}</td>
        {STRUCTURE_SIDES.map(side => <td key={side} className="mw-mono" data-side={side}>{row.values[side]}</td>)}
      </tr>)}</tbody>
    </table></div>

    <span className="mw-eyebrow">이황화 결합 (거리 기준, 잔기 쌍)</span>
    <ul className="mw-mutation-list" data-testid="mutation-model-disulfides">
      {STRUCTURE_SIDES.map(side => <li key={side} data-side={side} data-count={result.structures[side].disulfide_bonds.length}>
        {SIDE_LABEL[side]}: <span className="mw-mono">{disulfideText(result.structures[side].disulfide_bonds)}</span></li>)}
      <li data-testid="mutation-model-new-disulfide" data-value={result.comparison.new_disulfide_in_mutant}>
        야생형 기준에 없는 이황화 결합이 변이형에 있음: {result.comparison.new_disulfide_in_mutant ? "예" : "아니오"} (저장값)</li>
    </ul>

    <span className="mw-eyebrow">변이 잔기 밖에서 두 구조의 히스티딘·시스테인 변형 이름이 다르게 지정된 잔기</span>
    {!protonation.length
      ? <p className="mw-mutation-note" data-testid="mutation-model-protonation-none"
        data-count={result.comparison.protonation_difference_count}>해당 잔기 {result.comparison.protonation_difference_count}개 (두 구조에서 각각 pH 7.0으로 자동 지정한 저장값)</p>
      : <div className="mw-mutation-table-wrap"><table className="mw-mutation-table" data-testid="mutation-model-protonation"
        data-count={result.comparison.protonation_difference_count}>
        <thead><tr><th>잔기</th><th>잔기 7필드</th>{STRUCTURE_SIDES.map(side => <th key={side}>{SIDE_LABEL[side]}</th>)}</tr></thead>
        <tbody>{protonation.map(row => <tr key={row.fields}>
          <td className="mw-mono">{row.residue}</td><td className="mw-mono">{row.fields}</td>
          {STRUCTURE_SIDES.map(side => <td key={side} className="mw-mono">{row.values[side]}</td>)}
        </tr>)}</tbody>
      </table></div>}

    {result.excluded_components.length > 0 && <p className="mw-mutation-note" data-testid="mutation-model-excluded">
      제외 성분 (M7 규칙): {result.excluded_components.map(item =>
        `${item.reason} 잔기 ${item.residue_count}개·원자 ${item.atom_count}개`).join(" · ")}</p>}
  </div>;
}

function ContactTable({ page, onPage }: { page: MutationModelContactPage; onPage: (page: number) => void }) {
  const pages = contactPageCount(page.total, page.page_size);
  return <div data-testid="mutation-model-contacts" data-side={page.structure} data-total={page.total} data-page={page.page}>
    <p className="mw-mutation-note" data-testid="mutation-model-contacts-count">{contactPageText(page)}</p>
    {page.rows.length > 0 && <div className="mw-mutation-table-wrap"><table className="mw-mutation-table"
      data-testid="mutation-model-contacts-table">
      <thead><tr>{CONTACT_TABLE_HEADERS.map(header => <th key={header}>{header}</th>)}</tr></thead>
      <tbody>{page.rows.map(row => <tr key={row.index} data-contact-index={row.index} data-distance={row.distance_A}>
        {contactRowCells(row).map((cell, i) => <td key={i} className="mw-mono">{cell}</td>)}
      </tr>)}</tbody>
    </table></div>}
    {page.total > page.page_size && <div className="mw-mutation-inline" data-testid="mutation-model-contacts-pager">
      <span className="mw-mutation-note">페이지 {page.page} / {pages}</span>
      <Button size="sm" data-testid="mutation-model-contacts-prev" disabled={page.page <= 1}
        onClick={() => onPage(page.page - 1)}>이전</Button>
      <Button size="sm" data-testid="mutation-model-contacts-next" disabled={page.page >= pages}
        onClick={() => onPage(page.page + 1)}>다음</Button>
    </div>}
  </div>;
}

/**
 * Ligand, box, value and acknowledgement inputs of a docking on a mutation-model receptor (3D SDF only, free docking,
 * no instance-range box). Exported for the M23 sequence GA area, which passes its own test-id prefix, radio-group
 * names, ligand-source reason and labels; with the defaults this area renders exactly as before.
 */
export function PairInputs({ form, update, runId, prereq, ligandSdfs, onReloadPrereq,
  idPrefix = "mutation-model-pair", ligandSourceReason = pairLigandSourceDisabledReason, seedLabel,
  acknowledgementLegend = "제출 전 확인 (세 항목 모두, 두 작업에 같이 적용)" }: { form: PairDockingForm;
  update: (patch: Partial<PairDockingForm>) => void; runId: string; prereq: Load<DockingPrerequisites>;
  ligandSdfs: DockingPrerequisites["imports"]; onReloadPrereq: () => void; idPrefix?: string;
  ligandSourceReason?: (source: string) => string | null; seedLabel?: string; acknowledgementLegend?: string }) {
  return <div className="mw-mutation-group" data-testid={`${idPrefix}-form`}>
    <span className="mw-eyebrow">리간드 출처</span>
    {prereq.status === "loading" && <p className="mw-mutation-note" aria-busy="true">도킹 입력 목록을 읽는 중</p>}
    {prereq.status === "error" && <ErrorLine message={prereq.message} onRetry={onReloadPrereq} />}
    <div className="mw-mutation-inline">
      <Button size="sm" data-testid={`${idPrefix}-prereq-refresh`} disabled={prereq.status === "loading"}
        onClick={onReloadPrereq}>도킹 입력 목록 다시 읽기</Button>
      <span className="mw-mutation-note">리간드 3D SDF 가져오기는 리간드 설계·탐색 탭에서 만듭니다.</span>
    </div>
    <fieldset className="mw-mutation-choices" data-testid={`${idPrefix}-ligand-source`}>
      <legend>출처 (한 번에 하나, 자동으로 고르지 않음)</legend>
      {LIGAND_SOURCES.map(source => {
        const reason = ligandSourceReason(source);
        return <label key={source} data-pair-ligand-source={source} data-disabled-reason={reason ?? undefined}>
          <input type="radio" name={`${idPrefix}-source-${runId}`} checked={form.ligandSource === source}
            disabled={!!reason} onChange={() => update({ ligandSource: source })} /> {LIGAND_SOURCE_LABEL[source]}
          {reason && <span className="mw-mutation-note">{reason}</span>}</label>;
      })}
    </fieldset>
    {form.ligandSource === "sdf" && <label className="mw-mutation-check">리간드 SDF 가져오기
      <select className="mw-select" data-testid={`${idPrefix}-sdf`} value={form.sdfHandle ?? ""}
        onChange={event => update({ sdfHandle: event.target.value || null })}>
        <option value="">선택</option>
        {ligandSdfs.map(row => <option key={row.handle} value={row.handle}>
          {`생성 순번 ${row.created_seq} · ${row.size} B · ${shortHandle(row.handle)}`}</option>)}
      </select></label>}
    {form.ligandSource === "sdf" && prereq.status === "ready" && !ligandSdfs.length &&
      <p className="mw-mutation-note">가져온 리간드 SDF가 없습니다.</p>}

    <span className="mw-eyebrow">상자</span>
    <p className="mw-mutation-note" data-testid={`${idPrefix}-frame-note`}>{BOX_FRAME_NOTE}</p>
    <fieldset className="mw-mutation-choices" data-testid={`${idPrefix}-box-source`}>
      <legend>상자 출처 (자동으로 고르지 않음)</legend>
      {BOX_SOURCES.map((source: DockingBoxSource) => {
        const reason = pairBoxSourceDisabledReason(source);
        return <label key={source} data-pair-box={source} data-disabled-reason={reason ?? undefined}>
          <input type="radio" name={`${idPrefix}-box-${runId}`} checked={form.boxSource === source}
            disabled={!!reason || !(PAIR_BOX_SOURCES as readonly string[]).includes(source)}
            onChange={() => update({ boxSource: source })} /> {boxSourceLabel(source)}
          {reason && <span className="mw-mutation-note">{reason}</span>}</label>;
      })}
    </fieldset>
    {form.boxSource === "ligand_range" && <label className="mw-mutation-check">여백 (Å, {MARGIN_MIN_A}–{MARGIN_MAX_A})
      <input className="mw-mutation-input" data-testid={`${idPrefix}-margin`} inputMode="decimal" value={form.margin}
        onChange={event => update({ margin: event.target.value })} /></label>}
    {form.boxSource === "manual" && <div className="mw-mutation-inline" data-testid={`${idPrefix}-manual-box`}>
      {AXES.map((axis, i) => <label key={`c${axis}`} className="mw-mutation-check">중심 {axis} (Å)
        <input className="mw-mutation-input" data-testid={`${idPrefix}-center-${axis}`} inputMode="decimal"
          value={form.center[i]} onChange={event => update({ center: form.center.map((value, j) => j === i
            ? event.target.value : value) as PairDockingForm["center"] })} /></label>)}
      {AXES.map((axis, i) => <label key={`s${axis}`} className="mw-mutation-check">크기 {axis} (Å, {BOX_SIDE_MIN_A}–{BOX_SIDE_MAX_A})
        <input className="mw-mutation-input" data-testid={`${idPrefix}-size-${axis}`} inputMode="decimal"
          value={form.size[i]} onChange={event => update({ size: form.size.map((value, j) => j === i
            ? event.target.value : value) as PairDockingForm["size"] })} /></label>)}
    </div>}

    <span className="mw-eyebrow">값과 확인</span>
    <div className="mw-mutation-inline">
      <label className="mw-mutation-check">{seedLabel ?? <>seed (필수, {SEED_MIN}–{SEED_MAX})</>}
        <input className="mw-mutation-input" data-testid={`${idPrefix}-seed`} inputMode="numeric" value={form.seed}
          onChange={event => update({ seed: event.target.value })} /></label>
      <label className="mw-mutation-check">exhaustiveness ({EXHAUSTIVENESS_MIN}–{EXHAUSTIVENESS_MAX})
        <input className="mw-mutation-input" data-testid={`${idPrefix}-exhaustiveness`} inputMode="numeric"
          value={form.exhaustiveness} onChange={event => update({ exhaustiveness: event.target.value })} /></label>
      <label className="mw-mutation-check">num_modes ({NUM_MODES_MIN}–{NUM_MODES_MAX})
        <input className="mw-mutation-input" data-testid={`${idPrefix}-num-modes`} inputMode="numeric"
          value={form.numModes} onChange={event => update({ numModes: event.target.value })} /></label>
      <label className="mw-mutation-check">energy_range (kcal/mol, {ENERGY_RANGE_MIN}–{ENERGY_RANGE_MAX})
        <input className="mw-mutation-input" data-testid={`${idPrefix}-energy-range`} inputMode="decimal"
          value={form.energyRange} onChange={event => update({ energyRange: event.target.value })} /></label>
    </div>
    <p className="mw-mutation-note">cpu는 1로 고정됩니다.</p>
    <fieldset className="mw-mutation-choices" data-testid={`${idPrefix}-acknowledgement`}>
      <legend>{acknowledgementLegend}</legend>
      {ACKNOWLEDGEMENT_KEYS.map((key: DockingAcknowledgementKey) => <label key={key} data-pair-ack={key}>
        <input type="checkbox" checked={form.acknowledgement[key]}
          onChange={event => update({ acknowledgement: { ...form.acknowledgement, [key]: event.target.checked } })} />
        {ACKNOWLEDGEMENT_LABEL[key]}</label>)}
    </fieldset>
  </div>;
}

function PairTable({ pairs }: { pairs: MutationModelDockingPairs }) {
  const headers = pairTableHeaders(pairs.score_label);
  return <div className="mw-mutation-table-wrap"><table className="mw-mutation-table" data-testid="mutation-model-pairs"
    data-total={pairs.total}>
    <thead><tr>{headers.map(header => <th key={header}>{header}</th>)}</tr></thead>
    <tbody>{pairRows(pairs).map(row => <tr key={row.index} data-pair-index={row.index}
      data-pair-loop={row.loopText === null ? undefined : "true"}>
      <td className="mw-mono">{row.index}</td>
      <td className="mw-mono">{row.condition}{row.loopText !== null && <><br /><span className="mw-mutation-note"
        data-testid="mutation-model-pair-loop">{row.loopText}</span></>}</td>
      {STRUCTURE_SIDES.map(side => {
        const cell = row.cells[side];
        return <td key={side} data-side={side} data-has-score={cell.score !== null}
          data-result-handle={cell.resultHandle ?? undefined}>
          <span className="mw-mono">{cell.text}</span><br /><span className="mw-mutation-note">작업: {cell.job}</span></td>;
      })}
    </tr>)}</tbody>
  </table></div>;
}
