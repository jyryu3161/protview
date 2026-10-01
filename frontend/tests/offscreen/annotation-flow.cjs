"use strict";

// M16 reference site annotation offscreen QA (spec §10.4). Real Electron offscreen page (isOffscreen, GPU/WebGL, paint).
// Every product mutation is a Playwright locator mouse/keyboard/file-chooser/select input. Observation is read-only:
// data attributes and text of the page, the Mol* QA snapshot bridge (native readback), renderer request/response
// events, Electron paint frames, downloaded bytes and GET reads of the loopback API. Labeled renderer-route fixtures
// (a failed read, held late responses) are recorded in the ledger and never produce a scientific value.
//
// Independent oracle: docs/qa/m16-annotations-20261001/preflight.txt (T1; numpy on the prepared 1MQ4 coordinates,
// not the product's own functions): per-site contact counts / minimum distance and the ADP polar pairs.
//
// Modes (the full sequence: scripts/m16_offscreen_acceptance.py):
//   main       1MQ4 → prepare → ADP contacts → prepared-structure numbering map (PDB ID 1MQ4 confirmed) → annotation,
//              Mol* readback, scenes/figures (legend on/off, annotation off), restore, M8, report, no-contacts
//              annotation, pocket overlay, M10 comparison, labeled read failures + retry, run switch + late response
//   minimized  public 1UBQ → prepare → OpenMM minimization → minimized source shows the unavailable reason only
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const sharp = require("sharp");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const { waitForViewer } = require("./normal-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const FIXTURES = path.join(REPO, "backend/tests/fixtures");
const STRUCTURE = path.join(FIXTURES, "public_1mq4.cif");
const UBQ = path.join(FIXTURES, "public_1ubq.cif");
const PREFLIGHT = path.join(REPO, "docs/qa/m16-annotations-20261001/preflight.txt");
const MODES = ["main", "minimized"];
const ACCESSION = "O14965";
const ADP = { model_number: 1, chain_auth: "A", chain_label: "E", seq_auth: 2001, seq_label: null, icode: "", resname: "ADP" };
const RESIDUE_FIELDS = ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"];
const SITE_LABELS = ["III.17", "αC.24", "GK.45", "hinge.46", "hinge.47", "hinge.48", "xDFG.80", "xDFG.81", "xDFG.82", "xDFG.83"];
const FIGURE_LEGEND_TEXT = "점선: 기하 극성 접촉(원자 거리), 수소결합 판정 아님";
const PANEL_LEGEND_TEXT = "점선: 기하 극성 접촉(N/O–N/O 원자 거리, cutoff 이내). 수소결합 판정 아님.";
const MINIMIZED_REASON = "최소화 구조에는 번호 대응이 없어 주석할 수 없음";
const NO_MAP_PREREQUISITE = "이 구조로 지식 탭에서 번호 대응을 먼저 만드세요";
const POCKET_OVERLAY_BLOCKS_ANNOTATION = "포켓 오버레이가 켜져 있어 참조 주석을 켤 수 없습니다";
const ANNOTATION_BLOCKS_POCKET_OVERLAY = "참조 주석이 켜져 있어 포켓 오버레이를 켤 수 없습니다";
const COMPARISON_BLOCKS_ANNOTATION = "두 구조 비교(겹쳐 보기) 중에는 참조 주석을 켤 수 없습니다";
const ANNOTATION_BLOCKS_M8 = "참조 주석이 켜진 동안에는 자연어 뷰어 요청을 보낼 수 없습니다";
const RESTORE_BLOCKED_POCKET = "포켓 오버레이가 켜져 있어 참조 주석 보기를 복원하지 않았습니다";
const RESTORE_BLOCKED_COMPARISON = "두 구조 비교 중이라 참조 주석 보기를 복원하지 않았습니다";
const NO_CONTACT_RESULT_TEXT = "접촉 결과 없음";
const NO_CONTACT_IN_CUTOFF = "계산한 종류·cutoff 안 접촉 없음";
const FAULT_LABEL = "QA fault fixture (labeled renderer route, not a scientific value): site annotation read failure";
const HOLD_LABEL = "QA held-response fixture (labeled renderer route; unchanged backend bytes released late)";
const PROVIDER_EVENT_TYPES = new Set(["egress", "egress_budget_settled", "viewer_dispatch_started"]);

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const shortHandle = handle => handle.split("/").at(-1).slice(0, 12);
const sameResidue = (a, b) => !!a && !!b && RESIDUE_FIELDS.every(field => a[field] === b[field]);

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, "set-hash": null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2);
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode)) throw new Error(
    `Usage: annotation-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> [--url http://127.0.0.1:3000] ` +
    "[--set-hash <active reference set hash>]. Full sequence: scripts/m16_offscreen_acceptance.py.");
  if (value.mode === "main" && !value["set-hash"]) throw new Error("--set-hash is required for mode main");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  value.artifacts = path.resolve(value.artifacts);
  value.url = new URL("/", value.url).toString();
  return value;
}

// ------------------------------------------------------------------ independent oracle (T1 preflight)
/** Site table and ADP polar pairs of preflight.txt (numpy on the prepared 1MQ4 coordinates, T1). */
function preflightOracle() {
  const text = fs.readFileSync(PREFLIGHT, "utf8");
  const sites = new Map();
  for (const match of text.matchAll(/^\s{2}(\S+\.\d+)\s+([A-Z]{3})(\d+)\s*:\s*(\d+)\/(\d+)\/(\d+), min (없음|[\d.]+)$/gm))
    sites.set(match[1], { label: match[1], resname: match[2], seqAuth: Number(match[3]),
      counts: { contact: Number(match[4]), polar_contact: Number(match[5]), hydrophobic_contact: Number(match[6]) },
      min: match[7] === "없음" ? null : Number(match[7]) });
  const pairs = [...text.matchAll(/^\s{2}(\S+\.\d+) ([A-Z]{3})(\d+)\s+(\S+)\s+–\s+(\S+)\s+([\d.]+)\s+(\d+\.\d\d)$/gm)].map(match =>
    ({ label: match[1], resname: match[2], seqAuth: Number(match[3]), proteinAtom: match[4], ligandAtom: match[5],
      distance: Number(match[6]), shown: `${match[7]} Å` }));
  assert.equal(sites.size, 10, `preflight site table rows: ${sites.size}`);
  assert.equal(pairs.length, 10, `preflight polar pairs: ${pairs.length}`);
  return { file: fileRecord(PREFLIGHT), sites, pairs };
}
function halfUp2(value) {
  const text = String(value);
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
async function atomCatalog(page, run, handle) {
  const rows = [];
  let total = null;
  while (total === null || rows.length < total) {
    const chunk = await readApi(page, `/runs/${run}/structures/atoms?handle=${enc(handle)}&offset=${rows.length}&limit=500`);
    assert.equal(chunk.schema, "atom_catalog@1");
    total = chunk.total;
    rows.push(...chunk.rows);
    if (!chunk.rows.length) break;
  }
  return rows;
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
    rows.push({ at: Date.now(), method: request.method(), path: url.pathname, api: url.pathname.startsWith("/api/"),
      tool: request.method() === "POST" ? (() => { try { return request.postDataJSON()?.tool ?? null; } catch { return null; } })() : null });
  });
  return rows;
}

// ------------------------------------------------------------------ evidence
function recorder(session, input, evidence) {
  const { app, page, artifacts } = session;
  const file = path.join(artifacts, `annotation-${input.mode}.jsonl`);
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
      append({ caseId, cases, status: "pass", description, assertion, blockedRequests: proof.status.blockedRequests.length,
        paintCount: proof.status.paintCount, screenshot: fileRecord(proof.screenshot), paint: fileRecord(proof.paint.path),
        durationMs: Date.now() - started });
      mark(cases, true);
      return result;
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* keep the primary failure */ }
      const html = await page.evaluate(() => document.querySelector('[data-testid="site-annotation-panel"]')?.outerHTML.slice(0, 60000) ?? "")
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
  try { const text = JSON.stringify(value); return text.length > 4000 ? `${text.slice(0, 4000)}…` : JSON.parse(text); }
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
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).click();
  const viewer = await waitForViewer(page, value => !!value.sourceHandle && value.sourceHandle !== before &&
    value.sourceHandle.includes("/structure/") && value.catalogReady === true, 90000);
  return { handle: viewer.sourceHandle, file: { name: path.basename(file), ...fileRecord(file), provenance } };
}
async function prepareManual(page) {
  const back = page.getByRole("button", { name: "최신 구조로 돌아가기", exact: true });
  if (await back.isVisible().catch(() => false)) await back.click();
  const row = page.locator(".mw-workflow-row").filter({ has: page.getByRole("button", { name: "전처리", exact: true }) });
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    /\/commands$/.test(new URL(response.url()).pathname) && response.request().postDataJSON()?.tool === "prepare_structure",
  { timeout: 90000 });
  await row.getByRole("button", { name: "전처리", exact: true }).click();
  const body = await (await posted).json();
  assert.equal(body.ok, true, `prepare failed: ${JSON.stringify(body).slice(0, 400)}`);
  const prepared = body.handle.handle;
  assert.match(prepared, /\/prepared_structure\//);
  await waitForViewer(page, value => value.sourceHandle === prepared && value.catalogReady === true, 90000);
  return { prepared, policies: (await (await posted).request().postDataJSON()).args };
}

// ------------------------------------------------------------------ numbering panel (지식·보고서), as numbering-flow.cjs
const numbering = page => page.locator("section.mw-numbering");
const nTestId = (page, id) => numbering(page).locator(`[data-testid="${id}"]`);
const nAreaState = (page, name) => numbering(page).locator(`[data-numbering-area="${name}"]`)
  .getAttribute("data-state", { timeout: 2000 }).catch(() => null);
async function nWaitArea(page, name, states, timeout = 60000) {
  const wanted = Array.isArray(states) ? states : [states];
  return waitFor(page, async () => { const state = await nAreaState(page, name); return wanted.includes(state) ? state : null; },
    `${name} area ${wanted.join("|")}`, timeout);
}

