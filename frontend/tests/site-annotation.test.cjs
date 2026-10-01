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
const lib = load("site-annotation", { "./comparison": load("comparison"), "./numbering": load("numbering"),
  "./event-model": load("event-model") });
const plain = value => JSON.parse(JSON.stringify(value));

const SRC = "obj://r1/prepared_structure/p";
const OTHER = "obj://r1/structure/s";
const res = (seq, over = {}) => ({ model_number: 1, chain_auth: "A", chain_label: "A", seq_auth: seq, seq_label: seq,
  icode: "", resname: "GLU", ...over });
const LIG = { model_number: 1, chain_auth: "A", chain_label: "C", seq_auth: 400, seq_label: null, icode: "", resname: "ADP" };
const byType = (contact, polar, hydro) => ({ contact, polar_contact: polar, hydrophobic_contact: hydro });
const site = (over = {}) => ({ klifs_index: 46, klifs_label: "hinge.46", status: "annotated", absent_reason: null,
  residue: res(211), map_row_index: 5, residue_match: true, klifs_match: "contiguous", display_label: "Glu211 (hinge.46)",
  contact: { assessed: true, not_assessed_reason: null,
    by_type: byType({ computed: true, count: 0 }, { computed: true, count: 1 }, { computed: false, count: null }),
    min_distance_A: 2.935, min_distance_row_index: 3,
    polar_pairs: [{ contact_row_index: 3, protein_atom: "O", ligand_atom: "N6", distance_A: 2.935 }] }, ...over });
const absent = reason => ({ klifs_index: 17, klifs_label: "III.17", status: "absent", absent_reason: reason, residue: null,
  map_row_index: null, residue_match: null, klifs_match: null, display_label: null, contact: null });
const annotation = (over = {}) => ({ schema: "reference_site_annotation@1", method_version: "mw.site_annotation/v1",
  site_set: { id: "kinase_key_sites@1", sites: [] }, numbering_map: "m1", snapshot_set_hash: "h",
  structure: { handle: SRC, structure_kind: "prepared_structure", model_number: 1 },
  contacts: { handle: "c1", ligand: LIG, cutoff_A: 4, types: ["contact", "polar_contact"] },
  groups: [{ chain_auth: "A", accession: "O14965", klifs_applied: true, klifs_absent_reason: null, sites: [site(), absent("pocket_gap")] }],
  other_contact_residues: [], null_result: false, limitations: [], ...over });

test("distance text is two-decimal ROUND_HALF_UP on the decimal string", () => {
  assert.equal(lib.distanceText(2.93), "2.93 Å");
  assert.equal(lib.distanceText(2.935), "2.94 Å");       // binary 2.93499.. but decimal string "2.935"
  assert.equal(lib.distanceText(2.9349999), "2.93 Å");
  assert.equal(lib.distanceText(3), "3.00 Å");
  assert.equal(lib.distanceText(2.995), "3.00 Å");
  assert.equal(lib.distanceText(0.004), "0.00 Å");
  assert.equal(lib.decimalHalfUp(-1.005, 2), "-1.01");
  assert.equal(lib.decimalHalfUp(1e-7, 2), "1e-7");
  assert.equal(lib.decimalHalfUp(97.25, 1), "97.3");
});

test("reason text is 한국어 (code) for site, group and contact reasons; unknown codes as is", () => {
  for (const code of ["klifs_not_applied", "pocket_gap", "region_unresolved", "no_mapped_residue", "no_mapped_accession",
    "residue_not_checked_by_contact_method", "accession_not_in_klifs", "klifs_pocket_empty", "klifs_multiple_entries",
    "uniprot_sequence_unavailable"]) {
    assert.match(lib.siteReasonText(code), new RegExp(`^[^()]*[가-힣][^()]* \\(${code}\\)$`), code);
  }
  assert.equal(lib.siteReasonText("pocket_gap"), "KLIFS 포켓 서열에서 이 자리가 gap (pocket_gap)");
  assert.equal(lib.siteReasonText("brand_new"), "brand_new");
  assert.equal(lib.siteReasonText("__proto__"), "__proto__");
  assert.equal(lib.siteStatusText(absent("region_unresolved")), "없음: 이 자리의 KLIFS 구역을 정하지 못함 (region_unresolved)");
  assert.equal(lib.siteStatusText(site()), "주석됨");
});

