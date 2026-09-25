"use strict";

// B03: only the initial dry-run record is a loopback API fixture. Every
// structure and OpenMM policy action is then made through the Electron UI.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { launchOffscreen, capture, status } = require("./driver.cjs");
const { sha256, sourceDigest, waitForBoot, waitForViewer, assertViewer } = require("./normal-flow.cjs");

function parse(argv) {
  const input = { url: null, fixture: null, artifacts: null };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--url") input.url = argv[++i];
    else if (argv[i] === "--fixture") input.fixture = argv[++i];
    else if (argv[i] === "--artifacts") input.artifacts = argv[++i];
    else throw new Error(`Unknown argument: ${argv[i]}`);
  }
  if (!input.url || !input.fixture || !input.artifacts)
    throw new Error("Usage: dry-run.cjs --url LOOPBACK --fixture public_1ubq.cif --artifacts PATH");
  const url = new URL(input.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("QA URL must be loopback HTTP(S)");
  input.url = url.origin;
  input.fixture = path.resolve(input.fixture);
  input.artifacts = path.resolve(input.artifacts);
  if (!fs.statSync(input.fixture).isFile()) throw new Error("Fixture is not a file");
  return input;
}

async function readJson(origin, route) {
  const response = await fetch(new URL(`/api${route}`, origin));
  assert.equal(response.status, 200);
  return response.json();
}

async function runDry(input) {
  const response = await fetch(new URL("/api/runs", input.url), { method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ goal: "B03 isolated dry-run UI QA", context: [], dry_run: true, egress: "local_only" }) });
  assert.equal(response.status, 201);
  const run = await response.json();
  assert.equal(run.dry_run, true);
  const route = `/runs/${run.run_id}`;
  const session = await launchOffscreen({ url: new URL(`/?run=${run.run_id}`, input.url).toString(),
    artifacts: input.artifacts });
  const { app, page, artifacts } = session;
  const evidence = path.join(artifacts, "dry-run.jsonl");
  const source = sourceDigest();
  const fixtureSha256 = sha256(input.fixture);
  const rows = [];
  async function step(caseId, action, observe) {
    const before = await status(app, page);
    try {
      await action();
      const assertion = await observe();
      const proof = await capture(app, page, artifacts, caseId);
      assert.equal(proof.status.offscreen, true);
      assert.equal(proof.status.visible, false);
      assert.deepEqual(proof.status.blockedRequests, []);
      const row = { caseId, status: "pass", fixture: "API-created dry-run record; actual Electron clicks",
        source, fixtureSha256, runId: run.run_id, before, after: proof.status,
        assertion, screenshot: proof.screenshot, paint: proof.paint };
      fs.appendFileSync(evidence, JSON.stringify(row) + "\n"); rows.push(row);
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* preserve failure */ }
      fs.appendFileSync(evidence, JSON.stringify({ caseId, status: "fail", source, fixtureSha256,
        runId: run.run_id, before, after: proof?.status, screenshot: proof?.screenshot,
        paint: proof?.paint, error: String(error) }) + "\n");
      throw error;
    }
  }
  try {
    await step("B03-badge", async () => { await waitForBoot(page); }, async () => {
      assert.equal(new URL(page.url()).searchParams.get("run"), run.run_id);
      assert.match(await page.locator("body").innerText(), /dry_run/);
      return { dryRunBadge: true };
    });
    await step("B03-upload", async () => {
      const chooser = page.waitForEvent("filechooser");
      await page.locator('input[type="file"]').click();
      await (await chooser).setFiles(input.fixture);
      await page.getByRole("button", { name: "구조 불러오기" }).waitFor({ timeout: 20000 });
    }, async () => ({ fixtureSha256 }));
    await step("B03-load", async () => {
      await page.getByRole("button", { name: "구조 불러오기" }).click();
      await waitForViewer(page);
    }, async () => ({ viewer: assertViewer(await status(app, page)) }));
    const section = page.getByText("OpenMM 단백질 전용 최소화 · kJ/mol").locator("..");
    await step("B03-prepare", async () => {
      const previous = await waitForViewer(page);
      await page.getByRole("combobox", { name: /^물/ }).selectOption("keep_all");
      await page.getByRole("button", { name: "전처리", exact: true }).click();
      await waitForViewer(page, viewer => viewer.sourceHandle !== previous.sourceHandle);
    }, async () => ({ viewer: assertViewer(await status(app, page)) }));
    await step("B03-preflight", async () => {
      await section.getByRole("button", { name: "단백질 입력·제외 항목 확인" }).click();
      await section.getByRole("region", { name: "OpenMM 제외 성분" }).waitFor({ timeout: 30000 });
      await section.getByLabel(/protein_only 선택과 제외 항목/).check();
      await section.getByLabel(/기존 수소 제거 후 pH 7.0/).check();
    }, async () => ({ exclusions: await section.getByRole("region", { name: "OpenMM 제외 성분" }).locator("p").count() }));
    await step("B03-submit", async () => {
      const submitted = page.waitForResponse(item => item.url().includes(`/api${route}/jobs`) &&
        item.request().method() === "POST", { timeout: 30000 });
      await section.getByRole("button", { name: "OpenMM 작업 제출" }).click();
      const result = await submitted;
      assert.equal(result.status(), 200);
      const plan = await result.json();
      assert.equal(plan.plan_only, true);
      assert.equal(plan.reason_code, "dry_run");
    }, async () => {
      const notice = section.locator('p[role="status"]');
      const expectedNotice = "dry-run 계획만 반환되었습니다. 작업은 생성되지 않았고 계산·예산은 사용되지 않았습니다.";
      await notice.filter({ hasText: expectedNotice }).waitFor({ timeout: 30000 });
      assert.equal((await notice.textContent()).trim(), expectedNotice);
      const jobs = await readJson(input.url, `${route}/jobs`);
      const budget = await readJson(input.url, `${route}/budget`);
      assert.deepEqual(jobs, []);
      assert.equal(budget.expensive_calls.used, 0);
      assert.equal(budget.external_tokens.used, 0);
      assert.equal(budget.usd.used, 0);
      assert.equal(await section.getByRole("button", { name: "작업 시작" }).count(), 0);
      return { jobs, budget, planNotice: expectedNotice, noPhysicalStartControl: true };
    });
    await step("B03-reopen", async () => {
      await page.reload();
      await waitForBoot(page);
      await waitForViewer(page);
    }, async () => {
      assert.equal(new URL(page.url()).searchParams.get("run"), run.run_id);
      assert.match(await page.locator("body").innerText(), /dry_run/);
      assert.deepEqual(await readJson(input.url, `${route}/jobs`), []);
      assert.equal(await section.locator('p[role="status"]').count(), 0,
        "Transient plan notice must clear on reopen");
      return { persistedDryRun: true, transientNoticeCleared: true,
        viewer: assertViewer(await status(app, page)) };
    });
    return { runId: run.run_id, evidence, cases: rows.length };
  } finally { await session.close(); }
}

if (require.main === module) {
  runDry(parse(process.argv.slice(2))).then(result => process.stdout.write(JSON.stringify({ ok: true, ...result }) + "\n"))
    .catch(error => { process.stderr.write(`Dry-run click QA failed: ${error.stack || error}\n`); process.exitCode = 1; });
}

module.exports = { parse, runDry };
