"use strict";

// M20 mutation candidate offscreen QA (spec §10, §12 화면). Real Electron offscreen page (isOffscreen, GPU/WebGL, paint).
// Every product mutation is a Playwright locator mouse/keyboard/file-chooser/select input. Observation is read-only:
// data attributes and text of the page, renderer request/response events, Electron paint frames, downloaded bytes and
// GET reads of the loopback API. Labeled renderer-route fixtures (held late responses, request bodies altered in flight
// so that the real server refuses them) are recorded in the ledger and never produce a scientific value.
//
// Independent oracle: docs/qa/m20-mutations-20261003/preflight.txt (T1; numpy on the prepared 1MQ4 coordinates, not
// the product's own functions): ADP 5.0 Å shell residues and distances, metal (MG) contacts, the ten KLIFS sites.
// fpocket is not deterministic (fresh clock seed), so pocket expectations are read from the stored pocket_set.
//
// Mode (the full sequence: scripts/m20_offscreen_acceptance.py):
//   main  fresh root: no run → 1MQ4 → run without a prepared structure → 전처리 → request without annotation (검사하지
//         않음) → numbering map + annotation → direct + ligand shell with protection/release → allowed residues shrunk →
//         same request again (same handle) → real fpocket → pocket source → filters/sort/paging → zero candidates →
//         server refusals → report + library → late responses (result switch, run switch) → tab state → wording
//   catalytic  (M26, --plan from scripts/m26_offscreen_acceptance.py) M20 v2 with M-CSA catalytic annotations made in the
//         지식·보고서 "효소 반응 지식" area by real clicks: UK2 without a result, newest result pre-selected (never
//         submitted), per-chain prediction, chains_not_covered and checked sets, conflict / unmatched lists, release
//         ("해제됨"), seven exclusion reasons, limitation sentence 3 variants (with a stored v1 run), and the
//         "촉매 잔기 검사 안 함" mark on the M20 / M21 / M23 / M24 / M25 pickers. Reaction reference values of the
//         fixture stage are SYNTHETIC (the plan says so); the screen is compared with the stored sets.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const { waitForViewer } = require("./normal-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const STRUCTURE = path.join(REPO, "backend/tests/fixtures/public_1mq4.cif");
const PREFLIGHT = path.join(REPO, "docs/qa/m20-mutations-20261003/preflight.txt");
const MODES = ["main", "catalytic"];
const TAB = "단백질 공학";
const ACCESSION = "O14965";
const TOOL = "generate_mutation_candidates";
const RESIDUE_FIELDS = ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"];
const ADP = { model_number: 1, chain_auth: "A", chain_label: "E", seq_auth: 2001, seq_label: null, icode: "", resname: "ADP" };
const MG2088 = { model_number: 1, chain_auth: "A", chain_label: "C", seq_auth: 2088, seq_label: null, icode: "", resname: "MG" };
const ALL = "ACDEFGHIKLMNPQRSTVWY";
// Spec §11, verbatim.
const LIMITATIONS = [
  "후보는 위치와 바꿀 잔기의 조합 목록이며 구조 모델링·에너지·점수를 계산하지 않았다.",
  "이 목록은 변이의 효과(안정성·결합·활성)를 뜻하지 않으며 순위나 추천이 아니다.",
  "보호 잔기는 사용자 지정·KLIFS 주요 부위·금속 근접·이황화 결합 기준으로만 판정했고 촉매 잔기 데이터베이스는 사용하지 않았다(없음).",
  "거리는 준비된 구조의 저장 좌표에서 계산한 중원자 사이 최소 거리(Å)이며 결합이나 상호작용을 뜻하지 않는다.",
  "바꿀 히스티딘의 양성자 상태와 변이 구조의 형태는 정하지 않았다.",
];
const NO_RUN_REASON = "run이 없습니다. 구조 분석 탭에서 run을 먼저 고르세요.";
const NO_PREPARED_REASON = "이 run에 전처리 구조가 없습니다. 구조 분석 탭에서 구조를 먼저 전처리하세요.";
const KLIFS_NOTICE = "KLIFS 주요 부위 보호를 검사하지 않음";
const LIGAND_REQUIRED_TEXT = "리간드 껍질을 쓰려면 리간드를 고르세요.";
const CONFLICT_TEXT = "같은 잔기를 보호와 해제에 모두 넣을 수 없습니다";
// Korean names the screen must show for the refused requests (spec §2 reason codes).
const REFUSALS = {
  structure_invalid: "이 run의 전처리 구조가 아님",
  annotation_invalid: "이 run의 참조 주석이 아님",
  protect_release_conflict: "같은 잔기가 보호 목록과 해제 목록에 모두 있음",
  ligand_required: "리간드 껍질에는 리간드 선택이 필요함",
};
const FORBIDDEN = /친화|ΔΔG|안정성|순위|추천|최적|개선|활성|예측|좋은|유망|안전|\brank|\bbest|optimal|improv|recommend|affinity|stabili|predict/gi;
const ALTER_LABEL = "QA refusal fixture (labeled renderer route): the generate_mutation_candidates request body is altered " +
  "in flight so that the real server refuses it; the server reply is shown unchanged";
const HOLD_LABEL = "QA held-response fixture (labeled renderer route; unchanged backend bytes released late)";
const PROVIDER_EVENT_TYPES = new Set(["egress", "egress_budget_settled", "viewer_dispatch_started"]);

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const shortHandle = handle => handle.split("/").at(-1).slice(0, 12);
const sameResidue = (a, b) => !!a && !!b && RESIDUE_FIELDS.every(field => a[field] === b[field]);
const resKey = ref => `${ref.resname}${ref.seq_auth}`;

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, "set-hash": null, plan: null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2);
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode) || (value.mode === "main" && !value["set-hash"]) ||
      (value.mode === "catalytic" && !value.plan)) throw new Error(
    `Usage: mutation-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> (main: --set-hash <active reference set hash>; ` +
    "catalytic: --plan <m26 plan.json>) [--url http://127.0.0.1:3000]. Needs a fresh runs root. Full sequences: " +
    "scripts/m20_offscreen_acceptance.py, scripts/m26_offscreen_acceptance.py.");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  value.artifacts = path.resolve(value.artifacts);
  value.url = new URL("/", value.url).toString();
  value.planData = value.plan ? JSON.parse(fs.readFileSync(value.plan, "utf8")) : null;
  return value;
}

// ------------------------------------------------------------------ independent oracle (T1 preflight)
function preflightOracle() {
  const text = fs.readFileSync(PREFLIGHT, "utf8");
  const block = (start, end) => {
    const from = text.indexOf(start);
    assert.ok(from >= 0, `preflight lacks ${start}`);
    const to = text.indexOf(end, from + start.length);
    assert.ok(to > from, `preflight lacks ${end}`);
    return text.slice(from + start.length, to);
  };
  const shell = [...block("≤5.0 Å (chain A, 잔기, 최소 거리 Å):", "(KLIFS 주석 부위 중 껍질 안").matchAll(/([A-Z]{3})(\d+) +(\d+\.\d+)/g)]
    .map(m => ({ resname: m[1], seqAuth: Number(m[2]), distance: Number(m[3]) }));
  const metal = [...block("폴리머 잔기 중원자–금속 최소 거리 ≤5.0 Å:", "metal_contact 기본 3.0 Å").matchAll(/([A-Z]{3}) A(\d+) (\d+\.\d+) \(MG(\d+)\)/g)]
    .map(m => ({ resname: m[1], seqAuth: Number(m[2]), distance: Number(m[3]), metal: Number(m[4]) }));
  const sites = [...block("1MQ4 주석 부위(M16 preflight와 같음):", "결론:").matchAll(/(\S+\.\d+) ([A-Z]{3})(\d+)/g)]
    .map(m => ({ label: m[1], resname: m[2], seqAuth: Number(m[3]) }));
  assert.equal(shell.length, 20, "preflight ADP 5.0 Å shell rows");
  assert.equal(metal.length, 7, "preflight metal rows");
  assert.equal(sites.length, 10, "preflight KLIFS sites");
  return { file: fileRecord(PREFLIGHT), shell, metal, sites, metalWithin3: metal.filter(row => row.distance <= 3.0) };
}
/** "x.yy Å" with ROUND_HALF_UP on the decimal string of the stored value (independent of the product helper). */
function halfUp2(value) {
  const text = String(value);
  assert.ok(!/e/i.test(text), `exponent in ${text}`);
  const [whole, frac = ""] = text.split(".");
  let scaled = BigInt(whole + frac.slice(0, 2).padEnd(2, "0"));
  if (frac.length > 2 && frac[2] >= "5") scaled += 1n;
  const body = scaled.toString().padStart(3, "0");
  return `${body.slice(0, -2)}.${body.slice(-2)} Å`;
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
const setPath = (run, handle, tail = "") => `/runs/${run}/mutation_candidate_sets/${enc(handle)}${tail}`;
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
async function mutationSetCount(page, run) {
  return (await readApi(page, `/runs/${run}/mutation_candidate_sets?offset=0&limit=100`)).total;
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
    rows.push({ at: Date.now(), method: request.method(), path: url.pathname, search: url.search,
      api: url.pathname.startsWith("/api/"),
      tool: request.method() === "POST" ? (() => { try { return request.postDataJSON()?.tool ?? null; } catch { return null; } })() : null });
  });
  return rows;
}

// ------------------------------------------------------------------ evidence
function recorder(session, input, evidence) {
  const { app, page, artifacts } = session;
  const file = path.join(artifacts, `mutation-${input.mode}.jsonl`);
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
      const html = await page.evaluate(() => document.querySelector('[data-testid="mutation-panel"]')?.outerHTML.slice(0, 80000) ?? "")
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
/** Every new control used at least once, with what was observed right after. */
function control(evidence, id, observed) { (evidence.controls[id] ??= []).push(observed); }

// ------------------------------------------------------------------ tabs, runs, structure screen
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
async function uploadLoad(page, file, provenance) {
  await page.getByRole("tab", { name: /^run/i }).click();
  const before = (await snapshot(page))?.sourceHandle ?? null;
  const chooser = page.waitForEvent("filechooser", { timeout: 30000 });
  await page.locator('input[type="file"]').first().click();
  await (await chooser).setFiles(file);
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).waitFor({ timeout: 30000 });
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    /\/commands$/.test(new URL(response.url()).pathname) && response.request().postDataJSON()?.tool === "load_structure",
  { timeout: 90000 });
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).click();
  const loadArgs = (await posted).request().postDataJSON().args;
  const viewer = await waitForViewer(page, value => !!value.sourceHandle && value.sourceHandle !== before &&
    value.sourceHandle.includes("/structure/") && value.catalogReady === true, 90000);
  return { handle: viewer.sourceHandle, loadArgs: { model_index: loadArgs.model_index },
    file: { name: path.basename(file), ...fileRecord(file), provenance } };
}
async function prepareManual(page) {
  const back = page.getByRole("button", { name: "최신 구조로 돌아가기", exact: true });
  if (await back.isVisible().catch(() => false)) await back.click();
  const row = page.locator(".mw-workflow-row").filter({ has: page.getByRole("button", { name: "전처리", exact: true }) });
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    /\/commands$/.test(new URL(response.url()).pathname) && response.request().postDataJSON()?.tool === "prepare_structure",
  { timeout: 90000 });
  await row.getByRole("button", { name: "전처리", exact: true }).click();
  const response = await posted;
  const body = await response.json();
  assert.equal(body.ok, true, `prepare failed: ${JSON.stringify(body).slice(0, 400)}`);
  const prepared = body.handle.handle;
  assert.match(prepared, /\/prepared_structure\//);
  await waitForViewer(page, value => value.sourceHandle === prepared && value.catalogReady === true, 90000);
  return { prepared, args: response.request().postDataJSON().args };
}

// ------------------------------------------------------------------ numbering + annotation (as annotation-flow.cjs)
const numbering = page => page.locator("section.mw-numbering");
const nTestId = (page, id) => numbering(page).locator(`[data-testid="${id}"]`);
async function nWaitArea(page, name, state, timeout = 60000) {
  return waitFor(page, async () => await numbering(page).locator(`[data-numbering-area="${name}"]`)
    .getAttribute("data-state", { timeout: 2000 }).catch(() => null) === state ? true : null, `${name} area ${state}`, timeout);
}
const sitePanel = page => page.locator('[data-testid="site-annotation-panel"]');
const sTestId = (page, id) => sitePanel(page).locator(`[data-testid="${id}"]`);

