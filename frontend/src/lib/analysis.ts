/** M13 analysis workflow panel: pure decisions only (no fetch, no React). See docs/contracts.md (M13). */
import type { AnalysisAction, AnalysisExecution, AnalysisExecutionListRow, AnalysisGoal, AnalysisStepRecord, ResidueRef } from "./contracts";
import type { AtomRefV1 } from "./comparison";

export type AnalysisPanelKind = "main" | "chemical";
export type AnalysisUiState = "loading" | "ready" | "scientific_null" | "failure" | "unavailable";

export const ANALYSIS_GOALS: AnalysisGoal[] = ["inspect_ligand", "measure_atoms", "compare_structures",
  "chemical_interactions", "find_cavities", "minimize_protein"];
export const GOAL_LABELS: Record<AnalysisGoal, string> = {
  inspect_ligand: "리간드 조사", measure_atoms: "원자 거리 측정", compare_structures: "두 구조 비교",
  chemical_interactions: "화학 상호작용", find_cavities: "공동 찾기", minimize_protein: "단백질 최소화" };
export const CHEMICAL_CATEGORIES = ["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"];
export const CONTACT_TYPES = ["contact", "polar_contact", "hydrophobic_contact"];
export const LOCAL_RULES_NOTE = "로컬 규칙으로 만든 계획이며 모델 판단이 아닙니다";
export const DRY_RUN_NOTICE = "연습용 run의 계획은 미리보기 전용입니다. 실행하려면 일반 run에서 같은 입력으로 계획을 다시 만드세요.";
export const EDIT_NEW_PLAN_NOTE = "입력은 계획을 만들 때의 값으로 고정됩니다. 입력을 고치면 새 계획이 되고, 이전 승인은 새 실행에 적용되지 않습니다.";
export const BUSY_TEXT = "다른 요청을 처리 중입니다";
export const MAKE_IN_SCREEN = "기존 화면에서 먼저 만드세요";
export const PLAN_ESTIMATE_NOTE = "계획은 측정 결과가 아닙니다. 비용 표시는 고정 한도와 현재 남은 예산뿐이며 실행 시간·결과를 예측하지 않습니다.";

// ---------------------------------------------------------------------------------------------- placement
export function goalPlacement(panel: AnalysisPanelKind, goal: AnalysisGoal):
  { allowed: boolean; reason: string | null; enterChemical: boolean } {
  if (panel === "main") return goal === "chemical_interactions"
    ? { allowed: false, reason: "화학 작업 화면에서 시작합니다", enterChemical: true }
    : { allowed: true, reason: null, enterChemical: false };
  return goal === "chemical_interactions" || goal === "find_cavities"
    ? { allowed: true, reason: null, enterChemical: false }
    : { allowed: false, reason: "기존 구조 화면(메인 화면)에서 시작합니다", enterChemical: false };
}

export function allowedSourceKinds(panel: AnalysisPanelKind, goal: AnalysisGoal): string[] {
  switch (goal) {
    case "inspect_ligand": return ["structure", "prepared_structure"];
    case "measure_atoms": case "compare_structures": return ["structure", "prepared_structure", "openmm_minimized_structure"];
    case "find_cavities": return panel === "chemical" ? ["chemical_structure"] : ["prepared_structure", "openmm_minimized_structure"];
    case "minimize_protein": return ["prepared_structure"];
    default: return [];
  }
}

// ---------------------------------------------------------------------------------------------- screen import
export interface PreparationPolicy { altloc: "highest_occupancy" | "first"; waters: "strip_all" | "keep_all"; hydrogens: "strip" | "keep" }
export interface ScreenSelections {
  displayedSource: { handle: string; kind: string } | null;
  /** The ligand instance the user explicitly chose on the screen (never the first or only one). */
  ligand: ResidueRef | null;
  ligandSourceHandle: string | null;
  preparation: PreparationPolicy | null;
  cutoff_A: number | null;
  types: string[] | null;
  pocketChains: string[] | null;
  atoms: { source: string; first: AtomRefV1; second: AtomRefV1 } | null;
  comparison: { reference: string; moving: string; pairs: { reference: AtomRefV1; moving: AtomRefV1 }[] } | null;
  chemicalRequest: Record<string, unknown> | null;
  openmmAcknowledged: { protein_only: boolean; rebuild_pH7: boolean } | null;
}

