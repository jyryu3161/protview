"use strict";

// M9 real Electron offscreen scene/export suite. Product mutations use
// Playwright inputs; fetch inspects persisted objects. Projection mode has an
// explicitly labeled API-written orthographic fixture for restore coverage.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const sharp = require("sharp");
const { launchOffscreen, capture, status, downloadByClick } = require("./driver.cjs");
const { sourceDigest, waitForBoot, waitForViewer } = require("./normal-flow.cjs");

const FIELDS = ["mode", "fov", "position", "up", "target", "radius", "radiusMax", "fog", "clipFar", "minNear", "minFar"];
const CONTROL = { name: "보기 이름", save: "현재 보기 저장", saved: "저장된 보기",
  restore: "저장된 보기 복원", export: "현재 보기 PNG 내보내기",
  current: "현재 구조로 돌아가기", png: "PNG 다운로드", json: "JSON 출처 다운로드" };
const observedSceneHandles = new Map();
function uiRepresentation(stored) { return stored === "ball_and_stick" ? "ball-and-stick" : stored; }
function storedRepresentation(ui) { return ui === "ball-and-stick" ? "ball_and_stick" : ui; }

function parse(argv) {
  const input = { url: null, run: null, otherRun: null, artifacts: null, mode: "core", figure: null,
    identityFixture: path.join(__dirname, "fixtures", "m9-identities.pdb") };
  for (let i = 0; i < argv.length; i += 1) {
    const option = argv[i];
    if (option === "--url") input.url = argv[++i];
    else if (option === "--run") input.run = argv[++i];
    else if (option === "--other-run") input.otherRun = argv[++i];
    else if (option === "--artifacts") input.artifacts = argv[++i];
    else if (option === "--mode") input.mode = argv[++i];
    else if (option === "--figure") input.figure = argv[++i];
    else if (option === "--identity-fixture") input.identityFixture = argv[++i];
    else throw new Error(`Unknown argument: ${option}`);
  }
  if (!input.url || !input.run || !input.artifacts || !["core", "faults", "replay", "identity", "projection",
    "readiness", "post-races", "encoding", "restore-manual", "detail-manual", "focus-immediate",
    "scope-large", "overlap-restore"].includes(input.mode))
    throw new Error("Usage: scenes-flow.cjs --url http://127.0.0.1:3000 --run <completed isolated run> --artifacts /tmp/... [--mode core|faults|replay|identity|projection|readiness|post-races|encoding|restore-manual|detail-manual|focus-immediate|scope-large|overlap-restore] [--other-run <id>]");
  if (["readiness", "post-races"].includes(input.mode) && !input.otherRun)
    throw new Error(`${input.mode} requires --other-run`);
  const url = new URL(input.url);
  if (!["http:", "https:"].includes(url.protocol) || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname))
    throw new Error("--url must be a loopback HTTP(S) server");
  assert.match(input.run, /^run_[a-f0-9]+$/);
  if (input.otherRun) { assert.match(input.otherRun, /^run_[a-f0-9]+$/); assert.notEqual(input.otherRun, input.run); }
  if (input.figure) assert.match(input.figure, new RegExp(`^obj://${input.run}/viewer_figure/[a-f0-9]{64}$`));
  input.url = new URL(`/?run=${input.run}`, url).toString();
  input.artifacts = path.resolve(input.artifacts);
  input.identityFixture = path.resolve(input.identityFixture);
  if (input.mode === "identity") assert.ok(fs.statSync(input.identityFixture).isFile(), "Identity fixture missing");
  return input;
}

function digest(bytes) { return crypto.createHash("sha256").update(bytes).digest("hex"); }
function snapshot(camera) {
  assert.ok(camera && typeof camera === "object", "Native full camera missing");
  const result = {};
  for (const key of FIELDS) { assert.ok(Object.hasOwn(camera, key), `Native camera lacks ${key}`); result[key] = camera[key]; }
  for (const key of ["position", "target", "up"]) {
    assert.equal(result[key].length, 3);
    assert.ok(result[key].every(Number.isFinite));
  }
  return result;
}
function closeCamera(actual, expected) {
  for (const key of FIELDS) {
    if (["mode", "clipFar"].includes(key)) { assert.equal(actual[key], expected[key], `camera ${key}`); continue; }
    const values = Array.isArray(expected[key]) ? expected[key] : [expected[key]];
    const observed = Array.isArray(actual[key]) ? actual[key] : [actual[key]];
    assert.equal(observed.length, values.length);
    values.forEach((value, index) => {
      const abs = ["position", "target", "radius", "radiusMax", "minNear", "minFar"].includes(key)
        ? Math.max(1e-4, 1e-6 * Math.abs(value)) : 1e-6;
      assert.ok(Math.abs(observed[index] - value) <= abs,
        `camera ${key}[${index}] ${observed[index]} versus ${value} beyond ${abs}`);
    });
  }
}
function cameraNear(actual, expected) {
  try { closeCamera(snapshot(actual), snapshot(expected)); return true; } catch { return false; }
}
function sameResidue(actual, expected) {
  if (actual == null || expected == null) return actual == null && expected == null;
  return ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"]
    .every(key => (actual[key] ?? null) === (expected[key] ?? null));
}
function changedCamera(a, b, key) {
  const left = a?.[key], right = b?.[key];
  if (Array.isArray(left)) return left.some((number, index) => Math.abs(number - right[index]) > 1e-5);
  return left !== right && Math.abs(left - right) > 1e-5;
}
async function readJson(url) {
  const response = await fetch(url);
  assert.equal(response.status, 200, `Read-only prerequisite failed: ${url} (${response.status})`);
  return response.json();
}
async function bounded(promise, label, timeoutMs = 30000) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out`)), timeoutMs);
  })]); }
  finally { clearTimeout(timer); }
}
async function apiState(origin, run) {
  const base = new URL(`/api/runs/${run}/`, origin);
  const [scenes, figures, reports, budget, jobs] = await Promise.all(
    ["viewer/scenes", "viewer/figures", "reports", "budget", "jobs"].map(route => readJson(new URL(route, base))));
  return { scenes, figures, reports, budget, jobs };
}
async function reportByteDigests(origin, run, reports) {
  const result = {};
  for (const report of reports) {
    assert.ok(report.handle, "Saved report list contains no handle");
    for (const format of ["markdown", "json"]) {
      const url = new URL(`/api/runs/${run}/reports/download`, origin);
      url.searchParams.set("handle", report.handle);
      url.searchParams.set("format", format);
      const response = await fetch(url);
      assert.equal(response.status, 200, `Could not read saved ${format} report bytes`);
      result[`${report.handle}|${format}`] = digest(Buffer.from(await response.arrayBuffer()));
    }
  }
  return result;
}
function itemRows(value) { return Array.isArray(value) ? value : value.rows; }
async function getScene(origin, run, handle) {
  const url = new URL(`/api/runs/${run}/viewer/scenes/selected`, origin);
  url.searchParams.set("handle", handle);
  return readJson(url);
}
async function getFigure(origin, run, handle) {
  const url = new URL(`/api/runs/${run}/viewer/figures/selected`, origin);
  url.searchParams.set("handle", handle);
  return readJson(url);
}
async function waitForNative(page, predicate, timeoutMs = 30000) {
  return waitForViewer(page, viewer => viewer.nativeCamera && viewer.sourceHandle &&
    viewer.sessionId && viewer.generation !== null && predicate(viewer), timeoutMs);
}
async function waitForViewerSession(page, timeoutMs = 30000) {
  await page.getByRole("button", { name: "확대", exact: true }).waitFor({ state: "visible", timeout: timeoutMs });
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "확대");
    return !!button && !button.disabled;
  }, null, { timeout: timeoutMs });
  return waitForNative(page, viewer => !!viewer.sessionId, timeoutMs);
}
async function waitForCameraSettled(page, timeoutMs = 15000, requireBinding = true) {
  const deadline = Date.now() + timeoutMs;
  let last = null, stable = 0;
  while (Date.now() < deadline) {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const current = requireBinding ? await waitForNative(page, () => true, 1000) :
      await waitForViewer(page, viewer => viewer.nativeCamera && viewer.sourceHandle && !viewer.sessionId, 1000);
    stable = last && cameraNear(current.nativeCamera, last.nativeCamera) &&
      sameResidue(current.selection, last.selection) && current.sessionId === last.sessionId ? stable + 1 : 0;
    if (stable >= 8) return current;
    last = current;
  }
  throw new Error(`Native camera did not settle: ${JSON.stringify(last?.nativeCamera)}`);
}
function assertNative(viewer) {
  assert.equal(viewer.ready, true);
  assert.ok(viewer.sourceHandle && viewer.sessionId && viewer.generation);
  assert.ok(viewer.molstarRepresentation);
  snapshot(viewer.nativeCamera);
  assert.ok(["dark", "light"].includes(viewer.theme));
  assert.ok(Number.isInteger(viewer.backgroundColor), "Rendered background observation missing");
  return viewer;
}
async function selectedScene(page) {
  return page.getByRole("combobox", { name: CONTROL.saved }).inputValue();
}
async function saveScene(page, origin, run, name) {
  await waitForViewerSession(page);
  await page.getByRole("textbox", { name: CONTROL.name }).fill(name);
  const responsePromise = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/viewer/scenes`, { timeout: 30000 });
  await page.getByRole("button", { name: CONTROL.save }).click();
  const response = await responsePromise;
  assert.equal(response.status(), 201, `Scene save failed: ${await response.text()}`);
  const result = await response.json();
  assert.ok(result.handle);
  const durable = await getScene(origin, run, result.handle);
  assert.equal(durable.handle, result.handle);
  await page.getByText(`보기 저장 완료 · ${name}`, { exact: true }).waitFor({ timeout: 30000 });
  const choice = page.getByRole("combobox", { name: CONTROL.saved });
  await page.waitForFunction(handle => [...document.querySelectorAll("select option")]
    .some(option => option.value === handle), result.handle, { timeout: 30000 });
  assert.equal(await choice.inputValue(), result.handle, "UI did not select the saved scene");
  const known = observedSceneHandles.get(run) ?? new Set();
  known.add(result.handle); observedSceneHandles.set(run, known);
  const options = await choice.locator("option").evaluateAll(items => items.map(item => item.value));
  for (const handle of known) assert.ok(options.includes(handle), `Earlier saved scene disappeared from UI: ${handle}`);
  return durable;
}
async function restoreScene(page, scene) {
  const before = await waitForNative(page, () => true);
  await page.getByRole("combobox", { name: CONTROL.saved }).selectOption(scene.handle);
  await page.getByRole("button", { name: CONTROL.restore }).click();
  await page.getByText(`저장된 보기 복원 완료 · ${scene.value.name}`, { exact: true }).waitFor({ timeout: 45000 });
  const after = await waitForNative(page, viewer => !!viewer.sessionId && viewer.generation !== null &&
    viewer.sourceHandle === scene.value.structure_handle &&
    viewer.sessionId !== before.sessionId && viewer.generation !== before.generation &&
    viewer.representation === uiRepresentation(scene.value.representation) && viewer.theme === scene.value.theme &&
    cameraNear(viewer.nativeCamera, scene.value.camera) &&
    sameResidue(viewer.selection, scene.value.selection), 45000);
  assertNative(after);
  closeCamera(snapshot(after.nativeCamera), snapshot(scene.value.camera));
  assert.deepEqual(after.selection ?? null, scene.value.selection ?? null);
  return { before, after };
}
async function changeRepresentation(page, value) {
  await page.getByRole("group", { name: "표현 방식" }).getByRole("button", { name: value, exact: true }).click();
  return waitForNative(page, viewer => viewer.representation === value);
}
async function dragCamera(page, dx, dy, button = "left") {
  const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
  const box = await canvas.boundingBox();
  assert.ok(box, "Mol* canvas has no visible box");
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down({ button });
  await page.mouse.move(x + dx, y + dy, { steps: 12 });
  await page.mouse.up({ button });
}
async function checkPng(file, sidecar) {
  const bytes = fs.readFileSync(file);
  assert.ok(bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])));
  const decoded = sharp(bytes, { limitInputPixels: 4_000_000 });
  const metadata = await decoded.metadata();
  assert.equal(metadata.format, "png");
  assert.equal(metadata.width, sidecar.width);
  assert.equal(metadata.height, sidecar.height);
  assert.ok(metadata.width >= 64 && metadata.height >= 64);
  const { data, info } = await decoded.ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const colors = new Set();
  let occupied = 0;
  for (let y = 0; y < info.height; y += Math.max(1, Math.floor(info.height / 64))) {
    for (let x = 0; x < info.width; x += Math.max(1, Math.floor(info.width / 64))) {
      const at = (y * info.width + x) * 4;
      const color = `${data[at]},${data[at + 1]},${data[at + 2]},${data[at + 3]}`;
      colors.add(color);
      if (data[at + 3] > 0) occupied += 1;
    }
  }
  assert.ok(colors.size >= 12, `PNG appears blank/flat: ${colors.size} sampled colors`);
  assert.ok(occupied >= 100, "PNG has too few nontransparent sampled pixels");
  assert.equal(digest(bytes), sidecar.png_sha256);
  return { sha256: digest(bytes), bytes: bytes.length, width: metadata.width, height: metadata.height,
    sampledColors: colors.size, occupiedSamples: occupied };
}
async function backgroundCorner(file, color) {
  const raw = await sharp(file).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const observed = [...raw.data.subarray(0, 3)];
  const expected = [(color >>> 16) & 255, (color >>> 8) & 255, color & 255];
  expected.forEach((component, index) => assert.ok(Math.abs(observed[index] - component) <= 8,
    `PNG corner ${observed} does not match rendered background ${expected}`));
  return { observed, expected };
}

