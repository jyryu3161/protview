"use strict";

// M14 top-level tab offscreen QA (spec §10.4). Real Electron offscreen page (isOffscreen, GPU/WebGL, paint).
// Every product mutation is a Playwright locator mouse/keyboard/file-chooser input. Observation is read-only:
// tab/tabpanel roles and data attributes, the bounded QA snapshots (window.__protviewQaSnapshot /
// __protviewQaChemical), renderer request events, Electron paint frames and GET reads of the loopback API.
// Labeled renderer-route fixtures (a 422 on the reports list, held list responses) are recorded in the ledger row and
// never produce a scientific value. Scientific artifacts are created through the existing screens only.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const sharp = require("sharp");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const { waitForViewer } = require("./normal-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const FIXTURES = path.join(REPO, "backend/tests/fixtures");
const CHEM = path.join(FIXTURES, "chemical");
const MODES = ["main", "chemical"];
const TAB_LABELS = ["구조 분석", "단백질 공학", "리간드 설계·탐색", "지식·보고서"];
const TAB_IDS = ["structure", "protein", "ligand", "knowledge"];
// Spec §6: what each unavailable part must name (reason + opening stages).
const UNAVAILABLE = {
  protein: { tab: "단백질 공학", title: "단백질 공학", stages: ["M20", "M21"], extra: [] },
};
// M15 replaced the knowledge tab's "사용할 수 없음" notice with the residue numbering screen (NumberingPanel);
// M17 replaced the ligand tab's notice with the ligand candidate screen (LigandPanel).
const NO_RUN_TEXT = "구조 분석 탭에서 run을 먼저 선택하세요";
const LIST_NAMES = { reports: "저장된 보고서", figures: "저장된 그림", summaries: "분석 흐름 요약" };
const FAULT_LABEL = "QA fault fixture (labeled renderer route, not a scientific value): reports list read failure";
const HOLD_LABEL = "QA held-response fixture (labeled renderer route; unchanged backend bytes released late)";
const TERMINAL = new Set(["complete", "cancelled", "blocked"]);
const PROVIDER_EVENT_TYPES = new Set(["egress", "egress_budget_settled", "viewer_dispatch_started"]);
const LIST_PATH = /^\/api\/runs\/([^/]+)\/(reports|viewer\/figures|analysis\/executions)$/;

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;

function provenanceLabel(name) {
  return {
    "public_1hsg.cif": "public PDB entry 1HSG (repository fixture)",
    "public_1ubq.cif": "public PDB entry 1UBQ (repository fixture; OpenMM input)",
    "prolif-vina-rec.pdb": "public ProLIF tutorial prepared receptor (prepared docking example; not experimental validation)",
    "prolif-vina-output.sdf": "public ProLIF tutorial docking-pose SDF (prepared docking example; not experimental validation)",
  }[name] ?? "unlabeled file";
}

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2);
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode)) throw new Error(
    `Usage: tabs-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> [--url http://127.0.0.1:3000]. ` +
    "main needs a fresh backend runs root (the no-run case runs first). Full sequence: scripts/m14_offscreen_acceptance.py.");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  value.artifacts = path.resolve(value.artifacts);
  value.url = new URL("/", value.url).toString();
  return value;
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
/** Provider-call evidence for one run: no gate audit/egress events and zero external tokens/USD in the budget. */
async function providerCalls(page, run) {
  const events = await runEvents(page, run);
  const budget = await readApi(page, `/runs/${run}/budget`);
  const egress = events.filter(event => PROVIDER_EVENT_TYPES.has(event.type)).length;
  return { run, egressEvents: egress, externalTokensUsed: budget.external_tokens?.used ?? null,
    usdUsed: budget.usd?.used ?? null,
    zero: egress === 0 && (budget.external_tokens?.used ?? 0) === 0 && (budget.usd?.used ?? 0) === 0 };
}
const execRecord = (page, run, id) => readApi(page, `/runs/${run}/analysis/executions/${id}`);
const terminal = rec => TERMINAL.has(rec.status) || (rec.status === "failed" && !rec.retryable_step);
const snapshot = page => page.evaluate(() => typeof window.__protviewQaSnapshot === "function" ? window.__protviewQaSnapshot() : null);
const chemicalSnapshot = page => page.evaluate(() => typeof window.__protviewQaChemical === "function" ? window.__protviewQaChemical() : null);
async function waitFor(page, probe, label, timeout = 60000) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    try { last = await probe(); if (last) return last; } catch (error) { last = String(error); }
    await page.waitForTimeout(150);
  }
  throw new Error(`${label}: timed out; last=${JSON.stringify(last)?.slice(0, 600)}`);
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

/** Every renderer request of the session (read-only), for the unavailable-tab and no-run request checks. */
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
  const file = path.join(artifacts, `tabs-${input.mode}.jsonl`);
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
      append({ caseId, cases, status: "pass", description, assertion, blockedRequests: proof.status.blockedRequests.length,
        paintCount: proof.status.paintCount, screenshot: fileRecord(proof.screenshot), paint: fileRecord(proof.paint.path),
        durationMs: Date.now() - started });
      mark(cases, true);
      return result;
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* keep the primary failure */ }
      const html = await page.evaluate(() => [document.querySelector(".mw-app-bar")?.outerHTML ?? "",
        ...[...document.querySelectorAll('[role="tabpanel"]')].filter(node => node.getAttribute("data-shown") !== "true" ||
          node.id !== "mw-app-panel-structure").map(node => node.outerHTML.slice(0, 20000))]).catch(() => null);
      if (html) fs.writeFileSync(path.join(artifacts, `${caseId}-failure.tabs.html`), html.join("\n\n"));
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
  try { const text = JSON.stringify(value); return text.length > 4000 ? `${text.slice(0, 4000)}…` : JSON.parse(text); }
  catch { return String(value); }
}

// ------------------------------------------------------------------ top-level tabs (real input only)
const tabButton = (page, label) => page.locator(".mw-app-tabs").getByRole("tab", { name: label, exact: true });
async function selectTab(page, label) {
  await tabButton(page, label).click();
  await waitFor(page, async () => await tabButton(page, label).getAttribute("aria-selected") === "true", `${label} selected`, 10000);
}
async function tabBar(page) {
  return page.locator(".mw-app-tabs [role=tab]").evaluateAll(items => items.map(item => ({
    label: item.textContent?.trim(), selected: item.getAttribute("aria-selected"),
    visible: item.getClientRects().length > 0 && getComputedStyle(item).visibility !== "hidden" })));
}
async function globalLine(page) {
  return page.evaluate(() => ({ run: document.querySelector(".mw-app-run")?.getAttribute("data-global-run") ?? null,
    runText: document.querySelector(".mw-app-run")?.textContent?.trim() ?? null,
    budget: document.querySelector(".mw-app-budget")?.textContent?.replace(/\s+/g, " ").trim() ?? null,
    structureRun: document.querySelector("#mw-app-panel-structure .mw-topbar .mw-mono")?.textContent?.trim() ?? null,
    structureShown: document.querySelector("#mw-app-panel-structure")?.getAttribute("data-shown") ?? null }));
}
/** The global budget element must equal the backend /budget read (expensive used/limit) after a tab switch. */
async function budgetMatches(page, run, minimumUsed) {
  return waitFor(page, async () => {
    const budget = await readApi(page, `/runs/${run}/budget`);
    const expected = `expensive ${budget.expensive_calls.used}/${budget.expensive_calls.limit}`;
    const line = await globalLine(page);
    return line.budget === expected && budget.expensive_calls.used >= minimumUsed
      ? { shown: line.budget, backend: budget.expensive_calls, run: line.run } : null;
  }, "global budget equals backend /budget", 15000);
}
/** Spec §4: a tab click itself triggers one GET /runs/{id}/budget (not only other refresh paths). */
async function budgetReadAfter(page, log, run, since) {
  const target = `/api/runs/${run}/budget`;
  return waitFor(page, async () => {
    const row = log.find(item => item.method === "GET" && item.path === target && item.at >= since);
    return row ? { path: row.path, afterClickMs: row.at - since } : null;
  }, "budget read after the tab click", 10000);
}
const apiPaths = (log, from, to = Infinity) => log.filter(row => row.api && row.at >= from && row.at < to);