export interface AnalysisDraft {
  goal: AnalysisGoal; panel: AnalysisPanelKind;
  // editable in the panel
  source: string; sourceKind: string | null; ligand: ResidueRef | null;
  preparation: PreparationPolicy; cutoff_A: number; types: string[]; chains: string[];
  proteinOnly: boolean; rebuildH: boolean;
  // read-only: made in the existing screens
  atoms: ScreenSelections["atoms"]; comparison: ScreenSelections["comparison"];
  chemicalRequest: Record<string, unknown> | null;
}

const DEFAULT_PREPARATION: PreparationPolicy = { altloc: "highest_occupancy", waters: "strip_all", hydrogens: "strip" };

export function importDraft(goal: AnalysisGoal, panel: AnalysisPanelKind, screen: ScreenSelections): AnalysisDraft {
  const kinds = allowedSourceKinds(panel, goal);
  let source: { handle: string; kind: string | null } | null =
    screen.displayedSource && kinds.includes(screen.displayedSource.kind) ? screen.displayedSource : null;
  // The two measured atoms carry their own source; they are never re-bound to another structure.
  if (goal === "measure_atoms" && screen.atoms) source = { handle: screen.atoms.source,
    kind: screen.displayedSource?.handle === screen.atoms.source ? screen.displayedSource.kind : null };
  const handle = source?.handle ?? "";
  return { goal, panel, source: handle, sourceKind: source?.kind ?? null,
    ligand: screen.ligand && screen.ligandSourceHandle !== null && screen.ligandSourceHandle === handle ? screen.ligand : null,
    preparation: screen.preparation ?? DEFAULT_PREPARATION,
    cutoff_A: screen.cutoff_A ?? 4, types: screen.types ? [...screen.types] : [...CONTACT_TYPES],
    chains: screen.pocketChains ? [...screen.pocketChains] : [],
    proteinOnly: screen.openmmAcknowledged?.protein_only === true,
    rebuildH: screen.openmmAcknowledged?.rebuild_pH7 === true,
    atoms: screen.atoms, comparison: screen.comparison, chemicalRequest: screen.chemicalRequest };
}

/** The pocket panel's explicit chain selection, imported only for the displayed source of the same run.
 * The panel default (null) or an empty selection imports nothing: no chain is chosen for the user. */
export function importedPocketChains(selection: { runId: string; source: string; chains: string[] | null } | null,
  runId: string | null, displayedHandle: string | null): string[] | null {
  if (!selection || !runId || selection.runId !== runId || !displayedHandle || selection.source !== displayedHandle ||
      !selection.chains?.length) return null;
  return [...new Set(selection.chains)].sort();
}

export interface DraftMapping { inputs: Record<string, unknown> | null; blockers: string[]; missing: string[] }

/** Maps the frozen panel values to the server `inputs`. Blockers disable 계획 만들기; missing items are sent as
 * null/empty so the server records its unmet prerequisite (nothing is substituted). */
