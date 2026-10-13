"use strict";

// M29 structure repair acceptance harness (.dryforge/spec.md §10.3; plan T11): the UI parts of R1, R3, R4a, R8 and
// R10 (and the viewer part of R6) in a real Electron offscreen page (isOffscreen, GPU/WebGL, paint frames). Every product
// mutation is a Playwright locator mouse/keyboard/file-chooser/select input (the repair confirmation, the first
// expensive call's approval, the job start, every "만들기" button: a person's click); nothing calls application
// internals and this script never posts to the API itself. JEV: the preview is built and the approval area is read,
// the confirmation box and the send button are NEVER touched (spec R10: 전송 0건). Observation is read-only: data
// attributes and text of the page, renderer request/response events, Electron paint frames, downloaded bytes, GET reads
// of the loopback API (page.request.get) and the run's events.jsonl (read-only file reads).
//
// The plan (--plan, written by scripts/m29_offscreen_acceptance.py) names the inputs, the residues and values to choose
// and, for the modes on an existing run, its handles. The harness checks the screen against the stored objects (UI =
// API); the science expectations (the oracle of the input files and the installed template) are the runner's
// (scripts/m29_api_cases.py), which judges the cases from this row and its own GET reads.
//
// Modes:
//   r1   new run: 8VF6 불러오기 → 전처리(strip_all) → 구조 보완 사전 검사 → 확인 → 제출 → 승인 → 시작 → 결과 → mmCIF
//        내려받기 → 보완 보고서 (R1)
//   r3   the r1 run (?run=): M20 on the repaired structure with the original structure's numbering map, annotation and
//        pocket set (the runner made them) + a side-chain residue and a gap residue; SO1–SO3, modeled-residue cells,
//        KLIFS rows, M20 report (R3); JEV preview/approval JW1 without a send, M23 option (R10); the structure tab's
//        structure selects (R6 viewer path)
//   r4a  new run: 1HSG → repair → M20 → M21 (timeout 240) → model report → the labeled synthetic phenol SDF → same-
//        condition docking pair → M18 result and report (R4a)
//   r8   an existing run (?run=) holding the repaired 1RNH: open the record, the replaced-residue table and RP5 (R8)
//
// Step functions copied or adapted from older harnesses say so ("copied from <file>" / "adapted from <file>"); those
// files are not changed. Required exports: driver (launchOffscreen, capture, downloadByClick), normal-flow
// (waitForViewer).
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const { waitForViewer } = require("./normal-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const MODES = ["r1", "r3", "r4a", "r8"];
const TAB = { structure: "구조 분석", protein: "단백질 공학", ligand: "리간드 설계·탐색", knowledge: "지식·보고서" };
const PANEL_ID = { [TAB.structure]: "structure", [TAB.protein]: "protein", [TAB.ligand]: "ligand",
  [TAB.knowledge]: "knowledge" };
const REPAIR_PROTOCOL = "pdbfixer_repair_v1";
const MODEL_PROTOCOL = "openmm_mutation_model_v1";
const DOCKING_PROTOCOL = "qvina_dock_v1";
const M20_TOOL = "generate_mutation_candidates";
const SIDES = ["wild_type_reference", "mutant"];
const ACK_KEYS = ["keep_input_protonation", "tool_assigned_types_charges", "rigid_no_optimization"];
// copied from frontend/src/lib/structure-repair.ts (the screen's own words; the harness never builds them)
const MODELED_NOT_CHECKED_TEXT = "검사 안 함(모델링 잔기)";
const MODELED_BASIS_TRUE = "모델링 원자·잔기 포함";
const REPAIRED_SUFFIX = " · 보완 구조";
const APPROVED_NOTICE = "승인을 기록했습니다";
// What the JEV body must not carry (spec 6.4: the body is unchanged and never says the structure was repaired).
const BODY_FORBIDDEN = ["repair", "보완", "structure_origin", "calc_flag", "obj://", "/Users/"];

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const attr = (name, value) => `[${name}="${String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"]`;
const resText = r => `${r.resname} ${r.chain_auth}:${r.seq_auth}${r.icode ?? ""}`;

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, plan: null, "runs-dir": null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2);
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode) || !value.plan || !value["runs-dir"]) throw new Error(
    `Usage: structure-repair-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> --plan <plan.json> ` +
    "--runs-dir <MW_RUNS_DIR> [--url http://127.0.0.1:3000]. Plan and sequence: scripts/m29_offscreen_acceptance.py.");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  for (const key of ["artifacts", "runs-dir", "plan"]) value[key] = path.resolve(value[key]);
  value.planData = JSON.parse(fs.readFileSync(value.plan, "utf8"));
  assert.equal(value.planData.schema, "m29_plan@1");
  assert.equal(value.planData.mode, value.mode, "the plan is of another mode");
  const run = value.planData.run;
  value.url = new URL(run ? `/?run=${enc(run)}` : "/", value.url).toString();
  return value;
}

// ------------------------------------------------------------------ read-only observation (copied from endtoend-c-flow.cjs)
async function readApi(page, route) {
  const response = await page.request.get(new URL(`/api${route}`, page.url()).toString());
  assert.equal(response.status(), 200, `${route}: ${(await response.text()).slice(0, 300)}`);
  return response.json();
}
async function readBytes(page, route) {
  const response = await page.request.get(new URL(`/api${route}`, page.url()).toString());
  assert.equal(response.status(), 200, route);
  return Buffer.from(await response.body());
}
function runEvents(runsDir, run) {
  return fs.readFileSync(path.join(runsDir, run, "events.jsonl"), "utf8").split("\n").filter(Boolean)
    .map(line => JSON.parse(line));
}
function dispatchTotal(runsDir) {
  let total = 0;
  for (const name of fs.readdirSync(runsDir)) {
    const file = path.join(runsDir, name, "events.jsonl");
    if (!/^run_[0-9a-f]+$/.test(name) || !fs.existsSync(file)) continue;
    total += runEvents(runsDir, name).filter(event => event.type === "jev_science_dispatch_started").length;
  }
  return total;
}
async function waitFor(page, probe, label, timeout = 60000) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    try { last = await probe(); if (last) return last; } catch (error) { last = String(error).slice(0, 300); }
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
/** Renderer requests and the JSON answers of the API writes (adapted from endtoend-c-flow.cjs requestLog). */
function requestLog(page) {
  const rows = [];
  const api = [];
  page.on("request", request => {
    const url = new URL(request.url());
    rows.push({ at: Date.now(), method: request.method(), path: url.pathname });
  });
  page.on("response", async response => {
    const request = response.request();
    const url = new URL(response.url());
    if (request.method() !== "POST" || !url.pathname.startsWith("/api/")) return;
    let body = null;
    try { body = request.postDataJSON(); } catch { body = null; }
    const entry = { at: Date.now(), path: url.pathname, status: response.status(), request: body, json: undefined };
    api.push(entry);
    try { entry.json = await response.json(); } catch { entry.json = null; }
  });
  return { rows, api };
}

// ------------------------------------------------------------------ evidence (adapted from endtoend-c-flow.cjs recorder)
/** Steps and parts. A part runs only when the parts it needs passed; a step failure fails its part, which is recorded
 * and the flow goes on with the next part. */
