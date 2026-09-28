const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const source = fs.readFileSync(path.join(__dirname, "../src/lib/pockets.ts"), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const moduleObject = { exports: {} };
vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, require });
const p = moduleObject.exports;
const same = (actual, expected, message) => assert.deepEqual(JSON.parse(JSON.stringify(actual)), expected, message);

// Synthetic, clearly labelled shapes only. No engine observation is used as an expected value.
const SYNTHETIC_SOURCE = "obj://run-synthetic/prepared_structure/aaaa";
const syntheticRef = (site, handle = SYNTHETIC_SOURCE) => ({ structure_handle: handle, site_index: site,
  atom_name: "CA", altloc: "", element: "C",
  residue: { model_number: 1, chain_auth: "A", seq_auth: site + 1, icode: "", chain_label: null, seq_label: null, resname: "GLY" } });
const syntheticGeometry = (overrides = {}) => ({ schema: "pocket_geometry@1", handle: "obj://run-synthetic/pocket_set/bbbb",
  rank: 2, source_handle: SYNTHETIC_SOURCE, model_number: 1, units: {}, descriptors: {},
  spheres: [{ x_A: 1, y_A: 2, z_A: 3, radius_A: 3.25 }, { x_A: -1, y_A: 0.5, z_A: 9, radius_A: 3.4 }],
  lining_atoms: { transport_indices: [0, 1], atoms: [syntheticRef(0), syntheticRef(1)], native_record_count: 3, dedup_policy: "x" },
  lining_residues: [syntheticRef(0).residue, syntheticRef(1).residue],
  display_center: { x_A: 0, y_A: 1.25, z_A: 6, method: "arithmetic_mean_of_stored_sphere_centers" }, ...overrides });

test("top-k defaults to 10, stays within 1–50 and never exceeds the engine total", () => {
  assert.equal(p.DEFAULT_TOP_K, 10);
  assert.equal(p.clampTopK(10, 3), 3);
  assert.equal(p.clampTopK(0, 30), 1);
  assert.equal(p.clampTopK(-4, 30), 1);
  assert.equal(p.clampTopK(51, 200), 50);
  assert.equal(p.clampTopK(7.8, 30), 7);
  assert.equal(p.clampTopK(Number.NaN, 30), 10);
  assert.equal(p.clampTopK(10, 0), 0);
});

