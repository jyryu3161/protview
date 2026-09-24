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
const { reportSelectionKey, savedForSelection, responseMatchesSelection } = moduleObject.exports;

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
