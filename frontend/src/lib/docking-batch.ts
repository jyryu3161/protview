/**
 * Pure logic of the M19 batch docking area of the "리간드 설계·탐색" tab (`.dryforge/spec.md` sections 3, 4.3, 4.4,
 * 5.4, 5.5, 6, 9).
 *
 * Every score, count, budget figure and sentence shown comes from the server (the stored `docking_batch_result@1`, its
 * per-row `docking_result@1`, the preflight read or the job record); this module never computes a score or an
 * aggregate. It decides the exact job-argument shape, the parent-row and limit-approval rules, the display order of the
 * table (the order is only a display order: rows without a score stay last and are never treated as 0), wording
 * ("한국어 (code)") and the one-job-at-a-time rule. M18 rules and texts are reused from `lib/docking.ts`.
 */
import type { DockingBatchArgs, DockingBatchPreflight, DockingBatchProgress, DockingBatchRowState,
  DockingBatchStatus, DockingBatchStopReason, DockingMode } from "./contracts";
import { type ArgsCheck, DOCKING_LIMITATIONS, dockingArgs, dockingCapabilityText, dockingFailureText,
  dockingForbiddenWords, dockingJobPhase, dockingReasonText, dockingRefusalList, type DockingForm,
  type DockingRefusalList, initialDockingForm, patchDockingForm, SCORE_COLUMN_LABEL, scoreText } from "./docking";
import { decimalHalfUp } from "./site-annotation";

export { SCORE_COLUMN_LABEL };

// ---- closed sets and limits (same values and order as backend/mw/docking_batch_constants.py; tests compare) ----
export const BATCH_PROTOCOL = "qvina_batch_dock_v1";
export const BATCH_TOOL = "qvina_dock_batch";
export const MAX_CANDIDATES = 50;
export const PER_CANDIDATE_S = 300;
export const TOTAL_S = 7200;
/** Fixed `POST /jobs` time limit of a batch job (the protocol's own maximum; not a job argument, not shown). */
export const BATCH_TIMEOUT_S = 7800;
export const ROW_KINDS = ["parent", "candidate"] as const;
export const ROW_STATES: readonly DockingBatchRowState[] = ["scored", "null_result", "failed", "cancelled", "not_run"];
export const BATCH_STATUSES: readonly DockingBatchStatus[] = ["complete", "partial"];
export const STOP_REASONS: readonly DockingBatchStopReason[] = ["cancelled", "time_exhausted", "worker_failed",
  "resource_exceeded"];
export const ADMISSION_REASONS = ["batch_empty", "batch_too_large", "batch_parent_not_allowed",
  "batch_limit_raise_required"] as const;
export const ROW_ONLY_REASONS = ["candidate_timeout", "time_exhausted", "cancelled", "worker_failed"] as const;

// ---- fixed wording ----
/** Score target of each row: the first row of its per-row result (server string; shown, never computed). */
export const SCORE_ROW_LABELS: Record<DockingMode, string> = { free: "모드 1(엔진 출력 순서)",
  core_fixed: "샘플 1(점수 오름차순 나열)" };
/** spec 5.4, verbatim: B1 always, B2 when partial, B3 with the parent row. The screen shows stored ids' texts. */
export const BATCH_STATEMENTS = {
  B1: "이 일괄의 모든 행은 같은 수용체·상자·seed·방식·값으로 계산되어 점수를 같은 표에서 나란히 볼 수 있으며, " +
    "표의 정렬은 표시 순서일 뿐 순위가 아니다.",
  B2: "이 일괄은 일부만 계산되었다. 계산하지 않은 행은 점수가 없으며 0이 아니다.",
  B3: "부모 행은 후보와 같은 설정으로 도킹한 기준 입력이며, 점수 차이를 개선이나 악화로 해석하지 않는다.",
} as const;
export const PARENT_ROW_LABEL = "부모(기준 입력)";
export const REUSED_LABEL = "저장된 결과 재사용";
export const LIMIT_RAISE_LABEL = "이 일괄에 필요한 만큼 한도를 올림";
export const WAIT_NOTE = "일괄이 도는 동안(최대 약 2시간) 이 run의 다른 계산·보고서 호출과 다른 비싼 작업이 기다린다.";
export const PARTIAL_RISK_NOTE = "2시간 안에 못 끝나면 끝낸 후보만 남음 (새로 계산할 행 × 300초가 7200초를 넘음).";

