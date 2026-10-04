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
const siteAnnotation = load("site-annotation", { "./comparison": load("comparison"), "./numbering": load("numbering"),
  "./event-model": load("event-model") });
const docking = load("docking", { "./site-annotation": siteAnnotation });
const lib = load("mutation-model", { "./site-annotation": siteAnnotation, "./docking": docking });
const reportLibrary = load("report-library");
const plain = value => JSON.parse(JSON.stringify(value));
const LIB_SOURCE = fs.readFileSync(path.join(__dirname, "../src/lib/mutation-model.ts"), "utf8");

// ---- closed sets, limits and fixed sentences are read from the backend modules themselves ----
const constantsSource = fs.readFileSync(path.join(__dirname, "../../backend/mw/mutation_model_constants.py"), "utf8");
const readsSource = fs.readFileSync(path.join(__dirname, "../../backend/mw/mutation_model_reads.py"), "utf8");
function pyTuple(source, name) {
  const match = new RegExp(`^${name} = \\(([^)]*)\\)`, "m").exec(source);
  assert.ok(match, `backend constant ${name} not found`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map(item => item[1]);
}
function pyValue(source, name) {
  const match = new RegExp(`^${name} = ([^#\\n]+)`, "m").exec(source);
  assert.ok(match, `backend constant ${name} not found`);
  return match[1].trim();
}
function pyString(source, name) {
  const match = new RegExp(`^${name} = "([^"]+)"`, "m").exec(source);
  assert.ok(match, `backend constant ${name} not found`);
  return match[1];
}
/** L1..L7 (single or parenthesised implicit concatenation) in LIMITATION_ORDER. */
function backendLimitations() {
  const sentence = name => {
    const start = constantsSource.search(new RegExp(`^${name} = `, "m"));
    assert.ok(start >= 0, name);
    const rest = constantsSource.slice(start + `${name} = `.length);
    const body = rest.startsWith("(") ? rest.slice(1, rest.indexOf(")\n")) : rest.slice(0, rest.indexOf("\n"));
    return [...body.matchAll(/"([^"]*)"/g)].map(item => item[1]).join("");
  };
  const order = /^LIMITATION_ORDER = \(([^)]*)\)/m.exec(constantsSource)[1].split(",").map(text => text.trim());
  return order.map(sentence);
}

test("closed sets, limits, defaults and the fixed sentences equal the backend constants", () => {
  assert.equal(lib.MODEL_PROTOCOL, pyString(constantsSource, "PROTOCOL"));
  assert.equal(lib.MODEL_TOOL, pyString(constantsSource, "TOOL"));
  assert.equal(lib.MODEL_REPORT_TYPE, pyString(constantsSource, "KIND"));
  assert.equal(lib.SELECTION_POLICY, pyString(constantsSource, "SELECTION_POLICY"));
  assert.equal(lib.HYDROGEN_POLICY, pyString(constantsSource, "HYDROGEN_POLICY"));
  assert.equal(lib.CONTACT_CUTOFF_DEFAULT_A, Number(pyValue(constantsSource, "CONTACT_CUTOFF_DEFAULT_A")));
  assert.equal(pyValue(constantsSource, "CONTACT_CUTOFF_RANGE_A"), `(${lib.CONTACT_CUTOFF_RANGE_A[0]}, ${lib.CONTACT_CUTOFF_RANGE_A[1].toFixed(1)})`);
  assert.equal(pyValue(constantsSource, "SEED_RANGE"), `(${lib.SEED_RANGE[0]}, ${lib.SEED_RANGE[1]})`);
  assert.equal(lib.TIMEOUT_DEFAULT_S, Number(pyValue(constantsSource, "TIMEOUT_DEFAULT_S")));
  assert.equal(lib.TIMEOUT_MAX_S, Number(pyValue(constantsSource, "TIMEOUT_MAX_S")));
  assert.equal(lib.MAX_CONTACT_ROWS, Number(pyValue(constantsSource, "MAX_CONTACT_ROWS")));
  assert.equal(lib.EXCLUDED_BOND_DISTANCE, Number(pyValue(constantsSource, "EXCLUDED_BOND_DISTANCE")));
  assert.equal(lib.TOO_MANY_CONTACTS, pyString(constantsSource, "TOO_MANY_CONTACTS"));
  for (const name of ["ADMISSION_REASON_CODES", "UNAVAILABLE_REASON_CODES", "FAILURE_REASON_CODES"])
    assert.deepEqual(plain(lib[name]), pyTuple(constantsSource, name), name);
  assert.deepEqual(plain(lib.STRUCTURE_SIDES), pyTuple(constantsSource, "STRUCTURE_SIDES"));
  assert.deepEqual(plain(lib.MODEL_LIMITATIONS), backendLimitations());
  assert.equal(lib.MODEL_LIMITATIONS.length, 7);
  assert.equal(pyValue(readsSource, "LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX"), `${lib.LIST_LIMIT_DEFAULT}, ${lib.LIST_LIMIT_MAX}`);
  assert.equal(pyValue(readsSource, "CONTACT_PAGE_SIZE_DEFAULT, CONTACT_PAGE_SIZE_MAX"),
    `${lib.CONTACT_PAGE_SIZE_DEFAULT}, ${lib.CONTACT_PAGE_SIZE_MAX}`);
  const pairBlock = readsSource.slice(readsSource.indexOf("PAIR_REASONS = {"), readsSource.indexOf("\n}\n",
    readsSource.indexOf("PAIR_REASONS = {")));
  assert.deepEqual(plain(lib.PAIR_REASON_CODES), [...pairBlock.matchAll(/^\s+"([a-z_]+)":/gm)].map(item => item[1]));
  assert.equal(lib.PAIR_DOCKING_UNITS, 2);
});

test("every closed code reads as 'Korean (code)'; unknown codes stay raw", () => {
  const codes = [...lib.ADMISSION_REASON_CODES, ...lib.UNAVAILABLE_REASON_CODES, ...lib.FAILURE_REASON_CODES,
    "dry_run", "method_evidence_invalid", "global_concurrency_busy"];
  for (const code of codes) {
    const text = lib.modelReasonText(code);
    assert.ok(text.endsWith(` (${code})`) && /[가-힣]/.test(text), text);
  }
  assert.equal(lib.modelReasonText("something_new"), "something_new");
  assert.equal(lib.modelReasonText("toString"), "toString");
});

// ---- model request ----

const SET = "obj://r/mutation_candidate_set/s";
function form(overrides = {}) {
  return { ...lib.modelFormForCandidate(lib.initialModelForm(), SET, 0), seed: "11", selectionConfirmed: true,
    hydrogenConfirmed: true, ...overrides };
}
const errorsOf = check => { assert.equal(check.ok, false); return check.errors.join("\n"); };

