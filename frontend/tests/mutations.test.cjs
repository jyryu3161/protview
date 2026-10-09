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
  vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, URLSearchParams,
    require: name => dependencies[name] ?? require(name) });
  return moduleObject.exports;
}
const eventModel = load("event-model");
const siteAnnotation = load("site-annotation", { "./comparison": load("comparison"), "./numbering": load("numbering"),
  "./event-model": eventModel });
const lib = load("mutations", { "./event-model": eventModel, "./site-annotation": siteAnnotation });
const reportLibrary = load("report-library");
const plain = value => JSON.parse(JSON.stringify(value));

// ---- closed sets, limits and fixed wording are read from backend/mw/mutation_constants.py itself ----
const constantsSource = fs.readFileSync(path.join(__dirname, "../../backend/mw/mutation_constants.py"), "utf8");
function backendTuple(name) {
  const match = new RegExp(`^${name} = \\(([^)]*)\\)`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map(item => item[1]);
}
function backendValue(name) {
  const match = new RegExp(`^${name} = ([^#\\n]+)`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return match[1].trim();
}
function backendLimitations() {
  const start = constantsSource.indexOf("LIMITATIONS = (");
  const end = constantsSource.indexOf("\n)\n", start);
  const block = constantsSource.slice(start + "LIMITATIONS = (".length, end).replace(/"\s*\n\s*"/g, "");
  return [...block.matchAll(/"([^"]+)"/g)].map(item => item[1]);
}
/** `NAME = "..."` or a parenthesized concatenation `NAME = ("a"\n "b")`. */
function backendSentence(name, source = constantsSource) {
  const single = new RegExp(`^${name} = "([^"]*)"`, "m").exec(source);
  if (single) return single[1];
  const match = new RegExp(`^${name} = \\(([\\s\\S]*?)\\)\\n`, "m").exec(source);
  assert.ok(match, `backend constant ${name} not found`);
  return [...match[1].matchAll(/"([^"]*)"/g)].map(item => item[1]).join("");
}
// M26 screen notes UK2 / UK3 of backend/mw/reaction_knowledge_constants.py (SCREEN_NOTES), read as written
const reactionConstants = fs.readFileSync(path.join(__dirname, "../../backend/mw/reaction_knowledge_constants.py"), "utf8");
function reactionNote(key) {
  const block = reactionConstants.slice(reactionConstants.indexOf("SCREEN_NOTES = {"));
  const match = new RegExp(`"${key}": (\\((?:\\s*"[^"]*")+\\s*\\)|"[^"]*")`).exec(block);
  assert.ok(match, `SCREEN_NOTES ${key} not found`);
  return [...match[1].matchAll(/"([^"]*)"/g)].map(item => item[1]).join("");
}

const S = "obj://r1/prepared_structure/s1";
const S2 = "obj://r1/prepared_structure/s2";
const res = (chain, seq, resname, over = {}) => ({ model_number: 1, chain_auth: chain, chain_label: chain, seq_auth: seq,
  seq_label: seq, icode: "", resname, ...over });
const LIG = res("A", 101, "LIG", { chain_label: "C", seq_label: null });
const LIG2 = res("A", 102, "LIG", { chain_label: "D", seq_label: null });
const A10 = res("A", 10, "ILE", { icode: "A", seq_label: null });
const CC11 = res("CC", 11, "ALA", { chain_label: "E" });
const A5 = res("A", 5, "CYS");
const pocketRow = (handle, source, nullResult = false) => ({ handle, source_handle: source, source_kind: "prepared_structure",
  model_number: 1, selected_chains: ["A"], total_count: 3, null_result: nullResult, job_id: "j", created_seq: 3, published_seq: 4 });
const mapRow = (handle, structure, seq = 5) => ({ handle, structure, structure_kind: "prepared_structure", model_number: 1,
  pdb_id: null, chains: ["A"], cross_checked_chains: [], set_hash: "h", counts: { mapped: 1, unmapped: 0, conflict: 0 },
  row_count: 1, null_result: false, created_seq: seq, stale_snapshot: false, chain_details: [] });
const annRow = (handle, structure, map, seq) => ({ handle, structure, structure_kind: "prepared_structure", model_number: 1,
  numbering_map: map, contacts: null, ligand: null, set_hash: "h", groups: [], counts: { annotated: 1, absent: 0 },
  null_result: false, created_seq: seq, stale_snapshot: false });
const OPTIONS = {
  pocketSets: [pocketRow("P1", S), pocketRow("P0", S, true), pocketRow("P2", S2)],
  maps: [mapRow("M1", S), mapRow("M2", S), mapRow("M3", S2)],
  annotations: [annRow("N1", S, "M1", 10), annRow("N2", S, "M2", 20), annRow("N3", S2, "M3", 30)],
  ligands: [LIG, LIG2],
};
const draft = over => ({ ...lib.initialMutationDraft(S), ...over });
const errorsOf = over => { const out = lib.mutationRequestArgs(draft(over), OPTIONS); assert.equal(out.ok, false); return plain(out.errors); };

const counts = over => ({ positions: 4, candidate_positions: 2, excluded_positions: 2, released_positions: 1, candidates: 38,
  exclusion_reason_counts: { non_standard_residue: 0, user_protected: 1, klifs_key_site: 0, metal_contact: 1,
    disulfide_cys: 1, no_allowed_alternative: 0 }, source_counts: { pocket: 0, ligand_shell: 3, user: 2 }, ...over });
const CHECKED = { user_list: { status: "checked", protected: 1, released: 2 },
  klifs_key_sites: { status: "checked", reason: null, annotation: "N1", annotated_sites: 9, absent_sites: 1 },
  metal_contact: { status: "checked", threshold_A: 3.0, metal_residues: 1, metal_names: ["ZN"] },
  disulfide: { status: "checked", threshold_A: 2.5, pairs: 1 },
  catalytic_residue_database: { status: "not_available", reason: "not_implemented" } };
const NOT_CHECKED = { ...CHECKED, klifs_key_sites: { status: "not_checked", reason: "annotation_not_given", annotation: null,
  annotated_sites: null, absent_sites: null } };
// ---- M26 v2 catalytic checks (synthetic; handles are placeholders) ----
const RK = "obj://r1/reaction_knowledge/rk1";
const RK2 = "obj://r1/reaction_knowledge/rk2";
const RK3 = "obj://r1/reaction_knowledge/rk3";
const catItem = (chain, reason, residue, listed = {}) => ({ chain_auth: chain, mcsa_id: 282, residue_index: 3, reason,
  residue, listed: { chain_name: chain, resid: 101, auth_resid: 99, code: "Asp", ...listed } });
const V2_NOT_GIVEN = { status: "not_checked", reason: "annotation_not_given", annotation: null };
const V2_CHECKED = { status: "checked", reason: null, annotation: RK, covered_chains: ["A"], uncovered_chains: [],
  matched_rows: 4, conflict_rows: 1, unmatched_rows: 1,
  conflicts: [catItem("A", "residue_name_differs", res("A", 99, "GLU"))],
  unmatched: [catItem("A", "residue_not_in_structure", null, { resid: null, auth_resid: 250, code: "His" })] };
const V2_NONE_COVERED = { status: "not_checked", reason: "chains_not_covered", annotation: RK, covered_chains: [],
  uncovered_chains: [{ chain_auth: "A", coverage: "pdb_not_in_snapshot" }], matched_rows: 0, conflict_rows: 0,
  unmatched_rows: 0, conflicts: [], unmatched: [] };
const V2_PARTIAL = { status: "not_checked", reason: "chains_not_covered", annotation: RK, covered_chains: ["A"],
  uncovered_chains: [{ chain_auth: "B", coverage: "chain_not_listed" }, { chain_auth: "C", coverage: "not_in_annotation" },
    { chain_auth: "D", coverage: "not_checked" }], matched_rows: 2, conflict_rows: 0, unmatched_rows: 0, conflicts: [],
  unmatched: [] };
const rkItem = (handle, structure, over = {}) => ({ handle, structure_handle: structure, structure_kind: "prepared_structure",
  pdb_id: "1S9I", chain_count: 2, covered_chain_count: 1, mcsa_rows: { matched: 4, unmatched: 1, conflict: 1 },
  uniprot_feature_count: null, null_result: false, set_hash: "a".repeat(64), active: true, ...over });
// newest first, as GET /runs/{id}/reaction_knowledge answers
const RK_RESULTS = [rkItem(RK3, S2), rkItem(RK2, S), rkItem(RK, S)];

test("closed sets, limits, defaults and fixed sentences equal backend/mw/mutation_constants.py", () => {
  assert.deepEqual(plain(lib.SOURCE_KINDS), backendTuple("SOURCE_KINDS"));
  assert.deepEqual(plain(lib.PROTECTION_REASONS), backendTuple("PROTECTION_REASONS"));
  assert.deepEqual(plain(lib.EXCLUSION_REASONS), backendTuple("EXCLUSION_REASONS"));
  assert.deepEqual(plain(lib.POSITION_STATUSES), backendTuple("POSITION_STATUSES"));
  assert.deepEqual(plain(lib.PROTECTION_CHECK_KEYS), backendTuple("PROTECTION_CHECK_KEYS"));
  assert.deepEqual(plain(lib.ADMISSION_REASON_CODES), backendTuple("ADMISSION_REASON_CODES"));
  // M26 v2: the catalytic reason closes the protection reasons; v1 keeps its six exclusion reasons
  assert.deepEqual(plain(lib.PROTECTION_REASONS_V2), backendTuple("PROTECTION_REASONS_V2"));
  assert.deepEqual(plain(lib.EXCLUSION_REASONS_V2), backendTuple("EXCLUSION_REASONS_V2"));
  assert.equal(lib.EXCLUSION_REASONS.length, 6);
  assert.equal(lib.EXCLUSION_REASONS_V2.length, 7);
  assert.deepEqual(plain(lib.EXCLUSION_REASONS_V2.filter(reason => reason !== "catalytic_residue")), plain(lib.EXCLUSION_REASONS));
  assert.equal(lib.ADMISSION_REASON_CODES.indexOf("catalytic_annotation_invalid"),
    lib.ADMISSION_REASON_CODES.indexOf("annotation_invalid") + 1);
  assert.deepEqual(plain(lib.CATALYTIC_UNCOVERED_COVERAGE), backendTuple("CATALYTIC_UNCOVERED_COVERAGE"));
  assert.deepEqual(plain(Object.keys(lib.UNCOVERED_COVERAGE_LABEL)), backendTuple("CATALYTIC_UNCOVERED_COVERAGE"));
  assert.deepEqual(plain(Object.keys(lib.CATALYTIC_ROW_REASON_LABEL).sort()),
    [...backendTuple("CATALYTIC_CONFLICT_REASONS"), ...backendTuple("CATALYTIC_UNMATCHED_REASONS")].sort());
  assert.equal(lib.CATALYTIC_LIST_TOO_LONG, JSON.parse(backendValue("CATALYTIC_LIST_TOO_LONG")));
  assert.equal(lib.MAX_CATALYTIC_LIST, Number(backendValue("MAX_CATALYTIC_LIST")));
  assert.equal(lib.CATALYTIC_REASON, JSON.parse(backendValue("CATALYTIC_REASON")));
  assert.equal(lib.CATALYTIC_NOT_GIVEN_REASON, JSON.parse(backendValue("CATALYTIC_NOT_GIVEN_REASON")));
  assert.equal(lib.CATALYTIC_NOT_COVERED_REASON, JSON.parse(backendValue("CATALYTIC_NOT_COVERED_REASON")));
  assert.equal(lib.CATALYTIC_NOT_AVAILABLE_REASON, JSON.parse(backendValue("CATALYTIC_NOT_AVAILABLE_REASON")));
  assert.deepEqual(plain(lib.CATALYTIC_STATUSES), [JSON.parse(backendValue("CHECKED")), JSON.parse(backendValue("NOT_CHECKED")),
    JSON.parse(backendValue("NOT_AVAILABLE"))]);
  assert.equal(lib.METHOD_VERSION, JSON.parse(backendValue("METHOD_VERSION")));
  assert.equal(lib.METHOD_VERSION_V2, JSON.parse(backendValue("METHOD_VERSION_V2")));
  // the third limitation sentence of v2 (spec 8.4), verbatim; v1 keeps its own third sentence
  assert.equal(lib.MUTATION_LIMITATION_3_CHECKED, backendSentence("LIMITATION_3_CHECKED"));
  assert.equal(lib.MUTATION_LIMITATION_3_NOT_CHECKED, backendSentence("LIMITATION_3_NOT_CHECKED"));
  assert.equal(lib.MUTATION_LIMITATION_3_CHECKED,
    "보호 잔기는 사용자 지정·KLIFS 주요 부위·금속 근접·이황화 결합·M-CSA 촉매 잔기 주석 기준으로만 판정했다.");
  assert.equal(lib.MUTATION_LIMITATION_3_NOT_CHECKED, "보호 잔기는 사용자 지정·KLIFS 주요 부위·금속 근접·이황화 결합 " +
    "기준으로만 판정했고 M-CSA 촉매 잔기 주석은 주지 않았거나 일부 체인만 다뤘다(검사하지 않은 부분은 '없음'이 아니다).");
  // UK2 / UK3 (M26 SCREEN_NOTES) verbatim
  assert.equal(lib.CATALYTIC_NOT_CHECKED_BADGE, reactionNote("UK2"));
  assert.equal(lib.UNIPROT_SITES_NOTE, reactionNote("UK3"));
  assert.equal(lib.UNIPROT_SITES_NOTE, "UniProt 부위 정보는 지식 탭에서만 보이며 보호에 쓰지 않음.");
  assert.equal(lib.TOO_MANY_POSITIONS, JSON.parse(backendValue("TOO_MANY_POSITIONS")));
  assert.equal(lib.MUTATION_TOOL, JSON.parse(backendValue("TOOL")));
  assert.equal(lib.ONE_LETTER_ORDER, JSON.parse(backendValue("ONE_LETTER_ORDER")));
  assert.equal(lib.MAX_POSITIONS, Number(backendValue("MAX_POSITIONS")));
  assert.equal(lib.MAX_LIST, Number(backendValue("MAX_LIST")));
  assert.equal(lib.LIGAND_SHELL_RADIUS_DEFAULT_A, Number(backendValue("LIGAND_SHELL_RADIUS_DEFAULT_A")));
  assert.equal(lib.METAL_CONTACT_DEFAULT_A, Number(backendValue("METAL_CONTACT_DEFAULT_A")));
  assert.equal(lib.DISULFIDE_SG_A, Number(backendValue("DISULFIDE_SG_A")));
  assert.deepEqual(plain(lib.LIGAND_SHELL_RADIUS_RANGE_A), JSON.parse(backendValue("LIGAND_SHELL_RADIUS_RANGE_A").replace("(", "[").replace(")", "]")));
  assert.deepEqual(plain(lib.METAL_CONTACT_RANGE_A), JSON.parse(backendValue("METAL_CONTACT_RANGE_A").replace("(", "[").replace(")", "]")));
  assert.deepEqual(plain(lib.MUTATION_LIMITATIONS), backendLimitations());
  assert.equal(lib.MUTATION_LIMITATIONS.length, 5);
  assert.equal(Object.keys(lib.ONE_LETTER_RESNAME).join(""), lib.ONE_LETTER_ORDER);
  // read page limits of backend/mw/mutation_reads.py
  const reads = fs.readFileSync(path.join(__dirname, "../../backend/mw/mutation_reads.py"), "utf8");
  assert.match(reads, new RegExp(`^LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX = 50, ${lib.LIST_LIMIT_MAX}$`, "m"));
  assert.match(reads, new RegExp(`^POSITION_LIMIT_DEFAULT, POSITION_LIMIT_MAX = ${lib.POSITION_LIMIT_DEFAULT}, ${lib.POSITION_LIMIT_MAX}$`, "m"));
  assert.match(reads, new RegExp(`^CANDIDATE_LIMIT_DEFAULT, CANDIDATE_LIMIT_MAX = ${lib.CANDIDATE_LIMIT_DEFAULT}, ${lib.CANDIDATE_LIMIT_MAX}$`, "m"));
  assert.deepEqual(plain(lib.POSITION_SORTS), [...reads.matchAll(/^SORTS = \(([^)]*)\)/gm)][0][1].match(/"[^"]+"/g).map(JSON.parse));
});

test("every code the panel can show has a Korean name shown as \"한국어 (code)\"; unknown codes as is", () => {
  const codes = [...lib.ADMISSION_REASON_CODES, lib.TOO_MANY_POSITIONS, ...lib.EXCLUSION_REASONS_V2,
    "annotation_not_given", "not_implemented", "method_evidence_invalid", lib.CATALYTIC_LIST_TOO_LONG,
    lib.CATALYTIC_NOT_COVERED_REASON];
  for (const code of codes) assert.match(lib.mutationReasonText(code), new RegExp(`^\\S.* \\(${code}\\)$`), code);
  assert.equal(lib.mutationReasonText("brand_new_code"), "brand_new_code");
  assert.equal(lib.mutationReasonText("toString"), "toString");
  for (const kind of lib.SOURCE_KINDS) assert.ok(lib.SOURCE_LABEL[kind]);
  for (const key of lib.PROTECTION_CHECK_KEYS) assert.ok(lib.PROTECTION_CHECK_LABEL[key]);
});

test("initial draft: no source on, radius 5, metal 3, all 20 residues allowed, no lists, no map/annotation", () => {
  const initial = plain(lib.initialMutationDraft(S));
  assert.equal(initial.structure, S);
  assert.equal(initial.pocketOn || initial.ligandShellOn || initial.userOn, false);
  assert.equal(initial.radiusText, "5");
  assert.equal(initial.metalText, "3");
  assert.equal(initial.allowed.join(""), "ACDEFGHIKLMNPQRSTVWY");
  assert.deepEqual([initial.residues, initial.protectedResidues, initial.releasedResidues], [[], [], []]);
  assert.deepEqual([initial.ligand, initial.numberingMap, initial.annotation, initial.catalyticAnnotation],
    [null, null, null, null]);
  assert.deepEqual(errorsOf({}), ["위치 출처(포켓 검출·리간드 껍질·직접 선택)를 하나 이상 켜고 위치를 정하세요."]);
});

test("request args: normalized order, 7 fields with null labels kept, off sources sent as null / []", () => {
  const out = plain(lib.mutationRequestArgs(draft({ pocketOn: true, pocketSet: "P1", pocketRanks: [3, 1],
    ligandShellOn: true, radiusText: "12", userOn: false, residues: [A10], ligand: { ...LIG, extra: 1 },
    allowed: ["W", "A", "C"], protectedResidues: [A5], releasedResidues: [CC11], metalText: "1.0",
    numberingMap: "M1", annotation: "N1" }), OPTIONS));
  assert.deepEqual(out, { ok: true, args: {
    structure: S,
    sources: { pocket: { pocket_set: "P1", ranks: [1, 3] }, ligand_shell: { radius_A: 12 }, residues: [] },
    ligand: LIG, allowed_residues: "ACW", protected_residues: [A5], released_residues: [CC11], metal_contact_A: 1,
    numbering_map: "M1", annotation: "N1", catalytic_annotation: null } });
  assert.equal(out.args.ligand.seq_label, null);
  const user = plain(lib.mutationRequestArgs(draft({ userOn: true, residues: [A10, CC11] }), OPTIONS));
  assert.deepEqual(user.args.sources, { pocket: null, ligand_shell: null, residues: [A10, CC11] });
  assert.equal(user.args.allowed_residues, "ACDEFGHIKLMNPQRSTVWY");
  assert.equal(user.args.metal_contact_A, 3);
  assert.equal(user.args.residues, undefined);
  assert.deepEqual(Object.keys(user.args), ["structure", "sources", "ligand", "allowed_residues", "protected_residues",
    "released_residues", "metal_contact_A", "numbering_map", "annotation", "catalytic_annotation"]);
  assert.equal(user.args.catalytic_annotation, null);
});

test("request checks: no source, structure, pocket choice of the same structure with pockets", () => {
  assert.ok(errorsOf({ structure: null, userOn: true, residues: [A10] }).includes("전처리 구조를 고르세요."));
  assert.equal(errorsOf({ userOn: true, residues: [] }).length, 1, "user on with no residue is no source");
  assert.deepEqual(errorsOf({ pocketOn: true }), ["포켓 결과를 고르세요.", "포켓 번호를 하나 이상 고르세요."]);
  assert.deepEqual(errorsOf({ pocketOn: true, pocketSet: "P2", pocketRanks: [1] }), ["고른 포켓 결과가 이 구조의 포켓 있는 결과가 아닙니다."]);
  assert.deepEqual(errorsOf({ pocketOn: true, pocketSet: "P0", pocketRanks: [1] }), ["고른 포켓 결과가 이 구조의 포켓 있는 결과가 아닙니다."]);
  assert.deepEqual(errorsOf({ pocketOn: true, pocketSet: "P1", pocketRanks: [1, 1] }), ["포켓 번호가 올바르지 않습니다."]);
  assert.deepEqual(errorsOf({ pocketOn: true, pocketSet: "P1", pocketRanks: [0] }), ["포켓 번호가 올바르지 않습니다."]);
  assert.equal(lib.mutationRequestArgs(draft({ pocketOn: true, pocketSet: "P1", pocketRanks: [2] }), OPTIONS).ok, true);
});

test("radius 1–12 and metal 1–5 (both ends inclusive, plain decimals only)", () => {
  const shell = radiusText => lib.mutationRequestArgs(draft({ ligandShellOn: true, ligand: LIG, radiusText }), OPTIONS);
  for (const ok of ["1", "1.0", "12", "12.0", "5", " 7.25 "]) assert.equal(shell(ok).ok, true, ok);
  for (const bad of ["0.99", "12.01", "", "0", "-5", "1e1", "NaN", "Infinity", "0x5", "5,0", "abc"]) {
    const out = plain(shell(bad));
    assert.equal(out.ok, false, bad);
    assert.deepEqual(out.errors, ["리간드 껍질 반경는 1.0–12.0 Å 사이의 숫자여야 합니다(양끝 포함)."]);
  }
  const metal = metalText => lib.mutationRequestArgs(draft({ userOn: true, residues: [A10], metalText }), OPTIONS);
  for (const ok of ["1", "5", "5.0", "3.25"]) assert.equal(metal(ok).ok, true, ok);
  for (const bad of ["0.5", "5.01", "", "1e0"]) assert.equal(metal(bad).ok, false, bad);
  // the radius is not checked while the ligand shell is off
  assert.equal(lib.mutationRequestArgs(draft({ userOn: true, residues: [A10], radiusText: "99" }), OPTIONS).ok, true);
});

test("allowed residues: empty, outside the 20 standard codes and duplicates are refused", () => {
  assert.deepEqual(plain(lib.allowedResiduesString([])), { ok: false, error: "허용 잔기를 하나 이상 고르세요." });
  assert.equal(lib.allowedResiduesString(["B"]).ok, false);
  assert.equal(lib.allowedResiduesString(["AC"]).ok, false);
  assert.equal(lib.allowedResiduesString(["a"]).ok, false);
  assert.deepEqual(plain(lib.allowedResiduesString(["A", "A"])), { ok: false, error: "허용 잔기에 같은 코드가 두 번 있습니다." });
  assert.deepEqual(plain(lib.allowedResiduesString(["Y", "G", "A"])), { ok: true, value: "AGY" });
  assert.ok(errorsOf({ userOn: true, residues: [A10], allowed: [] }).includes("허용 잔기를 하나 이상 고르세요."));
});

test("lists: at most 400, no duplicate in a list, no residue both protected and released", () => {
  const many = Array.from({ length: 401 }, (_, i) => res("A", i + 1, "ALA"));
  assert.ok(errorsOf({ userOn: true, residues: many }).includes("직접 고른 위치: 최대 400개까지 보낼 수 있습니다."));
  assert.ok(errorsOf({ userOn: true, residues: [A10], protectedResidues: many }).includes("보호 목록: 최대 400개까지 보낼 수 있습니다."));
  assert.equal(lib.mutationRequestArgs(draft({ userOn: true, residues: many.slice(0, 400) }), OPTIONS).ok, true);
  assert.ok(errorsOf({ userOn: true, residues: [A10, { ...A10 }] }).includes("직접 고른 위치에 같은 잔기가 두 번 있습니다."));
  // same auth numbers but another label is another residue (7-field identity)
  assert.equal(lib.mutationRequestArgs(draft({ userOn: true, residues: [A10, { ...A10, chain_label: "Z" }] }), OPTIONS).ok, true);
  assert.deepEqual(plain(lib.protectReleaseConflicts([A5, A10], [CC11, { ...A10 }])), [A10]);
  assert.deepEqual(plain(lib.protectReleaseConflicts([A5], [{ ...A5, seq_label: null }])), []);
  assert.deepEqual(errorsOf({ userOn: true, residues: [A10], protectedResidues: [A5], releasedResidues: [A5] }),
    ["같은 잔기를 보호와 해제에 모두 넣을 수 없습니다: CYS A:5"]);
  assert.deepEqual(plain(lib.toggleResidue(lib.toggleResidue([A5], A10), { ...A5 })), [A10]);
});

test("ligand shell requires a ligand; a ligand must be one of the structure's listed ligands", () => {
  assert.deepEqual(errorsOf({ ligandShellOn: true }), ["리간드 껍질을 쓰려면 리간드를 고르세요."]);
  assert.deepEqual(errorsOf({ userOn: true, residues: [A10], ligand: { ...LIG, seq_label: 1 } }),
    ["고른 리간드가 이 구조의 리간드 목록에 없습니다."]);
  const withLigand = plain(lib.mutationRequestArgs(draft({ userOn: true, residues: [A10], ligand: LIG2 }), OPTIONS));
  assert.deepEqual([withLigand.args.ligand, withLigand.args.sources.ligand_shell], [LIG2, null]);
  const list = { model_number: 1, residues: [{ ...A10, category: "polymer" }, { ...LIG, category: "nonpolymer" },
    { ...res("A", 300, "HOH"), category: "water" }, { ...res("B", 1, "GLY", { model_number: 2 }), category: "polymer" }],
  ligands: [{ ...LIG, model_number: undefined }] };
  assert.deepEqual(plain(lib.proteinResidueOptions(list)), [A10]);
  assert.deepEqual(plain(lib.ligandOptions(list)), [LIG]);
  assert.deepEqual(plain(lib.chainOptions([A10, CC11, A5])), ["A", "CC"]);
});

test("same structure only; newest annotation pre-selected together with the map it recorded", () => {
  assert.deepEqual(plain(lib.pocketSetsForStructure(OPTIONS.pocketSets, S).map(row => row.handle)), ["P1"]);
  assert.deepEqual(plain(lib.mapsForStructure(OPTIONS.maps, S).map(row => row.handle)), ["M1", "M2"]);
  assert.deepEqual(plain(lib.annotationsForStructure(OPTIONS.annotations, S2).map(row => row.handle)), ["N3"]);
  assert.deepEqual(plain(lib.mapsForStructure(OPTIONS.maps, null)), []);
  assert.deepEqual(plain(lib.preselectAnnotation(OPTIONS.annotations, OPTIONS.maps, S)), { annotation: "N2", numbering_map: "M2" });
  assert.deepEqual(plain(lib.preselectAnnotation([OPTIONS.annotations[0]], OPTIONS.maps, S)), { annotation: "N1", numbering_map: "M1" });
  // the recorded map is not among this structure's maps: the annotation alone is pre-selected
  assert.deepEqual(plain(lib.preselectAnnotation(OPTIONS.annotations, [OPTIONS.maps[0]], S)), { annotation: "N2", numbering_map: null });
  assert.deepEqual(plain(lib.preselectAnnotation([], OPTIONS.maps, S)), { annotation: null, numbering_map: null });
  assert.deepEqual(plain(lib.preselectAnnotation(OPTIONS.annotations, OPTIONS.maps, null)), { annotation: null, numbering_map: null });
  const next = plain(lib.draftForStructure(draft({ pocketSet: "P1", pocketRanks: [1], residues: [A10], ligand: LIG,
    protectedResidues: [A5], releasedResidues: [CC11], allowed: ["A"], radiusText: "7" }), S2, OPTIONS.annotations, OPTIONS.maps));
  assert.deepEqual([next.structure, next.pocketSet, next.pocketRanks, next.residues, next.ligand, next.protectedResidues,
    next.releasedResidues, next.annotation, next.numberingMap, next.allowed, next.radiusText],
  [S2, null, [], [], null, [], [], "N3", "M3", ["A"], "7"]);
});

test("annotation/map conflict is shown and blocks the request; other-structure choices are refused", () => {
  assert.equal(lib.annotationMapConflict("N2", "M1", OPTIONS.annotations), lib.MAP_CONFLICT_TEXT);
  assert.equal(lib.annotationMapConflict("N2", "M2", OPTIONS.annotations), null);
  assert.equal(lib.annotationMapConflict("N2", null, OPTIONS.annotations), null);
  assert.equal(lib.annotationMapConflict(null, "M1", OPTIONS.annotations), null);
  assert.deepEqual(errorsOf({ userOn: true, residues: [A10], annotation: "N2", numberingMap: "M1" }), [lib.MAP_CONFLICT_TEXT]);
  assert.deepEqual(errorsOf({ userOn: true, residues: [A10], numberingMap: "M3" }), ["고른 번호 대응이 이 구조의 것이 아닙니다."]);
  assert.deepEqual(errorsOf({ userOn: true, residues: [A10], annotation: "N3" }), ["고른 참조 주석이 이 구조의 것이 아닙니다."]);
  assert.equal(lib.mutationRequestArgs(draft({ userOn: true, residues: [A10], annotation: "N1" }), OPTIONS).ok, true);
  assert.equal(lib.klifsNotice(null), lib.KLIFS_NOT_CHECKED_NOTICE);
  assert.match(lib.KLIFS_NOT_CHECKED_NOTICE, /^KLIFS 주요 부위 보호를 검사하지 않음/);
  assert.equal(lib.klifsNotice("N1"), null);
});

test("five panel states: unavailable (no run / capability / no prepared structure), loading, failed, empty, ready", () => {
  const base = { runId: "r1", capability: { available: true, reason: null }, structures: [S] };
  const state = over => plain(lib.mutationPanelState({ ...base, ...over }));
  assert.deepEqual(state({ runId: null }), { state: "unavailable", reason: lib.NO_RUN_REASON });
  assert.deepEqual(state({ capability: { available: false, reason: "이유" } }), { state: "unavailable", reason: "이유" });
  assert.deepEqual(state({ capability: null }), { state: "unavailable", reason: lib.CAPABILITY_REASON });
  assert.deepEqual(state({ capability: undefined }), { state: "loading" });
  assert.deepEqual(state({ structures: undefined }), { state: "loading" });
  assert.deepEqual(state({ loading: true }), { state: "loading" });
  assert.deepEqual(state({ error: "실패" }), { state: "failed", message: "실패" });
  assert.deepEqual(state({ structures: [] }), { state: "unavailable", reason: lib.NO_PREPARED_REASON });
  assert.doesNotMatch(lib.NO_PREPARED_REASON, /\d/);
  assert.deepEqual(state({}), { state: "ready" });
  assert.deepEqual(state({ detail: { null_result: false, counts: counts() } }), { state: "ready" });
  const empty = state({ detail: { null_result: true, counts: counts({ candidates: 0, candidate_positions: 0, excluded_positions: 4 }) } });
  assert.equal(empty.state, "scientific_null");
  assert.equal(empty.message, "후보 0개(빈 결과, scientific_null): 위치 4개 중 제외 4개. 제외 사유별 위치 수: 사용자 보호 1개, 금속 근접 1개, 이황화 Cys 1개.");
  assert.equal(state({ detail: { null_result: true, counts: counts() } }).state, "failed");
  assert.equal(state({ detail: { null_result: false, counts: counts({ candidates: 0 }) } }).state, "failed");
  const none = lib.nullResultText(counts({ positions: 0, excluded_positions: 0, candidates: 0,
    exclusion_reason_counts: Object.fromEntries(lib.EXCLUSION_REASONS.map(reason => [reason, 0])) }));
  assert.equal(none, "후보 0개(빈 결과, scientific_null): 위치 0개 중 제외 0개. 제외 사유가 있는 위치 없음.");
});

test("prepared structures come from result events, once per handle", () => {
  const out = (handle, kind = "prepared_structure") => ({ handle, kind, schema: `${kind}@1`, summary: {} });
  const events = [
    { seq: 1, type: "tool_succeeded", tool: "load_structure", call_id: "c1", key: "k1", output: out("L", "structure"), cached: false },
    { seq: 2, type: "tool_succeeded", tool: "prepare_structure", call_id: "c2", key: "k2", output: out(S), cached: false },
    { seq: 3, type: "tool_succeeded", tool: "prepare_structure", call_id: "c3", key: "k3", output: out(S2), cached: false },
    { seq: 4, type: "tool_succeeded", tool: "prepare_structure", call_id: "c4", key: "k2", output: out(S), cached: false },
    { seq: 5, type: "tool_failed", tool: "prepare_structure", call_id: "c5" },
  ];
  assert.deepEqual(plain(lib.preparedStructures(events)), [{ handle: S, seq: 2 }, { handle: S2, seq: 3 }]);
  assert.deepEqual(plain(lib.preparedStructures([])), []);
});

test("read queries: empty filters are not sent; closed values; pages", () => {
  assert.equal(lib.positionQuery(lib.EMPTY_POSITION_FILTERS, "order", 0), "sort=order&offset=0&limit=50");
  assert.equal(lib.positionQuery({ status: "excluded", source: "ligand_shell", exclusion_reason: "metal_contact", chain_auth: "CC" },
    "ligand_distance", 50, 100), "status=excluded&source=ligand_shell&exclusion_reason=metal_contact&chain_auth=CC&sort=ligand_distance&offset=50&limit=100");
  assert.equal(lib.positionQuery({ ...lib.EMPTY_POSITION_FILTERS, chain_auth: "A B&" }, "order", 0), "chain_auth=A+B%26&sort=order&offset=0&limit=50");
  assert.equal(lib.candidateQuery(lib.EMPTY_CANDIDATE_FILTERS, 0), "offset=0&limit=100");
  assert.equal(lib.candidateQuery({ position_index: 0, to: "W" }, 200, 200), "position_index=0&to=W&offset=200&limit=200");
  assert.equal(lib.pageRangeText({ total: 120, offset: 50, rows: Array(50) }), "전체 120개 중 51–100번째");
  assert.equal(lib.pageRangeText({ total: 0, offset: 0, rows: [] }), "전체 0개 · 이 페이지에 행 없음");
  assert.equal(lib.previousOffset(0, 50), null);
  assert.equal(lib.previousOffset(30, 50), 0);
  assert.equal(lib.previousOffset(100, 50), 50);
  assert.equal(lib.nextOffset({ total: 120, offset: 100, limit: 50 }), null);
  assert.equal(lib.nextOffset({ total: 120, offset: 50, limit: 50 }), 100);
  assert.equal(lib.POSITION_SORT_LABEL.order, "구조 파일 순서");
});

test("late responses: applied only for the same run, result handle and request number", () => {
  const live = { runId: "r1", handle: "H", seq: 4 };
  assert.equal(lib.mutationResponseCurrent({ ...live }, live), true);
  assert.equal(lib.mutationResponseCurrent({ ...live, runId: "r2" }, live), false);
  assert.equal(lib.mutationResponseCurrent({ ...live, handle: "H2" }, live), false);
  assert.equal(lib.mutationResponseCurrent({ ...live, seq: 3 }, live), false);
  assert.equal(lib.mutationResponseCurrent({ ...live, runId: null }, { ...live, runId: null }), false);
  assert.equal(lib.mutationResponseCurrent({ runId: "r1", handle: null, seq: 1 }, { runId: "r1", handle: null, seq: 1 }), true);
});

test("a saved report is announced for the same run even when the late inline display is dropped", () => {
  const captured = { runId: "r1", handle: "H", seq: 4 };
  // another set opened meanwhile: display dropped, report still announced
  assert.equal(lib.mutationResponseCurrent(captured, { runId: "r1", handle: "H2", seq: 5 }), false);
  assert.equal(lib.mutationReportSavedForRun(captured, "r1"), true);
  assert.equal(lib.mutationReportSavedForRun(captured, "r2"), false);
  assert.equal(lib.mutationReportSavedForRun({ ...captured, runId: null }, null), false);
});

test("display: null is \"—\" with a reason (never 0); distances are stored values with two decimals half-up", () => {
  assert.equal(lib.nullableText(null), "—");
  assert.equal(lib.nullableText(undefined), "—");
  assert.equal(lib.nullableText(0), "0");
  assert.equal(lib.distanceText(null), "—");
  assert.equal(lib.distanceText(2.935), "2.94 Å");
  assert.equal(lib.distanceText(2.9349), "2.93 Å");
  assert.equal(lib.distanceText(5), "5.00 Å");
  assert.equal(lib.distanceText(1e-7), "0.00 Å");
  assert.equal(lib.ligandDistanceText(null, false), "— (리간드를 고르지 않아 계산하지 않음)");
  assert.equal(lib.ligandDistanceText(null, true), "— (중원자 없음)");
  assert.equal(lib.ligandDistanceText(3.4449, true), "3.44 Å");
  assert.equal(lib.residueText(A10), "ILE A:10A");
  assert.equal(lib.residueLabelText(A10), "label A:—");
  assert.equal(lib.residueKey(A10), JSON.stringify([1, "A", "A", 10, null, "A", "ILE"]));
  assert.equal(lib.klifsSitesText(null), "— (검사하지 않음)");
  assert.equal(lib.klifsSitesText([]), "해당 부위 없음");
  assert.equal(lib.klifsSitesText(["hinge.46", "GK.45"]), "hinge.46, GK.45");
  assert.equal(lib.numberingText(null), "— (번호 대응을 고르지 않음)");
  assert.equal(lib.numberingText({ status: "not_in_map", uniprot_accession: null, uniprot_position: null, uniprot_residue: null,
    klifs_index: null, klifs_label: null }), "— (지도에 없음)");
  assert.equal(lib.numberingText({ status: "mapped", uniprot_accession: "P00533", uniprot_position: 745, uniprot_residue: "K",
    klifs_index: 17, klifs_label: "III.17" }), "대응됨 · UniProt P00533 K745 · KLIFS III.17");
  assert.equal(lib.numberingText({ status: "unmapped", uniprot_accession: null, uniprot_position: null, uniprot_residue: null,
    klifs_index: null, klifs_label: null }), "대응 없음 · UniProt — · KLIFS —");
  assert.equal(lib.metalText(null), "기준 거리 안 금속 없음");
  assert.equal(lib.metalText({ min_distance_A: 2.005, metal_residue: res("A", 200, "ZN") }), "ZN A:200 2.01 Å");
  assert.equal(lib.disulfideText(null), "기준 거리 안 짝 없음");
  assert.equal(lib.disulfideText(A5), "CYS A:5");
  assert.equal(lib.exclusionReasonsText([]), "없음");
  assert.equal(lib.exclusionReasonsText(["non_standard_residue", "metal_contact"]),
    "표준 잔기가 아님 (non_standard_residue), 금속 근접 (metal_contact)");
  assert.equal(lib.protectionText({ reasons: [], released: false, klifs_sites: null, metal: null, disulfide_partner: null }), "보호 사유 없음");
  assert.equal(lib.protectionText({ reasons: ["user_protected", "disulfide_cys"], released: true, klifs_sites: [], metal: null,
    disulfide_partner: A5 }), "사용자 보호, 이황화 Cys (보호 해제됨)");
  assert.equal(lib.sourcesText([{ kind: "pocket", pocket_rank: 1 }, { kind: "ligand_shell", radius_A: 5.0 }, { kind: "user" }]),
    "포켓 검출 #1, 리간드 껍질 5 Å, 직접 선택");
  assert.equal(lib.sourcesUsedText({ pocket: false, ligand_shell: true, user: true }), "리간드 껍질 · 직접 선택");
  assert.equal(lib.sourcesUsedText(null), "—");
  assert.equal(lib.candidateText({ from: "I", to: "A" }), "I→A (ILE→ALA)");
  assert.equal(lib.releaseEffectText({ residue: A5, effect: "none" }), "CYS A:5: 보호 사유가 없어 영향 없음");
  assert.equal(lib.countsText(counts()), "위치 4개 · 후보 위치 2개 · 제외 2개 · 해제 1개 · 후보 38개");
});

test("protection check table: not checked / not available carry no number", () => {
  const checked = plain(lib.protectionCheckRows(CHECKED));
  assert.deepEqual(checked.map(row => row.key), plain(lib.PROTECTION_CHECK_KEYS));
  assert.deepEqual(checked.map(row => row.status), ["검사함 (checked)", "검사함 (checked)", "검사함 (checked)",
    "검사함 (checked)", "사용할 수 없음 (not_available)"]);
  assert.equal(checked[1].detail, "주석 N1 · 주석된 부위 9개 · 없는 부위 1개");
  assert.equal(checked[2].detail, "기준 3 Å 이하 · 금속 잔기 1개 (ZN)");
  assert.equal(checked[3].detail, "SG–SG 기준 2.5 Å 이하 · 짝 1개");
  assert.equal(checked[4].detail, "— (구현하지 않음 (not_implemented))");
  const notChecked = plain(lib.protectionCheckRows(NOT_CHECKED))[1];
  assert.deepEqual(notChecked, { key: "klifs_key_sites", label: "KLIFS 주요 부위", status: "검사하지 않음 (not_checked)",
    detail: "— (참조 주석을 고르지 않음 (annotation_not_given))" });
  assert.doesNotMatch(notChecked.detail, /\d/);
  const noMetal = plain(lib.protectionCheckRows({ ...CHECKED, metal_contact: { ...CHECKED.metal_contact, metal_residues: 0, metal_names: [] } }))[2];
  assert.equal(noMetal.detail, "기준 3 Å 이하 · 금속 잔기 0개");
});

test("list rows: an invalid stored set shows no numbers; error text keeps reason code and stored limit", () => {
  const row = { handle: "H", created_seq: 9, valid: true, structure: S, model_number: 1, ligand: null,
    sources_used: { pocket: true, ligand_shell: false, user: false }, klifs_status: "not_checked", numbering_map: null,
    annotation: null, counts: counts(), null_result: false };
  assert.equal(lib.setRowText(row), "포켓 검출 · 후보 38개 · KLIFS 주요 부위 검사하지 않음");
  const invalid = { ...row, valid: false, structure: null, sources_used: null, klifs_status: null, counts: null, null_result: null };
  assert.equal(lib.setRowText(invalid), "저장된 결과를 검증하지 못함 (저장된 결과가 검증되지 않음 (method_evidence_invalid))");
  assert.doesNotMatch(lib.setRowText(invalid), /\d/);
  assert.equal(lib.mutationErrorText({ message: "positions exceed", code: "resource_exceeded",
    detail: { reason_code: "too_many_positions", positions: 412, limit: 400 } }),
  "위치 수 상한 초과 (too_many_positions): 위치 412개가 상한 400개를 넘어 저장하지 않았습니다. 출처를 줄여 다시 요청하세요.");
  assert.equal(lib.mutationErrorText({ message: "bad", code: "input_invalid", detail: { reason_code: "ligand_required" } }),
    "리간드 껍질에는 리간드 선택이 필요함 (ligand_required): bad");
  assert.equal(lib.mutationErrorText({ message: "", code: "input_invalid" }), "요청 오류 (input_invalid)");
  assert.equal(lib.mutationErrorText("x"), "x");
});

test("report: kind label in the report library and manifest match of the opened set", () => {
  assert.equal(reportLibrary.reportKindLabel({ kind: "mutation_candidates", handle: "h", target_handle: "m", created_seq: 6 }),
    "변이 후보 보고서");
  const artifact = { handle: "R", markdown_handle: "MD", markdown: "", manifest: { schema: "method_report_manifest@1",
    analysis_type: "mutation_candidates", result_handle: "H", snapshot: { event_seq: 3 } } };
  assert.equal(lib.mutationReportMatches(artifact, "H"), true);
  assert.equal(lib.mutationReportMatches(artifact, "H2"), false);
  assert.equal(lib.mutationReportMatches({ ...artifact, manifest: { ...artifact.manifest, analysis_type: "ligand_docking" } }, "H"), false);
});

// ---- wording: no interpretation, ranking, recommendation or safety claim anywhere on screen ----

test("wording check finds forbidden words; only a line equal to a fixed limitation sentence is exempt", () => {
  for (const word of ["친화도", "ΔΔG", "안정성", "순위", "추천", "최적", "개선", "활성", "예측", "좋은", "유망", "안전",
    "rank", "best", "optimal", "improved", "recommended", "affinity", "stability", "predicted",
    // M26 (spec §2): importance and effect wording
    "중요", "핵심", "필수", "효과", "effect", "essential", "critical", "important"])
    assert.ok(lib.mutationForbiddenWords(`이 후보는 ${word}`).length, word);
  // "KLIFS 주요 부위" (a label) is not importance wording
  assert.deepEqual(plain(lib.mutationForbiddenWords("KLIFS 주요 부위 · M-CSA 촉매 잔기 주석")), []);
  // the fixed sentences do contain checked words, and are exempt only verbatim on their own line
  assert.ok(lib.mutationForbiddenWords(`${lib.MUTATION_LIMITATIONS[1]} `).length);
  assert.ok(lib.MUTATION_LIMITATIONS[1].includes("효과"));
  assert.deepEqual(plain(lib.mutationForbiddenWords(lib.MUTATION_LIMITATIONS[1])), []);
  for (const sentence of lib.MUTATION_LIMITATIONS) assert.deepEqual(plain(lib.mutationForbiddenWords(sentence)), []);
  assert.deepEqual(plain(lib.mutationForbiddenWords(lib.MUTATION_LIMITATIONS.join("\n"))), []);
});

function screenStrings() {
  const texts = [];
  const collect = value => {
    if (typeof value === "string") texts.push(value);
    else if (Array.isArray(value)) value.forEach(collect);
    else if (value && typeof value === "object") Object.values(value).forEach(collect);
  };
  // every exported string constant and label table (codes such as "order" are harmless and checked too)
  for (const [name, value] of Object.entries(lib)) if (typeof value !== "function" && name !== "MUTATION_LIMITATIONS") collect(value);
  // every function output that reaches the screen
  const pos = { index: 0, residue: A10, standard_resname: "ILE", one_letter: "I", sources: [{ kind: "user" }],
    ligand_min_distance_A: null, numbering: null, protection: { reasons: ["metal_contact"], released: false, klifs_sites: null,
      metal: { min_distance_A: 2.1, metal_residue: res("A", 200, "ZN") }, disulfide_partner: null },
    exclusion_reasons: ["metal_contact"], status: "excluded", candidate_count: 0 };
  collect([
    ...lib.ADMISSION_REASON_CODES.map(lib.mutationReasonText), lib.mutationReasonText(lib.TOO_MANY_POSITIONS),
    ...lib.EXCLUSION_REASONS.map(lib.mutationReasonText), lib.mutationReasonText("annotation_not_given"),
    lib.mutationReasonText("not_implemented"), lib.mutationReasonText("method_evidence_invalid"),
    lib.ligandDistanceText(null, false), lib.ligandDistanceText(null, true), lib.distanceText(3.1),
    lib.numberingText(null), lib.numberingText({ status: "not_in_map", uniprot_accession: null, uniprot_position: null,
      uniprot_residue: null, klifs_index: null, klifs_label: null }), lib.klifsSitesText(null), lib.klifsSitesText([]),
    lib.metalText(null), lib.metalText(pos.protection.metal), lib.disulfideText(null), lib.exclusionReasonsText([]),
    lib.exclusionReasonsText(pos.exclusion_reasons), lib.protectionText(pos.protection),
    lib.protectionText({ ...pos.protection, released: true }), lib.protectionText({ ...pos.protection, reasons: [] }),
    lib.sourcesText([{ kind: "pocket", pocket_rank: 2 }, { kind: "ligand_shell", radius_A: 5 }, { kind: "user" }]),
    lib.sourcesUsedText({ pocket: true, ligand_shell: true, user: true }), lib.candidateText({ from: "I", to: "W" }),
    lib.releaseEffectText({ residue: A5, effect: "released" }), lib.releaseEffectText({ residue: A5, effect: "none" }),
    lib.countsText(counts()), lib.nullResultText(counts({ candidates: 0 })), lib.pageRangeText({ total: 3, offset: 0, rows: [1] }),
    lib.pageRangeText({ total: 0, offset: 0, rows: [] }), lib.residueLabelText(A10), lib.residueText(A10),
    lib.protectionCheckRows(CHECKED), lib.protectionCheckRows(NOT_CHECKED),
    lib.setRowText({ valid: false, counts: null }), lib.setRowText({ valid: true, counts: counts(), klifs_status: "checked",
      sources_used: { pocket: true, ligand_shell: false, user: true } }),
    lib.mutationErrorText({ message: "m", code: "resource_exceeded", detail: { reason_code: "too_many_positions", positions: 401, limit: 400 } }),
    lib.mutationErrorText({ message: "", code: "input_invalid" }),
    lib.mutationPanelState({ runId: null }), lib.mutationPanelState({ runId: "r", capability: null }),
    lib.mutationPanelState({ runId: "r", capability: { available: true, reason: null }, structures: [] }),
    lib.mutationPanelState({ runId: "r", capability: { available: true, reason: null }, structures: [S],
      detail: { null_result: true, counts: counts() } }),
    // M26 v2 catalytic texts
    ...[V2_NOT_GIVEN, V2_CHECKED, V2_NONE_COVERED, V2_PARTIAL, CHECKED.catalytic_residue_database].map(check =>
      [lib.catalyticCheckView(check), lib.catalyticCheckDetail(check)]),
    lib.protectionCheckRows({ ...CHECKED, catalytic_residue_database: V2_PARTIAL }),
    ...lib.CATALYTIC_STATUSES.map(status => [lib.catalyticBadge(status), lib.catalyticBadge(status, "chains_not_covered"),
      lib.mutationLimitationsFor(status)]),
    lib.catalyticBadge("brand_new"),
    lib.catalyticProtectionText({ released: false }), lib.catalyticProtectionText({ catalytic: null, released: false }),
    lib.catalyticProtectionText({ catalytic: [], released: false }),
    lib.catalyticProtectionText({ catalytic: [{ mcsa_id: 282, residue_index: 3, is_reference: true }], released: true }),
    lib.catalyticRequestNotices({ selected: null, prediction: null, uniprotNotice: null }),
    lib.catalyticRequestNotices({ selected: RK, uniprotNotice: lib.UNIPROT_SITES_NOTE,
      prediction: lib.predictCatalyticCoverage({ chains: [], page: { chain_total: 2 } }, ["A", "B"]) }),
    lib.predictCatalyticCoverage({ chains: [{ chain_auth: "A", mcsa: { status: "not_checked", coverage: null } },
      { chain_auth: "B", mcsa: { status: "checked", coverage: "chain_not_listed" } },
      { chain_auth: "C", mcsa: { status: "checked", coverage: "pdb_not_in_snapshot" } }] }, ["A", "B", "C", "D"]),
    lib.nullResultText(counts({ candidates: 0, exclusion_reason_counts: { ...counts().exclusion_reason_counts, catalytic_residue: 2 } })),
    lib.mutationErrorText({ message: "x", code: "resource_exceeded",
      detail: { reason_code: "catalytic_list_too_long", list: "conflicts", count: 401, limit: 400 } }),
    lib.mutationReasonText("catalytic_annotation_invalid"), lib.catalyticReasonText("annotation_not_given"),
    ...lib.CATALYTIC_UNCOVERED_COVERAGE.map(lib.uncoveredCoverageText),
  ]);
  const bad = [{}, { structure: null }, { pocketOn: true }, { pocketOn: true, pocketSet: "P2", pocketRanks: [1, 1] },
    { ligandShellOn: true, radiusText: "99" }, { userOn: true, residues: [A10, A10], metalText: "9", allowed: [] },
    { userOn: true, residues: [A10], allowed: ["B"] }, { userOn: true, residues: [A10], allowed: ["A", "A"] },
    { userOn: true, residues: [A10], protectedResidues: [A5], releasedResidues: [A5] },
    { userOn: true, residues: Array.from({ length: 401 }, (_, i) => res("A", i + 1, "ALA")) },
    { userOn: true, residues: [A10], ligand: res("Z", 1, "XYZ"), numberingMap: "M3", annotation: "N3" },
    { userOn: true, residues: [A10], annotation: "N2", numberingMap: "M1" },
    { userOn: true, residues: [A10], catalyticAnnotation: RK3 }];
  for (const over of bad) collect(plain(lib.mutationRequestArgs(draft(over), OPTIONS)).errors);
  return texts;
}

test("every user-visible string of this module passes the wording check (fixed limitation sentences excepted)", () => {
  const texts = screenStrings();
  assert.ok(texts.length > 150, `collected ${texts.length}`);
  for (const text of texts) assert.deepEqual(plain(lib.mutationForbiddenWords(text)), [], text);
  // nothing reads as a ranking: no "n위", "1등", "top", "#1 후보" style wording outside pocket numbers
  for (const text of texts) assert.doesNotMatch(text, /\d+\s*위(?!치)|\d+\s*등(?!록)|\btop\b|상위|하위/i, text);
});

// ---- M26: M20 v2 catalytic residue protection (spec 8-10) ----

test("catalytic annotation: same structure only, newest (first in the newest-first list) pre-selected, none -> null", () => {
  assert.deepEqual(plain(lib.catalyticAnnotationsForStructure(RK_RESULTS, S).map(item => item.handle)), [RK2, RK]);
  assert.deepEqual(plain(lib.catalyticAnnotationsForStructure(RK_RESULTS, null)), []);
  assert.equal(lib.defaultCatalyticAnnotation(RK_RESULTS, S), RK2);
  assert.equal(lib.defaultCatalyticAnnotation(RK_RESULTS, S2), RK3);
  assert.equal(lib.defaultCatalyticAnnotation(RK_RESULTS, "obj://r1/prepared_structure/other"), null);
  assert.equal(lib.defaultCatalyticAnnotation([], S), null);
  assert.equal(lib.defaultCatalyticAnnotation(RK_RESULTS, null), null);
  // a new structure pre-selects that structure's newest result; without results nothing is chosen
  const next = lib.draftForStructure(draft({ catalyticAnnotation: RK3 }), S, OPTIONS.annotations, OPTIONS.maps, RK_RESULTS);
  assert.equal(next.catalyticAnnotation, RK2);
  assert.equal(lib.draftForStructure(draft({ catalyticAnnotation: RK2 }), S, OPTIONS.annotations, OPTIONS.maps).catalyticAnnotation, null);
  // the choice is only sent when the person presses the button (the args just carry it)
  const withResults = { ...OPTIONS, reactionResults: RK_RESULTS };
  const out = plain(lib.mutationRequestArgs(draft({ userOn: true, residues: [A10], catalyticAnnotation: RK }), withResults));
  assert.equal(out.ok, true);
  assert.equal(out.args.catalytic_annotation, RK);
  assert.deepEqual(plain(lib.mutationRequestArgs(draft({ userOn: true, residues: [A10], catalyticAnnotation: RK3 }), withResults).errors),
    ["고른 효소 반응 지식 결과가 이 구조의 것이 아닙니다."]);
  assert.equal(lib.mutationRequestArgs(draft({ userOn: true, residues: [A10], catalyticAnnotation: RK }), OPTIONS).ok, false);
  assert.equal(plain(lib.mutationRequestArgs(draft({ userOn: true, residues: [A10] }), withResults)).args.catalytic_annotation, null);
});

test("coverage prediction before the request: covered, the four uncovered coverage values and an unread chain page", () => {
  const result = { chains: [
    { chain_auth: "A", mcsa: { status: "checked", coverage: "covered" } },
    { chain_auth: "B", mcsa: { status: "checked", coverage: "chain_not_listed" } },
    { chain_auth: "C", mcsa: { status: "checked", coverage: "pdb_not_in_snapshot" } },
    { chain_auth: "D", mcsa: { status: "not_checked", coverage: null } }], page: { chain_total: 4 } };
  const out = plain(lib.predictCatalyticCoverage(result, ["A", "B", "C", "D", "E", "A"]));
  assert.deepEqual(out.covered, ["A"]);
  assert.deepEqual(out.uncovered.map(item => [item.chain_auth, item.coverage]),
    [["B", "chain_not_listed"], ["C", "pdb_not_in_snapshot"], ["D", "not_checked"], ["E", "not_in_annotation"]]);
  assert.equal(out.uncovered[0].text, "체인 B: 촉매 잔기를 검사하지 않음 — 이 체인은 M-CSA 행에 없음 (chain_not_listed)");
  assert.equal(out.uncovered[3].text, "체인 E: 촉매 잔기를 검사하지 않음 — 고른 효소 반응 지식 결과에 이 체인이 없음 (not_in_annotation)");
  // a detail page that does not hold every chain: a missing chain is "not read yet", never "not in the annotation"
  const partial = plain(lib.predictCatalyticCoverage({ ...result, page: { chain_total: 12 } }, ["E"]));
  assert.deepEqual(partial.uncovered.map(item => [item.chain_auth, item.coverage]), [["E", null]]);
  assert.match(partial.uncovered[0].text, /아직 읽지 않은 체인/);
  assert.deepEqual(plain(lib.predictCatalyticCoverage(result, [])), { covered: [], uncovered: [] });
});

test("request notices: UK2 when nothing is chosen or chains would be uncovered, then UK3 when UniProt sites are linked", () => {
  assert.deepEqual(plain(lib.catalyticRequestNotices({ selected: null, prediction: null, uniprotNotice: null })),
    [lib.CATALYTIC_NOT_SELECTED_NOTICE, lib.CATALYTIC_NOT_CHECKED_BADGE]);
  assert.match(lib.CATALYTIC_NOT_SELECTED_NOTICE, /^M-CSA 촉매 잔기 보호를 검사하지 않음/);
  const covered = { covered: ["A"], uncovered: [] };
  assert.deepEqual(plain(lib.catalyticRequestNotices({ selected: RK, prediction: covered, uniprotNotice: null })), []);
  const prediction = lib.predictCatalyticCoverage({ chains: [{ chain_auth: "A", mcsa: { status: "checked", coverage: "covered" } }] },
    ["A", "B"]);
  assert.deepEqual(plain(lib.catalyticRequestNotices({ selected: RK, prediction, uniprotNotice: lib.UNIPROT_SITES_NOTE })),
    [lib.CATALYTIC_NOT_CHECKED_BADGE, prediction.uncovered[0].text, lib.UNIPROT_SITES_NOTE]);
  // UK3 from the server's linked position counts only (nothing recounted)
  assert.equal(lib.uniprotSitesNotice(null), null);
  assert.equal(lib.uniprotSitesNotice({ linked_positions: null }), null);
  assert.equal(lib.uniprotSitesNotice({ linked_positions: { mapped: 0, not_in_map: 3 } }), null);
  assert.equal(lib.uniprotSitesNotice({ linked_positions: { mapped: 2, not_in_map: 0 } }), lib.UNIPROT_SITES_NOTE);
});

test("catalytic badge follows the check status: none for checked, UK2 with distinct details otherwise", () => {
  assert.equal(lib.catalyticBadge("checked"), null);
  assert.equal(lib.catalyticBadge(null), null);
  assert.equal(lib.catalyticBadge(undefined), null);
  const v1 = plain(lib.catalyticBadge("not_available"));
  const v2 = plain(lib.catalyticBadge("not_checked"));
  assert.equal(v1.text, lib.CATALYTIC_NOT_CHECKED_BADGE);
  assert.equal(v2.text, lib.CATALYTIC_NOT_CHECKED_BADGE);
  assert.notEqual(v1.detail, v2.detail);
  assert.match(v1.detail, /촉매 잔기 검사가 생기기 전\(v1\)/);
  assert.match(v2.detail, /보호 검사 칸/);
  assert.equal(lib.catalyticBadge("not_checked", "chains_not_covered").detail,
    "검사하지 않은 이유: 위치가 있는 체인 중 M-CSA가 다루지 않은 체인이 있거나 위치가 없음 (chains_not_covered) (not_checked).");
  assert.equal(lib.catalyticBadge("not_checked", "annotation_not_given").detail,
    "검사하지 않은 이유: 효소 반응 지식 결과를 고르지 않음 (annotation_not_given) (not_checked).");
  // a value outside the closed set is never shown as checked
  assert.equal(lib.catalyticBadge("checked ").text, lib.CATALYTIC_NOT_CHECKED_BADGE);
});

test("catalytic check view: three statuses; row counts are numbers only with covered chains (a stored 0 is not a count)", () => {
  const notGiven = plain(lib.catalyticCheckView(V2_NOT_GIVEN));
  assert.deepEqual([notGiven.statusText, notGiven.coveredChains, notGiven.uncovered, notGiven.conflicts, notGiven.unmatched],
    ["검사하지 않음 (not_checked)", null, null, null, null]);
  assert.equal(notGiven.rowCounts.matched, "— (효소 반응 지식 결과를 고르지 않음 (annotation_not_given))");
  assert.equal(notGiven.limitation3, lib.MUTATION_LIMITATION_3_NOT_CHECKED);
  assert.equal(notGiven.badge.text, lib.CATALYTIC_NOT_CHECKED_BADGE);
  const v1 = plain(lib.catalyticCheckView(CHECKED.catalytic_residue_database));
  assert.equal(v1.statusText, "사용할 수 없음 (not_available)");
  assert.equal(v1.note, lib.CATALYTIC_NOTE_V1);
  assert.equal(v1.note, "촉매 잔기 데이터베이스는 사용할 수 없음(구현하지 않음). 촉매 잔기는 판정하지 않았습니다.");
  assert.equal(v1.limitation3, lib.MUTATION_LIMITATIONS[2]);
  for (const view of [notGiven, v1]) for (const text of Object.values(view.rowCounts)) assert.doesNotMatch(text, /\d/);
  const none = plain(lib.catalyticCheckView(V2_NONE_COVERED));
  assert.deepEqual(none.coveredChains, []);
  assert.deepEqual(none.rowCounts, { matched: "— (M-CSA가 다룬 체인 없음)", conflict: "— (M-CSA가 다룬 체인 없음)",
    unmatched: "— (M-CSA가 다룬 체인 없음)" });
  assert.deepEqual(none.uncovered, [{ chainAuth: "A", coverage: "pdb_not_in_snapshot",
    coverageText: "이 PDB ID는 스냅샷에 없음 (pdb_not_in_snapshot)" }]);
  assert.equal(none.reasonText, "위치가 있는 체인 중 M-CSA가 다루지 않은 체인이 있거나 위치가 없음 (chains_not_covered)");
  const partial = plain(lib.catalyticCheckView(V2_PARTIAL));
  assert.deepEqual(partial.rowCounts, { matched: "2개", conflict: "0개", unmatched: "0개" });
  assert.deepEqual(partial.uncovered.map(item => item.coverageText), ["이 체인은 M-CSA 행에 없음 (chain_not_listed)",
    "고른 효소 반응 지식 결과에 이 체인이 없음 (not_in_annotation)",
    "결과가 이 체인의 M-CSA를 검사하지 않음(PDB ID 없음) (not_checked)"]);
  assert.equal(partial.badge.text, lib.CATALYTIC_NOT_CHECKED_BADGE);
  const checked = plain(lib.catalyticCheckView(V2_CHECKED));
  assert.deepEqual([checked.statusText, checked.reasonText, checked.badge, checked.limitation3],
    ["검사함 (checked)", null, null, lib.MUTATION_LIMITATION_3_CHECKED]);
  assert.deepEqual(checked.rowCounts, { matched: "4개", conflict: "1개", unmatched: "1개" });
  assert.equal(checked.note, lib.CATALYTIC_NOTE);
  // conflict and unmatched rows carry the listed position prominently and the 7-field residue (or why there is none)
  assert.deepEqual(checked.conflicts, [{ chainAuth: "A", mcsaId: 282, residueIndex: 3,
    reasonText: "구조 잔기 이름이 M-CSA 잔기 이름과 다름 (residue_name_differs)",
    positionText: "체인 A · M-CSA가 적은 번호 auth 99 (resid 101) · Asp",
    residueText: "구조 잔기 GLU A:99 (label A:99, 모델 1)" }]);
  assert.deepEqual(checked.unmatched[0].positionText, "체인 A · M-CSA가 적은 번호 auth 250 (resid —) · His");
  assert.equal(checked.unmatched[0].residueText, "— (구조에서 이 잔기 하나로 정하지 못함)");
  // protection check table rows: v1 detail unchanged, v2 details from the stored check
  const rows = check => plain(lib.protectionCheckRows({ ...CHECKED, catalytic_residue_database: check }))[4];
  assert.deepEqual(rows(CHECKED.catalytic_residue_database), { key: "catalytic_residue_database", label: "촉매 잔기 데이터베이스",
    status: "사용할 수 없음 (not_available)", detail: "— (구현하지 않음 (not_implemented))" });
  assert.equal(rows(V2_NOT_GIVEN).detail, "— (효소 반응 지식 결과를 고르지 않음 (annotation_not_given))");
  assert.equal(rows(V2_NONE_COVERED).detail, `결과 ${RK} · 다룬 체인 — (M-CSA가 다룬 체인 없음) · 다루지 않은 체인 A 이 PDB ID는 ` +
    "스냅샷에 없음 (pdb_not_in_snapshot) · 대응됨 — (M-CSA가 다룬 체인 없음) · 충돌 — (M-CSA가 다룬 체인 없음) · 대응 없음 — " +
    "(M-CSA가 다룬 체인 없음)");
  assert.doesNotMatch(rows(V2_NONE_COVERED).detail.replace(RK, ""), /\d/);
  assert.equal(rows(V2_CHECKED).detail, `결과 ${RK} · 다룬 체인 A · 다루지 않은 체인 없음 · 대응됨 4개 · 충돌 1개 · 대응 없음 1개`);
  assert.equal(rows(V2_CHECKED).status, "검사함 (checked)");
});

test("position catalytic cell: v1 and null are \"—\" with a reason, [] is checked-none, entries with 해제됨 when released", () => {
  assert.equal(lib.catalyticProtectionText({ released: false }), "— (촉매 잔기 검사 전 v1 집합)");
  assert.equal(lib.catalyticProtectionText({ catalytic: null, released: false }), "— (이 체인의 촉매 잔기를 검사하지 않음)");
  assert.equal(lib.catalyticProtectionText({ catalytic: [], released: false }), "대응된 M-CSA 촉매 잔기 행 없음(검사함)");
  const entries = [{ mcsa_id: 175, residue_index: 0, is_reference: true }, { mcsa_id: 175, residue_index: 2, is_reference: false }];
  assert.equal(lib.catalyticProtectionText({ catalytic: entries, released: false }),
    "M-CSA 175 잔기 순번 0 · 기준 구조, M-CSA 175 잔기 순번 2");
  assert.equal(lib.catalyticProtectionText({ catalytic: entries, released: true }),
    "M-CSA 175 잔기 순번 0 · 기준 구조, M-CSA 175 잔기 순번 2 · 해제됨");
  // the reason name itself, also when released (the reason list stays)
  assert.equal(lib.protectionText({ reasons: ["metal_contact", "catalytic_residue"], released: true, klifs_sites: [], metal: null,
    disulfide_partner: null, catalytic: entries }), "금속 근접, M-CSA 촉매 잔기 주석 (보호 해제됨)");
  assert.equal(lib.mutationReasonText("catalytic_residue"), "M-CSA 촉매 잔기 주석 (catalytic_residue)");
});

test("limitation sentence 3 follows the catalytic status; the other four are the v1 sentences", () => {
  assert.equal(lib.mutationLimitationsFor("not_available"), lib.MUTATION_LIMITATIONS);
  for (const [status, third] of [["checked", lib.MUTATION_LIMITATION_3_CHECKED], ["not_checked", lib.MUTATION_LIMITATION_3_NOT_CHECKED]]) {
    const out = plain(lib.mutationLimitationsFor(status));
    assert.deepEqual(out, [lib.MUTATION_LIMITATIONS[0], lib.MUTATION_LIMITATIONS[1], third, lib.MUTATION_LIMITATIONS[3],
      lib.MUTATION_LIMITATIONS[4]]);
  }
  // the backend v2 tuples, sentence by sentence
  assert.match(constantsSource, /CHECKED: \(LIMITATIONS\[0\], LIMITATIONS\[1\], LIMITATION_3_CHECKED, LIMITATIONS\[3\], LIMITATIONS\[4\]\)/);
  assert.match(constantsSource, /NOT_CHECKED: \(LIMITATIONS\[0\], LIMITATIONS\[1\], LIMITATION_3_NOT_CHECKED, LIMITATIONS\[3\], LIMITATIONS\[4\]\)/);
  for (const line of lib.MUTATION_FIXED_LINES) assert.deepEqual(plain(lib.mutationForbiddenWords(line)), [], line);
  // the request-area note no longer says the database is unavailable; the v1 wording stays for v1 sets
  assert.notEqual(lib.CATALYTIC_NOTE, lib.CATALYTIC_NOTE_V1);
  assert.match(lib.CATALYTIC_NOTE, /대응됨인 잔기만 보호/);
});

test("v2 exclusion counts: seven keys shown in the closed order, v1 keeps six; the null-result text uses stored counts", () => {
  const v1 = counts();
  assert.deepEqual(plain(lib.exclusionReasonsOf(v1)), plain(lib.EXCLUSION_REASONS));
  const v2 = counts({ exclusion_reason_counts: { ...v1.exclusion_reason_counts, catalytic_residue: 2 } });
  assert.deepEqual(plain(lib.exclusionReasonsOf(v2)), plain(lib.EXCLUSION_REASONS_V2));
  assert.equal(lib.exclusionReasonCount(v1, "catalytic_residue"), undefined);
  assert.equal(lib.exclusionReasonCount(v2, "catalytic_residue"), 2);
  assert.equal(lib.nullResultText({ ...v2, candidates: 0 }), "후보 0개(빈 결과, scientific_null): 위치 4개 중 제외 2개. " +
    "제외 사유별 위치 수: 사용자 보호 1개, 금속 근접 1개, 이황화 Cys 1개, M-CSA 촉매 잔기 주석 2개.");
  assert.equal(lib.mutationErrorText({ message: "x", code: "resource_exceeded",
    detail: { reason_code: "catalytic_list_too_long", list: "unmatched", count: 401, limit: 400 } }),
  "촉매 잔기 충돌·대응 없음 목록 상한 초과 (catalytic_list_too_long): 대응 없음 행 401개가 상한 400개를 넘어 저장하지 않았습니다(자르지 않음).");
  assert.equal(lib.mutationErrorText({ message: "bad", code: "input_invalid", detail: { reason_code: "catalytic_annotation_invalid" } }),
    "이 run의 효소 반응 지식 결과가 아니거나 검증되지 않음 (catalytic_annotation_invalid): bad");
});

test("counts line: the catalytic_residue count is — with the reason unless a chain was covered (a stored 0 counts nothing)", () => {
  // the stored v2 counts carry catalytic_residue: 0 whenever no chain was covered (spec 8.3/8.6, storage unchanged)
  const zero = counts({ exclusion_reason_counts: { ...counts().exclusion_reason_counts, catalytic_residue: 0 } });
  const line = check => plain(lib.exclusionReasonsOf(zero).map(reason => lib.exclusionReasonCountText(zero, reason, check)));
  const catalytic = check => lib.exclusionReasonCountText(zero, "catalytic_residue", check);
  assert.equal(catalytic(V2_NOT_GIVEN),
    "M-CSA 촉매 잔기 주석 — (효소 반응 지식 결과를 고르지 않음 (annotation_not_given), 세지 않음)");
  assert.equal(catalytic(V2_NONE_COVERED), "M-CSA 촉매 잔기 주석 — (M-CSA가 다룬 체인 없음, 세지 않음)");
  assert.equal(catalytic(CHECKED.catalytic_residue_database), "M-CSA 촉매 잔기 주석 — (구현하지 않음 (not_implemented), 세지 않음)");
  for (const check of [V2_NOT_GIVEN, V2_NONE_COVERED, CHECKED.catalytic_residue_database]) {
    assert.doesNotMatch(catalytic(check), /\d/);
    assert.ok(!line(check).join(" · ").includes("M-CSA 촉매 잔기 주석 0"), JSON.stringify(check));
  }
  // checked: the number; partly covered: the number of the covered chains only, with those chains named
  const three = counts({ exclusion_reason_counts: { ...counts().exclusion_reason_counts, catalytic_residue: 3 } });
  assert.equal(lib.exclusionReasonCountText(three, "catalytic_residue", V2_CHECKED), "M-CSA 촉매 잔기 주석 3개");
  assert.equal(lib.exclusionReasonCountText(zero, "catalytic_residue", V2_CHECKED), "M-CSA 촉매 잔기 주석 0개");
  assert.equal(lib.exclusionReasonCountText(three, "catalytic_residue", V2_PARTIAL), "M-CSA 촉매 잔기 주석 3개 (검사한 체인 A만)");
  // the other reasons are their stored numbers, also 0, whatever the catalytic check (v1: six entries)
  assert.deepEqual(line(V2_NOT_GIVEN), ["표준 잔기가 아님 0개", "사용자 보호 1개", "KLIFS 주요 부위 0개", "금속 근접 1개",
    "이황화 Cys 1개", "M-CSA 촉매 잔기 주석 — (효소 반응 지식 결과를 고르지 않음 (annotation_not_given), 세지 않음)",
    "허용 목록에 바꿀 잔기 없음 0개"]);
  const v1 = counts();
  assert.deepEqual(plain(lib.exclusionReasonsOf(v1).map(reason => lib.exclusionReasonCountText(v1, reason,
    CHECKED.catalytic_residue_database))), ["표준 잔기가 아님 0개", "사용자 보호 1개", "KLIFS 주요 부위 0개", "금속 근접 1개",
    "이황화 Cys 1개", "허용 목록에 바꿀 잔기 없음 0개"]);
  for (const check of [V2_NOT_GIVEN, V2_NONE_COVERED, V2_PARTIAL, V2_CHECKED])
    assert.deepEqual(plain(lib.mutationForbiddenWords(line(check).join(" · "))), []);
});

test("a failed reaction knowledge list read is no result to choose, never a block; a failed detail read keeps UK2", () => {
  assert.deepEqual(plain(lib.catalyticChoices({ status: "idle" })), { rows: [], settled: false, error: null });
  assert.deepEqual(plain(lib.catalyticChoices({ status: "loading" })), { rows: [], settled: false, error: null });
  assert.deepEqual(plain(lib.catalyticChoices({ status: "ready", value: RK_RESULTS })),
    { rows: plain(RK_RESULTS), settled: true, error: null });
  const failed = plain(lib.catalyticChoices({ status: "error", message: "효소 반응 지식 결과 목록 읽기 실패: 409" }));
  assert.deepEqual([failed.rows, failed.settled], [[], true]);
  assert.equal(failed.error, `효소 반응 지식 결과 목록 읽기 실패: 409 — ${lib.CATALYTIC_LIST_FAILED_NOTE}`);
  // with no result to choose: nothing is pre-selected, UK2 is shown, and the request without an annotation is valid
  const next = lib.draftForStructure(draft({}), S, OPTIONS.annotations, OPTIONS.maps, failed.rows);
  assert.equal(next.catalyticAnnotation, null);
  assert.deepEqual(plain(lib.catalyticRequestNotices({ selected: next.catalyticAnnotation, prediction: null, uniprotNotice: null })),
    [lib.CATALYTIC_NOT_SELECTED_NOTICE, lib.CATALYTIC_NOT_CHECKED_BADGE]);
  const out = plain(lib.mutationRequestArgs({ ...next, userOn: true, residues: [A10] }, { ...OPTIONS, reactionResults: failed.rows }));
  assert.equal(out.ok, true);
  assert.equal(out.args.catalytic_annotation, null);
  // the chosen result's detail could not be read: UK2 and why nothing is known before the request (no prediction, no UK3)
  assert.deepEqual(plain(lib.catalyticRequestNotices({ selected: RK, prediction: null, uniprotNotice: lib.UNIPROT_SITES_NOTE,
    detailFailed: true })), [lib.CATALYTIC_NOT_CHECKED_BADGE, lib.CATALYTIC_DETAIL_UNREAD_NOTE]);
  assert.equal(lib.CATALYTIC_NOT_CHECKED_BADGE, reactionNote("UK2"));
  // the request with the chosen handle stays possible (the server validates it)
  assert.equal(lib.mutationRequestArgs(draft({ userOn: true, residues: [A10], catalyticAnnotation: RK }),
    { ...OPTIONS, reactionResults: RK_RESULTS }).ok, true);
  for (const text of [failed.error, lib.CATALYTIC_DETAIL_UNREAD_NOTE])
    assert.deepEqual(plain(lib.mutationForbiddenWords(text)), [], text);
});