// ------------------------------------------------------------------ site annotation panel and viewer
const sitePanel = page => page.locator('[data-testid="site-annotation-panel"]');
const sTestId = (page, id) => sitePanel(page).locator(`[data-testid="${id}"]`);
const panelState = page => sitePanel(page).getAttribute("data-site-annotation-state", { timeout: 2000 }).catch(() => null);
async function waitPanel(page, states, timeout = 60000) {
  const wanted = Array.isArray(states) ? states : [states];
  return waitFor(page, async () => { const state = await panelState(page); return wanted.includes(state) ? state : null; },
    `annotation panel ${wanted.join("|")}`, timeout);
}
/** Viewer root data attributes and the native readback of the QA snapshot bridge (read only). */
async function siteObserve(page) {
  return page.evaluate(() => {
    const node = [...document.querySelectorAll(".mw-molstar[data-site-annotation]")].find(item => item.getClientRects().length > 0);
    const snap = typeof window.__protviewQaSnapshot === "function" ? window.__protviewQaSnapshot() : null;
    return { data: node ? { ...node.dataset } : null, readback: snap?.siteAnnotation ?? null,
      error: snap?.siteAnnotationError ?? null, sourceHandle: snap?.sourceHandle ?? null, ready: snap?.ready ?? null,
      camera: snap?.camera ?? null, pocketOverlay: snap?.pocketOverlay ?? null, layers: snap?.layers?.length ?? null };
  });
}
async function waitSite(page, predicate, label, timeout = 60000) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    last = await siteObserve(page);
    try { if (predicate(last)) return last; } catch { /* keep polling */ }
    await page.waitForTimeout(150);
  }
  throw new Error(`${label}: timed out; last=${JSON.stringify({ data: last?.data, error: last?.error,
    lines: last?.readback?.drawnLineCount ?? null, source: last?.sourceHandle })}`);
}
const siteApplied = (obs, handle, legend) => obs.data?.siteAnnotation === "applied" && obs.data.siteAnnotationHandle === handle &&
  obs.readback?.handle === handle && (legend === undefined || obs.readback.legend === legend);
const siteNone = obs => obs.data?.siteAnnotation === "none" && !obs.readback;
async function mapRadios(page) {
  if (!await sTestId(page, "site-annotation-maps").count()) return [];
  return sTestId(page, "site-annotation-maps").locator("label[data-site-map]").evaluateAll(items => items.map(item => ({
    handle: item.getAttribute("data-site-map"), stale: item.getAttribute("data-stale"),
    checked: item.querySelector("input")?.checked ?? null, text: item.textContent.replace(/\s+/g, " ").trim() })));
}
async function contactRadios(page) {
  return sTestId(page, "site-annotation-contacts").locator("label[data-site-contact]").evaluateAll(items => items.map(item => ({
    value: item.getAttribute("data-site-contact"), checked: item.querySelector("input")?.checked ?? null,
    text: item.textContent.replace(/\s+/g, " ").trim() })));
}
async function annotationRows(page) {
  if (!await sTestId(page, "site-annotation-list").count()) return [];
  return sTestId(page, "site-annotation-list").locator("label[data-site-annotation-row]").evaluateAll(items => items.map(item => ({
    handle: item.getAttribute("data-site-annotation-row"), nullResult: item.getAttribute("data-null-result"),
    checked: item.querySelector("input")?.checked ?? null, text: item.textContent.replace(/\s+/g, " ").trim() })));
}
async function siteTable(page) {
  const table = sTestId(page, "site-annotation-sites");
  await table.waitFor({ timeout: 30000 });
  return { handle: await table.getAttribute("data-site-annotation-handle"),
    contactSource: clean(await sTestId(page, "site-annotation-contact-source").textContent()),
    rows: await table.locator("tr[data-site-klifs]").evaluateAll(items => items.map(item => {
      const cells = [...item.querySelectorAll("td")].map(cell => cell.textContent.replace(/\s+/g, " ").trim());
      const count = type => item.querySelector(`[data-site-count="${type}"]`)?.textContent.trim() ?? null;
      return { klifs: item.getAttribute("data-site-klifs"), status: item.getAttribute("data-site-status"),
        absentReason: item.getAttribute("data-site-absent-reason"), statusText: cells[1], label: cells[2],
        counts: { contact: count("contact"), polar_contact: count("polar_contact"), hydrophobic_contact: count("hydrophobic_contact") },
        min: item.querySelector("[data-site-min-distance]")?.textContent.trim() ?? null };
    })) };
}
async function toggleText(page) { return clean(await sTestId(page, "site-annotation-toggle").textContent()); }
/** Click 주석 표시 (real input) and wait for the Mol* native readback of that annotation. */
async function showAnnotation(page, handle, legend) {
  assert.equal(await toggleText(page), "주석 표시");
  await sTestId(page, "site-annotation-toggle").click();
  const obs = await waitSite(page, value => siteApplied(value, handle, legend), `annotation ${shortHandle(handle)} applied`, 90000);
  await sitePanel(page).locator('[data-testid="site-annotation-viewer-status"][data-site-annotation-viewer="applied"]').waitFor({ timeout: 30000 });
  return obs;
}
/** Choose an annotation in the panel list (real radio input) and wait for its site table. */
async function selectAnnotation(page, handle) {
  const radio = sTestId(page, "site-annotation-list").locator(`label[data-site-annotation-row="${handle}"] input`);
  if (!await radio.isChecked()) await radio.check();
  await sitePanel(page).locator(`[data-testid="site-annotation-sites"][data-site-annotation-handle="${handle}"]`).waitFor({ timeout: 30000 });
}
/** Show exactly this annotation: turn another one off first, choose it, click 주석 표시. */
async function ensureShown(page, handle, legend) {
  const now = await siteObserve(page);
  if (siteApplied(now, handle, legend)) return now;
  if (await toggleText(page) === "주석 끄기") await hideAnnotation(page);
  await selectAnnotation(page, handle);
  return showAnnotation(page, handle, legend);
}
async function ensureOff(page) {
  if (await toggleText(page) === "주석 끄기") return hideAnnotation(page);
  return waitSite(page, siteNone, "annotation off", 30000);
}
async function hideAnnotation(page) {
  assert.equal(await toggleText(page), "주석 끄기");
  await sTestId(page, "site-annotation-toggle").click();
  return waitSite(page, siteNone, "annotation off", 30000);
}
async function annotationDetail(page, run, handle) {
  const detail = await readApi(page, `/runs/${run}/site_annotations/detail?handle=${enc(handle)}`);
  assert.equal(detail.meta.handle, handle);
  assert.equal(detail.annotation.schema, "reference_site_annotation@1");
  return detail.annotation;
}
const annotatedSites = annotation => annotation.groups.flatMap(group => group.sites.filter(site => site.status === "annotated"));

// ------------------------------------------------------------------ scenes and figures (M9 controls)
const SCENE = { name: "보기 이름", save: "현재 보기 저장", saved: "저장된 보기", restore: "저장된 보기 복원",
  export: "현재 보기 PNG 내보내기", current: "현재 구조로 돌아가기", png: "PNG 다운로드", json: "JSON 출처 다운로드" };
async function waitViewerSession(page) {
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "확대");
    return !!button && !button.disabled;
  }, null, { timeout: 45000 });
  return waitForViewer(page, value => !!value.sessionId && value.catalogReady === true, 45000);
}
async function settleCamera(page) {
  let last = null, stable = 0;
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const current = await snapshot(page);
    const same = last && current?.camera && JSON.stringify(current.camera) === JSON.stringify(last.camera) && !current.cameraTransitioning;
    stable = same ? stable + 1 : 0;
    if (stable >= 6) return current;
    last = current;
  }
  throw new Error("camera did not settle");
}
async function saveScene(page, run, name) {
  await waitViewerSession(page);
  await settleCamera(page);
  await page.getByRole("textbox", { name: SCENE.name }).fill(name);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/viewer/scenes`, { timeout: 45000 });
  await page.getByRole("button", { name: SCENE.save, exact: true }).click();
  const response = await posted;
  assert.equal(response.status(), 201, `scene save failed: ${await response.text()}`);
  const body = await response.json();
  const requestBody = response.request().postDataJSON();
  await page.getByText(`보기 저장 완료 · ${name}`, { exact: true }).waitFor({ timeout: 30000 });
  assert.equal(await page.getByRole("combobox", { name: SCENE.saved }).inputValue(), body.handle);
  const stored = await readApi(page, `/runs/${run}/viewer/scenes/selected?handle=${enc(body.handle)}`);
  return { handle: body.handle, value: stored.value, requestKeys: Object.keys(requestBody).sort(), requestSchema: requestBody.schema,
    requestAnnotation: requestBody.annotation ?? null };
}
async function exportFigure(page, run) {
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/viewer/figures`, { timeout: 60000 });
  await page.getByRole("button", { name: SCENE.export, exact: true }).click();
  const response = await posted;
  assert.equal(response.status(), 201, `figure save failed: ${await response.text()}`);
  const handle = (await response.json()).handle;
  await page.getByText(`PNG 및 출처 JSON 저장 완료 · ${handle}`, { exact: true }).waitFor({ timeout: 30000 });
  const stored = await readApi(page, `/runs/${run}/viewer/figures/selected?handle=${enc(handle)}`);
  const requestBody = response.request().postDataJSON();
  return { handle, value: stored.value, requestSchema: requestBody.schema, legendComposited: requestBody.legend_composited ?? null };
}
/** Click PNG 다운로드 and JSON 출처 다운로드; both equal the backend bytes (read-only GET). */
async function downloadFigure(app, page, run, figure) {
  const result = {};
  for (const [format, label] of [["png", SCENE.png], ["json", SCENE.json]]) {
    const downloaded = await downloadByClick(app, page.getByRole("link", { name: label, exact: true }));
    const url = new URL(downloaded.url);
    assert.equal(url.pathname, `/api/runs/${run}/viewer/figures/download`);
    assert.equal(url.searchParams.get("handle"), figure.handle);
    assert.equal(url.searchParams.get("format"), format);
    const bytes = fs.readFileSync(downloaded.downloaded);
    const again = await readBytes(page, `/runs/${run}/viewer/figures/download?handle=${enc(figure.handle)}&format=${format}`);
    assert.ok(bytes.equals(again), `${format} download differs from the backend bytes`);
    if (format === "png") {
      assert.equal(sha(bytes), figure.value.png_sha256);
      assert.ok(bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])));
    } else assert.deepEqual(JSON.parse(bytes.toString("utf8")), figure.value);
    result[format] = { file: downloaded.downloaded, sha256: sha(bytes), backendSha256: sha(again), bytes: bytes.length };
  }
  return result;
}
async function restoreScene(page, scene) {
  await page.getByRole("combobox", { name: SCENE.saved }).selectOption(scene.handle);
  await page.getByRole("button", { name: SCENE.restore, exact: true }).click();
}
function cameraEqual(a, b) {
  for (const key of ["position", "target", "up"]) {
    assert.equal(a[key].length, b[key].length);
    a[key].forEach((value, index) => assert.ok(Math.abs(value - b[key][index]) <= 1e-6, `camera ${key}[${index}] ${value} != ${b[key][index]}`));
  }
  for (const key of ["fov", "radius"]) if (key in a) assert.ok(Math.abs(a[key] - b[key]) <= 1e-6, `camera ${key}`);
}

