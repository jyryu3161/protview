const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

function load(filename, dependencies = {}) {
  const source = fs.readFileSync(path.join(__dirname, `../src/lib/${filename}.ts`), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const moduleObject = { exports: {} };
  vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports,
    require: name => dependencies[name] ?? require(name) });
  return moduleObject.exports;
}
const comparison = load("comparison");
const { exactChemicalRow, validateChemicalCatalog, chemicalAnnotationForRow,
  chemicalApprovalRequired, previewMatchesRequest, canonicalChemicalElement,
  canHydrateChemicalJobs, chemicalJobActionCurrent, chemicalCanCancel, declaredTerminalNames,
  completedChemicalResultHandles, linkedChemicalJobs, waitForChemicalCameraSettle, settleChemicalFocus,
  chemicalFocusSettleTimeoutMs, chemicalFocusTimeoutMessage } =
  load("chemical", { "./comparison": comparison });
const { chemicalFailureDetails } = load("chemical", { "./comparison": comparison });
const { collectChemicalAtomCatalog } = load("chemical", { "./comparison": comparison });

const source = "obj://run_one/chemical_structure/abc";
const residue = (chain, seq, resname) => ({ model_number: 2, chain_auth: chain,
  chain_label: chain === "L" ? null : "Axp", seq_auth: seq, seq_label: chain === "L" ? null : seq,
  icode: chain === "A" ? "A" : "", resname });
const atom = (site, chain, seq, name, element) => ({ structure_handle: source,
  residue: residue(chain, seq, chain === "L" ? "LIG" : "ASN"),
  atom_name: name, altloc: "", element, site_index: site });
const donor = atom(1, "L", 501, "N1", "N");
const hydrogen = atom(2, "L", 501, "H1", "H");
const acceptor = atom(3, "A", 12, "O", "O");
const row = { row_id: "r1", category: "HBDonor", backend_category: "HBDonor",
  ligand_atoms: [donor, hydrogen], receptor_atoms: [acceptor],
  roles: { donor, hydrogen, acceptor },
  role_coordinates_A: { donor: [0, 0, 0], hydrogen: [1, 0, 0], acceptor: [2.5, 1.5, 0] },
  engine_role_coordinates_A: { donor: [0, 0, 0], hydrogen: [1, 0, 0], acceptor: [2.5, 1.5, 0] },
  native_parent_indices: { ligand: [0, 1], protein: [2] },
  native_within_residue_indices: { ligand: [0, 1], protein: [1] },
  distance_A: Math.hypot(2.5, 1.5), distance_roles: ["donor", "acceptor"],
  DHA_angle_deg: 135, native_metadata: { distance: Math.hypot(2.5, 1.5), DHA_angle: 135 } };

test("validated chemical failure presents exact full source refs and zero-based SDF indices", () => {
  const failedResidue = { model_number: 2, chain_auth: "A", chain_label: null,
    seq_auth: 42, seq_label: null, icode: "B", resname: "HIS" };
  const failedAtom = { ...acceptor, residue: failedResidue, atom_name: "ND1",
    altloc: "A", site_index: 7 };
  assert.deepEqual(Array.from(chemicalFailureDetails({ error: "input_invalid", message: "bad graph",
    reason_code: "histidine_ring_graph", source_residues: [failedResidue],
    source_atoms: [failedAtom], sdf_atom_indices: [0, 12] })), [
    "reason_code histidine_ring_graph",
    "source residue: model 2, auth A/42 insertion B, label null/null, HIS",
    `source atom: model 2, auth A/42 insertion B, label null/null, HIS, atom ND1, altloc A, element O, site 7, structure ${source}`,
    "SDF atom index (zero-based): 0", "SDF atom index (zero-based): 12",
  ]);
  assert.deepEqual(Array.from(chemicalFailureDetails({ error: "fatal", message: "unknown" })), []);
});