test("counts keep 0, not computed, not assessed and no contact result apart", () => {
  const a = annotation();
  const s = site();
  assert.equal(lib.contactCountText(a, s, "contact"), "0");
  assert.equal(lib.contactCountText(a, s, "polar_contact"), "1");
  assert.equal(lib.contactCountText(a, s, "hydrophobic_contact"), "계산하지 않음");
  const hetatm = site({ residue: res(212, { resname: "MSE" }), contact: { assessed: false,
    not_assessed_reason: "residue_not_checked_by_contact_method",
    by_type: byType({ computed: true, count: null }, { computed: true, count: null }, { computed: false, count: null }),
    min_distance_A: null, min_distance_row_index: null, polar_pairs: null } });
  for (const type of lib.CONTACT_TYPES) assert.equal(lib.contactCountText(a, hetatm, type), "접촉 도구가 검사하지 않는 잔기");
  assert.equal(lib.minDistanceText(a, hetatm), "접촉 도구가 검사하지 않는 잔기");
  const none = annotation({ contacts: null, other_contact_residues: null });
  const bare = site({ contact: null });
  assert.equal(lib.contactCountText(none, bare, "contact"), "접촉 결과 없음");
  assert.equal(lib.minDistanceText(none, bare), "접촉 결과 없음");
  assert.equal(lib.contactCountText(a, absent("pocket_gap"), "contact"), "—");
  assert.equal(lib.minDistanceText(a, s), "2.94 Å");
  // zero-row contact result: computed types 0, distance null (never "0.00 Å")
  const zero = site({ contact: { assessed: true, not_assessed_reason: null,
    by_type: byType({ computed: true, count: 0 }, { computed: true, count: 0 }, { computed: true, count: 0 }),
    min_distance_A: null, min_distance_row_index: null, polar_pairs: [] } });
  assert.equal(lib.contactCountText(a, zero, "polar_contact"), "0");
  assert.equal(lib.minDistanceText(a, zero), "계산한 종류·cutoff 안 접촉 없음");
});

test("panel has five distinct states", () => {
  const cap = { available: true, reason: null };
  assert.equal(lib.annotationPanelState({ sourceKind: "openmm_minimized_structure", capability: cap }).reason,
    "최소화 구조에는 번호 대응이 없어 주석할 수 없음");
  assert.equal(lib.annotationPanelState({ sourceKind: "chemical_structure", capability: cap }).state, "unavailable");
  assert.equal(lib.annotationPanelState({ sourceKind: null, capability: cap }).state, "unavailable");
  assert.equal(lib.annotationPanelState({ sourceKind: "structure", capability: null }).state, "unavailable");
  assert.equal(lib.annotationPanelState({ sourceKind: "structure" }).state, "loading");
  assert.equal(lib.annotationPanelState({ sourceKind: "structure", capability: cap, loading: true }).state, "loading");
  assert.deepEqual(plain(lib.annotationPanelState({ sourceKind: "structure", capability: cap, error: "boom", loading: true })),
    { state: "failure", message: "boom" });
  assert.equal(lib.annotationPanelState({ sourceKind: "prepared_structure", capability: cap }).state, "ready");
  assert.equal(lib.annotationPanelState({ sourceKind: "prepared_structure", capability: cap, annotation: annotation() }).state, "ready");
  const nullResult = annotation({ null_result: true, groups: [{ chain_auth: "A", accession: null, klifs_applied: false,
    klifs_absent_reason: "no_mapped_accession", sites: [absent("klifs_not_applied")] }] });
  assert.deepEqual(plain(lib.annotationPanelState({ sourceKind: "prepared_structure", capability: cap, annotation: nullResult })),
    { state: "scientific_null", message: "이 대응에는 주요 부위에 번호가 붙은 잔기가 없습니다" });
  // inconsistent null_result is a failure, not a silent ready
  assert.equal(lib.annotationPanelState({ sourceKind: "prepared_structure", capability: cap,
    annotation: annotation({ null_result: true }) }).state, "failure");
});