function recorder(session, evidence) {
  const { app, page, artifacts } = session;
  const file = path.join(artifacts, "structure-repair.jsonl");
  const append = row => fs.appendFileSync(file, JSON.stringify(row) + "\n");
  let current = null;
  async function step(id, description, action, check) {
    const started = Date.now();
    let result;
    try {
      result = await action();
      const assertion = await check(result);
      const proof = await capture(app, page, artifacts, id);
      assert.equal(proof.status.blockedRequests.length, 0, "renderer attempted a non-loopback request");
      assert.equal(proof.status.offscreen, true);
      append({ id, part: current, status: "pass", description, assertion: summarize(assertion),
        blockedRequests: proof.status.blockedRequests.length, paintCount: proof.status.paintCount,
        screenshot: fileRecord(proof.screenshot), paint: fileRecord(proof.paint.path), durationMs: Date.now() - started });
      return assertion;
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${id}-failure`); } catch { /* keep the primary failure */ }
      append({ id, part: current, status: "fail", description, error: String(error.stack ?? error).slice(0, 4000),
        actionResult: result === undefined ? null : summarize(result), screenshot: proof && fileRecord(proof.screenshot),
        durationMs: Date.now() - started });
      throw error;
    }
  }
  async function part(name, needs, work) {
    const blocked = needs.filter(need => evidence.parts[need]?.status !== "pass");
    if (blocked.length) {
      evidence.parts[name] = { status: "not_run", blockedBy: blocked };
      append({ id: `${name}-not-run`, part: name, status: "not_run", blockedBy: blocked });
      return null;
    }
    current = name;
    evidence.parts[name] = { status: "running", startedAt: new Date().toISOString() };
    try {
      const value = await work();
      evidence.parts[name] = { ...evidence.parts[name], status: "pass", finishedAt: new Date().toISOString() };
      return value;
    } catch (error) {
      evidence.parts[name] = { ...evidence.parts[name], status: "fail", finishedAt: new Date().toISOString(),
        error: String(error).slice(0, 800) };
      append({ id: `${name}-aborted`, part: name, status: "fail", error: String(error.stack ?? error).slice(0, 4000) });
      return null;
    } finally { current = null; }
  }
  return { step, part, append, file };
}
function summarize(value) {
  try {
    const text = JSON.stringify(value);
    return text.length > 8000 ? { omitted: "over 8000 characters", chars: text.length, sha256: sha(Buffer.from(text)) }
      : JSON.parse(text);
  } catch { return String(value); }
}
/** A screen text for the runner's R11 scan (texts/<name>.screentext: not a text suffix of the runner's export, kept
 * in the git-ignored artifacts; the row names the file, its size and digest). */
async function keepText(page, evidence, artifacts, name, locator) {
  const text = await locator.innerText({ timeout: 15000 });
  const rel = path.join("texts", `${name.replace(/[^a-z0-9_-]/gi, "_")}.screentext`);
  fs.mkdirSync(path.join(artifacts, "texts"), { recursive: true });
  fs.writeFileSync(path.join(artifacts, rel), text);
  evidence.texts[name] = rel;
  return { name, bytes: Buffer.byteLength(text), sha256: sha(Buffer.from(text)) };
}

// ------------------------------------------------------------------ tabs, runs, structure screen (copied from endtoend-c-flow.cjs)
const tabButton = (page, label) => page.locator(".mw-app-tabs").getByRole("tab", { name: label, exact: true });
async function selectTab(page, label) {
  await tabButton(page, label).click();
  await waitFor(page, async () => await tabButton(page, label).getAttribute("aria-selected") === "true", `${label} selected`, 10000);
}
/** The tab mounts its areas afresh when selected: leave it first when it is the shown tab. */
async function enterTab(page, label) {
  if (await tabButton(page, label).getAttribute("aria-selected") === "true")
    await selectTab(page, label === TAB.structure ? TAB.knowledge : TAB.structure);
  await selectTab(page, label);
}
const globalRun = page => page.evaluate(() => document.querySelector(".mw-app-run")?.getAttribute("data-global-run") ?? null);
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
  await selectTab(page, TAB.structure);
  await waitForBoot(page);
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
async function uploadLoad(page, file) {
  await selectTab(page, TAB.structure);
  await page.getByRole("tab", { name: /^run/i }).click();
  const before = (await snapshot(page))?.sourceHandle ?? null;
  const chooser = page.waitForEvent("filechooser", { timeout: 30000 });
  await page.locator('input[type="file"]').first().click();
  await (await chooser).setFiles(file);
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).waitFor({ timeout: 30000 });
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    /\/commands$/.test(new URL(response.url()).pathname) && response.request().postDataJSON()?.tool === "load_structure",
  { timeout: 90000 });
  posted.catch(() => undefined);
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).click();
  const loadArgs = (await posted).request().postDataJSON().args;
  const viewer = await waitForViewer(page, value => !!value.sourceHandle && value.sourceHandle !== before &&
    value.sourceHandle.includes("/structure/") && value.catalogReady === true, 90000);
  return { handle: viewer.sourceHandle, loadArgs: { model_index: loadArgs.model_index } };
}
async function prepareManual(page, waters) {
  const back = page.getByRole("button", { name: "최신 구조로 돌아가기", exact: true });
  if (await back.isVisible().catch(() => false)) await back.click();
  const row = page.locator(".mw-workflow-row").filter({ has: page.getByRole("button", { name: "전처리", exact: true }) });
  const select = row.getByRole("combobox", { name: /^물/ });
  await select.selectOption(waters);
  assert.equal(await select.inputValue(), waters);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    /\/commands$/.test(new URL(response.url()).pathname) && response.request().postDataJSON()?.tool === "prepare_structure",
  { timeout: 90000 });
  posted.catch(() => undefined);
  await row.getByRole("button", { name: "전처리", exact: true }).click();
  const response = await posted;
  const body = await response.json();
  assert.equal(body.ok, true, `prepare failed: ${JSON.stringify(body).slice(0, 400)}`);
  const prepared = body.handle.handle;
  assert.match(prepared, /\/prepared_structure\//);
  await waitForViewer(page, value => value.sourceHandle === prepared && value.catalogReady === true, 90000);
  return { prepared, args: response.request().postDataJSON().args };
}

// ------------------------------------------------------------------ M29 repair area (new; StructureRepairPanel test ids)
const rpanel = page => page.locator('#mw-app-panel-protein [data-testid="repair-panel"]');
const rt = (page, id) => rpanel(page).locator(`[data-testid="${id}"]`);
const rarea = (page, name) => rpanel(page).locator(`[data-repair-area="${name}"]`);
async function openRepair(page) {
  await enterTab(page, TAB.protein);
  await rpanel(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => ["ready", "empty"].includes(await rpanel(page).getAttribute("data-repair-state")) &&
    await rarea(page, "input").getAttribute("data-state") === "ready" &&
    await rarea(page, "results").getAttribute("data-state") === "ready" ? true : null, "repair area ready", 60000);
}
async function tableCount(page, id) {
  if (await rt(page, id).count()) return Number(await rt(page, id).getAttribute("data-count"));
  if (await rt(page, `${id}-empty`).count()) return 0;
  return null;
}
async function tableRows(page, id) {
  if (!await rt(page, id).count()) return [];
  return rt(page, id).locator("tbody tr").evaluateAll(rows => rows.map(row =>
    [...row.querySelectorAll("td")].map(cell => cell.textContent.replace(/\s+/g, " ").trim())));
}
/** Choose the structure, read the free preflight, check the confirmation (off by default) and submit; approve the
 * run's first expensive call when asked and start; wait for the job to end; open the new record. */
async function repairThroughScreen(ctx, id, prepared, run) {
  const { page, rec, log } = ctx;
  await rec.step(`${id}-preflight`, "구조 보완: choose the prepared structure (nothing chosen by itself); the free preflight " +
    "read shows the server's defect lists, blockers, statements and admission; the confirmation box is off and the submit " +
    "button is blocked until it is ticked", async () => {
    await openRepair(page);
    const chosenBefore = await rpanel(page).locator('input[data-testid="repair-structure"]:checked').count();
    const confirmDisabledBefore = await rt(page, "repair-confirm").isDisabled();
    await rpanel(page).locator(`input[data-testid="repair-structure"]${attr("data-repair-structure", prepared)}`).check();
    await rpanel(page).locator(`[data-testid="repair-preflight"]${attr("data-structure", prepared)}`).waitFor({ timeout: 60000 });
    const api = await readApi(page, `/runs/${run}/structure_repair/preflight?structure=${enc(prepared)}`);
    const box = rt(page, "repair-preflight");
    const gaps = await tableRows(page, "repair-defect-gaps");
    const shown = { repairable: await box.getAttribute("data-repairable"), admitted: await box.getAttribute("data-admitted"),
      sideChainRows: await tableCount(page, "repair-defect-side-chain"), oxtRows: await tableCount(page, "repair-defect-oxt"),
      gapRows: await tableCount(page, "repair-defect-gaps"), gapLengths: gaps.map(cells => Number(cells[3])),
      chainPartRows: await tableCount(page, "repair-defect-chain-parts"),
      nonstandardRows: await tableCount(page, "repair-defect-nonstandard"),
      blockerRows: await tableCount(page, "repair-blockers"),
      statements: await rt(page, "repair-preflight-statements").count()
        ? (await rt(page, "repair-preflight-statements").locator("p").allInnerTexts()).map(clean) : [],
      expectedText: clean(await rt(page, "repair-preflight-expected").innerText()),
      confirmChecked: await rt(page, "repair-confirm").isChecked(), submitDisabled: await rt(page, "repair-submit").isDisabled(),
      blockedShown: await rt(page, "repair-submit-blocked").count() > 0 };
    return { chosenBefore, confirmDisabledBefore, api, shown };
  }, async value => {
    const { api, shown } = value;
    assert.equal(value.chosenBefore, 0, "a structure was chosen by itself");
    assert.equal(value.confirmDisabledBefore, true, "the confirmation is usable before a structure is chosen");
    assert.equal(api.starts_job, false);
    assert.equal(shown.repairable, String(api.repairable));
    assert.equal(shown.admitted, String(api.admission.admitted));
    assert.equal(shown.sideChainRows, api.defects.side_chain_residues.length);
    assert.equal(shown.oxtRows, api.defects.terminal_oxt.length);
    assert.equal(shown.gapRows, api.defects.gaps.length);
    assert.deepEqual(shown.gapLengths, api.defects.gaps.map(gap => gap.length));
    assert.equal(shown.chainPartRows, api.defects.chain_parts.length);
    assert.equal(shown.nonstandardRows, api.defects.nonstandard.length);
    assert.equal(shown.blockerRows, api.blockers.length);
    assert.deepEqual(shown.statements, api.statements);
    assert.ok(shown.expectedText.includes(String(api.expected_added_residues)) &&
      shown.expectedText.includes(String(api.expected_added_heavy_atoms)), shown.expectedText);
    assert.equal(shown.confirmChecked, false, "the confirmation box is on by default");
    assert.equal(shown.submitDisabled, true, "the submit button is open before the confirmation");
    assert.equal(shown.blockedShown, true);
    ctx.state.preflight = shown;
    return shown;
  });
  const job = await rec.step(`${id}-job`, "Tick the repair_policy confirmation, 보완 작업 제출 (POST /jobs pdbfixer_repair_v1 " +
    "with the literal policy); the run's first expensive call asks for 비싼 계산 승인 (a person's click), then 작업 시작; the " +
    "real PDBFixer job finishes and the screen offers the new record without opening it", async () => {
    await rt(page, "repair-confirm").check();
    await waitFor(page, async () => await rt(page, "repair-submit").isEnabled() ? true : null, "submit enabled", 15000);
    const since = Date.now();
    await rt(page, "repair-submit").click();
    const submitted = await waitApi(page, log, since, entry => entry.path === `/api/runs/${run}/jobs` &&
      entry.request?.protocol_id === REPAIR_PROTOCOL, "repair job submission");
    const jobId = submitted.json?.job_id;
    const phases = [];
    let approved = false;
    const first = await waitFor(page, async () => {
      const node = rt(page, "repair-job");
      if (!await node.count() || await node.getAttribute("data-job-id") !== jobId) return null;
      if (await rt(page, "repair-job-approve").count() && await rt(page, "repair-job-approve").isEnabled()) return "awaiting_approval";
      const status = await node.getAttribute("data-job-status");
      return ["claimed", "running", "done", "failed", "cancelled"].includes(status) ? status : null;
    }, "repair job after submit", 120000);
    phases.push(first);
    if (first === "awaiting_approval") {
      await rt(page, "repair-job-approve").click();
      approved = true;
      await rt(page, "repair-notice").filter({ hasText: APPROVED_NOTICE }).waitFor({ timeout: 30000 });
      await waitFor(page, async () => await rt(page, "repair-job-start").isEnabled() ? true : null, "작업 시작 enabled", 30000);
      await rt(page, "repair-job-start").click();
      phases.push("started");
    }
    const status = await waitFor(page, async () => {
      const value = await rt(page, "repair-job").getAttribute("data-job-status");
      if (value !== phases.at(-1)) phases.push(value);
      return ["done", "failed", "cancelled", "interrupted"].includes(value) ? value : null;
    }, "repair job final", 600000);
    const stored = await readApi(page, `/runs/${run}/jobs/${enc(jobId)}`);
    await rt(page, "repair-new").waitFor({ timeout: 60000 });
    const record = await rt(page, "repair-new").getAttribute("data-repair-record");
    const openedBefore = await rt(page, "repair-detail").count();
    return { jobId, phases, approved, status, stored, record, openedBefore, request: submitted.request };
  }, async value => {
    assert.equal(value.status, "done", JSON.stringify(value.stored.failure));
    assert.equal(value.approved, true, "the run's first expensive call did not ask for approval");
    assert.deepEqual(value.request.args, { structure: prepared, repair_policy: "complete_missing_atoms_v1" });
    assert.equal(value.request.timeout_s, 120, "the screen sends its fixed 120 s");
    assert.equal(value.stored.output_handles[0], value.record);
    assert.equal(value.openedBefore, 0, "the new record was opened by itself");
    return { jobId: value.jobId, phases: value.phases, record: value.record, repaired: value.stored.output_handles[1],
      approved: value.approved, timeoutS: value.request.timeout_s };
  });
  return job;
}
/** Open a record and compare every shown value with the stored record read (no number made by the browser). */
async function recordMatches(page, run, record, opener) {
  await opener.click();
  await rpanel(page).locator(`[data-testid="repair-detail"]${attr("data-repair-record", record)}`).waitFor({ timeout: 60000 });
  await waitFor(page, async () => await rt(page, "repair-atoms-pager").count() ? true : null, "atom page", 60000);
  const detail = await readApi(page, `/runs/${run}/structure_repairs/${enc(record)}`);
  const result = detail.result;
  const summary = rt(page, "repair-summary");
  const shown = { heavy: Number(await summary.getAttribute("data-protein-heavy-atoms")),
    residues: Number(await summary.getAttribute("data-added-residues")), atoms: Number(await summary.getAttribute("data-added-atoms")),
    classes: await rt(page, "repair-classes").locator("span[data-class]").evaluateAll(items =>
      items.map(item => [item.getAttribute("data-class"), item.getAttribute("data-applied")])),
    gaps: await tableCount(page, "repair-gaps"), atomsTotal: Number(await rt(page, "repair-atoms-pager").getAttribute("data-total")),
    atomRows: await tableCount(page, "repair-atoms"), replaced: await tableCount(page, "repair-replaced"),
    replacedRows: await tableRows(page, "repair-replaced"), chainEnds: await tableCount(page, "repair-chain-ends"),
    collisions: await tableCount(page, "repair-collisions"),
    zero: Number(await rt(page, "repair-zero-occupancy").getAttribute("data-count")),
    limitations: (await rt(page, "repair-limitations").locator("[data-limitation]").allInnerTexts()).map(clean),
    repairedAttr: await rt(page, "repair-detail").getAttribute("data-repaired-structure") };
  assert.equal(shown.heavy, result.counts.protein_heavy_atoms);
  assert.equal(shown.residues, result.counts.added_residues);
  assert.equal(shown.atoms, result.counts.added_atoms);
  assert.deepEqual(shown.classes.filter(([, applied]) => applied === "true").map(([key]) => key), result.classes_applied);
  assert.equal(shown.gaps, result.gaps.length);
  assert.equal(shown.atomsTotal, detail.added_atom_count);
  assert.equal(shown.atomRows, Math.min(100, detail.added_atom_count));
  assert.equal(shown.replaced, result.replaced.length);
  assert.equal(shown.chainEnds, result.chain_ends.length);
  assert.equal(shown.collisions, 5, "one collision row per partner class");
  assert.equal(shown.zero, result.zero_occupancy_input_atoms.count);
  assert.deepEqual(shown.limitations, result.limitations);
  assert.equal(shown.repairedAttr, detail.prepared_structure);
  return { shown, detail };
}

// ------------------------------------------------------------------ M20 panel (copied from endtoend-c-flow.cjs)
const panel = page => page.locator('#mw-app-panel-protein [data-testid="mutation-panel"]');
const testId = (page, id) => panel(page).locator(`[data-testid="${id}"]`);
const panelState = page => panel(page).getAttribute("data-mutation-state", { timeout: 2000 }).catch(() => null);
async function waitState(page, states, timeout = 60000) {
  const wanted = Array.isArray(states) ? states : [states];
  return waitFor(page, async () => { const state = await panelState(page); return wanted.includes(state) ? state : null; },
    `mutation panel ${wanted.join("|")}`, timeout);
}
async function openReady(page) {
  await enterTab(page, TAB.protein);
  await panel(page).waitFor({ timeout: 15000 });
  await waitState(page, ["ready", "scientific_null"]);
  await waitFor(page, async () => await panel(page).locator('[data-mutation-area="sets"]').getAttribute("data-state") === "ready"
    && await panel(page).locator('[data-testid="mutation-structures"] input').first().isEnabled() ? true : null,
  "mutation lists ready", 60000);
}
async function chooseStructure(page, prepared) {
  await panel(page).locator(`label${attr("data-mutation-structure", prepared)} input`).check();
  await waitFor(page, async () => (await testId(page, "mutation-ligand").locator("option").count()) > 1 ||
    (await testId(page, "mutation-no-ligands").count()) > 0 ? true : null, "structure residues read (ligand options)", 60000);
}
async function selectOptions(locator) {
  return locator.locator("option").evaluateAll(items => items.map(item => ({ value: item.value, text: item.textContent.trim(),
    disabled: item.disabled })));
}
async function setCheck(page, id, on) {
  const box = testId(page, id);
  if (await box.isChecked() !== on) await box.click();
  assert.equal(await box.isChecked(), on);
}
async function pickerCount(page, picker) { return Number(await testId(page, `mutation-picker-${picker}`).getAttribute("data-count")); }
async function pickResidueAt(page, picker, spec) {
  const select = testId(page, `mutation-pick-${picker}`);
  const option = await waitFor(page, async () => {
    const found = (await selectOptions(select)).filter(item => item.text.startsWith(`${spec.resname} ${spec.chain_auth}:${spec.seq_auth}${spec.icode ?? ""} ·`)
      && !item.disabled);
    return found.length === 1 ? found[0] : null;
  }, `${picker} option ${spec.resname} ${spec.chain_auth}:${spec.seq_auth}`, 60000);
  const before = await pickerCount(page, picker);
  await select.selectOption(option.value);
  await testId(page, `mutation-add-${picker}`).click();
  await waitFor(page, async () => await pickerCount(page, picker) === before + 1 ? true : null, `${picker} count +1`, 10000);
}
async function requestErrors(page) {
  if (!await testId(page, "mutation-request-errors").count()) return [];
  return testId(page, "mutation-request-errors").locator("li").allInnerTexts();
}
async function create(page, run) {
  await waitFor(page, async () => await testId(page, "mutation-create").isEnabled() ? true : null, "후보 만들기 enabled", 15000)
    .catch(async error => { throw new Error(`${error.message}; request errors: ${(await requestErrors(page)).join(" | ")}`); });
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === M20_TOOL,
  { timeout: 180000 });
  await testId(page, "mutation-create").click();
  const response = await posted;
  const body = await response.json();
  const args = response.request().postDataJSON().args;
  if (body.ok !== true) return { ok: false, status: response.status(), body, args };
  const handle = body.handle.handle;
  await panel(page).locator(`[data-testid="mutation-create-done"]${attr("data-mutation-new-set", handle)}`).waitFor({ timeout: 30000 });
  await panel(page).locator(`[data-testid="mutation-detail"]${attr("data-mutation-detail", handle)}`).waitFor({ timeout: 90000 });
  await waitState(page, ["ready", "scientific_null"]);
  return { ok: true, status: response.status(), body, args, handle };
}
async function positionRows(page) {
  if (!await testId(page, "mutation-positions").count()) return [];
  return testId(page, "mutation-positions").locator("tr[data-mutation-position]").evaluateAll(items => items.map(item => ({
    index: Number(item.getAttribute("data-mutation-position")), residue: item.getAttribute("data-residue"),
    status: item.getAttribute("data-status"), reasons: item.getAttribute("data-exclusion-reasons"),
    modeledAttr: item.getAttribute("data-modeled-basis"),
    numbering: item.querySelector('[data-cell="numbering"]')?.textContent.trim() ?? null,
    klifs: item.querySelector('[data-cell="klifs"]')?.textContent.trim() ?? null,
    modeledBasis: item.querySelector('[data-cell="modeled-basis"]')?.textContent.trim() ?? null })));
}
/** Filter the position table and wait until it equals the stored page of the same query (index order). */
async function filteredPositions(page, run, set, filter, value) {
  await testId(page, filter).selectOption(value);
  const query = `${filter === "mutation-filter-source" ? "source" : "exclusion_reason"}=${enc(value)}&sort=order&offset=0&limit=50`;
  const api = await readApi(page, `/runs/${run}/mutation_candidate_sets/${enc(set)}/positions?${query}`);
  await waitFor(page, async () => {
    const node = testId(page, "mutation-positions-pager");
    if (api.total && !await node.count()) return null;
    if (api.total && Number(await node.getAttribute("data-total")) !== api.total) return null;
    const rows = await positionRows(page);
    return rows.map(row => row.index).join(",") === api.rows.map(row => row.index).join(",") ? true : null;
  }, `positions ${query}`, 30000);
  const rows = await positionRows(page);
  await testId(page, filter).selectOption("");
  return { api, rows };
}

// ------------------------------------------------------------------ M21 model panel (copied from endtoend-c-flow.cjs)
const mpanel = page => page.locator('#mw-app-panel-protein [data-testid="mutation-model-panel"]');
const mt = (page, id) => mpanel(page).locator(`[data-testid="${id}"]`);
async function waitListReady(page) {
  await waitFor(page, async () => await mpanel(page).locator('[data-mutation-model-area="list"]').getAttribute("data-state") === "ready"
    ? true : null, "model list ready", 60000);
}
async function jobView(page) {
  const job = mt(page, "mutation-model-job");
  if (!await job.count()) return null;
  return { id: await job.getAttribute("data-job-id"), status: await job.getAttribute("data-job-status"),
    approval: await job.getAttribute("data-approval-pending") };
}
async function runModelJob(page, run, waitMs) {
  const phases = [];
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/jobs` && response.request().postDataJSON()?.protocol_id === MODEL_PROTOCOL,
  { timeout: 120000 });
  posted.catch(() => undefined);
  await mt(page, "mutation-model-submit").click();
  const response = await posted;
  const submitted = await response.json();
  const request = response.request().postDataJSON();
  assert.equal(response.status(), 200, JSON.stringify(submitted).slice(0, 400));
  const jobId = submitted.job_id;
  const first = await waitFor(page, async () => {
    const view = await jobView(page);
    if (!view || view.id !== jobId) return null;
    if (view.approval === "true" && await mt(page, "mutation-model-job-approve").isEnabled().catch(() => false)) return { ...view, phase: "awaiting_approval" };
    if (["claimed", "running", "done", "failed", "cancelled", "interrupted"].includes(view.status)) return { ...view, phase: view.status };
    if (view.status === "queued" && await mt(page, "mutation-model-job-start").isEnabled().catch(() => false)) return { ...view, phase: "saved" };
    return null;
  }, "model job submitted", 120000);
  phases.push(first.phase);
  let approved = false;
  if (first.phase === "awaiting_approval") {
    await mt(page, "mutation-model-job-approve").click();
    approved = true;
    await mt(page, "mutation-model-notice").filter({ hasText: APPROVED_NOTICE }).waitFor({ timeout: 30000 });
  }
  const view = await jobView(page);
  if (view.status === "queued") {
    await waitFor(page, async () => await mt(page, "mutation-model-job-start").isEnabled() ? true : null, "작업 시작 enabled", 30000);
    await mt(page, "mutation-model-job-start").click();
  }
  const done = await waitFor(page, async () => {
    const value = await jobView(page);
    if (value && value.id === jobId && value.status !== phases.at(-1)) phases.push(value.status);
    return value && value.id === jobId && ["done", "failed", "cancelled", "interrupted"].includes(value.status) ? value : null;
  }, "model job final", waitMs);
  const job = await readApi(page, `/runs/${run}/jobs/${enc(jobId)}`);
  return { jobId, request, phases, approved, done, job };
}
async function openModel(page, handle) {
  const radio = mpanel(page).locator(`label${attr("data-mutation-model", handle)} input`);
  await radio.waitFor({ timeout: 30000 });
  await radio.check();
  await mpanel(page).locator(`[data-testid="mutation-model-detail"]${attr("data-model-handle", handle)}`).waitFor({ timeout: 60000 });
}
async function pairJobs(page) {
  return Object.fromEntries(await Promise.all(SIDES.map(async side => {
    const node = mt(page, `mutation-model-pair-job-${side}`);
    if (!await node.count()) return [side, null];
    return [side, { status: await node.getAttribute("data-job-status"), id: await node.getAttribute("data-job-id") }];
  })));
}
async function fillPair(page, sdfHandle, docking) {
  await mpanel(page).locator('label[data-pair-ligand-source="sdf"] input').check();
  await mt(page, "mutation-model-pair-sdf").selectOption(sdfHandle);
  await mpanel(page).locator('label[data-pair-box="ligand_range"] input').check();
  for (const [id, value] of [["mutation-model-pair-margin", docking.margin], ["mutation-model-pair-seed", docking.seed],
    ["mutation-model-pair-exhaustiveness", docking.exhaustiveness], ["mutation-model-pair-num-modes", docking.numModes],
    ["mutation-model-pair-energy-range", docking.energyRange]]) await mt(page, id).fill(value);
  for (const key of ACK_KEYS) await mpanel(page).locator(`label[data-pair-ack="${key}"] input`).check();
}
async function submitPair(page, run) {
  await mt(page, "mutation-model-pair-units").check();
  await waitFor(page, async () => await mt(page, "mutation-model-pair-submit").isEnabled() ? true : null, "pair submit enabled", 15000);
  const responses = [];
  const listener = async response => {
    if (response.request().method() !== "POST" || new URL(response.url()).pathname !== `/api/runs/${run}/jobs`) return;
    const body = response.request().postDataJSON();
    if (body?.protocol_id !== DOCKING_PROTOCOL) return;
    responses.push({ status: response.status(), request: body, body: await response.json().catch(() => null) });
  };
  page.on("response", listener);
  try {
    await mt(page, "mutation-model-pair-submit").click();
    await waitFor(page, async () => responses.length === 2 && responses.every(item => item.body) ? true : null, "two docking submissions", 60000);
  } finally { page.off("response", listener); }
  return { responses };
}
async function drivePair(page, ids) {
  const actions = [];
  const deadline = Date.now() + 900000;
  while (Date.now() < deadline) {
    const jobs = await pairJobs(page);
    if (SIDES.every(side => ["done", "failed", "cancelled", "interrupted"].includes(jobs[side]?.status))) return { actions, jobs };
    for (const id of ["mutation-model-pair-approve", "mutation-model-pair-continue"]) {
      if (await mt(page, id).isVisible().catch(() => false) && await mt(page, id).isEnabled().catch(() => false)) {
        await mt(page, id).click();
        actions.push(id);
        await page.waitForTimeout(500);
      }
    }
    await page.waitForTimeout(300);
  }
  throw new Error(`pair jobs did not end: ${JSON.stringify(await pairJobs(page))} ids ${JSON.stringify(ids)}`);
}
async function importLigandSdf(page, run, file) {
  await selectTab(page, TAB.ligand);
  const dock = page.locator('#mw-app-panel-ligand [data-testid="docking-panel"]');
  await dock.waitFor({ timeout: 15000 });
  const known = new Set((await readApi(page, `/runs/${run}/docking/prerequisites`)).imports.map(item => item.handle));
  const chooser = page.waitForEvent("filechooser", { timeout: 15000 });
  await dock.locator('[data-testid="docking-file-ligand"]').click();
  await (await chooser).setFiles(file);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/chemical/imports`, { timeout: 60000 });
  posted.catch(() => undefined);
  await dock.locator('[data-testid="docking-import"]').click();
  assert.equal((await posted).status(), 201);
  await dock.locator('[data-testid="docking-import-done"]').waitFor({ timeout: 60000 });
  const fresh = (await readApi(page, `/runs/${run}/docking/prerequisites`)).imports.filter(item => !known.has(item.handle));
  assert.equal(fresh.length, 1, JSON.stringify(fresh));
  assert.equal(fresh[0].input_kind, "ligand_sdf");
  return fresh[0].handle;
}

// ------------------------------------------------------------------ JEV (adapted from endtoend-c-flow.cjs)
const jev = page => page.locator('#mw-app-panel-knowledge [data-testid="jev-panel"]');
const jt = (page, id) => jev(page).locator(`[data-testid="${id}"]`);
const jarea = (page, name) => jev(page).locator(`[data-jev-area="${name}"]`);
async function openKnowledge(page) {
  await enterTab(page, TAB.knowledge);
  await jev(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => await jev(page).getAttribute("data-jev-state") === "ready" &&
    await jarea(page, "status").getAttribute("data-state") === "ready" &&
    await jarea(page, "history").getAttribute("data-state") === "ready" ? true : null, "JEV area ready", 45000);
}
async function waitApi(page, log, since, match, label, timeout = 120000) {
  return waitFor(page, async () => log.api.find(entry => entry.at >= since && entry.json !== undefined &&
    match(entry)) ?? null, label, timeout);
}

// ------------------------------------------------------------------ JEV loop area, protein (adapted from endtoend-c-flow.cjs)
const lp = page => page.locator('#mw-app-panel-protein [data-testid="jev-loop-panel"][data-branch="protein"]');
const lpt = (page, id) => lp(page).locator(`[data-testid="${id}"]`);
async function openLoopArea(page) {
  await enterTab(page, TAB.protein);
  await lp(page).waitFor({ timeout: 30000 });
  await waitFor(page, async () => {
    const state = await lp(page).getAttribute("data-jev-loop-state");
    if (!["ready", "empty"].includes(state)) return null;
    if (await lp(page).locator('[data-jev-loop-area="status"]').getAttribute("data-state") !== "ready") return null;
    if (await lp(page).locator('[data-jev-loop-field="pool"] [aria-busy="true"]').count()) return null;
    if (await lp(page).locator('[data-jev-loop-field="setup"] [aria-busy="true"]').count()) return null;
    return true;
  }, "protein loop area ready", 60000);
}
async function loopFill(page, id, value) { await lpt(page, id).fill(String(value)); }
async function loopProteinSetup(page, phenol, docking) {
  await lpt(page, "jev-loop-confirm-selection").check();
  await lpt(page, "jev-loop-confirm-hydrogen").check();
  await loopFill(page, "jev-loop-cutoff", "4.0");
  await lp(page).locator('[data-testid="jev-loop-setup-ligand-source"] label[data-pair-ligand-source="sdf"] input').check();
  await waitFor(page, async () => await lpt(page, "jev-loop-setup-sdf").locator(`option${attr("value", phenol)}`).count()
    ? true : null, "phenol SDF listed", 30000);
  await lpt(page, "jev-loop-setup-sdf").selectOption(phenol);
  await lp(page).locator('[data-testid="jev-loop-setup-box-source"] label[data-pair-box="ligand_range"] input').check();
  await loopFill(page, "jev-loop-setup-margin", docking.margin);
  await loopFill(page, "jev-loop-setup-seed", docking.seed);
  await loopFill(page, "jev-loop-setup-exhaustiveness", docking.exhaustiveness);
  await loopFill(page, "jev-loop-setup-num-modes", docking.numModes);
  await loopFill(page, "jev-loop-setup-energy-range", docking.energyRange);
  for (const key of ACK_KEYS)
    await lp(page).locator(`[data-testid="jev-loop-setup-acknowledgement"] label[data-pair-ack="${key}"] input`).check();
}

// ------------------------------------------------------------------ modes
async function modeR1(ctx) {
  const { page, plan, rec, evidence, artifacts } = ctx;
  const seen = evidence.observed.r1 = {};
  await rec.part("r1-load", [], async () => {
    const made = await rec.step("r1-01", "구조 분석: 새 run, choose the 8VF6 file (file chooser), 구조 불러오기, then 전처리 with " +
      "물 strip_all (the screen's own controls)", async () => {
      const run = await newRun(page);
      const loaded = await uploadLoad(page, plan.input.path);
      const prepared = await prepareManual(page, plan.waters);
      return { run, loaded, prepared };
    }, async value => {
      assert.equal(fileRecord(plan.input.path).sha256, plan.input.sha256, "the chosen file is not the plan's");
      assert.equal(value.prepared.args.waters, plan.waters);
      return { run: value.run, source: value.loaded.handle, prepared: value.prepared.prepared, args: value.prepared.args };
    });
    Object.assign(seen, made);
    evidence.run = made.run;
  });
  await rec.part("r1-preflight", ["r1-load"], async () => {
    seen.job = await repairThroughScreen(ctx, "r1-02", seen.prepared, seen.run);
    seen.preflight = ctx.state.preflight;
    seen.record = seen.job.record;
    seen.repaired = seen.job.repaired;
  });
  await rec.part("r1-job", ["r1-preflight"], async () => { assert.ok(seen.record); });
  await rec.part("r1-result", ["r1-job"], async () => {
    seen.detail = await rec.step("r1-03", "이 기록 열기: the summary, class table, added residues and atoms (page), chain parts, " +
      "replaced residues, chain ends, the collision record (one row per partner class), zero-occupancy count and RP " +
      "sentences equal the stored record read", async () => recordMatches(page, seen.run, seen.record, rt(page, "repair-open-new")),
    async value => ({ shown: value.shown, published: value.detail.published_seq }));
    seen.panelText = await keepText(page, evidence, artifacts, "r1-repair-panel", rpanel(page));
  });
  await rec.part("r1-download", ["r1-result"], async () => {
    seen.download = await rec.step("r1-04", "보완 구조 mmCIF 내려받기 (a person's click on the link): the downloaded bytes are " +
      "the stored repaired structure's bytes", async () => {
      const download = await downloadByClick(ctx.app, rt(page, "repair-download"), 60000);
      const api = await readBytes(page, `/runs/${seen.run}/structure_repairs/${enc(seen.record)}/structure`);
      return { download, apiSha256: sha(api), apiBytes: api.length };
    }, async value => {
      assert.equal(value.download.sha256, value.apiSha256);
      assert.equal(value.download.bytes, value.apiBytes);
      return { sha256: value.download.sha256, bytes: value.download.bytes, filename: value.download.filename };
    });
  });
  await rec.part("r1-report", ["r1-result"], async () => {
    seen.report = await rec.step("r1-05", "보고서 만들기: saved (201) as structure_repair_markdown@1 for this record, listed under " +
      "the record (the repair is not run again)", async () => {
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${seen.run}/method_reports`, { timeout: 120000 });
      const jobsBefore = (await readApi(page, `/runs/${seen.run}/jobs`)).length;
      await rt(page, "repair-report").click();
      const response = await posted;
      const body = await response.json();
      await rt(page, "repair-report-done").waitFor({ timeout: 60000 });
      await rt(page, "repair-report-list").locator(`li${attr("data-report-handle", body.handle)}`).waitFor({ timeout: 30000 });
      const saved = await readApi(page, `/runs/${seen.run}/reports/selected?handle=${enc(body.handle)}`);
      return { status: response.status(), handle: body.handle, done: await rt(page, "repair-report-done").getAttribute("data-report-handle"),
        saved, jobsAdded: (await readApi(page, `/runs/${seen.run}/jobs`)).length - jobsBefore };
    }, async value => {
      assert.equal(value.status, 201);
      assert.equal(value.done, value.handle);
      assert.equal(value.saved.manifest.analysis_type, "structure_repair");
      assert.equal(value.saved.manifest.render_version, "structure_repair_markdown@1");
      assert.equal(value.saved.manifest.result_handle, seen.record);
      assert.equal(value.jobsAdded, 0, "the report ran a job");
      return { handle: value.handle, renderVersion: value.saved.manifest.render_version };
    });
  });
}

