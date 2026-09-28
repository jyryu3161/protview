"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type RunSummary, type SavedReportRef } from "@/lib/api";
import { Button } from "./primitives";
import { cancelRerunNotice, capabilityStatusText, chainArgument, clampOpacity, clampTopK, DEFAULT_OPACITY, DEFAULT_TOP_K,
  DESCRIPTOR_KEYS, descriptorText, DRUGGABILITY_WARNING, geometryError, LIMITATION_NOTE, MAX_TOP_K, NONDETERMINISM_NOTE,
  OVERLAY_LABEL, overlayRequest, pocketActionCurrent, pocketDisplay, pocketUiState, RELATIVE_SCORE_NOTE, reopenDecision,
  type PocketActionStamp, type PocketCapability, type PocketJob, type PocketOverlayReadback, type PocketOverlayRequest,
  type PocketPanelKind, type PocketPreflight, type PocketReportArtifact, type PocketSetRow, type PocketSourceKind,
  type PocketSummary } from "@/lib/pockets";

const EXCLUDED_LABELS: Record<string, string> = { water: "물", ligand: "리간드", ion: "이온", hydrogen: "수소(H/D)",
  unselected_chain: "선택하지 않은 체인" };
const DESCRIPTOR_LABELS: Record<string, string> = { score: "Score", druggability_score: "Druggability Score",
  alpha_sphere_count: "Number of Alpha Spheres", total_sasa_A2: "Total SASA", volume_A3: "Volume" };
const UI_STATE_TEXT = { loading: "불러오는 중", ready: "준비", scientific_null: "정상적인 빈 결과 (scientific_null)",
  failed: "실패", unavailable: "사용할 수 없음" } as const;