test("chemical row keeps the exact D/H/A source identities and endpoint meaning", () => {
  assert.equal(exactChemicalRow(row, source), true);
  const presentation = chemicalAnnotationForRow(row, source);
  assert.equal(presentation.distance.label, "D···A");
  assert.equal(presentation.distance.first.site_index, 1);
  assert.equal(presentation.distance.second.site_index, 3);
  assert.equal(presentation.angle.hydrogen.site_index, 2);
  assert.equal(presentation.angle.value_deg, 135);
  assert.equal(presentation.sourceHandle, source);
});

test("chemical rows reject wrong source, missing hydrogen and roles absent from native matched atoms", () => {
  assert.equal(exactChemicalRow(row, "obj://run_other/chemical_structure/def"), false);
  assert.equal(exactChemicalRow({ ...row, roles: { donor, hydrogen: atom(99, "L", 501, "H99", "H"), acceptor } }, source), false);
  assert.equal(exactChemicalRow({ ...row, DHA_angle_deg: null }, source), false);
  assert.equal(exactChemicalRow({ ...row, category: "Invented" }, source), false);
});

test("non-hydrogen roles cannot be described as D···A or a DHA angle", () => {
  const hydrophobic = { ...row, category: "Hydrophobic", roles: { ligand_site: donor, receptor_site: acceptor },
    distance_roles: ["ligand_site", "receptor_site"], DHA_angle_deg: null };
  assert.equal(exactChemicalRow(hydrophobic, source), true);
  const presentation = chemicalAnnotationForRow(hydrophobic, source);
  assert.equal(presentation.distance.label, "ligand_site···receptor_site");
  assert.equal(presentation.angle, undefined);
});

test("chemical catalog admission requires exact served-byte SHA, model, complete unique sites and indices", () => {
  const view = { handle: source, viewer_source_sha256: "a".repeat(64), model_number: 2 };
  const catalog = { structure_handle: source, viewer_source_sha256: view.viewer_source_sha256,
    model_number: 2, total: 3, rows: [donor, hydrogen, acceptor].map((ref, viewer_source_index) =>
      ({ ref, viewer_source_index, coordinate_A: [viewer_source_index, 0, 0], protein: viewer_source_index === 2 })) };
  assert.equal(validateChemicalCatalog(view, catalog), true);
  assert.equal(validateChemicalCatalog(view, { ...catalog, viewer_source_sha256: "b".repeat(64) }), false);
  assert.equal(validateChemicalCatalog(view, { ...catalog, model_number: 1 }), false);
  assert.equal(validateChemicalCatalog(view, { ...catalog, rows: [catalog.rows[0], catalog.rows[0], catalog.rows[2]] }), false);
  assert.equal(validateChemicalCatalog(view, { ...catalog, rows: catalog.rows.slice(0, 2) }), false);
});

test("M11 catalog collector requests bounded 1000-site pages and rejects gaps, duplicate refs and changing provenance", async () => {
  const rows = [donor, hydrogen, acceptor].map((ref, viewer_source_index) =>
    ({ ref: { ...ref, site_index: viewer_source_index }, viewer_source_index,
      coordinate_A: [viewer_source_index, 0, 0], protein: false }));
  const page = (offset, limit) => ({ schema: "atom_catalog@1", structure_handle: source,
    viewer_source_sha256: "a".repeat(64), model_number: 2, total: rows.length,
    offset, limit, rows: rows.slice(offset, offset + limit) });
  const requested = [];
  const combined = await collectChemicalAtomCatalog(source, async (offset, limit) => {
    requested.push([offset, limit]); return page(offset, limit);
  }, 2);
  assert.deepEqual(requested, [[0, 2], [2, 2]]);
  assert.deepEqual(Array.from(combined.rows, row => row.ref.site_index), [0, 1, 2]);
  await assert.rejects(collectChemicalAtomCatalog(source, async (offset, limit) =>
    offset ? { ...page(offset, limit), viewer_source_sha256: "b".repeat(64) } : page(offset, limit), 2), /SHA/);
  await assert.rejects(collectChemicalAtomCatalog(source, async (offset, limit) =>
    offset ? { ...page(offset, limit), rows: [{ ...rows[2], viewer_source_index: 1 }] } : page(offset, limit), 2), /식별자/);
  await assert.rejects(collectChemicalAtomCatalog(source, async (offset, limit) =>
    offset ? { ...page(offset, limit), rows: [{ ...rows[2], ref: donor }] } : page(offset, limit), 2), /중복/);
  await assert.rejects(collectChemicalAtomCatalog(source, async (offset, limit) =>
    offset ? { ...page(offset, limit), schema: "other@1" } : page(offset, limit), 2), /페이지/);
  await assert.rejects(collectChemicalAtomCatalog(source, async (offset, limit) =>
    offset ? { ...page(offset, limit), model_number: 1 } : page(offset, limit), 2), /모델/);
  await assert.rejects(collectChemicalAtomCatalog(source, async () => page(0, 2), 1001), /크기/);
});