async function modeR3(ctx) {
  const { page, plan, rec, evidence, artifacts, log } = ctx;
  const S = plan.r3;
  const run = plan.run;
  const seen = evidence.observed.r3 = { run, record: S.record, repaired: S.repaired };
  const r10 = evidence.observed.r10 = { sendClicked: false };
  evidence.run = run;
  await rec.part("r3-m20", [], async () => {
    await rec.step("r3-00", "Open the r1 run (its address): the page reopens that run", async () => {
      await waitForBoot(page);
      await waitFor(page, async () => await globalRun(page) === run, "the plan's run", 30000);
      return { run: await globalRun(page) };
    }, async value => value);
    const made = await rec.step("r3-01", "단백질 공학 변이 후보: the repaired structure is offered with its 보완 구조 badge (original and " +
      "record named); choose it: the reference note; pocket source = the ORIGINAL structure's pocket set rank 1, ligand " +
      "shell 5.0 Å around A1AAY A:600, direct residues = a side-chain-repaired residue and a gap residue; annotation and " +
      "numbering map of the original structure; 후보 만들기", async () => {
      await openReady(page);
      const label = panel(page).locator(`label${attr("data-mutation-structure", S.repaired)}`);
      const badge = label.locator('[data-testid="mutation-structure-repaired"]');
      const badgeView = { record: await badge.getAttribute("data-repair-record"), source: await badge.getAttribute("data-source-structure") };
      await chooseStructure(page, S.repaired);
      const referenceNote = await testId(page, "mutation-repair-reference-note").count();
      if (S.pocketSet) {
        await setCheck(page, "mutation-source-pocket", true);
        await panel(page).locator(`label${attr("data-mutation-pocket-set", S.pocketSet)} input`).check();
        await testId(page, "mutation-pocket-numbers").waitFor({ timeout: 60000 });
        for (const rank of S.pocketRanks) await testId(page, "mutation-pocket-numbers").getByRole("checkbox", { name: `포켓 ${rank}`, exact: true }).check();
      }
      await setCheck(page, "mutation-source-ligand-shell", true);
      await testId(page, "mutation-radius").fill(String(S.radiusA.toFixed(1)));
      const ligandOption = (await selectOptions(testId(page, "mutation-ligand"))).find(item =>
        item.text.startsWith(`${resText(S.ligand)} ·`));
      assert.ok(ligandOption, "the ligand is not offered");
      await testId(page, "mutation-ligand").selectOption(ligandOption.value);
      await setCheck(page, "mutation-source-user", true);
      for (const residue of [S.sideChainResidue, S.gapResidue]) await pickResidueAt(page, "user", residue);
      await testId(page, "mutation-annotation").selectOption(S.annotation);
      await testId(page, "mutation-numbering-map").selectOption(S.numberingMap);
      const created = await create(page, run);
      return { badgeView, referenceNote, created };
    }, async value => {
      assert.deepEqual(value.badgeView, { record: S.record, source: S.prepared });
      assert.equal(value.referenceNote, 1);
      assert.equal(value.created.ok, true, JSON.stringify(value.created.body).slice(0, 600));
      const args = value.created.args;
      assert.equal(args.structure, S.repaired);
      assert.equal(args.numbering_map, S.numberingMap);
      assert.equal(args.annotation, S.annotation);
      if (S.pocketSet) assert.deepEqual(args.sources.pocket, { pocket_set: S.pocketSet, ranks: S.pocketRanks });
      return { set: value.created.handle, args };
    });
    seen.set = made.set;
    seen.args = made.args;
  });
  await rec.part("r3-detail", ["r3-m20"], async () => {
    await rec.step("r3-02", "The opened set: SO1 with the record (보완 기록 열기), SO2 and SO3 as the server gives them; the user " +
      "rows: the gap residue's numbering and KLIFS cells read 검사 안 함(모델링 잔기) and its modeled-basis cell 모델링 원자·잔기 " +
      "포함; the klifs_key_site rows equal the stored page", async () => {
      const origin = testId(page, "mutation-repair-origin");
      await origin.waitFor({ timeout: 30000 });
      const so1 = clean(await origin.locator('p[data-statement="SO1"]').innerText());
      const statements = await testId(page, "mutation-repair-statements").locator("p[data-statement]").evaluateAll(items =>
        items.map(item => ({ id: item.getAttribute("data-statement"), text: item.textContent.replace(/\s+/g, " ").trim() })));
      const user = await filteredPositions(page, run, seen.set, "mutation-filter-source", "user");
      const klifs = await filteredPositions(page, run, seen.set, "mutation-filter-reason", "klifs_key_site");
      return { so1, originRecord: await origin.getAttribute("data-repair-record"), statements, user, klifs };
    }, async value => {
      const gapText = resText(S.gapResidue);
      const gapRow = value.user.rows.find(row => row.residue === gapText);
      assert.ok(gapRow, `the gap residue ${gapText} is not a user row`);
      const apiGap = value.user.api.rows.find(row => row.index === gapRow.index);
      assert.ok((apiGap.reference_not_checked ?? []).includes("klifs_sites"));
      assert.equal(gapRow.modeledAttr, String(apiGap.modeled_basis));
      for (const row of value.user.rows) {
        const api = value.user.api.rows.find(item => item.index === row.index);
        assert.equal(row.modeledAttr, String(api.modeled_basis), `${row.residue} modeled_basis`);
      }
      assert.deepEqual(value.klifs.rows.map(row => row.residue), value.klifs.api.rows.map(row => resText(row.residue)));
      Object.assign(seen, { so1: value.so1, originRecord: value.originRecord, statements: value.statements,
        gapRow: { residue: gapRow.residue, numbering: gapRow.numbering, klifs: gapRow.klifs, modeledBasis: gapRow.modeledBasis },
        klifsRows: value.klifs.rows.map(row => row.residue) });
      return { so1: value.so1 === null ? null : "shown", statements: value.statements.map(item => item.id),
        gapRow: seen.gapRow, klifsRows: seen.klifsRows.length };
    });
    seen.texts = [await keepText(page, evidence, artifacts, "r3-repair-origin", testId(page, "mutation-repair-origin")),
      await keepText(page, evidence, artifacts, "r3-repair-statements", testId(page, "mutation-repair-statements"))];
  });
  await rec.part("r3-report", ["r3-detail"], async () => {
    seen.report = await rec.step("r3-03", "보고서 만들기 for the set on the repaired structure: saved (201); the format is " +
      "mutation_candidates_markdown@3 with its 구조 출처 section", async () => {
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 120000 });
      await testId(page, "mutation-report").click();
      const response = await posted;
      const body = await response.json();
      await testId(page, "mutation-report-done").waitFor({ timeout: 60000 });
      return { status: response.status(), handle: body.handle,
        saved: await readApi(page, `/runs/${run}/reports/selected?handle=${enc(body.handle)}`) };
    }, async value => {
      assert.equal(value.status, 201);
      assert.equal(value.saved.manifest.render_version, "mutation_candidates_markdown@3");
      return value.handle;
    });
  });
  await rec.part("r10-jev", ["r3-m20"], async () => {
    const before = dispatchTotal(ctx.input["runs-dir"]);
    const shown = await rec.step("r10-01", "지식·보고서 JEV 판정: kind 변이 후보, the repaired set (보완 구조 mark), two candidates, " +
      "보낼 내용 만들기: the preview and the approval area show JW1 as the server gives it; the body does not say the " +
      "structure was repaired; the confirmation box and the send button are NOT touched (no send)", async () => {
      await openKnowledge(page);
      await jt(page, "jev-kind-mutation").check();
      const radio = jev(page).locator(`input[data-testid="jev-source"]${attr("data-jev-source", seen.set)}`);
      await radio.waitFor({ timeout: 30000 });
      const mark = await jev(page).locator(`label${attr("data-jev-source", seen.set)} [data-testid="jev-source-repaired"]`).count();
      await radio.check();
      await waitFor(page, async () => await jarea(page, "candidates").getAttribute("data-state") === "ready" &&
        await jt(page, "jev-candidates").count() === 1 ? true : null, "candidate rows", 30000);
      const boxes = jev(page).locator('input[data-testid="jev-candidate"]');
      for (const index of [0, 1]) await boxes.nth(index).check();
      const since = Date.now();
      await jt(page, "jev-build").click();
      const command = await waitApi(page, log, since, entry => entry.path === `/api/runs/${run}/commands` &&
        entry.request?.tool === "build_jev_projection", "projection command");
      const preview = await waitApi(page, log, since, entry => entry.path === `/api/runs/${run}/jev/preview`, "preview read");
      await jt(page, "jev-preview-repair-warning").waitFor({ timeout: 30000 });
      await jt(page, "jev-approval-repair-warning").waitFor({ timeout: 30000 });
      const read = node => node.evaluate(item => ({ id: item.getAttribute("data-statement"),
        text: item.textContent.replace(/\s+/g, " ").trim() }));
      const body = await jt(page, "jev-preview-body").textContent();
      return { mark, command: command.json, preview: preview.json, previewWarning: await read(jt(page, "jev-preview-repair-warning")),
        approvalWarning: await read(jt(page, "jev-approval-repair-warning")), body,
        confirmChecked: await jt(page, "jev-confirm").isChecked() };
    }, async value => {
      assert.equal(value.mark, 1, "the repaired set carries no mark in the JEV sources");
      assert.equal(value.command.ok, true);
      assert.deepEqual(value.previewWarning, value.preview.repair_warning);
      assert.deepEqual(value.approvalWarning, value.preview.repair_warning);
      assert.equal(value.body, value.preview.body, "the shown body differs from the server preview body");
      assert.equal(value.confirmChecked, false);
      return { previewWarning: value.previewWarning, approvalWarning: value.approvalWarning,
        bodyMentions: BODY_FORBIDDEN.filter(word => value.body.includes(word)), bodySha256: sha(Buffer.from(value.body)),
        bodyBytes: Buffer.byteLength(value.body), projection: value.command.handle.handle };
    });
    Object.assign(r10, shown);
    r10.texts = [await keepText(page, evidence, artifacts, "r10-jev-approval", jarea(page, "approval"))];
    const sends = await readApi(page, `/runs/${run}/jev/sends`);
    r10.sends = Array.isArray(sends) ? sends.length : (sends.rows ?? sends.sends ?? []).length;
    r10.dispatchAdded = dispatchTotal(ctx.input["runs-dir"]) - before;
    assert.equal(r10.sends, 0, "a send was recorded");
    assert.equal(r10.dispatchAdded, 0, "a dispatch event was recorded");
  });
  await rec.part("r10-loop", ["r3-m20"], async () => {
    const before = dispatchTotal(ctx.input["runs-dir"]);
    const phenol = await rec.step("r10-03", "리간드 설계·탐색 도킹: import the LABELED SYNTHETIC phenol SDF (the protein loop's " +
      "computation inputs need a 3D ligand; nothing is docked here)", () => importLigandSdf(page, run, plan.phenol.path),
    async handle => handle);
    const loop = await rec.step("r10-04", "단백질 공학 JEV 루프 (단백질): the repaired set, a pool of its first two candidates, " +
      "탐색형, loop seed and cap 1, the computation inputs; 루프 만들기; consent on (run-level switch); 보낼 내용 만들기: the " +
      "loop preview and the approval area show JW1 as the server gives it; the confirmation box and the send button are NOT " +
      "touched (no send)", async () => {
      await openLoopArea(page);
      const radio = lp(page).locator(`input[data-testid="jev-loop-source"]${attr("data-jev-loop-source", seen.set)}`);
      await radio.waitFor({ timeout: 30000 });
      await radio.check();
      await waitFor(page, async () => await lpt(page, "jev-loop-candidates").count() === 1 ? true : null, "loop rows", 30000);
      const keys = (await lp(page).locator("tr[data-jev-loop-candidate-row]").evaluateAll(items =>
        items.map(item => item.getAttribute("data-jev-loop-candidate-row")))).slice(0, 2);
      for (const key of keys)
        await lp(page).locator(`input[data-testid="jev-loop-candidate"]${attr("data-jev-loop-candidate", key)}`).check();
      await lpt(page, "jev-loop-goal-explore").check();
      await loopFill(page, "jev-loop-seed", "31");
      await loopFill(page, "jev-loop-iteration-cap", "1");
      await loopProteinSetup(page, phenol, plan.docking);
      await waitFor(page, async () => await lpt(page, "jev-loop-create").isEnabled() ? true : null, "create enabled", 15000);
      let since = Date.now();
      await lpt(page, "jev-loop-create").click();
      const created = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev_loops`, "loop created", 120000);
      await waitFor(page, async () => await lpt(page, "jev-loop-record").getAttribute("data-loop-id") === created.json?.loop_id
        ? true : null, "loop opened", 30000);
      if (await lpt(page, "jev-loop-consent-label").getAttribute("data-consent") !== "on") {
        since = Date.now();
        await lpt(page, "jev-loop-consent").click();
        await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev/consent`, "consent answer", 30000);
        await waitFor(page, async () => await lpt(page, "jev-loop-consent-label").getAttribute("data-consent") === "on"
          ? true : null, "consent shown", 15000);
      }
      await waitFor(page, async () => await lpt(page, "jev-loop-build").isEnabled() ? true : null, "build enabled", 15000);
      since = Date.now();
      await lpt(page, "jev-loop-build").click();
      const command = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/commands` &&
        item.request?.tool === "build_jev_loop_projection", "loop projection command", 120000);
      const preview = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev/preview`, "loop preview", 60000);
      await lpt(page, "jev-loop-preview-repair-warning").waitFor({ timeout: 30000 });
      await lpt(page, "jev-loop-approval-repair-warning").waitFor({ timeout: 30000 });
      const read = node => node.evaluate(item => ({ id: item.getAttribute("data-statement"),
        text: item.textContent.replace(/\s+/g, " ").trim() }));
      return { created: created.json, status: created.status, command: command.json, preview: preview.json,
        previewWarning: await read(lpt(page, "jev-loop-preview-repair-warning")),
        approvalWarning: await read(lpt(page, "jev-loop-approval-repair-warning")),
        body: await lpt(page, "jev-loop-preview-body").textContent(), confirmChecked: await lpt(page, "jev-loop-confirm").isChecked() };
    }, async value => {
      assert.equal(value.status, 200, JSON.stringify(value.created).slice(0, 400));
      assert.equal(value.command.ok, true, JSON.stringify(value.command).slice(0, 400));
      assert.deepEqual(value.previewWarning, value.preview.repair_warning);
      assert.deepEqual(value.approvalWarning, value.preview.repair_warning);
      assert.equal(value.body, value.preview.body);
      assert.equal(value.confirmChecked, false);
      return { loopId: value.created.loop_id, previewWarning: value.previewWarning, approvalWarning: value.approvalWarning,
        bodyMentions: BODY_FORBIDDEN.filter(word => value.body.includes(word)), bodySha256: sha(Buffer.from(value.body)) };
    });
    r10.loop = loop;
    r10.texts = [...(r10.texts ?? []), await keepText(page, evidence, artifacts, "r10-loop-approval",
      lp(page).locator('[data-testid="jev-loop-approval-repair-warning"]'))];
    r10.loopDispatchAdded = dispatchTotal(ctx.input["runs-dir"]) - before;
    assert.equal(r10.loopDispatchAdded, 0, "a dispatch event was recorded");
  });
  await rec.part("r10-m23", ["r3-m20"], async () => {
    const m23 = await rec.step("r10-02", "단백질 공학 서열 GA: the candidate-set choice of the repaired set ends with ' · 보완 " +
      "구조' (screen display only; the M23 report is unchanged)", async () => {
      await enterTab(page, TAB.protein);
      const select = page.locator('#mw-app-panel-protein [data-testid="sequence-ga-panel"] [data-testid="sequence-ga-candidate-set"]');
      await select.waitFor({ timeout: 30000 });
      const option = await waitFor(page, async () => (await selectOptions(select)).find(item => item.value === seen.set) ?? null,
        "M23 set option", 60000);
      return option;
    }, async option => ({ text: option.text, repaired: option.text.endsWith(REPAIRED_SUFFIX) }));
    r10.m23Option = m23.text;
    r10.m23Repaired = m23.repaired;
    assert.equal(m23.repaired, true);
  });
  await rec.part("r6-viewer", [], async () => {
    evidence.observed.viewer = await rec.step("r6-01", "구조 분석: no structure select of the tab offers the repaired structure and " +
      "the viewer does not show it (spec 5.2: the viewer has no path to a repaired structure)", async () => {
      await enterTab(page, TAB.structure);
      const values = await page.locator("#mw-app-panel-structure select option").evaluateAll(items => items.map(item => item.value));
      const view = await snapshot(page);
      return { selects: await page.locator("#mw-app-panel-structure select").count(), values, view };
    }, async value => ({ selects: value.selects, optionsWithRepaired: value.values.filter(item => item === S.repaired).length,
      optionsWithPrepared: value.values.filter(item => item === S.prepared).length,
      viewerSource: value.view?.sourceHandle ?? null, repaired: S.repaired }));
  });
}

