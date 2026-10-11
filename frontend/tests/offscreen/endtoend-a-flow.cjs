"use strict";

// M28 end-to-end acceptance, branch A (.dryforge/spec.md §4.1, A1–A8): structure analysis and knowledge on public
// structures (1M17, 1FIN, 1MQ4, 1S9I, 1A30, 1A4I). Real Electron offscreen page (isOffscreen, GPU/WebGL, paint). Every
// product mutation is a Playwright locator mouse/keyboard/file-chooser/select input; nothing calls application
// internals. Observation is read-only: data attributes and text of the page, the Mol* QA snapshot bridge (native
// readback), renderer request/response events, Electron paint frames, downloaded bytes and GET reads of the loopback API.
//
// The plan (--plan, written by scripts/m28_branch_a.py) holds the independent expectations computed from the input
// files and the installed reference sets (A1 counts, A2 contact pairs, the A6 site oracle, A7 target counts, A8 M-CSA
// rows); the screen is compared with the stored objects and the stored objects with the plan. Nothing here supplies a
// scientific value. Real reference text (kbase, M-CSA / UniProt / Rhea) stays out of the step records: A7 / A8 steps
// keep IDs, counts and digests, their errors go to endtoend-a-real-errors.held, the tab texts go to texts/*.tabtext.
//
// Step functions come from the older harnesses (each block says "copied from <file>"); those files are not changed.
// Exported oracle helpers and constants are required: normal-flow (waitForViewer, validateReportDownload),
// pocket-flow (compareSpheres, validateReport), scenes-flow (checkPng), kinase-precedents-flow (KT1, LIMITATIONS, UP2,
// UP5, countTexts, chainCells, pageText, bareZeroOrNone, mdEscape, forbiddenIn, realSafe, textDigest) and
// reaction-knowledge-flow (checkChainExpectation, identityText, forbiddenIn, FIXED).
//
// Parts (a part whose earlier part did not pass is not run and says which one): A1 → A2 → A3 → A4 → A5-m17 → A6 →
// A5-others → A7 → A8. A5 runs in two parts so that A6 (annotation on the 1M17 prepared structure) is done before
// other structures are loaded into the run.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const { waitForViewer, validateReportDownload } = require("./normal-flow.cjs");
const { compareSpheres, validateReport } = require("./pocket-flow.cjs");
const { checkPng } = require("./scenes-flow.cjs");
const kinase = require("./kinase-precedents-flow.cjs");
const reaction = require("./reaction-knowledge-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const MODES = ["fixture"];
const KNOWLEDGE = "지식·보고서";
const RESIDUE_FIELDS = ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"];
const PROVIDER_EVENT_TYPES = new Set(["egress", "egress_budget_settled", "viewer_dispatch_started"]);
// M16 decision 0024: the ten reference sites (KLIFS positions) of the annotation, in stored order.
const SITE_LABELS = ["III.17", "αC.24", "GK.45", "hinge.46", "hinge.47", "hinge.48", "xDFG.80", "xDFG.81", "xDFG.82", "xDFG.83"];
const NO_CONTACT_IN_CUTOFF = "계산한 종류·cutoff 안 접촉 없음";              // copied from annotation-flow.cjs
const KLIFS_REFERENCE_HEADER = "KLIFS 번호 (참조)";
const NUMBERING_REFERENCE_NOTE = "UniProt accession·위치·잔기와 KLIFS 번호는 참조 스냅샷 값이며 계산값이 아닙니다.";
const REACTION_REFERENCE_NOTE = "참조값, 계산 아님";
// Fixed sentences of the M26 harness (FIXED = RK1–RK6, UK1–UK4 in that order; spec §11.1 of M26, verbatim).
const RK = reaction.FIXED.slice(0, 6);
const UK = { UK1: reaction.FIXED[6], UK4: reaction.FIXED[9] };
const ROW_LABEL = { matched: "대응됨", unmatched: "대응 없음", conflict: "충돌" };   // copied from reaction-knowledge-flow.cjs
const REFERENCE_COLUMN = "M-CSA 원문, 계산 아님";                            // copied from reaction-knowledge-flow.cjs
const NULL = "—";
// A line naming a hydrogen bond must be a negation (geometric contacts are never called hydrogen bonds).
const HBOND = /수소\s*결합|hydrogen[\s-]+bonds?/i;
const NEGATION = /아님|아닙니다|아니다|아니며|아니고|\bnot\b|\bno\b/i;
// Fixed-wording checks of the kinase / reaction harnesses need the forbidden list of those harnesses only.
const DESCRIPTOR_UNITS = { score: "dimensionless", druggability_score: "dimensionless", alpha_sphere_count: "count",
  total_sasa_A2: "A2", volume_A3: "A3" };                                     // copied from pocket-flow.cjs
const DESCRIPTOR_ORDER = ["score", "druggability_score", "alpha_sphere_count", "total_sasa_A2", "volume_A3"];
const UNIT_RENDER = { A2: text => `${text} Å²`, A3: text => `${text} Å³`, count: text => `${text}개`,
  dimensionless: text => `${text} (무차원)` };
const SASA_FIELDS = [["단백질 매몰", "protein_burial_A2"], ["리간드 매몰", "ligand_burial_A2"],
  ["총 SASA 손실", "total_sasa_loss_A2"], ["분리 단백질 SASA", "protein_sasa_isolated_A2"],
  ["분리 리간드 SASA", "ligand_sasa_isolated_A2"], ["결합체 SASA", "complex_sasa_A2"]];
const SASA_ROW_FIELDS = ["isolated_A2", "bound_A2", "buried_A2"];
const PNG_MAX_BYTES = 8 * 1024 * 1024;

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const residueKey = residue => JSON.stringify(RESIDUE_FIELDS.map(field => residue[field]));
const sameResidue = (a, b) => !!a && !!b && RESIDUE_FIELDS.every(field => a[field] === b[field]);
const noDigit = text => !/\d/.test(text);

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, plan: null, "runs-dir": null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2);
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode) || !value.plan) throw new Error(
    `Usage: endtoend-a-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> --plan <plan.json> [--url http://127.0.0.1:3000] ` +
    "[--runs-dir <dir>]. Plan and sequence: scripts/m28_branch_a.py through scripts/m28_offscreen_acceptance.py.");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  value.artifacts = path.resolve(value.artifacts);
  value.url = new URL("/", value.url).toString();
  value.planData = JSON.parse(fs.readFileSync(value.plan, "utf8"));
  assert.equal(value.planData.schema, "m28_branch_a_plan@1");
  return value;
}

// ------------------------------------------------------------------ number formats (independent of the product)
/** Decimal ROUND_HALF_UP of the shortest decimal text of a finite number (String(value)) to ``digits`` places. */
function halfUp(value, digits) {
  assert.ok(Number.isFinite(value), `not a finite number: ${value}`);
  const text = Math.abs(value).toString();
  if (text.includes("e")) {
    assert.ok(Math.abs(value) < 1e-6, `exponent form outside the rounding helper: ${text}`);
    return (0).toFixed(digits);
  }
  const [whole, fraction = ""] = text.split(".");
  let scaled = BigInt(whole + fraction.slice(0, digits).padEnd(digits, "0"));
  if (fraction.length > digits && fraction[digits] >= "5") scaled += 1n;
  const body = scaled.toString().padStart(digits + 1, "0");
  const out = digits ? `${body.slice(0, -digits)}.${body.slice(-digits)}` : body;
  return value < 0 && scaled !== 0n ? `-${out}` : out;
}
/** The area rendering of SASA values: two places, |v| < 0.0001 shown as 0.00 (frontend/src/lib/area-format.ts rule). */
const area2 = value => Math.abs(value) < 0.0001 ? "0.00" : halfUp(value, 2);
const angstrom2 = value => `${halfUp(value, 2)} Å`;

// ------------------------------------------------------------------ read-only observation (copied from annotation-flow.cjs)
async function readApi(page, route) {
  const response = await page.request.get(new URL(`/api${route}`, page.url()).toString());
  assert.equal(response.status(), 200, `${route}: HTTP ${response.status()}`);
  const value = await response.json();
  if (/precedent|numbering_maps|reaction/.test(route)) SEEN.push(value);
  return value;
}
// Stored precedent / reaction / map answers seen: removed from screen text before the wording checks (memory only).
const SEEN = [];
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
async function storedRows(page, run, handle) {
  const rows = [];
  let total = null;
  while (total === null || rows.length < total) {
    const chunk = await readApi(page, `/runs/${run}/objects?handle=${enc(handle)}&offset=${rows.length}&limit=100`);
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
    try { last = await probe(); if (last) return last; } catch (error) { last = String(error).slice(0, 300); }
    await page.waitForTimeout(150);
  }
  throw new Error(`${label}: timed out; last=${JSON.stringify(last)?.slice(0, 400)}`);
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
/** Steps and parts (adapted from annotation-flow.cjs recorder). A part runs only when the parts it needs passed; a
 * step failure fails its part, which is recorded and the flow goes on with the next part. ``real`` parts (A7, A8)
 * keep IDs, counts and digests only (kinase-precedents-flow realSafe) and write error text to a held file. */
function recorder(session, evidence) {
  const { app, page, artifacts } = session;
  const file = path.join(artifacts, "endtoend-a.jsonl");
  // Not a text suffix of the runner: assertion text may quote reference values, so it stays in the git-ignored
  // artifacts (path, size and SHA-256 only in the committed evidence).
  const errors = path.join(artifacts, "endtoend-a-real-errors.held");
  const append = row => fs.appendFileSync(file, JSON.stringify(row) + "\n");
  let current = null;
  const real = () => current?.real === true;
  const errorText = (id, error) => {
    const text = String(error?.stack ?? error);
    if (!real()) return text;
    fs.appendFileSync(errors, `--- ${id}\n${text}\n`);
    return { errorDigest: kinase.textDigest(text), errorName: error?.name ?? null, heldIn: path.basename(errors) };
  };
  async function step(id, description, action, check) {
    const started = Date.now();
    let result;
    try {
      result = await action();
      const assertion = await check(result);
      const proof = await capture(app, page, artifacts, id);
      assert.equal(proof.status.blockedRequests.length, 0, "renderer attempted a non-loopback request");
      assert.equal(proof.status.offscreen, true);
      append({ id, part: current?.name ?? null, status: "pass", description,
        assertion: real() ? kinase.realSafe(summarize(assertion)) : summarize(assertion),
        blockedRequests: proof.status.blockedRequests.length, paintCount: proof.status.paintCount,
        screenshot: fileRecord(proof.screenshot), paint: fileRecord(proof.paint.path), durationMs: Date.now() - started });
      return result;
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${id}-failure`); } catch { /* keep the primary failure */ }
      append({ id, part: current?.name ?? null, status: "fail", description, error: errorText(id, error),
        screenshot: proof && fileRecord(proof.screenshot), paint: proof && fileRecord(proof.paint.path),
        durationMs: Date.now() - started });
      throw error;
    }
  }
  async function part(name, needs, work, { real: isReal = false } = {}) {
    const blocked = needs.filter(need => evidence.parts[need]?.status !== "pass");
    if (blocked.length) {
      evidence.parts[name] = { status: "not_run", blockedBy: blocked };
      append({ id: `${name}-not-run`, part: name, status: "not_run", blockedBy: blocked });
      return null;
    }
    current = { name, real: isReal };
    evidence.parts[name] = { status: "running", startedAt: new Date().toISOString() };
    try {
      const value = await work();
      evidence.parts[name] = { ...evidence.parts[name], status: "pass", finishedAt: new Date().toISOString() };
      return value;
    } catch (error) {
      evidence.parts[name] = { ...evidence.parts[name], status: "fail", finishedAt: new Date().toISOString(),
        error: isReal ? "held (reference text)" : String(error).slice(0, 800) };
      append({ id: `${name}-aborted`, part: name, status: "fail", error: errorText(`${name}-aborted`, error) });
      return null;
    } finally { current = null; }
  }
  return { step, part, append, file };
}
function summarize(value) {
  try { const text = JSON.stringify(value); return text.length > 6000 ? `${text.slice(0, 6000)}…` : JSON.parse(text); }
  catch { return String(value); }
}
/** A tab area's text for the X4 scan, handed to the runner through the branch module. The file suffix is not a text
 * suffix of the runner (texts/<name>.tabtext): the knowledge tab quotes kbase and M-CSA / UniProt / Rhea text, so these
 * dumps stay in the git-ignored artifacts (path, size and SHA-256 only) and are not scanned twice. */
async function keepTabText(page, evidence, artifacts, name, tabId) {
  const node = page.locator(`#mw-app-panel-${tabId}`);
  const text = await node.innerText({ timeout: 15000 });
  const rel = path.join("texts", `${name.replace(/[^a-z0-9_-]/gi, "_")}.tabtext`);
  fs.mkdirSync(path.join(artifacts, "texts"), { recursive: true });
  fs.writeFileSync(path.join(artifacts, rel), text);
  evidence.texts[name] = rel;
  return { name, ...kinase.textDigest(text) };
}
function noteReport(evidence, caseId, kind, status, handle) {
  if (status === 201) evidence.reportsCreated += 1;
  evidence.reportHandles.push({ case: caseId, kind, httpStatus: status, handle });
}
function x5(evidence, ok, detail) { evidence.x5.push({ ok: !!ok, detail }); }
/** Lines naming a hydrogen bond in ``text``: every one must be a negation. Returns their count and digests. */
function hbondLines(text) {
  const lines = String(text).split("\n").map(clean).filter(line => HBOND.test(line));
  const positive = lines.filter(line => !NEGATION.test(line));
  assert.deepEqual(positive.map(line => kinase.textDigest(line).sha256), [], "a line names a hydrogen bond without negating it");
  return { negationLines: lines.length, lineSha256: lines.map(line => kinase.textDigest(line).sha256) };
}

// ------------------------------------------------------------------ tabs, runs, structure screen (copied from annotation-flow.cjs)
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
async function uploadLoad(page, item) {
  await selectTab(page, "구조 분석");
  await page.getByRole("tab", { name: /^run/i }).click();
  const before = (await snapshot(page))?.sourceHandle ?? null;
  const chooser = page.waitForEvent("filechooser", { timeout: 30000 });
  await page.locator('input[type="file"]').first().click();
  await (await chooser).setFiles(item.path);
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).click();
  const viewer = await waitForViewer(page, value => !!value.sourceHandle && value.sourceHandle !== before &&
    value.sourceHandle.includes("/structure/") && value.catalogReady === true, 120000);
  const record = fileRecord(item.path);
  assert.equal(record.sha256, item.sha256, `${item.name}: the input file changed since the plan was written`);
  return { handle: viewer.sourceHandle, file: { name: item.name, bytes: record.bytes, sha256: record.sha256,
    provenance: item.provenance } };
}
async function prepareManual(page) {
  const back = page.getByRole("button", { name: "최신 구조로 돌아가기", exact: true });
  if (await back.isVisible().catch(() => false)) await back.click();
  const row = page.locator(".mw-workflow-row").filter({ has: page.getByRole("button", { name: "전처리", exact: true }) });
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    /\/commands$/.test(new URL(response.url()).pathname) && response.request().postDataJSON()?.tool === "prepare_structure",
  { timeout: 120000 });
  await row.getByRole("button", { name: "전처리", exact: true }).click();
  const response = await posted;
  const body = await response.json();
  assert.equal(body.ok, true, `prepare failed: ${JSON.stringify(body).slice(0, 400)}`);
  const prepared = body.handle.handle;
  assert.match(prepared, /\/prepared_structure\//);
  await waitForViewer(page, value => value.sourceHandle === prepared && value.catalogReady === true, 120000);
  return { prepared, policies: response.request().postDataJSON().args };
}
/** Back to the latest pipeline view (the structure screen's own control) when a history step or result is shown. */
async function latestPipeline(page, prepared) {
  await selectTab(page, "구조 분석");
  const back = page.getByRole("button", { name: "최신 구조로 돌아가기", exact: true });
  if (await back.isVisible().catch(() => false)) await back.click();
  if (prepared) await waitForViewer(page, value => value.sourceHandle === prepared && value.catalogReady === true, 90000);
}
/** Copied from normal-flow.cjs createAndWaitForSavedReport (not exported there). */
async function createAndWaitForSavedReport(page, section, runId, createPath, buttonName, previewName) {
  const base = `/api/runs/${encodeURIComponent(runId)}`;
  const created = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `${base}/${createPath}`, { timeout: 30000 });
  const savedRead = page.waitForResponse(response => response.request().method() === "GET" &&
    new URL(response.url()).pathname === `${base}/reports/selected`, { timeout: 30000 });
  await section.getByRole("button", { name: buttonName }).click();
  const createResponse = await created;
  const status = createResponse.status();
  assert.equal(status, 201, "Report creation failed");
  const createdArtifact = await createResponse.json();
  const readResponse = await savedRead;
  assert.equal(readResponse.status(), 200, "Saved report reload failed");
  const savedArtifact = await readResponse.json();
  assert.equal(savedArtifact.handle, createdArtifact.handle, "Reloaded a different saved report");
  const preview = section.getByLabel(previewName);
  await preview.waitFor({ state: "visible", timeout: 30000 });
  await section.getByRole("link", { name: "Markdown 다운로드" }).waitFor({ state: "visible" });
  await section.getByRole("link", { name: "정확한 JSON 다운로드" }).waitFor({ state: "visible" });
  assert.equal(await preview.textContent(), savedArtifact.markdown, "Saved preview differs from reloaded report");
  return { status, artifact: savedArtifact };
}
async function historyStep(page, tool) {
  const prior = await waitForViewer(page);
  await page.getByRole("tab", { name: /^run/i }).click();
  await page.locator(".mw-step").filter({ hasText: tool }).last().click();
  await page.getByText(/선택한 단계의 구조 · model/).waitFor({ timeout: 30000 });
  await waitForViewer(page, viewer => viewer.sessionId !== prior.sessionId || viewer.generation !== prior.generation);
}
async function downloadBoth(app, page, section, run) {
  const out = {};
  for (const [suffix, name] of [["md", "Markdown 다운로드"], ["json", "정확한 JSON 다운로드"]]) {
    const downloaded = await downloadByClick(app, section.getByRole("link", { name }));
    const validated = await validateReportDownload(page, section, run, downloaded.downloaded, suffix);
    out[suffix] = { sha256: validated.sha256, bytes: validated.bytes, reportHandle: validated.reportHandle };
  }
  return out;
}

// ------------------------------------------------------------------ pocket panel (copied from pocket-flow.cjs)
const pocketPanel = page => page.locator('section[data-pocket-panel="main"]');
async function pocketObserve(page) {
  return page.evaluate(() => {
    const nodes = [...document.querySelectorAll(".mw-molstar[data-pocket-overlay]")].filter(node => node.getClientRects().length > 0);
    const node = nodes[0] ?? null;
    const main = typeof window.__protviewQaSnapshot === "function" ? window.__protviewQaSnapshot() : null;
    return { viewerNodes: nodes.length, data: node ? { ...node.dataset } : null, native: main };
  });
}
async function waitObserve(page, predicate, label, timeout = 45000) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    last = await pocketObserve(page);
    try { if (predicate(last)) return last; } catch { /* keep polling */ }
    await page.waitForTimeout(100);
  }
  throw new Error(`${label}: timed out; last=${JSON.stringify({ data: last?.data, overlay: last?.native?.pocketOverlay ?? null,
    sourceHandle: last?.native?.sourceHandle })}`);
}
const overlayApplied = (obs, set, ordinal) => obs.data?.pocketOverlay === "applied" &&
  obs.data.pocketSetHandle === set && Number(obs.data.pocketRank) === ordinal && !!obs.native?.pocketOverlay &&
  obs.native.pocketOverlay.rank === ordinal && obs.native.pocketOverlay.setHandle === set;
