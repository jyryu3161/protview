"use strict";

// M17 ligand partial-replacement candidate offscreen QA (spec §12.4). Real Electron offscreen page (isOffscreen,
// GPU/WebGL, paint). Every product mutation is a Playwright locator mouse/keyboard/file-chooser/select input; DOM
// .click() and product handlers are never called. Observation is read-only: data attributes and text of the page,
// renderer request/response events, Electron paint frames, downloaded bytes and GET reads of the loopback API.
// A labeled renderer-route fixture (held late response) is recorded in the ledger and never produces a value.
//
// Independent oracle: backend/tests/fixtures/ligand/expected.json (T1, hand-derived; RDKit only canonicalised the
// hand-written SMILES): explicit-H parent heavy serials and bonds, block library summaries, rule validity, product
// SMILES of the methoxy site, heavy-atom counts and molecular weights. Candidate ids are re-derived here with SHA-256.
//
// Modes (the full sequence: scripts/m17_offscreen_acceptance.py):
//   main         run (구조 분석: 새 run + 1MQ4) → 리간드 탭 → parent/block files + rules → import → inspection job
//                (approval UI) → numbered 2D figure + atom table → site reject/pass → enumeration job → candidate table
//                vs the oracle → filters (boundaries), passes-only, sort → report + 지식·보고서 list + downloads →
//                zero-candidate set → invalid rules → paging (labeled generated chain library) → structure tab kept
//                mounted → run switch with a held late response
//   unavailable  backend started from a layout without the locked RDKit environment (runner): no-run and
//                capability-unavailable states show a reason only (no numbers, no controls)
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const { waitForViewer } = require("./normal-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const FIXTURES = path.join(REPO, "backend/tests/fixtures");
const LIGAND = path.join(FIXTURES, "ligand");
const STRUCTURE = path.join(FIXTURES, "public_1mq4.cif");
const PARENT_H = path.join(LIGAND, "synthetic-parent-methacetin-explicit-h.sdf");
const BLOCKS_SDF = path.join(LIGAND, "synthetic-blocks.sdf");
const BLOCKS_SMI = path.join(LIGAND, "synthetic-blocks.smi");
const RULES_JSON = path.join(LIGAND, "synthetic-reaction-rules.json");
const EXPECTED = path.join(LIGAND, "expected.json");
const MODES = ["main", "unavailable"];
const TAB = "리간드 설계·탐색";
// Rules typed into the textarea, in this order (rule_id user_<n> follows the typed order):
// fixture rules 1, 2, 3 (valid), 4 (reactant_count), 7 (reaction_parse_failed), 8 (duplicate of 1 → duplicate_rule).
const RULE_PICK = [1, 2, 3, 4, 7, 8];
const RULE_EXPECTED = ["valid", "valid", "valid", "reactant_count", "reaction_parse_failed", "duplicate_rule"];
const CHAIN_COUNT = 60;
const CHAIN_LABEL = "QA-GENERATED SYNTHETIC building-block list (labeled; written by ligand-flow.cjs for paging, "
  + "not a scientific input): *C…C chains of 1–60 carbons";
const HOLD_LABEL = "QA held-response fixture (labeled renderer route; unchanged backend bytes released late)";
const UNAVAILABLE_LABEL = "labeled runtime layout without .deps/prolif/venv-locked (runner): capability worker_missing";
const PROVIDER_EVENT_TYPES = new Set(["egress", "egress_budget_settled", "viewer_dispatch_started"]);
const NO_RUN_REASON = "구조 분석 탭에서 run을 먼저 고르세요.";

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const shortHandle = handle => handle.split("/").at(-1).slice(0, 12);
const candidateId = smiles => `c_${sha(Buffer.from(smiles, "utf8")).slice(0, 16)}`;
const nonZero = counts => Object.fromEntries(Object.entries(counts ?? {}).filter(([, count]) => count !== 0));
const sameSet = (a, b) => a.length === b.length && [...a].sort().every((value, i) => value === [...b].sort()[i]);

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, "fixture-label": null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2);
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode)) throw new Error(
    `Usage: ligand-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> [--url http://127.0.0.1:3000] ` +
    "[--fixture-label <runtime layout label>]. main needs the locked RDKit environment; unavailable needs a backend " +
    "without it and a fresh runs root. Full sequence: scripts/m17_offscreen_acceptance.py.");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  value.artifacts = path.resolve(value.artifacts);
  value.url = new URL("/", value.url).toString();
  return value;
}

// ------------------------------------------------------------------ independent oracle (T1 expected.json)
function oracle() {
  const expected = JSON.parse(fs.readFileSync(EXPECTED, "utf8"));
  const rules = JSON.parse(fs.readFileSync(RULES_JSON, "utf8")).rules;
  const gen = expected.generation_with_site_methoxy;
  const names = gen.union_unique_candidates_fixed_plus_valid_rules_both_libraries;
  const props = expected.properties;
  const smilesOf = name => props[name].canonical_smiles;
  const explicit = expected.parents.explicit_h;
  // heavy-atom adjacency of the explicit-H parent from the hand bond list (SDF serials)
  const adjacency = new Map(explicit.heavy_atoms.map(atom => [atom.serial, []]));
  for (const [a, b] of explicit.bonds_heavy) { adjacency.get(a).push(b); adjacency.get(b).push(a); }
  for (const list of adjacency.values()) list.sort((x, y) => x - y);
  return {
    files: [EXPECTED, RULES_JSON].map(fileRecord),
    ruleTexts: RULE_PICK.map(index => rules[index - 1]),
    explicit, adjacency,
    blocks: { building_blocks_sdf: expected.block_libraries.sdf.summary, building_blocks_smiles: expected.block_libraries.smiles.summary },
    candidates: names.map(name => ({ name, smiles: smilesOf(name), heavy: props[name].heavy_atoms.value,
      mw: Number(props[name].mol_weight.value) })),
    parentSmiles: smilesOf("parent_methacetin"),
    zeroSmiles: [],
    // hand-traced from expected.json outcomes (fixed both libraries + user_1..user_3 over both libraries)
    duplicates: { fixed_methyl: 3, phenacetin: 2 },
    rejected: { equals_parent: 2, outside_site: 2 },
  };
}

/** Labeled generated block list for the paging case (written into the artifacts folder, never committed). */
function chainLibrary(artifacts) {
  const file = path.join(artifacts, "qa-generated-chain-blocks.smi");
  const lines = [`# ${CHAIN_LABEL}`];
  for (let n = 1; n <= CHAIN_COUNT; n++) lines.push(`*${"C".repeat(n)} qa_chain_${n}`);
  fs.writeFileSync(file, lines.join("\n") + "\n");
  return file;
}

// ------------------------------------------------------------------ read-only observation
async function readApi(page, route) {
  const response = await page.request.get(new URL(`/api${route}`, page.url()).toString());
  assert.equal(response.status(), 200, `${route}: ${await response.text()}`);
  return response.json();
}
async function readBytes(page, route) {
  const response = await page.request.get(new URL(`/api${route}`, page.url()).toString());
  assert.equal(response.status(), 200, route);
  return Buffer.from(await response.body());
}
async function runEvents(page, run) {
  const events = [];
  let after = 0;
  for (;;) {
    const chunk = await readApi(page, `/runs/${run}/events?after=${after}&limit=500`);
    events.push(...chunk);
    if (chunk.length < 500) break;
    after = chunk.at(-1).seq;
  }
  return events;
}
async function providerCalls(page, run) {
  const events = await runEvents(page, run);
  const budget = await readApi(page, `/runs/${run}/budget`);
  const egress = events.filter(event => PROVIDER_EVENT_TYPES.has(event.type)).length;
  return { run, egressEvents: egress, externalTokensUsed: budget.external_tokens?.used ?? null,
    usdUsed: budget.usd?.used ?? null,
    zero: egress === 0 && (budget.external_tokens?.used ?? 0) === 0 && (budget.usd?.used ?? 0) === 0 };
}
async function waitFor(page, probe, label, timeout = 60000) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    try { last = await probe(); if (last) return last; } catch (error) { last = String(error); }
    await page.waitForTimeout(150);
  }
  throw new Error(`${label}: timed out; last=${JSON.stringify(last)?.slice(0, 800)}`);
}

async function offscreenProof(app, page) {
  const state = await app.evaluate(({ app: electronApp }) => electronApp.__offscreenQa.status());
  const webgl = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
    if (!gl) return null;
    const info = gl.getExtension("WEBGL_debug_renderer_info");
    return { version: gl.getParameter(gl.VERSION),
      renderer: info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER) };
  });
  let firstPaint = null;
  if (state.firstPaint?.path) {
    const bytes = fs.existsSync(state.firstPaint.path) ? fs.readFileSync(state.firstPaint.path) : null;
    firstPaint = { ...state.firstPaint, onDiskBytes: bytes?.length ?? null, onDiskSha256: bytes ? sha(bytes) : null };
  }
  return { offscreen: state.offscreen, visible: state.visible, painting: state.painting,
    hardwareAccelerationEnabled: state.hardwareAccelerationEnabled, paintCount: state.paintCount, firstPaint, webgl,
    nonLoopbackRequests: state.blockedRequests.length, blockedRequests: state.blockedRequests,
    loopbackRequestCount: state.loopbackRequestCount, versions: state.versions };
}
function offscreenComplete(proof) {
  return !!proof && proof.offscreen === true && proof.visible === false && proof.painting === true &&
    proof.hardwareAccelerationEnabled === true && proof.paintCount > 0 && !!proof.webgl &&
    !!proof.firstPaint && proof.firstPaint.onDiskBytes > 0 && proof.firstPaint.onDiskSha256 === proof.firstPaint.sha256;
}
function requestLog(page) {
  const rows = [];
  page.on("request", request => {
    const url = new URL(request.url());
    rows.push({ at: Date.now(), method: request.method(), path: url.pathname, api: url.pathname.startsWith("/api/") });
  });
  return rows;
}

