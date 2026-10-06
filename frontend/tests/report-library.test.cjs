const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const source = fs.readFileSync(path.join(__dirname, "../src/lib/report-library.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const moduleObject = { exports: {} };
vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, require });
const lib = moduleObject.exports;
const { initialLibraryState, libraryReducer, buildReportRows, buildFigureRows, buildSummaryRows,
  readAllFigurePages, errorDetail, reportKindLabel, RUN_FIGURE_LIMIT, INTERACTION_REPORT_KIND } = lib;

const plain = value => JSON.parse(JSON.stringify(value));
const reduce = (state, ...actions) => actions.reduce(libraryReducer, state);

const reportRefs = [
  { handle: "rep-m", result_handle: "res-p", analysis_type: "pocket_detection", markdown_handle: "md-m", created_seq: 30, snapshot_event_seq: 29 },
  { handle: "rep-i", interaction_handle: "int-a", markdown_handle: "md-i", created_seq: 10, snapshot_event_seq: 9 },
  { handle: "rep-s", result_handle: "res-s", analysis_type: "interface_sasa", markdown_handle: "md-s", created_seq: 20, snapshot_event_seq: 19 },
];
const figure = (handle, scene) => ({ handle, value: { schema: "viewer_figure@1", scene_handle: scene } });
const execRow = (over) => ({ execution_id: "ex", plan_handle: "p", goal: "contact_overview", status: "complete",
  revision: 3, created_seq: 5, dry_run: false, current_step: null, summary_handle: "sum", error: null, ...over });

test("report rows keep every kind, expose target handle, and order by created_seq", () => {
  const rows = plain(buildReportRows(reportRefs));
  assert.deepEqual(rows, [
    { kind: INTERACTION_REPORT_KIND, handle: "rep-i", target_handle: "int-a", created_seq: 10 },
    { kind: "interface_sasa", handle: "rep-s", target_handle: "res-s", created_seq: 20 },
    { kind: "pocket_detection", handle: "rep-m", target_handle: "res-p", created_seq: 30 },
  ]);
  assert.equal(reportKindLabel(rows[0]), "상호작용 보고서");
  assert.equal(reportKindLabel(rows[1]), "interface_sasa");
  assert.equal(reportKindLabel({ kind: "residue_numbering", handle: "h", target_handle: null, created_seq: 1 }), "잔기 번호 대응 보고서");
  assert.equal(reportKindLabel({ kind: "reference_site_annotation", handle: "h", target_handle: "a", created_seq: 2 }), "참조 주석 보고서");
  assert.equal(reportKindLabel({ kind: "ligand_candidates", handle: "h", target_handle: "c", created_seq: 3 }), "리간드 후보 보고서");
  assert.equal(reportKindLabel({ kind: "ligand_docking", handle: "h", target_handle: "d", created_seq: 4 }), "리간드 도킹 보고서");
  assert.equal(reportKindLabel({ kind: "ligand_docking_batch", handle: "h", target_handle: "b", created_seq: 5 }),
    "리간드 도킹 일괄 보고서");
  assert.equal(reportKindLabel({ kind: "ligand_ga", handle: "h", target_handle: "g", created_seq: 6 }),
    "리간드 GA 설계 보고서");
  assert.equal(reportKindLabel({ kind: "sequence_ga", handle: "h", target_handle: "s", created_seq: 7 }),
    "서열 GA 보고서");
  assert.equal(reportKindLabel({ kind: "jev_choice", handle: "h", target_handle: "j", created_seq: 8 }),
    "JEV 판정 보고서");
  assert.deepEqual(plain(buildReportRows([])), []);
});

test("figure rows keep server order and show figure handle and scene handle only", () => {
  assert.deepEqual(plain(buildFigureRows([figure("fig-2", "scene-b"), figure("fig-1", "scene-a")])), [
    { handle: "fig-2", scene_handle: "scene-b" }, { handle: "fig-1", scene_handle: "scene-a" },
  ]);
});

