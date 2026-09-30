"use strict";

// M15 residue numbering offscreen QA (spec §10.4). Real Electron offscreen page (isOffscreen, GPU/WebGL, paint).
// Every product mutation is a Playwright locator mouse/keyboard/file-chooser/select input. Observation is read-only:
// data attributes and text of the 지식·보고서 numbering panel, renderer request/response events, Electron paint
// frames and GET reads of the loopback API. Labeled renderer-route fixtures (a failed read, held late responses) are
// recorded in the ledger and never produce a scientific value. The KLIFS oracle is the committed comparison-only
// KLIFS match_residues fixture row for 1MQ4:A (author number → KLIFS position), not the product's own function.
//
// Modes (the full sequence and the reference-folder changes between them: scripts/m15_offscreen_acceptance.py):
//   empty  service started with an empty MW_REFERENCE_DIR: 사용할 수 없음 + reason, no numbers, no run control
//   main   imported real snapshot: confirmed PDB ID + SIFTS prefill, alignment only, below identity, prepared
//          structure, report + download, read failure + retry, run switch + late response
//   stale  after a marked fixture set was activated: the main mode's maps show 이전 스냅샷 기준
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const { waitForViewer } = require("./normal-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const FIXTURES = path.join(REPO, "backend/tests/fixtures");
const STRUCTURE = path.join(FIXTURES, "public_1mq4.cif");
const KLIFS_ORACLE = path.join(FIXTURES, "reference/klifs/match_residues_fixture.jsonl");
const MODES = ["empty", "main", "stale"];
const ACCESSION = "O14965";            // AURKA; SIFTS accession of 1MQ4:A
const WRONG_QUERY = "CAMK1D";          // another kinase of the snapshot, far in sequence from AURKA
const WRONG_ACCESSION = "Q8IU85";
const TIE_RESIDUE = 388;               // C-terminal S388: SIFTS 388, alignment ambiguous (backend oracle test)
const ORACLE_REQUIRED = [210, 211, 212, 213, 273, 274]; // GK.45, hinge.46–48, xDFG.80–81 of the KLIFS table
const FAULT_LABEL = "QA fault fixture (labeled renderer route, not a scientific value): numbering read failure";
const HOLD_LABEL = "QA held-response fixture (labeled renderer route; unchanged backend bytes released late)";
const PROVIDER_EVENT_TYPES = new Set(["egress", "egress_budget_settled", "viewer_dispatch_started"]);

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, "set-hash": null, "previous-set-hash": null,
    runs: null, marker: null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2);
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode)) throw new Error(
    `Usage: numbering-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> [--url http://127.0.0.1:3000] ` +
    "[--set-hash <active set hash>] [--previous-set-hash <hash>] [--runs <runA,runB>] [--marker <text>]. " +
    "Full sequence: scripts/m15_offscreen_acceptance.py.");
  if (value.mode !== "empty" && !value["set-hash"]) throw new Error(`--set-hash is required for mode ${value.mode}`);
  if (value.mode === "stale" && (!value.runs || !value["previous-set-hash"]))
    throw new Error("mode stale needs --runs <runA,runB> and --previous-set-hash");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  value.artifacts = path.resolve(value.artifacts);
  value.url = new URL("/", value.url).toString();
  return value;
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
async function backendMaps(page, run) {
  const rows = [];
  let first = null;
  for (;;) {
    const chunk = await readApi(page, `/runs/${run}/numbering_maps?offset=${rows.length}&limit=100`);
    first ??= chunk;
    rows.push(...chunk.rows);
    if (!chunk.rows.length || rows.length >= chunk.total) break;
  }
  return { ...first, rows };
}
async function backendRows(page, run, handle) {
  const rows = [];
  for (;;) {
    const chunk = await readApi(page, `/runs/${run}/objects?handle=${enc(handle)}&offset=${rows.length}&limit=100`);
    rows.push(...chunk.rows);
    if (!chunk.rows.length || rows.length >= chunk.total) break;
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
  const file = path.join(artifacts, `numbering-${input.mode}.jsonl`);
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
      const html = await page.evaluate(() => document.querySelector("section.mw-numbering")?.outerHTML.slice(0, 60000) ?? "")
        .catch(() => null);
      if (html) fs.writeFileSync(path.join(artifacts, `${caseId}-failure.numbering.html`), html);
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

// ------------------------------------------------------------------ tabs and structure screen (as tabs-flow.cjs)
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
async function chooseRun(page, run) {
  await selectTab(page, "구조 분석");
  await page.getByRole("tab", { name: /^run/i }).click();
  await page.locator("#run-choice").selectOption(run);
  await waitFor(page, async () => await globalRun(page) === run, `run ${run} selected`, 30000);
  await waitForViewer(page, value => value.sourceHandle !== null && value.catalogReady === true, 60000);
}
async function uploadLoad(page, file) {
  await page.getByRole("tab", { name: /^run/i }).click();
  const before = (await snapshot(page))?.sourceHandle ?? null;
  const chooser = page.waitForEvent("filechooser", { timeout: 30000 });
  await page.locator('input[type="file"]').first().click();
  await (await chooser).setFiles(file);
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).click();
  const viewer = await waitForViewer(page, value => !!value.sourceHandle && value.sourceHandle !== before &&
    value.sourceHandle.includes("/structure/") && value.catalogReady === true, 90000);
  return { handle: viewer.sourceHandle, file: { name: path.basename(file), ...fileRecord(file),
    provenance: "public PDB entry 1MQ4 (repository fixture; Aurora A kinase domain)" } };
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
  return { prepared };
}

// ------------------------------------------------------------------ numbering panel (지식·보고서)
const panel = page => page.locator("section.mw-numbering");
const area = (page, name) => panel(page).locator(`[data-numbering-area="${name}"]`);
const testId = (page, id) => panel(page).locator(`[data-testid="${id}"]`);
const areaState = (page, name) => area(page, name).getAttribute("data-state", { timeout: 2000 }).catch(() => null);
async function waitArea(page, name, states, timeout = 60000) {
  const wanted = Array.isArray(states) ? states : [states];
  return waitFor(page, async () => { const state = await areaState(page, name); return wanted.includes(state) ? state : null; },
    `${name} area ${wanted.join("|")}`, timeout);
}
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
async function openKnowledge(page) {
  await selectTab(page, "지식·보고서");
  await panel(page).waitFor({ timeout: 15000 });
}
async function mapButtons(page) {
  return panel(page).locator("button.mw-numbering-map").evaluateAll(items => items.map(item => ({
    handle: item.getAttribute("data-numbering-map"), stale: item.getAttribute("data-stale"),
    nullResult: item.getAttribute("data-null-result"), pressed: item.getAttribute("aria-pressed"),
    text: item.textContent?.replace(/\s+/g, " ").trim() })));
}
/** Pick the structure (a real select input). An empty choice first resets the form of an earlier map. */
async function chooseStructure(page, handle) {
  await waitArea(page, "create", "ready");
  const select = testId(page, "numbering-structure");
  if (await select.inputValue() !== "") await select.selectOption("");
  await select.selectOption(handle);
  await waitFor(page, async () => await testId(page, "numbering-chain-A").count() === 1 ? true : null, "chain A choice", 30000);
  await waitFor(page, async () => /업로드 원본|PDB ID가 없습니다|읽지 못했습니다/.test(await testId(page, "numbering-pdb-hint").textContent())
    ? true : null, "PDB ID suggestion read", 30000);
}
async function pickFromSearch(page, chain, query, accession) {
  await testId(page, `numbering-picker-${chain}`).click();
  await testId(page, "numbering-uniprot-query").fill(query);
  await testId(page, "numbering-uniprot-search").click();
  const result = panel(page).locator(`[data-testid="numbering-uniprot-picker"] button[data-uniprot-accession="${accession}"]`);
  await result.waitFor({ timeout: 30000 });
  const shown = await panel(page).locator('[data-testid="numbering-uniprot-picker"] button[data-uniprot-accession]')
    .evaluateAll(items => items.map(item => item.getAttribute("data-uniprot-accession")));
  await result.click();
  await waitFor(page, async () => (await testId(page, `numbering-accession-${chain}`).textContent()).includes(accession)
    ? true : null, `${accession} picked for ${chain}`, 15000);
  return { query, results: shown };
}
/** Click 실행 and return the new map handle (POST response read, not produced). */
async function runMap(page, run) {
  const button = testId(page, "numbering-run");
  await waitFor(page, async () => await button.isEnabled() ? true : null, "실행 enabled", 30000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/commands` &&
    response.request().postDataJSON()?.tool === "map_residue_numbering", { timeout: 180000 });
  await button.click();
  const response = await posted;
  const body = await response.json();
  const request = response.request().postDataJSON();
  assert.equal(body.ok, true, `map_residue_numbering failed: ${JSON.stringify(body).slice(0, 600)}`);
  const handle = body.handle.handle;
  await testId(page, "numbering-run-result").filter({ hasText: "대응을 만들었습니다" }).waitFor({ timeout: 30000 });
  await panel(page).locator(`button.mw-numbering-map[data-numbering-map="${handle}"][aria-pressed="true"]`).waitFor({ timeout: 30000 });
  await waitArea(page, "detail", ["ready", "scientific_null"], 60000);
  return { handle, request: request.args };
}
async function chainSummary(page, chain) {
  const node = panel(page).locator(`[data-chain-summary="${chain}"]`);
  await node.waitFor({ timeout: 15000 });
  return { crossCheck: await node.getAttribute("data-cross-check"), text: clean(await node.textContent()),
    klifsApplied: await node.locator("[data-klifs-applied]").evaluateAll(items => items.map(item => item.getAttribute("data-klifs-applied"))) };
}
async function filterCount(page) {
  const text = clean(await testId(page, "numbering-filter-count").textContent());
  const found = text.match(/필터 결과 (\d+) \/ 전체 (\d+)/);
  assert.ok(found, `filter count text: ${text}`);
  return { text, matched: Number(found[1]), total: Number(found[2]) };
}
async function clickFilter(page, value) {
  await testId(page, `numbering-filter-${value}`).click();
  await waitFor(page, async () => await testId(page, `numbering-filter-${value}`).getAttribute("aria-pressed") === "true" ? true : null,
    `filter ${value}`, 10000);
  return filterCount(page);
}
async function visibleRows(page) {
  if (!await testId(page, "numbering-rows").count()) return [];
  return testId(page, "numbering-rows").locator("tbody tr").evaluateAll(items => items.map(item => {
    const cells = [...item.querySelectorAll("td")].map(cell => cell.textContent.replace(/\s+/g, " ").trim());
    return { status: item.getAttribute("data-numbering-status"), residue: cells[0], statusText: cells[1], uniprot: cells[2],
      match: cells[3], crossCheck: cells[4], klifs: cells[5], answers: cells[6],
      noCrossCheck: !!item.querySelector('[data-no-cross-check="true"]'), mismatch: !!item.querySelector('[data-residue-mismatch="true"]'),
      klifsGapped: !!item.querySelector('[data-klifs-gapped="true"]') };
  }));
}
function parseResidue(text) {
  const found = text.match(/^모델 (\d+) (\S+) (\S+) (-?\d+)(\S*) \(/);
  return found ? { model: Number(found[1]), chain: found[2], resname: found[3], seqAuth: Number(found[4]), icode: found[5] } : null;
}
/** Every row of the current filter, page by page through the 다음 button (read-only DOM between clicks). */
async function allScreenRows(page) {
  const rows = [];
  for (let guard = 0; guard < 100; guard++) {
    const pageText = clean(await testId(page, "numbering-page").textContent());
    rows.push(...(await visibleRows(page)).map(row => ({ ...row, page: pageText })));
    const next = testId(page, "numbering-page-next");
    if (!await next.isEnabled()) return rows;
    await next.click();
    await waitFor(page, async () => clean(await testId(page, "numbering-page").textContent()) !== pageText ? true : null,
      "next page", 10000);
  }
  throw new Error("page loop did not end");
}
function klifsOracle() {
  const row = fs.readFileSync(KLIFS_ORACLE, "utf8").split("\n").filter(Boolean).map(line => JSON.parse(line))
    .find(item => item.pdb_id === "1MQ4" && item.chain === "A");
  assert.ok(row, "1MQ4:A KLIFS match_residues fixture row missing");
  const data = typeof row.data === "string" ? JSON.parse(row.data) : row.data;
  return { structureId: row.structure_ID, file: fileRecord(KLIFS_ORACLE),
    table: data.filter(item => /^\d+$/.test(String(item.Xray_position)))
      .map(item => ({ seqAuth: Number(item.Xray_position), label: item.KLIFS_position, index: item.index })) };
}

// ------------------------------------------------------------------ modes
async function modeEmpty(session, input, rec_, evidence, log) {
  const { page } = session;
  const run = await rec_.step("A01-new-run", [], "Click 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.runs.A = run;
  const loaded = await rec_.step("A02-upload", [], "Choose public_1mq4.cif, 구조 불러오기", () => uploadLoad(page, STRUCTURE),
    async value => value);
  evidence.inputs.push(loaded.file);
  await rec_.step("A03-no-snapshot", ["N-no-snapshot"],
    "Click 지식·보고서 with no reference snapshot: 사용할 수 없음 + reason + import command; no numbers, no run control", async () => {
      const started = Date.now();
      await openKnowledge(page);
      await waitArea(page, "snapshots", "unavailable");
      await waitArea(page, "create", "unavailable");
      await page.waitForTimeout(1500);
      const snapshotText = clean(await area(page, "snapshots").textContent());
      const createText = clean(await area(page, "create").textContent());
      return { snapshotText, createText,
        command: clean(await testId(page, "numbering-snapshot-unavailable").locator("pre.mw-numbering-command").textContent()),
        controls: await area(page, "snapshots").locator("button, input, select, textarea, a").count() +
          await area(page, "create").locator("button, input, select, textarea, a").count(),
        runButtons: await testId(page, "numbering-run").count(), structureSelects: await testId(page, "numbering-structure").count(),
        setHash: await testId(page, "numbering-set-hash").count(), sources: await testId(page, "numbering-snapshot-sources").count(),
        mapsText: clean(await area(page, "maps").textContent()), mapButtons: (await mapButtons(page)).length,
        writes: log.filter(row => row.api && row.at >= started && row.method !== "GET").map(row => `${row.method} ${row.path}`),
        api: await readApi(page, "/reference/snapshots"), capability: (await readApi(page, "/capabilities")).methods?.residue_numbering ?? null };
    }, async value => {
      assert.equal(value.api.available, false, "the backend reports a snapshot; the empty case needs an empty reference folder");
      assert.ok(value.snapshotText.includes("사용할 수 없음"), value.snapshotText);
      assert.ok(value.api.reason && value.snapshotText.includes(value.api.reason), `reason not shown: ${value.snapshotText}`);
      assert.ok(value.createText.includes("사용할 수 없음"), value.createText);
      assert.match(value.command, /import_reference_snapshots\.py/);
      assert.ok(!/\d/.test(value.snapshotText + value.createText), `a number is shown: ${value.snapshotText} | ${value.createText}`);
      assert.equal(value.controls, 0, "controls in the unavailable snapshot/create areas");
      assert.equal(value.runButtons, 0);
      assert.equal(value.structureSelects, 0);
      assert.equal(value.setHash, 0);
      assert.equal(value.sources, 0);
      assert.equal(value.mapButtons, 0);
      assert.deepEqual(value.writes, []);
      return value;
    });
  evidence.providerCalls.push(await providerCalls(page, run));
}

async function modeMain(session, input, rec_, evidence, log) {
  const { page } = session;
  const runA = await rec_.step("M01-new-run", [], "Click 새 run (run A)", () => newRun(page), async id => ({ run: id }));
  evidence.runs.A = runA;
  const loaded = await rec_.step("M02-upload", [], "Choose public_1mq4.cif, 구조 불러오기", () => uploadLoad(page, STRUCTURE),
    async value => value);
  evidence.inputs.push(loaded.file);
  const structure = loaded.handle;
  evidence.handles.structure = structure;
  const maps = evidence.handles.maps;

  // ---- b: confirmed PDB ID → SIFTS prefill → cross-checked map, rows, KLIFS oracle, filter, S388 conflict
  const confirmed = await rec_.part("confirmed", ["N-confirmed-sifts", "N-klifs-oracle", "N-status-filter", "N-conflict-row"], async () => {
    const cases = ["N-confirmed-sifts"];
    await rec_.step("B01-snapshot", cases, "Click 지식·보고서: active snapshot set, sources, licenses shown", async () => {
      await openKnowledge(page);
      await waitArea(page, "snapshots", "ready");
      return { setHash: clean(await testId(page, "numbering-set-hash").textContent()),
        setHashTitle: await testId(page, "numbering-set-hash").getAttribute("title"),
        sources: await testId(page, "numbering-snapshot-sources").locator("[data-snapshot-source]").evaluateAll(items =>
          items.map(item => ({ source: item.getAttribute("data-snapshot-source"), text: item.textContent.replace(/\s+/g, " ").trim() }))),
        api: await readApi(page, "/reference/snapshots") };
    }, async value => {
      assert.equal(value.api.set_hash, input["set-hash"], "backend active set differs from the imported set");
      assert.equal(value.setHashTitle, input["set-hash"]);
      assert.equal(value.setHash, input["set-hash"].slice(0, 12));
      assert.deepEqual(value.sources.map(item => item.source).sort(), ["klifs", "sifts", "uniprot"]);
      for (const source of value.api.sources) {
        const shown = value.sources.find(item => item.source === source.source);
        assert.ok(shown.text.includes(source.snapshot_id) && shown.text.includes(source.date), `${source.source} row`);
      }
      return { setHash: value.api.set_hash, sources: value.api.sources.map(item => [item.source, item.snapshot_id, item.license]) };
    });
    await rec_.step("B02-structure", cases, "Choose the structure and chain A; the PDB ID suggestion 1MQ4 is shown unconfirmed", async () => {
      await chooseStructure(page, structure);
      await testId(page, "numbering-chain-A").check();
      return { hint: clean(await testId(page, "numbering-pdb-hint").textContent()), pdbId: await testId(page, "numbering-pdb-id").inputValue(),
        confirmed: await testId(page, "numbering-pdb-confirm").isChecked(), accession: clean(await testId(page, "numbering-accession-A").textContent()),
        options: await testId(page, "numbering-structure").locator("option").evaluateAll(items => items.map(item => item.value)),
        backendHint: await readApi(page, `/runs/${runA}/reference/pdb_id_hint?structure=${enc(structure)}`) };
    }, async value => {
      assert.equal(value.backendHint.pdb_id, "1MQ4");
      assert.ok(value.hint.includes("1MQ4"), value.hint);
      assert.equal(value.pdbId, "1MQ4");
      assert.equal(value.confirmed, false, "the suggestion was confirmed automatically");
      assert.ok(value.accession.includes("고르지 않음"), value.accession);
      assert.ok(value.options.includes(structure));
      return value;
    });
    await rec_.step("B03-confirm", cases, "Tick 이 PDB ID가 맞습니다: SIFTS accession O14965 prefilled for chain A", async () => {
      await testId(page, "numbering-pdb-confirm").check();
      await waitFor(page, async () => (await testId(page, "numbering-accession-A").textContent()).includes(ACCESSION) ? true : null,
        "SIFTS prefill", 30000);
      return { accession: clean(await testId(page, "numbering-accession-A").textContent()),
        sifts: clean(await testId(page, "numbering-sifts-state").textContent()), backend: await readApi(page, "/reference/sifts_chains?pdb_id=1MQ4") };
    }, async value => {
      assert.ok(value.accession.includes("SIFTS 미리 채움"), value.accession);
      assert.deepEqual(value.backend.chains.find(chain => chain.chain_auth === "A")?.accessions, [ACCESSION]);
      return value;
    });
    const made = await rec_.step("B04-run", cases, "Click 실행: the map appears; chain A cross-checked, KLIFS applied", () => runMap(page, runA),
      async value => {
        assert.deepEqual(value.request.chains, [{ chain_auth: "A", uniprot_accession: ACCESSION }]);
        assert.equal(value.request.pdb_id, "1MQ4");
        const summary = await chainSummary(page, "A");
        const listed = (await backendMaps(page, runA)).rows.find(row => row.handle === value.handle);
        const chain = listed.chain_details.find(item => item.chain_auth === "A");
        assert.equal(summary.crossCheck, "true");
        assert.equal(chain.cross_check, true);
        assert.deepEqual(chain.methods_run, ["sifts", "local_alignment"]);
        assert.deepEqual(summary.klifsApplied, ["true"]);
        assert.equal(await areaState(page, "detail"), "ready");
        assert.ok(summary.text.includes("일치율 100 %"), summary.text);
        return { handle: value.handle, summary, backendCounts: listed.counts, pdbId: listed.pdb_id };
      });
    maps.confirmed = made.handle;
    const screen = await rec_.step("B05-rows", ["N-confirmed-sifts", "N-klifs-oracle"],
      "Page through the rows table (다음); KLIFS numbers on screen equal the KLIFS match_residues table of 1MQ4:A", async () => {
        const rows = await allScreenRows(page);
        return { rows, count: await filterCount(page), backend: await backendRows(page, runA, made.handle) };
      }, async value => {
        const oracle = klifsOracle();
        assert.equal(value.rows.length, value.backend.length, "shown rows differ from the stored rows");
        assert.equal(value.count.total, value.backend.length);
        const byAuth = new Map();
        for (const row of value.rows) {
          const residue = parseResidue(row.residue);
          assert.ok(residue, `residue text ${row.residue}`);
          if (residue.icode === "") byAuth.set(residue.seqAuth, row);
        }
        value.rows.forEach((row, index) => assert.equal(row.status, value.backend[index].status, `row ${index} status`));
        let compared = 0;
        let gapped = 0;
        const checked = [];
        for (const item of oracle.table) {
          const row = byAuth.get(item.seqAuth);
          // The cell is "KLIFS <label>" plus an optional 건너뛴 일치 badge (data-klifs-gapped), which is not part of the label.
          const shown = row?.klifs.replace(/건너뛴 일치$/, "").match(/^KLIFS (\S+)$/)?.[1] ?? null;
          if (shown === null) { assert.ok(!ORACLE_REQUIRED.includes(item.seqAuth), `no KLIFS number shown for ${item.seqAuth}`); continue; }
          assert.equal(shown, item.label, `author ${item.seqAuth}: screen KLIFS ${shown} != KLIFS table ${item.label}`);
          compared++;
          if (row.klifsGapped) gapped++;
          if (ORACLE_REQUIRED.includes(item.seqAuth)) checked.push({ seqAuth: item.seqAuth, residue: row.residue, screen: shown, oracle: item.label });
        }
        assert.equal(checked.length, ORACLE_REQUIRED.length);
        assert.ok(compared >= 75, `only ${compared} KLIFS numbers compared`);
        return { rows: value.rows.length, pages: [...new Set(value.rows.map(row => row.page))], compared, gappedShown: gapped,
          oracleRows: oracle.table.length, oracleStructureId: oracle.structureId, oracleFile: oracle.file, required: checked };
      });
    await rec_.step("B06-filter", ["N-status-filter", "N-conflict-row"],
      "Click 충돌 / 대응됨 / 대응 없음 / 전체: the count text follows; the only conflict is S388 (one_method_only)", async () => {
        const conflict = await clickFilter(page, "conflict");
        const conflictRows = await visibleRows(page);
        const mapped = await clickFilter(page, "mapped");
        const unmapped = await clickFilter(page, "unmapped");
        const emptyNote = clean(await area(page, "detail").textContent()).includes("이 필터에 맞는 행이 없습니다");
        const all = await clickFilter(page, "all");
        return { conflict, conflictRows, mapped, unmapped, emptyNote, all };
      }, async value => {
        const counts = (await backendMaps(page, runA)).rows.find(row => row.handle === made.handle).counts;
        assert.equal(value.conflict.matched, counts.conflict);
        assert.equal(value.mapped.matched, counts.mapped);
        assert.equal(value.unmapped.matched, counts.unmapped);
        assert.equal(value.all.matched, counts.mapped + counts.unmapped + counts.conflict);
        assert.ok([value.conflict, value.mapped, value.unmapped].every(item => item.total === value.all.total), "total not kept");
        assert.equal(value.conflict.matched, 1);
        assert.equal(value.unmapped.matched, 0);
        assert.ok(value.emptyNote);
        const [row] = value.conflictRows;
        const residue = parseResidue(row.residue);
        assert.equal(residue.seqAuth, TIE_RESIDUE);
        assert.equal(residue.resname, "SER");
        assert.equal(row.status, "conflict");
        assert.ok(row.statusText.includes("충돌") && row.statusText.includes("one_method_only"), row.statusText);
        assert.ok(row.answers.includes(`SIFTS: ${ACCESSION} ${TIE_RESIDUE}`) && row.answers.includes("alignment_ambiguous"), row.answers);
        return { counts, filters: { conflict: value.conflict.text, mapped: value.mapped.text, unmapped: value.unmapped.text, all: value.all.text },
          conflictRow: row };
      });
    return made;
  });

  // ---- c: accession picked without confirming the PDB ID → alignment only, no cross-check, S388 unmapped
  await rec_.part("alignment-only", ["N-alignment-only"], async () => {
    const cases = ["N-alignment-only"];
    await rec_.step("C01-pick", cases, "Choose the structure again, chain A, leave PDB ID unconfirmed, UniProt 검색 O14965, pick it", async () => {
      await chooseStructure(page, structure);
      await testId(page, "numbering-chain-A").check();
      const search = await pickFromSearch(page, "A", ACCESSION, ACCESSION);
      return { search, confirmed: await testId(page, "numbering-pdb-confirm").isChecked(),
        accession: clean(await testId(page, "numbering-accession-A").textContent()) };
    }, async value => {
      assert.equal(value.confirmed, false);
      assert.ok(value.accession.includes("직접 고름"), value.accession);
      return value;
    });
    const made = await rec_.step("C02-run", cases, "Click 실행: chain A shows 교차 확인 없음; S388 is 대응 없음", async () => {
      const result = await runMap(page, runA);
      const summary = await chainSummary(page, "A");
      const firstPage = await visibleRows(page);
      const unmapped = await clickFilter(page, "unmapped");
      const unmappedRows = await visibleRows(page);
      await clickFilter(page, "all");
      return { ...result, summary, firstPage, unmapped, unmappedRows };
    }, async value => {
      assert.equal(value.request.pdb_id, null, "an unconfirmed PDB ID was sent");
      assert.deepEqual(value.request.chains, [{ chain_auth: "A", uniprot_accession: ACCESSION }]);
      const listed = (await backendMaps(page, runA)).rows.find(row => row.handle === value.handle);
      const chain = listed.chain_details.find(item => item.chain_auth === "A");
      assert.equal(chain.cross_check, false);
      assert.deepEqual(chain.methods_run, ["local_alignment"]);
      assert.equal(value.summary.crossCheck, "false");
      assert.ok(value.summary.text.includes("교차 확인 없음"), value.summary.text);
      assert.ok(value.firstPage.length > 0 && value.firstPage.every(row => row.noCrossCheck), "rows without 교차 확인 없음 marker");
      assert.equal(value.unmapped.matched, listed.counts.unmapped);
      const tie = value.unmappedRows.find(row => parseResidue(row.residue)?.seqAuth === TIE_RESIDUE);
      assert.ok(tie, "S388 not among the 대응 없음 rows");
      assert.equal(tie.status, "unmapped");
      assert.ok(tie.statusText.includes("대응 없음"));
      return { handle: value.handle, crossCheckAbsentReason: chain.cross_check_absent_reason, counts: listed.counts,
        summary: value.summary.text, s388: tie };
    });
    maps.alignmentOnly = made.handle;
  });

  // ---- d: wrong accession (another kinase) → below identity, chain unmapped, scientific_null
  await rec_.part("below-identity", ["N-below-identity"], async () => {
    const cases = ["N-below-identity"];
    await rec_.step("D01-pick", cases, `Choose the structure, chain A, UniProt 검색 ${WRONG_QUERY}, pick ${WRONG_ACCESSION}`, async () => {
      await chooseStructure(page, structure);
      await testId(page, "numbering-chain-A").check();
      return pickFromSearch(page, "A", WRONG_QUERY, WRONG_ACCESSION);
    }, async value => value);
    const made = await rec_.step("D02-run", cases, "Click 실행: chain unmapped below identity; 대응된 잔기 없음(계산은 성공)", async () => {
      const result = await runMap(page, runA);
      return { ...result, summary: await chainSummary(page, "A"), detail: await areaState(page, "detail"),
        nullText: clean(await testId(page, "numbering-null-result").textContent()),
        button: (await mapButtons(page)).find(item => item.handle === result.handle), count: await filterCount(page) };
    }, async value => {
      const listed = (await backendMaps(page, runA)).rows.find(row => row.handle === value.handle);
      const chain = listed.chain_details.find(item => item.chain_auth === "A");
      assert.equal(listed.null_result, true);
      assert.equal(listed.counts.mapped, 0);
      assert.ok(chain.alignment.chain_reason.includes("alignment_below_identity"), JSON.stringify(chain.alignment));
      assert.equal(value.detail, "scientific_null");
      assert.equal(value.nullText, "대응된 잔기 없음(계산은 성공)");
      assert.equal(value.button.nullResult, "true");
      assert.ok(value.summary.text.includes("alignment_below_identity"), value.summary.text);
      assert.ok(value.summary.text.includes(WRONG_ACCESSION));
      return { handle: value.handle, counts: listed.counts, identity: chain.alignment.identity_pct,
        coverage: chain.alignment.coverage_pct, chainReason: chain.alignment.chain_reason, summary: value.summary.text };
    });
    maps.belowIdentity = made.handle;
  });

  // ---- f: report of the confirmed map → report list + downloads equal the backend bytes
  if (confirmed) await rec_.part("report", ["N-report"], async () => {
    const cases = ["N-report"];
    const created = await rec_.step("F01-report", cases, "Click the confirmed map, then 보고서 만들기", async () => {
      await panel(page).locator(`button.mw-numbering-map[data-numbering-map="${confirmed.handle}"]`).click();
      await waitArea(page, "detail", "ready");
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${runA}/method_reports`, { timeout: 60000 });
      await testId(page, "numbering-report").click();
      const body = await (await posted).json();
      await testId(page, "numbering-report-done").waitFor({ timeout: 30000 });
      return { handle: body.handle, done: clean(await testId(page, "numbering-report-done").textContent()) };
    }, async value => {
      const listed = (await readApi(page, `/runs/${runA}/reports`)).find(item => item.handle === value.handle);
      assert.ok(listed, "created report not in the backend report list");
      assert.equal(listed.result_handle, confirmed.handle);
      assert.equal(listed.analysis_type, "residue_numbering");
      return value;
    });
    maps.report = created.handle;
    const library = page.getByRole("region", { name: "보고서 보관함", exact: true });
    const reports = library.getByRole("region", { name: "저장된 보고서", exact: true });
    const content = library.getByRole("region", { name: "선택한 항목 내용", exact: true });
    await rec_.step("F02-listed", cases, "The report list of the same tab shows 잔기 번호 대응 보고서; click it", async () => {
      const row = reports.locator("li button").filter({ hasText: created.handle });
      await row.waitFor({ timeout: 30000 });
      const kind = clean(await row.locator(".mw-library-kind").textContent());
      await row.click();
      const pre = content.getByLabel(`저장된 보고서 ${created.handle}`, { exact: true });
      await pre.waitFor({ timeout: 30000 });
      return { kind, text: await pre.textContent() };
    }, async value => {
      assert.equal(value.kind, "잔기 번호 대응 보고서");
      const saved = await readApi(page, `/runs/${runA}/reports/selected?handle=${enc(created.handle)}`);
      assert.equal(value.text, saved.markdown);
      assert.ok(value.text.includes("잔기 번호 대응 보고서"));
      return { kind: value.kind, markdownSha256: sha(Buffer.from(value.text)) };
    });
    for (const [label, format] of [["Markdown 다운로드", "markdown"], ["JSON 다운로드", "json"]]) {
      const route = `/runs/${runA}/reports/download?handle=${enc(created.handle)}&format=${format}`;
      await rec_.step(`F03-download-${format}`, cases, `Click ${label}; bytes equal the backend bytes`, () =>
        downloadByClick(rec_.app, content.getByRole("link", { name: label, exact: true })), async downloaded => {
        const bytes = fs.readFileSync(downloaded.downloaded);
        const saved = await readBytes(page, route);
        assert.equal(sha(bytes), sha(saved), "downloaded bytes differ from the backend bytes");
        const url = new URL(downloaded.url);
        assert.equal(`${url.pathname}${url.search}`, `/api${route}`);
        return { route, sha256: sha(bytes), backendSha256: sha(saved), bytes: bytes.length };
      });
    }
  });

  // ---- e: prepared structure (existing structure-tab 전처리) → map
  await rec_.part("prepared", ["N-prepared"], async () => {
    const cases = ["N-prepared"];
    const prepared = await rec_.step("E01-prepare", [], "Click 구조 분석, 전처리 (displayed default policies)", async () => {
      await selectTab(page, "구조 분석");
      return prepareManual(page);
    }, async value => value);
    evidence.handles.prepared = prepared.prepared;
    const made = await rec_.step("E02-map", cases, "Click 지식·보고서, choose the prepared structure, chain A, confirm 1MQ4, 실행", async () => {
      await openKnowledge(page);
      await chooseStructure(page, prepared.prepared);
      await testId(page, "numbering-chain-A").check();
      const hint = clean(await testId(page, "numbering-pdb-hint").textContent());
      await testId(page, "numbering-pdb-confirm").check();
      await waitFor(page, async () => (await testId(page, "numbering-accession-A").textContent()).includes(ACCESSION) ? true : null,
        "SIFTS prefill (prepared)", 30000);
      const result = await runMap(page, runA);
      return { ...result, hint, summary: await chainSummary(page, "A"), count: await filterCount(page) };
    }, async value => {
      const listed = (await backendMaps(page, runA)).rows.find(row => row.handle === value.handle);
      assert.equal(listed.structure, prepared.prepared);
      assert.equal(listed.structure_kind, "prepared_structure");
      assert.ok(listed.counts.mapped > 0, JSON.stringify(listed.counts));
      assert.equal(value.count.total, listed.counts.mapped + listed.counts.unmapped + listed.counts.conflict);
      assert.ok(value.hint.includes("1MQ4"), value.hint);
      return { handle: value.handle, counts: listed.counts, crossCheck: value.summary.crossCheck, summary: value.summary.text };
    });
    maps.prepared = made.handle;
  });

  // ---- i: read failure (labeled 503 fixture on one request) → 다시 시도 recovers
  await rec_.part("read-retry", ["N-read-retry"], async () => {
    const cases = ["N-read-retry"];
    for (const [name, pathname, areaName, retry] of [
      ["snapshots", "/api/reference/snapshots", "snapshots", "numbering-snapshots-retry"],
      ["maps", `/api/runs/${runA}/numbering_maps`, "maps", "numbering-maps-retry"]]) {
      await selectTab(page, "구조 분석");
      const faulted = [];
      let armed = true;
      const matcher = url => new URL(url).pathname === pathname;
      const handler = route => {
        if (armed && route.request().method() === "GET") {
          armed = false; // exactly one faulted request
          faulted.push({ at: Date.now(), path: new URL(route.request().url()).pathname });
          return route.fulfill({ status: 503, contentType: "application/json",
            body: JSON.stringify({ detail: { error: "qa_read_fault", message: FAULT_LABEL } }) });
        }
        return route.continue();
      };
      await page.route(matcher, handler);
      if (!evidence.fixtureLabels.includes(FAULT_LABEL)) evidence.fixtureLabels.push(FAULT_LABEL);
      try {
        await rec_.step(`I01-${name}-fault`, cases, `Fault one ${pathname} read, click 지식·보고서: ${areaName} area fails with a retry`, async () => {
          await openKnowledge(page);
          await waitArea(page, areaName, "failure", 30000);
          return { alert: clean(await area(page, areaName).locator('[role="alert"]').textContent()), faulted: [...faulted],
            retry: await testId(page, retry).count(), others: { snapshots: await areaState(page, "snapshots"), maps: await areaState(page, "maps") } };
        }, async value => {
          assert.ok(value.alert.includes(FAULT_LABEL), value.alert);
          assert.equal(value.retry, 1);
          assert.equal(value.faulted.length, 1);
          return value;
        });
        await rec_.step(`I02-${name}-retry`, cases, "Click 다시 시도: the area reads again", async () => {
          await testId(page, retry).click();
          await waitArea(page, areaName, "ready", 30000);
          return { hash: areaName === "snapshots" ? await testId(page, "numbering-set-hash").getAttribute("title") : null,
            buttons: await mapButtons(page), backend: await backendMaps(page, runA) };
        }, async value => {
          if (areaName === "snapshots") assert.equal(value.hash, input["set-hash"]);
          else assert.deepEqual(value.buttons.map(item => item.handle), value.backend.rows.map(row => row.handle));
          return { hash: value.hash, maps: value.buttons.length, faultedTotal: faulted.length };
        });
      } finally {
        armed = false;
        await page.unroute(matcher, handler);
      }
    }
  });

  // ---- h: run switch (only the new run's maps) and a held late response of the previous run
  const runB = await rec_.part("run-switch", ["N-run-switch"], async () => {
    const cases = ["N-run-switch"];
    const id = await rec_.step("H01-new-run", [], "Click 구조 분석 → 새 run (run B), upload 1MQ4", async () => {
      await selectTab(page, "구조 분석");
      const run = await newRun(page);
      const up = await uploadLoad(page, STRUCTURE);
      return { run, handle: up.handle };
    }, async value => value);
    evidence.runs.B = id.run;
    await rec_.step("H02-map-b", cases, "Click 지식·보고서: run A's maps absent; make one run B map (O14965 picked)", async () => {
      await openKnowledge(page);
      await waitArea(page, "maps", "ready");
      const before = await mapButtons(page);
      await chooseStructure(page, id.handle);
      await testId(page, "numbering-chain-A").check();
      await pickFromSearch(page, "A", ACCESSION, ACCESSION);
      const result = await runMap(page, id.run);
      return { before, result, after: await mapButtons(page), text: clean(await panel(page).textContent()) };
    }, async value => {
      const aHandles = (await backendMaps(page, runA)).rows.map(row => row.handle);
      const bHandles = (await backendMaps(page, id.run)).rows.map(row => row.handle);
      assert.deepEqual(value.before, [], "run A maps shown for run B");
      assert.deepEqual(value.after.map(item => item.handle), bHandles);
      for (const handle of aHandles) assert.ok(!value.text.includes(handle), `run A map shown: ${handle}`);
      maps.runB = value.result.handle;
      return { runBMaps: bHandles, runAMapsAbsent: aHandles.length };
    });
    return id.run;
  });

  if (runB) await rec_.part("late-response", ["N-late-response", "N-run-switch"], async () => {
    const cases = ["N-late-response", "N-run-switch"];
    const held = [];
    let holding = true;
    const matcher = url => new URL(url).pathname === `/api/runs/${runA}/numbering_maps`;
    const handler = async route => {
      if (!holding || route.request().method() !== "GET") return route.continue();
      const response = await route.fetch();
      held.push({ route, response, at: Date.now() });
    };
    await page.route(matcher, handler);
    evidence.fixtureLabels.push(HOLD_LABEL);
    try {
      await rec_.step("H03-held", cases, "Hold run A's map-list responses; choose run A in 저장된 run, click 지식·보고서 (list loading)", async () => {
        await chooseRun(page, runA);
        await openKnowledge(page);
        await waitFor(page, async () => held.length >= 1 ? true : null, "held run A map list", 30000);
        return { held: held.length, maps: await areaState(page, "maps") };
      }, async value => { assert.equal(value.maps, "loading"); return value; });
      await rec_.step("H04-switch-b", cases, "Click 구조 분석, choose run B, click 지식·보고서: run B's maps only", async () => {
        await chooseRun(page, runB);
        await openKnowledge(page);
        await waitArea(page, "maps", "ready");
        return { buttons: await mapButtons(page) };
      }, async value => {
        assert.deepEqual(value.buttons.map(item => item.handle), (await backendMaps(page, runB)).rows.map(row => row.handle));
        return value;
      });
      await rec_.step("H05-release", cases, "Release run A's held responses: run B's list stays, no run A map appears", async () => {
        holding = false;
        const released = [];
        for (const item of held) {
          try { await item.route.fulfill({ response: item.response }); released.push({ delivered: true }); }
          catch (error) { released.push({ delivered: false, reason: String(error).slice(0, 160) }); }
        }
        await page.waitForTimeout(2500);
        return { released, buttons: await mapButtons(page), text: clean(await panel(page).textContent()), run: await globalRun(page) };
      }, async value => {
        const aHandles = (await backendMaps(page, runA)).rows.map(row => row.handle);
        assert.deepEqual(value.buttons.map(item => item.handle), (await backendMaps(page, runB)).rows.map(row => row.handle));
        for (const handle of aHandles) assert.ok(!value.text.includes(handle), `late run A map shown: ${handle}`);
        assert.equal(value.run, runB);
        return { released: value.released, shown: value.buttons.map(item => item.handle) };
      });
    } finally {
      holding = false;
      for (const item of held) await item.route.fulfill({ response: item.response }).catch(() => undefined);
      await page.unroute(matcher, handler);
    }
  });

  for (const run of [runA, runB].filter(Boolean)) evidence.providerCalls.push(await providerCalls(page, run));
}

