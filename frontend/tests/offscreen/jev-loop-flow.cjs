"use strict";

// M25 JEV design loop offscreen QA (.dryforge/spec.md sections 2-10 and 12 "오프스크린 QA"). Real Electron offscreen page
// (isOffscreen, GPU/WebGL, paint). Every product action is a Playwright locator mouse/keyboard input on the "JEV 루프"
// areas of the 리간드 설계·탐색 and 단백질 공학 tabs (consent switch, set radio, candidate checkboxes, goal radio, loop
// seed, iteration cap, computation inputs, 루프 만들기, 보낼 내용 만들기, the exact-body confirmation, 이 내용을 JEV로
// 보냅니다, the compute confirmation, 이 선택으로 계산 시작, 직접 지정, 비싼 계산 승인, 작업 시작, 도킹 시작, 도킹 포기, 루프
// 끝내기, 보고서 만들기, sort headers), the 지식·보고서 tab (send history, report library) and the M21 model list. DOM
// .click() and product handlers are never called and this script never posts to the API itself. Observation is
// read-only: data attributes and text of the page, renderer request/response events, Electron paint frames, GET reads
// of the loopback API, the stored objects and events in <runs-dir>/<run>/events.jsonl (read-only file reads) and the
// fixture server's control folder (calls.jsonl, credentials.json).
//
// The runs and their inputs are made beforehand by backend/tests/offscreen_jev_loop_fixture/qa_setup.py (real cheap
// tools and real M17 jobs over the loopback API) and named in --setup. Independent oracle written here from the spec:
// LJ1-LJ8, UL1-UL3 and the four instructions verbatim (spec 4.5, 9.3), the shuffle sha256_order_v1 (spec 4.3: order,
// aliases, criteria, computed rows, list position), the closed reason names, the limitation lists per goal and branch,
// the display rounding (ROUND_HALF_UP; 1 decimal for scores, 3 for model-reported values), the order rule of the
// candidate table (rows without a score last in every order) and the wording check. Body identity: the preview <pre>
// text, the server preview string, the SHA-256 computed here, the stored projection, the audit `prepared` body and the
// bytes the scripted fixture transport received (calls.jsonl). Scores are never computed here: each one shown is
// compared with the stored M18 docking_result@1 of that step.
//
// Modes (the full sequence: scripts/m25_offscreen_acceptance.py):
//   fixture  backend = backend/tests/offscreen_jev_loop_fixture/server.py (SCIENCE_GATE over a scripted
//            httpx.MockTransport; no provider socket; no credential read but the sentinel placeholder). Run L (ligand):
//            tab entry, create field reasons, loop A (exploit, pool 5, cap 3): consent off block, preview identity and
//            order oracle, confirmation, model mismatch (then ordinal_mismatch), good (JEV card, list position, folded
//            values), compute with the JEV proposal (real qvina), computed alias (response_invalid), late reply after
//            consent off, human
//            designation of the late choice, a designation with no send, the candidate table orders, end, summary,
//            report; loop B (explore, a stored result reused) with no usage (egress stop); loop C (the stop refuses the
//            send); send cap display; 지식·보고서 loop rows; other tabs. Run P (protein, 1UBQ): tab entry, the 21st
//            candidate refused, create field reasons, the 1MQ4 pool refused by the server (setup_invalid,
//            openmm_preflight_failed), loop (explore, pool 3, cap 2): good send, compute with the first expensive-call
//            approval (POST /jobs/approve) and job start, end refused while the job waits and while docking waits, real
//            PDBFixer/OpenMM model and qvina docking, a human designation then docking abandoned, end, summary, report;
//            a second loop (exploit) reusing the computed candidate and HTTP 500 (a reply without usage stops the run's
//            egress, so it is the run's last send); the M21 pair table's loop docking mark, 지식·보고서 loop rows, other
//            tabs.
//   calibrate, live
//            the --plan the runner wrote (entries = loops of one branch in one setup run, one send per round; calibrate
//            = the first entry after pre-checks with no send, live = the rest). Every round: consent on, 보낼 내용 만들기,
//            the preview identity and order oracle, a dispatch guard right before the one click (the jev_science_
//            dispatch_started events of every run of --runs-dir must stay below plan.maxDispatch and plan.maxPerRun[run]),
//            the send, the result as stored; a compute round then presses 이 선택으로 계산 시작 (the first expensive-call
//            approval when asked; protein: the model, then 도킹 시작). Each loop is ended (summary) and, when planned,
//            reported; the shuffle entry records its first send beside the earlier loop's (same pool and goal, other loop
//            seed): two orders and two chosen list positions as observed values only. Against the product backend (no
//            --control) this sends to JEV and is run only by the runner's calibrate/live phases (its ledger and count);
//            with --control it is the rehearsal of the same path against the fixture server (script good, no call).
//            A send that does not complete, or a stopped egress, ends the plan (no retry, no new run); its row is kept.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { launchOffscreen, capture } = require("./driver.cjs");
const { halfUp, forbiddenWords: m24ForbiddenWords, J, U } = require("./jev-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const MODES = ["fixture", "calibrate", "live"];
const MAX_LIVE_CALLS = 8;              // the user's allocation of real calls for M25 (2026-10-07)
const TAB = { structure: "구조 분석", protein: "단백질 공학", ligand: "리간드 설계·탐색", knowledge: "지식·보고서" };
const TAB_LABELS = [TAB.structure, TAB.protein, TAB.ligand, TAB.knowledge];
const SERVED_MODEL = "typesafe/jev-1.13-20260917";
const REQUEST_MODEL = "typesafe/jev-1.13";
const PROVIDER = { allow_fallbacks: false, data_collection: "deny", zdr: true };
const MAX_POOL = 20;
const SEND_CAP = 10;
const SCORE_LABEL = "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)";
const SCORE_COLUMN = "qvina 점수(kcal/mol)";
const UNKNOWN_USAGE = "알 수 없음";
const NULL_TEXT = "—";
const APPROVAL_NOTICE = "승인을 기록했습니다. 작업 시작을 누르면 실제 계산이 실행됩니다.";
const PAIR_LOOP_TEXT = "루프 도킹(야생형 없음)";
const LOOP_REPORT_KIND = "JEV 루프 보고서";
const PROCESS_NOTE = "fixture: replies are scripted labeled fixtures (backend/tests/offscreen_jev_loop_fixture/server.py)";
// spec 9.3 verbatim (independent of the product constants)
const LJ = {
  LJ1: "JEV 루프는 사람이 바퀴마다 보낼 내용과 계산 시작을 승인하며, JEV 판정은 외부 모델이 계산 대기열에 먼저 둘 후보로 " +
    "고른 하나일 뿐 계산 결과가 아니라 제안으로 따로 기록한 것이다. 순위·추천·예측이 아니고 고른 이유는 알 수 없다.",
  LJ2: "점수는 저장된 qvina 도킹 결과의 첫 모드 값(kcal/mol, Vina 계열 스코어링 함수 값, 친화도가 아님)이며, 점수 없음은 " +
    "0이 아니다. 바퀴 순서·표 정렬·선택 표시는 순위나 개선이 아니다.",
  LJ3: "후보 순서와 별칭은 전송마다 기록된 seed로 섞은 것이며 의미가 없다. 모델 선택은 목록 위치의 영향을 받을 수 있어 " +
    "고른 위치를 값으로 기록했고, 이 기록은 효과를 뜻하지 않는다.",
  LJ4: "활용형은 점수가 낮게 나온 후보와 구조가 비슷한 후보를 고르게 하는 질문이며 점수 예측이 아니고 후보를 줄 세우지 않는다.",
  LJ5: "탐색형은 이미 계산한 후보와 가장 다른 후보를 고르게 하는 질문이며 점수를 보내지 않았다.",
  LJ6: "후보는 2D 그래프이고 점수는 사용자가 정한 수용체·상자에서 자유 도킹한 qvina 값이며 결합·활성·합성 가능성이 아니다. " +
    "JEV에는 수용체 정보를 보내지 않았다.",
  LJ7: "점수는 후보마다 다른 변이 구조(PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 단백질만의 " +
    "모델)에 사용자 리간드를 자유 도킹한 값이라 같은 수용체 안의 비교가 아니며 변이의 효과나 친화도가 아니다. 야생형 기준은 " +
    "계산하지 않았다.",
  LJ8: "이 루프는 계산하지 않은 후보를 남기고 끝났으며 계산하지 않은 후보는 점수가 없다(0이 아니다).",
};
const UL = {
  UL1: "JEV 루프는 바퀴마다 보낼 내용 승인과 계산 시작 승인을 따로 받는다. JEV가 고른 후보도 사람이 승인해야 계산된다.",
  UL2: "한 바퀴에 JEV 응답이 한 번 완료되면 다시 묻지 않는다. 다른 후보를 원하면 직접 지정한다.",
  UL3: "루프 전송은 뷰어 모델 명령·지식·보고서 탭의 전송과 같은 외부 토큰·USD 예산, 같은 run 10회 전송 상한, 같은 " +
    "'사용량 모름' 중지 상태를 쓴다.",
};
const FIXED_LINES = [...Object.values(LJ), ...Object.values(UL), U.U3, J.J7];
// spec 4.5 verbatim: C, O, E, S, RDK, GEO, NC and the four (kind, goal) instructions
const C = "Choose exactly one candidate from the candidates listed in the criteria to place first in a local computation " +
  "queue. This is a queue-order choice only; it is not a prediction of binding, activity, affinity, stability, " +
  "synthesizability, safety or the effect of a substitution. ";
const O = "The order of the candidate list and the alias numbers were shuffled for this request and carry no meaning.";
const E = "The computed field lists the aliases of the candidates that have already been computed. ";
const S = "Computed candidates are listed with their stored qvina score (Vina-family scoring function value in kcal/mol, " +
  "not an affinity); a candidate without a score is listed without one, which is not zero. ";
const RDK = "Property values are RDKit estimates, not measurements or interactions. ";
const GEO = "Distances and neighbor lists are geometry from stored coordinates, not measurements or interactions. ";
const NC = "Each score belongs to the modelled structure of its own mutation, so scores are not like-for-like comparisons. ";
const INSTRUCTIONS = {
  "ligand|explore": C + "Prefer the candidate whose structure (SMILES) is most different from all the computed " +
    "candidates; if no candidate is computed, choose any one. " + E + RDK + O,
  "ligand|exploit": C + "Prefer the candidate whose structure (SMILES) is most similar to the one computed candidate " +
    "with the lowest listed score; if no candidate has a listed score, choose any one. This is a judgment of structural " +
    "similarity only, not a prediction of any score. " + S + RDK + O,
  "mutation|explore": C + "Prefer the candidate whose position and substitution (from, to) are most different from all " +
    "the computed candidates; if no candidate is computed, choose any one. " + E + GEO + O,
  "mutation|exploit": C + "Prefer the candidate whose position and substitution (from, to) are most similar to the one " +
    "computed candidate with the lowest listed score; if no candidate has a listed score, choose any one. This is a " +
    "judgment of similarity of position and substitution only, not a prediction of any score or of the effect of a " +
    "mutation. " + S + NC + GEO + O,
};
const LIGAND_VALUES_NOTE = "RDKit estimates, not measurements; PAINS matches are structural alerts only; no receptor or " +
  "pocket information is included";
const LIGAND_EXPLOIT_SUFFIX = "; scores are stored qvina values from one fixed receptor and box";
const MUTATION_EXPLOIT_SUFFIX = "; each score belongs to the modelled structure of its own mutation";
const WIRE_SCHEMA = { ligand: "jev_loop_ligand_candidates@1", mutation: "jev_loop_mutation_candidates@1" };
const WIRE_TOP = {
  ligand: ["candidates", "computed", "goal", "parent", "property_methods", "schema", "task", "values_note"],
  mutation: ["candidates", "computed", "goal", "pockets", "positions", "protection_checks", "schema", "task",
    "values_note"],
};
// Spec 2 and 8.3 wording (a proposal is never a rank, recommendation, prediction or improvement; no comparison of
// scores). "점수" is allowed (the qvina score is shown); "최적화" is a process; "비활성" is not "활성". A line exactly equal
// to a fixed line is exempt and the exact score names are removed first (they say 친화도가 아님).
const FORBIDDEN = /순위|추천|최고|최저|최적(?!화)|최솟값|최댓값|개선|예측|유망|좋은|나쁜|좋아짐|승자|평균|차이|증감|친화|안정성|ΔΔG|(?<!비)활성|가장\s*높|가장\s*낮|\bbest|\brank|recommend|improv|winner|highest|lowest|효과|편향|\beffects?\b|\bbias(?:es|ed)?\b/gi;
const LATE_TEXT = "동의 끈 뒤 도착";
const ACK_KEYS = ["keep_input_protonation", "tool_assigned_types_charges", "rigid_no_optimization"];
// Ligand computation values: the M22 T1 small-pool docking values (manual 12 Å box, exhaustiveness 1, num_modes 2).
const LIGAND_SETUP = { model: "1", center: ["3.41", "0.72", "11.31"], size: ["12", "12", "12"], seed: "1",
  exhaustiveness: "1", numModes: "2", energyRange: "3" };
// Protein computation values: the M25 T6 test values (ligand range box 8 Å around the phenol SDF, exhaustiveness 1).
const PROTEIN_SETUP = { margin: "8", seed: "20261007", exhaustiveness: "1", numModes: "2", energyRange: "3" };
const PROTEIN_POOL = [4, 10, 14];           // L15A, I30A, I44A of the 1UBQ set (qa_setup.py modelPool)
const LOOP_A = { goal: "exploit", seed: "7", cap: "3", size: 5 };
const LOOP_B = { goal: "explore", seed: "99", cap: "2" };
const LOOP_C = { goal: "exploit", seed: "5", cap: "2" };
const LOOP_P = { goal: "explore", seed: "11", cap: "2" };

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const enc = encodeURIComponent;
const attr = (name, value) => `[${name}="${String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"]`;
const masked = text => (text ?? "").replace(/\d+(?:[.,]\d+)*/g, "#").replace(/[ \t]+/g, " ").trim();

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, "runs-dir": null, control: null, setup: null,
    plan: null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2);
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode) || !value["runs-dir"] || !value.setup ||
      (value.mode === "fixture" && !value.control) || (value.mode !== "fixture" && !value.plan))
    throw new Error(`Usage: jev-loop-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> --runs-dir <backend MW_RUNS_DIR> ` +
      "--setup <json> [--control <fixture control dir> (fixture: required; calibrate/live: the rehearsal against the " +
      "fixture server)] [--plan <json> (calibrate, live)] [--url http://127.0.0.1:3000]. The setup and plan files are " +
      "written by scripts/m25_offscreen_acceptance.py, which also starts the services and counts the real calls.");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  for (const key of ["artifacts", "runs-dir", "control", "setup", "plan"]) if (value[key]) value[key] = path.resolve(value[key]);
  value.url = new URL("/", value.url).toString();
  return value;
}

// ------------------------------------------------------------------ independent oracle helpers
function expectedLimitations(kind, goal, { late = false, ended = false, uncomputed = false } = {}) {
  return [LJ.LJ1, LJ.LJ2, LJ.LJ3, goal === "exploit" ? LJ.LJ4 : LJ.LJ5, kind === "ligand" ? LJ.LJ6 : LJ.LJ7,
    ...(ended && uncomputed ? [LJ.LJ8] : []), ...(late ? [J.J7] : [])];
}
/** Spec 4.3: every not-unavailable pool candidate by sha256(f"{seed}:{iteration}:{ordinal}:{ref}") ascending (ties:
 * pool order), aliases c01…/m01… in that order. `record` is the loop record read right before the projection. */
function oracleOrder(record, iteration, ordinal) {
  const kind = record.branch === "ligand" ? "ligand" : "mutation";
  const rows = record.candidates.map((row, position) => ({ ref: row.ref, state: row.state, score: row.score_kcal_mol,
    position })).filter(row => row.state !== "unavailable")
    .map(row => ({ ...row, key: sha(Buffer.from(`${record.loop_seed}:${iteration}:${ordinal}:${String(row.ref)}`, "ascii")) }));
  rows.sort((a, b) => a.key < b.key ? -1 : a.key > b.key ? 1 : a.position - b.position);
  const prefix = kind === "ligand" ? "c" : "m";
  const order = rows.map((row, i) => ({ alias: `${prefix}${String(i + 1).padStart(2, "0")}`, ref: row.ref, state: row.state,
    score: row.score }));
  const criteria = order.filter(row => row.state === "pending").map(row => row.alias);
  const computed = order.filter(row => row.state !== "pending").map(row => record.goal === "exploit"
    ? { alias: row.alias, state: row.state === "scored" ? "scored" : "no_score",
      score_kcal_mol: row.state === "scored" ? row.score : null }
    : { alias: row.alias });
  return { kind, order, criteria, computed };
}
/** Forbidden expressions in text, line by line (fixed lines and `exempt` lines skipped, exact score names removed). */
function forbiddenWords(text, exempt = []) {
  const found = [];
  for (const line of String(text ?? "").split("\n")) {
    if (FIXED_LINES.includes(line) || exempt.includes(line)) continue;
    const checked = line.split(SCORE_LABEL).join("").split(SCORE_COLUMN).join("");
    for (const match of checked.matchAll(FORBIDDEN)) found.push(match[0]);
  }
  return found;
}
function strings(value, out = []) {
  if (typeof value === "string") out.push(value);
  else if (Array.isArray(value)) for (const item of value) strings(item, out);
  else if (value && typeof value === "object") for (const [key, item] of Object.entries(value)) { out.push(key); strings(item, out); }
  return out;
}
function keysOf(value, out = []) {
  if (Array.isArray(value)) for (const item of value) keysOf(item, out);
  else if (value && typeof value === "object") for (const [key, item] of Object.entries(value)) { out.push(key); keysOf(item, out); }
  return out;
}

// ------------------------------------------------------------------ read-only observation
async function readApi(page, route) {
  const response = await page.request.get(new URL(`/api${route}`, page.url()).toString());
  assert.equal(response.status(), 200, `${route}: ${await response.text()}`);
  return response.json();
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
function eventCount(runsDir, run, type) { return runEvents(runsDir, run).filter(event => event.type === type).length; }
function dispatchCounts(runsDir) {
  const counts = {};
  for (const name of fs.readdirSync(runsDir)) {
    const file = path.join(runsDir, name, "events.jsonl");
    if (!/^run_[0-9a-f]+$/.test(name) || !fs.existsSync(file)) continue;
    counts[name] = runEvents(runsDir, name).filter(event => event.type === "jev_science_dispatch_started").length;
  }
  return counts;
}
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
    try { last = await probe(); if (last) return last; } catch (error) { last = String(error); }
    await page.waitForTimeout(150);
  }
  throw new Error(`${label}: timed out; last=${JSON.stringify(last)?.slice(0, 800)}`);
}
async function viewerSnapshot(page) {
  return page.evaluate(() => typeof window.__protviewQaSnapshot === "function" ? window.__protviewQaSnapshot() : null);
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
/** Renderer requests (every one) and the JSON answers of the API writes and previews (read from the response events). */
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
const posts = (log, since) => log.rows.filter(row => row.at >= since && row.method === "POST" && row.api).map(row => row.path);
const gets = (log, since) => [...new Set(log.rows.filter(row => row.at >= since && row.method === "GET" && row.api)
  .map(row => row.path))];
/** The first POST answer (JSON read) after `since` whose path and request satisfy `match`. */
async function waitApi(page, log, since, match, label, timeout = 120000) {
  return waitFor(page, async () => log.api.find(entry => entry.at >= since && entry.json !== undefined &&
    match(entry)) ?? null, label, timeout);
}

// ------------------------------------------------------------------ evidence
function recorder(session, input, evidence) {
  const { app, page, artifacts } = session;
  const file = path.join(artifacts, `jev-loop-${input.mode}.jsonl`);
  const append = row => fs.appendFileSync(file, JSON.stringify(row) + "\n");
  const caseRows = {};
  const mark = (cases, ok) => { for (const id of cases) (caseRows[id] ??= []).push(ok); };
  async function shownText() {
    return page.evaluate(() => {
      const tab = document.querySelector('.mw-app-tabs [role="tab"][aria-selected="true"]');
      const panel = tab ? document.getElementById(tab.getAttribute("aria-controls") ?? "") : null;
      return panel ? panel.innerText : document.body.innerText;
    }).catch(() => null);
  }
  async function step(caseId, cases, description, action, check) {
    const started = Date.now();
    let result;
    try {
      result = await action();
      const assertion = await check(result);
      const proof = await capture(app, page, artifacts, caseId);
      assert.equal(proof.status.blockedRequests.length, 0, "renderer attempted a non-loopback request");
      assert.equal(proof.status.offscreen, true);
      const text = await shownText();
      if (text !== null) fs.writeFileSync(path.join(artifacts, `${caseId}.dom.txt`), text);
      append({ caseId, cases, status: "pass", description, assertion: summarize(assertion),
        blockedRequests: proof.status.blockedRequests.length, paintCount: proof.status.paintCount,
        screenshot: fileRecord(proof.screenshot), paint: fileRecord(proof.paint.path),
        domText: text === null ? null : fileRecord(path.join(artifacts, `${caseId}.dom.txt`)), durationMs: Date.now() - started });
      mark(cases, true);
      return assertion;
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* keep the primary failure */ }
      const html = await page.evaluate(() => [...document.querySelectorAll('[data-testid="jev-loop-panel"]')]
        .map(node => node.outerHTML).join("\n").slice(0, 400000)).catch(() => null);
      if (html) fs.writeFileSync(path.join(artifacts, `${caseId}-failure.panel.html`), html);
      append({ caseId, cases, status: "fail", description, error: String(error.stack ?? error),
        actionResult: result === undefined ? null : summarize(result), screenshot: proof && fileRecord(proof.screenshot),
        paint: proof && fileRecord(proof.paint.path), durationMs: Date.now() - started });
      mark(cases, false);
      throw error;
    }
  }
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
  return { step, part, append, file, cases, mark };
}
function fileRecord(file) {
  return file && fs.existsSync(file) ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) }
    : { path: file ?? null, missing: true };
}
/** The JSON summary of a step's value; the exact outgoing body and the fixed question text are left out (they are
 * checked byte for byte where they are read and sit whole in the stored projection). */