test("only a typed supported expensive gate opens M11 job approval", () => {
  assert.equal(chemicalApprovalRequired(409,
    { gate: "expensive_first_call", tool: "prepare_chemical_structure" }, "prepare"), true);
  assert.equal(chemicalApprovalRequired(409,
    { gate: "expensive_first_call", tool: "compute_chemical_interactions" }, "detect"), true);
  for (const invalid of [undefined, { gate: "", tool: "prepare_chemical_structure" },
    { gate: "expensive_first_call", tool: "compute_chemical_interactions" }])
    assert.equal(chemicalApprovalRequired(409, invalid, "prepare"), false);
  assert.equal(chemicalApprovalRequired(503,
    { gate: "expensive_first_call", tool: "prepare_chemical_structure" }, "prepare"), false);
});

test("attach mapping and acknowledgement edits revoke a formerly ready preview", () => {
  const args = { schema: "chemical_prepare_request@1", mode: "attach_existing",
    mapping: [{ sdf_atom_index: 0, source_atom: donor }],
    acknowledgement: { supplied_graph_complete: true } };
  const admitted = JSON.stringify(args);
  assert.equal(previewMatchesRequest(admitted, args), true);
  assert.equal(previewMatchesRequest(admitted,
    { ...args, mapping: [{ sdf_atom_index: 0, source_atom: acceptor }] }), false);
  assert.equal(previewMatchesRequest(admitted,
    { ...args, acknowledgement: { supplied_graph_complete: false } }), false);
  assert.equal(previewMatchesRequest("", args), false);
});

test("new chemical lane matches Cl and Br without rewriting source AtomRefs", () => {
  assert.equal(canonicalChemicalElement("Cl"), "CL");
  assert.equal(canonicalChemicalElement(" BR "), "BR");
  const sourceRef = atom(8, "L", 501, "CL1", "CL");
  assert.equal(sourceRef.element, "CL");
  assert.equal(canonicalChemicalElement(sourceRef.element), canonicalChemicalElement("Cl"));
});

test("old jobs hydration cannot replace a newly selected preparation or a different run", () => {
  const old = [{ run_id: "run_a", protocol_id: "prolif_prepare_v1" }];
  assert.equal(canHydrateChemicalJobs("run_a", "run_a", 0, 0, old), true);
  assert.equal(canHydrateChemicalJobs("run_a", "run_a", 0, 1, old), false);
  assert.equal(canHydrateChemicalJobs("run_a", "run_b", 0, 0, old), false);
  assert.equal(canHydrateChemicalJobs("run_a", "run_a", 0, 0,
    [{ run_id: "run_b", protocol_id: "prolif_prepare_v1" }]), false);
});