/** After the runner activated a marked fixture set: every earlier map shows 이전 스냅샷 기준 (list and detail). */
async function modeStale(session, input, rec_, evidence) {
  const { page } = session;
  const runs = input.runs.split(",").filter(Boolean);
  runs.forEach((run, index) => { evidence.runs[String.fromCharCode(65 + index)] = run; });
  await waitForBoot(page);
  for (const [index, run] of runs.entries()) {
    await rec_.step(`G0${index + 1}-stale-${index ? "b" : "a"}`, ["N-stale"],
      `Choose run ${run} in 저장된 run, click 지식·보고서: new set hash; every map shows 이전 스냅샷 기준`, async () => {
        await chooseRun(page, run);
        await openKnowledge(page);
        await waitArea(page, "snapshots", "ready");
        await waitArea(page, "maps", "ready");
        const buttons = await mapButtons(page);
        await panel(page).locator("button.mw-numbering-map").first().click();
        await waitArea(page, "detail", ["ready", "scientific_null"]);
        return { hash: await testId(page, "numbering-set-hash").getAttribute("title"),
          snapshotText: clean(await area(page, "snapshots").textContent()), buttons,
          detailBadge: await area(page, "detail").locator(".mw-numbering-badge--stale").count(),
          backend: await backendMaps(page, run), api: await readApi(page, "/reference/snapshots") };
      }, async value => {
        assert.equal(value.api.set_hash, input["set-hash"]);
        assert.notEqual(input["set-hash"], input["previous-set-hash"]);
        assert.equal(value.hash, input["set-hash"]);
        if (input.marker) assert.ok(value.snapshotText.includes(input.marker), `marker not shown: ${value.snapshotText}`);
        assert.equal(value.backend.active_set_hash, input["set-hash"]);
        assert.ok(value.buttons.length > 0);
        assert.deepEqual(value.buttons.map(item => item.handle), value.backend.rows.map(row => row.handle));
        for (const row of value.backend.rows) {
          assert.equal(row.set_hash, input["previous-set-hash"], `${row.handle} was made under another set`);
          assert.equal(row.stale_snapshot, true);
        }
        for (const button of value.buttons) {
          assert.equal(button.stale, "true");
          assert.ok(button.text.includes("이전 스냅샷 기준"), button.text);
        }
        assert.equal(value.detailBadge, 1);
        return { maps: value.buttons.map(item => item.handle), activeSet: value.api.set_hash, previousSet: input["previous-set-hash"] };
      });
    evidence.providerCalls.push(await providerCalls(page, run));
  }
}

