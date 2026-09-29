const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const source = fs.readFileSync(path.join(__dirname, "../src/lib/analysis.ts"), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const moduleObject = { exports: {} };
vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, require });
const a = moduleObject.exports;
const same = (actual, expected, message) => assert.deepEqual(JSON.parse(JSON.stringify(actual)), expected, message);

// Synthetic, clearly labelled identifier shapes only. No engine observation is used anywhere.
const RAW = "obj://run-synthetic/structure/aaaa";
const PREPARED = "obj://run-synthetic/prepared_structure/bbbb";
const MINIMIZED = "obj://run-synthetic/openmm_minimized_structure/cccc";
const CHEMICAL = "obj://run-synthetic/chemical_structure/dddd";
const LIGAND = { model_number: 1, chain_auth: "B", chain_label: null, seq_auth: 201, seq_label: null, icode: "", resname: "LIG" };
const atom = (site, handle = PREPARED, name = "CA") => ({ structure_handle: handle, site_index: site, atom_name: name,
  altloc: "", element: "C", residue: { model_number: 1, chain_auth: "A", seq_auth: site + 1, icode: "",
    chain_label: null, seq_label: null, resname: "GLY" } });
const SOURCES = [{ handle: RAW, kind: "structure" }, { handle: PREPARED, kind: "prepared_structure" },
  { handle: MINIMIZED, kind: "openmm_minimized_structure" }];
const screen = (overrides = {}) => ({ displayedSource: { handle: PREPARED, kind: "prepared_structure" },
  ligand: null, ligandSourceHandle: null,
  preparation: { altloc: "highest_occupancy", waters: "strip_all", hydrogens: "strip" },
  cutoff_A: 4, types: ["contact", "polar_contact", "hydrophobic_contact"], pocketChains: null,
  atoms: null, comparison: null, chemicalRequest: null, openmmAcknowledged: null, ...overrides });

test("goal placement: main starts five goals, chemical_interactions goes to the chemical screen", () => {
  for (const goal of ["inspect_ligand", "measure_atoms", "compare_structures", "find_cavities", "minimize_protein"])
    assert.equal(a.goalPlacement("main", goal).allowed, true, goal);
  const chem = a.goalPlacement("main", "chemical_interactions");
  assert.equal(chem.allowed, false);
  assert.equal(chem.enterChemical, true);
  assert.equal(chem.reason, "화학 작업 화면에서 시작합니다");
  assert.equal(a.goalPlacement("chemical", "chemical_interactions").allowed, true);
  assert.equal(a.goalPlacement("chemical", "find_cavities").allowed, true);
  for (const goal of ["inspect_ligand", "measure_atoms", "compare_structures", "minimize_protein"]) {
    const decision = a.goalPlacement("chemical", goal);
    assert.equal(decision.allowed, false, goal);
    assert.equal(decision.enterChemical, false, goal);
    assert.ok(decision.reason);
  }
});

test("source kinds per panel and goal (find_cavities: main prepared/minimized, chemical chemical_structure)", () => {
  same(a.allowedSourceKinds("main", "find_cavities"), ["prepared_structure", "openmm_minimized_structure"]);
  same(a.allowedSourceKinds("chemical", "find_cavities"), ["chemical_structure"]);
  same(a.allowedSourceKinds("main", "inspect_ligand"), ["structure", "prepared_structure"]);
  same(a.allowedSourceKinds("main", "minimize_protein"), ["prepared_structure"]);
  same(a.allowedSourceKinds("main", "chemical_interactions"), []);
});

test("import: the displayed source is imported only when the goal accepts its kind", () => {
  assert.equal(a.importDraft("inspect_ligand", "main", screen()).source, PREPARED);
  const raw = a.importDraft("find_cavities", "main", screen({ displayedSource: { handle: RAW, kind: "structure" } }));
  assert.equal(raw.source, "");
  assert.equal(raw.sourceKind, null);
  const chem = a.importDraft("find_cavities", "chemical", screen({ displayedSource: { handle: CHEMICAL, kind: "chemical_structure" } }));
  assert.equal(chem.source, CHEMICAL);
});