/** Spec §6: notice + reason + opening stage, no numbers besides stage ids, no controls. */
async function unavailableNotice(page, key) {
  const spec = UNAVAILABLE[key];
  const panel = page.getByRole("tabpanel", { name: spec.tab, exact: true });
  await panel.waitFor({ timeout: 10000 });
  const section = panel.locator("section.mw-unavailable");
  await section.waitFor({ timeout: 10000 });
  const text = (await section.innerText()).replace(/\s+/g, " ").trim();
  const controls = await section.locator("button, input, select, textarea, a, [role=button], [tabindex]").count();
  const panelControls = await panel.locator("button, input, select, textarea, a, [role=button], [tabindex], img, canvas").count();
  assert.ok(text.includes("사용할 수 없음"), `${key}: 사용할 수 없음 missing: ${text}`);
  assert.ok(text.includes(spec.title), `${key}: title missing`);
  assert.ok(/구현하지 않/.test(text), `${key}: reason missing: ${text}`);
  for (const stage of spec.stages) assert.ok(text.includes(stage), `${key}: opening stage ${stage} missing`);
  for (const extra of spec.extra) assert.ok(text.includes(extra), `${key}: ${extra} missing`);
  assert.ok(!/\d/.test(text.replace(/M\d+/g, "")), `${key}: a number besides the stage ids is shown: ${text}`);
  assert.equal(controls, 0, `${key}: the notice holds controls`);
  assert.equal(panelControls, 0, `${key}: the tab holds controls/placeholders`);
  return { key, text, controls, panelControls };
}
/** M17: the ligand tab shows the ligand candidate screen for the global run, no unavailable notice. */
async function ligandScreen(page) {
  const panel = page.getByRole("tabpanel", { name: "리간드 설계·탐색", exact: true });
  await panel.waitFor({ timeout: 10000 });
  const screen = panel.locator('[data-testid="ligand-panel"]');
  await screen.waitFor({ timeout: 10000 });
  const notices = await panel.locator("section.mw-unavailable").count();
  assert.equal(notices, 0, "ligand: the M14 unavailable notice is still shown");
  return { key: "ligand", ligandScreen: true, state: await screen.getAttribute("data-ligand-state"), unavailableNotices: notices };
}
/** M15: the knowledge tab shows the residue numbering screen and the report library, no unavailable notice. */
async function knowledgeScreen(page) {
  const panel = page.getByRole("tabpanel", { name: "지식·보고서", exact: true });
  await panel.waitFor({ timeout: 10000 });
  await panel.locator("section.mw-numbering").waitFor({ timeout: 10000 });
  await library(page).waitFor({ timeout: 10000 });
  const notices = await panel.locator("section.mw-unavailable").count();
  assert.equal(notices, 0, "knowledge: the M14 unavailable notice is still shown");
  return { key: "knowledge", numberingScreen: true, reportLibrary: true, unavailableNotices: notices };
}

// ------------------------------------------------------------------ structure screen paths (copied from workflows-flow.cjs)
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
  await waitForBoot(page);
  const previous = new URL(page.url()).searchParams.get("run");
  await page.getByRole("button", { name: "새 run", exact: true }).click();
  await page.waitForFunction(old => {
    const current = new URL(location.href).searchParams.get("run");
    const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "새 run");
    return /^run_[a-f0-9]+$/.test(current ?? "") && current !== old && !!button && !button.disabled;
  }, previous, { timeout: 30000 });
  return new URL(page.url()).searchParams.get("run");
}
async function uploadLoad(page, file) {
  await page.getByRole("tab", { name: /^run/i }).click();
  const before = (await snapshot(page))?.sourceHandle ?? null;
  const chooser = page.waitForEvent("filechooser", { timeout: 30000 });
  await page.locator('input[type="file"]').first().click();
  await (await chooser).setFiles(file);
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).click();
  const viewer = await waitForViewer(page, value => !!value.sourceHandle && value.sourceHandle !== before &&
    value.sourceHandle.includes("/structure/") && value.catalogReady === true, 90000);
  return { handle: viewer.sourceHandle, file: { name: path.basename(file), ...fileRecord(file),
    provenance: provenanceLabel(path.basename(file)) } };
}
async function prepareManual(page, { keepWaters = false } = {}) {
  const back = page.getByRole("button", { name: "최신 구조로 돌아가기", exact: true });
  if (await back.isVisible().catch(() => false)) await back.click();
  const row = page.locator(".mw-workflow-row").filter({ has: page.getByRole("button", { name: "전처리", exact: true }) });
  if (keepWaters) await row.locator("select").nth(1).selectOption("keep_all");
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    /\/commands$/.test(new URL(response.url()).pathname) && response.request().postDataJSON()?.tool === "prepare_structure",
  { timeout: 90000 });
  await row.getByRole("button", { name: "전처리", exact: true }).click();
  const body = await (await posted).json();
  assert.equal(body.ok, true, `prepare failed: ${JSON.stringify(body).slice(0, 400)}`);
  const prepared = body.handle.handle;
  assert.match(prepared, /\/prepared_structure\//);
  await waitForViewer(page, value => value.sourceHandle === prepared && value.catalogReady === true, 90000);
  return { prepared };
}