// ------------------------------------------------------------------ main
const RUNNERS = { empty: modeEmpty, main: modeMain, stale: modeStale };

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const evidence = { schema: "m15_numbering_evidence@1", mode: input.mode, runs: {}, inputs: [],
    handles: { maps: {} }, fixtureLabels: [], providerCalls: [], partFailures: [], startedAt: new Date().toISOString() };
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
  fs.writeFileSync(path.join(input.artifacts, "numbering-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  fs.writeFileSync(path.join(input.artifacts, "numbering-requests.jsonl"), log.map(row => JSON.stringify(row)).join("\n") + "\n");
  const harness = Object.fromEntries(["numbering-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m15_case_ledger_row@1", mode: input.mode, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", cases, runId: evidence.runs.A ?? null, runs: evidence.runs,
    handles: evidence.handles, inputs: evidence.inputs, fixtureLabels: evidence.fixtureLabels, buildId: buildId(), harness,
    setHash: input["set-hash"], previousSetHash: input["previous-set-hash"],
    offscreen: proof, externalRequestCount: proof ? proof.nonLoopbackRequests : null, providerCalls: evidence.providerCalls,
    providerCallsZero: providerZero, partFailures: evidence.partFailures, error: evidence.error,
    evidenceFile: path.basename(rec_.file), startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, runs: evidence.runs, cases }) + "\n");
  if (error) process.stderr.write(`numbering-flow ${input.mode} failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`numbering-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main };
