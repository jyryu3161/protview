const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const source = fs.readFileSync(path.join(__dirname, "../src/lib/workspace-tabs.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const moduleObject = { exports: {} };
vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, require });
const { WORKSPACE_TABS, DEFAULT_WORKSPACE_TAB, UNAVAILABLE_NOTICES, UNAVAILABLE_STATUS, isWorkspaceTabId } = moduleObject.exports;

test("exactly four top-level tabs with the fixed order and labels", () => {
  assert.deepEqual([...WORKSPACE_TABS.map(tab => tab.label)], ["구조 분석", "단백질 공학", "리간드 설계·탐색", "지식·보고서"]);
  assert.deepEqual([...WORKSPACE_TABS.map(tab => tab.id)], ["structure", "protein", "ligand", "knowledge"]);
  assert.equal(new Set(WORKSPACE_TABS.map(tab => tab.id)).size, 4);
});

test("default tab is the structure analysis tab", () => {
  assert.equal(DEFAULT_WORKSPACE_TAB, "structure");
  assert.equal(WORKSPACE_TABS[0].id, DEFAULT_WORKSPACE_TAB);
});

test("top-level tab names never collide with the rail tab locators ^run / ^models", () => {
  for (const tab of WORKSPACE_TABS) {
    assert.doesNotMatch(tab.label, /^run/i);
    assert.doesNotMatch(tab.label, /^models/i);
  }
});

test("tab id guard accepts only the four ids", () => {
  for (const tab of WORKSPACE_TABS) assert.equal(isWorkspaceTabId(tab.id), true);
  for (const value of ["run", "models", "reports", "", null, undefined, 0, "STRUCTURE"]) assert.equal(isWorkspaceTabId(value), false);
});

// M20: the protein tab hosts the mutation candidate panel, so its notice is gone and no tab has a notice.
test("no tab has an unavailable notice: protein (M20 mutation candidates), ligand (M17) and knowledge (M15) have screens", () => {
  assert.deepEqual([...Object.keys(UNAVAILABLE_NOTICES)].sort(), []);
  assert.equal(UNAVAILABLE_STATUS, "사용할 수 없음");
  for (const notice of Object.values(UNAVAILABLE_NOTICES)) {
    assert.ok(notice.title.length > 0);
    assert.ok(notice.reason.length > 0);
    assert.ok(notice.opens.length > 0);
    for (const item of notice.opens) {
      assert.match(item.stage, /^M\d+$/);
      assert.ok(item.feature.length > 0);
    }
  }
});

test("notice text carries no measured-looking numbers beyond stage names", () => {
  for (const notice of Object.values(UNAVAILABLE_NOTICES)) {
    const text = [notice.title, notice.reason, notice.note ?? "", ...notice.opens.map(item => item.feature)].join(" ");
    assert.doesNotMatch(text.replace(/\bM\d+\b/g, ""), /\d/);
  }
});
