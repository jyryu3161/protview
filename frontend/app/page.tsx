"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BudgetMeter, Button, HandleChip, InspectorSection, InteractionTable, MolstarViewer,
  Segmented, StepList, WorkspaceShell, type Step, type ViewerRepresentation,
} from "@/components";
import { api, displayedEgressMode, type Capabilities, type MethodReportArtifact, type ObjectMeta, type OpenmmJob, type OpenmmResult, type OpenmmReportArtifact, type ReportArtifact, type ResidueList, type RunSummary, type SasaResult, type SavedReportRef, type UploadResult } from "@/lib/api";
import type { BudgetSnapshot, Handle, InteractionRow, ResidueRef, RunEvent } from "@/lib/contracts";
import { latestHandles, resultEvents, resultId, type CacheEvent } from "@/lib/event-model";
import { formatArea2 as area2 } from "@/lib/area-format";
import { currentOpenmmAction, currentOpenmmBudgetRequest, formatEnergy2, openmmContextChange, selectedOpenmmReadError,
  type OpenmmActionIdentity, type OpenmmContext } from "@/lib/openmm-action";
import { reportSelectionKey, responseMatchesMethodSelection, responseMatchesOpenmmSelection, responseMatchesSelection, savedForSelection, savedMethodForSelection, savedOpenmmForSelection } from "@/lib/report-selection";
import type { ViewerSource } from "@/components/MolstarViewer";
import type { ViewerBridge } from "@/components/MolstarViewer";
import { ViewerAgentPanel } from "@/components/ViewerAgentPanel";
import { advanceSceneGeneration } from "@/lib/viewer-scene";

type Handles = { loaded?: Handle; prepared?: Handle; interactions?: Handle; sasa?: Handle };
type UploadInfo = Pick<UploadResult, "upload_id" | "format" | "size"> & { model_numbers?: number[] };
type RowsState =
  | { key: string; status: "ready"; rows: InteractionRow[]; total: number }
  | { key: string; status: "error"; message: string };
type MetaState = { key: string; status: "ready"; meta: ObjectMeta } | { key: string; status: "error"; message: string };
type StructureData = { key: string; source: ViewerSource; residues: ResidueList; kind: "structure" | "prepared_structure" | "openmm_minimized_structure" };
type StructureState = { key: string; status: "ready"; data: StructureData } | { key: string; status: "error"; message: string };
type ViewerState = { key: string; source: ViewerSource; status: "loading" | "ready" | "error"; message?: string };
type ViewIntent = "latest_result" | "latest_pipeline" | "step";
type PipelineResidues = { key: string; residues: ResidueList };
type ReportState = { key: string; status: "pending" } | { key: string; status: "ready"; artifact: ReportArtifact } |
  { key: string; status: "error"; message: string };
type SasaState = { key: string; status: "ready"; result: SasaResult } | { key: string; status: "error"; message: string };
type MethodReportState = { key: string; status: "pending" } | { key: string; status: "ready"; artifact: MethodReportArtifact } |
  { key: string; status: "error"; message: string };
const contactTypes = ["contact", "polar_contact", "hydrophobic_contact"] as const;

function identity(ref: ResidueRef) {
  return [ref.model_number ?? "", ref.chain_auth, ref.chain_label ?? "", ref.seq_auth, ref.seq_label ?? "", ref.icode ?? "", ref.resname].join("/");
}
function displayResidue(ref: ResidueRef) {
  return `${ref.resname} auth ${ref.chain_auth}/${ref.seq_auth}${ref.icode || ""}` +
    ` · label ${ref.chain_label ?? "unknown"}/${ref.seq_label ?? "unknown"} · model ${ref.model_number ?? "unknown"}`;
}
function timeline(events: RunEvent[]): Step[] {
  const validCache = new Set(resultEvents(events).filter((event): event is CacheEvent => event.type === "cache_hit"));
  const actions = events.filter((e): e is Extract<RunEvent, { type: "tool_called" | "tool_succeeded" | "cache_hit" }> =>
    e.type === "tool_called" || (e.type === "cache_hit" && validCache.has(e)) ||
    (e.type === "tool_succeeded" && !!e.cached));
  return actions.map((event, i) => {
    const outcome = event.type === "tool_called" ? events.find(e =>
      (e.type === "tool_succeeded" || e.type === "tool_failed" || e.type === "tool_interrupted") &&
      "call_id" in e && e.call_id === event.call_id && e.seq > event.seq) : event;
    const success = outcome?.type === "tool_succeeded" || outcome?.type === "cache_hit" ? outcome : null;
    return {
      n: i + 1, tool: event.tool, callId: event.type === "tool_called" ? event.call_id : resultId(event),
      decidedBy: event.type === "tool_called" ? event.decided_by : undefined,
      state: outcome?.type === "tool_failed" || outcome?.type === "tool_interrupted"
        ? "failed" : success ? "done" : "running",
      result: success?.output.null_result ? "scientific_null" : outcome?.type === "tool_failed" ? outcome.error : undefined,
      cached: event.type === "cache_hit" || (event.type === "tool_succeeded" && !!event.cached),
      meta: success?.type === "tool_succeeded" && !success.cached && success.duration_s != null
        ? `${success.duration_s.toFixed(2)}s` : undefined,
      sub: success?.output ? <HandleChip handle={success.output} />
        : outcome?.type === "tool_interrupted" ? "interrupted" : undefined,
    };
  });
}

