"use strict";

// M12 fpocket pocket-panel offscreen QA harness (real Electron offscreen renderer, real Mol*).
// Every product interaction is a Playwright locator mouse/keyboard/file-chooser input. Observations are
// read-only: viewer data-pocket-* attributes, window.__protviewQaSnapshot()/__protviewQaChemical() and
// loopback GETs. Labeled renderer-route fixtures (503 on one read, held real responses) never create a
// scientific object and are listed in the ledger row. Nothing here supplies or adjusts a scientific value:
// every expected number is read from the stored pocket_set through the product API.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { launchOffscreen, capture, status, downloadByClick } = require("./driver.cjs");

const REPO = path.resolve(__dirname, "../../..");
const FIXTURES = path.join(REPO, "backend/tests/fixtures");
const PUBLIC_1HSG = path.join(FIXTURES, "public_1hsg.cif");
const DERIVED = path.join(FIXTURES, "derived_1hsg_first10_fixture.cif");
const DERIVED_PROVENANCE = path.join(FIXTURES, "derived_1hsg_first10_fixture.provenance.json");
const MODES = ["positive", "empty", "invalid", "unavailable", "cancel", "reopen", "report-download", "source-race",
  "overlay-disables", "comparison-block", "distance-with-overlay", "chemical-workspace", "replay"];
const NEW_RUN_MODES = ["positive", "empty", "invalid", "unavailable", "cancel"];
const EXISTING_SET_MODES = ["reopen", "report-download", "source-race", "overlay-disables", "comparison-block",
  "distance-with-overlay", "replay"];
const RESIDUE_FIELDS = ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"];
const OVERLAY_REASON = "포켓 오버레이를 지우면 다시 사용할 수 있습니다";
const COMPARISON_REASON = "두 구조 비교 중에는 포켓 검출과 오버레이를 사용할 수 없습니다";
const CONTEXT_CLEARED = "표시 구조가 바뀌어 포켓 오버레이를 지웠습니다";
const CHEMICAL_REASON = "화학 구조는 M8 프롬프트, M9 보기·PNG, M10 측정·비교 입력으로 쓸 수 없습니다";
const SCIENCE_EVENT_TYPES = new Set(["object_created", "tool_called", "tool_succeeded", "tool_failed", "job_submitted",
  "job_terminal", "budget_reserved", "approval_requested", "approval_resolved"]);

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const shaFile = file => sha(fs.readFileSync(file));
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: shaFile(file) } : { path: file ?? null, missing: true };
const shortHandle = handle => handle.split("/").at(-1).slice(0, 12);
const residueKey = residue => JSON.stringify(RESIDUE_FIELDS.map(field => residue[field]));

function provenanceLabel(name) {
  if (name === "public_1hsg.cif") return "public PDB entry 1HSG (repository fixture); fpocket candidates on it are not binding-site evidence";
  if (name === "derived_1hsg_first10_fixture.cif") return JSON.parse(fs.readFileSync(DERIVED_PROVENANCE, "utf8")).label;
  if (name.startsWith("m12-synthetic-")) return "labeled synthetic M12 invalid-input control (scripts/m12_qa_inputs.py); not an observed structure";
  if (name === "m12-invalid-cases.json") return "manifest of labeled synthetic M12 invalid-input controls (scripts/m12_qa_inputs.py)";
  return "unlabeled file";
}

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, run: null, set: null, otherRun: null,
    fixture: null, variants: null, expectCapability: null, result: null, report: null, expectMarkdownSha: null,
    expectJsonSha: null, fixtureLabel: null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode)) throw new Error(
    `Usage: pocket-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> [--url http://127.0.0.1:3000] ` +
    "[--fixture <cif/pdb>] [--run run_... --set obj://...pocket_set...] [--other-run run_...] " +
    "[--variants <dir from scripts/m12_qa_inputs.py>] [--expect-capability not_installed|unreviewed_build] " +
    "[--result <chemical result handle>] [--report <pocket report handle> --expect-markdown-sha <sha> --expect-json-sha <sha>]. " +
    "Full sequence: scripts/m12_offscreen_acceptance.py.");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  if (value.run) assert.match(value.run, /^run_[a-f0-9]+$/);
  if (value.otherRun) assert.match(value.otherRun, /^run_[a-f0-9]+$/);
  if (NEW_RUN_MODES.includes(value.mode)) assert.equal(value.run, null, `--mode ${value.mode} creates its own run`);
  if (EXISTING_SET_MODES.includes(value.mode)) assert.ok(value.run && value.set, `--mode ${value.mode} needs --run and --set`);
  if (value.mode === "source-race") assert.ok(value.otherRun, "--mode source-race needs --other-run");
  if (value.mode === "chemical-workspace") assert.ok(value.run && value.result, "--mode chemical-workspace needs --run --result");
  if (value.mode === "unavailable") assert.ok(["not_installed", "unreviewed_build"].includes(value.expectCapability),
    "--mode unavailable needs --expect-capability not_installed|unreviewed_build");
  if (value.mode === "replay") assert.ok(value.report && value.expectMarkdownSha && value.expectJsonSha,
    "--mode replay needs --report --expect-markdown-sha --expect-json-sha");
  if (value.mode === "invalid") {
    assert.ok(value.variants, "--mode invalid needs --variants (scripts/m12_qa_inputs.py output)");
    value.variants = path.resolve(value.variants);
    assert.ok(fs.statSync(path.join(value.variants, "m12-invalid-cases.json"), { throwIfNoEntry: false })?.isFile());
  }
  value.fixture = path.resolve(value.fixture ?? (value.mode === "empty" ? DERIVED : PUBLIC_1HSG));
  assert.ok(fs.statSync(value.fixture, { throwIfNoEntry: false })?.isFile(), `fixture not found: ${value.fixture}`);
  value.artifacts = path.resolve(value.artifacts);
  value.url = new URL(value.run ? `/?run=${value.run}` : "/", value.url).toString();
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
const scienceEvents = async (page, run) => (await runEvents(page, run)).filter(event => SCIENCE_EVENT_TYPES.has(event.type))
  .map(event => ({ seq: event.seq, type: event.type, kind: event.kind ?? null, handle: event.handle ?? null,
    job_id: event.job_id ?? event.job?.job_id ?? null }));
async function pocketJobs(page, run) {
  return (await readApi(page, `/runs/${run}/jobs`)).filter(job => job.protocol_id === "fpocket_detect_v1");
}
async function geometry(page, run, handle, rank) {
  return readApi(page, `/runs/${run}/pockets/geometry?handle=${encodeURIComponent(handle)}&rank=${rank}`);
}
async function summaryOf(page, run, handle) {
  return readApi(page, `/runs/${run}/pockets/result?handle=${encodeURIComponent(handle)}`);
}
/** Read-only viewer observation: data-pocket-* attributes of the visible viewer plus the QA bridges. */
async function observe(page) {
  return page.evaluate(() => {
    const nodes = [...document.querySelectorAll(".mw-molstar[data-pocket-overlay]")]
      .filter(node => node.getClientRects().length > 0);
    const node = nodes[0] ?? null;
    const chemical = typeof window.__protviewQaChemical === "function" ? window.__protviewQaChemical() : null;
    const main = typeof window.__protviewQaSnapshot === "function" ? window.__protviewQaSnapshot() : null;
    return { viewerNodes: nodes.length, data: node ? { ...node.dataset } : null,
      native: chemical ? chemical.native : main, chemical: chemical && { runId: chemical.runId,
        sourceHandle: chemical.sourceHandle, resultHandle: chemical.resultHandle, catalogReady: chemical.catalogReady,
        selectedRowId: chemical.selectedRowId, annotation: chemical.native?.chemicalAnnotation ?? null } };
  });
}
async function waitObserve(page, predicate, label, timeout = 45000) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    last = await observe(page);
    try { if (predicate(last)) return last; } catch { /* keep polling */ }
    await page.waitForTimeout(100);
  }
  throw new Error(`${label}: timed out; last=${JSON.stringify({ data: last?.data,
    pocketOverlay: last?.native?.pocketOverlay ?? null, sourceHandle: last?.native?.sourceHandle })}`);
}
const overlayApplied = (obs, set, rank) => obs.data?.pocketOverlay === "applied" &&
  obs.data.pocketSetHandle === set && Number(obs.data.pocketRank) === rank && !!obs.native?.pocketOverlay &&
  obs.native.pocketOverlay.rank === rank && obs.native.pocketOverlay.setHandle === set;
const overlayNone = obs => obs.data?.pocketOverlay === "none" && !obs.native?.pocketOverlay;

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

// ------------------------------------------------------------------ evidence
function recorder(session, input, evidence) {
  const { app, page, artifacts } = session;
  const file = path.join(artifacts, `pocket-${input.mode}.jsonl`);
  const append = row => fs.appendFileSync(file, JSON.stringify(row) + "\n");
  let count = 0;
  async function step(caseId, description, action, check) {
    const started = Date.now();
    const before = await status(app, page);
    let result;
    try {
      result = await action();
      const assertion = await check(result);
      const proof = await capture(app, page, artifacts, caseId);
      assert.equal(proof.status.blockedRequests.length, 0, "renderer attempted a non-loopback request");
      assert.equal(proof.status.offscreen, true);
      append({ caseId, status: "pass", description, assertion,
        blockedRequests: proof.status.blockedRequests.length, paintCount: proof.status.paintCount,
        screenshot: fileRecord(proof.screenshot), paint: fileRecord(proof.paint.path),
        pocketObservation: (await observe(page)).data, durationMs: Date.now() - started,
        beforePaintCount: before.paintCount });
      count++;
      return result;
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* keep the primary failure */ }
      append({ caseId, status: "fail", description, error: String(error.stack ?? error),
        actionResult: result === undefined ? null : result, screenshot: proof && fileRecord(proof.screenshot),
        paint: proof && fileRecord(proof.paint.path), pocketObservation: (await observe(page).catch(() => null))?.data ?? null,
        durationMs: Date.now() - started });
      throw error;
    }
  }
  return { step, append, file, steps: () => count, evidence };
}

