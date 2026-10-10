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
const lib = load("kinase-precedents", { "./numbering": numbering });
const reportLibrary = load("report-library");
const plain = value => JSON.parse(JSON.stringify(value));
const LIB_SOURCE = fs.readFileSync(path.join(__dirname, "../src/lib/kinase-precedents.ts"), "utf8");
/** The module's code without comments (block comments and whole-line `//` comments), for the code-level checks. */
const LIB_CODE = LIB_SOURCE.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

// ---- closed sets, caps and fixed sentences are read from the backend files themselves ----
const backend = name => fs.readFileSync(path.join(__dirname, `../../backend/mw/${name}`), "utf8");
const K = backend("precedent_constants.py");
const READS = backend("kinase_precedents_reads.py");
const TOOL = backend("tools/kinase_precedents.py");
const REPORTS = backend("kinase_precedents_reports.py");
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

// spec .dryforge/spec.md 9.1, verbatim (the hand copy the module and the backend are compared with)
const SPEC_KP = {
  KP1: "전례는 kbase_kinase가 논문에서 기계로 추출한 미검수 기록이며 ProtView가 계산하거나 판정한 것이 아니다.",
  KP2: "방향과 크기는 kbase 규칙 v1이 숫자 또는 본문에서 산출한 값이며 논문의 결론도 ProtView의 판정도 아니고, 측정 변화마다 대상 역할(on_target·off_target·not_applicable)이 함께 있다.",
  KP3: "kbase 기계 검사는 kbase가 만들 때 한 결과를 그대로 보인 것이며 ProtView는 논문 원문과 대조하지 않았다. 파일 이름(moves·moves_flagged)은 모든 검사의 통과 여부를 뜻하지 않는다.",
  KP4: "전례가 없다는 표시는 포함한 파일에 기록이 없다는 뜻이며 선행 연구가 없다는 뜻이 아니다. 포함하지 않은 파일의 전례와 표적이 해석되지 않은 전례는 이 결과에 연결하지 않았다.",
  KP5: "표적(UniProt)이 같은 전례만 연결했다. 다른 키나아제의 전례는 연결하지 않았고, 변이·리간드·구조와의 일치는 판단하지 않았다.",
  KP6: "전례 개수와 목록 순서는 순위·추천·유망도·성공률을 뜻하지 않는다.",
  KT1: "kbase_kinase 비공개 저장소 자료 · 이용 조건 명시 없음 · ChEMBL 유래 필드 포함 · 외부 공개 전 확인",
};
const SPEC_UP = {
  UP1: "원문 대조 안 함: ProtView에는 논문 원문이 없어 인용이 원문과 같은지 확인하지 않았다. 'ProtView 무결성 확인'은 가져온 파일과 레코드의 해시, 인용 길이, 논문 쪽 위치 존재만 뜻한다.",
  UP2: "moves_flagged 파일의 전례 N건은 포함하지 않았다.",
  UP3: "변이 표기는 kbase 기록 그대로이며 이 구조의 서열과 대조하지 않았다.",
  UP4: "PDB 언급은 kbase가 기록한 것(근거 수준 포함)이며 이 구조와의 일치를 판단하지 않았다.",
  UP5: "표적이 해석되지 않은 전례 N건(세트 전체)이 있어 어느 체인에도 연결하지 못했다.",
};

// ---- fixtures (LABELLED SYNTHETIC: made-up accessions, PMIDs, move IDs and texts; no kbase_kinase record) ----
const RUN = "r1";
const S = `obj://${RUN}/prepared_structure/${"1".repeat(64)}`;
const MAP = `obj://${RUN}/residue_numbering_map/${"3".repeat(64)}`;
const MAP_OLD = `obj://${RUN}/residue_numbering_map/${"5".repeat(64)}`;
const MAP_EMPTY = `obj://${RUN}/residue_numbering_map/${"6".repeat(64)}`;
const RESULT = `obj://${RUN}/kinase_precedents/${"4".repeat(64)}`;
const SET = "a".repeat(64);
const SET2 = "b".repeat(64);
const CHECKS = ["qualifier_consistency", "tag_vocab", "schema", "target_in_reference", "quote_in_source",
  "cross_parser_numbers", "chembl_crosscheck", "pmid_exists", "structure_ref_exists", "duplicate"];
const KBASE = { commit: "c0de".repeat(10), dist_commit: "d157".repeat(10), dist_commit_date: "2026-10-01T09:00:00+09:00",
  dirty: false, kb_version: "kbv1:synthetic-fixture", schema_version: "1", effect_rules_version: "1",
  vocab_version: "synthetic-vocab-version", source_snapshots: ["SNAP-synthetic"], origin: "kbase_kinase processed dist" };
const SET_SUMMARY = { records: { moves: 7, moves_flagged: 6 }, references: 6,
  unresolved_target_records: { moves: 2, moves_flagged: 3 },
  unresolved_names: [{ name_as_written: "SYN-NAME", moves: 1, moves_flagged: 2 },
    { name_as_written: null, moves: 1, moves_flagged: 1 }],
  unresolved_names_total: 2,
  resolution_basis_counts: [{ basis: "gene", moves: 4, moves_flagged: 2 }, { basis: "name_token", moves: 1, moves_flagged: 1 }] };
const PSET = { set_hash: SET, imported_at: "2026-10-10T00:00:00Z", importer_version: "precedent_import/1", kbase: KBASE,
  files: ["dist/moves.jsonl", "dist/moves_flagged.jsonl", "dist/references.jsonl"].map(name =>
    ({ name, path: `files/${name}`, sha256: "c".repeat(64), bytes: 100, rows: 6 })),
  bibliography_snapshot: { snapshot_id: "SNAP-pubmed-synthetic", date: "2026-10-01", license: "synthetic-license",
    origin: "kbase_kinase processed ref/pubmed", file: { name: "pubmed/2026-10-01/documents.jsonl",
      path: "files/pubmed/2026-10-01/documents.jsonl", sha256: "d".repeat(64), bytes: 50, rows: 5 } } };
const STATUS_OK = { schema: "precedent_reference_status@1", installed: true, reason: null, set_hash: SET,
  imported_at: "2026-10-10T00:00:00Z", importer_version: "precedent_import/1", kbase: KBASE,
  files: [{ name: "dist/moves.jsonl", rows: 7, bytes: 700 }, { name: "dist/moves_flagged.jsonl", rows: 6, bytes: 600 },
    { name: "dist/references.jsonl", rows: 6, bytes: 300 }],
  bibliography: { snapshot_id: "SNAP-pubmed-synthetic", date: "2026-10-01", license: "synthetic-license", rows: 5 },
  set_summary: SET_SUMMARY };
const STATUS_NONE = { schema: "precedent_reference_status@1", installed: false, reason: "not_installed", set_hash: null,
  imported_at: null, importer_version: null, kbase: null, files: null, bibliography: null, set_summary: null };
const STATUS_BAD = { ...STATUS_NONE, reason: "snapshot_invalid" };

const effect = over => ({ metric: "IC50", assay: "SYNTHETIC assay", assay_context: "synthetic context",
  target_ref: "SYN-KINASE", target_role: "on_target", before: { qualifier: "=", value: 100, unit: "nM" },
  after: { qualifier: "<", value: 10.5, unit: "nM" }, direction: "unchanged", direction_basis: "numeric",
  magnitude_bucket: "small", comparable: true, comparability_reason: null, fold_change: 9.5,
  chembl_crosscheck: { status: "not_checked", activity_id: null }, evidence: { synthetic: "fixture" }, ...over });
const checks = (over = {}) => ({ ...Object.fromEntries(CHECKS.map(name => [name, { status: "pass" }])), ...over });
const record = (move_id, over = {}) => ({ review_status: "unreviewed", schema_version: 1, move_id,
  source: { pmid: "900001", locations: [{ kind: "table", page: 3, table_index: 1, row: 2, figure_id: null, panel: null,
    bbox: null }] },
  target: { gene: "SYNG", uniprot: "P0SYN1", name_as_written: "SYN-KINASE", resolution_basis: "gene", candidates: [],
    variant: "not_reported" },
  structure_ref: null, structure_link_reason: null, structure_ref_from: null, structure_links: [], interactions: [],
  observation: { text: "SYNTHETIC observation text", quote: "SYNTHETIC quote four words", quote_truncated: false,
    evidence: { synthetic: "fixture" } },
  change: { description: "SYNTHETIC change", from_compound: "SYN-a", to_compound: "SYN-b", smiles_from: null,
    smiles_to: null },
  effects: [effect()], tradeoffs: [], mutations: [], tags: { site: ["bp_I_A"], goal: ["solubility"], tactic: ["scaffold_hop"] },
  proposed_tags: [], figures: [], checks: checks(),
  extraction: { model: "synthetic-model", provider: "synthetic", prompt_version: "fixture-1", run_at: "2026-10-01T00:00:00Z",
    chunks: [], dropped_effects: 0, notes: ["SYNTHETIC note not shown"] },
  content_hash: `sha256:${"e".repeat(64)}`, ...over });
const integrityOf = over => ({ hash_verified: true, observation_quote_words: 4, tradeoff_quote_words: [],
  quotes_within_limit: true, locations_have_page: true, ...over });
const item = (file, rec, integrity = {}) => ({ file, integrity: integrityOf(integrity), record: rec });

const R1 = item("moves", record("MOVE-0001", { tags: { site: ["bp_I_A", "back"], goal: ["solubility"], tactic: [] },
  source: { pmid: "900001", locations: [{ kind: "table", page: 3, table_index: 1, row: 2, figure_id: null, panel: null,
    bbox: null }, { kind: "text", page: 5 }] },
  checks: checks({ duplicate: { status: "fail", candidate_ids: [] }, pmid_exists: { status: "lookup_failed", reason: "r" },
    schema: { status: "fail", error_paths: [] }, quote_in_source: { status: "pass", missing_paths: [],
      quote_assembled: [{ path: ["observation", "quote"], fragment_count: 2, block_index: 0, page: 3 }] } }),
  observation: { text: "SYNTHETIC observation text", quote: "SYNTHETIC quote four words", quote_truncated: true,
    evidence: {} },
  effects: [effect(), effect({ target_role: "off_target", direction: "unknown", direction_basis: "text",
    magnitude_bucket: "unknown", fold_change: null, comparable: false, comparability_reason: "SYNTHETIC reason",
    before: { qualifier: null, value: null, unit: null }, after: { qualifier: null, value: null, unit: "nM" } })],
  tradeoffs: [{ text: "SYNTHETIC tradeoff text", quote: "SYNTHETIC tradeoff quote", quote_truncated: false, evidence: {} },
    { text: "SYNTHETIC tradeoff without quote", quote: null, quote_truncated: false, evidence: {} }],
  structure_ref: "0SYN", structure_link_reason: "SYNTHETIC link reason", structure_ref_from: "paper",
  structure_links: [{ pdb_id: "0SYN", chain: "A", ligand: "SYN", basis: "paper_context", confidence_note: "SYNTHETIC note",
    structure_id: "STRUCT-SYN-1", candidates: [] }],
  interactions: [{ interaction: "SYNTHETIC contact class", aa: "LYS", uniprot_resnum: 33, klifs_position: 17,
    change: "SYNTHETIC change", before_distance_a: null, after_distance_a: 3.1, anchor: "SYN", anchor_basis: "fixture",
    vocabulary: "fixture@1", source: "fixture", evidence: { synthetic: "fixture" } }] }),
{ tradeoff_quote_words: [3, null] });
const R2 = item("moves", record("MOVE-0010", { source: { pmid: "900002", locations: [{ kind: "figure", page: 7 }] },
  target: { gene: null, uniprot: "P0SYN1", name_as_written: "SYN tok", resolution_basis: "name_token", candidates: ["SYNG"],
    variant: "A10V" } }), { quotes_within_limit: false, observation_quote_words: 30 });