test("saved chemical results require their own successful terminal, not candidate object creation", () => {
  const candidate = "obj://run_a/chemical_interaction_set/candidate";
  const admitted = "obj://run_a/chemical_interaction_set/admitted";
  const events = [
    { type: "object_created", handle: candidate, kind: "chemical_interaction_set" },
    { type: "job_terminal", status: "cancelled", output_handles: [candidate] },
    { type: "object_created", handle: admitted, kind: "chemical_interaction_set" },
    { type: "job_terminal", status: "done", output_handles: [admitted] },
    { type: "job_terminal", status: "done", output_handles: [admitted] },
    { type: "job_terminal", status: "done", output_handles: ["obj://run_a/chemical_graph/other"] },
  ];
  assert.deepEqual(Array.from(completedChemicalResultHandles(events)), [admitted]);
  assert.deepEqual(Array.from(completedChemicalResultHandles(events.slice(0, 3))), []);
});

test("newest-first chemical history links a selected result to its producer graph and preparation", () => {
  const job = (job_id, protocol_id, status, input_handles, output_handles) =>
    ({ job_id, run_id: "run_a", protocol_id, status, input_handles, output_handles });
  const jobs = [
    job("detect_new", "prolif_detect_v1", "done", ["graph_new"], ["result_new"]),
    job("prepare_new", "prolif_prepare_v1", "done", ["raw_new"], ["manifest_new", "source_new", "graph_new"]),
    job("detect_old", "prolif_detect_v1", "done", ["graph_old"], ["result_old"]),
    job("prepare_old", "prolif_prepare_v1", "done", ["raw_old"], ["manifest_old", "source_old", "graph_old"]),
  ];
  assert.deepEqual(Object.fromEntries(Object.entries(linkedChemicalJobs(jobs)).map(([key, value]) =>
    [key, value?.job_id])), { prepare: "prepare_new", detect: "detect_new" });
  assert.deepEqual(Object.fromEntries(Object.entries(linkedChemicalJobs(jobs, "result_old")).map(([key, value]) =>
    [key, value?.job_id])), { prepare: "prepare_old", detect: "detect_old" });
  assert.deepEqual(Object.fromEntries(Object.entries(linkedChemicalJobs(jobs, "candidate")).map(([key, value]) =>
    [key, value?.job_id])), { prepare: undefined, detect: undefined });
  assert.deepEqual(Object.fromEntries(Object.entries(linkedChemicalJobs(jobs, "result_old", "graph_new"))
    .map(([key, value]) => [key, value?.job_id])), { prepare: undefined, detect: undefined },
  "An explicit result cannot be rebound to a different graph's preparation");
});

test("default reopen keeps the newest pending preparation instead of following an older done detection", () => {
  const job = (job_id, protocol_id, status, input_handles, output_handles) =>
    ({ job_id, run_id: "run_a", protocol_id, status, input_handles, output_handles });
  const oldDetect = job("detect_old", "prolif_detect_v1", "done", ["graph_old"], ["result_old"]);
  const oldPrepare = job("prepare_old", "prolif_prepare_v1", "done", ["raw_old"],
    ["manifest_old", "source_old", "graph_old"]);
  for (const status of ["queued", "claimed", "failed"]) {
    const newest = job(`prepare_${status}`, "prolif_prepare_v1", status, ["raw_new"], []);
    const jobs = [newest, oldDetect, oldPrepare];
    const selected = linkedChemicalJobs(jobs);
    assert.equal(selected.prepare?.job_id, newest.job_id);
    assert.equal(selected.detect, null);
    const historical = linkedChemicalJobs(jobs, "result_old");
    assert.equal(historical.prepare?.job_id, "prepare_old");
    assert.equal(historical.detect?.job_id, "detect_old");
    assert.equal(canHydrateChemicalJobs("run_a", "run_a", 4, 5, [oldDetect, oldPrepare]), false,
      "A held old jobs GET must not replace the newly submitted preparation");
  }
  const newestDone = job("prepare_new", "prolif_prepare_v1", "done", ["raw_new"],
    ["manifest_new", "source_new", "graph_new"]);
  assert.equal(linkedChemicalJobs([newestDone, oldDetect, oldPrepare]).prepare?.job_id, "prepare_new");
  assert.equal(linkedChemicalJobs([newestDone, oldDetect, oldPrepare]).detect, null,
    "An older completed detection must not attach to a newly prepared graph");
  const newestQueuedDetect = job("detect_new", "prolif_detect_v1", "queued", ["graph_new"], []);
  assert.equal(linkedChemicalJobs([newestQueuedDetect, newestDone, oldDetect, oldPrepare]).detect?.job_id,
    "detect_new", "The newest preparation may show only its graph-compatible detection");
});