const OMITTED_TEXT = new Set(["body", "instructions", "question"]);
function summarize(value) {
  try {
    const text = JSON.stringify(value, (key, item) => OMITTED_TEXT.has(key) && typeof item === "string"
      ? `<omitted ${item.length} characters>` : item);
    return text.length > 12000 ? `${text.slice(0, 12000)}…` : JSON.parse(text);
  } catch { return String(value); }
}
function control(evidence, id, observed) { (evidence.controls[id] ??= []).push(observed); }

// ------------------------------------------------------------------ tabs, runs
const tabButton = (page, label) => page.locator(".mw-app-tabs").getByRole("tab", { name: label, exact: true });
async function selectTab(page, label) {
  await tabButton(page, label).click();
  await waitFor(page, async () => await tabButton(page, label).getAttribute("aria-selected") === "true", `${label} selected`, 10000);
}
const globalRun = page => page.evaluate(() => document.querySelector(".mw-app-run")?.getAttribute("data-global-run") || null);
async function waitForBoot(page) {
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "새 run");
    return !!button && !button.disabled && /^run_/.test(new URL(location.href).searchParams.get("run") ?? "");
  }, null, { timeout: 45000 });
}
async function chooseRun(page, run) {
  await selectTab(page, TAB.structure);
  await page.getByRole("tab", { name: /^run/i }).click();
  if (await globalRun(page) !== run) await page.locator("#run-choice").selectOption(run);
  await waitFor(page, async () => await globalRun(page) === run, `run ${run} selected`, 30000);
  return waitFor(page, async () => {
    const value = await viewerSnapshot(page);
    return value?.ready === true && value.sourceHandle && value.catalogReady === true ? value : null;
  }, `run ${run} viewer ready`, 90000);
}
async function globalLine(page) {
  return page.evaluate(() => {
    const run = document.querySelector(".mw-app-bar .mw-app-run");
    const badge = document.querySelector(".mw-app-bar .mw-app-science");
    return { runText: run?.textContent ?? null, badge: badge ? { text: badge.textContent.trim(),
      afterRun: run?.nextElementSibling === badge } : null };
  });
}
async function structureHidden(page) {
  return page.evaluate(() => { const node = document.getElementById("mw-app-panel-structure");
    return node ? { shown: node.getAttribute("data-shown"), inert: node.inert } : null; });
}
/** The areas of one tab (data-testid ending in -panel) with their digit-masked text once settled (no busy element,
 * text stable over two reads 0.7 s apart); the JEV loop area is listed but its text is not kept. */
async function tabAreas(page, branch, log) {
  const since = Date.now();
  await selectTab(page, TAB[branch]);
  const panel = page.locator(`#mw-app-panel-${branch}`);
  await panel.waitFor({ timeout: 15000 });
  const read = () => panel.evaluate(node => [...node.querySelectorAll(':scope > div > [data-testid$="-panel"]')]
    .map(item => ({ id: item.getAttribute("data-testid"), branch: item.getAttribute("data-branch"),
      text: item.getAttribute("data-testid") === "jev-loop-panel" ? null : item.innerText })));
  const areas = await waitFor(page, async () => {
    if (await panel.locator('[aria-busy="true"]').count()) return null;
    const a = await read();
    await page.waitForTimeout(700);
    const b = await read();
    return JSON.stringify(a) === JSON.stringify(b) && !(await panel.locator('[aria-busy="true"]').count()) ? b : null;
  }, `${branch} tab settled`, 90000);
  return { branch, areas: areas.map(item => ({ ...item, text: item.text === null ? null : masked(item.text) })),
    posts: posts(log, since), structure: await structureHidden(page) };
}
/** Areas compared one by one; `listing` areas list run results the loop's standalone jobs add (their change is kept). */
function compareAreas(before, after, listing) {
  const out = { order: { before: before.areas.map(item => item.id), after: after.areas.map(item => item.id) }, areas: {} };
  for (const item of before.areas) {
    if (item.text === null) continue;
    const other = after.areas.find(next => next.id === item.id);
    const same = !!other && other.text === item.text;
    const added = other ? other.text.split("\n").filter(line => !item.text.split("\n").includes(line)).slice(0, 12) : null;
    const removed = other ? item.text.split("\n").filter(line => !other.text.split("\n").includes(line)).slice(0, 12) : null;
    out.areas[item.id] = { same, listing: listing.includes(item.id), added, removed };
  }
  return out;
}

// ------------------------------------------------------------------ the JEV loop area (real input; read-only helpers)
const lp = (page, branch) => page.locator(`#mw-app-panel-${branch} [data-testid="jev-loop-panel"]${attr("data-branch", branch)}`);
const lt = (page, branch, id) => lp(page, branch).locator(`[data-testid="${id}"]`);
const larea = (page, branch, name) => lp(page, branch).locator(`[data-jev-loop-area="${name}"]`);
const panelText = (page, branch) => lp(page, branch).evaluate(node => node.innerText);
async function openLoopArea(page, branch, log) {
  const since = Date.now();
  await selectTab(page, TAB[branch]);
  await lp(page, branch).waitFor({ timeout: 30000 });
  await waitFor(page, async () => {
    const state = await lp(page, branch).getAttribute("data-jev-loop-state");
    if (!["ready", "empty"].includes(state)) return null;
    if (await larea(page, branch, "status").getAttribute("data-state") !== "ready") return null;
    if (await lp(page, branch).locator('[data-jev-loop-field="pool"] [aria-busy="true"]').count()) return null;
    if (await lp(page, branch).locator('[data-jev-loop-field="setup"] [aria-busy="true"]').count()) return null;
    return true;
  }, `${branch} loop area ready`, 60000);
  return since;
}
async function consentState(page, branch) { return lt(page, branch, "jev-loop-consent-label").getAttribute("data-consent"); }
async function setConsent(page, branch, run, on, log, evidence) {
  if ((await consentState(page, branch) === "on") === on) return null;
  const since = Date.now();
  await lt(page, branch, "jev-loop-consent").click();
  const entry = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev/consent`, "consent answer", 30000);
  assert.equal(entry.status, 200, JSON.stringify(entry.json));
  assert.equal(entry.json.enabled, on);
  await waitFor(page, async () => await consentState(page, branch) === (on ? "on" : "off") ? true : null, "consent shown", 15000);
  control(evidence, "jev-loop-consent", { run, enabled: on });
  return entry.json;
}
const sourceRadio = (page, branch, handle) =>
  lp(page, branch).locator(`input[data-testid="jev-loop-source"]${attr("data-jev-loop-source", handle)}`);
async function listedSources(page, branch) {
  return lp(page, branch).locator('input[data-testid="jev-loop-source"]').evaluateAll(items =>
    items.map(item => ({ handle: item.getAttribute("data-jev-loop-source"), checked: item.checked })));
}
async function rowKeys(page, branch) {
  return lp(page, branch).locator("tr[data-jev-loop-candidate-row]").evaluateAll(items => items.map(item => ({
    key: item.getAttribute("data-jev-loop-candidate-row"), checked: item.getAttribute("data-checked") === "true",
    blocked: item.getAttribute("data-blocked-reason") })));
}
async function chooseSource(page, branch, handle, count, evidence) {
  const radio = sourceRadio(page, branch, handle);
  await radio.waitFor({ timeout: 30000 });
  if (!(await radio.isChecked())) await radio.check();
  control(evidence, `jev-loop-source-${branch}`, { handle });
  return waitFor(page, async () => {
    if (await lt(page, branch, "jev-loop-candidates").count() !== 1) return null;
    const rows = await rowKeys(page, branch);
    return rows.length === count ? rows : null;
  }, `${branch} candidate rows`, 30000);
}
const candidateBox = (page, branch, key) =>
  lp(page, branch).locator(`input[data-testid="jev-loop-candidate"]${attr("data-jev-loop-candidate", key)}`);
async function checkKeys(page, branch, keys, evidence) {
  for (const key of keys) {
    const box = candidateBox(page, branch, key);
    if (!(await box.isChecked())) await box.check();
    control(evidence, "jev-loop-candidate", { key: String(key) });
  }
}
async function uncheckAll(page, branch, evidence) {
  await uncheckKeys(page, branch, (await rowKeys(page, branch)).filter(row => row.checked).map(row => row.key), evidence);
}
async function uncheckKeys(page, branch, keys, evidence) {
  for (const key of keys) {
    const box = candidateBox(page, branch, key);
    if (await box.isChecked()) await box.uncheck();
    control(evidence, "jev-loop-candidate-uncheck", { key: String(key) });
  }
}
async function poolCount(page, branch) {
  return (await lt(page, branch, "jev-loop-pool-count").count())
    ? Number(await lt(page, branch, "jev-loop-pool-count").getAttribute("data-selected")) : null;
}
async function fieldErrors(page, branch) {
  const out = {};
  for (const field of ["general", "pool", "goal", "loop_seed", "iteration_cap", "setup"]) {
    const node = lt(page, branch, `jev-loop-errors-${field}`);
    if (!(await node.count())) { out[field] = { items: [], refusal: null }; continue; }
    const refusal = node.locator('[data-testid="jev-loop-create-refusal"]');
    out[field] = { items: await node.locator("li").evaluateAll(items => items.map(item => item.textContent.trim())),
      refusal: (await refusal.count()) ? { code: await refusal.getAttribute("data-reason-code"),
        field: await refusal.getAttribute("data-field"), text: clean(await refusal.textContent()) } : null };
  }
  return out;
}
async function fill(page, branch, id, value, evidence) {
  await lt(page, branch, id).fill(String(value));
  control(evidence, id, { value: String(value) });
}
async function setGoal(page, branch, goal, evidence) {
  await lt(page, branch, `jev-loop-goal-${goal}`).check();
  control(evidence, "jev-loop-goal", { goal });
}
async function settings(page, branch, values, evidence) {
  if (values.goal) await setGoal(page, branch, values.goal, evidence);
  if (values.seed !== undefined) await fill(page, branch, "jev-loop-seed", values.seed, evidence);
  if (values.cap !== undefined) await fill(page, branch, "jev-loop-iteration-cap", values.cap, evidence);
}
/** Ligand setup: parent SDF, receptor (model 1, 없음, PDB CONECT), manual box, free docking values, acknowledgements. */
async function ligandSetupInputs(page, setupRun, evidence) {
  const b = "ligand";
  await lt(page, b, "jev-loop-parent-sdf").waitFor({ timeout: 30000 });
  await waitFor(page, async () => await lt(page, b, "jev-loop-parent-sdf").locator(`option${attr("value", setupRun.parent)}`)
    .count() ? true : null, "parent SDF listed", 30000);
  await lt(page, b, "jev-loop-parent-sdf").selectOption(setupRun.parent);
  control(evidence, "jev-loop-parent-sdf", { handle: setupRun.parent });
  await lt(page, b, "jev-loop-receptor").selectOption(setupRun.receptor);
  control(evidence, "jev-loop-receptor", { handle: setupRun.receptor });
  await lt(page, b, "jev-loop-model").waitFor({ timeout: 30000 });
  await lt(page, b, "jev-loop-model").selectOption(LIGAND_SETUP.model);
  control(evidence, "jev-loop-model", { model: LIGAND_SETUP.model });
  await lt(page, b, "jev-loop-instances").waitFor({ timeout: 30000 });
  await lp(page, b).locator('[data-testid="jev-loop-instances"] label[data-jev-loop-instance="none"] input').check();
  control(evidence, "jev-loop-instance", { instance: "none" });
  await lt(page, b, "jev-loop-connectivity").locator("label").filter({ hasText: "PDB CONECT" }).locator("input").check();
  control(evidence, "jev-loop-connectivity", { kind: "pdb_conect" });
  await lp(page, b).locator('label[data-jev-loop-box="manual"] input').check();
  control(evidence, "jev-loop-box", { source: "manual" });
  for (const [i, axis] of ["x", "y", "z"].entries()) {
    await fill(page, b, `jev-loop-center-${axis}`, LIGAND_SETUP.center[i], evidence);
    await fill(page, b, `jev-loop-size-${axis}`, LIGAND_SETUP.size[i], evidence);
  }
  await fill(page, b, "jev-loop-docking-seed", LIGAND_SETUP.seed, evidence);
  await fill(page, b, "jev-loop-exhaustiveness", LIGAND_SETUP.exhaustiveness, evidence);
  await fill(page, b, "jev-loop-num-modes", LIGAND_SETUP.numModes, evidence);
  await fill(page, b, "jev-loop-energy-range", LIGAND_SETUP.energyRange, evidence);
  for (const key of ACK_KEYS) {
    await lp(page, b).locator(`label[data-jev-loop-ack="${key}"] input`).check();
    control(evidence, `jev-loop-ack-${key}`, { checked: true });
  }
}
/** Protein setup: the two literal confirmations, cutoff, the 3D SDF, ligand-range box, free docking values, acks. */
async function proteinSetupInputs(page, setupRun, evidence, { confirm = true, cutoff = "4.0" } = {}) {
  const b = "protein";
  if (confirm) {
    await lt(page, b, "jev-loop-confirm-selection").check();
    await lt(page, b, "jev-loop-confirm-hydrogen").check();
    control(evidence, "jev-loop-confirmations", { checked: true });
  }
  await fill(page, b, "jev-loop-cutoff", cutoff, evidence);
  await lp(page, b).locator('[data-testid="jev-loop-setup-ligand-source"] label[data-pair-ligand-source="sdf"] input').check();
  await waitFor(page, async () => await lt(page, b, "jev-loop-setup-sdf").locator(`option${attr("value", setupRun.phenol)}`)
    .count() ? true : null, "phenol SDF listed", 30000);
  await lt(page, b, "jev-loop-setup-sdf").selectOption(setupRun.phenol);
  control(evidence, "jev-loop-setup-sdf", { handle: setupRun.phenol });
  await lp(page, b).locator('[data-testid="jev-loop-setup-box-source"] label[data-pair-box="ligand_range"] input').check();
  control(evidence, "jev-loop-setup-box", { source: "ligand_range" });
  await fill(page, b, "jev-loop-setup-margin", PROTEIN_SETUP.margin, evidence);
  await fill(page, b, "jev-loop-setup-seed", PROTEIN_SETUP.seed, evidence);
  await fill(page, b, "jev-loop-setup-exhaustiveness", PROTEIN_SETUP.exhaustiveness, evidence);
  await fill(page, b, "jev-loop-setup-num-modes", PROTEIN_SETUP.numModes, evidence);
  await fill(page, b, "jev-loop-setup-energy-range", PROTEIN_SETUP.energyRange, evidence);
  for (const key of ACK_KEYS) {
    await lp(page, b).locator(`[data-testid="jev-loop-setup-acknowledgement"] label[data-pair-ack="${key}"] input`).check();
    control(evidence, `jev-loop-setup-ack-${key}`, { checked: true });
  }
}
async function createLoop(page, branch, run, log, evidence) {
  await waitFor(page, async () => await lt(page, branch, "jev-loop-create").isEnabled() ? true : null, "create enabled", 15000);
  const since = Date.now();
  await lt(page, branch, "jev-loop-create").click();
  control(evidence, "jev-loop-create", { run, branch });
  const entry = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev_loops`, "create answer", 120000);
  return entry;
}
async function recordAttrs(page, branch) {
  const node = lt(page, branch, "jev-loop-record");
  if (!(await node.count())) return null;
  return { loopId: await node.getAttribute("data-loop-id"), status: await node.getAttribute("data-status"),
    action: await node.getAttribute("data-action"), phase: await node.getAttribute("data-phase"),
    iteration: await node.getAttribute("data-iteration"), step: await node.getAttribute("data-step") };
}
async function recordWhen(page, branch, ok, label, timeout = 60000) {
  return waitFor(page, async () => { const value = await recordAttrs(page, branch); return value && ok(value) ? value : null; },
    label, timeout);
}
const readLoop = (page, run, loopId) => readApi(page, `/runs/${run}/jev_loops/${enc(loopId)}`);
/** 보낼 내용 만들기: the build_jev_loop_projection command and the preview read that follows (both from the screen). */
async function build(page, branch, run, log, evidence) {
  const since = Date.now();
  await waitFor(page, async () => await lt(page, branch, "jev-loop-build").isEnabled() ? true : null, "build enabled", 15000);
  await lt(page, branch, "jev-loop-build").click();
  control(evidence, "jev-loop-build", { run, branch });
  const command = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/commands` &&
    item.request?.tool === "build_jev_loop_projection", "projection command", 120000);
  assert.equal(command.status, 200, JSON.stringify(command.json).slice(0, 600));
  assert.equal(command.json.ok, true, JSON.stringify(command.json).slice(0, 600));
  const handle = command.json.handle.handle;
  const previewed = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev/preview` &&
    item.request?.projection === handle, "preview answer", 60000);
  assert.equal(previewed.status, 200);
  await lp(page, branch).locator(`[data-testid="jev-loop-preview"]${attr("data-projection-handle", handle)}`)
    .waitFor({ timeout: 30000 });
  return { request: command.request, handle, summary: command.json.handle.summary, preview: previewed.json };
}
async function previewShown(page, branch) {
  const box = lt(page, branch, "jev-loop-preview");
  return { handle: await box.getAttribute("data-projection-handle"), sha256: await box.getAttribute("data-body-sha256"),
    bytes: Number(await box.getAttribute("data-body-bytes")), blockedAttr: await box.getAttribute("data-blocked"),
    blocked: await lt(page, branch, "jev-loop-preview-blocked").locator("li[data-block-reason]").evaluateAll(items =>
      items.map(item => ({ code: item.getAttribute("data-block-reason"), text: item.textContent.trim() }))),
    loopBlocks: await lt(page, branch, "jev-loop-preview-blocked").locator("li[data-loop-block]").evaluateAll(items =>
      items.map(item => ({ code: item.getAttribute("data-loop-block"), text: item.textContent.trim() }))),
    previous: Number(await lt(page, branch, "jev-loop-preview-previous").getAttribute("data-previous-sends")),
    aliases: await lt(page, branch, "jev-loop-alias-table").locator("tr[data-alias]").evaluateAll(items =>
      items.map(item => ({ alias: item.getAttribute("data-alias"), cells: [...item.cells].map(cell => cell.textContent.trim()) }))),
    question: clean(await lt(page, branch, "jev-loop-preview-question").textContent()),
    order: clean(await lt(page, branch, "jev-loop-preview-order").textContent()),
    body: await lt(page, branch, "jev-loop-preview-body").textContent() };
}
async function previewWhen(page, branch, handle, ok, label) {
  return waitFor(page, async () => {
    if (!(await lt(page, branch, "jev-loop-preview").count())) return null;
    const shown = await previewShown(page, branch);
    return shown.handle === handle && ok(shown) ? shown : null;
  }, label, 30000);
}
/** Body identity (<pre> = server preview string = SHA-256 here = shown = stored) and the order oracle (spec 4.3-4.5). */
function previewMatches({ shown, built, stored, record, iteration, ordinal, runId }) {
  const kind = record.branch === "ligand" ? "ligand" : "mutation";
  const bytes = Buffer.from(shown.body, "utf8");
  assert.equal(shown.body, built.preview.body, "<pre> text differs from the server preview body");
  assert.equal(sha(bytes), built.preview.body_sha256);
  assert.equal(bytes.length, built.preview.body_bytes);
  assert.equal(shown.sha256, built.preview.body_sha256);
  assert.equal(shown.bytes, built.preview.body_bytes);
  assert.equal(stored.schema, "jev_loop_projection@1");
  assert.equal(stored.body_sha256, built.preview.body_sha256, "stored projection body hash");
  assert.equal(stored.body_bytes, built.preview.body_bytes);
  assert.ok(built.preview.body_bytes <= 65536);
  assert.deepEqual(stored.loop, { loop_id: record.loop_id, iteration, send_ordinal: ordinal });
  assert.deepEqual(stored.order, { algorithm: "sha256_order_v1", loop_seed: record.loop_seed, iteration, send_ordinal: ordinal });
  assert.deepEqual(built.summary.send_ordinal, ordinal);
  // the order oracle
  const oracle = oracleOrder(record, iteration, ordinal);
  assert.deepEqual(stored.selection, oracle.order.map(row => ({ alias: row.alias, ref: row.ref, state: row.state })),
    "stored selection differs from the independent sha256_order_v1 order");
  const body = JSON.parse(shown.body);
  assert.deepEqual(Object.keys(body).sort(), ["model", "provider", "questions", "state"]);
  assert.equal(body.model, REQUEST_MODEL);
  assert.deepEqual(body.provider, PROVIDER);
  assert.deepEqual(body.state, stored.wire, "body state differs from the stored wire");
  assert.equal(body.state.schema, WIRE_SCHEMA[kind]);
  assert.equal(body.state.goal, record.goal);
  assert.equal(body.state.task, "choose_one_candidate");
  assert.ok(Object.keys(body.state).every(key => WIRE_TOP[kind].includes(key)), Object.keys(body.state).join(","));
  assert.deepEqual(body.state.candidates.map(item => item.alias), oracle.order.map(row => row.alias));
  assert.deepEqual(body.state.computed, oracle.computed, "computed rows differ from the oracle (goal shape, raw score)");
  if (kind === "ligand") assert.equal(body.state.values_note, LIGAND_VALUES_NOTE +
    (record.goal === "exploit" ? LIGAND_EXPLOIT_SUFFIX : ""));
  else assert.equal(body.state.values_note.endsWith(MUTATION_EXPLOIT_SUFFIX), record.goal === "exploit");
  const question = body.questions.candidate_choice;
  assert.deepEqual(Object.keys(body.questions), ["candidate_choice"]);
  assert.equal(question.type, "choice");
  assert.equal(question.instructions, INSTRUCTIONS[`${kind}|${record.goal}`], "instructions are not the spec 4.5 text");
  assert.deepEqual(Object.keys(question.criteria), oracle.criteria, "criteria are not the not-yet-computed aliases in order");
  for (const alias of oracle.criteria) assert.equal(question.criteria[alias], `Candidate ${alias}.`);
  assert.equal(shown.question, INSTRUCTIONS[`${kind}|${record.goal}`]);
  assert.equal(shown.order, `후보 순서·별칭: sha256_order_v1로 섞음 · 루프 seed ${record.loop_seed} · 바퀴 ${iteration} · ` +
    `전송 순번 ${ordinal}`);
  // the alias table (local, not sent) = the stored selection
  assert.deepEqual(shown.aliases.map(row => row.alias), oracle.order.map(row => row.alias));
  for (const [i, row] of oracle.order.entries()) {
    assert.ok(shown.aliases[i].cells[1].includes(String(row.ref)), `alias row ${row.alias}: ${shown.aliases[i].cells[1]}`);
    assert.equal(shown.aliases[i].cells[5], "전송하지 않음");
  }
  // what never goes out (spec 4.4): handles, run id, loop id, candidate ids, paths, receptor/pocket (ligand)
  for (const forbidden of ["obj://", runId, record.loop_id, "/Users/", "handle", "loop_seed"])
    assert.ok(!shown.body.includes(forbidden), `body carries ${forbidden}`);
  assert.ok(!/c_[0-9a-f]{16}/.test(shown.body), "body carries a candidate id");
  const keys = keysOf(body.state);
  if (kind === "ligand") assert.deepEqual(keys.filter(key => /pocket|receptor|structure|coordinate|residue|neighbor/i.test(key)), []);
  assert.deepEqual(keys.filter(key => /coord|xyz|sequence|numbering|accession|path|smarts|seed/i.test(key)), []);
  return { bodySha256: built.preview.body_sha256, bodyBytes: built.preview.body_bytes, ordinal,
    order: oracle.order.map(row => `${row.alias}=${row.ref}:${row.state}`), criteria: oracle.criteria,
    computed: oracle.computed, reservation: built.preview.reservation };
}
async function sendState(page, branch) {
  return { enabled: await lt(page, branch, "jev-loop-send").isEnabled(),
    confirmEnabled: await lt(page, branch, "jev-loop-confirm").isEnabled(),
    confirmed: await lt(page, branch, "jev-loop-confirm").isChecked(),
    blockers: (await lt(page, branch, "jev-loop-send-blockers").count())
      ? await lt(page, branch, "jev-loop-send-blockers").locator("li").evaluateAll(items => items.map(item => item.textContent.trim()))
      : [] };
}
/** Confirmation, then 이 내용을 JEV로 보냅니다 (one click); `during` runs while the request is in flight and `onRecord`
 * gets the send record as soon as it arrives. `controlDir` null = the real gate (no fixture script, no transport rows). */