test("lists are filtered to the displayed structure handle", () => {
  const maps = [{ handle: "m1", structure: SRC }, { handle: "m2", structure: OTHER }];
  assert.deepEqual(plain(lib.mapsForSource(maps, SRC)).map(r => r.handle), ["m1"]);
  assert.deepEqual(plain(lib.mapsForSource(maps, null)), []);
  const rows = [{ handle: "a1", structure: OTHER }, { handle: "a2", structure: SRC }];
  assert.deepEqual(plain(lib.annotationsForSource(rows, SRC)).map(r => r.handle), ["a2"]);
  const out = (handle, structure, extra = {}) => ({ handle, kind: "interaction_set", schema: "interaction_set@1",
    summary: { structure, ligand: LIG, cutoff_A: 4, types: ["polar_contact"], n_edges: 3 }, preview: [], ...extra });
  const events = [
    { seq: 1, type: "tool_called", tool: "compute_interactions", key: "k1", call_id: "c1", args: {}, decided_by: "human", attempt: 1, version: "1" },
    { seq: 2, type: "tool_succeeded", tool: "compute_interactions", key: "k1", call_id: "c1", output: out("i1", SRC) },
    { seq: 3, type: "tool_succeeded", tool: "compute_interactions", key: "k2", call_id: "c2", output: out("i2", OTHER) },
    { seq: 4, type: "tool_succeeded", tool: "compute_interface_sasa", key: "k3", call_id: "c3",
      output: { handle: "x", kind: "interface_sasa", schema: "interface_sasa@1", summary: { structure: SRC }, preview: [] } },
    { seq: 5, type: "tool_succeeded", tool: "compute_interactions", key: "k1", call_id: "c4", cached: true, output: out("i1", SRC) },
    { seq: 6, type: "tool_succeeded", tool: "compute_interactions", key: "k5", call_id: "c5",
      output: out("i3", SRC, { null_result: true, summary: { structure: SRC, ligand: res(401, { resname: "PO4" }), cutoff_A: 4.5,
        types: ["contact"], n_edges: 0 } }) },
  ];
  const sets = plain(lib.contactSetsForSource(events, SRC));
  assert.deepEqual(sets.map(s => [s.handle, s.cutoff_A, s.null_result]), [["i1", 4, false], ["i3", 4.5, true]]);
  assert.deepEqual(sets[0].ligand, LIG);
  assert.deepEqual(plain(lib.contactSetsForSource(events, null)), []);
});