// ------------------------------------------------------------------ fpocket (as pocket-flow.cjs)
const pocketPanel = page => page.locator('section[data-pocket-panel="main"]');
async function detectPockets(page, run, prepared) {
  const panel = pocketPanel(page);
  const select = panel.getByRole("combobox", { name: "포켓 검출 소스" });
  await waitFor(page, async () => (await select.locator("option").evaluateAll(items => items.map(item => item.value)))
    .includes(prepared) ? true : null, "prepared pocket source offered", 60000);
  if (await select.inputValue() !== prepared) await select.selectOption(prepared);
  const button = panel.getByRole("button", { name: "포켓 검출 실행" });
  await waitFor(page, async () => await button.isEnabled() ? true : null, "포켓 검출 실행 enabled", 60000);
  const submitted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/jobs`, { timeout: 60000 });
  await button.click();
  const job = await (await submitted).json();
  assert.equal(job.protocol_id, "fpocket_detect_v1");
  const approval = panel.getByRole("button", { name: "포켓 계산 승인 후 시작" });
  let approvalSeen = false;
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    if (await approval.isVisible().catch(() => false)) { approvalSeen = true; break; }
    const shown = await panel.locator("[data-pocket-job-status]").getAttribute("data-pocket-job-status").catch(() => null);
    if (["running", "done", "failed", "cancelled", "interrupted"].includes(shown)) break;
    await page.waitForTimeout(100);
  }
  if (approvalSeen) await approval.click();
  await panel.locator('[data-pocket-job-status="done"], [data-pocket-job-status="failed"], [data-pocket-job-status="cancelled"], [data-pocket-job-status="interrupted"]')
    .first().waitFor({ timeout: 240000 });
  const durable = await readApi(page, `/runs/${run}/jobs/${job.job_id}`);
  assert.equal(durable.status, "done", `pocket job did not finish: ${JSON.stringify(durable.failure ?? durable.status)}`);
  const set = durable.artifacts?.pocket_set;
  assert.match(set ?? "", /\/pocket_set\//);
  return { jobId: job.job_id, set, approvalSeen };
}

// ------------------------------------------------------------------ mutation panel
const panel = page => page.locator('[data-testid="mutation-panel"]');
const testId = (page, id) => panel(page).locator(`[data-testid="${id}"]`);
const panelState = page => panel(page).getAttribute("data-mutation-state", { timeout: 2000 }).catch(() => null);
async function waitState(page, states, timeout = 60000) {
  const wanted = Array.isArray(states) ? states : [states];
  return waitFor(page, async () => { const state = await panelState(page); return wanted.includes(state) ? state : null; },
    `mutation panel ${wanted.join("|")}`, timeout);
}
async function openTab(page) {
  await selectTab(page, TAB);
  await panel(page).waitFor({ timeout: 15000 });
}
/** Tab entered, every run list read (structure radios enabled, result list ready). */
async function openReady(page) {
  await openTab(page);
  await waitState(page, ["ready", "scientific_null"]);
  await waitFor(page, async () => await panel(page).locator('[data-mutation-area="sets"]').getAttribute("data-state") === "ready"
    && await panel(page).locator('[data-testid="mutation-structures"] input').first().isEnabled() ? true : null,
  "mutation lists ready", 60000);
}
async function chooseStructure(page, prepared) {
  await panel(page).locator(`label[data-mutation-structure="${prepared}"] input`).check();
  control(evidenceRef.value, "mutation-structures", { checked: prepared });
  await waitFor(page, async () => (await testId(page, "mutation-ligand").locator("option").count()) > 1 ? true : null,
    "structure residues read (ligand options)", 60000);
}
const evidenceRef = { value: null };
async function selectOptions(locator) {
  return locator.locator("option").evaluateAll(items => items.map(item => ({ value: item.value, text: item.textContent.trim(),
    disabled: item.disabled })));
}
async function chooseLigand(page, resname, seq) {
  const select = testId(page, "mutation-ligand");
  const found = (await selectOptions(select)).filter(item => item.text.startsWith(`${resname} A:${seq} ·`));
  assert.equal(found.length, 1, `ligand option ${resname} ${seq}`);
  await select.selectOption(found[0].value);
  control(evidenceRef.value, "mutation-ligand", { chosen: found[0].text });
  return found[0];
}
async function setCheck(page, id, on) {
  const box = testId(page, id);
  if (await box.isChecked() !== on) await box.click();
  assert.equal(await box.isChecked(), on);
  control(evidenceRef.value, id, { checked: on });
}
async function fillText(page, id, value) {
  await testId(page, id).fill(value);
  control(evidenceRef.value, id, { value });
}
/** Pick one residue in a picker (select + 넣기) by its displayed auth text (the option keeps the 7 fields). */
async function pickResidue(page, picker, resname, seq) {
  const select = testId(page, `mutation-pick-${picker}`);
  const found = (await selectOptions(select)).filter(item => item.text.startsWith(`${resname} A:${seq} ·`));
  assert.equal(found.length, 1, `${picker} option ${resname} ${seq}: ${found.length}`);
  const before = Number(await testId(page, `mutation-picker-${picker}`).getAttribute("data-count"));
  await select.selectOption(found[0].value);
  await testId(page, `mutation-add-${picker}`).click();
  await waitFor(page, async () => Number(await testId(page, `mutation-picker-${picker}`).getAttribute("data-count")) === before + 1
    ? true : null, `${picker} count +1`, 10000);
  control(evidenceRef.value, `mutation-pick-${picker}`, { picked: found[0].text });
  control(evidenceRef.value, `mutation-add-${picker}`, { count: before + 1 });
}
async function removeResidue(page, picker, resname, seq) {
  const item = testId(page, `mutation-chosen-${picker}`).locator(`li[data-mutation-residue="${resname} A:${seq}"]`);
  const before = Number(await testId(page, `mutation-picker-${picker}`).getAttribute("data-count"));
  await item.locator(`[data-testid="mutation-remove-${picker}"]`).click();
  await waitFor(page, async () => Number(await testId(page, `mutation-picker-${picker}`).getAttribute("data-count")) === before - 1
    ? true : null, `${picker} count -1`, 10000);
  control(evidenceRef.value, `mutation-remove-${picker}`, { removed: `${resname} A:${seq}`, count: before - 1 });
}
async function setAllowed(page, codes) {
  await testId(page, "mutation-allowed-none").click();
  control(evidenceRef.value, "mutation-allowed-none", { clicked: true });
  for (const code of codes) await testId(page, "mutation-allowed").getByRole("checkbox", { name: `허용 잔기 ${code}`, exact: true }).check();
  control(evidenceRef.value, "mutation-allowed", { checked: codes.join("") });
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
    new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === TOOL,
  { timeout: 120000 });
  await testId(page, "mutation-create").click();
  control(evidenceRef.value, "mutation-create", { clicked: true });
  const response = await posted;
  const body = await response.json();
  const args = response.request().postDataJSON().args;
  if (body.ok !== true) {
    await testId(page, "mutation-create-error").waitFor({ timeout: 30000 });
    return { ok: false, status: response.status(), body, args };
  }
  const handle = body.handle.handle;
  await panel(page).locator(`[data-testid="mutation-create-done"][data-mutation-new-set="${handle}"]`).waitFor({ timeout: 30000 });
  await panel(page).locator(`[data-testid="mutation-detail"][data-mutation-detail="${handle}"]`).waitFor({ timeout: 60000 });
  await waitState(page, ["ready", "scientific_null"]);
  return { ok: true, status: response.status(), body, args, handle };
}
async function openSet(page, handle) {
  const radio = panel(page).locator(`label[data-mutation-set="${handle}"] input`);
  await radio.check();
  control(evidenceRef.value, "mutation-sets", { checked: handle });
  await panel(page).locator(`[data-testid="mutation-detail"][data-mutation-detail="${handle}"]`).waitFor({ timeout: 60000 });
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
async function candidateRows(page) {
  if (!await testId(page, "mutation-candidates").count()) return [];
  return testId(page, "mutation-candidates").locator("tr[data-mutation-candidate]").evaluateAll(items => items.map(item => ({
    index: Number(item.getAttribute("data-mutation-candidate")), position: Number(item.getAttribute("data-position-index")),
    from: item.getAttribute("data-from"), to: item.getAttribute("data-to") })));
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
      assert.equal(shown.distanceText, halfUp2(row.ligand_min_distance_A), `position ${row.index} distance`);
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
  else await testId(page, "mutation-positions-empty").waitFor({ timeout: 10000 });
  return { query, total: api.total, offset: api.offset, indices: api.rows.map(row => row.index) };
}
async function waitCandidates(page, run, handle, query, label) {
  const api = await readApi(page, setPath(run, handle, `/candidates?${query}`));
  await waitFor(page, async () => {
    const shown = await pager(page, "mutation-candidates");
    if (!shown || shown.total !== api.total || shown.offset !== api.offset) return null;
    const rows = await candidateRows(page);
    return rows.map(row => row.index).join(",") === api.rows.map(row => row.index).join(",") ? true : null;
  }, `${label}: candidate table = stored page (${query})`, 30000);
  const ui = await candidateRows(page);
  api.rows.forEach((row, i) => {
    assert.equal(ui[i].position, row.position_index);
    assert.equal(ui[i].from, row.from);
    assert.equal(ui[i].to, row.to);
  });
  return { query, total: api.total, offset: api.offset, first: api.rows[0]?.index ?? null, rows: api.rows.length };
}
async function selectFilter(page, id, value) {
  await testId(page, id).selectOption(value);
  control(evidenceRef.value, id, { value });
}
/** Panel text outside the fixed limitation sentences, and the limitation sentences shown. */
async function panelWording(page) {
  return panel(page).evaluate(node => {
    const copy = node.cloneNode(true);
    const limits = [...copy.querySelectorAll("[data-limitation]")].map(item => item.textContent.trim());
    for (const item of copy.querySelectorAll('[data-testid="mutation-limitations"]')) item.remove();
    return { text: copy.textContent, limits };
  });
}
function forbiddenIn(text) { return [...text.matchAll(FORBIDDEN)].map(match => match[0]); }
async function noControls(page) {
  return { state: await panelState(page), text: clean(await panel(page).textContent()),
    controls: await panel(page).locator("button, input, select, textarea, a, table").count() };
}

// ------------------------------------------------------------------ mode main
async function modeMain(session, input, rec_, evidence, log) {
  const { page, app } = session;
  const oracle = preflightOracle();
  evidence.inputs.push({ name: "preflight.txt", ...oracle.file, provenance: "M20 T1 independent numpy oracle (committed QA text)" });
  const handles = evidence.handles;
  const wording = [];
  const checkWording = async label => {
    const seen = await panelWording(page);
    const found = forbiddenIn(seen.text);
    wording.push({ label, found, chars: seen.text.length });
    assert.deepEqual(found, [], `${label}: forbidden wording ${found.join(", ")}`);
    return seen;
  };
  await waitForBoot(page);

  // ---- no run (fresh root): reason only
  await rec_.part("no-run", ["M-no-run"], () => rec_.step("M00-no-run", ["M-no-run"],
    "Fresh root: click 단백질 공학 before any run exists → 사용할 수 없음 + reason only (no numbers, no controls)", async () => {
      const runs = await readApi(page, "/runs");
      const before = Date.now();
      await openTab(page);
      await testId(page, "mutation-no-run").waitFor({ timeout: 15000 });
      await page.waitForTimeout(1500);
      return { runs: runs.length, ...await noControls(page), reason: clean(await testId(page, "mutation-no-run").textContent()),
        reads: log.filter(row => row.at >= before && row.path.includes("mutation_candidate_sets")).length };
    }, async value => {
      assert.equal(value.runs, 0, "mode main needs a fresh runs root");
      assert.equal(value.state, "unavailable");
      assert.ok(value.reason.includes("사용할 수 없음") && value.reason.includes(NO_RUN_REASON), value.reason);
      assert.ok(!/\d/.test(value.text), `a number is shown: ${value.text}`);
      assert.equal(value.controls, 0);
      assert.equal(value.reads, 0);
      return { reason: value.reason };
    }));

  // ---- run A: 1MQ4, then a run without a prepared structure, then 전처리
  const runA = await rec_.step("M01-new-run", [], "Click 구조 분석, 새 run (run A)", () => newRun(page), async id => ({ run: id }));
  evidence.runs.A = runA;
  const loaded = await rec_.step("M02-upload", ["M-load-prepare"], "Choose public_1mq4.cif, click 구조 불러오기",
    () => uploadLoad(page, STRUCTURE, "public PDB entry 1MQ4 (repository fixture; Aurora A kinase domain with ADP, PO4, 2 MG)"),
    async value => value);
  evidence.inputs.push(loaded.file);
  handles.structure = loaded.handle;
  await rec_.part("unprepared", ["M-unprepared"], () => rec_.step("M03-unprepared", ["M-unprepared"],
    "Click 단백질 공학 with a loaded but not prepared structure → 사용할 수 없음 with the reason; no numbers, no controls, no tool call",
    async () => {
      const before = Date.now();
      await openTab(page);
      await waitState(page, "unavailable", 30000);
      await testId(page, "mutation-unavailable").waitFor({ timeout: 15000 });
      return { ...await noControls(page), reason: clean(await testId(page, "mutation-unavailable").textContent()),
        posts: log.filter(row => row.at >= before && row.method === "POST").length };
    }, async value => {
      assert.ok(value.reason.includes("사용할 수 없음") && value.reason.includes(NO_PREPARED_REASON), value.reason);
      assert.ok(!/\d/.test(value.text), `a number is shown: ${value.text}`);
      assert.equal(value.controls, 0);
      assert.equal(value.posts, 0);
      return { reason: value.reason };
    }));
  const prepared = await rec_.step("M04-prepare", ["M-load-prepare"], "Click 구조 분석, 전처리 (displayed default policies)",
    async () => { await selectTab(page, "구조 분석"); return prepareManual(page); }, async value => value);
  handles.prepared = prepared.prepared;
  evidence.repro = { run: runA, loadArgs: loaded.loadArgs, prepareArgs: { ...prepared.args, structure: "<loaded structure>" } };

  // ---- S0: ligand shell without annotation (검사하지 않음), ligand chosen explicitly
  let s0 = null;
  await rec_.part("not-checked", ["M-ligand-explicit", "M-not-checked", "M-shell-oracle"], async () => {
    await rec_.step("S01-ligand-explicit", ["M-ligand-explicit", "M-not-checked"],
      "Click 단백질 공학, choose the prepared structure, tick 리간드 껍질: ADP/PO4 offered, none chosen, 후보 만들기 blocked; " +
      "the KLIFS 검사하지 않음 notice is shown", async () => {
        await openReady(page);
        await chooseStructure(page, handles.prepared);
        await setCheck(page, "mutation-source-ligand-shell", true);
        return { ligandValue: await testId(page, "mutation-ligand").inputValue(), options: await selectOptions(testId(page, "mutation-ligand")),
          createDisabled: await testId(page, "mutation-create").isDisabled(), errors: await requestErrors(page),
          notice: clean(await testId(page, "mutation-klifs-notice").textContent()),
          annotation: await testId(page, "mutation-annotation").inputValue(), radius: await testId(page, "mutation-radius").inputValue() };
      }, async value => {
        const names = value.options.filter(item => item.value !== "").map(item => item.text.split(" ")[0]).sort();
        assert.deepEqual(names, ["ADP", "PO4"]);
        assert.equal(value.ligandValue, "", "a ligand was chosen automatically");
        assert.equal(value.createDisabled, true);
        assert.ok(value.errors.includes(LIGAND_REQUIRED_TEXT), value.errors.join(" | "));
        assert.ok(value.notice.includes(KLIFS_NOTICE), value.notice);
        assert.equal(value.annotation, "");
        assert.equal(value.radius, "5");
        return value;
      });
    s0 = await rec_.step("S02-create-shell", ["M-ligand-explicit", "M-not-checked"],
      "Choose ADP in 리간드 (not the first option), click 후보 만들기 → result opens", async () => {
        await chooseLigand(page, "ADP", 2001);
        return create(page, runA);
      }, async value => {
        assert.equal(value.ok, true, JSON.stringify(value.body).slice(0, 400));
        assert.ok(sameResidue(value.args.ligand, ADP), JSON.stringify(value.args.ligand));
        assert.deepEqual(value.args.sources, { pocket: null, ligand_shell: { radius_A: 5 }, residues: [] });
        assert.equal(value.args.annotation, null);
        assert.equal(value.args.numbering_map, null);
        assert.equal(value.args.allowed_residues, ALL);
        assert.equal(value.args.structure, handles.prepared);
        return { handle: value.handle, args: value.args };
      });
    handles.s0 = s0.handle;
    evidence.repro.flowSet = s0.handle;
    evidence.repro.args = { ...s0.args, structure: "<prepared structure>" };
    await rec_.step("S03-not-checked", ["M-not-checked"],
      "Read the check table and the position table: KLIFS 주요 부위 검사하지 않음 (not_checked, annotation_not_given), KLIFS cells "
      + "— (검사하지 않음), list row KLIFS 검사하지 않음", async () => {
        const detail = await storedSet(page, runA, s0.handle);
        const row = panel(page).locator(`[data-testid="mutation-checks"] tr[data-mutation-check="klifs_key_sites"]`);
        return { detail, rowStatus: await row.getAttribute("data-check-status"), rowText: clean(await row.textContent()),
          klifsCells: await testId(page, "mutation-positions").locator("tr[data-mutation-position] td:nth-child(9)").allInnerTexts(),
          listStatus: await panel(page).locator(`label[data-mutation-set="${s0.handle}"]`).getAttribute("data-klifs-status"),
          listText: clean(await panel(page).locator(`label[data-mutation-set="${s0.handle}"]`).textContent()),
          catalytic: await panel(page).locator('tr[data-mutation-check="catalytic_residue_database"]').getAttribute("data-check-status") };
      }, async value => {
        const klifs = value.detail.result.protection_checks.klifs_key_sites;
        assert.deepEqual(klifs, { status: "not_checked", reason: "annotation_not_given", annotation: null, annotated_sites: null, absent_sites: null });
        assert.equal(value.rowStatus, "not_checked");
        assert.ok(value.rowText.includes("검사하지 않음") && value.rowText.includes("annotation_not_given"), value.rowText);
        assert.ok(value.klifsCells.length > 0 && value.klifsCells.every(text => text === "— (검사하지 않음)"), value.klifsCells.join("|"));
        assert.equal(value.listStatus, "not_checked");
        assert.ok(value.listText.includes("KLIFS 주요 부위 검사하지 않음"), value.listText);
        assert.equal(value.catalytic, "not_available");
        const positions = await storedPositions(page, runA, s0.handle);
        assert.ok(positions.every(row => row.protection.klifs_sites === null && !row.exclusion_reasons.includes("klifs_key_site")));
        return { klifs, rowText: value.rowText };
      });
    await rec_.step("S04-shell-oracle", ["M-shell-oracle"],
      "Stored + shown positions equal the T1 oracle: 20 residues within 5.0 Å of ADP, distances, MG contact exclusions (ASN261, ASP274)",
      async () => ({ detail: await storedSet(page, runA, s0.handle), positions: await storedPositions(page, runA, s0.handle),
        shown: await waitPositions(page, runA, s0.handle, "sort=order&offset=0&limit=50", true, "S0") }), async value => {
        const stored = new Map(value.positions.map(row => [resKey(row.residue), row]));
        assert.deepEqual([...stored.keys()].sort(), oracle.shell.map(row => `${row.resname}${row.seqAuth}`).sort());
        let maxDelta = 0;
        for (const want of oracle.shell) {
          const row = stored.get(`${want.resname}${want.seqAuth}`);
          maxDelta = Math.max(maxDelta, Math.abs(row.ligand_min_distance_A - want.distance));
          assert.deepEqual(row.sources, [{ kind: "ligand_shell", radius_A: 5 }]);
        }
        assert.ok(maxDelta <= 1e-9, `distance differs from the oracle by ${maxDelta}`);
        const metalRows = value.positions.filter(row => row.exclusion_reasons.includes("metal_contact"));
        assert.deepEqual(metalRows.map(row => resKey(row.residue)).sort(), oracle.metalWithin3.map(row => `${row.resname}${row.seqAuth}`).sort());
        for (const row of metalRows) {
          const want = oracle.metalWithin3.find(item => `${item.resname}${item.seqAuth}` === resKey(row.residue));
          assert.ok(sameResidue(row.protection.metal.metal_residue, MG2088));
          assert.ok(Math.abs(row.protection.metal.min_distance_A - want.distance) <= 1e-9);
          assert.equal(row.status, "excluded");
        }
        const counts = value.detail.result.counts;
        assert.equal(counts.positions, 20);
        assert.equal(counts.excluded_positions, 2);
        assert.equal(counts.candidates, 18 * 19);
        assert.equal(counts.exclusion_reason_counts.metal_contact, 2);
        assert.equal(value.detail.result.ligand.heavy_atom_count, 27);
        const shownCounts = clean(await testId(page, "mutation-counts").textContent());
        assert.equal(shownCounts, `위치 ${counts.positions}개 · 후보 위치 ${counts.candidate_positions}개 · 제외 ${counts.excluded_positions}개 · ` +
          `해제 ${counts.released_positions}개 · 후보 ${counts.candidates}개`);
        const seen = await checkWording("S0 opened");
        assert.deepEqual(seen.limits, LIMITATIONS);
        return { maxDelta, counts, metal: metalRows.map(row => [resKey(row.residue), row.protection.metal.min_distance_A]) };
      });
  });

  // ---- numbering map (지식·보고서) + annotation (구조 분석), real inputs
  await rec_.part("numbering-annotation", ["M-numbering-annotation"], async () => {
    const map = await rec_.step("A01-numbering", ["M-numbering-annotation"],
      "Click 지식·보고서, choose the prepared structure, chain A, tick 이 PDB ID가 맞습니다 (1MQ4), 실행", async () => {
        await selectTab(page, "지식·보고서");
        await numbering(page).waitFor({ timeout: 15000 });
        await nWaitArea(page, "create", "ready");
        const select = nTestId(page, "numbering-structure");
        if (await select.inputValue() !== "") await select.selectOption("");
        await select.selectOption(handles.prepared);
        await waitFor(page, async () => await nTestId(page, "numbering-chain-A").count() === 1 ? true : null, "chain A", 30000);
        await waitFor(page, async () => /업로드 원본|PDB ID가 없습니다|읽지 못했습니다/.test(await nTestId(page, "numbering-pdb-hint").textContent())
          ? true : null, "PDB ID suggestion", 30000);
        await nTestId(page, "numbering-chain-A").check();
        await nTestId(page, "numbering-pdb-confirm").check();
        await waitFor(page, async () => (await nTestId(page, "numbering-accession-A").textContent()).includes(ACCESSION) ? true : null,
          "SIFTS prefill", 30000);
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runA}/commands` &&
          response.request().postDataJSON()?.tool === "map_residue_numbering", { timeout: 180000 });
        await nTestId(page, "numbering-run").click();
        const body = await (await posted).json();
        await nTestId(page, "numbering-run-result").filter({ hasText: "대응을 만들었습니다" }).waitFor({ timeout: 30000 });
        return body;
      }, async body => {
        assert.equal(body.ok, true, JSON.stringify(body).slice(0, 400));
        const listed = (await readApi(page, `/runs/${runA}/numbering_maps?offset=0&limit=100`)).rows.find(row => row.handle === body.handle.handle);
        assert.equal(listed.structure, handles.prepared);
        assert.equal(listed.set_hash, input["set-hash"]);
        return { handle: body.handle.handle, setHash: listed.set_hash };
      });
    handles.map = map.handle.handle;
    const annotation = await rec_.step("A02-annotation", ["M-numbering-annotation"],
      "Click 구조 분석: choose the map radio and 접촉 결과 없이, click 주석 만들기 (annotate_reference_sites)", async () => {
        await selectTab(page, "구조 분석");
        await sitePanel(page).waitFor({ timeout: 30000 });
        const mapRadio = sTestId(page, "site-annotation-maps").locator(`label[data-site-map="${handles.map}"] input`);
        await mapRadio.waitFor({ timeout: 30000 });
        await mapRadio.check();
        await sTestId(page, "site-annotation-contacts").locator('label[data-site-contact="none"] input').check();
        await waitFor(page, async () => await sTestId(page, "site-annotation-create").isEnabled() ? true : null, "주석 만들기 enabled", 15000);
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runA}/commands` &&
          response.request().postDataJSON()?.tool === "annotate_reference_sites", { timeout: 60000 });
        await sTestId(page, "site-annotation-create").click();
        const response = await posted;
        return { body: await response.json(), args: response.request().postDataJSON().args };
      }, async value => {
        assert.equal(value.body.ok, true, JSON.stringify(value.body).slice(0, 400));
        assert.deepEqual(value.args, { numbering_map: handles.map, contacts: null });
        const detail = await readApi(page, `/runs/${runA}/site_annotations/detail?handle=${enc(value.body.handle.handle)}`);
        const annotated = detail.annotation.groups.flatMap(group => group.sites.filter(site => site.status === "annotated"));
        assert.deepEqual(annotated.map(site => `${site.klifs_label} ${site.residue.resname}${site.residue.seq_auth}`).sort(),
          oracle.sites.map(site => `${site.label} ${site.resname}${site.seqAuth}`).sort());
        return { handle: value.body.handle.handle, annotated: annotated.length };
      });
    handles.annotation = annotation.body.handle.handle;
  });

  // ---- S1: direct + ligand shell with protection and release; the annotation is pre-selected on entry
  let s1 = null;
  if (handles.annotation) await rec_.part("protect-release", ["M-reread-on-entry", "M-protect-release"], async () => {
    await rec_.step("P01-reread", ["M-reread-on-entry"],
      "Click 단백질 공학 (panel remounts): every list is read again; choosing the structure pre-selects the newest annotation and its map",
      async () => {
        const before = Date.now();
        await openReady(page);
        const reads = log.filter(row => row.at >= before && row.method === "GET").map(row => row.path);
        await chooseStructure(page, handles.prepared);
        return { reads, annotation: await testId(page, "mutation-annotation").inputValue(),
          map: await testId(page, "mutation-numbering-map").inputValue(), notice: await testId(page, "mutation-klifs-notice").count(),
          posts: log.filter(row => row.at >= before && row.method === "POST").length };
      }, async value => {
        for (const tail of ["/mutation_candidate_sets", "/numbering_maps", "/site_annotations", "/pockets", "/events"])
          assert.ok(value.reads.some(route => route === `/api/runs/${runA}${tail}`), `no GET ${tail} on tab entry`);
        assert.equal(value.annotation, handles.annotation);
        assert.equal(value.map, handles.map);
        assert.equal(value.notice, 0);
        assert.equal(value.posts, 0);
        return { annotation: value.annotation, map: value.map, reads: [...new Set(value.reads)] };
      });
    await rec_.step("P02-conflict", ["M-protect-release"],
      "Tick 리간드 껍질 + ADP, tick 직접 선택 + ARG A:126, 보호 LEU A:139, 해제 LEU A:139: the screen blocks the conflict; " +
      "빼기 removes it from 해제", async () => {
        await setCheck(page, "mutation-source-ligand-shell", true);
        await chooseLigand(page, "ADP", 2001);
        await setCheck(page, "mutation-source-user", true);
        await pickResidue(page, "user", "ARG", 126);
        await pickResidue(page, "protect", "LEU", 139);
        await pickResidue(page, "release", "LEU", 139);
        const blocked = { errors: await requestErrors(page), disabled: await testId(page, "mutation-create").isDisabled() };
        await removeResidue(page, "release", "LEU", 139);
        return { blocked, after: await requestErrors(page) };
      }, async value => {
        assert.equal(value.blocked.disabled, true);
        assert.ok(value.blocked.errors.some(text => text.startsWith(CONFLICT_TEXT)), value.blocked.errors.join(" | "));
        assert.ok(!value.after.some(text => text.startsWith(CONFLICT_TEXT)));
        return value;
      });
    s1 = await rec_.step("P03-create", ["M-protect-release"],
      "Pick 해제 ASN A:261 and ARG A:126, click 후보 만들기", async () => {
        await pickResidue(page, "release", "ASN", 261);
        await pickResidue(page, "release", "ARG", 126);
        return create(page, runA);
      }, async value => {
        assert.equal(value.ok, true, JSON.stringify(value.body).slice(0, 400));
        assert.equal(value.args.annotation, handles.annotation);
        assert.equal(value.args.numbering_map, handles.map);
        assert.deepEqual(value.args.protected_residues.map(resKey), ["LEU139"]);
        assert.deepEqual(value.args.released_residues.map(resKey), ["ASN261", "ARG126"]);
        assert.deepEqual(value.args.sources.residues.map(resKey), ["ARG126"]);
        return { handle: value.handle, args: value.args };
      });
    handles.s1 = s1.handle;
    await rec_.step("P04-reasons", ["M-protect-release"],
      "Read the stored and shown result: KLIFS key sites (annotation) excluded, ASP274 KLIFS + metal, LEU139 사용자 보호, ASN261 "
      + "released, ARG126 release without effect", async () => {
        const detail = await storedSet(page, runA, s1.handle);
        return { detail, positions: await storedPositions(page, runA, s1.handle),
          shown: await waitPositions(page, runA, s1.handle, "sort=order&offset=0&limit=50", true, "S1"),
          released: await testId(page, "mutation-released").locator("li").evaluateAll(items => items.map(item =>
            ({ effect: item.getAttribute("data-release-effect"), text: item.textContent.trim() }))),
          klifsRow: await panel(page).locator('tr[data-mutation-check="klifs_key_sites"]').getAttribute("data-check-status"),
          excluded: await testId(page, "mutation-excluded").locator("li").evaluateAll(items => items.map(item =>
            ({ index: item.getAttribute("data-mutation-excluded"), reasons: item.getAttribute("data-exclusion-reasons"),
              text: item.textContent.trim() }))) };
      }, async value => {
        const byKey = new Map(value.positions.map(row => [resKey(row.residue), row]));
        assert.equal(value.positions.length, 21);
        const shellSites = oracle.sites.filter(site => oracle.shell.some(row => row.resname === site.resname && row.seqAuth === site.seqAuth));
        for (const site of shellSites) {
          const row = byKey.get(`${site.resname}${site.seqAuth}`);
          assert.ok(row.exclusion_reasons.includes("klifs_key_site"), `${site.label} not excluded`);
          assert.deepEqual(row.protection.klifs_sites, [site.label]);
          assert.equal(row.status, "excluded");
        }
        assert.deepEqual(byKey.get("ASP274").exclusion_reasons, ["klifs_key_site", "metal_contact"]);
        assert.deepEqual(byKey.get("LEU139").exclusion_reasons, ["user_protected"]);
        const asn = byKey.get("ASN261");
        assert.deepEqual(asn.protection.reasons, ["metal_contact"]);
        assert.equal(asn.protection.released, true);
        assert.equal(asn.status, "candidate");
        assert.deepEqual(asn.exclusion_reasons, []);
        assert.deepEqual(byKey.get("ARG126").sources, [{ kind: "user" }]);
        assert.ok(byKey.get("ARG126").numbering && byKey.get("ARG126").numbering.status === "mapped");
        const result = value.detail.result;
        assert.deepEqual(result.released_residues.map(item => [resKey(item.residue), item.effect]), [["ARG126", "none"], ["ASN261", "released"]]);
        assert.deepEqual(value.released.map(item => item.effect).sort(), ["none", "released"]);
        assert.equal(result.protection_checks.klifs_key_sites.status, "checked");
        assert.equal(result.protection_checks.klifs_key_sites.annotated_sites, 10);
        assert.equal(value.klifsRow, "checked");
        assert.equal(result.counts.excluded_positions, shellSites.length + 1);
        assert.equal(result.counts.released_positions, 1);
        const storedExcluded = value.positions.filter(row => row.status === "excluded");
        assert.deepEqual(value.excluded.map(item => Number(item.index)), storedExcluded.map(row => row.index));
        assert.deepEqual(value.excluded.map(item => item.reasons), storedExcluded.map(row => row.exclusion_reasons.join(",")));
        await checkWording("S1 opened");
        return { shellSites: shellSites.map(site => site.label), counts: result.counts, released: value.released };
      });
  });

  // ---- S3: allowed residues shrunk (same sources); then the S1 request again → the same handle
  if (s1) await rec_.part("allowed", ["M-allowed-shrink", "M-same-handle"], async () => {
    const s3 = await rec_.step("R01-allowed", ["M-allowed-shrink"],
      "Click 모두 해제, tick A, G and W, click 후보 만들기 (same sources and lists)", async () => {
        await setAllowed(page, ["W", "A", "G"]);
        return create(page, runA);
      }, async value => {
        assert.equal(value.ok, true, JSON.stringify(value.body).slice(0, 400));
        assert.equal(value.args.allowed_residues, "AGW");
        assert.notEqual(value.handle, s1.handle);
        const positions = await storedPositions(page, runA, value.handle);
        for (const row of positions) {
          if (row.status !== "candidate") { assert.equal(row.candidate_count, 0); continue; }
          assert.equal(row.candidate_count, ["A", "G", "W"].filter(code => code !== row.one_letter).length, resKey(row.residue));
        }
        const candidates = await readApi(page, setPath(runA, value.handle, "/candidates?offset=0&limit=200"));
        assert.ok(candidates.rows.every(row => ["A", "G", "W"].includes(row.to) && row.to !== row.from));
        await waitCandidates(page, runA, value.handle, "offset=0&limit=100", "S3");
        return { handle: value.handle, total: candidates.total };
      });
    handles.s3 = s3.handle;
    await rec_.step("R02-same-handle", ["M-same-handle"], "Click 20종 모두 고르기 and 후보 만들기 again: the S1 request returns S1's handle, "
      + "no new stored result", async () => {
        const before = await mutationSetCount(page, runA);
        await testId(page, "mutation-allowed-all").click();
        control(evidence, "mutation-allowed-all", { clicked: true });
        const value = await create(page, runA);
        return { ...value, before, after: await mutationSetCount(page, runA) };
      }, async value => {
        assert.equal(value.ok, true);
        assert.equal(value.handle, s1.handle);
        assert.equal(value.after, value.before);
        return { handle: value.handle, sets: value.after };
      });
  });

  // ---- the remaining request controls: annotation/map selects, metal distance, 빼기, result list re-read
  if (s1) await rec_.part("controls", ["M-request-controls"], async () => {
    const cases = ["M-request-controls"];
    await rec_.step("C01-annotation-select", cases, "Choose 고르지 않음 in 참조 주석 (the 검사하지 않음 notice appears), choose the "
      + "annotation again (notice gone); choose 고르지 않음 and the map again in 번호 대응", async () => {
        await selectFilter(page, "mutation-annotation", "");
        const off = { notice: clean(await testId(page, "mutation-klifs-notice").textContent()), map: await testId(page, "mutation-numbering-map").inputValue() };
        await selectFilter(page, "mutation-annotation", handles.annotation);
        const on = { notices: await testId(page, "mutation-klifs-notice").count(), map: await testId(page, "mutation-numbering-map").inputValue() };
        await selectFilter(page, "mutation-numbering-map", "");
        const noMap = await testId(page, "mutation-numbering-map").inputValue();
        await selectFilter(page, "mutation-numbering-map", handles.map);
        return { off, on, noMap, conflict: await testId(page, "mutation-map-conflict").count(), errors: await requestErrors(page) };
      }, async value => {
        assert.ok(value.off.notice.includes(KLIFS_NOTICE), value.off.notice);
        assert.equal(value.on.notices, 0);
        assert.equal(value.on.map, handles.map);
        assert.equal(value.noMap, "");
        assert.equal(value.conflict, 0);
        assert.deepEqual(value.errors, []);
        return value;
      });
    const s5 = await rec_.step("C02-metal-remove", cases, "Fill 금속 근접 거리 5.0, 빼기 ARG A:126 from 직접 고른 위치 and LEU A:139 "
      + "from 보호 목록, untick 직접 선택, click 후보 만들기: MG contacts within 5.0 Å equal the T1 oracle", async () => {
        await fillText(page, "mutation-metal", "5.0");
        await removeResidue(page, "user", "ARG", 126);
        await removeResidue(page, "protect", "LEU", 139);
        await setCheck(page, "mutation-source-user", false);
        return create(page, runA);
      }, async value => {
        assert.equal(value.ok, true, JSON.stringify(value.body).slice(0, 400));
        assert.equal(value.args.metal_contact_A, 5);
        assert.deepEqual(value.args.protected_residues, []);
        assert.deepEqual(value.args.sources.residues, []);
        const positions = await storedPositions(page, runA, value.handle);
        const shellKeys = new Set(oracle.shell.map(row => `${row.resname}${row.seqAuth}`));
        const want = oracle.metal.filter(row => shellKeys.has(`${row.resname}${row.seqAuth}`));
        const metalRows = positions.filter(row => row.protection.reasons.includes("metal_contact"));
        assert.deepEqual(metalRows.map(row => resKey(row.residue)).sort(), want.map(row => `${row.resname}${row.seqAuth}`).sort());
        for (const row of metalRows) {
          const oracleRow = want.find(item => `${item.resname}${item.seqAuth}` === resKey(row.residue));
          assert.equal(row.protection.metal.metal_residue.seq_auth, oracleRow.metal);
          assert.ok(Math.abs(row.protection.metal.min_distance_A - oracleRow.distance) <= 1e-9);
        }
        const detail = await storedSet(page, runA, value.handle);
        assert.equal(detail.result.protection_checks.metal_contact.threshold_A, 5);
        assert.equal(detail.result.protection_checks.metal_contact.metal_residues, 2);
        const shown = await waitPositions(page, runA, value.handle, "sort=order&offset=0&limit=50", true, "S5");
        return { handle: value.handle, metal: metalRows.map(row => [resKey(row.residue), row.protection.metal.min_distance_A]),
          positions: shown.total };
      });
    handles.s5 = s5.handle;
    await rec_.step("C03-sets-refresh", cases, "Click 결과 목록 다시 읽기: the result list is read again (GET only) and lists every stored set",
      async () => {
        const before = Date.now();
        await testId(page, "mutation-sets-refresh").click();
        control(evidence, "mutation-sets-refresh", { clicked: true });
        await waitFor(page, async () => await panel(page).locator('[data-mutation-area="sets"]').getAttribute("data-state") === "ready"
          && log.some(row => row.at >= before && row.method === "GET" && row.path === `/api/runs/${runA}/mutation_candidate_sets`)
          ? true : null, "result list re-read", 30000);
        return { listed: await panel(page).locator("label[data-mutation-set]").evaluateAll(items => items.map(item =>
          item.getAttribute("data-mutation-set"))), posts: log.filter(row => row.at >= before && row.method === "POST").length };
      }, async value => {
        const stored = (await readApi(page, `/runs/${runA}/mutation_candidate_sets?offset=0&limit=100`)).rows.map(row => row.handle);
        assert.deepEqual(value.listed, stored);
        assert.equal(value.posts, 0);
        return value;
      });
  });

  // ---- real fpocket, then the pocket source (+ ligand shell 12 Å) for filters, sort and paging
  let s2 = null;
  await rec_.part("pocket", ["M-pocket", "M-tab-state"], async () => {
    const detected = await rec_.step("K01-fpocket", ["M-pocket", "M-tab-state"],
      "Click 구조 분석: the structure screen kept its source; click 포켓 검출 실행 (approve when asked), wait for the real fpocket job",
      async () => {
        await selectTab(page, "구조 분석");
        const shown = await waitForViewer(page, value => value.catalogReady === true, 30000);
        await page.locator("canvas.mw-molstar-canvas:visible").first().waitFor({ timeout: 15000 });
        const detectedSet = await detectPockets(page, runA, handles.prepared);
        return { source: shown.sourceHandle, ...detectedSet };
      }, async value => {
        assert.equal(value.source, handles.prepared, "structure screen source changed across the tab trips");
        const summary = await readApi(page, `/runs/${runA}/pockets/result?handle=${enc(value.set)}`);
        assert.equal(summary.null_result, false, "fpocket found no pocket on 1MQ4");
        return { set: value.set, jobId: value.jobId, approvalSeen: value.approvalSeen, pockets: summary.total_count };
      });
    handles.pocketSet = detected.set;
    const summary = await readApi(page, `/runs/${runA}/pockets/result?handle=${enc(detected.set)}`);
    const ranks = summary.pockets.map(pocket => pocket.rank);
    const lining = new Set();
    for (const rank of ranks)
      for (const ref of (await readApi(page, `/runs/${runA}/pockets/geometry?handle=${enc(detected.set)}&rank=${rank}`)).lining_residues)
        lining.add(JSON.stringify(RESIDUE_FIELDS.map(field => ref[field])));
    s2 = await rec_.step("K02-pocket-create", ["M-pocket"],
      "Click 단백질 공학, choose the structure, tick 포켓 검출, choose the pocket result, tick every stored pocket number, tick "
      + "리간드 껍질 12.0 Å + ADP, click 후보 만들기", async () => {
        await openReady(page);
        await chooseStructure(page, handles.prepared);
        await setCheck(page, "mutation-source-pocket", true);
        await testId(page, "mutation-pocket-sets").locator(`label[data-mutation-pocket-set="${detected.set}"] input`).check();
        control(evidence, "mutation-pocket-sets", { checked: detected.set });
        await testId(page, "mutation-pocket-numbers").waitFor({ timeout: 30000 });
        const offered = await testId(page, "mutation-pocket-numbers").locator("label[data-mutation-pocket]")
          .evaluateAll(items => items.map(item => Number(item.getAttribute("data-mutation-pocket"))));
        for (const rank of ranks) await testId(page, "mutation-pocket-numbers").getByRole("checkbox", { name: `포켓 ${rank}`, exact: true }).check();
        control(evidence, "mutation-pocket-numbers", { checked: ranks });
        await setCheck(page, "mutation-source-ligand-shell", true);
        await fillText(page, "mutation-radius", "12.0");
        await chooseLigand(page, "ADP", 2001);
        return { offered, ...await create(page, runA) };
      }, async value => {
        assert.deepEqual(value.offered, ranks);
        assert.equal(value.ok, true, JSON.stringify(value.body).slice(0, 400));
        assert.deepEqual(value.args.sources.pocket, { pocket_set: detected.set, ranks });
        assert.deepEqual(value.args.sources.ligand_shell, { radius_A: 12 });
        const positions = await storedPositions(page, runA, value.handle);
        const pocketRows = positions.filter(row => row.sources.some(source => source.kind === "pocket"));
        assert.deepEqual(new Set(pocketRows.map(row => JSON.stringify(RESIDUE_FIELDS.map(field => row.residue[field])))), lining);
        const detail = await storedSet(page, runA, value.handle);
        assert.equal(detail.result.counts.source_counts.pocket, lining.size);
        assert.equal(detail.result.pockets.pocket_set, detected.set);
        for (const row of pocketRows) {
          const sourceRanks = row.sources.filter(source => source.kind === "pocket").map(source => source.pocket_rank);
          assert.deepEqual(sourceRanks, [...sourceRanks].sort((a, b) => a - b));
        }
        return { handle: value.handle, positions: positions.length, pocketPositions: pocketRows.length, ranks };
      });
    handles.s2 = s2.handle;
  });

  if (s2) await rec_.part("filters", ["M-filters-sort", "M-paging"], async () => {
    const h = s2.handle;
    await rec_.step("F01-page", ["M-paging"], "Position table first page; click 다음 and 이전 on the position pager", async () => {
      const first = await waitPositions(page, runA, h, "sort=order&offset=0&limit=50", true, "S2 first");
      assert.ok(first.total > 50, `S2 has ${first.total} positions; paging needs more than 50`);
      await testId(page, "mutation-positions-next").click();
      control(evidence, "mutation-positions-next", { clicked: true });
      const second = await waitPositions(page, runA, h, "sort=order&offset=50&limit=50", true, "S2 second");
      await testId(page, "mutation-positions-prev").click();
      control(evidence, "mutation-positions-prev", { clicked: true });
      const back = await waitPositions(page, runA, h, "sort=order&offset=0&limit=50", true, "S2 back");
      return { first, second, back };
    }, async value => value);
    const filters = [
      ["mutation-filter-status", "excluded", "status=excluded"],
      ["mutation-filter-source", "pocket", "status=excluded&source=pocket"],
      ["mutation-filter-reason", "klifs_key_site", "status=excluded&source=pocket&exclusion_reason=klifs_key_site"],
      ["mutation-filter-chain", "A", "status=excluded&source=pocket&exclusion_reason=klifs_key_site&chain_auth=A"],
    ];
    const seen = [];
    for (const [id, value, query] of filters)
      seen.push(await rec_.step(`F02-${id}`, ["M-filters-sort"], `Choose ${value} in ${id}: the table equals the stored page`, async () => {
        await selectFilter(page, id, value);
        return waitPositions(page, runA, h, `${query}&sort=order&offset=0&limit=50`, true, id);
      }, async result => result));
    await rec_.step("F03-clear-sort", ["M-filters-sort"], "Reset the four filters to 전체, choose 리간드까지 최소 거리 오름차순: rows follow "
      + "the stored distances, rows without a value last", async () => {
        for (const [id] of filters) await selectFilter(page, id, "");
        await selectFilter(page, "mutation-sort", "ligand_distance");
        const shown = await waitPositions(page, runA, h, "sort=ligand_distance&offset=0&limit=50", true, "sort");
        return { shown, all: await storedPositions(page, runA, h, "sort=ligand_distance") };
      }, async value => {
        const distances = value.all.map(row => row.ligand_min_distance_A);
        const firstNull = distances.indexOf(null);
        const numbers = firstNull === -1 ? distances : distances.slice(0, firstNull);
        assert.ok(firstNull === -1 || distances.slice(firstNull).every(item => item === null));
        assert.ok(numbers.every((item, i) => i === 0 || numbers[i - 1] <= item), "ligand_distance sort is not ascending");
        return { total: value.all.length, nulls: firstNull === -1 ? 0 : distances.length - firstNull, first: value.shown.indices.slice(0, 5) };
      });
    await rec_.step("F04-candidates", ["M-filters-sort", "M-paging"],
      "Candidate table: 다음/이전 pages; click 후보 보기 on a row (position filter); choose W in 바꿀 잔기; 전체 위치 보기", async () => {
        const all = await waitCandidates(page, runA, h, "offset=0&limit=100", "cand first");
        await testId(page, "mutation-candidates-next").click();
        control(evidence, "mutation-candidates-next", { clicked: true });
        const second = await waitCandidates(page, runA, h, "offset=100&limit=100", "cand second");
        await testId(page, "mutation-candidates-prev").click();
        control(evidence, "mutation-candidates-prev", { clicked: true });
        await waitCandidates(page, runA, h, "offset=0&limit=100", "cand back");
        const button = testId(page, "mutation-position-candidates").first();
        const index = Number(await button.getAttribute("data-position-index"));
        await button.click();
        control(evidence, "mutation-position-candidates", { position: index });
        const byPosition = await waitCandidates(page, runA, h, `position_index=${index}&offset=0&limit=100`, "cand position");
        await selectFilter(page, "mutation-candidate-to", "W");
        const toW = await waitCandidates(page, runA, h, `position_index=${index}&to=W&offset=0&limit=100`, "cand to W");
        await testId(page, "mutation-candidate-position-clear").click();
        control(evidence, "mutation-candidate-position-clear", { clicked: true });
        const allW = await waitCandidates(page, runA, h, "to=W&offset=0&limit=100", "cand all W");
        await selectFilter(page, "mutation-candidate-to", "");
        return { all, second, index, byPosition, toW, allW };
      }, async value => {
        assert.ok(value.all.total > 100, `candidate paging needs more than 100 rows: ${value.all.total}`);
        assert.ok(value.byPosition.total >= 1 && value.byPosition.total <= 19);
        assert.ok(value.toW.total <= 1);
        return value;
      });
    await checkWording("S2 filters");
  });

  // ---- S4: zero candidates (ALA A:160 only, allowed A only) → empty scientific result, not a failure
  await rec_.part("zero", ["M-zero"], () => rec_.step("Z01-zero", ["M-zero"],
    "Untick 포켓 검출 and 리간드 껍질, tick 직접 선택 + ALA A:160, 모두 해제 + A, click 후보 만들기 → 빈 결과 (후보 0개)", async () => {
      if (!await testId(page, "mutation-source-user").count()) { await openReady(page); await chooseStructure(page, handles.prepared); }
      await setCheck(page, "mutation-source-pocket", false);
      await setCheck(page, "mutation-source-ligand-shell", false);
      await setCheck(page, "mutation-source-user", true);
      await pickResidue(page, "user", "ALA", 160);
      await setAllowed(page, ["A"]);
      const value = await create(page, runA);
      return { ...value, state: await panelState(page), badge: clean(await testId(page, "mutation-state").textContent()),
        nullText: clean(await testId(page, "mutation-null-result").textContent()), failures: await testId(page, "mutation-failure").count(),
        empty: clean(await testId(page, "mutation-candidates-empty").textContent()),
        listNull: await panel(page).locator(`label[data-mutation-set="${value.handle}"]`).getAttribute("data-null-result") };
    }, async value => {
      assert.equal(value.ok, true, JSON.stringify(value.body).slice(0, 400));
      assert.equal(value.state, "scientific_null");
      assert.equal(value.badge, "빈 결과 (후보 0개)");
      assert.equal(value.failures, 0);
      assert.equal(value.listNull, "true");
      const detail = await storedSet(page, runA, value.handle);
      assert.equal(detail.result.null_result, true);
      assert.equal(detail.result.counts.candidates, 0);
      assert.equal(detail.result.counts.exclusion_reason_counts.no_allowed_alternative, 1);
      assert.ok(value.nullText.includes("허용 목록에 바꿀 잔기 없음 1개"), value.nullText);
      assert.ok(value.empty.startsWith("후보 0개 (빈 결과)"), value.empty);
      handles.s4 = value.handle;
      return { handle: value.handle, nullText: value.nullText, state: value.state };
    }));

  // ---- server refusals (labeled in-flight request alteration; the real server decides)
  await rec_.part("refusals", ["M-refused"], async () => {
    const valid = async () => {
      await setCheck(page, "mutation-source-ligand-shell", true);
      await fillText(page, "mutation-radius", "5");
      if (await testId(page, "mutation-ligand").inputValue() === "") await chooseLigand(page, "ADP", 2001);
      await testId(page, "mutation-allowed-all").click();
      if (Number(await testId(page, "mutation-picker-protect").getAttribute("data-count")) === 0)
        await pickResidue(page, "protect", "LEU", 139);
    };
    await valid();
    const alter = {
      structure_invalid: args => ({ ...args, structure: handles.structure }),
      annotation_invalid: args => ({ ...args, annotation: handles.map }),
      protect_release_conflict: args => ({ ...args, released_residues: [...args.released_residues, args.protected_residues[0]] }),
      ligand_required: args => ({ ...args, ligand: null }),
    };
    evidence.fixtureLabels.push(ALTER_LABEL);
    for (const [code, change] of Object.entries(alter)) {
      const matcher = url => new URL(url).pathname === `/api/runs/${runA}/commands`;
      const handler = async route => {
        const body = route.request().postDataJSON();
        if (route.request().method() !== "POST" || body?.tool !== TOOL) return route.continue();
        return route.continue({ postData: JSON.stringify({ ...body, args: change(body.args) }) });
      };
      await page.route(matcher, handler);
      try {
        await rec_.step(`X-${code}`, ["M-refused"], `Click 후보 만들기 with the labeled alteration for ${code}: the refusal shows `
          + `"${REFUSALS[code]} (${code})", nothing is stored`, async () => {
          const before = await mutationSetCount(page, runA);
          const value = await create(page, runA);
          const line = testId(page, "mutation-create-error");
          await waitFor(page, async () => await line.getAttribute("data-reason-code") === value.body.detail?.reason_code ? true : null,
            "refusal line shows this reply", 10000);
          return { ...value, before, after: await mutationSetCount(page, runA), reasonCode: await line.getAttribute("data-reason-code"), text: clean(await line.textContent()) };
        }, async value => {
          assert.equal(value.ok, false);
          assert.equal(value.status, 422);
          assert.equal(value.body.detail?.reason_code, code);
          assert.equal(value.reasonCode, code);
          assert.ok(value.text.includes(`${REFUSALS[code]} (${code})`), value.text);
          assert.equal(value.after, value.before);
          return { code, status: value.status, shown: value.text, serverMessage: value.body.message };
        });
      } finally { await page.unroute(matcher, handler); }
    }
  });

  // ---- report → 지식·보고서 list → view → downloads
  if (handles.s1) await rec_.part("report", ["M-report"], async () => {
    const cases = ["M-report"];
    const created = await rec_.step("Q01-report", cases, "Open S1 in ② 저장된 결과, click 보고서 만들기", async () => {
      await openReady(page);
      await openSet(page, handles.s1);
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${runA}/method_reports`, { timeout: 60000 });
      await testId(page, "mutation-report").click();
      control(evidence, "mutation-report", { clicked: true });
      const response = await posted;
      const body = await response.json();
      await testId(page, "mutation-report-done").waitFor({ timeout: 30000 });
      return { status: response.status(), handle: body.handle, manifest: body.manifest, request: response.request().postDataJSON(),
        done: await testId(page, "mutation-report-done").getAttribute("data-report-handle") };
    }, async value => {
      assert.equal(value.done, value.handle);
      assert.equal(value.manifest.analysis_type, "mutation_candidates");
      assert.equal(value.manifest.result_handle, handles.s1);
      assert.deepEqual(value.request, { result_handle: handles.s1 });
      return { handle: value.handle, status: value.status };
    });
    evidence.handles.report = created.handle;
    const library = page.getByRole("region", { name: "보고서 보관함", exact: true });
    const reports = library.getByRole("region", { name: "저장된 보고서", exact: true });
    const content = library.getByRole("region", { name: "선택한 항목 내용", exact: true });
    await rec_.step("Q02-listed", cases, "Click 지식·보고서: the list shows 변이 후보 보고서; click it; content = stored Markdown", async () => {
      await selectTab(page, "지식·보고서");
      const row = reports.locator("li button").filter({ hasText: created.handle });
      await row.waitFor({ timeout: 30000 });
      const kind = clean(await row.locator(".mw-library-kind").textContent());
      await row.click();
      const pre = content.getByLabel(`저장된 보고서 ${created.handle}`, { exact: true });
      await pre.waitFor({ timeout: 30000 });
      return { kind, text: await pre.textContent() };
    }, async value => {
      assert.equal(value.kind, "변이 후보 보고서");
      const saved = await readApi(page, `/runs/${runA}/reports/selected?handle=${enc(created.handle)}`);
      assert.equal(value.text, saved.markdown);
      for (const sentence of LIMITATIONS) assert.ok(value.text.includes(sentence), `report lacks ${sentence}`);
      return { kind: value.kind, markdownSha256: sha(Buffer.from(value.text)) };
    });
    for (const [label, format] of [["Markdown 다운로드", "markdown"], ["JSON 다운로드", "json"]]) {
      const route = `/runs/${runA}/reports/download?handle=${enc(created.handle)}&format=${format}`;
      await rec_.step(`Q03-download-${format}`, cases, `Click ${label}; bytes equal the backend bytes`, () =>
        downloadByClick(app, content.getByRole("link", { name: label, exact: true })), async downloaded => {
        const bytes = fs.readFileSync(downloaded.downloaded);
        const saved = await readBytes(page, route);
        assert.equal(sha(bytes), sha(saved), "downloaded bytes differ from the backend bytes");
        return { route, sha256: sha(bytes), bytes: bytes.length };
      });
    }
  });

  // ---- late responses inside one mount: detail (request number) and position page (abort) of another result
  if (handles.s0 && handles.s1 && handles.s2) await rec_.part("late-result", ["M-late-result"], async () => {
    const cases = ["M-late-result"];
    await rec_.step("L01-ready", cases, "Click 단백질 공학, open S1", async () => { await openReady(page); await openSet(page, handles.s1); },
      async () => ({ opened: handles.s1 }));
    const detailPath = decodeURIComponent(`/api${setPath(runA, handles.s0)}`);
    const held = [];
    let holding = true;
    const matcher = url => decodeURIComponent(new URL(url).pathname) === detailPath;
    const handler = async route => {
      if (!holding || route.request().method() !== "GET") return route.continue();
      held.push({ route, response: await route.fetch(), at: Date.now() });
    };
    await page.route(matcher, handler);
    evidence.fixtureLabels.push(HOLD_LABEL);
    try {
      await rec_.step("L02-held-detail", cases, "Click S0: its detail response is held; click S2 → S2 opens", async () => {
        await panel(page).locator(`label[data-mutation-set="${handles.s0}"] input`).check();
        await waitFor(page, async () => held.length >= 1 ? true : null, "held S0 detail", 30000);
        await openSet(page, handles.s2);
        return { held: held.length };
      }, async value => value);
      await rec_.step("L03-release-detail", cases, "Release S0's held detail: S2 stays opened (late response dropped)", async () => {
        holding = false;
        const released = [];
        for (const item of held) {
          try { await item.route.fulfill({ response: item.response }); released.push({ delivered: true }); }
          catch (error) { released.push({ delivered: false, reason: String(error).slice(0, 160) }); }
        }
        await page.waitForTimeout(2500);
        return { released, detail: await testId(page, "mutation-detail").getAttribute("data-mutation-detail"),
          checked: await panel(page).locator(`label[data-mutation-set="${handles.s2}"] input`).isChecked(),
          shown: await waitPositions(page, runA, handles.s2, "sort=order&offset=0&limit=50", true, "S2 after late S0") };
      }, async value => {
        assert.equal(value.detail, handles.s2);
        assert.equal(value.checked, true);
        return { released: value.released, layer: value.released.some(item => item.delivered) ? "request number (delivered, dropped)" : "abort" };
      });
    } finally {
      holding = false;
      for (const item of held) await item.route.fulfill({ response: item.response }).catch(() => undefined);
      await page.unroute(matcher, handler);
    }
    const posPath = decodeURIComponent(`/api${setPath(runA, handles.s2, "/positions")}`);
    const heldPos = [];
    let holdingPos = true;
    const posMatcher = url => decodeURIComponent(new URL(url).pathname) === posPath && new URL(url).searchParams.get("sort") === "ligand_distance";
    const posHandler = async route => {
      if (!holdingPos) return route.continue();
      try { heldPos.push({ route, response: await route.fetch(), at: Date.now() }); }
      catch (error) { heldPos.push({ route, response: null, error: String(error).slice(0, 160) }); }
    };
    await page.route(posMatcher, posHandler);
    try {
      await rec_.step("L04-held-positions", cases, "On S2 choose 리간드까지 최소 거리 정렬: that page is held; click S1 → S1's table", async () => {
        await selectFilter(page, "mutation-sort", "ligand_distance");
        await waitFor(page, async () => heldPos.length >= 1 ? true : null, "held S2 position page", 30000);
        await openSet(page, handles.s1);
        return waitPositions(page, runA, handles.s1, "sort=order&offset=0&limit=50", true, "S1 after switch");
      }, async value => value);
      await rec_.step("L05-release-positions", cases, "Release the held S2 page: S1's table stays", async () => {
        holdingPos = false;
        const released = [];
        for (const item of heldPos) {
          if (!item.response) { released.push({ delivered: false, reason: item.error }); continue; }
          try { await item.route.fulfill({ response: item.response }); released.push({ delivered: true }); }
          catch (error) { released.push({ delivered: false, reason: String(error).slice(0, 160) }); }
        }
        await page.waitForTimeout(2500);
        return { released, detail: await testId(page, "mutation-detail").getAttribute("data-mutation-detail"),
          shown: await waitPositions(page, runA, handles.s1, "sort=order&offset=0&limit=50", true, "S1 after late S2") };
      }, async value => {
        assert.equal(value.detail, handles.s1);
        return { released: value.released, layer: "dropped; abort or request number not distinguished (fulfill delivered)" };
      });
    } finally {
      holdingPos = false;
      for (const item of heldPos) if (item.response) await item.route.fulfill({ response: item.response }).catch(() => undefined);
      await page.unroute(posMatcher, posHandler);
    }
  });

  // ---- run B (loaded, never prepared) + run switch with a held run A list response
  const runB = await rec_.part("run-switch", ["M-late-run", "M-unprepared"], async () => {
    const cases = ["M-late-run"];
    const made = await rec_.step("W01-run-b", ["M-unprepared"], "Click 구조 분석, 새 run (run B), load public_1mq4.cif without 전처리; "
      + "click 단백질 공학 → 사용할 수 없음 with the reason", async () => {
        const id = await newRun(page);
        await uploadLoad(page, STRUCTURE, "public PDB entry 1MQ4 (repository fixture)");
        await openTab(page);
        await waitState(page, "unavailable", 30000);
        return { run: id, ...await noControls(page), reason: clean(await testId(page, "mutation-unavailable").textContent()) };
      }, async value => {
        assert.ok(value.reason.includes(NO_PREPARED_REASON), value.reason);
        assert.ok(!/\d/.test(value.text), value.text);
        assert.equal(value.controls, 0);
        return value;
      });
    evidence.runs.B = made.run;
    const held = [];
    let holding = true;
    const matcher = url => new URL(url).pathname === `/api/runs/${runA}/mutation_candidate_sets`;
    const handler = async route => {
      if (!holding || route.request().method() !== "GET") return route.continue();
      try { held.push({ route, response: await route.fetch(), at: Date.now() }); }
      catch (error) { held.push({ route, response: null, error: String(error).slice(0, 160) }); }
    };
    await page.route(matcher, handler);
    evidence.fixtureLabels.push(HOLD_LABEL);
    try {
      await rec_.step("W02-held", cases, "Choose run A in 저장된 run, click 단백질 공학: run A's result-list response is held", async () => {
        await chooseRun(page, runA);
        await openTab(page);
        await waitFor(page, async () => held.length >= 1 ? true : null, "held run A result list", 30000);
        return { held: held.length, area: await panel(page).locator('[data-mutation-area="sets"]').getAttribute("data-state").catch(() => null),
          run: await globalRun(page) };
      }, async value => { assert.equal(value.run, runA); return value; });
      await rec_.step("W03-switch-b", cases, "Click 구조 분석, choose run B, click 단백질 공학: run B's panel", async () => {
        await chooseRun(page, made.run, false);
        await openTab(page);
        await waitState(page, "unavailable", 30000);
        return { run: await globalRun(page), state: await panelState(page) };
      }, async value => { assert.equal(value.run, made.run); return value; });
      await rec_.step("W04-release", cases, "Release run A's held list: run B's panel stays, no run A result appears", async () => {
        holding = false;
        const released = [];
        for (const item of held) {
          if (!item.response) { released.push({ delivered: false, reason: item.error }); continue; }
          try { await item.route.fulfill({ response: item.response }); released.push({ delivered: true }); }
          catch (error) { released.push({ delivered: false, reason: String(error).slice(0, 160) }); }
        }
        await page.waitForTimeout(2500);
        return { released, run: await globalRun(page), state: await panelState(page), text: clean(await panel(page).textContent()),
          sets: await panel(page).locator("label[data-mutation-set]").count() };
      }, async value => {
        assert.equal(value.run, made.run);
        assert.equal(value.state, "unavailable");
        assert.equal(value.sets, 0);
        for (const handle of [handles.s0, handles.s1, handles.s2].filter(Boolean))
          assert.ok(!value.text.includes(shortHandle(handle)), `late run A result shown: ${handle}`);
        return { released: value.released, layer: "abort (panel unmounted and re-keyed by run)" };
      });
    } finally {
      holding = false;
      for (const item of held) if (item.response) await item.route.fulfill({ response: item.response }).catch(() => undefined);
      await page.unroute(matcher, handler);
    }
    return made.run;
  });

  // ---- wording (every check above) summarized; provider calls
  await rec_.part("wording", ["M-wording"], () => rec_.step("V01-wording", ["M-wording"],
    "No rank/recommendation/effect wording in the panel outside the five fixed sentences (every check of this run)", async () => {
      if (runB) await chooseRun(page, runA);
      await openReady(page);
      const last = handles.s3 ?? handles.s1 ?? handles.s0;
      if (last) await openSet(page, last);
      await checkWording("final");
      return wording;
    }, async value => {
      assert.ok(value.length >= 4, `wording checks: ${value.length}`);
      assert.ok(value.every(item => item.found.length === 0));
      return value;
    }));
  for (const id of [runA, runB].filter(Boolean)) evidence.providerCalls.push(await providerCalls(page, id));
}

