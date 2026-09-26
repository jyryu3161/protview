"use strict";

// O09/B01: API setup only creates two distinct queued jobs. Job selection,
// run reopening, and budget observations use actual offscreen Electron UI.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { launchOffscreen, capture, status } = require("./driver.cjs");
const { sha256, sourceDigest, waitForBoot, waitForViewer, assertViewer } = require("./normal-flow.cjs");

function parse(argv) {
  const input = { url: null, fixture: null, artifacts: null, fullRun: null,
    queuedCancelRun: null, runningCancelRun: null };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--url") input.url = argv[++i];
    else if (argv[i] === "--fixture") input.fixture = argv[++i];
    else if (argv[i] === "--artifacts") input.artifacts = argv[++i];
    else if (argv[i] === "--full-run") input.fullRun = argv[++i];
    else if (argv[i] === "--queued-cancel-run") input.queuedCancelRun = argv[++i];
    else if (argv[i] === "--running-cancel-run") input.runningCancelRun = argv[++i];
    else throw new Error(`Unknown argument: ${argv[i]}`);
  }
  if (Object.values(input).some(value => !value)) throw new Error("Usage: openmm-persistence.cjs --url LOOPBACK --fixture public_1ubq.cif --artifacts PATH --full-run RUN --queued-cancel-run RUN --running-cancel-run RUN");
  const url = new URL(input.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("QA URL must be loopback HTTP(S)");
  for (const name of ["fullRun", "queuedCancelRun", "runningCancelRun"])
    assert.match(input[name], /^run_[a-f0-9]+$/);
  input.url = url.origin;
  input.fixture = path.resolve(input.fixture);
  input.artifacts = path.resolve(input.artifacts);
  if (!fs.statSync(input.fixture).isFile()) throw new Error("Fixture is not a file");
  return input;
}

async function api(origin, route, init = {}, expected = 200) {
  const response = await fetch(new URL(`/api${route}`, origin), init);
  const body = await response.json();
  assert.equal(response.status, expected, `${route}: HTTP ${response.status} ${JSON.stringify(body)}`);
  return body;
}

function post(body) { return { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }; }

async function setup(input) {
  const run = await api(input.url, "/runs", post({ goal: "O09 isolated two-job selection fixture",
    context: [], dry_run: false, egress: "local_only" }), 201);
  const route = `/runs/${run.run_id}`;
  const uploaded = await api(input.url, `${route}/uploads?filename=${encodeURIComponent(path.basename(input.fixture))}`, {
    method: "POST", headers: { "content-type": "application/octet-stream" }, body: fs.readFileSync(input.fixture),
  }, 201);
  assert.equal(uploaded.sha256, sha256(input.fixture));
  const loaded = await api(input.url, `${route}/commands`, post({ tool: "load_structure",
    args: { source: uploaded.upload_id, model_index: 0 }, decided_by: "human", execution_mode: "human" }));
  assert.equal(loaded.ok, true);
  const jobs = [];
  for (const waters of ["keep_all", "strip_all"]) {
    const prepared = await api(input.url, `${route}/commands`, post({ tool: "prepare_structure",
      args: { structure: loaded.handle.handle, altloc: "highest_occupancy", waters,
        hydrogens: "strip", missing_residues: "leave_gaps", symmetry_mates: "ignore" },
      decided_by: "human", execution_mode: "human" }));
    assert.equal(prepared.ok, true);
    const job = await api(input.url, `${route}/jobs`, post({ protocol_id: "openmm_protein_minimize",
      args: { structure: prepared.handle.handle, selection_policy: "protein_only",
        hydrogen_policy: "rebuild_pH7" }, timeout_s: 60 }));
    assert.equal(job.status, "queued");
    jobs.push({ jobId: job.job_id, preparedHandle: prepared.handle.handle, waters });
  }
  assert.notEqual(jobs[0].jobId, jobs[1].jobId);
  return { runId: run.run_id, jobs, fixtureSha256: sha256(input.fixture) };
}

