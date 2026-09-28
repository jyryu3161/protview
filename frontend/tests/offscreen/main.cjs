"use strict";

// Electron main process for real, invisible offscreen QA. The renderer is the
// production Next.js application; this file never injects product behavior.
const { app, BrowserWindow, session } = require("electron");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const url = process.env.PROTVIEW_OFFSCREEN_URL;
const artifacts = path.resolve(process.env.PROTVIEW_OFFSCREEN_ARTIFACTS || path.join(process.cwd(), "tests/offscreen/artifacts"));
const profile = path.join(artifacts, "browser-profile");
const state = { paintCount: 0, lastPaintAt: null, lastSize: null, blockedRequests: [],
  loopbackRequestCount: 0, loadError: null, downloads: [], firstPaint: null };
let lastImage = null;

function isLoopback(value) {
  try {
    const parsed = new URL(value);
    return ["http:", "https:", "ws:", "wss:"].includes(parsed.protocol) &&
      ["127.0.0.1", "localhost", "[::1]"].includes(parsed.hostname);
  } catch {
    return false;
  }
}

if (!url || !isLoopback(url)) {
  throw new Error("PROTVIEW_OFFSCREEN_URL must be an http(s) loopback URL");
}
fs.mkdirSync(profile, { recursive: true });
app.setPath("userData", profile);

// GPU acceleration remains enabled: offscreen uses the GPU bitmap path so
// Mol* WebGL can render. Do not call app.disableHardwareAcceleration().
app.commandLine.appendSwitch("ignore-gpu-blocklist");

app.whenReady().then(async () => {
  session.defaultSession.on("will-download", (_event, item) => {
    const source = item.getURL();
    if (!isLoopback(source)) {
      state.blockedRequests.push({ origin: new URL(source).origin, resourceType: "download" });
      item.cancel();
      return;
    }
    const filename = path.basename(item.getFilename()).replace(/[^a-z0-9._-]/gi, "_");
    const output = path.join(artifacts, "downloads", `${Date.now()}-${process.pid}-${state.downloads.length + 1}-${filename}`);
    fs.mkdirSync(path.dirname(output), { recursive: true });
    item.setSavePath(output);
    const record = { url: source, filename, path: output, status: "progressing", receivedBytes: 0 };
    state.downloads.push(record);
    item.once("done", (_doneEvent, doneStatus) => {
      record.status = doneStatus;
      record.receivedBytes = item.getReceivedBytes();
    });
  });
  session.defaultSession.webRequest.onBeforeRequest((details, callback) => {
    if (/^(?:https?|wss?):/i.test(details.url) && !isLoopback(details.url)) {
      state.blockedRequests.push({ origin: new URL(details.url).origin, resourceType: details.resourceType });
      callback({ cancel: true });
      return;
    }
    if (isLoopback(details.url)) state.loopbackRequestCount += 1;
    callback({ cancel: false });
  });

  const win = new BrowserWindow({
    width: 1440,
    height: 960,
    show: false,
    backgroundColor: "#0b1220",
    webPreferences: {
      offscreen: true,
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });
  win.webContents.setFrameRate(60);
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (event, target) => {
    if (!isLoopback(target)) event.preventDefault();
  });
  win.webContents.on("did-fail-load", (_event, code, description, target) => {
    if (code !== -3) state.loadError = { code, description, targetOrigin: new URL(target).origin };
  });
  win.webContents.on("paint", (_event, dirtyRect, image) => {
    state.paintCount += 1;
    state.lastPaintAt = new Date().toISOString();
    state.lastSize = image.getSize();
    state.lastDirtyRect = dirtyRect;
    lastImage = image;
    // The earliest paint events can carry an empty bitmap; paint-first.png is
    // the first frame with a non-zero size and non-empty PNG bytes.
    if (!state.firstPaint && !image.isEmpty()) {
      const size = image.getSize();
      const png = size.width > 0 && size.height > 0 ? image.toPNG() : null;
      if (png && png.length > 0) {
        const output = path.join(artifacts, "paint-first.png");
        fs.writeFileSync(output, png);
        state.firstPaint = { path: output, paintOrdinal: state.paintCount, size, bytes: png.length,
          sha256: crypto.createHash("sha256").update(png).digest("hex") };
      }
    }
  });

  app.__offscreenQa = {
    status: () => ({
      ...state,
      offscreen: win.webContents.isOffscreen(),
      visible: win.isVisible(),
      painting: win.webContents.isPainting(),
      hardwareAccelerationEnabled: app.isHardwareAccelerationEnabled(),
      versions: {
        electron: process.versions.electron,
        chrome: process.versions.chrome,
        node: process.versions.node,
      },
      url: win.webContents.getURL(),
    }),
    capturePaint: (basename) => {
      if (!lastImage) throw new Error("No Electron paint frame received");
      const safeName = String(basename).replace(/[^a-z0-9_-]/gi, "_");
      const output = path.join(artifacts, `${safeName}.paint.png`);
      fs.writeFileSync(output, lastImage.toPNG());
      return { path: output, paintCount: state.paintCount, size: lastImage.getSize() };
    },
  };

  win.webContents.startPainting();
  await win.loadURL(url);
  win.webContents.invalidate();
});

app.on("window-all-closed", () => app.quit());