// ------------------------------------------------------------------ analysis panel (copied from workflows-flow.cjs)
const PRODUCT_ISSUES = [];
const analysisPanel = (page, kind = "main") => page.locator(`section[aria-label="분석 흐름"][data-analysis-panel="${kind}"]`);
const controlButton = (panel, label) => panel.locator(`[aria-label="분석 실행 컨트롤"] [data-analysis-control="${label}"]`);
async function waitEnabled(page, locator, label, timeout = 60000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await locator.isVisible().catch(() => false) && await locator.isEnabled().catch(() => false)) return;
    await page.waitForTimeout(150);
  }
  const reason = await locator.getAttribute("data-analysis-control-reason", { timeout: 2000 }).catch(() => null) ??
    await locator.getAttribute("title", { timeout: 2000 }).catch(() => null);
  throw new Error(`${label} stayed disabled/hidden: ${reason}`);
}
async function reimport(page, panel) {
  await panel.getByRole("button", { name: "화면 선택 다시 가져오기", exact: true }).click();
  await panel.locator("[data-analysis-notice]").filter({ hasText: "화면 선택을 다시 가져왔습니다" }).waitFor({ timeout: 15000 });
}
async function chooseGoal(page, panel, goal) {
  const select = panel.getByRole("combobox", { name: "분석 목표", exact: true });
  const again = panel.getByRole("button", { name: "화면 선택 다시 가져오기", exact: true });
  if (await select.inputValue() === goal) {
    if (await again.isVisible().catch(() => false)) await reimport(page, panel);
    else { await select.selectOption(""); await select.selectOption(goal); }
  } else await select.selectOption(goal);
  await panel.locator(`[data-analysis-draft-goal="${goal}"], [data-analysis-placement="${goal}"], ` +
    `[data-analysis-template-unavailable="${goal}"]`).first().waitFor({ timeout: 30000 });
}
async function ensureSource(page, panel, expected) {
  const select = panel.getByRole("combobox", { name: "분석 소스", exact: true });
  for (let i = 0; i < 5; i++) {
    if (await select.inputValue() === expected) return { imported: true, reimports: i };
    await page.waitForTimeout(1000);
    await reimport(page, panel);
  }
  await select.selectOption(expected);
  return { imported: false, chosenInPanel: true };
}
async function openHistory(panel) {
  const details = panel.locator('details[aria-label="분석 기록"]');
  if ((await details.getAttribute("open")) === null) await details.locator("summary").first().click();
  await panel.getByRole("button", { name: "목록 다시 읽기", exact: true }).click();
}
async function createPlan(page, panel, run) {
  const button = panel.getByRole("button", { name: "계획 만들기", exact: true });
  await waitEnabled(page, button, "계획 만들기", 60000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/analysis/plans`, { timeout: 90000 });
  await button.click();
  const response = await posted;
  const body = await response.json();
  assert.ok([200, 201].includes(response.status()), `plan POST ${response.status()}: ${JSON.stringify(body).slice(0, 600)}`);
  const preview = panel.locator(`[aria-label="계획 미리보기"][data-analysis-plan-handle="${body.handle}"]`);
  const openExecution = await panel.locator('[aria-label="분석 실행"]').getAttribute("data-analysis-execution-id", { timeout: 1000 })
    .catch(() => null);
  try { await preview.waitFor({ timeout: openExecution ? 5000 : 30000 }); }
  catch (error) {
    if (!openExecution) throw error;
    PRODUCT_ISSUES.push({ issue: "new_plan_hidden_by_open_execution", planHandle: body.handle, openExecution,
      note: "the preview kept showing the open execution's plan; recovered with 계획 다시 열기 (M13 known issue)" });
    await openHistory(panel);
    await panel.getByRole("button", { name: `계획 다시 열기 ${body.ordinal}`, exact: true }).click();
    await preview.waitFor({ timeout: 30000 });
  }
  return body;
}
async function releaseStuckBusy(page, panel, id, after) {
  const select = panel.getByRole("combobox", { name: "분석 목표", exact: true });
  const deadline = Date.now() + 4000;
  while (Date.now() < deadline) {
    if (await select.isEnabled().catch(() => false)) return false;
    await page.waitForTimeout(200);
  }
  PRODUCT_ISSUES.push({ issue: "panel_busy_after_create_execution", after, executionId: id,
    note: "panel stayed busy after the request finished; recovered by 기록 다시 읽기 (M13 known issue)" });
  await panel.locator('[aria-label="분석 실행 컨트롤"]').getByRole("button", { name: "기록 다시 읽기", exact: true }).click();
  await waitFor(page, async () => await select.isEnabled() ? true : null, "panel busy released by 기록 다시 읽기", 15000);
  return true;
}
async function createExecution(page, panel, run, plan) {
  const button = panel.getByRole("button", { name: "실행 만들기", exact: true });
  await waitEnabled(page, button, "실행 만들기", 30000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/analysis/executions`, { timeout: 60000 });
  await button.click();
  const response = await posted;
  const body = await response.json();
  assert.equal(response.status(), 201, `execution POST ${response.status()}: ${JSON.stringify(body).slice(0, 400)}`);
  const id = body.execution.execution_id;
  assert.equal(body.execution.plan_handle, plan.handle);
  await panel.locator(`[aria-label="분석 실행"][data-analysis-execution-id="${id}"]`).waitFor({ timeout: 30000 });
  await releaseStuckBusy(page, panel, id, "실행 만들기");
  return body.execution;
}
const ACTION_PATH = { "계획 승인": "approve", "계산 승인": "scientific-approval", "다음 단계 실행": "advance", "중지": "cancel" };
async function clickControl(page, panel, run, id, label, timeout = 300000) {
  const button = controlButton(panel, label);
  await waitEnabled(page, button, label, 60000);
  const route = `/api/runs/${run}/analysis/executions/${id}/${ACTION_PATH[label]}`;
  const seen = [];
  const listener = response => { if (response.request().method() === "POST" && new URL(response.url()).pathname === route) seen.push(response); };
  page.on("response", listener);
  try {
    await button.click();
    const read = async response => { let body = null; try { body = await response.json(); } catch { /* keep null */ }
      return { status: response.status(), body }; };
    const first = await read(await waitFor(page, async () => seen[0] ?? null, `${label} response`, timeout));
    if (label === "중지" && first.status === 409 && first.body?.error === "stale_revision")
      return { ...await read(await waitFor(page, async () => seen[1] ?? null, "중지 automatic re-send", 60000)), resentAfterStale: true };
    return first;
  } finally { page.off("response", listener); }
}
async function panelInSync(page, panel, rec) {
  const node = panel.locator('[aria-label="분석 실행"]');
  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    if (await node.getAttribute("data-analysis-revision", { timeout: 2000 }).catch(() => null) === String(rec.revision)) return true;
    await page.waitForTimeout(150);
  }
  await panel.locator('[aria-label="분석 실행 컨트롤"]').getByRole("button", { name: "기록 다시 읽기", exact: true }).click();
  await page.waitForTimeout(600);
  return false;
}
/** Drive one execution with real clicks (계획 승인 / 계산 승인 / 다음 단계 실행) until it settles. */
async function drive(rec_, page, panel, run, id, { maxClicks = 40, jobTimeout = 420000, cases = [], prefix = "D" } = {}) {
  const clicks = [];
  for (let i = 0; i < maxClicks; i++) {
    let rec = await execRecord(page, run, id);
    if (terminal(rec) || (rec.status === "failed" && rec.retryable_step) || rec.status === "plan_only") return { rec, clicks };
    let label = "다음 단계 실행";
    if (rec.status === "awaiting_approval") label = "계획 승인";
    else if (rec.scientific_approval.state === "pending") label = "계산 승인";
    const button = controlButton(panel, label);
    if (label === "다음 단계 실행" && ["executing", "waiting_job"].includes(rec.status)) {
      const deadline = Date.now() + jobTimeout;
      while (Date.now() < deadline && !(await button.isEnabled().catch(() => false))) {
        await page.waitForTimeout(500);
        rec = await execRecord(page, run, id);
        if (terminal(rec)) return { rec, clicks };
      }
    }
    await panelInSync(page, panel, rec);
    const before = rec;
    const result = await rec_.step(`${prefix}${String(clicks.length + 1).padStart(2, "0")}-${ACTION_PATH[label]}`, cases,
      `Click ${label} (status ${before.status}, step ${before.current_step ?? "-"}, revision ${before.revision})`,
      () => clickControl(page, panel, run, id, label), async value => {
        assert.ok(value.status < 500, `${label} HTTP ${value.status}: ${JSON.stringify(value.body).slice(0, 400)}`);
        return { http: value.status, outcome: value.body?.request?.outcome ?? value.body?.error ?? null,
          statusAfter: value.body?.execution?.status ?? null };
      });
    clicks.push({ label, before: before.status, http: result.status });
  }
  throw new Error(`execution ${id} did not settle within ${maxClicks} clicks`);
}
function assertCompleted(rec, plan) {
  assert.equal(rec.status, "complete", `execution ended ${rec.status}: ${JSON.stringify(rec.blocked_reason ?? rec.steps.map(s => s.failure))}`);
  assert.equal(rec.plan_handle, plan.handle);
  for (const item of rec.steps) assert.equal(item.status, "completed", `${item.step_id} ${item.status}`);
  assert.match(rec.summary_handle ?? "", /\/workflow_summary\//);
  return { executionId: rec.execution_id, summary: rec.summary_handle,
    reports: rec.steps.filter(item => item.report_handle).map(item => item.report_handle) };
}
/** Plan (already made) → 실행 만들기 → drive → complete. */
async function executeToComplete(rec_, page, panel, run, plan, prefix, cases) {
  const created = await rec_.step(`${prefix}-execution`, cases, "Click 실행 만들기", () => createExecution(page, panel, run, plan),
    async value => { assert.equal(value.status, "awaiting_approval"); return { executionId: value.execution_id }; });
  await drive(rec_, page, panel, run, created.execution_id, { cases, prefix: `${prefix}-D` });
  const rec = await rec_.step(`${prefix}-complete`, cases, "Observe the completed execution record", () =>
    execRecord(page, run, created.execution_id), async value => {
    const done = assertCompleted(value, plan);
    await panel.locator(`[aria-label="분석 실행"][data-analysis-status="complete"]`).waitFor({ timeout: 30000 });
    return done;
  });
  return { id: created.execution_id, rec: assertCompleted(rec, plan) };
}

// ------------------------------------------------------------------ chemical workspace (copied from workflows-flow.cjs)
async function chooseChemicalFile(page, label, file) {
  const holder = page.locator(".mw-chemical-file").filter({ hasText: label });
  const input = holder.locator('input[type="file"]');
  const chooser = page.waitForEvent("filechooser", { timeout: 15000 });
  await input.click();
  await (await chooser).setFiles(file);
  await holder.getByText(/obj:\/\/run_/).waitFor({ timeout: 30000 });
  return { name: path.basename(file), ...fileRecord(file), provenance: provenanceLabel(path.basename(file)),
    handle: (await holder.getByText(/obj:\/\/run_/).innerText()).trim() };
}
async function openChemicalWorkspace(page) {
  await page.getByRole("button", { name: "화학 상호작용 작업 열기", exact: true }).waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: "화학 상호작용 작업 열기", exact: true }).click();
  await page.getByText("준비 입력과 실제 화학 상호작용", { exact: true }).waitFor({ timeout: 30000 });
  const run = new URL(page.url()).searchParams.get("run");
  await waitFor(page, async () => (await chemicalSnapshot(page))?.runId === run, "chemical workspace ready", 30000);
  return run;
}
const ACKS = ["공급된 수용체 결합 그래프가 완전함", "공급된 수소가 완전함", "공급된 protonation/tautomer 그대로 사용",
  "수용체 bond order/charge 추론 동의"];
async function chemicalCreateForm(page, run, receptor, sdf) {
  const files = { receptor: await chooseChemicalFile(page, "준비된 수용체 PDB/mmCIF", receptor),
    sdf: await chooseChemicalFile(page, "명시적 H가 있는 3D 리간드 V2000 SDF", sdf) };
  for (const label of ACKS) await page.getByLabel(label, { exact: true }).check();
  const firstPreview = page.waitForResponse(response => response.request().method() === "POST" &&
    response.url().includes(`/api/runs/${run}/chemical/preview`), { timeout: 60000 });
  await page.getByRole("button", { name: "준비 조건 미리보기", exact: true }).click();
  await firstPreview;
  await page.getByText(/준비 조건 미충족|계산 준비 가능/).first().waitFor({ timeout: 30000 });
  const terminalChecks = page.locator("label").filter({ hasText: "말단 확장 승인:" }).locator('input[type="checkbox"]');
  const terminals = await terminalChecks.count();
  for (let i = 0; i < terminals; i++) await terminalChecks.nth(i).check();
  const ready = page.waitForResponse(response => response.request().method() === "POST" &&
    response.url().includes(`/api/runs/${run}/chemical/preview`), { timeout: 60000 });
  await page.getByRole("button", { name: "준비 조건 미리보기", exact: true }).click();
  const preview = await (await ready).json();
  await page.getByText("계산 준비 가능", { exact: false }).first().waitFor({ timeout: 30000 });
  assert.equal(preview.ready, true, `preview not ready: ${JSON.stringify(preview.blockers).slice(0, 400)}`);
  return { files, terminalExtensions: terminals, previewReady: preview.ready };
}