test("initial form: no candidate, empty seed, confirmations unchecked, defaults shown; nothing is sendable", () => {
  const initial = lib.initialModelForm();
  assert.deepEqual(plain(initial), { candidateSet: null, candidateIndex: null, seed: "", selectionConfirmed: false,
    hydrogenConfirmed: false, cutoff: "4.0", timeout: "120" });
  const errors = errorsOf(lib.modelRequest(initial));
  assert.match(errors, /후보 행에서 시작/);
  assert.match(errors, /seed/);
  assert.match(errors, /confirmation_missing/);
});

test("a complete form builds exactly the server's six arguments and the top-level timeout", () => {
  const check = lib.modelRequest(form({ candidateIndex: 0, cutoff: " 4.5 ", timeout: "240" }));
  assert.equal(check.ok, true);
  assert.deepEqual(plain(check.args), { args: { candidate_set: SET, candidate_index: 0, seed: 11,
    selection_policy: "protein_only", hydrogen_policy: "rebuild_pH7", contact_cutoff_A: 4.5 }, timeout_s: 240 });
  assert.deepEqual(Object.keys(check.args.args), ["candidate_set", "candidate_index", "seed", "selection_policy",
    "hydrogen_policy", "contact_cutoff_A"]);
});

test("seed is required; both confirmations are required; cutoff 2.5–6.0 inclusive; timeout 1–240", () => {
  for (const seed of ["", " ", "-1", "1.5", "1e3", "2147483648", "0x10", "abc"])
    assert.match(errorsOf(lib.modelRequest(form({ seed }))), /seed/, seed);
  assert.equal(lib.modelRequest(form({ seed: "0" })).ok, true);
  assert.equal(lib.modelRequest(form({ seed: "2147483647" })).ok, true);
  assert.match(errorsOf(lib.modelRequest(form({ selectionConfirmed: false }))), /confirmation_missing/);
  assert.match(errorsOf(lib.modelRequest(form({ hydrogenConfirmed: false }))), /confirmation_missing/);
  for (const cutoff of ["2.5", "6.0", "6", "4"]) assert.equal(lib.modelRequest(form({ cutoff })).ok, true, cutoff);
  for (const cutoff of ["2.49", "6.01", "", "-3", "1e0", "NaN", "Infinity", "4.", ".5", "0x4"])
    assert.match(errorsOf(lib.modelRequest(form({ cutoff }))), /argument_invalid/, cutoff);
  for (const timeout of ["0", "241", "1.5", "", "-1"])
    assert.match(errorsOf(lib.modelRequest(form({ timeout }))), /시간 상한/, timeout);
  assert.equal(lib.modelRequest(form({ timeout: "1" })).ok, true);
});

test("the candidate is an integer index chosen from a row, never found by letters or chosen automatically", () => {
  for (const candidateIndex of [null, -1, 1.5, Number.NaN])
    assert.match(errorsOf(lib.modelRequest(form({ candidateIndex }))), /후보 행에서 시작/);
  assert.match(errorsOf(lib.modelRequest(form({ candidateSet: null }))), /후보 행에서 시작/);
  assert.equal(lib.modelRequest(form({ candidateIndex: 37 })).args.args.candidate_index, 37);
  // A different candidate unchecks both confirmations; the same candidate keeps them; seed/cutoff/time stay.
  const confirmed = form({ cutoff: "5.0" });
  const other = lib.modelFormForCandidate(confirmed, SET, 1);
  assert.equal(other.selectionConfirmed, false);
  assert.equal(other.hydrogenConfirmed, false);
  assert.equal(other.seed, "11");
  assert.equal(other.cutoff, "5.0");
  const again = lib.modelFormForCandidate(confirmed, SET, 0);
  assert.equal(again.selectionConfirmed, true);
  assert.equal(lib.modelFormForCandidate(confirmed, "obj://r/mutation_candidate_set/t", 0).hydrogenConfirmed, false);
});

test("submit is blocked without capability, while busy, while a job runs, or with errors", () => {
  const capability = { available: true, reason: null, reason_code: null };
  const check = lib.modelRequest(form());
  assert.equal(lib.modelSubmitBlockedReason({ capability, busy: false, activeJob: null, check }), null);
  assert.equal(lib.modelSubmitBlockedReason({ capability: { available: false, reason: "PDBFixer 없음",
    reason_code: "pdbfixer_unavailable" }, busy: false, activeJob: null, check }), "PDBFixer 없음 (pdbfixer_unavailable)");
  assert.equal(lib.modelSubmitBlockedReason({ capability: undefined, busy: false, activeJob: null, check }),
    lib.CAPABILITY_REASON);
  assert.match(lib.modelSubmitBlockedReason({ capability, busy: true, activeJob: null, check }), /처리하는 중/);
  assert.match(lib.modelSubmitBlockedReason({ capability, busy: false, activeJob: { status: "running" }, check }),
    /한 번에 한 작업/);
  assert.equal(lib.modelSubmitBlockedReason({ capability, busy: false, activeJob: { status: "done" }, check }), null);
  assert.match(lib.modelSubmitBlockedReason({ capability, busy: false, activeJob: null,
    check: lib.modelRequest(form({ seed: "" })) }), /seed/);
});

// ---- errors, jobs and approval ----

test("request and failure text keep the closed code and the server message; M7 reason shown as given", () => {
  assert.equal(lib.modelRequestErrorText({ message: "M7 refused", code: "input_invalid",
    detail: { reason_code: "openmm_preflight_failed", m7_reason: "oxt_missing", m7_message: "terminal OXT missing" } }),
  "OpenMM(M7) 사전 검사 실패 (openmm_preflight_failed) · M7: oxt_missing · terminal OXT missing");
  assert.match(lib.modelRequestErrorText({ message: "x", detail: { reason_code: "openmm_preflight_failed", m7_reason: null,
    m7_message: "too many atoms" } }), /M7 이유 코드 없음 · too many atoms$/);
  assert.equal(lib.modelRequestErrorText({ message: "no fixer", code: "precondition",
    detail: { reason_code: "pdbfixer_unavailable" } }), "고정 PDBFixer를 사용할 수 없음 (pdbfixer_unavailable) · no fixer");
  assert.equal(lib.modelRequestErrorText({ message: "bad", code: "input_invalid" }), "요청 오류 (input_invalid) · bad");
  assert.equal(lib.modelRequestErrorText({ message: "boom" }), "요청 실패 · boom");
  const tooMany = lib.modelFailureText({ error: "resource_exceeded", reason_code: "resource_exceeded", message: "rows",
    detail: { reason_code: "resource_exceeded", limit: "too_many_contacts", rows: 2345 } });
  assert.match(tooMany, /접촉 행 2345개가 구조당 상한 2000개를 넘어 저장하지 않았습니다\(자르지 않음\)/);
  assert.equal(lib.modelFailureText({ error: "fatal", message: "m" }), "fatal · m");
  assert.equal(lib.modelFailureText(null), "이유 없음");
});

