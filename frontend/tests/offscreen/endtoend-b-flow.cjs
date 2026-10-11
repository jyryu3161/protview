"use strict";

// M28 end-to-end acceptance, branch B (.dryforge/spec.md §4.2, B1–B8; §6 live L-B7): ligand design and search on the
// ProLIF public example receptor and pose, the public-derived parent and labeled synthetic block lists and reaction
// rules. Real Electron offscreen page (isOffscreen, GPU/WebGL, paint). Every product mutation is a Playwright locator
// mouse/keyboard/file-chooser/select input (every approval, every limit raise and every JEV send a person's click on
// the screen); nothing calls application internals and this script never posts to the API itself. Observation is
// read-only: data attributes and text of the page, renderer request/response events, Electron paint frames, downloaded
// bytes, GET reads of the loopback API, the stored objects and events in <runs-dir>/<run>/events.jsonl (read-only file
// reads) and, with the fixture server, its control folder (calls.jsonl, credentials.json).
//
// The plan (--plan, written by scripts/m28_branch_b.py) holds the independent expectations computed from the input
// files: input SHA-256 and record counts, the receptor PDB atoms and the pose SDF record-0 atoms (every stored chemical
// row role and every stored docking contact is matched to them and its distance recomputed), the rule texts, the
// docking values, the GA settings with their spec 6 numbers, the loops and the unit plan (remaining units before every
// computation, the raises a person clicks). Scores are never computed here: each one shown is compared with the first
// mode of the stored M18 docking_result@1 it names.
//
// Step functions come from the older harnesses (each block says "copied from <file>"); those files are not changed.
// Exported oracle helpers and constants are required: driver (launchOffscreen, capture, downloadByClick), docking-flow
// (halfUp, expectedLimitations, forbiddenWords), docking-batch-flow (neededFor, shortfallFor, sortOracle),
// ligand-ga-flow (needFor, shortfallFor, sortOracle), ligand-flow (candidateId), jev-flow (J, expectedLimitations,
// forbiddenWords, halfUp), jev-loop-flow (oracleOrder, expectedLimitations, forbiddenWords, INSTRUCTIONS, LJ,
// fixtureServer) and m11-ledger (provenanceLabel).
//
// Modes:
//   fixture  backend = backend/tests/offscreen_jev_loop_fixture/server.py (the product app; only SCIENCE_GATE over a
//            scripted httpx.MockTransport, scripts good / good_second only). One new run, parts in the budget order of
//            the coordinator (decision 1): B1 → B2 → B3 (+ the same arguments again) → B6 → B7 (explore round, then
//            exploit round) → B4 → B5 (setting 1, setting 2) → B8. Three limit raises, each a click on the screen.
//   live     a new run: L-pre-B2 → L-pre-B3 → L-pre-B4 (the same part code) → L-B7 (ONE exploit round). With --control
//            (rehearsal) the backend is the fixture server; without it the real science gate. The send is clicked only
//            when the plan allows it and the dispatch events of every run in --runs-dir are below plan.live.
//            dispatchLimit (one send); a send that does not complete ends the plan (no retry, no other call).
// A part whose earlier part did not pass is not run and says which one.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const m18 = require("./docking-flow.cjs");
const m19 = require("./docking-batch-flow.cjs");
const m22 = require("./ligand-ga-flow.cjs");
const { candidateId } = require("./ligand-flow.cjs");
const m24 = require("./jev-flow.cjs");
const m25 = require("./jev-loop-flow.cjs");
const { provenanceLabel } = require("./m11-ledger.cjs");

const REPO = path.resolve(__dirname, "../../..");
const MODES = ["fixture", "live"];
const TAB = { structure: "구조 분석", protein: "단백질 공학", ligand: "리간드 설계·탐색", knowledge: "지식·보고서" };
const PANEL_ID = { [TAB.structure]: "structure", [TAB.ligand]: "ligand", [TAB.knowledge]: "knowledge" };
const ACK_KEYS = ["keep_input_protonation", "tool_assigned_types_charges", "rigid_no_optimization"];
const SCORE_LABEL = "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)";
const SCORE_COLUMN = "qvina 점수(kcal/mol)";
const MODE_ROW = "모드 1(엔진 출력 순서)";
const REUSED_LABEL = "저장된 결과 재사용";
const PARENT_LABEL = "부모(기준 입력)";                                      // copied from docking-batch-flow.cjs
const NULL_TEXT = "—";
const FIXED_PROPERTY_NOTE = "필터는 저장된 RDKit 추정값에 서버가 적용합니다(경계 포함, 비우면 범위 없음). 후보를 다시 생성하지 않습니다.";
// Spec B2: properties are RDKit estimates and PAINS are structural alerts; none of these words (outside the stored
// limitation sentences, which say what was not computed) may name a candidate.
const LIGAND_WORDS = /약물\s*유사|독성|(?<!비)활성|합성\s*가능|drug-?like|toxic/i;
// spec 5.4 of M19 verbatim (copied from docking-batch-flow.cjs; independent of the product constants)
const B = {
  B1: "이 일괄의 모든 행은 같은 수용체·상자·seed·방식·값으로 계산되어 점수를 같은 표에서 나란히 볼 수 있으며, " +
    "표의 정렬은 표시 순서일 뿐 순위가 아니다.",
  B2: "이 일괄은 일부만 계산되었다. 계산하지 않은 행은 점수가 없으며 0이 아니다.",
  B3: "부모 행은 후보와 같은 설정으로 도킹한 기준 입력이며, 점수 차이를 개선이나 악화로 해석하지 않는다.",
};
// spec 4 of M22 verbatim (copied from ligand-ga-flow.cjs)
const G = {
  G1: "GA는 후보 풀에서 어디를 도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 순위나 추천이 아니다. " +
    "부모·유사 후보 연결은 작업 모듈 기록이며 서버가 다시 계산하지 않았다.",
  G2: "이 실행은 시간·도킹 상한·취소 등으로 일부 세대만 계산되었다. 계산하지 않은 개체는 점수가 없으며 0이 아니고, " +
    "한도 도달로 멈춘 실행은 같은 설정으로 다시 해도 같은 경로를 보장하지 않는다.",
  G3: "재사용한 개체는 같은 수용체·상자·seed·방식·값으로 이전에 저장된 도킹 결과를 가져온 것이며, " +
    "저장된 결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있다.",
};
const GA_STATUS_OF = { generations_complete: "complete", no_change: "complete", pool_exhausted: "complete",
  docking_limit: "partial", time_exhausted: "partial", cancelled: "partial", worker_failed: "partial",
  resource_exceeded: "partial" };                                             // copied from ligand-ga-flow.cjs
const GA_ORIGIN_LABEL = { initial: "초기", carried: "이어받음", similar: "유사", random: "무작위" };
const GA_STATE_LABEL = { scored: "점수 있음", null_result: "빈 과학 결과(모드 0개)", failed: "실패" };
const GA_SCORE_HEADER = "qvina 점수(kcal/mol) · 모드 1(엔진 출력 순서)";
const GA_CARRIED_LABEL = "다시 도킹하지 않음(이전 세대 결과 인용)";
const GA_DOCKED_LABEL = "새 도킹";
const MAY_BE_PARTIAL = "끝까지 못 갈 수 있음";
const GA_KEYS = ["seed", "population_size", "generations", "elite_count", "tournament_size", "neighbor_count",
  "random_fraction", "patience", "max_new_dockings", "total_s"];
const UNKNOWN_USAGE = "알 수 없음";
const LOOP_REPORT_KIND = "JEV 루프 보고서";
const CONFIRMING_TEXT = "루프 기록이 이 전송의 완료를 아직 보이지 않습니다. 기록을 다시 읽어 이 바퀴의 선택인지 확인하는 중입니다.";
const LIGAND_VALUES_NOTE = "RDKit estimates, not measurements; PAINS matches are structural alerts only; no receptor or " +
  "pocket information is included";                                           // copied from jev-loop-flow.cjs
const LIGAND_EXPLOIT_SUFFIX = "; scores are stored qvina values from one fixed receptor and box";
const REQUEST_MODEL = "typesafe/jev-1.13";
const PROVIDER = { allow_fallbacks: false, data_collection: "deny", zdr: true };
const WIRE_TOP_LIGAND = ["candidates", "computed", "goal", "parent", "property_methods", "schema", "task", "values_note"];

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const attr = (name, value) => `[${name}="${String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"]`;
const { halfUp } = m18;
const dist2 = value => `${halfUp(value, 2)} Å`;
const seconds = value => `${halfUp(value, 1)}초`;
const pairText = pair => `비싼 계산 ${pair.expensive_calls}단위 · 활동 시간 ${seconds(pair.wall_clock_s)}`;

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, plan: null, "runs-dir": null, control: null,
    "backend-pid": null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2);
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  const pid = value["backend-pid"] === null ? null : Number(value["backend-pid"]);
  if (!value.artifacts || !MODES.includes(value.mode) || !value.plan || !value["runs-dir"] ||
      (value.mode === "fixture" && !value.control) || (!!value.control !== (pid !== null)) ||
      (pid !== null && !(Number.isInteger(pid) && pid > 0))) throw new Error(
    `Usage: endtoend-b-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> --plan <plan.json> --runs-dir <MW_RUNS_DIR> ` +
    "[--control <fixture control dir> --backend-pid <pid of the fixture server just started> (fixture: required; live: " +
    "the rehearsal)] [--url http://127.0.0.1:3000]. Plan and sequence: scripts/m28_branch_b.py through " +
    "scripts/m28_offscreen_acceptance.py.");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  for (const key of ["artifacts", "runs-dir", "control", "plan"]) if (value[key]) value[key] = path.resolve(value[key]);
  value["backend-pid"] = pid;
  value.url = new URL("/", value.url).toString();
  value.planData = JSON.parse(fs.readFileSync(value.plan, "utf8"));
  assert.equal(value.planData.schema, "m28_branch_b_plan@1");
  assert.equal(value.planData.phase, value.mode, "the plan is of another phase");
  return value;
}

