"use strict";

// M18 single-ligand docking (qvina) offscreen QA (spec §12.5). Real Electron offscreen page (isOffscreen, GPU/WebGL,
// paint). Every product mutation is a Playwright locator mouse/keyboard/file-chooser/select input; DOM .click() and
// product handlers are never called. Observation is read-only: data attributes and text of the page, renderer
// request/response events, Electron paint frames, downloaded bytes, GET reads of the loopback API, the stored
// object payloads in <runs-dir>/<run>/events.jsonl (read-only file reads) and the process table (`ps`/`lsof`).
// A labeled renderer-route fixture (held late response) is recorded in the ledger and never produces a value.
//
// Independent oracle: backend/tests/fixtures/docking/expected.json (T1, hand-derived): the ligand-range box of the
// public-derived ligand (hand reading of the SDF columns), the complex receptor's ligand instance (seven fields, atom
// and element counts), the M17 candidate id of the fixture enumeration, the expected rejection reasons; the spec §5.4
// selection rules of the limitation sentences; spec §4.5 contact rules (cutoff 4.0 Å, element pair kinds, order).
// The complex receptor minus its instance is atom-for-atom the plain receptor (fixture provenance), so the same seed
// and box must give byte-identical poses: a cross-check of instance removal against the plain receptor result.
//
// Modes (the full sequence: scripts/m18_offscreen_acceptance.py):
//   main         run A (구조 분석: 새 run + 1MQ4) → 리간드 탭 → receptor + 3D SDF imports → acknowledgement missing →
//                free docking (approval, real qvina) → summary, mode table, contacts, SDF downloads (= stored pose_sdf) →
//                report + 지식·보고서 list + downloads → complex receptor with one removed instance (instance_range box) →
//                real M17 inspection + enumeration → core-fixed docking of the fixture candidate → structure tab kept
//                mounted → run B: run switch with a held late response → rejections (planar SDF, implicit H, box over
//                40 Å on screen and in the worker) → cancel while qvina runs (worker and qvina processes gone) →
//                screen wording (no rank/best/improvement/affinity claims)
//   unavailable  backend started from a layout without the locked environments (runner): no-run and
//                capability-unavailable states show a reason only (no numbers, no controls, no docking requests)
// Zero-mode results: qvina does not produce zero modes for a valid input here; no input is forged to get one. The empty
// scientific result is covered by tests/docking.test.cjs (dockingPanelState) and the backend tests (recorded in the
// ledger as not observed).
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const { waitForViewer } = require("./normal-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const FIXTURES = path.join(REPO, "backend/tests/fixtures");
const DOCK = path.join(FIXTURES, "docking");
const STRUCTURE = path.join(FIXTURES, "public_1mq4.cif");
const RECEPTOR = path.join(FIXTURES, "chemical/prolif-vina-rec.pdb");
const PARENT = path.join(DOCK, "public-derived-parent-record0.sdf");
const COMPLEX = path.join(DOCK, "synthetic-complex-receptor-lig.pdb");
const PLANAR = path.join(DOCK, "synthetic-ligand-planar-z0.sdf");
const IMPLICIT = path.join(DOCK, "synthetic-ligand-implicit-h.sdf");
const BLOCKS_SMI = path.join(DOCK, "synthetic-docking-blocks.smi");
const EXPECTED = path.join(DOCK, "expected.json");
const M17_RESULT = path.join(DOCK, "m17-enumerate-result-record0-nmethyl.json");
const MODES = ["main", "unavailable"];
const TAB = "리간드 설계·탐색";
// Small values so a real qvina run takes seconds (the cancel case uses exhaustiveness 32 so qvina is still running).
const FAST = { seed: "42", exhaustiveness: "1", numModes: "3", energyRange: "3" };
const SLOW = { seed: "7", exhaustiveness: "32", numModes: "9", energyRange: "3" };
const CORE_CONFORMERS = "5";
const SITE_ATOM = 22; // N-methyl carbon of the public-derived parent (expected.json public_example_numbering)
const HOLD_LABEL = "QA held-response fixture (labeled renderer route; unchanged backend bytes released late)";
const UNAVAILABLE_LABEL = "labeled runtime layout without .deps (runner): capability worker_missing";
const PROVIDER_EVENT_TYPES = new Set(["egress", "egress_budget_settled", "viewer_dispatch_started"]);
const NO_RUN_REASON = "구조 분석 탭에서 run을 먼저 고르세요.";
const ACK_KEYS = ["keep_input_protonation", "tool_assigned_types_charges", "rigid_no_optimization"];
const CONTACT_CUTOFF_A = 4.0;
// spec §8/§9 and the handoff: no rank, best, optimum, improvement, binding strength or affinity claim on screen.
// "최적화" (a process: "no optimisation is done") is allowed; a line equal to a stored limitation sentence is exempt.
const FORBIDDEN = /순위|최고|최적(?!화)|개선|결합\s*강도|친화|ΔΔG|합성\s*가능|\brank|\bbest|optimal|improv|stronger|affinity/gi;
const PROCESS_PATTERNS = ["qvina2", "docking_worker.py", "guardian.py"];

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const shortHandle = handle => handle.split("/").at(-1).slice(0, 12);
const attr = (name, value) => `[${name}="${String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"]`;

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, "fixture-label": null, "runs-dir": null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2);
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode) || (value.mode === "main" && !value["runs-dir"])) throw new Error(
    `Usage: docking-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> [--url http://127.0.0.1:3000] ` +
    "[--runs-dir <backend MW_RUNS_DIR> (main: stored pose bytes)] [--fixture-label <runtime layout label>]. main needs " +
    "the locked docking environments; unavailable needs a backend without them and a fresh runs root. Full sequence: " +
    "scripts/m18_offscreen_acceptance.py.");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  value.artifacts = path.resolve(value.artifacts);
  if (value["runs-dir"]) value["runs-dir"] = path.resolve(value["runs-dir"]);
  value.url = new URL("/", value.url).toString();
  return value;
}

// ------------------------------------------------------------------ independent oracle
function oracle() {
  const expected = JSON.parse(fs.readFileSync(EXPECTED, "utf8"));
  const m17 = JSON.parse(fs.readFileSync(M17_RESULT, "utf8"));
  const box = expected.public_example_box;
  const receptors = expected.receptor_fixtures;
  return {
    files: [EXPECTED, M17_RESULT].map(fileRecord),
    box: { center: box.center_A, size: box.size_A, margin: box.margin_A },
    instance: receptors.instance,
    instanceAtoms: receptors["synthetic-complex-receptor-lig.pdb"].instance_atoms,
    instanceElements: receptors["synthetic-complex-receptor-lig.pdb"].instance_element_counts,
    candidateId: expected.m17_candidate.fixed_candidate_id,
    candidateIds: m17.candidates.map(item => item.id),
    candidateRetained: m17.candidates.find(item => item.id === expected.m17_candidate.fixed_candidate_id).retained_parent_atoms,
    planarReason: expected.ligand_fixtures["synthetic-ligand-planar-z0.sdf"].expected_reason,
    implicitReason: expected.ligand_fixtures["synthetic-ligand-implicit-h.sdf"].expected_reason,
  };
}

/** Decimal-string ROUND_HALF_UP (ties away from zero), written independently of the product's helper. */
function halfUp(value, places) {
  let text = String(value);
  const exp = /^(-?)(\d+)(?:\.(\d+))?e([+-]\d+)$/.exec(text);
  if (exp) { // expand an exponent form into plain digits
    const [, sign, int, frac = "", power] = exp;
    const digits = int + frac, point = int.length + Number(power);
    text = sign + (point <= 0 ? `0.${"0".repeat(-point)}${digits}` : point >= digits.length
      ? digits.padEnd(point, "0") : `${digits.slice(0, point)}.${digits.slice(point)}`);
  }
  const negative = text.startsWith("-");
  const [int, frac = ""] = text.replace("-", "").split(".");
  const kept = (int + frac.padEnd(places, "0").slice(0, places)).split("").map(Number);
  if ((frac[places] ?? "0") >= "5") {
    let i = kept.length - 1;
    while (i >= 0) { if (kept[i] === 9) { kept[i] = 0; i -= 1; } else { kept[i] += 1; break; } }
    if (i < 0) kept.unshift(1);
  }
  const all = kept.join("");
  const whole = all.slice(0, all.length - places).replace(/^0+(?=\d)/, "") || "0";
  const out = places ? `${whole}.${all.slice(all.length - places)}` : whole;
  return negative && /[1-9]/.test(out) ? `-${out}` : out;
}
const dist2 = value => `${halfUp(value, 2)} Å`;
const triple = values => `(${values.map(value => halfUp(value, 2)).join(", ")}) Å`;

