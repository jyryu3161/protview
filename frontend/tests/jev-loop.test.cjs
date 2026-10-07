const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

function load(filename, dependencies = {}, sandbox = {}) {
  const source = fs.readFileSync(path.join(__dirname, `../src/lib/${filename}.ts`), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const moduleObject = { exports: {} };
  vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, URLSearchParams, ...sandbox,
    require: name => dependencies[name] ?? require(name) });
  return moduleObject.exports;
}
const siteAnnotation = load("site-annotation", { "./comparison": load("comparison"), "./numbering": load("numbering"),
  "./event-model": load("event-model") });
const docking = load("docking", { "./site-annotation": siteAnnotation });
const mutationModel = load("mutation-model", { "./site-annotation": siteAnnotation, "./docking": docking });
const jev = load("jev", { "./site-annotation": siteAnnotation }, { crypto: globalThis.crypto });
const lib = load("jev-loop", { "./docking": docking, "./jev": jev, "./mutation-model": mutationModel });
const reportLibrary = load("report-library");
const plain = value => JSON.parse(JSON.stringify(value));

// ---- closed sets, caps and fixed sentences are read from the backend modules themselves ----
const backend = name => fs.readFileSync(path.join(__dirname, `../../backend/mw/${name}`), "utf8");
const constantsSource = backend("jev_loop_constants.py");
function pyTuple(name, source = constantsSource) {
  const match = new RegExp(`^${name} = \\(([^)]*)\\)`, "m").exec(source);
  assert.ok(match, `backend constant ${name} not found`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map(item => item[1]);
}
function pyNumber(name, source = constantsSource) {
  const match = new RegExp(`^${name} = ([0-9_.]+)\\b`, "m").exec(source);
  assert.ok(match, `backend constant ${name} not found`);
  return Number(match[1].replace(/_/g, ""));
}
function pyString(name, source = constantsSource) {
  const match = new RegExp(`^${name} = "([^"]+)"`, "m").exec(source);
  assert.ok(match, `backend constant ${name} not found`);
  return match[1];
}
/** `NAME = "..."` or a parenthesized concatenation `NAME = ("a" "b")`. */
function pySentence(name) {
  if (new RegExp(`^${name} = "`, "m").test(constantsSource)) return pyString(name);
  const match = new RegExp(`^${name} = \\(([\\s\\S]*?)\\)\\n`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return [...match[1].matchAll(/"([^"]*)"/g)].map(item => item[1]).join("");
}
/** The fixed loop sentences LJ1–LJ8 (stored by the server; the screen shows them as given, never as constants). */
const LJ = Object.fromEntries(["LJ1", "LJ2", "LJ3", "LJ4", "LJ5", "LJ6", "LJ7", "LJ8"].map(name => [name, pySentence(name)]));

// spec .dryforge/spec.md 9.3, verbatim (the hand copy the module and the backend are compared with)
const SPEC_UL = {
  UL1: "JEV 루프는 바퀴마다 보낼 내용 승인과 계산 시작 승인을 따로 받는다. JEV가 고른 후보도 사람이 승인해야 계산된다.",
  UL2: "한 바퀴에 JEV 응답이 한 번 완료되면 다시 묻지 않는다. 다른 후보를 원하면 직접 지정한다.",
  UL3: "루프 전송은 뷰어 모델 명령·지식·보고서 탭의 전송과 같은 외부 토큰·USD 예산, 같은 run 10회 전송 상한, 같은 '사용량 모름' 중지 상태를 쓴다.",
};

// ---- fixtures (synthetic; handles, hashes and scores are placeholders, no scientific value) ----
const RUN = "run-loop";
const LOOP = "1c6f0a6e-3b1d-4b8e-9a51-6a2d1f0b7c11";
const LOOP_P = "2d7e1b7f-4c2e-4c9f-8b62-7b3e2a1c8d22";
const SID = "123e4567-e89b-42d3-a456-426614174000";
const SID_2 = "9b2c5a0e-1f3d-4c6b-8e7a-0d1c2b3a4f5e";
const AUDIT = `eg_${"e".repeat(32)}`;
const hex = c => c.repeat(64);
const LIG_SET = `obj://${RUN}/ligand_candidate_set/${hex("a")}`;
const MUT_SET = `obj://${RUN}/mutation_candidate_set/${hex("c")}`;
const PROJ = `obj://${RUN}/jev_loop_projection/${hex("b")}`;
const CHOICE_1 = `obj://${RUN}/jev_loop_choice/${hex("9")}`;
const CHOICE_4 = `obj://${RUN}/jev_loop_choice/${hex("8")}`;
const RES = c => `obj://${RUN}/docking_result/${hex(c)}`;
const MODEL_H = `obj://${RUN}/mutation_set_model/${hex("d")}`;
const SUMMARY_H = `obj://${RUN}/jev_loop_result/${hex("f")}`;
const id16 = n => `c_${n.toString(16).padStart(16, "0")}`;
const SMILES = n => `C${"C".repeat(n)}O`;
const RESIDUE = { model_number: 1, chain_auth: "A", chain_label: "A", seq_auth: 42, seq_label: 40, icode: "", resname: "LYS" };
const amounts = over => ({ expensive_units: 1, wall_clock_s: 300, external_tokens: null, usd: null, sends: 1, ...over });
const counts = over => ({ started: 3, done: 3, jev_decided: 1, human_decided: 2, sends_dispatched: 1, units_charged: 3,
  reused_count: 1, ...over });
const step = over => ({ step: "ligand_dock", candidate_ref: id16(1), job_id: "job-1", call_key: hex("1"),
  result_handle: RES("1"), state: "completed", reason_code: null, evaluation: "computed", ...over });
const send = over => ({ send_id: SID, status: "completed", send_ordinal: 0, proposal_handle: CHOICE_1, late: false, ...over });
const iteration = over => ({ index: 1, phase: "done", decided_by: "jev", candidate_ref: id16(1), proposal_handle: CHOICE_1,
  list_position: 2, list_size: 5, approvals: [{ step: "ligand_dock", candidate_ref: id16(1), decided_by: "jev",
    proposal_handle: CHOICE_1, call_key: hex("1") }], sends: [send()], steps: [step()], state: "scored",
  score_kcal_mol: -7.25, ...over });
const candidate = (n, over) => ({ ref: id16(n), display: { smiles: SMILES(n) }, state: "pending", evaluation: null,
  score_kcal_mol: null, iteration: null, ...over });
const current = over => ({ iteration: 4, phase: "awaiting_selection", step: "ligand_dock", action: "select",
  needs: amounts(), remaining: amounts({ expensive_units: 5, wall_clock_s: 1500, sends: 9 }), blocked_axes: [],
  send_blocked_axes: [], can_end: true, job: null, ...over });
/** A ligand loop after three iterations: c1 scored by a JEV choice, c2 an empty result, c6 failed, c4 reused. */
function ligandRecord(over = {}) {
  const candidates = [
    candidate(1, { state: "scored", evaluation: "computed", score_kcal_mol: -7.25, iteration: 1 }),
    candidate(2, { state: "null_result", evaluation: "computed", iteration: 2 }),
    candidate(3),
    candidate(4, { state: "scored", evaluation: "reused", score_kcal_mol: -6.05 }),
    candidate(5, { state: "unavailable" }),
    candidate(6, { state: "failed", evaluation: "computed", iteration: 3 }),
    candidate(7),
  ];
  return { schema: "jev_loop@1", loop_id: LOOP, branch: "ligand", status: "active", end_reason: null,
    exhausted_reason: null, goal: "exploit", loop_seed: 20261007, iteration_cap: 5, effective_cap: 5,
    pool: { source: { handle: LIG_SET, schema: "ligand_candidate_set@1" }, structure: null, filter: null,
      candidates: candidates.map(row => ({ ref: row.ref, display: row.display })) },
    setup: {}, setup_sha256: hex("5"), pins: {}, counts: counts(), candidates,
    iterations: [
      iteration(),
      iteration({ index: 2, decided_by: "human", candidate_ref: id16(2), proposal_handle: null, list_position: null,
        list_size: null, sends: [], approvals: [], steps: [step({ candidate_ref: id16(2), job_id: "job-2",
          result_handle: RES("2") })], state: "null_result", score_kcal_mol: null }),
      iteration({ index: 3, decided_by: "human", candidate_ref: id16(6), proposal_handle: null, list_position: null,
        list_size: null, sends: [], approvals: [], steps: [step({ candidate_ref: id16(6), job_id: "job-6",
          result_handle: null, state: "failed", reason_code: "engine_failed" })], state: "failed", score_kcal_mol: null }),
    ],
    current: current(), result_handle: null, limitations: [LJ.LJ1, LJ.LJ2, LJ.LJ3, LJ.LJ4, LJ.LJ6], ...over };
}
/** A protein loop whose iteration 1 modelled candidate 12 and awaits its docking decision. */
function proteinRecord(over = {}) {
  const display = to => ({ residue: RESIDUE, from: "K", to });
  return { schema: "jev_loop@1", loop_id: LOOP_P, branch: "protein", status: "active", end_reason: null,
    exhausted_reason: null, goal: "explore", loop_seed: 7, iteration_cap: 3, effective_cap: 3,
    pool: { source: { handle: MUT_SET, schema: "mutation_candidate_set@1" },
      structure: { handle: `obj://${RUN}/prepared_structure/${hex("6")}`, model_number: 1 }, filter: null,
      candidates: [{ ref: 12, display: display("A") }, { ref: 3, display: display("G") }, { ref: 30, display: display("W") }] },
    setup: {}, setup_sha256: hex("5"), pins: {},
    counts: counts({ started: 1, done: 0, jev_decided: 0, human_decided: 1, sends_dispatched: 0, units_charged: 1,
      reused_count: 0 }),
    candidates: [{ ref: 12, display: display("A"), state: "pending", evaluation: null, score_kcal_mol: null, iteration: null },
      { ref: 3, display: display("G"), state: "pending", evaluation: null, score_kcal_mol: null, iteration: null },
      { ref: 30, display: display("W"), state: "pending", evaluation: null, score_kcal_mol: null, iteration: null }],
    iterations: [{ index: 1, phase: "awaiting_docking", decided_by: "human", candidate_ref: 12, proposal_handle: null,
      list_position: null, list_size: null,
      approvals: [{ step: "model", candidate_ref: 12, decided_by: "human", proposal_handle: null, call_key: hex("2") }],
      sends: [], steps: [{ step: "model", candidate_ref: 12, job_id: "job-m", call_key: hex("2"), result_handle: MODEL_H,
        state: "completed", reason_code: null, evaluation: "computed" }], state: "in_progress", score_kcal_mol: null }],
    current: current({ iteration: 1, phase: "awaiting_docking", step: "dock", action: "dock",
      needs: amounts({ sends: 0 }), remaining: amounts({ expensive_units: 6, wall_clock_s: 1400, sends: 10 }),
      can_end: false }),
    result_handle: null, limitations: [LJ.LJ1, LJ.LJ2, LJ.LJ3, LJ.LJ5, LJ.LJ7], ...over };
}
const BODY = JSON.stringify({ model: "typesafe/jev-1.13", questions: { candidate_choice: { criteria: { c01: "Candidate c01." },
  instructions: "x", type: "choice" } }, state: { schema: "jev_loop_ligand_candidates@1" } });
const SELECTION = [{ alias: "c01", ref: id16(7), state: "pending" }, { alias: "c02", ref: id16(1), state: "scored" },
  { alias: "c03", ref: id16(3), state: "pending" }, { alias: "c04", ref: id16(2), state: "null_result" },
  { alias: "c05", ref: id16(4), state: "scored" }, { alias: "c06", ref: id16(6), state: "failed" }];
const preview = over => ({ schema: "jev_preview@1", projection_handle: PROJ, kind: "ligand",
  source: { handle: LIG_SET, schema: "ligand_candidate_set@1" },
  question: { id: "ligand_loop_choice@1", key: "candidate_choice", type: "choice",
    instructions: "Choose exactly one candidate ... not a prediction of binding ... lowest listed score ...",
    instructions_sha256: hex("c") },
  body: BODY, body_sha256: hex("d"), body_bytes: BODY.length, selection: SELECTION, selection_sent: false,
  reservation: { external_tokens: 4096 + Math.ceil(BODY.length * 2 / 3), usd: 0.1 }, send_cap: 10, used: 1, remaining: 9,
  budget_remaining: { external_tokens: 110000, usd: 1.9 }, blocked_by: [], previous_sends: 0,
  loop: { loop_id: LOOP, iteration: 4, send_ordinal: 1,
    needs: amounts({ external_tokens: 4200, usd: 0.1 }),
    remaining: amounts({ expensive_units: 5, wall_clock_s: 1500, external_tokens: 110000, usd: 1.9, sends: 9 }),
    send_blocked_axes: [] },
  loop_blocks: [], ...over });
const USAGE = { input_tokens: 1500, output_tokens: 20, external_tokens: 1520, cost: 0.00123 };
const choice = over => ({ schema: "jev_loop_choice@1", method_version: "mw.jev_loop_choice/v1", label: "JEV 판정(모델 선택)",
  scientific_result: false, loop: { loop_id: LOOP, iteration: 4, send_ordinal: 1 }, goal: "exploit",
  send: { send_id: SID_2, audit_id: AUDIT }, source: { handle: LIG_SET, schema: "ligand_candidate_set@1" },
  projection: { handle: PROJ, wire_sha256: hex("f"), body_sha256: hex("d"), body_bytes: 1234 },
  question: { id: "ligand_loop_choice@1", key: "candidate_choice", instructions_sha256: hex("c") },
  requested_model: "typesafe/jev-1.13", served_model: "typesafe/jev-1.13-20260917", selection: SELECTION,
  answer: { choice_alias: "c03", list_position: 2, list_size: 3, local_ref: { candidate_id: id16(3) },
    local_display: { smiles: SMILES(3) }, confidence: 0.87654, probabilities: { c03: 0.7, c01: 0.2 } },
  usage: USAGE, arrival: { late: false, late_reason: null }, limitations: [LJ.LJ1, LJ.LJ2, LJ.LJ3, LJ.LJ4, LJ.LJ6], ...over });
const detail = (over = {}, choiceOver = {}) => ({ schema: "jev_send@1", send_id: SID_2, status: "completed",
  reason_code: null, projection_handle: PROJ, source: { handle: LIG_SET, schema: "ligand_candidate_set@1" }, kind: "ligand",
  question_id: "ligand_loop_choice@1", selection_count: 6, body_sha256: hex("d"), body_bytes: 1234, audit_id: AUDIT,
  requested_model: "typesafe/jev-1.13", served_model: "typesafe/jev-1.13-20260917", usage: USAGE, choice_handle: CHOICE_4,
  late: false, late_reason: null, approved_event_seq: 40, outcome_event_seq: 44,
  loop: { loop_id: LOOP, iteration: 4, send_ordinal: 1 }, choice: choice(choiceOver),
  local_display: { smiles: SMILES(3) }, ...over });
/** The ligand record once iteration 4 has the JEV selection `CHOICE_4` (phase awaiting_compute). */
function computeRecord(over = {}) {
  const base = ligandRecord();
  return { ...base, iterations: [...base.iterations, iteration({ index: 4, phase: "awaiting_compute", decided_by: null,
    candidate_ref: null, proposal_handle: null, list_position: null, list_size: null, approvals: [], steps: [],
    sends: [send({ send_id: SID, status: "failed", send_ordinal: 0, proposal_handle: null }),
      send({ send_id: SID_2, send_ordinal: 1, proposal_handle: CHOICE_4 })], state: "in_progress", score_kcal_mol: null })],
  current: current({ phase: "awaiting_compute", action: "compute", needs: amounts({ sends: 0 }) }), ...over };
}

// ---- constants ----

test("closed sets, caps, names and screen notes equal backend/mw/jev_loop_constants.py and the spec text", () => {
  const pairs = [["LOOP_BRANCHES", "BRANCHES"], ["LOOP_GOALS", "GOALS"], ["LOOP_CANDIDATE_STATES", "CANDIDATE_STATES"],
    ["LOOP_EVALUATIONS", "EVALUATIONS"], ["LOOP_STEPS", "STEPS"], ["LOOP_STEP_STATES", "STEP_STATES"],
    ["LOOP_ITERATION_STATES", "ITERATION_STATES"], ["LOOP_PHASES", "PHASES"], ["LOOP_ACTIONS", "ACTIONS"],
    ["LOOP_DECIDED_BY", "DECIDED_BY"], ["LOOP_EXHAUSTED_REASONS", "EXHAUSTED_REASONS"], ["LOOP_END_REASONS", "END_REASONS"],
    ["LOOP_AXES", "AXES"], ["LOOP_CREATE_REASONS", "CREATE_REASONS"], ["LOOP_SEND_REASONS", "LOOP_SEND_REASONS"],
    ["LOOP_COMPUTE_REASONS", "COMPUTE_REASONS"], ["LOOP_END_REFUSAL_REASONS", "END_REFUSAL_REASONS"]];
  for (const [front, back] of pairs) assert.deepEqual(plain(lib[front]), pyTuple(back), front);
  assert.deepEqual(plain(lib.LOOP_PROJECTION_REASON_CODES), [...pyTuple("PROJECTION_REASON_CODES"),
    pyString("PROJECTION_INVALID")]);
  assert.equal(lib.LOOP_CREATE_REASONS.length, 11);
  assert.deepEqual(plain(lib.LOOP_QUESTION_IDS), [pyString("LIGAND_QUESTION_ID"), pyString("MUTATION_QUESTION_ID")]);
  for (const [front, back] of [["LOOP_MIN_POOL", "MIN_POOL"], ["LOOP_MAX_POOL", "MAX_POOL"],
    ["ITERATION_CAP_MIN", "MIN_ITERATION_CAP"], ["ITERATION_CAP_MAX", "MAX_ITERATION_CAP"],
    ["ITERATION_CAP_DEFAULT", "DEFAULT_ITERATION_CAP"], ["LOOP_SEED_MIN", "MIN_LOOP_SEED"],
    ["LOOP_SEED_MAX", "MAX_LOOP_SEED"], ["MIN_PENDING_TO_SEND", "MIN_PENDING_TO_SEND"]])
    assert.equal(lib[front], pyNumber(back), front);
  assert.deepEqual([lib.LOOP_MIN_POOL, lib.LOOP_MAX_POOL, lib.ITERATION_CAP_MIN, lib.ITERATION_CAP_MAX,
    lib.ITERATION_CAP_DEFAULT, lib.LOOP_SEED_MAX], [2, 20, 1, 8, 5, 2147483647]);
  assert.equal(lib.LOOP_POLL_MS, pyNumber("READ_POLL_INTERVAL_S") * 1000);
  assert.equal(mutationModel.CONTACT_CUTOFF_DEFAULT_A, pyNumber("DEFAULT_CONTACT_CUTOFF_A"));
  for (const [front, back] of [["LOOP_TOOL", "TOOL"], ["LOOP_SCHEMA", "LOOP_SCHEMA"],
    ["LOOP_PROJECTION_KIND", "PROJECTION_KIND"], ["LOOP_PROJECTION_SCHEMA", "PROJECTION_SCHEMA"],
    ["LOOP_CHOICE_SCHEMA", "CHOICE_SCHEMA"], ["LOOP_RESULT_SCHEMA", "RESULT_SCHEMA"],
    ["LOOP_REPORT_TYPE", "REPORT_ANALYSIS_TYPE"], ["LOOP_REPORT_LABEL", "REPORT_LABEL"],
    ["ORDER_ALGORITHM", "ORDER_ALGORITHM"], ["LOOP_ID_CONFLICT", "LOOP_ID_CONFLICT"],
    ["LOOP_SEND_INVALID", "LOOP_SEND_INVALID"], ["LOOP_STEP_UNAVAILABLE", "STEP_UNAVAILABLE"],
    ["LOOP_START_BLOCKED", "START_BLOCKED"], ["LOOP_NOT_RUN_REASON", "NOT_RUN_REASON"]])
    assert.equal(lib[front], pyString(back), front);
  assert.equal(lib.LOOP_REPORT_LABEL, "JEV 루프 보고서");
  // UL1–UL3 verbatim (spec 9.3 = backend = screen); the protein area's U3 and J7 are the M24 constants
  for (const key of Object.keys(SPEC_UL)) assert.equal(pySentence(key), SPEC_UL[key], `backend ${key}`);
  assert.deepEqual(plain(lib.LOOP_SCREEN_NOTES), SPEC_UL);
  assert.deepEqual(Object.keys(lib.LOOP_SCREEN_NOTES), ["UL1", "UL2", "UL3"]);
  assert.equal(lib.PROTEIN_SCREEN_NOTE, jev.JEV_SCREEN_NOTES.U3);
  assert.equal(pySentence("J7"), jev.JEV_STATEMENTS.J7);
  assert.equal(pyString("CHOICE_LABEL"), jev.JEV_CHOICE_LABEL);
  // LJ1–LJ8 are never screen constants of this module (the server's stored sentences are shown as given)
  const source = fs.readFileSync(path.join(__dirname, "../src/lib/jev-loop.ts"), "utf8");
  for (const [name, sentence] of Object.entries(LJ)) assert.ok(!source.includes(sentence.slice(0, 24)), name);
  // the compute / end refusal HTTP tables of the backend name exactly these reasons
  const loops = backend("jev_loops.py");
  const httpKeys = name => [...new RegExp(`^${name} = \\{([^}]*)\\}`, "m").exec(loops)[1].matchAll(/"([a-z_]+)":/g)]
    .map(item => item[1]);
  assert.deepEqual(httpKeys("COMPUTE_HTTP"), plain(lib.LOOP_COMPUTE_REASONS));
  assert.deepEqual(httpKeys("END_HTTP"), plain(lib.LOOP_END_REFUSAL_REASONS));
});

// ---- closed labels ----

test("every closed code has a Korean label \"한국어 (code)\"; values outside a set get the fixed default", () => {
  const sets = [[lib.LOOP_CANDIDATE_STATES, lib.candidateStateText], [lib.LOOP_PHASES, lib.phaseText],
    [lib.LOOP_ACTIONS, lib.actionText], [lib.LOOP_STEPS, lib.stepText], [lib.LOOP_STEP_STATES, lib.stepStateText],
    [lib.LOOP_ITERATION_STATES, lib.iterationStateText], [lib.LOOP_EXHAUSTED_REASONS, lib.exhaustedReasonText],
    [lib.LOOP_END_REASONS, lib.endReasonText], [lib.LOOP_AXES, lib.axisText], [lib.LOOP_GOALS, lib.goalText],
    [[...lib.LOOP_CREATE_REASONS, lib.LOOP_ID_CONFLICT], lib.createReasonText],
    [[...lib.LOOP_COMPUTE_REASONS, lib.LOOP_STEP_UNAVAILABLE], lib.computeReasonText],
    [lib.LOOP_END_REFUSAL_REASONS, lib.endRefusalText], [lib.LOOP_PROJECTION_REASON_CODES, lib.loopProjectionReasonText],
    [lib.LOOP_SEND_REASONS, lib.loopSendReasonText]];
  for (const [codes, text] of sets) {
    for (const code of codes) assert.match(text(code), new RegExp(`^[^\\s(].* \\(${code}\\)$`), code);
    for (const outside of ["brand_new_code", "toString", "__proto__", "constructor", "", null, undefined, 42, {}])
      assert.equal(text(outside), jev.UNKNOWN_CODE_TEXT, String(outside));
  }
  // a code of one set is not silently accepted by another
  assert.equal(lib.createReasonText("state_changed"), jev.UNKNOWN_CODE_TEXT);
  assert.equal(lib.loopSendReasonText("budget_blocked"), jev.UNKNOWN_CODE_TEXT);
  assert.equal(lib.endRefusalText("pool_invalid"), jev.UNKNOWN_CODE_TEXT);
  assert.equal(lib.computeReasonText("cap_reached"), jev.UNKNOWN_CODE_TEXT);
  // the six candidate states, evaluations and who chose
  assert.deepEqual(plain(lib.LOOP_CANDIDATE_STATES.map(state => lib.candidateStateText(state))), ["계산하지 않음 (pending)",
    "점수 있음 (scored)", "빈 결과(모드 0개) (null_result)", "실패 (failed)", "도킹하지 않음(모델만 있음) (not_run)",
    "이 run에서 계산할 수 없음 (unavailable)"]);
  assert.equal(lib.evaluationText("computed"), "새 계산 (computed)");
  assert.equal(lib.evaluationText("reused"), "저장된 결과 재사용 (reused)");
  assert.equal(lib.evaluationText(null), "—");
  assert.deepEqual([lib.decidedByText("jev"), lib.decidedByText("human"), lib.decidedByText(null)], ["JEV", "사람", "—"]);
  // M18 / M21 names: the M21 one first in the protein branch, docking_not_run its own
  assert.equal(lib.engineReasonText("box_too_large"), docking.dockingReasonText("box_too_large"));
  assert.equal(lib.engineReasonText("argument_invalid", true), mutationModel.modelReasonText("argument_invalid"));
  assert.equal(lib.engineReasonText("candidate_unknown", true), mutationModel.modelReasonText("candidate_unknown"));
  assert.equal(lib.engineReasonText("candidate_unknown", false), docking.dockingReasonText("candidate_unknown"));
  assert.equal(lib.engineReasonText("not_a_code"), jev.UNKNOWN_CODE_TEXT);
  assert.equal(lib.stepReasonText("dock", "docking_not_run"), "도킹하지 않음 (docking_not_run)");
  assert.equal(lib.stepReasonText("model", "coordinates_changed"), mutationModel.modelReasonText("coordinates_changed"));
  assert.equal(lib.stepReasonText("ligand_dock", null), null);
});

// ---- pool guard ----

const ligandRow = (n, passes = null) => ({ generation_order: n, candidate: { id: id16(n), smiles: SMILES(n) },
  filters: {}, passes_all: passes });
const ligandOption = (n, passes = null, source = LIG_SET) => jev.ligandCandidateOption(source, ligandRow(n, passes));
const mutationOption = (index, source = MUT_SET) => jev.mutationCandidateOption(source, { index });
function choose(selection, options) {
  return options.reduce((current, option) => {
    const out = jev.toggleJevCandidate(current, option, true);
    assert.equal(out.refused, null);
    return out.selection;
  }, selection);
}

test("pool guard: 2–20 candidates, the 21st check refused with its reason, fewer than 2 closes the create", () => {
  const empty = jev.emptyJevSelection("ligand", LIG_SET);
  assert.equal(lib.loopPoolCountText(empty), "선택 0/20 · 최소 2");
  assert.equal(lib.loopPoolCountText(null), "선택 0/20 · 최소 2");
  const one = choose(empty, [ligandOption(5)]);
  const two = choose(one, [ligandOption(2)]);
  const twenty = choose(empty, Array.from({ length: 20 }, (_, i) => ligandOption(i + 1)));
  for (const [selection, ok] of [[empty, false], [one, false], [two, true], [twenty, true]]) {
    const check = lib.loopPoolArgs("ligand", selection, null);
    assert.equal(check.ok, ok, `${selection.items.length} candidates`);
    if (!ok) assert.ok(check.errors.some(text => text.includes("2개 이상") && text.includes("(pool_invalid)")));
  }
  assert.equal(lib.loopPoolCountText(twenty), "선택 20/20 · 최소 2");
  // the 21st check is refused with its reason and changes nothing
  const refused = jev.toggleJevCandidate(twenty, ligandOption(21), true);
  assert.equal(refused.refused, jev.SELECTION_FULL_REASON);
  assert.equal(refused.selection, twenty);
  // a 21-candidate selection (never made by the guard) is refused by the request check too
  const over = { ...twenty, items: [...twenty.items, { key: id16(21), order: 21 }] };
  assert.ok(lib.loopPoolArgs("ligand", over, null).errors.some(text => text.includes("20개까지")));
  // unchecking frees a place; candidates go in the set's stored order, never twice
  const freed = jev.toggleJevCandidate(twenty, ligandOption(3), false).selection;
  assert.equal(jev.toggleJevCandidate(freed, ligandOption(21), true).refused, null);
  assert.equal(choose(two, []).items.length, 2);
  assert.equal(jev.toggleJevCandidate(two, ligandOption(5), true).selection.items.length, 2);
  const ordered = lib.loopPoolArgs("ligand", choose(empty, [ligandOption(9), ligandOption(2), ligandOption(5)]), null);
  assert.deepEqual(plain(ordered.args), { source: LIG_SET, candidates: [id16(2), id16(5), id16(9)], filter: null });
  assert.equal(lib.loopPoolArgs("ligand", null, null).ok, false);
});

test("pool guard: ligand candidates only when they pass the applied filter; protein by index, never a filter", () => {
  const empty = jev.emptyJevSelection("ligand", LIG_SET);
  assert.equal(jev.toggleJevCandidate(empty, ligandOption(4, false), true).refused, jev.FILTERED_OUT_REASON);
  const filter = { ranges: { mol_weight: { min: null, max: 300 } }, pains_exclude: false };
  const passing = choose(empty, [ligandOption(1, true), ligandOption(2, true)]);
  assert.deepEqual(plain(lib.loopPoolArgs("ligand", passing, filter).args.filter), filter);
  // a filter that applies nothing is sent as null
  assert.equal(lib.loopPoolArgs("ligand", passing, { ranges: {}, pains_exclude: false }).args.filter, null);
  // chosen candidates the current filter refuses close the request until unchecked
  const conflicts = jev.jevFilterConflicts(passing, [ligandRow(1, true), ligandRow(2, false)]);
  const blocked = lib.loopPoolArgs("ligand", passing, filter, conflicts);
  assert.equal(blocked.ok, false);
  assert.ok(blocked.errors[0].includes(id16(2)) && blocked.errors[0].includes("(pool_invalid)"));
  // protein: candidate indices, no filter; another branch's set is refused
  const mutation = choose(jev.emptyJevSelection("mutation", MUT_SET), [mutationOption(30), mutationOption(3)]);
  assert.deepEqual(plain(lib.loopPoolArgs("protein", mutation, null).args), { source: MUT_SET, candidates: [3, 30],
    filter: null });
  assert.equal(lib.loopPoolArgs("protein", mutation, filter).ok, false);
  assert.ok(lib.loopPoolArgs("protein", passing, null).errors.some(text => text.includes("이 갈래의 후보 집합이 아닙니다")));
  assert.equal(jev.toggleJevCandidate(mutation, ligandOption(1), true).refused, jev.SOURCE_MISMATCH_REASON);
});

// ---- settings, setup and the create request ----

test("loop settings: goal never chosen automatically, seed required 0–2147483647, iteration cap 1–8 (default 5)", () => {
  const initial = lib.initialLoopSettings();
  assert.deepEqual(plain(initial), { goal: null, loopSeed: "", iterationCap: "5" });
  const blank = lib.checkLoopSettings(initial);
  assert.equal(blank.ok, false);
  assert.match(blank.fields.goal, /\(goal_invalid\)/);
  assert.match(blank.fields.loop_seed, /\(seed_invalid\)/);
  assert.equal(blank.fields.iteration_cap, null);
  const settings = over => lib.checkLoopSettings({ goal: "explore", loopSeed: "0", iterationCap: "5", ...over });
  for (const [cap, ok] of [["0", false], ["1", true], ["8", true], ["9", false], ["", false], ["05", false],
    ["1.5", false], ["-1", false], [" 3 ", true], ["1e0", false]]) {
    const check = settings({ iterationCap: cap });
    assert.equal(check.ok, ok, `cap ${JSON.stringify(cap)}`);
    if (!ok) assert.match(check.fields.iteration_cap, /\(iteration_cap_invalid\)/);
  }
  for (const [seed, ok] of [["", false], ["0", true], ["2147483647", true], ["2147483648", false], ["-1", false],
    ["7.0", false], ["abc", false], ["00", false]]) {
    const check = settings({ loopSeed: seed });
    assert.equal(check.ok, ok, `seed ${JSON.stringify(seed)}`);
    if (!ok) assert.match(check.fields.loop_seed, /\(seed_invalid\)/);
  }
  assert.deepEqual(plain(settings({ goal: "exploit", loopSeed: "2147483647", iterationCap: "8" })), { ok: true,
    goal: "exploit", loopSeed: 2147483647, iterationCap: 8, fields: { goal: null, loop_seed: null, iteration_cap: null } });
  assert.equal(settings({ goal: "neutral" }).ok, false);
  assert.deepEqual(Object.keys(lib.GOAL_MEANING), ["explore", "exploit"]);
});

const dockingTriple = ["1.5", "-2", "3.25"];
function ligandForm(over = {}) {
  return lib.patchLigandLoopSetupForm(lib.initialLigandLoopSetupForm(), { receptorHandle: "rec", receptorModelNumber: 1,
    connectivity: "pdb_conect", instance: { kind: "none" }, parentSdfHandle: "parent", boxSource: "manual",
    center: dockingTriple, size: ["20", "20", "20"], seed: "11", acknowledgement: { keep_input_protonation: true,
      tool_assigned_types_charges: true, rigid_no_optimization: true }, ...over });
}
function proteinForm(over = {}) {
  return lib.patchProteinLoopSetupForm(lib.initialProteinLoopSetupForm(), { sdfHandle: "sdf", boxSource: "ligand_range",
    seed: "20261007", selectionConfirmed: true, hydrogenConfirmed: true, acknowledgement: { keep_input_protonation: true,
      tool_assigned_types_charges: true, rigid_no_optimization: true }, ...over });
}

test("ligand setup: the M22 shared M18 fields and the parent SDF exactly; free docking and the candidate source fixed", () => {
  const backendKeys = [...pyTuple("M18_KEYS", backend("ligand_ga_inputs.py")), "parent_sdf_handle"];
  const check = lib.ligandLoopSetup(ligandForm(), LIG_SET);
  assert.equal(check.ok, true, JSON.stringify(check));
  assert.deepEqual(Object.keys(check.args).sort(), [...backendKeys].sort());
  assert.deepEqual(plain(check.args), { receptor_handle: "rec", receptor_model_number: 1,
    connectivity: { kind: "pdb_conect", sidecar_handle: null }, receptor_instance: null,
    box: { source: "manual", center_A: [1.5, -2, 3.25], size_A: [20, 20, 20] },
    parameters: { seed: 11, exhaustiveness: 8, num_modes: 9, energy_range: 3 },
    acknowledgement: { keep_input_protonation: true, tool_assigned_types_charges: true, rigid_no_optimization: true },
    parent_sdf_handle: "parent" });
  // a patch never moves the source or the mode
  const form = lib.patchLigandLoopSetupForm(ligandForm(), { ligandSource: "sdf", mode: "core_fixed" });
  assert.equal(form.ligandSource, "candidate");
  assert.equal(form.mode, "free");
  // the M18 reasons, all at once
  const missing = lib.ligandLoopSetup(lib.initialLigandLoopSetupForm(), LIG_SET);
  assert.equal(missing.ok, false);
  for (const part of ["수용체 가져오기를 고르세요.", "부모 3D SDF", "상자 출처를 고르세요.", "seed:", "(acknowledgement_missing)"])
    assert.ok(missing.errors.some(text => text.includes(part)), part);
  assert.ok(lib.ligandLoopSetup(ligandForm({ size: ["41", "20", "20"] }), LIG_SET).errors[0].includes("(box_too_large)"));
  assert.equal(lib.ligandLoopSetup(ligandForm({ boxSource: "instance_range", margin: "8" }), LIG_SET).ok, false);
});

test("protein setup: SDF ligand, M18 box / free values / acknowledgements, the two literals and cutoff 2.5–6.0 (4.0)", () => {
  const backendKeys = pyTuple("PROTEIN_SETUP_KEYS", backend("jev_loop_store.py"));
  assert.equal(lib.initialProteinLoopSetupForm().cutoff, "4.0");
  const check = lib.proteinLoopSetup(proteinForm());
  assert.equal(check.ok, true, JSON.stringify(check));
  assert.deepEqual(Object.keys(check.args).sort(), [...backendKeys].sort());
  assert.deepEqual(plain(check.args), { ligand: { source: "sdf", sdf_handle: "sdf" },
    box: { source: "ligand_range", margin_A: 8 }, parameters: { seed: 20261007, exhaustiveness: 8, num_modes: 9,
      energy_range: 3 }, selection_policy: "protein_only", hydrogen_policy: "rebuild_pH7",
    acknowledgement: { keep_input_protonation: true, tool_assigned_types_charges: true, rigid_no_optimization: true },
    contact_cutoff_A: 4 });
  for (const [cutoff, ok] of [["2.5", true], ["6.0", true], ["2.4", false], ["6.1", false], ["", false], ["4e0", false]]) {
    const result = lib.proteinLoopSetup(proteinForm({ cutoff }));
    assert.equal(result.ok, ok, cutoff);
    if (!ok) assert.ok(result.errors.some(text => text.includes("(argument_invalid)")));
  }
  assert.ok(lib.proteinLoopSetup(proteinForm({ hydrogenConfirmed: false })).errors.includes(lib.CONFIRMATION_ERROR));
  // an instance-range box and a candidate ligand cannot be chosen (no instance in a protein-only model; SDF only)
  const patched = lib.patchProteinLoopSetupForm(proteinForm(), { boxSource: "instance_range", ligandSource: "candidate" });
  assert.equal(patched.boxSource, null);
  assert.equal(patched.ligandSource, "sdf");
  assert.equal(lib.proteinLoopSetup(lib.initialProteinLoopSetupForm()).ok, false);
});

test("create request: per-field reasons, the exact body, one loop_id per pressed body until a record answers", () => {
  const pool = lib.loopPoolArgs("ligand", choose(jev.emptyJevSelection("ligand", LIG_SET), [ligandOption(1),
    ligandOption(2)]), null);
  const setup = lib.ligandLoopSetup(ligandForm(), LIG_SET);
  const settings = { goal: "exploit", loopSeed: "42", iterationCap: "5" };
  const blocked = lib.loopCreateRequest({ branch: "ligand", pool: lib.loopPoolArgs("ligand", null, null),
    settings: lib.initialLoopSettings(), setup: lib.ligandLoopSetup(lib.initialLigandLoopSetupForm(), LIG_SET) });
  assert.equal(blocked.ok, false);
  assert.deepEqual(Object.keys(blocked.fields), plain(lib.LOOP_CREATE_FIELDS));
  for (const field of ["pool", "goal", "loop_seed", "setup"]) assert.ok(blocked.fields[field].length > 0, field);
  assert.deepEqual(plain(blocked.fields.iteration_cap), []);
  const made = lib.loopCreateRequest({ branch: "ligand", pool, settings, setup });
  assert.equal(made.ok, true);
  assert.deepEqual(Object.keys(made.request).sort(), pyTuple("CREATE_KEYS").filter(key => key !== "loop_id").sort());
  // one loop_id per pressed body: a retry (double click, network error) is the same loop
  let n = 0;
  const make = () => `00000000-0000-4000-8000-00000000000${++n}`;
  const first = lib.loopCreateAttempt(null, made.request, make);
  assert.equal(lib.loopCreateAttempt(first, made.request, make), first);
  const body = lib.loopCreateBody(first, made.request);
  assert.equal(body.loop_id, first.loopId);
  assert.deepEqual(Object.keys(body).sort(), [...pyTuple("CREATE_KEYS")].sort());
  assert.equal(lib.loopCreateAttemptAfter(first, { record: false, code: null }), first);
  assert.equal(lib.loopCreateAttemptAfter(first, { record: false, code: "busy" }), first);
  assert.equal(lib.loopCreateAttemptAfter(first, { record: true }), null);
  assert.equal(lib.loopCreateAttemptAfter(first, { record: false, code: "loop_id_conflict" }), null);
  // another body is another loop
  const changed = lib.loopCreateRequest({ branch: "ligand", pool, settings: { ...settings, loopSeed: "43" }, setup });
  assert.notEqual(lib.loopCreateAttempt(first, changed.request, make).loopId, first.loopId);
  assert.match(lib.newLoopId(), jev.UUID_V4_RE);
});

test("server create refusals land on their field: all eleven admission reasons and loop_id_conflict", () => {
  const expected = { unknown_field: "general", loop_id_invalid: "general", dry_run: "general", branch_invalid: "general",
    capability_unavailable: "general", loop_active: "general", pool_invalid: "pool", goal_invalid: "goal",
    seed_invalid: "loop_seed", iteration_cap_invalid: "iteration_cap", setup_invalid: "setup",
    loop_id_conflict: "general" };
  assert.deepEqual(Object.keys(expected), [...lib.LOOP_CREATE_REASONS, lib.LOOP_ID_CONFLICT]);
  const refusal = (reason, extra = {}, status = 422) => Object.assign(new Error("english server text"), { status,
    code: status === 422 ? "input_invalid" : reason, detail: { error: status === 422 ? "input_invalid" : reason,
      reason_code: reason, message: "english server text", ...extra } });
  for (const [reason, field] of Object.entries(expected)) {
    const out = lib.loopCreateRefusal(refusal(reason), "ligand");
    assert.equal(out.field, field, reason);
    assert.equal(out.reasonCode, reason);
    assert.ok(out.text.startsWith(lib.createReasonText(reason)), reason);
    assert.ok(!out.text.includes("english server text"));
  }
  // setup_reason (M18 / M21 closed names), the refused candidates and the engine reason are shown with their codes
  const setupLigand = lib.loopCreateRefusal(refusal("setup_invalid", { setup_reason: "box_too_large" }), "ligand");
  assert.equal(setupLigand.text, `${lib.createReasonText("setup_invalid")}: ${docking.dockingReasonText("box_too_large")}`);
  const setupProtein = lib.loopCreateRefusal(refusal("setup_invalid", { setup_reason: "argument_invalid" }), "protein");
  assert.ok(setupProtein.text.endsWith(mutationModel.modelReasonText("argument_invalid")));
  assert.ok(lib.loopCreateRefusal(refusal("setup_invalid", { setup_reason: "made_up" }), "ligand").text
    .endsWith(jev.UNKNOWN_CODE_TEXT));
  const pool = lib.loopCreateRefusal(refusal("pool_invalid", { candidates: [id16(9), id16(8)] }), "ligand");
  assert.equal(pool.field, "pool");
  assert.ok(pool.text.endsWith(`해당 후보: ${id16(9)}, ${id16(8)}`));
  const capability = lib.loopCreateRefusal(refusal("capability_unavailable", { capability: { reason_code: "worker_missing",
    reason: "도킹 작업 환경이 없다." } }, 412), "ligand");
  assert.ok(capability.text.endsWith(": 도킹 작업 환경이 없다. (worker_missing)"));
  // anything else stays in the general area with a fixed text
  assert.deepEqual(plain(lib.loopCreateRefusal(refusal("made_up"), "ligand")), { field: "general", reasonCode: "made_up",
    text: jev.UNKNOWN_CODE_TEXT });
  assert.equal(lib.loopCreateRefusal({ status: 503, code: "busy", detail: { error: "busy", message: "x" } }, "ligand").field,
    "general");
  assert.equal(lib.loopCreateRefusal("network down", "ligand").text, jev.REQUEST_FAILED_TEXT);
  // the local guard: one unended loop per branch
  const rows = [{ branch: "protein", status: "active" }, { branch: "ligand", status: "ended" }];
  assert.equal(lib.loopCreateBlockedReason(rows, "ligand"), null);
  assert.equal(lib.loopCreateBlockedReason(rows, "protein"), lib.createReasonText("loop_active"));
});

// ---- the record: phase actions and buttons ----

const enabled = view => Object.entries(view.buttons).filter(([, state]) => state.enabled).map(([name]) => name).sort();

test("phase awaiting_selection: send or name a candidate; no JEV choice to compute; end allowed", () => {
  const view = lib.loopActionView(ligandRecord(), { busy: false });
  assert.equal(view.action, "select");
  assert.deepEqual(enabled(view), ["build", "designate", "end"]);
  assert.equal(view.iterationText, "바퀴 4");
  assert.equal(view.phaseText, lib.phaseText("awaiting_selection"));
  assert.equal(view.selection, null);
  assert.ok(view.buttons.computeProposal.reasons[0].startsWith("지금은"));
  assert.equal(view.progressText, "시작한 바퀴 3 · 끝난 바퀴 3 · 유효 반복 상한 5(반복 상한 5, 풀 7개)");
  // one pending candidate or none: the server's needs.sends is 0 and no send is offered
  const single = lib.loopActionView(ligandRecord({ current: current({ needs: amounts({ sends: 0 }) }) }), { busy: false });
  assert.deepEqual(plain(single.buttons.build.reasons), [lib.loopProjectionReasonText("too_few_candidates")]);
  assert.equal(single.buttons.designate.enabled, true);
  // a send in flight: can_end false from the server
  const sending = lib.loopActionView(ligandRecord({ current: current({ can_end: false }) }), { busy: false });
  assert.deepEqual(plain(sending.buttons.end.reasons), [lib.endRefusalText("send_in_progress")]);
  // a request of the area in flight closes everything
  const busy = lib.loopActionView(ligandRecord(), { busy: true });
  assert.deepEqual(enabled(busy), []);
  for (const state of Object.values(busy.buttons)) assert.ok(state.reasons.includes(lib.BUSY_REASON));
});

test("phase awaiting_compute: the iteration's one JEV selection, approved only for a still pending candidate", () => {
  const record = computeRecord();
  const pending = lib.loopActionView(record, { busy: false, proposalRef: id16(3) });
  assert.equal(pending.action, "compute");
  assert.deepEqual(plain(pending.selection), { sendId: SID_2, proposalHandle: CHOICE_4 });
  assert.deepEqual(enabled(pending), ["computeProposal", "designate", "end"]);
  assert.deepEqual(plain(pending.buttons.build.reasons), [lib.loopProjectionReasonText("selection_done")]);
  assert.deepEqual(plain(lib.loopProposalComputeRequest(record, CHOICE_4)), { iteration: 4, proposal: CHOICE_4 });
  assert.deepEqual(plain(lib.loopCandidateComputeRequest(record, id16(7))), { iteration: 4, candidate: id16(7) });
  // not read yet / unreadable / computed meanwhile / unavailable / outside the pool
  for (const [ref, reason] of [[undefined, "JEV 판정을 읽는 중입니다."], [null, lib.CHOICE_MISMATCH_TEXT],
    [id16(4), lib.computeReasonText("candidate_computed")], [id16(1), lib.computeReasonText("candidate_computed")],
    [id16(5), lib.computeReasonText("candidate_unavailable")], [id16(99), lib.computeReasonText("candidate_invalid")]]) {
    const view = lib.loopActionView(record, { busy: false, proposalRef: ref });
    assert.deepEqual(plain(view.buttons.computeProposal.reasons), [reason], String(ref));
    assert.equal(view.buttons.designate.enabled, true);
  }
  // the compute side is short: both first-step buttons show the server's axes and amounts, verbatim
  const short = lib.loopActionView(computeRecord({ current: current({ phase: "awaiting_compute", action: "compute",
    needs: amounts({ sends: 0 }), remaining: amounts({ expensive_units: 0, wall_clock_s: 120, sends: 9 }),
    blocked_axes: ["expensive_units", "wall_clock_s"] }) }), { busy: false, proposalRef: id16(3) });
  const reasons = ["비싼 계산 단위 (expensive_units) 모자람: 필요 1단위 · 남은 0단위",
    "활동 시간 (wall_clock_s) 모자람: 필요 300초 · 남은 120초"];
  assert.deepEqual(plain(short.computeBlockedTexts), reasons);
  assert.deepEqual(plain(short.buttons.computeProposal.reasons), reasons);
  assert.deepEqual(plain(short.buttons.designate.reasons), reasons);
  assert.equal(short.buttons.end.enabled, true);
  assert.deepEqual(plain(short.axisRows.filter(row => row.blocked).map(row => row.axis)), ["expensive_units", "wall_clock_s"]);
});

test("phase running: only the waiting job's start (first expensive-call approval) and cancel; end refused", () => {
  const job = { job_id: "job-7", step: "ligand_dock", status: "claimed", start_blocked: "approval_required" };
  const base = ligandRecord();
  const record = { ...base, iterations: [...base.iterations, iteration({ index: 4, phase: "running", decided_by: "human",
    candidate_ref: id16(7), proposal_handle: null, list_position: null, list_size: null, sends: [],
    steps: [step({ candidate_ref: id16(7), job_id: "job-7", result_handle: null, state: "waiting_start",
      evaluation: null })], state: "in_progress", score_kcal_mol: null })],
  current: current({ phase: "running", action: "wait_job", needs: amounts({ expensive_units: 0, wall_clock_s: 0, sends: 0 }),
    can_end: false, job }) };
  const view = lib.loopActionView(record, { busy: false });
  assert.deepEqual(enabled(view), ["cancelJob", "startJob"]);
  assert.equal(view.approvalGuide, lib.FIRST_APPROVAL_GUIDE);
  assert.equal(view.cancelNote, lib.CANCEL_BEFORE_START_NOTE);
  assert.equal(view.jobText, `작업 job-7 · ${lib.stepText("ligand_dock")} · ${lib.loopJobStatusText("claimed")}`);
  assert.deepEqual(plain(view.buttons.end.reasons), [lib.endRefusalText("job_running")]);
  assert.deepEqual(plain(lib.loopResumeRequest(record)), { iteration: 4, candidate: id16(7) });
  // a JEV-decided iteration resumes with its proposal; a running job takes no start or cancel here
  const jevRecord = { ...record, iterations: record.iterations.map(it => it.index === 4
    ? { ...it, decided_by: "jev", proposal_handle: CHOICE_4, candidate_ref: id16(3) } : it) };
  assert.deepEqual(plain(lib.loopResumeRequest(jevRecord)), { iteration: 4, proposal: CHOICE_4 });
  const running = lib.loopActionView({ ...record, current: { ...record.current, job: { ...job, status: "running",
    start_blocked: null } } }, { busy: false });
  assert.deepEqual(enabled(running), []);
  assert.equal(running.approvalGuide, null);
  assert.equal(running.cancelNote, null);
  assert.equal(lib.loopResumeRequest(ligandRecord()), null);
});

test("protein awaiting_docking: dock or abandon; dock closes on a short compute side; end waits for the decision", () => {
  const record = proteinRecord();
  const view = lib.loopActionView(record, { busy: false });
  assert.equal(view.action, "dock");
  assert.deepEqual(enabled(view), ["abandon", "dock"]);
  assert.deepEqual(plain(view.buttons.end.reasons), [lib.endRefusalText("docking_pending")]);
  assert.deepEqual(plain(lib.loopDockRequest(record)), { iteration: 1 });
  assert.deepEqual(plain(lib.loopAbandonRequest(record)), { iteration: 1 });
  const short = lib.loopActionView(proteinRecord({ current: { ...record.current, blocked_axes: ["expensive_units"],
    remaining: amounts({ expensive_units: 0, wall_clock_s: 1400, sends: 10 }) } }), { busy: false });
  assert.deepEqual(enabled(short), ["abandon"]);
  assert.deepEqual(plain(short.buttons.dock.reasons), ["비싼 계산 단위 (expensive_units) 모자람: 필요 1단위 · 남은 0단위"]);
  // the docking step resumes with the iteration only
  const docking = proteinRecord({ current: { ...record.current, phase: "running", action: "wait_job",
    job: { job_id: "job-d", step: "dock", status: "queued", start_blocked: null } } });
  assert.deepEqual(plain(lib.loopResumeRequest(docking)), { iteration: 1 });
});

test("exhausted, then ended: end is the only action; an ended loop closes everything and names its reason", () => {
  const exhausted = ligandRecord({ exhausted_reason: "pool_exhausted", current: current({ iteration: null, phase: null,
    step: null, action: "end", needs: amounts({ expensive_units: 0, wall_clock_s: 0, sends: 0 }) }) });
  const view = lib.loopActionView(exhausted, { busy: false });
  assert.deepEqual(enabled(view), ["end"]);
  assert.equal(view.exhaustedText, `${lib.exhaustedReasonText("pool_exhausted")}: 루프 끝내기를 누르면 요약을 만듭니다.`);
  assert.equal(view.iterationText, "—");
  assert.equal(lib.loopProjectionArgs(exhausted), null);
  const ended = ligandRecord({ status: "ended", end_reason: "ended_by_user", result_handle: SUMMARY_H,
    current: current({ iteration: null, phase: null, step: null, action: "none", can_end: false,
      needs: amounts({ expensive_units: 0, wall_clock_s: 0, sends: 0 }) }) });
  const endedView = lib.loopActionView(ended, { busy: false });
  assert.deepEqual(enabled(endedView), []);
  for (const state of Object.values(endedView.buttons))
    assert.deepEqual(plain(state.reasons), [lib.endRefusalText("loop_ended")]);
  assert.equal(endedView.statusText, `끝남 (ended) · ${lib.endReasonText("ended_by_user")}`);
  assert.deepEqual(plain(lib.loopStatusView(ended)), { ended: true, resultHandle: SUMMARY_H,
    statusText: `끝남 (ended) · ${lib.endReasonText("ended_by_user")}`, reportBlockedReason: null });
  const cancelled = lib.loopStatusView({ ...ended, end_reason: "run_cancelled", result_handle: null });
  assert.equal(cancelled.resultHandle, null);
  assert.ok(cancelled.reportBlockedReason.includes("(run_cancelled)"));
  assert.ok(lib.loopStatusView(ligandRecord()).reportBlockedReason !== null);
  assert.equal(lib.loopSelectableCandidates(ended).length, 0);
  // the projection of the current iteration only while awaiting a selection
  assert.deepEqual(plain(lib.loopProjectionArgs(ligandRecord())), { loop_id: LOOP, iteration: 4 });
  assert.equal(lib.loopProjectionArgs(computeRecord()), null);
});

test("send-side axes and amounts are the server's values (tokens and USD only with a preview reservation)", () => {
  const record = ligandRecord({ current: current({ remaining: amounts({ expensive_units: 5, wall_clock_s: 1500, sends: 0 }),
    send_blocked_axes: ["sends"] }) });
  const view = lib.loopActionView(record, { busy: false });
  assert.deepEqual(plain(view.sendBlockedTexts), ["과학 전송 횟수 (sends) 모자람: 필요 1회 · 남은 0회"]);
  const tokens = view.axisRows.find(row => row.axis === "external_tokens");
  assert.deepEqual(plain(tokens), { axis: "external_tokens", label: lib.axisText("external_tokens"), needText: "—",
    remainingText: "—", blocked: false });
  const rows = lib.loopAxisRows(preview().loop.needs, preview().loop.remaining, ["usd"]);
  assert.deepEqual(plain(rows.map(row => [row.axis, row.needText, row.remainingText, row.blocked])), [
    ["expensive_units", "1단위", "5단위", false], ["wall_clock_s", "300초", "1500초", false],
    ["external_tokens", "4200", "110000", false], ["usd", "0.1000 USD", "1.9000 USD", true], ["sends", "1회", "9회", false]]);
  assert.equal(lib.loopAxisReason("made_up", null, null), jev.UNKNOWN_CODE_TEXT);
});

// ---- the record: candidate table, order, iterations ----

test("candidate table: notation, six states, evaluation, iteration, chooser, score values only, no score is never 0", () => {
  const rows = lib.loopCandidateRows(ligandRecord());
  assert.deepEqual(plain(rows.map(row => [row.refText, row.displayText, row.state, row.evaluationText, row.scoreText,
    row.iterationText, row.decidedByText, row.resultHandle, row.selectable])), [
    [`후보 ${id16(1)}`, SMILES(1), "scored", "새 계산 (computed)", "-7.3", "바퀴 1", "JEV", RES("1"), false],
    [`후보 ${id16(2)}`, SMILES(2), "null_result", "새 계산 (computed)", "— (도킹 모드 0개(빈 결과))", "바퀴 2", "사람",
      RES("2"), false],
    [`후보 ${id16(3)}`, SMILES(3), "pending", "—", "— (계산하지 않음)", "—", "—", null, true],
    [`후보 ${id16(4)}`, SMILES(4), "scored", "저장된 결과 재사용 (reused)", "-6.1", "—", "—", null, false],
    [`후보 ${id16(5)}`, SMILES(5), "unavailable", "—", "— (이 run에서 계산할 수 없음)", "—", "—", null, false],
    [`후보 ${id16(6)}`, SMILES(6), "failed", "새 계산 (computed)",
      `— (작업 실패: ${docking.dockingReasonText("engine_failed")})`, "바퀴 3", "사람", null, false],
    [`후보 ${id16(7)}`, SMILES(7), "pending", "—", "— (계산하지 않음)", "—", "—", null, true],
  ]);
  assert.deepEqual(plain(rows.map(row => row.score)), [-7.25, null, null, -6.05, null, null, null]);
  for (const row of rows) {
    if (row.score === null) assert.ok(row.scoreText.startsWith("— (") && !/^-?0(\.0)?$/.test(row.scoreText));
    for (const key of ["rank", "best", "highlight", "difference", "delta", "lowest", "change"]) assert.ok(!(key in row), key);
  }
  assert.deepEqual(plain(lib.loopSelectableCandidates(ligandRecord()).map(row => row.ref)), [id16(3), id16(7)]);
  // protein notation: residue · from→to, by candidate index
  const protein = lib.loopCandidateRows(proteinRecord());
  assert.equal(protein[0].refText, "후보 번호 12");
  assert.equal(protein[0].displayText, `${jev.residueText(RESIDUE)} · K→A`);
  assert.equal(protein[0].selectable, false);         // awaiting_docking: no first step can be approved
  const notRun = lib.loopCandidateRows(proteinRecord({ candidates: [{ ...proteinRecord().candidates[0], state: "not_run",
    evaluation: "computed", iteration: 1 }, ...proteinRecord().candidates.slice(1)] }));
  assert.equal(notRun[0].scoreText, "— (도킹하지 않음 (docking_not_run))");
});

test("candidate order: display only; rows without a score are last in every column and direction, ties in pool order", () => {
  const rows = lib.loopCandidateRows(ligandRecord());
  const refs = sorted => plain(sorted.map(row => row.ref));
  const tail = [id16(2), id16(3), id16(5), id16(6), id16(7)];
  assert.deepEqual(refs(lib.sortLoopCandidates(rows, null)), [id16(1), id16(4), ...tail]);
  assert.deepEqual(refs(lib.sortLoopCandidates(rows, { key: "score", direction: "asc" })), [id16(1), id16(4), ...tail]);
  assert.deepEqual(refs(lib.sortLoopCandidates(rows, { key: "score", direction: "desc" })), [id16(4), id16(1), ...tail]);
  assert.deepEqual(refs(lib.sortLoopCandidates(rows, { key: "pool", direction: "desc" })), [id16(4), id16(1), ...tail]);
  assert.deepEqual(refs(lib.sortLoopCandidates(rows, { key: "candidate", direction: "desc" })), [id16(4), id16(1), ...tail]);
  // a reused row has no iteration and stays after numbered rows in both directions
  assert.deepEqual(refs(lib.sortLoopCandidates(rows, { key: "iteration", direction: "asc" })), [id16(1), id16(4), ...tail]);
  assert.deepEqual(refs(lib.sortLoopCandidates(rows, { key: "iteration", direction: "desc" })), [id16(1), id16(4), ...tail]);
  // equal scores keep the pool order (stable); the input is never changed
  const same = rows.map(row => row.score === null ? row : { ...row, score: -5 });
  for (const direction of ["asc", "desc"])
    assert.deepEqual(refs(lib.sortLoopCandidates(same, { key: "score", direction })), [id16(1), id16(4), ...tail]);
  assert.deepEqual(refs(rows), [1, 2, 3, 4, 5, 6, 7].map(id16));
  // protein refs (indices) sort as numbers
  const protein = [{ position: 0, ref: 12, score: -4, iteration: 1 }, { position: 1, ref: 3, score: -4, iteration: 2 },
    { position: 2, ref: 30, score: null, iteration: null }];
  assert.deepEqual(plain(lib.sortLoopCandidates(protein, { key: "candidate", direction: "asc" }).map(row => row.ref)),
    [3, 12, 30]);
  assert.deepEqual(plain(lib.nextLoopSort(null, "score")), { key: "score", direction: "asc" });
  assert.deepEqual(plain(lib.nextLoopSort({ key: "score", direction: "asc" }, "score")), { key: "score", direction: "desc" });
  assert.deepEqual(plain(lib.nextLoopSort({ key: "score", direction: "desc" }, "pool")), { key: "pool", direction: "asc" });
  assert.equal(lib.loopAriaSort({ key: "score", direction: "desc" }, "score"), "descending");
  assert.equal(lib.loopAriaSort({ key: "score", direction: "desc" }, "pool"), "none");
});

test("iteration rows: who chose, list position n/m as recorded, each send on its own, step states and reasons", () => {
  const rows = lib.loopIterationRows(computeRecord());
  assert.deepEqual(plain(rows.map(row => [row.index, row.decidedByText, row.candidateText, row.listPositionText,
    row.scoreText])), [[1, "JEV", SMILES(1), "2/5", "-7.3"], [2, "사람", SMILES(2), "—",
    `— (${lib.iterationStateText("null_result")})`], [3, "사람", SMILES(6), "—", `— (${lib.iterationStateText("failed")})`],
  [4, "—", "—", "—", `— (${lib.iterationStateText("in_progress")})`]]);
  assert.deepEqual(plain(rows[2].steps[0]), { stepText: lib.stepText("ligand_dock"), stateText: lib.stepStateText("failed"),
    reasonText: docking.dockingReasonText("engine_failed"), jobId: "job-6", resultHandle: null, candidateText: SMILES(6) });
  assert.deepEqual(plain(rows[3].sends), [
    { sendId: SID, statusText: jev.sendStatusText("failed"), ordinalText: "전송 순번 0", lateText: null, proposalHandle: null },
    { sendId: SID_2, statusText: jev.sendStatusText("completed"), ordinalText: "전송 순번 1", lateText: null,
      proposalHandle: CHOICE_4 }]);
});

test("the iteration's JEV selection is its one completed, not-late send with a proposal handle", () => {
  const it = sends => ({ ...iteration(), sends });
  assert.deepEqual(plain(lib.loopIterationSelection(it([send()]))), { sendId: SID, proposalHandle: CHOICE_1 });
  assert.equal(lib.loopIterationSelection(it([send({ late: true })])), null);
  assert.equal(lib.loopIterationSelection(it([send({ proposal_handle: null })])), null);
  assert.equal(lib.loopIterationSelection(it([send({ status: "failed" })])), null);
  assert.equal(lib.loopIterationSelection(it([send({ status: "in_progress", proposal_handle: null })])), null);
  assert.equal(lib.loopIterationSelection(it([])), null);
  assert.equal(lib.loopIterationSelection(null), null);
  // a late proposal next to the selection does not hide it; two selections (never written) are not guessed
  assert.deepEqual(plain(lib.loopIterationSelection(it([send({ send_id: SID_2, late: true, proposal_handle: CHOICE_4 }),
    send()]))), { sendId: SID, proposalHandle: CHOICE_1 });
  assert.equal(lib.loopIterationSelection(it([send(), send({ send_id: SID_2, proposal_handle: CHOICE_4 })])), null);
});

// ---- preview and approval ----

test("loop preview: exact body, bytes and SHA-256 as given, alias table not sent, shuffle record, loop blocks", () => {
  const record = ligandRecord();
  assert.equal(lib.jevLoopPreviewMatches(preview(), PROJ, LOOP), true);
  assert.equal(lib.jevLoopPreviewMatches(preview(), PROJ, LOOP_P), false);
  assert.equal(lib.jevLoopPreviewMatches(preview(), `obj://${RUN}/jev_loop_projection/${hex("7")}`, LOOP), false);
  assert.equal(lib.jevLoopPreviewMatches({ ...preview(), loop_blocks: undefined }, PROJ, LOOP), false);
  assert.equal(lib.jevLoopPreviewMatches({ ...preview(), question: { ...preview().question,
    id: "ligand_candidate_choice@1" } }, PROJ, LOOP), false);
  const view = lib.jevLoopPreviewView(preview(), record);
  assert.equal(view.body, BODY);
  assert.equal(view.bodySha256, hex("d"));
  assert.equal(view.bodyBytesText, `${BODY.length} 바이트`);
  assert.equal(view.instructions, preview().question.instructions);
  assert.equal(view.confirmText, "이 본문 그대로 외부 서비스(JEV)로 보내는 데 동의합니다");
  assert.equal(view.orderText, "후보 순서·별칭: sha256_order_v1로 섞음 · 루프 seed 20261007 · 바퀴 4 · 전송 순번 1");
  assert.deepEqual(plain(view.aliasRows.slice(0, 2)), [
    { alias: "c01", refText: `후보 ${id16(7)}`, displayText: SMILES(7), stateText: lib.candidateStateText("pending"),
      choosableText: "JEV가 고를 수 있음", sentText: "전송하지 않음" },
    { alias: "c02", refText: `후보 ${id16(1)}`, displayText: SMILES(1), stateText: lib.candidateStateText("scored"),
      choosableText: "계산됨(JEV가 고를 수 없음)", sentText: "전송하지 않음" }]);
  assert.deepEqual(plain(view.aliasRows.map(row => row.alias)), SELECTION.map(item => item.alias));
  assert.equal(view.reservationText, `예약: 외부 토큰 ${preview().reservation.external_tokens} · 0.1000 USD`);
  assert.equal(view.capText, "run당 과학 전송 10회 · 사용 1회 · 남은 9회");
  assert.deepEqual(plain(view.loopBlocks), []);
  const blocked = lib.jevLoopPreviewView(preview({ blocked_by: ["consent_off"], loop_blocks: ["state_changed"] }), record);
  assert.deepEqual(plain(blocked.loopBlocks), [{ code: "state_changed", text: lib.loopSendReasonText("state_changed") }]);
  assert.deepEqual(plain(blocked.blocked.map(item => item.code)), ["consent_off"]);
});

test("send button: M24 refusals, loop refusals, a send in flight and the unchecked confirmation all close it", () => {
  assert.deepEqual(plain(lib.jevLoopSendBlockers({ preview: null, confirmed: true, sending: false })),
    ["먼저 보낼 내용을 만들고 미리보기를 읽으세요."]);
  assert.equal(lib.jevLoopCanSend({ preview: preview(), confirmed: true, sending: false }), true);
  assert.equal(lib.jevLoopCanSend({ preview: preview(), confirmed: false, sending: false }), false);
  assert.equal(lib.jevLoopCanSend({ preview: preview(), confirmed: true, sending: true }), false);
  const reasons = lib.jevLoopSendBlockers({ preview: preview({ blocked_by: ["send_cap_exhausted"],
    loop_blocks: ["ordinal_mismatch"] }), confirmed: false, sending: true });
  assert.deepEqual(plain(reasons), [jev.blockReasonText("send_cap_exhausted"), lib.loopSendReasonText("ordinal_mismatch"),
    "전송 중입니다. 응답이 올 때까지 기다리세요(한 번에 한 전송).",
    `확인 체크를 켜세요: "이 본문 그대로 외부 서비스(JEV)로 보내는 데 동의합니다".`]);
  // the confirmation is bound to the exact previewed body hash (M24 rule)
  assert.equal(jev.jevConfirmed(hex("d"), preview()), true);
  assert.equal(jev.jevConfirmed(hex("e"), preview()), false);
});

test("send_id is made at the first press and kept until a record answers (double click and retry are one send)", () => {
  let n = 0;
  const make = () => `00000000-0000-4000-8000-00000000000${++n}`;
  const first = jev.jevSendAttempt(null, preview(), make);
  assert.equal(jev.jevSendAttempt(first, preview(), make), first);                       // double click
  assert.deepEqual(plain(jev.jevSendRequest(first)), { send_id: first.sendId, projection: PROJ, body_sha256: hex("d"),
    confirm: "send_to_jev" });
  // a refused loop send (409 loop_send_invalid, nothing recorded) keeps the same id for the same body
  const refused = Object.assign(new Error("x"), { status: 409, code: "loop_send_invalid",
    detail: { error: "loop_send_invalid", message: "x", reason: "state_changed" } });
  const kept = jev.jevAttemptAfter(first, { record: false, code: lib.loopErrorInfo(refused).code });
  assert.equal(kept, first);
  assert.equal(jev.jevAttemptAfter(first, { record: false, code: null }), first);         // network error, retry
  assert.equal(jev.jevAttemptAfter(first, { record: true }), null);                        // the record arrived
  // a new projection or body is a new send
  assert.notEqual(jev.jevSendAttempt(first, preview({ projection_handle: `obj://${RUN}/jev_loop_projection/${hex("7")}` }),
    make).sendId, first.sendId);
  assert.notEqual(jev.jevSendAttempt(first, preview({ body_sha256: hex("e") }), make).sendId, first.sendId);
  assert.equal(n, 3);
});

// ---- the JEV proposal card ----

test("proposal card: label, local notation, list position n/m, model-reported confidence, probabilities in sent order", () => {
  const record = computeRecord();
  assert.equal(lib.jevLoopDetailMatches(detail(), SID_2, LOOP), true);
  assert.equal(lib.jevLoopDetailMatches(detail(), SID, LOOP), false);
  assert.equal(lib.jevLoopDetailMatches(detail({ loop: null }), SID_2, LOOP), false);
  assert.equal(lib.jevLoopDetailMatches(detail(), SID_2, LOOP_P), false);
  const view = lib.loopChoiceView(detail(), record);
  assert.equal(view.state, "completed");
  const card = view.card;
  assert.equal(card.label, "JEV 판정(모델 선택)");
  assert.equal(card.isSelection, true);
  assert.equal(card.role, "selection");
  assert.equal(card.roleText, "바퀴 4의 선택(계산은 사람이 승인해야 시작)");
  assert.equal(card.chosenAlias, "c03");
  assert.equal(card.ref, id16(3));
  assert.equal(card.refText, `후보 ${id16(3)}`);
  assert.equal(card.localDisplayText, SMILES(3));
  assert.equal(card.listPositionText, "2/3");
  assert.equal(card.confidenceLabel, "모델 보고 확신도(0–1, 과학 값 아님)");
  assert.equal(card.confidence, 0.87654);                       // stored value unchanged
  assert.equal(card.confidenceText, "0.877");                   // display only
  assert.equal(card.reasonText, jev.CHOICE_REASON_TEXT);
  assert.equal(card.lateText, null);
  assert.equal(card.lateNote, null);
  assert.deepEqual(plain(card.limitations), [LJ.LJ1, LJ.LJ2, LJ.LJ3, LJ.LJ4, LJ.LJ6]);
  // probabilities: the not-yet-computed aliases in the sent order (c01, c03), never sorted by value
  assert.deepEqual(plain(card.probabilityRows), [
    { alias: "c01", refText: `후보 ${id16(7)}`, displayText: SMILES(7), value: 0.2, text: "0.200" },
    { alias: "c03", refText: `후보 ${id16(3)}`, displayText: SMILES(3), value: 0.7, text: "0.700" }]);
  const reordered = lib.loopChoiceView(detail({}, { answer: { ...choice().answer, probabilities: { c01: 0.2, c03: 0.7 } } }),
    record).card;
  assert.deepEqual(plain(reordered.probabilityRows), plain(card.probabilityRows));
  const partial = lib.loopChoiceView(detail({}, { answer: { ...choice().answer, probabilities: { c03: 0.9 } } }),
    record).card;
  assert.deepEqual(plain(partial.probabilityRows.map(row => [row.alias, row.text])), [["c01", "보고 없음"], ["c03", "0.900"]]);
  for (const row of card.probabilityRows)
    assert.deepEqual(Object.keys(row).sort(), ["alias", "displayText", "refText", "text", "value"]);
  // nothing reported
  const none = lib.loopChoiceView(detail({}, { answer: { ...choice().answer, confidence: null, probabilities: null } }),
    record).card;
  assert.equal(none.confidenceText, "보고 없음");
  assert.equal(none.probabilitiesReported, false);
  assert.equal(none.probabilityText, "보고 없음");
  assert.deepEqual(plain(none.probabilityRows), []);
  const mutation = lib.loopChoiceView(detail({ loop: { loop_id: LOOP_P, iteration: 1, send_ordinal: 0 }, kind: "mutation" },
    { loop: { loop_id: LOOP_P, iteration: 1, send_ordinal: 0 }, selection: [{ alias: "m01", ref: 3, state: "pending" },
      { alias: "m02", ref: 30, state: "pending" }], answer: { choice_alias: "m02", list_position: 2, list_size: 2,
      local_ref: { candidate_index: 30, position_index: 4 }, local_display: { residue: RESIDUE, from: "K", to: "W" },
      confidence: 1, probabilities: { m02: 1, m01: 0 } } }),
    // T11 fix: the record must show the send completed before the card is judged (here: completed, no proposal kept)
    proteinRecord({ iterations: [{ ...proteinRecord().iterations[0], sends: [send({ send_id: SID_2, send_ordinal: 0,
      proposal_handle: null })] }] }));
  assert.equal(mutation.card.ref, 30);
  assert.equal(mutation.card.refText, "후보 번호 30");
  assert.equal(mutation.card.isSelection, false);       // the record lists no such selection for iteration 1
  assert.equal(mutation.card.role, "not_selection");
  assert.equal(mutation.card.roleText, "바퀴 1의 선택이 아님");
  assert.deepEqual(plain(mutation.card.probabilityRows.map(row => [row.alias, row.text])), [["m01", "0.000"],
    ["m02", "1.000"]]);
});

test("a late proposal shows J7 and is not the iteration's selection; refusals and failures show their reason only", () => {
  const record = computeRecord();
  const late = lib.loopChoiceView(detail({ late: true, late_reason: "consent_off" }, { arrival: { late: true,
    late_reason: "consent_off" }, limitations: [...choice().limitations, jev.JEV_STATEMENTS.J7] }), record).card;
  assert.equal(late.isSelection, false);
  assert.equal(late.lateText, "동의 끈 뒤 도착");
  assert.equal(late.lateNote, `${lib.LATE_CHOICE_NOTE}\n${jev.JEV_STATEMENTS.J7}`);
  assert.equal(late.limitations.at(-1), jev.JEV_STATEMENTS.J7);
  for (const code of jev.REJECTED_REASONS) {
    const view = lib.loopChoiceView({ ...detail({ status: "rejected", reason_code: code, choice_handle: null }), choice: null },
      record);
    assert.deepEqual(plain(view), { state: "rejected", statusText: jev.sendStatusText("rejected"),
      reasonText: jev.rejectedReasonText(code) });
  }
  for (const code of jev.FAILED_REASONS) {
    const view = lib.loopChoiceView({ ...detail({ status: "failed", reason_code: code, choice_handle: null }), choice: null },
      record);
    assert.equal(view.reasonText, jev.failedReasonText(code));
  }
  assert.deepEqual(plain(lib.loopChoiceView(detail({ status: "in_progress", choice_handle: null }), record)),
    { state: "in_progress", statusText: jev.sendStatusText("in_progress") });
  // a proposal that does not belong to this loop or send, or claims to be a result, is not shown
  for (const [over, choiceOver] of [[{}, { send: { send_id: SID, audit_id: AUDIT } }],
    [{}, { loop: { loop_id: LOOP_P, iteration: 4, send_ordinal: 1 } }], [{}, { scientific_result: true }],
    [{}, { schema: "jev_choice@1" }], [{}, { label: "추천" }], [{ loop: null }, {}], [{ choice_handle: null }, {}],
    [{ loop: { loop_id: LOOP, iteration: 3, send_ordinal: 1 } }, {}]])
    assert.equal(lib.loopChoiceView(detail(over, choiceOver), record).state, "invalid", JSON.stringify([over, choiceOver]));
});

test("card judged only from a record that shows the send completed: stale record → confirming, no number or judgment", () => {
  // The send answer arrived but the record read is older: iteration 4 lists the send still in progress, or not at all.
  const fresh = computeRecord();
  const inProgress = { ...fresh, iterations: fresh.iterations.map(it => it.index !== 4 ? it : { ...it,
    sends: it.sends.map(item => item.send_id === SID_2 ? { ...item, status: "in_progress", proposal_handle: null } : item) }) };
  const unlisted = ligandRecord();   // no iteration 4 row yet
  for (const stale of [inProgress, unlisted]) {
    const view = lib.loopChoiceView(detail(), stale);
    assert.equal(view.state, "confirming");
    assert.equal(view.message, lib.CHOICE_CONFIRMING_TEXT);
    assert.equal("card" in view, false);
    assert.ok(!/\d/.test(view.message) && !/선택이 아님|의 선택\(/.test(view.message));
    assert.deepEqual(plain(lib.jevLoopForbiddenWords(view.message)), []);
    assert.equal(lib.loopRecordReflectsSend(stale, SID_2, "completed"), false);
  }
  // A fresh record that shows it as the iteration's selection: the selection mark.
  const selected = lib.loopChoiceView(detail(), fresh);
  assert.equal(selected.state, "completed");
  assert.equal(selected.card.role, "selection");
  assert.equal(selected.card.roleText, "바퀴 4의 선택(계산은 사람이 승인해야 시작)");
  assert.equal(lib.loopRecordReflectsSend(fresh, SID_2, "completed"), true);
  assert.equal(lib.loopRecordReflectsSend(fresh, SID_2, "failed"), false);
  assert.equal(lib.loopRecordReflectsSend(fresh, SID), true);      // the failed send of iteration 4, any status
  // A fresh record whose send is a late proposal: not the selection, with J7.
  const lateRecord = { ...fresh, iterations: fresh.iterations.map(it => it.index !== 4 ? it : { ...it, phase:
    "awaiting_selection", sends: it.sends.map(item => item.send_id === SID_2 ? { ...item, late: true } : item) }),
  current: current() };
  const late = lib.loopChoiceView(detail({ late: true, late_reason: "consent_off" }, { arrival: { late: true,
    late_reason: "consent_off" }, limitations: [...choice().limitations, jev.JEV_STATEMENTS.J7] }), lateRecord);
  assert.equal(late.state, "completed");
  assert.equal(late.card.role, "not_selection");
  assert.equal(late.card.roleText, "바퀴 4의 선택이 아님");
  assert.equal(late.card.lateNote, `${lib.LATE_CHOICE_NOTE}\n${jev.JEV_STATEMENTS.J7}`);
  assert.equal(late.card.limitations.at(-1), jev.JEV_STATEMENTS.J7);
  // The record names another proposal as the selection: this one is not it.
  const other = { ...fresh, iterations: fresh.iterations.map(it => it.index !== 4 ? it : { ...it,
    sends: it.sends.map(item => item.send_id === SID_2 ? { ...item, proposal_handle: CHOICE_1 } : item) }) };
  assert.equal(lib.loopChoiceView(detail(), other).card.role, "not_selection");
  assert.equal(lib.loopRecordSend(fresh, "absent"), null);
  assert.deepEqual(plain(lib.loopRecordSend(fresh, SID_2)), { ...send({ send_id: SID_2, send_ordinal: 1,
    proposal_handle: CHOICE_4 }), iteration: 4 });
});

test("record reads: a request while a read is in flight is kept (merged), read once more when it ends, never dropped", () => {
  let queue = lib.initialLoopReadQueue();
  assert.deepEqual(plain(queue), { inFlight: null, pending: false });
  let step = lib.loopReadRequest(queue, LOOP);
  assert.equal(step.start, true);
  queue = step.queue;
  // Requests while the read is in flight (the send's finally, poll ticks) are merged into one pending mark.
  for (let i = 0; i < 3; i++) {
    step = lib.loopReadRequest(queue, LOOP);
    assert.equal(step.start, false);
    queue = step.queue;
    assert.deepEqual(plain(queue), { inFlight: LOOP, pending: true });
  }
  // The read ends (applied or dropped): exactly one more read, which starts at once.
  let settled = lib.loopReadSettled(queue, LOOP);
  assert.equal(settled.again, LOOP);
  queue = settled.queue;
  assert.deepEqual(plain(queue), { inFlight: null, pending: false });
  step = lib.loopReadRequest(queue, settled.again);
  assert.equal(step.start, true);
  queue = step.queue;
  // That read ends with no request meanwhile: nothing more.
  settled = lib.loopReadSettled(queue, LOOP);
  assert.equal(settled.again, null);
  queue = settled.queue;
  // Another loop opened while a read of the first is in flight: its read starts; the old read's end changes nothing.
  queue = lib.loopReadRequest(queue, LOOP).queue;
  step = lib.loopReadRequest(queue, LOOP_P);
  assert.equal(step.start, true);
  queue = step.queue;
  settled = lib.loopReadSettled(queue, LOOP);
  assert.equal(settled.again, null);
  assert.deepEqual(plain(settled.queue), { inFlight: LOOP_P, pending: false });
  // The request-number rule still decides whether an answer is applied: a later request number drops the older answer.
  const captured = { runId: RUN, loopId: LOOP, iteration: null, seq: 3 };
  assert.equal(lib.loopResponseCurrent(captured, { ...captured }), true);
  assert.equal(lib.loopResponseCurrent(captured, { ...captured, seq: 4 }), false);
  assert.equal(lib.loopResponseCurrent(captured, { ...captured, loopId: LOOP_P }), false);
});

// ---- errors, projection command, API client, history, reports, panel ----

test("error parsing: closed loop names with their details, the loop send refusal, M18 / M21 admission, never English", () => {
  const error = (status, code, detail) => Object.assign(new Error("english message"), { status, code, detail });
  const budget = lib.loopErrorInfo(error(429, "budget_blocked", { error: "budget_blocked", reason_code: "budget_blocked",
    message: "x", blocked_axes: ["expensive_units", "wall_clock_s"], needs: { expensive_units: 2, wall_clock_s: 420 } }));
  assert.equal(budget.text, `${lib.computeReasonText("budget_blocked")} · ${lib.axisText("expensive_units")} 필요 2단위 · ` +
    `${lib.axisText("wall_clock_s")} 필요 420초`);
  const step = lib.loopErrorInfo(error(409, "step_unavailable", { error: "step_unavailable", reason_code: "step_unavailable",
    message: "x", job: { id: "job-9", status: "cancelled" } }));
  assert.equal(step.text, `${lib.computeReasonText("step_unavailable")} · 작업 job-9 (${lib.loopJobStatusText("cancelled")})`);
  for (const reason of [...lib.LOOP_COMPUTE_REASONS, ...lib.LOOP_END_REFUSAL_REASONS]) {
    const info = lib.loopErrorInfo(error(409, reason, { error: reason, reason_code: reason, message: "english message" }));
    assert.equal(info.reasonCode, reason);
    assert.ok(info.text.startsWith(`${lib.computeReasonText(reason) === jev.UNKNOWN_CODE_TEXT
      ? lib.endRefusalText(reason) : lib.computeReasonText(reason)}`), reason);
    assert.ok(!info.text.includes("english"));
  }
  const send = lib.loopErrorInfo(error(409, "loop_send_invalid", { error: "loop_send_invalid", message: "x",
    reason: "ordinal_mismatch" }));
  assert.equal(send.reasonCode, "ordinal_mismatch");
  assert.ok(send.text.endsWith(lib.loopSendReasonText("ordinal_mismatch")) && send.text.includes("(loop_send_invalid)"));
  assert.ok(lib.loopErrorInfo(error(409, "loop_send_invalid", { error: "loop_send_invalid", reason: "bogus" })).text
    .endsWith(jev.UNKNOWN_CODE_TEXT));
  // the compute route passes the M18 / M21 job admission refusal on as it is
  assert.equal(lib.loopErrorInfo(error(422, "input_invalid", { reason_code: "receptor_altloc_present" })).text,
    docking.dockingReasonText("receptor_altloc_present"));
  assert.equal(lib.loopErrorInfo(error(422, "input_invalid", { reason_code: "residue_mismatch" }), "protein").text,
    mutationModel.modelReasonText("residue_mismatch"));
  assert.equal(lib.loopErrorInfo(error(409, "busy", { reason_code: "global_concurrency_busy" })).text,
    docking.dockingReasonText("global_concurrency_busy"));
  assert.equal(lib.loopErrorInfo(error(409, undefined, undefined)).text, jev.REQUEST_FAILED_TEXT);
  assert.equal(lib.loopErrorInfo(Object.assign(new Error("x"), { status: 409, approval: { gate: "budget_checkpoint" } })).text,
    "실행 승인이 필요함 (budget_checkpoint)");
  assert.equal(lib.loopErrorInfo(error(409, "cancelled", undefined)).text, jev.errorCodeText("cancelled"));
  assert.equal(lib.loopErrorInfo(error(503, "busy", { error: "busy", message: "x" })).text,
    "run이 다른 작업 중(아무것도 기록하지 않음) (busy)");
  assert.equal(lib.loopErrorInfo(error(409, "preview_mismatch", { error: "preview_mismatch" })).text,
    jev.errorCodeText("preview_mismatch"));
  assert.equal(lib.loopErrorInfo(error(500, "something_new", { error: "something_new" })).text, jev.UNKNOWN_CODE_TEXT);
  assert.equal(lib.loopErrorInfo(null).text, jev.REQUEST_FAILED_TEXT);
});

test("projection command: a jev_loop_projection handle with its summary, or the refusal reason with its code", () => {
  const summary = { kind: "ligand", loop_id: LOOP, iteration: 4, send_ordinal: 1, selection_count: 6, body_bytes: 1234,
    body_sha256: hex("d") };
  assert.deepEqual(plain(lib.jevLoopProjectionOutcome({ ok: true, handle: { handle: PROJ, kind: "jev_loop_projection",
    schema: "jev_loop_projection@1", summary, preview: [] } })), { ok: true, handle: PROJ, summary });
  assert.deepEqual(plain(lib.jevLoopProjectionOutcome({ ok: true, handle: { handle: PROJ, kind: "jev_projection",
    schema: "jev_projection@1", summary } })), { ok: false, text: lib.NOT_A_LOOP_PROJECTION_TEXT, reasonCode: null });
  for (const reason of lib.LOOP_PROJECTION_REASON_CODES) {
    const out = lib.jevLoopProjectionOutcome({ ok: false, error: "precondition", message: "english",
      detail: { reason_code: reason } });
    assert.deepEqual(plain(out), { ok: false, text: lib.loopProjectionReasonText(reason), reasonCode: reason }, reason);
  }
  assert.equal(lib.jevLoopProjectionOutcome({ ok: false, loop_stop: { reason: "x" } }).ok, false);
});

test("API client: paths, methods and bodies of every loop call; the M24 preview and send take the loop projection", async () => {
  const calls = [];
  let answer = { status: 200, body: {} };
  const fetch = async (url, init = {}) => {
    calls.push({ url, method: init.method ?? "GET", body: init.body === undefined ? undefined : JSON.parse(init.body),
      contentType: init.headers?.["content-type"] });
    return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
  };
  const { api } = load("api", {}, { fetch });
  const create = { loop_id: LOOP, branch: "ligand", pool: { source: LIG_SET, candidates: [id16(1), id16(2)], filter: null },
    goal: "explore", loop_seed: 1, iteration_cap: 5, setup: {} };
  await api.createJevLoop(RUN, create);
  await api.jevLoops(RUN);
  await api.jevLoop(RUN, LOOP);
  await api.jevLoopCompute(RUN, LOOP, { iteration: 4, proposal: CHOICE_4 });
  await api.jevLoopCompute(RUN, LOOP, { iteration: 4, candidate: id16(3) });
  await api.jevLoopAbandonDocking(RUN, LOOP, { iteration: 1 });
  await api.jevLoopEnd(RUN, LOOP);
  await api.buildJevLoopProjection(RUN, { loop_id: LOOP, iteration: 4 });
  await api.jevPreview(RUN, PROJ);
  await api.jevSend(RUN, { send_id: SID, projection: PROJ, body_sha256: hex("d"), confirm: "send_to_jev" });
  await api.jevSendDetail(RUN, SID);
  await api.createJevLoopReport(RUN, SUMMARY_H);
  const json = "application/json";
  assert.deepEqual(plain(calls), [
    { url: `/api/runs/${RUN}/jev_loops`, method: "POST", contentType: json, body: create },
    { url: `/api/runs/${RUN}/jev_loops`, method: "GET" },
    { url: `/api/runs/${RUN}/jev_loops/${LOOP}`, method: "GET" },
    { url: `/api/runs/${RUN}/jev_loops/${LOOP}/compute`, method: "POST", contentType: json,
      body: { iteration: 4, proposal: CHOICE_4 } },
    { url: `/api/runs/${RUN}/jev_loops/${LOOP}/compute`, method: "POST", contentType: json,
      body: { iteration: 4, candidate: id16(3) } },
    { url: `/api/runs/${RUN}/jev_loops/${LOOP}/abandon_docking`, method: "POST", contentType: json, body: { iteration: 1 } },
    { url: `/api/runs/${RUN}/jev_loops/${LOOP}/end`, method: "POST", contentType: json, body: {} },
    { url: `/api/runs/${RUN}/commands`, method: "POST", contentType: json,
      body: { tool: "build_jev_loop_projection", args: { loop_id: LOOP, iteration: 4 }, decided_by: "human",
        execution_mode: "human" } },
    { url: `/api/runs/${RUN}/jev/preview`, method: "POST", contentType: json, body: { projection: PROJ } },
    { url: `/api/runs/${RUN}/jev/sends`, method: "POST", contentType: json,
      body: { send_id: SID, projection: PROJ, body_sha256: hex("d"), confirm: "send_to_jev" } },
    { url: `/api/runs/${RUN}/jev/sends/${SID}`, method: "GET" },
    { url: `/api/runs/${RUN}/method_reports`, method: "POST", contentType: json, body: { result_handle: SUMMARY_H } },
  ]);
  // a loop route refusal: {"detail": {error, reason_code, message, ...}}
  answer = { status: 422, body: { detail: { error: "input_invalid", reason_code: "seed_invalid", message: "english" } } };
  const refused = await api.createJevLoop(RUN, create).catch(error => error);
  assert.equal(refused.status, 422);
  assert.deepEqual(plain(lib.loopCreateRefusal(refused, "ligand")), { field: "loop_seed", reasonCode: "seed_invalid",
    text: lib.createReasonText("seed_invalid") });
  // loop ids with reserved characters stay one path segment
  calls.length = 0;
  answer = { status: 200, body: {} };
  await api.jevLoop(RUN, "a/b?c");
  assert.equal(calls[0].url, `/api/runs/${RUN}/jev_loops/a%2Fb%3Fc`);
});

test("knowledge tab history: a loop send is a read-only row with the loop mark; an M24 send is unchanged", () => {
  assert.equal(lib.loopSendHistoryMark({ kind: "ligand" }), null);
  assert.deepEqual(plain(lib.loopSendHistoryMark({ kind: "ligand", loop: { loop_id: LOOP, iteration: 2, send_ordinal: 1 } })), {
    text: "JEV 루프 · 바퀴 2 · 전송 순번 1", canOpen: false, canReport: false,
    guide: "이 전송은 JEV 루프 기록입니다. 결과와 계산은 리간드 설계·탐색 탭의 JEV 루프 영역에서 봅니다." });
  assert.ok(lib.loopSendHistoryMark({ kind: "mutation", loop: null }).guide.includes("단백질 공학 탭"));
  assert.equal(lib.loopSendHistoryMark({ kind: "mutation", loop: null }).text, "JEV 루프 · —");
});

test("report kind label and report match; panel states; list rows; late responses by run, loop, iteration and seq", () => {
  assert.equal(reportLibrary.reportKindLabel({ kind: "jev_loop", handle: "h", target_handle: SUMMARY_H, created_seq: 9 }),
    lib.LOOP_REPORT_LABEL);
  const artifact = { handle: "r", markdown_handle: "m", markdown: "", manifest: { schema: "method_report_manifest@1",
    analysis_type: "jev_loop", result_handle: SUMMARY_H, snapshot: { event_seq: 3 } } };
  assert.equal(lib.jevLoopReportMatches(artifact, SUMMARY_H), true);
  assert.equal(lib.jevLoopReportMatches(artifact, `obj://${RUN}/jev_loop_result/${hex("e")}`), false);
  assert.equal(lib.jevLoopReportMatches({ manifest: { ...artifact.manifest, analysis_type: "jev_choice" } }, SUMMARY_H), false);
  // five states per branch
  const capability = { ligand: { available: true, reason_code: null, reason: null },
    protein: { available: false, reason_code: "pdbfixer_unavailable", reason: "PDBFixer를 쓸 수 없다." } };
  const rows = [{ branch: "ligand", status: "active" }];
  assert.deepEqual(plain(lib.loopPanelState({ runId: null, branch: "ligand" })), { state: "unavailable",
    reason: lib.NO_RUN_REASON });
  assert.deepEqual(plain(lib.loopPanelState({ runId: RUN, branch: "ligand", capability: null })), { state: "unavailable",
    reason: lib.CAPABILITY_REASON });
  assert.deepEqual(plain(lib.loopPanelState({ runId: RUN, branch: "protein", capability, rows })), { state: "unavailable",
    reason: "PDBFixer를 쓸 수 없다. (pdbfixer_unavailable)" });
  assert.equal(lib.loopPanelState({ runId: RUN, branch: "ligand" }).state, "loading");
  assert.equal(lib.loopPanelState({ runId: RUN, branch: "ligand", capability }).state, "loading");
  assert.deepEqual(plain(lib.loopPanelState({ runId: RUN, branch: "ligand", capability, rows, error: "읽기 실패" })),
    { state: "failed", message: "읽기 실패" });
  assert.equal(lib.loopPanelState({ runId: RUN, branch: "ligand", capability, rows: [] }).state, "empty");
  assert.equal(lib.loopPanelState({ runId: RUN, branch: "ligand", capability, rows }).state, "ready");
  // list rows of one branch, server order (newest first), nothing opened automatically
  const list = [{ loop_id: LOOP_P, branch: "protein", status: "active", end_reason: null, goal: "explore", pool_size: 3,
    counts: counts({ started: 1 }), created_seq: 30 }, { loop_id: LOOP, branch: "ligand", status: "ended",
    end_reason: "iteration_cap", goal: "exploit", pool_size: 7, counts: counts(), created_seq: 10 }];
  assert.deepEqual(plain(lib.loopListRows(list, "ligand")), [{ loopId: LOOP, active: false, createdSeq: 10,
    text: `활용형 · 풀 7개 · 시작한 바퀴 3 · 끝남: ${lib.endReasonText("iteration_cap")}` }]);
  assert.equal(lib.loopListRows(list, "protein")[0].text, "탐색형 · 풀 3개 · 시작한 바퀴 1 · 진행 중");
  assert.equal(lib.loopSwitchBlockedReason(true), lib.LOOP_SWITCH_BUSY_REASON);
  assert.equal(lib.loopSwitchBlockedReason(false), null);
  // late answers
  const stamp = { runId: RUN, loopId: LOOP, iteration: 4, seq: 3 };
  assert.equal(lib.loopResponseCurrent(stamp, { ...stamp }), true);
  for (const change of [{ runId: "other" }, { loopId: LOOP_P }, { iteration: 5 }, { seq: 4 }])
    assert.equal(lib.loopResponseCurrent(stamp, { ...stamp, ...change }), false, JSON.stringify(change));
  assert.equal(lib.loopResponseCurrent({ ...stamp, runId: null }, { ...stamp, runId: null }), false);
  assert.equal(lib.loopRecordMatches(ligandRecord(), LOOP), true);
  assert.equal(lib.loopRecordMatches(ligandRecord(), LOOP_P), false);
  assert.equal(lib.loopRecordMatches({ schema: "jev_loop@1" }), false);
});

// ---- wording ----

/** Every string inside a value, skipping the named keys (verbatim server / wire text). */
function strings(value, skip = new Set()) {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(item => strings(item, skip));
  if (value && typeof value === "object")
    return Object.entries(value).flatMap(([key, item]) => skip.has(key) ? [] : strings(item, skip));
  return [];
}

test("no screen string ranks, recommends, predicts, compares or improves (UL1–UL3, U3, J7 and the server's LJ exempt)", () => {
  // the checker itself: each forbidden term is caught, the score names and the fixed lines are not
  for (const word of ["순위", "추천", "최고", "최저", "최적", "최솟값", "최댓값", "개선", "예측", "유망", "좋은", "나쁜", "좋아짐",
    "나아짐", "승자", "우승", "우수", "상위", "하위", "향상", "악화", "평균", "차이", "증감", "변화량", "대비", "비교", "효과", "친화도",
    "안정성", "ΔΔG", "활성", "에너지", "안전", "가장 높음", "가장 낮은", "best", "rank", "recommend", "winner", "improved",
    "predicted", "promising", "highest", "lowest", "better", "worse", "superior", "optimal", "affinity", "stability",
    "average", "Best", "RANK"])
    assert.equal(lib.jevLoopForbiddenWords(`후보 c02는 ${word}`).length, 1, word);
  for (const allowed of ["비활성 버튼", "최소화", "최적화", "qvina 점수 -7.3", lib.SCORE_LABEL, lib.SCORE_COLUMN_LABEL,
    "가장 다른 후보", "최소 2개"])
    assert.deepEqual(plain(lib.jevLoopForbiddenWords(allowed)), [], allowed);
  for (const line of lib.LOOP_FIXED_LINES) assert.deepEqual(plain(lib.jevLoopForbiddenWords(line)), [], line);
  // the server's stored LJ sentences are exempt only as given (whole lines); they name what the loop is not
  const sentences = Object.values(LJ);
  for (const sentence of sentences) assert.deepEqual(plain(lib.jevLoopForbiddenWords(sentence, sentences)), [], sentence);
  for (const name of ["LJ1", "LJ2", "LJ4", "LJ6", "LJ7"]) assert.ok(lib.jevLoopForbiddenWords(LJ[name]).length > 0, name);
  assert.ok(lib.jevLoopForbiddenWords(`요약: ${LJ.LJ1}`, sentences).length > 0);
  assert.ok(lib.jevLoopForbiddenWords(`${lib.LOOP_SCREEN_NOTES.UL1} 이 후보가 최고다.`).length > 0);

  // every exported string constant (tables included)
  const outputs = [];
  for (const [name, value] of Object.entries(lib)) {
    if (typeof value === "function" || value instanceof RegExp) continue;
    outputs.push(...strings(value).map(text => [name, text]));
  }
  // every label of every closed code, and the default
  const codes = [...lib.LOOP_CANDIDATE_STATES, ...lib.LOOP_PHASES, ...lib.LOOP_ACTIONS, ...lib.LOOP_STEPS,
    ...lib.LOOP_STEP_STATES, ...lib.LOOP_ITERATION_STATES, ...lib.LOOP_EXHAUSTED_REASONS, ...lib.LOOP_END_REASONS,
    ...lib.LOOP_AXES, ...lib.LOOP_GOALS, ...lib.LOOP_CREATE_REASONS, lib.LOOP_ID_CONFLICT, ...lib.LOOP_COMPUTE_REASONS,
    lib.LOOP_STEP_UNAVAILABLE, ...lib.LOOP_END_REFUSAL_REASONS, ...lib.LOOP_PROJECTION_REASON_CODES,
    ...lib.LOOP_SEND_REASONS, "unknown"];
  for (const fn of ["candidateStateText", "phaseText", "actionText", "stepText", "stepStateText", "iterationStateText",
    "exhaustedReasonText", "endReasonText", "axisText", "goalText", "createReasonText", "computeReasonText",
    "endRefusalText", "loopProjectionReasonText", "loopSendReasonText", "loopJobStatusText"])
    for (const code of codes) outputs.push([fn, lib[fn](code)]);
  // view models over the fixtures; the body and the question instructions are the exact wire text (shown verbatim),
  // and stored limitations are the server's LJ sentences
  const skip = new Set(["body", "instructions", "limitations", "projectionHandle", "bodySha256", "sendId",
    "proposalHandle", "resultHandle", "displayText", "localDisplayText", "candidateText"]);
  const record = computeRecord();
  const job = { job_id: "job-7", step: "model", status: "claimed", start_blocked: "approval_required" };
  const error = (status, code, detail) => ({ status, code, detail });
  const views = [
    ...[ligandRecord(), computeRecord(), proteinRecord(), ligandRecord({ status: "ended", end_reason: "budget_exhausted",
      exhausted_reason: "iteration_cap", current: current({ action: "none", can_end: false }) }),
    proteinRecord({ current: { ...proteinRecord().current, action: "wait_job", job } })]
      .flatMap(item => [lib.loopActionView(item, { busy: true, proposalRef: id16(4) }),
        lib.loopActionView(item, { busy: false }), lib.loopCandidateRows(item), lib.loopIterationRows(item),
        lib.loopStatusView(item)]),
    lib.loopActionView(ligandRecord({ current: current({ blocked_axes: ["expensive_units"], send_blocked_axes: ["sends"],
      needs: amounts({ sends: 0 }) }) }), { busy: false }),
    lib.jevLoopPreviewView(preview({ blocked_by: [...jev.PREVIEW_BLOCK_REASONS], loop_blocks: [...lib.LOOP_SEND_REASONS] }),
      record),
    lib.jevLoopSendBlockers({ preview: preview({ blocked_by: [...jev.PREVIEW_BLOCK_REASONS],
      loop_blocks: [...lib.LOOP_SEND_REASONS] }), confirmed: false, sending: true }),
    lib.jevLoopSendBlockers({ preview: null, confirmed: false, sending: false }),
    lib.loopChoiceView(detail(), record),
    lib.loopChoiceView(detail({ late: true, late_reason: "run_cancelled" }, { arrival: { late: true,
      late_reason: "run_cancelled" }, answer: { ...choice().answer, confidence: null, probabilities: null } }), record),
    lib.loopChoiceView(detail({}, { scientific_result: true }), record),
    ...jev.REJECTED_REASONS.map(code => lib.loopChoiceView({ ...detail({ status: "rejected", reason_code: code }),
      choice: null }, record)),
    ...jev.FAILED_REASONS.map(code => lib.loopChoiceView({ ...detail({ status: "failed", reason_code: code }), choice: null },
      record)),
    lib.loopPoolArgs("ligand", null, null), lib.loopPoolArgs("protein", jev.emptyJevSelection("ligand", LIG_SET),
      { ranges: {}, pains_exclude: true }, [id16(1)]),
    lib.loopPoolCountText(null), lib.checkLoopSettings(lib.initialLoopSettings()),
    lib.checkLoopSettings({ goal: null, loopSeed: "x", iterationCap: "9" }),
    lib.ligandLoopSetup(lib.initialLigandLoopSetupForm(), null), lib.proteinLoopSetup(lib.initialProteinLoopSetupForm()),
    lib.proteinLoopSetup(proteinForm({ cutoff: "9" })),
    ...[...lib.LOOP_CREATE_REASONS, lib.LOOP_ID_CONFLICT].map(reason => lib.loopCreateRefusal(error(422, "input_invalid",
      { reason_code: reason, setup_reason: "box_invalid", candidates: [id16(1)], capability: { reason_code: "worker_missing",
        reason: "도킹 작업 환경이 없다." } }), "ligand")),
    ...[...lib.LOOP_COMPUTE_REASONS, lib.LOOP_STEP_UNAVAILABLE, ...lib.LOOP_END_REFUSAL_REASONS].map(reason =>
      lib.loopErrorInfo(error(409, reason, { reason_code: reason, blocked_axes: ["expensive_units"],
        needs: { expensive_units: 1 }, job: { id: "job-1", status: "queued" } }))),
    lib.loopErrorInfo(error(409, "loop_send_invalid", { reason: "state_changed" })),
    lib.loopErrorInfo(error(503, "busy", {})), lib.loopErrorInfo(error(500, "internal_error", {})),
    lib.loopErrorInfo(error(415, "unsupported_media_type", {})),
    lib.loopErrorInfo({ status: 409, approval: { gate: "budget_checkpoint" } }),
    ...lib.LOOP_PROJECTION_REASON_CODES.map(reason => lib.jevLoopProjectionOutcome({ ok: false, error: "precondition",
      message: "x", detail: { reason_code: reason } })),
    lib.jevLoopProjectionOutcome({ ok: true, handle: { handle: PROJ, kind: "x", schema: "x", summary: {} } }),
    lib.loopSendHistoryMark({ kind: "ligand", loop: { loop_id: LOOP, iteration: 1, send_ordinal: 0 } }),
    lib.loopSendHistoryMark({ kind: "mutation", loop: null }),
    lib.loopPanelState({ runId: null, branch: "ligand" }), lib.loopPanelState({ runId: RUN, branch: "ligand",
      capability: { ligand: { available: true }, protein: { available: true } }, rows: [] }),
    lib.loopListRows([{ loop_id: LOOP, branch: "ligand", status: "ended", end_reason: "run_cancelled", goal: "explore",
      pool_size: 2, counts: counts(), created_seq: 1 }], "ligand"),
    lib.loopCreateBlockedReason([{ branch: "ligand", status: "active" }], "ligand"),
    lib.loopSwitchBlockedReason(true),
  ];
  for (const view of views) outputs.push(...strings(view, skip).map(text => ["view", text]));
  assert.ok(outputs.length > 400, String(outputs.length));
  for (const [name, text] of outputs) assert.deepEqual(plain(lib.jevLoopForbiddenWords(text)), [], `${name}: ${text}`);
  // the verbatim wire text is kept even though it names what the choice is not
  assert.ok(lib.jevLoopPreviewView(preview(), record).instructions.includes("not a prediction of binding"));
  // no "가장 높음" / bars / colours: probability rows carry only alias, local reference, notation, value and text
  assert.ok(!JSON.stringify(plain(lib.loopChoiceView(detail(), record))).includes("가장"));
});
