"use strict";

// M24 JEV science send offscreen QA (.dryforge/spec.md sections 2, 5, 6, 9, 11). Real Electron offscreen page
// (isOffscreen, GPU/WebGL, paint). Every product action is a Playwright locator mouse/keyboard input on the 지식·보고서
// tab (consent switch, kind and set radios, candidate checkboxes, filter form, 보낼 내용 만들기, confirmation, 이 내용을
// JEV로 보냅니다, 결과 열기, 보고서 만들기, the report library); DOM .click() and product handlers are never called and
// this script never posts to the API itself. Observation is read-only: data attributes and text of the page, renderer
// request/response events, Electron paint frames, GET reads of the loopback API, the stored objects and events in
// <runs-dir>/<run>/events.jsonl (read-only file reads) and, with the fixture server, its control folder (calls.jsonl).
//
// The candidate sets are made beforehand by scripts/m24_offscreen_acceptance.py (real M17 jobs and real M20
// generate_mutation_candidates calls over the loopback API) and named in --setup. Independent oracle written here from
// the spec: J1–J7 and U1–U3 verbatim (spec 6), the closed refusal/failure codes (spec 5), the cap of 20 candidates and
// 10 sends, the expected limitation list per kind, the display rounding (ROUND_HALF_UP, 3 decimals) and the wording
// check. Body identity: the preview <pre> text, the server preview string, the SHA-256 computed here, the stored
// projection, the `prepared` audit body and (fixture) the bytes the scripted transport received.
//
// Modes (the full sequence: scripts/m24_offscreen_acceptance.py):
//   fixture  backend = backend/tests/offscreen_jev_fixture/server.py (SCIENCE_GATE over a scripted httpx.MockTransport;
//            no provider socket). Runs A (ligand + 1UBQ + 1MQ4 sets), B and C (1UBQ set): tab entry, consent off/on,
//            source choice, 20-candidate cap, ligand filter, preview identity, confirmation, good, same-body resend,
//            report, alias outside the list, model mismatch, late reply after consent off, send cap, other tabs (run A);
//            no usage then egress stop (run B); HTTP 500 (run C); wording; browser egress 0.
//   live     the --plan sends through the same screen path, one by one, each guarded before its click: the dispatch
//            events of every run in --runs-dir must stay below the plan's maxDispatch and below maxPerRun in the run.
//            Against the real backend this is the only mode that sends to JEV (scripts/m24_offscreen_acceptance.py
//            --phase calibrate|live); with --control it is the rehearsal of that plan against the fixture server.
//            A plan with `preChecks` (the calibrate plan) first checks, with no send, consent off → consent_off and a
//            closed send button, the refused 21st candidate, and the closed button before the confirmation.
//            A send that is not completed, or a stopped egress, ends the plan (no retry, no new run); its row is kept.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { launchOffscreen, capture } = require("./driver.cjs");

const REPO = path.resolve(__dirname, "../../..");
const MODES = ["fixture", "live"];
const TAB = "지식·보고서";
const TAB_LABELS = ["구조 분석", "단백질 공학", "리간드 설계·탐색", "지식·보고서"];
const SERVED_MODEL = "typesafe/jev-1.13-20260917";
const MAX_CANDIDATES = 20;
const SEND_CAP = 10;
// spec 6 verbatim (independent of the product constants)
const J = {
  J1: "JEV 판정은 외부 모델이 보낸 후보 목록에서 고른 하나일 뿐이며 계산 결과가 아니라 제안으로 따로 기록한 것이다. " +
    "순위·추천·예측이 아니다.",
  J2: "고른 이유는 알 수 없다. 응답에는 선택과 모델이 보고한 확신도·확률만 있으며 과학 값이 아니다.",
  J3: "외부로 나간 내용은 승인한 미리보기 본문과 바이트가 같고(해시로 확인) 그 본문이 이 기록의 근거 전부이다.",
  J4: "모델 선택은 후보 목록의 순서(로컬 저장 순서)의 영향을 받을 수 있다.",
  J5: "후보는 2D 그래프이고 속성값은 RDKit 추정값이며 결합·활성·합성 가능성을 계산하지 않았고 수용체 정보 없이 고른 것이다.",
  J6: "후보는 위치와 바꿀 잔기의 조합이고 이웃 잔기·구간·거리는 준비된 구조의 저장 좌표에서 잰 기하이며 변이의 효과나 " +
    "상호작용을 뜻하지 않는다. 보호 판정은 사용자 목록·KLIFS 주요 부위(주석이 있을 때)·금속 근접·이황화 기준으로만 " +
    "했고 촉매 잔기 데이터베이스는 사용하지 않았으며, 검사하지 않은 항목은 '없음'이 아니다.",
  J7: "이 응답은 run 취소 또는 과학 전송 동의 끄기 뒤에 도착했으며 어떤 작업도 일으키지 않았다.",
};
const U = {
  U1: "같은 후보 목록을 다시 보내면 응답이 달라질 수 있다. 응답은 합치거나 다수결로 쓰지 않고 시간순으로 따로 보인다.",
  U2: "과학 전송은 뷰어 모델 명령과 같은 외부 토큰·USD 예산과 '사용량 모름' 중지 상태를 쓰며, 한쪽이 예산을 다 쓰거나 " +
    "사용량을 모르면 이 run에서 다른 쪽도 멈춘다.",
  U3: "보내는 서열 구간과 이웃 잔기 이름만으로도 어떤 단백질인지 알려질 수 있다. 번호 대응·accession은 보내지 않는다.",
};
const FIXED_LINES = [...Object.values(J), ...Object.values(U)];
// M26 spec 9 verbatim: a mutation projection's fifth sentence follows its wire's catalytic_residue_database status (J6
// for not_available = every v1 set; J6n / J6c for the v2 sets the M20 tool builds since M26). Not in FIXED_LINES.
const J6_BY_CATALYTIC = {
  not_available: J.J6,
  not_checked: "후보는 위치와 바꿀 잔기의 조합이고 이웃 잔기·구간·거리는 준비된 구조의 저장 좌표에서 잰 기하이며 변이의 효과나 " +
    "상호작용을 뜻하지 않는다. 보호 판정은 사용자 목록·KLIFS 주요 부위(주석이 있을 때)·금속 근접·이황화 기준으로만 " +
    "했고 이 집합에서는 M-CSA 촉매 잔기 주석을 전부 검사하지 않았으며, 검사하지 않은 항목은 '없음'이 아니다.",
  checked: "후보는 위치와 바꿀 잔기의 조합이고 이웃 잔기·구간·거리는 준비된 구조의 저장 좌표에서 잰 기하이며 변이의 효과나 " +
    "상호작용을 뜻하지 않는다. 보호 판정은 사용자 목록·KLIFS 주요 부위(주석이 있을 때)·금속 근접·이황화·M-CSA 촉매 " +
    "잔기 주석 기준으로만 했으며, 검사하지 않은 항목은 '없음'이 아니다.",
};
// Forbidden expressions (spec 2 and 8, plus 최고, 가장 높/낮 and highest; "비활성" is not "활성"): the same pattern and
// line rule as the product's jevForbiddenWords (frontend/src/lib/jev.ts JEV_FORBIDDEN) and the acceptance runner
// (scripts/m24_offscreen_acceptance.py FORBIDDEN); frontend/tests/jev.test.cjs and scripts/test_m24_offscreen_acceptance.py
// compare the three. A line exactly equal to a fixed sentence J1–J7 or note U1–U3 is exempt; nothing else is.
const FORBIDDEN = /순위|추천|최고|최적|개선|예측|유망|점수|에너지|(?<!비)활성|친화|안정성|ΔΔG|좋은|나쁜|안전|가장 높|가장 낮|winner|\bbest|\brank|recommend|highest/gi;
const LATE_TEXT = { consent_off: "동의 끈 뒤 도착", run_cancelled: "run 취소 뒤 도착" };
const UNKNOWN_USAGE_TEXT = "알 수 없음";
const NOT_REPORTED_TEXT = "보고 없음";
const PROCESS_NOTE = "fixture: replies are scripted labeled fixtures (backend/tests/offscreen_jev_fixture/server.py)";

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const enc = encodeURIComponent;
const attr = (name, value) => `[${name}="${String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"]`;
const masked = text => (text ?? "").replace(/\d+(?:[.,]\d+)*/g, "#").replace(/[ \t]+/g, " ").trim();

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, "runs-dir": null, control: null,
    setup: null, plan: null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2);
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode) || !value["runs-dir"] || !value.setup ||
      (value.mode === "fixture" && !value.control) || (value.mode === "live" && !value.plan)) throw new Error(
    `Usage: jev-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> --runs-dir <backend MW_RUNS_DIR> --setup <json> ` +
    "[--control <fixture control dir> (fixture: required; live: rehearsal against the fixture server)] " +
    "[--plan <json> (live)] [--url http://127.0.0.1:3000]. The setup and plan files are written by " +
    "scripts/m24_offscreen_acceptance.py, which also starts the services.");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  for (const key of ["artifacts", "runs-dir", "control", "setup", "plan"]) if (value[key]) value[key] = path.resolve(value[key]);
  value.url = new URL("/", value.url).toString();
  return value;
}