async function modeR4a(ctx) {
  const { page, plan, rec, evidence, artifacts } = ctx;
  const P = plan.r4a;
  const seen = evidence.observed.r4a = {};
  await rec.part("r4a-repair", [], async () => {
    const made = await rec.step("r4a-01", "구조 분석: 새 run, choose the 1HSG file, 구조 불러오기, 전처리 strip_all", async () => {
      const run = await newRun(page);
      const loaded = await uploadLoad(page, plan.input.path);
      const prepared = await prepareManual(page, plan.waters);
      return { run, loaded: loaded.handle, prepared: prepared.prepared };
    }, async value => {
      assert.equal(fileRecord(plan.input.path).sha256, plan.input.sha256);
      return value;
    });
    Object.assign(seen, made);
    evidence.run = made.run;
    const job = await repairThroughScreen(ctx, "r4a-02", seen.prepared, seen.run);
    Object.assign(seen, { record: job.record, repaired: job.repaired, repairJob: job });
    await rec.step("r4a-03", "Open the record: the shown values equal the stored record", async () =>
      recordMatches(page, seen.run, seen.record, rt(page, "repair-open-new")), async value => ({ counts: value.shown.residues }));
    seen.panelText = await keepText(page, evidence, artifacts, "r4a-repair-panel", rpanel(page));
  });
  await rec.part("r4a-m20", ["r4a-repair"], async () => {
    const made = await rec.step("r4a-04", "변이 후보: the repaired structure (badge), 직접 선택 the plan's residue, 허용 잔기 only " +
      "the plan's code; 후보 만들기", async () => {
      await openReady(page);
      await chooseStructure(page, seen.repaired);
      await setCheck(page, "mutation-source-user", true);
      await pickResidueAt(page, "user", P.residue);
      await testId(page, "mutation-allowed-none").click();
      await testId(page, "mutation-allowed").getByRole("checkbox", { name: `허용 잔기 ${P.allowed}`, exact: true }).check();
      return create(page, seen.run);
    }, async value => {
      assert.equal(value.ok, true, JSON.stringify(value.body).slice(0, 600));
      assert.equal(value.args.structure, seen.repaired);
      return { set: value.handle };
    });
    seen.set = made.set;
  });
  await rec.part("r4a-m21", ["r4a-m20"], async () => {
    const model = await rec.step("r4a-05", `변이 구조 모델링 on candidate 0; seed ${P.model.seed}, cutoff ${P.model.cutoff} Å, both ` +
      `confirmations, timeout ${P.model.timeout} s; 모델링 작업 제출 → 작업 시작: the real PDBFixer + OpenMM job finishes within ` +
      "the limit", async () => {
      await panel(page).locator('[data-testid="mutation-candidate-model"][data-candidate-index="0"]').click();
      await mt(page, "mutation-model-candidate").waitFor({ timeout: 15000 });
      const requestOrigin = await mt(page, "mutation-model-request-repair-origin").count();
      await mt(page, "mutation-model-seed").fill(P.model.seed);
      await mt(page, "mutation-model-confirm-selection").check();
      await mt(page, "mutation-model-confirm-hydrogen").check();
      await mt(page, "mutation-model-cutoff").fill(P.model.cutoff);
      await mt(page, "mutation-model-timeout").fill(P.model.timeout);
      return { ...await runModelJob(page, seen.run, (Number(P.model.timeout) + 300) * 1000), requestOrigin };
    }, async value => {
      assert.equal(value.request.protocol_id, MODEL_PROTOCOL);
      assert.equal(value.request.timeout_s, Number(P.model.timeout));
      assert.equal(value.request.args.candidate_set, seen.set);
      assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
      const handle = value.job.artifacts?.mutation_model;
      assert.match(handle ?? "", /\/mutation_model\//);
      return { handle, jobId: value.jobId, status: value.job.status, timeoutS: value.request.timeout_s,
        requestOrigin: value.requestOrigin, phases: value.phases };
    });
    seen.model = model.handle;
    seen.modelJob = { status: model.status, timeoutS: model.timeoutS, jobId: model.jobId, phases: model.phases };
    await rec.step("r4a-06", "Open the model: SO1 with the record on the model (보완 기록 열기)", async () => {
      await waitListReady(page);
      await openModel(page, seen.model);
      const origin = mt(page, "mutation-model-repair-origin");
      await origin.waitFor({ timeout: 30000 });
      return { so1: clean(await origin.locator('p[data-statement="SO1"]').innerText()),
        record: await origin.getAttribute("data-repair-record") };
    }, async value => {
      seen.modelSo1 = value.so1;
      seen.modelOriginRecord = value.record;
      assert.equal(value.record, seen.record);
      return { record: value.record };
    });
    seen.texts = [await keepText(page, evidence, artifacts, "r4a-model-origin", mt(page, "mutation-model-repair-origin"))];
  });
  await rec.part("r4a-model-report", ["r4a-m21"], async () => {
    seen.modelReport = await rec.step("r4a-07", "보고서 만들기 for the model: saved (201) as mutation_model_markdown@2", async () => {
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${seen.run}/method_reports`, { timeout: 120000 });
      await mt(page, "mutation-model-report").click();
      const response = await posted;
      const body = await response.json();
      await mt(page, "mutation-model-report-done").waitFor({ timeout: 60000 });
      return { status: response.status(), handle: body.handle,
        saved: await readApi(page, `/runs/${seen.run}/reports/selected?handle=${enc(body.handle)}`) };
    }, async value => {
      assert.equal(value.status, 201);
      assert.equal(value.saved.manifest.render_version, "mutation_model_markdown@2");
      return value.handle;
    });
  });
  await rec.part("r4a-docking", ["r4a-m21"], async () => {
    const docking = seen.docking = {};
    const phenol = await rec.step("r4a-08", "리간드 설계·탐색 도킹: import the LABELED SYNTHETIC phenol SDF (a mechanical path " +
      "check, not a biological pose)", () => importLigandSdf(page, seen.run, plan.phenol.path), async handle => {
      const meta = await readApi(page, `/runs/${seen.run}/objects/meta?handle=${enc(handle)}`);
      assert.equal(meta.summary?.sha256, plan.phenol.sha256, "imported SDF bytes differ from the file");
      return handle;
    });
    const submitted = await rec.step("r4a-09", "단백질 공학: open the model, 같은 조건 도킹 (3D SDF, 리간드 범위 + margin, the docking " +
      "values, the acknowledgements and the 2-unit confirmation) → approve / continue through the screen until both real " +
      "qvina jobs end", async () => {
      await enterTab(page, TAB.protein);
      await mpanel(page).waitFor({ timeout: 15000 });
      await waitListReady(page);
      await openModel(page, seen.model);
      await mt(page, "mutation-model-pair-prereq-refresh").click();
      await mpanel(page).locator('label[data-pair-ligand-source="sdf"] input').check();
      await waitFor(page, async () => await mt(page, "mutation-model-pair-sdf").locator(`option${attr("value", phenol)}`).count()
        ? true : null, "phenol SDF offered", 30000);
      await fillPair(page, phenol, P.docking);
      const sent = await submitPair(page, seen.run);
      const refused = sent.responses.filter(item => item.status !== 200);
      if (refused.length) return { refused: refused.map(item => item.body), sent };
      return { sent, driven: await drivePair(page, sent.responses.map(item => item.body.job_id)) };
    }, async value => {
      if (value.refused) {
        const text = JSON.stringify(value.refused);
        if (/receptor.*atom|atom.*limit/i.test(text)) return { notObserved: "receptor_atom_limit", refused: value.refused };
        throw new Error(`docking refused: ${text.slice(0, 400)}`);
      }
      for (const side of SIDES) assert.equal(value.driven.jobs[side].status, "done", JSON.stringify(value.driven.jobs));
      return { jobs: Object.fromEntries(SIDES.map(side => [side, value.driven.jobs[side].status])) };
    });
    if (submitted.notObserved) { docking.notObserved = submitted.notObserved; return; }
    docking.jobs = submitted.jobs;
    const pairs = await readApi(page, `/runs/${seen.run}/mutation_models/${enc(seen.model)}/docking_pairs`);
    const result = pairs.pairs.map(item => item.sides.mutant.result_handle).find(Boolean);
    assert.ok(result, "no mutant-side docking result");
    docking.result = result;
    const shown = await rec.step("r4a-10", "리간드 설계·탐색 도킹 결과: open the mutant-side result: SO1 with the record " +
      "(보완 구조 badge in the list); 보고서 만들기: saved as ligand_docking_markdown@2", async () => {
      await enterTab(page, TAB.ligand);
      const dock = page.locator('#mw-app-panel-ligand [data-testid="docking-panel"]');
      await dock.waitFor({ timeout: 15000 });
      const label = dock.locator(`label${attr("data-docking-result", result)}`);
      await label.waitFor({ timeout: 60000 });
      const badge = await label.locator('[data-testid="docking-result-repaired"]').count();
      await label.locator("input").check();
      const origin = dock.locator('[data-testid="docking-repair-origin"]');
      await origin.waitFor({ timeout: 60000 });
      const so1 = clean(await origin.locator('p[data-statement="SO1"]').innerText());
      const record = await origin.getAttribute("data-repair-record");
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${seen.run}/method_reports`, { timeout: 120000 });
      await dock.locator('[data-testid="docking-report"]').click();
      const response = await posted;
      const body = await response.json();
      await dock.locator('[data-testid="docking-report-done"]').waitFor({ timeout: 60000 });
      const saved = await readApi(page, `/runs/${seen.run}/reports/selected?handle=${enc(body.handle)}`);
      const text = await keepText(page, evidence, artifacts, "r4a-docking-origin", origin);
      return { badge, so1, record, status: response.status(), handle: body.handle, saved, text };
    }, async value => {
      assert.equal(value.badge, 1);
      assert.equal(value.record, seen.record);
      assert.equal(value.status, 201);
      assert.equal(value.saved.manifest.render_version, "ligand_docking_markdown@2");
      return { so1: value.so1, report: value.handle };
    });
    Object.assign(docking, shown);
  });
}

