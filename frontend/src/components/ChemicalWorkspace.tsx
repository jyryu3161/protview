"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, displayedEgressMode, type Capabilities, type RunSummary,
  type SavedReportRef } from "@/lib/api";
import type { BudgetSnapshot, ResidueRef, RunEvent } from "@/lib/contracts";
import type { AtomCatalog, AtomRefV1 } from "@/lib/comparison";
import { atomLabel, sameResidueRef } from "@/lib/comparison";
import { canHydrateChemicalJobs, canonicalChemicalElement, chemicalAnnotationForRow, chemicalApprovalRequired,
  chemicalCanCancel, chemicalFailureDetails, chemicalJobActionCurrent, completedChemicalResultHandles, linkedChemicalJobs,
  chemicalCategories, chemicalReadTimeoutMs, chemicalStartProgressed, chemicalSubmitStatus, declaredTerminalNames,
  exactChemicalRow, previewMatchesRequest, readChemicalAtomCatalog, validateChemicalCatalog,
  type ChemicalAck, type ChemicalCategory, type ChemicalImport, type ChemicalInspect,
  type ChemicalJob, type ChemicalJobFailure, type ChemicalLigandAtom, type ChemicalMapping, type ChemicalMode,
  type ChemicalPreparationManifest, type ChemicalPrepareArgs, type ChemicalPreview,
  type ChemicalResult, type ChemicalResultPage,
  type ChemicalRow, type ChemicalView, type HydrogenPolicy, type TerminalExtension } from "@/lib/chemical";
import { Button, InspectorSection, MolstarViewer, WorkspaceShell,
  type ViewerRepresentation } from "@/components";
import type { ViewerBridge, ViewerSource } from "./MolstarViewer";
import { PocketPanel } from "./PocketPanel";
import { chemicalExclusive, featureGates, overlayContextDecision, pocketRequestAccepted, type PocketOverlayReadback,
  type PocketOverlayRequest } from "@/lib/pockets";

type ChemicalDisplay = { generation: number; view: ChemicalView; source: ViewerSource;
  catalog: AtomCatalog; graphHandle: string; manifest: ChemicalPreparationManifest };
type ImportKind = ChemicalImport["kind"];
const jobDone = new Set(["done", "failed", "cancelled", "interrupted"]);
const emptyAck: ChemicalAck = { schema: "chemical_preparation_ack@1", supplied_graph_complete: false,
  supplied_hydrogens_complete: false, use_supplied_protonation_tautomer: false,
  infer_receptor_orders_charges: false, description: "", ph_annotation: null };
const refKey = (ref: ResidueRef) => JSON.stringify([ref.model_number, ref.chain_auth, ref.chain_label,
  ref.seq_auth, ref.seq_label, ref.icode, ref.resname]);
const errorText = (e: unknown) => e instanceof Error ? e.message : String(e);

function ChemicalFailure({ failure }: { failure: ChemicalJobFailure }) {
  const details = chemicalFailureDetails(failure);
  return <div role="alert" className="mw-table-error">
    <p>{failure.error}: {failure.message}</p>
    {details.length > 0 && <details><summary>실패한 화학 입력 진단</summary>
      <ul>{details.map((line, index) => <li className="mw-mono" key={index}>{line}</li>)}</ul>
    </details>}
  </div>;
}

export interface ChemicalWorkspaceProps {
  run: RunSummary; runs: RunSummary[]; events: RunEvent[]; capabilities: Capabilities | null;
  onExit: () => void; onSwitchRun: (id: string) => void; onRestoreScene: (handle: string) => void;
  onTheme: () => void;
}