// ------------------------------------------------------------------ read-only observation (copied from jev-loop-flow.cjs)
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
function runEvents(runsDir, run) {
  return fs.readFileSync(path.join(runsDir, run, "events.jsonl"), "utf8").split("\n").filter(Boolean)
    .map(line => JSON.parse(line));
}
function storedObject(runsDir, run, handle) {
  for (const event of runEvents(runsDir, run))
    if (event.type === "object_created" && event.handle === handle)
      return JSON.parse(Buffer.from(event.payload_b64, "base64").toString("utf8"));
  throw new Error(`no object_created event for ${handle}`);
}
function storedBytes(runsDir, run, handle) {
  for (const event of runEvents(runsDir, run))
    if (event.type === "object_created" && event.handle === handle) return Buffer.from(event.payload_b64, "base64");
  throw new Error(`no object_created event for ${handle}`);
}
/** Every stored M18 docking_result@1 of the run (event-log order), payload included (read-only file read). */
function dockingResults(runsDir, run) {
  return runEvents(runsDir, run).filter(event => event.type === "object_created" && /\/docking_result\//.test(event.handle ?? ""))
    .map(event => ({ handle: event.handle, value: JSON.parse(Buffer.from(event.payload_b64, "base64").toString("utf8")) }));
}
function dispatchCounts(runsDir) {
  const counts = {};
  for (const name of fs.readdirSync(runsDir)) {
    const file = path.join(runsDir, name, "events.jsonl");
    if (!/^run_[0-9a-f]+$/.test(name) || !fs.existsSync(file)) continue;
    counts[name] = runEvents(runsDir, name).filter(event => event.type === "jev_science_dispatch_started").length;
  }
  return counts;
}
const dispatchTotal = runsDir => Object.values(dispatchCounts(runsDir)).reduce((sum, item) => sum + item, 0);
function fixtureCalls(control) {
  const file = path.join(control, "calls.jsonl");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").split("\n").filter(Boolean).map(line => JSON.parse(line)) : [];
}
function credentialReads(control) {
  const file = path.join(control, "credentials.json");
  return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : null;
}
function writeScript(control, script) {
  fs.writeFileSync(path.join(control, "script.json"), JSON.stringify({ script }) + "\n");
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
/** Renderer requests and the JSON answers of the API writes (read from the response events). */
function requestLog(page) {
  const rows = [];
  const api = [];
  page.on("request", request => {
    const url = new URL(request.url());
    rows.push({ at: Date.now(), method: request.method(), path: url.pathname, api: url.pathname.startsWith("/api/") });
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
async function waitApi(page, log, since, match, label, timeout = 120000) {
  return waitFor(page, async () => log.api.find(entry => entry.at >= since && entry.json !== undefined &&
    match(entry)) ?? null, label, timeout);
}

// ------------------------------------------------------------------ evidence (adapted from endtoend-a-flow.cjs recorder)
/** Steps and parts. A part runs only when the parts it needs passed; a step failure fails its part, which is recorded
 * and the flow goes on with the next part (and the unit tracker leaves its plan). */
function recorder(session, evidence, onPartFailure) {
  const { app, page, artifacts } = session;
  const file = path.join(artifacts, "endtoend-b.jsonl");
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
      const html = await page.evaluate(() => document.querySelector('.mw-app-tabs [role="tab"][aria-selected="true"]')
        ? document.getElementById(document.querySelector('.mw-app-tabs [role="tab"][aria-selected="true"]')
          .getAttribute("aria-controls") ?? "")?.outerHTML.slice(0, 400000) ?? "" : "").catch(() => null);
      if (html) fs.writeFileSync(path.join(artifacts, `${id}-failure.panel.html`), html);
      append({ id, part: current, status: "fail", description, error: String(error.stack ?? error),
        actionResult: result === undefined ? null : summarize(result), screenshot: proof && fileRecord(proof.screenshot),
        paint: proof && fileRecord(proof.paint.path), durationMs: Date.now() - started });
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
      append({ id: `${name}-aborted`, part: name, status: "fail", error: String(error.stack ?? error) });
      onPartFailure(name);
      return null;
    } finally { current = null; }
  }
  return { step, part, append, file, app };
}
const OMITTED_TEXT = new Set(["body", "instructions", "question"]);
function summarize(value) {
  try {
    const text = JSON.stringify(value, (key, item) => OMITTED_TEXT.has(key) && typeof item === "string"
      ? `<omitted ${item.length} characters>` : item);
    return text.length > 8000 ? `${text.slice(0, 8000)}…` : JSON.parse(text);
  } catch { return String(value); }
}
/** A tab area's text for the X4 scan, handed to the runner through the branch module (texts/<name>.tabtext: not a text
 * suffix of the runner, kept in the git-ignored artifacts; the branch-A convention). */
async function keepTabText(page, evidence, artifacts, name, tabId) {
  const label = Object.keys(PANEL_ID).find(key => PANEL_ID[key] === tabId);
  if (await tabButton(page, label).getAttribute("aria-selected") !== "true") await selectTab(page, label);
  const text = await page.locator(`#mw-app-panel-${tabId}`).innerText({ timeout: 15000 });
  const rel = path.join("texts", `${name.replace(/[^a-z0-9_-]/gi, "_")}.tabtext`);
  fs.mkdirSync(path.join(artifacts, "texts"), { recursive: true });
  fs.writeFileSync(path.join(artifacts, rel), text);
  evidence.texts[name] = rel;
  return { name, bytes: Buffer.byteLength(text), sha256: sha(Buffer.from(text)) };
}
function noteReport(evidence, caseId, kind, status, handle) {
  if (status === 201) evidence.reportsCreated += 1;
  evidence.reportHandles.push({ case: caseId, kind, httpStatus: status, handle });
}
function x5(evidence, ok, detail) { evidence.x5.push({ ok: !!ok, detail }); }

/** The remaining expensive units before every computation (the plan's number while every earlier computation went
 * as planned) and the units each computation used (always its planned number). */
function unitTracker(page, plan, evidence) {
  let onPlan = true;
  let run = null;
  async function read() {
    const budget = await readApi(page, `/runs/${run}/budget`);
    return { limit: budget.expensive_calls.limit, used: budget.expensive_calls.used,
      wallLimit: budget.wall_clock_s.limit, wallUsed: budget.wall_clock_s.used };
  }
  return {
    setRun(id) { run = id; },
    offPlan() { onPlan = false; },
    async before(label) {
      const now = await read();
      const entry = { label, before: now, remaining: now.limit - now.used, planned: plan.units.units[label],
        plannedRemaining: plan.units.remainingBefore[label], onPlan };
      evidence.units.push(entry);
      if (onPlan) assert.equal(entry.remaining, entry.plannedRemaining,
        `${label}: ${entry.remaining} units remain, the plan says ${entry.plannedRemaining}`);
      return entry;
    },
    async after(entry) {
      const now = await read();
      entry.after = now;
      entry.usedUnits = now.used - entry.before.used;
      assert.equal(entry.usedUnits, entry.planned, `${entry.label}: used ${entry.usedUnits} units, planned ${entry.planned}`);
      return entry;
    },
  };
}

// ------------------------------------------------------------------ tabs, runs (copied from endtoend-a-flow.cjs)
const tabButton = (page, label) => page.locator(".mw-app-tabs").getByRole("tab", { name: label, exact: true });
async function selectTab(page, label) {
  await tabButton(page, label).click();
  await waitFor(page, async () => await tabButton(page, label).getAttribute("aria-selected") === "true", `${label} selected`, 10000);
}
const globalRun = page => page.evaluate(() => document.querySelector(".mw-app-run")?.getAttribute("data-global-run") ?? null);
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
  await selectTab(page, TAB.structure);
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

// ------------------------------------------------------------------ B1 chemical workspace (copied from chemical-flow.cjs)
async function chemical(page) {
  return page.evaluate(() => typeof window.__protviewQaChemical === "function" ? window.__protviewQaChemical() : null);
}
async function waitChemical(page, predicate, timeout = 45000) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    last = await chemical(page);
    if (last && predicate(last)) return last;
    await page.waitForTimeout(100);
  }
  throw new Error(`Chemical native observation timed out: ${JSON.stringify(last)?.slice(0, 600)}`);
}
async function chooseChemicalFile(page, label, file, run) {
  const holder = page.locator(".mw-chemical-file").filter({ hasText: label });
  assert.equal(await holder.count(), 1, `Expected one file input for ${label}`);
  const chooser = page.waitForEvent("filechooser", { timeout: 15000 });
  await holder.locator('input[type="file"]').click();
  await (await chooser).setFiles(file);
  await holder.getByText(/obj:\/\/run_/).waitFor({ timeout: 30000 });
  const handle = (await holder.getByText(/obj:\/\/run_/).innerText()).trim();
  const meta = await readApi(page, `/runs/${run}/objects/meta?handle=${enc(handle)}`);
  const local = sha(fs.readFileSync(file));
  assert.equal(meta.summary?.sha256, local, `Imported ${label} bytes differ from the chosen file`);
  return { name: path.basename(file), bytes: fs.statSync(file).size, sha256: local, handle,
    provenance: provenanceLabel(path.basename(file)) };
}
function nestedSelect(page, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return page.locator("label").filter({ hasText: new RegExp(`^\\s*${escaped}`) }).locator("select");
}
async function clickButton(page, name) { await page.getByRole("button", { name, exact: true }).click(); }
async function rail(page, name) { await page.getByRole("tab", { name: new RegExp(`^${name}(?: ·|$)`) }).click(); }
async function submittedJob(page, stage, previous = null) {
  return waitChemical(page, state => {
    const id = stage === "prepare" ? state.prepareJobId : state.detectJobId;
    return !!id && id !== previous;
  }, 30000);
}
async function waitChemicalJob(page, stage, id) {
  await page.waitForFunction(({ stage, id }) => {
    const node = document.querySelector(".mw-chemical-stack");
    const proof = window.__protviewQaChemical?.();
    return !!node && (stage === "prepare" ? proof?.prepareJobId : proof?.detectJobId) === id &&
      [...document.querySelectorAll(".mw-chemical-job")].some(job => job.textContent?.includes(id) && job.textContent?.includes("done"));
  }, { stage, id }, { timeout: 240000 });
  return page.locator(".mw-chemical-job").filter({ hasText: id }).innerText();
}
/** Start a saved chemical job; approve through 이 실제 작업 승인 when asked (the run's first expensive call), then start. */
async function chemicalStart(page, stage) {
  const start = stage === "prepare" ? "준비 작업 시작" : "상호작용 작업 시작";
  const initial = await chemical(page);
  const id = stage === "prepare" ? initial.prepareJobId : initial.detectJobId;
  assert.ok(id, `${stage} job ID absent after visible submission`);
  await clickButton(page, start);
  const approval = page.getByRole("button", { name: "이 실제 작업 승인" });
  const deadline = Date.now() + 30000;
  let needsApproval = false;
  while (Date.now() < deadline) {
    if (await approval.isVisible().catch(() => false)) { needsApproval = true; break; }
    const jobText = await page.locator(".mw-chemical-job").filter({ hasText: id }).innerText();
    if (/\b(running|done|failed|interrupted)\b/.test(jobText)) break;
    await page.waitForTimeout(100);
  }
  if (needsApproval) {
    await approval.click();
    await page.getByText(/계산 승인을 기록했습니다/).first().waitFor({ timeout: 30000 });
    await page.getByRole("button", { name: start }).waitFor({ state: "visible" });
    await clickButton(page, start);
  }
  return { id, text: await waitChemicalJob(page, stage, id), approvalSeen: needsApproval };
}
async function chemicalRows(page, run, handle) {
  const rows = [];
  let total = null;
  while (total === null || rows.length < total) {
    const chunk = await readApi(page, `/runs/${run}/chemical/results/rows?handle=${enc(handle)}&offset=${rows.length}&limit=50`);
    total = chunk.total;
    rows.push(...chunk.rows);
    if (!chunk.rows.length) break;
  }
  return rows;
}
const separation = (a, b) => Math.hypot(...a.map((value, index) => value - b[index]));
function angleAt(donor, hydrogen, acceptor) {
  const a = donor.map((value, index) => value - hydrogen[index]);
  const b = acceptor.map((value, index) => value - hydrogen[index]);
  const cos = a.reduce((sum, value, index) => sum + value * b[index], 0) / (Math.hypot(...a) * Math.hypot(...b));
  return Math.acos(Math.max(-1, Math.min(1, cos))) * 180 / Math.PI;
}
const atomIdentity = ref => JSON.stringify([ref.structure_handle, ref.residue.model_number, ref.residue.chain_auth,
  ref.residue.chain_label, ref.residue.seq_auth, ref.residue.seq_label, ref.residue.icode, ref.residue.resname,
  ref.atom_name, ref.altloc, ref.element, ref.site_index]);              // copied from chemical-flow.cjs
/** The input atom one stored role names: a receptor atom by its residue fields and atom name (and element and
 * coordinates within 0.002 Å), a ligand atom (the declared instance) by element and coordinates in pose record 0. */
function inputAtomOf(plan, ref, xyz) {
  const ligand = plan.chemical.ligand;
  const isLigand = ref.residue.chain_auth === ligand.chain_auth && ref.residue.seq_auth === ligand.seq_auth &&
    ref.residue.resname === ligand.resname;
  const near = atom => Math.hypot(...atom.xyz.map((value, index) => value - xyz[index])) <= 0.002;
  if (isLigand) {
    const found = plan.poseRecord0.filter(atom => atom.element === String(ref.element).toUpperCase() && near(atom));
    return found.length === 1 ? { side: "ligand", atom: found[0] } : null;
  }
  const found = plan.receptorAtoms.filter(atom => atom.chain === ref.residue.chain_auth && atom.seq === ref.residue.seq_auth &&
    atom.icode === (ref.residue.icode ?? "") && atom.resname === ref.residue.resname && atom.name === ref.atom_name &&
    atom.element === String(ref.element).toUpperCase() && near(atom));
  return found.length === 1 ? { side: "receptor", atom: found[0] } : null;
}

// ------------------------------------------------------------------ ligand tab areas (copied from ligand-flow.cjs / docking-flow.cjs)
const ligandPanel = page => page.locator('#mw-app-panel-ligand [data-testid="ligand-panel"]');
const lt = (page, id) => ligandPanel(page).locator(`[data-testid="${id}"]`);
const ligandState = page => ligandPanel(page).getAttribute("data-ligand-state", { timeout: 2000 }).catch(() => null);
const ligandArea = (page, area) => ligandPanel(page).locator(`[data-ligand-area="${area}"]`).getAttribute("data-state", { timeout: 2000 })
  .catch(() => null);
const dock = page => page.locator('#mw-app-panel-ligand [data-testid="docking-panel"]');
const dt = (page, id) => dock(page).locator(`[data-testid="${id}"]`);
const dockState = page => dock(page).getAttribute("data-docking-state", { timeout: 2000 }).catch(() => null);
const dockArea = (page, area) => dock(page).locator(`[data-docking-area="${area}"]`).getAttribute("data-state", { timeout: 2000 })
  .catch(() => null);
const batch = page => page.locator('#mw-app-panel-ligand [data-testid="docking-batch-panel"]');
const bt = (page, id) => batch(page).locator(`[data-testid="${id}"]`);
const ga = page => page.locator('#mw-app-panel-ligand [data-testid="ligand-ga-panel"]');
const gt = (page, id) => ga(page).locator(`[data-testid="${id}"]`);
async function openLigandTab(page) {
  await selectTab(page, TAB.ligand);
  await ligandPanel(page).waitFor({ timeout: 15000 });
  await dock(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => ["ready", "scientific_null", "failure", "unavailable"].includes(await ligandState(page)) &&
    await ligandArea(page, "inspections") !== "loading" && await ligandArea(page, "sets") !== "loading" &&
    ["ready", "scientific_null", "failure", "unavailable"].includes(await dockState(page)) &&
    await dockArea(page, "results") === "ready" ? true : null, "ligand tab settled", 60000);
}
async function chooseLigandFile(page, slot, file) {
  const chooser = page.waitForEvent("filechooser", { timeout: 15000 });
  await lt(page, `ligand-file-${slot}`).click();
  await (await chooser).setFiles(file);
}
async function ligandJobPhase(page) {
  const job = lt(page, "ligand-job");
  if (!await job.count()) return null;
  return { phase: await job.getAttribute("data-ligand-job-phase"), status: await job.getAttribute("data-ligand-job-status"),
    id: await job.getAttribute("data-ligand-job-id"), protocol: await job.getAttribute("data-ligand-job-protocol") };
}
/** Start an M17 job (real input); approve when asked, then 작업 시작; wait for the job to finish. */
async function runLigandJob(page, run, startId, protocol) {
  const prior = (await ligandJobPhase(page))?.id ?? null;
  await lt(page, startId).click();
  const settled = async () => {
    const value = await ligandJobPhase(page);
    if (!value || value.protocol !== protocol || value.id === prior) return null;
    if (["running", "done", "failed", "cancelled"].includes(value.phase)) return value;
    if (value.phase === "awaiting_approval" && await lt(page, "ligand-job-approve").isEnabled().catch(() => false)) return value;
    if (value.phase === "saved" && await lt(page, "ligand-job-start").isEnabled().catch(() => false)) return value;
    return null;
  };
  const first = await waitFor(page, settled, `${protocol} job submitted`, 60000);
  let approved = false;
  if (first.phase === "awaiting_approval") {
    await lt(page, "ligand-job-approve").click();
    approved = true;
    await waitFor(page, async () => (await settled())?.phase === "saved" ? true : null, "approval recorded", 30000);
  }
  if ((await ligandJobPhase(page)).phase === "saved") await lt(page, "ligand-job-start").click();
  const done = await waitFor(page, async () => {
    const value = await ligandJobPhase(page);
    return value && value.id !== prior && ["done", "failed", "cancelled"].includes(value.phase) ? value : null;
  }, `${protocol} job finished`, 240000);
  const job = await readApi(page, `/runs/${run}/jobs/${enc(done.id)}`);
  return { approved, job, handle: job.artifacts?.ligand_inspection ?? job.artifacts?.ligand_candidate_set ?? null };
}
async function candidateTable(page) {
  const count = lt(page, "ligand-candidate-count");
  await count.waitFor({ timeout: 30000 });
  const counts = await count.evaluate(node => ({ total: node.getAttribute("data-total"), passing: node.getAttribute("data-passing"),
    hidden: node.getAttribute("data-hidden"), matched: node.getAttribute("data-matched"),
    text: node.textContent.replace(/\s+/g, " ").trim() }));
  const table = lt(page, "ligand-candidates");
  const rows = !await table.count() ? [] : await table.locator("tr[data-candidate-id]").evaluateAll(items => items.map(item => ({
    id: item.getAttribute("data-candidate-id"), order: Number(item.getAttribute("data-generation-order")),
    passesAll: item.getAttribute("data-passes-all"), smiles: item.querySelector(".mw-ligand-smiles")?.textContent.trim() ?? null,
    filters: Object.fromEntries([...item.querySelectorAll("td[data-filter]")].map(cell =>
      [cell.getAttribute("data-filter"), cell.getAttribute("data-pass")])),
    pains: Number(item.querySelector("[data-pains-count]")?.getAttribute("data-pains-count") ?? NaN),
    painsText: item.querySelector("[data-pains-count]")?.textContent.trim() ?? null })));
  const headers = !await table.count() ? [] : (await table.locator("thead th").allTextContents()).map(clean);
  return { counts, rows, headers };
}
async function rowsAfter(page, run, act) {
  const response = page.waitForResponse(item => item.request().method() === "GET" &&
    new URL(item.url()).pathname === `/api/runs/${run}/ligand/candidate_sets/rows`, { timeout: 30000 });
  await act();
  const received = await response;
  assert.equal(received.status(), 200, `rows read failed: ${await received.text()}`);
  const body = await received.json();
  await waitFor(page, async () => {
    const table = await candidateTable(page);
    return table.rows.length === body.rows.length && table.rows.every((row, i) => row.id === body.rows[i].candidate.id) ? true : null;
  }, "candidate table shows the received rows", 30000);
  return { query: new URL(received.url()).search, body, table: await candidateTable(page) };
}
async function fillLigandFilter(page, name, side, value) {
  const field = lt(page, `ligand-filter-${name}-${side}`);
  await field.click();
  await field.fill(value);
}
/** Import the receptor through the docking area (file chooser + 가져오기); the handle is the receptor import whose
 * stored bytes are this file (an import of the same bytes may already exist: the chemical workspace's). */
async function ensureReceptor(page, run, file) {
  const chooser = page.waitForEvent("filechooser", { timeout: 15000 });
  await dt(page, "docking-file-receptor").click();
  await (await chooser).setFiles(file);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/chemical/imports`, { timeout: 60000 });
  await dt(page, "docking-import").click();
  const status = (await posted).status();
  assert.ok([200, 201].includes(status), `receptor import HTTP ${status}`);
  await dt(page, "docking-import-done").waitFor({ timeout: 60000 });
  const want = sha(fs.readFileSync(file));
  const receptors = (await readApi(page, `/runs/${run}/docking/prerequisites`)).imports.filter(item => item.input_kind === "receptor");
  const matching = [];
  for (const item of receptors) {
    const meta = await readApi(page, `/runs/${run}/objects/meta?handle=${enc(item.handle)}`);
    if (meta.summary?.sha256 === want) matching.push(item.handle);
  }
  assert.equal(matching.length, 1, `receptor imports with the file's bytes: ${matching.length}`);
  return { handle: matching[0], status };
}
/** The docking form (copied from docking-flow.cjs fillForm; candidate source, free mode, manual box). */
async function fillDockingForm(page, spec) {
  const radio = async selector => { const input = dock(page).locator(`${selector} input`); await input.waitFor({ timeout: 30000 }); await input.check(); };
  const fill = async (id, value) => { const field = dt(page, id); await field.click(); await field.fill(value); };
  await dt(page, "docking-receptor").selectOption(spec.receptor);
  await dt(page, "docking-model").waitFor({ timeout: 30000 });
  await dt(page, "docking-model").selectOption(spec.values.model);
  await dt(page, "docking-instances").waitFor({ timeout: 30000 });
  await radio('[data-testid="docking-instances"] label[data-docking-instance="none"]');
  await dt(page, "docking-connectivity").locator("label").filter({ hasText: "PDB CONECT" }).locator("input").check();
  await radio('label[data-docking-source="candidate"]');
  await dt(page, "docking-candidate-set").selectOption(spec.set);
  await radio(`label${attr("data-docking-candidate", spec.candidate)}`);
  await dt(page, "docking-parent-sdf").selectOption(spec.parent);
  await radio('label[data-docking-mode="free"]');
  await radio('label[data-docking-box="manual"]');
  for (const [i, axis] of ["x", "y", "z"].entries()) {
    await fill(`docking-center-${axis}`, spec.values.center[i]);
    await fill(`docking-size-${axis}`, spec.values.size[i]);
  }
  await fill("docking-seed", spec.values.seed);
  await fill("docking-exhaustiveness", spec.values.exhaustiveness);
  await fill("docking-num-modes", spec.values.numModes);
  await fill("docking-energy-range", spec.values.energyRange);
  for (const key of ACK_KEYS) await dock(page).locator(`label[data-docking-ack="${key}"] input`).check();
}
async function dockingJobPhase(page) {
  const job = dt(page, "docking-job");
  if (!await job.count()) return null;
  return { phase: await job.getAttribute("data-docking-job-phase"), status: await job.getAttribute("data-docking-job-status"),
    id: await job.getAttribute("data-docking-job-id") };
}
/** Click 도킹 작업 시작; approve when asked, then 작업 시작; wait for the job (copied from docking-flow.cjs runDockingJob). */
async function runDockingJob(page, run) {
  const phases = [];
  const previousJob = (await dockingJobPhase(page))?.id ?? null;
  await dt(page, "docking-start").click();
  const settled = async () => {
    const value = await dockingJobPhase(page);
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
    await waitFor(page, async () => (await settled())?.phase === "saved" ? true : null, "approval recorded", 30000);
  }
  if ((await dockingJobPhase(page)).phase === "saved" && await dt(page, "docking-job-start").isEnabled().catch(() => false))
    await dt(page, "docking-job-start").click();
  const done = await waitFor(page, async () => {
    const value = await dockingJobPhase(page);
    if (value && value.phase !== phases.at(-1)) phases.push(value.phase);
    return value && ["done", "failed", "cancelled"].includes(value.phase) ? value : null;
  }, "docking job final", 600000);
  const job = await readApi(page, `/runs/${run}/jobs/${enc(done.id)}`);
  if (done.phase === "done") await dt(page, "docking-result-notice").waitFor({ timeout: 30000 });
  return { phases, approved, job, handle: job.artifacts?.docking_result ?? null };
}
async function openDockingResult(page, handle) {
  await waitFor(page, async () => await dockArea(page, "results") === "ready" ? true : null, "results list", 30000);
  const input = dock(page).locator(`label${attr("data-docking-result", handle)} input`);
  await input.waitFor({ timeout: 30000 });
  await input.check();
  await dock(page).locator(`[data-testid="docking-result"]${attr("data-docking-result-handle", handle)}`).waitFor({ timeout: 30000 });
}
async function dockingResultView(page) {
  const view = dt(page, "docking-result");
  const summary = await view.locator('[data-testid="docking-summary"] .mw-ligand-fact').evaluateAll(items => items.map(item =>
    [item.querySelector("dt").textContent.trim(), item.querySelector("dd").textContent.trim()]));
  const rows = await view.locator('[data-testid="docking-modes"] tbody tr[data-mode]').evaluateAll(items => items.map(item => ({
    mode: Number(item.getAttribute("data-mode")), cells: [...item.querySelectorAll("td")].map(cell => cell.textContent.trim()) })));
  return { summary: Object.fromEntries(summary), rows,
    headers: await view.locator('[data-testid="docking-modes"] thead th').allTextContents().catch(() => []),
    caption: clean(await view.locator('[data-testid="docking-modes"] caption').textContent({ timeout: 1000 }).catch(() => "")),
    limitations: await view.locator('[data-testid="docking-limitations"] li').allTextContents() };
}
/** The displayed mode table equals the stored rows (copied from docking-flow.cjs modeTableEquals, free mode). */
function modeTableEquals(view, detail, stored) {
  assert.equal(view.rows.length, stored.modes.length);
  assert.equal(detail.result.modes.length, stored.modes.length);
  stored.modes.forEach((row, i) => {
    const cells = view.rows[i].cells;
    assert.equal(view.rows[i].mode, row.mode);
    assert.equal(row.mode, i + 1);
    assert.equal(cells[0], `모드 ${row.mode}(엔진 출력 순서)`);
    assert.equal(cells[1], halfUp(row.score_kcal_mol, 1), `score of row ${row.mode}`);
    assert.equal(cells[2], String(row.contacts.length));
    assert.equal(detail.result.modes[i].contact_count, row.contacts.length);
    assert.equal(cells[3], dist2(row.min_heavy_atom_distance_A));
    assert.equal(cells[4], String(row.atoms_outside_box));
    assert.equal(cells[5], `${dist2(row.engine_rmsd_lb_A)} · ${dist2(row.engine_rmsd_ub_A)}`);
  });
}
/** Stored contacts obey the M18 rule (copied from docking-flow.cjs contactsFollowRules). */
function contactsFollowRules(stored, cutoff) {
  for (const row of stored.modes) {
    const keys = row.contacts.map(item => [item.ligand_serial, item.receptor_atom.site_index]);
    for (let i = 1; i < keys.length; i++)
      assert.ok(keys[i - 1][0] < keys[i][0] || (keys[i - 1][0] === keys[i][0] && keys[i - 1][1] < keys[i][1]), "contact order");
    for (const item of row.contacts) {
      assert.ok(item.distance_A <= cutoff, `contact over cutoff: ${item.distance_A}`);
      assert.notEqual(item.ligand_element, "H");
      assert.notEqual(item.receptor_atom.element, "H");
      assert.equal(item.kind, m18.contactKind(item.ligand_element, item.receptor_atom.element));
    }
  }
}
const KIND_LABEL = { contact: "기타 접촉(contact)", polar_contact: "극성 접촉(polar_contact)",
  hydrophobic_contact: "소수성 접촉(hydrophobic_contact)" };                 // copied from docking-flow.cjs
async function contactTable(page, mode) {
  const box = dock(page).locator(`[data-testid="docking-contacts"][data-mode="${mode}"]`);
  await box.locator(".mw-docking-contact-page").waitFor({ timeout: 30000 });
  const pageNode = box.locator(".mw-docking-contact-page");
  return { total: Number(await pageNode.getAttribute("data-total")), count: clean(await dt(page, "docking-contacts-count").textContent()),
    note: clean(await dock(page).locator('[data-testid="docking-contacts"] .mw-ligand-note').first().textContent()),
    rows: await box.locator("tbody tr").evaluateAll(items => items.map(item => ({
      ligandSerial: Number(item.getAttribute("data-ligand-serial")), siteIndex: Number(item.getAttribute("data-site-index")),
      cells: [...item.querySelectorAll("td")].map(cell => cell.textContent.trim()) }))) };
}
/** The displayed contact page equals the stored contact rows (copied from docking-flow.cjs contactsEqual). */
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
}
/** V2000 atoms of one SDF record (1-based serial, element, coordinates). */
function sdfAtoms(text) {
  const lines = text.split("\n");
  assert.ok(lines[3]?.trimEnd().endsWith("V2000"), "the stored pose is not a V2000 record");
  const count = Number(lines[3].slice(0, 3));
  return lines.slice(4, 4 + count).map((line, i) => ({ serial: i + 1, element: line.slice(31, 34).trim().toUpperCase(),
    xyz: [Number(line.slice(0, 10)), Number(line.slice(10, 20)), Number(line.slice(20, 30))] }));
}
/** Independent contacts: every receptor heavy atom of the input PDB within the cutoff of a heavy atom of the stored pose
 * (the same pair rule as scripts/m28_branch_b.contact_pairs). */
function recomputeContacts(plan, poseText) {
  const pose = sdfAtoms(poseText).filter(atom => !["H", "D"].includes(atom.element));
  const heavy = plan.receptorAtoms.filter(atom => !["H", "D"].includes(atom.element));
  const pairs = [];
  for (const ligand of pose) for (const atom of heavy) {
    const distance = Math.hypot(...atom.xyz.map((value, i) => value - ligand.xyz[i]));
    if (distance <= plan.contactCutoff_A)
      pairs.push({ key: `${ligand.serial}|${atom.chain}|${atom.seq}|${atom.icode}|${atom.resname}|${atom.name}`, distance,
        kind: m18.contactKind(ligand.element, atom.element) });
  }
  return pairs;
}