const R3 = item("moves_flagged", record("MOVE-0100", { source: { pmid: "900003", locations: [{ kind: "text", page: 1 }] },
  tags: { site: ["front"], goal: [], tactic: ["ring_fusion"] } }));
const BIBLIOGRAPHY = { "900001": { title: "SYNTHETIC title one", journal: "SYN J", year: "2020", doi: "10.0/syn", pmc: null },
  "900002": null, "900003": { title: null, journal: null, year: null, doi: null, pmc: "PMC0" } };
const ref = (ref_id, over = {}) => ({ ref_id, gene: "SYNG", klifs_name: "SYN", group: "SYNGROUP", family: "SYNFAM",
  coverage: "partial", content_hash: `sha256:${"f".repeat(64)}`, ...over });
const tcounts = over => ({ moves: 0, moves_flagged: 0, variants: [], tags: { site: [], goal: [], tactic: [] },
  resolution_basis: [], ...over });
const chain = (chain_auth, status, reason, accessions, over = {}) => ({ chain_auth, total_residue_count: 300,
  mapped_residue_count: accessions.length ? 280 : 0, cross_check: true, cross_check_absent_reason: null, status, reason,
  accession: status === "linked" ? accessions[0] : null, accessions, ...over });
const CHAINS = [chain("A", "linked", null, ["P0SYN1"]), chain("B", "linked", null, ["P0SYN1"],
  { cross_check: false, cross_check_absent_reason: "pdb_id_not_given" }),
chain("C", "not_linked", "no_mapped_residues", []), chain("D", "not_linked", "multiple_accessions", ["P0SYN8", "P0SYN9"]),
chain("E", "linked", null, ["Q0SYN2"]), chain("F", "linked", null, ["R0SYN3"])];
const TARGETS_IN = [
  { accession: "P0SYN1", chains: ["A", "B"], status: "precedents_found", references: [ref("REF-1"), ref("REF-2", { gene: null })],
    excluded_flagged: null, counts: tcounts({ moves: 2, moves_flagged: 1,
      variants: [{ variant: "A10V", count: 1 }, { variant: "not_reported", count: 2 }],
      tags: { site: [{ term: "back", count: 1 }, { term: "bp_I_A", count: 2 }, { term: "front", count: 1 }],
        goal: [{ term: "solubility", count: 2 }], tactic: [{ term: "ring_fusion", count: 1 }, { term: "scaffold_hop", count: 1 }] },
      resolution_basis: [{ basis: "gene", count: 2 }, { basis: "name_token", count: 1 }] }) },
  { accession: "Q0SYN2", chains: ["E"], status: "none_in_included_files", references: [ref("REF-3")], excluded_flagged: null,
    counts: tcounts({}) },
  { accession: "R0SYN3", chains: ["F"], status: "not_in_kbase_references", references: [], excluded_flagged: null,
    counts: tcounts({}) }];
const FACETS = { file: [{ value: "moves", count: 2 }, { value: "moves_flagged", count: 1 }],
  site: [{ value: "back", count: 1 }, { value: "bp_I_A", count: 2 }, { value: "front", count: 1 }],
  goal: [{ value: "solubility", count: 2 }], tactic: [{ value: "ring_fusion", count: 1 }, { value: "scaffold_hop", count: 1 }],
  variant: [{ value: "A10V", count: 1 }, { value: "not_reported", count: 2 }] };
const LIMITATIONS = ["KP1", "KP2", "KP3", "KP4", "KP5", "KP6"].map(key => SPEC_KP[key]);
const DETAIL = { schema: "kinase_precedents_detail@1", handle: RESULT, method_version: "mw.kinase_precedents/v1",
  numbering_map: { handle: MAP }, structure: { handle: S, structure_kind: "prepared_structure", model_number: 1 },
  pdb_id: "0SY5", include_flagged: true, record_format: "kbase_record_minus_2_paths@1", precedent_set: PSET, chains: CHAINS,
  targets_overview: TARGETS_IN, set_summary: SET_SUMMARY,
  counts: { chains: 6, linked_chains: 4, not_linked_chains: 2, targets: 3, records: { moves: 2, moves_flagged: 1 },
    excluded_moves_flagged: null },
  null_result: false, limitations: LIMITATIONS, page: { target: "P0SYN1", total: 3, filtered_total: 3, offset: 0, limit: 25 },
  facets: FACETS, records: [R1, R2, R3], bibliography: BIBLIOGRAPHY, active_set: { set_hash: SET2, same: false } };
const TARGETS_EX = [
  { ...TARGETS_IN[0], excluded_flagged: 1, counts: { ...TARGETS_IN[0].counts, moves_flagged: null } },
  { ...TARGETS_IN[1], excluded_flagged: 2, counts: { ...TARGETS_IN[1].counts, moves_flagged: null } },
  { ...TARGETS_IN[2], excluded_flagged: 0, counts: { ...TARGETS_IN[2].counts, moves_flagged: null } }];
const DETAIL_EXCLUDED = { ...DETAIL, include_flagged: false, targets_overview: TARGETS_EX,
  counts: { ...DETAIL.counts, records: { moves: 2, moves_flagged: null }, excluded_moves_flagged: 3 },
  page: { ...DETAIL.page, total: 2, filtered_total: 2 }, facets: { ...FACETS, file: [{ value: "moves", count: 2 }] },
  records: [R1, R2], active_set: { set_hash: SET, same: true } };
const DETAIL_NO_TARGET = { ...DETAIL, include_flagged: false, pdb_id: null, chains: [CHAINS[2]], targets_overview: [],
  counts: { chains: 1, linked_chains: 0, not_linked_chains: 1, targets: 0, records: { moves: 0, moves_flagged: null },
    excluded_moves_flagged: 0 },
  null_result: true, page: { target: null, total: null, filtered_total: null, offset: 0, limit: 25 }, facets: null,
  records: [], bibliography: {}, active_set: { set_hash: null, same: false } };

const chainDetail = (chain_auth, mapped) => ({ chain_auth, methods_run: ["sifts"], cross_check: false,
  cross_check_absent_reason: "pdb_id_not_given", sifts: null, alignment: null, klifs: [],
  counts: { mapped, unmapped: 1, conflict: 0 } });
const mapRow = (handle, created_seq, details, row_count) => ({ handle, structure: S, structure_kind: "prepared_structure",
  model_number: 1, pdb_id: "0SY5", chains: details.map(detail => detail.chain_auth), cross_checked_chains: [], set_hash: "h",
  counts: { mapped: 1, unmapped: 0, conflict: 0 }, row_count, null_result: false, created_seq, stale_snapshot: false,
  chain_details: details });
const MAPS = [mapRow(MAP_OLD, 4, [chainDetail("A", 2)], 3),
  mapRow(MAP, 9, [chainDetail("A", 2), chainDetail("B", 0), chainDetail("C", 3)], 9),
  mapRow(MAP_EMPTY, 2, [], 0)];
const row = (chain_auth, status, uniprot_accession) => ({ residue: { chain_auth }, status, uniprot_accession });
const MAP_ROWS = [row("A", "mapped", "P0SYN1"), row("A", "mapped", "P0SYN1"), row("A", "conflict", null),
  row("A", "unmapped", null), row("B", "unmapped", null), row("C", "mapped", "P0SYN8"), row("C", "mapped", "P0SYN9"),
  row("C", "mapped", "P0SYN8"), row("C", "unmapped", null)];
const OPTIONS = { snapshot: STATUS_OK, maps: MAPS };
const form = over => ({ ...lib.formForMap(MAPS[1]), ...over });
const check = (over, options = OPTIONS) => plain(lib.checkPrecedentForm(form(over), options));

// ---- constants and fixed wording ----

test("closed sets, caps and names equal backend/mw/precedent_constants.py", () => {
  for (const [name, value] of [["SNAPSHOT_REASON_CODES", lib.SNAPSHOT_REASON_CODES],
    ["ADMISSION_REASON_CODES", lib.ADMISSION_REASON_CODES], ["CHAIN_STATUSES", lib.CHAIN_STATUSES],
    ["CHAIN_REASONS", lib.CHAIN_REASONS], ["TARGET_STATUSES", lib.TARGET_STATUSES], ["FILTER_KEYS", lib.FILTER_KEYS],
    ["SORT_KEYS", lib.SORT_KEYS], ["SORT_ORDERS", lib.SORT_ORDERS], ["FILE_SOURCES", lib.FILE_SOURCES],
    ["CHECK_NAMES", lib.CHECK_NAMES], ["LOCATION_KINDS", lib.LOCATION_KINDS]])
    assert.deepEqual(plain(value), pyTuple(name), name);
  assert.equal(lib.ADMISSION_REASON_CODES.length, 5);
  assert.deepEqual(plain(lib.SORT_KEYS), ["move_id", "pmid", "year", "variant", "file"]);
  assert.deepEqual(plain(lib.TAG_AXES), [.../^TAG_AXES = \{([^}]*)\}/m.exec(K)[1].matchAll(/"(\w+)":/g)].map(m => m[1]));
  for (const [ts, py] of [["PRECEDENT_TOOL", "TOOL"], ["PRECEDENT_KIND", "KIND"], ["PRECEDENT_SCHEMA", "SCHEMA"],
    ["PRECEDENT_METHOD_VERSION", "METHOD_VERSION"], ["PRECEDENT_STATUS_SCHEMA", "STATUS_SCHEMA"],
    ["PRECEDENT_DETAIL_SCHEMA", "DETAIL_SCHEMA"], ["PRECEDENT_RECORD_FORMAT", "RECORD_FORMAT"],
    ["RESULT_TOO_LARGE_REASON", "RESULT_TOO_LARGE_REASON"], ["RESULT_INVALID_REASON", "RESULT_INVALID_REASON"]])
    assert.equal(lib[ts], pyString(py), ts);
  for (const name of ["MAX_RESULT_BYTES", "MAX_QUERY_CHARS", "PAGE_LIMIT_MIN", "PAGE_LIMIT_MAX", "RECORDS_PAGE_DEFAULT",
    "LIST_PAGE_DEFAULT", "MAX_UNRESOLVED_NAMES"])
    assert.equal(lib[name], pyInt(name), name);
  const removed = /^REMOVED_PATHS = \((.*)\)$/m.exec(K)[1];
  assert.deepEqual(plain(lib.REMOVED_PATHS), [...removed.matchAll(/\(([^()]*)\)/g)]
    .map(group => [...group[1].matchAll(/"([^"]+)"/g)].map(m => m[1]).join(".")));
  assert.equal(lib.PRECEDENT_REPORT_TYPE, pyString("ANALYSIS_TYPE", REPORTS));
  assert.equal(lib.PROCESSED_LABEL, pyString("PROCESSED_LABEL", REPORTS));
  assert.equal(lib.REFERENCE_NOTE, pyString("REFERENCE_NOTE", REPORTS));
  // tool argument keys and the server's normalized key order; the detail read's query keys
  assert.deepEqual(pySet(/^_ARG_KEYS = frozenset\(\{([^}]*)\}\)/m, TOOL).sort(), ["chains", "include_flagged", "numbering_map"]);
  const normalized = /normalized = \{([^}]*)\}/.exec(TOOL)[1];
  const ok = lib.checkPrecedentForm(form({}), OPTIONS);
  assert.deepEqual(Object.keys(ok.args), [...normalized.matchAll(/"(\w+)":/g)].map(item => item[1]));
  assert.match(READS, /^DETAIL_QUERY_KEYS = \("target", \*K\.FILTER_KEYS, "sort", "order", "limit", "offset"\)$/m);
  assert.match(READS, /^RECORD_LIMIT_DEFAULT, RECORD_LIMIT_MAX = K\.RECORDS_PAGE_DEFAULT, K\.PAGE_LIMIT_MAX$/m);
  assert.match(READS, /^LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX = K\.LIST_PAGE_DEFAULT, K\.PAGE_LIMIT_MAX$/m);
});