test("job text, approval gate and re-attach use this protocol's tool and status only", () => {
  const job = status => ({ status, cancel_requested: false, failure: null });
  assert.match(lib.modelJobText(job("queued"), false), /저장되었습니다.*1단위/);
  assert.match(lib.modelJobText(job("queued"), true), /승인이 필요합니다/);
  assert.match(lib.modelJobText({ ...job("running"), cancel_requested: true }, false), /실행 중 · 취소 요청됨/);
  assert.equal(lib.modelJobText(job("done"), false), "변이 구조 모델링 완료");
  assert.match(lib.modelJobText({ status: "failed", cancel_requested: false, failure: { error: "tool_failed",
    reason_code: "coordinates_changed", message: "moved" } }, false), /변이 잔기 밖의 좌표가 바뀜 \(coordinates_changed\) · moved/);
  assert.equal(lib.modelJobText(null, false), "변이 구조 모델링 작업 없음");
  assert.equal(lib.modelApprovalRequired(409, { gate: "expensive_first_call", tool: "openmm_mutation_model" }), true);
  assert.equal(lib.modelApprovalRequired(409, { gate: "expensive_first_call", tool: "openmm_protein_minimize" }), false);
  assert.equal(lib.modelApprovalRequired(422, { gate: "expensive_first_call", tool: "openmm_mutation_model" }), false);
  assert.equal(lib.modelApprovalRequired(409, undefined), false);
  const jobs = [{ run_id: "r", protocol_id: "openmm_mutation_model_v1", status: "done", job_id: "a" },
    { run_id: "r", protocol_id: "qvina_dock_v1", status: "running", job_id: "b" },
    { run_id: "q", protocol_id: "openmm_mutation_model_v1", status: "running", job_id: "c" },
    { run_id: "r", protocol_id: "openmm_mutation_model_v1", status: "queued", job_id: "d" }];
  assert.equal(lib.modelActiveJob(jobs, "r").job_id, "d");
  assert.equal(lib.modelActiveJob(jobs.slice(0, 3), "r"), null);
  assert.equal(lib.modelActiveJob(null, "r"), null);
  assert.equal(lib.modelJobResult({ status: "done", artifacts: { mutation_model: "obj://r/mutation_model/m" } }),
    "obj://r/mutation_model/m");
  assert.equal(lib.modelJobResult({ status: "running", artifacts: { mutation_model: "x" } }), null);
  assert.equal(lib.modelJobResult({ status: "done", artifacts: {} }), null);
  assert.equal(lib.modelSubmitText({ plan_only: true }), "dry-run run이라 계획만 만들었습니다. 실제 계산과 결과 객체는 없습니다.");
  assert.match(lib.modelSubmitText({ job_id: "j", status: "done" }), /기존 작업을 다시 표시합니다 · j · done/);
  assert.equal(lib.isPlanOnly({ plan_only: true }), true);
  assert.equal(lib.isPlanOnly({ job_id: "j", status: "queued" }), false);
});

// ---- five states and late responses ----

test("five area states: unavailable, failed, loading, empty, ready", () => {
  const capability = { available: true, reason: null, reason_code: null };
  assert.deepEqual(plain(lib.modelAreaState({ runId: null })), { state: "unavailable", reason: lib.NO_RUN_REASON });
  assert.deepEqual(plain(lib.modelAreaState({ runId: "r", capability: null })),
    { state: "unavailable", reason: lib.CAPABILITY_REASON });
  assert.deepEqual(plain(lib.modelAreaState({ runId: "r", capability: { available: false, reason: "없음",
    reason_code: "openmm_unavailable" }, models: [] })), { state: "unavailable", reason: "없음 (openmm_unavailable)" });
  assert.equal(lib.modelAreaState({ runId: "r", capability: undefined, models: [] }).state, "loading");
  assert.equal(lib.modelAreaState({ runId: "r", capability }).state, "loading");
  assert.equal(lib.modelAreaState({ runId: "r", capability, models: [], job: { status: "running", failure: null } }).state,
    "loading");
  assert.deepEqual(plain(lib.modelAreaState({ runId: "r", capability, models: [] })),
    { state: "empty", message: lib.NO_MODELS_TEXT });
  assert.equal(lib.modelAreaState({ runId: "r", capability, models: [{}] }).state, "ready");
  assert.equal(lib.modelAreaState({ runId: "r", capability, models: [], detail: {} }).state, "ready");
  assert.deepEqual(plain(lib.modelAreaState({ runId: "r", capability, models: [], error: "읽기 실패" })),
    { state: "failed", message: "읽기 실패" });
  assert.equal(lib.modelAreaState({ runId: "r", capability, models: [{}], job: { status: "cancelled", failure: null } }).state,
    "failed");
  assert.match(lib.modelAreaState({ runId: "r", capability, models: [{}], job: { status: "failed",
    failure: { error: "tool_failed", reason_code: "energy_invalid", message: "nan" } } }).message, /energy_invalid/);
  for (const state of ["loading", "ready", "empty", "failed", "unavailable"]) assert.ok(lib.MODEL_STATE_TEXT[state]);
  // Docking-pair area.
  const docking = { available: true, reason: null, reason_code: null };
  assert.equal(lib.pairAreaState({ runId: "r", capability: docking, pairs: { total: 0 } }).state, "empty");
  assert.equal(lib.pairAreaState({ runId: "r", capability: docking, pairs: { total: 2 } }).state, "ready");
  assert.equal(lib.pairAreaState({ runId: "r", capability: docking }).state, "loading");
  assert.equal(lib.pairAreaState({ runId: "r", capability: { available: false, reason: "qvina 없음", reason_code: "engine_missing" },
    pairs: { total: 1 } }).state, "unavailable");
  assert.equal(lib.pairAreaState({ runId: "r", capability: docking, error: "x", pairs: { total: 1 } }).state, "failed");
});