// ------------------------------------------------------------------ independent oracle helpers
/** Decimal-string ROUND_HALF_UP of a finite number (display rounding only). */
function halfUp(value, places) {
  let text = String(value);
  const exp = /^(-?)(\d+)(?:\.(\d+))?e([+-]\d+)$/.exec(text);
  if (exp) {
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
function expectedLimitations(kind, late, catalytic = "not_available") {
  assert.ok(catalytic in J6_BY_CATALYTIC, `catalytic status ${catalytic}`);
  return [J.J1, J.J2, J.J3, J.J4, kind === "ligand" ? J.J5 : J6_BY_CATALYTIC[catalytic], ...(late ? [J.J7] : [])];
}
/** The catalytic_residue_database status of a stored projection's wire (not_available for a ligand projection). */
function catalyticStatus(projection) {
  return projection.kind === "ligand" ? "not_available" : projection.wire.protection_checks.catalytic_residue_database;
}
/** Forbidden expressions in text, line by line; a line exactly equal to a fixed sentence or note is exempt. */
function forbiddenWords(text) {
  const found = [];
  for (const line of String(text ?? "").split("\n")) {
    if (FIXED_LINES.includes(line)) continue;
    for (const match of line.matchAll(FORBIDDEN)) found.push(match[0]);
  }
  return found;
}
/** Every string (keys and values) of a JSON value, for the wording check of replies. */
function strings(value, out = []) {
  if (typeof value === "string") out.push(value);
  else if (Array.isArray(value)) for (const item of value) strings(item, out);
  else if (value && typeof value === "object") for (const [key, item] of Object.entries(value)) { out.push(key); strings(item, out); }
  return out;
}

// ------------------------------------------------------------------ read-only observation
async function readApi(page, route) {
  const response = await page.request.get(new URL(`/api${route}`, page.url()).toString());
  assert.equal(response.status(), 200, `${route}: ${await response.text()}`);
  return response.json();
}
function runEvents(runsDir, run) {
  const file = path.join(runsDir, run, "events.jsonl");
  return fs.readFileSync(file, "utf8").split("\n").filter(Boolean).map(line => JSON.parse(line));
}
function storedObject(runsDir, run, handle) {
  for (const event of runEvents(runsDir, run))
    if (event.type === "object_created" && event.handle === handle)
      return JSON.parse(Buffer.from(event.payload_b64, "base64").toString("utf8"));
  throw new Error(`no object_created event for ${handle}`);
}
/** jev_science_dispatch_started events per run of the runs folder (read-only file reads). */
function dispatchCounts(runsDir) {
  const counts = {};
  for (const name of fs.readdirSync(runsDir)) {
    const file = path.join(runsDir, name, "events.jsonl");
    if (!/^run_[0-9a-f]+$/.test(name) || !fs.existsSync(file)) continue;
    counts[name] = fs.readFileSync(file, "utf8").split("\n")
      .filter(line => line.includes("jev_science_dispatch_started"))
      .filter(line => JSON.parse(line).type === "jev_science_dispatch_started").length;
  }
  return counts;
}
function fixtureCalls(control) {
  const file = path.join(control, "calls.jsonl");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").split("\n").filter(Boolean).map(line => JSON.parse(line)) : [];
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
function requestLog(page) {
  const rows = [];
  page.on("request", request => {
    const url = new URL(request.url());
    rows.push({ at: Date.now(), method: request.method(), path: url.pathname, api: url.pathname.startsWith("/api/") });
  });
  return rows;
}
const posts = (log, since) => log.filter(row => row.at >= since && row.method === "POST" && row.api).map(row => row.path);

// ------------------------------------------------------------------ evidence
function recorder(session, input, evidence) {
  const { app, page, artifacts } = session;
  const file = path.join(artifacts, `jev-${input.mode}.jsonl`);
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
      const html = await page.evaluate(() => document.querySelector('[data-testid="jev-panel"]')?.outerHTML
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
  return { step, part, append, file, cases, mark };
}
function fileRecord(file) {
  return file && fs.existsSync(file) ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) }
    : { path: file ?? null, missing: true };
}
function summarize(value) {
  try { const text = JSON.stringify(value); return text.length > 8000 ? `${text.slice(0, 8000)}…` : JSON.parse(text); }
  catch { return String(value); }
}
/** Every product control used, with what was observed right after. */
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
  await selectTab(page, "구조 분석");
  await page.getByRole("tab", { name: /^run/i }).click();
  if (await globalRun(page) !== run) await page.locator("#run-choice").selectOption(run);
  await waitFor(page, async () => await globalRun(page) === run, `run ${run} selected`, 30000);
  return waitFor(page, async () => {
    const value = await viewerSnapshot(page);
    return value?.ready === true && value.sourceHandle && value.catalogReady === true ? value : null;
  }, `run ${run} viewer ready`, 90000);
}
/** The science-consent mark of the global run line: present only right after .mw-app-run. */
async function globalLine(page) {
  return page.evaluate(() => {
    const run = document.querySelector(".mw-app-bar .mw-app-run");
    const badge = document.querySelector(".mw-app-bar .mw-app-science");
    return { runText: run?.textContent ?? null, globalRun: run?.getAttribute("data-global-run") ?? null,
      badge: badge ? { text: badge.textContent.trim(), consent: badge.getAttribute("data-science-consent"),
        afterRun: run?.nextElementSibling === badge, title: badge.getAttribute("title") } : null };
  });
}
/** The tab's text without the M25 "JEV 루프" area (jev-loop-panel), which those tabs now hold by design. */
const textWithoutLoopArea = panel => panel.evaluate(node => {
  const all = node.innerText;
  const loop = node.querySelector('[data-testid="jev-loop-panel"]');
  const part = loop ? loop.innerText : "";
  const at = part ? all.indexOf(part) : -1;
  return at < 0 ? all : all.slice(0, at) + all.slice(at + part.length);
});
/** Areas and masked text of one tab once its content is settled (no busy element, text stable for 0.7 s). */
async function tabSignature(page, label, id, log) {
  const since = Date.now();
  await selectTab(page, label);
  const panel = page.locator(`#mw-app-panel-${id}`);
  await panel.waitFor({ timeout: 15000 });
  const text = await waitFor(page, async () => {
    if (await panel.locator('[aria-busy="true"]').count()) return null;
    const a = masked(await textWithoutLoopArea(panel));
    await page.waitForTimeout(700);
    const b = masked(await textWithoutLoopArea(panel));
    return a === b && !(await panel.locator('[aria-busy="true"]').count()) ? b : null;
  }, `${label} settled`, 60000);
  return { label, areas: await panel.locator("[data-testid$='-panel']").evaluateAll(items =>
    items.map(item => item.getAttribute("data-testid"))),
  jevElements: await panel.locator('[data-testid^="jev-"]:not([data-testid^="jev-loop-"])').count(),
  textSha256: sha(Buffer.from(text)), lines: text.split("\n").length, text, posts: posts(log, since) };
}
function sameSignature(before, after) {
  const differing = before.text === after.text ? [] : after.text.split("\n").filter(line => !before.text.split("\n").includes(line))
    .slice(0, 12);
  return { areasEqual: JSON.stringify(before.areas) === JSON.stringify(after.areas), textEqual: before.text === after.text,
    differing, jevElements: after.jevElements, posts: after.posts };
}

// ------------------------------------------------------------------ JEV area (real input; read-only helpers)
const jev = page => page.locator('#mw-app-panel-knowledge [data-testid="jev-panel"]');
const jt = (page, id) => jev(page).locator(`[data-testid="${id}"]`);
const jarea = (page, name) => jev(page).locator(`[data-jev-area="${name}"]`);
const panelText = page => jev(page).evaluate(node => node.innerText);
async function openKnowledge(page) {
  await selectTab(page, TAB);
  await jev(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => await jev(page).getAttribute("data-jev-state") === "ready" &&
    await jarea(page, "status").getAttribute("data-state") === "ready" &&
    await jarea(page, "history").getAttribute("data-state") === "ready" ? true : null, "JEV area ready", 45000);
}
async function consentState(page) { return jt(page, "jev-consent-label").getAttribute("data-consent"); }
async function setConsent(page, run, on, evidence) {
  if ((await consentState(page) === "on") === on) return null;
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/jev/consent`, { timeout: 30000 });
  await jt(page, "jev-consent").click();
  const response = await posted;
  assert.equal(response.status(), 200, await response.text());
  const body = await response.json();
  assert.equal(body.enabled, on);
  await waitFor(page, async () => await consentState(page) === (on ? "on" : "off") ? true : null, "consent shown", 15000);
  control(evidence, "jev-consent", { run, enabled: on });
  return body;
}
/** Kind radio, then the set radio; waits until the table shows exactly `rows` candidate rows of that set. */
async function chooseSource(page, kind, handle, rows, evidence) {
  await jt(page, `jev-kind-${kind}`).check();
  const radio = jev(page).locator(`input[data-testid="jev-source"]${attr("data-jev-source", handle)}`);
  await radio.waitFor({ timeout: 30000 });
  const listed = await jev(page).locator('input[data-testid="jev-source"]').evaluateAll(items =>
    items.map(item => ({ handle: item.getAttribute("data-jev-source"), checked: item.checked })));
  if (!(await radio.isChecked())) await radio.check();
  await tableRows(page, kind, rows, "candidate rows");
  control(evidence, `jev-source-${kind}`, { handle });
  return listed;
}
/** The candidate table of `kind` once loaded with exactly `count` rows (a table being re-read has none). */
async function tableRows(page, kind, count, label) {
  return waitFor(page, async () => {
    if (await jarea(page, "candidates").getAttribute("data-state") !== "ready") return null;
    if (await jt(page, "jev-candidates").count() !== 1) return null;
    if (await jt(page, "jev-candidates").getAttribute("data-kind") !== kind) return null;
    const rows = await rowKeys(page);
    return rows.length === count ? rows : null;
  }, label, 30000);
}
const candidateBox = (page, key) => jev(page).locator(`input[data-testid="jev-candidate"]${attr("data-jev-candidate", key)}`);
async function rowKeys(page) {
  return jev(page).locator("tr[data-jev-candidate-row]").evaluateAll(items => items.map(item => ({
    key: item.getAttribute("data-jev-candidate-row"), checked: item.getAttribute("data-checked") === "true",
    passes: item.getAttribute("data-passes-all"), blocked: item.getAttribute("data-blocked-reason") })));
}
async function selectedCount(page) {
  return (await jt(page, "jev-selection-count").count()) ? Number(await jt(page, "jev-selection-count").getAttribute("data-selected")) : null;
}
async function uncheckAll(page) {
  for (const row of await rowKeys(page)) if (row.checked) await candidateBox(page, row.key).uncheck();
}
async function checkKeys(page, keys, evidence) {
  for (const key of keys) {
    await candidateBox(page, key).check();
    control(evidence, "jev-candidate", { key });
  }
}
/** 보낼 내용 만들기: the build_jev_projection command and the preview read that follows (both from the screen). */
async function build(page, run, evidence) {
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
  control(evidence, "jev-build", { run, projection: handle, count: result.handle.summary.selection_count });
  return { request: response.request().postDataJSON(), handle, summary: result.handle.summary, preview };
}
async function previewShown(page) {
  const box = jt(page, "jev-preview");
  return { handle: await box.getAttribute("data-projection-handle"), sha256: await box.getAttribute("data-body-sha256"),
    bytes: Number(await box.getAttribute("data-body-bytes")), blockedAttr: await box.getAttribute("data-blocked"),
    blocked: await jt(page, "jev-preview-blocked").locator("li[data-block-reason]").evaluateAll(items =>
      items.map(item => ({ code: item.getAttribute("data-block-reason"), text: item.textContent.trim() }))),
    previous: Number(await jt(page, "jev-preview-previous").getAttribute("data-previous-sends")),
    aliases: await jt(page, "jev-alias-table").locator("tr[data-alias]").evaluateAll(items =>
      items.map(item => ({ alias: item.getAttribute("data-alias"), cells: [...item.cells].map(cell => cell.textContent.trim()) }))),
    question: clean(await jt(page, "jev-preview-question").textContent()),
    body: await jt(page, "jev-preview-body").textContent() };
}
/** Waits for a re-read preview of this projection whose blocked list satisfies `ok`. */
async function previewWhen(page, handle, ok, label) {
  return waitFor(page, async () => {
    const shown = await previewShown(page);
    return shown.handle === handle && ok(shown) ? shown : null;
  }, label, 30000);
}
/** Body identity: <pre> text = server preview string; SHA-256 and bytes computed here; stored projection and the
 * alias table; question = stored question instructions. */
function previewIdentity(shown, built, stored) {
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
  return { bodySha256: built.preview.body_sha256, bodyBytes: built.preview.body_bytes, aliases: stored.selection.length,
    reservation: built.preview.reservation };
}
async function sendState(page) {
  return { enabled: await jt(page, "jev-send").isEnabled(), confirmEnabled: await jt(page, "jev-confirm").isEnabled(),
    confirmed: await jt(page, "jev-confirm").isChecked(),
    blocked: (await jt(page, "jev-send-blocked").count()) ? clean(await jt(page, "jev-send-blocked").textContent()) : "" };
}
/** Confirmation, then 이 내용을 JEV로 보냅니다 (one human click); `during` runs while the request is in flight and
 * `onRecord` gets the send record as soon as it arrives (before anything is waited for on the screen). */
async function confirmAndSend(page, run, { control: controlDir = null, script = null, during = null, onRecord = null } = {},
                              evidence) {
  if (controlDir) writeScript(controlDir, script);
  if (!(await jt(page, "jev-confirm").isChecked())) await jt(page, "jev-confirm").check();
  await waitFor(page, async () => await jt(page, "jev-send").isEnabled() ? true : null, "send enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/jev/sends`, { timeout: 90000 });
  await jt(page, "jev-send").click();
  control(evidence, "jev-send", { run, script });
  const extra = during ? await during() : null;
  const response = await posted;
  assert.equal(response.status(), 200, await response.text());
  const record = await response.json();
  if (onRecord) onRecord(record);
  await jev(page).locator(`[data-testid="jev-send-record"]${attr("data-send-id", record.send_id)}`).waitFor({ timeout: 30000 });
  await waitFor(page, async () => {
    const card = jev(page).locator(`[data-testid="jev-result-card"]${attr("data-send-id", record.send_id)}`);
    const reason = jev(page).locator(`[data-testid="jev-result-reason"]${attr("data-send-id", record.send_id)}`);
    return (await card.count()) + (await reason.count()) > 0 ? true : null;
  }, "result shown", 30000);
  return { request: response.request().postDataJSON(), record, extra };
}
async function readCard(page, sendId) {
  const card = jev(page).locator(`[data-testid="jev-result-card"]${attr("data-send-id", sendId)}`);
  const details = card.locator('[data-testid="jev-result-probabilities"]');
  const foldedBefore = !(await details.evaluate(node => node.open));
  if (foldedBefore) await details.locator("summary").click();
  return { foldedBefore,
    choiceHandle: await card.getAttribute("data-choice-handle"), chosen: await card.getAttribute("data-chosen-alias"),
    lateAttr: await card.getAttribute("data-late"),
    alias: clean(await card.locator('[data-testid="jev-result-alias"]').textContent()),
    local: clean(await card.locator('[data-testid="jev-result-local"]').textContent()),
    confidence: clean(await card.locator('[data-testid="jev-result-confidence"]').textContent()),
    model: clean(await card.locator('[data-testid="jev-result-model"]').textContent()),
    usage: Object.fromEntries(await card.locator("dd[data-usage]").evaluateAll(items =>
      items.map(item => [item.getAttribute("data-usage"), item.textContent.trim()]))),
    reported: await details.getAttribute("data-reported"),
    probabilities: await details.locator("li[data-alias]").evaluateAll(items =>
      items.map(item => ({ alias: item.getAttribute("data-alias"), text: item.textContent.trim() }))),
    probabilitiesText: clean(await details.innerText()),
    limitations: await card.locator('[data-testid="jev-result-limitations"] [data-limitation]').evaluateAll(items =>
      items.map(item => item.textContent)),
    late: (await card.locator('[data-testid="jev-result-late"]').count())
      ? clean(await card.locator('[data-testid="jev-result-late"]').textContent()) : null,
    // no ordering, bars or colour comparison: none of these exist in the JEV area
    comparison: await jev(page).evaluate(node => ({
      graphics: node.querySelectorAll("progress, meter, svg, canvas").length,
      ariaSort: node.querySelectorAll("[aria-sort]").length,
      styled: [...node.querySelectorAll("[style]")].filter(item => /width|background|color/i.test(item.getAttribute("style")))
        .length,
      attrs: [...node.querySelectorAll("*")].flatMap(item => [...item.attributes].map(a => a.name))
        .filter(name => /rank|best|score|recommend|winner/i.test(name)).length })),
  };
}
/** The completed card = the stored proposal (alias, local display, confidence, model, usage, probabilities in the sent
 * order, the fixed sentences) and nothing that orders or compares. */