const overlayNone = obs => obs.data?.pocketOverlay === "none" && !obs.native?.pocketOverlay;
const pocketJobs = async (page, run) => (await readApi(page, `/runs/${run}/jobs`)).filter(job => job.protocol_id === "fpocket_detect_v1");
const preflightFor = (page, run, source) => readApi(page, `/runs/${run}/pockets/preflight?structure=${enc(source)}`);
const pocketGeometry = (page, run, handle, ordinal) => readApi(page, `/runs/${run}/pockets/geometry?handle=${enc(handle)}&rank=${ordinal}`);
const pocketSummary = (page, run, handle) => readApi(page, `/runs/${run}/pockets/result?handle=${enc(handle)}`);
async function waitPreflightText(panel, selectedChains) {
  await panel.getByLabel("포켓 입력 확인").getByText(`선택 체인 ${selectedChains.join(", ")} ·`, { exact: false })
    .waitFor({ timeout: 30000 });
}
async function detect(page, panel, run) {
  const button = panel.getByRole("button", { name: "포켓 검출 실행" });
  await button.waitFor({ timeout: 30000 });
  await waitFor(page, async () => await button.isEnabled() ? true : null, "포켓 검출 실행 enabled", 60000);
  const submitted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/jobs`, { timeout: 60000 });
  await button.click();
  const response = await submitted;
  assert.ok([200, 201, 202].includes(response.status()), `pocket job submission HTTP ${response.status()}`);
  const job = await response.json();
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
  await panel.locator("[data-pocket-total-count], [data-pocket-null-result]").first().waitFor({ timeout: 60000 });
  return { job: durable.job_id ?? job.job_id, set, approvalSeen };
}
async function descriptorCellsMatch(row, pocket, units) {
  const cells = await row.locator("td").allInnerTexts();
  assert.equal(cells.length, 2 + DESCRIPTOR_ORDER.length + 1, "unexpected column count");
  assert.equal(cells[0].trim(), String(pocket.rank));
  const seen = {};
  DESCRIPTOR_ORDER.forEach((key, i) => {
    const descriptor = pocket.descriptors[key];
    assert.ok(descriptor, `stored descriptor ${key} missing`);
    assert.equal(descriptor.unit, DESCRIPTOR_UNITS[key], `${key}: stored unit ${descriptor.unit}`);
    if (units && key in units) assert.equal(units[key], descriptor.unit, `summary units.${key} differs from the row unit`);
    const expected = UNIT_RENDER[descriptor.unit](descriptor.native_text ?? String(descriptor.value));
    const cell = cells[1 + i].replace(/\s+/g, " ").trim();
    if (key === "druggability_score") {
      assert.ok(cell.startsWith(expected), `${key}: cell "${cell}" != "${expected}"`);
      assert.ok(cell.slice(expected.length).includes("약물성 증거 아님"), "druggability cell lacks the warning");
    } else assert.equal(cell, expected, `${key}: cell "${cell}" != "${expected}"`);
    seen[key] = descriptor.unit;
  });
  assert.equal(cells[1 + DESCRIPTOR_ORDER.length].trim(), String(pocket.lining_residue_count));
  return seen;
}
async function summaryTable(panel, summary, expectedShown) {
  const shown = Number(await panel.locator("[data-pocket-displayed-count]").getAttribute("data-pocket-displayed-count"));
  const total = Number(await panel.locator("[data-pocket-total-count]").getAttribute("data-pocket-total-count"));
  assert.equal(total, summary.total_count, "displayed total_count differs from stored pocket_set");
  assert.equal(shown, expectedShown, "displayed_count differs from the top-k rule");
  const rows = panel.getByRole("region", { name: "fpocket 후보 공동 목록" }).locator("tbody tr");
  assert.equal(await rows.count(), shown);
  let units = null;
  for (let i = 0; i < shown; i++) {
    const row = rows.nth(i);
    assert.equal(Number(await row.getAttribute("data-pocket-rank")), summary.pockets[i].rank, "row order differs from the stored order");
    units = await descriptorCellsMatch(row, summary.pockets[i], summary.units);
  }
  return { displayed: shown, total, descriptorUnits: units };
}
async function catalogRows(page, run, handle) { return atomCatalog(page, run, handle); }
function focusMatches(obs, geo) {
  assert.equal(obs.data.pocketFocused, "true");
  const target = obs.native.pocketOverlay.focusedTarget;
  assert.ok(Array.isArray(target), "pocket focus did not settle on the display center");
  const center = [geo.display_center.x_A, geo.display_center.y_A, geo.display_center.z_A];
  const delta = Math.hypot(...center.map((value, i) => value - target[i]));
  assert.ok(delta <= 1e-3, "camera target differs from the stored display center");
  return { deltaA: delta };
}
async function selectAndCompare(page, panel, run, set, ordinal) {
  const geoRead = page.waitForResponse(response => response.request().method() === "GET" &&
    new URL(response.url()).pathname === `/api/runs/${run}/pockets/geometry`, { timeout: 30000 });
  await panel.getByRole("button", { name: `포켓 rank ${ordinal} 선택` }).click();
  assert.equal((await geoRead).status(), 200);
  const obs = await waitObserve(page, value => overlayApplied(value, set, ordinal), "overlay applied", 60000);
  await panel.locator('[data-pocket-overlay-status="applied"]').waitFor({ timeout: 30000 });
  const geo = await pocketGeometry(page, run, set, ordinal);
  const settled = await waitObserve(page, value => overlayApplied(value, set, ordinal) &&
    Array.isArray(value.native.pocketOverlay.focusedTarget) && value.native.cameraTransitioning === false,
  "overlay focus settled", 30000);
  const rows = await catalogRows(page, run, geo.source_handle);
  return { ordinal, spheres: compareSpheres(settled, geo, rows), focus: focusMatches(settled, geo),
    spheresVisible: obs.data.pocketSpheresVisible, sphereCount: Number(obs.data.pocketSphereCount) };
}
async function createPocketReport(page, panel, run) {
  const button = panel.getByRole("button", { name: /^(포켓 보고서 만들기|저장된 포켓 보고서 열기)$/ });
  await button.waitFor({ timeout: 30000 });
  const label = (await button.innerText()).trim();
  let created = null, status = null;
  if (label === "포켓 보고서 만들기") {
    const posted = page.waitForResponse(response => response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
    await button.click();
    const response = await posted;
    status = response.status();
    assert.equal(status, 201, `pocket report creation HTTP ${status}`);
    created = (await response.json()).handle;
  } else await button.click();
  await panel.getByRole("link", { name: "포켓 보고서 JSON 다운로드" }).waitFor({ timeout: 30000 });
  return { label, created, status };
}
async function pocketReportDownloads(app, page, panel, run, set, summary) {
  const md = await downloadByClick(app, panel.getByRole("link", { name: "포켓 보고서 Markdown 다운로드" }));
  const js = await downloadByClick(app, panel.getByRole("link", { name: "포켓 보고서 JSON 다운로드" }));
  const href = await panel.getByRole("link", { name: "포켓 보고서 JSON 다운로드" }).getAttribute("href");
  const handle = new URL(href, page.url()).searchParams.get("handle");
  const saved = await readApi(page, `/runs/${run}/reports/selected?handle=${enc(handle)}`);
  const mdBytes = fs.readFileSync(md.downloaded), jsBytes = fs.readFileSync(js.downloaded);
  assert.ok(mdBytes.equals(await readBytes(page, `/runs/${run}/reports/download?handle=${enc(handle)}&format=markdown`)));
  assert.ok(jsBytes.equals(await readBytes(page, `/runs/${run}/reports/download?handle=${enc(handle)}&format=json`)));
  const markdown = mdBytes.toString("utf8");
  const manifest = JSON.parse(jsBytes.toString("utf8"));
  assert.equal(markdown, saved.markdown);
  assert.deepEqual(manifest, saved.manifest);
  const geometries = new Map();
  for (const pocket of summary.pockets) geometries.set(pocket.rank, await pocketGeometry(page, run, set, pocket.rank));
  const validation = validateReport(manifest, markdown, summary, geometries, set);
  return { handle, markdownSha256: sha(mdBytes), jsonSha256: sha(jsBytes), claims: validation.claims,
    pockets: validation.pockets, limitations: validation.limitations };
}

// ------------------------------------------------------------------ numbering panel (copied from kinase-precedents-flow.cjs makeMap / numbering-flow.cjs)
const numbering = page => page.locator("section.mw-numbering");
const nTestId = (page, id) => numbering(page).locator(`[data-testid="${id}"]`);
const nAreaState = (page, name) => numbering(page).locator(`[data-numbering-area="${name}"]`)
  .getAttribute("data-state", { timeout: 2000 }).catch(() => null);
async function makeMap(page, run, structureHandle, spec) {
  await selectTab(page, KNOWLEDGE);
  await numbering(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => await nAreaState(page, "create") === "ready" ? true : null, "numbering create ready", 60000);
  const select = nTestId(page, "numbering-structure");
  if (await select.inputValue() !== "") await select.selectOption("");
  await select.selectOption(structureHandle);
  for (const chain of spec.chains)
    await waitFor(page, async () => await nTestId(page, `numbering-chain-${chain.chain}`).count() === 1 ? true : null,
      `chain ${chain.chain}`, 30000);
  await waitFor(page, async () => /업로드 원본|PDB ID가 없습니다|읽지 못했습니다/.test(await nTestId(page, "numbering-pdb-hint")
    .textContent()) ? true : null, "PDB ID suggestion", 30000);
  for (const chain of spec.chains) await nTestId(page, `numbering-chain-${chain.chain}`).check();
  assert.equal(await nTestId(page, "numbering-pdb-id").inputValue(), spec.pdbConfirm, "the file's PDB ID suggestion");
  assert.equal(await nTestId(page, "numbering-pdb-confirm").isChecked(), false, "the PDB ID suggestion was confirmed by itself");
  await nTestId(page, "numbering-pdb-confirm").check();
  for (const chain of spec.chains)
    await waitFor(page, async () => (await nTestId(page, `numbering-accession-${chain.chain}`).textContent())
      .includes(chain.expect) ? true : null, `SIFTS ${chain.expect} for ${chain.chain}`, 30000);
  const button = nTestId(page, "numbering-run");
  await waitFor(page, async () => await button.isEnabled() ? true : null, "실행 enabled", 30000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/commands` &&
    response.request().postDataJSON()?.tool === "map_residue_numbering", { timeout: 180000 });
  await button.click();
  const response = await posted;
  const body = await response.json();
  assert.equal(body.ok, true, `map_residue_numbering failed: ${JSON.stringify(body).slice(0, 300)}`);
  await nTestId(page, "numbering-run-result").filter({ hasText: "대응을 만들었습니다" }).waitFor({ timeout: 30000 });
  const handle = body.handle.handle;
  await numbering(page).locator(`button.mw-numbering-map[data-numbering-map="${handle}"][aria-pressed="true"]`).waitFor({ timeout: 30000 });
  await waitFor(page, async () => ["ready", "scientific_null"].includes(await nAreaState(page, "detail")) ? true : null,
    "map detail shown", 60000);
  return { handle, args: response.request().postDataJSON().args };
}
async function filterCount(page) {
  const text = clean(await nTestId(page, "numbering-filter-count").textContent());
  const found = text.match(/필터 결과 (\d+) \/ 전체 (\d+)/);
  assert.ok(found, `filter count text: ${text}`);
  return { matched: Number(found[1]), total: Number(found[2]) };
}
async function clickFilter(page, value) {
  await nTestId(page, `numbering-filter-${value}`).click();
  await waitFor(page, async () => await nTestId(page, `numbering-filter-${value}`).getAttribute("aria-pressed") === "true" ? true : null,
    `filter ${value}`, 10000);
  return filterCount(page);
}
/** Every stored row of a map (residue and status only, pages of 100 of /objects) counted per author chain and status
 * (T11: the counts the screen and the list summary show are compared with the stored rows themselves). */