test("contact result is never auto-selected, even when only one exists", () => {
  const maps = [{ handle: "m1", structure: SRC }];
  const sets = [{ handle: "i1", structure: SRC }];
  assert.deepEqual(plain(lib.INITIAL_CONTACT_CHOICE), { kind: "unset" });
  let check = lib.createAnnotationArgs({ sourceHandle: SRC, mapHandle: "m1", contactChoice: lib.INITIAL_CONTACT_CHOICE, maps, contactSets: sets });
  assert.equal(check.ok, false);
  assert.match(check.errors.join(" "), /접촉 결과 없이/);
  check = lib.createAnnotationArgs({ sourceHandle: SRC, mapHandle: "m1", contactChoice: { kind: "none" }, maps, contactSets: sets });
  assert.deepEqual(plain(check), { ok: true, args: { numbering_map: "m1", contacts: null } });
  check = lib.createAnnotationArgs({ sourceHandle: SRC, mapHandle: "m1", contactChoice: { kind: "set", handle: "i1" }, maps, contactSets: sets });
  assert.deepEqual(plain(check), { ok: true, args: { numbering_map: "m1", contacts: "i1" } });
  // map of another structure / no map at all / contact set of another structure
  assert.equal(lib.createAnnotationArgs({ sourceHandle: SRC, mapHandle: null, contactChoice: { kind: "none" }, maps, contactSets: sets }).ok, false);
  check = lib.createAnnotationArgs({ sourceHandle: OTHER, mapHandle: "m1", contactChoice: { kind: "none" }, maps, contactSets: sets });
  assert.deepEqual(plain(check.errors), ["이 구조로 지식 탭에서 번호 대응을 먼저 만드세요"]);
  assert.equal(lib.createAnnotationArgs({ sourceHandle: SRC, mapHandle: "m1", contactChoice: { kind: "set", handle: "i9" }, maps, contactSets: sets }).ok, false);
  // a vanished choice resets to unset, never to another option
  assert.deepEqual(plain(lib.reconcileContactChoice({ kind: "set", handle: "gone" }, sets)), { kind: "unset" });
  assert.deepEqual(plain(lib.reconcileContactChoice({ kind: "set", handle: "i1" }, sets)), { kind: "set", handle: "i1" });
  assert.deepEqual(plain(lib.reconcileContactChoice({ kind: "none" }, [])), { kind: "none" });
  assert.equal(lib.reconcileMapChoice("gone", maps), null);
  assert.equal(lib.reconcileMapChoice(null, maps), null);
  assert.equal(lib.annotationMatchesSource(annotation(), SRC), true);
  assert.equal(lib.annotationMatchesSource(annotation(), OTHER), false);
});

test("exclusivity: pocket overlay, comparison, minimized/chemical source, M8 blocked, M9 allowed", () => {
  const gates = input => plain(lib.annotationGates({ sourceKind: "prepared_structure", annotationOn: false,
    pocketOverlayActive: false, comparisonActive: false, ...input }));
  assert.deepEqual(gates({}), { annotation: null, pocketOverlay: null, m8: null, m9: null });
  assert.match(gates({ pocketOverlayActive: true }).annotation, /포켓 오버레이/);
  assert.match(gates({ comparisonActive: true }).annotation, /비교/);
  assert.equal(gates({ sourceKind: "openmm_minimized_structure" }).annotation, "최소화 구조에는 번호 대응이 없어 주석할 수 없음");
  assert.match(gates({ sourceKind: "chemical_structure" }).annotation, /화학 구조/);
  const on = gates({ annotationOn: true });
  assert.match(on.pocketOverlay, /참조 주석/);
  assert.match(on.m8, /자연어 뷰어 요청/);
  assert.equal(on.m9, null);
});

test("viewer_scene@2 restore is refused while pocket overlay or comparison is active", () => {
  const v2 = { schema: "viewer_scene@2", annotation: { handle: "a1", legend: true } };
  const v1 = { schema: "viewer_scene@1" };
  const ok = { pocketOverlayActive: false, comparisonActive: false };
  assert.deepEqual(plain(lib.sceneRestoreDecision(v2, ok)), { allowed: true, reason: null });
  assert.equal(lib.sceneRestoreDecision(v2, { ...ok, pocketOverlayActive: true }).allowed, false);
  assert.match(lib.sceneRestoreDecision(v2, { ...ok, comparisonActive: true }).reason, /비교/);
  assert.equal(lib.sceneRestoreDecision(v1, { pocketOverlayActive: true, comparisonActive: true }).allowed, true);
  assert.deepEqual(plain(lib.sceneAnnotation(v2)), { handle: "a1", legend: true });
  assert.equal(lib.sceneAnnotation(v1), null);
});

