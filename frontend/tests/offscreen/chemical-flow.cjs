"use strict";

// M11 real offscreen control harness. The parent owns service release and final review.
// Fixtures are supplied prepared/public or explicitly labeled analytic inputs, not experiments.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const sharp = require("sharp");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const ledger = require("./m11-ledger.cjs");

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const atomIdentity = ref => JSON.stringify([ref.structure_handle, ref.residue.model_number,
  ref.residue.chain_auth, ref.residue.chain_label, ref.residue.seq_auth, ref.residue.seq_label,
  ref.residue.icode, ref.residue.resname, ref.atom_name, ref.altloc, ref.element, ref.site_index]);
const separation = (a, b) => Math.hypot(...a.map((value, index) => value - b[index]));
function angleAtHydrogen(donor, hydrogen, acceptor) {
  const a = donor.map((value, index) => value - hydrogen[index]);
  const b = acceptor.map((value, index) => value - hydrogen[index]);
  const cos = a.reduce((sum, value, index) => sum + value * b[index], 0) /
    (Math.hypot(...a) * Math.hypot(...b));
  return Math.acos(Math.max(-1, Math.min(1, cos))) * 180 / Math.PI;
}
const modes = new Set(["create", "empty", "prepare-only", "attach", "job-controls", "running-cancel", "detect-controls",
  "retry-failed", "reopen", "reopen-complete", "restrictions", "faults", "replay", "capability", "invalid-inputs",
  "invalid-attach"]);
const newRunModes = ["create", "empty", "prepare-only", "job-controls", "running-cancel", "capability", "invalid-inputs"];
const capabilityStates = ["ready", "worker_missing", "worker_version_invalid"];
function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null,
    run: null, receptor: null, sdf: null, sidecar: null, connectivity: "pdb_conect",
    complex: null, ligand: null, mapping: null, result: null, otherResult: null,
    report: null, otherReport: null, scene: null, job: null, graph: null,
    failureExpected: "false", failureLocalized: "false", expectCapability: null, variants: null,
    expectMarkdownSha: null, expectJsonSha: null, fixtureLabel: null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !modes.has(value.mode)) throw new Error(
    `Usage: chemical-flow.cjs --mode ${[...modes].join("|")} --artifacts tests/offscreen/artifacts/m11-... [--url http://127.0.0.1:3000] [--run run_...] [--receptor ../backend/tests/fixtures/chemical/prolif-vina-rec.pdb --sdf ../backend/tests/fixtures/chemical/prolif-vina-output.sdf] [--complex obj://... --mapping <setup-out>/m11-attach-mapping-run.json --sidecar <setup-out>/m11-attach-bonds-run.json --ligand <setup-out>/m11-attach-ligand-instance-run.json] [--result obj://... --report obj://... --scene obj://...] [--expect-capability ${capabilityStates.join("|")}] [--variants <dir from scripts/m11_invalid_inputs.py>]. Synthetic inputs: scripts/m11_qa_inputs.py and scripts/m11_invalid_inputs.py; run-bound attach inputs: scripts/m11_attach_browser_setup.py; full sequence: scripts/m11_offscreen_acceptance.py.`);
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only loopback service is permitted");
  if (value.run) assert.match(value.run, /^run_[a-f0-9]+$/);
  for (const key of ["receptor", "sdf", "sidecar", "mapping", "ligand"])
    if (value[key]) {
      value[key] = path.resolve(value[key]);
      if (!fs.statSync(value[key], { throwIfNoEntry: false })?.isFile())
        throw new Error(`--${key} input file not found: ${value[key]}`);
    }
  if (value.variants) {
    value.variants = path.resolve(value.variants);
    assert.ok(fs.statSync(path.join(value.variants, "m11-invalid-cases.json"), { throwIfNoEntry: false })?.isFile(),
      "--variants must be an output directory of scripts/m11_invalid_inputs.py");
  }
  if (["create", "empty", "prepare-only", "job-controls", "running-cancel", "capability"].includes(value.mode))
    assert.ok(value.receptor && value.sdf);
  if (value.mode === "retry-failed") assert.ok(value.run && value.job);
  if (value.mode === "detect-controls") assert.ok(value.run && value.graph);
  if (value.mode === "attach") assert.ok(value.run && value.complex && value.sdf && value.mapping && value.ligand);
  if (["reopen", "reopen-complete", "restrictions", "replay", "faults"].includes(value.mode))
    assert.ok(value.run && value.result);
  if (value.mode === "replay") assert.ok(value.report);
  if (value.mode === "capability") assert.ok(capabilityStates.includes(value.expectCapability),
    "--mode capability needs --expect-capability ready|worker_missing|worker_version_invalid");
  if (value.expectCapability) assert.ok(capabilityStates.includes(value.expectCapability));
  if (value.mode === "invalid-inputs") assert.ok(value.variants && !value.run);
  if (value.mode === "invalid-attach") assert.ok(value.variants && value.run && value.complex && value.ligand &&
    value.sdf, "--mode invalid-attach needs --variants (generated with --attach-sidecar) --run --complex --ligand --sdf");
  if (value.connectivity === "sidecar") assert.ok(value.sidecar);
  value.artifacts = path.resolve(value.artifacts);
  value.url = new URL(value.run ? `/?run=${value.run}` : "/", value.url).toString();
  return value;
}
async function chemical(page) {
  return page.evaluate(() => typeof window.__protviewQaChemical === "function"
    ? window.__protviewQaChemical() : null);
}
async function waitChemical(page, predicate, timeout = 45000) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    last = await chemical(page);
    if (last && predicate(last)) return last;
    await page.waitForTimeout(100);
  }
  throw new Error(`Chemical native observation timed out: ${JSON.stringify(last)}`);
}
async function readApi(page, route) {
  const response = await page.request.get(new URL(`/api${route}`, page.url()).toString());
  assert.equal(response.status(), 200, `${route}: ${await response.text()}`);
  return response.json();
}
async function getBytes(page, route) {
  const response = await page.request.get(new URL(`/api${route}`, page.url()).toString());
  assert.equal(response.status(), 200, route);
  return Buffer.from(await response.body());
}
async function runEvents(page, run) {
  const events = [];
  let after = 0;
  for (;;) {
    const pageEvents = await readApi(page, `/runs/${run}/events?after=${after}&limit=500`);
    events.push(...pageEvents);
    if (pageEvents.length < 500) break;
    after = pageEvents.at(-1).seq;
  }
  return events;
}
async function scienceEvents(page, run) {
  return (await runEvents(page, run)).filter(event => ["object_created", "tool_called", "tool_succeeded", "tool_failed",
    "job_submitted", "job_terminal", "budget_reserved", "approval_requested", "approval_resolved"].includes(event.type));
}
async function imageNonblank(file) {
  const { data, info } = await sharp(file).removeAlpha().raw().toBuffer({ resolveWithObject: true });
  let low = 255, high = 0;
  for (const value of data) { low = Math.min(low, value); high = Math.max(high, value); }
  assert.ok(info.width >= 600 && info.height >= 400 && high - low > 20,
    `Offscreen page did not contain a rendered interface: ${JSON.stringify({ width: info.width, height: info.height, low, high })}`);
  return { width: info.width, height: info.height, low, high, sha256: sha(fs.readFileSync(file)) };
}
async function chooseFile(page, label, file) {
  const holder = page.locator(".mw-chemical-file").filter({ hasText: label });
  assert.equal(await holder.count(), 1, `Expected one file input for ${label}`);
  const input = holder.locator('input[type="file"]');
  const chooser = page.waitForEvent("filechooser", { timeout: 15000 });
  await input.click();
  await (await chooser).setFiles(file);
  await holder.getByText(/obj:\/\/run_/).waitFor({ timeout: 30000 });
  // The immutable import must hold the exact chosen bytes (H02 original bytes/hash).
  const handle = (await holder.getByText(/obj:\/\/run_/).innerText()).trim();
  const run = new URL(page.url()).searchParams.get("run");
  const meta = await readApi(page, `/runs/${run}/objects/meta?handle=${encodeURIComponent(handle)}`);
  const local = sha(fs.readFileSync(file));
  assert.equal(meta.summary?.sha256, local, `Imported ${label} bytes differ from the chosen file`);
  return { path: file, bytes: fs.statSync(file).size, sha256: local, handle,
    provenance: ledger.provenanceLabel(path.basename(file)) };
}
function nestedSelect(page, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return page.locator("label").filter({ hasText: new RegExp(`^\\s*${escaped}`) }).locator("select");
}
async function selectByLabel(page, name, value) {
  const control = nestedSelect(page, name);
  assert.equal(await control.count(), 1, `Expected one visible ${name} select`);
  await control.selectOption(value);
}
async function click(page, name) { await page.getByRole("button", { name, exact: true }).click(); }
/** Click a real control and wait for its own POST to answer before reading durable state (click resolves on input). */
async function clickAwaitingPost(page, name, pathSuffix) {
  const response = page.waitForResponse(value => value.request().method() === "POST" &&
    new URL(value.url()).pathname.endsWith(pathSuffix), { timeout: 60000 });
  await click(page, name);
  return (await response).status();
}
async function rail(page, name) { await page.getByRole("tab", { name: new RegExp(`^${name}(?: ·|$)`) }).click(); }
async function submittedJob(page, stage, previous = null) {
  return waitChemical(page, state => {
    const id = stage === "prepare" ? state.prepareJobId : state.detectJobId;
    return !!id && id !== previous;
  }, 30000);
}
async function openWorkspace(page, input, beforeChemicalOpen = null) {
  if (newRunModes.includes(input.mode) && !input.run) {
    // A fresh QA root has no run, so the chemical entry appears only after a local-only run exists.
    await page.getByRole("button", { name: "새 run", exact: true }).waitFor({ timeout: 30000 });
    // Wait for the page's own boot (it reopens the latest saved run); a new run clicked during boot can be
    // reopened again by that boot read, which closes a chemical workspace opened in between.
    const hasRuns = (await readApi(page, "/runs")).length > 0;
    await page.waitForFunction(existing => {
      const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "새 run");
      const selected = new URL(location.href).searchParams.get("run");
      return !!button && !button.disabled && (existing ? /^run_/.test(selected ?? "")
        : document.body.textContent?.includes("현재 사용 불가"));
    }, hasRuns, { timeout: 30000 });
    const previousRun = new URL(page.url()).searchParams.get("run");
    await click(page, "새 run");
    await page.waitForURL(url => {
      const selected = url.searchParams.get("run");
      return !!selected && /^run_[a-f0-9]+$/.test(selected) && selected !== previousRun;
    }, { timeout: 30000 });
  }
  await page.getByRole("button", { name: "화학 상호작용 작업 열기" }).waitFor({ timeout: 30000 });
  if (beforeChemicalOpen) await beforeChemicalOpen(new URL(page.url()).searchParams.get("run"));
  await click(page, "화학 상호작용 작업 열기");
  await page.getByText("준비 입력과 실제 화학 상호작용", { exact: true }).waitFor({ timeout: 30000 });
  const selected = new URL(page.url()).searchParams.get("run");
  assert.match(selected ?? "", /^run_[a-f0-9]+$/);
  if (input.run) assert.equal(selected, input.run);
  await waitChemical(page, state => state.runId === selected, 30000);
  return selected;
}
async function testRestrictions(page, label) {
  const names = ["프롬프트 사용 불가", "현재 보기 저장", "현재 보기 PNG 내보내기",
    "원자 거리 측정", "두 구조 비교 추가"];
  for (const name of names) assert.equal(await page.getByRole("button", { name, exact: true }).isDisabled(), true,
    `${label}: ${name} is enabled for chemical source`);
  await page.getByText(/Chemical sources are not supported by saved-scene\/export schema v1/).waitFor();
  return names;
}
const RESTRICTED_EVENT_TYPES = new Set(["viewer_intent_requested", "viewer_dispatch_started", "viewer_command_ack",
  "viewer_scene_admitted", "viewer_scene_saved", "viewer_figure_admitted", "viewer_figure_saved"]);
