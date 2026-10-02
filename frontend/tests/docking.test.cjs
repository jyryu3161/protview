const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

function load(filename, dependencies = {}, globals = {}) {
  const source = fs.readFileSync(path.join(__dirname, `../src/lib/${filename}.ts`), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const moduleObject = { exports: {} };
  vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports,
    require: name => dependencies[name] ?? require(name), ...globals });
  return moduleObject.exports;
}
const siteAnnotation = load("site-annotation", { "./comparison": load("comparison"), "./numbering": load("numbering"),
  "./event-model": load("event-model") });
const lib = load("docking", { "./site-annotation": siteAnnotation });
const plain = value => JSON.parse(JSON.stringify(value));

// ---- closed sets, ranges and fixed wording are read from backend/mw/docking_constants.py itself ----
const constantsSource = fs.readFileSync(path.join(__dirname, "../../backend/mw/docking_constants.py"), "utf8");
function backendTuple(name) {
  const match = new RegExp(`^${name} = \\(([^)]*)\\)`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map(item => item[1]);
}
function backendNumbers(names) {
  const match = new RegExp(`^${names.join(", ")} = ([^#\\n]+)`, "m").exec(constantsSource);
  assert.ok(match, `backend constants ${names} not found`);
  return match[1].split(",").map(text => Number(text.trim().replace(/_/g, "")));
}
function backendString(name) {
  const match = new RegExp(`^${name} = "([^"]+)"`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return match[1];
}
function backendLimitations() {
  const start = constantsSource.indexOf("LIMITATIONS = (");
  const end = constantsSource.indexOf("\n)\n", start);
  const block = constantsSource.slice(start + "LIMITATIONS = (".length, end).replace(/"\s*\n\s*"/g, "");
  return [...block.matchAll(/"([^"]+)"/g)].map(item => item[1]);
}

// Every code the docking area can show. Adding a code to a backend set (or a label here) breaks this test, so the
// Korean names and this list are changed together with backend/mw/docking_constants.py.
const REASON_CODES = [
  // 5.3 closed sets (admission and worker)
  "receptor_invalid", "receptor_hydrogens_missing", "receptor_unsupported_residue", "receptor_altloc_present",
  "receptor_instance_unknown", "receptor_instance_ambiguous", "receptor_instance_covalent", "receptor_prep_failed",
  "ligand_unparseable", "ligand_record_count", "ligand_multiple_fragments", "ligand_element_not_allowed",
  "ligand_too_many_atoms", "ligand_too_many_torsions", "ligand_not_3d", "ligand_hydrogens_missing", "ligand_prep_failed",
  "candidate_unknown", "parent_mismatch", "parent_not_3d", "core_match_failed", "core_match_ambiguous", "embed_failed",
  "box_invalid", "box_too_large", "box_no_receptor_atoms", "engine_failed", "engine_output_invalid", "resource_exceeded",
  // admission-only and capability (5.3, 5.5)
  "invalid_job_arguments", "mode_source_mismatch", "acknowledgement_missing",
  "worker_missing", "engine_missing", "engine_hash_mismatch", "handshake_failed", "version_mismatch",
  // job queue reasons a docking submission or start can return, dry-run plan, list read
  "worker_version_invalid", "process_identity_unavailable", "global_concurrency_busy", "global_job_cleanup_pending",
  "global_job_ledger_unavailable", "dry_run", "evidence_invalid",
];

test("closed sets, ranges and fixed wording equal the backend constants", () => {
  for (const name of ["RECEPTOR_REASONS", "LIGAND_REASONS", "CANDIDATE_REASONS", "BOX_REASONS", "ENGINE_REASONS",
    "ADMISSION_ONLY_REASONS", "CAPABILITY_REASONS", "MODES", "LIGAND_SOURCES", "BOX_SOURCES", "CONTACT_KINDS",
    "ACKNOWLEDGEMENT_KEYS"]) assert.deepEqual(plain(lib[name]), backendTuple(name), name);
  for (const code of ["RECEPTOR_REASONS", "LIGAND_REASONS", "CANDIDATE_REASONS", "BOX_REASONS", "ENGINE_REASONS",
    "ADMISSION_ONLY_REASONS", "CAPABILITY_REASONS"].flatMap(backendTuple)) assert.ok(REASON_CODES.includes(code), code);
  assert.deepEqual([lib.SEED_MIN, lib.SEED_MAX], backendNumbers(["SEED_MIN", "SEED_MAX"]));
  assert.deepEqual([lib.EXHAUSTIVENESS_MIN, lib.EXHAUSTIVENESS_MAX, lib.EXHAUSTIVENESS_DEFAULT],
    backendNumbers(["EXHAUSTIVENESS_MIN", "EXHAUSTIVENESS_MAX", "EXHAUSTIVENESS_DEFAULT"]));
  assert.deepEqual([lib.NUM_MODES_MIN, lib.NUM_MODES_MAX, lib.NUM_MODES_DEFAULT],
    backendNumbers(["NUM_MODES_MIN", "NUM_MODES_MAX", "NUM_MODES_DEFAULT"]));
  assert.deepEqual([lib.ENERGY_RANGE_MIN, lib.ENERGY_RANGE_MAX, lib.ENERGY_RANGE_DEFAULT],
    backendNumbers(["ENERGY_RANGE_MIN", "ENERGY_RANGE_MAX", "ENERGY_RANGE_DEFAULT"]));
  assert.deepEqual([lib.CONFORMERS_MIN, lib.CONFORMERS_MAX, lib.CONFORMERS_DEFAULT],
    backendNumbers(["CONFORMERS_MIN", "CONFORMERS_MAX", "CONFORMERS_DEFAULT"]));
  assert.deepEqual([lib.MARGIN_MIN_A, lib.MARGIN_MAX_A, lib.MARGIN_DEFAULT_A],
    backendNumbers(["MARGIN_MIN_A", "MARGIN_MAX_A", "MARGIN_DEFAULT_A"]));
  assert.deepEqual([lib.BOX_SIDE_MIN_A, lib.BOX_SIDE_MAX_A], backendNumbers(["BOX_SIDE_MIN_A", "BOX_SIDE_MAX_A"]));
  assert.deepEqual([lib.MAX_BOX_CENTER_ABS_A], backendNumbers(["MAX_BOX_CENTER_ABS_A"]));
  assert.equal(lib.DOCKING_PROTOCOL, backendString("PROTOCOL"));
  assert.equal(lib.DOCKING_TOOL, backendString("TOOL"));
  assert.equal(lib.SCORE_LABEL, backendString("SCORE_LABEL"));
  assert.equal(lib.SCORE_COLUMN_LABEL, backendString("SCORE_COLUMN_LABEL"));
  assert.equal(lib.SCORE_LABEL, "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)");
  assert.equal(lib.SCORE_COLUMN_LABEL, "qvina 점수(kcal/mol)");
  const limitations = backendLimitations();
  assert.equal(limitations.length, 11);
  assert.deepEqual(plain(lib.DOCKING_LIMITATIONS), limitations);
});

test("every reason code reads as 'Korean (code)'; unknown codes stay raw", () => {
  assert.deepEqual(Object.keys(lib.DOCKING_REASON_LABEL).sort(), [...REASON_CODES].sort());
  for (const code of REASON_CODES) {
    const text = lib.dockingReasonText(code);
    assert.ok(text.endsWith(` (${code})`) && /[가-힣]/.test(text), text);
  }
  assert.equal(lib.dockingReasonText("made_up_code"), "made_up_code");
  assert.equal(lib.dockingReasonText("constructor"), "constructor");
  assert.equal(lib.dockingReasonText("ligand_not_3d"), "리간드 좌표가 3D가 아님(모든 원자의 z가 같음) (ligand_not_3d)");
});

test("capability, failure and refused-request texts carry the code; resource_exceeded adds the hint", () => {
  assert.equal(lib.dockingCapabilityText({ reason: "qvina 2.1 엔진 환경이 없습니다.", reason_code: "engine_missing" }),
    "qvina 2.1 엔진 환경이 없습니다. (engine_missing)");
  assert.equal(lib.dockingCapabilityText({ reason: null, reason_code: "version_mismatch" }),
    "작업 환경 패키지 버전이 고정 버전과 다름 (version_mismatch)");
  assert.equal(lib.dockingCapabilityText(null), "리간드 도킹 기능을 사용할 수 없습니다.");
  assert.equal(lib.dockingFailureText({ error: "input_invalid", message: "z all equal", reason_code: "ligand_not_3d" }),
    "리간드 좌표가 3D가 아님(모든 원자의 z가 같음) (ligand_not_3d) · z all equal");
  assert.equal(lib.dockingFailureText({ error: "resource_exceeded", message: "4 MiB", reason_code: "resource_exceeded" }),
    "결과 크기 상한 초과 (resource_exceeded) · 4 MiB · 모드 수를 줄여 다시 시도하세요.");
  assert.equal(lib.dockingFailureText({ error: "transient", message: "timeout" }), "transient · timeout");
  assert.equal(lib.dockingFailureText(null), "이유 없음");
  assert.equal(lib.dockingRequestErrorText({ message: "box", code: "input_invalid",
    detail: { reason_code: "box_too_large" } }), "상자 한 변이 40 Å 초과 (box_too_large) · box");
  assert.equal(lib.dockingRequestErrorText({ message: "left", code: "input_invalid",
    detail: { reason_code: "receptor_unsupported_residue", items: [{}, {}], total: 25 } }),
  "수용체에 물·금속 이온·보조인자·다른 리간드·지원하지 않는 잔기가 남아 있음 (receptor_unsupported_residue) · left · 목록 25개 중 2개 표시");
  assert.equal(lib.dockingRequestErrorText({ message: "HTTP 500" }), "요청 실패 · HTTP 500");
});

// ---- panel state ----

const READY_CAP = { available: true, reason: null, reason_code: null };

test("five panel states; zero modes is an empty scientific result, a failed job is a failure", () => {
  assert.deepEqual(plain(lib.dockingPanelState({ runId: null, capability: READY_CAP })),
    { state: "unavailable", reason: "구조 분석 탭에서 run을 먼저 고르세요." });
  assert.deepEqual(plain(lib.dockingPanelState({ runId: "r", capability: { available: false,
    reason: "qvina2 실행 파일의 SHA-256이 설치 기록·고정 값과 다릅니다.", reason_code: "engine_hash_mismatch" } })),
  { state: "unavailable", reason: "qvina2 실행 파일의 SHA-256이 설치 기록·고정 값과 다릅니다. (engine_hash_mismatch)" });
  assert.equal(lib.dockingPanelState({ runId: "r", capability: null }).state, "unavailable");
  assert.equal(lib.dockingPanelState({ runId: "r" }).state, "loading");
  assert.equal(lib.dockingPanelState({ runId: "r", capability: READY_CAP, loading: true }).state, "loading");
  assert.equal(lib.dockingPanelState({ runId: "r", capability: READY_CAP,
    job: { status: "running", failure: null } }).state, "loading");
  assert.deepEqual(plain(lib.dockingPanelState({ runId: "r", capability: READY_CAP, error: "읽기 실패" })),
    { state: "failure", message: "읽기 실패" });
  assert.deepEqual(plain(lib.dockingPanelState({ runId: "r", capability: READY_CAP, job: { status: "failed",
    failure: { error: "resource_exceeded", message: "big", reason_code: "resource_exceeded" } } })),
  { state: "failure", message: "작업 실패: 결과 크기 상한 초과 (resource_exceeded) · big · 모드 수를 줄여 다시 시도하세요." });
  assert.deepEqual(plain(lib.dockingPanelState({ runId: "r", capability: READY_CAP,
    job: { status: "cancelled", failure: null } })),
  { state: "failure", message: "작업이 취소되어 결과를 저장하지 않았습니다." });
  // A failed job never reads as an empty result, even when a 0-mode result is also passed.
  assert.equal(lib.dockingPanelState({ runId: "r", capability: READY_CAP, job: { status: "interrupted", failure: null },
    result: { modes: 0, mode: "free" } }).state, "failure");
  const empty = lib.dockingPanelState({ runId: "r", capability: READY_CAP, job: { status: "done", failure: null },
    result: { modes: 0, mode: "free" } });
  assert.equal(empty.state, "scientific_null");
  assert.match(empty.message, /실패가 아닙니다/);
  assert.match(lib.dockingPanelState({ runId: "r", capability: READY_CAP, result: { modes: 0, mode: "core_fixed" } })
    .message, /샘플이 0개/);
  assert.deepEqual(plain(lib.dockingPanelState({ runId: "r", capability: READY_CAP,
    result: { modes: 3, mode: "free" } })), { state: "ready" });
  assert.deepEqual(plain(lib.dockingPanelState({ runId: "r", capability: READY_CAP })), { state: "ready" });
});

// ---- compatibility ----

const LIGAND_RES = { model_number: 1, chain_auth: "A", chain_label: null, seq_auth: 300, seq_label: null, icode: "",
  resname: "XYZ" };

test("core-fixed only with the candidate source; instance range only with a chosen instance", () => {
  assert.equal(lib.modeDisabledReason("sdf", "free"), null);
  assert.equal(lib.modeDisabledReason("candidate", "free"), null);
  assert.equal(lib.modeDisabledReason("candidate", "core_fixed"), null);
  assert.match(lib.modeDisabledReason("sdf", "core_fixed"), /\(mode_source_mismatch\)$/);
  assert.match(lib.modeDisabledReason(null, "free"), /리간드 출처/);
  for (const source of ["ligand_range", "manual"]) {
    assert.equal(lib.boxSourceDisabledReason(source, { kind: "unset" }), null);
    assert.equal(lib.boxSourceDisabledReason(source, { kind: "none" }), null);
  }
  assert.ok(lib.boxSourceDisabledReason("instance_range", { kind: "none" }));
  assert.ok(lib.boxSourceDisabledReason("instance_range", { kind: "unset" }));
  assert.equal(lib.boxSourceDisabledReason("instance_range", { kind: "instance", residue: LIGAND_RES }), null);
});

test("residue identity keeps exactly the seven fields with nulls; instances come from the chosen model only", () => {
  const extra = { ...LIGAND_RES, display: "A/XYZ300", atom_count: 30 };
  assert.deepEqual(Object.keys(lib.exactResidue(extra)),
    ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"]);
  assert.deepEqual(plain(lib.exactResidue(extra)), LIGAND_RES);
  assert.ok(lib.sameResidue(LIGAND_RES, { ...LIGAND_RES }));
  assert.ok(!lib.sameResidue(LIGAND_RES, { ...LIGAND_RES, chain_label: "B" }));
  assert.ok(!lib.sameResidue(LIGAND_RES, { ...LIGAND_RES, icode: "A" }));
  assert.ok(!lib.sameResidue(LIGAND_RES, { ...LIGAND_RES, seq_label: 300 }));
  const listing = { models: [{ model_number: 1, instances: [{ residue: LIGAND_RES, atom_count: 3,
    element_counts: { C: 2, O: 1 } }] }, { model_number: 2, instances: [] }] };
  assert.equal(lib.modelInstances(listing, 1).length, 1);
  assert.deepEqual(plain(lib.modelInstances(listing, 2)), []);
  assert.deepEqual(plain(lib.modelInstances(listing, 3)), []);
  assert.deepEqual(plain(lib.modelInstances(listing, null)), []);
});

// ---- job arguments ----

const ACK_ALL = { keep_input_protonation: true, tool_assigned_types_charges: true, rigid_no_optimization: true };
function form(overrides = {}) {
  return { ...lib.initialDockingForm(), receptorHandle: "obj://r/chemical_raw_input/rec", receptorModelNumber: 1,
    connectivity: "pdb_conect", instance: { kind: "none" }, ligandSource: "sdf", sdfHandle: "obj://r/chemical_raw_input/lig",
    mode: "free", boxSource: "ligand_range", seed: "7", acknowledgement: { ...ACK_ALL }, ...overrides };
}
const errorsOf = check => { assert.equal(check.ok, false); return check.errors.join("\n"); };

test("initial form: defaults shown, seed empty, nothing chosen, acknowledgements unchecked", () => {
  const initial = lib.initialDockingForm();
  assert.deepEqual(plain(initial), {
    receptorHandle: null, receptorModelNumber: null, connectivity: null, sidecarHandle: null, instance: { kind: "unset" },
    ligandSource: null, sdfHandle: null, candidateSetHandle: null, candidateId: null, parentSdfHandle: null, mode: null,
    boxSource: null, margin: "8", center: ["", "", ""], size: ["", "", ""], seed: "", exhaustiveness: "8",
    numModes: "9", energyRange: "3", conformers: "50",
    acknowledgement: { keep_input_protonation: false, tool_assigned_types_charges: false, rigid_no_optimization: false } });
  assert.equal(lib.dockingArgs(initial).ok, false);
});

test("free docking with an SDF and a ligand-range box builds the exact server shape without conformers", () => {
  const check = lib.dockingArgs(form({ conformers: "not a number" }));
  assert.equal(check.ok, true);
  assert.deepEqual(plain(check.args), {
    receptor_handle: "obj://r/chemical_raw_input/rec", receptor_model_number: 1,
    connectivity: { kind: "pdb_conect", sidecar_handle: null }, receptor_instance: null,
    ligand: { source: "sdf", sdf_handle: "obj://r/chemical_raw_input/lig" }, mode: "free",
    box: { source: "ligand_range", margin_A: 8 },
    parameters: { seed: 7, exhaustiveness: 8, num_modes: 9, energy_range: 3 },
    acknowledgement: ACK_ALL });
  assert.ok(!("conformers" in check.args.parameters));
  assert.deepEqual(Object.keys(check.args), ["receptor_handle", "receptor_model_number", "connectivity",
    "receptor_instance", "ligand", "mode", "box", "parameters", "acknowledgement"]);
});

test("core-fixed candidate with an instance, sidecar and instance-range box", () => {
  const check = lib.dockingArgs(form({ connectivity: "sidecar", sidecarHandle: "obj://r/chemical_raw_input/bonds",
    instance: { kind: "instance", residue: { ...LIGAND_RES, label: "x" } }, ligandSource: "candidate", sdfHandle: null,
    candidateSetHandle: "obj://r/ligand_candidate_set/s", candidateId: "c_0001",
    parentSdfHandle: "obj://r/chemical_raw_input/p", mode: "core_fixed", boxSource: "instance_range", margin: " 4.5 ",
    seed: "2147483647", exhaustiveness: "32", numModes: "20", energyRange: "1.5", conformers: "200" }));
  assert.equal(check.ok, true);
  assert.deepEqual(plain(check.args), {
    receptor_handle: "obj://r/chemical_raw_input/rec", receptor_model_number: 1,
    connectivity: { kind: "sidecar", sidecar_handle: "obj://r/chemical_raw_input/bonds" }, receptor_instance: LIGAND_RES,
    ligand: { source: "candidate", candidate_set_handle: "obj://r/ligand_candidate_set/s", candidate_id: "c_0001",
      parent_sdf_handle: "obj://r/chemical_raw_input/p" }, mode: "core_fixed",
    box: { source: "instance_range", margin_A: 4.5 },
    parameters: { seed: 2147483647, exhaustiveness: 32, num_modes: 20, energy_range: 1.5, conformers: 200 },
    acknowledgement: ACK_ALL });
  assert.deepEqual(Object.keys(check.args.receptor_instance),
    ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"]);
});

test("manual box: finite centre, sides 8-40 A; above 40 is box_too_large (never shrunk)", () => {
  const ok = lib.dockingArgs(form({ boxSource: "manual", center: ["-12.5", "0", "1e2"], size: ["8", "40", "22.25"] }));
  assert.equal(ok.ok, true);
  assert.deepEqual(plain(ok.args.box), { source: "manual", center_A: [-12.5, 0, 100], size_A: [8, 40, 22.25] });
  assert.ok(!("margin_A" in ok.args.box));
  const negativeZero = lib.dockingArgs(form({ boxSource: "manual", center: ["-0", "0", "0"], size: ["10", "10", "10"] }));
  assert.ok(Object.is(negativeZero.args.box.center_A[0], 0));
  assert.match(errorsOf(lib.dockingArgs(form({ boxSource: "manual", center: ["0", "0", "0"],
    size: ["40.01", "10", "10"] }))), /상자 크기 x.*\(box_too_large\)/);
  assert.match(errorsOf(lib.dockingArgs(form({ boxSource: "manual", center: ["0", "0", "0"],
    size: ["10", "7.99", "10"] }))), /상자 크기 y.*\(box_invalid\)/);
  for (const bad of ["", "abc", "Infinity", "NaN", "1e400", "0x10", "1,5", "100001"]) {
    assert.match(errorsOf(lib.dockingArgs(form({ boxSource: "manual", center: ["0", "0", bad],
      size: ["10", "10", "10"] }))), /상자 중심 z.*\(box_invalid\)/, bad);
  }
  assert.match(errorsOf(lib.dockingArgs(form({ boxSource: "manual", center: ["0", "0", "0"],
    size: ["10", "10", "1e400"] }))), /상자 크기 z.*\(box_invalid\)/);
});

test("box source and margin checks: instance range needs an instance, margin 0-20", () => {
  assert.equal(lib.dockingArgs(form({ margin: "0" })).args.box.margin_A, 0);
  assert.equal(lib.dockingArgs(form({ margin: "20" })).args.box.margin_A, 20);
  for (const bad of ["20.5", "-1", "", "x"])
    assert.match(errorsOf(lib.dockingArgs(form({ margin: bad }))), /상자 여백.*\(box_invalid\)/, bad);
  assert.match(errorsOf(lib.dockingArgs(form({ boxSource: "instance_range", instance: { kind: "none" } }))),
    /인스턴스를 골랐을 때만.*\(box_invalid\)/);
  assert.match(errorsOf(lib.dockingArgs(form({ boxSource: null }))), /상자 출처를 고르세요/);
});

test("value checks: seed required integer 0-2147483647, exhaustiveness 1-32, num_modes 1-20, energy_range 1-5", () => {
  assert.equal(lib.dockingArgs(form({ seed: "0" })).args.parameters.seed, 0);
  for (const seed of ["", "-1", "2147483648", "1.5", "1e3", "07", "abc"])
    assert.match(errorsOf(lib.dockingArgs(form({ seed }))), /seed: 0–2147483647 사이의 정수/, seed);
  for (const value of ["0", "33", "8.0"])
    assert.match(errorsOf(lib.dockingArgs(form({ exhaustiveness: value }))), /exhaustiveness: 1–32/, value);
  for (const value of ["0", "21"])
    assert.match(errorsOf(lib.dockingArgs(form({ numModes: value }))), /num_modes: 1–20/, value);
  for (const value of ["0.99", "5.01", "", "Infinity"])
    assert.match(errorsOf(lib.dockingArgs(form({ energyRange: value }))), /energy_range: 1–5/, value);
  assert.equal(lib.dockingArgs(form({ energyRange: "5" })).args.parameters.energy_range, 5);
  const core = { ligandSource: "candidate", candidateSetHandle: "s", candidateId: "c", parentSdfHandle: "p",
    mode: "core_fixed" };
  for (const value of ["0", "201", "", "1.5"])
    assert.match(errorsOf(lib.dockingArgs(form({ ...core, conformers: value }))), /conformers: 1–200/, value);
  assert.equal(lib.dockingArgs(form({ ...core, conformers: "1" })).args.parameters.conformers, 1);
});

test("selection checks: mode/source mismatch, missing handles, unset instance, acknowledgements", () => {
  assert.match(errorsOf(lib.dockingArgs(form({ mode: "core_fixed" }))), /\(mode_source_mismatch\)/);
  assert.match(errorsOf(lib.dockingArgs(form({ instance: { kind: "unset" } }))), /없음\(단백질만\)/);
  assert.match(errorsOf(lib.dockingArgs(form({ connectivity: "sidecar", sidecarHandle: null }))), /결합 사이드카/);
  assert.match(errorsOf(lib.dockingArgs(form({ connectivity: null }))), /연결 정보/);
  assert.match(errorsOf(lib.dockingArgs(form({ receptorHandle: null }))), /수용체 가져오기/);
  assert.match(errorsOf(lib.dockingArgs(form({ receptorModelNumber: null }))), /모델 번호/);
  assert.match(errorsOf(lib.dockingArgs(form({ sdfHandle: null }))), /3D SDF/);
  assert.match(errorsOf(lib.dockingArgs(form({ ligandSource: "candidate", sdfHandle: null }))),
    /후보 집합을 고르세요[\s\S]*후보를 고르세요[\s\S]*부모 3D SDF/);
  assert.match(errorsOf(lib.dockingArgs(form({ mode: null }))), /방식/);
  for (const key of ["keep_input_protonation", "tool_assigned_types_charges", "rigid_no_optimization"]) {
    const ack = { ...ACK_ALL, [key]: false };
    assert.equal(lib.acknowledgementComplete(ack), false);
    assert.match(errorsOf(lib.dockingArgs(form({ acknowledgement: ack }))), /\(acknowledgement_missing\)/);
  }
  assert.equal(lib.acknowledgementComplete(ACK_ALL), true);
  assert.deepEqual(Object.keys(lib.ACKNOWLEDGEMENT_LABEL), [...lib.ACKNOWLEDGEMENT_KEYS]);
});

// ---- jobs ----

test("submission is blocked while unavailable, busy, another job is active, or the inputs are incomplete", () => {
  const okCheck = lib.dockingArgs(form());
  assert.equal(lib.dockingSubmitBlockedReason({ capability: READY_CAP, busy: false, activeJob: null, check: okCheck }), null);
  assert.equal(lib.dockingSubmitBlockedReason({ capability: READY_CAP, busy: false, activeJob: { status: "done" },
    check: okCheck }), null);
  assert.match(lib.dockingSubmitBlockedReason({ capability: { available: false, reason: "없음",
    reason_code: "worker_missing" }, busy: false, activeJob: null, check: okCheck }), /\(worker_missing\)/);
  assert.ok(lib.dockingSubmitBlockedReason({ capability: undefined, busy: false, activeJob: null, check: okCheck }));
  assert.ok(lib.dockingSubmitBlockedReason({ capability: READY_CAP, busy: true, activeJob: null, check: okCheck }));
  for (const status of ["queued", "claimed", "running"])
    assert.match(lib.dockingSubmitBlockedReason({ capability: READY_CAP, busy: false, activeJob: { status },
      check: okCheck }), /한 번에 한 작업/);
  assert.match(lib.dockingSubmitBlockedReason({ capability: READY_CAP, busy: false, activeJob: null,
    check: lib.dockingArgs(form({ seed: "" })) }), /seed/);
});

test("job phases, texts, approval and idempotent submission", () => {
  assert.equal(lib.dockingJobPhase(null, false), "none");
  assert.equal(lib.dockingJobPhase({ status: "queued" }, false), "saved");
  assert.equal(lib.dockingJobPhase({ status: "queued" }, true), "awaiting_approval");
  assert.equal(lib.dockingJobPhase({ status: "running" }, false), "running");
  assert.equal(lib.dockingJobPhase({ status: "done" }, true), "done");
  assert.equal(lib.dockingJobPhase({ status: "cancelled" }, false), "cancelled");
  assert.equal(lib.dockingJobPhase({ status: "interrupted" }, false), "failed");
  assert.match(lib.dockingJobText({ status: "running", cancel_requested: true, failure: null }, false), /취소 요청됨/);
  assert.match(lib.dockingJobText({ status: "failed", cancel_requested: false,
    failure: { error: "input_invalid", message: "m", reason_code: "embed_failed" } }, false), /\(embed_failed\) · m$/);
  assert.match(lib.dockingJobText({ status: "weird", cancel_requested: false, failure: null }, false), /weird/);
  assert.ok(lib.dockingApprovalRequired(409, { gate: "expensive_first_call", tool: "qvina_dock_ligand" }));
  assert.ok(!lib.dockingApprovalRequired(409, { gate: "expensive_first_call", tool: "rdkit_enumerate_ligands" }));
  assert.ok(!lib.dockingApprovalRequired(422, { gate: "expensive_first_call", tool: "qvina_dock_ligand" }));
  assert.ok(!lib.dockingApprovalRequired(409, undefined));
  assert.match(lib.dockingSubmitText({ plan_only: true }), /계획만/);
  assert.match(lib.dockingSubmitText({ job_id: "j", status: "queued" }), /저장되었습니다/);
  assert.match(lib.dockingSubmitText({ job_id: "j", status: "done" }), /새 작업을 만들지 않았습니다/);
});

// ---- late responses ----

test("late responses: run, selection key and sequence must all be current", () => {
  const key = lib.dockingInputKey(form());
  const stamp = { runId: "r1", key, seq: 4 };
  assert.ok(lib.dockingResponseCurrent(stamp, { ...stamp }));
  assert.ok(!lib.dockingResponseCurrent(stamp, { ...stamp, runId: "r2" }));
  assert.ok(!lib.dockingResponseCurrent(stamp, { ...stamp, seq: 5 }));
  assert.ok(!lib.dockingResponseCurrent(stamp, { ...stamp, key: lib.dockingInputKey(form({ sdfHandle: "other" })) }));
  assert.ok(!lib.dockingResponseCurrent({ ...stamp, runId: null }, { ...stamp, runId: null }));
  assert.notEqual(lib.dockingInputKey(form({ instance: { kind: "none" } })),
    lib.dockingInputKey(form({ instance: { kind: "unset" } })));
  assert.notEqual(lib.dockingInputKey(form({ instance: { kind: "instance", residue: LIGAND_RES } })),
    lib.dockingInputKey(form({ instance: { kind: "instance", residue: { ...LIGAND_RES, chain_label: "C" } } })));
  // Values (seed etc.) are not part of the input selection key.
  assert.equal(lib.dockingInputKey(form({ seed: "1" })), lib.dockingInputKey(form({ seed: "2" })));
});

// ---- display ----

test("rounding is ROUND_HALF_UP on the decimal string (never toFixed)", () => {
  assert.equal(lib.scoreText(-7.25), "-7.3");
  assert.equal(lib.scoreText(-7.35), "-7.4");
  assert.equal(lib.scoreText(-5.05), "-5.1");
  assert.notEqual((-5.05).toFixed(1), "-5.1");   // binary float rounding would show -5.0 or similar
  assert.equal(lib.scoreText(-9), "-9.0");
  assert.equal(lib.scoreText(-0.04), "0.0");     // backend render_score shows a zero without a sign
  assert.equal(lib.scoreText(1e-7), "0.0");
  assert.equal(lib.distanceText(2.675), "2.68 Å");
  assert.notEqual((2.675).toFixed(2), "2.68");
  assert.equal(lib.distanceText(3), "3.00 Å");
  assert.equal(lib.distanceText(1.004999), "1.00 Å");
  assert.equal(lib.optionalDistanceText(null), "해당 없음");
  assert.equal(lib.optionalDistanceText(0), "0.00 Å");
  assert.equal(lib.countText(0), "0");
  assert.equal(lib.boxText({ center_A: [1.005, -2, 3.333], size_A: [20, 22.5, 8], source: "ligand_range",
    margin_A: 8 }), "중심 (1.01, -2.00, 3.33) Å · 크기 (20.00, 22.50, 8.00) Å · 리간드 범위+여백 · 여백 8.00 Å");
  assert.equal(lib.boxText({ center_A: [0, 0, 0], size_A: [10, 10, 10], source: "manual", margin_A: null }),
    "중심 (0.00, 0.00, 0.00) Å · 크기 (10.00, 10.00, 10.00) Å · 직접 입력");
});

test("row names: free 'mode n (engine output order)', core-fixed 'sample n (ascending score listing)'", () => {
  assert.equal(lib.modeRowLabel("free", 1), "모드 1(엔진 출력 순서)");
  assert.equal(lib.modeRowLabel("core_fixed", 3), "샘플 3(점수 오름차순 나열)");
  assert.equal(lib.modeColumnLabel("free"), "모드");
  assert.equal(lib.modeColumnLabel("core_fixed"), "샘플");
  assert.equal(lib.contactKindText("polar_contact"), "극성 접촉(polar_contact)");
  assert.equal(lib.ligandAtomText({ ligand_serial: 5, ligand_element: "N", ligand_parent_serial: null }),
    "포즈 SDF 5 · N");
  assert.equal(lib.ligandAtomText({ ligand_serial: 5, ligand_element: "N", ligand_parent_serial: 9 }),
    "포즈 SDF 5 · N · 부모 SDF 9");
  assert.equal(lib.receptorAtomText({ residue: { ...LIGAND_RES, resname: "ASP", seq_auth: 86 }, atom_name: "OD1",
    altloc: "", element: "O", site_index: 1203 }), "모델 1 · 체인 A · ASP 86 · OD1 · O · site 1203");
  assert.equal(lib.generatedText({ hydrogens: true, coordinates: true }),
    "수소: RDKit이 만든 것(생성됨) · 3D 좌표: RDKit이 만든 것(생성됨)");
  assert.equal(lib.generatedText({ hydrogens: false, coordinates: false }), "수소: 입력 그대로 · 3D 좌표: 입력 그대로");
  assert.equal(lib.removedInstanceText(null), "뺀 인스턴스 없음(단백질만)");
  assert.equal(lib.removedInstanceText({ residue: LIGAND_RES, atom_count: 3, element_counts: { C: 2, O: 1 } }),
    "모델 1 · 체인 A · XYZ 300 · 원자 3개(C 2, O 1)");
});

test("forbidden wording: rank/best/optimal/improvement/affinity claims are found; fixed sentences are exempt", () => {
  for (const [text, word] of [["모드 1 순위", "순위"], ["best pose", "best"], ["최적 모드", "최적"], ["점수 개선", "개선"],
    ["결합 강도가 큼", "결합 강도"], ["친화도 -7", "친화"], ["Rank 1", "Rank"], ["optimal", "optimal"],
    ["improved score", "improv"], ["stronger", "stronger"], ["affinity", "affinity"], ["최고 점수", "최고"],
    ["ΔΔG", "ΔΔG"], ["합성 가능", "합성 가능"]])
    assert.deepEqual(plain(lib.dockingForbiddenWords(text)), [word], text);
  assert.deepEqual(plain(lib.dockingForbiddenWords(lib.SCORE_LABEL)), []);
  assert.deepEqual(plain(lib.dockingForbiddenWords(`${lib.SCORE_COLUMN_LABEL}\n${lib.SCORE_LABEL}: -7.3`)), []);
  // The score name is removed, the rest of the line is still checked.
  assert.deepEqual(plain(lib.dockingForbiddenWords(`${lib.SCORE_LABEL} best`)), ["best"]);
  for (const sentence of lib.DOCKING_LIMITATIONS) assert.deepEqual(plain(lib.dockingForbiddenWords(sentence)), []);
  // Exempt only when the whole line equals a limitation sentence.
  assert.deepEqual(plain(lib.dockingForbiddenWords(`${lib.DOCKING_LIMITATIONS[0]} 순위`)), ["친화", "순위"]);
  // "최적화" (optimization, a process) is not a claim of optimality.
  assert.deepEqual(plain(lib.dockingForbiddenWords("구조는 최적화하지 않았습니다")), []);
  assert.deepEqual(plain(lib.dockingForbiddenWords("abest, ranking-free")), ["rank"]);
});

test("every fixed screen string of this module passes the wording check", () => {
  const texts = [
    ...Object.values(lib.DOCKING_REASON_LABEL), ...Object.values(lib.ACKNOWLEDGEMENT_LABEL),
    ...Object.values(lib.MODE_LABEL), lib.BOX_FRAME_NOTE, lib.CONTACT_NOTE, lib.NO_RUN_REASON, lib.RESOURCE_EXCEEDED_HINT,
    lib.nullResultText("free"), lib.nullResultText("core_fixed"), lib.modeRowLabel("free", 1),
    lib.modeRowLabel("core_fixed", 1), ...["ligand_range", "instance_range", "manual"].map(lib.boxSourceLabel),
    ...[null, { status: "queued" }, { status: "running" }, { status: "done" }, { status: "cancelled" },
      { status: "failed" }].map(job => lib.dockingJobText(job && { ...job, cancel_requested: false, failure: null },
      false)),
    lib.dockingJobText({ status: "queued", cancel_requested: false, failure: null }, true),
    lib.dockingSubmitText({ plan_only: true }), lib.dockingCapabilityText(null),
    ...plain(lib.dockingArgs(lib.initialDockingForm())).errors,
  ];
  for (const text of texts) assert.deepEqual(plain(lib.dockingForbiddenWords(text)), [], text);
});

// ---- screen wiring (T9) ----

test("form edits clear the choices they invalidate and never choose anything in their place", () => {
  const base = form({ connectivity: "sidecar", sidecarHandle: "obj://r/chemical_raw_input/b",
    instance: { kind: "instance", residue: LIGAND_RES }, boxSource: "instance_range", ligandSource: "candidate",
    sdfHandle: null, candidateSetHandle: "obj://r/ligand_candidate_set/s", candidateId: "c_1",
    parentSdfHandle: "obj://r/chemical_raw_input/p", mode: "core_fixed" });
  // New receptor: model and instance cleared; the instance range box is dropped with the instance.
  const receptor = lib.patchDockingForm(base, { receptorHandle: "obj://r/chemical_raw_input/other" });
  assert.equal(receptor.receptorModelNumber, null);
  assert.deepEqual(plain(receptor.instance), { kind: "unset" });
  assert.equal(receptor.boxSource, null);
  // Same receptor again changes nothing.
  assert.deepEqual(plain(lib.patchDockingForm(base, { receptorHandle: base.receptorHandle })), plain(base));
  // New model: instance cleared.
  assert.deepEqual(plain(lib.patchDockingForm(base, { receptorModelNumber: 2 }).instance), { kind: "unset" });
  // "None" also drops the instance range box; other box sources stay.
  assert.equal(lib.patchDockingForm(base, { instance: { kind: "none" } }).boxSource, null);
  assert.equal(lib.patchDockingForm({ ...base, boxSource: "manual" }, { instance: { kind: "none" } }).boxSource, "manual");
  // New candidate set: candidate and parent SDF cleared.
  const set = lib.patchDockingForm(base, { candidateSetHandle: "obj://r/ligand_candidate_set/t" });
  assert.equal(set.candidateId, null);
  assert.equal(set.parentSdfHandle, null);
  // SDF source: core-fixed dropped (never switched to free automatically).
  const sdf = lib.patchDockingForm(base, { ligandSource: "sdf" });
  assert.equal(sdf.mode, null);
  assert.equal(lib.patchDockingForm({ ...base, mode: "free" }, { ligandSource: "sdf" }).mode, "free");
  // Leaving the sidecar clears its handle.
  assert.equal(lib.patchDockingForm(base, { connectivity: "pdb_conect" }).sidecarHandle, null);
  // Core-fixed cannot be set without the candidate source; instance range cannot be set without an instance.
  assert.equal(lib.patchDockingForm(sdf, { mode: "core_fixed" }).mode, null);
  assert.equal(lib.patchDockingForm(receptor, { boxSource: "instance_range" }).boxSource, null);
  // The input is not mutated.
  assert.equal(base.mode, "core_fixed");
  // A complete form stays complete through unrelated edits.
  assert.equal(lib.dockingArgs(lib.patchDockingForm(form(), { seed: "11" })).ok, true);
});

test("re-attaching to this run's active docking job; imports by kind; parent SDF reason", () => {
  const jobs = [
    { job_id: "a", run_id: "r", protocol_id: "qvina_dock_v1", status: "done" },
    { job_id: "b", run_id: "r", protocol_id: "rdkit_enumerate_v1", status: "running" },
    { job_id: "c", run_id: "other", protocol_id: "qvina_dock_v1", status: "running" },
    { job_id: "d", run_id: "r", protocol_id: "qvina_dock_v1", status: "queued" },
    { job_id: "e", run_id: "r", protocol_id: "qvina_dock_v1", status: "running" },
  ];
  assert.equal(lib.dockingActiveJob(jobs, "r").job_id, "e");
  assert.equal(lib.dockingActiveJob(jobs.slice(0, 3), "r"), null);
  assert.equal(lib.dockingActiveJob({ not: "a list" }, "r"), null);
  assert.ok(lib.dockingJobActive({ status: "claimed" }));
  assert.ok(!lib.dockingJobActive({ status: "done" }));
  assert.ok(!lib.dockingJobActive(null));
  const imports = [{ handle: "1", input_kind: "receptor" }, { handle: "2", input_kind: "ligand_sdf" },
    { handle: "3", input_kind: "receptor" }];
  assert.deepEqual(plain(lib.importsOfKind(imports, "receptor").map(row => row.handle)), ["1", "3"]);
  assert.match(lib.parentSdfMissingReason(null), /후보 집합/);
  assert.match(lib.parentSdfMissingReason({ valid: false, parent_sdf_handles: null }), /\(evidence_invalid\)/);
  assert.match(lib.parentSdfMissingReason({ valid: true, parent_sdf_handles: [] }), /부모 3D SDF를 가져오세요/);
  assert.equal(lib.parentSdfMissingReason({ valid: true, parent_sdf_handles: ["h"] }), null);
  assert.equal(lib.stereoFlagText(null), "해당 없음(SDF 출처)");
  assert.equal(lib.stereoFlagText("new_unspecified_center"), "새로 생긴 미지정 입체 중심 (new_unspecified_center)");
  assert.equal(lib.stereoFlagText("unknown_flag"), "unknown_flag");
});

function resultFixture(mode, overrides = {}) {
  const core = mode === "core_fixed";
  return {
    method: core ? "qvina_core_fixed_score_only_v1" : "qvina_free_v1",
    inputs: {
      receptor: { handle: "obj://r/chemical_raw_input/rec", sha256: "a".repeat(64), model_number: 1,
        connectivity: { kind: "pdb_conect", sidecar_handle: null },
        removed_instance: { residue: LIGAND_RES, atom_count: 3, element_counts: { C: 2, O: 1 } },
        acknowledgement: ACK_ALL },
      ligand: core ? { source: "candidate", sdf_handle: null, sdf_sha256: null,
        candidate_set_handle: "obj://r/ligand_candidate_set/s", candidate_id: "c_0001",
        parent_sdf_handle: "obj://r/chemical_raw_input/p", parent_sdf_sha256: "b".repeat(64),
        generated: { hydrogens: true, coordinates: true }, stereo_flag: "none", unspecified_stereo_centers: 0 }
        : { source: "sdf", sdf_handle: "obj://r/chemical_raw_input/lig", sdf_sha256: "c".repeat(64),
          candidate_set_handle: null, candidate_id: null, parent_sdf_handle: null, parent_sdf_sha256: null,
          generated: { hydrogens: false, coordinates: false }, stereo_flag: null, unspecified_stereo_centers: null },
      mode },
    box: { center_A: [1.005, 2, 3], size_A: [20, 20, 20], source: "instance_range", margin_A: 8 },
    parameters: { seed: 7, exhaustiveness: 8, num_modes: 9, energy_range: 3, conformers: core ? 50 : null, cpu: 1 },
    engine: { name: "qvina", version: "2.1.0", binary_sha256: "d".repeat(64), package: "conda-forge qvina 2.1.0" },
    preparation: { tool: "Meeko", version: "0.8.0", rdkit_version: "2026.03.6", atom_typing: "AD4", charges: "gasteiger" },
    counts: { modes: 2, contacts_by_mode: [3, 0], null_result: false, samples_generated: core ? 50 : null,
      samples_scored: core ? 50 : null },
    limitations: [],
    ...overrides,
  };
}
const MODE_ROW = { mode: 1, score_kcal_mol: -7.25, contact_count: 3, min_heavy_atom_distance_A: 2.675,
  atoms_outside_box: 0, engine_rmsd_lb_A: 0, engine_rmsd_ub_A: 0, conformer_index: null, core_max_deviation_A: null };

test("result summary shows stored fields: engine, seed, values, box, receptor hash, removed instance, generated flags", () => {
  const free = new Map(plain(lib.dockingSummaryRows(resultFixture("free"))));
  assert.equal(free.get("점수"), lib.SCORE_LABEL);
  assert.equal(free.get("seed"), "7");
  assert.match(free.get("엔진"), /^qvina 2\.1\.0 · conda-forge qvina 2\.1\.0 · 실행 파일 SHA-256 d{64}$/);
  assert.equal(free.get("값"), "exhaustiveness 8 · num_modes 9 · energy_range 3.00 kcal/mol · cpu 1");
  assert.equal(free.get("상자"), "중심 (1.01, 2.00, 3.00) Å · 크기 (20.00, 20.00, 20.00) Å · 수용체 안 인스턴스 범위+여백 · 여백 8.00 Å");
  assert.match(free.get("수용체"), new RegExp(`SHA-256 ${"a".repeat(64)} · 모델 1 · 연결 정보 PDB CONECT$`));
  assert.equal(free.get("뺀 인스턴스"), "모델 1 · 체인 A · XYZ 300 · 원자 3개(C 2, O 1)");
  assert.equal(free.get("생성 여부"), "수소: 입력 그대로 · 3D 좌표: 입력 그대로");
  assert.equal(free.get("후보 stereo_flag"), "해당 없음(SDF 출처)");
  assert.equal(free.get("미지정 입체 중심 수"), "해당 없음(SDF 출처)");
  assert.equal(free.get("모드 수"), "2");
  assert.ok(!free.has("만든 형태 · 점수를 매긴 형태"));
  const core = new Map(plain(lib.dockingSummaryRows(resultFixture("core_fixed"))));
  assert.match(core.get("리간드 출처"), /^M17 후보 c_0001 · .* · 부모 SHA-256 b{64}$/);
  assert.equal(core.get("생성 여부"), "수소: RDKit이 만든 것(생성됨) · 3D 좌표: RDKit이 만든 것(생성됨)");
  assert.equal(core.get("후보 stereo_flag"), "입체 표시 없음 (none)");
  // 0 unspecified centres is a stored count, shown as 0 (not "not applicable").
  assert.equal(core.get("미지정 입체 중심 수"), "0");
  assert.equal(core.get("샘플 수"), "2");
  assert.equal(core.get("만든 형태 · 점수를 매긴 형태"), "50 · 50");
  assert.match(core.get("값"), /conformers 50$/);
});

test("mode table: free 'mode n' with engine RMSD, core-fixed 'sample n' with core deviation; stored values rounded", () => {
  assert.deepEqual(plain(lib.modeTableHeaders("free")), ["모드", "qvina 점수(kcal/mol)", "접촉 수(기하)", "최소 중원자 거리",
    "상자 밖 중원자 수", "엔진 RMSD 하한·상한(모드 1 기준)"]);
  assert.deepEqual(plain(lib.modeTableHeaders("core_fixed")).slice(-2), ["코어 최대 이탈", "형태 번호"]);
  assert.deepEqual(plain(lib.modeTableCells("free", MODE_ROW)),
    ["모드 1(엔진 출력 순서)", "-7.3", "3", "2.68 Å", "0", "0.00 Å · 0.00 Å"]);
  assert.deepEqual(plain(lib.modeTableCells("free", { ...MODE_ROW, mode: 2, engine_rmsd_lb_A: null, engine_rmsd_ub_A: null })).at(-1),
    "해당 없음");
  assert.deepEqual(plain(lib.modeTableCells("core_fixed", { ...MODE_ROW, engine_rmsd_lb_A: null, engine_rmsd_ub_A: null,
    conformer_index: 0, core_max_deviation_A: 0.004, atoms_outside_box: 2, contact_count: 0 })),
  ["샘플 1(점수 오름차순 나열)", "-7.3", "0", "2.68 Å", "2", "0.00 Å", "0"]);
  assert.equal(lib.modeTableHeaders("free").length, lib.modeTableCells("free", MODE_ROW).length);
  assert.equal(lib.modeTableHeaders("core_fixed").length, lib.modeTableCells("core_fixed", MODE_ROW).length);
});

test("contact page text, result list rows and report check", () => {
  assert.match(lib.contactPageText({ total: 0, offset: 0, rows: [] }), /0개/);
  assert.equal(lib.contactPageText({ total: 250, offset: 100, rows: new Array(100) }), "기하 접촉 250개 중 101–200");
  const row = { created_seq: 12, valid: true, reason_code: null, mode: "free", ligand_source: "sdf", candidate_id: null,
    seed: 7, box_source: "manual", modes: 9, null_result: false };
  assert.equal(lib.dockingResultRowText(row), "생성 순번 12 · 자유 도킹 · 3D SDF · seed 7 · 직접 입력 · 모드 9개");
  assert.match(lib.dockingResultRowText({ ...row, mode: "core_fixed", ligand_source: "candidate", candidate_id: "c_1",
    modes: 0, null_result: true }), /후보 c_1 .* 샘플 0개 \(빈 과학 결과\)$/);
  assert.match(lib.dockingResultRowText({ ...row, valid: false, reason_code: null }), /읽을 수 없음: .*\(evidence_invalid\)$/);
  const artifact = { manifest: { schema: "method_report_manifest@1", analysis_type: "ligand_docking", result_handle: "h" } };
  assert.ok(lib.dockingReportMatches(artifact, "h"));
  assert.ok(!lib.dockingReportMatches(artifact, "other"));
  assert.ok(!lib.dockingReportMatches({ manifest: { ...artifact.manifest, analysis_type: "ligand_candidates" } }, "h"));
});

test("screen wording: generated texts and every line of DockingPanel.tsx pass the forbidden-word check", () => {
  const texts = [
    ...lib.dockingSummaryRows(resultFixture("free")).flat(), ...lib.dockingSummaryRows(resultFixture("core_fixed")).flat(),
    ...lib.modeTableHeaders("free"), ...lib.modeTableHeaders("core_fixed"), ...lib.modeTableCells("free", MODE_ROW),
    ...Object.values(lib.DOCKING_STATE_TEXT), lib.contactPageText({ total: 0, offset: 0, rows: [] }),
    lib.parentSdfMissingReason({ valid: true, parent_sdf_handles: [] }),
  ];
  for (const text of texts) assert.deepEqual(plain(lib.dockingForbiddenWords(text)), [], text);
  const source = fs.readFileSync(path.join(__dirname, "../src/components/DockingPanel.tsx"), "utf8");
  assert.deepEqual(plain(lib.dockingForbiddenWords(source)), []);
  // The panel shows no timeout (fixed 600 s, not on screen) and renders no HTML string.
  assert.ok(!/timeout_s|dangerouslySetInnerHTML|innerHTML/.test(source));
});

// ---- api.ts calls (fetch replaced; nothing leaves the process) ----

test("api: docking submission sends the fixed protocol and timeout; reads and download URLs use the docking routes", async () => {
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url, init });
    return { ok: true, json: async () => ({}) };
  };
  const { api, DOCKING_TIMEOUT_S } = load("api", {}, { fetch });
  assert.equal(DOCKING_TIMEOUT_S, 600);
  const args = lib.dockingArgs(form()).args;
  await api.submitDocking("run 1", args);
  assert.equal(calls[0].url, "/api/runs/run%201/jobs");
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].init.body), { protocol_id: "qvina_dock_v1", args: plain(args), timeout_s: 600 });
  await api.dockingPrerequisites("r");
  await api.dockingReceptorInstances("r", "obj://r/chemical_raw_input/a b");
  await api.dockingResults("r", 0, 100);
  await api.dockingResult("r", "obj://r/docking_result/x");
  await api.dockingContacts("r", "obj://r/docking_result/x", 2, 100, 100);
  await api.createDockingReport("r", "obj://r/docking_result/x");
  await api.dockingJob("r", "job/1");
  assert.deepEqual(calls.slice(1).map(call => call.url), [
    "/api/runs/r/docking/prerequisites",
    "/api/runs/r/docking/receptor_instances?handle=obj%3A%2F%2Fr%2Fchemical_raw_input%2Fa%20b",
    "/api/runs/r/docking/results?offset=0&limit=100",
    "/api/runs/r/docking/results/detail?handle=obj%3A%2F%2Fr%2Fdocking_result%2Fx",
    "/api/runs/r/docking/results/contacts?handle=obj%3A%2F%2Fr%2Fdocking_result%2Fx&mode=2&offset=100&limit=100",
    "/api/runs/r/method_reports",
    "/api/runs/r/jobs/job%2F1",
  ]);
  assert.deepEqual(JSON.parse(calls[6].init.body), { result_handle: "obj://r/docking_result/x" });
  assert.equal(api.dockingPoseSdfUrl("r", "obj://r/docking_result/x", 3),
    "/api/runs/r/docking/results/pose_sdf?handle=obj%3A%2F%2Fr%2Fdocking_result%2Fx&mode=3");
  assert.equal(api.dockingPosesSdfUrl("r", "obj://r/docking_result/x"),
    "/api/runs/r/docking/results/poses_sdf?handle=obj%3A%2F%2Fr%2Fdocking_result%2Fx");
});