function cardMatches(shown, record, choice, projection) {
  assert.equal(shown.choiceHandle, record.choice_handle);
  assert.equal(choice.scientific_result, false);
  assert.equal(choice.label, "JEV 판정(모델 선택)");
  assert.equal(shown.chosen, choice.answer.choice_alias);
  assert.equal(shown.alias, choice.answer.choice_alias);
  const aliases = projection.selection.map(item => item.alias);
  assert.ok(aliases.includes(choice.answer.choice_alias));
  const display = choice.answer.local_display;
  if ("smiles" in display) assert.ok(shown.local.includes(display.smiles), shown.local);
  else {
    for (const value of [display.residue.resname, String(display.residue.seq_auth), `${display.from}→${display.to}`])
      assert.ok(shown.local.includes(value), `${value} not in ${shown.local}`);
  }
  assert.equal(shown.confidence, choice.answer.confidence === null ? NOT_REPORTED_TEXT : halfUp(choice.answer.confidence, 3));
  assert.equal(shown.model, choice.served_model);
  assert.equal(shown.model, SERVED_MODEL);
  for (const key of ["input_tokens", "output_tokens", "external_tokens", "cost"]) {
    const value = choice.usage === null ? null : choice.usage[key];
    assert.equal(shown.usage[key], value === null ? UNKNOWN_USAGE_TEXT : String(value), `usage ${key}`);
  }
  if (choice.answer.probabilities === null) {
    assert.equal(shown.reported, "false");
    assert.equal(shown.probabilities.length, 0);
    assert.ok(shown.probabilitiesText.includes(NOT_REPORTED_TEXT));
  } else {
    assert.equal(shown.reported, "true");
    assert.deepEqual(shown.probabilities.map(item => item.alias), aliases, "probabilities not in the sent order");
    for (const item of shown.probabilities) {
      const value = choice.answer.probabilities[item.alias];
      if (value === undefined) assert.ok(item.text.includes(NOT_REPORTED_TEXT));
      else assert.ok(item.text.endsWith(halfUp(value, 3)), `${item.alias}: ${item.text}`);
    }
  }
  const late = choice.arrival.late;
  assert.deepEqual(shown.limitations, expectedLimitations(projection.kind, late, catalyticStatus(projection)));
  assert.equal(shown.lateAttr, String(late));
  assert.equal(shown.late === null, !late);
  if (late) assert.ok(shown.late.includes(LATE_TEXT[choice.arrival.late_reason]), shown.late);
  assert.deepEqual(shown.comparison, { graphics: 0, ariaSort: 0, styled: 0, attrs: 0 });
  assert.equal(shown.foldedBefore, true, "the per-candidate values were not folded when the card appeared");
  return { alias: shown.alias, confidence: shown.confidence, reported: shown.reported, late, usage: shown.usage,
    foldedBefore: shown.foldedBefore };
}
/** Failed or refused, observed only (read-only; reasonOnlyMatches judges it). */
async function reasonOnly(page, record) {
  const reason = jev(page).locator(`[data-testid="jev-result-reason"]${attr("data-send-id", record.send_id)}`);
  const result = jarea(page, "result");
  return { status: await reason.getAttribute("data-status"), code: await reason.getAttribute("data-reason-code"),
    text: clean(await reason.textContent()), resultText: clean(await result.innerText()),
    cards: await jt(page, "jev-result-card").count(), probabilities: await jt(page, "jev-result-probabilities").count(),
    aliasItems: await result.locator("[data-alias], [data-chosen-alias]").count() };
}
/** The reason only: status and code of the record, "(code)" in the reason line, no result card, no candidate value
 * and no number in the result area outside that reason line (the product's fixed label may hold one, e.g. 15초). */
function reasonOnlyMatches(value, record) {
  assert.equal(value.status, record.status);
  assert.equal(value.code, record.reason_code);
  assert.ok(value.text.includes(`(${record.reason_code})`), value.text);
  assert.equal(value.cards, 0);
  assert.equal(value.probabilities, 0);
  assert.equal(value.aliasItems, 0);
  const outside = value.resultText.split(value.text).join(" ");
  assert.ok(value.resultText.includes(value.text), `the reason line is not in the result area: ${value.resultText}`);
  assert.ok(!/\d/.test(outside), `a number in the result area outside the reason line: ${outside}`);
  assert.ok(!/\b[cm]\d{2}\b/.test(value.resultText), `a candidate alias in the result area: ${value.resultText}`);
  return value;
}
/** The audit `prepared` body of a send = the preview body; the payload hash = the preview hash. */
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
async function historyRows(page) {
  return jt(page, "jev-sends").locator("tr[data-jev-send]").evaluateAll(items => items.map(item => ({
    sendId: item.getAttribute("data-jev-send"), status: item.getAttribute("data-status"), late: item.getAttribute("data-late"),
    text: item.textContent.replace(/\s+/g, " ").trim() })));
}
/** The send history once it satisfies `ok` (the list is re-read after every send). */
async function historyWhen(page, ok, label) {
  return waitFor(page, async () => {
    if (!(await jt(page, "jev-sends").count())) return null;
    const rows = await historyRows(page);
    return ok(rows) ? rows : null;
  }, label, 30000);
}
async function wordingCheck(page, label, evidence) {
  const text = await panelText(page);
  const found = forbiddenWords(text);
  evidence.wording.push({ label, kind: "screen", found });
  return found;
}
/** 보고서 만들기 on a send row; the report library lists "JEV 판정 보고서" and shows the saved Markdown. */
async function makeReport(page, run, choiceHandle, evidence, button = null) {
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 120000 });
  await (button ?? jev(page).locator(`[data-testid="jev-send-report"]${attr("data-choice-handle", choiceHandle)}`)).click();
  const response = await posted;
  const body = await response.json();
  assert.equal(response.status(), 201, JSON.stringify(body).slice(0, 400));
  control(evidence, "jev-send-report", { run, choice: choiceHandle });
  await jev(page).locator(`[data-testid="jev-report-done"]${attr("data-report-handle", body.handle)}`).waitFor({ timeout: 60000 });
  const library = page.getByRole("region", { name: "보고서 보관함", exact: true });
  const reports = library.getByRole("region", { name: "저장된 보고서", exact: true });
  const content = library.getByRole("region", { name: "선택한 항목 내용", exact: true });
  const row = reports.locator("li button").filter({ hasText: body.handle });
  await row.waitFor({ timeout: 30000 });
  const kind = clean(await row.locator(".mw-library-kind").textContent());
  await row.click();
  control(evidence, "report-library-open", { handle: body.handle });
  const pre = content.getByLabel(`저장된 보고서 ${body.handle}`, { exact: true });
  await pre.waitFor({ timeout: 30000 });
  const saved = await readApi(page, `/runs/${run}/reports/selected?handle=${enc(body.handle)}`);
  return { status: response.status(), handle: body.handle, request: response.request().postDataJSON(), manifest: body.manifest,
    kind, text: await pre.textContent(), saved };
}
function reportMatches(report, choice, choiceHandle, evidence, projection) {
  assert.equal(report.kind, "JEV 판정 보고서");
  assert.deepEqual(report.request, { result_handle: choiceHandle });
  assert.equal(report.manifest.analysis_type, "jev_choice");
  assert.equal(report.manifest.result_handle, choiceHandle);
  assert.equal(report.text, report.saved.markdown);
  assert.equal(choice.projection.wire_sha256, projection.wire_sha256, "the choice is not of this projection");
  for (const sentence of expectedLimitations(choice.answer.local_display.smiles ? "ligand" : "mutation", choice.arrival.late,
    catalyticStatus(projection)))
    assert.ok(report.text.includes(sentence), "report lacks a fixed sentence");
  // per-candidate values stay out of the report: no other sent alias appears and no probabilities field is stored
  for (const item of choice.selection) {
    if (item.alias === choice.answer.choice_alias) continue;
    assert.ok(!new RegExp(`\\b${item.alias}\\b`).test(report.text), `the report names the other alias ${item.alias}`);
  }
  const keys = [];
  (function walk(item) {
    if (Array.isArray(item)) item.forEach(walk);
    else if (item && typeof item === "object") for (const [key, inner] of Object.entries(item)) { keys.push(key); walk(inner); }
  })(report.saved);
  assert.ok(!keys.includes("probabilities"), "the saved report carries a probabilities field");
  const found = forbiddenWords(report.text);
  evidence.wording.push({ label: "report markdown", kind: "report", found });
  assert.deepEqual(found, []);
  return { handle: report.handle, markdownSha256: sha(Buffer.from(report.text)), kind: report.kind };
}

