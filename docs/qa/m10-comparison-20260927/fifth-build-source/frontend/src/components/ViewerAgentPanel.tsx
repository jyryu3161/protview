"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import type { ResidueRef } from "@/lib/contracts";
import { desiredSceneSelection, restoreCatalogScope } from "@/lib/saved-scene";
import { api, ApiError, type ResidueList } from "@/lib/api";
import type { ViewerIntent, ViewerOnlineStatus, ViewerSession, ViewerRepresentationValue } from "@/lib/viewer-agent";
import { commandTargetsCurrentScene, viewerPromptAllowed, withViewerSceneUpdate } from "@/lib/viewer-scene";
import type { ViewerBinding, ViewerBridge, ViewerRepresentation } from "./MolstarViewer";

function backendRepresentation(value: ViewerRepresentation): ViewerRepresentationValue {
  return value === "ball-and-stick" ? "ball_and_stick" : value;
}
function localRepresentation(value: ViewerRepresentationValue): ViewerRepresentation {
  return value === "ball_and_stick" ? "ball-and-stick" : value;
}
function sameRef(a: ResidueRef, b: ResidueRef): boolean {
  return a.model_number === b.model_number && a.chain_auth === b.chain_auth &&
    a.seq_auth === b.seq_auth && (a.icode ?? "") === (b.icode ?? "") && a.resname === b.resname &&
    (a.chain_label == null || a.chain_label === b.chain_label) &&
    (a.seq_label == null || a.seq_label === b.seq_label);
}
type PendingIntent = { id: string; runId: string; controller: AbortController; session: ViewerSession;
  stopped: boolean; stopInProgress: boolean; expectedRevision: number;
  nativeAxes: Set<"representation" | "selection" | "camera">;
  applyTask: Promise<{ status: "applied" | "no_change" | "failed"; reasonCode: string | null }> | null };
function binding(session: ViewerSession): ViewerBinding {
  return { sessionId: session.viewer_session_id, clientId: session.client_instance_id,
    generation: session.scene_generation, sourceHandle: session.structure_handle,
    catalogHash: session.catalog_hash, actionRevision: session.action_revision };
}
function explanation(intent: ViewerIntent | null): string {
  if (!intent) return "명령을 입력하세요.";
  if (intent.status === "interpreting") return "모델이 뷰어 요청을 해석하는 중입니다.";
  if (intent.status === "planned" || intent.status === "applying") return "실제 뷰어에 명령을 적용하고 확인하는 중입니다.";
  if (intent.status === "applied") return "실제 뷰어에 적용하고 확인했습니다.";
  if (intent.status === "partial") return "일부 명령만 적용됐습니다. 아래 결과를 확인하세요.";
  if (intent.status === "no_change") return "변경할 뷰어 상태가 없습니다.";
  if (intent.status === "clarification") return "대상이나 동작을 더 구체적으로 적어주세요.";
  if (intent.status === "unsupported") return "이 요청은 지원하는 뷰어 명령 밖입니다.";
  if (intent.status === "cancelled") return "요청이 취소되었습니다. 전송된 요청의 비용은 남을 수 있습니다.";
  if (intent.status === "detached") return "현재 장면과 다른 이전 요청입니다. 다시 보내야 합니다.";
  return `요청을 완료하지 못했습니다${intent.reason_code ? ` (${intent.reason_code})` : ""}.`;
}

export interface ViewerAgentPanelProps {
  runId: string | null;
  clientId: string;
  sceneGeneration: number;
  sourceHandle: string | null;
  viewerReady: boolean;
  bridgeRef: MutableRefObject<ViewerBridge | null>;
  representation: ViewerRepresentation;
  selected: ResidueRef | null;
  residues: ResidueList | null;
  dryRun: boolean;
  onRepresentation: (value: ViewerRepresentation) => void;
  onSelection: (value: ResidueRef | null) => void;
  onMode: (enabled: boolean) => void;
  onBudgetRefresh: () => void;
  onScopeChange: () => void;
  registerInvalidator: (invalidate: (() => void) | null) => void;
  restoreTarget?: ResidueRef | null;
  restorePending?: boolean;
  onManualSceneAction?: () => void;
  onSession?: (session: ViewerSession | null) => void;
  onSessionError?: (message: string) => void;
  registerSceneController?: (controller: SceneController | null) => void;
}