// ------------------------------------------------------------------ mode catalytic (M26, spec §8, §10.2, §10.3)
// Spec §11.1 UK2 and §8.4 sentence 3, verbatim; the v1 third sentence is LIMITATIONS[2] above (unchanged).
const UK2 = "촉매 잔기 검사 안 함: 이 집합은 M-CSA 촉매 잔기 주석 없이 만들었거나 일부 체인만 검사했다.";
const UK3 = "UniProt 부위 정보는 지식 탭에서만 보이며 보호에 쓰지 않음.";
const LIMIT3 = {
  checked: "보호 잔기는 사용자 지정·KLIFS 주요 부위·금속 근접·이황화 결합·M-CSA 촉매 잔기 주석 기준으로만 판정했다.",
  not_checked: "보호 잔기는 사용자 지정·KLIFS 주요 부위·금속 근접·이황화 결합 기준으로만 판정했고 M-CSA 촉매 잔기 주석은 " +
    "주지 않았거나 일부 체인만 다뤘다(검사하지 않은 부분은 '없음'이 아니다).",
  not_available: LIMITATIONS[2],
};
// Screen text of the M20 area (the product's wording, copied here as the expectation).
const CATALYTIC_NOT_SELECTED = "M-CSA 촉매 잔기 보호를 검사하지 않음: 같은 구조의 효소 반응 지식 결과를 고르지 않았습니다. " +
  "이 요청에서는 M-CSA 촉매 잔기가 제외 목록에 들어가지 않습니다.";
