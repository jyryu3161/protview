"use strict";

// Reusable offline 1HSG click path. Run against an isolated QA backend root.
// Every product mutation below is a Playwright user input in the Electron page.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { launchOffscreen, capture, status, downloadByClick } = require("./driver.cjs");

function parse(argv) {
  const input = { url: null, fixture: null, artifacts: null };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--url") input.url = argv[++i];
    else if (argv[i] === "--fixture") input.fixture = argv[++i];
    else if (argv[i] === "--artifacts") input.artifacts = argv[++i];
    else throw new Error(`Unknown argument ${argv[i]}`);
  }
  if (!input.url || !input.fixture || !input.artifacts) {
    throw new Error("Usage: node normal-flow.cjs --url http://127.0.0.1:3000 --fixture /path/public_1hsg.cif --artifacts /path/qa-evidence");
  }
  const url = new URL(input.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol)) {
    throw new Error("QA URL must be loopback HTTP(S)");
  }
  input.fixture = path.resolve(input.fixture);
  input.artifacts = path.resolve(input.artifacts);
  if (!fs.statSync(input.fixture).isFile()) throw new Error("Fixture is not a file");
  return input;
}

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function sourceDigest() {
  const root = path.resolve(__dirname, "../../..");
  const hash = crypto.createHash("sha256");
  const roots = ["frontend/app", "frontend/src", "frontend/tests/offscreen", "backend/mw", "frontend/package.json"];
  function visit(relative) {
    const absolute = path.join(root, relative);
    if (!fs.existsSync(absolute)) return;
    if (fs.statSync(absolute).isDirectory()) {
      for (const name of fs.readdirSync(absolute).sort()) {
        if (name === "artifacts" || name === "__pycache__") continue;
        visit(path.join(relative, name));
      }
    } else if (fs.statSync(absolute).isFile()) {
      hash.update(relative).update("\0").update(fs.readFileSync(absolute));
    }
  }
  roots.forEach(visit);
  const buildId = path.join(root, "frontend/.next/BUILD_ID");
  return { sourceSha256: hash.digest("hex"), buildId: fs.existsSync(buildId)
    ? fs.readFileSync(buildId, "utf8").trim() : "development-server" };
}