test("late responses apply only when run, model handle, area and that area's number are all current", () => {
  let counters = lib.initialModelCounters();
  const first = lib.nextModelRequest(counters, "contacts", "r", "h");
  counters = first.counters;
  assert.equal(lib.modelResponseCurrent(first.stamp, first.stamp), true);
  const second = lib.nextModelRequest(counters, "contacts", "r", "h");
  assert.equal(lib.modelResponseCurrent(first.stamp, second.stamp), false);
  assert.equal(lib.modelResponseCurrent(second.stamp, second.stamp), true);
  // Another area's request does not make this one stale.
  const pairs = lib.nextModelRequest(second.counters, "pairs", "r", "h");
  assert.equal(pairs.counters.contacts, second.counters.contacts);
  assert.equal(lib.modelResponseCurrent(second.stamp, { ...second.stamp }), true);
  assert.equal(lib.modelResponseCurrent(second.stamp, { ...second.stamp, runId: "q" }), false);
  assert.equal(lib.modelResponseCurrent(second.stamp, { ...second.stamp, handle: "h2" }), false);
  assert.equal(lib.modelResponseCurrent(second.stamp, { ...second.stamp, area: "pairs" }), false);
  assert.equal(lib.modelResponseCurrent({ ...second.stamp, runId: null }, { ...second.stamp, runId: null }), false);
  assert.equal(lib.modelReportSavedForRun(second.stamp, "r"), true);
  assert.equal(lib.modelReportSavedForRun(second.stamp, "q"), false);
});

// ---- display of one stored model ----

const RES = { model_number: 1, chain_auth: "A", chain_label: null, seq_auth: 10, seq_label: 10, icode: "", resname: "ILE" };
const PARTNER = { model_number: 1, chain_auth: "A", chain_label: "A", seq_auth: 12, seq_label: null, icode: "B", resname: "HIS" };
function structureEntry(overrides) {
  return { structure_object: "obj://r/structure/x", structure_sha256: "a".repeat(64), system_xml_sha256: "b".repeat(64),
    topology_sha256: "c".repeat(64), heavy_atoms: 602, added_hydrogens: 629, added_heavy_atoms: [],
    protonation_variants: [], disulfide_bonds: [],
    energy: { before_kJ_mol: -1234.565, after_kJ_mol: -5678.123, unit: "kJ/mol", engine: "OpenMM",
      force_field: "amber14-all + implicit/gbn2", convergence: "convergence_not_claimed" },
    sasa: { residue: RES, engine: "FreeSASA", value_A2: 12.345, parameters: {} },
    contacts: { cutoff_A: 4, excluded_bond_distance: 3, count: 17, residue_count: 5 }, ...overrides };
}
const RESULT = {
  candidate: { candidate_set: SET, candidate_index: 3, position_index: 1, from: "I", to: "A", residue: RES,
    mutant_resname: "ALA" },
  parameters: { seed: 11, contact_cutoff_A: 4, selection_policy: "protein_only", hydrogen_policy: "rebuild_pH7" },
  structures: {
    wild_type_reference: structureEntry({}),
    mutant: structureEntry({ heavy_atoms: 599, added_hydrogens: 620,
      added_heavy_atoms: [{ atom_name: "CB", element: "C" }],
      energy: { before_kJ_mol: -1000.005, after_kJ_mol: -4000.004, unit: "kJ/mol", engine: "OpenMM",
        force_field: "amber14-all + implicit/gbn2", convergence: "convergence_not_claimed" },
      sasa: { residue: { ...RES, resname: "ALA" }, engine: "FreeSASA", value_A2: 0.005, parameters: {} },
      contacts: { cutoff_A: 4, excluded_bond_distance: 3, count: 0, residue_count: 0 },
      disulfide_bonds: [[PARTNER, RES]] }),
  },
  comparison: { mutated_residue: RES, resnames: { wild_type_reference: "ILE", mutant: "ALA" },
    new_disulfide_in_mutant: true, protonation_difference_count: 1 },
  protonation_differences: [{ residue: PARTNER, wild_type_reference: "HIE", mutant: null }],
  limitations: [lib.MODEL_LIMITATIONS[0], lib.MODEL_LIMITATIONS[1], lib.MODEL_LIMITATIONS[6]],
};

test("numbers: two decimals with decimal-string ROUND_HALF_UP; null is '—' with a reason, never 0", () => {
  assert.equal(lib.energyText(-1234.565), "-1234.57");
  assert.equal(lib.energyText(1.005), "1.01");
  assert.equal(lib.energyText(-0.004), "0.00");
  assert.equal(lib.sasaText(12.345), "12.35 Å²");
  assert.equal(lib.sasaText(0), "0.00 Å²");
  assert.equal(lib.distanceText(3.005), "3.01 Å");
  assert.equal(lib.distanceText(2.675), "2.68 Å");
  assert.equal(lib.countText(0), "0");
  for (const fn of [lib.energyText, lib.sasaText, lib.distanceText, lib.countText]) {
    assert.equal(fn(null, "계산하지 않음"), "— (계산하지 않음)");
    assert.equal(fn(null), "— (값 없음)");
  }
});

test("side-by-side rows hold one stored value per structure and nothing derived from both", () => {
  const rows = plain(lib.sideBySideRows(RESULT));
  assert.deepEqual(rows.map(row => row.key), ["resname", "energy_before", "energy_after", "sasa", "contacts",
    "contact_residues", "added_heavy_atoms", "disulfide_bonds", "heavy_atoms", "added_hydrogens"]);
  const byKey = Object.fromEntries(rows.map(row => [row.key, row]));
  assert.deepEqual(byKey.energy_before.values, { wild_type_reference: "-1234.57", mutant: "-1000.01" });
  assert.deepEqual(byKey.energy_after.values, { wild_type_reference: "-5678.12", mutant: "-4000.00" });
  assert.equal(byKey.energy_before.label, "OpenMM Amber14-all + GBn2 전위(kJ/mol) · 최소화 전");
  assert.deepEqual(byKey.sasa.values, { wild_type_reference: "12.35 Å²", mutant: "0.01 Å²" });
  assert.deepEqual(byKey.contacts.values, { wild_type_reference: "17", mutant: "0" });
  assert.match(byKey.contacts.label, /4\.00 Å 이하, 3결합 이내 제외/);
  assert.deepEqual(byKey.added_heavy_atoms.values, { wild_type_reference: "0개", mutant: "1개 (CB C)" });
  assert.deepEqual(byKey.resname.values, { wild_type_reference: "ILE", mutant: "ALA" });
  assert.deepEqual(byKey.disulfide_bonds.values, { wild_type_reference: "0", mutant: "1" });
  // No row holds a value computed from the two structures (any subtraction of the stored numbers).
  const text = JSON.stringify(rows);
  for (const derived of ["-234.56", "234.56", "-1678.12", "1678.12", "12.34", "4443.69", "3678.12", "-4444",
    "17 → 0", "-17", "2.98"]) assert.ok(!text.includes(derived), derived);
  for (const row of rows) assert.deepEqual(Object.keys(row.values), ["wild_type_reference", "mutant"]);
  assert.deepEqual(plain(lib.modelForbiddenWords(rows.map(row => row.label).join("\n"))), []);
});