export function chargeNote(units: number): string {
  return `시작하면 ${units}단위가 소진되고 중간에 멈춰도 돌려받지 않음`;
}

// ---- reasons, states, status ----

/** Korean names of the reasons M19 adds (spec 5.5); every other code uses the M18 names. */
export const BATCH_REASON_LABEL: Record<string, string> = {
  batch_empty: "후보를 하나도 고르지 않음",
  batch_too_large: `후보 수 상한(${MAX_CANDIDATES}개) 초과`,
  batch_parent_not_allowed: "부모 기준 행은 자유 도킹에서만 쓸 수 있음(부모에는 고정할 코어가 없음)",
  batch_limit_raise_required: "이 일괄에 필요한 예산이 남은 예산보다 큼(한도 증액 승인 필요)",
  candidate_timeout: `한 행의 시간 상한(${PER_CANDIDATE_S}초) 초과`,
  time_exhausted: `일괄 전체 시간 상한(${TOTAL_S}초) 소진`,
  cancelled: "사용자 취소",
  worker_failed: "작업 프로세스 중단",
};

/** "한국어 (code)"; M18 codes keep their M18 names; unknown codes are shown as is. */
export function batchReasonText(code: string): string {
  const label = Object.prototype.hasOwnProperty.call(BATCH_REASON_LABEL, code) ? BATCH_REASON_LABEL[code] : undefined;
  return label ? `${label} (${code})` : dockingReasonText(code);
}

export const ROW_STATE_TEXT: Record<DockingBatchRowState, string> = { scored: "점수 있음", null_result: "빈 과학 결과(모드 0개)",
  failed: "실패", cancelled: "중단됨", not_run: "계산하지 않음" };

export function rowStateText(state: DockingBatchRowState): string { return `${ROW_STATE_TEXT[state]} (${state})`; }

/** "완료 (complete)" or "부분 완료 (partial) · 멈춘 이유: …". */
export function batchStatusText(summary: { status: DockingBatchStatus; stop_reason: DockingBatchStopReason | null }): string {
  if (summary.status === "complete") return "완료 (complete)";
  return `부분 완료 (partial) · 멈춘 이유: ${summary.stop_reason ? batchReasonText(summary.stop_reason) : "기록 없음"}`;
}

/** B2 above the table of a partial batch (the server's text when a detail is loaded, else the local copy); null
 * otherwise. */
export function partialStatement(summary: { status: DockingBatchStatus },
  statements?: { batch: { id: string; text: string }[] } | null): string | null {
  if (summary.status !== "partial") return null;
  return statements?.batch.find(item => item.id === "B2")?.text ?? BATCH_STATEMENTS.B2;
}

// ---- table rows (display only; stored values) ----

export interface BatchRowLike { row_index: number; kind: "parent" | "candidate"; candidate_id: string | null;
  state: DockingBatchRowState; reason_code: string | null; result_handle: string | null; score_kcal_mol: number | null;
  score_row_label: string | null }

export function rowCandidateText(row: Pick<BatchRowLike, "kind" | "candidate_id">): string {
  return row.kind === "parent" || row.candidate_id === null ? PARENT_ROW_LABEL : row.candidate_id;
}

function hasScore(row: Pick<BatchRowLike, "state" | "score_kcal_mol">): boolean {
  return row.state === "scored" && typeof row.score_kcal_mol === "number";
}

/** Stored score with one decimal for `scored` rows; empty for every other state (never "0"). */
export function rowScoreText(row: Pick<BatchRowLike, "state" | "score_kcal_mol">): string {
  return hasScore(row) ? scoreText(row.score_kcal_mol as number) : "";
}

export function rowScoreTargetText(row: Pick<BatchRowLike, "state" | "score_row_label">): string {
  return row.state === "scored" && row.score_row_label ? row.score_row_label : "";
}

export function rowReasonText(row: Pick<BatchRowLike, "reason_code">): string {
  return row.reason_code ? batchReasonText(row.reason_code) : "";
}

