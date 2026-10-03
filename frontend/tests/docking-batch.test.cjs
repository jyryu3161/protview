const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

function load(filename, dependencies = {}, globals = {}) {
  const source = fs.readFileSync(path.join(__dirname, `../src/lib/${filename}.ts`), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const moduleObject = { exports: {} };
  vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports,
    require: name => dependencies[name] ?? require(name), ...globals });
  return moduleObject.exports;
}
const siteAnnotation = load("site-annotation", { "./comparison": load("comparison"), "./numbering": load("numbering"),
  "./event-model": load("event-model") });
const docking = load("docking", { "./site-annotation": siteAnnotation });
const lib = load("docking-batch", { "./docking": docking, "./site-annotation": siteAnnotation });
const plain = value => JSON.parse(JSON.stringify(value));

// ---- closed sets, limits and fixed wording are read from backend/mw/docking_batch_constants.py itself ----
const constantsSource = fs.readFileSync(path.join(__dirname, "../../backend/mw/docking_batch_constants.py"), "utf8");
function backendTuple(name) {
  const match = new RegExp(`^${name} = \\(([^)]*)\\)`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map(item => item[1]);
}
function backendNumber(name) {
  const match = new RegExp(`^${name} = ([0-9_]+)`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return Number(match[1].replace(/_/g, ""));
}
function backendString(name) {
  const match = new RegExp(`^${name} = "([^"]+)"`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return match[1];
}
function backendDict(name) {
  const start = constantsSource.indexOf(`${name} = {`);
  assert.ok(start >= 0, `backend constant ${name} not found`);
  const end = constantsSource.indexOf("}", start);
  const block = constantsSource.slice(start + name.length + 4, end).replace(/"\s*\n\s*"/g, "");
  return Object.fromEntries([...block.matchAll(/"([^"]+)":\s*"([^"]+)"/g)].map(item => [item[1], item[2]]));
}

test("closed sets, limits and fixed wording equal the backend batch constants", () => {
  assert.equal(lib.BATCH_PROTOCOL, backendString("PROTOCOL"));
  assert.equal(lib.BATCH_TOOL, backendString("TOOL"));
  for (const name of ["ROW_KINDS", "ROW_STATES", "BATCH_STATUSES", "STOP_REASONS", "ADMISSION_REASONS",
    "ROW_ONLY_REASONS"]) assert.deepEqual(plain(lib[name]), backendTuple(name), name);
  assert.equal(lib.MAX_CANDIDATES, backendNumber("MAX_CANDIDATES"));
  assert.equal(lib.PER_CANDIDATE_S, backendNumber("PER_CANDIDATE_S"));
  assert.equal(lib.TOTAL_S, backendNumber("TOTAL_S"));
  assert.equal(lib.BATCH_TIMEOUT_S, backendNumber("TIMEOUT_MAX_S"));
  const apiSource = fs.readFileSync(path.join(__dirname, "../src/lib/api.ts"), "utf8");
  assert.equal(Number(/^export const DOCKING_BATCH_TIMEOUT_S = (\d+);/m.exec(apiSource)?.[1]), lib.BATCH_TIMEOUT_S);
  assert.ok(apiSource.includes('protocol_id: "qvina_batch_dock_v1", args,\n      timeout_s: DOCKING_BATCH_TIMEOUT_S'));
  assert.deepEqual(plain(lib.SCORE_ROW_LABELS), backendDict("SCORE_ROW_LABELS"));
  assert.deepEqual(plain(lib.BATCH_STATEMENTS), backendDict("BATCH_STATEMENTS"));
  assert.equal(lib.SCORE_COLUMN_LABEL, "qvina 점수(kcal/mol)");
  assert.equal(lib.SCORE_COLUMN_LABEL, docking.SCORE_COLUMN_LABEL);
});

test("every batch reason has Korean text with its code; M18 reasons reuse the M18 names", () => {
  for (const code of [...lib.ADMISSION_REASONS, ...lib.ROW_ONLY_REASONS, ...lib.STOP_REASONS]) {
    const text = lib.batchReasonText(code);
    assert.ok(text.endsWith(` (${code})`) && text.length > code.length + 3, code);
  }
  assert.equal(lib.batchReasonText("ligand_not_3d"), docking.dockingReasonText("ligand_not_3d"));
  assert.equal(lib.batchReasonText("engine_failed"), docking.dockingReasonText("engine_failed"));
  assert.equal(lib.batchReasonText("unknown_code_x"), "unknown_code_x");
  // The M18 label map stays exactly the M18 set (its own test compares it); batch codes live here.
  for (const code of lib.ADMISSION_REASONS) assert.equal(docking.DOCKING_REASON_LABEL[code], undefined);
});

// ---- table rows ----

const row = (index, state, extra = {}) => ({ row_index: index, kind: "candidate", candidate_id: `c_${index}`, state,
  reason_code: state === "scored" || state === "null_result" ? null : "worker_failed",
  result_handle: state === "scored" || state === "null_result" ? `obj://r/docking_result/h${index}` : null,
  score_kcal_mol: null, score_row_label: null, reused: false, ...extra });
const scored = (index, score, extra = {}) => row(index, "scored", { score_kcal_mol: score,
  score_row_label: "모드 1(엔진 출력 순서)", ...extra });
const order = rows => plain(rows.map(item => item.row_index));

const ROWS = [
  row(0, "scored", { kind: "parent", candidate_id: null, score_kcal_mol: -6.1, score_row_label: "모드 1(엔진 출력 순서)" }),
  scored(1, -7.2, { candidate_id: "c_b" }),
  row(2, "failed", { candidate_id: "c_a", reason_code: "ligand_too_many_torsions" }),
  scored(3, 0, { candidate_id: "c_d" }),
  row(4, "null_result", { candidate_id: "c_c" }),
  scored(5, -7.2, { candidate_id: "c_e" }),
  row(6, "not_run", { candidate_id: "c_f", reason_code: "time_exhausted" }),
  scored(7, -8.0, { candidate_id: "c_g" }),
  row(8, "cancelled", { candidate_id: "c_h", reason_code: "time_exhausted" }),
];

test("default order is the batch row order; sorting never changes the rows themselves", () => {
  const shuffled = [ROWS[3], ROWS[0], ROWS[8], ROWS[1]];
  assert.deepEqual(order(lib.sortBatchRows(shuffled, null)), [0, 1, 3, 8]);
  const before = plain(ROWS);
  lib.sortBatchRows(ROWS, { key: "score", direction: "asc" });
  assert.deepEqual(plain(ROWS), before);
});

test("score sort: scored rows by stored score, unscored rows always last in row order, never treated as 0", () => {
  // A real 0 score (row 3) is a number and sorts as one; null_result / failed / cancelled / not_run do not.
  assert.deepEqual(order(lib.sortBatchRows(ROWS, { key: "score", direction: "asc" })), [7, 1, 5, 0, 3, 2, 4, 6, 8]);
  assert.deepEqual(order(lib.sortBatchRows(ROWS, { key: "score", direction: "desc" })), [3, 0, 1, 5, 7, 2, 4, 6, 8]);
  // Ties keep row order in both directions (stable).
  const asc = order(lib.sortBatchRows(ROWS, { key: "score", direction: "asc" }));
  assert.ok(asc.indexOf(1) < asc.indexOf(5));
  const desc = order(lib.sortBatchRows(ROWS, { key: "score", direction: "desc" }));
  assert.ok(desc.indexOf(1) < desc.indexOf(5));
  // A row whose state is not scored is unscored even if a number were present.
  const odd = [scored(0, -9), row(1, "failed", { score_kcal_mol: -99 })];
  assert.deepEqual(order(lib.sortBatchRows(odd, { key: "score", direction: "asc" })), [0, 1]);
  assert.deepEqual(order(lib.sortBatchRows(odd, { key: "score", direction: "desc" })), [0, 1]);
});

test("row number and candidate id sorts; the parent row (no candidate id) stays last in a candidate id sort", () => {
  assert.deepEqual(order(lib.sortBatchRows(ROWS, { key: "row", direction: "asc" })), [0, 1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(order(lib.sortBatchRows(ROWS, { key: "row", direction: "desc" })), [8, 7, 6, 5, 4, 3, 2, 1, 0]);
  assert.deepEqual(order(lib.sortBatchRows(ROWS, { key: "candidate", direction: "asc" })), [2, 1, 4, 3, 5, 6, 7, 8, 0]);
  assert.deepEqual(order(lib.sortBatchRows(ROWS, { key: "candidate", direction: "desc" })), [8, 7, 6, 5, 3, 4, 1, 2, 0]);
});

test("header clicks: a new column starts ascending, the same column toggles; aria-sort follows", () => {
  let sort = null;
  sort = lib.nextBatchSort(sort, "score");
  assert.deepEqual(plain(sort), { key: "score", direction: "asc" });
  sort = lib.nextBatchSort(sort, "score");
  assert.deepEqual(plain(sort), { key: "score", direction: "desc" });
  sort = lib.nextBatchSort(sort, "candidate");
  assert.deepEqual(plain(sort), { key: "candidate", direction: "asc" });
  assert.equal(lib.ariaSort(sort, "candidate"), "ascending");
  assert.equal(lib.ariaSort(sort, "score"), "none");
  assert.equal(lib.ariaSort({ key: "row", direction: "desc" }, "row"), "descending");
  assert.equal(lib.ariaSort(null, "row"), "none");
});

test("cells: score only for scored rows (one decimal, stored value), blanks and reasons for the rest", () => {
  assert.equal(lib.rowScoreText(scored(1, -7.25)), "-7.3");
  assert.equal(lib.rowScoreText(scored(1, 0)), "0.0");
  for (const state of ["null_result", "failed", "cancelled", "not_run"])
    assert.equal(lib.rowScoreText(row(1, state, { score_kcal_mol: -5 })), "");
  assert.equal(lib.rowCandidateText(ROWS[0]), "부모(기준 입력)");
  assert.equal(lib.rowCandidateText(ROWS[1]), "c_b");
  // The score target label is the server's string, shown as is (never computed here).
  assert.equal(lib.rowScoreTargetText(scored(1, -7, { score_row_label: "샘플 1(점수 오름차순 나열)" })),
    "샘플 1(점수 오름차순 나열)");
  assert.equal(lib.rowScoreTargetText(row(2, "failed")), "");
  assert.equal(lib.rowReasonText(row(2, "failed", { reason_code: "candidate_timeout" })),
    lib.batchReasonText("candidate_timeout"));
  assert.equal(lib.rowReasonText(scored(1, -7)), "");
  assert.equal(lib.rowStateText("not_run"), `${lib.ROW_STATE_TEXT.not_run} (not_run)`);
  assert.equal(lib.reusedText(true), "저장된 결과 재사용");
  assert.equal(lib.reusedText(false), "");
  assert.equal(lib.rowDetailAvailable(row(4, "null_result")), true);
  assert.equal(lib.rowDetailAvailable(row(2, "failed")), false);
  assert.equal(lib.rowDetailAvailable(scored(1, -7)), true);
});

test("batch status and stop reason wording; B2 only when partial", () => {
  assert.equal(lib.batchStatusText({ status: "complete", stop_reason: null }), "완료 (complete)");
  for (const reason of lib.STOP_REASONS) {
    const text = lib.batchStatusText({ status: "partial", stop_reason: reason });
    assert.ok(text.startsWith("부분 완료 (partial)") && text.includes(lib.batchReasonText(reason)), reason);
  }
  assert.equal(lib.partialStatement({ status: "complete" }), null);
  assert.equal(lib.partialStatement({ status: "partial" }), lib.BATCH_STATEMENTS.B2);
});

// ---- inputs ----

test("parent baseline row: disabled with the closed reason in core-fixed mode and until a mode is chosen", () => {
  assert.equal(lib.parentDisabledReason("free"), null);
  assert.ok(lib.parentDisabledReason("core_fixed").includes("(batch_parent_not_allowed)"));
  assert.ok(lib.parentDisabledReason(null));
  assert.ok(!/[0-9]/.test(lib.parentDisabledReason("core_fixed").replace("batch_parent_not_allowed", "")));
});

test("candidate selection: at most 50, ids kept in candidate-set order (not click order)", () => {
  let selection = {};
  selection = lib.toggleCandidate(selection, "c_9", 9, true);
  selection = lib.toggleCandidate(selection, "c_2", 2, true);
  selection = lib.toggleCandidate(selection, "c_5", 5, true);
  assert.deepEqual(plain(lib.orderedCandidateIds(selection)), ["c_2", "c_5", "c_9"]);
  selection = lib.toggleCandidate(selection, "c_5", 5, false);
  assert.deepEqual(plain(lib.orderedCandidateIds(selection)), ["c_2", "c_9"]);
  let full = {};
  for (let i = 0; i < 50; i += 1) full = lib.toggleCandidate(full, `c_${i}`, i, true);
  assert.equal(lib.orderedCandidateIds(full).length, 50);
  assert.equal(lib.candidateSelectable(full, "c_50"), false);
  assert.equal(lib.candidateSelectable(full, "c_3"), true);   // a chosen one can still be unchecked
  const over = lib.toggleCandidate(full, "c_50", 50, true);
  assert.equal(lib.orderedCandidateIds(over).length, 50);
  assert.equal(lib.selectionCountText(50), "선택 50 / 50");
  assert.equal(lib.selectionCountText(0), "선택 0 / 50");
});

const RECEPTOR = "obj://r/chemical_raw_input/rec", SET = "obj://r/ligand_candidate_set/s",
  PARENT = "obj://r/chemical_raw_input/par";
const form = patch => ({ ...lib.initialBatchForm(), receptorHandle: RECEPTOR, receptorModelNumber: 1,
  connectivity: "pdb_conect", instance: { kind: "none" }, candidateSetHandle: SET, parentSdfHandle: PARENT,
  candidateOrder: { c_3: 3, c_1: 1 }, mode: "free", boxSource: "ligand_range", seed: "42",
  acknowledgement: { keep_input_protonation: true, tool_assigned_types_charges: true, rigid_no_optimization: true },
  ...patch });

test("batch arguments: the fixed qvina_batch_dock_v1 shape, ids in set order, no ligand key", () => {
  const check = lib.batchArgs(form({}));
  assert.equal(check.ok, true);
  assert.deepEqual(plain(check.args), {
    receptor_handle: RECEPTOR, receptor_model_number: 1, connectivity: { kind: "pdb_conect", sidecar_handle: null },
    receptor_instance: null, candidate_set_handle: SET, parent_sdf_handle: PARENT, candidate_ids: ["c_1", "c_3"],
    include_parent: false, mode: "free", box: { source: "ligand_range", margin_A: 8 },
    parameters: { seed: 42, exhaustiveness: 8, num_modes: 9, energy_range: 3 },
    acknowledgement: { keep_input_protonation: true, tool_assigned_types_charges: true, rigid_no_optimization: true },
  });
  const core = lib.batchArgs(form({ mode: "core_fixed" }));
  assert.equal(core.ok, true);
  assert.equal(core.args.parameters.conformers, 50);
  assert.equal(lib.batchArgs(form({ includeParent: true })).args.include_parent, true);
});

test("batch arguments refuse what the server would refuse (empty, parent in core-fixed, no seed, no acknowledgement)", () => {
  const empty = lib.batchArgs(form({ candidateOrder: {} }));
  assert.equal(empty.ok, false);
  assert.ok(empty.errors.some(text => text.includes("(batch_empty)")));
  assert.ok(!empty.errors.includes("후보를 고르세요."));
  const parent = lib.batchArgs(form({ mode: "core_fixed", includeParent: true }));
  assert.equal(parent.ok, false);
  assert.ok(parent.errors.some(text => text.includes("(batch_parent_not_allowed)")));
  assert.equal(lib.batchArgs(form({ seed: "" })).ok, false);
  assert.equal(lib.batchArgs(form({ acknowledgement: { keep_input_protonation: true,
    tool_assigned_types_charges: false, rigid_no_optimization: true } })).ok, false);
  const many = {};
  for (let i = 0; i < 51; i += 1) many[`c_${i}`] = i;
  const tooMany = lib.batchArgs(form({ candidateOrder: many }));
  assert.equal(tooMany.ok, false);
  assert.ok(tooMany.errors.some(text => text.includes("(batch_too_large)")));
});

test("form edits: a new set clears the selection; core-fixed clears the parent row; nothing is chosen instead", () => {
  const base = form({ includeParent: true });
  const set = lib.patchBatchForm(base, { candidateSetHandle: "obj://r/ligand_candidate_set/t" });
  assert.deepEqual(plain(set.candidateOrder), {});
  assert.equal(set.parentSdfHandle, null);
  assert.equal(lib.patchBatchForm(base, { mode: "core_fixed" }).includeParent, false);
  assert.equal(lib.patchBatchForm(base, { seed: "7" }).includeParent, true);
  assert.deepEqual(plain(lib.patchBatchForm(base, { seed: "7" }).candidateOrder), plain(base.candidateOrder));
  assert.equal(lib.patchBatchForm(base, { candidateSetHandle: SET }).candidateOrder, base.candidateOrder);
  // The ligand source stays the candidate source (the batch has no SDF source).
  assert.equal(lib.initialBatchForm().ligandSource, "candidate");
  assert.equal(lib.initialBatchForm().mode, null);
  assert.equal(lib.initialBatchForm().includeParent, false);
});

// ---- preflight and limit approval ----

const preflight = patch => ({ schema: "docking_batch_preflight@1", starts_job: false,
  admission: { admitted: true, error: null, reason_code: null, message: null, detail: null },
  batch_input_sha256: "a".repeat(64), rows: [], new_dockings: 3, reused_rows: 1,
  needed: { expensive_calls: 3, wall_clock_s: 1200 }, remaining: { expensive_calls: 1, wall_clock_s: 900.5 },
  shortfall: { expensive_calls: 2, wall_clock_s: 299.5 }, full_batch_may_be_partial: false,
  statements: { batch: [{ id: "B1", text: lib.BATCH_STATEMENTS.B1 }], m18: [] }, existing_job: null, ...patch });

test("limit approval is offered only for an admitted preflight with a shortfall, outside dry-run", () => {
  assert.equal(lib.limitApprovalOffered(preflight({}), false), true);
  assert.equal(lib.limitApprovalOffered(preflight({ shortfall: { expensive_calls: 0, wall_clock_s: 10 } }), false), true);
  assert.equal(lib.limitApprovalOffered(preflight({ shortfall: { expensive_calls: 0, wall_clock_s: 0 } }), false), false);
  assert.equal(lib.limitApprovalOffered(preflight({}), true), false);
  assert.equal(lib.limitApprovalOffered(preflight({ admission: { admitted: false, error: "input_invalid",
    reason_code: "batch_empty", message: "x", detail: null }, shortfall: null }), false), false);
  assert.equal(lib.limitApprovalOffered(null, false), false);
});

test("preflight lines show server numbers: N, reuse, need, remaining, shortfall and the no-refund note", () => {
  const lines = lib.preflightLines(preflight({})).map(([label, value]) => `${label}: ${value}`);
  assert.ok(lines.some(line => line.includes("새로 계산할 행") && line.includes("3")));
  assert.ok(lines.some(line => line.includes("저장된 결과 재사용 1개")));
  assert.ok(lines.some(line => line.includes("비싼 계산 3단위") && line.includes("1200")));
  assert.ok(lines.some(line => line.includes("900.5")));
  assert.ok(lines.some(line => line.includes("비싼 계산 2단위") && line.includes("299.5")));
  assert.equal(lib.chargeNote(3), "시작하면 3단위가 소진되고 중간에 멈춰도 돌려받지 않음");
  assert.ok(lib.WAIT_NOTE.includes("최대 약 2시간"));
  assert.ok(lib.PARTIAL_RISK_NOTE.includes("2시간"));
  assert.equal(lib.preflightLines(preflight({ admission: { admitted: false, error: "input_invalid",
    reason_code: "batch_empty", message: "x", detail: null } })).length, 0);
  assert.ok(lib.preflightRefusalText(preflight({ admission: { admitted: false, error: "input_invalid",
    reason_code: "batch_parent_not_allowed", message: "m", detail: null } })).includes("(batch_parent_not_allowed)"));
  assert.ok(lib.existingJobText({ job_id: "job_1", status: "done", summary_handle: null }).includes("job_1"));
});

test("a refused preflight keeps the receptor refusal items (seven fields, nulls kept, total) for the screen", () => {
  const residue = { model_number: 1, chain_auth: "W", chain_label: null, seq_auth: 1, seq_label: null, icode: "",
    resname: "HOH" };
  const refused = preflight({ admission: { admitted: false, error: "input_invalid",
    reason_code: "receptor_unsupported_residue", message: "m", detail: { reason_code: "receptor_unsupported_residue",
      items: [{ residue, atom_names: ["O", "H1", "H2"] }], total: 2 } }, shortfall: null });
  const list = lib.preflightRefusalList(refused);
  assert.equal(list.reason_code, "receptor_unsupported_residue");
  assert.equal(list.total, 2);
  assert.equal(list.shown, 1);
  assert.deepEqual(plain(list.lines), ['model_number=1, chain_auth="W", chain_label=null, seq_auth=1, seq_label=null, ' +
    'icode="", resname="HOH" · 원자 O, H1, H2']);
  assert.equal(lib.preflightRefusalList(preflight({})), null);
  assert.equal(lib.preflightRefusalList(preflight({ admission: { admitted: false, error: "input_invalid",
    reason_code: "batch_empty", message: "x", detail: { reason_code: "batch_empty" } } })), null);
});

test("start is blocked until a current admitted preflight without shortfall exists (dry-run plans only)", () => {
  const capability = { available: true, reason: null, reason_code: null };
  const check = lib.batchArgs(form({}));
  const key = lib.batchArgsKey(check.args);
  const base = { capability, busy: false, activeJob: null, check, dryRun: false };
  assert.ok(lib.batchStartBlockedReason({ ...base, preflight: null }));
  assert.ok(lib.batchStartBlockedReason({ ...base, preflight: { key: "other", value: preflight({ shortfall:
    { expensive_calls: 0, wall_clock_s: 0 } }) } }));
  assert.ok(lib.batchStartBlockedReason({ ...base, preflight: { key, value: preflight({}) } }));
  assert.equal(lib.batchStartBlockedReason({ ...base, preflight: { key, value: preflight({ shortfall:
    { expensive_calls: 0, wall_clock_s: 0 } }) } }), null);
  assert.equal(lib.batchStartBlockedReason({ ...base, dryRun: true, preflight: { key, value: preflight({}) } }), null);
  assert.ok(lib.batchStartBlockedReason({ ...base, activeJob: { status: "running" }, preflight: { key, value:
    preflight({ shortfall: { expensive_calls: 0, wall_clock_s: 0 } }) } }));
  assert.ok(lib.batchStartBlockedReason({ ...base, capability: { available: false, reason: "r", reason_code: "worker_missing" },
    preflight: { key, value: preflight({ shortfall: { expensive_calls: 0, wall_clock_s: 0 } }) } }));
});

// ---- jobs ----

test("job wording, progress from stored job state, approval gate and active-job re-attach", () => {
  assert.equal(lib.batchProgressText({ rows: 5, reused_rows: [1], finished_rows: 2, summary_handle: null }),
    "새로 계산하는 행 4개 중 상태가 기록된 행 2개 · 저장된 결과 재사용 1행");
  assert.equal(lib.batchApprovalRequired(409, { gate: "expensive_first_call", tool: "qvina_dock_batch" }), true);
  assert.equal(lib.batchApprovalRequired(409, { gate: "expensive_first_call", tool: "qvina_dock_ligand" }), false);
  const jobs = [{ run_id: "r", protocol_id: "qvina_dock_v1", status: "running" },
    { run_id: "r", protocol_id: "qvina_batch_dock_v1", status: "done" },
    { run_id: "r", protocol_id: "qvina_batch_dock_v1", status: "queued", job_id: "j2" }];
  assert.equal(lib.batchActiveJob(jobs, "r").job_id, "j2");
  assert.equal(lib.batchActiveJob(jobs.slice(0, 2), "r"), null);
  for (const status of ["queued", "running", "done", "failed", "cancelled"])
    assert.ok(lib.batchJobText({ status, cancel_requested: false, failure: null }, false));
  assert.ok(lib.batchJobText({ status: "queued", cancel_requested: false, failure: null }, true).includes("승인"));
  assert.ok(lib.batchReportMatches({ manifest: { schema: "method_report_manifest@1", analysis_type: "ligand_docking_batch",
    result_handle: "h" } }, "h"));
  assert.ok(!lib.batchReportMatches({ manifest: { schema: "method_report_manifest@1", analysis_type: "ligand_docking",
    result_handle: "h" } }, "h"));
});

// ---- wording ----

test("forbidden-word guard: batch sentences and fixed score phrases are exempt, everything else is checked", () => {
  for (const sentence of Object.values(lib.BATCH_STATEMENTS)) assert.deepEqual(plain(lib.batchForbiddenWords(sentence)), []);
  for (const sentence of docking.DOCKING_LIMITATIONS) assert.deepEqual(plain(lib.batchForbiddenWords(sentence)), []);
  assert.deepEqual(plain(lib.batchForbiddenWords(docking.SCORE_LABEL)), []);
  for (const [text, word] of [["순위 1", "순위"], ["best", "best"], ["최고 점수", "최고"], ["최적 후보", "최적"],
    ["점수 개선", "개선"], ["결합 강도", "결합 강도"], ["친화도", "친화"]])
    assert.deepEqual(plain(lib.batchForbiddenWords(text)), [word], text);
  assert.deepEqual(plain(lib.batchForbiddenWords(`${lib.BATCH_STATEMENTS.B1} best`)), ["순위", "best"]);
});

test("every fixed screen string of this module and every line of DockingBatchPanel.tsx pass the wording check", () => {
  const texts = [
    ...Object.values(lib.BATCH_REASON_LABEL), ...Object.values(lib.ROW_STATE_TEXT), lib.WAIT_NOTE,
    lib.PARTIAL_RISK_NOTE, lib.chargeNote(3), lib.LIMIT_RAISE_LABEL, lib.REUSED_LABEL, lib.PARENT_ROW_LABEL,
    lib.parentDisabledReason("core_fixed"), lib.parentDisabledReason(null),
    ...lib.STOP_REASONS.map(reason => lib.batchStatusText({ status: "partial", stop_reason: reason })),
    lib.batchStatusText({ status: "complete", stop_reason: null }),
    ...["queued", "running", "done", "failed", "cancelled"].map(status =>
      lib.batchJobText({ status, cancel_requested: false, failure: null }, false)),
    ...plain(lib.batchArgs(lib.initialBatchForm())).errors,
    ...lib.preflightLines(preflight({ full_batch_may_be_partial: true })).flat(),
  ];
  for (const text of texts) assert.deepEqual(plain(lib.batchForbiddenWords(text)), [], text);
  const panel = path.join(__dirname, "../src/components/DockingBatchPanel.tsx");
  if (fs.existsSync(panel)) assert.deepEqual(plain(lib.batchForbiddenWords(fs.readFileSync(panel, "utf8"))), []);
});
