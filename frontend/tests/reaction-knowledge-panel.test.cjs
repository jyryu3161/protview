// M26 T8 screen: the "효소 반응 지식" area compiled from source and rendered on the server (effects do not run, so no
// request is made), source checks of what the component can render and request, the knowledge-tab wiring, and the
// shared "촉매 잔기 검사 안 함" mark of the other areas that pick an M20 candidate set. The pure decisions are tested in
// tests/reaction-knowledge.test.cjs and tests/mutations.test.cjs.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function load(filename, dependencies = {}) {
  const source = fs.readFileSync(path.join(__dirname, `../src/lib/${filename}.ts`), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const moduleObject = { exports: {} };
  vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, URLSearchParams,
    require: name => dependencies[name] ?? require(name) });
  return moduleObject.exports;
}
function compileTsx(relativePath, dependencies) {
  const source = fs.readFileSync(path.join(__dirname, relativePath), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const moduleObject = { exports: {} };
  vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, URLSearchParams, AbortSignal,
    AbortController, require: name => dependencies[name] ?? require(name) });
  return moduleObject.exports;
}
const numbering = load("numbering");
const eventModel = load("event-model");
const siteAnnotation = load("site-annotation", { "./comparison": load("comparison"), "./numbering": numbering,
  "./event-model": eventModel });
const lib = load("reaction-knowledge", { "./numbering": numbering });
const mutations = load("mutations", { "./event-model": eventModel, "./site-annotation": siteAnnotation });
const primitives = compileTsx("../src/components/primitives.tsx", { "@/lib/contracts": load("contracts") });
const noRequest = () => { throw new Error("a server render makes no request"); };
const apiStub = { api: new Proxy({}, { get: () => noRequest }), ApiError: class ApiError extends Error {} };
const panel = compileTsx("../src/components/ReactionKnowledgePanel.tsx", { "@/lib/api": apiStub,
  "@/lib/reaction-knowledge": lib, "./primitives": primitives });
const workspaceTabs = compileTsx("../src/components/WorkspaceTabs.tsx", { "@/lib/workspace-tabs": load("workspace-tabs") });
const plain = value => JSON.parse(JSON.stringify(value));
const decode = text => text.replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
  .replace(/&amp;/g, "&");
const textLines = html => decode(html.replace(/<[^>]+>/g, "\n")).split("\n").map(line => line.trim()).filter(Boolean);
const tagOf = (html, testId) => new RegExp(`<[a-z]+ [^>]*data-testid="${testId}"[^>]*>`).exec(html)?.[0] ?? "";
const CAPABILITY = { available: false, reason_code: "not_installed", reason: "반응 참조 스냅샷 없음", set_hash: null,
  sources: [] };
const render = props => renderToStaticMarkup(React.createElement(panel.ReactionKnowledgePanel,
  { runId: "fixture-run", capability: CAPABILITY, onReportCreated: () => undefined, ...props }));
const COMPONENTS = path.join(__dirname, "../src/components");
const SOURCE_FILE = path.join(COMPONENTS, "ReactionKnowledgePanel.tsx");
const SOURCE = fs.readFileSync(SOURCE_FILE, "utf8");

