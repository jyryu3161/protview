"use strict";

// M13 analysis-workflow offscreen QA (spec §12 "Electron 오프스크린 수락 QA").
// Every product mutation is a Playwright locator mouse/keyboard/file-chooser input in the real offscreen Electron page.
// Observation is read-only: data-analysis-* / data-pocket-* attributes, the bounded QA snapshots
// (window.__protviewQaSnapshot / __protviewQaChemical) and GET reads of the loopback API. Labeled fixtures
// (renderer-held responses, an OS-level SIGKILL of this QA run's own worker, API-created dry-run/attach records)
// are recorded in the ledger row and never produce a scientific value.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
const { launchOffscreen, capture, status, downloadByClick } = require("./driver.cjs");
const { waitForViewer } = require("./normal-flow.cjs");
const { fixtureOracle, catalog, measurement } = require("./comparison-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const FIXTURES = path.join(REPO, "backend/tests/fixtures");
const CHEM = path.join(FIXTURES, "chemical");
const M10_FIXTURES = path.join(__dirname, "fixtures");
const MODES = ["main", "m10", "race", "minimize", "chemical-create", "chemical-attach", "chemical-error", "dry-run",
  "unavailable"];
const TERMINAL = new Set(["complete", "cancelled", "blocked"]);
const DRY_RUN_NOTICE = "연습용 run의 계획은 미리보기 전용입니다. 실행하려면 일반 run에서 같은 입력으로 계획을 다시 만드세요.";
const LOCAL_RULES_NOTE = "로컬 규칙으로 만든 계획이며 모델 판단이 아닙니다";
const RESIDUE_FIELDS = ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"];
// Event types that record scientific work, jobs, charges or approvals. analysis_* workflow events and the plan object
// are excluded where a case checks that planning itself did no science.
const SCIENCE_EVENT_TYPES = new Set(["tool_called", "tool_succeeded", "tool_failed", "cache_hit", "job_submitted",
  "job_dispatch_intent", "job_terminal", "budget_reserved", "approval_requested", "approval_resolved"]);
const PROVIDER_EVENT_TYPES = new Set(["egress", "egress_budget_settled", "viewer_dispatch_started"]);

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;

function provenanceLabel(name) {
  const labels = {
    "public_1hsg.cif": "public PDB entry 1HSG (repository fixture)",
    "public_1ubq.cif": "public PDB entry 1UBQ (repository fixture; OpenMM input, 1HSG is refused by OpenMM)",
    "prolif-vina-rec.pdb": "public ProLIF tutorial prepared receptor (prepared docking example; not experimental validation)",
    "prolif-vina-output.sdf": "public ProLIF tutorial docking-pose SDF (prepared docking example; not experimental validation)",
    "synthetic-pentavalent-carbon.sdf": "labeled synthetic failure-control SDF (impossible valence; no scientific output)",
    "m11-attach-bonds-run.json": "run-bound receptor_bonds@1 sidecar generated from the QA run's own source catalog",
    "m11-attach-mapping-run.json": "run-bound labeled map_existing SDF→AtomRef mapping from the QA run's source catalog",
    "m11-attach-ligand-instance-run.json": "run-bound exact selected ligand instance from the QA run's source catalog",
  };
  if (labels[name]) return labels[name];
  if (name.startsWith("m10-")) return "labeled synthetic M10 coordinate fixture (frontend/tests/offscreen/fixtures)";
  return "unlabeled file";
}

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, run: null, otherRun: null, runsRoot: null,
    complex: null, mapping: null, ligand: null, sidecar: null, fixtureLabel: null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode)) throw new Error(
    `Usage: workflows-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> [--url http://127.0.0.1:3000] ` +
    "[--run run_... --other-run run_...] (race) [--runs-root <QA runs root>] (minimize: scopes the labeled worker fault) " +
    "[--run --complex obj://... --mapping --ligand --sidecar <scripts/m11_attach_browser_setup.py outputs>] (chemical-attach) " +
    "[--fixture-label <text>] (unavailable). Full sequence: scripts/m13_offscreen_acceptance.py.");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  if (value.run) assert.match(value.run, /^run_[a-f0-9]+$/);
  if (value.otherRun) assert.match(value.otherRun, /^run_[a-f0-9]+$/);
  if (value.mode === "race") assert.ok(value.run && value.otherRun, "--mode race needs --run (main run) --other-run");
  if (value.mode === "minimize") assert.ok(value.runsRoot, "--mode minimize needs --runs-root (scopes the worker fault)");
  if (value.mode === "chemical-attach") assert.ok(value.run && value.complex && value.mapping && value.ligand && value.sidecar,
    "--mode chemical-attach needs --run --complex --mapping --ligand --sidecar");
  for (const key of ["mapping", "ligand", "sidecar", "runsRoot"]) if (value[key]) value[key] = path.resolve(value[key]);
  value.artifacts = path.resolve(value.artifacts);
  value.origin = url.origin;
  value.url = new URL(value.run && value.mode !== "race" ? `/?run=${value.run}` : value.run ? `/?run=${value.run}` : "/",
    value.url).toString();
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
const scienceEvents = async (page, run) => (await runEvents(page, run))
  .filter(event => SCIENCE_EVENT_TYPES.has(event.type) ||
    (event.type === "object_created" && event.kind !== "analysis_plan" && event.kind !== "workflow_summary"))
  .map(event => ({ seq: event.seq, type: event.type, kind: event.kind ?? null, handle: event.handle ?? null }));
const execRecord = (page, run, id) => readApi(page, `/runs/${run}/analysis/executions/${id}`);
const terminal = rec => TERMINAL.has(rec.status) || (rec.status === "failed" && !rec.retryable_step);
async function snapshot(page) {
  return page.evaluate(() => typeof window.__protviewQaSnapshot === "function" ? window.__protviewQaSnapshot() : null);
}
async function chemicalSnapshot(page) {
  return page.evaluate(() => typeof window.__protviewQaChemical === "function" ? window.__protviewQaChemical() : null);
}
async function waitFor(page, probe, label, timeout = 60000) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    try { last = await probe(); if (last) return last; } catch (error) { last = String(error); }
    await page.waitForTimeout(150);
  }
  throw new Error(`${label}: timed out; last=${JSON.stringify(last)?.slice(0, 600)}`);
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

// ------------------------------------------------------------------ evidence
/** One JSONL row per step (with page screenshot + Electron paint frame). Every row names the M13 case ids it covers. */
function recorder(session, input, evidence) {
  const { app, page, artifacts } = session;
  const file = path.join(artifacts, `workflows-${input.mode}.jsonl`);
  const append = row => fs.appendFileSync(file, JSON.stringify(row) + "\n");
  const caseRows = {};
  const mark = (cases, ok) => { for (const id of cases) (caseRows[id] ??= []).push(ok); };
  async function step(caseId, cases, description, action, check, opts = {}) {
    const started = Date.now();
    const which = opts.session ?? session;
    let result;
    try {
      result = await action();
      const assertion = await check(result);
      const proof = await capture(which.app, which.page, which.artifacts, caseId);
      assert.equal(proof.status.blockedRequests.length, 0, "renderer attempted a non-loopback request");
      assert.equal(proof.status.offscreen, true);
      append({ caseId, cases, status: "pass", description, assertion, window: which === session ? "A" : "B",
        blockedRequests: proof.status.blockedRequests.length, paintCount: proof.status.paintCount,
        screenshot: fileRecord(proof.screenshot), paint: fileRecord(proof.paint.path), durationMs: Date.now() - started });
      mark(cases, true);
      return result;
    } catch (error) {
      let proof = null;
      try { proof = await capture(which.app, which.page, which.artifacts, `${caseId}-failure`); } catch { /* keep the primary failure */ }
      const panelHtml = await which.page.evaluate(() => [...document.querySelectorAll('section[aria-label="분석 흐름"]')]
        .map(node => node.outerHTML.replace(/<option[^>]*>[^<]*<\/option>/g, "").slice(0, 20000))).catch(() => null);
      if (panelHtml) fs.writeFileSync(path.join(which.artifacts, `${caseId}-failure.panel.html`), panelHtml.join("\n\n"));
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
      // The failing step already failed its own cases; cases never reached stay missing (the runner fails them).
      append({ caseId: `${name}-aborted`, cases: [], partCases: cases, status: "fail", description: `part ${name} aborted`,
        error: String(error.stack ?? error) });
      evidence.partFailures.push({ part: name, cases, error: String(error).slice(0, 800) });
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

// ------------------------------------------------------------------ shared UI paths (real input only)
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
async function backToLatest(page) {
  const back = page.getByRole("button", { name: "최신 구조로 돌아가기", exact: true });
  if (await back.isVisible().catch(() => false)) await back.click();
}
/** The ordinary 전처리 control with the displayed policies (optionally 물 유지). */
async function prepareManual(page, { keepWaters = false } = {}) {
  await backToLatest(page);
  const row = page.locator(".mw-workflow-row").filter({ has: page.getByRole("button", { name: "전처리", exact: true }) });
  if (keepWaters) await row.locator("select").nth(1).selectOption("keep_all");
  const before = (await snapshot(page))?.sourceHandle ?? null;
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    /\/commands$/.test(new URL(response.url()).pathname) && response.request().postDataJSON()?.tool === "prepare_structure",
  { timeout: 90000 });
  await row.getByRole("button", { name: "전처리", exact: true }).click();
  const body = await (await posted).json();
  assert.equal(body.ok, true, `prepare failed: ${JSON.stringify(body).slice(0, 400)}`);
  const prepared = body.handle.handle;
  assert.match(prepared, /\/prepared_structure\//);
  await waitForViewer(page, value => value.sourceHandle === prepared && value.catalogReady === true, 90000);
  return { prepared, before };
}

// ------------------------------------------------------------------ analysis panel helpers
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
async function chooseGoal(page, panel, goal) {
  const select = panel.getByRole("combobox", { name: "분석 목표", exact: true });
  const again = panel.getByRole("button", { name: "화면 선택 다시 가져오기", exact: true });
  // Re-selecting the same option fires no change: the visible re-import control imports the current screen instead.
  if (await select.inputValue() === goal) {
    if (await again.isVisible().catch(() => false)) await reimport(page, panel);
    else { await select.selectOption(""); await select.selectOption(goal); }
  } else await select.selectOption(goal);
  await panel.locator(`[data-analysis-draft-goal="${goal}"], [data-analysis-placement="${goal}"], ` +
    `[data-analysis-template-unavailable="${goal}"]`).first().waitFor({ timeout: 30000 });
}
async function reimport(page, panel) {
  await panel.getByRole("button", { name: "화면 선택 다시 가져오기", exact: true }).click();
  await panel.locator("[data-analysis-notice]").filter({ hasText: "화면 선택을 다시 가져왔습니다" }).waitFor({ timeout: 15000 });
}
/**
 * The draft must hold the displayed source. A re-inspection of the displayed structure can briefly leave nothing to
 * import; press 화면 선택 다시 가져오기 again, and only as a last resort choose the source in 분석 소스 (both real input).
 */
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
/** Click 계획 만들기 and return the stored plan record the panel shows. */
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
      note: "계획 만들기 succeeded but the preview kept showing the open execution's plan and 실행 만들기 did not appear; " +
        "recovered with 계획 다시 열기 in 이 run의 계획·실행" });
    await openHistory(panel);
    await panel.getByRole("button", { name: `계획 다시 열기 ${body.ordinal}`, exact: true }).click();
    await preview.waitFor({ timeout: 30000 });
  }
  return body;
}
function assertPlanPreview(record, goal) {
  const plan = record.plan;
  assert.equal(plan.schema, "analysis_plan@1");
  assert.equal(plan.goal, goal);
  assert.equal(plan.source, "local_rules");
  assert.equal(plan.planner, "local_rules@1");
  assert.equal(plan.plan_only, true);
  plan.steps.forEach((item, index) => assert.equal(item.step_id, `s${String(index + 1).padStart(2, "0")}`));
}
async function observePlanPreview(panel, record) {
  const preview = panel.locator(`[aria-label="계획 미리보기"][data-analysis-plan-handle="${record.handle}"]`);
  assert.equal(await preview.getAttribute("data-analysis-plan-executable"), String(record.executable));
  assert.equal(await preview.locator(`[data-analysis-plan-source="local_rules"]`).innerText(), LOCAL_RULES_NOTE);
  const steps = await preview.locator("li[data-analysis-plan-step]").evaluateAll(items =>
    items.map(item => ({ step: item.getAttribute("data-analysis-plan-step"), lane: item.getAttribute("data-analysis-plan-lane"),
      expensive: !!item.querySelector("[data-analysis-expensive]") })));
  assert.deepEqual(steps.map(item => [item.step, item.lane]), record.plan.steps.map(item => [item.step_id, item.lane]),
    "visible plan steps differ from the stored plan");
  steps.forEach(item => assert.equal(item.expensive, item.lane === "durable_job", `${item.step}: expensive badge`));
  const inputs = JSON.parse(await preview.locator("[data-analysis-plan-inputs]").innerText());
  assert.deepEqual(inputs, record.plan.inputs, "visible exact inputs differ from the stored plan inputs");
  const limits = await preview.locator("[data-analysis-limits]").innerText();
  assert.ok(limits.includes(`물리 시도 ${record.plan.limits.max_physical_attempts}`), limits);
  const unmet = await preview.locator("[data-analysis-unmet-code]").evaluateAll(items =>
    items.map(item => item.getAttribute("data-analysis-unmet-code")));
  assert.deepEqual(unmet, record.plan.unmet_prerequisites.map(item => item.code));
  return { handle: record.handle, sha256: record.plan_sha256, ordinal: record.ordinal, steps, unmet,
    executable: record.executable };
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
/**
 * Product issues observed while driving (never hidden): the panel kept its busy state after a finished request.
 * The flow then presses the panel's own visible 기록 다시 읽기 control (a real user recovery path) and continues;
 * every occurrence is written to the ledger row as a failing P-panel-busy-after-request case.
 */
const PRODUCT_ISSUES = [];
async function releaseStuckBusy(page, panel, id, after) {
  const select = panel.getByRole("combobox", { name: "분석 목표", exact: true });
  const deadline = Date.now() + 4000;
  while (Date.now() < deadline) {
    if (await select.isEnabled().catch(() => false)) return false;
    await page.waitForTimeout(200);
  }
  const reason = await controlButton(panel, "다음 단계 실행").getAttribute("data-analysis-control-reason", { timeout: 2000 }).catch(() => null);
  PRODUCT_ISSUES.push({ issue: "panel_busy_after_create_execution", after, executionId: id, observedReason: reason,
    note: "분석 목표/계획 승인 stayed disabled (요청을 처리하는 중입니다) after the request finished; " +
      "recovered by clicking the panel's 기록 다시 읽기" });
  await panel.locator('[aria-label="분석 실행 컨트롤"]').getByRole("button", { name: "기록 다시 읽기", exact: true }).click();
  await waitFor(page, async () => await select.isEnabled() ? true : null, "panel busy released by 기록 다시 읽기", 15000);
  return true;
}
const ACTION_PATH = { "계획 승인": "approve", "승인 철회": "revoke", "계산 승인": "scientific-approval",
  "다음 단계 실행": "advance", "재시도": "retry", "중지": "cancel" };
/** Real click on one execution control; waits for that control's own POST and returns {status, body}. */
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
      return { status: response.status(), body, requestBody: response.request().postDataJSON() }; };
    const first = await read(await waitFor(page, async () => seen[0] ?? null, `${label} response`, timeout));
    // 중지 on a stale revision: the panel re-reads the record and re-sends once by itself (product rule, spec §6).
    if (label === "중지" && first.status === 409 && first.body?.error === "stale_revision") {
      const second = await read(await waitFor(page, async () => seen[1] ?? null, "중지 automatic re-send", 60000));
      return { ...second, firstAttempt: { status: first.status, error: first.body?.error }, resentAfterStale: true };
    }
    return first;
  } finally { page.off("response", listener); }
}
/** Click 다음 단계 실행 and return while its request (a job start runs inside it) is still in flight. */
async function clickAdvanceInFlight(page, panel, run, id) {
  const button = controlButton(panel, "다음 단계 실행");
  await waitEnabled(page, button, "다음 단계 실행");
  const response = page.waitForResponse(item => item.request().method() === "POST" &&
    new URL(item.url()).pathname === `/api/runs/${run}/analysis/executions/${id}/advance`, { timeout: 600000 })
    .then(async item => ({ status: item.status(), body: await item.json().catch(() => null) }), error => ({ error: String(error) }));
  await button.click();
  return { response };
}
async function waitJobRunning(page, run, id, timeout = 120000) {
  return waitFor(page, async () => { const rec = await execRecord(page, run, id);
    return rec.steps[0].job_id && rec.steps[0].job_status === "running" ? rec : null; }, "owned job running", timeout);
}
async function panelInSync(page, panel, rec) {
  const node = panel.locator('[aria-label="분석 실행"]');
  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    if (await node.getAttribute("data-analysis-revision", { timeout: 2000 }).catch(() => null) === String(rec.revision)) return true;
    await page.waitForTimeout(150);
  }
  // The panel polls only while a step runs: re-read through its own visible control.
  await panel.locator('[aria-label="분석 실행 컨트롤"]').getByRole("button", { name: "기록 다시 읽기", exact: true }).click();
  await page.waitForTimeout(600);
  return false;
}
/**
 * Drive one execution with real clicks, one control per iteration, choosing the control from the recorded state:
 * 계획 승인 / 계산 승인 (pending gate only) / 다음 단계 실행. Stops at terminal, at a retryable failure, or at `until`.
 */
