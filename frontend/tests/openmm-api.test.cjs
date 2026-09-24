const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

test("OpenMM preflight uses canonical structure query while object reads retain handle", async () => {
  const source = fs.readFileSync(path.join(__dirname, "../src/lib/api.ts"), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const seen = [];
  const moduleObject = { exports: {} };
  const fetch = async (url) => {
    seen.push(url);
    return { ok: true, json: async () => ({}) };
  };
  vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, fetch, require });
  const { api } = moduleObject.exports;
  const structure = "obj://run-a/prepared_structure/abc";
  await api.openmmPreflight("run-a", structure);
  await api.meta("run-a", structure);
  assert.equal(seen[0], `/api/runs/run-a/jobs/preflight?structure=${encodeURIComponent(structure)}`);
  assert.equal(seen[1], `/api/runs/run-a/objects/meta?handle=${encodeURIComponent(structure)}`);
});
