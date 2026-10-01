"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BudgetMeter, Button, HandleChip, InspectorSection, InteractionTable, MolstarViewer,
  Segmented, StepList, WorkspaceShell, WorkspaceTabs, type Step, type ViewerRepresentation,
} from "@/components";
import { api, displayedEgressMode, type Capabilities, type MethodReportArtifact, type ObjectMeta, type OpenmmJob, type OpenmmResult, type OpenmmReportArtifact, type ReportArtifact, type ResidueList, type RunSummary, type SasaResult, type SavedReportRef, type UploadResult } from "@/lib/api";
import type { BudgetSnapshot, Handle, InteractionRow, ResidueRef, RunEvent } from "@/lib/contracts";
import { latestHandles, resultEvents, resultId, type CacheEvent } from "@/lib/event-model";
import { formatArea2 as area2 } from "@/lib/area-format";
import { currentOpenmmAction, currentOpenmmBudgetRequest, formatEnergy2, openmmContextChange, selectedOpenmmReadError,
  type OpenmmActionIdentity, type OpenmmContext } from "@/lib/openmm-action";
import { reportSelectionKey, responseMatchesMethodSelection, responseMatchesOpenmmSelection, responseMatchesSelection, savedForSelection, savedMethodForSelection, savedOpenmmForSelection } from "@/lib/report-selection";
import type { ViewerSource } from "@/components/MolstarViewer";
import type { ViewerBinding, ViewerBridge } from "@/components/MolstarViewer";
import { ViewerAgentPanel, type SceneController } from "@/components/ViewerAgentPanel";
import { ChemicalWorkspace } from "@/components/ChemicalWorkspace";
import { PocketPanel } from "@/components/PocketPanel";
import { AnalysisWorkflowPanel, type AnalysisOpenRequest } from "@/components/AnalysisWorkflowPanel";
import { ReportLibraryPanel } from "@/components/ReportLibraryPanel";
import { NumberingPanel } from "@/components/NumberingPanel";
import { SiteAnnotationPanel } from "@/components/SiteAnnotationPanel";
import { hostRequestAccepted, importedPocketChains, newerEventLog, type ScreenSelections } from "@/lib/analysis";
import { featureGates, overlayContextDecision, pocketRequestAccepted, type PocketOverlayReadback, type PocketOverlayRequest,
  type PocketSourceKind } from "@/lib/pockets";
import { chemicalEntryBlockedReason } from "@/lib/chemical";
import { advanceSceneGeneration } from "@/lib/viewer-scene";
import { DEFAULT_WORKSPACE_TAB, type WorkspaceTabId } from "@/lib/workspace-tabs";
import { mergeSavedRows, sceneMatches, type NativeSceneState, type SavedFigureDetail, type SavedSceneDetail } from "@/lib/saved-scene";
import type { ViewerSession } from "@/lib/viewer-agent";
import { ANNOTATION_BLOCKS_POCKET_OVERLAY, ANNOTATION_REQUEST_NOT_READY, annotationGates, annotationShowAccepted,
  annotationShownCurrent, figureSaveBody, sceneAnnotation, sceneRestoreDecision, sceneSaveBody, siteAnnotationRequest,
  type SiteAnnotationReadback, type SiteAnnotationRequest, type SiteAnnotationShown } from "@/lib/site-annotation";