export function draftInputs(draft: AnalysisDraft): DraftMapping {
  const blockers: string[] = [], missing: string[] = [];
  const needsSource = draft.goal !== "compare_structures" && draft.goal !== "chemical_interactions";
  if (needsSource && !draft.source) blockers.push("분석할 소스를 고르세요.");
  let inputs: Record<string, unknown> | null = null;
  switch (draft.goal) {
    case "inspect_ligand": {
      if (!Number.isFinite(draft.cutoff_A) || draft.cutoff_A < 2.5 || draft.cutoff_A > 6)
        blockers.push("cutoff는 2.5–6.0 Å이어야 합니다.");
      const types = [...new Set(draft.types)].filter(type => CONTACT_TYPES.includes(type)).sort();
      if (!types.length) blockers.push("접촉 종류를 하나 이상 고르세요.");
      if (!draft.ligand) missing.push("리간드 인스턴스를 고르세요 (자동으로 고르지 않습니다).");
      inputs = { source: draft.source, ...(draft.sourceKind === "structure" ? { preparation: { ...draft.preparation } } : {}),
        ligand: draft.ligand, cutoff_A: draft.cutoff_A, types };
      break;
    }
    case "measure_atoms": {
      const atoms = draft.atoms && draft.atoms.source === draft.source ? draft.atoms : null;
      if (!atoms) missing.push(`원자 두 개: ${MAKE_IN_SCREEN} (원자 거리 측정).`);
      inputs = { source: draft.source, first: atoms?.first ?? null, second: atoms?.second ?? null };
      break;
    }
    case "compare_structures": {
      const comparison = draft.comparison;
      if (!comparison || !comparison.reference || !comparison.moving) {
        blockers.push(`기준·이동 구조: ${MAKE_IN_SCREEN} (두 구조 비교).`);
        break;
      }
      const pairs = comparison.pairs.length >= 3 && comparison.pairs.length <= 1000 ? comparison.pairs : null;
      if (!pairs) missing.push(`CA 대응표(3–1000쌍): ${MAKE_IN_SCREEN} (두 구조 비교).`);
      inputs = { reference: comparison.reference, moving: comparison.moving, pairs };
      break;
    }
    case "chemical_interactions":
      if (!draft.chemicalRequest) missing.push(`준비 요청(미리보기 ready): ${MAKE_IN_SCREEN} (화학 작업 화면 1–2단계).`);
      inputs = { request: draft.chemicalRequest };
      break;
    case "find_cavities":
      if (!draft.chains.length) missing.push("체인을 하나 이상 고르세요 (빈 목록을 전체 체인으로 바꾸지 않습니다).");
      inputs = { source: draft.source, chains: [...new Set(draft.chains)].sort() };
      break;
    case "minimize_protein":
      if (!draft.proteinOnly || !draft.rebuildH) blockers.push("OpenMM 확인 두 개(protein_only, rebuild_pH7)를 체크하세요.");
      inputs = { source: draft.source, selection_policy: "protein_only", hydrogen_policy: "rebuild_pH7" };
      break;
  }
  return { inputs: blockers.length ? null : inputs, blockers, missing };
}

// ---------------------------------------------------------------------------------------------- controls
export type ControlKey = "approve" | "revoke" | "scientific_approval" | "advance" | "retry" | "cancel";
export interface ControlState { visible: boolean; enabled: boolean; reason: string | null }
type RecordView = Pick<AnalysisExecution, "status" | "dry_run" | "retryable_step" | "current_step" | "plan_approval" |
  "scientific_approval" | "driver" | "recovery_pending"> & { steps: Partial<AnalysisStepRecord>[] };

const ENDED_JOB = new Set(["done", "failed", "cancelled", "interrupted"]);

export function isTerminal(record: Pick<AnalysisExecution, "status" | "retryable_step">): boolean {
  return record.status === "complete" || record.status === "cancelled" || record.status === "blocked" ||
    (record.status === "failed" && !record.retryable_step);
}

function currentStep(record: RecordView): Partial<AnalysisStepRecord> | null {
  return record.steps.find(step => step.step_id === record.current_step) ??
    record.steps.find(step => step.status === "waiting_job" || step.status === "dispatched") ?? null;
}

function advanceReason(record: RecordView): string | null {
  switch (record.status) {
    case "ready": return null;
    case "awaiting_approval": return "먼저 계획을 승인하세요.";
    case "awaiting_scientific_approval": return "작업 시작에 계산 승인이 필요합니다. 먼저 계산 승인을 누르세요.";
    case "failed": return "실패한 단계를 재시도하거나 중지하세요.";
    case "waiting_job": {
      const step = currentStep(record);
      if (record.recovery_pending || (step?.job_status && ENDED_JOB.has(step.job_status))) return null;
      return step?.job_ownership === "observed_shared"
        ? "공유 작업이 끝나기를 기다리는 중입니다. 끝나면 다음 단계 실행으로 결과를 기록합니다."
        : "작업이 진행 중입니다. 끝나면 다음 단계 실행으로 결과를 기록합니다.";
    }
    case "executing": return record.recovery_pending ? null : "단계를 실행하는 중입니다.";
    default: return "진행할 수 없는 상태입니다.";
  }
}