test("fixed sentences KP1–KP6, KT1 and screen notes UP1–UP5 equal the backend constants and the spec, in order", () => {
  assert.deepEqual(pyDictStrings("STATEMENTS"), SPEC_KP);
  assert.deepEqual(pyDictStrings("SCREEN_NOTES"), SPEC_UP);
  assert.deepEqual(plain(lib.PRECEDENT_STATEMENTS), SPEC_KP);
  assert.deepEqual(plain(lib.PRECEDENT_SCREEN_NOTES), SPEC_UP);
  assert.deepEqual(Object.keys(lib.PRECEDENT_STATEMENTS), ["KP1", "KP2", "KP3", "KP4", "KP5", "KP6", "KT1"]);
  assert.deepEqual(Object.keys(lib.PRECEDENT_SCREEN_NOTES), ["UP1", "UP2", "UP3", "UP4", "UP5"]);
  const order = /^LIMITATIONS = tuple\(STATEMENTS\[key\] for key in \(([^)]*)\)\)/m.exec(K);
  assert.ok(order, "LIMITATIONS order not found");
  assert.deepEqual(plain(lib.PRECEDENT_LIMITATIONS), [...order[1].matchAll(/"(KP\d)"/g)].map(item => SPEC_KP[item[1]]));
  assert.deepEqual(pyTuple("NUMBERED_NOTES"), ["UP2", "UP5"]);
  // UP2 / UP5 with N filled exactly like the server's screen_note (first "N건" -> "<n>건", 0 included)
  assert.equal(lib.screenNote("UP2", 0), "moves_flagged 파일의 전례 0건은 포함하지 않았다.");
  assert.equal(lib.screenNote("UP2", 66), "moves_flagged 파일의 전례 66건은 포함하지 않았다.");
  assert.equal(lib.screenNote("UP5", 396), "표적이 해석되지 않은 전례 396건(세트 전체)이 있어 어느 체인에도 연결하지 못했다.");
  assert.equal(lib.screenNote("UP3"), SPEC_UP.UP3);
  for (const bad of [-1, 1.5, null, undefined, "3"]) assert.throws(() => lib.screenNote("UP2", bad));
  assert.throws(() => lib.screenNote("UP1", 3));
  // the import command named on screen is the script that exists (it takes --from)
  const importer = path.join(__dirname, "../../scripts/import_precedent_snapshots.py");
  assert.ok(fs.existsSync(importer));
  assert.match(fs.readFileSync(importer, "utf8"), /add_argument\("--from"/);
  assert.equal(lib.PRECEDENT_IMPORT_COMMAND, ".venv/bin/python scripts/import_precedent_snapshots.py --from <kbase_kinase 경로>");
  assert.equal(lib.EFFECTS_HEADER, "측정 변화(kbase 추출 effects)");
  assert.equal(lib.PROCESSED_LABEL, "kbase_kinase 가공본 · 미검수 · 기계 추출");
});

test("every admission, snapshot, result and chain reason is \"한국어 (code)\"; unknown codes stay raw", () => {
  const codes = [...lib.ADMISSION_REASON_CODES, ...lib.SNAPSHOT_REASON_CODES, lib.RESULT_INVALID_REASON,
    lib.RESULT_TOO_LARGE_REASON, ...lib.CHAIN_REASONS, "input_invalid", "precondition", "resource_exceeded", "transient",
    "fatal", "not_found", "run_corrupt", "method_evidence_invalid", "report_evidence_invalid", "cancelled"];
  assert.equal(codes.length, new Set(codes).size);
  for (const code of codes) {
    const text = lib.precedentReasonText(code);
    assert.ok(text.endsWith(` (${code})`) && /[가-힣]/.test(text), text);
  }
  assert.equal(lib.precedentReasonText("brand_new"), "brand_new");
  assert.equal(lib.precedentReasonText("toString"), "toString");
  assert.deepEqual(Object.keys(lib.CHAIN_STATUS_LABEL), plain(lib.CHAIN_STATUSES));
  assert.deepEqual(Object.keys(lib.TARGET_STATUS_LABEL), plain(lib.TARGET_STATUSES));
  assert.deepEqual(Object.keys(lib.LOCATION_KIND_LABEL), plain(lib.LOCATION_KINDS));
  assert.deepEqual(Object.keys(lib.SORT_LABEL), plain(lib.SORT_KEYS));
  assert.deepEqual(Object.values(lib.AREA_STATE_LABEL), ["불러오는 중", "준비", "빈 결과", "실패", "사용할 수 없음"]);
  // the three target status phrases of spec 8 (precedents_found takes its N from the counts)
  assert.deepEqual(plain(lib.TARGET_STATUS_LABEL), { precedents_found: "전례 N건",
    none_in_included_files: "포함한 파일에 이 표적의 전례 기록 없음",
    not_in_kbase_references: "kbase에 이 표적 참조가 없음(전례 없음과 다름)" });
});

// ---- request guards ----

test("numbering map: this run's newest is preselected (never submitted); chains default to all, moves_flagged off", () => {
  assert.equal(lib.newestMap(MAPS).handle, MAP);
  assert.equal(lib.newestMap([]), null);
  assert.deepEqual(plain(lib.emptyPrecedentForm()), { numberingMap: null, chains: [], includeFlagged: false });
  assert.deepEqual(plain(lib.formForMap(MAPS[1])), { numberingMap: MAP, includeFlagged: false, chains: [
    { chain_auth: "A", selected: true }, { chain_auth: "B", selected: true }, { chain_auth: "C", selected: true }] });
  assert.equal(lib.formForMap(MAPS[1], true).includeFlagged, true);
  assert.deepEqual(plain(lib.formForMap(null)), { numberingMap: null, includeFlagged: false, chains: [] });
  const off = lib.setPrecedentChainSelected(lib.formForMap(MAPS[1]), "B", false);
  assert.deepEqual(off.chains.map(choice => choice.selected), [true, false, true]);
  assert.equal(lib.setIncludeFlagged(off, true).includeFlagged, true);
});

test("request guard: every branch in admission order with its field; ok args in the server's shape", () => {
  const errors = (over, options) => check(over, options).errors.map(item => [item.field, item.chain, item.text]);
  assert.deepEqual(errors({}, { ...OPTIONS, snapshot: null }), [["snapshot", null, lib.STATUS_LOADING_REASON]]);
  assert.deepEqual(errors({}, { ...OPTIONS, snapshot: STATUS_NONE }), [["snapshot", null,
    "키나아제 전례 참조 스냅샷이 설치되지 않음 (not_installed): 가져오기 명령으로 스냅샷을 먼저 설치하세요."]]);
  assert.deepEqual(errors({}, { ...OPTIONS, snapshot: STATUS_BAD }).map(([field, , text]) => [field, text.includes("(snapshot_invalid)")]),
    [["snapshot", true]]);
  assert.deepEqual(errors({ numberingMap: null }), [["numbering_map", null, "번호 대응 결과를 고르세요."]]);
  assert.deepEqual(errors({ numberingMap: "obj://r2/residue_numbering_map/x" }),
    [["numbering_map", null, "고른 번호 대응이 이 run의 것이 아닙니다."]]);
  assert.deepEqual(errors({ numberingMap: MAP_EMPTY, chains: [] }), [["numbering_map", null, "고른 번호 대응에 체인이 없습니다."],
    ["chains", null, "체인을 하나 이상 고르세요."]]);
  assert.deepEqual(errors({ includeFlagged: "yes" }), [["include_flagged", null,
    "moves_flagged 파일 전례 포함 여부는 켬 또는 끔이어야 합니다."]]);
  assert.deepEqual(errors({ chains: [{ chain_auth: "A", selected: false }] }), [["chains", null, "체인을 하나 이상 고르세요."]]);
  assert.deepEqual(errors({ chains: [{ chain_auth: "A", selected: true }, { chain_auth: "A", selected: true }] }),
    [["chains", "A", "같은 체인이 두 번 있습니다."]]);
  assert.deepEqual(errors({ chains: [{ chain_auth: "Z", selected: true }] }), [["chains", "Z", "고른 번호 대응에 없는 체인입니다."]]);
  // several reasons at once, in the admission order (snapshot, map, flag, chains)
  assert.deepEqual(errors({ numberingMap: null, includeFlagged: 1, chains: [] }, { ...OPTIONS, snapshot: STATUS_NONE })
    .map(([field]) => field), ["snapshot", "numbering_map", "include_flagged", "chains"]);
  // every chain selected -> chains null (the same normalized call); a subset in the map's order, not the click order
  assert.deepEqual(check({}), { ok: true, args: { numbering_map: MAP, chains: null, include_flagged: false } });
  assert.deepEqual(check({ includeFlagged: true, chains: [{ chain_auth: "C", selected: true }, { chain_auth: "B", selected: false },
    { chain_auth: "A", selected: true }] }), { ok: true, args: { numbering_map: MAP, chains: ["A", "C"], include_flagged: true } });
  // chains the screen shows as "연결 안 함" can still be sent (the server returns the reason in the result)
  assert.deepEqual(check({ chains: [{ chain_auth: "B", selected: true }] }).args.chains, ["B"]);
  // the request block itself: reason only while the snapshot is missing or the run has no numbering map
  assert.equal(lib.requestUnavailableReason({ snapshot: null, maps: undefined }), lib.STATUS_LOADING_REASON);
  assert.equal(lib.requestUnavailableReason({ snapshot: STATUS_NONE, maps: MAPS }),
    `사용할 수 없음: 키나아제 전례 참조 스냅샷이 설치되지 않음 (not_installed). ${lib.IMPORT_HINT} ${lib.PRECEDENT_IMPORT_COMMAND}`);
  assert.equal(lib.requestUnavailableReason({ snapshot: STATUS_OK, maps: [] }), lib.NO_MAP_REASON);
  assert.equal(lib.requestUnavailableReason({ snapshot: STATUS_OK, maps: MAPS }), null);
  assert.equal(lib.requestUnavailableReason({ snapshot: STATUS_OK, maps: undefined }), null);
});