test("displayed_count and total_count stay separate; truncation is not incompleteness", () => {
  const pockets = Array.from({ length: 12 }, (_, i) => ({ rank: i + 1 }));
  const shown = p.pocketDisplay(pockets, 12, 10);
  assert.equal(shown.displayed_count, 10);
  assert.equal(shown.total_count, 12);
  assert.equal(shown.truncated, true);
  same(shown.rows.map(row => row.rank), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  const all = p.pocketDisplay(pockets.slice(0, 3), 3, 10);
  assert.equal(all.displayed_count, 3);
  assert.equal(all.total_count, 3);
  assert.equal(all.truncated, false);
  const empty = p.pocketDisplay([], 0, 10);
  assert.equal(empty.displayed_count, 0);
  assert.equal(empty.total_count, 0);
});

test("five UI states are distinct: empty is never failure and failure is never empty", () => {
  const ready = { available: true };
  const unavailable = { available: false, reason: "not installed" };
  assert.equal(p.pocketUiState({ capability: unavailable }), "unavailable");
  assert.equal(p.pocketUiState({ capability: ready }), "ready");
  assert.equal(p.pocketUiState({ capability: ready, jobStatus: "running" }), "loading");
  assert.equal(p.pocketUiState({ capability: ready, jobStatus: "queued" }), "loading");
  assert.equal(p.pocketUiState({ capability: ready, summaryPending: true }), "loading");
  assert.equal(p.pocketUiState({ capability: ready, jobStatus: "failed" }), "failed");
  assert.equal(p.pocketUiState({ capability: ready, jobStatus: "interrupted" }), "failed");
  assert.equal(p.pocketUiState({ capability: ready, jobStatus: "cancelled" }), "failed");
  assert.equal(p.pocketUiState({ capability: ready, readError: "HTTP 422" }), "failed");
  assert.equal(p.pocketUiState({ capability: ready, jobStatus: "done", summary: { null_result: true, total_count: 0 } }), "scientific_null");
  assert.equal(p.pocketUiState({ capability: ready, jobStatus: "done", summary: { null_result: false, total_count: 4 } }), "ready");
  // A stored result reopens even without the engine: it is not "unavailable".
  assert.equal(p.pocketUiState({ capability: unavailable, summary: { null_result: false, total_count: 4 } }), "ready");
  assert.equal(p.pocketUiState({ capability: unavailable, summary: { null_result: true, total_count: 0 } }), "scientific_null");
  // An inconsistent summary is a failure, not an empty result.
  assert.equal(p.pocketUiState({ capability: ready, summary: { null_result: true, total_count: 3 } }), "failed");
  assert.equal(p.pocketUiState({ capability: ready, summary: { null_result: false, total_count: 0 } }), "failed");
});

test("overlay disables M8 prompt and M9 save/PNG with a reason; clearing restores supported sources", () => {
  const on = p.featureGates({ sourceKind: "prepared_structure", overlayActive: true, comparisonActive: false });
  assert.match(on.m8, /포켓 오버레이를 지우면 다시 사용할 수 있습니다/);
  assert.match(on.m9, /포켓 오버레이를 지우면 다시 사용할 수 있습니다/);
  assert.equal(on.m10Measure, null, "distance measurement stays available with an overlay");
  assert.equal(on.pocket, null);
  const off = p.featureGates({ sourceKind: "prepared_structure", overlayActive: false, comparisonActive: false });
  same([off.m8, off.m9, off.m10Measure, off.pocket], [null, null, null, null]);
  const minimized = p.featureGates({ sourceKind: "openmm_minimized_structure", overlayActive: false, comparisonActive: false });
  same([minimized.m8, minimized.m9], [null, null]);
});

test("M10 comparison disables pocket detection and overlay until a single source returns", () => {
  const gates = p.featureGates({ sourceKind: "prepared_structure", overlayActive: false, comparisonActive: true });
  assert.match(gates.pocket, /단일 구조로 돌아가/);
  assert.equal(p.featureGates({ sourceKind: "prepared_structure", overlayActive: false, comparisonActive: false }).pocket, null);
});

test("chemical source restrictions persist after the pocket overlay is cleared", () => {
  for (const overlayActive of [true, false]) {
    const gates = p.featureGates({ sourceKind: "chemical_structure", overlayActive, comparisonActive: false });
    assert.ok(gates.m8 && gates.m9 && gates.m10Measure, `overlay ${overlayActive}`);
    assert.match(gates.m9, /화학/);
    assert.equal(gates.pocket, null, "pocket detection reads the chemical protein projection");
  }
});

test("each panel reopens only its own source kinds and explains the others", () => {
  for (const kind of ["prepared_structure", "openmm_minimized_structure"]) {
    same(p.reopenDecision("main", kind), { allowed: true, reason: null });
    const chemical = p.reopenDecision("chemical", kind);
    assert.equal(chemical.allowed, false);
    assert.match(chemical.reason, /메인 작업 화면에서 열기/);
  }
  same(p.reopenDecision("chemical", "chemical_structure"), { allowed: true, reason: null });
  const main = p.reopenDecision("main", "chemical_structure");
  assert.equal(main.allowed, false);
  assert.match(main.reason, /화학 작업 화면에서 열기/);
  assert.equal(p.reopenDecision("main", "structure").allowed, false);
  assert.equal(p.reopenDecision("main", null).allowed, false);
});

test("a submission that returns an existing cancelled job explains how to run again", () => {
  const notice = p.cancelRerunNotice({ status: "cancelled", protocol_id: "fpocket_detect_v1" });
  assert.match(notice, /다른 체인 조합/);
  assert.match(notice, /새 run/);
  assert.equal(p.cancelRerunNotice({ status: "queued", protocol_id: "fpocket_detect_v1" }), null);
  assert.equal(p.cancelRerunNotice({ status: "done", protocol_id: "fpocket_detect_v1" }), null);
  assert.equal(p.cancelRerunNotice({ status: "cancelled", protocol_id: "openmm_protein_minimize" }), null);
});

test("stale responses are ignored after run, action, source, set or rank changes", () => {
  const captured = { runId: "run-a", action: 3, source: "src-a", setHandle: "set-a", rank: 1 };
  assert.equal(p.pocketActionCurrent(captured, { ...captured }), true);
  for (const [field, value] of Object.entries({ runId: "run-b", action: 4, source: "src-b", setHandle: "set-b", rank: 2 }))
    assert.equal(p.pocketActionCurrent(captured, { ...captured, [field]: value }), false, field);
});

test("an overlay binds only to its displayed source and clears with a reason when the display changes", () => {
  const request = { key: "k", sourceHandle: "src-a" };
  same(p.overlayContextDecision(null, null, "ctx-1", "src-a", true), { action: "none", reason: null });
  same(p.overlayContextDecision(request, null, "ctx-1", "src-b", true), { action: "wait", reason: null });
  same(p.overlayContextDecision(request, null, "ctx-1", "src-a", false), { action: "wait", reason: null });
  same(p.overlayContextDecision(request, null, "ctx-1", "src-a", true), { action: "bind", reason: null });
  same(p.overlayContextDecision(request, "ctx-1", "ctx-1", "src-a", true), { action: "keep", reason: null });
  const moved = p.overlayContextDecision(request, "ctx-1", "ctx-2", "src-a", true);
  assert.equal(moved.action, "clear");
  assert.match(moved.reason, /표시 구조가 바뀌어/);
  const other = p.overlayContextDecision(request, "ctx-1", "ctx-1", "src-b", true);
  assert.equal(other.action, "clear");
});

test("geometry responses must match the requested set, rank and source before drawing", () => {
  const expected = { handle: "obj://run-synthetic/pocket_set/bbbb", rank: 2, sourceHandle: SYNTHETIC_SOURCE };
  assert.equal(p.geometryError(syntheticGeometry(), expected), null);
  assert.match(p.geometryError(syntheticGeometry({ rank: 3 }), expected), /rank/);
  assert.match(p.geometryError(syntheticGeometry({ handle: "other" }), expected), /handle/);
  assert.match(p.geometryError(syntheticGeometry({ source_handle: "other" }), expected), /소스/);
  assert.match(p.geometryError(syntheticGeometry({ spheres: [] }), expected), /알파 구/);
  assert.match(p.geometryError(syntheticGeometry({ spheres: [{ x_A: 1, y_A: 2, z_A: Number.NaN, radius_A: 3 }] }), expected), /알파 구/);
  assert.match(p.geometryError(syntheticGeometry({ spheres: [{ x_A: 1, y_A: 2, z_A: 3, radius_A: 0 }] }), expected), /알파 구/);
  assert.match(p.geometryError(syntheticGeometry({ lining_atoms: { atoms: [syntheticRef(0, "elsewhere")], transport_indices: [0], native_record_count: 1 } }), expected), /주변 원자/);
});

test("overlay requests carry stored spheres exactly and a bounded display focus", () => {
  const geometry = syntheticGeometry();
  const request = p.overlayRequest("run-a", geometry, { showSpheres: true, showLining: false, opacity: 0.4, focusToken: 2 });
  same(request.spheres, geometry.spheres.map(s => [s.x_A, s.y_A, s.z_A, s.radius_A]));
  assert.equal(request.sourceHandle, SYNTHETIC_SOURCE);
  assert.equal(request.rank, 2);
  assert.equal(request.liningAtoms.length, 2);
  same(request.focus.center, [0, 1.25, 6]);
  const far = Math.max(...geometry.spheres.map(s => Math.hypot(s.x_A - 0, s.y_A - 1.25, s.z_A - 6) + s.radius_A));
  assert.equal(request.focus.radius, far);
  assert.equal(p.clampOpacity(2), 1);
  assert.equal(p.clampOpacity(0), 0.1);
  assert.equal(p.clampOpacity(Number.NaN), p.DEFAULT_OPACITY);
});

test("native readback must reproduce stored centers and radii at their notation precision", () => {
  const spheres = [[1, 2, 3, 3.25], [-1, 0.5, 9, 3.4]];
  assert.equal(p.readbackMismatch(spheres, [[1.00000001, 2, 3], [-1, 0.5, 9]], [3.25, 3.4]), null);
  assert.match(p.readbackMismatch(spheres, [[1, 2, 3]], [3.25]), /개수/);
  assert.match(p.readbackMismatch(spheres, [[1.01, 2, 3], [-1, 0.5, 9]], [3.25, 3.4]), /중심/);
  assert.match(p.readbackMismatch(spheres, [[1, 2, 3], [-1, 0.5, 9]], [3.25, 3.42]), /반지름/);
});

test("descriptors render their native text and unit; druggability always carries the warning", () => {
  assert.equal(p.descriptorText({ native_name: "Volume", native_text: "123.456", value: 123.456, unit: "A3" }), "123.456 Å³");
  assert.equal(p.descriptorText({ native_name: "Total SASA", native_text: "10.000", value: 10, unit: "A2" }), "10.000 Å²");
  assert.equal(p.descriptorText({ native_name: "Number of Alpha Spheres", native_text: "35", value: 35, unit: "count" }), "35개");
  assert.equal(p.descriptorText({ native_name: "Score", native_text: "0.100", value: 0.1, unit: "dimensionless" }), "0.100 (무차원)");
  assert.equal(p.descriptorText(undefined), "—");
  assert.match(p.DRUGGABILITY_WARNING, /druggability/);
  assert.match(p.DRUGGABILITY_WARNING, /증거가 아닙니다/);
  assert.equal(p.OVERLAY_LABEL, "fpocket 후보 공동");
});

test("chemical workspace keeps the M11 annotation and the pocket overlay mutually exclusive", () => {
  const overlayOn = p.chemicalExclusive("overlay_on", { annotationVisible: true, overlayActive: false });
  assert.equal(overlayOn.annotationVisible, false);
  assert.equal(overlayOn.clearOverlay, false);
  assert.match(overlayOn.notice, /주석/);
  const annotationOn = p.chemicalExclusive("annotation_on", { annotationVisible: false, overlayActive: true });
  assert.equal(annotationOn.annotationVisible, true);
  assert.equal(annotationOn.clearOverlay, true);
  assert.match(annotationOn.notice, /포켓 오버레이/);
  const quiet = p.chemicalExclusive("annotation_on", { annotationVisible: false, overlayActive: false });
  assert.equal(quiet.notice, null);
});

test("chain selection sends an empty list for the default of every protein chain", () => {
  same(p.chainArgument(["A", "B"], ["A", "B"]), []);
  same(p.chainArgument(["B"], ["A", "B"]), ["B"]);
  same(p.chainArgument(["B", "A"], ["A", "B", "C"]), ["A", "B"]);
});