// ------------------------------------------------------------------ shared UI paths (real input only)
const panelOf = (page, kind = "main") => page.locator(`section[data-pocket-panel="${kind}"]`);
async function waitForBoot(page) {
  const hasRuns = (await readApi(page, "/runs")).length > 0;
  await page.waitForFunction(existing => {
    const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "새 run");
    const selected = new URL(location.href).searchParams.get("run");
    return !!button && !button.disabled && (existing ? /^run_/.test(selected ?? "")
      : document.body.textContent?.includes("현재 사용 불가"));
  }, hasRuns, { timeout: 30000 });
}
async function newRun(page) {
  await waitForBoot(page);
  const previous = new URL(page.url()).searchParams.get("run");
  await page.getByRole("button", { name: "새 run", exact: true }).click();
  await page.waitForFunction(old => {
    const current = new URL(location.href).searchParams.get("run");
    const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "새 run");
    return /^run_[a-f0-9]+$/.test(current ?? "") && current !== old && !!button && !button.disabled;
  }, previous, { timeout: 30000 });
  return new URL(page.url()).searchParams.get("run");
}
async function viewerReady(page, predicate = () => true, timeout = 60000) {
  return waitObserve(page, obs => obs.native?.ready === true && !!obs.native.sourceHandle && obs.native.catalogReady === true &&
    predicate(obs.native), "Mol* viewer ready", timeout);
}
async function uploadLoadPrepare(page, run, file) {
  await page.getByRole("tab", { name: /^run/i }).click();
  const chooser = page.waitForEvent("filechooser", { timeout: 30000 });
  await page.locator('input[type="file"]').first().click();
  await (await chooser).setFiles(file);
  await page.getByRole("button", { name: "구조 불러오기" }).waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: "구조 불러오기" }).click();
  const loaded = await viewerReady(page, native => native.sourceHandle.includes("/structure/"));
  await page.getByRole("button", { name: "전처리", exact: true }).waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: "전처리", exact: true }).click();
  const panel = panelOf(page);
  const select = panel.getByRole("combobox", { name: "포켓 검출 소스" });
  await page.waitForFunction(() => [...document.querySelectorAll('section[data-pocket-panel="main"] select option')]
    .some(option => option.value.includes("/prepared_structure/")), null, { timeout: 60000 });
  const prepared = await select.inputValue();
  assert.match(prepared, /\/prepared_structure\//);
  const events = await runEvents(page, run);
  assert.ok(events.some(event => event.type === "object_created" && event.handle === prepared),
    "Pocket source option is not a prepared_structure object of this run");
  const shown = await viewerReady(page, native => native.sourceHandle === prepared);
  return { original: loaded.native.sourceHandle, prepared, displayed: shown.native.sourceHandle,
    upload: { name: path.basename(file), ...fileRecord(file), provenance: provenanceLabel(path.basename(file)) } };
}
async function preflightFor(page, run, source, chains = []) {
  const query = chains.length ? `&${chains.map(chain => `chains=${encodeURIComponent(chain)}`).join("&")}` : "";
  return readApi(page, `/runs/${run}/pockets/preflight?structure=${encodeURIComponent(source)}${query}`);
}
async function waitPreflightText(panel, selectedChains) {
  await panel.getByLabel("포켓 입력 확인").getByText(`선택 체인 ${selectedChains.join(", ")} ·`, { exact: false })
    .waitFor({ timeout: 30000 });
}
/** Click detection, approve when the product asks, and wait for the durable terminal job. */
async function detect(page, panel, run, { approve = true } = {}) {
  const before = (await pocketJobs(page, run)).map(job => job.job_id);
  const button = panel.getByRole("button", { name: "포켓 검출 실행" });
  await button.waitFor({ timeout: 30000 });
  const enabledBy = Date.now() + 60000;
  while (!(await button.isEnabled())) {
    if (Date.now() > enabledBy) throw new Error(`포켓 검출 실행 stayed disabled: ${await panel.locator("[data-pocket-detect-reason]").innerText().catch(() => "")}`);
    await page.waitForTimeout(100);
  }
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
  if (approvalSeen && !approve) return { job, approvalSeen, previousJobs: before };
  if (approvalSeen) await approval.click();
  await panel.locator('[data-pocket-job-status="done"], [data-pocket-job-status="failed"], [data-pocket-job-status="cancelled"], [data-pocket-job-status="interrupted"]')
    .first().waitFor({ timeout: 240000 });
  const durable = await readApi(page, `/runs/${run}/jobs/${job.job_id}`);
  assert.equal(durable.status, "done", `pocket job did not finish: ${JSON.stringify(durable.failure ?? durable.status)}`);
  const set = durable.artifacts?.pocket_set;
  assert.match(set ?? "", /\/pocket_set\//);
  await panel.locator("[data-pocket-total-count], [data-pocket-null-result]").first().waitFor({ timeout: 60000 });
  return { job: durable, set, approvalSeen, previousJobs: before };
}
function descriptorCellsMatch(rowText, pocket) {
  for (const [key, descriptor] of Object.entries(pocket.descriptors)) {
    const text = descriptor.native_text ?? String(descriptor.value);
    assert.ok(rowText.includes(text), `rank ${pocket.rank} ${key}: displayed row lacks stored value ${text}`);
  }
  return true;
}
async function assertSummaryTable(panel, summary, expectedShown) {
  const shown = Number(await panel.locator("[data-pocket-displayed-count]").getAttribute("data-pocket-displayed-count"));
  const total = Number(await panel.locator("[data-pocket-total-count]").getAttribute("data-pocket-total-count"));
  assert.equal(total, summary.total_count, "displayed total_count differs from stored pocket_set");
  assert.equal(shown, expectedShown, "displayed_count differs from top-k rule");
  const rows = panel.getByRole("region", { name: "fpocket 후보 공동 목록" }).locator("tbody tr");
  assert.equal(await rows.count(), shown);
  const ranks = [];
  for (let i = 0; i < shown; i++) {
    const row = rows.nth(i);
    const rank = Number(await row.getAttribute("data-pocket-rank"));
    const pocket = summary.pockets[i];
    assert.equal(rank, pocket.rank, "table row order differs from stored native rank order");
    descriptorCellsMatch(await row.innerText(), pocket);
    ranks.push(rank);
  }
  return { displayed: shown, total, ranks };
}
/** Stored spheres vs what Mol* holds: centers are float32 GPU texture values (exact float32 of the stored
 *  double); radii are Mol*'s packed centi-Ångström size (exact integer/100 of the stored radius). */
function compareSpheres(obs, geo) {
  const attr = JSON.parse(obs.data.pocketSpheres);
  const native = obs.native.pocketOverlay;
  assert.equal(Number(obs.data.pocketSphereCount), geo.spheres.length, "sphere count differs from stored pocket");
  assert.equal(attr.length, geo.spheres.length);
  assert.equal(native.centers.length, geo.spheres.length);
  let maxCenterDelta = 0, maxRadiusDelta = 0, radiiAtStoredPrecision = 0;
  geo.spheres.forEach((sphere, i) => {
    const stored = [sphere.x_A, sphere.y_A, sphere.z_A];
    stored.forEach((value, axis) => {
      assert.equal(attr[i][axis], Math.fround(value), `sphere ${i + 1} axis ${axis}: Mol* ${attr[i][axis]} vs stored ${value}`);
      assert.equal(native.centers[i][axis], attr[i][axis]);
      maxCenterDelta = Math.max(maxCenterDelta, Math.abs(attr[i][axis] - value));
    });
    const packed = Math.round(sphere.radius_A * 100) / 100;
    assert.equal(attr[i][3], packed, `sphere ${i + 1} radius: Mol* ${attr[i][3]} vs stored ${sphere.radius_A}`);
    assert.equal(native.radii[i], attr[i][3]);
    if (packed === sphere.radius_A) radiiAtStoredPrecision++;
    maxRadiusDelta = Math.max(maxRadiusDelta, Math.abs(attr[i][3] - sphere.radius_A));
  });
  assert.equal(obs.data.pocketPickable, "false");
  assert.equal(native.pickable, false);
  assert.equal(Number(obs.data.pocketLiningAtomCount), geo.lining_atoms.atoms.length);
  assert.equal(Number(obs.data.pocketLiningResidueCount), geo.lining_residues.length);
  return { sphereCount: geo.spheres.length, comparedSpheres: geo.spheres.length, maxCenterDeltaFloat32_A: maxCenterDelta,
    maxRadiusDelta_A: maxRadiusDelta, radiiExactlyAtStoredPrecision: radiiAtStoredPrecision,
    liningAtoms: geo.lining_atoms.atoms.length, liningResidues: geo.lining_residues.length,
    liningSitesInMolstar: native.liningNativeSourceIndices.length, rule: "center === Math.fround(stored); radius === round(stored*100)/100" };
}
function focusMatches(obs, geo) {
  const target = obs.native.pocketOverlay.focusedTarget;
  assert.ok(Array.isArray(target), "pocket focus did not settle on the display center");
  const center = [geo.display_center.x_A, geo.display_center.y_A, geo.display_center.z_A];
  const delta = Math.hypot(...center.map((value, i) => value - target[i]));
  assert.ok(delta <= 1e-3, `camera target ${target} differs from stored display center ${center}`);
  const camera = obs.native.nativeCamera.target;
  assert.ok(Math.hypot(...center.map((value, i) => value - camera[i])) <= 1e-3, "native camera target is not the pocket center");
  return { displayCenter: center, focusedTarget: target, deltaA: delta, cameraPosition: obs.native.nativeCamera.position };
}
async function openHistory(page, panel) {
  const summary = panel.locator("details[aria-label='포켓 기록'] > summary");
  const open = await panel.locator("details[aria-label='포켓 기록']").evaluate(node => node.open);
  if (!open) await summary.click();
  return summary.innerText();
}
async function reopenSet(page, panel, run, set) {
  await openHistory(page, panel);
  const button = panel.getByRole("button", { name: `포켓 결과 다시 열기 ${shortHandle(set)}` });
  await button.waitFor({ timeout: 30000 });
  const read = page.waitForResponse(response => response.request().method() === "GET" &&
    new URL(response.url()).pathname === `/api/runs/${run}/pockets/result`, { timeout: 30000 });
  await button.click();
  assert.equal((await read).status(), 200);
  await panel.locator("[data-pocket-total-count], [data-pocket-null-result]").first().waitFor({ timeout: 30000 });
  return summaryOf(page, run, set);
}
async function selectRank(page, panel, run, set, rank) {
  const geoRead = page.waitForResponse(response => response.request().method() === "GET" &&
    new URL(response.url()).pathname === `/api/runs/${run}/pockets/geometry`, { timeout: 30000 });
  await panel.getByRole("button", { name: `포켓 rank ${rank} 선택` }).click();
  assert.equal((await geoRead).status(), 200);
  const obs = await waitObserve(page, value => overlayApplied(value, set, rank), `overlay rank ${rank} applied`, 60000);
  await panel.locator('[data-pocket-overlay-status="applied"]').waitFor({ timeout: 30000 });
  return obs;
}
async function selectAndCompare(page, panel, run, set, rank) {
  const obs = await selectRank(page, panel, run, set, rank);
  const geo = await geometry(page, run, set, rank);
  const settled = await waitObserve(page, value => overlayApplied(value, set, rank) &&
    Array.isArray(value.native.pocketOverlay.focusedTarget) && value.native.cameraTransitioning === false,
  `overlay rank ${rank} focus settled`, 30000);
  return { rank, spheres: compareSpheres(settled, geo), focus: focusMatches(settled, geo),
    liningVisible: obs.data.pocketLiningVisible, spheresVisible: obs.data.pocketSpheresVisible,
    geometrySha256: sha(Buffer.from(JSON.stringify(geo))) };
}
async function holdRoute(page, pattern, label) {
  let release, started;
  const gate = new Promise(resolve => { release = resolve; });
  const startedGate = new Promise(resolve => { started = resolve; });
  const delivered = [];
  const handler = async route => {
    let response;
    try { response = await route.fetch(); } catch (error) { started({ error: String(error) }); return; }
    started({ status: response.status(), url: route.request().url() });
    await gate;
    try { await route.fulfill({ response }); delivered.push("fulfilled"); }
    catch (error) { delivered.push(`browser_cancelled: ${String(error).slice(0, 200)}`); }
  };
  await page.route(pattern, handler);
  return { label, started: startedGate, release: () => release(), delivered,
    remove: () => page.unroute(pattern, handler) };
}
async function failOnce(page, pattern, label) {
  let hits = 0;
  const handler = async route => {
    hits++;
    await route.fulfill({ status: 503, contentType: "application/json",
      body: JSON.stringify({ detail: { error: "qa_injected_read_503", message: `Labeled QA read fault: ${label}` } }) });
  };
  await page.route(pattern, handler);
  return { hits: () => hits, remove: () => page.unroute(pattern, handler) };
}
async function historyStepClick(page, tool) {
  await page.getByRole("tab", { name: /^run/i }).click();
  const row = page.locator(".mw-step").filter({ hasText: tool }).first();
  await row.waitFor({ timeout: 30000 });
  await row.click();
}
async function withoutJobPosts(page, run, work) {
  const posts = [];
  const listener = request => {
    if (request.method() === "POST" && /\/(jobs|commands|method_reports)(\/|\?|$)/.test(new URL(request.url()).pathname))
      posts.push(new URL(request.url()).pathname);
  };
  page.on("request", listener);
  const before = await scienceEvents(page, run);
  try { await work(); } finally { page.off("request", listener); }
  const after = await scienceEvents(page, run);
  return { posts, scienceEventsBefore: before.length, scienceEventsAfter: after.length, unchanged:
    JSON.stringify(before) === JSON.stringify(after) };
}

// ------------------------------------------------------------------ report validation
function validateReport(manifest, markdown, summary, geometries, set) {
  assert.equal(manifest.schema, "method_report_manifest@1");
  assert.equal(manifest.analysis_type, "pocket_detection");
  assert.equal(manifest.result_schema, "pocket_set@1");
  assert.equal(manifest.result_handle, set);
  assert.equal(manifest.total_count, summary.total_count);
  assert.equal(manifest.null_result, summary.null_result);
  assert.equal(manifest.source_handle, summary.source_handle);
  // The renderer escapes Markdown punctuation; compare statements against the unescaped text.
  const plain = markdown.replace(/\\([\\`*_{}\[\]()#+\-.!|>~])/g, "$1");
  assert.ok(plain.includes(manifest.evidence_statement), "report Markdown lacks the evidence statement");
  assert.ok(manifest.evidence_statement.includes("not binding-site, affinity or druggability evidence"));
  const byRank = new Map(summary.pockets.map(pocket => [pocket.rank, pocket]));
  const counts = {};
  for (const claim of manifest.claims) {
    counts[claim.statement_id] = (counts[claim.statement_id] ?? 0) + 1;
    assert.ok(markdown.includes(claim.rendered_value) || plain.includes(claim.rendered_value),
      `markdown lacks rendered claim ${claim.field_path}=${claim.rendered_value}`);
    const pocket = claim.row_selector ? byRank.get(claim.row_selector.rank) : null;
    if (claim.row_selector) assert.ok(pocket, `claim for unknown rank ${claim.row_selector.rank}`);
    if (claim.statement_id === "pocket_count") assert.equal(claim.exact_value, summary.total_count);
    else if (claim.statement_id === "pocket_descriptor") {
      const key = claim.field_path.split(".descriptors.")[1].replace(/\.value$/, "");
      assert.equal(claim.exact_value, pocket.descriptors[key].value, `${claim.field_path}`);
      assert.equal(claim.unit, pocket.descriptors[key].unit);
      assert.equal(claim.source_handle, set);
    } else if (claim.statement_id === "lining_residue_count") {
      const geo = geometries.get(pocket.rank);
      assert.equal(claim.exact_value, new Set(geo.lining_residues.map(residueKey)).size);
    } else if (claim.statement_id === "display_center_coordinate") {
      const axis = claim.field_path.split(".display_center.")[1];
      assert.equal(claim.exact_value, pocket.display_center[axis]);
      const geo = geometries.get(pocket.rank);
      const index = { x_A: "x_A", y_A: "y_A", z_A: "z_A" }[axis];
      const mean = geo.spheres.reduce((sum, sphere) => sum + sphere[index], 0) / geo.spheres.length;
      assert.ok(Math.abs(mean - claim.exact_value) <= 1e-9,
        `display center ${axis} ${claim.exact_value} is not the arithmetic mean ${mean} of the stored spheres`);
    } else if (claim.statement_id === "excluded_site_count") {
      assert.equal(claim.exact_value, summary.excluded_counts[claim.field_path.split(".")[1]]);
    } else if (claim.statement_id === "transport_count") {
      assert.equal(claim.exact_value, summary.counts[claim.field_path.split(".")[1]]);
    } else if (claim.statement_id === "quantization") {
      assert.equal(claim.exact_value, summary.quantization[claim.field_path.split(".")[1]]);
    } else assert.fail(`unexpected claim statement ${claim.statement_id}`);
  }
  assert.equal(manifest.pockets.length, summary.pockets.length);
  manifest.pockets.forEach((pocket, i) => {
    assert.equal(pocket.rank, summary.pockets[i].rank);
    assert.deepEqual(pocket.descriptors, summary.pockets[i].descriptors);
    assert.deepEqual(pocket.display_center, summary.pockets[i].display_center);
    assert.deepEqual(pocket.lining_residues, geometries.get(pocket.rank).lining_residues);
  });
  return { claims: manifest.claims.length, claimCounts: counts, pockets: manifest.pockets.length };
}
async function reportDownloads(session, panel, run, set, summary) {
  const { app, page } = session;
  const md = await downloadByClick(app, panel.getByRole("link", { name: "포켓 보고서 Markdown 다운로드" }));
  const js = await downloadByClick(app, panel.getByRole("link", { name: "포켓 보고서 JSON 다운로드" }));
  const href = await panel.getByRole("link", { name: "포켓 보고서 JSON 다운로드" }).getAttribute("href");
  const handle = new URL(href, page.url()).searchParams.get("handle");
  assert.match(handle ?? "", /method_report_manifest/);
  const saved = await readApi(page, `/runs/${run}/reports/selected?handle=${encodeURIComponent(handle)}`);
  const mdBytes = fs.readFileSync(md.downloaded), jsBytes = fs.readFileSync(js.downloaded);
  assert.ok(mdBytes.equals(await readBytes(page, `/runs/${run}/reports/download?handle=${encodeURIComponent(handle)}&format=markdown`)));
  assert.ok(jsBytes.equals(await readBytes(page, `/runs/${run}/reports/download?handle=${encodeURIComponent(handle)}&format=json`)));
  const markdown = mdBytes.toString("utf8");
  const manifest = JSON.parse(jsBytes.toString("utf8"));
  assert.equal(markdown, saved.markdown, "downloaded Markdown differs from the saved report");
  assert.deepEqual(manifest, saved.manifest, "downloaded JSON differs from the saved manifest");
  const geometries = new Map();
  for (const pocket of summary.pockets) geometries.set(pocket.rank, await geometry(page, run, set, pocket.rank));
  const validation = validateReport(manifest, markdown, summary, geometries, set);
  return { handle, markdown: { ...md, sha256: sha(mdBytes) }, json: { ...js, sha256: sha(jsBytes) }, validation };
}

// ------------------------------------------------------------------ modes
async function modePositive(session, input, rec) {
  const { page } = session;
  const { step, evidence } = rec;
  const panel = panelOf(page);
  const run = await step("P01-new-run", "Click 새 run", () => newRun(page), async id => {
    assert.match(id, /^run_/); return { run: id };
  });
  evidence.run = run;
  const sources = await step("P02-upload-prepare", `Choose ${path.basename(input.fixture)}, 구조 불러오기, 전처리`,
    () => uploadLoadPrepare(page, run, input.fixture), async value => value);
  evidence.inputs.push(sources.upload);
  evidence.handles.original = sources.original; evidence.handles.prepared = sources.prepared;
  const cap = (await readApi(page, "/capabilities")).methods.pocket_detection;
  const preflight = await step("P03-capability-preflight", "Observe capability and default-chain preflight", async () => {
    await panel.getByText(`${cap.engine} ${cap.release} · build ${cap.build}`, { exact: false }).waitFor({ timeout: 30000 });
    const value = await preflightFor(page, run, sources.prepared);
    await waitPreflightText(panel, value.selected_chains);
    return value;
  }, async value => {
    assert.equal(cap.available, true, `fpocket capability not ready: ${JSON.stringify(cap)}`);
    assert.equal(value.ready, true);
    assert.ok(value.available_chains.length >= 1);
    assert.equal(await panel.getAttribute("data-pocket-ui-state"), "ready");
    return { capability: { status: cap.status, engine: cap.engine, release: cap.release, build: cap.build },
      selectedChains: value.selected_chains, projected: [value.projected_atom_count, value.projected_residue_count],
      excluded: value.excluded_counts };
  });
  const chains = preflight.selected_chains;
  if (chains.length > 1) {
    const keep = chains.slice(0, -1), dropped = chains.at(-1);
    await step("P04-chain-uncheck", `Uncheck 체인 ${dropped}`, async () => {
      await panel.getByRole("checkbox", { name: `체인 ${dropped}` }).uncheck();
      await waitPreflightText(panel, keep);
    }, async () => {
      const api = await preflightFor(page, run, sources.prepared, keep);
      assert.deepEqual(api.selected_chains, keep);
      assert.equal(await panel.getByRole("checkbox", { name: `체인 ${dropped}` }).isChecked(), false);
      return { selected: keep, projectedAtoms: api.projected_atom_count, unselectedExcluded: api.excluded_counts?.unselected_chain };
    });
    await step("P04-chain-default", "Click 기본 체인으로", async () => {
      await panel.getByRole("button", { name: "기본 체인으로" }).click();
      await waitPreflightText(panel, chains);
    }, async () => {
      for (const chain of chains) assert.equal(await panel.getByRole("checkbox", { name: `체인 ${chain}` }).isChecked(), true);
      assert.equal(await panel.getByRole("button", { name: "기본 체인으로" }).count(), 0);
      return { selected: chains };
    });
    const fault = await failOnce(page, `**/api/runs/${run}/pockets/preflight?*`, "pocket preflight");
    await step("P04-preflight-fault", "Labeled 503 on the preflight read, then click a chain checkbox off", async () => {
      // The failed read removes the chain list (no preflight), so this is a plain click, not uncheck().
      await panel.getByRole("checkbox", { name: `체인 ${dropped}` }).click();
      await panel.getByRole("button", { name: "입력 다시 확인" }).waitFor({ timeout: 30000 });
    }, async () => ({ routeHits: fault.hits(), visibleError: await panel.getByRole("alert").filter({ hasText: "입력 확인 실패" }).innerText() }));
    await fault.remove();
    await step("P04-preflight-retry", "Fault removed; click 입력 다시 확인", async () => {
      await panel.getByRole("button", { name: "입력 다시 확인" }).click();
      await waitPreflightText(panel, keep);
    }, async () => ({ retried: true, selected: keep }));
    await step("P04-chain-recheck", `Check 체인 ${dropped} again`, async () => {
      await panel.getByRole("checkbox", { name: `체인 ${dropped}` }).check();
      await waitPreflightText(panel, chains);
    }, async () => ({ selected: chains }));
    evidence.fixtureLabels.push("renderer-route fixture: labeled 503 on one pocket preflight GET (retry control)");
  }
  const detected = await step("P05-detect-approve", "Click 포켓 검출 실행, then 포켓 계산 승인 후 시작 when asked", () =>
    detect(page, panel, run), async value => {
    assert.equal(value.approvalSeen, true, "first expensive call of a fresh run did not ask for approval");
    const budget = await readApi(page, `/runs/${run}/budget`).catch(() => null);
    return { jobId: value.job.job_id, set: value.set, approvalSeen: value.approvalSeen, attempt: value.job.attempt_ordinal,
      budget };
  });
  evidence.handles.set = detected.set; evidence.handles.job = detected.job.job_id;
  const summary = await summaryOf(page, run, detected.set);
  evidence.summary = { total: summary.total_count, null_result: summary.null_result, chains: summary.selected_chains };
  await step("P06-summary", "Observe the stored result table", async () => summary, async value => {
    assert.equal(value.null_result, false, "public 1HSG produced a null result; positive mode needs pockets");
    assert.equal(await panel.getAttribute("data-pocket-ui-state"), "ready");
    await panel.getByText("약물성(druggability) 증거가 아닙니다", { exact: false }).first().waitFor();
    return assertSummaryTable(panel, value, Math.min(10, value.total_count));
  });
  const topK = panel.getByRole("spinbutton", { name: "표시할 포켓 수 (top-k)" });
  await step("P07-topk-one", "Fill top-k 1", async () => { await topK.fill("1"); }, async () =>
    assertSummaryTable(panel, summary, 1));
  await step("P07-topk-below", "Fill top-k 0 (below range)", async () => { await topK.fill("0"); }, async () => {
    assert.equal(await topK.inputValue(), "1"); return assertSummaryTable(panel, summary, 1);
  });
  await step("P07-topk-arrow", "Press ArrowUp in top-k", async () => { await topK.press("ArrowUp"); }, async () =>
    assertSummaryTable(panel, summary, Math.min(2, summary.total_count)));
  await step("P07-topk-above", "Fill top-k 999 (above range)", async () => { await topK.fill("999"); }, async () => {
    const bound = Math.min(50, summary.total_count);
    assert.equal(Number(await topK.inputValue()), bound);
    return assertSummaryTable(panel, summary, bound);
  });
  const shown = Math.min(50, summary.total_count);
  evidence.overlays = [];
  for (const pocket of summary.pockets.slice(0, shown)) {
    const compared = await step(`P08-rank-${pocket.rank}`, `Click 포켓 rank ${pocket.rank} 선택 and compare every sphere`, () =>
      selectAndCompare(page, panel, run, detected.set, pocket.rank), async value => value);
    evidence.overlays.push(compared);
  }
  const lastRank = summary.pockets[shown - 1].rank;
  await step("P09-spheres-hide", "Uncheck 알파 구 표시", async () => {
    await panel.getByLabel("알파 구 표시").uncheck();
    return waitObserve(page, obs => overlayApplied(obs, detected.set, lastRank) && obs.data.pocketSpheresVisible === "false", "spheres hidden");
  }, async obs => ({ spheresVisible: obs.data.pocketSpheresVisible, nativeVisible: obs.native.pocketOverlay.spheresVisible }));
  await step("P09-spheres-show", "Check 알파 구 표시", async () => {
    await panel.getByLabel("알파 구 표시").check();
    return waitObserve(page, obs => overlayApplied(obs, detected.set, lastRank) && obs.data.pocketSpheresVisible === "true", "spheres shown");
  }, async obs => ({ spheresVisible: obs.data.pocketSpheresVisible }));
  await step("P10-lining-hide", "Uncheck 주변 잔기 표시", async () => {
    await panel.getByLabel("주변 잔기 표시").uncheck();
    return waitObserve(page, obs => overlayApplied(obs, detected.set, lastRank) && obs.data.pocketLiningVisible === "false", "lining hidden");
  }, async obs => {
    assert.equal(Number(obs.data.pocketLiningSiteCount), 0, "hidden lining still has Mol* sites");
    return { liningVisible: obs.data.pocketLiningVisible, liningSites: Number(obs.data.pocketLiningSiteCount) };
  });
  await step("P10-lining-show", "Check 주변 잔기 표시", async () => {
    await panel.getByLabel("주변 잔기 표시").check();
    return waitObserve(page, obs => overlayApplied(obs, detected.set, lastRank) && obs.data.pocketLiningVisible === "true", "lining shown");
  }, async obs => {
    assert.ok(Number(obs.data.pocketLiningSiteCount) >= Number(obs.data.pocketLiningAtomCount));
    return { liningVisible: obs.data.pocketLiningVisible, liningSites: Number(obs.data.pocketLiningSiteCount) };
  });
  const slider = panel.getByRole("slider", { name: "알파 구 불투명도" });
  for (const [key, label] of [["ArrowRight", "raise"], ["ArrowLeft", "lower"], ["ArrowLeft", "lower-again"]]) {
    await step(`P11-opacity-${label}`, `Focus 알파 구 불투명도 and press ${key}`, async () => {
      const before = Number(await slider.inputValue());
      await slider.focus();
      await page.keyboard.press(key);
      const after = Number(await slider.inputValue());
      assert.notEqual(after, before);
      const obs = await waitObserve(page, value => overlayApplied(value, detected.set, lastRank) &&
        Math.abs(Number(value.data.pocketOpacity) - after) <= 1e-6, "opacity applied");
      return { before, after, observed: Number(obs.data.pocketOpacity), nativeOpacity: obs.native.pocketOverlay.opacity };
    }, async value => value);
  }
  await step("P12-focus", "Right-drag the canvas to pan the camera away, then click 포켓 초점", async () => {
    const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
    const box = await canvas.boundingBox();
    const before = (await observe(page)).native.nativeCamera;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down({ button: "right" });
    await page.mouse.move(box.x + box.width / 2 + 160, box.y + box.height / 2 + 60, { steps: 12 });
    await page.mouse.up({ button: "right" });
    const rotated = await waitObserve(page, obs => obs.native.cameraTransitioning === false &&
      Math.hypot(...obs.native.nativeCamera.target.map((v, i) => v - before.target[i])) > 0.5, "camera target panned by drag");
    const token = Number(rotated.data.pocketFocusToken);
    await panel.getByRole("button", { name: "포켓 초점" }).click();
    const focused = await waitObserve(page, obs => overlayApplied(obs, detected.set, lastRank) &&
      Number(obs.data.pocketFocusToken) === token + 1 && Array.isArray(obs.native.pocketOverlay.focusedTarget) &&
      obs.native.cameraTransitioning === false, "refocused");
    return { before, rotated: rotated.native.nativeCamera, focused, token };
  }, async value => ({ pannedTarget: value.rotated.target, targetBefore: value.before.target,
    focusToken: Number(value.focused.data.pocketFocusToken),
    focus: focusMatches(value.focused, await geometry(page, run, detected.set, lastRank)) }));
  await step("P13-clear", "Click 오버레이 지우기", async () => {
    await panel.getByRole("button", { name: "오버레이 지우기" }).click();
    return waitObserve(page, overlayNone, "overlay cleared");
  }, async obs => {
    assert.equal(await panel.getByRole("button", { name: "포켓 초점" }).isDisabled(), true);
    assert.equal(await page.locator("[data-pocket-m9-reason]").count(), 0);
    return { overlay: obs.data.pocketOverlay };
  });
  await step("P14-return-to-source", "Select rank 1 again, then click 원래 소스로 돌아가기", async () => {
    await selectRank(page, panel, run, detected.set, summary.pockets[0].rank);
    await panel.getByRole("button", { name: "원래 소스로 돌아가기" }).click();
    return waitObserve(page, obs => overlayNone(obs) && obs.native?.ready === true, "returned to source");
  }, async obs => ({ overlay: obs.data.pocketOverlay, displayedSource: obs.native.sourceHandle }));
  evidence.sources = sources;
}

async function modeEmpty(session, input, rec) {
  const { page } = session;
  const { step, evidence } = rec;
  const panel = panelOf(page);
  const run = await step("E01-new-run", "Click 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.run = run;
  const sources = await step("E02-upload-prepare", `Choose ${path.basename(input.fixture)} (derived), 구조 불러오기, 전처리`,
    () => uploadLoadPrepare(page, run, input.fixture), async value => value);
  evidence.inputs.push(sources.upload);
  evidence.handles.prepared = sources.prepared;
  await step("E03-preflight", "Observe the derived fixture projection", async () => {
    const value = await preflightFor(page, run, sources.prepared);
    await waitPreflightText(panel, value.selected_chains);
    return value;
  }, async value => {
    const provenance = JSON.parse(fs.readFileSync(DERIVED_PROVENANCE, "utf8"));
    if (path.basename(input.fixture) === provenance.file) {
      assert.equal(value.projected_atom_count, provenance.expected_projection.heavy_atoms, "derived fixture contract size");
      assert.equal(value.projected_residue_count, provenance.expected_projection.residues);
    }
    return { projectedAtoms: value.projected_atom_count, projectedResidues: value.projected_residue_count };
  });
  const detected = await step("E04-detect", "Click 포켓 검출 실행 and approve", () => detect(page, panel, run), async value =>
    ({ jobId: value.job.job_id, set: value.set }));
  evidence.handles.set = detected.set; evidence.handles.job = detected.job.job_id;
  const summary = await summaryOf(page, run, detected.set);
  evidence.summary = { total: summary.total_count, null_result: summary.null_result };
  if (summary.total_count !== 0) throw new Error(`derived fixture produced ${summary.total_count} pockets; ` +
    "the result is preserved for investigation (never forced to empty)");
  await step("E05-scientific-null", "Observe scientific_null, distinct from failure", async () => null, async () => {
    assert.equal(summary.null_result, true);
    assert.equal(await panel.getAttribute("data-pocket-ui-state"), "scientific_null");
    await panel.locator("[data-pocket-null-result]").waitFor();
    assert.equal(await panel.locator("[data-pocket-total-count]").count(), 0, "null result shows a pocket count row");
    assert.equal(await panel.getByRole("region", { name: "fpocket 후보 공동 목록" }).count(), 0);
    assert.equal(await panel.getByRole("button", { name: /^포켓 rank \d+ 선택$/ }).count(), 0);
    assert.equal(await panel.locator("[role=alert]").count(), 0, "scientific_null is shown as an error");
    assert.equal(await panel.getByRole("button", { name: "포켓 초점" }).isDisabled(), true);
    return { uiState: "scientific_null", nullText: await panel.locator("[data-pocket-null-result]").innerText() };
  });
  const report = await step("E06-report", "Click 포켓 보고서 만들기 and download both files", async () => {
    await createReport(page, panel, run);
    return reportDownloads(session, panel, run, detected.set, summary);
  }, async value => { assert.equal(value.validation.pockets, 0); return value; });
  evidence.handles.report = report.handle;
  evidence.report = { md: report.markdown.sha256, json: report.json.sha256 };
}

async function createReport(page, panel, run) {
  const button = panel.getByRole("button", { name: /^(포켓 보고서 만들기|저장된 포켓 보고서 열기)$/ });
  await button.waitFor({ timeout: 30000 });
  const label = (await button.innerText()).trim();
  let created = null;
  if (label === "포켓 보고서 만들기") {
    const posted = page.waitForResponse(response => response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
    await button.click();
    const response = await posted;
    assert.equal(response.status(), 201, `pocket report creation HTTP ${response.status()}`);
    created = (await response.json()).handle;
  } else await button.click();
  await panel.getByRole("link", { name: "포켓 보고서 JSON 다운로드" }).waitFor({ timeout: 30000 });
  return { label, created };
}

async function modeInvalid(session, input, rec) {
  const { page } = session;
  const { step, evidence } = rec;
  const manifest = JSON.parse(fs.readFileSync(path.join(input.variants, "m12-invalid-cases.json"), "utf8"));
  evidence.inputs.push({ name: "m12-invalid-cases.json", ...fileRecord(path.join(input.variants, "m12-invalid-cases.json")),
    provenance: provenanceLabel("m12-invalid-cases.json") });
  evidence.cases = [];
  const panel = panelOf(page);
  for (const item of manifest.cases) {
    const file = path.join(input.variants, item.file);
    assert.equal(shaFile(file), item.sha256, `${item.file} bytes differ from its manifest`);
    const tag = item.expected_reason_code;
    const run = await step(`I01-${tag}-new-run`, "Click 새 run", () => newRun(page), async id => ({ run: id }));
    const sources = await step(`I02-${tag}-upload-prepare`, `Choose ${item.file}, 구조 불러오기, 전처리`,
      () => uploadLoadPrepare(page, run, file), async value => value);
    evidence.inputs.push(sources.upload);
    const outcome = await step(`I03-${tag}-reject`, "Observe the preflight rejection reason and a disabled detection", async () => {
      await panel.locator(`[data-pocket-reject="${tag}"]`).waitFor({ timeout: 30000 });
      const button = panel.getByRole("button", { name: "포켓 검출 실행" });
      assert.equal(await button.isDisabled(), true);
      const before = await scienceEvents(page, run);
      const posts = [];
      const listener = request => { if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/jobs")) posts.push(request.url()); };
      page.on("request", listener);
      let forced = "clicked";
      try { await button.click({ force: true, timeout: 5000 }); } catch (error) { forced = `input refused: ${String(error).slice(0, 200)}`; }
      await page.waitForTimeout(700);
      page.off("request", listener);
      return { before, posts, forced, after: await scienceEvents(page, run) };
    }, async value => {
      const api = await preflightFor(page, run, sources.prepared);
      assert.equal(api.ready, false);
      assert.equal(api.reject?.reason_code, tag, `expected ${tag}, got ${JSON.stringify(api.reject)}`);
      assert.equal(api.status, "unsupported_input");
      assert.deepEqual(value.posts, [], "a disabled detection control submitted a job");
      assert.deepEqual(value.after, value.before, "an invalid input created a job or object");
      assert.equal((await pocketJobs(page, run)).length, 0);
      const reason = await panel.locator("[data-pocket-detect-reason]").innerText();
      assert.match(reason, /입력을 사용할 수 없습니다/);
      const rejectText = await panel.locator(`[data-pocket-reject="${tag}"]`).innerText();
      assert.equal(/\d+\.\d+\s*Å/.test(rejectText), false, "rejection shows a scientific number");
      return { reasonCode: api.reject.reason_code, message: api.reject.message, detectReason: reason, rejectText,
        forcedClick: value.forced, jobs: 0 };
    });
    evidence.cases.push({ file: item.file, run, prepared: sources.prepared, ...outcome });
  }
  evidence.run = evidence.cases.map(item => item.run).join(",");
}

async function modeUnavailable(session, input, rec) {
  const { page } = session;
  const { step, evidence } = rec;
  const panel = panelOf(page);
  const run = await step("U01-new-run", "Click 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.run = run;
  const sources = await step("U02-upload-prepare", `Choose ${path.basename(input.fixture)}, 구조 불러오기, 전처리`,
    () => uploadLoadPrepare(page, run, input.fixture), async value => value);
  evidence.inputs.push(sources.upload);
  await step("U03-unavailable", `Observe capability ${input.expectCapability} without numbers`, async () => {
    await panel.locator(`[data-pocket-capability="${input.expectCapability}"]`).waitFor({ timeout: 30000 });
    const button = panel.getByRole("button", { name: "포켓 검출 실행" });
    assert.equal(await button.isDisabled(), true);
    const before = await scienceEvents(page, run);
    let forced = "clicked";
    try { await button.click({ force: true, timeout: 5000 }); } catch (error) { forced = `input refused: ${String(error).slice(0, 200)}`; }
    await page.waitForTimeout(700);
    return { before, forced, after: await scienceEvents(page, run) };
  }, async value => {
    const cap = (await readApi(page, "/capabilities")).methods.pocket_detection;
    assert.equal(cap.available, false);
    assert.equal(cap.status, input.expectCapability);
    const api = await preflightFor(page, run, sources.prepared);
    assert.equal(api.status, input.expectCapability);
    assert.equal(api.available, false);
    assert.equal(await panel.getAttribute("data-pocket-ui-state"), "unavailable");
    const text = await panel.locator(`[data-pocket-capability="${input.expectCapability}"]`).innerText();
    assert.ok(text.includes(cap.reason), "panel does not show the capability reason verbatim");
    assert.equal(await panel.locator("[data-pocket-total-count], [data-pocket-null-result]").count(), 0);
    assert.equal(await panel.getByRole("region", { name: "fpocket 후보 공동 목록" }).count(), 0);
    assert.deepEqual(value.after, value.before, "an unavailable engine accepted a job");
    assert.equal((await pocketJobs(page, run)).length, 0);
    return { capability: { status: cap.status, reason_code: cap.reason_code, reason: cap.reason }, panelText: text,
      detectReason: await panel.locator("[data-pocket-detect-reason]").innerText(), forcedClick: value.forced };
  });
}

async function modeCancel(session, input, rec) {
  const { page } = session;
  const { step, evidence } = rec;
  const panel = panelOf(page);
  const run = await step("K01-new-run", "Click 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.run = run;
  const sources = await step("K02-upload-prepare", `Choose ${path.basename(input.fixture)}, 구조 불러오기, 전처리`,
    () => uploadLoadPrepare(page, run, input.fixture), async value => value);
  evidence.inputs.push(sources.upload);
  const preflight = await preflightFor(page, run, sources.prepared);
  await waitPreflightText(panel, preflight.selected_chains);
  const started = await step("K03-start-held-for-approval", "Click 포켓 검출 실행; the start asks for approval (job queued)", () =>
    detect(page, panel, run, { approve: false }), async value => {
    assert.equal(value.approvalSeen, true);
    const job = await readApi(page, `/runs/${run}/jobs/${value.job.job_id}`);
    assert.ok(["queued", "claimed"].includes(job.status), `job not waiting for approval: ${job.status}`);
    assert.equal(job.attempt_ordinal, 0, "a job waiting for approval already started an attempt");
    return { jobId: job.job_id, status: job.status, attempt: job.attempt_ordinal };
  });
  const budgetBefore = await readApi(page, `/runs/${run}/budget`);
  await step("K04-cancel", "Click 포켓 작업 취소", async () => {
    await panel.getByRole("button", { name: "포켓 작업 취소" }).click();
    await panel.locator('[data-pocket-job-status="cancelled"]').waitFor({ timeout: 30000 });
  }, async () => {
    const job = await readApi(page, `/runs/${run}/jobs/${started.job.job_id}`);
    assert.equal(job.status, "cancelled");
    const budgetAfter = await readApi(page, `/runs/${run}/budget`);
    assert.deepEqual(budgetAfter.expensive_calls, budgetBefore.expensive_calls, "a queued cancel was charged");
    assert.equal(await panel.getByRole("button", { name: "포켓 작업 취소" }).count(), 0);
    return { job: job.status, uiState: await panel.getAttribute("data-pocket-ui-state"), budget: budgetAfter.expensive_calls };
  });
  await step("K05-cancel-rerun-notice", "Click 포켓 검출 실행 again with the same chains", async () => {
    const jobsBefore = await pocketJobs(page, run);
    const posted = page.waitForResponse(response => response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/api/runs/${run}/jobs`, { timeout: 30000 });
    await panel.getByRole("button", { name: "포켓 검출 실행" }).click();
    const body = await (await posted).json();
    await panel.locator("[data-pocket-notice]").waitFor({ timeout: 30000 });
    return { jobsBefore, body };
  }, async value => {
    const notice = await panel.locator("[data-pocket-notice]").innerText();
    assert.ok(notice.includes("다른 체인 조합") && notice.includes("새 run"), `cancel-rerun notice: ${notice}`);
    assert.equal(value.body.job_id, started.job.job_id, "same call key returned a different job");
    assert.equal(value.body.status, "cancelled");
    const jobsAfter = await pocketJobs(page, run);
    assert.equal(jobsAfter.length, value.jobsBefore.length, "same-call re-detection created a job");
    return { notice, returnedJob: value.body.job_id, jobs: jobsAfter.length };
  });
  if (preflight.selected_chains.length > 1) {
    const keep = preflight.selected_chains.slice(0, -1);
    const other = await step("K06-other-chains", `Uncheck 체인 ${preflight.selected_chains.at(-1)} and detect (different call key)`, async () => {
      await panel.getByRole("checkbox", { name: `체인 ${preflight.selected_chains.at(-1)}` }).uncheck();
      await waitPreflightText(panel, keep);
      return detect(page, panel, run);
    }, async value => {
      assert.notEqual(value.job.job_id, started.job.job_id);
      const summary = await summaryOf(page, run, value.set);
      assert.deepEqual(summary.selected_chains, keep);
      return { jobId: value.job.job_id, set: value.set, chains: summary.selected_chains, total: summary.total_count };
    });
    evidence.handles.set = other.set;
  }
  evidence.handles.cancelledJob = started.job.job_id;
}

async function openExisting(page, input) {
  await page.waitForFunction(id => new URL(location.href).searchParams.get("run") === id, input.run, { timeout: 30000 });
  const panel = panelOf(page);
  await panel.waitFor({ timeout: 60000 });
  await viewerReady(page);
  return panel;
}

async function modeReopen(session, input, rec) {
  const { page } = session;
  const { step, evidence } = rec;
  evidence.run = input.run; evidence.handles.set = input.set;
  const panel = await openExisting(page, input);
  const jobsBefore = await pocketJobs(page, input.run);
  const fault = await failOnce(page, `**/api/runs/${input.run}/pockets/result?*`, "pocket result");
  await step("R01-history-fault", "Labeled 503 on the result read; click 포켓 결과 다시 열기 from history", async () => {
    const heading = await openHistory(page, panel);
    await panel.getByRole("button", { name: `포켓 결과 다시 열기 ${shortHandle(input.set)}` }).click();
    await panel.getByRole("button", { name: "포켓 결과 다시 읽기" }).waitFor({ timeout: 30000 });
    return heading;
  }, async heading => {
    assert.equal(await panel.getAttribute("data-pocket-ui-state"), "failed");
    return { historyHeading: heading, routeHits: fault.hits() };
  });
  await fault.remove();
  evidence.fixtureLabels.push("renderer-route fixture: labeled 503 on one pocket result GET (retry control)");
  let summary;
  const guard = await withoutJobPosts(page, input.run, async () => {
    summary = await step("R02-result-retry", "Fault removed; click 포켓 결과 다시 읽기", async () => {
      await panel.getByRole("button", { name: "포켓 결과 다시 읽기" }).click();
      await panel.locator("[data-pocket-total-count], [data-pocket-null-result]").first().waitFor({ timeout: 30000 });
      return summaryOf(page, input.run, input.set);
    }, async value => {
      assert.equal(value.handle, input.set);
      if (!value.null_result) await assertSummaryTable(panel, value, Math.min(10, value.total_count));
      return { total: value.total_count };
    });
    await step("R03-history-refresh", "Click 포켓 기록 다시 읽기", async () => {
      const read = page.waitForResponse(response => new URL(response.url()).pathname === `/api/runs/${input.run}/pockets`, { timeout: 30000 });
      await panel.getByRole("button", { name: "포켓 기록 다시 읽기" }).click();
      return (await read).json();
    }, async list => {
      assert.ok(list.rows.some(row => row.handle === input.set));
      assert.equal(await panel.locator(`[data-pocket-history="${input.set}"]`).count(), 1);
      return { rows: list.total };
    });
    if (!summary.null_result) for (const pocket of summary.pockets.slice(0, Math.min(3, summary.pockets.length))) {
      const compared = await step(`R04-rank-${pocket.rank}`, `Click 포켓 rank ${pocket.rank} 선택 on the reopened set`, () =>
        selectAndCompare(page, panel, input.run, input.set, pocket.rank), async value => value);
      evidence.overlays = [...(evidence.overlays ?? []), compared];
    }
  });
  await step("R05-no-new-job", "Reopen created no job or scientific event", async () => guard, async value => {
    assert.deepEqual(value.posts, [], "reopen posted a job/command/report");
    assert.equal(value.unchanged, true, "reopen appended scientific/job events");
    assert.deepEqual((await pocketJobs(page, input.run)).map(job => job.job_id), jobsBefore.map(job => job.job_id));
    return value;
  });
}

async function modeReportDownload(session, input, rec) {
  const { page } = session;
  const { step, evidence } = rec;
  evidence.run = input.run; evidence.handles.set = input.set;
  const panel = await openExisting(page, input);
  const summary = await reopenSet(page, panel, input.run, input.set);
  const first = await step("D01-create", "Click 포켓 보고서 만들기; download Markdown and JSON; decode and validate", async () => {
    const made = await createReport(page, panel, input.run);
    return { made, downloads: await reportDownloads(session, panel, input.run, input.set, summary) };
  }, async value => value);
  evidence.handles.report = first.downloads.handle;
  evidence.report = { md: first.downloads.markdown.sha256, json: first.downloads.json.sha256 };
  await step("D02-reopen-saved", "Reload, reopen the set, click 저장된 포켓 보고서 열기 (no new report)", async () => {
    await page.reload();
    const again = await openExisting(page, input);
    await reopenSet(page, again, input.run, input.set);
    const posts = [];
    const listener = request => { if (request.method() === "POST") posts.push(new URL(request.url()).pathname); };
    page.on("request", listener);
    const made = await createReport(page, again, input.run);
    page.off("request", listener);
    return { made, posts, downloads: await reportDownloads(session, again, input.run, input.set, summary) };
  }, async value => {
    assert.equal(value.made.label, "저장된 포켓 보고서 열기");
    assert.deepEqual(value.posts, [], "reopening the saved report created a new one");
    assert.equal(value.downloads.handle, first.downloads.handle);
    assert.equal(value.downloads.markdown.sha256, first.downloads.markdown.sha256);
    assert.equal(value.downloads.json.sha256, first.downloads.json.sha256);
    return value;
  });
}

async function modeOverlayDisables(session, input, rec) {
  const { page } = session;
  const { step, evidence } = rec;
  evidence.run = input.run; evidence.handles.set = input.set;
  const panel = await openExisting(page, input);
  const summary = await reopenSet(page, panel, input.run, input.set);
  const rank = summary.pockets[0].rank;
  await page.locator("label").filter({ hasText: "보기 이름" }).locator("input").fill("m12 pocket QA view");
  const viewerEventTypes = ["viewer_intent_requested", "viewer_dispatch_started", "viewer_scene_saved", "viewer_figure_saved"];
  const viewerEvents = async () => (await runEvents(page, input.run)).filter(event => viewerEventTypes.includes(event.type)).length;
  await step("O01-overlay-on", `Click 포켓 rank ${rank} 선택`, () => selectRank(page, panel, input.run, input.set, rank),
    async obs => ({ overlay: obs.data.pocketOverlay }));
  await step("O02-disabled", "Observe M9 save/PNG and M8 request disabled with reasons; type /zoom in + Enter; force-click", async () => {
    const before = await viewerEvents();
    await page.locator("#viewer-prompt").fill("/zoom in");
    await page.locator("#viewer-prompt").press("Enter");
    const attempts = [];
    for (const name of ["현재 보기 저장", "현재 보기 PNG 내보내기", "확대", "실행"]) {
      const button = page.getByRole("button", { name, exact: true });
      let outcome = "clicked";
      try { await button.click({ force: true, timeout: 5000 }); } catch (error) { outcome = `input refused: ${String(error).slice(0, 160)}`; }
      attempts.push({ name, disabled: await button.isDisabled(), outcome });
    }
    await page.waitForTimeout(700);
    return { before, after: await viewerEvents(), attempts };
  }, async value => {
    assert.equal(value.after, value.before, "a disabled M8/M9 control created a viewer event");
    for (const attempt of value.attempts) assert.equal(attempt.disabled, true, `${attempt.name} enabled while overlay on`);
    const m9 = await page.locator("[data-pocket-m9-reason]").innerText();
    const m8 = await page.locator("[data-viewer-request-disabled]").innerText();
    assert.ok(m9.includes(OVERLAY_REASON) && m8.includes(OVERLAY_REASON));
    assert.ok((await page.getByRole("button", { name: "현재 보기 저장" }).getAttribute("title")).includes(OVERLAY_REASON));
    return { m9Reason: m9, m8Reason: m8, attempts: value.attempts };
  });
  await step("O03-clear", "Click 오버레이 지우기", async () => {
    await panel.getByRole("button", { name: "오버레이 지우기" }).click();
    return waitObserve(page, overlayNone, "overlay cleared");
  }, async () => {
    assert.equal(await page.locator("[data-pocket-m9-reason]").count(), 0);
    assert.equal(await page.locator("[data-viewer-request-disabled]").count(), 0);
    await page.waitForFunction(() => [...document.querySelectorAll("button")].some(b => b.textContent?.trim() === "확대" && !b.disabled),
      null, { timeout: 30000 });
    assert.equal(await page.getByRole("button", { name: "현재 보기 저장", exact: true }).isEnabled(), true);
    return { restored: true };
  });
  await step("O04-m8-restored", "Click 확대 (local viewer request) after clearing", async () => {
    const before = await viewerEvents();
    await page.getByRole("button", { name: "확대", exact: true }).click();
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline && await viewerEvents() === before) await page.waitForTimeout(200);
    return { before, after: await viewerEvents() };
  }, async value => { assert.ok(value.after > value.before, "M8 request did not reach the backend after clear"); return value; });
  await step("O05-m9-restored", "Click 현재 보기 저장 after clearing", async () => {
    const posted = page.waitForResponse(response => response.request().method() === "POST" &&
      /\/viewer\/scenes/.test(new URL(response.url()).pathname), { timeout: 30000 });
    await page.getByRole("button", { name: "현재 보기 저장", exact: true }).click();
    const response = await posted;
    return { status: response.status() };
  }, async value => { assert.ok([200, 201].includes(value.status), `scene save HTTP ${value.status}`); return value; });
}