test("workflow summaries include only complete rows with a summary handle and no error", () => {
  const list = { schema: "analysis_execution_list@1", total: 6, rows: [
    execRow({ execution_id: "ex-late", created_seq: 40, summary_handle: "sum-late" }),
    execRow({ execution_id: "ex-running", status: "running", summary_handle: null }),
    execRow({ execution_id: "ex-blocked", status: "blocked", summary_handle: null }),
    execRow({ execution_id: "ex-nosum", status: "complete", summary_handle: null }),
    execRow({ execution_id: "ex-broken", status: "complete", summary_handle: "sum-x", error: { code: "corrupt", message: "bad" } }),
    execRow({ execution_id: "ex-early", created_seq: 12, summary_handle: "sum-early", goal: "pocket_overview" }),
  ] };
  assert.deepEqual(plain(buildSummaryRows(list)), [
    { execution_id: "ex-early", goal: "pocket_overview", summary_handle: "sum-early", created_seq: 12 },
    { execution_id: "ex-late", goal: "contact_overview", summary_handle: "sum-late", created_seq: 40 },
  ]);
});

test("figure pages are read to the end and concatenated in server order", async () => {
  const all = Array.from({ length: 73 }, (_, i) => figure(`fig-${i}`, `scene-${i}`));
  const offsets = [];
  const rows = await readAllFigurePages(async offset => {
    offsets.push(offset);
    return { total: all.length, offset, limit: 50, rows: all.slice(offset, offset + 50) };
  });
  assert.deepEqual(offsets, [0, 50]);
  assert.deepEqual(plain(rows.map(row => row.handle)), all.map(row => row.handle));
  assert.equal(RUN_FIGURE_LIMIT, 100);
});

test("figure paging never yields a partial list when the listing changes or stalls", async () => {
  await assert.rejects(readAllFigurePages(async offset => offset === 0
    ? { total: 60, offset, limit: 50, rows: Array.from({ length: 50 }, (_, i) => figure(`f${i}`, "s")) }
    : { total: 61, offset, limit: 50, rows: [figure("x", "s")] }));
  await assert.rejects(readAllFigurePages(async offset => offset === 0
    ? { total: 60, offset, limit: 50, rows: Array.from({ length: 50 }, (_, i) => figure(`f${i}`, "s")) }
    : { total: 60, offset, limit: 50, rows: [] }));
  await assert.rejects(readAllFigurePages(async offset =>
    ({ total: 101, offset, limit: 50, rows: Array.from({ length: 50 }, (_, i) => figure(`f${offset + i}`, "s")) })));
});

test("no run means a distinct no-run state and every request is ignored", () => {
  const state = initialLibraryState(null);
  assert.equal(state.runId, null);
  assert.equal(lib.isNoRun(state), true);
  const after = reduce(state, { type: "list_request", kind: "reports", runId: null, seq: 1 },
    { type: "list_request", kind: "reports", runId: "run-a", seq: 2 });
  assert.equal(after.lists.reports.status, "idle");
  assert.equal(lib.isNoRun(initialLibraryState("run-a")), false);
});