test("import: the ligand is never auto-picked and only kept for its own source", () => {
  assert.equal(a.importDraft("inspect_ligand", "main", screen()).ligand, null);
  same(a.importDraft("inspect_ligand", "main", screen({ ligand: LIGAND, ligandSourceHandle: PREPARED })).ligand, LIGAND);
  assert.equal(a.importDraft("inspect_ligand", "main", screen({ ligand: LIGAND, ligandSourceHandle: RAW })).ligand, null);
});

test("inputs: inspect_ligand on a prepared source omits preparation and keeps the full 7-field ligand", () => {
  const draft = a.importDraft("inspect_ligand", "main", screen({ ligand: LIGAND, ligandSourceHandle: PREPARED }));
  const mapped = a.draftInputs(draft);
  same(mapped.blockers, []);
  same(mapped.inputs, { source: PREPARED, ligand: LIGAND, cutoff_A: 4,
    types: ["contact", "hydrophobic_contact", "polar_contact"] });
  assert.equal(Object.prototype.hasOwnProperty.call(mapped.inputs, "preparation"), false);
});

test("inputs: inspect_ligand on a raw source sends the explicit preparation policy", () => {
  const draft = a.importDraft("inspect_ligand", "main", screen({ displayedSource: { handle: RAW, kind: "structure" },
    ligand: LIGAND, ligandSourceHandle: RAW, preparation: { altloc: "first", waters: "keep_all", hydrogens: "keep" } }));
  same(a.draftInputs(draft).inputs.preparation, { altloc: "first", waters: "keep_all", hydrogens: "keep" });
});

test("inputs: missing ligand is sent as null (server prerequisite) and shown as a local missing item", () => {
  const mapped = a.draftInputs(a.importDraft("inspect_ligand", "main", screen()));
  assert.equal(mapped.inputs.ligand, null);
  assert.ok(mapped.missing.some(item => item.includes("리간드")));
});

test("inputs: invalid cutoff, empty contact types or missing source block plan creation", () => {
  const base = a.importDraft("inspect_ligand", "main", screen());
  assert.ok(a.draftInputs({ ...base, cutoff_A: 7 }).blockers.length > 0);
  assert.ok(a.draftInputs({ ...base, cutoff_A: Number.NaN }).blockers.length > 0);
  assert.ok(a.draftInputs({ ...base, types: [] }).blockers.length > 0);
  assert.ok(a.draftInputs({ ...base, source: "", sourceKind: null }).blockers.length > 0);
  assert.equal(a.draftInputs({ ...base, cutoff_A: 7 }).inputs, null);
});

test("inputs: measure_atoms imports the two M10 atoms read-only, else prerequisite 기존 화면에서 먼저 만드세요", () => {
  const first = atom(3), second = atom(9);
  const draft = a.importDraft("measure_atoms", "main", screen({ atoms: { source: PREPARED, first, second } }));
  assert.equal(draft.source, PREPARED);
  same(a.draftInputs(draft).inputs, { source: PREPARED, first, second });
  const missing = a.draftInputs(a.importDraft("measure_atoms", "main", screen()));
  same(missing.inputs, { source: PREPARED, first: null, second: null });
  assert.ok(missing.missing.some(item => item.includes("기존 화면에서 먼저 만드세요")));
});

test("inputs: compare_structures imports reference, moving and the explicit CA pairs (3-1000) only", () => {
  const pairs = [0, 1, 2].map(i => ({ reference: atom(i, RAW), moving: atom(i, PREPARED) }));
  const draft = a.importDraft("compare_structures", "main", screen({ comparison: { reference: RAW, moving: PREPARED, pairs } }));
  same(a.draftInputs(draft).inputs, { reference: RAW, moving: PREPARED, pairs });
  const short = a.draftInputs(a.importDraft("compare_structures", "main",
    screen({ comparison: { reference: RAW, moving: PREPARED, pairs: pairs.slice(0, 2) } })));
  assert.equal(short.inputs.pairs, null);
  assert.ok(short.missing.some(item => item.includes("기존 화면에서 먼저 만드세요")));
  const none = a.draftInputs(a.importDraft("compare_structures", "main", screen()));
  assert.ok(none.blockers.length > 0, "no reference/moving: nothing to send");
});