/** spec §5.4 selection rules applied to the capability's eleven fixed sentences (independent of the stored list). */
function expectedLimitations(all, { mode, source, removed, unspecified }) {
  const pick = [1, 2, 3, 4, 5];
  if (mode === "free") pick.push(6);
  if (source === "candidate") pick.push(7);
  if (mode === "core_fixed") pick.push(8);
  if (removed) pick.push(9);
  if (source === "candidate" && mode === "free") pick.push(10);
  if ((unspecified ?? 0) > 0) pick.push(11);
  return pick.map(n => all[n - 1]);
}
/** spec §4.5 kind by element pair (M2 rule): both N/O polar, both C hydrophobic, else contact. */
function contactKind(a, b) {
  if (["N", "O"].includes(a) && ["N", "O"].includes(b)) return "polar_contact";
  if (a === "C" && b === "C") return "hydrophobic_contact";
  return "contact";
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
/** The stored docking_result@1 content: the object_created payload in the run's event log (read-only file read). */
function storedResult(runsDir, run, handle) {
  const file = path.join(runsDir, run, "events.jsonl");
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    if (!line.includes(handle)) continue;
    const event = JSON.parse(line);
    if (event.type === "object_created" && event.handle === handle)
      return JSON.parse(Buffer.from(event.payload_b64, "base64").toString("utf8"));
  }
  throw new Error(`no object_created event for ${handle}`);
}
/** Worker, guardian and qvina2 processes whose command or working directory lies under the runs folder. */
function jobProcesses(runsDir) {
  const ps = execFileSync("ps", ["-axo", "pid=,command="], { encoding: "utf8" });
  const found = [];
  for (const line of ps.split("\n")) {
    const trimmed = line.trim();
    if (!PROCESS_PATTERNS.some(item => trimmed.includes(item))) continue;
    const pid = trimmed.split(/\s+/, 1)[0];
    let cwd = "";
    try { cwd = execFileSync("lsof", ["-a", "-p", pid, "-d", "cwd", "-Fn"], { encoding: "utf8" }); } catch { /* exited */ }
    const dirs = cwd.split("\n").filter(item => item.startsWith("n")).map(item => item.slice(1));
    if (trimmed.includes(runsDir) || dirs.some(dir => dir === runsDir || dir.startsWith(`${runsDir}/`)))
      found.push({ pid: Number(pid), command: trimmed.slice(0, 300), cwd: dirs[0] ?? null });
  }
  return found;
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
  const file = path.join(artifacts, `docking-${input.mode}.jsonl`);
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
      const html = await page.evaluate(() => document.querySelector('[data-testid="docking-panel"]')?.outerHTML.slice(0, 120000) ?? "")
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

// ------------------------------------------------------------------ docking area (read-only helpers)
const dock = page => page.locator('#mw-app-panel-ligand [data-testid="docking-panel"]');
const dt = (page, id) => dock(page).locator(`[data-testid="${id}"]`);
const dockState = page => dock(page).getAttribute("data-docking-state", { timeout: 2000 }).catch(() => null);
const areaState = (page, area) => dock(page).locator(`[data-docking-area="${area}"]`).getAttribute("data-state", { timeout: 2000 })
  .catch(() => null);
const ligandPanel = page => page.locator('#mw-app-panel-ligand [data-testid="ligand-panel"]');
const lt = (page, id) => ligandPanel(page).locator(`[data-testid="${id}"]`);
async function openLigandTab(page) {
  await selectTab(page, TAB);
  await dock(page).waitFor({ timeout: 15000 });
  await ligandPanel(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => ["ready", "scientific_null", "failure", "unavailable"].includes(await dockState(page))
    && await areaState(page, "results") === "ready" ? true : null, "docking area settled", 60000);
}
async function panelText(page) { return dock(page).evaluate(node => node.innerText); }
/** Forbidden words on screen, line by line; a line equal to a stored limitation sentence is exempt, score names removed. */
function forbiddenWords(text, limitations, scoreLabels) {
  const found = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || limitations.includes(line)) continue;
    let checked = line;
    for (const label of scoreLabels) checked = checked.split(label).join("");
    for (const match of checked.matchAll(FORBIDDEN)) found.push({ word: match[0], line: line.slice(0, 200) });
  }
  return found;
}
async function startState(page) {
  const button = dt(page, "docking-start");
  return { enabled: await button.isEnabled(), title: await button.getAttribute("title"),
    blocked: clean(await dt(page, "docking-start-blocked").textContent({ timeout: 1000 }).catch(() => "")),
    errors: await dt(page, "docking-input-errors").locator("li").allTextContents().catch(() => []) };
}
/** Choose files through the file chooser and click 가져오기; returns the created handles by kind (POST responses). */
async function importDocking(page, run, files, evidence) {
  for (const [slot, file] of Object.entries(files)) {
    const chooser = page.waitForEvent("filechooser", { timeout: 15000 });
    await dt(page, `docking-file-${slot}`).click();
    await (await chooser).setFiles(file);
    control(evidence, `docking-file-${slot}`, { file: path.basename(file) });
  }
  // new handles = the backend's import list after minus before (response bodies are not read: the renderer may
  // drop them once the list re-reads)
  const known = new Set((await readApi(page, `/runs/${run}/docking/prerequisites`)).imports.map(item => item.handle));
  const statuses = [];
  const listener = response => {
    if (response.request().method() === "POST" && new URL(response.url()).pathname === `/api/runs/${run}/chemical/imports`)
      statuses.push(response.status());
  };
  page.on("response", listener);
  try {
    await dt(page, "docking-import").click();
    control(evidence, "docking-import", { files: Object.keys(files) });
    await dt(page, "docking-import-done").waitFor({ timeout: 60000 });
    await waitFor(page, async () => statuses.length === Object.keys(files).length ? true : null, "import responses", 30000);
  } finally { page.off("response", listener); }
  for (const status of statuses) assert.equal(status, 201);
  const fresh = (await readApi(page, `/runs/${run}/docking/prerequisites`)).imports.filter(item => !known.has(item.handle));
  assert.equal(fresh.length, Object.keys(files).length, JSON.stringify(fresh));
  const handles = Object.fromEntries(fresh.map(row => [row.input_kind, row.handle]));
  // the prerequisite list is read again after an import: every new handle becomes an option
  await waitFor(page, async () => {
    for (const handle of Object.values(handles))
      if (!await dock(page).locator(`option${attr("value", handle)}`).count()) {
        // the option of a ligand_sdf import is shown only once the SDF source is chosen
        const prereq = await readApi(page, `/runs/${run}/docking/prerequisites`);
        if (!prereq.imports.some(item => item.handle === handle)) return null;
      }
    return true;
  }, "imports listed", 30000);
  return handles;
}
async function radio(page, selector) {
  const input = dock(page).locator(`${selector} input`);
  await input.waitFor({ timeout: 30000 });
  await input.check();
  return input;
}
async function fill(page, id, value) {
  const field = dt(page, id);
  await field.click();
  await field.fill(value);
}
/**
 * Fill the docking form by real input, in screen order. spec: { receptor, instance: "none" | residue, source: "sdf" |
 * "candidate", sdf | set+candidate+parent, mode, box: { source, margin? , center?, size? }, values, acks: [keys] }.
 */
async function fillForm(page, spec, evidence) {
  await dt(page, "docking-receptor").selectOption(spec.receptor);
  control(evidence, "docking-receptor", { handle: spec.receptor });
  await dt(page, "docking-model").waitFor({ timeout: 30000 });
  await dt(page, "docking-model").selectOption("1");
  control(evidence, "docking-model", { model: 1 });
  await dt(page, "docking-instances").waitFor({ timeout: 30000 });
  if (spec.instance === "none") await radio(page, '[data-testid="docking-instances"] label[data-docking-instance="none"]');
  else await radio(page, `[data-testid="docking-instances"] label${attr("data-docking-instance", JSON.stringify(spec.instance))}`);
  control(evidence, "docking-instance-radio", { instance: spec.instance });
  const conect = dt(page, "docking-connectivity").locator("label").filter({ hasText: "PDB CONECT" }).locator("input");
  await conect.check();
  control(evidence, "docking-connectivity-radio", { kind: "pdb_conect" });
  await radio(page, `label[data-docking-source="${spec.source}"]`);
  control(evidence, "docking-source-radio", { source: spec.source });
  if (spec.source === "sdf") {
    await dt(page, "docking-sdf").selectOption(spec.sdf);
    control(evidence, "docking-sdf", { handle: spec.sdf });
  } else {
    await dt(page, "docking-candidate-set").selectOption(spec.set);
    control(evidence, "docking-candidate-set", { handle: spec.set });
    await radio(page, `label${attr("data-docking-candidate", spec.candidate)}`);
    control(evidence, "docking-candidate-radio", { id: spec.candidate });
    await dt(page, "docking-parent-sdf").selectOption(spec.parent);
    control(evidence, "docking-parent-sdf", { handle: spec.parent });
  }
  await radio(page, `label[data-docking-mode="${spec.mode}"]`);
  control(evidence, "docking-mode-radio", { mode: spec.mode });
  await radio(page, `label[data-docking-box="${spec.box.source}"]`);
  control(evidence, "docking-box-radio", { source: spec.box.source });
  if (spec.box.source === "manual") {
    for (const [i, axis] of ["x", "y", "z"].entries()) {
      await fill(page, `docking-center-${axis}`, spec.box.center[i]);
      await fill(page, `docking-size-${axis}`, spec.box.size[i]);
    }
    control(evidence, "docking-manual-box", { center: spec.box.center, size: spec.box.size });
  } else {
    await fill(page, "docking-margin", spec.box.margin);
    control(evidence, "docking-margin", { value: spec.box.margin });
  }
  const values = spec.values;
  await fill(page, "docking-seed", values.seed);
  await fill(page, "docking-exhaustiveness", values.exhaustiveness);
  await fill(page, "docking-num-modes", values.numModes);
  await fill(page, "docking-energy-range", values.energyRange);
  for (const id of ["docking-seed", "docking-exhaustiveness", "docking-num-modes", "docking-energy-range"]) control(evidence, id, {});
  if (spec.mode === "core_fixed") { await fill(page, "docking-conformers", values.conformers); control(evidence, "docking-conformers", {}); }
  for (const key of ACK_KEYS) {
    const box = dock(page).locator(`label[data-docking-ack="${key}"] input`);
    if (spec.acks.includes(key)) await box.check(); else await box.uncheck();
    control(evidence, `docking-ack-${key}`, { checked: spec.acks.includes(key) });
  }
}
async function jobPhase(page) {
  const job = dt(page, "docking-job");
  if (!await job.count()) return null;
  return { phase: await job.getAttribute("data-docking-job-phase"), status: await job.getAttribute("data-docking-job-status"),
    id: await job.getAttribute("data-docking-job-id") };
}
async function budgetUsed(page, run) { return (await readApi(page, `/runs/${run}/budget`)).expensive_calls; }
/**
 * Click 도킹 작업 시작 (real input); approve through 비싼 계산 승인 when asked, then 작업 시작; wait for the job to
 * leave the active states (or, with `until: "running"`, until it runs). Returns the phases, the backend job and handle.
 */