const savedScene = load("saved-scene");

/** Frame-driven fake of the native camera probe used by the chemical row focus path. */
function fakeCamera(script) {
  const state = { frame: 0, now: 0 };
  const probe = () => script(state.frame);
  const nextFrame = async () => { state.frame += 1; state.now += 16; };
  return { state, probe, nextFrame, now: () => state.now };
}
const calm = (camera, applied = true) => ({ inTransition: false, camera, applied });
const moving = camera => ({ inTransition: true, camera, applied: true });

test("chemical focus default settle bound is three seconds and tunable", () => {
  assert.equal(chemicalFocusSettleTimeoutMs, 3000);
  assert.match(chemicalFocusTimeoutMessage, /다시/, "Timeout must tell the user the focus is retryable");
});

test("chemical focus waits through transition, deferred apply and orbit inertia before settling", async () => {
  // Frames 1-3: orbit inertia changes the camera; 4-6: transition; 7-9: calm but
  // the deferred Mol* reset is still pending (not applied); afterwards applied and stable.
  const fake = fakeCamera(frame => frame <= 3 ? calm(`orbit${frame}`) : frame <= 6 ? moving(`t${frame}`) :
    frame <= 9 ? calm("old", false) : calm("focused"));
  const settled = await waitForChemicalCameraSettle(fake.probe, fake.nextFrame, () => true, fake.now,
    fake.now() + chemicalFocusSettleTimeoutMs);
  assert.equal(settled, "focused");
  assert.ok(fake.state.frame >= 12, "Two consecutive unchanged calm frames after apply are required");
});

test("chemical focus settle timeout is a retryable error and never reports applied", async () => {
  const fake = fakeCamera(() => moving("spin"));
  await assert.rejects(waitForChemicalCameraSettle(fake.probe, fake.nextFrame, () => true, fake.now,
    fake.now() + 100), error => error.message === chemicalFocusTimeoutMessage);
  const pending = fakeCamera(() => calm("old", false));
  await assert.rejects(waitForChemicalCameraSettle(pending.probe, pending.nextFrame, () => true, pending.now,
    pending.now() + 100), error => error.message === chemicalFocusTimeoutMessage,
  "A calm camera that never reached the requested focus is not applied");
  let readbacks = 0;
  const drifting = fakeCamera(frame => calm(`drift${Math.floor(frame / 4)}`));
  await assert.rejects(settleChemicalFocus(drifting.probe, drifting.nextFrame, () => true, drifting.now,
    drifting.now() + 400, async () => { readbacks += 1; drifting.state.frame += 1; return readbacks; }),
  error => error.message === chemicalFocusTimeoutMessage);
});

test("chemical focus readback retries when the camera moves during readback instead of failing", async () => {
  let moved = false;
  const fake = fakeCamera(() => calm(moved ? "focused-after" : "focused"));
  const result = await settleChemicalFocus(fake.probe, fake.nextFrame, () => true, fake.now,
    fake.now() + chemicalFocusSettleTimeoutMs, async () => { const first = !moved; moved = true; return first; });
  assert.deepEqual({ ...result }, { value: false, camera: "focused-after" },
    "Readback taken while the camera moved is discarded and repeated after the next settle");
});