export function reusedText(reused: boolean): string { return reused ? REUSED_LABEL : ""; }

/** "상세 열기" opens the stored M18 result; rows without a per-row result handle have none. */
export function rowDetailAvailable(row: Pick<BatchRowLike, "result_handle">): boolean {
  return typeof row.result_handle === "string" && row.result_handle.length > 0;
}

export type BatchSortKey = "row" | "candidate" | "score";
export type BatchSort = { key: BatchSortKey; direction: "asc" | "desc" } | null;

/**
 * Display order. null = batch row order. Row number and candidate id sort both ways; the score sort orders `scored`
 * rows by the stored score, and rows without a score (any other state) stay last in row order whatever the direction,
 * never compared as 0. The parent row has no candidate id and stays last in a candidate id sort. Ties keep row order.
 * Returns a new array; the rows themselves are not changed.
 */
export function sortBatchRows<T extends BatchRowLike>(rows: readonly T[], sort: BatchSort): T[] {
  const byRow = [...rows].sort((a, b) => a.row_index - b.row_index);
  if (sort === null || (sort.key === "row" && sort.direction === "asc")) return byRow;
  if (sort.key === "row") return byRow.reverse();
  const sign = sort.direction === "asc" ? 1 : -1;
  const valued = sort.key === "score" ? (row: T) => hasScore(row) : (row: T) => row.candidate_id !== null;
  const compare = sort.key === "score"
    ? (a: T, b: T) => (a.score_kcal_mol as number) - (b.score_kcal_mol as number)
    : (a: T, b: T) => (a.candidate_id as string) < (b.candidate_id as string) ? -1
      : (a.candidate_id as string) > (b.candidate_id as string) ? 1 : 0;
  const head = byRow.filter(valued), tail = byRow.filter(row => !valued(row));
  return [...head.sort((a, b) => sign * compare(a, b) || a.row_index - b.row_index), ...tail];
}

/** Header click: a new column starts ascending; the same column toggles its direction. */
export function nextBatchSort(current: BatchSort, key: BatchSortKey): BatchSort {
  if (current && current.key === key) return { key, direction: current.direction === "asc" ? "desc" : "asc" };
  return { key, direction: "asc" };
}

export function ariaSort(sort: BatchSort, key: BatchSortKey): "ascending" | "descending" | "none" {
  return sort && sort.key === key ? sort.direction === "asc" ? "ascending" : "descending" : "none";
}

// ---- inputs ----

/** Why the parent baseline row cannot be chosen (null = usable): free docking only, no number shown. */
export function parentDisabledReason(mode: DockingMode | null): string | null {
  if (mode === null) return "방식을 먼저 고르세요(부모 기준 행은 자유 도킹에서만 씁니다).";
  if (mode === "core_fixed") return `코어 고정에서는 부모 기준 행을 쓸 수 없습니다: ${batchReasonText("batch_parent_not_allowed")}`;
  return null;
}

/** Chosen candidates: id -> generation order (the candidate-set order, read from the server rows). */
export type CandidateSelection = Record<string, number>;

export function candidateSelectable(selection: CandidateSelection, id: string): boolean {
  return Object.prototype.hasOwnProperty.call(selection, id) || Object.keys(selection).length < MAX_CANDIDATES;
}

/** Checks or unchecks one candidate; a check beyond the cap changes nothing. */
export function toggleCandidate(selection: CandidateSelection, id: string, generationOrder: number,
  checked: boolean): CandidateSelection {
  if (!checked) {
    const next = { ...selection };
    delete next[id];
    return next;
  }
  if (!candidateSelectable(selection, id)) return selection;
  return { ...selection, [id]: generationOrder };
}

/** The chosen ids in candidate-set order (never click order). */
export function orderedCandidateIds(selection: CandidateSelection): string[] {
  return Object.entries(selection).sort((a, b) => a[1] - b[1] || (a[0] < b[0] ? -1 : 1)).map(([id]) => id);
}

export function selectionCountText(count: number): string { return `선택 ${count} / ${MAX_CANDIDATES}`; }

/** The M18 form fields the batch shares (the ligand source is always the candidate source) plus the batch choices. */
export interface BatchForm extends DockingForm { candidateOrder: CandidateSelection; includeParent: boolean }

