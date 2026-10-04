"use strict";

// M21 mutation structure model offscreen QA (spec §9, §11). Real Electron offscreen page (isOffscreen, GPU/WebGL, paint).
// Every product mutation is a Playwright locator mouse/keyboard/file-chooser/select input. Observation is read-only:
// data attributes and text of the page, renderer request/response events, Electron paint frames, downloaded bytes, GET
// reads of the loopback API, the stored object payloads in <runs-dir>/<run>/events.jsonl (read-only file reads) and the
// process table (`ps`/`lsof`). Labeled renderer-route fixtures (held late responses) are recorded in the ledger and never
// produce a scientific value.
//
// Inputs: public 1UBQ (backend/tests/fixtures/public_1ubq.cif, the only local public structure that passes the M7
// preflight; no ligand) and the synthetic phenol SDF (backend/tests/fixtures/mutation_model/synthetic-phenol-ligand.sdf,
// SYNTHETIC-FIXTURE, for the same-condition docking only). The M20 candidate set uses the direct-residue source (ILE A:44,
// allowed W) so its only candidate is I44W. Expected values are the stored ones (API reads and the event-log payload);
// the harness rounds them with its own ROUND_HALF_UP on the decimal string (not the product helper).
//
// Mode (the full sequence: scripts/m21_offscreen_acceptance.py):
//   main  fresh root: no run → 1UBQ load + 전처리 → M20 direct-residue set (I44W) → "변이 구조 모델링" on the candidate
//         row → request validation → real modeling job (approval, start, done; 1 unit; not opened automatically) → open →
//         side-by-side = stored, contact table + paging = stored rows, both mmCIF downloads = structure_sha256, fixed
//         limitation sentences, report + downloads → same submission again (same job and handle, no new unit) → late
//         contact page → ligand SDF import (리간드 탭) and tab trip → same-condition docking (one action, two real qvina
//         jobs, 2-unit confirmation) → pair table → partial pair (one side cancelled) → wording/colour checks → cancel a
//         running modeling job → run switch with a held run A list response
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const { waitForViewer } = require("./normal-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const STRUCTURE = path.join(REPO, "backend/tests/fixtures/public_1ubq.cif");
const LIGAND_SDF = path.join(REPO, "backend/tests/fixtures/mutation_model/synthetic-phenol-ligand.sdf");
const MODES = ["main"];
const TAB = "단백질 공학";
const LIGAND_TAB = "리간드 설계·탐색";
const PROTOCOL = "openmm_mutation_model_v1";
const DOCKING_PROTOCOL = "qvina_dock_v1";
const M20_TOOL = "generate_mutation_candidates";
const SIDES = ["wild_type_reference", "mutant"];
const SIDE_LABEL = { wild_type_reference: "야생형 기준", mutant: "변이형" };
const RESIDUE_FIELDS = ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"];
// Main request: seed fixed by the person; cutoff 6.0 Å (inside 2.5–6.0) so the mutant contact table has more than one
// page (100 rows) and the pager is exercised.
const MODEL = { seed: "20261004", cutoff: "6.0", timeout: "240" };
const CANCEL_SEED = "7";
// Same-condition docking values (T1 preflight (d): ligand_range margin 8, seed 20261004, exhaustiveness 8; ~2 s each).
const PAIR = { margin: "8", seed: "20261004", exhaustiveness: "8", numModes: "9", energyRange: "3" };
const PARTIAL_SEED = "7";
const ACK_KEYS = ["keep_input_protonation", "tool_assigned_types_charges", "rigid_no_optimization"];
// Spec §4, verbatim, in the stored order L1, L2, L3, L4, L7, then L5 and L6 only when their condition holds.
const L = {
  L1: "변이 구조는 PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 모델이며 회전이성질체 탐색과 수렴을 주장하지 않는다.",
  L2: "OpenMM 전위는 각 구조의 Amber14-all + GBn2 암시 용매 값(kJ/mol)이며 서열이 다른 두 구조의 값은 서로 비교할 수 없고 ΔΔG·안정성·친화도가 아니다.",
  L3: "모델은 단백질만 포함하며 리간드·금속 이온·물·보조인자는 제외했다.",
  L4: "SASA는 리간드가 없는 단백질 모델의 변이 위치 잔기 값이다.",
  L7: "접촉은 중원자 사이 거리(Å)이며 수소결합이나 상호작용의 종류를 뜻하지 않는다.",
  L5: "변이한 잔기 밖에서 히스티딘·시스테인 양성자 상태가 두 구조에서 다르게 지정되었으므로 두 구조의 차이는 변이 하나만이 아니다.",
  L6: "변이형에는 야생형 기준에 없는 이황화 결합이 거리 기준으로 만들어졌다.",
};
const ALL_LIMITATIONS = Object.values(L);
const NO_RUN_REASON = "run이 없습니다. 구조 분석 탭에서 run을 먼저 고르세요.";
const SCORE_LABEL = "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)";
// No difference, change, rank, recommendation, stability, "better" or comparison arrow anywhere in the model panel.
// "최적화"/"최소화" (processes) are allowed; a line equal to a fixed limitation sentence is exempt; the score name is
// removed before the check.
const FORBIDDEN = /순위|추천|개선|증가|감소|안정성|ΔΔG|Δ|차이|변화량|최적(?!화)|최고|유망|좋은|나쁜|친화|\brank|\bbest|improv|recommend|optimal|stabili|delta|differen|better|worse|↑|↓|▲|▼|⬆|⬇/gi;
const ARROWS = /[↑↓▲▼⬆⬇→←]/;
const HOLD_LABEL = "QA held-response fixture (labeled renderer route; unchanged backend bytes released late)";
const PROVIDER_EVENT_TYPES = new Set(["egress", "egress_budget_settled", "viewer_dispatch_started"]);
const PROCESS_PATTERNS = ["openmm_mutation_worker.py", "docking_worker.py", "qvina2", "guardian.py"];
const L1_APPROVED = "승인을 기록했습니다. 작업 시작을 누르면 실제 계산이 실행됩니다.";

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const shortHandle = handle => handle.split("/").at(-1).slice(0, 12);
const attr = (name, value) => `[${name}="${String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"]`;
const sameResidue = (a, b) => !!a && !!b && RESIDUE_FIELDS.every(field => a[field] === b[field]);
const resShort = ref => `${ref.resname} ${ref.chain_auth}:${ref.seq_auth}${ref.icode}`;

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, "runs-dir": null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2);
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode) || !value["runs-dir"]) throw new Error(
    `Usage: mutation-model-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> --runs-dir <backend MW_RUNS_DIR> ` +
    "[--url http://127.0.0.1:3000]. Needs a fresh runs root, the fixed OpenMM/PDBFixer and the locked docking " +
    "environments. Full sequence: scripts/m21_offscreen_acceptance.py.");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  value.artifacts = path.resolve(value.artifacts);
  value["runs-dir"] = path.resolve(value["runs-dir"]);
  value.url = new URL("/", value.url).toString();
  return value;
}

/** ROUND_HALF_UP of the value's decimal string (independent of the product helper); no exponent forms expected. */
function halfUp(value, places) {
  const text = String(value);
  assert.ok(!/e/i.test(text), `exponent in ${text}`);
  const negative = text.startsWith("-");
  const [whole, frac = ""] = text.replace(/^-/, "").split(".");
  let scaled = BigInt(whole + frac.slice(0, places).padEnd(places, "0"));
  if (frac.length > places && frac[places] >= "5") scaled += 1n;
  if (scaled === 0n) return places ? `0.${"0".repeat(places)}` : "0";
  const body = scaled.toString().padStart(places + 1, "0");
  return `${negative ? "-" : ""}${places ? `${body.slice(0, -places)}.${body.slice(-places)}` : body}`;
}
/** The limitation sentences the stored result must carry (spec §4 order and conditions). */
function expectedLimitations(result) {
  const list = [L.L1, L.L2, L.L3, L.L4, L.L7];
  if (result.comparison.protonation_difference_count > 0) list.push(L.L5);
  if (result.comparison.new_disulfide_in_mutant) list.push(L.L6);
  return list;
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
async function unitsUsed(page, run) { return (await readApi(page, `/runs/${run}/budget`)).expensive_calls?.used ?? null; }
/** The stored object content: the object_created payload in the run's event log (read-only file read). */
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
const modelPath = (run, handle, tail = "") => `/runs/${run}/mutation_models/${enc(handle)}${tail}`;
async function modelCount(page, run) { return (await readApi(page, `/runs/${run}/mutation_models?offset=0&limit=100`)).total; }

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
    let body = null;
    if (request.method() === "POST") { try { body = request.postDataJSON(); } catch { body = null; } }
    rows.push({ at: Date.now(), method: request.method(), path: url.pathname, search: url.search,
      api: url.pathname.startsWith("/api/"), tool: body?.tool ?? null, protocol: body?.protocol_id ?? null });
  });
  return rows;
}