// ------------------------------------------------------------------ batch area (copied from docking-batch-flow.cjs)
async function batchStart(page) {
  return { enabled: await bt(page, "docking-batch-start").isEnabled(),
    blocked: clean(await bt(page, "docking-batch-start-blocked").textContent({ timeout: 1000 }).catch(() => "")) };
}
async function batchPreflight(page, run) {
  await waitFor(page, async () => await bt(page, "docking-batch-preflight").isEnabled() ? true : null, "preflight enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/docking/batches/preflight`, { timeout: 60000 });
  await bt(page, "docking-batch-preflight").click();
  const response = await posted;
  const body = await response.json();
  return { status: response.status(), body, request: response.request().postDataJSON(), view: await batchPreflightView(page, body) };
}
async function batchPreflightView(page, body) {
  if (!body.admission.admitted) {
    await bt(page, "docking-batch-preflight-refused").waitFor({ timeout: 30000 });
    return { refused: clean(await bt(page, "docking-batch-preflight-refused").textContent()) };
  }
  const view = bt(page, "docking-batch-preflight-view");
  await waitFor(page, async () => await view.count() &&
    await view.getAttribute("data-new-dockings") === String(body.new_dockings) &&
    await view.getAttribute("data-shortfall-calls") === String(body.shortfall.expensive_calls) ? true : null, "preflight view", 30000);
  return {
    newDockings: Number(await view.getAttribute("data-new-dockings")),
    reusedRows: Number(await view.getAttribute("data-reused-rows")),
    shortfallCalls: Number(await view.getAttribute("data-shortfall-calls")),
    shortfallWall: Number(await view.getAttribute("data-shortfall-wall")),
    lines: Object.fromEntries(await view.locator(".mw-ligand-fact").evaluateAll(items => items.map(item =>
      [item.querySelector("dt").textContent.trim(), item.querySelector("dd").textContent.trim()]))),
    rows: await bt(page, "docking-batch-preflight-rows").locator("li").evaluateAll(items => items.map(item => ({
      row: Number(item.getAttribute("data-row-index")), reuse: item.getAttribute("data-reuse") === "true",
      text: item.textContent.trim() }))),
    statements: await bt(page, "docking-batch-preflight-statements").locator("li[data-statement]").evaluateAll(items =>
      items.map(item => ({ id: item.getAttribute("data-statement"), text: item.textContent.trim() }))),
    approvalButtons: await bt(page, "docking-batch-limit-approve").count(),
    start: await batchStart(page),
  };
}
function batchPreflightMatches(pf, { rows, reused }) {
  const body = pf.body, view = pf.view;
  assert.equal(pf.status, 200);
  assert.equal(body.admission.admitted, true, JSON.stringify(body.admission));
  assert.equal(body.starts_job, false);
  const n = rows - reused;
  assert.equal(body.new_dockings, n);
  assert.equal(body.reused_rows, reused);
  assert.deepEqual(body.needed, m19.neededFor(n), "needed differs from spec 6.3 arithmetic");
  assert.deepEqual(body.shortfall, m19.shortfallFor(body.needed, body.remaining), "shortfall differs from needed - remaining");
  assert.equal(view.newDockings, n);
  assert.equal(view.reusedRows, reused);
  assert.equal(view.lines["새로 계산할 행"], `${n}개`);
  assert.equal(view.lines["재사용"], `${REUSED_LABEL} ${reused}개 (과금하지 않음)`);
  assert.equal(view.lines["필요"], `${pairText(body.needed)} (최대)`);
  assert.equal(view.lines["현재 잔여"], pairText(body.remaining));
  assert.equal(view.lines["부족분"], pairText(body.shortfall));
  assert.deepEqual(view.statements, [{ id: "B1", text: B.B1 }], "preflight statement is not B1 verbatim");
  const shortfall = body.shortfall.expensive_calls > 0 || body.shortfall.wall_clock_s > 0;
  assert.equal(view.approvalButtons, shortfall ? 1 : 0, "limit approval shown iff shortfall > 0");
  return { n, needed: body.needed, remaining: body.remaining, shortfall: body.shortfall };
}
async function batchJobPhase(page) {
  const job = bt(page, "docking-batch-job");
  if (!await job.count()) return null;
  return { phase: await job.getAttribute("data-batch-job-phase"), id: await job.getAttribute("data-batch-job-id") };
}
async function runBatch(page, run) {
  const previousJob = (await batchJobPhase(page))?.id ?? null;
  await waitFor(page, async () => (await batchStart(page)).enabled ? true : null, "start enabled", 15000);
  await bt(page, "docking-batch-start").click();
  const settled = async () => {
    const value = await batchJobPhase(page);
    if (!value || value.id === previousJob) return null;
    if (["running", "done", "failed", "cancelled"].includes(value.phase)) return value;
    if (value.phase === "awaiting_approval" && await bt(page, "docking-batch-job-approve").isEnabled().catch(() => false)) return value;
    if (value.phase === "saved" && await bt(page, "docking-batch-job-start").isEnabled().catch(() => false)) return value;
    return null;
  };
  const first = await waitFor(page, settled, "batch job submitted", 120000);
  let approved = false;
  if (first.phase === "awaiting_approval") {
    await bt(page, "docking-batch-job-approve").click();
    approved = true;
    await waitFor(page, async () => (await settled())?.phase === "saved" ? true : null, "approval recorded", 30000);
  }
  if ((await batchJobPhase(page)).phase === "saved" && await bt(page, "docking-batch-job-start").isEnabled().catch(() => false))
    await bt(page, "docking-batch-job-start").click();
  const done = await waitFor(page, async () => {
    const value = await batchJobPhase(page);
    return value && ["done", "failed", "cancelled"].includes(value.phase) ? value : null;
  }, "batch job", 900000);
  const job = await readApi(page, `/runs/${run}/jobs/${enc(done.id)}`);
  return { approved, job, handle: job.batch?.summary_handle ?? null };
}
async function batchResultTable(page) {
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
async function openBatchSummary(page, handle) {
  const radio = batch(page).locator(`label${attr("data-batch-summary", handle)} input`);
  await waitFor(page, async () => await radio.count() ? true : null, "summary listed", 30000);
  await radio.check();
  await bt(page, "docking-batch-result").and(batch(page).locator(attr("data-batch-handle", handle))).waitFor({ timeout: 30000 });
  return batchResultTable(page);
}
/** Every displayed cell equals the stored summary row and each score its row's first mode (copied from
 * docking-batch-flow.cjs tableEquals). */
function batchTableEquals(table, detail, stored, runsDir, run) {
  assert.equal(table.handle, detail.handle);
  assert.equal(table.status, stored.status);
  assert.equal(table.stopReason ?? null, stored.stop_reason);
  assert.equal(table.mode, stored.inputs.mode);
  assert.deepEqual(detail.summary, stored, "detail summary differs from the stored object");
  assert.equal(table.headers[3], SCORE_COLUMN);
  assert.equal(table.caption, SCORE_LABEL);
  const want = ["B1", ...(stored.status === "partial" ? ["B2"] : []), ...(stored.inputs.include_parent ? ["B3"] : [])];
  assert.deepEqual(table.statements, want.map(id => ({ id, text: B[id] })), "batch statements differ from spec 5.4");
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
    if (row.state === "scored") {
      const result = storedObject(runsDir, run, row.result_handle);
      assert.equal(row.score_kcal_mol, result.modes[0].score_kcal_mol, "summary score is not the stored first row");
      assert.equal(shown.cells[3], halfUp(row.score_kcal_mol, 1));
      assert.equal(shown.cells[4], MODE_ROW);
      assert.deepEqual(result.parameters, stored.parameters);
      assert.deepEqual(result.box, stored.box);
    } else {
      assert.equal(row.score_kcal_mol, null);
      assert.equal(shown.cells[3], "", `row ${row.row_index} (${row.state}) shows a score`);
    }
    assert.equal(shown.reused, reusedSet.has(row.row_index));
    assert.equal(shown.cells[6], shown.reused ? REUSED_LABEL : "");
    assert.equal(shown.openEnabled, !!row.result_handle);
  }
}
/** Each sortable header twice: the order follows the independent sort oracle (copied from docking-batch-flow.cjs). */
async function batchSortChecks(page, stored) {
  const seen = [];
  for (const key of ["score", "candidate", "row"]) for (const direction of ["asc", "desc"]) {
    await bt(page, `docking-batch-sort-${key}`).click();
    const want = m19.sortOracle(stored.rows, key, direction).map(row => row.row_index);
    const table = await waitFor(page, async () => {
      const value = await batchResultTable(page);
      return JSON.stringify(value.rows.map(row => row.row)) === JSON.stringify(want) ? value : null;
    }, `sort ${key} ${direction}`, 10000);
    const column = { row: 0, candidate: 1, score: 3 }[key];
    assert.equal(table.aria[column], direction === "asc" ? "ascending" : "descending");
    assert.ok(!table.headers.some(text => /순위|rank/i.test(text)), "a rank column is shown");
    seen.push({ key, direction, order: want });
  }
  return seen;
}

// ------------------------------------------------------------------ GA area (copied from ligand-ga-flow.cjs)
async function gaFill(page, id, value) { const field = gt(page, id); await field.click(); await field.fill(String(value)); }
async function gaStart(page) {
  return { enabled: await gt(page, "ligand-ga-start").isEnabled(),
    blocked: clean(await gt(page, "ligand-ga-start-blocked").textContent({ timeout: 1000 }).catch(() => "")),
    preflightEnabled: await gt(page, "ligand-ga-preflight").isEnabled() };
}
async function openGaArea(page) {
  await openLigandTab(page);
  await ga(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => await ga(page).getAttribute("data-ga-state") === "ready" &&
    await ga(page).locator('[data-ga-area="results"]').getAttribute("data-state") === "ready" ? true : null, "GA area settled", 60000);
}
async function gaChooseInputs(page, run, inputs, docking) {
  const reread = page.waitForResponse(response => response.request().method() === "GET" &&
    new URL(response.url()).pathname === `/api/runs/${run}/docking/prerequisites`, { timeout: 30000 });
  await gt(page, "ligand-ga-prereq-refresh").click();
  await reread;
  await waitFor(page, async () => await gt(page, "ligand-ga-candidate-set").locator(`option${attr("value", inputs.set)}`).count()
    ? true : null, "set listed", 30000);
  await gt(page, "ligand-ga-candidate-set").selectOption(inputs.set);
  await gt(page, "ligand-ga-parent-sdf").waitFor({ timeout: 30000 });
  await gt(page, "ligand-ga-parent-sdf").selectOption(inputs.parent);
  await gt(page, "ligand-ga-receptor").selectOption(inputs.receptor);
  await gt(page, "ligand-ga-model").waitFor({ timeout: 30000 });
  await gt(page, "ligand-ga-model").selectOption(docking.model);
  await gt(page, "ligand-ga-instances").waitFor({ timeout: 30000 });
  await ga(page).locator('[data-testid="ligand-ga-instances"] label[data-ga-instance="none"] input').check();
  await gt(page, "ligand-ga-connectivity").locator("label").filter({ hasText: "PDB CONECT" }).locator("input").check();
  await ga(page).locator('label[data-ga-box="manual"] input').check();
  for (const [i, axis] of ["x", "y", "z"].entries()) {
    await gaFill(page, `ligand-ga-center-${axis}`, docking.center[i]);
    await gaFill(page, `ligand-ga-size-${axis}`, docking.size[i]);
  }
  await gaFill(page, "ligand-ga-docking-seed", docking.seed);
  await gaFill(page, "ligand-ga-exhaustiveness", docking.exhaustiveness);
  await gaFill(page, "ligand-ga-num-modes", docking.numModes);
  await gaFill(page, "ligand-ga-energy-range", docking.energyRange);
  for (const key of ACK_KEYS) await ga(page).locator(`label[data-ga-ack="${key}"] input`).check();
}
async function gaPreflight(page, run) {
  await waitFor(page, async () => await gt(page, "ligand-ga-preflight").isEnabled() ? true : null, "preflight enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/ligand/ga/preflight`, { timeout: 60000 });
  await gt(page, "ligand-ga-preflight").click();
  const response = await posted;
  const body = await response.json();
  return { status: response.status(), body, request: response.request().postDataJSON(), view: await gaPreflightView(page, body) };
}
async function gaPreflightView(page, body) {
  if (!body.admission.admitted) {
    await gt(page, "ligand-ga-preflight-refused").waitFor({ timeout: 30000 });
    return { refused: clean(await gt(page, "ligand-ga-preflight-refused").textContent()),
      reasonCode: await gt(page, "ligand-ga-preflight-refused").getAttribute("data-reason-code"), start: await gaStart(page) };
  }
  const view = gt(page, "ligand-ga-preflight-view");
  await waitFor(page, async () => await view.count() &&
    await view.getAttribute("data-reserved-units") === String(body.reserved_units) &&
    await view.getAttribute("data-shortfall-calls") === String(body.shortfall.expensive_calls) ? true : null, "preflight view", 30000);
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
    approvalButtons: await gt(page, "ligand-ga-limit-approve").count(),
    start: await gaStart(page),
  };
}
/** The displayed preflight lines equal the server numbers, and the server numbers equal the spec 6 arithmetic
 * (copied from ligand-ga-flow.cjs preflightMatches). */
function gaPreflightMatches(pf, { gaValues, pool, want }) {
  const body = pf.body, view = pf.view;
  assert.equal(pf.status, 200);
  assert.equal(body.admission.admitted, true, JSON.stringify(body.admission));
  assert.equal(body.starts_job, false);
  assert.deepEqual(body.ga, gaValues, "the preflight's effective parameters differ from the typed values");
  assert.deepEqual(body.pool, pool);
  const arithmetic = m22.needFor(gaValues);
  assert.equal(body.reserved_units, arithmetic.reserved, "reserved_units differs from spec 6 arithmetic");
  assert.equal(body.reserved_units, want.reserved, "reserved_units differs from the plan");
  assert.deepEqual(body.needed, arithmetic.needed, "needed differs from spec 6 arithmetic");
  assert.equal(body.needed.wall_clock_s, want.neededWall);
  assert.deepEqual(body.shortfall, m22.shortfallFor(body.needed, body.remaining), "shortfall differs from needed − remaining");
  assert.equal(body.full_run_may_be_partial, want.mayBePartial);
  assert.deepEqual(body.statements, [{ id: "G1", text: G.G1 }], "preflight statement is not G1 verbatim");
  assert.equal(view.reservedUnits, body.reserved_units);
  assert.equal(view.reusable, body.reusable_count);
  assert.equal(view.shortfallCalls, body.shortfall.expensive_calls);
  assert.equal(view.shortfallWall, body.shortfall.wall_clock_s);
  assert.equal(view.mayBePartial, String(body.full_run_may_be_partial));
  assert.equal(view.lines["예약 단위"], `${body.reserved_units}단위`);
  assert.equal(view.lines["필요"], `${pairText(body.needed)} (최대)`);
  assert.equal(view.lines["현재 잔여"], pairText(body.remaining));
  assert.equal(view.lines["부족분"], pairText(body.shortfall));
  assert.equal(view.lines["과금"], `시작하면 ${body.reserved_units}단위가 예약·소진되고 중간에 멈추거나 재사용이 있어도 돌려받지 않음`);
  if (body.full_run_may_be_partial) assert.ok(view.lines["시간 상한"].startsWith(MAY_BE_PARTIAL), view.lines["시간 상한"]);
  assert.deepEqual(view.statements, [{ id: "G1", text: G.G1 }], "the shown preflight statement is not G1 verbatim");
  const shortfall = body.shortfall.expensive_calls > 0 || body.shortfall.wall_clock_s > 0;
  assert.equal(view.approvalButtons, shortfall ? 1 : 0, "limit approval shown iff shortfall > 0");
  assert.equal(view.start.enabled, !shortfall, `start ${view.start.enabled} with shortfall ${JSON.stringify(body.shortfall)}`);
  return { reserved: body.reserved_units, needed: body.needed, remaining: body.remaining, shortfall: body.shortfall,
    reusable: body.reusable_count, mayBePartial: body.full_run_may_be_partial, lines: view.lines };
}
/** The screen's limit approval button (a person's click); the preflight is read again (copied from ligand-ga-flow.cjs). */
async function gaApproveLimits(page, run, pf) {
  const budget = await readApi(page, `/runs/${run}/budget`);
  const approval = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/ligand/ga/limit_approval`, { timeout: 60000 });
  const reread = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/ligand/ga/preflight`, { timeout: 60000 });
  await gt(page, "ligand-ga-limit-approve").click();
  const approvedResponse = await approval;
  const approved = await approvedResponse.json();
  const again = await (await reread).json();
  await gt(page, "ligand-ga-limit-done").waitFor({ timeout: 30000 });
  const view = await gaPreflightView(page, again);
  return { budget, approved, approvalRequest: approvedResponse.request().postDataJSON(), again, view,
    done: clean(await gt(page, "ligand-ga-limit-done").textContent()),
    raisedAttr: await gt(page, "ligand-ga-limit-done").getAttribute("data-raised"),
    budgetAfter: await readApi(page, `/runs/${run}/budget`), pf };
}
function gaApprovalMatches(value, events) {
  const { pf, approved, budget, budgetAfter } = value;
  const shortfall = pf.body.shortfall;
  assert.equal(approved.raised, true);
  assert.equal(approved.increase.expensive_calls, shortfall.expensive_calls, "the raise is not the unit shortfall");
  assert.ok(approved.increase.wall_clock_s >= shortfall.wall_clock_s, "the wall raise is below the shortfall");
  assert.deepEqual(value.approvalRequest, pf.request, "the approval body is not the previewed GA arguments");
  assert.equal(budgetAfter.expensive_calls.limit, budget.expensive_calls.limit + shortfall.expensive_calls);
  assert.equal(budgetAfter.expensive_calls.used, budget.expensive_calls.used, "the approval used budget");
  const updated = events.filter(event => event.type === "budget_limit_updated");
  assert.equal(updated.length, 1, JSON.stringify(events.map(event => event.type)));
  assert.equal(updated[0].by, "human");
  assert.equal(updated[0].context.purpose, "ligand_ga_limit_raise");
  assert.ok(!events.some(event => event.type.startsWith("job_") || event.type === "object_created"), "the approval created a job or an object");
  assert.equal(value.raisedAttr, "true");
  assert.ok(value.done.includes("되돌리지 않음"), value.done);
  assert.deepEqual(value.again.shortfall, { expensive_calls: 0, wall_clock_s: 0 });
  assert.equal(value.view.approvalButtons, 0, "approval still offered without a shortfall");
  assert.equal(value.view.start.enabled, true, value.view.start.blocked);
  return { shortfall, increase: approved.increase, limitsBefore: approved.limits_before, limitsAfter: approved.limits_after };
}
async function gaJobPhase(page) {
  const job = gt(page, "ligand-ga-job");
  if (!await job.count()) return null;
  return { phase: await job.getAttribute("data-ga-job-phase"), id: await job.getAttribute("data-ga-job-id") };
}
async function runGa(page, run) {
  const previousJob = (await gaJobPhase(page))?.id ?? null;
  await waitFor(page, async () => (await gaStart(page)).enabled ? true : null, "start enabled", 15000);
  await gt(page, "ligand-ga-start").click();
  const settled = async () => {
    const value = await gaJobPhase(page);
    if (!value || value.id === previousJob) return null;
    if (["running", "done", "failed", "cancelled"].includes(value.phase)) return value;
    if (value.phase === "awaiting_approval" && await gt(page, "ligand-ga-job-approve").isEnabled().catch(() => false)) return value;
    if (value.phase === "saved" && await gt(page, "ligand-ga-job-start").isEnabled().catch(() => false)) return value;
    return null;
  };
  const first = await waitFor(page, settled, "GA job submitted", 120000);
  let approved = false;
  if (first.phase === "awaiting_approval") {
    await gt(page, "ligand-ga-job-approve").click();
    approved = true;
    await waitFor(page, async () => (await settled())?.phase === "saved" ? true : null, "approval recorded", 30000);
  }
  if ((await gaJobPhase(page)).phase === "saved" && await gt(page, "ligand-ga-job-start").isEnabled().catch(() => false))
    await gt(page, "ligand-ga-job-start").click();
  const done = await waitFor(page, async () => {
    const value = await gaJobPhase(page);
    return value && ["done", "failed", "cancelled"].includes(value.phase) ? value : null;
  }, "GA job", 900000);
  const job = await readApi(page, `/runs/${run}/jobs/${enc(done.id)}`);
  return { approved, job, handle: job.ga?.summary_handle ?? null };
}
async function openGaSummary(page, handle) {
  await waitFor(page, async () => await ga(page).locator(`label${attr("data-ga-summary", handle)}`).count() ? true : null,
    "summary listed", 30000);
  await ga(page).locator(`label${attr("data-ga-summary", handle)} input`).check();
  await gt(page, "ligand-ga-result").and(ga(page).locator(attr("data-ga-handle", handle))).waitFor({ timeout: 30000 });
  const view = gt(page, "ligand-ga-result");
  return { handle: await view.getAttribute("data-ga-handle"), status: await view.getAttribute("data-ga-status"),
    stopReason: await view.getAttribute("data-stop-reason"), statusText: clean(await gt(page, "ligand-ga-status").textContent()),
    statements: await gt(page, "ligand-ga-statements").locator("li").evaluateAll(items => items.map(item =>
      ({ id: item.getAttribute("data-statement"), text: item.textContent.trim() }))),
    summaryLines: Object.fromEntries(await gt(page, "ligand-ga-summary").locator("[data-summary-line]").evaluateAll(items =>
      items.map(item => [item.querySelector("dt").textContent.trim(), item.querySelector("dd").textContent.trim()]))),
    tabs: await gt(page, "ligand-ga-generation-tabs").locator('[role="tab"]').evaluateAll(items => items.map(item => ({
      id: item.getAttribute("data-testid"), complete: item.getAttribute("data-complete"), text: item.textContent.trim() })))
      .catch(() => []) };
}
async function gaGenerationTable(page) {
  const table = gt(page, "ligand-ga-individuals");
  return { generation: Number(await gt(page, "ligand-ga-generation-panel").getAttribute("data-generation")),
    range: clean(await gt(page, "ligand-ga-generation-range").textContent()),
    caption: clean(await table.locator("caption").textContent()),
    headers: (await table.locator("thead th").allTextContents()).map(clean),
    aria: await table.locator("thead th").evaluateAll(items => items.map(item => item.getAttribute("aria-sort"))),
    rows: await table.locator("tbody tr").evaluateAll(items => items.map(item => ({
      position: Number(item.getAttribute("data-position")), candidate: item.getAttribute("data-candidate-id"),
      cells: [...item.querySelectorAll("td")].map(cell => cell.textContent.trim()),
      openEnabled: !item.querySelector("button").disabled }))) };
}
async function gaShowGeneration(page, index) {
  await gt(page, `ligand-ga-generation-${index}`).click();
  await waitFor(page, async () => await gt(page, "ligand-ga-generation-panel").getAttribute("data-generation") === String(index)
    ? true : null, `generation ${index} shown`, 15000);
  return gaGenerationTable(page);
}
/** The opened summary equals the stored object (adapted from ligand-ga-flow.cjs resultEquals: the pool is this run's
 * set, so the similarity values are checked for their form and parent only; the fixture fingerprints of M22 do not
 * cover it). Scores = the stored M18 result's first mode. */
async function gaResultEquals(page, ids, header, detail, stored, runsDir, run) {
  assert.equal(header.handle, detail.handle);
  assert.deepEqual(detail.summary, stored, "detail summary differs from the stored object");
  assert.equal(header.status, stored.status);
  assert.equal(header.stopReason, stored.stop_reason);
  assert.equal(GA_STATUS_OF[stored.stop_reason], stored.status, "stop reason outside the closed set or status mismatch");
  const statusLabel = stored.status === "complete" ? "완료" : "일부 세대만 계산됨";
  assert.ok(header.statusText.startsWith(`GA 상태: ${statusLabel} (${stored.status}) · 종료 이유:`), header.statusText);
  assert.ok(header.statusText.endsWith(`(${stored.stop_reason})`), header.statusText);
  const all = stored.generations.flatMap(gen => gen.individuals);
  const reused = all.filter(item => item.evaluation === "reused").length;
  const docked = all.filter(item => item.evaluation === "docked").length;
  const want = ["G1", ...(stored.status === "partial" ? ["G2"] : []), ...(reused > 0 ? ["G3"] : [])];
  assert.deepEqual(stored.limitations, want, "stored G sentence ids differ from the spec 4 rule");
  assert.deepEqual(header.statements, want.map(id => ({ id, text: G[id] })), "shown G sentences differ from spec 4");
  assert.equal(stored.reused_count, reused);
  assert.equal(stored.new_dockings_used, docked);
  assert.ok(stored.new_dockings_used <= stored.reserved_units);
  assert.equal(header.summaryLines["새 도킹"], `${stored.new_dockings_used}건 (예약 ${stored.reserved_units}단위)`);
  assert.equal(header.summaryLines[REUSED_LABEL], `${stored.reused_count}개 (과금하지 않음)`);
  assert.equal(header.tabs.length, stored.generations.length);
  const seen = new Set();
  let previous = null;
  const tables = [];
  for (const gen of stored.generations) {
    const table = await gaShowGeneration(page, gen.index);
    assert.equal(table.caption, SCORE_LABEL);
    assert.deepEqual(table.headers, ["자리", "후보 id", "출처", "부모 · 유사도", "평가", "상태", GA_SCORE_HEADER, "이유", "상세"]);
    const scores = gen.individuals.filter(item => item.state === "scored").map(item => item.score);
    assert.equal(gen.min_score, scores.length ? Math.min(...scores) : null);
    assert.equal(gen.max_score, scores.length ? Math.max(...scores) : null);
    assert.equal(table.range, scores.length ? `점수 최솟값 ${halfUp(gen.min_score, 1)} · 점수 최댓값 ${halfUp(gen.max_score, 1)} (kcal/mol)`
      : "이 세대에 점수 있는 개체 없음");
    assert.equal(table.rows.length, gen.individuals.length);
    gen.individuals.forEach((item, position) => {
      const row = table.rows.find(entry => entry.position === position);
      assert.ok(row, `generation ${gen.index} position ${position} not shown`);
      assert.ok(ids.includes(item.candidate_id), "an individual outside the pool");
      assert.equal(row.cells[1], item.candidate_id);
      assert.equal(row.cells[2], GA_ORIGIN_LABEL[item.origin]);
      if (item.origin === "carried") {
        assert.ok(previous?.individuals.some(entry => entry.candidate_id === item.candidate_id), "carried without a previous");
        assert.equal(row.cells[4], GA_CARRIED_LABEL);
      } else {
        assert.ok(!seen.has(item.candidate_id), `candidate ${item.candidate_id} evaluated twice`);
        seen.add(item.candidate_id);
        assert.equal(row.cells[4], item.evaluation === "reused" ? REUSED_LABEL : GA_DOCKED_LABEL);
      }
      if (item.origin === "similar") {
        assert.match(item.similarity, /^[01]\.\d{6}$/, "similarity is not a 6-decimal string");
        assert.ok(previous.individuals.some(entry => entry.candidate_id === item.parent_candidate_id && entry.state === "scored"));
        assert.equal(row.cells[3], `부모 ${item.parent_candidate_id} · 지문 Tanimoto ${item.similarity}`);
      } else assert.equal(row.cells[3], "");
      assert.equal(row.cells[5], `${GA_STATE_LABEL[item.state]} (${item.state})`);
      if (item.state === "scored") {
        const result = storedObject(runsDir, run, item.result_handle);
        assert.equal(item.score, result.modes[0].score_kcal_mol, "individual score is not the stored first mode");
        assert.equal(result.inputs.ligand.candidate_id, item.candidate_id);
        assert.equal(result.inputs.mode, "free");
        assert.equal(row.cells[6], halfUp(item.score, 1));
      } else {
        assert.equal(item.score, null);
        assert.equal(row.cells[6], "", "a score is shown for an individual without one");
      }
    });
    tables.push({ generation: gen.index, complete: gen.complete, range: table.range, rows: gen.individuals.map(item => ({
      id: item.candidate_id, origin: item.origin, evaluation: item.evaluation, state: item.state, score: item.score })) });
    previous = gen;
  }
  return { status: stored.status, stopReason: stored.stop_reason, generationsDone: stored.generations_done,
    newDockings: stored.new_dockings_used, reused: stored.reused_count, reserved: stored.reserved_units, statements: want, tables };
}
async function gaSortChecks(page, gen) {
  const seen = [];
  for (const key of ["score", "candidate", "slot"]) for (const direction of ["asc", "desc"]) {
    await gt(page, `ligand-ga-sort-${key}`).click();
    const want = m22.sortOracle(gen.individuals, key, direction).map(row => row.position);
    const table = await waitFor(page, async () => {
      const value = await gaGenerationTable(page);
      return JSON.stringify(value.rows.map(row => row.position)) === JSON.stringify(want) ? value : null;
    }, `sort ${key} ${direction}`, 10000);
    const column = { slot: 0, candidate: 1, score: 6 }[key];
    assert.equal(table.aria[column], direction === "asc" ? "ascending" : "descending");
    seen.push({ key, direction, order: want });
  }
  return seen;
}