test("late responses need the same run, source and request sequence", () => {
  const stamp = { runId: "r1", sourceHandle: SRC, seq: 3 };
  assert.equal(lib.annotationResponseCurrent(stamp, { ...stamp }), true);
  assert.equal(lib.annotationResponseCurrent(stamp, { ...stamp, runId: "r2" }), false);
  assert.equal(lib.annotationResponseCurrent(stamp, { ...stamp, sourceHandle: OTHER }), false);
  assert.equal(lib.annotationResponseCurrent(stamp, { ...stamp, seq: 4 }), false);
  assert.equal(lib.annotationResponseCurrent({ ...stamp, runId: null }, { ...stamp, runId: null }), false);
});

test("save bodies: @1 unchanged byte for byte, @2 adds annotation / legend_composited", () => {
  const scene = { client_instance_id: "c", viewer_session_id: "v", scene_generation: 1, action_revision: 2, request_id: "q",
    schema: "viewer_scene@1", name: "n", structure_handle: SRC, selection: null, representation: "cartoon", camera: {}, theme: "dark" };
  const before = JSON.stringify(scene);
  const same = lib.sceneSaveBody(scene, null);
  assert.equal(same, scene);
  assert.equal(JSON.stringify(same), before);
  const v2 = lib.sceneSaveBody(scene, { handle: "a1", legend: false, extra: 1 });
  assert.equal(v2.schema, "viewer_scene@2");
  assert.deepEqual(plain(v2.annotation), { handle: "a1", legend: false });
  assert.equal(JSON.stringify(scene), before);   // input not mutated
  const figure = { ...scene, schema: "viewer_figure@1", scene_handle: "s1", png_base64: "AA==" };
  delete figure.name;
  const fBefore = JSON.stringify(figure);
  assert.equal(lib.figureSaveBody(figure, "viewer_scene@1", true), figure);
  assert.equal(JSON.stringify(lib.figureSaveBody(figure, "viewer_scene@1", true)), fBefore);
  const f2 = lib.figureSaveBody(figure, "viewer_scene@2", true);
  assert.equal(f2.schema, "viewer_figure@2");
  assert.equal(f2.legend_composited, true);
  assert.equal(lib.legendShouldComposite(true, 2), true);
  assert.equal(lib.legendShouldComposite(true, 0), false);
  assert.equal(lib.legendShouldComposite(false, 3), false);
  assert.equal(lib.FIGURE_LEGEND_TEXT, "점선: 기하 극성 접촉(원자 거리), 수소결합 판정 아님");
});

test("figure legend wraps at the same font size and is refused when it cannot fit", () => {
  const measure = text => Array.from(text).length * 10;   // 10 px per character
  const text = lib.FIGURE_LEGEND_TEXT;
  assert.deepEqual(plain(lib.wrapLegendText(text, 10000, measure)), [text]);
  const wrapped = lib.wrapLegendText(text, 120, measure);
  assert.ok(wrapped.length > 1);
  for (const line of wrapped) assert.ok(measure(line) <= 120, line);
  assert.equal(wrapped.join(" "), text);   // only spaces become line breaks when every word fits
  // a word wider than the line is broken by characters, nothing is dropped or squeezed
  const narrow = lib.wrapLegendText(text, 40, measure);
  for (const line of narrow) assert.ok(measure(line) <= 40, line);
  assert.equal(narrow.join("").replace(/ /g, ""), text.replace(/ /g, ""));
  assert.equal(lib.wrapLegendText(text, 9, measure), null);
  assert.equal(lib.wrapLegendText(text, 0, measure), null);
  assert.match(lib.FIGURE_LEGEND_NO_FIT, /범례/);
});

const atomRow = (residue, atom, index, over = {}) => ({ ref: { structure_handle: SRC, residue, atom_name: atom, altloc: "",
  element: atom[0], site_index: index }, coordinate_A: [0, 0, 0], protein: true, viewer_source_index: index, ...over });
const catalog = rows => ({ schema: "atom_catalog@1", structure_handle: SRC, viewer_source_sha256: "x", model_number: 1,
  total: rows.length, offset: 0, limit: 1000, rows });

