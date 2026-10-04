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
const docking = load("docking", { "./site-annotation": siteAnnotation });
const batch = load("docking-batch", { "./docking": docking, "./site-annotation": siteAnnotation });
const lib = load("ligand-ga", { "./docking": docking, "./site-annotation": siteAnnotation });
const plain = value => JSON.parse(JSON.stringify(value));

// ---- closed sets, ranges, limits and fixed wording are read from backend/mw/ligand_ga_constants.py itself ----
const constantsSource = fs.readFileSync(path.join(__dirname, "../../backend/mw/ligand_ga_constants.py"), "utf8");
function backendTuple(name) {
  const match = new RegExp(`^${name} = \\(([^)]*)\\)`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map(item => item[1]);
}
function backendNumber(name) {
  const match = new RegExp(`^${name} = ([0-9_]+)`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return Number(match[1].replace(/_/g, ""));
}
function backendString(name) {
  const match = new RegExp(`^${name} = "([^"]+)"`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return match[1];
}
function backendBlock(name) {
  const start = constantsSource.indexOf(`\n${name} = {`);
  assert.ok(start >= 0, `backend constant ${name} not found`);
  return constantsSource.slice(start + name.length + 5, constantsSource.indexOf("\n}", start));
}
function backendStringDict(name) {
  const block = backendBlock(name).replace(/"\s*\n\s*"/g, "");
  return Object.fromEntries([...block.matchAll(/"([^"]+)":\s*"([^"]+)"/g)].map(item => [item[1], item[2]]));
}
function backendRanges() {
  const block = backendBlock("GA_RANGES");
  return Object.fromEntries([...block.matchAll(/"([a-z_]+)":\s*\(([^)]*)\)/g)].map(item => [item[1],
    item[2].split(",").map(text => text.trim()).map(text => text === "None" ? null : Number(text))]));
}

const G = {
  G1: "GA는 후보 풀에서 어디를 도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 순위나 추천이 아니다. 부모·유사 후보 연결은 작업 모듈 기록이며 서버가 다시 계산하지 않았다.",
  G2: "이 실행은 시간·도킹 상한·취소 등으로 일부 세대만 계산되었다. 계산하지 않은 개체는 점수가 없으며 0이 아니고, 한도 도달로 멈춘 실행은 같은 설정으로 다시 해도 같은 경로를 보장하지 않는다.",
  G3: "재사용한 개체는 같은 수용체·상자·seed·방식·값으로 이전에 저장된 도킹 결과를 가져온 것이며, 저장된 결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있다.",
};

test("closed sets, ranges, limits and G1–G3 equal backend/mw/ligand_ga_constants.py", () => {
  assert.equal(lib.GA_PROTOCOL, backendString("PROTOCOL"));
  assert.equal(lib.GA_TOOL, backendString("TOOL"));
  assert.deepEqual(plain(lib.GA_KEYS), backendTuple("GA_KEYS"));
  assert.deepEqual(plain(lib.GA_FLOAT_KEYS), backendTuple("GA_FLOAT_KEYS"));
  assert.deepEqual(plain(lib.GA_RANGES), backendRanges());
  for (const name of ["ADMISSION_REASONS", "STOP_REASONS", "ORIGINS", "EVALUATIONS", "STATES",
    "FAILED_EXTRA_REASONS"]) assert.deepEqual(plain(lib[name]), backendTuple(name), name);
  assert.deepEqual(plain(lib.GA_STATUSES), backendTuple("STATUSES"));
  assert.deepEqual(plain(lib.STATUS_BY_STOP_REASON), backendStringDict("STATUS_BY_STOP_REASON"));
  for (const name of ["MIN_NEW_SLOTS", "PER_CANDIDATE_S", "MAX_NEW_DOCKINGS", "FINISH_MARGIN_S", "TIMEOUT_MAX_S",
    "MAX_POOL"]) assert.equal(lib[name], backendNumber(name), name);
  assert.equal(lib.TOTAL_S_MAX, backendNumber("TOTAL_S_MAX"));
  assert.equal(lib.TIMEOUT_MAX_S, lib.TOTAL_S_MAX + lib.FINISH_MARGIN_S);
  assert.equal(lib.SCORE_ROW_LABEL, backendString("SCORE_ROW_LABEL"));
  assert.equal(lib.SCORE_ROW_LABEL, batch.SCORE_ROW_LABELS.free);
  assert.equal(lib.SCORE_COLUMN_LABEL, docking.SCORE_COLUMN_LABEL);
  assert.equal(lib.SCORE_LABEL, docking.SCORE_LABEL);
  // G1–G3: verbatim, in order, identical to the backend constants and to the spec text.
  const backendStatements = backendStringDict("STATEMENTS");
  assert.deepEqual(Object.keys(backendStatements), ["G1", "G2", "G3"]);
  assert.deepEqual(plain(lib.GA_STATEMENTS), backendStatements);
  assert.deepEqual(plain(lib.GA_STATEMENTS), G);
  // The API client sends timeout_s = ga.total_s + the finishing margin, with the GA protocol id.
  const apiSource = fs.readFileSync(path.join(__dirname, "../src/lib/api.ts"), "utf8");
  assert.equal(Number(/^export const LIGAND_GA_FINISH_MARGIN_S = (\d+);/m.exec(apiSource)?.[1]), lib.FINISH_MARGIN_S);
  assert.ok(apiSource.includes('protocol_id: "qvina_ga_dock_v1", args,\n      timeout_s: args.ga.total_s + ' +
    "LIGAND_GA_FINISH_MARGIN_S"));
});

// ---- parameters ----

test("parameter definitions: every key with Korean label, range and default; seed has no default", () => {
  assert.deepEqual(plain(lib.GA_PARAMETERS.map(item => item.key)), plain(lib.GA_KEYS));
  for (const item of lib.GA_PARAMETERS) {
    assert.ok(/[가-힣]/.test(item.label), item.key);
    assert.equal(item.integer, item.key !== "random_fraction", item.key);
    assert.deepEqual([item.min, item.max, item.default], plain(lib.GA_RANGES[item.key]));
  }
  assert.equal(lib.gaRangeText("seed"), "0–2147483647 · 기본 없음(필수)");
  assert.equal(lib.gaRangeText("population_size"), "4–24 개 · 기본 12");
  assert.equal(lib.gaRangeText("random_fraction"), "0–0.5 · 기본 0.2");
  assert.equal(lib.gaRangeText("max_new_dockings"), "세대당 개체 수–100 건 · 기본 60");
  assert.equal(lib.gaRangeText("total_s"), "600–14400 초 · 기본 7200");
  const input = lib.initialGaInput();
  assert.deepEqual(plain(input), { seed: "", population_size: "12", generations: "5", elite_count: "2",
    tournament_size: "2", neighbor_count: "10", random_fraction: "0.2", patience: "3", max_new_dockings: "60",
    total_s: "7200" });
  assert.deepEqual(plain(lib.resetGaDefaults({ ...input, seed: "17", population_size: "20" })),
    { ...plain(input), seed: "17" });
});

const valid = (patch = {}) => ({ ...lib.initialGaInput(), seed: "7", ...patch });

test("validator: defaults plus a seed pass, values are numbers, every range boundary is inclusive", () => {
  const check = lib.checkGaInput(valid());
  assert.equal(check.ok, true);
  assert.deepEqual(plain(check.ga), { seed: 7, population_size: 12, generations: 5, elite_count: 2,
    tournament_size: 2, neighbor_count: 10, random_fraction: 0.2, patience: 3, max_new_dockings: 60, total_s: 7200 });
  const ints = { seed: [0, 2147483647], generations: [1, 8], tournament_size: [2, 4], neighbor_count: [3, 30],
    patience: [1, 8], total_s: [600, 14400] };
  for (const [key, [low, high]] of Object.entries(ints)) {
    for (const value of [low, high]) assert.equal(lib.checkGaInput(valid({ [key]: String(value) })).ok, true, key);
    for (const value of [low - 1, high + 1]) {
      const bad = lib.checkGaInput(valid({ [key]: String(value) }));
      assert.equal(bad.ok, false, `${key}=${value}`);
      assert.ok(bad.fields[key].includes("(invalid_job_arguments)"), key);
      for (const other of lib.GA_KEYS) if (other !== key) assert.equal(bad.fields[other], null, `${key} -> ${other}`);
    }
  }
  // population_size 4..24 (max_new_dockings and elite_count kept consistent).
  assert.equal(lib.checkGaInput(valid({ population_size: "4", elite_count: "2" })).ok, true);
  assert.equal(lib.checkGaInput(valid({ population_size: "24", max_new_dockings: "24" })).ok, true);
  assert.equal(lib.checkGaInput(valid({ population_size: "3", elite_count: "0" })).fields.population_size !== null, true);
  assert.equal(lib.checkGaInput(valid({ population_size: "25", max_new_dockings: "100" })).ok, false);
  // elite_count 0..4; max_new_dockings ..100.
  assert.equal(lib.checkGaInput(valid({ elite_count: "0" })).ok, true);
  assert.equal(lib.checkGaInput(valid({ elite_count: "4" })).ok, true);
  assert.equal(lib.checkGaInput(valid({ elite_count: "5" })).ok, false);
  assert.equal(lib.checkGaInput(valid({ max_new_dockings: "100" })).ok, true);
  assert.equal(lib.checkGaInput(valid({ max_new_dockings: "101" })).ok, false);
  // random_fraction: a finite real 0..0.5.
  for (const text of ["0", "0.0", "0.5", "0.25", "5e-1"]) assert.equal(lib.checkGaInput(valid({ random_fraction: text })).ok,
    true, text);
  for (const text of ["0.51", "-0.1", "", "abc", "Infinity", "NaN", "0x1", ".2", "1/5"])
    assert.equal(lib.checkGaInput(valid({ random_fraction: text })).ok, false, text);
  assert.equal(lib.checkGaInput(valid({ random_fraction: " 0.3 " })).ga.random_fraction, 0.3);
});

test("validator guards: integers only (no decimals, signs, blanks, exponents), seed required", () => {
  for (const text of ["", " ", "1.0", "+3", "-1", "3e0", "0x10", "07", "abc", "1 2", "9007199254740993"])
    assert.equal(lib.checkGaInput(valid({ population_size: text })).fields.population_size !== null, true, text);
  const noSeed = lib.checkGaInput(lib.initialGaInput());
  assert.equal(noSeed.ok, false);
  assert.ok(noSeed.fields.seed.includes("(필수)"));
  assert.deepEqual(plain(noSeed.errors), [noSeed.fields.seed]);
  assert.equal(lib.checkGaInput(valid({ seed: "2147483648" })).ok, false);
});

test("cross rules: population_size − elite_count ≥ 2 and max_new_dockings ≥ population_size", () => {
  const elite = lib.checkGaInput(valid({ population_size: "5", elite_count: "4" }));
  assert.equal(elite.ok, false);
  assert.ok(elite.fields.elite_count.includes("2 이상"), elite.fields.elite_count);
  assert.equal(elite.fields.population_size, null);
  assert.equal(lib.checkGaInput(valid({ population_size: "6", elite_count: "4" })).ok, true);
  assert.equal(lib.checkGaInput(valid({ population_size: "4", elite_count: "3" })).ok, false);
  const cap = lib.checkGaInput(valid({ population_size: "20", max_new_dockings: "19" }));
  assert.equal(cap.ok, false);
  assert.ok(cap.fields.max_new_dockings.includes("세대당 개체 수(20) 이상"), cap.fields.max_new_dockings);
  assert.equal(lib.checkGaInput(valid({ population_size: "20", max_new_dockings: "20" })).ok, true);
  // max_new_dockings 4 is the absolute minimum (= the smallest population size).
  assert.equal(lib.checkGaInput(valid({ population_size: "4", max_new_dockings: "4" })).ok, true);
  assert.equal(lib.checkGaInput(valid({ population_size: "4", max_new_dockings: "3" })).fields.max_new_dockings !== null,
    true);
  // A field already out of range is not reported twice through a cross rule.
  const both = lib.checkGaInput(valid({ population_size: "abc", elite_count: "9" }));
  assert.equal(both.errors.length, 2);
  // Errors keep the GA key order.
  const many = lib.checkGaInput(valid({ seed: "", total_s: "1", population_size: "6", elite_count: "5" }));
  assert.deepEqual(plain(many.errors), [many.fields.seed, many.fields.elite_count, many.fields.total_s]);
});

test("timeout is always total_s + 600 (≤ 15000), and the time advice compares the docking cap with total_s", () => {
  assert.equal(lib.gaTimeoutS(600), 1200);
  assert.equal(lib.gaTimeoutS(7200), 7800);
  assert.equal(lib.gaTimeoutS(lib.TOTAL_S_MAX), lib.TIMEOUT_MAX_S);
  assert.equal(lib.gaTimeAdvice({ max_new_dockings: 24, total_s: 7200 }), null);   // 7200 = 7200
  const advice = lib.gaTimeAdvice({ max_new_dockings: 60, total_s: 7200 });
  assert.ok(advice.startsWith("끝까지 못 갈 수 있음"), advice);
  assert.ok(advice.includes("60건 × 300초 = 18000초") && advice.includes("7200초"), advice);
  assert.ok(!advice.includes("부분 완료"));
  const lines = lib.gaParameterLines(lib.checkGaInput(valid()).ga);
  assert.equal(lines.length, lib.GA_KEYS.length + 1);
  assert.ok(lines.at(-1)[1].startsWith("7800초"));
});

// ---- request builder ----

const residue = { model_number: 1, chain_auth: "A", chain_label: "A", seq_auth: 401, seq_label: null, icode: null,
  resname: "LIG" };
function readyForm(patch = {}) {
  let form = lib.initialGaForm();
  form = lib.patchGaForm(form, { receptorHandle: "obj://r/receptor/1" });
  form = lib.patchGaForm(form, { receptorModelNumber: 1, connectivity: "pdb_conect",
    instance: { kind: "instance", residue }, candidateSetHandle: "obj://r/ligand_candidate_set/1" });
  form = lib.patchGaForm(form, { parentSdfHandle: "obj://r/sdf/1", boxSource: "ligand_range", seed: "42",
    acknowledgement: { keep_input_protonation: true, tool_assigned_types_charges: true, rigid_no_optimization: true },
    ga: valid(), ...patch });
  return form;
}

test("request: the fixed server shape (no mode, no ligand), M18 values via dockingArgs, filter and every GA key", () => {
  const check = lib.gaArgs(readyForm({ filter: { ranges: { mol_weight: { min: 100, max: 500 } }, pains_exclude: true } }));
  assert.equal(check.ok, true, check.errors?.join(" "));
  assert.deepEqual(Object.keys(check.args).sort(), ["acknowledgement", "box", "candidate_set_handle", "connectivity",
    "filter", "ga", "parameters", "parent_sdf_handle", "receptor_handle", "receptor_instance", "receptor_model_number"]);
  assert.deepEqual(plain(check.args.parameters), { seed: 42, exhaustiveness: 8, num_modes: 9, energy_range: 3 });
  assert.equal("conformers" in check.args.parameters, false);
  assert.deepEqual(plain(check.args.box), { source: "ligand_range", margin_A: 8 });
  assert.deepEqual(plain(check.args.receptor_instance), residue);
  assert.equal(check.args.ga.seed, 7);   // the GA seed, separate from the docking seed
  assert.equal(check.args.parameters.seed, 42);
  assert.deepEqual(plain(check.args.filter), { ranges: { mol_weight: { min: 100, max: 500 } }, pains_exclude: true });
  assert.ok(!JSON.stringify(check.args).includes("ga_pool"));
  // The same M18 condition (box, parameters, acknowledgement) as a standalone free M18 request of one candidate.
  const m18 = docking.dockingArgs({ ...readyForm(), ligandSource: "candidate", mode: "free", candidateId: "c1" });
  assert.equal(m18.ok, true);
  for (const key of ["receptor_handle", "receptor_model_number", "connectivity", "receptor_instance", "box",
    "parameters", "acknowledgement"]) assert.deepEqual(plain(check.args[key]), plain(m18.args[key]), key);
  // Equal GA and docking seeds are allowed (two separate inputs).
  assert.equal(lib.gaArgs(readyForm({ ga: valid({ seed: "42" }) })).ok, true);
  assert.equal(lib.gaArgsKey(check.args), JSON.stringify(check.args));
});

test("request guards: M18 errors and GA field errors are listed together; mode and source cannot change", () => {
  const empty = lib.gaArgs(lib.initialGaForm());
  assert.equal(empty.ok, false);
  assert.ok(empty.errors.some(text => text.includes("후보 집합을 고르세요")));
  assert.ok(empty.errors.some(text => text.includes("GA seed")));
  assert.ok(!empty.errors.some(text => text.includes("후보를 고르세요")));   // the pool stands in for the candidate
  assert.ok(!empty.errors.some(text => text.includes("방식")));
  const badGa = lib.gaArgs(readyForm({ ga: valid({ elite_count: "11" }) }));
  assert.equal(badGa.ok, false);
  assert.equal(badGa.errors.length, 1);
  const noAck = lib.gaArgs(readyForm({ acknowledgement: { keep_input_protonation: true,
    tool_assigned_types_charges: false, rigid_no_optimization: true } }));
  assert.ok(noAck.errors.some(text => text.includes("acknowledgement_missing")));
  const forced = lib.patchGaForm(readyForm(), { mode: "core_fixed", ligandSource: "sdf" });
  assert.equal(forced.mode, "free");
  assert.equal(forced.ligandSource, "candidate");
  // A new candidate set clears its parent SDF (M18 rule); nothing is chosen automatically.
  const moved = lib.patchGaForm(readyForm(), { candidateSetHandle: "obj://r/ligand_candidate_set/2" });
  assert.equal(moved.parentSdfHandle, null);
  assert.equal(lib.gaArgs(moved).ok, false);
});

// ---- preflight ----

const pair = (calls, wall) => ({ expensive_calls: calls, wall_clock_s: wall });
function preflight(patch = {}) {
  return { schema: "ligand_ga_preflight@1", starts_job: false, capability: { available: true }, score_label: "x",
    budget: {}, admission: { admitted: true, error: null, reason_code: null, message: null, detail: null },
    selection_sha256: "s", pool: { size: 40, eligible_count: 31, filter_excluded_count: 9 }, reusable_count: 3,
    reserved_units: 52, max_new_dockings_expected: 52, needed: pair(52, 15900), remaining: pair(10, 1800),
    shortfall: pair(42, 14100), full_run_may_be_partial: true, ga: null, statements: [{ id: "G1", text: G.G1 }],
    existing_job: null, ...patch };
}

test("preflight lines: server numbers as given, reusable and filter-excluded counts, wording for may-not-finish", () => {
  const lines = Object.fromEntries(lib.gaPreflightLines(preflight()));
  assert.equal(lines["후보 풀"], "40개 · 적격 31개 · 필터 제외 9개(도킹하지 않음)");
  assert.ok(lines["재사용 가능"].includes("3개") && lines["재사용 가능"].includes("과금하지 않음"));
  assert.equal(lines["예약 단위"], "52단위");
  assert.equal(lines["예상 최대 새 도킹"], "52건");
  assert.equal(lines["예상 시간 상한"], "15900.0초");
  assert.equal(lines["부족분"], "비싼 계산 42단위 · 활동 시간 14100.0초");
  assert.ok(lines["과금"].includes("52단위") && lines["과금"].includes("돌려받지 않음"));
  assert.ok(lines["시간 상한"].includes("끝까지 못 갈 수 있음"));
  const text = lib.gaPreflightLines(preflight()).map(item => item.join(" ")).join("\n");
  assert.ok(!text.includes("부분 완료"));
  assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
  const fits = Object.fromEntries(lib.gaPreflightLines(preflight({ full_run_may_be_partial: false })));
  assert.equal(fits["시간 상한"], undefined);
  const refused = preflight({ admission: { admitted: false, error: "input_invalid", reason_code: "ga_pool_too_small",
    message: "fewer eligible candidates than ga.population_size", detail: { reason_code: "ga_pool_too_small",
      eligible_count: 5, population_size: 12 } }, pool: null, reserved_units: null, needed: null, shortfall: null,
  max_new_dockings_expected: null, reusable_count: null, full_run_may_be_partial: null });
  assert.deepEqual(plain(lib.gaPreflightLines(refused)), []);
  const refusal = lib.gaPreflightRefusalText(refused);
  assert.ok(refusal.startsWith(lib.gaReasonText("ga_pool_too_small")), refusal);
  assert.ok(refusal.includes("적격 5개, 세대당 개체 수 12"), refusal);
  assert.equal(lib.gaPreflightRefusalList(preflight()), null);
});

test("limit approval offer: admitted, short on an axis, not dry-run; start gating needs the same args key", () => {
  assert.equal(lib.gaLimitApprovalOffered(preflight(), false), true);
  assert.equal(lib.gaLimitApprovalOffered(preflight(), true), false);
  assert.equal(lib.gaLimitApprovalOffered(preflight({ shortfall: pair(0, 0) }), false), false);
  assert.equal(lib.gaLimitApprovalOffered(preflight({ shortfall: pair(0, 5) }), false), true);
  assert.equal(lib.gaLimitApprovalOffered(preflight({ admission: { admitted: false } }), false), false);
  assert.equal(lib.gaLimitApprovalOffered(null, false), false);
  const check = lib.gaArgs(readyForm());
  const key = lib.gaArgsKey(check.args);
  const capability = { available: true, reason: null, reason_code: null };
  const base = { capability, busy: false, activeJob: null, check, dryRun: false };
  assert.ok(lib.gaStartBlockedReason({ ...base, preflight: null }).includes("시작 전 확인"));
  assert.ok(lib.gaStartBlockedReason({ ...base, preflight: { key: "other", value: preflight() } }).includes("시작 전 확인"));
  assert.ok(lib.gaStartBlockedReason({ ...base, preflight: { key, value: preflight() } }).includes("ga_limit_raise_required"));
  assert.equal(lib.gaStartBlockedReason({ ...base, preflight: { key, value: preflight({ shortfall: pair(0, 0) }) } }), null);
  assert.equal(lib.gaStartBlockedReason({ ...base, dryRun: true, preflight: { key, value: preflight() } }), null);
  assert.ok(lib.gaStartBlockedReason({ ...base, activeJob: { status: "running" }, preflight: { key,
    value: preflight({ shortfall: pair(0, 0) }) } }).includes("한 번에 한 작업"));
  assert.ok(lib.gaStartBlockedReason({ ...base, capability: { available: false, reason: "없음",
    reason_code: "engine_missing" }, preflight: null }).includes("engine_missing"));
  assert.equal(lib.gaLimitApprovalText({ raised: false, increase: pair(0, 0), limits_after: pair(1, 1) }),
    "이미 충분해 한도를 바꾸지 않았습니다.");
  assert.ok(lib.gaLimitApprovalText({ raised: true, increase: pair(42, 14160), limits_after: pair(60, 15960) })
    .includes("증가분 비싼 계산 42단위"));
});

// ---- progress, job, status ----

test("progress shows staged counts only; job text keeps a published summary outcome", () => {
  const text = lib.gaProgressText({ pool: { size: 40, eligible_count: 31, filter_excluded_count: 9 },
    reserved_units: 52, reused_planned: 3, individuals_started: 14, individuals_finished: 13, generation_records: 2,
    generations_complete: 1, summary_handle: null, summary_status: null, summary_stop_reason: null });
  assert.equal(text, "완료한 세대 1개(세대 기록 2개) · 평가 시작 14개 · 평가 끝 13개 · 저장된 결과 재사용 예정 3개 · 예약 52단위");
  const ga = { summary_handle: "obj://r/ligand_ga_result/h", summary_status: "partial",
    summary_stop_reason: "time_exhausted" };
  const failed = lib.gaJobText({ status: "failed", cancel_requested: false,
    failure: { error: "resource_exceeded", message: "job timeout" }, ga }, false);
  assert.ok(failed.includes("작업 기록 failed") && failed.includes("(time_exhausted)") && !failed.includes("job timeout"));
  assert.ok(lib.gaJobText({ status: "failed", cancel_requested: false,
    failure: { error: "worker_failed", message: "m" }, ga: null }, false).startsWith("GA 작업 실패"));
  assert.equal(lib.gaJobText(null, false), "GA 작업 없음");
  assert.equal(lib.gaApprovalRequired(409, { gate: "expensive_first_call", tool: "qvina_ga_design" }), true);
  assert.equal(lib.gaApprovalRequired(409, { gate: "expensive_first_call", tool: "qvina_dock_batch" }), false);
  const jobs = [{ run_id: "r", protocol_id: "qvina_ga_dock_v1", status: "done" },
    { run_id: "r", protocol_id: "qvina_batch_dock_v1", status: "running" },
    { run_id: "r", protocol_id: "qvina_ga_dock_v1", status: "running", job_id: "j2" },
    { run_id: "s", protocol_id: "qvina_ga_dock_v1", status: "queued" }];
  assert.equal(lib.gaActiveJob(jobs, "r").job_id, "j2");
  assert.equal(lib.gaActiveJob(jobs, "x"), null);
  assert.equal(lib.gaActiveJob(null, "r"), null);
});

test("stop reasons and status: closed names with codes, no_change is 점수 최솟값 변화 없음, never 부분 완료", () => {
  assert.equal(lib.STOP_REASON_LABEL.no_change, "점수 최솟값 변화 없음");
  for (const reason of lib.STOP_REASONS) {
    const text = lib.gaStatusText({ status: lib.STATUS_BY_STOP_REASON[reason], stop_reason: reason });
    assert.ok(text.includes(`(${reason})`), reason);
    assert.ok(!text.includes("부분 완료"), text);
    assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
  }
  assert.equal(lib.gaStatusText({ status: "complete", stop_reason: "no_change" }),
    "완료 (complete) · 종료 이유: 점수 최솟값 변화 없음 (no_change)");
  assert.ok(lib.gaStatusText({ status: "partial", stop_reason: "docking_limit" }).startsWith("일부 세대만 계산됨 (partial)"));
  for (const code of [...lib.ADMISSION_REASONS, ...lib.FAILED_EXTRA_REASONS])
    assert.ok(lib.gaReasonText(code).endsWith(` (${code})`), code);
  assert.equal(lib.gaReasonText("ligand_not_3d"), docking.dockingReasonText("ligand_not_3d"));
  assert.equal(lib.gaReasonText("unknown_x"), "unknown_x");
});

test("statements: server ids' texts verbatim when given, else G1 always, G2 when partial, G3 when reused", () => {
  assert.deepEqual(plain(lib.gaStatementTexts({ status: "complete", reused_count: 0 })), [G.G1]);
  assert.deepEqual(plain(lib.gaStatementTexts({ status: "partial", reused_count: 0 })), [G.G1, G.G2]);
  assert.deepEqual(plain(lib.gaStatementTexts({ status: "partial", reused_count: 2 })), [G.G1, G.G2, G.G3]);
  assert.deepEqual(plain(lib.gaStatementTexts({ status: "complete", reused_count: 1 })), [G.G1, G.G3]);
  assert.deepEqual(plain(lib.gaStatementTexts({ status: "complete", reused_count: 0 },
    [{ id: "G1", text: "server G1" }, { id: "G3", text: "server G3" }])), ["server G1", "server G3"]);
  for (const text of Object.values(G)) assert.deepEqual(plain(lib.gaForbiddenWords(text)), []);
});

// ---- results ----

const ind = (candidate_id, origin, state, score, extra = {}) => ({ candidate_id, origin, parent_candidate_id: null,
  similarity: null, evaluation: origin === "carried" ? null : "docked", eval_index: 0, state,
  reason_code: state === "failed" ? "candidate_timeout" : null, score,
  result_handle: state === "failed" ? null : `obj://r/docking_result/${candidate_id}`, ...extra });
const GEN = { index: 2, complete: true, min_score: -8.25, max_score: 0, individuals: [
  ind("c_e", "carried", "scored", -8.25),
  ind("c_a", "similar", "failed", null, { parent_candidate_id: "c_e", similarity: 0.5234565 }),
  ind("c_d", "similar", "scored", 0, { parent_candidate_id: "c_e", similarity: 1 }),
  ind("c_b", "random", "null_result", null, { evaluation: "reused" }),
  ind("c_c", "random", "scored", -7.2),
  ind("c_f", "similar", "scored", -7.2),
] };
const ids = rows => plain(rows.map(row => row.candidate_id));

test("individuals table: stored slot order by default; score sort keeps score-less rows last, never as 0", () => {
  const rows = lib.individualRows(GEN);
  assert.deepEqual(plain(rows.map(row => row.position)), [0, 1, 2, 3, 4, 5]);
  assert.deepEqual(ids(lib.sortIndividuals(rows, null)), ["c_e", "c_a", "c_d", "c_b", "c_c", "c_f"]);
  assert.deepEqual(ids(lib.sortIndividuals(rows, { key: "score", direction: "asc" })),
    ["c_e", "c_c", "c_f", "c_d", "c_a", "c_b"]);
  assert.deepEqual(ids(lib.sortIndividuals(rows, { key: "score", direction: "desc" })),
    ["c_d", "c_c", "c_f", "c_e", "c_a", "c_b"]);
  assert.deepEqual(ids(lib.sortIndividuals(rows, { key: "slot", direction: "desc" })),
    ["c_f", "c_c", "c_b", "c_d", "c_a", "c_e"]);
  assert.deepEqual(ids(lib.sortIndividuals(rows, { key: "candidate", direction: "asc" })),
    ["c_a", "c_b", "c_c", "c_d", "c_e", "c_f"]);
  // A non-scored state is score-less even if a number were present.
  const odd = lib.individualRows({ individuals: [ind("x", "initial", "failed", -99), ind("y", "initial", "scored", -1)] });
  assert.deepEqual(ids(lib.sortIndividuals(odd, { key: "score", direction: "asc" })), ["y", "x"]);
  assert.deepEqual(ids(lib.sortIndividuals(odd, { key: "score", direction: "desc" })), ["y", "x"]);
  const before = plain(rows);
  lib.sortIndividuals(rows, { key: "score", direction: "desc" });
  assert.deepEqual(plain(rows), before);
  let sort = lib.nextIndividualSort(null, "score");
  assert.deepEqual(plain(sort), { key: "score", direction: "asc" });
  sort = lib.nextIndividualSort(sort, "score");
  assert.equal(lib.individualAriaSort(sort, "score"), "descending");
  assert.equal(lib.individualAriaSort(sort, "slot"), "none");
});

test("cells: origin labels, reuse flag, stored score only for scored, lineage, M18 detail link, generation values", () => {
  assert.deepEqual(plain(lib.ORIGINS.map(lib.originText)), ["초기", "이어받음", "유사", "무작위"]);
  assert.equal(lib.evaluationText("reused"), "저장된 결과 재사용");
  assert.equal(lib.evaluationText("docked"), "새 도킹");
  assert.ok(lib.evaluationText(null).includes("다시 도킹하지 않음"));
  assert.equal(lib.individualScoreText(GEN.individuals[0]), "-8.3");
  assert.equal(lib.individualScoreText(GEN.individuals[2]), "0.0");   // a real stored 0 is a number
  assert.equal(lib.individualScoreText(GEN.individuals[1]), "");
  assert.equal(lib.individualScoreText(GEN.individuals[3]), "");
  assert.equal(lib.individualReasonText(GEN.individuals[1]), lib.gaReasonText("candidate_timeout"));
  assert.equal(lib.individualReasonText(GEN.individuals[0]), "");
  assert.equal(lib.lineageText(GEN.individuals[1]), "부모 c_e · 지문 Tanimoto 0.523457");
  assert.equal(lib.lineageText(GEN.individuals[2]), "부모 c_e · 지문 Tanimoto 1.000000");
  assert.equal(lib.lineageText(GEN.individuals[4]), "");
  assert.equal(lib.individualDetailHandle(GEN.individuals[0]), "obj://r/docking_result/c_e");
  assert.equal(lib.individualDetailHandle(GEN.individuals[1]), null);
  assert.equal(lib.generationRangeText(GEN), "점수 최솟값 -8.3 · 점수 최댓값 0.0 (kcal/mol)");
  assert.equal(lib.generationRangeText({ min_score: null, max_score: null }), "이 세대에 점수 있는 개체 없음");
  assert.equal(lib.generationTabText({ index: 3, complete: true }), "세대 3");
  assert.ok(lib.generationTabText({ index: 4, complete: false }).includes("중간에 멈춤"));
  assert.equal(lib.scoreHeaderText(), "qvina 점수(kcal/mol) · 모드 1(엔진 출력 순서)");
  assert.equal(lib.stateText("null_result"), "빈 과학 결과(모드 0개) (null_result)");
  const list = lib.gaListRowText({ published_seq: 9, valid: true, reason_code: null, status: "complete",
    stop_reason: "pool_exhausted", generations_done: 3, new_dockings_used: 20, reused_count: 4 });
  assert.ok(list.includes("완료한 세대 3개") && list.includes("(pool_exhausted)"), list);
  assert.ok(lib.gaListRowText({ published_seq: 9, valid: false, reason_code: "evidence_invalid", status: null,
    stop_reason: null, generations_done: null, new_dockings_used: null, reused_count: null }).includes("읽을 수 없음"));
  const summary = Object.fromEntries(lib.gaSummaryLines({ status: "partial", stop_reason: "docking_limit",
    generations_done: 2, new_dockings_used: 52, reused_count: 3, reserved_units: 52,
    pool: { size: 40, eligible_count: 31, filter_excluded_count: 9 } }));
  assert.equal(summary["새 도킹"], "52건 (예약 52단위)");
  assert.ok(lib.gaReportMatches({ manifest: { schema: "method_report_manifest@1", analysis_type: "ligand_ga",
    result_handle: "h" } }, "h"));
  assert.ok(!lib.gaReportMatches({ manifest: { schema: "method_report_manifest@1", analysis_type: "ligand_docking_batch",
    result_handle: "h" } }, "h"));
});

// ---- wording ----

test("forbidden words: every string this module exports passes; the check catches GA words", () => {
  const strings = [];
  const collect = value => {
    if (typeof value === "string") strings.push(value);
    else if (Array.isArray(value)) value.forEach(collect);
    else if (value && typeof value === "object") Object.values(value).forEach(collect);
  };
  for (const [name, value] of Object.entries(lib)) if (typeof value !== "function") collect(value);
  for (const key of lib.GA_KEYS) strings.push(lib.gaRangeText(key));
  strings.push(lib.chargeNote(5), lib.gaTimeAdvice({ max_new_dockings: 100, total_s: 600 }),
    lib.gaExistingJobText({ job_id: "j", status: "done" }), lib.scoreHeaderText(),
    lib.checkGaInput(lib.initialGaInput()).errors.join("\n"),
    lib.checkGaInput(valid({ population_size: "5", elite_count: "4", max_new_dockings: "4" })).errors.join("\n"));
  for (const reason of lib.STOP_REASONS) strings.push(lib.stopReasonText(reason));
  for (const text of strings) assert.deepEqual(plain(lib.gaForbiddenWords(text)), [], text);
  const banned = ["순위", "최고", "best", "개선", "승자", "추천", "친화도가 높다", "평균 비교", "부분 완료"];
  for (const word of banned) assert.ok(lib.gaForbiddenWords(`세대 ${word}`).length > 0, word);
  // The exact score label (which says 친화도가 아님) and the G sentences are exempt.
  assert.deepEqual(plain(lib.gaForbiddenWords(lib.SCORE_LABEL)), []);
  assert.deepEqual(plain(lib.gaForbiddenWords(`${G.G1}\n${G.G2}`)), []);
  assert.ok(lib.gaForbiddenWords(`${G.G1} 추가`).length > 0);
});