const SERVER_POSITIONS_NOTE = "포켓·리간드 껍질 출처의 위치는 서버가 정하므로, 아래는 이 구조의 체인마다 위치가 생기면 적용될 " +
  "촉매 잔기 검사 상태입니다.";
const UNCOVERED_LABEL = { not_in_annotation: "고른 효소 반응 지식 결과에 이 체인이 없음", chain_not_listed: "이 체인은 M-CSA 행에 없음",
  pdb_not_in_snapshot: "이 PDB ID는 스냅샷에 없음", not_checked: "결과가 이 체인의 M-CSA를 검사하지 않음(PDB ID 없음)" };
const EXCLUSION_V1 = ["non_standard_residue", "user_protected", "klifs_key_site", "metal_contact", "disulfide_cys",
  "no_allowed_alternative"];
const EXCLUSION_V2 = ["non_standard_residue", "user_protected", "klifs_key_site", "metal_contact", "disulfide_cys",
  "catalytic_residue", "no_allowed_alternative"];
const EXCLUSION_LABEL = { non_standard_residue: "표준 잔기가 아님", user_protected: "사용자 보호", klifs_key_site: "KLIFS 주요 부위",
  metal_contact: "금속 근접", disulfide_cys: "이황화 Cys", catalytic_residue: "M-CSA 촉매 잔기 주석",
  no_allowed_alternative: "허용 목록에 바꿀 잔기 없음" };