// ------------------------------------------------------------------ evidence
function recorder(session, input, evidence) {
  const { app, page, artifacts } = session;
  const file = path.join(artifacts, `ligand-${input.mode}.jsonl`);
  const append = row => fs.appendFileSync(file, JSON.stringify(row) + "\n");
  const caseRows = {};
  const mark = (cases, ok) => { for (const id of cases) (caseRows[id] ??= []).push(ok); };
  async function step(caseId, cases, description, action, check) {
    const started = Date.now();
    let result;
    try {
      result = await action();
      const assertion = await check(result);
      const proof = await capture(app, page, artifacts, caseId);
      assert.equal(proof.status.blockedRequests.length, 0, "renderer attempted a non-loopback request");
      assert.equal(proof.status.offscreen, true);
      append({ caseId, cases, status: "pass", description, assertion: summarize(assertion),
        blockedRequests: proof.status.blockedRequests.length, paintCount: proof.status.paintCount,
        screenshot: fileRecord(proof.screenshot), paint: fileRecord(proof.paint.path), durationMs: Date.now() - started });
      mark(cases, true);
      return result;
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* keep the primary failure */ }
      const html = await page.evaluate(() => document.querySelector('[data-testid="ligand-panel"]')?.outerHTML.slice(0, 80000) ?? "")
        .catch(() => null);
      if (html) fs.writeFileSync(path.join(artifacts, `${caseId}-failure.panel.html`), html);
      append({ caseId, cases, status: "fail", description, error: String(error.stack ?? error),
        actionResult: result === undefined ? null : summarize(result), screenshot: proof && fileRecord(proof.screenshot),
        paint: proof && fileRecord(proof.paint.path), durationMs: Date.now() - started });
      mark(cases, false);
      throw error;
    }
  }
  /** An independent part: a failure is recorded (its cases fail) and the mode continues with the next part. */
  async function part(name, cases, work) {
    try { return await work(); } catch (error) {
      append({ caseId: `${name}-aborted`, cases: [], partCases: cases, status: "fail", description: `part ${name} aborted`,
        error: String(error.stack ?? error) });
      evidence.partFailures.push({ part: name, cases, error: String(error).slice(0, 800) });
      mark(cases, false);
      return null;
    }
  }
  const cases = () => Object.fromEntries(Object.entries(caseRows).map(([id, list]) =>
    [id, list.length && list.every(Boolean) ? "pass" : "fail"]));
  return { step, part, append, file, cases, app, page, artifacts };
}
function summarize(value) {
  try { const text = JSON.stringify(value); return text.length > 6000 ? `${text.slice(0, 6000)}…` : JSON.parse(text); }
  catch { return String(value); }
}
/** Every new control clicked at least once, with what was observed right after. */
function control(evidence, id, observed) { (evidence.controls[id] ??= []).push(observed); }

// ------------------------------------------------------------------ tabs, runs, structure screen
const tabButton = (page, label) => page.locator(".mw-app-tabs").getByRole("tab", { name: label, exact: true });
async function selectTab(page, label) {
  await tabButton(page, label).click();
  await waitFor(page, async () => await tabButton(page, label).getAttribute("aria-selected") === "true", `${label} selected`, 10000);
}
const globalRun = page => page.evaluate(() => document.querySelector(".mw-app-run")?.getAttribute("data-global-run") || null);
const snapshot = page => page.evaluate(() => typeof window.__protviewQaSnapshot === "function" ? window.__protviewQaSnapshot() : null);
async function waitForBoot(page) {
  const hasRuns = (await readApi(page, "/runs")).length > 0;
  await page.waitForFunction(existing => {
    const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "새 run");
    const selected = new URL(location.href).searchParams.get("run");
    return !!button && !button.disabled && (existing ? /^run_/.test(selected ?? "")
      : document.body.textContent?.includes("현재 사용 불가"));
  }, hasRuns, { timeout: 45000 });
}
async function newRun(page) {
  await page.getByRole("tab", { name: /^run/i }).click();
  const previous = new URL(page.url()).searchParams.get("run");
  await page.getByRole("button", { name: "새 run", exact: true }).click();
  await page.waitForFunction(old => {
    const current = new URL(location.href).searchParams.get("run");
    const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "새 run");
    return /^run_[a-f0-9]+$/.test(current ?? "") && current !== old && !!button && !button.disabled;
  }, previous, { timeout: 30000 });
  const run = new URL(page.url()).searchParams.get("run");
  await waitFor(page, async () => await globalRun(page) === run, "global run id", 10000);
  return run;
}
async function chooseRun(page, run, waitViewer = true) {
  await selectTab(page, "구조 분석");
  await page.getByRole("tab", { name: /^run/i }).click();
  await page.locator("#run-choice").selectOption(run);
  await waitFor(page, async () => await globalRun(page) === run, `run ${run} selected`, 30000);
  if (waitViewer) await waitForViewer(page, value => value.sourceHandle !== null && value.catalogReady === true, 60000);
}
async function uploadLoad(page, file) {
  await page.getByRole("tab", { name: /^run/i }).click();
  const before = (await snapshot(page))?.sourceHandle ?? null;
  const chooser = page.waitForEvent("filechooser", { timeout: 30000 });
  await page.locator('#mw-app-panel-structure input[type="file"]').first().click();
  await (await chooser).setFiles(file);
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).click();
  const viewer = await waitForViewer(page, value => !!value.sourceHandle && value.sourceHandle !== before &&
    value.sourceHandle.includes("/structure/") && value.catalogReady === true, 90000);
  return viewer.sourceHandle;
}
/** Viewer and structure-panel state (read only): the panel stays mounted (hidden) while another tab is shown. */
async function structureState(page) {
  const viewer = await snapshot(page);
  const dom = await page.evaluate(() => {
    const panel = document.querySelector("#mw-app-panel-structure");
    return { present: !!panel, shown: panel?.getAttribute("data-shown") ?? null, inert: panel?.hasAttribute("inert") ?? null,
      canvases: panel ? panel.querySelectorAll("canvas").length : 0,
      visibility: panel ? getComputedStyle(panel).visibility : null };
  });
  return { dom, sourceHandle: viewer?.sourceHandle ?? null, sessionId: viewer?.sessionId ?? null,
    generation: viewer?.generation ?? null, representation: viewer?.representation ?? null,
    ready: viewer?.ready ?? null, catalogReady: viewer?.catalogReady ?? null };
}

// ------------------------------------------------------------------ ligand panel (read-only helpers)
const panel = page => page.locator('#mw-app-panel-ligand [data-testid="ligand-panel"]');
const testId = (page, id) => panel(page).locator(`[data-testid="${id}"]`);
const panelState = page => panel(page).getAttribute("data-ligand-state", { timeout: 2000 }).catch(() => null);
const areaState = (page, area) => panel(page).locator(`[data-ligand-area="${area}"]`).getAttribute("data-state", { timeout: 2000 })
  .catch(() => null);
async function waitArea(page, area, states, timeout = 60000) {
  const wanted = Array.isArray(states) ? states : [states];
  return waitFor(page, async () => { const state = await areaState(page, area); return wanted.includes(state) ? state : null; },
    `${area} area ${wanted.join("|")}`, timeout);
}
async function openLigandTab(page) {
  await selectTab(page, TAB);
  await panel(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => ["ready", "scientific_null", "failure", "unavailable"].includes(await panelState(page))
    && await areaState(page, "inspections") !== "loading" && await areaState(page, "sets") !== "loading" ? true : null,
  "ligand panel settled", 60000);
}
async function chooseLigandFile(page, slot, file) {
  const chooser = page.waitForEvent("filechooser", { timeout: 15000 });
  await testId(page, `ligand-file-${slot}`).click();
  await (await chooser).setFiles(file);
}
async function jobPhase(page) {
  const job = testId(page, "ligand-job");
  if (!await job.count()) return null;
  return { phase: await job.getAttribute("data-ligand-job-phase"), status: await job.getAttribute("data-ligand-job-status"),
    id: await job.getAttribute("data-ligand-job-id"), protocol: await job.getAttribute("data-ligand-job-protocol") };
}
async function budgetUsed(page, run) { return (await readApi(page, `/runs/${run}/budget`)).expensive_calls; }
/**
 * Click the start control of a job (real input); approve through 비싼 계산 승인 when asked, then 작업 시작; wait for
 * the job to finish. Returns the observed phases, the job (backend) and the stored result handle.
 */