async function run(input) {
  const session = await launchOffscreen(input);
  const { app, page, artifacts } = session;
  const harnessBytes = fs.readFileSync(__filename);
  fs.writeFileSync(path.join(artifacts, "harness-source.cjs"), harnessBytes);
  fs.writeFileSync(path.join(artifacts, "harness-source.sha256"), `${digest(harnessBytes)}  harness-source.cjs\n`);
  const evidence = path.join(artifacts, `scenes-${input.mode}.jsonl`);
  const origin = new URL(page.url()).origin;
  const source = sourceDigest();
  const rows = [];
  async function step(caseId, actionDescription, action, observe) {
    const before = await status(app, page);
    let result, proof;
    try {
      result = await action();
      const assertion = await observe(result);
      proof = await capture(app, page, artifacts, caseId);
      assert.equal(proof.status.blockedRequests.length, 0, "Offscreen renderer attempted non-loopback request");
      assert.equal(proof.status.offscreen, true);
      assert.equal(proof.status.visible, false);
      assert.equal(proof.status.hardwareAccelerationEnabled, true);
      const record = { caseId, status: "pass", input: actionDescription, source, before,
        after: proof.status, assertion, screenshot: proof.screenshot, paint: proof.paint };
      rows.push(record); fs.appendFileSync(evidence, JSON.stringify(record) + "\n");
      return result;
    } catch (error) {
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* primary error kept */ }
      const record = { caseId, status: "fail", input: actionDescription, source, before,
        actionResult: result ?? null,
        after: proof?.status ?? null, error: String(error), screenshot: proof?.screenshot, paint: proof?.paint };
      rows.push(record); fs.appendFileSync(evidence, JSON.stringify(record) + "\n");
      throw error;
    }
  }
  try {
    await waitForBoot(page);
    assert.equal(new URL(page.url()).searchParams.get("run"), input.run);
    const prior = await apiState(origin, input.run);
    const originalReports = JSON.stringify(prior.reports);
    const originalReportBytes = await reportByteDigests(origin, input.run, prior.reports);
    const originalBudget = JSON.stringify(prior.budget);
    const originalJobs = JSON.stringify(prior.jobs);
    const initial = await step("V01", "Read actual ready Mol* and scene controls", async () => {
      await page.getByRole("textbox", { name: CONTROL.name }).waitFor({ timeout: 30000 });
      return waitForNative(page, () => true);
    }, async viewer => ({ viewer: assertNative(viewer), baseline: session.baseline }));

    if (input.mode === "core") {
      const originalNative = await step("V04-original-source", "Click real load_structure history row", async () => {
        const before = await waitForNative(page, () => true);
        await page.locator(".mw-step").filter({ hasText: "load_structure" }).last().click();
        return waitForNative(page, viewer => viewer.sourceHandle?.includes("/structure/") &&
          !!viewer.sessionId && viewer.sessionId !== before.sessionId);
      }, async viewer => ({ sourceHandle: viewer.sourceHandle, native: assertNative(viewer) }));
      await step("V02-invalid", "Type empty, whitespace and oversized scene names", async () => {
        const field = page.getByRole("textbox", { name: CONTROL.name });
        const button = page.getByRole("button", { name: CONTROL.save });
        for (const name of ["", "   "]) {
          await field.fill(name);
          assert.equal(await button.isDisabled(), true, `Invalid name permitted: ${JSON.stringify(name)}`);
        }
        await field.fill("x".repeat(81));
        const entered = await field.inputValue();
        assert.ok(entered.length <= 80 || await button.isDisabled(),
          "Oversized name can be submitted through the visible input");
        return { emptyBlocked: true, whitespaceBlocked: true,
          oversizedAttemptLength: 81, enteredLength: entered.length,
          oversizedTruncatedOrBlocked: true };
      }, async result => result);
      const original = await step("V03-original", "Type Unicode name and click current view save", async () =>
        saveScene(page, origin, input.run, "원본 보기 A"), async scene => {
        assert.equal(scene.value.structure_handle, originalNative.sourceHandle);
        assert.equal(scene.value.theme, originalNative.theme);
        assert.equal(scene.value.representation, storedRepresentation(originalNative.representation));
        closeCamera(snapshot(scene.value.camera), snapshot(originalNative.nativeCamera));
        return { sceneHandle: scene.handle, sourceHandle: scene.value.structure_handle };
      });
      await step("V03-identical", "Save identical canonical view again", async () =>
        saveScene(page, origin, input.run, "원본 보기 A"), async scene => {
        assert.equal(scene.handle, original.handle, "Identical scene did not reuse immutable handle");
        return { reusedHandle: scene.handle };
      });
      await step("V03-duplicate-name", "Change real representation and save the same display name", async () => {
        const changed = original.value.representation === "surface" ? "cartoon" : "surface";
        await changeRepresentation(page, changed);
        return saveScene(page, origin, input.run, "원본 보기 A");
      }, async scene => {
        assert.equal(scene.value.name, original.value.name);
        assert.notEqual(scene.handle, original.handle, "Changed view with duplicate name reused old handle");
        return { duplicateName: scene.value.name, originalHandle: original.handle,
          changedHandle: scene.handle, representation: scene.value.representation };
      });
      const prepared = await step("V04-prepared", "Click prepare_structure history row and save its historical input", async () => {
        const before = await waitForNative(page, () => true);
        await page.locator(".mw-step").filter({ hasText: "prepare_structure" }).last().click();
        const native = await waitForNative(page, viewer => viewer.sourceHandle?.includes("/prepared_structure/") &&
          !!viewer.sessionId && viewer.sessionId !== before.sessionId);
        return { native, saved: await saveScene(page, origin, input.run, "준비된 과거 구조") };
      }, async ({ native, saved }) => {
        assert.equal(saved.value.structure_kind, "prepared_structure");
        assert.equal(saved.value.structure_handle, native.sourceHandle);
        return { handle: saved.handle, sourceHandle: native.sourceHandle, model: saved.value.model_number };
      });
      const minimized = await step("V05-minimized", "Click real completed OpenMM minimized-coordinate view and save", async () => {
        const before = await waitForNative(page, () => true);
        await page.getByRole("button", { name: "최소화 단백질 좌표 보기" }).click();
        const native = await waitForNative(page, viewer => viewer.sourceHandle?.includes("/openmm_minimized_structure/") &&
          !!viewer.sessionId && viewer.sessionId !== before.sessionId, 45000);
        return { native, saved: await saveScene(page, origin, input.run, "실제 OpenMM 최소화 좌표") };
      }, async ({ native, saved }) => {
        assert.equal(saved.value.structure_kind, "openmm_minimized_structure");
        assert.equal(saved.value.structure_handle, native.sourceHandle);
        return { handle: saved.handle, sourceHandle: native.sourceHandle, model: saved.value.model_number };
      });
      for (const scene of [original, prepared.saved, minimized.saved])
        await step(`V10-source-${scene.value.structure_kind}`, "Select saved exact source and click restore", async () =>
          restoreScene(page, scene), async ({ before, after }) => ({
          sceneHandle: scene.handle, from: before.sourceHandle, sourceHandle: after.sourceHandle,
          session: after.sessionId, generation: after.generation, sourceKind: scene.value.structure_kind,
        }));

      const themes = new Map([[initial.theme, original]]);
      for (const value of ["surface", "ball-and-stick", "cartoon"]) {
        const scene = await step(`V06-${value}`, `Click ${value} and save it`, async () => {
          const native = await changeRepresentation(page, value);
          const saved = await saveScene(page, origin, input.run, `표현 ${value}`);
          return { native, saved };
        }, async ({ native, saved }) => {
          assert.equal(native.representation, value);
        assert.equal(saved.value.representation, storedRepresentation(value));
          assert.equal(await page.getByRole("group", { name: "표현 방식" })
            .getByRole("button", { name: value, exact: true }).getAttribute("aria-pressed"), "true");
          return { handle: saved.handle, representation: value };
        });
        await step(`V06-restore-${value}`, `Select saved ${value} and restore`, async () =>
          restoreScene(page, scene.saved), async ({ after }) => ({ nativeRepresentation: after.representation,
          generation: after.generation, sourceHandle: after.sourceHandle }));
      }
      await step("V07-theme", "Click theme toggle and save native rendered theme", async () => {
        const before = await waitForNative(page, () => true);
        await page.getByRole("button", { name: "테마 전환" }).click();
        const native = await waitForNative(page, viewer => viewer.theme !== before.theme &&
          viewer.backgroundColor !== before.backgroundColor);
        const saved = await saveScene(page, origin, input.run, `테마 ${native.theme}`);
        themes.set(native.theme, saved);
        return { native, saved };
      }, async ({ native, saved }) => {
        assert.equal(saved.value.theme, native.theme);
        assert.equal(await page.locator("html").getAttribute("data-theme"), native.theme);
        return { theme: native.theme, backgroundColor: native.backgroundColor, handle: saved.handle };
      });
      for (const scene of themes.values()) await step(`V07-restore-${scene.value.theme}`, "Restore saved theme", async () =>
        restoreScene(page, scene), async ({ after }) => ({ theme: after.theme, backgroundColor: after.backgroundColor }));

      const cameraBefore = await waitForNative(page, () => true);
      const moved = await step("V09-camera", "Orbit, zoom and Ctrl+Shift roll actual Mol* canvas, then save full camera", async () => {
        await dragCamera(page, 100, 45);
        const orbited = await waitForNative(page, viewer => changedCamera(cameraBefore.nativeCamera, viewer.nativeCamera, "position"));
        const canvas = page.locator("canvas.mw-molstar-canvas:visible").first();
        const box = await canvas.boundingBox(); assert.ok(box);
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        await page.mouse.wheel(0, -400);
        const zoomed = await waitForNative(page, viewer => changedCamera(orbited.nativeCamera, viewer.nativeCamera, "position"));
        await page.keyboard.down("Control");
        await page.keyboard.down("Shift");
        try { await dragCamera(page, 55, -75); }
        finally { await page.keyboard.up("Shift"); await page.keyboard.up("Control"); }
        const native = await waitForNative(page, viewer => changedCamera(zoomed.nativeCamera, viewer.nativeCamera, "up"));
        const saved = await saveScene(page, origin, input.run, "회전 확대 보기");
        return { orbited, zoomed, native, saved };
      }, async ({ native, saved }) => {
        closeCamera(snapshot(native.nativeCamera), snapshot(saved.value.camera));
        return { camera: saved.value.camera, handle: saved.handle };
      });
      await step("V09-restore", "Restore orbit and zoom through visible saved-view control", async () =>
        restoreScene(page, moved.saved), async ({ before, after }) => ({ previousGeneration: before.generation,
          generation: after.generation, fullCamera: after.nativeCamera }));
      await step("V11-same-source", "Restore exact same source/scene again", async () =>
        restoreScene(page, moved.saved), async ({ before, after }) => {
        assert.equal(after.sourceHandle, before.sourceHandle);
        return { priorSession: before.sessionId, session: after.sessionId,
          priorGeneration: before.generation, generation: after.generation };
      });
      await step("V11-rapid-A-B", "Click restore A then select and restore B without waiting for A result", async () => {
        const choice = page.getByRole("combobox", { name: CONTROL.saved });
        await choice.selectOption(original.handle);
        await page.getByRole("button", { name: CONTROL.restore }).click();
        await choice.selectOption(minimized.saved.handle);
        await page.getByRole("button", { name: CONTROL.restore }).click();
        return waitForNative(page, viewer => viewer.sourceHandle === minimized.saved.value.structure_handle &&
          cameraNear(viewer.nativeCamera, minimized.saved.value.camera));
      }, async viewer => ({ finalSource: viewer.sourceHandle, finalSession: viewer.sessionId,
        finalGeneration: viewer.generation }));
      await step("V11-current", "Click return-to-current control after scene restore", async () => {
        const before = await waitForNative(page, () => true);
        await page.getByRole("button", { name: CONTROL.current }).click();
        const after = await waitForNative(page, viewer => viewer.sourceHandle === minimized.saved.value.structure_handle &&
          viewer.sessionId !== before.sessionId && viewer.generation !== before.generation);
        return { before, after };
      }, async ({ before, after }) => ({ priorSource: before.sourceHandle, currentSource: after.sourceHandle,
        currentSession: after.sessionId, currentGeneration: after.generation }));
      await step("V15-restore-before-export", "Restore exact saved camera and source before export", async () =>
        restoreScene(page, moved.saved), async ({ after }) => ({ sceneHandle: moved.saved.handle,
          restoredSource: after.sourceHandle }));

      const exported = await step("V15-export", "Click native PNG export for restored saved scene", async () => {
        const responsePromise = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${input.run}/viewer/figures`, { timeout: 45000 });
        await page.getByRole("button", { name: CONTROL.export }).click();
        const response = await responsePromise;
        assert.equal(response.status(), 201, await response.text());
        const body = await response.json();
        return getFigure(origin, input.run, body.handle);
      }, async figure => {
        assert.equal(figure.value.scene_handle, moved.saved.handle);
        assert.equal(figure.value.structure_handle, moved.saved.value.structure_handle);
        assert.equal(figure.value.capture_method, "molstar_image_pass");
        assert.equal(figure.value.provenance, "client_rendered_local_view");
        return { figureHandle: figure.handle, value: figure.value };
      });
      for (const format of ["png", "json"]) await step(`V16-${format}`, `Click ${format} browser download`, async () => {
        const label = format === "png" ? CONTROL.png : CONTROL.json;
        return downloadByClick(app, page.getByRole("link", { name: label }));
      }, async downloaded => {
        const url = new URL(downloaded.url);
        assert.equal(url.origin, origin);
        assert.equal(url.pathname, `/api/runs/${input.run}/viewer/figures/download`);
        assert.equal(url.searchParams.get("handle"), exported.handle);
        assert.equal(url.searchParams.get("format"), format);
        const stored = await fetch(url);
        assert.equal(stored.status, 200);
        const bytes = Buffer.from(await stored.arrayBuffer());
        assert.ok(fs.readFileSync(downloaded.downloaded).equals(bytes));
        if (format === "png") return { ...downloaded, decoded: await checkPng(downloaded.downloaded, exported.value) };
        assert.deepEqual(JSON.parse(bytes.toString("utf8")), exported.value);
        return { ...downloaded, sidecarMatched: true };
      });
      for (const scene of themes.values()) await step(`V16-theme-png-${scene.value.theme}`,
        `Restore ${scene.value.theme} scene, export, and click real PNG download`, async () => {
          const restored = await restoreScene(page, scene);
          const responsePromise = page.waitForResponse(response => response.request().method() === "POST" &&
            new URL(response.url()).pathname === `/api/runs/${input.run}/viewer/figures`, { timeout: 45000 });
          await page.getByRole("button", { name: CONTROL.export }).click();
          const response = await responsePromise;
          assert.equal(response.status(), 201, await response.text());
          const figure = await getFigure(origin, input.run, (await response.json()).handle);
          const downloaded = await downloadByClick(app, page.getByRole("link", { name: CONTROL.png }));
          return { restored, figure, downloaded };
        }, async ({ restored, figure, downloaded }) => {
          assert.equal(figure.value.scene_handle, scene.handle);
          const decoded = await checkPng(downloaded.downloaded, figure.value);
          const background = await backgroundCorner(downloaded.downloaded, restored.after.backgroundColor);
          return { theme: scene.value.theme, figureHandle: figure.handle, downloaded, decoded, background };
        });
      if (input.otherRun) {
        const otherOriginState = await apiState(origin, input.otherRun);
        await step("V08-other-run", "Select saved 1HSG run through visible run selector", async () => {
          await page.locator("#run-choice").selectOption(input.otherRun);
          return waitForNative(page, viewer => viewer.sourceHandle?.includes(input.otherRun), 45000);
        }, async viewer => ({ sourceHandle: viewer.sourceHandle,
          priorSceneCount: itemRows(otherOriginState.scenes).length }));
        const selected = await step("V08-select", "Click real ligand in MODELS and save exact full residue identity", async () => {
          await page.getByRole("tab", { name: /^models/i }).click();
          await page.locator(".mw-ligand-item").first().click();
          await waitForNative(page, viewer => viewer.selection !== null);
          const native = await waitForCameraSettled(page);
          assert.ok(native.selection);
          return { native, saved: await saveScene(page, origin, input.otherRun, "선택된 MK1 리간드") };
        }, async ({ native, saved }) => {
          assert.deepEqual(saved.value.selection, native.selection);
          assert.equal(saved.value.selection.seq_label, null, "Expected 1HSG ligand's unknown label sequence");
          return { selected: saved.value.selection, sceneHandle: saved.handle };
        });
        const cleared = await step("V08-clear", "Click real clear-selection control and save empty selection", async () => {
          await page.getByRole("button", { name: "선택 해제" }).click();
          const native = await waitForNative(page, viewer => viewer.selection === null);
          return { native, saved: await saveScene(page, origin, input.otherRun, "선택 해제 보기") };
        }, async ({ native, saved }) => {
          assert.equal(native.selection, null);
          assert.equal(saved.value.selection, null);
          return { sceneHandle: saved.handle, sourceHandle: native.sourceHandle };
        });
        await step("V08-restore-selected", "Restore saved ligand selection through visible scene control", async () =>
          restoreScene(page, selected.saved), async ({ after }) => ({ selection: after.selection,
          sourceHandle: after.sourceHandle, sceneHandle: selected.saved.handle }));
        await step("V08-manual-clear", "Click manual clear after selected restore", async () => {
          await page.getByRole("button", { name: "선택 해제" }).click();
          return waitForNative(page, viewer => viewer.selection === null);
        }, async after => {
          assert.equal(after.selection, null);
          assert.deepEqual((await getScene(origin, input.otherRun, selected.saved.handle)).value.selection,
            selected.saved.value.selection);
          return { nativeSelection: null, savedSceneStillSelected: true };
        });
        await step("V08-manual-rescope", "Choose chain A scope after manual clear", async () => {
          const before = await waitForNative(page, () => true);
          await page.getByRole("combobox", { name: "뷰어 대상 체인 범위" }).selectOption("A");
          return waitForNative(page, viewer => viewer.sessionId !== before.sessionId && viewer.selection === null);
        }, async after => ({ sourceHandle: after.sourceHandle, newSession: after.sessionId,
          nativeSelection: after.selection }));
        await step("V08-restore-clear", "Restore saved cleared selection after manual scope change", async () =>
          restoreScene(page, cleared.saved), async ({ after }) => ({ selection: after.selection,
          sourceHandle: after.sourceHandle, sceneHandle: cleared.saved.handle }));
        await step("V08-return-run", "Return to completed OpenMM run via visible selector", async () => {
          await page.getByRole("tab", { name: /^run/i }).click();
          await page.locator("#run-choice").selectOption(input.run);
          return waitForNative(page, viewer => viewer.sourceHandle?.includes(input.run), 45000);
        }, async viewer => ({ sourceHandle: viewer.sourceHandle, run: input.run }));
      }
      await step("V19-unchanged", "Read old reports, budget and jobs after scene controls", async () =>
        apiState(origin, input.run), async after => {
        assert.equal(JSON.stringify(after.reports), originalReports);
        assert.deepEqual(await reportByteDigests(origin, input.run, after.reports), originalReportBytes);
        assert.equal(JSON.stringify(after.budget), originalBudget);
        assert.equal(JSON.stringify(after.jobs), originalJobs);
        return { reportsUnchanged: true, reportByteDigests: originalReportBytes,
          budgetUnchanged: true, jobsUnchanged: true,
          sceneCount: itemRows(after.scenes).length, figureCount: itemRows(after.figures).length };
      });
    } else if (input.mode === "scope-large") {
      const original = await step("V09-large-original", "Click real 1HSG original load_structure history row (>256 residues)", async () => {
        await page.locator(".mw-step").filter({ hasText: "load_structure" }).last().click();
        await page.getByRole("tab", { name: /^models/i }).click();
        const viewer = await waitForViewer(page, value => value.ready && value.nativeCamera &&
          value.sourceHandle?.startsWith(`obj://${input.run}/structure/`), 45000);
        const count = Number((await page.locator(".mw-rail-group").filter({ hasText: "표시 중인 구조" })
          .first().innerText()).match(/(\d+) residues/)?.[1]);
        assert.ok(count > 256, `Original source is not the required >256-residue case: ${count}`);
        return { viewer, count };
      }, async ({ viewer, count }) => ({ originalSource: viewer.sourceHandle, residueCount: count,
        fixture: "real original 1HSG handle from copied historical run events" }));
      const scope = page.getByRole("combobox", { name: "뷰어 정확한 대상 범위" });
      const chosen = await step("V09-large-exact-scope", "Choose visible MK1 exact residue scope on real >256 source", async () => {
        const option = scope.locator("option").filter({ hasText: /MK1/ }).first();
        const label = await option.innerText(), value = await option.getAttribute("value");
        assert.ok(value && value !== "" && /MK1/.test(label), "Exact MK1 scope option absent");
        await scope.selectOption(value);
        const viewer = await waitForNative(page, native => native.sourceHandle === original.viewer.sourceHandle, 45000);
        assert.equal(await scope.inputValue(), value);
        return { label, value, viewer };
      }, async ({ label, value, viewer }) => ({ exactOption: label, optionValue: value,
        sourceHandle: viewer.sourceHandle, sessionId: viewer.sessionId }));
      const saved = await step("V09-large-selected-save", "Click actual ligand, wait focus, save exact selected scene", async () => {
        await page.locator(".mw-ligand-item").filter({ hasText: /MK1/ }).first().click();
        const native = await waitForCameraSettled(page);
        assert.ok(native.selection && native.sourceHandle === original.viewer.sourceHandle);
        const scene = await saveScene(page, origin, input.run, `QA 1HSG >256 exact MK1 ${Date.now()}`);
        return { native, scene };
      }, async ({ native, scene }) => {
        assert.ok(sameResidue(scene.value.selection, native.selection));
        assert.equal(scene.value.structure_handle, original.viewer.sourceHandle);
        return { sceneHandle: scene.handle, exactSelection: scene.value.selection,
          fullCamera: scene.value.camera };
      });
      await step("V09-large-restore-scope", "Restore selected scene and inspect truthful exact-scope UI", async () => {
        await page.getByRole("button", { name: "선택 해제" }).click();
        await waitForNative(page, native => native.selection === null);
        await restoreScene(page, saved.scene);
        const value = await scope.inputValue();
        const label = await scope.locator(`option[value="${value}"]`).innerText();
        return { value, label, native: await waitForNative(page, native =>
          sameResidue(native.selection, saved.scene.value.selection)) };
      }, async ({ value, label, native }) => {
        assert.equal(value, chosen.value, "Restored exact scope was displayed as All or the wrong residue");
        assert.equal(label, chosen.label);
        assert.ok(sameResidue(native.selection, saved.scene.value.selection));
        return { selectedScopeValue: value, selectedScopeLabel: label,
          selectedResidue: native.selection, sessionId: native.sessionId };
      });
      await step("V09-large-manual-all-chain", "Clear selection, manually choose All then chain A; old saved exact scope must not reassert", async () => {
        await page.getByRole("button", { name: "선택 해제" }).click();
        await waitForNative(page, native => native.selection === null);
        await scope.selectOption("");
        assert.equal(await scope.inputValue(), "");
        await page.getByRole("combobox", { name: "뷰어 대상 체인 범위" }).selectOption("A");
        const native = await waitForNative(page, value => value.sourceHandle === original.viewer.sourceHandle &&
          value.selection === null && value.sessionId !== chosen.viewer.sessionId, 45000);
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        return { native, exactValue: await scope.inputValue(),
          chainValue: await page.getByRole("combobox", { name: "뷰어 대상 체인 범위" }).inputValue() };
      }, async ({ native, exactValue, chainValue }) => {
        assert.equal(exactValue, "", "Old saved exact scope reasserted after manual chain choice");
        assert.equal(chainValue, "A");
        assert.equal(native.selection, null);
        return { sourceHandle: native.sourceHandle, newSession: native.sessionId,
          chainValue, exactValue, manualSelection: native.selection };
      });
    } else if (input.mode === "overlap-restore") {
      const scenes = itemRows(prior.scenes);
      const a = scenes.find(scene => scene.value.structure_handle !== initial.sourceHandle);
      const b = scenes.find(scene => scene.value.structure_handle === initial.sourceHandle &&
        scene.handle !== a?.handle);
      assert.ok(a && b, "Overlapping restore needs saved A/B scenes with different real source handles");
      const sessionPattern = `**/api/runs/${input.run}/viewer/sessions`;
      const detailPattern = `**/api/runs/${input.run}/viewer/scenes/selected?*`;
      let releaseSession, startedSession, releaseDetail, startedDetail;
      const sessionGate = new Promise(resolve => { releaseSession = resolve; });
      const sessionSeen = new Promise(resolve => { startedSession = resolve; });
      const detailGate = new Promise(resolve => { releaseDetail = resolve; });
      const detailSeen = new Promise(resolve => { startedDetail = resolve; });
      const holdSession = async route => {
        if (route.request().method() !== "POST") { await route.continue(); return; }
        const response = await route.fetch();
        startedSession({ status: response.status(), url: route.request().url() });
        await sessionGate;
        try { await route.fulfill({ response }); } catch { /* cancelled A session */ }
      };
      const holdDetail = async route => {
        if (new URL(route.request().url()).searchParams.get("handle") !== b.handle) {
          await route.continue(); return;
        }
        const response = await route.fetch();
        startedDetail({ status: response.status(), url: route.request().url() });
        await detailGate;
        try { await route.fulfill({ response }); } catch { /* cancelled B read */ }
      };
      await page.route(sessionPattern, holdSession);
      await page.route(detailPattern, holdDetail);
      try {
        await step("V17-overlap-A-held-B-read", "Start A restore with real session POST held, then B restore with real scene detail GET held", async () => {
          await page.getByRole("combobox", { name: CONTROL.saved }).selectOption(a.handle);
          await page.getByRole("button", { name: CONTROL.restore }).click();
          const heldA = await bounded(sessionSeen, "Expected A viewer session POST", 45000);
          assert.equal(heldA.status, 201);
          const pendingA = await waitForViewer(page, value => value.ready && value.nativeCamera &&
            value.sourceHandle === a.value.structure_handle && !value.sessionId, 30000);
          await page.getByRole("combobox", { name: CONTROL.saved }).selectOption(b.handle);
          await page.getByRole("button", { name: CONTROL.restore }).click();
          const heldB = await bounded(detailSeen, "Expected B saved-scene detail GET", 30000);
          assert.equal(heldB.status, 200);
          releaseSession();
          await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
          const midpoint = { heldA, heldB, pendingA, status: await page.locator("body").innerText() };
          fs.writeFileSync(path.join(artifacts, "overlap-restore-midpoint.json"),
            JSON.stringify(midpoint, null, 2) + "\n");
          assert.match(midpoint.status, /읽는 중/, "Older A completion cleared B's pending read indicator");
          assert.equal(midpoint.status.includes(`저장된 보기 복원 완료 · ${a.value.name}`), false,
            "Older A falsely claimed completion while B restore was pending");
          releaseDetail();
          await page.getByText(`저장된 보기 복원 완료 · ${b.value.name}`, { exact: true })
            .waitFor({ timeout: 45000 });
          const final = await waitForNative(page, value => value.sourceHandle === b.value.structure_handle &&
            value.representation === uiRepresentation(b.value.representation) &&
            sameResidue(value.selection, b.value.selection) &&
            cameraNear(value.nativeCamera, b.value.camera), 45000);
          return { heldA, heldB, pendingA, final };
        }, async ({ heldA, heldB, pendingA, final }) => {
          closeCamera(snapshot(final.nativeCamera), snapshot(b.value.camera));
          assert.deepEqual(final.selection ?? null, b.value.selection ?? null);
          assert.notEqual(final.sessionId, pendingA.sessionId);
          return { fixture: "unchanged real A viewer-session POST and B scene detail GET held in renderer",
            a: a.handle, b: b.handle, heldA, heldB, finalSource: final.sourceHandle,
            finalSession: final.sessionId, finalCamera: final.nativeCamera };
        });
      } finally {
        releaseSession(); releaseDetail();
        await page.unroute(detailPattern, holdDetail);
        await page.unroute(sessionPattern, holdSession);
      }
    } else if (input.mode === "focus-immediate") {
      await step("V08-immediate-focus-save", "Click ligand and immediately click Save without QA camera settle delay", async () => {
        await page.getByRole("tab", { name: /^models/i }).click();
        await page.locator(".mw-ligand-item").first().click();
        const saved = await saveScene(page, origin, input.run, `QA immediate focus ${Date.now()}`);
        const native = await waitForCameraSettled(page);
        return { saved, native };
      }, async ({ saved, native }) => {
        assert.ok(saved.value.selection);
        assert.ok(sameResidue(saved.value.selection, native.selection));
        closeCamera(snapshot(native.nativeCamera), snapshot(saved.value.camera));
        return { savedHandle: saved.handle, sourceHandle: native.sourceHandle,
          selected: native.selection, fullCamera: native.nativeCamera };
      });
    } else if (input.mode === "detail-manual") {
      const scene = itemRows(prior.scenes).find(item => item.value.structure_handle === initial.sourceHandle);
      assert.ok(scene, "Detail-read manual race requires a same-source saved scene");
      const selectedPattern = `**/api/runs/${input.run}/viewer/scenes/selected?*`;
      let release, intercepted;
      const gate = new Promise(resolve => { release = resolve; });
      const seen = new Promise(resolve => { intercepted = resolve; });
      const hold = async route => {
        const response = await route.fetch();
        intercepted({ status: response.status(), url: route.request().url() });
        await gate;
        try { await route.fulfill({ response }); } catch { /* cancelled request is expected */ }
      };
      await page.route(selectedPattern, hold);
      try {
        await step("V17-manual-during-scene-read", "Hold unchanged real scene detail GET; orbit current viewer; release", async () => {
          const before = await waitForCameraSettled(page);
          await page.getByRole("combobox", { name: CONTROL.saved }).selectOption(scene.handle);
          await page.getByRole("button", { name: CONTROL.restore }).click();
          const held = await bounded(seen, "Expected scene detail GET", 30000);
          assert.equal(held.status, 200);
          await dragCamera(page, 105, 55);
          const manual = await waitForCameraSettled(page);
          assert.ok(changedCamera(before.nativeCamera, manual.nativeCamera, "position"));
          fs.writeFileSync(path.join(artifacts, "detail-manual-midpoint.json"), JSON.stringify({
            fixture: "unchanged real selected-scene GET held", before, manual, held,
          }, null, 2) + "\n");
          release();
          await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
          return { held, before, manual, final: await waitForCameraSettled(page) };
        }, async ({ held, before, manual, final }) => {
          assert.equal(final.sourceHandle, before.sourceHandle);
          assert.equal(cameraNear(final.nativeCamera, manual.nativeCamera), true,
            "Late scene detail GET overwrote newer manual orbit");
          assert.equal((await page.locator("body").innerText()).includes(`저장된 보기 복원 완료 · ${scene.value.name}`), false,
            "UI falsely claimed a restore after manual orbit");
          return { held, sceneHandle: scene.handle, manualCamera: manual.nativeCamera,
            finalCamera: final.nativeCamera };
        });
      } finally { release(); await page.unroute(selectedPattern, hold); }
      const deny = route => route.fulfill({ status: 503, contentType: "application/json",
        body: JSON.stringify({ detail: { error: "qa_injected_scene_read_503", message: "Labeled scene detail read fault" } }) });
      await page.route(selectedPattern, deny);
      try {
        await step("V13-failed-detail-current-usable", "Click Restore under labeled 503 and then real local representation control", async () => {
          await page.getByRole("combobox", { name: CONTROL.saved }).selectOption(scene.handle);
          await page.getByRole("button", { name: CONTROL.restore }).click();
          await page.getByRole("alert").filter({ hasText: /저장된 보기 읽기 실패/ }).waitFor({ timeout: 30000 });
          const before = await waitForNative(page, () => true);
          const next = before.representation === "surface" ? "cartoon" : "surface";
          await changeRepresentation(page, next);
          return { before, next };
        }, async ({ before, next }) => {
          const after = await waitForNative(page, viewer => viewer.representation === next);
          assert.equal(after.sourceHandle, before.sourceHandle);
          return { sourceHandle: after.sourceHandle, representation: next,
            fixture: "renderer-scoped 503; local viewer remained usable" };
        });
      } finally { await page.unroute(selectedPattern, deny); }
    } else if (input.mode === "restore-manual") {
      const scenes = itemRows(prior.scenes);
      const scene = scenes.find(item => item.value.structure_kind === "structure") ?? scenes[0];
      assert.ok(scene, "Manual restore race requires a persisted saved scene");
      const sessionPattern = `**/api/runs/${input.run}/viewer/sessions`;
      let release, intercepted;
      const gate = new Promise(resolve => { release = resolve; });
      const seen = new Promise(resolve => { intercepted = resolve; });
      const hold = async route => {
        if (route.request().method() !== "POST") { await route.continue(); return; }
        const response = await route.fetch();
        intercepted({ status: response.status(), url: route.request().url() });
        await gate;
        try { await route.fulfill({ response }); } catch { /* old request may be cancelled */ }
      };
      await page.route(sessionPattern, hold);
      try {
        await step("V17-manual-before-restore-session", "Hold real new viewer-session POST response, orbit native canvas, release", async () => {
          await page.getByRole("combobox", { name: CONTROL.saved }).selectOption(scene.handle);
          await page.getByRole("button", { name: CONTROL.restore }).click();
          const held = await bounded(seen, "Expected real restore session POST", 45000);
          assert.equal(held.status, 201);
          const unbound = await waitForViewer(page, viewer => viewer.ready && viewer.nativeCamera &&
            viewer.sourceHandle === scene.value.structure_handle && !viewer.sessionId, 30000);
          await dragCamera(page, 110, 60);
          const manual = await waitForCameraSettled(page, 15000, false);
          assert.ok(changedCamera(unbound.nativeCamera, manual.nativeCamera, "position"),
            "Real pointer orbit did not change native camera while session response was held");
          fs.writeFileSync(path.join(artifacts, "restore-manual-midpoint.json"), JSON.stringify({
            fixture: "unchanged real session POST held after backend commit",
            sceneHandle: scene.handle, held, unbound, manual,
          }, null, 2) + "\n");
          release();
          await waitForNative(page, viewer => viewer.sourceHandle === scene.value.structure_handle, 30000);
          await page.getByText("복원 중…", { exact: true }).waitFor({ state: "hidden", timeout: 15000 });
          const final = await waitForCameraSettled(page);
          return { held, unbound, manual, final };
        }, async ({ held, unbound, manual, final }) => {
          assert.equal(cameraNear(final.nativeCamera, manual.nativeCamera), true,
            "Late restore overwrote the newer manual camera orbit");
          assert.equal(cameraNear(final.nativeCamera, scene.value.camera), false,
            "Late restore applied saved camera after manual orbit");
          assert.equal((await page.locator("body").innerText()).includes(`저장된 보기 복원 완료 · ${scene.value.name}`), false,
            "UI falsely claimed restore applied after manual orbit");
          return { fixture: "unchanged real session POST response held after backend commit",
            sceneHandle: scene.handle, unboundSession: unbound.sessionId,
            manualCamera: manual.nativeCamera, finalCamera: final.nativeCamera, held };
        });
      } finally { release(); await page.unroute(sessionPattern, hold); }
    } else if (input.mode === "readiness") {
      const sessionPattern = `**/api/runs/${input.run}/viewer/sessions`;
      const denySession = route => route.fulfill({ status: 503, contentType: "application/json",
        body: JSON.stringify({ detail: { error: "qa_injected_session_503", message: "Labeled M9 QA session creation fault" } }) });
      await page.locator("#run-choice").selectOption(input.otherRun);
      await waitForNative(page, viewer => viewer.sourceHandle?.includes(input.otherRun));
      await page.route(sessionPattern, denySession);
      try {
        await step("V12-session-503", "Switch to target run with labeled viewer-session POST 503", async () => {
          await page.locator("#run-choice").selectOption(input.run);
          return waitForViewer(page, viewer => viewer.ready && viewer.nativeCamera &&
            viewer.sourceHandle?.includes(input.run) && !viewer.sessionId, 45000);
        }, async viewer => {
          assert.equal(await page.getByRole("button", { name: CONTROL.save }).isDisabled(), true,
            "Save enabled without stable viewer session");
          assert.equal(await page.getByRole("button", { name: CONTROL.export }).isDisabled(), true);
          return { nativeReady: viewer.ready, sessionId: viewer.sessionId,
            fixture: "renderer-scoped viewer session POST 503" };
        });
      } finally { await page.unroute(sessionPattern, denySession); }
      await step("V12-session-retry", "Switch away and back after removing session fault", async () => {
        await page.locator("#run-choice").selectOption(input.otherRun);
        await waitForNative(page, viewer => viewer.sourceHandle?.includes(input.otherRun));
        await page.locator("#run-choice").selectOption(input.run);
        await waitForViewerSession(page, 45000);
        return waitForNative(page, viewer => viewer.sourceHandle?.includes(input.run) && !!viewer.sessionId);
      }, async viewer => ({ sessionId: viewer.sessionId, generation: viewer.generation,
        sourceHandle: viewer.sourceHandle }));
      const sourcePattern = `**/api/runs/${input.run}/structures/bytes?*`;
      let release, intercepted;
      const gate = new Promise(resolve => { release = resolve; });
      const seen = new Promise(resolve => { intercepted = resolve; });
      const hold = async route => {
        const response = await route.fetch();
        intercepted({ status: response.status(), url: route.request().url() });
        await gate;
        try { await route.fulfill({ response }); } catch { /* old navigation cancelled */ }
      };
      await page.locator("#run-choice").selectOption(input.otherRun);
      await waitForNative(page, viewer => viewer.sourceHandle?.includes(input.otherRun));
      await page.route(sourcePattern, hold);
      try {
        await step("V12-held-source", "Hold unchanged real source bytes, inspect disabled save/export, switch away", async () => {
          await page.locator("#run-choice").selectOption(input.run);
          const held = await bounded(seen, "Expected real source read", 30000);
          assert.equal(held.status, 200);
          assert.equal(await page.getByRole("button", { name: CONTROL.save }).isDisabled(), true);
          assert.equal(await page.getByRole("button", { name: CONTROL.export }).isDisabled(), true);
          await page.locator("#run-choice").selectOption(input.otherRun);
          release();
          return waitForNative(page, viewer => viewer.sourceHandle?.includes(input.otherRun), 45000);
        }, async viewer => ({ finalSource: viewer.sourceHandle, heldReadReleased: true,
          fixture: "unchanged real loopback source response held during run switch" }));
      } finally { release(); await page.unroute(sourcePattern, hold); }
    } else if (input.mode === "post-races") {
      const otherBefore = await apiState(origin, input.otherRun);
      const heldName = `QA held scene ${Date.now()}`;
      const scenePost = `**/api/runs/${input.run}/viewer/scenes`;
      let sceneRelease, sceneSeen;
      const sceneGate = new Promise(resolve => { sceneRelease = resolve; });
      const sceneStarted = new Promise(resolve => { sceneSeen = resolve; });
      const holdScene = async route => {
        if (route.request().method() !== "POST") { await route.continue(); return; }
        const response = await route.fetch();
        sceneSeen({ status: response.status(), body: await response.json() });
        await sceneGate;
        try { await route.fulfill({ response }); } catch { /* old client request cancelled */ }
      };
      await page.route(scenePost, holdScene);
      try {
        await step("V17-scene-post", "Click Save, hold real committed POST response, switch run, release", async () => {
          await waitForViewerSession(page);
          await page.getByRole("textbox", { name: CONTROL.name }).fill(heldName);
          await page.getByRole("button", { name: CONTROL.save }).click();
          const held = await bounded(sceneStarted, "Expected real scene POST", 45000);
          assert.equal(held.status, 201);
          await page.locator("#run-choice").selectOption(input.otherRun);
          sceneRelease();
          await waitForNative(page, viewer => viewer.sourceHandle?.includes(input.otherRun));
          return held;
        }, async held => {
          const other = await apiState(origin, input.otherRun);
          assert.equal(itemRows(other.scenes).length, itemRows(otherBefore.scenes).length);
          assert.equal(await page.getByRole("combobox", { name: CONTROL.saved }).locator(`option[value="${held.body.handle}"]`).count(), 0);
          return { committedOldScene: held.body.handle, finalRun: input.otherRun, staleOptionAbsent: true };
        });
      } finally { sceneRelease(); await page.unroute(scenePost, holdScene); }
      await page.locator("#run-choice").selectOption(input.run);
      await waitForViewerSession(page, 45000);
      const scenes = itemRows((await apiState(origin, input.run)).scenes);
      const scene = scenes.find(item => item.value.name === heldName) ?? scenes[0];
      assert.ok(scene, "Figure POST race needs a saved scene");
      await restoreScene(page, scene);
      const oldFigureCount = itemRows((await apiState(origin, input.run)).figures).length;
      let figureRelease, figureSeen;
      const figureGate = new Promise(resolve => { figureRelease = resolve; });
      const figureStarted = new Promise(resolve => { figureSeen = resolve; });
      const figurePost = `**/api/runs/${input.run}/viewer/figures`;
      const holdFigure = async route => {
        if (route.request().method() !== "POST") { await route.continue(); return; }
        const response = await route.fetch();
        figureSeen({ status: response.status(), body: await response.json() });
        await figureGate;
        try { await route.fulfill({ response }); } catch { /* old client request cancelled */ }
      };
      await page.route(figurePost, holdFigure);
      try {
        await step("V17-figure-post", "Click Export, hold real committed figure POST response, switch run, release", async () => {
          await page.getByRole("button", { name: CONTROL.export }).click();
          const held = await bounded(figureStarted, "Expected real figure POST", 60000);
          assert.equal(held.status, 201);
          await page.locator("#run-choice").selectOption(input.otherRun);
          figureRelease();
          await waitForNative(page, viewer => viewer.sourceHandle?.includes(input.otherRun));
          return held;
        }, async held => {
          const old = await apiState(origin, input.run), other = await apiState(origin, input.otherRun);
          assert.ok(itemRows(old.figures).length > oldFigureCount);
          assert.equal(itemRows(other.figures).length, itemRows(otherBefore.figures).length);
          assert.equal(await page.getByRole("combobox", { name: "저장된 그림" })
            .locator(`option[value="${held.body.handle}"]`).count(), 0);
          return { committedOldFigure: held.body.handle, finalRun: input.otherRun,
            staleFigureOptionAbsent: true };
        });
      } finally { figureRelease(); await page.unroute(figurePost, holdFigure); }
    } else if (input.mode === "encoding") {
      const scenes = itemRows(prior.scenes);
      assert.ok(scenes.length, "Encoding fault QA requires a saved scene");
      const scene = scenes[0];
      await restoreScene(page, scene);
      const figureCount = itemRows(prior.figures).length;
      await step("V14-encode-null", "Labeled browser toBlob null fixture; click actual export", async () => {
        await page.evaluate(() => {
          const proto = HTMLCanvasElement.prototype;
          window.__m9OriginalToBlob = proto.toBlob;
          proto.toBlob = function(callback, ...args) {
            proto.toBlob = window.__m9OriginalToBlob;
            callback(null);
          };
        });
        await page.getByRole("button", { name: CONTROL.export }).click();
        await page.getByRole("alert").filter({ hasText: /PNG 내보내기 실패/ }).waitFor({ timeout: 45000 });
      }, async () => {
        const after = await apiState(origin, input.run);
        assert.equal(itemRows(after.figures).length, figureCount);
        return { visibleError: await page.getByRole("alert").filter({ hasText: /PNG 내보내기 실패/ }).innerText(),
          fixture: "one-shot HTMLCanvasElement.toBlob(null); actual Mol* capture attempted", newFigure: false };
      });
      await page.evaluate(() => { if (window.__m9OriginalToBlob) HTMLCanvasElement.prototype.toBlob = window.__m9OriginalToBlob; });
      await restoreScene(page, scene);
      await step("V17-manual-during-encode", "Hold real PNG encoding, click representation, release original toBlob", async () => {
        await page.evaluate(() => {
          const original = HTMLCanvasElement.prototype.toBlob;
          window.__m9OriginalToBlob = original;
          window.__m9BlobStarted = false;
          HTMLCanvasElement.prototype.toBlob = function(callback, ...args) {
            const canvas = this;
            window.__m9BlobStarted = true;
            window.__m9ReleaseToBlob = () => original.call(canvas, callback, ...args);
          };
        });
        await page.getByRole("button", { name: CONTROL.export }).click();
        await page.waitForFunction(() => window.__m9BlobStarted === true, null, { timeout: 45000 });
        const before = await waitForNative(page, () => true);
        const next = before.representation === "surface" ? "cartoon" : "surface";
        await page.getByRole("group", { name: "표현 방식" }).getByRole("button", { name: next }).click();
        await page.evaluate(() => {
          HTMLCanvasElement.prototype.toBlob = window.__m9OriginalToBlob;
          window.__m9ReleaseToBlob();
        });
        await page.getByRole("alert").filter({ hasText: /PNG 내보내기 실패/ }).waitFor({ timeout: 45000 });
        return { before: before.representation, after: next };
      }, async result => {
        const after = await apiState(origin, input.run);
        assert.equal(itemRows(after.figures).length, figureCount);
        return { ...result, visibleError: await page.getByRole("alert")
          .filter({ hasText: /PNG 내보내기 실패/ }).innerText(), newFigure: false,
          fixture: "delayed original toBlob; representation changed by real click" };
      });
      await page.evaluate(() => { if (window.__m9OriginalToBlob) HTMLCanvasElement.prototype.toBlob = window.__m9OriginalToBlob; });
      const denyCapacity = route => route.fulfill({ status: 429, contentType: "application/json",
        body: JSON.stringify({ detail: { error: "resource_exceeded", message: "Labeled M9 QA scene capacity fixture" } }) });
      const savePattern = `**/api/runs/${input.run}/viewer/scenes`;
      await page.route(savePattern, denyCapacity);
      try {
        await step("V18-capacity-429", "Labeled scene admission 429; click actual Save", async () => {
          await waitForViewerSession(page);
          await page.getByRole("textbox", { name: CONTROL.name }).fill("QA capacity retry");
          await page.getByRole("button", { name: CONTROL.save }).click();
          await page.getByRole("alert").filter({ hasText: /보기 저장 실패/ }).waitFor({ timeout: 30000 });
        }, async () => ({ visibleError: await page.getByRole("alert")
          .filter({ hasText: /보기 저장 실패/ }).innerText(),
          fixture: "renderer-scoped 429; real backend capacity tested separately" }));
      } finally { await page.unroute(savePattern, denyCapacity); }
      await step("V18-capacity-retry", "Remove 429 and click Save again", async () =>
        saveScene(page, origin, input.run, "QA capacity retry"), async saved => ({
          savedHandle: saved.handle, realBackendAdmission: true }));
    } else if (input.mode === "projection") {
      const perspective = await step("V09-projection-base", "Click save for real native perspective base scene", async () =>
        saveScene(page, origin, input.run, "QA 투영 기준"), async scene => {
        assert.equal(scene.value.camera.mode, "perspective");
        return { sceneHandle: scene.handle, cameraMode: scene.value.camera.mode };
      });
      const projected = await step("V09-orthographic-fixture", "Labeled loopback fixture setup: save same current binding with orthographic camera mode", async () => {
        const native = await waitForNative(page, () => true);
        const sessionUrl = new URL(`/api/runs/${input.run}/viewer/sessions/${native.sessionId}`, origin);
        const binding = await readJson(sessionUrl);
        assert.equal(binding.current, true);
        const body = { schema: "viewer_scene@1", request_id: crypto.randomUUID(),
          client_instance_id: binding.client_instance_id, viewer_session_id: binding.viewer_session_id,
          scene_generation: binding.scene_generation, action_revision: binding.action_revision,
          name: "QA fixture orthographic", structure_handle: perspective.value.structure_handle,
          selection: perspective.value.selection, representation: perspective.value.representation,
          camera: { ...perspective.value.camera, mode: "orthographic" }, theme: perspective.value.theme };
        const response = await fetch(new URL(`/api/runs/${input.run}/viewer/scenes`, origin), {
          method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
        });
        if (response.status !== 201)
          throw new Error(`Orthographic fixture setup failed (${response.status}): ${await response.text()}`);
        return response.json();
      }, async scene => ({ fixture: "API-created orthographic scene from real current binding; not a UI save",
        handle: scene.handle, source: scene.value.structure_handle, mode: scene.value.camera.mode }));
      await step("V09-orthographic-restore", "Reload and click saved orthographic scene restore in real Electron viewer", async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await waitForBoot(page);
        return restoreScene(page, projected);
      }, async ({ after }) => {
        assert.equal(after.nativeCamera.mode, "orthographic");
        return { sourceHandle: after.sourceHandle, nativeCamera: after.nativeCamera,
          fixtureSceneHandle: projected.handle };
      });
    } else if (input.mode === "identity") {
      let fixtureRun;
      await step("V08-identity-upload", "Create local-only run; choose labeled synthetic PDB with real file chooser", async () => {
        await page.getByRole("button", { name: "새 run" }).click();
        await page.waitForFunction(previous => {
          const now = new URL(location.href).searchParams.get("run");
          return !!now && now !== previous;
        }, input.run);
        fixtureRun = new URL(page.url()).searchParams.get("run");
        assert.equal(await page.getByRole("button", { name: CONTROL.save }).isDisabled(), true);
        assert.equal(await page.getByRole("button", { name: CONTROL.export }).isDisabled(), true);
        const chooser = page.waitForEvent("filechooser");
        await page.locator('input[type="file"]').click();
        await (await chooser).setFiles(input.identityFixture);
        await page.getByRole("button", { name: "구조 불러오기" }).waitFor({ timeout: 30000 });
        return fixtureRun;
      }, async runId => ({ runId, fixture: path.basename(input.identityFixture),
        sha256: digest(fs.readFileSync(input.identityFixture)), synthetic: true }));
      const identityScene = await step("V08-identity-model-selection", "Choose model index 1, load actual synthetic bytes, select A 42A, and save", async () => {
        await page.getByRole("button", { name: "구조 불러오기" }).locator("..").locator("select").first().selectOption("1");
        await page.getByRole("button", { name: "구조 불러오기" }).click();
        await waitForNative(page, viewer => viewer.sourceHandle?.includes(fixtureRun));
        await page.getByRole("combobox", { name: "뷰어 대상 선택" }).selectOption({ index: 1 });
        const native = await waitForNative(page, viewer => viewer.selection?.model_number === 2 &&
          viewer.selection?.seq_auth === 42 && viewer.selection?.icode === "A");
        return { native, saved: await saveScene(page, origin, fixtureRun, "합성 model 2 · A 42A") };
      }, async ({ native, saved }) => {
        assert.equal(native.selection.seq_label, null);
        assert.equal(saved.value.model_number, 2);
        assert.equal(saved.value.selection.icode, "A");
        assert.equal(saved.value.selection.seq_label, null);
        assert.deepEqual(saved.value.selection, native.selection);
        return { runId: fixtureRun, sceneHandle: saved.handle, selected: saved.value.selection };
      });
      await step("V08-identity-reopen", "Reopen actual synthetic run in Electron and click restore", async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await waitForBoot(page);
        const durable = await getScene(origin, fixtureRun, identityScene.saved.handle);
        return restoreScene(page, durable);
      }, async ({ before, after }) => {
        assert.equal(after.selection.icode, "A");
        assert.equal(after.selection.seq_label, null);
        return { beforeSession: before.sessionId, afterSession: after.sessionId,
          sourceHandle: after.sourceHandle, selected: after.selection };
      });
    } else if (input.mode === "replay") {
      const scenes = itemRows(prior.scenes), figures = itemRows(prior.figures);
      assert.ok(scenes.length >= 1 && figures.length >= 1, "Replay QA needs persisted scene and figure");
      for (const sceneSummary of scenes) {
        const scene = await getScene(origin, input.run, sceneSummary.handle);
        await step(`V10-${scenes.indexOf(sceneSummary)}`, "Select persisted scene after browser reopen; click restore", async () =>
          restoreScene(page, scene), async ({ after }) => ({ handle: scene.handle,
          sourceHandle: after.sourceHandle, generation: after.generation, camera: after.nativeCamera }));
      }
      const chosenFigure = input.figure ?? figures[0].handle;
      assert.ok(figures.some(item => item.handle === chosenFigure), "Requested successful replay figure is absent");
      const figure = await getFigure(origin, input.run, chosenFigure);
      await page.getByRole("combobox", { name: "저장된 그림" }).selectOption(figure.handle);
      for (const format of ["png", "json"]) await step(`V16-replay-${format}`, `Click persisted ${format} download`, async () =>
        downloadByClick(app, page.getByRole("link", { name: format === "png" ? CONTROL.png : CONTROL.json })),
      async downloaded => {
        const saved = await fetch(downloaded.url);
        assert.equal(saved.status, 200);
        assert.ok(fs.readFileSync(downloaded.downloaded).equals(Buffer.from(await saved.arrayBuffer())));
        return format === "png" ? checkPng(downloaded.downloaded, figure.value) :
          { sha256: digest(fs.readFileSync(downloaded.downloaded)), exactStoredBytes: true };
      });
    } else {
      assert.ok(itemRows(prior.scenes).length, "Fault QA needs one saved scene");
      const scene = await getScene(origin, input.run, itemRows(prior.scenes)[0].handle);
      const selectedUrl = `**/api/runs/${input.run}/viewer/scenes/selected?*`;
      const deny = route => route.fulfill({ status: 503, contentType: "application/json",
        body: JSON.stringify({ detail: { error: "qa_injected_read_503", message: "Labeled M9 QA scene read fault" } }) });
      await page.route(selectedUrl, deny);
      try {
        await step("V13-fault", "Inject labeled 503 for selected scene GET; click restore", async () => {
          const responsePromise = page.waitForResponse(response => response.request().method() === "GET" &&
            new URL(response.url()).pathname === `/api/runs/${input.run}/viewer/scenes/selected` &&
            new URL(response.url()).searchParams.get("handle") === scene.handle && response.status() === 503,
          { timeout: 30000 });
          await page.getByRole("combobox", { name: CONTROL.saved }).selectOption(scene.handle);
          await page.getByRole("button", { name: CONTROL.restore }).click();
          const response = await responsePromise;
          const alert = page.getByRole("alert").filter({ hasText: /저장된 보기 읽기 실패/ });
          await alert.waitFor({ timeout: 30000 });
          return { responseStatus: response.status(), visibleError: await alert.innerText() };
        }, async ({ responseStatus, visibleError }) => {
          assert.equal(responseStatus, 503);
          assert.match(visibleError, /저장된 보기 읽기 실패/);
          return { responseStatus, visibleError, fixture: "renderer-scoped 503 on exact scene GET" };
        });
      } finally { await page.unroute(selectedUrl, deny); }
      await step("V13-retry", "Remove 503 and click visible scene retry", async () => {
        await page.getByRole("button", { name: /저장된 보기.*다시/ }).click();
        return restoreScene(page, scene);
      }, async ({ before, after }) => ({ sourceHandle: after.sourceHandle, ready: after.ready,
        oldSession: before.sessionId, freshSession: after.sessionId,
        theme: after.theme, representation: after.representation,
        selection: after.selection, fullCamera: after.nativeCamera }));
      const missing = route => route.fulfill({ status: 404, contentType: "application/json",
        body: JSON.stringify({ detail: { error: "not_found", message: "Labeled M9 QA missing-scene read fixture" } }) });
      await page.route(selectedUrl, missing);
      try {
        await step("V18-missing-read", "Labeled 404 on selected saved-scene read; click restore", async () => {
          await page.getByRole("combobox", { name: CONTROL.saved }).selectOption(scene.handle);
          await page.getByRole("button", { name: CONTROL.restore }).click();
          await page.getByRole("alert").filter({ hasText: /저장된 보기 읽기 실패/ }).waitFor({ timeout: 30000 });
        }, async () => ({ visibleError: await page.getByRole("alert")
          .filter({ hasText: /저장된 보기 읽기 실패/ }).innerText(),
          fixture: "renderer-scoped 404; no saved scientific object was changed" }));
      } finally { await page.unroute(selectedUrl, missing); }
      await step("V18-read-boundaries", "Read-only API probes for missing, wrong-kind, and foreign scene handles", async () => {
        const handles = [
          `obj://${input.run}/viewer_scene/${"0".repeat(64)}`,
          prior.reports[0]?.handle,
        ].filter(Boolean);
        if (input.otherRun) {
          const other = itemRows((await apiState(origin, input.otherRun)).scenes)[0];
          if (other) handles.push(other.handle);
        }
        const probes = [];
        for (const handle of handles) {
          const url = new URL(`/api/runs/${input.run}/viewer/scenes/selected`, origin);
          url.searchParams.set("handle", handle);
          const response = await fetch(url);
          probes.push({ handle, status: response.status });
          assert.ok(response.status >= 400 && response.status < 500,
            `Invalid scene probe returned ${response.status}`);
        }
        return probes;
      }, async probes => ({ probes, productMutation: false }));
      if (input.otherRun) {
        let release, intercepted;
        const gate = new Promise(resolve => { release = resolve; });
        const seen = new Promise(resolve => { intercepted = resolve; });
        const hold = async route => {
          const response = await route.fetch();
          intercepted({ status: response.status(), url: route.request().url() });
          await gate;
          try { await route.fulfill({ response }); } catch { /* navigation may cancel old request */ }
        };
        await page.route(selectedUrl, hold);
        try {
          await step("V17-late-read", "Hold unchanged real saved-scene GET, switch run via UI, release old response", async () => {
            await page.getByRole("combobox", { name: CONTROL.saved }).selectOption(scene.handle);
            await page.getByRole("button", { name: CONTROL.restore }).click();
            const held = await bounded(seen, "Expected saved-scene read interception");
            assert.equal(held.status, 200);
            assert.equal(await page.getByRole("button", { name: CONTROL.save }).isDisabled(), true);
            assert.equal(await page.getByRole("button", { name: CONTROL.export }).isDisabled(), true);
            await page.locator("#run-choice").selectOption(input.otherRun);
            release();
            return waitForNative(page, viewer => viewer.sourceHandle?.includes(input.otherRun), 45000);
          }, async viewer => {
            assert.equal(new URL(page.url()).searchParams.get("run"), input.otherRun);
            assert.notEqual(viewer.sourceHandle, scene.value.structure_handle);
            return { finalRun: input.otherRun, finalSource: viewer.sourceHandle, staleSceneAbsent: true };
          });
        } finally { release(); await page.unroute(selectedUrl, hold); }
        await page.locator("#run-choice").selectOption(input.run);
        await waitForNative(page, viewer => viewer.sourceHandle?.includes(input.run), 45000);
      }
      await step("V14-context-loss", "Trigger WEBGL_lose_context on real canvas, then inspect disabled scene actions", async () => {
        return page.evaluate(() => {
          const canvas = document.querySelector("canvas.mw-molstar-canvas");
          const gl = canvas?.getContext("webgl2") || canvas?.getContext("webgl");
          const extension = gl?.getExtension("WEBGL_lose_context");
          if (!extension) throw new Error("WEBGL_lose_context unavailable in QA renderer");
          extension.loseContext();
          return { fixture: "real WebGL context loss extension", lost: gl.isContextLost() };
        });
      }, async result => {
        assert.equal(result.lost, true);
        await page.waitForTimeout(300);
        assert.equal(await page.getByRole("button", { name: CONTROL.save }).isDisabled(), true);
        assert.equal(await page.getByRole("button", { name: CONTROL.export }).isDisabled(), true);
        return result;
      });
    }
    return { rows, evidence, artifacts };
  } finally { await session.close(); }
}

if (require.main === module) {
  run(parse(process.argv.slice(2))).then(result => process.stdout.write(JSON.stringify({
    ok: true, cases: result.rows.length, evidence: result.evidence,
  }) + "\n")).catch(error => {
    process.stderr.write(`Scene offscreen QA failed: ${error.stack || error}\n`);
    process.exitCode = 1;
  });
}

module.exports = { parse, run, closeCamera, checkPng };