async function comparisonPairs(page, run, reference, moving) {
  const rows = async handle => {
    const out = [];
    let total = null;
    while (total === null || out.length < total) {
      const chunk = await readApi(page, `/runs/${run}/structures/atoms?handle=${encodeURIComponent(handle)}&offset=${out.length}&limit=500`);
      total = chunk.total; out.push(...chunk.rows);
      if (!chunk.rows.length) break;
    }
    return out;
  };
  const ref = (await rows(reference)).filter(row => row.ref.atom_name === "CA");
  const mov = (await rows(moving)).filter(row => row.ref.atom_name === "CA");
  const same = (a, b) => ["chain_auth", "seq_auth", "icode", "resname"].every(field => a.ref.residue[field] === b.ref.residue[field]);
  const pairs = [];
  for (const row of ref) {
    const match = mov.filter(item => same(row, item));
    if (match.length === 1) pairs.push([row.ref.site_index, match[0].ref.site_index]);
    if (pairs.length === 3) break;
  }
  assert.equal(pairs.length, 3, "could not find three same-residue CA pairs");
  return pairs;
}

async function modeComparisonBlock(session, input, rec) {
  const { page } = session;
  const { step, evidence } = rec;
  evidence.run = input.run; evidence.handles.set = input.set;
  const panel = await openExisting(page, input);
  const summary = await reopenSet(page, panel, input.run, input.set);
  const rank = summary.pockets[0].rank;
  await step("C01-overlay-on", `Click 포켓 rank ${rank} 선택`, () => selectRank(page, panel, input.run, input.set, rank),
    async obs => ({ overlay: obs.data.pocketOverlay }));
  const events = await runEvents(page, input.run);
  const original = events.find(event => event.type === "object_created" && event.kind === "structure").handle;
  const reference = summary.source_handle;
  const pairs = await comparisonPairs(page, input.run, reference, original);
  const m10 = page.locator('[aria-label="원자 거리와 두 구조 비교"]');
  await step("C02-compare", "Choose ball-and-stick, reference/moving, three CA pairs, click 정렬 계산", async () => {
    await page.getByRole("group", { name: "표현 방식" }).getByRole("button", { name: "ball-and-stick", exact: true }).click();
    await m10.getByRole("combobox", { name: "기준 구조" }).selectOption(reference);
    await m10.getByRole("combobox", { name: "이동 구조" }).selectOption(original);
    for (const [a, b] of pairs) {
      await m10.getByRole("combobox", { name: "기준 CA site" }).locator(`option[value="${a}"]`).waitFor({ state: "attached", timeout: 30000 });
      await m10.getByRole("combobox", { name: "기준 CA site" }).selectOption(String(a));
      await m10.getByRole("combobox", { name: "이동 CA site" }).selectOption(String(b));
      await m10.getByRole("button", { name: "대응 추가" }).click();
    }
    const posted = page.waitForResponse(response => response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/api/runs/${input.run}/commands`, { timeout: 45000 });
    await m10.getByRole("button", { name: "정렬 계산" }).click();
    assert.equal((await posted).status(), 200);
    return waitObserve(page, obs => obs.native?.layers?.length === 2, "comparison layers");
  }, async obs => {
    await panel.getByText(COMPARISON_REASON, { exact: false }).first().waitFor({ timeout: 30000 });
    assert.ok(overlayNone(await waitObserve(page, overlayNone, "overlay cleared by comparison")));
    return { layers: obs.native.layers.map(layer => layer.sourceHandle) };
  });
  await step("C03-blocked", "Observe pocket detection/overlay disabled with the reason; force-click rank and reopen", async () => {
    const attempts = [];
    for (const button of [panel.getByRole("button", { name: `포켓 rank ${rank} 선택` }),
      panel.getByRole("button", { name: "포켓 검출 실행" })]) {
      let outcome = "clicked";
      try { await button.click({ force: true, timeout: 5000 }); } catch (error) { outcome = `input refused: ${String(error).slice(0, 160)}`; }
      attempts.push({ disabled: await button.isDisabled(), outcome });
    }
    await openHistory(page, panel);
    const reopen = panel.getByRole("button", { name: `포켓 결과 다시 열기 ${shortHandle(input.set)}` });
    attempts.push({ name: "reopen", disabled: await reopen.isDisabled() });
    await page.waitForTimeout(700);
    return attempts;
  }, async attempts => {
    for (const attempt of attempts) assert.equal(attempt.disabled, true);
    const obs = await observe(page);
    assert.ok(overlayNone(obs), "pocket overlay drawn in the comparison frame");
    const reason = await panel.locator("[data-pocket-detect-reason]").innerText();
    assert.ok(reason.includes(COMPARISON_REASON));
    return { attempts, detectReason: reason };
  });
  await step("C04-single", "Click 단일 구조로 돌아가기; pocket overlay usable again", async () => {
    await m10.getByRole("button", { name: "단일 구조로 돌아가기" }).click();
    await page.waitForFunction(text => !document.querySelector('section[data-pocket-panel="main"]')?.textContent?.includes(text),
      COMPARISON_REASON, { timeout: 30000 });
    await viewerReady(page, native => !native.layers || native.layers.length === 1);
    return selectRank(page, panel, input.run, input.set, rank);
  }, async obs => ({ overlay: obs.data.pocketOverlay }));
}

function projectToCanvas(camera, world, box, size) {
  const sub = (a, b) => a.map((v, i) => v - b[i]);
  const dot = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0);
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm = a => { const l = Math.hypot(...a); return a.map(v => v / l); };
  assert.equal(camera.mode, "perspective");
  const forward = norm(sub(camera.target, camera.position));
  const right = norm(cross(forward, camera.up));
  const up = norm(cross(right, forward));
  const relative = sub(world, camera.position), depth = dot(relative, forward);
  const scale = box.height / (2 * Math.tan(camera.fov / 2) * depth);
  return { x: box.x + box.width / 2 + dot(relative, right) * scale, y: box.y + box.height / 2 - dot(relative, up) * scale,
    depth, canvas: size };
}

async function modeDistanceWithOverlay(session, input, rec) {
  const { page } = session;
  const { step, evidence } = rec;
  evidence.run = input.run; evidence.handles.set = input.set;
  const panel = await openExisting(page, input);
  const summary = await reopenSet(page, panel, input.run, input.set);
  const rank = summary.pockets[0].rank;
  const m10 = page.locator('[aria-label="원자 거리와 두 구조 비교"]');
  await step("M01-ball-and-stick", "Choose ball-and-stick representation", async () => {
    await page.getByRole("group", { name: "표현 방식" }).getByRole("button", { name: "ball-and-stick", exact: true }).click();
    return viewerReady(page, native => native.representation === "ball-and-stick");
  }, async obs => ({ representation: obs.native.representation }));
  await step("M02-overlay-on", `Click 포켓 rank ${rank} 선택`, () => selectRank(page, panel, input.run, input.set, rank),
    async obs => ({ overlay: obs.data.pocketOverlay, source: obs.native.sourceHandle }));
  await step("M03-measure-mode", "Click 원자 거리 측정 with the overlay on", async () => {
    await m10.getByRole("button", { name: "원자 거리 측정", exact: true }).click();
    return waitObserve(page, obs => obs.native?.measureMode === true, "measure mode");
  }, async obs => {
    const still = overlayApplied(obs, input.set, rank);
    return { measureMode: true, overlayStillApplied: still, notice: still ? null :
      await panel.locator("[data-pocket-overlay-notice]").innerText().catch(() => null) };
  });
  const geo = await geometry(page, input.run, input.set, rank);
  await step("M04-sphere-not-pickable", "Click the projected center of a stored alpha sphere", async () => {
    const obs = await waitObserve(page, value => value.native?.ready && value.native.cameraTransitioning === false, "camera idle");
    const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
    const box = await canvas.boundingBox();
    const size = await canvas.evaluate(node => ({ width: node.width, height: node.height }));
    const sphere = geo.spheres[0];
    const point = projectToCanvas(obs.native.nativeCamera, [sphere.x_A, sphere.y_A, sphere.z_A], box, size);
    const before = obs.native.nativeClickRevision;
    await page.mouse.move(point.x, point.y);
    await page.mouse.click(point.x, point.y);
    const after = await waitObserve(page, value => value.native.nativeClickRevision > before, "native click observed", 10000);
    return { point, click: after.native.lastNativeClick, pick: after.native.lastAtomPick, overlay: after.data.pocketOverlay };
  }, async value => {
    assert.ok(!["group-loci", "shape-loci"].includes(value.click.kind), `alpha sphere was picked: ${value.click.kind}`);
    if (value.pick) assert.ok(value.pick.ref?.structure_handle === summary.source_handle, "pick outside the source atoms");
    return value;
  });
  await step("M05-distance", "Click two actual atoms; the guarded distance command answers", async () => {
    const atoms = (await observe(page)).native.qaAtoms.filter(atom => atom.layer === "reference");
    const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
    const box = await canvas.boundingBox();
    const size = await canvas.evaluate(node => ({ width: node.width, height: node.height }));
    const inside = atoms.filter(atom => atom.canvasPixel[0] > 8 && atom.canvasPixel[0] < size.width - 8 &&
      atom.canvasPixel[1] > 8 && atom.canvasPixel[1] < size.height - 8);
    const picks = [];
    let posted = null;
    for (const atom of inside.slice(0, 40)) {
      if (picks.length === 2) break;
      const before = (await observe(page)).native;
      const x = box.x + atom.canvasPixel[0] * box.width / size.width, y = box.y + atom.canvasPixel[1] * box.height / size.height;
      if (picks.length === 1) posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${input.run}/commands`, { timeout: 30000 }).catch(error => ({ error }));
      await page.mouse.move(x, y);
      await page.mouse.click(x, y);
      try {
        const after = await waitObserve(page, value => value.native.atomPickRevision > before.atomPickRevision &&
          !picks.some(p => p.site_index === value.native.lastAtomPick?.ref.site_index), "atom pick", 1500);
        picks.push(after.native.lastAtomPick.ref);
      } catch { posted = picks.length === 1 ? null : posted; }
    }
    assert.equal(picks.length, 2, "two genuine atom picks did not succeed");
    const response = await posted;
    assert.ok(response && !response.error, "distance command POST not observed");
    const body = await response.json();
    assert.equal(body.ok, true, JSON.stringify(body));
    return { picks, handle: body.handle.handle };
  }, async value => {
    const detail = await readApi(page, `/runs/${input.run}/objects/measurement?handle=${encodeURIComponent(value.handle)}`);
    assert.equal(detail.result.structure_handle, summary.source_handle);
    const obs = await observe(page);
    const still = overlayApplied(obs, input.set, rank);
    if (!still) {
      assert.ok(overlayNone(obs));
      assert.ok((await panel.locator("[data-pocket-overlay-notice]").innerText()).includes(CONTEXT_CLEARED));
    }
    return { handle: value.handle, distance_A: detail.result.distance_A, overlayStillApplied: still,
      displayedSource: obs.native.sourceHandle };
  });
  await step("M06-end-measure", "Click 원자 거리 측정 끝내기", async () => {
    await m10.getByRole("button", { name: "원자 거리 측정 끝내기" }).click();
    return waitObserve(page, obs => obs.native?.measureMode === false, "measure ended");
  }, async obs => ({ overlay: obs.data.pocketOverlay }));
  if (!overlayApplied(await observe(page), input.set, rank))
    await step("M07-overlay-again", `Click 포켓 rank ${rank} 선택`, () => selectRank(page, panel, input.run, input.set, rank),
      async obs => ({ overlay: obs.data.pocketOverlay }));
  await step("M08-source-change", "Click the load_structure history step (displayed source changes)", async () => {
    await historyStepClick(page, "load_structure");
    return waitObserve(page, obs => overlayNone(obs) && obs.native?.ready && obs.native.sourceHandle !== summary.source_handle,
      "source changed and overlay cleared");
  }, async obs => {
    const notice = await panel.locator("[data-pocket-overlay-notice]").innerText();
    assert.ok(notice.includes(CONTEXT_CLEARED), notice);
    return { displayedSource: obs.native.sourceHandle, notice };
  });
}

