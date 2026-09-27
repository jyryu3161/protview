const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

function compiledModule(relativePath) {
  const source = fs.readFileSync(path.join(__dirname, relativePath), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const moduleObject = { exports: {} };
  vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, require });
  return moduleObject.exports;
}

const { isAllowedHost, HOST_REJECT_STATUS, HOST_REJECT_MESSAGE } =
  compiledModule("../src/lib/host-allowlist.ts");

test("loopback host names are allowed with or without a port, case-insensitively", () => {
  for (const host of ["127.0.0.1", "127.0.0.1:3000", "localhost", "localhost:3000",
    "LOCALHOST:3000", "LocalHost", "[::1]", "[::1]:3000"]) {
    assert.equal(isAllowedHost(host), true, host);
  }
});

test("any other or missing host is rejected", () => {
  for (const host of [null, undefined, "", "evil.example", "evil.example:3000", "testserver",
    "127.0.0.1.evil.example", "localhost.", "localhost:", "localhost:80a", "127.0.0.2",
    "0.0.0.0:3000", "::1", "[::1]x", "user@127.0.0.1", "127.0.0.1:3000:1", " localhost",
    "localhost, evil.example"]) {
    assert.equal(isAllowedHost(host), false, String(host));
  }
});

test("rejection is a fixed 400 message that cannot carry request content", () => {
  assert.equal(HOST_REJECT_STATUS, 400);
  assert.equal(typeof HOST_REJECT_MESSAGE, "string");
  assert.ok(HOST_REJECT_MESSAGE.length > 0);
});

test("root middleware uses the predicate for every path", () => {
  const source = fs.readFileSync(path.join(__dirname, "../middleware.ts"), "utf8");
  assert.match(source, /isAllowedHost\(/);
  assert.doesNotMatch(source, /export\s+const\s+config/);
});