export default function WorkspacePage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [run, setRun] = useState<RunSummary | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [budget, setBudget] = useState<BudgetSnapshot | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [handles, setHandles] = useState<Handles>({});
  const [pipelineResidues, setPipelineResidues] = useState<PipelineResidues | null>(null);
  const [inspectedStructure, setInspectedStructure] = useState<StructureState | null>(null);
  const [viewerState, setViewerState] = useState<ViewerState | null>(null);
  const [upload, setUpload] = useState<UploadInfo | null>(null);
  const [modelIndex, setModelIndex] = useState(0);
  const [altloc, setAltloc] = useState<"highest_occupancy" | "first">("highest_occupancy");
  const [waters, setWaters] = useState<"strip_all" | "keep_all">("strip_all");
  const [hydrogens, setHydrogens] = useState<"strip" | "keep">("strip");
  const [ligandIndex, setLigandIndex] = useState("");
  const [cutoff, setCutoff] = useState(4.0);
  const [representation, setRepresentation] = useState<ViewerRepresentation>("cartoon");
  const [viewerScopeRevision, setViewerScopeRevision] = useState(0);
  const [highlight, setHighlight] = useState<{ key: string; residue: ResidueRef } | null>(null);
  const [focusedResidue, setFocusedResidue] = useState<{ key: string; residue: ResidueRef } | null>(null);
  const [focusError, setFocusError] = useState<{ key: string; message: string } | null>(null);
  const [rowsState, setRowsState] = useState<RowsState | null>(null);
  const [rowsRetry, setRowsRetry] = useState(0);
  const [offset, setOffset] = useState(0);
  const [viewIntent, setViewIntent] = useState<ViewIntent>("latest_result");
  const [selectedStepNumber, setSelectedStepNumber] = useState<number | null>(null);
  const [inspectionRevision, setInspectionRevision] = useState(0);
  const [metaState, setMetaState] = useState<MetaState | null>(null);
  const [busy, setBusy] = useState("서버 연결 중…");
  const [error, setError] = useState("");
  const [savedReports, setSavedReports] = useState<SavedReportRef[]>([]);
  const [reportState, setReportState] = useState<ReportState | null>(null);
  const reportKeyRef = useRef<string | null>(null);
  const [sasaState, setSasaState] = useState<SasaState | null>(null);
  const [sasaRetry, setSasaRetry] = useState(0);
  const [methodReportState, setMethodReportState] = useState<MethodReportState | null>(null);
  const [openmmJobs, setOpenmmJobs] = useState<OpenmmJob[]>([]);
  const [openmmJobId, setOpenmmJobId] = useState<string | null>(null);
  const [openmmPreflight, setOpenmmPreflight] = useState<{ key: string; heavy_atom_count: number; excluded: { residue: ResidueRef; atom_count: number; reason: string }[] } | null>(null);
  const [proteinOnlyAccepted, setProteinOnlyAccepted] = useState(false);
  const [hydrogenAccepted, setHydrogenAccepted] = useState(false);
  const [openmmBusy, setOpenmmBusy] = useState(false);
  const [openmmError, setOpenmmError] = useState("");
  const [openmmPlan, setOpenmmPlan] = useState<{ key: string; message: string } | null>(null);
  const [openmmResultError, setOpenmmResultError] = useState<{ key: string; message: string } | null>(null);
  const [openmmReportError, setOpenmmReportError] = useState<{ key: string; message: string } | null>(null);
  const [openmmResult, setOpenmmResult] = useState<{ key: string; value: OpenmmResult } | null>(null);
  const [openmmReport, setOpenmmReport] = useState<{ key: string; artifact: OpenmmReportArtifact } | null>(null);
  const [openmmViewHandle, setOpenmmViewHandle] = useState<string | null>(null);
  const [openmmReadRetry, setOpenmmReadRetry] = useState(0);
  const [openmmReportRetry, setOpenmmReportRetry] = useState(0);
  const openmmActionRef = useRef(0);
  const openmmRunRef = useRef<string | null>(null);
  const openmmInputRef = useRef<string | undefined>(undefined);
  const openmmJobRef = useRef<string | null>(null);
  const openmmOutputRef = useRef<string | undefined>(undefined);
  const openmmContextRef = useRef<OpenmmContext | null>(null);
  const budgetRequestRef = useRef(0);
  const methodReportKeyRef = useRef<string | null>(null);
  const epoch = useRef(0);
  const viewerBridgeRef = useRef<ViewerBridge | null>(null);
  const manualViewerInvalidator = useRef<(() => void) | null>(null);
  const viewerClientId = useRef<string | null>(null);
  if (!viewerClientId.current && typeof window !== "undefined") viewerClientId.current = crypto.randomUUID();
  const runId = run?.run_id;
  openmmRunRef.current = runId ?? null;

  const refreshOpenmmBudget = useCallback(async (id: string, jobId: string, ticket: number) => {
    const request = ++budgetRequestRef.current;
    try {
      const snapshot = await api.budget(id);
      if (currentOpenmmBudgetRequest({ request, epoch: ticket, runId: id, jobId },
        { request: budgetRequestRef.current, epoch: epoch.current,
          runId: openmmRunRef.current, jobId: openmmJobRef.current })) setBudget(snapshot);
    } catch { /* A later poll or run reopen can retry the read. */ }
  }, []);

  const reopen = useCallback(async (id: string) => {
    const ticket = ++epoch.current;
    setError("");
    const [summary, log, limits, reports, jobs] = await Promise.all([api.run(id), api.allEvents(id), api.budget(id), api.reports(id), api.jobs(id)]);
    if (ticket !== epoch.current) return;
    const latest = latestHandles(log);
    const lastLoadSeq = [...resultEvents(log)].reverse().find(event => event.tool === "load_structure")?.seq ?? 0;
    const pendingUpload = [...log].reverse().find(event => event.type === "upload_received" && event.seq > lastLoadSeq);
    setRun(summary); setEvents(log); setBudget(limits); setHandles(latest); setSavedReports(reports); setReportState(null); setSasaState(null); setMethodReportState(null);
    setOpenmmJobs(jobs.filter(job => job.protocol_id === "openmm_protein_minimize")); setOpenmmJobId(jobs.find(job => job.protocol_id === "openmm_protein_minimize")?.job_id ?? null); setOpenmmResult(null); setOpenmmReport(null); setOpenmmPreflight(null); setOpenmmPlan(null); setOpenmmViewHandle(null);
    // A completed contact/SASA/report call can reopen the same immutable
    // prepared handle. Keep its validated residue list in that case: the
    // loading effect is keyed by run+handle and will not rerun for identical
    // inputs. A changed handle still invalidates the list and triggers fetch.
    const preparedKey = latest.prepared ? JSON.stringify([id, latest.prepared.handle]) : null;
    setPipelineResidues(previous => previous?.key === preparedKey ? previous : null);
    setInspectedStructure(null); setViewerState(null);
    setUpload(pendingUpload?.type === "upload_received" ? { upload_id: pendingUpload.upload_id, format: pendingUpload.format as UploadInfo["format"], size: pendingUpload.size } : null);
    setModelIndex(0); setViewIntent("latest_result"); setSelectedStepNumber(null); setInspectionRevision(value => value + 1); setHighlight(null); setFocusedResidue(null); setFocusError(null); setLigandIndex(""); setOffset(0);
    window.history.replaceState(null, "", `/?run=${encodeURIComponent(id)}`);
  }, []);

  useEffect(() => {
    let active = true;
    (async () => {
      setBusy("서버 연결 중…");
      try {
        const [available, list] = await Promise.all([api.capabilities(), api.runs()]);
        if (!active) return;
        setCapabilities(available); setRuns(list);
        const urlRun = new URLSearchParams(window.location.search).get("run");
        const chosen = list.find(item => item.run_id === urlRun) ?? list.at(-1);
        if (chosen) await reopen(chosen.run_id);
      } catch (e) { if (active) setError(e instanceof Error ? e.message : String(e)); }
      finally { if (active) setBusy(""); }
    })();
    return () => { active = false; epoch.current++; };
  }, [reopen]);

  const steps = useMemo(() => timeline(events), [events]);
  const selectedStep = steps.find(step => step.n === selectedStepNumber);
  const selectedOutput = [...resultEvents(events)].reverse().find(e => resultId(e) === selectedStep?.callId);
  const latestResult = [...resultEvents(events)].reverse().find(e =>
    (e.tool === "load_structure" || e.tool === "prepare_structure" || e.tool === "compute_interactions" || e.tool === "compute_interface_sasa"));
  const pipelineHandle = handles.prepared ?? handles.loaded;
  const selectedHandle = viewIntent === "step"
    ? selectedOutput?.output
    : viewIntent === "latest_pipeline" ? handles.interactions ?? pipelineHandle
      : latestResult?.output;
  const selectedTool = viewIntent === "step" ? selectedStep?.tool
    : viewIntent === "latest_pipeline" ? handles.interactions ? "compute_interactions" : handles.prepared ? "prepare_structure" : handles.loaded ? "load_structure" : undefined
      : latestResult?.tool;
  const interactionHandle = selectedTool === "compute_interactions" ? selectedHandle : undefined;
  const sasaHandle = selectedTool === "compute_interface_sasa" ? selectedHandle : undefined;
  const reportKey = reportSelectionKey(runId, interactionHandle?.handle);
  reportKeyRef.current = reportKey;
  const activeReport = reportState?.key === reportKey ? reportState : null;
  const savedReport = savedForSelection(savedReports, interactionHandle?.handle);
  const methodReportKey = reportSelectionKey(runId, sasaHandle?.handle);
  methodReportKeyRef.current = methodReportKey;
  const activeMethodReport = methodReportState?.key === methodReportKey ? methodReportState : null;
  const savedMethodReport = savedMethodForSelection(savedReports, sasaHandle?.handle);
  const sasaKey = reportSelectionKey(runId, sasaHandle?.handle);
  const activeSasa = sasaState?.key === sasaKey ? sasaState : null;
  const interactionKey = runId && interactionHandle ? JSON.stringify([runId, interactionHandle.handle, offset]) : null;
  const currentRows = rowsState?.key === interactionKey ? rowsState : null;
  const metaKey = runId && selectedHandle ? JSON.stringify([runId, selectedHandle.handle]) : null;
  const selectedMeta = metaState?.key === metaKey ? metaState : null;
  const objectMeta = selectedMeta?.status === "ready" ? selectedMeta.meta : null;
  const latestResidues = pipelineResidues?.key === (runId && handles.prepared ? JSON.stringify([runId, handles.prepared.handle]) : null)
    ? pipelineResidues.residues : null;
  const inspecting = viewIntent === "step";
  const selectedStructure = selectedHandle && (selectedTool === "load_structure" || selectedTool === "prepare_structure");
  const selectedInteraction = selectedTool === "compute_interactions" && !!selectedHandle;
  const selectedSasa = selectedTool === "compute_interface_sasa" && !!selectedHandle;
  const selectedMeasurement = selectedInteraction || selectedSasa;
  const expectedKind = openmmViewHandle ? "openmm_minimized_structure" : selectedMeasurement ? "prepared_structure" : selectedStructure
    ? selectedTool === "load_structure" ? "structure" : "prepared_structure"
    : handles.prepared ? "prepared_structure" : "structure";
  const associationError = !openmmViewHandle && selectedMeasurement && objectMeta &&
    (selectedHandle?.kind !== (selectedSasa ? "interface_sasa" : "interaction_set") || objectMeta.kind !== (selectedSasa ? "interface_sasa" : "interaction_set") ||
      objectMeta.schema !== (selectedSasa ? "interface_sasa@1" : "interaction_set@1") ||
      typeof objectMeta.summary.structure !== "string" || !objectMeta.summary.structure)
      ? "측정 객체에 확인 가능한 입력 구조가 없습니다." :
    !openmmViewHandle && selectedStructure && objectMeta && (selectedHandle?.kind !== expectedKind || objectMeta.kind !== expectedKind)
      ? "선택한 단계의 구조 종류가 객체 메타데이터와 일치하지 않습니다." : null;
  const targetHandle = openmmViewHandle ?? (selectedMeasurement
    ? !associationError && objectMeta ? String(objectMeta.summary.structure) : null
    : selectedStructure ? !associationError && objectMeta ? objectMeta.handle : null
      : pipelineHandle?.handle ?? null);
  const targetKey = runId && targetHandle ? JSON.stringify([runId, targetHandle, inspectionRevision]) : null;
  const viewerContextKey = targetKey ? JSON.stringify([targetKey, viewIntent, selectedStep?.callId ?? null]) : null;
  const sceneToken = useRef<{ key: string | null; generation: number }>({ key: null, generation: 0 });
  sceneToken.current = advanceSceneGeneration(sceneToken.current,
    JSON.stringify([viewerContextKey, viewerScopeRevision]));
  const displayData = inspectedStructure?.key === targetKey && inspectedStructure.status === "ready" ? inspectedStructure.data : null;
  const displaySource = displayData?.source ?? null;
  const displayResidues = displayData?.residues ?? null;
  const viewerReady = !!viewerContextKey && viewerState?.key === viewerContextKey &&
    viewerState.status === "ready" && viewerState.source === displaySource;
  const focusEnabled = viewerReady && !busy && !openmmViewHandle;
  const selectedFocus = viewerReady && focusedResidue?.key === viewerContextKey ? focusedResidue.residue : null;
  const displayedError = associationError ?? (selectedMeta?.status === "error" && (selectedMeasurement || selectedStructure)
    ? `선택한 객체의 메타데이터를 읽지 못했습니다: ${selectedMeta.message}` : null) ??
    (targetKey && inspectedStructure?.key === targetKey && inspectedStructure.status === "error" ? inspectedStructure.message : null) ??
    (viewerContextKey && viewerState?.key === viewerContextKey && viewerState.status === "error" ? viewerState.message : null);
  const activeOpenmmJob = openmmJobs.find(job => job.job_id === openmmJobId) ?? null;
  const openmmOutput = activeOpenmmJob?.status === "done" ? activeOpenmmJob.output_handles[0] : undefined;
  const openmmResultKey = reportSelectionKey(runId, openmmOutput);
  const selectedOpenmmResult = openmmResult?.key === openmmResultKey ? openmmResult.value : null;
  const savedOpenmmReport = savedOpenmmForSelection(savedReports, openmmOutput);
  const selectedOpenmmReport = openmmReport?.key === openmmResultKey ? openmmReport.artifact : null;
  const openmmReportErrorKey = JSON.stringify([openmmResultKey, savedOpenmmReport?.handle ?? null]);
  const activeOpenmmResultError = selectedOpenmmReadError(openmmResultError, openmmResultKey);
  const activeOpenmmReportError = selectedOpenmmReadError(openmmReportError, openmmReportErrorKey);
  const openmmInput = displayData?.kind === "prepared_structure" ? displayData.source.handle : handles.prepared?.handle;
  openmmInputRef.current = openmmInput;
  openmmJobRef.current = openmmJobId;
  openmmOutputRef.current = openmmOutput;
  function actionIdentity(): OpenmmActionIdentity {
    setOpenmmBusy(false);
    return { epoch: epoch.current, runId: openmmRunRef.current, input: openmmInputRef.current,
      jobId: openmmJobRef.current, result: openmmOutputRef.current, action: ++openmmActionRef.current };
  }
  function actionCurrent(request: OpenmmActionIdentity): boolean {
    return currentOpenmmAction(request, { epoch: epoch.current, runId: openmmRunRef.current,
      input: openmmInputRef.current, jobId: openmmJobRef.current,
      result: openmmOutputRef.current, action: openmmActionRef.current });
  }
  useEffect(() => { setOpenmmBusy(false); }, [runId, openmmInput, openmmJobId, openmmOutput]);
  useEffect(() => {
    const change = openmmContextChange(openmmContextRef.current, { runId, input: openmmInput, jobId: openmmJobId });
    if (change.resetPolicy) {
      setProteinOnlyAccepted(false);
      setHydrogenAccepted(false);
    }
    if (change.resetErrors)
      setOpenmmError("");
    if (change.resetErrors) {
      setOpenmmResultError(null);
      setOpenmmReportError(null);
      setOpenmmPlan(null);
    }
    openmmContextRef.current = { runId, input: openmmInput, jobId: openmmJobId };
  }, [runId, openmmInput, openmmJobId]);
  const openmmPreflightKey = reportSelectionKey(runId, openmmInput);
  const activeOpenmmPreflight = openmmPreflight?.key === openmmPreflightKey ? openmmPreflight : null;
  const displayDiffersFromPipeline = !!selectedHandle && !!targetHandle && targetHandle !== pipelineHandle?.handle;
  const mutationDisabled = !!busy || inspecting || (!!selectedHandle && (!targetHandle || displayDiffersFromPipeline));

  useEffect(() => {
    if (!runId || !reportKey || !savedReport) return;
    let active = true;
    setReportState({ key: reportKey, status: "pending" });
    api.report(runId, savedReport.handle).then(artifact => {
      if (!active) return;
      if (!responseMatchesSelection(reportKey, reportKeyRef.current, runId, interactionHandle!.handle, artifact)) {
        setReportState({ key: reportKey, status: "error", message: "저장된 보고서가 선택한 측정 객체와 일치하지 않습니다." });
        return;
      }
      setReportState({ key: reportKey, status: "ready", artifact });
    }).catch(e => { if (active) setReportState({ key: reportKey, status: "error", message: e instanceof Error ? e.message : String(e) }); });
    return () => { active = false; };
  }, [runId, reportKey, savedReport?.handle, interactionHandle?.handle]);

  useEffect(() => {
    if (!runId || !sasaHandle || !sasaKey) return;
    let active = true;
    setSasaState(null);
    api.sasa(runId, sasaHandle.handle).then(response => {
      if (!active) return;
      if (response.meta.handle !== sasaHandle.handle || response.meta.kind !== "interface_sasa" ||
          response.meta.schema !== "interface_sasa@1" || response.result.schema !== "interface_sasa@1" ||
          response.result.structure !== response.meta.summary.structure ||
          JSON.stringify(response.result.ligand) !== JSON.stringify(response.meta.summary.ligand)) {
        setSasaState({ key: sasaKey, status: "error", message: "SASA 응답이 선택한 결과와 일치하지 않습니다." });
        return;
      }
      setSasaState({ key: sasaKey, status: "ready", result: response.result });
    }).catch(e => { if (active) setSasaState({ key: sasaKey, status: "error", message: e instanceof Error ? e.message : String(e) }); });
    return () => { active = false; };
  }, [runId, sasaHandle?.handle, sasaKey, sasaRetry]);

  useEffect(() => {
    if (!runId || !methodReportKey || !savedMethodReport || !sasaHandle) return;
    let active = true;
    setMethodReportState({ key: methodReportKey, status: "pending" });
    api.methodReport(runId, savedMethodReport.handle).then(artifact => {
      if (!active) return;
      if (!responseMatchesMethodSelection(methodReportKey, methodReportKeyRef.current, runId, sasaHandle.handle, artifact))
        setMethodReportState({ key: methodReportKey, status: "error", message: "저장된 방법 보고서가 선택한 결과와 일치하지 않습니다." });
      else setMethodReportState({ key: methodReportKey, status: "ready", artifact });
    }).catch(e => { if (active) setMethodReportState({ key: methodReportKey, status: "error", message: e instanceof Error ? e.message : String(e) }); });
    return () => { active = false; };
  }, [runId, methodReportKey, savedMethodReport?.handle, sasaHandle?.handle]);

  async function createSelectedMethodReport() {
    if (!runId || !sasaHandle || !methodReportKey || activeMethodReport?.status === "pending") return;
    const key = methodReportKey;
    const selected = sasaHandle.handle;
    const ticket = epoch.current;
    setMethodReportState({ key, status: "pending" });
    try {
      const artifact = savedMethodReport ? await api.methodReport(runId, savedMethodReport.handle)
        : await api.createMethodReport(runId, selected);
      if (ticket !== epoch.current || methodReportKeyRef.current !== key) return;
      if (!responseMatchesMethodSelection(key, methodReportKeyRef.current, runId, selected, artifact))
        throw new Error("방법 보고서가 선택한 결과와 일치하지 않습니다.");
      setMethodReportState({ key, status: "ready", artifact });
      if (!savedMethodReport) {
        const refreshed = await api.reports(runId);
        if (ticket === epoch.current && methodReportKeyRef.current === key) setSavedReports(refreshed);
      }
    } catch (e) {
      if (ticket === epoch.current && methodReportKeyRef.current === key)
        setMethodReportState({ key, status: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }

  async function createSelectedReport() {
    if (!runId || !interactionHandle || !reportKey || activeReport?.status === "pending") return;
    const key = reportKey;
    const selected = interactionHandle.handle;
    const ticket = epoch.current;
    setReportState({ key, status: "pending" });
    try {
      const artifact = savedReport ? await api.report(runId, savedReport.handle) : await api.createReport(runId, selected);
      if (ticket !== epoch.current || reportKeyRef.current !== key) return;
      if (!responseMatchesSelection(key, reportKeyRef.current, runId, selected, artifact))
        throw new Error("보고서가 선택한 측정 객체와 일치하지 않습니다.");
      setReportState({ key, status: "ready", artifact });
      if (!savedReport) {
        const refreshed = await api.reports(runId);
        if (ticket === epoch.current && reportKeyRef.current === key) setSavedReports(refreshed);
      }
    } catch (e) {
      if (ticket === epoch.current && reportKeyRef.current === key)
        setReportState({ key, status: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }

  useEffect(() => {
    if (!runId || !interactionHandle || !interactionKey) return;
    let active = true;
    setRowsState(null);
    api.interactions(runId, interactionHandle.handle, offset).then(page => {
      if (!active) return;
      if (page.meta.handle !== interactionHandle.handle || page.meta.kind !== "interaction_set" ||
          !Number.isInteger(page.total) || page.total < 0 || page.meta.null_result !== (page.total === 0) ||
          (page.total > 0 && page.rows.length === 0)) {
        setRowsState({ key: interactionKey, status: "error", message: "측정 행 응답이 선택한 객체와 일치하지 않습니다." });
        return;
      }
      setRowsState({ key: interactionKey, status: "ready", rows: page.rows, total: page.total });
    }).catch(e => { if (active) setRowsState({ key: interactionKey, status: "error", message: e instanceof Error ? e.message : String(e) }); });
    return () => { active = false; };
  }, [runId, interactionHandle?.handle, interactionKey, offset, rowsRetry]);

  useEffect(() => {
    if (!runId || !selectedHandle || !metaKey) return;
    let active = true;
    setMetaState(null);
    api.meta(runId, selectedHandle.handle).then(meta => {
      if (!active) return;
      setMetaState(meta.handle === selectedHandle.handle
        ? { key: metaKey, status: "ready", meta }
        : { key: metaKey, status: "error", message: "객체 메타데이터의 handle이 선택한 객체와 다릅니다." });
    }).catch(e => { if (active) setMetaState({ key: metaKey, status: "error", message: e instanceof Error ? e.message : String(e) }); });
    return () => { active = false; };
  }, [runId, selectedHandle?.handle, metaKey, inspectionRevision]);

  useEffect(() => {
    if (!runId || !targetHandle || !targetKey) return;
    let active = true;
    setInspectedStructure(null);
    (async () => {
      try {
        const meta = await api.meta(runId, targetHandle);
        if (meta.handle !== targetHandle || meta.kind !== expectedKind) throw new Error("입력 구조의 handle 또는 종류가 측정 기록과 일치하지 않습니다.");
        const [source, residues] = await Promise.all([api.structure(runId, targetHandle), api.residues(runId, targetHandle)]);
        if (source.handle !== targetHandle) throw new Error("구조 바이트의 handle이 측정 기록과 일치하지 않습니다.");
        if (active) setInspectedStructure({ key: targetKey, status: "ready", data: { key: targetKey, source, residues, kind: expectedKind } });
      } catch (e) {
        if (active) setInspectedStructure({ key: targetKey, status: "error", message: `선택한 구조를 불러오지 못했습니다: ${e instanceof Error ? e.message : String(e)}` });
      }
    })();
    return () => { active = false; };
  }, [runId, targetHandle, targetKey, expectedKind]);

  useEffect(() => {
    if (!runId || !handles.prepared) return;
    const handle = handles.prepared.handle;
    const key = JSON.stringify([runId, handle]);
    let active = true;
    setPipelineResidues(null);
    Promise.all([api.meta(runId, handle), api.residues(runId, handle)]).then(([meta, residues]) => {
      if (active && meta.handle === handle && meta.kind === "prepared_structure") setPipelineResidues({ key, residues });
    }).catch(() => { if (active) setPipelineResidues(null); });
    return () => { active = false; };
  }, [runId, handles.prepared?.handle]);

  useEffect(() => {
    if (!runId || !openmmJobId) return;
    let active = true;
    const ticket = epoch.current;
    let observedStatus: string | null = null;
    const poll = async () => {
      try {
        const job = await api.job(runId, openmmJobId);
        if (active && ticket === epoch.current && openmmRunRef.current === runId &&
            openmmJobRef.current === openmmJobId && job.run_id === runId && job.job_id === openmmJobId) {
          setOpenmmJobs(old => [job, ...old.filter(item => item.job_id !== job.job_id)]);
          if (observedStatus !== job.status) {
            observedStatus = job.status;
            if (job.attempt_ordinal > 0 || ["done", "failed", "cancelled", "interrupted"].includes(job.status))
              void refreshOpenmmBudget(runId, openmmJobId, ticket);
          }
        }
      } catch (e) { if (active && ticket === epoch.current && openmmJobRef.current === openmmJobId)
        setOpenmmError(e instanceof Error ? e.message : String(e)); }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [runId, openmmJobId, refreshOpenmmBudget]);

  useEffect(() => {
    if (!runId || !openmmOutput || !openmmResultKey) return;
    let active = true;
    const ticket = epoch.current;
    setOpenmmResult(null);
    api.openmm(runId, openmmOutput).then(response => {
      if (active && ticket === epoch.current && openmmOutputRef.current === openmmOutput &&
          openmmJobRef.current === openmmJobId && response.meta.handle === openmmOutput && response.meta.kind === "openmm_minimization" &&
          response.result.schema === "openmm_protein_minimization@1" && response.result.job_id === openmmJobId)
        { setOpenmmResult({ key: openmmResultKey, value: response.result }); setOpenmmResultError(null); }
      else if (active && ticket === epoch.current && openmmOutputRef.current === openmmOutput)
        setOpenmmResultError({ key: openmmResultKey, message: "OpenMM 결과가 선택한 작업과 일치하지 않습니다." });
    }).catch(e => { if (active && ticket === epoch.current && openmmOutputRef.current === openmmOutput) {
      setOpenmmResult(null); setOpenmmResultError({ key: openmmResultKey, message: e instanceof Error ? e.message : String(e) });
    } });
    return () => { active = false; };
  }, [runId, openmmOutput, openmmJobId, openmmResultKey, openmmReadRetry]);

  useEffect(() => {
    if (!runId || !savedOpenmmReport || !openmmResultKey) return;
    let active = true;
    const ticket = epoch.current;
    setOpenmmReport(null);
    api.openmmReport(runId, savedOpenmmReport.handle).then(artifact => {
      if (active && ticket === epoch.current && openmmOutputRef.current === openmmOutput && openmmOutput &&
          responseMatchesOpenmmSelection(openmmResultKey, reportSelectionKey(runId, openmmOutput), runId, openmmOutput, artifact))
        { setOpenmmReport({ key: openmmResultKey, artifact }); setOpenmmReportError(null); }
      else if (active && ticket === epoch.current && openmmOutputRef.current === openmmOutput)
        setOpenmmReportError({ key: openmmReportErrorKey, message: "저장된 OpenMM 보고서가 선택한 결과와 일치하지 않습니다." });
    }).catch(e => { if (active && ticket === epoch.current && openmmOutputRef.current === openmmOutput) {
      setOpenmmReport(null); setOpenmmReportError({ key: openmmReportErrorKey, message: e instanceof Error ? e.message : String(e) });
    } });
    return () => { active = false; };
  }, [runId, savedOpenmmReport?.handle, openmmResultKey, openmmReportErrorKey, openmmOutput, openmmReportRetry]);

  async function checkOpenmmInput() {
    if (!runId || !openmmInput || !openmmPreflightKey) return;
    const request = actionIdentity();
    setOpenmmError(""); setOpenmmPlan(null);
    try {
      const value = await api.openmmPreflight(runId, openmmInput);
      if (actionCurrent(request) && value.structure === openmmInput)
        setOpenmmPreflight({ key: openmmPreflightKey, heavy_atom_count: value.heavy_atom_count, excluded: value.excluded });
    } catch (e) { if (actionCurrent(request)) { setOpenmmPreflight(null); setOpenmmError(e instanceof Error ? e.message : String(e)); } }
  }

  async function submitOpenmm() {
    if (!runId || !openmmInput || !activeOpenmmPreflight || !proteinOnlyAccepted || !hydrogenAccepted) return;
    const id = runId, input = openmmInput;
    const request = actionIdentity();
    setOpenmmError(""); setOpenmmPlan(null); setOpenmmBusy(true);
    try {
      const result = await api.submitOpenmm(id, input);
      if (actionCurrent(request)) {
        if ("plan_only" in result) {
          if (result.plan_only === true && result.protocol_id === "openmm_protein_minimize" &&
              result.reason_code === "dry_run" && result.available === false &&
              Array.isArray(result.output_handles) && result.output_handles.length === 0 &&
              result.normalized_parameters?.structure === input) {
            setOpenmmPlan({ key: reportSelectionKey(id, input)!,
              message: "dry-run 계획만 반환되었습니다. 작업은 생성되지 않았고 계산·예산은 사용되지 않았습니다." });
          } else setOpenmmError("예상하지 못한 dry-run 계획 응답입니다.");
        } else if (result.run_id === id && result.input_handles?.[0] === input && typeof result.job_id === "string") {
          openmmJobRef.current = result.job_id;
          setOpenmmJobs(old => [result, ...old.filter(item => item.job_id !== result.job_id)]);
          setOpenmmJobId(result.job_id);
        } else setOpenmmError("제출 응답이 현재 구조와 일치하지 않습니다.");
      }
    } catch (e) { if (actionCurrent(request)) setOpenmmError(e instanceof Error ? e.message : String(e)); }
    finally { if (actionCurrent(request)) setOpenmmBusy(false); }
  }

  async function startOpenmm(expectedJobId?: string) {
    if (!runId || !activeOpenmmJob) return;
    const id = runId, jobId = activeOpenmmJob.job_id;
    if (expectedJobId && expectedJobId !== jobId) return;
    const request = actionIdentity();
    setOpenmmError(""); setOpenmmBusy(true);
    try {
      const job = await api.startJob(id, jobId);
      if (actionCurrent(request) && job.run_id === id && job.job_id === jobId) {
        setOpenmmJobs(old => [job, ...old.filter(item => item.job_id !== jobId)]);
        void refreshOpenmmBudget(id, jobId, request.epoch);
      }
    } catch (e) {
      if (actionCurrent(request) && !(e instanceof Error && e.message === "HTTP 409")) setOpenmmError(e instanceof Error ? e.message : String(e));
    } finally { if (actionCurrent(request)) setOpenmmBusy(false); }
  }

  async function approveOpenmm() {
    if (!runId || !activeOpenmmJob) return;
    const id = runId, jobId = activeOpenmmJob.job_id, request = actionIdentity();
    setOpenmmBusy(true);
    try { await api.approveOpenmm(id); if (actionCurrent(request)) { setOpenmmError(""); await startOpenmm(jobId); } }
    catch (e) { if (actionCurrent(request)) setOpenmmError(e instanceof Error ? e.message : String(e)); }
    finally { if (actionCurrent(request)) setOpenmmBusy(false); }
  }

  async function cancelOpenmm() {
    if (!runId || !activeOpenmmJob) return;
    const request = actionIdentity(), jobId = activeOpenmmJob.job_id, id = runId;
    try {
      const response = await api.cancelJob(id, jobId);
      if (actionCurrent(request) && response.job.run_id === id && response.job.job_id === jobId)
        setOpenmmJobs(old => [response.job, ...old.filter(item => item.job_id !== response.job.job_id)]);
    } catch (e) { if (actionCurrent(request)) setOpenmmError(e instanceof Error ? e.message : String(e)); }
  }

  async function retryOpenmm() {
    if (!runId || !activeOpenmmJob) return;
    const request = actionIdentity(), jobId = activeOpenmmJob.job_id, id = runId;
    try {
      const job = await api.retryJob(id, jobId);
      if (actionCurrent(request) && job.run_id === id && job.job_id === jobId) {
        setOpenmmJobs(old => [job, ...old.filter(item => item.job_id !== job.job_id)]);
        setOpenmmError("");
      }
    } catch (e) { if (actionCurrent(request)) setOpenmmError(e instanceof Error ? e.message : String(e)); }
  }

  async function createOpenmmReport() {
    if (!runId || !openmmOutput || !openmmResultKey || !selectedOpenmmResult) return;
    const id = runId, result = openmmOutput;
    const request = actionIdentity();
    try {
      const artifact = await api.createOpenmmReport(id, result);
      if (actionCurrent(request) && responseMatchesOpenmmSelection(openmmResultKey, reportSelectionKey(id, result), id, result, artifact)) {
        setOpenmmReport({ key: openmmResultKey, artifact });
        const reports = await api.reports(id);
        if (actionCurrent(request)) setSavedReports(reports);
      }
    } catch (e) { if (actionCurrent(request)) setOpenmmError(e instanceof Error ? e.message : String(e)); }
  }

  async function switchRun(id: string) {
    setBusy("run 불러오는 중…"); setError("");
    try { await reopen(id); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(""); }
  }

  async function doCreate() {
    setBusy("run 생성 중…"); setError("");
    try {
      const created = await api.createRun();
      setRuns(await api.runs()); setUpload(null); setPipelineResidues(null); setInspectedStructure(null); setHandles({}); setEvents([]);
      await reopen(created.run_id);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(""); }
  }
  async function doUpload(file: File | undefined) {
    if (!file || mutationDisabled) return;
    if (file.size > 25 * 1024 * 1024) {
      setError("업로드 파일이 25 MiB 제한을 초과했습니다. 더 작은 PDB 또는 mmCIF 파일을 선택하세요.");
      return;
    }
    setBusy("로컬 파일 업로드 중…"); setError("");
    try {
      let id = runId;
      if (!id) { const created = await api.createRun(); id = created.run_id; setRuns(await api.runs()); await reopen(id); }
      const result = await api.upload(id, file);
      setUpload(result); setModelIndex(0); setPipelineResidues(null); setInspectedStructure(null); setHandles({}); setEvents([]); setRowsState(null); setViewIntent("latest_result"); setSelectedStepNumber(null); setHighlight(null); setFocusedResidue(null); setOffset(0);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(""); }
  }
  async function call(tool: "load_structure" | "prepare_structure" | "compute_interactions" | "compute_interface_sasa", args: Record<string, unknown>) {
    if (!runId || mutationDisabled) return;
    setBusy(`${tool} 실행 중…`); setError("");
    try {
      const result = await api.command(runId, tool, args);
      if (!result.ok) {
        setError("message" in result ? result.message : "approval" in result ? result.approval.reason : result.loop_stop.reason);
        return;
      }
      await reopen(runId);
      setRuns(await api.runs());
      if (tool === "load_structure") setUpload(null);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(""); }
  }
  async function calculateExactSasa(structure: string, ligand: ResidueRef) {
    if (!runId || busy || !viewerReady || displaySource?.handle !== structure ||
        !displayResidues?.ligands.some(candidate => identity(candidate) === identity(ligand))) return;
    const id = runId;
    const ticket = epoch.current;
    setBusy("compute_interface_sasa 실행 중…"); setError("");
    try {
      const result = await api.command(id, "compute_interface_sasa", { structure, ligand });
      if (ticket !== epoch.current) return;
      if (!result.ok) { setError("message" in result ? result.message : "SASA 계산을 시작할 수 없습니다."); return; }
      await reopen(id);
      setBusy("");
    } catch (e) { if (ticket === epoch.current) setError(e instanceof Error ? e.message : String(e)); }
    finally { if (ticket === epoch.current) setBusy(""); }
  }
  async function calculateInspectedSasa() {
    if (!selectedInteraction || !objectMeta || objectMeta.kind !== "interaction_set" ||
        objectMeta.schema !== "interaction_set@1" || typeof objectMeta.summary.structure !== "string" ||
        !objectMeta.summary.ligand || typeof objectMeta.summary.ligand !== "object") return;
    await calculateExactSasa(objectMeta.summary.structure, objectMeta.summary.ligand as ResidueRef);
  }
  function selectFromViewer(ref: ResidueRef | null) {
    // Native canvas picks remain available in a displayed minimized scene and
    // while a scientific mutation is busy; table/ligand focus buttons retain
    // their separate focusEnabled guard.
    if (!viewerReady || !viewerContextKey) return;
    if (!ref) {
      manualViewerInvalidator.current?.();
      setHighlight(null); setFocusedResidue(null); setFocusError(null);
      return;
    }
    const matches = displayResidues?.residues.filter(item => item.model_number === ref.model_number &&
      item.chain_auth === ref.chain_auth && item.seq_auth === ref.seq_auth &&
      (item.icode ?? "") === (ref.icode ?? "") && item.resname === ref.resname &&
      (item.chain_label == null || item.chain_label === ref.chain_label) &&
      (item.seq_label == null || item.seq_label === ref.seq_label)) ?? [];
    if (matches.length !== 1) return;
    manualViewerInvalidator.current?.();
    const exact = matches[0];
    setHighlight(previous => previous?.key === viewerContextKey && identity(previous.residue) === identity(exact)
      ? previous : { key: viewerContextKey, residue: exact });
    setFocusedResidue({ key: viewerContextKey, residue: exact });
    setFocusError(null);
  }
  function focusResidue(ref: ResidueRef) {
    if (!focusEnabled || !viewerContextKey) return;
    manualViewerInvalidator.current?.();
    setFocusedResidue(null); setFocusError(null);
    setHighlight({ key: viewerContextKey, residue: ref });
  }
  function toggleTheme() {
    const root = document.documentElement;
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
  }

  const latestUpload = [...events].reverse().find(e => e.type === "upload_received");
  const uploadedCount = events.filter(e => e.type === "upload_received").length;
  const noLigands = handles.prepared && latestResidues?.ligands.length === 0;

  return <WorkspaceShell
    runId={runId} pipeline="load_structure → prepare_structure → compute_interactions"
    egress={displayedEgressMode(run)} onToggleTheme={toggleTheme} tabs={["run", "models"]}
    budgetShort={budget && <span className="mw-muted mw-mono mw-top-budget">expensive {budget.expensive_calls.used}/{budget.expensive_calls.limit}</span>}
    railCounts={{ run: steps.length, models: displayResidues?.ligands.length ?? 0 }}
    rail={{
      run: <>
        <div className="mw-rail-group"><label className="mw-eyebrow" htmlFor="run-choice">저장된 run</label>
          <select id="run-choice" className="mw-select" value={runId ?? ""} disabled={!!busy}
            onChange={e => { if (e.target.value) void switchRun(e.target.value); }}>
            <option value="">run 선택</option>
            {runs.map(item => <option key={item.run_id} value={item.run_id}>{item.run_id.slice(0, 18)}…</option>)}
          </select>
          <Button size="sm" onClick={doCreate} disabled={!!busy || inspecting}>새 run</Button>
          {latestUpload?.type === "upload_received" && <small className="mw-muted">업로드 {uploadedCount}건 · {latestUpload.format}</small>}
        </div>
        {(inspecting || displayDiffersFromPipeline) && <div className="mw-inspection-context"><span>{selectedInteraction && displayDiffersFromPipeline
          ? "이 측정의 입력 구조는 최신 전처리 구조와 다릅니다. 최신 파이프라인의 도구는 여기에서 사용할 수 없습니다."
          : displayDiffersFromPipeline ? "표시 중인 결과의 구조가 최신 파이프라인과 다릅니다. 새 계산은 최신 파이프라인에서 실행합니다."
            : "선택한 단계 검사 중 · 새 계산은 최신 파이프라인에서 실행합니다."}</span>
          <Button size="sm" onClick={() => { setOpenmmViewHandle(null); setViewIntent("latest_pipeline"); setSelectedStepNumber(null); setInspectionRevision(value => value + 1); setOffset(0); setHighlight(null); setFocusedResidue(null); setFocusError(null); }}>최신 구조로 돌아가기</Button></div>}
        {steps.length ? <StepList steps={steps} selected={selectedStep?.n} onSelect={step => { setOpenmmViewHandle(null); setViewIntent("step"); setSelectedStepNumber(step.n); setInspectionRevision(value => value + 1); setOffset(0); setHighlight(null); setFocusedResidue(null); setFocusError(null); }} />
          : <p className="mw-empty-note">파일을 업로드하면 실제 도구 호출이 여기에 기록됩니다.</p>}
      </>,
      models: <div className="mw-rail-group">
        {displayData && <><span className="mw-eyebrow">{viewerReady ? "표시 중인 구조" : displayedError ? "표시 실패한 구조" : "불러오는 구조"} · {openmmViewHandle ? "OpenMM 최소화 단백질 좌표" : viewIntent === "step" ? "선택한 단계" : viewIntent === "latest_result" ? "최근 결과" : "최신 파이프라인"}</span><HandleChip handle={{ handle: displayData.source.handle, kind: displayData.kind }} />
          <span className="mw-muted">model {displayResidues?.model_number ?? "—"} · {displayResidues?.residues.length ?? "—"} residues</span></>}
        {displayedError && <span className="mw-workflow-error" role="alert">{displayedError}</span>}
        {displayedError && <Button size="sm" onClick={() => { setInspectionRevision(value => value + 1); setHighlight(null); setFocusedResidue(null); setFocusError(null); }}>구조 다시 시도</Button>}
        {!displayData && targetHandle && !displayedError && <span className="mw-muted">선택한 구조를 불러오는 중…</span>}
        <span className="mw-eyebrow">리간드 인스턴스</span>
        {displayResidues?.ligands.length ? displayResidues.ligands.map(ligand => <button type="button" className="mw-ligand-item" key={identity(ligand)} disabled={!focusEnabled} onClick={() => focusResidue(ligand)}>{displayResidue(ligand)}</button>)
          : <span className="mw-muted">{displaySource ? "선택 가능한 리간드 없음" : "구조를 불러오세요"}</span>}
      </div>,
      jobs: null,
    }}
    canvas={<MolstarViewer key={viewerContextKey ?? "no-structure"} source={displaySource} representation={representation}
      highlight={viewerReady && highlight?.key === viewerContextKey ? highlight.residue : null}
      onBridge={bridge => { viewerBridgeRef.current = bridge; }}
      onManualInteraction={() => manualViewerInvalidator.current?.()}
      onSelect={selectFromViewer}
      onLoadState={(loadedSource, status, message) => {
        if (viewerContextKey && loadedSource === displaySource) setViewerState({ key: viewerContextKey, source: loadedSource, status, message });
      }}
      onFocusResult={(focusedSource, residue, found) => {
        if (!viewerReady || !viewerContextKey || focusedSource !== displaySource || highlight?.key !== viewerContextKey || identity(highlight.residue) !== identity(residue)) return;
        if (found) { setFocusedResidue({ key: viewerContextKey, residue }); setFocusError(null); }
        else { setFocusedResidue(null); setFocusError({ key: viewerContextKey, message: "선택한 잔기를 표시 중인 구조에서 찾지 못했습니다." }); }
      }}
      emptyMessage={displayedError ?? (targetHandle ? "선택한 구조를 불러오는 중…" : selectedMeasurement || selectedStructure ? "선택한 객체의 입력 구조를 확인하는 중…" : undefined)}
      emptyIsError={!!displayedError} />}
    canvasOverlayTopLeft={<Segmented label="표현 방식" value={representation} onChange={value => {
      manualViewerInvalidator.current?.(); setRepresentation(value);
    }} options={[
      { value: "cartoon", label: "cartoon" }, { value: "ball-and-stick", label: "ball-and-stick" }, { value: "surface", label: "surface" },
    ]} />}
    canvasLegend={(displayData || inspecting) && <><span className="mw-muted">{openmmViewHandle ? "OpenMM 최소화 단백질 좌표" : viewIntent === "step" ? "선택한 단계의 구조" : viewIntent === "latest_result" ? "최근 결과의 구조" : "최신 파이프라인 구조"}{viewerReady ? ` · model ${displayResidues?.model_number ?? "—"}` : displayedError ? " · 표시 실패" : " · 불러오는 중"}</span>
      {selectedFocus && <span className="mw-mono">선택: {displayResidue(selectedFocus)}</span>}</>}
    strip={<><ViewerAgentPanel key={viewerContextKey ?? `empty-${runId ?? "none"}`}
      runId={runId ?? null} clientId={viewerClientId.current ?? ""} sceneGeneration={sceneToken.current.generation}
      sourceHandle={displaySource?.handle ?? null} viewerReady={viewerReady} bridgeRef={viewerBridgeRef}
      representation={representation} selected={selectedFocus} residues={displayResidues} dryRun={run?.dry_run ?? false}
      onRepresentation={setRepresentation}
      onSelection={ref => { if (viewerContextKey) {
        if (ref) { setFocusedResidue({ key: viewerContextKey, residue: ref }); setFocusError(null); }
        else { setFocusedResidue(null); setHighlight(null); setFocusError(null); }
      } }}
      onMode={enabled => setRun(previous => previous ? { ...previous, egress: enabled ? "online" : "local_only" } : previous)}
      onBudgetRefresh={() => { if (runId) {
        const id = runId, ticket = epoch.current;
        void api.budget(id).then(value => {
          if (openmmRunRef.current === id && epoch.current === ticket) setBudget(value);
        }).catch(() => undefined);
      } }}
      onScopeChange={() => setViewerScopeRevision(value => value + 1)}
      registerInvalidator={value => { manualViewerInvalidator.current = value; }} />
    <div className="mw-workflow">
      <div className="mw-workflow-row"><label className="mw-file">로컬 구조 파일 <input type="file" accept=".pdb,.cif,.mmcif" disabled={mutationDisabled} onChange={e => { const file = e.target.files?.[0]; doUpload(file); e.target.value = ""; }} /></label>
        {upload && <><span className="mw-mono mw-muted">{upload.format} · {upload.size.toLocaleString()} bytes</span>
          {upload.model_numbers ? <label>model <select className="mw-select" value={modelIndex} disabled={mutationDisabled} onChange={e => setModelIndex(Number(e.target.value))}>{upload.model_numbers.map((number, index) => <option key={index} value={index}>{index} · #{number}</option>)}</select></label>
            : <label>model index <input className="mw-number" type="number" min="0" step="1" value={modelIndex} disabled={mutationDisabled} onChange={e => setModelIndex(Number(e.target.value))} title="재연 업로드의 모델 수는 이벤트에 기록되지 않았습니다. 0부터 시작하는 모델 인덱스를 입력하세요." /></label>}
          <Button variant="primary" size="sm" disabled={mutationDisabled || !Number.isInteger(modelIndex) || modelIndex < 0} onClick={() => call("load_structure", { source: upload.upload_id, model_index: modelIndex })}>구조 불러오기</Button></>}
      </div>
      {handles.loaded && <div className="mw-workflow-row">
        <label>altloc <select className="mw-select" value={altloc} disabled={mutationDisabled} onChange={e => setAltloc(e.target.value as typeof altloc)}><option value="highest_occupancy">highest occupancy</option><option value="first">first</option></select></label>
        <label>물 <select className="mw-select" value={waters} disabled={mutationDisabled} onChange={e => setWaters(e.target.value as typeof waters)}><option value="strip_all">제거</option><option value="keep_all">유지</option></select></label>
        <label>수소 <select className="mw-select" value={hydrogens} disabled={mutationDisabled} onChange={e => setHydrogens(e.target.value as typeof hydrogens)}><option value="strip">제거</option><option value="keep">유지</option></select></label>
        <Button size="sm" disabled={mutationDisabled} onClick={() => call("prepare_structure", { structure: handles.loaded!.handle, altloc, waters, hydrogens, missing_residues: "leave_gaps", symmetry_mates: "ignore" })}>전처리</Button>
      </div>}
      {handles.prepared && <div className="mw-workflow-row">
        <label>리간드 <select className="mw-select" value={ligandIndex} onChange={e => setLigandIndex(e.target.value)} disabled={mutationDisabled || !latestResidues?.ligands.length}>
          <option value="">인스턴스 선택</option>{latestResidues?.ligands.map((ligand, index) => <option value={index} key={identity(ligand)}>{displayResidue(ligand)}</option>)}
        </select></label>
        <label>cutoff <input className="mw-number" type="number" min="2.5" max="6" step="0.1" value={cutoff} disabled={mutationDisabled} onChange={e => setCutoff(Number(e.target.value))} /> Å</label>
        <Button variant="primary" size="sm" disabled={mutationDisabled || !latestResidues || ligandIndex === "" || !Number.isFinite(cutoff) || cutoff < 2.5 || cutoff > 6}
          onClick={() => call("compute_interactions", { structure: handles.prepared!.handle, ligand: latestResidues!.ligands[Number(ligandIndex)], cutoff_A: cutoff, types: contactTypes, engine: "geometric" })}>기하 접촉 계산</Button>
        <Button size="sm" disabled={mutationDisabled || !latestResidues || ligandIndex === "" || capabilities?.methods?.interface_sasa?.available !== true}
          onClick={() => call("compute_interface_sasa", { structure: handles.prepared!.handle, ligand: latestResidues!.ligands[Number(ligandIndex)] })}>선택한 리간드 SASA 계산</Button>
        {noLigands && <span className="mw-muted">리간드가 없어 접촉을 계산할 수 없습니다.</span>}
      </div>}
      {busy && <span role="status" className="mw-muted">{busy}</span>}
      {error && <span role="alert" className="mw-workflow-error">{error}</span>}
    </div></>}
    inspectorTitle={selectedStep ? `Inspector · #${String(selectedStep.n).padStart(2, "0")}` : "Inspector · 측정"}
    inspector={<>
      {selectedMeta?.status === "error" && <InspectorSection><p className="mw-table-error" role="alert">객체 메타데이터를 읽지 못했습니다: {selectedMeta.message}</p></InspectorSection>}
      {objectMeta && <InspectorSection><HandleChip handle={objectMeta} /><dl className="mw-kv mw-inspector-kv">
        <dt>schema</dt><dd>{objectMeta.schema}</dd><dt>bytes</dt><dd>{objectMeta.size}</dd><dt>produced_by</dt><dd>{objectMeta.produced_by ?? "—"}</dd>
        <dt>null_result</dt><dd>{String(objectMeta.null_result)}</dd>
        {Object.entries(objectMeta.summary).filter(([, value]) => typeof value === "number" || typeof value === "string").map(([key, value]) => <Fragment key={key}><dt>{key}</dt><dd>{String(value)}</dd></Fragment>)}
      </dl></InspectorSection>}
      {interactionHandle && !openmmViewHandle && <InspectorSection flush>
        <div className="mw-table-head"><strong>기하 접촉{currentRows?.status === "ready" ? ` · ${currentRows.total}건` : ""}</strong><span>heavy atom distance · Å</span></div>
        {!currentRows ? <p className="mw-empty-note" role="status">측정 행을 불러오는 중…</p>
          : currentRows.status === "error" ? <div className="mw-table-error" role="alert"><p>측정 행을 불러오지 못했습니다: {currentRows.message}</p><Button size="sm" onClick={() => setRowsRetry(value => value + 1)}>다시 시도</Button></div>
          : currentRows.total > 0 ? <>{!focusEnabled && <p className="mw-empty-note" role={displayedError ? "alert" : "status"}>잔기 초점 사용 불가: {displayedError ?? (busy ? "실행 중에는 잔기 초점을 사용할 수 없습니다." : "측정에 사용된 구조가 뷰어에 표시될 때까지 기다리세요.")}</p>}
          {focusError?.key === viewerContextKey && <p className="mw-empty-note" role="alert">{focusError.message}</p>}
          <div className="mw-table-scroll" role="region" aria-label="기하 접촉 측정 행" tabIndex={0}><InteractionTable rows={currentRows.rows} onSelect={focusEnabled ? row => focusResidue(row.residue) : undefined} /></div>
          <div className="mw-pagination"><Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>이전</Button>
            <span>{offset + 1}–{Math.min(offset + currentRows.rows.length, currentRows.total)} / {currentRows.total}</span>
            <Button size="sm" disabled={offset + currentRows.rows.length >= currentRows.total} onClick={() => setOffset(offset + 50)}>다음</Button></div></>
          : <p className="mw-empty-note">측정은 성공했습니다. 선택한 조건에서 접촉이 없습니다 (scientific_null).</p>}
        <p className="mw-empty-note">거리 기반 접촉이며 수소결합, 친화도 또는 안정성의 검증 결과가 아닙니다.</p>
      </InspectorSection>}
      {selectedInteraction && objectMeta?.kind === "interaction_set" && viewerReady &&
        <InspectorSection><span className="mw-eyebrow">이 측정의 정확한 입력</span>
          <p className="mw-capability">선택한 접촉의 전처리 구조와 리간드 인스턴스로 SASA를 계산합니다.</p>
          <Button size="sm" disabled={!!busy || capabilities?.methods?.interface_sasa?.available !== true}
            onClick={() => void calculateInspectedSasa()}>이 입력의 SASA 계산</Button></InspectorSection>}
      {selectedStructure && expectedKind === "prepared_structure" && objectMeta?.kind === "prepared_structure" &&
        <InspectorSection><span className="mw-eyebrow">표시 중인 전처리 구조의 SASA</span>
          <p className="mw-capability">Models에서 정확한 리간드 인스턴스를 선택하고 뷰어 초점이 확인되면 계산할 수 있습니다.</p>
          <Button size="sm" disabled={!!busy || !viewerReady || !selectedFocus ||
            !displayResidues?.ligands.some(candidate => identity(candidate) === identity(selectedFocus)) ||
            capabilities?.methods?.interface_sasa?.available !== true}
            onClick={() => { if (displaySource && selectedFocus) void calculateExactSasa(displaySource.handle, selectedFocus); }}>선택한 리간드 SASA 계산</Button>
        </InspectorSection>}
      {sasaHandle && !openmmViewHandle && <InspectorSection flush>
        <div className="mw-table-head"><strong>단백질–리간드 SASA · Å²</strong><span>Lee–Richards 100 slices</span></div>
        {!activeSasa ? <p className="mw-empty-note" role="status">SASA 결과를 불러오는 중…</p>
          : activeSasa.status === "error" ? <div className="mw-table-error" role="alert"><p>SASA 결과를 불러오지 못했습니다: {activeSasa.message}</p>
              <Button size="sm" onClick={() => setSasaRetry(value => value + 1)}>다시 시도</Button></div>
            : <>
              <p className="mw-capability mw-mono">{activeSasa.result.method.method_id} · FreeSASA {activeSasa.result.method.engine_version} · probe {activeSasa.result.method.probe_radius_A} Å · {activeSasa.result.method.threads} thread</p>
              <p className="mw-capability">리간드: {displayResidue(activeSasa.result.ligand)} · 단백질 중원자 {activeSasa.result.atom_counts.protein}개 · 리간드 중원자 {activeSasa.result.atom_counts.ligand}개 · 제외 잔기 {activeSasa.result.atom_counts.excluded_residues}개</p>
              <dl className="mw-kv mw-inspector-kv">
                <dt>단백질 매몰</dt><dd>{area2(activeSasa.result.summary.protein_burial_A2)} Å²</dd>
                <dt>리간드 매몰</dt><dd>{area2(activeSasa.result.summary.ligand_burial_A2)} Å²</dd>
                <dt>총 SASA 손실</dt><dd>{area2(activeSasa.result.summary.total_sasa_loss_A2)} Å²</dd>
                <dt>분리 단백질 SASA</dt><dd>{area2(activeSasa.result.summary.protein_sasa_isolated_A2)} Å²</dd>
                <dt>분리 리간드 SASA</dt><dd>{area2(activeSasa.result.summary.ligand_sasa_isolated_A2)} Å²</dd>
                <dt>결합체 SASA</dt><dd>{area2(activeSasa.result.summary.complex_sasa_A2)} Å²</dd>
              </dl>
              {!focusEnabled && <p className="mw-empty-note" role={displayedError ? "alert" : "status"}>잔기 초점 사용 불가: {displayedError ?? "해당 구조가 뷰어에 표시될 때까지 기다리세요."}</p>}
              {focusError?.key === viewerContextKey && <p className="mw-empty-note" role="alert">{focusError.message}</p>}
              <div className="mw-table-scroll" role="region" aria-label="단백질 잔기 SASA 측정 행" tabIndex={0}>
                <table className="mw-table"><thead><tr><th>단백질 잔기 (auth/label/model)</th><th>분리 Å²</th><th>결합 Å²</th><th>매몰 Å²</th></tr></thead>
                  <tbody>{activeSasa.result.residues.map((row, index) => <tr key={`${identity(row.residue)}-${index}`}>
                    <td><button type="button" disabled={!focusEnabled || displaySource?.handle !== activeSasa.result.structure}
                      onClick={() => focusResidue(row.residue)}>{displayResidue(row.residue)}</button></td>
                    <td>{area2(row.isolated_A2)}</td><td>{area2(row.bound_A2)}</td><td>{area2(row.buried_A2)}</td>
                  </tr>)}</tbody></table>
              </div>
              <p className="mw-empty-note">0.00 Å² 매몰은 유효한 측정값입니다. 이 값은 용매 접근 기하이며 친화도나 에너지가 아닙니다.</p>
            </>}
      </InspectorSection>}
      {sasaHandle && runId && <InspectorSection>
        <span className="mw-eyebrow">선택한 SASA 결과의 로컬 방법 보고서</span>
        <p className="mw-capability mw-mono">결과 {sasaHandle.handle}</p>
        {!savedMethodReport && activeMethodReport?.status !== "ready" && <Button size="sm" onClick={() => void createSelectedMethodReport()}
          disabled={activeMethodReport?.status === "pending" || activeSasa?.status !== "ready"}>방법 보고서 만들기</Button>}
        {activeMethodReport?.status === "pending" && <p role="status" className="mw-muted">방법 보고서를 불러오는 중…</p>}
        {activeMethodReport?.status === "error" && <div role="alert" className="mw-table-error"><p>방법 보고서를 불러오지 못했습니다: {activeMethodReport.message}</p>
          <Button size="sm" onClick={() => void createSelectedMethodReport()}>다시 시도</Button></div>}
        {activeMethodReport?.status === "ready" && activeSasa?.status === "ready" &&
          (activeMethodReport.artifact.manifest.prepared_handle !== activeSasa.result.structure ?
            <p role="alert" className="mw-table-error">보고서의 입력 구조가 선택한 SASA 결과와 다릅니다.</p> : <>
              <p className="mw-capability">저장된 방법 보고서 · 증거 이벤트 #{activeMethodReport.artifact.manifest.snapshot.event_seq}</p>
              <div className="mw-report-downloads">
                <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, activeMethodReport.artifact.handle, "markdown")}>Markdown 다운로드</a>
                <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, activeMethodReport.artifact.handle, "json")}>정확한 JSON 다운로드</a>
              </div>
              <pre className="mw-report-preview" aria-label="저장된 방법 보고서 미리보기">{activeMethodReport.artifact.markdown}</pre>
            </>)}
      </InspectorSection>}
      {interactionHandle && runId && <InspectorSection>
        <span className="mw-eyebrow">선택한 측정의 로컬 보고서</span>
        <p className="mw-capability mw-mono">결과 {interactionHandle.handle}</p>
        {objectMeta?.kind === "interaction_set" && <p className="mw-capability mw-mono">입력 구조 {String(objectMeta.summary.structure ?? "확인 중")}</p>}
        {!savedReport && activeReport?.status !== "ready" && <Button size="sm" onClick={() => void createSelectedReport()}
          disabled={activeReport?.status === "pending"}>보고서 만들기</Button>}
        {activeReport?.status === "pending" && <p role="status" className="mw-muted">선택한 결과의 보고서를 불러오는 중…</p>}
        {activeReport?.status === "error" && <div role="alert" className="mw-table-error"><p>보고서를 불러오지 못했습니다: {activeReport.message}</p>
          <Button size="sm" onClick={() => void createSelectedReport()}>다시 시도</Button></div>}
        {activeReport?.status === "ready" && <>
          <p className="mw-capability">저장된 보고서 · 증거 이벤트 #{activeReport.artifact.manifest.snapshot.event_seq} · 원자쌍 {activeReport.artifact.manifest.counts.atom_pairs}건 · 잔기 {activeReport.artifact.manifest.counts.contacting_residues}개</p>
          <div className="mw-report-downloads">
            <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, activeReport.artifact.handle, "markdown")}>Markdown 다운로드</a>
            <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, activeReport.artifact.handle, "json")}>정확한 JSON 다운로드</a>
          </div>
          <pre className="mw-report-preview" aria-label="저장된 보고서 미리보기">{activeReport.artifact.markdown}</pre>
        </>}
      </InspectorSection>}
      {capabilities?.methods?.openmm_protein_minimize && <InspectorSection>
        <span className="mw-eyebrow">OpenMM 단백질 전용 최소화 · kJ/mol</span>
        <p className="mw-capability">Amber14-all + GBn2, CPU 1 thread, NoCutoff, 최대 50회. 단백질만 남기고 물·리간드·이온·비단백질은 제외합니다. 이 전위 에너지는 결합 친화도 또는 안정성 예측이 아닙니다.</p>
        <p className="mw-capability">{capabilities.methods.openmm_protein_minimize.available
          ? `${capabilities.methods.openmm_protein_minimize.method_id} · OpenMM ${capabilities.methods.openmm_protein_minimize.distribution_version} (${capabilities.methods.openmm_protein_minimize.engine_build})`
          : `사용 불가: ${capabilities.methods.openmm_protein_minimize.explanation ?? "엔진 확인 실패"}`}</p>
        {openmmInput && <p className="mw-capability mw-mono">입력 {openmmInput}</p>}
        <Button size="sm" disabled={!openmmInput || openmmBusy || capabilities.methods.openmm_protein_minimize.available !== true}
          onClick={() => void checkOpenmmInput()}>단백질 입력·제외 항목 확인</Button>
        {activeOpenmmPreflight && <>
          <p className="mw-capability">단백질 중원자 {activeOpenmmPreflight.heavy_atom_count}개; 제외 성분 {activeOpenmmPreflight.excluded.length}개.</p>
          <div className="mw-table-scroll" role="region" aria-label="OpenMM 제외 성분" tabIndex={0}>
            {activeOpenmmPreflight.excluded.map((item, index) => <p key={`${identity(item.residue)}-${index}`} className="mw-capability">{displayResidue(item.residue)} · {item.reason} · {item.atom_count} atoms</p>)}
          </div>
          <label><input type="checkbox" checked={proteinOnlyAccepted} onChange={e => setProteinOnlyAccepted(e.target.checked)} /> protein_only 선택과 제외 항목을 확인했습니다.</label>
          <label><input type="checkbox" checked={hydrogenAccepted} onChange={e => setHydrogenAccepted(e.target.checked)} /> 기존 수소 제거 후 pH 7.0에서 수소를 다시 만듭니다 (rebuild_pH7).</label>
          <Button size="sm" disabled={openmmBusy || !proteinOnlyAccepted || !hydrogenAccepted}
            onClick={() => void submitOpenmm()}>OpenMM 작업 제출</Button>
          {openmmPlan?.key === openmmPreflightKey && <p role="status" className="mw-capability">{openmmPlan.message}</p>}
        </>}
        {openmmJobs.length > 0 && <label>작업 <select className="mw-select" value={openmmJobId ?? ""} onChange={e => { openmmJobRef.current = e.target.value; openmmOutputRef.current = undefined; setOpenmmJobId(e.target.value); setOpenmmViewHandle(null); }}>
          {openmmJobs.map(job => <option key={job.job_id} value={job.job_id}>{job.job_id.slice(0, 18)} · {job.status}</option>)}
        </select></label>}
        {activeOpenmmJob && <>
          <p className="mw-capability mw-mono">상태 {activeOpenmmJob.status} · 시도 {activeOpenmmJob.attempt_ordinal} · {activeOpenmmJob.job_id}</p>
          {activeOpenmmJob.failure && <p role="alert" className="mw-table-error">{activeOpenmmJob.failure.error}: {activeOpenmmJob.failure.message}</p>}
          {activeOpenmmJob.status === "queued" || activeOpenmmJob.status === "claimed" ? <Button size="sm" disabled={openmmBusy} onClick={() => void startOpenmm()}>작업 시작</Button> : null}
          {["failed", "interrupted"].includes(activeOpenmmJob.status) && activeOpenmmJob.attempt_ordinal < 4 &&
            <Button size="sm" disabled={openmmBusy} onClick={() => void retryOpenmm()}>실패한 작업 재시도</Button>}
          {activeOpenmmJob.blocked_reason === "approval_or_cancel" && <Button size="sm" disabled={openmmBusy} onClick={() => void approveOpenmm()}>고비용 계산 승인 후 시작</Button>}
          {["queued", "claimed", "running"].includes(activeOpenmmJob.status) && <Button size="sm" onClick={() => void cancelOpenmm()}>작업 취소</Button>}
        </>}
        {selectedOpenmmResult && <>
          <dl className="mw-kv mw-inspector-kv">
            <dt>시작 전위</dt><dd>{formatEnergy2(selectedOpenmmResult.before_kJ_mol)} kJ/mol</dd>
            <dt>최소화 후 전위</dt><dd>{formatEnergy2(selectedOpenmmResult.after_kJ_mol)} kJ/mol</dd>
            <dt>전위 변화</dt><dd>{formatEnergy2(selectedOpenmmResult.potential_change_kJ_mol)} kJ/mol</dd>
            <dt>결과 원자</dt><dd>{selectedOpenmmResult.atom_count} (추가 수소 {selectedOpenmmResult.added_hydrogen_count})</dd>
          </dl>
          <p className="mw-capability">수렴을 주장하지 않습니다. 원래 복합체 접촉표는 이 단백질 전용 좌표의 측정값이 아닙니다.</p>
          <Button size="sm" onClick={() => { setOpenmmViewHandle(selectedOpenmmResult.minimized_structure); setHighlight(null); setFocusedResidue(null); }}>최소화 단백질 좌표 보기</Button>
          {openmmViewHandle && <Button size="sm" onClick={() => setOpenmmViewHandle(null)}>원래 구조로 돌아가기</Button>}
          {!savedOpenmmReport && <Button size="sm" onClick={() => void createOpenmmReport()}>OpenMM 방법 보고서 만들기</Button>}
        </>}
        {selectedOpenmmReport && runId && <>
          <p className="mw-capability">저장된 OpenMM 방법 보고서 · 이벤트 #{selectedOpenmmReport.manifest.snapshot.event_seq}</p>
          <div className="mw-report-downloads">
            <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, selectedOpenmmReport.handle, "markdown")}>Markdown 다운로드</a>
            <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, selectedOpenmmReport.handle, "json")}>정확한 JSON 다운로드</a>
          </div>
          <pre className="mw-report-preview" aria-label="저장된 OpenMM 보고서 미리보기">{selectedOpenmmReport.markdown}</pre>
        </>}
        {openmmOutput && !selectedOpenmmResult && <Button size="sm" onClick={() => setOpenmmReadRetry(n => n + 1)}>저장된 OpenMM 결과 다시 읽기</Button>}
        {savedOpenmmReport && !selectedOpenmmReport && <Button size="sm" onClick={() => setOpenmmReportRetry(n => n + 1)}>저장된 OpenMM 보고서 다시 읽기</Button>}
        {activeOpenmmResultError && <p role="alert" className="mw-table-error">{activeOpenmmResultError}</p>}
        {activeOpenmmReportError && <p role="alert" className="mw-table-error">{activeOpenmmReportError}</p>}
        {openmmError && <p role="alert" className="mw-table-error">{openmmError}</p>}
      </InspectorSection>}
      {budget && <InspectorSection><span className="mw-eyebrow">실제 예산</span><BudgetMeter budget={budget} /></InspectorSection>}
      {capabilities?.methods?.interface_sasa && <InspectorSection><span className="mw-eyebrow">지원하는 로컬 방법</span>
        <p className="mw-capability"><b>단백질–리간드 SASA</b><br />{capabilities.methods.interface_sasa.available
          ? `${capabilities.methods.interface_sasa.method_id} · ${capabilities.methods.interface_sasa.algorithm} ${capabilities.methods.interface_sasa.n_slices} slices · Å² · ${capabilities.methods.interface_sasa.limitations}`
          : `사용 불가: ${capabilities.methods.interface_sasa.explanation ?? "엔진을 확인할 수 없습니다."}`}</p></InspectorSection>}
      {capabilities && <InspectorSection><span className="mw-eyebrow">현재 사용 불가</span>{Object.entries(capabilities.unavailable).map(([name, reason]) => <p className="mw-capability" key={name}><b>{name}</b><br />{reason}</p>)}</InspectorSection>}
    </>}
  />;
}