async function modeSourceRace(session, input, rec) {
  const { page } = session;
  const { step, evidence } = rec;
  evidence.run = input.run; evidence.handles.set = input.set; evidence.handles.otherRun = input.otherRun;
  const panel = await openExisting(page, input);
  const summary = await reopenSet(page, panel, input.run, input.set);
  assert.ok(summary.pockets.length >= 2, "source-race needs at least two stored pockets");
  const [a, b] = summary.pockets.map(pocket => pocket.rank);
  const geoPattern = `**/api/runs/${input.run}/pockets/geometry?*`;
  evidence.fixtureLabels.push("renderer-route fixture: held real pocket geometry GET responses (released unchanged)");
  await step("S01-quick-switch", `Hold rank ${a} geometry, click rank ${a} then rank ${b}; release late rank ${a}`, async () => {
    let first = true, held = null;
    let release, started;
    const gate = new Promise(resolve => { release = resolve; });
    const startedGate = new Promise(resolve => { started = resolve; });
    const handler = async route => {
      if (!first) { await route.continue(); return; }
      first = false;
      const response = await route.fetch();
      started();
      await gate;
      try { await route.fulfill({ response }); held = "fulfilled"; } catch (error) { held = `cancelled: ${String(error).slice(0, 120)}`; }
    };
    await page.route(geoPattern, handler);
    try {
      await panel.getByRole("button", { name: `포켓 rank ${a} 선택` }).click();
      await startedGate;
      await panel.getByRole("button", { name: `포켓 rank ${b} 선택` }).click().catch(async () => {
        // The rank buttons are disabled while one geometry read is in flight: wait, then click B.
        await page.waitForTimeout(100);
      });
      release();
      await page.waitForTimeout(300);
      if (!overlayApplied(await observe(page), input.set, b)) {
        await panel.getByRole("button", { name: `포켓 rank ${b} 선택` }).click();
      }
      const obs = await waitObserve(page, value => overlayApplied(value, input.set, b), `rank ${b} final`, 60000);
      await page.waitForTimeout(1500);
      return { final: await observe(page), heldDelivery: held, firstApplied: obs.data.pocketRank };
    } finally { release(); await page.unroute(geoPattern, handler); }
  }, async value => {
    assert.ok(overlayApplied(value.final, input.set, b), "late rank A response replaced the final rank B overlay");
    return { finalRank: Number(value.final.data.pocketRank), heldDelivery: value.heldDelivery };
  });
  await step("S02-display-source-change", "Overlay on; click the load_structure history step", async () => {
    await historyStepClick(page, "load_structure");
    return waitObserve(page, obs => overlayNone(obs) && obs.native?.ready && obs.native.sourceHandle !== summary.source_handle,
      "overlay cleared on source change");
  }, async obs => {
    const notice = await panel.locator("[data-pocket-overlay-notice]").innerText();
    assert.ok(notice.includes(CONTEXT_CLEARED));
    return { notice, displayedSource: obs.native.sourceHandle };
  });
  const hold = await holdRoute(page, geoPattern, "held geometry across run switch");
  try {
    await step("S03-run-switch", `Hold rank ${a} geometry, switch run to ${input.otherRun}, release`, async () => {
      await panel.getByRole("button", { name: `포켓 rank ${a} 선택` }).click();
      const started = await hold.started;
      assert.equal(started.status, 200);
      await page.locator("#run-choice").selectOption(input.otherRun);
      await page.waitForFunction(id => new URL(location.href).searchParams.get("run") === id, input.otherRun, { timeout: 30000 });
      hold.release();
      await page.waitForTimeout(2000);
      return observe(page);
    }, async obs => {
      assert.equal(new URL(page.url()).searchParams.get("run"), input.otherRun);
      assert.ok(!obs.data || obs.data.pocketOverlay !== "applied", "late old-run overlay applied in the other run");
      assert.equal(await page.locator("[data-pocket-m9-reason]").count(), 0, "late old-run overlay disabled M9 in the other run");
      assert.equal(await page.locator("[data-viewer-request-disabled]").count(), 0, "late old-run overlay disabled M8 in the other run");
      assert.equal(await page.locator("[data-pocket-overlay-status]").count(), 0, "late old-run overlay status shown in the other run");
      return { currentRun: input.otherRun, overlay: obs.data?.pocketOverlay ?? null, delivery: hold.delivered,
        displayedSource: obs.native?.sourceHandle ?? null };
    });
  } finally { hold.release(); await hold.remove(); }
}

