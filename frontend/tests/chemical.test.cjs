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
  completedChemicalResultHandles, linkedChemicalJobs, waitForChemicalCameraSettle } =
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

test("chemical focus waits past a delayed native transition and revokes on manual intent", async () => {
  let frames = 0;
  const next = async () => { frames += 1; };
  const settled = await waitForChemicalCameraSettle(() => frames < 4, next, () => true,
    () => frames * 16, 500);
  assert.equal(settled, true);
  assert.ok(frames >= 5);
  frames = 0;
  const revoked = await waitForChemicalCameraSettle(() => true, next, () => frames < 3,
    () => frames * 16, 500);
  assert.equal(revoked, false);
  await assert.rejects(waitForChemicalCameraSettle(() => true, next, () => true,
    () => frames++ * 16, 32), /정착 시간이 초과/);
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
