"use strict";

const { _electron: electron } = require("playwright");
const electronBinary = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");
const crypto = require("node:crypto");

const main = path.join(__dirname, "main.cjs");
const defaultArtifacts = path.join(__dirname, "artifacts");

function options(argv) {
  const parsed = { url: "http://127.0.0.1:3000", artifacts: defaultArtifacts, interactive: false };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--url") parsed.url = argv[++i];
    else if (argv[i] === "--artifacts") parsed.artifacts = argv[++i];
    else if (argv[i] === "--interactive") parsed.interactive = true;
    else throw new Error(`Unknown argument: ${argv[i]}`);
  }
  const url = new URL(parsed.url);
  if (!["http:", "https:"].includes(url.protocol) || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)) {
    throw new Error("--url must point to a loopback HTTP server");
  }
  parsed.artifacts = path.resolve(parsed.artifacts);
  return parsed;
}

function locator(page, target) {
  if (!target || typeof target !== "object") throw new Error("A locator target is required");
  if (target.by === "role") return page.getByRole(target.role, { name: target.name, exact: target.exact ?? true });
  if (target.by === "label") return page.getByLabel(target.name, { exact: target.exact ?? true });
  if (target.by === "text") return page.getByText(target.name, { exact: target.exact ?? true });
  if (target.by === "css") return page.locator(target.selector);
  throw new Error(`Unsupported locator: ${target.by}`);
}

async function status(electronApp, page) {
  const state = await electronApp.evaluate(({ app }) => app.__offscreenQa.status());
  let viewer = null;
  let viewerObservationError = null;
  try {
    viewer = await page.evaluate(() => typeof window.__protviewQaSnapshot === "function"
      ? window.__protviewQaSnapshot() : null);
  } catch (error) {
    viewerObservationError = String(error);
  }
  return { ...state, title: await page.title(), canvasCount: await page.locator("canvas").count(),
    rendererUserAgent: await page.evaluate(() => navigator.userAgent), viewer, viewerObservationError };
}

async function capture(electronApp, page, artifacts, name) {
  const safe = String(name).replace(/[^a-z0-9_-]/gi, "_");
  const previous = await electronApp.evaluate(({ app }) => app.__offscreenQa.status().paintCount);
  await electronApp.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.invalidate());
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const count = await electronApp.evaluate(({ app }) => app.__offscreenQa.status().paintCount);
    if (count > previous) break;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  const afterInvalidate = await electronApp.evaluate(({ app }) => app.__offscreenQa.status().paintCount);
  if (afterInvalidate <= previous) throw new Error("No fresh Electron paint frame after invalidation");
  const screenshot = path.join(artifacts, `${safe}.page.png`);
  await page.screenshot({ path: screenshot, animations: "disabled", timeout: 15000 });
  const paint = await electronApp.evaluate(({ app }, basename) => app.__offscreenQa.capturePaint(basename), safe);
  return { screenshot, paint, status: await status(electronApp, page) };
}

