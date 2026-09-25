"use strict";

// Explicit loopback 503/delay fixtures for existing isolated QA runs. No success is fabricated.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { launchOffscreen, capture, status } = require("./driver.cjs");
const { waitForBoot, waitForViewer, sourceDigest } = require("./normal-flow.cjs");

function parse(argv) {
  const input = { url: null, targetRun: null, otherRun: null, artifacts: null, mode: null };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--url") input.url = argv[++i];
    else if (argv[i] === "--target-run") input.targetRun = argv[++i];
    else if (argv[i] === "--other-run") input.otherRun = argv[++i];
    else if (argv[i] === "--artifacts") input.artifacts = argv[++i];
    else if (argv[i] === "--mode") input.mode = argv[++i];
    else throw new Error(`Unknown argument ${argv[i]}`);
  }
  if (!input.url || !input.targetRun || !input.otherRun || !input.artifacts ||
      !["read-retry", "late-result", "late-report"].includes(input.mode))
    throw new Error("Usage: openmm-faults.cjs --url LOOPBACK --target-run DONE_RUN --other-run NO_OPENMM_RUN --artifacts PATH --mode read-retry|late-result|late-report");
  const url = new URL(input.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("QA URL must be loopback HTTP(S)");
  assert.match(input.targetRun, /^run_[a-f0-9]+$/);
  assert.match(input.otherRun, /^run_[a-f0-9]+$/);
  assert.notEqual(input.targetRun, input.otherRun);
  input.url = new URL(`/?run=${input.otherRun}`, url).toString();
  input.artifacts = path.resolve(input.artifacts);
  return input;
}

async function readJson(url) {
  const response = await fetch(url);
  assert.equal(response.status, 200, `Read-only prerequisite failed: ${url}`);
  return response.json();
}

async function bounded(promise, label, timeoutMs = 30000) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`${label} timed out`)), timeoutMs);
    })]);
  } finally { clearTimeout(timer); }
}