test("the three lists succeed or fail independently and failures keep the server reason", () => {
  let state = initialLibraryState("run-a");
  state = reduce(state,
    { type: "list_request", kind: "reports", runId: "run-a", seq: 1 },
    { type: "list_request", kind: "figures", runId: "run-a", seq: 2 },
    { type: "list_request", kind: "summaries", runId: "run-a", seq: 3 });
  assert.deepEqual([state.lists.reports.status, state.lists.figures.status, state.lists.summaries.status],
    ["loading", "loading", "loading"]);
  state = reduce(state,
    { type: "list_failed", kind: "reports", runId: "run-a", seq: 1, message: "report evidence invalid", code: "report_evidence_invalid" },
    { type: "list_loaded", kind: "figures", runId: "run-a", seq: 2, response: [figure("fig-1", "scene-1")] },
    { type: "list_loaded", kind: "summaries", runId: "run-a", seq: 3, response: { schema: "analysis_execution_list@1", total: 1, rows: [execRow({})] } });
  assert.deepEqual(plain(state.lists.reports), { status: "error", message: "report evidence invalid", code: "report_evidence_invalid" });
  assert.equal(state.lists.reports.rows, undefined);
  assert.equal(state.lists.figures.status, "ready");
  assert.equal(state.lists.figures.rows.length, 1);
  assert.equal(state.lists.summaries.status, "ready");
  assert.equal(state.lists.summaries.rows[0].summary_handle, "sum");
  // retrying the failed list does not disturb the others
  state = reduce(state, { type: "list_request", kind: "reports", runId: "run-a", seq: 4 },
    { type: "list_loaded", kind: "reports", runId: "run-a", seq: 4, response: reportRefs });
  assert.equal(state.lists.reports.status, "ready");
  assert.equal(state.lists.reports.rows.length, 3);
  assert.equal(state.lists.figures.rows.length, 1);
});

test("errorDetail reads the server message and typed code without inventing one", () => {
  const apiError = Object.assign(new Error("evidence mismatch"), { status: 422, code: "report_evidence_invalid" });
  assert.deepEqual(plain(errorDetail(apiError)), { message: "evidence mismatch", code: "report_evidence_invalid" });
  assert.deepEqual(plain(errorDetail(new Error("boom"))), { message: "boom", code: null });
  assert.equal(typeof errorDetail("weird").message, "string");
});

test("late list responses after a run switch are dropped and old rows are cleared", () => {
  let state = initialLibraryState("run-a");
  state = reduce(state,
    { type: "list_request", kind: "reports", runId: "run-a", seq: 1 },
    { type: "list_loaded", kind: "reports", runId: "run-a", seq: 1, response: reportRefs },
    { type: "list_request", kind: "figures", runId: "run-a", seq: 2 });
  state = libraryReducer(state, { type: "run_changed", runId: "run-b" });
  assert.equal(state.runId, "run-b");
  assert.equal(state.lists.reports.status, "idle");
  assert.equal(state.lists.figures.status, "idle");
  state = reduce(state, { type: "list_request", kind: "figures", runId: "run-b", seq: 3 },
    { type: "list_loaded", kind: "figures", runId: "run-a", seq: 2, response: [figure("old", "old-scene")] },
    { type: "list_failed", kind: "figures", runId: "run-a", seq: 2, message: "old", code: null });
  assert.equal(state.lists.figures.status, "loading");
  state = libraryReducer(state, { type: "list_loaded", kind: "figures", runId: "run-b", seq: 3, response: [figure("new", "new-scene")] });
  assert.deepEqual(plain(state.lists.figures.rows), [{ handle: "new", scene_handle: "new-scene" }]);
  // switching back to run-a does not accept a response from the earlier run-a request
  state = reduce(state, { type: "run_changed", runId: "run-a" },
    { type: "list_request", kind: "reports", runId: "run-a", seq: 5 },
    { type: "list_loaded", kind: "reports", runId: "run-a", seq: 1, response: [] });
  assert.equal(state.lists.reports.status, "loading");
  // switching to no run clears everything
  state = libraryReducer(state, { type: "run_changed", runId: null });
  assert.equal(lib.isNoRun(state), true);
  assert.equal(state.lists.reports.status, "idle");
});

test("a newer request for the same list wins over an older response in the same run", () => {
  let state = reduce(initialLibraryState("run-a"),
    { type: "list_request", kind: "reports", runId: "run-a", seq: 1 },
    { type: "list_request", kind: "reports", runId: "run-a", seq: 2 },
    { type: "list_loaded", kind: "reports", runId: "run-a", seq: 1, response: [] });
  assert.equal(state.lists.reports.status, "loading");
  state = libraryReducer(state, { type: "list_loaded", kind: "reports", runId: "run-a", seq: 2, response: reportRefs });
  assert.equal(state.lists.reports.rows.length, 3);
  // an out-of-order older request cannot become the current one
  const same = libraryReducer(state, { type: "list_request", kind: "reports", runId: "run-a", seq: 1 });
  assert.equal(same, state);
});

