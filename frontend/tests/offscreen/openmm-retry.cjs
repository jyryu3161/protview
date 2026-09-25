"use strict";

// O12: prepare a genuine, time-limited failed job on the isolated QA backend,
// then use the visible Electron UI to request its bounded retry. The local API
// calls are fixture setup; the assertion under test is the real retry click.
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
    throw new Error("Usage: openmm-retry.cjs --url LOOPBACK --fixture public_1ubq.cif --artifacts PATH");
  const url = new URL(input.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("QA URL must be loopback HTTP(S)");
  input.url = url.origin;
  input.fixture = path.resolve(input.fixture);
  input.artifacts = path.resolve(input.artifacts);
  if (!fs.statSync(input.fixture).isFile()) throw new Error("Fixture is not a file");
  return input;
}

async function request(origin, route, init = {}, expected = 200) {
  const response = await fetch(new URL(`/api${route}`, origin), init);
  const body = await response.json();
  assert.ok((Array.isArray(expected) ? expected : [expected]).includes(response.status),
    `${route}: HTTP ${response.status} ${JSON.stringify(body)}`);
  return body;
}

function jsonPost(body) {
  return { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

async function setupFailedJob(input) {
  const origin = input.url;
  const fixture = fs.readFileSync(input.fixture);
  const run = await request(origin, "/runs", jsonPost({
    goal: "O12 isolated timeout fixture", context: [], dry_run: false, egress: "local_only",
  }), 201);
  const runId = run.run_id;
  assert.match(runId, /^run_[a-f0-9]+$/);
  const route = `/runs/${encodeURIComponent(runId)}`;
  const uploaded = await request(origin, `${route}/uploads?filename=${encodeURIComponent(path.basename(input.fixture))}`, {
    method: "POST", headers: { "content-type": "application/octet-stream" }, body: fixture,
  }, 201);
  assert.equal(uploaded.sha256, sha256(input.fixture));
  const loaded = await request(origin, `${route}/commands`, jsonPost({
    tool: "load_structure", args: { source: uploaded.upload_id, model_index: 0 },
    decided_by: "human", execution_mode: "human",
  }));
  assert.equal(loaded.ok, true);
  const sourceHandle = loaded.handle.handle;
  const prepared = await request(origin, `${route}/commands`, jsonPost({
    tool: "prepare_structure", args: { structure: sourceHandle, altloc: "highest_occupancy",
      waters: "keep_all", hydrogens: "strip", missing_residues: "leave_gaps", symmetry_mates: "ignore" },
    decided_by: "human", execution_mode: "human",
  }));
  assert.equal(prepared.ok, true);
  const preparedHandle = prepared.handle.handle;
  const preflight = await request(origin, `${route}/jobs/preflight?structure=${encodeURIComponent(preparedHandle)}`);
  assert.equal(preflight.available, true);
  assert.equal(preflight.excluded.length, 58);
  const job = await request(origin, `${route}/jobs`, jsonPost({
    protocol_id: "openmm_protein_minimize", timeout_s: 0.001,
    args: { structure: preparedHandle, selection_policy: "protein_only", hydrogen_policy: "rebuild_pH7" },
  }));
  assert.equal(job.status, "queued");
  assert.deepEqual(job.input_handles, [preparedHandle]);
  const jobRoute = `${route}/jobs/${encodeURIComponent(job.job_id)}`;
  const approval = await request(origin, `${jobRoute}/start`, { method: "POST" }, 409);
  assert.equal(approval.ok, false);
  assert.equal(approval.approval.gate, "expensive_first_call");
  await request(origin, `${route}/jobs/approve`, { method: "POST" });
  const failed = await request(origin, `${jobRoute}/start`, { method: "POST" });
  assert.equal(failed.status, "failed", "0.001 s physical worker fixture must fail, never fabricate failure");
  assert.equal(failed.output_handles.length, 0);
  assert.equal(failed.attempt_ordinal, 1);
  const beforeBudget = await request(origin, `${route}/budget`);
  return { runId, jobId: job.job_id, sourceHandle, preparedHandle, failed, beforeBudget,
    fixtureSha256: sha256(input.fixture), timeout_s: 0.001 };
}

async function runRetry(input) {
  const setup = await setupFailedJob(input);
  const url = new URL(`/?run=${setup.runId}`, input.url).toString();
  const session = await launchOffscreen({ url, artifacts: input.artifacts });
  const { app, page, artifacts } = session;
  const source = sourceDigest();
  const evidence = path.join(artifacts, "openmm-retry.jsonl");
  let before;
  try {
    await waitForBoot(page);
    await waitForViewer(page);
    before = await status(app, page);
    const section = page.getByText("OpenMM 단백질 전용 최소화 · kJ/mol").locator("..");
    await section.getByText(/상태 failed/).waitFor({ timeout: 30000 });
    await section.getByRole("button", { name: "실패한 작업 재시도" }).click();
    await section.getByText(/상태 queued/).waitFor({ timeout: 30000 });
    const after = await status(app, page);
    assertViewer(after);
    const job = await request(input.url, `/runs/${setup.runId}/jobs/${setup.jobId}`);
    const afterBudget = await request(input.url, `/runs/${setup.runId}/budget`);
    assert.equal(job.status, "queued");
    assert.equal(job.attempt_ordinal, 1, "Retry request must not silently start a second attempt");
    assert.deepEqual(job.input_handles, [setup.preparedHandle]);
    assert.deepEqual(job.output_handles, []);
    assert.deepEqual(afterBudget.expensive_calls, setup.beforeBudget.expensive_calls,
      "Retry request must not charge or start a second physical attempt");
    const proof = await capture(app, page, artifacts, "O12");
    assert.equal(proof.status.offscreen, true);
    assert.equal(proof.status.visible, false);
    assert.deepEqual(proof.status.blockedRequests, []);
    const row = { caseId: "O12", status: "pass", fixture: "real physical 0.001 s timeout; setup via isolated loopback API",
      source, setup, before, after: proof.status, retryJob: job, afterBudget,
      screenshot: proof.screenshot, paint: proof.paint };
    fs.appendFileSync(evidence, JSON.stringify(row) + "\n");
    return { runId: setup.runId, jobId: setup.jobId, evidence };
  } catch (error) {
    let proof = null;
    try { proof = await capture(app, page, artifacts, "O12-failure"); } catch { /* preserve failure */ }
    fs.appendFileSync(evidence, JSON.stringify({ caseId: "O12", status: "fail", source,
      setup, before, after: proof?.status, screenshot: proof?.screenshot,
      paint: proof?.paint, error: String(error) }) + "\n");
    throw error;
  } finally {
    await session.close();
  }
}

if (require.main === module) {
  runRetry(parse(process.argv.slice(2))).then(result => process.stdout.write(JSON.stringify({ ok: true, ...result }) + "\n"))
    .catch(error => { process.stderr.write(`OpenMM retry click QA failed: ${error.stack || error}\n`); process.exitCode = 1; });
}

module.exports = { parse, runRetry };
