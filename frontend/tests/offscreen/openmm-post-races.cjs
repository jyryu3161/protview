"use strict";

// O14: a real old-run POST reaches the isolated backend, but its response is
// delayed until the user switches runs. No response or success is fabricated.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { launchOffscreen, capture, status } = require("./driver.cjs");
const { sha256, sourceDigest, waitForBoot, waitForViewer, assertViewer } = require("./normal-flow.cjs");

function parse(argv) {
  const input = { url: null, fixture: null, otherRun: null, artifacts: null, mode: null };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--url") input.url = argv[++i];
    else if (argv[i] === "--fixture") input.fixture = argv[++i];
    else if (argv[i] === "--other-run") input.otherRun = argv[++i];
    else if (argv[i] === "--artifacts") input.artifacts = argv[++i];
    else if (argv[i] === "--mode") input.mode = argv[++i];
    else throw new Error(`Unknown argument: ${argv[i]}`);
  }
  if (!input.url || !input.fixture || !input.otherRun || !input.artifacts ||
      !["submit", "start", "approve", "create"].includes(input.mode))
    throw new Error("Usage: openmm-post-races.cjs --url LOOPBACK --fixture public_1ubq.cif --other-run NO_OPENMM_RUN --artifacts PATH --mode submit|start|approve|create");
  const url = new URL(input.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("QA URL must be loopback HTTP(S)");
  assert.match(input.otherRun, /^run_[a-f0-9]+$/);
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

function post(body) {
  return { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

async function setup(input) {
  const run = await api(input.url, "/runs", post({ goal: `O14 isolated ${input.mode} POST response race`,
    context: [], dry_run: false, egress: "local_only" }), 201);
  const runId = run.run_id;
  const route = `/runs/${runId}`;
  const uploaded = await api(input.url, `${route}/uploads?filename=${encodeURIComponent(path.basename(input.fixture))}`, {
    method: "POST", headers: { "content-type": "application/octet-stream" }, body: fs.readFileSync(input.fixture),
  }, 201);
  assert.equal(uploaded.sha256, sha256(input.fixture));
  const loaded = await api(input.url, `${route}/commands`, post({ tool: "load_structure",
    args: { source: uploaded.upload_id, model_index: 0 }, decided_by: "human", execution_mode: "human" }));
  assert.equal(loaded.ok, true);
  const prepared = await api(input.url, `${route}/commands`, post({ tool: "prepare_structure",
    args: { structure: loaded.handle.handle, altloc: "highest_occupancy", waters: "keep_all",
      hydrogens: "strip", missing_residues: "leave_gaps", symmetry_mates: "ignore" },
    decided_by: "human", execution_mode: "human" }));
  assert.equal(prepared.ok, true);
  const preparedHandle = prepared.handle.handle;
  const preflight = await api(input.url, `${route}/jobs/preflight?structure=${encodeURIComponent(preparedHandle)}`);
  assert.equal(preflight.available, true);
  assert.equal(preflight.excluded.length, 58);
  let job = null;
  if (input.mode !== "submit") {
    job = await api(input.url, `${route}/jobs`, post({ protocol_id: "openmm_protein_minimize",
      args: { structure: preparedHandle, selection_policy: "protein_only", hydrogen_policy: "rebuild_pH7" }, timeout_s: 60 }));
    assert.equal(job.status, "queued");
  }
  if (["approve", "create"].includes(input.mode)) {
    const approvalRequired = await api(input.url, `${route}/jobs/${job.job_id}/start`, { method: "POST" }, 409);
    assert.equal(approvalRequired.approval.gate, "expensive_first_call");
  }
  if (input.mode === "create") {
    await api(input.url, `${route}/jobs/approve`, { method: "POST" });
    job = await api(input.url, `${route}/jobs/${job.job_id}/start`, { method: "POST" });
    assert.equal(job.status, "done", "Real local OpenMM setup must complete before report-create race");
    assert.equal((await api(input.url, `${route}/reports`)).filter(item => item.analysis_type === "openmm_protein_minimize").length, 0);
  }
  return { runId, preparedHandle, jobId: job?.job_id ?? null, setupStatus: job?.status ?? null,
    fixtureSha256: sha256(input.fixture), preflightExclusions: preflight.excluded.length };
}

async function bounded(promise, label, timeoutMs = 30000) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out`)), timeoutMs);
  })]); } finally { clearTimeout(timer); }
}

async function runRace(input) {
  const setupEvidence = await setup(input);
  const otherJobsBefore = await api(input.url, `/runs/${input.otherRun}/jobs`);
  const otherReportsBefore = await api(input.url, `/runs/${input.otherRun}/reports`);
  assert.ok(otherJobsBefore.every(job => job.status !== "done"));
  const session = await launchOffscreen({ url: new URL(`/?run=${setupEvidence.runId}`, input.url).toString(),
    artifacts: input.artifacts });
  const { app, page, artifacts } = session;
  const source = sourceDigest();
  const evidence = path.join(artifacts, `openmm-post-${input.mode}.jsonl`);
  let before;
  let release;
  const releaseGate = new Promise(resolve => { release = resolve; });
  let began;
  const beganGate = new Promise(resolve => { began = resolve; });
  let delivered;
  const deliveredGate = new Promise(resolve => { delivered = resolve; });
  let routePattern;
  let hold;
  try {
    await waitForBoot(page);
    assert.equal(new URL(page.url()).searchParams.get("run"), setupEvidence.runId);
    await waitForViewer(page);
    const section = page.getByText("OpenMM 단백질 전용 최소화 · kJ/mol").locator("..");
    if (input.mode === "submit") {
      await section.getByRole("button", { name: "단백질 입력·제외 항목 확인" }).click();
      await section.getByRole("region", { name: "OpenMM 제외 성분" }).waitFor({ timeout: 30000 });
      await section.getByLabel(/protein_only 선택과 제외 항목/).check();
      await section.getByLabel(/기존 수소 제거 후 pH 7.0/).check();
    } else if (input.mode === "start") {
      await section.getByText(/상태 queued/).waitFor({ timeout: 30000 });
    } else if (input.mode === "approve") {
      await section.getByRole("button", { name: "고비용 계산 승인 후 시작" }).waitFor({ timeout: 30000 });
    } else {
      await section.getByRole("button", { name: "OpenMM 방법 보고서 만들기" }).waitFor({ timeout: 30000 });
    }
    before = await status(app, page);
    const base = `**/api/runs/${setupEvidence.runId}`;
    routePattern = input.mode === "submit" ? `${base}/jobs` : input.mode === "start"
      ? `${base}/jobs/${setupEvidence.jobId}/start` : input.mode === "approve"
        ? `${base}/jobs/approve` : `${base}/method_reports`;
    hold = async route => {
      if (route.request().method() !== "POST") { await route.continue(); return; }
      try {
        const response = await route.fetch();
        began({ status: response.status(), url: route.request().url(), method: route.request().method() });
        await releaseGate;
        try { await route.fulfill({ response }); delivered({ state: "fulfilled" }); }
        catch (error) { delivered({ state: "browser_cancelled", reason: String(error) }); }
      } catch (error) { began({ status: null, error: String(error) }); delivered({ state: "fetch_failed", reason: String(error) }); }
    };
    await page.route(routePattern, hold);
    const buttonName = { submit: "OpenMM 작업 제출", start: "작업 시작",
      approve: "고비용 계산 승인 후 시작", create: "OpenMM 방법 보고서 만들기" }[input.mode];
    await section.getByRole("button", { name: buttonName }).click();
    const intercepted = await bounded(beganGate, "real POST interception", input.mode === "create" ? 120000 : 30000);
    assert.equal(intercepted.status, input.mode === "start" ? 409 : input.mode === "create" ? 201 : 200);
    await page.locator("#run-choice").selectOption(input.otherRun);
    await page.waitForFunction(id => new URL(location.href).searchParams.get("run") === id, input.otherRun);
    release();
    const delivery = await bounded(deliveredGate, "held POST delivery");
    const viewer = await waitForViewer(page, state => state.sourceHandle.includes(input.otherRun));
    assert.ok(viewer.sourceHandle.includes(input.otherRun));
    assert.equal(await page.getByText("시작 전위").count(), 0);
    assert.equal(await page.getByLabel("저장된 OpenMM 보고서 미리보기").count(), 0);
    const otherJobsAfter = await api(input.url, `/runs/${input.otherRun}/jobs`);
    const otherReportsAfter = await api(input.url, `/runs/${input.otherRun}/reports`);
    assert.deepEqual(otherJobsAfter, otherJobsBefore, "Old-run POST must not create an other-run job");
    assert.deepEqual(otherReportsAfter, otherReportsBefore, "Old-run POST must not create an other-run report");
    const targetJobs = await api(input.url, `/runs/${setupEvidence.runId}/jobs`);
    const targetReports = await api(input.url, `/runs/${setupEvidence.runId}/reports`);
    if (input.mode === "submit") assert.equal(targetJobs.length, 1);
    if (input.mode === "start") {
      assert.equal(targetJobs[0].status, "claimed");
      assert.equal(targetJobs[0].attempt_ordinal, 0);
    }
    if (input.mode === "approve") {
      assert.equal(targetJobs[0].status, "claimed", "Stale approve response must not chain-start old job");
      assert.equal(targetJobs[0].attempt_ordinal, 0);
    }
    if (input.mode === "create")
      assert.equal(targetReports.filter(item => item.analysis_type === "openmm_protein_minimize").length, 1);
    const proof = await capture(app, page, artifacts, `O14-${input.mode}`);
    assertViewer(proof.status);
    assert.equal(proof.status.offscreen, true);
    assert.equal(proof.status.visible, false);
    assert.deepEqual(proof.status.blockedRequests, []);
    const row = { caseId: `O14-${input.mode}`, status: "pass", fixture: "real old-run POST response held after backend commit",
      source, setup: setupEvidence, before, intercepted, delivery, after: proof.status,
      targetJobs, targetReports, otherJobsBefore, otherJobsAfter, otherReportsBefore, otherReportsAfter,
      screenshot: proof.screenshot, paint: proof.paint };
    fs.appendFileSync(evidence, JSON.stringify(row) + "\n");
    return { runId: setupEvidence.runId, evidence };
  } catch (error) {
    let proof = null;
    try { proof = await capture(app, page, artifacts, `O14-${input.mode}-failure`); } catch { /* preserve failure */ }
    fs.appendFileSync(evidence, JSON.stringify({ caseId: `O14-${input.mode}`, status: "fail",
      source, setup: setupEvidence, before, after: proof?.status, screenshot: proof?.screenshot,
      paint: proof?.paint, error: String(error) }) + "\n");
    throw error;
  } finally {
    release();
    if (routePattern && hold) await page.unroute(routePattern, hold);
    await session.close();
  }
}

if (require.main === module) {
  runRace(parse(process.argv.slice(2))).then(result => process.stdout.write(JSON.stringify({ ok: true, ...result }) + "\n"))
    .catch(error => { process.stderr.write(`OpenMM POST race click QA failed: ${error.stack || error}\n`); process.exitCode = 1; });
}

module.exports = { parse, runRace };