test("inputs: chemical_interactions sends the ready M11 request read-only; categories are the fixed five", () => {
  const request = { schema: "chemical_prepare_request@1", mode: "create_new" };
  const draft = a.importDraft("chemical_interactions", "chemical", screen({ chemicalRequest: request }));
  same(a.draftInputs(draft).inputs, { request });
  same(a.CHEMICAL_CATEGORIES, ["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"]);
  const missing = a.draftInputs(a.importDraft("chemical_interactions", "chemical", screen()));
  same(missing.inputs, { request: null });
  assert.ok(missing.missing.some(item => item.includes("기존 화면에서 먼저 만드세요")));
});

test("inputs: find_cavities sends sorted explicit chains; an empty list stays empty (server prerequisite, never all chains)", () => {
  const draft = a.importDraft("find_cavities", "main", screen({ pocketChains: ["B", "A"] }));
  same(a.draftInputs(draft).inputs, { source: PREPARED, chains: ["A", "B"] });
  const empty = a.draftInputs({ ...draft, chains: [] });
  same(empty.inputs, { source: PREPARED, chains: [] });
  assert.ok(empty.missing.length > 0);
});

test("inputs: minimize_protein needs both OpenMM acknowledgements", () => {
  const draft = a.importDraft("minimize_protein", "main", screen());
  assert.ok(a.draftInputs(draft).blockers.length > 0);
  const acknowledged = a.importDraft("minimize_protein", "main", screen({ openmmAcknowledged: { protein_only: true, rebuild_pH7: true } }));
  same(a.draftInputs(acknowledged).inputs, { source: PREPARED, selection_policy: "protein_only", hydrogen_policy: "rebuild_pH7" });
});

const record = (overrides = {}) => ({ execution_id: "exec_00", run_id: "run-synthetic", status: "ready", dry_run: false,
  retryable_step: null, revision: 3, current_step: "s01",
  plan_approval: { approved: true, event_seq: 9, plan_sha256: "f".repeat(64), revocations: [] },
  scientific_approval: { required: false, run_approved: false, state: "not_required", pending_tool: null, recorded_seqs: [] },
  driver: { in_progress: false, request_ids: [] }, recovery_pending: false, notice: null, blocked_reason: null, stop: null,
  steps: [{ step_id: "s01", operation: "compute_interactions", lane: "run_call", status: "pending", null_result: null,
    job_status: null, outputs: {}, report_handle: null, failure: null }], summary_handle: null, ...overrides });

test("controls: awaiting_approval enables 계획 승인 only (plus 중지)", () => {
  const c = a.executionControls(record({ status: "awaiting_approval", plan_approval: { approved: false, event_seq: null,
    plan_sha256: null, revocations: [] } }), { busy: false });
  assert.equal(c.approve.enabled, true);
  assert.equal(c.advance.enabled, false);
  assert.ok(c.advance.reason);
  assert.equal(c.revoke.enabled, false);
  assert.equal(c.cancel.enabled, true);
  assert.equal(c.retry.visible, false);
});

test("controls: ready enables 다음 단계 실행 and 승인 철회; a pending request disables all but 중지", () => {
  const c = a.executionControls(record(), { busy: false });
  assert.equal(c.advance.enabled, true);
  assert.equal(c.revoke.enabled, true);
  assert.equal(c.approve.enabled, false);
  const busy = a.executionControls(record(), { busy: true, busyAction: "advance" });
  for (const key of ["approve", "revoke", "advance", "retry", "scientific_approval"])
    assert.equal(busy[key].enabled, false, key);
  assert.ok(busy.advance.reason);
  assert.equal(busy.cancel.enabled, true, "a long Advance must stay stoppable");
  assert.equal(a.executionControls(record(), { busy: true, busyAction: "cancel" }).cancel.enabled, false);
});

test("controls: retry only for failed with retryable_step; advance then refused with reason", () => {
  const retryable = a.executionControls(record({ status: "failed", retryable_step: "s01" }), { busy: false });
  assert.equal(retryable.retry.visible, true);
  assert.equal(retryable.retry.enabled, true);
  assert.equal(retryable.advance.enabled, false);
  assert.ok(retryable.advance.reason.includes("재시도"));
  const final = a.executionControls(record({ status: "failed", retryable_step: null }), { busy: false });
  assert.equal(final.retry.visible, false);
  assert.equal(final.cancel.enabled, false, "terminal");
  assert.equal(a.isTerminal(record({ status: "failed", retryable_step: null })), true);
  assert.equal(a.isTerminal(record({ status: "failed", retryable_step: "s01" })), false);
});