async function confirmAndSend(page, branch, run, controlDir, script, log, evidence, during = null, onRecord = null) {
  if (controlDir) writeScript(controlDir, script);
  if (!(await lt(page, branch, "jev-loop-confirm").isChecked())) await lt(page, branch, "jev-loop-confirm").check();
  await waitFor(page, async () => await lt(page, branch, "jev-loop-send").isEnabled() ? true : null, "send enabled", 15000);
  const callsBefore = controlDir ? fixtureCalls(controlDir).length : 0;
  const since = Date.now();
  await lt(page, branch, "jev-loop-send").click();
  control(evidence, "jev-loop-send", { run, script });
  const extra = during ? await during() : null;
  const entry = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev/sends`, "send answer", 120000);
  assert.equal(entry.status, 200, JSON.stringify(entry.json));
  const record = entry.json;
  if (onRecord) onRecord(record);
  await lp(page, branch).locator(`[data-testid="jev-loop-send-record"]${attr("data-send-id", record.send_id)}`)
    .waitFor({ timeout: 30000 });
  const calls = controlDir ? fixtureCalls(controlDir).slice(callsBefore) : null;
  return { request: entry.request, record, extra, calls };
}
/** Server-side byte comparisons of every send (written to jev-loop-bytes.json). */
const BYTE_LOG = [];
/** The send's audit `prepared` body = the preview body; its payload hash = the preview hash; one dispatch; and, with
 * the fixture server (`calls` not null), the bytes its transport received. */
function serverBytes(runsDir, run, sendId, shownBody, bodySha, calls) {
  const events = runEvents(runsDir, run);
  const prepared = events.filter(event => event.type === "egress" && event.stage === "prepared" && event.send_id === sendId);
  assert.equal(prepared.length, 1, `prepared audits of ${sendId}`);
  assert.equal(prepared[0].scope, "science");
  assert.equal(prepared[0].payload_sha256, bodySha);
  assert.deepEqual(prepared[0].body, JSON.parse(shownBody), "prepared audit body differs from the preview body");
  const dispatched = events.filter(event => event.type === "jev_science_dispatch_started" && event.send_id === sendId);
  assert.equal(dispatched.length, 1);
  const call = calls === null ? null : calls[0];
  if (calls !== null) {
    assert.equal(calls.length, 1, "fixture transport calls of this send");
    assert.equal(call.bodySha256, bodySha, "transport bytes differ from the preview");
    assert.equal(call.bodyBytes, Buffer.byteLength(shownBody, "utf8"));
    assert.equal(call.authorizationIsSentinel, true);
  }
  const row = { run, sendId, script: call?.script ?? null, previewSha256: bodySha,
    previewBytes: Buffer.byteLength(shownBody, "utf8"), preparedSha256: prepared[0].payload_sha256, preparedBodyEqual: true,
    transportSha256: call?.bodySha256 ?? null, transportBytes: call?.bodyBytes ?? null,
    authorizationIsSentinel: call?.authorizationIsSentinel ?? null, dispatched: dispatched.length,
    fixtureCall: call?.n ?? null, gate: calls === null ? "product" : "fixture" };
  BYTE_LOG.push(row);
  return row;
}
async function readCard(page, branch, sendId) {
  const card = lp(page, branch).locator(`[data-testid="jev-loop-choice-card"]${attr("data-send-id", sendId)}`);
  await card.waitFor({ timeout: 30000 });
  const details = card.locator('[data-testid="jev-loop-choice-probabilities"]');
  const foldedBefore = !(await details.evaluate(node => node.open));
  if (foldedBefore) await details.locator("summary").click();
  const late = card.locator('[data-testid="jev-loop-choice-late"]');
  const lateNote = card.locator('[data-testid="jev-loop-choice-late-note"]');
  return { foldedBefore, container: await card.evaluate(node => node.parentElement?.getAttribute("data-testid") ?? null),
    proposalHandle: await card.getAttribute("data-proposal-handle"), chosen: await card.getAttribute("data-chosen-alias"),
    lateAttr: await card.getAttribute("data-late"), selectionAttr: await card.getAttribute("data-selection"),
    positionAttr: await card.getAttribute("data-list-position"),
    title: clean(await card.locator(".mw-jev-title").first().textContent()),
    role: clean(await card.locator('[data-testid="jev-loop-choice-role"]').textContent()),
    alias: clean(await card.locator('[data-testid="jev-loop-choice-alias"]').textContent()),
    local: clean(await card.locator('[data-testid="jev-loop-choice-local"]').textContent()),
    position: clean(await card.locator('[data-testid="jev-loop-choice-position"]').textContent()),
    confidence: clean(await card.locator('[data-testid="jev-loop-choice-confidence"]').textContent()),
    model: clean(await card.locator('[data-testid="jev-loop-choice-model"]').textContent()),
    usage: Object.fromEntries(await card.locator("dd[data-usage]").evaluateAll(items =>
      items.map(item => [item.getAttribute("data-usage"), item.textContent.trim()]))),
    reported: await details.getAttribute("data-reported"),
    probabilities: await details.locator("li[data-alias]").evaluateAll(items =>
      items.map(item => ({ alias: item.getAttribute("data-alias"), text: item.textContent.trim() }))),
    limitations: await card.locator('[data-testid="jev-loop-choice-limitations"] [data-limitation]').evaluateAll(items =>
      items.map(item => item.textContent)),
    late: (await late.count()) ? clean(await late.textContent()) : null,
    lateNote: (await lateNote.count()) ? await lateNote.textContent() : null,
    comparison: await card.evaluate(node => ({
      graphics: node.querySelectorAll("progress, meter, svg, canvas").length,
      ariaSort: node.querySelectorAll("[aria-sort]").length,
      styled: [...node.querySelectorAll("[style]")].filter(item => /width|background|color/i.test(item.getAttribute("style")))
        .length,
      attrs: [...node.querySelectorAll("*")].flatMap(item => [...item.attributes].map(a => a.name))
        .filter(name => /rank|best|score|recommend|winner/i.test(name)).length })) };
}
/** The card = the stored proposal (alias, list position n/m, local notation, confidence, model, usage, values in the
 * sent order folded at first, the stored sentences) and nothing that orders or compares. */
function cardMatches(shown, record, choice, projection, { late, isSelection, iteration }) {
  assert.equal(choice.schema, "jev_loop_choice@1");
  assert.equal(choice.label, "JEV 판정(모델 선택)");
  assert.equal(choice.scientific_result, false);
  assert.equal(shown.title, "JEV 판정(모델 선택)");
  assert.equal(shown.proposalHandle, record.choice_handle);
  assert.equal(shown.chosen, choice.answer.choice_alias);
  assert.equal(shown.alias, choice.answer.choice_alias);
  const criteria = projection.selection.filter(item => item.state === "pending").map(item => item.alias);
  assert.equal(choice.answer.list_position, criteria.indexOf(choice.answer.choice_alias) + 1, "list position ≠ criteria place");
  assert.equal(choice.answer.list_size, criteria.length);
  assert.equal(shown.position, `${choice.answer.list_position}/${choice.answer.list_size}`);
  assert.equal(shown.positionAttr, shown.position);
  const display = choice.answer.local_display;
  if ("smiles" in display) assert.equal(shown.local, display.smiles);
  else for (const value of [display.residue.resname, String(display.residue.seq_auth), `${display.from}→${display.to}`])
    assert.ok(shown.local.includes(value), `${value} not in ${shown.local}`);
  assert.equal(shown.confidence, choice.answer.confidence === null ? "보고 없음" : halfUp(choice.answer.confidence, 3));
  assert.equal(shown.model, SERVED_MODEL);
  assert.equal(choice.served_model, SERVED_MODEL);
  for (const key of ["input_tokens", "output_tokens", "external_tokens", "cost"]) {
    const value = choice.usage === null ? null : choice.usage[key];
    assert.equal(shown.usage[key], value === null ? UNKNOWN_USAGE : String(value), `usage ${key}`);
  }
  const reported = choice.answer.probabilities;
  assert.equal(shown.reported, String(reported !== null));
  if (reported === null) assert.deepEqual(shown.probabilities, []);
  else {
    assert.deepEqual(shown.probabilities.map(item => item.alias), criteria, "probabilities not in the sent order");
    for (const item of shown.probabilities) {
      const value = Object.prototype.hasOwnProperty.call(reported, item.alias) ? reported[item.alias] : null;
      assert.ok(value === null ? item.text.includes("보고 없음") : item.text.endsWith(halfUp(value, 3)), `${item.alias}: ${item.text}`);
    }
  }
  assert.equal(shown.foldedBefore, true, "the per-candidate values were not folded when the card appeared");
  assert.deepEqual(shown.limitations, expectedLimitations(projection.kind, choice.goal, { late }));
  assert.deepEqual(choice.limitations, shown.limitations);
  assert.deepEqual(choice.arrival.late, late);
  assert.equal(shown.lateAttr, String(late));
  assert.equal(shown.selectionAttr, String(isSelection));
  assert.equal(shown.role, isSelection ? `바퀴 ${iteration}의 선택(계산은 사람이 승인해야 시작)` : `바퀴 ${iteration}의 선택이 아님`);
  assert.equal(shown.late === null, !late);
  if (late) {
    assert.ok(shown.late.includes(LATE_TEXT), shown.late);
    assert.ok(shown.lateNote.includes(J.J7), "late note without J7");
  }
  assert.deepEqual(shown.comparison, { graphics: 0, ariaSort: 0, styled: 0, attrs: 0 });
  return { alias: shown.alias, position: shown.position, confidence: shown.confidence, late, container: shown.container,
    probabilities: shown.probabilities.length };
}
async function reasonOnly(page, branch, sendId) {
  const reason = lp(page, branch).locator(`[data-testid="jev-loop-choice-reason"]${attr("data-send-id", sendId)}`);
  await reason.waitFor({ timeout: 30000 });
  const holder = lp(page, branch).locator(`[data-jev-loop-area="choice"]`);
  return { status: await reason.getAttribute("data-status"), code: await reason.getAttribute("data-reason-code"),
    text: clean(await reason.textContent()),
    cards: await holder.locator(`[data-testid="jev-loop-choice-card"]${attr("data-send-id", sendId)}`).count(),
    sendRecord: { status: await lt(page, branch, "jev-loop-send-record").getAttribute("data-status"),
      code: await lt(page, branch, "jev-loop-send-record").getAttribute("data-reason-code") } };
}
function reasonOnlyMatches(value, record, code) {
  assert.deepEqual([record.status, record.reason_code], ["failed", code]);
  assert.equal(record.choice_handle, null);
  assert.equal(value.status, "failed");
  assert.equal(value.code, code);
  assert.ok(value.text.includes(`(${code})`), value.text);
  assert.equal(value.cards, 0, "a proposal card for a failed send");
  assert.ok(!/\b[cm]\d{2}\b/.test(value.text), "a candidate alias in the reason");
  assert.deepEqual(value.sendRecord, { status: "failed", code });
  return value;
}
async function computeConfirm(page, branch) {
  if (!(await lt(page, branch, "jev-loop-compute-confirm").isChecked())) await lt(page, branch, "jev-loop-compute-confirm").check();
}
/** The compute confirmation and one press of `button`; resolves with the route's answer (held until the job ends). */
async function pressCompute(page, branch, run, loopId, button, log, evidence, { confirm = true, timeout = 600000 } = {}) {
  if (confirm) await computeConfirm(page, branch);
  await waitFor(page, async () => await lt(page, branch, button).isEnabled() ? true : null, `${button} enabled`, 30000);
  const since = Date.now();
  await lt(page, branch, button).click();
  control(evidence, button, { run, loopId });
  return waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev_loops/${loopId}/compute`, `${button} answer`,
    timeout);
}
async function endState(page, branch) {
  return { enabled: await lt(page, branch, "jev-loop-end").isEnabled(),
    reasons: (await lt(page, branch, "jev-loop-end-blocked").count())
      ? await lt(page, branch, "jev-loop-end-blocked").locator("li").evaluateAll(items => items.map(item => item.textContent.trim()))
      : [] };
}
async function candidateTable(page, branch) {
  const table = lt(page, branch, "jev-loop-candidate-table");
  return { headers: await table.locator("thead th").evaluateAll(items => items.map(item => item.textContent.trim())),
    ariaSort: await table.locator("thead th[aria-sort]").evaluateAll(items => items.map(item => item.getAttribute("aria-sort"))),
    rows: await table.locator("tbody tr").evaluateAll(items => items.map(item => ({ ref: item.getAttribute("data-ref"),
      state: item.getAttribute("data-state"), evaluation: item.getAttribute("data-evaluation"),
      hasScore: item.getAttribute("data-has-score") === "true", iteration: item.getAttribute("data-iteration"),
      score: item.querySelector("[data-score-cell]")?.textContent.trim() ?? null,
      cells: [...item.cells].map(cell => cell.textContent.trim()) }))) };
}
/** Every row's state, evaluation and score cell = the record (a score = halfUp(stored first mode, 1); no score "—"). */
function candidateRowsMatch(table, record) {
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
async function wordingCheck(page, branch, label, evidence) {
  const value = await lp(page, branch).evaluate(node => ({ text: node.innerText,
    exempt: [...node.querySelectorAll('[data-testid="jev-loop-m18-area"], [data-testid="jev-loop-limitations"], ' +
      '[data-testid="jev-loop-choice-limitations"], [data-testid="jev-loop-preview-body"], ' +
      '[data-testid="jev-loop-preview-question"], .mw-ligand-filter')].flatMap(item => item.innerText.split("\n")) }));
  const found = forbiddenWords(value.text, value.exempt);
  evidence.wording.push({ label, kind: "screen", found });
  return found;
}
/** The 지식·보고서 tab's report library: the saved report listed with its kind; clicking it shows the saved Markdown. */
async function libraryReport(page, run, handle, evidence) {
  await selectTab(page, TAB.knowledge);
  const library = page.getByRole("region", { name: "보고서 보관함", exact: true });
  const reports = library.getByRole("region", { name: "저장된 보고서", exact: true });
  const content = library.getByRole("region", { name: "선택한 항목 내용", exact: true });
  const row = reports.locator("li button").filter({ hasText: handle });
  await row.waitFor({ timeout: 30000 });
  const kind = clean(await row.locator(".mw-library-kind").textContent());
  await row.click();
  control(evidence, "report-library-open", { handle });
  const pre = content.getByLabel(`저장된 보고서 ${handle}`, { exact: true });
  await pre.waitFor({ timeout: 30000 });
  const saved = await readApi(page, `/runs/${run}/reports/selected?handle=${enc(handle)}`);
  return { kind, text: await pre.textContent(), saved };
}
function reportMatches(report, summary, kind, goal, evidence) {
  assert.equal(report.kind, LOOP_REPORT_KIND);
  assert.equal(report.text, report.saved.markdown);
  for (const sentence of expectedLimitations(kind, goal, { ended: true,
    uncomputed: summary.candidates.some(row => ["pending", "unavailable"].includes(row.state)) }))
    assert.ok(report.text.includes(sentence), "report lacks a fixed sentence");
  assert.ok(!keysOf(report.saved).includes("probabilities"), "the saved report carries a probabilities field");
  const found = forbiddenWords(report.text);
  evidence.wording.push({ label: `report ${summary.loop_id}`, kind: "report", found });
  assert.deepEqual(found, []);
  return { markdownSha256: sha(Buffer.from(report.text)), kind: report.kind };
}
async function makeLoopReport(page, branch, run, log, evidence) {
  const since = Date.now();
  await lt(page, branch, "jev-loop-report").click();
  control(evidence, "jev-loop-report", { run, branch });
  const entry = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/method_reports`, "report answer", 120000);
  assert.equal(entry.status, 201, JSON.stringify(entry.json).slice(0, 400));
  await lp(page, branch).locator(`[data-testid="jev-loop-report-done"]${attr("data-report-handle", entry.json.handle)}`)
    .waitFor({ timeout: 60000 });
  return entry;
}
/** The 지식·보고서 tab send history: every loop send is a read-only row with the loop mark and guide, no open or report
 * button; the M24 wording rule holds in that area. */
async function knowledgeRows(page, run) {
  await selectTab(page, TAB.knowledge);
  const jev = page.locator('#mw-app-panel-knowledge [data-testid="jev-panel"]');
  await jev.waitFor({ timeout: 15000 });
  await waitFor(page, async () => await jev.locator('[data-jev-area="history"]').getAttribute("data-state") === "ready"
    ? true : null, "history ready", 45000);
  const rows = await jev.locator("tr[data-jev-send]").evaluateAll(items => items.map(item => ({
    sendId: item.getAttribute("data-jev-send"), loop: item.getAttribute("data-jev-loop"), status: item.getAttribute("data-status"),
    mark: item.querySelector('[data-testid="jev-send-loop-mark"]')?.textContent.trim() ?? null,
    guide: item.querySelector('[data-testid="jev-send-loop-guide"]')?.textContent.trim() ?? null,
    openButtons: item.querySelectorAll('[data-testid="jev-send-open"]').length,
    reportButtons: item.querySelectorAll('[data-testid="jev-send-report"]').length })));
  return { rows, list: await readApi(page, `/runs/${run}/jev/sends`), text: await jev.evaluate(node => node.innerText) };
}
function knowledgeRowsMatch(value, tab, expectedSends) {
  assert.equal(value.rows.length, expectedSends.length);
  for (const send of expectedSends) {
    const row = value.rows.find(item => item.sendId === send.send_id);
    assert.ok(row, `send ${send.send_id} not listed`);
    const listed = value.list.find(item => item.send_id === send.send_id);
    assert.ok(listed?.loop, "the send record has no loop key");
    assert.equal(row.loop, "true");
    assert.equal(row.mark, `JEV 루프 · 바퀴 ${listed.loop.iteration} · 전송 순번 ${listed.loop.send_ordinal}`);
    assert.equal(row.guide, `이 전송은 JEV 루프 기록입니다. 결과와 계산은 ${tab} 탭의 JEV 루프 영역에서 봅니다.`);
    assert.equal(row.openButtons, 0);
    assert.equal(row.reportButtons, 0, "the M24 report button is on a loop row");
  }
  return value.rows.map(row => ({ sendId: row.sendId, status: row.status, mark: row.mark }));
}

// ------------------------------------------------------------------ run L (ligand): loops A, B, C
async function ligandBranch(session, input, setup, rec_, evidence, log) {
  const { page } = session;
  const runsDir = input["runs-dir"];
  const controlDir = input.control;
  const L = setup.runs.L;
  const run = L.run;
  const b = "ligand";
  const ids = L.ligandSet.ids;
  const poolA = ids.slice(0, LOOP_A.size);
  let viewerBefore = null;
  let before = null;
  let loopA = null;
  const sends = [];

  await rec_.part("L-entry", ["L-tab-entry", "L-create-fields"], async () => {
    viewerBefore = await rec_.step("L00-run", [], "구조 분석: run L chosen in the rail; the viewer shows its structure",
      () => chooseRun(page, run), async value => ({ sourceHandle: value.sourceHandle, sessionId: value.sessionId }));
    await rec_.step("L01-other-areas-before", [], "리간드 설계·탐색 and 단백질 공학 visited before any loop action " +
      "(areas and digit-masked text recorded; the JEV loop area is last in each tab)", async () => {
      before = { ligand: await tabAreas(page, "ligand", log), protein: await tabAreas(page, "protein", log) };
      return before;
    }, async value => {
      assert.deepEqual(value.ligand.areas.map(item => item.id), ["ligand-panel", "docking-panel", "docking-batch-panel",
        "ligand-ga-panel", "jev-loop-panel"]);
      assert.deepEqual(value.protein.areas.map(item => item.id), ["mutation-panel", "mutation-model-panel",
        "sequence-ga-panel", "jev-loop-panel"]);
      for (const sig of Object.values(value)) assert.deepEqual(sig.posts, [], "entering a tab posted");
      return { ligand: value.ligand.areas.map(item => item.id), protein: value.protein.areas.map(item => item.id) };
    });
    await rec_.step("L02-tab-entry", ["L-tab-entry"], "Click 리간드 설계·탐색: the JEV 루프 area mounts with GET reads only; " +
      "consent off; UL1 and UL3 (no U3 here); no loop (empty state); the set listed and not chosen; no goal chosen; loop " +
      "seed empty; iteration cap 5; 루프 만들기 closed; 구조 분석 hidden and inert; no global science mark", async () => {
      const since = await openLoopArea(page, b, log);
      await waitFor(page, async () => (await lt(page, b, "jev-loop-sources").count()) ? true : null, "sources listed", 30000);
      return { posts: posts(log, since), reads: gets(log, since), state: await lp(page, b).getAttribute("data-jev-loop-state"),
        consent: await consentState(page, b), consentChecked: await lt(page, b, "jev-loop-consent").isChecked(),
        ul1: await lt(page, b, "jev-loop-note-ul1").textContent(), ul3: await lt(page, b, "jev-loop-note-ul3").textContent(),
        u3: await lt(page, b, "jev-loop-note-u3").count(), none: await lt(page, b, "jev-loop-none").count(),
        sources: await listedSources(page, b),
        goals: await lp(page, b).locator('input[data-testid^="jev-loop-goal-"]').evaluateAll(items => items.map(item => item.checked)),
        seed: await lt(page, b, "jev-loop-seed").inputValue(), cap: await lt(page, b, "jev-loop-iteration-cap").inputValue(),
        createEnabled: await lt(page, b, "jev-loop-create").isEnabled(), record: await lt(page, b, "jev-loop-record").count(),
        structure: await structureHidden(page), line: await globalLine(page),
        tabs: await page.locator(".mw-app-tabs [role=tab]").evaluateAll(items => items.map(item => item.textContent.trim())),
        free: await lt(page, b, "jev-loop-free-note").textContent() };
    }, async value => {
      assert.deepEqual(value.posts, [], "entering the tab posted");
      for (const route of ["jev/status", "jev_loops", "docking/prerequisites"])
        assert.ok(value.reads.some(item => item.endsWith(route)), `no GET ${route}: ${value.reads}`);
      assert.equal(value.state, "empty");
      assert.equal(value.consent, "off");
      assert.equal(value.consentChecked, false);
      assert.equal(value.ul1, UL.UL1);
      assert.equal(value.ul3, UL.UL3);
      assert.equal(value.u3, 0);
      assert.equal(value.none, 1);
      assert.deepEqual(value.sources, [{ handle: L.ligandSet.handle, checked: false }]);
      assert.deepEqual(value.goals, [false, false], "a goal was chosen automatically");
      assert.equal(value.seed, "");
      assert.equal(value.cap, "5");
      assert.equal(value.createEnabled, false);
      assert.equal(value.record, 0);
      assert.deepEqual(value.structure, { shown: "false", inert: true });
      assert.equal(value.line.badge, null);
      assert.deepEqual(value.tabs, TAB_LABELS);
      assert.equal(value.free, "루프의 도킹은 자유 도킹으로 고정됩니다(코어 고정 없음).");
      return { reads: value.reads.length, state: value.state };
    });
    await rec_.step("L03-create-fields", ["L-create-fields"], "Choose the set and check one candidate; type iteration cap 9: " +
      "루프 만들기 stays closed and each field shows its reason (pool: 2개 이상 pool_invalid; goal: goal_invalid, nothing " +
      "chosen; loop seed empty: seed_invalid; cap 9: iteration_cap_invalid; setup: the computation inputs)", async () => {
      const rows = await chooseSource(page, b, L.ligandSet.handle, ids.length, evidence);
      await checkKeys(page, b, [ids[0]], evidence);
      await fill(page, b, "jev-loop-iteration-cap", "9", evidence);
      const errors = await fieldErrors(page, b);
      return { rows, count: await poolCount(page, b), errors, createEnabled: await lt(page, b, "jev-loop-create").isEnabled(),
        posts: posts(log, 0).filter(item => item.endsWith("/jev_loops")) };
    }, async value => {
      assert.ok(value.rows.every(row => !row.checked), "a candidate was checked automatically");
      assert.equal(value.count, 1);
      assert.equal(value.createEnabled, false);
      assert.ok(value.errors.pool.items.some(text => text.includes("2개 이상") && text.includes("(pool_invalid)")), JSON.stringify(value.errors.pool));
      assert.ok(value.errors.goal.items.some(text => text.includes("(goal_invalid)")));
      assert.ok(value.errors.loop_seed.items.some(text => text.includes("(seed_invalid)")));
      assert.ok(value.errors.iteration_cap.items.some(text => text.includes("(iteration_cap_invalid)")));
      assert.ok(value.errors.setup.items.length > 0, "no setup reason before the computation inputs");
      assert.deepEqual(value.posts, [], "a create request was sent");
      return value.errors;
    });
  });

  await rec_.part("L-create", ["L-create", "L-loop-active"], async () => {
    loopA = await rec_.step("L04-create", ["L-create", "L-loop-active"], "Check four more candidates (pool 5), 활용형, loop " +
      "seed 7, cap 3, the computation inputs (receptor model 1, 없음, PDB CONECT, manual 12 Å box, seed 1, exhaustiveness 1, " +
      "num_modes 2, the acknowledgements, the parent SDF): no field reason; 루프 만들기: jev_loop_created, the loop opens " +
      "(active, iteration 1, awaiting_selection), the list shows it, and a second loop of this branch is refused with " +
      "loop_active (button closed)", async () => {
      await checkKeys(page, b, poolA.slice(1), evidence);
      await settings(page, b, { goal: LOOP_A.goal, seed: LOOP_A.seed, cap: LOOP_A.cap }, evidence);
      await ligandSetupInputs(page, L, evidence);
      const errors = await fieldErrors(page, b);
      const entry = await createLoop(page, b, run, log, evidence);
      const attrs = await recordWhen(page, b, value => value.loopId === entry.json?.loop_id, "loop opened", 30000);
      const blocked = await waitFor(page, async () => (await lt(page, b, "jev-loop-create-blocked").count())
        ? clean(await lt(page, b, "jev-loop-create-blocked").textContent()) : null, "create blocked", 15000);
      return { errors, entry, attrs, blocked, createEnabled: await lt(page, b, "jev-loop-create").isEnabled(),
        list: await lt(page, b, "jev-loop-list").locator("input[data-testid=jev-loop-open]").evaluateAll(items =>
          items.map(item => ({ loopId: item.getAttribute("data-loop-id"), checked: item.checked }))),
        record: await readLoop(page, run, entry.json.loop_id), events: eventCount(runsDir, run, "jev_loop_created") };
    }, async value => {
      for (const [field, item] of Object.entries(value.errors)) assert.deepEqual(item.items, [], `${field} reason left`);
      assert.equal(value.entry.status, 200, JSON.stringify(value.entry.json).slice(0, 600));
      const request = value.entry.request;
      assert.deepEqual(request.pool, { source: L.ligandSet.handle, candidates: poolA, filter: null });
      assert.deepEqual([request.branch, request.goal, request.loop_seed, request.iteration_cap], ["ligand", "exploit", 7, 3]);
      assert.ok(!("mode" in request.setup) && !("ligand" in request.setup), "setup carries mode or ligand");
      assert.equal(request.setup.parent_sdf_handle, L.parent);
      assert.deepEqual(value.attrs, { loopId: request.loop_id, status: "active", action: "select", phase: "awaiting_selection",
        iteration: "1", step: "ligand_dock" });
      const record = value.record;
      assert.equal(record.effective_cap, 3);
      assert.deepEqual(record.candidates.map(item => item.ref), poolA);
      assert.ok(record.candidates.every(item => item.state === "pending" && item.score_kcal_mol === null));
      assert.deepEqual(record.limitations, expectedLimitations("ligand", "exploit"));
      assert.equal(value.events, 1);
      assert.ok(value.blocked.includes("(loop_active)"), value.blocked);
      assert.equal(value.createEnabled, false);
      assert.deepEqual(value.list, [{ loopId: request.loop_id, checked: true }]);
      return { loopId: request.loop_id, blocked: value.blocked };
    });
  });
  if (!loopA?.loopId) return { run, sends };

  // ---- loop A iteration 1: consent off block, preview identity and oracle, confirmation, HTTP 500, model mismatch, good
  let firstBuilt = null;
  await rec_.part("L-iter1-preview", ["L-consent-off-block", "L-preview-match", "L-order-oracle", "L-consent-toggle",
    "L-confirm-required"], async () => {
    await rec_.step("L05-consent-off", ["L-consent-off-block", "L-preview-match", "L-order-oracle"], "보낼 내용 " +
      "만들기 (consent off): the stored projection, the exact body folded at first; its text = the server preview string, " +
      "SHA-256 and bytes computed here = shown = stored; the order, aliases, criteria and computed rows = the independent " +
      "sha256_order_v1 oracle; the question is the spec 4.5 exploit text; the preview lists consent_off and with the " +
      "confirmation the send stays closed", async () => {
      const record = await readLoop(page, run, loopA.loopId);
      const built = await build(page, b, run, log, evidence);
      const folded = !(await lt(page, b, "jev-loop-preview-body-details").evaluate(node => node.open));
      await lt(page, b, "jev-loop-preview-body-details").locator("summary").click();
      const shown = await previewWhen(page, b, built.handle, item => item.blocked.length > 0, "preview with consent_off");
      await lt(page, b, "jev-loop-confirm").check();
      return { record, built, folded, shown, send: await sendState(page, b), stored: storedObject(runsDir, run, built.handle) };
    }, async value => {
      assert.equal(value.folded, true, "the exact body was not folded at first");
      const identity = previewMatches({ shown: value.shown, built: value.built, stored: value.stored, record: value.record,
        iteration: 1, ordinal: 0, runId: run });
      assert.deepEqual(value.shown.blocked.map(item => item.code), ["consent_off"]);
      assert.ok(value.shown.blocked[0].text.includes("(consent_off)"));
      assert.equal(value.shown.blockedAttr, "true");
      assert.equal(value.send.confirmed, true);
      assert.equal(value.send.enabled, false);
      assert.ok(value.send.blockers.some(text => text.includes("(consent_off)")), value.send.blockers.join(" | "));
      assert.deepEqual(value.stored.limitations, expectedLimitations("ligand", "exploit"));
      firstBuilt = { built: value.built, shown: value.shown };     // kept for the next steps, not logged
      return identity;
    });
    await rec_.step("L06-consent-confirm", ["L-consent-toggle", "L-confirm-required"], "Turn the loop area's consent switch " +
      "on: the preview is read again without refusals and the global line shows 과학 전송 허용 after the run id; uncheck the " +
      "confirmation: the send button closes with the confirmation reason; check it again: the button opens", async () => {
      await setConsent(page, b, run, true, log, evidence);
      const shownOn = await previewWhen(page, b, firstBuilt.built.handle, item => item.blocked.length === 0, "preview unblocked");
      const line = await waitFor(page, async () => { const value = await globalLine(page); return value.badge ? value : null; },
        "global mark", 15000);
      await lt(page, b, "jev-loop-confirm").uncheck();
      control(evidence, "jev-loop-confirm", { checked: false });
      const unchecked = await sendState(page, b);
      await lt(page, b, "jev-loop-confirm").check();
      control(evidence, "jev-loop-confirm", { checked: true });
      return { shownOn, line, unchecked, checked: await sendState(page, b),
        status: await readApi(page, `/runs/${run}/jev/status`) };
    }, async value => {
      assert.deepEqual(value.shownOn.blocked, []);
      assert.deepEqual(value.shownOn.loopBlocks, []);
      assert.deepEqual(value.line.badge, { text: "과학 전송 허용", afterRun: true });
      assert.equal(value.unchecked.enabled, false);
      assert.ok(value.unchecked.blockers.some(text => text.includes("확인 체크")), value.unchecked.blockers.join(" | "));
      assert.equal(value.checked.enabled, true);
      assert.equal(value.status.enabled, true);
      return { line: value.line, unchecked: value.unchecked.blockers };
    });
  });

  let goodSend = null;
  await rec_.part("L-iter1-sends", ["L-failed-model", "L-ordinal-refused", "L-send-good", "L-bytes-equal", "L-choice-card",
    "L-order-oracle"], async () => {
    const built = firstBuilt?.built;
    const shownBody = firstBuilt?.shown.body;
    await rec_.step("L07-model-mismatch", ["L-failed-model", "L-ordinal-refused", "L-bytes-equal"], "이 내용을 JEV로 " +
      "보냅니다 (fixture model_mismatch): failed model_mismatch, the reason only (no card); transport bytes = preview = " +
      "prepared audit; the preview read again lists the loop block ordinal_mismatch (the send used ordinal 0) and the send " +
      "stays closed", async () => {
      const sent = await confirmAndSend(page, b, run, controlDir, "model_mismatch", log, evidence);
      const reason = await reasonOnly(page, b, sent.record.send_id);
      const after = await previewWhen(page, b, built.handle, item => item.loopBlocks.length > 0, "ordinal_mismatch shown");
      return { sent, reason, after, send: await sendState(page, b), status: await readApi(page, `/runs/${run}/jev/status`) };
    }, async value => {
      reasonOnlyMatches(value.reason, value.sent.record, "model_mismatch");
      const bytes = serverBytes(runsDir, run, value.sent.record.send_id, shownBody, built.preview.body_sha256, value.sent.calls);
      assert.equal(value.sent.calls[0].script, "model_mismatch");
      assert.deepEqual(value.after.loopBlocks.map(item => item.code), ["ordinal_mismatch"]);
      assert.deepEqual(value.after.blocked, []);
      assert.equal(value.send.enabled, false);
      assert.ok(value.send.blockers.some(text => text.includes("(ordinal_mismatch)")), value.send.blockers.join(" | "));
      assert.equal(value.status.egress_stop_reason, null);
      sends.push(value.sent.record);
      return { reason: value.reason.text, bytes, blockers: value.send.blockers };
    });
    goodSend = await rec_.step("L08-good", ["L-send-good", "L-choice-card", "L-bytes-equal", "L-order-oracle"], "보낼 내용 " +
      "만들기 again (send ordinal 1: a new order = the oracle) and send (fixture good: the first criteria key): completed; " +
      "the iteration's JEV selection card = the stored jev_loop_choice@1 (JEV 판정(모델 선택), the chosen alias, list " +
      "position n/m = its criteria place, the local SMILES, confidence 0.620, the served model, usage, per-candidate values " +
      "folded at first and listed in the sent order, LJ1-LJ4 and LJ6); no ordering, bar or colour element; the phase " +
      "becomes awaiting_compute and 보낼 내용 만들기 closes (selection_done)", async () => {
      const record = await readLoop(page, run, loopA.loopId);
      const made = await build(page, b, run, log, evidence);
      const shown = await previewWhen(page, b, made.handle, item => item.blocked.length === 0 && item.loopBlocks.length === 0,
        "preview");
      const stored = storedObject(runsDir, run, made.handle);
      const sent = await confirmAndSend(page, b, run, controlDir, "good", log, evidence);
      await lp(page, b).locator(`[data-testid="jev-loop-selection"]${attr("data-send-id", sent.record.send_id)}`)
        .waitFor({ timeout: 30000 });
      const card = await readCard(page, b, sent.record.send_id);
      const attrs = await recordWhen(page, b, item => item.action === "compute", "awaiting compute");
      const buildBlocked = await waitFor(page, async () => (await lt(page, b, "jev-loop-build-blocked").count())
        ? clean(await lt(page, b, "jev-loop-build-blocked").textContent()) : null, "build closed", 15000);
      return { record, made, shown, stored, sent, card, attrs, buildBlocked, wording: await wordingCheck(page, b, "good card", evidence) };
    }, async value => {
      assert.deepEqual(value.wording, []);
      const identity = previewMatches({ shown: value.shown, built: value.made, stored: value.stored, record: value.record,
        iteration: 1, ordinal: 1, runId: run });
      assert.notDeepEqual(value.stored.selection.map(item => item.ref),
        storedObject(runsDir, run, built.handle).selection.map(item => item.ref), "the order did not change per send");
      const record = value.sent.record;
      assert.equal(record.status, "completed");
      assert.deepEqual(record.loop, { loop_id: loopA.loopId, iteration: 1, send_ordinal: 1 });
      const choice = storedObject(runsDir, run, record.choice_handle);
      const card = cardMatches(value.card, record, choice, value.stored, { late: false, isSelection: true, iteration: 1 });
      const call = value.sent.calls[0];
      assert.equal(call.script, "good");
      assert.deepEqual(call.criteria, identity.criteria);
      assert.equal(choice.answer.choice_alias, identity.criteria[0], "the fixture chose the first criteria key");
      assert.equal(card.container, "jev-loop-selection");
      const bytes = serverBytes(runsDir, run, record.send_id, value.shown.body, value.made.preview.body_sha256, value.sent.calls);
      assert.deepEqual([value.attrs.phase, value.attrs.iteration], ["awaiting_compute", "1"]);
      assert.ok(value.buildBlocked.includes("(selection_done)"), value.buildBlocked);
      sends.push(record);
      return { card, bytes, choiceHandle: record.choice_handle, ref: choice.answer.local_ref.candidate_id,
        position: card.position, identity };
    });
  });

  // ---- compute with the JEV proposal (real qvina)
  await rec_.part("L-compute-jev", ["L-compute-jev", "L-real-engine"], async () => {
    await rec_.step("L10-compute-jev", ["L-compute-jev", "L-real-engine"], "Check the compute confirmation and press 이 " +
      "선택으로 계산 시작 (JEV 판정 사용): one jev_loop_compute_approved (decided_by jev), the standalone M18 job runs (real " +
      "qvina); iteration 1 ends scored; the candidate's score = the stored docking_result@1 first mode (shown with one " +
      "decimal), evaluation 새 계산, the iteration row shows list position n/m", async () => {
      const entry = await pressCompute(page, b, run, loopA.loopId, "jev-loop-compute-proposal", log, evidence);
      const attrs = await recordWhen(page, b, item => item.iteration === "2" && item.action === "select", "iteration 2", 120000);
      const record = await readLoop(page, run, loopA.loopId);
      return { entry, attrs, record, table: await candidateTable(page, b),
        position: clean(await lt(page, b, "jev-loop-iterations").locator('tr[data-iteration="1"] [data-testid="jev-loop-iteration-position"]').textContent()),
        approvals: runEvents(runsDir, run).filter(event => event.type === "jev_loop_compute_approved") };
    }, async value => {
      assert.equal(value.entry.status, 200, JSON.stringify(value.entry.json).slice(0, 600));
      assert.deepEqual(value.entry.request, { iteration: 1, proposal: goodSend.choiceHandle });
      assert.equal(value.approvals.length, 1);
      assert.equal(value.approvals[0].decided_by, "jev");
      assert.equal(value.approvals[0].proposal_handle, goodSend.choiceHandle);
      assert.equal(value.approvals[0].candidate_ref, goodSend.ref);
      const it = value.record.iterations.find(item => item.index === 1);
      assert.deepEqual([it.state, it.decided_by, it.candidate_ref], ["scored", "jev", goodSend.ref]);
      assert.equal(`${it.list_position}/${it.list_size}`, goodSend.position);
      assert.equal(value.position, goodSend.position);
      const step = it.steps[0];
      assert.deepEqual([step.step, step.state], ["ligand_dock", "completed"]);
      const result = storedObject(runsDir, run, step.result_handle);
      const candidate = value.record.candidates.find(item => item.ref === goodSend.ref);
      assert.deepEqual([candidate.state, candidate.evaluation, candidate.iteration], ["scored", "computed", 1]);
      assert.equal(candidate.score_kcal_mol, result.modes[0].score_kcal_mol, "the record score is not the stored first mode");
      assert.equal(it.score_kcal_mol, result.modes[0].score_kcal_mol);
      candidateRowsMatch(value.table, value.record);
      assert.deepEqual(value.record.counts, { started: 1, done: 1, jev_decided: 1, human_decided: 0, sends_dispatched: 2,
        units_charged: 1, reused_count: 0 });
      return { score: result.modes[0].score_kcal_mol, shown: halfUp(result.modes[0].score_kcal_mol, 1), job: step.job_id };
    });
  });

  // ---- iteration 2: computed alias refused, late reply, human designation of the late choice
  let lateRef = null;
  await rec_.part("L-iter2", ["L-failed-computed-alias", "L-late", "L-designate", "L-bytes-equal", "L-order-oracle"], async () => {
    await rec_.step("L11-computed-alias", ["L-failed-computed-alias", "L-order-oracle", "L-bytes-equal"], "Iteration 2: " +
      "보낼 내용 만들기 (send ordinal 0): the computed row carries the iteration 1 alias with its stored score as is " +
      "(exploit) and criteria the other four; send (fixture computed_alias: the computed alias): failed response_invalid " +
      "at the gate, the reason only; bytes equal", async () => {
      const record = await readLoop(page, run, loopA.loopId);
      const made = await build(page, b, run, log, evidence);
      const shown = await previewWhen(page, b, made.handle, item => item.blocked.length === 0, "preview");
      const stored = storedObject(runsDir, run, made.handle);
      const sent = await confirmAndSend(page, b, run, controlDir, "computed_alias", log, evidence);
      return { record, made, shown, stored, sent, reason: await reasonOnly(page, b, sent.record.send_id) };
    }, async value => {
      const identity = previewMatches({ shown: value.shown, built: value.made, stored: value.stored, record: value.record,
        iteration: 2, ordinal: 0, runId: run });
      assert.equal(identity.computed.length, 1);
      assert.equal(identity.computed[0].state, "scored");
      assert.equal(typeof identity.computed[0].score_kcal_mol, "number");
      assert.equal(identity.criteria.length, LOOP_A.size - 1);
      assert.deepEqual(value.sent.calls[0].computed, identity.computed.map(item => item.alias));
      assert.equal(value.sent.calls[0].response.answers.candidate_choice.choice, identity.computed[0].alias);
      reasonOnlyMatches(value.reason, value.sent.record, "response_invalid");
      const bytes = serverBytes(runsDir, run, value.sent.record.send_id, value.shown.body, value.made.preview.body_sha256,
        value.sent.calls);
      sends.push(value.sent.record);
      return { identity, bytes };
    });
    await rec_.step("L12-late", ["L-late", "L-bytes-equal"], "보낼 내용 만들기 (send ordinal 1); send (fixture slow); while " +
      "the reply is held, turn the consent switch off; let the reply go: completed and late (동의 끈 뒤 도착), its card is " +
      "not the iteration's selection (바퀴 2의 선택이 아님, the late note with J7, J7 last among the stored sentences); the " +
      "iteration stays awaiting_selection; the global mark is gone; switch consent on again", async () => {
      const record = await readLoop(page, run, loopA.loopId);
      const made = await build(page, b, run, log, evidence);
      const shown = await previewWhen(page, b, made.handle, item => item.blocked.length === 0, "preview");
      const stored = storedObject(runsDir, run, made.handle);
      const sent = await confirmAndSend(page, b, run, controlDir, "slow", log, evidence, async () => {
        await waitFor(page, async () => fs.existsSync(path.join(controlDir, "inflight.json")) ? true : null, "reply held", 15000);
        const sending = await lt(page, b, "jev-loop-sending").count();
        await setConsent(page, b, run, false, log, evidence);
        const line = await globalLine(page);
        fs.writeFileSync(path.join(controlDir, "release"), "release\n");
        return { sending, line };
      });
      await lp(page, b).locator(`[data-testid="jev-loop-opened-send"]${attr("data-send-id", sent.record.send_id)}`)
        .waitFor({ timeout: 30000 });
      const card = await readCard(page, b, sent.record.send_id);
      const attrs = await recordWhen(page, b, item => item.action === "select" && item.iteration === "2", "still selecting");
      const wording = await wordingCheck(page, b, "late card", evidence);
      await setConsent(page, b, run, true, log, evidence);
      return { record, made, shown, stored, sent, card, attrs, wording, loop: await readLoop(page, run, loopA.loopId) };
    }, async value => {
      assert.deepEqual(value.wording, []);
      previewMatches({ shown: value.shown, built: value.made, stored: value.stored, record: value.record, iteration: 2,
        ordinal: 1, runId: run });
      const record = value.sent.record;
      assert.equal(value.sent.extra.sending, 1);
      assert.equal(value.sent.extra.line.badge, null);
      assert.deepEqual([record.status, record.late, record.late_reason], ["completed", true, "consent_off"]);
      assert.equal(value.sent.calls[0].released, true);
      const choice = storedObject(runsDir, run, record.choice_handle);
      const card = cardMatches(value.card, record, choice, value.stored, { late: true, isSelection: false, iteration: 2 });
      assert.equal(card.container, "jev-loop-opened-send");
      assert.deepEqual([value.attrs.phase, value.attrs.action], ["awaiting_selection", "select"]);
      const it = value.loop.iterations.find(item => item.index === 2);
      assert.equal(it.decided_by, null);
      assert.ok(it.sends.some(item => item.send_id === record.send_id && item.late === true));
      serverBytes(runsDir, run, record.send_id, value.shown.body, value.made.preview.body_sha256, value.sent.calls);
      sends.push(record);
      lateRef = choice.answer.local_ref.candidate_id;
      return { card, lateRef };
    });
    await rec_.step("L13-designate", ["L-designate", "L-real-engine"], "직접 지정 (no new send) the candidate the late " +
      "reply named, check the compute confirmation, press 고른 후보로 계산 시작: decided_by human, the real docking runs, " +
      "iteration 2 ends scored", async () => {
      await lp(page, b).locator(`input[data-testid="jev-loop-designate-option"]${attr("data-ref", lateRef)}`).check();
      control(evidence, "jev-loop-designate-option", { ref: lateRef });
      const entry = await pressCompute(page, b, run, loopA.loopId, "jev-loop-designate", log, evidence);
      const attrs = await recordWhen(page, b, item => item.iteration === "3" && item.action === "select", "iteration 3", 120000);
      return { entry, attrs, record: await readLoop(page, run, loopA.loopId), table: await candidateTable(page, b) };
    }, async value => {
      assert.equal(value.entry.status, 200);
      assert.deepEqual(value.entry.request, { iteration: 2, candidate: lateRef });
      const it = value.record.iterations.find(item => item.index === 2);
      assert.deepEqual([it.state, it.decided_by, it.candidate_ref, it.proposal_handle], ["scored", "human", lateRef, null]);
      const result = storedObject(runsDir, run, it.steps[0].result_handle);
      assert.equal(it.score_kcal_mol, result.modes[0].score_kcal_mol);
      candidateRowsMatch(value.table, value.record);
      assert.equal(value.record.counts.human_decided, 1);
      return { ref: lateRef, score: it.score_kcal_mol };
    });
  });

  // ---- iteration 3: a designation with no send at all, the table orders, end, summary, report
  let summaryA = null;
  await rec_.part("L-iter3-end", ["L-designate-no-send", "L-candidate-table", "L-end-summary", "L-report"], async () => {
    await rec_.step("L14-designate-no-send", ["L-designate-no-send", "L-real-engine"], "Iteration 3: with no send, 직접 지정 " +
      "the first selectable candidate and start it: decided_by human, scored; the loop reaches its effective cap " +
      "(exhausted iteration_cap, action end)", async () => {
      const options = await lp(page, b).locator('input[data-testid="jev-loop-designate-option"]').evaluateAll(items =>
        items.map(item => item.getAttribute("data-ref")));
      await lp(page, b).locator(`input[data-testid="jev-loop-designate-option"]${attr("data-ref", options[0])}`).check();
      control(evidence, "jev-loop-designate-option", { ref: options[0] });
      const entry = await pressCompute(page, b, run, loopA.loopId, "jev-loop-designate", log, evidence);
      const attrs = await recordWhen(page, b, item => item.action === "end", "exhausted", 120000);
      return { options, entry, attrs, record: await readLoop(page, run, loopA.loopId),
        exhausted: clean(await lt(page, b, "jev-loop-exhausted").textContent()) };
    }, async value => {
      assert.equal(value.options.length, LOOP_A.size - 2);
      assert.deepEqual(value.entry.request, { iteration: 3, candidate: value.options[0] });
      const it = value.record.iterations.find(item => item.index === 3);
      assert.deepEqual([it.state, it.decided_by, it.sends.length], ["scored", "human", 0]);
      assert.equal(value.record.exhausted_reason, "iteration_cap");
      assert.ok(value.exhausted.includes("(iteration_cap)"), value.exhausted);
      assert.deepEqual(value.record.counts, { started: 3, done: 3, jev_decided: 1, human_decided: 2, sends_dispatched: 4,
        units_charged: 3, reused_count: 0 });
      return { ref: value.options[0] };
    });
    await rec_.step("L15-candidate-table", ["L-candidate-table"], "Candidate table: score cells = the stored first modes " +
      "(one decimal), rows without a score show — with the reason; click the score header (ascending, then descending), " +
      "the iteration and candidate headers: rows with a score are ordered by the column and every row without a score " +
      "stays last in pool order; aria-sort follows; no position-number column", async () => {
      const record = await readLoop(page, run, loopA.loopId);
      const initial = await candidateTable(page, b);
      const orders = {};
      for (const key of ["score", "iteration", "candidate"]) {
        for (const direction of ["asc", "desc"]) {
          await lt(page, b, `jev-loop-sort-${key}`).click();
          control(evidence, `jev-loop-sort-${key}`, { direction });
          const want = direction === "asc" ? "ascending" : "descending";
          orders[`${key}-${direction}`] = await waitFor(page, async () => {
            const table = await candidateTable(page, b);
            return table.ariaSort.includes(want) ? table : null;
          }, `${key} ${direction}`, 15000);
        }
      }
      return { record, initial, orders, note: clean(await lt(page, b, "jev-loop-order-note").textContent()),
        wording: await wordingCheck(page, b, "candidate table", evidence) };
    }, async value => {
      assert.deepEqual(value.wording, []);
      candidateRowsMatch(value.initial, value.record);
      assert.deepEqual(value.initial.headers, ["풀 순서", "후보", "표기", "상태", SCORE_COLUMN, "바퀴", "선택 주체", "평가", "상세"]);
      const pool = value.record.candidates.map(item => String(item.ref));
      const scores = Object.fromEntries(value.record.candidates.map(item => [String(item.ref), item.score_kcal_mol]));
      const its = Object.fromEntries(value.record.candidates.map(item => [String(item.ref), item.iteration]));
      for (const [name, table] of Object.entries(value.orders)) {
        const flags = table.rows.map(row => row.hasScore);
        const firstNo = flags.indexOf(false);
        assert.ok(firstNo > 0 && flags.slice(firstNo).every(flag => !flag), `${name}: a row without a score is not last`);
        const tail = table.rows.slice(firstNo).map(row => row.ref);
        assert.deepEqual(tail, pool.filter(ref => tail.includes(ref)), `${name}: no-score rows not in pool order`);
        const head = table.rows.slice(0, firstNo).map(row => row.ref);
        const [key, direction] = name.split("-");
        const sign = direction === "asc" ? 1 : -1;
        const value_ = ref => key === "score" ? scores[ref] : key === "iteration" ? its[ref] : ref;
        for (let i = 1; i < head.length; i++) {
          const a = value_(head[i - 1]), z = value_(head[i]);
          assert.ok(sign * (a < z ? -1 : a > z ? 1 : 0) <= 0, `${name}: ${head.join(",")}`);
        }
        candidateRowsMatch(table, value.record);
      }
      assert.equal(value.note, "표의 정렬은 표시 순서일 뿐입니다. 점수 없는 후보는 0이 아니며 어떤 정렬에서도 끝에 둡니다.");
      return Object.fromEntries(Object.entries(value.orders).map(([name, table]) => [name, table.rows.map(row =>
        `${row.ref.slice(0, 8)}:${row.score}`)]));
    });
    summaryA = await rec_.step("L16-end", ["L-end-summary"], "루프 끝내기: ended (iteration_cap); the summary " +
      "jev_loop_result@1 is stored (counts, scores = stored first modes, the JEV-decided iteration's list position); the " +
      "record's sentences add LJ8 (two candidates were not computed); 루프 만들기 opens again", async () => {
      const since = Date.now();
      await lt(page, b, "jev-loop-end").click();
      control(evidence, "jev-loop-end", { loopId: loopA.loopId });
      const entry = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev_loops/${loopA.loopId}/end`,
        "end answer", 120000);
      const ended = await waitFor(page, async () => (await lt(page, b, "jev-loop-ended").count()) ? {
        reason: await lt(page, b, "jev-loop-ended").getAttribute("data-end-reason"),
        result: await lt(page, b, "jev-loop-ended").getAttribute("data-result-handle"),
        status: clean(await lt(page, b, "jev-loop-ended-status").textContent()) } : null, "ended shown", 30000);
      const record = await readLoop(page, run, loopA.loopId);
      return { entry, ended, record, summary: storedObject(runsDir, run, ended.result),
        limitations: await lt(page, b, "jev-loop-limitations").locator("li").evaluateAll(items => items.map(item => item.textContent)),
        createBlocked: await lt(page, b, "jev-loop-create-blocked").count() };
    }, async value => {
      assert.equal(value.entry.status, 200);
      assert.deepEqual([value.ended.reason, value.record.end_reason, value.record.status], ["iteration_cap", "iteration_cap", "ended"]);
      assert.ok(value.ended.status.includes("(iteration_cap)"));
      const summary = value.summary;
      assert.equal(summary.schema, "jev_loop_result@1");
      assert.equal(summary.end_reason, "iteration_cap");
      assert.deepEqual(summary.counts, value.record.counts);
      for (const row of summary.candidates) {
        const it = summary.iterations.find(item => item.candidate_ref === row.ref);
        if (row.state === "scored") {
          const step = it.steps.find(item => item.step === "ligand_dock");
          assert.equal(row.score_kcal_mol, storedObject(runsDir, run, step.result_handle).modes[0].score_kcal_mol);
        } else assert.equal(row.score_kcal_mol, null);
      }
      const jev = summary.iterations.find(item => item.decided_by === "jev");
      assert.equal(`${jev.list_position}/${jev.list_size}`, goodSend.position);
      assert.deepEqual(summary.unfinished, []);
      assert.ok(!keysOf(summary).some(key => /rank|best|improv|recommend|probabilit/i.test(key)), "a forbidden key in the summary");
      assert.deepEqual(value.limitations, expectedLimitations("ligand", "exploit", { ended: true, uncomputed: true }));
      assert.equal(value.createBlocked, 0);
      return { result: value.ended.result, counts: summary.counts };
    });
    await rec_.step("L17-report", ["L-report"], "보고서 만들기 (JEV 루프 보고서): saved; 지식·보고서 lists JEV 루프 보고서; clicking " +
      "it shows the saved Markdown (LJ1-LJ4, LJ6, LJ8; no per-candidate probabilities; no forbidden word)", async () => {
      const entry = await makeLoopReport(page, b, run, log, evidence);
      const report = await libraryReport(page, run, entry.json.handle, evidence);
      return { entry, report };
    }, async value => {
      assert.equal(value.entry.json.manifest.analysis_type, "jev_loop");
      assert.equal(value.entry.json.manifest.result_handle, summaryA.result);
      return reportMatches(value.report, storedObject(runsDir, run, summaryA.result), "ligand", "exploit", evidence);
    });
  });

  // ---- loop B (explore; a stored result reused): no usage → egress stopped; loop C: the stop refuses the send
  await rec_.part("L-loop-b", ["L-reuse", "L-no-usage-stop", "L-send-cap-display"], async () => {
    const reusedRef = goodSend?.ref;
    const poolB = ids.filter(id => id === reusedRef || id === ids[5] || id === ids[6]);
    let loopB = null;
    loopB = await rec_.step("L18-reuse", ["L-reuse"], "Back on 리간드 설계·탐색 (the area mounts afresh): a new loop (탐색형, " +
      "seed 99, cap 2) over the iteration-1 candidate and two candidates no loop computed: the first is already computed " +
      "(the stored M18 result of the same call key: scored, 저장된 결과 재사용, no iteration, no unit); the others pending",
    async () => {
      await openLoopArea(page, b, log);
      await chooseSource(page, b, L.ligandSet.handle, ids.length, evidence);
      await checkKeys(page, b, poolB, evidence);
      await settings(page, b, { goal: LOOP_B.goal, seed: LOOP_B.seed, cap: LOOP_B.cap }, evidence);
      await ligandSetupInputs(page, L, evidence);
      const entry = await createLoop(page, b, run, log, evidence);
      await recordWhen(page, b, value => value.loopId === entry.json?.loop_id, "loop B opened", 30000);
      return { entry, record: await readLoop(page, run, entry.json.loop_id), table: await candidateTable(page, b),
        budget: await readApi(page, `/runs/${run}/budget`) };
    }, async value => {
      assert.equal(value.entry.status, 200, JSON.stringify(value.entry.json).slice(0, 600));
      const reused = value.record.candidates.find(item => item.ref === reusedRef);
      assert.deepEqual([reused.state, reused.evaluation, reused.iteration], ["scored", "reused", null]);
      assert.equal(typeof reused.score_kcal_mol, "number");
      assert.equal(value.record.counts.reused_count, 1);
      assert.equal(value.record.counts.units_charged, 0);
      const row = value.table.rows.find(item => item.ref === reusedRef);
      assert.ok(row.cells.some(cell => cell.includes("저장된 결과 재사용")), row.cells.join(" | "));
      candidateRowsMatch(value.table, value.record);
      assert.equal(value.budget.expensive_calls.used, 5, "the reuse charged a unit");
      return { loopId: value.entry.json.loop_id, reused: reusedRef };
    });
    await rec_.step("L19-no-usage", ["L-no-usage-stop", "L-order-oracle", "L-bytes-equal"], "Loop B: 보낼 내용 만들기 " +
      "(explore: the computed row is the alias only, no score), send (fixture no_usage): completed with every usage value " +
      "알 수 없음; the run's egress stops (usage_unknown) and the status notes say so", async () => {
      const record = await readLoop(page, run, loopB.loopId);
      const made = await build(page, b, run, log, evidence);
      const shown = await previewWhen(page, b, made.handle, item => item.blocked.length === 0, "preview");
      const stored = storedObject(runsDir, run, made.handle);
      const sent = await confirmAndSend(page, b, run, controlDir, "no_usage", log, evidence);
      await lp(page, b).locator(`[data-testid="jev-loop-selection"]${attr("data-send-id", sent.record.send_id)}`)
        .waitFor({ timeout: 30000 });
      const card = await readCard(page, b, sent.record.send_id);
      const notes = await waitFor(page, async () => (await lt(page, b, "jev-loop-status-notes").count())
        ? clean(await lt(page, b, "jev-loop-status-notes").textContent()) : null, "status notes", 15000);
      return { record, made, shown, stored, sent, card, notes, status: await readApi(page, `/runs/${run}/jev/status`) };
    }, async value => {
      const identity = previewMatches({ shown: value.shown, built: value.made, stored: value.stored, record: value.record,
        iteration: 1, ordinal: 0, runId: run });
      assert.deepEqual(identity.computed.map(item => Object.keys(item)), [["alias"]], "explore sent more than the alias");
      const record = value.sent.record;
      assert.equal(record.status, "completed");
      const choice = storedObject(runsDir, run, record.choice_handle);
      cardMatches(value.card, record, choice, value.stored, { late: false, isSelection: true, iteration: 1 });
      assert.deepEqual(Object.values(value.card.usage), Array(4).fill(UNKNOWN_USAGE));
      assert.ok(value.notes.includes("(usage_unknown)"), value.notes);
      assert.equal(value.status.egress_stop_reason, "usage_unknown");
      serverBytes(runsDir, run, record.send_id, value.shown.body, value.made.preview.body_sha256, value.sent.calls);
      sends.push(record);
      return { notes: value.notes, usage: value.card.usage };
    });
    await rec_.step("L20-stop-refuses", ["L-no-usage-stop", "L-send-cap-display"], "End loop B (ended_by_user, LJ5, LJ6, " +
      "LJ8); a loop C (활용형, two other candidates): 보낼 내용 만들기 shows egress_stopped and the send stays closed even with " +
      "the confirmation; the cap line shows the run's dispatches (5 of 10); end loop C", async () => {
      const since = Date.now();
      await lt(page, b, "jev-loop-end").click();
      control(evidence, "jev-loop-end", { loopId: loopB.loopId });
      const endB = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev_loops/${loopB.loopId}/end`,
        "end B", 60000);
      const recordB = await readLoop(page, run, loopB.loopId);
      const poolC = [ids[7], ids[8]];
      await chooseSource(page, b, L.ligandSet.handle, ids.length, evidence);
      await uncheckAll(page, b, evidence);
      await checkKeys(page, b, poolC, evidence);
      await settings(page, b, { goal: LOOP_C.goal, seed: LOOP_C.seed, cap: LOOP_C.cap }, evidence);
      const entry = await createLoop(page, b, run, log, evidence);
      await recordWhen(page, b, value => value.loopId === entry.json?.loop_id, "loop C opened", 30000);
      const made = await build(page, b, run, log, evidence);
      const shown = await previewWhen(page, b, made.handle, item => item.blocked.length > 0, "egress_stopped shown");
      await lt(page, b, "jev-loop-confirm").check();
      const send = await sendState(page, b);
      const cap = { used: await lt(page, b, "jev-loop-cap").getAttribute("data-used"),
        remaining: await lt(page, b, "jev-loop-cap").getAttribute("data-remaining"),
        text: clean(await lt(page, b, "jev-loop-cap").textContent()) };
      const since2 = Date.now();
      await lt(page, b, "jev-loop-end").click();
      control(evidence, "jev-loop-end", { loopId: entry.json.loop_id });
      const endC = await waitApi(page, log, since2, item => item.path === `/api/runs/${run}/jev_loops/${entry.json.loop_id}/end`,
        "end C", 60000);
      return { endB, recordB, entry, shown, send, cap, endC, recordC: await readLoop(page, run, entry.json.loop_id),
        dispatched: dispatchCounts(runsDir)[run] };
    }, async value => {
      assert.equal(value.endB.status, 200);
      assert.equal(value.recordB.end_reason, "ended_by_user");
      assert.deepEqual(value.recordB.limitations, expectedLimitations("ligand", "explore", { ended: true, uncomputed: true }));
      assert.equal(value.entry.status, 200);
      assert.deepEqual(value.shown.blocked.map(item => item.code), ["egress_stopped"]);
      assert.equal(value.send.enabled, false);
      assert.ok(value.send.blockers.some(text => text.includes("(egress_stopped)")), value.send.blockers.join(" | "));
      assert.equal(value.dispatched, 5);
      assert.deepEqual([value.cap.used, value.cap.remaining], ["5", String(SEND_CAP - 5)]);
      assert.equal(value.endC.status, 200);
      assert.equal(value.recordC.end_reason, "ended_by_user");
      return { cap: value.cap, refused: value.send.blockers };
    });
  });

  // ---- 지식·보고서 loop rows, other tabs, the viewer
  await rec_.part("L-after", ["L-knowledge-rows", "L-other-tabs"], async () => {
    await rec_.step("L21-knowledge-rows", ["L-knowledge-rows"], "지식·보고서: every loop send of run L is a read-only row " +
      "with the JEV 루프 mark (iteration, send ordinal) and the way to the loop area; no open or 보고서 만들기 button on " +
      "those rows; the M24 wording rule holds in the JEV area", async () => knowledgeRows(page, run), async value => {
      const rows = knowledgeRowsMatch(value, TAB.ligand, sends);
      const found = m24ForbiddenWords(value.text);
      evidence.wording.push({ label: "knowledge JEV area (run L)", kind: "screen-m24", found });
      assert.deepEqual(found, []);
      return rows;
    });
    await rec_.step("L22-other-tabs", ["L-other-tabs"], "After every loop action of run L: the other areas of 리간드 " +
      "설계·탐색 and 단백질 공학 show the same digit-masked text (the M18 docking area lists the loop's standalone docking " +
      "results: kept as evidence), no POST on entry; 구조 분석 stayed hidden and inert; back on 구조 분석 the viewer is the " +
      "same session and source", async () => {
      const ligand = await tabAreas(page, "ligand", log);
      const protein = await tabAreas(page, "protein", log);
      await selectTab(page, TAB.structure);
      return { ligand: compareAreas(before.ligand, ligand, ["docking-panel"]), protein: compareAreas(before.protein, protein, []),
        posts: [...ligand.posts, ...protein.posts], structure: [ligand.structure, protein.structure],
        viewer: await viewerSnapshot(page) };
    }, async value => {
      for (const side of [value.ligand, value.protein]) {
        assert.deepEqual(side.order.after, side.order.before);
        for (const [id, item] of Object.entries(side.areas)) if (!item.listing) assert.equal(item.same, true, `${id} changed: ${JSON.stringify(item)}`);
      }
      assert.deepEqual(value.posts, []);
      for (const item of value.structure) assert.deepEqual(item, { shown: "false", inert: true });
      assert.equal(value.viewer.sessionId, viewerBefore.sessionId);
      assert.equal(value.viewer.sourceHandle, viewerBefore.sourceHandle);
      return { ligand: value.ligand, protein: value.protein };
    });
  });
  return { run, sends };
}

// ------------------------------------------------------------------ run P (protein, 1UBQ)
async function proteinBranch(session, input, setup, rec_, evidence, log) {
  const { page } = session;
  const runsDir = input["runs-dir"];
  const controlDir = input.control;
  const P = setup.runs.P;
  const run = P.run;
  const b = "protein";
  const sends = [];
  let viewerBefore = null;
  let before = null;
  let loop = null;
  let good = null;
  for (const index of PROTEIN_POOL) assert.ok(P.ubqSet.modelPool.includes(index), `pool candidate ${index} not modelled here`);

  await rec_.part("P-entry", ["P-tab-entry", "P-pool-limit", "P-create-fields", "P-create-refused"], async () => {
    viewerBefore = await rec_.step("P00-run", [], "구조 분석: run P chosen in the rail", () => chooseRun(page, run),
      async value => ({ sourceHandle: value.sourceHandle, sessionId: value.sessionId }));
    await rec_.step("P01-other-areas-before", [], "단백질 공학 and 리간드 설계·탐색 visited before any loop action " +
      "(the protein tab first, so the next step enters it afresh)", async () => {
      before = { protein: await tabAreas(page, "protein", log), ligand: await tabAreas(page, "ligand", log) };
      return before;
    }, async value => {
      for (const sig of Object.values(value)) assert.deepEqual(sig.posts, []);
      return { ligand: value.ligand.areas.map(item => item.id), protein: value.protein.areas.map(item => item.id) };
    });
    await rec_.step("P02-tab-entry", ["P-tab-entry"], "Click 단백질 공학: the JEV 루프 area mounts with GET reads only; consent " +
      "off; UL1, UL3 and U3; no loop; both mutation sets listed and none chosen; no goal; seed empty", async () => {
      const since = await openLoopArea(page, b, log);
      await waitFor(page, async () => (await lt(page, b, "jev-loop-sources").count()) ? true : null, "sources listed", 30000);
      return { posts: posts(log, since), reads: gets(log, since), state: await lp(page, b).getAttribute("data-jev-loop-state"),
        consent: await consentState(page, b), u3: await lt(page, b, "jev-loop-note-u3").textContent(),
        ul1: await lt(page, b, "jev-loop-note-ul1").textContent(), ul3: await lt(page, b, "jev-loop-note-ul3").textContent(),
        sources: await listedSources(page, b),
        goals: await lp(page, b).locator('input[data-testid^="jev-loop-goal-"]').evaluateAll(items => items.map(item => item.checked)),
        seed: await lt(page, b, "jev-loop-seed").inputValue(), createEnabled: await lt(page, b, "jev-loop-create").isEnabled(),
        structure: await structureHidden(page) };
    }, async value => {
      assert.deepEqual(value.posts, []);
      for (const route of ["jev/status", "jev_loops", "docking/prerequisites", "mutation_candidate_sets"])
        assert.ok(value.reads.some(item => item.endsWith(route)), `no GET ${route}: ${value.reads}`);
      assert.equal(value.state, "empty");
      assert.equal(value.consent, "off");
      assert.equal(value.u3, U.U3);
      assert.equal(value.ul1, UL.UL1);
      assert.equal(value.ul3, UL.UL3);
      assert.deepEqual(value.sources.map(item => item.handle).sort(), [P.ubqSet.handle, P.mq4Set.handle].sort());
      assert.ok(value.sources.every(item => !item.checked), "a set was chosen automatically");
      assert.deepEqual(value.goals, [false, false]);
      assert.equal(value.seed, "");
      assert.equal(value.createEnabled, false);
      assert.deepEqual(value.structure, { shown: "false", inert: true });
      return { reads: value.reads.length };
    });
    await rec_.step("P03-pool-limit", ["P-pool-limit"], "Choose the 1UBQ set (22 candidates), check 20: the area says the " +
      "pool is full; click the 21st: it stays unchecked and the reason is shown (20 kept); uncheck down to one: the pool " +
      "field says at least 2 (pool_invalid)", async () => {
      const rows = await chooseSource(page, b, P.ubqSet.handle, P.ubqSet.candidates, evidence);
      const want = rows.slice(0, MAX_POOL).map(row => row.key);
      await checkKeys(page, b, want, evidence);
      const full = await lt(page, b, "jev-loop-pool-full").count();
      const extra = rows[MAX_POOL].key;
      await candidateBox(page, b, extra).click();
      control(evidence, "jev-loop-candidate-21st", { key: extra });
      await lt(page, b, "jev-loop-pool-refused").waitFor({ timeout: 10000 });
      const after = await rowKeys(page, b);
      const capped = { full, refused: clean(await lt(page, b, "jev-loop-pool-refused").textContent()),
        count: await poolCount(page, b), extraRow: after.find(row => row.key === extra),
        checked: after.filter(row => row.checked).map(row => row.key) };
      await uncheckKeys(page, b, want.slice(1), evidence);
      return { want, capped, one: await poolCount(page, b), errors: await fieldErrors(page, b) };
    }, async value => {
      assert.equal(value.capped.full, 1);
      assert.equal(value.capped.count, MAX_POOL);
      assert.deepEqual(value.capped.checked, value.want);
      assert.equal(value.capped.extraRow.checked, false);
      assert.ok(value.capped.refused.includes(`${MAX_POOL}개`), value.capped.refused);
      assert.equal(value.capped.extraRow.blocked, value.capped.refused);
      assert.equal(value.one, 1);
      assert.ok(value.errors.pool.items.some(text => text.includes("2개 이상") && text.includes("(pool_invalid)")));
      return { refused: value.capped.refused };
    });
    await rec_.step("P04-create-fields", ["P-create-fields"], "Protein field reasons: no goal (goal_invalid), seed empty " +
      "(seed_invalid), iteration cap 0 (iteration_cap_invalid), the two modelling confirmations unchecked " +
      "(confirmation_missing) and cutoff 7 (argument_invalid); 루프 만들기 closed", async () => {
      await fill(page, b, "jev-loop-iteration-cap", "0", evidence);
      await proteinSetupInputs(page, P, evidence, { confirm: false, cutoff: "7" });
      return { errors: await fieldErrors(page, b), createEnabled: await lt(page, b, "jev-loop-create").isEnabled() };
    }, async value => {
      assert.equal(value.createEnabled, false);
      assert.ok(value.errors.goal.items.some(text => text.includes("(goal_invalid)")));
      assert.ok(value.errors.loop_seed.items.some(text => text.includes("(seed_invalid)")));
      assert.ok(value.errors.iteration_cap.items.some(text => text.includes("(iteration_cap_invalid)")));
      assert.ok(value.errors.setup.items.some(text => text.includes("(confirmation_missing)")), JSON.stringify(value.errors.setup));
      assert.ok(value.errors.setup.items.some(text => text.includes("(argument_invalid)")), JSON.stringify(value.errors.setup));
      return value.errors;
    });
    await rec_.step("P05-create-refused", ["P-create-refused"], "Fix every field and choose the 1MQ4 set with two " +
      "candidates; 루프 만들기: the server refuses (422 setup_invalid, setup_reason openmm_preflight_failed: 1MQ4 cannot be " +
      "modelled) and the setup field shows it; no jev_loop_created event, no loop listed", async () => {
      await settings(page, b, { goal: LOOP_P.goal, seed: LOOP_P.seed, cap: LOOP_P.cap }, evidence);
      await proteinSetupInputs(page, P, evidence);
      const rows = await chooseSource(page, b, P.mq4Set.handle, P.mq4Set.candidates, evidence);
      await checkKeys(page, b, rows.slice(0, 2).map(row => row.key), evidence);
      const entry = await createLoop(page, b, run, log, evidence);
      const refusal = await waitFor(page, async () => {
        const errors = await fieldErrors(page, b);
        return errors.setup.refusal ? errors : null;
      }, "server refusal shown", 30000);
      return { entry, refusal, events: eventCount(runsDir, run, "jev_loop_created"),
        list: await readApi(page, `/runs/${run}/jev_loops`) };
    }, async value => {
      assert.equal(value.entry.status, 422, JSON.stringify(value.entry.json).slice(0, 400));
      assert.equal(value.entry.json.detail.reason_code, "setup_invalid");
      assert.equal(value.entry.json.detail.setup_reason, "openmm_preflight_failed");
      assert.deepEqual([value.refusal.setup.refusal.field, value.refusal.setup.refusal.code], ["setup", "setup_invalid"]);
      assert.ok(value.refusal.setup.refusal.text.includes("(openmm_preflight_failed)"), value.refusal.setup.refusal.text);
      assert.equal(value.events, 0);
      assert.deepEqual(value.list, []);
      return value.refusal.setup.refusal;
    });
  });

  await rec_.part("P-create", ["P-create"], async () => {
    loop = await rec_.step("P06-create", ["P-create"], "Choose the 1UBQ set again and the pool (L15A, I30A, I44A): 루프 " +
      "만들기: jev_loop_created; active, iteration 1, step model; loop_active closes 루프 만들기", async () => {
      await chooseSource(page, b, P.ubqSet.handle, P.ubqSet.candidates, evidence);
      await checkKeys(page, b, PROTEIN_POOL.map(String), evidence);
      const entry = await createLoop(page, b, run, log, evidence);
      const attrs = await recordWhen(page, b, value => value.loopId === entry.json?.loop_id, "loop opened", 30000);
      const blocked = await waitFor(page, async () => (await lt(page, b, "jev-loop-create-blocked").count())
        ? clean(await lt(page, b, "jev-loop-create-blocked").textContent()) : null, "create blocked", 15000);
      return { entry, attrs, blocked, record: await readLoop(page, run, entry.json.loop_id) };
    }, async value => {
      assert.equal(value.entry.status, 200, JSON.stringify(value.entry.json).slice(0, 600));
      const request = value.entry.request;
      assert.deepEqual(request.pool, { source: P.ubqSet.handle, candidates: PROTEIN_POOL, filter: null });
      assert.deepEqual(request.setup.ligand, { source: "sdf", sdf_handle: P.phenol });
      assert.deepEqual([request.setup.selection_policy, request.setup.hydrogen_policy, request.setup.contact_cutoff_A],
        ["protein_only", "rebuild_pH7", 4]);
      assert.deepEqual(value.attrs, { loopId: request.loop_id, status: "active", action: "select", phase: "awaiting_selection",
        iteration: "1", step: "model" });
      assert.equal(value.record.effective_cap, 2);
      assert.deepEqual(value.record.limitations, expectedLimitations("mutation", "explore"));
      assert.ok(value.blocked.includes("(loop_active)"));
      return { loopId: request.loop_id };
    });
  });
  if (!loop?.loopId) return { run, sends };

  await rec_.part("P-iter1", ["P-send-good", "P-bytes-equal", "P-order-oracle", "P-first-approval", "P-end-refused-job",
    "P-end-refused-docking", "P-dock", "P-real-engine"], async () => {
    good = await rec_.step("P07-good", ["P-send-good", "P-bytes-equal", "P-order-oracle"], "Consent on (this run); 보낼 내용 " +
      "만들기: the mutation body (oracle order, explore question text, no coordinate, sequence, numbering, handle or id); " +
      "confirmation; send (fixture good): the JEV card with the residue notation and list position n/3", async () => {
      await setConsent(page, b, run, true, log, evidence);
      const record = await readLoop(page, run, loop.loopId);
      const made = await build(page, b, run, log, evidence);
      const shown = await previewWhen(page, b, made.handle, item => item.blocked.length === 0, "preview");
      const stored = storedObject(runsDir, run, made.handle);
      const sent = await confirmAndSend(page, b, run, controlDir, "good", log, evidence);
      await lp(page, b).locator(`[data-testid="jev-loop-selection"]${attr("data-send-id", sent.record.send_id)}`)
        .waitFor({ timeout: 30000 });
      const card = await readCard(page, b, sent.record.send_id);
      return { record, made, shown, stored, sent, card, wording: await wordingCheck(page, b, "protein good card", evidence) };
    }, async value => {
      assert.deepEqual(value.wording, []);
      const identity = previewMatches({ shown: value.shown, built: value.made, stored: value.stored, record: value.record,
        iteration: 1, ordinal: 0, runId: run });
      assert.deepEqual(identity.computed, []);
      const record = value.sent.record;
      assert.equal(record.status, "completed");
      const choice = storedObject(runsDir, run, record.choice_handle);
      const card = cardMatches(value.card, record, choice, value.stored, { late: false, isSelection: true, iteration: 1 });
      assert.equal(card.position, `1/${PROTEIN_POOL.length}`);
      const bytes = serverBytes(runsDir, run, record.send_id, value.shown.body, value.made.preview.body_sha256, value.sent.calls);
      sends.push(record);
      return { card, bytes, choiceHandle: record.choice_handle, ref: choice.answer.local_ref.candidate_index };
    });
    await rec_.step("P08-first-approval", ["P-first-approval", "P-end-refused-job"], "이 선택으로 계산 시작: the M21 job is " +
      "made and waits for the run's first expensive-call approval (200, start_blocked approval_required): the guide and " +
      "비싼 계산 승인 show and 루프 끝내기 is closed with job_running; press 비싼 계산 승인 (POST /jobs/approve): the notice; " +
      "press 작업 시작: the same step again (no new approval event), the real PDBFixer/OpenMM model runs and the iteration " +
      "awaits its docking", async () => {
      const entry = await pressCompute(page, b, run, loop.loopId, "jev-loop-compute-proposal", log, evidence, { timeout: 120000 });
      const blocked = await waitFor(page, async () => (await lt(page, b, "jev-loop-approval-guide").count()) ? {
        guide: clean(await lt(page, b, "jev-loop-approval-guide").textContent()),
        job: { status: await lt(page, b, "jev-loop-job").getAttribute("data-job-status"),
          startBlocked: await lt(page, b, "jev-loop-job").getAttribute("data-start-blocked") } } : null, "approval guide", 30000);
      const attrs = await recordAttrs(page, b);
      const end = await endState(page, b);
      const approvalsBefore = eventCount(runsDir, run, "jev_loop_compute_approved");
      const since = Date.now();
      await lt(page, b, "jev-loop-approve-first").click();
      control(evidence, "jev-loop-approve-first", { run });
      const approved = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jobs/approve`, "approve", 30000);
      const notice = await waitFor(page, async () => (await lt(page, b, "jev-loop-job-notice").count())
        ? clean(await lt(page, b, "jev-loop-job-notice").textContent()) : null, "approval notice", 15000);
      await waitFor(page, async () => await lt(page, b, "jev-loop-job-start").isEnabled() ? true : null, "job start enabled", 30000);
      const since2 = Date.now();
      await lt(page, b, "jev-loop-job-start").click();
      control(evidence, "jev-loop-job-start", { run });
      const resumed = await waitApi(page, log, since2, item => item.path === `/api/runs/${run}/jev_loops/${loop.loopId}/compute`,
        "job start answer", 600000);
      const docking = await recordWhen(page, b, item => item.action === "dock", "awaiting docking", 120000);
      return { entry, blocked, attrs, end, approved, notice, resumed, docking,
        approvalsAfter: eventCount(runsDir, run, "jev_loop_compute_approved"), approvalsBefore,
        record: await readLoop(page, run, loop.loopId) };
    }, async value => {
      assert.equal(value.entry.status, 200, JSON.stringify(value.entry.json).slice(0, 600));
      assert.deepEqual(value.entry.request, { iteration: 1, proposal: good.choiceHandle });
      assert.equal(value.entry.json.current.job.start_blocked, "approval_required");
      assert.ok(value.blocked.guide.includes("(approval_required)"), value.blocked.guide);
      assert.equal(value.blocked.job.startBlocked, "approval_required");
      assert.deepEqual([value.attrs.action, value.attrs.phase], ["wait_job", "running"]);
      assert.equal(value.end.enabled, false);
      assert.ok(value.end.reasons.some(text => text.includes("(job_running)")), value.end.reasons.join(" | "));
      assert.equal(value.approved.status, 200);
      assert.equal(value.notice, APPROVAL_NOTICE);
      assert.equal(value.resumed.status, 200, JSON.stringify(value.resumed.json).slice(0, 600));
      assert.deepEqual(value.resumed.request, { iteration: 1, proposal: good.choiceHandle });
      assert.equal(value.approvalsAfter, value.approvalsBefore, "the job start wrote a second approval");
      assert.deepEqual([value.docking.phase, value.docking.step], ["awaiting_docking", "dock"]);
      const step = value.record.iterations[0].steps.find(item => item.step === "model");
      assert.equal(step.state, "completed");
      assert.equal(storedObject(runsDir, run, step.result_handle).schema.startsWith("mutation_model"), true);
      return { model: step.result_handle, job: step.job_id };
    });
    await rec_.step("P09-dock", ["P-end-refused-docking", "P-dock", "P-real-engine"], "Awaiting docking: 루프 끝내기 is closed " +
      "with docking_pending; check the compute confirmation and press 도킹 시작: the M18 docking into the mutant model " +
      "runs (real qvina) and iteration 1 ends scored (score = the stored first mode)", async () => {
      const end = await endState(page, b);
      const entry = await pressCompute(page, b, run, loop.loopId, "jev-loop-dock", log, evidence);
      const attrs = await recordWhen(page, b, item => item.iteration === "2" && item.action === "select", "iteration 2", 120000);
      return { end, entry, attrs, record: await readLoop(page, run, loop.loopId), table: await candidateTable(page, b) };
    }, async value => {
      assert.equal(value.end.enabled, false);
      assert.ok(value.end.reasons.some(text => text.includes("(docking_pending)")), value.end.reasons.join(" | "));
      assert.deepEqual(value.entry.request, { iteration: 1 });
      const it = value.record.iterations[0];
      assert.deepEqual([it.state, it.decided_by], ["scored", "jev"]);
      const dock = it.steps.find(item => item.step === "dock");
      assert.equal(dock.state, "completed");
      const result = storedObject(runsDir, run, dock.result_handle);
      assert.equal(it.score_kcal_mol, result.modes[0].score_kcal_mol);
      assert.deepEqual(result.inputs.receptor.source, { kind: "mutation_model", side: "mutant",
        mutation_model: value.record.iterations[0].steps.find(item => item.step === "model").result_handle });
      candidateRowsMatch(value.table, value.record);
      return { dock: dock.result_handle, score: it.score_kcal_mol };
    });
  });

  let summary = null;
  await rec_.part("P-iter2-end", ["P-abandon", "P-end-summary", "P-report"], async () => {
    await rec_.step("P10-abandon", ["P-abandon", "P-real-engine"], "Iteration 2 (no send): 직접 지정 the first selectable " +
      "candidate; the model runs (no second approval); awaiting docking; press 도킹 포기: the candidate is not_run " +
      "(docking_not_run) and the loop reaches its effective cap", async () => {
      const options = await lp(page, b).locator('input[data-testid="jev-loop-designate-option"]').evaluateAll(items =>
        items.map(item => item.getAttribute("data-ref")));
      await lp(page, b).locator(`input[data-testid="jev-loop-designate-option"]${attr("data-ref", options[0])}`).check();
      control(evidence, "jev-loop-designate-option", { ref: options[0] });
      const entry = await pressCompute(page, b, run, loop.loopId, "jev-loop-designate", log, evidence);
      await recordWhen(page, b, item => item.action === "dock" && item.iteration === "2", "awaiting docking 2", 120000);
      const since = Date.now();
      await lt(page, b, "jev-loop-abandon").click();
      control(evidence, "jev-loop-abandon", { loopId: loop.loopId });
      const abandoned = await waitApi(page, log, since, item =>
        item.path === `/api/runs/${run}/jev_loops/${loop.loopId}/abandon_docking`, "abandon", 60000);
      const attrs = await recordWhen(page, b, item => item.action === "end", "exhausted", 60000);
      return { options, entry, abandoned, attrs, record: await readLoop(page, run, loop.loopId),
        table: await candidateTable(page, b),
        iterationText: clean(await lt(page, b, "jev-loop-iterations").locator('tr[data-iteration="2"]').textContent()) };
    }, async value => {
      assert.equal(value.entry.status, 200);
      assert.equal(value.abandoned.status, 200, JSON.stringify(value.abandoned.json).slice(0, 400));
      assert.deepEqual(value.abandoned.request, { iteration: 2 });
      const it = value.record.iterations.find(item => item.index === 2);
      assert.deepEqual([it.state, it.decided_by], ["not_run", "human"]);
      const candidate = value.record.candidates.find(item => String(item.ref) === value.options[0]);
      assert.deepEqual([candidate.state, candidate.score_kcal_mol], ["not_run", null]);
      const row = value.table.rows.find(item => item.ref === value.options[0]);
      assert.equal(row.state, "not_run");
      assert.ok(row.score.startsWith(NULL_TEXT) && row.score.includes("(docking_not_run)"), row.score);
      assert.ok(value.iterationText.includes("(not_run)"), value.iterationText);
      candidateRowsMatch(value.table, value.record);
      assert.equal(value.record.exhausted_reason, "iteration_cap");
      assert.equal(value.record.counts.units_charged, 3);
      return { ref: value.options[0] };
    });
    summary = await rec_.step("P11-end", ["P-end-summary"], "루프 끝내기: ended (iteration_cap), the summary stored, LJ1-LJ3, " +
      "LJ5, LJ7 and LJ8", async () => {
      const since = Date.now();
      await lt(page, b, "jev-loop-end").click();
      control(evidence, "jev-loop-end", { loopId: loop.loopId });
      const entry = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev_loops/${loop.loopId}/end`,
        "end answer", 60000);
      const result = await waitFor(page, async () => (await lt(page, b, "jev-loop-ended").count())
        ? lt(page, b, "jev-loop-ended").getAttribute("data-result-handle") : null, "ended", 30000);
      return { entry, result, record: await readLoop(page, run, loop.loopId),
        limitations: await lt(page, b, "jev-loop-limitations").locator("li").evaluateAll(items => items.map(item => item.textContent)) };
    }, async value => {
      assert.equal(value.entry.status, 200);
      assert.equal(value.record.end_reason, "iteration_cap");
      const stored = storedObject(runsDir, run, value.result);
      assert.equal(stored.end_reason, "iteration_cap");
      assert.equal(stored.counts.units_charged, 3);
      assert.deepEqual(value.limitations, expectedLimitations("mutation", "explore", { ended: true, uncomputed: true }));
      return { result: value.result };
    });
    await rec_.step("P12-report", ["P-report"], "보고서 만들기: saved and listed as JEV 루프 보고서 with the saved Markdown",
      async () => {
        const entry = await makeLoopReport(page, b, run, log, evidence);
        return { entry, report: await libraryReport(page, run, entry.json.handle, evidence) };
      }, async value => reportMatches(value.report, storedObject(runsDir, run, summary.result), "mutation", "explore", evidence));
  });

  // ---- a second protein loop (exploit): the computed candidate reused; HTTP 500 (the run's egress stops: last send)
  await rec_.part("P-second", ["P-reuse", "P-failed-http", "P-bytes-equal", "P-order-oracle"], async () => {
    const reusedRef = good?.ref;
    const pool = [1, 2, reusedRef].filter(item => item !== undefined).sort((x, y) => x - y);
    await rec_.step("P13-reuse-http", ["P-reuse", "P-failed-http", "P-bytes-equal", "P-order-oracle"], "Back on 단백질 " +
      "공학 (the area mounts afresh): a second loop (활용형, seed 13, cap 1) over I3A, V5A and the iteration-1 candidate " +
      "(its stored model and mutant docking: reused, scored, no unit); 보낼 내용 만들기: the exploit computed row carries " +
      "the reused alias with its stored score as is; send (fixture http_500): failed provider_http_error, the reason only; " +
      "bytes equal; the run's egress stops (usage_unknown) and the preview lists egress_stopped; end the loop", async () => {
      await openLoopArea(page, b, log);
      await chooseSource(page, b, P.ubqSet.handle, P.ubqSet.candidates, evidence);
      await checkKeys(page, b, pool.map(String), evidence);
      await settings(page, b, { goal: "exploit", seed: "13", cap: "1" }, evidence);
      await proteinSetupInputs(page, P, evidence);
      const entry = await createLoop(page, b, run, log, evidence);
      await recordWhen(page, b, value => value.loopId === entry.json?.loop_id, "second loop opened", 30000);
      const record = await readLoop(page, run, entry.json.loop_id);
      const made = await build(page, b, run, log, evidence);
      const shown = await previewWhen(page, b, made.handle, item => item.blocked.length === 0, "preview");
      const stored = storedObject(runsDir, run, made.handle);
      const sent = await confirmAndSend(page, b, run, controlDir, "http_500", log, evidence);
      const reason = await reasonOnly(page, b, sent.record.send_id);
      const after = await previewWhen(page, b, made.handle, item => item.blocked.length > 0, "egress_stopped shown");
      const status = await readApi(page, `/runs/${run}/jev/status`);
      const since = Date.now();
      await lt(page, b, "jev-loop-end").click();
      control(evidence, "jev-loop-end", { loopId: entry.json.loop_id });
      const ended = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev_loops/${entry.json.loop_id}/end`,
        "end second loop", 60000);
      return { entry, record, made, shown, stored, sent, reason, after, status, ended,
        final: await readLoop(page, run, entry.json.loop_id) };
    }, async value => {
      assert.equal(value.entry.status, 200, JSON.stringify(value.entry.json).slice(0, 600));
      const reused = value.record.candidates.find(item => item.ref === reusedRef);
      assert.deepEqual([reused.state, reused.evaluation, reused.iteration], ["scored", "reused", null]);
      assert.deepEqual([value.record.counts.reused_count, value.record.counts.units_charged], [1, 0]);
      const identity = previewMatches({ shown: value.shown, built: value.made, stored: value.stored, record: value.record,
        iteration: 1, ordinal: 0, runId: run });
      assert.deepEqual(identity.computed.map(item => [item.state, item.score_kcal_mol]), [["scored", reused.score_kcal_mol]]);
      reasonOnlyMatches(value.reason, value.sent.record, "provider_http_error");
      const bytes = serverBytes(runsDir, run, value.sent.record.send_id, value.shown.body, value.made.preview.body_sha256,
        value.sent.calls);
      assert.equal(value.status.egress_stop_reason, "usage_unknown");
      assert.deepEqual(value.after.blocked.map(item => item.code), ["egress_stopped"]);
      assert.deepEqual(value.after.loopBlocks.map(item => item.code), ["ordinal_mismatch"]);
      assert.equal(value.ended.status, 200);
      assert.equal(value.final.end_reason, "ended_by_user");
      assert.deepEqual(value.final.limitations, expectedLimitations("mutation", "exploit", { ended: true, uncomputed: true }));
      sends.push(value.sent.record);
      return { identity, bytes, stop: value.status.egress_stop_reason };
    });
  });

  await rec_.part("P-after", ["P-pair-loop", "P-knowledge-rows", "P-other-tabs"], async () => {
    await rec_.step("P14-pair-loop", ["P-pair-loop"], "단백질 공학 M21 area: re-read the model list, open the iteration-1 " +
      "model: its same-condition docking pair table marks the loop's mutant docking 루프 도킹(야생형 없음) · 바퀴 1 (no " +
      "wild-type score); the iteration-2 model has no loop row", async () => {
      const record = await readLoop(page, run, loop.loopId);
      const model1 = record.iterations[0].steps.find(item => item.step === "model").result_handle;
      const model2 = record.iterations[1].steps.find(item => item.step === "model").result_handle;
      const dock1 = record.iterations[0].steps.find(item => item.step === "dock").result_handle;
      await selectTab(page, TAB.protein);
      const panel = page.locator('#mw-app-panel-protein [data-testid="mutation-model-panel"]');
      await panel.locator('[data-testid="mutation-model-list-refresh"]').click();
      const open = async handle => {
        const radio = panel.locator(`label${attr("data-mutation-model", handle)} input`);
        await radio.waitFor({ timeout: 30000 });
        await radio.check();
        control(evidence, "mutation-model-open", { handle });
        await panel.locator(`[data-testid="mutation-model-detail"]${attr("data-model-handle", handle)}`).waitFor({ timeout: 30000 });
        await waitFor(page, async () => ["ready", "empty"].includes(await panel.locator('[data-testid="mutation-model-pairs-area"]')
          .getAttribute("data-pair-state")) ? true : null, "pairs read", 30000);
        return panel.locator('[data-testid="mutation-model-pairs"] tbody tr').evaluateAll(items => items.map(item => ({
          loop: item.getAttribute("data-pair-loop"), mark: item.querySelector('[data-testid="mutation-model-pair-loop"]')
            ?.textContent.trim() ?? null,
          cells: [...item.querySelectorAll("td[data-side]")].map(cell => ({ side: cell.getAttribute("data-side"),
            hasScore: cell.getAttribute("data-has-score"), result: cell.getAttribute("data-result-handle"),
            text: cell.textContent.replace(/\s+/g, " ").trim() })) })));
      };
      return { first: await open(model1), second: await open(model2), dock1,
        pairs: await readApi(page, `/runs/${run}/mutation_models/${enc(model1)}/docking_pairs`) };
    }, async value => {
      const rows = value.first.filter(row => row.loop === "true");
      assert.equal(rows.length, 1, JSON.stringify(value.first));
      assert.equal(rows[0].mark, `${PAIR_LOOP_TEXT} · 바퀴 1`);
      const pair = value.pairs.pairs.find(item => item.loop);
      const mutant = rows[0].cells.find(cell => cell.side === "mutant");
      const wild = rows[0].cells.find(cell => cell.side === "wild_type_reference");
      assert.equal(mutant.hasScore, "false", "a score shown without both sides (M21 rule)");
      assert.equal(mutant.result, null);
      assert.ok(mutant.text.startsWith(`없음(${pair.sides.mutant.reason})`), mutant.text);
      assert.ok(mutant.text.includes("(done)"), mutant.text);
      assert.equal(wild.hasScore, "false");
      assert.ok(wild.text.startsWith(`없음(${pair.sides.wild_type_reference.reason})`), wild.text);
      assert.deepEqual(pair.loop, { loop_id: loop.loopId, iteration: 1 });
      assert.deepEqual([pair.both_published, pair.sides.mutant.job_status, pair.sides.mutant.reason_code,
        pair.sides.wild_type_reference.reason_code], [false, "done", "other_side_missing", "not_submitted"]);
      const job = (await readLoop(page, run, loop.loopId)).iterations[0].steps.find(item => item.step === "dock").job_id;
      assert.equal(pair.sides.mutant.job_id, job, "the loop row is not the loop's docking job");
      assert.equal(value.second.filter(row => row.loop === "true").length, 0);
      return { first: value.first, second: value.second.length, loopKey: pair.loop };
    });
    await rec_.step("P15-knowledge-rows", ["P-knowledge-rows"], "지식·보고서: run P's two loop sends are read-only JEV 루프 " +
      "rows (no open, no 보고서 만들기)", async () => knowledgeRows(page, run), async value => {
      const rows = knowledgeRowsMatch(value, TAB.protein, sends);
      const found = m24ForbiddenWords(value.text);
      evidence.wording.push({ label: "knowledge JEV area (run P)", kind: "screen-m24", found });
      assert.deepEqual(found, []);
      return rows;
    });
    await rec_.step("P16-other-tabs", ["P-other-tabs"], "After every loop action of run P: the other areas unchanged (the " +
      "M21 area lists the loop's models and the M18 docking area its mutant dockings: kept as evidence), no POST on entry, 구조 분석 hidden and inert, the viewer the " +
      "same session and source", async () => {
      const ligand = await tabAreas(page, "ligand", log);
      const protein = await tabAreas(page, "protein", log);
      await selectTab(page, TAB.structure);
      return { ligand: compareAreas(before.ligand, ligand, ["docking-panel"]), protein: compareAreas(before.protein, protein,
        ["mutation-model-panel"]), posts: [...ligand.posts, ...protein.posts], structure: [ligand.structure, protein.structure],
        viewer: await viewerSnapshot(page) };
    }, async value => {
      for (const side of [value.ligand, value.protein]) {
        assert.deepEqual(side.order.after, side.order.before);
        for (const [id, item] of Object.entries(side.areas)) if (!item.listing) assert.equal(item.same, true, `${id} changed: ${JSON.stringify(item)}`);
      }
      assert.deepEqual(value.posts, []);
      for (const item of value.structure) assert.deepEqual(item, { shown: "false", inert: true });
      assert.equal(value.viewer.sessionId, viewerBefore.sessionId);
      assert.equal(value.viewer.sourceHandle, viewerBefore.sourceHandle);
      return { ligand: value.ligand, protein: value.protein };
    });
  });
  return { run, sends };
}