// ------------------------------------------------------------------ mode fixture (scripted replies)
async function modeFixture(session, input, setup, rec_, evidence, log) {
  const { page } = session;
  const runsDir = input["runs-dir"];
  const controlDir = input.control;
  const server = JSON.parse(fs.readFileSync(path.join(controlDir, "server.json"), "utf8"));
  assert.equal(server.fixture, true, "the backend is not the fixture server");
  evidence.fixtureLabels.push(PROCESS_NOTE);
  const A = setup.runs.A, B = setup.runs.B, C = setup.runs.C;
  evidence.runs = { A: A.run, B: B.run, C: C.run };
  await waitForBoot(page);
  const callsBefore = fixtureCalls(controlDir).length;
  let viewerBefore = null;
  let before = null;

  // ---- run A: entry, consent, sources, the cap, preview identity, confirmation
  await rec_.part("entry", ["J-tab-entry", "J-other-tabs"], async () => {
    viewerBefore = await rec_.step("F00-run-a", [], "구조 분석: run A chosen in the rail (#run-choice); the viewer shows its " +
      "structure", () => chooseRun(page, A.run), async value => ({ sourceHandle: value.sourceHandle, sessionId: value.sessionId,
      generation: value.generation }));
    before = await rec_.step("F01-other-tabs-before", [], "단백질 공학 and 리간드 설계·탐색 visited before any JEV action " +
      "(areas and digit-masked text recorded)", async () => ({
      protein: await tabSignature(page, "단백질 공학", "protein", log), ligand: await tabSignature(page, "리간드 설계·탐색", "ligand", log) }),
    async value => {
      for (const sig of Object.values(value)) assert.equal(sig.jevElements, 0);
      return { protein: value.protein.areas, ligand: value.ligand.areas };
    });
    await rec_.step("F02-tab-entry", ["J-tab-entry"], "Click 지식·보고서: the JEV area mounts with GET reads only; consent off, " +
      "nothing chosen, built or sent; fixed notice, U2 and U3; cap 10 with 0 used; the 구조 분석 panel hidden and inert; " +
      "no global science mark", async () => {
      const since = Date.now();
      await openKnowledge(page);
      await page.waitForTimeout(800);
      return {
        posts: posts(log, since), reads: [...new Set(log.filter(row => row.at >= since && row.api && row.method === "GET")
          .map(row => row.path))],
        consent: await consentState(page), consentChecked: await jt(page, "jev-consent").isChecked(),
        notice: await jt(page, "jev-consent-notice").locator("p").evaluateAll(items => items.map(item => item.textContent)),
        u2: await jt(page, "jev-note-u2").textContent(), u3: await jt(page, "jev-note-u3").textContent(),
        cap: { used: await jt(page, "jev-cap").getAttribute("data-used"), remaining: await jt(page, "jev-cap").getAttribute("data-remaining"),
          text: clean(await jt(page, "jev-cap").textContent()) },
        kinds: await jev(page).locator('input[data-testid^="jev-kind-"]:checked').count(),
        sources: await jt(page, "jev-sources").count(), selection: await jt(page, "jev-selection-count").count(),
        buildEnabled: await jt(page, "jev-build").isEnabled(), send: await sendState(page),
        projection: await jt(page, "jev-projection").count(), cards: await jt(page, "jev-result-card").count(),
        history: await jt(page, "jev-sends").count(),
        structure: await page.evaluate(() => { const node = document.getElementById("mw-app-panel-structure");
          return node ? { shown: node.getAttribute("data-shown"), inert: node.inert } : null; }),
        tabs: await page.locator(".mw-app-tabs [role=tab]").evaluateAll(items => items.map(item => item.textContent.trim())),
        line: await globalLine(page),
      };
    }, async value => {
      assert.deepEqual(value.posts, [], "entering the tab posted");
      for (const route of ["jev/status", "jev/sends", "ligand/candidate_sets", "mutation_candidate_sets"])
        assert.ok(value.reads.some(item => item.endsWith(route)), `no GET ${route}: ${value.reads}`);
      assert.equal(value.consent, "off");
      assert.equal(value.consentChecked, false);
      const notice = value.notice.join("\n");
      // destination, provider policy, the cap, per-send approval of the exact body, and what each body carries (spec 3)
      for (const word of ["OpenRouter", "data_collection=deny", "zdr", "10", "정확한 본문", "리간드 후보 본문", "정규 SMILES",
        "stereo_flag", "PAINS", "변이 후보 본문", "서열 구간", "이웃 잔기", "거리", "보내지 않는 것", "API 키"])
        assert.ok(notice.includes(word), word);
      assert.equal(value.u2, U.U2);
      assert.equal(value.u3, U.U3);
      assert.deepEqual([value.cap.used, value.cap.remaining], ["0", String(SEND_CAP)]);
      assert.equal([value.kinds, value.sources, value.selection, value.projection, value.cards, value.history].join(","),
        "0,0,0,0,0,0");
      assert.equal(value.buildEnabled, false);
      assert.equal(value.send.enabled, false);
      assert.equal(value.send.confirmEnabled, false);
      assert.deepEqual(value.structure, { shown: "false", inert: true });
      assert.deepEqual(value.tabs, TAB_LABELS);
      assert.equal(value.line.badge, null);
      assert.equal(value.line.runText, A.run);
      return { ...value, notice: value.notice.length };
    });
  });

  let mutationBuilt = null;
  await rec_.part("consent-off", ["J-consent-off-block", "J-source-choice", "J-consent-toggle"], async () => {
    const sources = await rec_.step("F03-source", ["J-source-choice"], "Click 변이 후보 집합: both mutation sets of run A are " +
      "listed and none is chosen; click the 1UBQ set: its candidate rows load (nothing checked)", async () => {
      await jt(page, "jev-kind-mutation").check();
      await jt(page, "jev-sources").waitFor({ timeout: 30000 });
      const listed = await jev(page).locator('input[data-testid="jev-source"]').evaluateAll(items =>
        items.map(item => ({ handle: item.getAttribute("data-jev-source"), checked: item.checked })));
      await chooseSource(page, "mutation", A.sets.ubq.handle, A.sets.ubq.candidates, evidence);
      return { listed, rows: await rowKeys(page), count: await selectedCount(page) };
    }, async value => {
      assert.deepEqual(value.listed.map(item => item.handle).sort(), [A.sets.ubq.handle, A.sets.mq4.handle].sort());
      assert.ok(value.listed.every(item => !item.checked), "a set was chosen automatically");
      assert.equal(value.rows.length, A.sets.ubq.candidates);
      assert.ok(value.rows.every(row => !row.checked));
      assert.equal(value.count, 0);
      return { listed: value.listed.length, rows: value.rows.length };
    });
    mutationBuilt = await rec_.step("F04-consent-off", ["J-consent-off-block"], "Check 3 candidates, 보낼 내용 만들기: the " +
      "preview lists the server refusal consent_off; with the confirmation checked the send button stays closed", async () => {
      const keys = sources.rows ? (await rowKeys(page)).slice(0, 3).map(row => row.key) : [];
      await checkKeys(page, keys, evidence);
      const built = await build(page, A.run, evidence);
      const shown = await previewWhen(page, built.handle, item => item.blocked.length > 0, "preview with consent_off");
      await jt(page, "jev-confirm").check();
      return { keys, built, shown, send: await sendState(page) };
    }, async value => {
      assert.deepEqual(value.shown.blocked.map(item => item.code), ["consent_off"]);
      assert.ok(value.shown.blocked[0].text.includes("(consent_off)"));
      assert.equal(value.shown.blockedAttr, "true");
      assert.equal(value.send.confirmed, true);
      assert.equal(value.send.enabled, false);
      assert.ok(value.send.blocked.includes("(consent_off)"), value.send.blocked);
      assert.deepEqual(value.built.request.args, { source: A.sets.ubq.handle, candidates: value.keys.map(Number), filter: null });
      return { blocked: value.shown.blocked, send: value.send };
    });
    await rec_.step("F05-consent-toggle", ["J-consent-toggle"], "Click the consent switch on: the preview is read again " +
      "without refusals and the global line shows 과학 전송 허용 right after the run id; switch off: the mark goes away and " +
      "consent_off returns; switch on again", async () => {
      const on = await setConsent(page, A.run, true, evidence);
      const shownOn = await previewWhen(page, mutationBuilt.built.handle, item => item.blocked.length === 0, "preview unblocked");
      const lineOn = await waitFor(page, async () => { const line = await globalLine(page); return line.badge ? line : null; },
        "global mark", 15000);
      const sendOn = await sendState(page);
      await setConsent(page, A.run, false, evidence);
      const shownOff = await previewWhen(page, mutationBuilt.built.handle, item => item.blocked.length > 0, "preview blocked");
      const lineOff = await waitFor(page, async () => { const line = await globalLine(page); return line.badge ? null : line; },
        "global mark gone", 15000);
      await setConsent(page, A.run, true, evidence);
      await previewWhen(page, mutationBuilt.built.handle, item => item.blocked.length === 0, "preview unblocked again");
      return { on: on.enabled, shownOn: shownOn.blocked, lineOn, sendOn, shownOff: shownOff.blocked, lineOff,
        status: await readApi(page, `/runs/${A.run}/jev/status`) };
    }, async value => {
      assert.deepEqual(value.shownOn, []);
      assert.deepEqual(value.lineOn.badge, { text: "과학 전송 허용", consent: "on", afterRun: true, title: value.lineOn.badge.title });
      assert.equal(value.lineOn.runText, A.run);
      assert.equal(value.sendOn.enabled, true);
      assert.deepEqual(value.shownOff.map(item => item.code), ["consent_off"]);
      assert.equal(value.lineOff.badge, null);
      assert.equal(value.lineOff.runText, A.run);
      assert.equal(value.status.enabled, true);
      assert.equal(value.status.used, 0);
      return { lineOn: value.lineOn, lineOff: value.lineOff };
    });
  });

  // ---- the 20-candidate cap, preview identity, confirmation, good send
  let first = null;
  await rec_.part("cap-and-good", ["J-candidate-limit", "J-preview-match", "J-confirm-required", "J-send-good",
    "J-bytes-equal"], async () => {
    const twenty = await rec_.step("F06-twenty", ["J-candidate-limit"], "Check candidates up to 20/20; click the 21st: it " +
      "stays unchecked and the area says why; 20 remain", async () => {
      const rows = await rowKeys(page);
      const want = rows.slice(0, MAX_CANDIDATES).map(row => row.key);
      await checkKeys(page, want.filter(key => !rows.find(row => row.key === key).checked), evidence);
      const full = await jt(page, "jev-selection-full").count();
      const extra = rows[MAX_CANDIDATES].key;
      await candidateBox(page, extra).click();
      control(evidence, "jev-candidate-21st", { key: extra });
      await jt(page, "jev-selection-refused").waitFor({ timeout: 10000 });
      const after = await rowKeys(page);
      return { want, extra, full, refused: clean(await jt(page, "jev-selection-refused").textContent()),
        count: await selectedCount(page), extraRow: after.find(row => row.key === extra),
        checked: after.filter(row => row.checked).map(row => row.key) };
    }, async value => {
      assert.equal(value.full, 1);
      assert.equal(value.count, MAX_CANDIDATES);
      assert.deepEqual(value.checked, value.want);
      assert.equal(value.extraRow.checked, false);
      assert.ok(value.refused.includes(`${MAX_CANDIDATES}개`), value.refused);
      assert.equal(value.extraRow.blocked, value.refused);
      return { count: value.count, refused: value.refused, extra: value.extra };
    });
    const built = await rec_.step("F07-preview", ["J-preview-match"], "보낼 내용 만들기 with 20: open the exact body; its text " +
      "= the server preview string, SHA-256 and bytes computed here = shown = stored projection; the alias table = the " +
      "stored selection (m01–m20, candidate index order); the question is the stored fixed wording", async () => {
      const made = await build(page, A.run, evidence);
      const bodyFolded = !(await jt(page, "jev-preview-body-details").evaluate(node => node.open));
      await jt(page, "jev-preview-body-details").locator("summary").click();
      control(evidence, "jev-preview-body-details", { opened: true });
      const shown = await previewShown(page);
      const stored = storedObject(runsDir, A.run, made.handle);
      return { made, shown, stored, bodyFolded };
    }, async value => {
      assert.equal(value.bodyFolded, true, "the exact body was not folded at first");
      const identity = previewIdentity(value.shown, value.made, value.stored);
      assert.deepEqual(value.made.request.args.candidates, twenty.want.map(Number));
      assert.deepEqual(value.stored.selection.map(item => item.alias),
        Array.from({ length: MAX_CANDIDATES }, (_, i) => `m${String(i + 1).padStart(2, "0")}`));
      assert.equal(value.shown.question, value.made.preview.question.instructions);
      assert.equal(value.shown.previous, 0);
      assert.deepEqual(value.shown.blocked, []);
      return identity;
    });
    await rec_.step("F08-confirm", ["J-confirm-required"], "Without the confirmation the send button is closed with the " +
      "confirmation reason; check it: the button opens", async () => {
      const unchecked = await sendState(page);
      await jt(page, "jev-confirm").check();
      control(evidence, "jev-confirm", { checked: true });
      return { unchecked, checked: await sendState(page) };
    }, async value => {
      assert.equal(value.unchecked.confirmed, false);
      assert.equal(value.unchecked.enabled, false);
      assert.ok(value.unchecked.blocked.includes("확인 체크"), value.unchecked.blocked);
      assert.equal(value.checked.enabled, true);
      return value;
    });
    first = await rec_.step("F09-good", ["J-send-good", "J-bytes-equal"], "이 내용을 JEV로 보냅니다 (fixture good): " +
      "completed; the card = the stored proposal (alias, local notation, confidence, model, usage, folded per-candidate " +
      "values in the sent order, J1–J4 and J6); the bytes the transport received = the preview = the prepared audit",
    async () => {
      const sent = await confirmAndSend(page, A.run, { control: controlDir, script: "good" }, evidence);
      const shown = await readCard(page, sent.record.send_id);
      return { sent, shown, wording: await wordingCheck(page, "good card", evidence) };
    }, async value => {
      assert.deepEqual(value.wording, []);
      const record = value.sent.record;
      assert.equal(record.status, "completed");
      const choice = storedObject(runsDir, A.run, record.choice_handle);
      const projection = storedObject(runsDir, A.run, built.made.handle);
      const card = cardMatches(value.shown, record, choice, projection);
      assert.ok(card.reported === "true");
      assert.equal(value.shown.foldedBefore, true, "the per-candidate values were not folded at first");
      const calls = fixtureCalls(controlDir);
      const call = calls.at(-1);
      assert.equal(call.script, "good");
      assert.equal(call.bodySha256, built.made.preview.body_sha256, "transport bytes differ from the preview");
      assert.equal(call.bodyBytes, built.made.preview.body_bytes);
      assert.equal(call.authorizationIsSentinel, true);
      const prepared = preparedMatches(runsDir, A.run, record.send_id, built.shown.body, built.made.preview.body_sha256);
      assert.equal(prepared.dispatched, 1);
      assert.equal(choice.answer.choice_alias, call.response.answers.candidate_choice.choice);
      assert.deepEqual(choice.answer.probabilities, call.response.answers.candidate_choice.probabilities);
      return { card, prepared, transport: { sha256: call.bodySha256, bytes: call.bodyBytes } };
    });
    first = { ...first, built };
  });

  // ---- same body again, report
  await rec_.part("resend-report", ["J-resend", "J-report"], async () => {
    const again = await rec_.step("F10-resend", ["J-resend"], "Same body again (fixture good_no_extras): the preview " +
      "counts 1 earlier send; a second, separate proposal; the history lists both in time order with U1 and no merged " +
      "line; the new card says 보고 없음 for the values it did not get", async () => {
      const shownBefore = await previewWhen(page, first.built.made.handle, item => item.previous === 1, "previous sends 1");
      const sent = await confirmAndSend(page, A.run, { control: controlDir, script: "good_no_extras" }, evidence);
      const shown = await readCard(page, sent.record.send_id);
      const rows = await historyWhen(page, items => items.some(row => row.sendId === sent.record.send_id &&
        row.status === "completed"), "second send listed");
      return { previous: shownBefore.previous, sent, shown, rows,
        u1: await jt(page, "jev-note-u1").textContent(),
        history: clean((await jarea(page, "history").innerText()).split(U.U1).join(" ")),
        wording: await wordingCheck(page, "same body again", evidence) };
    }, async value => {
      assert.deepEqual(value.wording, []);
      assert.equal(value.previous, 1);
      const record = value.sent.record;
      assert.equal(record.status, "completed");
      assert.notEqual(record.send_id, first.sent.record.send_id);
      assert.notEqual(record.choice_handle, first.sent.record.choice_handle);
      const choice = storedObject(runsDir, A.run, record.choice_handle);
      const projection = storedObject(runsDir, A.run, first.built.made.handle);
      cardMatches(value.shown, record, choice, projection);
      assert.equal(value.shown.confidence, NOT_REPORTED_TEXT);
      assert.deepEqual(value.rows.map(row => row.sendId), [first.sent.record.send_id, record.send_id]);
      assert.deepEqual(value.rows.map(row => row.status), ["completed", "completed"]);
      assert.equal(value.u1, U.U1);
      assert.ok(!/합계|다수|평균|최신/.test(value.history), "a merged or summary line in the history");
      return { rows: value.rows.map(row => row.status) };
    });
    await rec_.step("F11-report", ["J-report"], "보고서 만들기 on the first send's row: saved; 지식·보고서 list shows JEV 판정 " +
      "보고서; clicking it shows the saved Markdown (fixed sentences, no per-candidate values)", async () =>
      makeReport(page, A.run, first.sent.record.choice_handle, evidence), async value =>
      reportMatches(value, storedObject(runsDir, A.run, first.sent.record.choice_handle), first.sent.record.choice_handle,
        evidence, storedObject(runsDir, A.run, first.built.made.handle)));
    void again;
  });

  // ---- ligand: filter, failures, late reply
  let ligandBuilt = null;
  await rec_.part("ligand-failures-late", ["J-ligand-filter", "J-failed-alias", "J-failed-model", "J-late"], async () => {
    ligandBuilt = await rec_.step("F12-ligand-filter", ["J-ligand-filter"], "Click 리간드 후보 집합 and the run's set; type " +
      "heavy-atom max = the lowest stored value, 필터 적용: rows refused by the filter cannot be checked; 필터 통과만 보기 shows " +
      "only passing rows; check two, 보낼 내용 만들기 (the filter goes with the request)", async () => {
      await chooseSource(page, "ligand", A.sets.ligand.handle, A.sets.ligand.candidates, evidence);
      const page0 = await readApi(page, `/runs/${A.run}/ligand/candidate_sets/rows?handle=${enc(A.sets.ligand.handle)}` +
        "&offset=0&limit=100");
      const heavy = page0.rows.map(row => row.candidate.properties.heavy_atoms);
      const bound = Math.min(...heavy);
      await jt(page, "jev-filter-heavy_atoms-max").fill(String(bound));
      await jt(page, "jev-filter-apply").click();
      control(evidence, "jev-filter-apply", { heavy_atoms_max: bound });
      const passing = page0.rows.filter(row => row.candidate.properties.heavy_atoms <= bound).length;
      const filtered = await waitFor(page, async () => {
        const rows = await tableRows(page, "ligand", page0.rows.length, "filtered rows");
        return rows.every(row => row.passes === "true" || row.passes === "false") ? rows : null;
      }, "filter applied", 30000);
      const disabled = await jev(page).locator('tr[data-passes-all="false"] input[data-testid="jev-candidate"]').evaluateAll(
        items => items.map(item => item.disabled));
      await jt(page, "jev-passes-only").check();
      control(evidence, "jev-passes-only", { checked: true });
      const only = await waitFor(page, async () => {
        const rows = await tableRows(page, "ligand", passing, "passing rows");
        return rows.every(row => row.passes === "true") ? rows : null;
      }, "passes only", 30000);
      const count = jt(page, "jev-candidate-count");
      const counts = { total: await count.getAttribute("data-total"), passing: await count.getAttribute("data-passing"),
        hidden: await count.getAttribute("data-hidden") };
      const keys = only.slice(0, 2).map(row => row.key);
      assert.equal(keys.length, 2, "fewer than two passing candidates");
      await checkKeys(page, keys, evidence);
      assert.equal(await selectedCount(page), 2);
      const made = await build(page, A.run, evidence);
      const shown = await previewShown(page);
      return { bound, heavy: Object.fromEntries(page0.rows.map(row => [row.candidate.id, row.candidate.properties.heavy_atoms])),
        filtered, disabled, only, counts, keys, made, shown, stored: storedObject(runsDir, A.run, made.handle) };
    }, async value => {
      for (const row of value.filtered) assert.equal(row.passes, String(value.heavy[row.key] <= value.bound), row.key);
      assert.ok(value.disabled.length > 0 && value.disabled.every(Boolean), "a refused row can be checked");
      const passing = Object.values(value.heavy).filter(item => item <= value.bound).length;
      assert.equal(value.only.length, passing);
      assert.deepEqual([value.counts.total, value.counts.passing, value.counts.hidden],
        [String(Object.keys(value.heavy).length), String(passing), String(Object.keys(value.heavy).length - passing)]);
      assert.equal(value.made.request.args.filter.ranges.heavy_atoms.max, value.bound);
      assert.deepEqual(value.made.request.args.candidates, value.keys);
      assert.equal(value.stored.filter.ranges.heavy_atoms.max, value.bound);
      const identity = previewIdentity(value.shown, value.made, value.stored);
      const state = JSON.parse(value.shown.body).state;
      assert.deepEqual(Object.keys(state).sort(), ["candidates", "parent", "property_methods", "schema", "task",
        "values_note"]);
      const keys = [];
      (function walk(item) {
        if (Array.isArray(item)) item.forEach(walk);
        else if (item && typeof item === "object") for (const [key, inner] of Object.entries(item)) { keys.push(key); walk(inner); }
      })(state);
      assert.deepEqual(keys.filter(key => /pocket|receptor|structure|coordinate|residue|neighbor/i.test(key)), [],
        "receptor or pocket fields in the ligand body");
      return { bound: value.bound, passing, identity };
    });
    await rec_.step("F13-alias-outside", ["J-failed-alias"], "Send (fixture alias_outside): failed response_invalid; the " +
      "result shows the reason only (no card, no number)", async () => {
      const sent = await confirmAndSend(page, A.run, { control: controlDir, script: "alias_outside" }, evidence);
      return { sent, reason: await reasonOnly(page, sent.record) };
    }, async value => {
      assert.deepEqual([value.sent.record.status, value.sent.record.reason_code], ["failed", "response_invalid"]);
      assert.equal(value.sent.record.choice_handle, null);
      reasonOnlyMatches(value.reason, value.sent.record);
      preparedMatches(runsDir, A.run, value.sent.record.send_id, ligandBuilt.shown.body, ligandBuilt.made.preview.body_sha256);
      assert.equal(fixtureCalls(controlDir).at(-1).bodySha256, ligandBuilt.made.preview.body_sha256);
      return value.reason;
    });
    await rec_.step("F14-model-mismatch", ["J-failed-model"], "Send (fixture model_mismatch): failed model_mismatch, reason " +
      "only", async () => {
      const sent = await confirmAndSend(page, A.run, { control: controlDir, script: "model_mismatch" }, evidence);
      return { sent, reason: await reasonOnly(page, sent.record) };
    }, async value => {
      assert.deepEqual([value.sent.record.status, value.sent.record.reason_code], ["failed", "model_mismatch"]);
      assert.equal(value.sent.record.served_model, null);
      reasonOnlyMatches(value.reason, value.sent.record);
      return value.reason;
    });
    await rec_.step("F15-late", ["J-late"], "Send (fixture slow); while the reply is held, click the consent switch off; then " +
      "let the reply go: completed and marked late (동의 끈 뒤 도착) with J7; the history row is marked; the global mark is " +
      "gone; switch on again", async () => {
      const sent = await confirmAndSend(page, A.run, { control: controlDir, script: "slow", during: async () => {
        await waitFor(page, async () => fs.existsSync(path.join(controlDir, "inflight.json")) ? true : null, "reply held", 15000);
        const sending = await jev(page).getAttribute("data-sending");
        await setConsent(page, A.run, false, evidence);
        const line = await globalLine(page);
        fs.writeFileSync(path.join(controlDir, "release"), "release\n");
        return { sending, line };
      } }, evidence);
      const shown = await readCard(page, sent.record.send_id);
      const rows = await historyWhen(page, items => items.some(row => row.sendId === sent.record.send_id &&
        row.late === "true"), "late send listed");
      const line = await globalLine(page);
      const wording = await wordingCheck(page, "late card", evidence);
      await setConsent(page, A.run, true, evidence);
      return { sent, shown, rows, line, wording };
    }, async value => {
      assert.deepEqual(value.wording, []);
      const record = value.sent.record;
      assert.equal(value.sent.extra.sending, "true");
      assert.deepEqual([record.status, record.late, record.late_reason], ["completed", true, "consent_off"]);
      const choice = storedObject(runsDir, A.run, record.choice_handle);
      const card = cardMatches(value.shown, record, choice, ligandBuilt.stored);
      assert.equal(card.late, true);
      assert.ok(value.shown.limitations.includes(J.J7));
      assert.equal(value.rows.find(row => row.sendId === record.send_id).late, "true");
      assert.equal(value.line.badge, null);
      assert.equal(fixtureCalls(controlDir).at(-1).released, true);
      return { late: value.shown.late, limitations: value.shown.limitations.length };
    });
  });

  // ---- the send cap (10 per run) on the 1MQ4 set (20 candidates)
  await rec_.part("cap", ["J-send-cap"], async () => {
    await rec_.step("F16-cap", ["J-send-cap"], "1MQ4 set, 20 candidates, 보낼 내용 만들기; five more sends (fixture good): " +
      "after the tenth the status shows 10 used / 0 left, the preview lists send_cap_exhausted and the send button stays " +
      "closed", async () => {
      await chooseSource(page, "mutation", A.sets.mq4.handle, A.sets.mq4.candidates, evidence);
      const keys = (await rowKeys(page)).slice(0, MAX_CANDIDATES).map(row => row.key);
      await checkKeys(page, keys, evidence);
      const made = await build(page, A.run, evidence);
      const identity = previewIdentity(await previewShown(page), made, storedObject(runsDir, A.run, made.handle));
      const used = Number((await readApi(page, `/runs/${A.run}/jev/status`)).used);
      const records = [];
      for (let i = used; i < SEND_CAP; i++) {
        await previewWhen(page, made.handle, item => item.blocked.length === 0 && item.previous === records.length,
          `preview before send ${i + 1}`);
        records.push((await confirmAndSend(page, A.run, { control: controlDir, script: "good" }, evidence)).record);
      }
      const shown = await previewWhen(page, made.handle, item => item.blocked.length > 0, "cap refusal shown");
      await jt(page, "jev-confirm").check().catch(() => undefined);
      await waitFor(page, async () => await jt(page, "jev-cap").getAttribute("data-used") === String(SEND_CAP) ? true : null,
        "cap text", 15000);
      return { identity, used, records, shown, send: await sendState(page),
        cap: { used: await jt(page, "jev-cap").getAttribute("data-used"), remaining: await jt(page, "jev-cap").getAttribute("data-remaining") },
        status: await readApi(page, `/runs/${A.run}/jev/status`), dispatched: dispatchCounts(runsDir)[A.run] };
    }, async value => {
      assert.equal(value.used, 5);
      assert.deepEqual(value.records.map(item => item.status), Array(SEND_CAP - value.used).fill("completed"));
      assert.deepEqual(value.shown.blocked.map(item => item.code), ["send_cap_exhausted"]);
      assert.equal(value.send.enabled, false);
      assert.ok(value.send.blocked.includes("(send_cap_exhausted)"), value.send.blocked);
      assert.deepEqual(value.cap, { used: String(SEND_CAP), remaining: "0" });
      assert.equal(value.status.used, SEND_CAP);
      assert.equal(value.dispatched, SEND_CAP);
      return { identity: value.identity, cap: value.cap, dispatched: value.dispatched };
    });
  });

  // ---- other tabs unchanged (run A)
  await rec_.part("other-tabs", ["J-other-tabs"], async () => {
    await rec_.step("F17-other-tabs", ["J-other-tabs"], "After every JEV action: 단백질 공학 and 리간드 설계·탐색 show the " +
      "same areas and the same digit-masked text, no JEV element and no POST on entry; back on 구조 분석 the viewer is the " +
      "same session and source", async () => {
      const protein = await tabSignature(page, "단백질 공학", "protein", log);
      const ligand = await tabSignature(page, "리간드 설계·탐색", "ligand", log);
      await selectTab(page, "구조 분석");
      const viewer = await viewerSnapshot(page);
      return { protein: sameSignature(before.protein, protein), ligand: sameSignature(before.ligand, ligand), viewer };
    }, async value => {
      for (const [name, item] of Object.entries({ protein: value.protein, ligand: value.ligand })) {
        assert.equal(item.areasEqual, true, `${name} areas changed`);
        assert.equal(item.textEqual, true, `${name} text changed: ${JSON.stringify(item.differing)}`);
        assert.equal(item.jevElements, 0);
        assert.deepEqual(item.posts, [], `${name} posted on entry`);
      }
      assert.equal(value.viewer.sessionId, viewerBefore.sessionId);
      assert.equal(value.viewer.sourceHandle, viewerBefore.sourceHandle);
      return { protein: value.protein.areasEqual, ligand: value.ligand.areasEqual, viewer: value.viewer.sessionId };
    });
  });

  // ---- run B: no usage → egress stopped; run C: HTTP 500
  await rec_.part("no-usage", ["J-no-usage-stop"], async () => {
    await rec_.step("F18-no-usage", ["J-no-usage-stop"], "Run B: consent on, 1UBQ set, 3 candidates, send (fixture " +
      "no_usage): completed with every usage value 알 수 없음; the run's egress stops (usage_unknown) and the preview lists " +
      "egress_stopped; the send button stays closed", async () => {
      await chooseRun(page, B.run);
      await openKnowledge(page);
      await setConsent(page, B.run, true, evidence);
      await chooseSource(page, "mutation", B.sets.ubq.handle, B.sets.ubq.candidates, evidence);
      await checkKeys(page, (await rowKeys(page)).slice(0, 3).map(row => row.key), evidence);
      const made = await build(page, B.run, evidence);
      const sent = await confirmAndSend(page, B.run, { control: controlDir, script: "no_usage" }, evidence);
      const shown = await readCard(page, sent.record.send_id);
      const blocked = await previewWhen(page, made.handle, item => item.blocked.length > 0, "egress stop shown");
      await waitFor(page, async () => (await jt(page, "jev-status-notes").count()) ? true : null, "status notes", 15000);
      return { made, sent, shown, blocked, send: await sendState(page),
        notes: clean(await jt(page, "jev-status-notes").textContent()), status: await readApi(page, `/runs/${B.run}/jev/status`),
        wording: await wordingCheck(page, "no usage, egress stopped", evidence) };
    }, async value => {
      assert.deepEqual(value.wording, []);
      const record = value.sent.record;
      assert.equal(record.status, "completed");
      assert.equal(record.usage.input_tokens, null);
      const choice = storedObject(runsDir, B.run, record.choice_handle);
      cardMatches(value.shown, record, choice, storedObject(runsDir, B.run, value.made.handle));
      assert.deepEqual(Object.values(value.shown.usage), Array(4).fill(UNKNOWN_USAGE_TEXT));
      assert.deepEqual(value.blocked.blocked.map(item => item.code), ["egress_stopped"]);
      assert.equal(value.send.enabled, false);
      assert.ok(value.notes.includes("(usage_unknown)"), value.notes);
      assert.equal(value.status.egress_stop_reason, "usage_unknown");
      return { usage: value.shown.usage, blocked: value.blocked.blocked, notes: value.notes };
    });
  });
  await rec_.part("http-500", ["J-failed-http"], async () => {
    await rec_.step("F19-http-500", ["J-failed-http"], "Run C: consent on, 1UBQ set, 2 candidates, send (fixture HTTP " +
      "500): failed provider_http_error; the result shows the reason only", async () => {
      await chooseRun(page, C.run);
      await openKnowledge(page);
      await setConsent(page, C.run, true, evidence);
      await chooseSource(page, "mutation", C.sets.ubq.handle, C.sets.ubq.candidates, evidence);
      await checkKeys(page, (await rowKeys(page)).slice(0, 2).map(row => row.key), evidence);
      await build(page, C.run, evidence);
      const sent = await confirmAndSend(page, C.run, { control: controlDir, script: "http_500" }, evidence);
      return { sent, reason: await reasonOnly(page, sent.record), status: await readApi(page, `/runs/${C.run}/jev/status`),
        wording: await wordingCheck(page, "HTTP 500 reason", evidence) };
    }, async value => {
      assert.deepEqual(value.wording, []);
      assert.deepEqual([value.sent.record.status, value.sent.record.reason_code], ["failed", "provider_http_error"]);
      assert.equal(value.sent.record.choice_handle, null);
      reasonOnlyMatches(value.reason, value.sent.record);
      return { reason: value.reason, egressStop: value.status.egress_stop_reason };
    });
  });

  // ---- wording (screen at the end of each run part, report, scripted replies)
  const replies = fixtureCalls(controlDir).slice(callsBefore);
  for (const call of replies) evidence.wording.push({ label: `fixture reply ${call.n}`, kind: "reply",
    found: forbiddenWords(strings(call.response ?? {}).join("\n")) });
  evidence.fixture = { calls: replies.length, scripts: replies.map(call => call.script), statuses: replies.map(call => call.status),
    sentinelAuthorization: replies.every(call => call.authorizationIsSentinel === true),
    bodySha256: replies.map(call => call.bodySha256) };
  evidence.dispatchCounts = dispatchCounts(runsDir);
}