test("controls: terminal states disable every mutation", () => {
  for (const status of ["complete", "cancelled", "blocked"]) {
    const c = a.executionControls(record({ status }), { busy: false });
    for (const key of ["approve", "revoke", "advance", "retry", "scientific_approval", "cancel"])
      assert.equal(c[key].enabled, false, `${status}:${key}`);
  }
});

test("controls: dry-run plan_only allows only 중지 and shows the preview-only notice", () => {
  const c = a.executionControls(record({ status: "plan_only", dry_run: true, plan_approval: { approved: false,
    event_seq: null, plan_sha256: null, revocations: [] } }), { busy: false });
  assert.equal(c.cancel.enabled, true);
  for (const key of ["approve", "advance", "retry", "scientific_approval"]) {
    assert.equal(c[key].enabled, false, key);
  }
  assert.equal(c.approve.reason, a.DRY_RUN_NOTICE);
  assert.equal(a.DRY_RUN_NOTICE, "연습용 run의 계획은 미리보기 전용입니다. 실행하려면 일반 run에서 같은 입력으로 계획을 다시 만드세요.");
});

test("controls: scientific approval button only for a pending gate; advance waits for it", () => {
  const pending = a.executionControls(record({ status: "awaiting_scientific_approval",
    scientific_approval: { required: true, run_approved: false, state: "pending", pending_tool: "detect_pockets", recorded_seqs: [] } }), { busy: false });
  assert.equal(pending.scientific_approval.visible, true);
  assert.equal(pending.scientific_approval.enabled, true);
  assert.equal(pending.advance.enabled, false);
  const already = a.executionControls(record({ scientific_approval: { required: true, run_approved: true,
    state: "already_approved_in_run", pending_tool: null, recorded_seqs: [] } }), { busy: false });
  assert.equal(already.scientific_approval.visible, false);
});

test("controls: waiting_job enables advance only once the job ended (reads never record it)", () => {
  const running = record({ status: "waiting_job", steps: [{ step_id: "s01", operation: "fpocket_detect_v1",
    lane: "durable_job", status: "waiting_job", job_status: "running" }] });
  assert.equal(a.executionControls(running, { busy: false }).advance.enabled, false);
  const done = record({ status: "waiting_job", steps: [{ step_id: "s01", operation: "fpocket_detect_v1",
    lane: "durable_job", status: "dispatched", job_status: "done" }] });
  assert.equal(a.executionControls(done, { busy: false }).advance.enabled, true);
  const driving = record({ status: "executing", driver: { in_progress: true, request_ids: ["x"] } });
  const c = a.executionControls(driving, { busy: false });
  assert.equal(c.advance.enabled, false);
  assert.equal(c.cancel.enabled, true, "Stop is never refused as busy");
  const recovery = record({ status: "executing", recovery_pending: true });
  assert.equal(a.executionControls(recovery, { busy: false }).advance.enabled, true);
});

test("two approvals are shown separately and never substitute for each other", () => {
  const view = a.approvalDisplay(record({ scientific_approval: { required: true, run_approved: true,
    state: "already_approved_in_run", pending_tool: null, recorded_seqs: [] } }));
  assert.equal(view.plan.state, "approved");
  assert.equal(view.scientific.text, "이 run에서 이미 계산 승인됨");
  const planOnly = a.approvalDisplay(record({ plan_approval: { approved: false, event_seq: null, plan_sha256: null, revocations: [] },
    scientific_approval: { required: true, run_approved: true, state: "already_approved_in_run", pending_tool: null, recorded_seqs: [] } }));
  assert.equal(planOnly.plan.state, "not_approved", "a run scientific approval never approves a plan");
  const noJobs = a.approvalDisplay(record());
  assert.equal(noJobs.scientific.state, "not_required");
  const waiting = a.approvalDisplay(record({ status: "awaiting_scientific_approval", scientific_approval: { required: true,
    run_approved: false, state: "pending", pending_tool: "openmm_protein_minimize", recorded_seqs: [] } }));
  assert.equal(waiting.scientific.state, "pending");
  assert.equal(waiting.plan.state, "approved", "plan approval does not answer the scientific gate");
});