async function runFault(input) {
  const session = await launchOffscreen(input);
  const { app, page, artifacts } = session;
  const source = sourceDigest();
  const evidence = path.join(artifacts, `openmm-${input.mode}.jsonl`);
  const rows = [];
  async function row(caseId, fixture, action, observe) {
    const before = await status(app, page);
    try {
      await action();
      const assertion = await observe();
      const proof = await capture(app, page, artifacts, caseId);
      assert.equal(proof.status.blockedRequests.length, 0);
      const entry = { caseId, status: "pass", fixture, source, before,
        after: proof.status, assertion, screenshot: proof.screenshot, paint: proof.paint };
      fs.appendFileSync(evidence, JSON.stringify(entry) + "\n"); rows.push(entry);
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* retain failure */ }
      const entry = { caseId, status: "fail", fixture, source, before,
        after: proof?.status, screenshot: proof?.screenshot, paint: proof?.paint, error: String(error) };
      fs.appendFileSync(evidence, JSON.stringify(entry) + "\n"); rows.push(entry);
      throw error;
    }
  }

  try {
    await waitForBoot(page);
    assert.equal(new URL(page.url()).searchParams.get("run"), input.otherRun);
    const origin = new URL(page.url()).origin;
    const otherJobs = await readJson(new URL(`/api/runs/${input.otherRun}/jobs`, origin));
    assert.ok(otherJobs.every(job => job.status !== "done"), "Other run must have no completed OpenMM job");
    const targetJobs = await readJson(new URL(`/api/runs/${input.targetRun}/jobs`, origin));
    assert.ok(targetJobs.some(job => job.status === "done" && job.output_handles?.length),
      "Target run needs a genuine completed OpenMM job");
    const targetReports = await readJson(new URL(`/api/runs/${input.targetRun}/reports`, origin));
    assert.ok(targetReports.some(report => report.analysis_type === "openmm_protein_minimize"),
      "Target run needs a genuine saved OpenMM report");

    const resultPattern = `**/api/runs/${input.targetRun}/openmm_minimization?*`;
    const reportPattern = `**/api/runs/${input.targetRun}/reports/selected?*`;
    const selector = page.locator("#run-choice");
    if (input.mode === "read-retry") {
      const deny = async route => route.fulfill({ status: 503, contentType: "application/json",
        body: JSON.stringify({ detail: { error: "qa_injected_read_503", message: "Labeled QA read fault" } }) });
      await page.route(resultPattern, deny);
      await page.route(reportPattern, deny);
      await row("O13-fault", "injected 503 on exact loopback OpenMM result and saved-report GETs", async () => {
        await selector.selectOption(input.targetRun);
        await page.getByRole("button", { name: "저장된 OpenMM 결과 다시 읽기" }).waitFor({ timeout: 30000 });
        await page.getByRole("button", { name: "저장된 OpenMM 보고서 다시 읽기" }).waitFor({ timeout: 30000 });
      }, async () => {
        assert.equal(new URL(page.url()).searchParams.get("run"), input.targetRun);
        assert.equal(await page.getByText("시작 전위").count(), 0);
        return { resultRetryVisible: true, reportRetryVisible: true };
      });
      await page.unroute(resultPattern, deny);
      await page.unroute(reportPattern, deny);
      await row("O13-result-retry", "fault removed; real backend GET", async () => {
        await page.getByRole("button", { name: "저장된 OpenMM 결과 다시 읽기" }).click();
        await page.getByText("시작 전위").waitFor({ timeout: 30000 });
      }, async () => ({ resultVisible: await page.getByText("시작 전위").isVisible() }));
      await row("O13-report-retry", "fault removed; real saved-report GET", async () => {
        await page.getByRole("button", { name: "저장된 OpenMM 보고서 다시 읽기" }).click();
        await page.getByLabel("저장된 OpenMM 보고서 미리보기").waitFor({ timeout: 30000 });
      }, async () => ({ previewLength: (await page.getByLabel("저장된 OpenMM 보고서 미리보기").textContent()).length }));
    } else {
      const pattern = input.mode === "late-result" ? resultPattern : reportPattern;
      let release;
      const releaseGate = new Promise(resolve => { release = resolve; });
      let started;
      const startedGate = new Promise(resolve => { started = resolve; });
      let delivered;
      const deliveredGate = new Promise(resolve => { delivered = resolve; });
      let deliveryEvidence = null;
      const holdRealResponse = async route => {
        let response;
        try { response = await route.fetch(); }
        catch (error) { started({ status: null, error: String(error) }); return; }
        started({ status: response.status(), url: route.request().url() });
        await releaseGate;
        try {
          await route.fulfill({ response });
          delivered({ state: "fulfilled" });
        } catch (error) {
          delivered({ state: "browser_cancelled", reason: String(error) });
        }
      };
      await page.route(pattern, holdRealResponse);
      try {
        await row(`O14-${input.mode}`, "hold real loopback GET response, switch run through selector, then release unchanged bytes", async () => {
          await selector.selectOption(input.targetRun);
          const held = await bounded(startedGate, "Expected real read interception");
          assert.equal(held.status, 200);
          await selector.selectOption(input.otherRun);
          await page.waitForFunction(id => new URL(location.href).searchParams.get("run") === id, input.otherRun);
          release();
          deliveryEvidence = await bounded(deliveredGate, "Held read delivery");
          await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        }, async () => {
          assert.equal(new URL(page.url()).searchParams.get("run"), input.otherRun);
          assert.equal(await page.getByText("시작 전위").count(), 0, "Late old result leaked into other run");
          assert.equal(await page.getByLabel("저장된 OpenMM 보고서 미리보기").count(), 0,
            "Late old report leaked into other run");
          const viewer = await waitForViewer(page);
          assert.ok(viewer.sourceHandle.includes(input.otherRun));
          return { currentRun: input.otherRun, displayedSource: viewer.sourceHandle,
            staleResultVisible: false, staleReportVisible: false, delivery: deliveryEvidence };
        });
      } finally {
        release();
        await page.unroute(pattern, holdRealResponse);
      }
    }
    return { rows, evidence };
  } finally {
    await session.close();
  }
}

if (require.main === module) {
  runFault(parse(process.argv.slice(2))).then(result => process.stdout.write(JSON.stringify({
    ok: true, cases: result.rows.length, evidence: result.evidence,
  }) + "\n")).catch(error => {
    process.stderr.write(`OpenMM fault click QA failed: ${error.stack || error}\n`);
    process.exitCode = 1;
  });
}

module.exports = { parse, runFault };