async function waitForViewer(page, predicate = () => true, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    last = await page.evaluate(() => typeof window.__protviewQaSnapshot === "function"
      ? window.__protviewQaSnapshot() : null);
    if (last?.ready === true && predicate(last)) return last;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Mol* observation did not become ready: ${JSON.stringify(last)}`);
}

async function waitForBoot(page) {
  const response = await fetch(new URL("/api/runs", page.url()));
  assert.equal(response.status, 200, "Initial read-only run list failed");
  const hasRuns = (await response.json()).length > 0;
  await page.waitForFunction(existing => {
    const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "새 run");
    const selected = new URL(location.href).searchParams.get("run");
    return !!button && !button.disabled && (existing ? /^run_/.test(selected ?? "")
      : document.body.textContent?.includes("현재 사용 불가"));
  }, hasRuns, { timeout: 30000 });
}

function assertViewer(after, expectedRepresentation) {
  assert.ok(after.viewer, `Mol* QA observation missing: ${after.viewerObservationError ?? "bridge absent"}`);
  assert.equal(after.viewer.ready, true, "Mol* instance not ready");
  assert.ok(after.viewer.sourceHandle, "Mol* instance has no source handle");
  assert.ok(after.viewer.molstarRepresentation, "Mol* representation object not observed");
  assert.ok(after.viewer.camera, "Mol* camera not observed");
  for (const vector of [after.viewer.camera.position, after.viewer.camera.target]) {
    assert.equal(vector.length, 3, "Mol* camera vector must be three-dimensional");
    assert.ok(vector.every(Number.isFinite), "Mol* camera coordinates must be finite");
  }
  assert.ok(Number.isFinite(after.viewer.camera.radius), "Mol* camera radius must be finite");
  assert.ok(Number.isFinite(after.viewer.camera.distance), "Mol* camera distance must be finite");
  if (expectedRepresentation) {
    assert.equal(after.viewer.representation, expectedRepresentation,
      "Mol* committed representation differs from clicked control");
  }
  return after.viewer;
}

function cameraChanged(before, after, field) {
  const a = before?.camera?.[field];
  const b = after?.camera?.[field];
  if (Array.isArray(a) && Array.isArray(b))
    return a.some((value, index) => Math.abs(value - b[index]) > 1e-5);
  return Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) > 1e-5;
}

async function validateReportDownload(page, section, runId, file, suffix) {
  const label = suffix === "md" ? "Markdown 다운로드" : "정확한 JSON 다운로드";
  const href = await section.getByRole("link", { name: label }).getAttribute("href");
  assert.ok(href, "Report download link has no href");
  const downloadUrl = new URL(href, page.url());
  assert.equal(downloadUrl.origin, new URL(page.url()).origin, "Report download escaped QA origin");
  assert.equal(downloadUrl.pathname, `/api/runs/${encodeURIComponent(runId)}/reports/download`);
  assert.equal(downloadUrl.searchParams.get("format"), suffix === "md" ? "markdown" : "json");
  const handle = downloadUrl.searchParams.get("handle");
  assert.ok(handle, "Report download has no saved handle");
  const selectedUrl = new URL(`/api/runs/${encodeURIComponent(runId)}/reports/selected`, downloadUrl.origin);
  selectedUrl.searchParams.set("handle", handle);
  const [response, selectedResponse] = await Promise.all([fetch(downloadUrl), fetch(selectedUrl)]);
  assert.equal(response.status, 200, "Read-only report download response failed");
  assert.equal(selectedResponse.status, 200, "Saved report detail response failed");
  const downloaded = fs.readFileSync(file);
  const raw = Buffer.from(await response.arrayBuffer());
  assert.ok(downloaded.equals(raw), "Clicked download differs from read-only saved bytes");
  const artifact = await selectedResponse.json();
  assert.equal(artifact.handle, handle);
  if (suffix === "md") {
    assert.equal(downloaded.toString("utf8"), artifact.markdown, "Markdown differs from saved report");
    assert.equal(await section.getByLabel(/저장된 .*보고서 미리보기/).textContent(), artifact.markdown,
      "Markdown differs from visible preview");
  } else {
    assert.deepEqual(JSON.parse(downloaded.toString("utf8")), artifact.manifest,
      "JSON differs from saved report manifest");
  }
  return { path: file, sha256: sha256(file), bytes: downloaded.length, reportHandle: handle,
    selectedUrl: selectedUrl.toString(), downloadUrl: downloadUrl.toString(), savedArtifactMatched: true };
}

async function runNormalFlow(input) {
  const session = await launchOffscreen({ ...input, interactive: false });
  const { app, page, artifacts } = session;
  const rows = [];
  const evidence = path.join(artifacts, "normal-flow.jsonl");
  const fixtureSha256 = sha256(input.fixture);
  const source = sourceDigest();

  async function step(caseId, inputDescription, action, observe) {
    const before = await status(app, page);
    const started = Date.now();
    let row;
    try {
      await action();
      const assertion = await observe(await status(app, page));
      const proof = await capture(app, page, artifacts, caseId);
      assert.equal(proof.status.blockedRequests.length, 0, "renderer attempted non-loopback request");
      row = { caseId, status: "pass", source, input: inputDescription,
        before, after: proof.status, assertion, screenshot: proof.screenshot,
        paint: proof.paint, durationMs: Date.now() - started };
    } catch (error) {
      let failureCapture = null;
      try { failureCapture = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* retain primary failure */ }
      row = { caseId, status: "fail", source, input: inputDescription, before,
        after: failureCapture?.status ?? await status(app, page),
        screenshot: failureCapture?.screenshot, paint: failureCapture?.paint,
        error: String(error), durationMs: Date.now() - started };
      fs.appendFileSync(evidence, JSON.stringify(row) + "\n");
      rows.push(row);
      throw error;
    }
    fs.appendFileSync(evidence, JSON.stringify(row) + "\n");
    rows.push(row);
    return row;
  }

  try {
    let runId;
    await step("W02", "Click 새 run; verify new local_only run", async () => {
      await waitForBoot(page);
      const old = new URL(page.url()).searchParams.get("run");
      await page.getByRole("button", { name: "새 run" }).click();
      await page.waitForFunction(previous => {
        const current = new URL(location.href).searchParams.get("run");
        const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "새 run");
        return !!current && current !== previous && !!button && !button.disabled;
      }, old);
      runId = new URL(page.url()).searchParams.get("run");
    }, async after => {
      assert.match(runId, /^run_/);
      assert.match(await page.locator("body").innerText(), /local_only/);
      return { runId, offscreen: after.offscreen, visible: after.visible };
    });

    await step("I01", `Click file input and choose ${path.basename(input.fixture)} (SHA-256 ${fixtureSha256})`, async () => {
      const chooser = page.waitForEvent("filechooser");
      await page.locator('input[type="file"]').click();
      await (await chooser).setFiles(input.fixture);
      await page.getByRole("button", { name: "구조 불러오기" }).waitFor({ timeout: 20000 });
    }, async () => {
      assert.match(await page.locator("body").innerText(), /cif/);
      return { fixtureSha256 };
    });

    await step("I03", "Click 구조 불러오기 on selected model", async () => {
      await page.getByRole("button", { name: "구조 불러오기" }).click();
      await page.getByRole("button", { name: "전처리", exact: true }).waitFor({ timeout: 20000 });
      await waitForViewer(page);
    }, async after => {
      assert.equal(after.offscreen, true);
      return { viewer: assertViewer(after), canvasCount: after.canvasCount };
    });

    await step("I08", "Click 전처리 with displayed default policies", async () => {
      await page.getByRole("button", { name: "전처리", exact: true }).click();
      await page.getByRole("combobox", { name: /^리간드/ }).waitFor({ timeout: 20000 });
      await page.getByRole("combobox", { name: /^리간드/ }).locator("option").nth(1).waitFor({ state: "attached", timeout: 20000 });
      await waitForViewer(page);
    }, async after => ({ viewer: assertViewer(after),
      ligandOptions: await page.getByRole("combobox", { name: /^리간드/ }).locator("option").count() }));

    await step("W04-models", "Click MODELS rail tab", async () => {
      await page.getByRole("tab", { name: /^models/i }).click();
      await page.locator(".mw-ligand-item").first().waitFor({ timeout: 20000 });
    }, async after => {
      assertViewer(after);
      assert.equal(await page.getByRole("tab", { name: /^models/i }).getAttribute("aria-selected"), "true");
      return { ligandButtons: await page.locator(".mw-ligand-item").count() };
    });
    await step("W04-run", "Click RUN rail tab", async () => {
      await page.getByRole("tab", { name: /^run/i }).click();
      await page.locator(".mw-step").first().waitFor({ timeout: 20000 });
    }, async after => {
      assertViewer(after);
      assert.equal(await page.getByRole("tab", { name: /^run/i }).getAttribute("aria-selected"), "true");
      return { historySteps: await page.locator(".mw-step").count() };
    });

    const originalTheme = await page.locator("html").getAttribute("data-theme");
    for (const direction of ["away", "restore"]) {
      await step(`W05-${direction}`, "Click theme toggle and observe the rendered theme", async () => {
        const prior = await page.locator("html").getAttribute("data-theme");
        await page.getByRole("button", { name: "테마 전환" }).click();
        await page.waitForFunction(previous => document.documentElement.getAttribute("data-theme") !== previous, prior);
        await waitForViewer(page);
      }, async after => ({ viewer: assertViewer(after),
        theme: await page.locator("html").getAttribute("data-theme"),
        canvasColor: await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--canvas").trim()) }));
    }
    assert.equal(await page.locator("html").getAttribute("data-theme"), originalTheme);

    await step("C01", "Select first exact ligand instance from the UI dropdown", async () => {
      await page.getByRole("combobox", { name: /^리간드/ }).selectOption({ index: 1 });
    }, async () => ({ ligand: await page.getByRole("combobox", { name: /^리간드/ }).inputValue() }));

    await step("C02-invalid", "Fill cutoff 2.4 Å, below the permitted range", async () => {
      await page.getByLabel("cutoff").fill("2.4");
      await page.getByRole("button", { name: "기하 접촉 계산" }).waitFor({ state: "visible" });
    }, async () => {
      assert.equal(await page.getByRole("button", { name: "기하 접촉 계산" }).isDisabled(), true);
      return { cutoff: await page.getByLabel("cutoff").inputValue(), computeDisabled: true };
    });
    await step("C02-four", "Fill valid 4 Å cutoff", async () => {
      await page.getByLabel("cutoff").fill("4");
    }, async () => {
      assert.equal(await page.getByRole("button", { name: "기하 접촉 계산" }).isEnabled(), true);
      return { cutoff: await page.getByLabel("cutoff").inputValue(), computeEnabled: true };
    });

    await step("C03", "Click 기하 접촉 계산 at 4 Å", async () => {
      await page.getByRole("button", { name: "기하 접촉 계산" }).click();
      await page.getByText(/기하 접촉 · 97건/).waitFor({ timeout: 30000 });
    }, async () => {
      const text = await page.getByText(/기하 접촉 · 97건/).innerText();
      assert.match(text, /97건/);
      return { measuredRows: 97, label: text };
    });

    const contactRows = page.getByRole("region", { name: "기하 접촉 측정 행" });
    await step("C04-next", "Click next page of contact measurements", async () => {
      await page.getByRole("button", { name: "다음", exact: true }).click();
      await page.getByText("51–97 / 97").waitFor({ timeout: 20000 });
    }, async () => {
      assert.equal(await contactRows.locator("tbody tr").count(), 47);
      return { page: "51–97 / 97", visibleRows: 47 };
    });
    await step("C04-previous", "Click previous page of contact measurements", async () => {
      await page.getByRole("button", { name: "이전", exact: true }).click();
      await page.getByText("1–50 / 97").waitFor({ timeout: 20000 });
    }, async () => {
      assert.equal(await contactRows.locator("tbody tr").count(), 50);
      return { page: "1–50 / 97", visibleRows: 50 };
    });

    await step("C05", "Wheel horizontally through contact table identities and distances", async () => {
      const box = await contactRows.boundingBox();
      assert.ok(box, "Contact table is not visible");
      const before = await contactRows.evaluate(el => ({ scrollWidth: el.scrollWidth, clientWidth: el.clientWidth }));
      assert.ok(before.scrollWidth > before.clientWidth, "Contact table has no horizontal overflow to exercise");
      await page.mouse.move(box.x + box.width / 2, box.y + Math.min(box.height / 2, 80));
      await page.mouse.wheel(280, 0);
      await page.waitForFunction(() => {
        const el = document.querySelector('[aria-label="기하 접촉 측정 행"]');
        return !!el && el.scrollLeft > 0;
      }, null, { timeout: 10000 });
    }, async () => {
      const metrics = await contactRows.evaluate(el => ({ scrollLeft: el.scrollLeft,
        scrollWidth: el.scrollWidth, clientWidth: el.clientWidth }));
      assert.ok(metrics.scrollLeft > 0);
      assert.equal(await contactRows.locator("tbody tr").count(), 50);
      return metrics;
    });

    await step("V04", "Click the exact ligand instance in MODELS", async () => {
      const prior = await waitForViewer(page);
      await page.getByRole("tab", { name: /^models/i }).click();
      await page.locator(".mw-ligand-item").first().click();
      await waitForViewer(page, viewer => viewer.sourceHandle === prior.sourceHandle &&
        viewer.selection !== null && cameraChanged(prior, viewer, "target"));
    }, async after => ({ selection: assertViewer(after).selection, camera: after.viewer.camera }));
    await step("V04-return", "Click RUN tab after exact ligand focus", async () => {
      await page.getByRole("tab", { name: /^run/i }).click();
      await contactRows.locator("tbody tr").first().waitFor({ timeout: 20000 });
    }, async after => ({ viewer: assertViewer(after), tab: "run" }));

    await step("V05-click", "Click first measured contact row to focus its protein residue", async () => {
      const prior = await waitForViewer(page);
      await contactRows.locator("tbody tr").first().click();
      await waitForViewer(page, viewer => viewer.sourceHandle === prior.sourceHandle &&
        viewer.selection !== null && JSON.stringify(viewer.selection) !== JSON.stringify(prior.selection));
    }, async after => ({ selection: assertViewer(after).selection, camera: after.viewer.camera }));

    const viewerControls = page.locator('section[aria-label="뷰어 요청"]');
    await step("V06", "Click local clear-selection control", async () => {
      const prior = await waitForViewer(page, viewer => viewer.selection !== null);
      await viewerControls.getByRole("button", { name: "선택 해제" }).click();
      await waitForViewer(page, viewer => viewer.sourceHandle === prior.sourceHandle &&
        viewer.selection === null && viewer.lastAck?.commandId !== prior.lastAck?.commandId &&
        viewer.lastAck?.status === "applied");
    }, async after => ({ selection: assertViewer(after).selection, ack: after.viewer.lastAck }));

    const representation = page.getByRole("group", { name: "표현 방식" });
    for (const value of ["surface", "ball-and-stick", "cartoon"]) {
      await step(`V01-${value}`, `Click ${value} representation`, async () => {
        await representation.getByRole("button", { name: value, exact: true }).click();
        await waitForViewer(page, viewer => viewer.representation === value);
      }, async after => {
        assert.equal(await representation.getByRole("button", { name: value, exact: true }).getAttribute("aria-pressed"), "true");
        return { committedViewerObservation: assertViewer(after, value), paintCount: after.paintCount };
      });
    }

    const canvas = page.locator("canvas:visible").first();
    await step("V02-orbit", "Drag actual Mol* canvas to orbit the camera", async () => {
      const prior = await waitForViewer(page);
      const box = await canvas.boundingBox();
      assert.ok(box, "Mol* canvas has no visible bounding box");
      const x = box.x + box.width / 2;
      const y = box.y + box.height / 2;
      await page.mouse.move(x, y);
      await page.mouse.down();
      await page.mouse.move(x + 90, y + 45, { steps: 12 });
      await page.mouse.up();
      await waitForViewer(page, viewer => viewer.sourceHandle === prior.sourceHandle &&
        cameraChanged(prior, viewer, "position"));
    }, async after => ({ viewer: assertViewer(after), cameraChanged: true }));
    await step("V02-wheel", "Wheel actual Mol* canvas to zoom", async () => {
      const prior = await waitForViewer(page);
      const box = await canvas.boundingBox();
      assert.ok(box, "Mol* canvas has no visible bounding box");
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.wheel(0, -450);
      await waitForViewer(page, viewer => viewer.sourceHandle === prior.sourceHandle &&
        cameraChanged(prior, viewer, "distance"));
    }, async after => ({ viewer: assertViewer(after), cameraChanged: true }));

    for (const [caseId, label, expected] of [
      ["V03-in", "확대", "decrease"], ["V03-out", "축소", "increase"],
      ["V03-reset", "시점 초기화", "changed"],
    ]) {
      await step(caseId, `Click local ${label} camera control`, async () => {
        const prior = await waitForViewer(page);
        await viewerControls.getByRole("button", { name: label, exact: true }).click();
        await waitForViewer(page, viewer => viewer.sourceHandle === prior.sourceHandle &&
          viewer.lastAck?.commandId !== prior.lastAck?.commandId && viewer.lastAck?.status === "applied" &&
          (expected === "decrease" ? viewer.camera?.distance < prior.camera.distance - 1e-5 :
            expected === "increase" ? viewer.camera?.distance > prior.camera.distance + 1e-5 :
              cameraChanged(prior, viewer, "position")));
      }, async after => ({ camera: assertViewer(after).camera, ack: after.viewer.lastAck }));
    }

    const geometrySection = page.getByText("선택한 측정의 로컬 보고서").locator("..");
    await step("R01-history", "Click contact history step to inspect its exact geometry result", async () => {
      const prior = await waitForViewer(page);
      await page.locator(".mw-step").filter({ hasText: "compute_interactions" }).last().click();
      await geometrySection.getByRole("button", { name: "보고서 만들기" }).waitFor({ timeout: 20000 });
      await page.getByText(/선택한 단계의 구조 · model/).waitFor({ timeout: 30000 });
      await waitForViewer(page, viewer => viewer.sessionId !== prior.sessionId ||
        viewer.generation !== prior.generation);
    }, async after => ({ viewer: assertViewer(after), contactSectionVisible: await geometrySection.isVisible() }));
    await step("R01", "Click geometry report create", async () => {
      await geometrySection.getByRole("button", { name: "보고서 만들기" }).click();
      await geometrySection.getByLabel("저장된 보고서 미리보기").waitFor({ timeout: 30000 });
    }, async () => ({ previewLength: (await geometrySection.getByLabel("저장된 보고서 미리보기").innerText()).length }));

    for (const [suffix, name] of [["md", "Markdown 다운로드"], ["json", "정확한 JSON 다운로드"]]) {
      let downloaded;
      await step(`R02-${suffix}`, `Click geometry ${name}`, async () => {
        downloaded = await downloadByClick(app, geometrySection.getByRole("link", { name }));
      }, async () => {
        const validated = await validateReportDownload(page, geometrySection, runId, downloaded.downloaded, suffix);
        return { ...validated, electronDownload: downloaded };
      });
    }

    await step("S01-input", "Return to latest pipeline and reselect its exact ligand instance", async () => {
      const back = page.getByRole("button", { name: "최신 구조로 돌아가기" });
      if (await back.isVisible()) await back.click();
      await page.getByRole("combobox", { name: /^리간드/ }).selectOption({ index: 1 });
      await page.waitForFunction(() => {
        const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "선택한 리간드 SASA 계산");
        return !!button && !button.disabled;
      }, null, { timeout: 20000 });
      await waitForViewer(page);
    }, async after => ({ viewer: assertViewer(after),
      ligand: await page.getByRole("combobox", { name: /^리간드/ }).inputValue() }));

    await step("S01", "Click latest selected-ligand SASA calculation", async () => {
      await page.getByRole("button", { name: "선택한 리간드 SASA 계산" }).first().click();
      await page.getByRole("region", { name: "단백질 잔기 SASA 측정 행" }).waitFor({ timeout: 60000 });
      await waitForViewer(page);
    }, async after => {
      assertViewer(after);
      const body = await page.locator("body").innerText();
      assert.match(body, /리간드 매몰/);
      assert.match(body, /Å²/);
      return { method: "freesasa_lee_richards_v1", unit: "Å²" };
    });

    const sasaSection = page.getByText("선택한 SASA 결과의 로컬 방법 보고서").locator("..");
    await step("R03-history", "Click SASA history step to inspect its exact method result", async () => {
      const prior = await waitForViewer(page);
      await page.locator(".mw-step").filter({ hasText: "compute_interface_sasa" }).last().click();
      await sasaSection.getByRole("button", { name: "방법 보고서 만들기" }).waitFor({ timeout: 20000 });
      await page.getByText(/선택한 단계의 구조 · model/).waitFor({ timeout: 30000 });
      await waitForViewer(page, viewer => viewer.sessionId !== prior.sessionId ||
        viewer.generation !== prior.generation);
    }, async after => ({ viewer: assertViewer(after), sasaSectionVisible: await sasaSection.isVisible() }));
    await step("R03", "Click SASA method report create", async () => {
      await sasaSection.getByRole("button", { name: "방법 보고서 만들기" }).click();
      await sasaSection.getByLabel("저장된 방법 보고서 미리보기").waitFor({ timeout: 30000 });
    }, async () => ({ previewLength: (await sasaSection.getByLabel("저장된 방법 보고서 미리보기").innerText()).length }));

    for (const [suffix, name] of [["md", "Markdown 다운로드"], ["json", "정확한 JSON 다운로드"]]) {
      let downloaded;
      await step(`R03-${suffix}`, `Click SASA ${name}`, async () => {
        downloaded = await downloadByClick(app, sasaSection.getByRole("link", { name }));
      }, async () => {
        const validated = await validateReportDownload(page, sasaSection, runId, downloaded.downloaded, suffix);
        return { ...validated, electronDownload: downloaded };
      });
    }

    return { runId, rows, artifacts };
  } finally {
    await session.close();
  }
}

if (require.main === module) {
  runNormalFlow(parse(process.argv.slice(2))).then(result => {
    process.stdout.write(JSON.stringify({ ok: true, runId: result.runId, cases: result.rows.length,
      evidence: path.join(result.artifacts, "normal-flow.jsonl") }) + "\n");
  }).catch(error => {
    process.stderr.write(`Normal flow QA failed: ${error.stack || error}\n`);
    process.exitCode = 1;
  });
}

module.exports = { parse, runNormalFlow, sha256, sourceDigest, waitForViewer, waitForBoot,
  assertViewer, validateReportDownload };