// ------------------------------------------------------------------ PNG pixel comparison (decoded with sharp)
async function decode(file) {
  const { data, info } = await sharp(file, { limitInputPixels: 4_000_000 }).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  return { data, width: info.width, height: info.height };
}
/** Pixels whose max channel difference exceeds `threshold`, split by an optional region predicate. */
function pixelDiff(a, b, region = () => false, threshold = 24) {
  assert.equal(a.width, b.width); assert.equal(a.height, b.height);
  let inside = 0, outside = 0;
  const box = { x0: Infinity, y0: Infinity, x1: -1, y1: -1 };
  for (let y = 0; y < a.height; y++) for (let x = 0; x < a.width; x++) {
    const at = (y * a.width + x) * 4;
    const delta = Math.max(Math.abs(a.data[at] - b.data[at]), Math.abs(a.data[at + 1] - b.data[at + 1]),
      Math.abs(a.data[at + 2] - b.data[at + 2]));
    if (delta <= threshold) continue;
    if (region(x, y)) inside++; else outside++;
    box.x0 = Math.min(box.x0, x); box.y0 = Math.min(box.y0, y); box.x1 = Math.max(box.x1, x); box.y1 = Math.max(box.y1, y);
  }
  return { inside, outside, total: inside + outside, box: box.x1 < 0 ? null : box, pixels: a.width * a.height };
}
function colorPixels(image, hex, tolerance = 28) {
  const target = [1, 3, 5].map(i => Number.parseInt(hex.slice(i, i + 2), 16));
  let count = 0;
  for (let at = 0; at < image.data.length; at += 4)
    if (Math.abs(image.data[at] - target[0]) <= tolerance && Math.abs(image.data[at + 1] - target[1]) <= tolerance &&
        Math.abs(image.data[at + 2] - target[2]) <= tolerance) count++;
  return count;
}
/** Yellow dashed-line pixels (polar line token #f0e442 after Mol* shading); the lime ligand colour is excluded. */
function yellowPixels(image) {
  let count = 0;
  for (let at = 0; at < image.data.length; at += 4) {
    const r = image.data[at], g = image.data[at + 1], b = image.data[at + 2];
    if (r >= 150 && g >= 130 && b <= 110 && r >= g - 15 && r - g <= 70) count++;
  }
  return count;
}
async function crop(file, box, out) {
  if (!box) return null;
  const left = Math.max(0, box.x0 - 10), top = Math.max(0, box.y0 - 10);
  const meta = await sharp(file).metadata();
  const width = Math.min(meta.width - left, box.x1 - box.x0 + 20), height = Math.min(meta.height - top, box.y1 - box.y0 + 20);
  await sharp(file).extract({ left, top, width, height }).resize(width * 3, height * 3, { kernel: "nearest" }).toFile(out);
  return fileRecord(out);
}
/** The lower-left legend box geometry of MolstarViewer.compositeFigureLegend (for the region split only). */
function legendRegion(width, height) {
  const fontSize = Math.max(12, Math.round(height * 0.026));
  const margin = Math.round(fontSize * 0.8), pad = Math.round(fontSize * 0.6);
  const boxHeight = Math.ceil(fontSize + 2 * pad);
  const y0 = height - margin - boxHeight;
  return { fontSize, x0: margin - 2, y0: y0 - 2, y1: height - margin + 2,
    contains: (x, y) => x >= margin - 2 && y >= y0 - 2 && y <= height - margin + 2 };
}

