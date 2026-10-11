"use strict";

// M28 end-to-end acceptance, branch C (.dryforge/spec.md §4.3, C1–C7; §6 live L-C6): protein engineering on public
// 1A30 (catalytic protection with the archived M26 reaction set) and public 1UBQ (M7, M20, M21, same-condition docking
// pairs with the labeled synthetic phenol SDF, M24, M25 protein loop, M23 sequence GA). C1 and C2–C6 use DIFFERENT
// structures (no local public structure both passes M7 and is in M-CSA). Real Electron offscreen page (isOffscreen,
// GPU/WebGL, paint). Every product mutation is a Playwright locator mouse/keyboard/file-chooser/select input (every
// approval, every limit raise and every JEV send a person's click on the screen); nothing calls application internals
// and this script never posts to the API itself. Observation is read-only: data attributes and text of the page,
// renderer request/response events, Electron paint frames, downloaded bytes, GET reads of the loopback API, the stored
// objects and events in <runs-dir>/<run>/events.jsonl (read-only file reads) and, with the fixture server, its control
// folder (calls.jsonl, credentials.json).
//
// The plan (--plan, written by scripts/m28_branch_c.py) holds the independent expectations computed from the input
// files: input SHA-256, the 1A30 M-CSA coverage, row counts and per-position protecting rows (archived set's
// entries.jsonl), the checked rule of the two linked results, the 1UBQ protein heavy atoms and waters of the keep_all
// M7 preflight, the M20 candidates and combination space, the loop pools, the docking values, the GA settings with their
// spec 7 numbers and the unit plan (remaining units before every computation, the raises a person clicks). Scores and
// potentials are never computed here: each one shown is compared with the stored object it names.
//
// Step functions come from the older harnesses (each block says "copied from <file>" or "adapted from <file>"); those
// files are not changed. Exported oracle helpers and constants are required: driver (launchOffscreen, capture,
// downloadByClick), normal-flow (waitForViewer), mutation-flow (reasonCountText, UK2, LIMIT3, FORBIDDEN_CATALYTIC,
// forbiddenIn, halfUp2), mutation-model-flow (halfUp, expectedLimitations), sequence-ga-flow (needFor, shortfallFor,
// spaceSize, sortOracle, statementIds), jev-flow (J, expectedLimitations, forbiddenWords, halfUp) and jev-loop-flow
// (oracleOrder, expectedLimitations, forbiddenWords, INSTRUCTIONS, LJ, fixtureServer).
//
// Modes:
//   fixture  backend = backend/tests/offscreen_jev_loop_fixture/server.py (the product app; only SCIENCE_GATE over a
//            scripted httpx.MockTransport, scripts good / good_second only). One new run, parts in the budget order of
//            the coordinator (decision 1): C1 → C2 → C3 → C5 → C6 (explore round, then exploit round) → C4 (setting 1,
//            setting 2) → C7. Two limit raises, each a click on the screen.
//   live     a new run: L-pre-C2 (the C2 part code) → L-C6 (ONE explore round of the protein loop). With --control
//            (rehearsal) the backend is the fixture server; without it the real science gate. The send is clicked only
//            when the plan allows it and the dispatch events of every run in --runs-dir are below plan.live.
//            dispatchLimit (one send); a send that does not complete ends the plan (no retry, no other call).
// A part whose earlier part did not pass is not run and says which one.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const { waitForViewer } = require("./normal-flow.cjs");
const M20 = require("./mutation-flow.cjs");
const M21 = require("./mutation-model-flow.cjs");
const M23 = require("./sequence-ga-flow.cjs");
const M24 = require("./jev-flow.cjs");
const M25 = require("./jev-loop-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const MODES = ["fixture", "live"];
const TAB = { structure: "구조 분석", protein: "단백질 공학", ligand: "리간드 설계·탐색", knowledge: "지식·보고서" };
const PANEL_ID = { [TAB.structure]: "structure", [TAB.protein]: "protein", [TAB.ligand]: "ligand",
  [TAB.knowledge]: "knowledge" };
const M20_TOOL = "generate_mutation_candidates";
const REACTION_TOOL = "link_reaction_knowledge";
const MODEL_PROTOCOL = "openmm_mutation_model_v1";
const DOCKING_PROTOCOL = "qvina_dock_v1";
const GA_PROTOCOL = "sequence_ga_dock_v1";
const ACK_KEYS = ["keep_input_protonation", "tool_assigned_types_charges", "rigid_no_optimization"];
const SIDES = ["wild_type_reference", "mutant"];
const SIDE_LABEL = { wild_type_reference: "야생형 기준", mutant: "변이형" };
const ENERGY_LABEL = "OpenMM Amber14-all + GBn2 전위(kJ/mol)";
const SCORE_LABEL = "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)";
const SCORE_COLUMN = "qvina 점수(kcal/mol)";
const SCORE_HEADER = "qvina 점수(kcal/mol) · 모드 1(엔진 출력 순서)";
const NULL_TEXT = "—";
const LOOP_REPORT_KIND = "JEV 루프 보고서";
// M21 spec §4 verbatim (copied from mutation-model-flow.cjs; L5 and L6 only under their stored conditions).
const L21 = {
  L1: "변이 구조는 PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 모델이며 회전이성질체 탐색과 수렴을 주장하지 않는다.",
  L2: "OpenMM 전위는 각 구조의 Amber14-all + GBn2 암시 용매 값(kJ/mol)이며 서열이 다른 두 구조의 값은 서로 비교할 수 없고 ΔΔG·안정성·친화도가 아니다.",
  L3: "모델은 단백질만 포함하며 리간드·금속 이온·물·보조인자는 제외했다.",
  L4: "SASA는 리간드가 없는 단백질 모델의 변이 위치 잔기 값이다.",
  L7: "접촉은 중원자 사이 거리(Å)이며 수소결합이나 상호작용의 종류를 뜻하지 않는다.",
  L5: "변이한 잔기 밖에서 히스티딘·시스테인 양성자 상태가 두 구조에서 다르게 지정되었으므로 두 구조의 차이는 변이 하나만이 아니다.",
  L6: "변이형에는 야생형 기준에 없는 이황화 결합이 거리 기준으로 만들어졌다.",
};
// No difference, change, rank or comparison word or arrow in the M21 area (copied from mutation-model-flow.cjs).
const FORBIDDEN_MODEL = /순위|추천|개선|증가|감소|안정성|ΔΔG|Δ|차이|변화량|최적(?!화)|최고|유망|좋은|나쁜|친화|\brank|\bbest|improv|recommend|optimal|stabili|delta|differen|better|worse|↑|↓|▲|▼|⬆|⬇/gi;
const ARROWS = /[↑↓▲▼⬆⬇→←]/;
// No stored field may carry a value computed from both structures (key prefixes; protonation_difference_count is a
// count of residues whose variant names differ, not a value difference, and is not matched by these prefixes).
const DIFFERENCE_KEY = /"(?:energy_delta|delta|difference|diff_|change_|potential_change|rank|best)/i;
// M20 (copied from mutation-flow.cjs, mode catalytic).
const UNCOVERED_LABEL = { not_in_annotation: "고른 효소 반응 지식 결과에 이 체인이 없음", chain_not_listed: "이 체인은 M-CSA 행에 없음",
  pdb_not_in_snapshot: "이 PDB ID는 스냅샷에 없음", not_checked: "결과가 이 체인의 M-CSA를 검사하지 않음(PDB ID 없음)" };
const EXCLUSION_V1 = ["non_standard_residue", "user_protected", "klifs_key_site", "metal_contact", "disulfide_cys",
  "no_allowed_alternative"];
const EXCLUSION_V2 = ["non_standard_residue", "user_protected", "klifs_key_site", "metal_contact", "disulfide_cys",
  "catalytic_residue", "no_allowed_alternative"];
const REACTION_SET_HEADING = "### 촉매 잔기 주석의 반응 참조 세트";
// M23 spec 4 verbatim (copied from sequence-ga-flow.cjs; independent of the product constants).
const S23 = {
  S1: "서열 GA는 변이 조합 공간에서 어떤 조합을 모델링·도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 순위나 " +
    "추천이 아니다. 교차·편집의 부모 선택은 작업 모듈 기록이며 서버가 다시 계산하지 않았고 변이 목록의 부모–자식 관계만 검증했다.",
  S2: "이 실행은 시간·평가 상한·취소·기준 행 실패·연속 실패 등으로 일부만 계산되었다. 계산하지 않은 개체는 점수가 없으며 " +
    "0이 아니고, 한도 도달로 멈춘 실행은 같은 설정으로 다시 해도 같은 경로를 보장하지 않는다.",
  S3: "재사용한 개체는 같은 후보 집합·구조·리간드·상자·seed·값으로 이전에 저장된 모델링·도킹 결과를 가져온 것이며, 저장된 " +
    "결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있다.",
  S4: "점수는 각 개체의 변이 구조(PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 단백질만의 " +
    "모델)에 사용자가 준 리간드 좌표를 그대로 두고 자유 도킹한 qvina 점수이며, 변이의 효과나 결합 친화도를 뜻하지 않는다.",
  S5: "OpenMM 전위는 각 구조의 Amber14-all + GBn2 값(kJ/mol)이며 서열이 다른 구조의 값은 서로 비교할 수 없고 " +
    "ΔΔG·안정성이 아니다.",
  S6: "여러 곳 변이는 구조 순서대로 한 곳씩 PDBFixer로 연속 적용한 모델이며(앞 단계에서 놓은 원자 좌표는 다음 단계 전에 " +
    "소수 넷째 자리로 반올림했다) 적용 순서와 곁사슬 크기에 따라 모델이 달라질 수 있다. 구조의 충돌·전위는 점수나 선택에 " +
    "쓰지 않았고(전위가 늘거나 유한하지 않은 모델만 실패로 처리), 개체마다 수용체가 다르므로 개체 점수를 나란히 두는 것은 " +
    "같은 수용체 안의 비교가 아니며(개체 도킹 결과의 M18 둘째 한계 문장이 말하는 조건과 다르다) 순위나 '더 잘 결합'을 " +
    "뜻하지 않는다.",
};
const MODEL_LIMITATIONS = [
  "변이 구조는 PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 모델이며 회전이성질체 탐색과 수렴을 주장하지 않는다.",
  "모델은 단백질만 포함하며 리간드·금속 이온·물·보조인자는 제외했다.",
  "변이한 잔기 밖에서 히스티딘·시스테인 양성자 상태가 야생형 기준 구조와 다르게 지정되었으므로 두 구조의 차이는 지정한 변이만이 아니다.",
  "변이형에는 야생형 기준에 없는 이황화 결합이 거리 기준으로 만들어졌다.",
];
const ORIGIN_LABEL = { initial: "초기", carried: "이어받음", crossover: "교차", edit: "편집", random: "무작위" };
const STOP_STATUS = { generations_complete: "complete", no_change: "complete", space_exhausted: "complete",
  evaluation_limit: "partial", time_exhausted: "partial", cancelled: "partial", worker_failed: "partial",
  resource_exceeded: "partial", reference_failed: "partial", repeated_failure: "partial" };
const NO_CHANGE_LABEL = "점수 최솟값 변화 없음";
const MAY_BE_PARTIAL = "끝까지 못 갈 수 있음";
const M18_HEAVY_ATOM_ESTIMATE = 4890;
const RESIDUE_FIELDS = ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"];
const FORBIDDEN_GA = new RegExp(["순위", "최고", "최적(?!화)", "개선", "승자", "우승", "추천", "유망", "좋은", "나쁜", "우수",
  "우월", "상위", "하위", "향상", "악화", "대비", "차이", "증감", "증가", "감소", "변화량", "평균", "효과", "친화", "안정성",
  "ΔΔG", "Δ", "결합\\s*강도", "부분\\s*완료", "\\brank", "\\bbest", "improv", "winner", "recommend", "optimal", "stabili",
  "delta", "differen", "affinity", "better", "worse", "superior", "↑", "↓", "▲", "▼"].join("|"), "gi");
// M24 / M25 (copied from jev-flow.cjs / jev-loop-flow.cjs).
const NOT_REPORTED_TEXT = "보고 없음";
const UNKNOWN_USAGE_TEXT = "알 수 없음";
const REQUEST_MODEL = "typesafe/jev-1.13";
const PROVIDER = { allow_fallbacks: false, data_collection: "deny", zdr: true };
const WIRE_TOP_MUTATION = ["candidates", "computed", "goal", "pockets", "positions", "protection_checks", "schema", "task",
  "values_note"];
const MUTATION_EXPLOIT_SUFFIX = "; each score belongs to the modelled structure of its own mutation";
const CONFIRMING_TEXT = "루프 기록이 이 전송의 완료를 아직 보이지 않습니다. 기록을 다시 읽어 이 바퀴의 선택인지 확인하는 중입니다.";
const LOOP_WORDING_EXEMPT = '[data-testid="jev-loop-m18-area"], [data-testid="jev-loop-limitations"], ' +
  '[data-testid="jev-loop-choice-limitations"], [data-testid="jev-loop-preview-body"], ' +
  '[data-testid="jev-loop-preview-question"], .mw-ligand-filter';

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const textDigest = text => ({ chars: (text ?? "").length, sha256: sha(Buffer.from(text ?? "", "utf8")) });
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const attr = (name, value) => `[${name}="${String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"]`;
const { halfUp } = M21;
const seconds = value => `${halfUp(value, 1)}초`;
const pairText = pair => `비싼 계산 ${pair.expensive_calls}단위 · 활동 시간 ${seconds(pair.wall_clock_s)}`;
const count = value => String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const strings = values => Object.fromEntries(Object.entries(values).map(([key, value]) => [key, String(value)]));
const resShort = r => `${r.resname} ${r.chain_auth}:${r.seq_auth}${r.icode}`;
const rkey = resShort;
const fieldsText = r => RESIDUE_FIELDS.map(key => `${key}=${JSON.stringify(r[key])}`).join(", ");
const mutText = m => `${resShort(m.residue)} ${m.from}→${m.to}`;
const candidateText = row => `${resShort(row.residue)} ${row.from}→${row.to}`;
const sameResidue = (x, y) => !!x && !!y && RESIDUE_FIELDS.every(field => x[field] === y[field]);
const modelPath = (run, handle, tail = "") => `/runs/${run}/mutation_models/${enc(handle)}${tail}`;
const setPath = (run, handle, tail = "") => `/runs/${run}/mutation_candidate_sets/${enc(handle)}${tail}`;

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
    `Usage: endtoend-c-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> --plan <plan.json> --runs-dir <MW_RUNS_DIR> ` +
    "[--control <fixture control dir> --backend-pid <pid of the fixture server just started> (fixture: required; live: " +
    "the rehearsal)] [--url http://127.0.0.1:3000]. Plan and sequence: scripts/m28_branch_c.py through " +
    "scripts/m28_offscreen_acceptance.py.");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  for (const key of ["artifacts", "runs-dir", "control", "plan"]) if (value[key]) value[key] = path.resolve(value[key]);
  value["backend-pid"] = pid;
  value.url = new URL("/", value.url).toString();
  value.planData = JSON.parse(fs.readFileSync(value.plan, "utf8"));
  assert.equal(value.planData.schema, "m28_branch_c_plan@1");
  assert.equal(value.planData.phase, value.mode, "the plan is of another phase");
  return value;
}