export interface SceneController {
  settledSession(): Promise<ViewerSession | null>;
  detach(): Promise<void>;
}

export function ViewerAgentPanel(p: ViewerAgentPanelProps) {
  const [session, setSession] = useState<ViewerSession | null>(null);
  const sessionRef = useRef<ViewerSession | null>(null);
  const [online, setOnline] = useState<ViewerOnlineStatus | null>(null);
  const [scope, setScope] = useState("");
  const [scopeTarget, setScopeTarget] = useState("");
  const [scopeTouched, setScopeTouched] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [intent, setIntent] = useState<ViewerIntent | null>(null);
  const [history, setHistory] = useState<ViewerIntent[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pendingRef = useRef<PendingIntent | null>(null);
  const activeRunIdRef = useRef(p.runId);
  activeRunIdRef.current = p.runId;
  const sceneMutationRef = useRef<{ key: string; tail: Promise<void> }>({ key: "", tail: Promise.resolve() });
  const nativeSyncRef = useRef<{ intentId: string; representation: ViewerRepresentationValue; selectedAlias: string | null } | null>(null);
  const submittingRef = useRef(false);
  const preparingRef = useRef<{ stopped: boolean } | null>(null);
  const mountedRef = useRef(true);
  const onlineMutationRef = useRef(0);
  const ledgerReadRef = useRef(0);
  const chains = useMemo(() => [...new Set(p.residues?.residues.map(item => item.chain_auth) ?? [])], [p.residues]);
  const restoredScope = restoreCatalogScope(p.residues?.residues ?? null, p.restoreTarget ?? null);
  const shownScopeTarget = !scopeTouched && restoredScope.kind === "exact" ? restoredScope.index : scopeTarget;

  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false;
    if (preparingRef.current) preparingRef.current.stopped = true;
    if (pendingRef.current) { pendingRef.current.stopped = true; pendingRef.current.controller.abort(); }
    onlineMutationRef.current++; ledgerReadRef.current++; p.bridgeRef.current?.bind(null); }; }, [p.bridgeRef]);
  useEffect(() => {
    if (!p.runId) { setOnline(null); setHistory([]); return; }
    let active = true;
    void Promise.all([api.viewerOnline(p.runId), api.viewerIntents(p.runId)]).then(([mode, previous]) => {
      if (active) { setOnline(mode); setHistory(previous); }
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : "연결 오류"); });
    return () => { active = false; };
  }, [p.runId]);
  useEffect(() => {
    nativeSyncRef.current = null;
    sessionRef.current = null; setSession(null); setIntent(null); p.bridgeRef.current?.bind(null); p.onSession?.(null);
    if (!p.runId || !p.sourceHandle || !p.viewerReady || !p.bridgeRef.current || p.sceneGeneration < 1) return;
    if (!scopeTouched && restoredScope.kind === "missing") {
      const message = "저장된 대상이 구조의 정확한 잔기 목록에 없습니다.";
      setError(message); p.onSessionError?.(message); return;
    }
    const id = p.runId, handle = p.sourceHandle;
    let active = true;
    void api.viewerSession(id, { client_instance_id: p.clientId, scene_generation: p.sceneGeneration,
      structure_handle: handle, representation: backendRepresentation(p.representation),
      ...(!scopeTouched && restoredScope.kind === "exact" && p.restoreTarget ? { scope_target: p.restoreTarget } :
        { ...(scope ? { scope_chain_auth: scope } : {}),
          ...(scopeTarget && p.residues ? { scope_target: p.residues.residues[Number(scopeTarget) - 1] } : {}) }),
      ...(p.restorePending && p.restoreTarget ? { selected_target: p.restoreTarget } : {}) }).then(value => {
      if (!active || p.bridgeRef.current?.snapshot().sourceHandle !== handle) return;
      sessionRef.current = value; setSession(value); p.bridgeRef.current?.bind(binding(value)); p.onSession?.(value); setError("");
    }).catch(e => {
      if (active) {
        const message = e instanceof ApiError && e.code === "scope_required"
          ? "대상이 256개를 넘어 체인 범위를 먼저 선택해야 합니다." : e instanceof Error ? e.message : "장면을 만들 수 없습니다.";
        setError(message); p.onSessionError?.(message);
      }
    });
    return () => { active = false; p.bridgeRef.current?.bind(null); p.onSession?.(null); };
  // The exact scene identity and local scope own session creation. Representation
  // changes are synchronized separately so they do not create a new session.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.runId, p.sourceHandle, p.viewerReady, p.sceneGeneration, p.clientId, scope, scopeTarget, scopeTouched, p.restoreTarget]);

  const invalidate = useCallback(async (representation?: ViewerRepresentationValue, selectedAlias?: string | null) => {
    const current = sessionRef.current;
    if (!current || !p.runId) return null;
    const runId = p.runId;
    const next = withViewerSceneUpdate(current, {
      representation: representation ?? current.representation,
      selected_alias: selectedAlias === undefined ? current.selected_alias : selectedAlias,
      action_revision: current.action_revision + 1 });
    // Invalidate the browser bridge before the network round trip so a delayed
    // plan cannot touch Mol* while the short server transition is pending.
    p.bridgeRef.current?.bind(binding(next));
    sessionRef.current = next; setSession(next);
    const sceneKey = [runId, current.client_instance_id, current.viewer_session_id,
      current.scene_generation, current.structure_handle].join("|");
    if (sceneMutationRef.current.key !== sceneKey)
      sceneMutationRef.current = { key: sceneKey, tail: Promise.resolve() };
    const queue = sceneMutationRef.current;
    const sameScene = (candidate: ViewerSession | null) => mountedRef.current &&
      activeRunIdRef.current === runId && candidate?.client_instance_id === current.client_instance_id &&
      candidate.viewer_session_id === current.viewer_session_id &&
      candidate.scene_generation === current.scene_generation &&
      candidate.structure_handle === current.structure_handle;
    // Keep the immediate local revision above, but serialize only the server
    // writes. A later local action can supersede a queued older revision.
    const task: Promise<ViewerSession | null> = queue.tail.then(async () => {
      if (!sameScene(sessionRef.current) || sessionRef.current!.action_revision > next.action_revision) return null;
      try {
        return await api.viewerSessionState(runId, current.viewer_session_id, {
          representation: next.representation, selected_alias: next.selected_alias,
          action_revision: next.action_revision,
        });
      } catch (error) {
        if (!sameScene(sessionRef.current) || sessionRef.current!.action_revision > next.action_revision) return null;
        throw error;
      }
    });
    queue.tail = task.then(() => undefined, () => undefined);
    const saved = await task;
    if (!saved) return null;
    const merged = { ...next, ...saved, projection: next.projection };
    if (sameScene(sessionRef.current) && sessionRef.current!.action_revision === next.action_revision) {
      sessionRef.current = merged; setSession(merged); p.bridgeRef.current?.bind(binding(merged)); p.onSession?.(merged);
      return merged;
    }
    return null;
  }, [p.runId, p.bridgeRef]);

  const refreshLedger = useCallback(async () => {
    const id = p.runId;
    if (!id || !mountedRef.current) return;
    const read = ++ledgerReadRef.current;
    try {
      const mode = await api.viewerOnline(id);
      if (mountedRef.current && ledgerReadRef.current === read) {
        setOnline(mode);
        p.onBudgetRefresh();
      }
    } catch { /* A later explicit action or run reopen can retry this read. */ }
  }, [p.runId, p.onBudgetRefresh]);

  const reconcileNativeState = useCallback(async (pending: PendingIntent) => {
    if (pending.nativeAxes.size === 0) return;
    const current = sessionRef.current;
    const snapshot = p.bridgeRef.current?.snapshot();
    if (!mountedRef.current || pendingRef.current !== pending ||
        p.runId !== pending.runId || p.clientId !== pending.session.client_instance_id ||
        !current || current.viewer_session_id !== pending.session.viewer_session_id ||
        current.scene_generation !== pending.session.scene_generation ||
        current.structure_handle !== pending.session.structure_handle ||
        current.action_revision !== pending.expectedRevision ||
        !snapshot?.ready || snapshot.sessionId !== current.viewer_session_id ||
        snapshot.generation !== current.scene_generation || snapshot.sourceHandle !== current.structure_handle ||
        !snapshot.representation) return;
    const observedAlias = snapshot.selection
      ? current.targets.find(item => sameRef(item.residue, snapshot.selection!))?.alias ?? null : null;
    if (pending.nativeAxes.has("selection") && snapshot.selection && !observedAlias) {
      setError("실제 뷰어 선택을 현재 대상 목록과 일치시킬 수 없습니다.");
      return;
    }
    const representation = pending.nativeAxes.has("representation")
      ? backendRepresentation(snapshot.representation) : current.representation;
    const selectedAlias = pending.nativeAxes.has("selection") ? observedAlias : current.selected_alias;
    const target = { intentId: pending.id, representation, selectedAlias };
    if (representation !== current.representation || selectedAlias !== current.selected_alias) {
      // invalidate publishes the next session optimistically. Until parent
      // controls catch up with the observed native state, the normal prop-sync
      // effect must not write the old controls back into that session.
      nativeSyncRef.current = target;
      let updated: ViewerSession | null;
      try { updated = await invalidate(representation, selectedAlias); }
      catch (error) {
        if (nativeSyncRef.current?.intentId === pending.id) nativeSyncRef.current = null;
        throw error;
      }
      if (!updated || !mountedRef.current || pendingRef.current !== pending ||
          sessionRef.current?.viewer_session_id !== updated.viewer_session_id ||
          sessionRef.current.action_revision !== updated.action_revision) {
        if (nativeSyncRef.current?.intentId === pending.id) nativeSyncRef.current = null;
        return;
      }
      pending.expectedRevision = updated.action_revision;
    }
    if (mountedRef.current && pendingRef.current === pending &&
        sessionRef.current?.action_revision === pending.expectedRevision) {
      if (pending.nativeAxes.has("representation")) p.onRepresentation(snapshot.representation);
      if (pending.nativeAxes.has("selection")) p.onSelection(snapshot.selection);
    }
  }, [p, invalidate]);

  useEffect(() => {
    p.registerInvalidator(() => { nativeSyncRef.current = null;
      void invalidate().catch(e => setError(e instanceof Error ? e.message : "장면 동기화 실패")); });
    return () => p.registerInvalidator(null);
  }, [invalidate, p.registerInvalidator]);
  useEffect(() => {
    const current = sessionRef.current;
    if (!current) return;
    // The fresh session is seeded with the saved target before native restore.
    // Ignore the still-empty page selection only for that pending transaction.
    const selected = desiredSceneSelection(!!p.restorePending, p.restoreTarget ?? null, p.selected);
    const selectedAlias = selected ? current.targets.find(item => sameRef(item.residue, selected))?.alias ?? null : null;
    const rep = backendRepresentation(p.representation);
    const nativeSync = nativeSyncRef.current;
    if (nativeSync) {
      if (rep !== nativeSync.representation || selectedAlias !== nativeSync.selectedAlias) return;
      nativeSyncRef.current = null;
    }
    if (current.representation !== rep || current.selected_alias !== selectedAlias) {
      void invalidate(rep, selectedAlias).catch(e => setError(e instanceof Error ? e.message : "장면 동기화 실패"));
    }
  }, [p.representation, p.selected, p.restorePending, p.restoreTarget, session, invalidate]);

  const stop = useCallback(async () => {
    const pending = pendingRef.current;
    if (!pending) {
      if (preparingRef.current) {
        preparingRef.current.stopped = true;
        setBusy(false);
        setError("요청이 취소되었습니다. 로컬 명령은 적용되지 않았습니다.");
      }
      return;
    }
    if (!p.runId) return;
    pending.stopInProgress = true;
    pending.stopped = true;
    pending.controller.abort();
    setBusy(false);
    try {
      const cancelled = await api.viewerIntentCancel(p.runId, pending.id, {
        client_instance_id: pending.session.client_instance_id,
        viewer_session_id: pending.session.viewer_session_id,
        scene_generation: pending.session.scene_generation });
      if (mountedRef.current) setIntent(previous => previous?.intent_id === cancelled.intent_id ?
        { ...previous, status: "cancelled" } : previous);
    } catch (e) { if (mountedRef.current) setError(e instanceof Error ? e.message : "취소 요청 실패"); }
    finally {
      if (pending.applyTask) await pending.applyTask.catch(() => undefined);
      try { await reconcileNativeState(pending); }
      catch (e) { if (mountedRef.current) setError(e instanceof Error ? e.message : "뷰어 상태 동기화 실패"); }
      pending.stopInProgress = false;
      if (pendingRef.current === pending) pendingRef.current = null;
      void refreshLedger(); }
  }, [p.runId, reconcileNativeState, refreshLedger]);

  useEffect(() => {
    p.registerSceneController?.({
      settledSession: async () => {
        const queue = sceneMutationRef.current;
        await queue.tail;
        const current = sessionRef.current;
        if (pendingRef.current || preparingRef.current || busy || !current ||
            current.viewer_session_id !== p.bridgeRef.current?.snapshot().sessionId) return null;
        return current;
      },
      detach: async () => {
        const bridge = p.bridgeRef.current;
        const previous = sessionRef.current;
        bridge?.invalidate();
        if (pendingRef.current || preparingRef.current) await stop();
        if (!mountedRef.current || p.bridgeRef.current !== bridge || sessionRef.current !== previous) return;
        sessionRef.current = null; setSession(null); p.onSession?.(null);
      },
    });
    return () => p.registerSceneController?.(null);
  }, [p.registerSceneController, p.bridgeRef, p.onSession, busy, stop]);

  const changeScope = (chain: string, target: string) => {
    p.onManualSceneAction?.();
    if (pendingRef.current) void stop();
    p.bridgeRef.current?.bind(null);
    setScopeTouched(true); setScope(chain); setScopeTarget(target); p.onScopeChange();
  };

  const submit = useCallback(async (value: string, local = false) => {
    const current = sessionRef.current;
    if (!p.runId || !current || !p.bridgeRef.current?.snapshot().catalogReady || busy || submittingRef.current ||
        !viewerPromptAllowed(value, online?.enabled ?? false, p.dryRun)) return;
    p.onManualSceneAction?.();
    submittingRef.current = true;
    const preparation = { stopped: false };
    preparingRef.current = preparation;
    setBusy(true); setError("");
    let pending: PendingIntent | null = null;
    try {
      if (local || value.trim().startsWith("/")) {
        if (pendingRef.current) await stop();
        await invalidate();
      }
      if (preparation.stopped || !mountedRef.current ||
          sessionRef.current?.viewer_session_id !== current.viewer_session_id ||
          !p.bridgeRef.current?.snapshot().catalogReady) return;
      const scene = sessionRef.current;
      const requestId = crypto.randomUUID(), controller = new AbortController();
      pending = { id: requestId, runId: p.runId, controller, session: scene, stopped: false,
        stopInProgress: false, expectedRevision: scene.action_revision, nativeAxes: new Set(), applyTask: null };
      pendingRef.current = pending;
      if (preparingRef.current === preparation) preparingRef.current = null;
      setIntent({ intent_id: requestId, status: "interpreting", source: value.trim().startsWith("/") ? "local_command" : "jev",
        viewer_session_id: scene.viewer_session_id, scene_generation: scene.scene_generation,
        structure_handle: scene.structure_handle, catalog_hash: scene.catalog_hash,
        prompt_sha256: "", projection_sha256: null, question_version: null, requested_model: null,
        served_model: null, audit_id: null, reason_code: null, commands: [], acks: [] });
      let result = await api.viewerIntent(p.runId, { client_instance_id: scene.client_instance_id,
        viewer_session_id: scene.viewer_session_id, scene_generation: scene.scene_generation,
        request_id: requestId, prompt: value }, controller.signal);
      if (pending.stopped || pendingRef.current !== pending) return;
      setIntent(result);
      let appliedRepresentation: ViewerRepresentation | null = null;
      let appliedSelection: ResidueRef | null | undefined;
      for (const command of result.commands) {
        if (pending.stopped || pendingRef.current !== pending) break;
        const bridge = p.bridgeRef.current;
        const observed = bridge?.snapshot();
        const canApply = observed && sessionRef.current &&
          commandTargetsCurrentScene(command, sessionRef.current, observed);
        if (canApply) pending.nativeAxes.add(command.axis);
        const task = canApply ? bridge!.apply(command) : null;
        pending.applyTask = task;
        const outcome = task ? await task : { status: "failed" as const, reasonCode: "stale_or_not_ready" };
        pending.applyTask = null;
        if (pending.stopped || pendingRef.current !== pending) {
          if (pending.stopped && !pending.stopInProgress) await reconcileNativeState(pending);
          break;
        }
        result = await api.viewerAck(p.runId, result.intent_id, {
          command_id: command.command_id, status: outcome.status, reason_code: outcome.reasonCode,
          client_instance_id: scene.client_instance_id, viewer_session_id: scene.viewer_session_id,
          scene_generation: scene.scene_generation, action_revision: command.action_revision });
        if (!mountedRef.current || pending.stopped || pendingRef.current !== pending) break;
        setIntent(result);
        if (outcome.status === "applied") {
          if (command.axis === "representation") appliedRepresentation = localRepresentation(command.value as ViewerRepresentationValue);
          if (command.axis === "selection") appliedSelection = command.value === "clear" ? null : command.target;
        }
      }
      if (mountedRef.current && !pending.stopped && pendingRef.current === pending &&
          sessionRef.current?.viewer_session_id === scene.viewer_session_id &&
          sessionRef.current.scene_generation === scene.scene_generation) {
        if (appliedRepresentation) p.onRepresentation(appliedRepresentation);
        if (appliedSelection !== undefined) p.onSelection(appliedSelection);
        setHistory(previous => [result, ...previous.filter(item => item.intent_id !== result.intent_id)]);
      }
    } catch (e) {
      if (!preparation.stopped && !pending?.stopped && mountedRef.current)
        setError(e instanceof Error ? e.message : "요청 실패");
      if (pending && !pending.stopped && pendingRef.current === pending) {
        try { await reconcileNativeState(pending); }
        catch (syncError) { if (mountedRef.current)
          setError(`요청 실패 후 뷰어 상태 동기화 실패: ${syncError instanceof Error ? syncError.message : "알 수 없는 오류"}`); }
      }
    } finally {
      if (preparingRef.current === preparation) preparingRef.current = null;
      if (pending && pendingRef.current === pending && !pending.stopInProgress) pendingRef.current = null;
      submittingRef.current = false;
      if (mountedRef.current) { setBusy(false); void refreshLedger(); }
    }
  }, [p, busy, online?.enabled, stop, invalidate, refreshLedger, reconcileNativeState]);

  const changeOnline = async (enabled: boolean) => {
    if (!p.runId) return;
    const runId = p.runId;
    const mutation = ++onlineMutationRef.current;
    if (!enabled && pendingRef.current) await stop();
    try {
      const mode = await api.setViewerOnline(runId, enabled);
      if (!mountedRef.current || onlineMutationRef.current !== mutation) return;
      setOnline(mode); p.onMode(mode.enabled); setError("");
    } catch (e) { if (mountedRef.current && onlineMutationRef.current === mutation)
      setError(e instanceof Error ? e.message : "모드 변경 실패"); }
  };
  const catalogReady = p.bridgeRef.current?.snapshot().catalogReady === true;
  const canSend = !!session && p.viewerReady && catalogReady && !busy &&
    !!p.bridgeRef.current?.snapshot().ready;
  const promptAllowed = viewerPromptAllowed(prompt, online?.enabled ?? false, p.dryRun);
  return <section className="mw-agent-panel" aria-label="뷰어 요청">
    <div className="mw-agent-row"><strong>뷰어 요청</strong>
      <span className="mw-badge">{p.dryRun ? "dry-run" : online?.mode ?? "local_only"}</span>
      {online && <span className="mw-muted">온라인 요청 {online.used}/{online.request_cap}</span>}
      {!p.dryRun && <label className="mw-agent-mode"><input type="checkbox" checked={online?.enabled ?? false}
        onChange={event => void changeOnline(event.target.checked)} /> 온라인 해석 허용</label>}
      {busy && <button type="button" className="mw-btn mw-btn--sm" onClick={() => { p.onManualSceneAction?.(); void stop(); }}>요청 중단</button>}
    </div>
    <div className="mw-agent-row">
      <label className="mw-agent-prompt-label" htmlFor="viewer-prompt">요청</label>
      <input id="viewer-prompt" className="mw-agent-prompt" value={prompt} maxLength={512}
        placeholder={online?.enabled ? "예: 리간드에 초점을 맞추고 표면으로 보기" : "예: /representation surface, /focus t0001, /zoom in"}
        onChange={event => setPrompt(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.nativeEvent.isComposing) void submit(prompt); }} />
      <button type="button" className="mw-btn mw-btn--sm" disabled={!canSend || !promptAllowed}
        onClick={() => void submit(prompt)}>실행</button>
    </div>
    <div className="mw-agent-row">
      <label>체인 범위 <select className="mw-select" aria-label="뷰어 대상 체인 범위" value={scope}
        onChange={event => changeScope(event.target.value, "")} disabled={!p.residues || busy}>
        <option value="">전체</option>{chains.map(chain => <option key={chain} value={chain}>{chain || "(빈 체인)"}</option>)}
      </select></label>
      <label>정확한 대상 범위 <select className="mw-select" aria-label="뷰어 정확한 대상 범위" value={shownScopeTarget}
        onChange={event => changeScope("", event.target.value)} disabled={!p.residues || busy}>
        <option value="">전체</option>{p.residues?.residues.map((item, index) => <option key={`${index}-${item.chain_auth}-${item.seq_auth}`} value={index + 1}>
          {item.resname} · model {item.model_number} · auth {item.chain_auth}/{item.seq_auth}{item.icode || ""} · label {item.chain_label ?? "—"}/{item.seq_label ?? "—"}
        </option>)}</select></label>
      <label>대상 <select className="mw-select" aria-label="뷰어 대상 선택" value="" disabled={!session || !catalogReady || busy}
        onChange={event => { if (event.target.value) void submit(`/focus ${event.target.value}`, true); }}>
        <option value="">선택</option>{session?.targets.map(item => <option key={item.alias} value={item.alias}>
          {item.alias} · {item.residue.resname} {item.residue.chain_auth}/{item.residue.seq_auth}{item.residue.icode}
        </option>)}</select></label>
      <button type="button" className="mw-btn mw-btn--sm" disabled={!canSend} onClick={() => void submit("/zoom in", true)}>확대</button>
      <button type="button" className="mw-btn mw-btn--sm" disabled={!canSend} onClick={() => void submit("/zoom out", true)}>축소</button>
      <button type="button" className="mw-btn mw-btn--sm" disabled={!canSend} onClick={() => void submit("/reset", true)}>시점 초기화</button>
      <button type="button" className="mw-btn mw-btn--sm" disabled={!canSend} onClick={() => void submit("/clear", true)}>선택 해제</button>
    </div>
    <div className="mw-agent-row mw-agent-status" role="status">{error || explanation(intent)}
      {p.viewerReady && !catalogReady && <span className="mw-muted">원자 목록을 검증하는 중입니다. 실패하면 구조의 원자 목록 다시 읽기를 사용하세요.</span>}
      {session && !session.scope_complete && session.targets.length === 0 && <span className="mw-muted">대상 목록이 큰 구조입니다. 표현·시점 명령은 가능하며 초점에는 체인 또는 정확한 대상 범위가 필요합니다.</span>}
      {intent?.served_model && <span className="mw-muted">{intent.served_model}</span>}
      {intent?.commands.length ? <span className="mw-muted">{intent.acks.length}/{intent.commands.length} 명령 확인</span> : null}
    </div>
    <details className="mw-agent-details"><summary>전송 내용 · 요청 기록</summary>
      <p>온라인 해석 시 입력한 문장과 아래의 제한된 대상 식별자를 OpenRouter로 보냅니다. 좌표·구조 파일·서열·경로는 보내지 않습니다. 문장에 민감한 내용을 직접 입력하지 마세요.</p>
      <pre aria-label="전송 상태 미리보기">{JSON.stringify(session ? { ...session.projection, prompt } : { unavailable: "현재 장면의 대상 목록이 준비되지 않았습니다." }, null, 2)}</pre>
      {history.slice(0, 8).map(item => <p key={item.intent_id}>{item.source} · {item.status} · {item.reason_code ?? "완료"}</p>)}
    </details>
  </section>;
}