async function downloadByClick(electronApp, target, timeoutMs = 30000) {
  const previous = await electronApp.evaluate(({ app }) => app.__offscreenQa.status().downloads.length);
  await target.click({ timeout: timeoutMs });
  const deadline = Date.now() + timeoutMs;
  let record = null;
  while (Date.now() < deadline) {
    const downloads = await electronApp.evaluate(({ app }) => app.__offscreenQa.status().downloads);
    record = downloads[previous] ?? null;
    if (record?.status === "completed") {
      const bytes = fs.readFileSync(record.path);
      return { downloaded: record.path, sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
        bytes: bytes.length, url: record.url, filename: record.filename,
        electronDownloadStatus: record.status };
    }
    if (record && ["cancelled", "interrupted"].includes(record.status))
      throw new Error(`Electron download ${record.status}: ${record.url}`);
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Electron will-download/done did not complete: ${JSON.stringify(record)}`);
}

async function command(electronApp, page, artifacts, request) {
  const target = request.target ? locator(page, request.target) : null;
  const before = await status(electronApp, page);
  let outcome;
  switch (request.action) {
    case "status": return { status: before };
    case "snapshot": return { before, ...await capture(electronApp, page, artifacts, request.name || "snapshot") };
    case "click":
      await target.click({ timeout: request.timeoutMs || 15000 });
      outcome = { clicked: true };
      break;
    case "fill":
      await target.fill(String(request.value), { timeout: request.timeoutMs || 15000 });
      outcome = { filled: true };
      break;
    case "press":
      await target.press(String(request.key), { timeout: request.timeoutMs || 15000 });
      outcome = { pressed: request.key };
      break;
    case "keyboard":
      await page.keyboard.press(String(request.key));
      outcome = { pressed: request.key };
      break;
    case "check":
      await target.check({ timeout: request.timeoutMs || 15000 });
      outcome = { checked: true };
      break;
    case "uncheck":
      await target.uncheck({ timeout: request.timeoutMs || 15000 });
      outcome = { checked: false };
      break;
    case "select":
      outcome = { selected: await target.selectOption(request.value, { timeout: request.timeoutMs || 15000 }) };
      break;
    case "chooseFile": {
      const chooserPromise = page.waitForEvent("filechooser", { timeout: request.timeoutMs || 15000 });
      await target.click({ timeout: request.timeoutMs || 15000 });
      const chooser = await chooserPromise;
      await chooser.setFiles(path.resolve(request.file));
      outcome = { chosen: path.basename(request.file) };
      break;
    }
    case "drag": {
      const box = await target.boundingBox();
      if (!box) throw new Error("Drag target has no visible bounding box");
      const x = box.x + box.width / 2;
      const y = box.y + box.height / 2;
      await page.mouse.move(x, y);
      await page.mouse.down();
      await page.mouse.move(x + Number(request.dx || 80), y + Number(request.dy || 40), { steps: 12 });
      await page.mouse.up();
      outcome = { dragged: true };
      break;
    }
    case "wheel": {
      const box = await target.boundingBox();
      if (!box) throw new Error("Wheel target has no visible bounding box");
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.wheel(Number(request.dx || 0), Number(request.dy || 300));
      outcome = { wheeled: true };
      break;
    }
    case "download": {
      outcome = await downloadByClick(electronApp, target, request.timeoutMs || 30000);
      break;
    }
    case "wait":
      await target.waitFor({ state: request.state || "visible", timeout: request.timeoutMs || 15000 });
      return { before, status: await status(electronApp, page), waited: request.state || "visible" };
    case "text": return { text: await target.innerText({ timeout: request.timeoutMs || 15000 }) };
    case "count": return { count: await target.count() };
    default: throw new Error(`Unknown action: ${request.action}`);
  }
  if (request.settleMs) await page.waitForTimeout(request.settleMs);
  if (request.capture === false) return { before, outcome, status: await status(electronApp, page) };
  return { before, outcome, ...await capture(electronApp, page, artifacts, request.name || `action-${Date.now()}`) };
}

async function waitForPaint(electronApp, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const state = await electronApp.evaluate(({ app }) => app.__offscreenQa?.status());
    if (state && state.paintCount > 0) return state;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error("Electron offscreen paint event did not arrive");
}

async function launchOffscreen(cli = options([])) {
  fs.mkdirSync(cli.artifacts, { recursive: true });
  const app = await electron.launch({
    executablePath: electronBinary,
    args: [main],
    cwd: path.join(__dirname, "../.."),
    env: {
      ...process.env,
      PROTVIEW_OFFSCREEN_URL: cli.url,
      PROTVIEW_OFFSCREEN_ARTIFACTS: cli.artifacts,
      ELECTRON_RUN_AS_NODE: "",
    },
    timeout: 30000,
  });
  try {
    const page = await app.firstWindow({ timeout: 30000 });
    await page.waitForLoadState("domcontentloaded", { timeout: 30000 });
    const proof = await waitForPaint(app);
    if (!proof.offscreen || proof.visible || !proof.painting || !proof.hardwareAccelerationEnabled) {
      throw new Error(`Not an invisible GPU-enabled offscreen Electron window: ${JSON.stringify(proof)}`);
    }
    if (proof.blockedRequests.length) throw new Error("Application attempted a non-loopback request");
    const baseline = await capture(app, page, cli.artifacts, "baseline");
    fs.writeFileSync(path.join(cli.artifacts, "baseline.json"), JSON.stringify({
      electronVersion: await app.evaluate(({ app: electronApp }) => electronApp.getVersion()),
      playwrightVersion: require("playwright/package.json").version,
      capturedAt: new Date().toISOString(),
      ...baseline,
    }, null, 2) + "\n");
    return { app, page, artifacts: cli.artifacts, baseline, close: () => app.close() };
  } catch (error) {
    await app.close();
    throw error;
  }
}

async function mainRun() {
  const session = await launchOffscreen(options(process.argv.slice(2)));
  const { app, page, artifacts, baseline } = session;
  let lines;
  let quitId;
  const evidencePath = path.join(artifacts, "interactive.jsonl");
  try {
    process.stdout.write(JSON.stringify({ ready: true, ...baseline }) + "\n");
    if (!process.argv.includes("--interactive")) return;
    lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
    for await (const line of lines) {
      if (!line.trim()) continue;
      let request;
      try {
        request = JSON.parse(line);
        if (request.action === "quit") {
          quitId = request.id;
          break;
        }
        const result = await command(app, page, artifacts, request);
        const input = { id: request.id, action: request.action, target: request.target,
          name: request.name, file: request.file ? path.basename(request.file) : undefined,
          valueLength: typeof request.value === "string" ? request.value.length : undefined,
          valueSha256: typeof request.value === "string"
            ? crypto.createHash("sha256").update(request.value).digest("hex") : undefined };
        fs.appendFileSync(evidencePath, JSON.stringify({ at: new Date().toISOString(), input,
          observed: result, status: "observed_unreviewed" }) + "\n");
        process.stdout.write(JSON.stringify({ id: request.id, ok: true, ...result }) + "\n");
      } catch (error) {
        fs.appendFileSync(evidencePath, JSON.stringify({ at: new Date().toISOString(),
          input: { id: request?.id, action: request?.action, target: request?.target },
          error: String(error), status: "failed" }) + "\n");
        process.stdout.write(JSON.stringify({ id: request?.id, ok: false, error: String(error) }) + "\n");
      }
    }
  } finally {
    lines?.close();
    process.stdin.pause();
    await session.close();
  }
  if (quitId !== undefined) {
    const observed = { id: quitId, closed: true };
    fs.appendFileSync(evidencePath, JSON.stringify({ at: new Date().toISOString(),
      input: { id: quitId, action: "quit" }, observed, status: "observed_unreviewed" }) + "\n");
    process.stdout.write(JSON.stringify(observed) + "\n");
  }
}

if (require.main === module) {
  mainRun().catch(error => {
    process.stderr.write(`Offscreen QA failed: ${error.stack || error}\n`);
    process.exitCode = 1;
  });
}

module.exports = { options, launchOffscreen, locator, command, capture, status, waitForPaint,
  downloadByClick };