// ------------------------------------------------------------------ structure state and paint
function sameNumbers(a, b, tolerance = 1e-6) {
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) <= tolerance;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((value, i) => sameNumbers(value, b[i], tolerance));
  if (a && b && typeof a === "object" && typeof b === "object") {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    return [...keys].every(key => sameNumbers(a[key], b[key], tolerance));
  }
  return a === b;
}
async function structureState(page) {
  const viewer = await snapshot(page);
  const rail = await page.locator("#mw-app-panel-structure [role=tab]").evaluateAll(items =>
    items.map(item => [item.textContent?.trim(), item.getAttribute("aria-selected")]));
  const representation = await page.locator('#mw-app-panel-structure [role="group"][aria-label="표현 방식"] [aria-pressed="true"]')
    .evaluateAll(items => items.map(item => item.textContent?.trim()));
  return { url: page.url(), sourceHandle: viewer?.sourceHandle ?? null, representation: viewer?.representation ?? null,
    pressedRepresentation: representation, selection: viewer?.selection ?? null, camera: viewer?.camera ?? null,
    nativeCamera: viewer?.nativeCamera ?? null, sessionId: viewer?.sessionId ?? null, generation: viewer?.generation ?? null,
    ready: viewer?.ready ?? null, catalogReady: viewer?.catalogReady ?? null, rail };
}
/** Electron paint frame of the visible Mol* canvas region: pixel statistics (a blank canvas has ~0 deviation). */
async function canvasPaint(session, name, selector = "canvas.mw-molstar-canvas:visible") {
  const { app, page, artifacts } = session;
  const canvas = page.locator(selector).first();
  const box = await canvas.boundingBox();
  assert.ok(box && box.width > 20 && box.height > 20, `Mol* canvas has no visible size: ${JSON.stringify(box)}`);
  const proof = await capture(app, page, artifacts, name);
  const meta = await sharp(proof.paint.path).metadata();
  const scale = meta.width / await page.evaluate(() => window.innerWidth);
  const region = { left: Math.max(0, Math.floor(box.x * scale)), top: Math.max(0, Math.floor(box.y * scale)) };
  region.width = Math.min(meta.width - region.left, Math.floor(box.width * scale));
  region.height = Math.min(meta.height - region.top, Math.floor(box.height * scale));
  const stats = await sharp(proof.paint.path).extract(region).stats();
  const stdev = stats.channels.slice(0, 3).map(item => Number(item.stdev.toFixed(3)));
  return { paint: fileRecord(proof.paint.path), screenshot: fileRecord(proof.screenshot), paintCount: proof.paint.paintCount,
    region, stdev, nonEmpty: Math.max(...stdev) > 3 };
}

// ------------------------------------------------------------------ reports library (지식·보고서)
const library = page => page.getByRole("region", { name: "보고서 보관함", exact: true });
const listRegion = (page, kind) => library(page).getByRole("region", { name: LIST_NAMES[kind], exact: true });
const contentRegion = page => library(page).getByRole("region", { name: "선택한 항목 내용", exact: true });
async function listState(page, kind) {
  return listRegion(page, kind).evaluate(node => {
    const alert = node.querySelector('[role="alert"]');
    const rows = [...node.querySelectorAll("li button")].map(button => ({
      codes: [...button.querySelectorAll("code")].map(code => code.textContent), text: button.textContent,
      kind: button.querySelector(".mw-library-kind")?.textContent ?? null, pressed: button.getAttribute("aria-pressed") }));
    const busy = !!node.querySelector('[aria-busy="true"]');
    const empty = node.textContent.includes("아직 없음");
    return { status: alert ? "error" : busy ? "loading" : rows.length ? "ready" : empty ? "empty" : "idle",
      rows, alert: alert?.textContent ?? null };
  });
}
async function expectedLists(page, run) {
  const reports = (await readApi(page, `/runs/${run}/reports`)).slice().sort((a, b) => a.created_seq - b.created_seq);
  const figures = (await readApi(page, `/runs/${run}/viewer/figures?offset=0&limit=100`)).rows;
  const executions = (await readApi(page, `/runs/${run}/analysis/executions`)).rows;
  const summaries = executions.filter(row => row.status === "complete" && row.summary_handle && !row.error)
    .sort((a, b) => (a.created_seq ?? Infinity) - (b.created_seq ?? Infinity));
  return { reports: reports.map(item => [item.handle, item.interaction_handle ?? item.result_handle ?? "없음"]),
    reportKinds: reports.map(item => item.analysis_type ?? "상호작용 보고서"),
    figures: figures.map(item => [item.handle, item.value.scene_handle]),
    summaries: summaries.map(item => [item.execution_id, item.summary_handle]),
    nonComplete: executions.filter(row => !(row.status === "complete" && row.summary_handle && !row.error)).map(row => row.execution_id),
    raw: { reports, figures: figures.map(item => item.handle), executions: executions.map(row => [row.execution_id, row.status]) } };
}
/** Wait until the three lists are settled and equal the backend lists of `run`. */
async function listsMatch(page, run, { skip = [] } = {}) {
  let expected = null;
  return waitFor(page, async () => {
    expected = await expectedLists(page, run);
    const shown = {};
    for (const kind of ["reports", "figures", "summaries"]) {
      if (skip.includes(kind)) continue;
      const state = await listState(page, kind);
      const want = expected[kind];
      if (want.length ? state.status !== "ready" : state.status !== "empty") return null;
      if (JSON.stringify(state.rows.map(row => row.codes)) !== JSON.stringify(want)) return null;
      shown[kind] = state;
    }
    if (shown.reports && JSON.stringify(shown.reports.rows.map(row => row.kind)) !== JSON.stringify(expected.reportKinds)) return null;
    const toolbar = await library(page).locator(".mw-library-run code").textContent();
    return toolbar === run ? { expected, shown, toolbarRun: toolbar } : null;
  }, `lists equal the backend lists of ${run}`, 30000);
}
async function libraryText(page) {
  return library(page).evaluate(node => node.textContent);
}
async function clickDownload(rec_, page, run, link, route, name, cases) {
  return rec_.step(name, cases, `Click ${await link.textContent()} and compare with the backend bytes`, async () =>
    downloadByClick(rec_.app, link), async downloaded => {
    const bytes = fs.readFileSync(downloaded.downloaded);
    const saved = await readBytes(page, route);
    assert.equal(sha(bytes), sha(saved), "downloaded bytes differ from the backend bytes of the same format");
    const url = new URL(downloaded.url);
    assert.equal(`${url.pathname}${url.search}`, `/api${route}`, "download link targets a different item/format");
    return { route, sha256: sha(bytes), backendSha256: sha(saved), bytes: bytes.length, downloaded: downloaded.downloaded };
  });
}