// ------------------------------------------------------------------ read-only observation (copied from endtoend-b-flow.cjs)
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
function objectHandles(runsDir, run, kind) {
  return runEvents(runsDir, run).filter(event => event.type === "object_created" && (event.handle ?? "").includes(`/${kind}/`))
    .map(event => event.handle);
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

// ------------------------------------------------------------------ evidence (copied from endtoend-b-flow.cjs recorder)
/** Steps and parts. A part runs only when the parts it needs passed; a step failure fails its part, which is recorded
 * and the flow goes on with the next part (and the unit tracker leaves its plan). */
function recorder(session, evidence, onPartFailure) {
  const { app, page, artifacts } = session;
  const file = path.join(artifacts, "endtoend-c.jsonl");
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
const OMITTED_TEXT = new Set(["body", "instructions", "question", "text", "markdown"]);
function summarize(value) {
  try {
    const text = JSON.stringify(value, (key, item) => OMITTED_TEXT.has(key) && typeof item === "string"
      ? `<omitted ${item.length} characters>` : item);
    // an oversized value is kept as its length and digest (a cut JSON string would quote product text out of its lines)
    return text.length > 8000 ? { omitted: "over 8000 characters", ...textDigest(text) } : JSON.parse(text);
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

/** The remaining expensive units before every computation and the units each computation used (adapted from
 * endtoend-b-flow.cjs: decision 1 asks for "need ≤ remaining" before every computation, the planned raise included;
 * whether the remaining units are the plan's number is recorded with the entry). */
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
        plannedRemaining: plan.units.remainingBefore[label], raisePlanned: plan.units.raises[label] ?? 0, onPlan };
      entry.remainingMatchesPlan = entry.remaining === entry.plannedRemaining;
      evidence.units.push(entry);
      assert.ok(entry.planned <= entry.remaining + entry.raisePlanned, `${label}: ${entry.planned} units needed, ` +
        `${entry.remaining} remain (+${entry.raisePlanned} by a planned raise)`);
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

// ------------------------------------------------------------------ tabs, runs, structure screen (copied from mutation-flow.cjs)
const tabButton = (page, label) => page.locator(".mw-app-tabs").getByRole("tab", { name: label, exact: true });
async function selectTab(page, label) {
  await tabButton(page, label).click();
  await waitFor(page, async () => await tabButton(page, label).getAttribute("aria-selected") === "true", `${label} selected`, 10000);
}
/** The tab mounts its areas afresh when it is selected (their lists are read on mount): leave it first when it is the
 * shown tab (adapted from endtoend-b-flow.cjs openLoopArea). */
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
/** 전처리 with the screen's policies; `waters` (keep_all for the M7 run, openmm-flow.cjs O-setup-policy) is chosen in the
 * same row first when given. */
async function prepareManual(page, waters = null) {
  const back = page.getByRole("button", { name: "최신 구조로 돌아가기", exact: true });
  if (await back.isVisible().catch(() => false)) await back.click();
  const row = page.locator(".mw-workflow-row").filter({ has: page.getByRole("button", { name: "전처리", exact: true }) });
  if (waters) {
    const select = row.getByRole("combobox", { name: /^물/ });
    await select.selectOption(waters);
    assert.equal(await select.inputValue(), waters);
  }
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

// ------------------------------------------------------------------ M20 mutation panel (copied from mutation-flow.cjs)
const panel = page => page.locator('#mw-app-panel-protein [data-testid="mutation-panel"]');
const testId = (page, id) => panel(page).locator(`[data-testid="${id}"]`);
const panelState = page => panel(page).getAttribute("data-mutation-state", { timeout: 2000 }).catch(() => null);
async function waitState(page, states, timeout = 60000) {
  const wanted = Array.isArray(states) ? states : [states];
  return waitFor(page, async () => { const state = await panelState(page); return wanted.includes(state) ? state : null; },
    `mutation panel ${wanted.join("|")}`, timeout);
}
/** Tab entered afresh, every run list read (structure radios enabled, result list ready). */
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
async function chosenResidues(page, picker) {
  if (!await testId(page, `mutation-chosen-${picker}`).count()) return [];
  return testId(page, `mutation-chosen-${picker}`).locator("li[data-mutation-residue]").evaluateAll(items =>
    items.map(item => item.getAttribute("data-mutation-residue")));
}
async function pickerCount(page, picker) { return Number(await testId(page, `mutation-picker-${picker}`).getAttribute("data-count")); }
/** Pick one residue (select + 넣기) by its displayed auth text (the option keeps the 7 fields). */
async function pickResidueAt(page, picker, spec) {
  const select = testId(page, `mutation-pick-${picker}`);
  const option = await waitFor(page, async () => {
    const found = (await selectOptions(select)).filter(item => item.text.startsWith(`${spec.resname} ${spec.chain}:${spec.seq} ·`)
      && !item.disabled);
    return found.length === 1 ? found[0] : null;
  }, `${picker} option ${spec.resname} ${spec.chain}:${spec.seq}`, 60000);
  const before = await pickerCount(page, picker);
  await select.selectOption(option.value);
  await testId(page, `mutation-add-${picker}`).click();
  await waitFor(page, async () => await pickerCount(page, picker) === before + 1 ? true : null, `${picker} count +1`, 10000);
}
async function removeResidue(page, picker, text) {
  const before = await pickerCount(page, picker);
  await testId(page, `mutation-chosen-${picker}`).locator(`li${attr("data-mutation-residue", text)} ` +
    `[data-testid="mutation-remove-${picker}"]`).click();
  await waitFor(page, async () => await pickerCount(page, picker) === before - 1 ? true : null, `${picker} count -1`, 10000);
}
/** The pickers hold exactly `wanted` (adapted from sequence-ga-flow.cjs m20Create: residues of an earlier request are
 * removed first). */
async function setPicker(page, picker, wanted) {
  const texts = wanted.map(spec => `${spec.resname} ${spec.chain}:${spec.seq}`);
  for (const text of await chosenResidues(page, picker)) if (!texts.includes(text)) await removeResidue(page, picker, text);
  for (const spec of wanted)
    if (!(await chosenResidues(page, picker)).includes(`${spec.resname} ${spec.chain}:${spec.seq}`))
      await pickResidueAt(page, picker, spec);
}
async function requestErrors(page) {
  if (!await testId(page, "mutation-request-errors").count()) return [];
  return testId(page, "mutation-request-errors").locator("li").allInnerTexts();
}
/** Click 후보 만들기; returns the POST args and reply; a success opens the stored set. */
async function create(page, run) {
  await waitFor(page, async () => await testId(page, "mutation-create").isEnabled() ? true : null, "후보 만들기 enabled", 15000)
    .catch(async error => { throw new Error(`${error.message}; request errors: ${(await requestErrors(page)).join(" | ")}`); });
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === M20_TOOL,
  { timeout: 120000 });
  await testId(page, "mutation-create").click();
  const response = await posted;
  const body = await response.json();
  const args = response.request().postDataJSON().args;
  if (body.ok !== true) {
    await testId(page, "mutation-create-error").waitFor({ timeout: 30000 });
    return { ok: false, status: response.status(), body, args };
  }
  const handle = body.handle.handle;
  await panel(page).locator(`[data-testid="mutation-create-done"]${attr("data-mutation-new-set", handle)}`).waitFor({ timeout: 30000 });
  await panel(page).locator(`[data-testid="mutation-detail"]${attr("data-mutation-detail", handle)}`).waitFor({ timeout: 60000 });
  await waitState(page, ["ready", "scientific_null"]);
  return { ok: true, status: response.status(), body, args, handle };
}
async function openSet(page, handle) {
  await panel(page).locator(`label${attr("data-mutation-set", handle)} input`).check();
  await panel(page).locator(`[data-testid="mutation-detail"]${attr("data-mutation-detail", handle)}`).waitFor({ timeout: 60000 });
}
async function storedSet(page, run, handle) {
  const detail = await readApi(page, setPath(run, handle));
  assert.equal(detail.schema, "mutation_candidate_set_detail@1");
  return detail;
}
async function storedPositions(page, run, handle, query = "") {
  const rows = [];
  let total = null;
  while (total === null || rows.length < total) {
    const chunk = await readApi(page, setPath(run, handle, `/positions?${query}${query ? "&" : ""}offset=${rows.length}&limit=100`));
    total = chunk.total;
    rows.push(...chunk.rows);
    if (!chunk.rows.length) break;
  }
  return rows;
}
async function storedCandidates(page, run, handle) {
  const rows = [];
  let total = null;
  while (total === null || rows.length < total) {
    const chunk = await readApi(page, setPath(run, handle, `/candidates?offset=${rows.length}&limit=100`));
    total = chunk.total;
    rows.push(...chunk.rows);
    if (!chunk.rows.length) break;
  }
  return rows;
}
async function positionRows(page) {
  if (!await testId(page, "mutation-positions").count()) return [];
  return testId(page, "mutation-positions").locator("tr[data-mutation-position]").evaluateAll(items => items.map(item => {
    const cells = [...item.querySelectorAll("td")].map(cell => cell.textContent.replace(/\s+/g, " ").trim());
    return { index: Number(item.getAttribute("data-mutation-position")), status: item.getAttribute("data-status"),
      reasons: item.getAttribute("data-exclusion-reasons"), residue: item.getAttribute("data-residue"),
      distanceAttr: item.getAttribute("data-ligand-distance"),
      distanceText: item.querySelector('[data-cell="ligand-distance"]')?.textContent.trim() ?? null, cells };
  }));
}
async function pager(page, id) {
  const node = testId(page, `${id}-pager`);
  if (!await node.count()) return null;
  return { total: Number(await node.getAttribute("data-total")), offset: Number(await node.getAttribute("data-offset")) };
}
/** UI position rows must equal the stored page of the same query (index order, status, reasons, distance text). */
function positionsMatch(ui, api, ligandGiven) {
  assert.deepEqual(ui.map(row => row.index), api.rows.map(row => row.index), "position index order");
  api.rows.forEach((row, i) => {
    const shown = ui[i];
    assert.equal(shown.status, row.status, `position ${row.index} status`);
    assert.equal(shown.reasons, row.exclusion_reasons.join(","), `position ${row.index} reasons`);
    assert.equal(shown.residue, `${row.residue.resname} ${row.residue.chain_auth}:${row.residue.seq_auth}${row.residue.icode}`);
    if (row.ligand_min_distance_A === null) {
      assert.equal(shown.distanceAttr, "");
      assert.ok(shown.distanceText.startsWith("—"), `null distance shown as ${shown.distanceText}`);
      assert.ok(!/\d/.test(shown.distanceText), `null distance shown with a number: ${shown.distanceText}`);
    } else {
      assert.ok(ligandGiven);
      assert.equal(shown.distanceText, M20.halfUp2(row.ligand_min_distance_A), `position ${row.index} distance`);
    }
    assert.equal(shown.cells[13], String(row.candidate_count), `position ${row.index} candidate count`);
  });
}
async function waitPositions(page, run, handle, query, ligandGiven, label) {
  const api = await readApi(page, setPath(run, handle, `/positions?${query}`));
  await waitFor(page, async () => {
    const shown = await pager(page, "mutation-positions");
    if (!shown || shown.total !== api.total || shown.offset !== api.offset) return null;
    const rows = await positionRows(page);
    return rows.map(row => row.index).join(",") === api.rows.map(row => row.index).join(",") ? true : null;
  }, `${label}: position table = stored page (${query})`, 30000);
  const ui = await positionRows(page);
  if (api.rows.length) positionsMatch(ui, api, ligandGiven);
  return { query, total: api.total, offset: api.offset, indices: api.rows.map(row => row.index) };
}
/** Panel text outside the fixed limitation sentences, and the limitation sentences shown. */
async function m20Wording(page) {
  const seen = await panel(page).evaluate(node => {
    const copy = node.cloneNode(true);
    for (const item of copy.querySelectorAll('[data-testid="mutation-limitations"]')) item.remove();
    return copy.textContent;
  });
  return M20.forbiddenIn(seen, M20.FORBIDDEN_CATALYTIC);
}
async function catalyticCells(page) {
  if (!await testId(page, "mutation-positions").count()) return [];
  return testId(page, "mutation-positions").locator("tr[data-mutation-position]").evaluateAll(items => items.map(item => {
    const cell = item.querySelector('[data-cell="catalytic"]');
    return { residue: item.getAttribute("data-residue"), status: item.getAttribute("data-status"),
      reasons: item.getAttribute("data-exclusion-reasons"), kind: cell?.getAttribute("data-catalytic") ?? null,
      released: cell?.getAttribute("data-released") ?? null, text: cell?.textContent.trim() ?? null };
  }));
}
function catalyticCellText(protection) {
  const value = protection.catalytic;
  if (value === undefined) return "— (촉매 잔기 검사 전 v1 집합)";
  if (value === null) return "— (이 체인의 촉매 잔기를 검사하지 않음)";
  if (!value.length) return "대응된 M-CSA 촉매 잔기 행 없음(검사함)";
  const entries = value.map(entry => `M-CSA ${entry.mcsa_id} 잔기 순번 ${entry.residue_index}${entry.is_reference ? " · 기준 구조" : ""}`)
    .join(", ");
  return protection.released ? `${entries} · 해제됨` : entries;
}
/** The stored set's catalytic check, positions and limitations versus the screen (one opened set; adapted from
 * mutation-flow.cjs verifyCatalyticSet: the expectations are the plan's independent ones, the returned facts are the
 * stored check in the plan's shape). */
async function verifyCatalyticSet(page, run, handle, want) {
  const detail = await storedSet(page, run, handle);
  const result = detail.result;
  const check = result.protection_checks.catalytic_residue_database;
  const positions = await storedPositions(page, run, handle);
  await waitPositions(page, run, handle, "sort=order&offset=0&limit=50", result.ligand !== null, handle.slice(-8));
  const block = testId(page, "mutation-catalytic-check");
  const ui = { status: await block.getAttribute("data-catalytic-status"),
    statusText: clean(await testId(page, "mutation-catalytic-status").textContent()),
    covered: clean(await testId(page, "mutation-catalytic-covered-chains").textContent()),
    uncovered: clean(await testId(page, "mutation-catalytic-uncovered-chains").textContent()),
    matched: clean(await testId(page, "mutation-catalytic-matched").textContent()),
    badge: await testId(page, "mutation-catalytic-check-badge").count() ? clean(await testId(page, "mutation-catalytic-check-badge")
      .textContent()) : null,
    limits: await testId(page, "mutation-limitations").locator("[data-limitation]").allInnerTexts(),
    limitStatus: await testId(page, "mutation-limitations").getAttribute("data-catalytic-status"),
    reasonCounts: clean(await testId(page, "mutation-reason-counts").textContent()),
    reasonFilter: (await selectOptions(testId(page, "mutation-filter-reason"))).map(item => item.value).filter(Boolean),
    cells: await catalyticCells(page) };
  assert.equal(check.status, want.status, `${handle} catalytic status`);
  assert.equal(check.reason, want.reason, `${handle} catalytic reason`);
  assert.equal(ui.status, check.status);
  assert.ok(ui.statusText.includes(`(${check.status})`), ui.statusText);
  if (check.reason) assert.ok(ui.statusText.includes(`(${check.reason})`), ui.statusText);
  assert.equal(ui.limitStatus, check.status);
  assert.deepEqual(ui.limits, result.limitations);
  assert.equal(result.limitations[2], M20.LIMIT3[check.status], "limitation sentence 3 variant");
  assert.equal(result.method_version, "mw.mutation_candidates/v2");
  assert.deepEqual(Object.keys(result.counts.exclusion_reason_counts).sort(), [...EXCLUSION_V2].sort(), "exclusion reason keys");
  assert.deepEqual(ui.reasonFilter, EXCLUSION_V2, "reason filter options");
  for (const reason of EXCLUSION_V2) assert.ok(ui.reasonCounts.includes(M20.reasonCountText(reason,
    result.counts.exclusion_reason_counts[reason], check)), `${reason}: ${ui.reasonCounts}`);
  if (!(check.covered_chains ?? []).length)
    assert.ok(!/M-CSA 촉매 잔기 주석 \d/.test(ui.reasonCounts), `not checked shown as a count: ${ui.reasonCounts}`);
  if (!("covered_chains" in check)) {
    for (const text of [ui.covered, ui.uncovered, ui.matched])
      assert.ok(text.startsWith("—") && !/\d/.test(text), `not checked shown with a number: ${text}`);
    assert.ok(positions.every(row => row.protection.catalytic === null));
  } else {
    assert.deepEqual(check.covered_chains, want.covered, "covered chains");
    assert.deepEqual(check.uncovered_chains, want.uncovered, "uncovered chains");
    assert.deepEqual({ matched_rows: check.matched_rows, conflict_rows: check.conflict_rows,
      unmatched_rows: check.unmatched_rows }, want.counts, "row counts");
    assert.equal(ui.covered, check.covered_chains.length ? check.covered_chains.join(", ") : "— (M-CSA가 다룬 체인 없음)");
    assert.equal(ui.uncovered, check.uncovered_chains.length ? check.uncovered_chains.map(item =>
      `${item.chain_auth} ${UNCOVERED_LABEL[item.coverage]} (${item.coverage})`).join(", ") : "빈 목록 ([])");
    for (const row of positions) {
      const covered = check.covered_chains.includes(row.residue.chain_auth);
      if (!covered) { assert.equal(row.protection.catalytic, null, `${rkey(row.residue)} not covered`); continue; }
      assert.deepEqual(row.protection.catalytic.map(item => [item.mcsa_id, item.residue_index, item.is_reference]),
        want.catalytic[rkey(row.residue)] ?? [], `${rkey(row.residue)} catalytic`);
      assert.equal(row.protection.reasons.includes("catalytic_residue"), row.protection.catalytic.length > 0);
      if (row.protection.catalytic.length && !row.protection.released) {
        assert.equal(row.status, "excluded");
        assert.ok(row.exclusion_reasons.includes("catalytic_residue"));
      }
    }
  }
  if (check.status === "checked") assert.equal(ui.badge, null, "a checked set carries the not-checked mark");
  else assert.ok(ui.badge?.startsWith(M20.UK2), `badge ${ui.badge}`);
  const byResidue = new Map(positions.map(row => [rkey(row.residue), row]));
  assert.ok(ui.cells.length > 0);
  for (const cell of ui.cells) {
    const row = byResidue.get(cell.residue);
    assert.ok(row, `shown position ${cell.residue} not stored`);
    assert.equal(cell.text, catalyticCellText(row.protection), `${cell.residue} catalytic cell`);
    assert.equal(cell.released, row.protection.released ? "true" : null);
    if (row.protection.catalytic === null) assert.ok(!/\d/.test(cell.text), cell.text);
  }
  return { handle, status: check.status, reason: check.reason, covered: check.covered_chains ?? null,
    uncovered: check.uncovered_chains ?? null,
    counts: "covered_chains" in check ? { matched_rows: check.matched_rows, conflict_rows: check.conflict_rows,
      unmatched_rows: check.unmatched_rows } : null,
    catalytic: Object.fromEntries(positions.map(row => [rkey(row.residue), row.protection.catalytic === null ? null
      : row.protection.catalytic.map(item => [item.mcsa_id, item.residue_index, item.is_reference])])),
    protected: positions.filter(row => row.protection.catalytic?.length && !row.protection.released &&
      row.status === "excluded" && row.exclusion_reasons.includes("catalytic_residue")).map(row => rkey(row.residue)).sort(),
    positions, cells: ui.cells, reasonCounts: ui.reasonCounts, limitations: result.limitations };
}
/** 보고서 만들기 for an opened set; the saved report and its library view (adapted from mutation-flow.cjs Q01–Q02). */
async function m20Report(page, run, handle) {
  await openSet(page, handle);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
  await testId(page, "mutation-report").click();
  const response = await posted;
  const body = await response.json();
  await testId(page, "mutation-report-done").waitFor({ timeout: 30000 });
  return { status: response.status(), handle: body.handle, manifest: body.manifest, request: response.request().postDataJSON(),
    done: await testId(page, "mutation-report-done").getAttribute("data-report-handle") };
}

// ------------------------------------------------------------------ 효소 반응 지식 (copied from mutation-flow.cjs linkReaction)
const rpanel = page => page.locator('#mw-app-panel-knowledge [data-testid="reaction-panel"]');
const rt = (page, id) => rpanel(page).locator(`[data-testid="${id}"]`);
async function linkReaction(page, run, structure, pdbId, chains) {
  await selectTab(page, TAB.knowledge);
  await rpanel(page).waitFor({ timeout: 15000 });
  await rt(page, "reaction-request-form").waitFor({ timeout: 60000 });
  const select = rt(page, "reaction-structure");
  if (await select.inputValue() !== "") await select.selectOption("");
  await select.selectOption(structure);
  for (const chain of chains)
    await waitFor(page, async () => await rt(page, `reaction-chain-${chain}`).count() === 1 ? true : null, `chain ${chain}`, 60000);
  await waitFor(page, async () => { const hint = clean(await rt(page, "reaction-pdb-hint").textContent());
    return hint && !hint.includes("읽는 중") ? hint : null; }, "PDB ID suggestion", 30000);
  await rt(page, "reaction-pdb-id").fill(pdbId);
  await rt(page, "reaction-pdb-confirm").check();
  for (const chain of chains) await rt(page, `reaction-chain-${chain}`).check();
  const button = rt(page, "reaction-link");
  await waitFor(page, async () => await button.isEnabled() ? true : null, "연결하기 enabled", 15000);
  const response = page.waitForResponse(item => item.request().method() === "POST" &&
    new URL(item.url()).pathname === `/api/runs/${run}/commands` && item.request().postDataJSON()?.tool === REACTION_TOOL,
  { timeout: 180000 });
  await button.click();
  const body = await (await response).json();
  assert.equal(body.ok, true, `link failed: ${JSON.stringify(body).slice(0, 400)}`);
  await rpanel(page).locator(`[data-testid="reaction-link-done"]${attr("data-reaction-new-result", body.handle.handle)}`)
    .waitFor({ timeout: 30000 });
  return body.handle.handle;
}

// ------------------------------------------------------------------ M7 OpenMM section (adapted from openmm-flow.cjs O02–O08, annotation-flow.cjs N03)
const openmmSection = page => page.getByText("OpenMM 단백질 전용 최소화 · kJ/mol").locator("..");

// ------------------------------------------------------------------ M21 model panel (copied from mutation-model-flow.cjs)
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
    approval: await job.getAttribute("data-approval-pending"), text: clean(await job.locator("p").first().textContent()) };
}
/** Click 모델링 작업 제출; approve through 비싼 계산 승인 when asked, then 작업 시작; wait until the job ends. */
async function runModelJob(page, run) {
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
    await mt(page, "mutation-model-notice").filter({ hasText: "승인을 기록했습니다" }).waitFor({ timeout: 30000 });
    phases.push("approved");
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
  }, "model job final", 300000);
  const job = await readApi(page, `/runs/${run}/jobs/${enc(jobId)}`);
  return { jobId, request, submitted, phases, approved, done, job };
}
async function openModel(page, handle) {
  const radio = mpanel(page).locator(`label${attr("data-mutation-model", handle)} input`);
  await radio.waitFor({ timeout: 30000 });
  await radio.check();
  await mpanel(page).locator(`[data-testid="mutation-model-detail"]${attr("data-model-handle", handle)}`).waitFor({ timeout: 60000 });
}
async function sideBySide(page) {
  return mt(page, "mutation-model-side-by-side").evaluate(table => ({
    headers: [...table.querySelectorAll("thead th")].map(th => th.textContent.trim()),
    rows: [...table.querySelectorAll("tbody tr")].map(tr => {
      const cells = [...tr.querySelectorAll("td")];
      const style = cell => { const s = getComputedStyle(cell); return { color: s.color, background: s.backgroundColor,
        weight: s.fontWeight, className: cell.className, inline: cell.getAttribute("style") }; };
      return { key: tr.getAttribute("data-row-key"), label: cells[0].textContent.trim(), trStyle: tr.getAttribute("style"),
        values: Object.fromEntries(cells.slice(1).map(cell => [cell.getAttribute("data-side"), cell.textContent.trim()])),
        styles: Object.fromEntries(cells.slice(1).map(cell => [cell.getAttribute("data-side"), style(cell)])), cellCount: cells.length };
    }) }));
}
/** The side-by-side texts the stored result must produce (harness rounding; no value computed from both sides). */
function expectedSideBySide(result) {
  const per = pick => Object.fromEntries(SIDES.map(side => [side, pick(result.structures[side])]));
  const added = atoms => atoms.length ? `${atoms.length}개 (${atoms.map(atom => `${atom.atom_name} ${atom.element}`).join(", ")})` : "0개";
  return {
    resname: { ...result.comparison.resnames },
    energy_before: per(s => halfUp(s.energy.before_kJ_mol, 2)),
    energy_after: per(s => halfUp(s.energy.after_kJ_mol, 2)),
    sasa: per(s => `${halfUp(s.sasa.value_A2, 2)} Å²`),
    contacts: per(s => String(s.contacts.count)),
    contact_residues: per(s => String(s.contacts.residue_count)),
    added_heavy_atoms: per(s => added(s.added_heavy_atoms)),
    disulfide_bonds: per(s => String(s.disulfide_bonds.length)),
    heavy_atoms: per(s => String(s.heavy_atoms)),
    added_hydrogens: per(s => String(s.added_hydrogens)),
  };
}
async function contactView(page) {
  const area = mt(page, "mutation-model-contacts");
  if (!await area.count()) return null;
  return area.evaluate(node => ({ side: node.getAttribute("data-side"), total: Number(node.getAttribute("data-total")),
    page: Number(node.getAttribute("data-page")), count: node.querySelector('[data-testid="mutation-model-contacts-count"]')?.textContent.trim(),
    rows: [...node.querySelectorAll("tbody tr")].map(tr => ({ index: Number(tr.getAttribute("data-contact-index")),
      distance: tr.getAttribute("data-distance"), cells: [...tr.querySelectorAll("td")].map(td => td.textContent.trim()) })) }));
}
/** UI contact page = API page = the stored rows of that side, cell by cell (copied from mutation-model-flow.cjs). */
async function checkContacts(page, run, handle, stored, side, pageNo) {
  const api = await readApi(page, modelPath(run, handle, `/contacts?structure=${side}&page=${pageNo}&page_size=100`));
  const view = await waitFor(page, async () => {
    const value = await contactView(page);
    return value && value.side === side && value.page === pageNo && value.rows.length === api.rows.length ? value : null;
  }, `contact page ${side} ${pageNo}`, 30000);
  const rows = stored.structures[side].contacts.rows;
  let mismatches = 0;
  if (api.total !== rows.length || view.total !== api.total) mismatches++;
  api.rows.forEach((row, i) => {
    const want = rows[(pageNo - 1) * 100 + i];
    if (row.index !== (pageNo - 1) * 100 + i || row.distance_A !== want.distance_A || row.atom_name !== want.atom_name ||
        !sameResidue(row.partner_residue, want.partner_residue) || row.partner_atom_name !== want.partner_atom_name) mismatches++;
    const shown = view.rows[i];
    if (shown.index !== row.index || shown.distance !== String(row.distance_A) || JSON.stringify(shown.cells) !== JSON.stringify(
      [String(row.index + 1), `${row.atom_name} (${row.element})`, resShort(row.partner_residue),
        `${row.partner_atom_name} (${row.partner_element})`, `${halfUp(row.distance_A, 2)} Å`])) mismatches++;
  });
  return { side, page: pageNo, total: api.total, rows: api.rows.length, mismatches };
}
/** Panel text lines (innerText), forbidden words outside the fixed limitation sentences and the score name. */
async function modelWording(page, limitations) {
  const text = await mpanel(page).evaluate(node => node.innerText);
  const found = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || Object.values(L21).includes(line) || limitations.includes(line)) continue;
    const checked = line.split(SCORE_LABEL).join("").split(SCORE_COLUMN).join("");
    for (const match of checked.matchAll(FORBIDDEN_MODEL)) found.push({ word: match[0], line: line.slice(0, 200) });
  }
  return { found, chars: text.length };
}
async function pairView(page) {
  const table = mt(page, "mutation-model-pairs");
  if (!await table.count()) return null;
  return table.evaluate(node => ({ total: Number(node.getAttribute("data-total")),
    headers: [...node.querySelectorAll("thead th")].map(th => th.textContent.trim()),
    rows: [...node.querySelectorAll("tbody tr")].map(tr => ({ index: Number(tr.getAttribute("data-pair-index")),
      cellCount: tr.querySelectorAll("td").length, trStyle: tr.getAttribute("style"),
      sides: Object.fromEntries([...tr.querySelectorAll("td[data-side]")].map(td => {
        const s = getComputedStyle(td);
        return [td.getAttribute("data-side"), { hasScore: td.getAttribute("data-has-score"),
          result: td.getAttribute("data-result-handle"), text: td.querySelector(".mw-mono")?.textContent.trim() ?? "",
          job: td.querySelector(".mw-mutation-note")?.textContent.trim() ?? "", color: s.color, background: s.backgroundColor,
          weight: s.fontWeight, className: td.className, inline: td.getAttribute("style") }];
      })) })) }));
}
async function pairJobs(page) {
  return Object.fromEntries(await Promise.all(SIDES.map(async side => {
    const node = mt(page, `mutation-model-pair-job-${side}`);
    if (!await node.count()) return [side, null];
    return [side, { submit: await node.getAttribute("data-submit-status"), status: await node.getAttribute("data-job-status"),
      id: await node.getAttribute("data-job-id") }];
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
/** Tick the 2-unit confirmation, click 같은 조건 도킹 제출 once; the two POST /jobs (qvina) of that one click. */
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
/** Drive the saved pair jobs by the screen's own buttons (approve when asked, 남은 작업 차례로 시작) until both end. */
async function drivePair(page, ids) {
  const actions = [];
  const deadline = Date.now() + 600000;
  while (Date.now() < deadline) {
    const jobs = await pairJobs(page);
    if (SIDES.every(side => ["done", "failed", "cancelled", "interrupted"].includes(jobs[side]?.status))) return { actions, jobs };
    if (await mt(page, "mutation-model-pair-approve").isVisible().catch(() => false) &&
        await mt(page, "mutation-model-pair-approve").isEnabled().catch(() => false)) {
      await mt(page, "mutation-model-pair-approve").click();
      actions.push({ approve: true });
      await page.waitForTimeout(500);
      continue;
    }
    if (await mt(page, "mutation-model-pair-continue").isVisible().catch(() => false) &&
        await mt(page, "mutation-model-pair-continue").isEnabled().catch(() => false)) {
      await mt(page, "mutation-model-pair-continue").click();
      actions.push({ continue: true });
      await page.waitForTimeout(500);
      continue;
    }
    await page.waitForTimeout(300);
  }
  throw new Error(`pair jobs did not end: ${JSON.stringify(await pairJobs(page))} ids ${JSON.stringify(ids)}`);
}

// ------------------------------------------------------------------ ligand SDF import (copied from sequence-ga-flow.cjs importLigandSdf)
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

// ------------------------------------------------------------------ M23 sequence GA area (copied from sequence-ga-flow.cjs)
const seqPanel = page => page.locator('#mw-app-panel-protein [data-testid="sequence-ga-panel"]');
const st = (page, id) => seqPanel(page).locator(`[data-testid="${id}"]`);
const gaArea = (page, name) => seqPanel(page).locator(`[data-sequence-ga-area="${name}"]`);
const gaState = page => seqPanel(page).getAttribute("data-ga-state", { timeout: 2000 }).catch(() => null);
async function enabled(locator) { return locator.isEnabled({ timeout: 1000 }).catch(() => false); }
async function openGaArea(page) {
  await enterTab(page, TAB.protein);
  await seqPanel(page).waitFor({ timeout: 15000 });
  return waitFor(page, async () => {
    const state = await gaState(page);
    if (state === "unavailable" || state === "failed") return state;
    if ((state === "ready" || state === "empty") &&
        await gaArea(page, "results").getAttribute("data-state", { timeout: 1000 }).catch(() => null) === "ready") return state;
    return null;
  }, "sequence GA area settled", 90000);
}
function gaForbidden(text, exempt) {
  const found = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || exempt.has(line)) continue;
    const checked = line.split(SCORE_LABEL).join("").split(SCORE_COLUMN).join("");
    for (const match of checked.matchAll(FORBIDDEN_GA)) found.push({ word: match[0], line: line.slice(0, 200) });
  }
  return found;
}
async function gaFill(page, id, value) { const field = st(page, id); await field.click(); await field.fill(String(value)); }
async function startState(page) {
  return { enabled: await st(page, "sequence-ga-start").isEnabled(),
    blocked: clean(await st(page, "sequence-ga-start-blocked").textContent({ timeout: 1000 }).catch(() => "")),
    preflightEnabled: await st(page, "sequence-ga-preflight").isEnabled() };
}
async function setChecked(locator, on) { if (await locator.isChecked() !== on) await locator.setChecked(on); }
/** ① inputs: candidate set, 3D SDF, ligand-range box, evaluation seed and docking values, confirmations, acks. */
async function chooseGaInputs(page, run, input) {
  const reread = page.waitForResponse(response => response.request().method() === "GET" &&
    new URL(response.url()).pathname === `/api/runs/${run}/docking/prerequisites`, { timeout: 30000 });
  reread.catch(() => undefined);
  await st(page, "sequence-ga-prereq-refresh").click();
  await reread;
  await waitFor(page, async () => await st(page, "sequence-ga-candidate-set").locator(`option${attr("value", input.set)}`)
    .count() ? true : null, "candidate set offered", 30000);
  await st(page, "sequence-ga-candidate-set").selectOption(input.set);
  await setChecked(seqPanel(page).locator('label[data-pair-ligand-source="sdf"] input'), true);
  await waitFor(page, async () => await st(page, "sequence-ga-sdf").locator(`option${attr("value", input.sdf)}`).count()
    ? true : null, "SDF offered", 30000);
  await st(page, "sequence-ga-sdf").selectOption(input.sdf);
  await setChecked(seqPanel(page).locator('label[data-pair-box="ligand_range"] input'), true);
  await gaFill(page, "sequence-ga-margin", input.docking.margin);
  for (const [id, value] of [["sequence-ga-seed", input.docking.seed], ["sequence-ga-exhaustiveness", input.docking.exhaustiveness],
    ["sequence-ga-num-modes", input.docking.numModes], ["sequence-ga-energy-range", input.docking.energyRange]])
    await gaFill(page, id, value);
  await setChecked(st(page, "sequence-ga-confirm-selection"), true);
  await setChecked(st(page, "sequence-ga-confirm-hydrogen"), true);
  for (const key of ACK_KEYS) await setChecked(seqPanel(page).locator(`label[data-pair-ack="${key}"] input`), true);
}
async function gaPreflight(page, run) {
  await waitFor(page, async () => await st(page, "sequence-ga-preflight").isEnabled() ? true : null, "preflight enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/sequence_ga/preflight`, { timeout: 120000 });
  posted.catch(() => undefined);
  await st(page, "sequence-ga-preflight").click();
  const response = await posted;
  const body = await response.json();
  return { status: response.status(), body, request: response.request().postDataJSON(), view: await gaPreflightView(page, body) };
}
const factLines = locator => locator.evaluateAll(items => items.map(item =>
  [item.querySelector("dt").textContent.trim(), item.querySelector("dd").textContent.trim()]));
async function gaPreflightView(page, body) {
  if (!body.admission.admitted) {
    await st(page, "sequence-ga-preflight-refused").waitFor({ timeout: 30000 });
    return { refused: clean(await st(page, "sequence-ga-preflight-refused").textContent()),
      reasonCode: await st(page, "sequence-ga-preflight-refused").getAttribute("data-reason-code"), start: await startState(page) };
  }
  const view = st(page, "sequence-ga-preflight-view");
  await waitFor(page, async () => await view.count() &&
    await view.getAttribute("data-reserved-units") === String(body.reserved_units) &&
    await view.getAttribute("data-shortfall-calls") === String(body.shortfall.expensive_calls) ? true : null,
  "preflight view", 30000);
  const data = Object.fromEntries(await Promise.all(["data-reserved-units", "data-reserved-evaluations", "data-reusable",
    "data-reference-reusable", "data-shortfall-calls", "data-shortfall-wall", "data-may-be-partial",
    "data-heavy-atom-warning", "data-space-size"].map(async name => [name, await view.getAttribute(name)])));
  return { data, lines: Object.fromEntries(await factLines(view.locator("[data-preflight-line]"))),
    statements: await st(page, "sequence-ga-preflight-statements").locator("li[data-statement]").evaluateAll(items =>
      items.map(item => ({ id: item.getAttribute("data-statement"), text: item.textContent.trim() }))).catch(() => []),
    approvalButtons: await st(page, "sequence-ga-limit-approve").count(), start: await startState(page) };
}
/** The displayed preflight equals the server numbers, and the server numbers equal the spec 7 arithmetic and the plan
 * (adapted from sequence-ga-flow.cjs preflightMatches). */
function gaPreflightMatches(pf, { gaValues, space, want, reusable, referenceReusable }) {
  const body = pf.body, view = pf.view;
  const arithmetic = M23.needFor(gaValues);
  assert.equal(pf.status, 200);
  assert.equal(body.admission.admitted, true, JSON.stringify(body.admission));
  assert.equal(body.starts_job, false);
  assert.deepEqual(body.ga, gaValues, "the preflight's effective parameters differ from the typed values");
  assert.deepEqual(body.space, space, "the preflight space differs from the hand-counted space");
  assert.equal(body.reserved_evaluations, arithmetic.reservedEvaluations);
  assert.equal(body.reserved_evaluations, want.reservedEvaluations, "reserved_evaluations differs from the plan");
  assert.equal(body.reserved_units, want.reserved, "reserved_units differs from 2 × (reserved_evaluations + 1)");
  assert.deepEqual(body.needed, arithmetic.needed, "needed differs from spec 7 arithmetic");
  assert.equal(body.needed.wall_clock_s, want.neededWall);
  assert.deepEqual(body.shortfall, M23.shortfallFor(body.needed, body.remaining), "shortfall differs from needed − remaining");
  assert.equal(body.full_run_may_be_partial, want.mayBePartial);
  if (reusable !== undefined) assert.equal(body.reusable_count, reusable, "reusable individuals");
  if (referenceReusable !== undefined) assert.equal(body.reference_reusable, referenceReusable, "reference row reuse");
  assert.deepEqual(body.statements, ["S1", "S4", "S5", "S6"].map(id => ({ id, text: S23[id] })));
  assert.equal(body.heavy_atom_warning, body.projection_heavy_atoms > M18_HEAVY_ATOM_ESTIMATE);
  assert.equal(view.data["data-reserved-units"], String(body.reserved_units));
  assert.equal(view.data["data-reserved-evaluations"], String(body.reserved_evaluations));
  assert.equal(view.data["data-shortfall-calls"], String(body.shortfall.expensive_calls));
  assert.equal(view.data["data-space-size"], String(body.space.size));
  assert.equal(view.lines["예약 단위"], `${body.reserved_units}단위 (새 평가 최대 ${body.reserved_evaluations}건 × 2단위 + ` +
    "야생형 기준 행 2단위)");
  assert.equal(view.lines["필요"], `${pairText(body.needed)} (최대)`);
  assert.equal(view.lines["현재 잔여"], pairText(body.remaining));
  assert.equal(view.lines["부족분"], pairText(body.shortfall));
  assert.equal(view.lines["과금"], `시작하면 ${body.reserved_units}단위가 예약·소진되고 중간에 멈추거나 재사용이 있어도 돌려받지 않음`);
  if (body.full_run_may_be_partial) assert.ok(view.lines["시간 상한"].startsWith(MAY_BE_PARTIAL), view.lines["시간 상한"]);
  assert.deepEqual(view.statements, ["S1", "S4", "S5", "S6"].map(id => ({ id, text: S23[id] })));
  const shortfall = body.shortfall.expensive_calls > 0 || body.shortfall.wall_clock_s > 0;
  assert.equal(view.approvalButtons, shortfall ? 1 : 0, "limit approval shown iff shortfall > 0");
  assert.equal(view.start.enabled, !shortfall, `start ${view.start.enabled} with shortfall ${JSON.stringify(body.shortfall)}`);
  return { reservedEvaluations: body.reserved_evaluations, reserved: body.reserved_units, needed: body.needed,
    remaining: body.remaining, shortfall: body.shortfall, mayBePartial: body.full_run_may_be_partial,
    reusable: body.reusable_count, referenceReusable: body.reference_reusable, space: body.space,
    reservedLine: view.lines["예약 단위"] };
}
/** Click the screen's limit approval button (a person's click); the area reads the preflight again itself. */
async function gaApproveLimits(page, runsDir, run, pf) {
  const budget = await readApi(page, `/runs/${run}/budget`);
  const eventsBefore = runEvents(runsDir, run).length;
  const jobsBefore = (await readApi(page, `/runs/${run}/jobs`)).length;
  const approval = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/sequence_ga/limit_approval`, { timeout: 60000 });
  const reread = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/sequence_ga/preflight`, { timeout: 120000 });
  approval.catch(() => undefined);
  reread.catch(() => undefined);
  await st(page, "sequence-ga-limit-approve").click();
  const approvedResponse = await approval;
  const approved = await approvedResponse.json();
  const again = await (await reread).json();
  await st(page, "sequence-ga-limit-done").waitFor({ timeout: 30000 });
  const view = await gaPreflightView(page, again);
  await page.waitForTimeout(500);
  return { budget, approved, status: approvedResponse.status(), approvalRequest: approvedResponse.request().postDataJSON(),
    again, view, events: runEvents(runsDir, run).slice(eventsBefore),
    done: clean(await st(page, "sequence-ga-limit-done").textContent()),
    raisedAttr: await st(page, "sequence-ga-limit-done").getAttribute("data-raised"),
    budgetAfter: await readApi(page, `/runs/${run}/budget`), jobsBefore,
    jobsAfter: (await readApi(page, `/runs/${run}/jobs`)).length, pf };
}
function gaApprovalMatches(value) {
  const { pf, approved, budget, budgetAfter, events } = value;
  const shortfall = pf.body.shortfall;
  assert.equal(value.status, 200);
  assert.equal(approved.raised, true);
  assert.equal(approved.increase.expensive_calls, shortfall.expensive_calls, "the raise is not the unit shortfall");
  assert.ok(approved.increase.wall_clock_s >= shortfall.wall_clock_s, "the wall raise is below the shortfall");
  assert.deepEqual(value.approvalRequest, pf.request, "the approval body is not the previewed GA arguments");
  assert.equal(budgetAfter.expensive_calls.limit, budget.expensive_calls.limit + shortfall.expensive_calls);
  assert.equal(budgetAfter.expensive_calls.used, budget.expensive_calls.used, "the approval used budget");
  const updated = events.filter(event => event.type === "budget_limit_updated");
  assert.equal(updated.length, 1, JSON.stringify(events.map(event => event.type)));
  assert.equal(updated[0].by, "human");
  assert.equal(updated[0].context.purpose, "sequence_ga_limit_raise");
  assert.ok(!events.some(event => event.type.startsWith("job_") || event.type === "object_created"),
    "the approval created a job or an object");
  assert.equal(value.jobsAfter, value.jobsBefore, "the approval submitted a job");
  assert.equal(value.raisedAttr, "true");
  assert.ok(value.done.includes("되돌리지 않음"), value.done);
  assert.deepEqual(value.again.shortfall, { expensive_calls: 0, wall_clock_s: 0 });
  assert.equal(value.view.approvalButtons, 0, "approval still offered without a shortfall");
  assert.equal(value.view.start.enabled, true, value.view.start.blocked);
  return { shortfall, increase: approved.increase, limitsBefore: approved.limits_before, limitsAfter: approved.limits_after };
}
async function gaJobPhase(page) {
  const job = st(page, "sequence-ga-job");
  if (!await job.count()) return null;
  return { phase: await job.getAttribute("data-ga-job-phase"), status: await job.getAttribute("data-ga-job-status"),
    id: await job.getAttribute("data-ga-job-id") };
}
/** Click 서열 GA 시작; approve when asked, then 작업 시작; wait until the job ends. */
async function runGa(page, run) {
  const phases = [];
  const previousJob = (await gaJobPhase(page))?.id ?? null;
  await waitFor(page, async () => (await startState(page)).enabled ? true : null, "start enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/jobs`, { timeout: 120000 });
  posted.catch(() => undefined);
  await st(page, "sequence-ga-start").click();
  const response = await posted;
  const request = response.request().postDataJSON();
  const settled = async () => {
    const value = await gaJobPhase(page);
    if (!value || value.id === previousJob) return null;
    if (["running", "done", "failed", "cancelled"].includes(value.phase)) return value;
    if (value.phase === "awaiting_approval" && await enabled(st(page, "sequence-ga-job-approve"))) return value;
    if (value.phase === "saved" && await enabled(st(page, "sequence-ga-job-start"))) return value;
    return null;
  };
  const first = await waitFor(page, settled, "GA job submitted", 120000);
  phases.push(first.phase);
  let approved = false;
  if (first.phase === "awaiting_approval") {
    await st(page, "sequence-ga-job-approve").click();
    approved = true;
    await waitFor(page, async () => (await settled())?.phase === "saved" ? true : null, "approval recorded", 30000);
  }
  if ((await gaJobPhase(page)).phase === "saved" && await enabled(st(page, "sequence-ga-job-start")))
    await st(page, "sequence-ga-job-start").click();
  const done = await waitFor(page, async () => {
    const value = await gaJobPhase(page);
    if (value && value.phase !== phases.at(-1)) phases.push(value.phase);
    return value && ["done", "failed", "cancelled"].includes(value.phase) ? value : null;
  }, "GA job", 1500000);
  const job = await readApi(page, `/runs/${run}/jobs/${enc(done.id)}`);
  return { phases, approved, request, job, handle: job.sequence_ga?.summary_handle ?? null };
}
async function openGaSummary(page, handle) {
  await waitFor(page, async () => await enabled(seqPanel(page).locator(`label${attr("data-ga-summary", handle)} input`))
    ? true : null, "summary listed", 60000);
  await seqPanel(page).locator(`label${attr("data-ga-summary", handle)} input`).check();
  await st(page, "sequence-ga-result").and(seqPanel(page).locator(attr("data-ga-handle", handle))).waitFor({ timeout: 60000 });
  const view = st(page, "sequence-ga-result");
  return { handle: await view.getAttribute("data-ga-handle"), status: await view.getAttribute("data-ga-status"),
    stopReason: await view.getAttribute("data-stop-reason"), generationsDone: await view.getAttribute("data-generations-done"),
    statusText: clean(await st(page, "sequence-ga-status").textContent()),
    statements: await st(page, "sequence-ga-statements").locator("li").evaluateAll(items => items.map(item =>
      ({ id: item.getAttribute("data-statement"), text: item.textContent.trim() }))),
    summaryLines: Object.fromEntries(await factLines(st(page, "sequence-ga-summary").locator("[data-line]"))),
    tabs: await st(page, "sequence-ga-generation-tabs").locator('[role="tab"]').evaluateAll(items => items.map(item => ({
      id: item.getAttribute("data-testid"), complete: item.getAttribute("data-complete"), text: item.textContent.trim() })))
      .catch(() => []),
    reference: await st(page, "sequence-ga-reference").evaluate(node => ({ state: node.getAttribute("data-state"),
      evaluation: node.getAttribute("data-evaluation"), inTable: !!node.closest("table"),
      title: node.querySelector(".mw-eyebrow")?.textContent.trim() ?? null,
      lines: Object.fromEntries([...node.querySelectorAll("dl > div")].map(item =>
        [item.querySelector("dt").textContent.trim(), item.querySelector("dd").textContent.trim()])) })) };
}
async function gaGenerationTable(page) {
  const table = st(page, "sequence-ga-individuals");
  return {
    generation: Number(await st(page, "sequence-ga-generation-panel").getAttribute("data-generation")),
    range: clean(await st(page, "sequence-ga-generation-range").textContent()),
    caption: clean(await table.locator("caption").textContent()),
    headers: (await table.locator("thead th").allTextContents()).map(clean),
    rows: await table.locator("tbody tr").evaluateAll(items => items.map(item => {
      const t = value => (value ?? "").replace(/\s+/g, " ").trim();
      const cells = [...item.querySelectorAll(":scope > td")];
      const details = cells[2]?.querySelector("details") ?? null;
      return { position: Number(item.getAttribute("data-position")), key: item.getAttribute("data-key"),
        origin: item.getAttribute("data-origin"), evaluation: item.getAttribute("data-evaluation"),
        state: item.getAttribute("data-state"), cells: cells.map(cell => t(cell.textContent)),
        mutationSummary: t(details?.querySelector("summary")?.textContent),
        scoreCell: t(item.querySelector("[data-score-cell]")?.textContent), referenceRow: item.getAttribute("data-key") === "wild_type" };
    })),
  };
}
async function gaShowGeneration(page, index) {
  await st(page, `sequence-ga-generation-${index}`).click();
  await waitFor(page, async () => await st(page, "sequence-ga-generation-panel").getAttribute("data-generation") === String(index)
    ? true : null, `generation ${index} shown`, 15000);
  return gaGenerationTable(page);
}
function setMutations(setContent, key) {
  return key.split("-").map(Number).map(index => {
    const candidate = setContent.candidates.find(item => item.index === index);
    assert.ok(candidate, `candidate ${index} not in the set`);
    const position = setContent.positions.find(item => item.index === candidate.position_index);
    return { candidate_index: index, residue: position.residue, from: candidate.from, to: candidate.to };
  });
}
/** The opened summary equals the stored object and the stored rules (adapted from sequence-ga-flow.cjs resultEquals:
 * the reference row apart from the table with values only, every generation row; score = the stored M18 result's first
 * mode; min / max as values only; carried = previous generation's score order). */
async function gaResultEquals(page, ctx, header, detail, stored) {
  const { runsDir, run, setContent } = ctx;
  assert.equal(header.handle, detail.handle);
  assert.deepEqual(detail.summary, stored, "detail summary differs from the stored object");
  assert.equal(header.status, stored.status);
  assert.equal(header.stopReason, stored.stop_reason);
  assert.equal(STOP_STATUS[stored.stop_reason], stored.status, "stop reason outside the closed set or status mismatch");
  assert.ok(header.statusText.startsWith("서열 GA 상태: ") && header.statusText.includes(`(${stored.status}) · 종료 이유: `),
    header.statusText);
  assert.ok(header.statusText.endsWith(`(${stored.stop_reason})`), header.statusText);
  if (stored.stop_reason === "no_change") assert.ok(header.statusText.includes(NO_CHANGE_LABEL), header.statusText);
  const evaluated = stored.generations.flatMap(gen => gen.individuals).filter(item => item.origin !== "carried");
  assert.equal(stored.reused_count, evaluated.filter(item => item.evaluation === "reused").length);
  assert.equal(stored.new_evaluations_used, evaluated.filter(item => item.evaluation === "computed").length);
  const want = M23.statementIds(stored);
  assert.deepEqual(stored.limitations, want, "stored S sentence ids differ from the spec 4 rule");
  assert.deepEqual(header.statements, want.map(id => ({ id, text: S23[id] })), "shown S sentences differ from spec 4");
  const need = M23.needFor(stored.ga);
  assert.equal(stored.reserved_evaluations, need.reservedEvaluations);
  assert.equal(stored.reserved_units, need.units);
  assert.ok(stored.new_evaluations_used <= stored.reserved_evaluations);
  assert.equal(header.summaryLines["새 평가"], `${stored.new_evaluations_used}건 (예약 ${stored.reserved_evaluations}건 · ` +
    `${stored.reserved_units}단위)`);
  const ref = stored.reference;
  assert.equal(header.reference.inTable, false, "the reference row is inside the individuals table");
  assert.equal(header.reference.title, "야생형 기준(참고)");
  assert.equal(header.reference.state, ref.state);
  assert.equal(header.reference.evaluation, ref.evaluation);
  assert.equal(header.reference.lines["키"], "wild_type");
  assert.equal(header.reference.lines[SCORE_HEADER], ref.state === "scored" ? halfUp(ref.score, 1) : NULL_TEXT);
  if (ref.state === "scored") {
    const result = storedObject(runsDir, run, ref.result_handle);
    assert.equal(ref.score, result.modes[0].score_kcal_mol, "reference score is not the stored first mode");
    assert.deepEqual(result.inputs.receptor.source, { kind: "mutation_model", mutation_model: ref.model_handle,
      side: "wild_type_reference" });
  } else assert.equal(ref.score, null);
  assert.equal(header.tabs.length, stored.generations.length);
  const seen = new Map(), tables = [];
  let previous = null;
  let noScore = 0;
  for (const gen of stored.generations) {
    const table = await gaShowGeneration(page, gen.index);
    assert.equal(table.caption, SCORE_LABEL);
    assert.deepEqual(table.headers, ["자리", "개체 키", "변이 (구조 순서)", "출처", "부모", "평가", "상태", SCORE_HEADER, "이유", "상세"]);
    assert.equal(table.rows.length, gen.individuals.length);
    assert.ok(!table.rows.some(row => row.referenceRow), "the reference row is in the individuals table");
    assert.deepEqual(table.rows.map(row => row.position), M23.sortOracle(gen.individuals.map((item, position) =>
      ({ ...item, position })), null, null).map(row => row.position), "default order: rows without a score are not last");
    const scores = gen.individuals.filter(item => item.state === "scored").map(item => item.score);
    assert.equal(gen.min_score, scores.length ? Math.min(...scores) : null);
    assert.equal(gen.max_score, scores.length ? Math.max(...scores) : null);
    assert.equal(table.range, scores.length ? `점수 최솟값 ${halfUp(gen.min_score, 1)} · 점수 최댓값 ${halfUp(gen.max_score, 1)} ` +
      "(kcal/mol)" : "이 세대에 점수 있는 개체 없음");
    gen.individuals.forEach((item, position) => {
      const row = table.rows.find(entry => entry.position === position);
      assert.ok(row, `generation ${gen.index} position ${position} not shown`);
      assert.equal(row.key, item.key);
      assert.equal(row.origin, item.origin);
      assert.equal(row.state, item.state);
      assert.deepEqual(item.mutations, setMutations(setContent, item.key), `${item.key}: mutations differ from the set`);
      assert.equal(row.mutationSummary, item.mutations.map(mutText).join(", "));
      assert.ok(item.origin === "edit" ? row.cells[3].startsWith(`${ORIGIN_LABEL.edit}(`) : row.cells[3] === ORIGIN_LABEL[item.origin],
        row.cells[3]);
      for (const parent of item.parents ?? [])
        assert.ok(previous.individuals.some(entry => entry.key === parent && entry.state === "scored"),
          `${item.key}: parent ${parent} is not a scored individual of the previous generation`);
      if (item.origin === "carried") {
        const first = seen.get(item.key);
        assert.ok(first, "a carried individual not evaluated before");
        assert.equal(item.result_handle, first.result_handle);
      } else {
        assert.ok(!seen.has(item.key), `key ${item.key} evaluated twice in one run`);
        seen.set(item.key, item);
        assert.equal(row.cells[5], item.evaluation === "reused" ? "재사용" : "계산");
      }
      if (item.state === "scored") {
        const result = storedObject(runsDir, run, item.result_handle);
        assert.equal(item.score, result.modes[0].score_kcal_mol, "individual score is not the stored first mode");
        assert.deepEqual(result.inputs.receptor.source, { kind: "mutation_model", mutation_model: item.model_handle,
          side: "mutant" });
        assert.equal(result.inputs.mode, "free");
        assert.equal(row.scoreCell, halfUp(item.score, 1));
      } else {
        assert.equal(item.score, null);
        assert.equal(row.scoreCell, NULL_TEXT, "a row without a score shows a value");
        noScore++;
      }
    });
    tables.push({ generation: gen.index, complete: gen.complete, range: table.range, rows: gen.individuals.map(item =>
      ({ key: item.key, origin: item.origin, evaluation: item.evaluation, state: item.state, score: item.score })) });
    previous = gen;
  }
  return { status: stored.status, stopReason: stored.stop_reason, generationsDone: stored.generations_done,
    newEvaluations: stored.new_evaluations_used, reused: stored.reused_count, reserved: stored.reserved_units,
    reservedEvaluations: stored.reserved_evaluations, statements: want, noScore,
    reference: { state: ref.state, evaluation: ref.evaluation, score: ref.score }, tables };
}
async function gaIndividualView(page) {
  return st(page, "sequence-ga-individual").evaluate(el => {
    const t = value => (value ?? "").replace(/\s+/g, " ").trim();
    const q = id => el.querySelector(`[data-testid="${id}"]`);
    const lines = id => [...(q(id)?.querySelectorAll("li") ?? [])].map(li => t(li.textContent));
    const facts = node => Object.fromEntries([...(node?.querySelectorAll(":scope > div") ?? [])].map(item =>
      [t(item.querySelector("dt")?.textContent), t(item.querySelector("dd")?.textContent)]));
    const model = q("sequence-ga-detail-model");
    return { key: el.getAttribute("data-key"), state: el.getAttribute("data-state"),
      title: t(el.querySelector(".mw-mutation-title")?.textContent), model: !!model,
      structureLabel: t(model?.querySelector(".mw-eyebrow")?.textContent),
      energy: facts(q("sequence-ga-detail-energy")), energyStatements: lines("sequence-ga-detail-energy-statements"),
      counts: facts(q("sequence-ga-detail-counts")), limitations: lines("sequence-ga-detail-limitations"),
      m18Handle: q("sequence-ga-m18")?.getAttribute("data-docking-result-handle") ?? null,
      m18Limitations: lines("sequence-ga-m18-limitations") };
  });
}
/** 개체 상세: the stored model values of that one structure only (its own potentials with S5, counts, limitations)
 * and its M18 result (adapted from sequence-ga-flow.cjs individualMatches). */
function gaIndividualMatches(view, read, ctx, row) {
  const { runsDir, run } = ctx;
  assert.equal(view.key, row.key);
  assert.equal(read.is_reference, false);
  for (const key of ["state", "score", "model_handle", "result_handle"]) assert.equal(read[key], row[key], key);
  assert.equal(view.title, `개체 ${row.key}`);
  const model = storedObject(runsDir, run, row.model_handle);
  assert.equal(model.schema, "mutation_set_model@1");
  assert.deepEqual(Object.keys(model.structures), ["mutant"], "the individual's model holds another structure");
  const entry = model.structures.mutant;
  assert.ok(!DIFFERENCE_KEY.test(JSON.stringify(model)), "the model stores a value computed from two structures");
  assert.equal(view.structureLabel, "저장된 모델 값 · 변이 구조 (mutant)");
  assert.deepEqual(view.energy, { [`${ENERGY_LABEL} · 최소화 전`]: halfUp(entry.energy.before_kJ_mol, 2),
    [`${ENERGY_LABEL} · 최소화 후`]: halfUp(entry.energy.after_kJ_mol, 2) }, "potentials shown differ from the stored model");
  assert.deepEqual(view.energyStatements, [S23.S5], "the potentials do not carry S5 verbatim");
  assert.deepEqual(view.counts, { "중원자 수": String(entry.heavy_atoms), "pH 7.0에서 만든 수소 수": String(entry.added_hydrogens) });
  assert.deepEqual(view.limitations, model.limitations);
  assert.ok(model.limitations.every(text => MODEL_LIMITATIONS.includes(text)), "a model limitation is not a fixed sentence");
  if (row.result_handle) {
    const result = storedObject(runsDir, run, row.result_handle);
    assert.equal(view.m18Handle, row.result_handle);
    assert.deepEqual(view.m18Limitations, result.limitations);
    assert.equal(row.score, result.modes[0].score_kcal_mol);
  }
  // only this structure's potentials (before / after minimization), no second structure and no comparison row
  assert.equal(Object.keys(view.energy).length, 2);
  return { key: row.key, energy: entry.energy, heavyAtoms: entry.heavy_atoms, limitations: model.limitations.length,
    m18: view.m18Handle !== null };
}

// ------------------------------------------------------------------ JEV area of 지식·보고서 (copied from jev-flow.cjs)
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
async function jevChooseSource(page, kind, handle, rows) {
  await jt(page, `jev-kind-${kind}`).check();
  const radio = jev(page).locator(`input[data-testid="jev-source"]${attr("data-jev-source", handle)}`);
  await radio.waitFor({ timeout: 30000 });
  if (!(await radio.isChecked())) await radio.check();
  return waitFor(page, async () => {
    if (await jarea(page, "candidates").getAttribute("data-state") !== "ready") return null;
    if (await jt(page, "jev-candidates").count() !== 1) return null;
    if (await jt(page, "jev-candidates").getAttribute("data-kind") !== kind) return null;
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
    body: await jt(page, "jev-preview-body").textContent() };
}
/** Body identity (copied from jev-flow.cjs previewIdentity; the mutation alias rows name the candidate index). */
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
  for (const [index, item] of stored.selection.entries()) {
    const local = "candidate_id" in item ? item.candidate_id : String(item.candidate_index);
    assert.ok(shown.aliases[index].cells[1].includes(local), `alias table row ${item.alias}: ${shown.aliases[index].cells[1]}`);
  }
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
/** The catalytic_residue_database status of a stored projection's wire (copied from jev-flow.cjs catalyticStatus). */
function catalyticStatus(projection) {
  return projection.kind === "ligand" ? "not_available" : projection.wire.protection_checks.catalytic_residue_database;
}
/** The completed card = the stored proposal and nothing that orders or compares (adapted from jev-flow.cjs cardMatches:
 * the mutation notation, the served model as stored). */
function jevCardMatches(shown, record, choice, projection) {
  assert.equal(shown.choiceHandle, record.choice_handle);
  assert.equal(choice.scientific_result, false);
  assert.equal(choice.label, "JEV 판정(모델 선택)");
  assert.equal(shown.chosen, choice.answer.choice_alias);
  assert.equal(shown.alias, choice.answer.choice_alias);
  const aliases = projection.selection.map(item => item.alias);
  assert.ok(aliases.includes(choice.answer.choice_alias));
  const display = choice.answer.local_display;
  for (const value of [display.residue.resname, String(display.residue.seq_auth), `${display.from}→${display.to}`])
    assert.ok(shown.local.includes(value), `${value} not in ${shown.local}`);
  assert.equal(shown.confidence, choice.answer.confidence === null ? NOT_REPORTED_TEXT : M24.halfUp(choice.answer.confidence, 3));
  assert.equal(shown.model, choice.served_model);
  for (const key of ["input_tokens", "output_tokens", "external_tokens", "cost"]) {
    const value = choice.usage === null ? null : choice.usage[key];
    assert.equal(shown.usage[key], value === null ? UNKNOWN_USAGE_TEXT : String(value), `usage ${key}`);
  }
  if (choice.answer.probabilities !== null) {
    assert.equal(shown.reported, "true");
    assert.deepEqual(shown.probabilities.map(item => item.alias), aliases, "probabilities not in the sent order");
  } else assert.equal(shown.reported, "false");
  const limitations = M24.expectedLimitations("mutation", choice.arrival.late, catalyticStatus(projection));
  assert.deepEqual(shown.limitations, limitations);
  assert.equal(shown.lateAttr, String(choice.arrival.late));
  assert.deepEqual(shown.comparison, { graphics: 0, ariaSort: 0, styled: 0, attrs: 0 });
  assert.equal(shown.foldedBefore, true, "the per-candidate values were not folded when the card appeared");
  return { alias: shown.alias, confidence: shown.confidence, reported: shown.reported, late: choice.arrival.late,
    catalytic: catalyticStatus(projection), limitations: limitations.length };
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

// ------------------------------------------------------------------ JEV loop area, protein (copied from jev-loop-flow.cjs)
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
/** Protein setup: the two literal confirmations, cutoff, the 3D SDF, ligand-range box, free docking values, acks. */
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
async function loopRecordAttrs(page) {
  const node = lpt(page, "jev-loop-record");
  if (!(await node.count())) return null;
  return { loopId: await node.getAttribute("data-loop-id"), status: await node.getAttribute("data-status"),
    action: await node.getAttribute("data-action"), phase: await node.getAttribute("data-phase"),
    iteration: await node.getAttribute("data-iteration"), step: await node.getAttribute("data-step") };
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
function keysOf(value, out = []) {
  if (Array.isArray(value)) for (const item of value) keysOf(item, out);
  else if (value && typeof value === "object") for (const [key, item] of Object.entries(value)) { out.push(key); keysOf(item, out); }
  return out;
}
/** Body identity and the order oracle (copied from jev-loop-flow.cjs previewMatches, mutation branch). */
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
  const oracle = M25.oracleOrder(record, iteration, ordinal);
  assert.deepEqual(stored.selection, oracle.order.map(row => ({ alias: row.alias, ref: row.ref, state: row.state })),
    "stored selection differs from the independent sha256_order_v1 order");
  const body = JSON.parse(shown.body);
  assert.deepEqual(Object.keys(body).sort(), ["model", "provider", "questions", "state"]);
  assert.equal(body.model, REQUEST_MODEL);
  assert.deepEqual(body.provider, PROVIDER);
  assert.deepEqual(body.state, stored.wire, "body state differs from the stored wire");
  assert.equal(body.state.schema, "jev_loop_mutation_candidates@1");
  assert.equal(body.state.goal, record.goal);
  assert.equal(body.state.task, "choose_one_candidate");
  assert.ok(Object.keys(body.state).every(key => WIRE_TOP_MUTATION.includes(key)), Object.keys(body.state).join(","));
  assert.deepEqual(body.state.candidates.map(item => item.alias), oracle.order.map(row => row.alias));
  assert.deepEqual(body.state.computed, oracle.computed, "computed rows differ from the oracle (goal shape, raw score)");
  assert.equal(body.state.values_note.endsWith(MUTATION_EXPLOIT_SUFFIX), record.goal === "exploit");
  const question = body.questions.candidate_choice;
  assert.equal(question.instructions, M25.INSTRUCTIONS[`mutation|${record.goal}`], "instructions are not the spec 4.5 text");
  assert.deepEqual(Object.keys(question.criteria), oracle.criteria, "criteria are not the not-yet-computed aliases in order");
  assert.equal(shown.question, M25.INSTRUCTIONS[`mutation|${record.goal}`]);
  assert.equal(shown.order, `후보 순서·별칭: sha256_order_v1로 섞음 · 루프 seed ${record.loop_seed} · 바퀴 ${iteration} · ` +
    `전송 순번 ${ordinal}`);
  assert.deepEqual(shown.aliases.map(row => row.alias), oracle.order.map(row => row.alias));
  for (const [i, row] of oracle.order.entries()) {
    assert.ok(shown.aliases[i].cells[1].includes(String(row.ref)), `alias row ${row.alias}: ${shown.aliases[i].cells[1]}`);
    assert.equal(shown.aliases[i].cells[5], "전송하지 않음");
  }
  for (const forbidden of ["obj://", runId, record.loop_id, "/Users/", "handle", "loop_seed"])
    assert.ok(!shown.body.includes(forbidden), `body carries ${forbidden}`);
  assert.deepEqual(keysOf(body.state).filter(key => /coord|xyz|sequence|numbering|accession|path|smarts|seed/i.test(key)), []);
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
  const display = choice.answer.local_display;
  for (const value of [display.residue.resname, String(display.residue.seq_auth), `${display.from}→${display.to}`])
    assert.ok(shown.local.includes(value), `${value} not in ${shown.local}`);
  assert.equal(shown.model, choice.served_model);
  assert.equal(shown.foldedBefore, true, "the per-candidate values were not folded when the card appeared");
  assert.deepEqual(shown.limitations, M25.expectedLimitations("mutation", goal, { late: false }));
  assert.equal(shown.selectionAttr, "true");
  assert.deepEqual(shown.comparison, { graphics: 0, ariaSort: 0, attrs: 0 });
  if (shown.confirming !== null) assert.ok(shown.confirming.text.endsWith(CONFIRMING_TEXT), shown.confirming.text);
  return { alias: shown.chosen, position: shown.position, ref: choice.answer.local_ref.candidate_index };
}
async function loopPressCompute(page, run, loopId, button, log, timeout = 900000) {
  if (!(await lpt(page, "jev-loop-compute-confirm").isChecked())) await lpt(page, "jev-loop-compute-confirm").check();
  await waitFor(page, async () => await lpt(page, button).isEnabled() ? true : null, `${button} enabled`, 30000);
  const since = Date.now();
  await lpt(page, button).click();
  return waitApi(page, log, since, item => item.path === `/api/runs/${run}/jev_loops/${loopId}/compute`, `${button} answer`, timeout);
}
/** After a person's compute press: the run's first expensive-call approval when the server asks for it, then the
 * docking step; returns when the round has ended (copied from jev-loop-flow.cjs finishRound, protein branch). */
async function loopFinishRound(page, run, loopId, first, round, log) {
  let approval = null;
  if (first.json?.current?.job?.start_blocked === "approval_required") {
    await lpt(page, "jev-loop-approval-guide").waitFor({ timeout: 30000 });
    const since = Date.now();
    await lpt(page, "jev-loop-approve-first").click();
    const approved = await waitApi(page, log, since, item => item.path === `/api/runs/${run}/jobs/approve`, "approve", 30000);
    await waitFor(page, async () => await lpt(page, "jev-loop-job-start").isEnabled() ? true : null, "job start", 30000);
    const since2 = Date.now();
    await lpt(page, "jev-loop-job-start").click();
    const resumed = await waitApi(page, log, since2, item => item.path === `/api/runs/${run}/jev_loops/${loopId}/compute`,
      "job start answer", 900000);
    approval = { approve: approved.status, resumed: resumed.status };
  }
  await loopRecordWhen(page, item => item.action === "dock" || item.action === "end" || Number(item.iteration) > round,
    "modelled", 900000);
  let dock = null;
  if ((await loopRecordAttrs(page)).action === "dock") dock = await loopPressCompute(page, run, loopId, "jev-loop-dock", log);
  await loopRecordWhen(page, item => item.action === "end" || Number(item.iteration) > round, "round ended", 900000);
  return { approval, dock: dock ? { status: dock.status, request: dock.request } : null };
}
async function loopCandidateTable(page) {
  const table = lpt(page, "jev-loop-candidate-table");
  return { rows: await table.locator("tbody tr").evaluateAll(items => items.map(item => ({ ref: item.getAttribute("data-ref"),
    state: item.getAttribute("data-state"), evaluation: item.getAttribute("data-evaluation"),
    hasScore: item.getAttribute("data-has-score") === "true",
    score: item.querySelector("[data-score-cell]")?.textContent.trim() ?? null }))) };
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
/** What a person or assistive technology reads in the loop area outside the exempt subtrees (copied from
 * jev-loop-flow.cjs shownTexts / wordingCheck). */
async function loopWording(page) {
  const value = await lp(page).evaluate((node, selector) => {
    const exempt = [...node.querySelectorAll(selector)];
    const inExempt = item => exempt.some(root => root.contains(item));
    const attributes = [node, ...node.querySelectorAll("[title], [aria-label], [alt]")].filter(item => !inExempt(item))
      .flatMap(item => ["title", "aria-label", "alt"].map(name => item.getAttribute(name)).filter(text => text));
    return { text: node.innerText, attributes, exempt: exempt.flatMap(item => item.innerText.split("\n")) };
  }, LOOP_WORDING_EXEMPT);
  return M25.forbiddenWords([value.text, ...value.attributes].join("\n"), value.exempt);
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

// ------------------------------------------------------------------ report library (copied from endtoend-b-flow.cjs)
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
async function ensureRun(ctx, name) {
  const { page, rec, evidence, units } = ctx;
  const S = ctx.state;
  if (S.run) return S.run;
  S.run = await rec.step(`${name}-00`, "구조 분석: click 새 run", () => newRun(page), async run => { assert.match(run, /^run_/); return run; });
  evidence.run = S.run;
  units.setRun(S.run);
  return S.run;
}
/** The labeled synthetic phenol SDF imported once through the docking area of the ligand tab. */
async function ensurePhenol(ctx, name) {
  const { page, plan, rec } = ctx;
  const S = ctx.state;
  if (S.phenol) return S.phenol;
  S.phenol = await rec.step(`${name}-phenol`, "리간드 설계·탐색 docking area: choose the labeled synthetic phenol SDF as 리간드 " +
    "SDF (file chooser), 가져오기: one new ligand_sdf import whose stored bytes are the file's", () =>
    importLigandSdf(page, S.run, plan.inputs.phenol.path), async handle => {
    const meta = await readApi(page, `/runs/${S.run}/objects/meta?handle=${enc(handle)}`);
    assert.equal(meta.summary?.sha256, plan.inputs.phenol.sha256, "imported SDF bytes differ from the file");
    return handle;
  });
  return S.phenol;
}

async function flowC1(ctx) {
  const { page, plan, rec, evidence, input, artifacts } = ctx;
  const S = ctx.state;
  const runsDir = input["runs-dir"];
  await rec.part("C1", [], async () => {
    assert.ok(plan.c1, "the plan has no C1 expectation (no reaction set copy)");
    const P1 = plan.c1;
    const E = P1.expect;
    const run = await ensureRun(ctx, "C1");
    const loaded = await rec.step("C1-01", "구조 분석: choose public_1a30.cif (file chooser; its SHA-256 is the plan's), 구조 " +
      "불러오기, 전처리 (the screen's policies)", async () => {
      const up = await uploadLoad(page, plan.inputs.a30.path);
      return { ...up, prepared: (await prepareManual(page)).prepared };
    }, async value => {
      assert.equal(fileRecord(plan.inputs.a30.path).sha256, plan.inputs.a30.sha256, "the chosen file is not the plan's");
      assert.match(value.prepared, /\/prepared_structure\//);
      return { loaded: value.handle, prepared: value.prepared, structure: "1A30" };
    });
    S.a30 = loaded.prepared;
    const linked = await rec.step("C1-02", `지식·보고서 효소 반응 지식: the prepared 1A30, PDB ID ${P1.pdbId} confirmed, chain ` +
      `${P1.chainsPartial.join(",")} → 연결하기; again with chains ${P1.chainsAll.join(",")} → 연결하기: each stored result names ` +
      "the archived set and each chain's M-CSA coverage and row counts equal the ones counted from the set's entries " +
      "file and the structure file", async () => ({
      partial: await linkReaction(page, run, S.a30, P1.pdbId, P1.chainsPartial),
      all: await linkReaction(page, run, S.a30, P1.pdbId, P1.chainsAll) }), async value => {
      const facts = {};
      for (const [name, chains] of [["partial", P1.chainsPartial], ["all", P1.chainsAll]]) {
        const stored = storedObject(runsDir, run, value[name]);
        assert.equal(stored.snapshot_set.set_hash, E.setHash, "the result does not name the archived set");
        assert.deepEqual(stored.chains.map(chain => chain.chain_auth).sort(), [...chains].sort());
        for (const chain of stored.chains) {
          assert.equal(chain.mcsa.coverage, E.coverage[chain.chain_auth], `${name} ${chain.chain_auth} coverage`);
          assert.deepEqual(chain.mcsa.counts, E.rowCounts[chain.chain_auth], `${name} ${chain.chain_auth} row counts`);
        }
        facts[name] = { handle: value[name], chains: stored.chains.map(chain => [chain.chain_auth, chain.mcsa.coverage]) };
      }
      return facts;
    });
    S.rPartial = linked.partial.handle;
    S.rAll = linked.all.handle;
    const want = name => ({ status: E[name].status, reason: E[name].reason, covered: E[name].covered,
      uncovered: E[name].uncovered, counts: E[name].counts, catalytic: E.catalytic });
    const observed = (evidence.observed.C1 = { sets: {} });
    const made = {};
    for (const [name, annotation] of [["partial", S.rPartial], ["all", S.rAll]]) {
      made[name] = await rec.step(`C1-03-${name}`, `단백질 공학: the prepared 1A30, 직접 선택 ${P1.residues.map(r =>
        `${r.resname} ${r.chain}${r.seq}`).join(", ")}, the ${name === "partial" ? "chain-A" : "chains A,B"} result; 후보 ` +
        `만들기: catalytic check ${E[name].status}${E[name].reason ? ` (${E[name].reason})` : ""} as computed here (true only ` +
        "when every chain holding a position is covered); covered chains, row counts and each position's M-CSA rows and " +
        "cell equal the independent expectation", async () => {
        if (name === "partial") {
          await openReady(page);
          await chooseStructure(page, S.a30);
          await setCheck(page, "mutation-source-user", true);
          await setPicker(page, "user", P1.residues);
          await setPicker(page, "release", []);
        }
        await testId(page, "mutation-catalytic-annotation").selectOption(annotation);
        return create(page, run);
      }, async value => {
        assert.equal(value.ok, true, JSON.stringify(value.body).slice(0, 400));
        assert.equal(value.args.catalytic_annotation, annotation);
        const verified = await verifyCatalyticSet(page, run, value.handle, want(name));
        const found = await m20Wording(page);
        assert.deepEqual(found, [], `M20 wording: ${found.join(", ")}`);
        observed.sets[name] = { status: verified.status, reason: verified.reason, covered: verified.covered,
          uncovered: verified.uncovered, counts: verified.counts };
        if (name === "all") {
          observed.catalytic = Object.fromEntries(Object.entries(verified.catalytic).map(([key, rows]) => [key, rows ?? []]));
          observed.protected = verified.protected;
          for (const key of verified.protected) {
            const cell = verified.cells.find(item => item.residue === key);
            assert.ok(cell && cell.reasons.split(",").includes("catalytic_residue") && cell.status === "excluded",
              `${key}: the catalytic reason is not shown on the excluded row`);
          }
        } else {
          for (const cell of verified.cells.filter(item => !E.partial.covered.includes(item.residue.split(" ")[1].split(":")[0])))
            x5(evidence, cell.text.startsWith(NULL_TEXT) && !/\d/.test(cell.text), `C1 chain-A-only set: position ` +
              `${cell.residue} of the uncovered chain shows "${cell.text}" (not checked, no number)`);
        }
        return { handle: value.handle, status: verified.status, reason: verified.reason, covered: verified.covered,
          protected: verified.protected };
      });
    }
    await rec.step("C1-04-release", `Pick ${P1.release.resname} ${P1.release.chain}:${P1.release.seq} in 해제 목록, 후보 만들기 ` +
      "(chains A,B result): that position is a candidate, its M-CSA rows stay and the cell says 해제됨 (release per residue)",
    async () => {
      await setPicker(page, "release", [P1.release]);
      return create(page, run);
    }, async value => {
      assert.equal(value.ok, true, JSON.stringify(value.body).slice(0, 400));
      const verified = await verifyCatalyticSet(page, run, value.handle, want("all"));
      const key = `${P1.release.resname} ${P1.release.chain}:${P1.release.seq}`;
      const row = verified.positions.find(item => rkey(item.residue) === key);
      assert.ok(row && row.protection.released === true && row.status === "candidate" && row.protection.catalytic.length > 0,
        JSON.stringify(row?.protection));
      assert.ok(row.protection.reasons.includes("catalytic_residue"));
      const cell = verified.cells.find(item => item.residue === key);
      assert.ok(cell.text.endsWith("· 해제됨") && cell.released === "true", cell.text);
      const effects = (await storedSet(page, run, value.handle)).result.released_residues.map(item => [rkey(item.residue), item.effect]);
      assert.deepEqual(effects, [[key, "released"]]);
      observed.release = { residue: key, status: row.status, released: true,
        catalytic: row.protection.catalytic.map(item => [item.mcsa_id, item.residue_index, item.is_reference]) };
      return { handle: value.handle, release: observed.release };
    });
    await rec.step("C1-05-report", "Open the chains A,B set, 보고서 만들기: saved (201) as mutation_candidates_markdown@2 with " +
      "one reaction reference set table copied from the cited result (its set hash = the archived set's); the library " +
      "shows 변이 후보 보고서 with the stored Markdown, the stored limitation sentences and the set table", async () => {
      await openReady(page);
      const report = await m20Report(page, run, made.all.handle);
      noteReport(evidence, "C1", "mutation_candidates", report.status, report.handle);
      const opened = await libraryOpen(page, report.handle);
      const saved = await readApi(page, `/runs/${run}/reports/selected?handle=${enc(report.handle)}`);
      await keepTabText(page, evidence, artifacts, "knowledge@C1", "knowledge");
      return { report, opened: { kind: opened.kind, text: opened.text }, saved };
    }, async value => {
      assert.equal(value.report.status, 201);
      assert.equal(value.report.done, value.report.handle);
      const manifest = value.saved.manifest;
      assert.equal(manifest.analysis_type, "mutation_candidates");
      assert.equal(manifest.result_handle, made.all.handle);
      assert.equal(manifest.render_version, E.reportRender);
      const sets = manifest.reference_snapshot_sets ?? [];
      const result = storedObject(runsDir, run, S.rAll);
      assert.equal(sets.length, 1, "the report does not carry exactly the cited reaction set");
      assert.equal(sets[0].copied_from, S.rAll);
      assert.deepEqual(sets[0].snapshot_set, result.snapshot_set, "the table is not the cited result's snapshot set");
      assert.equal(value.opened.kind, "변이 후보 보고서");
      assert.equal(value.opened.text, value.saved.markdown);
      assert.ok(value.saved.markdown.includes(REACTION_SET_HEADING), "no reaction set table in the Markdown");
      assert.ok(value.saved.markdown.includes(E.setHash), "the table does not name the set hash");
      const limitations = storedObject(runsDir, run, made.all.handle).limitations;
      for (const sentence of limitations) assert.ok(value.saved.markdown.includes(sentence), "the report lacks a limitation");
      observed.report = { renderVersion: manifest.render_version, setHashes: sets.map(item => item.snapshot_set.set_hash),
        setSchemas: sets.map(item => item.set_schema), handle: value.report.handle };
      return { ...observed.report, markdown: textDigest(value.saved.markdown) };
    });
    await keepTabText(page, evidence, artifacts, "protein@C1", "protein");
  });
}

async function flowC2(ctx, name) {
  const { page, plan, rec, evidence, units, input, artifacts } = ctx;
  const S = ctx.state;
  const runsDir = input["runs-dir"];
  const P2 = plan.c2;
  const E = P2.expect;
  await rec.part(name, [], async () => {
    const run = await ensureRun(ctx, name);
    const observed = (evidence.observed[name] = {});
    const loaded = await rec.step(`${name}-01`, "구조 분석: choose public_1ubq.cif (file chooser; its SHA-256 is the plan's), 구조 " +
      "불러오기, 물 = 유지 (keep_all), 전처리 (a structure other than C1's 1A30)", async () => {
      const up = await uploadLoad(page, plan.inputs.ubq.path);
      const prepared = await prepareManual(page, P2.waters);
      return { ...up, prepared };
    }, async value => {
      assert.equal(fileRecord(plan.inputs.ubq.path).sha256, plan.inputs.ubq.sha256, "the chosen file is not the plan's");
      assert.equal(value.prepared.args.waters, P2.waters);
      assert.notEqual(value.prepared.prepared, S.a30 ?? null, "C2 reuses the C1 structure");
      return { loaded: value.handle, prepared: value.prepared.prepared, structure: "1UBQ" };
    });
    S.ubq = loaded.prepared;
    const section = openmmSection(page);
    await rec.step(`${name}-02`, "OpenMM 단백질 전용 최소화: 단백질 입력·제외 항목 확인: the preflight passes with the protein " +
      "heavy atoms and the excluded waters counted here from the mmCIF file", async () => {
      await section.getByRole("button", { name: "단백질 입력·제외 항목 확인" }).click();
      await section.getByRole("region", { name: "OpenMM 제외 성분" }).waitFor({ timeout: 60000 });
      const text = await section.innerText();
      const found = /단백질 중원자 (\d+)개; 제외 성분 (\d+)개\./.exec(text);
      return { heavy: found ? Number(found[1]) : null, excluded: found ? Number(found[2]) : null,
        rows: await section.getByRole("region", { name: "OpenMM 제외 성분" }).locator("p").count() };
    }, async value => {
      assert.equal(value.heavy, E.proteinHeavyAtoms, "protein heavy atoms differ from the file count");
      assert.equal(value.excluded, E.waters, "excluded components differ from the file's waters");
      assert.equal(value.rows, E.waters);
      observed.m7 = { heavyAtoms: value.heavy, excluded: value.excluded };
      return observed.m7;
    });
    const m7 = await rec.step(`${name}-03`, "Tick protein_only and rebuild_pH7, OpenMM 작업 제출, 작업 시작; the run's first " +
      "expensive call asks for 고비용 계산 승인 후 시작 (a person's click); the real OpenMM minimization finishes with one unit",
    async () => {
      await section.getByLabel(/protein_only 선택과 제외 항목/).check();
      await section.getByLabel(/기존 수소 제거 후 pH 7.0/).check();
      await section.getByRole("button", { name: "OpenMM 작업 제출" }).click();
      await section.getByText(/상태 queued/).waitFor({ timeout: 30000 });
      const jobId = await section.getByLabel("작업").inputValue();
      const entry = await units.before("C2-m7");
      await section.getByRole("button", { name: "작업 시작" }).click();
      const approve = section.getByRole("button", { name: "고비용 계산 승인 후 시작" });
      await approve.or(section.getByText(/상태 (running|done)/)).first().waitFor({ timeout: 60000 });
      const approvalSeen = await approve.isVisible().catch(() => false);
      if (approvalSeen) await approve.click();
      await section.getByText(/상태 done/).waitFor({ timeout: 600000 });
      await units.after(entry);
      const job = await readApi(page, `/runs/${run}/jobs/${enc(jobId)}`);
      const payload = await readApi(page, `/runs/${run}/openmm_minimization?handle=${enc(job.output_handles[0])}`);
      return { jobId, job, approvalSeen, entry, result: payload.result, handle: job.output_handles[0] };
    }, async value => {
      assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
      assert.equal(value.approvalSeen, true, "the run's first expensive call did not ask for approval");
      assert.equal(value.result.schema, "openmm_protein_minimization@1");
      assert.equal(value.result.structure, S.ubq);
      for (const key of ["before_kJ_mol", "after_kJ_mol"]) assert.ok(Number.isFinite(value.result[key]), key);
      observed.m7.approvalSeen = value.approvalSeen;
      return { job: value.jobId, handle: value.handle, units: value.entry.usedUnits };
    });
    await rec.step(`${name}-04`, "OpenMM 방법 보고서 만들기: saved (201) as openmm_protein_minimize for this result; the " +
      "preview shows the stored Markdown (the viewer consent is not touched afterwards)", async () => {
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 120000 });
      await section.getByRole("button", { name: "OpenMM 방법 보고서 만들기" }).click();
      const response = await posted;
      const body = await response.json();
      noteReport(evidence, name, "openmm_protein_minimize", response.status(), body.handle);
      await section.getByLabel("저장된 OpenMM 보고서 미리보기").waitFor({ timeout: 60000 });
      const preview = await section.getByLabel("저장된 OpenMM 보고서 미리보기").textContent();
      await keepTabText(page, evidence, artifacts, `structure@${name}`, "structure");
      return { status: response.status(), handle: body.handle, preview,
        saved: await readApi(page, `/runs/${run}/reports/selected?handle=${enc(body.handle)}`) };
    }, async value => {
      assert.equal(value.status, 201);
      assert.equal(value.saved.manifest.analysis_type, "openmm_protein_minimize");
      assert.equal(value.saved.manifest.result_handle, m7.handle);
      assert.equal(value.preview, value.saved.markdown);
      return { handle: value.handle, markdown: textDigest(value.saved.markdown) };
    });
    const set = await rec.step(`${name}-05`, "단백질 공학: the prepared 1UBQ, 직접 선택 I3 K6 I44 G76, 보호 I3, 허용 잔기 A W, 효소 " +
      "반응 지식 결과 없음; 후보 만들기: the stored candidates are the ones counted here (each unprotected position × each " +
      "allowed residue other than its own); catalytic check not_checked (annotation_not_given), shown without a number",
    async () => {
      await openReady(page);
      await chooseStructure(page, S.ubq);
      await setCheck(page, "mutation-source-user", true);
      await setPicker(page, "user", P2.residues.map(([resname, seq]) => ({ resname, chain: "A", seq })));
      await setPicker(page, "protect", P2.protect.map(([resname, seq]) => ({ resname, chain: "A", seq })));
      await setPicker(page, "release", []);
      await testId(page, "mutation-allowed-none").click();
      for (const code of P2.allowed)
        await testId(page, "mutation-allowed").getByRole("checkbox", { name: `허용 잔기 ${code}`, exact: true }).check();
      const select = testId(page, "mutation-catalytic-annotation");
      if (await select.count() && await select.inputValue() !== "") await select.selectOption("");
      return create(page, run);
    }, async value => {
      assert.equal(value.ok, true, JSON.stringify(value.body).slice(0, 400));
      assert.equal(value.args.structure, S.ubq);
      assert.equal(value.args.catalytic_annotation ?? null, null);
      const candidates = await storedCandidates(page, run, value.handle);
      const positions = await storedPositions(page, run, value.handle);
      const verified = await verifyCatalyticSet(page, run, value.handle, { status: "not_checked", reason: "annotation_not_given" });
      for (const cell of verified.cells)
        x5(evidence, cell.text.startsWith(NULL_TEXT) && !/\d/.test(cell.text), `${name} 1UBQ set: position ${cell.residue} ` +
          `catalytic cell "${cell.text}" (not checked, no number)`);
      const catalyticLine = /M-CSA 촉매 잔기 주석 — \([^]*?세지 않음\)/.exec(verified.reasonCounts)?.[0] ?? "";
      x5(evidence, catalyticLine !== "" && !/주석 \d/.test(verified.reasonCounts), `${name} 1UBQ set: the catalytic ` +
        `exclusion count reads "${catalyticLine}" (not counted, not 0)`);
      const found = await m20Wording(page);
      assert.deepEqual(found, [], `M20 wording: ${found.join(", ")}`);
      observed.set = { positions: positions.length, candidates: candidates.map(candidateText) };
      assert.deepEqual(observed.set.candidates, E.candidates.map(item => `${item.residue} ${item.from}→${item.to}`));
      S.setContent = storedObject(runsDir, run, value.handle);
      return { handle: value.handle, ...observed.set, catalytic: verified.status };
    });
    S.set = set.handle;
    S.candidates = await storedCandidates(page, run, S.set);
    await rec.step(`${name}-06`, "보고서 만들기 for the 1UBQ set: saved (201); it cites no reference value, so its format is " +
      "mutation_candidates_markdown@1 and carries no set table", async () => {
      const report = await m20Report(page, run, S.set);
      noteReport(evidence, name, "mutation_candidates", report.status, report.handle);
      return { report, saved: await readApi(page, `/runs/${run}/reports/selected?handle=${enc(report.handle)}`) };
    }, async value => {
      assert.equal(value.report.status, 201);
      assert.equal(value.saved.manifest.render_version, "mutation_candidates_markdown@1");
      assert.ok(!("reference_snapshot_sets" in value.saved.manifest));
      assert.ok(!value.saved.markdown.includes(REACTION_SET_HEADING));
      return { handle: value.report.handle, renderVersion: value.saved.manifest.render_version };
    });
    const target = E.modelTarget;
    const candidate = S.candidates.find(row => resShort(row.residue) === target.residue && row.from === target.from &&
      row.to === target.to);
    assert.ok(candidate, `no ${target.residue} ${target.from}→${target.to} candidate in the set`);
    const job = await rec.step(`${name}-07`, `변이 구조 모델링 on candidate ${target.residue} ${target.from}→${target.to}; seed ` +
      `${P2.model.seed}, cutoff ${P2.model.cutoff} Å, both confirmations; 모델링 작업 제출 → (no second approval) 작업 시작: the ` +
      "real PDBFixer + OpenMM job finishes with one unit", async () => {
      await panel(page).locator(`[data-testid="mutation-candidate-model"]${attr("data-candidate-index", candidate.index)}`).click();
      await mt(page, "mutation-model-candidate").waitFor({ timeout: 15000 });
      await mt(page, "mutation-model-seed").fill(P2.model.seed);
      await mt(page, "mutation-model-confirm-selection").check();
      await mt(page, "mutation-model-confirm-hydrogen").check();
      await mt(page, "mutation-model-cutoff").fill(P2.model.cutoff);
      await mt(page, "mutation-model-timeout").fill(P2.model.timeout);
      const entry = await units.before("C2-m21");
      const value = await runModelJob(page, run);
      await units.after(entry);
      return { ...value, entry };
    }, async value => {
      assert.equal(value.request.protocol_id, MODEL_PROTOCOL);
      assert.deepEqual(value.request.args, { candidate_set: S.set, candidate_index: candidate.index, seed: Number(P2.model.seed),
        selection_policy: "protein_only", hydrogen_policy: "rebuild_pH7", contact_cutoff_A: Number(P2.model.cutoff) });
      assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
      assert.equal(value.approved, false, "the run's approval was asked again");
      const handle = value.job.artifacts?.mutation_model;
      assert.match(handle ?? "", /\/mutation_model\//);
      return { handle, jobId: value.jobId, units: value.entry.usedUnits };
    });
    S.model = job.handle;
    const stored = storedObject(runsDir, run, S.model);
    assert.equal(stored.schema, "mutation_model@1");
    let limitationsSeen = [];
    await rec.step(`${name}-08`, "Open the model: the side-by-side table (one stored value per structure: the two " +
      `${ENERGY_LABEL} rows, SASA, contacts, atoms) equals the stored object; no column or stored field computed from both ` +
      "structures; HIS/CYS variant names that differ between the structures as stored; L1–L7 as stored; the panel has no " +
      "comparison wording", async () => {
      await waitListReady(page);
      await openModel(page, S.model);
      return { api: await readApi(page, modelPath(run, S.model)), table: await sideBySide(page),
        protonation: await mt(page, "mutation-model-protonation-none").count()
          ? { none: true, count: await mt(page, "mutation-model-protonation-none").getAttribute("data-count") }
          : { none: false, rows: await mt(page, "mutation-model-protonation").locator("tbody tr").evaluateAll(items =>
            items.map(tr => [...tr.querySelectorAll("td")].map(td => td.textContent.trim()))) },
        limitations: (await mt(page, "mutation-model-limitations").locator("[data-limitation]").allTextContents()).map(text => text.trim()) };
    }, async value => {
      const result = value.api.result;
      assert.equal(value.api.schema, "mutation_model_detail@1");
      for (const side of SIDES) {
        assert.deepEqual(result.structures[side].energy, stored.structures[side].energy, `${side} energy API = stored`);
        assert.deepEqual(result.structures[side].sasa, stored.structures[side].sasa, `${side} sasa API = stored`);
        assert.equal(result.structures[side].energy.unit, "kJ/mol");
      }
      assert.deepEqual(result.comparison, stored.comparison);
      const differenceKeys = [JSON.stringify(stored), JSON.stringify(result)].flatMap(text => text.match(new RegExp(DIFFERENCE_KEY.source,
        "gi")) ?? []);
      assert.deepEqual(differenceKeys, [], "a stored value computed from both structures");
      assert.deepEqual([result.candidate.residue.resname, result.candidate.from, result.candidate.to],
        [target.residue.split(" ")[0], target.from, target.to]);
      const want = expectedSideBySide(result);
      assert.deepEqual(value.table.headers, ["항목", SIDE_LABEL.wild_type_reference, SIDE_LABEL.mutant]);
      assert.deepEqual(value.table.rows.map(row => row.key), Object.keys(want));
      let sideBySideMismatches = 0;
      for (const row of value.table.rows) {
        assert.equal(row.cellCount, 3, `${row.key}: extra column`);
        if (SIDES.some(side => row.values[side] !== want[row.key][side])) sideBySideMismatches++;
        assert.deepEqual(row.styles.wild_type_reference, row.styles.mutant, `${row.key}: the two cells differ in style`);
      }
      assert.equal(sideBySideMismatches, 0, "a side-by-side cell differs from the stored value of its structure");
      const energyRows = value.table.rows.filter(row => row.key.startsWith("energy_"));
      assert.deepEqual(energyRows.map(row => row.label), [`${ENERGY_LABEL} · 최소화 전`, `${ENERGY_LABEL} · 최소화 후`]);
      assert.ok(!value.table.rows.some(row => ARROWS.test(Object.values(row.values).join(" "))), "an arrow in the table");
      if (stored.comparison.protonation_difference_count === 0) {
        assert.deepEqual(value.protonation, { none: true, count: "0" });
      } else {
        assert.deepEqual(value.protonation.rows.map(cells => cells[0]), stored.protonation_differences.map(item => resShort(item.residue)));
      }
      const limitations = M21.expectedLimitations(result);
      assert.deepEqual(stored.limitations, limitations);
      assert.deepEqual(value.limitations, limitations);
      limitationsSeen = limitations;
      const wording = await modelWording(page, limitationsSeen);
      assert.deepEqual(wording.found, [], JSON.stringify(wording.found));
      observed.model = { target: { residue: resShort(result.candidate.residue), from: result.candidate.from, to: result.candidate.to },
        energyUnit: result.structures.mutant.energy.unit, sideBySideMismatches, differenceKeys,
        energies: Object.fromEntries(SIDES.map(side => [side, { before: result.structures[side].energy.before_kJ_mol,
          after: result.structures[side].energy.after_kJ_mol }])),
        sasa: Object.fromEntries(SIDES.map(side => [side, result.structures[side].sasa.value_A2])),
        contacts: Object.fromEntries(SIDES.map(side => [side, result.structures[side].contacts.count])),
        hisCys: { protonationDifferences: stored.comparison.protonation_difference_count,
          variants: Object.fromEntries(SIDES.map(side => [side, (stored.structures[side].protonation_variants ?? [])
            .map(item => `${resShort(item.residue)}:${item.variant}`)])) },
        limitations: limitations.length };
      return observed.model;
    });
    await rec.step(`${name}-09`, "Contact table: 야생형 기준 page 1, then 변이형 page 1: every page equals the API page and the " +
      "stored rows (7 partner fields, atom names, distance)", async () => {
      const pages = [await checkContacts(page, run, S.model, stored, "wild_type_reference", 1)];
      await mt(page, "mutation-model-contacts-side-mutant").check();
      pages.push(await checkContacts(page, run, S.model, stored, "mutant", 1));
      return pages;
    }, async pages => {
      const mismatches = pages.reduce((sum, item) => sum + item.mismatches, 0);
      observed.model.contactMismatches = mismatches;
      assert.equal(mismatches, 0, "contacts shown differ from the stored rows");
      return pages;
    });
    await rec.step(`${name}-10`, "보고서 만들기 for the model: saved (201) as mutation_model; the library shows the stored " +
      "Markdown with L1–L7 as stored, no docking value and no comparison wording outside the fixed sentences", async () => {
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
      await mt(page, "mutation-model-report").click();
      const response = await posted;
      const body = await response.json();
      noteReport(evidence, name, "mutation_model", response.status(), body.handle);
      await mt(page, "mutation-model-report-done").waitFor({ timeout: 30000 });
      await keepTabText(page, evidence, artifacts, `protein@${name}`, "protein");
      const opened = await libraryOpen(page, body.handle);
      return { status: response.status(), handle: body.handle, opened: { kind: opened.kind, text: opened.text },
        saved: await readApi(page, `/runs/${run}/reports/selected?handle=${enc(body.handle)}`) };
    }, async value => {
      assert.equal(value.status, 201);
      const manifest = value.saved.manifest;
      assert.equal(manifest.analysis_type, "mutation_model");
      assert.equal(manifest.result_handle, S.model);
      assert.equal(value.opened.text, value.saved.markdown);
      for (const sentence of limitationsSeen) assert.ok(value.saved.markdown.includes(sentence), "the report lacks a limitation");
      assert.ok(!value.saved.markdown.includes("qvina"), "the model report cites a docking value");
      // no value computed from the two structures: every potential and SASA claim is one structure's stored field
      // (the rendered value = that field), and no report line puts a number beside a difference / change word
      const valueClaims = manifest.claims.filter(claim => ["kJ/mol", "A2"].includes(claim.unit));
      assert.equal(valueClaims.length, 6, "two potentials and one SASA per structure");
      for (const claim of valueClaims) {
        const found = /^structures\.(wild_type_reference|mutant)\.(energy\.(?:before|after)_kJ_mol|sasa\.value_A2)$/.exec(claim.field_path);
        assert.ok(found, `a value claim outside one structure's stored fields: ${claim.field_path}`);
        const [, side, field] = found;
        const storedValue = field.split(".").reduce((item, key) => item[key], stored.structures[side]);
        assert.equal(claim.rendered_value, halfUp(storedValue, 2), `${claim.field_path} rendered value`);
      }
      const numbered = value.saved.markdown.split("\n").map(line => line.trim())
        .filter(line => line && !Object.values(L21).includes(line) && /차이|변화량|Δ|delta|differen/i.test(line) && /\d/.test(line));
      assert.deepEqual(numbered, [], "a report line puts a number beside a difference or change word");
      assert.ok(!DIFFERENCE_KEY.test(JSON.stringify(manifest)), "the report stores a value computed from both structures");
      observed.model.reportValueClaims = valueClaims.length;
      return { handle: value.handle, kind: value.opened.kind, markdown: textDigest(value.saved.markdown) };
    });
    observed.units = evidence.units.filter(item => ["C2-m7", "C2-m21"].includes(item.label)).map(item => item.usedUnits);
  });
}

async function flowC3(ctx) {
  const { page, plan, rec, evidence, units, input, artifacts } = ctx;
  const S = ctx.state;
  const runsDir = input["runs-dir"];
  await rec.part("C3", ["C2"], async () => {
    const run = S.run;
    await ensurePhenol(ctx, "C3");
    const submitted = await rec.step("C3-01", "단백질 공학: open the model, read the docking inputs again, 3D SDF = the phenol " +
      "import, 리간드 범위 + margin, the docking values, the acknowledgements and the 2-unit confirmation; 같은 조건 도킹 " +
      "제출 once: two qvina_dock_v1 jobs (wild-type reference and mutant receptors of this model), the same arguments " +
      "but the side", async () => {
      await enterTab(page, TAB.protein);
      await mpanel(page).waitFor({ timeout: 15000 });
      await waitListReady(page);
      await openModel(page, S.model);
      await mt(page, "mutation-model-pair-prereq-refresh").click();
      await mpanel(page).locator('label[data-pair-ligand-source="sdf"] input').check();
      await waitFor(page, async () => await mt(page, "mutation-model-pair-sdf").locator(`option${attr("value", S.phenol)}`).count()
        ? true : null, "phenol SDF offered", 30000);
      await fillPair(page, S.phenol, plan.docking);
      const entry = await units.before("C3-pair");
      return { ...await submitPair(page, run), entry };
    }, async value => {
      assert.equal(value.responses.length, 2);
      assert.deepEqual(value.responses.map(item => item.request.args.receptor_source.side), SIDES);
      for (const item of value.responses) {
        assert.equal(item.status, 200);
        assert.equal(item.request.args.receptor_source.mutation_model, S.model);
      }
      const strip = args => JSON.stringify({ ...args, receptor_source: { ...args.receptor_source, side: null } });
      assert.equal(strip(value.responses[0].request.args), strip(value.responses[1].request.args));
      assert.deepEqual(value.responses[0].request.args.box, { source: "ligand_range", margin_A: Number(plan.docking.margin) });
      S.pairEntry = value.entry;
      return { jobs: value.responses.map(item => item.body.job_id) };
    });
    await rec.step("C3-02", "Approve / continue through the screen's own buttons until both real qvina jobs end: two units",
      () => drivePair(page, submitted.jobs), async value => {
        for (const side of SIDES) assert.equal(value.jobs[side].status, "done", JSON.stringify(value.jobs));
        await units.after(S.pairEntry);
        return { actions: value.actions, units: S.pairEntry.usedUnits };
      });
    await rec.step("C3-03", "Pair table: one row for this condition, both scores side by side, each = the first mode of its " +
      "stored M18 result; the header names the qvina score; no difference column, same cell style on both sides", async () => {
      const api = await readApi(page, modelPath(run, S.model, "/docking_pairs"));
      const pair = api.pairs.find(item => SIDES.every((side, i) => item.sides[side].job_id === submitted.jobs[i]));
      assert.ok(pair, `no pair for jobs ${submitted.jobs}`);
      const view = await waitFor(page, async () => {
        const value = await pairView(page);
        const row = value?.rows.find(item => item.index === pair.index);
        return row && SIDES.every(side => row.sides[side]?.hasScore === "true") ? value : null;
      }, "pair row with both scores", 60000);
      return { api, pair, view };
    }, async value => {
      const { api, pair, view } = value;
      assert.equal(api.score_label, SCORE_LABEL);
      assert.equal(pair.both_published, true);
      assert.deepEqual(view.headers, ["짝", "도킹 조건", `${SIDE_LABEL.wild_type_reference} · ${SCORE_LABEL}`, `${SIDE_LABEL.mutant} · ${SCORE_LABEL}`]);
      const row = view.rows.find(item => item.index === pair.index);
      assert.equal(row.cellCount, 4, "extra column in the pair table");
      let scoresFirstMode = true;
      const scores = {};
      for (const side of SIDES) {
        const result = storedObject(runsDir, run, pair.sides[side].result_handle);
        assert.deepEqual(result.inputs.receptor.source, { kind: "mutation_model", mutation_model: S.model, side });
        const first = result.modes[0];
        if (pair.sides[side].score_kcal_mol !== first.score_kcal_mol) scoresFirstMode = false;
        if (row.sides[side].text !== `${halfUp(first.score_kcal_mol, 1)} · 모드 ${pair.sides[side].score_mode}(엔진 출력 순서)`)
          scoresFirstMode = false;
        scores[side] = first.score_kcal_mol;
      }
      for (const key of ["color", "background", "weight", "className", "inline"])
        assert.equal(row.sides.wild_type_reference[key], row.sides.mutant[key], `pair cells differ in ${key}`);
      assert.ok(!DIFFERENCE_KEY.test(JSON.stringify(pair)), "the pair stores a value computed from both sides");
      const wording = await modelWording(page, []);
      assert.deepEqual(wording.found, [], JSON.stringify(wording.found));
      assert.ok(scoresFirstMode, "a pair score is not the first mode of its stored result");
      evidence.observed.C3 = { scoresFirstMode, units: S.pairEntry.usedUnits, pair: pair.index,
        results: SIDES.map(side => pair.sides[side].result_handle) };
      await keepTabText(page, evidence, artifacts, "protein@C3", "protein");
      return { ...evidence.observed.C3, scores };
    });
  });
}

async function flowC5(ctx) {
  const { page, plan, rec, evidence, input, artifacts } = ctx;
  const S = ctx.state;
  const runsDir = input["runs-dir"];
  await rec.part("C5", ["C2"], async () => {
    const run = S.run;
    const built = await rec.step("C5-01", "지식·보고서 JEV area: switch the run's science consent on; 변이 후보 and the 1UBQ set; " +
      `check its first ${plan.send.pick} candidates; 보낼 내용 만들기; open the exact body: its text = the server preview, its ` +
      "SHA-256 and bytes computed here = shown = the stored projection", async () => {
      await openKnowledge(page);
      await jevSetConsent(page, run, true);
      const rows = await jevChooseSource(page, "mutation", S.set, S.candidates.length);
      const keys = rows.slice(0, plan.send.pick).map(row => row.key);
      for (const key of keys) await jev(page).locator(`input[data-testid="jev-candidate"]${attr("data-jev-candidate", key)}`).check();
      const made = await jevBuild(page, run);
      await jt(page, "jev-preview-body-details").locator("summary").click();
      const shown = await jevPreviewShown(page);
      return { keys, made, shown, stored: storedObject(runsDir, run, made.handle) };
    }, async value => {
      assert.deepEqual(value.shown.blocked, []);
      const identity = jevPreviewIdentity(value.shown, value.made, value.stored);
      assert.ok(value.keys.length >= 2);
      return { ...identity, keys: value.keys, handle: value.made.handle, previewSha256: value.made.preview.body_sha256,
        body: value.shown.body };
    });
    const sent = await rec.step("C5-02", "Check the confirmation and click 이 내용을 JEV로 보냅니다 (fixture good): completed; the " +
      "card is the stored proposal, labeled JEV 판정(모델 선택), with the M24 sentences of a v2 set whose catalytic check " +
      "was not performed; the bytes the transport received = the preview = the prepared audit; the M24 wording check of " +
      "the area finds nothing", async () => {
      const result = await jevConfirmAndSend(page, run, input.control, plan.send.script);
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
        assert.equal(call.script, plan.send.script);
        assert.equal(call.bodySha256, built.previewSha256, "transport bytes differ from the preview");
        assert.equal(call.authorizationIsSentinel, true);
        transport = { sha256: call.bodySha256, bytes: call.bodyBytes };
      }
      const found = M24.forbiddenWords(value.text);
      assert.deepEqual(found, [], JSON.stringify(found));
      evidence.sends.push({ case: "C5", sendId: record.send_id, status: record.status, bodySha256: built.previewSha256,
        transportSha256: transport?.sha256 ?? null, preparedSha256: prepared.preparedSha256 });
      evidence.observed.C5 = { bodyHashEqual: prepared.preparedSha256 === built.previewSha256 &&
        (transport === null || transport.sha256 === built.previewSha256), limitationsOk: true, catalytic: card.catalytic };
      return { card, prepared, transport, choice: record.choice_handle };
    });
    await rec.step("C5-03", "보고서 만들기 on the send row: saved (201); the library shows JEV 판정 보고서 with the stored " +
      "Markdown (fixed sentences, no per-candidate values, no forbidden word)", async () => {
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 120000 });
      await jev(page).locator(`[data-testid="jev-send-report"]${attr("data-choice-handle", sent.choice)}`).click();
      const response = await posted;
      const body = await response.json();
      noteReport(evidence, "C5", "jev_choice", response.status(), body.handle);
      await jev(page).locator(`[data-testid="jev-report-done"]${attr("data-report-handle", body.handle)}`).waitFor({ timeout: 60000 });
      const opened = await libraryOpen(page, body.handle);
      await keepTabText(page, evidence, artifacts, "knowledge@C5", "knowledge");
      return { status: response.status(), body, opened: { kind: opened.kind, text: opened.text },
        saved: await readApi(page, `/runs/${run}/reports/selected?handle=${enc(body.handle)}`) };
    }, async value => {
      assert.equal(value.status, 201);
      assert.equal(value.body.manifest.analysis_type, "jev_choice");
      assert.equal(value.opened.kind, "JEV 판정 보고서");
      assert.equal(value.opened.text, value.saved.markdown);
      const choice = storedObject(runsDir, run, sent.choice);
      const projection = storedObject(runsDir, run, built.handle);
      for (const sentence of M24.expectedLimitations("mutation", choice.arrival.late, catalyticStatus(projection)))
        assert.ok(value.opened.text.includes(sentence), "the report lacks a fixed sentence");
      assert.deepEqual(M24.forbiddenWords(value.opened.text), []);
      return { handle: value.body.handle, markdown: textDigest(value.saved.markdown) };
    });
  });
}

/** One loop of one round (adapted from endtoend-b-flow.cjs loopRound and jev-loop-flow.cjs proteinBranch / modeLive):
 * create (pool, goal, seed, cap 1, the computation inputs), 보낼 내용 만들기 (identity and the order oracle), the send
 * (guarded in the live phase), the card, the compute (model, then docking: two units), end, report. */
async function loopRound(ctx, { id, pool, loop, unitLabel, guard = null }) {
  const { page, rec, evidence, units, input, log, plan } = ctx;
  const S = ctx.state;
  const runsDir = input["runs-dir"];
  const run = S.run;
  const created = await rec.step(`${id}-01`, `JEV 루프 (단백질): choose the 1UBQ set, check the pool (${pool.length}), ` +
    `${loop.goal === "explore" ? "탐색형" : "활용형"}, loop seed ${loop.seed}, cap ${loop.cap}, the computation inputs (the ` +
    "branch's docking values, the phenol SDF); 루프 만들기: a candidate computed by an earlier round is scored as stored " +
    "(reused, no unit), the others pending", async () => {
    await openLoopArea(page);
    await loopChooseSource(page, S.set, S.candidates.length);
    await loopPool(page, pool.map(String));
    await lpt(page, `jev-loop-goal-${loop.goal}`).check();
    await loopFill(page, "jev-loop-seed", loop.seed);
    await loopFill(page, "jev-loop-iteration-cap", loop.cap);
    await loopProteinSetup(page, S.phenol, plan.docking);
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
    assert.deepEqual(value.entry.request.setup.ligand, { source: "sdf", sdf_handle: S.phenol });
    for (const item of value.record.candidates) {
      const earlier = S.loopComputed[String(item.ref)];
      if (earlier) {
        assert.deepEqual([item.state, item.evaluation], ["scored", "reused"], `${item.ref} not reused`);
        assert.equal(item.score_kcal_mol, earlier.score);
      } else assert.equal(item.state, "pending");
    }
    assert.equal(value.record.counts.units_charged, 0);
    assert.deepEqual(value.record.limitations, M25.expectedLimitations("mutation", loop.goal));
    loopRowsMatch(value.table, value.record);
    for (const row of value.table.rows.filter(item => !item.hasScore))
      x5(evidence, row.score.startsWith(NULL_TEXT) && !/\b0(\.0+)?\b/.test(row.score), `${id} pending row ${row.ref}: ` +
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
        const earlier = S.loopComputed[String(ref)];
        return row.state === "scored" && !!earlier && row.score_kcal_mol === earlier.score;
      });
      assert.ok(observed.bodyScoresStored, "an exploit body score is not the stored first mode of its candidate");
      observed.computedRows = rows.length;
    }
    (evidence.observed[id.startsWith("L-") ? "L-C6" : "C6"] ??= {})[loop.goal] = observed;
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
    return { result, card, status, wording: record.status === "completed" ? await loopWording(page) : [] };
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
    assert.deepEqual(value.wording, [], JSON.stringify(value.wording));
    if (evidence.live) Object.assign(evidence.live.send, { listPosition: choice.answer.list_position, listSize: choice.answer.list_size,
      responseShape: { confidence: choice.answer.confidence !== null, probabilities: choice.answer.probabilities !== null },
      usage: choice.usage, bodyBytes: built.bodyBytes });
    return { ...card, proposal: record.choice_handle, sendId: record.send_id, bytes };
  });
  const computed = await rec.step(`${id}-04`, "Check the compute confirmation and press 이 선택으로 계산 시작 (JEV 판정 사용): the " +
    "M21 model of the candidate the card named (real PDBFixer + OpenMM), then 도킹 시작: the M18 docking into that " +
    "mutant model (real qvina); two units; the round ends with the stored first-mode score", async () => {
    const entry = await units.before(unitLabel);
    const first = await loopPressCompute(page, run, loopId, "jev-loop-compute-proposal", log);
    const finish = await loopFinishRound(page, run, loopId, first, 1, log);
    await units.after(entry);
    return { first, finish, entry, record: await readLoop(page, run, loopId), table: await loopCandidateTable(page) };
  }, async value => {
    assert.equal(value.first.status, 200, JSON.stringify(value.first.json).slice(0, 600));
    assert.deepEqual(value.first.request, { iteration: 1, proposal: sent.proposal });
    const it = value.record.iterations.find(item => item.index === 1);
    assert.equal(it.decided_by, "jev");
    assert.equal(it.candidate_ref, sent.ref, "the computation is not on the candidate JEV chose");
    const model = it.steps.find(item => item.step === "model");
    const dock = it.steps.find(item => item.step === "dock");
    assert.equal(model.state, "completed");
    assert.equal(dock.state, "completed");
    const modelJob = await readApi(page, `/runs/${run}/jobs/${enc(model.job_id)}`);
    const dockJob = await readApi(page, `/runs/${run}/jobs/${enc(dock.job_id)}`);
    assert.deepEqual([modelJob.protocol_id, modelJob.status], [MODEL_PROTOCOL, "done"]);
    assert.deepEqual([dockJob.protocol_id, dockJob.status], [DOCKING_PROTOCOL, "done"]);
    const result = storedObject(runsDir, run, dock.result_handle);
    assert.deepEqual(result.inputs.receptor.source, { kind: "mutation_model", side: "mutant", mutation_model: model.result_handle });
    assert.ok(["scored", "null_result"].includes(it.state), it.state);
    if (it.state === "scored") assert.equal(it.score_kcal_mol, result.modes[0].score_kcal_mol, "the round score is not the stored first mode");
    loopRowsMatch(value.table, value.record);
    if (it.state === "scored") S.loopComputed[String(it.candidate_ref)] = { score: it.score_kcal_mol, result: dock.result_handle };
    if (evidence.live) evidence.live.compute = { state: it.state, model: modelJob.status, dock: dockJob.status };
    return { ref: sent.ref, state: it.state, score: it.score_kcal_mol, units: value.entry.usedUnits,
      approval: value.finish.approval };
  });
  await rec.step(`${id}-05`, "루프 끝내기: the summary jev_loop_result@1 is stored (scores = stored first modes); the " +
    "sentences add LJ8 when candidates are left without a score (not 0); 보고서 만들기: saved (201), JEV 루프 보고서 in the " +
    "library", async () => {
    const ended = await loopEnd(page, run, loopId, log);
    const report = await loopReport(page, run, log);
    noteReport(evidence, id.startsWith("L-") ? "L-C6" : "C6", "jev_loop", report.status, report.json?.handle);
    const opened = report.status === 201 ? await libraryOpen(page, report.json.handle) : null;
    return { ended, report, opened: opened && { kind: opened.kind, text: opened.text }, saved: report.status === 201
      ? await readApi(page, `/runs/${run}/reports/selected?handle=${enc(report.json.handle)}`) : null };
  }, async value => {
    assert.equal(value.ended.answer.status, 200);
    const summary = storedObject(runsDir, run, value.ended.result);
    assert.equal(summary.schema, "jev_loop_result@1");
    for (const row of summary.candidates) {
      if (row.state !== "scored") { assert.equal(row.score_kcal_mol, null); continue; }
      assert.equal(row.score_kcal_mol, S.loopComputed[String(row.ref)]?.score, `${row.ref} score`);
    }
    const uncomputed = summary.candidates.some(row => ["pending", "unavailable"].includes(row.state));
    assert.deepEqual(value.ended.limitations, M25.expectedLimitations("mutation", loop.goal, { ended: true, uncomputed }));
    x5(evidence, !uncomputed || value.ended.limitations.includes(M25.LJ.LJ8), `${id} ended loop: LJ8 shown for the ` +
      "candidates left without a score (no score, not 0)");
    assert.equal(value.report.status, 201, JSON.stringify(value.report.json).slice(0, 400));
    assert.equal(value.report.json.manifest.analysis_type, "jev_loop");
    assert.equal(value.opened.kind, LOOP_REPORT_KIND);
    assert.equal(value.opened.text, value.saved.markdown);
    assert.deepEqual(M25.forbiddenWords(value.opened.text), [], "forbidden wording in the loop report");
    return { endReason: summary.end_reason, report: value.report.json.handle, counts: summary.counts };
  });
  return { loopId, chosen: computed.ref, proposal: sent.proposal };
}

/** The loop pool of the plan rule from the stored set: candidates outside Gly / Pro / Cys positions and not the M21
 * target, in set order. */
function loopPoolRefs(plan, candidates) {
  const wanted = plan.c2.expect.loopPool;
  const refs = candidates.filter(row => wanted.includes(candidateText(row))).map(row => row.index);
  assert.deepEqual(candidates.filter(row => refs.includes(row.index)).map(candidateText), wanted, "loop pool differs from the plan");
  return refs;
}

async function flowC6(ctx) {
  const { rec, evidence, plan, artifacts, page } = ctx;
  const S = ctx.state;
  await rec.part("C6", ["C2"], async () => {
    await ensurePhenol(ctx, "C6");
    const refs = loopPoolRefs(plan, S.candidates);
    assert.ok(refs.length >= 3, "fewer than three candidates for the loops");
    const explore = await loopRound(ctx, { id: "C6-explore", pool: refs, loop: plan.loops.explore, unitLabel: "C6-explore" });
    const exploit = await loopRound(ctx, { id: "C6-exploit", pool: refs, loop: plan.loops.exploit, unitLabel: "C6-exploit" });
    evidence.observed.C6 = { ...(evidence.observed.C6 ?? {}), chosen: [explore.chosen, exploit.chosen], pool: refs };
    await keepTabText(page, evidence, artifacts, "protein@C6", "protein");
  });
}

async function flowC4(ctx) {
  const { page, plan, rec, evidence, units, input, artifacts } = ctx;
  const S = ctx.state;
  const runsDir = input["runs-dir"];
  await rec.part("C4", ["C2"], async () => {
    const run = S.run;
    await ensurePhenol(ctx, "C4");
    const space = plan.c2.expect.space;
    const gaCtx = { runsDir, run, setContent: S.setContent };
    const observed = (evidence.observed.C4 = { settings: {} });
    const exempt = new Set([...Object.values(S23), ...MODEL_LIMITATIONS]);
    let first = null;
    for (const key of ["1", "2"]) {
      const setting = plan.ga.settings[key];
      const label = `C4-${key}`;
      const reusable = first === null ? 0 : new Set(first.generations.flatMap(gen => gen.individuals)
        .filter(item => item.origin !== "carried" && item.result_handle).map(item => item.key)).size;
      const pf = await rec.step(`${label}-01`, `서열 GA: 입력 목록 다시 읽기; the 1UBQ set, the phenol SDF, 리간드 범위 + margin, the ` +
        `docking values, both confirmations and the acknowledgements; setting ${key} (${Object.entries(setting).map(([k, v]) =>
          `${k} ${v}`).join(", ")}); 시작 전 확인 보기: the reserved units 2 × (reserved_evaluations + 1) are on screen and equal the ` +
        "spec 7 arithmetic; the space is the one counted here", async () => {
        await openGaArea(page);
        await chooseGaInputs(page, run, { set: S.set, sdf: S.phenol, docking: plan.docking });
        for (const [k, v] of Object.entries(strings(setting))) await gaFill(page, `sequence-ga-param-${k}`, v);
        const entry = await units.before(label);
        return { pf: await gaPreflight(page, run), entry };
      }, async value => {
        const facts = gaPreflightMatches(value.pf, { gaValues: setting, space, want: plan.ga.need[key],
          reusable, referenceReusable: first === null ? false : first.reference.result_handle !== null });
        assert.deepEqual(value.pf.request.box, { source: "ligand_range", margin_A: Number(plan.docking.margin) });
        if (value.entry.onPlan)
          assert.equal(facts.shortfall.expensive_calls, plan.units.raises[label] ?? 0, "the unit shortfall differs from the plan");
        S.gaEntry = value.entry;
        return { ...facts, request: value.pf.request, pf: value.pf };
      });
      if (pf.shortfall.expensive_calls > 0 || pf.shortfall.wall_clock_s > 0) {
        await rec.step(`${label}-02`, "Click 이 서열 GA에 필요한 만큼 한도를 올림 (a person's click): the limit rises by the " +
          "shortfall only, by human, with the sequence GA context; no job, object or charge; the preflight is read again with " +
          "no shortfall", () => gaApproveLimits(page, runsDir, run, pf.pf), async value => {
          const facts = gaApprovalMatches(value);
          evidence.raises.push({ case: label, shortfall: facts.shortfall, increase: facts.increase,
            limitsBefore: facts.limitsBefore, limitsAfter: facts.limitsAfter, by: "human-click" });
          return evidence.raises.at(-1);
        });
      }
      const ran = await rec.step(`${label}-03`, "Click 서열 GA 시작 (no second approval): the real GA (PDBFixer + OpenMM model of " +
        "each individual, qvina) runs to its stop reason with exactly the reserved units; choose its summary: the wild-type " +
        "reference row apart from the table with values only, every generation table = the stored individuals (score = " +
        "the stored M18 first mode, min / max as values only), the stop reason in the closed set, the S sentences verbatim",
      async () => {
        const job = await runGa(page, run);
        await units.after(S.gaEntry);
        const header = await openGaSummary(page, job.handle);
        return { job, header, detail: await readApi(page, `/runs/${run}/sequence_ga/results/${enc(job.handle)}`) };
      }, async value => {
        assert.equal(value.job.job.status, "done", JSON.stringify(value.job.job.failure));
        assert.equal(value.job.job.protocol_id, GA_PROTOCOL);
        assert.equal(value.job.approved, false, "the run's approval was asked again");
        const stored = storedObject(runsDir, run, value.job.handle);
        const facts = await gaResultEquals(page, gaCtx, value.header, value.detail, stored);
        assert.equal(stored.reserved_units, plan.ga.need[key].reserved);
        if (first !== null) {
          let reuseMismatches = 0;
          const earlier = new Map(first.generations.flatMap(gen => gen.individuals)
            .filter(item => item.origin !== "carried" && item.result_handle).map(item => [item.key, item]));
          for (const item of stored.generations.flatMap(gen => gen.individuals).filter(entry => entry.origin !== "carried")) {
            const want = earlier.has(item.key) ? "reused" : "computed";
            if (item.evaluation !== want) reuseMismatches++;
            if (want === "reused" && item.result_handle !== earlier.get(item.key).result_handle) reuseMismatches++;
          }
          if (first.reference.result_handle && (stored.reference.evaluation !== "reused" ||
            stored.reference.result_handle !== first.reference.result_handle)) reuseMismatches++;
          observed.reuseMismatches = reuseMismatches;
          assert.equal(reuseMismatches, 0, "an individual stored by setting 1 was computed again");
        }
        for (const item of stored.generations.flatMap(gen => gen.individuals).filter(entry => entry.state !== "scored"))
          x5(evidence, item.score === null, `${label} individual ${item.key} without a score: null, shown ${NULL_TEXT} (not 0)`);
        observed.settings[key] = { reserved: stored.reserved_units, reservedEvaluations: stored.reserved_evaluations,
          space: stored.space, newEvaluations: stored.new_evaluations_used, reused: stored.reused_count,
          stopReason: stored.stop_reason, status: stored.status, generations: stored.generations.length,
          reference: facts.reference };
        return { handle: value.job.handle, ...facts, tables: facts.tables.length, units: S.gaEntry.usedUnits };
      });
      const stored = storedObject(runsDir, run, ran.handle);
      if (key === "1") {
        const pick = stored.generations.flatMap(gen => gen.individuals.map((item, position) => ({ gen: gen.index, position, item })))
          .find(entry => entry.item.origin !== "carried" && entry.item.state === "scored");
        assert.ok(pick, "setting 1 has no scored individual to open");
        await rec.step(`${label}-04`, `Click 개체 상세 of individual ${pick.item.key} (generation ${pick.gen}): the stored model ` +
          "values of that one mutant structure only (its own two potentials with S5, atom counts, its limitations) and its " +
          "stored M18 result; no other structure's potential beside it", async () => {
          await gaShowGeneration(page, pick.gen);
          await st(page, `sequence-ga-open-${pick.gen}-${pick.position}`).click();
          await st(page, "sequence-ga-individual").and(seqPanel(page).locator(attr("data-key", pick.item.key))).waitFor({ timeout: 60000 });
          await waitFor(page, async () => await gaArea(page, "individual").getAttribute("data-state") === "ready" ? true : null,
            "individual area ready", 30000);
          return { view: await gaIndividualView(page),
            read: await readApi(page, `/runs/${run}/sequence_ga/results/${enc(ran.handle)}/individual?key=${enc(pick.item.key)}`) };
        }, async value => {
          const facts = gaIndividualMatches(value.view, value.read, gaCtx, pick.item);
          for (const text of value.view.m18Limitations) exempt.add(text);
          observed.individual = { key: facts.key, limitations: facts.limitations, m18: facts.m18 };
          return facts;
        });
      }
      await rec.step(`${label}-05`, "보고서 만들기 for this summary: saved (201) as sequence_ga; the library shows 서열 GA 보고서 " +
        "with the stored Markdown (the score name and the S sentences of the summary); the M23 wording check of the GA area " +
        "(fixed sentences exempt) finds nothing", async () => {
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 120000 });
        posted.catch(() => undefined);
        await st(page, "sequence-ga-report").click();
        const response = await posted;
        const body = await response.json();
        noteReport(evidence, "C4", "sequence_ga", response.status(), body.handle);
        await st(page, "sequence-ga-report-done").waitFor({ timeout: 60000 });
        const text = await seqPanel(page).evaluate(node => node.innerText);
        if (key === "2") await keepTabText(page, evidence, artifacts, "protein@C4", "protein");
        const opened = await libraryOpen(page, body.handle);
        return { status: response.status(), body, text, opened: { kind: opened.kind, text: opened.text },
          saved: await readApi(page, `/runs/${run}/reports/selected?handle=${enc(body.handle)}`) };
      }, async value => {
        assert.equal(value.status, 201);
        assert.equal(value.body.manifest.analysis_type, "sequence_ga");
        assert.equal(value.body.manifest.result_handle, ran.handle);
        assert.equal(value.opened.kind, "서열 GA 보고서");
        assert.equal(value.opened.text, value.saved.markdown);
        assert.ok(value.saved.markdown.includes(SCORE_LABEL), "the report lacks the score name");
        for (const id of M23.statementIds(stored)) assert.ok(value.saved.markdown.includes(S23[id]), `the report lacks ${id}`);
        const found = gaForbidden(value.text, exempt);
        assert.deepEqual(found, [], JSON.stringify(found));
        return { handle: value.body.handle, markdown: textDigest(value.saved.markdown) };
      });
      first = first ?? stored;
    }
  });
}

async function flowC7(ctx) {
  const { page, app, rec, evidence, input, artifacts } = ctx;
  const S = ctx.state;
  const runsDir = input["runs-dir"];
  await rec.part("C7", [], async () => {
    assert.ok(S.run, "no run");
    const run = S.run;
    const made = evidence.reportHandles.filter(item => item.httpStatus === 201);
    await rec.step("C7-01", "지식·보고서 report library: the list shows exactly the reports of the run's report events, which " +
      "are the reports C1–C6 made; each one clicked opens with the stored Markdown and reports/selected 200; its JSON " +
      "다운로드 equals the backend bytes and the stored manifest bytes", async () => {
      const events = runEvents(runsDir, run).filter(event => ["report_created", "method_report_created"].includes(event.type));
      const handles = events.map(event => event.report_handle);
      await enterTab(page, TAB.knowledge);
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
      await keepTabText(page, evidence, artifacts, "knowledge@C7", "knowledge");
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
      evidence.observed.C7 = { listed: value.shown.length, created: made.length, events: value.handles.length, downloadMismatches,
        kinds: [...new Set(value.opened.map(item => item.kind))].sort(),
        reports: value.opened.map(item => ({ case: item.case, kind: item.kind, jsonSha256: sha(item.download) })) };
      return evidence.observed.C7;
    });
  });
}

// ------------------------------------------------------------------ modes
function newContext(ctx) { ctx.state.loopComputed = {}; return ctx; }

async function modeFixture(ctx) {
  const { input } = ctx;
  M25.fixtureServer(input.control, input["runs-dir"], input["backend-pid"]);
  await flowC1(ctx);
  await flowC2(ctx, "C2");
  await flowC3(ctx);
  await flowC5(ctx);
  await flowC6(ctx);
  await flowC4(ctx);
  await flowC7(ctx);
}

async function modeLive(ctx) {
  const { input, plan, rec, evidence, page, artifacts } = ctx;
  const S = ctx.state;
  if (input.control) M25.fixtureServer(input.control, input["runs-dir"], input["backend-pid"]);
  evidence.live = { rehearsal: !!input.control, sendAllowed: plan.live.sendAllowed, dispatchLimit: plan.live.dispatchLimit,
    send: null, compute: null, guard: null, egressStop: null };
  await flowC2(ctx, "L-pre-C2");
  await rec.part("L-C6", ["L-pre-C2"], async () => {
    await ensurePhenol(ctx, "L-C6");
    const refs = loopPoolRefs(plan, S.candidates);
    const guard = () => {
      if (!plan.live.sendAllowed) return "the plan does not allow a send (an earlier round did not complete)";
      const total = dispatchTotal(input["runs-dir"]);
      if (total >= plan.live.dispatchLimit) return `dispatch events ${total} ≥ the limit ${plan.live.dispatchLimit}`;
      return null;
    };
    await loopRound(ctx, { id: "L-C6", pool: refs, loop: plan.loops.explore, unitLabel: "C6-explore", guard });
    await keepTabText(page, evidence, artifacts, "protein@L-C6", "protein");
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
  const evidence = { schema: "m28_branch_c_evidence@1", mode: input.mode, rehearsal: input.mode === "live" && !!input.control,
    run: null, parts: {}, observed: {}, reportsCreated: 0, reportHandles: [], x5: [], texts: {}, units: [], raises: [],
    sends: [], live: null, structures: plan.structures, planSha256: sha(fs.readFileSync(input.plan)),
    inputs: Object.fromEntries(Object.entries(plan.inputs).map(([key, item]) => [key, { name: item.name, sha256: item.sha256,
      syntheticLabeled: item.syntheticLabeled }])), startedAt: new Date().toISOString() };
  const session = await launchOffscreen({ url: input.url, artifacts: input.artifacts, interactive: false });
  const log = requestLog(session.page);
  const units = unitTracker(session.page, plan, evidence);
  const rec = recorder(session, evidence, () => units.offPlan());
  const ctx = newContext({ ...session, input, plan, rec, evidence, units, log, state: {} });
  const callsBefore = input.control ? fixtureCalls(input.control).length : 0;
  let error = null;
  let proof = null;
  try {
    proof = await offscreenProof(session.app, session.page);
    await waitForBoot(session.page);
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
    const dispatched = dispatchTotal(input["runs-dir"]);
    evidence.fixture = { calls: calls.length, scripts: calls.map(call => call.script), dispatched,
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
  fs.writeFileSync(path.join(input.artifacts, "endtoend-c-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  const harness = Object.fromEntries(["endtoend-c-flow.cjs", "driver.cjs", "main.cjs", "mutation-flow.cjs",
    "mutation-model-flow.cjs", "sequence-ga-flow.cjs", "jev-flow.cjs", "jev-loop-flow.cjs", "normal-flow.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m28_branch_c_row@1", mode: input.mode, rehearsal: evidence.rehearsal,
    evidenceKind: "real_electron_offscreen", status: passed ? "pass" : "fail", parts, runId: evidence.run,
    reportsCreated: evidence.reportsCreated, buildId: buildId(), harness, offscreen: proof, offscreenComplete: complete,
    externalRequestCount: proof ? proof.nonLoopbackRequests : null, fixtureProof, fixture: evidence.fixture ?? null,
    units: evidence.units.map(item => ({ label: item.label, remaining: item.remaining, planned: item.planned,
      remainingMatchesPlan: item.remainingMatchesPlan, used: item.usedUnits ?? null })),
    raises: evidence.raises, sends: evidence.sends, live: evidence.live, structures: evidence.structures,
    error: evidence.error ? "see endtoend-c-evidence.json" : null, evidenceFile: "endtoend-c-evidence.json",
    stepsFile: path.basename(rec.file), artifacts: input.artifacts, startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, run: evidence.run, parts }) + "\n");
  if (error) process.stderr.write(`endtoend-c-flow failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`endtoend-c-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, expectedSideBySide, catalyticCellText, loopPoolRefs, candidateText };
