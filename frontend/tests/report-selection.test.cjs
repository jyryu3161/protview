const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const source = fs.readFileSync(path.join(__dirname, "../src/lib/report-selection.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const moduleObject = { exports: {} };
vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, require });
const { reportSelectionKey, savedForSelection, responseMatchesSelection,
  savedMethodForSelection, responseMatchesMethodSelection,
  savedOpenmmForSelection, responseMatchesOpenmmSelection } = moduleObject.exports;

test("historic report references bind to exact interaction, not latest result", () => {
  const reports = [
    { handle: "report-a", interaction_handle: "interaction-a", created_seq: 10 },
    { handle: "report-b", interaction_handle: "interaction-b", created_seq: 20 },
    { handle: "report-a2", interaction_handle: "interaction-a", created_seq: 30 },
  ];
  assert.equal(savedForSelection(reports, "interaction-a").handle, "report-a2");
  assert.equal(savedForSelection(reports, "interaction-b").handle, "report-b");
  assert.equal(savedForSelection(reports, "missing"), undefined);
});

test("stale asynchronous report responses cannot cross run or selection", () => {
  const a = reportSelectionKey("run-a", "interaction-a");
  const b = reportSelectionKey("run-a", "interaction-b");
  const otherRun = reportSelectionKey("run-b", "interaction-a");
  const artifact = { manifest: { interaction_handle: "interaction-a" } };
  assert.equal(responseMatchesSelection(a, a, "run-a", "interaction-a", artifact), true);
  assert.equal(responseMatchesSelection(a, b, "run-a", "interaction-a", artifact), false);
  assert.equal(responseMatchesSelection(a, otherRun, "run-a", "interaction-a", artifact), false);
  assert.equal(responseMatchesSelection(a, a, "run-a", "interaction-b", artifact), false);
  assert.equal(responseMatchesSelection(a, a, "run-a", "interaction-a",
    { manifest: { interaction_handle: "interaction-b" } }), false);
});

test("method reports stay bound to their exact result across history and asynchronous responses", () => {
  const reports = [
    { handle: "legacy", interaction_handle: "result-a" },
    { handle: "sasa-a", result_handle: "result-a", analysis_type: "interface_sasa" },
    { handle: "sasa-b", result_handle: "result-b", analysis_type: "interface_sasa" },
  ];
  assert.equal(savedMethodForSelection(reports, "result-a").handle, "sasa-a");
  assert.equal(savedMethodForSelection(reports, "result-b").handle, "sasa-b");
  assert.equal(savedMethodForSelection(reports, "missing"), undefined);
  const a = reportSelectionKey("run-a", "result-a");
  const b = reportSelectionKey("run-a", "result-b");
  const artifact = { manifest: { schema: "method_report_manifest@1", analysis_type: "interface_sasa", result_handle: "result-a" } };
  assert.equal(responseMatchesMethodSelection(a, a, "run-a", "result-a", artifact), true);
  assert.equal(responseMatchesMethodSelection(a, b, "run-a", "result-a", artifact), false);
  assert.equal(responseMatchesMethodSelection(a, a, "run-b", "result-a", artifact), false);
  assert.equal(responseMatchesMethodSelection(a, a, "run-a", "result-b", artifact), false);
  assert.equal(responseMatchesMethodSelection(a, a, "run-a", "result-a",
    { manifest: { ...artifact.manifest, schema: "report_manifest@1" } }), false);
});

test("OpenMM reports remain bound to method, run, and historical result", () => {
  const reports = [
    { handle: "sasa-a", result_handle: "result-a", analysis_type: "interface_sasa" },
    { handle: "openmm-a", result_handle: "result-a", analysis_type: "openmm_protein_minimize" },
    { handle: "openmm-b", result_handle: "result-b", analysis_type: "openmm_protein_minimize" },
  ];
  assert.equal(savedOpenmmForSelection(reports, "result-a").handle, "openmm-a");
  assert.equal(savedOpenmmForSelection(reports, "result-b").handle, "openmm-b");
  const key = reportSelectionKey("run-a", "result-a");
  const artifact = { manifest: { schema: "method_report_manifest@1", analysis_type: "openmm_protein_minimize", result_handle: "result-a" } };
  assert.equal(responseMatchesOpenmmSelection(key, key, "run-a", "result-a", artifact), true);
  assert.equal(responseMatchesOpenmmSelection(key, reportSelectionKey("run-b", "result-a"), "run-a", "result-a", artifact), false);
  assert.equal(responseMatchesOpenmmSelection(key, reportSelectionKey("run-a", "result-b"), "run-a", "result-a", artifact), false);
  assert.equal(responseMatchesOpenmmSelection(key, key, "run-a", "result-a", { manifest: { ...artifact.manifest, analysis_type: "interface_sasa" } }), false);
  assert.equal(responseMatchesOpenmmSelection(key, key, "run-a", "result-a", { manifest: { ...artifact.manifest, result_handle: "result-b" } }), false);
});