// ------------------------------------------------------------------ evidence
function recorder(session, input, evidence) {
  const { app, page, artifacts } = session;
  const file = path.join(artifacts, `mutation-model-${input.mode}.jsonl`);
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
      const html = await page.evaluate(() => document.querySelector('[data-testid="mutation-model-panel"]')?.outerHTML.slice(0, 120000) ?? "")
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
const evidenceRef = { value: null };
/** Every control used at least once, with what was observed right after. */
function control(id, observed) { (evidenceRef.value.controls[id] ??= []).push(observed); }

// ------------------------------------------------------------------ tabs, runs, structure screen (as mutation-flow.cjs)
const tabButton = (page, label) => page.locator(".mw-app-tabs").getByRole("tab", { name: label, exact: true });
async function selectTab(page, label) {
  await tabButton(page, label).click();
  await waitFor(page, async () => await tabButton(page, label).getAttribute("aria-selected") === "true", `${label} selected`, 10000);
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
  await selectTab(page, "구조 분석");
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
  await page.locator('input[type="file"]').first().click();
  await (await chooser).setFiles(file);
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).waitFor({ timeout: 30000 });
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    /\/commands$/.test(new URL(response.url()).pathname) && response.request().postDataJSON()?.tool === "load_structure",
  { timeout: 90000 });
  posted.catch(() => undefined); // a failed click must not leave an unhandled rejection
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).click();
  const loadArgs = (await posted).request().postDataJSON().args;
  const viewer = await waitForViewer(page, value => !!value.sourceHandle && value.sourceHandle !== before &&
    value.sourceHandle.includes("/structure/") && value.catalogReady === true, 90000);
  return { handle: viewer.sourceHandle, loadArgs: { model_index: loadArgs.model_index } };
}
async function prepareManual(page) {
  const back = page.getByRole("button", { name: "최신 구조로 돌아가기", exact: true });
  if (await back.isVisible().catch(() => false)) await back.click();
  const row = page.locator(".mw-workflow-row").filter({ has: page.getByRole("button", { name: "전처리", exact: true }) });
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    /\/commands$/.test(new URL(response.url()).pathname) && response.request().postDataJSON()?.tool === "prepare_structure",
  { timeout: 90000 });
  posted.catch(() => undefined); // a failed click must not leave an unhandled rejection
  await row.getByRole("button", { name: "전처리", exact: true }).click();
  const response = await posted;
  const body = await response.json();
  assert.equal(body.ok, true, `prepare failed: ${JSON.stringify(body).slice(0, 400)}`);
  const prepared = body.handle.handle;
  assert.match(prepared, /\/prepared_structure\//);
  await waitForViewer(page, value => value.sourceHandle === prepared && value.catalogReady === true, 90000);
  return { prepared, args: response.request().postDataJSON().args };
}

// ------------------------------------------------------------------ M20 candidate panel (as mutation-flow.cjs)
const m20 = page => page.locator('[data-testid="mutation-panel"]');
const m20Id = (page, id) => m20(page).locator(`[data-testid="${id}"]`);
async function m20Ready(page) {
  await waitFor(page, async () => await m20(page).locator('[data-mutation-area="sets"]').getAttribute("data-state") === "ready"
    && await m20(page).locator('[data-testid="mutation-structures"] input').first().isEnabled() ? true : null,
  "M20 lists ready", 60000);
}
async function m20CreateDirect(page, run, prepared) {
  await m20(page).locator(`label[data-mutation-structure="${prepared}"] input`).check();
  control("mutation-structures", { checked: prepared });
  const user = m20Id(page, "mutation-source-user");
  if (!await user.isChecked()) await user.click();
  control("mutation-source-user", { checked: true });
  const select = m20Id(page, "mutation-pick-user");
  const option = await waitFor(page, async () => {
    const found = await select.locator("option").evaluateAll(items => items.map(item => ({ value: item.value, text: item.textContent.trim() })));
    return found.find(item => item.text.startsWith("ILE A:44 ·")) ?? null;
  }, "ILE A:44 offered", 60000);
  await select.selectOption(option.value);
  await m20Id(page, "mutation-add-user").click();
  control("mutation-pick-user", { picked: option.text });
  await m20Id(page, "mutation-allowed-none").click();
  await m20Id(page, "mutation-allowed").getByRole("checkbox", { name: "허용 잔기 W", exact: true }).check();
  control("mutation-allowed", { checked: "W" });
  await waitFor(page, async () => await m20Id(page, "mutation-create").isEnabled() ? true : null, "후보 만들기 enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === M20_TOOL,
  { timeout: 120000 });
  posted.catch(() => undefined); // a failed click must not leave an unhandled rejection
  await m20Id(page, "mutation-create").click();
  control("mutation-create", { clicked: true });
  const response = await posted;
  const body = await response.json();
  assert.equal(body.ok, true, JSON.stringify(body).slice(0, 400));
  const handle = body.handle.handle;
  await m20(page).locator(`[data-testid="mutation-detail"][data-mutation-detail="${handle}"]`).waitFor({ timeout: 60000 });
  return { handle, args: response.request().postDataJSON().args };
}

// ------------------------------------------------------------------ model panel
const panel = page => page.locator('[data-testid="mutation-model-panel"]');
const mt = (page, id) => panel(page).locator(`[data-testid="${id}"]`);
const modelState = page => panel(page).getAttribute("data-model-state", { timeout: 2000 }).catch(() => null);
async function openTab(page) {
  await selectTab(page, TAB);
  await panel(page).waitFor({ timeout: 15000 });
}
async function waitListReady(page) {
  await waitFor(page, async () => await panel(page).locator('[data-mutation-model-area="list"]').getAttribute("data-state") === "ready"
    ? true : null, "model list ready", 60000);
}
async function requestErrors(page) {
  if (!await mt(page, "mutation-model-request-errors").count()) return [];
  return mt(page, "mutation-model-request-errors").locator("li").allInnerTexts();
}
async function jobView(page) {
  const job = mt(page, "mutation-model-job");
  if (!await job.count()) return null;
  return { id: await job.getAttribute("data-job-id"), status: await job.getAttribute("data-job-status"),
    approval: await job.getAttribute("data-approval-pending"), text: clean(await job.locator("p").first().textContent()) };
}
/**
 * Click 모델링 작업 제출 (real input); approve through 비싼 계산 승인 when asked, then 작업 시작; wait until the job
 * leaves the active states (or, with `until: "running"`, until it runs). Returns the phases, the backend job and budget.
 */