async function runPersistence(input) {
  const setupEvidence = await setup(input);
  const session = await launchOffscreen({ url: new URL(`/?run=${setupEvidence.runId}`, input.url).toString(),
    artifacts: input.artifacts });
  const { app, page, artifacts } = session;
  const evidence = path.join(artifacts, "openmm-persistence.jsonl");
  const source = sourceDigest();
  const rows = [];
  const section = page.getByText("OpenMM 단백질 전용 최소화 · kJ/mol").locator("..");
  async function row(caseId, action, observe) {
    const before = await status(app, page);
    try {
      await action();
      const assertion = await observe();
      const proof = await capture(app, page, artifacts, caseId);
      assertViewer(proof.status);
      assert.equal(proof.status.offscreen, true);
      assert.equal(proof.status.visible, false);
      assert.deepEqual(proof.status.blockedRequests, []);
      const item = { caseId, status: "pass", fixture: "two queued jobs via isolated loopback setup",
        source, setup: setupEvidence, before, after: proof.status, assertion,
        screenshot: proof.screenshot, paint: proof.paint };
      fs.appendFileSync(evidence, JSON.stringify(item) + "\n"); rows.push(item);
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* preserve failure */ }
      fs.appendFileSync(evidence, JSON.stringify({ caseId, status: "fail", source,
        setup: setupEvidence, before, after: proof?.status, screenshot: proof?.screenshot,
        paint: proof?.paint, error: String(error) }) + "\n");
      throw error;
    }
  }
  async function budgetAssertion(runId) {
    const budget = await api(input.url, `/runs/${runId}/budget`);
    const events = await api(input.url, `/runs/${runId}/events?after=0&limit=500`);
    const reservations = events.filter(event => event.type === "budget_reserved" &&
      event.tool === "openmm_protein_minimize").length;
    assert.equal(budget.expensive_calls.used, reservations, "Budget must match durable reservation ledger");
    const expected = `expensive ${budget.expensive_calls.used}/${budget.expensive_calls.limit}`;
    await page.waitForFunction(value => document.querySelector(".mw-top-budget")?.textContent?.trim() === value, expected);
    const topbar = (await page.locator(".mw-top-budget").textContent()).trim();
    const detail = (await page.locator(".mw-budget__v").nth(1).textContent()).trim();
    assert.equal(topbar, expected);
    assert.equal(detail, `${budget.expensive_calls.used} / ${budget.expensive_calls.limit}`);
    return { runId, topbar, detail, reservations, budget };
  }
  try {
    await waitForBoot(page);
    await waitForViewer(page);
    await row("O09-job-selector", async () => {
      const chooser = section.getByLabel("작업");
      assert.equal(await chooser.locator("option").count(), 2);
      await chooser.selectOption(setupEvidence.jobs[0].jobId);
      await section.getByText(new RegExp(`상태 queued.*${setupEvidence.jobs[0].jobId}`)).waitFor();
      await chooser.selectOption(setupEvidence.jobs[1].jobId);
      await section.getByText(new RegExp(`상태 queued.*${setupEvidence.jobs[1].jobId}`)).waitFor();
    }, async () => ({ selectedJob: await section.getByLabel("작업").inputValue(),
      jobs: await api(input.url, `/runs/${setupEvidence.runId}/jobs`) }));
    for (const [caseId, runId] of [["B01-full", input.fullRun],
      ["B01-queued-cancel", input.queuedCancelRun], ["B01-running-cancel", input.runningCancelRun]]) {
      await row(caseId, async () => {
        await page.locator("#run-choice").selectOption(runId);
        await page.waitForFunction(id => new URL(location.href).searchParams.get("run") === id, runId);
        await waitForViewer(page, viewer => viewer.sourceHandle.includes(runId));
      }, async () => {
        const jobs = await api(input.url, `/runs/${runId}/jobs`);
        assert.equal(jobs.length, 1);
        assert.equal(await section.getByLabel("작업").inputValue(), jobs[0].job_id);
        assert.match(await section.innerText(), new RegExp(`상태 ${jobs[0].status}`));
        return { jobs, budget: await budgetAssertion(runId) };
      });
    }
    await row("O09-reopen", async () => {
      await page.locator("#run-choice").selectOption(setupEvidence.runId);
      await page.waitForFunction(id => new URL(location.href).searchParams.get("run") === id, setupEvidence.runId);
      await waitForViewer(page, viewer => viewer.sourceHandle.includes(setupEvidence.runId));
      assert.equal(await section.getByLabel("작업").locator("option").count(), 2);
      await section.getByLabel("작업").selectOption(setupEvidence.jobs[0].jobId);
      await section.getByText(new RegExp(`상태 queued.*${setupEvidence.jobs[0].jobId}`)).waitFor();
    }, async () => ({ selectedJob: await section.getByLabel("작업").inputValue(),
      jobs: await api(input.url, `/runs/${setupEvidence.runId}/jobs`),
      budget: await budgetAssertion(setupEvidence.runId) }));
    return { runId: setupEvidence.runId, evidence, cases: rows.length };
  } finally { await session.close(); }
}

if (require.main === module) {
  runPersistence(parse(process.argv.slice(2))).then(result => process.stdout.write(JSON.stringify({ ok: true, ...result }) + "\n"))
    .catch(error => { process.stderr.write(`OpenMM persistence click QA failed: ${error.stack || error}\n`); process.exitCode = 1; });
}

module.exports = { parse, runPersistence };