// ------------------------------------------------------------------ mode live (the plan; also the fixture rehearsal)
/** Choose `run` in the rail, record the other tabs before any JEV action there, then open the knowledge tab. */
async function enterRun(page, run, signatures, log) {
  await chooseRun(page, run);
  signatures[run] = { protein: await tabSignature(page, "단백질 공학", "protein", log),
    ligand: await tabSignature(page, "리간드 설계·탐색", "ligand", log) };
  await openKnowledge(page);
}

/** The plan's pre-checks (spec 11 "실서버로" screen cases that need no call): real input on the real screen before
 * the first send of the plan; nothing is sent. Observation only; preChecksMatch judges it. */
async function preChecks(page, runsDir, run, set, spec, evidence, log) {
  const since = Date.now();
  const dispatchedBefore = dispatchCounts(runsDir)[run] ?? 0;
  await setConsent(page, run, true, evidence);
  await chooseSource(page, spec.kind, set.handle, set.candidates, evidence);
  await uncheckAll(page);
  const rows = await rowKeys(page);
  assert.ok(rows.length > MAX_CANDIDATES, `the ${spec.set} set needs more than ${MAX_CANDIDATES} candidate rows`);
  const want = rows.slice(0, MAX_CANDIDATES).map(row => row.key);
  await checkKeys(page, want, evidence);
  const full = await jt(page, "jev-selection-full").count();
  const extra = rows[MAX_CANDIDATES].key;
  await candidateBox(page, extra).click();
  control(evidence, "jev-candidate-21st", { key: extra });
  await jt(page, "jev-selection-refused").waitFor({ timeout: 10000 });
  const capped = await rowKeys(page);
  const cap = { full, refused: clean(await jt(page, "jev-selection-refused").textContent()), count: await selectedCount(page),
    extraRow: capped.find(row => row.key === extra), checked: capped.filter(row => row.checked).map(row => row.key) };
  for (const key of want.slice(spec.keep)) {
    await candidateBox(page, key).uncheck();
    control(evidence, "jev-candidate-uncheck", { key });
  }
  const reduced = { count: await selectedCount(page),
    checked: (await rowKeys(page)).filter(row => row.checked).map(row => row.key) };
  const built = await build(page, run, evidence);
  const shownOn = await previewWhen(page, built.handle, item => item.blocked.length === 0, "preview without refusals");
  const stored = storedObject(runsDir, run, built.handle);
  const unconfirmed = await sendState(page);
  await setConsent(page, run, false, evidence);
  const shownOff = await previewWhen(page, built.handle, item => item.blocked.length > 0, "preview with consent_off");
  const lineOff = await waitFor(page, async () => { const line = await globalLine(page); return line.badge ? null : line; },
    "global mark gone", 15000);
  await jt(page, "jev-confirm").check();
  control(evidence, "jev-confirm", { checked: true });
  const offConfirmed = await sendState(page);
  await jt(page, "jev-confirm").uncheck();
  control(evidence, "jev-confirm", { checked: false });
  await setConsent(page, run, true, evidence);
  const shownBack = await previewWhen(page, built.handle, item => item.blocked.length === 0, "preview without refusals again");
  const lineOn = await waitFor(page, async () => { const line = await globalLine(page); return line.badge ? line : null; },
    "global mark back", 15000);
  return { want, extra, cap, reduced, built, shownOn, stored, unconfirmed, shownOff, lineOff, offConfirmed, shownBack,
    lineOn, back: await sendState(page), wording: await wordingCheck(page, "pre-checks", evidence),
    sendPosts: posts(log, since).filter(item => item.endsWith("/jev/sends")),
    dispatched: { before: dispatchedBefore, after: dispatchCounts(runsDir)[run] ?? 0 } };
}
function preChecksMatch(value, spec) {
  // the 21st candidate: refused with its reason, 20 stay checked; then reduced to `keep`
  assert.equal(value.cap.full, 1);
  assert.equal(value.cap.count, MAX_CANDIDATES);
  assert.deepEqual(value.cap.checked, value.want);
  assert.equal(value.cap.extraRow.checked, false);
  assert.ok(value.cap.refused.includes(`${MAX_CANDIDATES}개`), value.cap.refused);
  assert.equal(value.cap.extraRow.blocked, value.cap.refused);
  const kept = value.want.slice(0, spec.keep);
  assert.equal(value.reduced.count, spec.keep);
  assert.deepEqual(value.reduced.checked, kept);
  // the body of the kept candidates: preview identity; no refusal while consent is on
  const identity = previewIdentity(value.shownOn, value.built, value.stored);
  assert.deepEqual(value.built.request.args.candidates, kept.map(key => spec.kind === "mutation" ? Number(key) : key));
  assert.deepEqual(value.shownOn.blocked, []);
  // without the confirmation the send button is closed with that reason
  assert.equal(value.unconfirmed.confirmed, false);
  assert.equal(value.unconfirmed.enabled, false);
  assert.ok(value.unconfirmed.blocked.includes("확인 체크"), value.unconfirmed.blocked);
  // consent off: consent_off in the preview, the global mark gone, the button closed even with the confirmation
  assert.deepEqual(value.shownOff.blocked.map(item => item.code), ["consent_off"]);
  assert.ok(value.shownOff.blocked[0].text.includes("(consent_off)"), value.shownOff.blocked[0].text);
  assert.equal(value.shownOff.blockedAttr, "true");
  assert.equal(value.lineOff.badge, null);
  assert.equal(value.offConfirmed.confirmed, true);
  assert.equal(value.offConfirmed.enabled, false);
  assert.ok(value.offConfirmed.blocked.includes("(consent_off)"), value.offConfirmed.blocked);
  // consent on again: no refusal, the mark back, the button closed for the (unchecked) confirmation only
  assert.deepEqual(value.shownBack.blocked, []);
  assert.equal(value.lineOn.badge.text, "과학 전송 허용");
  assert.equal(value.back.confirmed, false);
  assert.equal(value.back.enabled, false);
  assert.ok(value.back.blocked.includes("확인 체크") && !value.back.blocked.includes("(consent_off)"), value.back.blocked);
  assert.deepEqual(value.wording, []);
  // nothing was sent
  assert.deepEqual(value.sendPosts, [], "a send request during the pre-checks");
  assert.equal(value.dispatched.after, value.dispatched.before, "a dispatch event during the pre-checks");
  return { set: spec.set, kind: spec.kind, refused: value.cap.refused, kept: spec.keep, identity,
    blockedOff: value.shownOff.blocked.map(item => item.code), unconfirmed: value.unconfirmed.blocked,
    offConfirmed: value.offConfirmed.blocked, back: value.back.blocked, sendRequests: value.sendPosts.length,
    dispatched: value.dispatched };
}