test("mutation summary, protonation and disulfide rows keep the stored 7 fields (nulls included)", () => {
  const summary = lib.mutationSummaryText(RESULT.candidate);
  assert.match(summary, /^ILE A:10 · I → A \(ILE → ALA\)/);
  assert.match(summary, /chain_label=null/);
  assert.match(summary, /후보 번호 3/);
  assert.deepEqual(plain(lib.protonationRows(RESULT)), [{ residue: "HIS A:12B",
    fields: 'model_number=1, chain_auth="A", chain_label="A", seq_auth=12, seq_label=null, icode="B", resname="HIS"',
    values: { wild_type_reference: "HIE", mutant: "기본 템플릿 (null)" } }]);
  assert.equal(lib.disulfideText(RESULT.structures.mutant.disulfide_bonds), "HIS A:12B–ILE A:10");
  assert.equal(lib.disulfideText([]), "0개");
});

test("limitation sentences are the stored ones, verbatim and in stored order", () => {
  assert.equal(lib.modelLimitations(RESULT), RESULT.limitations);
  assert.deepEqual(plain(lib.unknownLimitations(RESULT.limitations)), []);
  assert.deepEqual(plain(lib.unknownLimitations(["바뀐 문장"])), ["바뀐 문장"]);
  // Conditional L5/L6 are not added or re-ordered here.
  assert.deepEqual(plain(lib.modelLimitations({ limitations: [lib.MODEL_LIMITATIONS[6], lib.MODEL_LIMITATIONS[0]] })),
    [lib.MODEL_LIMITATIONS[6], lib.MODEL_LIMITATIONS[0]]);
});

test("contact pages: query, cells, and a zero count that reads as a computed 0", () => {
  assert.equal(lib.modelContactQuery("mutant", 2), "structure=mutant&page=2&page_size=100");
  assert.equal(lib.modelContactQuery("wild_type_reference", 0, 500), "structure=wild_type_reference&page=1&page_size=200");
  const row = { index: 0, atom_name: "CD1", element: "C", partner_residue: PARTNER, partner_atom_name: "NE2",
    partner_element: "N", distance_A: 3.005 };
  assert.deepEqual(plain(lib.contactRowCells(row)), ["1", "CD1 (C)", "HIS A:12B", "NE2 (N)", "3.01 Å"]);
  assert.equal(lib.CONTACT_TABLE_HEADERS.length, lib.contactRowCells(row).length);
  const page = { structure: "wild_type_reference", cutoff_A: 4, total: 150, page: 2, page_size: 100, rows: new Array(50) };
  assert.equal(lib.contactPageText(page), "야생형 기준: 중원자 접촉 150개 중 101–150");
  const zero = lib.contactPageText({ ...page, structure: "mutant", total: 0, page: 1, rows: [] });
  assert.match(zero, /^변이형: .*0개입니다\(4\.00 Å 안, 3결합 이내 제외\)\. 계산한 결과이며 빈 값이 아닙니다\.$/);
  assert.equal(lib.contactPageCount(0), 1);
  assert.equal(lib.contactPageCount(201), 3);
});

test("list rows, download labels and report matching", () => {
  assert.equal(lib.modelListRowText({ handle: "h", created_seq: 9, valid: true,
    candidate: { candidate_set: SET, candidate_index: 3, residue: RES, from: "I", to: "A", mutant_resname: "ALA" },
    structure: { handle: "s", model_number: 1, structure_kind: "prepared_structure" }, parameters: RESULT.parameters }),
  "생성 순번 9 · ILE A:10 I → A · seed 11 · cutoff 4.00 Å");
  assert.match(lib.modelListRowText({ handle: "h", created_seq: 4, valid: false, candidate: null, structure: null,
    parameters: null }), /읽을 수 없음: 저장된 결과가 검증되지 않음 \(method_evidence_invalid\)/);
  assert.equal(lib.structureDownloadLabel("mutant"), "변이형 구조 mmCIF 내려받기");
  const artifact = { manifest: { schema: "method_report_manifest@1", analysis_type: "mutation_model", result_handle: "M" } };
  assert.equal(lib.modelReportMatches(artifact, "M"), true);
  assert.equal(lib.modelReportMatches(artifact, "N"), false);
  assert.equal(lib.modelReportMatches({ manifest: { ...artifact.manifest, analysis_type: "mutation_candidates" } }, "M"), false);
  assert.equal(reportLibrary.reportKindLabel({ kind: "mutation_model", handle: "h", target_handle: "M", created_seq: 1 }),
    "변이 구조 모델 보고서");
});

// ---- same-condition docking requests ----

const MODEL = "obj://r/mutation_model/m";
const ACK_ALL = { keep_input_protonation: true, tool_assigned_types_charges: true, rigid_no_optimization: true };
function pairForm(overrides = {}) {
  return lib.patchPairDockingForm(lib.initialPairDockingForm(), { ligandSource: "sdf",
    sdfHandle: "obj://r/chemical_raw_input/lig", boxSource: "ligand_range", seed: "7", acknowledgement: { ...ACK_ALL },
    ...overrides });
}

test("two requests that differ only in receptor_source.side, with no imported-receptor key", () => {
  const check = lib.pairDockingRequests(pairForm(), MODEL);
  assert.equal(check.ok, true);
  const { wild_type_reference: wild, mutant } = plain(check.args);
  assert.deepEqual(wild, { receptor_source: { kind: "mutation_model", mutation_model: MODEL, side: "wild_type_reference" },
    ligand: { source: "sdf", sdf_handle: "obj://r/chemical_raw_input/lig" }, mode: "free",
    box: { source: "ligand_range", margin_A: 8 }, parameters: { seed: 7, exhaustiveness: 8, num_modes: 9, energy_range: 3 },
    acknowledgement: ACK_ALL });
  assert.deepEqual({ ...mutant, receptor_source: { ...mutant.receptor_source, side: "wild_type_reference" } }, wild);
  assert.equal(mutant.receptor_source.side, "mutant");
  for (const args of [wild, mutant]) {
    assert.deepEqual(Object.keys(args), ["receptor_source", "ligand", "mode", "box", "parameters", "acknowledgement"]);
    for (const key of ["receptor_handle", "receptor_model_number", "connectivity", "receptor_instance"])
      assert.ok(!(key in args), key);
  }
  // The condition part is exactly what the M18 builder makes from the same values.
  const m18 = docking.dockingArgs({ ...docking.initialDockingForm(), ...pairForm(), receptorHandle: "x",
    receptorModelNumber: 1, connectivity: "pdb_conect", instance: { kind: "none" } });
  for (const key of ["ligand", "mode", "box", "parameters", "acknowledgement"])
    assert.deepEqual(wild[key], plain(m18.args[key]), key);
  // A manual box passes through unchanged.
  const manual = lib.pairDockingRequests(pairForm({ boxSource: "manual", center: ["1", "2", "3"], size: ["20", "20", "20"] }),
    MODEL);
  assert.equal(manual.ok, true);
  assert.deepEqual(plain(manual.args.mutant.box), { source: "manual", center_A: [1, 2, 3], size_A: [20, 20, 20] });
});