// ------------------------------------------------------------------ modes
async function modeMain(session, input, rec_, evidence, log) {
  const { page } = session;

  // ---- no run: guidance, no list calls (fresh backend root)
  await rec_.part("no-run", ["T-no-run"], () => rec_.step("N01-no-run", ["T-no-run"],
    "Fresh root: click 지식·보고서 before any run exists; guidance shown and no list request", async () => {
      await waitForBoot(page);
      const runs = await readApi(page, "/runs");
      const started = Date.now();
      await selectTab(page, "지식·보고서");
      await library(page).waitFor({ timeout: 10000 });
      await page.waitForTimeout(2000);
      const text = await libraryText(page);
      const requests = apiPaths(log, started).filter(row => LIST_PATH.test(row.path));
      const refresh = await library(page).getByRole("button", { name: "새로 고침", exact: true }).count();
      const line = await globalLine(page);
      await selectTab(page, "구조 분석");
      return { runs: runs.length, text, requests, refresh, line };
    }, async value => {
      assert.equal(value.runs, 0, "the backend root is not fresh (runs exist); the no-run case needs a fresh root");
      assert.ok(value.text.includes(NO_RUN_TEXT), `guidance missing: ${value.text}`);
      assert.deepEqual(value.requests, [], "list requests were sent without a run");
      assert.equal(value.refresh, 0);
      assert.equal(value.line.run, "");
      assert.equal(value.line.runText, "run 없음");
      return { guidance: NO_RUN_TEXT, listRequests: 0, globalRun: value.line.runText };
    }));

  await rec_.step("T01-tabs", ["T-tabs"], "Observe the tab bar; click each tab once and back (URL and reload unchanged)", async () => {
    const initial = await tabBar(page);
    const url = page.url();
    const navigations = [];
    const listener = frame => { if (frame === page.mainFrame()) navigations.push(frame.url()); };
    page.on("framenavigated", listener);
    const seen = [];
    for (const label of [...TAB_LABELS.slice(1), TAB_LABELS[0]]) {
      await selectTab(page, label);
      seen.push({ label, bar: await tabBar(page), url: page.url(),
        panel: await page.getByRole("tabpanel", { name: label, exact: true }).count() });
    }
    page.off("framenavigated", listener);
    return { initial, url, seen, navigations };
  }, async value => {
    assert.deepEqual(value.initial.map(item => item.label), TAB_LABELS);
    assert.deepEqual(value.initial.map(item => item.selected), ["true", "false", "false", "false"]);
    assert.ok(value.initial.every(item => item.visible));
    for (const item of value.seen) {
      assert.equal(item.url, value.url, "tab switch changed the address");
      assert.deepEqual(item.bar.map(tab => tab.selected), TAB_LABELS.map(label => String(label === item.label)));
      assert.equal(item.panel, 1, `${item.label} tabpanel not shown`);
    }
    assert.deepEqual(value.navigations, [], "tab switching navigated the page");
    assert.ok(TAB_LABELS.every(label => !/^(run|models)/i.test(label)));
    return { labels: value.initial.map(item => item.label), defaultSelected: "구조 분석", url: value.url };
  });

  // ---- run A (1HSG): structure, workflows, reports, figure
  const runA = await rec_.step("A01-new-run", ["T-global-run"], "Click 새 run; the global run id equals the structure screen's",
    () => newRun(page), async id => {
      const line = await waitFor(page, async () => { const value = await globalLine(page); return value.run === id ? value : null; },
        "global run id", 10000);
      assert.equal(line.structureRun, id);
      assert.equal(line.runText, id);
      return { run: id, line };
    });
  evidence.runs.A = runA;
  const loaded = await rec_.step("A02-upload-load", [], "Choose public_1hsg.cif, 구조 불러오기", () =>
    uploadLoad(page, path.join(FIXTURES, "public_1hsg.cif")), async value => value);
  evidence.inputs.push(loaded.file);
  const manual = await rec_.step("A03-prepare", [], "Click 전처리 (displayed default policies)", () => prepareManual(page),
    async value => value);
  evidence.handles.prepared = manual.prepared;

  const panel = analysisPanel(page, "main");
  const workflow = await rec_.part("workflows", ["T-reports-list"], async () => {
    const cases = [];
    await rec_.step("W01-goal", cases, "Select inspect_ligand for the displayed prepared structure and its ligand", async () => {
      await chooseGoal(page, panel, "inspect_ligand");
      const imported = await ensureSource(page, panel, manual.prepared);
      const select = panel.getByRole("combobox", { name: "분석 리간드 인스턴스", exact: true });
      await select.locator("option").nth(1).waitFor({ state: "attached", timeout: 30000 });
      await select.selectOption({ index: 1 });
      return { imported, source: await panel.getByRole("combobox", { name: "분석 소스", exact: true }).inputValue() };
    }, async value => { assert.equal(value.source, manual.prepared); return value; });
    const plan = await rec_.step("W02-plan", cases, "Click 계획 만들기 (inspect_ligand)", () => createPlan(page, panel, runA),
      async value => { assert.equal(value.executable, true, JSON.stringify(value.plan.unmet_prerequisites));
        return { handle: value.handle, ordinal: value.ordinal, operations: value.plan.steps.map(item => item.operation) }; });
    // A non-complete execution: created, then stopped while awaiting plan approval (status cancelled, no summary).
    const stopped = await rec_.step("W03-stopped-execution", cases, "Click 실행 만들기 then 중지 (non-complete execution)", async () => {
      const created = await createExecution(page, panel, runA, plan);
      const stop = await clickControl(page, panel, runA, created.execution_id, "중지");
      return { id: created.execution_id, stop };
    }, async value => {
      assert.equal(value.stop.status, 200);
      const rec = await execRecord(page, runA, value.id);
      assert.notEqual(rec.status, "complete");
      assert.equal(rec.summary_handle ?? null, null);
      return { executionId: value.id, status: rec.status };
    });
    await openHistory(panel);
    await panel.getByRole("button", { name: `계획 다시 열기 ${plan.ordinal}`, exact: true }).click();
    await panel.getByRole("button", { name: "실행 만들기", exact: true }).waitFor({ timeout: 30000 });
    const done = await executeToComplete(rec_, page, panel, runA, plan, "W04", cases);
    return { plan: plan.handle, stopped: stopped.id, complete: done.id, summary: done.rec.summary,
      reports: done.rec.reports };
  });
  evidence.handles.workflow = workflow;

  const figure = await rec_.part("figure", ["T-reports-list"], () => rec_.step("F01-figure", [],
    "Fill 보기 이름, click 현재 보기 저장, then 현재 보기 PNG 내보내기 (saved figure)", async () => {
      await page.getByRole("tab", { name: /^run/i }).click();
      await waitForViewer(page, value => value.sourceHandle === manual.prepared && value.catalogReady === true, 60000);
      await page.getByRole("textbox", { name: "보기 이름", exact: true }).fill("M14 탭 QA 보기");
      const scenePost = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${runA}/viewer/scenes`, { timeout: 30000 });
      const save = page.getByRole("button", { name: "현재 보기 저장", exact: true });
      await waitEnabled(page, save, "현재 보기 저장", 30000);
      await save.click();
      const scene = await (await scenePost).json();
      await page.getByText("보기 저장 완료 · M14 탭 QA 보기", { exact: true }).waitFor({ timeout: 30000 });
      const figurePost = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${runA}/viewer/figures`, { timeout: 45000 });
      const exportButton = page.getByRole("button", { name: "현재 보기 PNG 내보내기", exact: true });
      await waitEnabled(page, exportButton, "현재 보기 PNG 내보내기", 30000);
      await exportButton.click();
      const response = await figurePost;
      assert.equal(response.status(), 201, await response.text());
      return { scene: scene.handle, figure: (await response.json()).handle };
    }, async value => {
      const stored = await readApi(page, `/runs/${runA}/viewer/figures/selected?handle=${enc(value.figure)}`);
      assert.equal(stored.value.scene_handle, value.scene);
      return value;
    }));
  evidence.handles.figure = figure;

  // ---- structure state across the three other tabs (+ unavailable notices and their requests)
  await rec_.part("structure-state", ["T-structure-state", "T-unavailable"], async () => {
    const before = await rec_.step("S01-set-state", ["T-structure-state"],
      "Click ball-and-stick, then the exact ligand in MODELS (residue selection + camera focus)", async () => {
        const representation = page.getByRole("group", { name: "표현 방식" });
        await representation.getByRole("button", { name: "ball-and-stick", exact: true }).click();
        await waitForViewer(page, viewer => viewer.representation === "ball-and-stick", 30000);
        const prior = await waitForViewer(page);
        await page.getByRole("tab", { name: /^models/i }).click();
        await page.locator(".mw-ligand-item").first().click();
        await waitForViewer(page, viewer => viewer.selection !== null && viewer.sourceHandle === prior.sourceHandle, 30000);
        await page.waitForTimeout(1500); // camera focus transition settles before the state is recorded
        await waitForViewer(page, viewer => viewer.cameraTransitioning !== true, 15000);
        return { state: await structureState(page), paint: await canvasPaint(session, "S01-paint") };
      }, async value => {
        assert.equal(value.state.representation, "ball-and-stick");
        assert.ok(value.state.selection, "no residue selection observed");
        assert.ok(value.state.camera);
        assert.ok(value.paint.nonEmpty, `canvas paint looks empty before the trip: ${JSON.stringify(value.paint.stdev)}`);
        return value;
      });
    // Baseline: every API path the page requested before leaving the structure tab.
    const trip = [];
    for (const [key, label] of [["protein", "단백질 공학"], ["ligand", "리간드 설계·탐색"], ["knowledge", "지식·보고서"]]) {
      const cases = key === "knowledge" ? ["T-structure-state", "T-unavailable"] : ["T-structure-state", "T-unavailable"];
      trip.push(await rec_.step(`S02-${key}`, cases, key === "knowledge"
        ? `Click ${label}: numbering screen + report library (M15), no unavailable notice`
        : key === "ligand" ? `Click ${label}: ligand candidate screen (M17), no unavailable notice; read requests only`
          : `Click ${label}: 사용할 수 없음 notice; requests while shown`, async () => {
        const baseline = new Set(apiPaths(log, 0).map(row => `${row.method} ${row.path}`));
        const started = Date.now();
        await selectTab(page, label);
        const notice = key === "knowledge" ? await knowledgeScreen(page)
          : key === "ligand" ? await ligandScreen(page) : await unavailableNotice(page, key);
        await page.waitForTimeout(3000);
        const during = apiPaths(log, started);
        return { notice, during, baseline: [...baseline], line: await globalLine(page),
          structureRun: (await snapshot(page))?.sourceHandle ?? null };
      }, async value => {
        assert.equal(value.line.run, runA);
        if (key !== "knowledge") {
          const baseline = new Set(value.baseline);
          const fresh = value.during.filter(row => !baseline.has(`${row.method} ${row.path}`));
          const writes = value.during.filter(row => row.method !== "GET");
          // M17: the ligand screen reads its own lists (GET only) while shown; the unavailable tab sends none.
          if (key !== "ligand") assert.deepEqual(fresh, [], `the ${label} tab caused requests outside the pre-switch polling paths`);
          assert.deepEqual(writes, []);
        }
        return { notice: value.notice, requestsWhileShown: value.during.map(row => `${row.method} ${row.path}`),
          baselinePaths: value.baseline.length };
      }));
    }
    await rec_.step("S03-return", ["T-structure-state"], "Click 구조 분석; state equals the recorded state and the viewer repaints",
      async () => {
        await selectTab(page, "구조 분석");
        await page.locator("canvas.mw-molstar-canvas:visible").first().waitFor({ timeout: 15000 });
        await page.waitForTimeout(1000);
        return { state: await structureState(page), paint: await canvasPaint(session, "S03-paint") };
      }, async value => {
        const a = before.state, b = value.state;
        for (const key of ["url", "sourceHandle", "representation", "sessionId", "generation", "ready", "catalogReady"])
          assert.deepEqual(b[key], a[key], `${key} changed across the tab trip`);
        assert.deepEqual(b.pressedRepresentation, a.pressedRepresentation);
        assert.deepEqual(b.selection, a.selection, "residue selection changed across the tab trip");
        assert.deepEqual(b.rail, a.rail, "rail tab selection changed");
        assert.ok(sameNumbers(b.camera, a.camera), `camera changed: ${JSON.stringify([a.camera, b.camera])}`);
        if (a.nativeCamera || b.nativeCamera) assert.ok(sameNumbers(b.nativeCamera, a.nativeCamera), "native camera changed");
        assert.ok(value.paint.nonEmpty, `no non-empty paint after return: ${JSON.stringify(value.paint.stdev)}`);
        return { before: a, after: b, paintBefore: before.paint, paintAfter: value.paint, trip: trip.length };
      });
  });

  // ---- reports tab lists, content and downloads (run A)
  const listedA = await rec_.part("reports-list", ["T-reports-list"], () => rec_.step("L01-lists", ["T-reports-list"],
    "Click 지식·보고서: interaction + method report, saved figure, completed summary listed; stopped execution absent", async () => {
      await selectTab(page, "지식·보고서");
      return listsMatch(page, runA);
    }, async value => {
      const kinds = value.expected.reportKinds;
      assert.ok(kinds.includes("상호작용 보고서"), `no interaction report listed: ${kinds}`);
      assert.ok(kinds.some(kind => kind !== "상호작용 보고서"), `no method report listed: ${kinds}`);
      assert.ok(value.expected.figures.length >= 1, "no saved figure listed");
      assert.ok(value.expected.summaries.length >= 1, "no completed workflow summary listed");
      if (workflow) {
        assert.ok(value.expected.summaries.some(row => row[0] === workflow.complete));
        for (const handle of workflow.reports) assert.ok(value.expected.reports.some(row => row[0] === handle), handle);
        assert.match(workflow.stopped ?? "", /\S/, "stopped execution id missing");
        const text = await libraryText(page);
        assert.ok(!text.includes(workflow.stopped), "a non-complete execution is listed");
        assert.ok(value.expected.nonComplete.includes(workflow.stopped));
      }
      if (figure) assert.ok(value.expected.figures.some(row => row[0] === figure.figure));
      return { expected: value.expected, rows: Object.fromEntries(Object.entries(value.shown).map(([k, v]) => [k, v.rows])) };
    }));

  if (listedA) await rec_.part("reports-content", ["T-reports-content"], async () => {
    const cases = ["T-reports-content"];
    const expected = listedA.expected;
    const reportsRegion = listRegion(page, "reports");
    for (const [index, [handle]] of expected.reports.entries()) {
      const kind = expected.reportKinds[index];
      await rec_.step(`C01-report-${index + 1}`, cases, `Click the ${kind} row; saved Markdown shown as text`, async () => {
        await reportsRegion.locator("li button").filter({ hasText: handle }).click();
        const pre = contentRegion(page).getByLabel(`저장된 보고서 ${handle}`, { exact: true });
        await pre.waitFor({ timeout: 30000 });
        return { text: await pre.textContent(), pressed: await reportsRegion.locator("li button").filter({ hasText: handle })
          .getAttribute("aria-pressed") };
      }, async value => {
        const saved = await readApi(page, `/runs/${runA}/reports/selected?handle=${enc(handle)}`);
        assert.equal(value.text, saved.markdown, "shown text differs from the saved Markdown");
        assert.equal(value.pressed, "true");
        return { handle, kind, markdownSha256: sha(Buffer.from(value.text)) };
      });
      const links = contentRegion(page);
      await clickDownload(rec_, page, runA, links.getByRole("link", { name: "Markdown 다운로드", exact: true }),
        `/runs/${runA}/reports/download?handle=${enc(handle)}&format=markdown`, `C01-report-${index + 1}-md`, cases);
      await clickDownload(rec_, page, runA, links.getByRole("link", { name: "JSON 다운로드", exact: true }),
        `/runs/${runA}/reports/download?handle=${enc(handle)}&format=json`, `C01-report-${index + 1}-json`, cases);
    }
    const [figureHandle] = expected.figures[0];
    await rec_.step("C02-figure", cases, "Click the saved figure row; its PNG is shown", async () => {
      await listRegion(page, "figures").locator("li button").filter({ hasText: figureHandle }).click();
      const img = contentRegion(page).getByRole("img", { name: `저장된 그림 ${figureHandle}`, exact: true });
      await img.waitFor({ timeout: 30000 });
      return waitFor(page, async () => { const value = await img.evaluate(node => ({ complete: node.complete,
        width: node.naturalWidth, height: node.naturalHeight, src: node.getAttribute("src") }));
      return value.complete && value.width > 0 ? value : null; }, "figure image decoded", 30000);
    }, async value => {
      assert.equal(value.src, `/api/runs/${enc(runA)}/viewer/figures/download?handle=${enc(figureHandle)}&format=png`);
      return { figureHandle, ...value };
    });
    await clickDownload(rec_, page, runA, contentRegion(page).getByRole("link", { name: "PNG", exact: true }),
      `/runs/${runA}/viewer/figures/download?handle=${enc(figureHandle)}&format=png`, "C02-figure-png", cases);
    await clickDownload(rec_, page, runA, contentRegion(page).getByRole("link", { name: "출처 JSON", exact: true }),
      `/runs/${runA}/viewer/figures/download?handle=${enc(figureHandle)}&format=json`, "C02-figure-json", cases);
    const [executionId] = expected.summaries[0];
    await rec_.step("C03-summary", cases, "Click the workflow summary row; workflow_summary@1 shown read-only", async () => {
      await listRegion(page, "summaries").locator("li button").filter({ hasText: executionId }).click();
      const pre = contentRegion(page).getByLabel(`분석 흐름 요약 ${executionId}`, { exact: true });
      await pre.waitFor({ timeout: 30000 });
      return pre.textContent();
    }, async text => {
      const stored = await readApi(page, `/runs/${runA}/analysis/executions/${executionId}/summary`);
      assert.deepEqual(JSON.parse(text), stored, "shown summary differs from the stored summary");
      assert.equal(stored.summary.schema, "workflow_summary@1");
      return { executionId, summaryHandle: stored.handle };
    });
    await clickDownload(rec_, page, runA, contentRegion(page).getByRole("link", { name: "JSON 다운로드", exact: true }),
      `/runs/${runA}/analysis/executions/${executionId}/summary?download=json`, "C03-summary-json", cases);
  });

  // ---- reports list fault (labeled renderer fixture, only on /reports requests after opening the tab)
  if (listedA) await rec_.part("reports-fault", ["T-reports-fault"], async () => {
    const cases = ["T-reports-fault"];
    await selectTab(page, "구조 분석");
    const faulted = [];
    let armed = false;
    const matcher = url => new URL(url).pathname === `/api/runs/${runA}/reports`;
    const handler = route => {
      if (armed && route.request().method() === "GET") {
        faulted.push({ at: Date.now(), path: new URL(route.request().url()).pathname });
        return route.fulfill({ status: 422, contentType: "application/json",
          body: JSON.stringify({ detail: { error: "report_evidence_invalid", message: FAULT_LABEL } }) });
      }
      return route.continue();
    };
    await page.route(matcher, handler);
    evidence.fixtureLabels.push(FAULT_LABEL);
    try {
      await rec_.step("E01-fault", cases, "Arm the labeled 422 fixture, click 지식·보고서: only the reports list fails", async () => {
        armed = true;
        await selectTab(page, "지식·보고서");
        await listRegion(page, "reports").getByRole("alert").waitFor({ timeout: 30000 });
        await listsMatch(page, runA, { skip: ["reports"] });
        return { reports: await listState(page, "reports"), figures: await listState(page, "figures"),
          summaries: await listState(page, "summaries"), faulted: [...faulted] };
      }, async value => {
        assert.equal(value.reports.status, "error");
        assert.ok(value.reports.alert.includes(FAULT_LABEL) && value.reports.alert.includes("report_evidence_invalid"),
          `server reason not shown: ${value.reports.alert}`);
        assert.equal(value.reports.rows.length, 0, "the failed list kept rows");
        assert.equal(await listRegion(page, "reports").getByRole("button", { name: "다시 시도", exact: true }).count(), 1);
        assert.equal(value.figures.status, "ready");
        assert.equal(value.summaries.status, "ready");
        assert.ok(value.faulted.length >= 1);
        return { alert: value.reports.alert, faultedRequests: value.faulted.length, figures: value.figures.rows.length,
          summaries: value.summaries.rows.length };
      });
      await rec_.step("E02-retry", cases, "Disarm the fixture, click 다시 시도: the reports list reads again", async () => {
        armed = false;
        await listRegion(page, "reports").getByRole("button", { name: "다시 시도", exact: true }).click();
        return listsMatch(page, runA);
      }, async value => ({ reports: value.expected.reports.length, faultedTotal: faulted.length }));
    } finally {
      armed = false;
      await page.unroute(matcher, handler);
    }
    await rec_.step("E03-structure-intact", cases, "Click 구조 분석: the structure screen is unaffected", async () => {
      await selectTab(page, "구조 분석");
      return waitForViewer(page, value => value.sourceHandle === manual.prepared && value.catalogReady === true, 30000);
    }, async viewer => {
      const alerts = await page.locator("#mw-app-panel-structure [role=alert]").allTextContents();
      assert.ok(!alerts.some(text => text.includes(FAULT_LABEL)), "the fault reached the structure screen");
      return { source: viewer.sourceHandle, faultedWhileArmed: faulted.map(item => item.path) };
    });
  });

  // ---- run B (1UBQ): run switch, OpenMM job progressing on another tab, budget, method report
  const runB = await rec_.step("B01-new-run", ["T-global-run"], "Click 구조 분석 → 새 run; global run id follows", async () => {
    await selectTab(page, "구조 분석");
    await page.getByRole("tab", { name: /^run/i }).click();
    return newRun(page);
  }, async id => {
    const line = await waitFor(page, async () => { const value = await globalLine(page); return value.run === id ? value : null; },
      "global run id", 10000);
    assert.equal(line.structureRun, id);
    return { run: id, line };
  });
  evidence.runs.B = runB;
  const openmm = page.getByText("OpenMM 단백질 전용 최소화 · kJ/mol").locator("..");
  const job = await rec_.part("running-job", ["T-running-job"], async () => {
    const loadedB = await rec_.step("J01-setup", [], "Upload 1UBQ, load, keep_all waters, 전처리, preflight, policies, submit",
      async () => {
        const up = await uploadLoad(page, path.join(FIXTURES, "public_1ubq.cif"));
        await page.getByRole("combobox", { name: /^물/ }).selectOption("keep_all");
        const before = await waitForViewer(page);
        await page.getByRole("button", { name: "전처리", exact: true }).click();
        await openmm.getByRole("button", { name: "단백질 입력·제외 항목 확인" }).waitFor({ timeout: 30000 });
        const prepared = (await waitForViewer(page, viewer => viewer.sourceHandle !== before.sourceHandle, 60000)).sourceHandle;
        await openmm.getByRole("button", { name: "단백질 입력·제외 항목 확인" }).click();
        await openmm.getByRole("region", { name: "OpenMM 제외 성분" }).waitFor({ timeout: 30000 });
        await openmm.getByLabel(/protein_only 선택과 제외 항목/).check();
        await openmm.getByLabel(/기존 수소 제거 후 pH 7.0/).check();
        await openmm.getByRole("button", { name: "OpenMM 작업 제출" }).click();
        await openmm.getByText(/상태 queued/).waitFor({ timeout: 30000 });
        const jobId = await openmm.getByLabel("작업").inputValue();
        await openmm.getByRole("button", { name: "작업 시작" }).click();
        await openmm.getByRole("button", { name: "고비용 계산 승인 후 시작" }).waitFor({ timeout: 30000 });
        return { file: up.file, prepared, jobId };
      }, async value => { assert.ok(value.jobId); return value; });
    evidence.inputs.push(loadedB.file);
    const away = await rec_.step("J02-away", ["T-running-job"],
      "Click 고비용 계산 승인 후 시작; once running click 단백질 공학 and stay there until the job ends", async () => {
        await openmm.getByRole("button", { name: "고비용 계산 승인 후 시작" }).click();
        await openmm.getByText(/상태 running/).waitFor({ timeout: 60000 });
        const jobAtSwitch = await readApi(page, `/runs/${runB}/jobs/${loadedB.jobId}`);
        const shownAtSwitch = (await openmm.textContent()).match(/상태 \w+/)?.[0] ?? null;
        const left = Date.now();
        await selectTab(page, "단백질 공학");
        // The hidden structure screen keeps polling: its own OpenMM status text turns done while this tab is shown.
        const shownDone = await waitFor(page, async () => /상태 done/.test(await openmm.textContent()) ? Date.now() : null,
          "hidden OpenMM panel reached done", 240000);
        const jobDone = await readApi(page, `/runs/${runB}/jobs/${loadedB.jobId}`);
        const stillAway = await tabButton(page, "단백질 공학").getAttribute("aria-selected");
        const polls = apiPaths(log, left).filter(row => row.path.includes(`/runs/${runB}/jobs`) && row.method === "GET");
        return { jobAtSwitch: jobAtSwitch.status, shownAtSwitch, left, shownDoneAt: shownDone, jobDone: jobDone.status,
          stillAway, polls: polls.map(row => ({ at: row.at - left, path: row.path })) };
      }, async value => {
        assert.equal(value.jobAtSwitch, "running", "the job was not running when the tab was left");
        assert.equal(value.shownAtSwitch, "상태 running");
        assert.equal(value.stillAway, "true", "the check did not stay on the other tab");
        assert.equal(value.jobDone, "done");
        assert.ok(value.polls.length >= 1, "no job polling request while another tab was shown");
        return value;
      });
    await rec_.step("J03-return", ["T-running-job"], "Click 구조 분석 (no other input): the result is shown", async () => {
      await selectTab(page, "구조 분석");
      await openmm.getByText("시작 전위").waitFor({ timeout: 30000 });
      return openmm.innerText();
    }, async text => {
      assert.match(text, /상태 done/);
      return { shown: text.slice(0, 400), awayMs: away.shownDoneAt - away.left };
    });
    return { jobId: loadedB.jobId, prepared: loadedB.prepared };
  });
  evidence.handles.openmm = job;

  await rec_.part("budget-main", ["T-budget-main", "T-global-run"], () => rec_.step("G01-budget-main", ["T-budget-main", "T-global-run"],
    "After the expensive OpenMM job click 지식·보고서: global run and budget equal the backend", async () => {
      await selectTab(page, "단백질 공학");
      const clickedAt = Date.now();
      await selectTab(page, "지식·보고서");
      const refreshRead = await budgetReadAfter(page, log, runB, clickedAt);
      const atKnowledge = await budgetMatches(page, runB, 1);
      await selectTab(page, "구조 분석");
      const atStructure = await budgetMatches(page, runB, 1);
      const topbar = await page.locator("#mw-app-panel-structure .mw-top-budget").textContent().catch(() => null);
      return { refreshRead, atKnowledge, atStructure, topbar, line: await globalLine(page) };
    }, async value => {
      assert.equal(value.line.run, runB);
      assert.equal(value.line.structureRun, runB);
      return value;
    }));

  await rec_.part("method-report-b", ["T-run-switch"], () => rec_.step("B02-openmm-report", [],
    "Click OpenMM 방법 보고서 만들기 (run B method report)", async () => {
      await openmm.getByRole("button", { name: "OpenMM 방법 보고서 만들기" }).click();
      await openmm.getByLabel("저장된 OpenMM 보고서 미리보기").waitFor({ timeout: 30000 });
      return readApi(page, `/runs/${runB}/reports`);
    }, async rows => { assert.equal(rows.length, 1); return { report: rows[0].handle, kind: rows[0].analysis_type }; }));

  await rec_.part("run-switch", ["T-run-switch"], () => rec_.step("R01-run-switch", ["T-run-switch"],
    "Click 지식·보고서 after the run switch: only run B's lists", async () => {
      await selectTab(page, "지식·보고서");
      return listsMatch(page, runB);
    }, async value => {
      const text = await libraryText(page);
      const aHandles = listedA ? [...listedA.expected.reports.flat(), ...listedA.expected.figures.flat(),
        ...listedA.expected.summaries.flat()].filter(item => item !== "없음") : [];
      for (const handle of aHandles) assert.ok(!text.includes(handle), `run A item still shown: ${handle}`);
      assert.ok(!text.includes(runA));
      return { expected: value.expected, runAHandlesAbsent: aHandles.length };
    }));

  // ---- late responses: run B's list responses held across a run switch to A, released after A's lists show
  await rec_.part("late-response", ["T-late-response", "T-run-switch"], async () => {
    const cases = ["T-late-response", "T-run-switch"];
    await selectTab(page, "구조 분석");
    const held = [];
    const seenPaths = new Set();
    let holding = true;
    const matcher = url => { const found = new URL(url).pathname.match(LIST_PATH); return !!found && found[1] === runB; };
    const handler = async route => {
      const pathname = new URL(route.request().url()).pathname;
      if (!holding || route.request().method() !== "GET" || seenPaths.has(pathname)) return route.continue();
      seenPaths.add(pathname);
      const response = await route.fetch();
      held.push({ route, response, path: pathname, at: Date.now() });
    };
    await page.route(matcher, handler);
    evidence.fixtureLabels.push(HOLD_LABEL);
    try {
      await rec_.step("R02-held", cases, "Hold run B's list responses; click 지식·보고서 (lists stay loading)", async () => {
        await selectTab(page, "지식·보고서");
        await waitFor(page, async () => held.length >= 3 ? true : null, "three held list responses", 30000);
        return { held: held.map(item => item.path), states: { reports: (await listState(page, "reports")).status,
          figures: (await listState(page, "figures")).status, summaries: (await listState(page, "summaries")).status } };
      }, async value => {
        assert.deepEqual(Object.values(value.states), ["loading", "loading", "loading"]);
        return value;
      });
      await rec_.step("R03-switch-to-a", cases, "Click 구조 분석, choose run A in 저장된 run, click 지식·보고서", async () => {
        await selectTab(page, "구조 분석");
        await page.getByRole("tab", { name: /^run/i }).click();
        await page.locator("#run-choice").selectOption(runA);
        await waitFor(page, async () => (await globalLine(page)).run === runA ? true : null, "run A selected", 30000);
        await waitForViewer(page, value => value.sourceHandle !== null && value.catalogReady === true, 60000);
        await selectTab(page, "지식·보고서");
        return listsMatch(page, runA);
      }, async value => ({ lists: value.expected.raw }));
      await rec_.step("R04-release", cases, "Release run B's held responses; run A's lists stay, no run B item appears", async () => {
        holding = false;
        const released = [];
        for (const item of held) {
          try { await item.route.fulfill({ response: item.response }); released.push({ path: item.path, delivered: true }); }
          catch (error) { released.push({ path: item.path, delivered: false, reason: String(error).slice(0, 160) }); }
        }
        await page.waitForTimeout(2500);
        return { released, lists: await listsMatch(page, runA), text: await libraryText(page),
          downloads: (await session.app.evaluate(({ app }) => app.__offscreenQa.status().downloads.length)) };
      }, async value => {
        const bRows = await expectedLists(page, runB);
        for (const handle of [...bRows.reports.flat(), ...bRows.figures.flat(), ...bRows.summaries.flat()].filter(item => item !== "없음"))
          assert.ok(!value.text.includes(handle), `late run B item shown: ${handle}`);
        assert.ok(!value.text.includes(runB), "run B id shown after the switch");
        assert.equal((await globalLine(page)).run, runA);
        assert.ok(value.text.includes("목록에서 항목을 고르면"), "a selection survived the run switch");
        return { released: value.released, runALists: value.lists.expected.raw, downloadsSoFar: value.downloads };
      });
    } finally {
      holding = false;
      for (const item of held) await item.route.fulfill({ response: item.response }).catch(() => undefined);
      await page.unroute(matcher, handler);
    }
    await selectTab(page, "구조 분석");
  });

  for (const run of [runA, runB]) evidence.providerCalls.push(await providerCalls(page, run));
}