test("atom resolution needs exactly one atom by 7 fields + atom name", () => {
  const rows = [atomRow(res(211), "O", 0), atomRow(res(211), "N", 1),
    atomRow(res(211, { chain_label: null }), "O", 2),               // label differs -> different residue
    atomRow(res(211, { icode: "A" }), "O", 3),                      // insertion code differs
    atomRow(res(211, { model_number: 2 }), "O", 4),                 // other model
    atomRow(res(212), "OG", 5), atomRow(res(212), "OG", 6, { ref: { structure_handle: SRC, residue: res(212),
      atom_name: "OG", altloc: "B", element: "O", site_index: 6 } }),
    atomRow(LIG, "N6", 7)];
  const cat = catalog(rows);
  const one = lib.resolveAtom(cat, res(211), "O");
  assert.equal(one.drawable, true);
  assert.equal(one.atom.viewer_source_index, 0);
  assert.equal(lib.resolveAtom(cat, res(211, { chain_label: null }), "O").atom.viewer_source_index, 2);
  assert.equal(lib.resolveAtom(cat, res(211, { icode: "A" }), "O").atom.viewer_source_index, 3);
  assert.deepEqual(plain(lib.resolveAtom(cat, res(211), "CB")), { drawable: false, reason: "none" });
  assert.deepEqual(plain(lib.resolveAtom(cat, res(212), "OG")), { drawable: false, reason: "ambiguous" });
  assert.deepEqual(plain(lib.resolveAtom(cat, res(213), "O")), { drawable: false, reason: "none" });
  assert.throws(() => lib.resolveAtom({ ...cat, total: 99 }, res(211), "O"), /Incomplete/);

  const pairs = [{ contact_row_index: 1, protein_atom: "O", ligand_atom: "N6", distance_A: 2.935 },
    { contact_row_index: 2, protein_atom: "N", ligand_atom: "O9", distance_A: 3.1 }];
  const a = annotation({ groups: [{ chain_auth: "A", accession: "P", klifs_applied: true, klifs_absent_reason: null, sites: [
    site({ contact: { ...site().contact, polar_pairs: pairs } }),
    site({ klifs_index: 47, residue: res(212), display_label: "Glu212 (hinge.47)",
      contact: { ...site().contact, polar_pairs: [{ contact_row_index: 3, protein_atom: "OG", ligand_atom: "N6", distance_A: 3 }] } }),
    absent("pocket_gap")] }] });
  const result = lib.polarPairsForDrawing(a, cat);
  assert.deepEqual(plain(result.drawn.map(d => [d.pair.contact_row_index, d.protein.viewer_source_index, d.ligand.viewer_source_index, d.label])),
    [[1, 0, 7, "2.94 Å"]]);
  assert.deepEqual(plain(result.undrawn.map(u => [u.pair.contact_row_index, u.side, u.reason, u.text])),
    [[2, "ligand", "none", "그리지 못함(원자 대응 없음)"], [3, "protein", "ambiguous", "그리지 못함(원자 대응 모호)"]]);
  // no contacts or another structure's catalog: nothing drawn
  assert.deepEqual(plain(lib.polarPairsForDrawing(annotation({ contacts: null }), cat)), { drawn: [], undrawn: [] });
  assert.deepEqual(plain(lib.polarPairsForDrawing(a, { ...cat, structure_handle: OTHER })), { drawn: [], undrawn: [] });
});

test("site regions follow the fixed kinase_key_sites@1 indexes", () => {
  assert.deepEqual([17, 24, 45, 46, 47, 48, 80, 81, 82, 83, 1].map(lib.siteRegion),
    ["III", "αC", "GK", "hinge", "hinge", "hinge", "xDFG", "xDFG", "xDFG", "xDFG", null]);
});