async function modeLive(session, input, setup, rec_, evidence, log) {
  const { page } = session;
  const runsDir = input["runs-dir"];
  const plan = JSON.parse(fs.readFileSync(input.plan, "utf8"));
  const controlDir = input.control;
  const rehearsal = !!controlDir;
  if (rehearsal) {
    const server = JSON.parse(fs.readFileSync(path.join(controlDir, "server.json"), "utf8"));
    assert.equal(server.fixture, true, "rehearsal needs the fixture server");
    evidence.fixtureLabels.push(PROCESS_NOTE);
  }
  assert.ok(Number.isInteger(plan.maxDispatch) && plan.maxDispatch >= 1, "plan.maxDispatch");
  assert.ok(Number.isInteger(plan.maxPerRun) && plan.maxPerRun >= 1 && plan.maxPerRun <= 3, "plan.maxPerRun");
  const checks = plan.preChecks ?? null;
  assert.ok(checks === null || (setup.runs[checks.run]?.sets?.[checks.set] && ["ligand", "mutation"].includes(checks.kind) &&
    Number.isInteger(checks.keep) && checks.keep >= 1 && checks.keep < MAX_CANDIDATES), "plan.preChecks");
  evidence.plan = { entries: plan.entries.map(item => item.id), maxDispatch: plan.maxDispatch, maxPerRun: plan.maxPerRun,
    preChecks: checks, rehearsal };
  evidence.runs = Object.fromEntries(Object.entries(setup.runs).map(([key, value]) => [key, value.run]));
  await waitForBoot(page);
  const caseId = rehearsal ? "J-live-rehearsal" : "JL-live";
  const built = {};
  const signatures = {};
  let current = null;
  let stop = null;
  if (checks !== null) {
    const run = setup.runs[checks.run].run;
    const done = await rec_.part("pre-checks", [caseId], () => rec_.step("P-pre-checks", [caseId], `Before the first send ` +
      `(run ${checks.run}, ${checks.kind} set ${checks.set}; nothing is sent): consent on; 20 candidates checked and the ` +
      `21st click refused (unchecked, the reason shown, 20 kept), then ${checks.keep} kept; 보낼 내용 만들기 and the preview ` +
      "identity; without the confirmation the send button is closed with that reason; consent off: consent_off in the " +
      "preview, the global mark gone and the button closed even with the confirmation checked; confirmation unchecked " +
      "and consent on again: no refusal, the mark back, the button closed for the confirmation only; no send request " +
      "and no dispatch event", async () => {
      if (current !== run) { await enterRun(page, run, signatures, log); current = run; }
      return preChecks(page, runsDir, run, setup.runs[checks.run].sets[checks.set], checks, evidence, log);
    }, async value => {
      evidence.preChecks = preChecksMatch(value, checks);
      return evidence.preChecks;
    }));
    if (done === null) stop = "the pre-checks failed (nothing sent)";
  }
  for (const entry of plan.entries) {
    if (stop) { evidence.sends.push({ entry: entry.id, skipped: stop }); continue; }
    const runInfo = setup.runs[entry.run];
    const run = runInfo.run;
    const done = await rec_.part(`send-${entry.id}`, [caseId], () => rec_.step(`P-${entry.id}`, [caseId], `Plan entry ` +
      `${entry.id}: run ${entry.run}, ${entry.resend ? `same body as ${entry.resend}` : `${entry.kind} set ${entry.set}, ` +
      `first ${entry.pick.first} candidates`}; consent on, 보낼 내용 만들기, preview identity, confirmation, one send` +
      `${rehearsal ? " (fixture good)" : ""}; the result shown as stored (a card with its per-candidate values folded at ` +
      "first, or the reason only); the send row is recorded as soon as the record arrives", async () => {
      if (current !== run) { await enterRun(page, run, signatures, log); current = run; }
      await setConsent(page, run, true, evidence);
      let made;
      if (entry.resend) {
        made = built[entry.resend];
        assert.ok(made && made.run === run, `resend ${entry.resend} must be an earlier entry of the same run`);
        assert.equal(await jt(page, "jev-preview").getAttribute("data-projection-handle"), made.handle,
          "the resent body is not the one on screen");
      } else {
        await chooseSource(page, entry.kind, runInfo.sets[entry.set].handle, runInfo.sets[entry.set].candidates, evidence);
        await uncheckAll(page);
        const keys = (await rowKeys(page)).slice(0, entry.pick.first).map(row => row.key);
        assert.equal(keys.length, entry.pick.first, "not enough candidate rows");
        await checkKeys(page, keys, evidence);
        made = { ...(await build(page, run, evidence)), run };
        built[entry.id] = made;
      }
      const shown = await previewWhen(page, made.handle, () => true, "preview");
      const stored = storedObject(runsDir, run, made.handle);
      const identity = previewIdentity(shown, made, stored);
      if (shown.blocked.length) return { entry: entry.id, run, blocked: shown.blocked.map(item => item.code), identity };
      // guard right before the one click: every run of this runs folder, and this run
      const counts = dispatchCounts(runsDir);
      const total = Object.values(counts).reduce((sum, item) => sum + item, 0);
      if (total >= plan.maxDispatch || (counts[run] ?? 0) >= plan.maxPerRun)
        return { entry: entry.id, run, guard: { total, inRun: counts[run] ?? 0 }, identity };
      const row = { entry: entry.id, run, kind: stored.kind, aliases: identity.aliases, bodyBytes: identity.bodyBytes,
        bodySha256: identity.bodySha256, reservation: identity.reservation, dispatchedBefore: { total, inRun: counts[run] ?? 0 } };
      const sent = await confirmAndSend(page, run, { ...(rehearsal ? { control: controlDir, script: "good" } : {}),
        onRecord: record => {
          // kept at once: a later failed wait or check still leaves this send and its reason code in the evidence
          Object.assign(row, { sendId: record.send_id, status: record.status, reasonCode: record.reason_code,
            servedModel: record.served_model, usage: record.usage, late: record.late });
          evidence.sends.push(row);
        } }, evidence);
      const status = await readApi(page, `/runs/${run}/jev/status`);
      Object.assign(row, { egressStop: status.egress_stop_reason, statusUsed: status.used, budgetAfter: status.budget });
      const value = { entry: entry.id, run, sent, identity, body: shown.body, stored, row };
      if (sent.record.status === "completed") value.shown = await readCard(page, sent.record.send_id);
      else value.reason = row.reason = await reasonOnly(page, sent.record);
      if (entry.report && sent.record.status === "completed")
        value.report = await makeReport(page, run, sent.record.choice_handle, evidence,
          jev(page).locator(`[data-testid="jev-result-report"]${attr("data-choice-handle", sent.record.choice_handle)}`));
      value.wording = await wordingCheck(page, `after ${entry.id}`, evidence);
      return value;
    }, async value => {
      if (value.blocked) throw new Error(`the server refuses before the send: ${value.blocked.join(", ")}`);
      if (value.guard) throw new Error(`dispatch guard: ${JSON.stringify(value.guard)} (no send)`);
      const record = value.sent.record;
      const row = value.row;
      row.preparedSha256 = record.status === "rejected" ? null
        : preparedMatches(runsDir, value.run, record.send_id, value.body, value.identity.bodySha256).preparedSha256;
      if (rehearsal) {
        const call = fixtureCalls(controlDir).at(-1);
        assert.equal(call.bodySha256, value.identity.bodySha256);
        row.fixtureCall = call.n;
      }
      if (value.shown) {
        const choice = storedObject(runsDir, value.run, record.choice_handle);
        row.responseShape = { confidence: choice.answer.confidence !== null,
          probabilities: choice.answer.probabilities !== null,
          probabilityCount: choice.answer.probabilities === null ? 0 : Object.keys(choice.answer.probabilities).length };
        row.card = cardMatches(value.shown, record, choice, value.stored);
        assert.equal(row.card.foldedBefore, true);
        if (value.report) row.report = reportMatches(value.report, choice, record.choice_handle, evidence, value.stored);
      } else {
        reasonOnlyMatches(value.reason, record);
      }
      assert.deepEqual(value.wording, []);
      if (record.status !== "completed") throw new Error(`send ${entry.id} ended ${record.status}/${record.reason_code}`);
      if (row.egressStop) throw new Error(`egress stopped after ${entry.id}: ${row.egressStop}`);
      return row;
    }));
    if (done === null) stop = `stopped after ${entry.id} (see its row)`;
  }
  await rec_.part("live-other-tabs", [caseId], async () => {
    for (const [run, before] of Object.entries(signatures)) {
      await rec_.step(`P-other-tabs-${run.slice(4, 12)}`, [caseId], `Run ${run}: 단백질 공학 and 리간드 설계·탐색 unchanged ` +
        "(areas, digit-masked text, no JEV element, no POST on entry)", async () => {
        await chooseRun(page, run);
        return { protein: sameSignature(before.protein, await tabSignature(page, "단백질 공학", "protein", log)),
          ligand: sameSignature(before.ligand, await tabSignature(page, "리간드 설계·탐색", "ligand", log)) };
      }, async value => {
        for (const item of Object.values(value)) {
          assert.equal(item.areasEqual, true);
          assert.equal(item.textEqual, true, JSON.stringify(item.differing));
          assert.equal(item.jevElements, 0);
          assert.deepEqual(item.posts, []);
        }
        return { protein: value.protein.textEqual, ligand: value.ligand.textEqual };
      });
    }
  });
  evidence.dispatchCounts = dispatchCounts(runsDir);
  if (rehearsal) evidence.fixture = { calls: fixtureCalls(controlDir).length };
}