test("real user actions during the settle wait revoke the pending chemical focus", async () => {
  const binding = { sessionId: "", clientId: "c", generation: 2, sourceHandle: "obj://run/chemical_structure/a",
    catalogHash: "h", actionRevision: 0 };
  for (const action of ["pointer", "empty-click", "rotation", "rebind-different", "new-row"]) {
    const live = { token: 4, revision: 9, intent: 1 };
    const expected = { ...live };
    const fake = fakeCamera(frame => {
      if (frame === 3) {
        if (action === "rebind-different")
          live.token = savedScene.nativeTokenAfterBinding(live.token, binding, { ...binding, generation: 3 });
        else if (action === "new-row") live.intent += 1;
        else live.revision += 1; // trusted pointerdown/wheel or native selection change
      }
      return moving("spin");
    });
    const current = () => comparison.nativeIntentCurrent(expected, live);
    assert.equal(await waitForChemicalCameraSettle(fake.probe, fake.nextFrame, current, fake.now,
      fake.now() + chemicalFocusSettleTimeoutMs), null, action);
    let readback = false;
    assert.equal(await settleChemicalFocus(fakeCamera(() => moving("spin")).probe, fake.nextFrame, current,
      fake.now, fake.now() + chemicalFocusSettleTimeoutMs, async () => { readback = true; }), null, action);
    assert.equal(readback, false, `${action} must not read back a revoked focus`);
  }
});

test("identical six-field republish and catalog observation do not revoke the pending chemical focus", async () => {
  const binding = { sessionId: "", clientId: "c", generation: 2, sourceHandle: "obj://run/chemical_structure/a",
    catalogHash: "h", actionRevision: 0 };
  const live = { token: 4, revision: 9, intent: 1 };
  const expected = { ...live };
  let catalogObservations = 0;
  const fake = fakeCamera(frame => {
    if (frame === 2 || frame === 5) live.token = savedScene.nativeTokenAfterBinding(live.token, binding, { ...binding });
    if (frame === 4) catalogObservations += 1; // catalog readiness is observed without a manual revision
    return frame <= 6 ? moving("spin") : calm("focused");
  });
  const current = () => comparison.nativeIntentCurrent(expected, live);
  const result = await settleChemicalFocus(fake.probe, fake.nextFrame, current, fake.now,
    fake.now() + chemicalFocusSettleTimeoutMs, async () => "selection");
  assert.equal(catalogObservations, 1);
  assert.deepEqual({ ...result }, { value: "selection", camera: "focused" });
});

test("running cancellation remains available during held Start and invalidates its late response", () => {
  const job = { run_id: "run_a", job_id: "job_a", protocol_id: "prolif_prepare_v1" };
  const startTicket = 7;
  assert.equal(chemicalCanCancel("running", false, false), true);
  assert.equal(chemicalCanCancel("claimed", false, false), true);
  assert.equal(chemicalCanCancel("running", true, false), false);
  assert.equal(chemicalCanCancel("running", false, true), false);
  assert.equal(chemicalCanCancel("done", false, false), false);
  assert.equal(chemicalJobActionCurrent(startTicket, startTicket + 1,
    job.run_id, job.job_id, job.protocol_id, job), false,
  "Cancel increments ownership, so a late Start completion cannot overwrite it");
  assert.equal(chemicalJobActionCurrent(startTicket + 1, startTicket + 1,
    job.run_id, job.job_id, job.protocol_id, job), true);
  assert.equal(chemicalJobActionCurrent(startTicket + 1, startTicket + 1,
    job.run_id, job.job_id, job.protocol_id, { ...job, job_id: "other" }), false);
});

test("custom terminal declaration resolves exact existing names and rejects ambiguous sites", () => {
  const residueRef = residue("A", 12, "ASN");
  const atoms = [atom(10, "A", 12, "CAY", "C"), atom(11, "A", 12, "OY", "O")];
  assert.deepEqual(Array.from(declaredTerminalNames(residueRef, "CAY, OY", atoms)), ["CAY", "OY"]);
  assert.throws(() => declaredTerminalNames(residueRef, "CAY, CAY", atoms), /중복/);
  assert.throws(() => declaredTerminalNames(residueRef, "CAY, ZZ", atoms), /ZZ/);
  assert.throws(() => declaredTerminalNames(residueRef, "OY", [...atoms, atom(12, "A", 12, "OY", "O")]), /모호/);
});