async function drive(rec_, page, panel, run, id, { until = null, maxClicks = 40, jobTimeout = 420000, cases = [],
  prefix = "D" } = {}) {
  const clicks = [];
  for (let i = 0; i < maxClicks; i++) {
    let rec = await execRecord(page, run, id);
    if (until && until(rec)) return { rec, clicks };
    if (terminal(rec) || (rec.status === "failed" && rec.retryable_step)) return { rec, clicks };
    if (rec.status === "plan_only") return { rec, clicks };
    let label = "다음 단계 실행";
    if (rec.status === "awaiting_approval") label = "계획 승인";
    else if (rec.scientific_approval.state === "pending") label = "계산 승인";
    const button = controlButton(panel, label);
    if (label === "다음 단계 실행" && ["executing", "waiting_job"].includes(rec.status)) {
      // A running step or job: the control stays disabled until the recorded job ends (panel polls read-only).
      const deadline = Date.now() + jobTimeout;
      while (Date.now() < deadline && !(await button.isEnabled().catch(() => false))) {
        await page.waitForTimeout(500);
        rec = await execRecord(page, run, id);
        if (until && until(rec)) return { rec, clicks };
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
          replayed: value.body?.replayed ?? null, statusAfter: value.body?.execution?.status ?? null,
          revisionAfter: value.body?.execution?.revision ?? null };
      });
    clicks.push({ label, before: before.status, http: result.status, outcome: result.body?.request?.outcome ??
      result.body?.error ?? null });
  }
  throw new Error(`execution ${id} did not settle within ${maxClicks} clicks`);
}
function assertCompleted(rec, plan) {
  assert.equal(rec.status, "complete", `execution ended ${rec.status}: ${JSON.stringify(rec.blocked_reason ?? rec.steps.map(s => s.failure))}`);
  assert.equal(rec.plan_handle, plan.handle);
  assert.equal(rec.source, "local_rules");
  assert.equal(rec.steps.length, plan.plan.steps.length);
  for (const item of rec.steps) assert.equal(item.status, "completed", `${item.step_id} ${item.status}`);
  assert.match(rec.summary_handle ?? "", /\/workflow_summary\//);
  return { executionId: rec.execution_id, revision: rec.revision, physicalAttempts: rec.physical_attempts,
    steps: rec.steps.map(item => ({ step: item.step_id, operation: item.operation, status: item.status,
      nullResult: item.null_result, outputs: item.outputs, report: item.report_handle, calls: item.child_call_ids,
      job: item.job_id, ownership: item.job_ownership, attempts: item.attempts })) };
}
async function panelStepStatuses(panel) {
  return panel.locator('ol[aria-label="실행 단계"] li[data-analysis-step]').evaluateAll(items =>
    items.map(item => [item.getAttribute("data-analysis-step"), item.getAttribute("data-analysis-step-status")]));
}
/** The result handle a report step documents: its step_output binding resolved through the recorded outputs. */
function reportSubject(plan, rec, stepId) {
  const planStep = plan.plan.steps.find(item => item.step_id === stepId);
  const binding = Object.values(planStep.bindings).find(item => item.kind === "step_output");
  assert.ok(binding, `${stepId} has no step_output binding`);
  const handle = rec.steps.find(item => item.step_id === binding.step_id).outputs[binding.output_name];
  assert.ok(handle, `${stepId}: bound output ${binding.step_id}.${binding.output_name} missing`);
  return handle;
}
/** Download both report files of one report step through its real links and check the received bytes. */
async function verifyReports(rec_, page, panel, run, plan, stepId, cases) {
  const rec = await execRecord(page, run, panel.__execId);
  const stepRec = rec.steps.find(item => item.step_id === stepId);
  assert.ok(stepRec.report_handle, `${stepId} has no report handle`);
  const subject = reportSubject(plan, rec, stepId);
  const holder = panel.locator(`li[data-analysis-step="${stepId}"] [data-analysis-report]`);
  const out = {};
  for (const [format, name] of [["markdown", "보고서 Markdown 다운로드"], ["json", "보고서 JSON 다운로드"]]) {
    out[format] = await rec_.step(`${panel.__prefix}-${stepId}-report-${format}`, cases,
      `Click ${name} of ${stepId} and decode the received bytes`, async () =>
        downloadByClick(rec_.app, holder.getByRole("link", { name, exact: true })), async downloaded => {
        const bytes = fs.readFileSync(downloaded.downloaded);
        const saved = await readBytes(page, `/runs/${run}/reports/download?handle=${enc(stepRec.report_handle)}&format=${format}`);
        assert.ok(bytes.equals(saved), "clicked download differs from the saved report bytes");
        const selected = await readApi(page, `/runs/${run}/reports/selected?handle=${enc(stepRec.report_handle)}`);
        assert.equal(selected.handle, stepRec.report_handle);
        const text = bytes.toString("utf8");
        if (format === "markdown") {
          assert.equal(text, selected.markdown, "Markdown differs from the saved report");
        } else {
          assert.deepEqual(JSON.parse(text), selected.manifest, "JSON differs from the saved report manifest");
          assert.ok(text.includes(subject), `report JSON does not reference its bound result ${subject}`);
        }
        const url = new URL(downloaded.url);
        assert.equal(url.searchParams.get("handle"), stepRec.report_handle);
        return { reportHandle: stepRec.report_handle, subject, format, sha256: downloaded.sha256, bytes: downloaded.bytes,
          downloaded: downloaded.downloaded, savedBytesMatched: true };
      });
  }
  return out;
}
async function verifySummary(rec_, page, panel, run, id, cases) {
  const rec = await execRecord(page, run, id);
  const viewed = await rec_.step(`${panel.__prefix}-summary-view`, cases, "Click 요약 보기", async () => {
    await panel.getByRole("button", { name: "요약 보기", exact: true }).click();
    await panel.locator(`[data-analysis-summary-handle="${rec.summary_handle}"]`).waitFor({ timeout: 30000 });
    return readApi(page, `/runs/${run}/analysis/executions/${id}/summary`);
  }, async value => {
    assert.equal(value.handle, rec.summary_handle);
    assert.equal(value.summary.schema, "workflow_summary@1");
    assert.equal(value.summary.execution_id, id);
    assert.equal(value.summary.plan_handle, rec.plan_handle);
    const rows = await panel.locator("tr[data-analysis-summary-step]").evaluateAll(items =>
      items.map(item => item.getAttribute("data-analysis-summary-step")));
    assert.deepEqual(rows, value.summary.steps.map(item => item.step_id));
    for (const item of value.summary.steps) {
      const stepRec = rec.steps.find(candidate => candidate.step_id === item.step_id);
      assert.equal(item.status, stepRec.status);
      assert.equal(item.report_handle ?? null, stepRec.report_handle ?? null);
    }
    return { summaryHandle: value.handle, steps: rows, physicalAttempts: value.summary.physical_attempts };
  });
  const downloaded = await rec_.step(`${panel.__prefix}-summary-json`, cases, "Click 요약 JSON 다운로드", async () =>
    downloadByClick(rec_.app, panel.getByRole("link", { name: "요약 JSON 다운로드", exact: true })), async value => {
    const bytes = fs.readFileSync(value.downloaded);
    const saved = await readBytes(page, `/runs/${run}/analysis/executions/${id}/summary?download=json`);
    assert.ok(bytes.equals(saved), "summary JSON download differs from the stored bytes");
    const parsed = JSON.parse(bytes.toString("utf8"));
    assert.equal(parsed.schema, "workflow_summary@1");
    assert.equal(parsed.execution_id, id);
    assert.equal(parsed.plan_handle, rec.plan_handle);
    assert.deepEqual(parsed.steps.map(item => item.report_handle ?? null), rec.steps.map(item => item.report_handle ?? null));
    return { sha256: value.sha256, bytes: value.bytes, downloaded: value.downloaded, storedBytesMatched: true };
  });
  return { viewed, downloaded };
}
async function openHistory(panel) {
  const details = panel.locator('details[aria-label="분석 기록"]');
  if ((await details.getAttribute("open")) === null) await details.locator("summary").first().click();
  await panel.getByRole("button", { name: "목록 다시 읽기", exact: true }).click();
}
/** Reopen an execution from the panel history; a read must not write events. */
async function reopenFromHistory(rec_, page, panel, run, id, expectedStatus, cases) {
  return rec_.step(`${panel.__prefix}-reopen`, cases, `Reopen ${id} from 이 run의 계획·실행`, async () => {
    // Viewer session bookkeeping (viewer_session_created) is the Mol* display, not the read; everything else counts.
    const recorded = async () => (await runEvents(page, run)).filter(event => event.type !== "viewer_session_created").length;
    const before = await recorded();
    await openHistory(panel);
    const row = panel.locator(`[data-analysis-history-execution="${id}"]`);
    await row.waitFor({ timeout: 30000 });
    const others = await panel.locator("[data-analysis-history-execution]").evaluateAll(items =>
      items.map(item => item.getAttribute("data-analysis-history-execution")));
    const other = others.find(item => item !== id);
    if (other) {
      await panel.getByRole("button", { name: `실행 다시 열기 ${other}`, exact: true }).click();
      await panel.locator(`[aria-label="분석 실행"][data-analysis-execution-id="${other}"]`).waitFor({ timeout: 30000 });
    }
    await panel.getByRole("button", { name: `실행 다시 열기 ${id}`, exact: true }).click();
    await panel.locator(`[aria-label="분석 실행"][data-analysis-execution-id="${id}"][data-analysis-status="${expectedStatus}"]`)
      .waitFor({ timeout: 30000 });
    await page.waitForTimeout(800);
    return { before, after: await recorded(), other: other ?? null };
  }, async value => {
    assert.equal(value.after, value.before, "reopening an execution wrote events");
    const rec = await execRecord(page, run, id);
    assert.equal(rec.status, expectedStatus);
    assert.deepEqual(await panelStepStatuses(panel), rec.steps.map(item => [item.step_id, item.status]));
    assert.equal(await panel.getAttribute("data-analysis-ui-state") !== null, true);
    return { ...value, historyStatus: await panel.locator(`[data-analysis-history-execution="${id}"]`)
      .getAttribute("data-analysis-history-status"), steps: await panelStepStatuses(panel) };
  });
}
/** Plan → execution → drive → complete, returning the plan, execution id and completed record. */
async function runToComplete(rec_, page, panel, run, goal, prefix, cases, { planned = null } = {}) {
  panel.__prefix = prefix;
  const plan = planned ?? await rec_.step(`${prefix}-plan`, cases, `Click 계획 만들기 (${goal})`, () => createPlan(page, panel, run),
    async value => { assertPlanPreview(value, goal); assert.equal(value.executable, true, JSON.stringify(value.plan.unmet_prerequisites));
      return observePlanPreview(panel, value); });
  const created = await rec_.step(`${prefix}-execution`, cases, "Click 실행 만들기", () => createExecution(page, panel, run, plan),
    async value => {
      assert.equal(value.status, "awaiting_approval");
      assert.equal(await panel.locator("[data-analysis-plan-approval]").getAttribute("data-analysis-plan-approval"), "not_approved");
      return { executionId: value.execution_id, status: value.status, scientific: value.scientific_approval.state };
    });
  panel.__execId = created.execution_id;
  const driven = await drive(rec_, page, panel, run, created.execution_id, { cases, prefix: `${prefix}-D` });
  const rec = await rec_.step(`${prefix}-complete`, cases, "Observe the completed execution record and step list", async () =>
    execRecord(page, run, created.execution_id), async value => {
    const done = assertCompleted(value, plan);
    await panel.locator(`[aria-label="분석 실행"][data-analysis-status="complete"]`).waitFor({ timeout: 30000 });
    assert.deepEqual(await panelStepStatuses(panel), value.steps.map(item => [item.step_id, item.status]));
    assert.equal(await panel.locator("[data-analysis-plan-approval]").getAttribute("data-analysis-plan-approval"), "approved");
    return { ...done, clicks: driven.clicks };
  });
  return { plan, id: created.execution_id, rec };
}
const openButton = (panel, stepId) => panel.getByRole("button", { name: `결과 열기 ${stepId}`, exact: true });

// ------------------------------------------------------------------ result observation (actual structure/overlay/table)
async function openContacts(rec_, page, panel, run, rec, stepId, structure, cases) {
  const handle = rec.steps.find(item => item.step_id === stepId).outputs.interaction_set;
  return rec_.step(`${panel.__prefix}-open-${stepId}`, cases, `Click 결과 열기 ${stepId} (contacts)`, async () => {
    await openButton(panel, stepId).click();
    const measured = await readApi(page, `/runs/${run}/objects?handle=${enc(handle)}&offset=0&limit=50`);
    const label = measured.total > 0 ? new RegExp(`기하 접촉 · ${measured.total}건`) : /scientific_null/;
    await page.getByText(label).first().waitFor({ timeout: 45000 });
    const viewer = await waitForViewer(page, value => value.sourceHandle === structure && value.catalogReady === true, 60000);
    return { measured, viewer };
  }, async value => {
    assert.equal(value.measured.meta.handle, handle);
    assert.equal(value.measured.meta.kind, "interaction_set");
    const rows = await page.getByRole("region", { name: "기하 접촉 측정 행", exact: true }).locator("tbody tr").count().catch(() => 0);
    assert.equal(rows, Math.min(50, value.measured.total), "visible contact rows differ from the stored page");
    for (const field of RESIDUE_FIELDS) if (value.measured.rows[0]) assert.ok(Object.hasOwn(value.measured.rows[0].residue, field));
    return { interactionHandle: handle, total: value.measured.total, visibleRows: rows,
      viewerSource: value.viewer.sourceHandle, representation: value.viewer.representation };
  });
}
async function openSasa(rec_, page, panel, run, rec, stepId, structure, cases) {
  return rec_.step(`${panel.__prefix}-open-${stepId}`, cases, `Click 결과 열기 ${stepId} (SASA)`, async () => {
    await openButton(panel, stepId).click();
    const region = page.getByRole("region", { name: "단백질 잔기 SASA 측정 행", exact: true });
    await region.waitFor({ timeout: 45000 });
    const viewer = await waitForViewer(page, value => value.sourceHandle === structure && value.catalogReady === true, 60000);
    return { rows: await region.locator("tbody tr").count(), viewer };
  }, async value => {
    const body = await page.locator("body").innerText();
    assert.match(body, /Å²/);
    assert.ok(value.rows > 0, "no SASA rows shown");
    return { sasaRows: value.rows, viewerSource: value.viewer.sourceHandle,
      sasaHandle: rec.steps.find(item => item.step_id === stepId).outputs };
  });
}
async function openStructure(rec_, page, panel, rec, stepId, cases) {
  const prepared = rec.steps.find(item => item.step_id === stepId).outputs.prepared_structure;
  return rec_.step(`${panel.__prefix}-open-${stepId}`, cases, `Click 결과 열기 ${stepId} (prepared structure)`, async () => {
    await openButton(panel, stepId).click();
    return waitForViewer(page, value => value.sourceHandle === prepared && value.catalogReady === true, 60000);
  }, async viewer => {
    assert.match(prepared, /\/prepared_structure\//);
    assert.ok(viewer.camera && viewer.molstarRepresentation, "Mol* representation/camera not observed");
    return { prepared, viewerSource: viewer.sourceHandle, representation: viewer.representation };
  });
}
async function openPocket(rec_, page, panel, run, rec, stepId, kind, cases) {
  const set = rec.steps.find(item => item.step_id === stepId).outputs.pocket_set;
  const pocketPanel = page.locator(`section[data-pocket-panel="${kind}"]`);
  return rec_.step(`${panel.__prefix}-open-${stepId}`, cases, `Click 결과 열기 ${stepId} (pocket) then 포켓 rank 1 선택`, async () => {
    await openButton(panel, stepId).click();
    await pocketPanel.locator("[data-pocket-total-count], [data-pocket-null-result]").first().waitFor({ timeout: 60000 });
    const summary = await readApi(page, `/runs/${run}/pockets/result?handle=${enc(set)}`);
    if (!summary.pockets.length) return { summary, overlay: null };
    await pocketPanel.getByRole("button", { name: "포켓 rank 1 선택", exact: true }).click();
    const overlay = await waitFor(page, async () => page.evaluate(expected => {
      const node = [...document.querySelectorAll(".mw-molstar[data-pocket-overlay]")].find(item => item.getClientRects().length > 0);
      return node && node.dataset.pocketOverlay === "applied" && node.dataset.pocketSetHandle === expected
        ? { ...node.dataset } : null;
    }, set), "pocket overlay applied", 60000);
    return { summary, overlay };
  }, async value => {
    assert.match(set, /\/pocket_set\//);
    assert.equal(value.summary.handle ?? set, set);
    const total = await pocketPanel.locator("[data-pocket-total-count]").getAttribute("data-pocket-total-count", { timeout: 2000 }).catch(() => null);
    if (value.summary.pockets.length) assert.equal(Number(value.overlay.pocketRank), 1);
    return { set, pockets: value.summary.pockets.length, shownTotal: total, overlay: value.overlay,
      selectedChains: value.summary.selected_chains };
  });
}

// ------------------------------------------------------------------ labeled fault fixture (minimize retry)
/** Real worker processes of this QA runs root (cwd inside it), as `ps` + `lsof` report them. Read-only. */
function workerPids(runsRoot, name) {
  const ps = execFileSync("ps", ["-axo", "pid=,command="], { encoding: "utf8" }).split("\n");
  const found = [];
  for (const line of ps) {
    const [pid, ...rest] = line.trim().split(/\s+/);
    const command = rest.join(" ");
    if (!pid || !command.includes(name)) continue;
    let cwd = "";
    try { cwd = execFileSync("lsof", ["-a", "-p", pid, "-d", "cwd", "-Fn"], { encoding: "utf8" }); } catch { continue; }
    const dirs = cwd.split("\n").filter(item => item.startsWith("n")).map(item => item.slice(1));
    if (dirs.some(dir => dir === runsRoot || dir.startsWith(runsRoot + path.sep))) found.push({ pid: Number(pid), command, cwd: dirs[0] });
  }
  return found;
}

// ------------------------------------------------------------------ chemical workspace helpers (copied from chemical-flow)
function nestedSelect(page, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return page.locator("label").filter({ hasText: new RegExp(`^\\s*${escaped}`) }).locator("select");
}
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
/** create_new: files, acknowledgements, terminal extension approvals, preview until 계산 준비 가능 (M11 visible path). */
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
function atomIdentity(ref) {
  return JSON.stringify([ref.structure_handle, ref.site_index, ref.atom_name, ref.altloc, ref.element,
    ...RESIDUE_FIELDS.map(field => ref.residue[field])]);
}
/** attach_existing with the labeled run-bound map_existing mapping (M11 visible path), preview until ready. */
async function chemicalAttachForm(page, run, input) {
  const fixture = JSON.parse(fs.readFileSync(input.mapping, "utf8"));
  const ligand = JSON.parse(fs.readFileSync(input.ligand, "utf8"));
  assert.equal(fixture.complex_handle, input.complex);
  await nestedSelect(page, "입력 방식").selectOption("attach_existing");
  await page.waitForFunction(handle => [...document.querySelectorAll("select")].some(select =>
    [...select.options].some(option => option.value === handle)), input.complex, { timeout: 30000 });
  await nestedSelect(page, "기존 준비된 복합체").selectOption(input.complex);
  const key = JSON.stringify(RESIDUE_FIELDS.map(field => ligand[field]));
  await page.waitForFunction(value => [...document.querySelectorAll("select")].some(select =>
    [...select.options].some(option => option.value === value)), key, { timeout: 120000 });
  await nestedSelect(page, "정확한 리간드 인스턴스").selectOption(key);
  await nestedSelect(page, "리간드 H 처리").selectOption(fixture.hydrogen_policy ?? "map_existing");
  const files = { sdf: await chooseChemicalFile(page, "명시적 H가 있는 3D 리간드 V2000 SDF", path.join(CHEM, "prolif-vina-output.sdf")) };
  await nestedSelect(page, "수용체 결합 제공").selectOption("sidecar");
  files.sidecar = await chooseChemicalFile(page, "완전한 receptor_bonds@1 JSON", input.sidecar);
  if (fixture.sdf_record_index != null) await nestedSelect(page, "SDF 기록").selectOption(String(fixture.sdf_record_index));
  const inventoryPromise = page.waitForResponse(response => response.request().method() === "POST" &&
    response.url().includes(`/api/runs/${run}/chemical/preview`), { timeout: 60000 });
  await page.getByRole("button", { name: "준비 조건 미리보기", exact: true }).click();
  const inventory = await (await inventoryPromise).json();
  assert.equal(inventory.ready, false, "attach preview was ready before any explicit mapping");
  const editor = page.getByRole("region", { name: "SDF 전체 원자 대응", exact: true });
  await editor.waitFor({ timeout: 30000 });
  const atomRows = editor.locator("label");
  for (const item of fixture.mapping) {
    const row = atomRows.filter({ hasText: new RegExp(`^SDF #${item.sdf_atom_index}\\b`) });
    const values = await row.locator("select option").evaluateAll(list => list.map(option => option.value));
    const matching = values.filter(value => value && atomIdentity(JSON.parse(value)) === atomIdentity(item.source_atom));
    assert.equal(matching.length, 1, `exact AtomRef unavailable for SDF #${item.sdf_atom_index}`);
    await row.locator("select").selectOption(matching[0]);
  }
  for (const label of ACKS) await page.getByLabel(label, { exact: true }).check();
  const terminalChecks = page.locator("label").filter({ hasText: "말단 확장 승인:" }).locator('input[type="checkbox"]');
  const terminals = await terminalChecks.count();
  for (let i = 0; i < terminals; i++) await terminalChecks.nth(i).check();
  const readyPromise = page.waitForResponse(response => response.request().method() === "POST" &&
    response.url().includes(`/api/runs/${run}/chemical/preview`), { timeout: 60000 });
  await page.getByRole("button", { name: "준비 조건 미리보기", exact: true }).click();
  const preview = await (await readyPromise).json();
  await page.getByText("계산 준비 가능", { exact: false }).first().waitFor({ timeout: 30000 });
  assert.equal(preview.ready, true, `attach preview not ready: ${JSON.stringify(preview.blockers).slice(0, 400)}`);
  return { files, mapped: fixture.mapping.length, policy: fixture.hydrogen_policy ?? "map_existing",
    fixtureLabel: fixture.label, terminalExtensions: terminals };
}
async function openChemicalResults(rec_, page, panel, rec, prefix, cases) {
  const s01 = rec.steps.find(item => item.step_id === "s01");
  const s02 = rec.steps.find(item => item.step_id === "s02");
  const prepared = await rec_.step(`${prefix}-open-s01`, cases, "Click 결과 열기 s01 (chemical preparation)", async () => {
    await openButton(panel, "s01").click();
    return waitFor(page, async () => { const value = await chemicalSnapshot(page);
      return value?.prepareJobId === s01.job_id && value.sourceHandle && value.catalogReady ? value : null; },
    "chemical preparation displayed", 60000);
  }, async value => {
    assert.ok(Object.values(s01.outputs).includes(value.graphHandle) || Object.values(s01.outputs).includes(value.sourceHandle),
      `displayed chemical structure/graph is not an s01 output: ${JSON.stringify({ outputs: s01.outputs, value })}`);
    return { prepareJobId: value.prepareJobId, sourceHandle: value.sourceHandle, graphHandle: value.graphHandle };
  });
  const result = await rec_.step(`${prefix}-open-s02`, cases, "Click 결과 열기 s02 (chemical interactions)", async () => {
    await openButton(panel, "s02").click();
    return waitFor(page, async () => { const value = await chemicalSnapshot(page);
      return value?.resultHandle === s02.outputs.chemical_interaction_set && value.catalogReady && value.resultTotal !== null
        ? value : null; }, "chemical result displayed", 60000);
  }, async value => ({ resultHandle: value.resultHandle, resultTotal: value.resultTotal, sourceHandle: value.sourceHandle,
    native: !!value.native }));
  return { prepared, result };
}
/** Make an explicit chain selection in a pocket panel (uncheck/recheck real checkboxes) for the displayed source. */
async function tickPocketChains(page, kind, run, source, keep) {
  const pocket = page.locator(`section[data-pocket-panel="${kind}"]`);
  const select = pocket.getByRole("combobox", { name: "포켓 검출 소스", exact: true });
  if (await select.count() && await select.inputValue() !== source) await select.selectOption(source);
  const preflight = await readApi(page, `/runs/${run}/pockets/preflight?structure=${enc(source)}`);
  const chains = preflight.available_chains.map(item => item.chain_auth);
  for (const chain of chains) await pocket.getByRole("checkbox", { name: `체인 ${chain}`, exact: true }).waitFor({ timeout: 30000 });
  // Any explicit selection (even the default one) must come from real checkbox input.
  for (const chain of chains) if (await pocket.getByRole("checkbox", { name: `체인 ${chain}`, exact: true }).isChecked())
    await pocket.getByRole("checkbox", { name: `체인 ${chain}`, exact: true }).uncheck();
  for (const chain of keep) await pocket.getByRole("checkbox", { name: `체인 ${chain}`, exact: true }).check();
  // The pocket panel reports its selection to the host in an effect after the render; let it settle before import.
  await waitFor(page, async () => {
    for (const chain of chains)
      if (await pocket.getByRole("checkbox", { name: `체인 ${chain}`, exact: true }).isChecked() !== keep.includes(chain)) return null;
    return true;
  }, "pocket chain checkboxes settled", 15000);
  await page.waitForTimeout(700);
  return { available: chains, selected: [...keep].sort() };
}

// ------------------------------------------------------------------ modes
/** 1HSG: NL unavailable, inspect_ligand from raw (incl. prepare) and prepared, find_cavities, prerequisites, stops, quick clicks. */
async function modeMain(session, input, rec_, evidence) {
  const { page } = session;
  const panel = analysisPanel(page, "main");
  const run = await rec_.step("M01-new-run", ["S-no-egress"], "Click 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.run = run;
  const loaded = await rec_.step("M02-upload-load", [], "Choose public_1hsg.cif, 구조 불러오기", () =>
    uploadLoad(page, path.join(FIXTURES, "public_1hsg.cif")), async value => value);
  evidence.inputs.push(loaded.file);
  evidence.handles.raw = loaded.handle;

  await rec_.part("nl", ["S-nl-unavailable"], () => rec_.step("M03-nl-unavailable", ["S-nl-unavailable"],
    "Observe 자연어로 계획 만들기 (사용할 수 없음) and force-click it", async () => {
      const button = panel.getByRole("button", { name: "자연어로 계획 만들기 (사용할 수 없음)", exact: true });
      await button.waitFor({ timeout: 30000 });
      const posts = [];
      const listener = request => { if (request.method() === "POST") posts.push(new URL(request.url()).pathname); };
      page.on("request", listener);
      let forced = "clicked";
      try { await button.click({ force: true, timeout: 3000 }); } catch (error) { forced = `input refused: ${String(error).slice(0, 120)}`; }
      await page.waitForTimeout(700);
      page.off("request", listener);
      return { disabled: await button.isDisabled(), posts, forced,
        reason: await panel.locator("[data-analysis-nl-unavailable]").innerText() };
    }, async value => {
      const cap = (await readApi(page, "/capabilities")).methods.analysis_workflows;
      assert.equal(cap.natural_language_planning.available, false);
      assert.equal(value.disabled, true);
      assert.deepEqual(value.posts, []);
      assert.equal(value.reason.trim(), cap.natural_language_planning.reason);
      const templates = await readApi(page, `/runs/${run}/analysis/templates`);
      const goals = await panel.getByRole("combobox", { name: "분석 목표", exact: true }).locator("option").evaluateAll(items =>
        items.map(item => item.value).filter(Boolean));
      assert.deepEqual(goals.sort(), templates.templates.map(item => item.goal).sort());
      assert.equal(goals.length, 6);
      return { reason: value.reason, forcedClick: value.forced, capability: { available: cap.available, planner: cap.planner },
        goals, providerEvidence: await providerCalls(page, run) };
    }));

  // ---- inspect_ligand from the raw structure (prepare step inside the plan)
  const raw = await rec_.part("inspect-raw", ["W-inspect-raw", "S-prereq-ligand", "S-stop-plan-approval"], async () => {
    const cases = ["W-inspect-raw"];
    await rec_.step("IR01-goal", cases, "Select 분석 목표 inspect_ligand while the raw 1HSG structure is displayed", async () => {
      await chooseGoal(page, panel, "inspect_ligand");
      return { source: await panel.getByRole("combobox", { name: "분석 소스", exact: true }).inputValue() };
    }, async value => {
      assert.equal(value.source, loaded.handle, "the draft did not import the displayed raw source");
      await panel.getByRole("combobox", { name: "분석 altloc", exact: true }).waitFor();
      assert.equal(await panel.getByRole("combobox", { name: "분석 리간드 인스턴스", exact: true }).inputValue(), "", "a ligand was preselected");
      return { importedSource: value.source, preparationFieldset: true, ligandPreselected: false };
    });
    const unmet = await rec_.step("IR02-no-ligand-plan", ["S-prereq-ligand"],
      "Click 계획 만들기 without choosing a ligand; 실행 만들기 must stay disabled (forced click sends nothing)", async () => {
        const plan = await createPlan(page, panel, run);
        const button = panel.getByRole("button", { name: "실행 만들기", exact: true });
        const posts = [];
        const listener = request => { if (request.method() === "POST" && /\/analysis\/executions$/.test(new URL(request.url()).pathname)) posts.push(1); };
        page.on("request", listener);
        let forced = "clicked";
        try { await button.click({ force: true, timeout: 3000 }); } catch (error) { forced = `input refused: ${String(error).slice(0, 120)}`; }
        await page.waitForTimeout(600);
        page.off("request", listener);
        return { plan, posts, forced, disabled: await button.isDisabled(),
          reason: await panel.locator("[data-analysis-execution-reason]").innerText() };
      }, async value => {
        assert.equal(value.plan.executable, false);
        assert.deepEqual(value.plan.plan.unmet_prerequisites.map(item => item.code), ["ligand_required"]);
        assert.equal(value.disabled, true);
        assert.deepEqual(value.posts, []);
        const preview = await observePlanPreview(panel, value.plan);
        assert.equal(await panel.locator("[data-analysis-missing]").count() > 0, true);
        return { ...preview, executionReason: value.reason, forcedClick: value.forced };
      });
    evidence.handles.unmetLigandPlan = unmet.handle;
    const ligand = await rec_.step("IR03-choose-ligand", cases, "Select the exact ligand instance and explicit preparation policies",
      async () => {
        const select = panel.getByRole("combobox", { name: "분석 리간드 인스턴스", exact: true });
        await select.locator("option").nth(1).waitFor({ state: "attached", timeout: 30000 });
        await select.selectOption({ index: 1 });
        await panel.getByRole("combobox", { name: "분석 altloc", exact: true }).selectOption("highest_occupancy");
        await panel.getByRole("combobox", { name: "분석 물 처리", exact: true }).selectOption("strip_all");
        await panel.getByRole("combobox", { name: "분석 수소 처리", exact: true }).selectOption("strip");
        return { shown: await panel.locator("[data-analysis-ligand]").innerText() };
      }, async value => {
        const residues = await readApi(page, `/runs/${run}/structures/residues?handle=${enc(loaded.handle)}`);
        assert.ok(residues.ligands.length >= 1);
        return { ligandText: value.shown, ligandCount: residues.ligands.length };
      });
    // Stop while waiting for plan approval (first execution), then the main path on a second execution of the same plan.
    const plan = await rec_.step("IR04-plan", cases, "Click 계획 만들기 (inspect_ligand from raw)", () => createPlan(page, panel, run),
      async value => { assertPlanPreview(value, "inspect_ligand"); assert.equal(value.executable, true);
        assert.deepEqual(value.plan.steps.map(item => item.operation), ["prepare_structure", "compute_interactions",
          "compute_interface_sasa", "inspection_report", "method_report"]);
        for (const field of RESIDUE_FIELDS) assert.ok(Object.hasOwn(value.plan.inputs.ligand, field), `ligand ${field}`);
        assert.ok(value.plan.inputs.preparation, "raw source plan lacks the explicit preparation policy");
        return { ...await observePlanPreview(panel, value), ligand: value.plan.inputs.ligand, ligandShown: ligand.ligandText }; });
    await rec_.part("stop-plan-approval", ["S-stop-plan-approval"], async () => {
      const created = await rec_.step("IR05-stop-exec", ["S-stop-plan-approval"], "Click 실행 만들기", () =>
        createExecution(page, panel, run, plan), async value => ({ executionId: value.execution_id, status: value.status }));
      const before = await scienceEvents(page, run);
      await rec_.step("IR06-stop-awaiting-approval", ["S-stop-plan-approval"], "Click 중지 while awaiting plan approval", () =>
        clickControl(page, panel, run, created.execution_id, "중지"), async value => {
        assert.equal(value.status, 200);
        const rec = await execRecord(page, run, created.execution_id);
        assert.equal(rec.status, "cancelled");
        assert.equal(rec.stop?.reason, "stop");
        await panel.locator("[data-analysis-stop]").waitFor({ timeout: 15000 });
        assert.deepEqual(await scienceEvents(page, run), before, "stopping before approval started scientific work");
        for (const label of ["계획 승인", "다음 단계 실행"]) assert.equal(await controlButton(panel, label).isDisabled(), true);
        return { executionId: rec.execution_id, status: rec.status, stop: rec.stop,
          stopText: await panel.locator("[data-analysis-stop]").innerText() };
      });
      evidence.handles.stoppedBeforeApproval = created.execution_id;
      await openHistory(panel);
      await panel.getByRole("button", { name: `계획 다시 열기 ${plan.ordinal}`, exact: true }).click();
      await panel.getByRole("button", { name: "실행 만들기", exact: true }).waitFor({ timeout: 30000 });
    });
    const done = await runToComplete(rec_, page, panel, run, "inspect_ligand", "IR", cases, { planned: plan });
    evidence.handles.inspectRaw = { plan: plan.handle, execution: done.id, summary: done.rec.summary_handle ?? null };
    const recRaw = await execRecord(page, run, done.id);
    const prepared = recRaw.steps.find(item => item.step_id === "s01").outputs.prepared_structure;
    evidence.handles.prepared = prepared;
    await openStructure(rec_, page, panel, recRaw, "s01", cases);
    await openContacts(rec_, page, panel, run, recRaw, "s02", prepared, cases);
    await openSasa(rec_, page, panel, run, recRaw, "s03", prepared, cases);
    await verifyReports(rec_, page, panel, run, plan, "s04", cases);
    await verifyReports(rec_, page, panel, run, plan, "s05", cases);
    await verifySummary(rec_, page, panel, run, done.id, cases);
    await reopenFromHistory(rec_, page, panel, run, done.id, "complete", cases);
    return { prepared };
  });

  // ---- the ordinary 전처리 control makes the prepared structure the displayed source
  const manual = await rec_.step("M10-prepare-manual", [], "Click the ordinary 전처리 control (displayed default policies)",
    () => prepareManual(page), async value => ({ ...value, sameAsWorkflowPrepare: value.prepared === raw?.prepared }));
  evidence.handles.displayedPrepared = manual.prepared;

  // ---- inspect_ligand from the prepared structure (cutoff 4.5) + quick double click on 다음 단계 실행
  await rec_.part("inspect-prepared", ["W-inspect-prepared", "S-race-clicks"], async () => {
    const cases = ["W-inspect-prepared"];
    panel.__prefix = "IP";
    await rec_.step("IP01-goal", cases, "Select inspect_ligand for the displayed prepared structure, ligand, cutoff 4.5", async () => {
      await chooseGoal(page, panel, "inspect_ligand");
      const imported = await ensureSource(page, panel, manual.prepared);
      const select = panel.getByRole("combobox", { name: "분석 리간드 인스턴스", exact: true });
      await select.locator("option").nth(1).waitFor({ state: "attached", timeout: 30000 });
      await select.selectOption({ index: 1 });
      await panel.getByRole("spinbutton", { name: "분석 cutoff", exact: true }).fill("4.5");
      return { imported, source: await panel.getByRole("combobox", { name: "분석 소스", exact: true }).inputValue() };
    }, async value => {
      assert.equal(value.source, manual.prepared);
      assert.equal(await panel.getByRole("combobox", { name: "분석 altloc", exact: true }).count(), 0, "prepared source shows a preparation policy");
      return value;
    });
    const plan = await rec_.step("IP-plan", cases, "Click 계획 만들기 (inspect_ligand from prepared, 4.5 Å)", () =>
      createPlan(page, panel, run), async value => {
      assertPlanPreview(value, "inspect_ligand"); assert.equal(value.executable, true);
      assert.equal(value.plan.inputs.cutoff_A, 4.5);
      assert.deepEqual(value.plan.steps.map(item => item.operation), ["compute_interactions", "compute_interface_sasa",
        "inspection_report", "method_report"]);
      return observePlanPreview(panel, value); });
    const created = await rec_.step("IP-execution", cases, "Click 실행 만들기", () => createExecution(page, panel, run, plan),
      async value => ({ executionId: value.execution_id }));
    const id = created.execution_id;
    panel.__execId = id;
    await rec_.step("IP-approve", cases, "Click 계획 승인", () => clickControl(page, panel, run, id, "계획 승인"),
      async value => { assert.equal(value.status, 200); assert.equal(value.body.execution.status, "ready");
        return { outcome: value.body.request.outcome }; });
    await rec_.part("quick-clicks", ["S-race-clicks"], () => rec_.step("IP-quick-double-click", ["S-race-clicks"],
      "Two quick clicks (dblclick input) on 다음 단계 실행: one step must start, never two", async () => {
        const posts = [];
        const listener = request => { if (request.method() === "POST" && new URL(request.url()).pathname.endsWith(`/${id}/advance`))
          posts.push(request.postDataJSON()); };
        page.on("request", listener);
        const responses = [];
        const responder = response => { if (response.request().method() === "POST" && new URL(response.url()).pathname.endsWith(`/${id}/advance`))
          responses.push(response); };
        page.on("response", responder);
        const button = controlButton(panel, "다음 단계 실행");
        await waitEnabled(page, button, "다음 단계 실행");
        await button.dblclick();
        await waitFor(page, async () => responses.length >= posts.length && posts.length > 0 ? true : null, "advance responses", 180000);
        await page.waitForTimeout(1500);
        page.off("request", listener); page.off("response", responder);
        const bodies = [];
        for (const response of responses) bodies.push({ status: response.status(), body: await response.json().catch(() => null) });
        return { posts, bodies };
      }, async value => {
        const rec = await execRecord(page, run, id);
        const s01 = rec.steps.find(item => item.step_id === "s01");
        assert.equal(s01.status, "completed", "the first step did not complete");
        assert.equal(s01.child_call_ids.length, 1, `quick clicks started ${s01.child_call_ids.length} calls`);
        assert.ok(s01.attempts <= 1, `quick clicks made ${s01.attempts} physical attempts`);
        assert.equal(rec.steps.find(item => item.step_id === "s02").status, "pending", "quick clicks advanced two steps");
        const ids = new Set(value.posts.map(item => item.request_id));
        const advanced = value.bodies.filter(item => item.status === 200 && item.body?.request?.outcome === "advanced" && !item.body.replayed);
        assert.equal(advanced.length, 1, `expected one fresh advanced outcome: ${JSON.stringify(value.bodies.map(item => [item.status, item.body?.request?.outcome, item.body?.replayed, item.body?.error]))}`);
        return { advancePosts: value.posts.length, distinctRequestIds: ids.size,
          responses: value.bodies.map(item => ({ http: item.status, outcome: item.body?.request?.outcome ?? item.body?.error,
            replayed: item.body?.replayed ?? null })), s01Calls: s01.child_call_ids, s01Attempts: s01.attempts };
      }));
    await drive(rec_, page, panel, run, id, { cases, prefix: "IP-D" });
    const rec = await rec_.step("IP-complete", cases, "Observe the completed execution", () => execRecord(page, run, id),
      async value => assertCompleted(value, plan));
    const recFull = await execRecord(page, run, id);
    await openContacts(rec_, page, panel, run, recFull, "s01", manual.prepared, cases);
    await openSasa(rec_, page, panel, run, recFull, "s02", manual.prepared, cases);
    await verifyReports(rec_, page, panel, run, plan, "s03", cases);
    await verifyReports(rec_, page, panel, run, plan, "s04", cases);
    await verifySummary(rec_, page, panel, run, id, cases);
    await reopenFromHistory(rec_, page, panel, run, id, "complete", cases);
    evidence.handles.inspectPrepared = { plan: plan.handle, execution: id, summary: recFull.summary_handle, attempts: rec.physicalAttempts };
  });

  // ---- find_cavities on the displayed prepared structure: chains missing, stop at scientific approval, main path
  await rec_.part("cavities", ["W-cavities-main", "S-prereq-chains", "S-stop-scientific-approval"], async () => {
    await backToLatest(page);
    await waitForViewer(page, value => value.sourceHandle === manual.prepared, 60000);
    panel.__prefix = "FC";
    await rec_.step("FC01-no-chains", ["S-prereq-chains"], "Select find_cavities with the pocket panel's default chains " +
      "(nothing explicit); click 계획 만들기", async () => {
      await chooseGoal(page, panel, "find_cavities");
      await panel.locator("[data-analysis-missing]").first().waitFor({ timeout: 15000 });
      return createPlan(page, panel, run);
    }, async value => {
      assert.equal(value.executable, false);
      assert.deepEqual(value.plan.unmet_prerequisites.map(item => item.code), ["chains_required"]);
      for (const box of await panel.getByRole("checkbox", { name: /^분석 체인 / }).all()) assert.equal(await box.isChecked(), false);
      return { ...await observePlanPreview(panel, value), missing: await panel.locator("[data-analysis-missing]").first().innerText() };
    });
    const pocketChains = await readApi(page, `/runs/${run}/pockets/preflight?structure=${enc(manual.prepared)}`);
    const all = pocketChains.selected_chains;
    assert.ok(all.length >= 1);
    const subset = all.length > 1 ? all.slice(0, 1) : all;
    await rec_.part("stop-scientific", ["S-stop-scientific-approval"], async () => {
      const cases = ["S-stop-scientific-approval"];
      await rec_.step("FC02-tick-subset", cases, `Tick pocket panel chains ${subset.join(",")} and 화면 선택 다시 가져오기`, async () => {
        const ticked = await tickPocketChains(page, "main", run, manual.prepared, subset);
        await chooseGoal(page, panel, "find_cavities");
        return ticked;
      }, async value => {
        for (const chain of value.available) assert.equal(await panel.getByRole("checkbox", { name: `분석 체인 ${chain}`, exact: true }).isChecked(),
          subset.includes(chain));
        return value;
      });
      const plan = await rec_.step("FC03-plan-subset", cases, "Click 계획 만들기 (find_cavities, chain subset)", () =>
        createPlan(page, panel, run), async value => { assert.equal(value.executable, true);
        assert.deepEqual(value.plan.inputs.chains, subset); return observePlanPreview(panel, value); });
      const created = await rec_.step("FC04-exec", cases, "Click 실행 만들기", () => createExecution(page, panel, run, plan),
        async value => ({ executionId: value.execution_id }));
      panel.__execId = created.execution_id;
      const budgetBefore = await readApi(page, `/runs/${run}/budget`);
      const held = await drive(rec_, page, panel, run, created.execution_id, { cases, prefix: "FC-S",
        until: rec => rec.status === "awaiting_scientific_approval" });
      await rec_.step("FC05-awaiting-scientific", cases, "Observe 계산 승인 대기 and the separate plan approval", async () => held.rec,
        async value => {
          assert.equal(value.status, "awaiting_scientific_approval");
          await panel.locator('[data-analysis-scientific-approval="pending"]').waitFor({ timeout: 15000 });
          assert.equal(await panel.locator("[data-analysis-plan-approval]").getAttribute("data-analysis-plan-approval"), "approved");
          assert.equal(await controlButton(panel, "계산 승인").isEnabled(), true);
          return { status: value.status, scientific: value.scientific_approval };
        });
      await rec_.step("FC06-stop", cases, "Click 중지 while the job waits for scientific approval", () =>
        clickControl(page, panel, run, created.execution_id, "중지"), async value => {
        assert.equal(value.status, 200);
        const rec = await execRecord(page, run, created.execution_id);
        assert.equal(rec.status, "cancelled");
        const job = rec.steps[0].job_id ? await readApi(page, `/runs/${run}/jobs/${rec.steps[0].job_id}`) : null;
        if (job) {
          const settled = await waitFor(page, async () => { const value2 = await readApi(page, `/runs/${run}/jobs/${job.job_id}`);
            return ["cancelled", "failed", "interrupted", "done"].includes(value2.status) ? value2 : null; }, "job terminal", 60000);
          assert.equal(settled.status, "cancelled");
          assert.equal(settled.attempt_ordinal, 0, "a job waiting for approval started an attempt");
        }
        const budgetAfter = await readApi(page, `/runs/${run}/budget`);
        assert.deepEqual(budgetAfter.expensive_calls, budgetBefore.expensive_calls, "stopping before approval was charged");
        await panel.locator("[data-analysis-stop]").waitFor({ timeout: 15000 });
        return { status: rec.status, job: job?.job_id ?? null, stepStatus: rec.steps[0].status,
          expensive: budgetAfter.expensive_calls };
      });
    });
    const cases = ["W-cavities-main"];
    await rec_.step("FC10-tick-all", cases, `Tick pocket panel chains ${all.join(",")}; 화면 선택 다시 가져오기`, async () => {
      const ticked = await tickPocketChains(page, "main", run, manual.prepared, all);
      await chooseGoal(page, panel, "find_cavities");
      return ticked;
    }, async value => {
      for (const chain of all) assert.equal(await panel.getByRole("checkbox", { name: `분석 체인 ${chain}`, exact: true }).isChecked(), true);
      return value;
    });
    const done = await runToComplete(rec_, page, panel, run, "find_cavities", "FC", cases);
    const rec = await execRecord(page, run, done.id);
    assert.deepEqual(done.plan.plan.inputs.chains, [...all].sort());
    await openPocket(rec_, page, panel, run, rec, "s01", "main", cases);
    await verifyReports(rec_, page, panel, run, done.plan, "s02", cases);
    await verifySummary(rec_, page, panel, run, done.id, cases);
    await reopenFromHistory(rec_, page, panel, run, done.id, "complete", cases);
    evidence.handles.cavitiesMain = { plan: done.plan.handle, execution: done.id };
  });
  evidence.providerCalls.push(await providerCalls(page, run));
}

/** M10 inputs: two real atom picks → measure_atoms; explicit CA pairs → compare_structures (and the no-pairs prerequisite). */
async function modeM10(session, input, rec_, evidence) {
  const { page } = session;
  const panel = analysisPanel(page, "main");
  const oracle = fixtureOracle(M10_FIXTURES);
  const run = await rec_.step("T01-new-run", [], "Click 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.run = run;
  const origin = new URL(page.url()).origin;
  const cmp = page.locator('[aria-label="원자 거리와 두 구조 비교"]');
  await rec_.part("measure", ["W-measure"], async () => {
    const cases = ["W-measure"];
    const loaded = await rec_.step("T02-distance-upload", cases, `Choose ${oracle.manifest.distance_fixture}, 구조 불러오기`, () =>
      uploadLoad(page, path.join(M10_FIXTURES, oracle.manifest.distance_fixture)), async value => value);
    evidence.inputs.push(loaded.file);
    const atoms = await catalog(origin, run, loaded.handle);
    const first = atoms.rows.find(row => row.ref.residue.seq_auth === 10 && row.ref.atom_name === "N");
    const second = atoms.rows.find(row => row.ref.residue.seq_auth === 11 && row.ref.atom_name === "O");
    await rec_.step("T03-measure-mode", cases, "Click ball-and-stick and 원자 거리 측정", async () => {
      await page.getByRole("group", { name: "표현 방식" }).getByRole("button", { name: "ball-and-stick", exact: true }).click();
      await cmp.getByRole("button", { name: "원자 거리 측정", exact: true }).click();
      return waitForViewer(page, value => value.measureMode === true && value.sourceHandle === loaded.handle);
    }, async value => ({ measureMode: value.measureMode }));
    const measured = await rec_.step("T04-two-atom-picks", cases, "Click two real atoms in Mol* (N then O) for the screen measurement",
      async () => {
        await clickCatalogAtom(page, first);
        await cmp.getByText(/첫 원자:/).waitFor({ timeout: 10000 });
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${run}/commands`, { timeout: 30000 });
        await clickCatalogAtom(page, second);
        const body = await (await posted).json();
        assert.equal(body.ok, true, JSON.stringify(body).slice(0, 300));
        await cmp.getByText(/원자 거리 [0-9.]+ Å/).waitFor({ timeout: 30000 });
        return body.handle.handle;
      }, async handle => ({ screenMeasurement: handle }));
    await rec_.step("T05-goal", cases, "Select measure_atoms: the two atoms are imported read-only", async () => {
      await chooseGoal(page, panel, "measure_atoms");
      return JSON.parse(await panel.locator('[data-analysis-readonly="atoms"] pre').innerText());
    }, async value => {
      assert.equal(value.first.site_index, first.ref.site_index);
      assert.equal(value.second.site_index, second.ref.site_index);
      assert.equal(await panel.getByRole("combobox", { name: "분석 소스", exact: true }).count(), 0, "atom source was editable");
      return value;
    });
    const done = await runToComplete(rec_, page, panel, run, "measure_atoms", "MA", cases);
    const rec = await execRecord(page, run, done.id);
    const handle = rec.steps[0].outputs.atom_distance;
    await rec_.step("MA-open-s01", cases, "Click 결과 열기 s01 (measurement overlay)", async () => {
      await cmp.getByRole("button", { name: "원자 거리 측정 끝내기", exact: true }).click().catch(() => undefined);
      await openButton(panel, "s01").click();
      const detail = await measurement(origin, run, handle);
      await cmp.getByText(`원자 거리 ${detail.result.distance_A.toFixed(3)} Å`, { exact: false }).waitFor({ timeout: 30000 });
      const viewer = await waitForViewer(page, value => value.sourceHandle === loaded.handle && value.measureMode === true, 45000);
      return { detail, viewer };
    }, async value => {
      assert.equal(value.detail.result.schema, "atom_distance@1");
      assert.equal(value.detail.result.first.site_index, first.ref.site_index);
      assert.equal(value.detail.result.second.site_index, second.ref.site_index);
      assert.ok(Math.abs(value.detail.result.distance_A - 5) <= 1e-9, "independent 3-4-5 fixture distance");
      assert.equal(await cmp.locator("select").first().inputValue(), handle, "saved measurement selector did not select the result");
      return { handle, distance_A: value.detail.result.distance_A, viewerSource: value.viewer.sourceHandle,
        measureMode: value.viewer.measureMode };
    });
    await verifyReports(rec_, page, panel, run, done.plan, "s02", cases);
    await verifySummary(rec_, page, panel, run, done.id, cases);
    await reopenFromHistory(rec_, page, panel, run, done.id, "complete", cases);
    evidence.handles.measure = { plan: done.plan.handle, execution: done.id, result: handle };
    await cmp.getByRole("button", { name: "원자 거리 측정 끝내기", exact: true }).click().catch(() => undefined);
  });
  await rec_.part("compare", ["W-compare", "S-prereq-ca"], async () => {
    const cases = ["W-compare"];
    const ref = await rec_.step("T10-reference-upload", cases, `Choose ${oracle.manifest.reference}`, () =>
      uploadLoad(page, path.join(M10_FIXTURES, oracle.manifest.reference)), async value => value);
    const mov = await rec_.step("T11-moving-upload", cases, `Choose ${oracle.manifest.moving}`, () =>
      uploadLoad(page, path.join(M10_FIXTURES, oracle.manifest.moving)), async value => value);
    evidence.inputs.push(ref.file, mov.file);
    await rec_.step("T12-select-sources", ["S-prereq-ca"], "Select 기준 구조 / 이동 구조 (no CA pairs yet)", async () => {
      await cmp.getByRole("combobox", { name: "기준 구조" }).selectOption(ref.handle);
      await cmp.getByRole("combobox", { name: "이동 구조" }).selectOption(mov.handle);
      await cmp.getByRole("combobox", { name: "기준 CA site" }).locator("option").nth(1).waitFor({ state: "attached", timeout: 30000 });
      return true;
    }, async () => ({ reference: ref.handle, moving: mov.handle }));
    await rec_.step("T13-no-pairs-plan", ["S-prereq-ca"], "Select compare_structures with no CA pairs; click 계획 만들기", async () => {
      await chooseGoal(page, panel, "compare_structures");
      await panel.locator("[data-analysis-missing]").first().waitFor({ timeout: 15000 });
      return createPlan(page, panel, run);
    }, async value => {
      assert.equal(value.executable, false);
      assert.deepEqual(value.plan.unmet_prerequisites.map(item => item.code), ["ca_pairs_required"]);
      assert.equal(await panel.getByRole("button", { name: "실행 만들기", exact: true }).isDisabled(), true);
      return observePlanPreview(panel, value);
    });
    const refAtoms = await catalog(origin, run, ref.handle);
    const movAtoms = await catalog(origin, run, mov.handle);
    const pick = (atoms, identity) => atoms.rows.find(row => row.ref.residue.model_number === 1 &&
      row.ref.residue.chain_auth === identity.chain_auth && row.ref.residue.seq_auth === identity.seq_auth &&
      row.ref.residue.icode === identity.icode && row.ref.atom_name === identity.atom_name && row.ref.altloc === identity.altloc);
    await rec_.step("T14-add-pairs", cases, `Add ${oracle.manifest.ca_pairs.length} explicit CA pairs with 대응 추가`, async () => {
      for (const identity of oracle.manifest.ca_pairs) {
        await cmp.getByRole("combobox", { name: "기준 CA site" }).selectOption(String(pick(refAtoms, identity).ref.site_index));
        await cmp.getByRole("combobox", { name: "이동 CA site" }).selectOption(String(pick(movAtoms, identity).ref.site_index));
        await cmp.getByRole("button", { name: "대응 추가", exact: true }).click();
      }
      return cmp.getByRole("region", { name: "명시한 CA 대응", exact: true }).locator("tbody tr").count();
    }, async count => { assert.equal(count, oracle.manifest.ca_pairs.length); return { pairs: count }; });
    await rec_.step("T15-reimport", cases, "화면 선택 다시 가져오기: CA pairs imported read-only", async () => {
      await chooseGoal(page, panel, "compare_structures");
      return panel.locator('[data-analysis-readonly="comparison"] pre').textContent();
    }, async text => { const pairs = JSON.parse(text); assert.equal(pairs.length, oracle.manifest.ca_pairs.length);
      return { pairs: pairs.length }; });
    const done = await runToComplete(rec_, page, panel, run, "compare_structures", "CS", cases);
    const rec = await execRecord(page, run, done.id);
    const handle = rec.steps[0].outputs.rigid_alignment;
    await rec_.step("CS-open-s01", cases, "Click 결과 열기 s01 (alignment overlay)", async () => {
      await openButton(panel, "s01").click();
      const detail = await measurement(origin, run, handle);
      await cmp.getByText(`정렬 RMSD ${detail.result.rmsd_A.toFixed(4)} Å`, { exact: false }).waitFor({ timeout: 30000 });
      const viewer = await waitForViewer(page, value => value.layers?.length === 2 &&
        value.layers[0].sourceHandle === ref.handle && value.layers[1].sourceHandle === mov.handle, 45000);
      return { detail, viewer };
    }, async value => {
      assert.equal(value.detail.result.schema, "rigid_alignment@1");
      assert.equal(value.detail.result.pair_count, oracle.manifest.ca_pairs.length);
      assert.ok(Math.abs(value.detail.result.unaligned_rmsd_A - oracle.manifest.unaligned_rmsd_A) <= 1e-9);
      return { handle, rmsd_A: value.detail.result.rmsd_A, layers: value.viewer.layers.map(item => item.sourceHandle) };
    });
    await verifyReports(rec_, page, panel, run, done.plan, "s02", cases);
    await verifySummary(rec_, page, panel, run, done.id, cases);
    await reopenFromHistory(rec_, page, panel, run, done.id, "complete", cases);
    evidence.handles.compare = { plan: done.plan.handle, execution: done.id, result: handle };
  });
  evidence.providerCalls.push(await providerCalls(page, run));
}

/** Races: a second offscreen window on the same execution, and a held Advance response across a run switch. */
async function modeRace(session, input, rec_, evidence) {
  const { page } = session;
  const panel = analysisPanel(page, "main");
  const run = input.run;
  evidence.run = run;
  await waitForBoot(page);
  const prepared = (await runEvents(page, run)).filter(event => event.type === "object_created" && event.kind === "prepared_structure").at(-1)?.handle;
  assert.ok(prepared, "race run has no prepared structure");
  await backToLatest(page);
  await waitForViewer(page, value => value.sourceHandle === prepared && value.catalogReady === true, 90000);
  panel.__prefix = "RC";
  const plan = await rec_.step("RC01-plan", ["S-race-window", "S-race-run-switch"], "Select inspect_ligand (prepared), ligand, cutoff 5.0; 계획 만들기",
    async () => {
      await chooseGoal(page, panel, "inspect_ligand");
      await ensureSource(page, panel, prepared);
      const select = panel.getByRole("combobox", { name: "분석 리간드 인스턴스", exact: true });
      await select.locator("option").nth(1).waitFor({ state: "attached", timeout: 30000 });
      await select.selectOption({ index: 1 });
      await panel.getByRole("spinbutton", { name: "분석 cutoff", exact: true }).fill("5");
      return createPlan(page, panel, run);
    }, async value => { assert.equal(value.executable, true); return observePlanPreview(panel, value); });
  const created = await rec_.step("RC02-exec-approve", ["S-race-window", "S-race-run-switch"], "Click 실행 만들기 and 계획 승인", async () => {
    const exec = await createExecution(page, panel, run, plan);
    await clickControl(page, panel, run, exec.execution_id, "계획 승인");
    return exec;
  }, async value => ({ executionId: value.execution_id, status: (await execRecord(page, run, value.execution_id)).status }));
  const id = created.execution_id;
  await rec_.part("second-window", ["S-race-window"], async () => {
    const other = await launchOffscreen({ url: new URL(`/?run=${run}`, input.origin).toString(),
      artifacts: path.join(session.artifacts, "window-b"), interactive: false });
    evidence.fixtureLabels.push("second real offscreen Electron window (own browser profile) on the same run and execution");
    try {
      const panelB = analysisPanel(other.page, "main");
      await rec_.step("RC03-window-b-reopen", ["S-race-window"], "Window B: reopen the same execution from history", async () => {
        await waitForBoot(other.page);
        await openHistory(panelB);
        await panelB.getByRole("button", { name: `실행 다시 열기 ${id}`, exact: true }).click();
        await panelB.locator(`[aria-label="분석 실행"][data-analysis-execution-id="${id}"][data-analysis-status="ready"]`).waitFor({ timeout: 30000 });
        return true;
      }, async () => ({ windowB: "ready", proof: await offscreenProof(other.app, other.page) }), { session: other });
      const race = await rec_.step("RC04-concurrent-advance", ["S-race-window"],
        "Click 다음 단계 실행 in window A and window B at the same time", async () => {
          const results = await Promise.all([clickControl(page, panel, run, id, "다음 단계 실행"),
            clickControl(other.page, panelB, run, id, "다음 단계 실행")]);
          await page.waitForTimeout(1500);
          return results;
        }, async results => {
          const rec = await execRecord(page, run, id);
          const s01 = rec.steps[0];
          assert.equal(s01.status, "completed");
          assert.equal(s01.child_call_ids.length, 1, "two windows started two calls");
          assert.ok(s01.attempts <= 1);
          assert.equal(rec.steps[1].status, "pending", "two windows advanced two steps");
          const fresh = results.filter(item => item.status === 200 && item.body?.request?.outcome === "advanced");
          assert.equal(fresh.length, 1, `outcomes: ${JSON.stringify(results.map(item => [item.status, item.body?.request?.outcome ?? item.body?.error]))}`);
          const loser = results.find(item => item !== fresh[0]);
          assert.ok([409, 200].includes(loser.status));
          if (loser.status === 409) assert.ok(["busy", "stale_revision"].includes(loser.body?.error), JSON.stringify(loser.body));
          const shown = await panelB.locator("[data-analysis-error], [data-analysis-busy], [data-analysis-notice]").allInnerTexts();
          return { outcomes: results.map(item => ({ http: item.status, outcome: item.body?.request?.outcome ?? item.body?.error })),
            s01Calls: s01.child_call_ids, s01Attempts: s01.attempts, windowBMessages: shown };
        });
      evidence.race = race;
    } finally { await other.close(); }
  });
  await rec_.part("run-switch", ["S-race-run-switch"], async () => {
    const pattern = `**/api/runs/${run}/analysis/executions/${id}/advance`;
    let release, started;
    const gate = new Promise(resolve => { release = resolve; });
    const startedGate = new Promise(resolve => { started = resolve; });
    const delivered = [];
    const handler = async route => {
      let response;
      try { response = await route.fetch({ timeout: 300000 }); } catch (error) { started({ error: String(error) }); return; }
      started({ status: response.status() });
      await gate;
      try { await route.fulfill({ response }); delivered.push("fulfilled"); }
      catch (error) { delivered.push(`browser_cancelled: ${String(error).slice(0, 160)}`); }
    };
    evidence.fixtureLabels.push("renderer-route fixture: real Advance POST committed by the backend, response held and released unchanged after a run switch");
    await page.route(pattern, handler);
    try {
      await rec_.step("RC05-held-advance-run-switch", ["S-race-run-switch"],
        `Click 다음 단계 실행 (response held), switch run to ${input.otherRun}, release the late response`, async () => {
          await backToLatest(page);
          const downloadsBefore = (await session.app.evaluate(({ app }) => app.__offscreenQa.status().downloads.length));
          const button = controlButton(panel, "다음 단계 실행");
          await waitEnabled(page, button, "다음 단계 실행");
          await button.click();
          const committed = await startedGate;
          await page.locator("#run-choice").selectOption(input.otherRun);
          await page.waitForFunction(value => new URL(location.href).searchParams.get("run") === value, input.otherRun, { timeout: 30000 });
          release();
          await waitFor(page, async () => delivered.length ? true : null, "late response delivered", 30000);
          await page.waitForTimeout(2000);
          const otherPanel = analysisPanel(page, "main");
          return { committed, delivered: [...delivered], downloadsBefore,
            downloadsAfter: await session.app.evaluate(({ app }) => app.__offscreenQa.status().downloads.length),
            otherExecutionShown: await otherPanel.locator(`[data-analysis-execution-id="${id}"]`).count(),
            otherNotices: await otherPanel.locator("[data-analysis-notice], [data-analysis-error]").allInnerTexts() };
        }, async value => {
          assert.equal(value.committed.status, 200);
          assert.equal(new URL(page.url()).searchParams.get("run"), input.otherRun);
          assert.equal(value.otherExecutionShown, 0, "the late old-run execution appeared in the other run's panel");
          assert.ok(!value.otherNotices.some(text => text.includes("다음 단계 실행")), "late Advance notice shown in the other run");
          assert.equal(value.downloadsAfter, value.downloadsBefore, "a late response started a download");
          return value;
        });
    } finally { release(); await page.unroute(pattern, handler); }
    await rec_.step("RC06-switch-back", ["S-race-run-switch"], "Switch back and reopen the execution: the held Advance was recorded once",
      async () => {
        await page.locator("#run-choice").selectOption(run);
        await page.waitForFunction(value => new URL(location.href).searchParams.get("run") === value, run, { timeout: 30000 });
        await openHistory(panel);
        await panel.getByRole("button", { name: `실행 다시 열기 ${id}`, exact: true }).click();
        await panel.locator(`[aria-label="분석 실행"][data-analysis-execution-id="${id}"]`).waitFor({ timeout: 30000 });
        return execRecord(page, run, id);
      }, async rec => {
        assert.equal(rec.steps[1].status, "completed", "the held Advance did not record s02");
        assert.equal(rec.steps[1].child_call_ids.length, 1);
        assert.equal(rec.steps[2].status, "pending");
        return { s02: rec.steps[1].status, calls: rec.steps[1].child_call_ids, status: rec.status };
      });
  });
  evidence.handles.race = { plan: plan.handle, execution: id };
  evidence.providerCalls.push(await providerCalls(page, run));
}

/** 1UBQ minimize_protein: labeled worker fault → retry, results, shared job, and Stop during a running job. */
async function modeMinimize(session, input, rec_, evidence) {
  const { page } = session;
  const panel = analysisPanel(page, "main");
  const run = await rec_.step("O01-new-run", [], "Click 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.run = run;
  const loaded = await rec_.step("O02-upload-load", [], "Choose public_1ubq.cif, 구조 불러오기", () =>
    uploadLoad(page, path.join(FIXTURES, "public_1ubq.cif")), async value => value);
  evidence.inputs.push(loaded.file);
  const prepA = await rec_.step("O03-prepare", [], "Click 전처리 (물 제거)", () => prepareManual(page), async value => value);
  const cases = ["W-minimize"];
  panel.__prefix = "MN";
  const planRecord = (await rec_.step("MN01-goal-plan", cases, "Select minimize_protein; the plan stays disabled until both OpenMM " +
    "acknowledgements are checked; click 계획 만들기", async () => {
    await chooseGoal(page, panel, "minimize_protein");
    const button = panel.getByRole("button", { name: "계획 만들기", exact: true });
    const disabledFirst = await button.isDisabled();
    const reason = await panel.locator("[data-analysis-plan-reason]").innerText().catch(() => "");
    await panel.getByRole("checkbox", { name: "분석 protein_only 확인", exact: true }).check();
    await panel.getByRole("checkbox", { name: "분석 rebuild_pH7 확인", exact: true }).check();
    return { disabledFirst, reason, plan: await createPlan(page, panel, run) };
  }, async value => {
    assert.equal(value.disabledFirst, true, "plan was enabled without the OpenMM acknowledgements");
    assert.equal(value.plan.executable, true);
    assert.equal(value.plan.plan.inputs.source, prepA.prepared);
    return { reasonBeforeAcks: value.reason, ...await observePlanPreview(panel, value.plan) };
  })).plan;
  evidence.handles.minPlan = planRecord.handle;
  const created = await rec_.step("MN02-exec", cases, "Click 실행 만들기", () => createExecution(page, panel, run, planRecord),
    async value => ({ executionId: value.execution_id }));
  const id = created.execution_id;
  panel.__execId = id;
  // Approve, 계산 승인 (first expensive job in this run), start; stop at a running job.
  // Approve, 계산 승인 (first expensive job in this run); stop before the job-starting Advance.
  const ready = await drive(rec_, page, panel, run, id, { cases, prefix: "MN-D",
    until: rec => rec.status === "ready" && !!rec.steps[0].job_id && rec.steps[0].status !== "completed" });
  assert.equal(ready.rec.status, "ready", `minimize did not reach the approved job start: ${ready.rec.status}`);
  await rec_.part("retry", ["S-retry", "S-error"], async () => {
    const jobId = ready.rec.steps[0].job_id;
    const killed = await rec_.step("MN03-worker-fault", ["S-retry"], "Click 다음 단계 실행 (job start); while the real job runs, " +
      "labeled fault fixture: SIGKILL this QA run's OpenMM worker process (cwd inside the QA runs root)", async () => {
      const inflight = await clickAdvanceInFlight(page, panel, run, id);
      const runningRec = await waitJobRunning(page, run, id);
      // Observation only: whether the panel re-reads the record while its own Advance request is still pending.
      const panelWaitingJob = await waitFor(page, async () => panel.locator('[aria-label="분석 실행"][data-analysis-status="waiting_job"]')
        .count().then(count => count ? true : null), "panel shows 작업 대기", 5000).catch(() => false);
      const found = await waitFor(page, async () => { const list = workerPids(input.runsRoot, "openmm_worker.py"); return list.length ? list : null; },
        "running OpenMM worker process", 60000);
      for (const item of found) process.kill(item.pid, "SIGKILL");
      const job = await waitFor(page, async () => { const value = await readApi(page, `/runs/${run}/jobs/${jobId}`);
        return ["failed", "interrupted", "done"].includes(value.status) ? value : null; }, "job terminal after fault", 120000);
      return { killed: found, job, advance: await inflight.response, runningStatus: runningRec.status, panelWaitingJob };
    }, async value => {
      assert.ok(["failed", "interrupted"].includes(value.job.status), `job ended ${value.job.status} (fault landed too late)`);
      return { killedPids: value.killed.map(item => item.pid), jobStatus: value.job.status, failure: value.job.failure,
        advanceHttp: value.advance.status, advanceOutcome: value.advance.body?.request?.outcome ?? value.advance.error ?? null,
        statusWhileRunning: value.runningStatus, panelShowedWaitingJobDuringAdvance: value.panelWaitingJob };
    });
    evidence.fixtureLabels.push("labeled OS fault fixture: SIGKILL of this QA run's own openmm_worker.py (scoped by cwd to the QA runs root); no result is produced by the fixture");
    evidence.faults = { killed };
    await rec_.step("MN04-failed-retryable", ["S-retry", "S-error"], "Observe the recorded job failure (click 다음 단계 실행 " +
      "first when the failure is not yet recorded): 재시도 appears", async () => {
        let rec = await execRecord(page, run, id);
        let click = null;
        if (rec.status !== "failed") { click = await clickControl(page, panel, run, id, "다음 단계 실행"); rec = await execRecord(page, run, id); }
        return { rec, click };
      }, async ({ rec, click }) => {
        assert.equal(rec.status, "failed");
        assert.equal(rec.retryable_step, "s01");
        await panel.locator('[aria-label="분석 실행"][data-analysis-retryable-step="s01"]').waitFor({ timeout: 15000 });
        await panel.locator('li[data-analysis-step="s01"] [data-analysis-step-failure]').waitFor({ timeout: 15000 });
        await waitEnabled(page, controlButton(panel, "재시도"), "재시도", 15000);
        assert.equal(await controlButton(panel, "다음 단계 실행").isDisabled(), true);
        return { status: rec.status, retryable: rec.retryable_step, failure: rec.steps[0].failure, recordingClick: click?.status ?? null,
          uiState: await panel.getAttribute("data-analysis-ui-state"),
          shownFailure: await panel.locator('li[data-analysis-step="s01"] [data-analysis-step-failure]').innerText() };
      });
    await rec_.step("MN05-retry", ["S-retry"], "Click 재시도 (one explicit retry of s01)", () =>
      clickControl(page, panel, run, id, "재시도"), async value => {
      assert.equal(value.status, 200, JSON.stringify(value.body).slice(0, 300));
      const rec = await execRecord(page, run, id);
      assert.ok(["executing", "waiting_job", "ready", "awaiting_scientific_approval"].includes(rec.status), rec.status);
      assert.equal(rec.steps[0].retries_used, 1);
      return { status: rec.status, retriesUsed: rec.steps[0].retries_used, outcome: value.body.request.outcome };
    });
  });
  await drive(rec_, page, panel, run, id, { cases, prefix: "MN-E" });
  const rec = await rec_.step("MN06-complete", cases, "Observe the completed minimize execution", () => execRecord(page, run, id),
    async value => { const done = assertCompleted(value, planRecord);
      assert.equal(value.steps[0].job_ownership, "owned"); return done; });
  const recFull = await execRecord(page, run, id);
  await rec_.step("MN07-open-s01", cases, "Click 결과 열기 s01 then 최소화 단백질 좌표 보기", async () => {
    await openButton(panel, "s01").click();
    await page.getByRole("button", { name: "최소화 단백질 좌표 보기", exact: true }).waitFor({ timeout: 45000 });
    await page.getByRole("button", { name: "최소화 단백질 좌표 보기", exact: true }).click();
    return waitForViewer(page, value => (value.sourceHandle ?? "").includes("/openmm_minimized_structure/") && value.catalogReady === true, 90000);
  }, async viewer => {
    const job = await readApi(page, `/runs/${run}/jobs/${recFull.steps[0].job_id}`);
    const events = await runEvents(page, run);
    const made = events.find(event => event.type === "object_created" && event.handle === viewer.sourceHandle);
    assert.ok(made, "displayed minimized structure is not an object of this run");
    assert.ok(JSON.stringify(job).includes(viewer.sourceHandle) || JSON.stringify(recFull.steps[0].outputs).length > 0);
    return { minimized: viewer.sourceHandle, job: job.job_id, jobStatus: job.status, representation: viewer.representation };
  });
  await verifyReports(rec_, page, panel, run, planRecord, "s02", cases);
  await verifySummary(rec_, page, panel, run, id, cases);
  await rec_.step("MN08-reload-reopen", cases, "Reload the page, then reopen the execution from history", async () => {
    await page.reload({ waitUntil: "domcontentloaded" });
    await waitForBoot(page);
    return true;
  }, async () => ({ reloaded: true }));
  await reopenFromHistory(rec_, page, panel, run, id, "complete", cases);
  evidence.handles.minimize = { plan: planRecord.handle, execution: id, summary: recFull.summary_handle, record: rec };

  await rec_.part("shared", ["S-shared"], async () => {
    const cases2 = ["S-shared"];
    await rec_.step("SH01-new-exec", cases2, "Reopen the same plan from history and click 실행 만들기 (second execution)", async () => {
      await openHistory(panel);
      await panel.getByRole("button", { name: `계획 다시 열기 ${planRecord.ordinal}`, exact: true }).click();
      return createExecution(page, panel, run, planRecord);
    }, async value => { evidence.handles.sharedExecution = value.execution_id; return { executionId: value.execution_id }; });
    const sid = evidence.handles.sharedExecution;
    panel.__execId = sid;
    await drive(rec_, page, panel, run, sid, { cases: cases2, prefix: "SH-D", until: r => r.steps[0].status === "completed" });
    await rec_.step("SH02-shared-notice", cases2, "Observe the shared-job explanation on s01", async () =>
      execRecord(page, run, sid), async value => {
      const s01 = value.steps[0];
      assert.equal(s01.job_ownership, "observed_shared");
      assert.equal(s01.job_id, recFull.steps[0].job_id, "the second execution did not observe the same job");
      const li = panel.locator('li[data-analysis-step="s01"][data-analysis-job-ownership="observed_shared"]');
      await li.waitFor({ timeout: 15000 });
      const text = await li.locator("[data-analysis-shared-job]").innerText();
      assert.match(text, /관찰만/);
      return { jobId: s01.job_id, ownership: s01.job_ownership, attempts: s01.attempts, text };
    });
    await drive(rec_, page, panel, run, sid, { cases: cases2, prefix: "SH-E" });
    await rec_.step("SH03-complete", cases2, "Observe the second execution complete without a second job", async () =>
      execRecord(page, run, sid), async value => {
      assert.equal(value.status, "complete");
      const jobs = (await readApi(page, `/runs/${run}/jobs`)).filter(job => job.protocol_id === "openmm_protein_minimize");
      assert.equal(jobs.length, 1, "the shared execution created a second OpenMM job");
      return { status: value.status, openmmJobs: jobs.length };
    });
  });

  await rec_.part("stop-running", ["S-stop-running", "S-scientific-already"], async () => {
    const cases3 = ["S-stop-running"];
    const prepB = await rec_.step("ST01-prepare-waters", cases3, "Select 물 유지 and click 전처리 (a different prepared source)",
      () => prepareManual(page, { keepWaters: true }), async value => { assert.notEqual(value.prepared, prepA.prepared); return value; });
    const planB = await rec_.step("ST02-plan", cases3, "Select minimize_protein for the new source; check both acknowledgements; 계획 만들기",
      async () => {
        await chooseGoal(page, panel, "minimize_protein");
        await panel.getByRole("checkbox", { name: "분석 protein_only 확인", exact: true }).check();
        await panel.getByRole("checkbox", { name: "분석 rebuild_pH7 확인", exact: true }).check();
        return createPlan(page, panel, run);
      }, async value => { assert.equal(value.plan.inputs.source, prepB.prepared); assert.equal(value.executable, true);
        return observePlanPreview(panel, value); });
    const exec = await rec_.step("ST03-exec", cases3, "Click 실행 만들기", () => createExecution(page, panel, run, planB),
      async value => ({ executionId: value.execution_id }));
    const sid = exec.execution_id;
    panel.__execId = sid;
    const runningB = await drive(rec_, page, panel, run, sid, { cases: cases3, prefix: "ST-D",
      until: r => r.plan_approval.approved && r.status === "ready" && r.steps[0].status === "pending" });
    await rec_.step("ST04-already-approved", ["S-scientific-already"], "Observe 이 run에서 이미 계산 승인됨 (no second approval asked)",
      async () => execRecord(page, run, sid), async value => {
        assert.equal(value.scientific_approval.state, "already_approved_in_run");
        await panel.locator("[data-analysis-already-approved]").waitFor({ timeout: 15000 });
        assert.ok(!runningB.clicks.some(item => item.label === "계산 승인"), "scientific approval was asked again");
        return { state: value.scientific_approval.state, text: await panel.locator("[data-analysis-already-approved]").innerText() };
      });
    await rec_.step("ST05-stop-running", cases3, "Click 다음 단계 실행 (job start), then 중지 while the owned OpenMM job runs", async () => {
      const inflight = await clickAdvanceInFlight(page, panel, run, sid);
      await waitJobRunning(page, run, sid);
      const stop = await clickControl(page, panel, run, sid, "중지");
      return { ...stop, advance: await inflight.response };
    }, async value => {
      assert.equal(value.status, 200, JSON.stringify(value.body).slice(0, 300));
      const recB = await execRecord(page, run, sid);
      assert.equal(recB.status, "cancelled");
      const job = await waitFor(page, async () => { const item = await readApi(page, `/runs/${run}/jobs/${recB.steps[0].job_id}`);
        return ["cancelled", "failed", "interrupted", "done"].includes(item.status) ? item : null; }, "stopped job terminal", 120000);
      assert.equal(job.status, "cancelled", `owned running job ended ${job.status}`);
      await panel.locator("[data-analysis-stop]").waitFor({ timeout: 15000 });
      const later = await execRecord(page, run, sid);
      assert.equal(later.steps[1].status, "pending", "a later step started after Stop");
      return { status: recB.status, job: job.job_id, jobStatus: job.status, stepStatus: later.steps[0].status,
        attempts: later.physical_attempts, stopOutcome: value.body?.request?.outcome, stopFirstAttempt: value.firstAttempt ?? null,
        advanceHttp: value.advance.status, advanceOutcome: value.advance.body?.request?.outcome ?? value.advance.error ?? null };
    });
  });
  evidence.providerCalls.push(await providerCalls(page, run));
}

/** create_new chemical_interactions (+ no-request prerequisite), chemical find_cavities, main-panel placement. */
async function modeChemicalCreate(session, input, rec_, evidence) {
  const { page } = session;
  const run = await rec_.step("H01-new-run", [], "Click 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.run = run;
  await rec_.step("H02-open-workspace", [], "Click 화학 상호작용 작업 열기", () => openChemicalWorkspace(page),
    async value => { assert.equal(value, run); return { run: value }; });
  const panel = analysisPanel(page, "chemical");
  panel.__prefix = "CH";
  await rec_.part("no-request", ["S-prereq-chem"], () => rec_.step("H03-no-request", ["S-prereq-chem"],
    "Select chemical_interactions before any ready preview; click 계획 만들기", async () => {
      await chooseGoal(page, panel, "chemical_interactions");
      await panel.locator('[data-analysis-readonly-missing="chemical_request"]').waitFor({ timeout: 15000 });
      return createPlan(page, panel, run);
    }, async value => {
      assert.equal(value.executable, false);
      assert.deepEqual(value.plan.unmet_prerequisites.map(item => item.code), ["chemical_request_required"]);
      assert.equal(await panel.getByRole("button", { name: "실행 만들기", exact: true }).isDisabled(), true);
      const categories = await panel.locator("[data-analysis-categories]").innerText();
      for (const item of ["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"]) assert.ok(categories.includes(item));
      return { ...await observePlanPreview(panel, value), categories };
    }));
  const cases = ["W-chem-create"];
  const form = await rec_.step("H04-create-form", cases, "Choose public receptor + SDF, acknowledgements, preview until ready", () =>
    chemicalCreateForm(page, run, path.join(CHEM, "prolif-vina-rec.pdb"), path.join(CHEM, "prolif-vina-output.sdf")),
  async value => value);
  evidence.inputs.push(form.files.receptor, form.files.sdf);
  await rec_.step("H05-import-request", cases, "화면 선택 다시 가져오기: the ready M11 request is imported read-only", async () => {
    await chooseGoal(page, panel, "chemical_interactions");

    return panel.locator('[data-analysis-readonly="chemical_request"] pre').textContent();
  }, async text => { const request = JSON.parse(text); assert.equal(request.mode, "create_new"); return { mode: request.mode }; });
  const done = await runToComplete(rec_, page, panel, run, "chemical_interactions", "CH", cases);
  const rec = await execRecord(page, run, done.id);
  assert.deepEqual(rec.steps.map(item => item.job_ownership ?? null), ["owned", "owned", null], "chemical job ownership");
  await openChemicalResults(rec_, page, panel, rec, "CH", cases);
  await verifyReports(rec_, page, panel, run, done.plan, "s03", cases);
  await verifySummary(rec_, page, panel, run, done.id, cases);
  await reopenFromHistory(rec_, page, panel, run, done.id, "complete", cases);
  evidence.handles.chemicalCreate = { plan: done.plan.handle, execution: done.id,
    result: rec.steps[1].outputs.chemical_interaction_set };

  await rec_.part("chemical-cavities", ["W-cavities-chemical", "S-scientific-already"], async () => {
    const cases2 = ["W-cavities-chemical"];
    const showResult = async () => {
      await openButton(panel, "s02").click();
      return (await waitFor(page, async () => { const value = await chemicalSnapshot(page); return value?.sourceHandle ? value : null; },
        "chemical structure displayed", 30000)).sourceHandle;
    };
    let source = await showResult();
    const pocketSelect = page.locator('section[data-pocket-panel="chemical"]').getByRole("combobox", { name: "포켓 검출 소스", exact: true });
    const listed = await pocketSelect.locator("option").evaluateAll(items => items.map(item => item.value));
    if (!listed.includes(source)) {
      PRODUCT_ISSUES.push({ issue: "sources_stale_after_workflow_objects", source, listed,
        note: "the chemical structure made by the workflow is displayed but missing from the pocket/analysis source lists " +
          "until the page is reloaded; recovered by reload → 화학 상호작용 작업 열기 → 실행 다시 열기 → 결과 열기 s02" });
      await page.reload({ waitUntil: "domcontentloaded" });
      await waitForBoot(page);
      await openChemicalWorkspace(page);
      await openHistory(panel);
      await panel.getByRole("button", { name: `실행 다시 열기 ${done.id}`, exact: true }).click();
      await panel.locator(`[aria-label="분석 실행"][data-analysis-execution-id="${done.id}"][data-analysis-status="complete"]`).waitFor({ timeout: 30000 });
      source = await showResult();
    }
    const chains = (await readApi(page, `/runs/${run}/pockets/preflight?structure=${enc(source)}`)).selected_chains;
    await rec_.step("HC01-tick", cases2, `Tick chemical pocket panel chains ${chains.join(",")}; select find_cavities`, async () => {
      const ticked = await tickPocketChains(page, "chemical", run, source, chains);
      await chooseGoal(page, panel, "find_cavities");
      return ticked;
    }, async value => {
      assert.equal(await panel.getByRole("combobox", { name: "분석 소스", exact: true }).inputValue(), source);
      for (const chain of chains) assert.equal(await panel.getByRole("checkbox", { name: `분석 체인 ${chain}`, exact: true }).isChecked(), true);
      return { ...value, source };
    });
    const run2 = await runToComplete(rec_, page, panel, run, "find_cavities", "HC", cases2);
    assert.equal(run2.plan.plan.inputs.source_kind, "chemical_structure");
    await rec_.step("HC02-already-approved", ["S-scientific-already"], "Observe 이 run에서 이미 계산 승인됨 for the chemical pocket job",
      async () => execRecord(page, run, run2.id), async value => {
        assert.equal(value.scientific_approval.state, "already_approved_in_run");
        return { state: value.scientific_approval.state };
      });
    const rec2 = await execRecord(page, run, run2.id);
    await openPocket(rec_, page, panel, run, rec2, "s01", "chemical", cases2);
    await verifyReports(rec_, page, panel, run, run2.plan, "s02", cases2);
    await verifySummary(rec_, page, panel, run, run2.id, cases2);
    evidence.handles.chemicalCavities = { plan: run2.plan.handle, execution: run2.id };
  });

  await rec_.part("main-placement", ["S-chem-placement"], async () => {
    const cases3 = ["S-chem-placement"];
    await rec_.step("HP01-exit", cases3, "Click 기존 구조로 돌아가기; main panel: chemical_interactions starts in the chemical screen",
      async () => {
        await page.getByRole("button", { name: "기존 구조로 돌아가기", exact: true }).click();
        const main = analysisPanel(page, "main");
        await main.waitFor({ timeout: 30000 });
        await chooseGoal(page, main, "chemical_interactions");
        return main.locator('[data-analysis-placement="chemical_interactions"]').innerText();
      }, async text => { assert.ok(text.includes("화학 작업 화면에서 시작합니다"), text);
        assert.equal(await analysisPanel(page, "main").getByRole("button", { name: "계획 만들기", exact: true }).count(), 0);
        return { placement: text }; });
    await rec_.step("HP02-main-reopen", cases3, "Main panel: reopen the chemical execution; its results open only in the chemical screen",
      async () => {
        const main = analysisPanel(page, "main");
        await openHistory(main);
        await main.getByRole("button", { name: `실행 다시 열기 ${done.id}`, exact: true }).click();
        await main.locator(`[aria-label="분석 실행"][data-analysis-execution-id="${done.id}"][data-analysis-status="complete"]`)
          .waitFor({ timeout: 30000 });
        return { chemButtons: await main.getByRole("button", { name: /^화학 작업 화면에서 열기 s0/ }).count(),
          openHere: await main.getByRole("button", { name: /^결과 열기 s0/ }).count() };
      }, async value => { assert.ok(value.chemButtons >= 2); assert.equal(value.openHere, 0); return value; });
    await rec_.step("HP03-enter", cases3, "Click 화학 작업 화면으로 이동", async () => {
      const main = analysisPanel(page, "main");
      await main.getByRole("button", { name: "화학 작업 화면으로 이동", exact: true }).click();
      await page.getByText("준비 입력과 실제 화학 상호작용", { exact: true }).waitFor({ timeout: 30000 });
      return true;
    }, async () => ({ chemicalWorkspace: true }));
  });
  evidence.providerCalls.push(await providerCalls(page, run));
}

async function modeChemicalAttach(session, input, rec_, evidence) {
  const { page } = session;
  const run = input.run;
  evidence.run = run;
  evidence.fixtureLabels.push("labeled loopback API setup (runner): synthetic attach complex upload/load and SDF import only");
  await waitForBoot(page);
  await rec_.step("A01-open-workspace", [], "Click 화학 상호작용 작업 열기 on the labeled attach run", () => openChemicalWorkspace(page),
    async value => { assert.equal(value, run); return { run }; });
  const panel = analysisPanel(page, "chemical");
  const cases = ["W-chem-attach"];
  const form = await rec_.step("A02-attach-form", cases, "attach_existing: complex, exact ligand, explicit map_existing mapping, " +
    "sidecar, acknowledgements, preview until ready", () => chemicalAttachForm(page, run, input), async value => value);
  evidence.inputs.push(form.files.sdf, form.files.sidecar,
    { name: path.basename(input.mapping), ...fileRecord(input.mapping), provenance: provenanceLabel(path.basename(input.mapping)) },
    { name: path.basename(input.ligand), ...fileRecord(input.ligand), provenance: provenanceLabel(path.basename(input.ligand)) });
  await rec_.step("A03-import", cases, "Select chemical_interactions; the attach request is imported read-only", async () => {
    await chooseGoal(page, panel, "chemical_interactions");

    return panel.locator('[data-analysis-readonly="chemical_request"] pre').textContent();
  }, async text => { const request = JSON.parse(text); assert.equal(request.mode, "attach_existing");
    assert.equal(request.complex_handle, input.complex); return { mode: request.mode, mapped: request.ligand_mapping?.length ?? null }; });
  const done = await runToComplete(rec_, page, panel, run, "chemical_interactions", "AT", cases);
  const rec = await execRecord(page, run, done.id);
  await openChemicalResults(rec_, page, panel, rec, "AT", cases);
  await verifyReports(rec_, page, panel, run, done.plan, "s03", cases);
  await verifySummary(rec_, page, panel, run, done.id, cases);
  await reopenFromHistory(rec_, page, panel, run, done.id, "complete", cases);
  evidence.handles.chemicalAttach = { plan: done.plan.handle, execution: done.id, result: rec.steps[1].outputs.chemical_interaction_set };
  evidence.providerCalls.push(await providerCalls(page, run));
}

/** The labeled impossible-valence SDF: preview is ready, the real native preparation refuses it → visible typed error. */
async function modeChemicalError(session, input, rec_, evidence) {
  const { page } = session;
  const run = await rec_.step("E01-new-run", [], "Click 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.run = run;
  await rec_.step("E02-open-workspace", [], "Click 화학 상호작용 작업 열기", () => openChemicalWorkspace(page), async value => ({ run: value }));
  const panel = analysisPanel(page, "chemical");
  panel.__prefix = "ER";
  const cases = ["S-error"];
  const form = await rec_.step("E03-form", cases, "Choose public receptor + labeled pentavalent-carbon SDF; preview until ready", () =>
    chemicalCreateForm(page, run, path.join(CHEM, "prolif-vina-rec.pdb"), path.join(CHEM, "synthetic-pentavalent-carbon.sdf")),
  async value => value);
  evidence.inputs.push(form.files.receptor, form.files.sdf);
  evidence.fixtureLabels.push("labeled synthetic failure-control SDF (impossible valence); the real native preparation refuses it");
  await chooseGoal(page, panel, "chemical_interactions");

  const plan = await rec_.step("E04-plan", cases, "Click 계획 만들기", () => createPlan(page, panel, run), async value => {
    assert.equal(value.executable, true); return observePlanPreview(panel, value); });
  const created = await rec_.step("E05-exec", cases, "Click 실행 만들기", () => createExecution(page, panel, run, plan),
    async value => ({ executionId: value.execution_id }));
  const id = created.execution_id;
  panel.__execId = id;
  const ended = await drive(rec_, page, panel, run, id, { cases, prefix: "ER-D" });
  await rec_.step("E06-error-shown", cases, "Observe the typed failure of s01 (no later step, no result)", async () => ended.rec,
    async rec => {
      assert.ok(["blocked", "failed"].includes(rec.status), `unexpected ${rec.status}`);
      const s01 = rec.steps[0];
      assert.ok(["blocked", "failed"].includes(s01.status));
      assert.ok(s01.failure, "no recorded failure on s01");
      for (const later of rec.steps.slice(1)) assert.equal(later.status, "pending");
      assert.equal(await panel.getAttribute("data-analysis-ui-state"), "failure");
      const shown = rec.status === "blocked"
        ? await panel.locator("[data-analysis-blocked]").innerText()
        : await panel.locator('li[data-analysis-step="s01"] [data-analysis-step-failure]').innerText();
      const job = await readApi(page, `/runs/${run}/jobs/${s01.job_id}`);
      assert.equal(job.status, "failed");
      assert.deepEqual(job.output_handles, []);
      return { status: rec.status, blocked: rec.blocked_reason, failure: s01.failure, shown, retryable: rec.retryable_step,
        jobFailure: { error: job.failure?.error, reason_code: job.failure?.reason_code } };
    });
  evidence.handles.chemicalError = { plan: plan.handle, execution: id };
  evidence.providerCalls.push(await providerCalls(page, run));
}

/** A dry-run run (API-created record only): plan preview works, execution is plan_only, no science; Stop allowed. */
async function modeDryRun(session, input, rec_, evidence) {
  const { page } = session;
  const response = await page.request.post(new URL("/api/runs", input.origin).toString(), { data: {
    goal: "M13 dry-run QA (labeled API-created dry-run record)", context: [], dry_run: true, egress: "local_only" } });
  assert.equal(response.status(), 201);
  const created = await response.json();
  assert.equal(created.dry_run, true);
  const run = created.run_id;
  evidence.run = run;
  evidence.fixtureLabels.push("labeled loopback API setup: only the initial dry_run:true run record");
  await page.goto(new URL(`/?run=${run}`, input.origin).toString());
  await waitForBoot(page);
  const panel = analysisPanel(page, "main");
  panel.__prefix = "DR";
  const cases = ["S-dry-run"];
  const loaded = await rec_.step("DR01-upload-load-prepare", [], "Choose public_1hsg.cif, 구조 불러오기, 전처리 in the dry-run run", async () => {
    const value = await uploadLoad(page, path.join(FIXTURES, "public_1hsg.cif"));
    const prepared = await prepareManual(page);
    return { ...value, prepared: prepared.prepared };
  }, async value => value);
  evidence.inputs.push(loaded.file);
  await rec_.step("DR02-notice", cases, "Observe the dry-run notice in the analysis panel", async () =>
    panel.locator("[data-analysis-dry-run]").first().innerText(), async text => {
    assert.equal(text.trim(), DRY_RUN_NOTICE); return { notice: text }; });
  const before = await scienceEvents(page, run);
  const plan = await rec_.step("DR03-plan", cases, "Select inspect_ligand, ligand; click 계획 만들기", async () => {
    await chooseGoal(page, panel, "inspect_ligand");
    await ensureSource(page, panel, loaded.prepared);
    const select = panel.getByRole("combobox", { name: "분석 리간드 인스턴스", exact: true });
    await select.locator("option").nth(1).waitFor({ state: "attached", timeout: 30000 });
    await select.selectOption({ index: 1 });
    return createPlan(page, panel, run);
  }, async value => { assert.equal(value.executable, true); return observePlanPreview(panel, value); });
  const exec = await rec_.step("DR04-exec", cases, "Click 실행 만들기: a plan_only execution", async () => {
    const button = panel.getByRole("button", { name: "실행 만들기", exact: true });
    const posted = page.waitForResponse(item => item.request().method() === "POST" &&
      new URL(item.url()).pathname === `/api/runs/${run}/analysis/executions`, { timeout: 60000 });
    await button.click();
    const execution = (await (await posted).json()).execution;
    await panel.locator(`[aria-label="분석 실행"][data-analysis-execution-id="${execution.execution_id}"]`).waitFor({ timeout: 30000 });
    await releaseStuckBusy(page, panel, execution.execution_id, "실행 만들기 (dry-run)");
    return execution;
  }, async value => {
    assert.equal(value.status, "plan_only");
    await panel.locator(`[aria-label="분석 실행"][data-analysis-status="plan_only"]`).waitFor({ timeout: 15000 });
    const notices = await panel.locator("[data-analysis-dry-run]").allInnerTexts();
    assert.ok(notices.every(text => text.trim() === DRY_RUN_NOTICE) && notices.length >= 2);
    for (const label of ["계획 승인", "다음 단계 실행"]) {
      assert.equal(await controlButton(panel, label).isDisabled(), true);
      assert.equal(await controlButton(panel, label).getAttribute("data-analysis-control-reason"), DRY_RUN_NOTICE);
    }
    const posts = [];
    const listener = request => { if (request.method() === "POST" && /\/analysis\/executions\//.test(new URL(request.url()).pathname)) posts.push(1); };
    page.on("request", listener);
    try { await controlButton(panel, "계획 승인").click({ force: true, timeout: 3000 }); } catch { /* refused input */ }
    await page.waitForTimeout(600);
    page.off("request", listener);
    assert.deepEqual(posts, [], "a forced click on a disabled dry-run control sent a request");
    assert.deepEqual(await scienceEvents(page, run), before, "planning in a dry-run run did scientific work");
    return { executionId: value.execution_id, status: value.status, notices: notices.length };
  });
  await rec_.step("DR05-stop", cases, "Click 중지 on the plan_only execution", () =>
    clickControl(page, panel, run, exec.execution_id, "중지"), async value => {
    assert.equal(value.status, 200);
    const rec = await execRecord(page, run, exec.execution_id);
    assert.equal(rec.status, "cancelled");
    assert.deepEqual(await scienceEvents(page, run), before);
    return { status: rec.status };
  });
  evidence.handles.dryRun = { plan: plan.handle, execution: exec.execution_id };
  evidence.providerCalls.push(await providerCalls(page, run));
}

/** Backend started from a labeled layout without the method engines: templates show 사용할 수 없음 with the reason. */
async function modeUnavailable(session, input, rec_, evidence) {
  const { page } = session;
  if (input.fixtureLabel) evidence.fixtureLabels.push(input.fixtureLabel);
  const run = await rec_.step("U01-new-run", [], "Click 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.run = run;
  const loaded = await rec_.step("U02-upload-prepare", [], "Choose public_1hsg.cif, 구조 불러오기, 전처리", async () => {
    const value = await uploadLoad(page, path.join(FIXTURES, "public_1hsg.cif"));
    return { ...value, prepared: (await prepareManual(page)).prepared };
  }, async value => value);
  evidence.inputs.push(loaded.file);
  const panel = analysisPanel(page, "main");
  const cases = ["S-unavailable"];
  await rec_.step("U03-find-cavities", cases, "Select find_cavities: 사용할 수 없음 with the reason, 계획 만들기 disabled", async () => {
    await chooseGoal(page, panel, "find_cavities");
    return panel.locator('[data-analysis-template-unavailable="find_cavities"]').innerText();
  }, async text => {
    const cap = (await readApi(page, "/capabilities")).methods.analysis_workflows;
    const template = cap.templates.find_cavities;
    assert.equal(template.available, false);
    assert.ok(text.includes(template.reason), `panel lacks the capability reason: ${text}`);
    const button = panel.getByRole("button", { name: "계획 만들기", exact: true });
    assert.ok((await button.count()) === 0 || await button.isDisabled(), "계획 만들기 enabled for an unavailable template");
    assert.equal(await panel.getAttribute("data-analysis-ui-state"), "unavailable");
    assert.ok(!/\d+\s*(Å|개|건)/.test(text), "unavailable text shows a number");
    return { text, reason_code: template.reason_code, uiState: "unavailable" };
  });
  await rec_.step("U04-nl", ["S-nl-unavailable"], "Observe 자연어 계획 사용할 수 없음 on this backend too", async () =>
    panel.locator("[data-analysis-nl-unavailable]").innerText(), async text => {
    const cap = (await readApi(page, "/capabilities")).methods.analysis_workflows;
    assert.equal(text.trim(), cap.natural_language_planning.reason);
    return { reason: text };
  });
  await rec_.step("U05-chemical", cases, "Open the chemical workspace; chemical_interactions shows 사용할 수 없음", async () => {
    await openChemicalWorkspace(page);
    const chem = analysisPanel(page, "chemical");
    await chooseGoal(page, chem, "chemical_interactions");
    return chem.locator('[data-analysis-template-unavailable="chemical_interactions"]').innerText();
  }, async text => {
    const cap = (await readApi(page, "/capabilities")).methods.analysis_workflows.templates.chemical_interactions;
    assert.equal(cap.available, false);
    assert.ok(text.includes(cap.reason));
    return { text, reason_code: cap.reason_code };
  });
  evidence.providerCalls.push(await providerCalls(page, run));
}

// ------------------------------------------------------------------ copied M10 pointer helpers (comparison-flow.cjs)
// Exact atom pick through a real mouse click at the native Mol* projection of a catalog atom (not exported there).
function vectorSub(a, b) { return a.map((v, i) => v - b[i]); }
function norm(a) { return Math.hypot(...a); }
function observerIdle(value) {
  return value?.ready === true && value.nativeBusy === false && value.nativeUpdating === false &&
    value.nativeAnimating === false && value.cameraTransitioning === false && value.m10QueuePending === 0 &&
    Number.isInteger(value.nativeClickRevision);
}
async function nativeQuietAt(page, row, timeoutMs = 12000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await page.waitForFunction(() => {
      const value = window.__protviewQaSnapshot?.();
      return value?.ready === true && value.nativeBusy === false && value.nativeUpdating === false &&
        value.nativeAnimating === false && value.cameraTransitioning === false && value.m10QueuePending === 0;
    }, null, { timeout: Math.max(1000, deadline - Date.now()) });
    const first = await snapshot(page);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const second = await snapshot(page);
    const atom = value => value?.qaAtoms?.find(item => item.layer === "reference" &&
      item.ref.structure_handle === row.ref.structure_handle && item.ref.site_index === row.ref.site_index);
    const a = atom(first), b = atom(second);
    if (observerIdle(first) && observerIdle(second) && a && b && norm(vectorSub(a.canvasPixel, b.canvasPixel)) <= 0.25)
      return { second, target: b };
  }
  throw new Error("Native pointer target did not settle");
}
async function clickCatalogAtom(page, row) {
  const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
  const box = await canvas.boundingBox();
  assert.ok(box, "Mol* canvas not visible");
  const size = await canvas.evaluate(element => ({ width: element.width, height: element.height }));
  for (let attempt = 1; attempt <= 3; attempt++) {
    const quiet = await nativeQuietAt(page, row);
    const before = quiet.second;
    const point = { x: box.x + quiet.target.canvasPixel[0] * box.width / size.width,
      y: box.y + quiet.target.canvasPixel[1] * box.height / size.height };
    if (attempt > 1) await page.mouse.move(point.x + 16, point.y + 16);
    await page.mouse.move(point.x, point.y);
    await page.mouse.click(point.x, point.y);
    try {
      return await waitForViewer(page, value => value.atomPickRevision > before.atomPickRevision &&
        value.lastAtomPick?.ref.site_index === row.ref.site_index, 1500);
    } catch (error) {
      const raw = await snapshot(page);
      if (raw?.atomPickRevision > before.atomPickRevision) throw new Error("pointer accepted a different atom");
      if (attempt === 3) throw error;
    }
  }
  throw new Error("unreachable");
}

// ------------------------------------------------------------------ main
const RUNNERS = { main: modeMain, m10: modeM10, race: modeRace, minimize: modeMinimize, "chemical-create": modeChemicalCreate,
  "chemical-attach": modeChemicalAttach, "chemical-error": modeChemicalError, "dry-run": modeDryRun, unavailable: modeUnavailable };

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const evidence = { schema: "m13_workflows_evidence@1", mode: input.mode, run: null, inputs: [], handles: {},
    fixtureLabels: [], providerCalls: [], partFailures: [], startedAt: new Date().toISOString() };
  const session = await launchOffscreen({ url: input.url, artifacts: input.artifacts, interactive: false });
  const rec_ = recorder(session, input, evidence);
  let error = null;
  let proof = null;
  try {
    proof = await offscreenProof(session.app, session.page);
    await RUNNERS[input.mode](session, input, rec_, evidence);
  } catch (caught) {
    error = caught;
  } finally {
    try { proof = { ...await offscreenProof(session.app, session.page), atStart: proof }; } catch { /* keep the start proof */ }
    await session.close();
  }
  if (PRODUCT_ISSUES.length) {
    for (const kind of new Set(PRODUCT_ISSUES.map(item => item.issue)))
      rec_.append({ caseId: `P-${kind}`, cases: [`P-${kind}`], status: "fail",
        description: "Product issue observed while driving the panel (recovered through a visible control)",
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
  fs.writeFileSync(path.join(input.artifacts, "workflows-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  const harness = Object.fromEntries(["workflows-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs", "comparison-flow.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m13_case_ledger_row@1", mode: input.mode, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", cases, runId: evidence.run, handles: evidence.handles, inputs: evidence.inputs,
    fixtureLabels: evidence.fixtureLabels, buildId: buildId(), harness, offscreen: proof,
    externalRequestCount: proof ? proof.nonLoopbackRequests : null, providerCalls: evidence.providerCalls,
    providerCallsZero: providerZero, partFailures: evidence.partFailures, error: evidence.error,
    evidenceFile: path.basename(rec_.file), startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, run: evidence.run, cases }) + "\n");
  if (error) process.stderr.write(`workflows-flow ${input.mode} failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`workflows-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main };
