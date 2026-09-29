"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type RunSummary } from "@/lib/api";
import type { AnalysisAction, AnalysisExecution, AnalysisExecutionList, AnalysisGoal, AnalysisPlanList,
  AnalysisPlanRecord, AnalysisStepRecord, AnalysisSummary, AnalysisTemplates, AnalysisWorkflowsCapability, BudgetSnapshot,
  ResidueRef } from "@/lib/contracts";
import { acceptPolled, adoptExecution, allowedSourceKinds, ANALYSIS_GOALS, analysisUiState, approvalDisplay, BUSY_TEXT, CHEMICAL_CATEGORIES,
  classifyFailure, CONTACT_TYPES, DRY_RUN_NOTICE, draftInputs, EDIT_NEW_PLAN_NOTE, executionControls, executionProgressed,
  GOAL_LABELS, goalPlacement, importDraft, isTerminal, keepRequestAfter, LOCAL_RULES_NOTE, MAKE_IN_SCREEN, noticeApplies,
  objectsMayHaveChanged, outcomeText, PLAN_ESTIMATE_NOTE, planView, pollNeeded, requestIdFor, requestKey, responseCurrent, resultOpenDecision, stepIsExpensive, stopResend,
  type AnalysisDraft, type AnalysisPanelKind, type FailureKind, type PanelStamp, type PendingRequest, type PlanFocus, type ResultView,
  type ScreenSelections } from "@/lib/analysis";
import { Button } from "./primitives";

export interface AnalysisOpenRequest { runId: string; executionId: string; stepId: string; view: ResultView;
  handle: string | null; jobId: string | null; outputs: Record<string, string> }

export interface AnalysisWorkflowPanelProps {
  panel: AnalysisPanelKind;
  run: RunSummary;
  /** undefined while capabilities are read; null when the backend reports no analysis workflow capability. */
  capability: AnalysisWorkflowsCapability | null | undefined;
  sourceOptions: { handle: string; kind: string }[];
  /** Read only when a goal is chosen or 화면 선택 다시 가져오기 is pressed; later screen changes never alter a plan. */
  screen: ScreenSelections;
  /** Resolves to null when the host opened the result, or to the refusing guard's reason. */
  onOpenResult: (request: AnalysisOpenRequest) => string | null | void | Promise<string | null>;
  /** Main panel: enter the chemical workspace (chemical_interactions and chemical-structure results). */
  onEnterChemical?: (runId: string) => void;
  /** Chemical panel: return to the ordinary structure screen. */
  onExitToMain?: (runId: string) => void;
  /** A workflow mutation moved the record and may have created objects: the host re-reads its event log. */
  onObjectsChanged?: (runId: string) => void;
}

const UI_STATE_TEXT = { loading: "불러오는 중", ready: "준비", scientific_null: "정상적인 빈 결과 (scientific_null)",
  failure: "실패", unavailable: "사용할 수 없음" } as const;
const STATUS_TEXT: Record<string, string> = { plan_only: "계획 전용 (dry-run)", awaiting_approval: "계획 승인 대기",
  ready: "다음 단계 대기", executing: "단계 실행 중", waiting_job: "작업 대기", awaiting_scientific_approval: "계산 승인 대기",
  blocked: "차단됨", failed: "실패", cancelled: "중지됨", complete: "완료" };
const STEP_STATUS_TEXT: Record<string, string> = { pending: "대기", dispatched: "시작됨", waiting_job: "작업 진행 중",
  completed: "완료", failed: "실패", interrupted: "중단됨", cancelled: "취소됨", blocked: "차단됨" };
const ACTION_TEXT: Record<AnalysisAction, string> = { approve: "계획 승인", revoke: "승인 철회", advance: "다음 단계 실행",
  retry: "재시도", cancel: "중지", scientific_approval: "계산 승인" };
const errorText = (e: unknown) => e instanceof Error ? e.message : String(e);
const shortHandle = (handle: string) => handle.split("/").at(-1)?.slice(0, 12) ?? handle;
const json = (value: unknown) => JSON.stringify(value, null, 1);
const newId = () => crypto.randomUUID();
function residueText(ref: ResidueRef) {
  return `${ref.resname} · model ${ref.model_number ?? "?"} · auth ${ref.chain_auth}/${ref.seq_auth}${ref.icode || ""}` +
    ` · label ${ref.chain_label ?? "null"}/${ref.seq_label ?? "null"}`;
}
function failureOf(e: unknown): { kind: Exclude<FailureKind, "ok">; message: string; detail?: Record<string, unknown> } {
  if (e instanceof ApiError) return { kind: classifyFailure({ status: e.status, code: e.code }),
    message: `${e.code ? `${e.code}: ` : ""}${e.message}`, detail: e.detail };
  return { kind: "transport", message: errorText(e) };
}