// ------------------------------------------------------------------ mode fixture
async function modeFixture(session, input, setup, rec_, evidence, log) {
  const { page } = session;
  const controlDir = input.control;
  const server = JSON.parse(fs.readFileSync(path.join(controlDir, "server.json"), "utf8"));
  assert.equal(server.fixture, true, "the backend is not the fixture server");
  assert.equal(server.schema, "m25_jev_loop_fixture_server@1");
  assert.equal(server.runsDir, input["runs-dir"]);
  evidence.fixtureLabels.push(PROCESS_NOTE);
  evidence.runs = { L: setup.runs.L.run, P: setup.runs.P.run };
  const callsBefore = fixtureCalls(controlDir).length;
  await waitForBoot(page);
  const ligand = await ligandBranch(session, input, setup, rec_, evidence, log);
  const protein = await proteinBranch(session, input, setup, rec_, evidence, log);
  evidence.sends = [...ligand.sends, ...protein.sends].map(record => ({ sendId: record.send_id, status: record.status,
    reasonCode: record.reason_code, late: record.late, loop: record.loop }));
  // wording of the scripted replies; the fixture proof (calls = dispatch events, sentinel only, no product key read)
  const calls = fixtureCalls(controlDir).slice(callsBefore);
  for (const call of calls) evidence.wording.push({ label: `fixture reply ${call.n}`, kind: "reply",
    found: forbiddenWords(strings(call.response ?? {}).join("\n")) });
  const counts = dispatchCounts(input["runs-dir"]);
  const reads = credentialReads(controlDir);
  const dispatched = Object.values(counts).reduce((sum, item) => sum + item, 0);
  evidence.fixture = { calls: calls.length, scripts: calls.map(call => call.script), statuses: calls.map(call => call.status),
    sentinelAuthorization: calls.every(call => call.authorizationIsSentinel === true),
    bodySha256: calls.map(call => call.bodySha256), credentialReads: reads, dispatchCounts: counts, dispatched };
  rec_.mark(["X-fixture-proof"], calls.length === dispatched && calls.length === evidence.sends.length &&
    BYTE_LOG.length === calls.length &&
    evidence.fixture.sentinelAuthorization && reads !== null && reads.productResolverReads === 0 &&
    reads.sentinelReads === dispatched);
}