test("request ids: a new UUID per action, the same UUID when re-sending the same body after a transport failure", () => {
  let n = 0;
  const fresh = () => `id-${++n}`;
  const key = a.requestKey("advance", "exec_00", { expected_revision: 3 });
  const first = a.requestIdFor(null, key, fresh);
  assert.equal(first.requestId, "id-1");
  assert.equal(a.requestIdFor(first, key, fresh).requestId, "id-1", "resend after network failure reuses");
  const other = a.requestKey("advance", "exec_00", { expected_revision: 4 });
  assert.equal(a.requestIdFor(first, other, fresh).requestId, "id-2", "a new body is a new action");
  assert.notEqual(a.requestKey("retry", "exec_00", { expected_revision: 3, step_id: "s01" }), key);
  assert.equal(a.keepRequestAfter("transport"), true);
  for (const kind of ["ok", "stale_revision", "busy", "request_id_conflict", "refusal"]) assert.equal(a.keepRequestAfter(kind), false, kind);
});

test("failure classification: typed refusals versus proxy/network loss", () => {
  assert.equal(a.classifyFailure({ status: 409, code: "stale_revision" }), "stale_revision");
  assert.equal(a.classifyFailure({ status: 409, code: "busy" }), "busy");
  assert.equal(a.classifyFailure({ status: 409, code: "request_id_conflict" }), "request_id_conflict");
  assert.equal(a.classifyFailure({ status: 412, code: "retry_or_stop_required" }), "refusal");
  assert.equal(a.classifyFailure({ status: 503, code: "transient" }), "refusal");
  assert.equal(a.classifyFailure({ status: 500 }), "transport");
  assert.equal(a.classifyFailure({ status: 504 }), "transport");
  assert.equal(a.classifyFailure({}), "transport");
});

test("stop auto re-read and resend happens once and only on stale_revision", () => {
  assert.equal(a.stopResend("stale_revision", 0), true);
  assert.equal(a.stopResend("stale_revision", 1), false);
  assert.equal(a.stopResend("busy", 0), false);
  assert.equal(a.stopResend("refusal", 0), false);
});

test("a lost Advance response is judged by the re-read record, not the transport error", () => {
  const before = record({ revision: 3, status: "ready" });
  assert.equal(a.executionProgressed(before, record({ revision: 5, status: "waiting_job" })), true);
  assert.equal(a.executionProgressed(before, record({ revision: 3, status: "ready" })), false);
  assert.equal(a.executionProgressed(before, record({ revision: 3, status: "ready", driver: { in_progress: true, request_ids: ["r"] } })), true);
  assert.equal(a.executionProgressed(before, record({ execution_id: "exec_11", revision: 9 })), false);
});

test("stale responses are discarded on run, execution or action change and after unmount", () => {
  const captured = { runId: "run-a", executionId: "exec_1", action: 4 };
  assert.equal(a.responseCurrent(captured, { runId: "run-a", executionId: "exec_1", action: 4 }, true), true);
  assert.equal(a.responseCurrent(captured, { runId: "run-b", executionId: "exec_1", action: 4 }, true), false);
  assert.equal(a.responseCurrent(captured, { runId: "run-a", executionId: "exec_2", action: 4 }, true), false);
  assert.equal(a.responseCurrent(captured, { runId: "run-a", executionId: "exec_1", action: 5 }, true), false);
  assert.equal(a.responseCurrent(captured, { runId: "run-a", executionId: "exec_1", action: 4 }, false), false);
  assert.equal(a.hostRequestAccepted({ runId: "run-a" }, { runId: "run-a" }), true);
  assert.equal(a.hostRequestAccepted({ runId: "run-a" }, { runId: "run-b" }), false);
  assert.equal(a.hostRequestAccepted({ runId: "run-a" }, { runId: null }), false);
});