test("chain previews: no mapped row -> \"연결 안 함 (no_mapped_residues)\"; fused mapped rows -> multiple_accessions", () => {
  // without the rows only the mapped count is known: a chain with mapped rows is not prejudged
  const before = plain(lib.chainPreviews(MAPS[1], null));
  assert.deepEqual(before.map(item => [item.chainAuth, item.status, item.reason]),
    [["A", null, null], ["B", "not_linked", "no_mapped_residues"], ["C", null, null]]);
  assert.equal(before[0].text, lib.PREVIEW_PENDING_TEXT);
  assert.equal(before[1].text, "연결 안 함 (번호 대응에 mapped 잔기 행이 없음 (no_mapped_residues))");
  assert.equal(before[1].mappedText, "mapped 잔기 행 0개");
  // a partial read is not used
  assert.deepEqual(plain(lib.chainPreviews(MAPS[1], MAP_ROWS.slice(0, 5))).map(item => item.status), [null, "not_linked", null]);
  // every row read: the server rule (distinct accessions of the chain's mapped rows; conflict / unmapped ignored)
  const after = plain(lib.chainPreviews(MAPS[1], MAP_ROWS));
  assert.deepEqual(after.map(item => [item.chainAuth, item.status, item.reason, item.accessions]), [
    ["A", "linked", null, ["P0SYN1"]], ["B", "not_linked", "no_mapped_residues", []],
    ["C", "not_linked", "multiple_accessions", ["P0SYN8", "P0SYN9"]]]);
  assert.equal(after[0].text, "연결 예정: accession P0SYN1 (서버가 결과로 정함)");
  assert.equal(after[2].text, "연결 안 함 (mapped 잔기의 accession이 둘 이상(융합 단백질 등) (multiple_accessions): P0SYN8, P0SYN9)");
});

// ---- server refusals ----

test("server refusals: \"한국어 (code)\" beside its field (with the chain), 412 snapshot, other errors", () => {
  const refusal = (code, reason, extra = {}) => plain(lib.precedentRefusal({ message: "m", code,
    detail: reason === null ? undefined : { reason_code: reason, ...extra } }));
  const fields = { unknown_field: "request", numbering_map_invalid: "numbering_map",
    include_flagged_invalid: "include_flagged", chains_invalid: "chains", chain_not_in_map: "chains" };
  assert.deepEqual(Object.keys(fields), plain(lib.ADMISSION_REASON_CODES));
  for (const [reason, field] of Object.entries(fields)) {
    const out = refusal("input_invalid", reason);
    assert.deepEqual([out.field, out.code, out.text, out.sizeAdvice], [field, reason, `${lib.precedentReasonText(reason)}: m`, null]);
  }
  assert.deepEqual(refusal("input_invalid", "chain_not_in_map", { chain_auth: "Z" }), { field: "chains", chain: "Z",
    code: "chain_not_in_map", text: "번호 대응에 없는 체인 (chain_not_in_map): m", sizeAdvice: null });
  assert.equal(refusal("precondition", "not_installed").field, "snapshot");
  assert.equal(refusal("precondition", "snapshot_invalid").field, "snapshot");
  assert.equal(refusal("input_invalid", "result_invalid").field, "result");
  assert.deepEqual(refusal("cancelled", null), { field: "request", chain: null, code: "cancelled",
    text: "run이 취소됨 (cancelled): m", sizeAdvice: null });
  assert.deepEqual(plain(lib.precedentRefusal("boom")), { field: "request", chain: null, code: null, text: "boom", sizeAdvice: null });
  assert.equal(lib.precedentRefusal({ message: "" }).text, lib.REQUEST_FAILED_TEXT);
  // the command envelope
  const handle = { handle: RESULT, kind: "kinase_precedents", schema: "kinase_precedents@1", summary: {}, preview: [] };
  assert.deepEqual(plain(lib.precedentCommandOutcome({ ok: true, handle })), { ok: true, handle: RESULT });
  assert.equal(lib.precedentCommandOutcome({ ok: true, handle: { ...handle, kind: "other" } }).refusal.text, lib.NOT_A_RESULT_TEXT);
  assert.equal(lib.precedentCommandOutcome({ ok: false, error: "input_invalid", message: "x",
    detail: { reason_code: "chain_not_in_map", chain_auth: "Q" } }).refusal.chain, "Q");
  assert.equal(lib.precedentCommandOutcome({ ok: false, approval: { gate: "g", tool: "t", reason: "r" } }).refusal.text,
    lib.REQUEST_FAILED_TEXT);
});

test("429 result_too_large: which targets fit alone and whether turning moves_flagged off fits (server sizes)", () => {
  const detail = { reason_code: "result_too_large", limit: 1048576, actual: 1604884, size_without_flagged: 900000,
    target_sizes: [{ accession: "P00001", chains: ["A"], bytes: 855798 }, { accession: "P00002", chains: ["B", "C"], bytes: 1100000 }] };
  const out = plain(lib.precedentRefusal({ message: "server text", code: "resource_exceeded", detail }));
  assert.equal(out.field, "result");
  assert.equal(out.code, "result_too_large");
  assert.equal(out.text, "결과 크기 상한 초과로 저장하지 않음 (result_too_large): 결과 정규 JSON 1604884 B가 상한 1048576 B를 넘어 " +
    "저장하지 않았습니다(자르지 않음). moves_flagged 파일 전례 포함을 끄면 900000 B(상한 안). 표적별 단독 요청: " +
    "P00001(체인 A)만 요청하면 855798 B(상한 안); P00002(체인 B, C)만 요청하면 1100000 B(상한 초과). 체인을 나눠 요청하거나 " +
    "moves_flagged 파일 전례 포함을 끄세요.");
  assert.deepEqual(out.sizeAdvice.withoutFlagged, { bytesText: "900000 B", fits: true,
    text: "moves_flagged 파일 전례 포함을 끄면 900000 B(상한 안)" });
  assert.deepEqual(out.sizeAdvice.targets.map(item => [item.accession, item.chainsText, item.fits]),
    [["P00001", "체인 A", true], ["P00002", "체인 B, C", false]]);
  // already off: no moves_flagged advice
  const off = plain(lib.precedentRefusal({ code: "resource_exceeded", detail: { ...detail, size_without_flagged: null } }));
  assert.equal(off.sizeAdvice.withoutFlagged, null);
  assert.doesNotMatch(off.text, /끄면/);
  // a malformed 429 detail falls back to the plain refusal text
  const bad = plain(lib.precedentRefusal({ message: "m", code: "resource_exceeded",
    detail: { reason_code: "result_too_large", limit: 1 } }));
  assert.deepEqual([bad.field, bad.text, bad.sizeAdvice], ["result", "결과 크기 상한 초과로 저장하지 않음 (result_too_large): m", null]);
});

// ---- detail query: target, filters, the five sort keys, page ----

test("detail query: fixed key order, repeated tag keys, trimmed search; the page restarts on any change", () => {
  const base = lib.defaultPrecedentQuery();
  assert.deepEqual(plain(base), { target: null, filters: { file: null, site: [], goal: [], tactic: [], variant: null, q: "" },
    sort: "move_id", order: "asc", limit: 25, offset: 0 });
  assert.deepEqual(plain(lib.checkPrecedentQuery(base)), { ok: true, query: "sort=move_id&order=asc&limit=25&offset=0" });
  const query = { target: "P0SYN1", filters: { file: "moves_flagged", site: ["bp_I_A", "front"], goal: ["solubility"],
    tactic: ["ring_fusion"], variant: "A10V", q: "  SYN text  " }, sort: "year", order: "desc", limit: 10, offset: 20 };
  const out = plain(lib.checkPrecedentQuery(query));
  assert.equal(out.query, "target=P0SYN1&file=moves_flagged&site=bp_I_A&site=front&goal=solubility&tactic=ring_fusion&" +
    "variant=A10V&q=SYN+text&sort=year&order=desc&limit=10&offset=20");
  // every key is one the server accepts (DETAIL_QUERY_KEYS), in its order
  const allowed = ["target", ...pyTuple("FILTER_KEYS"), "sort", "order", "limit", "offset"];
  const keys = [...new URLSearchParams(out.query).keys()];
  assert.deepEqual(keys.filter((key, i) => keys.indexOf(key) === i), allowed.filter(key => keys.includes(key)));
  // a blank search is no search
  assert.equal(lib.checkPrecedentQuery({ ...base, filters: { ...base.filters, q: "   " } }).query,
    "sort=move_id&order=asc&limit=25&offset=0");
  // 100 characters (code points, as the server counts) pass; 101 do not
  assert.equal(lib.checkPrecedentQuery({ ...base, filters: { ...base.filters, q: "z".repeat(100) } }).ok, true);
  assert.equal(lib.checkPrecedentQuery({ ...base, filters: { ...base.filters, q: "\u{1F600}".repeat(100) } }).ok, true);
  assert.deepEqual(plain(lib.checkPrecedentQuery({ ...base, filters: { ...base.filters, q: "z".repeat(101) } })),
    { ok: false, errors: ["검색어는 100자 이하입니다."] });
  // changing target clears filters; filters / sort reset the offset; tag terms toggle in clicking order
  const moved = { ...query, offset: 50 };
  assert.deepEqual(plain(lib.withTarget(moved, "Q0SYN2")), { ...plain(moved), target: "Q0SYN2", filters: plain(lib.emptyFilters()),
    offset: 0 });
  assert.equal(lib.withFilters(moved, lib.emptyFilters()).offset, 0);
  assert.deepEqual(plain(lib.withSort(moved, "pmid", "asc")), { ...plain(moved), sort: "pmid", order: "asc", offset: 0 });
  assert.equal(lib.withOffset(base, 25).offset, 25);
  const toggled = lib.toggleTagTerm(lib.toggleTagTerm(lib.emptyFilters(), "site", "front"), "site", "bp_I_A");
  assert.deepEqual(plain(toggled.site), ["front", "bp_I_A"]);
  assert.deepEqual(plain(lib.toggleTagTerm(toggled, "site", "front").site), ["bp_I_A"]);
});