async function runDockingJob(page, run, evidence, { until = "final" } = {}) {
  const phases = [];
  const before = await budgetUsed(page, run);
  const previousJob = (await jobPhase(page))?.id ?? null; // a finished job of this mount stays shown until replaced
  await dt(page, "docking-start").click();
  control(evidence, "docking-start", { clicked: true });
  const settled = async () => {
    const value = await jobPhase(page);
    if (!value || value.id === previousJob) return null;
    if (["running", "done", "failed", "cancelled"].includes(value.phase)) return value;
    if (value.phase === "awaiting_approval" && await dt(page, "docking-job-approve").isEnabled().catch(() => false)) return value;
    if (value.phase === "saved" && await dt(page, "docking-job-start").isEnabled().catch(() => false)) return value;
    return null;
  };
  const first = await waitFor(page, settled, "docking job submitted", 120000);
  phases.push(first.phase);
  let approved = false;
  if (first.phase === "awaiting_approval") {
    await dt(page, "docking-job-approve").click();
    approved = true;
    const noticed = await waitFor(page, async () => { const value = await settled(); return value?.phase === "saved" ? value : null; },
      "approval recorded (job saved)", 30000);
    phases.push(noticed.phase);
    control(evidence, "docking-job-approve", { phaseAfter: noticed.phase,
      notice: clean(await dt(page, "docking-notice").textContent().catch(() => "")) });
  }
  if ((await jobPhase(page)).phase === "saved" && await dt(page, "docking-job-start").isEnabled().catch(() => false)) {
    await dt(page, "docking-job-start").click();
    control(evidence, "docking-job-start", { clicked: true });
  }
  const finals = until === "running" ? ["running", "done", "failed", "cancelled"] : ["done", "failed", "cancelled"];
  const done = await waitFor(page, async () => {
    const value = await jobPhase(page);
    if (value && value.phase !== phases.at(-1)) phases.push(value.phase);
    return value && finals.includes(value.phase) ? value : null;
  }, `docking job ${until}`, 600000);
  const job = await readApi(page, `/runs/${run}/jobs/${enc(done.id)}`);
  const handle = job.artifacts?.docking_result ?? null;
  if (done.phase === "done") await dt(page, "docking-result-notice").waitFor({ timeout: 30000 });
  return { phases, approved, job, handle, budgetBefore: before, budgetAfter: await budgetUsed(page, run),
    resultNotice: clean(await dt(page, "docking-result-notice").textContent({ timeout: 1000 }).catch(() => "")),
    state: await dockState(page) };
}
async function openResult(page, handle, evidence) {
  await waitFor(page, async () => await areaState(page, "results") === "ready" ? true : null, "results list", 30000);
  await radio(page, `label${attr("data-docking-result", handle)}`);
  control(evidence, "docking-result-radio", { handle });
  await dock(page).locator(`[data-testid="docking-result"]${attr("data-docking-result-handle", handle)}`).waitFor({ timeout: 30000 });
}
async function resultView(page) {
  const view = dt(page, "docking-result");
  const summary = await view.locator('[data-testid="docking-summary"] .mw-ligand-fact').evaluateAll(items => items.map(item =>
    [item.querySelector("dt").textContent.trim(), item.querySelector("dd").textContent.trim()]));
  const headers = await view.locator('[data-testid="docking-modes"] thead th').allTextContents().catch(() => []);
  const rows = await view.locator('[data-testid="docking-modes"] tbody tr[data-mode]').evaluateAll(items => items.map(item => ({
    mode: Number(item.getAttribute("data-mode")), cells: [...item.querySelectorAll("td")].map(cell => cell.textContent.trim()) })));
  return { summary: Object.fromEntries(summary), headers, rows,
    caption: clean(await view.locator('[data-testid="docking-modes"] caption').textContent({ timeout: 1000 }).catch(() => "")),
    limitations: await view.locator('[data-testid="docking-limitations"] li').allTextContents(),
    mode: await view.getAttribute("data-docking-mode"), nullResult: await view.getAttribute("data-null-result") };
}
/** The displayed mode table equals the stored rows (stored values, decimal-string rounding, row names). */
function modeTableEquals(view, detail, stored) {
  const mode = stored.inputs.mode;
  assert.equal(view.rows.length, stored.modes.length);
  assert.equal(detail.result.modes.length, stored.modes.length);
  stored.modes.forEach((row, i) => {
    const cells = view.rows[i].cells;
    assert.equal(view.rows[i].mode, row.mode);
    assert.equal(row.mode, i + 1);
    assert.equal(cells[0], mode === "core_fixed" ? `샘플 ${row.mode}(점수 오름차순 나열)` : `모드 ${row.mode}(엔진 출력 순서)`);
    assert.equal(cells[1], halfUp(row.score_kcal_mol, 1), `score of row ${row.mode}`);
    assert.equal(cells[2], String(row.contacts.length));
    assert.equal(detail.result.modes[i].contact_count, row.contacts.length);
    assert.equal(cells[3], dist2(row.min_heavy_atom_distance_A));
    assert.equal(cells[4], String(row.atoms_outside_box));
    if (mode === "core_fixed") {
      assert.equal(cells[5], row.core_max_deviation_A === null ? "해당 없음" : dist2(row.core_max_deviation_A));
      assert.equal(cells[6], String(row.conformer_index));
      assert.equal(row.engine_rmsd_lb_A, null);
    } else {
      assert.equal(cells[5], `${dist2(row.engine_rmsd_lb_A)} · ${dist2(row.engine_rmsd_ub_A)}`);
      assert.equal(row.conformer_index, null);
    }
  });
}
/** Stored contacts obey spec §4.5: heavy atoms only, distance ≤ 4.0 Å, element-pair kind, sorted by serial then site. */
function contactsFollowRules(stored) {
  for (const row of stored.modes) {
    const keys = row.contacts.map(item => [item.ligand_serial, item.receptor_atom.site_index]);
    for (let i = 1; i < keys.length; i++)
      assert.ok(keys[i - 1][0] < keys[i][0] || (keys[i - 1][0] === keys[i][0] && keys[i - 1][1] < keys[i][1]), "contact order");
    for (const item of row.contacts) {
      assert.ok(item.distance_A <= CONTACT_CUTOFF_A, `contact over cutoff: ${item.distance_A}`);
      assert.notEqual(item.ligand_element, "H");
      assert.notEqual(item.receptor_atom.element, "H");
      assert.equal(item.kind, contactKind(item.ligand_element, item.receptor_atom.element));
    }
  }
}
async function contactTable(page, mode) {
  const box = dock(page).locator(`[data-testid="docking-contacts"][data-mode="${mode}"]`);
  await box.locator(".mw-docking-contact-page").waitFor({ timeout: 30000 });
  const pageNode = box.locator(".mw-docking-contact-page");
  return { total: Number(await pageNode.getAttribute("data-total")), offset: Number(await pageNode.getAttribute("data-offset")),
    count: clean(await dt(page, "docking-contacts-count").textContent()),
    rows: await box.locator("tbody tr").evaluateAll(items => items.map(item => ({
      ligandSerial: Number(item.getAttribute("data-ligand-serial")), siteIndex: Number(item.getAttribute("data-site-index")),
      cells: [...item.querySelectorAll("td")].map(cell => cell.textContent.trim()) }))) };
}
const KIND_LABEL = { contact: "기타 접촉(contact)", polar_contact: "극성 접촉(polar_contact)",
  hydrophobic_contact: "소수성 접촉(hydrophobic_contact)" };