const REACTION_TOOL = "link_reaction_knowledge";
const posted = (log, since) => log.filter(row => row.at >= since && row.method === "POST" && row.api)
  .map(row => `${row.path}${row.tool ? ` ${row.tool}` : ""}`);
const rkey = ref => `${ref.resname} ${ref.chain_auth}:${ref.seq_auth}${ref.icode}`;

async function chooseLigandAt(page, spec) {
  const select = testId(page, "mutation-ligand");
  const found = (await selectOptions(select)).filter(item => item.text.startsWith(`${spec.resname} ${spec.chain}:${spec.seq} ·`));
  assert.equal(found.length, 1, `ligand option ${spec.resname} ${spec.chain}:${spec.seq}`);
  await select.selectOption(found[0].value);
  control(evidenceRef.value, "mutation-ligand", { chosen: found[0].text });
}
async function pickResidueAt(page, picker, spec) {
  const select = testId(page, `mutation-pick-${picker}`);
  const found = (await selectOptions(select)).filter(item => item.text.startsWith(`${spec.resname} ${spec.chain}:${spec.seq} ·`));
  assert.equal(found.length, 1, `${picker} option ${spec.resname} ${spec.chain}:${spec.seq}: ${found.length}`);
  const before = Number(await testId(page, `mutation-picker-${picker}`).getAttribute("data-count"));
  await select.selectOption(found[0].value);
  await testId(page, `mutation-add-${picker}`).click();
  await waitFor(page, async () => Number(await testId(page, `mutation-picker-${picker}`).getAttribute("data-count")) === before + 1
    ? true : null, `${picker} count +1`, 10000);
  control(evidenceRef.value, `mutation-pick-${picker}`, { picked: found[0].text });
}
/** The plan's position sources on the request form (ligand shell around a chosen ligand, or direct residues). */
async function setPositions(page, positions) {
  if (positions.ligandShell) {
    await setCheck(page, "mutation-source-ligand-shell", true);
    await fillText(page, "mutation-radius", positions.ligandShell.radius);
    await chooseLigandAt(page, positions.ligandShell);
  } else {
    await setCheck(page, "mutation-source-user", true);
    for (const residue of positions.residues) await pickResidueAt(page, "user", residue);
  }
}