test("sorting is limited to the five keys of spec 6: no effect, direction or magnitude sort can be sent", () => {
  assert.deepEqual(plain(lib.SORT_OPTIONS.map(option => option.value)), ["move_id", "pmid", "year", "variant", "file"]);
  for (const key of lib.SORT_KEYS) assert.equal(lib.isSortKey(key), true, key);
  const base = lib.defaultPrecedentQuery("P0SYN1");
  for (const bad of ["direction", "magnitude_bucket", "fold_change", "effects", "target_role", "score", "count", "", "Move_id"]) {
    assert.equal(lib.isSortKey(bad), false, bad);
    const out = plain(lib.checkPrecedentQuery({ ...base, sort: bad }));
    assert.equal(out.ok, false, bad);
    assert.deepEqual(out.errors, ["정렬은 move_id·pmid·year·variant·file 다섯 가지 중 하나만 고를 수 있습니다."]);
  }
  for (const [over, error] of [[{ order: "up" }, "정렬 방향은 asc 또는 desc입니다."], [{ limit: 0 }, "쪽 크기는 1–100입니다."],
    [{ limit: 101 }, "쪽 크기는 1–100입니다."], [{ limit: 1.5 }, "쪽 크기는 1–100입니다."],
    [{ offset: -1 }, "쪽 시작 위치는 0 이상의 정수입니다."],
    [{ filters: { ...base.filters, file: "flagged" } }, "파일 필터는 moves 또는 moves_flagged입니다."]])
    assert.deepEqual(plain(lib.checkPrecedentQuery({ ...base, ...over })).errors, [error], JSON.stringify(over));
  assert.equal(lib.checkPrecedentQuery({ ...base, limit: 100 }).ok, true);
  assert.equal(lib.checkPrecedentQuery({ ...base, limit: 1 }).ok, true);
});

test("filter choices come from the result's facets (server order and counts), never from the vocabulary", () => {
  const options = plain(lib.filterOptions(FACETS));
  assert.deepEqual(options.file, [{ value: "moves", text: "moves 파일 (2건)" }, { value: "moves_flagged", text: "moves_flagged 파일 (1건)" }]);
  assert.deepEqual(options.site.map(item => item.value), ["back", "bp_I_A", "front"]);
  assert.deepEqual(options.variant, [{ value: "A10V", text: "A10V (1건)" }, { value: "not_reported", text: "not_reported (2건)" }]);
  assert.equal(lib.filterOptions(null), null);
  assert.deepEqual(plain(lib.filterOptions({ file: [], site: [], goal: [], tactic: [], variant: [] })).goal, []);
  // the module carries no vocabulary list: choices are only what the target's records use
  assert.doesNotMatch(LIB_SOURCE, /SITE_TERMS|GOAL_TERMS|TACTIC_TERMS|allosteric_non_atp|degrader_conversion/);
});

test("page text, next / previous offsets come from the server's totals; no target is \"—\" with the reason", () => {
  assert.equal(lib.recordPageText(DETAIL.page, 3), "전체 3건 · 필터 결과 3건 · 1–3번째");
  assert.equal(lib.recordPageText({ target: "P", total: 120, filtered_total: 60, offset: 25, limit: 25 }, 25),
    "전체 120건 · 필터 결과 60건 · 26–50번째");
  assert.equal(lib.recordPageText({ target: "P", total: 6, filtered_total: 0, offset: 0, limit: 25 }, 0),
    "전체 6건 · 필터 결과 0건 · 이 쪽에 없음");
  assert.equal(lib.recordPageText(DETAIL_NO_TARGET.page, 0), "— (연결된 표적 없음)");
  assert.equal(lib.nextOffset({ target: "P", total: 120, filtered_total: 60, offset: 25, limit: 25 }), 50);
  assert.equal(lib.nextOffset({ target: "P", total: 120, filtered_total: 50, offset: 25, limit: 25 }), null);
  assert.equal(lib.nextOffset(DETAIL_NO_TARGET.page), null);
  assert.equal(lib.previousOffset({ target: "P", total: 9, filtered_total: 9, offset: 0, limit: 25 }), null);
  assert.equal(lib.previousOffset({ target: "P", total: 90, filtered_total: 90, offset: 10, limit: 25 }), 0);
  assert.equal(lib.precedentDetailMatches(DETAIL), true);
  assert.equal(lib.precedentDetailMatches(DETAIL_NO_TARGET), true);
  assert.equal(lib.precedentDetailMatches({ ...DETAIL, schema: "kinase_precedents@1" }), false);
  assert.equal(lib.precedentDetailMatches({ ...DETAIL, page: undefined }), false);
  assert.equal(lib.precedentDetailMatches(null), false);
});

// ---- snapshot block ----

test("snapshot block: not installed or invalid shows the reason and the import command only (no numbers)", () => {
  for (const status of [STATUS_NONE, STATUS_BAD]) {
    const view = plain(lib.precedentSnapshotView(status));
    assert.deepEqual(Object.keys(view).sort(), ["command", "hint", "reasonCode", "reasonText", "state"]);
    assert.equal(view.state, "unavailable");
    assert.equal(view.reasonCode, status.reason);
    assert.equal(view.command, lib.PRECEDENT_IMPORT_COMMAND);
    for (const text of [view.reasonText, view.hint, view.command]) assert.doesNotMatch(text, /\d/);
  }
  assert.equal(lib.precedentSnapshotView(STATUS_NONE).reasonText, "키나아제 전례 참조 스냅샷이 설치되지 않음 (not_installed)");
  assert.equal(lib.precedentSnapshotView({ ...STATUS_OK, set_summary: null }).state, "unavailable");
  assert.equal(lib.precedentStatusMatches(STATUS_OK), true);
  assert.equal(lib.precedentStatusMatches({ installed: true }), false);
});

test("snapshot block: hashes and commits cut to 12, dates, dirty, versions, rows, KT1, UP5 with the set-wide sum", () => {
  const ok = plain(lib.precedentSnapshotView(STATUS_OK));
  assert.equal(ok.state, "ready");
  assert.deepEqual([ok.setHashShort, ok.kbaseCommitShort, ok.distCommitText, ok.distCommitDateText],
    [SET.slice(0, 12), "c0dec0dec0de", "d157d157d157", "2026-10-01T09:00:00+09:00"]);
  assert.equal(ok.dirtyText, "커밋되지 않은 변경 없음 (dirty false)");
  assert.equal(ok.kbVersion, "kbv1:synthetic-fixture");
  assert.deepEqual(ok.versions.map(item => item.key), ["schema_version", "effect_rules_version", "vocab_version"]);
  assert.deepEqual(ok.files, [{ name: "dist/moves.jsonl", rowsText: "7행" }, { name: "dist/moves_flagged.jsonl", rowsText: "6행" },
    { name: "dist/references.jsonl", rowsText: "6행" }]);
  assert.deepEqual(ok.bibliography, { snapshotId: "SNAP-pubmed-synthetic", date: "2026-10-01", license: "synthetic-license",
    rowsText: "5행" });
  assert.equal(ok.processedLabel, "kbase_kinase 가공본 · 미검수 · 기계 추출");
  assert.equal(ok.licenseNote, SPEC_KP.KT1);
  // UP5's N = unresolved moves + moves_flagged of the whole set (2 + 3)
  assert.equal(ok.summary.unresolvedNote, "표적이 해석되지 않은 전례 5건(세트 전체)이 있어 어느 체인에도 연결하지 못했다.");
  assert.deepEqual(ok.summary.unresolvedNames, [{ nameText: "SYN-NAME", text: "moves 1건 · moves_flagged 2건" },
    { nameText: "— (kbase 기록에 이름 없음)", text: "moves 1건 · moves_flagged 1건" }]);
  assert.equal(ok.summary.otherNamesText, null);
  assert.deepEqual(ok.summary.bases, [{ basis: "gene", text: "moves 4건 · moves_flagged 2건" },
    { basis: "name_token", text: "moves 1건 · moves_flagged 1건" }]);
  // more distinct names than listed: "그 밖 N개"
  const capped = plain(lib.setSummaryView({ ...SET_SUMMARY, unresolved_names_total: 135 }));
  assert.equal(capped.otherNamesText, "그 밖 133개(목록 상한 100개)");
  // no dist commit: "—" with the reason, and "날짜 없음"
  const nodist = plain(lib.precedentSnapshotView({ ...STATUS_OK, kbase: { ...KBASE, dist_commit: null, dist_commit_date: null,
    dirty: true } }));
  assert.deepEqual([nodist.distCommitText, nodist.distCommitDateText, nodist.dirtyText],
    ["— (dist를 추적하는 커밋 없음)", "날짜 없음", "커밋되지 않은 변경 있음 (dirty true)"]);
});

test("snapshot badges: \"이전 스냅샷 기준\" only against another active set, \"사용 중 스냅샷 없음\" without one", () => {
  assert.equal(lib.resultSnapshotBadge({ set_hash: SET2, same: false }), "stale");
  assert.equal(lib.resultSnapshotBadge({ set_hash: SET, same: true }), null);
  assert.equal(lib.resultSnapshotBadge({ set_hash: null, same: false }), "no_active_set");
  assert.equal(lib.listSnapshotBadge({ active: false }, true), "stale");
  assert.equal(lib.listSnapshotBadge({ active: true }, true), null);
  assert.equal(lib.listSnapshotBadge({ active: false }, false), "no_active_set");
  assert.equal(lib.listSnapshotBadge({ active: false }, null), null);
  const manifest = active => ({ precedent_set: { set_hash: SET }, snapshot: { active_set_hash: active } });
  assert.equal(lib.reportSnapshotBadge(manifest(SET)), null);
  assert.equal(lib.reportSnapshotBadge(manifest(SET2)), "stale");
  assert.equal(lib.reportSnapshotBadge(manifest(null)), "no_active_set");
  assert.equal(lib.snapshotBadgeText("stale"), "이전 스냅샷 기준");
  assert.equal(lib.snapshotBadgeText("no_active_set"), "사용 중 스냅샷 없음");
  assert.equal(lib.snapshotBadgeText(null), null);
});

// ---- results ----

test("list items: a file that was not included is \"—\" with the reason, never 0", () => {
  const item = over => ({ handle: RESULT, numbering_map_handle: MAP, pdb_id: "0SY5", include_flagged: false, chain_count: 5,
    linked_chain_count: 3, target_count: 2, records: { moves: 4, moves_flagged: null }, null_result: false, set_hash: SET,
    active: true, ...over });
  const excluded = lib.precedentListItemText(item());
  assert.equal(excluded, "PDB 0SY5 · 체인 5개(연결 3개) · 표적 2개 · moves 파일 4건 · moves_flagged 파일 — (포함하지 않음)");
  assert.doesNotMatch(excluded.split("moves_flagged 파일")[1], /\d/);
  assert.equal(lib.precedentListItemText(item({ include_flagged: true, records: { moves: 4, moves_flagged: 0 } })),
    "PDB 0SY5 · 체인 5개(연결 3개) · 표적 2개 · moves 파일 4건 · moves_flagged 파일 0건");
  assert.equal(lib.precedentListItemText(item({ pdb_id: null, chain_count: 1, linked_chain_count: 0, target_count: 0,
    records: { moves: 0, moves_flagged: null }, null_result: true })),
  "PDB ID — (번호 대응에 PDB ID가 없음) · 체인 1개(연결 0개) · 표적 0개 · moves 파일 0건 · moves_flagged 파일 — (포함하지 않음) · 빈 결과");
});