test("five UI states are distinct: empty science is never failure and failure is never empty", () => {
  assert.equal(a.analysisUiState({ available: false }), "unavailable");
  assert.equal(a.analysisUiState({ available: true, templateAvailable: false }), "unavailable");
  assert.equal(a.analysisUiState({ available: true, reading: true }), "loading");
  assert.equal(a.analysisUiState({ available: true, record: record({ status: "waiting_job" }) }), "loading");
  assert.equal(a.analysisUiState({ available: true, record: record({ status: "executing" }) }), "loading");
  assert.equal(a.analysisUiState({ available: true, readError: "x" }), "failure");
  assert.equal(a.analysisUiState({ available: true, record: record({ status: "failed", retryable_step: "s01" }) }), "failure");
  assert.equal(a.analysisUiState({ available: true, record: record({ status: "blocked" }) }), "failure");
  const empty = record({ status: "complete", steps: [{ step_id: "s01", operation: "fpocket_detect_v1", lane: "durable_job",
    status: "completed", null_result: true }] });
  assert.equal(a.analysisUiState({ available: true, record: empty }), "scientific_null");
  assert.equal(a.analysisUiState({ available: true, record: record() }), "ready");
  assert.equal(a.analysisUiState({ available: true }), "ready");
});

test("where to open a result: chemical-structure results only in the chemical screen", () => {
  const mainChem = a.resultOpenDecision("main", "chemical_interactions", null, "prolif_detect_v1");
  assert.equal(mainChem.action, "open_in_chemical_screen");
  assert.equal(mainChem.label, "화학 작업 화면에서 열기");
  const mainPocketChem = a.resultOpenDecision("main", "find_cavities", "chemical_structure", "fpocket_detect_v1");
  assert.equal(mainPocketChem.action, "open_in_chemical_screen");
  const chemHere = a.resultOpenDecision("chemical", "chemical_interactions", null, "prolif_detect_v1");
  same([chemHere.action, chemHere.view], ["open_here", "chemical"]);
  const mainPocket = a.resultOpenDecision("main", "find_cavities", "prepared_structure", "fpocket_detect_v1");
  same([mainPocket.action, mainPocket.view], ["open_here", "pocket"]);
  const chemPocketPrepared = a.resultOpenDecision("chemical", "find_cavities", "prepared_structure", "fpocket_detect_v1");
  assert.equal(chemPocketPrepared.action, "open_in_main_screen");
  same(a.resultOpenDecision("main", "inspect_ligand", "prepared_structure", "compute_interactions").view, "contacts");
  same(a.resultOpenDecision("main", "inspect_ligand", "prepared_structure", "compute_interface_sasa").view, "sasa");
  same(a.resultOpenDecision("main", "measure_atoms", "prepared_structure", "measure_distance").view, "measurement");
  same(a.resultOpenDecision("main", "compare_structures", null, "align_structures").view, "measurement");
  same(a.resultOpenDecision("main", "minimize_protein", "prepared_structure", "openmm_protein_minimize").view, "openmm");
  assert.equal(a.resultOpenDecision("main", "inspect_ligand", "prepared_structure", "method_report").action, "none");
});

test("job steps are marked expensive; plan estimate text is never a measurement", () => {
  assert.equal(a.stepIsExpensive({ lane: "durable_job" }), true);
  assert.equal(a.stepIsExpensive({ lane: "run_call" }), false);
  assert.equal(a.LOCAL_RULES_NOTE, "로컬 규칙으로 만든 계획이며 모델 판단이 아닙니다");
  assert.equal(a.EDIT_NEW_PLAN_NOTE.includes("이전 승인"), true);
});

test("outcome text never invents progress for no-op and busy outcomes", () => {
  assert.ok(a.outcomeText("run_busy").includes("다른"));
  assert.ok(a.outcomeText("no_op_waiting_job").length > 0);
  assert.equal(a.outcomeText("advanced"), "한 단계를 진행했습니다.");
  assert.equal(a.BUSY_TEXT, "다른 요청을 처리 중입니다");
});

test("pocket chain import: only an explicit selection of the displayed source of this run", () => {
  const chosen = { runId: "run-a", source: PREPARED, chains: ["B", "A"] };
  same(a.importedPocketChains(chosen, "run-a", PREPARED), ["A", "B"]);
  assert.equal(a.importedPocketChains(chosen, "run-b", PREPARED), null, "another run");
  assert.equal(a.importedPocketChains(chosen, "run-a", MINIMIZED), null, "not the displayed source");
  assert.equal(a.importedPocketChains({ ...chosen, chains: null }, "run-a", PREPARED), null, "default = nothing explicit");
  assert.equal(a.importedPocketChains({ ...chosen, chains: [] }, "run-a", PREPARED), null, "nothing checked");
  assert.equal(a.importedPocketChains(null, "run-a", PREPARED), null);
  const draft = a.importDraft("find_cavities", "main", screen({ pocketChains: a.importedPocketChains(chosen, "run-a", PREPARED) }));
  same(draft.chains, ["A", "B"]);
});