export function executionControls(record: RecordView, opts: { busy: boolean; busyAction?: AnalysisAction | null }):
  Record<ControlKey, ControlState> {
  const terminal = isTerminal(record);
  const dry = record.dry_run || record.status === "plan_only";
  const localBusy = opts.busy ? "요청을 처리하는 중입니다." : null;
  const driverBusy = record.driver.in_progress ? `${BUSY_TEXT}. 잠시 뒤 다시 읽거나 누르세요.` : null;
  const ended = terminal ? "종료된 실행입니다. 새 실행을 만드세요." : null;
  const gate = (reason: string | null): ControlState => ({ visible: true, enabled: reason === null, reason });
  const approve = gate(dry ? DRY_RUN_NOTICE : ended ?? localBusy ??
    (record.status === "awaiting_approval" ? null : record.plan_approval.approved ? "이미 승인한 계획입니다." : "승인할 수 없는 상태입니다."));
  // Revoke, like Stop, is never refused as busy (server rule); only a revoke already in flight disables it.
  const revoke = gate(dry ? DRY_RUN_NOTICE : ended ?? (opts.busy && opts.busyAction === "revoke" ? "승인 철회 요청을 처리하는 중입니다." : null) ??
    (record.plan_approval.approved ? null : "승인한 계획이 없습니다."));
  const advance = gate(dry ? DRY_RUN_NOTICE : ended ?? localBusy ?? driverBusy ?? advanceReason(record));
  const retryVisible = record.status === "failed" && !!record.retryable_step;
  const retry = { ...gate(dry ? DRY_RUN_NOTICE : localBusy ?? driverBusy ?? (retryVisible ? null : "재시도할 수 있는 단계가 없습니다.")),
    visible: retryVisible };
  const scientificVisible = record.scientific_approval.state === "pending" || record.status === "awaiting_scientific_approval";
  const scientific_approval = { ...gate(dry ? DRY_RUN_NOTICE : ended ?? localBusy ??
    (scientificVisible ? null : "대기 중인 계산 승인 요청이 없습니다.")), visible: scientificVisible && !dry };
  // Stop is never refused as busy (server rule); only a Stop already in flight disables it.
  const cancel = gate(ended ?? (opts.busy && opts.busyAction === "cancel" ? "중지 요청을 처리하는 중입니다." : null));
  return { approve, revoke, advance, retry, scientific_approval, cancel };
}

export function approvalDisplay(record: Pick<AnalysisExecution, "status" | "plan_approval" | "scientific_approval">) {
  const plan = record.plan_approval.approved
    ? { state: "approved" as const, text: `계획 승인됨 (이벤트 #${record.plan_approval.event_seq ?? "?"})` }
    : { state: "not_approved" as const, text: record.plan_approval.revocations.length ? "계획 승인 철회됨 · 승인 대기" : "계획 승인 대기" };
  const sci = record.scientific_approval;
  const scientific = sci.state === "not_required" ? { state: "not_required" as const, text: "계산 승인 필요 없음 (작업 단계 없음)" }
    : sci.state === "already_approved_in_run" ? { state: "already_approved_in_run" as const, text: "이 run에서 이미 계산 승인됨" }
      : sci.state === "pending" ? { state: "pending" as const, text: `계산 승인 대기${sci.pending_tool ? ` · ${sci.pending_tool}` : ""}` }
        : { state: "not_yet_requested" as const, text: "계산 승인 아직 요청되지 않음 (작업 시작 때 요청)" };
  return { plan, scientific };
}

// ---------------------------------------------------------------------------------------------- requests
export interface PendingRequest { key: string; requestId: string }
export type FailureKind = "ok" | "stale_revision" | "busy" | "request_id_conflict" | "refusal" | "transport";

export function requestKey(action: AnalysisAction | "create_plan" | "create_execution", scope: string,
  body: Record<string, unknown>): string {
  return JSON.stringify([action, scope, Object.keys(body).sort().map(key => [key, body[key]])]);
}

/** The same UUID for the same action body (re-send after a transport failure); a new UUID otherwise. */
export function requestIdFor(pending: PendingRequest | null, key: string, fresh: () => string): PendingRequest {
  return pending && pending.key === key ? pending : { key, requestId: fresh() };
}