test("chain table: status, reason \"한국어 (code)\", accession, mapped / all residues, cross check; UP5 is set-wide", () => {
  const view = plain(lib.precedentResultView(DETAIL));
  assert.deepEqual(view.chains.map(item => [item.chainAuth, item.statusText, item.reasonText, item.accessionText]), [
    ["A", "연결 (linked)", "—", "P0SYN1"], ["B", "연결 (linked)", "—", "P0SYN1"],
    ["C", "연결 안 함 (not_linked)", "번호 대응에 mapped 잔기 행이 없음 (no_mapped_residues)",
      "— (번호 대응에 mapped 잔기 행이 없음 (no_mapped_residues))"],
    ["D", "연결 안 함 (not_linked)", "mapped 잔기의 accession이 둘 이상(융합 단백질 등) (multiple_accessions)",
      "— (mapped 잔기의 accession이 둘 이상(융합 단백질 등) (multiple_accessions))"],
    ["E", "연결 (linked)", "—", "Q0SYN2"], ["F", "연결 (linked)", "—", "R0SYN3"]]);
  // the same accession on two chains: one target, each chain row kept; every accession of a fused chain shown
  assert.deepEqual(view.chains.map(item => item.accessionsText),
    ["P0SYN1", "P0SYN1", "빈 목록 ([])", "P0SYN8, P0SYN9", "Q0SYN2", "R0SYN3"]);
  assert.equal(view.chains[0].residuesText, "mapped 280 / 전체 300");
  assert.equal(view.chains[2].residuesText, "mapped 0 / 전체 300");
  assert.equal(view.chains[0].crossCheckText, "두 방법 교차 확인함 (cross_check true)");
  assert.equal(view.chains[1].crossCheckText, "교차 확인 안 함 (cross_check false): PDB ID를 주지 않음 (pdb_id_not_given)");
  assert.equal(view.unresolvedNote, "표적이 해석되지 않은 전례 5건(세트 전체)이 있어 어느 체인에도 연결하지 못했다.");
  assert.deepEqual([view.badge, view.badgeText], ["stale", "이전 스냅샷 기준"]);
  assert.deepEqual(view.limitations, LIMITATIONS);
  assert.equal(view.processedLabel, "kbase_kinase 가공본 · 미검수 · 기계 추출");
  assert.equal(view.licenseNote, SPEC_KP.KT1);
  assert.equal(view.setHashShort, SET.slice(0, 12));
  assert.equal(view.kbVersion, "kbv1:synthetic-fixture");
  assert.equal(view.recordFormatText, "전례 사본 형식 kbase_record_minus_2_paths@1");
});

test("counts: included and not-included moves_flagged are separate; the side that does not apply is \"—\", never 0", () => {
  const rows = d => Object.fromEntries(plain(lib.precedentResultView(d)).countRows.map(item => [item.key, item.text]));
  assert.deepEqual(rows(DETAIL), { chains: "6개", linked_chains: "4개", not_linked_chains: "2개", targets: "3개",
    records_moves: "2건", records_moves_flagged: "1건",
    excluded_moves_flagged: "— (moves_flagged 파일을 포함해 미포함 수 없음)" });
  const excluded = rows(DETAIL_EXCLUDED);
  assert.equal(excluded.records_moves_flagged, "— (포함하지 않음)");
  assert.equal(excluded.excluded_moves_flagged, "3건");
  assert.doesNotMatch(excluded.records_moves_flagged, /\d/);
  assert.doesNotMatch(rows(DETAIL).excluded_moves_flagged, /\d/);
  // an excluded count of 0 is a counted 0 (it is an integer), the included side stays "—"
  const none = rows(DETAIL_NO_TARGET);
  assert.deepEqual([none.records_moves, none.records_moves_flagged, none.excluded_moves_flagged], ["0건", "— (포함하지 않음)", "0건"]);
  assert.equal(plain(lib.precedentResultView(DETAIL)).includeFlaggedText, "moves_flagged 파일 전례 포함함 (include_flagged true)");
  assert.equal(plain(lib.precedentResultView(DETAIL_EXCLUDED)).includeFlaggedText,
    "moves_flagged 파일 전례 포함하지 않음 (include_flagged false)");
});

test("targets: three status phrases (never 0 or a bare \"없음\"), UP2 under the status whenever excluded_flagged is an integer", () => {
  const included = plain(lib.precedentResultView(DETAIL)).targets;
  assert.deepEqual(included.map(item => [item.accession, item.chainsText, item.statusText, item.excludedNote]), [
    ["P0SYN1", "체인 A, B", "전례 3건", null],
    ["Q0SYN2", "체인 E", "포함한 파일에 이 표적의 전례 기록 없음", null],
    ["R0SYN3", "체인 F", "kbase에 이 표적 참조가 없음(전례 없음과 다름)", null]]);
  // "전례 N건" of the selected target is the server's page total (included records of both files when included)
  assert.equal(included[0].statusText, `전례 ${DETAIL.page.total}건`);
  const excluded = plain(lib.precedentResultView(DETAIL_EXCLUDED)).targets;
  assert.deepEqual(excluded.map(item => [item.statusText, item.excludedNote]), [
    ["전례 2건", "moves_flagged 파일의 전례 1건은 포함하지 않았다."],
    ["포함한 파일에 이 표적의 전례 기록 없음", "moves_flagged 파일의 전례 2건은 포함하지 않았다."],
    ["kbase에 이 표적 참조가 없음(전례 없음과 다름)", "moves_flagged 파일의 전례 0건은 포함하지 않았다."]]);
  assert.equal(excluded[0].statusText, `전례 ${DETAIL_EXCLUDED.page.total}건`);
  for (const target of [...included, ...excluded].filter(item => item.status !== "precedents_found")) {
    assert.doesNotMatch(target.statusText, /\d/);
    assert.notEqual(target.statusText.trim(), "없음");
  }
  // per-file counts: the file that was not included is "—" with the reason
  assert.deepEqual([included[0].movesText, included[0].movesFlaggedText], ["moves 파일 2건", "moves_flagged 파일 1건"]);
  assert.deepEqual([excluded[0].movesText, excluded[0].movesFlaggedText], ["moves 파일 2건", "moves_flagged 파일 — (포함하지 않음)"]);
  // every reference kept (two for one accession), kbase values as written; none -> "—" with the reason
  assert.deepEqual(included[0].references.map(item => [item.refId, item.gene, item.klifsName, item.group, item.family, item.coverage]),
    [["REF-1", "SYNG", "SYN", "SYNGROUP", "SYNFAM", "partial"], ["REF-2", "—", "SYN", "SYNGROUP", "SYNFAM", "partial"]]);
  assert.equal(included[0].referencesText, null);
  assert.equal(included[2].referencesText, "— (kbase에 이 표적 참조가 없음)");
  // counts by variant notation, tag and resolution basis (server counts, server order); empty -> "빈 목록 ([])"; UP3
  assert.deepEqual(included[0].variants.map(item => item.text), ["A10V 1건", "not_reported 2건"]);
  assert.deepEqual(included[0].tags.map(item => [item.axis, item.items.map(entry => entry.text)]), [
    ["site", ["back 1건", "bp_I_A 2건", "front 1건"]], ["goal", ["solubility 2건"]],
    ["tactic", ["ring_fusion 1건", "scaffold_hop 1건"]]]);
  assert.deepEqual(included[0].bases.map(item => item.text), ["gene 2건", "name_token 1건"]);
  assert.equal(included[0].variantNote, SPEC_UP.UP3);
  assert.deepEqual([included[1].variantsText, included[1].basesText, included[1].tags[0].text],
    ["빈 목록 ([])", "빈 목록 ([])", "빈 목록 ([])"]);
});

test("no target (page.target === null): no records, no facets, \"—\" with the reason; an empty result is not a failure", () => {
  const view = plain(lib.precedentResultView(DETAIL_NO_TARGET));
  assert.equal(view.selectedTarget, null);
  assert.equal(view.noTargetText, lib.NO_TARGET_TEXT);
  assert.deepEqual([view.records, view.targets], [[], []]);
  assert.equal(view.pageText, "— (연결된 표적 없음)");
  assert.deepEqual([view.nullResult, view.nullResultText], [true, lib.NULL_RESULT_TEXT]);
  assert.equal(view.pdbIdText, "— (번호 대응에 PDB ID가 없음)");
  assert.deepEqual([view.badge, view.badgeText], ["no_active_set", "사용 중 스냅샷 없음"]);
  assert.equal(lib.filterOptions(DETAIL_NO_TARGET.facets), null);
  // a result with targets has none of that
  const full = plain(lib.precedentResultView(DETAIL));
  assert.deepEqual([full.noTargetText, full.nullResultText, full.selectedTarget], [null, null, "P0SYN1"]);
  assert.equal(full.pageText, "전체 3건 · 필터 결과 3건 · 1–3번째");
  assert.deepEqual([plain(lib.precedentResultView(DETAIL_EXCLUDED)).badge], [null]);
});

test("precedent table rows: kbase values verbatim, file names as written, bibliography or \"서지 없음\", check badges", () => {
  const rows = plain(lib.precedentResultView(DETAIL)).records;
  // the server's page order (no re-sorting here)
  assert.deepEqual(rows.map(item => [item.moveId, item.fileText, item.variant, item.resolutionBasis, item.pmid]), [
    ["MOVE-0001", "moves 파일", "not_reported", "gene", "900001"],
    ["MOVE-0010", "moves 파일", "A10V", "name_token", "900002"],
    ["MOVE-0100", "moves_flagged 파일", "not_reported", "gene", "900003"]]);
  assert.deepEqual(rows[0].tags, [{ axis: "site", text: "bp_I_A, back" }, { axis: "goal", text: "solubility" },
    { axis: "tactic", text: "빈 목록 ([])" }]);
  assert.equal(rows[0].bibliographyText, "PMID 900001 · SYNTHETIC title one · SYN J · 2020");
  assert.equal(rows[1].bibliographyText, "PMID 900002 · — (서지 없음)");
  assert.equal(rows[2].bibliographyText, "PMID 900003 · — · — · —");
  assert.equal(rows[0].locationsText, "표(table) 3쪽, 본문(text) 5쪽");
  assert.equal(rows[1].locationsText, "그림(figure) 7쪽");
  assert.deepEqual(rows[0].checks, { failNames: ["schema", "duplicate"], lookupFailedNames: ["pmid_exists"],
    text: "kbase 기계 검사 fail 2 · lookup_failed 1" });
  assert.equal(rows[1].checks.text, "kbase 기계 검사 fail 0 · lookup_failed 0");
  // file names are never called pass / fail
  for (const row of rows) assert.doesNotMatch(row.fileText, /통과|실패|pass|fail/);
});

