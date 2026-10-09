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
const mutationModel = load("mutation-model", { "./site-annotation": siteAnnotation, "./docking": docking });
const lib = load("sequence-ga", { "./docking": docking, "./mutation-model": mutationModel,
  "./site-annotation": siteAnnotation });
const reportLibrary = load("report-library");
const plain = value => JSON.parse(JSON.stringify(value));
const LIB_SOURCE = fs.readFileSync(path.join(__dirname, "../src/lib/sequence-ga.ts"), "utf8");

// ---- closed sets, ranges, limits and fixed wording are read from backend/mw/sequence_ga_constants.py itself ----
const constantsSource = fs.readFileSync(path.join(__dirname, "../../backend/mw/sequence_ga_constants.py"), "utf8");
const reportsSource = fs.readFileSync(path.join(__dirname, "../../backend/mw/sequence_ga_reports.py"), "utf8");
function pyTuple(name, source = constantsSource) {
  const match = new RegExp(`^${name} = \\(([^)]*)\\)`, "m").exec(source);
  assert.ok(match, `backend constant ${name} not found`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map(item => item[1]);
}
function pyNumber(name) {
  const match = new RegExp(`^${name} = ([0-9_]+)\\b`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return Number(match[1].replace(/_/g, ""));
}
function pyString(name, source = constantsSource) {
  const match = new RegExp(`^${name} = "([^"]+)"`, "m").exec(source);
  assert.ok(match, `backend constant ${name} not found`);
  return match[1];
}
/** A parenthesized string concatenation `NAME = ("a" "b")`. */
function pyJoined(name) {
  const match = new RegExp(`^${name} = \\(([\\s\\S]*?)\\)\\n`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return [...match[1].matchAll(/"([^"]*)"/g)].map(item => item[1]).join("");
}
function pyBlock(name) {
  const start = constantsSource.indexOf(`\n${name} = {`);
  assert.ok(start >= 0, `backend constant ${name} not found`);
  return constantsSource.slice(start + name.length + 5, constantsSource.indexOf("\n}", start));
}
function pyStringDict(name) {
  const block = pyBlock(name).replace(/"\s*\n\s*"/g, "");
  return Object.fromEntries([...block.matchAll(/"([^"]+)":\s*"([^"]+)"/g)].map(item => [item[1], item[2]]));
}
function pyRanges() {
  return Object.fromEntries([...pyBlock("GA_RANGES").matchAll(/"([a-z_]+)":\s*\(([^)]*)\)/g)].map(item => [item[1],
    item[2].split(",").map(text => text.trim()).map(text => text === "None" ? null : Number(text))]));
}
/** ADMISSION_STEPS flattened (LIGAND_BOX_REASONS expanded in place). */
function pyAdmissionReasons() {
  const start = constantsSource.indexOf("\nADMISSION_STEPS = (");
  assert.ok(start >= 0);
  const block = constantsSource.slice(start, constantsSource.indexOf("\n)\n", start));
  const ligandBox = pyTuple("LIGAND_BOX_REASONS");
  return [...block.matchAll(/"([^"]+)"|LIGAND_BOX_REASONS/g)].flatMap(item => item[1] ? [item[1]] : ligandBox);
}

// spec .dryforge/spec.md 4, verbatim (the hand copy every other copy is compared with)
const S = {
  S1: "서열 GA는 변이 조합 공간에서 어떤 조합을 모델링·도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 순위나 추천이 아니다. 교차·편집의 부모 선택은 작업 모듈 기록이며 서버가 다시 계산하지 않았고 변이 목록의 부모–자식 관계만 검증했다.",
  S2: "이 실행은 시간·평가 상한·취소·기준 행 실패·연속 실패 등으로 일부만 계산되었다. 계산하지 않은 개체는 점수가 없으며 0이 아니고, 한도 도달로 멈춘 실행은 같은 설정으로 다시 해도 같은 경로를 보장하지 않는다.",
  S3: "재사용한 개체는 같은 후보 집합·구조·리간드·상자·seed·값으로 이전에 저장된 모델링·도킹 결과를 가져온 것이며, 저장된 결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있다.",
  S4: "점수는 각 개체의 변이 구조(PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 단백질만의 모델)에 사용자가 준 리간드 좌표를 그대로 두고 자유 도킹한 qvina 점수이며, 변이의 효과나 결합 친화도를 뜻하지 않는다.",
  S5: "OpenMM 전위는 각 구조의 Amber14-all + GBn2 값(kJ/mol)이며 서열이 다른 구조의 값은 서로 비교할 수 없고 ΔΔG·안정성이 아니다.",
  S6: "여러 곳 변이는 구조 순서대로 한 곳씩 PDBFixer로 연속 적용한 모델이며(앞 단계에서 놓은 원자 좌표는 다음 단계 전에 소수 넷째 자리로 반올림했다) 적용 순서와 곁사슬 크기에 따라 모델이 달라질 수 있다. 구조의 충돌·전위는 점수나 선택에 쓰지 않았고(전위가 늘거나 유한하지 않은 모델만 실패로 처리), 개체마다 수용체가 다르므로 개체 점수를 나란히 두는 것은 같은 수용체 안의 비교가 아니며(개체 도킹 결과의 M18 둘째 한계 문장이 말하는 조건과 다르다) 순위나 '더 잘 결합'을 뜻하지 않는다.",
};
const statement = id => ({ id, text: S[id] });

test("closed sets, ranges, limits and S1–S6 equal backend/mw/sequence_ga_constants.py", () => {
  assert.equal(lib.GA_PROTOCOL, pyString("PROTOCOL"));
  assert.equal(lib.GA_TOOL, pyString("TOOL"));
  assert.equal(lib.REFERENCE_KEY, pyString("REFERENCE_KEY"));
  assert.equal(lib.KEY_SEPARATOR, pyString("KEY_SEPARATOR"));
  assert.equal(lib.SELECTION_POLICY, pyString("SELECTION_POLICY"));
  assert.equal(lib.HYDROGEN_POLICY, pyString("HYDROGEN_POLICY"));
  assert.equal(lib.REPORT_TYPE, pyString("ANALYSIS_TYPE", reportsSource));
  assert.deepEqual(plain(lib.GA_KEYS), pyTuple("GA_KEYS"));
  assert.equal(lib.GA_KEYS.length, 11);
  assert.deepEqual(plain(lib.GA_FLOAT_KEYS), pyTuple("GA_FLOAT_KEYS"));
  assert.deepEqual(plain(lib.GA_RANGES), pyRanges());
  for (const name of ["STOP_REASONS", "ORIGINS", "EDIT_OPERATIONS", "EVALUATIONS", "STATES", "MODEL_FAILURE_REASONS",
    "FAILED_EXTRA_REASONS"]) assert.deepEqual(plain(lib[name]), pyTuple(name), name);
  assert.deepEqual(plain(lib.GA_STATUSES), pyTuple("STATUSES"));
  assert.deepEqual(plain(lib.STATUS_BY_STOP_REASON), pyStringDict("STATUS_BY_STOP_REASON"));
  assert.deepEqual(plain(lib.ADMISSION_REASONS), pyAdmissionReasons());
  for (const name of ["MIN_NEW_SLOTS", "FINISH_MARGIN_S", "TOTAL_S_MAX", "TIMEOUT_MAX_S", "MODEL_STEP_S", "DOCKING_STEP_S",
    "SECONDS_PER_UNIT", "UNITS_PER_EVALUATION", "CONSECUTIVE_FAILURE_LIMIT", "M18_HEAVY_ATOM_ESTIMATE"])
    assert.equal(lib[name], pyNumber(name), name);
  assert.equal(lib.TIMEOUT_MAX_S, lib.TOTAL_S_MAX + lib.FINISH_MARGIN_S);
  // Score wording = M18 / M19 (docking.ts) = the backend copies.
  assert.equal(lib.SCORE_LABEL, pyString("SCORE_LABEL"));
  assert.equal(lib.SCORE_LABEL, docking.SCORE_LABEL);
  assert.equal(lib.SCORE_COLUMN_LABEL, docking.SCORE_COLUMN_LABEL);
  assert.equal(lib.SCORE_ROW_LABEL, pyString("SCORE_ROW_LABEL"));
  // S1–S6: verbatim, in order, identical to the backend constants and to the spec text.
  const backendStatements = pyStringDict("STATEMENTS");
  assert.deepEqual(Object.keys(backendStatements), ["S1", "S2", "S3", "S4", "S5", "S6"]);
  assert.deepEqual(plain(lib.STATEMENTS), backendStatements);
  assert.deepEqual(plain(lib.STATEMENTS), S);
  // Model limitations L1, L3, SL5, L6 in the stored order; L1 / L3 / L6 are the M21 sentences.
  assert.deepEqual(plain(lib.MODEL_LIMITATIONS), [pyString("L1"), pyString("L3"), pyJoined("SL5"), pyString("L6")]);
  for (const sentence of [lib.MODEL_LIMITATIONS[0], lib.MODEL_LIMITATIONS[1], lib.MODEL_LIMITATIONS[3]])
    assert.ok(mutationModel.MODEL_LIMITATIONS.includes(sentence), sentence);
  // The API client sends timeout_s = ga.total_s + the finishing margin, with the sequence GA protocol id.
  const apiSource = fs.readFileSync(path.join(__dirname, "../src/lib/api.ts"), "utf8");
  assert.equal(Number(/^export const SEQUENCE_GA_FINISH_MARGIN_S = (\d+);/m.exec(apiSource)?.[1]), lib.FINISH_MARGIN_S);
  assert.ok(apiSource.includes('protocol_id: "sequence_ga_dock_v1", args,\n      timeout_s: args.ga.total_s + ' +
    "SEQUENCE_GA_FINISH_MARGIN_S"));
});

// ---- parameters ----

test("parameter definitions: all 11 keys with Korean label, range and default; seed has no default", () => {
  assert.deepEqual(plain(lib.GA_PARAMETERS.map(item => item.key)), plain(lib.GA_KEYS));
  for (const item of lib.GA_PARAMETERS) {
    assert.ok(/[가-힣]/.test(item.label), item.key);
    assert.equal(item.integer, !["crossover_fraction", "random_fraction"].includes(item.key), item.key);
    assert.deepEqual([item.min, item.max, item.default], plain(lib.GA_RANGES[item.key]));
  }
  assert.equal(lib.gaRangeText("seed"), "0–2147483647 · 기본 없음(필수)");
  assert.equal(lib.gaRangeText("population_size"), "4–16 개 · 기본 8");
  assert.equal(lib.gaRangeText("crossover_fraction"), "0–1 · 기본 0.5");
  assert.equal(lib.gaRangeText("random_fraction"), "0–0.5 · 기본 0.2");
  assert.equal(lib.gaRangeText("max_mutations"), "1–4 개 · 기본 3");
  assert.equal(lib.gaRangeText("max_new_evaluations"), "세대당 개체 수–64 건 · 기본 32");
  assert.equal(lib.gaRangeText("total_s"), "600–14400 초 · 기본 7200");
  const input = lib.initialGaInput();
  assert.deepEqual(plain(input), { seed: "", population_size: "8", generations: "5", elite_count: "2",
    tournament_size: "2", crossover_fraction: "0.5", random_fraction: "0.2", max_mutations: "3", patience: "3",
    max_new_evaluations: "32", total_s: "7200" });
  // "기본값으로": every default back, the typed GA seed kept.
  assert.deepEqual(plain(lib.resetGaDefaults({ ...input, seed: "17", population_size: "12", crossover_fraction: "1" })),
    { ...plain(input), seed: "17" });
});

const valid = (patch = {}) => ({ ...lib.initialGaInput(), seed: "7", ...patch });

test("validator: defaults plus a seed pass as numbers; every range boundary is inclusive", () => {
  const check = lib.checkGaInput(valid());
  assert.equal(check.ok, true);
  assert.deepEqual(plain(check.ga), { seed: 7, population_size: 8, generations: 5, elite_count: 2, tournament_size: 2,
    crossover_fraction: 0.5, random_fraction: 0.2, max_mutations: 3, patience: 3, max_new_evaluations: 32,
    total_s: 7200 });
  // Integer keys whose boundaries do not touch a cross rule at the default population (8) and elite (2).
  const ints = { seed: [0, 2147483647], generations: [1, 8], tournament_size: [2, 4], max_mutations: [1, 4],
    patience: [1, 8], total_s: [600, 14400], elite_count: [0, 4] };
  for (const [key, [low, high]] of Object.entries(ints)) {
    for (const value of [low, high]) assert.equal(lib.checkGaInput(valid({ [key]: String(value) })).ok, true, key);
    for (const value of [low - 1, high + 1]) {
      const bad = lib.checkGaInput(valid({ [key]: String(value) }));
      assert.equal(bad.ok, false, `${key}=${value}`);
      assert.ok(bad.fields[key].includes("(invalid_job_arguments)"), key);
      for (const other of lib.GA_KEYS) if (other !== key) assert.equal(bad.fields[other], null, `${key} -> ${other}`);
    }
  }
  // population_size 4..16 (elite and the evaluation cap kept consistent).
  assert.equal(lib.checkGaInput(valid({ population_size: "4", elite_count: "2", max_new_evaluations: "4" })).ok, true);
  assert.equal(lib.checkGaInput(valid({ population_size: "16", max_new_evaluations: "16" })).ok, true);
  assert.notEqual(lib.checkGaInput(valid({ population_size: "3", elite_count: "0" })).fields.population_size, null);
  assert.notEqual(lib.checkGaInput(valid({ population_size: "17", max_new_evaluations: "64" })).fields.population_size,
    null);
  // max_new_evaluations ..64 (absolute minimum 4 = the smallest population).
  assert.equal(lib.checkGaInput(valid({ max_new_evaluations: "64" })).ok, true);
  assert.notEqual(lib.checkGaInput(valid({ max_new_evaluations: "65" })).fields.max_new_evaluations, null);
  // The two fractions are finite reals: crossover 0..1, random 0..0.5.
  for (const text of ["0", "0.0", "1", "1.0", "0.25", "5e-1"])
    assert.equal(lib.checkGaInput(valid({ crossover_fraction: text })).ok, true, text);
  for (const text of ["0", "0.0", "0.5", "0.25", "5e-1"])
    assert.equal(lib.checkGaInput(valid({ random_fraction: text })).ok, true, text);
  for (const text of ["1.01", "-0.1", "", "abc", "Infinity", "NaN", "0x1", ".2", "1/5", "true"])
    assert.equal(lib.checkGaInput(valid({ crossover_fraction: text })).ok, false, text);
  for (const text of ["0.51", "-0.1", "", "Infinity", "NaN", "false"])
    assert.equal(lib.checkGaInput(valid({ random_fraction: text })).ok, false, text);
  assert.equal(lib.checkGaInput(valid({ random_fraction: " 0.3 " })).ga.random_fraction, 0.3);
});

test("validator guards: integers only (no bool, decimals, signs, blanks, exponents), GA seed required", () => {
  for (const text of ["", " ", "1.0", "8.5", "+3", "-1", "3e0", "1e1", "0x10", "07", "abc", "1 2", "true", "false",
    "Infinity", "9007199254740993"])
    assert.notEqual(lib.checkGaInput(valid({ population_size: text })).fields.population_size, null, text);
  for (const text of ["true", "1e3", "600.0"])
    assert.notEqual(lib.checkGaInput(valid({ total_s: text })).fields.total_s, null, text);
  const noSeed = lib.checkGaInput(lib.initialGaInput());
  assert.equal(noSeed.ok, false);
  assert.ok(noSeed.fields.seed.includes("(필수)"));
  assert.deepEqual(plain(noSeed.errors), [noSeed.fields.seed]);
  assert.equal(lib.checkGaInput(valid({ seed: "2147483648" })).ok, false);
});

test("cross rules: population_size − elite_count ≥ 2 and max_new_evaluations ≥ population_size", () => {
  const elite = lib.checkGaInput(valid({ population_size: "5", elite_count: "4" }));
  assert.equal(elite.ok, false);
  assert.ok(elite.fields.elite_count.includes("2 이상"), elite.fields.elite_count);
  assert.ok(elite.fields.elite_count.includes("(invalid_job_arguments)"));
  assert.equal(elite.fields.population_size, null);
  assert.equal(lib.checkGaInput(valid({ population_size: "6", elite_count: "4" })).ok, true);
  assert.equal(lib.checkGaInput(valid({ population_size: "4", elite_count: "3", max_new_evaluations: "4" })).ok, false);
  assert.equal(lib.checkGaInput(valid({ population_size: "4", elite_count: "2", max_new_evaluations: "4" })).ok, true);
  const cap = lib.checkGaInput(valid({ population_size: "16", max_new_evaluations: "15" }));
  assert.equal(cap.ok, false);
  assert.ok(cap.fields.max_new_evaluations.includes("세대당 개체 수(16) 이상"), cap.fields.max_new_evaluations);
  assert.equal(lib.checkGaInput(valid({ population_size: "16", max_new_evaluations: "16" })).ok, true);
  assert.notEqual(lib.checkGaInput(valid({ population_size: "4", max_new_evaluations: "3" })).fields.max_new_evaluations,
    null);
  // A field already out of range is not reported twice through a cross rule.
  assert.equal(lib.checkGaInput(valid({ population_size: "abc", elite_count: "9" })).errors.length, 2);
  // Errors keep the GA key order.
  const many = lib.checkGaInput(valid({ seed: "", total_s: "1", population_size: "6", elite_count: "5" }));
  assert.deepEqual(plain(many.errors), [many.fields.seed, many.fields.elite_count, many.fields.total_s]);
});

test("timeout is always total_s + 600 (≤ 15000); the effective parameter summary lists every key", () => {
  assert.equal(lib.gaTimeoutS(600), 1200);
  assert.equal(lib.gaTimeoutS(7200), 7800);
  assert.equal(lib.gaTimeoutS(lib.TOTAL_S_MAX), lib.TIMEOUT_MAX_S);
  const lines = lib.gaParameterLines(lib.checkGaInput(valid()).ga);
  assert.equal(lines.length, lib.GA_KEYS.length + 1);
  assert.deepEqual(plain(lines.slice(0, -1).map(line => line[0])), plain(lib.GA_PARAMETERS.map(item => item.label)));
  assert.equal(lines[5][1], "0.5");
  assert.ok(lines.at(-1)[1].startsWith("7800초"), lines.at(-1)[1]);
});

// ---- request builder ----

const SDF = "obj://r/chemical_raw_input/sdf1";
const SET = "obj://r/mutation_candidate_set/set1";
const ACK = { keep_input_protonation: true, tool_assigned_types_charges: true, rigid_no_optimization: true };
function readyForm(patch = {}) {
  let form = lib.initialGaForm();
  form = lib.patchGaForm(form, { candidateSet: SET, sdfHandle: SDF, boxSource: "ligand_range", seed: "42",
    acknowledgement: ACK, selectionConfirmed: true, hydrogenConfirmed: true, ga: valid() });
  return lib.patchGaForm(form, patch);
}

test("request: the fixed server shape {candidate_set, ligand sdf, box, parameters, two literals, ack, ga}", () => {
  const check = lib.gaArgs(readyForm());
  assert.equal(check.ok, true, check.errors?.join(" "));
  assert.deepEqual(Object.keys(check.args).sort(), ["acknowledgement", "box", "candidate_set", "ga", "hydrogen_policy",
    "ligand", "parameters", "selection_policy"]);
  assert.equal(check.args.candidate_set, SET);
  assert.deepEqual(plain(check.args.ligand), { source: "sdf", sdf_handle: SDF });
  assert.deepEqual(plain(check.args.box), { source: "ligand_range", margin_A: 8 });
  assert.deepEqual(plain(check.args.parameters), { seed: 42, exhaustiveness: 8, num_modes: 9, energy_range: 3 });
  assert.equal(check.args.selection_policy, "protein_only");
  assert.equal(check.args.hydrogen_policy, "rebuild_pH7");
  assert.deepEqual(plain(check.args.acknowledgement), ACK);
  assert.equal(check.args.ga.seed, 7);   // the GA seed, separate from the evaluation seed
  assert.deepEqual(Object.keys(check.args.ga), plain(lib.GA_KEYS));
  const text = JSON.stringify(check.args);
  for (const key of ["mode", "receptor_", "connectivity", "contact_cutoff_A", "filter", "conformers", "timeout_s"])
    assert.ok(!text.includes(`"${key}`), key);
  assert.equal(lib.gaTimeoutS(check.args.ga.total_s), 7800);
  // The same M18 condition (ligand, box, values, acknowledgement) as the M21 same-condition docking request.
  const pair = mutationModel.pairDockingRequests({ ...readyForm(), ligandSource: "sdf" }, "obj://r/mutation_model/m");
  assert.equal(pair.ok, true);
  for (const key of ["ligand", "box", "parameters", "acknowledgement"])
    assert.deepEqual(plain(check.args[key]), plain(pair.args.mutant[key]), key);
  // A manual box keeps the M18 shape; equal GA and evaluation seeds are allowed (two inputs).
  const manual = lib.gaArgs(readyForm({ boxSource: "manual", center: ["1", "2", "3"], size: ["20", "20", "20"] }));
  assert.deepEqual(plain(manual.args.box), { source: "manual", center_A: [1, 2, 3], size_A: [20, 20, 20] });
  assert.equal(lib.gaArgs(readyForm({ ga: valid({ seed: "42" }) })).ok, true);
  assert.equal(lib.gaArgsKey(check.args), JSON.stringify(check.args));
});

test("request guards: nothing chosen automatically; SDF only, free only, no instance range; every reason listed", () => {
  const empty = lib.initialGaForm();
  assert.equal(empty.candidateSet, null);
  assert.equal(empty.sdfHandle, null);
  assert.equal(empty.boxSource, null);
  assert.equal(empty.selectionConfirmed, false);
  assert.equal(empty.hydrogenConfirmed, false);
  assert.equal(empty.ligandSource, "sdf");
  assert.equal(empty.mode, "free");
  const refused = lib.gaArgs(empty);
  assert.equal(refused.ok, false);
  for (const part of ["변이 후보 집합", "3D SDF", "상자 출처", "seed:", "acknowledgement_missing", "confirmation_missing",
    "GA seed"]) assert.ok(refused.errors.some(text => text.includes(part)), part);
  assert.ok(!refused.errors.some(text => text.includes("방식")));
  // The ligand source stays the 3D SDF, the mode stays free and an instance-range box is dropped.
  const forced = lib.patchGaForm(readyForm(), { ligandSource: "candidate", mode: "core_fixed",
    boxSource: "instance_range" });
  assert.equal(forced.ligandSource, "sdf");
  assert.equal(forced.mode, "free");
  assert.equal(forced.boxSource, null);
  assert.ok(lib.boxSourceDisabledReason("instance_range").includes("인스턴스"));
  assert.equal(lib.boxSourceDisabledReason("ligand_range"), null);
  assert.equal(lib.boxSourceDisabledReason("manual"), null);
  assert.ok(lib.ligandSourceDisabledReason("candidate").includes("SDF"));
  assert.equal(lib.ligandSourceDisabledReason("sdf"), null);
  // One confirmation missing, one acknowledgement missing, one GA field wrong: each blocks with its reason.
  const literal = lib.gaArgs(readyForm({ hydrogenConfirmed: false }));
  assert.deepEqual(plain(literal), { ok: false, errors: ["protein_only와 rebuild_pH7 확인을 모두 체크하세요 " +
    "(confirmation_missing)."] });
  assert.ok(lib.gaArgs(readyForm({ acknowledgement: { ...ACK, rigid_no_optimization: false } })).errors
    .some(text => text.includes("acknowledgement_missing")));
  const badGa = lib.gaArgs(readyForm({ ga: valid({ population_size: "5", elite_count: "4" }) }));
  assert.equal(badGa.ok, false);
  assert.equal(badGa.errors.length, 1);
  assert.ok(badGa.errors[0].includes("2 이상"));
  // Changing the candidate set keeps the rest of the form (no other choice is made for the person).
  const moved = lib.patchGaForm(readyForm(), { candidateSet: "obj://r/mutation_candidate_set/set2" });
  assert.equal(moved.sdfHandle, SDF);
  assert.equal(moved.selectionConfirmed, true);
});

// ---- candidate sets and availability ----

test("candidate sets: server order, invalid rows not selectable, nothing preselected; unavailable reasons", () => {
  const counts = (positions, candidates) => ({ positions: positions + 1, candidate_positions: positions,
    excluded_positions: 1, released_positions: 0, candidates, exclusion_reason_counts: {}, source_counts: {} });
  const rows = [
    { handle: "obj://r/mutation_candidate_set/b", created_seq: 9, valid: true, counts: counts(3, 6), null_result: false },
    { handle: "obj://r/mutation_candidate_set/x", created_seq: 7, valid: false, counts: null, null_result: null },
    { handle: "obj://r/mutation_candidate_set/a", created_seq: 5, valid: true, counts: counts(0, 0), null_result: true },
  ];
  const options = lib.candidateSetOptions(rows);
  assert.deepEqual(plain(options.map(item => [item.handle, item.selectable])), [["obj://r/mutation_candidate_set/b", true],
    ["obj://r/mutation_candidate_set/x", false], ["obj://r/mutation_candidate_set/a", true]]);
  assert.ok(options[0].text.includes("후보 위치 3개") && options[0].text.includes("후보 6개"), options[0].text);
  assert.ok(options[1].text.includes("읽을 수 없음"));
  assert.ok(options[2].text.includes("후보 0개"));
  const capability = { available: true, reason: null, reason_code: null };
  assert.ok(lib.gaUnavailableReason({ runId: null, capability, candidateSets: rows }).includes("run"));
  assert.ok(lib.gaUnavailableReason({ runId: "r", capability: { available: false, reason: "qvina 엔진 환경이 없음",
    reason_code: "engine_missing" }, candidateSets: rows }).includes("(engine_missing)"));
  assert.ok(lib.gaUnavailableReason({ runId: "r", capability: null, candidateSets: rows }).length > 0);
  assert.ok(lib.gaUnavailableReason({ runId: "r", capability, candidateSets: [rows[1]] }).includes("후보 집합"));
  assert.equal(lib.gaUnavailableReason({ runId: "r", capability, candidateSets: rows }), null);
});

// ---- preflight ----

const pair = (calls, wall) => ({ expensive_calls: calls, wall_clock_s: wall });
const GA_DEFAULTS = { seed: 7, population_size: 8, generations: 5, elite_count: 2, tournament_size: 2,
  crossover_fraction: 0.5, random_fraction: 0.2, max_mutations: 3, patience: 3, max_new_evaluations: 32, total_s: 7200 };
function preflight(patch = {}) {
  return { schema: "sequence_ga_preflight@1", starts_job: false, capability: { available: true },
    score_label: docking.SCORE_LABEL, budget: { expensive_calls: { used: 0, limit: 10 },
      wall_clock_s: { used: 0, limit: 1800 } }, remaining: pair(10, 1800),
    admission: { admitted: true, error: null, reason_code: null, message: null, detail: null },
    selection_sha256: "s", conditions_sha256: "c",
    space: { positions: 400, candidates: 7600, effective_max_mutations: 3, size: 136935281390200 },
    projection_heavy_atoms: 602, heavy_atom_warning: false, reusable_count: 4, reference_reusable: true,
    reserved_evaluations: 32, reserved_units: 66, needed: pair(66, 7800), shortfall: pair(56, 6000),
    full_run_may_be_partial: true, ga: GA_DEFAULTS,
    statements: ["S1", "S4", "S5", "S6"].map(statement), existing_job: null, ...patch };
}
const NULLS = { selection_sha256: null, conditions_sha256: null, space: null, projection_heavy_atoms: null,
  heavy_atom_warning: null, reusable_count: null, reference_reusable: null, reserved_evaluations: null,
  reserved_units: null, needed: null, shortfall: null, full_run_may_be_partial: null, ga: null, statements: null,
  existing_job: null };
const refusal = (error, reasonCode, message, detail) => preflight({ ...NULLS,
  admission: { admitted: false, error, reason_code: reasonCode, message, detail: { reason_code: reasonCode, ...detail } } });

test("preflight lines: server numbers as given (space, effective cap, reuse, reference row, units, need, shortfall)", () => {
  const lines = Object.fromEntries(lib.gaPreflightLines(preflight()));
  assert.equal(lines["조합 공간"], "위치 400개 · 후보 7,600개 · 조합 136,935,281,390,200개 (서버 계산)");
  assert.equal(lines["유효 동시 변이 수 상한"], "3개 (입력 3개, 서버 값)");
  assert.equal(lines["투영 단백질 중원자"], "602개");
  assert.ok(lines["재사용 가능 개체"].startsWith("4개") && lines["재사용 가능 개체"].includes("과금하지 않음"));
  assert.equal(lines["야생형 기준 행"], lib.REFERENCE_REUSED_TEXT);
  assert.ok(lib.REFERENCE_REUSED_TEXT.includes("2단위") && lib.REFERENCE_REUSED_TEXT.includes("돌려받지 않음"));
  assert.equal(lines["예약 단위"], "66단위 (새 평가 최대 32건 × 2단위 + 야생형 기준 행 2단위)");
  assert.equal(lines["예상 시간 상한"], "7800.0초");
  assert.equal(lines["필요"], "비싼 계산 66단위 · 활동 시간 7800.0초 (최대)");
  assert.equal(lines["현재 잔여"], "비싼 계산 10단위 · 활동 시간 1800.0초");
  assert.equal(lines["부족분"], "비싼 계산 56단위 · 활동 시간 6000.0초");
  assert.ok(lines["과금"].includes("66단위") && lines["과금"].includes("돌려받지 않음"));
  assert.equal(lines["시간 상한"], lib.PARTIAL_RISK_NOTE);
  assert.equal(lines["중원자 경고"], undefined);
  assert.equal(lines["대기"], lib.WAIT_NOTE);
  // The effective cap shows the server's value next to the input (never min() in the browser).
  assert.equal(Object.fromEntries(lib.gaPreflightLines(preflight({ space: { positions: 2, candidates: 3,
    effective_max_mutations: 2, size: 5 }, ga: { ...GA_DEFAULTS, max_mutations: 4 } })))["유효 동시 변이 수 상한"],
  "2개 (입력 4개, 서버 값)");
  const other = Object.fromEntries(lib.gaPreflightLines(preflight({ full_run_may_be_partial: false,
    reference_reusable: false, heavy_atom_warning: true, projection_heavy_atoms: 5120 })));
  assert.equal(other["시간 상한"], undefined);
  assert.equal(other["야생형 기준 행"], lib.REFERENCE_NEW_TEXT);
  assert.equal(other["중원자 경고"], lib.heavyAtomWarningText(5120));
  assert.ok(other["중원자 경고"].includes("5,120개") && other["중원자 경고"].includes("4,890") &&
    other["중원자 경고"].includes("receptor_invalid"), other["중원자 경고"]);
  const text = lib.gaPreflightLines(preflight({ heavy_atom_warning: true })).map(item => item.join(" ")).join("\n");
  assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
  assert.deepEqual(plain(lib.gaPreflightLines(refusal("input_invalid", "ga_space_too_small", "m", {}))), []);
  assert.equal(lib.gaExistingJobText({ job_id: "j1", status: "running" }).includes("j1 · running"), true);
});

test("preflight refusal: closed reason \"한국어 (code)\", the server message and its typed detail", () => {
  const space = lib.gaPreflightRefusalText(refusal("input_invalid", "ga_space_too_small",
    "the combination space is smaller than ga.population_size", { size: 3, population_size: 8 }));
  assert.ok(space.startsWith(lib.gaReasonText("ga_space_too_small")), space);
  assert.ok(space.includes("조합 3개, 세대당 개체 수 8") && space.includes("smaller than"), space);
  const m7 = lib.gaPreflightRefusalText(refusal("input_invalid", "openmm_preflight_failed", "M7 refused",
    { m7_reason: "nonstandard_residue", m7_message: "residue X" }));
  assert.ok(m7.includes("(openmm_preflight_failed)") && m7.includes("M7: nonstandard_residue · residue X"), m7);
  const residue = { model_number: 1, chain_auth: "A", chain_label: null, seq_auth: 44, seq_label: null, icode: "",
    resname: "ILE" };
  const mismatch = lib.gaPreflightRefusalText(refusal("input_invalid", "residue_mismatch", "m", { residue }));
  assert.ok(mismatch.includes("(residue_mismatch)") && mismatch.includes('chain_label=null') &&
    mismatch.includes('resname="ILE"'), mismatch);
  const staged = lib.gaPreflightRefusalText(refusal("resource_exceeded", "staged_input_bytes", "m",
    { bytes: 17000000, max_bytes: 16777216 }));
  assert.ok(staged.includes("17000000") && staged.includes("16777216"), staged);
  const env = refusal("precondition", "engine_missing", "qvina 엔진 환경이 없음", {});
  assert.ok(lib.gaPreflightRefusalText(env).startsWith("qvina 엔진 환경이 없음 (engine_missing)"));
  assert.equal(lib.gaLimitApprovalOffered(env, false), false);
  for (const reason of lib.ADMISSION_REASONS) {
    const text = lib.gaPreflightRefusalText(refusal("input_invalid", reason, "message", {}));
    assert.ok(text.includes(`(${reason})`), reason);
    assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
  }
});

test("limit approval offer and start guard: admitted, short, not dry-run; same args key; one GA at a time", () => {
  assert.equal(lib.gaLimitApprovalOffered(preflight(), false), true);
  assert.equal(lib.gaLimitApprovalOffered(preflight(), true), false);
  assert.equal(lib.gaLimitApprovalOffered(preflight({ shortfall: pair(0, 0) }), false), false);
  assert.equal(lib.gaLimitApprovalOffered(preflight({ shortfall: pair(0, 5) }), false), true);
  assert.equal(lib.gaLimitApprovalOffered(null, false), false);
  const check = lib.gaArgs(readyForm());
  const key = lib.gaArgsKey(check.args);
  const capability = { available: true, reason: null, reason_code: null };
  const base = { capability, busy: false, activeJob: null, check, dryRun: false };
  assert.ok(lib.gaStartBlockedReason({ ...base, preflight: null }).includes("시작 전 확인"));
  assert.ok(lib.gaStartBlockedReason({ ...base, preflight: { key: "other", value: preflight() } })
    .includes("시작 전 확인"));
  assert.ok(lib.gaStartBlockedReason({ ...base, preflight: { key, value: preflight() } })
    .includes("ga_limit_raise_required"));
  assert.equal(lib.gaStartBlockedReason({ ...base, preflight: { key, value: preflight({ shortfall: pair(0, 0) }) } }), null);
  assert.equal(lib.gaStartBlockedReason({ ...base, dryRun: true, preflight: { key, value: preflight() } }), null);
  assert.ok(lib.gaStartBlockedReason({ ...base, preflight: { key, value: refusal("input_invalid", "ga_space_too_small",
    "m", { size: 3, population_size: 8 }) } }).includes("(ga_space_too_small)"));
  assert.ok(lib.gaStartBlockedReason({ ...base, activeJob: { status: "running" }, preflight: { key,
    value: preflight({ shortfall: pair(0, 0) }) } }).includes("한 번에 한"));
  assert.ok(lib.gaStartBlockedReason({ ...base, check: lib.gaArgs(lib.initialGaForm()), preflight: null })
    .includes("confirmation_missing"));
  assert.ok(lib.gaStartBlockedReason({ ...base, capability: { available: false, reason: "없음",
    reason_code: "pdbfixer_unavailable" }, preflight: null }).includes("pdbfixer_unavailable"));
  assert.equal(lib.gaLimitApprovalText({ raised: false, increase: pair(0, 0), limits_after: pair(1, 1) }),
    "이미 충분해 한도를 바꾸지 않았습니다.");
  const raised = lib.gaLimitApprovalText({ raised: true, increase: pair(56, 6060), limits_after: pair(66, 7860) });
  assert.ok(raised.includes("올린 양 비싼 계산 56단위") && raised.includes("새 한도 비싼 계산 66단위"), raised);
});

// ---- progress, job, status ----

test("job phase: a claimed job blocked on a reason the queue's start accepts again waits for 작업 시작", () => {
  // The queue's `start` set (backend/mw/jobs/queue.py: a claimed job with one of these blocked reasons starts again).
  const queueSource = fs.readFileSync(path.join(__dirname, "../../backend/mw/jobs/queue.py"), "utf8");
  const match = /job\["status"\] == "claimed" and job\.get\("blocked_reason"\) in \{([^}]*)\}/.exec(queueSource);
  assert.ok(match, "queue start restart set not found");
  const restartable = [...match[1].matchAll(/"([^"]+)"/g)].map(item => item[1]);
  assert.deepEqual(restartable, ["approval_or_cancel", "global_concurrency_busy", "global_job_cleanup_pending",
    "global_job_ledger_unavailable"]);
  assert.deepEqual(plain(lib.GA_RESTARTABLE_BLOCKS), restartable);
  const job = (status, blocked_reason = null) => ({ status, blocked_reason });
  for (const reason of restartable) {
    assert.equal(lib.gaJobPhase(job("claimed", reason), false), "saved", reason);
    // while the run's first expensive-call approval is pending, the approval comes first
    assert.equal(lib.gaJobPhase(job("claimed", reason), true), "awaiting_approval", reason);
  }
  assert.equal(lib.gaJobPhase(job("claimed"), false), "running");                     // claimed and starting
  assert.equal(lib.gaJobPhase(job("claimed", "job_cleanup_pending"), false), "running");   // not restartable
  assert.equal(lib.gaJobPhase(null, false), "none");
  assert.equal(lib.gaJobPhase(job("queued"), false), "saved");
  assert.equal(lib.gaJobPhase(job("queued"), true), "awaiting_approval");
  assert.equal(lib.gaJobPhase(job("running"), false), "running");
  assert.equal(lib.gaJobPhase(job("running", "approval_or_cancel"), false), "running");
  for (const status of ["done", "cancelled", "failed", "interrupted"])
    assert.equal(lib.gaJobPhase(job(status, "approval_or_cancel"), false), docking.dockingJobPhase(job(status), false));
  assert.equal(lib.gaJobPhase({ status: "claimed" }, false), "running");                 // no blocked_reason field
});

test("progress shows the reference row state and staged counts only; job text keeps a published summary outcome", () => {
  const progress = { space: { positions: 3, candidates: 6, effective_max_mutations: 3, size: 26 },
    reserved_evaluations: 7, reserved_units: 16, reused_planned: 2, reference_reuse_planned: true,
    reference_recorded: true, individuals_started: 5, individuals_finished: 4, generation_records: 2,
    generations_complete: 1, summary_handle: null, summary_status: null, summary_stop_reason: null };
  const text = lib.gaProgressText(progress);
  // `reused_planned` is the size of the start's reuse index: individuals that can be reused, not ones that will be
  assert.equal(text, "야생형 기준 행 기록됨(재사용 예정) · 완료한 세대 1개(세대 기록 2개) · 새 평가 시작 5건 · " +
    "새 평가 끝 4건 · 재사용 가능 개체 2개(파일이 없어 새 평가 수에 들지 않음) · 예약 16단위");
  assert.ok(lib.gaProgressText({ ...progress, reference_recorded: false, reference_reuse_planned: false })
    .startsWith("야생형 기준 행 아직 기록 없음(새 평가)"));
  assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
  const ga = { summary_handle: "obj://r/sequence_ga_result/h", summary_status: "partial",
    summary_stop_reason: "reference_failed" };
  const failed = lib.gaJobText({ status: "failed", cancel_requested: false,
    failure: { error: "resource_exceeded", message: "job timeout" }, sequence_ga: ga }, false);
  assert.ok(failed.includes("작업 기록 failed") && failed.includes("(reference_failed)") && !failed.includes("job timeout"),
    failed);
  assert.ok(lib.gaJobText({ status: "failed", cancel_requested: false, failure: { error: "fatal", message: "m",
    reason_code: "worker_failed" }, sequence_ga: null }, false).startsWith("서열 GA 작업 실패: 작업 프로세스 중단 (worker_failed)"));
  assert.equal(lib.gaJobText(null, false), "서열 GA 작업 없음");
  assert.ok(lib.gaJobText({ status: "queued", cancel_requested: false, failure: null }, true).includes("승인"));
  assert.ok(lib.gaJobText({ status: "running", cancel_requested: true, failure: null }, false).includes("취소 요청됨"));
  assert.equal(lib.gaJobText({ status: "claimed", blocked_reason: "global_concurrency_busy", cancel_requested: false,
    failure: null }, false), lib.gaJobText({ status: "queued", cancel_requested: false, failure: null }, false));
  assert.equal(lib.gaApprovalRequired(409, { gate: "expensive_first_call", tool: "sequence_ga_design" }), true);
  assert.equal(lib.gaApprovalRequired(409, { gate: "expensive_first_call", tool: "qvina_ga_design" }), false);
  assert.equal(lib.gaApprovalRequired(412, { gate: "expensive_first_call", tool: "sequence_ga_design" }), false);
  const jobs = [{ run_id: "r", protocol_id: "sequence_ga_dock_v1", status: "done" },
    { run_id: "r", protocol_id: "qvina_ga_dock_v1", status: "running" },
    { run_id: "r", protocol_id: "sequence_ga_dock_v1", status: "running", job_id: "j2" },
    { run_id: "s", protocol_id: "sequence_ga_dock_v1", status: "queued" }];
  assert.equal(lib.gaActiveJob(jobs, "r").job_id, "j2");
  assert.equal(lib.gaActiveJob(jobs, "x"), null);
  assert.equal(lib.gaActiveJob(null, "r"), null);
  assert.equal(lib.gaJobResult({ status: "done", artifacts: { sequence_ga_result: "obj://r/sequence_ga_result/h" } }),
    "obj://r/sequence_ga_result/h");
  assert.equal(lib.gaJobResult({ status: "running", artifacts: {} }), null);
  assert.ok(lib.gaReportMatches({ manifest: { schema: "method_report_manifest@1", analysis_type: "sequence_ga",
    result_handle: "h" } }, "h"));
  assert.ok(!lib.gaReportMatches({ manifest: { schema: "method_report_manifest@1", analysis_type: "ligand_ga",
    result_handle: "h" } }, "h"));
});

test("stop reasons, statuses and every closed reason: Korean name with the code; no_change is 점수 최솟값 변화 없음", () => {
  assert.deepEqual(Object.keys(lib.STOP_REASON_LABEL), plain(lib.STOP_REASONS));
  assert.equal(lib.STOP_REASON_LABEL.no_change, "점수 최솟값 변화 없음");
  for (const reason of lib.STOP_REASONS) {
    const text = lib.gaStatusText({ status: lib.STATUS_BY_STOP_REASON[reason], stop_reason: reason });
    assert.ok(text.includes(`${lib.STOP_REASON_LABEL[reason]} (${reason})`), reason);
    assert.ok(/[가-힣]/.test(lib.STOP_REASON_LABEL[reason]), reason);
    assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
  }
  assert.equal(lib.gaStatusText({ status: "complete", stop_reason: "no_change" }),
    "완료 (complete) · 종료 이유: 점수 최솟값 변화 없음 (no_change)");
  assert.ok(lib.gaStatusText({ status: "partial", stop_reason: "evaluation_limit" }).startsWith("일부만 계산됨 (partial)"));
  assert.equal(lib.stopReasonText("unknown_x"), "unknown_x");
  // Every admission, modeling-failure, docking-failure (backend set) and extra failure code has a Korean name.
  const codes = [...lib.ADMISSION_REASONS, ...pyTuple("MODEL_FAILURE_REASONS"), ...pyTuple("DOCKING_FAILURE_REASONS"),
    ...pyTuple("FAILED_EXTRA_REASONS"), "evidence_invalid", "method_evidence_invalid", "dry_run"];
  for (const code of codes) {
    const text = lib.gaReasonText(code);
    assert.ok(text.endsWith(` (${code})`) && /[가-힣]/.test(text), code);
    assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
  }
  assert.equal(lib.gaReasonText("ligand_not_3d"), docking.dockingReasonText("ligand_not_3d"));
  assert.equal(lib.gaReasonText("coordinates_changed"), mutationModel.modelReasonText("coordinates_changed"));
  assert.equal(lib.gaReasonText("unknown_x"), "unknown_x");
});

test("statements: the server's stored texts verbatim and in order; S1–S6 pass the wording check", () => {
  assert.deepEqual(plain(lib.gaStatementTexts(["S1", "S2", "S4", "S5", "S6"].map(statement))),
    [S.S1, S.S2, S.S4, S.S5, S.S6]);
  assert.deepEqual(plain(lib.gaStatementTexts([{ id: "S1", text: "server S1" }])), ["server S1"]);
  assert.deepEqual(plain(lib.gaStatementTexts(null)), []);
  for (const text of Object.values(S)) assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
  assert.deepEqual(plain(lib.gaForbiddenWords(Object.values(S).join("\n"))), []);
});

// ---- results ----

const res = (seq, resname, extra = {}) => ({ model_number: 1, chain_auth: "A", chain_label: "A", seq_auth: seq,
  seq_label: seq, icode: "", resname, ...extra });
const K6 = res(6, "LYS");
const I44 = res(44, "ILE", { icode: "A", seq_label: null });
const G76 = res(76, "GLY", { chain_label: null });
const mut = (candidate_index, residue, from, to) => ({ candidate_index, residue, from, to });
const MUTS = { 0: mut(0, K6, "K", "A"), 1: mut(1, K6, "K", "W"), 2: mut(2, I44, "I", "A"), 3: mut(3, I44, "I", "W"),
  4: mut(4, G76, "G", "A"), 5: mut(5, G76, "G", "W") };
const entry = (key, origin, state, score, extra = {}) => ({ key,
  mutations: key.split("-").map(index => MUTS[index]), origin, parents: null, edit_op: null,
  evaluation: origin === "carried" ? null : "computed", pick_index: 0, eval_index: origin === "carried" ? null : 0,
  state, reason_code: state === "failed" ? "model_timeout" : null, score,
  model_handle: state === "failed" ? null : `obj://r/mutation_set_model/${key}`,
  result_handle: state === "failed" ? null : `obj://r/docking_result/${key}`,
  detail_available: state !== "failed", ...extra });
const GEN = { index: 2, complete: true, min_score: -8.25, max_score: 0, individuals: [
  entry("1-3", "carried", "scored", -8.25, { pick_index: 3 }),
  entry("2", "crossover", "failed", null, { parents: ["1-3", "0-5"], pick_index: 8 }),
  entry("3", "edit", "scored", 0, { parents: ["1-3"], edit_op: "remove", pick_index: 9 }),
  entry("5", "random", "null_result", null, { evaluation: "reused", eval_index: null, pick_index: 10 }),
  entry("0-3", "edit", "scored", -7.2, { parents: ["1-3"], edit_op: "move", pick_index: 11 }),
  entry("2-5", "random", "scored", -7.2, { pick_index: 12 }),
] };
const keys = rows => plain(rows.map(row => row.key));

test("individuals table: score-less rows last in every order (slot order among them), never as 0", () => {
  const rows = lib.individualRows(GEN);
  assert.deepEqual(plain(rows.map(row => row.position)), [0, 1, 2, 3, 4, 5]);
  assert.deepEqual(keys(lib.sortIndividuals(rows, null)), ["1-3", "3", "0-3", "2-5", "2", "5"]);
  assert.deepEqual(keys(lib.sortIndividuals(rows, { key: "slot", direction: "asc" })), ["1-3", "3", "0-3", "2-5", "2", "5"]);
  assert.deepEqual(keys(lib.sortIndividuals(rows, { key: "slot", direction: "desc" })), ["2-5", "0-3", "3", "1-3", "2", "5"]);
  assert.deepEqual(keys(lib.sortIndividuals(rows, { key: "score", direction: "asc" })), ["1-3", "0-3", "2-5", "3", "2", "5"]);
  assert.deepEqual(keys(lib.sortIndividuals(rows, { key: "score", direction: "desc" })), ["3", "0-3", "2-5", "1-3", "2", "5"]);
  // Keys compare as integer lists (never as strings): [0,3] < [1,3] < [2,5] < [3].
  assert.deepEqual(keys(lib.sortIndividuals(rows, { key: "key", direction: "asc" })), ["0-3", "1-3", "2-5", "3", "2", "5"]);
  assert.deepEqual(keys(lib.sortIndividuals(rows, { key: "key", direction: "desc" })), ["3", "2-5", "1-3", "0-3", "2", "5"]);
  const numeric = lib.individualRows({ individuals: [entry("10", "initial", "scored", -1), entry("9", "initial", "scored", -1)] });
  assert.deepEqual(keys(lib.sortIndividuals(numeric, { key: "key", direction: "asc" })), ["9", "10"]);
  // A non-scored state is score-less even if a number were present.
  const odd = lib.individualRows({ individuals: [entry("0", "initial", "failed", -99), entry("1", "initial", "scored", -1)] });
  assert.deepEqual(keys(lib.sortIndividuals(odd, { key: "score", direction: "asc" })), ["1", "0"]);
  assert.deepEqual(keys(lib.sortIndividuals(odd, { key: "score", direction: "desc" })), ["1", "0"]);
  const before = plain(rows);
  lib.sortIndividuals(rows, { key: "score", direction: "desc" });
  assert.deepEqual(plain(rows), before);
  let sort = lib.nextIndividualSort(null, "score");
  assert.deepEqual(plain(sort), { key: "score", direction: "asc" });
  sort = lib.nextIndividualSort(sort, "score");
  assert.equal(lib.individualAriaSort(sort, "score"), "descending");
  assert.equal(lib.individualAriaSort(sort, "slot"), "none");
  assert.ok(lib.ORDER_NOTE.includes("늘 끝") && lib.ORDER_NOTE.includes("표시 순서"), lib.ORDER_NOTE);
});

test("cells: mutation one-liner and 7 fields, origin and edit names, reuse flag, stored score only, generation values", () => {
  assert.equal(lib.mutationText(MUTS[3]), "ILE A:44A I→W");
  assert.equal(lib.mutationsText(GEN.individuals[4].mutations), "LYS A:6 K→A, ILE A:44A I→W");
  assert.deepEqual(plain(lib.mutationFieldLines([MUTS[4]])), ["후보 번호 4 · GLY A:76 G→A · model_number=1, " +
    'chain_auth="A", chain_label=null, seq_auth=76, seq_label=76, icode="", resname="GLY"']);
  assert.deepEqual(plain(lib.ORIGINS.map(origin => lib.ORIGIN_LABEL[origin])), ["초기", "이어받음", "교차", "편집", "무작위"]);
  assert.deepEqual(plain(lib.EDIT_OPERATIONS.map(op => lib.EDIT_OP_LABEL[op])), ["추가", "교체", "이동", "삭제"]);
  assert.equal(lib.originText(GEN.individuals[2]), "편집(삭제)");
  assert.equal(lib.originText(GEN.individuals[1]), "교차");
  assert.equal(lib.originText(GEN.individuals[0]), "이어받음");
  assert.equal(lib.parentsText(GEN.individuals[1]), "부모 1-3 · 0-5");
  assert.equal(lib.parentsText(GEN.individuals[4]), "부모 1-3");
  assert.equal(lib.parentsText(GEN.individuals[5]), "");
  assert.equal(lib.evaluationText("reused"), "재사용");
  assert.equal(lib.evaluationText("computed"), "계산");
  assert.ok(lib.evaluationText(null).includes("다시 평가하지 않음"));
  assert.equal(lib.individualScoreText(GEN.individuals[0]), "-8.3");   // decimal-string ROUND_HALF_UP
  assert.equal(lib.individualScoreText(GEN.individuals[2]), "0.0");    // a real stored 0 is a number
  assert.equal(lib.individualScoreText(GEN.individuals[1]), "");
  assert.equal(lib.individualScoreText(GEN.individuals[3]), "");
  assert.equal(lib.individualReasonText(GEN.individuals[1]), lib.gaReasonText("model_timeout"));
  assert.ok(lib.individualReasonText(GEN.individuals[1]).includes("(model_timeout)"));
  assert.equal(lib.individualReasonText(GEN.individuals[0]), "");
  assert.equal(lib.stateText("null_result"), "빈 과학 결과(모드 0개) (null_result)");
  assert.equal(lib.individualDetailHandle(GEN.individuals[0]), "obj://r/docking_result/1-3");
  assert.equal(lib.individualDetailHandle(GEN.individuals[1]), null);
  assert.equal(lib.individualDetailHandle({ result_handle: "x", detail_available: false }), null);
  assert.equal(lib.generationRangeText(GEN), "점수 최솟값 -8.3 · 점수 최댓값 0.0 (kcal/mol)");
  assert.equal(lib.generationRangeText({ min_score: null, max_score: null }), "이 세대에 점수 있는 개체 없음");
  assert.equal(lib.generationTabText({ index: 3, complete: true }), "세대 3");
  assert.ok(lib.generationTabText({ index: 4, complete: false }).includes("중간에 멈춤"));
  assert.equal(lib.scoreHeaderText(), "qvina 점수(kcal/mol) · 모드 1(엔진 출력 순서)");
});

test("wild-type reference row: separate \"야생형 기준(참고)\" view with values only", () => {
  const scored = lib.referenceRowView({ evaluation: "computed", state: "scored", reason_code: null, score: -6.35,
    model_handle: "obj://r/mutation_set_model/w", result_handle: "obj://r/docking_result/w", detail_available: true });
  assert.equal(scored.title, "야생형 기준(참고)");
  assert.equal(scored.key, "wild_type");
  assert.equal(scored.score, "-6.4");
  assert.equal(scored.evaluation, "계산");
  assert.equal(scored.detailHandle, "obj://r/docking_result/w");
  assert.equal(scored.reason, "");
  assert.deepEqual(Object.keys(scored).sort(), ["detailHandle", "evaluation", "key", "note", "reason", "score", "state",
    "title"]);
  assert.equal(scored.note, lib.REFERENCE_NOTE);
  const failed = lib.referenceRowView({ evaluation: "computed", state: "failed", reason_code: "ligand_hydrogens_missing",
    score: null, model_handle: "obj://r/mutation_set_model/w", result_handle: null, detail_available: false });
  assert.equal(failed.score, "");
  assert.equal(failed.detailHandle, null);
  assert.equal(failed.reason, lib.gaReasonText("ligand_hydrogens_missing"));
  const nothing = lib.referenceRowView({ evaluation: "reused", state: "null_result", reason_code: null, score: null,
    model_handle: "m", result_handle: "r", detail_available: true });
  assert.equal(nothing.score, "");
  assert.equal(nothing.evaluation, "재사용");
  const text = [lib.REFERENCE_NOTE, ...Object.values(scored), ...Object.values(failed)].filter(item =>
    typeof item === "string").join("\n");
  assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
});

test("summary lines and list rows: stored values only", () => {
  const summary = Object.fromEntries(lib.gaSummaryLines({ status: "partial", stop_reason: "evaluation_limit",
    generations_done: 2, new_evaluations_used: 16, reused_count: 3, reserved_evaluations: 16, reserved_units: 34,
    space: { positions: 3, candidates: 6, effective_max_mutations: 3, size: 26 } }));
  assert.ok(summary["상태"].includes("(evaluation_limit)"));
  assert.equal(summary["완료한 세대"], "2개");
  assert.equal(summary["새 평가"], "16건 (예약 16건 · 34단위)");
  assert.equal(summary["재사용"], "3개 (과금하지 않음)");
  assert.equal(summary["조합 공간"], "위치 3개 · 후보 6개 · 조합 26개 · 유효 동시 변이 수 상한 3개");
  const list = lib.gaListRowText({ published_seq: 9, valid: true, reason_code: null, status: "complete",
    stop_reason: "space_exhausted", generations_done: 3, new_evaluations_used: 20, reused_count: 4 });
  assert.ok(list.includes("완료한 세대 3개") && list.includes("(space_exhausted)") && list.includes("새 평가 20건"), list);
  assert.ok(lib.gaListRowText({ published_seq: 9, valid: false, reason_code: "evidence_invalid", status: null,
    stop_reason: null, generations_done: null, new_evaluations_used: null, reused_count: null }).includes("읽을 수 없음"));
});

// ---- individual detail ----

const HIS68 = res(68, "HIS");
const energy = (before, after) => ({ before_kJ_mol: before, after_kJ_mol: after, unit: "kJ/mol", engine: "OpenMM",
  force_field: "amber14-all + implicit/gbn2", convergence: "convergence_not_claimed" });
const structureEntry = (patch = {}) => ({ structure_object: "obj://r/mutation_set_model_structure/aa",
  structure_sha256: "a".repeat(64), system_xml_sha256: "b".repeat(64), topology_sha256: "c".repeat(64),
  heavy_atoms: 605, added_hydrogens: 640, added_heavy_atoms: [], protonation_variants: [{ residue: HIS68,
    variant: "HIE" }], disulfide_bonds: [], energy: energy(-12345.678, -15000.125), ...patch });
const model = (mutations, side, patch = {}) => ({ schema: "mutation_set_model@1",
  method_version: "mw.mutation_set_model/v1", candidate_set: SET, structure: { handle: "obj://r/prepared_structure/p",
    model_number: 1, structure_kind: "prepared_structure" }, mutations, seed: 42, method: {},
  structures: { [side]: structureEntry(patch.entry) }, protonation_differences: [], new_disulfide_in_mutant: false,
  reference_structure_sha256: null, limitations: [lib.MODEL_LIMITATIONS[0], lib.MODEL_LIMITATIONS[1]], ...patch.top });
const TRP44 = { ...I44, resname: "TRP" };
const mutantModel = model([{ ...MUTS[0], mutant_resname: "ALA" }, { ...MUTS[3], mutant_resname: "TRP" }], "mutant", {
  entry: { added_heavy_atoms: [{ residue: TRP44, atom_name: "CD2", element: "C" },
    { residue: TRP44, atom_name: "NE1", element: "N" }],
  disulfide_bonds: [[res(10, "CYS"), res(20, "CYS")]] },
  top: { protonation_differences: [{ residue: HIS68, wild_type_reference: "HID", mutant: "HIE" }],
    new_disulfide_in_mutant: true, reference_structure_sha256: "d".repeat(64), limitations: [...lib.MODEL_LIMITATIONS] } });
const individualRead = (patch = {}) => ({ schema: "sequence_ga_individual@1",
  summary_handle: "obj://r/sequence_ga_result/h", key: "0-3", mutations: [MUTS[0], MUTS[3]], is_reference: false,
  eval_index: 2, pick_index: 11, evaluation: "computed", state: "scored", reason_code: null, score: -7.25,
  model_handle: "obj://r/mutation_set_model/0-3", result_handle: "obj://r/docking_result/0-3",
  appearances: [{ generation: 1, position: 3, origin: "initial" }, { generation: 2, position: 0, origin: "carried" }],
  model: mutantModel, statements: [statement("S5")], score_label: docking.SCORE_LABEL,
  score_row_label: "모드 1(엔진 출력 순서)", m18_detail: { schema: "docking_result_detail@1",
    handle: "obj://r/docking_result/0-3" }, ...patch });

test("individual detail: stored model values only (mutations, potentials with S5, HIS/CYS, disulfide, added atoms)", () => {
  const view = lib.individualDetailView(individualRead());
  assert.equal(view.title, "개체 0-3");
  assert.equal(view.key, "0-3");
  assert.deepEqual(plain(view.mutationLines), [
    "후보 번호 0 · LYS A:6 K→A (LYS → ALA) · " + mutationModel.residueFieldsText(K6),
    "후보 번호 3 · ILE A:44A I→W (ILE → TRP) · " + mutationModel.residueFieldsText(I44)]);
  assert.deepEqual(plain(view.appearanceLines), ["세대 1 · 자리 4 · 초기", "세대 2 · 자리 1 · 이어받음"]);
  assert.equal(view.score, "-7.3");
  assert.equal(view.state, lib.stateText("scored"));
  assert.equal(view.evaluation, "계산");
  assert.equal(view.structureLabel, "변이 구조 (mutant)");
  assert.deepEqual(plain(view.energyRows), [["OpenMM Amber14-all + GBn2 전위(kJ/mol) · 최소화 전", "-12345.68"],
    ["OpenMM Amber14-all + GBn2 전위(kJ/mol) · 최소화 후", "-15000.13"]]);
  assert.deepEqual(plain(view.energyStatements), [S.S5]);
  assert.deepEqual(plain(view.protonationVariantLines), ["HIS A:68 · HIE"]);
  assert.deepEqual(plain(view.protonationDifferenceRows), [{ residue: "HIS A:68",
    fields: mutationModel.residueFieldsText(HIS68), wild_type_reference: "HID", mutant: "HIE" }]);
  assert.equal(view.disulfideText, "CYS A:10–CYS A:20");
  assert.equal(view.newDisulfideText, "예 (new_disulfide_in_mutant)");
  assert.deepEqual(plain(view.addedAtomLines), ["TRP A:44A: 2개 (CD2 C, NE1 N)"]);
  assert.deepEqual(plain(view.countLines), [["중원자 수", "605"], ["pH 7.0에서 만든 수소 수", "640"]]);
  assert.deepEqual(plain(view.modelLimitations), plain(lib.MODEL_LIMITATIONS));
  assert.deepEqual(plain(view.unknownLimitations), []);
  assert.equal(view.structureAvailable, true);
  assert.equal(view.m18Handle, "obj://r/docking_result/0-3");
  assert.equal(view.missingModelText, null);
  const text = [view.title, ...view.mutationLines, ...view.appearanceLines, view.structureLabel,
    ...view.energyRows.flat(), ...view.protonationVariantLines, view.disulfideText, view.newDisulfideText,
    ...view.addedAtomLines, ...view.countLines.flat(), ...view.modelLimitations, ...view.energyStatements,
    lib.PROTONATION_DIFFERENCE_HEADING, ...lib.PROTONATION_DIFFERENCE_HEADERS].join("\n");
  assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
  // A stored sentence that is not one of the fixed ones is flagged (the screen must not trust it).
  const odd = lib.individualDetailView(individualRead({ model: { ...mutantModel, limitations: ["다른 문장"] } }));
  assert.deepEqual(plain(odd.unknownLimitations), ["다른 문장"]);
});

test("individual detail: the reference row and a row without a stored model show no numbers", () => {
  const reference = lib.individualDetailView(individualRead({ key: "wild_type", is_reference: true, mutations: [],
    eval_index: null, pick_index: null, appearances: [], model: model([], "wild_type_reference") }));
  assert.equal(reference.title, "야생형 기준(참고)");
  assert.deepEqual(plain(reference.mutationLines), []);
  assert.equal(reference.structureLabel, "야생형 기준 구조 (wild_type_reference)");
  assert.deepEqual(plain(reference.protonationDifferenceRows), []);
  assert.equal(reference.protonationDifferenceText, "해당 없음(야생형 기준 구조)");
  assert.equal(reference.newDisulfideText, "해당 없음(야생형 기준 구조)");
  assert.deepEqual(plain(reference.addedAtomLines), ["0개"]);
  const failed = lib.individualDetailView(individualRead({ state: "failed", reason_code: "coordinates_changed",
    score: null, model_handle: null, result_handle: null, model: null, m18_detail: null }));
  assert.equal(failed.score, "");
  assert.equal(failed.structureAvailable, false);
  assert.equal(failed.m18Handle, null);
  assert.deepEqual(plain(failed.energyRows), []);
  assert.deepEqual(plain(failed.countLines), []);
  assert.equal(failed.reason, lib.gaReasonText("coordinates_changed"));
  assert.ok(failed.missingModelText.includes("저장된 모델 없음") && failed.missingModelText.includes("(coordinates_changed)"),
    failed.missingModelText);
  const docked = lib.individualDetailView(individualRead({ state: "failed", reason_code: "docking_timeout", score: null,
    result_handle: null, m18_detail: null }));
  assert.equal(docked.structureAvailable, true);
  assert.equal(docked.m18Handle, null);
  assert.equal(docked.missingModelText, null);
});

// ---- late responses ----

test("late responses: applied only when run, summary handle, area and that area's request number all match", () => {
  let counters = lib.initialGaCounters();
  assert.deepEqual(Object.keys(counters), plain(lib.GA_AREAS));
  const first = lib.nextGaRequest(counters, "detail", "r", "h1");
  counters = first.counters;
  const second = lib.nextGaRequest(counters, "detail", "r", "h1");
  counters = second.counters;
  const individual = lib.nextGaRequest(counters, "individual", "r", "h1");
  counters = individual.counters;
  assert.equal(lib.gaResponseCurrent(first.stamp, second.stamp), false);
  assert.equal(lib.gaResponseCurrent(second.stamp, second.stamp), true);
  assert.equal(lib.gaResponseCurrent(second.stamp, { ...second.stamp, runId: "s" }), false);
  assert.equal(lib.gaResponseCurrent(second.stamp, { ...second.stamp, handle: "h2" }), false);
  assert.equal(lib.gaResponseCurrent(individual.stamp, { ...individual.stamp, area: "detail" }), false);
  assert.equal(lib.gaResponseCurrent({ ...second.stamp, runId: null }, { ...second.stamp, runId: null }), false);
  assert.equal(counters.detail, 2);
  assert.equal(counters.individual, 1);
  assert.equal(lib.gaReportSavedForRun(second.stamp, "r"), true);
  assert.equal(lib.gaReportSavedForRun(second.stamp, "s"), false);
});

// ---- report library ----

test("report library names the sequence GA report", () => {
  assert.equal(reportLibrary.reportKindLabel({ kind: "sequence_ga", handle: "h", target_handle: "s", created_seq: 1 }),
    "서열 GA 보고서");
});

// ---- wording ----

test("forbidden words: every string this module exports or builds passes; the check catches the banned words", () => {
  const strings = [];
  const collect = value => {
    if (typeof value === "string") strings.push(value);
    else if (Array.isArray(value)) value.forEach(collect);
    else if (value && typeof value === "object") Object.values(value).forEach(collect);
  };
  for (const value of Object.values(lib)) if (typeof value !== "function") collect(value);
  for (const key of lib.GA_KEYS) strings.push(lib.gaRangeText(key));
  strings.push(lib.chargeNote(5), lib.gaExistingJobText({ job_id: "j", status: "done" }), lib.scoreHeaderText(),
    lib.heavyAtomWarningText(5000), lib.checkGaInput(lib.initialGaInput()).errors.join("\n"),
    lib.checkGaInput(valid({ population_size: "5", elite_count: "4", max_new_evaluations: "4" })).errors.join("\n"),
    lib.gaArgs(lib.initialGaForm()).errors.join("\n"), ...lib.gaParameterLines(GA_DEFAULTS).flat(),
    lib.gaLimitApprovalText({ raised: true, increase: pair(1, 1), limits_after: pair(2, 2) }));
  for (const reason of lib.STOP_REASONS) strings.push(lib.stopReasonText(reason));
  for (const row of lib.individualRows(GEN)) strings.push(lib.originText(row), lib.parentsText(row),
    lib.evaluationText(row.evaluation), lib.stateText(row.state), lib.individualReasonText(row), lib.mutationsText(row.mutations));
  for (const text of strings) assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
  const banned = ["순위", "최고", "최적", "best", "rank", "improve", "개선", "승자", "추천", "야생형 대비", "부모 대비", "차이",
    "증감", "delta", "평균", "친화도가 높다", "안정성", "ΔΔG", "부분 완료", "효과"];
  for (const word of banned) assert.ok(lib.gaForbiddenWords(`개체 ${word}`).length > 0, word);
  assert.deepEqual(plain(lib.gaForbiddenWords("OpenMM으로 최소화한 모델")), []);   // 최적화/최소화 are processes
  // The exact score label (which says 친화도가 아님) and the fixed sentences are exempt; anything added is not.
  assert.deepEqual(plain(lib.gaForbiddenWords(lib.SCORE_LABEL)), []);
  assert.deepEqual(plain(lib.gaForbiddenWords(`${S.S1}\n${S.S5}\n${lib.MODEL_LIMITATIONS[2]}`)), []);
  assert.ok(lib.gaForbiddenWords(`${S.S1} 추가`).length > 0);
  // The module source itself never says rank / best / improvement outside the wording check.
  const outside = LIB_SOURCE.slice(0, LIB_SOURCE.indexOf("// ---- wording check"));
  assert.ok(!/\b(rank|best|improv|winner|delta)\w*/i.test(outside.replace(/\/\/.*$|\/\*[\s\S]*?\*\//gm, "")), "source");
});

// ---- T8: the "서열 GA 설계" area (the pure logic it added, a server render of the component, source checks) ----

test("area state: five states; no run, no usable capability or no readable candidate set is a reason only", () => {
  const capability = { available: true, reason: null, reason_code: null };
  const state = input => plain(lib.gaAreaState({ runId: "r", capability, candidateSets: [{ valid: true }],
    summaries: [], ...input }));
  assert.deepEqual(state({ runId: null }), { state: "unavailable", reason: lib.NO_RUN_REASON });
  assert.deepEqual(state({ capability: undefined }), { state: "loading" });
  assert.deepEqual(state({ capability: null }), { state: "unavailable", reason: lib.CAPABILITY_REASON });
  const off = state({ capability: { available: false, reason: "PDBFixer가 없음", reason_code: "pdbfixer_unavailable" } });
  assert.equal(off.state, "unavailable");
  assert.ok(off.reason.includes("(pdbfixer_unavailable)"), off.reason);
  for (const candidateSets of [[], [{ valid: false }]])
    assert.deepEqual(state({ candidateSets }), { state: "unavailable", reason: lib.NO_CANDIDATE_SET_REASON });
  assert.deepEqual(state({ candidateSets: undefined }), { state: "loading" });
  assert.deepEqual(state({ summaries: undefined }), { state: "loading" });
  assert.deepEqual(state({ loading: true }), { state: "loading" });
  assert.deepEqual(state({ error: "읽기 실패" }), { state: "failed", message: "읽기 실패" });
  assert.deepEqual(state({}), { state: "empty", message: lib.NO_SUMMARIES_TEXT });
  assert.deepEqual(state({ detailOpen: true }), { state: "ready" });
  assert.deepEqual(state({ summaries: [{}] }), { state: "ready" });
  const job = (status, summaryHandle = null) => ({ status, cancel_requested: false,
    failure: { error: "fatal", message: "boom", reason_code: "worker_failed" },
    sequence_ga: { summary_handle: summaryHandle, summary_status: summaryHandle ? "partial" : null,
      summary_stop_reason: summaryHandle ? "worker_failed" : null } });
  for (const status of ["queued", "claimed", "running"])
    assert.deepEqual(state({ job: job(status), summaries: [{}] }), { state: "loading" }, status);
  const failed = state({ job: job("failed") });
  assert.equal(failed.state, "failed");
  assert.ok(failed.message.includes("(worker_failed)"), failed.message);
  assert.equal(state({ job: job("cancelled") }).state, "failed");
  // A job that ended but published a summary is not an area failure: the summary carries its own outcome.
  assert.deepEqual(state({ job: job("failed", "obj://r/sequence_ga_result/h"), summaries: [{}] }), { state: "ready" });
  assert.deepEqual(Object.keys(lib.GA_STATE_TEXT), ["loading", "ready", "empty", "failed", "unavailable"]);
});

test("one GA at a time: another summary cannot be opened while a GA request is in flight or a GA job runs", () => {
  assert.equal(lib.gaSwitchBlockedReason({ busy: false, job: null }), null);
  assert.equal(lib.gaSwitchBlockedReason({ busy: true, job: null }), lib.SUMMARY_SWITCH_BLOCKED_REASON);
  for (const status of ["queued", "claimed", "running"])
    assert.equal(lib.gaSwitchBlockedReason({ busy: false, job: { status } }), lib.SUMMARY_SWITCH_BLOCKED_REASON, status);
  for (const status of ["done", "failed", "cancelled", "interrupted"])
    assert.equal(lib.gaSwitchBlockedReason({ busy: false, job: { status } }), null, status);
});

test("late-response areas: summary areas carry the opened summary handle, run-wide areas carry none", () => {
  for (const area of ["candidate_sets", "prereq", "preflight", "limit", "job", "cancel", "list", "detail", "individual",
    "report", "report_list"]) assert.ok(lib.GA_AREAS.includes(area), area);
  assert.deepEqual(plain(lib.SUMMARY_AREAS), ["detail", "individual", "report", "report_list"]);
  for (const area of lib.GA_AREAS)
    assert.equal(lib.gaStampHandle(area, "h1"), lib.SUMMARY_AREAS.includes(area) ? "h1" : null, area);
  // A row's detail answer for summary h1 is stale once h2 is opened; the candidate-set list is not tied to it.
  const row = lib.nextGaRequest(lib.initialGaCounters(), "individual", "r", lib.gaStampHandle("individual", "h1"));
  assert.equal(lib.gaResponseCurrent(row.stamp, { ...row.stamp, handle: lib.gaStampHandle("individual", "h2") }), false);
  const sets = lib.nextGaRequest(row.counters, "candidate_sets", "r", lib.gaStampHandle("candidate_sets", "h1"));
  assert.equal(lib.gaResponseCurrent(sets.stamp, { ...sets.stamp, handle: lib.gaStampHandle("candidate_sets", "h2") }),
    true);
});

test("space lines and score cells: the server's space numbers only; a row without a score shows — (never 0)", () => {
  assert.deepEqual(plain(lib.gaSpaceLines(preflight())), plain(lib.gaPreflightLines(preflight()).slice(0, 2)));
  assert.deepEqual(plain(lib.gaSpaceLines(preflight()).map(([label]) => label)), ["조합 공간", "유효 동시 변이 수 상한"]);
  assert.deepEqual(plain(lib.gaSpaceLines(null)), []);
  assert.deepEqual(plain(lib.gaSpaceLines(refusal("input_invalid", "ga_space_too_small", "m", {}))), []);
  assert.ok(lib.SPACE_PENDING_TEXT.includes("서버"));
  assert.equal(lib.scoreCellText({ state: "scored", score: -7.25 }), "-7.3");
  assert.equal(lib.scoreCellText({ state: "scored", score: 0 }), "0.0");   // a real stored 0 is a number
  for (const state of ["null_result", "failed"]) assert.equal(lib.scoreCellText({ state, score: null }), "—", state);
  assert.equal(lib.scoreCellText({ state: "failed", score: -99 }), "—");
  for (const text of [lib.SPACE_PENDING_TEXT, lib.NO_SUMMARIES_TEXT, lib.SUMMARY_SWITCH_BLOCKED_REASON,
    ...Object.values(lib.GA_STATE_TEXT)]) assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
});

// The real components, compiled from source and rendered on the server (effects do not run: no request is made).
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
function compileTsx(relativePath, dependencies) {
  const source = fs.readFileSync(path.join(__dirname, relativePath), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const moduleObject = { exports: {} };
  vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports,
    require: name => dependencies[name] ?? require(name) });
  return moduleObject.exports;
}
const ligandLib = load("ligand", { "./site-annotation": siteAnnotation });
const primitives = compileTsx("../src/components/primitives.tsx", { "@/lib/contracts": load("contracts") });
const noRequest = () => { throw new Error("a server render makes no request"); };
const apiStub = { api: new Proxy({}, { get: () => noRequest }), ApiError: class ApiError extends Error {} };
const modelPanel = compileTsx("../src/components/MutationModelPanel.tsx", { "@/lib/api": apiStub,
  "@/lib/docking": docking, "@/lib/ligand": ligandLib, "@/lib/mutation-model": mutationModel,
  "./primitives": primitives });
// M26: the panel shows the shared "촉매 잔기 검사 안 함" mark of a candidate set (lib/mutations `catalyticBadge`).
const mutationsLib = load("mutations", { "./site-annotation": siteAnnotation, "./event-model": load("event-model") });
const gaPanel = compileTsx("../src/components/SequenceGaPanel.tsx", { "@/lib/api": apiStub, "@/lib/docking": docking,
  "@/lib/ligand": ligandLib, "@/lib/mutations": mutationsLib, "@/lib/sequence-ga": lib,
  "@/lib/site-annotation": siteAnnotation, "./MutationModelPanel": modelPanel, "./primitives": primitives });
const RUN = { run_id: "fixture-run", goal: "", context: [], dry_run: false, egress: "local_only", last_seq: 1 };
const CAPABILITY = { schema: "sequence_ga_capability@1", protocol_id: "sequence_ga_dock_v1", tool_id: "sequence_ga_design",
  engine: "qvina", execution_lane: "expensive", result_schema: "sequence_ga_result@1", model_schema: "mutation_set_model@1",
  available: true, status: "available", reason_code: null, reason: null, pins: null, versions: null };
const renderPanel = props => renderToStaticMarkup(React.createElement(gaPanel.SequenceGaPanel,
  { run: RUN, capability: CAPABILITY, onReportCreated: () => undefined, ...props }));
const decode = text => text.replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
  .replace(/&amp;/g, "&");
/** Visible text, one text node per line (tags and React's text separators split lines). */
const textLines = html => decode(html.replace(/<[^>]+>/g, "\n")).split("\n").map(line => line.trim()).filter(Boolean);
const tagOf = (html, testId) => new RegExp(`<[a-z]+ [^>]*data-testid="${testId}"[^>]*>`).exec(html)?.[0] ?? "";
const innerOf = (html, tag, testId) =>
  new RegExp(`<${tag}[^>]*data-testid="${testId}"[^>]*>([\\s\\S]*?)</${tag}>`).exec(html)?.[1] ?? null;
const selectedOptions = inner => [...inner.matchAll(/<option[^>]*selected=""[^>]*>([^<]*)</g)].map(match => match[1]);

test("initial render: nothing chosen, submitted or approved; preflight and start are blocked with the reasons", () => {
  const html = renderPanel({});
  assert.match(tagOf(html, "sequence-ga-panel"), /data-ga-state="loading"/);
  // No M20 candidate set and no ligand SDF is chosen ("선택" only).
  assert.deepEqual(selectedOptions(innerOf(html, "select", "sequence-ga-candidate-set")), ["선택"]);
  assert.deepEqual(selectedOptions(innerOf(html, "select", "sequence-ga-sdf")), ["선택"]);
  // The two literals and the three M18 acknowledgements are unchecked; no box source is chosen.
  for (const id of ["sequence-ga-confirm-selection", "sequence-ga-confirm-hydrogen"])
    assert.ok(tagOf(html, id) && !/checked/.test(tagOf(html, id)), id);
  assert.ok(!/checked/.test(innerOf(html, "fieldset", "sequence-ga-acknowledgement")));
  assert.equal((innerOf(html, "fieldset", "sequence-ga-acknowledgement").match(/type="checkbox"/g) ?? []).length, 3);
  const box = innerOf(html, "fieldset", "sequence-ga-box-source");
  assert.ok(!/checked/.test(box));
  assert.match(box, /data-pair-box="instance_range" data-disabled-reason="[^"]+"/);
  // The ligand is a 3D SDF only: the M17 candidate source is disabled with the reason (the SDF itself is not chosen).
  const ligand = innerOf(html, "fieldset", "sequence-ga-ligand-source");
  assert.ok(ligand.includes(`data-disabled-reason="${lib.SDF_ONLY_REASON.replace(/"/g, "&quot;")}"`));
  assert.match(ligand, /name="sequence-ga-source-fixture-run" checked=""/);
  // GA parameters: every default prefilled, the GA seed and the evaluation seed empty (required, no default).
  assert.match(tagOf(html, "sequence-ga-param-seed"), /value=""/);
  for (const key of lib.GA_KEYS.filter(key => key !== "seed"))
    assert.match(tagOf(html, `sequence-ga-param-${key}`), new RegExp(`value="${lib.GA_RANGES[key][2]}"`), key);
  assert.match(tagOf(html, "sequence-ga-seed"), /value=""/);
  // Preflight and start are disabled and say why; no approval, limit raise, job or result control exists.
  assert.match(tagOf(html, "sequence-ga-preflight"), /disabled=""/);
  assert.match(tagOf(html, "sequence-ga-start"), /disabled=""/);
  const blocked = textLines(innerOf(html, "span", "sequence-ga-start-blocked") ?? "").join(" ");
  assert.ok(blocked.includes("confirmation_missing") && blocked.includes("acknowledgement_missing"), blocked);
  for (const id of ["sequence-ga-limit-approve", "sequence-ga-job-approve", "sequence-ga-job-start", "sequence-ga-job",
    "sequence-ga-job-cancel", "sequence-ga-result", "sequence-ga-individual", "sequence-ga-preflight-view"])
    assert.ok(!html.includes(`data-testid="${id}"`), id);
  // The combination space is the server's: nothing is shown for it before a preflight answers.
  assert.ok(textLines(html).includes(lib.SPACE_PENDING_TEXT));
  assert.equal(tagOf(html, "sequence-ga-space").includes("data-space-size"), false);
  // Wording, test-id prefix (the reused M21 inputs included), no viewer markup.
  assert.deepEqual(plain(lib.gaForbiddenWords(textLines(html).join("\n"))), []);
  const ids = [...html.matchAll(/data-testid="([^"]+)"/g)].map(match => match[1]);
  assert.ok(ids.length > 40, String(ids.length));
  for (const id of ids) assert.ok(id.startsWith("sequence-ga-"), id);
  assert.ok(!/molstar|<canvas/i.test(html));
});

test("gate renders: no run, capability absent or unavailable, capabilities not read: reason only, no controls", () => {
  const unavailable = { ...CAPABILITY, available: false, status: "unavailable", reason: "PDBFixer가 없음",
    reason_code: "pdbfixer_unavailable" };
  for (const [props, id, state] of [[{ run: null }, "sequence-ga-no-run", "unavailable"],
    [{ capability: null }, "sequence-ga-unavailable", "unavailable"],
    [{ capability: unavailable }, "sequence-ga-unavailable", "unavailable"], [{ capability: undefined }, null, "loading"]]) {
    const html = renderPanel(props);
    assert.match(tagOf(html, "sequence-ga-panel"), new RegExp(`data-ga-state="${state}"`), id);
    if (id) assert.ok(html.includes(`data-testid="${id}"`), id);
    assert.ok(!/<(input|select|button|table|a) /.test(html), html);
    const text = textLines(html).join("\n");
    assert.ok(!/\d/.test(text), text);
    assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
  }
  assert.ok(renderPanel({ capability: unavailable }).includes("(pdbfixer_unavailable)"));
  assert.ok(textLines(renderPanel({ run: null })).join(" ").includes(lib.NO_RUN_REASON));
});

test("M21 PairInputs: the defaults keep the M21 markup; the GA passes its own prefix, names, reason and labels", () => {
  const props = { form: { ...mutationModel.initialPairDockingForm(), ligandSource: "sdf", boxSource: "manual" },
    update: () => undefined, runId: "r", prereq: { status: "idle" }, onReloadPrereq: () => undefined,
    ligandSdfs: [{ handle: "obj://r/chemical_raw_input/s", input_kind: "ligand_sdf", input_format: "sdf", size: 10,
      sha256: null, created_seq: 3 }] };
  const m21 = renderToStaticMarkup(React.createElement(modelPanel.PairInputs, props));
  const ga = renderToStaticMarkup(React.createElement(modelPanel.PairInputs, { ...props, idPrefix: "sequence-ga",
    ligandSourceReason: lib.ligandSourceDisabledReason, seedLabel: "평가 seed", acknowledgementLegend: "확인 세 항목" }));
  const idsOf = html => [...html.matchAll(/data-testid="([^"]+)"/g)].map(match => match[1]);
  const m21Ids = idsOf(m21);
  assert.deepEqual(m21Ids.slice(0, 4), ["mutation-model-pair-form", "mutation-model-pair-prereq-refresh",
    "mutation-model-pair-ligand-source", "mutation-model-pair-sdf"]);
  for (const id of m21Ids) assert.ok(id.startsWith("mutation-model-pair-"), id);
  assert.deepEqual(idsOf(ga), m21Ids.map(id => id.replace("mutation-model-pair-", "sequence-ga-")));
  assert.ok(m21.includes('name="mutation-model-pair-source-r"') && m21.includes('name="mutation-model-pair-box-r"'));
  assert.ok(ga.includes('name="sequence-ga-source-r"') && ga.includes('name="sequence-ga-box-r"') &&
    !ga.includes("mutation-model-pair"));
  assert.ok(textLines(m21).includes("제출 전 확인 (세 항목 모두, 두 작업에 같이 적용)"));
  assert.ok(textLines(m21).join("").includes("seed (필수, 0–2147483647)"));
  assert.ok(decode(m21).includes(mutationModel.PAIR_SDF_ONLY_REASON) && decode(ga).includes(lib.SDF_ONLY_REASON));
  assert.ok(textLines(ga).includes("확인 세 항목") && textLines(ga).includes("평가 seed"));
});

test("panel source: rendered literals pass the wording check; test ids prefixed; requests only on a person's action", () => {
  const file = path.join(__dirname, "../src/components/SequenceGaPanel.tsx");
  const source = fs.readFileSync(file, "utf8");
  const sourceFile = ts.createSourceFile(file, source, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
  const texts = [], effects = [], ids = [];
  const visit = node => {
    if (ts.isJsxText(node) && node.text.trim()) texts.push(node.text.trim());
    else if (ts.isStringLiteral(node) && !ts.isImportDeclaration(node.parent)) texts.push(node.text);
    else if (ts.isNoSubstitutionTemplateLiteral(node)) texts.push(node.text);
    else if (ts.isTemplateExpression(node)) texts.push(node.head.text, ...node.templateSpans.map(span => span.literal.text));
    if (ts.isCallExpression(node) && node.expression.getText(sourceFile) === "useEffect")
      effects.push(node.arguments[0].getText(sourceFile));
    if (ts.isJsxAttribute(node) && ["data-testid", "testId", "idPrefix"].includes(node.name.getText(sourceFile))) {
      const value = node.initializer;
      if (value && ts.isStringLiteral(value)) ids.push(value.text);
      else if (value && ts.isJsxExpression(value) && value.expression) {
        const expression = value.expression;
        if (ts.isTemplateExpression(expression)) ids.push(expression.head.text);
        else if (ts.isConditionalExpression(expression)) ids.push(expression.whenTrue.text, expression.whenFalse.text);
        else ids.push(`<${expression.getText(sourceFile)}>`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  // Every literal the component can render (text, attributes, templates) passes the M23 wording check.
  assert.ok(texts.length > 150, String(texts.length));
  for (const text of texts) assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
  assert.ok(!/dangerouslySetInnerHTML|innerHTML/.test(source));
  // Every test id carries the area prefix; the only other form is the ErrorLine / Facts pass-through.
  for (const id of ids) assert.ok(id === "<testId>" || id === "sequence-ga" || id.startsWith("sequence-ga-"), id);
  assert.ok(ids.length > 60, String(ids.length));
  // Effects (mount = entering the tab, polling, a finished job) only read: no submit, start, approval, preflight,
  // limit raise, report or cancel, and nothing is opened or chosen by itself.
  assert.ok(effects.length >= 8, String(effects.length));
  const reads = new Set(["mutationCandidateSets", "dockingPrerequisites", "sequenceGaResults", "sequenceGaJobs",
    "sequenceGaJob", "reports"]);
  for (const body of effects) {
    for (const match of body.matchAll(/api\.(\w+)\(/g)) assert.ok(reads.has(match[1]), match[1]);
    assert.ok(!/\b(submit|start|approveLimits|approveFirstCall|cancelJob|makeReport|runPreflight|openSummary|openIndividual|setSelected|update)\(/
      .test(body), body);
    assert.ok(!/candidateSet:|sdfHandle:|boxSource:|acknowledgement:/.test(body), body);
  }
  // Each writing request has one call site, reached from a person's click (start also right after that click's submit).
  for (const name of ["submitSequenceGa", "sequenceGaLimitApproval", "approveOpenmm", "createSequenceGaReport",
    "cancelJob", "startJob", "sequenceGaPreflight"])
    assert.equal([...source.matchAll(new RegExp(`api\\.${name}\\(`, "g"))].length, 1, name);
  assert.ok(source.includes("if (!check.ok || !gaLimitApprovalOffered(shownPreflight, run.dry_run)) return;"));
  for (const name of ["submit", "approveLimits", "approveFirstCall", "cancelJob", "makeReport"])
    assert.equal([...source.matchAll(new RegExp(`onClick=\\{\\(\\) => void ${name}\\(\\)\\}`, "g"))].length, 1, name);
  assert.ok(/<Button size="sm" data-testid="sequence-ga-limit-approve"/.test(source));
  // Values are shown through the view models only: no arithmetic on scores, potentials or counts here.
  assert.ok(!/\.score\s*[-+*/<>]|Math\./.test(source));
  assert.ok(/scoreCellText\(row\)/.test(source) && /individualDetailView\(read\)/.test(source));
  // No viewer, saved view or bridge.
  assert.ok(!/MolstarViewer|molstar|viewer-agent|saved-scene|captureScene/.test(source));
  // The area reuses the M21 inputs with its own prefix and the 3D-SDF-only reason.
  assert.ok(/<PairInputs form=\{form\} update=\{update\}/.test(source) && /idPrefix="sequence-ga"/.test(source) &&
    /ligandSourceReason=\{ligandSourceDisabledReason\}/.test(source));
});

test("page and existing areas: mounted after the M21 area in the protein tab; tabs and other areas unchanged", () => {
  const page = fs.readFileSync(path.join(__dirname, "../app/page.tsx"), "utf8");
  const protein = page.indexOf("protein={<>"), ligand = page.indexOf("ligand={<>");
  const m20 = page.indexOf("<MutationPanel "), m21 = page.indexOf("<MutationModelPanel "), m23 = page.indexOf("<SequenceGaPanel ");
  assert.ok(protein > 0 && protein < m20 && m20 < m21 && m21 < m23 && m23 < ligand, [protein, m20, m21, m23, ligand].join());
  assert.ok(page.includes("<SequenceGaPanel key={`sequence-ga-${run?.run_id ?? \"none\"}`} run={run}"));
  assert.ok(/capability=\{capabilities \? capabilities\.methods\?\.sequence_ga_design \?\? null : undefined\}/.test(page));
  assert.ok(page.includes('import { SequenceGaPanel } from "@/components/SequenceGaPanel";'));
  // The tab shell and the shared component surface do not change; panels are imported by path as before.
  const tabs = fs.readFileSync(path.join(__dirname, "../src/components/WorkspaceTabs.tsx"), "utf8");
  assert.ok(!/sequence/i.test(tabs));
  const index = fs.readFileSync(path.join(__dirname, "../src/components/index.ts"), "utf8");
  assert.ok(!/Panel/.test(index));
  // The M21 area keeps its exports and still renders its inputs with the defaults (same markup as before).
  const model = fs.readFileSync(path.join(__dirname, "../src/components/MutationModelPanel.tsx"), "utf8");
  assert.ok(/export function MutationModelPanel\(/.test(model) && /export interface ModelStartRequest /.test(model) &&
    /export interface MutationModelPanelProps /.test(model));
  assert.ok(/<PairInputs form=\{pairForm\} update=\{updatePair\} runId=\{runId\} prereq=\{prereq\} ligandSdfs=\{ligandSdfs\}\n\s+onReloadPrereq=\{\(\) => setPrereqReload\(value => value \+ 1\)\} \/>/
    .test(model));
});