test("same-run selection applies only the last selected item's content", () => {
  let state = reduce(initialLibraryState("run-a"),
    { type: "select", runId: "run-a", seq: 1, item: { kind: "report", handle: "rep-i" } },
    { type: "select", runId: "run-a", seq: 2, item: { kind: "report", handle: "rep-s" } });
  assert.deepEqual(plain(state.selection), { kind: "report", handle: "rep-s" });
  assert.equal(state.content.status, "loading");
  state = libraryReducer(state, { type: "content_loaded", runId: "run-a", seq: 1, content: { kind: "report", handle: "rep-i", markdown: "# old" } });
  assert.equal(state.content.status, "loading");
  state = libraryReducer(state, { type: "content_loaded", runId: "run-a", seq: 2, content: { kind: "report", handle: "rep-s", markdown: "# <b>raw</b>" } });
  assert.equal(state.content.status, "ready");
  assert.equal(state.content.content.markdown, "# <b>raw</b>");
  // content that does not belong to the selected item is refused even with a matching sequence
  const mismatch = reduce(state, { type: "select", runId: "run-a", seq: 3, item: { kind: "report", handle: "rep-m" } },
    { type: "content_loaded", runId: "run-a", seq: 3, content: { kind: "report", handle: "rep-i", markdown: "x" } });
  assert.equal(mismatch.content.status, "loading");
  // late failure of an earlier selection does not replace the current content
  state = libraryReducer(state, { type: "content_failed", runId: "run-a", seq: 1, message: "late", code: null });
  assert.equal(state.content.status, "ready");
});

test("content failures show the reason and retry reselects the item", () => {
  let state = reduce(initialLibraryState("run-a"),
    { type: "select", runId: "run-a", seq: 1, item: { kind: "summary", executionId: "ex", summaryHandle: "sum" } },
    { type: "content_failed", runId: "run-a", seq: 1, message: "summary missing", code: "not_found" });
  assert.deepEqual(plain(state.content), { status: "error", message: "summary missing", code: "not_found" });
  const summary = { handle: "sum", summary: { schema: "workflow_summary@1", execution_id: "ex" } };
  state = reduce(state, { type: "select", runId: "run-a", seq: 2, item: { kind: "summary", executionId: "ex", summaryHandle: "sum" } },
    { type: "content_loaded", runId: "run-a", seq: 2, content: { kind: "summary", executionId: "ex", summary } });
  assert.equal(state.content.status, "ready");
  assert.equal(state.content.content.summary.handle, "sum");
});

test("figure selection needs no fetch and switching run clears selection and drops its content", () => {
  let state = libraryReducer(initialLibraryState("run-a"),
    { type: "select", runId: "run-a", seq: 1, item: { kind: "figure", handle: "fig-1" } });
  assert.deepEqual(plain(state.content), { status: "ready", content: { kind: "figure", handle: "fig-1" } });
  state = reduce(state, { type: "select", runId: "run-a", seq: 2, item: { kind: "report", handle: "rep-i" } },
    { type: "run_changed", runId: "run-b" });
  assert.equal(state.selection, null);
  assert.equal(state.content.status, "idle");
  state = reduce(state, { type: "content_loaded", runId: "run-a", seq: 2, content: { kind: "report", handle: "rep-i", markdown: "late" } },
    { type: "select", runId: "run-a", seq: 3, item: { kind: "report", handle: "rep-i" } });
  assert.equal(state.selection, null);
  assert.equal(state.content.status, "idle");
  // same run id again is a no-op, so an in-flight selection is not cleared by a re-render
  const selected = libraryReducer(state, { type: "select", runId: "run-b", seq: 4, item: { kind: "figure", handle: "fig-9" } });
  assert.equal(libraryReducer(selected, { type: "run_changed", runId: "run-b" }), selected);
});