test("precedent detail: bibliography, every location, quotes with truncated / assembled marks, change, structure, interactions", () => {
  const detail = plain(lib.recordDetailView(R1, BIBLIOGRAPHY));
  assert.deepEqual(detail.bibliography, [{ key: "title", text: "SYNTHETIC title one" }, { key: "journal", text: "SYN J" },
    { key: "year", text: "2020" }, { key: "doi", text: "10.0/syn" }, { key: "pmc", text: "—" }]);
  assert.equal(detail.bibliographyText, null);
  const missing = plain(lib.recordDetailView(R2, BIBLIOGRAPHY));
  assert.deepEqual([missing.bibliography, missing.bibliographyText], [null, "— (서지 없음: 서지 스냅샷에 이 PMID의 행이 없음)"]);
  // every location with every field (unlisted keys kept, in order after the listed ones)
  assert.deepEqual(detail.locations, [
    [{ key: "kind", text: "table" }, { key: "page", text: "3" }, { key: "table_index", text: "1" }, { key: "row", text: "2" },
      { key: "figure_id", text: "—" }, { key: "panel", text: "—" }, { key: "bbox", text: "—" }],
    [{ key: "kind", text: "text" }, { key: "page", text: "5" }]]);
  assert.deepEqual(detail.target.map(item => item.key), ["gene", "uniprot", "name_as_written", "resolution_basis", "variant",
    "candidates"]);
  assert.deepEqual(detail.observation, { text: "SYNTHETIC observation text", quote: "SYNTHETIC quote four words",
    wordsText: "4단어", truncatedText: "인용 잘림 표시 (quote_truncated true)",
    assembledText: "조합된 인용 표시 (quote_assembled): 조각 2개 · 3쪽" });
  assert.deepEqual(detail.tradeoffs, [
    { text: "SYNTHETIC tradeoff text", quote: "SYNTHETIC tradeoff quote", wordsText: "3단어",
      truncatedText: "인용 잘림 표시 없음 (quote_truncated false)", assembledText: null },
    { text: "SYNTHETIC tradeoff without quote", quote: "— (kbase 기록에 인용 없음)", wordsText: "— (인용 없음)",
      truncatedText: "인용 잘림 표시 없음 (quote_truncated false)", assembledText: null }]);
  assert.equal(plain(lib.recordDetailView(R2, BIBLIOGRAPHY)).tradeoffsText, "빈 목록 ([])");
  assert.equal(plain(lib.recordDetailView(R2, BIBLIOGRAPHY)).observation.assembledText, null);
  assert.deepEqual(detail.change.map(item => [item.key, item.text]), [["description", "SYNTHETIC change"],
    ["from_compound", "SYN-a"], ["to_compound", "SYN-b"], ["smiles_from", "—"], ["smiles_to", "—"]]);
  assert.deepEqual(detail.structure.fields, [{ key: "structure_ref", text: "0SYN" },
    { key: "structure_link_reason", text: "SYNTHETIC link reason" }, { key: "structure_ref_from", text: "paper" }]);
  assert.deepEqual(detail.structure.links[0].slice(0, 4), [{ key: "pdb_id", text: "0SYN" }, { key: "chain", text: "A" },
    { key: "ligand", text: "SYN" }, { key: "basis", text: "paper_context" }]);
  assert.equal(detail.structure.note, SPEC_UP.UP4);
  assert.equal(plain(lib.recordDetailView(R2, BIBLIOGRAPHY)).structure.linksText, "빈 목록 ([])");
  assert.deepEqual(detail.interactions[0].slice(0, 3), [{ key: "interaction", text: "SYNTHETIC contact class" },
    { key: "aa", text: "LYS" }, { key: "uniprot_resnum", text: "33" }]);
  assert.equal(detail.interactions[0].at(-1).key, "evidence");
  assert.equal(plain(lib.recordDetailView(R2, BIBLIOGRAPHY)).interactionsText, "빈 목록 ([])");
});

test("measured changes: kbase rule v1 values verbatim with target_role; fold_change null is \"—\" with the reason", () => {
  const detail = plain(lib.recordDetailView(R1, BIBLIOGRAPHY));
  assert.equal(detail.effectsHeader, "측정 변화(kbase 추출 effects)");
  assert.equal(detail.effectsNote, SPEC_KP.KP2);
  const [first, second] = detail.effects;
  assert.deepEqual(first, { metric: "IC50", assay: "SYNTHETIC assay", beforeText: "= 100 nM", afterText: "< 10.5 nM",
    targetRef: "SYN-KINASE", targetRole: "on_target", direction: "unchanged", directionBasis: "numeric",
    basisText: "kbase 규칙 v1 산출 (numeric)", magnitudeBucket: "small", comparableText: "true",
    comparabilityReasonText: "—", foldChangeText: "9.5" });
  assert.deepEqual([second.targetRole, second.direction, second.basisText, second.magnitudeBucket, second.comparableText,
    second.comparabilityReasonText], ["off_target", "unknown", "kbase 규칙 v1 산출 (text)", "unknown", "false", "SYNTHETIC reason"]);
  assert.equal(second.foldChangeText, "— (kbase 기록에 값 없음, ProtView는 계산하지 않음)");
  assert.equal(second.beforeText, "— (kbase 기록에 값 없음)");
  assert.equal(second.afterText, "— (kbase 기록에 값 없음)");
  for (const text of [second.foldChangeText, second.beforeText]) assert.doesNotMatch(text, /\d/);
  // directions stay the English kbase words (never translated); the view carries no tone, colour or rank field
  for (const direction of ["improved", "worsened", "unchanged", "unknown"])
    assert.equal(lib.effectView(effect({ direction })).direction, direction);
  assert.deepEqual(Object.keys(first).sort(), ["afterText", "assay", "basisText", "beforeText", "comparabilityReasonText",
    "comparableText", "direction", "directionBasis", "foldChangeText", "magnitudeBucket", "metric", "targetRef", "targetRole"]);
  assert.doesNotMatch(LIB_CODE, /\b(?:tone|colou?r|className|cssClass|danger|warning|green|red)\b/i);
  assert.equal(lib.effectView(effect({ fold_change: 0 })).foldChangeText, "0");
});

test("two check channels stay apart: all ten kbase checks, ProtView integrity, \"원문 대조 안 함\", hash of the original record", () => {
  const detail = plain(lib.recordDetailView(R1, BIBLIOGRAPHY));
  assert.equal(detail.checksHeader, "kbase 기계 검사");
  assert.equal(detail.checksNote, SPEC_KP.KP3);
  assert.deepEqual(detail.checks.map(item => item.name), CHECKS);
  assert.deepEqual(detail.checks.filter(item => item.status !== "pass"), [{ name: "schema", status: "fail" },
    { name: "pmid_exists", status: "lookup_failed" }, { name: "duplicate", status: "fail" }]);
  assert.equal(detail.integrityHeader, "ProtView 무결성 확인");
  assert.deepEqual(detail.integrity.map(item => item.text), ["레코드 해시 일치 (hash_verified true)", "관찰 인용 4단어",
    "교환 인용 3단어, — (인용 없음)", "모든 인용 25단어 이하 (quotes_within_limit true)",
    "논문 쪽 위치 있음 (locations_have_page true)"]);
  // a quote above 25 words is not excluded: the value is shown as it is
  const long = plain(lib.recordDetailView(R2, BIBLIOGRAPHY)).integrity.map(item => item.text);
  assert.deepEqual([long[1], long[2], long[3]], ["관찰 인용 30단어", "교환 인용 빈 목록 ([])",
    "25단어를 넘는 인용 있음 (quotes_within_limit false)"]);
  assert.match(detail.sourceNote, /^원문 대조 안 함/);
  assert.equal(detail.sourceNote, SPEC_UP.UP1);
  assert.equal(detail.contentHash, `sha256:${"e".repeat(64)}`);
  assert.match(detail.contentHashNote, /^해시는 원본 레코드의 것/);
  assert.equal(detail.recordFormat, "kbase_record_minus_2_paths@1");
  assert.deepEqual(detail.extraction, [{ key: "model", text: "synthetic-model" }, { key: "provider", text: "synthetic" },
    { key: "prompt_version", text: "fixture-1" }, { key: "run_at", text: "2026-10-01T00:00:00Z" }]);
  assert.deepEqual(detail.otherFields.map(item => item.key), ["review_status", "schema_version", "mutations", "proposed_tags",
    "figures"]);
  // no single string joins the two channels into one claim
  for (const text of screenStrings()) assert.ok(!(text.includes("kbase 기계 검사") && text.includes("무결성 확인")) ||
    lib.PRECEDENT_FIXED_LINES.includes(text), text);
});

test("five area states: no run and no capability record are unavailable; a missing snapshot is not; empty result is not a failure", () => {
  const base = { runId: "r1", capability: { available: true, reason: null } };
  const state = over => plain(lib.precedentPanelState({ ...base, ...over }));
  assert.deepEqual(state({ runId: null }), { state: "unavailable", reason: lib.NO_RUN_REASON });
  assert.deepEqual(state({ capability: null }), { state: "unavailable", reason: lib.CAPABILITY_REASON });
  assert.deepEqual(state({ capability: undefined }), { state: "loading" });
  assert.deepEqual(state({ loading: true }), { state: "loading" });
  assert.deepEqual(state({ error: "실패함" }), { state: "failed", message: "실패함" });
  assert.deepEqual(state({}), { state: "ready" });
  assert.deepEqual(state({ capability: { available: false, reason: "not installed" } }), { state: "ready" });
  assert.deepEqual(state({ detail: { null_result: true } }), { state: "empty", message: lib.NULL_RESULT_TEXT });
  assert.deepEqual(state({ detail: { null_result: false } }), { state: "ready" });
  for (const text of [lib.NO_RUN_REASON, lib.CAPABILITY_REASON, lib.NULL_RESULT_TEXT]) assert.doesNotMatch(text, /\d/);
});

test("one area's state is one of the five: unavailable, then failed, then loading, then empty, else ready", () => {
  const state = input => lib.precedentAreaState(input);
  assert.equal(state({}), "ready");
  assert.equal(state({ empty: true }), "empty");
  assert.equal(state({ loading: true, empty: true }), "loading");
  assert.equal(state({ failed: true, loading: true, empty: true }), "failed");
  assert.equal(state({ unavailable: true, failed: true, loading: true, empty: true }), "unavailable");
  assert.equal(state({ unavailable: false, failed: false, loading: false, empty: false }), "ready");
  // every state it can give has its label among the five (spec 8)
  const given = new Set([{}, { empty: true }, { loading: true }, { failed: true }, { unavailable: true }].map(state));
  assert.deepEqual([...given].sort(), Object.keys(lib.AREA_STATE_LABEL).sort());
});

