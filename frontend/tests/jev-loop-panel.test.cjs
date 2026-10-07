// M25 T9 screen: the JEV loop areas compiled from source and rendered on the server (effects do not run, so no request
// is made), source checks of what the component can render and request, the page mounts, the knowledge-tab loop row
// wiring and the M21 pair-table loop mark. The pure decisions are tested in tests/jev-loop.test.cjs.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function load(filename, dependencies = {}, sandbox = {}) {
  const source = fs.readFileSync(path.join(__dirname, `../src/lib/${filename}.ts`), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const moduleObject = { exports: {} };
  vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, URLSearchParams, ...sandbox,
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
const eventModel = load("event-model");
const siteAnnotation = load("site-annotation", { "./comparison": load("comparison"), "./numbering": load("numbering"),
  "./event-model": eventModel });
const docking = load("docking", { "./site-annotation": siteAnnotation });
const mutationModel = load("mutation-model", { "./site-annotation": siteAnnotation, "./docking": docking });
const jev = load("jev", { "./site-annotation": siteAnnotation }, { crypto: globalThis.crypto });
const lib = load("jev-loop", { "./docking": docking, "./jev": jev, "./mutation-model": mutationModel });
const ligandLib = load("ligand", { "./site-annotation": siteAnnotation });
const mutationsLib = load("mutations", { "./site-annotation": siteAnnotation, "./event-model": eventModel });
const primitives = compileTsx("../src/components/primitives.tsx", { "@/lib/contracts": load("contracts") });
const noRequest = () => { throw new Error("a server render makes no request"); };
const apiStub = { api: new Proxy({}, { get: () => noRequest }), ApiError: class ApiError extends Error {} };
const ligandPanel = compileTsx("../src/components/LigandPanel.tsx", { "@/lib/api": apiStub, "@/lib/ligand": ligandLib,
  "./primitives": primitives });
const modelPanel = compileTsx("../src/components/MutationModelPanel.tsx", { "@/lib/api": apiStub,
  "@/lib/docking": docking, "@/lib/ligand": ligandLib, "@/lib/mutation-model": mutationModel, "./primitives": primitives });
const loopPanel = compileTsx("../src/components/JevLoopPanel.tsx", { "@/lib/api": apiStub, "@/lib/docking": docking,
  "@/lib/jev": jev, "@/lib/jev-loop": lib, "@/lib/ligand": ligandLib, "@/lib/mutations": mutationsLib,
  "@/lib/mutation-model": mutationModel, "./LigandPanel": ligandPanel, "./MutationModelPanel": modelPanel,
  "./primitives": primitives });
const plain = value => JSON.parse(JSON.stringify(value));
const RUN = { run_id: "fixture-run", goal: "", context: [], dry_run: false, egress: "local_only", last_seq: 1 };
const AVAILABLE = { available: true, reason_code: null, reason: null };
const BOTH = { ligand: AVAILABLE, protein: AVAILABLE };
const render = props => renderToStaticMarkup(React.createElement(loopPanel.JevLoopPanel,
  { branch: "ligand", run: RUN, capability: BOTH, onReportCreated: () => undefined, ...props }));
const decode = text => text.replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
  .replace(/&amp;/g, "&");
const textLines = html => decode(html.replace(/<[^>]+>/g, "\n")).split("\n").map(line => line.trim()).filter(Boolean);
const tagOf = (html, testId) => new RegExp(`<[a-z]+ [^>]*data-testid="${testId}"[^>]*>`).exec(html)?.[0] ?? "";
const SOURCE_FILE = path.join(__dirname, "../src/components/JevLoopPanel.tsx");
const SOURCE = fs.readFileSync(SOURCE_FILE, "utf8");

test("loop area gates: no run, capability absent, branch unavailable, not read: reason only, no controls", () => {
  const unavailable = { ...BOTH, protein: { available: false, reason_code: "engine_missing", reason: "엔진이 없다." } };
  for (const branch of ["ligand", "protein"]) {
    for (const [props, id, state] of [[{ run: null }, "jev-loop-no-run", "unavailable"],
      [{ capability: null }, "jev-loop-unavailable", "unavailable"], [{ capability: undefined }, null, "loading"]]) {
      const html = render({ branch, ...props });
      assert.match(tagOf(html, "jev-loop-panel"), new RegExp(`data-jev-loop-state="${state}"`), JSON.stringify(props));
      assert.match(tagOf(html, "jev-loop-panel"), new RegExp(`data-branch="${branch}"`));
      if (id) assert.ok(html.includes(`data-testid="${id}"`), id);
      assert.ok(!/<(input|select|button|table|a|details|pre) /.test(html), html);
      assert.ok(!/\d/.test(textLines(html).join("\n")));
    }
  }
  const html = render({ branch: "protein", capability: unavailable });
  assert.ok(html.includes('data-testid="jev-loop-unavailable"') && html.includes("(engine_missing)"));
  assert.ok(!/<(input|select|button) /.test(html));
  assert.match(tagOf(render({ branch: "ligand", capability: unavailable }), "jev-loop-panel"), /data-jev-loop-state="loading"/);
});

test("loop area first render: consent, create and list areas; nothing chosen; create closed; notes; wording; test ids", () => {
  for (const branch of ["ligand", "protein"]) {
    const html = render({ branch });
    assert.deepEqual([...html.matchAll(/data-jev-loop-area="([a-z]+)"/g)].map(match => match[1]),
      ["status", "create", "loops"], branch);
    assert.match(tagOf(html, "jev-loop-create"), /disabled=""/);
    for (const goal of ["explore", "exploit"]) assert.ok(!/checked/.test(tagOf(html, `jev-loop-goal-${goal}`)), goal);
    assert.match(tagOf(html, "jev-loop-seed"), /value=""/);
    assert.match(tagOf(html, "jev-loop-iteration-cap"), /value="5"/);
    for (const id of ["jev-loop-source", "jev-loop-candidate", "jev-loop-consent", "jev-loop-open", "jev-loop-record",
      "jev-loop-send", "jev-loop-preview", "jev-loop-choice-card"])
      assert.ok(!html.includes(`data-testid="${id}"`), id);
    const lines = textLines(html);
    for (const line of [lib.LOOP_SCREEN_NOTES.UL1, lib.LOOP_SCREEN_NOTES.UL3, lib.FREE_DOCKING_NOTE, lib.POOL_FIXED_NOTE,
      lib.LOOP_SEED_NOTE, lib.GOAL_MEANING.explore, lib.GOAL_MEANING.exploit]) assert.ok(lines.includes(line), line);
    assert.equal(lines.includes(lib.PROTEIN_SCREEN_NOTE), branch === "protein");
    assert.deepEqual(plain(lib.jevLoopForbiddenWords(lines.join("\n"))), [], branch);
    const ids = [...html.matchAll(/data-testid="([^"]+)"/g)].map(match => match[1]);
    assert.ok(ids.length >= 15, String(ids.length));
    for (const id of ids) assert.ok(id.startsWith("jev-loop-"), id);
    assert.ok(!/molstar|<canvas/i.test(html));
  }
  // The protein setup reuses the M21 inputs with its own prefix: a 3D SDF only, the candidate source closed.
  const protein = render({ branch: "protein" });
  assert.ok(protein.includes('data-testid="jev-loop-setup-form"') && protein.includes('data-testid="jev-loop-cutoff"'));
  assert.match(tagOf(protein, "jev-loop-cutoff"), /value="4.0"/);
  assert.ok(/data-pair-ligand-source="candidate" data-disabled-reason="[^"]+"/.test(protein));
});

test("loop area source: wording, test ids, reads on mount only, one call site per press, nothing sorted or computed", () => {
  const sourceFile = ts.createSourceFile(SOURCE_FILE, SOURCE, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
  const texts = [], effects = [], ids = [];
  const visit = node => {
    if (ts.isJsxText(node) && node.text.trim()) texts.push(node.text.trim());
    else if (ts.isStringLiteral(node) && !ts.isImportDeclaration(node.parent)) texts.push(node.text);
    else if (ts.isNoSubstitutionTemplateLiteral(node)) texts.push(node.text);
    else if (ts.isTemplateExpression(node)) texts.push(node.head.text, ...node.templateSpans.map(span => span.literal.text));
    if (ts.isCallExpression(node) && node.expression.getText(sourceFile) === "useEffect")
      effects.push(node.arguments[0].getText(sourceFile));
    if (ts.isJsxAttribute(node) && ["data-testid", "testId", "idPrefix"].includes(node.name.getText(sourceFile))) {
      const value = node.initializer;
      if (value && ts.isStringLiteral(value)) ids.push(value.text);
      else if (value && ts.isJsxExpression(value) && value.expression) {
        const expression = value.expression;
        if (ts.isTemplateExpression(expression)) ids.push(expression.head.text || `<${expression.getText(sourceFile)}>`);
        else if (ts.isConditionalExpression(expression)) ids.push(expression.whenTrue.text, expression.whenFalse.text);
        else ids.push(`<${expression.getText(sourceFile)}>`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  // Every literal the component can render passes the loop wording check (no rank, recommendation, comparison ...).
  assert.ok(texts.length > 150, String(texts.length));
  for (const text of texts) assert.deepEqual(plain(lib.jevLoopForbiddenWords(text)), [], text);
  assert.ok(!/dangerouslySetInnerHTML|innerHTML|localStorage|sessionStorage/.test(SOURCE));
  for (const id of ids) assert.ok(["<testId>", "<`${testId}-blocked`>"].includes(id) || id.startsWith("jev-loop"), id);
  assert.ok(ids.length > 60, String(ids.length));
  // Effects (mount = entering the tab, polling, a candidate page, the selection's proposal) only read.
  assert.ok(effects.length >= 8, String(effects.length));
  const reads = new Set(["jevStatus", "jevLoops", "dockingPrerequisites", "mutationCandidateSets", "ligandCandidateRows",
    "mutationCandidates", "dockingReceptorInstances"]);
  for (const body of effects) {
    for (const match of body.matchAll(/api\.(\w+)\(/g)) assert.ok(reads.has(match[1]), match[1]);
    assert.ok(!/\b(createLoop|buildProjection|sendLoopBody|computeWith|computeProposal|computeDesignated|computeDock|resumeJob|approveFirstCall|cancelJob|abandonDocking|endLoop|makeReport|changeConsent|chooseSource|toggle|openLoop|showLoop|setSelection|setDesignated|setConfirmedFor|setComputeConfirmedFor|setSettings)\(/
      .test(body), body);
  }
  // Each press has one call site (the preview read too); the send and the compute start are never aborted.
  for (const name of ["createJevLoop", "buildJevLoopProjection", "jevPreview", "jevSend", "jevLoopCompute",
    "jevLoopAbandonDocking", "jevLoopEnd", "createJevLoopReport", "jevSetConsent", "approveOpenmm", "cancelJob"])
    assert.equal([...SOURCE.matchAll(new RegExp(`api\\.${name}\\(`, "g"))].length, 1, name);
  assert.ok(SOURCE.includes("const sent = await api.jevSend(runId, jevSendRequest(attempt));"));
  assert.ok(SOURCE.includes("const value: unknown = await api.jevLoopCompute(runId, loopId, body);"));
  assert.ok(/const attempt = jevSendAttempt\(attemptRef\.current, previewValue\);/.test(SOURCE));
  assert.ok(/jevAttemptAfter\(attempt, \{ record: true \}\)/.test(SOURCE));
  assert.equal([...SOURCE.matchAll(/onClick=\{\(\) => void sendLoopBody\(\)\}/g)].length, 1);
  assert.ok(/disabled=\{!canSend\}/.test(SOURCE) && /const confirmed = jevConfirmed\(confirmedFor, previewValue\);/.test(SOURCE));
  // Late answers: every apply is behind run + loop + iteration + per-area request number.
  assert.ok(/loopResponseCurrent\(captured, liveStamp\(area, seqs\.current\[area\]\)\)/.test(SOURCE));
  // Values are shown through the view models only: no sorting, bars, colours or arithmetic on scores here.
  assert.ok(!/\.sort\(|<progress|<meter|style=|width:/.test(SOURCE));
  assert.deepEqual([...SOURCE.matchAll(/Math\.\w+/g)].map(match => match[0]), ["Math.max"]);   // the pager's offset only
  assert.ok(!/\.score(_kcal_mol)?\s*[-+*/<>]|[-+*/]\s*\w+\.score/.test(SOURCE));
  assert.ok(/sortLoopCandidates\(loopCandidateRows\(record\), sort\)/.test(SOURCE) && /row\.scoreText/.test(SOURCE));
  // The exact body and the probabilities are collapsed; the body is shown verbatim from the preview.
  assert.ok(!/<details[^>]*\bopen\b/.test(SOURCE));
  assert.ok(SOURCE.includes('<pre className="mw-jev-body" data-testid="jev-loop-preview-body">{view.body}</pre>'));
  // No viewer, no science send entry other than the M24 route call, no limit raise; the M17 filter and the M21 inputs.
  assert.ok(!/MolstarViewer|molstar|viewer-agent|saved-scene|request_science|run_send|raise_limits|limit_approval/.test(SOURCE));
  assert.ok(/<FilterForm idPrefix="jev-loop"/.test(SOURCE) && /<PairInputs form=\{form\} update=\{update\}/.test(SOURCE));
  // The read polling interval is the loop constant (2 s).
  assert.ok(/window\.setInterval\(\(\) => \{ readRecord\(\); if \(pollStatus\.current\) readStatus\(\); \}, LOOP_POLL_MS\)/
    .test(SOURCE));
  // T11 fix: a record read asked for while one is in flight is kept and read once more (never skipped); a send that
  // answered keeps the reads going until the record shows it ended; the card is judged by the lib from that record.
  assert.ok(/const request = loopReadRequest\(readQueue\.current, loopId\);/.test(SOURCE) &&
    /const settled = loopReadSettled\(readQueue\.current, loopId\);/.test(SOURCE) &&
    /if \(settled\.again !== null && mounted\.current\) readRecord\(settled\.again\);/.test(SOURCE));
  assert.ok(!/recordReading/.test(SOURCE));
  assert.ok(/!loopRecordReflectsSend\(recordValue, awaitedSend\.sendId, awaitedSend\.status\)/.test(SOURCE) &&
    /computeBusy \|\| sendPolling \|\| sendUnseen\)/.test(SOURCE));
  assert.ok(/view\.state === "confirming"/.test(SOURCE) && SOURCE.includes('data-testid="jev-loop-choice-confirming"') &&
    SOURCE.includes("{card.roleText}") && !/의 선택이 아님/.test(SOURCE));
});

test("page: one loop area per tab after the GA areas, keyed by branch and run; the knowledge tab gets the loop mark", () => {
  const page = fs.readFileSync(path.join(__dirname, "../app/page.tsx"), "utf8");
  const protein = page.indexOf("protein={<>"), ligand = page.indexOf("ligand={<>");
  const m23 = page.indexOf("<SequenceGaPanel "), m22 = page.indexOf("<LigandGaPanel ");
  const loopProtein = page.indexOf('<JevLoopPanel key={`jev-loop-protein-${run?.run_id ?? "none"}`} branch="protein"');
  const loopLigand = page.indexOf('<JevLoopPanel key={`jev-loop-ligand-${run?.run_id ?? "none"}`} branch="ligand"');
  assert.ok(protein > 0 && protein < m23 && m23 < loopProtein && loopProtein < ligand, [protein, m23, loopProtein, ligand].join());
  assert.ok(ligand < m22 && m22 < loopLigand && loopLigand < page.indexOf("onSelect={tab =>"), [ligand, m22, loopLigand].join());
  assert.equal([...page.matchAll(/capability=\{capabilities \? capabilities\.methods\?\.jev_loop \?\? null : undefined\}/g)]
    .length, 2);
  assert.ok(page.includes('import { JevLoopPanel } from "@/components/JevLoopPanel";'));
  assert.ok(page.includes("sendHistoryMark={loopSendHistoryMark} />}") &&
    page.includes('import { loopSendHistoryMark } from "@/lib/jev-loop";'));
  assert.equal([...page.matchAll(/api\.jev\w+\(/g)].length, 1);   // the page itself still makes only its status read
  const tabs = fs.readFileSync(path.join(__dirname, "../src/components/WorkspaceTabs.tsx"), "utf8");
  assert.ok(!/JevLoop|jev_loop/.test(tabs));
  // JevPanel takes the mark as a prop (no new import); its M24 rows keep their buttons, a loop row gets none.
  const panel = fs.readFileSync(path.join(__dirname, "../src/components/JevPanel.tsx"), "utf8");
  assert.ok(!/from "@\/lib\/jev-loop"/.test(panel));
  assert.ok(/loopMark \? <span className="mw-jev-note" data-testid="jev-send-loop-guide">\{loopMark\.guide\}<\/span> : <>/
    .test(panel));
});

test("M21 pair table: a loop docking group carries the loop mark; every other group has none", () => {
  const condition = { ligand: { source: "sdf", sdf_handle: "obj://r/chemical_raw_input/l" }, mode: "free",
    box: { source: "ligand_range", margin_A: 8 }, parameters: { seed: 7, exhaustiveness: 8, num_modes: 9, energy_range: 3,
      conformers: null }, method_pins_sha256: "p" };
  const side = (name, over = {}) => ({ side: name, job_id: "j", job_status: "done", submitted_seq: 1, result_handle: null,
    score_kcal_mol: null, score_mode: null, reason_code: "other_side_missing", reason: "r", ...over });
  const pair = (index, over = {}) => ({ index, first_submitted_seq: index, condition, both_published: false,
    sides: { wild_type_reference: side("wild_type_reference", { job_status: "not_submitted", reason_code: "not_submitted" }),
      mutant: side("mutant") }, ...over });
  const rows = plain(mutationModel.pairRows({ pairs: [pair(0), pair(1, { loop: { loop_id: "x", iteration: 2 } })] }));
  assert.equal(rows[0].loopText, null);
  assert.equal(rows[1].loopText, "루프 도킹(야생형 없음) · 바퀴 2");
  assert.equal(mutationModel.PAIR_LOOP_TEXT, "루프 도킹(야생형 없음)");
  // The rest of the row is the server's as before (no reason added, no number on the scoreless sides).
  assert.deepEqual(rows[1].cells, rows[0].cells);
  assert.deepEqual(plain(mutationModel.modelForbiddenWords(rows[1].loopText)), []);
  const source = fs.readFileSync(path.join(__dirname, "../src/components/MutationModelPanel.tsx"), "utf8");
  assert.ok(source.includes('data-pair-loop={row.loopText === null ? undefined : "true"}') &&
    source.includes('data-testid="mutation-model-pair-loop"'));
});