/** The M11 chemical-source restrictions (M8/M9/M10 controls disabled) observed through the real controls. */
async function chemicalRestrictions(page) {
  const names = ["프롬프트 사용 불가", "현재 보기 저장", "현재 보기 PNG 내보내기", "원자 거리 측정", "두 구조 비교 추가"];
  for (const name of names) assert.equal(await page.getByRole("button", { name, exact: true }).isDisabled(), true,
    `${name} is enabled for a chemical source`);
  await page.getByText(/Chemical sources are not supported by saved-scene\/export schema v1/).first().waitFor();
  return names;
}

async function modeChemicalWorkspace(session, input, rec) {
  const { page } = session;
  const { step, evidence } = rec;
  evidence.run = input.run; evidence.handles.chemicalResult = input.result;
  await page.getByRole("button", { name: "화학 상호작용 작업 열기" }).waitFor({ timeout: 60000 });
  const panel = panelOf(page, "chemical");
  await step("W01-open", "Click 화학 상호작용 작업 열기 and reopen the stored chemical result", async () => {
    await page.getByRole("button", { name: "화학 상호작용 작업 열기" }).click();
    await page.getByText("준비 입력과 실제 화학 상호작용", { exact: true }).waitFor({ timeout: 30000 });
    const select = page.locator("label").filter({ hasText: /^\s*저장된 화학 결과/ }).locator("select");
    await select.last().selectOption(input.result);
    return waitObserve(page, obs => obs.chemical?.resultHandle === input.result && obs.chemical.catalogReady &&
      obs.native?.sourceHandle === obs.chemical.sourceHandle, "chemical result shown", 60000);
  }, async obs => ({ source: obs.chemical.sourceHandle }));
  await step("W02-annotation-on", "Click the first interaction row (M11 annotation on)", async () => {
    const row = page.getByRole("region", { name: "화학 상호작용 행" }).locator("button.mw-chemical-row").first();
    await row.click();
    if (await page.getByRole("button", { name: "기하 주석 표시" }).count()) await page.getByRole("button", { name: "기하 주석 표시" }).click();
    return waitObserve(page, obs => !!obs.chemical?.annotation, "annotation shown");
  }, async obs => ({ annotationRow: obs.chemical.annotation.rowId }));
  const chemSource = (await observe(page)).chemical.sourceHandle;
  evidence.handles.chemicalSource = chemSource;
  await step("W03-panel", "Observe the chemical pocket panel and restrictions", async () => {
    await panel.waitFor({ timeout: 30000 });
    assert.equal(await panel.getByRole("combobox", { name: "포켓 검출 소스" }).inputValue(), chemSource);
    const pre = await preflightFor(page, input.run, chemSource);
    await waitPreflightText(panel, pre.selected_chains);
    return pre;
  }, async pre => {
    assert.equal(pre.ready, true, JSON.stringify(pre.reject));
    assert.equal(pre.source_kind, "chemical_structure");
    const restriction = await page.locator("[data-chemical-pocket-restriction]").innerText();
    assert.ok(restriction.includes(CHEMICAL_REASON));
    return { chains: pre.selected_chains, projectedAtoms: pre.projected_atom_count, excluded: pre.excluded_counts,
      resnameMapping: pre.resname_mapping.length, restriction };
  });
  const detected = await step("W04-detect", "Click 포켓 검출 실행 (approve if asked)", () => detect(page, panel, input.run),
    async value => ({ jobId: value.job.job_id, set: value.set, approvalSeen: value.approvalSeen }));
  evidence.handles.set = detected.set;
  const summary = await summaryOf(page, input.run, detected.set);
  assert.equal(summary.source_kind, "chemical_structure");
  evidence.summary = { total: summary.total_count, null_result: summary.null_result };
  if (!summary.null_result) {
    const rank = summary.pockets[0].rank;
    await step("W05-overlay-hides-annotation", `Click 포켓 rank ${rank} 선택 (annotation must turn off)`, async () => {
      const compared = await selectAndCompare(page, panel, input.run, detected.set, rank);
      const obs = await waitObserve(page, value => !value.chemical?.annotation, "annotation hidden");
      return { compared, annotation: obs.chemical.annotation };
    }, async value => {
      const notice = await panel.locator("[data-pocket-overlay-notice]").innerText();
      assert.ok(notice.includes("주석") && notice.includes("숨겼습니다"), notice);
      return { ...value, notice, restricted: await chemicalRestrictions(page) };
    });
    await step("W06-annotation-clears-overlay", "Click 기하 주석 표시 (overlay must be cleared)", async () => {
      await page.getByRole("button", { name: "기하 주석 표시" }).click();
      return waitObserve(page, obs => overlayNone(obs) && !!obs.chemical?.annotation, "overlay cleared by annotation");
    }, async () => {
      const notice = await panel.locator("[data-pocket-overlay-notice]").innerText();
      assert.ok(notice.includes("포켓 오버레이를 지웠습니다"), notice);
      return { notice, restricted: await chemicalRestrictions(page) };
    });
    await step("W07-clear-restrictions-stay", `Select rank ${rank}, click 오버레이 지우기; chemical restrictions remain`, async () => {
      await selectRank(page, panel, input.run, detected.set, rank);
      await panel.getByRole("button", { name: "오버레이 지우기" }).click();
      return waitObserve(page, overlayNone, "overlay cleared");
    }, async () => {
      const restriction = await page.locator("[data-chemical-pocket-restriction]").innerText();
      assert.ok(restriction.includes(CHEMICAL_REASON), "chemical restriction lifted after clearing the overlay");
      return { restriction, restricted: await chemicalRestrictions(page) };
    });
  }
  await step("W08-history-chemical", "Open 기록에서 다시 열기 in the chemical panel", async () => openHistory(page, panel), async heading => {
    assert.equal(await panel.getByRole("button", { name: `포켓 결과 다시 열기 ${shortHandle(detected.set)}` }).isEnabled(), true);
    return { heading };
  });
  await step("W09-main-cross-panel", "Click 기존 구조로 돌아가기; the main panel lists the chemical set disabled", async () => {
    await page.getByRole("tab", { name: /^run/i }).click();
    await page.getByRole("button", { name: "기존 구조로 돌아가기" }).click();
    const main = panelOf(page, "main");
    await main.waitFor({ timeout: 30000 });
    await openHistory(page, main);
    return main;
  }, async main => {
    const button = main.getByRole("button", { name: `포켓 결과 다시 열기 ${shortHandle(detected.set)}` });
    assert.equal(await button.isDisabled(), true);
    const reason = await main.locator(`[data-pocket-history="${detected.set}"]`).innerText();
    assert.ok(reason.includes("화학 작업 화면에서 열기"), reason);
    return { reason };
  });
}