// ------------------------------------------------------------------ main
const RUNNERS = { fixture: modeFixture, live: modeLive };

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const setup = JSON.parse(fs.readFileSync(input.setup, "utf8"));
  const evidence = { schema: "m24_jev_evidence@1", mode: input.mode, rehearsal: input.mode === "live" && !!input.control,
    runs: {}, sends: [], fixtureLabels: [], partFailures: [], controls: {}, wording: [], startedAt: new Date().toISOString() };
  const session = await launchOffscreen({ url: input.url, artifacts: input.artifacts, interactive: false });
  const log = requestLog(session.page);
  const rec_ = recorder(session, input, evidence);
  let error = null;
  let proof = null;
  try {
    proof = await offscreenProof(session.app, session.page);
    await RUNNERS[input.mode](session, input, setup, rec_, evidence, log);
    if (input.mode === "fixture") await wordingCheck(session.page, "end of fixture mode", evidence);
  } catch (caught) {
    error = caught;
  } finally {
    try { proof = { ...await offscreenProof(session.app, session.page), atStart: proof }; } catch { /* keep the start proof */ }
    await session.close();
  }
  const cases = rec_.cases();
  const wordingOk = evidence.wording.length > 0 && evidence.wording.every(item => item.found.length === 0);
  if (input.mode === "fixture") {
    cases["J-wording"] = wordingOk ? "pass" : "fail";
    cases["J-no-egress-browser"] = proof && proof.nonLoopbackRequests === 0 ? "pass" : "fail";
  }
  const passed = !error && evidence.partFailures.length === 0 && offscreenComplete(proof) && proof.nonLoopbackRequests === 0 &&
    Object.keys(cases).length > 0 && Object.values(cases).every(value => value === "pass") && wordingOk;
  evidence.finishedAt = new Date().toISOString();
  evidence.error = error ? String(error.stack ?? error) : null;
  evidence.requestCount = log.length;
  evidence.fixtureLabels = [...new Set(evidence.fixtureLabels)];
  fs.writeFileSync(path.join(input.artifacts, "jev-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  fs.writeFileSync(path.join(input.artifacts, "jev-requests.jsonl"), log.map(row => JSON.stringify(row)).join("\n") + "\n");
  const harness = Object.fromEntries(["jev-flow.cjs", "driver.cjs", "main.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m24_case_ledger_row@1", mode: input.mode, rehearsal: evidence.rehearsal,
    evidenceKind: "real_electron_offscreen", status: passed ? "pass" : "fail", cases, runs: evidence.runs,
    sends: evidence.sends, preChecks: evidence.preChecks ?? null, plan: evidence.plan ?? null, fixture: evidence.fixture ?? null,
    dispatchCounts: evidence.dispatchCounts ?? null, fixtureLabels: evidence.fixtureLabels, controls: evidence.controls,
    wording: evidence.wording.map(item => ({ label: item.label, kind: item.kind, found: item.found.length })),
    buildId: buildId(), harness, offscreen: proof, externalRequestCount: proof ? proof.nonLoopbackRequests : null,
    partFailures: evidence.partFailures, error: evidence.error, evidenceFile: path.basename(rec_.file),
    startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, runs: evidence.runs, cases }) + "\n");
  if (error) process.stderr.write(`jev-flow ${input.mode} failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`jev-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, halfUp, expectedLimitations, forbiddenWords, FORBIDDEN, FIXED_LINES, J, U, MODES };