test("pocket results open here in their own screen (through the pocket panel guards)", () => {
  const decision = a.resultOpenDecision("main", "find_cavities", "openmm_minimized_structure", "fpocket_detect_v1");
  same([decision.action, decision.view, decision.label], ["open_here", "pocket", "결과 열기"]);
});

test("created execution: the response adopts the new execution id so busy is released; stale answers stay discarded", () => {
  const captured = { runId: "run-a", executionId: null, action: 7 };
  const adopted = a.adoptExecution(captured, "exec_new");
  same(adopted, { runId: "run-a", executionId: "exec_new", action: 7 });
  same(captured, { runId: "run-a", executionId: null, action: 7 }, "the captured stamp is not mutated");
  const liveAfter = { runId: "run-a", executionId: "exec_new", action: 7 };
  assert.equal(a.responseCurrent(captured, liveAfter, true), false, "the original stamp alone never matches (the bug)");
  assert.equal(a.responseCurrent(adopted, liveAfter, true), true, "busy is cleared for the current panel");
  assert.equal(a.responseCurrent(adopted, { ...liveAfter, action: 8 }, true), false, "a newer action wins");
  assert.equal(a.responseCurrent(adopted, { ...liveAfter, runId: "run-b" }, true), false, "another run wins");
  assert.equal(a.responseCurrent(adopted, { ...liveAfter, executionId: "exec_other" }, true), false, "another execution wins");
  assert.equal(a.responseCurrent(adopted, liveAfter, false), false, "unmounted");
});

test("plan vs execution focus: a new or reopened plan is shown with 실행 만들기 even while an execution stays open", () => {
  const P = { handle: "plan-P" }, Q = { handle: "plan-Q" };
  same(a.planView({ plan: P, executionId: null, executionPlan: null, focus: "plan" }),
    { shownPlan: P, createExecution: true });
  same(a.planView({ plan: P, executionId: "exec_1", executionPlan: P, focus: "execution" }),
    { shownPlan: P, createExecution: false }, "the execution made from P shows its own plan");
  same(a.planView({ plan: Q, executionId: "exec_1", executionPlan: P, focus: "plan" }),
    { shownPlan: Q, createExecution: true }, "new plan Q while exec_1 is open");
  same(a.planView({ plan: null, executionId: "exec_1", executionPlan: P, focus: "plan" }),
    { shownPlan: P, createExecution: false }, "no plan chosen: the open execution's plan");
  same(a.planView({ plan: Q, executionId: "exec_1", executionPlan: P, focus: "execution" }),
    { shownPlan: P, createExecution: false }, "reopened execution takes the focus back");
  same(a.planView({ plan: null, executionId: null, executionPlan: null, focus: "plan" }),
    { shownPlan: null, createExecution: false });
});

test("objects may have changed after a mutation only when the same execution's record moved", () => {
  const before = record({ revision: 3 });
  assert.equal(a.objectsMayHaveChanged(before, record({ revision: 4, status: "ready" })), true);
  assert.equal(a.objectsMayHaveChanged(before, record({ revision: 3 })), false, "no-op answer");
  assert.equal(a.objectsMayHaveChanged(before, record({ execution_id: "exec_99", revision: 9 })), false, "another execution");
  assert.equal(a.objectsMayHaveChanged(before, null), false);
});

test("host event log refresh keeps the longer (newer) log so a late short read never drops objects", () => {
  const prev = [{ seq: 1 }, { seq: 2 }];
  assert.equal(a.newerEventLog(prev, [{ seq: 1 }, { seq: 2 }, { seq: 3 }]).length, 3);
  assert.equal(a.newerEventLog(prev, [{ seq: 1 }]), prev, "a late, shorter log is discarded");
});