async function runLigandJob(page, run, startId, protocol, evidence) {
  const phases = [];
  const before = await budgetUsed(page, run);
  await testId(page, startId).click();
  control(evidence, startId, { clicked: true });
  // Settled = the next visible control is usable (the panel is not busy) or the job already runs/finished.
  const settled = async () => {
    const value = await jobPhase(page);
    if (!value || value.protocol !== protocol) return null;
    if (["running", "done", "failed", "cancelled"].includes(value.phase)) return value;
    if (value.phase === "awaiting_approval" && await testId(page, "ligand-job-approve").isEnabled().catch(() => false)) return value;
    if (value.phase === "saved" && await testId(page, "ligand-job-start").isEnabled().catch(() => false)) return value;
    return null;
  };
  const first = await waitFor(page, settled, `${protocol} job submitted`, 60000);
  phases.push(first.phase);
  let approved = false;
  if (first.phase === "awaiting_approval") {
    await testId(page, "ligand-job-approve").click();
    approved = true;
    const noticed = await waitFor(page, async () => { const value = await settled(); return value?.phase === "saved" ? value : null; },
      "approval recorded (job saved)", 30000);
    phases.push(noticed.phase);
    control(evidence, "ligand-job-approve", { phaseAfter: noticed.phase,
      notice: clean(await testId(page, "ligand-notice").textContent().catch(() => "")) });
  }
  if ((await jobPhase(page)).phase === "saved") {
    await testId(page, "ligand-job-start").click();
    control(evidence, "ligand-job-start", { clicked: true });
  }
  const done = await waitFor(page, async () => {
    const value = await jobPhase(page);
    if (value && value.phase !== phases.at(-1)) phases.push(value.phase);
    return value && ["done", "failed", "cancelled"].includes(value.phase) ? value : null;
  }, `${protocol} job finished`, 240000);
  const job = await readApi(page, `/runs/${run}/jobs/${enc(done.id)}`);
  const handle = job.artifacts?.ligand_inspection ?? job.artifacts?.ligand_candidate_set ?? null;
  if (done.phase === "done") {
    await testId(page, "ligand-result-notice").waitFor({ timeout: 30000 });
    await waitArea(page, protocol === "rdkit_inspect_v1" ? "inspections" : "sets", "ready", 30000);
  }
  return { phases, approved, job, handle, budgetBefore: before, budgetAfter: await budgetUsed(page, run),
    resultNotice: clean(await testId(page, "ligand-result-notice").textContent().catch(() => "")) };
}
async function selectInspection(page, handle) {
  const radio = panel(page).locator(`label[data-ligand-inspection="${handle}"] input[type="radio"]`);
  await radio.waitFor({ timeout: 30000 });
  await radio.check();
  await panel(page).locator(`[data-testid="ligand-inspection"][data-ligand-inspection-handle="${handle}"]`).waitFor({ timeout: 30000 });
}
async function selectSet(page, handle) {
  const radio = panel(page).locator(`label[data-ligand-candidate-set="${handle}"] input[type="radio"]`);
  await radio.waitFor({ timeout: 30000 });
  await radio.check();
  await panel(page).locator(`[data-testid="ligand-set-detail"][data-ligand-set-handle="${handle}"]`).waitFor({ timeout: 30000 });
}
const atomBox = (page, serial) => testId(page, "ligand-atoms").locator(`input[data-serial="${serial}"]`);
async function waitPreview(page, attrs, label) {
  const selector = `[data-testid="ligand-preview"]${Object.entries(attrs).map(([k, v]) => `[${k}="${v}"]`).join("")}`;
  await panel(page).locator(selector).waitFor({ timeout: 30000 });
  const node = panel(page).locator('[data-testid="ligand-preview"]');
  return { ready: await node.getAttribute("data-ligand-preview-ready"), valid: await node.getAttribute("data-site-valid"),
    reason: await node.getAttribute("data-site-reason"), text: clean(await node.textContent()), label };
}
async function startState(page, id) {
  const button = testId(page, id);
  return { enabled: await button.isEnabled(), title: await button.getAttribute("title"),
    blocked: clean(await testId(page, id.replace("-start", "-blocked")).textContent().catch(() => "")) };
}
async function candidateTable(page) {
  const count = testId(page, "ligand-candidate-count");
  await count.waitFor({ timeout: 30000 });
  const counts = await count.evaluate(node => ({ total: node.getAttribute("data-total"), passing: node.getAttribute("data-passing"),
    failing: node.getAttribute("data-failing"), hidden: node.getAttribute("data-hidden"), matched: node.getAttribute("data-matched"),
    text: node.textContent.replace(/\s+/g, " ").trim() }));
  const rows = !await testId(page, "ligand-candidates").count() ? [] : await testId(page, "ligand-candidates")
    .locator("tr[data-candidate-id]").evaluateAll(items => items.map(item => ({
      id: item.getAttribute("data-candidate-id"), order: Number(item.getAttribute("data-generation-order")),
      passesAll: item.getAttribute("data-passes-all"), stereo: item.getAttribute("data-stereo-flag"),
      smiles: item.querySelector(".mw-ligand-smiles")?.textContent.trim() ?? null,
      properties: Object.fromEntries([...item.querySelectorAll("td[data-property]")].map(cell =>
        [cell.getAttribute("data-property"), cell.textContent.trim()])),
      filters: Object.fromEntries([...item.querySelectorAll("td[data-filter]")].map(cell =>
        [cell.getAttribute("data-filter"), cell.getAttribute("data-pass")])),
      pains: Number(item.querySelector("[data-pains-count]")?.getAttribute("data-pains-count") ?? NaN) })));
  const pageInfo = await testId(page, "ligand-page").count() ? { offset: Number(await testId(page, "ligand-page").getAttribute("data-offset")),
    text: clean(await testId(page, "ligand-page").textContent()),
    prev: await testId(page, "ligand-page-prev").isEnabled(), next: await testId(page, "ligand-page-next").isEnabled() } : null;
  return { counts, rows, page: pageInfo };
}
/** Perform an input that changes the candidate-row query; return the rows response the screen received and the table. */
async function rowsAfter(page, run, act) {
  const response = page.waitForResponse(item => item.request().method() === "GET" &&
    new URL(item.url()).pathname === `/api/runs/${run}/ligand/candidate_sets/rows`, { timeout: 30000 });
  await act();
  const received = await response;
  assert.equal(received.status(), 200, `rows read failed: ${await received.text()}`);
  const body = await received.json();
  const query = new URL(received.url()).search;
  await waitFor(page, async () => {
    const table = await candidateTable(page);
    return table.rows.length === body.rows.length && table.rows.every((row, i) => row.id === body.rows[i].candidate.id) ? true : null;
  }, "candidate table shows the received rows", 30000);
  return { query, body, table: await candidateTable(page) };
}
/** The table equals the server page row by row (order, id, smiles, passes_all, per-filter pass). */
function tableEqualsPage(table, body) {
  assert.equal(table.rows.length, body.rows.length);
  body.rows.forEach((row, i) => {
    const shown = table.rows[i];
    assert.equal(shown.id, row.candidate.id);
    assert.equal(shown.smiles, row.candidate.smiles);
    assert.equal(shown.order, row.generation_order);
    assert.equal(shown.passesAll, row.passes_all === null ? "null" : String(row.passes_all));
    for (const [key, value] of Object.entries(row.filters)) assert.equal(shown.filters[key], String(value), `${row.candidate.id} ${key}`);
  });
  assert.equal(Number(table.counts.total), body.total);
  assert.equal(table.counts.passing === null ? null : Number(table.counts.passing), body.passing);
  assert.equal(Number(table.counts.hidden), body.hidden_by_filter);
  assert.equal(Number(table.counts.matched), body.matched);
}
async function allRows(page, run, handle, query = "") {
  const body = await readApi(page, `/runs/${run}/ligand/candidate_sets/rows?handle=${enc(handle)}&offset=0&limit=100${query}`);
  assert.ok(body.total <= 100, "more rows than one read");
  return body;
}
async function fillFilter(page, name, side, value) {
  const field = testId(page, `ligand-filter-${name}-${side}`);
  await field.click();
  await field.fill(value);
}