/** Only a lost response keeps the request id: any typed answer settled that request. */
export function keepRequestAfter(kind: FailureKind): boolean { return kind === "transport"; }

export function classifyFailure(error: { status?: number; code?: string }): Exclude<FailureKind, "ok"> {
  if (error.code === "stale_revision") return "stale_revision";
  if (error.code === "busy") return "busy";
  if (error.code === "request_id_conflict") return "request_id_conflict";
  if (typeof error.status === "number" && error.code) return "refusal";
  if (typeof error.status === "number" && error.status >= 400 && error.status < 500) return "refusal";
  return "transport";
}

export function stopResend(kind: FailureKind, resends: number): boolean { return kind === "stale_revision" && resends < 1; }

export function executionProgressed(before: Pick<AnalysisExecution, "execution_id" | "revision" | "status">,
  after: Pick<AnalysisExecution, "execution_id" | "revision" | "status" | "driver">): boolean {
  if (before.execution_id !== after.execution_id) return false;
  return after.revision > before.revision || after.status !== before.status || after.driver.in_progress;
}

export interface PanelStamp { runId: string; executionId: string | null; action: number }
export function responseCurrent(captured: PanelStamp, live: PanelStamp, mounted: boolean): boolean {
  return mounted && captured.runId === live.runId && captured.executionId === live.executionId && captured.action === live.action;
}
export function hostRequestAccepted(request: { runId: string }, host: { runId: string | null }): boolean {
  return host.runId !== null && request.runId === host.runId;
}
/** A created (or replayed) execution becomes the panel's execution: its own response must still count as current. */
export function adoptExecution(captured: PanelStamp, executionId: string): PanelStamp {
  return { ...captured, executionId };
}

/** Plan selection is separate from the open execution: a new or reopened plan is shown with 실행 만들기. */
export type PlanFocus = "plan" | "execution";
export function planView<P>(input: { plan: P | null; executionId: string | null; executionPlan: P | null; focus: PlanFocus }):
  { shownPlan: P | null; createExecution: boolean } {
  const planFocused = !!input.plan && (input.focus === "plan" || !input.executionId);
  return { shownPlan: planFocused ? input.plan : input.executionId ? input.executionPlan : input.plan,
    createExecution: planFocused };
}

/** A mutation that moved the same execution's record may have created objects (the host re-reads its event log). */
export function objectsMayHaveChanged(before: Pick<AnalysisExecution, "execution_id" | "revision">,
  after: Pick<AnalysisExecution, "execution_id" | "revision"> | null): boolean {
  return !!after && after.execution_id === before.execution_id && after.revision > before.revision;
}
/** Of two reads of the append-only event log, the longer one is newer; a late shorter read is discarded. */
export function newerEventLog<T>(previous: T[], next: T[]): T[] { return next.length >= previous.length ? next : previous; }

/** Read-only polling: while a step or job runs, and while this panel's own Advance/Retry runs inside its request. */
export function pollNeeded(record: Pick<AnalysisExecution, "status" | "driver"> | null, busy: string | null): boolean {
  if (!record) return false;
  return record.status === "executing" || record.status === "waiting_job" || record.driver.in_progress ||
    busy === "advance" || busy === "retry";
}
export function acceptPolled(shown: Pick<AnalysisExecution, "execution_id" | "revision"> | null,
  polled: Pick<AnalysisExecution, "execution_id" | "revision">): boolean {
  return !shown || (shown.execution_id === polled.execution_id && polled.revision >= shown.revision);
}

/** A step-bound notice (record notice, 시작 보류) applies only to the current step while it is not completed. */
export function noticeApplies(record: Pick<AnalysisExecution, "current_step"> & { steps: Partial<AnalysisStepRecord>[] },
  stepId: string | null | undefined): boolean {
  if (!stepId) return true;
  const step = record.steps.find(item => item.step_id === stepId);
  return !!step && step.status !== "completed" && stepId === record.current_step;
}