test("SDF ligands only: the M17 candidate source is never offered, kept or sent (user decision)", () => {
  assert.equal(lib.pairLigandSourceDisabledReason("sdf"), null);
  assert.equal(lib.pairLigandSourceDisabledReason("candidate"), lib.PAIR_SDF_ONLY_REASON);
  assert.match(lib.PAIR_SDF_ONLY_REASON, /3D SDF 리간드만/);
  // Choosing the candidate source through the form patch drops it and keeps no candidate field.
  const patched = lib.patchPairDockingForm(pairForm(), { ligandSource: "candidate",
    candidateSetHandle: "obj://r/ligand_candidate_set/s", candidateId: "c_1", parentSdfHandle: "obj://r/chemical_raw_input/p" });
  assert.equal(patched.ligandSource, null);
  assert.equal(patched.candidateSetHandle, null);
  assert.equal(patched.candidateId, null);
  assert.equal(patched.parentSdfHandle, null);
  // A form that still names it (not through the patch) builds no request, with the backend's admission reason.
  const forced = lib.pairDockingRequests({ ...pairForm(), ligandSource: "candidate", sdfHandle: null,
    candidateSetHandle: "obj://r/ligand_candidate_set/s", candidateId: "c_1", parentSdfHandle: "obj://r/chemical_raw_input/p" },
    MODEL);
  assert.equal(forced.ok, false);
  assert.ok(plain(forced.errors).includes(`${lib.PAIR_SDF_ONLY_REASON} (mode_source_mismatch)`), forced.errors);
});

test("another model cannot be opened while the same-condition action is mid-way (visible reason)", () => {
  assert.equal(lib.modelSwitchBlockedReason(false), null);
  assert.equal(lib.modelSwitchBlockedReason(true), lib.MODEL_SWITCH_PAIR_BUSY_REASON);
  assert.match(lib.MODEL_SWITCH_PAIR_BUSY_REASON, /다른 모델을 열 수 없습니다/);
});

test("pair requests: model required, free docking only, no instance-range box, M18 value and acknowledgement rules", () => {
  assert.match(errorsOf(lib.pairDockingRequests(pairForm(), null)), /변이 구조 모델을 먼저 여세요/);
  assert.equal(lib.initialPairDockingForm().mode, "free");
  assert.equal(lib.patchPairDockingForm(pairForm(), { mode: "core_fixed" }).mode, "free");
  assert.match(errorsOf(lib.pairDockingRequests({ ...pairForm(), mode: "core_fixed" }, MODEL)), /자유 도킹만/);
  assert.equal(lib.patchPairDockingForm(pairForm(), { boxSource: "instance_range" }).boxSource, null);
  assert.match(errorsOf(lib.pairDockingRequests({ ...pairForm(), boxSource: "instance_range" }, MODEL)),
    /인스턴스 범위 상자를 쓸 수 없습니다\. \(box_invalid\)/);
  assert.equal(lib.pairBoxSourceDisabledReason("ligand_range"), null);
  assert.deepEqual(plain(lib.PAIR_BOX_SOURCES), ["ligand_range", "manual"]);
  assert.match(errorsOf(lib.pairDockingRequests(pairForm({ seed: "" }), MODEL)), /seed/);
  assert.match(errorsOf(lib.pairDockingRequests(pairForm({ acknowledgement: { ...ACK_ALL, rigid_no_optimization: false } }),
    MODEL)), /acknowledgement_missing/);
  assert.match(errorsOf(lib.pairDockingRequests(pairForm({ boxSource: "manual", center: ["0", "0", "0"],
    size: ["41", "20", "20"] }), MODEL)), /box_too_large/);
  const initial = lib.initialPairDockingForm();
  assert.equal(initial.ligandSource, null);
  assert.equal(initial.boxSource, null);
  assert.equal(initial.seed, "");
  assert.deepEqual(plain(initial.acknowledgement), { keep_input_protonation: false, tool_assigned_types_charges: false,
    rigid_no_optimization: false });
  // No candidate field survives a patch; nothing is chosen in their place.
  const set = lib.patchPairDockingForm(pairForm({ candidateSetHandle: "s1", candidateId: "c", parentSdfHandle: "p" }),
    { candidateSetHandle: "s2" });
  assert.equal(set.candidateSetHandle, null);
  assert.equal(set.candidateId, null);
  assert.equal(set.parentSdfHandle, null);
});

test("the two-job action needs the docking capability, the 2-unit confirmation and no running docking job", () => {
  const capability = { available: true, reason: null };
  const check = lib.pairDockingRequests(pairForm(), MODEL);
  const input = { capability, busy: false, unitsConfirmed: true, activeJobs: [], check };
  assert.equal(lib.pairSubmitBlockedReason(input), null);
  assert.match(lib.pairSubmitBlockedReason({ ...input, unitsConfirmed: false }), /2개, 합쳐서 비싼 계산 2단위/);
  assert.equal(lib.pairSubmitBlockedReason({ ...input, capability: { available: false, reason: "qvina 없음" } }), "qvina 없음");
  assert.match(lib.pairSubmitBlockedReason({ ...input, activeJobs: [{ status: "claimed" }] }), /진행 중인 도킹 작업/);
  assert.match(lib.pairSubmitBlockedReason({ ...input, check: lib.pairDockingRequests(pairForm(), null) }), /먼저 여세요/);
  assert.match(lib.PAIR_UNITS_NOTICE, /합쳐서 2단위/);
});