test("late responses: applied only for the same run, result handle and request number; reports for the same run", () => {
  const live = { runId: "r1", handle: RESULT, seq: 4 };
  assert.equal(lib.precedentResponseCurrent({ ...live }, live), true);
  assert.equal(lib.precedentResponseCurrent({ ...live, runId: "r2" }, live), false);
  assert.equal(lib.precedentResponseCurrent({ ...live, handle: "other" }, live), false);
  assert.equal(lib.precedentResponseCurrent({ ...live, seq: 3 }, live), false);
  assert.equal(lib.precedentResponseCurrent({ ...live, runId: null }, { ...live, runId: null }), false);
  assert.equal(lib.precedentReportSavedForRun(live, "r1"), true);
  assert.equal(lib.precedentReportSavedForRun(live, "r2"), false);
  assert.ok(lib.PRECEDENT_AREAS.includes("detail") && lib.PRECEDENT_AREAS.includes("command"));
  const artifact = { manifest: { schema: "method_report_manifest@1", analysis_type: "kinase_precedents", result_handle: RESULT } };
  assert.equal(lib.precedentReportMatches(artifact, RESULT), true);
  assert.equal(lib.precedentReportMatches(artifact, "other"), false);
  assert.equal(lib.precedentReportMatches({ manifest: { ...artifact.manifest, analysis_type: "reaction_knowledge" } }, RESULT), false);
  assert.equal(reportLibrary.reportKindLabel({ kind: lib.PRECEDENT_REPORT_TYPE, handle: "h", target_handle: RESULT, created_seq: 1 }),
    lib.PRECEDENT_REPORT_LABEL);
});

// ---- wording: no ranking, recommendation, verification, aggregation or effect claim in this module's own strings ----

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
  assert.ok(start >= 0, marker);
  const block = source.slice(start, source.indexOf(", re.IGNORECASE)", start));
  return [...block.matchAll(/r"([^"]*)"/g)].map(item => item[1]).join("");
}

test("the screen check is at least the M27 report check (M15 + M20 + M26 + M27 words) plus 최고·우수·악화", () => {
  const reportWords = [backend("numbering_reports.py"), backend("mutation_reports.py"), backend("reaction_knowledge_reports.py"),
    REPORTS].map(source => pyRegex(source, "INTERPRETIVE = re.compile(")).flatMap(alternatives);
  const mine = new Set(alternatives(lib.PRECEDENT_FORBIDDEN.source));
  for (const word of reportWords) assert.ok(mine.has(word), word);
  assert.equal(lib.PRECEDENT_FORBIDDEN.flags, "gi");
  for (const word of ["순위", "추천", "최고", "우수", "유망", "유망도", "성공률", "검증됨", "신뢰", "효과", "개선", "악화", "승자",
    "rank", "best", "recommend", "promising", "verified", "validated", "trusted", "reliable", "effect", "effects",
    "improved", "success rate", "winner", "highest", "score", "affinity", "점수", "ΔΔG"])
    assert.ok(lib.precedentForbiddenWords(`이 전례는 ${word}`).length, word);
  assert.deepEqual(plain(lib.precedentForbiddenWords("전례 · 측정 변화 · kbase 기계 검사 · ProtView 무결성 확인")), []);
});

test("fixed sentences are exempt only verbatim on their own line; the measured-change heading is the one exempt term", () => {
  // KP6 says 순위·추천·유망도·성공률 (in the negative): exempt as an exact line only
  assert.ok(lib.precedentForbiddenWords(`${SPEC_KP.KP6} `).length);
  assert.ok(lib.precedentForbiddenWords(`메모 ${SPEC_KP.KP6}`).length);
  for (const line of lib.PRECEDENT_FIXED_LINES) assert.deepEqual(plain(lib.precedentForbiddenWords(line)), [], line);
  assert.deepEqual(plain(lib.PRECEDENT_FIXED_LINES), [...Object.values(SPEC_KP), ...Object.values(SPEC_UP)]);
  assert.deepEqual(plain(lib.PRECEDENT_EXEMPT_TERMS), ["측정 변화(kbase 추출 effects)"]);
  assert.deepEqual(plain(lib.precedentForbiddenWords("측정 변화(kbase 추출 effects) 표")), []);
  assert.deepEqual(plain(lib.precedentForbiddenWords("kbase 추출 effects 요약")), ["effects"]);
  // spec 2: none of the fixed sentences says 효과 / effect / 검증됨, so the exemption is not what keeps them clean
  for (const line of lib.PRECEDENT_FIXED_LINES) assert.doesNotMatch(line, /효과|effect|검증됨/i, line);
});

function screenStrings() {
  const texts = [];
  const collect = value => {
    if (typeof value === "string") texts.push(value);
    else if (Array.isArray(value)) value.forEach(collect);
    else if (value && typeof value === "object") Object.values(value).forEach(collect);
  };
  for (const value of Object.values(lib)) if (typeof value !== "function" && !(value instanceof RegExp)) collect(value);
  const tooLarge = { reason_code: "result_too_large", limit: 10, actual: 20, size_without_flagged: 5,
    target_sizes: [{ accession: "P00001", chains: ["A"], bytes: 30 }] };
  collect([
    [...lib.ADMISSION_REASON_CODES, ...lib.SNAPSHOT_REASON_CODES, ...lib.CHAIN_REASONS, "result_invalid", "result_too_large",
      "cancelled", "not_found", "run_corrupt"].map(lib.precedentReasonText),
    [DETAIL, DETAIL_EXCLUDED, DETAIL_NO_TARGET].map(lib.precedentResultView),
    [R1, R2, R3].map(entry => lib.recordDetailView(entry, BIBLIOGRAPHY)),
    [STATUS_OK, STATUS_NONE, STATUS_BAD].map(lib.precedentSnapshotView),
    lib.setSummaryView({ ...SET_SUMMARY, unresolved_names_total: 130 }),
    ["stale", "no_active_set"].map(lib.snapshotBadgeText),
    lib.precedentListItemText({ handle: RESULT, numbering_map_handle: MAP, pdb_id: null, include_flagged: false, chain_count: 1,
      linked_chain_count: 0, target_count: 0, records: { moves: 0, moves_flagged: null }, null_result: true, set_hash: SET,
      active: false }),
    lib.requestUnavailableReason({ snapshot: STATUS_NONE, maps: [] }),
    lib.requestUnavailableReason({ snapshot: STATUS_OK, maps: [] }),
    lib.checkPrecedentForm({ numberingMap: null, chains: [], includeFlagged: 1 }, { ...OPTIONS, snapshot: STATUS_NONE }),
    lib.checkPrecedentForm(form({ chains: [{ chain_auth: "Z", selected: true }, { chain_auth: "Z", selected: true }] }), OPTIONS),
    lib.checkPrecedentForm(form({ numberingMap: MAP_EMPTY }), OPTIONS),
    lib.chainPreviews(MAPS[1], null), lib.chainPreviews(MAPS[1], MAP_ROWS),
    ...[...lib.ADMISSION_REASON_CODES, "not_installed", "result_invalid"].map(reason =>
      lib.precedentRefusal({ message: "", code: "input_invalid", detail: { reason_code: reason } })),
    lib.precedentRefusal({ message: "", code: "resource_exceeded", detail: tooLarge }),
    lib.checkPrecedentQuery({ ...lib.defaultPrecedentQuery(), sort: "x", order: "y", limit: 0, offset: -1,
      filters: { ...lib.emptyFilters(), file: "z", q: "q".repeat(101) } }),
    lib.filterOptions(FACETS), lib.recordPageText(DETAIL.page, 3), lib.recordPageText(DETAIL_NO_TARGET.page, 0),
    lib.precedentPanelState({ runId: null }), lib.precedentPanelState({ runId: "r", capability: null }),
    lib.precedentPanelState({ runId: "r", capability: { available: true, reason: null }, detail: { null_result: true } }),
    lib.screenNote("UP2", 7), lib.screenNote("UP5", 9),
  ]);
  return texts;
}

test("every user-visible string of this module passes the wording check (fixed lines excepted); nothing reads as a ranking", () => {
  const texts = screenStrings();
  assert.ok(texts.length > 300, `collected ${texts.length}`);
  for (const text of texts) assert.deepEqual(plain(lib.precedentForbiddenWords(text)), [], text);
  for (const text of texts) assert.doesNotMatch(text, /\d+\s*위(?!치)|\d+\s*등(?!록)|\btop\b|상위|하위|가장|막대/i, text);
  // file names are never called pass / fail outside the fixed sentence KP3, which says the opposite
  for (const text of texts.filter(item => !lib.PRECEDENT_FIXED_LINES.includes(item)))
    assert.doesNotMatch(text, /moves(?:_flagged)?[^.]{0,12}(?:통과|실패)|(?:통과|실패)[^.]{0,12}moves/, text);
});

test("the module never sorts or aggregates precedent values: no sort calls, arithmetic only in the spec-defined counts", () => {
  for (const pattern of [/\.sort\(/, /\.reverse\(/, /\.toSorted\(/, /\?\?\s*0\b/, /\|\|\s*0\b/, /reduce\([^)]*\+/,
    /innerHTML|dangerouslySetInnerHTML/, /\b(rank|best|score|delta|difference|improv|average|mean)\w*\s*[:=]/i])
    assert.ok(!pattern.test(LIB_CODE), String(pattern));
  // arithmetic on stored counts lives only in the named helpers (UP5's N, "전례 N건", "그 밖 N개", page positions)
  const allowed = ["unresolvedRecordTotal", "includedRecordCount", "unlistedNameCount", "recordPageText", "nextOffset",
    "previousOffset"];
  let rest = LIB_CODE;
  for (const name of allowed) {
    const start = rest.indexOf(`export function ${name}(`);
    assert.ok(start >= 0, name);
    rest = rest.slice(0, start) + rest.slice(rest.indexOf("\n}\n", start) + 3);
  }
  assert.doesNotMatch(rest, /\.(moves|moves_flagged|count|total|filtered_total|unresolved_names_total|length|bytes|fold_change|actual|offset|limit)\s*[-+*/](?![-+=])/);
  assert.doesNotMatch(rest, /Math\./);
  // the three spec counts on the fixture
  assert.equal(lib.unresolvedRecordTotal(SET_SUMMARY), 5);
  assert.equal(lib.includedRecordCount({ moves: 76, moves_flagged: null }), 76);
  assert.equal(lib.includedRecordCount({ moves: 76, moves_flagged: 66 }), 142);
  assert.equal(lib.unlistedNameCount(SET_SUMMARY), null);
  assert.equal(lib.unlistedNameCount({ ...SET_SUMMARY, unresolved_names_total: 102 }), 100);
});

test("kbase values pass through as plain text (strings as written, null \"—\", other JSON values as JSON text)", () => {
  assert.equal(lib.verbatimText("<b>SYNTHETIC</b>"), "<b>SYNTHETIC</b>");
  assert.equal(lib.verbatimText(""), "");
  assert.equal(lib.verbatimText(null), "—");
  assert.equal(lib.verbatimText(undefined), "—");
  assert.equal(lib.verbatimText(0), "0");
  assert.equal(lib.verbatimText(false), "false");
  assert.equal(lib.verbatimText(["a", 1]), "[\"a\",1]");
  assert.equal(lib.verbatimText({ k: null }), "{\"k\":null}");
  assert.equal(lib.notShownText("포함하지 않음"), "— (포함하지 않음)");
});
