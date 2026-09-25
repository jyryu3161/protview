"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const root = "/Users/jaeyongryu/Projects/protview";
const { launchOffscreen, capture, status } = require(path.join(root, "frontend/tests/offscreen/driver.cjs"));
const { waitForBoot, waitForViewer, sourceDigest } = require(path.join(root, "frontend/tests/offscreen/normal-flow.cjs"));
const url = "http://127.0.0.1:3000";
const fixture = "/tmp/protview-qa/m8-inputs/synthetic_water_hydrogen.pdb";
const artifacts = process.env.PROTVIEW_EXTRA_ARTIFACTS || "/tmp/protview-qa/m8-extra-v12-final";
const fixtureSha256 = crypto.createHash("sha256").update(fs.readFileSync(fixture)).digest("hex");
function identity(ref) { return [ref.model_number, ref.chain_auth, ref.chain_label, ref.seq_auth,
  ref.seq_label, ref.icode, ref.resname].map(v => v ?? "").join("/"); }
function matchesBackend(item, native) {
  return item.model_number === native.model_number && item.chain_auth === native.chain_auth &&
    item.seq_auth === native.seq_auth && item.icode === native.icode && item.resname === native.resname &&
    (item.chain_label == null || item.chain_label === native.chain_label) &&
    (item.seq_label == null || item.seq_label === native.seq_label);
}
function displayResidue(ref) { return `${ref.resname} auth ${ref.chain_auth}/${ref.seq_auth}${ref.icode || ""}` +
  ` · label ${ref.chain_label ?? "unknown"}/${ref.seq_label ?? "unknown"} · model ${ref.model_number ?? "unknown"}`; }