export function initialBatchForm(): BatchForm {
  return { ...initialDockingForm(), ligandSource: "candidate", candidateOrder: {}, includeParent: false };
}

/**
 * The M18 edit rules (`patchDockingForm`) plus: a new candidate set clears the chosen candidates, and core-fixed
 * mode clears the parent row (it is then disabled with its reason). Nothing is chosen automatically in their place.
 */
export function patchBatchForm(form: BatchForm, patch: Partial<BatchForm>): BatchForm {
  const next: BatchForm = { ...form, ...patchDockingForm(form, patch), candidateOrder: patch.candidateOrder ??
    form.candidateOrder, includeParent: patch.includeParent ?? form.includeParent, ligandSource: "candidate" };
  if (next.candidateSetHandle !== form.candidateSetHandle && !("candidateOrder" in patch)) next.candidateOrder = {};
  if (next.mode !== "free" && next.includeParent) next.includeParent = false;
  return next;
}

const NO_CANDIDATE = "후보를 고르세요.";

/**
 * The `qvina_batch_dock_v1` arguments exactly as `docking_batch_inputs.validate_arguments` accepts them: the M18
 * fields checked by `dockingArgs` (one candidate stands in for the shared checks), no `ligand` key, the candidate
 * set and parent SDF, the chosen ids in set order and `include_parent`. The server checks everything again.
 */
export function batchArgs(form: BatchForm): ArgsCheck<DockingBatchArgs> {
  const ids = orderedCandidateIds(form.candidateOrder);
  const shared = dockingArgs({ ...form, ligandSource: "candidate", sdfHandle: null, candidateId: ids[0] ?? null });
  const errors = shared.ok ? [] : shared.errors.filter(text => text !== NO_CANDIDATE);
  if (!ids.length) errors.push(`후보를 1개 이상 고르세요 (batch_empty).`);
  if (ids.length > MAX_CANDIDATES) errors.push(`후보는 ${MAX_CANDIDATES}개까지 고를 수 있습니다 (batch_too_large).`);
  if (form.includeParent && form.mode === "core_fixed") errors.push(`${batchReasonText("batch_parent_not_allowed")}.`);
  if (errors.length || !shared.ok) return { ok: false, errors };
  const { ligand, ...rest } = shared.args;
  if (ligand.source !== "candidate") return { ok: false, errors: ["리간드 출처가 후보가 아닙니다."] };
  return { ok: true, args: { ...rest, candidate_set_handle: ligand.candidate_set_handle,
    parent_sdf_handle: ligand.parent_sdf_handle, candidate_ids: ids, include_parent: form.includeParent } };
}

/** Identity of one argument set: a preflight answer applies only to the exact arguments it was asked for. */
export function batchArgsKey(args: DockingBatchArgs): string { return JSON.stringify(args); }

// ---- preflight and limit approval (server numbers, shown as given) ----

function secondsText(value: number): string { return `${decimalHalfUp(value, 1)}초`; }

function pairText(pair: { expensive_calls: number; wall_clock_s: number }): string {
  return `비싼 계산 ${pair.expensive_calls}단위 · 활동 시간 ${secondsText(pair.wall_clock_s)}`;
}

/** Admitted preflight with a shortfall on either axis, outside dry-run: the explicit approval button is shown. */
export function limitApprovalOffered(preflight: DockingBatchPreflight | null, dryRun: boolean): boolean {
  if (!preflight || dryRun || !preflight.admission.admitted || !preflight.shortfall) return false;
  return preflight.shortfall.expensive_calls > 0 || preflight.shortfall.wall_clock_s > 0;
}

function hasShortfall(preflight: DockingBatchPreflight): boolean {
  return !!preflight.shortfall && (preflight.shortfall.expensive_calls > 0 || preflight.shortfall.wall_clock_s > 0);
}