// The 효소 반응 지식 area (지식·보고서), driven the same way as reaction-knowledge-flow.cjs.
const rpanel = page => page.locator('#mw-app-panel-knowledge [data-testid="reaction-panel"]');
const rt = (page, id) => rpanel(page).locator(`[data-testid="${id}"]`);
async function linkReaction(page, run, structure, pdbId, chains) {
  await selectTab(page, "지식·보고서");
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
  await rpanel(page).locator(`[data-testid="reaction-link-done"][data-reaction-new-result="${body.handle.handle}"]`)
    .waitFor({ timeout: 30000 });
  return body.handle.handle;
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
/** The stored set's catalytic check, positions and limitations versus the screen (one opened set). */
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
    conflict: clean(await testId(page, "mutation-catalytic-conflict").textContent()),
    unmatched: clean(await testId(page, "mutation-catalytic-unmatched").textContent()),
    badge: await testId(page, "mutation-catalytic-check-badge").count() ? clean(await testId(page, "mutation-catalytic-check-badge")
      .textContent()) : null,
    conflicts: await testId(page, "mutation-catalytic-conflicts").locator("li").evaluateAll(items => items.map(item =>
      ({ chain: item.getAttribute("data-chain"), id: Number(item.getAttribute("data-mcsa-id")),
        index: Number(item.getAttribute("data-residue-index")), text: item.textContent.replace(/\s+/g, " ").trim() }))),
    unmatchedList: await testId(page, "mutation-catalytic-unmatched-list").locator("li").evaluateAll(items => items.map(item =>
      ({ chain: item.getAttribute("data-chain"), id: Number(item.getAttribute("data-mcsa-id")),
        index: Number(item.getAttribute("data-residue-index")), text: item.textContent.replace(/\s+/g, " ").trim() }))),
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
  assert.equal(result.limitations[2], LIMIT3[check.status], "limitation sentence 3 variant");
  const v1 = check.status === "not_available";
  assert.equal(result.method_version, v1 ? "mw.mutation_candidates/v1" : "mw.mutation_candidates/v2");
  const order = v1 ? EXCLUSION_V1 : EXCLUSION_V2;
  // stored objects are canonical JSON (sorted keys): the key set, not its order, is the stored fact
  assert.deepEqual(Object.keys(result.counts.exclusion_reason_counts).sort(), [...order].sort(), "exclusion reason keys");
  assert.deepEqual(ui.reasonFilter, order, "reason filter options");
  for (const reason of order) assert.ok(ui.reasonCounts.includes(`${EXCLUSION_LABEL[reason]} ${result.counts.exclusion_reason_counts[reason]}개`),
    ui.reasonCounts);
  if (!("covered_chains" in check)) {
    for (const text of [ui.covered, ui.uncovered, ui.matched, ui.conflict, ui.unmatched])
      assert.ok(text.startsWith("—") && !/\d/.test(text), `not checked shown with a number: ${text}`);
    assert.ok(positions.every(row => v1 ? row.protection.catalytic === undefined : row.protection.catalytic === null));
  } else {
    assert.deepEqual(check.covered_chains, want.covered, "covered chains");
    assert.deepEqual(check.uncovered_chains, want.uncovered, "uncovered chains");
    if (want.counts) assert.deepEqual({ matched_rows: check.matched_rows, conflict_rows: check.conflict_rows,
      unmatched_rows: check.unmatched_rows }, want.counts, "row counts");
    assert.equal(ui.covered, check.covered_chains.length ? check.covered_chains.join(", ") : "— (M-CSA가 다룬 체인 없음)");
    assert.equal(ui.uncovered, check.uncovered_chains.length ? check.uncovered_chains.map(item =>
      `${item.chain_auth} ${UNCOVERED_LABEL[item.coverage]} (${item.coverage})`).join(", ") : "빈 목록 ([])");
    for (const [key, text] of [["matched_rows", ui.matched], ["conflict_rows", ui.conflict], ["unmatched_rows", ui.unmatched]])
      assert.equal(text, check.covered_chains.length ? `${check[key]}개` : "— (M-CSA가 다룬 체인 없음)", key);
    if (check.covered_chains.length && (check.conflicts.length || check.unmatched.length)) {
      assert.deepEqual(ui.conflicts.map(item => [item.chain, item.id, item.index]),
        check.conflicts.map(item => [item.chain_auth, item.mcsa_id, item.residue_index]));
      assert.deepEqual(ui.unmatchedList.map(item => [item.chain, item.id, item.index]),
        check.unmatched.map(item => [item.chain_auth, item.mcsa_id, item.residue_index]));
      [...check.conflicts, ...check.unmatched].forEach(item => {
        const shown = [...ui.conflicts, ...ui.unmatchedList].find(row => row.chain === item.chain_auth && row.id === item.mcsa_id &&
          row.index === item.residue_index);
        assert.ok(shown.text.includes(`auth ${item.listed.auth_resid ?? "—"}`) && shown.text.includes(item.listed.code) &&
          shown.text.includes(`(${item.reason})`), shown.text);
      });
      if (want.conflicts) assert.deepEqual(check.conflicts.map(item => [item.chain_auth, item.mcsa_id, item.residue_index]), want.conflicts);
      if (want.unmatched) assert.deepEqual(check.unmatched.map(item => [item.chain_auth, item.mcsa_id, item.residue_index]), want.unmatched);
    }
    for (const row of positions) {
      const covered = check.covered_chains.includes(row.residue.chain_auth);
      if (!covered) { assert.equal(row.protection.catalytic, null, `${rkey(row.residue)} not covered`); continue; }
      const expected = (want.catalytic ?? {})[rkey(row.residue)];
      if (want.catalytic) assert.deepEqual(row.protection.catalytic.map(item => [item.mcsa_id, item.residue_index, item.is_reference]),
        expected ?? [], `${rkey(row.residue)} catalytic`);
      assert.equal(row.protection.reasons.includes("catalytic_residue"), row.protection.catalytic.length > 0);
      if (row.protection.catalytic.length && !row.protection.released) {
        assert.equal(row.status, "excluded");
        assert.ok(row.exclusion_reasons.includes("catalytic_residue"));
      }
    }
  }
  if (check.status === "checked") assert.equal(ui.badge, null, "a checked set carries the not-checked mark");
  else assert.ok(ui.badge?.startsWith(UK2), `badge ${ui.badge}`);
  const byResidue = new Map(positions.map(row => [rkey(row.residue), row]));
  assert.ok(ui.cells.length > 0);
  for (const cell of ui.cells) {
    const row = byResidue.get(cell.residue);
    assert.ok(row, `shown position ${cell.residue} not stored`);
    assert.equal(cell.text, catalyticCellText(row.protection), `${cell.residue} catalytic cell`);
    assert.equal(cell.released, row.protection.released ? "true" : null);
    // not checked is "—" with the reason, never a number ("v1" names the set generation, not a count)
    if (row.protection.catalytic === null || row.protection.catalytic === undefined)
      assert.ok(!/\d/.test(cell.text.replace("v1 집합", "")), cell.text);
  }
  return { handle, status: check.status, reason: check.reason, covered: check.covered_chains ?? null,
    uncovered: check.uncovered_chains ?? null, counts: "covered_chains" in check ? { matched: check.matched_rows,
      conflict: check.conflict_rows, unmatched: check.unmatched_rows } : null, limitation3: result.limitations[2],
    protectedPositions: positions.filter(row => row.protection.catalytic?.length).map(row => [rkey(row.residue), row.status,
      row.protection.released]) };
}
async function setMark(page, handle) {
  const label = panel(page).locator(`label[data-mutation-set="${handle}"]`);
  await label.waitFor({ timeout: 30000 });
  return { status: await label.getAttribute("data-catalytic-status"),
    mark: await label.locator('[data-testid="mutation-set-catalytic"]').count()
      ? clean(await label.locator('[data-testid="mutation-set-catalytic"] .mw-catalytic-badge').textContent()) : null,
    detail: await label.locator('[data-testid="mutation-set-catalytic-detail"]').count()
      ? clean(await label.locator('[data-testid="mutation-set-catalytic-detail"]').textContent()) : null };
}