// ------------------------------------------------------------------ modes calibrate and live (the real-call plan)
const PLAN_ENTRY_KEYS = ["branch", "cap", "compareWith", "compute", "goal", "id", "loopSeed", "pool", "report", "rounds",
  "run", "sends"];
/** The plan the runner wrote: every entry a loop of one branch in one setup run, one send per round. */
function checkPlan(plan, setup) {
  assert.ok(Number.isInteger(plan.maxDispatch) && plan.maxDispatch >= 1 && plan.maxDispatch <= MAX_LIVE_CALLS,
    "plan.maxDispatch");
  assert.ok(plan.maxPerRun && typeof plan.maxPerRun === "object" && Object.values(plan.maxPerRun).every(value =>
    Number.isInteger(value) && value >= 1 && value <= SEND_CAP), "plan.maxPerRun");
  assert.ok(Array.isArray(plan.entries), "plan.entries");
  for (const entry of plan.entries) {
    assert.deepEqual(Object.keys(entry).filter(key => !PLAN_ENTRY_KEYS.includes(key)), [], `plan entry ${entry.id} keys`);
    assert.ok(setup.runs[entry.run], `plan entry ${entry.id}: run ${entry.run}`);
    assert.ok(["ligand", "protein"].includes(entry.branch) && ["explore", "exploit"].includes(entry.goal));
    assert.ok(Number.isInteger(entry.loopSeed) && Number.isInteger(entry.cap) && entry.cap >= 1 && entry.cap <= 8);
    assert.ok(Array.isArray(entry.pool) && entry.pool.length >= 2 && entry.pool.length <= MAX_POOL);
    assert.ok(Number.isInteger(entry.rounds) && entry.rounds >= 1 && entry.rounds <= entry.cap && entry.sends === entry.rounds);
    assert.ok(entry.pool.length - entry.rounds + 1 >= 2, `plan entry ${entry.id}: two pending candidates in every round`);
  }
}
/** The pool refs of a plan entry: ligand candidate ids (by set order) or mutation candidate indices. */
function entryPool(setup, entry) {
  const run = setup.runs[entry.run];
  return entry.branch === "ligand" ? { source: run.ligandSet, refs: entry.pool.map(index => run.ligandSet.ids[index]) }
    : { source: run.ubqSet, refs: [...entry.pool] };
}
/** After a person's compute press: the run's first expensive-call approval when the server asks for it (guide →
 * 비싼 계산 승인 → 작업 시작), then, for a protein round, the docking step; returns when the round has ended. */