async function modeReplay(session, input, rec) {
  const { page } = session;
  const { step, evidence } = rec;
  evidence.run = input.run; evidence.handles.set = input.set; evidence.handles.report = input.report;
  const panel = await openExisting(page, input);
  const guard = await withoutJobPosts(page, input.run, async () => {
    await step("Y01-capability", "Observe the unavailable engine in the events-only root", async () =>
      panel.locator("[data-pocket-capability]").getAttribute("data-pocket-capability"), async value => {
      if (input.expectCapability) assert.equal(value, input.expectCapability);
      return { capability: value };
    });
    const summary = await step("Y02-reopen", "Click 포켓 결과 다시 열기 from history", () =>
      reopenSet(page, panel, input.run, input.set), async value => ({ total: value.total_count }));
    if (!summary.null_result) {
      const compared = await step(`Y03-rank-${summary.pockets[0].rank}`, "Reconstruct the overlay from the events-only set", () =>
        selectAndCompare(page, panel, input.run, input.set, summary.pockets[0].rank), async value => value);
      evidence.overlays = [compared];
    }
    await step("Y04-report", "Click 저장된 포켓 보고서 열기; download both; bytes equal the original root", async () => {
      const made = await createReport(page, panel, input.run);
      return { made, downloads: await reportDownloads(session, panel, input.run, input.set, summary) };
    }, async value => {
      assert.equal(value.made.label, "저장된 포켓 보고서 열기");
      assert.equal(value.downloads.handle, input.report);
      assert.equal(value.downloads.markdown.sha256, input.expectMarkdownSha);
      assert.equal(value.downloads.json.sha256, input.expectJsonSha);
      return value;
    });
  });
  await step("Y05-no-new-job", "Replay created no job, command or report", async () => guard, async value => {
    assert.deepEqual(value.posts, []);
    assert.equal(value.unchanged, true);
    return value;
  });
}