import { atomLabel, catalogAttemptKey, catalogForAttempt, catalogResponseCurrent, retainCatalogState,
  comparisonViewChangeRevokes, comparisonViewIntentKey,
  sameComparisonAction, sameResidueRef, singleSourceSceneCompatible,
  type AtomCatalog, type AtomDistance, type AtomRefV1, type RigidAlignment } from "@/lib/comparison";

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
  return JSON.stringify([ref.model_number, ref.chain_auth, ref.chain_label, ref.seq_auth,
    ref.seq_label, ref.icode, ref.resname]);
}
function displayResidue(ref: ResidueRef) {
  return `${ref.resname} auth ${ref.chain_auth}/${ref.seq_auth}${ref.icode || ""}` +
    ` · label ${ref.chain_label ?? "unknown"}/${ref.seq_label ?? "unknown"} · model ${ref.model_number ?? "unknown"}`;
}
function bridgeStateReady(bridge: ViewerBridge | null): boolean {
  const snapshot = bridge?.snapshot();
  return snapshot?.ready === true && snapshot.catalogReady === true;
}
function beforeDeadline<T>(task: Promise<T>, milliseconds: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error("구조 읽기 제한 시간이 초과되었습니다.")), milliseconds);
  });
  return Promise.race([task, timeout]).finally(() => clearTimeout(timer));
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
  const [sceneName, setSceneName] = useState("");
  const [chemicalActive, setChemicalActive] = useState(false);
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTabId>(DEFAULT_WORKSPACE_TAB);
  const [reportsReloadToken, setReportsReloadToken] = useState(0);
  // M16: numbering maps are made in the 지식·보고서 tab while the structure screen stays mounted; entering the structure
  // tab re-reads the annotation panel's map list (a read only; no event or tool).
  const [structureTabEntries, setStructureTabEntries] = useState(0);
  const [chemicalSceneToRestore, setChemicalSceneToRestore] = useState<string | null>(null);
  const [pocketState, setPocketState] = useState<{ request: PocketOverlayRequest; boundContext: string | null } | null>(null);
  const [pocketReadback, setPocketReadback] = useState<PocketOverlayReadback | null>(null);
  const [pocketOverlayError, setPocketOverlayError] = useState<string | null>(null);
  const [pocketNotice, setPocketNotice] = useState<string | null>(null);
  // M16 reference annotation shown in the viewer (null = off) and its native readback for the current request key.
  const [annotationShown, setAnnotationShown] = useState<SiteAnnotationShown | null>(null);
  const [annotationReadback, setAnnotationReadback] = useState<SiteAnnotationReadback | null>(null);
  const [annotationViewerError, setAnnotationViewerError] = useState<string | null>(null);
  // Annotation part of the latest viewer_scene@2 restore, shown apart from the scene status (never a rollback claim).
  const [annotationRestore, setAnnotationRestore] = useState<{ token: number; status: "applied" | "rejected"; text: string } | null>(null);
  const restoreAnnotationRef = useRef<{ token: number; rejected: string | null } | null>(null);
  const annotationKeyRef = useRef<string | null>(null);
  // Host-side guard of late panel requests and of the pocket overlay while an annotation is on.
  const annotationHostRef = useRef<{ runId: string | null; sourceHandle: string | null; blocked: string | null; on: boolean }>(
    { runId: null, sourceHandle: null, blocked: null, on: false });
  const exclusivityRef = useRef({ pocketOverlayActive: false, comparisonActive: false });
  // Only a prepared pocket source is shown through pocketView; a minimized source goes through openmmViewHandle so every
  // minimized-display rule (contact rows hidden, focus disabled, legend) applies unchanged.
  const [pocketView, setPocketView] = useState<{ handle: string; kind: "prepared_structure" } | null>(null);
  // The view that was on screen before a pocket selection switched the displayed source ("원래 소스로 돌아가기").
  const pocketReturnRef = useRef<{ shown: string; openmmViewHandle: string | null;
    pocketView: { handle: string; kind: "prepared_structure" } | null } | null>(null);
  const pocketKeyRef = useRef<string | null>(null);
  pocketKeyRef.current = pocketState?.request.key ?? null;
  // Host-side stale guard: the run and pocket sources the screen currently shows (read by late callbacks).
  const pocketHostRef = useRef<{ runId: string | null; sourceHandles: string[] }>({ runId: null, sourceHandles: [] });
  // Host-side stale guard for the M13 analysis panel: a late panel callback of another run is ignored.
  const analysisHostRef = useRef<{ runId: string | null }>({ runId: null });
  const analysisReportsReadRef = useRef(0);
  // M13 flow panel ↔ pocket panel: explicit chain selection (read-only import) and stored-set open requests that go
  // through the pocket panel's own "기록에서 다시 열기" guards.
  const [pocketChainSelection, setPocketChainSelection] = useState<{ runId: string; source: string; chains: string[] | null } | null>(null);
  const [pocketOpenRequest, setPocketOpenRequest] = useState<{ token: number; runId: string; setHandle: string } | null>(null);
  const pocketOpenToken = useRef(0);
  const pocketOpenResolvers = useRef(new Map<number, (refusal: string | null) => void>());
  const requestPocketOpen = useCallback((requestRunId: string, setHandle: string) => new Promise<string | null>(resolve => {
    for (const previous of pocketOpenResolvers.current.values()) previous("새 포켓 결과 열기 요청으로 대체되었습니다.");
    pocketOpenResolvers.current.clear();
    const token = ++pocketOpenToken.current;
    pocketOpenResolvers.current.set(token, resolve);
    setPocketOpenRequest({ token, runId: requestRunId, setHandle });
  }), []);
  const pocketOpenAnswered = useCallback((token: number, refusal: string | null) => {
    const resolve = pocketOpenResolvers.current.get(token);
    if (resolve) { pocketOpenResolvers.current.delete(token); resolve(refusal); }
  }, []);
  const [atomCatalogState, setAtomCatalogState] = useState<{ key: string; catalog: AtomCatalog } | null>(null);
  const [atomCatalogError, setAtomCatalogError] = useState("");
  const [atomReadRetry, setAtomReadRetry] = useState(0);
  const atomCatalogRequestRef = useRef<string | null>(null);
  const [movingCatalogState, setMovingCatalogState] = useState<{ key: string; catalog: AtomCatalog } | null>(null);
  const [referenceDraftCatalog, setReferenceDraftCatalog] = useState<{ key: string; catalog: AtomCatalog } | null>(null);
  const [movingDraftCatalog, setMovingDraftCatalog] = useState<{ key: string; catalog: AtomCatalog } | null>(null);
  const [referenceDraftError, setReferenceDraftError] = useState("");
  const [movingDraftError, setMovingDraftError] = useState("");
  const [movingReadRetry, setMovingReadRetry] = useState(0);
  const [draftReadRetry, setDraftReadRetry] = useState(0);
  const movingReadRequestRef = useRef<string | null>(null);
  const referenceDraftRequestRef = useRef<string | null>(null);
  const movingDraftRequestRef = useRef<string | null>(null);
  const [movingSourceState, setMovingSourceState] = useState<{ key: string; source: ViewerSource } | null>(null);
  const [measureMode, setMeasureMode] = useState(false);
  const [pendingAtom, setPendingAtom] = useState<AtomRefV1 | null>(null);
  const [lastPickedAtom, setLastPickedAtom] = useState<{ ref: AtomRefV1; layer: "reference" | "moving";
    sourceCoordinate_A: number[]; displayCoordinate_A: number[] } | null>(null);
  const [measurementSelection, setMeasurementSelection] = useState<{ handle: string; result: AtomDistance | RigidAlignment } | null>(null);
  const [distanceSourceHandle, setDistanceSourceHandle] = useState("");
  const [comparisonContext, setComparisonContext] = useState<{ handle: string; result: RigidAlignment } | null>(null);
  const [comparisonReference, setComparisonReference] = useState("");
  const [comparisonMoving, setComparisonMoving] = useState("");
  const [referenceSite, setReferenceSite] = useState("");
  const [movingSite, setMovingSite] = useState("");
  const [correspondence, setCorrespondence] = useState<{ reference: AtomRefV1; moving: AtomRefV1 }[]>([]);
  const [pairPickSide, setPairPickSide] = useState<"reference" | "moving" | null>(null);
  const [pickedPairHalf, setPickedPairHalf] = useState<AtomRefV1 | null>(null);
  const [comparisonAligned, setComparisonAligned] = useState(true);
  const [referenceVisible, setReferenceVisible] = useState(true);
  const [movingVisible, setMovingVisible] = useState(true);
  const [focusPair, setFocusPair] = useState<{ reference: AtomRefV1; moving: AtomRefV1; token: number } | null>(null);
  const [comparisonBusy, setComparisonBusy] = useState("");
  const comparisonBusyRef = useRef(false);
  const [comparisonError, setComparisonError] = useState("");
  const [comparisonReport, setComparisonReport] = useState<{ handle: string; resultHandle: string; markdown: string } | null>(null);
  const comparisonActionRef = useRef(0);
  const comparisonScopeRef = useRef("");
  const comparisonActionViewRef = useRef<string | null>(null);
  const comparisonReadControllerRef = useRef<AbortController | null>(null);
  const nextComparisonSignal = () => {
    comparisonReadControllerRef.current?.abort();
    const controller = new AbortController(); comparisonReadControllerRef.current = controller;
    return AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]);
  };
  const revokeComparisonAction = () => {
    comparisonReadControllerRef.current?.abort(); comparisonActionRef.current += 1;
    comparisonActionViewRef.current = null;
    comparisonBusyRef.current = false; setComparisonBusy("");
  };
  const [savedScenes, setSavedScenes] = useState<SavedSceneDetail[]>([]);
  const [savedFigures, setSavedFigures] = useState<SavedFigureDetail[]>([]);
  const [selectedSceneHandle, setSelectedSceneHandle] = useState("");
  const [selectedFigureHandle, setSelectedFigureHandle] = useState("");
  const [sceneReadRetry, setSceneReadRetry] = useState(0);
  const [sceneOverride, setSceneOverride] = useState<{ scene: SavedSceneDetail; token: number } | null>(null);
  const [restorePendingToken, setRestorePendingToken] = useState<number | null>(null);
  const [sceneBusy, setSceneBusy] = useState("");
  const [sceneError, setSceneError] = useState("");
  const [sceneStatus, setSceneStatus] = useState("");
  const [viewerSession, setViewerSession] = useState<ViewerSession | null>(null);
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
  const sceneControllerRef = useRef<SceneController | null>(null);
  const registerSceneController = useCallback((controller: SceneController | null) => { sceneControllerRef.current = controller; }, []);
  const sceneEpoch = useRef(0);
  const pendingRestoreTokenRef = useRef<number | null>(null);
  const sceneActionEpoch = useRef(0);
  const sceneReadAbort = useRef<AbortController | null>(null);
  const sceneContextRef = useRef<string | null>(null);
  const manualViewerInvalidator = useRef<(() => void) | null>(null);
  const viewerClientId = useRef<string | null>(null);
  if (!viewerClientId.current && typeof window !== "undefined") viewerClientId.current = crypto.randomUUID();
  const runId = run?.run_id;
  openmmRunRef.current = runId ?? null;
  analysisHostRef.current = { runId: runId ?? null };

  const refreshOpenmmBudget = useCallback(async (id: string, jobId: string, ticket: number) => {
    const request = ++budgetRequestRef.current;
    try {
      const snapshot = await api.budget(id);
      if (currentOpenmmBudgetRequest({ request, epoch: ticket, runId: id, jobId },
        { request: budgetRequestRef.current, epoch: epoch.current,
          runId: openmmRunRef.current, jobId: openmmJobRef.current })) setBudget(snapshot);
    } catch { /* A later poll or run reopen can retry the read. */ }
  }, []);

  // Global top line budget: one read on tab switch or chemical object change, no polling. Shares the
  // request counter with the OpenMM budget read so only the latest-started read reaches the page state.
  const refreshGlobalBudget = useCallback((id: string) => {
    const request = ++budgetRequestRef.current, ticket = epoch.current;
    api.budget(id).then(snapshot => {
      if (request === budgetRequestRef.current && ticket === epoch.current && openmmRunRef.current === id) setBudget(snapshot);
    }).catch(() => undefined);
  }, []);

  const reopen = useCallback(async (id: string) => {
    const ticket = ++epoch.current;
    sceneActionEpoch.current += 1; sceneReadAbort.current?.abort(); sceneReadAbort.current = null;
    sceneEpoch.current += 1; pendingRestoreTokenRef.current = null;
    setRestorePendingToken(null); setSceneBusy(""); setSceneError("");
    setError("");
    const [summary, log, limits, reports, jobs] = await Promise.all([api.run(id), api.allEvents(id), api.budget(id), api.reports(id), api.jobs(id)]);
    if (ticket !== epoch.current) return;
    const latest = latestHandles(log);
    const lastLoadSeq = [...resultEvents(log)].reverse().find(event => event.tool === "load_structure")?.seq ?? 0;
    const pendingUpload = [...log].reverse().find(event => event.type === "upload_received" && event.seq > lastLoadSeq);
    pocketHostRef.current = { runId: summary.run_id, sourceHandles: [] };
    setRun(summary); setEvents(log); setBudget(limits); setHandles(latest); setSavedReports(reports); setReportState(null); setSasaState(null); setMethodReportState(null);
    setChemicalActive(false); setChemicalSceneToRestore(null);
    setPocketState(null); setPocketReadback(null); setPocketOverlayError(null); setPocketNotice(null); setPocketView(null); pocketReturnRef.current = null;
    sceneEpoch.current += 1; setSceneOverride(null); setRestorePendingToken(null); setViewerSession(null); setSceneBusy(""); setSceneError(""); setSceneStatus("");
    setSavedScenes([]); setSavedFigures([]); setSelectedSceneHandle(""); setSelectedFigureHandle("");
    setOpenmmJobs(jobs.filter(job => job.protocol_id === "openmm_protein_minimize")); setOpenmmJobId(jobs.find(job => job.protocol_id === "openmm_protein_minimize")?.job_id ?? null); setOpenmmResult(null); setOpenmmReport(null); setOpenmmPreflight(null); setOpenmmPlan(null); setOpenmmViewHandle(null); setPocketView(null);
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
  const sourceOptions = [...new Map(events.filter((e): e is Extract<RunEvent, { type: "object_created" }> => e.type === "object_created" &&
    ["structure", "prepared_structure", "openmm_minimized_structure"].includes(e.kind))
    .map(e => [e.handle, { handle: e.handle, kind: e.kind }])).values()];
  const measurementOptions = [...new Map(events.filter((e): e is Extract<RunEvent, { type: "object_created" }> => e.type === "object_created" &&
    ["atom_distance", "rigid_alignment"].includes(e.kind))
    .map(e => [e.handle, { handle: e.handle, kind: e.kind }])).values()];
  const comparisonReferenceKind = sourceOptions.find(item => item.handle === comparisonContext?.result.reference_handle)?.kind as
    StructureData["kind"] | undefined;
  const distanceSourceKind = sourceOptions.find(item => item.handle === distanceSourceHandle)?.kind as StructureData["kind"] | undefined;
  const expectedKind = comparisonContext ? comparisonReferenceKind ?? "structure" : distanceSourceHandle ? distanceSourceKind ?? "structure" : sceneOverride ? sceneOverride.scene.value.structure_kind : pocketView ? pocketView.kind : openmmViewHandle ? "openmm_minimized_structure" : selectedMeasurement ? "prepared_structure" : selectedStructure
    ? selectedTool === "load_structure" ? "structure" : "prepared_structure"
    : handles.prepared ? "prepared_structure" : "structure";
  const associationError = !sceneOverride && !openmmViewHandle && !pocketView && selectedMeasurement && objectMeta &&
    (selectedHandle?.kind !== (selectedSasa ? "interface_sasa" : "interaction_set") || objectMeta.kind !== (selectedSasa ? "interface_sasa" : "interaction_set") ||
      objectMeta.schema !== (selectedSasa ? "interface_sasa@1" : "interaction_set@1") ||
      typeof objectMeta.summary.structure !== "string" || !objectMeta.summary.structure)
      ? "측정 객체에 확인 가능한 입력 구조가 없습니다." :
    !sceneOverride && !openmmViewHandle && !pocketView && selectedStructure && objectMeta && (selectedHandle?.kind !== expectedKind || objectMeta.kind !== expectedKind)
      ? "선택한 단계의 구조 종류가 객체 메타데이터와 일치하지 않습니다." : null;
  const targetHandle = comparisonContext?.result.reference_handle ?? (distanceSourceHandle || null) ?? sceneOverride?.scene.value.structure_handle ?? pocketView?.handle ?? openmmViewHandle ?? (selectedMeasurement
    ? !associationError && objectMeta ? String(objectMeta.summary.structure) : null
    : selectedStructure ? !associationError && objectMeta ? objectMeta.handle : null
      : pipelineHandle?.handle ?? null);
  const targetKey = runId && targetHandle ? JSON.stringify([runId, targetHandle, inspectionRevision,
    sceneOverride?.token ?? null, comparisonContext?.handle ?? null]) : null;
  const viewerContextKey = targetKey ? JSON.stringify([targetKey, viewIntent, selectedStep?.callId ?? null,
    sceneOverride?.token ?? null, comparisonContext?.handle ?? null]) : null;
  sceneContextRef.current = viewerContextKey;
  const sceneToken = useRef<{ key: string | null; generation: number }>({ key: null, generation: 0 });
  sceneToken.current = advanceSceneGeneration(sceneToken.current,
    JSON.stringify([viewerContextKey, viewerScopeRevision]));
  const displayData = inspectedStructure?.key === targetKey && inspectedStructure.status === "ready" ? inspectedStructure.data : null;
  const displaySource = displayData?.source ?? null;
  const atomCatalogKey = runId && displaySource
    ? catalogAttemptKey(runId, displaySource.handle, inspectionRevision, atomReadRetry) : null;
  const movingReadKey = runId && comparisonContext
    ? catalogAttemptKey(runId, comparisonContext.result.moving_handle, comparisonContext.handle, movingReadRetry) : null;
  const referenceDraftKey = runId && comparisonReference
    ? catalogAttemptKey(runId, comparisonReference, draftReadRetry) : null;
  const movingDraftKey = runId && comparisonMoving
    ? catalogAttemptKey(runId, comparisonMoving, draftReadRetry) : null;
  atomCatalogRequestRef.current = atomCatalogKey;
  movingReadRequestRef.current = movingReadKey;
  referenceDraftRequestRef.current = referenceDraftKey;
  movingDraftRequestRef.current = movingDraftKey;
  const atomCatalog = catalogForAttempt(atomCatalogState, atomCatalogKey);
  const movingCatalog = catalogForAttempt(movingCatalogState, movingReadKey);
  const movingSource = movingSourceState?.key === movingReadKey ? movingSourceState.source : null;
  const refDraft = catalogForAttempt(referenceDraftCatalog, referenceDraftKey);
  const movDraft = catalogForAttempt(movingDraftCatalog, movingDraftKey);
  const comparisonViewKey = comparisonViewIntentKey({ runId: runId ?? null, view: viewIntent,
    stepNumber: selectedStepNumber,
    latestHandle: latestResult?.output?.handle ?? null,
    pipelineHandle: (handles.interactions ?? pipelineHandle)?.handle ?? null,
    inspectionRevision, sceneToken: sceneOverride?.token ?? null,
    openmmHandle: openmmViewHandle, distanceHandle: distanceSourceHandle || null,
    comparisonHandle: comparisonContext?.handle ?? null, pocketHandle: pocketView?.handle ?? null });
  const comparisonScope = JSON.stringify([runId, comparisonReference, comparisonMoving,
    correspondence.map(pair => [pair.reference.site_index, pair.moving.site_index]),
    comparisonViewKey, measurementSelection?.handle ?? null]);
  comparisonScopeRef.current = comparisonScope;
  const beginComparisonAction = () => {
    comparisonActionViewRef.current = comparisonViewKey;
    return ++comparisonActionRef.current;
  };
  const comparisonActionCurrent = (action: number, id: string, scope: string, ticket: number) =>
    sameComparisonAction({ action: comparisonActionRef.current, epoch: epoch.current,
      runId: runId ?? "", scope: comparisonScopeRef.current },
    { action, epoch: ticket, runId: id, scope });
  useEffect(() => {
    setComparisonContext(null); setMeasurementSelection(null); setDistanceSourceHandle(""); setPendingAtom(null); setMeasureMode(false);
    comparisonReadControllerRef.current?.abort(); comparisonActionRef.current += 1;
    setCorrespondence([]); setComparisonReference(""); setComparisonMoving("");
    setAtomCatalogState(null); setMovingCatalogState(null); setMovingSourceState(null);
  }, [runId]);
  useEffect(() => {
    setPendingAtom(null); setLastPickedAtom(null); setPairPickSide(null);
    if (comparisonViewChangeRevokes(comparisonViewKey, comparisonActionViewRef.current)) {
      comparisonReadControllerRef.current?.abort(); comparisonActionRef.current += 1;
      comparisonBusyRef.current = false; setComparisonBusy("");
    }
  }, [comparisonViewKey]);
  useEffect(() => {
    setPendingAtom(null); setLastPickedAtom(null); setPairPickSide(null);
  }, [displaySource?.handle]);
  useEffect(() => {
    if (!runId || !displaySource || !atomCatalogKey) return;
    let active = true;
    const controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]);
    const key = atomCatalogKey;
    setAtomCatalogError("");
    api.allAtoms(runId, displaySource.handle, signal).then(catalog => {
      if (active && catalogResponseCurrent(key, atomCatalogRequestRef.current,
        catalog.structure_handle, displaySource.handle)) setAtomCatalogState(previous => retainCatalogState(previous, key, catalog));
    }).catch(e => { if (active && atomCatalogRequestRef.current === key)
      setAtomCatalogError(`원자 목록 읽기 실패: ${e instanceof Error ? e.message : String(e)}`); });
    return () => { active = false; controller.abort(); };
  }, [atomCatalogKey]);
  useEffect(() => {
    if (!runId || !comparisonContext || !movingReadKey) return;
    let active = true;
    const controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]);
    const handle = comparisonContext.result.moving_handle, key = movingReadKey;
    Promise.all([api.structure(runId, handle, signal), api.allAtoms(runId, handle, signal)]).then(([source, catalog]) => {
      if (!active || movingReadRequestRef.current !== key || source.handle !== handle ||
          catalog.structure_handle !== handle) return;
      setMovingSourceState({ key, source }); setMovingCatalogState({ key, catalog }); setComparisonError("");
    }).catch(e => { if (active && movingReadRequestRef.current === key)
      setComparisonError(`이동 구조 읽기 실패: ${e instanceof Error ? e.message : String(e)}`); });
    return () => { active = false; controller.abort(); };
  }, [movingReadKey]);
  useEffect(() => {
    if (!runId || !comparisonReference || !referenceDraftKey) return;
    let active = true;
    const controller = new AbortController();
    const key = referenceDraftKey;
    setReferenceDraftError("");
    api.allAtoms(runId, comparisonReference, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(catalog => {
      if (active && catalogResponseCurrent(key, referenceDraftRequestRef.current,
        catalog.structure_handle, comparisonReference)) {
        setReferenceDraftCatalog({ key, catalog }); setReferenceDraftError(""); }
    }).catch(e => { if (active && referenceDraftRequestRef.current === key)
      setReferenceDraftError(`기준 원자 목록 읽기 실패: ${e instanceof Error ? e.message : String(e)}`); });
    return () => { active = false; controller.abort(); };
  }, [referenceDraftKey]);
  useEffect(() => {
    if (!runId || !comparisonMoving || !movingDraftKey) return;
    let active = true;
    const controller = new AbortController();
    const key = movingDraftKey;
    setMovingDraftError("");
    api.allAtoms(runId, comparisonMoving, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(catalog => {
      if (active && catalogResponseCurrent(key, movingDraftRequestRef.current,
        catalog.structure_handle, comparisonMoving)) {
        setMovingDraftCatalog({ key, catalog }); setMovingDraftError(""); }
    }).catch(e => { if (active && movingDraftRequestRef.current === key)
      setMovingDraftError(`이동 원자 목록 읽기 실패: ${e instanceof Error ? e.message : String(e)}`); });
    return () => { active = false; controller.abort(); };
  }, [movingDraftKey]);
  const displayResidues = displayData?.residues ?? null;
  const viewerReady = !!viewerContextKey && viewerState?.key === viewerContextKey &&
    viewerState.status === "ready" && viewerState.source === displaySource;
  const m10SceneBlocked = !singleSourceSceneCompatible(!!comparisonContext, measureMode,
    !!pendingAtom, !!measurementSelection);
  const pocketGates = featureGates({ sourceKind: displayData?.kind ?? null, overlayActive: !!pocketState,
    comparisonActive: !!comparisonContext });
  const sceneBlocked = m10SceneBlocked || !!pocketGates.m9;
  const pocketSourceOptions = sourceOptions.filter((item): item is { handle: string; kind: "prepared_structure" | "openmm_minimized_structure" } =>
    item.kind === "prepared_structure" || item.kind === "openmm_minimized_structure");
  pocketHostRef.current = { runId: run?.run_id ?? null, sourceHandles: pocketSourceOptions.map(item => item.handle) };
  const pocketViewerReady = viewerReady && bridgeStateReady(viewerBridgeRef.current);
  // M16: the annotation panel follows the displayed (or loading) source; drawing needs the loaded source itself.
  const annotationSourceKind = targetHandle ? expectedKind : null;
  const siteGates = annotationGates({ sourceKind: displayData?.kind ?? null, annotationOn: !!annotationShown,
    pocketOverlayActive: !!pocketState, comparisonActive: !!comparisonContext });
  annotationHostRef.current = { runId: runId ?? null, sourceHandle: targetHandle, blocked: siteGates.annotation, on: !!annotationShown };
  exclusivityRef.current = { pocketOverlayActive: !!pocketState, comparisonActive: !!comparisonContext };
  const annotationRequest = useMemo(() => annotationShown ? siteAnnotationRequest(annotationShown) : null, [annotationShown]);
  annotationKeyRef.current = annotationRequest?.key ?? null;
  const annotationForViewer: SiteAnnotationRequest | null = annotationRequest && annotationShown?.runId === runId &&
    displaySource?.handle === annotationRequest.sourceHandle && !comparisonContext ? annotationRequest : null;
  const annotationApplied = annotationForViewer && annotationReadback?.key === annotationForViewer.key ? annotationReadback : null;
  // Run or source change, comparison start or an unsupported source turns a shown annotation off (spec 5.1, 5.3).
  useEffect(() => {
    if (annotationShown && !annotationShownCurrent(annotationShown, { runId: runId ?? null, sourceHandle: targetHandle,
      sourceKind: annotationSourceKind, comparisonActive: !!comparisonContext })) {
      setAnnotationShown(null); setAnnotationReadback(null); setAnnotationViewerError(null);
    }
  }, [annotationShown, runId, targetHandle, annotationSourceKind, comparisonContext]);
  const requestAnnotation = (requestRunId: string, request: SiteAnnotationShown | null) => {
    if (!annotationShowAccepted(request, requestRunId, annotationHostRef.current)) return;
    setAnnotationReadback(null); setAnnotationViewerError(null); setAnnotationRestore(null);
    setAnnotationShown(request);
  };
  useEffect(() => {
    const decision = overlayContextDecision(pocketState?.request ?? null, pocketState?.boundContext ?? null,
      viewerContextKey, displaySource?.handle ?? null, pocketViewerReady);
    if (decision.action === "bind" && viewerContextKey)
      setPocketState(previous => previous && previous.boundContext === null ? { ...previous, boundContext: viewerContextKey } : previous);
    else if (decision.action === "clear") {
      setPocketState(null); setPocketReadback(null); setPocketOverlayError(null); setPocketNotice(decision.reason);
    }
  }, [pocketState, viewerContextKey, displaySource?.handle, pocketViewerReady]);
  const pocketOverlayForViewer = pocketState && pocketState.boundContext === viewerContextKey &&
    displaySource?.handle === pocketState.request.sourceHandle ? pocketState.request : null;
  const requestPocketOverlay = (request: PocketOverlayRequest | null) => {
    if (!pocketRequestAccepted(request, pocketHostRef.current)) return;
    if (request && annotationHostRef.current.on) { setPocketNotice(ANNOTATION_BLOCKS_POCKET_OVERLAY); return; }
    setPocketOverlayError(null); setPocketNotice(null);
    if (!request) { setPocketState(null); setPocketReadback(null); return; }
    setPocketState(previous => ({ request, boundContext: previous && previous.request.key === request.key &&
      previous.request.sourceHandle === request.sourceHandle ? previous.boundContext : null }));
  };
  const bridgeState = viewerBridgeRef.current?.snapshot();
  const sceneSessionReady = viewerReady && !!viewerSession &&
    viewerSession.structure_handle === displaySource?.handle &&
    viewerSession.scene_generation === sceneToken.current.generation &&
    bridgeState?.ready === true && bridgeState.catalogReady === true &&
    bridgeState.sessionId === viewerSession.viewer_session_id &&
    bridgeState.generation === viewerSession.scene_generation;
  const focusEnabled = viewerReady && bridgeState?.catalogReady === true && !busy &&
    !openmmViewHandle && !sceneOverride && !comparisonContext;
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
  // A completed OpenMM job publishes its minimized structure through job events; re-read the log so the new
  // openmm_minimized_structure becomes an ordinary source option (M12 pocket detection) without a run reload.
  useEffect(() => {
    if (!runId || !openmmOutput) return;
    const ticket = epoch.current;
    const controller = new AbortController();
    api.allEvents(runId, controller.signal).then(log => {
      if (ticket === epoch.current) setEvents(previous => log.length >= previous.length ? log : previous);
    }).catch(() => undefined);
    return () => controller.abort();
  }, [runId, openmmOutput]);
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
  const displayDiffersFromPipeline = !!targetHandle && targetHandle !== pipelineHandle?.handle;
  const mutationDisabled = !!busy || !!sceneOverride || inspecting || (!!selectedHandle && (!targetHandle || displayDiffersFromPipeline));

  useEffect(() => {
    if (!runId) return;
    let active = true;
    const ticket = epoch.current;
    void Promise.all([api.savedScenes(runId), api.savedFigures(runId)]).then(async ([scenes, figures]) => {
      const [moreScenes, moreFigures] = await Promise.all([
        scenes.total > scenes.rows.length ? api.savedScenes(runId, 50) : Promise.resolve(null),
        figures.total > figures.rows.length ? api.savedFigures(runId, 50) : Promise.resolve(null),
      ]);
      if (!active || ticket !== epoch.current) return;
      const sceneRows = [...scenes.rows, ...(moreScenes?.rows ?? [])];
      const figureRows = [...figures.rows, ...(moreFigures?.rows ?? [])];
      setSavedScenes(previous => mergeSavedRows(previous, sceneRows));
      setSavedFigures(previous => mergeSavedRows(previous, figureRows));
      setSelectedSceneHandle(previous => previous || sceneRows[0]?.handle || "");
      setSelectedFigureHandle(previous => previous || figureRows[0]?.handle || "");
      setSceneError("");
    }).catch(e => { if (active && ticket === epoch.current) setSceneError(`저장된 보기 목록을 읽지 못했습니다: ${e instanceof Error ? e.message : String(e)}`); });
    return () => { active = false; };
  }, [runId, sceneReadRetry]);

  const restoredSceneToken = useRef(0);
  useEffect(() => {
    if (!sceneOverride) return;
    const token = sceneOverride.token;
    const timeout = setTimeout(() => {
      if (sceneEpoch.current === token && restoredSceneToken.current !== token) {
        sceneEpoch.current += 1; viewerBridgeRef.current?.invalidate();
        pendingRestoreTokenRef.current = null;
        setRestorePendingToken(null);
        setSceneBusy(""); setSceneError("저장된 보기 준비가 30초 안에 끝나지 않았습니다. 다시 읽어 복원하세요.");
      }
    }, 30000);
    return () => clearTimeout(timeout);
  }, [sceneOverride]);
  useEffect(() => {
    if (!sceneOverride || !runId || !viewerReady || !viewerSession || !displaySource || !viewerContextKey ||
        sceneEpoch.current !== sceneOverride.token || pendingRestoreTokenRef.current !== sceneOverride.token ||
        restoredSceneToken.current === sceneOverride.token ||
        viewerSession.scene_generation !== sceneToken.current.generation ||
        viewerSession.structure_handle !== sceneOverride.scene.value.structure_handle) return;
    const current = sceneOverride;
    const binding: ViewerBinding = { sessionId: viewerSession.viewer_session_id,
      clientId: viewerSession.client_instance_id, generation: viewerSession.scene_generation,
      sourceHandle: viewerSession.structure_handle, catalogHash: viewerSession.catalog_hash,
      actionRevision: viewerSession.action_revision };
    const bridge = viewerBridgeRef.current;
    if (!bridge || !bridge.snapshot().catalogReady) return;
    // viewer_scene@2: the annotation prop must already hold the same request (set with the scene override).
    const annotationRef = sceneAnnotation(current.scene.value);
    const plan = restoreAnnotationRef.current?.token === current.token ? restoreAnnotationRef.current : null;
    const annotationArg = annotationRef && plan && !plan.rejected && annotationForViewer &&
      annotationForViewer.handle === annotationRef.handle && annotationForViewer.legend === annotationRef.legend
      ? annotationForViewer : null;
    // A rejected annotation restore also withdraws the annotation request, so the normal draw cannot show it later.
    const withdrawRestoredAnnotation = (handle: string) => {
      setAnnotationShown(previous => previous && previous.handle === handle ? null : previous);
      setAnnotationReadback(null); setAnnotationViewerError(null);
    };
    if (annotationRef && !annotationArg && plan && !plan.rejected) {
      setAnnotationRestore({ token: current.token, status: "rejected", text: "주석 요청이 준비되지 않아 주석은 복원하지 않았습니다." });
      withdrawRestoredAnnotation(annotationRef.handle);
    }
    restoredSceneToken.current = current.token;
    setSceneBusy("복원 중"); setSceneError("");
    void bridge.restoreScene(binding, current.scene.value, annotationArg).then(restored => {
      if (sceneEpoch.current !== current.token || !sceneMatches(restored, current.scene.value)) return;
      const outcome = restored.siteAnnotation;
      if (outcome) setAnnotationRestore({ token: current.token, status: outcome.status, text: outcome.status === "applied"
        ? `참조 주석 다시 그림 · 부위 ${outcome.readback.drawnSiteCount}개 · 점선 ${outcome.readback.drawnLineCount}개 (Mol* 읽기 확인)`
        : `참조 주석 복원 거부: ${outcome.reason}` });
      if (outcome?.status === "rejected" && annotationRef) withdrawRestoredAnnotation(annotationRef.handle);
      restoredSceneToken.current = current.token;
      pendingRestoreTokenRef.current = null;
      setRestorePendingToken(null);
      setRepresentation(current.scene.value.representation === "ball_and_stick" ? "ball-and-stick" : current.scene.value.representation);
      setFocusedResidue(current.scene.value.selection ? { key: viewerContextKey, residue: current.scene.value.selection } : null);
      setHighlight(null); setSceneStatus(`저장된 보기 복원 완료 · ${current.scene.value.name}`);
    }).catch(e => {
      if (sceneEpoch.current === current.token) { pendingRestoreTokenRef.current = null; setRestorePendingToken(null);
        setSceneError(`저장된 보기 복원 실패: ${e instanceof Error ? e.message : String(e)}`); }
    }).finally(() => { if (sceneEpoch.current === current.token) setSceneBusy(""); });
  }, [sceneOverride, runId, viewerReady, viewerSession, displaySource, viewerContextKey, bridgeState?.catalogReady, annotationForViewer]);

  useEffect(() => {
    if (sceneOverride && displayedError) {
      setSceneBusy("");
      setSceneError(`저장된 보기의 구조를 불러오지 못했습니다: ${displayedError}`);
    }
  }, [sceneOverride, displayedError]);

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
        const meta = await beforeDeadline(api.meta(runId, targetHandle), 30000);
        if (meta.handle !== targetHandle || meta.kind !== expectedKind) throw new Error("입력 구조의 handle 또는 종류가 측정 기록과 일치하지 않습니다.");
        const [source, residues] = await beforeDeadline(Promise.all([api.structure(runId, targetHandle), api.residues(runId, targetHandle)]), 30000);
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
    if (!viewerReady || !viewerContextKey || measureMode || pairPickSide || comparisonContext) return;
    cancelPendingRestore();
    if (!ref) {
      manualViewerInvalidator.current?.();
      setHighlight(null); setFocusedResidue(null); setFocusError(null);
      return;
    }
    const matches = displayResidues?.residues.filter(item => sameResidueRef(item, ref)) ?? [];
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
    cancelPendingRestore();
    manualViewerInvalidator.current?.();
    setFocusError(null);
    setHighlight({ key: viewerContextKey, residue: ref });
  }
  function toggleTheme() {
    cancelPendingRestore();
    manualViewerInvalidator.current?.();
    const root = document.documentElement;
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
  }

  function bindingFor(session: ViewerSession): ViewerBinding {
    return { sessionId: session.viewer_session_id, clientId: session.client_instance_id,
      generation: session.scene_generation, sourceHandle: session.structure_handle,
      catalogHash: session.catalog_hash, actionRevision: session.action_revision };
  }
  function requestBinding(session: ViewerSession) {
    return { client_instance_id: session.client_instance_id, viewer_session_id: session.viewer_session_id,
      scene_generation: session.scene_generation, action_revision: session.action_revision,
      request_id: crypto.randomUUID() };
  }
  function sameSceneAction(action: number, ticket: number, context: string | null): boolean {
    return sceneActionEpoch.current === action && epoch.current === ticket && sceneContextRef.current === context;
  }
  function matchesCurrentNative(bridge: ViewerBridge, session: ViewerSession, captured: NativeSceneState): boolean {
    const snapshot = bridge.snapshot();
    return snapshot.ready && snapshot.sourceHandle === session.structure_handle &&
      snapshot.sessionId === session.viewer_session_id && snapshot.generation === session.scene_generation &&
      !!snapshot.nativeCamera && !!snapshot.representation &&
      sceneMatches({ structure_handle: snapshot.sourceHandle, selection: snapshot.selection,
        representation: snapshot.representation === "ball-and-stick" ? "ball_and_stick" : snapshot.representation,
        camera: snapshot.nativeCamera, theme: snapshot.theme }, captured);
  }
  function cancelPendingRestore() {
    if (!sceneReadAbort.current && pendingRestoreTokenRef.current === null) return;
    sceneActionEpoch.current += 1;
    sceneReadAbort.current?.abort(); sceneReadAbort.current = null;
    if (pendingRestoreTokenRef.current !== null) sceneEpoch.current += 1;
    pendingRestoreTokenRef.current = null; setRestorePendingToken(null);
    viewerBridgeRef.current?.cancelNative();
    setSceneBusy(""); setSceneError("수동 뷰어 작업으로 저장된 보기 복원이 취소되었습니다.");
  }
  function exitSceneOverride() {
    sceneActionEpoch.current += 1; sceneEpoch.current += 1;
    sceneReadAbort.current?.abort(); sceneReadAbort.current = null;
    pendingRestoreTokenRef.current = null;
    viewerBridgeRef.current?.invalidate(); void sceneControllerRef.current?.detach();
    setSceneOverride(null); setRestorePendingToken(null); setSceneBusy(""); setSceneError(""); setSceneStatus("");
    setHighlight(null); setFocusedResidue(null); setFocusError(null);
  }
  async function saveCurrentScene() {
    if (!runId || !sceneSessionReady || !sceneName.trim() || sceneBusy || sceneBlocked) return;
    const ticket = epoch.current, action = ++sceneActionEpoch.current;
    const context = viewerContextKey, name = sceneName.trim(), id = runId;
    setSceneBusy("저장 중"); setSceneError(""); setSceneStatus("");
    try {
      const session = await sceneControllerRef.current?.settledSession();
      const bridge = viewerBridgeRef.current;
      if (!sameSceneAction(action, ticket, context)) return;
      if (!session || !bridge || session.structure_handle !== displaySource?.handle) throw new Error("현재 뷰어 세션이 안정될 때까지 기다리세요.");
      // A shown annotation is recorded as viewer_scene@2; without one the viewer_scene@1 body is sent unchanged.
      if (annotationShown && !annotationForViewer) throw new Error(ANNOTATION_REQUEST_NOT_READY);
      const annotationRef = annotationForViewer ? { handle: annotationForViewer.handle, legend: annotationForViewer.legend } : null;
      const native = await bridge.captureScene(bindingFor(session), annotationRef);
      if (!sameSceneAction(action, ticket, context)) return;
      const saved = await api.saveScene(id, sceneSaveBody({ ...requestBinding(session), schema: "viewer_scene@1" as const, name, ...native },
        annotationRef));
      const currentSession = await sceneControllerRef.current?.settledSession();
      if (!sameSceneAction(action, ticket, context)) return;
      if (!currentSession ||
          currentSession.viewer_session_id !== session.viewer_session_id ||
          currentSession.action_revision !== session.action_revision ||
          !matchesCurrentNative(bridge, session, native)) {
        setSavedScenes(previous => mergeSavedRows(previous, [saved]));
        setSceneStatus("보기는 저장되었지만 현재 장면이 바뀌었습니다. 저장된 보기에서 다시 선택하세요.");
        return;
      }
      setSavedScenes(previous => previous.some(row => row.handle === saved.handle) ? previous : [...previous, saved]);
      setSelectedSceneHandle(saved.handle); setSceneName(""); setSceneStatus(`보기 저장 완료 · ${saved.value.name}`);
    } catch (e) { if (sameSceneAction(action, ticket, context)) setSceneError(`보기 저장 실패: ${e instanceof Error ? e.message : String(e)}`); }
    finally { if (sceneActionEpoch.current === action && ticket === epoch.current) setSceneBusy(""); }
  }
  async function restoreSavedScene(requestedHandle?: string) {
    if (!runId || !(requestedHandle ?? selectedSceneHandle)) return;
    // viewer_scene@2 is refused while a pocket overlay or a comparison is on, before any side effect (spec 5.4).
    const listed = savedScenes.find(row => row.handle === (requestedHandle ?? selectedSceneHandle));
    const early = listed ? sceneRestoreDecision(listed.value, exclusivityRef.current) : null;
    if (early && !early.allowed) { setSceneStatus(""); setSceneError(early.reason ?? ""); return; }
    revokeComparisonAction(); setPendingAtom(null);
    const ticket = epoch.current, action = ++sceneActionEpoch.current;
    const context = viewerContextKey, id = runId, selected = requestedHandle ?? selectedSceneHandle;
    // A newer read owns the restore result immediately. In particular, an
    // older native restore must not finish while this detail GET is held and
    // then clear the newer request's status or apply its camera.
    if (pendingRestoreTokenRef.current !== null) {
      sceneEpoch.current += 1;
      pendingRestoreTokenRef.current = null;
      setRestorePendingToken(null);
      viewerBridgeRef.current?.cancelNative();
    }
    sceneReadAbort.current?.abort();
    const controller = new AbortController(); sceneReadAbort.current = controller;
    manualViewerInvalidator.current?.();
    setSceneBusy("읽는 중"); setSceneError(""); setSceneStatus("");
    try {
      const detail = await api.savedScene(id, selected, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]));
      if (!sameSceneAction(action, ticket, context) || detail.handle !== selected) return;
      const decision = sceneRestoreDecision(detail.value, exclusivityRef.current);
      if (!decision.allowed) { setSceneError(decision.reason ?? ""); setSceneBusy(""); return; }
      // viewer_scene@2: the stored annotation is read (no tool call) and set as the viewer prop before the restore.
      const annotationRef = sceneAnnotation(detail.value);
      let restoredAnnotation: SiteAnnotationShown | null = null, annotationRejected: string | null = null;
      if (annotationRef) {
        try {
          const read = await api.siteAnnotation(id, annotationRef.handle, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]));
          if (!sameSceneAction(action, ticket, context)) return;
          if (read.meta.handle !== annotationRef.handle || read.annotation.schema !== "reference_site_annotation@1" ||
              read.annotation.structure.handle !== detail.value.structure_handle)
            throw new Error("저장된 보기의 주석이 보기의 구조와 다릅니다.");
          restoredAnnotation = { runId: id, sourceHandle: detail.value.structure_handle, handle: annotationRef.handle,
            annotation: read.annotation, legend: annotationRef.legend };
        } catch (e) {
          if (!sameSceneAction(action, ticket, context)) return;
          annotationRejected = `주석을 읽지 못했습니다: ${e instanceof Error ? e.message : String(e)}`;
        }
        const again = sceneRestoreDecision(detail.value, exclusivityRef.current);
        if (!again.allowed) { setSceneError(again.reason ?? ""); setSceneBusy(""); return; }
      }
      setComparisonContext(null); setDistanceSourceHandle(""); setMeasureMode(false); setPendingAtom(null); setPairPickSide(null);
      setMeasurementSelection(null); setComparisonReport(null); setFocusPair(null); setLastPickedAtom(null);
      const token = ++sceneEpoch.current;
      pendingRestoreTokenRef.current = token;
      restoreAnnotationRef.current = annotationRef ? { token, rejected: annotationRejected } : null;
      setAnnotationShown(restoredAnnotation); setAnnotationReadback(null); setAnnotationViewerError(null);
      setAnnotationRestore(annotationRejected ? { token, status: "rejected", text: annotationRejected } : null);
      setRepresentation(detail.value.representation === "ball_and_stick" ? "ball-and-stick" : detail.value.representation);
      setSceneOverride({ scene: detail, token }); setRestorePendingToken(token);
      setHighlight(null); setFocusedResidue(null); setFocusError(null);
      setSceneBusy("구조를 불러오는 중");
    } catch (e) { if (sameSceneAction(action, ticket, context)) { setSceneError(`저장된 보기 읽기 실패: ${e instanceof Error ? e.message : String(e)}`); setSceneBusy(""); } }
    finally { if (sceneReadAbort.current === controller) sceneReadAbort.current = null; }
  }
  function returnToCurrentStructure() {
    exitSceneOverride();
    setInspectionRevision(value => value + 1);
  }
  function onComparisonAtomPick(ref: AtomRefV1, layer: "reference" | "moving") {
    if (comparisonBusyRef.current || comparisonBusy) return;
    setComparisonError("");
    const selectedCatalog = layer === "moving" ? movingCatalog : atomCatalog;
    const sourceCoordinate_A = selectedCatalog?.rows.find(row => row.ref.site_index === ref.site_index)?.coordinate_A;
    const nativePick = viewerBridgeRef.current?.snapshot().lastAtomPick;
    if (sourceCoordinate_A && nativePick?.ref.site_index === ref.site_index && nativePick.layer === layer)
      setLastPickedAtom({ ref, layer, sourceCoordinate_A, displayCoordinate_A: nativePick.worldCoordinate_A });
    if (pairPickSide) {
      const wanted = pairPickSide === "reference" ? comparisonReference : comparisonMoving;
      if (ref.structure_handle !== wanted) {
        setComparisonError(`선택한 ${pairPickSide === "reference" ? "기준" : "이동"} 구조의 원자를 클릭하세요.`);
        return;
      }
      if (ref.atom_name !== "CA" || !selectedCatalog?.rows.find(row =>
          row.ref.site_index === ref.site_index)?.protein) {
        setComparisonError("대응에는 단백질 CA 원자만 사용할 수 있습니다."); return; }
      if (pairPickSide === "reference") setReferenceSite(String(ref.site_index));
      else setMovingSite(String(ref.site_index));
      setPairPickSide(null);
      return;
    }
    if (!measureMode) return;
    if (!pendingAtom) { setPendingAtom(ref); return; }
    if (pendingAtom.structure_handle !== ref.structure_handle) {
      setPendingAtom(null);
      setComparisonError("서로 다른 층의 원자는 측정할 수 없습니다. 같은 구조에서 첫 원자를 다시 선택하세요.");
      return;
    }
    const id = runId, first = pendingAtom;
    setPendingAtom(null);
    if (!id) return;
    const ticket = epoch.current, action = beginComparisonAction(), scope = comparisonScope;
    const signal = nextComparisonSignal();
    comparisonBusyRef.current = true; setComparisonBusy("원자 거리 계산 중");
    void api.command(id, "measure_distance", { structure: ref.structure_handle, first, second: ref }, signal)
      .then(async response => {
        if (!response.ok) throw new Error("message" in response ? response.message : "거리 계산을 완료하지 못했습니다.");
        const selected = await api.measurement(id, response.handle.handle, signal);
        const log = await api.allEvents(id, signal);
        if (!comparisonActionCurrent(action, id, scope, ticket) || selected.result.schema !== "atom_distance@1" ||
            selected.meta.handle !== response.handle.handle) return;
        comparisonBusyRef.current = false; setComparisonBusy("");
        setMeasurementSelection({ handle: response.handle.handle, result: selected.result });
        setComparisonReport(null); setEvents(log);
      }).catch(e => { if (comparisonActionCurrent(action, id, scope, ticket))
        setComparisonError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (comparisonActionCurrent(action, id, scope, ticket)) {
        comparisonBusyRef.current = false; setComparisonBusy(""); } });
  }
  function addCorrespondence() {
    const a = refDraft?.rows.find(row => row.ref.site_index === Number(referenceSite));
    const b = movDraft?.rows.find(row => row.ref.site_index === Number(movingSite));
    if (!referenceSite || !movingSite || !a || !b || !a.protein || !b.protein ||
        a.ref.atom_name !== "CA" || b.ref.atom_name !== "CA") {
      setComparisonError("양쪽 구조의 정확한 단백질 CA site를 선택하세요."); return;
    }
    if (correspondence.some(pair => pair.reference.site_index === a.ref.site_index ||
        pair.moving.site_index === b.ref.site_index)) {
      setComparisonError("같은 CA site는 한 번만 대응시킬 수 있습니다."); return;
    }
    revokeComparisonAction();
    setCorrespondence(previous => [...previous, { reference: a.ref, moving: b.ref }]);
    setReferenceSite(""); setMovingSite(""); setComparisonError("");
  }
  async function computeAlignment() {
    if (!runId || !comparisonReference || !comparisonMoving || correspondence.length < 3 || comparisonBusy) return;
    const id = runId, ticket = epoch.current, action = beginComparisonAction(), scope = comparisonScope;
    const signal = nextComparisonSignal();
    comparisonBusyRef.current = true; setComparisonBusy("명시한 CA 대응 정렬 계산 중"); setComparisonError("");
    try {
      const response = await api.command(id, "align_structures", { reference: comparisonReference,
        moving: comparisonMoving, pairs: correspondence }, signal);
      if (!response.ok) throw new Error("message" in response ? response.message : "정렬 계산을 완료하지 못했습니다.");
      const selected = await api.measurement(id, response.handle.handle, signal);
      const log = await api.allEvents(id, signal);
      if (!comparisonActionCurrent(action, id, scope, ticket) || selected.result.schema !== "rigid_alignment@1" ||
          selected.meta.handle !== response.handle.handle || selected.result.reference_handle !== comparisonReference ||
          selected.result.moving_handle !== comparisonMoving) return;
      comparisonBusyRef.current = false; setComparisonBusy("");
      manualViewerInvalidator.current?.(); viewerBridgeRef.current?.invalidate();
      exitSceneOverride(); setOpenmmViewHandle(null); setPocketView(null); setHighlight(null); setFocusedResidue(null);
      setDistanceSourceHandle(""); setFocusPair(null); setComparisonContext({ handle: response.handle.handle, result: selected.result });
      setMeasurementSelection({ handle: response.handle.handle, result: selected.result });
      setComparisonAligned(true); setReferenceVisible(true); setMovingVisible(true);
      setMeasureMode(false); setPendingAtom(null); setComparisonReport(null);
      setEvents(log);
    } catch (e) { if (comparisonActionCurrent(action, id, scope, ticket))
      setComparisonError(e instanceof Error ? e.message : String(e)); }
    finally { if (comparisonActionCurrent(action, id, scope, ticket)) {
      comparisonBusyRef.current = false; setComparisonBusy(""); } }
  }
  async function reopenMeasurement(handle: string) {
    if (!runId || !handle) return;
    const id = runId, ticket = epoch.current, action = beginComparisonAction(), scope = comparisonScope;
    const signal = nextComparisonSignal();
    comparisonBusyRef.current = true; setComparisonBusy("저장된 측정 읽는 중"); setComparisonError("");
    try {
      const { meta, result } = await api.measurement(id, handle, signal);
      if (!comparisonActionCurrent(action, id, scope, ticket) || meta.handle !== handle) return;
      comparisonBusyRef.current = false; setComparisonBusy("");
      setMeasurementSelection({ handle, result }); setComparisonReport(null); setFocusPair(null);
      if (result.schema === "rigid_alignment@1") {
        manualViewerInvalidator.current?.(); viewerBridgeRef.current?.invalidate();
        exitSceneOverride(); setOpenmmViewHandle(null); setPocketView(null); setDistanceSourceHandle(""); setComparisonContext({ handle, result });
        setComparisonReference(result.reference_handle); setComparisonMoving(result.moving_handle);
        setCorrespondence(result.pairs.map(pair => ({ reference: pair.reference, moving: pair.moving })));
        setComparisonAligned(true); setReferenceVisible(true); setMovingVisible(true);
      } else {
        manualViewerInvalidator.current?.(); viewerBridgeRef.current?.invalidate();
        exitSceneOverride(); setOpenmmViewHandle(null); setPocketView(null); setComparisonContext(null);
        setDistanceSourceHandle(result.structure_handle); setMeasureMode(true);
      }
    } catch (e) { if (comparisonActionCurrent(action, id, scope, ticket))
      setComparisonError(e instanceof Error ? e.message : String(e)); }
    finally { if (comparisonActionCurrent(action, id, scope, ticket)) {
      comparisonBusyRef.current = false; setComparisonBusy(""); } }
  }
  async function createComparisonReport() {
    if (!runId || !measurementSelection) return;
    const id = runId, selected = measurementSelection.handle, ticket = epoch.current;
    const action = beginComparisonAction(), scope = comparisonScope;
    const signal = nextComparisonSignal();
    comparisonBusyRef.current = true; setComparisonBusy("측정 보고서 저장 중"); setComparisonError("");
    try {
      const existing = savedReports.find(row => row.result_handle === selected &&
        ["atom_distance", "rigid_alignment"].includes(row.analysis_type ?? ""));
      const artifact = existing ? await api.methodReport(id, existing.handle, signal) : await api.createMethodReport(id, selected, signal);
      if (!comparisonActionCurrent(action, id, scope, ticket) || artifact.manifest.result_handle !== selected) return;
      setComparisonReport({ handle: artifact.handle, resultHandle: selected, markdown: artifact.markdown });
      if (!existing) { const refreshed = await api.reports(id, signal);
        if (comparisonActionCurrent(action, id, scope, ticket)) setSavedReports(refreshed); }
    } catch (e) { if (comparisonActionCurrent(action, id, scope, ticket))
      setComparisonError(e instanceof Error ? e.message : String(e)); }
    finally { if (comparisonActionCurrent(action, id, scope, ticket)) {
      comparisonBusyRef.current = false; setComparisonBusy(""); } }
  }
  async function exportCurrentFigure() {
    if (!runId || !selectedSceneHandle || !sceneSessionReady || sceneBusy || sceneBlocked) return;
    const ticket = epoch.current, action = ++sceneActionEpoch.current;
    const context = viewerContextKey, id = runId, selected = selectedSceneHandle;
    setSceneBusy("PNG 생성 중"); setSceneError(""); setSceneStatus("");
    try {
      const scene = await api.savedScene(id, selected);
      if (!sameSceneAction(action, ticket, context) || scene.handle !== selected) return;
      const session = await sceneControllerRef.current?.settledSession();
      const bridge = viewerBridgeRef.current;
      if (!sameSceneAction(action, ticket, context)) return;
      if (!session || !bridge || session.structure_handle !== scene.value.structure_handle) throw new Error("저장된 보기의 구조와 현재 세션이 다릅니다.");
      const image = await bridge.captureFigure(bindingFor(session), scene.value, sceneAnnotation(scene.value));
      if (!sameSceneAction(action, ticket, context)) return;
      const figure = await api.saveFigure(id, figureSaveBody({ ...requestBinding(session), schema: "viewer_figure@1" as const,
        scene_handle: scene.handle, ...image.state, png_base64: image.pngBase64 }, scene.value.schema, image.legendComposited));
      const currentSession = await sceneControllerRef.current?.settledSession();
      if (!sameSceneAction(action, ticket, context)) return;
      if (!currentSession ||
          currentSession.viewer_session_id !== session.viewer_session_id ||
          currentSession.action_revision !== session.action_revision ||
          !matchesCurrentNative(bridge, session, image.state)) {
        setSavedFigures(previous => mergeSavedRows(previous, [figure]));
        setSceneStatus("그림은 저장되었지만 현재 장면이 바뀌었습니다. 저장된 그림에서 다시 선택하세요.");
        return;
      }
      setSavedFigures(previous => previous.some(row => row.handle === figure.handle) ? previous : [...previous, figure]);
      setSelectedFigureHandle(figure.handle); setSceneStatus(`PNG 및 출처 JSON 저장 완료 · ${figure.handle}`);
    } catch (e) { if (sameSceneAction(action, ticket, context)) setSceneError(`PNG 내보내기 실패: ${e instanceof Error ? e.message : String(e)}`); }
    finally { if (sceneActionEpoch.current === action && ticket === epoch.current) setSceneBusy(""); }
  }

  function enterChemical() {
    cancelPendingRestore(); revokeComparisonAction(); viewerBridgeRef.current?.invalidate();
    setMeasureMode(false); setPendingAtom(null); setPairPickSide(null);
    setMeasurementSelection(null); setComparisonContext(null); setFocusPair(null);
    setPocketState(null); setPocketReadback(null); setPocketView(null);
    setAnnotationShown(null); setAnnotationReadback(null); setAnnotationViewerError(null);
    setChemicalActive(true);
  }
  /** A workflow step may have created objects (prepared/chemical/minimized structures, reports): re-read this run's
   * event log and saved report list so they become ordinary source, history and saved-report options without a
   * reload. A newer run or reopen wins; for reports, only the latest such read may apply (no late overwrite). */
  function refreshEventsFromAnalysis(requestRunId: string) {
    if (!hostRequestAccepted({ runId: requestRunId }, analysisHostRef.current)) return;
    const ticket = epoch.current;
    const current = () => ticket === epoch.current && hostRequestAccepted({ runId: requestRunId }, analysisHostRef.current);
    api.allEvents(requestRunId).then(log => {
      if (current()) setEvents(previous => newerEventLog(previous, log));
    }).catch(() => undefined);
    const read = ++analysisReportsReadRef.current;
    api.reports(requestRunId).then(reports => {
      if (current() && read === analysisReportsReadRef.current) setSavedReports(reports);
    }).catch(() => undefined);
  }
  function enterChemicalFromAnalysis(requestRunId: string) {
    if (!hostRequestAccepted({ runId: requestRunId }, analysisHostRef.current)) return;
    const blocked = chemicalEntryBlockedReason(busy);
    if (blocked) { setError(blocked); return; }
    enterChemical();
  }
  /** Opens a workflow step result through the existing page paths and guards (no new Mol* operation). */
  async function openAnalysisResult(request: AnalysisOpenRequest): Promise<string | null> {
    if (!hostRequestAccepted(request, analysisHostRef.current)) return "다른 run의 요청입니다.";
    if (request.view === "pocket") return request.handle ? requestPocketOpen(request.runId, request.handle) : "포켓 결과 handle이 없습니다.";
    const id = request.runId, ticket = epoch.current;
    const accepted = () => ticket === epoch.current && hostRequestAccepted(request, analysisHostRef.current);
    try {
      if (request.view === "measurement" && request.handle) { await reopenMeasurement(request.handle); return null; }
      if (request.view === "openmm" && request.jobId) {
        const jobId = request.jobId;
        const job = await api.job(id, jobId);
        if (!accepted()) return null;
        if (job.run_id !== id || job.job_id !== jobId || job.protocol_id !== "openmm_protein_minimize")
          throw new Error("분석 흐름의 OpenMM 작업이 요청과 다릅니다.");
        setOpenmmJobs(old => [job, ...old.filter(item => item.job_id !== jobId)]);
        openmmJobRef.current = jobId; openmmOutputRef.current = undefined;
        setOpenmmJobId(jobId); setOpenmmViewHandle(null); setPocketView(null);
        return null;
      }
      if (["contacts", "sasa", "structure"].includes(request.view) && request.handle) {
        const [log, reports] = await Promise.all([api.allEvents(id), api.reports(id)]);
        if (!accepted()) return null;
        const result = [...resultEvents(log)].reverse().find(event => event.output?.handle === request.handle);
        const step = result ? timeline(log).find(item => item.callId === resultId(result)) : undefined;
        if (!step) throw new Error("분석 흐름 결과의 도구 호출 기록을 찾지 못했습니다.");
        setEvents(log); setHandles(latestHandles(log)); setSavedReports(reports);
        exitSceneOverride(); setOpenmmViewHandle(null); setViewIntent("step"); setPocketView(null);
        setSelectedStepNumber(step.n); setInspectionRevision(value => value + 1); setOffset(0);
      }
      return null;
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      if (accepted()) setError(`분석 흐름 결과 열기 실패: ${message}`);
      return message;
    }
  }
  const focusedLigand = selectedFocus && displayResidues?.ligands.some(candidate => identity(candidate) === identity(selectedFocus))
    ? selectedFocus : null;
  const listedLigand = ligandIndex !== "" ? latestResidues?.ligands[Number(ligandIndex)] ?? null : null;
  const analysisScreen: ScreenSelections = {
    displayedSource: displaySource && displayData ? { handle: displaySource.handle, kind: displayData.kind } : null,
    ligand: focusedLigand ?? listedLigand,
    ligandSourceHandle: focusedLigand ? displaySource?.handle ?? null : listedLigand ? handles.prepared?.handle ?? null : null,
    preparation: { altloc, waters, hydrogens }, cutoff_A: cutoff, types: [...contactTypes],
    pocketChains: importedPocketChains(pocketChainSelection, runId ?? null, displaySource?.handle ?? null),
    atoms: measurementSelection?.result.schema === "atom_distance@1" ? { source: measurementSelection.result.structure_handle,
      first: measurementSelection.result.first, second: measurementSelection.result.second } : null,
    comparison: comparisonReference && comparisonMoving ? { reference: comparisonReference, moving: comparisonMoving,
      pairs: correspondence.map(pair => ({ reference: pair.reference, moving: pair.moving })) } : null,
    chemicalRequest: null, openmmAcknowledged: { protein_only: proteinOnlyAccepted, rebuild_pH7: hydrogenAccepted } };

  const latestUpload = [...events].reverse().find(e => e.type === "upload_received");
  const uploadedCount = events.filter(e => e.type === "upload_received").length;
  const noLigands = handles.prepared && latestResidues?.ligands.length === 0;

  useEffect(() => {
    if (chemicalActive || !chemicalSceneToRestore) return;
    const handle = chemicalSceneToRestore;
    setChemicalSceneToRestore(null);
    setSelectedSceneHandle(handle);
    void restoreSavedScene(handle);
  // A chemical restore is intentionally admitted only after the ordinary viewer has remounted.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chemicalActive, chemicalSceneToRestore]);

  const structureScreen = chemicalActive && run ? <ChemicalWorkspace key={run.run_id} run={run} runs={runs}
    events={events} capabilities={capabilities} onTheme={toggleTheme}
    onObjectsChanged={id => { refreshEventsFromAnalysis(id); if (hostRequestAccepted({ runId: id }, analysisHostRef.current)) refreshGlobalBudget(id); }}
    onExit={() => { setChemicalActive(false); setInspectionRevision(value => value + 1); }}
    onSwitchRun={id => { setChemicalActive(false); void switchRun(id); }}
    onRestoreScene={handle => { setChemicalSceneToRestore(handle); setChemicalActive(false); }} />
  : <WorkspaceShell
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
          <Button size="sm" onClick={() => { exitSceneOverride(); setOpenmmViewHandle(null); setViewIntent("latest_pipeline"); setPocketView(null); setSelectedStepNumber(null); setInspectionRevision(value => value + 1); setOffset(0); }}>최신 구조로 돌아가기</Button></div>}
        {steps.length ? <StepList steps={steps} selected={selectedStep?.n} onSelect={step => { exitSceneOverride(); setOpenmmViewHandle(null); setViewIntent("step"); setPocketView(null); setSelectedStepNumber(step.n); setInspectionRevision(value => value + 1); setOffset(0); }} />
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
    canvas={<MolstarViewer key={`${viewerContextKey ?? "no-structure"}:${comparisonContext ? movingSource?.handle ?? "moving-loading" : "single"}`}
      source={comparisonContext && (!movingSource || !movingCatalog || !atomCatalog) ? null : displaySource}
      representation={representation}
      residues={displayResidues?.residues}
      highlight={!comparisonContext && viewerReady && highlight?.key === viewerContextKey ? highlight.residue : null}
      atomCatalog={atomCatalog} measureMode={measureMode || !!pairPickSide} onAtomPick={onComparisonAtomPick}
      comparison={comparisonContext && movingSource && movingCatalog ? { source: movingSource, catalog: movingCatalog,
        alignment: comparisonContext.result, aligned: comparisonAligned, referenceVisible, movingVisible } : null}
      focusPair={focusPair}
      pocketOverlay={pocketOverlayForViewer}
      onPocketOverlay={(key, readback, overlayError) => {
        if (key === null) { setPocketReadback(previous => previous === null ? previous : null); return; }
        if (key !== pocketKeyRef.current) return;
        setPocketReadback(readback); setPocketOverlayError(overlayError);
      }}
      siteAnnotation={annotationForViewer}
      onSiteAnnotation={(key, readback, siteError) => {
        if (key === null) { setAnnotationReadback(previous => previous === null ? previous : null); return; }
        if (key !== annotationKeyRef.current) return;
        setAnnotationReadback(readback); setAnnotationViewerError(siteError);
      }}
      selectedAtoms={pendingAtom ? [pendingAtom] : measurementSelection?.result.schema === "atom_distance@1" &&
        [displaySource?.handle, movingSource?.handle].includes(measurementSelection.result.structure_handle)
        ? [measurementSelection.result.first, measurementSelection.result.second] : []}
      distanceResult={measurementSelection?.result.schema === "atom_distance@1" &&
        [displaySource?.handle, movingSource?.handle].includes(measurementSelection.result.structure_handle)
        ? measurementSelection.result : null}
      onBridge={bridge => { viewerBridgeRef.current = bridge; }}
      onManualInteraction={() => { cancelPendingRestore(); manualViewerInvalidator.current?.(); }}
      onSelect={selectFromViewer}
      onLoadState={(loadedSource, status, message) => {
        if (viewerContextKey && loadedSource === displaySource) setViewerState({ key: viewerContextKey, source: loadedSource, status, message });
      }}
      onFocusResult={(focusedSource, residue, found) => {
        if (!viewerReady || !viewerContextKey || focusedSource !== displaySource || highlight?.key !== viewerContextKey || identity(highlight.residue) !== identity(residue)) return;
        if (found) { setFocusedResidue({ key: viewerContextKey, residue }); setFocusError(null); }
        else {
          const observed = viewerBridgeRef.current?.snapshot();
          if (observed?.catalogReady && !observed.selectionError)
            setFocusedResidue(observed.selection ? { key: viewerContextKey, residue: observed.selection } : null);
          setFocusError({ key: viewerContextKey, message: "선택한 잔기를 표시 중인 구조에서 찾지 못했습니다." });
        }
      }}
      emptyMessage={displayedError ?? (targetHandle ? "선택한 구조를 불러오는 중…" : selectedMeasurement || selectedStructure ? "선택한 객체의 입력 구조를 확인하는 중…" : undefined)}
      emptyIsError={!!displayedError} />}
    canvasOverlayTopLeft={comparisonContext ? <span className="mw-muted">기준 · 파랑 / 이동 · 주황 · {comparisonAligned ? "정렬" : "원래 좌표"}</span>
      : <Segmented label="표현 방식" value={representation} onChange={value => {
      cancelPendingRestore(); manualViewerInvalidator.current?.(); setRepresentation(value);
    }} options={[
      { value: "cartoon", label: "cartoon" }, { value: "ball-and-stick", label: "ball-and-stick" }, { value: "surface", label: "surface" },
    ]} />}
    canvasLegend={(displayData || inspecting) && <><span className="mw-muted">{comparisonContext ? `두 구조 비교 · 기준 ${comparisonContext.result.reference_model_number} / 이동 ${comparisonContext.result.moving_model_number}` : sceneOverride ? `저장된 보기 · ${sceneOverride.scene.value.name}` : pocketView ? "fpocket 포켓 결과의 소스 구조" : openmmViewHandle ? "OpenMM 최소화 단백질 좌표" : viewIntent === "step" ? "선택한 단계의 구조" : viewIntent === "latest_result" ? "최근 결과의 구조" : "최신 파이프라인 구조"}{viewerReady ? ` · model ${displayResidues?.model_number ?? "—"}` : displayedError ? " · 표시 실패" : " · 불러오는 중"}</span>
      {selectedFocus && <span className="mw-mono">선택: {displayResidue(selectedFocus)}</span>}
      {pocketReadback && pocketOverlayForViewer && <span className="mw-muted">fpocket 후보 공동 · rank {pocketReadback.rank} · 알파 구 {pocketReadback.sphereCount}개</span>}</>}
    strip={<>{runId && <Button size="sm" disabled={!!chemicalEntryBlockedReason(busy)}
      title={chemicalEntryBlockedReason(busy) ?? undefined} onClick={enterChemical}>화학 상호작용 작업 열기</Button>}
    {comparisonContext ? <p className="mw-muted">두 구조 비교 중에는 한 구조용 프롬프트 명령을 사용할 수 없습니다.</p> : <ViewerAgentPanel key={viewerContextKey ?? `empty-${runId ?? "none"}`}
      runId={runId ?? null} clientId={viewerClientId.current ?? ""} sceneGeneration={sceneToken.current.generation}
      disabledReason={pocketGates.m8}
      naturalLanguageDisabledReason={siteGates.m8}
      sourceHandle={displaySource?.handle ?? null} viewerReady={viewerReady} bridgeRef={viewerBridgeRef}
      representation={representation} selected={selectedFocus} residues={displayResidues} dryRun={run?.dry_run ?? false}
      restoreTarget={sceneOverride?.scene.value.selection ?? null} onSession={setViewerSession}
      restorePending={!!sceneOverride && restorePendingToken === sceneOverride.token}
      onManualSceneAction={cancelPendingRestore}
      onSessionError={message => { if (sceneOverride && sceneEpoch.current === sceneOverride.token) {
        sceneEpoch.current += 1; viewerBridgeRef.current?.invalidate(); setSceneBusy("");
        pendingRestoreTokenRef.current = null;
        setRestorePendingToken(null);
        setSceneError(`저장된 보기 세션을 만들지 못했습니다: ${message}`);
      } }}
      registerSceneController={registerSceneController}
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
      registerInvalidator={value => { manualViewerInvalidator.current = value; }} />}
    <div className="mw-workflow" aria-label="원자 거리와 두 구조 비교">
      <div className="mw-workflow-row">
        <Button size="sm" disabled={!viewerReady || !atomCatalog || bridgeState?.catalogReady !== true ||
          (!measureMode && bridgeState?.representation !== "ball-and-stick")} onClick={() => {
          revokeComparisonAction();
          setHighlight(null); setFocusedResidue(null); setFocusError(null);
          if (measureMode) { setMeasurementSelection(null); setComparisonReport(null);
            setLastPickedAtom(null); setDistanceSourceHandle(""); }
          setMeasureMode(value => !value); setPairPickSide(null); setPendingAtom(null); setComparisonError("");
        }}>{measureMode ? "원자 거리 측정 끝내기" : "원자 거리 측정"}</Button>
        {!measureMode && viewerReady && bridgeState?.representation !== "ball-and-stick" &&
          <span className="mw-muted">원자 선택 전에 ball-and-stick 표시를 선택하세요.</span>}
        {measureMode && <><Button size="sm" disabled={!pendingAtom} onClick={() => setPendingAtom(null)}>첫 원자 취소</Button>
          <Button size="sm" onClick={() => { revokeComparisonAction(); setPendingAtom(null); setMeasurementSelection(null);
            setDistanceSourceHandle(""); setComparisonReport(null); setLastPickedAtom(null); }}>측정 지우기</Button>
          <span className="mw-muted">{pendingAtom ? `첫 원자: ${atomLabel(pendingAtom)}` : "Mol* 화면에서 첫 원자, 두 번째 원자를 클릭하세요."}</span></>}
      {comparisonContext && <Button size="sm" onClick={() => { revokeComparisonAction(); viewerBridgeRef.current?.invalidate();
          setComparisonContext(null); setPairPickSide(null); setMeasureMode(false); setPendingAtom(null);
          setMeasurementSelection(null); setComparisonReport(null); setLastPickedAtom(null);
          setFocusPair(null); setInspectionRevision(value => value + 1); }}>단일 구조로 돌아가기</Button>}
      </div>
      {lastPickedAtom && <p className="mw-capability">선택 원자 {atomLabel(lastPickedAtom.ref, lastPickedAtom.layer)} · 원본 좌표 [{lastPickedAtom.sourceCoordinate_A.join(", ")}] Å · 화면 좌표 [{lastPickedAtom.displayCoordinate_A.map(value => value.toFixed(3)).join(", ")}] Å</p>}
      {atomCatalogError && <p role="alert" className="mw-workflow-error">{atomCatalogError}</p>}
      {(atomCatalogError || displayedError) && <Button size="sm" onClick={() => {
        setInspectionRevision(value => value + 1); setAtomReadRetry(value => value + 1);
      }}>기준 구조·원자 다시 읽기</Button>}
      {comparisonContext && (!movingCatalog || !movingSource || displayedError) &&
        <Button size="sm" onClick={() => setMovingReadRetry(value => value + 1)}>이동 구조·원자 다시 읽기</Button>}
      {referenceDraftError && <p role="alert" className="mw-workflow-error">{referenceDraftError}</p>}
      {movingDraftError && <p role="alert" className="mw-workflow-error">{movingDraftError}</p>}
      {comparisonReference && comparisonMoving && (!refDraft || !movDraft) && <Button size="sm" onClick={() => setDraftReadRetry(value => value + 1)}>대응 원자 목록 다시 읽기</Button>}
      {measurementSelection?.result.schema === "atom_distance@1" && <p className="mw-capability">원자 거리 {measurementSelection.result.distance_A.toFixed(3)} Å · {atomLabel(measurementSelection.result.first)} ↔ {atomLabel(measurementSelection.result.second)} · 원본 좌표의 유클리드 거리</p>}
      <div className="mw-workflow-row"><label>저장된 거리·정렬 결과 <select className="mw-select" value={measurementSelection?.handle ?? ""}
        onChange={e => { if (!e.target.value) { revokeComparisonAction(); setMeasurementSelection(null); setDistanceSourceHandle("");
          setComparisonReport(null); } else void reopenMeasurement(e.target.value); }}><option value="">결과 선택</option>
        {measurementOptions.map(item => <option key={item.handle} value={item.handle}>{item.kind} · {item.handle.split("/").at(-1)?.slice(0, 12)}</option>)}</select></label>
        {measurementSelection && <Button size="sm" disabled={!!comparisonBusy} onClick={() => void createComparisonReport()}>측정 보고서 만들기</Button>}
      </div>
      {comparisonReport && comparisonReport.resultHandle === measurementSelection?.handle && runId && <><div className="mw-report-downloads">
        <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, comparisonReport.handle, "markdown")}>Markdown 다운로드</a>
        <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, comparisonReport.handle, "json")}>정확한 JSON 다운로드</a>
      </div><pre className="mw-report-preview" aria-label="원자 측정 보고서 미리보기">{comparisonReport.markdown}</pre></>}
      <div className="mw-workflow-row"><label>기준 구조 <select className="mw-select" value={comparisonReference} onChange={e => {
        revokeComparisonAction();
        setComparisonReference(e.target.value); setCorrespondence([]); setReferenceSite(""); setComparisonContext(null); setDistanceSourceHandle(""); setFocusPair(null);
      }}><option value="">구조 선택</option>{sourceOptions.map(item => <option key={item.handle} value={item.handle}>{item.kind} · {item.handle.split("/").at(-1)?.slice(0, 12)}</option>)}</select></label>
        <label>이동 구조 <select className="mw-select" value={comparisonMoving} onChange={e => {
          revokeComparisonAction();
          setComparisonMoving(e.target.value); setCorrespondence([]); setMovingSite(""); setComparisonContext(null); setDistanceSourceHandle(""); setFocusPair(null);
        }}><option value="">구조 선택</option>{sourceOptions.filter(item => item.handle !== comparisonReference).map(item => <option key={item.handle} value={item.handle}>{item.kind} · {item.handle.split("/").at(-1)?.slice(0, 12)}</option>)}</select></label>
      </div>
      {comparisonReference && comparisonMoving && <><div className="mw-workflow-row">
        <label>기준 CA site <select className="mw-select" value={referenceSite} onChange={e => setReferenceSite(e.target.value)}><option value="">정확한 원자 선택</option>
          {refDraft?.rows.filter(row => row.protein && row.ref.atom_name === "CA").map(row => <option key={row.ref.site_index} value={row.ref.site_index}>{atomLabel(row.ref, "기준")}</option>)}</select></label>
        <Button size="sm" disabled={!viewerReady || bridgeState?.catalogReady !== true || displaySource?.handle !== comparisonReference} onClick={() => { setPairPickSide("reference"); setMeasureMode(true); }}>기준 CA 화면 선택</Button>
        <label>이동 CA site <select className="mw-select" value={movingSite} onChange={e => setMovingSite(e.target.value)}><option value="">정확한 원자 선택</option>
          {movDraft?.rows.filter(row => row.protein && row.ref.atom_name === "CA").map(row => <option key={row.ref.site_index} value={row.ref.site_index}>{atomLabel(row.ref, "이동")}</option>)}</select></label>
        <Button size="sm" disabled={!viewerReady || bridgeState?.catalogReady !== true || !comparisonContext || comparisonMoving !== comparisonContext.result.moving_handle} onClick={() => { setPairPickSide("moving"); setMeasureMode(true); }}>이동 CA 화면 선택</Button>
        <Button size="sm" disabled={!referenceSite || !movingSite} onClick={addCorrespondence}>대응 추가</Button>
      </div>
      <div className="mw-table-scroll" role="region" aria-label="명시한 CA 대응" tabIndex={0}><table className="mw-table"><thead><tr><th>기준 CA</th><th>이동 CA</th><th>작업</th></tr></thead><tbody>
        {correspondence.map((pair, index) => <tr key={`${pair.reference.site_index}:${pair.moving.site_index}`}>
          <td>{atomLabel(pair.reference, "기준")}</td><td>{atomLabel(pair.moving, "이동")}</td><td>
            <Button size="sm" onClick={() => { revokeComparisonAction(); setFocusPair(null);
              setCorrespondence(rows => rows.filter((_, i) => i !== index)); }}>대응 제거</Button>
            {comparisonContext && <Button size="sm" onClick={() => setFocusPair(previous =>
              ({ ...pair, token: (previous?.token ?? 0) + 1 }))}>대응 원자 초점</Button>}
          </td></tr>)}
      </tbody></table></div>
      <div className="mw-workflow-row"><Button size="sm" disabled={correspondence.length < 3 || correspondence.length > 1000 || !!comparisonBusy ||
          !refDraft || !movDraft || comparisonReference === comparisonMoving} onClick={() => void computeAlignment()}>정렬 계산</Button>
        <span className="mw-muted">명시한 단백질 CA 대응 {correspondence.length}개 · 최소 3개, 최대 1000개 · 자동 짝짓기 없음</span></div></>}
      {comparisonContext && <><p className="mw-capability">정렬 RMSD {comparisonContext.result.rmsd_A.toFixed(4)} Å · 원래 RMSD {comparisonContext.result.unaligned_rmsd_A.toFixed(4)} Å · {comparisonContext.result.pair_count}쌍</p>
        <div className="mw-workflow-row"><label><input type="radio" name="comparison-coordinates" checked={comparisonAligned} onChange={() => setComparisonAligned(true)} /> 정렬 좌표</label>
          <label><input type="radio" name="comparison-coordinates" checked={!comparisonAligned} onChange={() => setComparisonAligned(false)} /> 원래 좌표</label>
          <label><input type="checkbox" checked={referenceVisible} onChange={e => setReferenceVisible(e.target.checked)} /> 기준 구조 표시</label>
          <label><input type="checkbox" checked={movingVisible} onChange={e => setMovingVisible(e.target.checked)} /> 이동 구조 표시</label></div>
        <p className="mw-muted">파랑: 기준 구조 · 주황: 이동 구조. 정렬은 화면 변환이며 저장된 구조 좌표를 변경하지 않습니다.</p></>}
      {comparisonBusy && <span role="status" className="mw-muted">{comparisonBusy}…</span>}
      {comparisonError && <p role="alert" className="mw-workflow-error">{comparisonError}</p>}
    </div>
    <div className="mw-workflow" aria-label="저장된 보기와 그림">
      <div className="mw-workflow-row"><label>보기 이름 <input className="mw-input" type="text" maxLength={80} value={sceneName} onChange={e => setSceneName(e.target.value)} /></label>
        <Button size="sm" disabled={sceneBlocked || !runId || !sceneSessionReady || !sceneName.trim() || !!sceneBusy} title={pocketGates.m9 ? pocketGates.m9 : m10SceneBlocked ? "원자 측정 표시를 지우거나 두 구조 비교에서 나간 뒤 단일 구조 보기를 저장하세요." : !viewerReady ? "구조를 먼저 불러오세요" : !sceneSessionReady ? "뷰어 세션을 준비하는 중입니다" : "현재 장면을 저장합니다"} onClick={() => void saveCurrentScene()}>현재 보기 저장</Button>
        <label>저장된 보기 <select className="mw-select" value={selectedSceneHandle} onChange={e => setSelectedSceneHandle(e.target.value)}>
          <option value="">보기 선택</option>{savedScenes.map(scene => <option key={scene.handle} value={scene.handle}>{scene.value.name} · {scene.value.structure_kind} · {scene.handle.split("/").at(-1)?.slice(0, 12)}{sceneAnnotation(scene.value) ? " · 참조 주석" : ""}</option>)}
        </select></label>
        <Button size="sm" disabled={!runId || !selectedSceneHandle} onClick={() => void restoreSavedScene()}>저장된 보기 복원</Button>
        {sceneOverride && <Button size="sm" onClick={returnToCurrentStructure}>현재 구조로 돌아가기</Button>}
        <Button size="sm" disabled={sceneBlocked || !runId || !selectedSceneHandle || !sceneSessionReady || !!sceneBusy} title={pocketGates.m9 ? pocketGates.m9 : m10SceneBlocked ? "원자 측정 표시를 지우거나 두 구조 비교에서 나간 뒤 단일 구조 PNG를 내보내세요." : !viewerReady ? "구조를 먼저 불러오세요" : !sceneSessionReady ? "뷰어 세션을 준비하는 중입니다" : !selectedSceneHandle ? "저장된 보기를 먼저 선택하세요" : "현재 장면이 선택한 저장 보기와 정확히 일치해야 합니다"} onClick={() => void exportCurrentFigure()}>현재 보기 PNG 내보내기</Button>
      </div>
      {pocketGates.m9 && <p className="mw-muted" role="status" data-pocket-m9-reason>보기 저장·PNG 내보내기 사용 불가: {pocketGates.m9}</p>}
      {m10SceneBlocked && <p className="mw-muted" role="status">원자 측정 표시와 두 구조 비교는 단일 구조 보기·PNG에 기록되지 않습니다. 측정을 지우거나 단일 구조로 돌아간 뒤 저장하세요.</p>}
      <div className="mw-workflow-row"><label>저장된 그림 <select className="mw-select" value={selectedFigureHandle} onChange={e => setSelectedFigureHandle(e.target.value)}>
        <option value="">그림 선택</option>{savedFigures.map(figure => <option key={figure.handle} value={figure.handle}>{figure.value.scene_handle.split("/").at(-1)?.slice(0, 12)} · {figure.value.width}×{figure.value.height} · {figure.handle.split("/").at(-1)?.slice(0, 12)}</option>)}
      </select></label>
        {runId && selectedFigureHandle && <><a href={api.figureDownload(runId, selectedFigureHandle, "png")} download>PNG 다운로드</a>
          <a href={api.figureDownload(runId, selectedFigureHandle, "json")} download>JSON 출처 다운로드</a></>}
        <Button size="sm" disabled={!runId} onClick={() => setSceneReadRetry(value => value + 1)}>저장된 보기 다시 읽기</Button>
        {viewerReady && !sceneSessionReady && <span role="status" className="mw-muted">뷰어 세션 준비 중…</span>}
        {sceneBusy && <span role="status" className="mw-muted">{sceneBusy}…</span>}
        {sceneStatus && <span role="status" className="mw-muted">{sceneStatus}</span>}
        {sceneError && <span role="alert" className="mw-workflow-error">{sceneError}</span>}
        {annotationRestore && annotationRestore.token === sceneOverride?.token && <span role={annotationRestore.status === "applied" ? "status" : "alert"}
          className={annotationRestore.status === "applied" ? "mw-muted" : "mw-workflow-error"} data-testid="scene-annotation-restore"
          data-scene-annotation-restore={annotationRestore.status}>{annotationRestore.text}</span>}
      </div>
      <p className="mw-muted">PNG는 현재 장면을 Mol*에서 로컬로 렌더링한 그림입니다. 저장된 보기와 장면이 일치하고 뷰어가 준비된 경우에만 내보낼 수 있습니다. 새 과학 계산 결과가 아닙니다.</p>
    </div>
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
        {openmmJobs.length > 0 && <label>작업 <select className="mw-select" value={openmmJobId ?? ""} onChange={e => { openmmJobRef.current = e.target.value; openmmOutputRef.current = undefined; setOpenmmJobId(e.target.value); setOpenmmViewHandle(null); setPocketView(null); }}>
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
          <Button size="sm" onClick={() => { exitSceneOverride(); setPocketView(null); setOpenmmViewHandle(selectedOpenmmResult.minimized_structure); }}>최소화 단백질 좌표 보기</Button>
          {openmmViewHandle && <Button size="sm" onClick={() => { exitSceneOverride(); setOpenmmViewHandle(null); setPocketView(null); }}>원래 구조로 돌아가기</Button>}
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
      {run && <InspectorSection><AnalysisWorkflowPanel key={run.run_id} panel="main" run={run}
        capability={capabilities ? capabilities.methods?.analysis_workflows ?? null : undefined}
        sourceOptions={sourceOptions} screen={analysisScreen}
        onOpenResult={openAnalysisResult} onEnterChemical={enterChemicalFromAnalysis}
        onObjectsChanged={refreshEventsFromAnalysis} /></InspectorSection>}
      {run && <InspectorSection><PocketPanel key={run.run_id} panel="main" run={run}
        capability={capabilities ? capabilities.methods?.pocket_detection ?? null : undefined} sourceOptions={pocketSourceOptions}
        displayedSourceHandle={displaySource?.handle ?? null} viewerReady={pocketViewerReady}
        blockedReason={pocketGates.pocket} overlayBlockedReason={siteGates.pocketOverlay} overlay={pocketState?.request ?? null}
        overlayApplied={pocketReadback} overlayError={pocketOverlayError} overlayNotice={pocketNotice}
        onOverlay={requestPocketOverlay}
        openRequest={pocketOpenRequest} onOpenRequestResult={pocketOpenAnswered} onChainSelection={setPocketChainSelection}
        onShowSource={(requestRunId, handle, kind) => {
          if (kind === "chemical_structure" || !pocketRequestAccepted({ runId: requestRunId, sourceHandle: handle },
            pocketHostRef.current)) return;
          const shownNow = pocketView?.handle ?? openmmViewHandle;
          if (!pocketReturnRef.current || pocketReturnRef.current.shown !== shownNow)
            pocketReturnRef.current = { shown: handle, openmmViewHandle, pocketView };
          else pocketReturnRef.current = { ...pocketReturnRef.current, shown: handle };
          exitSceneOverride(); setDistanceSourceHandle("");
          if (kind === "openmm_minimized_structure") { setPocketView(null); setOpenmmViewHandle(handle); }
          else { setOpenmmViewHandle(null); setPocketView({ handle, kind }); }
        }}
        onReturnToSource={() => {
          requestPocketOverlay(null);
          const prior = pocketReturnRef.current;
          pocketReturnRef.current = null;
          // Restore the view before the pocket selection switched the source, only while that switch is still on screen.
          if (prior && prior.shown === (pocketView?.handle ?? openmmViewHandle)) {
            setPocketView(prior.pocketView); setOpenmmViewHandle(prior.openmmViewHandle);
          }
        }} /></InspectorSection>}
      {run && <InspectorSection><SiteAnnotationPanel key={run.run_id} run={run}
        capability={capabilities ? capabilities.methods?.reference_site_annotation ?? null : undefined}
        sourceHandle={targetHandle} sourceKind={annotationSourceKind} viewerReady={pocketViewerReady && displaySource?.handle === targetHandle}
        events={events} blockedReason={siteGates.annotation} shown={annotationShown}
        applied={annotationApplied} appliedError={annotationForViewer ? annotationViewerError : null}
        onShow={requestAnnotation} onObjectsChanged={refreshEventsFromAnalysis}
        mapsReloadToken={structureTabEntries}
        onReportCreated={() => setReportsReloadToken(token => token + 1)} /></InspectorSection>}
      {budget && <InspectorSection><span className="mw-eyebrow">실제 예산</span><BudgetMeter budget={budget} /></InspectorSection>}
      {capabilities?.methods?.interface_sasa && <InspectorSection><span className="mw-eyebrow">지원하는 로컬 방법</span>
        <p className="mw-capability"><b>단백질–리간드 SASA</b><br />{capabilities.methods.interface_sasa.available
          ? `${capabilities.methods.interface_sasa.method_id} · ${capabilities.methods.interface_sasa.algorithm} ${capabilities.methods.interface_sasa.n_slices} slices · Å² · ${capabilities.methods.interface_sasa.limitations}`
          : `사용 불가: ${capabilities.methods.interface_sasa.explanation ?? "엔진을 확인할 수 없습니다."}`}</p></InspectorSection>}
      {capabilities && <InspectorSection><span className="mw-eyebrow">현재 사용 불가</span>{Object.entries(capabilities.unavailable).map(([name, reason]) => <p className="mw-capability" key={name}><b>{name}</b><br />{reason}</p>)}</InspectorSection>}
    </>}
  />;

  return <WorkspaceTabs active={workspaceTab} runId={runId ?? null} budget={budget} structure={structureScreen}
    reports={<ReportLibraryPanel run={run} active={workspaceTab === "knowledge"} reloadToken={reportsReloadToken} />}
    numbering={<NumberingPanel key={run?.run_id ?? "none"} runId={run?.run_id ?? null}
      onReportCreated={() => setReportsReloadToken(token => token + 1)} />}
    onSelect={tab => { setWorkspaceTab(tab); if (tab === "structure") setStructureTabEntries(value => value + 1);
      if (runId) refreshGlobalBudget(runId); }} />;
}