async function modeCatalytic(session, input, rec_, evidence, log) {
  const { page } = session;
  const plan = input.planData;
  const M = plan.mutation;
  const K = id => plan.stage !== "real" ? id : id === "C-picker-marks" ? "X-picker-marks" : id.startsWith("C-") ? "X-m20"
    : ({ "R-no-zero": "X-no-zero", "R-wording": "X-wording" })[id] ?? id;
  if (plan.synthetic) evidence.fixtureLabels.push(plan.synthetic);
  const handles = evidence.handles;
  const wording = [];
  const checkWording = async label => {
    const seen = await panelWording(page);
    const found = forbiddenIn(seen.text);
    wording.push({ label, found, chars: seen.text.length });
    assert.deepEqual(found, [], `${label}: forbidden wording ${found.join(", ")}`);
  };
  const run = await rec_.step("K01-new-run", [], "Click 구조 분석, 새 run (run M)", () => newRun(page), async id => ({ run: id }));
  evidence.runs.A = run;
  const loaded = await rec_.step("K02-upload-prepare", [], `Choose ${M.structure.name}, 구조 불러오기, 전처리`, async () => {
    const value = await uploadLoad(page, M.structure.file, M.structure.provenance);
    await selectTab(page, "구조 분석");
    return { ...value, prepared: (await prepareManual(page)).prepared };
  }, async value => { assert.equal(value.file.sha256, M.structure.sha256); return value; });
  evidence.inputs.push(loaded.file);
  handles.prepared = loaded.prepared;
  const P = loaded.prepared;

  // ---- no result yet: UK2; a set without an annotation
  await rec_.part("none", [K("C-uk2-none"), K("R-no-zero")], async () => {
    await rec_.step("K03-uk2-none", [K("C-uk2-none")], "Click 단백질 공학, choose the prepared structure: no same-structure result → " +
      "the not-selected notice and UK2 in the request area; 고르지 않음 selected", async () => {
      await openReady(page);
      await chooseStructure(page, P);
      return { value: await testId(page, "mutation-catalytic-annotation").inputValue(),
        none: clean(await testId(page, "mutation-no-catalytic").textContent()),
        notice: (await testId(page, "mutation-catalytic-notice").locator("p").allInnerTexts()).map(clean) };
    }, async value => {
      assert.equal(value.value, "");
      assert.ok(value.none.includes("효소 반응 지식 결과가 없습니다"), value.none);
      assert.deepEqual(value.notice, [CATALYTIC_NOT_SELECTED, UK2]);
      return value;
    });
    const s0 = await rec_.step("K04-set-none", [K("C-uk2-none"), K("R-no-zero")], "Set the plan's positions, click 후보 만들기 → " +
      "catalytic check not_checked (annotation_not_given); every catalytic cell — (not checked)", async () => {
      await setPositions(page, M.positions);
      return create(page, run);
    }, async value => {
      assert.equal(value.ok, true, JSON.stringify(value.body).slice(0, 400));
      assert.equal(value.args.catalytic_annotation, null);
      const verified = await verifyCatalyticSet(page, run, value.handle, { status: "not_checked", reason: "annotation_not_given" });
      await checkWording("S0");
      return { handle: value.handle, verified };
    });
    handles.s0 = s0.handle;
  });

  // ---- two results on the prepared structure through the 효소 반응 지식 area (real clicks)
  await rec_.step("K05-results", [K("C-preselect")], `Click 지식·보고서, 효소 반응 지식: the prepared structure, PDB ID ${M.pdbId}, ` +
    `chains ${M.chainsPartial.join(",")} → 연결하기; again with chains ${M.chainsAll.join(",")} → 연결하기`, async () => ({
    partial: await linkReaction(page, run, P, M.pdbId, M.chainsPartial),
    all: await linkReaction(page, run, P, M.pdbId, M.chainsAll) }), async value => {
    const list = (await readApi(page, `/runs/${run}/reaction_knowledge?offset=0&limit=100`)).items;
    assert.deepEqual(list.map(item => item.handle), [value.all, value.partial], "newest first");
    return value;
  }).then(value => { handles.rPartial = value.partial; handles.rAll = value.all; });

  // ---- the newest result pre-selected (never submitted); per-chain prediction with the partial one
  await rec_.part("preselect", [K("C-preselect"), K("C-prediction")], async () => {
    await rec_.step("K06-preselect", [K("C-preselect")], "Click 단백질 공학, choose the prepared structure: the newest result is " +
      "pre-selected (options: the two same-structure results, newest first); nothing is posted", async () => {
      const started = Date.now();
      await openReady(page);
      await chooseStructure(page, P);
      const select = testId(page, "mutation-catalytic-annotation");
      await waitFor(page, async () => await select.inputValue() !== "" ? true : null, "pre-selected", 30000);
      return { value: await select.inputValue(), options: (await selectOptions(select)).map(item => item.value).filter(Boolean),
        posts: posted(log, started) };
    }, async value => {
      assert.equal(value.value, handles.rAll);
      assert.deepEqual(value.options, [handles.rAll, handles.rPartial]);
      assert.deepEqual(value.posts, [], "the request was submitted by itself");
      return value;
    });
    await rec_.step("K07-prediction", [K("C-prediction")], "Set the plan's positions; with the newest result the covered chains " +
      "line lists every chain; choose the partial result → UK2 and one line per chain it does not cover", async () => {
      await setPositions(page, M.positions);
      const covered = testId(page, "mutation-catalytic-covered");
      await covered.waitFor({ timeout: 30000 });
      const full = { covered: await covered.getAttribute("data-covered-chains"),
        notice: await testId(page, "mutation-catalytic-notice").count() ? (await testId(page, "mutation-catalytic-notice")
          .locator("p").allInnerTexts()).map(clean) : [] };
      await selectFilter(page, "mutation-catalytic-annotation", handles.rPartial);
      await waitFor(page, async () => await testId(page, "mutation-catalytic-covered").getAttribute("data-covered-chains")
        === M.chainsPartial.join(",") ? true : null, "partial prediction", 30000);
      return { full, partial: { covered: await testId(page, "mutation-catalytic-covered").getAttribute("data-covered-chains"),
        notice: (await testId(page, "mutation-catalytic-notice").locator("p").allInnerTexts()).map(clean) } };
    }, async value => {
      const fullUncovered = M.expect.allUncovered ?? [];
      assert.equal(value.full.covered, M.chainsAll.filter(chain => !fullUncovered.some(item => item.chain_auth === chain)).join(","));
      if (!fullUncovered.length) assert.ok(!value.full.notice.includes(UK2), value.full.notice.join(" | "));
      assert.ok(value.partial.notice.includes(UK2), value.partial.notice.join(" | "));
      for (const item of M.expect.partialUncovered)
        assert.ok(value.partial.notice.includes(`체인 ${item.chain_auth}: 촉매 잔기를 검사하지 않음 — ${UNCOVERED_LABEL[item.coverage]} ` +
          `(${item.coverage})`), value.partial.notice.join(" | "));
      if (M.positions.ligandShell) assert.ok(value.partial.notice.includes(SERVER_POSITIONS_NOTE));
      assert.ok(!value.partial.notice.includes(UK3) || M.expect.uk3 === true);
      return value;
    });
  });

  // ---- sets: partial (chains_not_covered), full (checked), full + release
  await rec_.part("sets", [K("C-chains-not-covered"), K("C-checked"), K("C-lists"), K("C-release"), K("C-exclusion-seven"),
    K("R-no-zero")], async () => {
    const s1 = await rec_.step("K08-set-partial", [K("C-chains-not-covered"), K("R-no-zero")], "Click 후보 만들기 with the partial " +
      "result → not_checked (chains_not_covered): covered / uncovered chains, protected positions, — for the uncovered chain",
    () => create(page, run), async value => {
      assert.equal(value.ok, true, JSON.stringify(value.body).slice(0, 400));
      assert.equal(value.args.catalytic_annotation, handles.rPartial);
      const verified = await verifyCatalyticSet(page, run, value.handle, { status: "not_checked", reason: "chains_not_covered",
        covered: M.chainsPartial, uncovered: M.expect.partialUncovered, counts: M.expect.partialCounts,
        catalytic: M.expect.catalytic });
      await checkWording("S1");
      return { handle: value.handle, verified };
    });
    handles.s1 = s1.handle;
    const allUncovered = M.expect.allUncovered ?? [];
    const allStatus = allUncovered.length ? ["not_checked", "chains_not_covered"] : ["checked", null];
    const s2 = await rec_.step("K09-set-all", [K("C-checked"), K("C-lists"), K("C-exclusion-seven")], "Choose the newest (all " +
      "chains) result, click 후보 만들기 → the check status, row counts, catalytic_residue positions with M-CSA ids, conflict and " +
      "unmatched lists, seven exclusion reasons, the limitation variant", async () => {
      await selectFilter(page, "mutation-catalytic-annotation", handles.rAll);
      return create(page, run);
    }, async value => {
      assert.equal(value.ok, true, JSON.stringify(value.body).slice(0, 400));
      assert.equal(value.args.catalytic_annotation, handles.rAll);
      const verified = await verifyCatalyticSet(page, run, value.handle, { status: allStatus[0], reason: allStatus[1],
        covered: M.chainsAll.filter(chain => !allUncovered.some(item => item.chain_auth === chain)), uncovered: allUncovered,
        counts: M.expect.allCounts, catalytic: M.expect.catalytic, conflicts: M.expect.conflicts, unmatched: M.expect.unmatched });
      assert.ok(verified.protectedPositions.length > 0, "no position protected by a matched M-CSA row");
      await checkWording("S2");
      return { handle: value.handle, verified };
    });
    handles.s2 = s2.handle;
    const s3 = await rec_.step("K10-release", [K("C-release")], `Pick ${M.release.resname} ${M.release.chain}:${M.release.seq} in ` +
      "해제 목록, click 후보 만들기 → that position is a candidate, its M-CSA entries stay and the cell says 해제됨", async () => {
      await pickResidueAt(page, "release", M.release);
      return create(page, run);
    }, async value => {
      assert.equal(value.ok, true, JSON.stringify(value.body).slice(0, 400));
      const verified = await verifyCatalyticSet(page, run, value.handle, { status: allStatus[0], reason: allStatus[1],
        covered: M.chainsAll.filter(chain => !allUncovered.some(item => item.chain_auth === chain)), uncovered: allUncovered,
        counts: M.expect.allCounts, catalytic: M.expect.catalytic });
      const key = `${M.release.resname} ${M.release.chain}:${M.release.seq}`;
      const row = (await storedPositions(page, run, value.handle)).find(item => rkey(item.residue) === key);
      assert.ok(row && row.protection.released === true && row.status === "candidate" && row.protection.catalytic.length > 0,
        JSON.stringify(row?.protection));
      assert.ok(row.protection.reasons.includes("catalytic_residue"));
      const cell = (await catalyticCells(page)).find(item => item.residue === key);
      assert.ok(cell.text.endsWith("· 해제됨") && cell.released === "true", cell.text);
      const effects = (await storedSet(page, run, value.handle)).result.released_residues.map(item => [rkey(item.residue), item.effect]);
      assert.deepEqual(effects, [[key, "released"]]);
      await checkWording("S3");
      return { handle: value.handle, cell, effects };
    });
    handles.s3 = s3.handle;
  });

  // ---- the stored v1 run (copied T1 fixture): v1 wording and mark
  const limitationSeen = {};
  for (const name of ["s0", "s1", "s2"]) if (handles[name])
    limitationSeen[name] = (await storedSet(page, run, handles[name])).result.limitations[2];
  if (M.v1Run) await rec_.part("v1", [K("C-v1-set"), K("C-limitation-variants")], () => rec_.step("K11-v1", [K("C-v1-set"),
    K("C-limitation-variants")], `Choose the stored v1 run ${M.v1Run} in 저장된 run, click 단백질 공학: its sets carry the mark ` +
    "with the v1 detail; open one: not_available, the v1 limitation sentence, — (v1) cells, six exclusion reasons", async () => {
    await chooseRun(page, M.v1Run);
    await openReady(page);
    const sets = (await readApi(page, `/runs/${M.v1Run}/mutation_candidate_sets?offset=0&limit=100`)).rows;
    const marks = [];
    for (const row of sets) marks.push({ handle: row.handle, ...await setMark(page, row.handle) });
    await openSet(page, sets[0].handle);
    return { sets, marks, verified: await verifyCatalyticSet(page, M.v1Run, sets[0].handle, { status: "not_available",
      reason: "not_implemented" }) };
  }, async value => {
    assert.ok(value.sets.length >= 1);
    for (const item of value.marks) {
      assert.equal(item.status, "not_available");
      assert.equal(item.mark, UK2);
      assert.ok(item.detail.includes("(not_available)") && item.detail.includes("v1"), item.detail);
    }
    limitationSeen.v1 = value.verified.limitation3;
    assert.deepEqual([...new Set(Object.values(limitationSeen))].sort(), [LIMIT3.checked, LIMIT3.not_available,
      LIMIT3.not_checked].sort(), "the three limitation sentence 3 variants");
    return { marks: value.marks, verified: value.verified, limitationSeen };
  }));

  // ---- the shared mark on every place a set is picked
  if (handles.s1 && handles.s2) await rec_.part("pickers", [K("C-picker-marks")], async () => {
    const notChecked = [handles.s0, handles.s1].filter(Boolean);
    const checkedSet = (await storedSet(page, run, handles.s2)).result.protection_checks.catalytic_residue_database.status === "checked"
      ? handles.s2 : null;
    const picker = {};
    await rec_.step("K12-m20-list", [K("C-picker-marks")], "Choose run M, click 단백질 공학: the M20 result list marks the not-checked " +
      "sets (UK2 + their own detail) and not the checked one", async () => {
      await chooseRun(page, run);
      await openReady(page);
      const marks = {};
      for (const handle of [...notChecked, handles.s2]) marks[handle] = await setMark(page, handle);
      return marks;
    }, async value => {
      for (const handle of notChecked) {
        assert.equal(value[handle].mark, UK2);
        assert.ok(value[handle].detail.includes("(not_checked)"), value[handle].detail);
      }
      if (checkedSet) assert.equal(value[checkedSet].mark, null);
      picker.m20 = value;
      return value;
    });
    if (M.pickers.includes("m21")) await rec_.step("K13-m21", [K("C-picker-marks")], "Open the partial set, click 변이 구조 모델링 on a " +
      "candidate: the M21 request area shows the mark; then a candidate of the all-chains set", async () => {
      const started = Date.now();
      const out = {};
      for (const handle of [handles.s1, handles.s2]) {
        await openSet(page, handle);
        const button = testId(page, "mutation-candidate-model").first();
        await button.waitFor({ timeout: 30000 });
        await button.click();
        control(evidence, "mutation-candidate-model", { set: handle });
        const model = page.locator('[data-testid="mutation-model-panel"]');
        await model.locator(`[data-testid="mutation-model-candidate"][data-candidate-set="${handle}"]`).waitFor({ timeout: 30000 });
        out[handle] = { mark: await model.locator('[data-testid="mutation-model-catalytic"]').count()
          ? clean(await model.locator('[data-testid="mutation-model-catalytic"] .mw-catalytic-badge').textContent()) : null,
        detail: await model.locator('[data-testid="mutation-model-catalytic-detail"]').count()
          ? clean(await model.locator('[data-testid="mutation-model-catalytic-detail"]').textContent()) : null };
      }
      return { out, posts: posted(log, started) };
    }, async value => {
      assert.equal(value.out[handles.s1].mark, UK2);
      assert.ok(value.out[handles.s1].detail.includes("(not_checked)"), value.out[handles.s1].detail);
      if (checkedSet) assert.equal(value.out[handles.s2].mark, null);
      assert.deepEqual(value.posts, [], "the M21 handoff posted");
      picker.m21 = value.out;
      return value;
    });
    if (M.pickers.includes("m23")) await rec_.step("K14-m23", [K("C-picker-marks")], "서열 GA: the candidate set options name the mark " +
      "for not-checked sets; choose the partial set → the mark; choose the all-chains set → none", async () => {
      const started = Date.now();
      const ga = page.locator('[data-testid="sequence-ga-panel"]');
      const select = ga.locator('[data-testid="sequence-ga-candidate-set"]');
      await select.waitFor({ timeout: 30000 });
      const options = await selectOptions(select);
      await select.selectOption(handles.s1);
      control(evidence, "sequence-ga-candidate-set", { chosen: handles.s1 });
      await ga.locator('[data-testid="sequence-ga-catalytic"]').waitFor({ timeout: 15000 });
      const partial = clean(await ga.locator('[data-testid="sequence-ga-catalytic"] .mw-catalytic-badge').textContent());
      await select.selectOption(handles.s2);
      await page.waitForTimeout(500);
      const all = await ga.locator('[data-testid="sequence-ga-catalytic"]').count();
      await select.selectOption("");
      return { options, partial, all, posts: posted(log, started) };
    }, async value => {
      for (const handle of notChecked) assert.ok(value.options.find(item => item.value === handle).text.endsWith(UK2));
      if (checkedSet) assert.ok(!value.options.find(item => item.value === checkedSet).text.includes(UK2));
      assert.equal(value.partial, UK2);
      if (checkedSet) assert.equal(value.all, 0);
      assert.deepEqual(value.posts, [], "choosing a set posted");
      picker.m23 = { partial: value.partial, all: value.all };
      return value;
    });
    if (M.pickers.includes("m25")) await rec_.step("K15-m25", [K("C-picker-marks")], "JEV 루프 (단백질): the pool sources carry the mark " +
      "for not-checked sets and none for the checked set", async () => {
      const loop = page.locator('#mw-app-panel-protein [data-testid="jev-loop-panel"][data-branch="protein"]');
      await loop.locator('[data-testid="jev-loop-sources"]').waitFor({ timeout: 60000 });
      const out = {};
      for (const handle of [...notChecked, handles.s2]) out[handle] = await loop.locator(`label[data-jev-loop-source="${handle}"] ` +
        '[data-testid="jev-loop-source-catalytic"]').count();
      return out;
    }, async value => {
      for (const handle of notChecked) assert.equal(value[handle], 1);
      if (checkedSet) assert.equal(value[checkedSet], 0);
      picker.m25 = value;
      return value;
    });
    if (M.pickers.includes("m24")) await rec_.step("K16-m24", [K("C-picker-marks")], "Click 지식·보고서, JEV 판정: choose 변이 후보 as the " +
      "source kind → the sources carry the mark for not-checked sets and none for the checked set; nothing is sent", async () => {
      const started = Date.now();
      await selectTab(page, "지식·보고서");
      const jev = page.locator('#mw-app-panel-knowledge [data-testid="jev-panel"]');
      await jev.locator('[data-testid="jev-kind-mutation"]').waitFor({ timeout: 60000 });
      await jev.locator('[data-testid="jev-kind-mutation"]').check();
      control(evidence, "jev-kind-mutation", { checked: true });
      await jev.locator('[data-testid="jev-sources"]').waitFor({ timeout: 60000 });
      const out = {};
      for (const handle of [...notChecked, handles.s2]) out[handle] = await jev.locator(`label[data-jev-source="${handle}"] ` +
        '[data-testid="jev-source-catalytic"]').count();
      return { out, posts: posted(log, started) };
    }, async value => {
      for (const handle of notChecked) assert.equal(value.out[handle], 1);
      if (checkedSet) assert.equal(value.out[checkedSet], 0);
      assert.deepEqual(value.posts, [], "the JEV area posted");
      picker.m24 = value.out;
      return value;
    });
    evidence.pickers = picker;
  });

  await rec_.part("wording", [K("R-wording")], () => rec_.step("K17-wording", [K("R-wording")], "No rank / recommendation / " +
    "effect wording in the M20 panel outside the fixed sentences (every check of this mode)", async () => {
    await selectTab(page, "구조 분석");
    await chooseRun(page, run);
    await openReady(page);
    if (handles.s2) await openSet(page, handles.s2);
    await checkWording("final");
    return wording;
  }, async value => {
    assert.ok(value.length >= 2, `wording checks: ${value.length}`);
    assert.ok(value.every(item => item.found.length === 0));
    return value;
  }));
  evidence.providerCalls.push(await providerCalls(page, run));
  if (M.v1Run) evidence.providerCalls.push(await providerCalls(page, M.v1Run));
}