async function preview(page) {
  return JSON.parse(await page.getByLabel("전송 상태 미리보기").textContent());
}
async function agentStatus(page) {
  const value = await page.locator(".mw-agent-status").innerText();
  assert.doesNotMatch(value, /viewer action revision must increase|장면 동기화 실패|HTTP 409/,
    "Native canvas selection must not leave an agent scene error");
  return value;
}
async function main() {
  const session = await launchOffscreen({ url, artifacts });
  const { app, page } = session;
  const evidence = path.join(artifacts, "V12.jsonl");
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
      const row = { caseId, status: "pass", source, fixtureSha256, runId, before,
        after: proof.status, assertion, screenshot: proof.screenshot, paint: proof.paint };
      fs.appendFileSync(evidence, JSON.stringify(row) + "\n");
      return row;
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch {}
      fs.appendFileSync(evidence, JSON.stringify({ caseId, status: "fail", source, fixtureSha256,
        runId, before, after: proof?.status, screenshot: proof?.screenshot,
        paint: proof?.paint, error: String(error) }) + "\n");
      throw error;
    }
  }
  try {
    await step("V12-setup", async () => {
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
      await page.getByRole("button", { name: "구조 불러오기" }).click();
      await waitForViewer(page);
      await page.getByRole("button", { name: "ball-and-stick" }).click();
      await page.waitForFunction(() => window.__protviewQaSnapshot?.().molstarRepresentation?.toLowerCase().includes("ball"));
    }, async () => {
      const observed = await status(app, page);
      assert.equal(observed.viewer.selection, null);
      assert.ok(observed.viewer.sourceHandle.includes(runId));
      return { viewer: observed.viewer, canvas: await page.locator("canvas.mw-molstar-canvas").boundingBox() };
    });
    const canvas = page.locator("canvas.mw-molstar-canvas");
    const box = await canvas.boundingBox();
    assert.ok(box);
    const atom = { x: box.x + 319, y: box.y + 400 };
    const blank = { x: box.x + 579, y: box.y + 505 };
    let selected;
    let selectedAlias;
    await step("V12-pick", async () => {
      await page.mouse.click(atom.x, atom.y);
      await page.waitForFunction(() => !!window.__protviewQaSnapshot?.().selection, null, { timeout: 10000 });
      await page.waitForFunction(() => {
        try { return !!JSON.parse(document.querySelector('pre[aria-label="전송 상태 미리보기"]')?.textContent || "{}").selected_target; }
        catch { return false; }
      }, null, { timeout: 10000 });
    }, async () => {
      const observed = await status(app, page);
      selected = observed.viewer.selection;
      assert.ok(selected);
      assert.ok(observed.viewer.sourceHandle.includes(runId));
      const response = await fetch(`${url}/api/runs/${runId}/structures/residues?handle=${encodeURIComponent(observed.viewer.sourceHandle)}`);
      assert.equal(response.status, 200);
      const residues = await response.json();
      const matching = residues.residues.filter(item => matchesBackend(item, selected));
      assert.equal(matching.length, 1, "Native pick must uniquely match the displayed source identity");
      const legend = await page.locator("main.mw-canvas").innerText();
      assert.ok(legend.includes(`선택: ${displayResidue(matching[0])}`), "UI legend must match mapped source residue");
      const projected = await preview(page);
      selectedAlias = projected.selected_target;
      assert.match(selectedAlias, /^t\d{4}$/);
      return { atom, selection: selected, legend, displayedSource: observed.viewer.sourceHandle,
        matchingBackendResidue: matching[0], preview: projected, agentStatus: await agentStatus(page) };
    });
    let second;
    const attempts = [];
    await step("V12-different-residue", async () => {
      for (const target of [
        { x: box.x + 270, y: box.y + 425 },
        { x: box.x + 360, y: box.y + 400 },
        { x: box.x + 295, y: box.y + 445 },
        { x: box.x + 599, y: box.y + 51 },
      ]) {
        await page.mouse.click(target.x, target.y);
        await page.waitForTimeout(200);
        const candidate = (await status(app, page)).viewer.selection;
        attempts.push({ target, selection: candidate });
        if (candidate && identity(candidate) !== identity(selected)) {
          second = candidate;
          break;
        }
      }
      assert.ok(second, "Actual pointer clicks did not select a different displayed residue");
      await page.waitForFunction(previous => {
        try { const alias = JSON.parse(document.querySelector('pre[aria-label="전송 상태 미리보기"]')?.textContent || "{}").selected_target;
          return !!alias && alias !== previous; }
        catch { return false; }
      }, selectedAlias, { timeout: 10000 });
    }, async () => {
      const observed = await status(app, page);
      assert.equal(identity(observed.viewer.selection), identity(second));
      assert.ok(observed.viewer.sourceHandle.includes(runId));
      const response = await fetch(`${url}/api/runs/${runId}/structures/residues?handle=${encodeURIComponent(observed.viewer.sourceHandle)}`);
      assert.equal(response.status, 200);
      const residues = await response.json();
      const matching = residues.residues.filter(item => matchesBackend(item, second));
      assert.equal(matching.length, 1);
      const legend = await page.locator("main.mw-canvas").innerText();
      assert.ok(legend.includes(`선택: ${displayResidue(matching[0])}`));
      const projected = await preview(page);
      assert.match(projected.selected_target, /^t\d{4}$/);
      assert.notEqual(projected.selected_target, selectedAlias);
      return { attempts, selection: second, previousSelection: selected, matchingBackendResidue: matching[0],
        legend, preview: projected, agentStatus: await agentStatus(page) };
    });
    let distanceBeforeLocal;
    await step("V12-next-local-command", async () => {
      distanceBeforeLocal = (await status(app, page)).viewer.camera.distance;
      await page.locator('section[aria-label="뷰어 요청"]').getByRole("button", { name: "확대" }).click();
      await page.waitForFunction(() => window.__protviewQaSnapshot?.().lastAck?.status === "applied",
        null, { timeout: 10000 });
    }, async () => {
      const observed = await status(app, page);
      assert.equal(identity(observed.viewer.selection), identity(second));
      assert.equal(observed.viewer.lastAck.status, "applied");
      assert.ok(observed.viewer.camera.distance < distanceBeforeLocal,
        "Actual camera distance must decrease after local zoom");
      const projected = await preview(page);
      assert.match(projected.selected_target, /^t\d{4}$/);
      assert.notEqual(projected.selected_target, selectedAlias);
      return { beforeDistance: distanceBeforeLocal, viewer: observed.viewer,
        preview: projected, agentStatus: await agentStatus(page) };
    });
    await step("V12-blank-clear", async () => {
      await page.mouse.click(blank.x, blank.y);
      await page.waitForFunction(() => window.__protviewQaSnapshot?.().selection === null, null, { timeout: 10000 });
      await page.waitForFunction(() => {
        try { return JSON.parse(document.querySelector('pre[aria-label="전송 상태 미리보기"]')?.textContent || "{}").selected_target == null; }
        catch { return false; }
      }, null, { timeout: 10000 });
    }, async () => {
      const observed = await status(app, page);
      assert.equal(observed.viewer.selection, null);
      assert.ok(observed.viewer.sourceHandle.includes(runId));
      const legend = await page.locator("main.mw-canvas").innerText();
      assert.ok(!legend.includes("선택:"), "Blank native click must clear projected legend");
      return { blank, previousSelection: second, nativeSelection: null, legend,
        preview: await preview(page), agentStatus: await agentStatus(page) };
    });
    process.stdout.write(JSON.stringify({ ok: true, runId, evidence }) + "\n");
  } finally { await session.close(); }
}
main().catch(error => { process.stderr.write(`V12 final failed: ${error.stack || error}\n`); process.exitCode = 1; });