async function runModelJob(page, run, { until = "final" } = {}) {
  const phases = [];
  const before = await unitsUsed(page, run);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/jobs` && response.request().postDataJSON()?.protocol_id === PROTOCOL,
  { timeout: 120000 });
  posted.catch(() => undefined); // a failed click must not leave an unhandled rejection
  await mt(page, "mutation-model-submit").click();
  control("mutation-model-submit", { clicked: true });
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
  let approved = false, approvalNotice = null;
  if (first.phase === "awaiting_approval") {
    approvalNotice = clean(first.text);
    await mt(page, "mutation-model-job-approve").click();
    control("mutation-model-job-approve", { clicked: true });
    approved = true;
    await mt(page, "mutation-model-notice").filter({ hasText: L1_APPROVED }).waitFor({ timeout: 30000 });
    phases.push("approved");
  }
  const view = await jobView(page);
  if (view.status === "queued") {
    await waitFor(page, async () => await mt(page, "mutation-model-job-start").isEnabled() ? true : null, "작업 시작 enabled", 30000);
    await mt(page, "mutation-model-job-start").click();
    control("mutation-model-job-start", { clicked: true });
  }
  const finals = until === "running" ? ["running", "done", "failed", "cancelled", "interrupted"] : ["done", "failed", "cancelled", "interrupted"];
  const done = await waitFor(page, async () => {
    const value = await jobView(page);
    if (value && value.id === jobId && value.status !== phases.at(-1)) phases.push(value.status);
    return value && value.id === jobId && finals.includes(value.status) ? value : null;
  }, `model job ${until}`, 300000);
  const job = await readApi(page, `/runs/${run}/jobs/${enc(jobId)}`);
  return { jobId, request, submitted, phases, approved, approvalNotice, done, job, budgetBefore: before,
    budgetAfter: await unitsUsed(page, run) };
}
async function openModel(page, handle) {
  const radio = panel(page).locator(`label${attr("data-mutation-model", handle)} input`);
  await radio.waitFor({ timeout: 30000 });
  await radio.check();
  control("mutation-model-list", { checked: handle });
  await panel(page).locator(`[data-testid="mutation-model-detail"]${attr("data-model-handle", handle)}`).waitFor({ timeout: 60000 });
}
async function sideBySide(page) {
  return mt(page, "mutation-model-side-by-side").evaluate(table => ({
    headers: [...table.querySelectorAll("thead th")].map(th => th.textContent.trim()),
    rows: [...table.querySelectorAll("tbody tr")].map(tr => {
      const cells = [...tr.querySelectorAll("td")];
      const style = cell => { const s = getComputedStyle(cell); return { color: s.color, background: s.backgroundColor,
        weight: s.fontWeight, className: cell.className, inline: cell.getAttribute("style") }; };
      return { key: tr.getAttribute("data-row-key"), label: cells[0].textContent.trim(), trStyle: tr.getAttribute("style"),
        trClass: tr.className, values: Object.fromEntries(cells.slice(1).map(cell => [cell.getAttribute("data-side"), cell.textContent.trim()])),
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
    pager: !!node.querySelector('[data-testid="mutation-model-contacts-pager"]'),
    rows: [...node.querySelectorAll("tbody tr")].map(tr => ({ index: Number(tr.getAttribute("data-contact-index")),
      distance: tr.getAttribute("data-distance"), cells: [...tr.querySelectorAll("td")].map(td => td.textContent.trim()) })) }));
}
/** UI contact page = API page = the stored rows (event-log payload) of that side, cell by cell. */
async function checkContacts(page, run, handle, stored, side, pageNo) {
  const api = await readApi(page, modelPath(run, handle, `/contacts?structure=${side}&page=${pageNo}&page_size=100`));
  const view = await waitFor(page, async () => {
    const value = await contactView(page);
    return value && value.side === side && value.page === pageNo && value.rows.length === api.rows.length ? value : null;
  }, `contact page ${side} ${pageNo}`, 30000);
  const rows = stored.structures[side].contacts.rows;
  assert.equal(api.total, rows.length, "API total = stored rows");
  assert.equal(view.total, api.total);
  api.rows.forEach((row, i) => {
    const want = rows[(pageNo - 1) * 100 + i];
    assert.equal(row.index, (pageNo - 1) * 100 + i);
    assert.equal(row.distance_A, want.distance_A, `row ${row.index} distance stored`);
    assert.equal(row.atom_name, want.atom_name);
    assert.ok(sameResidue(row.partner_residue, want.partner_residue), `row ${row.index} partner residue`);
    assert.equal(row.partner_atom_name, want.partner_atom_name);
    const shown = view.rows[i];
    assert.equal(shown.index, row.index);
    assert.equal(shown.distance, String(row.distance_A));
    assert.deepEqual(shown.cells, [String(row.index + 1), `${row.atom_name} (${row.element})`, resShort(row.partner_residue),
      `${row.partner_atom_name} (${row.partner_element})`, `${halfUp(row.distance_A, 2)} Å`]);
  });
  const first = (pageNo - 1) * 100 + 1;
  assert.equal(view.count, `${SIDE_LABEL[side]}: 중원자 접촉 ${api.total}개 중 ${first}–${first + api.rows.length - 1}`);
  return { side, page: pageNo, total: api.total, rows: api.rows.length, pager: view.pager };
}
/** Panel text lines (innerText), forbidden words outside the fixed limitation sentences and the score name. */
async function panelWording(page, limitations) {
  const text = await panel(page).evaluate(node => node.innerText);
  const found = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || ALL_LIMITATIONS.includes(line) || limitations.includes(line)) continue;
    const checked = line.split(SCORE_LABEL).join("").split("qvina 점수(kcal/mol)").join("");
    for (const match of checked.matchAll(FORBIDDEN)) found.push({ word: match[0], line: line.slice(0, 200) });
  }
  return { found, chars: text.length };
}
/** Pair table as shown: headers, rows and per-side cells (score flag, text, style). */
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
      id: await node.getAttribute("data-job-id"), text: clean(await node.textContent()) }];
  })));
}
async function fillPair(page, sdfHandle, seed) {
  const source = panel(page).locator('label[data-pair-ligand-source="sdf"] input');
  await source.check();
  control("mutation-model-pair-ligand-source", { source: "sdf" });
  await mt(page, "mutation-model-pair-sdf").selectOption(sdfHandle);
  control("mutation-model-pair-sdf", { handle: sdfHandle });
  await panel(page).locator('label[data-pair-box="ligand_range"] input').check();
  control("mutation-model-pair-box-source", { source: "ligand_range" });
  const fill = async (id, value) => { await mt(page, id).fill(value); control(id, { value }); };
  await fill("mutation-model-pair-margin", PAIR.margin);
  await fill("mutation-model-pair-seed", seed);
  await fill("mutation-model-pair-exhaustiveness", PAIR.exhaustiveness);
  await fill("mutation-model-pair-num-modes", PAIR.numModes);
  await fill("mutation-model-pair-energy-range", PAIR.energyRange);
  for (const key of ACK_KEYS) {
    await panel(page).locator(`label[data-pair-ack="${key}"] input`).check();
    control(`mutation-model-pair-ack-${key}`, { checked: true });
  }
}
/** Tick the 2-unit confirmation, click 같은 조건 도킹 제출 once; the two POST /jobs (qvina) of that one click. */
async function submitPair(page, run, log) {
  const before = Date.now();
  const blockedBefore = { disabled: await mt(page, "mutation-model-pair-submit").isDisabled(),
    blocked: clean(await mt(page, "mutation-model-pair-blocked").textContent({ timeout: 2000 }).catch(() => "")) };
  await mt(page, "mutation-model-pair-units").check();
  control("mutation-model-pair-units", { checked: true });
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
    control("mutation-model-pair-submit", { clicked: true });
    await waitFor(page, async () => responses.length === 2 && responses.every(item => item.body) ? true : null, "two docking submissions", 60000);
  } finally { page.off("response", listener); }
  const posts = log.filter(row => row.at >= before && row.method === "POST" && row.protocol === DOCKING_PROTOCOL).length;
  // the 2-unit confirmation is asked again for the next action (unchecked once both submissions are answered)
  const units = await waitFor(page, async () => await mt(page, "mutation-model-pair-units").isChecked() ? null : "unchecked",
    "2-unit box unchecked after the submissions", 15000).catch(() => "still checked");
  return { blockedBefore, responses, posts, units };
}
/** Drive the saved pair jobs by the screen's own buttons (approve when asked, 남은 작업 차례로 시작) until both end. */
async function drivePair(page, ids, { cancelSide = null } = {}) {
  const actions = [];
  const deadline = Date.now() + 600000;
  let cancelled = false;
  while (Date.now() < deadline) {
    const jobs = await pairJobs(page);
    if (cancelSide && !cancelled && jobs[cancelSide]?.status === "queued") {
      const button = mt(page, `mutation-model-pair-cancel-${cancelSide}`);
      if (await button.isEnabled().catch(() => false)) {
        await button.click();
        control(`mutation-model-pair-cancel-${cancelSide}`, { clicked: true, statusBefore: "queued" });
        actions.push({ cancel: cancelSide, at: Date.now() });
        cancelled = true;
        continue;
      }
    }
    const terminal = SIDES.every(side => ["done", "failed", "cancelled", "interrupted"].includes(jobs[side]?.status));
    if (terminal) return { actions, jobs };
    if (await mt(page, "mutation-model-pair-approve").isVisible().catch(() => false) &&
        await mt(page, "mutation-model-pair-approve").isEnabled().catch(() => false)) {
      await mt(page, "mutation-model-pair-approve").click();
      control("mutation-model-pair-approve", { clicked: true });
      actions.push({ approve: true, at: Date.now() });
      await page.waitForTimeout(500);
      continue;
    }
    if ((!cancelSide || cancelled) && await mt(page, "mutation-model-pair-continue").isVisible().catch(() => false) &&
        await mt(page, "mutation-model-pair-continue").isEnabled().catch(() => false)) {
      await mt(page, "mutation-model-pair-continue").click();
      control("mutation-model-pair-continue", { clicked: true });
      actions.push({ continue: true, at: Date.now() });
      await page.waitForTimeout(500);
      continue;
    }
    await page.waitForTimeout(300);
  }
  throw new Error(`pair jobs did not end: ${JSON.stringify(await pairJobs(page))} ids ${JSON.stringify(ids)}`);
}

// ------------------------------------------------------------------ mode main
async function modeMain(session, input, rec_, evidence, log) {
  const { page, app } = session;
  const runsDir = input["runs-dir"];
  const handles = evidence.handles;
  const budget = evidence.budget;
  const wording = [];
  let limitationsSeen = [];
  const checkWording = async label => {
    const seen = await panelWording(page, limitationsSeen);
    wording.push({ label, found: seen.found, chars: seen.chars });
    assert.deepEqual(seen.found, [], `${label}: forbidden wording ${JSON.stringify(seen.found)}`);
    return seen;
  };
  await waitForBoot(page);

  // ---- no run (fresh root): reason only
  await rec_.part("no-run", ["MM-no-run"], () => rec_.step("N01-no-run", ["MM-no-run"],
    "Fresh root: click 단백질 공학 before any run exists → the model area shows 사용할 수 없음 + reason only", async () => {
      const runs = await readApi(page, "/runs");
      const before = Date.now();
      await openTab(page);
      await mt(page, "mutation-model-no-run").waitFor({ timeout: 15000 });
      await page.waitForTimeout(1000);
      return { runs: runs.length, state: await modelState(page), text: clean(await panel(page).textContent()),
        controls: await panel(page).locator("button, input, select, textarea, a, table").count(),
        reads: log.filter(row => row.at >= before && row.path.includes("mutation_models")).length };
    }, async value => {
      assert.equal(value.runs, 0, "mode main needs a fresh runs root");
      assert.equal(value.state, "unavailable");
      assert.ok(value.text.includes("사용할 수 없음") && value.text.includes(NO_RUN_REASON), value.text);
      assert.ok(!/\d/.test(value.text.replace("단백질 공학 · 변이 구조 모델링", "")), value.text);
      assert.equal(value.controls, 0);
      assert.equal(value.reads, 0);
      return { text: value.text };
    }));

  // ---- run A: 1UBQ load + 전처리
  const runA = await rec_.step("R01-new-run", [], "Click 구조 분석, 새 run (run A)", () => newRun(page), async id => ({ run: id }));
  evidence.runs.A = runA;
  const loaded = await rec_.step("R02-upload", ["MM-load-prepare"], "Choose public_1ubq.cif, click 구조 불러오기",
    () => uploadLoad(page, STRUCTURE), async value => value);
  evidence.inputs.push({ name: "public_1ubq.cif", ...fileRecord(STRUCTURE),
    provenance: "public PDB entry 1UBQ (repository fixture; public structure, not experimental validation)" });
  handles.structure = loaded.handle;
  const prepared = await rec_.step("R03-prepare", ["MM-load-prepare"], "Click 전처리 (displayed default policies)",
    () => prepareManual(page), async value => value);
  handles.prepared = prepared.prepared;
  evidence.repro = { run: runA, loadArgs: loaded.loadArgs, prepareArgs: { ...prepared.args, structure: "<loaded structure>" } };

  // ---- M20 direct-residue candidate set: ILE A:44, allowed W → one candidate I44W
  const set = await rec_.step("C01-candidate-set", ["MM-candidate-set"],
    "Click 단백질 공학, choose the prepared structure, tick 직접 선택 + ILE A:44, 모두 해제 + W, click 후보 만들기", async () => {
      await openTab(page);
      await m20Ready(page);
      return m20CreateDirect(page, runA, handles.prepared);
    }, async value => {
      assert.equal(value.args.structure, handles.prepared);
      assert.equal(value.args.allowed_residues, "W");
      assert.equal(value.args.ligand, null);
      assert.deepEqual(value.args.sources.residues.map(resShort), ["ILE A:44"]);
      const rows = await readApi(page, `/runs/${runA}/mutation_candidate_sets/${enc(value.handle)}/candidates?offset=0&limit=100`);
      assert.equal(rows.total, 1);
      assert.deepEqual([rows.rows[0].from, rows.rows[0].to, resShort(rows.rows[0].residue)], ["I", "W", "ILE A:44"]);
      return { handle: value.handle, candidate: rows.rows[0], args: value.args };
    });
  handles.candidateSet = set.handle;
  // a step returns its action's value; the candidate row is read again (GET) from the stored set
  const candidate = (await readApi(page, `/runs/${runA}/mutation_candidate_sets/${enc(set.handle)}/candidates?offset=0&limit=100`)).rows[0];
  evidence.repro.candidateArgs = { ...set.args, structure: "<prepared structure>" };

  // ---- handoff from the candidate row; request validation (nothing sent)
  await rec_.part("validation", ["MM-handoff", "MM-validation"], async () => {
    await rec_.step("V01-handoff", ["MM-handoff"], "Before any click the request area names no candidate; click 변이 구조 " +
      "모델링 on candidate 0 → the request area shows it (seed empty, confirmations unchecked, no job request)", async () => {
      await waitListReady(page);
      const empty = { noCandidate: await mt(page, "mutation-model-no-candidate").count(), state: await modelState(page),
        listEmpty: await mt(page, "mutation-model-list-empty").count() };
      const before = Date.now();
      await m20(page).locator(`[data-testid="mutation-candidate-model"][data-candidate-index="${candidate.index}"]`).click();
      control("mutation-candidate-model", { index: candidate.index });
      const chosen = mt(page, "mutation-model-candidate");
      await chosen.waitFor({ timeout: 15000 });
      return { empty, set: await chosen.getAttribute("data-candidate-set"), index: await chosen.getAttribute("data-candidate-index"),
        text: clean(await chosen.textContent()), seed: await mt(page, "mutation-model-seed").inputValue(),
        cutoff: await mt(page, "mutation-model-cutoff").inputValue(), timeout: await mt(page, "mutation-model-timeout").inputValue(),
        selection: await mt(page, "mutation-model-confirm-selection").isChecked(),
        hydrogen: await mt(page, "mutation-model-confirm-hydrogen").isChecked(),
        posts: log.filter(row => row.at >= before && row.method === "POST").length };
    }, async value => {
      assert.equal(value.empty.noCandidate, 1);
      assert.equal(value.empty.state, "empty");
      assert.equal(value.empty.listEmpty, 1);
      assert.equal(value.set, set.handle);
      assert.equal(value.index, String(candidate.index));
      assert.ok(value.text.includes("ILE A:44") && value.text.includes("I → W"), value.text);
      assert.deepEqual([value.seed, value.cutoff, value.timeout, value.selection, value.hydrogen], ["", "4.0", "120", false, false]);
      assert.equal(value.posts, 0);
      return value;
    });
    await rec_.step("V02-validation", ["MM-validation"], "Submit stays disabled: without seed and confirmations, with seed only, " +
      "with one confirmation, with cutoff 7.0; enabled only with seed + both confirmations + cutoff in range (no job request)",
    async () => {
      const before = Date.now();
      const snap = async label => ({ label, disabled: await mt(page, "mutation-model-submit").isDisabled(), errors: await requestErrors(page),
        blocked: clean(await mt(page, "mutation-model-submit-blocked").textContent({ timeout: 1000 }).catch(() => "")) });
      const seen = [await snap("empty")];
      await mt(page, "mutation-model-seed").fill(MODEL.seed);
      control("mutation-model-seed", { value: MODEL.seed });
      seen.push(await snap("seed only"));
      await mt(page, "mutation-model-confirm-selection").check();
      control("mutation-model-confirm-selection", { checked: true });
      seen.push(await snap("seed + protein_only"));
      await mt(page, "mutation-model-confirm-hydrogen").check();
      control("mutation-model-confirm-hydrogen", { checked: true });
      await mt(page, "mutation-model-cutoff").fill("7.0");
      control("mutation-model-cutoff", { value: "7.0" });
      seen.push(await snap("cutoff 7.0"));
      await mt(page, "mutation-model-cutoff").fill(MODEL.cutoff);
      await mt(page, "mutation-model-timeout").fill(MODEL.timeout);
      control("mutation-model-timeout", { value: MODEL.timeout });
      seen.push(await snap("complete"));
      return { seen, posts: log.filter(row => row.at >= before && row.method === "POST").length };
    }, async value => {
      const [empty, seedOnly, oneConfirm, badCutoff, complete] = value.seen;
      assert.equal(empty.disabled, true);
      assert.ok(empty.errors.some(text => text.startsWith("seed:")), empty.errors.join(" | "));
      assert.ok(empty.errors.some(text => text.includes("confirmation_missing")), empty.errors.join(" | "));
      assert.equal(seedOnly.disabled, true);
      assert.ok(!seedOnly.errors.some(text => text.startsWith("seed:")));
      assert.ok(seedOnly.errors.some(text => text.includes("confirmation_missing")));
      assert.equal(oneConfirm.disabled, true);
      assert.ok(oneConfirm.errors.some(text => text.includes("confirmation_missing")));
      assert.equal(badCutoff.disabled, true);
      assert.ok(badCutoff.errors.some(text => text.startsWith("접촉 cutoff") && text.includes("argument_invalid")), badCutoff.errors.join(" | "));
      assert.equal(complete.disabled, false);
      assert.deepEqual(complete.errors, []);
      assert.equal(value.posts, 0, "a request was sent while the form was blocked");
      return value.seen.map(item => ({ label: item.label, disabled: item.disabled, errors: item.errors }));
    });
  });

  // ---- real modeling job: approval → start → done; not opened automatically
  const job = await rec_.step("J01-model-job", ["MM-job"], "Click 모델링 작업 제출 → 비싼 계산 승인 → 작업 시작 → real " +
    "openmm_mutation_model_v1 done; one expensive unit; the model is listed but not opened automatically", async () => {
    const value = await runModelJob(page, runA);
    await mt(page, "mutation-model-new").waitFor({ timeout: 30000 });
    await waitListReady(page);
    return { ...value, newHandle: await mt(page, "mutation-model-new").getAttribute("data-model-handle"),
      detailShown: await mt(page, "mutation-model-detail").count(), listed: await panel(page).locator("label[data-mutation-model]").count() };
  }, async value => {
    assert.equal(value.request.protocol_id, PROTOCOL);
    assert.deepEqual(value.request.args, { candidate_set: set.handle, candidate_index: candidate.index, seed: Number(MODEL.seed),
      selection_policy: "protein_only", hydrogen_policy: "rebuild_pH7", contact_cutoff_A: Number(MODEL.cutoff) });
    assert.equal(value.request.timeout_s, Number(MODEL.timeout));
    assert.equal(value.approved, true, "the first expensive call of the run was not gated by approval");
    assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
    const handle = value.job.artifacts?.mutation_model;
    assert.match(handle ?? "", /\/mutation_model\//);
    assert.equal(value.newHandle, handle);
    assert.equal(value.detailShown, 0, "the model was opened automatically");
    assert.equal(value.listed, 1);
    assert.equal(value.budgetAfter - value.budgetBefore, 1);
    return { handle, jobId: value.jobId, phases: value.phases, approvalNotice: value.approvalNotice,
      units: [value.budgetBefore, value.budgetAfter] };
  });
  handles.model = job.job.artifacts.mutation_model;
  handles.modelJob = job.jobId;
  budget.model = { before: job.budgetBefore, after: job.budgetAfter };
  evidence.repro.modelArgs = { ...job.request.args, candidate_set: "<candidate set>" };
  evidence.repro.timeoutS = job.request.timeout_s;
  evidence.repro.model = handles.model;
  const stored = storedObject(runsDir, runA, handles.model);
  assert.equal(stored.schema, "mutation_model@1");

  // ---- open: side by side, contacts + paging, downloads, limitations
  let detail = null;
  await rec_.part("open", ["MM-side-by-side", "MM-limitations", "MM-negative"], async () => {
    const opened = await rec_.step("O01-side-by-side", ["MM-side-by-side"], "Click 이 모델 열기: summary and the side-by-side table " +
      "equal the stored values (API detail = event-log payload; harness ROUND_HALF_UP)", async () => {
      await mt(page, "mutation-model-open-new").click();
      control("mutation-model-open-new", { clicked: true });
      await panel(page).locator(`[data-testid="mutation-model-detail"]${attr("data-model-handle", handles.model)}`).waitFor({ timeout: 60000 });
      return { api: await readApi(page, modelPath(runA, handles.model)), table: await sideBySide(page),
        summary: clean(await mt(page, "mutation-model-summary").textContent()) };
    }, async value => {
      const result = value.api.result;
      assert.equal(value.api.schema, "mutation_model_detail@1");
      for (const side of SIDES) {
        const api = result.structures[side], kept = stored.structures[side];
        for (const field of ["structure_sha256", "system_xml_sha256", "topology_sha256", "heavy_atoms", "added_hydrogens"])
          assert.equal(api[field], kept[field], `${side}.${field} API = stored`);
        assert.deepEqual(api.energy, kept.energy, `${side} energy API = stored`);
        assert.deepEqual(api.sasa, kept.sasa, `${side} sasa API = stored`);
        assert.equal(api.contacts.count, kept.contacts.count);
        assert.equal(api.contacts.count, kept.contacts.rows.length);
        assert.equal(api.energy.unit, "kJ/mol");
      }
      assert.deepEqual(result.comparison, stored.comparison);
      for (const key of ["energy_delta", "delta", "difference", "rank"]) assert.ok(!JSON.stringify(result).includes(`"${key}`), key);
      assert.equal(result.candidate.from, "I");
      assert.equal(result.candidate.to, "W");
      assert.equal(result.candidate.mutant_resname, "TRP");
      assert.ok(sameResidue(result.candidate.residue, candidate.residue), "candidate residue 7 fields");
      const want = expectedSideBySide(result);
      assert.deepEqual(value.table.headers, ["항목", SIDE_LABEL.wild_type_reference, SIDE_LABEL.mutant]);
      assert.deepEqual(value.table.rows.map(row => row.key), Object.keys(want));
      for (const row of value.table.rows) {
        assert.equal(row.cellCount, 3, `${row.key}: extra column`);
        assert.deepEqual(row.values, want[row.key], `${row.key} shown = stored`);
      }
      assert.ok(value.summary.startsWith("ILE A:44 · I → W (ILE → TRP) · 위치"), value.summary);
      return { sideBySide: Object.fromEntries(value.table.rows.map(row => [row.key, row.values])),
        energies: Object.fromEntries(SIDES.map(side => [side, result.structures[side].energy])),
        sasa: Object.fromEntries(SIDES.map(side => [side, result.structures[side].sasa.value_A2])),
        contacts: Object.fromEntries(SIDES.map(side => [side, result.structures[side].contacts.count])) };
    });
    detail = opened.api;
    await rec_.step("O02-limitations", ["MM-limitations"], "The limitation group shows the stored sentences, verbatim, in the " +
      "spec order (L5/L6 only under their stored conditions)", async () => ({
      shown: await mt(page, "mutation-model-limitations").locator("[data-limitation]").allTextContents() }), async value => {
      const want = expectedLimitations(detail.result);
      assert.deepEqual(detail.result.limitations, want);
      assert.deepEqual(stored.limitations, want);
      assert.deepEqual(value.shown.map(text => text.trim()), want);
      limitationsSeen = want;
      return { count: want.length, protonationDifferences: detail.result.comparison.protonation_difference_count,
        newDisulfide: detail.result.comparison.new_disulfide_in_mutant };
    });
    await rec_.step("O03-negative", ["MM-negative"], "No difference/change/rank/best wording or arrow in the panel; the two " +
      "structure cells of every side-by-side row have the same style (no comparison colouring); no extra column", async () => ({
      wording: await checkWording("model opened"), table: await sideBySide(page),
      tableText: await mt(page, "mutation-model-side-by-side").textContent() }), async value => {
      for (const row of value.table.rows) {
        assert.deepEqual(row.styles.wild_type_reference, row.styles.mutant, `${row.key}: the two cells differ in style`);
        assert.equal(row.styles.mutant.inline, null);
        assert.equal(row.trStyle, null);
      }
      assert.ok(!ARROWS.test(value.tableText), "arrow in the side-by-side table");
      return { wordingChars: value.wording.chars, rows: value.table.rows.length };
    });
  });

  await rec_.part("contacts", ["MM-contacts"], async () => {
    const shown = [];
    await rec_.step("K01-contacts", ["MM-contacts"], "Contact table: 야생형 기준 page 1, then 변이형 page 1, 다음, 이전 — every page " +
      "equals the API page and the stored rows (7 partner fields, atom names, distance ROUND_HALF_UP)", async () => {
      shown.push(await checkContacts(page, runA, handles.model, stored, "wild_type_reference", 1));
      await mt(page, "mutation-model-contacts-side-mutant").check();
      control("mutation-model-contacts-side", { side: "mutant" });
      shown.push(await checkContacts(page, runA, handles.model, stored, "mutant", 1));
      assert.ok(shown[1].pager, "mutant contacts need more than one page (cutoff 6.0 Å)");
      await mt(page, "mutation-model-contacts-next").click();
      control("mutation-model-contacts-next", { clicked: true });
      shown.push(await checkContacts(page, runA, handles.model, stored, "mutant", 2));
      await mt(page, "mutation-model-contacts-prev").click();
      control("mutation-model-contacts-prev", { clicked: true });
      shown.push(await checkContacts(page, runA, handles.model, stored, "mutant", 1));
      return shown;
    }, async value => {
      assert.ok(value[1].total > 100);
      return value;
    });
  });

  await rec_.part("downloads", ["MM-downloads"], async () => {
    for (const side of SIDES) {
      await rec_.step(`D01-${side}`, ["MM-downloads"], `Click ${SIDE_LABEL[side]} 구조 mmCIF 내려받기: bytes SHA-256 = stored ` +
        "structure_sha256 = backend bytes", () => downloadByClick(app, mt(page, `mutation-model-download-${side}`)), async got => {
        control(`mutation-model-download-${side}`, { clicked: true });
        const bytes = fs.readFileSync(got.downloaded);
        const backend = await readBytes(page, modelPath(runA, handles.model, `/structure?side=${side}`));
        assert.equal(sha(bytes), stored.structures[side].structure_sha256);
        assert.equal(sha(bytes), sha(backend));
        return { side, sha256: sha(bytes), bytes: bytes.length, filename: got.filename };
      });
    }
  });

  await rec_.part("report", ["MM-report"], async () => {
    const created = await rec_.step("Q01-report", ["MM-report"], "Click 보고서 만들기: the report is saved and listed for this model",
      async () => {
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runA}/method_reports`, { timeout: 60000 });
        posted.catch(() => undefined); // a failed click must not leave an unhandled rejection
        const models = await modelCount(page, runA);
        await mt(page, "mutation-model-report").click();
        control("mutation-model-report", { clicked: true });
        const response = await posted;
        const body = await response.json();
        await mt(page, "mutation-model-report-done").waitFor({ timeout: 30000 });
        await panel(page).locator(`[data-testid="mutation-model-report-list"] li${attr("data-report-handle", body.handle)}`).waitFor({ timeout: 30000 });
        return { status: response.status(), body, request: response.request().postDataJSON(), modelsBefore: models,
          modelsAfter: await modelCount(page, runA), done: await mt(page, "mutation-model-report-done").getAttribute("data-report-handle") };
      }, async value => {
        assert.deepEqual(value.request, { result_handle: handles.model });
        assert.equal(value.body.manifest.analysis_type, "mutation_model");
        assert.equal(value.body.manifest.result_handle, handles.model);
        assert.equal(value.done, value.body.handle);
        assert.equal(value.modelsAfter, value.modelsBefore, "the report made a new model");
        return { handle: value.body.handle };
      });
    created.handle = created.body.handle;
    handles.report = created.handle;
    for (const [id, format] of [["mutation-model-report-markdown", "markdown"], ["mutation-model-report-json", "json"]]) {
      await rec_.step(`Q02-${format}`, ["MM-report"], `Click ${format} 내려받기: bytes = backend bytes; the Markdown carries the ` +
        "fixed sentences and no docking score", () => downloadByClick(app, panel(page)
        .locator(`[data-testid="mutation-model-report-list"] li${attr("data-report-handle", created.handle)} [data-testid="${id}"]`)),
      async got => {
        control(id, { clicked: true });
        const bytes = fs.readFileSync(got.downloaded);
        const backend = await readBytes(page, `/runs/${runA}/reports/download?handle=${enc(created.handle)}&format=${format}`);
        assert.equal(sha(bytes), sha(backend));
        if (format === "markdown") {
          const text = bytes.toString("utf8");
          for (const sentence of limitationsSeen) assert.ok(text.includes(sentence), `report lacks ${sentence}`);
          assert.ok(!text.includes("qvina"), "the model report cites a docking value");
        }
        return { format, sha256: sha(bytes), bytes: bytes.length };
      });
    }
  });

  // ---- same submission again → same job and handle, no new unit
  await rec_.part("same-handle", ["MM-same-handle"], () => rec_.step("S01-same-submit", ["MM-same-handle"],
    "Click 모델링 작업 제출 again with the same inputs: the existing done job and model come back, no new job, no unit",
    async () => {
      const before = { units: await unitsUsed(page, runA), models: await modelCount(page, runA),
        jobs: (await readApi(page, `/runs/${runA}/jobs`)).length };
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${runA}/jobs` && response.request().postDataJSON()?.protocol_id === PROTOCOL,
      { timeout: 60000 });
      posted.catch(() => undefined); // a failed click must not leave an unhandled rejection
      await mt(page, "mutation-model-submit").click();
      control("mutation-model-submit", { clicked: true, repeat: true });
      const response = await posted;
      const body = await response.json();
      await mt(page, "mutation-model-notice").waitFor({ timeout: 30000 });
      return { before, status: response.status(), body, request: response.request().postDataJSON(),
        notice: clean(await mt(page, "mutation-model-notice").textContent()),
        after: { units: await unitsUsed(page, runA), models: await modelCount(page, runA), jobs: (await readApi(page, `/runs/${runA}/jobs`)).length } };
    }, async value => {
      assert.equal(value.status, 200);
      assert.equal(value.body.job_id, handles.modelJob);
      assert.equal(value.body.status, "done");
      assert.equal(value.body.artifacts?.mutation_model, handles.model);
      assert.deepEqual(value.after, value.before);
      assert.ok(value.notice.includes("새 작업을 만들지 않았습니다") && value.notice.includes(handles.modelJob), value.notice);
      return { jobId: value.body.job_id, handle: value.body.artifacts.mutation_model, units: value.after.units };
    }));

  // ---- late contact page (held), inside one mount
  await rec_.part("late-contacts", ["MM-late-contacts"], async () => {
    const held = [];
    let holding = true;
    const contactsPath = decodeURIComponent(`/api${modelPath(runA, handles.model, "/contacts")}`);
    const matcher = url => decodeURIComponent(new URL(url).pathname) === contactsPath && new URL(url).searchParams.get("structure") === "mutant";
    const handler = async route => {
      if (!holding) return route.continue();
      try { held.push({ route, response: await route.fetch() }); }
      catch (error) { held.push({ route, response: null, error: String(error).slice(0, 160) }); }
    };
    await page.route(matcher, handler);
    evidence.fixtureLabels.push(HOLD_LABEL);
    try {
      await rec_.step("L01-held", ["MM-late-contacts"], "Show 야생형 기준, then choose 변이형: its contact page is held; choose " +
        "야생형 기준 again → the 야생형 기준 page", async () => {
        await mt(page, "mutation-model-contacts-side-wild_type_reference").check();
        await checkContacts(page, runA, handles.model, stored, "wild_type_reference", 1);
        await mt(page, "mutation-model-contacts-side-mutant").check();
        await waitFor(page, async () => held.length >= 1 ? true : null, "held mutant page", 30000);
        await mt(page, "mutation-model-contacts-side-wild_type_reference").check();
        return checkContacts(page, runA, handles.model, stored, "wild_type_reference", 1);
      }, async value => value);
      await rec_.step("L02-release", ["MM-late-contacts"], "Release the held 변이형 page: the 야생형 기준 page stays", async () => {
        holding = false;
        const released = [];
        for (const item of held) {
          if (!item.response) { released.push({ delivered: false, reason: item.error }); continue; }
          try { await item.route.fulfill({ response: item.response }); released.push({ delivered: true }); }
          catch (error) { released.push({ delivered: false, reason: String(error).slice(0, 160) }); }
        }
        await page.waitForTimeout(2500);
        return { released, view: await contactView(page) };
      }, async value => {
        assert.equal(value.view.side, "wild_type_reference");
        assert.equal(value.view.total, stored.structures.wild_type_reference.contacts.rows.length);
        return { released: value.released, layer: value.released.some(item => item.delivered)
          ? "request number (delivered, dropped)" : "abort (request aborted on key change)" };
      });
    } finally {
      holding = false;
      for (const item of held) if (item.response) await item.route.fulfill({ response: item.response }).catch(() => undefined);
      await page.unroute(matcher, handler);
    }
  });

  // ---- ligand SDF import (리간드 탭) and the tab trip back (remount: nothing opened, lists re-read)
  const sdf = await rec_.part("ligand-import", ["MM-tab-state"], async () => {
    const imported = await rec_.step("T01-import", [], "Click 리간드 설계·탐색, choose synthetic-phenol-ligand.sdf as 리간드 SDF " +
      "(file chooser), click 가져오기", async () => {
      await selectTab(page, LIGAND_TAB);
      const dock = page.locator('#mw-app-panel-ligand [data-testid="docking-panel"]');
      await dock.waitFor({ timeout: 15000 });
      const known = new Set((await readApi(page, `/runs/${runA}/docking/prerequisites`)).imports.map(item => item.handle));
      const chooser = page.waitForEvent("filechooser", { timeout: 15000 });
      await dock.locator('[data-testid="docking-file-ligand"]').click();
      await (await chooser).setFiles(LIGAND_SDF);
      control("docking-file-ligand", { file: path.basename(LIGAND_SDF) });
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${runA}/chemical/imports`, { timeout: 60000 });
      posted.catch(() => undefined); // a failed click must not leave an unhandled rejection
      await dock.locator('[data-testid="docking-import"]').click();
      control("docking-import", { files: ["ligand"] });
      const status = (await posted).status();
      await dock.locator('[data-testid="docking-import-done"]').waitFor({ timeout: 60000 });
      const fresh = (await readApi(page, `/runs/${runA}/docking/prerequisites`)).imports.filter(item => !known.has(item.handle));
      return { status, fresh };
    }, async value => {
      assert.equal(value.status, 201);
      assert.equal(value.fresh.length, 1);
      assert.equal(value.fresh[0].input_kind, "ligand_sdf");
      return { handle: value.fresh[0].handle };
    });
    evidence.inputs.push({ name: "synthetic-phenol-ligand.sdf", ...fileRecord(LIGAND_SDF),
      provenance: "SYNTHETIC-FIXTURE hand-built phenol (backend/tests/fixtures/mutation_model/SYNTHETIC-PROVENANCE.md)" });
    await rec_.step("T02-tab-trip", ["MM-tab-state"], "Click 단백질 공학 again: the panel remounts, reads its lists again (GET " +
      "only) and opens nothing by itself; the stored model is listed", async () => {
      const before = Date.now();
      await openTab(page);
      await waitListReady(page);
      await page.waitForTimeout(1000);
      return { reads: log.filter(row => row.at >= before && row.method === "GET").map(row => row.path),
        posts: log.filter(row => row.at >= before && row.method === "POST").length,
        detail: await mt(page, "mutation-model-detail").count(), listed: await panel(page).locator("label[data-mutation-model]").count(),
        checked: await panel(page).locator("label[data-mutation-model] input:checked").count(), state: await modelState(page) };
    }, async value => {
      assert.ok(value.reads.includes(`/api/runs/${runA}/mutation_models`), "no list read on tab entry");
      assert.equal(value.posts, 0);
      assert.equal(value.detail, 0, "a model was opened automatically");
      assert.equal(value.checked, 0);
      assert.equal(value.listed, 1);
      assert.equal(value.state, "ready");
      return { state: value.state, reads: [...new Set(value.reads)] };
    });
    return imported.fresh[0].handle;
  });
  handles.ligandSdf = sdf;

  // ---- same-condition docking: one action, two real qvina jobs, pair table
  let pair1 = null;
  if (sdf) await rec_.part("pair", ["MM-pair-submit", "MM-pair-scores", "MM-negative"], async () => {
    const submitted = await rec_.step("P01-pair-submit", ["MM-pair-submit"], "Open the model, read the docking inputs again, choose " +
      "3D SDF + the phenol import, 리간드 범위 + 여백 8, seed/values, three acknowledgements: the 2-unit notice is shown and " +
      "submit stays blocked until the 2-unit box is ticked; one click sends two qvina_dock_v1 jobs", async () => {
      await openModel(page, handles.model);
      await mt(page, "mutation-model-pair-prereq-refresh").click();
      control("mutation-model-pair-prereq-refresh", { clicked: true });
      await panel(page).locator('label[data-pair-ligand-source="sdf"] input').check();
      await waitFor(page, async () => await mt(page, "mutation-model-pair-sdf").locator(`option${attr("value", sdf)}`).count()
        ? true : null, "phenol SDF offered", 30000);
      await fillPair(page, sdf, PAIR.seed);
      const notice = clean(await mt(page, "mutation-model-pair-units-notice").textContent());
      const before = await unitsUsed(page, runA);
      const value = await submitPair(page, runA, log);
      return { notice, before, ...value, jobs: await pairJobs(page) };
    }, async value => {
      assert.ok(value.notice.includes("도킹 작업 2개") && value.notice.includes("합쳐서 2단위"), value.notice);
      assert.equal(value.blockedBefore.disabled, true);
      assert.ok(value.blockedBefore.blocked.includes("2단위"), value.blockedBefore.blocked);
      assert.equal(value.posts, 2, "one click must send exactly two docking jobs");
      const [wt, mu] = value.responses;
      assert.deepEqual(value.responses.map(item => item.request.args.receptor_source.side), SIDES);
      for (const item of value.responses) {
        assert.equal(item.status, 200);
        assert.equal(item.body.protocol_id, DOCKING_PROTOCOL);
        assert.equal(item.request.args.receptor_source.mutation_model, handles.model);
        for (const key of ["receptor_handle", "receptor_model_number", "connectivity", "receptor_instance"])
          assert.ok(!(key in item.request.args), `${key} sent with a mutation-model receptor`);
      }
      const strip = args => JSON.stringify({ ...args, receptor_source: { ...args.receptor_source, side: null } });
      assert.equal(strip(wt.request.args), strip(mu.request.args), "the two requests differ beyond the side");
      assert.deepEqual(wt.request.args.ligand, { source: "sdf", sdf_handle: sdf });
      assert.deepEqual(wt.request.args.box, { source: "ligand_range", margin_A: Number(PAIR.margin) });
      assert.equal(wt.request.args.mode, "free");
      assert.equal(value.units, "unchecked", "the 2-unit confirmation stays ticked after the submission");
      return { jobs: value.responses.map(item => item.body.job_id), args: wt.request.args, notice: value.notice,
        unitsBefore: value.before };
    });
    const ids = submitted.responses.map(item => item.body.job_id);
    submitted.unitsBefore = submitted.before;
    const driven = await rec_.step("P02-pair-run", ["MM-pair-submit"], "Approve/continue through the screen's own buttons until " +
      "both real qvina jobs end; two expensive units in total", async () => drivePair(page, ids), async value => {
      for (const side of SIDES) assert.equal(value.jobs[side].status, "done", JSON.stringify(value.jobs));
      const after = await unitsUsed(page, runA);
      assert.equal(after - submitted.unitsBefore, 2);
      return { actions: value.actions, units: [submitted.unitsBefore, after],
        approvalAsked: value.actions.some(item => item.approve) };
    });
    budget.pair = { before: submitted.unitsBefore, after: await unitsUsed(page, runA), actions: driven.actions };
    const pairStep = await rec_.step("P03-pair-table", ["MM-pair-scores"], "Pair table: one row for this condition, both scores side by " +
      "side = the server's pair = each M18 result's first mode score; header uses the server's score name; no difference " +
      "column, same cell style on both sides", async () => {
      const api = await readApi(page, modelPath(runA, handles.model, "/docking_pairs"));
      const pair = api.pairs.find(item => SIDES.every((side, i) => item.sides[side].job_id === ids[i]));
      assert.ok(pair, `no pair for jobs ${ids}`);
      const view = await waitFor(page, async () => {
        const value = await pairView(page);
        const row = value?.rows.find(item => item.index === pair.index);
        return row && SIDES.every(side => row.sides[side]?.hasScore === "true") ? value : null;
      }, "pair row with both scores", 60000);
      const results = {};
      for (const side of SIDES) {
        const handle = pair.sides[side].result_handle;
        results[side] = await readApi(page, `/runs/${runA}/docking/results/detail?handle=${enc(handle)}`);
      }
      return { api, pair, view, results };
    }, async value => {
      const { api, pair, view, results } = value;
      assert.equal(api.score_label, SCORE_LABEL);
      assert.equal(pair.both_published, true);
      assert.deepEqual(view.headers, ["짝", "도킹 조건", `${SIDE_LABEL.wild_type_reference} · ${SCORE_LABEL}`, `${SIDE_LABEL.mutant} · ${SCORE_LABEL}`]);
      const row = view.rows.find(item => item.index === pair.index);
      assert.equal(row.cellCount, 4, "extra column in the pair table");
      assert.equal(row.trStyle, null);
      const scores = {};
      for (const side of SIDES) {
        const result = results[side].result;
        assert.deepEqual(result.inputs.receptor.source, { kind: "mutation_model", mutation_model: handles.model, side });
        const first = result.modes[0];
        assert.equal(pair.sides[side].score_kcal_mol, first.score_kcal_mol, `${side} pair score = M18 result`);
        const cell = row.sides[side];
        assert.equal(cell.text, `${halfUp(first.score_kcal_mol, 1)} · 모드 ${pair.sides[side].score_mode}(엔진 출력 순서)`);
        assert.equal(cell.result, pair.sides[side].result_handle);
        assert.ok(cell.job.includes("완료 (done)"), cell.job);
        scores[side] = first.score_kcal_mol;
      }
      for (const key of ["color", "background", "weight", "className", "inline"])
        assert.equal(row.sides.wild_type_reference[key], row.sides.mutant[key], `pair cells differ in ${key}`);
      assert.ok(!SIDES.some(side => ARROWS.test(row.sides[side].text)), "arrow in a pair cell");
      for (const key of ["difference", "delta", "rank", "best"]) assert.ok(!JSON.stringify(pair).includes(`"${key}`), key);
      await checkWording("pairs shown");
      return { index: pair.index, scores, results: SIDES.map(side => pair.sides[side].result_handle) };
    });
    pair1 = { index: pairStep.pair.index, results: SIDES.map(side => pairStep.pair.sides[side].result_handle) };
    handles.pairResults = pair1.results;
  });

  // ---- partial pair: second condition (seed 7), the mutant job cancelled while queued
  if (sdf && handles.model) await rec_.part("pair-partial", ["MM-pair-partial"], async () => {
    const submitted = await rec_.step("P11-partial-submit", ["MM-pair-partial"], "Change seed to 7, tick the 2-unit box, submit: " +
      "two jobs; the 야생형 기준 job starts; cancel the 변이형 job while it is still queued", async () => {
      if (!await mt(page, "mutation-model-detail").count()) await openModel(page, handles.model);
      await fillPair(page, sdf, PARTIAL_SEED);
      const before = await unitsUsed(page, runA);
      const value = await submitPair(page, runA, log);
      return { before, ...value };
    }, async value => {
      assert.equal(value.posts, 2);
      assert.deepEqual(value.responses.map(item => item.request.args.parameters.seed), [7, 7]);
      return { jobs: value.responses.map(item => item.body.job_id), unitsBefore: value.before };
    });
    const ids = submitted.responses.map(item => item.body.job_id);
    submitted.unitsBefore = submitted.before;
    const driven = await rec_.step("P12-partial-run", ["MM-pair-partial"], "Cancel 변이형 (queued) through its button; the 야생형 " +
      "기준 job finishes; units: one for the started job only", async () => drivePair(page, ids, { cancelSide: "mutant" }),
    async value => {
      assert.equal(value.jobs.wild_type_reference.status, "done", JSON.stringify(value.jobs));
      assert.equal(value.jobs.mutant.status, "cancelled", JSON.stringify(value.jobs));
      const after = await unitsUsed(page, runA);
      return { actions: value.actions, units: [submitted.unitsBefore, after], delta: after - submitted.unitsBefore };
    });
    budget.partial = { before: submitted.unitsBefore, after: await unitsUsed(page, runA), actions: driven.actions };
    await rec_.step("P13-partial-table", ["MM-pair-partial", "MM-negative"], "Pair table row of seed 7: per-side job status; both " +
      "cells '없음(이유)' with the server's reason and no number (the cancelled side and the side whose partner is missing)",
    async () => {
      const api = await readApi(page, modelPath(runA, handles.model, "/docking_pairs"));
      const pair = api.pairs.find(item => SIDES.every((side, i) => item.sides[side].job_id === ids[i]));
      assert.ok(pair, `no pair for jobs ${ids}`);
      const view = await waitFor(page, async () => {
        const value = await pairView(page);
        const row = value?.rows.find(item => item.index === pair.index);
        return row && row.sides.mutant?.job.includes("cancelled") && row.sides.wild_type_reference?.job.includes("done") ? value : null;
      }, "partial pair row", 60000);
      return { api, pair, view };
    }, async value => {
      const { api, pair, view } = value;
      assert.equal(pair.both_published, false);
      assert.equal(api.total, 2);
      const row = view.rows.find(item => item.index === pair.index);
      for (const side of SIDES) {
        assert.equal(pair.sides[side].score_kcal_mol, null);
        const cell = row.sides[side];
        assert.equal(cell.hasScore, "false");
        assert.equal(cell.text, `없음(${pair.sides[side].reason})`);
        assert.ok(!/\d/.test(cell.text), `a number in a missing side: ${cell.text}`);
      }
      assert.equal(pair.sides.mutant.reason_code, "job_cancelled");
      assert.equal(pair.sides.wild_type_reference.reason_code, "other_side_missing");
      assert.ok(row.sides.mutant.job.includes("취소됨 (cancelled)"));
      assert.ok(row.sides.wild_type_reference.job.includes("완료 (done)"));
      const other = view.rows.find(item => item.index === pair1?.index);
      if (pair1) assert.ok(SIDES.every(side => other.sides[side].hasScore === "true"), "the first pair lost its scores");
      await checkWording("partial pair");
      return { index: pair.index, reasons: Object.fromEntries(SIDES.map(side => [side, pair.sides[side].reason_code])),
        cells: Object.fromEntries(SIDES.map(side => [side, row.sides[side].text])) };
    });
  });

  // ---- cancel a running modeling job (seed 7): cancelled, no model, no process left, unit charged once
  await rec_.part("cancel", ["MM-cancel"], async () => {
    await rec_.step("X01-cancel", ["MM-cancel"], "Hand candidate 0 over again (the tab trip reset the form), seed 7 + both confirmations, click 모델링 작업 제출 " +
      "(started, no approval needed in this run), " +
      "click 작업 취소 while it runs → cancelled; no new model; no worker/guardian process left; one unit kept", async () => {
      // the tab trip remounted both panels (request form reset): open the set and hand the candidate over again
      if (!await mt(page, "mutation-model-candidate").count()) {
        await m20(page).locator(`label${attr("data-mutation-set", set.handle)} input`).check();
        control("mutation-sets", { checked: set.handle });
        const button = m20(page).locator(`[data-testid="mutation-candidate-model"][data-candidate-index="${candidate.index}"]`);
        await button.waitFor({ timeout: 60000 });
        await button.click();
        control("mutation-candidate-model", { index: candidate.index, again: true });
        await mt(page, "mutation-model-candidate").waitFor({ timeout: 15000 });
      }
      await mt(page, "mutation-model-seed").fill(CANCEL_SEED);
      control("mutation-model-seed", { value: CANCEL_SEED });
      await mt(page, "mutation-model-cutoff").fill(MODEL.cutoff);
      await mt(page, "mutation-model-timeout").fill(MODEL.timeout);
      await mt(page, "mutation-model-confirm-selection").check();
      await mt(page, "mutation-model-confirm-hydrogen").check();
      const modelsBefore = await modelCount(page, runA);
      const value = await runModelJob(page, runA, { until: "running" });
      const runningProcs = jobProcesses(runsDir);
      await mt(page, "mutation-model-job-cancel").click();
      control("mutation-model-job-cancel", { clicked: true });
      const end = await waitFor(page, async () => { const view = await jobView(page); return view?.status === "cancelled" ? view : null; },
        "model job cancelled", 120000);
      const gone = await waitFor(page, async () => jobProcesses(runsDir).length === 0 ? true : null, "worker processes gone", 60000)
        .catch(() => false);
      return { ...value, end, runningProcs, gone, left: jobProcesses(runsDir), modelsBefore, modelsAfter: await modelCount(page, runA),
        state: await modelState(page), failure: clean(await mt(page, "mutation-model-failure").textContent({ timeout: 5000 }).catch(() => "")),
        job: await readApi(page, `/runs/${runA}/jobs/${enc(value.jobId)}`), units: await unitsUsed(page, runA) };
    }, async value => {
      assert.equal(value.request.args.seed, Number(CANCEL_SEED));
      assert.notEqual(value.jobId, handles.modelJob);
      assert.ok(value.phases.includes("running") || value.phases.includes("claimed"), value.phases.join(","));
      assert.equal(value.job.status, "cancelled");
      assert.ok(!value.job.artifacts?.mutation_model, "a cancelled job published a model");
      assert.equal(value.modelsAfter, value.modelsBefore);
      assert.equal(value.gone, true, `processes left: ${JSON.stringify(value.left)}`);
      assert.equal(value.state, "failed");
      assert.ok(value.failure.includes("취소"), value.failure);
      assert.equal(value.units - value.budgetBefore, 1, "a started (cancelled) job keeps its one reserved unit");
      return { jobId: value.jobId, phases: value.phases, runningProcs: value.runningProcs.length, units: [value.budgetBefore, value.units] };
    });
    budget.cancel = { note: "running modeling job cancelled (reservation kept)" };
  });

  // ---- run switch with a held run A list response
  const runB = await rec_.part("run-switch", ["MM-late-run"], async () => {
    const made = await rec_.step("W01-run-b", ["MM-late-run"], "Click 구조 분석, 새 run (run B, no structure); click 단백질 공학 → " +
      "the model area of run B (빈 결과, no model)", async () => {
      const id = await newRun(page);
      await openTab(page);
      await waitListReady(page);
      return { run: id, state: await modelState(page), listed: await panel(page).locator("label[data-mutation-model]").count() };
    }, async value => { assert.equal(value.state, "empty"); assert.equal(value.listed, 0); return value; });
    evidence.runs.B = made.run;
    const held = [];
    let holding = true;
    const matcher = url => new URL(url).pathname === `/api/runs/${runA}/mutation_models`;
    const handler = async route => {
      if (!holding || route.request().method() !== "GET") return route.continue();
      try { held.push({ route, response: await route.fetch() }); }
      catch (error) { held.push({ route, response: null, error: String(error).slice(0, 160) }); }
    };
    await page.route(matcher, handler);
    evidence.fixtureLabels.push(HOLD_LABEL);
    try {
      await rec_.step("W02-held", ["MM-late-run"], "Choose run A in 저장된 run, click 단백질 공학: run A's model list response is held",
        async () => {
          await chooseRun(page, runA);
          await openTab(page);
          await waitFor(page, async () => held.length >= 1 ? true : null, "held run A list", 30000);
          return { held: held.length, run: await globalRun(page) };
        }, async value => { assert.equal(value.run, runA); return value; });
      await rec_.step("W03-switch-b", ["MM-late-run"], "Click 구조 분석, choose run B, click 단백질 공학: run B's area", async () => {
        await chooseRun(page, made.run, false);
        await openTab(page);
        await waitListReady(page);
        return { run: await globalRun(page), state: await modelState(page) };
      }, async value => { assert.equal(value.run, made.run); assert.equal(value.state, "empty"); return value; });
      await rec_.step("W04-release", ["MM-late-run"], "Release run A's held list: run B's area stays empty, no run A model appears",
        async () => {
          holding = false;
          const released = [];
          for (const item of held) {
            if (!item.response) { released.push({ delivered: false, reason: item.error }); continue; }
            try { await item.route.fulfill({ response: item.response }); released.push({ delivered: true }); }
            catch (error) { released.push({ delivered: false, reason: String(error).slice(0, 160) }); }
          }
          await page.waitForTimeout(2500);
          return { released, run: await globalRun(page), state: await modelState(page), text: clean(await panel(page).textContent()),
            listed: await panel(page).locator("label[data-mutation-model]").count() };
        }, async value => {
          assert.equal(value.run, made.run);
          assert.equal(value.state, "empty");
          assert.equal(value.listed, 0);
          assert.ok(!value.text.includes(shortHandle(handles.model)), "late run A model shown in run B");
          return { released: value.released, layer: "abort (panel unmounted and re-keyed by run)" };
        });
    } finally {
      holding = false;
      for (const item of held) if (item.response) await item.route.fulfill({ response: item.response }).catch(() => undefined);
      await page.unroute(matcher, handler);
    }
    return made.run;
  });

  // ---- wording summary, budget, provider calls
  await rec_.part("wording", ["MM-negative"], () => rec_.step("V09-wording", ["MM-negative"],
    "Every wording check of this run found no difference/change/rank/best word or arrow in the model panel", async () => {
      if (runB) { await chooseRun(page, runA); await openTab(page); await waitListReady(page); await openModel(page, handles.model); }
      await checkWording("final");
      return wording;
    }, async value => {
      assert.ok(value.length >= 3, `wording checks: ${value.length}`);
      assert.ok(value.every(item => item.found.length === 0));
      return value;
    }));
  budget.totalRunA = await unitsUsed(page, runA);
  budget.limitRunA = (await readApi(page, `/runs/${runA}/budget`)).expensive_calls?.limit ?? null;
  for (const id of [runA, runB].filter(Boolean)) evidence.providerCalls.push(await providerCalls(page, id));
}

