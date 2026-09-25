"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const root = "/Users/jaeyongryu/Projects/protview";
const { launchOffscreen, capture, status } = require(path.join(root, "frontend/tests/offscreen/driver.cjs"));
const { waitForBoot, waitForViewer, sourceDigest } = require(path.join(root, "frontend/tests/offscreen/normal-flow.cjs"));
const url = "http://127.0.0.1:3000";
const fixture = "/tmp/protview-qa/m8-inputs/synthetic_multimodel.pdb";
const artifacts = process.env.PROTVIEW_EXTRA_ARTIFACTS || "/tmp/protview-qa/m8-extra-i09";
const sha256 = crypto.createHash("sha256").update(fs.readFileSync(fixture)).digest("hex");
async function api(runId, route) {
  const response = await fetch(`${url}/api/runs/${runId}${route}`);
  assert.equal(response.status, 200);
  return response.json();
}
async function main() {
  const session = await launchOffscreen({ url, artifacts });
  const { app, page } = session;
  const evidence = path.join(artifacts, "I09.jsonl");
  const source = sourceDigest();
  let runId;
  async function step(caseId, action, observe) {
    const before = await status(app, page);
    try {
      await action();
      const assertion = await observe();
      const proof = await capture(app, page, artifacts, caseId);
      assert.equal(proof.status.offscreen, true);
      assert.equal(proof.status.visible, false);
      assert.deepEqual(proof.status.blockedRequests, []);
      const row = { caseId, status: "pass", source, fixture, fixtureSha256: sha256, runId,
        before, after: proof.status, assertion, screenshot: proof.screenshot, paint: proof.paint };
      fs.appendFileSync(evidence, JSON.stringify(row) + "\n");
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch {}
      fs.appendFileSync(evidence, JSON.stringify({ caseId, status: "fail", source, fixtureSha256: sha256,
        runId, before, after: proof?.status, screenshot: proof?.screenshot,
        paint: proof?.paint, error: String(error) }) + "\n");
      throw error;
    }
  }
  try {
    await step("I09-upload-pending", async () => {
      await waitForBoot(page);
      const previous = new URL(page.url()).searchParams.get("run");
      await page.getByRole("button", { name: "새 run" }).click();
      await page.waitForFunction(old => {
        const next = new URL(location.href).searchParams.get("run");
        const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "새 run");
        return !!next && next !== old && !!button && !button.disabled;
      }, previous);
      runId = new URL(page.url()).searchParams.get("run");
      const chooser = page.waitForEvent("filechooser");
      await page.locator('input[type="file"]').click();
      await (await chooser).setFiles(fixture);
      await page.getByRole("combobox", { name: "model" }).waitFor({ timeout: 20000 });
    }, async () => {
      const events = await api(runId, "/events?after=0&limit=500");
      const upload = events.findLast(item => item.type === "upload_received");
      assert.equal(upload.sha256, sha256);
      const options = await page.getByRole("combobox", { name: "model" }).locator("option").allTextContents();
      assert.deepEqual(options.map(value => value.trim()), ["0 · #1", "1 · #2"]);
      assert.ok(!events.some(item => item.tool === "load_structure" && item.type === "tool_succeeded"));
      return { uploadId: upload.upload_id, modelOptions: options, pending: true };
    });
    await step("I09-reopen-numeric", async () => {
      await page.reload();
      await waitForBoot(page);
      await page.getByRole("spinbutton", { name: "model index" }).waitFor({ timeout: 20000 });
    }, async () => {
      assert.equal(new URL(page.url()).searchParams.get("run"), runId);
      assert.equal(await page.getByRole("combobox", { name: "model" }).count(), 0);
      return { numericValue: await page.getByRole("spinbutton", { name: "model index" }).inputValue() };
    });
    const numeric = page.getByRole("spinbutton", { name: "model index" });
    const load = page.getByRole("button", { name: "구조 불러오기" });
    await step("I09-invalid-negative", async () => { await numeric.fill("-1"); }, async () => {
      assert.equal(await load.isDisabled(), true);
      return { value: await numeric.inputValue(), disabled: true };
    });
    await step("I09-invalid-fraction", async () => { await numeric.fill("0.5"); }, async () => {
      assert.equal(await load.isDisabled(), true);
      return { value: await numeric.inputValue(), disabled: true };
    });
    await step("I09-out-of-range", async () => {
      await numeric.fill("2");
      assert.equal(await load.isEnabled(), true);
      await load.click();
      await page.getByRole("alert").filter({ hasText: /model|index|범위|input_invalid|invalid/i }).waitFor({ timeout: 20000 });
    }, async () => {
      const events = await api(runId, "/events?after=0&limit=500");
      assert.ok(!events.some(item => item.tool === "load_structure" && item.type === "tool_succeeded"));
      return { error: await page.getByRole("alert").allTextContents(), noLoadSuccess: true };
    });
    await step("I09-model2-load", async () => {
      await numeric.fill("1");
      await load.click();
      await waitForViewer(page);
    }, async () => {
      const viewer = (await status(app, page)).viewer;
      assert.ok(viewer?.ready && viewer.sourceHandle.includes(runId));
      const residues = await api(runId, `/structures/residues?handle=${encodeURIComponent(viewer.sourceHandle)}`);
      assert.equal(residues.model_number, 2);
      assert.equal(residues.residues[0].model_number, 2);
      assert.equal(residues.residues[0].seq_auth, 100);
      assert.equal(residues.residues[0].icode, "A");
      const events = await api(runId, "/events?after=0&limit=500");
      const loadEvent = events.findLast(item => item.type === "tool_succeeded" && item.tool === "load_structure");
      assert.equal(loadEvent.output.summary.selected_model_index, 1);
      assert.equal(loadEvent.output.summary.model_number, 2);
      return { viewer, residues, loadEvent };
    });
    process.stdout.write(JSON.stringify({ ok: true, runId, evidence }) + "\n");
  } finally { await session.close(); }
}
main().catch(error => { process.stderr.write(`I09 failed: ${error.stack || error}\n`); process.exitCode = 1; });