test("polling continues while the panel's own Advance/Retry runs inside the request", () => {
  assert.equal(a.pollNeeded(record({ status: "ready" }), null), false);
  assert.equal(a.pollNeeded(record({ status: "ready" }), "advance"), true);
  assert.equal(a.pollNeeded(record({ status: "failed", retryable_step: "s01" }), "retry"), true);
  assert.equal(a.pollNeeded(record({ status: "ready" }), "approve"), false);
  assert.equal(a.pollNeeded(record({ status: "executing" }), null), true);
  assert.equal(a.pollNeeded(record({ status: "waiting_job" }), null), true);
  assert.equal(a.pollNeeded(record({ driver: { in_progress: true, request_ids: [] } }), null), true);
  assert.equal(a.pollNeeded(null, "advance"), false, "nothing open");
});

test("a polled record is accepted only for the same execution and a revision not older than the shown one", () => {
  const shown = record({ revision: 5 });
  assert.equal(a.acceptPolled(shown, record({ revision: 6 })), true);
  assert.equal(a.acceptPolled(shown, record({ revision: 5 })), true);
  assert.equal(a.acceptPolled(shown, record({ revision: 4 })), false, "late older read");
  assert.equal(a.acceptPolled(shown, record({ execution_id: "exec_99", revision: 9 })), false);
  assert.equal(a.acceptPolled(null, record()), true);
});

test("record notices apply only to the current, not-yet-completed step", () => {
  const steps = [{ step_id: "s01", status: "completed" }, { step_id: "s02", status: "pending" }];
  const r = record({ current_step: "s02", steps });
  assert.equal(a.noticeApplies(r, "s01"), false, "completed step: 시작 보류 is history, not a notice");
  assert.equal(a.noticeApplies(r, "s02"), true);
  assert.equal(a.noticeApplies(record({ current_step: "s02", steps: [{ step_id: "s01", status: "pending" }, steps[1]] }), "s01"),
    false, "not the current step");
  assert.equal(a.noticeApplies(record({ current_step: "s01", steps: [{ step_id: "s01", status: "completed" }] }), "s01"), false);
  assert.equal(a.noticeApplies(r, null), true, "an execution-level notice without a step is kept");
  assert.equal(a.noticeApplies(r, "s99"), false, "unknown step");
});

test("an unreadable execution history row is shown as an error row without a reopen action", () => {
  const ok = { execution_id: "exec_1", plan_handle: "obj://run-synthetic/analysis_plan/eeee", goal: "measure_atoms",
    status: "complete", revision: 7, created_seq: 3, dry_run: false, current_step: null, summary_handle: null, error: null };
  same(a.historyRowView(ok), { kind: "ok", reopen: true, error: null });
  const bad = { execution_id: "exec_2", plan_handle: null, goal: null, status: null, revision: null, created_seq: 9,
    dry_run: null, current_step: null, summary_handle: null,
    error: { code: "execution_record_invalid", message: "기록을 읽을 수 없습니다." } };
  same(a.historyRowView(bad), { kind: "error", reopen: false, error: "기록을 읽을 수 없습니다. (execution_record_invalid)" });
  // A row without an error but missing its status is also not reopened (defensive against partial rows).
  same(a.historyRowView({ ...ok, status: null }), { kind: "error", reopen: false, error: "실행 기록을 읽을 수 없습니다." });
  assert.equal(a.historyCapNote(100, 130), "최근 100개만 표시합니다 (전체 130개).");
  assert.equal(a.historyCapNote(3, 3), null);
});

test("workflow object refresh re-reads events and saved reports behind the same run/epoch guards", () => {
  const page = fs.readFileSync(path.join(__dirname, "../app/page.tsx"), "utf8");
  const start = page.indexOf("function refreshEventsFromAnalysis(");
  assert.ok(start >= 0);
  const body = page.slice(start, page.indexOf("\n  function ", start + 1));
  assert.match(body, /api\.allEvents\(requestRunId\)/);
  assert.match(body, /api\.reports\(requestRunId\)/, "saved report list is re-read through the existing page path");
  assert.match(body, /ticket === epoch\.current && hostRequestAccepted\(\{ runId: requestRunId \}, analysisHostRef\.current\)/);
  assert.match(body, /if \(current\(\) && read === analysisReportsReadRef\.current\) setSavedReports\(reports\)/,
    "only the latest read for the current run/epoch may set the list");
});