// ------------------------------------------------------------------ mode main
async function modeMain(session, input, rec_, evidence, log) {
  const { page } = session;
  const o = oracle();
  evidence.inputs.push(...[STRUCTURE, PARENT_H, BLOCKS_SDF, BLOCKS_SMI].map(fileRecord), ...o.files);
  await waitForBoot(page);
  const runA = await rec_.step("R01-run", ["L-run-create"], "구조 분석: click 새 run, choose public_1mq4.cif, 구조 불러오기", async () => {
    const run = await newRun(page);
    const structure = await uploadLoad(page, STRUCTURE);
    return { run, structure, state: await structureState(page) };
  }, async value => {
    assert.match(value.run, /^run_/);
    assert.match(value.structure, /\/structure\//);
    assert.equal(value.state.dom.shown, "true");
    return value;
  });
  evidence.runs.A = runA.run;
  evidence.handles.structureA = runA.structure;
  const run = runA.run;
  const structureBefore = runA.state;

  await rec_.step("R02-ligand-tab", ["L-run-create", "L-structure-kept"], "Click 리간드 설계·탐색: the panel uses the global run; " +
    "the structure tab stays mounted (hidden)", async () => {
    await openLigandTab(page);
    return { state: await panelState(page), run: await globalRun(page), structure: await structureState(page),
      capability: clean(await testId(page, "ligand-capability").textContent()),
      budget: await testId(page, "ligand-budget").getAttribute("data-used").catch(() => null),
      inspections: clean(await panel(page).locator('[data-ligand-area="inspections"]').textContent()),
      siteDisabled: clean(await testId(page, "ligand-site-disabled").textContent()),
      inspectBlocked: await startState(page, "ligand-inspect-start") };
  }, async value => {
    assert.equal(value.state, "ready");
    assert.equal(value.run, run);
    assert.equal(value.structure.dom.present, true);
    assert.equal(value.structure.dom.shown, "false");
    assert.ok(value.structure.dom.canvases > 0, "Mol* canvas unmounted while the ligand tab is shown");
    assert.equal(value.structure.sessionId, structureBefore.sessionId);
    assert.ok(value.capability.includes("rdkit 2026.03.6"), value.capability);
    assert.ok(value.inspections.includes("이 run에 점검 결과가 없습니다"), value.inspections);
    assert.ok(value.siteDisabled.includes("점검 작업을 먼저"), value.siteDisabled);
    assert.equal(value.inspectBlocked.enabled, false);
    return value;
  });

  // ---- ① inputs
  const imports = await rec_.step("I01-files", ["L-inputs-import"], "Choose the explicit-H parent SDF, block SDF and block SMILES " +
    "files (file chooser), type six reaction rules, click 가져오기", async () => {
    await chooseLigandFile(page, "parent", PARENT_H);
    await chooseLigandFile(page, "blockSdf", BLOCKS_SDF);
    await chooseLigandFile(page, "blockSmiles", BLOCKS_SMI);
    const beforeImport = { blocked: clean(await testId(page, "ligand-inspect-blocked").textContent()) };
    await testId(page, "ligand-rules").click();
    await testId(page, "ligand-rules").fill(o.ruleTexts.join("\n"));
    await testId(page, "ligand-import").click();
    control(evidence, "ligand-import", { clicked: true });
    await waitArea(page, "inputs", "ready", 60000);
    const handles = await panel(page).locator("[data-ligand-import]").evaluateAll(items => Object.fromEntries(items.map(item =>
      [item.getAttribute("data-ligand-import"), item.getAttribute("data-import-handle")])));
    return { handles, beforeImport, inspect: await startState(page, "ligand-inspect-start"),
      rules: await testId(page, "ligand-rules").inputValue() };
  }, async value => {
    assert.ok(value.beforeImport.blocked.includes("가져오세요"), value.beforeImport.blocked);
    assert.deepEqual(Object.keys(value.handles).sort(), ["building_blocks_sdf", "building_blocks_smiles", "ligand_sdf"]);
    const prerequisites = await readApi(page, `/runs/${run}/ligand/prerequisites`);
    for (const [kind, handle] of Object.entries(value.handles)) {
      const listed = prerequisites.imports.find(item => item.handle === handle);
      assert.ok(listed, `import ${handle} not listed`);
      assert.equal(listed.input_kind, kind);
    }
    assert.equal(prerequisites.inspections, 0);
    assert.equal(value.rules, o.ruleTexts.join("\n"));
    assert.equal(value.inspect.enabled, true, JSON.stringify(value.inspect));
    return value;
  });
  evidence.handles.imports = imports.handles;
  for (const slot of ["parent", "blockSdf", "blockSmiles"]) control(evidence, `ligand-file-${slot}`, { chosen: true });
  control(evidence, "ligand-rules", { lines: o.ruleTexts.length });

  // ---- ② inspection job (approval UI)
  const inspection = await rec_.step("J01-inspect", ["L-inspect-job"], "Click 점검 시작; 비싼 계산 승인 when asked; 작업 시작; " +
    "the real RDKit inspection finishes", () => runLigandJob(page, run, "ligand-inspect-start", "rdkit_inspect_v1", evidence),
  async value => {
    assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
    assert.equal(value.job.protocol_id, "rdkit_inspect_v1");
    assert.match(value.handle ?? "", /ligand_inspection/);
    assert.ok(value.approved, "the first expensive inspection did not ask for approval");
    assert.equal(value.budgetAfter.used, value.budgetBefore.used + 1, "inspection did not use exactly one expensive unit");
    assert.ok(value.resultNotice.includes(shortHandle(value.handle)));
    return value;
  });
  evidence.handles.inspection = inspection.handle;

  // ---- ③ inspection result: numbered figure, atom table, block and rule summaries
  const detail = await readApi(page, `/runs/${run}/ligand/inspections/detail?handle=${enc(inspection.handle)}`);
  await rec_.step("K01-figure", ["L-inspection-figure"], "Click the new inspection's radio: numbered RDKit 2D figure loads as an " +
    "<img> data URI equal to the stored SVG", async () => {
    const listed = await panel(page).locator("label[data-ligand-inspection]").evaluateAll(items => items.map(item => ({
      handle: item.getAttribute("data-ligand-inspection"), checked: item.querySelector("input").checked })));
    await selectInspection(page, inspection.handle);
    control(evidence, "ligand-inspection-radio", { handle: inspection.handle });
    const img = testId(page, "ligand-parent-svg");
    await waitFor(page, () => img.evaluate(node => node.complete && node.naturalWidth > 0), "parent figure loaded", 30000);
    const image = await img.evaluate(node => ({ src: node.getAttribute("src"), complete: node.complete,
      width: node.naturalWidth, height: node.naturalHeight, inlineSvg: !!document.querySelector('[data-testid="ligand-panel"] svg') }));
    return { listed, image, smiles: clean(await testId(page, "ligand-parent-smiles").textContent()) };
  }, async value => {
    assert.deepEqual(value.listed, [{ handle: inspection.handle, checked: false }], "an inspection was chosen automatically");
    const prefix = "data:image/svg+xml;charset=utf-8,";
    assert.ok(value.image.src.startsWith(prefix), value.image.src.slice(0, 60));
    assert.equal(decodeURIComponent(value.image.src.slice(prefix.length)), detail.inspection.parent.svg);
    assert.ok(value.image.width > 0 && value.image.height > 0);
    assert.equal(value.image.inlineSvg, false, "SVG markup inserted into the DOM");
    assert.equal(value.smiles, o.parentSmiles);
    // the stored figure carries atom-number notes of the SDF serials (heavy atoms only)
    const svg = detail.inspection.parent.svg;
    return { width: value.image.width, height: value.image.height, svgBytes: Buffer.byteLength(svg),
      svgSha256: sha(Buffer.from(svg)), atomNoteClasses: (svg.match(/class=['"]note['"]/g) ?? []).length };
  });
  await rec_.step("K02-atoms", ["L-atom-numbering"], "Atom table: heavy atoms only, numbers are SDF serials with the hydrogen " +
    "serials skipped (explicit-H parent), elements and heavy neighbours equal the hand oracle", async () =>
    testId(page, "ligand-atoms").locator("tr[data-atom-serial]").evaluateAll(items => items.map(item => {
      const cells = [...item.querySelectorAll("td")].map(cell => cell.textContent.trim());
      return { serial: Number(item.getAttribute("data-atom-serial")), shown: cells[1], element: cells[2], charge: cells[3],
        neighbors: cells[4] ? cells[4].split(",").map(text => Number(text.trim())) : [],
        checkbox: item.querySelector("input")?.getAttribute("data-serial") };
    })), async rows => {
    const heavy = o.explicit.heavy_atoms;
    assert.deepEqual(rows.map(row => row.serial), heavy.map(atom => atom.serial));
    assert.deepEqual(rows.map(row => row.shown), heavy.map(atom => String(atom.serial)));
    assert.deepEqual(rows.map(row => row.element), heavy.map(atom => atom.element));
    assert.deepEqual(rows.map(row => row.checkbox), heavy.map(atom => String(atom.serial)));
    const heavySet = new Set(heavy.map(atom => atom.serial));
    for (const row of rows)
      assert.deepEqual(row.neighbors.filter(serial => heavySet.has(serial)).sort((a, b) => a - b), o.adjacency.get(row.serial),
        `neighbours of ${row.serial}`);
    const skipped = [];
    for (let serial = 1; serial <= o.explicit.atoms_in_sdf; serial++) if (!heavySet.has(serial)) skipped.push(serial);
    assert.deepEqual(skipped, o.explicit.hydrogen_serials);
    assert.equal(detail.inspection.parent.atoms_in_sdf, o.explicit.atoms_in_sdf);
    return { serials: rows.map(row => row.serial), skippedHydrogenSerials: skipped };
  });
  await rec_.part("blocks-rules", ["L-rules-status", "L-invalid-rule"], () => rec_.step("K03-blocks-rules", ["L-rules-status", "L-invalid-rule"], "Block and rule validation summaries: accepted/rejected " +
    "counts per library equal the hand oracle; rules user_1–3 valid, user_4 reactant_count, user_5 reaction_parse_failed, " +
    "user_6 duplicate_rule; invalid rules cannot be chosen for generation", async () => {
    const libraries = await testId(page, "ligand-blocks").locator("[data-block-kind]").evaluateAll(items => items.map(item => ({
      kind: item.getAttribute("data-block-kind"), text: item.textContent.replace(/\s+/g, " ").trim(),
      rejected: Object.fromEntries([...item.querySelectorAll("[data-rejected-reason]")].map(node =>
        [node.getAttribute("data-rejected-reason"), Number(node.getAttribute("data-count"))])) })));
    const rules = await testId(page, "ligand-rules-status").locator("li[data-rule-id]").evaluateAll(items => items.map(item => ({
      id: item.getAttribute("data-rule-id"), status: item.getAttribute("data-rule-status"), text: item.textContent.replace(/\s+/g, " ").trim() })));
    const boxes = [];
    for (const rule of rules) {
      const box = testId(page, `ligand-rule-${rule.id}`);
      boxes.push({ id: rule.id, enabled: await box.isEnabled(),
        note: clean(await panel(page).locator(`[data-testid="ligand-methods"] label[data-rule-id="${rule.id}"]`).textContent()) });
    }
    return { libraries, rules, boxes };
  }, async value => {
    for (const library of value.libraries) {
      const want = o.blocks[library.kind];
      for (const [label, count] of [["수락", want.accepted], ["고정 교체 대상", want.fixed_targets], ["규칙 대상", want.rule_targets]])
        assert.ok(new RegExp(`${label} ${count}(?!\\d)`).test(library.text), `${library.kind} ${label} ${count}: ${library.text}`);
      assert.deepEqual(nonZero(library.rejected), nonZero(want.rejected_counts), library.kind);
    }
    assert.deepEqual(value.libraries.map(item => item.kind).sort(), ["building_blocks_sdf", "building_blocks_smiles"]);
    assert.deepEqual(value.rules.map(rule => rule.id), RULE_EXPECTED.map((_, i) => `user_${i + 1}`));
    assert.deepEqual(value.rules.map(rule => rule.status), RULE_EXPECTED);
    assert.deepEqual(detail.inspection.rules.map(rule => rule.status), RULE_EXPECTED);
    value.rules.forEach((rule, i) => { if (RULE_EXPECTED[i] !== "valid") assert.ok(rule.text.includes(`(${RULE_EXPECTED[i]})`), rule.text); });
    value.boxes.forEach((box, i) => {
      assert.equal(box.enabled, RULE_EXPECTED[i] === "valid", `${box.id} checkbox`);
      if (RULE_EXPECTED[i] !== "valid") assert.ok(box.note.includes("생성에 쓸 수 없음"), box.note);
    });
    return value;
  }));

  // ---- site check: reject (crossing bonds 2) then pass
  await rec_.step("S01-site-reject", ["L-site-check"], "Tick atom 19 only (methoxy O): the site check rejects with " +
    "crossing_bond_count and 후보 생성 시작 stays disabled", async () => {
    await atomBox(page, 19).check();
    control(evidence, "ligand-atom-checkbox", { serial: 19 });
    const preview = await waitPreview(page, { "data-site-reason": "crossing_bond_count" }, "reject");
    return { preview, atoms: await testId(page, "ligand-site-atoms").getAttribute("data-site-atoms"),
      start: await startState(page, "ligand-enumerate-start"),
      blocking: await testId(page, "ligand-preview-blocking").locator("[data-blocking-reason]").evaluateAll(items =>
        items.map(item => item.getAttribute("data-blocking-reason"))) };
  }, async value => {
    assert.equal(value.atoms, "19");
    assert.equal(value.preview.valid, "false");
    assert.equal(value.preview.ready, "false");
    assert.ok(value.preview.text.includes("(crossing_bond_count)"), value.preview.text);
    assert.equal(value.start.enabled, false);
    assert.ok(value.blocking.includes("crossing_bond_count"), JSON.stringify(value.blocking));
    return value;
  });
  await rec_.step("S02-site-pass", ["L-site-check"], "Tick atom 20 too (methoxy O+CH3): one single crossing bond 14–19, " +
    "site hydrogens 21–23; 후보 생성 시작 enabled", async () => {
    await atomBox(page, 20).check();
    const preview = await waitPreview(page, { "data-site-valid": "true", "data-ligand-preview-ready": "true" }, "pass");
    return { preview, atoms: await testId(page, "ligand-site-atoms").getAttribute("data-site-atoms"),
      start: await startState(page, "ligand-enumerate-start") };
  }, async value => {
    assert.equal(value.atoms, "19,20");
    const [core, site] = o.explicit.crossing_bond;
    assert.ok(value.preview.text.includes(`코어 ${core} – 부위 ${site}, single`), value.preview.text);
    assert.ok(value.preview.text.includes(o.explicit.site_hydrogens_removed_with_site.join(", ")), value.preview.text);
    assert.equal(value.start.enabled, true, JSON.stringify(value.start));
    return value;
  });

  // ---- ④ enumeration (fixed + user_1..user_3)
  const enumerated = await rec_.step("E01-enumerate", ["L-enumerate-job"], "Tick user_1, user_2, user_3 (fixed replacement " +
    "stays on); click 후보 생성 시작; the real RDKit enumeration finishes", async () => {
    for (const id of ["user_1", "user_2", "user_3"]) {
      await testId(page, `ligand-rule-${id}`).check();
      control(evidence, `ligand-rule-${id}`, { checked: true });
    }
    await waitPreview(page, { "data-site-valid": "true", "data-ligand-preview-ready": "true" }, "with rules");
    await waitFor(page, async () => (await startState(page, "ligand-enumerate-start")).enabled ? true : null, "enumerate enabled", 30000);
    control(evidence, "ligand-use-fixed", { checked: await testId(page, "ligand-use-fixed").isChecked() });
    return runLigandJob(page, run, "ligand-enumerate-start", "rdkit_enumerate_v1", evidence);
  }, async value => {
    assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
    assert.match(value.handle ?? "", /ligand_candidate_set/);
    assert.equal(value.budgetAfter.used, value.budgetBefore.used + 1);
    return value;
  });
  evidence.handles.candidateSet = enumerated.handle;
  const setHandle = enumerated.handle;

  // ---- ⑤ candidate table vs the oracle
  const table = await rec_.step("C01-candidates", ["L-candidates-oracle"], "Click the new candidate set's radio: the table rows " +
    "equal the server rows; ids, SMILES and counts equal the hand oracle", async () => {
    const result = await rowsAfter(page, run, () => selectSet(page, setHandle));
    control(evidence, "ligand-candidate-set-radio", { handle: setHandle });
    const counts = await testId(page, "ligand-counts").evaluate(node => ({ candidates: node.getAttribute("data-candidates"),
      duplicates: node.getAttribute("data-duplicate-products"), rawProducts: node.getAttribute("data-raw-products"),
      rejected: Object.fromEntries([...node.querySelectorAll("[data-rejected-reason]")].map(item =>
        [item.getAttribute("data-rejected-reason"), Number(item.getAttribute("data-count"))])) }));
    return { ...result, counts, state: await panelState(page),
      limitations: await testId(page, "ligand-limitations").locator("p").allTextContents() };
  }, async value => {
    tableEqualsPage(value.table, value.body);
    const set = await readApi(page, `/runs/${run}/ligand/candidate_sets/detail?handle=${enc(setHandle)}`);
    const rows = value.table.rows;
    assert.equal(rows.length, set.candidate_count);
    assert.equal(rows.length, o.candidates.length);
    assert.ok(sameSet(rows.map(row => row.smiles), o.candidates.map(item => item.smiles)), JSON.stringify(rows.map(row => row.smiles)));
    for (const row of rows) assert.equal(row.id, candidateId(row.smiles), `id of ${row.smiles}`);
    for (const row of rows) assert.equal(row.stereo, "none");
    assert.equal(value.state, "ready");
    assert.equal(Number(value.counts.candidates), o.candidates.length);
    assert.deepEqual(nonZero(value.counts.rejected), o.rejected);
    const bySmiles = Object.fromEntries(value.body.rows.map(row => [row.candidate.smiles, row.candidate]));
    for (const [name, paths] of Object.entries(o.duplicates)) {
      const smiles = o.candidates.find(item => item.name === name).smiles;
      assert.equal(bySmiles[smiles].origins.length, paths, `${name} origins`);
    }
    assert.equal(Number(value.counts.duplicates), Object.values(o.duplicates).reduce((sum, n) => sum + n - 1, 0));
    for (const row of value.body.rows) {
      const hand = o.candidates.find(item => item.smiles === row.candidate.smiles);
      assert.equal(row.candidate.properties.heavy_atoms, hand.heavy, `${hand.name} heavy atoms`);
      assert.ok(Math.abs(row.candidate.properties.mol_weight - hand.mw) < 0.01, `${hand.name} mol_weight ${row.candidate.properties.mol_weight}`);
    }
    assert.deepEqual(value.limitations, set.candidate_set.limitations);
    assert.equal(value.limitations.length, 5);
    return { ids: rows.map(row => row.id), counts: value.counts, setCounts: set.candidate_set.counts };
  });

  // ---- filters: integer boundary, exact stored-value boundary, invalid input, PAINS exclusion
  const phenacetin = o.candidates.find(item => item.name === "phenacetin");
  const stored = Object.fromEntries((await allRows(page, run, setHandle)).rows.map(row => [row.candidate.smiles, row.candidate]));
  const boundary = String(stored[phenacetin.smiles].properties.mol_weight);
  await rec_.step("F01-heavy-range", ["L-filters"], "Type 중원자 수 12–14 and click 필터 적용: inclusive integer bounds, passing rows " +
    "equal the hand oracle (heavy atoms 12, 13, 14)", async () => {
    await fillFilter(page, "heavy_atoms", "min", "12");
    await fillFilter(page, "heavy_atoms", "max", "14");
    const result = await rowsAfter(page, run, () => testId(page, "ligand-filter-apply").click());
    control(evidence, "ligand-filter-apply", { query: result.query });
    return result;
  }, async value => {
    tableEqualsPage(value.table, value.body);
    const want = o.candidates.filter(item => item.heavy >= 12 && item.heavy <= 14).map(item => candidateId(item.smiles));
    const passing = value.table.rows.filter(row => row.passesAll === "true").map(row => row.id);
    assert.ok(sameSet(passing, want), JSON.stringify({ passing, want }));
    assert.equal(Number(value.table.counts.passing), want.length);
    assert.equal(Number(value.table.counts.total), o.candidates.length);
    for (const row of value.table.rows) assert.equal(row.filters.heavy_atoms, row.passesAll);
    return { query: value.query, passing: want.length };
  });
  await rec_.step("F02-weight-boundary", ["L-filters"], "Type 분자량 최댓값 = the stored phenacetin value exactly; click 필터 적용: " +
    "the boundary row passes (inclusive), heavier rows fail", async () => {
    await fillFilter(page, "mol_weight", "max", boundary);
    return rowsAfter(page, run, () => testId(page, "ligand-filter-apply").click());
  }, async value => {
    tableEqualsPage(value.table, value.body);
    const want = o.candidates.filter(item => item.heavy >= 12 && item.heavy <= 14 && item.mw <= phenacetin.mw)
      .map(item => candidateId(item.smiles));
    const passing = value.table.rows.filter(row => row.passesAll === "true").map(row => row.id);
    assert.ok(sameSet(passing, want), JSON.stringify({ passing, want }));
    const boundaryRow = value.table.rows.find(row => row.id === candidateId(phenacetin.smiles));
    assert.equal(boundaryRow.filters.mol_weight, "true", "the exact boundary value did not pass");
    assert.equal(new URL(`http://x/${value.query}`).searchParams.get("mol_weight_max"), boundary);
    assert.equal(await testId(page, "ligand-filter-applied").getAttribute("data-applied-count"), "2");
    return { boundary, passing: want.length };
  });
  await rec_.step("F03-invalid-input", ["L-filters"], "Type 'abc' as TPSA 최솟값 and click 필터 적용: an input error, the applied " +
    "filters stay unchanged; clear the field", async () => {
    const before = log.length;
    await fillFilter(page, "tpsa", "min", "abc");
    await testId(page, "ligand-filter-apply").click();
    await testId(page, "ligand-filter-errors").waitFor({ timeout: 10000 });
    const errors = clean(await testId(page, "ligand-filter-errors").textContent());
    const applied = await testId(page, "ligand-filter-applied").getAttribute("data-applied-count");
    await page.waitForTimeout(800);
    const rowsReads = log.slice(before).filter(row => row.path.endsWith("/ligand/candidate_sets/rows")).length;
    await fillFilter(page, "tpsa", "min", "");
    return { errors, applied, rowsReads };
  }, async value => {
    assert.ok(value.errors.includes("숫자만 입력하세요"), value.errors);
    assert.equal(value.applied, "2");
    assert.equal(value.rowsReads, 0, "an invalid filter input sent a rows read");
    return value;
  });
  await rec_.step("F04-pains", ["L-filters"], "Tick PAINS 구조 경고 일치 후보 제외 and click 필터 적용: per-row PAINS pass equals the " +
    "stored matches (morpholino has a match)", async () => {
    await testId(page, "ligand-filter-pains").check();
    control(evidence, "ligand-filter-pains", { checked: true });
    return rowsAfter(page, run, () => testId(page, "ligand-filter-apply").click());
  }, async value => {
    tableEqualsPage(value.table, value.body);
    for (const row of value.table.rows) assert.equal(row.filters.pains_exclude, String(row.pains === 0), row.smiles);
    const morpholino = value.table.rows.find(row => row.smiles === o.candidates.find(item => item.name === "fixed_morpholino").smiles);
    assert.equal(morpholino.filters.pains_exclude, "false");
    assert.ok(value.table.counts.text.includes(`전체 후보 ${o.candidates.length}개`), value.table.counts.text);
    return { passing: value.body.passing, failing: value.body.failing };
  });
  await rec_.step("F05-passes-only", ["L-passes-only"], "Tick 필터 통과만 보기: only passing rows shown; the count line shows the " +
    "total and the rows hidden by the filter", async () => {
    const result = await rowsAfter(page, run, () => testId(page, "ligand-passes-only").check());
    control(evidence, "ligand-passes-only", { checked: true });
    return result;
  }, async value => {
    tableEqualsPage(value.table, value.body);
    assert.ok(value.table.rows.every(row => row.passesAll === "true"));
    assert.equal(value.table.rows.length, value.body.passing);
    assert.equal(Number(value.table.counts.hidden), o.candidates.length - value.body.passing);
    assert.ok(value.table.counts.text.includes(`필터 때문에 보이지 않는 후보 ${o.candidates.length - value.body.passing}개`),
      value.table.counts.text);
    return { shown: value.table.rows.length, hidden: value.table.counts.hidden, text: value.table.counts.text };
  });
  await rec_.step("F06-sort", ["L-sort"], "Untick 필터 통과만 보기, choose 정렬 분자량 and 방향 내림차순: rows ordered by the stored " +
    "mol_weight, descending", async () => {
    await rowsAfter(page, run, () => testId(page, "ligand-passes-only").uncheck());
    await rowsAfter(page, run, () => testId(page, "ligand-sort").selectOption("mol_weight"));
    control(evidence, "ligand-sort", { value: "mol_weight" });
    const result = await rowsAfter(page, run, () => testId(page, "ligand-direction").selectOption("desc"));
    control(evidence, "ligand-direction", { value: "desc" });
    return result;
  }, async value => {
    tableEqualsPage(value.table, value.body);
    const weights = value.table.rows.map(row => stored[row.smiles].properties.mol_weight);
    for (let i = 1; i < weights.length; i++) assert.ok(weights[i - 1] >= weights[i], `not descending at ${i}: ${weights}`);
    assert.equal(value.table.rows.length, o.candidates.length);
    assert.equal(value.table.page.next, false);
    assert.equal(value.table.page.prev, false);
    return { order: value.table.rows.map(row => row.smiles), page: value.table.page };
  });

  // ---- ⑥ report → 지식·보고서 list → downloads
  await rec_.part("report", ["L-report"], async () => {
    const cases = ["L-report"];
    const created = await rec_.step("P01-report", cases, "Click ⑥ 보고서 만들기 (three applied filters)", async () => {
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
      await testId(page, "ligand-report").click();
      control(evidence, "ligand-report", { clicked: true });
      const response = await posted;
      const body = await response.json();
      await testId(page, "ligand-report-done").waitFor({ timeout: 30000 });
      return { status: response.status(), handle: body.handle, request: response.request().postDataJSON(),
        manifest: body.manifest, done: await testId(page, "ligand-report-done").getAttribute("data-report-handle") };
    }, async value => {
      assert.equal(value.done, value.handle);
      assert.equal(value.manifest.analysis_type, "ligand_candidates");
      assert.equal(value.manifest.result_handle, setHandle);
      assert.equal(value.request.result_handle, setHandle);
      assert.equal(Object.keys(value.request.filters.ranges).sort().join(","), "heavy_atoms,mol_weight");
      assert.equal(value.request.filters.pains_exclude, true);
      const listed = (await readApi(page, `/runs/${run}/reports`)).find(item => item.handle === value.handle);
      assert.ok(listed, "created report not in the backend report list");
      assert.equal(listed.analysis_type, "ligand_candidates");
      return { handle: value.handle, filters: value.request.filters };
    });
    evidence.handles.report = created.handle;
    const library = page.getByRole("region", { name: "보고서 보관함", exact: true });
    const reports = library.getByRole("region", { name: "저장된 보고서", exact: true });
    const content = library.getByRole("region", { name: "선택한 항목 내용", exact: true });
    await rec_.step("P02-listed", cases, "Click 지식·보고서: the report list shows 리간드 후보 보고서; click it", async () => {
      await selectTab(page, "지식·보고서");
      const row = reports.locator("li button").filter({ hasText: created.handle });
      await row.waitFor({ timeout: 30000 });
      const kind = clean(await row.locator(".mw-library-kind").textContent());
      await row.click();
      const pre = content.getByLabel(`저장된 보고서 ${created.handle}`, { exact: true });
      await pre.waitFor({ timeout: 30000 });
      return { kind, text: await pre.textContent() };
    }, async value => {
      assert.equal(value.kind, "리간드 후보 보고서");
      const saved = await readApi(page, `/runs/${run}/reports/selected?handle=${enc(created.handle)}`);
      assert.equal(value.text, saved.markdown);
      return { kind: value.kind, markdownSha256: sha(Buffer.from(value.text)) };
    });
    for (const [label, format] of [["Markdown 다운로드", "markdown"], ["JSON 다운로드", "json"]]) {
      const route = `/runs/${run}/reports/download?handle=${enc(created.handle)}&format=${format}`;
      await rec_.step(`P03-download-${format}`, cases, `Click ${label}; bytes equal the backend bytes`, () =>
        downloadByClick(rec_.app, content.getByRole("link", { name: label, exact: true })), async downloaded => {
        const bytes = fs.readFileSync(downloaded.downloaded);
        const saved = await readBytes(page, route);
        assert.equal(sha(bytes), sha(saved), "downloaded bytes differ from the backend bytes");
        const url = new URL(downloaded.url);
        assert.equal(`${url.pathname}${url.search}`, `/api${route}`);
        return { route, sha256: sha(bytes), backendSha256: sha(saved), bytes: bytes.length };
      });
    }
  });

  // ---- zero candidates (fixed off, user_3 only: every match lies outside the site) — empty scientific result
  await rec_.part("zero", ["L-zero-candidates"], async () => {
    const cases = ["L-zero-candidates"];
    const zero = await rec_.step("Z01-enumerate", cases, "Back to 리간드 설계·탐색 (panel remounts): choose the inspection, tick " +
      "19 and 20, untick 고정 교체, tick user_3 only; click 후보 생성 시작", async () => {
      await openLigandTab(page);
      await selectInspection(page, inspection.handle);
      await atomBox(page, 19).check();
      await atomBox(page, 20).check();
      await testId(page, "ligand-use-fixed").uncheck();
      control(evidence, "ligand-use-fixed", { checked: false });
      await testId(page, "ligand-rule-user_3").check();
      await waitPreview(page, { "data-site-valid": "true", "data-ligand-preview-ready": "true" }, "zero");
      await waitFor(page, async () => (await startState(page, "ligand-enumerate-start")).enabled ? true : null, "enumerate enabled", 30000);
      return runLigandJob(page, run, "ligand-enumerate-start", "rdkit_enumerate_v1", evidence);
    }, async value => {
      assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
      assert.equal(value.approved, false, "a second enumeration asked for approval again");
      return value;
    });
    evidence.handles.zeroSet = zero.handle;
    await rec_.step("Z02-null", cases, "Click the zero-candidate set: 빈 과학 결과 (not 실패), outside_site counts shown, no rows",
      async () => {
        const result = await rowsAfter(page, run, () => selectSet(page, zero.handle));
        return { ...result, state: await panelState(page), stateText: clean(await testId(page, "ligand-state").textContent()),
          nullText: clean(await testId(page, "ligand-set-null").textContent()),
          failure: await testId(page, "ligand-failure").count(),
          rejected: await testId(page, "ligand-counts").locator("[data-rejected-reason]").evaluateAll(items => Object.fromEntries(
            items.map(item => [item.getAttribute("data-rejected-reason"), Number(item.getAttribute("data-count"))]))),
          listRow: await panel(page).locator(`label[data-ligand-candidate-set="${zero.handle}"]`).getAttribute("data-null-result") };
      }, async value => {
        assert.equal(value.state, "scientific_null");
        assert.equal(value.failure, 0);
        assert.equal(value.listRow, "true");
        assert.equal(value.body.total, 0);
        assert.equal(value.table.rows.length, 0);
        assert.ok(value.nullText.includes("실패가 아님"), value.nullText);
        assert.equal(value.rejected.outside_site, o.rejected.outside_site);
        const set = await readApi(page, `/runs/${run}/ligand/candidate_sets/detail?handle=${enc(zero.handle)}`);
        assert.equal(set.candidate_count, 0);
        assert.deepEqual(nonZero(set.candidate_set.counts.rejected), { outside_site: o.rejected.outside_site });
        return { state: value.state, stateText: value.stateText, rejected: value.rejected };
      });
  });

  // ---- paging: a labeled generated chain library (60 *C…C blocks) → more candidates than one page
  await rec_.part("paging", ["L-paging"], async () => {
    const cases = ["L-paging"];
    const chains = chainLibrary(rec_.artifacts);
    evidence.inputs.push({ ...fileRecord(chains), label: CHAIN_LABEL });
    evidence.fixtureLabels.push(CHAIN_LABEL);
    const inspected = await rec_.step("G01-inspect", cases, "Choose the parent SDF, block SDF and the generated chain list, clear " +
      "the rules, 가져오기, 점검 시작", async () => {
      await chooseLigandFile(page, "parent", PARENT_H);
      await chooseLigandFile(page, "blockSdf", BLOCKS_SDF);
      await chooseLigandFile(page, "blockSmiles", chains);
      await testId(page, "ligand-rules").fill("");
      await testId(page, "ligand-import").click();
      await waitArea(page, "inputs", "ready", 60000);
      return runLigandJob(page, run, "ligand-inspect-start", "rdkit_inspect_v1", evidence);
    }, async value => {
      assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
      assert.notEqual(value.handle, inspection.handle);
      return value;
    });
    const made = await rec_.step("G02-enumerate", cases, "Choose that inspection, tick 19 and 20, tick 고정 교체 (fixed only); " +
      "후보 생성 시작", async () => {
      await selectInspection(page, inspected.handle);
      await atomBox(page, 19).check();
      await atomBox(page, 20).check();
      await testId(page, "ligand-use-fixed").check(); // unticked by the zero-candidate case (the choice outlives the inspection)
      await waitPreview(page, { "data-site-valid": "true", "data-ligand-preview-ready": "true" }, "paging");
      await waitFor(page, async () => (await startState(page, "ligand-enumerate-start")).enabled ? true : null, "enumerate enabled", 30000);
      return runLigandJob(page, run, "ligand-enumerate-start", "rdkit_enumerate_v1", evidence);
    }, async value => { assert.equal(value.job.status, "done", JSON.stringify(value.job.failure)); return value; });
    evidence.handles.pagingSet = made.handle;
    const first = await rec_.step("G03-page-1", cases, "Click that set: the first page holds 50 rows of more than 50", () =>
      rowsAfter(page, run, () => selectSet(page, made.handle)), async value => {
      tableEqualsPage(value.table, value.body);
      // 60 chains (1–60 C) + ethoxy (phenacetin) and nitrile from the block SDF; its ethyl/methyl repeat chains 2 and 1
      assert.equal(value.body.total, CHAIN_COUNT + 2, `paging candidates: ${value.body.total}`);
      assert.equal(value.table.rows.length, 50);
      assert.equal(value.table.page.offset, 0);
      assert.equal(value.table.page.next, true);
      assert.equal(value.table.page.prev, false);
      return { total: value.body.total, page: value.table.page };
    });
    const second = await rec_.step("G04-page-2", cases, "Click 다음: the remaining rows; no id repeats", async () => {
      const result = await rowsAfter(page, run, () => testId(page, "ligand-page-next").click());
      control(evidence, "ligand-page-next", { offset: result.table.page?.offset });
      return result;
    }, async value => {
      tableEqualsPage(value.table, value.body);
      assert.equal(value.table.page.offset, 50);
      assert.equal(value.table.rows.length, first.body.total - 50);
      const ids = [...first.table.rows, ...value.table.rows].map(row => row.id);
      assert.equal(new Set(ids).size, first.body.total);
      const all = await allRows(page, run, made.handle);
      assert.ok(sameSet(ids, all.rows.map(row => row.candidate.id)));
      return { page: value.table.page, rows: value.table.rows.length };
    });
    await rec_.step("G05-page-prev", cases, "Click 이전: back to the first page", async () => {
      const result = await rowsAfter(page, run, () => testId(page, "ligand-page-prev").click());
      control(evidence, "ligand-page-prev", { offset: result.table.page?.offset });
      return result;
    }, async value => {
      assert.equal(value.table.page.offset, 0);
      assert.deepEqual(value.table.rows.map(row => row.id), first.table.rows.map(row => row.id));
      return { page: value.table.page, secondRows: second.rows };
    });
  });

  // ---- structure tab kept mounted (hidden) through every ligand step
  await rec_.part("structure-kept", ["L-structure-kept"], () => rec_.step("T01-structure", ["L-structure-kept"],
    "Click 구조 분석: the same Mol* session, source and generation as before the ligand tab was opened", async () => {
      const hidden = await structureState(page);
      await selectTab(page, "구조 분석");
      await page.locator("canvas.mw-molstar-canvas:visible").first().waitFor({ timeout: 15000 });
      // the global budget line (refreshed at a tab switch, M14) equals the backend after the ligand jobs
      const budget = await waitFor(page, async () => {
        const backend = await budgetUsed(page, run);
        const shown = clean(await page.locator(".mw-app-budget").textContent());
        return shown === `expensive ${backend.used}/${backend.limit}` ? { shown, backend } : null;
      }, "global budget equals backend /budget", 15000);
      return { hidden, shown: await structureState(page), budget };
    }, async value => {
      assert.equal(value.hidden.dom.shown, "false");
      assert.ok(value.hidden.dom.canvases > 0);
      for (const key of ["sourceHandle", "sessionId", "generation", "representation"])
        assert.deepEqual(value.shown[key], structureBefore[key], `${key} changed across the ligand tab`);
      assert.equal(value.shown.dom.shown, "true");
      return value;
    }));

  // ---- run switch: a held run A response released after the switch is not applied
  const runB = await rec_.part("run-switch", ["L-run-switch-late"], async () => {
    const cases = ["L-run-switch-late"];
    const made = await rec_.step("W01-new-run-b", cases, "구조 분석: click 새 run (run B); 리간드 설계·탐색 shows run B only", async () => {
      const id = await newRun(page);
      await openLigandTab(page);
      return { run: id, global: await globalRun(page),
        inspections: await panel(page).locator("label[data-ligand-inspection]").count(),
        sets: await panel(page).locator("label[data-ligand-candidate-set]").count() };
    }, async value => {
      assert.equal(value.global, value.run);
      assert.equal(value.inspections, 0);
      assert.equal(value.sets, 0);
      return value;
    });
    evidence.runs.B = made.run;
    const held = [];
    let holding = true;
    const matcher = url => new URL(url).pathname === `/api/runs/${run}/ligand/inspections`;
    const handler = async route => {
      if (!holding || route.request().method() !== "GET") return route.continue();
      held.push({ route, response: await route.fetch(), at: Date.now() });
    };
    await page.route(matcher, handler);
    evidence.fixtureLabels.push(HOLD_LABEL);
    try {
      await rec_.step("W02-held", cases, "Choose run A in 저장된 run, click 리간드 설계·탐색: run A's inspection-list response is held " +
        "(panel loading)", async () => {
        await chooseRun(page, run);
        await selectTab(page, TAB);
        await panel(page).waitFor({ timeout: 15000 });
        await waitFor(page, async () => held.length >= 1 ? true : null, "held run A inspection list", 30000);
        return { held: held.length, area: await areaState(page, "inspections"), run: await globalRun(page) };
      }, async value => { assert.equal(value.area, "loading"); assert.equal(value.run, run); return value; });
      await rec_.step("W03-switch-b", cases, "Click 구조 분석, choose run B, click 리간드 설계·탐색: run B's empty lists", async () => {
        await chooseRun(page, made.run, false);
        await openLigandTab(page);
        return { run: await globalRun(page), inspections: await panel(page).locator("label[data-ligand-inspection]").count() };
      }, async value => { assert.equal(value.run, made.run); assert.equal(value.inspections, 0); return value; });
      await rec_.step("W04-release", cases, "Release run A's held response: run B's panel stays, no run A inspection appears", async () => {
        holding = false;
        const released = [];
        for (const item of held) {
          try { await item.route.fulfill({ response: item.response }); released.push({ delivered: true }); }
          catch (error) { released.push({ delivered: false, reason: String(error).slice(0, 160) }); }
        }
        await page.waitForTimeout(2500);
        return { released, run: await globalRun(page), text: clean(await panel(page).textContent()),
          inspections: await panel(page).locator("label[data-ligand-inspection]").count(),
          area: await areaState(page, "inspections") };
      }, async value => {
        assert.equal(value.run, made.run);
        assert.equal(value.inspections, 0);
        assert.equal(value.area, "ready");
        for (const handle of [inspection.handle, evidence.handles.candidateSet].filter(Boolean))
          assert.ok(!value.text.includes(shortHandle(handle)), `late run A result shown: ${handle}`);
        return { released: value.released };
      });
    } finally {
      holding = false;
      for (const item of held) await item.route.fulfill({ response: item.response }).catch(() => undefined);
      await page.unroute(matcher, handler);
    }
    return made.run;
  });

  for (const id of [run, runB].filter(Boolean)) evidence.providerCalls.push(await providerCalls(page, id));
}

// ------------------------------------------------------------------ mode unavailable (backend without the environment)
async function modeUnavailable(session, input, rec_, evidence, log) {
  const { page } = session;
  if (input["fixture-label"]) evidence.fixtureLabels.push(input["fixture-label"]);
  else evidence.fixtureLabels.push(UNAVAILABLE_LABEL);
  const capabilities = await readApi(page, "/capabilities");
  const capability = capabilities.methods?.ligand_candidates ?? null;
  evidence.capability = capability && { available: capability.available, reason_code: capability.reason_code };
  assert.ok(capability && capability.available === false, `backend reports the ligand method available: ${JSON.stringify(capability)}`);
  assert.equal((await readApi(page, "/runs")).length, 0, "mode unavailable needs a fresh runs root");
  const noControls = async () => ({ state: await panelState(page), text: clean(await panel(page).textContent()),
    controls: await panel(page).locator("button, input, select, textarea, a, img, table").count() });
  await waitForBoot(page);
  await rec_.step("U01-no-run", ["L-no-run"], "No run yet: click 리간드 설계·탐색 → reason only (no numbers, no controls)", async () => {
    await selectTab(page, TAB);
    await testId(page, "ligand-no-run").waitFor({ timeout: 15000 });
    return { ...await noControls(), reason: clean(await testId(page, "ligand-no-run").textContent()) };
  }, async value => {
    assert.equal(value.state, "unavailable");
    assert.ok(value.reason.includes(NO_RUN_REASON), value.reason);
    assert.ok(!/\d/.test(value.text), `a number is shown: ${value.text}`);
    assert.equal(value.controls, 0);
    return value;
  });
  const run = await rec_.step("U02-run", [], "Click 구조 분석, 새 run", async () => {
    await selectTab(page, "구조 분석");
    return newRun(page);
  }, async id => ({ run: id }));
  evidence.runs.A = run;
  await rec_.step("U03-unavailable", ["L-unavailable"], "Click 리간드 설계·탐색: 사용할 수 없음 with the capability reason " +
    "(worker_missing); no numbers, no controls, no ligand reads", async () => {
    const before = Date.now();
    await selectTab(page, TAB);
    await testId(page, "ligand-unavailable").waitFor({ timeout: 15000 });
    await page.waitForTimeout(2000);
    const ligandReads = log.filter(row => row.at >= before && row.path.includes("/ligand/")).map(row => `${row.method} ${row.path}`);
    return { ...await noControls(), reason: clean(await testId(page, "ligand-unavailable").textContent()), ligandReads };
  }, async value => {
    assert.equal(value.state, "unavailable");
    assert.ok(value.reason.includes("사용할 수 없음"), value.reason);
    assert.ok(value.reason.includes(`(${capability.reason_code})`), value.reason);
    assert.ok(value.reason.includes(capability.reason), value.reason);
    assert.ok(!/\d/.test(value.text), `a number is shown: ${value.text}`);
    assert.equal(value.controls, 0);
    assert.deepEqual(value.ligandReads, [], "the unavailable panel sent ligand requests");
    return value;
  });
  evidence.providerCalls.push(await providerCalls(page, run));
}

// ------------------------------------------------------------------ main
const RUNNERS = { main: modeMain, unavailable: modeUnavailable };

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const evidence = { schema: "m17_ligand_evidence@1", mode: input.mode, runs: {}, inputs: [], handles: {},
    fixtureLabels: [], providerCalls: [], partFailures: [], controls: {}, startedAt: new Date().toISOString() };
  const session = await launchOffscreen({ url: input.url, artifacts: input.artifacts, interactive: false });
  const log = requestLog(session.page);
  const rec_ = recorder(session, input, evidence);
  let error = null;
  let proof = null;
  try {
    proof = await offscreenProof(session.app, session.page);
    await RUNNERS[input.mode](session, input, rec_, evidence, log);
  } catch (caught) {
    error = caught;
  } finally {
    try { proof = { ...await offscreenProof(session.app, session.page), atStart: proof }; } catch { /* keep the start proof */ }
    await session.close();
  }
  const cases = rec_.cases();
  const providerZero = evidence.providerCalls.length > 0 && evidence.providerCalls.every(item => item.zero);
  const passed = !error && evidence.partFailures.length === 0 && offscreenComplete(proof) && proof.nonLoopbackRequests === 0 &&
    Object.keys(cases).length > 0 && Object.values(cases).every(value => value === "pass") && providerZero;
  evidence.finishedAt = new Date().toISOString();
  evidence.error = error ? String(error.stack ?? error) : null;
  evidence.requestCount = log.length;
  fs.writeFileSync(path.join(input.artifacts, "ligand-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  fs.writeFileSync(path.join(input.artifacts, "ligand-requests.jsonl"), log.map(row => JSON.stringify(row)).join("\n") + "\n");
  const harness = Object.fromEntries(["ligand-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m17_case_ledger_row@1", mode: input.mode, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", cases, runId: evidence.runs.A ?? null, runs: evidence.runs,
    handles: evidence.handles, inputs: evidence.inputs, fixtureLabels: evidence.fixtureLabels, controls: evidence.controls,
    buildId: buildId(), harness, offscreen: proof, externalRequestCount: proof ? proof.nonLoopbackRequests : null,
    providerCalls: evidence.providerCalls, providerCallsZero: providerZero, partFailures: evidence.partFailures,
    error: evidence.error, evidenceFile: path.basename(rec_.file), startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, runs: evidence.runs, cases }) + "\n");
  if (error) process.stderr.write(`ligand-flow ${input.mode} failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`ligand-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, oracle, candidateId };
