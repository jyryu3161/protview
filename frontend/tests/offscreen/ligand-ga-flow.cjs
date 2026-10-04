"use strict";

// M22 ligand GA design (qvina) offscreen QA (.dryforge/spec.md sections 2, 4, 6, 9, 11). Real Electron offscreen page
// (isOffscreen, GPU/WebGL, paint). Every product mutation is a Playwright locator mouse/keyboard/file-chooser/select
// input; DOM .click() and product handlers are never called. Observation is read-only: data attributes and text of
// the page, renderer request/response events, Electron paint frames, downloaded bytes, GET reads of the loopback API,
// the stored object payloads in <runs-dir>/<run>/events.jsonl (read-only file reads) and the process table
// (`ps`/`lsof`). Every limit raise is the screen's own button (a person's click); this script never posts one.
//
// Independent oracle: backend/tests/fixtures/ligand_ga/m17-candidate-set-small-pool.json and expected.json (T1,
// synthetic small pool: the ten candidate ids in set order, stored RDKit properties for the M17 filter, the stored
// Morgan radius-2 2,048-bit on-bit lists for an exact Tanimoto here), the spec 2 parameter table (ranges, defaults,
// cross rules) and spec 6 arithmetic (reserved_units = min(max_new, P + (G − 1)(P − E)); wall = min(total_s + 600,
// reserved × 300 + 300); shortfall = max(0, needed − remaining); full_run_may_be_partial = reserved × 300 > total_s),
// the spec 3 slot arithmetic (carried = the elite_count lowest stored scores of the previous generation, ties pool
// order; random slots = floor(random_fraction × slots + 0.5)), G1–G3 verbatim (spec 4) and the display order rule
// (rows without a score always last) written here independently. Scores are never computed here: each displayed score
// is compared with the first mode of the individual's stored M18 docking_result@1.
//
// Modes (the full sequence: scripts/m22_offscreen_acceptance.py):
//   main         run A (새 run): GA area before any candidate set (사용할 수 없음 + reason) → receptor import (docking
//                area) + real M17 inspection/enumeration of the synthetic small pool (10 candidates) → parameter guards
//                (out of range, cross rules, 기본값으로) → refused preflights (ga_pool_too_small: defaults, and the M17
//                filter) → GA 1 preflight (server numbers = spec arithmetic, 끝까지 못 갈 수 있음) → real GA (progress, done)
//                → results (generation tabs, individuals = stored, carried/slot rules, Tanimoto = fixture, min/max as
//                values, G1, stop reason), sort, M18 detail → GA 2 (other GA seed, same docking seed): shortfall →
//                limit approval by the screen button → GA 1 arguments again (existing job, no new job, no unit) → GA 2
//                run (reused individuals = GA 1 handles, G3) → GA 3 pool_exhausted (complete) → GA 4 docking_limit
//                (partial, G2) → GA 5 cancelled while running (partial, no process left) → report + 지식·보고서 list +
//                downloads → global budget = backend; processes; wording.
//   unavailable  backend started from a layout without the locked environments (runner): no-run and
//                capability-unavailable states show a reason only (no numbers, no controls, no GA requests)
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const m18 = require("./docking-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const FIXTURES = path.join(REPO, "backend/tests/fixtures");
const GA_FIXTURES = path.join(FIXTURES, "ligand_ga");
const RECEPTOR = path.join(FIXTURES, "chemical/prolif-vina-rec.pdb");
const PARENT = path.join(FIXTURES, "docking/public-derived-parent-record0.sdf");
const BLOCKS_SMI = path.join(GA_FIXTURES, "synthetic-ga-small-blocks.smi");
const SMALL_POOL = path.join(GA_FIXTURES, "m17-candidate-set-small-pool.json");
const EXPECTED = path.join(GA_FIXTURES, "expected.json");
const MODES = ["main", "unavailable"];
const TAB = "리간드 설계·탐색";
const SITE_ATOM = 22; // N-methyl carbon of the public-derived parent (M18/M19/M22 fixture site)
// T1 small-pool values (expected.json t1_observations.small_pool_docking: manual 12 Å box, exhaustiveness 1, num_modes
// 2, seed 1; 7–12 s per docking). The box center is the T1 center with two decimals (M18 manual box input).
const BOX_CENTER = ["3.41", "0.72", "11.31"];
const BOX_SIZE = ["12", "12", "12"];
const DOCKING = { seed: "1", exhaustiveness: "1", numModes: "2", energyRange: "3" };
const ACK_KEYS = ["keep_input_protonation", "tool_assigned_types_charges", "rigid_no_optimization"];
const UNAVAILABLE_LABEL = "labeled runtime layout without .deps (runner): capability worker_missing";
const PROVIDER_EVENT_TYPES = new Set(["egress", "egress_budget_settled", "viewer_dispatch_started"]);
const NO_RUN_REASON = "구조 분석 탭에서 run을 먼저 고르세요.";
const SCORE_LABEL = "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)";
const SCORE_HEADER = "qvina 점수(kcal/mol) · 모드 1(엔진 출력 순서)";
const REUSED_LABEL = "저장된 결과 재사용";
const DOCKED_LABEL = "새 도킹";
const CARRIED_LABEL = "다시 도킹하지 않음(이전 세대 결과 인용)";
const ORIGIN_LABEL = { initial: "초기", carried: "이어받음", similar: "유사", random: "무작위" };
const STATE_LABEL = { scored: "점수 있음", null_result: "빈 과학 결과(모드 0개)", failed: "실패" };
const MAY_BE_PARTIAL = "끝까지 못 갈 수 있음";
// spec 4 verbatim (independent of the product constants)
const G = {
  G1: "GA는 후보 풀에서 어디를 도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 순위나 추천이 아니다. " +
    "부모·유사 후보 연결은 작업 모듈 기록이며 서버가 다시 계산하지 않았다.",
  G2: "이 실행은 시간·도킹 상한·취소 등으로 일부 세대만 계산되었다. 계산하지 않은 개체는 점수가 없으며 0이 아니고, " +
    "한도 도달로 멈춘 실행은 같은 설정으로 다시 해도 같은 경로를 보장하지 않는다.",
  G3: "재사용한 개체는 같은 수용체·상자·seed·방식·값으로 이전에 저장된 도킹 결과를 가져온 것이며, " +
    "저장된 결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있다.",
};
// spec 2 table: [min, max, default] (seed: no default)
const RANGES = { seed: [0, 2147483647, null], population_size: [4, 24, 12], generations: [1, 8, 5],
  elite_count: [0, 4, 2], tournament_size: [2, 4, 2], neighbor_count: [3, 30, 10], random_fraction: [0, 0.5, 0.2],
  patience: [1, 8, 3], max_new_dockings: [4, 100, 60], total_s: [600, 14400, 7200] };
const GA_KEYS = Object.keys(RANGES);
const STATUS_OF = { generations_complete: "complete", no_change: "complete", pool_exhausted: "complete",
  docking_limit: "partial", time_exhausted: "partial", cancelled: "partial", worker_failed: "partial",
  resource_exceeded: "partial" };
// The GA runs of run A (small values keep each real GA a few minutes at most).
const GA1 = { seed: 11, population_size: 4, generations: 2, elite_count: 2, tournament_size: 2, neighbor_count: 3,
  random_fraction: 0.5, patience: 1, max_new_dockings: 6, total_s: 600 };
const GA2 = { ...GA1, seed: 12 };                                     // other GA seed, same docking seed → reuse
const GA3 = { ...GA1, seed: 13, generations: 8, elite_count: 0, patience: 8, max_new_dockings: 10 }; // pool_exhausted
const GA4 = { ...GA1, elite_count: 0, max_new_dockings: 4 };         // docking seed 2: docking_limit in generation 2
const GA5 = { ...GA4 };                                               // docking seed 3: cancelled while running
const FORBIDDEN_GA = /승자|추천|평균\s*비교|부분\s*완료|\bwinner|recommend/gi;
const PROCESS_PATTERNS = ["qvina2", "ligand_ga_worker.py", "docking_worker.py", "ligand_worker.py", "guardian.py"];

// absolute when present: a PATH without /usr/sbin must not make every process look like it is elsewhere
const LSOF = fs.existsSync("/usr/sbin/lsof") ? "/usr/sbin/lsof" : "lsof";
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
    `Usage: ligand-ga-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> [--url http://127.0.0.1:3000] ` +
    "[--runs-dir <backend MW_RUNS_DIR> (main: stored objects)] [--fixture-label <runtime layout label>]. main needs the " +
    "locked docking and M17 environments and a fresh runs root; unavailable needs a backend without them and a fresh " +
    "runs root. Full sequence: scripts/m22_offscreen_acceptance.py.");
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
  const pool = JSON.parse(fs.readFileSync(SMALL_POOL, "utf8"));
  const expected = JSON.parse(fs.readFileSync(EXPECTED, "utf8"));
  const bits = Object.fromEntries(expected.pools.small.candidates.map(item =>
    [item.candidate_id, new Set(item.morgan_r2_2048_on_bits)]));
  return {
    files: [SMALL_POOL, EXPECTED].map(fileRecord),
    ids: pool.candidates.map(item => item.id),
    heavyAtoms: Object.fromEntries(pool.candidates.map(item => [item.id, item.properties.heavy_atoms])),
    bits,
  };
}
/** Exact Tanimoto |A∩B| / |A∪B| of the fixture's stored on-bit sets, ROUND_HALF_UP to a six-decimal string (BigInt). */
function tanimoto6(o, a, b) {
  const A = o.bits[a], B = o.bits[b];
  assert.ok(A && B, `no fixture fingerprint for ${a} or ${b}`);
  let both = 0;
  for (const bit of A) if (B.has(bit)) both += 1;
  const union = A.size + B.size - both;
  const scaled = (BigInt(both) * 2000000n + BigInt(union)) / (2n * BigInt(union)); // floor(x·10⁶ + 0.5)
  const digits = scaled.toString().padStart(7, "0");
  return `${digits.slice(0, -6)}.${digits.slice(-6)}`; // the stored form: a 6-decimal string
}
/** spec 6: reserved_units, need, may-be-partial (hand arithmetic). */
function needFor(ga) {
  const reserved = Math.min(ga.max_new_dockings, ga.population_size + (ga.generations - 1) *
    (ga.population_size - ga.elite_count));
  return { reserved, needed: { expensive_calls: reserved, wall_clock_s: Math.min(ga.total_s + 600, reserved * 300 + 300) },
    mayBePartial: reserved * 300 > ga.total_s };
}
function shortfallFor(needed, remaining) {
  return { expensive_calls: Math.max(0, needed.expensive_calls - remaining.expensive_calls),
    wall_clock_s: Math.max(0, needed.wall_clock_s - remaining.wall_clock_s) };
}
/** Display order rule (spec 9), written independently: rows without a score always last (slot order). */
function sortOracle(individuals, key, direction) {
  const rows = individuals.map((item, position) => ({ ...item, position }));
  if (key === "slot") return direction === "asc" ? rows : [...rows].reverse();
  const sign = direction === "asc" ? 1 : -1;
  if (key === "candidate") return [...rows].sort((a, b) =>
    sign * (a.candidate_id < b.candidate_id ? -1 : a.candidate_id > b.candidate_id ? 1 : 0) || a.position - b.position);
  const has = row => row.state === "scored" && typeof row.score === "number";
  return [...rows.filter(has).sort((a, b) => sign * (a.score - b.score) || a.position - b.position),
    ...rows.filter(row => !has(row))];
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
/** Handles of the run's stored M18 docking results (event-log order, read-only file read). */
function dockingResultHandles(runsDir, run) {
  const found = [];
  for (const line of fs.readFileSync(path.join(runsDir, run, "events.jsonl"), "utf8").split("\n")) {
    if (!line.includes("object_created") || !line.includes("/docking_result/")) continue;
    const event = JSON.parse(line);
    if (event.type === "object_created" && /\/docking_result\//.test(event.handle ?? "")) found.push(event.handle);
  }
  return found;
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
    try { cwd = execFileSync(LSOF, ["-a", "-p", pid, "-d", "cwd", "-Fn"], { encoding: "utf8" }); } catch { /* exited */ }
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
  const file = path.join(artifacts, `ligand-ga-${input.mode}.jsonl`);
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
      const html = await page.evaluate(() => document.querySelector('[data-testid="ligand-ga-panel"]')?.outerHTML
        .slice(0, 200000) ?? "").catch(() => null);
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
  try { const text = JSON.stringify(value); return text.length > 8000 ? `${text.slice(0, 8000)}…` : JSON.parse(text); }
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

// ------------------------------------------------------------------ M18 docking area and M17 candidate area (inputs)
const dock = page => page.locator('#mw-app-panel-ligand [data-testid="docking-panel"]');
const dt = (page, id) => dock(page).locator(`[data-testid="${id}"]`);
const ligandPanel = page => page.locator('#mw-app-panel-ligand [data-testid="ligand-panel"]');
const lt = (page, id) => ligandPanel(page).locator(`[data-testid="${id}"]`);
const ga = page => page.locator('#mw-app-panel-ligand [data-testid="ligand-ga-panel"]');
const gt = (page, id) => ga(page).locator(`[data-testid="${id}"]`);
const gaState = page => ga(page).getAttribute("data-ga-state", { timeout: 2000 }).catch(() => null);
async function openLigandTab(page) {
  await selectTab(page, TAB);
  await ga(page).waitFor({ timeout: 15000 });
  await dock(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => ["ready", "unavailable"].includes(await gaState(page)) &&
    (await gaState(page) === "unavailable" || await ga(page).locator('[data-ga-area="results"]')
      .getAttribute("data-state") === "ready") ? true : null, "GA area settled", 60000);
}
/** Receptor import through the M18 docking area (file chooser + 가져오기); returns the new handle. */
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
async function m17CandidateSet(page, run, evidence) {
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
  control(evidence, "m17-candidate-set", { parent: path.basename(PARENT), blocks: path.basename(BLOCKS_SMI) });
  const set = enumerate.job.artifacts.ligand_candidate_set;
  const rows = await readApi(page, `/runs/${run}/ligand/candidate_sets/rows?handle=${enc(set)}&offset=0&limit=100`);
  return { inspection, set, inspectApproved: inspect.approved, ids: rows.rows.map(row => row.candidate.id), total: rows.total };
}

// ------------------------------------------------------------------ GA area (real input; read-only helpers)
async function gaText(page) { return ga(page).evaluate(node => node.innerText); }
/** Forbidden words in the GA area, line by line: a line equal to a G sentence or an M18 limitation is exempt; the
 * score names are removed; the M18 words and the GA words (winner, recommendation, average comparison). */
function forbiddenWords(text, exempt) {
  const found = m18.forbiddenWords(text, exempt, [SCORE_LABEL, "qvina 점수(kcal/mol)"]);
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || exempt.includes(line)) continue;
    for (const match of line.split(SCORE_LABEL).join("").matchAll(FORBIDDEN_GA))
      found.push({ word: match[0], line: line.slice(0, 200) });
  }
  return found;
}
async function fill(page, id, value) {
  const field = gt(page, id);
  await field.click();
  await field.fill(String(value));
}
async function setParams(page, values, evidence) {
  for (const [key, value] of Object.entries(values)) {
    await fill(page, `ligand-ga-param-${key}`, value);
    control(evidence, `ligand-ga-param-${key}`, { value: String(value) });
  }
}
async function paramValues(page) {
  return Object.fromEntries(await Promise.all(GA_KEYS.map(async key =>
    [key, await gt(page, `ligand-ga-param-${key}`).inputValue()])));
}
async function startState(page) {
  return { enabled: await gt(page, "ligand-ga-start").isEnabled(),
    blocked: clean(await gt(page, "ligand-ga-start-blocked").textContent({ timeout: 1000 }).catch(() => "")),
    preflightEnabled: await gt(page, "ligand-ga-preflight").isEnabled() };
}
async function fieldErrors(page) {
  return Object.fromEntries((await Promise.all(GA_KEYS.map(async key => {
    const node = gt(page, `ligand-ga-error-${key}`);
    return await node.count() ? [key, clean(await node.textContent())] : null;
  }))).filter(Boolean));
}
/** ①–④: candidate set + parent, receptor (model 1, 없음, PDB CONECT), manual box, docking values, acknowledgements. */
async function chooseInputs(page, run, inputs, evidence) {
  const reread = page.waitForResponse(response => response.request().method() === "GET" &&
    new URL(response.url()).pathname === `/api/runs/${run}/docking/prerequisites`, { timeout: 30000 });
  await gt(page, "ligand-ga-prereq-refresh").click();
  control(evidence, "ligand-ga-prereq-refresh", { clicked: true });
  const prereq = await (await reread).json();
  const parent = prereq.candidate_sets.find(item => item.handle === inputs.set).parent_sdf_handles[0];
  await waitFor(page, async () => await gt(page, "ligand-ga-candidate-set").locator(`option${attr("value", inputs.set)}`).count()
    ? true : null, "set listed", 30000);
  await gt(page, "ligand-ga-candidate-set").selectOption(inputs.set);
  control(evidence, "ligand-ga-candidate-set", { handle: inputs.set });
  await gt(page, "ligand-ga-parent-sdf").waitFor({ timeout: 30000 });
  await gt(page, "ligand-ga-parent-sdf").selectOption(parent);
  control(evidence, "ligand-ga-parent-sdf", { handle: parent });
  await gt(page, "ligand-ga-receptor").selectOption(inputs.receptor);
  control(evidence, "ligand-ga-receptor", { handle: inputs.receptor });
  await gt(page, "ligand-ga-model").waitFor({ timeout: 30000 });
  await gt(page, "ligand-ga-model").selectOption("1");
  control(evidence, "ligand-ga-model", { model: 1 });
  await gt(page, "ligand-ga-instances").waitFor({ timeout: 30000 });
  await ga(page).locator('[data-testid="ligand-ga-instances"] label[data-ga-instance="none"] input').check();
  control(evidence, "ligand-ga-instance-radio", { instance: "none" });
  await gt(page, "ligand-ga-connectivity").locator("label").filter({ hasText: "PDB CONECT" }).locator("input").check();
  control(evidence, "ligand-ga-connectivity-radio", { kind: "pdb_conect" });
  await ga(page).locator('label[data-ga-box="manual"] input').check();
  control(evidence, "ligand-ga-box-radio", { source: "manual" });
  for (const [i, axis] of ["x", "y", "z"].entries()) {
    await fill(page, `ligand-ga-center-${axis}`, BOX_CENTER[i]);
    await fill(page, `ligand-ga-size-${axis}`, BOX_SIZE[i]);
  }
  control(evidence, "ligand-ga-manual-box", { center: BOX_CENTER, size: BOX_SIZE });
  await setDockingSeed(page, DOCKING.seed, evidence);
  await fill(page, "ligand-ga-exhaustiveness", DOCKING.exhaustiveness);
  await fill(page, "ligand-ga-num-modes", DOCKING.numModes);
  await fill(page, "ligand-ga-energy-range", DOCKING.energyRange);
  for (const id of ["ligand-ga-exhaustiveness", "ligand-ga-num-modes", "ligand-ga-energy-range"]) control(evidence, id, {});
  for (const key of ACK_KEYS) {
    await ga(page).locator(`label[data-ga-ack="${key}"] input`).check();
    control(evidence, `ligand-ga-ack-${key}`, { checked: true });
  }
  return { parent };
}
async function setDockingSeed(page, value, evidence) {
  await fill(page, "ligand-ga-docking-seed", value);
  control(evidence, "ligand-ga-docking-seed", { value: String(value) });
}
/** Click 시작 전 확인 보기; returns the server response (what the view shows) and the view's DOM. */
async function preflight(page, run, evidence) {
  await waitFor(page, async () => await gt(page, "ligand-ga-preflight").isEnabled() ? true : null, "preflight enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/ligand/ga/preflight`, { timeout: 60000 });
  await gt(page, "ligand-ga-preflight").click();
  const response = await posted;
  const body = await response.json();
  control(evidence, "ligand-ga-preflight", { status: response.status(), admitted: body.admission?.admitted });
  return { status: response.status(), body, request: response.request().postDataJSON(), view: await preflightView(page, body) };
}
async function preflightView(page, body) {
  if (!body.admission.admitted) {
    await gt(page, "ligand-ga-preflight-refused").waitFor({ timeout: 30000 });
    return { refused: clean(await gt(page, "ligand-ga-preflight-refused").textContent()),
      reasonCode: await gt(page, "ligand-ga-preflight-refused").getAttribute("data-reason-code"), start: await startState(page) };
  }
  const view = gt(page, "ligand-ga-preflight-view");
  await waitFor(page, async () => await view.count() &&
    await view.getAttribute("data-reserved-units") === String(body.reserved_units) &&
    await view.getAttribute("data-shortfall-calls") === String(body.shortfall.expensive_calls) ? true : null,
  "preflight view", 30000);
  return {
    reservedUnits: Number(await view.getAttribute("data-reserved-units")),
    reusable: Number(await view.getAttribute("data-reusable")),
    shortfallCalls: Number(await view.getAttribute("data-shortfall-calls")),
    shortfallWall: Number(await view.getAttribute("data-shortfall-wall")),
    mayBePartial: await view.getAttribute("data-may-be-partial"),
    lines: Object.fromEntries(await view.locator("[data-preflight-line]").evaluateAll(items => items.map(item =>
      [item.querySelector("dt").textContent.trim(), item.querySelector("dd").textContent.trim()]))),
    statements: await gt(page, "ligand-ga-preflight-statements").locator("li[data-statement]").evaluateAll(items =>
      items.map(item => ({ id: item.getAttribute("data-statement"), text: item.textContent.trim() }))).catch(() => []),
    existingJob: await gt(page, "ligand-ga-existing-job").getAttribute("data-job-id", { timeout: 1000 }).catch(() => null),
    approvalButtons: await gt(page, "ligand-ga-limit-approve").count(),
    start: await startState(page),
  };
}
/** The displayed preflight lines equal the server numbers, and the server numbers equal the spec 6 arithmetic. */
function preflightMatches(pf, { gaValues, reusable, budget, pool = { size: 10, eligible_count: 10, filter_excluded_count: 0 } }) {
  const body = pf.body, view = pf.view;
  const want = needFor(gaValues);
  assert.equal(pf.status, 200);
  assert.equal(body.admission.admitted, true, JSON.stringify(body.admission));
  assert.equal(body.starts_job, false);
  assert.deepEqual(body.ga, gaValues, "the preflight's effective parameters differ from the typed values");
  assert.deepEqual(body.pool, pool);
  assert.equal(body.reserved_units, want.reserved, "reserved_units differs from spec 6 arithmetic");
  assert.equal(body.max_new_dockings_expected, want.reserved);
  assert.deepEqual(body.needed, want.needed, "needed differs from spec 6 arithmetic");
  assert.deepEqual(body.shortfall, shortfallFor(body.needed, body.remaining), "shortfall differs from needed − remaining");
  assert.equal(body.full_run_may_be_partial, want.mayBePartial);
  if (reusable !== undefined) assert.equal(body.reusable_count, reusable);
  if (budget) {
    assert.equal(body.remaining.expensive_calls, budget.expensive_calls.limit - budget.expensive_calls.used);
    assert.ok(body.remaining.wall_clock_s <= budget.wall_clock_s.limit - budget.wall_clock_s.used + 1e-6);
  }
  assert.deepEqual(body.statements, [{ id: "G1", text: G.G1 }], "preflight statement is not G1 verbatim");
  assert.equal(view.reservedUnits, body.reserved_units);
  assert.equal(view.reusable, body.reusable_count);
  assert.equal(view.shortfallCalls, body.shortfall.expensive_calls);
  assert.equal(view.shortfallWall, body.shortfall.wall_clock_s);
  assert.equal(view.mayBePartial, String(body.full_run_may_be_partial));
  const p = body.pool;
  assert.equal(view.lines["후보 풀"], `${p.size}개 · 적격 ${p.eligible_count}개 · 필터 제외 ${p.filter_excluded_count}개(도킹하지 않음)`);
  assert.equal(view.lines["재사용 가능"], `${REUSED_LABEL} 가능 후보 ${body.reusable_count}개 (과금하지 않음, 새 도킹 상한에 세지 않음)`);
  assert.equal(view.lines["예약 단위"], `${body.reserved_units}단위`);
  assert.equal(view.lines["예상 최대 새 도킹"], `${body.max_new_dockings_expected}건`);
  assert.equal(view.lines["예상 시간 상한"], seconds(body.needed.wall_clock_s));
  assert.equal(view.lines["필요"], `${pairText(body.needed)} (최대)`);
  assert.equal(view.lines["현재 잔여"], pairText(body.remaining));
  assert.equal(view.lines["부족분"], pairText(body.shortfall));
  assert.equal(view.lines["과금"], `시작하면 ${body.reserved_units}단위가 예약·소진되고 중간에 멈추거나 재사용이 있어도 돌려받지 않음`);
  assert.ok(view.lines["대기"]?.includes("기다립니다"), view.lines["대기"]);
  assert.equal("시간 상한" in view.lines, body.full_run_may_be_partial);
  if (body.full_run_may_be_partial) assert.ok(view.lines["시간 상한"].startsWith(MAY_BE_PARTIAL), view.lines["시간 상한"]);
  assert.deepEqual(view.statements, [{ id: "G1", text: G.G1 }], "the shown preflight statement is not G1 verbatim");
  const shortfall = body.shortfall.expensive_calls > 0 || body.shortfall.wall_clock_s > 0;
  assert.equal(view.approvalButtons, shortfall ? 1 : 0, "limit approval shown iff shortfall > 0");
  assert.equal(view.start.enabled, !shortfall, `start ${view.start.enabled} with shortfall ${JSON.stringify(body.shortfall)}`);
  if (shortfall) assert.ok(view.start.blocked.includes("(ga_limit_raise_required)"), view.start.blocked);
  return { reserved: body.reserved_units, needed: body.needed, remaining: body.remaining, shortfall: body.shortfall,
    mayBePartial: body.full_run_may_be_partial, reusable: body.reusable_count, lines: view.lines };
}
/** Click the screen's limit approval button (a person's click); the preflight is read again. */
async function approveLimits(page, run, pf, evidence) {
  const budget = await readApi(page, `/runs/${run}/budget`);
  const eventsBefore = (await runEvents(page, run)).length;
  const approval = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/ligand/ga/limit_approval`, { timeout: 60000 });
  const reread = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/ligand/ga/preflight`, { timeout: 60000 });
  await gt(page, "ligand-ga-limit-approve").click();
  control(evidence, "ligand-ga-limit-approve", { clicked: true });
  const approvedResponse = await approval;
  const approved = await approvedResponse.json();
  const again = await (await reread).json();
  await gt(page, "ligand-ga-limit-done").waitFor({ timeout: 30000 });
  const view = await preflightView(page, again);
  const events = (await runEvents(page, run)).slice(eventsBefore);
  return { budget, approved, approvalRequest: approvedResponse.request().postDataJSON(), again, view, events,
    done: clean(await gt(page, "ligand-ga-limit-done").textContent()),
    raisedAttr: await gt(page, "ligand-ga-limit-done").getAttribute("data-raised"),
    budgetAfter: await readApi(page, `/runs/${run}/budget`), pf };
}
function approvalMatches(value) {
  const { pf, approved, budget, budgetAfter, events } = value;
  const shortfall = pf.body.shortfall;
  assert.equal(approved.raised, true);
  // the server raises by the shortfall it sees at the click; the wall axis carries the 60 s margin (spec 6)
  assert.equal(approved.increase.expensive_calls, shortfall.expensive_calls, "the raise is not the unit shortfall");
  assert.ok(approved.increase.wall_clock_s >= shortfall.wall_clock_s, "the wall raise is below the shortfall");
  assert.deepEqual(value.approvalRequest, pf.request, "the approval body is not the previewed GA arguments");
  assert.equal(approved.limits_after.expensive_calls, budget.expensive_calls.limit + shortfall.expensive_calls);
  assert.equal(budgetAfter.expensive_calls.limit, budget.expensive_calls.limit + shortfall.expensive_calls);
  assert.equal(budgetAfter.expensive_calls.used, budget.expensive_calls.used, "the approval used budget");
  const updated = events.filter(event => event.type === "budget_limit_updated");
  assert.equal(updated.length, 1, JSON.stringify(events.map(event => event.type)));
  assert.equal(updated[0].by, "human");
  assert.equal(updated[0].context.purpose, "ligand_ga_limit_raise");
  assert.equal(updated[0].context.selection_sha256, pf.body.selection_sha256);
  assert.equal(updated[0].context.reserved_units, pf.body.reserved_units);
  assert.deepEqual(updated[0].context.increase, approved.increase);
  assert.ok(!events.some(event => event.type.startsWith("job_") || event.type === "object_created"),
    "the approval created a job or an object");
  assert.equal(value.raisedAttr, "true");
  assert.ok(value.done.includes("되돌리지 않음"), value.done);
  assert.deepEqual(value.again.shortfall, { expensive_calls: 0, wall_clock_s: 0 });
  assert.equal(value.view.approvalButtons, 0, "approval still offered without a shortfall");
  assert.equal(value.view.start.enabled, true, value.view.start.blocked);
  return { shortfall, increase: approved.increase, limitsBefore: approved.limits_before, limitsAfter: approved.limits_after,
    event: updated[0].seq };
}
async function jobPhase(page) {
  const job = gt(page, "ligand-ga-job");
  if (!await job.count()) return null;
  return { phase: await job.getAttribute("data-ga-job-phase"), status: await job.getAttribute("data-ga-job-status"),
    id: await job.getAttribute("data-ga-job-id"),
    generations: Number(await job.getAttribute("data-generations-complete") ?? NaN),
    finished: Number(await job.getAttribute("data-individuals-finished") ?? NaN),
    progress: clean(await gt(page, "ligand-ga-progress").textContent({ timeout: 500 }).catch(() => "")) };
}
async function budgetUsed(page, run) { return (await readApi(page, `/runs/${run}/budget`)).expensive_calls; }
/** The progress line written independently from the stored job record's `ga` counts. */
function progressText(p) {
  return `완료한 세대 ${p.generations_complete}개(세대 기록 ${p.generation_records}개) · 평가 시작 ${p.individuals_started}개 · ` +
    `평가 끝 ${p.individuals_finished}개 · ${REUSED_LABEL} 예정 ${p.reused_planned}개 · 예약 ${p.reserved_units}단위`;
}
/**
 * Click GA 시작 (real input); approve through 비싼 계산 승인 when asked, then 작업 시작; while running, compare the
 * progress line with the stored job record (`progress: true`); stop when `until(phase)` holds or the job ends.
 */
async function runGa(page, run, evidence, { until = null, timeout = 900000, progress = false } = {}) {
  const phases = [];
  const progressSeen = [];
  const before = await budgetUsed(page, run);
  const previousJob = (await jobPhase(page))?.id ?? null;
  const jobsBefore = (await readApi(page, `/runs/${run}/jobs`)).length;
  await waitFor(page, async () => (await startState(page)).enabled ? true : null, "start enabled", 15000);
  await gt(page, "ligand-ga-start").click();
  control(evidence, "ligand-ga-start", { clicked: true });
  const settled = async () => {
    const value = await jobPhase(page);
    if (!value || value.id === previousJob) return null;
    if (["running", "done", "failed", "cancelled"].includes(value.phase)) return value;
    if (value.phase === "awaiting_approval" && await gt(page, "ligand-ga-job-approve").isEnabled().catch(() => false)) return value;
    if (value.phase === "saved" && await gt(page, "ligand-ga-job-start").isEnabled().catch(() => false)) return value;
    return null;
  };
  const first = await waitFor(page, settled, "GA job submitted", 120000);
  phases.push(first.phase);
  let approved = false;
  if (first.phase === "awaiting_approval") {
    await gt(page, "ligand-ga-job-approve").click();
    approved = true;
    await waitFor(page, async () => (await settled())?.phase === "saved" ? true : null, "approval recorded", 30000);
    phases.push("saved");
    control(evidence, "ligand-ga-job-approve", { clicked: true });
  }
  if ((await jobPhase(page)).phase === "saved" && await gt(page, "ligand-ga-job-start").isEnabled().catch(() => false)) {
    await gt(page, "ligand-ga-job-start").click();
    control(evidence, "ligand-ga-job-start", { clicked: true });
  }
  const stop = until ?? (value => ["done", "failed", "cancelled"].includes(value.phase));
  const done = await waitFor(page, async () => {
    const value = await jobPhase(page);
    if (value && value.phase !== phases.at(-1)) phases.push(value.phase);
    if (progress && value?.phase === "running" && value.finished >= 1 && progressSeen.length < 3) {
      const record = await readApi(page, `/runs/${run}/jobs/${enc(value.id)}`);
      const shown = (await jobPhase(page))?.progress;
      if (record.status === "running" && record.ga && shown === progressText(record.ga) &&
          !progressSeen.some(item => item.text === shown))
        progressSeen.push({ text: shown, record: record.ga });
    }
    return value && stop(value) ? value : null;
  }, "GA job", timeout);
  const job = await readApi(page, `/runs/${run}/jobs/${enc(done.id)}`);
  return { phases, approved, job, phase: done, handle: job.ga?.summary_handle ?? null, budgetBefore: before,
    budgetAfter: await budgetUsed(page, run), jobsBefore, jobsAfter: (await readApi(page, `/runs/${run}/jobs`)).length,
    progressSeen, notice: clean(await gt(page, "ligand-ga-notice").textContent({ timeout: 1000 }).catch(() => "")) };
}
/** Choose a stored summary in ⑧ (radio); returns the opened result header read from the DOM. */
async function openSummary(page, handle, evidence) {
  await waitFor(page, async () => await ga(page).locator(`label${attr("data-ga-summary", handle)}`).count() ? true : null,
    "summary listed", 30000);
  await ga(page).locator(`label${attr("data-ga-summary", handle)} input`).check();
  control(evidence, "ligand-ga-summary-radio", { handle });
  await gt(page, "ligand-ga-result").and(ga(page).locator(attr("data-ga-handle", handle))).waitFor({ timeout: 30000 });
  const view = gt(page, "ligand-ga-result");
  return { handle: await view.getAttribute("data-ga-handle"), status: await view.getAttribute("data-ga-status"),
    stopReason: await view.getAttribute("data-stop-reason"), statusText: clean(await gt(page, "ligand-ga-status").textContent()),
    statements: await gt(page, "ligand-ga-statements").locator("li").evaluateAll(items => items.map(item =>
      ({ id: item.getAttribute("data-statement"), text: item.textContent.trim() }))),
    summaryLines: Object.fromEntries(await gt(page, "ligand-ga-summary").locator("[data-summary-line]").evaluateAll(items =>
      items.map(item => [item.querySelector("dt").textContent.trim(), item.querySelector("dd").textContent.trim()]))),
    tabs: await gt(page, "ligand-ga-generation-tabs").locator('[role="tab"]').evaluateAll(items => items.map(item => ({
      id: item.getAttribute("data-testid"), complete: item.getAttribute("data-complete"), text: item.textContent.trim(),
      selected: item.getAttribute("aria-selected") }))).catch(() => []),
    noGenerations: await gt(page, "ligand-ga-no-generations").count() };
}
async function generationTable(page) {
  const panel = gt(page, "ligand-ga-generation-panel");
  const table = gt(page, "ligand-ga-individuals");
  return {
    generation: Number(await panel.getAttribute("data-generation")),
    range: clean(await gt(page, "ligand-ga-generation-range").textContent()),
    caption: clean(await table.locator("caption").textContent()),
    headers: (await table.locator("thead th").allTextContents()).map(clean),
    aria: await table.locator("thead th").evaluateAll(items => items.map(item => item.getAttribute("aria-sort"))),
    rows: await table.locator("tbody tr").evaluateAll(items => items.map(item => ({
      position: Number(item.getAttribute("data-position")), candidate: item.getAttribute("data-candidate-id"),
      origin: item.getAttribute("data-origin"), evaluation: item.getAttribute("data-evaluation"),
      state: item.getAttribute("data-state"),
      cells: [...item.querySelectorAll("td")].map(cell => cell.textContent.trim()),
      openEnabled: !item.querySelector("button").disabled }))),
  };
}
async function showGeneration(page, index, evidence) {
  await gt(page, `ligand-ga-generation-${index}`).click();
  control(evidence, "ligand-ga-generation-tab", { index });
  await waitFor(page, async () => await gt(page, "ligand-ga-generation-panel").getAttribute("data-generation") === String(index)
    ? true : null, `generation ${index} shown`, 15000);
  return generationTable(page);
}
/**
 * The opened summary equals the stored object and the stored rules: statements, status, stop reason, every generation
 * tab and every individual row (score = the stored M18 result's first mode, carried = previous generation's lowest
 * stored scores, slot counts, similarity = fixture Tanimoto, eval indices), min/max as values only.
 */
async function resultEquals(page, o, header, detail, stored, runsDir, run, evidence) {
  assert.equal(header.handle, detail.handle);
  assert.deepEqual(detail.summary, stored, "detail summary differs from the stored object");
  assert.equal(header.status, stored.status);
  assert.equal(header.stopReason, stored.stop_reason);
  assert.equal(STATUS_OF[stored.stop_reason], stored.status, "stop reason and status disagree");
  const statusLabel = stored.status === "complete" ? "완료" : "일부 세대만 계산됨";
  assert.ok(header.statusText.startsWith(`GA 상태: ${statusLabel} (${stored.status}) · 종료 이유:`), header.statusText);
  assert.ok(header.statusText.endsWith(`(${stored.stop_reason})`), header.statusText);
  const reused = stored.generations.flatMap(gen => gen.individuals).filter(item => item.evaluation === "reused").length;
  const docked = stored.generations.flatMap(gen => gen.individuals).filter(item => item.evaluation === "docked").length;
  const want = ["G1", ...(stored.status === "partial" ? ["G2"] : []), ...(reused > 0 ? ["G3"] : [])];
  assert.deepEqual(stored.limitations, want, "stored G sentence ids differ from the spec 4 rule");
  assert.deepEqual(header.statements, want.map(id => ({ id, text: G[id] })), "shown G sentences differ from spec 4");
  assert.equal(stored.reused_count, reused);
  assert.equal(stored.new_dockings_used, docked);
  assert.ok(stored.new_dockings_used <= stored.reserved_units);
  assert.equal(stored.reserved_units, needFor(stored.ga).reserved);
  assert.equal(header.summaryLines["새 도킹"], `${stored.new_dockings_used}건 (예약 ${stored.reserved_units}단위)`);
  assert.equal(header.summaryLines[REUSED_LABEL], `${stored.reused_count}개 (과금하지 않음)`);
  assert.equal(header.summaryLines["완료한 세대"], `${stored.generations_done}개`);
  assert.equal(header.tabs.length, stored.generations.length);
  const seenIds = new Set(), evalIndices = [], tables = [];
  const order = Object.fromEntries(o.ids.map((id, i) => [id, i]));
  let previous = null;
  for (const gen of stored.generations) {
    const tab = header.tabs.find(item => item.id === `ligand-ga-generation-${gen.index}`);
    assert.ok(tab, `no tab for generation ${gen.index}`);
    assert.equal(tab.complete, String(gen.complete));
    assert.equal(tab.text, `세대 ${gen.index}${gen.complete ? "" : " (중간에 멈춤, 평가를 끝낸 개체만)"}`);
    const table = await showGeneration(page, gen.index, evidence);
    assert.equal(table.caption, SCORE_LABEL);
    assert.deepEqual(table.headers, ["자리", "후보 id", "출처", "부모 · 유사도", "평가", "상태", SCORE_HEADER, "이유", "상세"]);
    assert.ok(!table.headers.some(text => /순위|rank/i.test(text)), "a rank column is shown");
    assert.ok(gen.individuals.length <= stored.ga.population_size);
    assert.equal(table.rows.length, gen.individuals.length);
    const scores = gen.individuals.filter(item => item.state === "scored").map(item => item.score);
    assert.equal(gen.min_score, scores.length ? Math.min(...scores) : null, "stored min_score is not the generation minimum");
    assert.equal(gen.max_score, scores.length ? Math.max(...scores) : null, "stored max_score is not the generation maximum");
    assert.equal(table.range, scores.length ? `점수 최솟값 ${halfUp(gen.min_score, 1)} · 점수 최댓값 ${halfUp(gen.max_score, 1)} (kcal/mol)`
      : "이 세대에 점수 있는 개체 없음");
    // slot rules (spec 3)
    const carried = gen.individuals.filter(item => item.origin === "carried");
    if (previous === null) assert.ok(gen.individuals.every(item => item.origin === "initial"));
    else {
      const ranked = previous.individuals.filter(item => item.state === "scored")
        .sort((a, b) => a.score - b.score || order[a.candidate_id] - order[b.candidate_id]);
      assert.deepEqual(carried.map(item => item.candidate_id), ranked.slice(0, stored.ga.elite_count).map(item => item.candidate_id),
        "carried individuals are not the previous generation's lowest stored scores");
      const slots = stored.ga.population_size - carried.length;
      const random = Math.floor(stored.ga.random_fraction * slots + 0.5);
      const filled = gen.individuals.length - carried.length;
      if (gen.complete && filled === slots) {
        assert.equal(gen.individuals.filter(item => item.origin === "random").length, random, "random slot count");
        assert.equal(gen.individuals.filter(item => item.origin === "similar").length, slots - random, "similar slot count");
      }
    }
    gen.individuals.forEach((item, position) => {
      const row = table.rows.find(entry => entry.position === position);
      assert.ok(row, `generation ${gen.index} position ${position} not shown`);
      assert.equal(row.candidate, item.candidate_id);
      assert.ok(o.ids.includes(item.candidate_id), "an individual outside the pool");
      assert.equal(row.cells[0], String(position));
      assert.equal(row.cells[1], item.candidate_id);
      assert.equal(row.cells[2], ORIGIN_LABEL[item.origin]);
      if (item.origin === "carried") {
        const first = previous.individuals.find(entry => entry.candidate_id === item.candidate_id);
        assert.ok(first, "a carried individual not in the previous generation");
        assert.equal(item.result_handle, first.result_handle);
        assert.equal(item.score, first.score);
        assert.equal(item.evaluation, null);
        assert.equal(item.eval_index, null);
        assert.equal(row.cells[4], CARRIED_LABEL);
      } else {
        assert.ok(!seenIds.has(item.candidate_id), `candidate ${item.candidate_id} evaluated twice`);
        seenIds.add(item.candidate_id);
        evalIndices.push(item.eval_index);
        assert.equal(row.cells[4], item.evaluation === "reused" ? REUSED_LABEL : DOCKED_LABEL);
      }
      if (item.origin === "similar") {
        assert.ok(item.parent_candidate_id && previous.individuals.some(entry => entry.candidate_id === item.parent_candidate_id &&
          entry.state === "scored"), "a similar slot without a scored parent of the previous generation");
        assert.equal(item.similarity, tanimoto6(o, item.parent_candidate_id, item.candidate_id),
          "stored similarity differs from the fixture Morgan Tanimoto");
        assert.equal(row.cells[3], `부모 ${item.parent_candidate_id} · 지문 Tanimoto ${item.similarity}`);
      } else {
        assert.equal(item.parent_candidate_id, null);
        assert.equal(item.similarity, null);
        assert.equal(row.cells[3], "");
      }
      assert.equal(row.cells[5], `${STATE_LABEL[item.state]} (${item.state})`);
      if (item.state === "scored") {
        const result = storedObject(runsDir, run, item.result_handle);
        assert.equal(item.score, result.modes[0].score_kcal_mol, "individual score is not the stored first mode");
        assert.equal(result.inputs.ligand.source, "candidate");
        assert.equal(result.inputs.ligand.candidate_id, item.candidate_id);
        assert.equal(result.inputs.mode, "free");
        assert.deepEqual(result.parameters, stored.parameters);
        assert.deepEqual(result.box, stored.box);
        assert.equal(row.cells[6], halfUp(item.score, 1));
        assert.equal(row.cells[7], "");
      } else {
        assert.equal(item.score, null);
        assert.equal(row.cells[6], "", "a score is shown for an individual without one");
        assert.ok(!/\d/.test(row.cells[6]));
      }
      assert.equal(row.openEnabled, !!item.result_handle);
    });
    tables.push({ generation: gen.index, complete: gen.complete, range: table.range, rows: gen.individuals.map(item => ({
      id: item.candidate_id, origin: item.origin, evaluation: item.evaluation, state: item.state, score: item.score,
      similarity: item.similarity, parent: item.parent_candidate_id })) });
    previous = gen;
  }
  assert.deepEqual([...evalIndices].sort((a, b) => a - b), evalIndices.map((_, i) => i), "eval_index is not 0..n-1");
  return { status: stored.status, stopReason: stored.stop_reason, generationsDone: stored.generations_done,
    newDockings: stored.new_dockings_used, reused: stored.reused_count, reserved: stored.reserved_units,
    statements: want, tables };
}
/** Click the score, candidate id and slot headers twice each on the shown generation: the order follows the oracle. */
async function sortChecks(page, gen, evidence) {
  const seen = [];
  for (const key of ["score", "candidate", "slot"]) {
    for (const direction of ["asc", "desc"]) {
      await gt(page, `ligand-ga-sort-${key}`).click();
      control(evidence, `ligand-ga-sort-${key}`, { direction });
      const want = sortOracle(gen.individuals, key, direction).map(row => row.position);
      const table = await waitFor(page, async () => {
        const value = await generationTable(page);
        return JSON.stringify(value.rows.map(row => row.position)) === JSON.stringify(want) ? value : null;
      }, `sort ${key} ${direction}`, 10000);
      const column = { slot: 0, candidate: 1, score: 6 }[key];
      assert.equal(table.aria[column], direction === "asc" ? "ascending" : "descending");
      seen.push({ key, direction, order: want });
    }
  }
  return seen;
}

// ------------------------------------------------------------------ mode main
async function modeMain(session, input, rec_, evidence, log) {
  const { page } = session;
  const o = oracle();
  const runsDir = input["runs-dir"];
  evidence.inputs.push(...[RECEPTOR, PARENT, BLOCKS_SMI].map(fileRecord), ...o.files);
  const capabilities = await readApi(page, "/capabilities");
  const capability = capabilities.methods?.ligand_ga_design;
  const single = capabilities.methods?.ligand_docking;
  assert.ok(capability?.available === true, `GA capability unavailable: ${JSON.stringify(capability)}`);
  evidence.capability = { available: capability.available, engine: capability.engine, pins: capability.pins,
    ga_pins: capability.ga_pins, ga_ranges: capability.ga_ranges, limits: capability.limits };
  const exempt = [...Object.values(G), ...(single?.limitations ?? [])];
  const wording = [];
  const checkWording = async where => {
    const found = forbiddenWords(await gaText(page), exempt);
    wording.push({ where, found });
    return found;
  };
  await waitForBoot(page);

  // ---- run A: area before any candidate set
  const runA = await rec_.step("R01-run", ["GA-run-panel", "GA-no-candidate-set"], "구조 분석: click 새 run; click " +
    "리간드 설계·탐색: the GA area uses the global run (no run choice), shows its capability line, no summaries, a " +
    "blocked start, and in ① 사용할 수 없음 with the reason only (no candidate set yet)", async () => {
    const run = await newRun(page);
    await openLigandTab(page);
    await gt(page, "ligand-ga-no-candidate-set").waitFor({ timeout: 30000 });
    return { run, state: await gaState(page), global: await globalRun(page),
      capability: clean(await gt(page, "ligand-ga-capability").textContent()),
      results: clean(await ga(page).locator('[data-ga-area="results"]').textContent()),
      runChoices: await ga(page).locator("#run-choice, [data-testid*='run-choice']").count(),
      noSet: clean(await gt(page, "ligand-ga-no-candidate-set").textContent()),
      setOptions: await gt(page, "ligand-ga-candidate-set").locator("option").count(),
      start: await startState(page), gaRequests: log.filter(row => row.path.includes("/ligand/ga/") && row.method === "POST").length };
  }, async value => {
    assert.match(value.run, /^run_/);
    assert.equal(value.state, "ready");
    assert.equal(value.global, value.run);
    assert.equal(value.runChoices, 0);
    assert.ok(value.capability.startsWith("qvina · qvina_ga_design"), value.capability);
    assert.ok(value.results.includes("이 run에 GA 결과가 없습니다."), value.results);
    assert.ok(value.noSet.startsWith("사용할 수 없음"), value.noSet);
    assert.ok(value.noSet.includes("후보 집합이 없습니다"), value.noSet);
    assert.ok(!/\d/.test(value.noSet), value.noSet);
    assert.equal(value.setOptions, 1, "a candidate set option exists before any M17 job");
    assert.equal(value.start.enabled, false);
    assert.equal(value.start.preflightEnabled, false);
    assert.equal(value.gaRequests, 0);
    return value;
  });
  const run = runA.run;
  evidence.runs.A = run;
  const inputs = await rec_.step("I01-inputs", ["GA-m17-set"], "Docking area: choose prolif-vina-rec.pdb (수용체), " +
    "가져오기; candidate area: the public-derived parent SDF and synthetic-ga-small-blocks.smi, 가져오기, 점검 시작 " +
    "(approval), atom 22, 후보 생성 시작: the set equals the fixture's ten ids in set order", async () => {
    const receptor = await importReceptor(page, run, RECEPTOR, evidence);
    const m17 = await m17CandidateSet(page, run, evidence);
    return { receptor, ...m17 };
  }, async value => {
    assert.deepEqual(value.ids, o.ids, "candidate ids or set order differ from the fixture");
    assert.equal(value.total, 10);
    assert.equal(value.inspectApproved, true, "the run's first expensive call did not ask for approval");
    const set = await readApi(page, `/runs/${run}/ligand/candidate_sets/detail?handle=${enc(value.set)}`);
    assert.equal(set.candidate_set.parent_sha256, fileRecord(PARENT).sha256);
    return value;
  });
  evidence.handles.A = { receptor: inputs.receptor, set: inputs.set };

  // ---- parameter guards, defaults, refused preflights
  const chosen = await rec_.step("P01-guards", ["GA-param-guards"], "GA area: 입력 목록 다시 읽기; the set and its " +
    "parent, the receptor (model 1, 없음, PDB CONECT), 직접 입력 box, docking seed 1 / exhaustiveness 1 / num_modes 2, " +
    "the three acknowledgements; then GA seed empty, population 25, random fraction 0.6, population 4 with elite 3, " +
    "max new dockings 5 with population 6: each blocks 시작 전 확인 and GA 시작 with the field's reason; no GA request", async () => {
    const chosenInputs = await chooseInputs(page, run, inputs, evidence);
    const postsBefore = log.filter(row => row.method === "POST" && /\/ligand\/ga\/|\/jobs$/.test(row.path)).length;
    const observed = [];
    const look = async label => {
      const value = { label, errors: await fieldErrors(page), start: await startState(page),
        effectiveBlocked: await gt(page, "ligand-ga-effective-blocked").count(),
        inputErrors: (await gt(page, "ligand-ga-input-errors").locator("li").allTextContents().catch(() => [])).map(clean) };
      observed.push(value);
      return value;
    };
    await look("seed empty (initial)");
    await setParams(page, { seed: "11", population_size: "25" }, evidence);
    await look("population 25");
    await setParams(page, { population_size: "4", random_fraction: "0.6" }, evidence);
    await look("random fraction 0.6");
    await setParams(page, { random_fraction: "0.5", elite_count: "3" }, evidence);
    await look("population 4, elite 3");
    await setParams(page, { elite_count: "2", population_size: "6", max_new_dockings: "5" }, evidence);
    await look("max new 5 < population 6");
    await setParams(page, { population_size: "4", max_new_dockings: "6", seed: "" }, evidence);
    await look("seed cleared");
    return { ...chosenInputs, observed, postsAfter: log.filter(row => row.method === "POST" &&
      /\/ligand\/ga\/|\/jobs$/.test(row.path)).length, postsBefore };
  }, async value => {
    const expect = [["seed empty (initial)", "seed", "GA seed(후보 선택 난수): 0–2147483647 사이의 정수를 입력하세요(필수)"],
      ["population 25", "population_size", "세대당 개체 수: 4–24 사이의 정수"],
      ["random fraction 0.6", "random_fraction", "새 자리 중 무작위 후보 비율: 0–0.5 사이의 숫자"],
      ["population 4, elite 3", "elite_count", "세대당 개체 수 − 이어받는 개체 수가 2 이상이어야 합니다"],
      ["max new 5 < population 6", "max_new_dockings", "세대당 개체 수(6) 이상이어야 합니다"],
      ["seed cleared", "seed", "(필수)"]];
    for (const [label, key, text] of expect) {
      const seen = value.observed.find(item => item.label === label);
      assert.deepEqual(Object.keys(seen.errors), [key], `${label}: ${JSON.stringify(seen.errors)}`);
      assert.ok(seen.errors[key].includes(text) && seen.errors[key].includes("(invalid_job_arguments)"), seen.errors[key]);
      assert.equal(seen.start.enabled, false, `${label}: GA 시작 enabled`);
      assert.equal(seen.start.preflightEnabled, false, `${label}: 시작 전 확인 enabled`);
      assert.ok(seen.start.blocked.includes(seen.errors[key]), `${label}: blocked reason ${seen.start.blocked}`);
      assert.ok(seen.inputErrors.includes(seen.errors[key]), `${label}: ${JSON.stringify(seen.inputErrors)}`);
      assert.equal(seen.effectiveBlocked, 1, `${label}: effective summary shown with an error`);
    }
    assert.equal(value.postsAfter, value.postsBefore, "a GA request was sent while the inputs were invalid");
    return value.observed.map(item => ({ label: item.label, errors: item.errors }));
  });
  await rec_.step("P02-defaults", ["GA-defaults"], "GA seed 11; click 기본값으로: every parameter is the spec 2 " +
    "default again (12, 5, 2, 2, 10, 0.2, 3, 60, 7200) and the GA seed is kept; the effective summary lists every key " +
    "and the job time limit 7800 s; 끝까지 못 갈 수 있음 advice (60 × 300 s > 7200 s)", async () => {
    await setParams(page, { seed: "11" }, evidence);
    await gt(page, "ligand-ga-defaults").click();
    control(evidence, "ligand-ga-defaults", { clicked: true });
    await gt(page, "ligand-ga-effective").waitFor({ timeout: 10000 });
    return { values: await paramValues(page), ranges: Object.fromEntries(await Promise.all(GA_KEYS.map(async key =>
      [key, clean(await gt(page, `ligand-ga-range-${key}`).textContent())]))),
    effective: Object.fromEntries(await gt(page, "ligand-ga-effective").locator("[data-ga-line]").evaluateAll(items =>
      items.map(item => [item.querySelector("dt").textContent.trim(), item.querySelector("dd").textContent.trim()]))),
    advice: clean(await gt(page, "ligand-ga-time-advice").textContent()), errors: await fieldErrors(page),
    start: await startState(page) };
  }, async value => {
    const want = Object.fromEntries(GA_KEYS.map(key => [key, key === "seed" ? "11" : String(RANGES[key][2])]));
    assert.deepEqual(value.values, want, "기본값으로 did not restore the spec 2 defaults");
    assert.deepEqual(value.errors, {});
    for (const key of GA_KEYS) {
      const [low, high, fallback] = RANGES[key];
      const text = value.ranges[key];
      assert.ok(text.includes(`–${high}`) && text.includes(fallback === null ? "기본 없음(필수)" : `기본 ${fallback}`), `${key}: ${text}`);
      if (key !== "max_new_dockings") assert.ok(text.startsWith(`${low}–`), `${key}: ${text}`);
    }
    assert.equal(Object.keys(value.effective).length, GA_KEYS.length + 1);
    assert.equal(value.effective["작업 시간 한도"], "7800초 (GA 전체 시간 상한 + 마무리 600초)");
    assert.ok(value.advice.startsWith(MAY_BE_PARTIAL) && value.advice.includes("60건 × 300초 = 18000초") &&
      value.advice.includes("7200초"), value.advice);
    assert.equal(value.start.preflightEnabled, true);
    assert.equal(value.start.enabled, false, "GA 시작 enabled without a preflight");
    return value;
  });
  await rec_.step("P03-pool-too-small", ["GA-pool-too-small"], "시작 전 확인 보기 with the defaults (population 12, ten " +
    "eligible): refused ga_pool_too_small; then population 4 with the M17 filter 중원자 수 ≤ 44 applied (three " +
    "eligible): refused ga_pool_too_small with 적격 3개; start blocked; no job, no event; then 필터 지우기", async () => {
    const jobsBefore = (await readApi(page, `/runs/${run}/jobs`)).length;
    const eventsBefore = (await runEvents(page, run)).length;
    const first = await preflight(page, run, evidence);
    await setParams(page, { population_size: "4" }, evidence);
    await fill(page, "ligand-ga-filter-heavy_atoms-max", "44");
    await gt(page, "ligand-ga-filter-apply").click();
    control(evidence, "ligand-ga-filter-apply", { heavy_atoms_max: 44 });
    await waitFor(page, async () => await gt(page, "ligand-ga-filter-applied").getAttribute("data-applied-count") === "1"
      ? true : null, "filter applied", 10000);
    const filtered = await preflight(page, run, evidence);
    await gt(page, "ligand-ga-filter-clear").click();
    control(evidence, "ligand-ga-filter-clear", { clicked: true });
    return { first, filtered, jobsBefore, jobsAfter: (await readApi(page, `/runs/${run}/jobs`)).length, eventsBefore,
      eventsAfter: (await runEvents(page, run)).length };
  }, async value => {
    for (const [pf, eligible, population] of [[value.first, 10, 12], [value.filtered, 3, 4]]) {
      assert.equal(pf.status, 200);
      assert.equal(pf.body.admission.admitted, false);
      assert.equal(pf.body.admission.reason_code, "ga_pool_too_small");
      assert.equal(pf.body.admission.detail.eligible_count, eligible);
      assert.equal(pf.body.admission.detail.population_size, population);
      assert.equal(pf.body.reserved_units, null);
      assert.equal(pf.view.reasonCode, "ga_pool_too_small");
      assert.ok(pf.view.refused.includes(`(ga_pool_too_small) · 적격 ${eligible}개, 세대당 개체 수 ${population}`), pf.view.refused);
      assert.equal(pf.view.start.enabled, false);
    }
    assert.equal(o.ids.filter(id => o.heavyAtoms[id] <= 44).length, 3, "fixture filter oracle");
    assert.equal(value.filtered.request.filter.ranges.heavy_atoms.max, 44);
    assert.deepEqual(Object.keys(value.filtered.request.filter.ranges), ["heavy_atoms"]);
    assert.equal(value.jobsAfter, value.jobsBefore);
    assert.equal(value.eventsAfter, value.eventsBefore, "a preflight read wrote events");
    const found = await checkWording("pool too small");
    assert.deepEqual(found, [], JSON.stringify(found));
    return { reasons: [value.first.view.refused, value.filtered.view.refused] };
  });

  // ---- GA 1: preflight, real run, results, sort, detail
  const pf1 = await rec_.step("G01-preflight", ["GA-preflight"], "GA 1 parameters (GA seed 11, population 4, generations " +
    "2, elite 2, tournament 2, neighbors 3, random fraction 0.5, patience 1, max new 6, total 600 s); 시작 전 확인 " +
    "보기: pool 10 / 10 / 0, reusable 0, reserved 6 = expected, need 6 units / 1200 s, remaining = budget, shortfall = " +
    "need − remaining, 끝까지 못 갈 수 있음 (6 × 300 s > 600 s) in the preflight and as advice; G1; the view shows the " +
    "server numbers", async () => {
    await setParams(page, Object.fromEntries(Object.entries(GA1).map(([key, v]) => [key, String(v)])), evidence);
    const budget = await readApi(page, `/runs/${run}/budget`);
    const pf = await preflight(page, run, evidence);
    return { pf, budget, advice: clean(await gt(page, "ligand-ga-time-advice").textContent()) };
  }, async value => {
    const facts = preflightMatches(value.pf, { gaValues: GA1, reusable: 0, budget: value.budget });
    assert.equal(facts.mayBePartial, true);
    assert.ok(value.advice.startsWith(MAY_BE_PARTIAL) && value.advice.includes("6건 × 300초 = 1800초"), value.advice);
    assert.deepEqual(value.pf.request.ga, GA1);
    assert.deepEqual(value.pf.request.filter, { ranges: {}, pains_exclude: false });
    assert.ok(!("mode" in value.pf.request) && !("ligand" in value.pf.request), "mode or ligand key in the GA request");
    const p = value.pf.request.parameters;
    assert.deepEqual([p.seed, p.exhaustiveness, p.num_modes, p.energy_range], [1, 1, 2, 3]);
    // a fresh run: 8 units − 2 M17 units = 6 = reserved, so GA 1 needs no raise (the raise is observed with GA 2)
    assert.deepEqual(facts.shortfall, { expensive_calls: 0, wall_clock_s: 0 });
    const found = await checkWording("GA 1 preflight");
    assert.deepEqual(found, [], JSON.stringify(found));
    return { ...facts, request: value.pf.request };
  });
  // rec_.step returns the action result: the preflight response, the budget read and the advice
  const firstPreflight = { reserved: pf1.pf.body.reserved_units, request: pf1.pf.request };
  const ga1 = await rec_.step("G02-run", ["GA-run", "GA-progress"], "Click GA 시작: no second approval (the M17 " +
    "inspection had it); while running the progress line equals the stored job record; the real GA runs to done; " +
    "exactly reserved_units (6) expensive units; the summary is listed but not opened", async () =>
    runGa(page, run, evidence, { progress: true }), async value => {
    assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
    assert.equal(value.job.protocol_id, "qvina_ga_dock_v1");
    assert.equal(value.job.timeout_s, GA1.total_s + 600);
    assert.equal(value.approved, false);
    assert.ok(value.phases.includes("running"), JSON.stringify(value.phases));
    assert.ok(value.progressSeen.length >= 1, "no running progress line matched the job record");
    assert.match(value.handle ?? "", /\/ligand_ga_result\//);
    assert.equal(value.budgetAfter.used, value.budgetBefore.used + firstPreflight.reserved, "units differ from reserved_units");
    assert.equal(value.jobsAfter, value.jobsBefore + 1);
    assert.equal(value.job.ga.summary_status, "complete");
    assert.ok(value.notice.includes(value.handle.split("/").at(-1).slice(0, 12)), value.notice);
    assert.equal(await gt(page, "ligand-ga-result").count(), 0, "the summary was opened automatically");
    return { job: value.job.job_id, handle: value.handle, budget: [value.budgetBefore, value.budgetAfter],
      progressSeen: value.progressSeen, phases: value.phases };
  });
  evidence.handles.A.ga1 = ga1.handle;
  const ga1Stored = storedObject(runsDir, run, ga1.handle);
  // the start needs a preflight of exactly these arguments, so the preflight request is the job's argument set
  evidence.gaArgs = { run, job: ga1.job.job_id, summary: ga1.handle, args: firstPreflight.request, timeoutS: GA1.total_s + 600 };
  await rec_.step("T01-results", ["GA-results"], "Choose the GA 1 summary: status 완료 (generations_complete), G1 only, " +
    "the summary lines, both generation tabs; every row (origin, lineage, evaluation, state, score = stored M18 first " +
    "mode with ROUND_HALF_UP, no reason) equals the stored summary; carried = the two lowest stored scores; one similar " +
    "and one random slot; similarity = the fixture Morgan Tanimoto; min/max as stored values", async () => {
    const header = await openSummary(page, ga1.handle, evidence);
    const detail = await readApi(page, `/runs/${run}/ligand/ga/results/${enc(ga1.handle)}`);
    return resultEquals(page, o, header, detail, ga1Stored, runsDir, run, evidence);
  }, async value => {
    assert.equal(value.status, "complete");
    assert.equal(value.stopReason, "generations_complete");
    assert.equal(value.generationsDone, 2);
    assert.equal(value.newDockings, 6);
    assert.equal(value.reused, 0);
    assert.deepEqual(value.statements, ["G1"]);
    const gen2 = ga1Stored.generations[1].individuals;
    assert.deepEqual(gen2.map(item => item.origin).sort(), ["carried", "carried", "random", "similar"]);
    const found = await checkWording("GA 1 results");
    assert.deepEqual(found, [], JSON.stringify(found));
    return value;
  });
  await rec_.step("T02-sort", ["GA-sort"], "Generation 2 of GA 1: click 점수, 후보 id and 자리 headers twice each: the order " +
    "follows the stored values (display order only; rows without a score stay last; no rank column), aria-sort follows",
  async () => {
    await showGeneration(page, 2, evidence);
    return sortChecks(page, ga1Stored.generations[1], evidence);
  }, async value => value);
  await rec_.step("T03-detail", ["GA-detail"], "Click 상세 열기 of generation 1 position 0: the M18 docking area above " +
    "opens that individual's stored result (mode table = stored); the GA individual read names the same result",
  async () => {
    await showGeneration(page, 1, evidence);
    const item = ga1Stored.generations[0].individuals[0];
    await gt(page, "ligand-ga-open-1-0").click();
    control(evidence, "ligand-ga-open", { generation: 1, position: 0 });
    const view = dock(page).locator(`[data-testid="docking-result"]${attr("data-docking-result-handle", item.result_handle)}`);
    await view.waitFor({ timeout: 30000 });
    const modes = await view.locator('[data-testid="docking-modes"] tbody tr[data-mode]').evaluateAll(items => items.map(row =>
      ({ mode: Number(row.getAttribute("data-mode")), cells: [...row.querySelectorAll("td")].map(cell => cell.textContent.trim()) })));
    const read = await readApi(page, `/runs/${run}/ligand/ga/results/${enc(ga1.handle)}/individual?candidate_id=${enc(item.candidate_id)}`);
    return { item, modes, read };
  }, async value => {
    const stored = storedObject(runsDir, run, value.item.result_handle);
    assert.equal(value.modes.length, stored.modes.length);
    value.modes.forEach((row, i) => {
      assert.equal(row.mode, i + 1);
      assert.equal(row.cells[1], halfUp(stored.modes[i].score_kcal_mol, 1));
    });
    assert.equal(value.read.result_handle, value.item.result_handle);
    assert.equal(value.read.score, stored.modes[0].score_kcal_mol);
    assert.equal(value.read.m18_detail?.handle ?? value.item.result_handle, value.item.result_handle);
    return { candidate: value.item.candidate_id, handle: value.item.result_handle, modes: value.modes.length };
  });

  // ---- GA 2: shortfall → screen approval → GA 1 again (existing job) → GA 2 with reuse
  let ga2 = null;
  await rec_.part("reuse", ["GA-limit-approval", "GA-dedupe", "GA-reuse"], async () => {
    const raise = await rec_.step("L01-shortfall", ["GA-limit-approval"], "GA seed 12 (docking seed unchanged); 시작 전 " +
      "확인 보기: reusable 6 (GA 1's individuals), reserved 6 but 0 units remain → shortfall, 이 GA에 필요한 만큼 한도를 " +
      "올림 shown and GA 시작 blocked (ga_limit_raise_required); click it: the limit rises by the shortfall only (by " +
      "human, GA context, no job/object), the preflight is read again with no shortfall", async () => {
      await setParams(page, { seed: String(GA2.seed) }, evidence);
      const budget = await readApi(page, `/runs/${run}/budget`);
      const pf = await preflight(page, run, evidence);
      const facts = preflightMatches(pf, { gaValues: GA2, reusable: 6, budget });
      assert.ok(facts.shortfall.expensive_calls > 0, "GA 2 has no unit shortfall");
      return { facts, ...await approveLimits(page, run, pf, evidence) };
    }, async value => ({ ...approvalMatches(value), preflight: value.facts }));
    await rec_.step("U01-identical", ["GA-dedupe"], "GA seed 11 again (GA 1's arguments): 시작 전 확인 보기 shows the " +
      "existing GA 1 job; click GA 시작: that job is shown again (no new job, no unit)", async () => {
      await setParams(page, { seed: String(GA1.seed) }, evidence);
      const pf = await preflight(page, run, evidence);
      const before = await budgetUsed(page, run);
      const jobsBefore = (await readApi(page, `/runs/${run}/jobs`)).length;
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/jobs`, { timeout: 60000 });
      await gt(page, "ligand-ga-start").click();
      control(evidence, "ligand-ga-start", { identical: true });
      const response = await posted;
      const body = await response.json();
      await waitFor(page, async () => clean(await gt(page, "ligand-ga-notice").textContent({ timeout: 1000 }).catch(() => ""))
        .includes("같은 입력의 기존 GA 작업") ? true : null, "existing job notice", 30000);
      return { pf, status: response.status(), job: body, before, after: await budgetUsed(page, run), jobsBefore,
        jobsAfter: (await readApi(page, `/runs/${run}/jobs`)).length, notice: clean(await gt(page, "ligand-ga-notice").textContent()) };
    }, async value => {
      preflightMatches(value.pf, { gaValues: GA1, reusable: 6 });
      assert.equal(value.pf.view.existingJob, ga1.job.job_id);
      assert.equal(value.pf.body.existing_job.summary_handle, ga1.handle);
      assert.equal(value.status, 200);
      assert.equal(value.job.job_id, ga1.job.job_id, "a new job was created for identical GA arguments");
      assert.equal(value.jobsAfter, value.jobsBefore);
      assert.deepEqual(value.after, value.before, "identical GA arguments were charged");
      assert.ok(value.notice.includes(ga1.job.job_id) && value.notice.includes("새 작업을 만들지 않았습니다"), value.notice);
      return { job: value.job.job_id, notice: value.notice };
    });
    ga2 = await rec_.step("U02-reuse", ["GA-reuse"], "GA seed 12: 시작 전 확인 보기 (no shortfall now); GA 시작: a new GA " +
      "job; reserved_units charged once (no refund); every individual GA 1 evaluated is 저장된 결과 재사용 with GA 1's " +
      "stored handle (no new docking for it); new docking objects = new_dockings_used; G1 and G3", async () => {
      await setParams(page, { seed: String(GA2.seed) }, evidence);
      const pf = await preflight(page, run, evidence);
      const resultsBefore = dockingResultHandles(runsDir, run);
      const job = await runGa(page, run, evidence);
      const header = await openSummary(page, job.handle, evidence);
      const detail = await readApi(page, `/runs/${run}/ligand/ga/results/${enc(job.handle)}`);
      const stored = storedObject(runsDir, run, job.handle);
      const facts = await resultEquals(page, o, header, detail, stored, runsDir, run, evidence);
      const tables = [];
      for (const gen of stored.generations) tables.push(await showGeneration(page, gen.index, evidence));
      return { pf, ...job, stored, facts, tables, resultsBefore, resultsAfter: dockingResultHandles(runsDir, run),
        published: (await runEvents(page, run)).filter(event => event.type === "ligand_ga_individual_published" &&
          event.job_id === job.job.job_id) };
    }, async value => {
      const facts = preflightMatches(value.pf, { gaValues: GA2, reusable: 6 });
      assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
      assert.notEqual(value.job.job_id, ga1.job.job_id);
      assert.equal(value.budgetAfter.used, value.budgetBefore.used + facts.reserved, "GA 2 was not charged reserved_units once");
      const firstHandles = Object.fromEntries(ga1Stored.generations.flatMap(gen => gen.individuals)
        .filter(item => item.origin !== "carried").map(item => [item.candidate_id, item.result_handle]));
      const evaluated = value.stored.generations.flatMap(gen => gen.individuals).filter(item => item.origin !== "carried");
      for (const item of evaluated) {
        if (item.candidate_id in firstHandles) {
          assert.equal(item.evaluation, "reused", `${item.candidate_id} was docked again`);
          assert.equal(item.result_handle, firstHandles[item.candidate_id], "a reused individual does not cite GA 1's result");
        } else {
          assert.equal(item.evaluation, "docked");
          assert.ok(!Object.values(firstHandles).includes(item.result_handle));
        }
      }
      assert.ok(value.stored.reused_count >= 2, "GA 2 reused fewer than 2 individuals (6 + 6 of a 10-candidate pool)");
      const created = value.resultsAfter.filter(handle => !value.resultsBefore.includes(handle));
      assert.equal(created.length, value.stored.new_dockings_used, "new docking objects differ from new_dockings_used");
      assert.equal(value.published.length, value.stored.new_dockings_used);
      assert.deepEqual(value.facts.statements, ["G1", "G3"]);
      for (const table of value.tables) for (const row of table.rows) {
        if (row.evaluation === "reused") assert.equal(row.cells[4], REUSED_LABEL);
      }
      const found = await checkWording("GA 2 results");
      assert.deepEqual(found, [], JSON.stringify(found));
      return { job: value.job.job_id, handle: value.handle, reused: value.stored.reused_count,
        newDockings: value.stored.new_dockings_used, reserved: facts.reserved, budget: [value.budgetBefore, value.budgetAfter],
        raise: raise.approved.increase };
    });
    evidence.handles.A.ga2 = ga2.handle;
  });

  // ---- GA 3 (pool exhausted, complete), GA 4 (docking limit, partial), GA 5 (cancelled, partial)
  const raiseThenRun = async (values, dockingSeed, runOptions = {}) => {
    await setParams(page, Object.fromEntries(Object.entries(values).map(([key, v]) => [key, String(v)])), evidence);
    await setDockingSeed(page, dockingSeed, evidence);
    const pf = await preflight(page, run, evidence);
    const facts = preflightMatches(pf, { gaValues: values });
    let approval = null;
    // the screen's own button (a person's click); the area reads the preflight again itself
    if (facts.shortfall.expensive_calls > 0 || facts.shortfall.wall_clock_s > 0)
      approval = approvalMatches(await approveLimits(page, run, pf, evidence));
    const job = await runGa(page, run, evidence, runOptions);
    return { facts, approval, job };
  };
  await rec_.part("pool-exhausted", ["GA-pool-exhausted", "GA-limit-approval"], async () => {
    await rec_.step("E01-pool-exhausted", ["GA-pool-exhausted", "GA-limit-approval"], "GA seed 13, generations 8, elite " +
      "0, patience 8, max new 10 (docking seed 1): shortfall → the screen's approval; GA 시작: generations 1–3 take every " +
      "eligible candidate (4 + 4 + 2), then no slot can be filled → complete / pool_exhausted; reused individuals marked; " +
      "units = reserved", async () => {
      const value = await raiseThenRun(GA3, DOCKING.seed);
      const header = await openSummary(page, value.job.handle, evidence);
      const detail = await readApi(page, `/runs/${run}/ligand/ga/results/${enc(value.job.handle)}`);
      const stored = storedObject(runsDir, run, value.job.handle);
      return { ...value, stored, facts2: await resultEquals(page, o, header, detail, stored, runsDir, run, evidence) };
    }, async value => {
      assert.equal(value.job.job.status, "done", JSON.stringify(value.job.job.failure));
      assert.equal(value.stored.status, "complete");
      assert.equal(value.stored.stop_reason, "pool_exhausted");
      const evaluated = value.stored.generations.flatMap(gen => gen.individuals).filter(item => item.origin !== "carried");
      assert.deepEqual(evaluated.map(item => item.candidate_id).sort(), [...o.ids].sort(), "not every eligible candidate");
      assert.equal(value.job.budgetAfter.used, value.job.budgetBefore.used + value.facts.reserved);
      assert.ok(value.approval, "no shortfall before GA 3");
      const found = await checkWording("pool-exhausted results");
      assert.deepEqual(found, [], JSON.stringify(found));
      return { handle: value.job.handle, generations: value.stored.generations.map(gen => gen.individuals.length),
        reused: value.stored.reused_count, newDockings: value.stored.new_dockings_used, approval: value.approval };
    });
  });
  let partialHandle = null;
  await rec_.part("docking-limit", ["GA-partial", "GA-limit-approval"], async () => {
    const value = await rec_.step("K01-docking-limit", ["GA-partial", "GA-limit-approval"], "GA seed 11, elite 0, max " +
      "new 4, docking seed 2 (nothing reusable): shortfall → the screen's approval; GA 시작: generation 1 docks 4, the " +
      "first generation-2 individual needs a fifth docking → partial / docking_limit; G1 and G2; the stopped generation " +
      "tab says it stopped; uncomputed individuals have no number", async () => {
      const ran = await raiseThenRun(GA4, "2");
      const header = await openSummary(page, ran.job.handle, evidence);
      const detail = await readApi(page, `/runs/${run}/ligand/ga/results/${enc(ran.job.handle)}`);
      const stored = storedObject(runsDir, run, ran.job.handle);
      return { ...ran, header, stored, facts2: await resultEquals(page, o, header, detail, stored, runsDir, run, evidence) };
    }, async value => {
      assert.equal(value.facts.reusable, 0);
      assert.equal(value.stored.status, "partial");
      assert.equal(value.stored.stop_reason, "docking_limit");
      assert.equal(value.stored.new_dockings_used, 4);
      assert.equal(value.stored.generations[0].individuals.length, 4);
      assert.ok(value.stored.generations.length < 2 || value.stored.generations[1].complete === false);
      assert.deepEqual(value.facts2.statements, ["G1", "G2"]);
      assert.ok(value.header.statusText.includes("일부 세대만 계산됨 (partial)"), value.header.statusText);
      assert.equal(value.job.budgetAfter.used, value.job.budgetBefore.used + value.facts.reserved);
      const found = await checkWording("partial results");
      assert.deepEqual(found, [], JSON.stringify(found));
      return { handle: value.job.handle, generations: value.stored.generations.map(gen => ({ index: gen.index,
        complete: gen.complete, n: gen.individuals.length })), approval: value.approval };
    });
    partialHandle = value?.job?.handle ?? null;
  });
  await rec_.part("cancel", ["GA-cancel"], async () => {
    await rec_.step("C01-cancel", ["GA-cancel"], "Docking seed 3 (nothing reusable), the same GA values: shortfall → " +
      "approval; GA 시작; once one individual is finished click 작업 취소: the job ends cancelled, a partial / cancelled " +
      "summary keeps the finished individuals, G2; no GA worker, docking worker or qvina2 process remains; no refund",
    async () => {
      const ran = await raiseThenRun(GA5, "3", { until: value => value.phase === "running" && value.finished >= 1 ||
        ["done", "failed", "cancelled"].includes(value.phase) });
      const processes = await waitFor(page, async () => { const found = jobProcesses(runsDir); return found.length ? found : null; },
        "job processes while running", 15000).catch(() => []);
      const cancel = gt(page, "ligand-ga-job-cancel");
      await waitFor(page, async () => await cancel.isEnabled().catch(() => false) ? true : null, "cancel enabled", 60000);
      await cancel.click();
      control(evidence, "ligand-ga-job-cancel", { finishedBefore: ran.job.phase.finished });
      const final = await waitFor(page, async () => {
        const value = await jobPhase(page);
        return value && ["cancelled", "failed", "done"].includes(value.phase) ? value : null;
      }, "job cancelled", 180000);
      const gone = await waitFor(page, async () => jobProcesses(runsDir).length === 0 ? true : null, "job processes gone", 60000)
        .then(() => true, () => false);
      const job = await readApi(page, `/runs/${run}/jobs/${enc(final.id)}`);
      const handle = job.ga?.summary_handle ?? null;
      let stored = null, facts2 = null, header = null;
      if (handle) {
        header = await openSummary(page, handle, evidence);
        const detail = await readApi(page, `/runs/${run}/ligand/ga/results/${enc(handle)}`);
        stored = storedObject(runsDir, run, handle);
        facts2 = await resultEquals(page, o, header, detail, stored, runsDir, run, evidence);
      }
      return { ...ran, gaRun: ran.job, running: ran.job.phase, processesWhileRunning: processes, final, gone, left: jobProcesses(runsDir),
        job, handle, stored, facts2, header, budgetAfter: await budgetUsed(page, run) };
    }, async value => {
      assert.equal(value.running.phase, "running", "the GA ended before it could be cancelled");
      assert.ok(value.processesWhileRunning.some(item => item.command.includes("qvina2") ||
        item.command.includes("ligand_ga_worker.py")), JSON.stringify(value.processesWhileRunning));
      assert.equal(value.job.status, "cancelled");
      assert.equal(value.gone, true, JSON.stringify(value.left));
      assert.ok(value.handle, "no partial summary was published");
      assert.equal(value.stored.status, "partial");
      assert.equal(value.stored.stop_reason, "cancelled");
      assert.ok(value.stored.new_dockings_used >= 1);
      assert.deepEqual(value.facts2.statements, ["G1", "G2"]);
      const found = await checkWording("cancelled results");
      assert.deepEqual(found, [], JSON.stringify(found));
      assert.equal(value.budgetAfter.used, value.gaRun.budgetBefore.used + value.facts.reserved,
        "a cancelled GA was refunded or overcharged");
      return { handle: value.handle, newDockings: value.stored.new_dockings_used, approval: value.approval };
    });
  });

  // ---- report of GA 2 → 지식·보고서 list → downloads; global budget = backend (the GA area unmounts here)
  await rec_.part("report", ["GA-report"], async () => {
    const target = ga2?.handle ?? ga1.handle;
    const created = await rec_.step("P10-report", ["GA-report"], "Choose the GA 2 summary; click 보고서 만들기", async () => {
      await openSummary(page, target, evidence);
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
      await gt(page, "ligand-ga-report").click();
      control(evidence, "ligand-ga-report", { clicked: true });
      const response = await posted;
      const body = await response.json();
      await gt(page, "ligand-ga-report-done").waitFor({ timeout: 30000 });
      return { status: response.status(), handle: body.handle, request: response.request().postDataJSON(), manifest: body.manifest,
        done: await gt(page, "ligand-ga-report-done").getAttribute("data-report-handle") };
    }, async value => {
      assert.equal(value.done, value.handle);
      assert.equal(value.manifest.analysis_type, "ligand_ga");
      assert.equal(value.manifest.result_handle, target);
      assert.deepEqual(value.request, { result_handle: target });
      const listed = (await readApi(page, `/runs/${run}/reports`)).find(item => item.handle === value.handle);
      assert.ok(listed, "created report not in the backend report list");
      return { handle: value.handle };
    });
    const library = page.getByRole("region", { name: "보고서 보관함", exact: true });
    const reports = library.getByRole("region", { name: "저장된 보고서", exact: true });
    const content = library.getByRole("region", { name: "선택한 항목 내용", exact: true });
    await rec_.step("P11-listed", ["GA-report"], "Click 지식·보고서: the global budget equals the backend (raised limits " +
      "kept); the list shows 리간드 GA 설계 보고서; click it: the text equals the saved Markdown (G1, G3, score name)", async () => {
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
      assert.equal(value.kind, "리간드 GA 설계 보고서");
      const saved = await readApi(page, `/runs/${run}/reports/selected?handle=${enc(created.handle)}`);
      assert.equal(value.text, saved.markdown);
      assert.ok(value.text.includes(SCORE_LABEL), "report lacks the score name");
      assert.ok(value.text.includes(G.G1), "report lacks G1");
      if (ga2) assert.ok(value.text.includes(G.G3), "report lacks G3");
      assert.ok(value.budget.backend.limit > 8, "raised limit not kept");
      return { kind: value.kind, markdownSha256: sha(Buffer.from(value.text)), budget: value.budget.shown };
    });
    for (const [label, format] of [["Markdown 다운로드", "markdown"], ["JSON 다운로드", "json"]]) {
      const route = `/runs/${run}/reports/download?handle=${enc(created.handle)}&format=${format}`;
      await rec_.step(`P12-download-${format}`, ["GA-report"], `Click ${label}; bytes equal the backend bytes`, () =>
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
  evidence.handles.A.partial = partialHandle;

  await rec_.part("processes", ["GA-processes"], () => rec_.step("Z01-processes", ["GA-processes"], "After every GA: no " +
    "GA worker, docking worker, M17 worker, guardian or qvina2 process remains under the runs folder", async () =>
    waitFor(page, async () => jobProcesses(runsDir).length === 0 ? { left: [] } : null, "no job processes", 60000)
      .catch(() => ({ left: jobProcesses(runsDir) })), async value => {
    assert.deepEqual(value.left, []);
    return value;
  }));

  evidence.budget = await readApi(page, `/runs/${run}/budget`);
  evidence.wording = wording;
  for (const id of Object.values(evidence.runs).filter(Boolean)) evidence.providerCalls.push(await providerCalls(page, id));
  const wordingOk = wording.length >= 6 && wording.every(item => !item.found.length);
  rec_.append({ caseId: "WORDING", cases: ["GA-wording"], status: wordingOk ? "pass" : "fail", checks: wording });
  if (!wordingOk) evidence.partFailures.push({ part: "wording", cases: ["GA-wording"] });
  evidence.wordingPassed = wordingOk;
}

// ------------------------------------------------------------------ mode unavailable (backend without the environments)
async function modeUnavailable(session, input, rec_, evidence, log) {
  const { page } = session;
  evidence.fixtureLabels.push(input["fixture-label"] || UNAVAILABLE_LABEL);
  const capability = (await readApi(page, "/capabilities")).methods?.ligand_ga_design ?? null;
  evidence.capability = capability && { available: capability.available, reason_code: capability.reason_code };
  assert.ok(capability && capability.available === false, `backend reports GA available: ${JSON.stringify(capability)}`);
  assert.equal((await readApi(page, "/runs")).length, 0, "mode unavailable needs a fresh runs root");
  const noControls = async () => ({ state: await gaState(page), text: clean(await ga(page).textContent()),
    controls: await ga(page).locator("button, input, select, textarea, a, img, table").count() });
  await waitForBoot(page);
  await rec_.step("V01-no-run", ["GA-no-run"], "No run yet: click 리간드 설계·탐색 → the GA area shows the no-run reason " +
    "only (no numbers, no controls)", async () => {
    await selectTab(page, TAB);
    await gt(page, "ligand-ga-no-run").waitFor({ timeout: 15000 });
    return { ...await noControls(), reason: clean(await gt(page, "ligand-ga-no-run").textContent()) };
  }, async value => {
    assert.equal(value.state, "unavailable");
    assert.ok(value.reason.includes(NO_RUN_REASON), value.reason);
    assert.ok(!/\d/.test(value.text), `a number is shown: ${value.text}`);
    assert.equal(value.controls, 0);
    return value;
  });
  const run = await rec_.step("V02-run", [], "Click 구조 분석, 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.runs.A = run;
  await rec_.step("V03-unavailable", ["GA-unavailable"], "Click 리간드 설계·탐색: 사용할 수 없음 with the capability reason " +
    "(worker_missing); no numbers, no controls, no GA requests", async () => {
    const before = Date.now();
    await selectTab(page, TAB);
    await gt(page, "ligand-ga-unavailable").waitFor({ timeout: 15000 });
    await page.waitForTimeout(2000);
    const gaReads = log.filter(row => row.at >= before && row.path.includes("/ligand/ga")).map(row => `${row.method} ${row.path}`);
    return { ...await noControls(), reason: clean(await gt(page, "ligand-ga-unavailable").textContent()), gaReads };
  }, async value => {
    assert.equal(value.state, "unavailable");
    assert.ok(value.reason.includes("사용할 수 없음"), value.reason);
    assert.ok(value.reason.includes(`(${capability.reason_code})`), value.reason);
    assert.ok(value.reason.includes(capability.reason), value.reason);
    assert.ok(!/\d/.test(value.text), `a number is shown: ${value.text}`);
    assert.equal(value.controls, 0);
    assert.deepEqual(value.gaReads, [], "the unavailable area sent GA requests");
    return value;
  });
  evidence.providerCalls.push(await providerCalls(page, run));
}

// ------------------------------------------------------------------ main
const RUNNERS = { main: modeMain, unavailable: modeUnavailable };
// Cases the real environment cannot produce honestly here (never forged): kept with the tests that cover them.
const NOT_OBSERVED = [
  { case: "GA-null-result", reason: "qvina returns modes for every small-pool candidate (T1: all ten scored), so no " +
    "individual without a score (null_result/failed) is shown; nothing is forged. The display rule (rows without a " +
    "score last, never 0) is asserted on every sort here and covered by frontend/tests/ligand-ga.test.cjs and " +
    "backend/tests/test_ligand_ga_worker.py." },
  { case: "GA-no-change", reason: "no_change depends on the engine's scores (the minimum not decreasing for patience " +
    "generations); no input is chosen to force it. Covered by backend/tests/test_ligand_ga_worker.py." },
  { case: "GA-time-and-worker-limits", reason: "time_exhausted (600–14400 s), candidate_timeout (300 s), worker_failed " +
    "and resource_exceeded need hours, a killed worker or oversized output; covered by backend/tests/" +
    "test_ligand_ga_worker.py and test_ligand_ga_jobs.py with test-only reduced constants." },
];

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const evidence = { schema: "m22_ligand_ga_evidence@1", mode: input.mode, runs: {}, inputs: [], handles: {},
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
  if (input.mode === "main") cases["GA-wording"] = evidence.wordingPassed === true ? "pass" : "fail";
  const providerZero = evidence.providerCalls.length > 0 && evidence.providerCalls.every(item => item.zero);
  const passed = !error && evidence.partFailures.length === 0 && offscreenComplete(proof) && proof.nonLoopbackRequests === 0 &&
    Object.keys(cases).length > 0 && Object.values(cases).every(value => value === "pass") && providerZero;
  evidence.finishedAt = new Date().toISOString();
  evidence.error = error ? String(error.stack ?? error) : null;
  evidence.requestCount = log.length;
  fs.writeFileSync(path.join(input.artifacts, "ligand-ga-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  fs.writeFileSync(path.join(input.artifacts, "ligand-ga-requests.jsonl"), log.map(row => JSON.stringify(row)).join("\n") + "\n");
  const harness = Object.fromEntries(["ligand-ga-flow.cjs", "docking-flow.cjs", "driver.cjs", "main.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m22_case_ledger_row@1", mode: input.mode, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", cases, runId: evidence.runs.A ?? null, runs: evidence.runs,
    handles: evidence.handles, inputs: evidence.inputs, fixtureLabels: evidence.fixtureLabels, controls: evidence.controls,
    gaArgs: evidence.gaArgs ?? null, budget: evidence.budget ?? null, notObserved: evidence.notObserved,
    buildId: buildId(), harness, offscreen: proof, externalRequestCount: proof ? proof.nonLoopbackRequests : null,
    providerCalls: evidence.providerCalls, providerCallsZero: providerZero, partFailures: evidence.partFailures,
    error: evidence.error, evidenceFile: path.basename(rec_.file), startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, runs: evidence.runs, cases }) + "\n");
  if (error) process.stderr.write(`ligand-ga-flow ${input.mode} failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`ligand-ga-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, oracle, needFor, shortfallFor, sortOracle, tanimoto6, NOT_OBSERVED };