async function finishRound(page, b, run, loopId, first, round, log, evidence) {
  const steps = [{ request: first.request, status: first.status }];
  let approval = null;
  if (first.json?.current?.job?.start_blocked === "approval_required") {
    await lt(page, b, "jev-loop-approval-guide").waitFor({ timeout: 30000 });
    const since = Date.now();
    await lt(page, b, "jev-loop-approve-first").click();
    control(evidence, "jev-loop-approve-first", { run });
    const approved = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jobs/approve`, "approve", 30000);
    await waitFor(page, async () => await lt(page, b, "jev-loop-job-start").isEnabled() ? true : null, "job start", 30000);
    const since2 = Date.now();
    await lt(page, b, "jev-loop-job-start").click();
    control(evidence, "jev-loop-job-start", { run });
    const resumed = await waitApi(page, log, since2, item => item.path === `/api/runs/${run}/jev_loops/${loopId}/compute`,
      "job start answer", 900000);
    approval = { approve: approved.status, resumed: resumed.status };
    steps.push({ request: resumed.request, status: resumed.status });
  }
  if (b === "protein") {
    await recordWhen(page, b, item => item.action === "dock" || item.action === "end" || Number(item.iteration) > round,
      "modelled", 900000);
    if ((await recordAttrs(page, b)).action === "dock") {
      const dock = await pressCompute(page, b, run, loopId, "jev-loop-dock", log, evidence, { timeout: 900000 });
      steps.push({ request: dock.request, status: dock.status });
    }
  }
  await recordWhen(page, b, item => item.action === "end" || Number(item.iteration) > round, "round ended", 900000);
  return { steps, approval };
}
async function modeLive(session, input, setup, rec_, evidence, log) {
  const { page } = session;
  const runsDir = input["runs-dir"];
  const controlDir = input.control;
  const rehearsal = !!controlDir;
  const plan = JSON.parse(fs.readFileSync(input.plan, "utf8"));
  checkPlan(plan, setup);
  if (rehearsal) {
    const server = JSON.parse(fs.readFileSync(path.join(controlDir, "server.json"), "utf8"));
    assert.equal(server.fixture, true, "a rehearsal needs the fixture server");
    assert.equal(server.runsDir, runsDir);
    evidence.fixtureLabels.push(PROCESS_NOTE);
  }
  const caseId = input.mode === "calibrate" ? "JL-calibrate" : "JL-live";
  evidence.rehearsal = rehearsal;
  evidence.plan = { entries: plan.entries.map(entry => entry.id), maxDispatch: plan.maxDispatch, maxPerRun: plan.maxPerRun,
    preChecks: plan.preChecks ?? null };
  evidence.runs = { L: setup.runs.L.run, P: setup.runs.P.run };
  evidence.loops = [];
  const callsBefore = rehearsal ? fixtureCalls(controlDir).length : 0;
  await waitForBoot(page);
  const signatures = {};
  const viewers = {};
  let current = null;
  let stop = null;
  for (const entry of plan.entries) {
    if (stop) { evidence.loops.push({ entry: entry.id, skipped: stop }); continue; }
    const outcome = await rec_.part(`entry-${entry.id}`, [caseId], () => liveEntry(entry));
    if (outcome === null || outcome.stop) stop = outcome?.stop ?? `stopped after ${entry.id} (see its rows)`;
  }
  await rec_.part("live-other-tabs", [caseId], async () => {
    for (const [run, before] of Object.entries(signatures)) {
      await rec_.step(`X-other-tabs-${run.slice(4, 12)}`, [caseId], `Run ${run}: the other areas of 리간드 설계·탐색 and ` +
        "단백질 공학 unchanged (the M18 docking area and the M21 area list the loop's standalone results: kept as " +
        "evidence), no POST on entry, 구조 분석 hidden and inert, the viewer shows the same source", async () => {
        await chooseRun(page, run);
        const ligand = await tabAreas(page, "ligand", log);
        const protein = await tabAreas(page, "protein", log);
        await selectTab(page, TAB.structure);
        return { ligand: compareAreas(before.ligand, ligand, ["docking-panel"]),
          protein: compareAreas(before.protein, protein, ["mutation-model-panel"]), posts: [...ligand.posts, ...protein.posts],
          structure: [ligand.structure, protein.structure], viewer: await viewerSnapshot(page) };
      }, async value => {
        for (const side of [value.ligand, value.protein]) {
          assert.deepEqual(side.order.after, side.order.before);
          for (const [id, item] of Object.entries(side.areas)) if (!item.listing) assert.equal(item.same, true, `${id} changed`);
        }
        assert.deepEqual(value.posts, []);
        for (const item of value.structure) assert.deepEqual(item, { shown: "false", inert: true });
        assert.equal(value.viewer.sourceHandle, viewers[run].sourceHandle);
        return { ligand: value.ligand, protein: value.protein };
      });
    }
  });
  evidence.dispatchCounts = dispatchCounts(runsDir);
  if (rehearsal) {
    const calls = fixtureCalls(controlDir).slice(callsBefore);
    evidence.fixture = { calls: calls.length, scripts: calls.map(call => call.script), statuses: calls.map(call => call.status),
      sentinelAuthorization: calls.every(call => call.authorizationIsSentinel === true), credentialReads: credentialReads(controlDir) };
  }

  async function liveEntry(entry) {
    const b = entry.branch;
    const S = setup.runs[entry.run];
    const run = S.run;
    const kind = b === "ligand" ? "ligand" : "mutation";
    const { source, refs } = entryPool(setup, entry);
    if (current !== run) {
      const viewer = await chooseRun(page, run);
      if (!signatures[run]) {
        viewers[run] = viewer;
        signatures[run] = { protein: await tabAreas(page, "protein", log), ligand: await tabAreas(page, "ligand", log) };
      }
      current = run;
    }
    const loopRow = { entry: entry.id, run, branch: b, goal: entry.goal, loopSeed: entry.loopSeed, rounds: [] };
    evidence.loops.push(loopRow);
    const created = await rec_.step(`${entry.id}-create`, [caseId], `${entry.id}: on ${TAB[b]}, choose the set, check ` +
      `the pool (${refs.length}), ${entry.goal === "explore" ? "탐색형" : "활용형"}, loop seed ${entry.loopSeed}, cap ` +
      `${entry.cap}, the computation inputs; 루프 만들기: the loop opens at iteration 1 awaiting its selection`, async () => {
      await openLoopArea(page, b, log);
      await chooseSource(page, b, source.handle, source.candidates, evidence);
      await uncheckAll(page, b, evidence);
      await checkKeys(page, b, refs.map(String), evidence);
      await settings(page, b, { goal: entry.goal, seed: String(entry.loopSeed), cap: String(entry.cap) }, evidence);
      if (b === "ligand") await ligandSetupInputs(page, S, evidence);
      else await proteinSetupInputs(page, S, evidence);
      const made = await createLoop(page, b, run, log, evidence);
      await recordWhen(page, b, value => value.loopId === made.json?.loop_id, "loop opened", 30000);
      return { made, record: await readLoop(page, run, made.json.loop_id) };
    }, async value => {
      assert.equal(value.made.status, 200, JSON.stringify(value.made.json).slice(0, 600));
      assert.deepEqual(value.made.request.pool.candidates, refs);
      assert.deepEqual([value.made.request.goal, value.made.request.loop_seed, value.made.request.iteration_cap],
        [entry.goal, entry.loopSeed, entry.cap]);
      assert.deepEqual(value.record.candidates.map(item => item.ref), refs);
      assert.deepEqual(value.record.limitations, expectedLimitations(kind, entry.goal));
      return { loopId: value.made.json.loop_id };
    });
    const loopId = created.loopId;
    loopRow.loopId = loopId;
    if (input.mode === "calibrate" && plan.preChecks && entry === plan.entries[0]) {
      evidence.preChecks = await rec_.step(`${entry.id}-pre-checks`, [caseId], "Before the first real send, with no send: " +
        "consent off → 보낼 내용 만들기 shows consent_off and the send stays closed with the confirmation checked; consent on " +
        "→ no refusal; confirmation unchecked → closed with its reason; checked → open; no send request, no dispatch event",
      async () => {
        const since = Date.now();
        const before = dispatchCounts(runsDir)[run] ?? 0;
        await setConsent(page, b, run, false, log, evidence);
        const made = await build(page, b, run, log, evidence);
        const off = await previewWhen(page, b, made.handle, item => item.blocked.length > 0, "consent_off shown");
        if (!(await lt(page, b, "jev-loop-confirm").isChecked())) await lt(page, b, "jev-loop-confirm").check();
        const offSend = await sendState(page, b);
        await setConsent(page, b, run, true, log, evidence);
        const on = await previewWhen(page, b, made.handle, item => item.blocked.length === 0, "preview unblocked");
        await lt(page, b, "jev-loop-confirm").uncheck();
        const unchecked = await sendState(page, b);
        await lt(page, b, "jev-loop-confirm").check();
        return { off, offSend, on, unchecked, checked: await sendState(page, b),
          sendPosts: posts(log, since).filter(item => item.endsWith("/jev/sends")),
          dispatched: { before, after: dispatchCounts(runsDir)[run] ?? 0 } };
      }, async value => {
        assert.deepEqual(value.off.blocked.map(item => item.code), ["consent_off"]);
        assert.equal(value.offSend.enabled, false);
        assert.ok(value.offSend.blockers.some(text => text.includes("(consent_off)")));
        assert.deepEqual([value.on.blocked, value.on.loopBlocks], [[], []]);
        assert.equal(value.unchecked.enabled, false);
        assert.ok(value.unchecked.blockers.some(text => text.includes("확인 체크")));
        assert.equal(value.checked.enabled, true);
        assert.deepEqual(value.sendPosts, []);
        assert.equal(value.dispatched.after, value.dispatched.before);
        return { blockedOff: ["consent_off"], unchecked: value.unchecked.blockers, dispatched: value.dispatched };
      });
    }
    for (let round = 1; round <= entry.rounds; round++) {
      const roundRow = { round };
      loopRow.rounds.push(roundRow);
      const sent = await rec_.step(`${entry.id}-r${round}-send`, [caseId], `${entry.id} round ${round}: consent on, 보낼 ` +
        "내용 만들기, preview identity and the independent order oracle, the dispatch guard, the confirmation and one send" +
        `${rehearsal ? " (fixture good)" : ""}; the result as stored (the JEV card with its list position and values ` +
        "folded at first, or the reason only)", async () => {
        await setConsent(page, b, run, true, log, evidence);
        const record = await readLoop(page, run, loopId);
        assert.equal(record.current.action, "select", `round ${round} is not awaiting its selection`);
        const made = await build(page, b, run, log, evidence);
        const shown = await previewWhen(page, b, made.handle, () => true, "preview");
        const stored = storedObject(runsDir, run, made.handle);
        const identity = previewMatches({ shown, built: made, stored, record, iteration: record.current.iteration,
          ordinal: made.summary.send_ordinal, runId: run });
        if (shown.blocked.length || shown.loopBlocks.length)
          return { blocked: [...shown.blocked, ...shown.loopBlocks].map(item => item.code), identity };
        const counts = dispatchCounts(runsDir);
        const total = Object.values(counts).reduce((sum, item) => sum + item, 0);
        if (total >= plan.maxDispatch || (counts[run] ?? 0) >= (plan.maxPerRun[run] ?? 0))
          return { guard: { total, inRun: counts[run] ?? 0 }, identity };
        const row = { entry: entry.id, round, run, branch: b, goal: entry.goal, loopId, iteration: record.current.iteration,
          sendOrdinal: made.summary.send_ordinal, aliases: identity.order.length, order: identity.order,
          criteria: identity.criteria, bodyBytes: identity.bodyBytes, bodySha256: identity.bodySha256,
          reservation: identity.reservation, dispatchedBefore: { total, inRun: counts[run] ?? 0 } };
        const result = await confirmAndSend(page, b, run, rehearsal ? controlDir : null, rehearsal ? "good" : null, log,
          evidence, null, item => {
            Object.assign(row, { sendId: item.send_id, status: item.status, reasonCode: item.reason_code,
              servedModel: item.served_model, usage: item.usage, late: item.late });
            evidence.sends.push(row);
          });
        const status = await readApi(page, `/runs/${run}/jev/status`);
        Object.assign(row, { egressStop: status.egress_stop_reason, statusUsed: status.used, budgetAfter: status.budget });
        const value = { row, record, made, shown, stored, identity, result };
        if (result.record.status === "completed") {
          await lp(page, b).locator(`[data-testid="jev-loop-selection"]${attr("data-send-id", result.record.send_id)}`)
            .waitFor({ timeout: 30000 });
          value.card = await readCard(page, b, result.record.send_id);
        } else value.reason = await reasonOnly(page, b, result.record.send_id);
        value.wording = await wordingCheck(page, b, `${entry.id} round ${round}`, evidence);
        return value;
      }, async value => {
        if (value.blocked) throw new Error(`the server refuses before the send: ${value.blocked.join(", ")}`);
        if (value.guard) throw new Error(`dispatch guard: ${JSON.stringify(value.guard)} (no send)`);
        const record = value.result.record;
        const row = value.row;
        if (record.status !== "rejected")       // a refusal before the dispatch has no prepared audit and sends nothing
          row.bytes = serverBytes(runsDir, run, record.send_id, value.shown.body, value.identity.bodySha256, value.result.calls);
        if (value.card) {
          const choice = storedObject(runsDir, run, record.choice_handle);
          const card = cardMatches(value.card, record, choice, value.stored, { late: false, isSelection: true,
            iteration: row.iteration });
          Object.assign(row, { proposal: record.choice_handle, chosenAlias: choice.answer.choice_alias,
            chosenRef: "candidate_id" in choice.answer.local_ref ? choice.answer.local_ref.candidate_id
              : choice.answer.local_ref.candidate_index,
            listPosition: choice.answer.list_position, listSize: choice.answer.list_size,
            responseShape: { answersParsed: true, confidence: choice.answer.confidence !== null,
              probabilities: choice.answer.probabilities !== null,
              probabilityCount: choice.answer.probabilities === null ? 0 : Object.keys(choice.answer.probabilities).length } });
          row.card = card;
        } else {
          assert.ok(["failed", "rejected"].includes(record.status), record.status);
          assert.deepEqual([value.reason.status, value.reason.code], [record.status, record.reason_code]);
          assert.ok(value.reason.text.includes(`(${record.reason_code})`), value.reason.text);
          assert.equal(value.reason.cards, 0, "a proposal card for a send that did not complete");
          row.responseShape = { answersParsed: false };
        }
        assert.deepEqual(value.wording, []);
        roundRow.send = { sendId: row.sendId, status: row.status, reasonCode: row.reasonCode };
        return { status: record.status, reasonCode: record.reason_code, proposal: record.choice_handle,
          egressStop: row.egressStop, listPosition: row.listPosition ?? null, listSize: row.listSize ?? null };
      });
      // a send that did not complete or a stopped egress ends the plan here: no retry, no other call
      if (sent.status !== "completed") return { stop: `${entry.id} round ${round}: ${sent.status}/${sent.reasonCode}` };
      if (sent.egressStop) return { stop: `${entry.id} round ${round}: egress stopped (${sent.egressStop})` };
      if (!entry.compute) continue;
      await rec_.step(`${entry.id}-r${round}-compute`, [caseId], `${entry.id} round ${round}: the compute confirmation and ` +
        "이 선택으로 계산 시작 (JEV 판정 사용); the run's first expensive-call approval when asked; " +
        `${b === "protein" ? "the real PDBFixer/OpenMM model, then 도킹 시작 and the real qvina docking into it" :
          "the real qvina docking"}; the round ends with the stored first-mode score`, async () => {
        const first = await pressCompute(page, b, run, loopId, "jev-loop-compute-proposal", log, evidence, { timeout: 900000 });
        const steps = await finishRound(page, b, run, loopId, first, round, log, evidence);
        return { first, steps, record: await readLoop(page, run, loopId), table: await candidateTable(page, b) };
      }, async value => {
        assert.equal(value.first.status, 200, JSON.stringify(value.first.json).slice(0, 600));
        assert.deepEqual(value.first.request, { iteration: round, proposal: sent.proposal });
        const it = value.record.iterations.find(item => item.index === round);
        assert.equal(it.decided_by, "jev");
        assert.ok(["scored", "null_result", "failed"].includes(it.state), it.state);
        const docked = it.steps.find(item => item.step === (b === "ligand" ? "ligand_dock" : "dock"));
        if (it.state === "scored")
          assert.equal(it.score_kcal_mol, storedObject(runsDir, run, docked.result_handle).modes[0].score_kcal_mol);
        candidateRowsMatch(value.table, value.record);
        Object.assign(roundRow, { state: it.state, score: it.score_kcal_mol, steps: it.steps.map(item => ({ step: item.step,
          state: item.state })), approval: value.steps.approval });
        return roundRow;
      });
    }
    const ended = await rec_.step(`${entry.id}-end`, [caseId], `${entry.id}: 루프 끝내기; the summary jev_loop_result@1 is ` +
      "stored and the record's sentences are the stored ones", async () => {
      const since = Date.now();
      await lt(page, b, "jev-loop-end").click();
      control(evidence, "jev-loop-end", { loopId });
      const answer = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev_loops/${loopId}/end`, "end",
        120000);
      const result = await waitFor(page, async () => (await lt(page, b, "jev-loop-ended").count())
        ? lt(page, b, "jev-loop-ended").getAttribute("data-result-handle") : null, "ended", 30000);
      return { answer, result, record: await readLoop(page, run, loopId) };
    }, async value => {
      assert.equal(value.answer.status, 200, JSON.stringify(value.answer.json).slice(0, 400));
      const stored = storedObject(runsDir, run, value.result);
      assert.equal(stored.end_reason, value.record.end_reason);
      assert.deepEqual(value.record.limitations, expectedLimitations(kind, entry.goal, { ended: true,
        uncomputed: value.record.candidates.some(item => ["pending", "unavailable"].includes(item.state)) }));
      Object.assign(loopRow, { endReason: value.record.end_reason, result: value.result, counts: value.record.counts });
      return { endReason: value.record.end_reason, result: value.result };
    });
    if (entry.report) {
      await rec_.step(`${entry.id}-report`, [caseId], `${entry.id}: 보고서 만들기 (JEV 루프 보고서) and the saved Markdown in ` +
        "the 지식·보고서 library", async () => {
        const made = await makeLoopReport(page, b, run, log, evidence);
        return { made, report: await libraryReport(page, run, made.json.handle, evidence) };
      }, async value => {
        loopRow.report = value.made.json.handle;
        return reportMatches(value.report, storedObject(runsDir, run, ended.result), kind, entry.goal, evidence);
      });
    }
    if (entry.compareWith) {
      evidence.shuffle = await rec_.step(`${entry.id}-shuffle`, [caseId], `${entry.id}: the first send of this loop and ` +
        `of ${entry.compareWith} (same pool and goal, other loop seed) side by side: both sent orders and both chosen list ` +
        "positions, recorded as observed values only", async () => {
        const loops = await readApi(page, `/runs/${run}/jev_loops`);
        const records = await Promise.all(loops.map(row => readLoop(page, run, row.loop_id)));
        const mine = records.find(item => item.loop_id === loopId);
        const theirs = records.filter(item => item.loop_id !== loopId && item.branch === b && item.goal === entry.goal &&
          JSON.stringify(item.pool.candidates.map(row => row.ref)) === JSON.stringify(refs));
        const first = async loop => {
          const send = loop.iterations.find(item => item.index === 1)?.sends.find(item => item.send_ordinal === 0);
          if (!send) return { loopSeed: loop.loop_seed, send: null };
          const detail = await readApi(page, `/runs/${run}/jev/sends/${enc(send.send_id)}`);
          const projection = storedObject(runsDir, run, detail.projection_handle);
          return { loopSeed: loop.loop_seed, sendId: send.send_id, status: detail.status,
            order: projection.selection.map(item => item.ref), aliases: projection.selection.map(item => item.alias),
            listPosition: detail.choice?.answer.list_position ?? null, listSize: detail.choice?.answer.list_size ?? null,
            chosenRef: detail.choice ? ("candidate_id" in detail.choice.answer.local_ref
              ? detail.choice.answer.local_ref.candidate_id : detail.choice.answer.local_ref.candidate_index) : null };
        };
        return { mine: await first(mine), theirs: await Promise.all(theirs.map(first)) };
      }, async value => {
        assert.equal(value.theirs.length, 1, "the loop to set beside this one (same pool and goal) was not found");
        const [a, b_] = [value.theirs[0], value.mine];
        assert.notEqual(a.loopSeed, b_.loopSeed);
        assert.deepEqual([...a.order].map(String).sort(), [...b_.order].map(String).sort());
        return { note: "observed values only (two sent orders and two chosen list positions)", first: a, second: b_ };
      });
    }
    return { loopId };
  }
}