/** The displayed contact page equals the stored contact rows (first page). */
function contactsEqual(table, stored, mode) {
  const rows = stored.modes[mode - 1].contacts;
  assert.equal(table.total, rows.length);
  assert.equal(table.rows.length, Math.min(rows.length, 100));
  table.rows.forEach((shown, i) => {
    const row = rows[i];
    assert.equal(shown.ligandSerial, row.ligand_serial);
    assert.equal(shown.siteIndex, row.receptor_atom.site_index);
    assert.equal(shown.cells[0], `포즈 SDF ${row.ligand_serial} · ${row.ligand_element}` +
      (row.ligand_parent_serial === null ? "" : ` · 부모 SDF ${row.ligand_parent_serial}`));
    const res = row.receptor_atom.residue;
    assert.equal(shown.cells[1], `모델 ${res.model_number} · 체인 ${res.chain_auth} · ${res.resname} ${res.seq_auth}${res.icode} · ` +
      `${row.receptor_atom.atom_name}${row.receptor_atom.altloc ? ` (altloc ${row.receptor_atom.altloc})` : ""} · ` +
      `${row.receptor_atom.element} · site ${row.receptor_atom.site_index}`);
    assert.equal(shown.cells[2], dist2(row.distance_A));
    assert.equal(shown.cells[3], KIND_LABEL[row.kind]);
  });
  if (rows.length) assert.ok(table.count.includes(`기하 접촉 ${rows.length}개 중 1–${Math.min(rows.length, 100)}`), table.count);
}
/** Click a pose download; the bytes equal the stored pose_sdf (events.jsonl) and the backend route bytes. */
async function downloadPose(rec_, page, run, handle, stored, which) {
  const testid = which === "all" ? "docking-download-all" : `docking-download-${which}`;
  const route = which === "all" ? `/runs/${run}/docking/results/poses_sdf?handle=${enc(handle)}`
    : `/runs/${run}/docking/results/pose_sdf?handle=${enc(handle)}&mode=${which}`;
  const downloaded = await downloadByClick(rec_.app, dt(page, testid));
  const bytes = fs.readFileSync(downloaded.downloaded);
  const served = await readBytes(page, route);
  const want = which === "all"
    ? Buffer.from(stored.modes.map(row => `${row.pose_sdf}${row.pose_sdf.endsWith("\n") ? "" : "\n"}$$$$\n`).join(""), "utf8")
    : Buffer.from(stored.modes[which - 1].pose_sdf, "utf8");
  return { testid, route, bytes, served, want, filename: downloaded.filename, url: downloaded.url, path: downloaded.downloaded };
}