// ------------------------------------------------------------------ JEV area of 지식·보고서 (copied from jev-flow.cjs)
const jev = page => page.locator('#mw-app-panel-knowledge [data-testid="jev-panel"]');
const jt = (page, id) => jev(page).locator(`[data-testid="${id}"]`);
const jarea = (page, name) => jev(page).locator(`[data-jev-area="${name}"]`);
async function openKnowledge(page) {
  await selectTab(page, TAB.knowledge);
  await jev(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => await jev(page).getAttribute("data-jev-state") === "ready" &&
    await jarea(page, "status").getAttribute("data-state") === "ready" &&
    await jarea(page, "history").getAttribute("data-state") === "ready" ? true : null, "JEV area ready", 45000);
}
async function jevSetConsent(page, run, on) {
  if ((await jt(page, "jev-consent-label").getAttribute("data-consent") === "on") === on) return null;
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/jev/consent`, { timeout: 30000 });
  await jt(page, "jev-consent").click();
  const response = await posted;
  assert.equal(response.status(), 200, await response.text());
  const body = await response.json();
  assert.equal(body.enabled, on);
  await waitFor(page, async () => await jt(page, "jev-consent-label").getAttribute("data-consent") === (on ? "on" : "off")
    ? true : null, "consent shown", 15000);
  return body;
}
async function jevRowKeys(page) {
  return jev(page).locator("tr[data-jev-candidate-row]").evaluateAll(items => items.map(item => ({
    key: item.getAttribute("data-jev-candidate-row"), checked: item.getAttribute("data-checked") === "true" })));
}
async function jevChooseSource(page, handle, rows) {
  await jt(page, "jev-kind-ligand").check();
  const radio = jev(page).locator(`input[data-testid="jev-source"]${attr("data-jev-source", handle)}`);
  await radio.waitFor({ timeout: 30000 });
  if (!(await radio.isChecked())) await radio.check();
  return waitFor(page, async () => {
    if (await jarea(page, "candidates").getAttribute("data-state") !== "ready") return null;
    if (await jt(page, "jev-candidates").count() !== 1) return null;
    const found = await jevRowKeys(page);
    return found.length === rows ? found : null;
  }, "candidate rows", 30000);
}
async function jevBuild(page, run) {
  const command = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/commands` &&
    response.request().postDataJSON()?.tool === "build_jev_projection", { timeout: 120000 });
  const previewed = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/jev/preview`, { timeout: 120000 });
  await jt(page, "jev-build").click();
  const response = await command;
  const result = await response.json();
  assert.equal(response.status(), 200, JSON.stringify(result).slice(0, 600));
  assert.equal(result.ok, true);
  const handle = result.handle.handle;
  const preview = await (await previewed).json();
  assert.equal(preview.projection_handle, handle);
  await jev(page).locator(`[data-testid="jev-preview"]${attr("data-projection-handle", handle)}`).waitFor({ timeout: 30000 });
  return { request: response.request().postDataJSON(), handle, summary: result.handle.summary, preview };
}
async function jevPreviewShown(page) {
  const box = jt(page, "jev-preview");
  return { handle: await box.getAttribute("data-projection-handle"), sha256: await box.getAttribute("data-body-sha256"),
    bytes: Number(await box.getAttribute("data-body-bytes")),
    blocked: await jt(page, "jev-preview-blocked").locator("li[data-block-reason]").evaluateAll(items =>
      items.map(item => ({ code: item.getAttribute("data-block-reason"), text: item.textContent.trim() }))),
    aliases: await jt(page, "jev-alias-table").locator("tr[data-alias]").evaluateAll(items =>
      items.map(item => ({ alias: item.getAttribute("data-alias"), cells: [...item.cells].map(cell => cell.textContent.trim()) }))),
    question: clean(await jt(page, "jev-preview-question").textContent()),
    body: await jt(page, "jev-preview-body").textContent() };
}
/** Body identity (copied from jev-flow.cjs previewIdentity). */
function jevPreviewIdentity(shown, built, stored) {
  const bytes = Buffer.from(shown.body, "utf8");
  assert.equal(shown.body, built.preview.body, "<pre> text differs from the server preview body");
  assert.equal(sha(bytes), built.preview.body_sha256);
  assert.equal(bytes.length, built.preview.body_bytes);
  assert.equal(shown.sha256, built.preview.body_sha256);
  assert.equal(shown.bytes, built.preview.body_bytes);
  assert.equal(stored.body_sha256, built.preview.body_sha256, "stored projection body hash");
  assert.equal(stored.body_bytes, built.preview.body_bytes);
  assert.ok(built.preview.body_bytes <= 65536);
  const body = JSON.parse(shown.body);
  assert.deepEqual(Object.keys(body).sort(), ["model", "provider", "questions", "state"]);
  assert.deepEqual(body.state, stored.wire, "body state differs from the stored wire");
  assert.deepEqual(shown.aliases.map(row => row.alias), stored.selection.map(item => item.alias));
  for (const [index, item] of stored.selection.entries())
    assert.ok(shown.aliases[index].cells[1].includes(item.candidate_id), `alias table row ${item.alias}`);
  assert.deepEqual(body.state.candidates.map(item => item.alias), stored.selection.map(item => item.alias));
  for (const forbidden of ["obj://", "handle", "run_id", "/Users/", "candidate_id"])
    assert.ok(!shown.body.includes(forbidden), `body carries ${forbidden}`);
  return { bodySha256: built.preview.body_sha256, bodyBytes: built.preview.body_bytes, aliases: stored.selection.length };
}
async function jevConfirmAndSend(page, run, controlDir, script) {
  if (controlDir) writeScript(controlDir, script);
  if (!(await jt(page, "jev-confirm").isChecked())) await jt(page, "jev-confirm").check();
  await waitFor(page, async () => await jt(page, "jev-send").isEnabled() ? true : null, "send enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/jev/sends`, { timeout: 90000 });
  await jt(page, "jev-send").click();
  const response = await posted;
  assert.equal(response.status(), 200, await response.text());
  const record = await response.json();
  await jev(page).locator(`[data-testid="jev-send-record"]${attr("data-send-id", record.send_id)}`).waitFor({ timeout: 30000 });
  await waitFor(page, async () => {
    const card = jev(page).locator(`[data-testid="jev-result-card"]${attr("data-send-id", record.send_id)}`);
    const reason = jev(page).locator(`[data-testid="jev-result-reason"]${attr("data-send-id", record.send_id)}`);
    return (await card.count()) + (await reason.count()) > 0 ? true : null;
  }, "result shown", 30000);
  return { request: response.request().postDataJSON(), record };
}
async function jevReadCard(page, sendId) {
  const card = jev(page).locator(`[data-testid="jev-result-card"]${attr("data-send-id", sendId)}`);
  const details = card.locator('[data-testid="jev-result-probabilities"]');
  const foldedBefore = !(await details.evaluate(node => node.open));
  if (foldedBefore) await details.locator("summary").click();
  return { foldedBefore, choiceHandle: await card.getAttribute("data-choice-handle"), chosen: await card.getAttribute("data-chosen-alias"),
    lateAttr: await card.getAttribute("data-late"), alias: clean(await card.locator('[data-testid="jev-result-alias"]').textContent()),
    local: clean(await card.locator('[data-testid="jev-result-local"]').textContent()),
    confidence: clean(await card.locator('[data-testid="jev-result-confidence"]').textContent()),
    model: clean(await card.locator('[data-testid="jev-result-model"]').textContent()),
    usage: Object.fromEntries(await card.locator("dd[data-usage]").evaluateAll(items =>
      items.map(item => [item.getAttribute("data-usage"), item.textContent.trim()]))),
    reported: await details.getAttribute("data-reported"),
    probabilities: await details.locator("li[data-alias]").evaluateAll(items =>
      items.map(item => ({ alias: item.getAttribute("data-alias"), text: item.textContent.trim() }))),
    limitations: await card.locator('[data-testid="jev-result-limitations"] [data-limitation]').evaluateAll(items =>
      items.map(item => item.textContent)),
    comparison: await jev(page).evaluate(node => ({
      graphics: node.querySelectorAll("progress, meter, svg, canvas").length, ariaSort: node.querySelectorAll("[aria-sort]").length,
      styled: [...node.querySelectorAll("[style]")].filter(item => /width|background|color/i.test(item.getAttribute("style"))).length,
      attrs: [...node.querySelectorAll("*")].flatMap(item => [...item.attributes].map(a => a.name))
        .filter(name => /rank|best|score|recommend|winner/i.test(name)).length })) };
}
/** The completed card = the stored proposal and nothing that orders or compares (copied from jev-flow.cjs cardMatches). */
function jevCardMatches(shown, record, choice, projection) {
  assert.equal(shown.choiceHandle, record.choice_handle);
  assert.equal(choice.scientific_result, false);
  assert.equal(choice.label, "JEV 판정(모델 선택)");
  assert.equal(shown.chosen, choice.answer.choice_alias);
  assert.equal(shown.alias, choice.answer.choice_alias);
  const aliases = projection.selection.map(item => item.alias);
  assert.ok(aliases.includes(choice.answer.choice_alias));
  assert.ok(shown.local.includes(choice.answer.local_display.smiles), shown.local);
  assert.equal(shown.confidence, choice.answer.confidence === null ? "보고 없음" : m24.halfUp(choice.answer.confidence, 3));
  assert.equal(shown.model, choice.served_model);
  for (const key of ["input_tokens", "output_tokens", "external_tokens", "cost"]) {
    const value = choice.usage === null ? null : choice.usage[key];
    assert.equal(shown.usage[key], value === null ? UNKNOWN_USAGE : String(value), `usage ${key}`);
  }
  if (choice.answer.probabilities !== null) {
    assert.equal(shown.reported, "true");
    assert.deepEqual(shown.probabilities.map(item => item.alias), aliases, "probabilities not in the sent order");
  } else assert.equal(shown.reported, "false");
  assert.deepEqual(shown.limitations, m24.expectedLimitations("ligand", choice.arrival.late));
  assert.equal(shown.lateAttr, String(choice.arrival.late));
  assert.deepEqual(shown.comparison, { graphics: 0, ariaSort: 0, styled: 0, attrs: 0 });
  assert.equal(shown.foldedBefore, true, "the per-candidate values were not folded when the card appeared");
  return { alias: shown.alias, confidence: shown.confidence, reported: shown.reported, late: choice.arrival.late };
}
/** The audit `prepared` body of a send = the preview body; one dispatch (copied from jev-flow.cjs preparedMatches). */
function preparedMatches(runsDir, run, sendId, shownBody, bodySha) {
  const events = runEvents(runsDir, run);
  const prepared = events.filter(event => event.type === "egress" && event.stage === "prepared" && event.send_id === sendId);
  assert.equal(prepared.length, 1, `prepared audits of ${sendId}`);
  assert.equal(prepared[0].scope, "science");
  assert.equal(prepared[0].payload_sha256, bodySha);
  assert.deepEqual(prepared[0].body, JSON.parse(shownBody), "prepared audit body differs from the preview body");
  const dispatched = events.filter(event => event.type === "jev_science_dispatch_started" && event.send_id === sendId);
  return { preparedSha256: prepared[0].payload_sha256, dispatched: dispatched.length };
}

// ------------------------------------------------------------------ JEV loop area (copied from jev-loop-flow.cjs)
const lp = page => page.locator('#mw-app-panel-ligand [data-testid="jev-loop-panel"][data-branch="ligand"]');
const lpt = (page, id) => lp(page).locator(`[data-testid="${id}"]`);
async function openLoopArea(page) {
  // The tab mounts its areas afresh when it is selected (their input lists are read on mount): leave it first when it
  // is the shown tab, so a candidate set made since the last mount is listed.
  if (await tabButton(page, TAB.ligand).getAttribute("aria-selected") === "true") await selectTab(page, TAB.structure);
  await selectTab(page, TAB.ligand);
  await lp(page).waitFor({ timeout: 30000 });
  await waitFor(page, async () => {
    const state = await lp(page).getAttribute("data-jev-loop-state");
    if (!["ready", "empty"].includes(state)) return null;
    if (await lp(page).locator('[data-jev-loop-area="status"]').getAttribute("data-state") !== "ready") return null;
    if (await lp(page).locator('[data-jev-loop-field="pool"] [aria-busy="true"]').count()) return null;
    if (await lp(page).locator('[data-jev-loop-field="setup"] [aria-busy="true"]').count()) return null;
    return true;
  }, "ligand loop area ready", 60000);
}
async function loopSetConsent(page, run, on, log) {
  if ((await lpt(page, "jev-loop-consent-label").getAttribute("data-consent") === "on") === on) return null;
  const since = Date.now();
  await lpt(page, "jev-loop-consent").click();
  const entry = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev/consent`, "consent answer", 30000);
  assert.equal(entry.status, 200, JSON.stringify(entry.json));
  assert.equal(entry.json.enabled, on);
  await waitFor(page, async () => await lpt(page, "jev-loop-consent-label").getAttribute("data-consent") === (on ? "on" : "off")
    ? true : null, "consent shown", 15000);
  return entry.json;
}
async function loopRowKeys(page) {
  return lp(page).locator("tr[data-jev-loop-candidate-row]").evaluateAll(items => items.map(item => ({
    key: item.getAttribute("data-jev-loop-candidate-row"), checked: item.getAttribute("data-checked") === "true" })));
}
async function loopChooseSource(page, handle, count) {
  const radio = lp(page).locator(`input[data-testid="jev-loop-source"]${attr("data-jev-loop-source", handle)}`);
  await radio.waitFor({ timeout: 30000 });
  if (!(await radio.isChecked())) await radio.check();
  return waitFor(page, async () => {
    if (await lpt(page, "jev-loop-candidates").count() !== 1) return null;
    const rows = await loopRowKeys(page);
    return rows.length === count ? rows : null;
  }, "loop candidate rows", 30000);
}
const loopBox = (page, key) => lp(page).locator(`input[data-testid="jev-loop-candidate"]${attr("data-jev-loop-candidate", key)}`);
async function loopPool(page, keys) {
  for (const row of await loopRowKeys(page)) if (row.checked && !keys.includes(row.key)) await loopBox(page, row.key).uncheck();
  for (const key of keys) if (!(await loopBox(page, key).isChecked())) await loopBox(page, key).check();
}
async function loopFill(page, id, value) { await lpt(page, id).fill(String(value)); }
async function loopSetup(page, setup, docking) {
  await lpt(page, "jev-loop-parent-sdf").waitFor({ timeout: 30000 });
  await waitFor(page, async () => await lpt(page, "jev-loop-parent-sdf").locator(`option${attr("value", setup.parent)}`).count()
    ? true : null, "parent SDF listed", 30000);
  await lpt(page, "jev-loop-parent-sdf").selectOption(setup.parent);
  await lpt(page, "jev-loop-receptor").selectOption(setup.receptor);
  await lpt(page, "jev-loop-model").waitFor({ timeout: 30000 });
  await lpt(page, "jev-loop-model").selectOption(docking.model);
  await lpt(page, "jev-loop-instances").waitFor({ timeout: 30000 });
  await lp(page).locator('[data-testid="jev-loop-instances"] label[data-jev-loop-instance="none"] input').check();
  await lpt(page, "jev-loop-connectivity").locator("label").filter({ hasText: "PDB CONECT" }).locator("input").check();
  await lp(page).locator('label[data-jev-loop-box="manual"] input').check();
  for (const [i, axis] of ["x", "y", "z"].entries()) {
    await loopFill(page, `jev-loop-center-${axis}`, docking.center[i]);
    await loopFill(page, `jev-loop-size-${axis}`, docking.size[i]);
  }
  await loopFill(page, "jev-loop-docking-seed", docking.seed);
  await loopFill(page, "jev-loop-exhaustiveness", docking.exhaustiveness);
  await loopFill(page, "jev-loop-num-modes", docking.numModes);
  await loopFill(page, "jev-loop-energy-range", docking.energyRange);
  for (const key of ACK_KEYS) await lp(page).locator(`label[data-jev-loop-ack="${key}"] input`).check();
}
async function loopRecordAttrs(page) {
  const node = lpt(page, "jev-loop-record");
  if (!(await node.count())) return null;
  return { loopId: await node.getAttribute("data-loop-id"), status: await node.getAttribute("data-status"),
    action: await node.getAttribute("data-action"), phase: await node.getAttribute("data-phase"),
    iteration: await node.getAttribute("data-iteration") };
}
async function loopRecordWhen(page, ok, label, timeout = 60000) {
  return waitFor(page, async () => { const value = await loopRecordAttrs(page); return value && ok(value) ? value : null; },
    label, timeout);
}
const readLoop = (page, run, loopId) => readApi(page, `/runs/${run}/jev_loops/${enc(loopId)}`);
async function loopBuild(page, run, log) {
  const since = Date.now();
  await waitFor(page, async () => await lpt(page, "jev-loop-build").isEnabled() ? true : null, "build enabled", 15000);
  await lpt(page, "jev-loop-build").click();
  const command = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/commands` &&
    item.request?.tool === "build_jev_loop_projection", "projection command", 120000);
  assert.equal(command.status, 200, JSON.stringify(command.json).slice(0, 600));
  assert.equal(command.json.ok, true, JSON.stringify(command.json).slice(0, 600));
  const handle = command.json.handle.handle;
  const previewed = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev/preview` &&
    item.request?.projection === handle, "preview answer", 60000);
  assert.equal(previewed.status, 200);
  await lp(page).locator(`[data-testid="jev-loop-preview"]${attr("data-projection-handle", handle)}`).waitFor({ timeout: 30000 });
  return { handle, summary: command.json.handle.summary, preview: previewed.json };
}
async function loopPreviewShown(page) {
  const box = lpt(page, "jev-loop-preview");
  return { handle: await box.getAttribute("data-projection-handle"), sha256: await box.getAttribute("data-body-sha256"),
    bytes: Number(await box.getAttribute("data-body-bytes")),
    blocked: await lpt(page, "jev-loop-preview-blocked").locator("li[data-block-reason]").evaluateAll(items =>
      items.map(item => ({ code: item.getAttribute("data-block-reason"), text: item.textContent.trim() }))),
    loopBlocks: await lpt(page, "jev-loop-preview-blocked").locator("li[data-loop-block]").evaluateAll(items =>
      items.map(item => ({ code: item.getAttribute("data-loop-block"), text: item.textContent.trim() }))),
    aliases: await lpt(page, "jev-loop-alias-table").locator("tr[data-alias]").evaluateAll(items =>
      items.map(item => ({ alias: item.getAttribute("data-alias"), cells: [...item.cells].map(cell => cell.textContent.trim()) }))),
    question: clean(await lpt(page, "jev-loop-preview-question").textContent()),
    order: clean(await lpt(page, "jev-loop-preview-order").textContent()),
    body: await lpt(page, "jev-loop-preview-body").textContent() };
}
async function loopPreviewWhen(page, handle, ok, label) {
  return waitFor(page, async () => {
    if (!(await lpt(page, "jev-loop-preview").count())) return null;
    const shown = await loopPreviewShown(page);
    return shown.handle === handle && ok(shown) ? shown : null;
  }, label, 30000);
}
/** Body identity and the order oracle (copied from jev-loop-flow.cjs previewMatches, ligand branch). */
function loopPreviewMatches({ shown, built, stored, record, iteration, ordinal, runId }) {
  const bytes = Buffer.from(shown.body, "utf8");
  assert.equal(shown.body, built.preview.body, "<pre> text differs from the server preview body");
  assert.equal(sha(bytes), built.preview.body_sha256);
  assert.equal(bytes.length, built.preview.body_bytes);
  assert.equal(shown.sha256, built.preview.body_sha256);
  assert.equal(shown.bytes, built.preview.body_bytes);
  assert.equal(stored.schema, "jev_loop_projection@1");
  assert.equal(stored.body_sha256, built.preview.body_sha256, "stored projection body hash");
  assert.ok(built.preview.body_bytes <= 65536);
  assert.deepEqual(stored.loop, { loop_id: record.loop_id, iteration, send_ordinal: ordinal });
  assert.deepEqual(stored.order, { algorithm: "sha256_order_v1", loop_seed: record.loop_seed, iteration, send_ordinal: ordinal });
  const oracle = m25.oracleOrder(record, iteration, ordinal);
  assert.deepEqual(stored.selection, oracle.order.map(row => ({ alias: row.alias, ref: row.ref, state: row.state })),
    "stored selection differs from the independent sha256_order_v1 order");
  const body = JSON.parse(shown.body);
  assert.deepEqual(Object.keys(body).sort(), ["model", "provider", "questions", "state"]);
  assert.equal(body.model, REQUEST_MODEL);
  assert.deepEqual(body.provider, PROVIDER);
  assert.deepEqual(body.state, stored.wire, "body state differs from the stored wire");
  assert.equal(body.state.schema, "jev_loop_ligand_candidates@1");
  assert.equal(body.state.goal, record.goal);
  assert.equal(body.state.task, "choose_one_candidate");
  assert.ok(Object.keys(body.state).every(key => WIRE_TOP_LIGAND.includes(key)), Object.keys(body.state).join(","));
  assert.deepEqual(body.state.candidates.map(item => item.alias), oracle.order.map(row => row.alias));
  assert.deepEqual(body.state.computed, oracle.computed, "computed rows differ from the oracle (goal shape, raw score)");
  assert.equal(body.state.values_note, LIGAND_VALUES_NOTE + (record.goal === "exploit" ? LIGAND_EXPLOIT_SUFFIX : ""));
  const question = body.questions.candidate_choice;
  assert.equal(question.instructions, m25.INSTRUCTIONS[`ligand|${record.goal}`], "instructions are not the spec 4.5 text");
  assert.deepEqual(Object.keys(question.criteria), oracle.criteria, "criteria are not the not-yet-computed aliases in order");
  assert.equal(shown.question, m25.INSTRUCTIONS[`ligand|${record.goal}`]);
  for (const forbidden of ["obj://", runId, record.loop_id, "/Users/", "handle", "loop_seed"])
    assert.ok(!shown.body.includes(forbidden), `body carries ${forbidden}`);
  assert.ok(!/c_[0-9a-f]{16}/.test(shown.body), "body carries a candidate id");
  return { bodySha256: built.preview.body_sha256, bodyBytes: built.preview.body_bytes, ordinal,
    order: oracle.order.map(row => `${row.alias}=${row.ref}:${row.state}`), criteria: oracle.criteria,
    computed: oracle.computed, reservation: built.preview.reservation };
}
async function loopConfirmAndSend(page, run, controlDir, script, log) {
  if (controlDir) writeScript(controlDir, script);
  if (!(await lpt(page, "jev-loop-confirm").isChecked())) await lpt(page, "jev-loop-confirm").check();
  await waitFor(page, async () => await lpt(page, "jev-loop-send").isEnabled() ? true : null, "send enabled", 15000);
  const callsBefore = controlDir ? fixtureCalls(controlDir).length : 0;
  const since = Date.now();
  await lpt(page, "jev-loop-send").click();
  const entry = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev/sends`, "send answer", 180000);
  assert.equal(entry.status, 200, JSON.stringify(entry.json));
  const record = entry.json;
  await lp(page).locator(`[data-testid="jev-loop-send-record"]${attr("data-send-id", record.send_id)}`).waitFor({ timeout: 30000 });
  return { request: entry.request, record, calls: controlDir ? fixtureCalls(controlDir).slice(callsBefore) : null };
}
/** The send's audit `prepared` body = the preview body; one dispatch; with the fixture server the transport bytes
 * (copied from jev-loop-flow.cjs serverBytes). */