/** [label, value] lines of an admitted preflight (empty for a refused one). Every number is the server's. */
export function preflightLines(preflight: DockingBatchPreflight): [string, string][] {
  if (!preflight.admission.admitted || preflight.new_dockings === null || !preflight.needed || !preflight.shortfall)
    return [];
  const lines: [string, string][] = [
    ["새로 계산할 행", `${preflight.new_dockings}개`],
    ["재사용", `${REUSED_LABEL} ${preflight.reused_rows ?? 0}개 (과금하지 않음)`],
    ["필요", `${pairText(preflight.needed)} (최대)`],
    ["현재 잔여", pairText(preflight.remaining)],
    ["부족분", pairText(preflight.shortfall)],
    ["과금", chargeNote(preflight.new_dockings)],
  ];
  if (preflight.full_batch_may_be_partial) lines.push(["시간 상한", PARTIAL_RISK_NOTE]);
  lines.push(["대기", WAIT_NOTE]);
  return lines;
}

export function preflightRefusalText(preflight: DockingBatchPreflight): string {
  const admission = preflight.admission;
  const head = admission.reason_code ? batchReasonText(admission.reason_code) : admission.error ?? "거절";
  return `${head}${admission.message ? ` · ${admission.message}` : ""}`;
}

/** Receptor leftovers of a refused preflight (M18 rule: items with seven residue fields and the total), else null. */
export function preflightRefusalList(preflight: DockingBatchPreflight): DockingRefusalList | null {
  if (preflight.admission.admitted) return null;
  return dockingRefusalList(preflight.admission.reason_code, preflight.admission.detail);
}

export function existingJobText(existing: { job_id: string; status: string }): string {
  return `같은 입력의 일괄 작업이 이미 있습니다 · ${existing.job_id} · ${existing.status}. 시작하면 새 작업을 만들지 않고 그 작업을 ` +
    "다시 표시합니다.";
}

export function limitApprovalText(result: { raised: boolean; increase: { expensive_calls: number; wall_clock_s: number };
  limits_after: { expensive_calls: number; wall_clock_s: number } }): string {
  if (!result.raised) return "이미 충분해 한도를 바꾸지 않았습니다.";
  return `한도를 올렸습니다 · 증가분 ${pairText(result.increase)} · 새 한도 ${pairText(result.limits_after)} ` +
    "(되돌리지 않음, run 끝까지 유지)";
}

// ---- jobs ----

const ACTIVE_STATUSES = ["queued", "claimed", "running"];

export type BatchPreflightState = { key: string; value: DockingBatchPreflight } | null;

/** One job at a time; start needs an admitted preflight of exactly these arguments without a shortfall (dry-run plans). */
export function batchStartBlockedReason(input: { capability: { available: boolean; reason: string | null;
  reason_code: string | null } | null | undefined; busy: boolean; activeJob: { status: string } | null;
  check: ArgsCheck<DockingBatchArgs>; preflight: BatchPreflightState; dryRun: boolean }): string | null {
  if (!input.capability?.available) return dockingCapabilityText(input.capability ?? null);
  if (input.busy) return "요청을 처리하는 중입니다.";
  if (input.activeJob && ACTIVE_STATUSES.includes(input.activeJob.status))
    return "진행 중인 작업이 끝난 뒤 시작할 수 있습니다(한 번에 한 작업).";
  if (!input.check.ok) return input.check.errors.join(" ");
  if (!input.preflight || input.preflight.key !== batchArgsKey(input.check.args))
    return "지금 입력으로 \"시작 전 확인 보기\"를 먼저 누르세요.";
  if (!input.preflight.value.admission.admitted) return preflightRefusalText(input.preflight.value);
  if (!input.dryRun && hasShortfall(input.preflight.value))
    return "예산이 부족합니다. 한도를 먼저 올리고 시작 전 확인을 다시 보세요 (batch_limit_raise_required).";
  return null;
}

/**
 * A failed or interrupted job that still published a summary (e.g. stopped at the job deadline) shows the job record
 * status with the summary's own outcome (server values), never a bare failure message.
 */