async function modeR8(ctx) {
  const { page, plan, rec, evidence, artifacts } = ctx;
  const run = plan.run;
  const seen = evidence.observed.r8 = { run, record: plan.r8.record };
  evidence.run = run;
  await rec.part("r8-screen", [], async () => {
    await rec.step("r8-01", "Open the 1RNH run (its address): the page reopens that run", async () => {
      await waitForBoot(page);
      await waitFor(page, async () => await globalRun(page) === run, "the plan's run", 30000);
      return { run };
    }, async value => value);
    const shown = await rec.step("r8-02", "구조 보완: open the stored record (the list radio): the replaced-residue table shows the " +
      "three MSE→MET rows (original and new 7 fields, SE→SD, HETATM→ATOM) and RP5 is among the limitation sentences", async () => {
      await openRepair(page);
      const opener = rpanel(page).locator(`input[data-testid="repair-record"]${attr("data-repair-record", plan.r8.record)}`);
      const { shown: view } = await recordMatches(page, run, plan.r8.record, opener);
      return view;
    }, async view => ({ replacedRows: view.replaced, rows: view.replacedRows, rp5Shown: view.limitations.includes(plan.r8.rp5) }));
    Object.assign(seen, shown);
    seen.text = await keepText(page, evidence, artifacts, "r8-repair-panel", rpanel(page));
  });
}

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const plan = input.planData;
  const evidence = { schema: "m29_harness_evidence@1", mode: input.mode, run: plan.run ?? null, parts: {}, observed: {},
    texts: {}, planSha256: sha(fs.readFileSync(input.plan)), startedAt: new Date().toISOString() };
  const session = await launchOffscreen({ url: input.url, artifacts: input.artifacts, interactive: false });
  const log = requestLog(session.page);
  const rec = recorder(session, evidence);
  const ctx = { ...session, input, plan, rec, evidence, log, state: {} };
  const dispatchedBefore = dispatchTotal(input["runs-dir"]);
  let error = null;
  let proof = null;
  try {
    proof = await offscreenProof(session.app, session.page);
    await waitForBoot(session.page);
    await ({ r1: modeR1, r3: modeR3, r4a: modeR4a, r8: modeR8 })[input.mode](ctx);
  } catch (caught) {
    error = caught;
  } finally {
    try { proof = { ...await offscreenProof(session.app, session.page), atStart: proof }; } catch { /* keep the start proof */ }
    await session.close();
  }
  const parts = Object.fromEntries(Object.entries(evidence.parts).map(([name, value]) => [name, value.status]));
  const dispatched = dispatchTotal(input["runs-dir"]) - dispatchedBefore;
  const complete = offscreenComplete(proof);
  const posts = log.api.map(entry => entry.path.replace(/\/runs\/run_[0-9a-f]+/, "/runs/<run>"));
  const passed = !error && complete && proof.nonLoopbackRequests === 0 && dispatched === 0 &&
    Object.keys(parts).length > 0 && Object.values(parts).every(value => value === "pass");
  evidence.finishedAt = new Date().toISOString();
  evidence.error = error ? String(error.stack ?? error).slice(0, 4000) : null;
  evidence.requestCount = log.rows.length;
  evidence.postPaths = [...new Set(posts)].sort();
  fs.writeFileSync(path.join(input.artifacts, "structure-repair-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  const harness = Object.fromEntries(["structure-repair-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m29_harness_row@1", mode: input.mode, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", parts, run: evidence.run, observed: evidence.observed, texts: evidence.texts,
    buildId: buildId(), harness, offscreen: proof, offscreenComplete: complete,
    externalRequestCount: proof ? proof.nonLoopbackRequests : null, dispatchedDuringFlow: dispatched,
    postPaths: evidence.postPaths, error: evidence.error ? "see structure-repair-evidence.json" : null,
    evidenceFile: "structure-repair-evidence.json", stepsFile: path.basename(rec.file), artifacts: input.artifacts,
    startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, run: evidence.run, parts }) + "\n");
  if (error) process.stderr.write(`structure-repair-flow failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`structure-repair-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, MODES, BODY_FORBIDDEN, MODELED_NOT_CHECKED_TEXT };