function loopServerBytes(runsDir, run, sendId, shownBody, bodySha, calls) {
  const prepared = preparedMatches(runsDir, run, sendId, shownBody, bodySha);
  assert.equal(prepared.dispatched, 1);
  if (calls !== null) {
    assert.equal(calls.length, 1, "fixture transport calls of this send");
    assert.equal(calls[0].bodySha256, bodySha, "transport bytes differ from the preview");
    assert.equal(calls[0].bodyBytes, Buffer.byteLength(shownBody, "utf8"));
    assert.equal(calls[0].authorizationIsSentinel, true);
  }
  return { previewSha256: bodySha, preparedSha256: prepared.preparedSha256, transportSha256: calls?.[0]?.bodySha256 ?? null,
    dispatched: prepared.dispatched, gate: calls === null ? "product" : "fixture" };
}
async function loopReadCard(page, sendId) {
  const card = lp(page).locator(`[data-testid="jev-loop-choice-card"]${attr("data-send-id", sendId)}`);
  const line = lp(page).locator(`[data-testid="jev-loop-choice-confirming"]${attr("data-send-id", sendId)}`);
  const first = await waitFor(page, async () => {
    if (await card.count()) return { confirming: null };
    if (await line.count()) return { confirming: { text: clean(await line.textContent()) } };
    return null;
  }, "proposal card or confirming line", 30000);
  await card.waitFor({ timeout: 60000 });
  const details = card.locator('[data-testid="jev-loop-choice-probabilities"]');
  const foldedBefore = !(await details.evaluate(node => node.open));
  if (foldedBefore) await details.locator("summary").click();
  return { foldedBefore, confirming: first.confirming,
    proposalHandle: await card.getAttribute("data-proposal-handle"), chosen: await card.getAttribute("data-chosen-alias"),
    selectionAttr: await card.getAttribute("data-selection"),
    title: clean(await card.locator(".mw-jev-title").first().textContent()),
    position: clean(await card.locator('[data-testid="jev-loop-choice-position"]').textContent()),
    local: clean(await card.locator('[data-testid="jev-loop-choice-local"]').textContent()),
    model: clean(await card.locator('[data-testid="jev-loop-choice-model"]').textContent()),
    limitations: await card.locator('[data-testid="jev-loop-choice-limitations"] [data-limitation]').evaluateAll(items =>
      items.map(item => item.textContent)),
    comparison: await card.evaluate(node => ({
      graphics: node.querySelectorAll("progress, meter, svg, canvas").length, ariaSort: node.querySelectorAll("[aria-sort]").length,
      attrs: [...node.querySelectorAll("*")].flatMap(item => [...item.attributes].map(a => a.name))
        .filter(name => /rank|best|score|recommend|winner/i.test(name)).length })) };
}
function loopCardMatches(shown, record, choice, projection, goal) {
  assert.equal(choice.schema, "jev_loop_choice@1");
  assert.equal(choice.label, "JEV 판정(모델 선택)");
  assert.equal(choice.scientific_result, false);
  assert.equal(shown.title, "JEV 판정(모델 선택)");
  assert.equal(shown.proposalHandle, record.choice_handle);
  assert.equal(shown.chosen, choice.answer.choice_alias);
  const criteria = projection.selection.filter(item => item.state === "pending").map(item => item.alias);
  assert.equal(choice.answer.list_position, criteria.indexOf(choice.answer.choice_alias) + 1, "list position ≠ criteria place");
  assert.equal(choice.answer.list_size, criteria.length);
  assert.equal(shown.position, `${choice.answer.list_position}/${choice.answer.list_size}`);
  assert.equal(shown.local, choice.answer.local_display.smiles);
  assert.equal(shown.model, choice.served_model);
  assert.equal(shown.foldedBefore, true, "the per-candidate values were not folded when the card appeared");
  assert.deepEqual(shown.limitations, m25.expectedLimitations("ligand", goal, { late: false }));
  assert.equal(shown.selectionAttr, "true");
  assert.deepEqual(shown.comparison, { graphics: 0, ariaSort: 0, attrs: 0 });
  if (shown.confirming !== null) assert.ok(shown.confirming.text.endsWith(CONFIRMING_TEXT), shown.confirming.text);
  return { alias: shown.chosen, position: shown.position, ref: choice.answer.local_ref.candidate_id };
}
async function loopPressCompute(page, run, loopId, log) {
  if (!(await lpt(page, "jev-loop-compute-confirm").isChecked())) await lpt(page, "jev-loop-compute-confirm").check();
  await waitFor(page, async () => await lpt(page, "jev-loop-compute-proposal").isEnabled() ? true : null, "compute enabled", 30000);
  const since = Date.now();
  await lpt(page, "jev-loop-compute-proposal").click();
  return waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev_loops/${loopId}/compute`, "compute answer", 900000);
}
async function loopCandidateTable(page) {
  const table = lpt(page, "jev-loop-candidate-table");
  return { headers: await table.locator("thead th").evaluateAll(items => items.map(item => item.textContent.trim())),
    rows: await table.locator("tbody tr").evaluateAll(items => items.map(item => ({ ref: item.getAttribute("data-ref"),
      state: item.getAttribute("data-state"), hasScore: item.getAttribute("data-has-score") === "true",
      score: item.querySelector("[data-score-cell]")?.textContent.trim() ?? null,
      cells: [...item.cells].map(cell => cell.textContent.trim()) }))) };
}
function loopRowsMatch(table, record) {
  assert.equal(table.rows.length, record.candidates.length);
  for (const row of table.rows) {
    const item = record.candidates.find(candidate => String(candidate.ref) === row.ref);
    assert.ok(item, `row ${row.ref} not in the record`);
    assert.equal(row.state, item.state);
    assert.equal(row.hasScore, item.state === "scored");
    if (item.state === "scored") assert.equal(row.score, halfUp(item.score_kcal_mol, 1));
    else { assert.equal(item.score_kcal_mol, null); assert.ok(row.score.startsWith(NULL_TEXT), row.score); }
  }
}
async function loopEnd(page, run, loopId, log) {
  const since = Date.now();
  await lpt(page, "jev-loop-end").click();
  const answer = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev_loops/${loopId}/end`, "end", 120000);
  const result = await waitFor(page, async () => (await lpt(page, "jev-loop-ended").count())
    ? lpt(page, "jev-loop-ended").getAttribute("data-result-handle") : null, "ended", 30000);
  return { answer, result, record: await readLoop(page, run, loopId),
    limitations: await lpt(page, "jev-loop-limitations").locator("li").evaluateAll(items => items.map(item => item.textContent)) };
}
async function loopReport(page, run, log) {
  const since = Date.now();
  await lpt(page, "jev-loop-report").click();
  const entry = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/method_reports`, "report answer", 120000);
  if (entry.status === 201)
    await lp(page).locator(`[data-testid="jev-loop-report-done"]${attr("data-report-handle", entry.json.handle)}`).waitFor({ timeout: 60000 });
  return entry;
}

// ------------------------------------------------------------------ report library (copied from tabs-flow.cjs / ligand-flow.cjs)
const library = page => page.getByRole("region", { name: "보고서 보관함", exact: true });
async function libraryOpen(page, handle) {
  await selectTab(page, TAB.knowledge);
  const reports = library(page).getByRole("region", { name: "저장된 보고서", exact: true });
  const content = library(page).getByRole("region", { name: "선택한 항목 내용", exact: true });
  const row = reports.locator("li button").filter({ hasText: handle });
  await row.waitFor({ timeout: 30000 });
  const kind = clean(await row.locator(".mw-library-kind").textContent());
  await row.click();
  const pre = content.getByLabel(`저장된 보고서 ${handle}`, { exact: true });
  await pre.waitFor({ timeout: 30000 });
  return { kind, text: await pre.textContent(), content };
}
async function libraryRows(page) {
  const reports = library(page).getByRole("region", { name: "저장된 보고서", exact: true });
  return reports.locator("li button").evaluateAll(items => items.map(item => ({
    codes: [...item.querySelectorAll("code")].map(code => code.textContent),
    kind: item.querySelector(".mw-library-kind")?.textContent ?? null })));
}

// ------------------------------------------------------------------ the parts
/** The candidates of the set that already have a stored M18 result of this branch's docking values (the reuse rule:
 * same receptor, parent, box and parameters; read from the stored objects, not from a product reuse list). */
function dockedCandidates(runsDir, run, reference) {
  const docked = new Set();
  for (const { value } of dockingResults(runsDir, run)) {
    if (value.inputs?.ligand?.source !== "candidate" || value.inputs.mode !== "free") continue;
    if (JSON.stringify(value.parameters) !== JSON.stringify(reference.parameters)) continue;
    if (JSON.stringify(value.box) !== JSON.stringify(reference.box)) continue;
    if (value.inputs.receptor?.sha256 !== reference.inputs.receptor.sha256) continue;
    docked.add(value.inputs.ligand.candidate_id);
  }
  return docked;
}
function dockingResultOf(runsDir, run, reference, candidate) {
  return dockingResults(runsDir, run).find(({ value }) => value.inputs?.ligand?.source === "candidate" &&
    value.inputs.ligand.candidate_id === candidate && value.inputs.mode === "free" &&
    JSON.stringify(value.parameters) === JSON.stringify(reference.parameters) &&
    JSON.stringify(value.box) === JSON.stringify(reference.box)) ?? null;
}

async function flowB1(ctx) {
  const { page, app, artifacts, plan, rec, evidence, units, input } = ctx;
  const S = ctx.state;
  await rec.part("B1", [], async () => {
    S.run = await rec.step("B1-01", "구조 분석: click 새 run", () => newRun(page), async run => { assert.match(run, /^run_/); return run; });
    evidence.run = S.run;
    units.setRun(S.run);
    const run = S.run;
    const prepared = await rec.step("B1-02", "Click 화학 상호작용 작업 열기; choose the prepared receptor PDB and the pose SDF " +
      "(file chooser), model 1, SDF record 0, ligand instance Z 901 LQA, the four acknowledgements and the terminal " +
      "extensions, pH note; 준비 조건 미리보기 → 화학 구조 준비 작업 저장 → 준비 작업 시작 with the run's first expensive " +
      "approval (이 실제 작업 승인): the real ProLIF preparation finishes and uses exactly one unit", async () => {
      await page.getByRole("button", { name: "화학 상호작용 작업 열기" }).waitFor({ timeout: 30000 });
      await clickButton(page, "화학 상호작용 작업 열기");
      await page.getByText("준비 입력과 실제 화학 상호작용", { exact: true }).waitFor({ timeout: 30000 });
      await waitChemical(page, state => state.runId === run, 30000);
      const files = { receptor: await chooseChemicalFile(page, "준비된 수용체 PDB/mmCIF", plan.inputs.receptor.path, run),
        sdf: await chooseChemicalFile(page, "명시적 H가 있는 3D 리간드 V2000 SDF", plan.inputs.pose.path, run) };
      const modelSelect = nestedSelect(page, "수용체 model");
      await modelSelect.locator(`option[value="${plan.chemical.model}"]`).waitFor({ state: "attached", timeout: 30000 });
      await modelSelect.selectOption(String(plan.chemical.model));
      const recordSelect = nestedSelect(page, "SDF 기록");
      await page.waitForFunction(() => [...document.querySelectorAll("label")].some(label => label.textContent?.includes("SDF 기록") &&
        label.querySelectorAll("option").length > 1), null, { timeout: 30000 });
      const records = await recordSelect.locator("option").evaluateAll(items => items.map(item => Number(item.value)));
      await recordSelect.selectOption(String(plan.chemical.record));
      const ligand = plan.chemical.ligand;
      await page.getByLabel("리간드 chain auth", { exact: true }).fill(ligand.chain_auth);
      await page.getByLabel("seq auth", { exact: true }).fill(String(ligand.seq_auth));
      await page.getByLabel("resname", { exact: true }).fill(ligand.resname);
      for (const label of ["공급된 수용체 결합 그래프가 완전함", "공급된 수소가 완전함", "공급된 protonation/tautomer 그대로 사용",
        "수용체 bond order/charge 추론 동의"]) await page.getByLabel(label, { exact: true }).check();
      const previewed = page.waitForResponse(response => response.request().method() === "POST" &&
        response.url().includes(`/api/runs/${run}/chemical/preview`));
      await clickButton(page, "준비 조건 미리보기");
      const preview = await (await previewed).json();
      const terminalChecks = page.locator("label").filter({ hasText: "말단 확장 승인:" }).locator('input[type="checkbox"]');
      await waitFor(page, async () => await terminalChecks.count() === preview.terminal_extensions.length ? true : null,
        "terminal extension checks", 30000);
      for (let i = 0; i < preview.terminal_extensions.length; i++) await terminalChecks.nth(i).check();
      await page.getByLabel("준비 설명 (검증되지 않은 로컬 주석)").fill("Prepared local public tutorial input; supplied protonation state unverified");
      await page.getByLabel("pH 메모 (실험 검증 아님)").fill("7.4");
      let prepareRequest = null;
      const listen = request => {
        if (request.method() === "POST" && request.url().includes(`/api/runs/${run}/jobs`) &&
            request.postDataJSON()?.protocol_id === "prolif_prepare_v1") prepareRequest = request.postDataJSON();
      };
      page.on("request", listen);
      await clickButton(page, "준비 조건 미리보기");
      await page.getByText("계산 준비 가능", { exact: false }).waitFor({ timeout: 30000 });
      await clickButton(page, "화학 구조 준비 작업 저장");
      await page.getByRole("button", { name: "준비 작업 시작" }).waitFor({ timeout: 30000 });
      await submittedJob(page, "prepare");
      page.off("request", listen);
      const entry = await units.before("B1-prepare");
      const started = await chemicalStart(page, "prepare");
      await units.after(entry);
      const state = await waitChemical(page, value => value.sourceHandle && value.catalogReady &&
        value.native?.sourceHandle === value.sourceHandle, 60000);
      return { files, records, prepareRequest, started, state, entry };
    }, async value => {
      assert.ok(value.records.includes(plan.chemical.record) && value.records.length === plan.poseRecords,
        `SDF records offered ${value.records.length}, the file has ${plan.poseRecords}`);
      assert.deepEqual(value.prepareRequest?.args?.ligand_instance, plan.chemical.ligand);
      assert.equal(value.prepareRequest.args.sdf_record_index, plan.chemical.record);
      assert.equal(value.started.approvalSeen, true, "the run's first expensive call did not ask for approval");
      assert.equal(value.files.receptor.sha256, plan.inputs.receptor.sha256);
      assert.equal(value.files.sdf.sha256, plan.inputs.pose.sha256);
      return { files: value.files, approval: value.started.approvalSeen, units: value.entry.usedUnits, job: value.started.id };
    });
    const detected = await rec.step("B1-03", "Rail models: 저장된 실제 준비 선택 → 상호작용 계산 작업 저장 → 상호작용 작업 " +
      "시작 (no second approval): the real ProLIF detection finishes with rows and uses exactly one unit", async () => {
      await rail(page, "models");
      await page.getByText("저장된 실제 준비 선택").click();
      await clickButton(page, "상호작용 계산 작업 저장");
      await submittedJob(page, "detect");
      const entry = await units.before("B1-detect");
      const started = await chemicalStart(page, "detect");
      await units.after(entry);
      const state = await waitChemical(page, value => value.resultHandle && value.catalogReady &&
        value.native?.sourceHandle === value.sourceHandle, 60000);
      return { started, state, entry };
    }, async value => {
      assert.equal(value.started.approvalSeen, false, "the run's approval was asked again");
      assert.ok(value.state.resultTotal > 0, "the public prepared example produced no interaction rows");
      return { result: value.state.resultHandle, total: value.state.resultTotal, units: value.entry.usedUnits };
    });
    S.chemicalResult = detected.result;
    await rec.step("B1-04", "Read every stored interaction row: each role atom is an atom of the input files " +
      "(receptor: residue fields, atom name, element and coordinates of the PDB; ligand: element and coordinates of SDF " +
      "record 0) and each D···A distance (and D–H···A angle when stored) equals the one recomputed from the input " +
      "coordinates; the first page on screen lists the same rows", () => chemicalRows(page, run, S.chemicalResult), async stored => {
      let rolesUnmatched = 0, distanceMismatches = 0, angleMismatches = 0;
      for (const row of stored) {
        const input = {};
        for (const [role, ref] of Object.entries(row.roles)) {
          const xyz = row.role_coordinates_A?.[role] ?? row.engine_role_coordinates_A[role];
          const found = inputAtomOf(plan, ref, xyz);
          if (!found) { rolesUnmatched++; continue; }
          input[role] = found.atom.xyz;
        }
        const [a, b] = row.distance_roles;
        if (input[a] && input[b] && Math.abs(separation(input[a], input[b]) - row.distance_A) > 0.003) distanceMismatches++;
        if (Math.abs(separation(row.engine_role_coordinates_A[a], row.engine_role_coordinates_A[b]) - row.distance_A) > 1e-5)
          distanceMismatches++;
        if (row.DHA_angle_deg != null) {
          const c = row.engine_role_coordinates_A;
          if (Math.abs(angleAt(c.donor, c.hydrogen, c.acceptor) - row.DHA_angle_deg) > 1e-5) angleMismatches++;
          if (input.donor && input.hydrogen && input.acceptor &&
              Math.abs(angleAt(input.donor, input.hydrogen, input.acceptor) - row.DHA_angle_deg) > 0.5) angleMismatches++;
        }
      }
      const region = page.getByRole("region", { name: "화학 상호작용 행" });
      await region.locator("button.mw-chemical-row").first().waitFor({ state: "visible", timeout: 30000 });
      const shown = await page.locator(".mw-chemical-row").allInnerTexts();
      for (const [i, row] of stored.slice(0, shown.length).entries()) assert.ok(shown[i].includes(row.row_id), `screen row ${i}`);
      S.chemicalRows = stored;
      assert.equal(rolesUnmatched, 0, "a stored role atom is not an atom of the input files");
      assert.equal(distanceMismatches, 0, "a stored distance differs from the recomputed one");
      assert.equal(angleMismatches, 0, "a stored angle differs from the recomputed one");
      evidence.observed.B1 = { rows: stored.length, rolesUnmatched, distanceMismatches, angleMismatches,
        categories: [...new Set(stored.map(row => row.category))].sort(), screenRows: shown.length,
        units: evidence.units.filter(item => item.label.startsWith("B1-")).map(item => item.usedUnits) };
      return evidence.observed.B1;
    });
    await rec.step("B1-05", "Click the first interaction row: the viewer focuses exactly that row's role atoms and shows " +
      "the stored distance (and angle) (adapted from chemical-flow.cjs focusFirstRow)", async () => {
      const first = page.getByRole("region", { name: "화학 상호작용 행" }).locator("button.mw-chemical-row").first();
      await first.click();
      const rowId = (await chemical(page)).selectedRowId;
      const after = await waitChemical(page, state => state.native?.chemicalFocus?.rowId === state.selectedRowId &&
        state.native?.chemicalAnnotation?.rowId === state.selectedRowId, 30000);
      return { rowId, after };
    }, async value => {
      const exact = S.chemicalRows.find(row => row.row_id === value.rowId);
      assert.ok(exact, "the focused row is not stored");
      assert.deepEqual(value.after.native.chemicalFocus.atoms.map(item => atomIdentity(item.ref)).sort(),
        Object.values(exact.roles).map(atomIdentity).sort(), "focused atoms differ from the stored row roles");
      assert.ok(Math.abs(value.after.native.chemicalAnnotation.distanceNative_A - exact.distance_A) <= 0.005);
      if (exact.DHA_angle_deg != null) assert.ok(Math.abs(value.after.native.chemicalAnnotation.angleNative_deg - exact.DHA_angle_deg) <= 0.1);
      else assert.equal(value.after.native.chemicalAnnotation.angleNative_deg, null);
      return { rowId: value.rowId, category: exact.category };
    });
    await rec.step("B1-06", "Click 화학 보고서 저장: saved (201); Markdown and 정확한 JSON 다운로드 equal the backend bytes; " +
      "every row claim (distance, angle) equals the stored row", async () => {
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
      await clickButton(page, "화학 보고서 저장");
      const response = await posted;
      const body = await response.json();
      noteReport(evidence, "B1", "chemical_interactions", response.status(), body.handle);
      const reportSelect = nestedSelect(page, "저장된 보고서");
      await waitFor(page, async () => (await reportSelect.inputValue()) === body.handle ? true : null, "report selected", 30000);
      const markdown = await downloadByClick(app, page.getByRole("link", { name: "Markdown 다운로드" }));
      const json = await downloadByClick(app, page.getByRole("link", { name: "정확한 JSON 다운로드" }));
      const selected = await readApi(page, `/runs/${run}/reports/selected?handle=${enc(body.handle)}`);
      await keepTabText(page, evidence, artifacts, "structure@B1", "structure");
      return { status: response.status(), handle: body.handle, markdown, json, selected };
    }, async value => {
      assert.equal(value.status, 201);
      const exactMd = await readBytes(page, `/runs/${run}/reports/download?handle=${enc(value.handle)}&format=markdown`);
      const exactJson = await readBytes(page, `/runs/${run}/reports/download?handle=${enc(value.handle)}&format=json`);
      assert.equal(value.markdown.sha256, sha(exactMd));
      assert.equal(value.json.sha256, sha(exactJson));
      assert.equal(value.selected.manifest.analysis_type, "chemical_interactions");
      assert.equal(value.selected.manifest.result_handle, S.chemicalResult);
      const rows = S.chemicalRows;
      const byId = Object.fromEntries(rows.map(row => [row.row_id, row]));
      let claims = 0;
      for (const claim of value.selected.manifest.claims ?? []) {
        if (claim.field_path === "total") { assert.equal(claim.exact_value, rows.length); continue; }
        const field = claim.field_path.split(".").at(-1);
        assert.equal(claim.exact_value, byId[claim.row_id][field], `claim ${claim.field_path}`);
        claims++;
      }
      assert.ok(claims >= rows.length, "fewer row claims than rows");
      return { handle: value.handle, claims, markdownSha256: value.markdown.sha256 };
    });
  });
}

async function flowB2(ctx, name) {
  const { page, plan, rec, evidence, units, artifacts } = ctx;
  const S = ctx.state;
  await rec.part(name, [], async () => {
    if (!S.run) {
      S.run = await rec.step(`${name}-00`, "구조 분석: click 새 run", () => newRun(page), async run => { assert.match(run, /^run_/); return run; });
      evidence.run = S.run;
      units.setRun(S.run);
    }
    const run = S.run;
    const imported = await rec.step(`${name}-01`, "리간드 설계·탐색: choose the public-derived parent SDF, the labeled synthetic " +
      "block SDF and SMILES files (file chooser), type rules 2 and 3 of the synthetic rule file (two lines), click 가져오기",
    async () => {
      await openLigandTab(page);
      await chooseLigandFile(page, "parent", plan.inputs.parent.path);
      await chooseLigandFile(page, "blockSdf", plan.inputs.blocksSdf.path);
      await chooseLigandFile(page, "blockSmiles", plan.inputs.blocksSmiles.path);
      await lt(page, "ligand-rules").click();
      await lt(page, "ligand-rules").fill(plan.b2.rules.join("\n"));
      await lt(page, "ligand-import").click();
      await waitFor(page, async () => await ligandArea(page, "inputs") === "ready" ? true : null, "inputs imported", 60000);
      return ligandPanel(page).locator("[data-ligand-import]").evaluateAll(items => Object.fromEntries(items.map(item =>
        [item.getAttribute("data-ligand-import"), item.getAttribute("data-import-handle")])));
    }, async handles => {
      assert.deepEqual(Object.keys(handles).sort(), ["building_blocks_sdf", "building_blocks_smiles", "ligand_sdf"]);
      for (const [kind, handle] of Object.entries(handles)) {
        const meta = await readApi(page, `/runs/${run}/objects/meta?handle=${enc(handle)}`);
        const want = { ligand_sdf: plan.inputs.parent, building_blocks_sdf: plan.inputs.blocksSdf,
          building_blocks_smiles: plan.inputs.blocksSmiles }[kind];
        assert.equal(meta.summary?.sha256, want.sha256, `${kind} bytes differ from the input file`);
      }
      return handles;
    });
    S.parentImport = imported.ligand_sdf;
    const inspected = await rec.step(`${name}-02`, "Click 점검 시작 (approval if asked) → 작업 시작: the real RDKit inspection " +
      "finishes with one unit; both typed rules are valid; the block libraries count the input files' records", async () => {
      const entry = await units.before("B2-inspect");
      const job = await runLigandJob(page, run, "ligand-inspect-start", "rdkit_inspect_v1");
      await units.after(entry);
      const radio = ligandPanel(page).locator(`label${attr("data-ligand-inspection", job.handle)} input[type="radio"]`);
      await radio.waitFor({ timeout: 30000 });
      await radio.check();
      await ligandPanel(page).locator(`[data-testid="ligand-inspection"]${attr("data-ligand-inspection-handle", job.handle)}`)
        .waitFor({ timeout: 30000 });
      const libraries = await lt(page, "ligand-blocks").locator("[data-block-kind]").evaluateAll(items => items.map(item => ({
        kind: item.getAttribute("data-block-kind"), text: item.textContent.replace(/\s+/g, " ").trim() })));
      const rules = await lt(page, "ligand-rules-status").locator("li[data-rule-id]").evaluateAll(items => items.map(item => ({
        id: item.getAttribute("data-rule-id"), status: item.getAttribute("data-rule-status") })));
      return { job, entry, libraries, rules };
    }, async value => {
      assert.equal(value.job.job.status, "done", JSON.stringify(value.job.job.failure));
      assert.deepEqual(value.rules, plan.b2.rules.map((_, i) => ({ id: `user_${i + 1}`, status: "valid" })));
      const records = Object.fromEntries(value.libraries.map(item => [item.kind, Number(/레코드 (\d+)개 중/.exec(item.text)?.[1])]));
      evidence.observed[name] = { ...(evidence.observed[name] ?? {}), sdfBlocksSeen: records.building_blocks_sdf,
        smilesBlocksSeen: records.building_blocks_smiles };
      assert.equal(records.building_blocks_sdf, plan.b2.sdfRecords, "SDF block records");
      assert.equal(records.building_blocks_smiles, plan.b2.smilesBlocks, "SMILES block records");
      return { inspection: value.job.handle, approved: value.job.approved, units: value.entry.usedUnits, records };
    });
    S.inspection = inspected.inspection;
    const enumerated = await rec.step(`${name}-03`, "Tick parent atom 22 (the site check passes), keep 고정 교체 on, tick " +
      "user_1 and user_2; click 후보 생성 시작: the real RDKit enumeration finishes with one unit", async () => {
      await lt(page, "ligand-atoms").locator(`input[data-serial="${plan.b2.siteAtom}"]`).check();
      for (const id of plan.b2.rules.map((_, i) => `user_${i + 1}`)) await lt(page, `ligand-rule-${id}`).check();
      await ligandPanel(page).locator('[data-testid="ligand-preview"][data-site-valid="true"][data-ligand-preview-ready="true"]')
        .waitFor({ timeout: 30000 });
      await waitFor(page, async () => await lt(page, "ligand-enumerate-start").isEnabled() ? true : null, "enumerate enabled", 30000);
      const fixed = await lt(page, "ligand-use-fixed").isChecked();
      const entry = await units.before("B2-enumerate");
      const job = await runLigandJob(page, run, "ligand-enumerate-start", "rdkit_enumerate_v1");
      await units.after(entry);
      return { job, entry, fixed };
    }, async value => {
      assert.equal(value.job.job.status, "done", JSON.stringify(value.job.job.failure));
      assert.equal(value.fixed, plan.b2.useFixed);
      assert.equal(value.job.approved, false, "the run's approval was asked again");
      return { set: value.job.handle, units: value.entry.usedUnits };
    });
    S.set = enumerated.set;
    const table = await rec.step(`${name}-04`, "Click the new candidate set: at least 5 candidates; the table equals the " +
      "server rows; ids are c_ + SHA-256(SMILES)[:16]; every property column says RDKit 추정값 and the PAINS column 구조 " +
      "경고 일치; no drug-likeness, toxicity, activity or synthesizability word outside the stored limitation sentences",
    async () => {
      const result = await rowsAfter(page, run, async () => {
        const radio = ligandPanel(page).locator(`label${attr("data-ligand-candidate-set", S.set)} input[type="radio"]`);
        await radio.waitFor({ timeout: 30000 });
        await radio.check();
      });
      const detail = await readApi(page, `/runs/${run}/ligand/candidate_sets/detail?handle=${enc(S.set)}`);
      const all = await readApi(page, `/runs/${run}/ligand/candidate_sets/rows?handle=${enc(S.set)}&offset=0&limit=100`);
      const text = await ligandPanel(page).evaluate(node => node.innerText);
      return { ...result, detail, all, text };
    }, async value => {
      const rows = value.all.rows;
      assert.ok(value.all.total <= 100, "more candidates than one read");
      assert.ok(value.all.total >= plan.b2.minCandidates, `candidates ${value.all.total} < ${plan.b2.minCandidates}`);
      assert.equal(value.detail.candidate_count, value.all.total);
      let idMismatches = 0;
      for (const row of rows) if (row.candidate.id !== candidateId(row.candidate.smiles)) idMismatches++;
      assert.equal(idMismatches, 0);
      assert.equal(value.table.rows.length, value.body.rows.length);
      value.body.rows.forEach((row, i) => {
        assert.equal(value.table.rows[i].id, row.candidate.id);
        assert.equal(value.table.rows[i].smiles, row.candidate.smiles);
        assert.equal(value.table.rows[i].pains, row.candidate.pains.matches.length);
        assert.ok(value.table.rows[i].painsText.startsWith("구조 경고 일치"), value.table.rows[i].painsText);
      });
      const propertyHeaders = value.table.headers.filter(text => text.includes("RDKit 추정값"));
      assert.equal(propertyHeaders.length, 8, `property headers ${JSON.stringify(value.table.headers)}`);
      assert.ok(value.table.headers.includes("PAINS 구조 경고 일치"));
      const exempt = new Set([...value.detail.candidate_set.limitations, FIXED_PROPERTY_NOTE]);
      const words = value.text.split("\n").map(line => line.trim()).filter(line => line && !exempt.has(line) && LIGAND_WORDS.test(line));
      assert.deepEqual(words, [], "a drug-likeness / toxicity / activity / synthesizability word on the candidate area");
      S.candidates = rows.map(row => ({ id: row.candidate.id, smiles: row.candidate.smiles, heavy: row.candidate.properties.heavy_atoms }));
      evidence.observed[name] = { ...(evidence.observed[name] ?? {}), candidates: value.all.total, idMismatches,
        origins: [...new Set(rows.flatMap(row => row.candidate.origins.map(origin => origin.rule_id)))].sort() };
      return { candidates: value.all.total, origins: evidence.observed[name].origins };
    });
    await rec.step(`${name}-05`, "Type 중원자 수 최댓값 = the median stored value and click 필터 적용: the server applies it to the " +
      "stored values (each row's pass equals heavy_atoms ≤ bound computed here); clear it", async () => {
      const values = S.candidates.map(item => item.heavy).sort((a, b) => a - b);
      const bound = values[Math.floor((values.length - 1) / 2)];
      await fillLigandFilter(page, "heavy_atoms", "max", String(bound));
      const result = await rowsAfter(page, run, () => lt(page, "ligand-filter-apply").click());
      await fillLigandFilter(page, "heavy_atoms", "max", "");
      await rowsAfter(page, run, () => lt(page, "ligand-filter-apply").click());
      return { bound, ...result };
    }, async value => {
      let filterMismatches = 0;
      for (const row of value.body.rows) {
        const want = row.candidate.properties.heavy_atoms <= value.bound;
        if (row.passes_all !== want || row.filters.heavy_atoms !== want) filterMismatches++;
        const shown = value.table.rows.find(item => item.id === row.candidate.id);
        if (shown.passesAll !== String(want)) filterMismatches++;
      }
      assert.ok(new URL(`http://x/${value.query}`).searchParams.get("heavy_atoms_max") === String(value.bound), value.query);
      assert.equal(filterMismatches, 0, "the server filter differs from the stored values");
      evidence.observed[name].filterMismatches = filterMismatches;
      return { bound: value.bound, passing: value.body.passing, failing: value.body.failing, filterMismatches };
    });
    await rec.step(`${name}-06`, "Click ⑥ 보고서 만들기 for the set: saved (201), analysis_type ligand_candidates", async () => {
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
      await lt(page, "ligand-report").click();
      const response = await posted;
      const body = await response.json();
      noteReport(evidence, name, "ligand_candidates", response.status(), body.handle);
      await lt(page, "ligand-report-done").waitFor({ timeout: 30000 });
      if (name === "B2") await keepTabText(page, evidence, artifacts, "ligand@B2", "ligand");
      return { status: response.status(), handle: body.handle, manifest: body.manifest };
    }, async value => {
      assert.equal(value.status, 201);
      assert.equal(value.manifest.analysis_type, "ligand_candidates");
      assert.equal(value.manifest.result_handle, S.set);
      return { handle: value.handle };
    });
  });
}