// ------------------------------------------------------------------ main
const RUNNERS = { main: modeMain, catalytic: modeCatalytic };

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const evidence = { schema: "m20_mutation_evidence@1", mode: input.mode, runs: {}, inputs: [], handles: {}, repro: null,
    fixtureLabels: [], providerCalls: [], partFailures: [], controls: {}, startedAt: new Date().toISOString() };
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
  fs.writeFileSync(path.join(input.artifacts, "mutation-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  fs.writeFileSync(path.join(input.artifacts, "mutation-requests.jsonl"), log.map(row => JSON.stringify(row)).join("\n") + "\n");
  const harness = Object.fromEntries(["mutation-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m20_case_ledger_row@1", mode: input.mode, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", cases, runId: evidence.runs.A ?? null, runs: evidence.runs,
    handles: evidence.handles, inputs: evidence.inputs, fixtureLabels: evidence.fixtureLabels, controls: evidence.controls,
    repro: evidence.repro, buildId: buildId(), harness, setHash: input["set-hash"],
    offscreen: proof, externalRequestCount: proof ? proof.nonLoopbackRequests : null, providerCalls: evidence.providerCalls,
    providerCallsZero: providerZero, partFailures: evidence.partFailures, error: evidence.error,
    evidenceFile: path.basename(rec_.file), startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, runs: evidence.runs, cases }) + "\n");
  if (error) process.stderr.write(`mutation-flow ${input.mode} failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`mutation-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, preflightOracle, halfUp2 };