async function storedMapRowCounts(page, run, handle) {
  const counts = {};
  let total = null;
  let offset = 0;
  while (total === null || offset < total) {
    const chunk = await readApi(page, `/runs/${run}/objects?handle=${enc(handle)}&columns=residue,status&offset=${offset}&limit=100`);
    total = chunk.total;
    for (const row of chunk.rows) {
      const chain = (counts[row.residue.chain_auth] ??= { mapped: 0, unmapped: 0, conflict: 0 });
      chain[row.status] = (chain[row.status] ?? 0) + 1;
    }
    if (!chunk.rows.length) break;
    offset += chunk.rows.length;
  }
  assert.equal(offset, total, "not every stored map row was read");
  return counts;
}
/** Screen chain counts and filters of the opened map versus the stored map rows and list row; KLIFS shown as reference. */
async function checkMapScreen(page, run, handle, spec) {
  const listed = (await readApi(page, `/runs/${run}/numbering_maps?offset=0&limit=100`)).rows.find(row => row.handle === handle);
  assert.ok(listed, "the new map is not listed");
  assert.deepEqual(listed.chains, spec.chains.map(chain => chain.chain), "map chains");
  assert.equal(listed.pdb_id, spec.pdbConfirm, "map PDB ID");
  const rowCounts = await storedMapRowCounts(page, run, handle);
  assert.deepEqual(Object.keys(rowCounts).sort(), spec.chains.map(chain => chain.chain).sort(), "stored row chains");
  const chains = {};
  for (const chain of spec.chains) {
    const detail = listed.chain_details.find(item => item.chain_auth === chain.chain);
    assert.ok((detail.sifts?.accessions ?? []).includes(chain.expect), `${chain.chain} SIFTS accession`);
    assert.deepEqual(rowCounts[chain.chain], { mapped: detail.counts.mapped, unmapped: detail.counts.unmapped,
      conflict: detail.counts.conflict }, `chain ${chain.chain}: the stored rows differ from the list counts`);
    const node = numbering(page).locator(`[data-chain-summary="${chain.chain}"]`);
    await node.waitFor({ timeout: 15000 });
    const shown = {};
    for (const status of ["mapped", "unmapped", "conflict"]) {
      const text = clean(await node.locator(`[data-count-status="${status}"]`).textContent());
      shown[status] = Number(text.match(/(\d+)$/)?.[1]);
    }
    assert.deepEqual(shown, { mapped: detail.counts.mapped, unmapped: detail.counts.unmapped, conflict: detail.counts.conflict },
      `chain ${chain.chain} counts on screen differ from the stored map`);
    const klifs = await node.locator("[data-klifs-applied]").evaluateAll(items => items.map(item => item.getAttribute("data-klifs-applied")));
    chains[chain.chain] = { ...shown, klifsApplied: klifs, crossCheck: await node.getAttribute("data-cross-check"),
      storedRows: rowCounts[chain.chain] };
  }
  const totals = { mapped: 0, unmapped: 0, conflict: 0 };
  for (const chain of Object.values(chains)) for (const key of Object.keys(totals)) totals[key] += chain[key];
  const filters = {};
  for (const status of ["mapped", "unmapped", "conflict"]) filters[status] = (await clickFilter(page, status)).matched;
  const all = await clickFilter(page, "all");
  assert.deepEqual(filters, totals, "filter counts differ from the stored counts");
  assert.equal(all.total, totals.mapped + totals.unmapped + totals.conflict);
  const header = clean(await nTestId(page, "numbering-rows").locator("thead").textContent());
  assert.ok(header.includes(KLIFS_REFERENCE_HEADER), "KLIFS column is not marked as a reference value");
  const note = clean(await numbering(page).locator(".mw-numbering-note").allTextContents().then(items => items.join(" ")));
  assert.ok(note.includes(NUMBERING_REFERENCE_NOTE), "the reference-value note is not shown");
  const klifsCells = await nTestId(page, "numbering-rows").locator("tbody tr").evaluateAll(items =>
    items.map(item => item.querySelectorAll("td")[5]?.textContent?.trim() ?? "").filter(text => /^KLIFS /.test(text)).length);
  return { handle, pdbId: listed.pdb_id, chains, filters, klifsCellsOnFirstPage: klifsCells };
}