export function ChemicalWorkspace({ run, runs, events, capabilities, onExit, onSwitchRun,
  onRestoreScene, onTheme }: ChemicalWorkspaceProps) {
  const runId = run.run_id;
  const [mode, setMode] = useState<ChemicalMode>("create_new");
  const [imports, setImports] = useState<Partial<Record<ImportKind, ChemicalImport>>>({});
  const [inspection, setInspection] = useState<Partial<Record<ImportKind, ChemicalInspect>>>({});
  const [uploading, setUploading] = useState<ImportKind | null>(null);
  const [complexHandle, setComplexHandle] = useState("");
  const [complexOptions, setComplexOptions] = useState<{ handle: string; kind: string }[]>([]);
  const [complexResidues, setComplexResidues] = useState<ResidueRef[]>([]);
  const [complexAtoms, setComplexAtoms] = useState<AtomCatalog | null>(null);
  const [stagingAtoms, setStagingAtoms] = useState<{ ref: AtomRefV1; water: boolean }[]>([]);
  const [ligandKey, setLigandKey] = useState("");
  const [modelNumber, setModelNumber] = useState(1);
  const [recordIndex, setRecordIndex] = useState(0);
  const [connectivity, setConnectivity] = useState<"pdb_conect" | "sidecar">("pdb_conect");
  const [hydrogenPolicy, setHydrogenPolicy] = useState<HydrogenPolicy>("map_existing");
  const [ligandChain, setLigandChain] = useState("L");
  const [ligandSequence, setLigandSequence] = useState(1);
  const [ligandName, setLigandName] = useState("LIG");
  const [mapping, setMapping] = useState<ChemicalMapping[]>([]);
  const [extensions, setExtensions] = useState<TerminalExtension[]>([]);
  const [customTerminalResidue, setCustomTerminalResidue] = useState("");
  const [customTerminalNames, setCustomTerminalNames] = useState("");
  const [ack, setAck] = useState<ChemicalAck>(emptyAck);
  const [preview, setPreview] = useState<ChemicalPreview | null>(null);
  const [previewRequest, setPreviewRequest] = useState("");
  const [previewBusy, setPreviewBusy] = useState(false);
  const [jobBusy, setJobBusy] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [prepareJob, setPrepareJob] = useState<ChemicalJob | null>(null);
  const [detectJob, setDetectJob] = useState<ChemicalJob | null>(null);
  const [approvalFor, setApprovalFor] = useState<"prepare" | "detect" | null>(null);
  const [display, setDisplay] = useState<ChemicalDisplay | null>(null);
  const [displayStatus, setDisplayStatus] = useState<"loading" | "ready" | "error">("loading");
  const [representation, setRepresentation] = useState<ViewerRepresentation>("ball-and-stick");
  const [resultList, setResultList] = useState<string[]>(() => completedChemicalResultHandles(events));
  const [jobHistory, setJobHistory] = useState<ChemicalJob[]>([]);
  const [resultHandle, setResultHandle] = useState("");
  const [result, setResult] = useState<ChemicalResult | null>(null);
  const [resultLoadedHandle, setResultLoadedHandle] = useState("");
  const [category, setCategory] = useState<"" | ChemicalCategory>("");
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState<10 | 25 | 50>(50);
  const [rows, setRows] = useState<{ key: string; page: ChemicalResultPage } | null>(null);
  const [rowSelection, setRowSelection] = useState<ChemicalRow | null>(null);
  const [focusToken, setFocusToken] = useState(0);
  const [annotationVisible, setAnnotationVisible] = useState(true);
  const [reportRefs, setReportRefs] = useState<SavedReportRef[]>([]);
  const [reportHandle, setReportHandle] = useState("");
  const [reportMarkdown, setReportMarkdown] = useState("");
  const [reportBusy, setReportBusy] = useState(false);
  const [budget, setBudget] = useState<BudgetSnapshot | null>(null);
  const [sceneHandles, setSceneHandles] = useState<{ handle: string; name: string }[]>([]);
  const [sceneHandle, setSceneHandle] = useState("");
  const [status, setStatus] = useState("");
  const [failure, setFailure] = useState("");
  const [readRevision, setReadRevision] = useState(0);
  const [pocketState, setPocketState] = useState<{ request: PocketOverlayRequest; boundContext: string | null } | null>(null);
  const [pocketReadback, setPocketReadback] = useState<PocketOverlayReadback | null>(null);
  const [pocketOverlayError, setPocketOverlayError] = useState<string | null>(null);
  const [pocketNotice, setPocketNotice] = useState<string | null>(null);
  const pocketKeyRef = useRef<string | null>(null);
  pocketKeyRef.current = pocketState?.request.key ?? null;
  const uploadAction = useRef(0);
  const previewAction = useRef(0);
  const jobActionToken = useRef(0);
  const jobSelectionRevision = useRef(0);
  const resultAction = useRef(0);
  const reportAction = useRef(0);
  const reportAbort = useRef<AbortController | null>(null);
  const reportScope = useRef("");
  reportScope.current = JSON.stringify([runId, resultHandle]);
  const readAbort = useRef<AbortController | null>(null);
  const bridge = useRef<ViewerBridge | null>(null);
  const generation = useRef(0);

  const sources = useMemo(() => [...new Map(events.filter((event): event is Extract<RunEvent, { type: "object_created" }> =>
    event.type === "object_created" && ["structure", "prepared_structure"].includes(event.kind))
    .map(event => [event.handle, { handle: event.handle, kind: event.kind }])).values()], [events]);
  const selectedLigand = complexResidues.find(ref => refKey(ref) === ligandKey) ?? null;
  const ligandSourceAtoms = complexAtoms?.rows.filter(row => selectedLigand && sameResidueRef(row.ref.residue, selectedLigand)) ?? [];
  const terminalResidues = [...new Map((mode === "create_new" ? stagingAtoms.filter(row => !row.water) :
    complexAtoms?.rows.filter(row => row.protein) ?? []).map(row =>
    [refKey(row.ref.residue), row.ref.residue])).values()];
  const chemicalReady = !!display && displayStatus === "ready" &&
    bridge.current?.snapshot().catalogReady === true && bridge.current.snapshot().sourceHandle === display.view.handle;
  const activeResult = resultLoadedHandle === resultHandle ? result : null;
  const rowsKey = JSON.stringify([runId, resultHandle, offset, pageSize, category, readRevision]);
  const selectedResultRows = rows?.key === rowsKey ? rows.page : null;
  const capability = capabilities?.methods?.chemical_interactions;
  const preparedSourceHandle = prepareJob?.status === "done"
    ? prepareJob.artifacts?.chemical_structure ?? prepareJob.output_handles[1] ?? null : null;
  const preparedGraphHandle = prepareJob?.status === "done"
    ? prepareJob.artifacts?.chemical_graph ?? prepareJob.output_handles[2] ?? null : null;
  const desiredSourceHandle = activeResult?.chemical_structure_handle ?? (resultHandle ? null : preparedSourceHandle);
  const desiredGraphHandle = activeResult?.graph_handle ?? (resultHandle ? null : preparedGraphHandle);
  const pocketContext = display ? `chemical:${display.generation}` : null;
  const pocketSources = useMemo(() => [...new Map(events.filter((event): event is Extract<RunEvent, { type: "object_created" }> =>
    event.type === "object_created" && event.kind === "chemical_structure")
    .map(event => [event.handle, { handle: event.handle, kind: "chemical_structure" as const }])).values()], [events]);
  useEffect(() => {
    const decision = overlayContextDecision(pocketState?.request ?? null, pocketState?.boundContext ?? null,
      pocketContext, display?.view.handle ?? null, chemicalReady);
    if (decision.action === "bind" && pocketContext)
      setPocketState(previous => previous && previous.boundContext === null ? { ...previous, boundContext: pocketContext } : previous);
    else if (decision.action === "clear") {
      setPocketState(null); setPocketReadback(null); setPocketOverlayError(null); setPocketNotice(decision.reason);
    }
  }, [pocketState, pocketContext, display?.view.handle, chemicalReady]);
  const pocketOverlay = pocketState && pocketState.boundContext === pocketContext &&
    display?.view.handle === pocketState.request.sourceHandle ? pocketState.request : null;
  // Host-side stale guard read by late callbacks: this workspace's run and its chemical pocket sources.
  const pocketHostRef = useRef<{ runId: string | null; sourceHandles: string[] }>({ runId: null, sourceHandles: [] });
  pocketHostRef.current = { runId, sourceHandles: pocketSources.map(item => item.handle) };
  function requestPocketOverlay(request: PocketOverlayRequest | null) {
    if (!pocketRequestAccepted(request, pocketHostRef.current)) return;
    setPocketOverlayError(null); setPocketNotice(null);
    if (!request) { setPocketState(null); setPocketReadback(null); return; }
    // M11 annotation (lines, angle) and the pocket overlay are never shown together.
    const exclusive = chemicalExclusive("overlay_on", { annotationVisible: annotationVisible && !!rowSelection,
      overlayActive: !!pocketState });
    setAnnotationVisible(exclusive.annotationVisible); setPocketNotice(exclusive.notice);
    setPocketState(previous => ({ request, boundContext: previous && previous.request.key === request.key &&
      previous.request.sourceHandle === request.sourceHandle ? previous.boundContext : null }));
  }
  function showAnnotation() {
    const exclusive = chemicalExclusive("annotation_on", { annotationVisible, overlayActive: !!pocketState });
    if (exclusive.clearOverlay) { setPocketState(null); setPocketReadback(null); setPocketOverlayError(null); }
    setPocketNotice(exclusive.notice);
    setAnnotationVisible(true);
  }

  const revoke = useCallback(() => {
    uploadAction.current += 1; previewAction.current += 1; jobActionToken.current += 1;
    setUploading(null); setPreviewBusy(false); setJobBusy(false); setCancelBusy(false); setApprovalFor(null);
  }, []);
  const revokeResult = useCallback(() => { resultAction.current += 1; readAbort.current?.abort(); readAbort.current = null; }, []);
  const revokeReport = useCallback(() => {
    reportAction.current += 1; reportAbort.current?.abort(); reportAbort.current = null;
    setReportBusy(false);
  }, []);
  const nextSignal = () => { readAbort.current?.abort(); const controller = new AbortController();
    readAbort.current = controller; return AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]); };
  const beginUpload = () => { uploadAction.current += 1; setUploading(null); setFailure(""); setStatus("");
    return uploadAction.current; };
  const beginPreview = () => { previewAction.current += 1; setPreviewBusy(false); setFailure(""); setStatus("");
    return previewAction.current; };
  const beginJob = () => { jobActionToken.current += 1; setJobBusy(false); setCancelBusy(false); setApprovalFor(null);
    setFailure(""); setStatus("");
    return jobActionToken.current; };

  useEffect(() => {
    return () => {
      uploadAction.current += 1; previewAction.current += 1; jobActionToken.current += 1;
      resultAction.current += 1; readAbort.current?.abort();
      reportAction.current += 1; reportAbort.current?.abort();
      bridge.current?.cancelNative();
    };
  }, []);
  useEffect(() => { setResultList(previous =>
    [...new Set([...previous, ...completedChemicalResultHandles(events)])]); }, [events]);
  useEffect(() => {
    let live = true;
    void Promise.all(sources.map(async source => ({ ...source, meta: await api.meta(runId, source.handle) })))
      .then(list => { if (live) setComplexOptions(list.filter(source =>
        (source.kind === "structure" && source.meta.schema === "structure_selection@2") ||
        (source.kind === "prepared_structure" && source.meta.schema === "prepared_structure@1"))
        .map(({ handle, kind }) => ({ handle, kind }))); })
      .catch(e => { if (live) setFailure(`기존 복합체 종류 읽기 실패: ${errorText(e)}`); });
    return () => { live = false; };
  }, [runId, sources]);
  useEffect(() => {
    if (!resultHandle || resultLoadedHandle === resultHandle) return;
    bridge.current?.cancelNative(); setDisplay(null); setDisplayStatus("loading"); setRowSelection(null);
  }, [resultHandle, resultLoadedHandle]);
  useEffect(() => {
    let live = true;
    const selectionAtStart = jobSelectionRevision.current;
    void Promise.all([api.jobs(runId), api.reports(runId), api.savedScenes(runId), api.budget(runId)]).then(([jobs, reports, scenes, limits]) => {
      if (!live) return;
      const chemical = jobs.filter(job =>
        job.protocol_id === "prolif_prepare_v1" || job.protocol_id === "prolif_detect_v1") as ChemicalJob[];
      if (chemical.some(job => job.run_id !== runId))
        throw new Error("화학 작업 목록에 다른 run의 작업이 섞였습니다.");
      if (canHydrateChemicalJobs(runId, runId, selectionAtStart, jobSelectionRevision.current, chemical)) {
        setJobHistory(chemical);
        const linked = linkedChemicalJobs(chemical, resultHandle || null, activeResult?.graph_handle ?? null);
        setPrepareJob(linked.prepare);
        setDetectJob(linked.detect);
      }
      setReportRefs(reports); setBudget(limits);
      setSceneHandles(scenes.rows.map(scene => ({ handle: scene.handle, name: scene.value.name })));
    }).catch(e => { if (live) setFailure(`저장된 화학 작업 읽기 실패: ${errorText(e)}`); });
    return () => { live = false; };
  }, [runId, readRevision]);
  useEffect(() => {
    const pending = [prepareJob, detectJob].filter((job): job is ChemicalJob => !!job && !jobDone.has(job.status));
    if (!pending.length) return;
    let live = true;
    const selectionAtStart = jobSelectionRevision.current;
    const timer = setInterval(() => {
      const actionAtRead = jobActionToken.current;
      void Promise.all(pending.map(job => api.job(runId, job.job_id))).then(jobs => {
        if (!live || selectionAtStart !== jobSelectionRevision.current ||
            actionAtRead !== jobActionToken.current) return;
        for (const job of jobs as ChemicalJob[]) {
          if (job.run_id !== runId) continue;
          setJobHistory(previous => [job, ...previous.filter(saved => saved.job_id !== job.job_id)]);
          if (job.protocol_id === "prolif_prepare_v1" && job.job_id === prepareJob?.job_id)
            setPrepareJob(previous => previous?.job_id === job.job_id ? job : previous);
          if (job.protocol_id === "prolif_detect_v1") {
            if (job.job_id !== detectJob?.job_id) continue;
            setDetectJob(previous => previous?.job_id === job.job_id ? job : previous);
            if (job.status === "done") {
              const handle = job.artifacts?.chemical_interaction_set ?? job.output_handles[0];
              if (handle) { setResultList(previous => [...new Set([...previous, handle])]);
                setResultHandle(previous => previous || handle); }
            }
          }
        }
        void api.budget(runId).then(value => { if (live) setBudget(value); }).catch(() => undefined);
      }).catch(e => { if (live) setFailure(`작업 상태 읽기 실패: ${errorText(e)}`); });
    }, 1200);
    return () => { live = false; clearInterval(timer); };
  }, [runId, prepareJob?.job_id, prepareJob?.status, detectJob?.job_id, detectJob?.status]);

  useEffect(() => {
    if (!complexHandle || mode !== "attach_existing") return;
    let live = true;
    setComplexResidues([]); setComplexAtoms(null); setMapping([]); setPreview(null);
    void Promise.all([api.residues(runId, complexHandle), api.allAtoms(runId, complexHandle)]).then(([residues, atoms]) => {
      if (!live) return;
      setComplexResidues(residues.ligands); setComplexAtoms(atoms);
      setModelNumber(residues.model_number);
      setLigandKey(previous => residues.ligands.some(ref => refKey(ref) === previous) ? previous : refKey(residues.ligands[0] ?? {
        model_number: 0, chain_auth: "", chain_label: null, seq_auth: 0, seq_label: null, icode: "", resname: "" }));
    }).catch(e => { if (live) setFailure(`기존 복합체 원자 읽기 실패: ${errorText(e)}`); });
    return () => { live = false; };
  }, [runId, complexHandle, mode]);
  useEffect(() => {
    const handle = imports.receptor?.handle;
    if (!handle || mode !== "create_new") { setStagingAtoms([]); return; }
    let live = true; const controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]);
    void api.chemicalStagingAtoms(runId, handle, modelNumber, signal).then(rows => {
      if (live) setStagingAtoms(rows);
    }).catch(e => { if (live) setFailure(`수용체 원자 목록 읽기 실패: ${errorText(e)}`); });
    return () => { live = false; controller.abort(); };
  }, [runId, imports.receptor?.handle, modelNumber, mode]);

  useEffect(() => {
    if (!resultHandle) { setResult(null); setResultLoadedHandle(""); setRows(null); return; }
    revokeResult(); const ticket = resultAction.current, signal = nextSignal();
    setFailure("");
    setStatus("저장된 화학 상호작용 읽는 중"); setResult(null); setResultLoadedHandle(""); setRows(null);
    void api.chemicalResult(runId, resultHandle, signal).then(value => {
      if (resultAction.current !== ticket) return;
      if (value.meta.handle !== resultHandle || value.result.schema !== "chemical_interaction_set@1")
        throw new Error("저장된 화학 결과 식별자가 다릅니다.");
      setResult(value.result); setResultLoadedHandle(resultHandle);
      setStatus(value.result.null_result ? "정상적인 빈 결과 (scientific_null)" : "저장된 계산 결과를 읽었습니다.");
    }).catch(e => { if (resultAction.current === ticket) setFailure(`화학 결과 읽기 실패: ${errorText(e)}`); });
  // The result read is explicitly bound to the selected handle and retry revision.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, resultHandle, readRevision]);
  useEffect(() => {
    if (!resultHandle || !activeResult) return;
    let live = true; const controller = new AbortController();
    void api.chemicalRows(runId, resultHandle, offset, category, pageSize,
      AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(page => {
      if (!live) return;
      if (page.handle !== resultHandle || page.offset !== offset || page.limit !== pageSize || page.rows.some(row =>
        !exactChemicalRow(row, activeResult.chemical_structure_handle))) throw new Error("화학 상호작용 행의 출처가 다릅니다.");
      setRows({ key: JSON.stringify([runId, resultHandle, offset, pageSize, category, readRevision]), page });
    }).catch(e => { if (live) setFailure(`화학 상호작용 행 읽기 실패: ${errorText(e)}`); });
    return () => { live = false; controller.abort(); };
  }, [runId, resultHandle, activeResult, offset, pageSize, category, readRevision]);
  useEffect(() => {
    if (!desiredSourceHandle || !desiredGraphHandle) return;
    const target = desiredSourceHandle, graph = desiredGraphHandle;
    let live = true; const controller = new AbortController();
    setDisplayStatus("loading"); setDisplay(null); setRowSelection(null);
    // Each read gets its own bound; one shared deadline over every catalog page timed out valid sources.
    const signal = () => AbortSignal.any([controller.signal, AbortSignal.timeout(chemicalReadTimeoutMs)]);
    void Promise.all([api.chemicalView(runId, target, signal()),
      readChemicalAtomCatalog(target, (offset, limit, pageSignal) =>
        api.chemicalAtoms(runId, target, offset, limit, pageSignal), signal),
      api.chemicalGraph(runId, graph, signal()),
      api.chemicalPreparationManifest(runId, target, signal())]).then(async ([view, catalog, graphRead, saved]) => {
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(view.text))),
        byte => byte.toString(16).padStart(2, "0")).join("");
      if (!live) return;
      if (view.handle !== target || view.kind !== "chemical_structure" || view.format !== "mmcif" ||
          view.viewer_source_sha256 !== hash || !validateChemicalCatalog(view, catalog) ||
          graphRead.meta.handle !== graph || graphRead.meta.schema !== "chemical_graph@1" ||
          graphRead.graph.chemical_structure_handle !== view.handle ||
          graphRead.graph.manifest_handle !== view.manifest_handle ||
          saved.meta.handle !== view.manifest_handle ||
          saved.meta.schema !== "chemical_preparation_manifest@1" ||
          saved.manifest.schema !== "chemical_preparation_manifest@1" ||
          saved.manifest.mode !== saved.manifest.request.mode ||
          (activeResult && view.manifest_handle !== activeResult.manifest_handle))
        throw new Error("화학 구조 바이트·원자 목록·그래프 출처가 일치하지 않습니다.");
      generation.current += 1;
      setDisplay({ generation: generation.current, view, catalog, graphHandle: graph,
        manifest: saved.manifest,
        source: { handle: view.handle, text: view.text, format: "mmcif", modelIndex: 0 } });
    }).catch(e => { if (live) { setFailure(`화학 구조 읽기 실패: ${errorText(e)}`); setDisplayStatus("error"); } });
    return () => { live = false; controller.abort(); bridge.current?.cancelNative(); };
  }, [runId, desiredSourceHandle, desiredGraphHandle, activeResult?.manifest_handle, readRevision]);

  async function importFile(kind: ImportKind, file: File | null) {
    if (!file) return;
    const ticket = beginUpload(); setUploading(kind); setPreview(null);
    try {
      const imported = await api.chemicalImport(runId, kind, file);
      if (uploadAction.current !== ticket) return;
      const inspected = await api.chemicalInspect(runId, imported.handle);
      if (uploadAction.current !== ticket || imported.kind !== kind || inspected.handle !== imported.handle) return;
      setImports(previous => ({ ...previous, [kind]: imported }));
      setInspection(previous => ({ ...previous, [kind]: inspected }));
      if (kind === "ligand_sdf") setRecordIndex(inspected.records?.[0]?.index ?? 0);
      if (kind === "receptor") setModelNumber(inspected.model_numbers?.[0] ?? 1);
      setStatus(`${file.name} 원본 바이트 저장·검사 완료`);
    } catch (e) { if (uploadAction.current === ticket) setFailure(`입력 업로드 실패: ${errorText(e)}`); }
    finally { if (uploadAction.current === ticket) setUploading(null); }
  }

  function makeArgs(): ChemicalPrepareArgs {
    const sdf = imports.ligand_sdf?.handle;
    if (!sdf) throw new Error("명시적 수소가 포함된 SDF를 업로드하세요.");
    if (connectivity === "sidecar" && !imports.receptor_bonds) throw new Error("완전한 수용체 결합 sidecar를 업로드하세요.");
    const common = { schema: "chemical_prepare_request@1" as const,
      connectivity: { kind: connectivity, sidecar_handle: connectivity === "sidecar" ? imports.receptor_bonds!.handle : null },
      ligand_sdf_handle: sdf, sdf_record_index: recordIndex,
      terminal_extensions: extensions, acknowledgement: ack };
    if (mode === "create_new") {
      if (!imports.receptor) throw new Error("준비된 수용체 PDB/mmCIF를 업로드하세요.");
      const ligand_instance: ResidueRef = { model_number: modelNumber, chain_auth: ligandChain,
        chain_label: null, seq_auth: ligandSequence, seq_label: null, icode: "", resname: ligandName };
      return { ...common, mode, receptor_input_handle: imports.receptor.handle,
        receptor_model_number: modelNumber, ligand_instance };
    }
    if (!complexHandle || !selectedLigand) throw new Error("기존 복합체와 정확한 리간드 인스턴스를 선택하세요.");
    return { ...common, mode, complex_handle: complexHandle, complex_model_number: modelNumber,
      selected_ligand: selectedLigand, hydrogen_policy: hydrogenPolicy, mapping };
  }
  async function readPreview() {
    const ticket = beginPreview(); setPreviewBusy(true);
    try { const args = makeArgs(); const value = await api.chemicalPreview(runId, args);
      if (previewAction.current === ticket) { setPreview(value); setPreviewRequest(JSON.stringify(args));
        setStatus(value.ready ? "준비 입력 검증 완료 · 계산 전" : "준비 입력에 해결할 항목이 있습니다."); }
    } catch (e) { if (previewAction.current === ticket) setFailure(`준비 미리보기 실패: ${errorText(e)}`); }
    finally { if (previewAction.current === ticket) setPreviewBusy(false); }
  }
  async function submitPrepare() {
    if (!preview?.ready || !capability?.available || run.dry_run ||
        !previewMatchesRequest(previewRequest, makeArgs())) return;
    const ticket = beginJob(); setJobBusy(true);
    try { const job = await api.chemicalPrepareJob(runId, makeArgs());
      if (jobActionToken.current === ticket && job.run_id === runId && job.protocol_id === "prolif_prepare_v1") {
        jobSelectionRevision.current += 1; setPrepareJob(job); setDetectJob(null);
        setJobHistory(previous => [job, ...previous.filter(saved => saved.job_id !== job.job_id)]);
        setStatus(chemicalSubmitStatus("prepare", job)); } }
    catch (e) { if (jobActionToken.current === ticket) setFailure(`준비 작업 저장 실패: ${errorText(e)}`); }
    finally { if (jobActionToken.current === ticket) setJobBusy(false); }
  }
  async function submitDetect() {
    const graph = preparedGraphHandle;
    if (!graph || !capability?.available || run.dry_run) return;
    const ticket = beginJob(); setJobBusy(true);
    try { const job = await api.chemicalDetectJob(runId, graph);
      if (jobActionToken.current === ticket && job.run_id === runId && job.protocol_id === "prolif_detect_v1") {
        jobSelectionRevision.current += 1; setDetectJob(job);
        setJobHistory(previous => [job, ...previous.filter(saved => saved.job_id !== job.job_id)]);
        setStatus(chemicalSubmitStatus("detect", job)); } }
    catch (e) { if (jobActionToken.current === ticket) setFailure(`상호작용 작업 저장 실패: ${errorText(e)}`); }
    finally { if (jobActionToken.current === ticket) setJobBusy(false); }
  }
  async function jobAction(stage: "prepare" | "detect", operation: "start" | "retry" | "cancel") {
    const job = stage === "prepare" ? prepareJob : detectJob;
    if (!job) return;
    const ticket = beginJob(); setJobBusy(true);
    if (operation === "cancel") setCancelBusy(true);
    try {
      let lostStart = "";
      const value = operation === "start" ? await api.startJob(runId, job.job_id).catch(async (e: unknown) => {
        // Start runs the worker synchronously; a long real attempt can outlive the proxy connection.
        // The durable job, not the lost transport response, decides whether the start took effect.
        if (e instanceof ApiError && chemicalApprovalRequired(e.status, e.approval, stage)) throw e;
        const durable = await api.job(runId, job.job_id).catch(() => null) as ChemicalJob | null;
        if (!durable || !chemicalStartProgressed(job, durable)) throw e;
        lostStart = errorText(e);
        return durable;
      })
        : operation === "retry" ? await api.retryJob(runId, job.job_id)
          : (await api.cancelJob(runId, job.job_id)).job;
      if (!chemicalJobActionCurrent(ticket, jobActionToken.current, runId, job.job_id,
          job.protocol_id, value)) return;
      setJobHistory(previous => [value as ChemicalJob,
        ...previous.filter(saved => saved.job_id !== value.job_id)]);
      if (stage === "prepare") setPrepareJob(value as ChemicalJob);
      else {
        setDetectJob(value as ChemicalJob);
        if (value.status === "done") {
          const handle = (value as ChemicalJob).artifacts?.chemical_interaction_set ?? value.output_handles[0];
          if (handle) { setResultList(previous => [...new Set([...previous, handle])]);
            setResultHandle(previous => previous || handle); }
        }
      }
      setStatus(`${stage === "prepare" ? "화학 구조 준비" : "상호작용 계산"} · ${value.status}` +
        (lostStart ? ` (시작 응답을 받지 못해 저장된 작업 상태를 다시 읽었습니다: ${lostStart})` : ""));
    } catch (e) {
      if (jobActionToken.current !== ticket) return;
      if (e instanceof ApiError && operation === "start" &&
          chemicalApprovalRequired(e.status, e.approval, stage)) {
        setApprovalFor(stage); setStatus("비용이 드는 실제 계산 승인이 필요합니다.");
      } else setFailure(`작업 ${operation} 실패: ${errorText(e)}`);
    } finally { if (jobActionToken.current === ticket) {
      setJobBusy(false); if (operation === "cancel") setCancelBusy(false);
    } }
  }
  async function approveJob() {
    if (!approvalFor) return;
    const ticket = beginJob(); setJobBusy(true);
    try { await api.approveOpenmm(runId);
      if (jobActionToken.current === ticket) { const stage = approvalFor; setApprovalFor(null);
        setStatus(`${stage === "prepare" ? "준비" : "상호작용"} 계산 승인을 기록했습니다. 시작을 다시 누르세요.`); } }
    catch (e) { if (jobActionToken.current === ticket) setFailure(`작업 승인 실패: ${errorText(e)}`); }
    finally { if (jobActionToken.current === ticket) setJobBusy(false); }
  }
  function selectRow(row: ChemicalRow) {
    if (!display || !chemicalReady || !exactChemicalRow(row, display.view.handle)) {
      setFailure("검증된 현재 화학 구조에서만 정확한 원자를 표시할 수 있습니다."); return;
    }
    setRowSelection(row); setFocusToken(value => value + 1); showAnnotation();
  }
  function chooseResult(handle: string) {
    revokeResult(); revokeReport(); setResultHandle(handle); setResult(null);
    setRowSelection(null); setRows(null); setOffset(0); setReportHandle(""); setReportMarkdown("");
    setReportBusy(false);
    const selection = ++jobSelectionRevision.current;
    const linked = linkedChemicalJobs(jobHistory, handle || null);
    setPrepareJob(linked.prepare); setDetectJob(linked.detect);
    void api.jobs(runId).then(jobs => {
      if (jobSelectionRevision.current !== selection) return;
      const chemical = jobs.filter(job => job.protocol_id === "prolif_prepare_v1" ||
        job.protocol_id === "prolif_detect_v1") as ChemicalJob[];
      if (chemical.some(job => job.run_id !== runId)) throw new Error("다른 run의 화학 작업이 섞였습니다.");
      setJobHistory(chemical);
      const selected = linkedChemicalJobs(chemical, handle || null);
      setPrepareJob(selected.prepare); setDetectJob(selected.detect);
    }).catch(e => { if (jobSelectionRevision.current === selection)
      setFailure(`선택한 결과의 작업 출처 읽기 실패: ${errorText(e)}`); });
  }
  async function makeReport() {
    if (!resultHandle) return;
    revokeReport(); const ticket = reportAction.current, scope = reportScope.current;
    const selected = resultHandle;
    setFailure(""); setReportBusy(true);
    const active = () => reportAction.current === ticket && reportScope.current === scope;
    try { const report = await api.createMethodReport(runId, selected);
      if (!active()) return;
      if (report.manifest.result_handle !== selected) throw new Error("보고서 결과 식별자가 다릅니다.");
      setReportHandle(report.handle); setReportMarkdown(report.markdown);
      setStatus("불변 화학 보고서를 저장했습니다.");
      try { const refreshed = await api.reports(runId);
        if (active()) setReportRefs(previous => [...new Map([...previous, ...refreshed]
          .map(item => [item.handle, item])).values()]); }
      catch (e) { if (active()) setFailure(`보고서는 저장되었지만 목록을 다시 읽지 못했습니다: ${errorText(e)}`); }
    } catch (e) { if (active()) setFailure(`화학 보고서 저장 실패: ${errorText(e)}`); }
    finally { if (active()) setReportBusy(false); }
  }
  async function readReport(handle: string) {
    revokeReport(); const ticket = reportAction.current, scope = reportScope.current;
    setReportHandle(handle); setReportMarkdown("");
    if (!handle) return;
    const controller = new AbortController(); reportAbort.current = controller;
    const active = () => reportAction.current === ticket && reportScope.current === scope &&
      !controller.signal.aborted;
    try { const report = await api.methodReport(runId, handle,
      AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]));
      if (!active()) return;
      if (report.handle !== handle || report.manifest.result_handle !== resultHandle) throw new Error("보고서 선택 출처가 다릅니다.");
      setReportMarkdown(report.markdown);
    } catch (e) { if (active()) setFailure(`저장된 화학 보고서 읽기 실패: ${errorText(e)}`); }
    finally { if (reportAbort.current === controller) reportAbort.current = null; }
  }

  const fileControl = (kind: ImportKind, label: string, accept: string) =>
    <label className="mw-chemical-file">{label}<input type="file" accept={accept} disabled={!!uploading || !!jobBusy}
      onChange={e => void importFile(kind, e.target.files?.[0] ?? null)} />
      {imports[kind] && <small className="mw-muted mw-mono">{imports[kind]!.handle}</small>}</label>;
  const selectedRecord = inspection.ligand_sdf?.records?.find(record => record.index === recordIndex);
  const terminalCandidates = preview?.terminal_extensions ?? [];
  const terminalCandidate = terminalResidues.find(item => refKey(item) === customTerminalResidue);
  const chosenRows = preview?.ligand_atoms ?? [];
  const graphHandle = preparedGraphHandle;
  const sourceHandle = preparedSourceHandle;
  const resultReports = reportRefs.filter(item => item.result_handle === resultHandle);
  let previewCurrent = false;
  try { previewCurrent = !!preview && previewMatchesRequest(previewRequest, makeArgs()); } catch { /* incomplete form */ }
  const annotation = rowSelection && display && annotationVisible &&
      activeResult?.chemical_structure_handle === display.view.handle &&
      exactChemicalRow(rowSelection, display.view.handle)
    ? chemicalAnnotationForRow(rowSelection, display.view.handle) : null;
  const focus = rowSelection && display && exactChemicalRow(rowSelection, display.view.handle)
    ? { sourceHandle: display.view.handle, rowId: rowSelection.row_id,
    atoms: [...new Set(Object.values(rowSelection.roles))].slice(0, 3), token: focusToken } : null;

  if (typeof window !== "undefined") window.__protviewQaChemical = () => ({
    runId, mode, generation: display?.generation ?? null, sourceHandle: display?.view.handle ?? null,
    graphHandle: display?.graphHandle ?? null, catalogReady: chemicalReady,
    resultHandle, resultTotal: activeResult?.total ?? null, selectedRowId: rowSelection?.row_id ?? null,
    prepareJobId: prepareJob?.job_id ?? null, detectJobId: detectJob?.job_id ?? null,
    native: bridge.current?.snapshot() ?? null,
  });

  return <WorkspaceShell runId={runId} pipeline="prepared inputs → chemical graph → ProLIF interactions"
    egress={displayedEgressMode(run)} onToggleTheme={onTheme} tabs={["run", "models", "jobs"]}
    budgetShort={budget && <span className="mw-muted mw-mono mw-top-budget">expensive {budget.expensive_calls.used}/{budget.expensive_calls.limit}</span>}
    railCounts={{ models: resultList.length, jobs: Number(!!prepareJob) + Number(!!detectJob) }}
    rail={{
      run: <div className="mw-chemical-stack"><Button size="sm" onClick={onExit}>기존 구조로 돌아가기</Button>
        <label>저장된 run<select className="mw-select" value={runId} onChange={e => onSwitchRun(e.target.value)}>
          {runs.map(item => <option key={item.run_id} value={item.run_id}>{item.run_id}</option>)}</select></label>
        <p className="mw-muted">화학 구조는 로컬 전용 보기입니다. 이 보기에서 M8 프롬프트, M9 보기·PNG 저장,
          M10 거리 측정·두 구조 비교를 사용할 수 없습니다.</p></div>,
      models: <div className="mw-chemical-stack"><label>저장된 화학 결과<select className="mw-select" value={resultHandle}
        onChange={e => chooseResult(e.target.value)}>
        <option value="">결과 선택</option>{resultList.map(handle => <option key={handle} value={handle}>{handle}</option>)}</select></label>
        <Button size="sm" disabled={!resultHandle} onClick={() => setReadRevision(value => value + 1)}>저장된 결과 다시 읽기</Button>
        {display && <><span className="mw-eyebrow">검증된 화학 구조</span><span className="mw-mono">{display.view.handle}</span>
          <span className="mw-muted">로컬 세대 {display.generation} · 원자 {display.catalog.total}개</span>
          <details><summary>저장된 실제 준비 선택</summary>
            <p className="mw-mono">manifest {display.view.manifest_handle} · {display.view.manifest_sha256}</p>
            <p>방식 {display.manifest.mode} · SDF 기록 #{display.manifest.request.sdf_record_index}{" "}
              · pH 주석 {display.manifest.request.acknowledgement.ph_annotation ?? "없음"} (실험 검증 아님)</p>
            <p className="mw-mono">리간드 인스턴스 {JSON.stringify(display.manifest.request.mode === "create_new"
              ? display.manifest.request.ligand_instance : display.manifest.request.selected_ligand)}</p>
            <p>{display.manifest.derived_coordinate_policy}</p>
          </details></>}
        <label>저장된 일반 보기 복원<select className="mw-select" value={sceneHandle} onChange={e => setSceneHandle(e.target.value)}>
          <option value="">보기 선택</option>{sceneHandles.map(scene => <option key={scene.handle} value={scene.handle}>{scene.name}</option>)}</select></label>
        <Button size="sm" disabled={!sceneHandle} onClick={() => onRestoreScene(sceneHandle)}>저장된 보기 복원 후 화학 보기 끝내기</Button></div>,
      jobs: <div className="mw-chemical-stack">{[prepareJob, detectJob].map(job => job && <div key={job.job_id}>
        <b>{job.protocol_id}</b><p className="mw-mono">{job.job_id}</p><p>{job.status} · attempt {job.attempt_ordinal}</p>
        {job.blocked_reason && <p role="status">시작 대기 이유: {job.blocked_reason}</p>}
        {job.failure && <ChemicalFailure failure={job.failure} />}</div>)}</div>,
    }}
    canvas={<MolstarViewer key={`chemical:${display?.generation ?? "none"}`} source={display?.source ?? null}
      representation={representation} atomCatalog={display?.catalog ?? null}
      chemicalFocus={focus} chemicalAnnotation={annotation}
      pocketOverlay={pocketOverlay}
      onPocketOverlay={(key, readback, overlayError) => {
        if (key === null) { setPocketReadback(previous => previous === null ? previous : null); return; }
        if (key !== pocketKeyRef.current) return;
        setPocketReadback(readback); setPocketOverlayError(overlayError);
      }}
      onBridge={value => { bridge.current = value; }}
      onLoadState={(source, state, message) => { if (source === display?.source) {
        setDisplayStatus(state); if (state === "error") setFailure(message ?? "화학 구조 표시 실패"); } }}
      emptyMessage={failure || (resultHandle ? "화학 구조와 원자 목록을 확인하는 중…" : "준비 작업과 상호작용 계산을 완료하거나 저장된 결과를 선택하세요.")}
      emptyIsError={!!failure} />}
    canvasOverlayTopLeft={<div className="mw-chemical-inline"><span className="mw-badge">화학 소스 · 로컬 전용</span>
      <label>표현<select className="mw-select" value={representation}
        onChange={e => setRepresentation(e.target.value as ViewerRepresentation)}>
        <option value="cartoon">cartoon</option><option value="ball-and-stick">ball-and-stick</option>
        <option value="surface">surface</option></select></label></div>}
    canvasLegend={display && <span className="mw-muted">{displayStatus === "ready" ? "실제 화학 구조" : "화학 구조 불러오는 중"}
      {rowSelection && ` · ${rowSelection.category} · ${rowSelection.row_id}`}</span>}
    strip={<div className="mw-chemical-stack"><div className="mw-chemical-inline">
      <Button size="sm" onClick={onExit}>단일 구조로 돌아가기</Button>
      <Button size="sm" disabled>프롬프트 사용 불가</Button><Button size="sm" disabled>현재 보기 저장</Button>
      <Button size="sm" disabled>현재 보기 PNG 내보내기</Button><Button size="sm" disabled>원자 거리 측정</Button>
      <Button size="sm" disabled>두 구조 비교 추가</Button></div>
      <span className="mw-muted" role="status">Chemical sources are not supported by saved-scene/export schema v1.
        화학 소스는 M8 세션, M10 측정·비교 입력에도 지원되지 않습니다. 주석을 숨겨도 제한은 유지됩니다.</span>
      <span className="mw-muted" data-chemical-pocket-restriction>{featureGates({ sourceKind: "chemical_structure",
        overlayActive: !!pocketState, comparisonActive: false }).m9}</span></div>}
    inspectorTitle="준비 입력과 실제 화학 상호작용"
    inspector={<div className="mw-chemical-stack">
      <InspectorSection><span className="mw-eyebrow">방법 지원과 전제 조건</span>
        <p>{capability?.available ? `지원: ${capability.protocol ?? "prolif_prepared_explicit_h@1"}`
          : `사용 불가: ${capability?.reason ?? "로컬 화학 작업자와 고정 버전을 확인할 수 없습니다."}`}</p>
        <p className="mw-muted">준비된 수용체의 완전한 결합 그래프·명시적 H, 3D V2000 SDF 한 기록·명시적 H가 필요합니다.
          두 계산은 각각 내구성 있는 비싼 작업이며 시작 전에 승인 절차가 있을 수 있습니다.</p></InspectorSection>
      <InspectorSection><span className="mw-eyebrow">1 · 입력 모드와 실제 원본</span>
        <label>입력 방식<select className="mw-select" value={mode} onChange={e => {
          revoke(); setMode(e.target.value as ChemicalMode); setPreview(null); setMapping([]); setExtensions([]); }}>
          <option value="create_new">새 화학 구조 만들기</option><option value="attach_existing">기존 복합체에 SDF 화학 연결</option></select></label>
        {mode === "create_new" ? <>{fileControl("receptor", "준비된 수용체 PDB/mmCIF", ".pdb,.cif,.mmcif")}
          <label>수용체 model<select className="mw-select" value={modelNumber} onChange={e => setModelNumber(Number(e.target.value))}>
            {(inspection.receptor?.model_numbers ?? [modelNumber]).map(value => <option key={value} value={value}>{value}</option>)}</select></label>
          <div className="mw-chemical-inline"><label>리간드 chain auth<input value={ligandChain} maxLength={8} onChange={e => setLigandChain(e.target.value)} /></label>
            <label>seq auth<input type="number" value={ligandSequence} onChange={e => setLigandSequence(Number(e.target.value))} /></label>
            <label>resname<input value={ligandName} maxLength={8} onChange={e => setLigandName(e.target.value)} /></label></div></>
          : <><label>기존 준비된 복합체<select className="mw-select" value={complexHandle}
            onChange={e => { setComplexHandle(e.target.value); setPreview(null); }}>
            <option value="">복합체 선택</option>{complexOptions.map(source => <option key={source.handle} value={source.handle}>
              {source.kind} · {source.handle}</option>)}</select></label>
            <label>정확한 리간드 인스턴스<select className="mw-select" value={ligandKey} onChange={e => {
              setLigandKey(e.target.value); setMapping([]); setPreview(null); }}><option value="">리간드 선택</option>
              {complexResidues.map(ref => <option key={refKey(ref)} value={refKey(ref)}>
                {ref.resname} · model {ref.model_number} · auth {ref.chain_auth}/{ref.seq_auth}{ref.icode}{" "}
                · label {ref.chain_label ?? "?"}/{ref.seq_label ?? "?"}</option>)}</select></label>
            <label>리간드 H 처리<select className="mw-select" value={hydrogenPolicy}
              onChange={e => { setHydrogenPolicy(e.target.value as HydrogenPolicy); setMapping([]); setPreview(null); }}>
              <option value="map_existing">기존 H까지 정확히 매핑</option>
              <option value="replace_from_sdf">SDF H로 교체 · 중원자는 정확히 매핑</option></select></label></>}
        {fileControl("ligand_sdf", "명시적 H가 있는 3D 리간드 V2000 SDF", ".sdf")}
        <label>SDF 기록<select className="mw-select" value={recordIndex} onChange={e => {
          setRecordIndex(Number(e.target.value)); setMapping([]); setPreview(null); }}>
          {(inspection.ligand_sdf?.records ?? []).map(record => <option key={record.index} value={record.index}>
            #{record.index} {record.title} · {record.atom_count} atoms · H {record.hydrogen_count}</option>)}</select></label>
        {selectedRecord && <p className="mw-muted">선택한 원본 기록: {selectedRecord.has_3d ? "3D" : "3D 좌표 없음"}{" "}
          · H {selectedRecord.hydrogen_count} · {selectedRecord.heavy_atom_count} heavy</p>}
        <label>수용체 결합 제공<select className="mw-select" value={connectivity}
          onChange={e => { setConnectivity(e.target.value as "pdb_conect" | "sidecar"); setPreview(null); }}>
          <option value="pdb_conect">완전한 PDB CONECT</option><option value="sidecar">정확한 원자 ID sidecar</option></select></label>
        {connectivity === "sidecar" && fileControl("receptor_bonds", "완전한 receptor_bonds@1 JSON", ".json")}
      </InspectorSection>
      <InspectorSection><span className="mw-eyebrow">2 · 매핑·말단·공급 화학 확인</span>
        <Button size="sm" disabled={previewBusy || !!uploading} onClick={() => void readPreview()}>
          {previewBusy ? "읽는 중…" : "준비 조건 미리보기"}</Button>
        {preview && <><p role="status">{!previewCurrent ? "입력이 바뀌었습니다 · 다시 미리보기" : preview.ready ? "계산 준비 가능" : "준비 조건 미충족"}{" "}
          · 수용체 {preview.included_receptor_atoms} · 물 제외 {preview.excluded_water_atoms}{" "}
          · 리간드 {preview.selected_ligand_atoms}</p>
          {preview.blockers.map((blocker, i) => <div key={`${blocker.code}:${i}`} role="alert">
            <p>{blocker.code}: {blocker.message}</p>
            {blocker.atoms.length > 0 && <details><summary>문제가 있는 정확한 원자 {blocker.atoms.length}개</summary>
              {blocker.atoms.map((ref, index) => <p className="mw-mono" key={`${ref.site_index}:${index}`}>
                {atomLabel(ref)} · model {ref.residue.model_number} · auth {ref.residue.chain_auth}/{ref.residue.seq_auth}{ref.residue.icode}{" "}
                · label {ref.residue.chain_label ?? "?"}/{ref.residue.seq_label ?? "?"} · site {ref.site_index}</p>)}</details>}
          </div>)}
          {preview.limitations.map((item, i) => <p key={i} className="mw-muted">{item}</p>)}
          {preview.mapping_proposals.length > 0 && <div className="mw-chemical-stack" aria-label="명시적 매핑 제안">
            <b>원본 ID 기반 제안 · 자동 적용 안 함</b>{preview.mapping_proposals.map(proposal =>
              <div key={proposal.sdf_atom_index}>SDF #{proposal.sdf_atom_index}
                {proposal.reason && ` · ${proposal.reason}`}
                {(proposal.candidates ?? []).map((candidate, index) =>
                  <Button key={`${proposal.sdf_atom_index}:${index}`} size="sm" onClick={() => {
                    setMapping(previous => [...previous.filter(item => item.sdf_atom_index !== proposal.sdf_atom_index),
                      { sdf_atom_index: proposal.sdf_atom_index, source_atom: candidate.source_atom }]);
                  }}>명시적으로 선택: {atomLabel(candidate.source_atom)} · Δ {candidate.discrepancy_A.toFixed(4)} Å</Button>)}</div>)}</div>}
          {mode === "attach_existing" && <div className="mw-chemical-mapping" role="region" aria-label="SDF 전체 원자 대응" tabIndex={0}>
            <p className="mw-muted">파생 화학 구조는 수용체의 원래 좌표와 선택한 SDF 기록의 리간드 좌표를 그대로 사용합니다.
              정렬하지 않으며, 매핑된 원본 site의 좌표 차이는 0.002 Å 이하여야 합니다.</p>
            {chosenRows.map((atom: ChemicalLigandAtom) => {
              const choice = mapping.find(item => item.sdf_atom_index === atom.sdf_atom_index);
              const candidates = ligandSourceAtoms.filter(item =>
                canonicalChemicalElement(item.ref.element) === canonicalChemicalElement(atom.element));
              return <label key={atom.sdf_atom_index}>SDF #{atom.sdf_atom_index} {atom.atom_name ?? "이름 없음"}
                {atom.name_generated && " (SDF 원본 이름 없음 · 생성된 이름)"}
                {atom.atom_map_tag && ` · map ${atom.atom_map_tag}`} · {atom.element} · {atom.hydrogen ? "H" : "heavy"}
                {atom.formal_charge != null && ` · 공급 형식전하 ${atom.formal_charge}`}{" "}
                · [{atom.coordinate_A.join(", ")}]
                <select className="mw-select" value={choice ? JSON.stringify(choice.source_atom) : ""} onChange={e => {
                  const selected = candidates.find(row => JSON.stringify(row.ref) === e.target.value)?.ref;
                  setMapping(previous => [...previous.filter(item => item.sdf_atom_index !== atom.sdf_atom_index),
                    ...(selected ? [{ sdf_atom_index: atom.sdf_atom_index, source_atom: selected }] : [])]);
                }}><option value="">명시적으로 선택</option>{candidates.map(row => <option key={row.ref.site_index}
                  value={JSON.stringify(row.ref)}>{atomLabel(row.ref)} · site {row.ref.site_index}</option>)}</select>
                {preview.ligand_mapping.find(item => item.sdf_atom_index === atom.sdf_atom_index)?.discrepancy_A != null &&
                  <small>검증된 좌표 차이 {preview.ligand_mapping.find(item => item.sdf_atom_index === atom.sdf_atom_index)!.discrepancy_A.toFixed(4)} Å</small>}
              </label>;
            })}</div>}
          <p className="mw-muted">낯선 미신고 확장을 모두 검출할 수는 없습니다. 완전성은 사용자가 선언합니다.
            말단 단백질 잔기의 실제 공급 원자 이름만 선언할 수 있으며, 미리보기에서 원자·부착 결합을 확인하세요.</p>
          {preview.terminal_extensions.map(item => <div key={refKey(item.residue)} className="mw-chemical-stack"><label>
            <input type="checkbox" checked={extensions.some(ext => refKey(ext.residue) === refKey(item.residue))}
              onChange={e => setExtensions(previous => e.target.checked
                ? [...previous, { residue: item.residue, atom_names: item.atom_names, approve_supplied_graph: true }]
                : previous.filter(ext => refKey(ext.residue) !== refKey(item.residue)))} />
            말단 확장 승인: {item.residue.resname} {item.residue.chain_auth}/{item.residue.seq_auth}{" "}
            · {item.atom_names.join(", ")}</label>
            <small>말단 {item.terminal_anchor ?? "검증 전"} · 실제 원자 {item.resolved_atoms?.length ?? 0}개
              · 부착 결합 {item.attachment_bonds?.length ?? 0}개</small>
            {(item.resolved_atoms?.length || item.attachment_bonds?.length || item.extension_bonds?.length) ?
              <details><summary>해결된 원자와 공급 결합</summary>
                {item.resolved_atoms?.map(ref => <p key={JSON.stringify(ref)} className="mw-mono">{atomLabel(ref)}</p>)}
                {item.attachment_bonds?.map((bond, i) => <p key={`attach:${i}`} className="mw-mono">부착: {atomLabel(bond.first)} — {atomLabel(bond.second)}</p>)}
                {item.extension_bonds?.map((bond, i) => <p key={`extension:${i}`} className="mw-mono">확장: {atomLabel(bond.first)} — {atomLabel(bond.second)}</p>)}
              </details> : null}</div>)}
          <div className="mw-chemical-inline"><label>사용자 선언 말단 잔기<select className="mw-select" value={customTerminalResidue}
            onChange={e => { setCustomTerminalResidue(e.target.value);
              setCustomTerminalNames(extensions.find(item => refKey(item.residue) === e.target.value)?.atom_names.join(", ") ?? ""); }}>
            <option value="">공급 원자 목록의 잔기 선택</option>
            {terminalResidues.map(item => <option key={refKey(item)} value={refKey(item)}>
              {item.resname} · model {item.model_number} · {item.chain_auth}/{item.seq_auth}{item.icode}</option>)}</select></label>
            <label>실제 추가 원자 이름 (쉼표 구분)<input value={customTerminalNames}
              onChange={e => setCustomTerminalNames(e.target.value)} placeholder="CAY, CY, OY" /></label>
            <Button size="sm" disabled={!terminalCandidate || !customTerminalNames.trim()} onClick={() => {
              if (!terminalCandidate) return;
              let names: string[];
              try { names = declaredTerminalNames(terminalCandidate, customTerminalNames,
                mode === "create_new" ? stagingAtoms.map(row => row.ref) : complexAtoms?.rows.map(row => row.ref) ?? []); }
              catch (error) { setFailure(errorText(error)); return; }
              setExtensions(previous => [...previous.filter(item => refKey(item.residue) !== customTerminalResidue),
                { residue: terminalCandidate, atom_names: names, approve_supplied_graph: true }]);
            }}>정확한 말단 원자 선언</Button></div>
          {extensions.map(item => <div key={`declared:${refKey(item.residue)}`} className="mw-chemical-inline mw-mono">
            선언: {item.residue.resname} {item.residue.chain_auth}/{item.residue.seq_auth}{item.residue.icode}{" "}
            · {item.atom_names.join(", ")} · 공급 그래프 승인
            <Button size="sm" aria-label={`말단 선언 제거 ${refKey(item.residue)}`}
              onClick={() => setExtensions(previous => previous.filter(entry => refKey(entry.residue) !== refKey(item.residue)))}>
              선언 제거</Button></div>)}</>}
        <label><input type="checkbox" checked={ack.supplied_graph_complete}
          onChange={e => setAck(previous => ({ ...previous, supplied_graph_complete: e.target.checked }))} /> 공급된 수용체 결합 그래프가 완전함</label>
        <label><input type="checkbox" checked={ack.supplied_hydrogens_complete}
          onChange={e => setAck(previous => ({ ...previous, supplied_hydrogens_complete: e.target.checked }))} /> 공급된 수소가 완전함</label>
        <label><input type="checkbox" checked={ack.use_supplied_protonation_tautomer}
          onChange={e => setAck(previous => ({ ...previous, use_supplied_protonation_tautomer: e.target.checked }))} /> 공급된 protonation/tautomer 그대로 사용</label>
        <label><input type="checkbox" checked={ack.infer_receptor_orders_charges}
          onChange={e => setAck(previous => ({ ...previous, infer_receptor_orders_charges: e.target.checked }))} /> 수용체 bond order/charge 추론 동의</label>
        <label>준비 설명 (검증되지 않은 로컬 주석)<input value={ack.description} maxLength={500}
          onChange={e => setAck(previous => ({ ...previous, description: e.target.value }))} /></label>
        <label>pH 메모 (실험 검증 아님)<input type="number" min={0} max={14} step="any"
          value={ack.ph_annotation ?? ""} onChange={e => setAck(previous => ({ ...previous,
            ph_annotation: e.target.value === "" ? null : Number(e.target.value) }))} /></label>
        <Button size="sm" disabled={!preview?.ready || !previewCurrent || !capability?.available || jobBusy || run.dry_run}
          onClick={() => void submitPrepare()}>화학 구조 준비 작업 저장</Button>
      </InspectorSection>
      <InspectorSection><span className="mw-eyebrow">3 · 실제 계산 작업과 승인</span>
        {prepareJob && <div className="mw-chemical-job"><b>화학 구조 준비 · {prepareJob.status}</b>
          <span className="mw-mono">{prepareJob.job_id}</span>
          {prepareJob.blocked_reason && <p>시작 대기 이유: {prepareJob.blocked_reason}</p>}
          {prepareJob.cancel_requested && <p role="status">준비 작업 취소 요청됨 · 종료 확인 중</p>}
          <Button size="sm" disabled={jobBusy || !["queued", "claimed"].includes(prepareJob.status)}
            onClick={() => void jobAction("prepare", "start")}>준비 작업 시작</Button>
          <Button size="sm" disabled={!chemicalCanCancel(prepareJob.status, prepareJob.cancel_requested, cancelBusy)}
            onClick={() => void jobAction("prepare", "cancel")}>준비 작업 취소</Button>
          <Button size="sm" disabled={jobBusy || !["failed", "interrupted"].includes(prepareJob.status)}
            onClick={() => void jobAction("prepare", "retry")}>준비 작업 재시도</Button>
          {prepareJob.failure && <ChemicalFailure failure={prepareJob.failure} />}
          {sourceHandle && graphHandle && <p className="mw-mono">source {sourceHandle}<br />graph {graphHandle}</p>}</div>}
        <Button size="sm" disabled={!graphHandle || jobBusy || !capability?.available || run.dry_run}
          onClick={() => void submitDetect()}>상호작용 계산 작업 저장</Button>
        {detectJob && <div className="mw-chemical-job"><b>ProLIF 계산 · {detectJob.status}</b>
          <span className="mw-mono">{detectJob.job_id}</span>
          {detectJob.blocked_reason && <p>시작 대기 이유: {detectJob.blocked_reason}</p>}
          {detectJob.cancel_requested && <p role="status">상호작용 작업 취소 요청됨 · 종료 확인 중</p>}
          <Button size="sm" disabled={jobBusy || !["queued", "claimed"].includes(detectJob.status)}
            onClick={() => void jobAction("detect", "start")}>상호작용 작업 시작</Button>
          <Button size="sm" disabled={!chemicalCanCancel(detectJob.status, detectJob.cancel_requested, cancelBusy)}
            onClick={() => void jobAction("detect", "cancel")}>상호작용 작업 취소</Button>
          <Button size="sm" disabled={jobBusy || !["failed", "interrupted"].includes(detectJob.status)}
            onClick={() => void jobAction("detect", "retry")}>상호작용 작업 재시도</Button>
          {detectJob.failure && <ChemicalFailure failure={detectJob.failure} />}</div>}
        {approvalFor && <div role="alert"><p>첫 비싼 {approvalFor === "prepare" ? "준비" : "상호작용"} 계산을 승인해야 합니다.</p>
          <Button size="sm" disabled={jobBusy} onClick={() => void approveJob()}>이 실제 작업 승인</Button></div>}
      </InspectorSection>
      <InspectorSection><span className="mw-eyebrow">4 · 불변 결과와 정확한 원자 초점</span>
        <label>저장된 화학 결과<select className="mw-select" value={resultHandle}
          onChange={e => chooseResult(e.target.value)}>
          <option value="">결과 선택</option>{resultList.map(handle => <option key={handle} value={handle}>{handle}</option>)}</select></label>
        {activeResult && <><p>{activeResult.null_result ? "정상적인 빈 결과 (scientific_null)" : `실제 계산 행 ${activeResult.total}개`}</p>
          {activeResult.limitations.map((item, i) => <p className="mw-muted" key={i}>{item}</p>)}</>}
        <label>범주<select className="mw-select" value={category} onChange={e => { setCategory(e.target.value as "" | ChemicalCategory); setOffset(0); setRowSelection(null); }}>
          <option value="">전체</option>{chemicalCategories.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
        <div className="mw-chemical-rows" role="region" aria-label="화학 상호작용 행" tabIndex={0}>
          {selectedResultRows?.rows.map(row => <button type="button" className="mw-chemical-row" key={row.row_id}
            disabled={!chemicalReady} onClick={() => selectRow(row)}>
            <b>{row.category}</b> · {row.row_id} · {row.distance_roles.join("···")} {row.distance_A.toFixed(3)} Å
            {row.DHA_angle_deg != null && ` · D–H···A ${row.DHA_angle_deg.toFixed(1)}°`}
            <small>{row.ligand_atoms.map(ref => atomLabel(ref)).join(", ")} ↔ {row.receptor_atoms.map(ref => atomLabel(ref)).join(", ")}</small>
          </button>)}</div>
        <div className="mw-chemical-inline"><label>페이지 크기<select className="mw-select" value={pageSize}
          onChange={e => { setPageSize(Number(e.target.value) as 10 | 25 | 50); setOffset(0); }}>
          <option value={10}>10</option><option value={25}>25</option><option value={50}>50</option></select></label>
          <Button size="sm" disabled={offset === 0}
          onClick={() => setOffset(value => Math.max(0, value - pageSize))}>이전 페이지</Button>
          <span>{selectedResultRows ? selectedResultRows.total === 0 ? "0 / 0"
            : `${offset + 1}–${Math.min(offset + selectedResultRows.rows.length, selectedResultRows.total)} / ${selectedResultRows.total}` : "행 읽는 중"}</span>
          <Button size="sm" disabled={!selectedResultRows || offset + selectedResultRows.rows.length >= selectedResultRows.total}
            onClick={() => setOffset(value => value + pageSize)}>다음 페이지</Button></div>
        {rowSelection && <><p>선택한 실제 행: {rowSelection.category} · {rowSelection.row_id}</p>
          <p className="mw-muted">거리 끝점 {rowSelection.distance_roles.join(" / ")} · {rowSelection.distance_A.toFixed(3)} Å
            {rowSelection.DHA_angle_deg == null ? " · D–H···A 각도 없음" : ` · D–H···A ${rowSelection.DHA_angle_deg.toFixed(1)}°`}</p>
          <details><summary>정확한 역할·원본 native 원자 인덱스</summary>
            {Object.entries(rowSelection.roles).map(([role, ref]) => <p key={role} className="mw-mono">
              {role}: {atomLabel(ref)} · site {ref.site_index} · 표시 좌표 [{rowSelection.role_coordinates_A[role]?.join(", ")}]
              · 엔진 좌표 [{rowSelection.engine_role_coordinates_A[role]?.join(", ")}]</p>)}
            <p className="mw-mono">ligand native parent [{rowSelection.native_parent_indices.ligand.join(", ")}]
              · within [{rowSelection.native_within_residue_indices.ligand.join(", ")}]</p>
            <p className="mw-mono">receptor native parent [{rowSelection.native_parent_indices.protein.join(", ")}]
              · within [{rowSelection.native_within_residue_indices.protein.join(", ")}]</p>
          </details>
          <Button size="sm" onClick={() => { if (annotationVisible) setAnnotationVisible(false); else showAnnotation(); }}>
            {annotationVisible ? "기하 주석 숨기기" : "기하 주석 표시"}</Button>
          <Button size="sm" onClick={() => setFocusToken(value => value + 1)}>정확한 원자 다시 초점</Button></>}
      </InspectorSection>
      <InspectorSection><span className="mw-eyebrow">5 · 저장된 보고서</span>
        <Button size="sm" disabled={!activeResult || reportBusy} onClick={() => void makeReport()}>화학 보고서 저장</Button>
        <label>저장된 보고서<select className="mw-select" value={reportHandle}
          onChange={e => void readReport(e.target.value)}><option value="">보고서 선택</option>
          {resultReports.map(item => <option key={item.handle} value={item.handle}>{item.handle}</option>)}</select></label>
        {reportHandle && <div className="mw-chemical-inline">
          <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, reportHandle, "markdown")}>Markdown 다운로드</a>
          <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, reportHandle, "json")}>정확한 JSON 다운로드</a></div>}
        {reportMarkdown && <pre className="mw-report-preview" aria-label="저장된 화학 보고서">{reportMarkdown}</pre>}</InspectorSection>
      <InspectorSection><span className="mw-eyebrow">6 · fpocket 후보 공동 (화학 구조의 단백질 투영)</span>
        <PocketPanel panel="chemical" run={run} capability={capabilities?.methods?.pocket_detection}
          sourceOptions={pocketSources} displayedSourceHandle={display?.view.handle ?? null} viewerReady={chemicalReady}
          blockedReason={null} overlay={pocketState?.request ?? null} overlayApplied={pocketReadback}
          overlayError={pocketOverlayError} overlayNotice={pocketNotice} onOverlay={requestPocketOverlay}
          onReturnToSource={() => requestPocketOverlay(null)} /></InspectorSection>
      {status && <InspectorSection><p role="status">{status}</p></InspectorSection>}
      {failure && <InspectorSection><p role="alert" className="mw-table-error">{failure}</p>
        <Button size="sm" onClick={() => setReadRevision(value => value + 1)}>저장된 데이터 다시 읽기</Button></InspectorSection>}
    </div>} />;
}

declare global {
  interface Window { __protviewQaChemical?: () => { runId: string; mode: ChemicalMode;
    generation: number | null; sourceHandle: string | null; graphHandle: string | null;
    catalogReady: boolean; resultHandle: string; resultTotal: number | null;
    selectedRowId: string | null; prepareJobId: string | null; detectJobId: string | null;
    native: ReturnType<ViewerBridge["snapshot"]> | null } }
}