const ACTIVE_JOB = new Set(["queued", "claimed", "running"]);
const errorText = (e: unknown) => e instanceof Error ? e.message : String(e);
const shortHandle = (handle: string) => handle.split("/").at(-1)?.slice(0, 12) ?? handle;
const mib = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(1)} MiB`;

export interface PocketPanelProps {
  panel: PocketPanelKind;
  run: RunSummary;
  capability: PocketCapability | null | undefined;
  sourceOptions: { handle: string; kind: PocketSourceKind }[];
  displayedSourceHandle: string | null;
  viewerReady: boolean;
  /** A reason that blocks pocket detection and overlay (e.g. M10 comparison). */
  blockedReason: string | null;
  overlay: PocketOverlayRequest | null;
  overlayApplied: PocketOverlayReadback | null;
  overlayError: string | null;
  overlayNotice: string | null;
  onOverlay: (request: PocketOverlayRequest | null) => void;
  /** Main panel only: display the stored pocket source in the ordinary viewer. The host rejects another run's request. */
  onShowSource?: (runId: string, handle: string, kind: PocketSourceKind) => void;
  onReturnToSource: () => void;
}

export function PocketPanel(p: PocketPanelProps) {
  const runId = p.run.run_id;
  const [sourceHandle, setSourceHandle] = useState("");
  const [chainSelection, setChainSelection] = useState<string[] | null>(null);
  const [defaultChains, setDefaultChains] = useState<{ source: string; chains: string[] } | null>(null);
  const [preflight, setPreflight] = useState<{ key: string; value: PocketPreflight } | null>(null);
  const [preflightError, setPreflightError] = useState<{ key: string; message: string } | null>(null);
  const [preflightRetry, setPreflightRetry] = useState(0);
  const [job, setJob] = useState<PocketJob | null>(null);
  const [jobBusy, setJobBusy] = useState(false);
  const [approvalNeeded, setApprovalNeeded] = useState(false);
  const [jobError, setJobError] = useState("");
  const [notice, setNotice] = useState("");
  const [sets, setSets] = useState<PocketSetRow[]>([]);
  const [setsError, setSetsError] = useState("");
  const [setsRetry, setSetsRetry] = useState(0);
  const [setHandle, setSetHandle] = useState("");
  const [summary, setSummary] = useState<PocketSummary | null>(null);
  const [summaryPending, setSummaryPending] = useState(false);
  const [summaryError, setSummaryError] = useState("");
  const [topK, setTopK] = useState(DEFAULT_TOP_K);
  const [selectedRank, setSelectedRank] = useState<number | null>(null);
  const [geometryBusy, setGeometryBusy] = useState(false);
  const [selectionError, setSelectionError] = useState("");
  const [showSpheres, setShowSpheres] = useState(true);
  const [showLining, setShowLining] = useState(true);
  const [opacity, setOpacity] = useState(DEFAULT_OPACITY);
  const [focusToken, setFocusToken] = useState(0);
  const [reports, setReports] = useState<SavedReportRef[]>([]);
  const [report, setReport] = useState<{ setHandle: string; artifact: PocketReportArtifact } | null>(null);
  const [reportBusy, setReportBusy] = useState(false);
  const [reportError, setReportError] = useState("");
  const action = useRef(0);
  const live = useRef<PocketActionStamp>({ runId, action: 0, source: null, setHandle: null, rank: null });
  live.current = { runId, action: action.current, source: sourceHandle || null, setHandle: setHandle || null, rank: selectedRank };
  const stamp = (overrides: Partial<PocketActionStamp> = {}): PocketActionStamp =>
    ({ ...live.current, action: ++action.current, ...overrides });
  // Late responses must not reach a panel that unmounted (the panel is keyed by run) or the host of a newer run.
  const mounted = useRef(true);
  const latest = useRef(p);
  latest.current = p;
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; action.current += 1; };
  }, []);
  const current = (captured: PocketActionStamp) =>
    pocketActionCurrent(captured, { ...live.current, action: action.current }, mounted.current);

  const capability = p.capability ?? null;
  const sourceKind = p.sourceOptions.find(option => option.handle === sourceHandle)?.kind ?? null;
  const chainsForRequest = chainSelection === null ? [] : chainArgument(chainSelection,
    defaultChains?.source === sourceHandle ? defaultChains.chains : []);
  const preflightKey = JSON.stringify([runId, sourceHandle, chainsForRequest, preflightRetry]);
  const activePreflight = preflight?.key === preflightKey ? preflight.value : null;
  const activePreflightError = preflightError?.key === preflightKey ? preflightError.message : "";
  const uiState = pocketUiState({ capability, jobStatus: summary ? null : job?.status ?? null, summaryPending,
    readError: summaryError || null, summary });
  const display = summary ? pocketDisplay(summary.pockets, summary.total_count, topK) : null;
  const overlayOn = !!p.overlay;
  const applied = p.overlay && p.overlayApplied?.key === p.overlay.key ? p.overlayApplied : null;
  const savedSetReports = reports.filter(item => item.analysis_type === "pocket_detection" && item.result_handle === setHandle);
  const shownReport = report?.setHandle === setHandle ? report.artifact : null;

  useEffect(() => {
    if (p.sourceOptions.some(option => option.handle === sourceHandle)) return;
    const displayed = p.sourceOptions.find(option => option.handle === p.displayedSourceHandle);
    setSourceHandle(displayed?.handle ?? p.sourceOptions.at(-1)?.handle ?? "");
    setChainSelection(null);
  }, [p.sourceOptions, p.displayedSourceHandle, sourceHandle]);

  useEffect(() => {
    if (!sourceHandle) return;
    let active = true;
    const controller = new AbortController();
    const key = preflightKey, source = sourceHandle, defaultRequest = chainSelection === null;
    api.pocketPreflight(runId, source, chainsForRequest, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]))
      .then(value => {
        if (!active || value.source_handle !== source) return;
        setPreflight({ key, value }); setPreflightError(null);
        if (defaultRequest && value.ready) setDefaultChains({ source, chains: value.selected_chains });
      }).catch(e => { if (active) setPreflightError({ key, message: errorText(e) }); });
    return () => { active = false; controller.abort(); };
  // The preflight read is keyed by run, source, resolved chain argument and retry revision.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preflightKey]);

  const refreshSets = useCallback(() => setSetsRetry(value => value + 1), []);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]);
    Promise.all([api.pocketSets(runId, signal), api.reports(runId, signal)]).then(([list, saved]) => {
      if (!active) return;
      if (list.schema !== "pocket_set_list@1") throw new Error("포켓 결과 목록 형식이 다릅니다.");
      setSets(list.rows); setReports(saved); setSetsError("");
    }).catch(e => { if (active) setSetsError(`포켓 기록 읽기 실패: ${errorText(e)}`); });
    return () => { active = false; controller.abort(); };
  }, [runId, setsRetry]);

  useEffect(() => {
    if (!job || !ACTIVE_JOB.has(job.status)) return;
    let active = true;
    const jobId = job.job_id;
    const timer = window.setInterval(() => {
      void api.pocketJob(runId, jobId).then(value => {
        if (active && value.run_id === runId && value.job_id === jobId)
          setJob(previous => previous?.job_id === jobId ? value : previous);
      }).catch(() => undefined);
    }, 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [runId, job?.job_id, job?.status]);

  const openSet = useCallback(async (handle: string) => {
    const captured = stamp({ setHandle: handle, rank: null });
    setSetHandle(handle); setSelectedRank(null); setSummary(null); setSummaryError(""); setSelectionError("");
    setSummaryPending(true); setReportError("");
    if (p.overlay && p.overlay.setHandle !== handle) p.onOverlay(null);
    live.current = { ...live.current, setHandle: handle, rank: null };
    try {
      const value = await api.pocketResult(runId, handle);
      if (!current(captured)) return;
      if (value.schema !== "pocket_set_summary@1" || value.handle !== handle) throw new Error("포켓 결과가 선택한 handle과 다릅니다.");
      setSummary(value);
    } catch (e) { if (current(captured)) setSummaryError(`포켓 결과 읽기 실패: ${errorText(e)}`); }
    finally { if (current(captured)) setSummaryPending(false); }
  // stamp/current read the live refs; the callback only needs the run and overlay identity.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, p.overlay, p.onOverlay]);

  useEffect(() => {
    if (job?.status === "done" && job.artifacts?.pocket_set && job.artifacts.pocket_set !== setHandle) {
      void openSet(job.artifacts.pocket_set); refreshSets();
    }
    if (job && ["failed", "cancelled", "interrupted"].includes(job.status)) refreshSets();
  // Only a newly completed job opens its own immutable result.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.job_id, job?.status]);

  async function start(jobId: string) {
    const captured = stamp();
    setJobBusy(true); setJobError(""); setApprovalNeeded(false);
    try {
      const value = await api.startJob(runId, jobId).catch(async (e: unknown) => {
        if (e instanceof ApiError && e.approval) throw e;
        // Start runs the worker synchronously; the durable job decides what happened if the response is lost.
        const durable = await api.pocketJob(runId, jobId).catch(() => null);
        if (!durable || ["queued", "claimed"].includes(durable.status)) throw e;
        return durable;
      }) as PocketJob;
      if (current(captured) && value.run_id === runId && value.job_id === jobId) {
        setJob(value);
        if (!ACTIVE_JOB.has(value.status)) setNotice("");
      }
    } catch (e) {
      if (!current(captured)) return;
      if (e instanceof ApiError && e.approval) { setApprovalNeeded(true); setNotice("첫 비싼 계산이므로 승인이 필요합니다."); }
      else setJobError(`포켓 작업 시작 실패: ${errorText(e)}`);
      void api.pocketJob(runId, jobId).then(value => { if (current(captured)) setJob(value); }).catch(() => undefined);
    } finally { setJobBusy(false); }
  }

  async function detect() {
    if (!activePreflight?.ready || !capability?.available || p.blockedReason) return;
    const captured = stamp();
    const source = sourceHandle, chains = chainsForRequest;
    setJobBusy(true); setJobError(""); setNotice(""); setApprovalNeeded(false);
    try {
      const value = await api.submitPockets(runId, source, chains) as PocketJob & { plan_only?: boolean };
      if (!current(captured)) return;
      if (value.plan_only) { setNotice("dry-run 계획만 반환되었습니다. 작업은 만들어지지 않았고 계산·예산은 쓰이지 않았습니다."); return; }
      if (value.run_id !== runId || value.protocol_id !== "fpocket_detect_v1" || value.input_handles?.[0] !== source)
        throw new Error("제출 응답이 선택한 소스와 다릅니다.");
      setJob(value);
      const rerun = cancelRerunNotice(value);
      if (rerun) { setNotice(rerun); return; }
      if (value.status === "done") { setNotice("같은 호출의 저장된 결과를 다시 열었습니다(엔진을 다시 실행하지 않음)."); return; }
      if (value.status === "queued") { setJobBusy(false); await start(value.job_id); }
    } catch (e) { if (current(captured)) setJobError(`포켓 검출 제출 실패: ${errorText(e)}`); }
    finally { setJobBusy(false); }
  }

  async function approve() {
    if (!job) return;
    const captured = stamp(), jobId = job.job_id;
    setJobBusy(true);
    try {
      await api.approveOpenmm(runId);
      if (!current(captured)) return;
      setApprovalNeeded(false); setNotice("승인을 기록했습니다. 작업을 시작합니다."); setJobBusy(false);
      await start(jobId);
    } catch (e) { if (current(captured)) setJobError(`승인 실패: ${errorText(e)}`); }
    finally { setJobBusy(false); }
  }

  async function jobAction(kind: "cancel" | "retry") {
    if (!job) return;
    const captured = stamp(), jobId = job.job_id;
    setJobBusy(true); setJobError("");
    try {
      const value = kind === "cancel" ? (await api.cancelJob(runId, jobId)).job as unknown as PocketJob
        : await api.retryJob(runId, jobId) as unknown as PocketJob;
      if (current(captured) && value.run_id === runId && value.job_id === jobId) setJob(value);
    } catch (e) { if (current(captured)) setJobError(`포켓 작업 ${kind === "cancel" ? "취소" : "재시도"} 실패: ${errorText(e)}`); }
    finally { setJobBusy(false); }
  }

  async function selectPocket(rank: number) {
    if (!summary || p.blockedReason) return;
    const captured = stamp({ setHandle: summary.handle, rank });
    live.current = { ...live.current, rank };
    setSelectedRank(rank); setSelectionError(""); setGeometryBusy(true);
    try {
      const geometry = await api.pocketGeometry(runId, summary.handle, rank);
      if (!current(captured)) return;
      const problem = geometryError(geometry, { handle: summary.handle, rank, sourceHandle: summary.source_handle });
      if (problem) throw new Error(problem);
      const host = latest.current;
      if (host.run.run_id !== runId) return;
      if (summary.source_handle !== host.displayedSourceHandle) {
        if (!host.onShowSource) throw new Error("이 포켓 결과의 소스가 현재 표시된 구조와 다릅니다. 해당 구조를 표시한 뒤 다시 선택하세요.");
        host.onShowSource(runId, summary.source_handle, summary.source_kind);
      }
      const token = focusToken + 1;
      setFocusToken(token);
      host.onOverlay(overlayRequest(runId, geometry, { showSpheres, showLining, opacity, focusToken: token }));
    } catch (e) { if (current(captured)) setSelectionError(`포켓 기하 읽기 실패: ${errorText(e)}`); }
    finally { setGeometryBusy(false); }
  }

  function updateView(next: { showSpheres?: boolean; showLining?: boolean; opacity?: number; focus?: boolean }) {
    const spheres = next.showSpheres ?? showSpheres, lining = next.showLining ?? showLining;
    const alpha = clampOpacity(next.opacity ?? opacity), token = next.focus ? focusToken + 1 : focusToken;
    setShowSpheres(spheres); setShowLining(lining); setOpacity(alpha); setFocusToken(token);
    if (p.overlay) p.onOverlay({ ...p.overlay, showSpheres: spheres, showLining: lining, opacity: alpha, focusToken: token });
  }

  async function makeReport() {
    if (!summary) return;
    const captured = stamp(), handle = summary.handle;
    setReportBusy(true); setReportError("");
    try {
      const saved = savedSetReports.at(-1);
      const artifact = saved ? await api.pocketReport(runId, saved.handle) : await api.createPocketReport(runId, handle);
      if (!current(captured)) return;
      if (artifact.manifest.schema !== "method_report_manifest@1" || artifact.manifest.analysis_type !== "pocket_detection" ||
          artifact.manifest.result_handle !== handle) throw new Error("보고서가 선택한 포켓 결과와 다릅니다.");
      setReport({ setHandle: handle, artifact });
      if (!saved) { const refreshed = await api.reports(runId); if (current(captured)) setReports(refreshed); }
    } catch (e) { if (current(captured)) setReportError(`포켓 보고서 실패: ${errorText(e)}`); }
    finally { setReportBusy(false); }
  }

  const detectDisabledReason = p.blockedReason ?? (!capability ? "fpocket 능력 상태를 확인하는 중입니다."
    : !capability.available ? `사용할 수 없음: ${capability.reason ?? capabilityStatusText(capability.status)}`
      : !sourceHandle ? "검출할 소스가 없습니다. 먼저 구조를 전처리하세요."
        : !activePreflight ? "입력 확인 중입니다."
          : !activePreflight.ready ? `입력을 사용할 수 없습니다: ${activePreflight.reject?.message ?? capabilityStatusText(activePreflight.status)}`
            : jobBusy ? "작업 요청을 처리하는 중입니다."
              : job && ACTIVE_JOB.has(job.status) ? "진행 중인 포켓 작업이 있습니다." : null);
  const availableChains = activePreflight?.available_chains ?? [];
  const checkedChains = chainSelection ?? activePreflight?.selected_chains ?? [];

  return <section className="mw-pocket" aria-label={OVERLAY_LABEL} data-pocket-panel={p.panel} data-pocket-ui-state={uiState}>
    <div className="mw-pocket-head"><strong>{OVERLAY_LABEL}</strong>
      <span className="mw-badge" data-pocket-state={uiState}>{UI_STATE_TEXT[uiState]}</span></div>
    <p className="mw-muted">{LIMITATION_NOTE} {NONDETERMINISM_NOTE}</p>
    {p.blockedReason && <p role="status" className="mw-pocket-blocked">{p.blockedReason}</p>}
    {capability && !capability.available && <p role="status" className="mw-pocket-blocked" data-pocket-capability={capability.status}>
      fpocket 검출 사용할 수 없음 ({capabilityStatusText(capability.status)}): {capability.reason ?? "이유를 확인할 수 없습니다."}</p>}
    {capability?.available && <p className="mw-capability mw-mono">{capability.engine} {capability.release} · build {capability.build} · 제한 시간 {capability.limits.timeout_s ?? 120}s · parser {capability.parser_version}</p>}

    <div className="mw-pocket-group">
      <label>포켓 검출 소스<select className="mw-select" aria-label="포켓 검출 소스" value={sourceHandle}
        disabled={!!p.blockedReason || jobBusy} onChange={e => { setSourceHandle(e.target.value); setChainSelection(null); setNotice(""); }}>
        {!p.sourceOptions.length && <option value="">사용할 수 있는 소스 없음</option>}
        {p.sourceOptions.map(option => <option key={option.handle} value={option.handle}>
          {option.kind} · {shortHandle(option.handle)}{option.handle === p.displayedSourceHandle ? " · 표시 중" : ""}</option>)}
      </select></label>
      {sourceKind && <span className="mw-muted mw-mono">{sourceKind} · model {activePreflight?.model_number ?? "—"}</span>}
      {availableChains.length > 0 && <fieldset className="mw-pocket-chains"><legend>체인 선택 (기본: 단백질이 있는 모든 체인)</legend>
        {availableChains.map(({ chain_auth: chain, has_protein, protein_residues }) => <label key={chain}>
          <input type="checkbox" aria-label={`체인 ${chain}`}
          checked={checkedChains.includes(chain)} disabled={!!p.blockedReason || jobBusy}
          onChange={e => setChainSelection(previous => {
            const base = previous ?? activePreflight?.selected_chains ?? [];
            return e.target.checked ? [...new Set([...base, chain])].sort() : base.filter(item => item !== chain);
          })} /> 체인 {chain} <small className="mw-muted">{has_protein ? `단백질 잔기 ${protein_residues}` : "단백질 없음"}</small></label>)}
        {chainSelection !== null && <Button size="sm" onClick={() => setChainSelection(null)}>기본 체인으로</Button>}
      </fieldset>}
      {activePreflightError && <div role="alert" className="mw-table-error"><p>입력 확인 실패: {activePreflightError}</p>
        <Button size="sm" onClick={() => setPreflightRetry(value => value + 1)}>입력 다시 확인</Button></div>}
      {activePreflight && <div className="mw-pocket-preflight" aria-label="포켓 입력 확인">
        {activePreflight.ready ? <p className="mw-capability">선택 체인 {activePreflight.selected_chains.join(", ")} · 투영 중원자 {activePreflight.projected_atom_count}개 · 잔기 {activePreflight.projected_residue_count}개</p>
          : <p role="alert" className="mw-table-error" data-pocket-reject={activePreflight.reject?.reason_code ?? activePreflight.status}>
            입력 거부 ({activePreflight.reject?.reason_code ?? activePreflight.status}): {activePreflight.reject?.message ?? capabilityStatusText(activePreflight.status)}</p>}
        {activePreflight.excluded_counts && <p className="mw-muted">제외 원자: {Object.entries(activePreflight.excluded_counts)
          .map(([category, count]) => `${EXCLUDED_LABELS[category] ?? category} ${count}`).join(" · ")}</p>}
        {activePreflight.resname_mapping.length > 0 && <p className="mw-muted">히스티딘 이름 대응 {activePreflight.resname_mapping.length}개
          ({[...new Set(activePreflight.resname_mapping.map(item => item.original_resname))].join(", ")} → HIS, 결과 식별자는 원래 이름 유지)</p>}
        <p className="mw-muted">한도: 제한 시간 {activePreflight.timeout_s}s · 중원자 {activePreflight.limits.heavy_atoms} · 잔기 {activePreflight.limits.residues}
          · 원본 출력 보관 잔량 {mib(activePreflight.retention.remaining_bytes)} / {mib(activePreflight.retention.limit_bytes)}
          {activePreflight.budget?.expensive_calls && ` · 비싼 계산 ${activePreflight.budget.expensive_calls.used}/${activePreflight.budget.expensive_calls.limit}`}</p>
      </div>}
      <Button size="sm" variant="primary" disabled={!!detectDisabledReason} title={detectDisabledReason ?? undefined}
        onClick={() => void detect()}>포켓 검출 실행</Button>
      {detectDisabledReason && <span className="mw-muted" data-pocket-detect-reason>{detectDisabledReason}</span>}
    </div>

    {job && <div className="mw-pocket-group" aria-label="포켓 작업">
      <p className="mw-capability mw-mono" data-pocket-job-status={job.status}>작업 {job.status} · 시도 {job.attempt_ordinal} · {job.job_id}</p>
      {job.blocked_reason && <p role="status" className="mw-muted">시작 대기 이유: {job.blocked_reason}</p>}
      {job.failure && <p role="alert" className="mw-table-error">{job.failure.error}{job.failure.reason_code ? ` (${job.failure.reason_code})` : ""}: {job.failure.message}</p>}
      <div className="mw-chemical-inline">
        {["queued", "claimed"].includes(job.status) && !approvalNeeded &&
          <Button size="sm" disabled={jobBusy} onClick={() => void start(job.job_id)}>포켓 작업 시작</Button>}
        {approvalNeeded && <Button size="sm" disabled={jobBusy} onClick={() => void approve()}>포켓 계산 승인 후 시작</Button>}
        {ACTIVE_JOB.has(job.status) && <Button size="sm" disabled={job.cancel_requested} onClick={() => void jobAction("cancel")}>포켓 작업 취소</Button>}
        {["failed", "interrupted"].includes(job.status) && job.attempt_ordinal < 4 &&
          <Button size="sm" disabled={jobBusy} onClick={() => void jobAction("retry")}>실패한 포켓 작업 재시도</Button>}
      </div>
    </div>}
    {notice && <p role="status" className="mw-pocket-notice" data-pocket-notice>{notice}</p>}
    {jobError && <p role="alert" className="mw-table-error">{jobError}</p>}

    {(summary || summaryPending || summaryError) && <div className="mw-pocket-group" aria-label="포켓 결과">
      {summaryPending && <p role="status" className="mw-muted">포켓 결과를 읽는 중…</p>}
      {summaryError && <div role="alert" className="mw-table-error"><p>{summaryError}</p>
        <Button size="sm" onClick={() => void openSet(setHandle)}>포켓 결과 다시 읽기</Button></div>}
      {summary && <>
        <p className="mw-capability mw-mono">결과 {shortHandle(summary.handle)} · 소스 {summary.source_kind} {shortHandle(summary.source_handle)} · model {summary.model_number}
          · 체인 {summary.selected_chains.join(", ")} · 완전성 {summary.completeness}</p>
        {summary.null_result ? <p role="status" data-pocket-null-result>fpocket이 정상 종료했고 후보 공동이 없습니다 (scientific_null, 전체 0개). 실패가 아닙니다.</p> : <>
          <div className="mw-pocket-list-head" aria-label="포켓 개수">
            <span data-pocket-displayed-count={display!.displayed_count}>표시 {display!.displayed_count}개</span>
            <span data-pocket-total-count={display!.total_count}>전체 {display!.total_count}개</span>
            <label>top-k <input className="mw-number" type="number" min={1} max={Math.min(MAX_TOP_K, summary.total_count)}
              aria-label="표시할 포켓 수 (top-k)" value={clampTopK(topK, summary.total_count)}
              onChange={e => setTopK(clampTopK(Number(e.target.value), summary.total_count))} /></label>
          </div>
          <p className="mw-muted">표시 개수 제한은 화면 설정이며 엔진 결과는 전체 {display!.total_count}개로 완전합니다.</p>
          <p className="mw-pocket-warning" role="note">{DRUGGABILITY_WARNING}</p>
          <p className="mw-muted">{RELATIVE_SCORE_NOTE}</p>
          <div className="mw-table-scroll" role="region" aria-label="fpocket 후보 공동 목록" tabIndex={0}>
            <table className="mw-table"><thead><tr><th>rank</th>{DESCRIPTOR_KEYS.map(key => <th key={key}>{DESCRIPTOR_LABELS[key]}</th>)}<th>주변 잔기</th><th>표시</th></tr></thead>
              <tbody>{display!.rows.map(row => <tr key={row.rank} aria-selected={row.rank === selectedRank} data-pocket-rank={row.rank}>
                <td>{row.rank}</td>
                {DESCRIPTOR_KEYS.map(key => <td key={key} className="mw-mono">{descriptorText(row.descriptors[key])}
                  {key === "druggability_score" && <small className="mw-pocket-warning-inline"> 약물성 증거 아님</small>}</td>)}
                <td>{row.lining_residue_count}</td>
                <td><Button size="sm" aria-label={`포켓 rank ${row.rank} 선택`} disabled={!!p.blockedReason || geometryBusy}
                  onClick={() => void selectPocket(row.rank)}>{row.rank === selectedRank ? "다시 선택" : "선택"}</Button></td>
              </tr>)}</tbody></table>
          </div>
        </>}
        <details><summary>방법·한계</summary>
          <p className="mw-mono">{String(summary.method.engine)} {String(summary.method.release)} · build {String(summary.method.build)} · seed {String(summary.method.seed_control)}
            · 새 실행 결정적 {String(summary.method.fresh_execution_deterministic)}</p>
          {summary.limitations.map((item, i) => <p key={i} className="mw-muted">{item}</p>)}
        </details>
      </>}
    </div>}
    {selectionError && <p role="alert" className="mw-table-error">{selectionError}</p>}

    <div className="mw-pocket-group" aria-label="포켓 오버레이">
      <div className="mw-chemical-inline">
        <label><input type="checkbox" checked={showSpheres} onChange={e => updateView({ showSpheres: e.target.checked })} /> 알파 구 표시</label>
        <label><input type="checkbox" checked={showLining} onChange={e => updateView({ showLining: e.target.checked })} /> 주변 잔기 표시</label>
        <label>불투명도 <input type="range" aria-label="알파 구 불투명도" min={0.1} max={1} step={0.05} value={opacity}
          onChange={e => updateView({ opacity: Number(e.target.value) })} /> <span className="mw-mono">{opacity.toFixed(2)}</span></label>
      </div>
      <div className="mw-chemical-inline">
        <Button size="sm" disabled={!overlayOn} onClick={() => updateView({ focus: true })}>포켓 초점</Button>
        <Button size="sm" disabled={!overlayOn} onClick={() => { setSelectedRank(null); p.onOverlay(null); }}>오버레이 지우기</Button>
        <Button size="sm" disabled={!overlayOn} onClick={() => { setSelectedRank(null); p.onReturnToSource(); }}>원래 소스로 돌아가기</Button>
      </div>
      {p.overlay && <p role="status" className="mw-muted" data-pocket-overlay-status={applied ? "applied" : p.overlayError ? "error" : "pending"}>
        {applied ? `${OVERLAY_LABEL} rank ${applied.rank} 표시 확인 · 알파 구 ${applied.sphereCount}개 · 주변 원자 ${applied.liningAtomCount}개 (Mol* 읽기 확인, 선택 불가)`
          : p.overlayError ? `오버레이 표시 실패: ${p.overlayError}`
            : p.overlay.sourceHandle !== p.displayedSourceHandle || !p.viewerReady ? "포켓 소스를 표시하는 중…" : "Mol*에 오버레이를 적용하는 중…"}</p>}
      {p.overlayNotice && <p role="status" className="mw-pocket-notice" data-pocket-overlay-notice>{p.overlayNotice}</p>}
    </div>

    {summary && <div className="mw-pocket-group" aria-label="포켓 보고서">
      <Button size="sm" disabled={reportBusy} onClick={() => void makeReport()}>{savedSetReports.length ? "저장된 포켓 보고서 열기" : "포켓 보고서 만들기"}</Button>
      {reportError && <p role="alert" className="mw-table-error">{reportError}</p>}
      {shownReport && <><p className="mw-capability">저장된 포켓 보고서 · 증거 이벤트 #{shownReport.manifest.snapshot?.event_seq}</p>
        <div className="mw-report-downloads">
          <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, shownReport.handle, "markdown")}>포켓 보고서 Markdown 다운로드</a>
          <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, shownReport.handle, "json")}>포켓 보고서 JSON 다운로드</a>
        </div></>}
    </div>}

    <details className="mw-pocket-group" aria-label="포켓 기록">
      <summary>기록에서 다시 열기 ({sets.length})</summary>
      {setsError && <p role="alert" className="mw-table-error">{setsError}</p>}
      <Button size="sm" onClick={refreshSets}>포켓 기록 다시 읽기</Button>
      {sets.map(row => { const decision = reopenDecision(p.panel, row.source_kind);
        return <div key={row.handle} className="mw-pocket-history" data-pocket-history={row.handle}>
          <span className="mw-mono">{row.source_kind ?? "—"} · {shortHandle(row.source_handle ?? "")} · 체인 {(row.selected_chains ?? []).join(", ")}
            · {row.null_result ? "빈 결과 (scientific_null)" : `전체 ${row.total_count}개`}</span>
          <Button size="sm" aria-label={`포켓 결과 다시 열기 ${shortHandle(row.handle)}`} disabled={!decision.allowed || !!p.blockedReason}
            title={decision.reason ?? undefined} onClick={() => void openSet(row.handle)}>다시 열기</Button>
          {decision.reason && <small className="mw-muted">{decision.reason}</small>}
        </div>; })}
    </details>
  </section>;
}