test("every site region has its own colour token", () => {
  assert.deepEqual(Object.keys(lib.SITE_REGION_TOKEN).sort(), ["GK", "III", "hinge", "xDFG", "αC"].sort());
  assert.equal(new Set(Object.values(lib.SITE_REGION_TOKEN)).size, 5);
  for (const index of [17, 24, 45, 46, 47, 48, 80, 81, 82, 83]) assert.ok(lib.SITE_REGION_TOKEN[lib.siteRegion(index)]);
});

test("viewer request key follows run, annotation, source and legend", () => {
  const shown = { runId: "r1", sourceHandle: SRC, handle: "a1", annotation: annotation(), legend: true };
  const request = lib.siteAnnotationRequest(shown);
  assert.equal(request.visible, true);
  assert.equal(request.legend, true);
  assert.equal(request.handle, "a1");
  assert.equal(request.sourceHandle, SRC);
  assert.equal(request.annotation, shown.annotation);
  const keys = new Set([request, lib.siteAnnotationRequest({ ...shown, legend: false }),
    lib.siteAnnotationRequest({ ...shown, runId: "r2" }), lib.siteAnnotationRequest({ ...shown, handle: "a2" }),
    lib.siteAnnotationRequest({ ...shown, sourceHandle: OTHER })].map(item => item.key));
  assert.equal(keys.size, 5);
  assert.equal(lib.siteAnnotationRequest({ ...shown }).key, request.key);
});

test("a shown annotation turns off on run or source change, comparison, or an unsupported source", () => {
  const shown = { runId: "r1", sourceHandle: SRC, annotation: annotation() };
  const live = { runId: "r1", sourceHandle: SRC, sourceKind: "prepared_structure", comparisonActive: false };
  assert.equal(lib.annotationShownCurrent(shown, live), true);
  assert.equal(lib.annotationShownCurrent(shown, { ...live, runId: "r2" }), false);
  assert.equal(lib.annotationShownCurrent(shown, { ...live, sourceHandle: OTHER }), false);
  assert.equal(lib.annotationShownCurrent(shown, { ...live, sourceHandle: null, sourceKind: null }), false);
  assert.equal(lib.annotationShownCurrent(shown, { ...live, comparisonActive: true }), false);
  assert.equal(lib.annotationShownCurrent(shown, { ...live, sourceKind: "openmm_minimized_structure" }), false);
  assert.equal(lib.annotationShownCurrent(shown, { ...live, sourceKind: "chemical_structure" }), false);
  // the stored annotation of another structure is never drawn on this source
  assert.equal(lib.annotationShownCurrent({ ...shown, annotation: annotation({ structure: { handle: OTHER,
    structure_kind: "structure", model_number: 1 } }) }, live), false);
});

test("host accepts show requests only for its run, displayed source and without a block", () => {
  const request = { runId: "r1", sourceHandle: SRC, annotation: annotation() };
  const host = { runId: "r1", sourceHandle: SRC, blocked: null };
  assert.equal(lib.annotationShowAccepted(request, "r1", host), true);
  assert.equal(lib.annotationShowAccepted(null, "r1", host), true);
  assert.equal(lib.annotationShowAccepted(null, "r0", host), false, "late off of an older run");
  assert.equal(lib.annotationShowAccepted(request, "r0", host), false);
  assert.equal(lib.annotationShowAccepted({ ...request, runId: "r0" }, "r1", host), false);
  assert.equal(lib.annotationShowAccepted(request, "r1", { ...host, sourceHandle: OTHER }), false, "late on of an older source");
  assert.equal(lib.annotationShowAccepted(request, "r1", { ...host, blocked: lib.POCKET_OVERLAY_BLOCKS_ANNOTATION }), false);
  assert.equal(lib.annotationShowAccepted({ ...request, annotation: annotation({ structure: { handle: OTHER,
    structure_kind: "structure", model_number: 1 } }) }, "r1", host), false);
  assert.notEqual(lib.SCIENTIFIC_NULL_LABEL, "정상적인 빈 결과 (scientific_null)");
});
