const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const source = fs.readFileSync(path.join(__dirname, "../src/lib/numbering.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const moduleObject = { exports: {} };
vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, require });
const lib = moduleObject.exports;
const plain = value => JSON.parse(JSON.stringify(value));

test("numbering structures keep structure and prepared_structure handles in creation order, once", () => {
  const events = [
    { seq: 1, type: "object_created", handle: "s1", kind: "structure_source" },
    { seq: 2, type: "object_created", handle: "s2", kind: "structure" },
    { seq: 3, type: "object_created", handle: "p1", kind: "prepared_structure" },
    { seq: 4, type: "object_created", handle: "c1", kind: "chemical_structure" },
    { seq: 5, type: "object_created", handle: "s2", kind: "structure" },
    { seq: 6, type: "call_completed" },
  ];
  assert.deepEqual(plain(lib.numberingStructures(events)), [
    { handle: "s2", kind: "structure" }, { handle: "p1", kind: "prepared_structure" }]);
});

test("polymer chains exclude water and ligand-only chains", () => {
  const residues = [{ chain_auth: "A", category: "polymer" }, { chain_auth: "A", category: "water" },
    { chain_auth: "W", category: "water" }, { chain_auth: "B", category: "nonpolymer" }, { chain_auth: "AB", category: "polymer" }];
  assert.deepEqual(plain(lib.polymerChains(residues)), ["A", "AB"]);
});

const form = over => ({ ...lib.emptyForm(), structure: "s", chains: [{ chain_auth: "A", selected: true, accession: null }], ...over });
const sifts = [{ chain_auth: "A", accessions: ["O14965"], reason_code: null, reason: null },
  { chain_auth: "B", accessions: ["P1", "P2"], reason_code: null, reason: null },
  { chain_auth: "C", accessions: [], reason_code: "sifts_chain_no_segments", reason: "x" }];

test("PDB id is sent only after confirmation and chains need a usable method", () => {
  // Suggested but unconfirmed id is not sent and gives no SIFTS method.
  let check = lib.checkForm(form({ pdbId: "1mq4", pdbIdConfirmed: false, sifts }));
  assert.equal(check.ok, false);
  assert.match(check.errors[0], /체인 A/);
  // Confirmed id with SIFTS for the chain: ok without accession; id uppercased.
  check = lib.checkForm(form({ pdbId: "1mq4", pdbIdConfirmed: true, sifts }));
  assert.deepEqual(plain(check), { ok: true, body: { structure: "s", pdb_id: "1MQ4",
    chains: [{ chain_auth: "A", uniprot_accession: null }] } });
  // Unconfirmed + chosen accession: alignment only, pdb_id null.
  check = lib.checkForm(form({ pdbId: "1MQ4", chains: [{ chain_auth: "A", selected: true, accession: "O14965" }] }));
  assert.deepEqual(plain(check.body), { structure: "s", pdb_id: null, chains: [{ chain_auth: "A", uniprot_accession: "O14965" }] });
  // Unusable SIFTS chain needs an accession.
  check = lib.checkForm(form({ pdbId: "1MQ4", pdbIdConfirmed: true, sifts, chains: [{ chain_auth: "C", selected: true, accession: null }] }));
  assert.equal(check.ok, false);
  // Bad id format, no structure, no chain.
  assert.equal(lib.checkForm(form({ pdbId: "MQ4", pdbIdConfirmed: true, sifts })).ok, false);
  assert.equal(lib.checkForm(form({ structure: null })).ok, false);
  assert.equal(lib.checkForm(form({ chains: [{ chain_auth: "A", selected: false, accession: "O14965" }] })).ok, false);
});

test("SIFTS prefill fills only a single usable accession and never overwrites a user choice", () => {
  assert.equal(lib.siftsPrefill(sifts, "A"), "O14965");
  assert.equal(lib.siftsPrefill(sifts, "B"), null);
  assert.equal(lib.siftsPrefill(sifts, "C"), null);
  assert.equal(lib.siftsPrefill(null, "A"), null);
  const applied = lib.applySiftsHints(form({ chains: [
    { chain_auth: "A", selected: true, accession: null }, { chain_auth: "B", selected: true, accession: "Q9" }] }), sifts);
  assert.deepEqual(plain(applied.chains), [{ chain_auth: "A", selected: true, accession: "O14965" },
    { chain_auth: "B", selected: true, accession: "Q9" }]);
});

test("row filter pages matched rows and always reports the full total", () => {
  const rows = ["mapped", "conflict", "mapped", "unmapped", "mapped"].map((status, i) => ({ status, i }));
  assert.deepEqual(plain(lib.filterRows(rows, "all", 0, 2)), { total: 5, matched: 5, rows: rows.slice(0, 2) });
  const mapped = lib.filterRows(rows, "mapped", 1, 10);
  assert.equal(mapped.total, 5); assert.equal(mapped.matched, 3);
  assert.deepEqual(plain(mapped.rows).map(r => r.i), [2, 4]);
  assert.equal(lib.filterRows(rows, "conflict", 0, 10).matched, 1);
});

test("method answers show positions or every absent reason", () => {
  assert.equal(lib.answerText(null), "실행 안 함");
  assert.equal(lib.answerText({ accession: "O14965", position: 388 }), "O14965 388");
  assert.equal(lib.answerText({ absent_reason: "alignment_below_identity",
    absent_reasons: ["alignment_below_identity", "alignment_below_coverage"] }), "alignment_below_identity, alignment_below_coverage");
  assert.equal(lib.answerText({ absent_reason: "alignment_gap" }), "alignment_gap");
});

test("residue text keeps null labels explicit and insertion codes", () => {
  assert.equal(lib.residueText({ model_number: 1, chain_auth: "A", seq_auth: 240, icode: "A", chain_label: null, seq_label: null, resname: "GLY" }),
    "모델 1 A GLY 240A (label 없음)");
  assert.equal(lib.residueText({ model_number: 2, chain_auth: "A", seq_auth: 126, icode: "", chain_label: "A", seq_label: 7, resname: "ARG" }),
    "모델 2 A ARG 126 (label A/7)");
});

test("keyed reads drop responses of an older run or an older request", () => {
  let k = lib.keyedIdle("r1");
  k = lib.keyedRequest(k, "r1", 1);
  assert.equal(k.state.status, "loading");
  const late = lib.keyedResolve(k, "r1", 0, { status: "ready", value: 1 });
  assert.equal(late.state.status, "loading");
  k = lib.keyedRequest(k, "r2", 2);
  assert.equal(lib.keyedResolve(k, "r1", 1, { status: "ready", value: 1 }).state.status, "loading");
  k = lib.keyedResolve(k, "r2", 2, { status: "ready", value: 2 });
  assert.deepEqual(plain(k.state), { status: "ready", value: 2 });
  assert.equal(lib.keyedRequest(k, "r2", 2), k);
  assert.equal(lib.keyedRequest(k, null, 3), k);
});