// ------------------------------------------------------------------ main
const RUNNERS = { main: modeMain };

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const evidence = { schema: "m21_mutation_model_evidence@1", mode: input.mode, runs: {}, inputs: [], handles: {}, repro: null,
    budget: {}, fixtureLabels: [], providerCalls: [], partFailures: [], controls: {}, startedAt: new Date().toISOString() };
  evidenceRef.value = evidence;
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
  const providerZero = evidence.providerCalls.length > 0 && evidence.providerCalls.every(item => item.zero);
  const passed = !error && evidence.partFailures.length === 0 && offscreenComplete(proof) && proof.nonLoopbackRequests === 0 &&
    Object.keys(cases).length > 0 && Object.values(cases).every(value => value === "pass") && providerZero;
  evidence.finishedAt = new Date().toISOString();
  evidence.error = error ? String(error.stack ?? error) : null;
  evidence.requestCount = log.length;
  evidence.fixtureLabels = [...new Set(evidence.fixtureLabels)];
  fs.writeFileSync(path.join(input.artifacts, "mutation-model-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  fs.writeFileSync(path.join(input.artifacts, "mutation-model-requests.jsonl"), log.map(row => JSON.stringify(row)).join("\n") + "\n");
  const harness = Object.fromEntries(["mutation-model-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m21_case_ledger_row@1", mode: input.mode, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", cases, runId: evidence.runs.A ?? null, runs: evidence.runs,
    handles: evidence.handles, inputs: evidence.inputs, fixtureLabels: evidence.fixtureLabels, controls: evidence.controls,
    repro: evidence.repro, budget: evidence.budget, buildId: buildId(), harness,
    offscreen: proof, externalRequestCount: proof ? proof.nonLoopbackRequests : null, providerCalls: evidence.providerCalls,
    providerCallsZero: providerZero, partFailures: evidence.partFailures, error: evidence.error,
    evidenceFile: path.basename(rec_.file), startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, runs: evidence.runs, cases }) + "\n");
  if (error) process.stderr.write(`mutation-model-flow ${input.mode} failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`mutation-model-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, halfUp, expectedLimitations };