// ------------------------------------------------------------------ main
const RUNNERS = { fixture: modeFixture, calibrate: modeLive, live: modeLive };

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const setup = JSON.parse(fs.readFileSync(input.setup, "utf8"));
  assert.equal(setup.schema, "m25_jev_loop_setup@1");
  const evidence = { schema: "m25_jev_loop_evidence@1", mode: input.mode, rehearsal: input.mode !== "fixture" && !!input.control,
    runs: {}, sends: [], fixtureLabels: [], partFailures: [], controls: {}, wording: [], startedAt: new Date().toISOString() };
  const session = await launchOffscreen({ url: input.url, artifacts: input.artifacts, interactive: false });
  const log = requestLog(session.page);
  const rec_ = recorder(session, input, evidence);
  let error = null;
  let proof = null;
  try {
    proof = await offscreenProof(session.app, session.page);
    await RUNNERS[input.mode](session, input, setup, rec_, evidence, log);
  } catch (caught) {
    error = caught;
  } finally {
    try { proof = { ...await offscreenProof(session.app, session.page), atStart: proof }; } catch { /* keep the start proof */ }
    await session.close();
  }
  const cases = rec_.cases();
  const wordingOk = evidence.wording.length > 0 && evidence.wording.every(item => item.found.length === 0);
  cases["X-wording"] = wordingOk ? "pass" : "fail";
  cases["X-no-egress-browser"] = proof && proof.nonLoopbackRequests === 0 ? "pass" : "fail";
  const passed = !error && evidence.partFailures.length === 0 && offscreenComplete(proof) && proof.nonLoopbackRequests === 0 &&
    Object.keys(cases).length > 0 && Object.values(cases).every(value => value === "pass");
  evidence.finishedAt = new Date().toISOString();
  evidence.error = error ? String(error.stack ?? error) : null;
  evidence.requestCount = log.rows.length;
  evidence.fixtureLabels = [...new Set(evidence.fixtureLabels)];
  fs.writeFileSync(path.join(input.artifacts, "jev-loop-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  fs.writeFileSync(path.join(input.artifacts, "jev-loop-requests.jsonl"), log.rows.map(row => JSON.stringify(row)).join("\n") + "\n");
  fs.writeFileSync(path.join(input.artifacts, "jev-loop-bytes.json"), JSON.stringify({ schema: "m25_jev_loop_bytes@1",
    rule: "per send: the preview <pre> text = the server preview string; its SHA-256 = the audit prepared payload_sha256 " +
      "(prepared body deep-equal) = (fixture server) the SHA-256 of the bytes its transport received; one dispatch event",
    sends: BYTE_LOG }, null, 2) + "\n");
  const harness = Object.fromEntries(["jev-loop-flow.cjs", "jev-flow.cjs", "driver.cjs", "main.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m25_case_ledger_row@1", mode: input.mode, rehearsal: evidence.rehearsal,
    evidenceKind: "real_electron_offscreen", status: passed ? "pass" : "fail", cases, runs: evidence.runs,
    sends: evidence.sends, fixture: evidence.fixture ?? null, bytes: BYTE_LOG.length, plan: evidence.plan ?? null,
    preChecks: evidence.preChecks ?? null, loops: evidence.loops ?? null, shuffle: evidence.shuffle ?? null,
    dispatchCounts: evidence.dispatchCounts ?? null,
    fixtureLabels: evidence.fixtureLabels, controls: evidence.controls,
    wording: evidence.wording.map(item => ({ label: item.label, kind: item.kind, found: item.found.length })),
    buildId: buildId(), harness, offscreen: proof, externalRequestCount: proof ? proof.nonLoopbackRequests : null,
    partFailures: evidence.partFailures, error: evidence.error, evidenceFile: path.basename(rec_.file),
    startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, runs: evidence.runs, cases }) + "\n");
  if (error) process.stderr.write(`jev-loop-flow ${input.mode} failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`jev-loop-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, oracleOrder, expectedLimitations, forbiddenWords, checkPlan, FORBIDDEN, FIXED_LINES, LJ,
  UL, INSTRUCTIONS, MODES, MAX_LIVE_CALLS };