const RESTRICTED_OBJECT_KINDS = new Set(["viewer_scene", "viewer_figure", "atom_distance", "rigid_alignment"]);
async function restrictedArtifacts(page, run) {
  return (await runEvents(page, run)).filter(event => RESTRICTED_EVENT_TYPES.has(event.type) ||
    (event.type === "object_created" && RESTRICTED_OBJECT_KINDS.has(event.kind)))
    .map(event => ({ seq: event.seq, type: event.type, kind: event.kind ?? null, handle: event.handle ?? null }));
}
/** H12: actual pointer input on every disabled M8/M9/M10 control must create no intent, scene, figure or measurement. */
async function attemptRestrictedControls(page, label) {
  const run = new URL(page.url()).searchParams.get("run");
  const names = await testRestrictions(page, label);
  const reason = (await page.getByText(/Chemical sources are not supported by saved-scene\/export schema v1/)
    .innerText()).trim();
  const before = await restrictedArtifacts(page, run);
  const attempts = [];
  for (const name of names) {
    const button = page.getByRole("button", { name, exact: true });
    let outcome = "clicked";
    try { await button.click({ force: true, timeout: 5000 }); } catch (error) { outcome = `input refused: ${error.message}`; }
    attempts.push({ name, disabled: await button.isDisabled(), outcome });
  }
  await page.waitForTimeout(500);
  const after = await restrictedArtifacts(page, run);
  assert.deepEqual(after, before, `${label}: a disabled chemical-source control created an M8/M9/M10 artifact`);
  await testRestrictions(page, label);
  return { label, names, reason, attempts, restrictedArtifactsBefore: before.length,
    restrictedArtifactsAfter: after.length };
}
async function capabilityState(page, expected, workspaceOpen = true) {
  const capability = (await readApi(page, "/capabilities")).methods?.chemical_interactions;
  assert.ok(capability, "No chemical_interactions capability in /capabilities");
  if (expected === "ready") {
    assert.equal(capability.available, true, `Expected ready chemical worker: ${JSON.stringify(capability)}`);
    assert.equal(capability.reason_code, null);
  } else {
    assert.equal(capability.available, false, "A missing/wrong worker was advertised as available");
    assert.equal(capability.reason_code, expected);
    assert.ok(capability.reason && !/\d+\s*(rows?|interactions?|Å)/i.test(capability.reason));
    assert.equal(capability.versions, undefined, "Unavailable capability advertised pinned versions");
  }
  let visible = null;
  if (workspaceOpen) {
    const text = expected === "ready" ? `지원: ${capability.protocol}` : `사용 불가: ${capability.reason}`;
    await page.getByText(text, { exact: true }).waitFor({ timeout: 30000 });
    visible = text;
  }
  return { expected, capability, visible };
}
async function waitJob(page, stage, id) {
  const label = stage === "prepare" ? "화학 구조 준비" : "ProLIF 계산";
  await page.waitForFunction(({ stage, id }) => {
    const node = document.querySelector(".mw-chemical-stack");
    const proof = window.__protviewQaChemical?.();
    return !!node && (stage === "prepare" ? proof?.prepareJobId : proof?.detectJobId) === id &&
      [...document.querySelectorAll(".mw-chemical-job")].some(job =>
        job.textContent?.includes(id) && job.textContent?.includes("done"));
  }, { stage, id }, { timeout: 180000 });
  return page.locator(".mw-chemical-job").filter({ hasText: id }).innerText();
}
async function startWithApproval(page, stage, injectNonApproval = false) {
  const isPrepare = stage === "prepare";
  const start = isPrepare ? "준비 작업 시작" : "상호작용 작업 시작";
  const initial = await chemical(page);
  const id = isPrepare ? initial.prepareJobId : initial.detectJobId;
  assert.ok(id, `${stage} job ID absent after visible submission`);
  let conflictProof = null;
  if (injectNonApproval) {
    const run = new URL(page.url()).searchParams.get("run");
    const pattern = `**/api/runs/${run}/jobs/${id}/start`;
    let hits = 0;
    await page.route(pattern, async route => {
      hits++;
      await route.fulfill({ status: 409, contentType: "application/json",
        body: JSON.stringify({ ok: false, error: "resource_exceeded",
          message: "Labeled renderer fixture: competing job conflict, no approval field" }) });
    });
    await click(page, start);
    const visibleErrors = page.getByRole("alert").filter({ hasText: "Labeled renderer fixture" });
    await visibleErrors.first().waitFor({ timeout: 15000 });
    assert.equal(hits, 1, "Non-approval 409 fixture did not intercept start");
    assert.equal(await page.getByRole("button", { name: "이 실제 작업 승인" }).count(), 0,
      "An ordinary HTTP 409 incorrectly opened expensive approval");
    conflictProof = { routeHits: hits, visibleMessages: await visibleErrors.allInnerTexts(),
      fixture: "renderer-injected 409 with no approval field; backend job remains queued" };
    await page.unroute(pattern);
  }
  await click(page, start);
  const approval = page.getByRole("button", { name: "이 실제 작업 승인" });
  const deadline = Date.now() + 30000;
  let needsApproval = false;
  while (Date.now() < deadline) {
    if (await approval.isVisible().catch(() => false)) { needsApproval = true; break; }
    const jobText = await page.locator(".mw-chemical-job").filter({ hasText: id }).innerText();
    if (/\b(running|done|failed|interrupted)\b/.test(jobText)) break;
    await page.waitForTimeout(100);
  }
  if (needsApproval) {
    await approval.click();
    await page.getByText(/계산 승인을 기록했습니다/).first().waitFor({ timeout: 30000 });
    await page.getByRole("button", { name: start }).waitFor({ state: "visible" });
    await click(page, start);
  }
  return { id, text: await waitJob(page, stage, id), conflictProof, approvalSeen: needsApproval };
}
async function focusFirstRow(page, app, artifacts) {
  const region = page.getByRole("region", { name: "화학 상호작용 행" });
  const first = region.locator("button.mw-chemical-row").first();
  await first.waitFor({ state: "visible", timeout: 30000 });
  const before = await chemical(page);
  assert.equal(before.catalogReady, true, "Chemical native catalog not validated");
  await first.click();
  const rowId = (await chemical(page)).selectedRowId;
  assert.ok(rowId);
  const after = await waitChemical(page, state => state.native?.chemicalFocus?.rowId === state.selectedRowId &&
    state.native?.chemicalAnnotation?.rowId === state.selectedRowId &&
    state.native?.chemicalAnnotation?.nativeShapeRefs?.length >= 1, 30000);
  assert.equal(after.native.sessionId, null, "Chemical view must not synthesize an M8 session");
  assert.equal(after.native.sourceHandle, after.sourceHandle);
  assert.ok(after.native.chemicalFocus.atoms.every(atom => atom.ref.structure_handle === after.sourceHandle));
  const run = new URL(page.url()).searchParams.get("run");
  const selectedPage = await readApi(page, `/runs/${run}/chemical/results/rows?handle=${encodeURIComponent(after.resultHandle)}&offset=0&limit=50`);
  const exact = selectedPage.rows.find(row => row.row_id === rowId);
  assert.ok(exact, `Selected native row ${rowId} absent from immutable result page`);
  const expected = Object.values(exact.roles).map(atomIdentity).sort();
  assert.deepEqual(after.native.chemicalFocus.atoms.map(item => atomIdentity(item.ref)).sort(), expected,
    "Actual native focus atom set differs from all exact row roles");
  const catalog = await readApi(page, `/runs/${run}/chemical/structures/atoms?handle=${encodeURIComponent(after.sourceHandle)}&offset=0&limit=100`);
  const sourceIndices = new Map(catalog.rows.map(item => [atomIdentity(item.ref), item.viewer_source_index]));
  if (catalog.total > catalog.rows.length) {
    for (let offset = catalog.rows.length; offset < catalog.total; offset += 100) {
      const next = await readApi(page, `/runs/${run}/chemical/structures/atoms?handle=${encodeURIComponent(after.sourceHandle)}&offset=${offset}&limit=100`);
      for (const item of next.rows) sourceIndices.set(atomIdentity(item.ref), item.viewer_source_index);
    }
  }
  assert.deepEqual(after.native.chemicalFocus.selectedNativeSourceIndices,
    expected.map(identity => sourceIndices.get(identity)).sort((a, b) => a - b),
    "Mol* selection manager did not contain exactly the row role sites");
  assert.ok(after.native.chemicalFocus.settledCamera && !after.native.cameraTransitioning,
    "Row focus camera was not observed settled");
  for (const field of ["position", "target", "up"]) assert.ok(
    separation(after.native.chemicalFocus.settledCamera[field], after.native.nativeCamera[field]) < 1e-3,
    `Native camera ${field} changed before focus readback`);
  assert.equal(after.native.chemicalAnnotation.sourceHandle, exact.roles[exact.distance_roles[0]].structure_handle);
  const [a, b] = exact.distance_roles;
  const independentDistance = separation(exact.engine_role_coordinates_A[a], exact.engine_role_coordinates_A[b]);
  assert.ok(Math.abs(independentDistance - exact.distance_A) <= 1e-5,
    "Stored distance did not match independent engine-coordinate geometry");
  assert.ok(Math.abs(after.native.chemicalAnnotation.distanceNative_A - exact.distance_A) <= 0.005,
    "Native displayed distance differs from immutable result");
  let independentAngle = null;
  if (exact.DHA_angle_deg != null) {
    independentAngle = angleAtHydrogen(exact.engine_role_coordinates_A.donor,
      exact.engine_role_coordinates_A.hydrogen, exact.engine_role_coordinates_A.acceptor);
    assert.ok(Math.abs(independentAngle - exact.DHA_angle_deg) <= 1e-5,
      "Stored angle did not match independent engine-coordinate geometry");
    assert.ok(Math.abs(after.native.chemicalAnnotation.angleNative_deg - exact.DHA_angle_deg) <= 0.1);
  } else assert.equal(after.native.chemicalAnnotation.angleNative_deg, null);
  for (const picked of after.native.chemicalFocus.atoms) {
    const role = Object.entries(exact.roles).find(([, ref]) => atomIdentity(ref) === atomIdentity(picked.ref));
    assert.ok(role, `Native focus atom ${atomIdentity(picked.ref)} absent from stored row roles`);
    assert.ok(separation(picked.nativeWorldCoordinate_A, exact.role_coordinates_A[role[0]]) <= 0.005,
      `Native focus coordinate differs from source-view coordinate for ${role[0]}`);
  }
  const frame = await capture(app, page, artifacts, `row-${rowId}`);
  await imageNonblank(frame.screenshot);
  return { rowId, before, after, exact, independentDistance, independentAngle, frame };
}
async function downloadReport(app, page, run, report, artifacts) {
  const markdown = await downloadByClick(app, page.getByRole("link", { name: "Markdown 다운로드" }));
  const json = await downloadByClick(app, page.getByRole("link", { name: "정확한 JSON 다운로드" }));
  const exactMd = await getBytes(page, `/runs/${run}/reports/download?handle=${encodeURIComponent(report)}&format=markdown`);
  const exactJson = await getBytes(page, `/runs/${run}/reports/download?handle=${encodeURIComponent(report)}&format=json`);
  assert.equal(markdown.sha256, sha(exactMd)); assert.equal(json.sha256, sha(exactJson));
  const attribution = JSON.parse(exactJson.toString("utf8"));
  const selected = await readApi(page, `/runs/${run}/reports/selected?handle=${encodeURIComponent(report)}`);
  assert.equal(selected.handle, report);
  assert.equal(selected.manifest.result_handle, (await chemical(page)).resultHandle);
  fs.writeFileSync(path.join(artifacts, "report-download-proof.json"), JSON.stringify({ markdown, json,
    apiMarkdownSha256: sha(exactMd), apiJsonSha256: sha(exactJson), attribution,
    selectedManifest: selected.manifest }, null, 2));
  return { markdown, json, attribution, selectedManifest: selected.manifest };
}
async function categoryControls(page, app, artifacts) {
  const source = await chemical(page);
  const run = new URL(page.url()).searchParams.get("run");
  const record = [];
  for (const category of ["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"]) {
    const response = page.waitForResponse(value => value.url().includes("/chemical/results/rows?") &&
      new URL(value.url()).searchParams.get("category") === category && value.status() === 200);
    await selectByLabel(page, "범주", category);
    await response;
    const apiPage = await readApi(page, `/runs/${run}/chemical/results/rows?handle=${encodeURIComponent(source.resultHandle)}&offset=0&limit=50&category=${category}`);
    await page.waitForFunction(expected => document.querySelectorAll(".mw-chemical-row").length === expected,
      apiPage.rows.length, { timeout: 15000 });
    const visible = await page.locator(".mw-chemical-row").allInnerTexts();
    for (const row of apiPage.rows) assert.ok(visible.some(text => text.includes(row.row_id)),
      `Category ${category} omitted immutable row ${row.row_id}`);
    let focus = null;
    if ((category === "HBDonor" || category === "HBAcceptor") && apiPage.rows.length)
      focus = await focusFirstRow(page, app, artifacts);
    record.push({ category, total: apiPage.total, firstPageRowIds: apiPage.rows.map(row => row.row_id), focus });
  }
  await selectByLabel(page, "범주", "");
  return record;
}
async function paginationControls(page) {
  const run = new URL(page.url()).searchParams.get("run");
  const result = (await chemical(page)).resultHandle;
  await selectByLabel(page, "범주", "");
  await selectByLabel(page, "페이지 크기", "10");
  const first = await readApi(page, `/runs/${run}/chemical/results/rows?handle=${encodeURIComponent(result)}&offset=0&limit=10`);
  await page.waitForFunction(ids => [...document.querySelectorAll(".mw-chemical-row")]
    .map(node => node.textContent ?? "").every((text, i) => text.includes(ids[i])) &&
    document.querySelectorAll(".mw-chemical-row").length === ids.length,
  first.rows.map(row => row.row_id), { timeout: 15000 });
  const record = [{ offset: 0, ids: first.rows.map(row => row.row_id), total: first.total }];
  if (first.total > 10) {
    await click(page, "다음 페이지");
    const second = await readApi(page, `/runs/${run}/chemical/results/rows?handle=${encodeURIComponent(result)}&offset=10&limit=10`);
    await page.waitForFunction(ids => [...document.querySelectorAll(".mw-chemical-row")]
      .map(node => node.textContent ?? "").every((text, i) => text.includes(ids[i])) &&
      document.querySelectorAll(".mw-chemical-row").length === ids.length,
    second.rows.map(row => row.row_id), { timeout: 15000 });
    record.push({ offset: 10, ids: second.rows.map(row => row.row_id), total: second.total });
    await click(page, "이전 페이지");
    let releaseOld, finishOld;
    const gate = new Promise(resolve => { releaseOld = resolve; });
    const finished = new Promise(resolve => { finishOld = resolve; });
    let oldPageHits = 0;
    const pattern = `**/api/runs/${run}/chemical/results/rows?*`;
    await page.route(pattern, async route => {
      const query = new URL(route.request().url()).searchParams;
      if (query.get("offset") !== "10" || query.has("category")) { await route.continue(); return; }
      oldPageHits++;
      const response = await route.fetch(); const body = await response.body();
      await gate;
      try { await route.fulfill({ response, body }); } catch { /* stale page may abort */ }
      finishOld();
    });
    await click(page, "다음 페이지");
    const deadline = Date.now() + 30000;
    while (oldPageHits === 0 && Date.now() < deadline) await page.waitForTimeout(50);
    assert.equal(oldPageHits, 1);
    await selectByLabel(page, "범주", "HBDonor");
    const filtered = await readApi(page, `/runs/${run}/chemical/results/rows?handle=${encodeURIComponent(result)}&offset=0&limit=10&category=HBDonor`);
    await page.waitForFunction(ids => [...document.querySelectorAll(".mw-chemical-row")]
      .map(node => node.textContent ?? "").every((text, i) => text.includes(ids[i])) &&
      document.querySelectorAll(".mw-chemical-row").length === ids.length,
    filtered.rows.map(row => row.row_id), { timeout: 15000 });
    releaseOld(); await finished; await page.unroute(pattern);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const visible = await page.locator(".mw-chemical-row").allInnerTexts();
    assert.equal(visible.length, filtered.rows.length);
    for (let i = 0; i < visible.length; i++) assert.ok(visible[i].includes(filtered.rows[i].row_id));
    record.push({ stalePageHeld: true, category: "HBDonor", ids: filtered.rows.map(row => row.row_id) });
  }
  await selectByLabel(page, "범주", "");
  await selectByLabel(page, "페이지 크기", "50");
  return record;
}
function assertRefocusReadback(state, rowProof, label) {
  const focus = state.native.chemicalFocus;
  assert.equal(focus.rowId, rowProof.rowId, `${label}: wrong immutable row`);
  assert.deepEqual(focus.atoms.map(item => atomIdentity(item.ref)).sort(),
    Object.values(rowProof.exact.roles).map(atomIdentity).sort(),
    `${label}: actual native focus sites differ from all immutable row roles`);
  assert.deepEqual(focus.selectedNativeSourceIndices,
    rowProof.after.native.chemicalFocus.selectedNativeSourceIndices,
    `${label}: Mol* selection manager site indices differ from immutable row focus`);
  for (const field of ["position", "target", "up"]) assert.ok(
    separation(focus.settledCamera[field], state.native.nativeCamera[field]) < 1e-3,
    `${label}: native camera ${field} changed after focus readback`);
  for (const field of ["fov", "radius", "radiusMax", "fog", "minNear", "minFar"])
    assert.ok(Math.abs(focus.settledCamera[field] - state.native.nativeCamera[field]) < 1e-3,
      `${label}: native camera ${field} changed after focus readback`);
  for (const field of ["mode", "clipFar"])
    assert.equal(focus.settledCamera[field], state.native.nativeCamera[field],
      `${label}: native camera ${field} changed after focus readback`);
}
async function nativeControls(page, app, artifacts, rowProof) {
  const before = await chemical(page);
  const canvas = page.locator("canvas").first();
  const box = await canvas.boundingBox();
  assert.ok(box && box.width > 400 && box.height > 300);
  const x = box.x + box.width * 0.48, y = box.y + box.height * 0.48;
  await page.mouse.move(x, y); await page.mouse.down();
  await page.mouse.move(x + 80, y + 45, { steps: 12 }); await page.mouse.up();
  await page.mouse.wheel(0, 240);
  const moved = await waitChemical(page, state => state.native?.camera &&
    separation(state.native.camera.position, before.native.camera.position) > 0.05, 15000);
  await selectByLabel(page, "표현", "surface");
  await waitChemical(page, state => state.native?.representation === "surface", 30000);
  await selectByLabel(page, "표현", "ball-and-stick");
  const immediateBefore = await chemical(page);
  const refocusButton = page.getByRole("button", { name: "정확한 원자 다시 초점" });
  assert.equal(await refocusButton.isEnabled(), true,
    "Chemical row refocus was not enabled immediately after a real representation change");
  await refocusButton.click();
  const immediateFocused = await waitChemical(page, state => state.native?.chemicalFocus?.rowId === state.selectedRowId &&
    state.native.chemicalFocus.settledCamera && !state.native.cameraTransitioning &&
    state.native.representation === "ball-and-stick" &&
    separation(state.native.nativeCamera.position, moved.native.nativeCamera.position) > 0.05 &&
    separation(state.native.chemicalFocus.settledCamera.position, state.native.nativeCamera.position) < 1e-3,
  30000);
  assertRefocusReadback(immediateFocused, rowProof, "immediate enabled refocus");
  assert.equal(await page.getByRole("alert").filter({ hasText: "화학 원자 초점 카메라" }).count(), 0,
    "Immediate enabled refocus displayed a native camera timing error");
  const immediateFrame = await capture(app, page, artifacts, "immediate-enabled-refocus");
  await imageNonblank(immediateFrame.screenshot);

  await page.mouse.move(x, y); await page.mouse.down();
  await page.mouse.move(x - 65, y + 35, { steps: 10 }); await page.mouse.up();
  await page.mouse.wheel(0, -180);
  await waitChemical(page, state => state.native?.camera &&
    separation(state.native.camera.position, immediateFocused.native.camera.position) > 0.05, 15000);
  await waitChemical(page, state => state.native?.representation === "ball-and-stick" &&
    !state.native.nativeBusy && !state.native.cameraTransitioning &&
    state.native.m10QueuePending === 0, 30000);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const beforeRefocus = await chemical(page);
  assert.equal(beforeRefocus.native.cameraTransitioning, false,
    "Real manual camera was still transitioning before refocus click");
  assert.equal(beforeRefocus.native.m10QueuePending, 0);
  await click(page, "정확한 원자 다시 초점");
  const focused = await waitChemical(page, state => state.native?.chemicalFocus?.rowId === state.selectedRowId &&
    state.native.chemicalFocus.settledCamera && !state.native.cameraTransitioning &&
    state.native.representation === "ball-and-stick" &&
    separation(state.native.nativeCamera.position, beforeRefocus.native.nativeCamera.position) > 0.05 &&
    separation(state.native.chemicalFocus.settledCamera.position, state.native.nativeCamera.position) < 1e-3,
  30000);
  assertRefocusReadback(focused, rowProof, "idle-gated refocus");
  assert.equal(await page.getByRole("alert").filter({ hasText: "화학 원자 초점 카메라" }).count(), 0);
  const frame = await capture(app, page, artifacts, "manual-orbit-zoom-refocus");
  await imageNonblank(frame.screenshot);
  return { before, moved, immediateBefore, immediateFocused, immediateFrame,
    beforeRefocus, focused, frame };
}
async function runCreate(session, input, evidence) {
  const { page, app, artifacts } = session;
  const run = await openWorkspace(page, input); evidence.run = run;
  const cap = await readApi(page, "/capabilities");
  assert.equal(cap.methods?.chemical_interactions?.available, true,
    `Pinned local worker unavailable: ${JSON.stringify(cap.methods?.chemical_interactions)}`);
  evidence.capability = cap.methods.chemical_interactions;
  evidence.files = { receptor: await chooseFile(page, "준비된 수용체 PDB/mmCIF", input.receptor),
    sdf: await chooseFile(page, "명시적 H가 있는 3D 리간드 V2000 SDF", input.sdf) };
  const modelSelect = nestedSelect(page, "수용체 model");
  assert.equal(await modelSelect.count(), 1);
  await modelSelect.locator('option[value="1"]').waitFor({ state: "attached", timeout: 30000 });
  const models = await modelSelect.locator("option").evaluateAll(options => options.map(option => Number(option.value)));
  assert.ok(models.includes(1));
  await modelSelect.selectOption("1");
  const recordSelect = nestedSelect(page, "SDF 기록");
  assert.equal(await recordSelect.count(), 1);
  await page.waitForFunction(() => document.querySelectorAll('label select').length > 0 &&
    [...document.querySelectorAll('label')].some(label => label.textContent?.includes('SDF 기록') &&
      label.querySelectorAll('option').length > 1), null, { timeout: 30000 });
  const records = await recordSelect.locator("option").evaluateAll(options =>
    options.map(option => ({ index: Number(option.value), label: option.textContent })));
  assert.ok(records.length > 1, "Public multi-record SDF did not expose record selection");
  await recordSelect.selectOption(String(records[1].index));
  assert.equal(Number(await recordSelect.inputValue()), records[1].index);
  await recordSelect.selectOption("0");
  await page.getByLabel("리간드 chain auth", { exact: true }).fill("Z");
  await page.getByLabel("seq auth", { exact: true }).fill("901");
  await page.getByLabel("resname", { exact: true }).fill("LQA");
  evidence.formInput = { models, records, selectedRecord: 0,
    ligandInstance: { model_number: 1, chain_auth: "Z", chain_label: null,
      seq_auth: 901, seq_label: null, icode: "", resname: "LQA" },
    label: "User-selected local derived ligand identity; not experimental structure identity" };
  if (input.connectivity === "sidecar") {
    await selectByLabel(page, "수용체 결합 제공", "sidecar");
    evidence.files.sidecar = await chooseFile(page, "완전한 receptor_bonds@1 JSON", input.sidecar);
  }
  const firstPreviewPromise = page.waitForResponse(response => response.request().method() === "POST" &&
    response.url().includes(`/api/runs/${run}/chemical/preview`));
  await click(page, "준비 조건 미리보기");
  const firstPreviewResponse = await firstPreviewPromise;
  assert.equal(firstPreviewResponse.status(), 200);
  const firstPreview = await firstPreviewResponse.json();
  evidence.firstPreview = { ready: firstPreview.ready, blockers: firstPreview.blockers,
    terminalExtensions: firstPreview.terminal_extensions };
  await page.getByText(/준비 조건 미충족|계산 준비 가능/).waitFor({ timeout: 30000 });
  evidence.incompletePreview = await page.getByText(/준비 조건 미충족|계산 준비 가능/).first().innerText();
  for (const label of ["공급된 수용체 결합 그래프가 완전함", "공급된 수소가 완전함",
    "공급된 protonation/tautomer 그대로 사용", "수용체 bond order/charge 추론 동의"])
    await page.getByLabel(label, { exact: true }).check();
  const terminalChecks = page.locator("label").filter({ hasText: "말단 확장 승인:" }).locator('input[type="checkbox"]');
  evidence.terminalExtensionCount = await terminalChecks.count();
  if (firstPreview.terminal_extensions.length) {
    const first = firstPreview.terminal_extensions[0];
    const residueKey = JSON.stringify([first.residue.model_number, first.residue.chain_auth,
      first.residue.chain_label, first.residue.seq_auth, first.residue.seq_label,
      first.residue.icode, first.residue.resname]);
    const custom = nestedSelect(page, "사용자 선언 말단 잔기");
    await page.waitForFunction(key => [...document.querySelectorAll('select')]
      .some(select => [...select.options].some(option => option.value === key)), residueKey,
    { timeout: 30000 });
    await custom.selectOption(residueKey);
    const atomNames = page.getByLabel("실제 추가 원자 이름 (쉼표 구분)", { exact: true });
    await atomNames.fill(first.atom_names[0]);
    await click(page, "정확한 말단 원자 선언");
    assert.equal(await page.getByRole("button", { name: `말단 선언 제거 ${residueKey}` }).count(), 1);
    await atomNames.fill(first.atom_names.join(", "));
    await click(page, "정확한 말단 원자 선언");
    await page.getByRole("button", { name: `말단 선언 제거 ${residueKey}` }).click();
    assert.equal(await page.getByRole("button", { name: `말단 선언 제거 ${residueKey}` }).count(), 0);
    evidence.customTerminalControl = { residue: first.residue, added: [first.atom_names[0]],
      edited: first.atom_names, removed: true, source: "actual staging-atom inventory" };
  }
  for (let i = 0; i < evidence.terminalExtensionCount; i++) await terminalChecks.nth(i).check();
  await page.getByLabel("준비 설명 (검증되지 않은 로컬 주석)").fill("Prepared local public tutorial input; supplied protonation state unverified");
  await page.getByLabel("pH 메모 (실험 검증 아님)").fill("7.4");
  let prepareRequest = null;
  const recordPrepare = request => {
    if (request.method() !== "POST" || !request.url().includes(`/api/runs/${run}/jobs`)) return;
    const body = request.postDataJSON();
    if (body?.protocol_id === "prolif_prepare_v1") prepareRequest = body;
  };
  page.on("request", recordPrepare);
  await click(page, "준비 조건 미리보기");
  await page.getByText("계산 준비 가능", { exact: false }).waitFor({ timeout: 30000 });
  assert.equal(await page.getByRole("button", { name: "화학 구조 준비 작업 저장" }).isEnabled(), true);
  evidence.readyPreview = await page.getByText(/계산 준비 가능/).first().innerText();
  await click(page, "화학 구조 준비 작업 저장");
  await page.getByRole("button", { name: "준비 작업 시작" }).waitFor({ timeout: 30000 });
  await submittedJob(page, "prepare");
  page.off("request", recordPrepare);
  assert.deepEqual(prepareRequest?.args?.ligand_instance, evidence.formInput.ligandInstance);
  assert.equal(prepareRequest.args.sdf_record_index, 0);
  assert.equal(prepareRequest.args.acknowledgement.ph_annotation, 7.4);
  assert.equal(prepareRequest.args.terminal_extensions.length, evidence.terminalExtensionCount);
  evidence.prepareRequest = prepareRequest;
  evidence.prepare = await startWithApproval(page, "prepare", true);
  const prepared = await waitChemical(page, state => state.sourceHandle && state.catalogReady &&
    state.native?.sourceHandle === state.sourceHandle, 60000);
  assert.equal(prepared.native.generation, null);
  evidence.prepared = prepared;
  const preparedView = await readApi(page, `/runs/${run}/chemical/structures/view?handle=${encodeURIComponent(prepared.sourceHandle)}`);
  const savedPreparation = await readApi(page,
    `/runs/${run}/chemical/preparation-manifests?source_handle=${encodeURIComponent(prepared.sourceHandle)}`);
  assert.equal(savedPreparation.meta.handle, preparedView.manifest_handle);
  assert.equal(savedPreparation.meta.kind, "chemical_preparation_manifest");
  assert.equal(savedPreparation.manifest.schema, "chemical_preparation_manifest@1");
  assert.deepEqual(savedPreparation.manifest.request, prepareRequest.args,
    "Persisted source-linked preparation choices differ from the actual submitted UI request");
  assert.equal(savedPreparation.manifest.request.acknowledgement.ph_annotation, 7.4);
  assert.deepEqual(savedPreparation.manifest.request.ligand_instance, evidence.formInput.ligandInstance);
  evidence.prepareManifestLink = { handle: preparedView.manifest_handle,
    sha256: preparedView.manifest_sha256, savedPreparation };
  if (input.mode === "prepare-only") {
    const jobs = await readApi(page, `/runs/${run}/jobs`);
    assert.ok(jobs.some(job => job.protocol_id === "prolif_prepare_v1" &&
      job.status === "done" && (job.artifacts?.chemical_graph ?? job.output_handles[2]) === prepared.graphHandle));
    assert.equal(jobs.some(job => job.protocol_id === "prolif_detect_v1"), false,
      "Prepare-only fixture must not submit a detection before its cancel-control case");
    evidence.prepareOnly = { graphHandle: prepared.graphHandle, sourceHandle: prepared.sourceHandle,
      noDetectionSubmitted: true, actualNativePreparation: true };
    return evidence;
  }
  await rail(page, "models");
  await page.getByText("저장된 실제 준비 선택").click();
  await page.getByText(/pH 주석 7\.4/).waitFor({ timeout: 15000 });
  await click(page, "상호작용 계산 작업 저장");
  await submittedJob(page, "detect");
  evidence.detect = await startWithApproval(page, "detect");
  const detected = await waitChemical(page, state => state.resultHandle && state.catalogReady &&
    state.native?.sourceHandle === state.sourceHandle, 60000);
  evidence.resultHandle = detected.resultHandle;
  evidence.detected = detected;
  if (input.mode === "create") assert.ok(detected.resultTotal > 0,
    "The public prepared example produced no native interaction rows");
  if (input.mode === "empty") {
    assert.equal(detected.resultTotal, 0, "Translated synthetic derivative was expected to give a valid empty result");
    evidence.scientificNull = await scientificNullDistinct(page, app, artifacts, run, detected, evidence.detect.id);
  }
  evidence.restrictionsOn = await testRestrictions(page, "annotation on");
  if (detected.resultTotal > 0) {
    evidence.row = await focusFirstRow(page, app, artifacts);
    evidence.nativeControls = await nativeControls(page, app, artifacts, evidence.row);
    evidence.pagination = await paginationControls(page);
    evidence.categories = await categoryControls(page, app, artifacts);
    await page.locator(".mw-chemical-row").first().click();
    await waitChemical(page, state => state.native?.chemicalAnnotation?.rowId === state.selectedRowId);
    await click(page, "기하 주석 숨기기");
    await waitChemical(page, state => state.native?.chemicalAnnotation === null);
    evidence.restrictionsOff = await testRestrictions(page, "annotation off");
    await click(page, "기하 주석 표시");
    await waitChemical(page, state => state.native?.chemicalAnnotation?.rowId === state.selectedRowId);
  } else {
    assert.equal(detected.resultTotal, 0);
    await page.getByText("정상적인 빈 결과 (scientific_null)").first().waitFor();
  }
  await click(page, "화학 보고서 저장");
  const reportSelect = nestedSelect(page, "저장된 보고서");
  await page.waitForFunction(() => !!document.querySelector('select') &&
    [...document.querySelectorAll('select')].some(select => select.value.includes("method_report_manifest")),
  null, { timeout: 30000 });
  evidence.reportHandle = await reportSelect.inputValue();
  evidence.report = await downloadReport(app, page, run, evidence.reportHandle, artifacts);
  let releaseReport, finishReport;
  const reportGate = new Promise(resolve => { releaseReport = resolve; });
  const reportFinished = new Promise(resolve => { finishReport = resolve; });
  let heldReportPosts = 0;
  const reportPattern = `**/api/runs/${run}/method_reports`;
  await page.route(reportPattern, async route => {
    if (route.request().method() !== "POST") { await route.continue(); return; }
    heldReportPosts++;
    const response = await route.fetch(); const body = await response.body();
    evidence.createdButSupersededReport = { status: response.status(), sha256: sha(body),
      handle: JSON.parse(body.toString("utf8")).handle };
    await reportGate;
    try { await route.fulfill({ response, body }); } catch { /* visible report choice revoked old read */ }
    finishReport();
  });
  await click(page, "화학 보고서 저장");
  const reportDeadline = Date.now() + 30000;
  while (heldReportPosts === 0 && Date.now() < reportDeadline) await page.waitForTimeout(50);
  assert.equal(heldReportPosts, 1);
  await reportSelect.selectOption("");
  await reportSelect.selectOption(evidence.reportHandle);
  await page.getByLabel("저장된 화학 보고서").waitFor({ timeout: 30000 });
  const reportBeforeRelease = await page.getByLabel("저장된 화학 보고서").innerText();
  releaseReport(); await reportFinished; await page.unroute(reportPattern);
  assert.equal(await reportSelect.inputValue(), evidence.reportHandle,
    "Superseded report creation changed the selected historical report");
  assert.equal(await page.getByLabel("저장된 화학 보고서").innerText(), reportBeforeRelease);
  assert.equal(await page.getByRole("button", { name: "화학 보고서 저장" }).isEnabled(), true,
    "Superseded report creation left its busy control stuck");
  evidence.reportSelectionRace = { heldReportPosts, selectedHandle: evidence.reportHandle,
    markdownSha256: sha(Buffer.from(reportBeforeRelease, "utf8")) };
  return evidence;
}
/** H09: a valid empty native result is scientific_null, shown as a result and never as an error. */
async function scientificNullDistinct(page, app, artifacts, run, detected, detectJobId) {
  const saved = await readApi(page, `/runs/${run}/chemical/results?handle=${encodeURIComponent(detected.resultHandle)}`);
  assert.equal(saved.result.null_result, true, "Zero-row result is not recorded as scientific_null");
  assert.equal(saved.result.total, 0);
  const rows = await readApi(page, `/runs/${run}/chemical/results/rows?handle=${encodeURIComponent(detected.resultHandle)}&offset=0&limit=50`);
  assert.equal(rows.total, 0); assert.deepEqual(rows.rows, []);
  const job = await readApi(page, `/runs/${run}/jobs/${detectJobId}`);
  assert.equal(job.status, "done", "A valid empty result must come from a completed detection, not a failure");
  assert.equal(job.failure ?? null, null);
  const inspector = page.locator("p").filter({ hasText: /^정상적인 빈 결과 \(scientific_null\)$/ });
  assert.ok(await inspector.count() >= 1, "scientific_null result label is not visible");
  assert.equal(await page.getByText(/^실제 계산 행 \d+개$/).count(), 0, "Empty result displayed as a row count");
  assert.equal(await page.locator(".mw-chemical-row").count(), 0);
  await page.getByText("0 / 0", { exact: true }).waitFor({ timeout: 15000 });
  const alerts = await page.getByRole("alert").allInnerTexts();
  assert.deepEqual(alerts.filter(text => /실패|failed|error/i.test(text)), [],
    `Valid empty result displayed an error alert: ${JSON.stringify(alerts)}`);
  const frame = await capture(app, page, artifacts, "scientific-null");
  await imageNonblank(frame.screenshot);
  return { nullResult: saved.result.null_result, total: saved.result.total, limitations: saved.result.limitations,
    detectJob: { job_id: job.job_id, status: job.status }, visibleLabel: await inspector.first().innerText(),
    alerts, frame };
}
async function uploadExpectingRejection(page, label, file, text) {
  const holder = page.locator(".mw-chemical-file").filter({ hasText: label });
  const chooser = page.waitForEvent("filechooser", { timeout: 15000 });
  await holder.locator('input[type="file"]').click();
  await (await chooser).setFiles(file);
  const alert = page.getByRole("alert").filter({ hasText: "입력 업로드 실패" });
  await alert.first().waitFor({ timeout: 30000 });
  const shown = await alert.first().innerText();
  assert.ok(shown.includes(text), `Upload rejection does not name the prerequisite: ${shown}`);
  assert.equal(await holder.getByText(/obj:\/\/run_/).count(), 0, "Rejected file was bound as an import");
  return { file: path.basename(file), sha256: sha(fs.readFileSync(file)), shown,
    provenance: ledger.provenanceLabel(path.basename(file)) };
}
function blockerAtomLine(ref) {
  const residue = ref.residue;
  return `${residue.resname} ${residue.chain_auth}/${residue.seq_auth}${residue.icode || ""} · ${ref.atom_name}` +
    `${ref.altloc ? ` alt ${ref.altloc}` : ""} · model ${residue.model_number} · site ${ref.site_index}` +
    ` · model ${residue.model_number} · auth ${residue.chain_auth}/${residue.seq_auth}${residue.icode}` +
    ` · label ${residue.chain_label ?? "?"}/${residue.seq_label ?? "?"} · site ${ref.site_index}`;
}
const oracleIdentity = ref => JSON.stringify([ref.residue.model_number, ref.residue.chain_auth, ref.residue.chain_label,
  ref.residue.seq_auth, ref.residue.seq_label, ref.residue.icode, ref.residue.resname, ref.atom_name, ref.altloc,
  ref.element.toUpperCase()]);
