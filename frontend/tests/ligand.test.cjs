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
  vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports,
    require: name => dependencies[name] ?? require(name) });
  return moduleObject.exports;
}
const siteAnnotation = load("site-annotation", { "./comparison": load("comparison"), "./numbering": load("numbering"),
  "./event-model": load("event-model") });
const lib = load("ligand", { "./site-annotation": siteAnnotation });
const plain = value => JSON.parse(JSON.stringify(value));

// ---- closed sets: the backend constants are read from backend/mw/ligand_constants.py itself ----
const constantsSource = fs.readFileSync(path.join(__dirname, "../../backend/mw/ligand_constants.py"), "utf8");
function backendTuple(name) {
  const match = new RegExp(`^${name} = \\(([^)]*)\\)`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map(item => item[1]);
}

// Every code the ligand tab can show. Adding a code to a backend set (or a label here) breaks this test, so the
// Korean names and this list are changed together with backend/mw/ligand_constants.py.
const REASON_CODES = [
  // parent (6.2) and block (3.3) rejection
  "unparseable", "record_count", "multiple_fragments", "element_not_allowed", "too_many_atoms", "empty",
  "duplicate_name",
  // site pre-check (4.1)
  "site_empty", "core_empty", "crossing_bond_count", "crossing_bond_not_single", "site_atom_unknown",
  // rule check (4.3)
  "valid", "reaction_parse_failed", "reactant_count", "product_count", "no_mapped_atom", "too_large", "duplicate_rule",
  // product rejection (4.4)
  "sanitize_failed", "equals_parent", "outside_site",
  // stop reasons and stereo flags (4.4)
  "candidate_limit", "attempt_limit", "none", "parent_stereo_lost", "new_unspecified_center",
  // preview blocking, admission, worker and capability codes (ligand_reads.py, ligand_bundle.py)
  "no_generation_method", "rule_invalid", "inspection_required", "inspection_invalid", "site_atoms_invalid",
  "invalid_preview_request", "invalid_job_arguments", "rule_text_invalid", "parent_import_invalid",
  "block_import_invalid", "svg_limit", "output_limit", "inspection_size_limit", "staged_input_invalid",
  "rdkit_version_mismatch", "worker_internal_error", "worker_missing", "handshake_failed", "pains_catalog_unavailable",
  "evidence_invalid",
];

test("closed sets equal the backend constants", () => {
  assert.deepEqual(plain(lib.PARENT_REJECT_REASONS), backendTuple("PARENT_REJECT_REASONS"));
  assert.deepEqual(plain(lib.BLOCK_REJECT_REASONS), backendTuple("BLOCK_REJECT_REASONS"));
  assert.deepEqual(plain(lib.SITE_REASONS), backendTuple("SITE_REASONS"));
  assert.deepEqual(plain(lib.RULE_REASONS), backendTuple("RULE_REASONS"));
  assert.deepEqual(plain(lib.PRODUCT_REJECT_REASONS), backendTuple("PRODUCT_REJECT_REASONS"));
  assert.deepEqual(plain(lib.STOP_REASONS), backendTuple("STOP_REASONS"));
  assert.deepEqual(plain(lib.STEREO_FLAGS), backendTuple("STEREO_FLAGS"));
  assert.deepEqual(plain(lib.PROPERTY_NAMES), backendTuple("PROPERTY_NAMES"));
  assert.deepEqual(plain(lib.SORT_KEYS), ["generation_order", ...backendTuple("PROPERTY_NAMES")]);
  const backendCodes = ["PARENT_REJECT_REASONS", "BLOCK_REJECT_REASONS", "SITE_REASONS", "RULE_REASONS",
    "PRODUCT_REJECT_REASONS", "STOP_REASONS", "STEREO_FLAGS"].flatMap(backendTuple);
  for (const code of backendCodes) assert.ok(REASON_CODES.includes(code), code);
});

test("every reason code reads as 'Korean (code)'; unknown codes stay raw", () => {
  assert.deepEqual(Object.keys(lib.LIGAND_REASON_LABEL).sort(), [...REASON_CODES].sort());
  for (const code of REASON_CODES) {
    const text = lib.ligandReasonText(code);
    assert.ok(text.endsWith(` (${code})`) && /[가-힣]/.test(text), text);
  }
  assert.equal(lib.ligandReasonText("made_up_code"), "made_up_code");
  assert.equal(lib.ligandReasonText("constructor"), "constructor");
  assert.equal(lib.ligandReasonText("crossing_bond_not_single"),
    "부위와 나머지를 잇는 결합이 단일 결합이 아님 (crossing_bond_not_single)");
});

// ---- panel state ----
const cap = { available: true, reason: null, reason_code: null };

test("five panel states; zero candidates is a scientific null, never a failure", () => {
  assert.equal(lib.ligandPanelState({ runId: null }).state, "unavailable");
  assert.equal(lib.ligandPanelState({ runId: "r", capability: undefined }).state, "loading");
  const unavailable = lib.ligandPanelState({ runId: "r",
    capability: { available: false, reason: "RDKit 작업 환경이 없습니다.", reason_code: "worker_missing" } });
  assert.equal(unavailable.state, "unavailable");
  assert.match(unavailable.reason, /\(worker_missing\)/);
  assert.ok(!/\d/.test(unavailable.reason), "unavailable reason carries no number");
  assert.equal(lib.ligandPanelState({ runId: "r", capability: null }).state, "unavailable");
  assert.equal(lib.ligandPanelState({ runId: "r", capability: cap }).state, "ready");
  assert.equal(lib.ligandPanelState({ runId: "r", capability: cap, loading: true }).state, "loading");
  assert.equal(lib.ligandPanelState({ runId: "r", capability: cap, job: { status: "running", failure: null } }).state,
    "loading");
  const failed = lib.ligandPanelState({ runId: "r", capability: cap,
    job: { status: "failed", failure: { error: "input_invalid", message: "m", reason_code: "multiple_fragments" } } });
  assert.equal(failed.state, "failure");
  assert.match(failed.message, /분리된 조각이 여러 개 \(multiple_fragments\)/);
  assert.equal(lib.ligandPanelState({ runId: "r", capability: cap, error: "읽기 실패" }).state, "failure");
  const empty = lib.ligandPanelState({ runId: "r", capability: cap, candidates: 0 });
  assert.equal(empty.state, "scientific_null");
  assert.ok(empty.message.includes("실패가 아닙니다"));
  assert.equal(lib.ligandPanelState({ runId: "r", capability: cap, candidates: 3 }).state, "ready");
  // a read error wins over a stored result; an empty result is not turned into a failure
  assert.equal(lib.ligandPanelState({ runId: "r", capability: cap, candidates: 0, error: "x" }).state, "failure");
  assert.equal(lib.ligandPanelState({ runId: "r", capability: cap, candidates: 0,
    job: { status: "done", failure: null } }).state, "scientific_null");
  assert.equal(lib.ligandPanelState({ runId: "r", capability: cap,
    job: { status: "cancelled", failure: null } }).state, "failure");
});

// ---- site selection ----
test("site checks are off before an inspection, with the reason", () => {
  assert.match(lib.siteSelectionDisabledReason({ inspectionHandle: null, inspectionLoaded: false }), /점검/);
  assert.match(lib.siteSelectionDisabledReason({ inspectionHandle: "i1", inspectionLoaded: false }), /읽는 중/);
  assert.equal(lib.siteSelectionDisabledReason({ inspectionHandle: "i1", inspectionLoaded: true }), null);
});

test("site selection toggles SDF serials, stays sorted and resets on another inspection", () => {
  let selection = lib.emptySiteSelection("i1");
  selection = lib.toggleSiteAtom(selection, "i1", 7);
  selection = lib.toggleSiteAtom(selection, "i1", 3);
  selection = lib.toggleSiteAtom(selection, "i1", 12);
  assert.deepEqual(plain(selection), { inspectionHandle: "i1", atoms: [3, 7, 12] });
  selection = lib.toggleSiteAtom(selection, "i1", 7);
  assert.deepEqual(plain(selection.atoms), [3, 12]);
  assert.equal(lib.siteAtomChecked(selection, "i1", 3), true);
  assert.equal(lib.siteAtomChecked(selection, "i2", 3), false);
  const other = lib.toggleSiteAtom(selection, "i2", 5);
  assert.deepEqual(plain(other), { inspectionHandle: "i2", atoms: [5] });
});

// ---- numbers ----
test("properties show the stored value's decimal string rounded half up, with units", () => {
  assert.equal(lib.propertyText("mol_weight", 180.159), "180.16 Da");
  assert.equal(lib.propertyText("mol_weight", 2.675), "2.68 Da"); // toFixed would give 2.67
  assert.equal(lib.propertyText("crippen_logp", -0.125), "-0.13");
  assert.equal(lib.propertyText("crippen_logp", 1.3), "1.30");
  assert.equal(lib.propertyText("tpsa", 20.23), "20.23 Å²");
  assert.equal(lib.propertyText("tpsa", 0), "0.00 Å²");
  for (const name of ["hbd", "hba", "rotatable_bonds", "heavy_atoms"]) assert.equal(lib.propertyText(name, 3), "3");
  assert.equal(lib.propertyText("formal_charge", -1), "-1");
  assert.equal(lib.PROPERTY_UNIT.mol_weight, "Da");
  assert.equal(lib.PROPERTY_UNIT.tpsa, "Å²");
  assert.equal(lib.PROPERTY_UNIT.crippen_logp, "무차원");
  for (const name of lib.PROPERTY_NAMES) assert.ok(lib.propertyHeader(name).includes("RDKit 추정값"), name);
  assert.equal(lib.countText(2000), "2000");
});

test("PAINS matches read as structure alert matches, not as a verdict", () => {
  assert.equal(lib.painsText([]), "구조 경고 일치 없음");
  assert.equal(lib.painsText([{ catalog: "PAINS_A", name: "ene_one_A(1)" }, { catalog: "PAINS_C", name: "x(2)" }]),
    "구조 경고 일치 2건: PAINS_A ene_one_A(1), PAINS_C x(2)");
});

// ---- filters ----
test("filter input: empty means none, numbers only, min > max refused, eight property names", () => {
  const input = lib.emptyFilterInput();
  assert.deepEqual(Object.keys(input.ranges), [...lib.PROPERTY_NAMES]);
  assert.equal(input.painsExclude, false);
  assert.deepEqual(plain(lib.checkFilterInput(input)), { ok: true, spec: { ranges: {}, pains_exclude: false } });
  const set = (name, min, max, extra = {}) => ({ ...input, ...extra,
    ranges: { ...input.ranges, [name]: { min, max } } });
  assert.deepEqual(plain(lib.checkFilterInput(set("mol_weight", " 150 ", "", { painsExclude: true }))),
    { ok: true, spec: { ranges: { mol_weight: { min: 150, max: null } }, pains_exclude: true } });
  assert.deepEqual(plain(lib.checkFilterInput(set("crippen_logp", "-1.5", "2.5e0")).spec.ranges),
    { crippen_logp: { min: -1.5, max: 2.5 } });
  assert.deepEqual(plain(lib.checkFilterInput(set("tpsa", "20", "20")).spec.ranges), { tpsa: { min: 20, max: 20 } });
  for (const bad of ["abc", "1,5", "+1", ".5", "01", "1.", "Infinity", "NaN", "1e999", "0x10", "1 2"]) {
    const check = lib.checkFilterInput(set("hbd", bad, ""));
    assert.equal(check.ok, false, bad);
    assert.match(check.errors[0], /숫자/);
  }
  const reversed = lib.checkFilterInput(set("hba", "5", "2"));
  assert.equal(reversed.ok, false);
  assert.match(reversed.errors[0], /최솟값이 최댓값보다 큽니다/);
});

test("candidate rows query carries handle, applied filters, sort and page only", () => {
  const view = { sort: "generation_order", direction: "asc", offset: 0, limit: 50, passesOnly: false };
  assert.equal(lib.candidateRowsQuery("obj://r/ligand_candidate_set/ab", { ranges: {}, pains_exclude: false }, view),
    "handle=obj%3A%2F%2Fr%2Fligand_candidate_set%2Fab&sort=generation_order&direction=asc&offset=0&limit=50");
  const spec = { ranges: { mol_weight: { min: 150, max: null }, tpsa: { min: null, max: 90.5 } }, pains_exclude: true };
  assert.equal(lib.candidateRowsQuery("h", spec, { sort: "tpsa", direction: "desc", offset: 100, limit: 100,
    passesOnly: true }),
  "handle=h&mol_weight_min=150&tpsa_max=90.5&pains_exclude=true&passes_only=true&sort=tpsa&direction=desc" +
    "&offset=100&limit=100");
});

const page = over => ({ total: 10, passing: null, failing: null, matched: 10, hidden_by_filter: 0,
  passes_only: false, ...over });

test("count text shows the full total with the filtered-out count", () => {
  assert.equal(lib.candidateCountText(page({})), "전체 후보 10개 · 적용한 필터 없음");
  assert.equal(lib.candidateCountText(page({ passing: 4, failing: 6 })),
    "전체 후보 10개 · 필터 통과 4개 · 필터 실패 6개 · 모두 표시");
  assert.equal(lib.candidateCountText(page({ passing: 4, failing: 6, matched: 4, hidden_by_filter: 6,
    passes_only: true })),
  "전체 후보 10개 · 필터 통과 4개 · 필터 실패 6개 · 필터 때문에 보이지 않는 후보 6개");
  assert.equal(lib.filterSummaryText({ ranges: {}, pains_exclude: false }), "적용한 필터 없음");
  assert.equal(lib.filterSummaryText({ ranges: { hbd: { min: null, max: 5 } }, pains_exclude: true }),
    "적용한 필터 2개");
  assert.equal(lib.passText(null), "—");
  assert.equal(lib.passText(true), "통과");
  assert.equal(lib.passText(false), "실패");
});

test("limit text states where generation stopped, from the stored limits", () => {
  const limits = { max_candidates: 2000, max_attempts: 20000 };
  assert.equal(lib.limitReachedText({ limit_reached: false, stop_reason: null, limits }), null);
  assert.equal(lib.limitReachedText({ limit_reached: true, stop_reason: "candidate_limit", limits }),
    "상한 도달: 후보 수 상한 도달 (candidate_limit) · 후보 2000개에서 정해진 순서대로 멈췄습니다. 이후 순서의 후보는 만들지 않았습니다.");
  assert.equal(lib.limitReachedText({ limit_reached: true, stop_reason: "attempt_limit", limits }),
    "상한 도달: 생성 시도 상한 도달 (attempt_limit) · 생성 시도 20000회에서 정해진 순서대로 멈췄습니다. 이후 순서의 후보는 만들지 않았습니다.");
  const library = (read, cut) => ({ records_read: read, block_limit_reached: cut });
  assert.equal(lib.blockLimitText([library(10, false)]), null);
  assert.equal(lib.blockLimitText([library(600, false), library(400, true)]),
    "building block 상한 도달: 입력 순서대로 처음 1000개 레코드만 읽었습니다.");
});

// ---- late responses ----
test("a response applies only to the same run, handle and latest request", () => {
  const live = { runId: "r1", handle: "h1", seq: 3 };
  assert.equal(lib.ligandResponseCurrent({ runId: "r1", handle: "h1", seq: 3 }, live), true);
  assert.equal(lib.ligandResponseCurrent({ runId: "r1", handle: "h1", seq: 2 }, live), false);
  assert.equal(lib.ligandResponseCurrent({ runId: "r2", handle: "h1", seq: 3 }, live), false);
  assert.equal(lib.ligandResponseCurrent({ runId: "r1", handle: "h2", seq: 3 }, live), false);
  assert.equal(lib.ligandResponseCurrent({ runId: null, handle: null, seq: 0 }, { runId: null, handle: null, seq: 0 }),
    false);
  assert.equal(lib.ligandResponseCurrent({ runId: "r1", handle: null, seq: 1 }, { runId: "r1", handle: null, seq: 1 }),
    true);
});

// ---- jobs ----
test("one job at a time: start is off while a job is open, a request runs or the method is unavailable", () => {
  const base = { capability: cap, dryRun: false, busy: false, activeJob: null };
  assert.equal(lib.ligandStartBlockedReason(base), null);
  assert.match(lib.ligandStartBlockedReason({ ...base, busy: true }), /요청/);
  for (const status of ["queued", "claimed", "running"])
    assert.match(lib.ligandStartBlockedReason({ ...base, activeJob: { status } }), /끝난 뒤/, status);
  for (const status of ["done", "failed", "cancelled", "interrupted"])
    assert.equal(lib.ligandStartBlockedReason({ ...base, activeJob: { status } }), null, status);
  assert.match(lib.ligandStartBlockedReason({ ...base, capability: { available: false, reason: "없음",
    reason_code: "worker_missing" } }), /worker_missing/);
  assert.match(lib.ligandStartBlockedReason({ ...base, dryRun: true }), /dry-run/);
});

test("job phase and text: approval wait, running, done, failure and cancel", () => {
  const job = (status, extra = {}) => ({ status, cancel_requested: false, failure: null, ...extra });
  assert.equal(lib.ligandJobPhase(null, false), "none");
  assert.equal(lib.ligandJobPhase(job("queued"), false), "saved");
  assert.equal(lib.ligandJobPhase(job("queued"), true), "awaiting_approval");
  assert.equal(lib.ligandJobPhase(job("claimed"), false), "running");
  assert.equal(lib.ligandJobPhase(job("running"), false), "running");
  assert.equal(lib.ligandJobPhase(job("done"), true), "done");
  assert.equal(lib.ligandJobPhase(job("failed"), false), "failed");
  assert.equal(lib.ligandJobPhase(job("interrupted"), false), "failed");
  assert.equal(lib.ligandJobPhase(job("cancelled"), false), "cancelled");
  assert.equal(lib.ligandJobPhase(job("strange"), false), "failed");
  assert.match(lib.ligandJobText("rdkit_inspect_v1", job("queued"), false), /^점검 작업.*시작/);
  assert.match(lib.ligandJobText("rdkit_enumerate_v1", job("queued"), true), /승인/);
  assert.equal(lib.ligandJobText("rdkit_enumerate_v1", job("running", { cancel_requested: true }), false),
    "생성 작업 실행 중 · 취소 요청됨");
  assert.equal(lib.ligandJobText("rdkit_inspect_v1", job("done"), false), "점검 작업 완료");
  assert.equal(lib.ligandJobText("rdkit_enumerate_v1", job("failed", { failure: { error: "input_invalid",
    message: "site rejected", reason_code: "crossing_bond_count" } }), false),
  "생성 작업 실패: 부위와 나머지를 잇는 결합이 정확히 1개가 아님 (crossing_bond_count) · site rejected");
  assert.equal(lib.ligandJobText("rdkit_inspect_v1", job("failed", { failure: { error: "timeout", message: "t" } }),
    false), "점검 작업 실패: timeout · t");
  assert.match(lib.ligandJobText("rdkit_inspect_v1", job("cancelled"), false), /취소됨.*저장하지 않았습니다/);
  assert.match(lib.ligandJobText("rdkit_inspect_v1", job("strange"), false), /strange/);
});

test("submission text tells a stored new job, a reused job and a dry-run plan apart", () => {
  assert.match(lib.ligandSubmitText({ job_id: "j1", status: "queued", protocol_id: "rdkit_inspect_v1" }), /저장/);
  assert.match(lib.ligandSubmitText({ job_id: "j1", status: "done", protocol_id: "rdkit_inspect_v1" }),
    /같은 입력의 기존 작업.*j1.*done/);
  assert.match(lib.ligandSubmitText({ plan_only: true, protocol_id: "rdkit_enumerate_v1", reason_code: "dry_run" }),
    /dry-run/);
});

test("approval is the expensive-call gate of this protocol's tool only", () => {
  const approval = tool => ({ gate: "expensive_first_call", tool, reason: "r" });
  assert.equal(lib.ligandApprovalRequired(409, approval("rdkit_inspect_ligand"), "rdkit_inspect_v1"), true);
  assert.equal(lib.ligandApprovalRequired(409, approval("rdkit_enumerate_ligands"), "rdkit_enumerate_v1"), true);
  assert.equal(lib.ligandApprovalRequired(409, approval("rdkit_enumerate_ligands"), "rdkit_inspect_v1"), false);
  assert.equal(lib.ligandApprovalRequired(412, approval("rdkit_inspect_ligand"), "rdkit_inspect_v1"), false);
  assert.equal(lib.ligandApprovalRequired(409, undefined, "rdkit_inspect_v1"), false);
});

test("a lost start response still counts when the stored job moved past queued", () => {
  const before = { run_id: "r", job_id: "j", protocol_id: "rdkit_inspect_v1", attempt_ordinal: 0 };
  assert.equal(lib.ligandStartProgressed(before, { ...before, status: "running" }), true);
  assert.equal(lib.ligandStartProgressed(before, { ...before, status: "done" }), true);
  assert.equal(lib.ligandStartProgressed(before, { ...before, status: "queued" }), false);
  assert.equal(lib.ligandStartProgressed(before, { ...before, status: "queued", attempt_ordinal: 1 }), true);
  assert.equal(lib.ligandStartProgressed(before, { ...before, job_id: "k", status: "done" }), false);
  assert.equal(lib.ligandStartProgressed(before, { ...before, run_id: "x", status: "done" }), false);
});

// ---- request bodies ----
test("inspection args: parent required, blocks in kind order, one rule per non-blank line", () => {
  assert.equal(lib.inspectArgs({ parent: null, blockSdf: null, blockSmiles: null, rulesText: "" }).ok, false);
  assert.deepEqual(plain(lib.inspectArgs({ parent: "p", blockSdf: null, blockSmiles: null, rulesText: "" })),
    { ok: true, args: { parent_sdf_handle: "p", block_handles: [], rules: [] } });
  const rules = "[c:1][Cl]>>[c:1]\r\n\n  \n[C:1]O.[N]>>[C:1]N ";
  assert.deepEqual(plain(lib.inspectArgs({ parent: "p", blockSdf: "b1", blockSmiles: "b2", rulesText: rules }).args),
    { parent_sdf_handle: "p", block_handles: ["b1", "b2"], rules: ["[c:1][Cl]>>[c:1]", "[C:1]O.[N]>>[C:1]N "] });
  const many = Array.from({ length: 11 }, (_, i) => `[C:1]>>[C:1]${i}`).join("\n");
  const tooMany = lib.inspectArgs({ parent: "p", blockSdf: null, blockSmiles: null, rulesText: many });
  assert.equal(tooMany.ok, false);
  assert.match(tooMany.errors[0], /10개/);
});

test("enumeration body, usable rules and preview matching", () => {
  const rules = [{ rule_id: "user_1", status: "valid", text: "a", text_sha256: "x" },
    { rule_id: "user_2", status: "reactant_count", text: "b", text_sha256: "y" }];
  assert.deepEqual(plain(lib.usableRuleIds(rules)), ["user_1"]);
  assert.deepEqual(plain(lib.ruleStatusText(rules[1])), "반응물 템플릿이 2개가 아님 (reactant_count)");
  assert.deepEqual(plain(lib.ruleStatusText(rules[0])), "검증 통과 (valid)");
  const none = lib.enumerateArgs({ inspectionHandle: "i", siteAtoms: [4, 2], useFixed: false, ruleIds: [] });
  assert.equal(none.ok, false);
  assert.match(none.errors[0], /no_generation_method/);
  assert.equal(lib.enumerateArgs({ inspectionHandle: null, siteAtoms: [2], useFixed: true, ruleIds: [] }).ok, false);
  const body = lib.enumerateArgs({ inspectionHandle: "i", siteAtoms: [4, 2], useFixed: true, ruleIds: ["user_1"] });
  assert.deepEqual(plain(body), { ok: true, args: { inspection_handle: "i", site_atoms: [2, 4], use_fixed: true,
    rule_ids: ["user_1"] } });
  const preview = { inspection_handle: "i", site_check: { site_atoms: [2, 4] }, use_fixed: true,
    rules: [{ rule_id: "user_1", status: "valid", usable: true }], ready: true, blocking_reasons: [] };
  assert.equal(lib.previewMatches(preview, body.args), true);
  assert.equal(lib.previewMatches(preview, { ...body.args, site_atoms: [2] }), false);
  assert.equal(lib.previewMatches(preview, { ...body.args, use_fixed: false }), false);
  assert.equal(lib.previewMatches(preview, { ...body.args, rule_ids: [] }), false);
  assert.equal(lib.previewMatches(null, body.args), false);
  assert.equal(lib.enumerateReady(preview, body.args), true);
  assert.equal(lib.enumerateReady({ ...preview, ready: false, blocking_reasons: ["crossing_bond_count"] }, body.args),
    false);
  assert.deepEqual(plain(lib.previewBlockingText({ ...preview, ready: false,
    blocking_reasons: ["crossing_bond_count", "rule_invalid"] })),
  ["부위와 나머지를 잇는 결합이 정확히 1개가 아님 (crossing_bond_count)", "점검에서 통과하지 않은 규칙 (rule_invalid)"]);
});

test("the 2D drawing is an image data URI, never markup", () => {
  const uri = lib.svgDataUri("<svg xmlns='http://www.w3.org/2000/svg'><text>C1 #</text></svg>");
  assert.ok(uri.startsWith("data:image/svg+xml;charset=utf-8,"));
  assert.ok(!uri.includes("<") && !uri.includes("#"));
  assert.equal(decodeURIComponent(uri.slice("data:image/svg+xml;charset=utf-8,".length)),
    "<svg xmlns='http://www.w3.org/2000/svg'><text>C1 #</text></svg>");
});

// ---- wording ----
test("screen wording never claims activity, drug-likeness, toxicity or synthesis", () => {
  const forbidden = ["활성", "약물 유사", "약물유사", "독성", "안전", "합성 가능", "친화", "좋은", "나쁜", "최적", "억제"];
  const strings = [...Object.values(lib.LIGAND_REASON_LABEL), ...Object.values(lib.PROPERTY_LABEL),
    ...Object.values(lib.PROPERTY_UNIT), ...lib.PROPERTY_NAMES.map(lib.propertyHeader), lib.PROPERTY_NOTE,
    lib.PAINS_HEADER, lib.PAINS_NOTE, lib.NULL_RESULT_TEXT, lib.CANDIDATE_2D_NOTE, lib.NO_RUN_REASON];
  for (const text of strings) for (const word of forbidden) assert.ok(!text.includes(word), `${word} in ${text}`);
  assert.ok(lib.PROPERTY_NOTE.includes("RDKit 추정값"));
  assert.ok(lib.PAINS_HEADER.includes("구조 경고 일치"));
});
