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
const numbering = load("numbering");
const eventModel = load("event-model");
const siteAnnotation = load("site-annotation", { "./comparison": load("comparison"), "./numbering": numbering,
  "./event-model": eventModel });
const lib = load("reaction-knowledge", { "./numbering": numbering });
const mutations = load("mutations", { "./event-model": eventModel, "./site-annotation": siteAnnotation });
const reportLibrary = load("report-library");
const plain = value => JSON.parse(JSON.stringify(value));
const LIB_SOURCE = fs.readFileSync(path.join(__dirname, "../src/lib/reaction-knowledge.ts"), "utf8");

// ---- closed sets, caps and fixed sentences are read from the backend files themselves ----
const backend = name => fs.readFileSync(path.join(__dirname, `../../backend/mw/${name}`), "utf8");
const K = backend("reaction_knowledge_constants.py");
const READS = backend("reaction_knowledge_reads.py");
const TOOL = backend("tools/reaction_knowledge.py");
const REPORTS = backend("reaction_knowledge_reports.py");
const APP = backend("api/app.py");
function pyTuple(name, source = K) {
  const match = new RegExp(`^${name} = \\(([^)]*)\\)`, "m").exec(source);
  assert.ok(match, `backend constant ${name} not found`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map(item => item[1]);
}
function pyString(name, source = K) {
  const match = new RegExp(`^${name} = r?"([^"]*)"`, "m").exec(source);
  assert.ok(match, `backend constant ${name} not found`);
  return match[1];
}
function pyInt(name, source = K) {
  const match = new RegExp(`^${name} = ([0-9][0-9 *]*)`, "m").exec(source);
  assert.ok(match, `backend constant ${name} not found`);
  return match[1].split("*").map(part => Number(part.trim())).reduce((a, b) => a * b, 1);
}
/** `NAME = { "KEY": "..." | ("a" "b"), ... }` -> { KEY: text } in source order. */
function pyDictStrings(name) {
  const start = K.indexOf(`${name} = {`);
  assert.ok(start >= 0, `backend dict ${name} not found`);
  const block = K.slice(start, K.indexOf("\n}", start));
  return Object.fromEntries([...block.matchAll(/"(\w+)": (\((?:\s*"[^"]*")+\s*\)|"[^"]*")/g)]
    .map(([, key, value]) => [key, [...value.matchAll(/"([^"]*)"/g)].map(item => item[1]).join("")]));
}
function pySet(pattern, source) {
  const match = pattern.exec(source);
  assert.ok(match, String(pattern));
  return [...match[1].matchAll(/"([^"]+)"/g)].map(item => item[1]);
}

// spec .dryforge/spec.md 11.1, verbatim (the hand copy the module and the backend are compared with)
const SPEC_RK = {
  RK1: "촉매 잔기·부위·반응은 참조 스냅샷(M-CSA·UniProt·Rhea)에 적힌 값이며 ProtView가 계산하거나 판정한 것이 아니다.",
  RK2: "대응됨은 M-CSA가 적은 PDB·체인·번호와 이 구조의 잔기 이름이 모두 같다는 뜻이며 잔기의 역할이나 활성을 뜻하지 않는다.",
  RK3: "대응 없음·충돌·검사하지 않음은 이 스냅샷과 방법으로 확실하지 않다는 뜻이며 촉매 잔기가 없다는 뜻이 아니다.",
  RK4: "UniProt 부위는 번호 대응이 있는 체인에서만 구조 잔기에 연결했고 그 밖에는 단백질 서열 위치로만 보여 준다.",
  RK5: "반응 정보는 효소 활성·속도·특이성이나 반응 메커니즘이 유지된다는 뜻이 아니다.",
  RK6: "M-CSA·UniProt·Rhea 자료는 CC BY 4.0이며 출처·스냅샷 날짜는 아래에 있다.",
};
const SPEC_UK = {
  UK1: "촉매 잔기·부위·반응은 M-CSA·UniProt·Rhea가 적은 참조값이며 ProtView가 계산한 값이 아니다. 가져온 스냅샷 날짜 기준이다.",
  UK2: "촉매 잔기 검사 안 함: 이 집합은 M-CSA 촉매 잔기 주석 없이 만들었거나 일부 체인만 검사했다.",
  UK3: "UniProt 부위 정보는 지식 탭에서만 보이며 보호에 쓰지 않음.",
  UK4: "이 체인을 M-CSA가 다루지 않았다는 것은 촉매 잔기가 없다는 뜻이 아니다.",
};

// ---- fixtures (synthetic; handles and hashes are placeholders, reference strings are neutral) ----
const RUN = "r1";
const S = `obj://${RUN}/prepared_structure/${"1".repeat(64)}`;
const S_RAW = `obj://${RUN}/structure/${"2".repeat(64)}`;
const MAP = `obj://${RUN}/residue_numbering_map/${"3".repeat(64)}`;
const MAP_OLD = `obj://${RUN}/residue_numbering_map/${"5".repeat(64)}`;
const MAP_RAW = `obj://${RUN}/residue_numbering_map/${"6".repeat(64)}`;
const RESULT = `obj://${RUN}/reaction_knowledge/${"4".repeat(64)}`;
const SET = "a".repeat(64);
const SET2 = "b".repeat(64);
const res = (chain, seq, resname, over = {}) => ({ model_number: 1, chain_auth: chain, chain_label: chain, seq_auth: seq,
  seq_label: seq, icode: "", resname, ...over });
const ROLE = { group_function: "group text", function_type: "type text", function: "function text", emo: "EMO_00001" };
const reference = over => ({ roles_summary: "summary text", function_location_abv: "side chain", ptm: "", roles: [ROLE], ...over });
const mcsaRow = over => ({ mcsa_id: 282, residue_index: 0, is_reference: true,
  listed: { pdb_id: "1s9i", chain_name: "A", resid: 208, auth_resid: 208, code: "Asp", assemblies: [1] },
  status: "matched", reason: null, residue: res("A", 208, "ASP"), structure_resname: "ASP", reference: reference(), ...over });
// deliberately not in the canonical order: the view keeps the server order
const ROWS_A = [
  mcsaRow({ mcsa_id: 300, listed: { pdb_id: "1s9i", chain_name: "A", resid: 210, auth_resid: 210, code: "Glu", assemblies: [] },
    residue: res("A", 210, "GLU", { chain_label: null, seq_label: null }), structure_resname: "GLU", is_reference: false }),
  mcsaRow({}),
  mcsaRow({ residue_index: 1, status: "conflict", reason: "residue_name_differs",
    listed: { pdb_id: "1s9i", chain_name: "A", resid: 212, auth_resid: 212, code: "Ser", assemblies: [1, 2] },
    residue: res("A", 212, "ALA"), structure_resname: "ALA" }),
  mcsaRow({ residue_index: 2, status: "unmatched", reason: "residue_not_in_structure",
    listed: { pdb_id: "1s9i", chain_name: "A", resid: null, auth_resid: 999, code: "His", assemblies: [] },
    residue: null, structure_resname: null }),
  mcsaRow({ residue_index: 3, status: "unmatched", reason: "insertion_code_present",
    listed: { pdb_id: "1s9i", chain_name: "A", resid: 100, auth_resid: 100, code: "Lys", assemblies: [1] },
    residue: res("A", 100, "LYS", { icode: "A" }), structure_resname: "LYS" }),
  mcsaRow({ residue_index: 4, status: "conflict", reason: "mcsa_rows_disagree",
    listed: { pdb_id: "1s9i", chain_name: "A", resid: 230, auth_resid: 230, code: "Asp/Glu", assemblies: [] },
    residue: null, structure_resname: null, reference: reference({ roles_summary: "", function_location_abv: "", roles: null }) }),
];
const CHAIN_A = { chain_auth: "A", polymer_residue_count: 390, accession: "P36507", accession_source: "numbering_map",
  mcsa: { status: "checked", reason: null, coverage: "covered",
    entries: [{ mcsa_id: 282, enzyme_name: "enzyme two", reference_uniprot_id: "P36507", all_ecs: ["2.7.12.2"] },
      { mcsa_id: 300, enzyme_name: "enzyme three", reference_uniprot_id: "", all_ecs: [] }],
    rows: ROWS_A, counts: { matched: 2, unmatched: 2, conflict: 2 }, row_total: 6 },
  uniprot: { status: "checked", reason: null, skipped: null,
    entry: { accession: "P36507", entry_name: "ENTRY_HUMAN", protein_name: null, organism: "Homo sapiens", sequence_length: 400 },
    linked_via: "numbering_map", link_reason: null, feature_total: 2,
    features: [
      { type: "Binding site", start: 77, end: 79, description: "", ligand_name: "ATP", ligand_id: "ChEBI:CHEBI:30616", links: [
        { position: 77, status: "mapped", residue: res("A", 77, "GLY"), uniprot_residue: "G", residue_match: true },
        { position: 78, status: "not_in_map", residue: null, uniprot_residue: null, residue_match: null },
        { position: 79, status: "mapped", residue: res("A", 79, "SER", { seq_label: null }), uniprot_residue: "T",
          residue_match: false }] },
      { type: "Active site", start: 208, end: 208, description: "site text", ligand_name: null, ligand_id: null, links: [
        { position: 208, status: "mapped", residue: res("A", 208, "ASP"), uniprot_residue: "D", residue_match: true }] }] },
  reactions: { status: "checked", reason: null, ecs: { mcsa: ["2.7.12.2"], uniprot: [] },
    mcsa_compounds: [{ mcsa_id: 282, ec: "2.7.12.2", compounds: [{ type: "reactant", chebi_id: "15422", name: "ATP" }] },
      { mcsa_id: 300, ec: null, compounds: [] }],
    uniprot_activities: [{ reaction_name: "A + B = C + D", ec_number: null,
      rhea: [{ rhea_id: "RHEA:17989", in_snapshot: true }, { rhea_id: "RHEA:99999", in_snapshot: false }] }] },
  flags: ["accession_differs_from_mcsa"] };
const CHAIN_B = { chain_auth: "B", polymer_residue_count: 50, accession: "Q12345", accession_source: "user",
  mcsa: { status: "checked", reason: null, coverage: "chain_not_listed", entries: null, rows: null, counts: null, row_total: null },
  uniprot: { status: "not_available", reason: "accession_skipped_at_import",
    skipped: { reason: "merged", target_accessions: ["P99999"] }, entry: null, linked_via: null, link_reason: null,
    features: null, feature_total: null },
  reactions: { status: "not_checked", reason: "no_source", ecs: null, mcsa_compounds: null, uniprot_activities: null },
  flags: [] };
const SNAPSHOT_SET = { set_hash: SET, imported_at: "2026-10-08T01:02:03Z", importer_version: "reaction_import/1",
  sources: [["mcsa", "entries.jsonl"], ["uniprot_function", "entries.jsonl"], ["rhea", "reactions.jsonl"]].map(([source, name]) =>
    ({ source, date: "2026-10-08", license: "CC-BY-4.0", origin: "public server import",
      files: [{ name, sha256: "c".repeat(64), bytes: 10, rows: 1 }] })),
  requested_accessions: { from_mcsa: 2, from_m15_kinase_set: { set_hash: null, count: 0 }, m15_kinase_list: "absent",
    user_named: [], dropped_previous_user_named: [], union_count: 2 },
  skipped_accessions: [{ accession: "Q12345", reason: "merged", target_accessions: ["P99999"] }] };
const LIMITATIONS = Object.values(SPEC_RK).slice(0, 5);
const PAGE = { chain_total: 2, chain_offset: 0, chain_limit: 10, row_offset: 0, row_limit: 50, feature_offset: 0,
  feature_limit: 50 };
const DETAIL = { schema: "reaction_knowledge@1", method_version: "mw.reaction_knowledge/v1",
  structure: { handle: S, structure_kind: "prepared_structure", model_number: 1 }, pdb_id: "1S9I",
  numbering_map: { handle: MAP, pdb_id: "1S9I" }, snapshot_set: SNAPSHOT_SET, chains: [CHAIN_A, CHAIN_B],
  reference_rows: { mcsa: [], uniprot: [],
    rhea: [{ rhea_id: "RHEA:17989", equation: "A + B = C + D", ec_numbers: [], participants: [] }] },
  counts: { chains: 2, covered_chains: 1, mcsa_rows: { matched: 2, unmatched: 2, conflict: 2 }, mcsa_entries: 2,
    uniprot_features: { "Active site": 1, "Binding site": 1, "Site": 0 }, linked_positions: { mapped: 3, not_in_map: 1 },
    rhea: { in_snapshot: 1, not_in_snapshot: 1 } },
  null_result: false, limitations: LIMITATIONS, page: PAGE, active_set: { set_hash: SET2, same: false } };
const NOT_CHECKED_CHAIN = { chain_auth: "A", polymer_residue_count: 76, accession: null, accession_source: null,
  mcsa: { status: "not_checked", reason: "pdb_id_not_given", coverage: null, entries: null, rows: null, counts: null,
    row_total: null },
  uniprot: { status: "not_checked", reason: "accession_not_given", skipped: null, entry: null, linked_via: null,
    link_reason: null, features: null, feature_total: null },
  reactions: { status: "not_checked", reason: "no_source", ecs: null, mcsa_compounds: null, uniprot_activities: null },
  flags: [] };
const NULL_COUNTS = { chains: 1, covered_chains: 0, mcsa_rows: null, mcsa_entries: null, uniprot_features: null,
  linked_positions: null, rhea: null };
const DETAIL_NOT_CHECKED = { ...DETAIL, pdb_id: null, numbering_map: null, chains: [NOT_CHECKED_CHAIN],
  reference_rows: { mcsa: [], uniprot: [], rhea: [] }, counts: NULL_COUNTS, null_result: true,
  page: { ...PAGE, chain_total: 1 }, active_set: { set_hash: null, same: false } };
// checked but empty: UniProt features [] and activities [] (shown as empty lists, never as "not checked")
const EMPTY_CHAIN = { ...NOT_CHECKED_CHAIN, accession: "P36507", accession_source: "user",
  mcsa: { status: "checked", reason: null, coverage: "pdb_not_in_snapshot", entries: null, rows: null, counts: null,
    row_total: null },
  uniprot: { status: "checked", reason: null, skipped: null,
    entry: { accession: "P36507", entry_name: "ENTRY_HUMAN", protein_name: "protein text", organism: "Homo sapiens",
      sequence_length: 400 }, linked_via: null, link_reason: "numbering_map_not_given", features: [], feature_total: 0 },
  reactions: { status: "checked", reason: null, ecs: { mcsa: null, uniprot: [] }, mcsa_compounds: null, uniprot_activities: [] } };
const DETAIL_EMPTY = { ...DETAIL, pdb_id: "1UBQ", numbering_map: null, chains: [EMPTY_CHAIN],
  reference_rows: { mcsa: [], uniprot: [], rhea: [] }, null_result: true, page: { ...PAGE, chain_total: 1 },
  counts: { chains: 1, covered_chains: 0, mcsa_rows: null, mcsa_entries: null,
    uniprot_features: { "Active site": 0, "Binding site": 0, "Site": 0 }, linked_positions: null,
    rhea: { in_snapshot: 0, not_in_snapshot: 0 } }, active_set: { set_hash: SET, same: true } };
const STATUS_OK = { schema: "reaction_reference_status@1", installed: true, reason: null, set_hash: SET,
  imported_at: "2026-10-08T01:02:03Z", sources: [
    { source: "mcsa", date: "2026-10-08", license: "CC-BY-4.0", origin: "public server import", rows: 1003 },
    { source: "uniprot_function", date: "2026-10-08", license: "CC-BY-4.0", origin: "public server import", rows: 1612 },
    { source: "rhea", date: "2026-10-08", license: "CC-BY-4.0", origin: "public server import", rows: 18611 }],
  requested_accessions: { from_mcsa: 1094, from_m15_kinase_set: { set_hash: "d".repeat(64), count: 541 },
    m15_kinase_list: "present", user_named: ["P36507"], dropped_previous_user_named: [], union_count: 1631 },
  skipped_accessions: [{ accession: "P12345", reason: "merged", target_accessions: ["P67890"] },
    { accession: "Q11111", reason: "obsolete", target_accessions: [] }] };
const STATUS_NONE = { schema: "reaction_reference_status@1", installed: false, reason: "not_installed", set_hash: null,
  imported_at: null, sources: null, requested_accessions: null, skipped_accessions: null };
const STATUS_BAD = { ...STATUS_NONE, reason: "snapshot_invalid" };
const chainDetail = (chain_auth, over = {}) => ({ chain_auth, requested_uniprot_accession: null, methods_run: ["sifts"],
  cross_check: false, cross_check_absent_reason: null, sifts: null, alignment: null, klifs: [],
  counts: { mapped: 1, unmapped: 0, conflict: 0 }, ...over });
const mapRow = (handle, structure, seq, pdb_id, chain_details = []) => ({ handle, structure, structure_kind: "prepared_structure",
  model_number: 1, pdb_id, chains: chain_details.map(item => item.chain_auth), cross_checked_chains: [], set_hash: "h",
  counts: { mapped: 1, unmapped: 0, conflict: 0 }, row_count: 1, null_result: false, created_seq: seq, stale_snapshot: false,
  chain_details });
const MAPS = [
  mapRow(MAP_OLD, S, 4, "9ZZZ", [chainDetail("A", { requested_uniprot_accession: "Q99999" })]),
  mapRow(MAP, S, 9, "1S9I", [chainDetail("A", { sifts: { accessions: ["P36507"], sifts_chain_match: "", sifts_residue_key: "" } }),
    chainDetail("B", { requested_uniprot_accession: "Q12345", sifts: { accessions: ["P11111"], sifts_chain_match: "",
      sifts_residue_key: "" } }),
    chainDetail("C", { sifts: { accessions: ["P1A2B3", "P4C5D6"], sifts_chain_match: "", sifts_residue_key: "" } })]),
  mapRow(MAP_RAW, S_RAW, 20, "2ABC", [chainDetail("A")]),
];
const STRUCTURES = [{ handle: S_RAW, kind: "structure" }, { handle: S, kind: "prepared_structure" }];
const RESIDUES = [{ chain_auth: "A", category: "polymer" }, { chain_auth: "W", category: "water" },
  { chain_auth: "B", category: "polymer" }, { chain_auth: "L", category: "nonpolymer" }, { chain_auth: "C", category: "polymer" },
  { chain_auth: "A", category: "polymer" }];
const form = over => ({ ...lib.formForStructure(S, RESIDUES), ...over });
const chainsWith = (...pairs) => lib.formForStructure(S, RESIDUES).chains.map(choice => {
  const found = pairs.find(([chain]) => chain === choice.chain_auth);
  return found ? { ...choice, selected: true, accession: found[1] ?? "" } : choice;
});
const OPTIONS = { snapshot: STATUS_OK, structures: STRUCTURES, maps: MAPS };
const check = (over, options = OPTIONS) => plain(lib.checkReactionForm(form(over), options));

// ---- constants and fixed wording ----

test("closed sets, caps, patterns and names equal backend/mw/reaction_knowledge_constants.py", () => {
  for (const [name, value] of [["ADMISSION_REASON_CODES", lib.ADMISSION_REASON_CODES],
    ["SNAPSHOT_REASON_CODES", lib.SNAPSHOT_REASON_CODES], ["SOURCES", lib.REACTION_SOURCES], ["COVERAGE", lib.COVERAGE],
    ["MCSA_STATUSES", lib.MCSA_STATUSES], ["ROW_STATUSES", lib.ROW_STATUSES], ["UNMATCHED_REASONS", lib.UNMATCHED_REASONS],
    ["CONFLICT_REASONS", lib.CONFLICT_REASONS], ["UNIPROT_STATUSES", lib.UNIPROT_STATUSES],
    ["UNIPROT_REASONS", lib.UNIPROT_REASONS], ["LINK_STATUSES", lib.LINK_STATUSES], ["LINK_REASONS", lib.LINK_REASONS],
    ["REACTIONS_STATUSES", lib.REACTIONS_STATUSES], ["ACCESSION_SOURCES", lib.ACCESSION_SOURCES],
    ["CHAIN_FLAGS", lib.CHAIN_FLAGS], ["SITE_TYPES", lib.SITE_TYPES], ["SKIP_REASONS", lib.SKIP_REASONS],
    ["RESIDUE_FIELDS", lib.RESIDUE_FIELDS]])
    assert.deepEqual(plain(value), pyTuple(name), name);
  assert.equal(lib.ADMISSION_REASON_CODES.length, 9);
  assert.equal(lib.REACTION_TOOL, pyString("TOOL"));
  assert.equal(lib.REACTION_KIND, pyString("KIND"));
  assert.equal(lib.REACTION_SCHEMA, pyString("SCHEMA"));
  assert.equal(lib.REACTION_METHOD_VERSION, pyString("METHOD_VERSION"));
  assert.equal(lib.REACTION_STATUS_SCHEMA, pyString("STATUS_SCHEMA"));
  assert.equal(lib.RESULT_INVALID_REASON, pyString("RESULT_INVALID_REASON"));
  assert.equal(lib.RESULT_TOO_LARGE_REASON, pyString("RESULT_TOO_LARGE_REASON"));
  assert.equal(lib.TOO_MANY_LINKS_REASON, pyString("TOO_MANY_LINKS_REASON"));
  assert.equal(lib.MCSA_NOT_CHECKED_REASON, pyString("MCSA_NOT_CHECKED_REASON"));
  assert.equal(lib.REACTIONS_NOT_CHECKED_REASON, pyString("REACTIONS_NOT_CHECKED_REASON"));
  assert.equal(lib.MAX_RESULT_BYTES, pyInt("MAX_RESULT_BYTES"));
  assert.equal(lib.MAX_LINKS, pyInt("MAX_LINKS"));
  assert.equal(lib.UNIPROT_ACCESSION_PATTERN_SOURCE, pyString("UNIPROT_ACCESSION_PATTERN"));
  assert.equal(numbering.PDB_ID_PATTERN.source, `^${pyString("PDB_ID_PATTERN")}$`);
  assert.deepEqual(plain(lib.STRUCTURE_KINDS), pyTuple("STRUCTURE_KINDS", backend("reaction_knowledge.py")));
  assert.equal(lib.REACTION_REPORT_TYPE, pyString("ANALYSIS_TYPE", REPORTS));
  // read page limits and the detail route's query names
  for (const [names, values] of [["LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX", [lib.LIST_LIMIT_DEFAULT, lib.LIST_LIMIT_MAX]],
    ["CHAIN_LIMIT_DEFAULT, CHAIN_LIMIT_MAX", [lib.CHAIN_LIMIT_DEFAULT, lib.CHAIN_LIMIT_MAX]],
    ["ROW_LIMIT_DEFAULT, ROW_LIMIT_MAX", [lib.ROW_LIMIT_DEFAULT, lib.ROW_LIMIT_MAX]],
    ["FEATURE_LIMIT_DEFAULT, FEATURE_LIMIT_MAX", [lib.FEATURE_LIMIT_DEFAULT, lib.FEATURE_LIMIT_MAX]]])
    assert.match(READS, new RegExp(`^${names} = ${values[0]}, ${values[1]}$`, "m"), names);
  const detailRoute = APP.slice(APP.indexOf("def reaction_knowledge_detail("));
  assert.deepEqual(pySet(/_only_query\(request, \{([^}]*)\}\)/, detailRoute).sort(),
    Object.keys(plain(lib.DEFAULT_DETAIL_PAGING)).sort());
  // tool argument and chain keys, in the server's normalized order
  assert.deepEqual(pySet(/^_ARG_KEYS = frozenset\(\{([^}]*)\}\)/m, TOOL).sort(), ["chains", "numbering_map", "pdb_id", "structure"]);
  assert.deepEqual(pySet(/^_CHAIN_KEYS = frozenset\(\{([^}]*)\}\)/m, TOOL).sort(), ["chain_auth", "uniprot_accession"]);
  const normalized = /normalized = \{([^}]*)\}/.exec(TOOL)[1];
  const ok = lib.checkReactionForm(form({ chains: chainsWith(["A"]) }), OPTIONS);
  assert.deepEqual(Object.keys(ok.args), [...normalized.matchAll(/"(\w+)":/g)].map(item => item[1]));
});

test("fixed sentences RK1–RK6 and screen notes UK1–UK4 equal the backend constants and the spec, in order", () => {
  const statements = pyDictStrings("STATEMENTS");
  const notes = pyDictStrings("SCREEN_NOTES");
  assert.deepEqual(statements, SPEC_RK);
  assert.deepEqual(notes, SPEC_UK);
  assert.deepEqual(plain(lib.REACTION_STATEMENTS), SPEC_RK);
  assert.deepEqual(plain(lib.REACTION_SCREEN_NOTES), SPEC_UK);
  assert.deepEqual(Object.keys(lib.REACTION_STATEMENTS), ["RK1", "RK2", "RK3", "RK4", "RK5", "RK6"]);
  assert.deepEqual(Object.keys(lib.REACTION_SCREEN_NOTES), ["UK1", "UK2", "UK3", "UK4"]);
  const order = /^LIMITATIONS = tuple\(STATEMENTS\[key\] for key in \(([^)]*)\)\)/m.exec(K);
  assert.ok(order, "LIMITATIONS order not found");
  assert.deepEqual(plain(lib.REACTION_LIMITATIONS), [...order[1].matchAll(/"(RK\d)"/g)].map(item => SPEC_RK[item[1]]));
  // the M20 area shows UK2 / UK3 from its own module: the same text
  assert.equal(mutations.CATALYTIC_NOT_CHECKED_BADGE, lib.REACTION_SCREEN_NOTES.UK2);
  assert.equal(mutations.UNIPROT_SITES_NOTE, lib.REACTION_SCREEN_NOTES.UK3);
  // the import command named on screen is the script that exists
  assert.ok(fs.existsSync(path.join(__dirname, "../../scripts/import_reaction_references.py")));
  assert.equal(lib.REACTION_IMPORT_COMMAND, ".venv/bin/python scripts/import_reaction_references.py");
});

test("every admission, snapshot, result and section reason is \"한국어 (code)\"; unknown codes stay raw", () => {
  const codes = [...lib.ADMISSION_REASON_CODES, ...lib.SNAPSHOT_REASON_CODES, lib.RESULT_INVALID_REASON,
    lib.RESULT_TOO_LARGE_REASON, lib.TOO_MANY_LINKS_REASON, lib.MCSA_NOT_CHECKED_REASON, ...lib.UNIPROT_REASONS,
    lib.REACTIONS_NOT_CHECKED_REASON, ...lib.UNMATCHED_REASONS, ...lib.CONFLICT_REASONS, ...lib.LINK_REASONS,
    "input_invalid", "precondition", "resource_exceeded", "not_found", "run_corrupt", "method_evidence_invalid",
    "report_evidence_invalid"];
  assert.equal(codes.length, new Set(codes).size);
  for (const code of codes) {
    const text = lib.reactionReasonText(code);
    assert.ok(text.endsWith(` (${code})`) && /[가-힣]/.test(text), text);
  }
  for (const code of lib.SKIP_REASONS) assert.match(lib.skipReasonText(code), new RegExp(`^[^(]*[가-힣][^(]* \\(${code}\\)$`));
  assert.equal(lib.reactionReasonText("brand_new"), "brand_new");
  assert.equal(lib.reactionReasonText("toString"), "toString");
  assert.equal(lib.skipReasonText("constructor"), "constructor");
  // a closed label table per kind: coverage, row status, link status, accession source, flags, source names
  assert.deepEqual(Object.keys(lib.COVERAGE_LABEL), plain(lib.COVERAGE));
  assert.deepEqual(Object.keys(lib.ROW_STATUS_LABEL), plain(lib.ROW_STATUSES));
  assert.deepEqual(Object.keys(lib.LINK_STATUS_LABEL), plain(lib.LINK_STATUSES));
  assert.deepEqual(Object.keys(lib.ACCESSION_SOURCE_LABEL), plain(lib.ACCESSION_SOURCES));
  assert.deepEqual(Object.keys(lib.FLAG_LABEL), plain(lib.CHAIN_FLAGS));
  assert.deepEqual(Object.keys(lib.SOURCE_LABEL), plain(lib.REACTION_SOURCES));
  assert.deepEqual(Object.keys(lib.SKIP_REASON_LABEL), plain(lib.SKIP_REASONS));
  assert.deepEqual(Object.values(lib.AREA_STATE_LABEL), ["불러오는 중", "준비", "빈 결과", "실패", "사용할 수 없음"]);
});

// ---- request guards ----

test("structures: this run's structure and prepared_structure handles in creation order, nothing picked", () => {
  const events = [
    { seq: 1, type: "object_created", handle: "u", kind: "structure_source" },
    { seq: 2, type: "object_created", handle: S_RAW, kind: "structure" },
    { seq: 3, type: "object_created", handle: S, kind: "prepared_structure" },
    { seq: 4, type: "object_created", handle: "c", kind: "chemical_structure" },
    { seq: 5, type: "object_created", handle: S, kind: "prepared_structure" }];
  assert.deepEqual(plain(lib.reactionStructures(events)), plain(STRUCTURES));
  const fresh = plain(lib.emptyReactionForm());
  assert.deepEqual(fresh, { structure: null, pdbId: "", pdbIdConfirmed: false, chains: [], numberingMap: null });
  // a structure gives its polymer chains (file order, once), none selected, no accession; nothing else is kept
  const next = plain(lib.formForStructure(S, RESIDUES));
  assert.deepEqual(next, { structure: S, pdbId: "", pdbIdConfirmed: false, numberingMap: null, chains: [
    { chain_auth: "A", selected: false, accession: "" }, { chain_auth: "B", selected: false, accession: "" },
    { chain_auth: "C", selected: false, accession: "" }] });
  assert.deepEqual(plain(lib.setChainSelected(lib.formForStructure(S, RESIDUES), "B", true).chains.map(c => c.selected)),
    [false, true, false]);
  assert.equal(lib.setChainAccession(lib.formForStructure(S, RESIDUES), "C", "P36507").chains[2].accession, "P36507");
});

test("PDB ID: format [0-9][A-Za-z0-9]{3}, upper-cased, sent only after confirmation", () => {
  assert.equal(lib.normalizedPdbId(" 1s9i "), "1S9I");
  for (const bad of ["S9I1", "1S9", "1S9I0", "1S-I", "", "1s9 i"]) assert.equal(lib.normalizedPdbId(bad), null, bad);
  const unconfirmed = check({ pdbId: "1s9i", chains: chainsWith(["A"]) });
  assert.equal(unconfirmed.ok, true);
  assert.equal(unconfirmed.args.pdb_id, null);
  const confirmed = check({ pdbId: "1s9i", pdbIdConfirmed: true, chains: chainsWith(["A"]) });
  assert.equal(confirmed.args.pdb_id, "1S9I");
  assert.deepEqual(check({ pdbId: "S9I1", pdbIdConfirmed: true, chains: chainsWith(["A"]) }).errors,
    [{ field: "pdb_id", chain: null, text: "PDB ID 형식이 올바르지 않습니다(숫자 하나와 영숫자 셋, 예: 1S9I)." }]);
  // an unconfirmed bad suggestion is not sent and does not block
  assert.equal(check({ pdbId: "bad", chains: chainsWith(["A"]) }).ok, true);
});

test("accession format of spec 4.1 (case as is); a blank field is null", () => {
  for (const ok of ["P36507", "Q12345", "O14965", "A0A024R161", "A2BC19", "P0DTC2"]) assert.equal(lib.isAccession(ok), true, ok);
  for (const bad of ["p36507", "P3650", "P365077", "36507P", "P36507-2", "", "A0A024R16"]) assert.equal(lib.isAccession(bad), false, bad);
  const out = check({ chains: chainsWith(["A", " P36507 "], ["B", ""], ["C", "p36507"]) });
  assert.deepEqual(out.errors, [{ field: "chains", chain: "C", text: "UniProt accession 형식이 아닙니다: p36507 (대문자, 예: P36507)." }]);
  const sent = check({ chains: chainsWith(["A", " P36507 "], ["B", "  "]) });
  assert.deepEqual(sent.args.chains, [{ chain_auth: "A", uniprot_accession: "P36507" }, { chain_auth: "B", uniprot_accession: null }]);
});

test("request guard: every branch in admission order with its field; ok args in the server's shape", () => {
  const errors = (over, options) => check(over, options).errors.map(item => [item.field, item.chain, item.text]);
  assert.deepEqual(errors({ chains: chainsWith(["A"]) }, { ...OPTIONS, snapshot: null }),
    [["snapshot", null, lib.STATUS_LOADING_REASON]]);
  assert.deepEqual(errors({ chains: chainsWith(["A"]) }, { ...OPTIONS, snapshot: STATUS_BAD }),
    [["snapshot", null, "반응 참조 스냅샷의 매니페스트·파일 해시나 형식이 맞지 않음 (snapshot_invalid): 가져오기 명령으로 스냅샷을 먼저 설치하세요."]]);
  assert.deepEqual(errors({ structure: null, chains: chainsWith(["A"]) }), [["structure", null, "구조를 고르세요."]]);
  assert.deepEqual(errors({ structure: "obj://r2/prepared_structure/x", chains: chainsWith(["A"]) }),
    [["structure", null, "고른 구조가 이 run의 구조·전처리 구조가 아닙니다."]]);
  assert.deepEqual(errors({}), [["chains", null, "체인을 하나 이상 고르세요."]]);
  assert.deepEqual(errors({ chains: [{ chain_auth: "A", selected: true, accession: "" }, { chain_auth: "A", selected: true, accession: "" }] }),
    [["chains", "A", "같은 체인이 두 번 있습니다."]]);
  assert.deepEqual(errors({ chains: chainsWith(["A"]), numberingMap: MAP_RAW }),
    [["numbering_map", null, "고른 번호 대응이 이 구조의 것이 아닙니다."]]);
  assert.deepEqual(errors({ chains: chainsWith(["A"]), numberingMap: MAP_OLD, pdbId: "1S9I", pdbIdConfirmed: true }),
    [["numbering_map", null, "번호 대응의 PDB ID(9ZZZ)가 확인한 PDB ID(1S9I)와 다릅니다."]]);
  // the same map with the PDB ID unconfirmed (null) is not a mismatch (the server compares only two given IDs)
  assert.equal(check({ chains: chainsWith(["A"]), numberingMap: MAP_OLD }).ok, true);
  // several reasons at once, in order
  assert.deepEqual(errors({ structure: null, pdbId: "x", pdbIdConfirmed: true }, { ...OPTIONS, snapshot: STATUS_NONE })
    .map(([field]) => field), ["snapshot", "structure", "pdb_id", "chains"]);
  const ok = check({ pdbId: "1s9i", pdbIdConfirmed: true, chains: chainsWith(["B", "Q12345"], ["A"]), numberingMap: MAP });
  assert.deepEqual(ok, { ok: true, args: { structure: S, pdb_id: "1S9I",
    chains: [{ chain_auth: "A", uniprot_accession: null }, { chain_auth: "B", uniprot_accession: "Q12345" }], numbering_map: MAP } });
  // the raw structure is accepted too (both kinds); a map of the other structure is not
  const raw = plain(lib.checkReactionForm({ ...lib.formForStructure(S_RAW, RESIDUES), chains: chainsWith(["A"]), numberingMap: MAP_RAW }, OPTIONS));
  assert.equal(raw.ok, true);
  assert.equal(raw.args.structure, S_RAW);
  // the request block itself: reason only while the snapshot is missing or the run has no structure
  assert.equal(lib.requestUnavailableReason({ snapshot: null, structures: undefined }), lib.STATUS_LOADING_REASON);
  assert.equal(lib.requestUnavailableReason({ snapshot: STATUS_NONE, structures: STRUCTURES }),
    `사용할 수 없음: 반응 참조 스냅샷이 설치되지 않음 (not_installed). ${lib.IMPORT_HINT} ${lib.REACTION_IMPORT_COMMAND}`);
  assert.equal(lib.requestUnavailableReason({ snapshot: STATUS_OK, structures: [] }), lib.NO_STRUCTURE_REASON);
  assert.equal(lib.requestUnavailableReason({ snapshot: STATUS_OK, structures: STRUCTURES }), null);
  assert.equal(lib.requestUnavailableReason({ snapshot: STATUS_OK, structures: undefined }), null);
});

test("numbering map suggestions: newest same-structure map, requested accession first, a single SIFTS accession, never fused", () => {
  assert.deepEqual(plain(lib.mapsForStructure(MAPS, S).map(row => row.handle)), [MAP_OLD, MAP]);
  assert.deepEqual(plain(lib.mapsForStructure(MAPS, null)), []);
  assert.equal(lib.newestMapForStructure(MAPS, S).handle, MAP);
  assert.equal(lib.newestMapForStructure(MAPS, "obj://r1/prepared_structure/none"), null);
  assert.equal(lib.mapChainAccession(MAPS[1], "A"), "P36507");
  assert.equal(lib.mapChainAccession(MAPS[1], "B"), "Q12345");
  assert.equal(lib.mapChainAccession(MAPS[1], "C"), null);
  assert.equal(lib.mapChainAccession(MAPS[1], "Z"), null);
  const prefill = plain(lib.mapPrefill(MAPS, S, ["A", "B", "C"]));
  assert.deepEqual(prefill, { map: MAP, pdbId: "1S9I", accessions: { A: "P36507", B: "Q12345" } });
  assert.equal(lib.mapPrefill(MAPS, null, ["A"]), null);
  // the map's PDB ID (confirmed in M15) before the file's hint; none -> the hint
  assert.equal(lib.pdbIdSuggestion(prefill, "1ABC"), "1S9I");
  assert.equal(lib.pdbIdSuggestion({ ...prefill, pdbId: null }, "1ABC"), "1ABC");
  assert.equal(lib.pdbIdSuggestion(null, null), null);
  // filled into empty fields only; nothing is selected, confirmed or chosen
  const typed = lib.setChainAccession(lib.formForStructure(S, RESIDUES), "B", "P99999");
  const applied = plain(lib.applySuggestions(typed, "1S9I", prefill));
  assert.deepEqual(applied.chains, [{ chain_auth: "A", selected: false, accession: "P36507" },
    { chain_auth: "B", selected: false, accession: "P99999" }, { chain_auth: "C", selected: false, accession: "" }]);
  assert.deepEqual([applied.pdbId, applied.pdbIdConfirmed, applied.numberingMap], ["1S9I", false, null]);
  assert.equal(lib.applySuggestions({ ...typed, pdbId: "2XYZ" }, "1S9I", null).pdbId, "2XYZ");
  assert.equal(lib.applySuggestions({ ...typed, pdbId: "", pdbIdConfirmed: true }, "1S9I", null).pdbId, "");
});

test("PDB lookup: only an answer for the asked ID; \"이 accession 쓰기\" choices per chain, never applied", () => {
  const lookup = { pdb_id: "1A4I", entries: [
    { mcsa_id: 389, enzyme_name: "enzyme a", reference_uniprot_id: "P13995, P00001", chains: ["A", "B"] },
    { mcsa_id: 458, enzyme_name: "enzyme b", reference_uniprot_id: "P13995", chains: ["A"] },
    { mcsa_id: 500, enzyme_name: "enzyme c", reference_uniprot_id: "not-an-accession", chains: ["A"] }] };
  assert.equal(lib.pdbLookupMatches(lookup, "1A4I"), true);
  assert.equal(lib.pdbLookupMatches(lookup, "1S9I"), false);
  assert.equal(lib.pdbLookupMatches(null, "1A4I"), false);
  assert.equal(lib.pdbLookupMatches({ pdb_id: "1A4I" }, "1A4I"), false);
  assert.deepEqual(plain(lib.accessionSuggestions(lookup, "A")).map(item => [item.accession, item.mcsaId]),
    [["P13995", 389], ["P00001", 389]]);
  assert.deepEqual(plain(lib.accessionSuggestions(lookup, "B")).map(item => item.accession), ["P13995", "P00001"]);
  assert.deepEqual(plain(lib.accessionSuggestions(lookup, "C")), []);
  assert.deepEqual(plain(lib.accessionSuggestions(null, "A")), []);
  assert.equal(lib.accessionSuggestions(lookup, "A")[0].text, "P13995 · M-CSA 389 enzyme a (참조값, 계산 아님)");
  assert.equal(lib.pdbLookupText(lookup), "M-CSA 항목 3개가 PDB 1A4I를 적었습니다(참조값, 계산 아님).");
  const none = lib.pdbLookupText({ pdb_id: "1UBQ", entries: [] });
  assert.equal(none, "PDB 1UBQ를 적은 M-CSA 항목이 이 스냅샷에 없습니다. 촉매 잔기가 없다는 뜻이 아닙니다.");
  assert.doesNotMatch(none.replace("1UBQ", ""), /\d/);
  // the form only changes when the person presses the button
  const before = plain(lib.formForStructure(S, RESIDUES));
  lib.accessionSuggestions(lookup, "A");
  assert.deepEqual(plain(lib.formForStructure(S, RESIDUES)), before);
});

// ---- server refusals ----

test("server refusals: \"한국어 (code)\" beside its field (with the chain), 412 snapshot, 429 caps, other errors", () => {
  const refusal = (code, reason, extra = {}) => plain(lib.reactionRefusal({ message: "m", code,
    detail: reason === null ? undefined : { reason_code: reason, ...extra } }));
  const fields = { unknown_field: "request", structure_invalid: "structure", pdb_id_invalid: "pdb_id",
    chains_invalid: "chains", chain_not_found: "chains", accession_invalid: "chains", numbering_map_invalid: "numbering_map",
    structure_mismatch: "numbering_map", map_pdb_mismatch: "numbering_map" };
  assert.deepEqual(Object.keys(fields), plain(lib.ADMISSION_REASON_CODES));
  for (const [reason, field] of Object.entries(fields)) {
    const out = refusal("input_invalid", reason);
    assert.equal(out.field, field, reason);
    assert.equal(out.code, reason);
    assert.equal(out.text, `${lib.reactionReasonText(reason)}: m`);
  }
  assert.deepEqual(refusal("input_invalid", "chain_not_found", { chain_auth: "B" }), { field: "chains", chain: "B",
    code: "chain_not_found", text: "구조가 가리키는 모델에 이 체인의 사슬 잔기가 없음 (chain_not_found): m" });
  assert.equal(refusal("precondition", "not_installed").field, "snapshot");
  assert.equal(refusal("precondition", "snapshot_invalid").field, "snapshot");
  assert.equal(refusal("input_invalid", "result_invalid").field, "result");
  assert.deepEqual(refusal("resource_exceeded", "too_many_links", { limit: 2000 }), { field: "result", chain: null,
    code: "too_many_links", text: "연결 위치 수 상한 초과로 저장하지 않음 (too_many_links): 연결 위치가 상한 2000개를 넘어 " +
      "저장하지 않았습니다(자르지 않음). 번호 대응을 빼거나 체인을 줄여 다시 요청하세요." });
  assert.equal(refusal("resource_exceeded", "result_too_large", { limit: 1048576, actual: 2000000 }).text,
    "결과 크기 상한 초과로 저장하지 않음 (result_too_large): 결과가 2000000 바이트로 상한 1048576 바이트를 넘어 저장하지 " +
    "않았습니다(자르지 않음). 체인을 줄여 다시 요청하세요.");
  assert.deepEqual(refusal("cancelled", null), { field: "request", chain: null, code: "cancelled", text: "run이 취소됨 (cancelled): m" });
  assert.deepEqual(plain(lib.reactionRefusal("boom")), { field: "request", chain: null, code: null, text: "boom" });
  assert.equal(lib.reactionRefusal({ message: "" }).text, lib.REQUEST_FAILED_TEXT);
  // the command envelope
  const handle = { handle: RESULT, kind: "reaction_knowledge", schema: "reaction_knowledge@1", summary: {}, preview: [] };
  assert.deepEqual(plain(lib.reactionCommandOutcome({ ok: true, handle })), { ok: true, handle: RESULT });
  assert.equal(lib.reactionCommandOutcome({ ok: true, handle: { ...handle, kind: "other" } }).refusal.text, lib.NOT_A_RESULT_TEXT);
  assert.equal(lib.reactionCommandOutcome({ ok: false, error: "input_invalid", message: "x",
    detail: { reason_code: "accession_invalid", chain_auth: "A" } }).refusal.chain, "A");
  assert.equal(lib.reactionCommandOutcome({ ok: false, approval: { gate: "g", tool: "t", reason: "r" } }).refusal.text,
    lib.REQUEST_FAILED_TEXT);
});

// ---- reads ----

test("detail query carries the six paging values in a fixed order; page text and offsets come from server totals", () => {
  assert.equal(lib.reactionDetailQuery(), "chain_offset=0&chain_limit=10&row_offset=0&row_limit=50&feature_offset=0&feature_limit=50");
  assert.equal(lib.reactionDetailQuery({ chain_offset: 10, chain_limit: 10, row_offset: 200, row_limit: 200, feature_offset: 50,
    feature_limit: 1 }), "chain_offset=10&chain_limit=10&row_offset=200&row_limit=200&feature_offset=50&feature_limit=1");
  assert.equal(lib.pageText(6, 0, 6), "전체 6개 중 1–6번째");
  assert.equal(lib.pageText(120, 50, 50), "전체 120개 중 51–100번째");
  assert.equal(lib.pageText(0, 0, 0), "전체 0개 · 이 쪽에 없음");
  assert.equal(lib.pageText(null, 0, 0), "—");
  assert.equal(lib.nextOffset(120, 50, 50), 100);
  assert.equal(lib.nextOffset(100, 50, 50), null);
  assert.equal(lib.nextOffset(null, 0, 50), null);
  assert.equal(lib.previousOffset(0, 50), null);
  assert.equal(lib.previousOffset(30, 50), 0);
  assert.equal(lib.reactionDetailMatches(DETAIL), true);
  assert.equal(lib.reactionDetailMatches({ ...DETAIL, schema: "x" }), false);
  assert.equal(lib.reactionDetailMatches({ ...DETAIL, page: undefined }), false);
  assert.equal(lib.reactionDetailMatches(null), false);
});

test("snapshot block: not installed or invalid shows the reason and the import command only (no numbers)", () => {
  for (const status of [STATUS_NONE, STATUS_BAD]) {
    const view = plain(lib.reactionSnapshotView(status));
    assert.deepEqual(Object.keys(view).sort(), ["command", "hint", "reasonCode", "reasonText", "state"]);
    assert.equal(view.state, "unavailable");
    assert.equal(view.reasonCode, status.reason);
    assert.equal(view.command, lib.REACTION_IMPORT_COMMAND);
    for (const text of [view.reasonText, view.hint, view.command]) assert.doesNotMatch(text, /\d/);
  }
  assert.equal(lib.reactionSnapshotView(STATUS_NONE).reasonText, "반응 참조 스냅샷이 설치되지 않음 (not_installed)");
  // installed but malformed: still no numbers
  assert.equal(lib.reactionSnapshotView({ ...STATUS_OK, sources: null }).state, "unavailable");
  const ok = plain(lib.reactionSnapshotView(STATUS_OK));
  assert.equal(ok.state, "ready");
  assert.equal(ok.setHashShort, SET.slice(0, 12));
  assert.equal(ok.processedLabel, "공개 서버에서 가져온 가공본");
  assert.deepEqual(ok.sources.map(item => [item.label, item.date, item.licenseText, item.rowsText]), [
    ["M-CSA", "2026-10-08", "CC BY 4.0 (CC-BY-4.0)", "1003행"], ["UniProt", "2026-10-08", "CC BY 4.0 (CC-BY-4.0)", "1612행"],
    ["Rhea", "2026-10-08", "CC BY 4.0 (CC-BY-4.0)", "18611행"]]);
  assert.equal(ok.userNamedText, "직접 지정한 accession 1개");
  assert.equal(ok.skippedText, "가져올 때 건너뛴 accession 2개");
  assert.deepEqual(ok.skipped, [{ accession: "P12345", reasonText: "다른 accession으로 병합됨 (merged)", targetsText: "대상 P67890" },
    { accession: "Q11111", reasonText: "UniProt에서 폐기된 accession (obsolete)", targetsText: "—" }]);
  assert.deepEqual(ok.notes, [SPEC_RK.RK1, SPEC_UK.UK1]);
  assert.equal(ok.licenseNote, SPEC_RK.RK6);
  assert.equal(lib.reactionStatusMatches(STATUS_OK), true);
  assert.equal(lib.reactionStatusMatches({ installed: true }), false);
  assert.equal(lib.licenseText("other"), "other");
});

test("snapshot badges: \"이전 스냅샷 기준\" only against another active set, \"사용 중 스냅샷 없음\" without one", () => {
  assert.equal(lib.resultSnapshotBadge({ set_hash: SET2, same: false }), "stale");
  assert.equal(lib.resultSnapshotBadge({ set_hash: SET, same: true }), null);
  assert.equal(lib.resultSnapshotBadge({ set_hash: null, same: false }), "no_active_set");
  assert.equal(lib.listSnapshotBadge({ active: false }, true), "stale");
  assert.equal(lib.listSnapshotBadge({ active: true }, true), null);
  assert.equal(lib.listSnapshotBadge({ active: false }, false), "no_active_set");
  assert.equal(lib.listSnapshotBadge({ active: false }, null), null);
  assert.equal(lib.snapshotBadgeText("stale"), "이전 스냅샷 기준");
  assert.equal(lib.snapshotBadgeText("no_active_set"), "사용 중 스냅샷 없음");
  assert.equal(lib.snapshotBadgeText(null), null);
});

test("list items: server order, same structure only; counts that were not made are \"—\" with the reason, never 0", () => {
  const item = over => ({ handle: RESULT, structure_handle: S, structure_kind: "prepared_structure", pdb_id: "1S9I", chain_count: 2,
    covered_chain_count: 1, mcsa_rows: { matched: 2, unmatched: 2, conflict: 2 }, uniprot_feature_count: 2, null_result: false,
    set_hash: SET, active: true, ...over });
  assert.equal(lib.reactionListItemText(item()),
    "PDB 1S9I · 체인 2개 · M-CSA가 다룬 체인 1개 · M-CSA 행 대응됨 2 · 대응 없음 2 · 충돌 2 · UniProt 부위 2개");
  const unchecked = lib.reactionListItemText(item({ pdb_id: null, covered_chain_count: 0, mcsa_rows: null,
    uniprot_feature_count: null, null_result: true }));
  assert.equal(unchecked, "PDB ID — (주지 않음) · 체인 2개 · M-CSA — (PDB ID를 주지 않아 검사하지 않음) · UniProt 부위 — " +
    "(UniProt 절을 검사한 체인 없음) · 빈 결과");
  assert.doesNotMatch(unchecked.replace("체인 2개", ""), /\d/);
  assert.equal(lib.reactionListItemText(item({ covered_chain_count: 0, mcsa_rows: null })),
    "PDB 1S9I · 체인 2개 · M-CSA가 다룬 체인 0개 · M-CSA 행 — (M-CSA가 다룬 체인 없음) · UniProt 부위 2개");
  const items = [item({ handle: "h3", structure_handle: S_RAW }), item({ handle: "h2" }), item({ handle: "h1" })];
  assert.deepEqual(plain(lib.resultsForStructure(items, S).map(row => row.handle)), ["h2", "h1"]);
  assert.deepEqual(plain(lib.resultsForStructure(items, null)), []);
});

test("result view: per-chain M-CSA rows in server order with 7 fields (null as \"—\"), verbatim reference text, UK4", () => {
  const view = plain(lib.reactionResultView(DETAIL));
  assert.equal(view.pdbIdText, "1S9I");
  assert.equal(view.setHashShort, SET.slice(0, 12));
  assert.deepEqual([view.badge, view.badgeText], ["stale", "이전 스냅샷 기준"]);
  assert.equal(view.chainPageText, "전체 2개 중 1–2번째");
  assert.deepEqual(view.limitations, LIMITATIONS);
  assert.deepEqual(view.sources.map(item => item.label), ["M-CSA", "UniProt", "Rhea"]);
  const [a, b] = view.chains;
  // UK4 beside every chain M-CSA did not cover
  assert.equal(a.chainNote, null);
  assert.equal(b.chainNote, SPEC_UK.UK4);
  assert.equal(a.accessionText, "P36507 (번호 대응에서 가져옴)");
  assert.equal(b.accessionText, "Q12345 (사용자 입력)");
  assert.deepEqual(a.flags, [`${lib.FLAG_LABEL.accession_differs_from_mcsa} (accession_differs_from_mcsa)`]);
  assert.equal(a.mcsa.statusText, "검사함 (checked)");
  assert.equal(a.mcsa.coverageText, "M-CSA가 이 체인을 다룸 (covered)");
  assert.equal(a.mcsa.countsText, "대응됨 2 · 대응 없음 2 · 충돌 2");
  assert.equal(a.mcsa.rowPageText, "전체 6개 중 1–6번째");
  assert.deepEqual(a.mcsa.entries, [{ mcsaId: 282, text: "M-CSA 282 · enzyme two · UniProt P36507", ecsText: "EC 2.7.12.2" },
    { mcsaId: 300, text: "M-CSA 300 · enzyme three · UniProt —", ecsText: "EC —" }]);
  // the row order is exactly the server's (300 before 282), nothing sorted
  assert.deepEqual(a.mcsa.rows.map(row => [row.mcsaId, row.residueIndex]), ROWS_A.map(row => [row.mcsa_id, row.residue_index]));
  assert.deepEqual(a.mcsa.rows.map(row => row.statusText), ["대응됨 (matched)", "대응됨 (matched)", "충돌 (conflict)",
    "대응 없음 (unmatched)", "대응 없음 (unmatched)", "충돌 (conflict)"]);
  assert.deepEqual(a.mcsa.rows.map(row => row.reasonText), ["—", "—",
    "구조 잔기 이름이 M-CSA 잔기 이름과 다름 (residue_name_differs)", "이 번호의 사슬 잔기가 구조에 없음 (residue_not_in_structure)",
    "구조 잔기에 삽입 코드가 있음 (insertion_code_present)", "M-CSA 행끼리 잔기 이름이 다름 (mcsa_rows_disagree)"]);
  const [first, , conflict, missing, insertion, disagree] = a.mcsa.rows;
  assert.deepEqual(first.residue, { model_number: "1", chain_auth: "A", chain_label: "—", seq_auth: "210", seq_label: "—", icode: "",
    resname: "GLU" });
  assert.equal(first.residueText, "GLU auth A/210 icode \"\" label —/— 모델 1");
  assert.equal(first.listed.assembliesText, "—");
  assert.equal(first.isReferenceText, "기준 구조 아님 (is_reference false)");
  assert.equal(conflict.listed.code, "Ser");
  assert.equal(conflict.structureResnameText, "ALA");
  assert.equal(conflict.listed.assembliesText, "1, 2");
  assert.deepEqual([missing.residue, missing.residueText, missing.structureResnameText, missing.listed.residText,
    missing.listed.authResidText], [null, "— (구조 잔기 없음)", "—", "—", "999"]);
  assert.equal(insertion.residue.icode, "A");
  assert.equal(disagree.listed.code, "Asp/Glu");
  // M-CSA role text verbatim (an empty string stays empty; an empty role list is null, shown as no list)
  assert.deepEqual(first.reference, reference());
  assert.deepEqual(first.rolesText, ["group text / type text / function text / EMO_00001"]);
  assert.deepEqual([disagree.reference.roles_summary, disagree.reference.function_location_abv, disagree.reference.ptm,
    disagree.rolesText], ["", "", "", null]);
  assert.equal(lib.REFERENCE_COLUMN_LABEL, "M-CSA 원문, 계산 아님");
  // chain B: not covered -> "—" with the reason, never [] or 0
  assert.equal(b.mcsa.coverageText, "이 체인은 M-CSA 행에 없음 (chain_not_listed)");
  assert.deepEqual([b.mcsa.entries, b.mcsa.rows], [null, null]);
  for (const text of [b.mcsa.entriesText, b.mcsa.rowsText, b.mcsa.rowPageText, b.mcsa.countsText])
    assert.equal(text, "— (이 체인은 M-CSA 행에 없음 (chain_not_listed))");
});

test("result view: UniProt sites with link cells or the link reason, reactions with Rhea equations and in_snapshot", () => {
  const [a, b] = plain(lib.reactionResultView(DETAIL)).chains;
  assert.equal(a.uniprot.statusText, "검사함 (checked)");
  assert.deepEqual(a.uniprot.entry, { accession: "P36507", entryName: "ENTRY_HUMAN", proteinName: "—", organism: "Homo sapiens",
    sequenceLengthText: "서열 길이 400" });
  assert.equal(a.uniprot.linkText, "번호 대응으로 구조 잔기에 연결함 (numbering_map)");
  assert.equal(a.uniprot.featurePageText, "전체 2개 중 1–2번째");
  // feature order as stored (Binding site before Active site)
  assert.deepEqual(a.uniprot.features.map(item => [item.type, item.rangeText, item.description, item.ligandText]), [
    ["Binding site", "77–79", "", "ATP (ChEBI:CHEBI:30616)"], ["Active site", "208", "site text", "—"]]);
  const links = a.uniprot.features[0].links;
  assert.deepEqual(links.map(link => [link.position, link.statusText, link.uniprotResidueText, link.residueMatchText]), [
    [77, "번호 대응 행 있음 (mapped)", "G", "잔기 이름 같음 (residue_match true)"],
    [78, "번호 대응에 없음 (not_in_map)", "—", "—"],
    [79, "번호 대응 행 있음 (mapped)", "T", "잔기 이름 다름 (residue_match false)"]]);
  assert.equal(links[1].residueText, "— (번호 대응에 없음)");
  assert.equal(links[2].residue.seq_label, "—");
  // reactions: EC lists ([] is an empty list, null is "not contributed"), compounds, activities with equations
  assert.equal(a.reactions.ecMcsaText, "2.7.12.2");
  assert.equal(a.reactions.ecUniprotText, "빈 목록 ([])");
  assert.deepEqual(a.reactions.compounds, [{ mcsaId: 282, ecText: "2.7.12.2", items: [{ type: "reactant", chebiId: "15422", name: "ATP" }] },
    { mcsaId: 300, ecText: "—", items: [] }]);
  assert.deepEqual(a.reactions.activities, [{ reactionName: "A + B = C + D", ecText: "—", rhea: [
    { rheaId: "RHEA:17989", inSnapshot: true, inSnapshotText: "스냅샷에 있음 (in_snapshot true)", equationText: "A + B = C + D" },
    { rheaId: "RHEA:99999", inSnapshot: false, inSnapshotText: "스냅샷에 없음 (in_snapshot false)",
      equationText: "— (스냅샷에 없는 Rhea ID)" }] }]);
  // chain B: UniProt not available (skipped at import, the targets as recorded), reactions not checked
  assert.equal(b.uniprot.statusText, "사용할 수 없음 (not_available)");
  assert.equal(b.uniprot.reasonText, "가져올 때 건너뛴 accession (accession_skipped_at_import)");
  assert.equal(b.uniprot.skippedText, "가져올 때 건너뜀: 다른 accession으로 병합됨 (merged) · 대상 P99999");
  assert.deepEqual([b.uniprot.entry, b.uniprot.features], [null, null]);
  assert.equal(b.uniprot.featuresText, "— (가져올 때 건너뛴 accession (accession_skipped_at_import))");
  assert.equal(b.uniprot.linkText, "— (가져올 때 건너뛴 accession (accession_skipped_at_import))");
  assert.equal(b.reactions.statusText, "검사하지 않음 (not_checked)");
  for (const text of [b.reactions.ecMcsaText, b.reactions.ecUniprotText, b.reactions.compoundsText, b.reactions.activitiesText])
    assert.equal(text, "— (반응 정보를 준 출처가 없음 (no_source))");
  assert.deepEqual([b.reactions.compounds, b.reactions.activities], [null, null]);
});

test("result view: not checked, not available and not computed are \"—\" with a reason; [] stays an empty list; 0 only when counted", () => {
  const view = plain(lib.reactionResultView(DETAIL_NOT_CHECKED));
  assert.equal(view.pdbIdText, "— (PDB ID를 주지 않음 (pdb_id_not_given))");
  assert.equal(view.numberingMapText, "— (번호 대응을 주지 않아 연결하지 않음 (numbering_map_not_given))");
  assert.deepEqual([view.badge, view.badgeText], ["no_active_set", "사용 중 스냅샷 없음"]);
  const counts = Object.fromEntries(view.countRows.map(row => [row.key, row.text]));
  assert.deepEqual(counts, { chains: "1개", covered_chains: "— (PDB ID를 주지 않아 M-CSA를 검사하지 않음)",
    mcsa_rows: "— (PDB ID를 주지 않아 M-CSA를 검사하지 않음)", mcsa_entries: "— (PDB ID를 주지 않아 M-CSA를 검사하지 않음)",
    uniprot_features: "— (UniProt 절을 검사한 체인 없음)", linked_positions: "— (번호 대응으로 연결한 부위 없음)",
    rhea: "— (UniProt 촉매 활동이 있는 체인 없음)" });
  for (const [key, text] of Object.entries(counts)) if (key !== "chains") assert.doesNotMatch(text, /\d/, key);
  assert.deepEqual([view.nullResult, view.nullResultText], [true, lib.NULL_RESULT_TEXT]);
  const [chain] = view.chains;
  assert.equal(chain.chainNote, SPEC_UK.UK4);
  assert.equal(chain.accessionText, "— (accession을 주지 않음 (accession_not_given))");
  assert.equal(chain.mcsa.coverageText, "— (검사하지 않음)");
  assert.equal(chain.mcsa.rowsText, "— (PDB ID를 주지 않음 (pdb_id_not_given))");
  assert.equal(chain.uniprot.featuresText, "— (accession을 주지 않음 (accession_not_given))");
  assert.equal(chain.reactions.ecMcsaText, "— (반응 정보를 준 출처가 없음 (no_source))");
  // checked-but-empty is not "not checked": [] lists and counted zeros
  const empty = plain(lib.reactionResultView(DETAIL_EMPTY));
  const emptyCounts = Object.fromEntries(empty.countRows.map(row => [row.key, row.text]));
  assert.equal(emptyCounts.covered_chains, "0개");
  assert.equal(emptyCounts.mcsa_rows, "— (M-CSA가 다룬 체인 없음)");
  assert.equal(emptyCounts.uniprot_features, "Active site 0 · Binding site 0 · Site 0");
  assert.equal(emptyCounts.rhea, "스냅샷에 있음 0 · 스냅샷에 없음 0");
  assert.deepEqual([empty.badge, empty.badgeText], [null, null]);
  const [c] = empty.chains;
  assert.equal(c.mcsa.coverageText, "이 PDB ID는 스냅샷에 없음 (pdb_not_in_snapshot)");
  assert.equal(c.chainNote, SPEC_UK.UK4);
  assert.deepEqual([c.uniprot.features, c.uniprot.featuresText, c.uniprot.featurePageText], [[], "빈 목록 ([])", "전체 0개 · 이 쪽에 없음"]);
  assert.equal(c.uniprot.linkText, "— (번호 대응을 주지 않아 연결하지 않음 (numbering_map_not_given))");
  assert.deepEqual([c.reactions.ecMcsaText, c.reactions.ecUniprotText], ["— (M-CSA가 이 체인을 다루지 않음)", "빈 목록 ([])"]);
  assert.deepEqual([c.reactions.compounds, c.reactions.compoundsText], [null, "— (M-CSA가 이 체인을 다루지 않음)"]);
  assert.deepEqual([c.reactions.activities, c.reactions.activitiesText], [[], "빈 목록 ([])"]);
});

test("five area states: no run and no capability record are unavailable; a missing snapshot is not; empty result is not a failure", () => {
  const base = { runId: "r1", capability: { available: true, reason: null } };
  const state = over => plain(lib.reactionPanelState({ ...base, ...over }));
  assert.deepEqual(state({ runId: null }), { state: "unavailable", reason: lib.NO_RUN_REASON });
  assert.deepEqual(state({ capability: null }), { state: "unavailable", reason: lib.CAPABILITY_REASON });
  assert.deepEqual(state({ capability: undefined }), { state: "loading" });
  assert.deepEqual(state({ loading: true }), { state: "loading" });
  assert.deepEqual(state({ error: "실패함" }), { state: "failed", message: "실패함" });
  assert.deepEqual(state({}), { state: "ready" });
  assert.deepEqual(state({ capability: { available: false, reason: "not installed" } }), { state: "ready" });
  assert.deepEqual(state({ detail: { null_result: true } }), { state: "scientific_null", message: lib.NULL_RESULT_TEXT });
  assert.deepEqual(state({ detail: { null_result: false } }), { state: "ready" });
  for (const text of [lib.NO_RUN_REASON, lib.CAPABILITY_REASON, lib.NULL_RESULT_TEXT]) assert.doesNotMatch(text, /\d/);
});

test("late responses: applied only for the same run, result handle and request number; reports for the same run", () => {
  const live = { runId: "r1", handle: RESULT, seq: 4 };
  assert.equal(lib.reactionResponseCurrent({ ...live }, live), true);
  assert.equal(lib.reactionResponseCurrent({ ...live, runId: "r2" }, live), false);
  assert.equal(lib.reactionResponseCurrent({ ...live, handle: "other" }, live), false);
  assert.equal(lib.reactionResponseCurrent({ ...live, seq: 3 }, live), false);
  assert.equal(lib.reactionResponseCurrent({ ...live, runId: null }, { ...live, runId: null }), false);
  assert.equal(lib.reactionReportSavedForRun(live, "r1"), true);
  assert.equal(lib.reactionReportSavedForRun(live, "r2"), false);
  assert.equal(lib.reactionReportSavedForRun({ ...live, runId: null }, null), false);
  assert.ok(lib.REACTION_AREAS.includes("detail") && lib.REACTION_AREAS.includes("command"));
  const artifact = { handle: "R", markdown_handle: "M", markdown: "", manifest: { schema: "method_report_manifest@1",
    analysis_type: "reaction_knowledge", result_handle: RESULT } };
  assert.equal(lib.reactionReportMatches(artifact, RESULT), true);
  assert.equal(lib.reactionReportMatches(artifact, "other"), false);
  assert.equal(lib.reactionReportMatches({ manifest: { ...artifact.manifest, analysis_type: "residue_numbering" } }, RESULT), false);
  assert.equal(reportLibrary.reportKindLabel({ kind: lib.REACTION_REPORT_TYPE, handle: "h", target_handle: RESULT, created_seq: 1 }),
    lib.REACTION_REPORT_LABEL);
});

// ---- wording: no ranking, recommendation, importance, activity or effect claim in this module's own strings ----

/** Top-level alternatives of a regex source (split on "|" outside groups and classes). */
function alternatives(source) {
  const out = [];
  let depth = 0, inClass = false, current = "";
  for (let i = 0; i < source.length; i++) {
    const ch = source[i];
    if (ch === "\\") { current += ch + source[++i]; continue; }
    if (inClass) { inClass = ch !== "]"; current += ch; continue; }
    if (ch === "[") inClass = true;
    else if (ch === "(") depth++;
    else if (ch === ")") depth--;
    if (ch === "|" && depth === 0) { out.push(current); current = ""; continue; }
    current += ch;
  }
  out.push(current);
  return out.filter(Boolean).map(item => item.replace(/\(\?:/g, "("));
}
function pyRegex(source, marker) {
  const start = source.indexOf(marker);
  const block = source.slice(start, source.indexOf(", re.IGNORECASE)", start));
  return [...block.matchAll(/r"([^"]*)"/g)].map(item => item[1]).join("");
}

test("the screen check is at least the M26 report check (M15 + M20 + M26 words) plus 최고·우수", () => {
  const reportWords = [pyRegex(backend("numbering_reports.py"), "INTERPRETIVE = re.compile("),
    pyRegex(backend("mutation_reports.py"), "INTERPRETIVE = re.compile("), pyRegex(REPORTS, "INTERPRETIVE = re.compile(")]
    .flatMap(alternatives);
  const mine = new Set(alternatives(lib.REACTION_FORBIDDEN.source));
  for (const word of reportWords) assert.ok(mine.has(word), word);
  assert.equal(lib.REACTION_FORBIDDEN.flags, "gi");
  for (const word of ["순위", "추천", "최고", "우수", "중요", "핵심", "필수", "활성", "점수", "ΔΔG", "안정성", "친화도", "개선",
    "rank", "best", "recommend", "important", "essential", "critical", "key residue", "active", "activity", "score", "affinity",
    "stability", "stabilize", "improve", "predicted", "highest", "winner", "메커니즘이 유지", "mechanism is preserved",
    "효과", "변이 효과", "effect", "effects"])
    assert.ok(lib.reactionForbiddenWords(`이 잔기는 ${word}`).length, word);
  assert.deepEqual(plain(lib.reactionForbiddenWords("촉매 잔기 · 반응 · 효소")), []);
  // spec §2 "효과": none of the fixed sentences RK1–RK6 / UK1–UK4 says it, so the exemption is not what keeps them clean
  for (const line of lib.REACTION_FIXED_LINES) assert.doesNotMatch(line, /효과|effect/i, line);
  assert.deepEqual(plain(lib.reactionForbiddenWords("Active site 1 · Binding site 2 · Site 0 · side effect")), ["effect"]);
});

test("fixed sentences are exempt only verbatim on their own line; UniProt site type names are quoted reference terms", () => {
  // RK2 and RK5 say "활성" (in the negative): exempt as exact lines only
  assert.ok(lib.reactionForbiddenWords(SPEC_RK.RK2 + " ").length);
  assert.ok(lib.reactionForbiddenWords(`메모 ${SPEC_RK.RK5}`).length);
  for (const line of lib.REACTION_FIXED_LINES) assert.deepEqual(plain(lib.reactionForbiddenWords(line)), [], line);
  assert.deepEqual(plain(lib.REACTION_FIXED_LINES), [...Object.values(SPEC_RK), ...Object.values(SPEC_UK)]);
  assert.deepEqual(plain(lib.REACTION_EXEMPT_TERMS), pyTuple("SITE_TYPES"));
  assert.deepEqual(plain(lib.reactionForbiddenWords("Active site 1 · Binding site 2 · Site 0")), []);
  assert.ok(lib.reactionForbiddenWords("active residue").length);
  assert.ok(lib.reactionForbiddenWords("활성 부위").length);
});

function screenStrings() {
  const texts = [];
  const collect = value => {
    if (typeof value === "string") texts.push(value);
    else if (Array.isArray(value)) value.forEach(collect);
    else if (value && typeof value === "object") Object.values(value).forEach(collect);
  };
  for (const value of Object.values(lib)) if (typeof value !== "function" && !(value instanceof RegExp)) collect(value);
  const lookup = { pdb_id: "1A4I", entries: [{ mcsa_id: 389, enzyme_name: "enzyme a", reference_uniprot_id: "P13995",
    chains: ["A"] }] };
  collect([
    [...lib.ADMISSION_REASON_CODES, ...lib.SNAPSHOT_REASON_CODES, ...lib.UNMATCHED_REASONS, ...lib.CONFLICT_REASONS,
      ...lib.UNIPROT_REASONS, ...lib.LINK_REASONS, "result_invalid", "result_too_large", "too_many_links", "no_source",
      "pdb_id_not_given", "cancelled", "not_found"].map(lib.reactionReasonText),
    lib.SKIP_REASONS.map(lib.skipReasonText),
    [DETAIL, DETAIL_NOT_CHECKED, DETAIL_EMPTY].map(lib.reactionResultView),
    [STATUS_OK, STATUS_NONE, STATUS_BAD].map(lib.reactionSnapshotView),
    lib.accessionSuggestions(lookup, "A"), lib.pdbLookupText(lookup), lib.pdbLookupText({ pdb_id: "1UBQ", entries: [] }),
    ["stale", "no_active_set"].map(lib.snapshotBadgeText),
    lib.reactionListItemText({ handle: RESULT, structure_handle: S, structure_kind: "prepared_structure", pdb_id: null,
      chain_count: 1, covered_chain_count: 0, mcsa_rows: null, uniprot_feature_count: null, null_result: true, set_hash: SET,
      active: false }),
    lib.requestUnavailableReason({ snapshot: STATUS_NONE, structures: [] }),
    lib.requestUnavailableReason({ snapshot: STATUS_OK, structures: [] }),
    lib.checkReactionForm({ ...lib.emptyReactionForm(), pdbId: "x", pdbIdConfirmed: true }, { ...OPTIONS, snapshot: STATUS_NONE }),
    lib.checkReactionForm(form({ chains: chainsWith(["A", "bad"]), numberingMap: MAP_RAW }), OPTIONS),
    lib.checkReactionForm(form({ chains: chainsWith(["A"]), numberingMap: MAP_OLD, pdbId: "1S9I", pdbIdConfirmed: true }), OPTIONS),
    ...[...lib.ADMISSION_REASON_CODES, "too_many_links", "result_too_large", "not_installed"].map(reason =>
      lib.reactionRefusal({ message: "", code: "input_invalid", detail: { reason_code: reason, limit: 1, actual: 2 } })),
    lib.reactionPanelState({ runId: null }), lib.reactionPanelState({ runId: "r", capability: null }),
    lib.reactionPanelState({ runId: "r", capability: { available: true, reason: null }, detail: { null_result: true } }),
    lib.pageText(3, 0, 3), lib.pageText(0, 0, 0),
  ]);
  return texts;
}

test("every user-visible string of this module passes the wording check (fixed lines excepted); nothing reads as a ranking", () => {
  const texts = screenStrings();
  assert.ok(texts.length > 300, `collected ${texts.length}`);
  for (const text of texts) assert.deepEqual(plain(lib.reactionForbiddenWords(text)), [], text);
  for (const text of texts) assert.doesNotMatch(text, /\d+\s*위(?!치)|\d+\s*등(?!록)|\btop\b|상위|하위|가장/i, text);
});

test("the module never sorts, reverses or recounts: no sort / reverse calls and no arithmetic on stored counts", () => {
  for (const pattern of [/\.sort\(/, /\.reverse\(/, /\.toSorted\(/, /counts\.\w+\s*[-+]/, /[-+]\s*\w*counts\.\w+/,
    /\.length\s*-\s*\w/, /\b(rank|best|score|delta|difference|improv)\w*\s*[:=]/i])
    assert.ok(!pattern.test(LIB_SOURCE), String(pattern));
});