// ------------------------------------------------------------------ modes
async function modeMain(session, input, rec_, evidence, log) {
  const { page, app } = session;
  const oracle = preflightOracle();
  evidence.inputs.push({ name: "preflight.txt", ...oracle.file, provenance: "M16 T1 independent numpy oracle (committed QA text)" });
  const handles = evidence.handles;
  const runA = await rec_.step("M01-new-run", [], "Click 새 run (run A)", () => newRun(page), async id => ({ run: id }));
  evidence.runs.A = runA;

  // ---- 1MQ4 → prepare → ADP geometric contacts (ADP chosen explicitly among the two ligand instances)
  await rec_.part("contacts", ["A-load-prepare-contacts"], async () => {
    const cases = ["A-load-prepare-contacts"];
    const loaded = await rec_.step("M02-upload", cases, "Choose public_1mq4.cif, click 구조 불러오기",
      () => uploadLoad(page, STRUCTURE, "public PDB entry 1MQ4 (repository fixture; Aurora A kinase domain with ADP)"),
      async value => value);
    evidence.inputs.push(loaded.file);
    handles.structure = loaded.handle;
    const prepared = await rec_.step("M03-prepare", cases, "Click 전처리 (displayed default policies)", () => prepareManual(page),
      async value => value);
    handles.prepared = prepared.prepared;
    const contacts = await rec_.step("M04-adp-contacts", cases,
      "Choose the ADP instance in 리간드 (not the first option), click 기하 접촉 계산 (4 Å)", async () => {
        const select = page.getByRole("combobox", { name: /^리간드/ });
        const optionsShown = await select.locator("option").evaluateAll(items => items.map(item => ({ value: item.value, text: item.textContent.trim() })));
        const adp = optionsShown.filter(item => item.value !== "" && item.text.includes("ADP"));
        assert.equal(adp.length, 1, `ADP options: ${JSON.stringify(optionsShown)}`);
        await select.selectOption(adp[0].value);
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runA}/commands` &&
          response.request().postDataJSON()?.tool === "compute_interactions", { timeout: 90000 });
        await page.getByRole("button", { name: "기하 접촉 계산", exact: true }).click();
        const response = await posted;
        const body = await response.json();
        return { options: optionsShown, chosen: adp[0], request: response.request().postDataJSON().args, body };
      }, async value => {
        assert.equal(value.body.ok, true, JSON.stringify(value.body).slice(0, 400));
        assert.ok(value.options.filter(item => item.value !== "").length >= 2, "1MQ4 must offer ADP and PO4");
        assert.ok(sameResidue(value.request.ligand, ADP), `ligand sent: ${JSON.stringify(value.request.ligand)}`);
        assert.equal(value.request.structure, handles.prepared);
        await page.getByRole("region", { name: "기하 접촉 측정 행", exact: true }).waitFor({ timeout: 60000 });
        return { handle: value.body.handle.handle, ligand: value.request.ligand, cutoff: value.request.cutoff_A,
          types: value.request.types, options: value.options };
      });
    handles.contacts = contacts.body.handle.handle;
  });

  // ---- 지식·보고서: numbering map on the PREPARED structure with PDB ID 1MQ4 confirmed
  await rec_.part("numbering", ["A-numbering-prepared"], async () => {
    const made = await rec_.step("M05-numbering-prepared", ["A-numbering-prepared"],
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
        const hint = clean(await nTestId(page, "numbering-pdb-hint").textContent());
        await nTestId(page, "numbering-pdb-confirm").check();
        await waitFor(page, async () => (await nTestId(page, "numbering-accession-A").textContent()).includes(ACCESSION) ? true : null,
          "SIFTS prefill", 30000);
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runA}/commands` &&
          response.request().postDataJSON()?.tool === "map_residue_numbering", { timeout: 180000 });
        await nTestId(page, "numbering-run").click();
        const response = await posted;
        const body = await response.json();
        await nTestId(page, "numbering-run-result").filter({ hasText: "대응을 만들었습니다" }).waitFor({ timeout: 30000 });
        return { hint, body, request: response.request().postDataJSON().args };
      }, async value => {
        assert.equal(value.body.ok, true, JSON.stringify(value.body).slice(0, 400));
        assert.ok(value.hint.includes("1MQ4"), value.hint);
        assert.equal(value.request.pdb_id, "1MQ4");
        assert.equal(value.request.structure, handles.prepared);
        const listed = (await readApi(page, `/runs/${runA}/numbering_maps?offset=0&limit=100`)).rows
          .find(row => row.handle === value.body.handle.handle);
        assert.equal(listed.structure, handles.prepared);
        assert.equal(listed.structure_kind, "prepared_structure");
        assert.equal(listed.set_hash, input["set-hash"]);
        return { handle: value.body.handle.handle, pdbId: listed.pdb_id, counts: listed.counts, setHash: listed.set_hash };
      });
    handles.map = made.body.handle.handle;
  });

  // ---- 구조 분석 panel: choose map + contact result explicitly, create
  let annotation = null;
  if (handles.map && handles.contacts) await rec_.part("create", ["A-panel-create"], async () => {
    const cases = ["A-panel-create"];
    await rec_.step("M06-panel-ready", cases,
      "Click 구조 분석: the panel lists the prepared map and the ADP contact result; nothing is chosen automatically", async () => {
        await selectTab(page, "구조 분석");
        await sitePanel(page).waitFor({ timeout: 30000 });
        await waitPanel(page, ["ready"]);
        await waitFor(page, async () => (await mapRadios(page)).some(item => item.handle === handles.map) ? true : null,
          "prepared map listed in the panel", 30000);
        return { maps: await mapRadios(page), contacts: await contactRadios(page),
          createDisabled: await sTestId(page, "site-annotation-create").isDisabled(),
          createReason: clean(await sTestId(page, "site-annotation-create-reason").textContent().catch(() => "")),
          legendText: clean(await sTestId(page, "site-annotation-legend-text").textContent()),
          list: await annotationRows(page) };
      }, async value => {
        assert.deepEqual(value.maps.map(item => item.handle), [handles.map], "maps of other structures shown");
        assert.equal(value.maps[0].checked, false, "map chosen automatically");
        assert.deepEqual(value.contacts.map(item => item.value).sort(), [handles.contacts, "none"].sort());
        assert.ok(value.contacts.every(item => item.checked === false), "contact result chosen automatically");
        const adp = value.contacts.find(item => item.value === handles.contacts);
        assert.ok(adp.text.includes("ADP") && adp.text.includes("2001"), adp.text);
        assert.equal(value.createDisabled, true);
        assert.ok(value.createReason.length > 0, "no reason for the disabled 주석 만들기");
        assert.ok(value.legendText.includes(PANEL_LEGEND_TEXT), value.legendText);
        assert.ok(!/수소결합(?! 판정 아님)/.test(value.legendText.replace(PANEL_LEGEND_TEXT, "")), "hydrogen bond wording");
        assert.deepEqual(value.list, []);
        return { maps: value.maps, contacts: value.contacts, createReason: value.createReason };
      });
    annotation = await rec_.step("M07-create", cases,
      "Click the map radio, the ADP contact radio, 주석 만들기: annotate_reference_sites(map, contacts) → the new annotation opens", async () => {
        await sTestId(page, "site-annotation-maps").locator(`label[data-site-map="${handles.map}"] input`).check();
        control(evidence, "site-annotation-maps", { checked: handles.map });
        await sTestId(page, "site-annotation-contacts").locator(`label[data-site-contact="${handles.contacts}"] input`).check();
        control(evidence, "site-annotation-contacts:set", { checked: handles.contacts });
        await waitFor(page, async () => await sTestId(page, "site-annotation-create").isEnabled() ? true : null, "create enabled", 15000);
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runA}/commands` &&
          response.request().postDataJSON()?.tool === "annotate_reference_sites", { timeout: 60000 });
        await sTestId(page, "site-annotation-create").click();
        const response = await posted;
        const body = await response.json();
        const handle = body.handle?.handle;
        await waitFor(page, async () => (await annotationRows(page)).some(row => row.handle === handle && row.checked) ? true : null,
          "created annotation selected", 30000);
        await waitPanel(page, "ready");
        return { body, request: response.request().postDataJSON().args, handle, rows: await annotationRows(page) };
      }, async value => {
        assert.equal(value.body.ok, true, JSON.stringify(value.body).slice(0, 400));
        assert.deepEqual(value.request, { numbering_map: handles.map, contacts: handles.contacts });
        const stored = await annotationDetail(page, runA, value.handle);
        assert.equal(stored.structure.handle, handles.prepared);
        assert.equal(stored.numbering_map, handles.map);
        assert.equal(stored.contacts.handle, handles.contacts);
        assert.ok(sameResidue(stored.contacts.ligand, ADP));
        control(evidence, "site-annotation-create", { created: value.handle, listed: value.rows.length });
        return { handle: value.handle, request: value.request, rows: value.rows };
      });
    handles.annotation = annotation.handle;
  });

  let stored = null;
  let readback = null;
  if (handles.annotation) await rec_.part("table", ["A-site-table"], async () => {
    stored = await annotationDetail(page, runA, handles.annotation);
    await rec_.step("M08-site-table", ["A-site-table"],
      "Read the panel site table: labels, status, per-type counts and minimum distance equal the stored annotation and the T1 oracle",
      () => siteTable(page), async table => {
        const group = stored.groups.find(item => item.chain_auth === "A" && item.accession === ACCESSION);
        assert.ok(group && group.klifs_applied, "group A/O14965 not applied");
        assert.deepEqual(group.sites.map(site => site.klifs_label), SITE_LABELS);
        assert.equal(table.handle, handles.annotation);
        assert.ok(table.contactSource.includes("ADP") && table.contactSource.includes("cutoff 4"), table.contactSource);
        const shown = table.rows.filter((_, index) => index < 10);
        const compared = [];
        for (const [index, site] of group.sites.entries()) {
          const row = shown[index];
          const truth = oracle.sites.get(site.klifs_label);
          assert.equal(row.klifs, site.klifs_label);
          assert.equal(site.status, "annotated", `${site.klifs_label} ${site.absent_reason}`);
          assert.equal(row.status, "annotated");
          assert.equal(row.label, site.display_label);
          assert.equal(site.residue.seq_auth, truth.seqAuth);
          assert.equal(site.residue.resname, truth.resname);
          for (const type of ["contact", "polar_contact", "hydrophobic_contact"]) {
            assert.equal(site.contact.by_type[type].computed, true);
            assert.equal(site.contact.by_type[type].count, truth.counts[type], `${site.klifs_label} ${type} stored vs oracle`);
            assert.equal(row.counts[type], String(truth.counts[type]), `${site.klifs_label} ${type} cell`);
          }
          if (truth.min === null) {
            assert.equal(site.contact.min_distance_A, null);
            assert.equal(row.min, NO_CONTACT_IN_CUTOFF);
          } else {
            assert.ok(Math.abs(site.contact.min_distance_A - truth.min) <= 1e-9, `${site.klifs_label} min`);
            assert.equal(row.min, halfUp2(site.contact.min_distance_A));
          }
          compared.push({ klifs: row.klifs, label: row.label, counts: row.counts, min: row.min });
        }
        assert.ok(group.sites.some(site => site.display_label === "Glu211 (hinge.46)"), "Glu211 (hinge.46) label missing");
        return { compared, zeroSitesShownAsZeroNotNull: compared.filter(row => row.min === NO_CONTACT_IN_CUTOFF).map(row => row.klifs) };
      });
  });

  // ---- show: Mol* readback of sites, labels, lines vs display_labels and the independent polar-pair oracle
  if (handles.annotation) await rec_.part("show", ["A-show-readback"], async () => {
    stored ??= await annotationDetail(page, runA, handles.annotation);
    const catalog = await atomCatalog(page, runA, handles.prepared);
    const obs = await rec_.step("M09-show", ["A-show-readback"],
      "Click 주석 표시: Mol* readback sites/labels equal display_labels, lines equal the T1 polar pairs, none undrawn", async () => {
        const value = await showAnnotation(page, handles.annotation, true);
        control(evidence, "site-annotation-toggle:show", { data: value.data.siteAnnotation, lines: value.data.siteAnnotationLines });
        return { ...value, panelStatus: clean(await sTestId(page, "site-annotation-viewer-status").textContent()),
          undrawnList: await sTestId(page, "site-annotation-undrawn").getAttribute("data-undrawn-count") };
      }, async value => {
        const sites = annotatedSites(stored);
        const labels = sites.map(site => site.display_label);
        assert.equal(value.readback.drawnSiteCount, sites.length);
        assert.equal(Number(value.data.siteAnnotationSites), sites.length);
        assert.deepEqual(value.readback.sites.map(site => site.labelText), labels);
        assert.ok(labels.includes("Glu211 (hinge.46)"));
        assert.equal(value.readback.drawnLineCount, oracle.pairs.length, "drawn lines != T1 polar pairs");
        assert.equal(Number(value.data.siteAnnotationLines), oracle.pairs.length);
        assert.equal(value.readback.undrawnPairs.length, 0);
        assert.equal(value.data.siteAnnotationUndrawn, "0");
        assert.equal(value.undrawnList, "0");
        assert.equal(value.data.siteAnnotationLigandVisible, "true");
        assert.deepEqual(JSON.parse(value.data.siteAnnotationLabels), value.readback.labelTexts);
        assert.equal(value.readback.sourceHandle, handles.prepared);
        // Every oracle pair is drawn once, between the catalog atoms of that exact residue / ligand instance.
        const matched = [];
        for (const pair of oracle.pairs) {
          const site = sites.find(item => item.klifs_label === pair.label);
          const protein = catalog.filter(row => sameResidue(row.ref.residue, site.residue) && row.ref.atom_name === pair.proteinAtom);
          const ligand = catalog.filter(row => sameResidue(row.ref.residue, ADP) && row.ref.atom_name === pair.ligandAtom);
          assert.equal(protein.length, 1); assert.equal(ligand.length, 1);
          const line = value.readback.lines.filter(item => item.klifs_label === pair.label && item.protein_atom === pair.proteinAtom &&
            item.ligand_atom === pair.ligandAtom);
          assert.equal(line.length, 1, `line ${pair.label} ${pair.proteinAtom}-${pair.ligandAtom}`);
          assert.equal(line[0].proteinSourceIndex, protein[0].viewer_source_index);
          assert.equal(line[0].ligandSourceIndex, ligand[0].viewer_source_index);
          assert.equal(line[0].labelText, pair.shown, `distance label ${pair.label} ${pair.proteinAtom}-${pair.ligandAtom}`);
          assert.equal(line[0].pickable, false);
          matched.push({ site: pair.label, pair: `${pair.proteinAtom}-${pair.ligandAtom}`, label: line[0].labelText,
            proteinSourceIndex: line[0].proteinSourceIndex, ligandSourceIndex: line[0].ligandSourceIndex });
        }
        assert.ok(value.panelStatus.includes(`점선 ${oracle.pairs.length}개`), value.panelStatus);
        assert.ok(!value.readback.labelTexts.some(text => /수소결합/.test(text)));
        return { labels: value.readback.labelTexts, lines: matched, colors: value.readback.colors,
          otherContactResidues: value.readback.otherContactResidueCount, panelStatus: value.panelStatus };
      });
    readback = obs.readback;
  });

  // ---- scenes and figures: @2 legend on, @2 legend off, @1 annotation off; bytes and pixels
  const figures = {};
  const scenes = {};
  if (readback) await rec_.part("figures", ["A-figure-legend", "A-figure-no-legend", "A-figure-pixels", "A-scene-v1-unchanged"], async () => {
    await rec_.step("M10-figure-legend", ["A-figure-legend"],
      "Type 보기 이름, click 현재 보기 저장 (annotation on, legend on), 현재 보기 PNG 내보내기, PNG 다운로드, JSON 출처 다운로드", async () => {
        scenes.legend = await saveScene(page, runA, "m16 annotation legend");
        figures.legend = await exportFigure(page, runA);
        figures.legend.download = await downloadFigure(app, page, runA, figures.legend);
        return { scene: scenes.legend, figure: figures.legend };
      }, async value => {
        assert.equal(value.scene.requestSchema, "viewer_scene@2");
        assert.deepEqual(value.scene.requestAnnotation, { handle: handles.annotation, legend: true });
        assert.equal(value.scene.value.schema, "viewer_scene@2");
        assert.deepEqual(value.scene.value.annotation, { handle: handles.annotation, legend: true });
        assert.equal(value.figure.requestSchema, "viewer_figure@2");
        assert.equal(value.figure.legendComposited, true);
        const figure = value.figure.value;
        assert.equal(figure.schema, "viewer_figure@2");
        assert.equal(figure.capture_method, "molstar_image_pass+legend");
        assert.equal(figure.scene_handle, value.scene.handle);
        assert.equal(figure.annotation.handle, handles.annotation);
        assert.equal(figure.annotation.legend, true);
        assert.equal(figure.annotation.numbering_map, handles.map);
        assert.equal(figure.annotation.contacts, handles.contacts);
        assert.equal(figure.annotation.snapshot_set_hash, stored.snapshot_set_hash);
        assert.deepEqual(figure.annotation.display_labels, annotatedSites(stored).map(site => site.display_label));
        assert.ok(figure.width <= 2048 && figure.height <= 2048 && figure.width * figure.height <= 4_000_000);
        return { scene: value.scene.handle, figure: value.figure.handle, capture: figure.capture_method,
          png: value.figure.download.png, json: value.figure.download.json, size: [figure.width, figure.height] };
      });
    await rec_.step("M11-figure-no-legend", ["A-figure-no-legend"],
      "Untick 그림 범례 넣기 (redraw), 현재 보기 저장, 현재 보기 PNG 내보내기, PNG 다운로드, JSON 출처 다운로드", async () => {
        await sTestId(page, "site-annotation-legend").uncheck();
        const redrawn = await waitSite(page, value => siteApplied(value, handles.annotation, false), "legend-off redraw", 60000);
        control(evidence, "site-annotation-legend", { checked: false, readbackLegend: redrawn.readback.legend,
          lines: redrawn.readback.drawnLineCount });
        scenes.plain = await saveScene(page, runA, "m16 annotation no legend");
        figures.plain = await exportFigure(page, runA);
        figures.plain.download = await downloadFigure(app, page, runA, figures.plain);
        return { redrawn, scene: scenes.plain, figure: figures.plain };
      }, async value => {
        assert.equal(value.redrawn.readback.drawnLineCount, oracle.pairs.length);
        assert.deepEqual(value.scene.value.annotation, { handle: handles.annotation, legend: false });
        assert.equal(value.figure.value.schema, "viewer_figure@2");
        assert.equal(value.figure.legendComposited, false);
        assert.equal(value.figure.value.capture_method, "molstar_image_pass");
        assert.equal(value.figure.value.annotation.legend, false);
        return { scene: value.scene.handle, figure: value.figure.handle, capture: value.figure.value.capture_method,
          png: value.figure.download.png };
      });
    await rec_.step("M12-scene-v1", ["A-scene-v1-unchanged"],
      "Click 주석 끄기, tick 그림 범례 넣기 again, 현재 보기 저장 (viewer_scene@1 body unchanged), PNG 내보내기, PNG 다운로드", async () => {
        const off = await hideAnnotation(page);
        control(evidence, "site-annotation-toggle:off", { data: off.data.siteAnnotation });
        await sTestId(page, "site-annotation-legend").check();
        control(evidence, "site-annotation-legend", { checked: true, shown: false });
        scenes.off = await saveScene(page, runA, "m16 annotation off");
        figures.off = await exportFigure(page, runA);
        figures.off.download = await downloadFigure(app, page, runA, figures.off);
        return { off, scene: scenes.off, figure: figures.off };
      }, async value => {
        assert.equal(value.scene.requestSchema, "viewer_scene@1");
        assert.equal(value.scene.requestAnnotation, null);
        assert.ok(!value.scene.requestKeys.includes("annotation"), "annotation key sent in a @1 body");
        assert.equal(value.scene.value.schema, "viewer_scene@1");
        assert.ok(!("annotation" in value.scene.value));
        assert.equal(value.figure.value.schema, "viewer_figure@1");
        assert.equal(value.figure.requestSchema, "viewer_figure@1");
        assert.ok(!("annotation" in value.figure.value) && !("legend_composited" in value.figure.value));
        assert.equal(value.figure.value.capture_method, "molstar_image_pass");
        return { scene: value.scene.handle, figure: value.figure.handle, requestKeys: value.scene.requestKeys };
      });
    await rec_.step("M13-pixels", ["A-figure-pixels", "A-figure-legend"],
      "Decode the three downloaded PNGs of the same camera: legend pixels only in the legend corner; annotation lines/labels present", async () => {
        cameraEqual(scenes.legend.value.camera, scenes.plain.value.camera);
        cameraEqual(scenes.legend.value.camera, scenes.off.value.camera);
        const [legend, plain, off] = await Promise.all([figures.legend, figures.plain, figures.off].map(item => decode(item.download.png.file)));
        const region = legendRegion(legend.width, legend.height);
        const legendDiff = pixelDiff(legend, plain, region.contains);
        const annotationDiff = pixelDiff(plain, off, region.contains);
        const lineColor = readback.colors.polar_line;
        const regionPixels = (legend.width - region.x0) * (region.y1 - region.y0 + 1);
        const crops = { annotationOn: await crop(figures.plain.download.png.file, annotationDiff.box, path.join(rec_.artifacts, "M13-crop-annotation-on.png")),
          annotationOff: await crop(figures.off.download.png.file, annotationDiff.box, path.join(rec_.artifacts, "M13-crop-annotation-off.png")),
          legend: await crop(figures.legend.download.png.file, { x0: 0, y0: region.y0, x1: legend.width - 1, y1: legend.height - 1 },
            path.join(rec_.artifacts, "M13-crop-legend.png")) };
        return { size: [legend.width, legend.height], region: { x0: region.x0, y0: region.y0, y1: region.y1, fontSize: region.fontSize },
          legendDiff, annotationDiff, lineColor, crops,
          densities: { legendInside: legendDiff.inside / regionPixels, legendOutside: legendDiff.outside / (legendDiff.pixels - regionPixels) },
          lineColorExact: { plain: colorPixels(plain, lineColor), off: colorPixels(off, lineColor) },
          yellowLinePixels: { legend: yellowPixels(legend), plain: yellowPixels(plain), off: yellowPixels(off) } };
      }, async value => {
        // Legend: a dense block of changed pixels in the lower-left legend band; elsewhere only sparse antialiasing
        // edge noise of two separate Mol* image passes (≤ 1 %).
        assert.ok(value.legendDiff.inside >= 1000, `legend pixels ${value.legendDiff.inside}`);
        assert.ok(value.densities.legendOutside <= 0.01, `legend diff density outside the band ${value.densities.legendOutside}`);
        assert.ok(value.densities.legendInside >= 20 * value.densities.legendOutside, JSON.stringify(value.densities));
        // Annotation on vs off (same camera, both without legend): sticks, labels and dashed lines change pixels, and
        // yellow dashed-line pixels appear only with the annotation.
        assert.ok(value.annotationDiff.total >= value.annotationDiff.pixels * 0.005, `annotation diff ${value.annotationDiff.total}`);
        assert.ok(value.yellowLinePixels.plain >= 30 && value.yellowLinePixels.off <= 5,
          `yellow line pixels ${JSON.stringify(value.yellowLinePixels)}`);
        return value;
      });
  });

  // ---- restore the @2 view after turning the annotation off: the stored annotation is redrawn
  if (scenes.legend) await rec_.part("restore", ["A-restore-redraw"], async () => {
    await rec_.step("M14-restore", ["A-restore-redraw"],
      "Annotation off: choose the legend @2 view in 저장된 보기, click 저장된 보기 복원 → annotation redrawn (no tool call)", async () => {
        const before = await siteObserve(page);
        const started = Date.now();
        await restoreScene(page, scenes.legend);
        await page.getByText(`저장된 보기 복원 완료 · ${scenes.legend.value.name}`, { exact: true }).waitFor({ timeout: 60000 });
        const restored = page.locator('[data-testid="scene-annotation-restore"]');
        await restored.waitFor({ timeout: 30000 });
        const obs = await waitSite(page, value => siteApplied(value, handles.annotation, true), "restored annotation", 60000);
        return { before, obs, restore: { status: await restored.getAttribute("data-scene-annotation-restore"), text: clean(await restored.textContent()) },
          toggle: await toggleText(page), legendChecked: await sTestId(page, "site-annotation-legend").isChecked(),
          tools: log.filter(row => row.at >= started && row.tool).map(row => row.tool) };
      }, async value => {
        assert.ok(siteNone(value.before), "annotation was not off before the restore");
        assert.equal(value.restore.status, "applied", value.restore.text);
        assert.equal(value.obs.readback.drawnLineCount, oracle.pairs.length);
        assert.equal(value.obs.readback.drawnSiteCount, 10);
        assert.deepEqual(value.obs.readback.sites.map(site => site.labelText), annotatedSites(stored).map(site => site.display_label));
        assert.equal(value.toggle, "주석 끄기");
        assert.equal(value.legendChecked, true);
        assert.deepEqual(value.tools, [], `tool calls during restore: ${value.tools}`);
        cameraEqual((await snapshot(page)).nativeCamera ?? scenes.legend.value.camera, scenes.legend.value.camera);
        return { restore: value.restore, lines: value.obs.readback.drawnLineCount };
      });
    await rec_.step("M14b-current", [], "Click 현재 구조로 돌아가기", async () => {
      await page.getByRole("button", { name: SCENE.current, exact: true }).click();
      await waitForViewer(page, value => value.sourceHandle === handles.prepared && value.catalogReady === true, 60000);
      return siteObserve(page);
    }, async value => ({ annotation: value.data?.siteAnnotation, source: value.sourceHandle }));
  });

  // ---- M8: natural-language viewer requests blocked while shown; local "/" commands still work
  if (handles.annotation) await rec_.part("m8", ["A-blocked-m8"], async () => {
    const cases = ["A-blocked-m8"];
    await rec_.step("M15-m8-blocked", cases,
      "With the annotation shown: reason visible; type a natural-language request, press Enter and try 실행 → nothing sent", async () => {
        await ensureShown(page, handles.annotation);
        const agent = page.locator('section[aria-label="뷰어 요청"]');
        const reason = agent.locator("[data-viewer-natural-language-disabled]");
        await reason.waitFor({ timeout: 15000 });
        const eventsBefore = (await runEvents(page, runA)).length;
        const started = Date.now();
        await page.locator("#viewer-prompt").fill("리간드에 초점을 맞추고 표면으로 보기");
        const runDisabled = await agent.getByRole("button", { name: "실행", exact: true }).isDisabled();
        await page.locator("#viewer-prompt").press("Enter");
        await page.waitForTimeout(2000);
        return { reason: clean(await reason.textContent()), runDisabled,
          writes: log.filter(row => row.api && row.at >= started && row.method !== "GET").map(row => `${row.method} ${row.path}`),
          eventsAdded: (await runEvents(page, runA)).length - eventsBefore, annotation: (await siteObserve(page)).data?.siteAnnotation };
      }, async value => {
        assert.ok(value.reason.includes(ANNOTATION_BLOCKS_M8), value.reason);
        assert.equal(value.runDisabled, true);
        assert.deepEqual(value.writes, []);
        assert.equal(value.eventsAdded, 0);
        assert.equal(value.annotation, "applied");
        return value;
      });
    await rec_.step("M16-m8-local", cases, "Type /zoom in and click 실행: the local command runs with the annotation still drawn", async () => {
      const before = await settleCamera(page);
      const agent = page.locator('section[aria-label="뷰어 요청"]');
      await page.locator("#viewer-prompt").fill("/zoom in");
      await agent.getByRole("button", { name: "실행", exact: true }).click();
      const after = await waitFor(page, async () => {
        const now = await snapshot(page);
        return now?.camera && Math.abs(now.camera.distance - before.camera.distance) > 1e-3 ? now : null;
      }, "local zoom applied", 30000);
      return { before: before.camera.distance, after: after.camera.distance, obs: await siteObserve(page) };
    }, async value => {
      assert.ok(value.after < value.before, "zoom in did not bring the camera closer");
      assert.ok(siteApplied(value.obs, handles.annotation));
      return { distanceBefore: value.before, distanceAfter: value.after };
    });
    await rec_.step("M17-m8-off", cases, "Click 주석 끄기: the natural-language reason disappears", async () => {
      await hideAnnotation(page);
      await page.waitForTimeout(500);
      return { reasons: await page.locator("[data-viewer-natural-language-disabled]").count() };
    }, async value => { assert.equal(value.reasons, 0); return value; });
  });

  // ---- report: create, find in the knowledge-tab library, download bytes equal backend bytes
  if (handles.annotation) await rec_.part("report", ["A-report"], async () => {
    const cases = ["A-report"];
    const created = await rec_.step("M18-report", cases, "Click 보고서 만들기 in the panel", async () => {
      await selectAnnotation(page, handles.annotation);
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${runA}/method_reports`, { timeout: 60000 });
      await sTestId(page, "site-annotation-report").click();
      const response = await posted;
      const body = await response.json();
      const done = sTestId(page, "site-annotation-report-done");
      await done.waitFor({ timeout: 30000 });
      control(evidence, "site-annotation-report", { handle: body.handle, text: clean(await done.textContent()) });
      return { handle: body.handle, shown: await done.getAttribute("data-report-handle"), text: clean(await done.textContent()) };
    }, async value => {
      assert.equal(value.shown, value.handle);
      const listed = (await readApi(page, `/runs/${runA}/reports`)).find(item => item.handle === value.handle);
      assert.ok(listed, "report not in the backend list");
      assert.equal(listed.result_handle, handles.annotation);
      assert.equal(listed.analysis_type, "reference_site_annotation");
      return value;
    });
    handles.report = created.handle;
    const library = page.getByRole("region", { name: "보고서 보관함", exact: true });
    const reports = library.getByRole("region", { name: "저장된 보고서", exact: true });
    const content = library.getByRole("region", { name: "선택한 항목 내용", exact: true });
    await rec_.step("M19-library", cases, "Click 지식·보고서: 참조 주석 보고서 is listed; click it", async () => {
      await selectTab(page, "지식·보고서");
      const row = reports.locator("li button").filter({ hasText: created.handle });
      await row.waitFor({ timeout: 30000 });
      const kind = clean(await row.locator(".mw-library-kind").textContent());
      await row.click();
      const pre = content.getByLabel(`저장된 보고서 ${created.handle}`, { exact: true });
      await pre.waitFor({ timeout: 30000 });
      return { kind, text: await pre.textContent() };
    }, async value => {
      assert.equal(value.kind, "참조 주석 보고서");
      const saved = await readApi(page, `/runs/${runA}/reports/selected?handle=${enc(created.handle)}`);
      assert.equal(value.text, saved.markdown);
      // "수소결합" may appear only in a line equal to a fixed stored limitation sentence (a negative notice).
      const limitations = (await annotationDetail(page, runA, handles.annotation)).limitations;
      const hbLines = value.text.split("\n").filter(line => line.includes("수소결합"));
      for (const line of hbLines) assert.ok(limitations.includes(line.replace(/^[-*]\s+/, "").trim()), `hydrogen-bond wording: ${line}`);
      return { kind: value.kind, markdownSha256: sha(Buffer.from(value.text)), hydrogenBondLinesAllLimitations: hbLines };
    });
    for (const [label, format] of [["Markdown 다운로드", "markdown"], ["JSON 다운로드", "json"]]) {
      const route = `/runs/${runA}/reports/download?handle=${enc(created.handle)}&format=${format}`;
      await rec_.step(`M20-download-${format}`, cases, `Click ${label}; bytes equal the backend bytes`, () =>
        downloadByClick(rec_.app, content.getByRole("link", { name: label, exact: true })), async downloaded => {
        const bytes = fs.readFileSync(downloaded.downloaded);
        const saved = await readBytes(page, route);
        assert.equal(sha(bytes), sha(saved));
        const url = new URL(downloaded.url);
        assert.equal(`${url.pathname}${url.search}`, `/api${route}`);
        return { route, sha256: sha(bytes), backendSha256: sha(saved), bytes: bytes.length };
      });
    }
    await selectTab(page, "구조 분석");
  });

  // ---- annotation without a contact result
  if (handles.map) await rec_.part("no-contacts", ["A-no-contacts"], async () => {
    const made = await rec_.step("M21-no-contacts", ["A-no-contacts"],
      "Click the map radio, 접촉 결과 없이, 주석 만들기, then 주석 표시: sites and labels only, no numbers or lines", async () => {
        await selectTab(page, "구조 분석");
        await waitPanel(page, ["ready"]);
        await ensureOff(page);
        await sTestId(page, "site-annotation-maps").locator(`label[data-site-map="${handles.map}"] input`).check();
        await sTestId(page, "site-annotation-contacts").locator('label[data-site-contact="none"] input').check();
        control(evidence, "site-annotation-contacts:none", { checked: "none" });
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runA}/commands` &&
          response.request().postDataJSON()?.tool === "annotate_reference_sites", { timeout: 60000 });
        await sTestId(page, "site-annotation-create").click();
        const response = await posted;
        const body = await response.json();
        const handle = body.handle.handle;
        await waitFor(page, async () => (await annotationRows(page)).some(row => row.handle === handle && row.checked) ? true : null,
          "no-contact annotation selected", 30000);
        const table = await siteTable(page);
        const obs = await showAnnotation(page, handle, true);
        return { request: response.request().postDataJSON().args, handle, table, obs, rows: await annotationRows(page) };
      }, async value => {
        assert.deepEqual(value.request, { numbering_map: handles.map, contacts: null });
        const annotationValue = await annotationDetail(page, runA, value.handle);
        assert.equal(annotationValue.contacts, null);
        assert.ok(value.table.contactSource.includes(NO_CONTACT_RESULT_TEXT), value.table.contactSource);
        for (const row of value.table.rows) {
          assert.equal(row.status, "annotated");
          assert.deepEqual(Object.values(row.counts), [NO_CONTACT_RESULT_TEXT, NO_CONTACT_RESULT_TEXT, NO_CONTACT_RESULT_TEXT]);
          assert.equal(row.min, NO_CONTACT_RESULT_TEXT);
        }
        assert.equal(value.obs.readback.drawnSiteCount, 10);
        assert.equal(value.obs.readback.drawnLineCount, 0);
        assert.equal(value.obs.data.siteAnnotationLines, "0");
        assert.deepEqual(value.obs.readback.labelTexts, annotatedSites(annotationValue).map(site => site.display_label));
        const row = value.rows.find(item => item.handle === value.handle);
        assert.ok(row.text.includes(NO_CONTACT_RESULT_TEXT), row.text);
        return { handle: value.handle, labels: value.obs.readback.labelTexts, lines: 0, row: row.text };
      });
    handles.noContacts = made.handle;
    await rec_.step("M22-no-contacts-off", ["A-no-contacts"], "Click 주석 끄기", () => hideAnnotation(page), async value => ({ data: value.data?.siteAnnotation }));
  });

  // ---- pocket overlay exclusivity and @2 restore refusal
  if (handles.annotation) await rec_.part("pocket", ["A-blocked-pocket"], async () => {
    const cases = ["A-blocked-pocket"];
    const pocketPanel = page.locator('section[data-pocket-panel="main"]');
    const pockets = await rec_.step("M23-pocket-detect", [], "Choose the prepared source in 포켓 검출 소스, click 포켓 검출 실행 (approve)", async () => {
      await selectTab(page, "구조 분석");
      const select = pocketPanel.getByRole("combobox", { name: "포켓 검출 소스" });
      await select.locator(`option[value="${handles.prepared}"]`).waitFor({ state: "attached", timeout: 30000 });
      await select.selectOption(handles.prepared);
      const button = pocketPanel.getByRole("button", { name: "포켓 검출 실행" });
      await waitFor(page, async () => await button.isEnabled() ? true : null, "포켓 검출 실행 enabled", 60000);
      const submitted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${runA}/jobs`, { timeout: 60000 });
      await button.click();
      const job = await (await submitted).json();
      const approval = pocketPanel.getByRole("button", { name: "포켓 계산 승인 후 시작" });
      await approval.or(pocketPanel.locator('[data-pocket-job-status="running"], [data-pocket-job-status="done"]')).first().waitFor({ timeout: 60000 });
      if (await approval.isVisible().catch(() => false)) await approval.click();
      await pocketPanel.locator('[data-pocket-job-status="done"], [data-pocket-job-status="failed"]').first().waitFor({ timeout: 300000 });
      const durable = await readApi(page, `/runs/${runA}/jobs/${job.job_id}`);
      await pocketPanel.locator("[data-pocket-total-count], [data-pocket-null-result]").first().waitFor({ timeout: 60000 });
      return { job: durable.job_id ?? job.job_id, status: durable.status, set: durable.artifacts?.pocket_set };
    }, async value => {
      assert.equal(value.status, "done");
      assert.match(value.set ?? "", /\/pocket_set\//);
      const summary = await readApi(page, `/runs/${runA}/pockets/result?handle=${enc(value.set)}`);
      assert.ok(summary.pockets?.length > 0, "no pocket to overlay");
      return { ...value, rank: summary.pockets[0].rank };
    });
    const rank = (await readApi(page, `/runs/${runA}/pockets/result?handle=${enc(pockets.set)}`)).pockets[0].rank;
    const rankButton = pocketPanel.getByRole("button", { name: `포켓 rank ${rank} 선택` });
    await rec_.step("M24-annotation-blocks-overlay", cases,
      "Click 주석 표시: the pocket rank button is disabled with the reason; clicking it changes nothing", async () => {
        await ensureShown(page, handles.annotation);
        const blocked = pocketPanel.locator("[data-pocket-overlay-blocked]");
        await blocked.waitFor({ timeout: 15000 });
        await rankButton.click({ force: true, timeout: 5000 }).catch(() => undefined);
        await page.waitForTimeout(1000);
        return { reason: clean(await blocked.textContent()), disabled: await rankButton.isDisabled(), obs: await siteObserve(page) };
      }, async value => {
        assert.ok(value.reason.includes(ANNOTATION_BLOCKS_POCKET_OVERLAY), value.reason);
        assert.equal(value.disabled, true);
        assert.equal(value.obs.pocketOverlay, null);
        assert.equal(value.obs.data.pocketOverlay, "none");
        assert.ok(siteApplied(value.obs, handles.annotation));
        return { reason: value.reason };
      });
    await rec_.step("M25-overlay-blocks-annotation", cases,
      "Click 주석 끄기, then 포켓 rank 선택 (overlay on): 주석 표시 is disabled with the reason; @2 restore is refused", async () => {
        await hideAnnotation(page);
        await rankButton.click();
        await waitFor(page, async () => (await siteObserve(page)).data?.pocketOverlay === "applied" ? true : null, "overlay applied", 60000);
        const reason = sTestId(page, "site-annotation-show-reason");
        await reason.waitFor({ timeout: 15000 });
        const toggleDisabled = await sTestId(page, "site-annotation-toggle").isDisabled();
        await restoreScene(page, scenes.legend ?? { handle: "" });
        const refused = page.getByText(RESTORE_BLOCKED_POCKET, { exact: false });
        await refused.first().waitFor({ timeout: 15000 });
        return { reason: clean(await reason.textContent()), toggleDisabled, refused: clean(await refused.first().textContent()),
          obs: await siteObserve(page) };
      }, async value => {
        assert.ok(value.reason.includes(POCKET_OVERLAY_BLOCKS_ANNOTATION), value.reason);
        assert.equal(value.toggleDisabled, true);
        assert.ok(siteNone(value.obs), "annotation drawn together with the pocket overlay");
        assert.equal(value.obs.data.pocketOverlay, "applied", "the restore silently cleared the user's overlay");
        return { reason: value.reason, refused: value.refused };
      });
    await rec_.step("M26-overlay-clear", cases, "Click 오버레이 지우기: 주석 표시 is enabled again", async () => {
      await pocketPanel.getByRole("button", { name: "오버레이 지우기" }).click();
      await waitFor(page, async () => (await siteObserve(page)).data?.pocketOverlay === "none" ? true : null, "overlay cleared", 30000);
      await waitFor(page, async () => await sTestId(page, "site-annotation-toggle").isEnabled() ? true : null, "toggle enabled", 30000);
      return { reasons: await sTestId(page, "site-annotation-show-reason").count() };
    }, async value => { assert.equal(value.reasons, 0); return value; });
  });

  // A failed pocket part must not leave the overlay on for the next parts (cleanup through the same real control).
  if ((await siteObserve(page)).data?.pocketOverlay === "applied") {
    await page.locator('section[data-pocket-panel="main"]').getByRole("button", { name: "오버레이 지우기" }).click().catch(() => undefined);
    await waitFor(page, async () => (await siteObserve(page)).data?.pocketOverlay === "none" ? true : null, "overlay cleanup", 30000)
      .catch(() => undefined);
  }

  // ---- M10 comparison: starting one turns the annotation off; it cannot be turned on; @2 restore refused
  if (handles.annotation) await rec_.part("comparison", ["A-blocked-comparison"], async () => {
    const cases = ["A-blocked-comparison"];
    const panel = page.locator('[aria-label="원자 거리와 두 구조 비교"]');
    await rec_.step("M27-comparison", cases,
      "Click 주석 표시; choose 기준 구조 = prepared, 이동 구조 = original, three CA pairs (대응 추가), 정렬 계산 → annotation off", async () => {
        await ensureShown(page, handles.annotation);
        await panel.getByRole("combobox", { name: "기준 구조" }).selectOption(handles.prepared);
        await panel.getByRole("combobox", { name: "이동 구조" }).selectOption(handles.structure);
        const refCatalog = await atomCatalog(page, runA, handles.prepared);
        const movCatalog = await atomCatalog(page, runA, handles.structure);
        const ca = (rows, seq) => rows.filter(row => row.ref.residue.chain_auth === "A" && row.ref.residue.seq_auth === seq &&
          row.ref.atom_name === "CA");
        for (const seq of [162, 211, 274]) {
          const [ref] = ca(refCatalog, seq), [mov] = ca(movCatalog, seq);
          assert.ok(ref && mov, `CA ${seq}`);
          const refSelect = panel.getByRole("combobox", { name: "기준 CA site" });
          const movSelect = panel.getByRole("combobox", { name: "이동 CA site" });
          await refSelect.locator(`option[value="${ref.ref.site_index}"]`).waitFor({ state: "attached", timeout: 30000 });
          await movSelect.locator(`option[value="${mov.ref.site_index}"]`).waitFor({ state: "attached", timeout: 30000 });
          await refSelect.selectOption(String(ref.ref.site_index));
          await movSelect.selectOption(String(mov.ref.site_index));
          await panel.getByRole("button", { name: "대응 추가", exact: true }).click();
        }
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${runA}/commands`, { timeout: 60000 });
        await panel.getByRole("button", { name: "정렬 계산", exact: true }).click();
        const body = await (await posted).json();
        await panel.getByText(/정렬 RMSD/).waitFor({ timeout: 45000 });
        const obs = await waitSite(page, value => value.data?.siteAnnotation === "none", "annotation off after comparison start", 30000);
        return { body, obs, toggle: await toggleText(page) };
      }, async value => {
        assert.equal(value.body.ok, true, JSON.stringify(value.body).slice(0, 300));
        assert.ok(siteNone(value.obs));
        assert.equal(value.toggle, "주석 표시");
        return { alignment: value.body.handle.handle, annotation: value.obs.data.siteAnnotation };
      });
    await rec_.step("M28-comparison-blocked", cases, "During the comparison: 주석 표시 disabled with the reason; @2 restore refused", async () => {
      const reason = sTestId(page, "site-annotation-show-reason");
      await reason.waitFor({ timeout: 15000 });
      const disabled = await sTestId(page, "site-annotation-toggle").isDisabled();
      await sTestId(page, "site-annotation-toggle").click({ force: true, timeout: 5000 }).catch(() => undefined);
      await restoreScene(page, scenes.legend ?? { handle: "" });
      const refused = page.getByText(RESTORE_BLOCKED_COMPARISON, { exact: false });
      await refused.first().waitFor({ timeout: 15000 });
      await page.waitForTimeout(1000);
      return { reason: clean(await reason.textContent()), disabled, refused: clean(await refused.first().textContent()),
        obs: await siteObserve(page) };
    }, async value => {
      assert.ok(value.reason.includes(COMPARISON_BLOCKS_ANNOTATION), value.reason);
      assert.equal(value.disabled, true);
      assert.ok(siteNone(value.obs));
      assert.equal(value.obs.layers, 2, "the restore silently ended the comparison");
      return { reason: value.reason, refused: value.refused };
    });
    await rec_.step("M29-comparison-end", cases,
      "Click 단일 구조로 돌아가기: the comparison reason is gone; choose the annotation again and 주석 표시 is enabled", async () => {
      await page.getByRole("button", { name: "단일 구조로 돌아가기", exact: true }).click();
      await waitForViewer(page, value => value.sourceHandle === handles.prepared && value.catalogReady === true, 60000);
      await waitFor(page, async () => !clean(await sTestId(page, "site-annotation-show-reason").textContent().catch(() => ""))
        .includes(COMPARISON_BLOCKS_ANNOTATION) ? true : null, "comparison reason gone", 30000);
      const afterReturn = clean(await sTestId(page, "site-annotation-show-reason").textContent().catch(() => ""));
      await selectAnnotation(page, handles.annotation);
      await waitFor(page, async () => await sTestId(page, "site-annotation-toggle").isEnabled() ? true : null, "toggle enabled", 30000);
      return { afterReturn, reasons: await sTestId(page, "site-annotation-show-reason").count() };
    }, async value => { assert.equal(value.reasons, 0); return value; });
  });

  // ---- run switch: the annotation turns off; a held run A response released after the switch is not applied
  const runB = !handles.annotation ? null : await rec_.part("run-switch", ["A-run-switch-late"], async () => {
    const cases = ["A-run-switch-late"];
    const made = await rec_.step("M30-new-run-b", cases, "Click 주석 표시, then 새 run (run B) and upload 1MQ4: the annotation is off", async () => {
      await ensureShown(page, handles.annotation);
      const run = await newRun(page);
      const afterSwitch = await siteObserve(page);
      const up = await uploadLoad(page, STRUCTURE, "public PDB entry 1MQ4 (repository fixture)");
      await selectTab(page, "구조 분석");
      await waitPanel(page, ["ready"]);
      return { run, afterSwitch, handle: up.handle, rows: await annotationRows(page), maps: await mapRadios(page),
        prerequisite: clean(await sTestId(page, "site-annotation-prerequisite").textContent().catch(() => "")) };
    }, async value => {
      assert.ok(!value.afterSwitch.readback, "annotation still drawn after the run switch");
      assert.deepEqual(value.rows, []);
      assert.deepEqual(value.maps, []);
      assert.equal(value.prerequisite, NO_MAP_PREREQUISITE);
      return value;
    });
    evidence.runs.B = made.run;
    handles.runBStructure = made.handle;
    const held = [];
    let holding = true;
    const matcher = url => new URL(url).pathname === `/api/runs/${runA}/site_annotations`;
    const handler = async route => {
      if (!holding || route.request().method() !== "GET") return route.continue();
      held.push({ route, response: await route.fetch(), at: Date.now() });
    };
    await page.route(matcher, handler);
    evidence.fixtureLabels.push(HOLD_LABEL);
    try {
      await rec_.step("M31-held", cases, "Hold run A's annotation-list responses; choose run A in 저장된 run (panel loading)", async () => {
        await chooseRun(page, runA);
        await waitFor(page, async () => held.length >= 1 ? true : null, "held run A annotation list", 30000);
        return { held: held.length, state: await panelState(page) };
      }, async value => { assert.equal(value.state, "loading"); return value; });
      await rec_.step("M32-switch-b", cases, "Choose run B: run B's panel only", async () => {
        await chooseRun(page, made.run);
        await waitPanel(page, ["ready"]);
        return { rows: await annotationRows(page), run: await globalRun(page) };
      }, async value => { assert.deepEqual(value.rows, []); assert.equal(value.run, made.run); return value; });
      await rec_.step("M33-release", cases, "Release run A's held responses: run B's panel stays, no run A annotation appears", async () => {
        holding = false;
        const released = [];
        for (const item of held) {
          try { await item.route.fulfill({ response: item.response }); released.push({ delivered: true }); }
          catch (error) { released.push({ delivered: false, reason: String(error).slice(0, 160) }); }
        }
        await page.waitForTimeout(2500);
        return { released, rows: await annotationRows(page), text: clean(await sitePanel(page).textContent()),
          run: await globalRun(page), obs: await siteObserve(page) };
      }, async value => {
        assert.deepEqual(value.rows, []);
        for (const handle of [handles.annotation, handles.noContacts].filter(Boolean))
          assert.ok(!value.text.includes(shortHandle(handle)), `late run A annotation shown: ${handle}`);
        assert.equal(value.run, made.run);
        assert.ok(!value.obs.readback);
        return { released: value.released };
      });
    } finally {
      holding = false;
      for (const item of held) await item.route.fulfill({ response: item.response }).catch(() => undefined);
      await page.unroute(matcher, handler);
    }
    return made.run;
  });

  // ---- labeled read failures → the three retry controls recover
  if (runB && handles.annotation) await rec_.part("read-retry", ["A-read-retry"], async () => {
    const cases = ["A-read-retry"];
    const armed = { maps: true, list: true, detail: false };
    const faulted = [];
    const fault = (name, route) => {
      faulted.push({ name, at: Date.now(), path: new URL(route.request().url()).pathname });
      return route.fulfill({ status: 503, contentType: "application/json",
        body: JSON.stringify({ detail: { error: "qa_read_fault", message: FAULT_LABEL } }) });
    };
    const handlers = [
      [url => new URL(url).pathname === `/api/runs/${runA}/numbering_maps`, route =>
        armed.maps && route.request().method() === "GET" ? fault("maps", route) : route.continue()],
      [url => new URL(url).pathname === `/api/runs/${runA}/site_annotations`, route =>
        armed.list && route.request().method() === "GET" ? fault("list", route) : route.continue()],
      [url => new URL(url).pathname === `/api/runs/${runA}/site_annotations/detail`, route => {
        if (armed.detail && route.request().method() === "GET") { armed.detail = false; return fault("detail", route); }
        return route.continue();
      }]];
    for (const [matcher, handler] of handlers) await page.route(matcher, handler);
    evidence.fixtureLabels.push(FAULT_LABEL);
    try {
      await rec_.step("M34-fault", cases, "Fault run A's map-list and annotation-list reads; choose run A: the panel fails with both retries", async () => {
        await chooseRun(page, runA);
        await sTestId(page, "site-annotation-maps-retry").waitFor({ timeout: 30000 });
        await sTestId(page, "site-annotation-list-retry").waitFor({ timeout: 30000 });
        return { state: await panelState(page), failure: clean(await sTestId(page, "site-annotation-failure").textContent()),
          faulted: faulted.map(item => item.name) };
      }, async value => {
        assert.equal(value.state, "failure");
        assert.ok(value.failure.includes(FAULT_LABEL), value.failure);
        return value;
      });
      await rec_.step("M35-retry", cases, "Click 번호 대응 목록 다시 읽기 and 주석 목록 다시 읽기: both lists recover", async () => {
        armed.maps = false; armed.list = false;
        await sTestId(page, "site-annotation-maps-retry").click();
        await waitFor(page, async () => (await mapRadios(page)).length > 0 ? true : null, "maps recovered", 30000);
        control(evidence, "site-annotation-maps-retry", { maps: (await mapRadios(page)).length });
        await sTestId(page, "site-annotation-list-retry").click();
        await waitFor(page, async () => (await annotationRows(page)).length > 0 ? true : null, "list recovered", 30000);
        control(evidence, "site-annotation-list-retry", { rows: (await annotationRows(page)).length });
        return { maps: await mapRadios(page), rows: await annotationRows(page), state: await panelState(page) };
      }, async value => {
        assert.deepEqual(value.maps.map(item => item.handle), [handles.map]);
        const listed = (await readApi(page, `/runs/${runA}/site_annotations?structure=${enc(handles.prepared)}&offset=0&limit=100`)).rows;
        assert.deepEqual(value.rows.map(row => row.handle).sort(), listed.map(row => row.handle).sort());
        assert.equal(value.state, "ready");
        return { maps: value.maps.length, rows: value.rows.length };
      });
      await rec_.step("M36-detail-retry", cases, "Fault one detail read, click an annotation radio; click 주석 다시 읽기: the table opens", async () => {
        armed.detail = true;
        await sTestId(page, "site-annotation-list").locator(`label[data-site-annotation-row="${handles.annotation}"] input`).check();
        // (after the run switch nothing is selected, so this radio input opens the detail read)
        control(evidence, "site-annotation-list", { checked: handles.annotation });
        await sTestId(page, "site-annotation-detail-retry").waitFor({ timeout: 30000 });
        const failed = await panelState(page);
        await sTestId(page, "site-annotation-detail-retry").click();
        const table = await siteTable(page);
        control(evidence, "site-annotation-detail-retry", { table: table.handle });
        return { failed, table: table.handle, state: await panelState(page) };
      }, async value => {
        assert.equal(value.failed, "failure");
        assert.equal(value.table, handles.annotation);
        assert.equal(value.state, "ready");
        return { ...value, faulted: faulted.map(item => item.name) };
      });
    } finally {
      armed.maps = false; armed.list = false; armed.detail = false;
      for (const [matcher, handler] of handlers) await page.unroute(matcher, handler);
    }
  });

  for (const run of [runA, runB].filter(Boolean)) evidence.providerCalls.push(await providerCalls(page, run));
}

/** 1UBQ (OpenMM needs complete templates; engineering notes) → minimized source: only the unavailable reason. */
async function modeMinimized(session, input, rec_, evidence) {
  const { page } = session;
  const cases = ["B-minimized"];
  const run = await rec_.step("N01-new-run", [], "Click 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.runs.A = run;
  const loaded = await rec_.step("N02-upload", [], "Choose public_1ubq.cif, 구조 불러오기, 전처리", async () => {
    const up = await uploadLoad(page, UBQ, "public PDB entry 1UBQ (repository fixture; ubiquitin, no ligand)");
    const prepared = await prepareManual(page);
    return { ...up, prepared: prepared.prepared };
  }, async value => value);
  evidence.inputs.push(loaded.file);
  evidence.handles.prepared = loaded.prepared;
  const minimized = await rec_.step("N03-openmm", [], "Click 단백질 입력·제외 항목 확인, both acknowledgements, OpenMM 작업 제출, " +
    "작업 시작, 고비용 계산 승인 후 시작; wait for the real minimization", async () => {
    const openmm = page.getByText("OpenMM 단백질 전용 최소화 · kJ/mol").locator("..");
    await openmm.getByRole("button", { name: "단백질 입력·제외 항목 확인" }).click();
    await openmm.getByRole("region", { name: "OpenMM 제외 성분" }).waitFor({ timeout: 60000 });
    await openmm.getByLabel(/protein_only 선택과 제외 항목/).check();
    await openmm.getByLabel(/기존 수소 제거 후 pH 7.0/).check();
    await openmm.getByRole("button", { name: "OpenMM 작업 제출" }).click();
    await openmm.getByText(/상태 queued/).waitFor({ timeout: 30000 });
    const jobId = await openmm.getByLabel("작업").inputValue();
    await openmm.getByRole("button", { name: "작업 시작" }).click();
    const approve = openmm.getByRole("button", { name: "고비용 계산 승인 후 시작" });
    await approve.or(openmm.getByText(/상태 (running|done)/)).first().waitFor({ timeout: 60000 });
    if (await approve.isVisible().catch(() => false)) await approve.click();
    await openmm.getByText(/상태 done/).waitFor({ timeout: 600000 });
    const job = await readApi(page, `/runs/${run}/jobs/${enc(jobId)}`);
    assert.equal(job.status, "done", JSON.stringify(job.failure));
    const payload = await readApi(page, `/runs/${run}/openmm_minimization?handle=${enc(job.output_handles[0])}`);
    return { jobId, minimized: payload.result.minimized_structure };
  }, async value => { assert.match(value.minimized, /\/openmm_minimized_structure\//); return value; });
  evidence.handles.minimized = minimized.minimized;
  await rec_.step("N04-minimized-view", cases,
    "Click 최소화 단백질 좌표 보기: the panel shows only the unavailable reason (no numbers, no controls)", async () => {
      await page.getByRole("button", { name: "최소화 단백질 좌표 보기", exact: true }).click();
      await waitForViewer(page, value => value.sourceHandle === minimized.minimized && value.catalogReady === true, 90000);
      await waitPanel(page, "unavailable", 30000);
      return { state: await panelState(page), text: clean(await sitePanel(page).textContent()),
        reason: clean(await sTestId(page, "site-annotation-unavailable").textContent()),
        controls: await sitePanel(page).locator("button, input, select, textarea").count(), obs: await siteObserve(page) };
    }, async value => {
      assert.equal(value.state, "unavailable");
      assert.equal(value.reason, MINIMIZED_REASON);
      assert.ok(!/\d/.test(value.text), `a number is shown: ${value.text}`);
      assert.equal(value.controls, 0);
      assert.ok(siteNone(value.obs));
      return { reason: value.reason, text: value.text };
    });
  await rec_.step("N05-return", cases, "Click 최신 구조로 돌아가기: the prepared source is annotatable again (prerequisite shown)", async () => {
    await page.getByRole("button", { name: "최신 구조로 돌아가기", exact: true }).click();
    await waitForViewer(page, value => value.sourceHandle !== minimized.minimized && value.catalogReady === true, 90000);
    await waitPanel(page, ["ready"], 30000);
    return { state: await panelState(page), prerequisite: clean(await sTestId(page, "site-annotation-prerequisite").textContent()) };
  }, async value => { assert.equal(value.prerequisite, NO_MAP_PREREQUISITE); return value; });
  evidence.providerCalls.push(await providerCalls(page, run));
}

// ------------------------------------------------------------------ main
const RUNNERS = { main: modeMain, minimized: modeMinimized };

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const evidence = { schema: "m16_annotation_evidence@1", mode: input.mode, runs: {}, inputs: [], handles: {},
    fixtureLabels: [], providerCalls: [], partFailures: [], controls: {}, startedAt: new Date().toISOString() };
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
  fs.writeFileSync(path.join(input.artifacts, "annotation-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  fs.writeFileSync(path.join(input.artifacts, "annotation-requests.jsonl"), log.map(row => JSON.stringify(row)).join("\n") + "\n");
  const harness = Object.fromEntries(["annotation-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m16_case_ledger_row@1", mode: input.mode, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", cases, runId: evidence.runs.A ?? null, runs: evidence.runs,
    handles: evidence.handles, inputs: evidence.inputs, fixtureLabels: evidence.fixtureLabels, controls: evidence.controls,
    buildId: buildId(), harness, setHash: input["set-hash"],
    offscreen: proof, externalRequestCount: proof ? proof.nonLoopbackRequests : null, providerCalls: evidence.providerCalls,
    providerCallsZero: providerZero, partFailures: evidence.partFailures, error: evidence.error,
    evidenceFile: path.basename(rec_.file), startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, runs: evidence.runs, cases }) + "\n");
  if (error) process.stderr.write(`annotation-flow ${input.mode} failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`annotation-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, preflightOracle, legendRegion };