// ------------------------------------------------------------------ mode main
async function modeMain(session, input, rec_, evidence, log) {
  const { page } = session;
  const o = oracle();
  const runsDir = input["runs-dir"];
  evidence.inputs.push(...[STRUCTURE, RECEPTOR, PARENT, COMPLEX, PLANAR, IMPLICIT, BLOCKS_SMI].map(fileRecord), ...o.files);
  const capability = (await readApi(page, "/capabilities")).methods?.ligand_docking;
  assert.ok(capability?.available === true, `docking capability unavailable: ${JSON.stringify(capability)}`);
  evidence.capability = { available: capability.available, engine: capability.engine, pins: capability.pins };
  const scoreLabels = [capability.score_label, "qvina 점수(kcal/mol)"];
  const wording = [];
  const checkWording = async (where, limitations) => {
    const found = forbiddenWords(await panelText(page), limitations, scoreLabels);
    wording.push({ where, found });
    return found;
  };
  await waitForBoot(page);

  // ---- run A (structure tab), ligand tab
  const runA = await rec_.step("R01-run", ["D-run-create"], "구조 분석: click 새 run, choose public_1mq4.cif, 구조 불러오기", async () => {
    const run = await newRun(page);
    const structure = await uploadLoad(page, STRUCTURE);
    return { run, structure, state: await structureState(page) };
  }, async value => {
    assert.match(value.run, /^run_/);
    assert.equal(value.state.dom.shown, "true");
    return value;
  });
  evidence.runs.A = runA.run;
  const run = runA.run;
  const structureBefore = runA.state;
  await rec_.step("R02-ligand-tab", ["D-run-create", "D-structure-kept"], "Click 리간드 설계·탐색: the docking area uses the " +
    "global run (no run choice there); the structure tab stays mounted (hidden)", async () => {
    await openLigandTab(page);
    return { state: await dockState(page), run: await globalRun(page), structure: await structureState(page),
      capability: clean(await dt(page, "docking-capability").textContent()),
      results: clean(await dock(page).locator('[data-docking-area="results"]').textContent()),
      runChoices: await dock(page).locator("#run-choice, [data-testid*='run-choice']").count(),
      start: await startState(page), frame: clean(await dt(page, "docking-frame-note").textContent()) };
  }, async value => {
    assert.equal(value.state, "ready");
    assert.equal(value.run, run);
    assert.equal(value.runChoices, 0);
    assert.equal(value.structure.dom.present, true);
    assert.equal(value.structure.dom.shown, "false");
    assert.ok(value.structure.dom.canvases > 0, "Mol* canvas unmounted while the ligand tab is shown");
    assert.equal(value.structure.sessionId, structureBefore.sessionId);
    assert.ok(value.capability.startsWith("qvina · qvina_dock_ligand"), value.capability);
    assert.ok(value.results.includes("이 run에 도킹 결과가 없습니다."), value.results);
    assert.equal(value.start.enabled, false);
    assert.ok(value.frame.includes("같은 좌표계"), value.frame);
    return value;
  });

  // ---- ① imports: receptor + 3D SDF (file chooser)
  const imports = await rec_.step("I01-imports", ["D-imports"], "Choose prolif-vina-rec.pdb (수용체) and the public-derived " +
    "3D SDF (리간드) with the file chooser; click 가져오기", () => importDocking(page, run, { receptor: RECEPTOR, ligand: PARENT },
    evidence), async handles => {
    const prereq = await readApi(page, `/runs/${run}/docking/prerequisites`);
    assert.equal(prereq.import_counts.receptor, 1);
    assert.equal(prereq.import_counts.ligand_sdf, 1);
    for (const [kind, handle] of Object.entries(handles))
      assert.equal(prereq.imports.find(item => item.handle === handle)?.input_kind, kind);
    assert.equal(await dt(page, "docking-receptor").inputValue(), "", "a receptor was chosen automatically");
    return handles;
  });
  evidence.handles.imports = imports;
  const freeSpec = { receptor: imports.receptor, instance: "none", source: "sdf", sdf: imports.ligand_sdf, mode: "free",
    box: { source: "ligand_range", margin: String(o.box.margin) }, values: FAST, acks: ACK_KEYS };

  // ---- acknowledgement missing: start stays disabled
  await rec_.step("A01-ack-missing", ["D-ack-missing", "D-mode-compat"], "Fill the free-docking form (receptor, model 1, 없음, " +
    "PDB CONECT, 3D SDF, 자유 도킹, 리간드 범위+여백 8, seed 42, exhaustiveness 1, num_modes 3) with two of three " +
    "acknowledgements: 도킹 작업 시작 stays disabled (acknowledgement_missing); core-fixed is disabled for the SDF source",
  async () => {
    await fillForm(page, { ...freeSpec, acks: ACK_KEYS.slice(0, 2) }, evidence);
    const core = dock(page).locator('label[data-docking-mode="core_fixed"]');
    return { start: await startState(page), coreDisabled: await core.locator("input").isDisabled(),
      coreReason: await core.getAttribute("data-disabled-reason"),
      instanceBox: await dock(page).locator('label[data-docking-box="instance_range"]').getAttribute("data-disabled-reason") };
  }, async value => {
    assert.equal(value.start.enabled, false);
    assert.ok(value.start.blocked.includes("(acknowledgement_missing)"), value.start.blocked);
    assert.deepEqual(value.start.errors, ["확인 세 항목을 모두 체크하세요 (acknowledgement_missing)."]);
    assert.equal(value.coreDisabled, true);
    assert.ok(value.coreReason.includes("(mode_source_mismatch)"), value.coreReason);
    assert.ok(value.instanceBox, "instance range enabled without an instance");
    return value;
  });

  // ---- free docking (approval, real qvina)
  const free = await rec_.step("J01-free", ["D-free-job"], "Tick the third acknowledgement; click 도킹 작업 시작; 비싼 계산 승인; " +
    "작업 시작; the real qvina job finishes", async () => {
    await dock(page).locator(`label[data-docking-ack="${ACK_KEYS[2]}"] input`).check();
    await waitFor(page, async () => (await startState(page)).enabled ? true : null, "start enabled", 15000);
    return runDockingJob(page, run, evidence);
  }, async value => {
    assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
    assert.equal(value.job.protocol_id, "qvina_dock_v1");
    assert.ok(value.approved, "the first expensive call did not ask for approval");
    assert.match(value.handle ?? "", /\/docking_result\//);
    assert.equal(value.budgetAfter.used, value.budgetBefore.used + 1, "docking did not use exactly one expensive unit");
    assert.ok(value.resultNotice.includes(shortHandle(value.handle)), value.resultNotice);
    assert.equal(await dock(page).locator(`[data-testid="docking-result"]`).count(), 0, "the result was opened automatically");
    return value;
  });
  evidence.handles.free = free.handle;
  const freeStored = storedResult(runsDir, run, free.handle);
  evidence.freeArgs = { receptor: "prolif-vina-rec.pdb", ligand: path.basename(PARENT), mode: "free",
    box: { source: "ligand_range", margin_A: o.box.margin }, parameters: { seed: Number(FAST.seed),
      exhaustiveness: Number(FAST.exhaustiveness), num_modes: Number(FAST.numModes), energy_range: Number(FAST.energyRange) } };

  await rec_.step("V01-free-result", ["D-free-result"], "Click the new result's radio: summary (score name, engine, seed, values, " +
    "box, receptor hash), mode table and limitations equal the stored result", async () => {
    await openResult(page, free.handle, evidence);
    return { view: await resultView(page), state: await dockState(page),
      detail: await readApi(page, `/runs/${run}/docking/results/detail?handle=${enc(free.handle)}`) };
  }, async value => {
    const { view, detail } = value;
    const stored = freeStored;
    assert.equal(value.state, "ready");
    assert.equal(stored.method, "qvina_free_v1");
    assert.equal(stored.inputs.mode, "free");
    assert.ok(stored.modes.length >= 1 && stored.modes.length <= 3, `modes ${stored.modes.length}`);
    modeTableEquals(view, detail, stored);
    assert.equal(view.headers[1], "qvina 점수(kcal/mol)");
    assert.ok(view.caption.includes(capability.score_label) && view.caption.includes("모드 n(엔진 출력 순서)"), view.caption);
    assert.equal(view.summary["점수"], capability.score_label);
    assert.equal(view.summary["seed"], "42");
    assert.deepEqual(stored.parameters, { seed: 42, exhaustiveness: 1, num_modes: 3, energy_range: 3, conformers: null, cpu: 1 });
    assert.ok(view.summary["값"].startsWith("exhaustiveness 1 · num_modes 3 · energy_range 3.00 kcal/mol · cpu 1"), view.summary["값"]);
    assert.ok(view.summary["엔진"].startsWith(`qvina ${stored.engine.version}`), view.summary["엔진"]);
    assert.ok(view.summary["수용체"].includes(`SHA-256 ${stored.inputs.receptor.sha256}`));
    assert.equal(stored.inputs.receptor.sha256, fileRecord(RECEPTOR).sha256);
    assert.equal(stored.inputs.ligand.sdf_sha256, fileRecord(PARENT).sha256);
    assert.equal(view.summary["뺀 인스턴스"], "뺀 인스턴스 없음(단백질만)");
    assert.equal(view.summary["생성 여부"], "수소: 입력 그대로 · 3D 좌표: 입력 그대로");
    // box: hand oracle (expected.json public_example_box), stored values and the displayed rounding
    stored.box.center_A.forEach((v, i) => assert.ok(Math.abs(v - o.box.center[i]) < 1e-6, `center ${i}: ${v}`));
    stored.box.size_A.forEach((v, i) => assert.ok(Math.abs(v - o.box.size[i]) < 1e-6, `size ${i}: ${v}`));
    assert.equal(view.summary["상자"], `중심 ${triple(stored.box.center_A)} · 크기 ${triple(stored.box.size_A)} · 리간드 범위+여백 · 여백 8.00 Å`);
    assert.equal(triple(o.box.center), "(3.41, 0.72, 11.31) Å");
    assert.equal(triple(o.box.size), "(22.32, 27.51, 27.60) Å");
    const want = expectedLimitations(capability.limitations, { mode: "free", source: "sdf", removed: false, unspecified: null });
    assert.deepEqual(stored.limitations, want);
    assert.deepEqual(view.limitations, want);
    contactsFollowRules(stored);
    for (const row of stored.modes) for (const item of row.contacts) assert.equal(item.ligand_parent_serial, null);
    assert.equal(stored.modes[0].pose_sdf.split("\n")[0], "mode_1");
    const found = await checkWording("free result", stored.limitations);
    assert.deepEqual(found, [], JSON.stringify(found));
    return { modes: stored.modes.length, scores: stored.modes.map(row => row.score_kcal_mol), box: stored.box };
  });

  await rec_.step("V02-contacts", ["D-contacts"], "Click 접촉 보기 of 모드 1: the contact page equals the stored contacts " +
    "(pose SDF serial, receptor seven fields + atom + site_index, distance, geometric kind)", async () => {
    await dt(page, "docking-mode-contacts-1").click();
    control(evidence, "docking-mode-contacts", { mode: 1 });
    const table = await contactTable(page, 1);
    return { table, api: await readApi(page, `/runs/${run}/docking/results/contacts?handle=${enc(free.handle)}&mode=1&offset=0&limit=100`),
      pressed: await dt(page, "docking-mode-contacts-1").getAttribute("aria-pressed"),
      note: clean(await dock(page).locator('[data-testid="docking-contacts"] .mw-ligand-note').first().textContent()) };
  }, async value => {
    contactsEqual(value.table, freeStored, 1);
    assert.deepEqual(value.api.rows, freeStored.modes[0].contacts.slice(0, 100));
    assert.equal(value.api.cutoff_A, CONTACT_CUTOFF_A);
    assert.equal(value.pressed, "true");
    assert.ok(value.note.includes("수소결합 등 상호작용 판정이 아닙니다"), value.note);
    return { total: value.table.total, shown: value.table.rows.length };
  });

  for (const which of [1, "all"]) {
    await rec_.step(`V03-download-${which}`, ["D-downloads"], `Click ${which === "all" ? "포즈 SDF 전체 내려받기" : "모드 1 내려받기"}: ` +
      "bytes equal the stored pose_sdf (events.jsonl payload) and the backend bytes", () =>
      downloadPose(rec_, page, run, free.handle, freeStored, which), async value => {
      control(evidence, value.testid, { sha256: sha(value.bytes) });
      assert.equal(sha(value.bytes), sha(value.want), "downloaded bytes differ from the stored pose_sdf");
      assert.equal(sha(value.served), sha(value.want));
      assert.equal(`${new URL(value.url).pathname}${new URL(value.url).search}`, `/api${value.route}`);
      const stem = `protview-docking-${free.handle.split("/").at(-1).slice(0, 12)}`;
      assert.equal(value.filename, which === "all" ? `${stem}-modes.sdf` : `${stem}-mode_1.sdf`);
      if (which === "all") {
        const records = value.bytes.toString("utf8").split("$$$$\n").filter(Boolean);
        assert.equal(records.length, freeStored.modes.length);
        records.forEach((record, i) => assert.equal(record.split("\n")[0], `mode_${i + 1}`));
      }
      return { bytes: value.bytes.length, sha256: sha(value.bytes), filename: value.filename };
    });
  }

  // ---- report → 지식·보고서 list → downloads
  await rec_.part("report", ["D-report"], async () => {
    const cases = ["D-report"];
    const created = await rec_.step("P01-report", cases, "Click 보고서 만들기 for the free result", async () => {
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
      await dt(page, "docking-report").click();
      control(evidence, "docking-report", { clicked: true });
      const response = await posted;
      const body = await response.json();
      await dt(page, "docking-report-done").waitFor({ timeout: 30000 });
      return { status: response.status(), handle: body.handle, request: response.request().postDataJSON(), manifest: body.manifest,
        done: await dt(page, "docking-report-done").getAttribute("data-report-handle") };
    }, async value => {
      assert.equal(value.done, value.handle);
      assert.equal(value.manifest.analysis_type, "ligand_docking");
      assert.equal(value.manifest.result_handle, free.handle);
      assert.deepEqual(value.request, { result_handle: free.handle });
      const listed = (await readApi(page, `/runs/${run}/reports`)).find(item => item.handle === value.handle);
      assert.ok(listed, "created report not in the backend report list");
      assert.equal(listed.analysis_type, "ligand_docking");
      return { handle: value.handle };
    });
    evidence.handles.report = created.handle;
    const library = page.getByRole("region", { name: "보고서 보관함", exact: true });
    const reports = library.getByRole("region", { name: "저장된 보고서", exact: true });
    const content = library.getByRole("region", { name: "선택한 항목 내용", exact: true });
    await rec_.step("P02-listed", cases, "Click 지식·보고서: the report list shows 리간드 도킹 보고서; click it", async () => {
      await selectTab(page, "지식·보고서");
      const row = reports.locator("li button").filter({ hasText: created.handle });
      await row.waitFor({ timeout: 30000 });
      const kind = clean(await row.locator(".mw-library-kind").textContent());
      await row.click();
      const pre = content.getByLabel(`저장된 보고서 ${created.handle}`, { exact: true });
      await pre.waitFor({ timeout: 30000 });
      return { kind, text: await pre.textContent() };
    }, async value => {
      assert.equal(value.kind, "리간드 도킹 보고서");
      const saved = await readApi(page, `/runs/${run}/reports/selected?handle=${enc(created.handle)}`);
      assert.equal(value.text, saved.markdown);
      assert.ok(value.text.includes(capability.score_label), "report lacks the score name");
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
        return { route, sha256: sha(bytes), bytes: bytes.length };
      });
    }
  });

  // ---- complex receptor: one removed ligand instance, instance-range box
  await rec_.part("instance", ["D-instance"], async () => {
    const cases = ["D-instance"];
    const complex = await rec_.step("X01-import", cases, "Back to 리간드 설계·탐색 (the area remounts); choose the synthetic " +
      "complex receptor (file chooser), 가져오기; choose it, model 1: the instance list shows LIG L 1 (seven fields, 79 atoms) " +
      "and 없음; 수용체 안 인스턴스 범위 is disabled until the instance is chosen", async () => {
      await openLigandTab(page);
      const handles = await importDocking(page, run, { receptor: COMPLEX }, evidence);
      await dt(page, "docking-receptor").selectOption(handles.receptor);
      await dt(page, "docking-model").selectOption("1");
      await dt(page, "docking-instances").waitFor({ timeout: 30000 });
      const listed = await dt(page, "docking-instances").locator("label[data-docking-instance]").evaluateAll(items =>
        items.map(item => ({ key: item.getAttribute("data-docking-instance"), text: item.textContent.replace(/\s+/g, " ").trim() })));
      await radio(page, '[data-testid="docking-instances"] label[data-docking-instance="none"]');
      const disabled = await dock(page).locator('label[data-docking-box="instance_range"] input').isDisabled();
      const api = await readApi(page, `/runs/${run}/docking/receptor_instances?handle=${enc(handles.receptor)}`);
      return { handle: handles.receptor, listed, disabled, api };
    }, async value => {
      const key = JSON.stringify(o.instance);
      assert.deepEqual(value.listed.map(item => item.key), ["none", key]);
      const item = value.api.models.find(model => model.model_number === 1).instances;
      assert.equal(item.length, 1);
      assert.deepEqual(item[0].residue, o.instance);
      assert.equal(item[0].atom_count, o.instanceAtoms);
      assert.deepEqual(item[0].element_counts, o.instanceElements);
      assert.ok(value.listed[1].text.includes(`원자 ${o.instanceAtoms}개`), value.listed[1].text);
      assert.equal(value.disabled, true, "instance range usable with 없음 chosen");
      return value;
    });
    evidence.handles.complexReceptor = complex.handle;
    const docked = await rec_.step("X02-dock", cases, "Choose LIG L 1, 수용체 안 인스턴스 범위+여백 8, the 3D SDF, 자유 도킹, " +
      "seed 42 (same values as the free case); click 도킹 작업 시작 (no second approval)", async () => {
      await fillForm(page, { ...freeSpec, receptor: complex.handle, instance: o.instance,
        box: { source: "instance_range", margin: String(o.box.margin) } }, evidence);
      return runDockingJob(page, run, evidence);
    }, async value => {
      assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
      assert.equal(value.approved, false);
      return value;
    });
    evidence.handles.instance = docked.handle;
    await rec_.step("X03-result", cases, "Click the instance result: 뺀 인스턴스 (seven fields, 79 atoms, elements), the box " +
      "equals the hand oracle and the poses equal the plain-receptor poses byte for byte (instance removal leaves the plain " +
      "receptor)", async () => {
      await openResult(page, docked.handle, evidence);
      return { view: await resultView(page),
        detail: await readApi(page, `/runs/${run}/docking/results/detail?handle=${enc(docked.handle)}`) };
    }, async value => {
      const stored = storedResult(runsDir, run, docked.handle);
      modeTableEquals(value.view, value.detail, stored);
      const removed = stored.inputs.receptor.removed_instance;
      assert.deepEqual(removed.residue, o.instance);
      assert.equal(removed.atom_count, o.instanceAtoms);
      assert.deepEqual(removed.element_counts, o.instanceElements);
      const elements = Object.entries(o.instanceElements).map(([el, n]) => `${el} ${n}`).join(", ");
      assert.equal(value.view.summary["뺀 인스턴스"], `모델 1 · 체인 L · LIG 1 · 원자 ${o.instanceAtoms}개(${elements})`);
      assert.equal(stored.box.source, "instance_range");
      stored.box.center_A.forEach((v, i) => assert.ok(Math.abs(v - o.box.center[i]) < 1e-6));
      stored.box.size_A.forEach((v, i) => assert.ok(Math.abs(v - o.box.size[i]) < 1e-6));
      assert.ok(value.view.summary["상자"].includes("수용체 안 인스턴스 범위+여백"), value.view.summary["상자"]);
      const want = expectedLimitations(capability.limitations, { mode: "free", source: "sdf", removed: true, unspecified: null });
      assert.deepEqual(stored.limitations, want);
      assert.deepEqual(value.view.limitations, want);
      assert.deepEqual(stored.modes.map(row => row.score_kcal_mol), freeStored.modes.map(row => row.score_kcal_mol));
      assert.deepEqual(stored.modes.map(row => sha(Buffer.from(row.pose_sdf))), freeStored.modes.map(row => sha(Buffer.from(row.pose_sdf))));
      assert.deepEqual(stored.modes.map(row => row.contacts), freeStored.modes.map(row => row.contacts));
      const found = await checkWording("instance result", stored.limitations);
      assert.deepEqual(found, [], JSON.stringify(found));
      return { removed, box: stored.box, modes: stored.modes.length };
    });
  });

  // ---- core-fixed: real M17 inspection + enumeration in the candidate area, then the docking area
  await rec_.part("core-fixed", ["D-m17-candidates", "D-core-fixed"], async () => {
    const setHandle = await rec_.step("M01-m17", ["D-m17-candidates"], "Candidate area: choose the public-derived parent SDF and " +
      "synthetic-docking-blocks.smi, 가져오기, 점검 시작 (real RDKit), choose the inspection, tick atom 22, 후보 생성 시작 (fixed " +
      "replacement): the candidate set equals the fixture enumeration", async () => {
      await openLigandTab(page);
      for (const [slot, file] of [["parent", PARENT], ["blockSmiles", BLOCKS_SMI]]) {
        const chooser = page.waitForEvent("filechooser", { timeout: 15000 });
        await lt(page, `ligand-file-${slot}`).click();
        await (await chooser).setFiles(file);
      }
      await lt(page, "ligand-import").click();
      await waitFor(page, async () => await ligandPanel(page).locator('[data-ligand-area="inputs"]').getAttribute("data-state") === "ready"
        ? true : null, "ligand inputs imported", 60000);
      const inspect = await ligandJob(page, run, "ligand-inspect-start");
      assert.equal(inspect.job.status, "done", JSON.stringify(inspect.job.failure));
      const inspection = inspect.job.artifacts.ligand_inspection;
      const radioIn = ligandPanel(page).locator(`label${attr("data-ligand-inspection", inspection)} input[type="radio"]`);
      await radioIn.waitFor({ timeout: 30000 });
      await radioIn.check();
      await ligandPanel(page).locator(`[data-testid="ligand-inspection"]${attr("data-ligand-inspection-handle", inspection)}`)
        .waitFor({ timeout: 30000 });
      await lt(page, "ligand-atoms").locator(`input[data-serial="${SITE_ATOM}"]`).check();
      await ligandPanel(page).locator('[data-testid="ligand-preview"][data-site-valid="true"][data-ligand-preview-ready="true"]')
        .waitFor({ timeout: 30000 });
      await waitFor(page, async () => await lt(page, "ligand-enumerate-start").isEnabled() ? true : null, "enumerate enabled", 30000);
      const enumerate = await ligandJob(page, run, "ligand-enumerate-start");
      assert.equal(enumerate.job.status, "done", JSON.stringify(enumerate.job.failure));
      return { inspection, set: enumerate.job.artifacts.ligand_candidate_set, inspectApproved: inspect.approved };
    }, async value => {
      const set = await readApi(page, `/runs/${run}/ligand/candidate_sets/detail?handle=${enc(value.set)}`);
      const rows = await readApi(page, `/runs/${run}/ligand/candidate_sets/rows?handle=${enc(value.set)}&offset=0&limit=100`);
      assert.deepEqual(rows.rows.map(row => row.candidate.id).sort(), [...o.candidateIds].sort());
      assert.equal(set.candidate_set.parent_sha256, fileRecord(PARENT).sha256);
      assert.equal(value.inspectApproved, false, "the run's approval was asked again");
      return value;
    });
    evidence.handles.candidateSet = setHandle.set;
    const core = await rec_.step("C01-core-dock", ["D-core-fixed"], "Docking area: click 입력 목록 다시 읽기; M17 후보 + 부모 3D SDF, " +
      "the set, the fixture candidate, the parent SDF, 코어 고정, 리간드 범위+여백 8, conformers 5, seed 42; 도킹 작업 시작",
    async () => {
      // this mount read its input lists before the candidate set existed; the set appears only after a re-read
      const reread = page.waitForResponse(response => response.request().method() === "GET" &&
        new URL(response.url()).pathname === `/api/runs/${run}/docking/prerequisites`, { timeout: 30000 });
      await dt(page, "docking-prereq-refresh").click();
      control(evidence, "docking-prereq-refresh", { clicked: true });
      const prereq = await (await reread).json();
      const setRow = prereq.candidate_sets.find(item => item.handle === setHandle.set);
      await fillForm(page, { ...freeSpec, source: "candidate", set: setHandle.set, candidate: o.candidateId,
        parent: imports.ligand_sdf, mode: "core_fixed", values: { ...FAST, conformers: CORE_CONFORMERS } }, evidence);
      const job = await runDockingJob(page, run, evidence);
      return { ...job, parentOptions: setRow.parent_sdf_handles };
    }, async value => {
      assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
      assert.ok(value.parentOptions.includes(imports.ligand_sdf));
      return value;
    });
    evidence.handles.core = core.handle;
    await rec_.step("C02-core-result", ["D-core-fixed"], "Click the core-fixed result: rows are 샘플 n(점수 오름차순 나열), " +
      "core deviation shown, generated hydrogens/coordinates marked, parent serials on core contacts, limitations 1–5, 7, 8",
    async () => {
      await openResult(page, core.handle, evidence);
      const view = await resultView(page);
      let table = null;
      if (view.rows.length) {
        await dt(page, "docking-mode-contacts-1").click();
        table = await contactTable(page, 1);
      }
      return { view, table, detail: await readApi(page, `/runs/${run}/docking/results/detail?handle=${enc(core.handle)}`) };
    }, async value => {
      const stored = storedResult(runsDir, run, core.handle);
      assert.equal(stored.method, "qvina_core_fixed_score_only_v1");
      assert.equal(stored.inputs.ligand.source, "candidate");
      assert.equal(stored.inputs.ligand.candidate_id, o.candidateId);
      assert.equal(stored.inputs.ligand.parent_sdf_sha256, fileRecord(PARENT).sha256);
      assert.deepEqual(stored.inputs.ligand.generated, { hydrogens: true, coordinates: true });
      assert.equal(stored.parameters.conformers, Number(CORE_CONFORMERS));
      assert.ok(stored.counts.samples_generated <= Number(CORE_CONFORMERS));
      assert.ok(stored.modes.length <= 3 && stored.modes.length === Math.min(3, stored.counts.samples_scored));
      for (let i = 1; i < stored.modes.length; i++)
        assert.ok(stored.modes[i - 1].score_kcal_mol <= stored.modes[i].score_kcal_mol, "samples not in ascending score order");
      modeTableEquals(value.view, value.detail, stored);
      assert.equal(value.view.mode, "core_fixed");
      assert.ok(value.view.caption.includes("샘플 n(점수 오름차순 나열)"), value.view.caption);
      assert.ok(value.view.headers.includes("코어 최대 이탈"));
      assert.equal(value.view.summary["생성 여부"], "수소: RDKit이 만든 것(생성됨) · 3D 좌표: RDKit이 만든 것(생성됨)");
      assert.ok(value.view.summary["리간드 출처"].includes(`M17 후보 ${o.candidateId}`));
      for (const row of stored.modes) assert.equal(typeof row.core_max_deviation_A, "number");
      const want = expectedLimitations(capability.limitations, { mode: "core_fixed", source: "candidate", removed: false,
        unspecified: stored.inputs.ligand.unspecified_stereo_centers });
      assert.deepEqual(stored.limitations, want);
      assert.deepEqual(value.view.limitations, want);
      contactsFollowRules(stored);
      const retained = new Set(o.candidateRetained);
      for (const row of stored.modes) for (const item of row.contacts)
        if (item.ligand_parent_serial !== null) assert.ok(retained.has(item.ligand_parent_serial), `parent serial ${item.ligand_parent_serial}`);
      if (value.table) contactsEqual(value.table, stored, 1);
      const found = await checkWording("core-fixed result", stored.limitations);
      assert.deepEqual(found, [], JSON.stringify(found));
      return { samples: stored.counts, deviations: stored.modes.map(row => row.core_max_deviation_A),
        parentSerialContacts: stored.modes.map(row => row.contacts.filter(item => item.ligand_parent_serial !== null).length) };
    });
  });

  // ---- structure tab kept mounted (hidden) through every ligand step
  await rec_.part("structure-kept", ["D-structure-kept"], () => rec_.step("T01-structure", ["D-structure-kept"],
    "Click 구조 분석: the same Mol* session, source and generation as before the ligand tab was opened", async () => {
      const hidden = await structureState(page);
      await selectTab(page, "구조 분석");
      await page.locator("canvas.mw-molstar-canvas:visible").first().waitFor({ timeout: 15000 });
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

  // ---- run switch: a held run A results response released after the switch is not applied
  const runB = await rec_.part("run-switch", ["D-run-switch-late"], async () => {
    const cases = ["D-run-switch-late"];
    const made = await rec_.step("W01-new-run-b", cases, "구조 분석: click 새 run (run B); the docking area shows run B only",
      async () => {
        const id = await newRun(page);
        await openLigandTab(page);
        return { run: id, global: await globalRun(page),
          results: await dock(page).locator("label[data-docking-result]").count(),
          text: clean(await dock(page).locator('[data-docking-area="results"]').textContent()) };
      }, async value => {
        assert.equal(value.global, value.run);
        assert.equal(value.results, 0);
        assert.ok(value.text.includes("이 run에 도킹 결과가 없습니다."));
        return value;
      });
    evidence.runs.B = made.run;
    const held = [];
    let holding = true;
    const matcher = url => new URL(url).pathname === `/api/runs/${run}/docking/results`;
    const handler = async route => {
      if (!holding || route.request().method() !== "GET") return route.continue();
      held.push({ route, response: await route.fetch(), at: Date.now() });
    };
    await page.route(matcher, handler);
    evidence.fixtureLabels.push(HOLD_LABEL);
    try {
      await rec_.step("W02-held", cases, "Choose run A in 저장된 run, click 리간드 설계·탐색: run A's docking result list " +
        "response is held (results area loading)", async () => {
        await chooseRun(page, run);
        await selectTab(page, TAB);
        await dock(page).waitFor({ timeout: 15000 });
        await waitFor(page, async () => held.length >= 1 ? true : null, "held run A docking results", 30000);
        return { held: held.length, area: await areaState(page, "results"), run: await globalRun(page) };
      }, async value => { assert.equal(value.area, "loading"); assert.equal(value.run, run); return value; });
      await rec_.step("W03-switch-b", cases, "Click 구조 분석, choose run B, click 리간드 설계·탐색: run B's empty list", async () => {
        await chooseRun(page, made.run, false);
        await openLigandTab(page);
        return { run: await globalRun(page), results: await dock(page).locator("label[data-docking-result]").count() };
      }, async value => { assert.equal(value.run, made.run); assert.equal(value.results, 0); return value; });
      await rec_.step("W04-release", cases, "Release run A's held response: run B's area stays, no run A result appears", async () => {
        holding = false;
        const released = [];
        for (const item of held) {
          try { await item.route.fulfill({ response: item.response }); released.push({ delivered: true }); }
          catch (error) { released.push({ delivered: false, reason: String(error).slice(0, 160) }); }
        }
        await page.waitForTimeout(2500);
        return { released, run: await globalRun(page), text: clean(await panelText(page)),
          results: await dock(page).locator("label[data-docking-result]").count(), area: await areaState(page, "results") };
      }, async value => {
        assert.equal(value.run, made.run);
        assert.equal(value.results, 0);
        assert.equal(value.area, "ready");
        for (const handle of [free.handle, evidence.handles.instance, evidence.handles.core].filter(Boolean))
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

  // ---- rejections (run B): planar SDF, implicit hydrogens, box over 40 Å (screen and worker)
  const rejectRun = runB;
  const rejected = await rec_.part("rejections", ["D-reject-planar", "D-reject-implicit-h", "D-reject-box"], async () => {
    assert.ok(rejectRun, "run B was not created");
    const files = await rec_.step("N01-imports", ["D-reject-planar", "D-reject-implicit-h", "D-reject-box"], "Run B: choose " +
      "the receptor and the planar SDF, 가져오기; then the implicit-H SDF and the 3D SDF, 가져오기 (one at a time)", async () => {
      const first = await importDocking(page, rejectRun, { receptor: RECEPTOR, ligand: PLANAR }, evidence);
      const second = await importDocking(page, rejectRun, { ligand: IMPLICIT }, evidence);
      const third = await importDocking(page, rejectRun, { ligand: PARENT }, evidence);
      return { receptor: first.receptor, planar: first.ligand_sdf, implicit: second.ligand_sdf, parent: third.ligand_sdf };
    }, async value => { assert.ok(Object.values(value).every(Boolean)); return value; });
    const base = { ...freeSpec, receptor: files.receptor };
    const failed = async (caseId, label, sdf, box, reason) => rec_.step(caseId, [label], `Choose ${path.basename(sdf)}, ` +
      `${box.source} ${box.margin ?? ""}; click 도킹 작업 시작 (approval when asked): the job fails with ${reason}; the area ` +
      "shows 실패 with the closed reason; no result is stored", async () => {
      await fillForm(page, { ...base, sdf, box }, evidence);
      await waitFor(page, async () => (await startState(page)).enabled ? true : null, "start enabled", 15000);
      const job = await runDockingJob(page, rejectRun, evidence);
      return { ...job, failure: clean(await dt(page, "docking-failure").textContent({ timeout: 5000 }).catch(() => "")),
        results: await readApi(page, `/runs/${rejectRun}/docking/results`) };
    }, async value => {
      assert.equal(value.job.status, "failed");
      assert.equal(value.job.failure?.reason_code, reason);
      assert.equal(value.state, "failure");
      assert.ok(value.failure.includes(`(${reason})`), value.failure);
      assert.equal(value.results.total, 0, "a failed job stored a result");
      const found = await checkWording(`failure ${reason}`, []);
      assert.deepEqual(found, [], JSON.stringify(found));
      return { reason: value.job.failure.reason_code, message: value.job.failure.message, failure: value.failure };
    });
    await failed("N02-planar", "D-reject-planar", files.planar, { source: "ligand_range", margin: "8" }, o.planarReason);
    await failed("N03-implicit-h", "D-reject-implicit-h", files.implicit, { source: "ligand_range", margin: "8" }, o.implicitReason);
    await rec_.step("N04-box-screen", ["D-reject-box"], "Choose the 3D SDF and 직접 입력 with size x = 41 Å: 도킹 작업 시작 " +
      "stays disabled (box_too_large, never shrunk) and no job request is sent", async () => {
      const before = log.length;
      await fillForm(page, { ...base, sdf: files.parent, box: { source: "manual", center: ["3.41", "0.72", "11.31"],
        size: ["41", "20", "20"] } }, evidence);
      await page.waitForTimeout(800);
      return { start: await startState(page),
        posts: log.slice(before).filter(row => row.method === "POST" && row.path.endsWith("/jobs")).length };
    }, async value => {
      assert.equal(value.start.enabled, false);
      assert.ok(value.start.errors.some(text => text.includes("(box_too_large)")), JSON.stringify(value.start.errors));
      assert.equal(value.posts, 0);
      return value;
    });
    await failed("N05-box-worker", "D-reject-box", files.parent, { source: "ligand_range", margin: "20" }, "box_too_large");
    return files;
  });

  // ---- cancel while qvina runs: the worker and qvina2 processes are gone, no result is stored
  await rec_.part("cancel", ["D-cancel"], async () => {
    assert.ok(rejected, "run B inputs missing");
    const cases = ["D-cancel"];
    const running = await rec_.step("K01-running", cases, "Choose the 3D SDF, 리간드 범위+여백 8, exhaustiveness 32, num_modes 9, " +
      "seed 7; click 도킹 작업 시작: the job runs and a qvina2 process runs under the runs folder", async () => {
      await fillForm(page, { ...freeSpec, receptor: rejected.receptor, sdf: rejected.parent, values: SLOW }, evidence);
      const job = await runDockingJob(page, rejectRun, evidence, { until: "running" });
      const procs = await waitFor(page, async () => {
        const found = jobProcesses(runsDir);
        return found.some(item => item.command.includes("qvina2")) ? found : null;
      }, "qvina2 running", 120000);
      return { ...job, processes: procs };
    }, async value => {
      assert.ok(["running"].includes(value.job.status), value.job.status);
      return { job: value.job.job_id, processes: value.processes };
    });
    await rec_.step("K02-cancel", cases, "Click 작업 취소 once it is enabled: the job is cancelled, the area shows 실패 (취소, no " +
      "result saved), and no worker, guardian or qvina2 process remains", async () => {
      const cancel = dt(page, "docking-job-cancel");
      const waitedFrom = Date.now();
      await waitFor(page, async () => await cancel.isEnabled().catch(() => false) ? true : null, "cancel enabled", 180000);
      const enabledAfterMs = Date.now() - waitedFrom;
      await cancel.click();
      control(evidence, "docking-job-cancel", { enabledAfterMs });
      const final = await waitFor(page, async () => {
        const value = await jobPhase(page);
        return value && ["cancelled", "failed", "done"].includes(value.phase) ? value : null;
      }, "job cancelled", 120000);
      const gone = await waitFor(page, async () => jobProcesses(runsDir).length === 0 ? true : null, "job processes gone", 60000)
        .then(() => true, () => false);
      return { final, enabledAfterMs, gone, left: jobProcesses(runsDir), state: await dockState(page),
        failure: clean(await dt(page, "docking-failure").textContent({ timeout: 5000 }).catch(() => "")),
        job: await readApi(page, `/runs/${rejectRun}/jobs/${enc(running.job.job_id)}`),
        results: await readApi(page, `/runs/${rejectRun}/docking/results`) };
    }, async value => {
      assert.equal(value.job.status, "cancelled");
      assert.equal(value.final.phase, "cancelled");
      assert.equal(value.state, "failure");
      assert.ok(value.failure.includes("취소"), value.failure);
      assert.equal(value.gone, true, JSON.stringify(value.left));
      assert.equal(value.results.total, 0, "a cancelled job stored a result");
      return { enabledAfterMs: value.enabledAfterMs, left: value.left };
    });
  });

  evidence.wording = wording;
  for (const id of [run, runB].filter(Boolean)) evidence.providerCalls.push(await providerCalls(page, id));
  // the wording case passes only if every recorded check ran and found nothing
  rec_.append({ caseId: "WORDING", cases: ["D-wording"], status: wording.length >= 4 && wording.every(item => !item.found.length)
    ? "pass" : "fail", checks: wording });
  if (!(wording.length >= 4 && wording.every(item => !item.found.length))) evidence.partFailures.push({ part: "wording", cases: ["D-wording"] });
  evidence.wordingPassed = wording.length >= 4 && wording.every(item => !item.found.length);
}

/** Candidate-area job (M17 controls): start, approve when asked, start, wait until finished. */
async function ligandJob(page, run, startId) {
  const phase = async () => {
    const job = lt(page, "ligand-job");
    if (!await job.count()) return null;
    return { phase: await job.getAttribute("data-ligand-job-phase"), id: await job.getAttribute("data-ligand-job-id") };
  };
  const prior = (await phase())?.id ?? null; // the finished inspection stays shown until the next job replaces it
  await lt(page, startId).click();
  let approved = false;
  const first = await waitFor(page, async () => {
    const value = await phase();
    if (!value || value.id === prior) return null;
    if (["running", "done", "failed", "cancelled"].includes(value.phase)) return value;
    if (value.phase === "awaiting_approval" && await lt(page, "ligand-job-approve").isEnabled().catch(() => false)) return value;
    if (value.phase === "saved" && await lt(page, "ligand-job-start").isEnabled().catch(() => false)) return value;
    return null;
  }, `${startId} submitted`, 60000);
  if (first.phase === "awaiting_approval") {
    approved = true;
    await lt(page, "ligand-job-approve").click();
    await waitFor(page, async () => (await phase())?.phase === "saved" ? true : null, "ligand approval", 30000);
  }
  if ((await phase()).phase === "saved") await lt(page, "ligand-job-start").click();
  const done = await waitFor(page, async () => {
    const value = await phase();
    return value && value.id !== prior && ["done", "failed", "cancelled"].includes(value.phase) ? value : null;
  }, `${startId} finished`, 240000);
  return { approved, job: await readApi(page, `/runs/${run}/jobs/${enc(done.id)}`) };
}

// ------------------------------------------------------------------ mode unavailable (backend without the environments)
async function modeUnavailable(session, input, rec_, evidence, log) {
  const { page } = session;
  evidence.fixtureLabels.push(input["fixture-label"] || UNAVAILABLE_LABEL);
  const capabilities = await readApi(page, "/capabilities");
  const capability = capabilities.methods?.ligand_docking ?? null;
  evidence.capability = capability && { available: capability.available, reason_code: capability.reason_code };
  assert.ok(capability && capability.available === false, `backend reports docking available: ${JSON.stringify(capability)}`);
  assert.equal((await readApi(page, "/runs")).length, 0, "mode unavailable needs a fresh runs root");
  const noControls = async () => ({ state: await dockState(page), text: clean(await dock(page).textContent()),
    controls: await dock(page).locator("button, input, select, textarea, a, img, table").count() });
  await waitForBoot(page);
  await rec_.step("U01-no-run", ["D-no-run"], "No run yet: click 리간드 설계·탐색 → the docking area shows the no-run reason " +
    "only (no numbers, no controls)", async () => {
    await selectTab(page, TAB);
    await dt(page, "docking-no-run").waitFor({ timeout: 15000 });
    return { ...await noControls(), reason: clean(await dt(page, "docking-no-run").textContent()) };
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
  await rec_.step("U03-unavailable", ["D-unavailable"], "Click 리간드 설계·탐색: 사용할 수 없음 with the capability reason " +
    "(worker_missing); no numbers, no controls, no docking requests", async () => {
    const before = Date.now();
    await selectTab(page, TAB);
    await dt(page, "docking-unavailable").waitFor({ timeout: 15000 });
    await page.waitForTimeout(2000);
    const dockingReads = log.filter(row => row.at >= before && row.path.includes("/docking/")).map(row => `${row.method} ${row.path}`);
    return { ...await noControls(), reason: clean(await dt(page, "docking-unavailable").textContent()), dockingReads };
  }, async value => {
    assert.equal(value.state, "unavailable");
    assert.ok(value.reason.includes("사용할 수 없음"), value.reason);
    assert.ok(value.reason.includes(`(${capability.reason_code})`), value.reason);
    assert.ok(value.reason.includes(capability.reason), value.reason);
    assert.ok(!/\d/.test(value.text), `a number is shown: ${value.text}`);
    assert.equal(value.controls, 0);
    assert.deepEqual(value.dockingReads, [], "the unavailable area sent docking requests");
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
  const evidence = { schema: "m18_docking_evidence@1", mode: input.mode, runs: {}, inputs: [], handles: {},
    fixtureLabels: [], providerCalls: [], partFailures: [], controls: {}, startedAt: new Date().toISOString(),
    notObserved: input.mode === "main" ? [{ case: "D-zero-modes", reason: "qvina returns modes for every valid input used " +
      "here; no input or value is forged to produce a zero-mode result. Covered by frontend/tests/docking.test.cjs " +
      "(dockingPanelState: 0 modes = scientific_null, a failed job is never an empty result) and the backend docking tests." }]
      : [] };
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
  if (input.mode === "main") cases["D-wording"] = evidence.wordingPassed === true ? "pass" : "fail";
  const providerZero = evidence.providerCalls.length > 0 && evidence.providerCalls.every(item => item.zero);
  const passed = !error && evidence.partFailures.length === 0 && offscreenComplete(proof) && proof.nonLoopbackRequests === 0 &&
    Object.keys(cases).length > 0 && Object.values(cases).every(value => value === "pass") && providerZero;
  evidence.finishedAt = new Date().toISOString();
  evidence.error = error ? String(error.stack ?? error) : null;
  evidence.requestCount = log.length;
  fs.writeFileSync(path.join(input.artifacts, "docking-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  fs.writeFileSync(path.join(input.artifacts, "docking-requests.jsonl"), log.map(row => JSON.stringify(row)).join("\n") + "\n");
  const harness = Object.fromEntries(["docking-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m18_case_ledger_row@1", mode: input.mode, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", cases, runId: evidence.runs.A ?? null, runs: evidence.runs,
    handles: evidence.handles, inputs: evidence.inputs, fixtureLabels: evidence.fixtureLabels, controls: evidence.controls,
    freeArgs: evidence.freeArgs ?? null, notObserved: evidence.notObserved,
    buildId: buildId(), harness, offscreen: proof, externalRequestCount: proof ? proof.nonLoopbackRequests : null,
    providerCalls: evidence.providerCalls, providerCallsZero: providerZero, partFailures: evidence.partFailures,
    error: evidence.error, evidenceFile: path.basename(rec_.file), startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, runs: evidence.runs, cases }) + "\n");
  if (error) process.stderr.write(`docking-flow ${input.mode} failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`docking-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, oracle, halfUp, expectedLimitations, contactKind, forbiddenWords };
