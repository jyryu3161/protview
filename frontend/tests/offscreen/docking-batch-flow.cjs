"use strict";

// M19 candidate batch docking (qvina) offscreen QA (spec §13.6). Real Electron offscreen page (isOffscreen, GPU/WebGL,
// paint). Every product mutation is a Playwright locator mouse/keyboard/file-chooser/select input; DOM .click() and
// product handlers are never called. Observation is read-only: data attributes and text of the page, renderer
// request/response events, Electron paint frames, downloaded bytes, GET reads of the loopback API, the stored object
// payloads in <runs-dir>/<run>/events.jsonl (read-only file reads) and the process table (`ps`/`lsof`). Two labeled
// fixtures are recorded in the ledger and never produce a value: a dry-run run record created over the loopback API (the
// screen cannot create one) and a QA-generated chain building-block list (M17 paging convention) for the 50-candidate cap.
//
// Independent oracle: backend/tests/fixtures/docking/expected.json and m17-enumerate-result-record0-nmethyl.json (T1/M18,
// hand-derived: box, candidate ids in set order, stored RDKit properties for the filter), m19-batch-input.json (hand
// arithmetic of spec 6.2/6.3: needed = N units and min(7800, N × 300 + 300) s, N = 0 → 60 s; shortfall = max(0, needed −
// (limit − used)); full_batch_may_be_partial = N × 300 > 7200), the spec 5.4 sentences B1–B3 verbatim, the spec 9 sort
// rule (rows without a score always last) written here independently, and the fixture receptor refusal lists.
//
// Modes (the full sequence: scripts/m19_offscreen_acceptance.py):
//   main         run A (새 run): receptor imports + real M17 inspection/enumeration → batch area: candidate filter and
//                checkboxes → water/zinc receptor refused at preflight with its list → free batch with the parent row
//                (preflight N 4, no shortfall, no approval) → real qvina batch → table = stored values, sorting, row →
//                M18 detail + pose SDF download → identical batch (existing job, no new job, no charge) → subset batch (0
//                new dockings, reused marks) → core-fixed (parent row disabled; shortfall 1 → explicit limit approval →
//                batch) → report + 지식·보고서 list + downloads → global budget = backend.
//                run B: M17 set of the planar parent fixture → free batch with the parent row: the parent row fails
//                ligand_not_3d and the batch continues (complete), rows without a score stay last in every sort.
//                run C: M17 set from a labeled generated chain list (59 candidates) → slow free batch, 작업 취소 after the
//                first finished row → partial/cancelled, finished row kept, no worker/qvina2 left → 50-candidate cap
//                (51st disabled), preflight N 49 / reused 1, shortfall, may-be-partial note, approval offered (not used).
//                run D (labeled dry-run record): dry-run note, no limit approval control. Screen wording; processes.
//   unavailable  backend started from a layout without the locked environments (runner): no-run and
//                capability-unavailable states show a reason only (no numbers, no controls, no batch requests)
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const { waitForViewer } = require("./normal-flow.cjs");
const m18 = require("./docking-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const FIXTURES = path.join(REPO, "backend/tests/fixtures");
const DOCK = path.join(FIXTURES, "docking");
const RECEPTOR = path.join(FIXTURES, "chemical/prolif-vina-rec.pdb");
const PARENT = path.join(DOCK, "public-derived-parent-record0.sdf");
const PLANAR = path.join(DOCK, "synthetic-ligand-planar-z0.sdf");
const WATER_ZINC = path.join(DOCK, "synthetic-receptor-water-zinc.pdb");
const BLOCKS_SMI = path.join(DOCK, "synthetic-docking-blocks.smi");
const EXPECTED = path.join(DOCK, "expected.json");
const BATCH_FIXTURE = path.join(DOCK, "m19-batch-input.json");
const M17_RESULT = path.join(DOCK, "m17-enumerate-result-record0-nmethyl.json");
const MODES = ["main", "unavailable"];
const TAB = "리간드 설계·탐색";
// Small values keep the real batches short (free rows a few seconds each, core-fixed rows about a second); the cancel
// batch uses exhaustiveness 8 so a row is still running when 작업 취소 is clicked.
const FAST = { seed: "42", exhaustiveness: "1", numModes: "3", energyRange: "3" };
const SLOW = { seed: "7", exhaustiveness: "8", numModes: "9", energyRange: "3" };
const CORE_CONFORMERS = "5";
const SITE_ATOM = 22; // N-methyl carbon of the public-derived parent (expected.json public_example_numbering)
const CHAIN_COUNT = 60;
const CHAIN_LABEL = "QA-GENERATED SYNTHETIC building-block list (labeled; written by docking-batch-flow.cjs for the " +
  "50-candidate cap, not a scientific input): *C…C chains of 1–60 carbons";
const DRY_RUN_LABEL = "labeled loopback API fixture: dry-run run record (POST /runs dry_run true; the screen cannot create one)";
const UNAVAILABLE_LABEL = "labeled runtime layout without .deps (runner): capability worker_missing";
const PROVIDER_EVENT_TYPES = new Set(["egress", "egress_budget_settled", "viewer_dispatch_started"]);
const NO_RUN_REASON = "구조 분석 탭에서 run을 먼저 고르세요.";
const ACK_KEYS = ["keep_input_protonation", "tool_assigned_types_charges", "rigid_no_optimization"];
const SCORE_ROW_LABEL = { free: "모드 1(엔진 출력 순서)", core_fixed: "샘플 1(점수 오름차순 나열)" };
const REUSED_LABEL = "저장된 결과 재사용";
const PARENT_LABEL = "부모(기준 입력)";
const MAX_CANDIDATES = 50;
// spec 5.4 verbatim (independent of the product constants)
const B = {
  B1: "이 일괄의 모든 행은 같은 수용체·상자·seed·방식·값으로 계산되어 점수를 같은 표에서 나란히 볼 수 있으며, " +
    "표의 정렬은 표시 순서일 뿐 순위가 아니다.",
  B2: "이 일괄은 일부만 계산되었다. 계산하지 않은 행은 점수가 없으며 0이 아니다.",
  B3: "부모 행은 후보와 같은 설정으로 도킹한 기준 입력이며, 점수 차이를 개선이나 악화로 해석하지 않는다.",
};
const PROCESS_PATTERNS = ["qvina2", "docking_batch_worker.py", "docking_worker.py", "ligand_worker.py", "guardian.py"];

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const attr = (name, value) => `[${name}="${String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"]`;
const { halfUp } = m18;
const seconds = value => `${halfUp(value, 1)}초`;
const pairText = pair => `비싼 계산 ${pair.expensive_calls}단위 · 활동 시간 ${seconds(pair.wall_clock_s)}`;

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
    `Usage: docking-batch-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> [--url http://127.0.0.1:3000] ` +
    "[--runs-dir <backend MW_RUNS_DIR> (main: stored objects)] [--fixture-label <runtime layout label>]. main needs the " +
    "locked docking and M17 environments and a fresh runs root; unavailable needs a backend without them and a fresh " +
    "runs root. Full sequence: scripts/m19_offscreen_acceptance.py.");
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
  const batch = JSON.parse(fs.readFileSync(BATCH_FIXTURE, "utf8"));
  const m17 = JSON.parse(fs.readFileSync(M17_RESULT, "utf8"));
  const box = expected.public_example_box;
  return {
    files: [EXPECTED, BATCH_FIXTURE, M17_RESULT].map(fileRecord),
    box: { center: box.center_A, size: box.size_A, margin: box.margin_A },
    candidateIds: batch.inputs.candidate_ids_in_set_order,
    m17Ids: m17.candidates.map(item => item.id),
    heavyAtoms: Object.fromEntries(m17.candidates.map(item => [item.id, item.properties.heavy_atoms])),
    planarReason: expected.ligand_fixtures["synthetic-ligand-planar-z0.sdf"].expected_reason,
    refusal: m18.refusalOracle(m18.oracle()),
  };
}
/** spec 6.2/6.3 arithmetic (m19-batch-input.json hand_oracle "how"). */
function neededFor(n) {
  return { expensive_calls: n, wall_clock_s: n === 0 ? 60 : Math.min(7800, n * 300 + 300) };
}
function shortfallFor(needed, remaining) {
  return { expensive_calls: Math.max(0, needed.expensive_calls - remaining.expensive_calls),
    wall_clock_s: Math.max(0, needed.wall_clock_s - remaining.wall_clock_s) };
}
/** spec 9 display order, written independently: rows without a score always last (row order), ties by row number. */
function sortOracle(rows, key, direction) {
  const byRow = [...rows].sort((a, b) => a.row_index - b.row_index);
  if (key === "row") return direction === "asc" ? byRow : byRow.reverse();
  const has = key === "score" ? row => row.state === "scored" && typeof row.score_kcal_mol === "number"
    : row => row.candidate_id !== null;
  const value = key === "score" ? row => row.score_kcal_mol : row => row.candidate_id;
  const sign = direction === "asc" ? 1 : -1;
  const head = byRow.filter(has).sort((a, b) => (value(a) < value(b) ? -sign : value(a) > value(b) ? sign : 0) ||
    a.row_index - b.row_index);
  return [...head, ...byRow.filter(row => !has(row))];
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
/** A stored object's content: the object_created payload in the run's event log (read-only file read). */
function storedObject(runsDir, run, handle) {
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
  const file = path.join(artifacts, `docking-batch-${input.mode}.jsonl`);
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
      const html = await page.evaluate(() => document.querySelector('[data-testid="docking-batch-panel"]')?.outerHTML
        .slice(0, 160000) ?? "").catch(() => null);
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

// ------------------------------------------------------------------ tabs, runs
const tabButton = (page, label) => page.locator(".mw-app-tabs").getByRole("tab", { name: label, exact: true });
async function selectTab(page, label) {
  await tabButton(page, label).click();
  await waitFor(page, async () => await tabButton(page, label).getAttribute("aria-selected") === "true", `${label} selected`, 10000);
}
const globalRun = page => page.evaluate(() => document.querySelector(".mw-app-run")?.getAttribute("data-global-run") || null);
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
  await selectTab(page, "구조 분석");
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
async function chooseRun(page, run) {
  await selectTab(page, "구조 분석");
  await page.getByRole("tab", { name: /^run/i }).click();
  await waitFor(page, async () => await page.locator(`#run-choice option${attr("value", run)}`).count() ? true : null,
    `run ${run} listed`, 30000);
  await page.locator("#run-choice").selectOption(run);
  await waitFor(page, async () => await globalRun(page) === run, `run ${run} selected`, 30000);
}

// ------------------------------------------------------------------ M18 docking area and M17 candidate area (inputs)
const dock = page => page.locator('#mw-app-panel-ligand [data-testid="docking-panel"]');
const dt = (page, id) => dock(page).locator(`[data-testid="${id}"]`);
const ligandPanel = page => page.locator('#mw-app-panel-ligand [data-testid="ligand-panel"]');
const lt = (page, id) => ligandPanel(page).locator(`[data-testid="${id}"]`);
const batch = page => page.locator('#mw-app-panel-ligand [data-testid="docking-batch-panel"]');
const bt = (page, id) => batch(page).locator(`[data-testid="${id}"]`);
const batchState = page => batch(page).getAttribute("data-batch-state", { timeout: 2000 }).catch(() => null);
async function openLigandTab(page) {
  await selectTab(page, TAB);
  await batch(page).waitFor({ timeout: 15000 });
  await dock(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => ["ready", "unavailable"].includes(await batchState(page)) &&
    (await batchState(page) === "unavailable" || await batch(page).locator('[data-batch-area="results"]')
      .getAttribute("data-state") === "ready") ? true : null, "batch area settled", 60000);
}
/** Receptor imports through the M18 docking area (file chooser + 가져오기); returns the new handle. */
async function importReceptor(page, run, file, evidence) {
  const known = new Set((await readApi(page, `/runs/${run}/docking/prerequisites`)).imports.map(item => item.handle));
  const chooser = page.waitForEvent("filechooser", { timeout: 15000 });
  await dt(page, "docking-file-receptor").click();
  await (await chooser).setFiles(file);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/chemical/imports`, { timeout: 60000 });
  await dt(page, "docking-import").click();
  control(evidence, "docking-import", { file: path.basename(file) });
  assert.equal((await posted).status(), 201);
  await dt(page, "docking-import-done").waitFor({ timeout: 60000 });
  const fresh = (await readApi(page, `/runs/${run}/docking/prerequisites`)).imports.filter(item => !known.has(item.handle));
  assert.equal(fresh.length, 1, JSON.stringify(fresh));
  assert.equal(fresh[0].input_kind, "receptor");
  return fresh[0].handle;
}
/** Candidate-area job (M17 controls): start, approve when asked, start, wait until finished. */
async function ligandJob(page, run, startId) {
  const phase = async () => {
    const job = lt(page, "ligand-job");
    if (!await job.count()) return null;
    return { phase: await job.getAttribute("data-ligand-job-phase"), id: await job.getAttribute("data-ligand-job-id") };
  };
  const prior = (await phase())?.id ?? null;
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
/** Real M17 inspection + fixed-replacement enumeration at site 22 from the candidate area. */
async function m17CandidateSet(page, run, parentFile, blocksFile, evidence) {
  for (const [slot, file] of [["parent", parentFile], ["blockSmiles", blocksFile]]) {
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
  control(evidence, "m17-candidate-set", { parent: path.basename(parentFile), blocks: path.basename(blocksFile) });
  const set = enumerate.job.artifacts.ligand_candidate_set;
  const rows = await readApi(page, `/runs/${run}/ligand/candidate_sets/rows?handle=${enc(set)}&offset=0&limit=100`);
  return { inspection, set, inspectApproved: inspect.approved, ids: rows.rows.map(row => row.candidate.id), total: rows.total };
}
/** Labeled generated block list for the 50-candidate cap (written into the artifacts folder, never committed). */
function chainLibrary(artifacts) {
  const file = path.join(artifacts, "qa-generated-chain-blocks.smi");
  const lines = [`# ${CHAIN_LABEL}`];
  for (let n = 1; n <= CHAIN_COUNT; n++) lines.push(`*${"C".repeat(n)} qa_chain_${n}`);
  fs.writeFileSync(file, lines.join("\n") + "\n");
  return file;
}

// ------------------------------------------------------------------ batch area (real input; read-only helpers)
async function batchText(page) { return batch(page).evaluate(node => node.innerText); }
/** Forbidden words on screen, line by line; a line equal to a stored sentence is exempt and score names are removed. */
function forbiddenWords(text, exempt, scoreLabels) { return m18.forbiddenWords(text, exempt, scoreLabels); }
async function fill(page, id, value) {
  const field = bt(page, id);
  await field.click();
  await field.fill(value);
}
async function check(page, selector, on = true) {
  const input = batch(page).locator(`${selector} input`);
  await input.waitFor({ timeout: 30000 });
  if (on) await input.check(); else await input.uncheck();
}
/** ① receptor, model 1, 없음(단백질만), PDB CONECT (screen order; nothing chosen automatically). */
async function chooseReceptor(page, receptor, evidence) {
  await bt(page, "docking-batch-receptor").selectOption(receptor);
  control(evidence, "docking-batch-receptor", { handle: receptor });
  await bt(page, "docking-batch-model").waitFor({ timeout: 30000 });
  await bt(page, "docking-batch-model").selectOption("1");
  control(evidence, "docking-batch-model", { model: 1 });
  await bt(page, "docking-batch-instances").waitFor({ timeout: 30000 });
  await check(page, '[data-testid="docking-batch-instances"] label[data-batch-instance="none"]');
  control(evidence, "docking-batch-instance-radio", { instance: "none" });
  await bt(page, "docking-batch-connectivity").locator("label").filter({ hasText: "PDB CONECT" }).locator("input").check();
  control(evidence, "docking-batch-connectivity-radio", { kind: "pdb_conect" });
}
/** ② candidate set and parent SDF (the set's parent options; chosen explicitly). */
async function chooseSet(page, set, parent, evidence) {
  await bt(page, "docking-batch-candidate-set").selectOption(set);
  control(evidence, "docking-batch-candidate-set", { handle: set });
  await bt(page, "docking-batch-parent-sdf").waitFor({ timeout: 30000 });
  await bt(page, "docking-batch-parent-sdf").selectOption(parent);
  control(evidence, "docking-batch-parent-sdf", { handle: parent });
  await bt(page, "docking-batch-candidates").waitFor({ timeout: 30000 });
}
async function tick(page, id, on, evidence) {
  const box = bt(page, `docking-batch-candidate-${id}`);
  if (on) await box.check(); else await box.uncheck();
  control(evidence, "docking-batch-candidate", { id, checked: on });
}
async function selectionCount(page) {
  const node = bt(page, "docking-batch-selection-count");
  return { selected: Number(await node.getAttribute("data-selected")), text: clean(await node.textContent()) };
}
async function shownCandidates(page) {
  return bt(page, "docking-batch-candidates").locator("tbody tr").evaluateAll(items => items.map(item => ({
    id: item.getAttribute("data-batch-candidate"), checked: item.getAttribute("data-checked") === "true",
    disabled: item.querySelector('input[type="checkbox"]').disabled,
    cells: [...item.querySelectorAll("td")].slice(1).map(cell => cell.textContent.trim()) })));
}
/** ③–⑤ mode, parent row, box, values, acknowledgements. spec: { mode, includeParent, box, values, acks }. */
async function fillSettings(page, spec, evidence) {
  await check(page, `label[data-batch-mode="${spec.mode}"]`);
  control(evidence, "docking-batch-mode-radio", { mode: spec.mode });
  const parentBox = bt(page, "docking-batch-include-parent");
  if (spec.mode === "free") {
    if (spec.includeParent) await parentBox.check(); else await parentBox.uncheck();
    control(evidence, "docking-batch-include-parent", { checked: spec.includeParent });
  }
  await check(page, `label[data-batch-box="${spec.box.source}"]`);
  control(evidence, "docking-batch-box-radio", { source: spec.box.source });
  if (spec.box.source === "manual") {
    for (const [i, axis] of ["x", "y", "z"].entries()) {
      await fill(page, `docking-batch-center-${axis}`, spec.box.center[i]);
      await fill(page, `docking-batch-size-${axis}`, spec.box.size[i]);
    }
    control(evidence, "docking-batch-manual-box", { center: spec.box.center, size: spec.box.size });
  } else {
    await fill(page, "docking-batch-margin", spec.box.margin);
    control(evidence, "docking-batch-margin", { value: spec.box.margin });
  }
  await fill(page, "docking-batch-seed", spec.values.seed);
  await fill(page, "docking-batch-exhaustiveness", spec.values.exhaustiveness);
  await fill(page, "docking-batch-num-modes", spec.values.numModes);
  await fill(page, "docking-batch-energy-range", spec.values.energyRange);
  for (const id of ["docking-batch-seed", "docking-batch-exhaustiveness", "docking-batch-num-modes", "docking-batch-energy-range"])
    control(evidence, id, {});
  if (spec.mode === "core_fixed") {
    await fill(page, "docking-batch-conformers", spec.values.conformers);
    control(evidence, "docking-batch-conformers", {});
  }
  for (const key of ACK_KEYS) {
    const box = batch(page).locator(`label[data-batch-ack="${key}"] input`);
    if (spec.acks.includes(key)) await box.check(); else await box.uncheck();
    control(evidence, `docking-batch-ack-${key}`, { checked: spec.acks.includes(key) });
  }
}
/** Click 시작 전 확인 보기; returns the server response (what the view shows) and the view's DOM. */
async function preflight(page, run, evidence) {
  await waitFor(page, async () => await bt(page, "docking-batch-preflight").isEnabled() ? true : null, "preflight enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/docking/batches/preflight`, { timeout: 60000 });
  await bt(page, "docking-batch-preflight").click();
  const response = await posted;
  const body = await response.json();
  control(evidence, "docking-batch-preflight", { status: response.status(), admitted: body.admission?.admitted });
  return { status: response.status(), body, request: response.request().postDataJSON(), view: await preflightView(page, body) };
}
async function preflightView(page, body) {
  if (!body.admission.admitted) {
    await bt(page, "docking-batch-preflight-refused").waitFor({ timeout: 30000 });
    return { refused: clean(await bt(page, "docking-batch-preflight-refused").textContent()),
      reasonCode: await bt(page, "docking-batch-preflight-refused").getAttribute("data-reason-code") };
  }
  const view = bt(page, "docking-batch-preflight-view");
  await waitFor(page, async () => await view.count() &&
    await view.getAttribute("data-new-dockings") === String(body.new_dockings) ? true : null, "preflight view", 30000);
  return {
    newDockings: Number(await view.getAttribute("data-new-dockings")),
    reusedRows: Number(await view.getAttribute("data-reused-rows")),
    shortfallCalls: Number(await view.getAttribute("data-shortfall-calls")),
    shortfallWall: Number(await view.getAttribute("data-shortfall-wall")),
    mayBePartial: await view.getAttribute("data-may-be-partial"),
    lines: Object.fromEntries(await view.locator(".mw-ligand-fact").evaluateAll(items => items.map(item =>
      [item.querySelector("dt").textContent.trim(), item.querySelector("dd").textContent.trim()]))),
    rows: await bt(page, "docking-batch-preflight-rows").locator("li").evaluateAll(items => items.map(item => ({
      row: Number(item.getAttribute("data-row-index")), reuse: item.getAttribute("data-reuse") === "true",
      text: item.textContent.trim() }))),
    statements: await bt(page, "docking-batch-preflight-statements").locator("li[data-statement]").evaluateAll(items =>
      items.map(item => ({ id: item.getAttribute("data-statement"), text: item.textContent.trim() }))),
    existingJob: await bt(page, "docking-batch-existing-job").getAttribute("data-job-id", { timeout: 1000 }).catch(() => null),
    approvalButtons: await bt(page, "docking-batch-limit-approve").count(),
    start: await startState(page),
  };
}
/** The displayed preflight lines equal the server numbers, and the server numbers equal the hand arithmetic. */
function preflightMatches(pf, { rows, reused, budget }) {
  const body = pf.body, view = pf.view;
  assert.equal(pf.status, 200);
  assert.equal(body.admission.admitted, true, JSON.stringify(body.admission));
  assert.equal(body.starts_job, false);
  const n = rows - reused;
  assert.equal(body.new_dockings, n);
  assert.equal(body.reused_rows, reused);
  assert.deepEqual(body.needed, neededFor(n), "needed differs from spec 6.3 arithmetic");
  assert.deepEqual(body.shortfall, shortfallFor(body.needed, body.remaining), "shortfall differs from needed - remaining");
  assert.equal(body.full_batch_may_be_partial, n * 300 > 7200);
  if (budget) {
    assert.equal(body.remaining.expensive_calls, budget.expensive_calls.limit - budget.expensive_calls.used);
    assert.ok(body.remaining.wall_clock_s <= budget.wall_clock_s.limit - budget.wall_clock_s.used + 1e-6);
  }
  assert.equal(view.newDockings, n);
  assert.equal(view.reusedRows, reused);
  assert.equal(view.shortfallCalls, body.shortfall.expensive_calls);
  assert.equal(view.shortfallWall, body.shortfall.wall_clock_s);
  assert.equal(view.lines["새로 계산할 행"], `${n}개`);
  assert.equal(view.lines["재사용"], `${REUSED_LABEL} ${reused}개 (과금하지 않음)`);
  assert.equal(view.lines["필요"], `${pairText(body.needed)} (최대)`);
  assert.equal(view.lines["현재 잔여"], pairText(body.remaining));
  assert.equal(view.lines["부족분"], pairText(body.shortfall));
  assert.equal(view.lines["과금"], `시작하면 ${n}단위가 소진되고 중간에 멈춰도 돌려받지 않음`);
  assert.ok(view.lines["대기"].includes("최대 약 2시간"), view.lines["대기"]);
  assert.equal("시간 상한" in view.lines, body.full_batch_may_be_partial);
  assert.equal(view.rows.length, rows);
  view.rows.forEach((row, i) => {
    assert.equal(row.row, body.rows[i].row_index);
    assert.equal(row.reuse, body.rows[i].reuse);
    assert.ok(row.text.endsWith(row.reuse ? REUSED_LABEL : "새로 계산"), row.text);
  });
  assert.deepEqual(view.statements, [{ id: "B1", text: B.B1 }], "preflight statement is not B1 verbatim");
  const shortfall = body.shortfall.expensive_calls > 0 || body.shortfall.wall_clock_s > 0;
  assert.equal(view.approvalButtons, shortfall ? 1 : 0, "limit approval shown iff shortfall > 0");
  return { n, needed: body.needed, remaining: body.remaining, shortfall: body.shortfall, lines: view.lines };
}
async function startState(page) {
  const button = bt(page, "docking-batch-start");
  return { enabled: await button.isEnabled(), blocked: clean(await bt(page, "docking-batch-start-blocked")
    .textContent({ timeout: 1000 }).catch(() => "")) };
}
async function jobPhase(page) {
  const job = bt(page, "docking-batch-job");
  if (!await job.count()) return null;
  return { phase: await job.getAttribute("data-batch-job-phase"), status: await job.getAttribute("data-batch-job-status"),
    id: await job.getAttribute("data-batch-job-id"), finished: Number(await job.getAttribute("data-finished-rows") ?? NaN),
    rows: Number(await job.getAttribute("data-rows") ?? NaN) };
}
async function budgetUsed(page, run) { return (await readApi(page, `/runs/${run}/budget`)).expensive_calls; }
/**
 * Click 일괄 시작 (real input); approve through 비싼 계산 승인 when asked, then 작업 시작; wait for the job to leave the
 * active states (or with `until: (phase) => bool`). Returns the phases, the backend job and the summary handle.
 */
async function runBatch(page, run, evidence, { until = null, timeout = 900000 } = {}) {
  const phases = [];
  const before = await budgetUsed(page, run);
  const previousJob = (await jobPhase(page))?.id ?? null;
  const jobsBefore = (await readApi(page, `/runs/${run}/jobs`)).length;
  await waitFor(page, async () => (await startState(page)).enabled ? true : null, "start enabled", 15000);
  await bt(page, "docking-batch-start").click();
  control(evidence, "docking-batch-start", { clicked: true });
  const settled = async () => {
    const value = await jobPhase(page);
    if (!value || value.id === previousJob) return null;
    if (["running", "done", "failed", "cancelled"].includes(value.phase)) return value;
    if (value.phase === "awaiting_approval" && await bt(page, "docking-batch-job-approve").isEnabled().catch(() => false)) return value;
    if (value.phase === "saved" && await bt(page, "docking-batch-job-start").isEnabled().catch(() => false)) return value;
    return null;
  };
  const first = await waitFor(page, settled, "batch job submitted", 120000);
  phases.push(first.phase);
  let approved = false;
  if (first.phase === "awaiting_approval") {
    await bt(page, "docking-batch-job-approve").click();
    approved = true;
    await waitFor(page, async () => (await settled())?.phase === "saved" ? true : null, "approval recorded", 30000);
    phases.push("saved");
    control(evidence, "docking-batch-job-approve", { clicked: true });
  }
  if ((await jobPhase(page)).phase === "saved" && await bt(page, "docking-batch-job-start").isEnabled().catch(() => false)) {
    await bt(page, "docking-batch-job-start").click();
    control(evidence, "docking-batch-job-start", { clicked: true });
  }
  const stop = until ?? (value => ["done", "failed", "cancelled"].includes(value.phase));
  const done = await waitFor(page, async () => {
    const value = await jobPhase(page);
    if (value && value.phase !== phases.at(-1)) phases.push(value.phase);
    return value && stop(value) ? value : null;
  }, "batch job", timeout);
  const job = await readApi(page, `/runs/${run}/jobs/${enc(done.id)}`);
  return { phases, approved, job, phase: done, handle: job.batch?.summary_handle ?? null, budgetBefore: before,
    budgetAfter: await budgetUsed(page, run), jobsBefore, jobsAfter: (await readApi(page, `/runs/${run}/jobs`)).length,
    notice: clean(await bt(page, "docking-batch-notice").textContent({ timeout: 1000 }).catch(() => "")) };
}
/** Choose a stored summary in ⑧ (radio); returns the table read from the DOM. */
async function openSummary(page, handle, evidence) {
  const radio = batch(page).locator(`label${attr("data-batch-summary", handle)} input`);
  await waitFor(page, async () => await radio.count() ? true : null, "summary listed", 30000);
  await radio.check();
  control(evidence, "docking-batch-summary-radio", { handle });
  await bt(page, "docking-batch-result").and(batch(page).locator(attr("data-batch-handle", handle))).waitFor({ timeout: 30000 });
  return resultTable(page);
}
async function resultTable(page) {
  const view = bt(page, "docking-batch-result");
  return {
    handle: await view.getAttribute("data-batch-handle"), status: await view.getAttribute("data-batch-status"),
    stopReason: await view.getAttribute("data-stop-reason"), mode: await view.getAttribute("data-batch-mode"),
    statusText: clean(await bt(page, "docking-batch-status").textContent()),
    statements: await bt(page, "docking-batch-statements").locator("li").evaluateAll(items => items.map(item =>
      ({ id: item.getAttribute("data-statement"), text: item.textContent.trim() }))),
    headers: await bt(page, "docking-batch-rows").locator("thead th").allTextContents(),
    caption: clean(await bt(page, "docking-batch-rows").locator("caption").textContent()),
    aria: await bt(page, "docking-batch-rows").locator("thead th").evaluateAll(items => items.map(item => item.getAttribute("aria-sort"))),
    rows: await bt(page, "docking-batch-rows").locator("tbody tr").evaluateAll(items => items.map(item => ({
      row: Number(item.getAttribute("data-row-index")), kind: item.getAttribute("data-row-kind"),
      state: item.getAttribute("data-state"), reused: item.getAttribute("data-reused") === "true",
      candidate: item.getAttribute("data-candidate-id"),
      cells: [...item.querySelectorAll("td")].map(cell => cell.textContent.trim()),
      openEnabled: !item.querySelector("button").disabled }))),
  };
}
/** Every displayed cell equals the stored summary row (and each score equals its per-row result's first row). */
function tableEquals(table, detail, stored, runsDir, run) {
  assert.equal(table.handle, detail.handle);
  assert.equal(table.status, stored.status);
  assert.equal(table.stopReason ?? null, stored.stop_reason);
  assert.equal(table.mode, stored.inputs.mode);
  assert.deepEqual(detail.summary, stored, "detail summary differs from the stored object");
  assert.equal(table.headers[3], "qvina 점수(kcal/mol)");
  assert.equal(table.caption, "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)");
  const want = ["B1", ...(stored.status === "partial" ? ["B2"] : []), ...(stored.inputs.include_parent ? ["B3"] : [])];
  assert.deepEqual(table.statements, want.map(id => ({ id, text: B[id] })), "batch statements differ from spec 5.4");
  assert.deepEqual(stored.limitations.batch_statements, want);
  const byIndex = Object.fromEntries(table.rows.map(row => [row.row, row]));
  assert.equal(table.rows.length, stored.rows.length);
  const reusedSet = new Set(detail.reused_rows);
  for (const row of stored.rows) {
    const shown = byIndex[row.row_index];
    assert.ok(shown, `row ${row.row_index} not shown`);
    assert.equal(shown.kind, row.kind);
    assert.equal(shown.state, row.state);
    assert.equal(shown.cells[0], String(row.row_index));
    assert.equal(shown.cells[1], row.kind === "parent" ? PARENT_LABEL : row.candidate_id);
    assert.ok(shown.cells[2].endsWith(`(${row.state})`), shown.cells[2]);
    if (row.state === "scored") {
      const result = storedObject(runsDir, run, row.result_handle);
      assert.equal(row.score_kcal_mol, result.modes[0].score_kcal_mol, "summary score is not the stored first row");
      assert.equal(shown.cells[3], halfUp(row.score_kcal_mol, 1));
      assert.equal(shown.cells[4], SCORE_ROW_LABEL[stored.inputs.mode]);
      assert.equal(row.score_row_label, SCORE_ROW_LABEL[stored.inputs.mode]);
      assert.equal(result.inputs.mode, stored.inputs.mode);
      assert.deepEqual(result.parameters, stored.parameters);
      assert.deepEqual(result.box, stored.box);
    } else {
      assert.equal(row.score_kcal_mol, null);
      assert.equal(shown.cells[3], "", `row ${row.row_index} (${row.state}) shows a score`);
      assert.equal(shown.cells[4], "");
    }
    if (["failed", "cancelled", "not_run"].includes(row.state)) {
      assert.ok(row.reason_code, `row ${row.row_index} without a reason`);
      assert.ok(shown.cells[5].endsWith(`(${row.reason_code})`), shown.cells[5]);
      assert.equal(row.result_handle, null);
      assert.ok(!/\d/.test(shown.cells[3] + shown.cells[4]), "a number is shown for an uncomputed row");
    } else assert.equal(shown.cells[5], "");
    assert.equal(shown.reused, reusedSet.has(row.row_index));
    assert.equal(shown.cells[6], shown.reused ? REUSED_LABEL : "");
    assert.equal(shown.openEnabled, !!row.result_handle);
  }
  return { rows: stored.rows.map(row => ({ row: row.row_index, state: row.state, reason: row.reason_code,
    score: row.score_kcal_mol, reused: reusedSet.has(row.row_index) })), counts: stored.counts };
}
/** Click each sortable header twice; the displayed order follows the independent sort oracle every time. */
async function sortChecks(page, stored, evidence) {
  const seen = [];
  for (const key of ["score", "candidate", "row"]) {
    for (const direction of ["asc", "desc"]) {
      await bt(page, `docking-batch-sort-${key}`).click();
      control(evidence, `docking-batch-sort-${key}`, { direction });
      const want = sortOracle(stored.rows, key, direction).map(row => row.row_index);
      const table = await waitFor(page, async () => {
        const value = await resultTable(page);
        return JSON.stringify(value.rows.map(row => row.row)) === JSON.stringify(want) ? value : null;
      }, `sort ${key} ${direction}`, 10000);
      const column = { row: 0, candidate: 1, score: 3 }[key];
      assert.equal(table.aria[column], direction === "asc" ? "ascending" : "descending");
      const unscored = stored.rows.filter(row => row.state !== "scored").length;
      seen.push({ key, direction, order: want, unscoredLast: key === "score" && unscored ? want.slice(-unscored) : [] });
    }
  }
  return seen;
}

// ------------------------------------------------------------------ mode main
async function modeMain(session, input, rec_, evidence, log) {
  const { page } = session;
  const o = oracle();
  const runsDir = input["runs-dir"];
  evidence.inputs.push(...[RECEPTOR, PARENT, PLANAR, WATER_ZINC, BLOCKS_SMI].map(fileRecord), ...o.files);
  const capabilities = await readApi(page, "/capabilities");
  const capability = capabilities.methods?.ligand_docking_batch;
  const single = capabilities.methods?.ligand_docking;
  assert.ok(capability?.available === true, `batch capability unavailable: ${JSON.stringify(capability)}`);
  evidence.capability = { available: capability.available, engine: capability.engine, pins: capability.pins,
    batch_pins: capability.batch_pins, limits: capability.limits };
  const scoreLabels = [capability.score_label, "qvina 점수(kcal/mol)"];
  const exempt = [...Object.values(B), ...(single?.limitations ?? [])];
  const wording = [];
  const checkWording = async where => {
    const found = forbiddenWords(await batchText(page), exempt, scoreLabels);
    wording.push({ where, found });
    return found;
  };
  await waitForBoot(page);

  // ---- run A: area, imports, real M17 set
  const runA = await rec_.step("R01-run", ["B-run-panel"], "구조 분석: click 새 run; click 리간드 설계·탐색: the batch area " +
    "uses the global run (no run choice), shows its capability line, no summaries and a blocked start", async () => {
    const run = await newRun(page);
    await openLigandTab(page);
    return { run, state: await batchState(page), global: await globalRun(page),
      capability: clean(await bt(page, "docking-batch-capability").textContent()),
      results: clean(await batch(page).locator('[data-batch-area="results"]').textContent()),
      runChoices: await batch(page).locator("#run-choice, [data-testid*='run-choice']").count(),
      start: await startState(page) };
  }, async value => {
    assert.match(value.run, /^run_/);
    assert.equal(value.state, "ready");
    assert.equal(value.global, value.run);
    assert.equal(value.runChoices, 0);
    assert.ok(value.capability.startsWith("qvina · qvina_dock_batch"), value.capability);
    assert.ok(value.results.includes("이 run에 일괄 결과가 없습니다."), value.results);
    assert.equal(value.start.enabled, false);
    return value;
  });
  const run = runA.run;
  evidence.runs.A = run;
  const inputs = await rec_.step("I01-inputs", ["B-m17-set"], "Docking area: choose prolif-vina-rec.pdb and then " +
    "synthetic-receptor-water-zinc.pdb (수용체), 가져오기 each; candidate area: the public-derived parent SDF and " +
    "synthetic-docking-blocks.smi, 가져오기, 점검 시작 (approval), atom 22, 후보 생성 시작: the set equals the fixture ids",
  async () => {
    const receptor = await importReceptor(page, run, RECEPTOR, evidence);
    const waterZinc = await importReceptor(page, run, WATER_ZINC, evidence);
    const m17 = await m17CandidateSet(page, run, PARENT, BLOCKS_SMI, evidence);
    return { receptor, waterZinc, ...m17 };
  }, async value => {
    assert.deepEqual(value.ids, o.candidateIds, "candidate ids or set order differ from the fixture");
    assert.deepEqual(o.m17Ids, o.candidateIds);
    assert.equal(value.inspectApproved, true, "the run's first expensive call did not ask for approval");
    const set = await readApi(page, `/runs/${run}/ligand/candidate_sets/detail?handle=${enc(value.set)}`);
    assert.equal(set.candidate_set.parent_sha256, fileRecord(PARENT).sha256);
    return value;
  });
  evidence.handles.A = { receptor: inputs.receptor, waterZinc: inputs.waterZinc, set: inputs.set };

  // ---- candidate selection from the M17 filter result, then the receptor refusal list
  const parentHandle = await rec_.step("S01-select", ["B-select"], "Batch area: 입력 목록 다시 읽기; choose the water/zinc " +
    "receptor, model 1, 없음, PDB CONECT; the candidate set and its parent SDF; filter 중원자 수 ≤ 45, 필터 적용, 필터 통과만 " +
    "보기: the rows equal the server's filtered page; tick the two shown candidates (last one first), clear the filter and " +
    "the passes-only view, tick the third: 선택 3 / 50", async () => {
    const reread = page.waitForResponse(response => response.request().method() === "GET" &&
      new URL(response.url()).pathname === `/api/runs/${run}/docking/prerequisites`, { timeout: 30000 });
    await bt(page, "docking-batch-prereq-refresh").click();
    control(evidence, "docking-batch-prereq-refresh", { clicked: true });
    const prereq = await (await reread).json();
    const setRow = prereq.candidate_sets.find(item => item.handle === inputs.set);
    const parent = setRow.parent_sdf_handles[0];
    await chooseReceptor(page, inputs.waterZinc, evidence);
    await chooseSet(page, inputs.set, parent, evidence);
    const empty = await selectionCount(page);
    await fill(page, "docking-batch-filter-heavy_atoms-max", "45");
    const filtered = page.waitForResponse(response => new URL(response.url()).pathname ===
      `/api/runs/${run}/ligand/candidate_sets/rows` && response.url().includes("heavy_atoms_max=45") &&
      response.url().includes("passes_only=true"), { timeout: 30000 });
    await bt(page, "docking-batch-filter-apply").click();
    control(evidence, "docking-batch-filter-apply", { heavy_atoms_max: 45 });
    await bt(page, "docking-batch-passes-only").check();
    control(evidence, "docking-batch-passes-only", { checked: true });
    const served = await (await filtered).json();
    const shownFiltered = await waitFor(page, async () => {
      const rows = await shownCandidates(page);
      return rows.length === served.rows.length ? rows : null;
    }, "filtered rows shown", 15000);
    const count = { total: await bt(page, "docking-batch-candidate-count").getAttribute("data-total"),
      passing: await bt(page, "docking-batch-candidate-count").getAttribute("data-passing"),
      hidden: await bt(page, "docking-batch-candidate-count").getAttribute("data-hidden") };
    for (const row of [...shownFiltered].reverse()) await tick(page, row.id, true, evidence);
    const afterTwo = await selectionCount(page);
    await bt(page, "docking-batch-passes-only").uncheck();
    await bt(page, "docking-batch-filter-clear").click();
    control(evidence, "docking-batch-filter-clear", { clicked: true });
    const all = await waitFor(page, async () => {
      const rows = await shownCandidates(page);
      return rows.length === o.candidateIds.length ? rows : null;
    }, "all rows shown", 15000);
    const third = all.find(row => !row.checked);
    await tick(page, third.id, true, evidence);
    return { parent, setParents: setRow.parent_sdf_handles, empty, served: served.rows.map(row => ({
      id: row.candidate.id, passes: row.passes_all })), shownFiltered, count, afterTwo, all: await shownCandidates(page),
      third: third.id, final: await selectionCount(page) };
  }, async value => {
    const passing = o.candidateIds.filter(id => o.heavyAtoms[id] <= 45);
    assert.deepEqual(value.served.map(row => row.id), passing, "server filter differs from the stored properties");
    assert.deepEqual(value.shownFiltered.map(row => row.id), value.served.map(row => row.id), "shown rows differ from served");
    assert.equal(value.count.total, String(o.candidateIds.length));
    assert.equal(value.count.passing, String(passing.length));
    assert.equal(value.count.hidden, String(o.candidateIds.length - passing.length));
    assert.deepEqual(value.empty, { selected: 0, text: `선택 0 / ${MAX_CANDIDATES} · 일괄에는 고른 후보 id만 후보 집합 순서로 ` +
      "기록합니다(필터 조건은 기록하지 않음)." });
    assert.equal(value.afterTwo.selected, 2);
    assert.ok(value.final.text.startsWith(`선택 3 / ${MAX_CANDIDATES}`), value.final.text);
    assert.ok(value.all.every(row => row.checked && !row.disabled));
    return value;
  });
  await rec_.step("S02-refusal", ["B-refusal"], "Choose 자유 도킹, 부모 기준 행, 리간드 범위+여백 8, seed 42, exhaustiveness 1, " +
    "num_modes 3, the three acknowledgements; 시작 전 확인 보기 with the water/zinc receptor: refused " +
    "receptor_unsupported_residue with the refusal list (seven residue fields, nulls kept, atom names) equal to the fixture " +
    "oracle; start stays blocked; nothing is created", async () => {
    await fillSettings(page, { mode: "free", includeParent: true, box: { source: "ligand_range", margin: String(o.box.margin) },
      values: FAST, acks: ACK_KEYS }, evidence);
    const jobsBefore = (await readApi(page, `/runs/${run}/jobs`)).length;
    const eventsBefore = (await runEvents(page, run)).length;
    const pf = await preflight(page, run, evidence);
    const list = bt(page, "docking-refusal-list");
    await list.waitFor({ timeout: 30000 });
    return { pf, source: await list.getAttribute("data-docking-refusal-source"), reasonCode: await list.getAttribute("data-reason-code"),
      total: await list.getAttribute("data-total"), lines: (await list.locator("li[data-refusal-item]").allTextContents()).map(clean),
      heading: clean(await list.locator("span").first().textContent()), start: await startState(page), jobsBefore,
      jobsAfter: (await readApi(page, `/runs/${run}/jobs`)).length, eventsBefore, eventsAfter: (await runEvents(page, run)).length };
  }, async value => {
    const want = o.refusal.receptor_unsupported_residue;
    assert.equal(value.pf.body.admission.admitted, false);
    assert.equal(value.pf.body.admission.reason_code, "receptor_unsupported_residue");
    assert.deepEqual(value.pf.body.admission.detail.items, want, "API refusal items differ from the fixture oracle");
    assert.equal(value.pf.view.reasonCode, "receptor_unsupported_residue");
    assert.ok(value.pf.view.refused.includes("(receptor_unsupported_residue)"), value.pf.view.refused);
    assert.equal(value.source, "admission");
    assert.equal(value.total, String(want.length));
    assert.deepEqual(value.lines, want.map(m18.refusalLine), "screen refusal lines differ from the fixture oracle");
    assert.ok(value.heading.includes("(receptor_unsupported_residue)"), value.heading);
    assert.equal(value.start.enabled, false);
    assert.equal(value.jobsAfter, value.jobsBefore);
    assert.equal(value.eventsAfter, value.eventsBefore, "a preflight read wrote events");
    const found = await checkWording("refusal");
    assert.deepEqual(found, [], JSON.stringify(found));
    return { lines: value.lines, reason: value.reasonCode };
  });

  // ---- free batch with the parent row
  const freePreflight = await rec_.step("F01-preflight", ["B-preflight", "B-no-approval"], "Choose prolif-vina-rec.pdb " +
    "again (model 1, 없음, PDB CONECT); 시작 전 확인 보기: N 4 (parent + 3), needed 4 units and 1500 s, remaining = budget, " +
    "shortfall 0, the no-refund note, B1; rows in set order (parent first, not click order); no limit approval shown",
  async () => {
    await chooseReceptor(page, inputs.receptor, evidence);
    const budget = await readApi(page, `/runs/${run}/budget`);
    return { pf: await preflight(page, run, evidence), budget };
  }, async value => {
    const facts = preflightMatches(value.pf, { rows: 4, reused: 0, budget: value.budget });
    assert.deepEqual(value.pf.body.candidate_ids, o.candidateIds, "candidate ids not in set order");
    assert.deepEqual(value.pf.request.candidate_ids, o.candidateIds);
    assert.deepEqual(value.pf.body.rows.map(row => [row.kind, row.candidate_id]),
      [["parent", null], ...o.candidateIds.map(id => ["candidate", id])]);
    assert.deepEqual(facts.shortfall, { expensive_calls: 0, wall_clock_s: 0 });
    assert.deepEqual(facts.needed, { expensive_calls: 4, wall_clock_s: 1500 });
    assert.equal(value.pf.view.start.enabled, true, value.pf.view.start.blocked);
    const found = await checkWording("free preflight");
    assert.deepEqual(found, [], JSON.stringify(found));
    return facts;
  });
  const free = await rec_.step("F02-run", ["B-run"], "Click 일괄 시작: no second approval (the M17 inspection had it); the " +
    "real qvina batch runs to done; exactly 4 expensive units; the summary is listed but not opened", async () =>
    runBatch(page, run, evidence), async value => {
    assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
    assert.equal(value.job.protocol_id, "qvina_batch_dock_v1");
    assert.equal(value.approved, false);
    assert.match(value.handle ?? "", /\/docking_batch_result\//);
    assert.equal(value.budgetAfter.used, value.budgetBefore.used + freePreflight.pf.body.new_dockings, "units differ from N");
    assert.equal(value.jobsAfter, value.jobsBefore + 1);
    assert.equal(value.job.batch.finished_rows, 4);
    assert.ok(value.notice.includes(value.handle.split("/").at(-1).slice(0, 12)), value.notice);
    await waitFor(page, async () => await batch(page).locator(`label${attr("data-batch-summary", value.handle)}`).count()
      ? true : null, "summary listed", 30000);
    assert.equal(await bt(page, "docking-batch-result").count(), 0, "the summary was opened automatically");
    return { job: value.job.job_id, handle: value.handle, budget: [value.budgetBefore, value.budgetAfter] };
  });
  evidence.handles.A.free = free.handle;
  const freeJob = free.job.job_id;
  const freeStored = storedObject(runsDir, run, free.handle);
  // the start needs a preflight of exactly these arguments, so the preflight request is the job's argument set
  evidence.freeArgs = { run, job: freeJob, summary: free.handle, args: freePreflight.pf.request };
  await rec_.step("T01-table", ["B-table"], "Choose the summary: status 완료, B1 and B3, settings, and every row (state, " +
    "score = stored first row with ROUND_HALF_UP, score target, empty reason, no reuse) equal the stored summary", async () => {
    const table = await openSummary(page, free.handle, evidence);
    return { table, detail: await readApi(page, `/runs/${run}/docking/batches/detail?handle=${enc(free.handle)}`) };
  }, async value => {
    const facts = tableEquals(value.table, value.detail, freeStored, runsDir, run);
    assert.equal(freeStored.status, "complete");
    assert.equal(freeStored.stop_reason, null);
    assert.ok(freeStored.rows.every(row => row.state === "scored"));
    assert.ok(value.table.statusText.includes("완료 (complete)"));
    const found = await checkWording("free table");
    assert.deepEqual(found, [], JSON.stringify(found));
    return facts;
  });
  await rec_.step("T02-sort", ["B-sort"], "Click 점수, 후보 id and 행 번호 headers twice each: the order follows the stored " +
    "values (display order only; no rank column), aria-sort follows", () => sortChecks(page, freeStored, evidence),
  async value => {
    const table = await resultTable(page);
    assert.ok(!table.headers.some(text => /순위|rank/i.test(text)));
    return value;
  });
  await rec_.step("T03-detail", ["B-detail"], "Click 상세 열기 of row 1: the M18 docking area above opens that row's stored " +
    "result (mode table = stored); click 모드 1 내려받기: bytes equal the stored pose_sdf", async () => {
    const row = freeStored.rows.find(item => item.row_index === 1);
    await bt(page, "docking-batch-open-1").click();
    control(evidence, "docking-batch-open", { row: 1 });
    const view = dock(page).locator(`[data-testid="docking-result"]${attr("data-docking-result-handle", row.result_handle)}`);
    await view.waitFor({ timeout: 30000 });
    const modes = await view.locator('[data-testid="docking-modes"] tbody tr[data-mode]').evaluateAll(items => items.map(item =>
      ({ mode: Number(item.getAttribute("data-mode")), cells: [...item.querySelectorAll("td")].map(cell => cell.textContent.trim()) })));
    const downloaded = await downloadByClick(rec_.app, dt(page, "docking-download-1"));
    const bytes = fs.readFileSync(downloaded.downloaded);
    return { handle: row.result_handle, modes, bytes, url: downloaded.url, filename: downloaded.filename,
      served: await readBytes(page, `/runs/${run}/docking/results/pose_sdf?handle=${enc(row.result_handle)}&mode=1`) };
  }, async value => {
    const stored = storedObject(runsDir, run, value.handle);
    assert.equal(stored.inputs.ligand.source, "candidate");
    assert.equal(stored.inputs.ligand.candidate_id, o.candidateIds[0]);
    assert.equal(value.modes.length, stored.modes.length);
    value.modes.forEach((row, i) => {
      assert.equal(row.mode, i + 1);
      assert.equal(row.cells[0], `모드 ${i + 1}(엔진 출력 순서)`);
      assert.equal(row.cells[1], halfUp(stored.modes[i].score_kcal_mol, 1));
    });
    assert.equal(sha(value.bytes), sha(Buffer.from(stored.modes[0].pose_sdf, "utf8")), "download differs from stored pose_sdf");
    assert.equal(sha(value.served), sha(value.bytes));
    return { handle: value.handle, modes: value.modes.length, sha256: sha(value.bytes), filename: value.filename };
  });

  // ---- identical batch (existing job, no new job) and a subset batch (all rows reused)
  await rec_.part("reuse", ["B-dedupe", "B-reuse"], async () => {
    await rec_.step("U01-identical", ["B-dedupe"], "Same inputs: 시작 전 확인 보기 shows N 0, 4 reused rows, the existing job; " +
      "click 일괄 시작: the existing job is shown again (no new job, no unit)", async () => {
      const pf = await preflight(page, run, evidence);
      const before = await budgetUsed(page, run);
      const jobsBefore = (await readApi(page, `/runs/${run}/jobs`)).length;
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/jobs`, { timeout: 60000 });
      await bt(page, "docking-batch-start").click();
      control(evidence, "docking-batch-start", { identical: true });
      const response = await posted;
      const body = await response.json();
      await waitFor(page, async () => clean(await bt(page, "docking-batch-notice").textContent({ timeout: 1000 }).catch(() => ""))
        .includes("같은 입력의 기존 일괄 작업") ? true : null, "existing job notice", 30000);
      return { pf, status: response.status(), job: body, before, after: await budgetUsed(page, run), jobsBefore,
        jobsAfter: (await readApi(page, `/runs/${run}/jobs`)).length,
        notice: clean(await bt(page, "docking-batch-notice").textContent()) };
    }, async value => {
      preflightMatches(value.pf, { rows: 4, reused: 4 });
      assert.equal(value.pf.view.existingJob, freeJob);
      assert.ok(value.pf.view.rows.every(row => row.reuse));
      assert.equal(value.status, 200);
      assert.equal(value.job.job_id, freeJob, "a new job was created for an identical batch");
      assert.equal(value.jobsAfter, value.jobsBefore);
      assert.deepEqual(value.after, value.before, "an identical batch was charged");
      assert.ok(value.notice.includes(freeJob) && value.notice.includes("새 작업을 만들지 않았습니다"), value.notice);
      return { job: value.job.job_id, notice: value.notice };
    });
    const subset = await rec_.step("U02-subset", ["B-reuse"], "Untick 부모 기준 행: 시작 전 확인 보기 shows N 0 and 3 reused " +
      "rows; 일괄 시작 runs a new job with no unit; its summary marks every row 저장된 결과 재사용 with the stored handles",
    async () => {
      await bt(page, "docking-batch-include-parent").uncheck();
      control(evidence, "docking-batch-include-parent", { checked: false });
      const pf = await preflight(page, run, evidence);
      const job = await runBatch(page, run, evidence);
      const table = await openSummary(page, job.handle, evidence);
      return { pf, ...job, table, detail: await readApi(page, `/runs/${run}/docking/batches/detail?handle=${enc(job.handle)}`) };
    }, async value => {
      preflightMatches(value.pf, { rows: 3, reused: 3 });
      assert.deepEqual(value.pf.body.needed, { expensive_calls: 0, wall_clock_s: 60 });
      assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
      assert.notEqual(value.job.job_id, freeJob);
      assert.deepEqual(value.budgetAfter, value.budgetBefore, "reused rows were charged");
      const stored = storedObject(runsDir, run, value.handle);
      tableEquals(value.table, value.detail, stored, runsDir, run);
      assert.ok(value.table.rows.every(row => row.reused && row.cells[6] === REUSED_LABEL), "reuse marks missing");
      assert.deepEqual(stored.rows.map(row => row.result_handle), freeStored.rows.slice(1).map(row => row.result_handle),
        "reused rows do not point at the stored results");
      const found = await checkWording("reuse table");
      assert.deepEqual(found, [], JSON.stringify(found));
      return { job: value.job.job_id, handle: value.handle, budget: value.budgetAfter };
    });
    evidence.handles.A.subset = subset.handle;
  });

  // ---- core-fixed: parent row disabled; shortfall → explicit limit approval → batch
  await rec_.part("core-fixed", ["B-core-parent-disabled", "B-limit-approval", "B-core-fixed"], async () => {
    await rec_.step("C01-parent-disabled", ["B-core-parent-disabled"], "Tick 부모 기준 행, then choose 코어 고정: the parent " +
      "row is cleared and disabled with batch_parent_not_allowed (no number)", async () => {
      await bt(page, "docking-batch-include-parent").check();
      await check(page, 'label[data-batch-mode="core_fixed"]');
      control(evidence, "docking-batch-mode-radio", { mode: "core_fixed" });
      const box = bt(page, "docking-batch-include-parent");
      return { checked: await box.isChecked(), disabled: await box.isDisabled(),
        reason: await bt(page, "docking-batch-parent-row").getAttribute("data-disabled-reason"),
        note: clean(await bt(page, "docking-batch-parent-disabled").textContent()) };
    }, async value => {
      assert.equal(value.checked, false);
      assert.equal(value.disabled, true);
      assert.ok(value.reason.includes("(batch_parent_not_allowed)"), value.reason);
      assert.ok(value.note.includes("(batch_parent_not_allowed)"), value.note);
      assert.ok(!/\d/.test(value.note), value.note);
      return value;
    });
    const raise = await rec_.step("C02-shortfall", ["B-limit-approval"], "conformers 5; 시작 전 확인 보기: N 3 but 2 units " +
      "remain → shortfall 1 unit, 이 일괄에 필요한 만큼 한도를 올림 is shown and the start is blocked " +
      "(batch_limit_raise_required); click it: the limit rises by the shortfall only (8 → 9, by human, with the batch " +
      "context), the preflight is read again with no shortfall", async () => {
      await fillSettings(page, { mode: "core_fixed", includeParent: false, box: { source: "ligand_range",
        margin: String(o.box.margin) }, values: { ...FAST, conformers: CORE_CONFORMERS }, acks: ACK_KEYS }, evidence);
      const budget = await readApi(page, `/runs/${run}/budget`);
      const pf = await preflight(page, run, evidence);
      const blocked = await startState(page);
      const eventsBefore = (await runEvents(page, run)).length;
      const approval = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/docking/batches/limit_approval`, { timeout: 60000 });
      const reread = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/docking/batches/preflight`, { timeout: 60000 });
      await bt(page, "docking-batch-limit-approve").click();
      control(evidence, "docking-batch-limit-approve", { clicked: true });
      const approved = await (await approval).json();
      const again = await (await reread).json();
      await bt(page, "docking-batch-limit-done").waitFor({ timeout: 30000 });
      const view = await preflightView(page, again);
      const events = (await runEvents(page, run)).slice(eventsBefore);
      return { budget, pf, blocked, approved, again, view, events, done: clean(await bt(page, "docking-batch-limit-done").textContent()),
        raisedAttr: await bt(page, "docking-batch-limit-done").getAttribute("data-raised"),
        budgetAfter: await readApi(page, `/runs/${run}/budget`) };
    }, async value => {
      const facts = preflightMatches(value.pf, { rows: 3, reused: 0, budget: value.budget });
      assert.deepEqual(facts.shortfall, { expensive_calls: 1, wall_clock_s: 0 });
      assert.equal(value.blocked.enabled, false);
      assert.ok(value.blocked.blocked.includes("(batch_limit_raise_required)"), value.blocked.blocked);
      assert.equal(value.approved.raised, true);
      assert.deepEqual(value.approved.increase, { expensive_calls: 1, wall_clock_s: 0 }, "the raise is not the shortfall");
      assert.equal(value.approved.limits_after.expensive_calls, value.budget.expensive_calls.limit + 1);
      assert.equal(value.budgetAfter.expensive_calls.limit, value.budget.expensive_calls.limit + 1);
      assert.equal(value.budgetAfter.expensive_calls.used, value.budget.expensive_calls.used, "the approval used budget");
      const updated = value.events.filter(event => event.type === "budget_limit_updated");
      assert.equal(updated.length, 1, JSON.stringify(value.events.map(event => event.type)));
      assert.equal(updated[0].by, "human");
      assert.equal(updated[0].limits.expensive_calls, value.budget.expensive_calls.limit + 1);
      assert.equal(updated[0].context.batch_input_sha256, value.pf.body.batch_input_sha256);
      assert.deepEqual(updated[0].context.increase, value.approved.increase);
      assert.ok(!value.events.some(event => event.type.startsWith("job_") || event.type === "object_created"),
        "the approval created a job or an object");
      assert.equal(value.raisedAttr, "true");
      assert.ok(value.done.includes("되돌리지 않음"), value.done);
      assert.deepEqual(value.again.shortfall, { expensive_calls: 0, wall_clock_s: 0 });
      assert.equal(value.view.approvalButtons, 0, "approval still offered without a shortfall");
      assert.equal(value.view.lines["현재 잔여"], pairText(value.again.remaining));
      assert.equal(value.view.start.enabled, true, value.view.start.blocked);
      return { shortfall: facts.shortfall, increase: value.approved.increase, limitsBefore: value.approved.limits_before,
        limitsAfter: value.approved.limits_after, event: updated[0].seq };
    });
    const core = await rec_.step("C03-core-run", ["B-core-fixed", "B-limit-approval"], "Click 일괄 시작: the core-fixed batch " +
      "runs (3 units, now 9 of 9); its rows show 샘플 1(점수 오름차순 나열) scores equal to the stored results", async () => {
      const job = await runBatch(page, run, evidence);
      const table = await openSummary(page, job.handle, evidence);
      return { ...job, table, detail: await readApi(page, `/runs/${run}/docking/batches/detail?handle=${enc(job.handle)}`) };
    }, async value => {
      assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
      assert.equal(value.budgetAfter.used, value.budgetBefore.used + 3);
      assert.equal(value.budgetAfter.used, value.budgetAfter.limit);
      const stored = storedObject(runsDir, run, value.handle);
      assert.equal(stored.method, "qvina_core_fixed_score_only_v1");
      assert.equal(stored.inputs.include_parent, false);
      assert.equal(stored.parameters.conformers, Number(CORE_CONFORMERS));
      const facts = tableEquals(value.table, value.detail, stored, runsDir, run);
      const found = await checkWording("core table");
      assert.deepEqual(found, [], JSON.stringify(found));
      return { handle: value.handle, raise, ...facts };
    });
    evidence.handles.A.core = core.handle;
  });

  // ---- report of the free batch → 지식·보고서 list → downloads; global budget = backend
  await rec_.part("report", ["B-report", "B-limit-approval"], async () => {
    const cases = ["B-report"];
    const created = await rec_.step("P01-report", cases, "Choose the free summary; click 보고서 만들기", async () => {
      await openSummary(page, free.handle, evidence);
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
      await bt(page, "docking-batch-report").click();
      control(evidence, "docking-batch-report", { clicked: true });
      const response = await posted;
      const body = await response.json();
      await bt(page, "docking-batch-report-done").waitFor({ timeout: 30000 });
      return { status: response.status(), handle: body.handle, request: response.request().postDataJSON(), manifest: body.manifest,
        done: await bt(page, "docking-batch-report-done").getAttribute("data-report-handle") };
    }, async value => {
      assert.equal(value.done, value.handle);
      assert.equal(value.manifest.analysis_type, "ligand_docking_batch");
      assert.equal(value.manifest.result_handle, free.handle);
      assert.deepEqual(value.request, { result_handle: free.handle });
      const listed = (await readApi(page, `/runs/${run}/reports`)).find(item => item.handle === value.handle);
      assert.ok(listed, "created report not in the backend report list");
      return { handle: value.handle };
    });
    const library = page.getByRole("region", { name: "보고서 보관함", exact: true });
    const reports = library.getByRole("region", { name: "저장된 보고서", exact: true });
    const content = library.getByRole("region", { name: "선택한 항목 내용", exact: true });
    await rec_.step("P02-listed", ["B-report", "B-limit-approval"], "Click 지식·보고서: the global budget equals the backend " +
      "(raised limit kept); the list shows 리간드 도킹 일괄 보고서; click it: the text equals the saved Markdown", async () => {
      await selectTab(page, "지식·보고서");
      const budget = await waitFor(page, async () => {
        const backend = await budgetUsed(page, run);
        const shown = clean(await page.locator(".mw-app-budget").textContent());
        return shown === `expensive ${backend.used}/${backend.limit}` ? { shown, backend } : null;
      }, "global budget equals backend /budget", 15000);
      const row = reports.locator("li button").filter({ hasText: created.handle });
      await row.waitFor({ timeout: 30000 });
      const kind = clean(await row.locator(".mw-library-kind").textContent());
      await row.click();
      const pre = content.getByLabel(`저장된 보고서 ${created.handle}`, { exact: true });
      await pre.waitFor({ timeout: 30000 });
      return { kind, text: await pre.textContent(), budget };
    }, async value => {
      assert.equal(value.kind, "리간드 도킹 일괄 보고서");
      const saved = await readApi(page, `/runs/${run}/reports/selected?handle=${enc(created.handle)}`);
      assert.equal(value.text, saved.markdown);
      assert.ok(value.text.includes(capability.score_label), "report lacks the score name");
      assert.ok(value.text.includes(B.B1) && value.text.includes(B.B3), "report lacks B1/B3");
      assert.equal(value.budget.backend.limit, 9, "raised limit not kept");
      return { kind: value.kind, markdownSha256: sha(Buffer.from(value.text)), budget: value.budget.shown };
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

  // ---- run B: planar parent → the parent row fails ligand_not_3d and the batch continues
  await rec_.part("failing-row", ["B-fail-row", "B-sort"], async () => {
    const made = await rec_.step("X01-inputs", ["B-fail-row"], "구조 분석: 새 run (run B); 리간드 설계·탐색: the receptor " +
      "(docking area) and, in the candidate area, the planar parent fixture + blocks: real M17 inspection (approval) and " +
      "enumeration", async () => {
      const id = await newRun(page);
      await openLigandTab(page);
      const receptor = await importReceptor(page, id, RECEPTOR, evidence);
      const m17 = await m17CandidateSet(page, id, PLANAR, BLOCKS_SMI, evidence);
      return { run: id, receptor, ...m17 };
    }, async value => {
      assert.equal(value.ids.length, 3);
      const set = await readApi(page, `/runs/${value.run}/ligand/candidate_sets/detail?handle=${enc(value.set)}`);
      assert.equal(set.candidate_set.parent_sha256, fileRecord(PLANAR).sha256);
      return value;
    });
    evidence.runs.B = made.run;
    const failed = await rec_.step("X02-batch", ["B-fail-row"], "Batch area: 입력 목록 다시 읽기, the receptor, the set and " +
      "its (planar) parent SDF, all three candidates, 자유 도킹 + 부모 기준 행, 직접 입력 box (oracle center and size), " +
      "seed 42; 시작 전 확인 보기 (N 4); 일괄 시작: the parent row fails ligand_not_3d with no score, the candidate rows " +
      "are scored, the batch is complete", async () => {
      await bt(page, "docking-batch-prereq-refresh").click();
      const prereq = await waitFor(page, async () => {
        const value = await readApi(page, `/runs/${made.run}/docking/prerequisites`);
        return await bt(page, "docking-batch-candidate-set").locator(`option${attr("value", made.set)}`).count() ? value : null;
      }, "set listed", 30000);
      const parent = prereq.candidate_sets.find(item => item.handle === made.set).parent_sdf_handles[0];
      await chooseReceptor(page, made.receptor, evidence);
      await chooseSet(page, made.set, parent, evidence);
      for (const id of made.ids) await tick(page, id, true, evidence);
      await fillSettings(page, { mode: "free", includeParent: true, box: { source: "manual",
        center: o.box.center.map(v => halfUp(v, 2)), size: o.box.size.map(v => halfUp(v, 2)) }, values: FAST, acks: ACK_KEYS },
      evidence);
      const pf = await preflight(page, made.run, evidence);
      const job = await runBatch(page, made.run, evidence);
      const table = await openSummary(page, job.handle, evidence);
      return { pf, ...job, table, detail: await readApi(page, `/runs/${made.run}/docking/batches/detail?handle=${enc(job.handle)}`) };
    }, async value => {
      preflightMatches(value.pf, { rows: 4, reused: 0 });
      assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
      const stored = storedObject(runsDir, made.run, value.handle);
      const facts = tableEquals(value.table, value.detail, stored, runsDir, made.run);
      assert.equal(stored.status, "complete");
      assert.deepEqual([stored.rows[0].kind, stored.rows[0].state, stored.rows[0].reason_code], ["parent", "failed", o.planarReason]);
      assert.ok(stored.rows.slice(1).every(row => row.state === "scored"), "candidate rows did not continue");
      assert.equal(value.table.rows.find(row => row.row === 0).openEnabled, false);
      assert.equal(value.budgetAfter.used, value.budgetBefore.used + 4, "the failed row was not one charged unit");
      const found = await checkWording("failing-row table");
      assert.deepEqual(found, [], JSON.stringify(found));
      return { handle: value.handle, ...facts };
    });
    evidence.handles.B = { set: made.set, summary: failed.handle };
    await rec_.step("X03-sort", ["B-sort", "B-fail-row"], "Click the headers on this batch: the failed parent row (no " +
      "score, no candidate id) stays last in both score directions and in the candidate id sort", async () =>
      sortChecks(page, storedObject(runsDir, made.run, failed.handle), evidence), async value => {
      for (const item of value.filter(entry => entry.key !== "row")) assert.equal(item.order.at(-1), 0, JSON.stringify(item));
      return value;
    });
  });

  // ---- a labeled dry-run run record (loopback API; the screen cannot make one). Created before run C so that run C's
  // 새 run click re-reads the run list (the list is read at boot and after 새 run).
  evidence.fixtureLabels.push(DRY_RUN_LABEL);
  const dryResponse = await page.request.post(new URL("/api/runs", page.url()).toString(), { data: {
    goal: "M19 QA dry-run record (labeled fixture)", context: [], dry_run: true, egress: "local_only" } });
  const dry = dryResponse.status() === 201 ? (await dryResponse.json()).run_id : null;
  evidence.runs.D = dry;

  // ---- run C: generated chain set → cancel mid-batch (partial), then the 50-candidate cap
  await rec_.part("cancel-and-cap", ["B-cancel", "B-cap"], async () => {
    evidence.fixtureLabels.push(CHAIN_LABEL);
    const chains = chainLibrary(input.artifacts);
    evidence.inputs.push(fileRecord(chains));
    const made = await rec_.step("K01-inputs", ["B-cancel", "B-cap"], "구조 분석: 새 run (run C); the receptor and, in the " +
      "candidate area, the public-derived parent + the labeled generated chain list: real M17 inspection and enumeration " +
      "(59 candidates, two pages)", async () => {
      const id = await newRun(page);
      await openLigandTab(page);
      const receptor = await importReceptor(page, id, RECEPTOR, evidence);
      const m17 = await m17CandidateSet(page, id, PARENT, chains, evidence);
      return { run: id, receptor, ...m17 };
    }, async value => { assert.ok(value.total > MAX_CANDIDATES, `only ${value.total} candidates`); return value; });
    evidence.runs.C = made.run;
    const cancelled = await rec_.step("K02-cancel", ["B-cancel"], "Batch area: the receptor, the set and parent, the first " +
      "three candidates, 자유 도킹, 리간드 범위+여백 8, seed 7, exhaustiveness 8; 시작 전 확인 보기 (N 3); 일괄 시작; once " +
      "one row is finished click 작업 취소: status partial / cancelled, the finished row kept with its score, the running " +
      "row cancelled and the rest not_run with the reason and no number; no worker or qvina2 process remains; no refund",
    async () => {
      await bt(page, "docking-batch-prereq-refresh").click();
      const prereq = await waitFor(page, async () => {
        const value = await readApi(page, `/runs/${made.run}/docking/prerequisites`);
        return await bt(page, "docking-batch-candidate-set").locator(`option${attr("value", made.set)}`).count() ? value : null;
      }, "set listed", 30000);
      const parent = prereq.candidate_sets.find(item => item.handle === made.set).parent_sdf_handles[0];
      await chooseReceptor(page, made.receptor, evidence);
      await chooseSet(page, made.set, parent, evidence);
      for (const id of made.ids.slice(0, 3)) await tick(page, id, true, evidence);
      await fillSettings(page, { mode: "free", includeParent: false, box: { source: "ligand_range",
        margin: String(o.box.margin) }, values: SLOW, acks: ACK_KEYS }, evidence);
      const pf = await preflight(page, made.run, evidence);
      const running = await runBatch(page, made.run, evidence, { until: value => value.phase === "running" && value.finished >= 1 ||
        ["done", "failed", "cancelled"].includes(value.phase) });
      const processes = jobProcesses(runsDir);
      const cancel = bt(page, "docking-batch-job-cancel");
      await waitFor(page, async () => await cancel.isEnabled().catch(() => false) ? true : null, "cancel enabled", 60000);
      await cancel.click();
      control(evidence, "docking-batch-job-cancel", { finishedBefore: running.phase.finished });
      const final = await waitFor(page, async () => {
        const value = await jobPhase(page);
        return value && ["cancelled", "failed", "done"].includes(value.phase) ? value : null;
      }, "job cancelled", 180000);
      const gone = await waitFor(page, async () => jobProcesses(runsDir).length === 0 ? true : null, "job processes gone", 60000)
        .then(() => true, () => false);
      const job = await readApi(page, `/runs/${made.run}/jobs/${enc(final.id)}`);
      const handle = job.batch?.summary_handle;
      const table = handle ? await openSummary(page, handle, evidence) : null;
      return { pf, running: running.phase, processesWhileRunning: processes, final, gone, left: jobProcesses(runsDir), job,
        handle, table, budgetBefore: running.budgetBefore, budgetAfter: await budgetUsed(page, made.run),
        detail: handle ? await readApi(page, `/runs/${made.run}/docking/batches/detail?handle=${enc(handle)}`) : null };
    }, async value => {
      preflightMatches(value.pf, { rows: 3, reused: 0 });
      assert.equal(value.running.phase, "running", "the batch ended before it could be cancelled");
      assert.ok(value.processesWhileRunning.some(item => item.command.includes("qvina2") ||
        item.command.includes("docking_batch_worker.py")), JSON.stringify(value.processesWhileRunning));
      assert.equal(value.job.status, "cancelled");
      assert.equal(value.final.phase, "cancelled");
      assert.equal(value.gone, true, JSON.stringify(value.left));
      assert.ok(value.handle, "no partial summary was published");
      const stored = storedObject(runsDir, made.run, value.handle);
      const facts = tableEquals(value.table, value.detail, stored, runsDir, made.run);
      assert.equal(stored.status, "partial");
      assert.equal(stored.stop_reason, "cancelled");
      const states = stored.rows.map(row => row.state);
      const firstOpen = states.findIndex(state => state !== "scored");
      assert.ok(firstOpen >= 1, `no finished row kept: ${states}`);
      assert.equal(states[firstOpen], "cancelled");
      assert.ok(states.slice(firstOpen + 1).every(state => state === "not_run"), `${states}`);
      assert.ok(stored.rows.slice(firstOpen).every(row => row.reason_code === "cancelled" && row.score_kcal_mol === null));
      assert.ok(value.table.statusText.includes("(partial)") && value.table.statusText.includes("(cancelled)"));
      assert.equal(value.budgetAfter.used, value.budgetBefore.used + 3, "a cancelled batch was refunded or overcharged");
      const found = await checkWording("partial table");
      assert.deepEqual(found, [], JSON.stringify(found));
      return { handle: value.handle, states, finishedBeforeCancel: value.running.finished, ...facts };
    });
    evidence.handles.C = { set: made.set, summary: cancelled.handle };
    await rec_.step("K03-cap", ["B-cap"], "Tick 47 more candidates (first page): 선택 50 / 50 and the full notice; 다음: " +
      "the remaining candidates cannot be ticked; 시작 전 확인 보기: N = 50 minus the finished rows (reused), needed N " +
      "units and 7800 s, shortfall, the may-be-partial note; the limit approval is offered (not clicked); start blocked", async () => {
      const shown = await shownCandidates(page);
      for (const row of shown.filter(item => !item.checked).slice(0, MAX_CANDIDATES - 3)) await tick(page, row.id, true, evidence);
      const count = await selectionCount(page);
      const full = clean(await bt(page, "docking-batch-selection-full").textContent());
      await batch(page).locator(".mw-ligand-candidates").getByRole("button", { name: "다음", exact: true }).click();
      const second = await waitFor(page, async () => {
        const rows = await shownCandidates(page);
        return rows.length && !shown.some(item => item.id === rows[0].id) ? rows : null;
      }, "second page", 15000);
      await batch(page).locator(".mw-ligand-candidates").getByRole("button", { name: "이전", exact: true }).click();
      const budget = await readApi(page, `/runs/${made.run}/budget`);
      const eventsBefore = (await runEvents(page, made.run)).length;
      const pf = await preflight(page, made.run, evidence);
      const finished = storedObject(runsDir, made.run, cancelled.handle).rows.filter(row => row.state === "scored").length;
      return { count, full, second, pf, budget, finished, eventsAfter: (await runEvents(page, made.run)).length, eventsBefore };
    }, async value => {
      assert.equal(value.count.selected, MAX_CANDIDATES);
      assert.ok(value.count.text.startsWith(`선택 ${MAX_CANDIDATES} / ${MAX_CANDIDATES}`));
      assert.ok(value.full.includes(`${MAX_CANDIDATES}개를 모두 골랐습니다`), value.full);
      assert.ok(value.second.length > 0 && value.second.every(row => !row.checked && row.disabled), "a 51st candidate is selectable");
      // the rows the cancelled batch finished are reused (same inputs); the cancelled and not-run rows are computed again
      const facts = preflightMatches(value.pf, { rows: MAX_CANDIDATES, reused: value.finished, budget: value.budget });
      assert.deepEqual(facts.needed, { expensive_calls: MAX_CANDIDATES - value.finished, wall_clock_s: 7800 });
      assert.equal(value.pf.body.full_batch_may_be_partial, true);
      assert.ok(value.pf.view.lines["시간 상한"].includes("2시간 안에 못 끝나면 끝낸 후보만 남음"), JSON.stringify(value.pf.view.lines));
      assert.ok(facts.shortfall.expensive_calls > 0);
      assert.equal(value.pf.view.approvalButtons, 1);
      assert.equal(value.pf.view.start.enabled, false);
      assert.equal(value.eventsAfter, value.eventsBefore, "the preflight wrote events");
      const found = await checkWording("cap preflight");
      assert.deepEqual(found, [], JSON.stringify(found));
      return { n: facts.n, needed: facts.needed, shortfall: facts.shortfall, secondPage: value.second.length };
    });
  });

  // ---- run D: a labeled dry-run run record → no limit approval control
  await rec_.part("dry-run", ["B-dry-run"], async () => {
    assert.ok(dry, `dry-run record not created: ${dryResponse.status()}`);
    await rec_.step("D01-dry-run", ["B-dry-run"], "구조 분석: choose the dry-run run; 리간드 설계·탐색: the batch area shows the " +
      "dry-run note (plans only, no limit raise) and no limit approval control; nothing is computed", async () => {
      await chooseRun(page, dry);
      await openLigandTab(page);
      return { note: clean(await bt(page, "docking-batch-dry-run").textContent()), approvals: await bt(page, "docking-batch-limit-area").count(),
        start: await startState(page), jobs: await readApi(page, `/runs/${dry}/jobs`) };
    }, async value => {
      assert.ok(value.note.includes("dry-run") && value.note.includes("한도 증액도 하지 않습니다"), value.note);
      assert.equal(value.approvals, 0);
      assert.equal(value.start.enabled, false);
      assert.equal(value.jobs.length, 0);
      return value;
    });
  });

  await rec_.part("processes", ["B-processes"], () => rec_.step("Z01-processes", ["B-processes"], "After every batch: no " +
    "batch worker, docking worker, M17 worker, guardian or qvina2 process remains under the runs folder", async () =>
    waitFor(page, async () => jobProcesses(runsDir).length === 0 ? { left: [] } : null, "no job processes", 60000)
      .catch(() => ({ left: jobProcesses(runsDir) })), async value => {
    assert.deepEqual(value.left, []);
    return value;
  }));

  evidence.wording = wording;
  for (const id of Object.values(evidence.runs).filter(Boolean)) evidence.providerCalls.push(await providerCalls(page, id));
  const wordingOk = wording.length >= 6 && wording.every(item => !item.found.length);
  rec_.append({ caseId: "WORDING", cases: ["B-wording"], status: wordingOk ? "pass" : "fail", checks: wording });
  if (!wordingOk) evidence.partFailures.push({ part: "wording", cases: ["B-wording"] });
  evidence.wordingPassed = wordingOk;
}

// ------------------------------------------------------------------ mode unavailable (backend without the environments)
async function modeUnavailable(session, input, rec_, evidence, log) {
  const { page } = session;
  evidence.fixtureLabels.push(input["fixture-label"] || UNAVAILABLE_LABEL);
  const capability = (await readApi(page, "/capabilities")).methods?.ligand_docking_batch ?? null;
  evidence.capability = capability && { available: capability.available, reason_code: capability.reason_code };
  assert.ok(capability && capability.available === false, `backend reports the batch available: ${JSON.stringify(capability)}`);
  assert.equal((await readApi(page, "/runs")).length, 0, "mode unavailable needs a fresh runs root");
  const noControls = async () => ({ state: await batchState(page), text: clean(await batch(page).textContent()),
    controls: await batch(page).locator("button, input, select, textarea, a, img, table").count() });
  await waitForBoot(page);
  await rec_.step("U01-no-run", ["B-no-run"], "No run yet: click 리간드 설계·탐색 → the batch area shows the no-run reason " +
    "only (no numbers, no controls)", async () => {
    await selectTab(page, TAB);
    await bt(page, "docking-batch-no-run").waitFor({ timeout: 15000 });
    return { ...await noControls(), reason: clean(await bt(page, "docking-batch-no-run").textContent()) };
  }, async value => {
    assert.equal(value.state, "unavailable");
    assert.ok(value.reason.includes(NO_RUN_REASON), value.reason);
    assert.ok(!/\d/.test(value.text), `a number is shown: ${value.text}`);
    assert.equal(value.controls, 0);
    return value;
  });
  const run = await rec_.step("U02-run", [], "Click 구조 분석, 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.runs.A = run;
  await rec_.step("U03-unavailable", ["B-unavailable"], "Click 리간드 설계·탐색: 사용할 수 없음 with the capability reason " +
    "(worker_missing); no numbers, no controls, no batch requests", async () => {
    const before = Date.now();
    await selectTab(page, TAB);
    await bt(page, "docking-batch-unavailable").waitFor({ timeout: 15000 });
    await page.waitForTimeout(2000);
    const batchReads = log.filter(row => row.at >= before && row.path.includes("/docking/batches")).map(row => `${row.method} ${row.path}`);
    return { ...await noControls(), reason: clean(await bt(page, "docking-batch-unavailable").textContent()), batchReads };
  }, async value => {
    assert.equal(value.state, "unavailable");
    assert.ok(value.reason.includes("사용할 수 없음"), value.reason);
    assert.ok(value.reason.includes(`(${capability.reason_code})`), value.reason);
    assert.ok(value.reason.includes(capability.reason), value.reason);
    assert.ok(!/\d/.test(value.text), `a number is shown: ${value.text}`);
    assert.equal(value.controls, 0);
    assert.deepEqual(value.batchReads, [], "the unavailable area sent batch requests");
    return value;
  });
  evidence.providerCalls.push(await providerCalls(page, run));
}

// ------------------------------------------------------------------ main
const RUNNERS = { main: modeMain, unavailable: modeUnavailable };
// Spec 13.6 cases the real environment cannot produce (never forged): kept with the tests that cover them.
const NOT_OBSERVED = [
  { case: "B-dry-run-shortfall", reason: "a dry-run run cannot hold a candidate set (M17 jobs only plan there), so an " +
    "admitted preflight with a shortfall cannot be reached in one; the dry-run note and the absent approval control are " +
    "observed. Covered by frontend/tests/docking-batch.test.cjs (limitApprovalOffered, batchStartBlockedReason dry-run) " +
    "and backend/tests/test_docking_batch_budget.py (dry-run permits no raise)." },
  { case: "B-null-result", reason: "qvina returns modes for every valid input here; no zero-mode row is forged. Covered " +
    "by the backend batch tests and frontend/tests/docking-batch.test.cjs." },
  { case: "B-time-limits", reason: "candidate_timeout (300 s), time_exhausted (7200 s), worker_failed and the 128 MiB " +
    "output cap need hours or a killed worker; covered by backend/tests/test_docking_batch_worker.py and " +
    "test_docking_batch_jobs.py with test-only reduced constants." },
];

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const evidence = { schema: "m19_docking_batch_evidence@1", mode: input.mode, runs: {}, inputs: [], handles: {},
    fixtureLabels: [], providerCalls: [], partFailures: [], controls: {}, startedAt: new Date().toISOString(),
    notObserved: input.mode === "main" ? NOT_OBSERVED : [] };
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
  if (input.mode === "main") cases["B-wording"] = evidence.wordingPassed === true ? "pass" : "fail";
  const providerZero = evidence.providerCalls.length > 0 && evidence.providerCalls.every(item => item.zero);
  const passed = !error && evidence.partFailures.length === 0 && offscreenComplete(proof) && proof.nonLoopbackRequests === 0 &&
    Object.keys(cases).length > 0 && Object.values(cases).every(value => value === "pass") && providerZero;
  evidence.finishedAt = new Date().toISOString();
  evidence.error = error ? String(error.stack ?? error) : null;
  evidence.requestCount = log.length;
  fs.writeFileSync(path.join(input.artifacts, "docking-batch-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  fs.writeFileSync(path.join(input.artifacts, "docking-batch-requests.jsonl"), log.map(row => JSON.stringify(row)).join("\n") + "\n");
  const harness = Object.fromEntries(["docking-batch-flow.cjs", "docking-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m19_case_ledger_row@1", mode: input.mode, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", cases, runId: evidence.runs.A ?? null, runs: evidence.runs,
    handles: evidence.handles, inputs: evidence.inputs, fixtureLabels: evidence.fixtureLabels, controls: evidence.controls,
    freeArgs: evidence.freeArgs ?? null, notObserved: evidence.notObserved,
    buildId: buildId(), harness, offscreen: proof, externalRequestCount: proof ? proof.nonLoopbackRequests : null,
    providerCalls: evidence.providerCalls, providerCallsZero: providerZero, partFailures: evidence.partFailures,
    error: evidence.error, evidenceFile: path.basename(rec_.file), startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, runs: evidence.runs, cases }) + "\n");
  if (error) process.stderr.write(`docking-batch-flow ${input.mode} failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`docking-batch-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, oracle, neededFor, shortfallFor, sortOracle, NOT_OBSERVED };