/** Literals a component can render, its `useEffect` bodies and its test ids (the M23–M25 screen-test visitor). */
function scan(file) {
  const source = fs.readFileSync(file, "utf8");
  const sourceFile = ts.createSourceFile(file, source, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
  const texts = [], effects = [], ids = [];
  const visit = node => {
    if (ts.isJsxText(node) && node.text.trim()) texts.push(node.text.trim());
    else if (ts.isStringLiteral(node) && !ts.isImportDeclaration(node.parent)) texts.push(node.text);
    else if (ts.isNoSubstitutionTemplateLiteral(node)) texts.push(node.text);
    else if (ts.isTemplateExpression(node)) texts.push(node.head.text, ...node.templateSpans.map(span => span.literal.text));
    if (ts.isCallExpression(node) && node.expression.getText(sourceFile) === "useEffect")
      effects.push(node.arguments[0].getText(sourceFile));
    if (ts.isJsxAttribute(node) && ["data-testid", "testId"].includes(node.name.getText(sourceFile))) {
      const value = node.initializer;
      if (value && ts.isStringLiteral(value)) ids.push(value.text);
      else if (value && ts.isJsxExpression(value) && value.expression) {
        const expression = value.expression;
        if (ts.isTemplateExpression(expression)) ids.push(expression.head.text);
        else if (ts.isConditionalExpression(expression)) ids.push(expression.whenTrue.text, expression.whenFalse.text);
        else ids.push(`<${expression.getText(sourceFile)}>`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return { source, texts, effects, ids };
}

test("area gates: no run, capability record absent, capabilities not read: reason only, no controls, no numbers", () => {
  for (const [props, id, state] of [[{ runId: null }, "reaction-no-run", "unavailable"],
    [{ capability: null }, "reaction-unavailable", "unavailable"], [{ capability: undefined }, null, "loading"]]) {
    const html = render(props);
    assert.match(tagOf(html, "reaction-panel"), new RegExp(`data-reaction-state="${state}"`), JSON.stringify(props));
    if (id) assert.ok(html.includes(`data-testid="${id}"`), id);
    assert.ok(!/<(input|select|button|table|a|details|pre) /.test(html), html);
    assert.ok(!/\d/.test(textLines(html).join("\n")));
  }
  assert.ok(render({ runId: null }).includes(lib.NO_RUN_REASON));
  assert.ok(render({ capability: null }).includes(lib.CAPABILITY_REASON));
});

test("first render with a capability record (even without a snapshot): blocks in order, request closed, nothing chosen", () => {
  for (const capability of [CAPABILITY, { ...CAPABILITY, available: true, reason_code: null, reason: null }]) {
    const html = render({ capability });
    // a missing snapshot is not the area's "사용할 수 없음": the area loads, the request block waits for the status
    assert.match(tagOf(html, "reaction-panel"), /data-reaction-state="loading"/);
    assert.deepEqual([...html.matchAll(/data-reaction-area="([a-z]+)"/g)].map(match => match[1]),
      ["snapshot", "request", "results"]);
    assert.ok(html.includes('data-testid="reaction-request-unavailable"'));
    assert.ok(decode(html).includes(lib.STATUS_LOADING_REASON));
    for (const id of ["reaction-structure", "reaction-link", "reaction-result", "reaction-detail", "reaction-report",
      "reaction-pdb-id", "reaction-numbering-map"]) assert.ok(!html.includes(`data-testid="${id}"`), id);
    assert.ok(!/<(input|select|table) /.test(html));
    const ids = [...html.matchAll(/data-testid="([^"]+)"/g)].map(match => match[1]);
    for (const id of ids) assert.ok(id.startsWith("reaction-"), id);
    assert.deepEqual(plain(lib.reactionForbiddenWords(textLines(html).join("\n"))), []);
    assert.ok(!/molstar|<canvas/i.test(html));
  }
});

test("panel source: wording, test ids, reads on mount only, one call site per write, nothing sorted or computed", () => {
  const { source, texts, effects, ids } = scan(SOURCE_FILE);
  // Every literal the component can render passes the M26 wording check (fixed RK / UK lines come from the lib).
  assert.ok(texts.length > 120, String(texts.length));
  for (const text of texts) assert.deepEqual(plain(lib.reactionForbiddenWords(text)), [], text);
  assert.ok(!/dangerouslySetInnerHTML|innerHTML|localStorage|sessionStorage/.test(source));
  // Every test id carries the area prefix (the ErrorLine / FieldErrors pass-through aside).
  for (const id of ids) assert.ok(id === "<testId>" || id.startsWith("reaction-"), id);
  assert.ok(ids.length > 50, String(ids.length));
  // Effects (mount = entering the tab, the opened result's pages) only read: no link, report, choice or confirmation.
  assert.ok(effects.length >= 7, String(effects.length));
  const reads = new Set(["reactionReferenceStatus", "allEvents", "numberingMaps", "reactionKnowledgeResults",
    "reactionKnowledgeResult"]);
  for (const body of effects) {
    for (const match of body.matchAll(/api\.(\w+)\(/g)) assert.ok(reads.has(match[1]), match[1]);
    assert.ok(!/\b(link|makeReport|chooseStructure|setConfirmed|readLookup|openResult|setOpened)\(/.test(body), body);
    assert.ok(!/pdbIdConfirmed: true|selected: true|numberingMap:/.test(body), body);
  }
  // Each writing request has one call site, reached from a person's click.
  for (const name of ["linkReactionKnowledge", "createReactionKnowledgeReport"])
    assert.equal([...source.matchAll(new RegExp(`api\\.${name}\\(`, "g"))].length, 1, name);
  assert.equal([...source.matchAll(/onClick=\{\(\) => void makeReport\(\)\}/g)].length, 1);
  assert.equal([...source.matchAll(/onLink=\{\(\) => void link\(\)\}/g)].length, 1);
  // The accession suggestion goes into the field only on its button; the PDB lookup only after the confirmation.
  assert.ok(/onClick=\{\(\) => p\.onAccession\(choice\.chain_auth, suggestion\.accession\)\}/.test(source));
  assert.ok(/if \(checked && pdbId !== null && installed\) readLookup\(pdbId\);/.test(source));
  // Late answers: every apply is behind run + result handle + the area's request number.
  assert.ok(/reactionResponseCurrent\(captured, \{ runId, handle: handleOf\(area\), seq: seqs\.current\[area\] \}\)/
    .test(source));
  // Values are shown through the lib view models only: no sorting, bars or arithmetic on stored values.
  assert.ok(!/\.sort\(|\.reverse\(|toFixed\(|<progress|<meter|style=|Math\./.test(source));
  assert.ok(/reactionResultView\(detail\)/.test(source) && /reactionSnapshotView\(statusValue\)/.test(source));
  // Fixed sentences are never retyped here.
  for (const sentence of [...Object.values(lib.REACTION_STATEMENTS), ...Object.values(lib.REACTION_SCREEN_NOTES)])
    assert.ok(!source.includes(sentence.slice(0, 20)), sentence);
  // No viewer, saved view or bridge.
  assert.ok(!/MolstarViewer|molstar|viewer-agent|saved-scene|captureScene/.test(source));
});

test("knowledge tab: the reaction area sits below numbering and above JEV, keyed by run, only while the tab is shown", () => {
  const renderTabs = props => renderToStaticMarkup(React.createElement(workspaceTabs.WorkspaceTabs, { active: "knowledge",
    onSelect: () => undefined, runId: "run_1", budget: null, structure: React.createElement("div", null, "S"),
    numbering: React.createElement("div", null, "N"), reaction: React.createElement("div", null, "K"),
    jev: React.createElement("div", null, "J"), reports: React.createElement("div", null, "R"), ...props }));
  const html = renderTabs({});
  const order = ["mw-app-numbering", "mw-app-reaction", "mw-app-jev", "mw-app-reports"]
    .map(name => html.indexOf(`class="${name}"`));
  assert.ok(order.every(index => index > 0) && order.every((index, i) => i === 0 || order[i - 1] < index), order.join());
  for (const active of ["structure", "protein", "ligand"]) assert.ok(!renderTabs({ active }).includes("mw-app-reaction"), active);
  const page = fs.readFileSync(path.join(__dirname, "../app/page.tsx"), "utf8");
  assert.ok(page.includes('import { ReactionKnowledgePanel } from "@/components/ReactionKnowledgePanel";'));
  assert.ok(page.includes("reaction={<ReactionKnowledgePanel key={`reaction-${run?.run_id ?? \"none\"}`} runId={run?.run_id ?? null}"));
  assert.ok(/capability=\{capabilities \? capabilities\.methods\?\.reaction_knowledge \?\? null : undefined\}/.test(page));
  const index = fs.readFileSync(path.join(COMPONENTS, "index.ts"), "utf8");
  assert.ok(!/Panel/.test(index));   // panels are imported by path, as before
});

test("M20 area: catalytic choice is offered, pre-selected only by the lib rule, never submitted; v2 reasons and marks", () => {
  const { source, texts, effects } = scan(path.join(COMPONENTS, "MutationPanel.tsx"));
  for (const text of texts) assert.deepEqual(plain(mutations.mutationForbiddenWords(text)), [], text);
  // The structure choice passes this run's reaction results to the lib pre-selection; nothing submits by itself.
  assert.ok(source.includes("draftForStructure(previous, handle, annotationRows, mapRows, reactionRows)"));
  assert.ok(source.includes('data-testid="mutation-catalytic-annotation"'));
  assert.equal([...source.matchAll(/api\.generateMutationCandidates\(/g)].length, 1);
  for (const body of effects) assert.ok(!/generate\(|generateMutationCandidates|catalyticAnnotation:/.test(body), body);
  // The six v1 exclusion reasons are no longer hard-coded: the stored set's own reasons (v1 six, v2 seven).
  assert.ok(!/\bEXCLUSION_REASONS\b/.test(source));
  assert.ok(/exclusionReasonsOf\(opened\.result\.counts\)/.test(source) && /exclusionReasonsOf\(counts\)/.test(source));
  assert.ok(/catalyticRequestNotices\(/.test(source) && /catalyticCheckView\(check\)/.test(source) &&
    /catalyticProtectionText\(row\.protection\)/.test(source));
  for (const id of ["mutation-set-catalytic", "mutation-catalytic-notice", "mutation-catalytic-check",
    "mutation-catalytic-check-badge"]) assert.ok(source.includes(id), id);
  // A failed reaction knowledge list read never blocks M20: no result to choose (lib catalyticChoices), its error beside
  // the catalytic select, not the panel's failure; a failed detail read keeps the UK2 notices and the request possible.
  assert.ok(source.includes("const reactionChoices = catalyticChoices(reactionResults);"));
  assert.ok(/const reactionRows = reactionChoices\.rows;/.test(source) && /reactionChoices\.settled;/.test(source));
  assert.ok(!/reactionResults\.status === "ready"/.test(source));
  const readError = source.slice(source.indexOf("const readError ="), source.indexOf("const panelState ="));
  assert.ok(readError.includes("[events, pocketSets, maps, annotations, sets]") && !readError.includes("reactionResults"));
  assert.ok(/reactionChoices\.error && <ErrorLine message=\{reactionChoices\.error\} testId="mutation-catalytic-list-error"/
    .test(source));
  assert.ok(/detailFailed: catalyticFailed/.test(source));
  assert.ok(/<p className="mw-mutation-note" data-testid="mutation-reason-counts">[^]*?exclusionReasonCountText\(counts, reason, /
    .test(source));
});

test("other candidate-set pickers carry only the shared mark from catalyticBadge (M21, M23, M24, M25)", () => {
  for (const [file, prefix] of [["SequenceGaPanel.tsx", "sequence-ga-catalytic"], ["JevPanel.tsx", "jev-source-catalytic"],
    ["JevLoopPanel.tsx", "jev-loop-source-catalytic"]]) {
    const source = fs.readFileSync(path.join(COMPONENTS, file), "utf8");
    assert.ok(/catalyticBadge\(/.test(source) && source.includes(`data-testid="${prefix}"`), file);
    assert.ok(!source.includes(mutations.CATALYTIC_NOT_CHECKED_BADGE.slice(0, 24)), file);   // UK2 is never retyped
  }
  const model = fs.readFileSync(path.join(COMPONENTS, "MutationModelPanel.tsx"), "utf8");
  assert.ok(model.includes('data-testid="mutation-model-catalytic"') && !/catalyticBadge|@\/lib\/mutations"/.test(model));
  // The badge itself: nothing for checked, UK2 for v1 not_available and v2 not_checked, each with its own detail.
  assert.equal(mutations.catalyticBadge("checked"), null);
  const v1 = mutations.catalyticBadge("not_available"), v2 = mutations.catalyticBadge("not_checked", "chains_not_covered");
  assert.equal(v1.text, v2.text);
  assert.notEqual(v1.detail, v2.detail);
});