export function batchJobText(job: { status: string; cancel_requested: boolean; failure: Parameters<typeof dockingFailureText>[0];
  batch?: Pick<DockingBatchProgress, "summary_handle" | "summary_status" | "summary_stop_reason"> | null } | null,
  approvalPending: boolean): string {
  switch (dockingJobPhase(job, approvalPending)) {
    case "none": return "일괄 작업 없음";
    case "saved": return "일괄 작업이 저장되었습니다. 시작을 누르면 실제 계산이 실행됩니다.";
    case "awaiting_approval": return "비용이 드는 실제 계산 승인이 필요합니다(run의 첫 비싼 계산). 승인한 뒤 시작을 다시 누르세요.";
    case "running": return `일괄 작업 실행 중${job?.cancel_requested ? " · 취소 요청됨" : ""}`;
    case "done": return "일괄 작업 끝남";
    case "cancelled": return "일괄 작업 취소됨 (끝낸 행은 보관, 요약이 있으면 아래 목록에 나옴)";
    default:
      if (job && ["failed", "interrupted"].includes(job.status) && job.batch?.summary_handle && job.batch.summary_status)
        return `일괄 작업 끝남 · 작업 기록 ${job.status} · 일괄 요약 ${batchStatusText({ status: job.batch.summary_status,
          stop_reason: job.batch.summary_stop_reason })}`;
      return job && ["failed", "interrupted"].includes(job.status) ? `일괄 작업 실패: ${dockingFailureText(job.failure)}`
        : `일괄 작업 실패: 알 수 없는 작업 상태 (${job?.status})`;
  }
}

/** Progress from the stored job record (status files of the attempt; reused rows are not run). */
export function batchProgressText(progress: DockingBatchProgress): string {
  const reused = progress.reused_rows.length;
  return `새로 계산하는 행 ${progress.rows - reused}개 중 상태가 기록된 행 ${progress.finished_rows}개 · ${REUSED_LABEL} ${reused}행`;
}

export function batchApprovalRequired(status: number, approval: { gate: string; tool: string } | undefined): boolean {
  return status === 409 && approval?.gate === "expensive_first_call" && approval.tool === BATCH_TOOL;
}

/** The batch job of this run that is still queued or running (the latest one), for re-attaching after a remount. */
export function batchActiveJob<T extends { run_id: string; protocol_id: string; status: string }>(jobs: unknown,
  runId: string): T | null {
  if (!Array.isArray(jobs)) return null;
  return (jobs as T[]).filter(job => job && job.run_id === runId && job.protocol_id === BATCH_PROTOCOL &&
    ACTIVE_STATUSES.includes(job.status)).at(-1) ?? null;
}

export function batchReportMatches(artifact: { manifest: { schema: string; analysis_type: string; result_handle: string } },
  summaryHandle: string): boolean {
  return artifact.manifest.schema === "method_report_manifest@1" && artifact.manifest.analysis_type === "ligand_docking_batch" &&
    artifact.manifest.result_handle === summaryHandle;
}

/** One stored summary in the list (or why it cannot be read). */
export function batchListRowText(row: { published_seq: number; valid: boolean; reason_code: string | null;
  mode: DockingMode | null; status: DockingBatchStatus | null; stop_reason: DockingBatchStopReason | null;
  include_parent: boolean | null; counts: Record<string, number> | null }): string {
  if (!row.valid || !row.status || !row.counts)
    return `게시 순번 ${row.published_seq} · 읽을 수 없음: ${batchReasonText(row.reason_code ?? "evidence_invalid")}`;
  return `게시 순번 ${row.published_seq} · ${row.mode === "core_fixed" ? "코어 고정" : "자유 도킹"} · 행 ${row.counts.rows}개` +
    `${row.include_parent ? "(부모 기준 행 포함)" : ""} · ${batchStatusText({ status: row.status, stop_reason: row.stop_reason })}`;
}

// ---- wording check ----

const BATCH_SENTENCES: readonly string[] = Object.values(BATCH_STATEMENTS);

/**
 * Forbidden words (rank, best, improvement, binding strength, affinity outside the fixed score phrase) in screen
 * text, line by line: a line equal to a batch sentence or an M18 limitation is exempt; any other line goes through
 * the M18 check (`dockingForbiddenWords`, which removes only the exact score names).
 */
export function batchForbiddenWords(text: string): string[] {
  return text.split("\n").flatMap(line => BATCH_SENTENCES.includes(line) || DOCKING_LIMITATIONS.includes(line) ? []
    : dockingForbiddenWords(line));
}