test("submissions go in order and one side's refusal never hides or stops the other", () => {
  let submission = lib.initialPairSubmission();
  assert.equal(lib.nextPairSubmitSide(submission), "wild_type_reference");
  submission = lib.pairSubmitStarted(submission, "wild_type_reference");
  assert.equal(lib.nextPairSubmitSide(submission), null);
  submission = lib.pairSubmitAnswered(submission, "wild_type_reference",
    { ok: false, error: "이 run의 게시된 변이 구조 모델이 아님 (mutation_model_invalid)" });
  assert.equal(lib.nextPairSubmitSide(submission), "mutant");
  assert.equal(lib.pairSubmissionDone(submission), false);
  submission = lib.pairSubmitAnswered(lib.pairSubmitStarted(submission, "mutant"), "mutant",
    { ok: true, result: { job_id: "job-m", status: "queued" } });
  assert.equal(lib.pairSubmissionDone(submission), true);
  assert.equal(lib.nextPairSubmitSide(submission), null);
  assert.equal(submission.wild_type_reference.status, "refused");
  assert.equal(submission.mutant.status, "submitted");
  assert.equal(submission.mutant.jobId, "job-m");
  assert.match(lib.pairSubmitText(submission.wild_type_reference), /^야생형 기준: 제출 거절 · .*mutation_model_invalid/);
  assert.equal(lib.pairSubmitText(submission.mutant), "변이형: 작업 job-m · queued");
  const planned = lib.pairSubmitAnswered(lib.initialPairSubmission(), "mutant", { ok: true, result: { plan_only: true } });
  assert.equal(planned.mutant.status, "plan_only");
  assert.equal(planned.wild_type_reference.status, "pending");
  // Start order: the first queued side, only while no pair job is claimed or running.
  assert.equal(lib.nextPairStartSide({ wild_type_reference: { status: "queued" }, mutant: { status: "queued" } }),
    "wild_type_reference");
  assert.equal(lib.nextPairStartSide({ wild_type_reference: { status: "running" }, mutant: { status: "queued" } }), null);
  assert.equal(lib.nextPairStartSide({ wild_type_reference: { status: "failed" }, mutant: { status: "queued" } }), "mutant");
  assert.equal(lib.nextPairStartSide({ wild_type_reference: null, mutant: { status: "queued" } }), "mutant");
  assert.equal(lib.nextPairStartSide({ wild_type_reference: { status: "done" }, mutant: { status: "done" } }), null);
  assert.match(lib.pairJobText("mutant", { status: "failed", cancel_requested: false,
    failure: { error: "tool_failed", reason_code: "receptor_prep_failed", message: "x" } }, false), /^변이형: 도킹 작업 실패/);
  assert.equal(lib.pairApprovalRequired(409, { gate: "expensive_first_call", tool: "qvina_dock_ligand" }), true);
  assert.equal(lib.pairApprovalRequired(409, { gate: "expensive_first_call", tool: "openmm_mutation_model" }), false);
});

// ---- docking pair display ----

const SCORE_LABEL = "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)";
const CONDITION = { ligand: { source: "sdf", sdf_handle: "obj://r/chemical_raw_input/lig" }, mode: "free",
  box: { source: "ligand_range", margin_A: 8 },
  parameters: { seed: 7, exhaustiveness: 8, num_modes: 9, energy_range: 3, conformers: null }, method_pins_sha256: "e".repeat(64) };
function side(name, overrides) {
  return { side: name, job_id: `job-${name}`, job_status: "done", submitted_seq: 3, result_handle: null,
    score_kcal_mol: null, score_mode: null, reason_code: null, reason: null, ...overrides };
}
const PAIRS = { schema: "mutation_model_docking_pairs@1", handle: MODEL, score_label: SCORE_LABEL, total: 2, starts_job: false,
  pairs: [
    { index: 0, first_submitted_seq: 3, condition: CONDITION, both_published: true, sides: {
      wild_type_reference: side("wild_type_reference", { result_handle: "obj://r/docking_result/w", score_kcal_mol: -7.25,
        score_mode: 1 }),
      mutant: side("mutant", { result_handle: "obj://r/docking_result/m", score_kcal_mol: -6.05, score_mode: 1 }) } },
    { index: 1, first_submitted_seq: 9, condition: { ...CONDITION, parameters: { ...CONDITION.parameters, seed: 8 } },
      both_published: false, sides: {
        wild_type_reference: side("wild_type_reference", { job_status: "failed", reason_code: "job_failed",
          reason: "도킹 작업이 실패해 결과가 없다." }),
        // A defensive case: the server never sends a score without both_published; the screen still shows none.
        mutant: side("mutant", { result_handle: "obj://r/docking_result/m2", score_kcal_mol: -5.5, score_mode: 1,
          reason_code: "other_side_missing", reason: "다른 구조의 도킹 결과가 게시되지 않아 이 결과를 나란히 보이지 않는다." }) } },
  ] };