export function AnalysisWorkflowPanel(p: AnalysisWorkflowPanelProps) {
  const runId = p.run.run_id;
  const [templates, setTemplates] = useState<AnalysisTemplates | null>(null);
  const [templatesError, setTemplatesError] = useState("");
  const [goal, setGoal] = useState<AnalysisGoal | "">("");
  const [draft, setDraft] = useState<AnalysisDraft | null>(null);
  const [ligandOptions, setLigandOptions] = useState<{ source: string; ligands: ResidueRef[] } | null>(null);
  const [chainOptions, setChainOptions] = useState<{ source: string; chains: { chain_auth: string; has_protein: boolean }[];
    defaults: string[] } | null>(null);
  const [optionError, setOptionError] = useState("");
  const [plan, setPlan] = useState<AnalysisPlanRecord | null>(null);
  // Which plan the preview shows: the chosen (new or reopened) plan, or the open execution's plan.
  const [planFocus, setPlanFocus] = useState<PlanFocus>("plan");
  const [plans, setPlans] = useState<AnalysisPlanList | null>(null);
  const [executions, setExecutions] = useState<AnalysisExecutionList | null>(null);
  const [listsError, setListsError] = useState("");
  const [listRevision, setListRevision] = useState(0);
  const [executionId, setExecutionId] = useState<string | null>(null);
  const [execution, setExecution] = useState<AnalysisExecution | null>(null);
  const [executionPlan, setExecutionPlan] = useState<AnalysisPlanRecord | null>(null);
  const [reading, setReading] = useState(false);
  const [readError, setReadError] = useState("");
  const [budget, setBudget] = useState<BudgetSnapshot | null>(null);
  const [summary, setSummary] = useState<AnalysisSummary | null>(null);
  const [busy, setBusy] = useState<AnalysisAction | "create_plan" | "create_execution" | "open" | null>(null);
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState("");
  const [waitBusy, setWaitBusy] = useState(false);

  // Stale-response guards: a newer action, another execution, another run (panel is keyed by run) or unmount wins.
  const action = useRef(0);
  const mounted = useRef(true);
  const live = useRef<PanelStamp>({ runId, executionId: null, action: 0 });
  live.current = { runId, executionId, action: action.current };
  const screenRef = useRef(p.screen);
  screenRef.current = p.screen;
  const hostRef = useRef(p);
  hostRef.current = p;
  const pendingRef = useRef<PendingRequest | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; action.current += 1; };
  }, []);
  const stamp = (overrides: Partial<PanelStamp> = {}): PanelStamp =>
    ({ ...live.current, action: ++action.current, ...overrides });
  const current = (captured: PanelStamp) =>
    responseCurrent(captured, { ...live.current, action: action.current }, mounted.current);

  const capabilityUnavailable = p.capability === null || p.capability?.available === false;
  const templateRow = templates?.templates.find(row => row.goal === goal) ?? null;
  const templateAvailable = goal ? (templateRow?.available ?? p.capability?.templates?.[goal]?.available ?? true) : true;
  const naturalLanguage = templates?.natural_language_planning ?? p.capability?.natural_language_planning ?? null;

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]);
    api.analysisTemplates(runId, signal).then(value => {
      if (!active) return;
      if (value.schema !== "analysis_templates@1") throw new Error("분석 템플릿 응답 형식이 다릅니다.");
      setTemplates(value); setTemplatesError("");
    }).catch(e => { if (active) setTemplatesError(`분석 템플릿 읽기 실패: ${errorText(e)}`); });
    api.budget(runId).then(value => { if (active) setBudget(value); }).catch(() => undefined);
    return () => { active = false; controller.abort(); };
  }, [runId]);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]);
    Promise.all([api.analysisPlans(runId, signal), api.analysisExecutions(runId, signal)]).then(([planList, executionList]) => {
      if (!active) return;
      if (planList.schema !== "analysis_plan_list@1" || executionList.schema !== "analysis_execution_list@1")
        throw new Error("계획·실행 목록 형식이 다릅니다.");
      setPlans(planList); setExecutions(executionList); setListsError("");
    }).catch(e => { if (active) setListsError(`계획·실행 목록 읽기 실패: ${errorText(e)}`); });
    return () => { active = false; controller.abort(); };
  }, [runId, listRevision]);
  const refreshLists = useCallback(() => setListRevision(value => value + 1), []);

  // Ligand instances of the chosen source (read-only list; nothing is preselected).
  const ligandSource = draft?.goal === "inspect_ligand" ? draft.source : "";
  useEffect(() => {
    if (!ligandSource) return;
    let active = true;
    const controller = new AbortController();
    api.residues(runId, ligandSource).then(list => {
      if (active) { setLigandOptions({ source: ligandSource, ligands: list.ligands }); setOptionError(""); }
    }).catch(e => { if (active) setOptionError(`리간드 목록 읽기 실패: ${errorText(e)}`); });
    return () => { active = false; controller.abort(); };
  }, [runId, ligandSource]);
  // Chain list of a find_cavities source from the existing read-only pocket preflight (no chain is checked for the user).
  const chainSource = draft?.goal === "find_cavities" ? draft.source : "";
  useEffect(() => {
    if (!chainSource) return;
    let active = true;
    const controller = new AbortController();
    api.pocketPreflight(runId, chainSource, [], AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(value => {
      if (!active || value.source_handle !== chainSource) return;
      setChainOptions({ source: chainSource, chains: (value.available_chains ?? []).map(item =>
        ({ chain_auth: item.chain_auth, has_protein: item.has_protein })), defaults: value.selected_chains ?? [] });
      setOptionError("");
    }).catch(e => { if (active) setOptionError(`체인 목록 읽기 실패: ${errorText(e)}`); });
    return () => { active = false; controller.abort(); };
  }, [runId, chainSource]);

  const readExecution = useCallback(async (id: string, captured: PanelStamp) => {
    const value = await api.analysisExecution(runId, id);
    if (!current(captured)) return null;
    if (value.execution_id !== id || value.run_id !== runId) throw new Error("실행 기록이 선택한 실행과 다릅니다.");
    setExecution(value); setReadError("");
    return value;
  // current() reads refs only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // Read-only polling while a step or job is in progress, and while this panel's own Advance/Retry runs inside its
  // request, so status and revision stay current (e.g. for 중지). Reads never write events or record job endings.
  const polling = pollNeeded(execution, busy);
  useEffect(() => {
    if (!executionId || !polling) return;
    const id = executionId;
    const timer = window.setInterval(() => {
      const captured = { ...live.current };
      void api.analysisExecution(runId, id).then(value => {
        if (current(captured) && value.execution_id === id && value.run_id === runId)
          setExecution(previous => acceptPolled(previous, value) ? value : previous);
      }).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, executionId, polling]);

  function chooseGoal(next: AnalysisGoal | "") {
    stamp(); pendingRef.current = null;
    setGoal(next); setPlan(null); setNotice(""); setFailure(""); setOptionError("");
    setDraft(next ? importDraft(next, p.panel, screenRef.current) : null);
  }
  function reimport() {
    if (!goal) return;
    stamp(); pendingRef.current = null;
    setPlan(null); setNotice("화면 선택을 다시 가져왔습니다."); setFailure("");
    setDraft(importDraft(goal, p.panel, screenRef.current));
  }
  function edit(change: Partial<AnalysisDraft>) {
    if (!draft) return;
    setDraft({ ...draft, ...change });
    if (plan) { setPlan(null); setNotice(EDIT_NEW_PLAN_NOTE); }
  }

  async function createPlan() {
    if (!draft || !goal) return;
    const mapped = draftInputs(draft);
    if (!mapped.inputs) return;
    const captured = stamp(), body = { goal, inputs: mapped.inputs };
    const pending = requestIdFor(pendingRef.current, requestKey("create_plan", runId, body), newId);
    pendingRef.current = pending;
    setBusy("create_plan"); setNotice(""); setFailure("");
    try {
      const record = await api.createAnalysisPlan(runId, { request_id: pending.requestId, ...body });
      if (!current(captured)) return;
      pendingRef.current = null;
      if (record.plan.schema !== "analysis_plan@1" || record.plan.goal !== goal || record.plan.source !== "local_rules")
        throw new Error("계획 응답이 요청한 목표와 다릅니다.");
      setPlan(record); setPlanFocus("plan"); refreshLists();
      setNotice(record.replayed ? "같은 요청의 저장된 계획을 다시 열었습니다." : `계획 #${record.ordinal}을 만들었습니다.`);
      void api.budget(runId).then(value => { if (current(captured)) setBudget(value); }).catch(() => undefined);
    } catch (e) {
      if (!current(captured)) return;
      const f = failureOf(e);
      if (!keepRequestAfter(f.kind)) pendingRef.current = null;
      setFailure(`계획 만들기 실패: ${f.message}${f.kind === "transport" ? " (같은 요청으로 다시 보낼 수 있습니다)" : ""}`);
      if (f.kind === "transport") refreshLists();
    } finally { if (current(captured)) setBusy(null); }
  }

  async function openPlan(handle: string) {
    const captured = stamp();
    setBusy("open"); setFailure(""); setNotice("");
    try {
      const record = await api.analysisPlan(runId, handle);
      if (!current(captured)) return;
      if (record.handle !== handle) throw new Error("계획 응답의 handle이 다릅니다.");
      setGoal(record.plan.goal); setDraft(null); setPlan(record); setPlanFocus("plan");
      setNotice("저장된 계획을 다시 열었습니다. 입력은 저장된 값 그대로입니다.");
    } catch (e) { if (current(captured)) setFailure(`계획 읽기 실패: ${errorText(e)}`); }
    finally { if (current(captured)) setBusy(null); }
  }

  async function createExecution() {
    if (!plan) return;
    const captured = stamp(), body = { plan_handle: plan.handle };
    let settled = captured;
    const pending = requestIdFor(pendingRef.current, requestKey("create_execution", runId, body), newId);
    pendingRef.current = pending;
    setBusy("create_execution"); setFailure(""); setNotice("");
    try {
      const envelope = await api.createAnalysisExecution(runId, { request_id: pending.requestId, ...body });
      if (!current(captured)) return;
      pendingRef.current = null;
      const record = envelope.execution;
      if (record.run_id !== runId || record.plan_handle !== plan.handle) throw new Error("실행 응답이 계획과 다릅니다.");
      setExecutionId(record.execution_id); setExecution(record); setExecutionPlan(plan); setSummary(null); setPlanFocus("execution");
      live.current = { ...live.current, executionId: record.execution_id };
      // This response opened the new execution: it (not the pre-request stamp) decides whether busy is released.
      settled = adoptExecution(captured, record.execution_id);
      setNotice(record.dry_run ? DRY_RUN_NOTICE : envelope.replayed ? "같은 요청의 저장된 실행을 다시 열었습니다." : "실행을 만들었습니다. 계획을 승인하세요.");
      refreshLists();
    } catch (e) {
      if (!current(captured)) return;
      const f = failureOf(e);
      if (!keepRequestAfter(f.kind)) pendingRef.current = null;
      const codes = Array.isArray(f.detail?.codes) ? ` (${(f.detail!.codes as string[]).join(", ")})` : "";
      setFailure(`실행 만들기 실패: ${f.message}${codes}`);
      refreshLists();
    } finally { if (current(settled)) setBusy(null); }
  }

  async function openExecution(id: string) {
    const captured = stamp({ executionId: id });
    live.current = { ...live.current, executionId: id };
    pendingRef.current = null;
    setExecutionId(id); setExecution(null); setExecutionPlan(null); setSummary(null); setPlanFocus("execution");
    setReading(true); setReadError(""); setFailure(""); setNotice(""); setWaitBusy(false);
    try {
      const value = await readExecution(id, captured);
      if (!value) return;
      const planRecord = await api.analysisPlan(runId, value.plan_handle);
      if (!current(captured)) return;
      if (planRecord.handle !== value.plan_handle || planRecord.plan_sha256 !== value.plan_sha256)
        throw new Error("실행이 가리키는 계획의 해시가 다릅니다.");
      setExecutionPlan(planRecord);
    } catch (e) { if (current(captured)) setReadError(`실행 기록 읽기 실패: ${errorText(e)}`); }
    // This read superseded any older action whose late response is now discarded: release its busy state.
    finally { if (current(captured)) { setReading(false); setBusy(null); } }
  }

  async function mutate(kind: AnalysisAction, extra: { plan_hash?: string; step_id?: string } = {}) {
    if (execution) await send(execution, kind, extra, 0);
  }
  /** One user action = one request id; a transport-failed body is re-sent with the same id. Every refusal re-reads. */
  async function send(before: AnalysisExecution, kind: AnalysisAction, extra: { plan_hash?: string; step_id?: string },
    resends: number): Promise<void> {
    const id = before.execution_id;
    const captured = stamp();
    const body = { expected_revision: before.revision, ...extra };
    const pending = requestIdFor(resends ? null : pendingRef.current, requestKey(kind, id, body), newId);
    pendingRef.current = pending;
    setBusy(kind); setFailure(""); setNotice(""); setWaitBusy(false);
    try {
      const envelope = await api.analysisAction(runId, id, kind, { request_id: pending.requestId, ...body });
      if (!current(captured)) return;
      pendingRef.current = null;
      if (envelope.execution.execution_id !== id || envelope.execution.run_id !== runId)
        throw new Error("응답의 실행 식별자가 다릅니다.");
      setExecution(envelope.execution);
      const outcome = envelope.request.state === "pending" ? "요청을 처리하는 중입니다. 기록을 다시 읽으세요."
        : outcomeText(envelope.request.outcome);
      setNotice(`${ACTION_TEXT[kind]}: ${outcome}${envelope.replayed ? " (같은 요청의 기록된 결과)" : ""}` +
        (resends ? " (기록이 바뀌어 다시 읽은 뒤 한 번 다시 보냈습니다)" : ""));
      if (envelope.request.outcome === "run_busy") setWaitBusy(true);
      if (isTerminal(envelope.execution)) refreshLists();
      if (objectsMayHaveChanged(before, envelope.execution)) hostRef.current.onObjectsChanged?.(runId);
      void api.budget(runId).then(value => { if (mounted.current) setBudget(value); }).catch(() => undefined);
    } catch (e) {
      if (!current(captured)) return;
      const f = failureOf(e);
      if (!keepRequestAfter(f.kind)) pendingRef.current = null;
      // Any refusal may still have recorded recovery events, and a lost long Advance may have progressed: re-read first.
      let fresh: AnalysisExecution | null = null;
      try { fresh = await readExecution(id, captured); } catch (readFailure) {
        if (current(captured)) setReadError(`실행 기록 다시 읽기 실패: ${errorText(readFailure)}`);
      }
      if (!current(captured)) return;
      if (fresh && objectsMayHaveChanged(before, fresh)) hostRef.current.onObjectsChanged?.(runId);
      if (kind === "cancel" && fresh && stopResend(f.kind, resends)) { setBusy(null); await send(fresh, "cancel", {}, resends + 1); return; }
      if (f.kind === "busy") { setWaitBusy(true); setNotice(`${BUSY_TEXT}. 잠시 뒤 다시 누르세요.`); return; }
      if (f.kind === "transport" && fresh && executionProgressed(before, fresh)) {
        pendingRef.current = null;
        setNotice(`${ACTION_TEXT[kind]} 응답을 받지 못해 실행 기록을 다시 읽었습니다: ` +
          `${STATUS_TEXT[fresh.status] ?? fresh.status} (revision ${fresh.revision}).`);
        return;
      }
      setFailure(`${ACTION_TEXT[kind]} 실패: ${f.message}` + (f.kind === "transport"
        ? " (응답을 받지 못했습니다. 같은 요청으로 다시 보낼 수 있습니다)"
        : f.kind === "stale_revision" ? " (기록이 바뀌어 다시 읽었습니다. 확인 후 다시 누르세요)"
          : resends ? " (자동 재전송은 한 번만 합니다)" : ""));
    } finally { if (current(captured)) setBusy(null); }
  }

  async function loadSummary() {
    if (!execution) return;
    const captured = stamp(), id = execution.execution_id;
    setBusy("open"); setFailure("");
    try {
      const value = await api.analysisSummary(runId, id);
      if (!current(captured)) return;
      if (value.summary.execution_id !== id || value.handle !== execution.summary_handle) throw new Error("요약이 선택한 실행과 다릅니다.");
      setSummary(value);
    } catch (e) { if (current(captured)) setFailure(`요약 읽기 실패: ${errorText(e)}`); }
    finally { if (current(captured)) setBusy(null); }
  }

  async function rereadExecution() {
    if (!executionId) return;
    const captured = stamp();
    setReading(true); setWaitBusy(false);
    try { await readExecution(executionId, captured); }
    catch (e) { if (current(captured)) setReadError(`실행 기록 읽기 실패: ${errorText(e)}`); }
    finally { if (current(captured)) { setReading(false); setBusy(null); } }
  }

  async function openResult(step: AnalysisStepRecord, view: ResultView) {
    if (!execution) return;
    const host = hostRef.current;
    if (host.run.run_id !== runId) return;
    const captured = { ...live.current };
    const handle = Object.values(step.outputs ?? {}).find(value => value !== step.report_handle) ?? null;
    setNotice(`${step.step_id} 결과를 기존 화면의 경로로 엽니다.`); setFailure("");
    const refusal = await host.onOpenResult({ runId, executionId: execution.execution_id, stepId: step.step_id, view,
      handle, jobId: step.job_id, outputs: { ...step.outputs } });
    if (!refusal || !responseCurrent(captured, { ...live.current, action: action.current }, mounted.current)) return;
    setNotice("");
    setFailure(`${step.step_id} 결과를 열 수 없습니다: ${refusal}` + (view === "pocket"
      ? ` 조건이 풀리면 fpocket 후보 공동 패널의 "기록에서 다시 열기"에서 ${shortHandle(handle ?? "")} 항목을 여세요.` : ""));
  }

  // ------------------------------------------------------------------------------------------ derived view
  const mapping = draft ? draftInputs(draft) : null;
  const placement = goal ? goalPlacement(p.panel, goal) : null;
  const { shownPlan, createExecution: showCreateExecution } = planView({ plan, executionId, executionPlan, focus: planFocus });
  const controls = execution ? executionControls(execution, { busy: busy !== null, busyAction: busy as AnalysisAction | null }) : null;
  const approvals = execution ? approvalDisplay(execution) : null;
  const uiState = analysisUiState({ available: !capabilityUnavailable, templateAvailable: execution ? true : templateAvailable,
    reading: reading || (p.capability === undefined && !templates), pending: busy !== null && busy !== "cancel",
    readError: readError || null, record: execution });
  const planSourceKind = (record: AnalysisPlanRecord | null) =>
    (record?.plan.inputs.source_kind as string | undefined) ?? (record?.plan.inputs.reference_kind as string | undefined) ?? null;
  const approveHash = executionPlan && execution && executionPlan.plan_sha256 === execution.plan_sha256 ? execution.plan_sha256 : null;
  const planDisabled = busy !== null ? "요청을 처리하는 중입니다." : !goal ? "분석 목표를 고르세요."
    : placement && !placement.allowed ? placement.reason
      : !templateAvailable ? `사용할 수 없음: ${templateRow?.reason ?? p.capability?.templates?.[goal]?.reason ?? "방법을 사용할 수 없습니다."}`
        : !mapping ? "저장된 계획입니다. 새 계획은 목표를 다시 고르세요." : mapping.blockers[0] ?? null;
  const executionDisabled = busy !== null ? "요청을 처리하는 중입니다." : !plan ? "먼저 계획을 만드세요."
    : !plan.executable ? "선행 조건이 충족되지 않은 계획으로는 실행을 만들 수 없습니다." : null;
  const sourceChoices = goal ? p.sourceOptions.filter(option => allowedSourceKinds(p.panel, goal).includes(option.kind)) : [];

  return <section className="mw-analysis" aria-label="분석 흐름" data-analysis-panel={p.panel} data-analysis-ui-state={uiState}>
    <div className="mw-pocket-head"><strong>분석 흐름</strong>
      <span className="mw-badge" data-analysis-state={uiState}>{UI_STATE_TEXT[uiState]}</span></div>
    <p className="mw-muted">미리 정한 분석 목표를 골라 입력을 확인하고, 계획을 미리 본 뒤 승인하고, 한 번에 한 단계씩 실행합니다.
      모든 단계는 기존 도구 호출·작업·보고서 경로로만 실행됩니다.</p>
    {capabilityUnavailable && <p role="status" className="mw-pocket-blocked" data-analysis-unavailable>
      분석 흐름 사용할 수 없음: 백엔드가 분석 흐름 기능을 알려 주지 않았습니다.</p>}
    {templatesError && <p role="alert" className="mw-table-error">{templatesError}</p>}
    {p.run.dry_run && <p role="status" className="mw-pocket-notice" data-analysis-dry-run>{DRY_RUN_NOTICE}</p>}
    <div className="mw-analysis-inline">
      <Button size="sm" disabled title={naturalLanguage?.reason ?? "사용할 수 없음"}>자연어로 계획 만들기 (사용할 수 없음)</Button>
      <span className="mw-muted" data-analysis-nl-unavailable>{naturalLanguage?.reason ?? "자연어 계획은 사용할 수 없습니다."}</span>
    </div>

    <div className="mw-pocket-group" aria-label="분석 목표와 입력">
      <label>분석 목표<select className="mw-select" aria-label="분석 목표" value={goal} disabled={busy !== null}
        onChange={e => chooseGoal(e.target.value as AnalysisGoal | "")}>
        <option value="">목표 선택</option>
        {ANALYSIS_GOALS.map(item => { const row = templates?.templates.find(t => t.goal === item);
          const where = goalPlacement(p.panel, item);
          return <option key={item} value={item}>{GOAL_LABELS[item]} · {item}{row && !row.available ? " (사용할 수 없음)" : ""}
            {!where.allowed ? ` (${where.reason})` : ""}</option>; })}
      </select></label>
      {templateRow && <p className="mw-muted mw-mono">{templateRow.template_version} · 단계 {templateRow.steps.join(" → ")}</p>}
      {goal && !templateAvailable && <p role="status" className="mw-pocket-blocked" data-analysis-template-unavailable={goal}>
        사용할 수 없음 ({templateRow?.reason_code ?? p.capability?.templates?.[goal]?.reason_code ?? "method_unavailable"}):
        {" "}{templateRow?.reason ?? p.capability?.templates?.[goal]?.reason ?? "방법을 사용할 수 없습니다."}</p>}
      {placement && !placement.allowed && <div role="status" className="mw-pocket-notice" data-analysis-placement={goal}>
        <p>{placement.reason}</p>
        {placement.enterChemical && p.onEnterChemical &&
          <Button size="sm" onClick={() => p.onEnterChemical?.(runId)}>화학 작업 화면으로 이동</Button>}
        {!placement.enterChemical && p.onExitToMain &&
          <Button size="sm" onClick={() => p.onExitToMain?.(runId)}>기존 구조 화면으로 이동</Button>}
      </div>}
      {draft && placement?.allowed && <DraftEditor draft={draft} sourceChoices={sourceChoices} edit={edit}
        ligandOptions={ligandOptions?.source === draft.source ? ligandOptions.ligands : null}
        chainOptions={chainOptions?.source === draft.source ? chainOptions : null} disabled={busy !== null} />}
      {optionError && <p role="alert" className="mw-table-error">{optionError}</p>}
      {draft && placement?.allowed && <>
        {mapping?.missing.map(item => <p key={item} role="status" className="mw-analysis-missing" data-analysis-missing>{item}</p>)}
        <p className="mw-muted">{EDIT_NEW_PLAN_NOTE}</p>
        <div className="mw-analysis-inline">
          <Button size="sm" disabled={busy !== null} onClick={reimport}>화면 선택 다시 가져오기</Button>
          <Button size="sm" variant="primary" disabled={!!planDisabled} title={planDisabled ?? undefined}
            onClick={() => void createPlan()}>계획 만들기</Button>
          {planDisabled && <span className="mw-muted" data-analysis-plan-reason>{planDisabled}</span>}
        </div></>}
    </div>

    {shownPlan && <PlanPreview record={shownPlan} budget={budget} />}
    {plan && showCreateExecution && <div className="mw-analysis-inline">
      <Button size="sm" variant="primary" disabled={!!executionDisabled} title={executionDisabled ?? undefined}
        onClick={() => void createExecution()}>실행 만들기</Button>
      {executionDisabled && <span className="mw-muted" data-analysis-execution-reason>{executionDisabled}</span>}
      {p.run.dry_run && <span className="mw-muted">dry-run run에서는 계획 전용 실행(plan_only)만 만들어집니다.</span>}
    </div>}

    {notice && <p role="status" className="mw-pocket-notice" data-analysis-notice>{notice}</p>}
    {failure && <p role="alert" className="mw-table-error" data-analysis-error>{failure}</p>}
    {waitBusy && <div role="status" className="mw-pocket-notice" data-analysis-busy>{BUSY_TEXT}. 요청이 끝나면 다시 누르세요.
      <Button size="sm" onClick={() => void rereadExecution()}>기록 다시 읽기</Button></div>}

    {executionId && <div className="mw-pocket-group mw-analysis-execution" aria-label="분석 실행"
      data-analysis-execution-id={executionId} data-analysis-status={execution?.status ?? "loading"}
      data-analysis-revision={execution?.revision ?? ""} data-analysis-retryable-step={execution?.retryable_step ?? ""}>
      {reading && !execution && <p role="status" className="mw-muted">실행 기록을 읽는 중…</p>}
      {readError && <div role="alert" className="mw-table-error"><p>{readError}</p>
        <Button size="sm" onClick={() => void rereadExecution()}>실행 기록 다시 읽기</Button></div>}
      {execution && controls && approvals && <>
        <p className="mw-capability mw-mono">{execution.execution_id} · {GOAL_LABELS[execution.goal]} ({execution.goal})
          · {STATUS_TEXT[execution.status] ?? execution.status} · revision {execution.revision}
          · 물리 시도 {execution.physical_attempts}/{execution.limits.max_physical_attempts ?? 24}
          · 활동 {Math.round(execution.active_wall_s)}s/{execution.limits.max_active_wall_s ?? 1800}s</p>
        {execution.dry_run && <p role="status" className="mw-pocket-notice" data-analysis-dry-run>{DRY_RUN_NOTICE}</p>}
        <div className="mw-analysis-approvals">
          <span className="mw-badge" data-analysis-plan-approval={approvals.plan.state}>{approvals.plan.text}</span>
          <span className="mw-badge" data-analysis-scientific-approval={approvals.scientific.state}>{approvals.scientific.text}</span>
        </div>
        <p className="mw-muted">계획 승인은 이 계획의 단계 목록만 허가합니다. 작업 단계의 비싼 계산 승인·예산 한도는 따로이며 서로 대신하지 않습니다.</p>
        {execution.blocked_reason && <p role="alert" className="mw-table-error" data-analysis-blocked={execution.blocked_reason.reason_code}>
          차단 ({execution.blocked_reason.reason_code}{execution.blocked_reason.step_id ? ` · ${execution.blocked_reason.step_id}` : ""}): {execution.blocked_reason.message}</p>}
        {execution.notice && noticeApplies(execution, execution.notice.step_id) && <p role="status" className="mw-pocket-notice" data-analysis-record-notice={execution.notice.code}>
          {execution.notice.message ?? execution.notice.code}{execution.notice.step_id ? ` (${execution.notice.step_id})` : ""}</p>}
        {execution.stop && <p role="status" className="mw-muted" data-analysis-stop={execution.stop.reason}>
          {execution.stop.reason === "revoke" ? "실행 중 승인 철회로 종료되었습니다." : "중지되었습니다. 이 실행만 끝났고 run의 다른 실행·수동 도구는 그대로입니다."} (이벤트 #{execution.stop.seq})</p>}
        {execution.recovery_pending && <p role="status" className="mw-muted" data-analysis-recovery-pending>
          복구 대기: 다음 변경 요청(다음 단계 실행·중지 등)이 기록된 자식 결과를 확인해 조정합니다. 읽기는 아무것도 실행하지 않습니다.</p>}
        {!execution.jobs_readable && <p role="alert" className="mw-table-error">작업 상태를 읽지 못했습니다. 기록을 다시 읽으세요.</p>}
        <div className="mw-analysis-inline" aria-label="분석 실행 컨트롤">
          <ControlButton label="계획 승인" state={controls.approve} disabled={!approveHash}
            disabledReason={!approveHash ? "승인할 계획을 확인하는 중입니다." : null}
            onClick={() => approveHash && void mutate("approve", { plan_hash: approveHash })} />
          <ControlButton label="승인 철회" state={controls.revoke} onClick={() => void mutate("revoke")} />
          {controls.scientific_approval.visible
            ? <ControlButton label="계산 승인" state={controls.scientific_approval} onClick={() => void mutate("scientific_approval")} />
            : execution.scientific_approval.state === "already_approved_in_run" &&
              <span className="mw-muted" data-analysis-already-approved>이 run에서 이미 계산 승인됨</span>}
          <ControlButton label="다음 단계 실행" state={controls.advance} variant="primary" onClick={() => void mutate("advance")} />
          {controls.retry.visible && execution.retryable_step &&
            <ControlButton label="재시도" state={controls.retry}
              onClick={() => void mutate("retry", { step_id: execution.retryable_step! })} />}
          <ControlButton label="중지" state={controls.cancel} variant="stop" onClick={() => void mutate("cancel")} />
          <Button size="sm" disabled={reading} onClick={() => void rereadExecution()}>기록 다시 읽기</Button>
        </div>
        {controls.advance.reason && !isTerminal(execution) && <p className="mw-muted" data-analysis-advance-reason>다음 단계 실행: {controls.advance.reason}</p>}
        <p className="mw-muted">다음 단계 실행은 한 번에 한 단계(또는 한 작업 시작)만 진행하며 자동으로 이어 실행하지 않습니다.</p>
        <StepList execution={execution} planRecord={executionPlan} panel={p.panel} runId={runId}
          sourceKind={planSourceKind(executionPlan)} onOpen={openResult}
          onEnterChemical={p.onEnterChemical ? () => p.onEnterChemical?.(runId) : undefined}
          onExitToMain={p.onExitToMain ? () => p.onExitToMain?.(runId) : undefined} />
        {execution.status === "complete" && execution.summary_handle && <div className="mw-analysis-inline" aria-label="완료 요약">
          <Button size="sm" disabled={busy !== null} onClick={() => void loadSummary()}>요약 보기</Button>
          <a className="mw-btn mw-btn--sm" href={api.analysisSummaryDownload(runId, execution.execution_id)} download>요약 JSON 다운로드</a>
        </div>}
        {summary && summary.summary.execution_id === execution.execution_id && <SummaryView summary={summary} />}
      </>}
    </div>}

    <details className="mw-pocket-group" aria-label="분석 기록">
      <summary>이 run의 계획·실행 ({plans?.total ?? 0} / {executions?.total ?? 0})</summary>
      {listsError && <p role="alert" className="mw-table-error">{listsError}</p>}
      <Button size="sm" onClick={refreshLists}>목록 다시 읽기</Button>
      <p className="mw-eyebrow">실행</p>
      {executions?.rows.map(row => <div key={row.execution_id} className="mw-pocket-history" data-analysis-history-execution={row.execution_id}
        data-analysis-history-status={row.status}>
        <span className="mw-mono">{row.execution_id} · {row.goal} · {STATUS_TEXT[row.status] ?? row.status} · rev {row.revision}{row.dry_run ? " · dry-run" : ""}</span>
        <Button size="sm" aria-label={`실행 다시 열기 ${row.execution_id}`} disabled={busy !== null && busy !== "cancel"}
          onClick={() => void openExecution(row.execution_id)}>다시 열기</Button>
      </div>)}
      <p className="mw-eyebrow">계획</p>
      {plans?.rows.map(row => <div key={row.handle} className="mw-pocket-history" data-analysis-history-plan={row.handle}>
        <span className="mw-mono">#{row.ordinal} · {row.goal} · {shortHandle(row.handle)} · {row.executable ? "실행 가능" : "선행 조건 미충족"}</span>
        <Button size="sm" aria-label={`계획 다시 열기 ${row.ordinal}`} disabled={busy !== null}
          onClick={() => void openPlan(row.handle)}>다시 열기</Button>
      </div>)}
    </details>
  </section>;
}

function ControlButton({ label, state, onClick, variant, disabled, disabledReason }: { label: string;
  state: { visible: boolean; enabled: boolean; reason: string | null }; onClick: () => void;
  variant?: "primary" | "stop"; disabled?: boolean; disabledReason?: string | null }) {
  if (!state.visible) return null;
  const reason = state.reason ?? (disabled ? disabledReason ?? null : null);
  return <Button size="sm" variant={variant} disabled={!state.enabled || !!disabled} title={reason ?? undefined}
    data-analysis-control={label} data-analysis-control-reason={reason ?? ""} onClick={onClick}>{label}</Button>;
}

function DraftEditor({ draft, sourceChoices, edit, ligandOptions, chainOptions, disabled }: { draft: AnalysisDraft;
  sourceChoices: { handle: string; kind: string }[]; edit: (change: Partial<AnalysisDraft>) => void;
  ligandOptions: ResidueRef[] | null;
  chainOptions: { chains: { chain_auth: string; has_protein: boolean }[]; defaults: string[] } | null; disabled: boolean }) {
  const ligandKey = (ref: ResidueRef) => JSON.stringify([ref.model_number, ref.chain_auth, ref.chain_label, ref.seq_auth,
    ref.seq_label, ref.icode, ref.resname]);
  const sourceEditable = draft.goal !== "compare_structures" && draft.goal !== "chemical_interactions" &&
    !(draft.goal === "measure_atoms" && draft.atoms);
  return <div className="mw-analysis-draft" aria-label="가져온 화면 선택" data-analysis-draft-goal={draft.goal}>
    {sourceEditable && <label>소스 (표시 중인 구조에서 가져옴)<select className="mw-select" aria-label="분석 소스" value={draft.source}
      disabled={disabled} onChange={e => { const option = sourceChoices.find(item => item.handle === e.target.value);
        edit({ source: option?.handle ?? "", sourceKind: option?.kind ?? null, ligand: null, chains: [] }); }}>
      <option value="">소스 선택</option>
      {sourceChoices.map(option => <option key={option.handle} value={option.handle}>{option.kind} · {option.handle}</option>)}
    </select></label>}
    {!sourceEditable && draft.goal === "measure_atoms" && <p className="mw-mono">소스 (측정 원자의 구조, 읽기 전용): {draft.source}</p>}

    {draft.goal === "inspect_ligand" && <>
      <label>리간드 인스턴스 (자동으로 고르지 않음)<select className="mw-select" aria-label="분석 리간드 인스턴스"
        value={draft.ligand ? ligandKey(draft.ligand) : ""} disabled={disabled || !ligandOptions}
        onChange={e => edit({ ligand: ligandOptions?.find(item => ligandKey(item) === e.target.value) ?? null })}>
        <option value="">리간드 선택</option>
        {ligandOptions?.map(ref => <option key={ligandKey(ref)} value={ligandKey(ref)}>{residueText(ref)}</option>)}
      </select></label>
      {draft.ligand && <p className="mw-mono" data-analysis-ligand>{residueText(draft.ligand)}</p>}
      {draft.sourceKind === "structure" && <fieldset className="mw-pocket-chains"><legend>전처리 정책 (원본 구조)</legend>
        <label>altloc<select className="mw-select" aria-label="분석 altloc" value={draft.preparation.altloc} disabled={disabled}
          onChange={e => edit({ preparation: { ...draft.preparation, altloc: e.target.value as "highest_occupancy" | "first" } })}>
          <option value="highest_occupancy">highest_occupancy</option><option value="first">first</option></select></label>
        <label>물<select className="mw-select" aria-label="분석 물 처리" value={draft.preparation.waters} disabled={disabled}
          onChange={e => edit({ preparation: { ...draft.preparation, waters: e.target.value as "strip_all" | "keep_all" } })}>
          <option value="strip_all">strip_all</option><option value="keep_all">keep_all</option></select></label>
        <label>수소<select className="mw-select" aria-label="분석 수소 처리" value={draft.preparation.hydrogens} disabled={disabled}
          onChange={e => edit({ preparation: { ...draft.preparation, hydrogens: e.target.value as "strip" | "keep" } })}>
          <option value="strip">strip</option><option value="keep">keep</option></select></label>
        <small className="mw-muted">missing_residues=leave_gaps · symmetry_mates=ignore (고정)</small>
      </fieldset>}
      <label>cutoff (Å, 2.5–6.0)<input className="mw-number" type="number" min={2.5} max={6} step={0.1} aria-label="분석 cutoff"
        value={draft.cutoff_A} disabled={disabled} onChange={e => edit({ cutoff_A: Number(e.target.value) })} /></label>
      <fieldset className="mw-pocket-chains"><legend>접촉 종류 (기하 접촉, 수소결합 아님)</legend>
        {CONTACT_TYPES.map(type => <label key={type}><input type="checkbox" aria-label={`접촉 종류 ${type}`}
          checked={draft.types.includes(type)} disabled={disabled}
          onChange={e => edit({ types: e.target.checked ? [...new Set([...draft.types, type])] : draft.types.filter(item => item !== type) })} /> {type}</label>)}
      </fieldset>
    </>}

    {draft.goal === "measure_atoms" && (draft.atoms && draft.atoms.source === draft.source
      ? <div data-analysis-readonly="atoms"><p className="mw-eyebrow">원자 두 개 (기존 측정 화면에서 가져옴 · 읽기 전용)</p>
        <pre className="mw-analysis-json">{json({ first: draft.atoms.first, second: draft.atoms.second })}</pre></div>
      : <p role="status" className="mw-analysis-missing" data-analysis-readonly-missing="atoms">원자 두 개: {MAKE_IN_SCREEN}</p>)}

    {draft.goal === "compare_structures" && (draft.comparison
      ? <div data-analysis-readonly="comparison"><p className="mw-mono">기준 {draft.comparison.reference}<br />이동 {draft.comparison.moving}</p>
        <details><summary>CA 대응표 {draft.comparison.pairs.length}쌍 (읽기 전용 · 자동 짝짓기 없음)</summary>
          <pre className="mw-analysis-json">{json(draft.comparison.pairs)}</pre></details></div>
      : <p role="status" className="mw-analysis-missing" data-analysis-readonly-missing="comparison">기준·이동 구조와 CA 대응표: {MAKE_IN_SCREEN}</p>)}

    {draft.goal === "chemical_interactions" && <>
      {draft.chemicalRequest
        ? <details data-analysis-readonly="chemical_request"><summary>M11 준비 요청 (미리보기 ready · 읽기 전용 · {String(draft.chemicalRequest.mode)})</summary>
          <pre className="mw-analysis-json">{json(draft.chemicalRequest)}</pre></details>
        : <p role="status" className="mw-analysis-missing" data-analysis-readonly-missing="chemical_request">준비 요청: {MAKE_IN_SCREEN} (화학 작업 화면 1–2단계, 미리보기 ready)</p>}
      <p className="mw-mono" data-analysis-categories>상호작용 범주 (고정, 고를 수 없음): {CHEMICAL_CATEGORIES.join(", ")}</p>
    </>}

    {draft.goal === "find_cavities" && <fieldset className="mw-pocket-chains"><legend>체인 선택 (명시적으로 고름 · 빈 목록은 실행 불가)</legend>
      {!chainOptions && draft.source && <span className="mw-muted">체인 목록을 읽는 중…</span>}
      {chainOptions?.chains.map(({ chain_auth: chain, has_protein }) => <label key={chain}><input type="checkbox"
        aria-label={`분석 체인 ${chain}`} checked={draft.chains.includes(chain)} disabled={disabled}
        onChange={e => edit({ chains: e.target.checked ? [...new Set([...draft.chains, chain])].sort() : draft.chains.filter(item => item !== chain) })} />
        체인 {chain} <small className="mw-muted">{has_protein ? "단백질 있음" : "단백질 없음"}</small></label>)}
      {chainOptions && chainOptions.defaults.length > 0 && <Button size="sm" disabled={disabled}
        onClick={() => edit({ chains: [...chainOptions.defaults].sort() })}>단백질이 있는 체인 모두 고르기</Button>}
    </fieldset>}

    {draft.goal === "minimize_protein" && <fieldset className="mw-pocket-chains"><legend>OpenMM 확인</legend>
      <label><input type="checkbox" aria-label="분석 protein_only 확인" checked={draft.proteinOnly} disabled={disabled}
        onChange={e => edit({ proteinOnly: e.target.checked })} /> protein_only: 단백질만 남기고 물·리간드·이온·비단백질을 제외합니다.</label>
      <label><input type="checkbox" aria-label="분석 rebuild_pH7 확인" checked={draft.rebuildH} disabled={disabled}
        onChange={e => edit({ rebuildH: e.target.checked })} /> rebuild_pH7: 기존 수소 제거 후 pH 7.0에서 수소를 다시 만듭니다.</label>
    </fieldset>}
  </div>;
}

function PlanPreview({ record, budget }: { record: AnalysisPlanRecord; budget: BudgetSnapshot | null }) {
  const plan = record.plan;
  const inputs = plan.inputs;
  const assumptions: string[] = [];
  if (inputs.preparation && typeof inputs.preparation === "object") assumptions.push(`전처리 정책 ${JSON.stringify(inputs.preparation)}`);
  if (inputs.engine) assumptions.push(`접촉 엔진 ${String(inputs.engine)} (거리 기반 기하 접촉, 수소결합 아님)`);
  if (inputs.selection_policy) assumptions.push(`OpenMM ${String(inputs.selection_policy)} · ${String(inputs.hydrogen_policy)}`);
  if (inputs.categories) assumptions.push(`화학 범주 고정 ${(inputs.categories as string[]).join(", ")} · 방식 ${String(inputs.mode)}`);
  if (plan.goal === "find_cavities") assumptions.push("fpocket 결과 순위는 같은 실행 안의 상대 점수이며 결합 부위·약물성 증거가 아닙니다.");
  return <div className="mw-analysis-plan" aria-label="계획 미리보기" data-analysis-plan-handle={record.handle}
    data-analysis-plan-executable={String(record.executable)} data-analysis-plan-goal={plan.goal}>
    <div className="mw-analysis-inline"><span className="mw-badge mw-analysis-estimate">계획 · 측정 아님</span>
      <strong data-analysis-plan-source={plan.source}>{LOCAL_RULES_NOTE}</strong></div>
    <p className="mw-mono">{plan.planner} · source {plan.source} · {plan.template_version} · 계획 #{record.ordinal}
      · {record.handle} · sha256 {record.plan_sha256}</p>
    <p className="mw-muted">{PLAN_ESTIMATE_NOTE}</p>
    <details open><summary>정확한 입력 (식별자 전체)</summary><pre className="mw-analysis-json" data-analysis-plan-inputs>{json(inputs)}</pre></details>
    {assumptions.length > 0 && <div><p className="mw-eyebrow">가정</p>{assumptions.map(item => <p key={item} className="mw-muted">{item}</p>)}</div>}
    <ol className="mw-analysis-steps" aria-label="계획 단계">
      {plan.steps.map(step => <li key={step.step_id} data-analysis-plan-step={step.step_id} data-analysis-plan-lane={step.lane}>
        <span className="mw-mono">{step.step_id} · {step.operation} · {step.lane} · {step.operation_version}
          {step.depends_on.length ? ` · 선행 ${step.depends_on.join(", ")}` : ""}
          {typeof step.params.timeout_s === "number" ? ` · 제한 시간 ${step.params.timeout_s}s` : ""}</span>
        {stepIsExpensive(step) && <span className="mw-badge mw-analysis-expensive" data-analysis-expensive>비싼 계산 (작업 · 계산 승인 대상)</span>}
      </li>)}
    </ol>
    <p className="mw-muted" data-analysis-limits>고정 한도: 단계 {plan.limits.max_steps} · 물리 시도 {plan.limits.max_physical_attempts}
      · 활동 {plan.limits.max_active_wall_s}s · 단계당 재시도 {plan.limits.max_retries_per_step}
      {budget ? ` · 현재 run 예산: 비싼 계산 ${budget.expensive_calls.used}/${budget.expensive_calls.limit} (남음 ${Math.max(0, budget.expensive_calls.limit - budget.expensive_calls.used)})`
        + ` · 시간 ${Math.round(budget.wall_clock_s.used)}/${budget.wall_clock_s.limit}s` : " · 현재 run 예산을 읽는 중"}</p>
    {plan.unmet_prerequisites.length > 0 && <div role="alert" className="mw-table-error" data-analysis-unmet>
      <p>선행 조건 미충족 · 이 계획으로는 실행을 만들 수 없습니다</p>
      {plan.unmet_prerequisites.map((item, index) => <p key={`${item.code}:${index}`} data-analysis-unmet-code={item.code}>
        {item.code}: {item.message}{Object.keys(item.detail ?? {}).length ? ` ${JSON.stringify(item.detail)}` : ""}</p>)}
    </div>}
    <details><summary>실행 중 정해지는 출력 ({plan.deferred_bindings.length})</summary>
      {plan.deferred_bindings.map(item => <p key={`${item.step_id}:${item.output_name}`} className="mw-mono">
        {item.step_id}.{item.output_name} · {item.kind} · {item.schema}</p>)}</details>
    <details><summary>호환성 지문</summary><pre className="mw-analysis-json">{json(plan.compatibility)}</pre></details>
  </div>;
}

function StepList({ execution, planRecord, panel, runId, sourceKind, onOpen, onEnterChemical, onExitToMain }: {
  execution: AnalysisExecution; planRecord: AnalysisPlanRecord | null; panel: AnalysisPanelKind; runId: string;
  sourceKind: string | null; onOpen: (step: AnalysisStepRecord, view: ResultView) => Promise<void>;
  onEnterChemical?: () => void; onExitToMain?: () => void }) {
  return <ol className="mw-analysis-steps mw-analysis-measured" aria-label="실행 단계">
    {execution.steps.map(step => {
      const decision = resultOpenDecision(panel, execution.goal, sourceKind, step.operation);
      const completed = step.status === "completed";
      const cleanupPending = step.job_cleanup_status === "pending";
      const planStep = planRecord?.plan.steps.find(item => item.step_id === step.step_id);
      return <li key={step.step_id} data-analysis-step={step.step_id} data-analysis-step-status={step.status}
        data-analysis-step-null-result={step.null_result === null ? "" : String(step.null_result)}
        data-analysis-job-ownership={step.job_ownership ?? ""}>
        <div className="mw-analysis-inline">
          <span className="mw-mono">{step.step_id} · {step.operation} · {step.lane}</span>
          <span className="mw-badge">{STEP_STATUS_TEXT[step.status] ?? step.status}</span>
          {step.step_id === execution.current_step && !isTerminal(execution) && <span className="mw-muted">현재 단계</span>}
          {planStep && stepIsExpensive(planStep) && <span className="mw-badge mw-analysis-expensive">비싼 계산</span>}
        </div>
        <p className="mw-muted mw-mono">시도 {step.attempts}회 · 재시도 {step.retries_used}회
          {step.child_call_ids.length ? ` · 호출 ${step.child_call_ids.join(", ")}` : ""}
          {step.job_id ? ` · 작업 ${step.job_id} (${step.job_status ?? "상태 확인 불가"})` : ""}</p>
        {step.job_ownership === "owned" && <p className="mw-muted">이 실행이 만든 작업입니다 (시작·취소를 이 실행이 맡음).</p>}
        {step.job_ownership === "observed_shared" && <p className="mw-muted" data-analysis-shared-job>같은 호출 키로 이미 있던 작업을 관찰만 합니다.
          이 실행은 그 작업을 시작·재시도·취소하지 않습니다.{step.shared_job_notice ? ` ${step.shared_job_notice}` : ""}</p>}
        {step.job_blocked_reason && <p className="mw-muted">작업 시작 대기 이유: {step.job_blocked_reason}</p>}
        {step.job_cancel_requested && <p className="mw-muted">작업 취소 요청됨 · 종료 확인 중</p>}
        {cleanupPending && <p role="status" className="mw-pocket-notice" data-analysis-cleanup-pending>작업 정리 대기 ({step.job_cleanup_status})</p>}
        {step.deferred_reason && noticeApplies(execution, step.step_id) && <p className="mw-muted">시작 보류: {step.deferred_reason}</p>}
        {step.failure && <p role="alert" className="mw-table-error" data-analysis-step-failure={step.failure.reason_code ?? step.failure.error ?? ""}>
          {step.failure.status ?? "failed"} · {step.failure.error ?? "—"}{step.failure.reason_code ? ` (${step.failure.reason_code})` : ""}: {step.failure.message ?? ""}
          {step.failure.retryable ? " · 재시도 1회 가능" : " · 재시도 불가"}</p>}
        {completed && step.null_result === true && <p role="status" data-analysis-null-result>정상적인 빈 결과 (scientific_null). 실패가 아니며 다음 단계를 계속합니다.</p>}
        {completed && Object.keys(step.outputs).length > 0 && <p className="mw-mono">
          {Object.entries(step.outputs).map(([name, handle]) => `${name} ${handle}`).join(" · ")}</p>}
        {completed && decision.action === "open_here" && decision.view &&
          <Button size="sm" aria-label={`결과 열기 ${step.step_id}`} data-analysis-open-view={decision.view}
            onClick={() => void onOpen(step, decision.view!)}>결과 열기</Button>}
        {completed && decision.action === "open_in_chemical_screen" && onEnterChemical &&
          <Button size="sm" aria-label={`화학 작업 화면에서 열기 ${step.step_id}`} title={decision.reason ?? undefined}
            onClick={onEnterChemical}>화학 작업 화면에서 열기</Button>}
        {completed && decision.action === "open_in_main_screen" && onExitToMain &&
          <Button size="sm" aria-label={`기존 구조 화면에서 열기 ${step.step_id}`} title={decision.reason ?? undefined}
            onClick={onExitToMain}>기존 구조 화면에서 열기</Button>}
        {step.report_handle && <div className="mw-report-downloads" data-analysis-report={step.report_handle}>
          <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, step.report_handle, "markdown")} download>보고서 Markdown 다운로드</a>
          <a className="mw-btn mw-btn--sm" href={api.reportDownload(runId, step.report_handle, "json")} download>보고서 JSON 다운로드</a>
        </div>}
      </li>;
    })}
  </ol>;
}

function SummaryView({ summary }: { summary: AnalysisSummary }) {
  const value = summary.summary;
  return <div className="mw-analysis-summary mw-analysis-measured" aria-label="완료 요약" data-analysis-summary-handle={summary.handle}>
    <p className="mw-mono">{value.schema} · {summary.handle} · 계획 {value.plan_handle} · 승인 이벤트 #{value.approval_event_seq ?? "—"}
      · 이벤트 #{value.first_event_seq ?? "—"}–#{value.last_event_seq ?? "—"} · 물리 시도 {value.physical_attempts}</p>
    <p className="mw-muted">요약은 링크만 담습니다. 과학 수치는 각 보고서의 검증된 필드에서 읽습니다.</p>
    <table className="mw-table"><thead><tr><th>단계</th><th>연산</th><th>빈 결과</th><th>출력</th><th>보고서</th><th>작업</th><th>시도</th></tr></thead>
      <tbody>{value.steps.map(step => <tr key={step.step_id} data-analysis-summary-step={step.step_id}>
        <td>{step.step_id}</td><td className="mw-mono">{step.operation}</td><td>{step.null_result ? "scientific_null" : "아님"}</td>
        <td className="mw-mono">{step.output_handles.map(shortHandle).join(", ")}</td>
        <td className="mw-mono">{step.report_handle ? shortHandle(step.report_handle) : "—"}</td>
        <td className="mw-mono">{step.job_ids.join(", ") || "—"}{step.job_ownership ? ` (${step.job_ownership})` : ""}</td>
        <td>{step.attempts}</td></tr>)}</tbody></table>
  </div>;
}