/** H06: preview blockers must show the exact offending AtomRefs named by the generator's independent oracle. */
async function expectVisibleBlockers(page, previewBody, expected) {
  assert.equal(previewBody.ready, false, "Invalid input preview reported ready");
  const shown = [];
  for (const code of expected.codes) {
    const blockers = previewBody.blockers.filter(item => item.code === code);
    assert.equal(blockers.length, 1, `Expected one ${code} blocker: ${JSON.stringify(previewBody.blockers.map(b => b.code))}`);
    const blocker = blockers[0];
    const node = page.getByRole("alert").filter({ hasText: `${code}: ${blocker.message}` });
    assert.equal(await node.count(), 1, `${code} blocker is not visible exactly once`);
    let lines = [];
    if (blocker.atoms.length) {
      await node.getByText(`문제가 있는 정확한 원자 ${blocker.atoms.length}개`, { exact: true }).click();
      lines = (await node.locator("p.mw-mono").allInnerTexts()).map(line => line.trim());
      assert.equal(lines.length, blocker.atoms.length);
      for (const ref of blocker.atoms)
        assert.equal(lines.filter(line => line === blockerAtomLine(ref)).length, 1,
          `${code}: exact atom ${blockerAtomLine(ref)} is not shown once`);
    }
    if (expected.atoms[code]) assert.deepEqual(blocker.atoms.map(oracleIdentity).sort(),
      expected.atoms[code].map(oracleIdentity).sort(), `${code}: product offending atoms differ from generator oracle`);
    shown.push({ code, message: blocker.message, atoms: blocker.atoms, visibleLines: lines });
  }
  return shown;
}
async function computeControlsDisabled(page, label) {
  for (const name of ["화학 구조 준비 작업 저장", "상호작용 계산 작업 저장"])
    assert.equal(await page.getByRole("button", { name, exact: true }).isDisabled(), true,
      `${label}: ${name} enabled before a valid accepted graph`);
  assert.equal(await page.locator(".mw-chemical-job").count(), 0, `${label}: a chemical job was created`);
}
async function runInvalidInputs(session, input, evidence) {
  const { page, app, artifacts } = session;
  const manifest = JSON.parse(fs.readFileSync(path.join(input.variants, "m11-invalid-cases.json"), "utf8"));
  const fixtureDir = path.resolve(__dirname, "../../../backend/tests/fixtures/chemical");
  const file = name => fs.existsSync(path.join(fixtureDir, name)) ? path.join(fixtureDir, name) : path.join(input.variants, name);
  const posts = [];
  page.on("request", request => { if (request.method() === "POST") posts.push(new URL(request.url()).pathname); });
  let run = null;
  evidence.cases = [];
  evidence.manifestLabel = manifest.label;
  for (const item of manifest.cases.filter(entry => entry.mode !== "attach_existing")) {
    if (run) { await page.reload({ waitUntil: "domcontentloaded" }); }
    run = await openWorkspace(page, { ...input, run });
    evidence.run = run;
    const record = { case: item.case, category: item.category, expected: item.expected, files: {} };
    record.files.receptor = await chooseFile(page, "준비된 수용체 PDB/mmCIF", file(item.receptor));
    record.files.sdf = await chooseFile(page, "명시적 H가 있는 3D 리간드 V2000 SDF", file(item.sdf));
    if (item.ligand_instance) {
      await page.getByLabel("리간드 chain auth", { exact: true }).fill(item.ligand_instance.chain_auth);
      await page.getByLabel("seq auth", { exact: true }).fill(String(item.ligand_instance.seq_auth));
      await page.getByLabel("resname", { exact: true }).fill(item.ligand_instance.resname);
      record.enteredLigandInstance = item.ligand_instance;
    }
    if (item.connectivity === "sidecar") {
      await selectByLabel(page, "수용체 결합 제공", "sidecar");
      if (item.expected.kind === "upload_error") {
        record.upload = await uploadExpectingRejection(page, "완전한 receptor_bonds@1 JSON", file(item.sidecar),
          item.expected.text);
      } else if (item.sidecar) record.files.sidecar = await chooseFile(page, "완전한 receptor_bonds@1 JSON", file(item.sidecar));
    }
    if (item.acknowledge !== false)
      for (const label of ["공급된 수용체 결합 그래프가 완전함", "공급된 수소가 완전함",
        "공급된 protonation/tautomer 그대로 사용", "수용체 bond order/charge 추론 동의"])
        await page.getByLabel(label, { exact: true }).check();
    if (item.expected.kind !== "upload_error") {
      const before = posts.filter(value => value.endsWith("/chemical/preview")).length;
      const responsePromise = item.expected.kind === "client_error" ? null :
        page.waitForResponse(response => response.request().method() === "POST" &&
          response.url().includes(`/api/runs/${run}/chemical/preview`), { timeout: 30000 });
      await click(page, "준비 조건 미리보기");
      if (item.expected.kind === "client_error") {
        const alert = page.getByRole("alert").filter({ hasText: `준비 미리보기 실패: ${item.expected.text}` });
        await alert.first().waitFor({ timeout: 15000 });
        await page.waitForTimeout(300);
        assert.equal(posts.filter(value => value.endsWith("/chemical/preview")).length, before,
          "Missing graph was sent to the server instead of being refused before preview");
        record.shown = await alert.first().innerText();
      } else {
        const response = await responsePromise;
        const body = await response.json();
        record.previewStatus = response.status();
        if (item.expected.kind === "preview_error") {
          assert.equal(response.status(), 422, `${item.case}: expected typed input_invalid rejection`);
          const alert = page.getByRole("alert").filter({ hasText: "준비 미리보기 실패:" });
          await alert.first().waitFor({ timeout: 15000 });
          record.shown = await alert.first().innerText();
          assert.ok(record.shown.includes(item.expected.text), `${item.case}: visible error lacks the prerequisite`);
          record.response = body;
        } else {
          assert.equal(response.status(), 200);
          await page.getByText(/준비 조건 미충족/).first().waitFor({ timeout: 30000 });
          record.blockers = await expectVisibleBlockers(page, body, item.expected);
        }
      }
    }
    if (item.ligand_instance) for (const [label, value] of [["리간드 chain auth", item.ligand_instance.chain_auth],
      ["seq auth", String(item.ligand_instance.seq_auth)], ["resname", item.ligand_instance.resname]])
      assert.equal(await page.getByLabel(label, { exact: true }).inputValue(), value, "Colliding identity was relabeled");
    await computeControlsDisabled(page, item.case);
    record.frame = await capture(app, page, artifacts, `invalid-${item.case}`);
    await imageNonblank(record.frame.screenshot);
    evidence.cases.push(record);
  }
  assert.deepEqual(posts.filter(value => /\/jobs(\/|$)/.test(value)), [], "An invalid input submitted a job");
  evidence.jobPosts = 0;
  return evidence;
}
async function runInvalidAttach(session, input, evidence) {
  const { page, app, artifacts } = session;
  const manifest = JSON.parse(fs.readFileSync(path.join(input.variants, "m11-invalid-cases.json"), "utf8"));
  const item = manifest.cases.find(entry => entry.case === "covalent_ligand");
  assert.ok(item, "--variants was not generated with --attach-sidecar for this attach run");
  const posts = [];
  page.on("request", request => { if (request.method() === "POST") posts.push(new URL(request.url()).pathname); });
  const run = await openWorkspace(page, input); evidence.run = run;
  const selectedLigand = JSON.parse(fs.readFileSync(input.ligand, "utf8"));
  await selectByLabel(page, "입력 방식", "attach_existing");
  await page.waitForFunction(handle => [...document.querySelectorAll("select")].some(select =>
    [...select.options].some(option => option.value === handle)), input.complex, { timeout: 30000 });
  await nestedSelect(page, "기존 준비된 복합체").selectOption(input.complex);
  const key = JSON.stringify([selectedLigand.model_number, selectedLigand.chain_auth, selectedLigand.chain_label,
    selectedLigand.seq_auth, selectedLigand.seq_label, selectedLigand.icode, selectedLigand.resname]);
  await page.waitForFunction(value => [...document.querySelectorAll("select")].some(select =>
    [...select.options].some(option => option.value === value)), key, { timeout: 120000 });
  await selectByLabel(page, "정확한 리간드 인스턴스", key);
  await selectByLabel(page, "리간드 H 처리", "map_existing");
  evidence.files = { sdf: await chooseFile(page, "명시적 H가 있는 3D 리간드 V2000 SDF", input.sdf) };
  await selectByLabel(page, "수용체 결합 제공", "sidecar");
  evidence.files.sidecar = await chooseFile(page, "완전한 receptor_bonds@1 JSON", path.join(input.variants, item.sidecar));
  for (const label of ["공급된 수용체 결합 그래프가 완전함", "공급된 수소가 완전함",
    "공급된 protonation/tautomer 그대로 사용", "수용체 bond order/charge 추론 동의"])
    await page.getByLabel(label, { exact: true }).check();
  const responsePromise = page.waitForResponse(response => response.request().method() === "POST" &&
    response.url().includes(`/api/runs/${run}/chemical/preview`), { timeout: 60000 });
  await click(page, "준비 조건 미리보기");
  const response = await responsePromise;
  assert.equal(response.status(), 200);
  const body = await response.json();
  await page.getByText(/준비 조건 미충족/).first().waitFor({ timeout: 30000 });
  const expected = { ...item.expected, codes: [...item.expected.codes, "ligand_mapping_incomplete"] };
  evidence.cases = [{ case: item.case, category: item.category, expected: item.expected,
    blockers: await expectVisibleBlockers(page, body, expected) }];
  await computeControlsDisabled(page, item.case);
  evidence.cases[0].frame = await capture(app, page, artifacts, "invalid-covalent-ligand");
  assert.deepEqual(posts.filter(value => /\/jobs(\/|$)/.test(value)), [], "An invalid attach input submitted a job");
  return evidence;
}
async function runCapability(session, input, evidence) {
  const { page, app, artifacts } = session;
  const run = await openWorkspace(page, input); evidence.run = run;
  evidence.capabilityState = await capabilityState(page, input.expectCapability);
  evidence.fixtureLabel = input.fixtureLabel;
  evidence.files = { receptor: await chooseFile(page, "준비된 수용체 PDB/mmCIF", input.receptor),
    sdf: await chooseFile(page, "명시적 H가 있는 3D 리간드 V2000 SDF", input.sdf) };
  for (const label of ["공급된 수용체 결합 그래프가 완전함", "공급된 수소가 완전함",
    "공급된 protonation/tautomer 그대로 사용", "수용체 bond order/charge 추론 동의"])
    await page.getByLabel(label, { exact: true }).check();
  await click(page, "준비 조건 미리보기");
  await page.getByText(/준비 조건 미충족|계산 준비 가능/).first().waitFor({ timeout: 30000 });
  const terminalChecks = page.locator("label").filter({ hasText: "말단 확장 승인:" }).locator('input[type="checkbox"]');
  for (let i = 0, count = await terminalChecks.count(); i < count; i++) await terminalChecks.nth(i).check();
  await click(page, "준비 조건 미리보기");
  await page.getByText("계산 준비 가능", { exact: false }).first().waitFor({ timeout: 30000 });
  const submit = page.getByRole("button", { name: "화학 구조 준비 작업 저장", exact: true });
  const ready = input.expectCapability === "ready";
  assert.equal(await submit.isEnabled(), ready,
    ready ? "Ready worker did not enable the expensive preparation submission"
      : "Unavailable worker left the expensive preparation submission enabled");
  assert.equal(await page.getByRole("button", { name: "상호작용 계산 작업 저장", exact: true }).isDisabled(), true);
  assert.equal(await page.locator(".mw-chemical-row").count(), 0);
  assert.equal(await page.getByText(/^실제 계산 행 \d+개$/).count(), 0, "A result count was shown without a result");
  const jobs = (await readApi(page, `/runs/${run}/jobs`)).filter(job => job.protocol_id.startsWith("prolif_"));
  assert.deepEqual(jobs, [], "Capability inspection created a chemical job");
  evidence.submitEnabled = ready;
  evidence.frame = await capture(app, page, artifacts, `capability-${input.expectCapability}`);
  await imageNonblank(evidence.frame.screenshot);
  return evidence;
}
/** H13 setup: an ordinary M9 scene saved through the real control before chemical display (older scene). */
async function saveOrdinaryScene(page, run) {
  const name = "M11 QA ordinary scene saved before chemical display";
  await page.waitForFunction(() => {
    const native = window.__protviewQaSnapshot?.();
    return native?.ready && native.sessionId && native.catalogReady && !native.nativeBusy;
  }, null, { timeout: 60000 });
  // M10 Measure needs ball-and-stick; saving that representation lets the restore check re-enabled controls.
  await page.getByRole("button", { name: "ball-and-stick", exact: true }).click();
  await page.waitForFunction(() => {
    const native = window.__protviewQaSnapshot?.();
    return native?.representation === "ball-and-stick" && !native.nativeBusy && !native.cameraTransitioning;
  }, null, { timeout: 30000 });
  await page.getByRole("textbox", { name: "보기 이름" }).fill(name);
  const save = page.getByRole("button", { name: "현재 보기 저장", exact: true });
  await page.waitForFunction(() => [...document.querySelectorAll("button")]
    .some(button => button.textContent === "현재 보기 저장" && !button.disabled), null, { timeout: 30000 });
  const responsePromise = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/viewer/scenes`, { timeout: 30000 });
  await save.click();
  const response = await responsePromise;
  assert.equal(response.status(), 201, `Ordinary scene save failed: ${await response.text()}`);
  const handle = (await response.json()).handle;
  await page.getByText(`보기 저장 완료 · ${name}`, { exact: true }).waitFor({ timeout: 30000 });
  return handle;
}
async function runJobControls(session, input, evidence) {
  const { page } = session;
  let releaseJobs, finishJobs;
  const gate = new Promise(resolve => { releaseJobs = resolve; });
  const finished = new Promise(resolve => { finishJobs = resolve; });
  let heldJobs = 0;
  let pattern = null;
  const run = await openWorkspace(page, input, async selectedRun => {
    assert.match(selectedRun ?? "", /^run_[a-f0-9]+$/);
    pattern = `**/api/runs/${selectedRun}/jobs`;
    await page.route(pattern, async route => {
      if (route.request().method() !== "GET" || heldJobs > 0) { await route.continue(); return; }
      heldJobs++;
      const oldResponse = await route.fetch();
      const oldBody = await oldResponse.body();
      evidence.oldJobsSnapshot = { status: oldResponse.status(), sha256: sha(oldBody),
        jobs: JSON.parse(oldBody.toString("utf8")) };
      await gate;
      try { await route.fulfill({ response: oldResponse, body: oldBody }); }
      catch { /* superseded hydration can abort */ }
      finishJobs();
    });
  });
  evidence.run = run;
  const deadline = Date.now() + 30000;
  while (heldJobs === 0 && Date.now() < deadline) await page.waitForTimeout(50);
  assert.equal(heldJobs, 1, "Initial durable jobs GET was not actually held");
  let releaseUpload, finishUpload;
  const uploadGate = new Promise(resolve => { releaseUpload = resolve; });
  const uploadFinished = new Promise(resolve => { finishUpload = resolve; });
  let heldUploads = 0;
  const uploadPattern = `**/api/runs/${run}/chemical/imports?kind=receptor*`;
  await page.route(uploadPattern, async route => {
    heldUploads++;
    const response = await route.fetch(); const body = await response.body();
    evidence.supersededUpload = { status: response.status(), sha256: sha(body) };
    await uploadGate;
    try { await route.fulfill({ response, body }); } catch { /* old file input unmounted */ }
    finishUpload();
  });
  const receptorInput = page.locator(".mw-chemical-file").filter({ hasText: "준비된 수용체 PDB/mmCIF" })
    .locator('input[type="file"]');
  const chooser = page.waitForEvent("filechooser", { timeout: 15000 });
  await receptorInput.click(); await (await chooser).setFiles(input.receptor);
  const uploadDeadline = Date.now() + 30000;
  while (heldUploads === 0 && Date.now() < uploadDeadline) await page.waitForTimeout(50);
  assert.equal(heldUploads, 1);
  await selectByLabel(page, "입력 방식", "attach_existing");
  await selectByLabel(page, "입력 방식", "create_new");
  assert.equal(await receptorInput.isEnabled(), true, "Superseded upload left its input busy");
  releaseUpload(); await uploadFinished; await page.unroute(uploadPattern);
  assert.equal(await page.locator(".mw-chemical-file").filter({ hasText: "준비된 수용체 PDB/mmCIF" })
    .getByText(/obj:\/\/run_/).count(), 0, "Late upload rebound after mode change");
  evidence.files = { receptor: await chooseFile(page, "준비된 수용체 PDB/mmCIF", input.receptor),
    sdf: await chooseFile(page, "명시적 H가 있는 3D 리간드 V2000 SDF", input.sdf) };
  for (const label of ["공급된 수용체 결합 그래프가 완전함", "공급된 수소가 완전함",
    "공급된 protonation/tautomer 그대로 사용", "수용체 bond order/charge 추론 동의"])
    await page.getByLabel(label, { exact: true }).check();
  await click(page, "준비 조건 미리보기");
  await page.getByText(/준비 조건 미충족|계산 준비 가능/).first().waitFor({ timeout: 30000 });
  const terminalChecks = page.locator("label").filter({ hasText: "말단 확장 승인:" }).locator('input[type="checkbox"]');
  for (let i = 0, count = await terminalChecks.count(); i < count; i++) await terminalChecks.nth(i).check();
  await click(page, "준비 조건 미리보기");
  await page.getByText("계산 준비 가능", { exact: false }).waitFor({ timeout: 30000 });
  let releaseSubmission, finishSubmission;
  const submitGate = new Promise(resolve => { releaseSubmission = resolve; });
  const submitFinished = new Promise(resolve => { finishSubmission = resolve; });
  let submissionHits = 0;
  const submitPattern = `**/api/runs/${run}/jobs`;
  await page.route(submitPattern, async route => {
    if (route.request().method() !== "POST") { await route.continue(); return; }
    submissionHits++;
    const response = await route.fetch();
    const body = await response.body();
    evidence.heldSubmission = { status: response.status(), sha256: sha(body),
      response: JSON.parse(body.toString("utf8")) };
    await submitGate;
    try { await route.fulfill({ response, body }); } catch { /* stale UI request may abort */ }
    finishSubmission();
  });
  await click(page, "화학 구조 준비 작업 저장");
  const submittedDeadline = Date.now() + 30000;
  while (submissionHits === 0 && Date.now() < submittedDeadline) await page.waitForTimeout(50);
  assert.equal(submissionHits, 1, "Real durable preparation submission was not held");
  await click(page, "준비 조건 미리보기");
  await page.getByText("계산 준비 가능", { exact: false }).waitFor({ timeout: 30000 });
  releaseSubmission(); await submitFinished; await page.unroute(submitPattern);
  const selected = await submittedJob(page, "prepare");
  const jobId = selected.prepareJobId;
  assert.equal(jobId, evidence.heldSubmission.response.job_id,
    "Preview request superseded a valid held durable job submission");
  releaseJobs(); await finished;
  const afterOldHydration = await chemical(page);
  assert.equal(afterOldHydration.prepareJobId, jobId,
    "Delayed old jobs-list GET replaced a newer preparation job");
  await page.unroute(pattern);
  if (input.failureExpected === "true") {
    await click(page, "준비 작업 시작");
    const approval = page.getByRole("button", { name: "이 실제 작업 승인" });
    const deadline = Date.now() + 30000;
    let approved = false;
    while (Date.now() < deadline) {
      if (await approval.isVisible().catch(() => false)) { await approval.click(); approved = true; break; }
      if (/\b(failed|running)\b/.test(await page.locator(".mw-chemical-job").filter({ hasText: jobId }).innerText())) break;
      await page.waitForTimeout(100);
    }
    if (approved) await click(page, "준비 작업 시작");
    await page.locator(".mw-chemical-job").filter({ hasText: jobId }).getByText("화학 구조 준비 · failed")
      .waitFor({ timeout: 180000 });
    const failed = await readApi(page, `/runs/${run}/jobs/${jobId}`);
    assert.equal(failed.status, "failed");
    assert.deepEqual(failed.output_handles, []);
    assert.ok(failed.failure?.message, "Native failed attempt lacks a durable diagnostic");
    assert.ok(failed.failure.reason_code, "Native worker failure lacks its typed reason code");
    const visibleFailure = page.locator(".mw-chemical-job").filter({ hasText: jobId })
      .getByRole("alert");
    await visibleFailure.getByText(`${failed.failure.error}: ${failed.failure.message}`, { exact: true })
      .waitFor({ timeout: 15000 });
    await visibleFailure.getByText("실패한 화학 입력 진단").click();
    await visibleFailure.getByText(`reason_code ${failed.failure.reason_code}`, { exact: true })
      .waitFor({ timeout: 15000 });
    const shownDiagnostics = await visibleFailure.locator("li").allInnerTexts();
    for (const ref of failed.failure.source_atoms ?? [])
      assert.equal(shownDiagnostics.filter(line => line.startsWith("source atom:") &&
        line.includes(`atom ${ref.atom_name}, altloc ${ref.altloc || "∅"}, element ${ref.element}, site ${ref.site_index}, structure ${ref.structure_handle}`) &&
        line.includes(`auth ${ref.residue.chain_auth}/${ref.residue.seq_auth}`) &&
        line.includes(`, ${ref.residue.resname}, atom`)).length, 1,
      `Typed failure source atom ${atomIdentity(ref)} is not shown exactly once`);
    for (const residue of failed.failure.source_residues ?? [])
      assert.ok(shownDiagnostics.some(line => line.startsWith("source residue:") &&
        line.includes(`auth ${residue.chain_auth}/${residue.seq_auth}`) && line.endsWith(`, ${residue.resname}`)),
      `Typed failure source residue ${JSON.stringify(residue)} is not shown`);
    if (input.failureLocalized === "true") {
      assert.ok(failed.failure.sdf_atom_indices?.length,
        "This labeled native failure did not localize any supplied SDF atom index");
      for (const index of failed.failure.sdf_atom_indices)
        assert.equal(await visibleFailure.getByText(`SDF atom index (zero-based): ${index}`, { exact: true }).count(), 1);
    }
    evidence.retryHttpStatus = await clickAwaitingPost(page, "준비 작업 재시도", `/jobs/${jobId}/retry`);
    const retried = await readApi(page, `/runs/${run}/jobs/${jobId}`);
    assert.equal(retried.status, "queued");
    assert.deepEqual(retried.output_handles, []);
    evidence.jobControl = { heldJobs, jobId, afterOldHydration, failed, retried, approved,
      visibleNativeFailure: { reason_code: failed.failure.reason_code,
        sdf_atom_indices: failed.failure.sdf_atom_indices ?? [],
        source_atoms: failed.failure.source_atoms ?? [], source_residues: failed.failure.source_residues ?? [],
        shownDiagnostics },
      fixture: input.failureLocalized === "true"
        ? "labeled localized native-failure fixture; actual reason/indices read from durable worker failure"
        : "labeled synthetic pentavalent-carbon SDF; real native prepare fails, no scientific output" };
    return evidence;
  }
  await click(page, "준비 작업 취소");
  await page.locator(".mw-chemical-job").filter({ hasText: jobId }).getByText("화학 구조 준비 · cancelled")
    .waitFor({ timeout: 30000 });
  const durable = await readApi(page, `/runs/${run}/jobs/${jobId}`);
  assert.equal(durable.status, "cancelled");
  assert.deepEqual(durable.output_handles, []);
  assert.equal(await page.getByRole("button", { name: "준비 작업 재시도" }).isDisabled(), true,
    "Cancelled jobs are not retry eligible under the durable queue policy");
  evidence.jobControl = { heldJobs, jobId, afterOldHydration, durable,
    note: "Queued cancellation is terminal and deliberately not retryable; failed/interrupted retry has a separate mode" };
  return evidence;
}
async function runRunningCancel(session, input, evidence) {
  const { page } = session;
  const run = await openWorkspace(page, input); evidence.run = run;
  evidence.files = { receptor: await chooseFile(page, "준비된 수용체 PDB/mmCIF", input.receptor),
    sdf: await chooseFile(page, "명시적 H가 있는 3D 리간드 V2000 SDF", input.sdf) };
  for (const label of ["공급된 수용체 결합 그래프가 완전함", "공급된 수소가 완전함",
    "공급된 protonation/tautomer 그대로 사용", "수용체 bond order/charge 추론 동의"])
    await page.getByLabel(label, { exact: true }).check();
  await click(page, "준비 조건 미리보기");
  await page.getByText(/준비 조건 미충족|계산 준비 가능/).first().waitFor({ timeout: 30000 });
  const terminalChecks = page.locator("label").filter({ hasText: "말단 확장 승인:" }).locator('input[type="checkbox"]');
  for (let i = 0, count = await terminalChecks.count(); i < count; i++) await terminalChecks.nth(i).check();
  await click(page, "준비 조건 미리보기");
  await page.getByText("계산 준비 가능", { exact: false }).waitFor({ timeout: 30000 });
  await click(page, "화학 구조 준비 작업 저장");
  const selected = await submittedJob(page, "prepare");
  const id = selected.prepareJobId;
  let startResponses = 0;
  const onResponse = response => {
    if (response.request().method() === "POST" &&
        response.url().includes(`/api/runs/${run}/jobs/${id}/start`)) startResponses++;
  };
  page.on("response", onResponse);
  await click(page, "준비 작업 시작");
  const approval = page.getByRole("button", { name: "이 실제 작업 승인" });
  let approvalSeen = false, firstAlreadyRunning = false;
  const admissionDeadline = Date.now() + 30000;
  while (Date.now() < admissionDeadline) {
    if (await approval.isVisible().catch(() => false)) { approvalSeen = true; break; }
    const durable = await readApi(page, `/runs/${run}/jobs/${id}`);
    if (durable.status === "running") { firstAlreadyRunning = true; break; }
    if (["done", "failed", "cancelled"].includes(durable.status))
      throw new Error(`Worker reached ${durable.status} before the actual running-cancel window`);
    await page.waitForTimeout(100);
  }
  assert.ok(approvalSeen || firstAlreadyRunning, "Start never reached approval or running state");
  if (approvalSeen) {
    await approval.click();
    await page.getByText(/계산 승인을 기록했습니다/).first().waitFor({ timeout: 30000 });
    startResponses = 0; // Drop the typed approval 409; count only the executing Start response.
    await click(page, "준비 작업 시작");
  }
  const runningNode = page.locator(".mw-chemical-job").filter({ hasText: id }).getByText("화학 구조 준비 · running");
  await runningNode.waitFor({ timeout: 60000 });
  const running = await readApi(page, `/runs/${run}/jobs/${id}`);
  assert.equal(running.status, "running", "Cancellation case missed the actual running worker state");
  let workerStarted = null;
  const workerDeadline = Date.now() + 30000;
  while (Date.now() < workerDeadline && !workerStarted) {
    workerStarted = (await runEvents(page, run)).find(event =>
      event.type === "job_worker_started" && event.job_id === id) ?? null;
    if (!workerStarted) await page.waitForTimeout(100);
  }
  assert.ok(workerStarted?.attempt_id && workerStarted?.pid > 0,
    "Durable running state did not include an actual guardian STARTED worker observation");
  assert.equal(startResponses, 0, "Start HTTP response already completed before running Cancel");
  const cancel = page.getByRole("button", { name: "준비 작업 취소" });
  assert.equal(await cancel.isEnabled(), true,
    "Actual running Cancel is blocked while the synchronous Start HTTP request is pending");
  const cancelResponse = page.waitForResponse(value => value.request().method() === "POST" &&
    new URL(value.url()).pathname.endsWith(`/jobs/${id}/cancel`), { timeout: 60000 });
  await cancel.click();
  evidence.cancelHttpStatus = (await cancelResponse).status();
  const afterRequest = await readApi(page, `/runs/${run}/jobs/${id}`);
  assert.equal(afterRequest.cancel_requested, true);
  await page.waitForFunction(jobId => [...document.querySelectorAll(".mw-chemical-job")]
    .some(node => node.textContent?.includes(jobId) && node.textContent?.includes("cancelled")), id,
  { timeout: 180000 });
  const terminal = await readApi(page, `/runs/${run}/jobs/${id}`);
  assert.equal(terminal.status, "cancelled");
  assert.deepEqual(terminal.output_handles, []);
  const responseDeadline = Date.now() + 30000;
  while (startResponses === 0 && Date.now() < responseDeadline) await page.waitForTimeout(50);
  assert.ok(startResponses >= 1, "Held Start HTTP request did not settle after running cancellation");
  const settledText = await page.locator(".mw-chemical-job").filter({ hasText: id }).innerText();
  assert.match(settledText, /cancelled/);
  assert.doesNotMatch(settledText, /화학 구조 준비 · done/);
  const terminalEvents = await runEvents(page, run);
  const sameAttempt = terminalEvents.filter(event => event.attempt_id === workerStarted.attempt_id ||
    event.call_id === workerStarted.attempt_id);
  assert.equal(sameAttempt.filter(event => event.type === "budget_reserved").length, 1);
  assert.equal(sameAttempt.filter(event => event.type === "job_cleanup_verified" && event.group_empty === true).length, 1);
  assert.equal(sameAttempt.filter(event => event.type === "wall_charged" && event.reason === "job_attempt").length, 1);
  assert.equal(sameAttempt.filter(event => event.type === "job_terminal" && event.status === "cancelled").length, 1);
  page.off("response", onResponse);
  evidence.runningCancellation = { id, approvalSeen, workerStarted, running, afterRequest, terminal,
    attemptEvents: sameAttempt, startResponses,
    settledText, note: "Real running worker cancelled through visible button before synchronous Start response" };
  return evidence;
}
async function runRetryFailed(session, input, evidence) {
  const { page } = session;
  const run = await openWorkspace(page, input); evidence.run = run;
  await rail(page, "jobs");
  const initial = await readApi(page, `/runs/${run}/jobs/${input.job}`);
  assert.equal(initial.job_id, input.job);
  assert.ok(["failed", "interrupted"].includes(initial.status),
    "Retry control requires a genuinely failed or interrupted durable job");
  const stage = initial.protocol_id === "prolif_prepare_v1" ? "prepare" : "detect";
  const current = await waitChemical(page, state =>
    (stage === "prepare" ? state.prepareJobId : state.detectJobId) === input.job, 30000);
  assert.ok(current);
  evidence.retryHttpStatus = await clickAwaitingPost(page, stage === "prepare" ? "준비 작업 재시도" : "상호작용 작업 재시도",
    `/jobs/${input.job}/retry`);
  const retried = await readApi(page, `/runs/${run}/jobs/${input.job}`);
  assert.equal(retried.job_id, input.job);
  assert.equal(retried.status, "queued");
  assert.deepEqual(retried.output_handles, []);
  evidence.retry = { initial, retried, fixture: "preexisting real failed/interrupted job; no fabricated job status" };
  return evidence;
}
async function runDetectControls(session, input, evidence) {
  const { page } = session;
  const run = await openWorkspace(page, input); evidence.run = run;
  const graph = await waitChemical(page, state => state.graphHandle === input.graph &&
    state.sourceHandle && state.catalogReady, 60000);
  assert.equal(graph.graphHandle, input.graph);
  // Submission is idempotent (existing job semantics): a graph whose detection was already submitted
  // returns that same job, so no new queued job could ever be cancelled. Release3 used such a graph.
  const priorDetections = (await readApi(page, `/runs/${run}/jobs`)).filter(job =>
    job.protocol_id === "prolif_detect_v1" && job.input_handles.includes(input.graph));
  assert.deepEqual(priorDetections.map(job => job.job_id), [],
    "detect-controls needs a prepared graph with no prior detection (make one with --mode prepare-only)");
  const priorId = graph.detectJobId;
  await click(page, "상호작용 계산 작업 저장");
  const selected = await submittedJob(page, "detect", priorId);
  const id = selected.detectJobId;
  const queued = await readApi(page, `/runs/${run}/jobs/${id}`);
  assert.equal(queued.status, "queued");
  assert.deepEqual(queued.input_handles, [input.graph]);
  await click(page, "상호작용 작업 취소");
  await page.locator(".mw-chemical-job").filter({ hasText: id }).getByText("ProLIF 계산 · cancelled")
    .waitFor({ timeout: 30000 });
  const durable = await readApi(page, `/runs/${run}/jobs/${id}`);
  assert.equal(durable.protocol_id, "prolif_detect_v1");
  assert.equal(durable.status, "cancelled");
  assert.deepEqual(durable.output_handles, []);
  evidence.detectControl = { graph: input.graph, id, durable,
    note: "Actual queued detection cancelled before an expensive attempt; no assignment result" };
  return evidence;
}
async function runAttach(session, input, evidence) {
  const { page, app, artifacts } = session;
  const run = await openWorkspace(page, input); evidence.run = run;
  const fixture = JSON.parse(fs.readFileSync(input.mapping, "utf8"));
  const selectedLigand = JSON.parse(fs.readFileSync(input.ligand, "utf8"));
  assert.match(fixture.label ?? "", /fixture|prepared/i, "Attach mapping must be labeled fixture or prepared input");
  assert.equal(fixture.complex_handle, input.complex);
  assert.deepEqual(fixture.selected_ligand, selectedLigand);
  assert.ok(Array.isArray(fixture.mapping) && fixture.mapping.length > 0);
  const sourceKinds = await readApi(page, `/runs/${run}/objects/meta?handle=${encodeURIComponent(input.complex)}`);
  assert.ok(["structure_selection@2", "prepared_structure@1"].includes(sourceKinds.schema));
  evidence.complex = { handle: input.complex, schema: sourceKinds.schema };
  await selectByLabel(page, "입력 방식", "attach_existing");
  const complexSelect = nestedSelect(page, "기존 준비된 복합체");
  await page.waitForFunction(handle => [...document.querySelectorAll('select')].some(select =>
    [...select.options].some(option => option.value === handle)), input.complex, { timeout: 30000 });
  await complexSelect.selectOption(input.complex);
  const key = JSON.stringify([selectedLigand.model_number, selectedLigand.chain_auth,
    selectedLigand.chain_label, selectedLigand.seq_auth, selectedLigand.seq_label,
    selectedLigand.icode, selectedLigand.resname]);
  // The exact instance list comes from the complex's full atom catalog, which is slow on a large run.
  await page.waitForFunction(value => [...document.querySelectorAll('select')].some(select =>
    [...select.options].some(option => option.value === value)), key, { timeout: 120000 });
  await selectByLabel(page, "정확한 리간드 인스턴스", key);
  const policy = fixture.hydrogen_policy ?? "map_existing";
  await selectByLabel(page, "리간드 H 처리", policy);
  evidence.files = { sdf: await chooseFile(page, "명시적 H가 있는 3D 리간드 V2000 SDF", input.sdf) };
  if (input.connectivity === "sidecar") {
    await selectByLabel(page, "수용체 결합 제공", "sidecar");
    evidence.files.sidecar = await chooseFile(page, "완전한 receptor_bonds@1 JSON", input.sidecar);
  }
  if (fixture.sdf_record_index != null) await selectByLabel(page, "SDF 기록", String(fixture.sdf_record_index));
  const previewResponse = () => page.waitForResponse(response => response.request().method() === "POST" &&
    response.url().includes(`/api/runs/${run}/chemical/preview`));
  const inventoryPromise = previewResponse();
  await click(page, "준비 조건 미리보기");
  const inventoryResponse = await inventoryPromise;
  assert.equal(inventoryResponse.status(), 200);
  const inventory = await inventoryResponse.json();
  // H05: before any explicit choice the missing bijection is a visible prerequisite, never a guessed map.
  assert.equal(inventory.ready, false, "Attach preview was ready before any explicit mapping");
  assert.deepEqual(inventory.ligand_mapping, [], "Attach preview mapped atoms the user did not choose");
  assert.ok(inventory.blockers.some(item => item.code === "ligand_mapping_incomplete"));
  await page.getByRole("alert").filter({ hasText: "ligand_mapping_incomplete:" }).first().waitFor({ timeout: 30000 });
  evidence.unmappedBlockers = inventory.blockers.map(item => ({ code: item.code, atoms: item.atoms.length }));
  await page.getByRole("region", { name: "SDF 전체 원자 대응" }).waitFor({ timeout: 30000 });
  const editor = page.getByRole("region", { name: "SDF 전체 원자 대응" });
  const atomRows = editor.locator("label");
  const atomRowCount = await atomRows.count();
  assert.equal(atomRowCount, inventory.ligand_atoms.length,
    "Full selected SDF inventory is not visible before mapping");
  const heavyIndices = inventory.ligand_atoms.filter(atom => !atom.hydrogen).map(atom => atom.sdf_atom_index);
  const expectedIndices = policy === "replace_from_sdf" ? heavyIndices
    : inventory.ligand_atoms.map(atom => atom.sdf_atom_index);
  assert.deepEqual(fixture.mapping.map(item => item.sdf_atom_index).sort((a, b) => a - b),
    expectedIndices.sort((a, b) => a - b),
    `${policy} fixture must map exactly ${policy === "replace_from_sdf" ? "every SDF heavy atom" : "every SDF atom"}`);
  evidence.inventory = { sdfAtoms: inventory.ligand_atoms.length, heavyAtoms: heavyIndices.length,
    selectedLigandAtoms: inventory.selected_ligand_atoms, policy };
  const choices = [];
  for (const item of fixture.mapping) {
    const row = atomRows.filter({ hasText: new RegExp(`^SDF #${item.sdf_atom_index}\\b`) });
    assert.equal(await row.count(), 1, `SDF #${item.sdf_atom_index} mapping row missing`);
    const selector = row.locator("select");
    const optionValues = await selector.locator("option").evaluateAll(list => list.map(item => item.value));
    const matching = optionValues.filter(value => {
      if (!value) return false;
      const actual = JSON.parse(value);
      return atomIdentity(actual) === atomIdentity(item.source_atom);
    });
    assert.equal(matching.length, 1, `Exact supplied AtomRef unavailable for SDF #${item.sdf_atom_index}`);
    await selector.selectOption(matching[0]);
    assert.equal(await atomRows.count(), atomRowCount,
      "Mapping editor disappeared after a single explicit choice");
    choices.push({ sdf_atom_index: item.sdf_atom_index, source_atom: item.source_atom });
  }
  evidence.manualMapping = choices;
  for (const label of ["공급된 수용체 결합 그래프가 완전함", "공급된 수소가 완전함",
    "공급된 protonation/tautomer 그대로 사용", "수용체 bond order/charge 추론 동의"])
    await page.getByLabel(label, { exact: true }).check();
  const terminalChecks = page.locator("label").filter({ hasText: "말단 확장 승인:" }).locator('input[type="checkbox"]');
  evidence.terminalExtensionCount = await terminalChecks.count();
  for (let i = 0; i < evidence.terminalExtensionCount; i++) await terminalChecks.nth(i).check();
  await page.getByLabel("준비 설명 (검증되지 않은 로컬 주석)").fill(fixture.description ?? "Labeled prepared attach fixture; supplied chemistry unverified");
  const readyPromise = previewResponse();
  await click(page, "준비 조건 미리보기");
  const readyPreview = await (await readyPromise).json();
  await page.getByText("계산 준비 가능", { exact: false }).waitFor({ timeout: 30000 });
  assert.equal(readyPreview.ready, true, `Attach preview not ready: ${JSON.stringify(readyPreview.blockers)}`);
  assert.deepEqual(readyPreview.ligand_mapping.map(item => [item.sdf_atom_index, atomIdentity(item.source_atom)]).sort(),
    choices.map(item => [item.sdf_atom_index, atomIdentity(item.source_atom)]).sort(),
    "Validated preview mapping differs from the visible explicit choices");
  const shownDiscrepancies = [];
  for (const item of readyPreview.ligand_mapping) {
    assert.ok(Number.isFinite(item.discrepancy_A) && item.discrepancy_A >= 0 && item.discrepancy_A <= 0.002,
      `SDF #${item.sdf_atom_index} discrepancy outside the contract bound`);
    const row = atomRows.filter({ hasText: new RegExp(`^SDF #${item.sdf_atom_index}\\b`) });
    const shown = await row.locator("small").filter({ hasText: "검증된 좌표 차이" }).innerText();
    assert.equal(shown.trim(), `검증된 좌표 차이 ${item.discrepancy_A.toFixed(4)} Å`,
      `Visible coordinate discrepancy differs for SDF #${item.sdf_atom_index}`);
    shownDiscrepancies.push({ sdf_atom_index: item.sdf_atom_index, discrepancy_A: item.discrepancy_A, shown });
  }
  evidence.mappingPreview = { mapped: readyPreview.ligand_mapping.length, shownDiscrepancies,
    maxDiscrepancy_A: Math.max(...readyPreview.ligand_mapping.map(item => item.discrepancy_A)) };
  const priorPrepareId = (await chemical(page)).prepareJobId;
  await click(page, "화학 구조 준비 작업 저장");
  const queuedPrepare = await submittedJob(page, "prepare", priorPrepareId);
  const queuedId = queuedPrepare.prepareJobId;
  const jobsBeforeReopen = await readApi(page, `/runs/${run}/jobs`);
  assert.ok(Array.isArray(jobsBeforeReopen));
  const queuedDurable = jobsBeforeReopen.find(job => job.job_id === queuedId);
  assert.equal(queuedDurable?.protocol_id, "prolif_prepare_v1");
  assert.equal(queuedDurable.status, "queued",
    "Attach submission reused an existing preparation instead of saving a new queued job");
  if (policy === "replace_from_sdf") {
    assert.ok(jobsBeforeReopen.some(job => job.protocol_id === "prolif_prepare_v1" &&
      job.status === "done" && job.job_id !== queuedId),
    "Mixed-history fixture has no older completed preparation");
    assert.ok(jobsBeforeReopen.some(job => job.protocol_id === "prolif_detect_v1" && job.status === "done"),
      "Mixed-history fixture has no older completed detection");
  }
  await page.reload({ waitUntil: "domcontentloaded" });
  assert.equal(await openWorkspace(page, input), run,
    "Visible chemical workspace reopened in a different run");
  const queuedReopened = await waitChemical(page, state => state.prepareJobId === queuedId &&
    state.detectJobId === null && state.sourceHandle === null, 30000);
  assert.equal(await page.getByRole("button", { name: "준비 작업 시작" }).isEnabled(), true);
  assert.equal(await page.getByRole("button", { name: "준비 작업 취소" }).isEnabled(), true);
  const queuedFrame = await capture(app, page, artifacts, "queued-prepare-reopened");
  evidence.queuedReopen = { jobId: queuedId, priorDonePreparations: jobsBeforeReopen.filter(job =>
    job.protocol_id === "prolif_prepare_v1" && job.status === "done").map(job => job.job_id),
    priorDoneDetections: jobsBeforeReopen.filter(job => job.protocol_id === "prolif_detect_v1" &&
      job.status === "done").map(job => job.job_id), selected: queuedReopened, frame: queuedFrame };
  evidence.prepare = await startWithApproval(page, "prepare");
  const preparedJob = await readApi(page, `/runs/${run}/jobs/${queuedId}`);
  assert.equal(preparedJob.status, "done");
  const newSource = preparedJob.artifacts.chemical_structure;
  const newGraph = preparedJob.artifacts.chemical_graph;
  evidence.prepared = await waitChemical(page, state => state.sourceHandle === newSource &&
    state.graphHandle === newGraph && state.catalogReady && state.native?.sourceHandle === newSource, 60000);
  evidence.derivedSource = await attachSourceLink(page, run, newSource, input.complex, policy, choices,
    selectedLigand, jobsBeforeReopen);
  const priorDetectId = (await chemical(page)).detectJobId;
  await click(page, "상호작용 계산 작업 저장");
  const queuedDetect = await submittedJob(page, "detect", priorDetectId);
  const detectDurable = await readApi(page, `/runs/${run}/jobs/${queuedDetect.detectJobId}`);
  assert.equal(detectDurable.status, "queued", "Attach detection reused an existing job");
  assert.deepEqual(detectDurable.input_handles, [newGraph]);
  evidence.detect = await startWithApproval(page, "detect");
  const detectedJob = await readApi(page, `/runs/${run}/jobs/${queuedDetect.detectJobId}`);
  assert.equal(detectedJob.status, "done");
  const newResult = detectedJob.artifacts.chemical_interaction_set;
  evidence.detected = await waitChemical(page, state => state.resultHandle === newResult &&
    state.sourceHandle === newSource && state.catalogReady && state.native?.sourceHandle === newSource, 60000);
  evidence.resultHandle = evidence.detected.resultHandle;
  if (evidence.detected.resultTotal > 0) {
    evidence.row = await focusFirstRow(page, app, artifacts);
    evidence.pagination = await paginationControls(page);
  }
  evidence.restrictions = await testRestrictions(page, "attach source");
  await click(page, "화학 보고서 저장");
  const reportSelect = nestedSelect(page, "저장된 보고서");
  await page.waitForFunction(() => [...document.querySelectorAll('select')].some(select =>
    select.value.includes("method_report_manifest")), null, { timeout: 30000 });
  evidence.reportHandle = await reportSelect.inputValue();
  evidence.report = await downloadReport(app, page, run, evidence.reportHandle, artifacts);
  return evidence;
}
/** The attached chemical source is a new derived object whose saved manifest links the original complex. */
async function attachSourceLink(page, run, sourceHandle, complexHandle, policy, choices, selectedLigand, priorJobs) {
  const priorSources = priorJobs.filter(job => job.protocol_id === "prolif_prepare_v1" && job.status === "done")
    .map(job => job.artifacts?.chemical_structure);
  assert.equal(priorSources.includes(sourceHandle), false, "Attach did not create a new derived chemical source");
  assert.notEqual(sourceHandle, complexHandle);
  const meta = await readApi(page, `/runs/${run}/objects/meta?handle=${encodeURIComponent(sourceHandle)}`);
  assert.equal(meta.kind, "chemical_structure");
  const saved = await readApi(page,
    `/runs/${run}/chemical/preparation-manifests?source_handle=${encodeURIComponent(sourceHandle)}`);
  const manifest = saved.manifest;
  assert.equal(manifest.mode, "attach_existing");
  assert.equal(manifest.source_handle, complexHandle, "Derived source manifest is not linked to the original complex");
  assert.equal(manifest.request.complex_handle, complexHandle);
  assert.equal(manifest.request.hydrogen_policy, policy);
  assert.deepEqual(manifest.request.selected_ligand, selectedLigand);
  assert.deepEqual(manifest.request.mapping.map(item => [item.sdf_atom_index, atomIdentity(item.source_atom)]).sort(),
    choices.map(item => [item.sdf_atom_index, atomIdentity(item.source_atom)]).sort());
  assert.equal(manifest.attached_source_sites.length, choices.length);
  for (const site of manifest.attached_source_sites) {
    assert.equal(site.source_atom.structure_handle, complexHandle);
    assert.ok(site.discrepancy_A >= 0 && site.discrepancy_A <= 0.002);
  }
  const original = [];
  for (let offset = 0; ; offset += 500) {
    const page500 = await readApi(page, `/runs/${run}/structures/atoms?handle=${encodeURIComponent(complexHandle)}&offset=${offset}&limit=500`);
    original.push(...page500.rows);
    if (original.length >= page500.total) break;
  }
  const residueKey = residue => JSON.stringify([residue.model_number, residue.chain_auth, residue.chain_label,
    residue.seq_auth, residue.seq_label, residue.icode, residue.resname]);
  const originalH = original.filter(row => residueKey(row.ref.residue) === residueKey(selectedLigand) &&
    row.ref.element.toUpperCase() === "H").map(row => atomIdentity(row.ref)).sort();
  const excluded = (manifest.excluded_original_ligand_hydrogens ?? []).map(atomIdentity).sort();
  if (policy === "replace_from_sdf") assert.deepEqual(excluded, originalH,
    "replace_from_sdf must enumerate every excluded original ligand H AtomRef");
  else assert.deepEqual(excluded, [], "map_existing must not exclude original ligand H");
  const derived = [];
  for (let offset = 0; ; offset += 1000) {
    const next = await readApi(page, `/runs/${run}/chemical/structures/atoms?handle=${encodeURIComponent(sourceHandle)}&offset=${offset}&limit=1000`);
    derived.push(...next.rows);
    if (derived.length >= next.total) break;
  }
  const derivedLigand = derived.filter(row => residueKey(row.ref.residue) === residueKey(selectedLigand));
  assert.ok(derivedLigand.every(row => row.ref.structure_handle === sourceHandle));
  return { sourceHandle, kind: meta.kind, manifestHandle: saved.meta.handle, linkedComplex: manifest.source_handle,
    hydrogenPolicy: policy, attachedSites: manifest.attached_source_sites.length,
    excludedOriginalHydrogens: excluded.length, originalLigandHydrogens: originalH.length,
    derivedLigandAtoms: derivedLigand.length,
    derivedLigandHydrogens: derivedLigand.filter(row => row.ref.element.toUpperCase() === "H").length };
}
async function runReopen(session, input, evidence) {
  const { page, app, artifacts } = session;
  let createdScene = null;
  const run = await openWorkspace(page, input, input.mode === "restrictions" && !input.scene
    ? async selectedRun => { createdScene = await saveOrdinaryScene(page, selectedRun); } : null);
  evidence.run = run;
  const sceneHandle = input.scene ?? createdScene;
  if (input.mode === "restrictions") {
    const bytes = await getBytes(page, `/runs/${run}/viewer/scenes/selected?handle=${encodeURIComponent(sceneHandle)}`);
    evidence.scene = { handle: sceneHandle, createdThroughUi: !!createdScene, selectedBytesSha256Before: sha(bytes) };
  }
  if (["replay", "reopen"].includes(input.mode)) evidence.scienceEventsBefore = await scienceEvents(page, run);
  const selects = nestedSelect(page, "저장된 화학 결과");
  assert.ok(await selects.count() >= 1);
  await selects.last().selectOption(input.result);
  const state = await waitChemical(page, observation => observation.resultHandle === input.result &&
    observation.catalogReady && observation.native?.sourceHandle === observation.sourceHandle, 60000);
  assert.equal(state.native.sessionId, null);
  evidence.result = await readApi(page, `/runs/${run}/chemical/results?handle=${encodeURIComponent(input.result)}`);
  assert.equal(evidence.result.meta.handle, input.result);
  assert.equal(state.sourceHandle, evidence.result.result.chemical_structure_handle);
  evidence.native = state;
  evidence.restrictionsOn = await testRestrictions(page, "reopened source");
  if (state.resultTotal > 0) evidence.row = await focusFirstRow(page, app, artifacts);
  if (input.mode === "reopen-complete") {
    assert.ok(state.resultTotal > 0, "Completed attach fixture unexpectedly has no native interaction rows");
    evidence.nativeControls = await nativeControls(page, app, artifacts, evidence.row);
    evidence.pagination = await paginationControls(page);
    evidence.categories = await categoryControls(page, app, artifacts);
    await click(page, "화학 보고서 저장");
    const reportSelect = nestedSelect(page, "저장된 보고서");
    await page.waitForFunction(() => [...document.querySelectorAll("select")].some(select =>
      select.value.includes("method_report_manifest")), null, { timeout: 30000 });
    evidence.reportHandle = await reportSelect.inputValue();
    evidence.report = await downloadReport(app, page, run, evidence.reportHandle, artifacts);
    evidence.completedExisting = { resultHandle: input.result, reportHandle: evidence.reportHandle,
      preparationOrDetectionSubmitted: false,
      source: "actual completed prior attach result reopened without native computation" };
  }
  if (input.report) {
    const selector = nestedSelect(page, "저장된 보고서");
    await selector.selectOption(input.report);
    await page.getByLabel("저장된 화학 보고서").waitFor({ timeout: 30000 });
    evidence.report = await downloadReport(app, page, run, input.report, artifacts);
  }
  if (input.mode === "restrictions") {
    assert.ok(state.resultTotal > 0, "Restrictions need a result row so the geometry annotation can be shown and hidden");
    const shown = await waitChemical(page, observation => observation.selectedRowId &&
      observation.native?.chemicalAnnotation?.rowId === observation.selectedRowId, 30000);
    evidence.annotationShown = shown.native.chemicalAnnotation.rowId;
    evidence.restrictionsAnnotationOn = await attemptRestrictedControls(page, "annotation on");
    await click(page, "기하 주석 숨기기");
    await waitChemical(page, observation => observation.native?.chemicalAnnotation === null);
    evidence.restrictionsOff = await testRestrictions(page, "annotation hidden");
    evidence.restrictionsAnnotationOff = await attemptRestrictedControls(page, "annotation off");
    const savedScene = await readApi(page, `/runs/${run}/viewer/scenes/selected?handle=${encodeURIComponent(sceneHandle)}`);
    assert.equal(savedScene.handle, sceneHandle);
    await rail(page, "models");
    await selectByLabel(page, "저장된 일반 보기 복원", sceneHandle);
    await click(page, "저장된 보기 복원 후 화학 보기 끝내기");
    await page.waitForFunction(() => typeof window.__protviewQaChemical !== "function" ||
      !document.body.textContent?.includes("준비 입력과 실제 화학 상호작용"), null, { timeout: 30000 });
    await page.waitForFunction(expected => {
      const native = window.__protviewQaSnapshot?.();
      return native?.ready && native.sessionId && native.sourceHandle === expected &&
        native.catalogReady && !native.nativeBusy && !native.cameraTransitioning;
    }, savedScene.value.structure_handle, { timeout: 60000 });
    evidence.restoredNative = await page.evaluate(() => window.__protviewQaSnapshot?.());
    assert.equal(evidence.restoredNative.sourceHandle, savedScene.value.structure_handle);
    assert.deepEqual(evidence.restoredNative.selection, savedScene.value.selection);
    assert.equal(evidence.restoredNative.theme, savedScene.value.theme);
    assert.equal(evidence.restoredNative.representation,
      savedScene.value.representation === "ball_and_stick" ? "ball-and-stick" : savedScene.value.representation);
    for (const field of ["position", "target", "up"]) assert.ok(
      separation(evidence.restoredNative.nativeCamera[field], savedScene.value.camera[field]) < 1e-3,
      `Restored M9 camera ${field} differs from immutable scene`);
    for (const field of ["fov", "radius", "radiusMax", "fog", "minNear", "minFar"])
      assert.ok(Math.abs(evidence.restoredNative.nativeCamera[field] - savedScene.value.camera[field]) < 1e-3,
        `Restored M9 camera ${field} differs from immutable scene`);
    for (const field of ["mode", "clipFar"])
      assert.equal(evidence.restoredNative.nativeCamera[field], savedScene.value.camera[field]);
    assert.equal(await page.getByRole("button", { name: "프롬프트 사용 불가" }).count(), 0);
    assert.equal(await page.getByRole("button", { name: "원자 거리 측정", exact: true }).isEnabled(), true,
      "Ordinary source did not restore the M10 Measure control");
    assert.equal(await page.getByRole("button", { name: "현재 보기 저장", exact: true }).count(), 1);
    const afterBytes = await getBytes(page, `/runs/${run}/viewer/scenes/selected?handle=${encodeURIComponent(sceneHandle)}`);
    assert.equal(sha(afterBytes), evidence.scene.selectedBytesSha256Before, "Restoring changed the immutable M9 scene");
    evidence.scene.selectedBytesSha256After = sha(afterBytes);
    evidence.restoredControls = { measureEnabled: true, savePresent: true, chemicalWorkspaceClosed: true };
  }
  if (["replay", "reopen"].includes(input.mode)) {
    evidence.scienceEventsAfter = await scienceEvents(page, run);
    assert.deepEqual(evidence.scienceEventsAfter, evidence.scienceEventsBefore,
      "Chemical reopen appended scientific/job/approval activity");
  }
  if (input.mode === "replay" && (input.expectMarkdownSha || input.expectJsonSha)) {
    // Browser download bytes after events-only recovery equal the original root's recorded download bytes.
    if (input.expectMarkdownSha) assert.equal(evidence.report.markdown.sha256, input.expectMarkdownSha);
    if (input.expectJsonSha) assert.equal(evidence.report.json.sha256, input.expectJsonSha);
    evidence.crossRootReportBytesEqual = true;
  }
  return evidence;
}
async function runFaults(session, input, evidence) {
  const { page, app, artifacts } = session;
  const run = await openWorkspace(page, input); evidence.run = run;
  evidence.scienceEventsBefore = await scienceEvents(page, run);
  const resultSelect = nestedSelect(page, "저장된 화학 결과").first();
  await resultSelect.selectOption(input.result);
  const baseline = await waitChemical(page, state => state.resultHandle === input.result && state.catalogReady, 60000);
  const source = baseline.sourceHandle;
  evidence.baseline = baseline;
  const catalogPattern = `**/api/runs/${run}/chemical/structures/atoms?*`;
  let badCatalogHits = 0;
  await page.route(catalogPattern, async route => {
    const response = await route.fetch();
    const body = await response.json();
    badCatalogHits++;
    body.viewer_source_sha256 = "0".repeat(64);
    await route.fulfill({ response, json: body });
  });
  await rail(page, "models");
  await click(page, "저장된 결과 다시 읽기");
  await page.getByRole("alert").filter({ hasText: /화학 구조 읽기 실패|원자 목록|출처/ }).first()
    .waitFor({ timeout: 45000 });
  assert.ok(badCatalogHits > 0, "Malformed catalog route fixture did not hit an actual GET");
  const bad = await chemical(page);
  assert.notEqual(bad.catalogReady, true, "Malformed source catalog was admitted as ready");
  evidence.badCatalog = { hits: badCatalogHits, native: bad,
    alert: await page.getByRole("alert").filter({ hasText: /화학 구조 읽기 실패|원자 목록|출처/ }).first().innerText(),
    fixture: "renderer route changed only viewer_source_sha256; no science object was created" };
  await page.unroute(catalogPattern);
  const validCatalogGets = [];
  await page.route(catalogPattern, async route => {
    const response = await route.fetch();
    const body = await response.json();
    validCatalogGets.push({ status: response.status(), sha: body.viewer_source_sha256,
      handle: body.structure_handle, offset: body.offset });
    await route.fulfill({ response });
  });
  await click(page, "저장된 데이터 다시 읽기");
  const restored = await waitChemical(page, state => state.resultHandle === input.result && state.catalogReady &&
    state.sourceHandle === source, 60000);
  assert.ok(validCatalogGets.length > 0, "Catalog retry did not make a fresh GET");
  const view = await readApi(page, `/runs/${run}/chemical/structures/view?handle=${encodeURIComponent(source)}`);
  assert.ok(validCatalogGets.every(item => item.status === 200 && item.sha === view.viewer_source_sha256 &&
    item.handle === source), "Retry failed to consume fresh valid same-source catalog pages");
  evidence.validRetry = { native: restored, validCatalogGets, servedTextSha256: sha(Buffer.from(view.text, "utf8")) };
  assert.equal(view.viewer_source_sha256, evidence.validRetry.servedTextSha256);
  await page.unroute(catalogPattern);

  if (input.otherResult) {
    assert.notEqual(input.result, input.otherResult);
    let releaseA;
    const heldA = new Promise(resolve => { releaseA = resolve; });
    let aHits = 0;
    const resultPattern = `**/api/runs/${run}/chemical/results?*`;
    await page.route(resultPattern, async route => {
      const handle = new URL(route.request().url()).searchParams.get("handle");
      if (handle === input.result) { aHits++;
        await heldA;
        try { await route.continue(); } catch { /* aborted old request is expected */ }
      } else await route.continue();
    });
    await resultSelect.selectOption("");
    await resultSelect.selectOption(input.result);
    await page.waitForFunction(() => document.body.textContent?.includes("저장된 화학 상호작용 읽는 중"),
      null, { timeout: 15000 });
    assert.equal(aHits, 1, "Held older A detail GET was not admitted");
    await resultSelect.selectOption(input.otherResult);
    const latest = await waitChemical(page, state => state.resultHandle === input.otherResult &&
      state.catalogReady && state.native?.sourceHandle === state.sourceHandle, 60000);
    releaseA();
    await page.waitForTimeout(300);
    const settled = await chemical(page);
    assert.equal(settled.resultHandle, input.otherResult);
    assert.equal(settled.sourceHandle, latest.sourceHandle);
    evidence.heldResult = { aHits, latest, settled, fixture: "held old selected-result GET" };
    await page.unroute(resultPattern);

    const otherRead = await readApi(page, `/runs/${run}/chemical/results?handle=${encodeURIComponent(input.otherResult)}`);
    const otherSource = otherRead.result.chemical_structure_handle;
    assert.notEqual(otherSource, source,
      "Held source-read race requires two real results from distinct chemical sources");
    let releaseOld, finishOld;
    const oldGate = new Promise(resolve => { releaseOld = resolve; });
    const oldFinished = new Promise(resolve => { finishOld = resolve; });
    let oldSourceHits = 0;
    const viewPattern = `**/api/runs/${run}/chemical/structures/view?*`;
    await page.route(viewPattern, async route => {
      const handle = new URL(route.request().url()).searchParams.get("handle");
      if (handle !== source) { await route.continue(); return; }
      oldSourceHits++;
      await oldGate;
      try { await route.continue(); } catch { /* superseded GET may abort */ }
      finishOld();
    });
    await resultSelect.selectOption(input.result);
    await page.waitForFunction(() => document.body.textContent?.includes("화학 구조와 원자 목록을 확인하는 중"),
      null, { timeout: 15000 });
    const deadline = Date.now() + 30000;
    while (oldSourceHits === 0 && Date.now() < deadline) await page.waitForTimeout(50);
    assert.equal(oldSourceHits, 1, "Older source-view GET was not actually held");
    await resultSelect.selectOption(input.otherResult);
    const latestSource = await waitChemical(page, state => state.resultHandle === input.otherResult &&
      state.sourceHandle === otherSource && state.catalogReady &&
      state.native?.sourceHandle === otherSource, 60000);
    releaseOld(); await oldFinished;
    const afterOld = await chemical(page);
    assert.equal(afterOld.resultHandle, input.otherResult);
    assert.equal(afterOld.sourceHandle, otherSource);
    assert.equal(afterOld.native?.sourceHandle, otherSource);
    evidence.heldSource = { oldSourceHits, oldSource: source, latestSource, afterOld,
      fixture: "held old chemical structure-view GET; actual latest result selected through UI" };
    await page.unroute(viewPattern);
  }

  if (input.report && input.otherReport) {
    assert.notEqual(input.report, input.otherReport);
    const currentResult = (await chemical(page)).resultHandle;
    const [oldReport, newReport] = await Promise.all([
      readApi(page, `/runs/${run}/reports/selected?handle=${encodeURIComponent(input.report)}`),
      readApi(page, `/runs/${run}/reports/selected?handle=${encodeURIComponent(input.otherReport)}`)]);
    assert.equal(oldReport.manifest.result_handle, currentResult);
    assert.equal(newReport.manifest.result_handle, currentResult);
    const selector = nestedSelect(page, "저장된 보고서");
    let releaseOldReport, finishOldReport;
    const gate = new Promise(resolve => { releaseOldReport = resolve; });
    const finished = new Promise(resolve => { finishOldReport = resolve; });
    let oldReportHits = 0;
    const reportPattern = `**/api/runs/${run}/reports/selected?*`;
    await page.route(reportPattern, async route => {
      if (new URL(route.request().url()).searchParams.get("handle") !== input.report) {
        await route.continue(); return;
      }
      oldReportHits++;
      await gate;
      try { await route.continue(); } catch { /* old read may abort */ }
      finishOldReport();
    });
    await selector.selectOption(input.report);
    const deadline = Date.now() + 30000;
    while (oldReportHits === 0 && Date.now() < deadline) await page.waitForTimeout(50);
    assert.equal(oldReportHits, 1);
    await selector.selectOption(input.otherReport);
    await page.getByLabel("저장된 화학 보고서").waitFor({ timeout: 30000 });
    const latestMarkdown = await page.getByLabel("저장된 화학 보고서").innerText();
    assert.equal(latestMarkdown, newReport.markdown);
    releaseOldReport(); await finished;
    assert.equal(await page.getByLabel("저장된 화학 보고서").innerText(), latestMarkdown);
    evidence.heldReport = { oldReportHits, latestHandle: input.otherReport,
      markdownSha256: sha(Buffer.from(latestMarkdown, "utf8")), fixture: "held older selected-report GET" };
    await page.unroute(reportPattern);
  }

  const beforeTimeout = await chemical(page);
  const heldHandle = beforeTimeout.sourceHandle;
  const heldResult = beforeTimeout.resultHandle;
  let releaseView, finishView;
  const heldGate = new Promise(resolve => { releaseView = resolve; });
  const heldFinished = new Promise(resolve => { finishView = resolve; });
  let heldViewHits = 0;
  const timeoutPattern = `**/api/runs/${run}/chemical/structures/view?*`;
  await resultSelect.selectOption("");
  await waitChemical(page, state => state.resultHandle === "", 15000);
  await page.route(timeoutPattern, async route => {
    if (new URL(route.request().url()).searchParams.get("handle") !== heldHandle) {
      await route.continue(); return;
    }
    heldViewHits++;
    await heldGate;
    try { await route.continue(); } catch { /* bounded renderer request already aborted */ }
    finishView();
  });
  await resultSelect.selectOption(heldResult);
  const deadline = Date.now() + 30000;
  while (heldViewHits === 0 && Date.now() < deadline) await page.waitForTimeout(50);
  assert.equal(heldViewHits, 1, "Timed chemical source read did not issue its actual GET");
  const timeoutAlert = page.getByRole("alert").filter({ hasText: "화학 구조 읽기 실패" }).first();
  await timeoutAlert.waitFor({ timeout: 45000 });
  const timedOut = await chemical(page);
  assert.notEqual(timedOut.catalogReady, true);
  evidence.sourceDeadline = { heldViewHits, source: heldHandle,
    alert: await timeoutAlert.innerText(), timedOut,
    fixture: "renderer-held immutable chemical structure GET beyond bounded 30-second read deadline" };
  releaseView(); await heldFinished; await page.unroute(timeoutPattern);
  await click(page, "저장된 데이터 다시 읽기");
  evidence.sourceDeadline.recovered = await waitChemical(page, state =>
    state.resultHandle === heldResult && state.sourceHandle === heldHandle && state.catalogReady &&
    state.native?.sourceHandle === heldHandle, 60000);

  const beforeContext = await chemical(page);
  const lost = await page.evaluate(() => {
    const canvas = document.querySelector("canvas");
    const gl = canvas?.getContext("webgl2") || canvas?.getContext("webgl");
    const extension = gl?.getExtension("WEBGL_lose_context");
    if (!extension) return false;
    extension.loseContext(); return true;
  });
  evidence.contextLossFixture = { extensionAvailable: lost, before: beforeContext };
  if (lost) {
    await page.getByRole("alert").filter({ hasText: /표시|WebGL|context|구조/ }).first()
      .waitFor({ timeout: 30000 });
    await click(page, "저장된 데이터 다시 읽기");
    evidence.contextRecovery = await waitChemical(page, state => state.catalogReady &&
      state.native?.ready && state.sourceHandle === beforeContext.sourceHandle, 60000);
  }
  evidence.finalFrame = await capture(app, page, artifacts, "fault-recovered");
  evidence.scienceEventsAfter = await scienceEvents(page, run);
  assert.deepEqual(evidence.scienceEventsAfter, evidence.scienceEventsBefore,
    "A visible retry or held-response recovery started a new scientific calculation");
  return evidence;
}
async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const scriptBytes = fs.readFileSync(__filename);
  fs.writeFileSync(path.join(input.artifacts, "harness-source.cjs"), scriptBytes);
  const evidence = { mode: input.mode, ledgerMode: ledger.ledgerMode(input), status: "running",
    harnessSha256: sha(scriptBytes), ledgerHelperSha256: ledger.helperSha256(),
    fixtureFiles: Object.fromEntries(["receptor", "sdf", "sidecar", "mapping", "ligand"]
      .filter(key => input[key]).map(key => [key, { name: path.basename(input[key]),
        sha256: sha(fs.readFileSync(input[key])), provenance: ledger.provenanceLabel(path.basename(input[key])) }])),
    variantsManifest: input.variants ? ledger.fileDigest(path.join(input.variants, "m11-invalid-cases.json")) : null,
    expectCapability: input.expectCapability, fixtureLabel: input.fixtureLabel,
    buildId: ledger.buildId(), startedAt: new Date().toISOString() };
  let session = null;
  const network = [];
  let failure = null;
  try {
    session = await launchOffscreen(input);
    const { page, app, artifacts } = session;
    page.on("response", response => {
      if (/\/api\/runs\//.test(response.url())) network.push({ url: response.url(), status: response.status(),
        method: response.request().method() });
    });
    if (["create", "empty", "prepare-only"].includes(input.mode)) await runCreate(session, input, evidence);
    else if (input.mode === "job-controls") await runJobControls(session, input, evidence);
    else if (input.mode === "running-cancel") await runRunningCancel(session, input, evidence);
    else if (input.mode === "detect-controls") await runDetectControls(session, input, evidence);
    else if (input.mode === "retry-failed") await runRetryFailed(session, input, evidence);
    else if (input.mode === "attach") await runAttach(session, input, evidence);
    else if (["reopen", "reopen-complete", "restrictions", "replay"].includes(input.mode)) await runReopen(session, input, evidence);
    else if (input.mode === "faults") await runFaults(session, input, evidence);
    else if (input.mode === "capability") await runCapability(session, input, evidence);
    else if (input.mode === "invalid-inputs") await runInvalidInputs(session, input, evidence);
    else if (input.mode === "invalid-attach") await runInvalidAttach(session, input, evidence);
    else throw new Error(`${input.mode} control case is inventoried but has no runner`);
    if (input.expectCapability && input.mode !== "capability")
      evidence.capabilityState = await capabilityState(page, input.expectCapability, (await chemical(page)) !== null);
    const finalFrame = await capture(app, page, artifacts, "final");
    evidence.finalImage = await imageNonblank(finalFrame.screenshot);
    evidence.finalNative = await chemical(page);
    if (input.mode === "reopen-complete") {
      const forbidden = network.filter(item => item.method === "POST" &&
        /\/(chemical\/imports|chemical\/preview|jobs|commands)(\/|\?|$)/.test(item.url));
      assert.deepEqual(forbidden, [], "Reopened completion silently submitted a new chemical job");
      evidence.completedExisting.scientificJobPosts = forbidden;
    }
    if (["replay", "reopen"].includes(input.mode)) {
      const forbidden = network.filter(item => item.method === "POST" &&
        /\/(chemical\/imports|chemical\/preview|jobs|method_reports|commands)(\/|\?|$)/.test(item.url));
      assert.deepEqual(forbidden, [], `${input.mode} issued scientific/import/report creation POSTs`);
    }
    evidence.offscreen = await ledger.offscreenProof(app, page);
    assert.equal(evidence.offscreen.nonLoopbackRequests, 0, "Renderer attempted a non-loopback request");
    evidence.status = "observed_unreviewed";
  } catch (error) {
    failure = error;
    evidence.status = "failed"; evidence.error = String(error.stack ?? error);
    if (session) {
      try { evidence.failedFrame = await capture(session.app, session.page, session.artifacts, "failure"); }
      catch (captureError) { evidence.captureError = String(captureError); }
      if (!evidence.offscreen) try { evidence.offscreen = await ledger.offscreenProof(session.app, session.page); }
      catch (proofError) { evidence.offscreenError = String(proofError); }
    }
  } finally {
    evidence.network = network;
    evidence.finishedAt = new Date().toISOString();
    fs.writeFileSync(path.join(input.artifacts, "chemical-evidence.json"), JSON.stringify(evidence, null, 2));
    ledger.writeRow(input, evidence);
    if (session) await session.close();
  }
  if (failure) throw failure;
}
if (require.main === module) main().catch(error => { process.stderr.write(`${error.stack ?? error}\n`); process.exitCode = 1; });
module.exports = { options, main };
