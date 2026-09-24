const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function compiledModule(relativePath, requireModule = require) {
  const source = fs.readFileSync(path.join(__dirname, relativePath), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const moduleObject = { exports: {} };
  vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports,
    require: requireModule, fetch });
  return moduleObject.exports;
}

const { displayedEgressMode } = compiledModule("../src/lib/api.ts");
const { WorkspaceShell } = compiledModule("../src/components/shell.tsx", name =>
  name === "./primitives" ? { Button: () => null, Eyebrow: () => null,
    Kbd: () => null, Segmented: () => null } : require(name));

test("read-only mode badge renders effective local, online and dry run mode", () => {
  const base = { run_id: "fixture", goal: "", context: [], last_seq: 1, dry_run: false };
  for (const [run, expected] of [
    [null, "local_only"],
    [{ ...base, egress: "local_only" }, "local_only"],
    [{ ...base, egress: "online" }, "online"],
    [{ ...base, egress: "online", dry_run: true }, "dry_run"],
    [{ ...base, egress: "dry_run" }, "dry_run"],
  ]) {
    const mode = displayedEgressMode(run);
    assert.equal(mode, expected);
    const html = renderToStaticMarkup(React.createElement(WorkspaceShell, {
      egress: mode, rail: { run: null, models: null, jobs: null }, tabs: ["run"],
      canvas: null, inspectorTitle: "fixture", inspector: null,
    }));
    assert.match(html, new RegExp(`<span class="mw-badge">● ${expected}<\\/span>`));
  }
  const page = fs.readFileSync(path.join(__dirname, "../app/page.tsx"), "utf8");
  assert.match(page, /egress=\{displayedEgressMode\(run\)\}/);
});