/** Chemical workspace: tab bar there, state preserved across a round trip, global run/budget after expensive jobs. */
async function modeChemical(session, input, rec_, evidence, log) {
  const { page } = session;
  const run = await rec_.step("H01-new-run", ["T-global-run"], "Click 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.runs.C = run;
  await rec_.step("H02-open", ["T-chemical-preserved", "T-global-run"],
    "Click 화학 상호작용 작업 열기: tab bar visible, global run equals the chemical screen's", async () => {
      await openChemicalWorkspace(page);
      return { bar: await tabBar(page), line: await globalLine(page) };
    }, async value => {
      assert.deepEqual(value.bar.map(item => item.label), TAB_LABELS);
      assert.ok(value.bar.every(item => item.visible), "tab bar not visible on the chemical screen");
      assert.equal(value.bar[0].selected, "true");
      assert.equal(value.line.run, run);
      assert.equal(value.line.structureRun, run, "chemical screen run differs from the global run");
      return value;
    });
  const panel = analysisPanel(page, "chemical");
  const form = await rec_.step("H03-form", [], "Choose public receptor + SDF, acknowledgements, preview until ready", () =>
    chemicalCreateForm(page, run, path.join(CHEM, "prolif-vina-rec.pdb"), path.join(CHEM, "prolif-vina-output.sdf")),
  async value => value);
  evidence.inputs.push(form.files.receptor, form.files.sdf);
  const plan = await rec_.step("H04-plan", [], "Select chemical_interactions (imports the ready request), 계획 만들기", async () => {
    await chooseGoal(page, panel, "chemical_interactions");
    return createPlan(page, panel, run);
  }, async value => { assert.equal(value.executable, true, JSON.stringify(value.plan.unmet_prerequisites)); return { handle: value.handle }; });
  const done = await executeToComplete(rec_, page, panel, run, { handle: plan.handle }, "H05", []);
  const rec = await execRecord(page, run, done.id);
  const shown = await rec_.step("H06-open-result", [], "Click 결과 열기 s02 (chemical interactions)", async () => {
    await panel.getByRole("button", { name: "결과 열기 s02", exact: true }).click();
    const target = rec.steps.find(item => item.step_id === "s02").outputs.chemical_interaction_set;
    return waitFor(page, async () => { const value = await chemicalSnapshot(page);
      return value?.resultHandle === target && value.catalogReady && value.resultTotal !== null ? value : null; },
    "chemical result displayed", 60000);
  }, async value => ({ resultHandle: value.resultHandle, resultTotal: value.resultTotal, sourceHandle: value.sourceHandle }));
  evidence.handles.chemical = { execution: done.id, result: shown.resultHandle };

  const chemState = async () => {
    const value = await chemicalSnapshot(page);
    const { native, ...rest } = value ?? {};
    return { ...rest, nativeSource: native?.sourceHandle ?? null, nativeSession: native?.sessionId ?? null,
      nativeGeneration: native?.generation ?? null, nativeCamera: native?.camera ?? null,
      nativeRepresentation: native?.representation ?? null, nativeSelection: native?.selection ?? null,
      screen: await page.getByText("준비 입력과 실제 화학 상호작용", { exact: true }).count(),
      execution: await panel.locator('[aria-label="분석 실행"]').getAttribute("data-analysis-execution-id").catch(() => null),
      executionStatus: await panel.locator('[aria-label="분석 실행"]').getAttribute("data-analysis-status").catch(() => null) };
  };
  const before = await rec_.step("H07-record", ["T-chemical-preserved"], "Record the chemical screen state and paint", async () => {
    await page.waitForTimeout(1500);
    return { state: await chemState(), paint: await canvasPaint(session, "H07-paint") };
  }, async value => {
    assert.equal(value.state.runId, run);
    assert.equal(value.state.screen, 1);
    assert.ok(value.paint.nonEmpty, `chemical canvas paint looks empty: ${value.paint.stdev}`);
    return value;
  });
  await rec_.step("H08-trip", ["T-chemical-preserved", "T-budget-chemical", "T-global-run"],
    "Click 단백질 공학 then 지식·보고서 (global budget = backend after the expensive jobs), then 구조 분석", async () => {
      await selectTab(page, "단백질 공학");
      const barAway = await tabBar(page);
      const clickedAt = Date.now();
      await selectTab(page, "지식·보고서");
      const refreshRead = await budgetReadAfter(page, log, run, clickedAt);
      const budget = await budgetMatches(page, run, 1);
      const line = await globalLine(page);
      await selectTab(page, "구조 분석");
      await page.getByText("준비 입력과 실제 화학 상호작용", { exact: true }).waitFor({ timeout: 15000 });
      await page.waitForTimeout(1000);
      const budgetBack = await budgetMatches(page, run, 1);
      return { refreshRead, barAway, budget, budgetBack, line, state: await chemState(), paint: await canvasPaint(session, "H08-paint"),
        bar: await tabBar(page) };
    }, async value => {
      assert.equal(value.line.run, run);
      assert.equal(value.line.structureRun, run);
      assert.ok(value.bar.every(item => item.visible));
      const a = before.state, b = value.state;
      for (const key of ["runId", "mode", "generation", "sourceHandle", "graphHandle", "catalogReady", "resultHandle",
        "resultTotal", "selectedRowId", "prepareJobId", "detectJobId", "nativeSource", "nativeSession", "nativeGeneration",
        "nativeRepresentation", "screen", "execution", "executionStatus"])
        assert.deepEqual(b[key], a[key], `chemical ${key} changed across the tab trip`);
      assert.deepEqual(b.nativeSelection, a.nativeSelection);
      assert.ok(sameNumbers(b.nativeCamera, a.nativeCamera), "chemical camera changed");
      assert.ok(value.paint.nonEmpty, `no non-empty chemical paint after return: ${value.paint.stdev}`);
      return { budget: value.budget, budgetBack: value.budgetBack, before: a, after: b, paint: value.paint };
    });
  evidence.providerCalls.push(await providerCalls(page, run));
}

// ------------------------------------------------------------------ main
const RUNNERS = { main: modeMain, chemical: modeChemical };

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const evidence = { schema: "m14_tabs_evidence@1", mode: input.mode, runs: {}, inputs: [], handles: {},
    fixtureLabels: [], providerCalls: [], partFailures: [], startedAt: new Date().toISOString() };
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
  if (PRODUCT_ISSUES.length) {
    for (const kind of new Set(PRODUCT_ISSUES.map(item => item.issue)))
      rec_.append({ caseId: `P-${kind}`, cases: [`P-${kind}`], status: "fail",
        description: "Product issue observed while driving (recovered through a visible control)",
        issues: PRODUCT_ISSUES.filter(item => item.issue === kind) });
    evidence.productIssues = PRODUCT_ISSUES;
  }
  const cases = rec_.cases();
  for (const item of PRODUCT_ISSUES) cases[`P-${item.issue}`] = "fail";
  const providerZero = evidence.providerCalls.length > 0 && evidence.providerCalls.every(item => item.zero);
  const passed = !error && evidence.partFailures.length === 0 && offscreenComplete(proof) && proof.nonLoopbackRequests === 0 &&
    Object.values(cases).every(value => value === "pass") && providerZero;
  evidence.finishedAt = new Date().toISOString();
  evidence.error = error ? String(error.stack ?? error) : null;
  evidence.requestCount = log.length;
  fs.writeFileSync(path.join(input.artifacts, "tabs-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  fs.writeFileSync(path.join(input.artifacts, "tabs-requests.jsonl"), log.map(row => JSON.stringify(row)).join("\n") + "\n");
  const harness = Object.fromEntries(["tabs-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m14_case_ledger_row@1", mode: input.mode, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", cases, runId: Object.values(evidence.runs)[0] ?? null, runs: evidence.runs,
    handles: evidence.handles, inputs: evidence.inputs, fixtureLabels: evidence.fixtureLabels, buildId: buildId(), harness,
    offscreen: proof, externalRequestCount: proof ? proof.nonLoopbackRequests : null, providerCalls: evidence.providerCalls,
    providerCallsZero: providerZero, partFailures: evidence.partFailures, error: evidence.error,
    evidenceFile: path.basename(rec_.file), startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, runs: evidence.runs, cases }) + "\n");
  if (error) process.stderr.write(`tabs-flow ${input.mode} failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`tabs-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main };