// ---------------------------------------------------------------------------------------------- display
export function analysisUiState(input: { available: boolean; templateAvailable?: boolean; reading?: boolean;
  pending?: boolean; readError?: string | null; record?: { status: string; steps: Partial<AnalysisStepRecord>[] } | null }):
  AnalysisUiState {
  if (!input.available || input.templateAvailable === false) return "unavailable";
  if (input.readError) return "failure";
  if (input.reading || input.pending) return "loading";
  const record = input.record;
  if (!record) return "ready";
  if (record.status === "executing" || record.status === "waiting_job") return "loading";
  if (record.status === "failed" || record.status === "blocked") return "failure";
  if (record.steps.some(step => step.status === "completed" && step.null_result === true)) return "scientific_null";
  return "ready";
}

export type ResultView = "contacts" | "sasa" | "measurement" | "pocket" | "openmm" | "chemical" | "structure";
const OPERATION_VIEW: Record<string, ResultView> = { prepare_structure: "structure", compute_interactions: "contacts",
  compute_interface_sasa: "sasa", measure_distance: "measurement", align_structures: "measurement",
  fpocket_detect_v1: "pocket", openmm_protein_minimize: "openmm", prolif_prepare_v1: "chemical", prolif_detect_v1: "chemical" };

export function resultOpenDecision(panel: AnalysisPanelKind, goal: AnalysisGoal, sourceKind: string | null, operation: string):
  { action: "open_here" | "open_in_chemical_screen" | "open_in_main_screen" | "none"; view: ResultView | null;
    label: string | null; reason: string | null } {
  const view = OPERATION_VIEW[operation] ?? null;
  if (!view) return { action: "none", view: null, label: null, reason: null };
  const chemicalContext = goal === "chemical_interactions" || sourceKind === "chemical_structure";
  if (chemicalContext && panel === "main") return { action: "open_in_chemical_screen", view, label: "화학 작업 화면에서 열기",
    reason: "화학 구조 결과는 화학 작업 화면에서만 열 수 있습니다." };
  if (!chemicalContext && panel === "chemical") return { action: "open_in_main_screen", view, label: "기존 구조 화면에서 열기",
    reason: "이 결과는 기존 구조 화면(메인 화면)에서 엽니다." };
  return { action: "open_here", view, label: "결과 열기", reason: null };
}

export function stepIsExpensive(step: { lane: string }): boolean { return step.lane === "durable_job"; }

const OUTCOME_TEXT: Record<string, string> = {
  advanced: "한 단계를 진행했습니다.", created: "실행을 만들었습니다.", approved: "계획 승인을 기록했습니다.",
  revoked: "승인을 철회했습니다.", cancelled: "이 실행을 중지했습니다.", already_terminal: "이미 종료된 실행입니다.",
  interrupted: "중단을 기록했습니다.", run_busy: "run이 다른 작업을 처리 중이라 시작하지 않았습니다. 잠시 뒤 다시 실행하세요.",
  retry_or_stop_required: "실패한 단계를 재시도하거나 중지해야 합니다.", retry_not_allowed: "이 단계는 재시도할 수 없습니다.",
  resource_exceeded: "실행 한도를 넘어 시작하지 않았습니다.", blocked: "실행이 차단되었습니다. 새 계획을 만드세요.",
  scientific_approval: "계산 승인을 기록했습니다.", recorded: "계산 승인을 기록했습니다." };

export function outcomeText(outcome: string): string {
  if (OUTCOME_TEXT[outcome]) return OUTCOME_TEXT[outcome];
  if (outcome.startsWith("no_op_")) return `지금 진행할 단계가 없어 아무것도 실행하지 않았습니다 (상태 ${outcome.slice(6)}).`;
  return outcome;
}

// ---------------------------------------------------------------------------------------------- history list
/** An execution history row: an unreadable record is an error row with its reason and no reopen action. */
export function historyRowView(row: Pick<AnalysisExecutionListRow, "status" | "error">):
  { kind: "ok" | "error"; reopen: boolean; error: string | null } {
  if (row.error) return { kind: "error", reopen: false, error: `${row.error.message} (${row.error.code})` };
  if (row.status === null) return { kind: "error", reopen: false, error: "실행 기록을 읽을 수 없습니다." };
  return { kind: "ok", reopen: true, error: null };
}

/** Rows are capped by the backend; say so when fewer rows than executions are listed. */
export function historyCapNote(shown: number, total: number): string | null {
  return shown < total ? `최근 ${shown}개만 표시합니다 (전체 ${total}개).` : null;
}