// ------------------------------------------------------------------ site annotation panel and figures (copied from annotation-flow.cjs)
const sitePanel = page => page.locator('[data-testid="site-annotation-panel"]');
const sTestId = (page, id) => sitePanel(page).locator(`[data-testid="${id}"]`);
const sitePanelState = page => sitePanel(page).getAttribute("data-site-annotation-state", { timeout: 2000 }).catch(() => null);
async function waitSitePanel(page, states, timeout = 60000) {
  const wanted = Array.isArray(states) ? states : [states];
  return waitFor(page, async () => { const state = await sitePanelState(page); return wanted.includes(state) ? state : null; },
    `annotation panel ${wanted.join("|")}`, timeout);
}
async function siteObserve(page) {
  return page.evaluate(() => {
    const node = [...document.querySelectorAll(".mw-molstar[data-site-annotation]")].find(item => item.getClientRects().length > 0);
    const snap = typeof window.__protviewQaSnapshot === "function" ? window.__protviewQaSnapshot() : null;
    return { data: node ? { ...node.dataset } : null, readback: snap?.siteAnnotation ?? null,
      error: snap?.siteAnnotationError ?? null, sourceHandle: snap?.sourceHandle ?? null, pocketOverlay: snap?.pocketOverlay ?? null };
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
  throw new Error(`${label}: timed out; last=${JSON.stringify({ data: last?.data, error: last?.error, source: last?.sourceHandle })}`);
}
const siteApplied = (obs, handle, legend) => obs.data?.siteAnnotation === "applied" && obs.data.siteAnnotationHandle === handle &&
  obs.readback?.handle === handle && (legend === undefined || obs.readback.legend === legend);
const siteNone = obs => obs.data?.siteAnnotation === "none" && !obs.readback;
async function mapRadios(page) {
  if (!await sTestId(page, "site-annotation-maps").count()) return [];
  return sTestId(page, "site-annotation-maps").locator("label[data-site-map]").evaluateAll(items => items.map(item => ({
    handle: item.getAttribute("data-site-map"), checked: item.querySelector("input")?.checked ?? null })));
}
async function contactRadios(page) {
  return sTestId(page, "site-annotation-contacts").locator("label[data-site-contact]").evaluateAll(items => items.map(item => ({
    value: item.getAttribute("data-site-contact"), checked: item.querySelector("input")?.checked ?? null })));
}
async function annotationRows(page) {
  if (!await sTestId(page, "site-annotation-list").count()) return [];
  return sTestId(page, "site-annotation-list").locator("label[data-site-annotation-row]").evaluateAll(items => items.map(item => ({
    handle: item.getAttribute("data-site-annotation-row"), checked: item.querySelector("input")?.checked ?? null })));
}
async function siteTable(page) {
  const table = sTestId(page, "site-annotation-sites");
  await table.waitFor({ timeout: 30000 });
  return { handle: await table.getAttribute("data-site-annotation-handle"),
    rows: await table.locator("tr[data-site-klifs]").evaluateAll(items => items.map(item => {
      const count = type => item.querySelector(`[data-site-count="${type}"]`)?.textContent.trim() ?? null;
      return { klifs: item.getAttribute("data-site-klifs"), status: item.getAttribute("data-site-status"),
        label: [...item.querySelectorAll("td")][2]?.textContent.replace(/\s+/g, " ").trim() ?? null,
        counts: { contact: count("contact"), polar_contact: count("polar_contact"), hydrophobic_contact: count("hydrophobic_contact") },
        min: item.querySelector("[data-site-min-distance]")?.textContent.trim() ?? null };
    })) };
}
async function toggleText(page) { return clean(await sTestId(page, "site-annotation-toggle").textContent()); }
async function showAnnotation(page, handle, legend) {
  assert.equal(await toggleText(page), "주석 표시");
  await sTestId(page, "site-annotation-toggle").click();
  const obs = await waitSite(page, value => siteApplied(value, handle, legend), "annotation applied", 90000);
  await sitePanel(page).locator('[data-testid="site-annotation-viewer-status"][data-site-annotation-viewer="applied"]').waitFor({ timeout: 30000 });
  return obs;
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
const SCENE = { name: "보기 이름", save: "현재 보기 저장", saved: "저장된 보기", export: "현재 보기 PNG 내보내기",
  png: "PNG 다운로드", json: "JSON 출처 다운로드" };
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
  assert.equal(response.status(), 201, `scene save failed: HTTP ${response.status()}`);
  const body = await response.json();
  const requestBody = response.request().postDataJSON();
  await page.getByText(`보기 저장 완료 · ${name}`, { exact: true }).waitFor({ timeout: 30000 });
  const stored = await readApi(page, `/runs/${run}/viewer/scenes/selected?handle=${enc(body.handle)}`);
  return { handle: body.handle, value: stored.value, requestSchema: requestBody.schema, requestAnnotation: requestBody.annotation ?? null };
}
async function exportFigure(page, run) {
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/viewer/figures`, { timeout: 60000 });
  await page.getByRole("button", { name: SCENE.export, exact: true }).click();
  const response = await posted;
  assert.equal(response.status(), 201, `figure save failed: HTTP ${response.status()}`);
  const handle = (await response.json()).handle;
  await page.getByText(`PNG 및 출처 JSON 저장 완료 · ${handle}`, { exact: true }).waitFor({ timeout: 30000 });
  const stored = await readApi(page, `/runs/${run}/viewer/figures/selected?handle=${enc(handle)}`);
  const requestBody = response.request().postDataJSON();
  return { handle, value: stored.value, requestSchema: requestBody.schema, legendComposited: requestBody.legend_composited ?? null };
}
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
    result[format] = { file: downloaded.downloaded, sha256: sha(bytes), bytes: bytes.length };
  }
  return result;
}

// ------------------------------------------------------------------ precedent area (copied from kinase-precedents-flow.cjs)
const pPanel = page => page.locator('#mw-app-panel-knowledge [data-testid="kinase-precedents-panel"]');
const pt = (page, id) => pPanel(page).locator(`[data-testid="kinase-precedents-${id}"]`);
const pArea = (page, name) => pPanel(page).locator(`section[data-precedent-area="${name}"]`);
const pAreaState = (page, name) => pArea(page, name).getAttribute("data-state", { timeout: 2000 }).catch(() => null);
const DEFAULT_QUERY = "sort=move_id&order=asc&limit=25&offset=0";
const precedentDetailApi = (page, run, handle, query = DEFAULT_QUERY) =>
  readApi(page, `/runs/${run}/kinase_precedents/${enc(handle)}?${query}`);
/** Leave the knowledge tab and come back: its areas read their lists on tab entry (engineering notes, M27). */
async function reenterKnowledge(page) {
  await selectTab(page, "단백질 공학");
  await selectTab(page, KNOWLEDGE);
}
async function openPrecedents(page) {
  await selectTab(page, KNOWLEDGE);
  await pPanel(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => ["ready", "unavailable", "failed"].includes(await pAreaState(page, "snapshot")) &&
    ["ready", "empty", "failed"].includes(await pAreaState(page, "results")) ? true : null, "precedent area read", 60000);
}
async function pPanelText(page) {
  return pPanel(page).evaluate(node => {
    let text = node.innerText;
    for (const item of node.querySelectorAll('[data-testid="kinase-precedents-kbase-fields"] dl')) {
      const entries = item.innerText;
      if (entries) text = text.split(entries).join("\n");
    }
    return text;
  });
}
async function pProductText(page) {
  return pPanel(page).evaluate(node => {
    let text = node.innerText;
    for (const item of node.querySelectorAll('[data-testid="kinase-precedents-record-detail"]')) text = text.split(item.innerText).join("\n");
    return text;
  });
}
const pResultRadio = (page, handle) => pPanel(page).locator(`input[data-testid="kinase-precedents-result"][data-precedent-result="${handle}"]`);
async function detailRead(page, run, action) {
  const prefix = `/api/runs/${run}/kinase_precedents/`;
  const waiting = page.waitForResponse(response => response.request().method() === "GET" &&
    new URL(response.url()).pathname.startsWith(prefix), { timeout: 60000 });
  await action();
  const response = await waiting;
  assert.equal(response.status(), 200, `detail read HTTP ${response.status()}`);
  const body = await response.json();
  SEEN.push(body);
  const query = new URL(response.url()).search.slice(1);
  await waitFor(page, async () => ["ready", "empty"].includes(await pAreaState(page, "detail")) ? true : null, "detail settled", 60000);
  const again = await precedentDetailApi(page, run, body.handle, query);
  assert.deepEqual(again, body, "the same GET query gives another answer");
  return { body, query };
}
async function openPrecedentResult(page, run, handle) {
  await openPrecedents(page);
  const radio = pResultRadio(page, handle);
  await radio.waitFor({ timeout: 30000 });
  if (await radio.isChecked()) {
    const others = await pPanel(page).locator('input[data-testid="kinase-precedents-result"]').evaluateAll((items, own) =>
      items.map(item => item.getAttribute("data-precedent-result")).filter(value => value !== own), handle);
    if (!others.length) return { body: await precedentDetailApi(page, run, handle), query: DEFAULT_QUERY };
    await detailRead(page, run, () => pResultRadio(page, others[0]).check());
  }
  const read = await detailRead(page, run, () => radio.check());
  assert.equal(read.body.handle, handle);
  return read;
}
const badgeOf = activeSet => activeSet.set_hash === null ? "사용 중 스냅샷 없음" : activeSet.same ? null : "이전 스냅샷 기준";
const includedCount = counts => counts.moves + (counts.moves_flagged ?? 0);
const TARGET_PHRASE = { none_in_included_files: "포함한 파일에 이 표적의 전례 기록 없음",
  not_in_kbase_references: "kbase에 이 표적 참조가 없음(전례 없음과 다름)" };
const targetPhrase = target => target.status === "precedents_found" ? `전례 ${includedCount(target.counts)}건` : TARGET_PHRASE[target.status];
function bibliographyText(record, books) {
  const book = books[record.source.pmid] ?? null;
  return `PMID ${record.source.pmid} · ` + (book === null ? `${NULL} (서지 없음)`
    : [book.title, book.journal, book.year].map(value => value ?? NULL).join(" · "));
}
/** The opened result on screen versus the detail answer (copied from kinase-precedents-flow.cjs verifyDetail). */
async function verifyPrecedentDetail(page, body, expect) {
  const detail = pPanel(page).locator(`[data-testid="kinase-precedents-detail"][data-precedent-detail="${body.handle}"]`);
  await detail.waitFor({ timeout: 60000 });
  const shown = await detail.evaluate(node => {
    const text = el => el ? el.textContent.replace(/\s+/g, " ").trim() : null;
    const q = sel => node.querySelector(sel);
    const qa = sel => [...node.querySelectorAll(sel)];
    const target = q('[data-testid="kinase-precedents-target"]');
    return {
      nullResult: node.getAttribute("data-null-result"), includeFlagged: node.getAttribute("data-include-flagged"),
      marks: qa('[data-testid="kinase-precedents-detail-set"] [data-testid="kinase-precedents-snapshot-mark"]').map(text),
      counts: Object.fromEntries(qa('[data-testid="kinase-precedents-counts"] [data-precedent-count]').map(el =>
        [el.getAttribute("data-precedent-count"), text(el.querySelector("dd"))])),
      chains: qa('[data-testid="kinase-precedents-chain-table"] tbody tr').map(tr => ({ chain: tr.getAttribute("data-chain"),
        status: tr.getAttribute("data-chain-status"), cells: [...tr.querySelectorAll("td")].map(text) })),
      chainUp5: text(q('[data-testid="kinase-precedents-chain-up5"]')),
      tabs: qa('[data-testid="kinase-precedents-target-tab"]').map(b => ({ accession: b.getAttribute("data-accession"),
        status: b.getAttribute("data-target-status"), selected: b.getAttribute("aria-selected") })),
      target: target && { accession: target.getAttribute("data-accession"), status: target.getAttribute("data-target-status"),
        statusText: text(target.querySelector('[data-testid="kinase-precedents-target-status"]')),
        up2: text(target.querySelector('[data-testid="kinase-precedents-up2"]')),
        refs: [...target.querySelectorAll('[data-testid="kinase-precedents-references"] tbody tr')].map(tr => tr.getAttribute("data-ref-id")),
        counts: text(target.querySelector('[data-testid="kinase-precedents-target-counts"] > p')),
        variants: text(target.querySelector('[data-testid="kinase-precedents-variants"]')),
        up3: text(target.querySelector('[data-testid="kinase-precedents-up3"]')) },
      pageText: text(q('[data-testid="kinase-precedents-page-text"]')),
      records: qa('[data-testid="kinase-precedents-record-row"]').map(tr => ({ moveId: tr.getAttribute("data-move-id"),
        file: tr.getAttribute("data-file"), cells: [...tr.querySelectorAll(":scope > td")].map(text) })),
      limitations: qa('[data-testid="kinase-precedents-limitations"] [data-limitation]').map(text),
    };
  });
  assert.equal(shown.nullResult, String(body.null_result));
  assert.equal(shown.includeFlagged, String(body.include_flagged));
  const badge = badgeOf(body.active_set);
  assert.deepEqual(shown.marks, badge ? [badge] : [], "detail snapshot mark");
  assert.equal(badge, null, "the result is not of the active set");
  assert.deepEqual(shown.counts, kinase.countTexts(body.counts), "count rows");
  assert.deepEqual(shown.chains.map(row => row.chain), body.chains.map(chain => chain.chain_auth), "chain order");
  body.chains.forEach((chain, i) => {
    assert.equal(shown.chains[i].status, chain.status);
    assert.deepEqual(shown.chains[i].cells.slice(0, 6), kinase.chainCells(chain), `chain ${chain.chain_auth} cells`);
  });
  const unresolved = body.set_summary.unresolved_target_records.moves + body.set_summary.unresolved_target_records.moves_flagged;
  assert.equal(shown.chainUp5, kinase.UP5(unresolved), "UP5 under the chain table");
  assert.deepEqual(shown.tabs.map(tab => [tab.accession, tab.status]), body.targets_overview.map(item => [item.accession, item.status]));
  const target = body.targets_overview.find(item => item.accession === body.page.target);
  assert.ok(target, "no target page opened");
  assert.equal(shown.target.accession, target.accession);
  assert.equal(shown.target.statusText, targetPhrase(target), "target status phrase");
  assert.equal(shown.target.up2, target.excluded_flagged === null ? null : kinase.UP2(target.excluded_flagged), "UP2");
  assert.deepEqual(shown.target.refs, target.references.map(ref => ref.ref_id));
  const flagged = target.counts.moves_flagged === null ? `${NULL} (포함하지 않음)` : `${target.counts.moves_flagged}건`;
  assert.equal(shown.target.counts, `moves 파일 ${target.counts.moves}건 · moves_flagged 파일 ${flagged}`);
  const variants = target.counts.variants.map(item => `${item.variant} ${item.count}건`).join(" · ") || "빈 목록 ([])";
  assert.equal(shown.target.variants, `변이 표기(variant)별 ${variants}`);
  assert.equal(shown.target.up3, kinase.UP3);
  assert.equal(shown.pageText, kinase.pageText(body.page, body.records.length), "page text");
  assert.deepEqual(shown.records.map(row => row.moveId), body.records.map(item => item.record.move_id), "record order");
  body.records.forEach((item, i) => {
    assert.equal(shown.records[i].file, item.file);
    assert.equal(shown.records[i].cells[2], clean(item.record.target.variant));
    assert.equal(shown.records[i].cells[5], clean(bibliographyText(item.record, body.bibliography)), `${item.record.move_id} bibliography`);
  });
  assert.deepEqual(shown.limitations, body.limitations);
  assert.deepEqual(body.limitations, kinase.LIMITATIONS, "KP1–KP6 verbatim and in order");
  const bare = kinase.bareZeroOrNone(await pProductText(page));
  assert.deepEqual(bare, [], "a bare 0 or 없음 in the area");
  const found = kinase.forbiddenIn(await pPanelText(page), [...SEEN, body]);
  assert.deepEqual(found.length, 0, "forbidden wording in the precedent area");
  if (expect) checkPrecedentExpect(body, expect);
  return { flaggedText: shown.counts.records_moves_flagged, bareZeroOrNone: bare.length };
}
/** The plan's independent expectation against the stored answer (copied from kinase-precedents-flow.cjs checkExpect). */
function checkPrecedentExpect(body, expect) {
  assert.equal(body.null_result, expect.nullResult, "null_result");
  assert.deepEqual(body.chains.map(chain => chain.chain_auth).sort(), Object.keys(expect.chains).sort(), "chains");
  for (const [name, [status, reason, accession]] of Object.entries(expect.chains)) {
    const chain = body.chains.find(item => item.chain_auth === name);
    assert.deepEqual([chain.status, chain.reason, chain.accession], [status, reason, accession], `chain ${name}`);
  }
  assert.deepEqual(body.targets_overview.map(item => item.accession), Object.keys(expect.targets).sort(), "targets");
  for (const [accession, want] of Object.entries(expect.targets)) {
    const got = body.targets_overview.find(item => item.accession === accession);
    assert.deepEqual([got.status, got.counts.moves, got.counts.moves_flagged, got.excluded_flagged, got.references.length, got.chains],
      [want.status, want.moves, want.movesFlagged, want.excluded, want.references, want.chains], `target ${accession}`);
    assert.deepEqual(Object.fromEntries(got.counts.variants.map(item => [item.variant, item.count])), want.variants, `${accession} variants`);
  }
}
function precedentObserved(body) {
  return { nullResult: body.null_result, includeFlagged: body.include_flagged,
    chains: Object.fromEntries(body.chains.map(chain => [chain.chain_auth, [chain.status, chain.reason, chain.accession]])),
    targets: Object.fromEntries(body.targets_overview.map(target => [target.accession, { status: target.status,
      moves: target.counts.moves, movesFlagged: target.counts.moves_flagged, excluded: target.excluded_flagged,
      references: target.references.length,
      variants: Object.fromEntries(target.counts.variants.map(item => [item.variant, item.count])) }])) };
}
async function setPrecedentRequest(page, mapHandle, chains, includeFlagged) {
  const select = pt(page, "numbering-map");
  if (await select.inputValue() !== mapHandle) await select.selectOption(mapHandle);
  await pt(page, "chains").waitFor({ timeout: 30000 });
  const names = await pPanel(page).locator("[data-precedent-chain]").evaluateAll(items => items.map(item => item.getAttribute("data-precedent-chain")));
  for (const name of names) {
    const box = pt(page, `chain-${name}`);
    const want = chains === null || chains.includes(name);
    if (await box.isChecked() !== want) { if (want) await box.check(); else await box.uncheck(); }
  }
  const toggle = pt(page, "include-flagged");
  if (await toggle.isChecked() !== includeFlagged) { if (includeFlagged) await toggle.check(); else await toggle.uncheck(); }
  assert.equal(await pt(page, "flagged-note").count(), includeFlagged ? 1 : 0, "moves_flagged note");
  return names;
}
async function linkPrecedents(page, run, mapHandle, spec) {
  await openPrecedents(page);
  await pt(page, "request-form").waitFor({ timeout: 30000 });
  await setPrecedentRequest(page, mapHandle, spec.chains, spec.includeFlagged);
  const button = pt(page, "link");
  await waitFor(page, async () => await button.isEnabled() ? true : null, "전례 연결 enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === "link_kinase_precedents",
  { timeout: 120000 });
  const read = await detailRead(page, run, () => button.click());
  const response = await posted;
  const body = await response.json();
  assert.equal(body.ok, true, `link failed: HTTP ${response.status()}`);
  const made = body.handle.handle;
  await pPanel(page).locator(`[data-testid="kinase-precedents-link-done"][data-precedent-new-result="${made}"]`).waitFor({ timeout: 30000 });
  assert.deepEqual(response.request().postDataJSON().args, { numbering_map: mapHandle, chains: spec.chains,
    include_flagged: spec.includeFlagged }, "request arguments");
  assert.equal(read.body.handle, made, "the opened result is not the new one");
  const verified = await verifyPrecedentDetail(page, read.body, spec.expect);
  return { handle: made, body: read.body, verified };
}
async function allPrecedentRecords(page, run, handle, target) {
  const records = [];
  const bodies = [];
  for (let offset = 0; ; offset += 100) {
    const body = await precedentDetailApi(page, run, handle, `target=${enc(target)}&sort=move_id&order=asc&limit=100&offset=${offset}`);
    records.push(...body.records);
    bodies.push(body);
    if (body.page.filtered_total === null || offset + 100 >= body.page.filtered_total) return { records, bodies };
  }
}

// ------------------------------------------------------------------ reaction area (copied from reaction-knowledge-flow.cjs)
const rPanel = page => page.locator('#mw-app-panel-knowledge [data-testid="reaction-panel"]');
const rt = (page, id) => rPanel(page).locator(`[data-testid="${id}"]`);
const rArea = (page, name) => rPanel(page).locator(`section[data-reaction-area="${name}"]`);
const rAreaState = (page, name) => rArea(page, name).getAttribute("data-state", { timeout: 2000 }).catch(() => null);
const rPanelState = page => rPanel(page).getAttribute("data-reaction-state", { timeout: 2000 }).catch(() => null);
const DEFAULT_PAGING = { chain_offset: 0, chain_limit: 10, row_offset: 0, row_limit: 50, feature_offset: 0, feature_limit: 50 };
const pagingQuery = paging => ["chain_offset", "chain_limit", "row_offset", "row_limit", "feature_offset", "feature_limit"]
  .map(key => `${key}=${paging[key]}`).join("&");
const reactionDetailApi = (page, run, handle, paging = DEFAULT_PAGING) =>
  readApi(page, `/runs/${run}/reaction_knowledge/${enc(handle)}?${pagingQuery(paging)}`);
async function openReaction(page) {
  await selectTab(page, KNOWLEDGE);
  await rPanel(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => ["ready", "unavailable", "error"].includes(await rAreaState(page, "snapshot")) &&
    await rAreaState(page, "results") === "ready" ? true : null, "reaction area read", 60000);
}
const rPanelText = page => rPanel(page).evaluate(node => node.innerText);
const rowKey = row => `${row.mcsa_id}/${row.residue_index}`;
const rowState = row => row.reason === null ? row.status : `${row.status}:${row.reason}`;
/** The detail area of one opened reaction result versus the stored detail (copied from reaction-knowledge-flow.cjs
 * verifyDetail; the role and reference text is compared verbatim and kept out of the returned record). */
async function verifyReactionDetail(page, run, handle, expect) {
  const api = await reactionDetailApi(page, run, handle);
  const detail = rPanel(page).locator(`[data-testid="reaction-detail"][data-reaction-detail="${handle}"]`);
  await detail.waitFor({ timeout: 60000 });
  await waitFor(page, async () => await rAreaState(page, "detail") === "ready" ? true : null, "detail ready", 60000);
  const wantState = api.null_result ? "scientific_null" : "ready";
  await waitFor(page, async () => await rPanelState(page) === wantState ? true : null, `panel ${wantState}`, 30000);
  assert.equal(await detail.getAttribute("data-null-result"), String(api.null_result));
  assert.equal(api.null_result, expect.nullResult, "null_result");
  const badge = api.active_set.set_hash === null ? "사용 중 스냅샷 없음" : api.active_set.same ? null : "이전 스냅샷 기준";
  assert.equal(badge, null, "the result is not of the active set");
  assert.deepEqual((await detail.locator('[data-testid="reaction-snapshot-mark"]').allInnerTexts()).map(clean), []);
  const counts = api.counts;
  const countText = async key => clean(await rt(page, "reaction-counts").locator(`[data-reaction-count="${key}"] dd`).textContent());
  assert.equal(await countText("chains"), `${counts.chains}개`);
  assert.equal(await countText("covered_chains"), `${counts.covered_chains}개`);
  const rowsText = await countText("mcsa_rows");
  assert.equal(rowsText, `대응됨 ${counts.mcsa_rows.matched} · 대응 없음 ${counts.mcsa_rows.unmatched} · 충돌 ${counts.mcsa_rows.conflict}`);
  assert.deepEqual(await detail.locator("[data-reaction-chain-view]").evaluateAll(items => items.map(item => item.getAttribute("data-reaction-chain-view"))),
    api.chains.map(chain => chain.chain_auth), "chain order");
  const summary = {};
  for (const chain of api.chains) {
    const node = detail.locator(`[data-reaction-chain-view="${chain.chain_auth}"]`);
    const mcsa = chain.mcsa;
    assert.equal(await node.getAttribute("data-coverage"), mcsa.coverage, `${chain.chain_auth} coverage attr`);
    assert.equal(await node.getAttribute("data-mcsa-status"), mcsa.status);
    assert.equal(await node.getAttribute("data-uniprot-status"), chain.uniprot.status);
    assert.equal(await node.getAttribute("data-reactions-status"), chain.reactions.status);
    const uk4 = (await node.locator('[data-testid="reaction-chain-uk4"]').allInnerTexts()).map(clean);
    assert.deepEqual(uk4, mcsa.coverage === "covered" ? [] : [UK.UK4], `${chain.chain_auth} UK4`);
    const countsLine = clean(await node.locator('[data-testid="reaction-mcsa-counts"]').textContent());
    if (mcsa.counts === null) assert.ok(countsLine.includes(NULL) && noDigit(countsLine), `${chain.chain_auth} counts line`);
    else assert.ok(countsLine.endsWith(`대응됨 ${mcsa.counts.matched} · 대응 없음 ${mcsa.counts.unmatched} · 충돌 ${mcsa.counts.conflict}`));
    if (mcsa.rows === null) {
      const none = clean(await node.locator('[data-testid="reaction-mcsa-rows-none"]').textContent());
      assert.ok(none.includes(NULL) && noDigit(none.replace(/^M-CSA/, "")), `${chain.chain_auth} rows-none line`);
      assert.equal(await node.locator('[data-testid="reaction-mcsa-rows"]').count(), 0);
    } else {
      assert.ok(clean(await node.locator('[data-testid="reaction-mcsa-rows"] thead').textContent()).includes(REFERENCE_COLUMN));
      const shownRows = await node.locator('[data-testid="reaction-mcsa-rows"] tbody tr').evaluateAll(items => items.map(item => {
        const cells = [...item.querySelectorAll(":scope > td")];
        const dd = [...cells[6].querySelectorAll("dl > dd")];
        return { status: item.getAttribute("data-mcsa-row-status"), id: Number(item.getAttribute("data-mcsa-id")),
          index: Number(item.getAttribute("data-residue-index")), statusText: cells[0].textContent.trim(),
          residue: cells[2].textContent.trim(), resname: cells[3].textContent.trim(),
          listed: cells[4].textContent.replace(/\s+/g, " ").trim(), summary: dd[0]?.textContent ?? null,
          reason: cells[7].textContent.trim() };
      }));
      assert.equal(shownRows.length, mcsa.rows.length, `${chain.chain_auth} row count`);
      mcsa.rows.forEach((row, i) => {
        const ui = shownRows[i];
        const where = `${chain.chain_auth} ${rowKey(row)}`;
        assert.equal(ui.status, row.status, `${where} status`);
        assert.equal(ui.id, row.mcsa_id);
        assert.equal(ui.index, row.residue_index);
        assert.equal(ui.statusText, `${ROW_LABEL[row.status]} (${row.status})`, where);
        assert.equal(ui.residue, reaction.identityText(row.residue), `${where} 7-field identity`);
        assert.equal(ui.resname, row.structure_resname ?? NULL, `${where} structure name`);
        const listed = `${row.listed.pdb_id} · ${row.listed.chain_name} · resid ${row.listed.resid ?? NULL} · auth_resid ` +
          `${row.listed.auth_resid ?? NULL} · ${row.listed.code}`;
        assert.ok(ui.listed.startsWith(listed), `${where} listed`);
        assert.equal(ui.summary, row.reference.roles_summary === "" ? '""' : row.reference.roles_summary, `${where} roles_summary verbatim`);
        if (row.reason === null) assert.equal(ui.reason, NULL);
        else assert.ok(ui.reason.endsWith(`(${row.reason})`), `${where} reason`);
      });
    }
    if (chain.uniprot.features?.length) {
      const features = await node.locator('[data-testid="reaction-features"] tbody > tr').count();
      assert.equal(features, chain.uniprot.features.length, `${chain.chain_auth} UniProt sites shown`);
    }
    reaction.checkChainExpectation(chain, expect.chains[chain.chain_auth], api);
    summary[chain.chain_auth] = { coverage: mcsa.coverage, counts: mcsa.counts, uniprot: [chain.uniprot.status, chain.uniprot.reason],
      reactions: chain.reactions.status, features: chain.uniprot.features?.length ?? null,
      rows: mcsa.rows === null ? null : Object.fromEntries(mcsa.rows.map(row => [rowKey(row), rowState(row)])) };
  }
  const limits = await detail.locator('[data-testid="reaction-limitations"] [data-limitation]').allInnerTexts();
  assert.deepEqual(limits, api.limitations);
  assert.deepEqual(api.limitations, RK.slice(0, 5), "RK1–RK5 verbatim and in order");
  const found = reaction.forbiddenIn(await rPanelText(page), [...SEEN, api]);
  assert.equal(found.length, 0, "forbidden wording in the reaction area");
  return { api, summary };
}
async function reactionChooseStructure(page, handle, chains) {
  await rt(page, "reaction-request-form").waitFor({ timeout: 30000 });
  const select = rt(page, "reaction-structure");
  if (await select.inputValue() !== "") await select.selectOption("");
  await select.selectOption(handle);
  for (const chain of chains)
    await waitFor(page, async () => await rt(page, `reaction-chain-${chain}`).count() === 1 ? true : null, `chain row ${chain}`, 60000);
  await waitFor(page, async () => {
    const hint = clean(await rt(page, "reaction-pdb-hint").textContent());
    return hint && !hint.includes("읽는 중") ? hint : null;
  }, "PDB ID suggestion read", 30000);
}
async function linkReaction(page, run, handle, spec) {
  await openReaction(page);
  await reactionChooseStructure(page, handle, spec.chains.map(chain => chain.chain));
  await waitFor(page, async () => await rt(page, "reaction-pdb-id").inputValue() === spec.pdbId.suggested ? true : null,
    `PDB ID ${spec.pdbId.suggested} suggested`, 30000);
  assert.equal(await rt(page, "reaction-pdb-confirm").isChecked(), false, "a suggested PDB ID was confirmed by itself");
  await rt(page, "reaction-pdb-confirm").check();
  const lookup = await readApi(page, `/reaction_reference/pdb/${spec.pdbId.suggested}`);
  await waitFor(page, async () => await rt(page, "reaction-pdb-lookup").getAttribute("data-entries") === String(lookup.entries.length)
    ? true : null, "PDB lookup shown", 30000);
  assert.deepEqual(lookup.entries.map(entry => entry.mcsa_id), spec.lookupEntries, "M-CSA entries naming the PDB ID");
  const entered = [];
  for (const chain of spec.chains) {
    const box = rt(page, `reaction-chain-${chain.chain}`);
    assert.equal(await box.isChecked(), false, `chain ${chain.chain} ticked by itself`);
    await box.check();
    const input = rt(page, `reaction-accession-${chain.chain}`);
    if (chain.accession === null) {
      if (await input.inputValue() !== "") await input.fill("");
    } else {
      assert.equal(await input.inputValue(), "", "a suggestion was applied without a click");
      const button = rt(page, `reaction-use-accession-${chain.chain}-${chain.accession.suggestion}`);
      await button.waitFor({ timeout: 30000 });
      await button.click();
    }
    const value = chain.accession === null ? "" : chain.accession.suggestion;
    await waitFor(page, async () => await input.inputValue() === value ? true : null, `accession ${chain.chain}`, 15000);
    entered.push({ chain: chain.chain, accession: value || null });
  }
  assert.equal(await rt(page, "reaction-numbering-map").inputValue(), "", "a numbering map was chosen by itself");
  const button = rt(page, "reaction-link");
  await waitFor(page, async () => await button.isEnabled() ? true : null, "연결하기 enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === "link_reaction_knowledge",
  { timeout: 180000 });
  await button.click();
  const response = await posted;
  const body = await response.json();
  assert.equal(body.ok, true, `link failed: HTTP ${response.status()}`);
  const made = body.handle.handle;
  await rPanel(page).locator(`[data-testid="reaction-link-done"][data-reaction-new-result="${made}"]`).waitFor({ timeout: 30000 });
  assert.deepEqual(response.request().postDataJSON().args, { structure: handle, pdb_id: spec.pdbId.suggested.toUpperCase(),
    chains: entered.map(item => ({ chain_auth: item.chain, uniprot_accession: item.accession })), numbering_map: null },
  "request arguments");
  const verified = await verifyReactionDetail(page, run, made, spec.expect);
  return { handle: made, verified };
}

// ------------------------------------------------------------------ the flow
async function modeFixture(session, input, rec, evidence) {
  const { page, app, artifacts } = session;
  const plan = input.planData;
  const h = evidence.handles;
  let run = null;

  // ---- A1: upload 1M17, load model 0, prepare with the screen defaults; residues and atoms vs the input file
  await rec.part("A1", [], async () => {
    run = await rec.step("A1-01", "Click 새 run", () => newRun(page), async id => { assert.match(id, /^run_/); return { run: id }; });
    evidence.run = run;
    const loaded = await rec.step("A1-02", "Choose public_1m17.cif, click 구조 불러오기 (model 0)", () => uploadLoad(page, plan.inputs.m17),
      async value => value);
    h.m17 = { loaded: loaded.handle };
    evidence.inputs.push(loaded.file);
    const prepared = await rec.step("A1-03", "Click 전처리 with the displayed default policies; residues and atoms of the prepared " +
      "structure equal the counts of the input file after the same policy", () => prepareManual(page), async value => {
      assert.deepEqual({ altloc: value.policies.altloc, waters: value.policies.waters, hydrogens: value.policies.hydrogens },
        plan.a1.policy, "the screen defaults differ from the plan's policy");
      assert.equal(value.policies.structure, h.m17.loaded);
      const residues = (await readApi(page, `/runs/${run}/structures/residues?handle=${enc(value.prepared)}`)).residues.length;
      const atoms = (await readApi(page, `/runs/${run}/structures/atoms?handle=${enc(value.prepared)}&offset=0&limit=1`)).total;
      const meta = await readApi(page, `/runs/${run}/objects/meta?handle=${enc(value.prepared)}`);
      const removed = { waters: meta.summary.waters, hydrogens: meta.summary.hydrogens, altlocs: meta.summary.altlocs };
      assert.equal(residues, plan.a1.residues, "prepared residues");
      assert.equal(atoms, plan.a1.atoms, "prepared atoms");
      assert.deepEqual(removed, plan.a1.removed, "removed by the policy");
      evidence.observed.A1 = { residues, atoms, removed, prepared: value.prepared };
      return evidence.observed.A1;
    });
    h.m17.prepared = prepared.prepared;
  });

  // ---- A2: AQ4 by its 7 fields → geometric contacts; every row = one input atom pair; inspection report
  await rec.part("A2", ["A1"], async () => {
    const select = page.getByRole("combobox", { name: /^리간드/ });
    const contacts = await rec.step("A2-01", "Choose the AQ4 instance in 리간드, cutoff 4, click 기하 접촉 계산", async () => {
      await latestPipeline(page, h.m17.prepared);
      const shown = await select.locator("option").evaluateAll(items => items.map(item => ({ value: item.value, text: item.textContent.trim() })));
      const ligands = shown.filter(item => item.value !== "");
      assert.equal(ligands.length, 1, "1M17 offers one ligand instance");
      assert.ok(ligands[0].text.includes("AQ4"), "the instance is AQ4");
      await select.selectOption(ligands[0].value);
      await page.getByLabel("cutoff").fill(String(plan.contacts.cutoff_A));
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === "compute_interactions",
      { timeout: 90000 });
      await page.getByRole("button", { name: "기하 접촉 계산", exact: true }).click();
      const response = await posted;
      const body = await response.json();
      return { body, request: response.request().postDataJSON().args };
    }, async value => {
      assert.equal(value.body.ok, true, JSON.stringify(value.body).slice(0, 300));
      assert.ok(sameResidue(value.request.ligand, plan.ligand), "the ligand sent is not the 7-field AQ4 instance");
      assert.equal(value.request.structure, h.m17.prepared);
      assert.equal(value.request.cutoff_A, plan.contacts.cutoff_A);
      assert.deepEqual([...value.request.types].sort(), [...plan.contacts.types].sort());
      await page.getByText(/기하 접촉 · \d+건/).waitFor({ timeout: 60000 });
      return { handle: value.body.handle.handle };
    });
    h.contacts = contacts.body.handle.handle;
    const rows = await rec.step("A2-02", "Read the stored contact rows: each equals one independent input atom pair (7-field residue, atom " +
      "names, kind, distance Å); the first page on screen shows the same rows", () => storedRows(page, run, h.contacts), async stored => {
      const expected = new Map();
      for (const pair of plan.contacts.pairs) expected.set(`${residueKey(pair.residue)}|${pair.protein_atom}|${pair.ligand_atom}`, pair);
      let unmatched = 0;
      const seen = new Set();
      for (const row of stored) {
        const key = `${residueKey(row.residue)}|${row.protein_atom}|${row.ligand_atom}`;
        const pair = expected.get(key);
        if (!pair || seen.has(key)) { unmatched++; continue; }
        seen.add(key);
        assert.equal(row.type, pair.type, `${key} kind`);
        assert.ok(Math.abs(row.distance_A - pair.distance_A) <= 1e-9, `${key} distance`);
        assert.ok(sameResidue(row.ligand, plan.ligand), "a row names another ligand instance");
        assert.equal(row.unit, "angstrom");
      }
      assert.equal(unmatched, 0, "stored rows without an input atom pair");
      assert.ok(stored.length >= 1, "no contact row");
      assert.equal(stored.length, plan.contacts.pairs.length, "stored rows vs input pairs");
      const label = clean(await page.getByText(/기하 접촉 · \d+건/).innerText());
      assert.equal(label.match(/(\d+)건/)?.[1], String(stored.length), "the screen row total");
      const table = page.getByRole("region", { name: "기하 접촉 측정 행", exact: true });
      const cells = await table.locator("tbody tr").evaluateAll(items => items.map(item => [...item.querySelectorAll("td")]
        .map(cell => cell.textContent.replace(/\s+/g, " ").trim())));
      assert.equal(cells.length, Math.min(50, stored.length));
      cells.forEach((row, i) => {
        assert.ok(row[0].includes(`${stored[i].protein_atom}–${stored[i].ligand_atom}`), `row ${i} atoms`);
        assert.equal(row[2], `${stored[i].distance_A.toFixed(2)} Å`, `row ${i} distance`);
      });
      const byType = { contact: 0, polar_contact: 0, hydrophobic_contact: 0 };
      for (const row of stored) byType[row.type]++;
      evidence.observed.A2 = { rows: stored.length, byType, unmatchedRows: unmatched,
        residues: new Set(stored.map(row => residueKey(row.residue))).size, screenRows: cells.length };
      return evidence.observed.A2;
    });
    await rec.step("A2-03", "Click the contact history step, 보고서 만들기, Markdown 다운로드, 정확한 JSON 다운로드: bytes equal the saved " +
      "report; each claim equals the stored row and the input pair; wording lines negate", async () => {
      await historyStep(page, "compute_interactions");
      const section = page.getByText("선택한 측정의 로컬 보고서").locator("..");
      const made = await createAndWaitForSavedReport(page, section, run, "reports", "보고서 만들기", "저장된 보고서 미리보기");
      noteReport(evidence, "A2", "inspection", made.status, made.artifact.handle);
      const downloads = await downloadBoth(app, page, section, run);
      const tab = await keepTabText(page, evidence, artifacts, "structure@A2", "structure");
      return { artifact: made.artifact, downloads, tab, tabText: await page.locator("#mw-app-panel-structure").innerText() };
    }, async value => {
      const manifest = value.artifact.manifest;
      const claims = manifest.claims;
      const one = id => { const found = claims.filter(claim => claim.statement_id === id); assert.equal(found.length, 1, id); return found[0]; };
      const summary = plan.contacts.summary;
      assert.equal(one("contact_count").exact_value, summary.rows);
      assert.equal(one("contacting_residue_count").exact_value, summary.residues);
      assert.ok(Math.abs(one("minimum_distance").exact_value - summary.minimumDistance) <= 1e-9, "minimum distance");
      for (const claim of claims.filter(item => item.statement_id === "type_count"))
        assert.equal(claim.exact_value, summary.byType[claim.contact_type], `type_count ${claim.contact_type}`);
      const distanceClaims = claims.filter(item => item.statement_id === "contact_distance");
      assert.equal(distanceClaims.length, rows.length, "one distance claim per stored row");
      const pairs = new Map(plan.contacts.pairs.map(pair => [`${residueKey(pair.residue)}|${pair.protein_atom}|${pair.ligand_atom}`, pair]));
      for (const claim of distanceClaims) {
        const row = rows[claim.row_index];
        assert.ok(row, `claim row ${claim.row_index}`);
        assert.ok(sameResidue(claim.subject.residue, row.residue), "claim residue");
        assert.equal(claim.subject.protein_atom, row.protein_atom);
        assert.equal(claim.subject.ligand_atom, row.ligand_atom);
        assert.equal(claim.exact_value, row.distance_A, "claim value vs stored row");
        const pair = pairs.get(`${residueKey(row.residue)}|${row.protein_atom}|${row.ligand_atom}`);
        assert.ok(Math.abs(claim.exact_value - pair.distance_A) <= 1e-9, "claim value vs input pair");
        assert.equal(claim.rendered_value, halfUp(claim.exact_value, 2), "claim rendering (2 places, half up)");
        assert.equal(claim.unit, "angstrom");
      }
      const wording = { screen: hbondLines(value.tabText), report: hbondLines(value.artifact.markdown) };
      return { report: value.artifact.handle, claims: claims.length, distanceClaims: distanceClaims.length, downloads: value.downloads,
        wording, tab: value.tab };
    });
  });

  // ---- A3: interface SASA of the same selection; screen = stored object; method report claims = stored fields
  await rec.part("A3", ["A1"], async () => {
    const made = await rec.step("A3-01", "Back to the latest structure, choose the AQ4 instance, click 선택한 리간드 SASA 계산", async () => {
      await latestPipeline(page, h.m17.prepared);
      const select = page.getByRole("combobox", { name: /^리간드/ });
      await select.selectOption({ index: 1 });
      await waitFor(page, async () => await page.getByRole("button", { name: "선택한 리간드 SASA 계산" }).first().isEnabled() ? true : null,
        "SASA control enabled", 30000);
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === "compute_interface_sasa",
      { timeout: 120000 });
      await page.getByRole("button", { name: "선택한 리간드 SASA 계산" }).first().click();
      const response = await posted;
      const body = await response.json();
      await page.getByRole("region", { name: "단백질 잔기 SASA 측정 행" }).waitFor({ timeout: 60000 });
      return { body, request: response.request().postDataJSON().args };
    }, async value => {
      assert.equal(value.body.ok, true, JSON.stringify(value.body).slice(0, 300));
      assert.ok(sameResidue(value.request.ligand, plan.ligand));
      assert.equal(value.request.structure, h.m17.prepared);
      return { handle: value.body.handle.handle };
    });
    h.sasa = made.body.handle.handle;
    const stored = await rec.step("A3-02", "The SASA areas (Å²) and the per-residue table on screen equal the stored object", async () =>
      (await readApi(page, `/runs/${run}/interface_sasa?handle=${enc(h.sasa)}`)).result, async result => {
      assert.ok(sameResidue(result.ligand, plan.ligand));
      assert.equal(result.structure, h.m17.prepared);
      const section = page.locator(".mw-table-head", { hasText: "단백질–리간드 SASA" }).locator("..");
      const shown = await section.locator("dl.mw-kv").first().evaluate(node => {
        const out = {};
        const items = [...node.children];
        for (let i = 0; i + 1 < items.length; i += 2) out[items[i].textContent.trim()] = items[i + 1].textContent.replace(/\s+/g, " ").trim();
        return out;
      });
      for (const [label, field] of SASA_FIELDS) assert.equal(shown[label], `${area2(result.summary[field])} Å²`, `${label} on screen`);
      const table = await page.getByRole("region", { name: "단백질 잔기 SASA 측정 행" }).locator("tbody tr").evaluateAll(items =>
        items.map(item => [...item.querySelectorAll("td")].map(cell => cell.textContent.replace(/\s+/g, " ").trim())));
      assert.equal(table.length, result.residues.length, "residue rows on screen");
      result.residues.forEach((row, i) => {
        const residue = row.residue;
        assert.equal(table[i][0], `${residue.resname} auth ${residue.chain_auth}/${residue.seq_auth}${residue.icode || ""} · label ` +
          `${residue.chain_label ?? "unknown"}/${residue.seq_label ?? "unknown"} · model ${residue.model_number ?? "unknown"}`, `row ${i} residue`);
        SASA_ROW_FIELDS.forEach((field, k) => assert.equal(table[i][1 + k], area2(row[field]), `row ${i} ${field}`));
      });
      evidence.observed.A3 = { residues: result.residues.length, summaryFields: SASA_FIELDS.length };
      return evidence.observed.A3;
    });
    await rec.step("A3-03", "Click the SASA history step, 방법 보고서 만들기, both downloads: bytes equal the saved report; every claim " +
      "equals the stored field and the Markdown lines carry the same rendered values", async () => {
      await historyStep(page, "compute_interface_sasa");
      const section = page.getByText("선택한 SASA 결과의 로컬 방법 보고서").locator("..");
      const report = await createAndWaitForSavedReport(page, section, run, "method_reports", "방법 보고서 만들기", "저장된 방법 보고서 미리보기");
      noteReport(evidence, "A3", "interface_sasa", report.status, report.artifact.handle);
      const downloads = await downloadBoth(app, page, section, run);
      const tab = await keepTabText(page, evidence, artifacts, "structure@A3", "structure");
      return { artifact: report.artifact, downloads, tab };
    }, async value => {
      const claims = value.artifact.manifest.claims;
      const summaryClaims = claims.filter(claim => claim.row_index === null);
      for (const [, field] of SASA_FIELDS) assert.ok(summaryClaims.some(claim => claim.quantity === field), `no claim of ${field}`);
      assert.equal(claims.length - summaryClaims.length, SASA_ROW_FIELDS.length * stored.residues.length, "residue claim count");
      const lines = value.artifact.markdown.split("\n");
      for (const claim of claims) {
        assert.equal(claim.unit, "A2");
        if (claim.row_index === null) {
          assert.equal(claim.exact_value, stored.summary[claim.quantity], `summary ${claim.quantity}`);
          const escaped = claim.quantity.replace(/_/g, "\\_");
          assert.ok(lines.includes(`- ${escaped}: ${claim.rendered_value} Å²`), `Markdown line of ${claim.quantity}`);
        } else {
          const row = stored.residues[claim.row_index];
          assert.equal(claim.exact_value, row[claim.quantity], `residue ${claim.row_index} ${claim.quantity}`);
          assert.ok(sameResidue(claim.subject.residue, row.residue));
        }
        assert.equal(claim.rendered_value, area2(claim.exact_value), "claim rendering");
      }
      const tableLines = lines.filter(line => /^\| .* \| [-\d.]+ \| [-\d.]+ \| [-\d.]+ \|$/.test(line));
      assert.equal(tableLines.length, stored.residues.length, "Markdown residue rows");
      stored.residues.forEach((row, i) => assert.ok(tableLines[i].endsWith(
        ` | ${SASA_ROW_FIELDS.map(field => area2(row[field])).join(" | ")} |`), `Markdown residue row ${i}`));
      return { report: value.artifact.handle, claims: claims.length, downloads: value.downloads, tab: value.tab };
    });
    await latestPipeline(page, h.m17.prepared);
  });

  // ---- A4: fpocket on chain A of the prepared structure; descriptors with units; alpha-sphere overlay; report
  await rec.part("A4", ["A1"], async () => {
    const panel = pocketPanel(page);
    const preflight = await rec.step("A4-01", "Choose the prepared structure in 포켓 검출 소스; the input check selects chain A (one chain: " +
      "the chain-selection branch does not apply)", async () => {
      await latestPipeline(page, h.m17.prepared);
      const source = panel.getByRole("combobox", { name: "포켓 검출 소스" });
      await source.locator(`option[value="${h.m17.prepared}"]`).waitFor({ state: "attached", timeout: 30000 });
      await source.selectOption(h.m17.prepared);
      const value = await preflightFor(page, run, h.m17.prepared);
      await waitPreflightText(panel, value.selected_chains);
      return value;
    }, async value => {
      const cap = (await readApi(page, "/capabilities")).methods.pocket_detection;
      assert.equal(cap.available, true, "fpocket capability not ready");
      assert.equal(value.ready, true);
      assert.deepEqual(value.selected_chains, ["A"]);
      assert.deepEqual(value.available_chains.map(item => item.chain_auth), ["A"], "1M17 has one protein chain");
      return { selectedChains: value.selected_chains, engine: [cap.engine, cap.release] };
    });
    const detected = await rec.step("A4-02", "Click 포켓 검출 실행, then 포켓 계산 승인 후 시작", () => detect(page, panel, run), async value => {
      assert.equal(value.approvalSeen, true, "the first expensive call did not ask for approval");
      return { job: value.job, set: value.set };
    });
    h.pockets = detected.set;
    const summary = await pocketSummary(page, run, detected.set);
    await rec.step("A4-03", "The pocket table equals the stored pocket set: at least one candidate, five descriptors each with its unit",
      async () => summary, async value => {
        assert.equal(value.null_result, false, "no pocket candidate");
        assert.ok(value.total_count >= 1);
        assert.deepEqual(value.selected_chains, preflight.selected_chains);
        const table = await summaryTable(panel, value, Math.min(10, value.total_count));
        evidence.observed.A4 = { total: value.total_count, displayed: table.displayed, descriptorUnits: table.descriptorUnits };
        return evidence.observed.A4;
      });
    const first = summary.pockets[0].rank;
    await rec.step("A4-04", "Click the first candidate's 선택 button: the alpha-sphere overlay is drawn; every sphere equals the stored one",
      () => selectAndCompare(page, panel, run, detected.set, first), async value => {
        assert.ok(value.sphereCount >= 1);
        await keepTabText(page, evidence, artifacts, "structure@A4", "structure");
        return { sphereCount: value.sphereCount, compared: value.spheres.comparedSpheres, liningAtoms: value.spheres.liningAtoms,
          focusDeltaA: value.focus.deltaA };
      });
    await rec.step("A4-05", "Click 포켓 보고서 만들기, both downloads: bytes equal the saved report; claims equal the stored set", async () => {
      const made = await createPocketReport(page, panel, run);
      noteReport(evidence, "A4", "pocket_detection", made.status, made.created);
      return pocketReportDownloads(app, page, panel, run, detected.set, summary);
    }, async value => ({ report: value.handle, claims: value.claims, pockets: value.pockets, markdownSha256: value.markdownSha256 }));
    await rec.step("A4-06", "Click 오버레이 지우기: the overlay is off (the reference annotation and the overlay exclude each other)", async () => {
      await panel.getByRole("button", { name: "오버레이 지우기" }).click();
      return waitObserve(page, overlayNone, "overlay cleared");
    }, async value => ({ overlay: value.data.pocketOverlay }));
    await latestPipeline(page, h.m17.prepared);
  });

  // ---- A5 (1M17 part): numbering of the PREPARED structure, chain A; screen counts = stored; KLIFS as reference
  await rec.part("A5-m17", ["A1"], async () => {
    const spec = plan.maps.find(item => item.id === "m17");
    const made = await rec.step("A5-01", "지식·보고서 잔기 번호 대응: choose the prepared 1M17 structure, chain A, tick 이 PDB ID가 맞습니다 " +
      "(1M17), SIFTS P00533 prefilled, 실행", () => makeMap(page, run, h.m17.prepared, spec), async value => {
      assert.equal(value.args.structure, h.m17.prepared);
      assert.equal(value.args.pdb_id, "1M17");
      return { handle: value.handle };
    });
    h.maps = { m17: made.handle };
    await rec.step("A5-02", "Chain A counts (대응됨·대응 없음·충돌) and the status filters on screen equal the stored map; KLIFS numbers are " +
      "shown as reference values", () => checkMapScreen(page, run, made.handle, spec), async value => {
      (evidence.observed.A5 ??= { maps: {} }).maps.m17 = value.chains;
      return value;
    });
    await rec.step("A5-03", "Click 보고서 만들기 of the map; the saved report opens", async () => {
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
      await nTestId(page, "numbering-report").click();
      const response = await posted;
      const body = await response.json();
      noteReport(evidence, "A5", "residue_numbering", response.status(), body.handle);
      await nTestId(page, "numbering-report-done").waitFor({ timeout: 30000 });
      return { status: response.status(), handle: body.handle };
    }, async value => {
      assert.equal(value.status, 201);
      const saved = await readApi(page, `/runs/${run}/reports/selected?handle=${enc(value.handle)}`);
      assert.equal(saved.manifest.analysis_type, "residue_numbering");
      return { report: value.handle };
    });
  });

  // ---- A6: reference annotation on the prepared 1M17 (map + contacts of the same structure), Mol* readback vs the
  // independent oracle, saved view, PNG + provenance JSON pair with the legend, report
  await rec.part("A6", ["A1", "A2", "A5-m17"], async () => {
    let annotation = null;
    const created = await rec.step("A6-01", "Click 구조 분석; choose the 1M17 map and the AQ4 contact result, click 주석 만들기", async () => {
      await latestPipeline(page, h.m17.prepared);
      const overlay = await pocketObserve(page);
      assert.ok(overlayNone(overlay), "the pocket overlay is still on");
      await sitePanel(page).waitFor({ timeout: 30000 });
      await waitSitePanel(page, ["ready"]);
      await waitFor(page, async () => (await mapRadios(page)).some(item => item.handle === h.maps.m17) ? true : null, "map listed", 30000);
      const maps = await mapRadios(page);
      const contacts = await contactRadios(page);
      await sTestId(page, "site-annotation-maps").locator(`label[data-site-map="${h.maps.m17}"] input`).check();
      await sTestId(page, "site-annotation-contacts").locator(`label[data-site-contact="${h.contacts}"] input`).check();
      await waitFor(page, async () => await sTestId(page, "site-annotation-create").isEnabled() ? true : null, "create enabled", 15000);
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === "annotate_reference_sites",
      { timeout: 60000 });
      await sTestId(page, "site-annotation-create").click();
      const response = await posted;
      const body = await response.json();
      const handle = body.handle?.handle;
      await waitFor(page, async () => (await annotationRows(page)).some(row => row.handle === handle && row.checked) ? true : null,
        "created annotation selected", 30000);
      return { body, request: response.request().postDataJSON().args, handle, maps, contacts };
    }, async value => {
      assert.equal(value.body.ok, true, JSON.stringify(value.body).slice(0, 300));
      assert.deepEqual(value.request, { numbering_map: h.maps.m17, contacts: h.contacts });
      assert.ok(value.maps.every(item => item.checked === false) && value.contacts.every(item => item.checked === false),
        "a choice was made automatically");
      annotation = await annotationDetail(page, run, value.handle);
      assert.equal(annotation.structure.handle, h.m17.prepared);
      assert.equal(annotation.numbering_map, h.maps.m17);
      assert.equal(annotation.contacts.handle, h.contacts);
      return { handle: value.handle };
    });
    h.annotation = created.handle;
    const group = () => annotation.groups.find(item => item.chain_auth === "A" && item.accession === "P00533");
    let expectedLines = [];
    await rec.step("A6-02", "The site table: status, counts by kind and minimum distance of every site equal the stored annotation " +
      "and the independent oracle of the input coordinates", () => siteTable(page), async table => {
      const sites = group()?.sites ?? [];
      assert.ok(group()?.klifs_applied, "group A/P00533 not applied");
      assert.deepEqual(sites.map(site => site.klifs_label), SITE_LABELS);
      assert.equal(table.handle, h.annotation);
      const compared = [];
      expectedLines = [];
      sites.forEach((site, index) => {
        const row = table.rows[index];
        assert.equal(row.klifs, site.klifs_label);
        assert.equal(row.status, site.status, `${site.klifs_label} status on screen`);
        if (site.status !== "annotated") { compared.push({ klifs: site.klifs_label, status: site.status }); return; }
        assert.equal(row.label, site.display_label);
        const truth = plan.siteOracle[residueKey(site.residue)] ?? { counts: { contact: 0, polar_contact: 0, hydrophobic_contact: 0 }, min: null, polar: [] };
        for (const type of ["contact", "polar_contact", "hydrophobic_contact"]) {
          assert.equal(site.contact.by_type[type].computed, true);
          assert.equal(site.contact.by_type[type].count, truth.counts[type], `${site.klifs_label} ${type} stored vs oracle`);
          assert.equal(row.counts[type], String(truth.counts[type]), `${site.klifs_label} ${type} cell`);
        }
        if (truth.min === null) {
          assert.equal(site.contact.min_distance_A, null);
          assert.equal(row.min, NO_CONTACT_IN_CUTOFF);
          x5(evidence, row.min === NO_CONTACT_IN_CUTOFF && row.min !== "0", `A6 site ${site.klifs_label}: no contact within the cutoff shown as a sentence, not 0`);
        } else {
          assert.ok(Math.abs(site.contact.min_distance_A - truth.min) <= 1e-9, `${site.klifs_label} min`);
          assert.equal(row.min, angstrom2(site.contact.min_distance_A));
        }
        assert.equal((site.contact.polar_pairs ?? []).length, truth.polar.length, `${site.klifs_label} polar pairs`);
        for (const pair of truth.polar) {
          const stored = site.contact.polar_pairs.find(item => item.protein_atom === pair.protein_atom && item.ligand_atom === pair.ligand_atom);
          assert.ok(stored && Math.abs(stored.distance_A - pair.distance_A) <= 1e-9, `${site.klifs_label} polar pair`);
          expectedLines.push({ klifs: site.klifs_label, residue: site.residue, protein_atom: pair.protein_atom,
            ligand_atom: pair.ligand_atom, shown: angstrom2(stored.distance_A) });
        }
        compared.push({ klifs: site.klifs_label, status: site.status, counts: row.counts, min: row.min });
      });
      assert.ok(expectedLines.length >= 1, "the oracle gives no polar pair at a reference site");
      evidence.observed.A6 = { sites: compared, polarLines: expectedLines.length };
      return evidence.observed.A6;
    });
    const catalog = await atomCatalog(page, run, h.m17.prepared);
    await rec.step("A6-03", "Click 주석 표시: Mol* readback sites and labels equal the stored display labels; the dashed lines equal the " +
      "oracle's polar pairs at the sites, between the catalog atoms of those residues", async () => {
      const value = await showAnnotation(page, h.annotation, true);
      return { ...value, panelStatus: clean(await sTestId(page, "site-annotation-viewer-status").textContent()) };
    }, async value => {
      const sites = annotatedSites(annotation);
      assert.equal(value.readback.drawnSiteCount, sites.length);
      assert.deepEqual(value.readback.sites.map(site => site.labelText), sites.map(site => site.display_label));
      assert.equal(value.readback.drawnLineCount, expectedLines.length, "drawn lines vs oracle polar pairs");
      assert.equal(value.readback.undrawnPairs.length, 0);
      assert.equal(value.readback.legend, true, "legend off by default");
      // no viewer label names a hydrogen bond (copied from annotation-flow.cjs, T11 R4)
      assert.ok(!value.readback.labelTexts.some(text => /수소\s*결합|hydrogen[\s-]+bond/i.test(text)), "a label names a hydrogen bond");
      assert.equal(value.readback.sourceHandle, h.m17.prepared);
      for (const want of expectedLines) {
        const protein = catalog.filter(row => sameResidue(row.ref.residue, want.residue) && row.ref.atom_name === want.protein_atom);
        const ligand = catalog.filter(row => sameResidue(row.ref.residue, plan.ligand) && row.ref.atom_name === want.ligand_atom);
        assert.equal(protein.length, 1); assert.equal(ligand.length, 1);
        const line = value.readback.lines.filter(item => item.klifs_label === want.klifs && item.protein_atom === want.protein_atom &&
          item.ligand_atom === want.ligand_atom);
        assert.equal(line.length, 1, `line ${want.klifs} ${want.protein_atom}-${want.ligand_atom}`);
        assert.equal(line[0].proteinSourceIndex, protein[0].viewer_source_index);
        assert.equal(line[0].ligandSourceIndex, ligand[0].viewer_source_index);
        assert.equal(line[0].labelText, want.shown);
        assert.equal(line[0].pickable, false);
      }
      assert.ok(value.panelStatus.includes(`점선 ${expectedLines.length}개`));
      return { sites: sites.length, lines: value.readback.drawnLineCount, labels: value.readback.labelTexts.length };
    });
    await rec.step("A6-04", "Type 보기 이름, click 현재 보기 저장, 현재 보기 PNG 내보내기, PNG 다운로드, JSON 출처 다운로드: a PNG + provenance " +
      "JSON pair with the legend, within 2048 px a side, 4,000,000 pixels and 8 MiB; the JSON's PNG hash is the PNG's", async () => {
      const scene = await saveScene(page, run, "m28 A6 annotation legend");
      const figure = await exportFigure(page, run);
      figure.download = await downloadFigure(app, page, run, figure);
      await keepTabText(page, evidence, artifacts, "structure@A6", "structure");
      return { scene, figure };
    }, async value => {
      assert.equal(value.scene.requestSchema, "viewer_scene@2");
      assert.deepEqual(value.scene.requestAnnotation, { handle: h.annotation, legend: true });
      assert.deepEqual(value.scene.value.annotation, { handle: h.annotation, legend: true });
      const figure = value.figure.value;
      assert.equal(value.figure.requestSchema, "viewer_figure@2");
      assert.equal(value.figure.legendComposited, true);
      assert.equal(figure.schema, "viewer_figure@2");
      assert.equal(figure.capture_method, "molstar_image_pass+legend");
      assert.equal(figure.scene_handle, value.scene.handle);
      assert.equal(figure.annotation.handle, h.annotation);
      assert.equal(figure.annotation.legend, true);
      assert.equal(figure.annotation.numbering_map, h.maps.m17);
      assert.equal(figure.annotation.contacts, h.contacts);
      assert.deepEqual(figure.annotation.display_labels, annotatedSites(annotation).map(site => site.display_label));
      const png = fs.readFileSync(value.figure.download.png.file);
      const json = JSON.parse(fs.readFileSync(value.figure.download.json.file, "utf8"));
      assert.deepEqual(json, figure, "the provenance JSON differs from the stored figure");
      assert.equal(json.png_sha256, sha(png), "the provenance JSON is not the PNG's pair");
      const decoded = await checkPng(value.figure.download.png.file, figure);
      assert.ok(figure.width <= 2048 && figure.height <= 2048, "a side above 2048 px");
      assert.ok(figure.width * figure.height <= 4_000_000, "more than 4,000,000 pixels");
      assert.ok(png.length <= PNG_MAX_BYTES, `PNG ${png.length} bytes above 8 MiB`);
      evidence.observed.A6.figure = { width: figure.width, height: figure.height, pngBytes: png.length, pngSha256: sha(png) };
      return { scene: value.scene.handle, figure: value.figure.handle, size: [decoded.width, decoded.height], pngBytes: png.length,
        pngSha256: decoded.sha256, jsonSha256: value.figure.download.json.sha256 };
    });
    await rec.step("A6-05", "Click 보고서 만들기 in the annotation panel; then 주석 끄기", async () => {
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
      await sTestId(page, "site-annotation-report").click();
      const response = await posted;
      const body = await response.json();
      noteReport(evidence, "A6", "reference_site_annotation", response.status(), body.handle);
      await sTestId(page, "site-annotation-report-done").waitFor({ timeout: 30000 });
      const off = await hideAnnotation(page);
      return { status: response.status(), handle: body.handle, off: off.data?.siteAnnotation };
    }, async value => {
      assert.equal(value.status, 201);
      const saved = await readApi(page, `/runs/${run}/reports/selected?handle=${enc(value.handle)}`);
      assert.equal(saved.manifest.analysis_type, "reference_site_annotation");
      const wording = hbondLines(saved.markdown);
      return { report: value.handle, off: value.off, wording };
    });
  });

  // ---- A5 (other structures): 1FIN A·C and 1MQ4 A on the loaded structures
  await rec.part("A5-others", [], async () => {
    for (const id of ["fin", "mq4"]) {
      const loaded = await rec.step(`A5-${id}-load`, `Choose ${plan.inputs[id].name}, click 구조 불러오기`, () => uploadLoad(page, plan.inputs[id]),
        async value => ({ handle: value.handle }));
      h[id] = { loaded: loaded.handle };
      evidence.inputs.push(loaded.file);
    }
    for (const id of ["fin", "mq4"]) {
      const spec = plan.maps.find(item => item.id === id);
      const made = await rec.step(`A5-${id}-map`, `지식·보고서 잔기 번호 대응: choose the loaded ${spec.pdbConfirm}, chains ` +
        `${spec.chains.map(chain => chain.chain).join("·")}, tick 이 PDB ID가 맞습니다, SIFTS prefilled, 실행`,
      () => makeMap(page, run, h[id].loaded, spec), async value => ({ handle: value.handle }));
      h.maps = { ...(h.maps ?? {}), [id]: made.handle };
      await rec.step(`A5-${id}-counts`, "Chain counts and filters on screen equal the stored map; KLIFS shown as reference values",
        () => checkMapScreen(page, run, made.handle, spec), async value => {
          (evidence.observed.A5 ??= { maps: {} }).maps[id] = value.chains;
          return value;
        });
    }
    await keepTabText(page, evidence, artifacts, "knowledge@A5", "knowledge");
  });

  // ---- A7: kinase precedents through the maps (1M17 A → P00533, 1FIN A·C → P24941), counts = the installed files
  await rec.part("A7", ["A5-m17", "A5-others"], async () => {
    assert.ok(plan.precedent, "the precedent set was not installed (scripts/m28_branch_a.py)");
    await rec.step("A7-01", "Click 지식·보고서 again: the precedent snapshot is the installed set; KT1 shown; moves_flagged not included " +
      "by default", async () => {
      await reenterKnowledge(page);
      await openPrecedents(page);
      await pt(page, "request-form").waitFor({ timeout: 30000 });
      await waitFor(page, async () => await pt(page, "numbering-map").inputValue() !== "" ? true : null, "map pre-selected", 30000);
      await pt(page, "chains").waitFor({ timeout: 30000 });
      return { api: await readApi(page, "/precedent_reference/status"),
        title: await pt(page, "set-hash").getAttribute("title"), kt1: clean(await pt(page, "kt1").textContent()),
        toggle: await pt(page, "include-flagged").isChecked(), note: await pt(page, "flagged-note").count() };
    }, async value => {
      assert.equal(value.api.installed, true);
      assert.equal(value.api.set_hash, plan.precedent.setHash);
      assert.equal(value.title, plan.precedent.setHash);
      assert.equal(value.kt1, kinase.KT1);
      assert.equal(value.toggle, false, "moves_flagged included by default");
      assert.equal(value.note, 0);
      return { setHash: value.api.set_hash, kt1Shown: true, flaggedDefault: value.toggle };
    });
    const results = {};
    for (const link of plan.precedent.links) {
      const made = await rec.step(`A7-${link.id}`, `Choose the ${link.map} map (all its chains), leave moves_flagged unticked, click ` +
        "전례 연결: chains, target state and counts on screen = stored = counted from the installed files",
      () => linkPrecedents(page, run, h.maps[link.map], link), async value => {
        const seen = precedentObserved(value.body);
        ((evidence.observed.A7 ??= { links: {} }).links)[link.id] = seen;
        x5(evidence, value.verified.flaggedText === `${NULL} (포함하지 않음)`, `A7 ${link.id}: moves_flagged count shown as not included, not 0`);
        x5(evidence, value.verified.bareZeroOrNone === 0, `A7 ${link.id}: no bare 0 or 없음 in the area`);
        return { handle: value.handle, ...seen };
      });
      results[link.id] = made;
    }
    for (const link of plan.precedent.links) {
      const handle = results[link.id].handle;
      await rec.step(`A7-${link.id}-report`, "Open the result, click 보고서 만들기, Markdown and JSON downloads: summary and source list " +
        "(KP1–KP6, KT1, UP2, UP5; no quotation), bytes equal the saved report", async () => {
        await openPrecedentResult(page, run, handle);
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
        await pt(page, "report").click();
        const response = await posted;
        const body = await response.json();
        noteReport(evidence, "A7", "kinase_precedents", response.status(), body.handle);
        await pt(page, "report-done").waitFor({ timeout: 30000 });
        const files = {};
        for (const [id, format] of [["report-markdown", "markdown"], ["report-json", "json"]]) {
          const downloaded = await downloadByClick(app, pt(page, id));
          files[format] = fs.readFileSync(downloaded.downloaded);
        }
        return { status: response.status(), handle: body.handle, files };
      }, async value => {
        assert.equal(value.status, 201);
        for (const format of ["markdown", "json"])
          assert.ok(value.files[format].equals(await readBytes(page, `/runs/${run}/reports/download?handle=${enc(value.handle)}&format=${format}`)),
            `${format} download differs from the backend bytes`);
        const text = value.files.markdown.toString("utf8");
        const stored = await precedentDetailApi(page, run, handle);
        for (const sentence of [...kinase.LIMITATIONS, kinase.KT1]) assert.ok(text.includes(sentence), "the report lacks a fixed sentence");
        const unresolved = stored.set_summary.unresolved_target_records.moves + stored.set_summary.unresolved_target_records.moves_flagged;
        assert.ok(text.includes(kinase.UP5(unresolved)), "the report lacks UP5");
        const pages = [stored];
        const quotes = new Set();
        let listed = 0;
        for (const target of stored.targets_overview) {
          if (target.excluded_flagged !== null) assert.ok(text.includes(kinase.UP2(target.excluded_flagged)), "the report lacks UP2");
          const all = await allPrecedentRecords(page, run, handle, target.accession);
          pages.push(...all.bodies);
          for (const item of all.records) {
            const record = item.record;
            for (const quote of [record.observation.text, record.observation.quote, ...record.tradeoffs.flatMap(entry => [entry.text, entry.quote])])
              if (typeof quote === "string" && quote.length >= 12) quotes.add(quote);
            assert.ok(text.includes(kinase.mdEscape(record.move_id)), "a record is missing from the source list");
            listed++;
          }
        }
        assert.equal([...quotes].filter(item => text.includes(item)).length, 0, "the report quotes an observation, quote or tradeoff");
        assert.equal(kinase.forbiddenIn(text, pages, true).length, 0, "forbidden wording in the report");
        const manifest = JSON.parse(value.files.json.toString("utf8"));
        assert.equal(manifest.analysis_type ?? manifest.manifest?.analysis_type, "kinase_precedents");
        return { report: value.handle, markdownSha256: sha(value.files.markdown), sourcesListed: listed, quoteStringsChecked: quotes.size };
      });
    }
    await openPrecedents(page);
    await keepTabText(page, evidence, artifacts, "knowledge@A7", "knowledge");
  }, { real: true });

  // ---- A8: reaction knowledge of 1S9I, 1A30, 1A4I with the isolated copy of the archived set; rows = computed
  await rec.part("A8", [], async () => {
    assert.ok(plan.reaction, "the reaction set copy is not ready (scripts/m28_branch_a.py)");
    for (const link of plan.reaction.links) {
      const loaded = await rec.step(`A8-${link.id}-load`, `Choose ${plan.inputs[link.structure].name}, click 구조 불러오기`,
        () => uploadLoad(page, plan.inputs[link.structure]), async value => ({ handle: value.handle }));
      h[link.structure] = { loaded: loaded.handle };
      evidence.inputs.push(loaded.file);
    }
    await rec.step("A8-01", "Click 지식·보고서: the reaction snapshot is the copied set", async () => {
      await reenterKnowledge(page);
      await openReaction(page);
      return { api: await readApi(page, "/reaction_reference/status"), uk1: clean(await rt(page, "reaction-note-uk1").textContent()) };
    }, async value => {
      assert.equal(value.api.installed, true);
      assert.equal(value.api.set_hash, plan.reaction.setHash);
      assert.equal(value.uk1, UK.UK1);
      return { setHash: value.api.set_hash };
    });
    for (const link of plan.reaction.links) {
      const made = await rec.step(`A8-${link.id}`, `Choose the loaded ${link.pdbId.suggested}, tick the suggested PDB ID, its chains ` +
        "(the M-CSA accession suggestion where planned), click 연결하기: chain coverage, rows and counts on screen = stored = computed",
      () => linkReaction(page, run, h[link.structure].loaded, link), async value => {
        const summary = value.verified.summary;
        ((evidence.observed.A8 ??= { links: {} }).links)[link.id] = { chains: Object.fromEntries(Object.entries(summary).map(([chain, item]) =>
          [chain, { coverage: item.coverage, counts: item.counts }])) };
        // innerText follows CSS text-transform (the eyebrow headings are upper-cased): compare case-insensitively.
        const text = (await rPanelText(page)).toLowerCase();
        const marked = heading => text.includes(`${heading} (${REACTION_REFERENCE_NOTE})`.toLowerCase());
        for (const [chain, item] of Object.entries(summary)) {
          if (item.coverage !== "covered") x5(evidence, item.counts === null, `A8 ${link.id} ${chain} ${item.coverage}: counts shown as not checked, not 0`);
          if (item.uniprot[0] === "checked") {
            assert.ok(item.features > 0, `${link.id} ${chain}: no UniProt site shown`);
            assert.ok(marked("UniProt 부위"), "UniProt sites not marked as reference values");
          }
          if (item.coverage === "covered") {
            assert.equal(item.reactions, "checked", `${link.id} ${chain}: reaction section not checked`);
            assert.ok(marked("반응"), "reactions not marked as reference values");
          }
        }
        return { handle: value.handle, chains: Object.fromEntries(Object.entries(summary).map(([chain, item]) =>
          [chain, { coverage: item.coverage, counts: item.counts, uniprot: item.uniprot, reactions: item.reactions, features: item.features }])) };
      });
      await rec.step(`A8-${link.id}-report`, "Click 보고서 만들기 for the opened result; Markdown and JSON downloads equal the backend bytes", async () => {
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
        await rt(page, "reaction-report").click();
        const response = await posted;
        const body = await response.json();
        noteReport(evidence, "A8", "reaction_knowledge", response.status(), body.handle);
        await rt(page, "reaction-report-done").waitFor({ timeout: 30000 });
        const files = {};
        for (const [id, format] of [["reaction-report-markdown", "markdown"], ["reaction-report-json", "json"]]) {
          const downloaded = await downloadByClick(app, rt(page, id));
          files[format] = fs.readFileSync(downloaded.downloaded);
        }
        return { status: response.status(), handle: body.handle, manifest: body.manifest, files };
      }, async value => {
        assert.equal(value.status, 201);
        assert.equal(value.manifest.analysis_type, "reaction_knowledge");
        assert.equal(value.manifest.result_handle, made.handle);
        for (const format of ["markdown", "json"])
          assert.ok(value.files[format].equals(await readBytes(page, `/runs/${run}/reports/download?handle=${enc(value.handle)}&format=${format}`)),
            `${format} download differs from the backend bytes`);
        const text = value.files.markdown.toString("utf8");
        for (const sentence of RK) assert.ok(text.includes(sentence), "the report lacks an RK sentence");
        const stored = await reactionDetailApi(page, run, made.handle, { ...DEFAULT_PAGING, row_limit: 200, feature_limit: 200 });
        assert.equal(reaction.forbiddenIn(text, [stored]).length, 0, "forbidden wording in the report");
        return { report: value.handle, markdownSha256: sha(value.files.markdown) };
      });
    }
    await keepTabText(page, evidence, artifacts, "knowledge@A8", "knowledge");
  }, { real: true });

  if (run) evidence.providerCalls.push(await providerCalls(page, run));
}

// ------------------------------------------------------------------ main
function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const evidence = { schema: "m28_branch_a_evidence@1", mode: input.mode, run: null, inputs: [], handles: {}, parts: {},
    observed: {}, reportsCreated: 0, reportHandles: [], x5: [], texts: {}, providerCalls: [],
    planSha256: sha(fs.readFileSync(input.plan)), startedAt: new Date().toISOString() };
  const session = await launchOffscreen({ url: input.url, artifacts: input.artifacts, interactive: false });
  const log = requestLog(session.page);
  const rec = recorder(session, evidence);
  let error = null;
  let proof = null;
  try {
    proof = await offscreenProof(session.app, session.page);
    await modeFixture(session, input, rec, evidence);
  } catch (caught) {
    error = caught;
  } finally {
    try { proof = { ...await offscreenProof(session.app, session.page), atStart: proof }; } catch { /* keep the start proof */ }
    await session.close();
  }
  const parts = Object.fromEntries(Object.entries(evidence.parts).map(([name, value]) => [name, value.status]));
  const providerZero = evidence.providerCalls.length > 0 && evidence.providerCalls.every(item => item.zero);
  const complete = offscreenComplete(proof);
  const passed = !error && complete && proof.nonLoopbackRequests === 0 && providerZero &&
    Object.keys(parts).length > 0 && Object.values(parts).every(value => value === "pass");
  evidence.finishedAt = new Date().toISOString();
  evidence.error = error ? String(error.stack ?? error).slice(0, 4000) : null;
  evidence.requestCount = log.length;
  fs.writeFileSync(path.join(input.artifacts, "endtoend-a-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  const harness = Object.fromEntries(["endtoend-a-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs", "pocket-flow.cjs",
    "scenes-flow.cjs", "kinase-precedents-flow.cjs", "reaction-knowledge-flow.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m28_branch_a_row@1", mode: input.mode, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", parts, runId: evidence.run, reportsCreated: evidence.reportsCreated,
    buildId: buildId(), harness, offscreen: proof, offscreenComplete: complete,
    externalRequestCount: proof ? proof.nonLoopbackRequests : null, providerCalls: evidence.providerCalls,
    providerCallsZero: providerZero, error: evidence.error ? "see endtoend-a-evidence.json" : null,
    evidenceFile: "endtoend-a-evidence.json", stepsFile: path.basename(rec.file), artifacts: input.artifacts,
    startedAt: evidence.startedAt,
    finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, run: evidence.run, parts }) + "\n");
  if (error) process.stderr.write(`endtoend-a-flow failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`endtoend-a-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, halfUp, area2 };