async function flowB3(ctx, name, needs) {
  const { page, app, plan, rec, evidence, units, artifacts, input } = ctx;
  const S = ctx.state;
  const runsDir = input["runs-dir"];
  await rec.part(name, needs, async () => {
    const run = S.run;
    const capability = (await readApi(page, "/capabilities")).methods?.ligand_docking;
    assert.ok(capability?.available === true, `docking capability unavailable: ${JSON.stringify(capability)}`);
    S.capability = capability;
    S.X = S.candidates[0].id;
    const docked = await rec.step(`${name}-01`, "Docking area: choose the prepared receptor PDB (file chooser), 가져오기; 입력 " +
      "목록 다시 읽기; receptor, model 1, 없음, PDB CONECT, M17 후보 + 부모 3D SDF (the set, its first candidate, the parent " +
      "SDF), 자유 도킹, 직접 입력 box (3.41, 0.72, 11.31) 12 Å, seed 1, exhaustiveness 1, num_modes 2, energy_range 3, the " +
      "three acknowledgements; 도킹 작업 시작: the real qvina job finishes with one unit (no second approval)", async () => {
      await openLigandTab(page);
      const receptor = await ensureReceptor(page, run, plan.inputs.receptor.path);
      S.receptor = receptor.handle;
      const reread = page.waitForResponse(response => response.request().method() === "GET" &&
        new URL(response.url()).pathname === `/api/runs/${run}/docking/prerequisites`, { timeout: 30000 });
      await dt(page, "docking-prereq-refresh").click();
      const prereq = await (await reread).json();
      S.parent = prereq.candidate_sets.find(item => item.handle === S.set).parent_sdf_handles[0];
      await fillDockingForm(page, { receptor: S.receptor, set: S.set, candidate: S.X, parent: S.parent, values: plan.docking });
      await waitFor(page, async () => await dt(page, "docking-start").isEnabled() ? true : null, "start enabled", 15000);
      const entry = await units.before("B3");
      const job = await runDockingJob(page, run);
      await units.after(entry);
      return { job, entry, receptor };
    }, async value => {
      assert.equal(value.job.job.status, "done", JSON.stringify(value.job.job.failure));
      assert.equal(value.job.job.protocol_id, "qvina_dock_v1");
      assert.equal(value.job.approved, false, "the run's approval was asked again");
      assert.match(value.job.handle ?? "", /\/docking_result\//);
      return { handle: value.job.handle, job: value.job.job.job_id, units: value.entry.usedUnits, receptorImport: value.receptor.status };
    });
    S.dock = docked;
    const stored = storedObject(runsDir, run, docked.handle);
    S.dockStored = stored;
    await rec.step(`${name}-02`, "Click the result: the score is the qvina 점수 label, rows are 모드 n(엔진 출력 순서), the mode " +
      "table and limitations equal the stored result; the inputs are this plan's values and file", async () => {
      await openDockingResult(page, docked.handle);
      return { view: await dockingResultView(page), detail: await readApi(page, `/runs/${run}/docking/results/detail?handle=${enc(docked.handle)}`),
        text: await dock(page).evaluate(node => node.innerText) };
    }, async value => {
      modeTableEquals(value.view, value.detail, stored);
      assert.equal(stored.method, "qvina_free_v1");
      assert.equal(value.view.headers[1], SCORE_COLUMN);
      assert.ok(value.view.caption.includes(capability.score_label) && value.view.caption.includes("모드 n(엔진 출력 순서)"), value.view.caption);
      assert.equal(capability.score_label, SCORE_LABEL);
      assert.equal(value.view.summary["점수"], SCORE_LABEL);
      assert.deepEqual(stored.parameters, { seed: Number(plan.docking.seed), exhaustiveness: Number(plan.docking.exhaustiveness),
        num_modes: Number(plan.docking.numModes), energy_range: Number(plan.docking.energyRange), conformers: null, cpu: 1 });
      stored.box.center_A.forEach((v, i) => assert.ok(Math.abs(v - Number(plan.docking.center[i])) < 1e-9, `center ${i}`));
      stored.box.size_A.forEach((v, i) => assert.ok(Math.abs(v - Number(plan.docking.size[i])) < 1e-9, `size ${i}`));
      assert.equal(stored.inputs.receptor.sha256, plan.inputs.receptor.sha256);
      assert.equal(stored.inputs.ligand.source, "candidate");
      assert.equal(stored.inputs.ligand.candidate_id, S.X);
      const want = m18.expectedLimitations(capability.limitations, { mode: "free", source: "candidate", removed: false,
        unspecified: stored.inputs.ligand.unspecified_stereo_centers });
      assert.deepEqual(stored.limitations, want);
      assert.deepEqual(value.view.limitations, want);
      const scoreIsFirstMode = value.detail.result.modes[0].score_kcal_mol === stored.modes[0].score_kcal_mol &&
        value.view.rows[0].cells[1] === halfUp(stored.modes[0].score_kcal_mol, 1);
      assert.ok(scoreIsFirstMode, "the shown first row is not the stored first mode");
      const found = m18.forbiddenWords(value.text, stored.limitations, [SCORE_LABEL, SCORE_COLUMN]);
      assert.deepEqual(found, [], JSON.stringify(found));
      evidence.observed[name] = { ...(evidence.observed[name] ?? {}), scoreIsFirstMode, modes: stored.modes.length };
      return { modes: stored.modes.length, firstMode: stored.modes[0].score_kcal_mol };
    });
    await rec.step(`${name}-03`, "Click 접촉 보기 of 모드 1: the contact page equals the stored contacts (geometric contacts by " +
      "distance only, the area's own note says so); every stored contact equals one pair recomputed here from the input receptor PDB and " +
      "the stored pose (heavy atoms, ≤ 4.0 Å, element-pair kind)", async () => {
      await dt(page, "docking-mode-contacts-1").click();
      return contactTable(page, 1);
    }, async table => {
      contactsEqual(table, stored, 1);
      contactsFollowRules(stored, plan.contactCutoff_A);
      assert.ok(table.note.includes("수소결합 등 상호작용 판정이 아닙니다"), table.note);
      let contactMismatches = 0;
      for (const row of stored.modes) {
        const pairs = new Map(recomputeContacts(plan, row.pose_sdf).map(pair => [pair.key, pair]));
        if (pairs.size !== row.contacts.length) contactMismatches++;
        for (const contact of row.contacts) {
          const r = contact.receptor_atom;
          const pair = pairs.get(`${contact.ligand_serial}|${r.residue.chain_auth}|${r.residue.seq_auth}|${r.residue.icode ?? ""}|` +
            `${r.residue.resname}|${r.atom_name}`);
          if (!pair || Math.abs(pair.distance - contact.distance_A) > 2e-3 || pair.kind !== contact.kind) contactMismatches++;
        }
      }
      assert.equal(contactMismatches, 0, "stored contacts differ from the pairs recomputed from the input receptor and the pose");
      evidence.observed[name].contactMismatches = contactMismatches;
      return { total: table.total, shown: table.rows.length, contactMismatches };
    });
    for (const which of [1, "all"]) {
      await rec.step(`${name}-04-${which}`, `Click ${which === "all" ? "포즈 SDF 전체 내려받기" : "모드 1 내려받기"}: bytes equal the ` +
        "stored pose_sdf and the backend bytes", async () => {
        const testid = which === "all" ? "docking-download-all" : `docking-download-${which}`;
        const route = which === "all" ? `/runs/${run}/docking/results/poses_sdf?handle=${enc(docked.handle)}`
          : `/runs/${run}/docking/results/pose_sdf?handle=${enc(docked.handle)}&mode=${which}`;
        const downloaded = await downloadByClick(app, dt(page, testid));
        return { bytes: fs.readFileSync(downloaded.downloaded), served: await readBytes(page, route) };
      }, async value => {
        const want = which === "all"
          ? Buffer.from(stored.modes.map(row => `${row.pose_sdf}${row.pose_sdf.endsWith("\n") ? "" : "\n"}$$$$\n`).join(""), "utf8")
          : Buffer.from(stored.modes[which - 1].pose_sdf, "utf8");
        assert.equal(sha(value.bytes), sha(want), "downloaded bytes differ from the stored pose_sdf");
        assert.equal(sha(value.served), sha(want));
        return { sha256: sha(value.bytes), bytes: value.bytes.length };
      });
    }
    await rec.step(`${name}-05`, "The same arguments again: click 도킹 작업 시작 with the form unchanged: the existing job is " +
      "shown again (같은 입력의 기존 작업 …, no new job), no unit is used", async () => {
      const jobsBefore = (await readApi(page, `/runs/${run}/jobs`)).length;
      const entry = await units.before("B3-again");
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/jobs`, { timeout: 60000 });
      await dt(page, "docking-start").click();
      const response = await posted;
      const body = await response.json();
      await waitFor(page, async () => clean(await dt(page, "docking-notice").textContent({ timeout: 1000 }).catch(() => ""))
        .includes("같은 입력의 기존 작업") ? true : null, "existing job notice", 30000);
      await units.after(entry);
      return { status: response.status(), body, jobsBefore, jobsAfter: (await readApi(page, `/runs/${run}/jobs`)).length, entry,
        notice: clean(await dt(page, "docking-notice").textContent()) };
    }, async value => {
      const sameJob = value.body.job_id === docked.job;
      assert.ok(sameJob, `a new job ${value.body.job_id} instead of ${docked.job}`);
      assert.equal(value.jobsAfter, value.jobsBefore, "a job was added");
      assert.equal(value.notice, `같은 입력의 기존 작업을 다시 표시합니다 · ${docked.job} · done (새 작업을 만들지 않았습니다)`);
      evidence.observed[name].again = { sameJob, units: value.entry.usedUnits, httpStatus: value.status };
      return evidence.observed[name].again;
    });
    await rec.step(`${name}-06`, "Click 보고서 만들기 for the result: saved (201), analysis_type ligand_docking", async () => {
      await openDockingResult(page, docked.handle);
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
      await dt(page, "docking-report").click();
      const response = await posted;
      const body = await response.json();
      noteReport(evidence, name, "ligand_docking", response.status(), body.handle);
      await dt(page, "docking-report-done").waitFor({ timeout: 30000 });
      if (name === "B3") await keepTabText(page, evidence, artifacts, "ligand@B3", "ligand");
      return { status: response.status(), body };
    }, async value => {
      assert.equal(value.status, 201);
      assert.equal(value.body.manifest.analysis_type, "ligand_docking");
      assert.equal(value.body.manifest.result_handle, docked.handle);
      return { handle: value.body.handle };
    });
  });
}

async function flowB6(ctx) {
  const { page, rec, evidence, input, artifacts } = ctx;
  const S = ctx.state;
  const runsDir = input["runs-dir"];
  await rec.part("B6", ["B2"], async () => {
    const run = S.run;
    const built = await rec.step("B6-01", "지식·보고서 JEV area: switch the run's science consent on; 리간드 후보 집합 and the set; " +
      "check its first three candidates; 보낼 내용 만들기; open the exact body: its text = the server preview string, its " +
      "SHA-256 and bytes computed here = shown = the stored projection", async () => {
      await openKnowledge(page);
      await jevSetConsent(page, run, true);
      const rows = await jevChooseSource(page, S.set, S.candidates.length);
      const keys = rows.slice(0, 3).map(row => row.key);
      for (const key of keys) await jev(page).locator(`input[data-testid="jev-candidate"]${attr("data-jev-candidate", key)}`).check();
      const made = await jevBuild(page, run);
      await jt(page, "jev-preview-body-details").locator("summary").click();
      const shown = await jevPreviewShown(page);
      return { keys, made, shown, stored: storedObject(runsDir, run, made.handle) };
    }, async value => {
      assert.deepEqual(value.made.request.args.candidates, value.keys);
      assert.deepEqual(value.shown.blocked, []);
      const identity = jevPreviewIdentity(value.shown, value.made, value.stored);
      assert.ok(value.keys.length >= 2);
      return { ...identity, keys: value.keys, handle: value.made.handle, previewSha256: value.made.preview.body_sha256,
        body: value.shown.body };
    });
    const sent = await rec.step("B6-02", "Check the confirmation and click 이 내용을 JEV로 보냅니다 (fixture good): completed; the " +
      "card is the stored proposal, labeled JEV 판정(모델 선택); the bytes the transport received = the preview = the " +
      "prepared audit; the M24 wording check of the area finds nothing", async () => {
      const result = await jevConfirmAndSend(page, run, input.control, "good");
      const card = await jevReadCard(page, result.record.send_id);
      return { result, card, text: await jev(page).evaluate(node => node.innerText) };
    }, async value => {
      const record = value.result.record;
      assert.equal(record.status, "completed");
      const choice = storedObject(runsDir, run, record.choice_handle);
      const projection = storedObject(runsDir, run, built.handle);
      const card = jevCardMatches(value.card, record, choice, projection);
      const prepared = preparedMatches(runsDir, run, record.send_id, built.body, built.previewSha256);
      assert.equal(prepared.dispatched, 1);
      let transport = null;
      if (input.control) {
        const call = fixtureCalls(input.control).at(-1);
        assert.equal(call.script, "good");
        assert.equal(call.bodySha256, built.previewSha256, "transport bytes differ from the preview");
        assert.equal(call.authorizationIsSentinel, true);
        transport = { sha256: call.bodySha256, bytes: call.bodyBytes };
      }
      const found = m24.forbiddenWords(value.text);
      assert.deepEqual(found, [], JSON.stringify(found));
      evidence.sends.push({ case: "B6", sendId: record.send_id, status: record.status, bodySha256: built.previewSha256,
        transportSha256: transport?.sha256 ?? null, preparedSha256: prepared.preparedSha256 });
      return { card, prepared, transport, choice: record.choice_handle };
    });
    await rec.step("B6-03", "보고서 만들기 on the send row: saved (201); the library shows JEV 판정 보고서 with the stored " +
      "Markdown (fixed sentences, no per-candidate values, no forbidden word)", async () => {
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 120000 });
      await jev(page).locator(`[data-testid="jev-send-report"]${attr("data-choice-handle", sent.choice)}`).click();
      const response = await posted;
      const body = await response.json();
      noteReport(evidence, "B6", "jev_choice", response.status(), body.handle);
      await jev(page).locator(`[data-testid="jev-report-done"]${attr("data-report-handle", body.handle)}`).waitFor({ timeout: 60000 });
      const opened = await libraryOpen(page, body.handle);
      await keepTabText(page, evidence, artifacts, "knowledge@B6", "knowledge");
      return { status: response.status(), body, opened, saved: await readApi(page, `/runs/${run}/reports/selected?handle=${enc(body.handle)}`) };
    }, async value => {
      assert.equal(value.status, 201);
      assert.equal(value.body.manifest.analysis_type, "jev_choice");
      assert.equal(value.opened.kind, "JEV 판정 보고서");
      assert.equal(value.opened.text, value.saved.markdown);
      for (const sentence of m24.expectedLimitations("ligand", false)) assert.ok(value.opened.text.includes(sentence));
      assert.deepEqual(m24.forbiddenWords(value.opened.text), []);
      return { handle: value.body.handle };
    });
  });
}

/** One loop of one round: create (pool, goal, seed, cap 1, the computation inputs), 보낼 내용 만들기 (identity and the
 * order oracle), the send (guarded in the live phase), the card, the compute (one unit), end, report. */
async function loopRound(ctx, { id, pool, loop, unitLabel, guard = null }) {
  const { page, rec, evidence, units, input, log, plan } = ctx;
  const S = ctx.state;
  const runsDir = input["runs-dir"];
  const run = S.run;
  const created = await rec.step(`${id}-01`, `JEV 루프 (리간드): choose the set, check the pool (${pool.length}), ` +
    `${loop.goal === "explore" ? "탐색형" : "활용형"}, loop seed ${loop.seed}, cap ${loop.cap}, the computation inputs (the ` +
    "docking values of B3); 루프 만들기: computed candidates are scored as stored (reused, no unit), the others pending", async () => {
    await openLoopArea(page);
    await loopChooseSource(page, S.set, S.candidates.length);
    await loopPool(page, pool);
    await lpt(page, `jev-loop-goal-${loop.goal}`).check();
    await loopFill(page, "jev-loop-seed", loop.seed);
    await loopFill(page, "jev-loop-iteration-cap", loop.cap);
    await loopSetup(page, { parent: S.parent, receptor: S.receptor }, plan.docking);
    await waitFor(page, async () => await lpt(page, "jev-loop-create").isEnabled() ? true : null, "create enabled", 15000);
    const since = Date.now();
    await lpt(page, "jev-loop-create").click();
    const entry = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev_loops`, "create answer", 120000);
    await loopRecordWhen(page, value => value.loopId === entry.json?.loop_id, "loop opened", 30000);
    return { entry, record: await readLoop(page, run, entry.json.loop_id), table: await loopCandidateTable(page) };
  }, async value => {
    assert.equal(value.entry.status, 200, JSON.stringify(value.entry.json).slice(0, 600));
    assert.deepEqual(value.entry.request.pool.candidates, pool);
    assert.deepEqual([value.entry.request.goal, value.entry.request.loop_seed, value.entry.request.iteration_cap],
      [loop.goal, Number(loop.seed), Number(loop.cap)]);
    const docked = dockedCandidates(runsDir, run, S.dockStored);
    for (const item of value.record.candidates) {
      if (docked.has(item.ref)) {
        assert.deepEqual([item.state, item.evaluation], ["scored", "reused"], `${item.ref} not reused`);
        assert.equal(item.score_kcal_mol, dockingResultOf(runsDir, run, S.dockStored, item.ref).value.modes[0].score_kcal_mol);
      } else assert.equal(item.state, "pending");
    }
    assert.equal(value.record.counts.units_charged, 0);
    loopRowsMatch(value.table, value.record);
    for (const row of value.table.rows.filter(item => !item.hasScore))
      x5(evidence, row.score.startsWith(NULL_TEXT) && !/\b0(\.0+)?\b/.test(row.score), `${id} pending row ${row.ref.slice(0, 10)}: ` +
        `score cell "${row.score.slice(0, 20)}" (no score, not 0)`);
    return { loopId: value.entry.json.loop_id, computed: value.record.candidates.filter(item => item.state === "scored").length };
  });
  const loopId = created.loopId;
  const built = await rec.step(`${id}-02`, "보낼 내용 만들기 (consent on): the exact body = the server preview = the SHA-256 " +
    "computed here = the stored projection; the order, aliases, criteria and computed rows = the independent " +
    `sha256_order_v1 oracle; ${loop.goal === "explore" ? "the body carries no score (explore)" :
      "the computed rows carry the stored first-mode scores (exploit)"}`, async () => {
    await loopSetConsent(page, run, true, log);
    const record = await readLoop(page, run, loopId);
    const made = await loopBuild(page, run, log);
    const shown = await loopPreviewWhen(page, made.handle, item => item.blocked.length === 0 && item.loopBlocks.length === 0, "preview");
    return { record, made, shown, stored: storedObject(runsDir, run, made.handle) };
  }, async value => {
    const identity = loopPreviewMatches({ shown: value.shown, built: value.made, stored: value.stored, record: value.record,
      iteration: 1, ordinal: value.made.summary.send_ordinal, runId: run });
    const body = JSON.parse(value.shown.body);
    const observed = {};
    if (loop.goal === "explore") {
      observed.bodyHasScore = /score/i.test(value.shown.body);
      assert.equal(observed.bodyHasScore, false, "the explore body carries a score");
      assert.ok(body.state.computed.every(item => JSON.stringify(Object.keys(item)) === '["alias"]'));
    } else {
      const rows = body.state.computed;
      assert.ok(rows.length >= 1, "no computed row in the exploit body");
      observed.bodyScoresStored = rows.every(row => {
        const ref = value.stored.selection.find(item => item.alias === row.alias).ref;
        const stored = dockingResultOf(runsDir, run, S.dockStored, ref);
        return row.state === "scored" && !!stored && row.score_kcal_mol === stored.value.modes[0].score_kcal_mol;
      });
      assert.ok(observed.bodyScoresStored, "an exploit body score is not the stored first mode of its candidate");
      observed.computedRows = rows.length;
    }
    (evidence.observed.B7 ??= {})[loop.goal] = observed;
    return { ...identity, body: value.shown.body, handle: value.made.handle };
  });
  if (guard) {
    const verdict = guard();
    if (verdict) { evidence.live.guard = verdict; throw new Error(`no send: ${verdict}`); }
  }
  const sent = await rec.step(`${id}-03`, "Check the confirmation and click 이 내용을 JEV로 보냅니다" +
    `${input.control ? ` (fixture ${loop.script})` : " (the real science gate)"}: the result as stored; a completed send ` +
    "shows the selection card JEV 판정(모델 선택) = the stored jev_loop_choice@1 (list position n/m as a value only)", async () => {
    const result = await loopConfirmAndSend(page, run, input.control, loop.script, log);
    const record = result.record;
    if (evidence.live) evidence.live.send = { dispatched: record.status !== "rejected", status: record.status, reasonCode: record.reason_code,
      sendId: record.send_id, servedModel: record.served_model ?? null };
    const status = await readApi(page, `/runs/${run}/jev/status`);
    if (evidence.live) evidence.live.egressStop = status.egress_stop_reason ?? null;
    let card = null;
    if (record.status === "completed") {
      await lp(page).locator(`[data-testid="jev-loop-selection"]${attr("data-send-id", record.send_id)}`).waitFor({ timeout: 30000 });
      card = await loopReadCard(page, record.send_id);
    }
    return { result, card, status };
  }, async value => {
    const record = value.result.record;
    const bytes = record.status === "rejected" ? null
      : loopServerBytes(runsDir, run, record.send_id, built.body, built.bodySha256, value.result.calls);
    evidence.sends.push({ case: id, sendId: record.send_id, status: record.status, reasonCode: record.reason_code,
      goal: loop.goal, bodySha256: built.bodySha256, transportSha256: bytes?.transportSha256 ?? null, bodyBytes: built.bodyBytes });
    assert.equal(record.status, "completed", `send ${record.status}/${record.reason_code}`);
    assert.equal(value.status.egress_stop_reason ?? null, null, "the run's egress stopped");
    const choice = storedObject(runsDir, run, record.choice_handle);
    const card = loopCardMatches(value.card, record, choice, storedObject(runsDir, run, built.handle), loop.goal);
    if (evidence.live) Object.assign(evidence.live.send, { listPosition: choice.answer.list_position, listSize: choice.answer.list_size,
      responseShape: { confidence: choice.answer.confidence !== null, probabilities: choice.answer.probabilities !== null },
      usage: choice.usage, bodyBytes: built.bodyBytes });
    return { ...card, proposal: record.choice_handle, sendId: record.send_id, bytes };
  });
  const computed = await rec.step(`${id}-04`, "Check the compute confirmation and press 이 선택으로 계산 시작 (JEV 판정 사용): one " +
    "unit; the standalone M18 job (real qvina) on the candidate the card named; the round ends with the stored first-mode " +
    "score; the cap ends the loop's iterations", async () => {
    const entry = await units.before(unitLabel);
    const first = await loopPressCompute(page, run, loopId, log);
    await loopRecordWhen(page, item => item.action === "end" || Number(item.iteration) > 1, "round ended", 900000);
    await units.after(entry);
    return { first, entry, record: await readLoop(page, run, loopId), table: await loopCandidateTable(page) };
  }, async value => {
    assert.equal(value.first.status, 200, JSON.stringify(value.first.json).slice(0, 600));
    assert.deepEqual(value.first.request, { iteration: 1, proposal: sent.proposal });
    const it = value.record.iterations.find(item => item.index === 1);
    assert.equal(it.decided_by, "jev");
    assert.equal(it.candidate_ref, sent.ref, "the computation is not on the candidate JEV chose");
    const step = it.steps.find(item => item.step === "ligand_dock");
    const job = await readApi(page, `/runs/${run}/jobs/${enc(step.job_id)}`);
    assert.equal(job.protocol_id, "qvina_dock_v1");
    assert.equal(job.status, "done");
    assert.equal(it.state, "scored");
    const result = storedObject(runsDir, run, step.result_handle);
    assert.equal(it.score_kcal_mol, result.modes[0].score_kcal_mol, "the round score is not the stored first mode");
    loopRowsMatch(value.table, value.record);
    if (evidence.live) evidence.live.compute = { state: it.state, job: job.status };
    return { ref: sent.ref, state: it.state, score: it.score_kcal_mol, job: step.job_id, units: value.entry.usedUnits };
  });
  await rec.step(`${id}-05`, "루프 끝내기: the summary jev_loop_result@1 is stored (scores = stored first modes); the " +
    "sentences add LJ8 (candidates left without a score, not 0); 보고서 만들기: saved (201), JEV 루프 보고서 in the library",
  async () => {
    const ended = await loopEnd(page, run, loopId, log);
    const report = await loopReport(page, run, log);
    noteReport(evidence, id.startsWith("L-") ? "L-B7" : "B7", "jev_loop", report.status, report.json?.handle);
    const opened = report.status === 201 ? await libraryOpen(page, report.json.handle) : null;
    return { ended, report, opened, saved: report.status === 201
      ? await readApi(page, `/runs/${run}/reports/selected?handle=${enc(report.json.handle)}`) : null };
  }, async value => {
    assert.equal(value.ended.answer.status, 200);
    const summary = storedObject(runsDir, run, value.ended.result);
    assert.equal(summary.schema, "jev_loop_result@1");
    for (const row of summary.candidates) {
      if (row.state !== "scored") { assert.equal(row.score_kcal_mol, null); continue; }
      const stored = dockingResultOf(runsDir, run, S.dockStored, row.ref);
      assert.equal(row.score_kcal_mol, stored.value.modes[0].score_kcal_mol);
    }
    const uncomputed = summary.candidates.some(row => ["pending", "unavailable"].includes(row.state));
    assert.deepEqual(value.ended.limitations, m25.expectedLimitations("ligand", loop.goal, { ended: true, uncomputed }));
    x5(evidence, !uncomputed || value.ended.limitations.includes(m25.LJ.LJ8), `${id} ended loop: LJ8 shown for the candidates ` +
      "left without a score (no score, not 0)");
    assert.equal(value.report.status, 201, JSON.stringify(value.report.json).slice(0, 400));
    assert.equal(value.report.json.manifest.analysis_type, "jev_loop");
    assert.equal(value.opened.kind, LOOP_REPORT_KIND);
    assert.equal(value.opened.text, value.saved.markdown);
    assert.deepEqual(m25.forbiddenWords(value.opened.text), [], "forbidden wording in the loop report");
    return { endReason: summary.end_reason, report: value.report.json.handle, counts: summary.counts };
  });
  return { loopId, chosen: computed.ref, proposal: sent.proposal };
}

async function flowB7(ctx) {
  const { rec, evidence, plan, artifacts, page } = ctx;
  const S = ctx.state;
  await rec.part("B7", ["B2", "B3"], async () => {
    const ids = S.candidates.map(item => item.id);
    const pending = ids.filter(id => id !== S.X);
    assert.ok(pending.length >= 4, "fewer than five candidates for two loops");
    const explore = await loopRound(ctx, { id: "B7-explore", pool: [S.X, pending[0], pending[1]], loop: plan.loops.explore,
      unitLabel: "B7-explore" });
    S.Y = explore.chosen;
    const exploit = await loopRound(ctx, { id: "B7-exploit", pool: [S.X, S.Y, pending[2], pending[3]], loop: plan.loops.exploit,
      unitLabel: "B7-exploit" });
    S.Z = exploit.chosen;
    evidence.observed.B7 = { ...(evidence.observed.B7 ?? {}), chosen: [S.Y, S.Z] };
    await keepTabText(page, evidence, artifacts, "ligand@B7", "ligand");
  });
}

async function flowB4(ctx, name, needs) {
  const { page, plan, rec, evidence, units, input, artifacts } = ctx;
  const S = ctx.state;
  const runsDir = input["runs-dir"];
  await rec.part(name, needs, async () => {
    const run = S.run;
    const docked = dockedCandidates(runsDir, run, S.dockStored);
    const ids = S.candidates.map(item => item.id);
    const computed = ids.filter(id => docked.has(id));
    const fresh = ids.filter(id => !docked.has(id));
    const selection = [...computed.slice(0, plan.batch.computed), ...fresh.slice(0, plan.batch.new)];
    assert.equal(computed.length >= plan.batch.computed && fresh.length >= plan.batch.new, true,
      `candidates with a stored result ${computed.length}, without ${fresh.length}`);
    S.batchSelection = selection;
    const pf = await rec.step(`${name}-01`, `일괄 도킹: 입력 목록 다시 읽기; the receptor (model 1, 없음, PDB CONECT), the set and ` +
      `its parent SDF; tick ${selection.length} candidates (${plan.batch.computed} with a stored result of these values, ` +
      `${plan.batch.new} without), 부모 기준 행, 자유 도킹 with the B3 values; 시작 전 확인 보기: ${plan.batch.newRows} new rows, ` +
      `${plan.batch.computed} reused, the shortfall is the plan's`, async () => {
      await openLigandTab(page);
      const reread = page.waitForResponse(response => response.request().method() === "GET" &&
        new URL(response.url()).pathname === `/api/runs/${run}/docking/prerequisites`, { timeout: 30000 });
      await bt(page, "docking-batch-prereq-refresh").click();
      await reread;
      await bt(page, "docking-batch-receptor").selectOption(S.receptor);
      await bt(page, "docking-batch-model").waitFor({ timeout: 30000 });
      await bt(page, "docking-batch-model").selectOption(plan.docking.model);
      await bt(page, "docking-batch-instances").waitFor({ timeout: 30000 });
      await batch(page).locator('[data-testid="docking-batch-instances"] label[data-batch-instance="none"] input').check();
      await bt(page, "docking-batch-connectivity").locator("label").filter({ hasText: "PDB CONECT" }).locator("input").check();
      await bt(page, "docking-batch-candidate-set").selectOption(S.set);
      await bt(page, "docking-batch-parent-sdf").waitFor({ timeout: 30000 });
      await bt(page, "docking-batch-parent-sdf").selectOption(S.parent);
      await bt(page, "docking-batch-candidates").waitFor({ timeout: 30000 });
      for (const id of selection) await bt(page, `docking-batch-candidate-${id}`).check();
      await batch(page).locator('label[data-batch-mode="free"] input').check();
      await bt(page, "docking-batch-include-parent").check();
      await batch(page).locator('label[data-batch-box="manual"] input').check();
      const fill = async (id, value) => { const field = bt(page, id); await field.click(); await field.fill(value); };
      for (const [i, axis] of ["x", "y", "z"].entries()) {
        await fill(`docking-batch-center-${axis}`, plan.docking.center[i]);
        await fill(`docking-batch-size-${axis}`, plan.docking.size[i]);
      }
      await fill("docking-batch-seed", plan.docking.seed);
      await fill("docking-batch-exhaustiveness", plan.docking.exhaustiveness);
      await fill("docking-batch-num-modes", plan.docking.numModes);
      await fill("docking-batch-energy-range", plan.docking.energyRange);
      for (const key of ACK_KEYS) await batch(page).locator(`label[data-batch-ack="${key}"] input`).check();
      const entry = await units.before("B4");
      return { pf: await batchPreflight(page, run), entry };
    }, async value => {
      const facts = batchPreflightMatches(value.pf, { rows: selection.length + 1, reused: plan.batch.computed });
      assert.equal(facts.n, plan.batch.newRows);
      if (value.entry.onPlan)
        assert.equal(facts.shortfall.expensive_calls, plan.units.raises.B4 ?? 0, "the unit shortfall differs from the plan");
      // the batch lists the ticked candidates in set order (M19 rows: the parent row first)
      assert.deepEqual(value.pf.body.rows.map(row => [row.kind, row.candidate_id]),
        [["parent", null], ...ids.filter(id => selection.includes(id)).map(id => ["candidate", id])]);
      S.batchEntry = value.entry;
      return { ...facts, request: value.pf.request };
    });
    if (pf.shortfall.expensive_calls > 0 || pf.shortfall.wall_clock_s > 0) {
      await rec.step(`${name}-02`, "Click 이 일괄에 필요한 만큼 한도를 올림 (a person's click): the limit rises by the shortfall " +
        "only, by human; the preflight is read again with no shortfall", async () => {
        const budget = await readApi(page, `/runs/${run}/budget`);
        const eventsBefore = runEvents(runsDir, run).length;
        const approval = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${run}/docking/batches/limit_approval`, { timeout: 60000 });
        const reread = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${run}/docking/batches/preflight`, { timeout: 60000 });
        await bt(page, "docking-batch-limit-approve").click();
        const approved = await (await approval).json();
        const again = await (await reread).json();
        await bt(page, "docking-batch-limit-done").waitFor({ timeout: 30000 });
        const view = await batchPreflightView(page, again);
        return { budget, approved, again, view, events: runEvents(runsDir, run).slice(eventsBefore),
          budgetAfter: await readApi(page, `/runs/${run}/budget`) };
      }, async value => {
        assert.equal(value.approved.raised, true);
        assert.equal(value.approved.increase.expensive_calls, pf.shortfall.expensive_calls, "the raise is not the shortfall");
        assert.equal(value.budgetAfter.expensive_calls.limit, value.budget.expensive_calls.limit + pf.shortfall.expensive_calls);
        assert.equal(value.budgetAfter.expensive_calls.used, value.budget.expensive_calls.used, "the approval used budget");
        const updated = value.events.filter(event => event.type === "budget_limit_updated");
        assert.equal(updated.length, 1);
        assert.equal(updated[0].by, "human");
        assert.ok(!value.events.some(event => event.type.startsWith("job_") || event.type === "object_created"));
        assert.deepEqual(value.again.shortfall, { expensive_calls: 0, wall_clock_s: 0 });
        assert.equal(value.view.approvalButtons, 0);
        assert.equal(value.view.start.enabled, true, value.view.start.blocked);
        evidence.raises.push({ case: name, shortfall: pf.shortfall, increase: value.approved.increase,
          limitsBefore: value.approved.limits_before, limitsAfter: value.approved.limits_after, by: "human-click" });
        return evidence.raises.at(-1);
      });
    }
    const ran = await rec.step(`${name}-03`, "Click 일괄 시작 (no second approval): the real qvina batch runs to done with the " +
      "plan's units; choose its summary: every row (state, score = its M18 first mode, 모드 1(엔진 출력 순서), reuse mark) " +
      "equals the stored summary; B1 and B3 verbatim; the headers are the M19 ones", async () => {
      const job = await runBatch(page, run);
      await units.after(S.batchEntry);
      const table = await openBatchSummary(page, job.handle);
      return { job, table, detail: await readApi(page, `/runs/${run}/docking/batches/detail?handle=${enc(job.handle)}`) };
    }, async value => {
      assert.equal(value.job.job.status, "done", JSON.stringify(value.job.job.failure));
      assert.equal(value.job.approved, false);
      const stored = storedObject(runsDir, run, value.job.handle);
      batchTableEquals(value.table, value.detail, stored, runsDir, run);
      S.batchStored = stored;
      S.batchDetail = value.detail;
      return { handle: value.job.handle, rows: stored.rows.length, reused: value.detail.reused_rows.length,
        units: S.batchEntry.usedUnits };
    });
    await rec.step(`${name}-04`, "Click 점수, 후보 id and 행 번호 headers twice each: the order follows the independent sort " +
      "rule (rows without a score always last), aria-sort follows", () => batchSortChecks(page, S.batchStored), async value => value);
    await rec.step(`${name}-05`, "Click 상세 열기 of every row: the M18 docking area opens that row's stored result and its " +
      "모드 1 score cell equals the row's score cell; each row score is the first mode of that single M18 result", async () => {
      const rows = [];
      for (const row of S.batchStored.rows) {
        if (!row.result_handle) { rows.push({ row: row.row_index, handle: null }); continue; }
        await bt(page, `docking-batch-open-${row.row_index}`).click();
        const view = dock(page).locator(`[data-testid="docking-result"]${attr("data-docking-result-handle", row.result_handle)}`);
        await view.waitFor({ timeout: 30000 });
        const first = await view.locator('[data-testid="docking-modes"] tbody tr[data-mode="1"] td').allTextContents();
        rows.push({ row: row.row_index, handle: row.result_handle, firstCells: first.map(clean) });
      }
      return rows;
    }, async rows => {
      let rowScoreMismatches = 0;
      for (const item of rows) {
        const row = S.batchStored.rows.find(entry => entry.row_index === item.row);
        if (!item.handle) continue;
        const single = storedObject(runsDir, run, item.handle);
        if (single.modes[0].score_kcal_mol !== row.score_kcal_mol) rowScoreMismatches++;
        if (item.firstCells[0] !== MODE_ROW || item.firstCells[1] !== halfUp(row.score_kcal_mol, 1)) rowScoreMismatches++;
      }
      assert.equal(rowScoreMismatches, 0, "a row score differs from its single M18 result");
      evidence.observed[name] = { newRows: S.batchStored.rows.length - S.batchDetail.reused_rows.length,
        rowScoreMismatches, rows: rows.length };
      return evidence.observed[name];
    });
    await rec.step(`${name}-06`, "Click 보고서 만들기 for the batch summary: saved (201), analysis_type ligand_docking_batch", async () => {
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
      await bt(page, "docking-batch-report").click();
      const response = await posted;
      const body = await response.json();
      noteReport(evidence, name, "ligand_docking_batch", response.status(), body.handle);
      await bt(page, "docking-batch-report-done").waitFor({ timeout: 30000 });
      if (name === "B4") await keepTabText(page, evidence, artifacts, "ligand@B4", "ligand");
      return { status: response.status(), body };
    }, async value => {
      assert.equal(value.status, 201);
      assert.equal(value.body.manifest.analysis_type, "ligand_docking_batch");
      return { handle: value.body.handle };
    });
  });
}

async function flowB5(ctx) {
  const { page, plan, rec, evidence, units, input, artifacts } = ctx;
  const S = ctx.state;
  const runsDir = input["runs-dir"];
  await rec.part("B5", ["B2"], async () => {
    const run = S.run;
    const ids = S.candidates.map(item => item.id);
    const firstGenerations = {};
    for (const key of ["1", "2"]) {
      const setting = plan.ga.settings[key];
      const label = `B5-${key}`;
      const priorDocked = dockedCandidates(runsDir, run, S.dockStored);
      const pf = await rec.step(`${label}-01`, `GA area: 입력 목록 다시 읽기; the set and its parent, the receptor (model 1, 없음, ` +
        `PDB CONECT), the B3 docking values, the acknowledgements; setting ${key} (${GA_KEYS.map(item => `${item} ${setting[item]}`)
          .join(", ")}); 시작 전 확인 보기: the reserved units are on screen and equal the spec 6 arithmetic`, async () => {
        await openGaArea(page);
        await gaChooseInputs(page, run, { set: S.set, parent: S.parent, receptor: S.receptor }, plan.docking);
        for (const item of GA_KEYS) await gaFill(page, `ligand-ga-param-${item}`, setting[item]);
        const entry = await units.before(label);
        return { pf: await gaPreflight(page, run), entry };
      }, async value => {
        const facts = gaPreflightMatches(value.pf, { gaValues: setting, want: plan.ga.need[key],
          pool: { size: ids.length, eligible_count: ids.length, filter_excluded_count: 0 } });
        if (value.entry.onPlan)
          assert.equal(facts.shortfall.expensive_calls, plan.units.raises[label] ?? 0, "the unit shortfall differs from the plan");
        S.gaEntry = value.entry;
        return { ...facts, request: value.pf.request, pf: value.pf };
      });
      if (pf.shortfall.expensive_calls > 0 || pf.shortfall.wall_clock_s > 0) {
        await rec.step(`${label}-02`, "Click 이 GA에 필요한 만큼 한도를 올림 (a person's click): the limit rises by the " +
          "shortfall only, by human, with the GA context; the preflight is read again with no shortfall", async () => {
          const before = runEvents(runsDir, run).length;
          const value = await gaApproveLimits(page, run, pf.pf);
          return { value, events: runEvents(runsDir, run).slice(before) };
        }, async ({ value, events }) => {
          const facts = gaApprovalMatches(value, events);
          evidence.raises.push({ case: label, shortfall: facts.shortfall, increase: facts.increase,
            limitsBefore: facts.limitsBefore, limitsAfter: facts.limitsAfter, by: "human-click" });
          return evidence.raises.at(-1);
        });
      }
      const ran = await rec.step(`${label}-03`, "Click GA 시작 (no second approval): the real GA runs to its stop reason with " +
        "exactly the reserved units; choose its summary: every generation table equals the stored individuals (score = the " +
        "stored M18 first mode, min / max as values only), the stop reason is in the closed set, G1–G3 verbatim", async () => {
        const job = await runGa(page, run);
        await units.after(S.gaEntry);
        const header = await openGaSummary(page, job.handle);
        return { job, header, detail: await readApi(page, `/runs/${run}/ligand/ga/results/${enc(job.handle)}`) };
      }, async value => {
        assert.equal(value.job.job.status, "done", JSON.stringify(value.job.job.failure));
        assert.equal(value.job.approved, false);
        const stored = storedObject(runsDir, run, value.job.handle);
        const facts = await gaResultEquals(page, ids, value.header, value.detail, stored, runsDir, run);
        assert.equal(stored.reserved_units, plan.ga.need[key].reserved);
        firstGenerations[key] = stored.generations[0].individuals.map(item => item.candidate_id);
        let reuseMismatches = 0;
        if (key === "2") {
          for (const item of stored.generations.flatMap(gen => gen.individuals).filter(entry => entry.origin !== "carried")) {
            const want = priorDocked.has(item.candidate_id) ? "reused" : "docked";
            if (item.evaluation !== want) reuseMismatches++;
          }
          assert.deepEqual(firstGenerations["2"], firstGenerations["1"], "the same GA seed did not give the same first generation");
          assert.ok(stored.generations[0].individuals.every(item => item.evaluation === "reused"), "a setting-1 individual was docked again");
          assert.equal(reuseMismatches, 0, "an individual with a stored result of the same arguments was docked again");
        }
        S.gaStored = stored;
        const observed = (evidence.observed.B5 ??= { settings: {} });
        observed.settings[key] = { reserved: stored.reserved_units, newDockings: stored.new_dockings_used, reused: stored.reused_count,
          stopReason: stored.stop_reason, status: stored.status, generations: stored.generations.length };
        if (key === "2") observed.reuseMismatches = reuseMismatches;
        for (const item of stored.generations.flatMap(gen => gen.individuals).filter(entry => entry.state !== "scored"))
          x5(evidence, item.score === null, `${label} individual ${item.candidate_id} without a score: null, shown empty (not 0)`);
        return { ...facts, units: S.gaEntry.usedUnits };
      });
      if (key === "1") await rec.step(`${label}-04`, "Click the score, candidate id and slot headers twice each on generation " +
        "1: the order follows the independent rule (rows without a score last)", async () => {
        await gaShowGeneration(page, S.gaStored.generations[0].index);
        return gaSortChecks(page, S.gaStored.generations[0]);
      }, async value => value);
      await rec.step(`${label}-05`, "Click 보고서 만들기 for this GA summary: saved (201), analysis_type ligand_ga", async () => {
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
        await gt(page, "ligand-ga-report").click();
        const response = await posted;
        const body = await response.json();
        noteReport(evidence, "B5", "ligand_ga", response.status(), body.handle);
        await gt(page, "ligand-ga-report-done").waitFor({ timeout: 30000 });
        return { status: response.status(), body };
      }, async value => {
        assert.equal(value.status, 201);
        assert.equal(value.body.manifest.analysis_type, "ligand_ga");
        return { handle: value.body.handle, ran: ran.status };
      });
    }
    await keepTabText(page, evidence, artifacts, "ligand@B5", "ligand");
  });
}

async function flowB8(ctx) {
  const { page, app, rec, evidence, input, artifacts } = ctx;
  const S = ctx.state;
  const runsDir = input["runs-dir"];
  await rec.part("B8", [], async () => {
    assert.ok(S.run, "no run");
    const run = S.run;
    const made = evidence.reportHandles.filter(item => item.httpStatus === 201);
    await rec.step("B8-01", "지식·보고서 report library: the list (one read by the screen; the list route reopens every " +
      "report, so no second read competes with it) shows exactly the reports of the run's report events, which are the " +
      "reports B1–B7 made; each one clicked opens with the stored Markdown and reports/selected 200; its JSON 다운로드 " +
      "equals the backend bytes and the stored manifest bytes", async () => {
      const events = runEvents(runsDir, run).filter(event => ["report_created", "method_report_created"].includes(event.type));
      const handles = events.map(event => event.report_handle);
      await selectTab(page, TAB.knowledge);
      let state = null;
      const shown = await waitFor(page, async () => {
        const region = library(page).getByRole("region", { name: "저장된 보고서", exact: true });
        state = await region.evaluate(node => ({ alert: node.querySelector('[role="alert"]')?.textContent ?? null,
          busy: !!node.querySelector('[aria-busy="true"]') }));
        const rows = await libraryRows(page);
        return rows.length === handles.length && handles.every(handle => rows.some(row => row.codes[0] === handle)) ? rows : null;
      }, `report list shown (last state ${JSON.stringify(state)})`, 180000);
      const opened = [];
      for (const item of made) {
        const view = await libraryOpen(page, item.handle);
        const selected = await page.request.get(new URL(`/api/runs/${run}/reports/selected?handle=${enc(item.handle)}`,
          page.url()).toString(), { timeout: 120000 });
        const saved = await selected.json();
        const downloaded = await downloadByClick(app, view.content.getByRole("link", { name: "JSON 다운로드", exact: true }));
        opened.push({ ...item, kind: view.kind, selectedStatus: selected.status(), markdownEqual: view.text === saved.markdown,
          download: fs.readFileSync(downloaded.downloaded),
          backend: await readBytes(page, `/runs/${run}/reports/download?handle=${enc(item.handle)}&format=json`),
          stored: storedBytes(runsDir, run, item.handle) });
      }
      await keepTabText(page, evidence, artifacts, "knowledge@B8", "knowledge");
      return { handles, shown, opened };
    }, async value => {
      let downloadMismatches = 0;
      for (const item of value.opened) {
        assert.ok(value.handles.includes(item.handle), `${item.case} report is not a report event`);
        assert.equal(item.selectedStatus, 200, `${item.case} report does not reopen`);
        assert.ok(item.markdownEqual, `${item.case} shown Markdown differs`);
        if (sha(item.download) !== sha(item.backend) || sha(item.download) !== sha(item.stored)) downloadMismatches++;
      }
      assert.equal(value.shown.length, value.handles.length, "the screen list is not the report events");
      assert.equal(value.handles.length, made.length, "report events ≠ the reports the cases made");
      assert.equal(downloadMismatches, 0, "a JSON download differs from the stored bytes");
      evidence.observed.B8 = { listed: value.shown.length, created: made.length, events: value.handles.length, downloadMismatches,
        kinds: [...new Set(value.opened.map(item => item.kind))].sort(),
        reports: value.opened.map(item => ({ case: item.case, kind: item.kind, jsonSha256: sha(item.download) })) };
      return evidence.observed.B8;
    });
  });
}

// ------------------------------------------------------------------ modes
async function modeFixture(ctx) {
  const { input } = ctx;
  m25.fixtureServer(input.control, input["runs-dir"], input["backend-pid"]);
  await flowB1(ctx);
  await flowB2(ctx, "B2");
  await flowB3(ctx, "B3", ["B2"]);
  await flowB6(ctx);
  await flowB7(ctx);
  await flowB4(ctx, "B4", ["B2"]);
  await flowB5(ctx);
  await flowB8(ctx);
}

async function modeLive(ctx) {
  const { input, plan, rec, evidence, page, artifacts } = ctx;
  const S = ctx.state;
  if (input.control) m25.fixtureServer(input.control, input["runs-dir"], input["backend-pid"]);
  evidence.live = { rehearsal: !!input.control, sendAllowed: plan.live.sendAllowed, dispatchLimit: plan.live.dispatchLimit,
    send: null, compute: null, guard: null, egressStop: null };
  await flowB2(ctx, "L-pre-B2");
  await flowB3(ctx, "L-pre-B3", ["L-pre-B2"]);
  await flowB4(ctx, "L-pre-B4", ["L-pre-B3"]);
  await rec.part("L-B7", ["L-pre-B2", "L-pre-B3", "L-pre-B4"], async () => {
    const docked = dockedCandidates(input["runs-dir"], S.run, S.dockStored);
    const ids = S.candidates.map(item => item.id);
    const computed = ids.filter(id => docked.has(id));
    const pending = ids.filter(id => !docked.has(id)).slice(0, 2);
    assert.equal(pending.length, 2, "fewer than two candidates left without a result");
    const guard = () => {
      if (!plan.live.sendAllowed) return "the plan does not allow a send (an earlier round did not complete)";
      const total = dispatchTotal(input["runs-dir"]);
      if (total >= plan.live.dispatchLimit) return `dispatch events ${total} ≥ the limit ${plan.live.dispatchLimit}`;
      return null;
    };
    await loopRound(ctx, { id: "L-B7", pool: [...computed, ...pending], loop: plan.loops.exploit, unitLabel: "B7-exploit", guard });
    await keepTabText(page, evidence, artifacts, "ligand@L-B7", "ligand");
  });
  evidence.live.dispatchCounts = dispatchCounts(input["runs-dir"]);
}

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const plan = input.planData;
  const evidence = { schema: "m28_branch_b_evidence@1", mode: input.mode, rehearsal: input.mode === "live" && !!input.control,
    run: null, parts: {}, observed: {}, reportsCreated: 0, reportHandles: [], x5: [], texts: {}, units: [], raises: [],
    sends: [], live: null, planSha256: sha(fs.readFileSync(input.plan)), inputs: Object.fromEntries(Object.entries(plan.inputs)
      .map(([key, item]) => [key, { name: item.name, sha256: item.sha256, syntheticLabeled: item.syntheticLabeled }])),
    startedAt: new Date().toISOString() };
  const session = await launchOffscreen({ url: input.url, artifacts: input.artifacts, interactive: false });
  const log = requestLog(session.page);
  const units = unitTracker(session.page, plan, evidence);
  const rec = recorder(session, evidence, () => units.offPlan());
  const ctx = { ...session, input, plan, rec, evidence, units, log, state: {} };
  const callsBefore = input.control ? fixtureCalls(input.control).length : 0;
  // The runner runs the branches one after another on one fixture server and one runs folder (T9): this
  // harness owns only the calls and dispatch events made after it started.
  const dispatchedBefore = input.control ? dispatchTotal(input["runs-dir"]) : 0;
  let error = null;
  let proof = null;
  try {
    proof = await offscreenProof(session.app, session.page);
    await (input.mode === "fixture" ? modeFixture : modeLive)(ctx);
  } catch (caught) {
    error = caught;
  } finally {
    try { proof = { ...await offscreenProof(session.app, session.page), atStart: proof }; } catch { /* keep the start proof */ }
    await session.close();
  }
  const parts = Object.fromEntries(Object.entries(evidence.parts).map(([name, value]) => [name, value.status]));
  let fixtureProof = null;
  if (input.control) {
    const calls = fixtureCalls(input.control).slice(callsBefore);
    const reads = credentialReads(input.control);
    const dispatched = dispatchTotal(input["runs-dir"]) - dispatchedBefore;
    evidence.fixture = { calls: calls.length, scripts: calls.map(call => call.script), dispatched, dispatchedBefore,
      sentinelAuthorization: calls.every(call => call.authorizationIsSentinel === true), credentialReads: reads };
    fixtureProof = calls.length === dispatched && calls.every(call => call.authorizationIsSentinel === true) &&
      reads !== null && reads.productResolverReads === 0 && calls.every(call => ["good", "good_second"].includes(call.script));
  }
  const complete = offscreenComplete(proof);
  const passed = !error && complete && proof.nonLoopbackRequests === 0 && (fixtureProof !== false) &&
    Object.keys(parts).length > 0 && Object.values(parts).every(value => value === "pass");
  evidence.finishedAt = new Date().toISOString();
  evidence.error = error ? String(error.stack ?? error).slice(0, 4000) : null;
  evidence.requestCount = log.rows.length;
  fs.writeFileSync(path.join(input.artifacts, "endtoend-b-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  const harness = Object.fromEntries(["endtoend-b-flow.cjs", "driver.cjs", "main.cjs", "docking-flow.cjs", "docking-batch-flow.cjs",
    "ligand-ga-flow.cjs", "ligand-flow.cjs", "jev-flow.cjs", "jev-loop-flow.cjs", "m11-ledger.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m28_branch_b_row@1", mode: input.mode, rehearsal: evidence.rehearsal,
    evidenceKind: "real_electron_offscreen", status: passed ? "pass" : "fail", parts, runId: evidence.run,
    reportsCreated: evidence.reportsCreated, buildId: buildId(), harness, offscreen: proof, offscreenComplete: complete,
    externalRequestCount: proof ? proof.nonLoopbackRequests : null, fixtureProof, fixture: evidence.fixture ?? null,
    units: evidence.units.map(item => ({ label: item.label, remaining: item.remaining, planned: item.planned, used: item.usedUnits ?? null })),
    raises: evidence.raises, sends: evidence.sends, live: evidence.live,
    error: evidence.error ? "see endtoend-b-evidence.json" : null, evidenceFile: "endtoend-b-evidence.json",
    stepsFile: path.basename(rec.file), artifacts: input.artifacts, startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, run: evidence.run, parts }) + "\n");
  if (error) process.stderr.write(`endtoend-b-flow failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`endtoend-b-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, sdfAtoms, recomputeContacts, inputAtomOf };