const { readChemicalAtomCatalog, chemicalStartProgressed, chemicalSubmitStatus } =
  load("chemical", { "./comparison": comparison });

test("chemical source catalog gives every page its own read deadline instead of one shared budget", async () => {
  // Release3 attach: one 30 s signal spanned view + all catalog pages + graph + manifest, so a
  // slow but healthy backend timed out the whole display. Virtual clock: 3 pages × 30 ms, 50 ms deadline.
  const rows = [0, 1, 2].map(viewer_source_index => ({ viewer_source_index,
    ref: { ...donor, atom_name: `A${viewer_source_index}`, site_index: viewer_source_index },
    coordinate_A: [viewer_source_index, 0, 0], protein: false }));
  const page = (offset, limit) => ({ schema: "atom_catalog@1", structure_handle: source,
    viewer_source_sha256: "a".repeat(64), model_number: 2, total: rows.length,
    offset, limit, rows: rows.slice(offset, offset + limit) });
  let now = 0;
  const signals = [];
  const newSignal = () => { const signal = { deadline: now + 50 }; signals.push(signal); return signal; };
  const fetchPage = async (offset, limit, signal) => {
    now += 30;
    if (now > signal.deadline) throw new Error("signal timed out");
    return page(offset, limit);
  };
  const combined = await readChemicalAtomCatalog(source, fetchPage, newSignal, 1);
  assert.deepEqual(Array.from(combined.rows, row => row.ref.site_index), [0, 1, 2]);
  assert.equal(signals.length, 3, "each catalog page must receive a fresh deadline");
  now = 0;
  const shared = newSignal();
  await assert.rejects(collectChemicalAtomCatalog(source, (offset, limit) => fetchPage(offset, limit, shared), 1),
    /signal timed out/, "the former shared budget reproduces the release3 display timeout");
});

test("a lost Start response adopts durable progress but keeps a still-queued job a failure", () => {
  const job = { run_id: "run_a", job_id: "job_a", protocol_id: "prolif_detect_v1", status: "queued",
    attempt_ordinal: 0 };
  for (const status of ["running", "done", "failed", "interrupted", "cancelled"])
    assert.equal(chemicalStartProgressed(job, { ...job, status }), true, status);
  assert.equal(chemicalStartProgressed(job, { ...job, status: "queued" }), false);
  assert.equal(chemicalStartProgressed(job, { ...job, status: "claimed" }), false);
  assert.equal(chemicalStartProgressed(job, { ...job, status: "queued", attempt_ordinal: 1 }), true);
  assert.equal(chemicalStartProgressed(job, { ...job, job_id: "job_b", status: "done" }), false);
  assert.equal(chemicalStartProgressed(job, { ...job, run_id: "run_b", status: "done" }), false);
  assert.equal(chemicalStartProgressed(job, { ...job, protocol_id: "prolif_prepare_v1", status: "done" }), false);
});

test("an idempotent submission that returns an existing job is not announced as newly saved", () => {
  assert.match(chemicalSubmitStatus("detect", { job_id: "job_a", status: "queued" }), /저장되었습니다/);
  const reused = chemicalSubmitStatus("detect", { job_id: "job_a", status: "done" });
  assert.match(reused, /기존 작업/);
  assert.match(reused, /job_a/);
  assert.match(reused, /done/);
  assert.match(chemicalSubmitStatus("prepare", { job_id: "job_p", status: "queued" }), /준비 작업이 저장되었습니다/);
  assert.match(chemicalSubmitStatus("prepare", { job_id: "job_p", status: "failed" }), /기존 작업.*failed/);
});
