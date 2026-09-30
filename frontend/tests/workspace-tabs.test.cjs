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

test("unavailable notices cover protein and ligand only; structure and knowledge (M15 numbering) have none", () => {
  assert.deepEqual([...Object.keys(UNAVAILABLE_NOTICES)].sort(), ["ligand", "protein"]);
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

test("notices name the stage that opens each feature", () => {
  const stages = key => JSON.parse(JSON.stringify(UNAVAILABLE_NOTICES[key].opens.map(item => [item.stage, item.feature])));
  assert.deepEqual(stages("protein"), [["M20", "변이 후보 생성"], ["M21", "변이 구조 모델링"]]);
  assert.deepEqual(stages("ligand"), [["M17", "결합 부위 지정·후보 생성·필터"], ["M18", "도킹"]]);
  assert.match(UNAVAILABLE_NOTICES.ligand.note, /M11/);
  assert.match(UNAVAILABLE_NOTICES.ligand.note, /구조 분석/);
});

test("notice text carries no measured-looking numbers beyond stage names", () => {
  for (const notice of Object.values(UNAVAILABLE_NOTICES)) {
    const text = [notice.title, notice.reason, notice.note ?? "", ...notice.opens.map(item => item.feature)].join(" ");
    assert.doesNotMatch(text.replace(/\bM\d+\b/g, ""), /\d/);
  }
});