test("pair rows: scores side by side only when both are published; otherwise '없음(reason)' with the job status", () => {
  const rows = plain(lib.pairRows(PAIRS));
  assert.deepEqual(rows.map(row => row.index), [0, 1]);
  assert.deepEqual(rows[0].cells.wild_type_reference, { side: "wild_type_reference", job: "완료 (done)", score: "-7.3",
    text: "-7.3 · 모드 1(엔진 출력 순서)", resultHandle: "obj://r/docking_result/w" });
  assert.equal(rows[0].cells.mutant.score, "-6.1");
  assert.equal(rows[1].cells.wild_type_reference.score, null);
  assert.equal(rows[1].cells.wild_type_reference.text, "없음(도킹 작업이 실패해 결과가 없다.)");
  assert.equal(rows[1].cells.wild_type_reference.job, "실패 (failed)");
  assert.equal(rows[1].cells.mutant.score, null);
  assert.match(rows[1].cells.mutant.text, /^없음\(다른 구조의 도킹 결과가 게시되지 않아/);
  assert.equal(rows[1].cells.mutant.resultHandle, null);
  assert.match(rows[1].condition, /seed 8/);
  assert.equal(rows[0].condition, "3D SDF obj://r/chemical_raw_input/lig · 자유 도킹 · 상자 리간드 범위+여백 · 여백 8.00 Å · " +
    "seed 7 · exhaustiveness 8 · num_modes 9 · energy_range 3.00 kcal/mol");
  // Both published but qvina gave no pose: no number on either side.
  const empty = lib.pairSideCell({ both_published: true, condition: CONDITION, sides: {
    wild_type_reference: side("wild_type_reference", { result_handle: "w", reason_code: "no_modes",
      reason: "qvina가 자세를 내지 않은 빈 결과다." }), mutant: side("mutant", {}) } }, "wild_type_reference");
  assert.equal(empty.score, null);
  assert.equal(empty.text, "없음(qvina가 자세를 내지 않은 빈 결과다.)");
  // Not submitted, no reason sentence: the code is shown instead (never a number).
  assert.equal(lib.pairSideCell({ both_published: false, condition: CONDITION, sides: { wild_type_reference:
    side("wild_type_reference", { job_id: null, job_status: "not_submitted", reason_code: "not_submitted" }),
    mutant: side("mutant", {}) } }, "wild_type_reference").text, "없음(not_submitted)");
  // No difference between the two scores appears anywhere (-7.25 - -6.05 = -1.2).
  const text = JSON.stringify(rows);
  for (const derived of ["-1.2", "1.2", "1.20"]) assert.ok(!text.includes(derived), derived);
  assert.deepEqual(plain(lib.pairTableHeaders(PAIRS.score_label)), ["짝", "도킹 조건", `야생형 기준 · ${SCORE_LABEL}`,
    `변이형 · ${SCORE_LABEL}`]);
  assert.deepEqual(plain(lib.modelForbiddenWords([...lib.pairTableHeaders(PAIRS.score_label),
    ...rows.flatMap(row => [row.condition, row.cells.wild_type_reference.text, row.cells.mutant.text])].join("\n"))), []);
});

test("a manual box and a candidate ligand read from the stored condition", () => {
  const text = lib.pairConditionText({ ...CONDITION, ligand: { source: "candidate", candidate_set_handle: "S",
    candidate_id: "c_7", parent_sdf_handle: "P" }, box: { source: "manual", center_A: [1.005, 2, -3], size_A: [20, 22.5, 18] } });
  assert.match(text, /^M17 후보 c_7 · 후보 집합 S · 부모 SDF P · 자유 도킹 · 상자 중심 \(1\.01, 2\.00, -3\.00\) Å · 크기 \(20\.00, 22\.50, 18\.00\) Å/);
});

// ---- wording: no difference, change, rank, recommendation or stability claim anywhere on screen ----

test("the wording check finds each forbidden word; limitation sentences and the score name are exempt", () => {
  for (const [text, word] of [["순위", "순위"], ["추천 후보", "추천"], ["개선됨", "개선"], ["전위 증가", "증가"],
    ["SASA 감소", "감소"], ["안정성", "안정성"], ["ΔΔG", "ΔΔG"], ["Δ 값", "Δ"], ["best", "best"], ["rank", "rank"], ["improved", "improv"],
    ["두 값의 차이", "차이"], ["변화량", "변화량"], ["delta", "delta"], ["difference", "differen"], ["최고", "최고"],
    ["recommend", "recommend"], ["stability", "stabili"], ["affinity 친화", "친화"]])
    assert.ok(plain(lib.modelForbiddenWords(text)).includes(word), text);
  for (const sentence of lib.MODEL_LIMITATIONS) assert.deepEqual(plain(lib.modelForbiddenWords(sentence)), [], sentence);
  assert.deepEqual(plain(lib.modelForbiddenWords(`${lib.MODEL_LIMITATIONS[1]} 순위`)), ["ΔΔG", "안정성", "친화", "순위"]);
  assert.deepEqual(plain(lib.modelForbiddenWords(SCORE_LABEL)), []);
  assert.deepEqual(plain(lib.modelForbiddenWords("수용체는 최적화하지 않습니다")), []);
});

test("every fixed screen string of this module passes the wording check", () => {
  const texts = [
    lib.AREA_TITLE, lib.ENERGY_LABEL, lib.SASA_LABEL, ...Object.values(lib.CONFIRMATION_LABEL), ...Object.values(lib.SIDE_LABEL),
    lib.MODEL_METHOD_NOTE, lib.MODEL_BUDGET_NOTE, lib.SIDE_BY_SIDE_NOTE, lib.NO_RUN_REASON, lib.CAPABILITY_REASON,
    lib.NO_MODELS_TEXT, lib.PAIR_AREA_TITLE, lib.PAIR_UNITS_NOTICE, lib.PAIR_CONDITION_NOTE, lib.PAIR_SCORE_NOTE,
    lib.NO_PAIRS_TEXT, lib.PAIR_MODE_ONLY, lib.PAIR_INSTANCE_RANGE_REASON, ...Object.values(lib.MODEL_REASON_LABEL),
    ...Object.values(lib.MODEL_STATE_TEXT), ...lib.CONTACT_TABLE_HEADERS,
    ...lib.sideBySideRows(RESULT).map(row => row.label),
    ...[null, "queued", "running", "done", "cancelled", "failed"].map(status => lib.modelJobText(status && { status,
      cancel_requested: false, failure: null }, false)),
    lib.modelJobText({ status: "queued", cancel_requested: false, failure: null }, true),
    lib.modelSubmitText({ plan_only: true }), ...plain(lib.modelRequest(lib.initialModelForm())).errors,
    ...plain(lib.pairDockingRequests({ ...lib.initialPairDockingForm(), boxSource: "instance_range" }, null)).errors,
    lib.pairSubmitBlockedReason({ capability: { available: true, reason: null }, busy: false, unitsConfirmed: false,
      activeJobs: [], check: lib.pairDockingRequests(pairForm(), MODEL) }),
    ...["pending", "submitting", "plan_only", "refused", "submitted"].map(status => lib.pairSubmitText({ side: "mutant",
      status, jobId: "j", jobStatus: "queued", error: "e" })),
    ...docking.ACKNOWLEDGEMENT_KEYS.map(key => docking.ACKNOWLEDGEMENT_LABEL[key]),
    lib.contactPageText({ structure: "mutant", cutoff_A: 4, total: 0, page: 1, page_size: 100, rows: [] }),
    ...["not_submitted", "queued", "running", "done", "failed", "cancelled", "interrupted"].map(lib.pairJobStatusText),
    lib.PAIR_SDF_ONLY_REASON, lib.MODEL_SWITCH_PAIR_BUSY_REASON,
  ];
  for (const text of texts) assert.deepEqual(plain(lib.modelForbiddenWords(text)), [], text);
});

test("the module computes no difference: no subtraction of stored values and no delta/rank fields", () => {
  for (const pattern of [/(before|after)_kJ_mol\s*[-+]/, /[-+]\s*\w+\.(before|after)_kJ_mol/, /value_A2\s*[-+]/,
    /[-+]\s*\w+\.value_A2/, /score_kcal_mol\s*[-+]/, /[-+]\s*\w+\.score_kcal_mol/, /contacts\.count\s*[-+]/,
    /\b(delta|difference|rank|best|improv)\w*\s*[:=]/i])
    assert.ok(!pattern.test(LIB_SOURCE), String(pattern));
});