const RUNNERS = { positive: modePositive, empty: modeEmpty, invalid: modeInvalid, unavailable: modeUnavailable,
  cancel: modeCancel, reopen: modeReopen, "report-download": modeReportDownload, "source-race": modeSourceRace,
  "overlay-disables": modeOverlayDisables, "comparison-block": modeComparisonBlock,
  "distance-with-overlay": modeDistanceWithOverlay, "chemical-workspace": modeChemicalWorkspace, replay: modeReplay };

function buildId() {
  try { return fs.readFileSync(path.join(REPO, "frontend/.next/BUILD_ID"), "utf8").trim(); } catch { return null; }
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const harness = fs.readFileSync(__filename);
  const evidence = { schema: "m12_pocket_evidence@1", mode: input.mode, status: "running", harnessSha256: sha(harness),
    driverSha256: shaFile(path.join(__dirname, "driver.cjs")), mainSha256: shaFile(path.join(__dirname, "main.cjs")),
    buildId: buildId(), startedAt: new Date().toISOString(), run: null, handles: {}, inputs: [], fixtureLabels: [],
    expectCapability: input.expectCapability };
  if (input.fixtureLabel) evidence.fixtureLabels.push(input.fixtureLabel);
  let session = null, failure = null, rec = null;
  const network = [];
  try {
    session = await launchOffscreen(input);
    const { app, page } = session;
    page.on("response", response => {
      if (/\/api\/runs\//.test(response.url())) network.push({ method: response.request().method(),
        path: new URL(response.url()).pathname, status: response.status() });
    });
    rec = recorder(session, input, evidence);
    evidence.offscreenStart = await offscreenProof(app, page);
    rec.append({ caseId: "offscreen-proof", status: offscreenComplete(evidence.offscreenStart) ? "pass" : "fail",
      proof: evidence.offscreenStart, baseline: fileRecord(session.baseline.screenshot) });
    assert.ok(offscreenComplete(evidence.offscreenStart), "offscreen proof incomplete at start");
    await RUNNERS[input.mode](session, input, rec);
    evidence.offscreen = await offscreenProof(app, page);
    assert.equal(evidence.offscreen.nonLoopbackRequests, 0, "renderer attempted a non-loopback request");
    evidence.status = "pass";
  } catch (error) {
    failure = error;
    evidence.status = "fail";
    evidence.error = String(error.stack ?? error);
    if (session && !evidence.offscreen) try { evidence.offscreen = await offscreenProof(session.app, session.page); }
    catch (proofError) { evidence.offscreenError = String(proofError); }
  } finally {
    evidence.network = network;
    evidence.finishedAt = new Date().toISOString();
    evidence.externalRequestCount = evidence.offscreen ? evidence.offscreen.nonLoopbackRequests : null;
    if (rec) rec.append({ caseId: "external-requests", status: evidence.externalRequestCount === 0 ? "pass" : "fail",
      externalRequestCount: evidence.externalRequestCount, blockedRequests: evidence.offscreen?.blockedRequests ?? null });
    fs.writeFileSync(path.join(input.artifacts, "pocket-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
    const pass = evidence.status === "pass" && offscreenComplete(evidence.offscreen) && evidence.externalRequestCount === 0;
    const row = { schema: "m12_case_ledger_row@1", mode: input.mode, evidenceKind: "real_electron_offscreen",
      status: pass ? "pass" : "fail", error: evidence.error ?? (pass ? null : "offscreen proof incomplete"),
      buildId: evidence.buildId, harness: { pocketFlowSha256: evidence.harnessSha256, driverSha256: evidence.driverSha256,
        mainSha256: evidence.mainSha256 },
      inputs: evidence.inputs.map(item => ({ name: item.name, sha256: item.sha256, provenance: item.provenance })),
      provenanceLabels: [...new Set(evidence.inputs.map(item => item.provenance))], fixtureLabels: evidence.fixtureLabels,
      runId: evidence.run, handles: evidence.handles, expectCapability: input.expectCapability,
      externalRequestCount: evidence.externalRequestCount, steps: rec ? rec.steps() : 0,
      offscreen: evidence.offscreen && { offscreen: evidence.offscreen.offscreen, visible: evidence.offscreen.visible,
        painting: evidence.offscreen.painting, hardwareAccelerationEnabled: evidence.offscreen.hardwareAccelerationEnabled,
        paintCount: evidence.offscreen.paintCount, firstPaint: evidence.offscreen.firstPaint, webgl: evidence.offscreen.webgl },
      artifacts: input.artifacts, evidenceFile: `pocket-${input.mode}.jsonl`,
      startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
    fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
    if (session) await session.close();
  }
  if (failure) throw failure;
}

if (require.main === module) main().catch(error => { process.stderr.write(`${error.stack ?? error}\n`); process.exitCode = 1; });
module.exports = { options, main, compareSpheres, validateReport };
