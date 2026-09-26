const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const source = fs.readFileSync(path.join(__dirname, "../src/lib/area-format.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const moduleObject = { exports: {} };
vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, require });
const { formatArea2 } = moduleObject.exports;

test("SASA display uses decimal half-up and suppresses negative zero", () => {
  assert.equal(formatArea2(2.625), "2.63");
  assert.equal(formatArea2(2.624), "2.62");
  assert.equal(formatArea2(-2.625), "-2.63");
  assert.equal(formatArea2(-0.0001), "0.00");
  assert.equal(formatArea2(0), "0.00");
  assert.equal(formatArea2(Number.NaN), "invalid");
});
