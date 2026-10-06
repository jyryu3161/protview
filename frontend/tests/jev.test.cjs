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
const eventModel = load("event-model");
const siteAnnotation = load("site-annotation", { "./comparison": load("comparison"), "./numbering": load("numbering"),
  "./event-model": eventModel });
const lib = load("jev", { "./site-annotation": siteAnnotation }, { crypto: globalThis.crypto });
const reportLibrary = load("report-library");
const plain = value => JSON.parse(JSON.stringify(value));

// ---- closed sets, caps and fixed sentences are read from backend/mw/jev_constants.py itself ----
const constantsSource = fs.readFileSync(path.join(__dirname, "../../backend/mw/jev_constants.py"), "utf8");
function pyTuple(name) {
  const match = new RegExp(`^${name} = \\(([^)]*)\\)`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map(item => item[1]);
}
function pyNumber(name) {
  const match = new RegExp(`^${name} = ([0-9_]+)\\b`, "m").exec(constantsSource);
  assert.ok(match, `backend constant ${name} not found`);
  return Number(match[1].replace(/_/g, ""));
}
function pyString(name) {
  const match = new RegExp(`^${name} = "([^"]+)"`, "m").exec(constantsSource);
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

// spec .dryforge/spec.md 6, verbatim (the hand copy the module and the backend are compared with)
const SPEC_J = {
  J1: "JEV 판정은 외부 모델이 보낸 후보 목록에서 고른 하나일 뿐이며 계산 결과가 아니라 제안으로 따로 기록한 것이다. 순위·추천·예측이 아니다.",
  J2: "고른 이유는 알 수 없다. 응답에는 선택과 모델이 보고한 확신도·확률만 있으며 과학 값이 아니다.",
  J3: "외부로 나간 내용은 승인한 미리보기 본문과 바이트가 같고(해시로 확인) 그 본문이 이 기록의 근거 전부이다.",
  J4: "모델 선택은 후보 목록의 순서(로컬 저장 순서)의 영향을 받을 수 있다.",
  J5: "후보는 2D 그래프이고 속성값은 RDKit 추정값이며 결합·활성·합성 가능성을 계산하지 않았고 수용체 정보 없이 고른 것이다.",
  J6: "후보는 위치와 바꿀 잔기의 조합이고 이웃 잔기·구간·거리는 준비된 구조의 저장 좌표에서 잰 기하이며 변이의 효과나 상호작용을 뜻하지 않는다. 보호 판정은 사용자 목록·KLIFS 주요 부위(주석이 있을 때)·금속 근접·이황화 기준으로만 했고 촉매 잔기 데이터베이스는 사용하지 않았으며, 검사하지 않은 항목은 '없음'이 아니다.",
  J7: "이 응답은 run 취소 또는 과학 전송 동의 끄기 뒤에 도착했으며 어떤 작업도 일으키지 않았다.",
};
const SPEC_U = {
  U1: "같은 후보 목록을 다시 보내면 응답이 달라질 수 있다. 응답은 합치거나 다수결로 쓰지 않고 시간순으로 따로 보인다.",
  U2: "과학 전송은 뷰어 모델 명령과 같은 외부 토큰·USD 예산과 '사용량 모름' 중지 상태를 쓰며, 한쪽이 예산을 다 쓰거나 사용량을 모르면 이 run에서 다른 쪽도 멈춘다.",
  U3: "보내는 서열 구간과 이웃 잔기 이름만으로도 어떤 단백질인지 알려질 수 있다. 번호 대응·accession은 보내지 않는다.",
};

// ---- fixtures (synthetic; handles and hashes are placeholders, no scientific value) ----
const RUN = "run-a";
const LIG_SET = `obj://${RUN}/ligand_candidate_set/${"a".repeat(64)}`;
const LIG_SET_2 = `obj://${RUN}/ligand_candidate_set/${"e".repeat(64)}`;
const MUT_SET = `obj://${RUN}/mutation_candidate_set/${"c".repeat(64)}`;
const PROJ = `obj://${RUN}/jev_projection/${"b".repeat(64)}`;
const PROJ_2 = `obj://${RUN}/jev_projection/${"7".repeat(64)}`;
const CHOICE = `obj://${RUN}/jev_choice/${"9".repeat(64)}`;
const SID = "123e4567-e89b-42d3-a456-426614174000";
const SID_2 = "9b2c5a0e-1f3d-4c6b-8e7a-0d1c2b3a4f5e";
const AUDIT = `eg_${"e".repeat(32)}`;
const id16 = n => `c_${n.toString(16).padStart(16, "0")}`;
const INSTRUCTIONS = "Choose exactly one candidate from the list to place first in a local computation queue. This is a " +
  "queue-order choice only; it is not a prediction of binding, activity, affinity, stability, synthesizability, safety " +
  "or the effect of a substitution. Property values are RDKit estimates, not measurements or interactions. The order of " +
  "the candidate list is the local stored order only and carries no meaning.";
const BODY = JSON.stringify({ model: "typesafe/jev-1.13", provider: { allow_fallbacks: false, data_collection: "deny", zdr: true },
  questions: { candidate_choice: { criteria: { c01: "Candidate c01.", c02: "Candidate c02." }, instructions: INSTRUCTIONS,
    type: "choice" } }, state: { schema: "jev_ligand_candidates@1", candidates: [{ alias: "c01", smiles: "CCO" }] } });
const SELECTION = [{ alias: "c01", candidate_id: id16(1) }, { alias: "c02", candidate_id: id16(2) },
  { alias: "c03", candidate_id: id16(3) }];
const preview = over => ({ schema: "jev_preview@1", projection_handle: PROJ, kind: "ligand",
  source: { handle: LIG_SET, schema: "ligand_candidate_set@1" },
  question: { id: "ligand_candidate_choice@1", key: "candidate_choice", type: "choice", instructions: INSTRUCTIONS,
    instructions_sha256: "c".repeat(64) },
  body: BODY, body_sha256: "d".repeat(64), body_bytes: BODY.length, selection: SELECTION.slice(0, 2), selection_sent: false,
  reservation: { external_tokens: 4096 + Math.ceil(BODY.length / 2), usd: 0.1 }, send_cap: 10, used: 3, remaining: 7,
  budget_remaining: { external_tokens: 110000, usd: 1.9 }, blocked_by: [], previous_sends: 2, ...over });
const USAGE = { input_tokens: 1500, output_tokens: 20, external_tokens: 1520, cost: 0.00123 };
const RESIDUE = { model_number: 1, chain_auth: "A", chain_label: "A", seq_auth: 42, seq_label: 40, icode: "", resname: "LYS" };
const choice = over => ({ schema: "jev_choice@1", method_version: "mw.jev_choice/v1", label: "JEV 판정(모델 선택)",
  scientific_result: false, send: { send_id: SID, audit_id: AUDIT }, source: { handle: LIG_SET, schema: "ligand_candidate_set@1" },
  projection: { handle: PROJ, wire_sha256: "f".repeat(64), body_sha256: "d".repeat(64), body_bytes: 1234 },
  question: { id: "ligand_candidate_choice@1", key: "candidate_choice", instructions_sha256: "c".repeat(64) },
  requested_model: "typesafe/jev-1.13", served_model: "typesafe/jev-1.13-20260917", selection: SELECTION,
  answer: { choice_alias: "c02", local_ref: { candidate_id: id16(2) }, local_display: { smiles: "CC(=O)Nc1ccc(O)cc1" },
    confidence: 0.87654, probabilities: { c03: 0.2, c02: 0.7, c01: 0.1 } },
  usage: USAGE, arrival: { late: false, late_reason: null },
  limitations: [SPEC_J.J1, SPEC_J.J2, SPEC_J.J3, SPEC_J.J4, SPEC_J.J5], ...over });
const record = over => ({ schema: "jev_send@1", send_id: SID, status: "completed", reason_code: null, projection_handle: PROJ,
  source: { handle: LIG_SET, schema: "ligand_candidate_set@1" }, kind: "ligand", question_id: "ligand_candidate_choice@1",
  selection_count: 3, body_sha256: `0123abcd${"a".repeat(56)}`, body_bytes: 1234, audit_id: AUDIT,
  requested_model: "typesafe/jev-1.13", served_model: "typesafe/jev-1.13-20260917", usage: USAGE, choice_handle: CHOICE,
  late: false, late_reason: null, approved_event_seq: 10, outcome_event_seq: 14, ...over });
const detail = (over, choiceOver) => {
  const value = choice(choiceOver);
  return { ...record(over), choice: value, local_display: value.answer.local_display };
};
const statusOf = over => ({ schema: "jev_status@1", enabled: false, policy: "jev_science@1", send_cap: 10, used: 4,
  remaining: 6, budget: { external_tokens: { used: 20000, limit: 120000, remaining: 100000 },
    usd: { used: 0.25, limit: 2, remaining: 1.75 } }, egress_stop_reason: null, dry_run: false, cancelled: false,
  question_ids: ["ligand_candidate_choice@1", "mutation_candidate_choice@1"], send_in_progress: false,
  request_model: "typesafe/jev-1.13", allowed_served_model: "typesafe/jev-1.13-20260917",
  destination: "https://openrouter.ai/api/alpha/decisions", ...over });
const ligandRow = (n, passes = null) => ({ generation_order: n, candidate: { id: id16(n), smiles: "C".repeat(n + 1) },
  filters: {}, passes_all: passes });
const mutationRow = (index, position = index) => ({ index, position_index: position, residue: RESIDUE,
  standard_resname: "LYS", from: "K", to: "A" });
const ligandOption = (n, passes = null, source = LIG_SET) => lib.ligandCandidateOption(source, ligandRow(n, passes));
const mutationOption = (index, source = MUT_SET) => lib.mutationCandidateOption(source, mutationRow(index));
function choose(selection, options) {
  return options.reduce((current, option) => {
    const out = lib.toggleJevCandidate(current, option, true);
    assert.equal(out.refused, null);
    return out.selection;
  }, selection);
}

// ---- constants ----

test("closed sets, caps and fixed sentences equal backend/mw/jev_constants.py and the spec text", () => {
  assert.deepEqual(plain(lib.PREVIEW_BLOCK_REASONS), pyTuple("PREVIEW_BLOCK_REASONS"));
  assert.deepEqual(plain(lib.REJECTED_REASONS), pyTuple("REJECTED_REASONS"));
  assert.deepEqual(plain(lib.FAILED_REASONS), pyTuple("FAILED_REASONS"));
  assert.deepEqual(plain(lib.LATE_REASONS), pyTuple("LATE_REASONS"));
  assert.deepEqual(plain(lib.PROJECTION_REASON_CODES), [...pyTuple("PROJECTION_REASON_CODES"), pyString("PROJECTION_INVALID")]);
  assert.deepEqual(plain(lib.SEND_STATUSES), [...pyTuple("SEND_STATUSES"), pyString("IN_PROGRESS")]);
  for (const code of pyTuple("SEND_CONFLICT_REASONS")) assert.ok(lib.SEND_ERROR_CODES.includes(code), code);
  assert.deepEqual(plain(lib.QUESTION_IDS), [pyString("LIGAND_QUESTION_ID"), pyString("MUTATION_QUESTION_ID")]);
  assert.equal(lib.JEV_MAX_CANDIDATES, pyNumber("MAX_CANDIDATES"));
  assert.equal(lib.JEV_MAX_CANDIDATES, 20);
  assert.equal(lib.JEV_SEND_CAP, pyNumber("SEND_CAP"));
  assert.equal(lib.JEV_SEND_CAP, 10);
  assert.equal(lib.JEV_TOOL, pyString("TOOL"));
  assert.equal(lib.JEV_CONFIRM, pyString("CONFIRM"));
  assert.equal(lib.JEV_CHOICE_LABEL, pyString("CHOICE_LABEL"));
  assert.equal(lib.JEV_CHOICE_LABEL, "JEV 판정(모델 선택)");
  assert.equal(lib.JEV_CONFIDENCE_LABEL, "모델 보고 확신도(0–1, 과학 값 아님)");
  assert.equal(lib.JEV_REPORT_TYPE, "jev_choice");
  assert.equal(lib.JEV_REPORT_LABEL, "JEV 판정 보고서");
  for (const key of Object.keys(SPEC_J)) assert.equal(pySentence(key), SPEC_J[key], `backend ${key}`);
  for (const key of Object.keys(SPEC_U)) assert.equal(pySentence(key), SPEC_U[key], `backend ${key}`);
  assert.deepEqual(plain(lib.JEV_STATEMENTS), SPEC_J);
  assert.deepEqual(plain(lib.JEV_SCREEN_NOTES), SPEC_U);
  assert.deepEqual(Object.keys(lib.JEV_SCREEN_NOTES), ["U1", "U2", "U3"]);
  // the consent notice names the one destination, the content kinds, per-send approval, the cap and the provider policy
  const notice = lib.CONSENT_NOTICE.join("\n");
  for (const part of ["OpenRouter의 JEV 하나", "보낼 수 있는 내용", "전송마다", "승인", "run당 과학 전송은 10회",
    "data_collection=deny", "zdr", "뷰어 모델 명령의 온라인 동의와 별개"]) assert.ok(notice.includes(part), part);
});

// ---- closed reason labels ----

test("every closed code has a Korean label as \"한국어 (code)\"; values outside the set get the fixed default", () => {
  const sets = [[lib.PREVIEW_BLOCK_REASONS, lib.blockReasonText, 7], [lib.REJECTED_REASONS, lib.rejectedReasonText, 8],
    [lib.FAILED_REASONS, lib.failedReasonText, 8], [lib.PROJECTION_REASON_CODES, lib.projectionReasonText, 10],
    [lib.SEND_STATUSES, lib.sendStatusText, 4], [lib.SEND_ERROR_CODES, lib.errorCodeText, lib.SEND_ERROR_CODES.length]];
  for (const [codes, text, size] of sets) {
    assert.equal(codes.length, size);
    for (const code of codes) assert.match(text(code), new RegExp(`^[^\\s(].* \\(${code}\\)$`), code);
    for (const outside of ["brand_new_code", "toString", "__proto__", "constructor", "", null, undefined, 42, {}])
      assert.equal(text(outside), lib.UNKNOWN_CODE_TEXT, String(outside));
  }
  assert.equal(lib.LATE_REASONS.length, 2);
  assert.equal(lib.lateReasonText("run_cancelled"), "run 취소 뒤 도착");
  assert.equal(lib.lateReasonText("consent_off"), "동의 끈 뒤 도착");
  // a code of one set is not silently accepted by another
  assert.equal(lib.blockReasonText("missing_credential"), lib.UNKNOWN_CODE_TEXT);
  assert.equal(lib.rejectedReasonText("external_timeout"), lib.UNKNOWN_CODE_TEXT);
  assert.equal(lib.failedReasonText("dry_run"), lib.UNKNOWN_CODE_TEXT);
  assert.equal(lib.lateReasonText("cancelled"), lib.UNKNOWN_CODE_TEXT);
  assert.equal(lib.lateReasonText("toString"), lib.UNKNOWN_CODE_TEXT);
  assert.equal(lib.sendReasonText("rejected", "consent_off"), lib.rejectedReasonText("consent_off"));
  assert.equal(lib.sendReasonText("failed", "delivery_unknown"), lib.failedReasonText("delivery_unknown"));
  assert.equal(lib.sendReasonText("failed", "dry_run"), lib.UNKNOWN_CODE_TEXT);
  assert.equal(lib.sendReasonText("completed", null), null);
  assert.equal(lib.sendReasonText("in_progress", null), null);
  // the default never echoes the unknown value
  assert.ok(!lib.UNKNOWN_CODE_TEXT.includes("brand_new_code"));
});

// ---- candidate guard ----

test("candidate guard: 20 can be chosen, the 21st check is refused with its reason, unchecking frees a place", () => {
  let selection = lib.emptyJevSelection("ligand", LIG_SET);
  assert.equal(lib.jevSelectionCountText(selection), "선택 0/20");
  selection = choose(selection, Array.from({ length: 20 }, (_, i) => ligandOption(i + 1)));
  assert.equal(selection.items.length, 20);
  assert.equal(lib.jevSelectionCountText(selection), "선택 20/20");
  const twentyFirst = ligandOption(21);
  assert.equal(lib.jevCandidateBlockedReason(selection, twentyFirst), lib.SELECTION_FULL_REASON);
  assert.match(lib.SELECTION_FULL_REASON, /20개까지/);
  const refused = lib.toggleJevCandidate(selection, twentyFirst, true);
  assert.equal(refused.refused, lib.SELECTION_FULL_REASON);
  assert.equal(refused.selection, selection);
  assert.equal(lib.jevCandidateChecked(selection, twentyFirst), false);
  // a chosen candidate can always be unchecked (never blocked), which frees one place
  assert.equal(lib.jevCandidateBlockedReason(selection, ligandOption(5)), null);
  const fewer = lib.toggleJevCandidate(selection, ligandOption(5), false);
  assert.equal(fewer.refused, null);
  assert.equal(fewer.selection.items.length, 19);
  assert.equal(lib.jevCandidateBlockedReason(fewer.selection, twentyFirst), null);
  const again = lib.toggleJevCandidate(fewer.selection, twentyFirst, true);
  assert.equal(again.refused, null);
  assert.equal(again.selection.items.length, 20);
  // unchecking something not chosen changes nothing
  assert.deepEqual(plain(lib.toggleJevCandidate(again.selection, ligandOption(99), false).selection), plain(again.selection));
  // mutation sets have the same 20 limit
  let mutation = choose(lib.emptyJevSelection("mutation", MUT_SET), Array.from({ length: 20 }, (_, i) => mutationOption(i)));
  assert.equal(lib.toggleJevCandidate(mutation, mutationOption(20), true).refused, lib.SELECTION_FULL_REASON);
  mutation = lib.toggleJevCandidate(mutation, mutationOption(0), false).selection;
  assert.equal(mutation.items.length, 19);
});

test("ligand guard: only candidates that pass the applied filter (or with no filter) can be checked; no duplicates", () => {
  const empty = lib.emptyJevSelection("ligand", LIG_SET);
  // passes_all null = no filter applied: every candidate is kept (the M17 / M22 rule)
  assert.equal(lib.jevCandidateBlockedReason(empty, ligandOption(1, null)), null);
  assert.equal(lib.jevCandidateBlockedReason(empty, ligandOption(2, true)), null);
  assert.equal(lib.jevCandidateBlockedReason(empty, ligandOption(3, false)), lib.FILTERED_OUT_REASON);
  const refused = lib.toggleJevCandidate(empty, ligandOption(3, false), true);
  assert.equal(refused.refused, lib.FILTERED_OUT_REASON);
  assert.equal(refused.selection.items.length, 0);
  // checking twice keeps one entry
  let selection = choose(empty, [ligandOption(2, true)]);
  selection = lib.toggleJevCandidate(selection, ligandOption(2, true), true).selection;
  assert.equal(selection.items.length, 1);
  // a candidate of another set or kind is refused (identifiers are never mixed)
  assert.equal(lib.jevCandidateBlockedReason(selection, ligandOption(4, null, LIG_SET_2)), lib.SOURCE_MISMATCH_REASON);
  assert.equal(lib.jevCandidateBlockedReason(selection, mutationOption(4, LIG_SET)), lib.SOURCE_MISMATCH_REASON);
  assert.equal(lib.toggleJevCandidate(selection, mutationOption(4, LIG_SET), true).refused, lib.SOURCE_MISMATCH_REASON);
  // mutation candidates are never filter-blocked
  assert.equal(lib.jevCandidateBlockedReason(lib.emptyJevSelection("mutation", MUT_SET), mutationOption(7)), null);
  // a chosen candidate that the current filter now rejects is listed (the person unchecks it; nothing is dropped silently)
  selection = choose(empty, [ligandOption(1, true), ligandOption(2, true), ligandOption(3, true)]);
  assert.deepEqual(plain(lib.jevFilterConflicts(selection, [ligandRow(3, false), ligandRow(1, true), ligandRow(9, false)])),
    [id16(3)]);
  assert.deepEqual(plain(lib.jevFilterConflicts(selection, [ligandRow(3, null)])), []);
  assert.deepEqual(plain(lib.jevFilterConflicts(choose(lib.emptyJevSelection("mutation", MUT_SET), [mutationOption(1)]),
    [ligandRow(1, false)])), []);
});

test("candidates go to the tool in the source set's stored order whatever the click order", () => {
  const ligand = choose(lib.emptyJevSelection("ligand", LIG_SET), [ligandOption(7), ligandOption(2), ligandOption(11)]);
  assert.deepEqual(plain(lib.jevSelectedCandidates(ligand)), [id16(2), id16(7), id16(11)]);
  const mutation = choose(lib.emptyJevSelection("mutation", MUT_SET), [mutationOption(30), mutationOption(4), mutationOption(12)]);
  assert.deepEqual(plain(lib.jevSelectedCandidates(mutation)), [4, 12, 30]);
  assert.equal(typeof lib.jevSelectedCandidates(mutation)[0], "number");
  assert.equal(lib.jevCandidateChecked(mutation, mutationOption(12)), true);
  assert.equal(lib.jevCandidateChecked(mutation, mutationOption(13)), false);
});

test("projection args: exactly source, candidates and filter; 1–20; filter only for ligand, null when none applied", () => {
  const spec = { ranges: { mol_weight: { min: 100, max: 500 } }, pains_exclude: false };
  const none = { ranges: {}, pains_exclude: false };
  const ligand = choose(lib.emptyJevSelection("ligand", LIG_SET), [ligandOption(3, true), ligandOption(1, true)]);
  const out = lib.jevProjectionArgs(ligand, spec);
  assert.equal(out.ok, true);
  assert.deepEqual(Object.keys(out.args), ["source", "candidates", "filter"]);
  assert.deepEqual(plain(out.args), { source: LIG_SET, candidates: [id16(1), id16(3)], filter: spec });
  assert.equal(lib.jevProjectionArgs(ligand, none).args.filter, null);
  assert.equal(lib.jevProjectionArgs(ligand, null).args.filter, null);
  assert.deepEqual(plain(lib.jevProjectionArgs(ligand, { ranges: {}, pains_exclude: true }).args.filter),
    { ranges: {}, pains_exclude: true });
  const mutation = choose(lib.emptyJevSelection("mutation", MUT_SET), [mutationOption(5)]);
  assert.deepEqual(plain(lib.jevProjectionArgs(mutation, null).args), { source: MUT_SET, candidates: [5], filter: null });
  assert.deepEqual(plain(lib.jevProjectionArgs(mutation, none).args), { source: MUT_SET, candidates: [5], filter: null });
  const filtered = lib.jevProjectionArgs(mutation, spec);
  assert.equal(filtered.ok, false);
  assert.ok(filtered.errors.some(text => text.includes("(filter_invalid)")));
  const empty = lib.jevProjectionArgs(lib.emptyJevSelection("ligand", LIG_SET), null);
  assert.equal(empty.ok, false);
  assert.ok(empty.errors.some(text => text.includes("(selection_invalid)")));
  assert.deepEqual(plain(lib.jevProjectionArgs(null, null)), { ok: false, errors: [lib.NO_SOURCE_REASON] });
  const tooMany = { kind: "ligand", source: LIG_SET, items: Array.from({ length: 21 }, (_, i) => ({ key: id16(i), order: i })) };
  assert.equal(lib.jevProjectionArgs(tooMany, null).ok, false);
});

// ---- preview and approval ----

test("preview view keeps the exact body string, bytes, SHA-256, alias table (not sent), reservation and blockers", () => {
  const input = preview({ blocked_by: ["consent_off", "send_cap_exhausted"] });
  const before = plain(input);
  const view = lib.jevPreviewView(input);
  assert.equal(view.body, BODY);                              // byte for byte, never re-serialized or parsed
  assert.equal(view.instructions, INSTRUCTIONS);
  assert.equal(view.bodySha256, "d".repeat(64));
  assert.equal(view.bodyBytesText, `${BODY.length} 바이트`);
  assert.equal(view.projectionHandle, PROJ);
  assert.equal(view.questionId, "ligand_candidate_choice@1");
  assert.equal(view.kindText, "리간드 후보");
  assert.deepEqual(plain(view.aliasRows), [
    { alias: "c01", localRefText: `후보 ${id16(1)}`, sentText: "전송하지 않음" },
    { alias: "c02", localRefText: `후보 ${id16(2)}`, sentText: "전송하지 않음" }]);
  assert.equal(view.reservationText, `예약: 외부 토큰 ${4096 + Math.ceil(BODY.length / 2)} · 0.1000 USD`);
  assert.equal(view.capText, "run당 과학 전송 10회 · 사용 3회 · 남은 7회");
  assert.equal(view.budgetRemainingText, "남은 외부 토큰 110000 · 남은 1.9000 USD");
  assert.deepEqual(plain(view.blocked), [
    { code: "consent_off", text: lib.blockReasonText("consent_off") },
    { code: "send_cap_exhausted", text: lib.blockReasonText("send_cap_exhausted") }]);
  assert.equal(view.previousSendsText, "같은 투영으로 이전에 보낸 수: 2회");
  assert.deepEqual(plain(input), before);                    // the response is not changed
  const mutationView = lib.jevPreviewView(preview({ kind: "mutation", selection: [
    { alias: "m01", candidate_index: 12, position_index: 3 }] }));
  assert.equal(mutationView.kindText, "변이 후보");
  assert.equal(mutationView.aliasRows[0].localRefText, "후보 번호 12 · 위치 번호 3");
});

test("canSend only with zero blockers, the confirmation checked and no send in flight", () => {
  const ready = preview();
  assert.equal(lib.jevCanSend({ preview: ready, confirmed: true, sending: false }), true);
  assert.deepEqual(plain(lib.jevSendBlockers({ preview: ready, confirmed: true, sending: false })), []);
  assert.equal(lib.jevCanSend({ preview: ready, confirmed: false, sending: false }), false);
  assert.deepEqual(plain(lib.jevSendBlockers({ preview: ready, confirmed: false, sending: false })), [lib.CONFIRM_REQUIRED_REASON]);
  assert.equal(lib.jevCanSend({ preview: ready, confirmed: true, sending: true }), false);
  assert.deepEqual(plain(lib.jevSendBlockers({ preview: ready, confirmed: true, sending: true })), [lib.SENDING_REASON]);
  assert.equal(lib.jevCanSend({ preview: null, confirmed: true, sending: false }), false);
  assert.deepEqual(plain(lib.jevSendBlockers({ preview: null, confirmed: true, sending: false })), [lib.NO_PREVIEW_REASON]);
  for (const code of lib.PREVIEW_BLOCK_REASONS) {
    const blocked = preview({ blocked_by: [code] });
    assert.equal(lib.jevCanSend({ preview: blocked, confirmed: true, sending: false }), false, code);
    assert.deepEqual(plain(lib.jevSendBlockers({ preview: blocked, confirmed: true, sending: false })),
      [lib.blockReasonText(code)]);
  }
  assert.equal(lib.jevSendBlockers({ preview: preview({ blocked_by: ["dry_run", "consent_off"] }), confirmed: false,
    sending: true }).length, 4);
  assert.equal(lib.CONFIRM_CHECK_TEXT, "이 본문 그대로 외부 서비스(JEV)로 보내는 데 동의합니다");
  assert.equal(lib.SEND_BUTTON_TEXT, "이 내용을 JEV로 보냅니다");
});

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

test("send_id: crypto.randomUUID first, a v4 fallback from random bytes, always canonical lowercase v4", () => {
  assert.equal(String(lib.UUID_V4_RE), String(UUID_V4));
  assert.equal(lib.newSendId({ randomUUID: () => SID }), SID);
  // an unusable randomUUID answer (upper case, version 1) falls back to random bytes
  const ff = { randomUUID: () => SID.toUpperCase(), getRandomValues: bytes => { bytes.fill(255); return bytes; } };
  assert.equal(lib.newSendId(ff), "ffffffff-ffff-4fff-bfff-ffffffffffff");
  const zero = { randomUUID: () => "123e4567-e89b-12d3-a456-426614174000", getRandomValues: bytes => bytes };
  assert.equal(lib.newSendId(zero), "00000000-0000-4000-8000-000000000000");
  // no crypto at all: still the v4 form
  for (const source of [null, {}]) assert.match(lib.newSendId(source), UUID_V4);
  // the default uses the global crypto
  const ids = new Set(Array.from({ length: 200 }, () => lib.newSendId()));
  assert.equal(ids.size, 200);
  for (const value of ids) assert.match(value, UUID_V4);
});

test("send_id is reused for the same preview until an answer arrives, then a new one is made", () => {
  let made = 0;
  const make = () => [SID, SID_2, "0f0e0d0c-0b0a-4908-8706-050403020100"][made++];
  const first = lib.jevSendAttempt(null, preview(), make);
  assert.deepEqual(plain(first), { projectionHandle: PROJ, bodySha256: "d".repeat(64), sendId: SID });
  assert.deepEqual(plain(lib.jevSendRequest(first)),
    { send_id: SID, projection: PROJ, body_sha256: "d".repeat(64), confirm: "send_to_jev" });
  // a double click or a retry after no answer (network error, busy, in progress, mismatch) keeps the same id
  assert.equal(lib.jevSendAttempt(first, preview(), make), first);
  for (const code of [null, "busy", "send_in_progress", "preview_mismatch", "input_invalid", "transient"])
    assert.equal(lib.jevAttemptAfter(first, { record: false, code }), first, String(code));
  assert.equal(made, 1);
  // any jev_send@1 answer (completed, rejected, failed) or a send_id conflict ends the attempt
  assert.equal(lib.jevAttemptAfter(first, { record: true }), null);
  assert.equal(lib.jevAttemptAfter(first, { record: false, code: "send_id_conflict" }), null);
  assert.equal(lib.jevAttemptAfter(null, { record: true }), null);
  const second = lib.jevSendAttempt(lib.jevAttemptAfter(first, { record: true }), preview(), make);
  assert.equal(second.sendId, SID_2);
  // another preview (projection or body) never reuses the id
  const other = lib.jevSendAttempt(second, preview({ projection_handle: PROJ_2 }), make);
  assert.notEqual(other.sendId, SID_2);
  assert.equal(other.projectionHandle, PROJ_2);
  assert.notEqual(lib.jevSendAttempt(other, preview({ projection_handle: PROJ_2, body_sha256: "1".repeat(64) }),
    () => SID).sendId, other.sendId);
  // the default maker produces v4 ids
  assert.match(lib.jevSendAttempt(null, preview()).sendId, UUID_V4);
});

// ---- result card ----

test("result card keeps the stored answer, shows probabilities in the sent order and rounds for display only", () => {
  const input = detail();
  const before = plain(input);
  const view = lib.jevResultView(input);
  assert.equal(view.state, "completed");
  const card = view.card;
  assert.equal(card.label, "JEV 판정(모델 선택)");
  assert.equal(card.chosenAlias, "c02");
  assert.equal(card.localRefText, `후보 ${id16(2)}`);
  assert.equal(card.localDisplayText, "CC(=O)Nc1ccc(O)cc1");
  assert.equal(card.confidenceLabel, "모델 보고 확신도(0–1, 과학 값 아님)");
  assert.equal(card.confidence, 0.87654);                     // stored value unchanged
  assert.equal(card.confidenceText, "0.877");                 // display rounding only (ROUND_HALF_UP)
  assert.equal(card.probabilitiesReported, true);
  assert.equal(card.probabilityText, null);
  // the selection order (c01, c02, c03), never the reply's key order or the value order; no rank field
  assert.deepEqual(plain(card.probabilityRows), [
    { alias: "c01", localRefText: `후보 ${id16(1)}`, value: 0.1, text: "0.100" },
    { alias: "c02", localRefText: `후보 ${id16(2)}`, value: 0.7, text: "0.700" },
    { alias: "c03", localRefText: `후보 ${id16(3)}`, value: 0.2, text: "0.200" }]);
  for (const row of card.probabilityRows) assert.deepEqual(Object.keys(row), ["alias", "localRefText", "value", "text"]);
  assert.equal(card.reasonText, lib.CHOICE_REASON_TEXT);
  assert.equal(card.requestedModel, "typesafe/jev-1.13");
  assert.equal(card.servedModel, "typesafe/jev-1.13-20260917");
  assert.deepEqual(plain(card.usageRows.map(row => [row.key, row.text])),
    [["input_tokens", "1500"], ["output_tokens", "20"], ["external_tokens", "1520"], ["cost", "0.00123"]]);
  assert.equal(card.lateText, null);
  assert.deepEqual(plain(card.limitations), [SPEC_J.J1, SPEC_J.J2, SPEC_J.J3, SPEC_J.J4, SPEC_J.J5]);
  assert.equal(card.sendId, SID);
  assert.equal(card.choiceHandle, CHOICE);
  assert.deepEqual(plain(input), before);                    // nothing in the stored proposal is reordered or rounded
  // half-up on the decimal string: 0.0005 -> 0.001, 1 -> 1.000, 0 -> 0.000
  assert.equal(lib.confidenceText(0.0005), "0.001");
  assert.equal(lib.confidenceText(1), "1.000");
  assert.equal(lib.confidenceText(0), "0.000");
  assert.equal(lib.confidenceText(null), "보고 없음");
  // a reply that reported only some candidates: the others say so; the order is still the sent order
  const partial = lib.jevResultView(detail({}, { answer: { ...choice().answer, probabilities: { c03: 0.25 } } })).card;
  assert.deepEqual(plain(partial.probabilityRows.map(row => [row.alias, row.value, row.text])),
    [["c01", null, "보고 없음"], ["c02", null, "보고 없음"], ["c03", 0.25, "0.250"]]);
  // keys that are object prototype names are not read through the prototype
  const proto = lib.probabilityRows([{ alias: "toString", candidate_id: id16(1) }], {});
  assert.deepEqual(plain(proto), [{ alias: "toString", localRefText: `후보 ${id16(1)}`, value: null, text: "보고 없음" }]);
});

test("null confidence and probabilities read '보고 없음'; null usage reads '알 수 없음' and 0 stays 0", () => {
  const card = lib.jevResultView(detail({ usage: null }, { usage: null,
    answer: { ...choice().answer, confidence: null, probabilities: null } })).card;
  assert.equal(card.confidence, null);
  assert.equal(card.confidenceText, "보고 없음");
  assert.equal(card.probabilitiesReported, false);
  assert.deepEqual(plain(card.probabilityRows), []);
  assert.equal(card.probabilityText, "보고 없음");
  assert.deepEqual(plain(card.usageRows.map(row => row.text)), ["알 수 없음", "알 수 없음", "알 수 없음", "알 수 없음"]);
  const someUnknown = lib.usageRows({ input_tokens: 0, output_tokens: null, external_tokens: null, cost: 0 });
  assert.deepEqual(plain(someUnknown.map(row => row.text)), ["0", "알 수 없음", "알 수 없음", "0"]);
  for (const row of lib.usageRows(null)) assert.ok(/[가-힣]/.test(row.label));
});

test("mutation local notation shows chain, seq_auth, insertion code and from→to; identifiers stay as stored", () => {
  const display = { residue: RESIDUE, from: "K", to: "A" };
  const card = lib.jevResultView(detail({ kind: "mutation" }, { selection: [{ alias: "m01", candidate_index: 12, position_index: 3 }],
    answer: { choice_alias: "m01", local_ref: { candidate_index: 12, position_index: 3 }, local_display: display,
      confidence: 0.5, probabilities: null } })).card;
  assert.equal(card.localRefText, "후보 번호 12 · 위치 번호 3");
  assert.equal(card.localDisplayText, "LYS 체인 A · seq_auth 42 · 삽입 코드 없음 · 모델 1 · K→A");
  assert.deepEqual(plain(card.localDisplay), display);
  assert.equal(lib.localDisplayText({ residue: { ...RESIDUE, icode: "B" }, from: "K", to: "R" }),
    "LYS 체인 A · seq_auth 42 · 삽입 코드 B · 모델 1 · K→R");
  assert.equal(lib.localDisplayText({ residue: { ...RESIDUE, chain_auth: null, icode: null }, from: "K", to: "R" }),
    "LYS 체인 — · seq_auth 42 · 삽입 코드 — · 모델 1 · K→R");
  assert.equal(lib.localDisplayText({ residue: { ...RESIDUE, chain_auth: "", model_number: 2 }, from: "K", to: "R" }),
    "LYS 체인 (빈 문자열) · seq_auth 42 · 삽입 코드 없음 · 모델 2 · K→R");
});

test("late arrival marks, refusals and failures show only the reason, in-progress shows no number", () => {
  const cancelled = lib.jevResultView(detail({ late: true, late_reason: "run_cancelled" },
    { arrival: { late: true, late_reason: "run_cancelled" }, limitations: [...choice().limitations, SPEC_J.J7] }));
  assert.equal(cancelled.card.lateText, "run 취소 뒤 도착");
  assert.equal(cancelled.card.limitations.at(-1), SPEC_J.J7);
  const consent = lib.jevResultView(detail({ late: true, late_reason: "consent_off" },
    { arrival: { late: true, late_reason: "consent_off" } }));
  assert.equal(consent.card.lateText, "동의 끈 뒤 도착");
  const rejected = lib.jevResultView({ ...record({ status: "rejected", reason_code: "consent_off", choice_handle: null,
    usage: null, served_model: null }), choice: null, local_display: null });
  assert.deepEqual(plain(rejected), { state: "rejected", statusText: lib.sendStatusText("rejected"),
    reasonText: lib.rejectedReasonText("consent_off") });
  const failed = lib.jevResultView({ ...record({ status: "failed", reason_code: "response_invalid", choice_handle: null }),
    choice: null, local_display: null });
  assert.deepEqual(plain(failed), { state: "failed", statusText: lib.sendStatusText("failed"),
    reasonText: lib.failedReasonText("response_invalid") });
  const running = lib.jevResultView({ ...record({ status: "in_progress", reason_code: null, choice_handle: null, usage: null,
    outcome_event_seq: null }), choice: null, local_display: null });
  assert.deepEqual(plain(running), { state: "in_progress", statusText: lib.sendStatusText("in_progress") });
  assert.ok(!/\d/.test(JSON.stringify(plain(running)).replace(/\(in_progress\)/, "")));
});

test("a proposal that does not belong to the send is not shown", () => {
  for (const [over, choiceOver] of [[{}, { send: { send_id: SID_2, audit_id: AUDIT } }], [{}, { scientific_result: true }],
    [{}, { label: "다른 이름" }], [{ choice_handle: null }, {}]]) {
    const view = lib.jevResultView(detail(over, choiceOver));
    assert.equal(view.state, "invalid");
    assert.equal(view.message, lib.CHOICE_MISMATCH_TEXT);
    assert.equal(view.card, undefined);
  }
  const missing = lib.jevResultView({ ...record(), choice: null, local_display: null });
  assert.equal(missing.state, "invalid");
});

// ---- send history ----

test("send history: oldest first, status, candidate count, hash prefix, late mark, in-progress, report only when completed", () => {
  const rows = lib.jevSendRows([
    record({ send_id: SID_2, approved_event_seq: 30, status: "in_progress", reason_code: null, choice_handle: null,
      outcome_event_seq: null, usage: null }),
    record({ approved_event_seq: 10, late: true, late_reason: "consent_off" }),
    record({ send_id: "0f0e0d0c-0b0a-4908-8706-050403020100", approved_event_seq: 20, status: "failed",
      reason_code: "delivery_unknown", choice_handle: null, kind: "mutation", selection_count: 20 }),
  ]);
  assert.deepEqual(plain(rows.map(row => row.approvedSeq)), [10, 20, 30]);
  assert.deepEqual(plain(rows[0]), { sendId: SID, status: "completed", statusText: lib.sendStatusText("completed"),
    reasonText: null, kindText: "리간드 후보", countText: "후보 3개", bodyHashText: "0123abcd", lateText: "동의 끈 뒤 도착",
    inProgress: false, choiceHandle: CHOICE, canOpen: true, canReport: true, approvedSeq: 10 });
  assert.equal(rows[1].reasonText, lib.failedReasonText("delivery_unknown"));
  assert.equal(rows[1].kindText, "변이 후보");
  assert.equal(rows[1].countText, "후보 20개");
  assert.equal(rows[1].canReport, false);
  assert.equal(rows[1].canOpen, true);
  assert.equal(rows[2].inProgress, true);
  assert.equal(rows[2].statusText, lib.sendStatusText("in_progress"));
  assert.equal(rows[2].canOpen, false);
  assert.equal(rows[2].canReport, false);
  // rows are separate per send: nothing is merged, counted across sends or marked as the latest
  assert.equal(rows.length, 3);
  for (const row of rows) assert.ok(!("latest" in row) && !("merged" in row) && !("votes" in row));
});

// ---- status, panel, sources ----

test("status view: cap, budget, badge only when consent is on, dry-run consent reason, egress stop text", () => {
  const status = { schema: "jev_status@1", enabled: true, policy: "jev_science@1", send_cap: 10, used: 4, remaining: 6,
    budget: { external_tokens: { used: 20000, limit: 120000, remaining: 100000 }, usd: { used: 0.25, limit: 2, remaining: 1.75 } },
    egress_stop_reason: null, dry_run: false, cancelled: false, question_ids: ["ligand_candidate_choice@1",
      "mutation_candidate_choice@1"], send_in_progress: false, request_model: "typesafe/jev-1.13",
    allowed_served_model: "typesafe/jev-1.13-20260917", destination: "https://openrouter.ai/api/alpha/decisions" };
  assert.equal(lib.jevCapText(status), "run당 과학 전송 10회 · 사용 4회 · 남은 6회");
  assert.equal(lib.jevBudgetText(status.budget),
    "외부 토큰 남은 100000 / 한도 120000 · USD 남은 1.7500 / 한도 2.0000");
  assert.equal(lib.scienceBadgeText(status), "과학 전송 허용");
  assert.equal(lib.scienceBadgeText({ ...status, enabled: false }), null);
  assert.equal(lib.scienceBadgeText(null), null);
  assert.equal(lib.consentSwitchDisabledReason(status, false), null);
  assert.equal(lib.consentSwitchDisabledReason({ ...status, enabled: false }, true), null);
  assert.match(lib.consentSwitchDisabledReason({ ...status, enabled: false, dry_run: true }, true), /\(dry_run\)$/);
  assert.equal(lib.consentSwitchDisabledReason({ ...status, dry_run: true }, false), null);   // turning off is always possible
  assert.equal(lib.consentSwitchDisabledReason(null, true), lib.STATUS_LOADING_REASON);
  assert.equal(lib.egressStopText(null), null);
  assert.equal(lib.egressStopText("usage_unknown"), "이 run의 외부 전송이 멈춤: 사용량 모름 (usage_unknown)");
  assert.equal(lib.egressStopText("budget_exhausted"), "이 run의 외부 전송이 멈춤: 예산 소진 (budget_exhausted)");
  assert.equal(lib.egressStopText("other"), `이 run의 외부 전송이 멈춤: ${lib.UNKNOWN_CODE_TEXT}`);
});

test("panel state: no run, unavailable capability, failure, loading and ready are told apart", () => {
  assert.deepEqual(plain(lib.jevPanelState({ runId: null })), { state: "unavailable", reason: lib.NO_RUN_REASON });
  assert.deepEqual(plain(lib.jevPanelState({ runId: RUN, capability: null })),
    { state: "unavailable", reason: lib.CAPABILITY_REASON });
  assert.deepEqual(plain(lib.jevPanelState({ runId: RUN, capability: { available: false, reason: "투영 도구 없음" } })),
    { state: "unavailable", reason: "투영 도구 없음" });
  assert.deepEqual(plain(lib.jevPanelState({ runId: RUN, capability: { available: true, reason: null }, error: "읽기 실패" })),
    { state: "failed", message: "읽기 실패" });
  assert.deepEqual(plain(lib.jevPanelState({ runId: RUN })), { state: "loading" });
  assert.deepEqual(plain(lib.jevPanelState({ runId: RUN, capability: { available: true, reason: null } })), { state: "loading" });
  assert.deepEqual(plain(lib.jevPanelState({ runId: RUN, capability: { available: true, reason: null }, status: {} })),
    { state: "ready" });
});

test("source options list this run's sets in server order with reasons, never pre-selecting one", () => {
  const ligandRows = [
    { handle: LIG_SET_2, created_seq: 40, valid: true, candidates: 0 },
    { handle: LIG_SET, created_seq: 20, valid: true, candidates: 12 },
    { handle: "obj://run-a/ligand_candidate_set/bad", created_seq: 10, valid: false, candidates: null }];
  assert.deepEqual(plain(lib.ligandSourceOptions(ligandRows)), [
    { handle: LIG_SET_2, text: "리간드 후보 집합 · 기록 순번 40 · 후보 0개", disabledReason: lib.EMPTY_SOURCE_REASON },
    { handle: LIG_SET, text: "리간드 후보 집합 · 기록 순번 20 · 후보 12개", disabledReason: null },
    { handle: "obj://run-a/ligand_candidate_set/bad", text: "리간드 후보 집합 · 기록 순번 10 · 후보 수 —",
      disabledReason: lib.INVALID_SOURCE_REASON }]);
  const mutationRows = [{ handle: MUT_SET, created_seq: 50, valid: true, counts: { candidates: 38 } },
    { handle: "obj://run-a/mutation_candidate_set/bad", created_seq: 5, valid: false, counts: null }];
  assert.deepEqual(plain(lib.mutationSourceOptions(mutationRows)), [
    { handle: MUT_SET, text: "변이 후보 집합 · 기록 순번 50 · 후보 38개", disabledReason: null },
    { handle: "obj://run-a/mutation_candidate_set/bad", text: "변이 후보 집합 · 기록 순번 5 · 후보 수 —",
      disabledReason: lib.INVALID_SOURCE_REASON }]);
  assert.deepEqual(plain(lib.ligandSourceOptions([])), []);
});

test("late responses apply only for the same run, handle and request number", () => {
  const stamp = { runId: RUN, handle: PROJ, seq: 3 };
  assert.equal(lib.jevResponseCurrent(stamp, { ...stamp }), true);
  assert.equal(lib.jevResponseCurrent(stamp, { ...stamp, runId: "run-b" }), false);
  assert.equal(lib.jevResponseCurrent(stamp, { ...stamp, handle: PROJ_2 }), false);
  assert.equal(lib.jevResponseCurrent(stamp, { ...stamp, seq: 4 }), false);
  assert.equal(lib.jevResponseCurrent({ ...stamp, runId: null }, { ...stamp, runId: null }), false);
  assert.ok(lib.JEV_AREAS.includes("preview") && lib.JEV_AREAS.includes("send") && lib.JEV_AREAS.includes("report"));
});

// ---- errors and the projection command ----

test("error parsing: projection reasons, send conflicts, busy, unknown codes and network errors", () => {
  const filtered = lib.jevErrorInfo({ status: 422, code: "input_invalid", message: "chosen candidates do not pass the filter",
    detail: { reason_code: "candidate_filtered_out", candidates: [id16(3)] } });
  assert.deepEqual(plain(filtered), { status: 422, code: "input_invalid", reasonCode: "candidate_filtered_out",
    text: `${lib.projectionReasonText("candidate_filtered_out")}: chosen candidates do not pass the filter` });
  const tooLarge = lib.jevErrorInfo({ status: 429, code: "resource_exceeded", message: "", detail: { reason_code: "payload_too_large" } });
  assert.equal(tooLarge.text, lib.projectionReasonText("payload_too_large"));
  const invalid = lib.jevErrorInfo({ status: 422, code: "input_invalid", message: "not a valid jev_projection@1 of this run",
    detail: { error: "input_invalid", reason_code: "projection_invalid" } });
  assert.equal(invalid.reasonCode, "projection_invalid");
  assert.ok(invalid.text.startsWith(lib.projectionReasonText("projection_invalid")));
  for (const code of ["preview_mismatch", "send_id_conflict", "send_in_progress", "busy", "not_found", "dry_run"]) {
    const info = lib.jevErrorInfo({ status: 409, code, message: "m", detail: { error: code, message: "m" } });
    assert.equal(info.code, code);
    assert.equal(info.reasonCode, null);
    assert.equal(info.text, `${lib.errorCodeText(code)}: m`, code);
  }
  assert.equal(lib.jevErrorInfo({ status: 409, code: "brand_new", message: "" }).text, lib.UNKNOWN_CODE_TEXT);
  assert.deepEqual(plain(lib.jevErrorInfo(new TypeError("Failed to fetch"))),
    { status: null, code: null, reasonCode: null, text: "요청 실패: Failed to fetch" });
  assert.deepEqual(plain(lib.jevErrorInfo("weird")), { status: null, code: null, reasonCode: null, text: "요청 실패" });
});

test("projection outcome: a jev_projection handle with its summary, or the refusal reason", () => {
  const summary = { kind: "ligand", source: LIG_SET, selection_count: 2, body_bytes: 900, body_sha256: "d".repeat(64) };
  const ok = lib.jevProjectionOutcome({ ok: true, handle: { handle: PROJ, kind: "jev_projection", schema: "jev_projection@1",
    summary, preview: [] } });
  assert.deepEqual(plain(ok), { ok: true, handle: PROJ, summary });
  const wrong = lib.jevProjectionOutcome({ ok: true, handle: { handle: LIG_SET, kind: "ligand_candidate_set",
    schema: "ligand_candidate_set@1", summary: {}, preview: [] } });
  assert.deepEqual(plain(wrong), { ok: false, text: lib.NOT_A_PROJECTION_TEXT, reasonCode: null });
  const refused = lib.jevProjectionOutcome({ ok: false, error: "input_invalid", message: "unknown parameters: ['x']",
    detail: { reason_code: "unknown_field" } });
  assert.deepEqual(plain(refused), { ok: false, reasonCode: "unknown_field",
    text: `${lib.projectionReasonText("unknown_field")}: unknown parameters: ['x']` });
  assert.equal(lib.jevProjectionOutcome({ ok: false, loop_stop: { reason: "x" } }).ok, false);
});

test("API client: paths, methods and bodies of every JEV call; error bodies become typed errors", async () => {
  const calls = [];
  let answer = { status: 200, body: {} };
  const fetch = async (url, init = {}) => {
    calls.push({ url, method: init.method ?? "GET", body: init.body === undefined ? undefined : JSON.parse(init.body),
      contentType: init.headers?.["content-type"] });
    return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
  };
  const { api } = load("api", {}, { fetch });
  const args = { source: LIG_SET, candidates: [id16(1), id16(2)], filter: null };
  await api.buildJevProjection(RUN, args);
  await api.jevStatus(RUN);
  await api.jevSetConsent(RUN, true);
  await api.jevPreview(RUN, PROJ);
  await api.jevSend(RUN, { send_id: SID, projection: PROJ, body_sha256: "d".repeat(64), confirm: "send_to_jev" });
  await api.jevSends(RUN);
  await api.jevSendDetail(RUN, SID);
  await api.createJevReport(RUN, CHOICE);
  assert.deepEqual(plain(calls), [
    { url: `/api/runs/${RUN}/commands`, method: "POST", contentType: "application/json",
      body: { tool: "build_jev_projection", args, decided_by: "human", execution_mode: "human" } },
    { url: `/api/runs/${RUN}/jev/status`, method: "GET" },
    { url: `/api/runs/${RUN}/jev/consent`, method: "POST", contentType: "application/json", body: { enabled: true } },
    { url: `/api/runs/${RUN}/jev/preview`, method: "POST", contentType: "application/json", body: { projection: PROJ } },
    { url: `/api/runs/${RUN}/jev/sends`, method: "POST", contentType: "application/json",
      body: { send_id: SID, projection: PROJ, body_sha256: "d".repeat(64), confirm: "send_to_jev" } },
    { url: `/api/runs/${RUN}/jev/sends`, method: "GET" },
    { url: `/api/runs/${RUN}/jev/sends/${SID}`, method: "GET" },
    { url: `/api/runs/${RUN}/method_reports`, method: "POST", contentType: "application/json",
      body: { result_handle: CHOICE } },
  ]);
  // a JEV route error: {"detail": {error, message, ...}}
  answer = { status: 409, body: { detail: { error: "send_id_conflict", message: "this send_id was approved for another body" } } };
  const conflict = await api.jevSend(RUN, { send_id: SID, projection: PROJ, body_sha256: "d".repeat(64),
    confirm: "send_to_jev" }).catch(error => error);
  assert.equal(conflict.status, 409);
  assert.equal(conflict.code, "send_id_conflict");
  assert.equal(lib.jevErrorInfo(conflict).text, `${lib.errorCodeText("send_id_conflict")}: this send_id was approved for another body`);
  assert.equal(lib.jevAttemptAfter({ projectionHandle: PROJ, bodySha256: "d".repeat(64), sendId: SID },
    { record: false, code: lib.jevErrorInfo(conflict).code }), null);
  answer = { status: 422, body: { detail: { error: "input_invalid", message: "not a valid jev_projection@1 of this run",
    reason_code: "projection_invalid" } } };
  const invalid = await api.jevPreview(RUN, PROJ).catch(error => error);
  assert.equal(lib.jevErrorInfo(invalid).reasonCode, "projection_invalid");
  // a tool refusal on the command route: {"ok": false, error, message, detail: {reason_code}}
  answer = { status: 422, body: { ok: false, error: "input_invalid", message: "candidates are not in the candidate set",
    detail: { reason_code: "candidate_unknown", candidates: [id16(9)] } } };
  const unknown = await api.buildJevProjection(RUN, args).catch(error => error);
  assert.deepEqual(plain(lib.jevErrorInfo(unknown)), { status: 422, code: "input_invalid", reasonCode: "candidate_unknown",
    text: `${lib.projectionReasonText("candidate_unknown")}: candidates are not in the candidate set` });
  // send ids with reserved characters stay one path segment
  calls.length = 0;
  answer = { status: 200, body: {} };
  await api.jevSendDetail(RUN, "a/b?c");
  assert.equal(calls[0].url, `/api/runs/${RUN}/jev/sends/a%2Fb%3Fc`);
});

// ---- reports ----

test("report kind label and report match", () => {
  assert.equal(reportLibrary.reportKindLabel({ kind: "jev_choice", handle: "h", target_handle: CHOICE, created_seq: 9 }),
    lib.JEV_REPORT_LABEL);
  const artifact = { handle: "r", markdown_handle: "m", markdown: "", manifest: { schema: "method_report_manifest@1",
    analysis_type: "jev_choice", result_handle: CHOICE, snapshot: { event_seq: 3 } } };
  assert.equal(lib.jevReportMatches(artifact, CHOICE), true);
  assert.equal(lib.jevReportMatches(artifact, `obj://${RUN}/jev_choice/${"8".repeat(64)}`), false);
  assert.equal(lib.jevReportMatches({ ...artifact, manifest: { ...artifact.manifest, analysis_type: "sequence_ga" } }, CHOICE), false);
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

test("no screen string uses rank, recommendation, prediction or effect wording (fixed J1–J7 / U1–U3 exempt)", () => {
  // the checker itself: each forbidden term is caught, a fixed sentence line is exempt, the same words elsewhere are not
  for (const word of ["순위", "추천", "최고", "최적", "개선", "예측", "유망", "점수", "에너지", "활성", "친화도", "안정성", "ΔΔG",
    "좋은", "나쁜", "안전", "가장 높음", "winner", "best", "rank", "recommend", "Best", "RANK"])
    assert.deepEqual(plain(lib.jevForbiddenWords(`후보 c02는 ${word}`)).length, 1, word);
  for (const sentence of [...Object.values(SPEC_J), ...Object.values(SPEC_U)])
    assert.deepEqual(plain(lib.jevForbiddenWords(sentence)), [], sentence);
  assert.ok(lib.jevForbiddenWords(`${SPEC_J.J1} 이 후보가 최고다.`).length > 0);
  assert.ok(lib.jevForbiddenWords(`요약: ${SPEC_J.J5}`).length > 0);
  // negations of the plain "not a scientific value" kind need no exemption
  assert.deepEqual(plain(lib.jevForbiddenWords(lib.JEV_CONFIDENCE_LABEL)), []);

  // every exported string constant (arrays and tables included)
  const outputs = [];
  for (const [name, value] of Object.entries(lib)) {
    if (typeof value === "function" || value instanceof RegExp) continue;
    outputs.push(...strings(value).map(text => [name, text]));
  }
  // every label of every closed code, and the default
  const codes = [...lib.PREVIEW_BLOCK_REASONS, ...lib.REJECTED_REASONS, ...lib.FAILED_REASONS, ...lib.LATE_REASONS,
    ...lib.PROJECTION_REASON_CODES, ...lib.SEND_STATUSES, ...lib.SEND_ERROR_CODES, "unknown"];
  for (const fn of ["blockReasonText", "rejectedReasonText", "failedReasonText", "lateReasonText", "projectionReasonText",
    "sendStatusText", "errorCodeText"]) for (const code of codes) outputs.push([fn, lib[fn](code)]);
  // view models over the fixtures; the body and the question instructions are the exact wire text (shown verbatim,
  // never reworded), and stored limitations are the fixed J sentences
  const skip = new Set(["body", "instructions", "projectionHandle", "bodySha256", "sendId", "choiceHandle"]);
  const views = [
    lib.jevPreviewView(preview({ blocked_by: [...lib.PREVIEW_BLOCK_REASONS] })),
    lib.jevSendBlockers({ preview: preview({ blocked_by: [...lib.PREVIEW_BLOCK_REASONS] }), confirmed: false, sending: true }),
    lib.jevSendBlockers({ preview: null, confirmed: false, sending: false }),
    lib.jevResultView(detail()),
    lib.jevResultView(detail({ late: true, late_reason: "run_cancelled" }, { usage: null,
      arrival: { late: true, late_reason: "run_cancelled" }, answer: { ...choice().answer, confidence: null, probabilities: null },
      limitations: [...choice().limitations, SPEC_J.J7] })),
    lib.jevResultView(detail({}, { send: { send_id: SID_2, audit_id: AUDIT } })),
    ...lib.REJECTED_REASONS.map(code => lib.jevResultView({ ...record({ status: "rejected", reason_code: code }), choice: null,
      local_display: null })),
    ...lib.FAILED_REASONS.map(code => lib.jevResultView({ ...record({ status: "failed", reason_code: code }), choice: null,
      local_display: null })),
    lib.jevSendRows([record({ late: true, late_reason: "run_cancelled" }), record({ status: "in_progress" })]),
    lib.jevSelectionCountText(lib.emptyJevSelection("ligand", LIG_SET)),
    lib.jevProjectionArgs(lib.emptyJevSelection("mutation", MUT_SET), { ranges: {}, pains_exclude: true }),
    lib.jevCapText({ send_cap: 10, used: 1, remaining: 9 }),
    lib.egressStopText("usage_unknown"), lib.egressStopText("budget_exhausted"),
    lib.consentSwitchDisabledReason({ dry_run: true }, true),
    lib.ligandSourceOptions([{ handle: LIG_SET, created_seq: 1, valid: false, candidates: null }]),
    lib.mutationSourceOptions([{ handle: MUT_SET, created_seq: 1, valid: true, counts: { candidates: 0 } }]),
    lib.jevPanelState({ runId: null }), lib.jevPanelState({ runId: RUN, capability: null }),
    lib.jevErrorInfo({ status: 503, code: "busy", message: "" }),
    lib.jevProjectionOutcome({ ok: true, handle: { handle: LIG_SET, kind: "x", schema: "x", summary: {}, preview: [] } }),
    lib.jevStatusView(statusOf({ dry_run: true, cancelled: true, egress_stop_reason: "usage_unknown", send_in_progress: true })),
    lib.jevStatusView(statusOf()),
    lib.jevBuildBlockers({ selection: null, filter: null, building: true, sending: true }),
    lib.jevBuildBlockers({ selection: lib.emptyJevSelection("mutation", MUT_SET), filter: { ranges: {}, pains_exclude: true },
      building: false, sending: false }),
    lib.projectionSummaryText({ kind: "ligand", source: LIG_SET, selection_count: 3, body_bytes: 1234, body_sha256: "d" }),
    lib.globalScienceBadge({ runId: RUN, enabled: true }, RUN),
  ];
  for (const view of views) outputs.push(...strings(view, skip).map(text => ["view", text]));
  assert.ok(outputs.length > 150);
  for (const [name, text] of outputs) assert.deepEqual(plain(lib.jevForbiddenWords(text)), [], `${name}: ${text}`);
  // the verbatim wire text is kept even though it names what the choice is not
  assert.ok(lib.jevPreviewView(preview()).instructions.includes("not a prediction of binding"));
  // no "가장 높음" / bars / colours: the probability rows carry only alias, local reference, value and text
  assert.ok(!JSON.stringify(plain(lib.jevResultView(detail()))).includes("가장"));
});

// ---- T7 screen helpers (pure; the JevPanel screen uses them and adds no wording, guard or view model of its own) ----

test("global mark: only for the page's current run, only when that run's last known consent is on", () => {
  assert.deepEqual(plain(lib.scienceMarkFromStatus(RUN, statusOf({ enabled: true }))), { runId: RUN, enabled: true });
  assert.deepEqual(plain(lib.scienceMarkFromStatus(RUN, statusOf())), { runId: RUN, enabled: false });
  assert.deepEqual(plain(lib.scienceMarkFromStatus(RUN, { enabled: "true" })), { runId: RUN, enabled: false });
  const on = lib.scienceMarkFromStatus(RUN, statusOf({ enabled: true }));
  assert.deepEqual(plain(lib.globalScienceBadge(on, RUN)), { text: "과학 전송 허용", note: lib.SCIENCE_BADGE_NOTE });
  assert.equal(lib.globalScienceBadge(on, "run-b"), null);   // another run's mark is never shown
  assert.equal(lib.globalScienceBadge(on, null), null);
  assert.equal(lib.globalScienceBadge(null, RUN), null);
  assert.equal(lib.globalScienceBadge({ runId: RUN, enabled: false }, RUN), null);
  // the note says the mark is a separate run state, not the viewer interpretation mode
  assert.ok(lib.SCIENCE_BADGE_NOTE.includes("local_only") && lib.SCIENCE_BADGE_NOTE.includes("별개"));
});

test("status view: numbers from the server; a dry-run run shows the reason only (no cap or budget numbers)", () => {
  const view = lib.jevStatusView(statusOf({ enabled: true }));
  assert.equal(view.enabled, true);
  assert.equal(view.switchText, `${lib.CONSENT_SWITCH_LABEL}: 켜짐`);
  assert.equal(view.capText, "run당 과학 전송 10회 · 사용 4회 · 남은 6회");
  assert.equal(view.budgetText, "외부 토큰 남은 100000 / 한도 120000 · USD 남은 1.7500 / 한도 2.0000");
  assert.deepEqual(plain(view.notes), []);
  assert.equal(view.destinationText, "목적지: https://openrouter.ai/api/alpha/decisions");
  assert.ok(view.modelText.includes("typesafe/jev-1.13") && view.modelText.includes("typesafe/jev-1.13-20260917"));
  assert.equal(lib.jevStatusView(statusOf()).switchText, `${lib.CONSENT_SWITCH_LABEL}: 꺼짐`);
  assert.equal(lib.jevStatusView(statusOf({ enabled: "yes" })).enabled, false);
  const dry = lib.jevStatusView(statusOf({ dry_run: true }));
  assert.equal(dry.dryRun, true);
  assert.equal(dry.capText, null);
  assert.equal(dry.budgetText, null);
  assert.deepEqual(plain(dry.notes), [lib.DRY_RUN_NOTE]);
  assert.ok(!/\d/.test(lib.DRY_RUN_NOTE));
  const stopped = lib.jevStatusView(statusOf({ cancelled: true, egress_stop_reason: "usage_unknown", send_in_progress: true }));
  assert.deepEqual(plain(stopped.notes), [lib.blockReasonText("cancelled"), lib.egressStopText("usage_unknown"),
    lib.blockReasonText("send_in_progress")]);
  assert.equal(lib.jevStatusMatches(statusOf()), true);
  for (const bad of [null, {}, { schema: "jev_preview@1" }, "jev_status@1"]) assert.equal(lib.jevStatusMatches(bad), false);
});

test("build blockers: selection errors, building and a send in flight close 보낼 내용 만들기", () => {
  assert.deepEqual(plain(lib.jevBuildBlockers({ selection: null, filter: null, building: false, sending: false })),
    [lib.NO_SOURCE_REASON]);
  const empty = lib.emptyJevSelection("ligand", LIG_SET);
  assert.equal(lib.jevBuildBlockers({ selection: empty, filter: null, building: false, sending: false }).length, 1);
  const one = choose(empty, [ligandOption(1)]);
  assert.deepEqual(plain(lib.jevBuildBlockers({ selection: one, filter: null, building: false, sending: false })), []);
  assert.deepEqual(plain(lib.jevBuildBlockers({ selection: one, filter: null, building: true, sending: true })),
    [lib.BUILDING_REASON, lib.SEND_LOCK_REASON]);
  const mutation = choose(lib.emptyJevSelection("mutation", MUT_SET), [mutationOption(3)]);
  assert.deepEqual(plain(lib.jevBuildBlockers({ selection: mutation, filter: { ranges: {}, pains_exclude: true },
    building: false, sending: false })), ["변이 후보 집합에는 필터를 줄 수 없습니다 (filter_invalid)."]);
  assert.equal(lib.projectionSummaryText({ kind: "mutation", source: MUT_SET, selection_count: 3, body_bytes: 1234,
    body_sha256: "d".repeat(64) }), "변이 후보 3개 · 본문 1234 바이트");
});

test("confirmation is bound to the exact previewed body hash", () => {
  assert.equal(lib.jevConfirmed("d".repeat(64), preview()), true);
  assert.equal(lib.jevConfirmed("e".repeat(64), preview()), false);
  assert.equal(lib.jevConfirmed(null, preview()), false);
  assert.equal(lib.jevConfirmed("d".repeat(64), null), false);
  // a body hash change (a different preview) is not confirmed, so the send button stays closed
  const changed = preview({ body_sha256: "f".repeat(64) });
  assert.equal(lib.jevCanSend({ preview: changed, confirmed: lib.jevConfirmed("d".repeat(64), changed), sending: false }), false);
});

test("answers are applied only when they belong to the request (preview, send record, detail, list)", () => {
  assert.equal(lib.jevPreviewMatches(preview(), PROJ), true);
  assert.equal(lib.jevPreviewMatches(preview(), PROJ_2), false);
  assert.equal(lib.jevPreviewMatches({ ...preview(), schema: "jev_status@1" }, PROJ), false);
  assert.equal(lib.jevPreviewMatches({ ...preview(), body: null }, PROJ), false);
  assert.equal(lib.jevPreviewMatches(null, PROJ), false);
  const attempt = { projectionHandle: PROJ, bodySha256: `0123abcd${"a".repeat(56)}`, sendId: SID };
  assert.equal(lib.jevSendResponseMatches(record(), attempt), true);
  for (const over of [{ send_id: SID_2 }, { projection_handle: PROJ_2 }, { body_sha256: "a".repeat(64) },
    { schema: "jev_choice@1" }]) assert.equal(lib.jevSendResponseMatches(record(over), attempt), false, JSON.stringify(over));
  assert.equal(lib.jevSendResponseMatches(null, attempt), false);
  assert.equal(lib.jevDetailMatches(detail(), SID), true);
  assert.equal(lib.jevDetailMatches(detail(), SID_2), false);
  assert.equal(lib.jevDetailMatches({ ...detail(), schema: "x" }, SID), false);
  assert.equal(lib.jevSendListMatches([record(), record({ send_id: SID_2 })]), true);
  assert.equal(lib.jevSendListMatches([]), true);
  assert.equal(lib.jevSendListMatches([record(), { schema: "x" }]), false);
  assert.equal(lib.jevSendListMatches({ rows: [] }), false);
  assert.equal(lib.jevSendsPending([record(), record({ status: "in_progress" })]), true);
  assert.equal(lib.jevSendsPending([record(), record({ status: "failed" })]), false);
  assert.equal(lib.JEV_POLL_MS, 2000);
});

// ---- T7 screen: the real components compiled from source and rendered on the server (effects do not run, so no
// request is made), plus source checks of what the component can render and request ----

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
const mutationsLib = load("mutations", { "./site-annotation": siteAnnotation, "./event-model": eventModel });
const primitives = compileTsx("../src/components/primitives.tsx", { "@/lib/contracts": load("contracts") });
const noRequest = () => { throw new Error("a server render makes no request"); };
const apiStub = { api: new Proxy({}, { get: () => noRequest }), ApiError: class ApiError extends Error {} };
const ligandPanel = compileTsx("../src/components/LigandPanel.tsx", { "@/lib/api": apiStub, "@/lib/ligand": ligandLib,
  "./primitives": primitives });
const jevPanel = compileTsx("../src/components/JevPanel.tsx", { "@/lib/api": apiStub, "@/lib/jev": lib,
  "@/lib/ligand": ligandLib, "@/lib/mutations": mutationsLib, "./LigandPanel": ligandPanel, "./primitives": primitives });
const workspaceTabs = compileTsx("../src/components/WorkspaceTabs.tsx", { "@/lib/workspace-tabs": load("workspace-tabs") });
const PANEL_RUN = { run_id: "fixture-run", goal: "", context: [], dry_run: false, egress: "local_only", last_seq: 1 };
const AVAILABLE = { available: true, reason_code: null, reason: null };
const renderJev = props => renderToStaticMarkup(React.createElement(jevPanel.JevPanel,
  { run: PANEL_RUN, capability: AVAILABLE, onReportCreated: () => undefined, ...props }));
const decode = text => text.replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
  .replace(/&amp;/g, "&");
const textLines = html => decode(html.replace(/<[^>]+>/g, "\n")).split("\n").map(line => line.trim()).filter(Boolean);
const tagOf = (html, testId) => new RegExp(`<[a-z]+ [^>]*data-testid="${testId}"[^>]*>`).exec(html)?.[0] ?? "";

test("JevPanel gates: no run, capability absent or unavailable, capabilities not read: reason only, no controls", () => {
  const unavailable = { available: false, reason_code: "tool_unavailable", reason: "투영 도구가 등록되어 있지 않다." };
  for (const [props, id, state] of [[{ run: null }, "jev-no-run", "unavailable"],
    [{ capability: null }, "jev-unavailable", "unavailable"], [{ capability: unavailable }, "jev-unavailable", "unavailable"],
    [{ capability: undefined }, null, "loading"]]) {
    const html = renderJev(props);
    assert.match(tagOf(html, "jev-panel"), new RegExp(`data-jev-state="${state}"`), JSON.stringify(props));
    if (id) assert.ok(html.includes(`data-testid="${id}"`), id);
    assert.ok(!/<(input|select|button|table|a|details|pre) /.test(html), html);
    const text = textLines(html).join("\n");
    assert.ok(!/\d/.test(text), text);
    assert.deepEqual(plain(lib.jevForbiddenWords(text)), [], text);
  }
  assert.ok(textLines(renderJev({ run: null })).join(" ").includes(lib.NO_RUN_REASON));
  assert.ok(textLines(renderJev({ capability: null })).join(" ").includes(lib.CAPABILITY_REASON));
  assert.ok(renderJev({ capability: unavailable }).includes("(tool_unavailable)"));
});

test("JevPanel first render: nothing chosen or sent; build and send closed with reasons; notices U1–U3 shown", () => {
  const html = renderJev({});
  assert.match(tagOf(html, "jev-panel"), /data-jev-state="loading"/);
  assert.match(tagOf(html, "jev-panel"), /data-sending="false"/);
  // The seven areas in order.
  assert.deepEqual([...html.matchAll(/data-jev-area="([a-z]+)"/g)].map(match => match[1]),
    ["status", "source", "candidates", "build", "approval", "result", "history"]);
  // No source kind and no candidate set is chosen; no set list or candidate row exists yet.
  for (const kind of ["ligand", "mutation"]) {
    const tag = tagOf(html, `jev-kind-${kind}`);
    assert.ok(tag && !/checked/.test(tag), kind);
  }
  for (const id of ["jev-source", "jev-candidate", "jev-candidates", "jev-preview", "jev-preview-body", "jev-result-card",
    "jev-result-probabilities", "jev-consent", "jev-sends", "jev-send-record", "jev-report-done"])
    assert.ok(!html.includes(`data-testid="${id}"`), id);
  // Build and send are closed and say why; the confirmation cannot be checked before a preview.
  assert.match(tagOf(html, "jev-build"), /disabled=""/);
  assert.match(tagOf(html, "jev-send"), /disabled=""/);
  assert.match(tagOf(html, "jev-confirm"), /disabled=""/);
  assert.ok(!/checked/.test(tagOf(html, "jev-confirm")));
  assert.ok(!/data-send-id/.test(tagOf(html, "jev-send")));
  const lines = textLines(html);
  assert.ok(lines.includes(lib.NO_SOURCE_REASON) && lines.includes(lib.NO_PREVIEW_REASON));
  for (const line of [...lib.CONSENT_NOTICE, lib.JEV_SCREEN_NOTES.U1, lib.JEV_SCREEN_NOTES.U2, lib.JEV_SCREEN_NOTES.U3,
    lib.SCIENCE_BADGE_NOTE, lib.CONFIRM_CHECK_TEXT, lib.SEND_BUTTON_TEXT, lib.BUILD_BUTTON_TEXT, lib.JEV_TEXT.resultNone])
    assert.ok(lines.includes(line), line);
  // Wording, test-id prefix, no viewer markup.
  assert.deepEqual(plain(lib.jevForbiddenWords(lines.join("\n"))), []);
  const ids = [...html.matchAll(/data-testid="([^"]+)"/g)].map(match => match[1]);
  assert.ok(ids.length >= 15, String(ids.length));
  for (const id of ids) assert.ok(id.startsWith("jev-"), id);
  assert.ok(!/molstar|<canvas/i.test(html));
});

test("JevPanel source: wording, test ids, reads on mount only, one call site per write, the send never aborted", () => {
  const file = path.join(__dirname, "../src/components/JevPanel.tsx");
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
  // Every literal the component can render passes the M24 wording check; the visible text is the module's.
  assert.ok(texts.length > 60, String(texts.length));
  for (const text of texts) assert.deepEqual(plain(lib.jevForbiddenWords(text)), [], text);
  assert.ok(!/[가-힣]/.test(texts.filter(text => !text.startsWith("JEV")).join("")),
    "Korean screen text comes from lib/jev.ts, not from component literals");
  assert.ok(!/dangerouslySetInnerHTML|innerHTML|localStorage|sessionStorage/.test(source));
  // Every test id carries the area prefix (the ErrorLine / Pager pass-through and the M17 FilterForm prefix aside).
  for (const id of ids) assert.ok(id === "<testId>" || id === "jev" || id.startsWith("jev-"), id);
  assert.ok(ids.length > 40, String(ids.length));
  // Effects (mount = entering the tab, polling, candidate pages) only read: no build, preview, send, consent or report,
  // and nothing is chosen, opened or checked by itself.
  assert.ok(effects.length >= 5, String(effects.length));
  const reads = new Set(["jevStatus", "jevSends", "ligandCandidateRows", "mutationCandidates"]);
  for (const body of effects) {
    for (const match of body.matchAll(/api\.(\w+)\(/g)) assert.ok(reads.has(match[1]), match[1]);
    assert.ok(!/\b(send|buildProjection|changeConsent|makeReport|readPreview|openSend|chooseKind|chooseSource|toggle|setSelection|setKind|setConfirmedFor)\(/
      .test(body), body);
  }
  // Each writing (or preview) request has one call site.
  for (const name of ["jevSend", "jevSetConsent", "buildJevProjection", "createJevReport", "jevPreview", "jevSendDetail"])
    assert.equal([...source.matchAll(new RegExp(`api\\.${name}\\(`, "g"))].length, 1, name);
  // The send is the person's click only, uses the one-attempt send id rule and is never aborted by leaving the tab.
  assert.equal([...source.matchAll(/onClick=\{\(\) => void send\(\)\}/g)].length, 1);
  assert.equal([...source.matchAll(/(?<!function )\bsend\(\)/g)].length, 1);   // its only call site is that click
  assert.ok(source.includes("const record = await api.jevSend(runId, jevSendRequest(attempt));"));
  assert.ok(/const attempt = jevSendAttempt\(attemptRef\.current, previewValue\);/.test(source));
  assert.ok(/jevAttemptAfter\(attempt, \{ record: true \}\)/.test(source) &&
    /jevAttemptAfter\(attempt, \{ record: false, code: info\.code \}\)/.test(source));
  assert.ok(/if \(sendingRef\.current \|\| previewValue === null \|\| sendBlockers\.length\) return;/.test(source));
  assert.ok(/disabled=\{sendBlockers\.length > 0\}/.test(source));
  assert.ok(/const confirmed = jevConfirmed\(confirmedFor, previewValue\);/.test(source));
  assert.equal([...source.matchAll(/onClick=\{\(\) => void buildProjection\(\)\}/g)].length, 1);
  assert.equal([...source.matchAll(/void changeConsent\(event\.target\.checked\)/g)].length, 1);
  // Values are shown through the view models only: no sorting, arithmetic or bars on probabilities or confidence.
  assert.ok(!/\.sort\(|toFixed\(|<progress|<meter|width:/.test(source));
  assert.deepEqual([...source.matchAll(/Math\.\w+/g)].map(match => match[0]), ["Math.max"]);   // the pager's offset only
  assert.ok(source.includes("onClick={() => onPage(Math.max(0, offset - limit))}"));
  assert.ok(/jevResultView\(detail\)/.test(source) && /jevPreviewView\(preview\)/.test(source) &&
    /jevSendRows\(sends\.value\)/.test(source));
  // The exact body and the probabilities are collapsed (no `open`); the body is shown verbatim from the preview.
  assert.ok(!/<details[^>]*\bopen\b/.test(source));
  assert.ok(source.includes('<pre className="mw-jev-body" data-testid="jev-preview-body">{view.body}</pre>'));
  // Late answers: every apply is behind the per-area run + handle + request number check.
  assert.ok(/jevResponseCurrent\(captured, \{ runId, handle: keyOf\(area\), seq: seqs\.current\[area\] \}\)/.test(source));
  // No viewer, saved view, bridge, or another tab's area.
  assert.ok(!/MolstarViewer|molstar|viewer-agent|saved-scene|captureScene|request_science/.test(source));
  // The M17 filter form is reused with its own prefix.
  assert.ok(/<FilterForm idPrefix="jev"/.test(source) && source.includes('import { FilterForm } from "./LigandPanel";'));
});

test("global line: the science mark sits outside .mw-app-run and only when given; the JEV area is between numbering and reports", () => {
  const render = props => renderToStaticMarkup(React.createElement(workspaceTabs.WorkspaceTabs, { active: "knowledge",
    onSelect: () => undefined, runId: "run_123", budget: null, structure: React.createElement("div", null, "S"),
    numbering: React.createElement("div", null, "N"), jev: React.createElement("div", null, "J"),
    reports: React.createElement("div", null, "R"), ...props }));
  const withMark = render({ scienceBadge: lib.globalScienceBadge({ runId: "run_123", enabled: true }, "run_123") });
  const run = /<span class="mw-mono mw-app-run"[^>]*>([^<]*)<\/span>/.exec(withMark);
  assert.equal(run?.[1], "run_123");                       // the run element's text is the run id only
  const mark = /<span class="mw-badge mw-app-science" data-science-consent="on" title="([^"]*)">([^<]*)<\/span>/
    .exec(withMark);
  assert.ok(mark, withMark);
  assert.equal(decode(mark[1]), lib.SCIENCE_BADGE_NOTE);
  assert.equal(decode(mark[2]).trim(), "과학 전송 허용");
  assert.ok(withMark.indexOf("mw-app-run") < withMark.indexOf("mw-app-science"));
  for (const off of [null, lib.globalScienceBadge({ runId: "run_123", enabled: false }, "run_123"),
    lib.globalScienceBadge({ runId: "run_other", enabled: true }, "run_123")])
    assert.ok(!render({ scienceBadge: off }).includes("mw-app-science"));
  assert.ok(!render({}).includes("mw-app-science"));
  const order = ["mw-app-numbering", "mw-app-jev", "mw-app-reports"].map(name => withMark.indexOf(`class="${name}"`));
  assert.ok(order.every(index => index > 0) && order[0] < order[1] && order[1] < order[2], order.join());
  // Other tabs never render the JEV area.
  for (const active of ["structure", "protein", "ligand"]) assert.ok(!render({ active }).includes("mw-app-jev"), active);
});

test("page: JevPanel keyed by run in the knowledge tab; report reload and the global mark guarded by the run", () => {
  const page = fs.readFileSync(path.join(__dirname, "../app/page.tsx"), "utf8");
  assert.ok(page.includes('import { JevPanel } from "@/components/JevPanel";'));
  assert.ok(page.includes("jev={<JevPanel key={`jev-${run?.run_id ?? \"none\"}`} run={run}"));
  assert.ok(/capability=\{capabilities \? capabilities\.methods\?\.jev_choice \?\? null : undefined\}/.test(page));
  assert.ok(/onStatus=\{\(statusRunId, status\) => \{ if \(hostRequestAccepted\(\{ runId: statusRunId \}, analysisHostRef\.current\)\)\n\s+setScienceMark\(scienceMarkFromStatus\(statusRunId, status\)\); \}\}/.test(page));
  assert.ok(page.includes("scienceBadge={globalScienceBadge(scienceMark, runId ?? null)}"));
  // The run-change read is one GET of the status (no consent write, no polling).
  const start = page.indexOf("// M24 global mark");
  const effect = page.slice(start, page.indexOf("}, [runId]);", start));
  assert.ok(start > 0 && /api\.jevStatus\(runId, controller\.signal\)/.test(effect), effect);
  assert.ok(!/jevSetConsent|setInterval|jevSend\b/.test(effect));
  assert.equal([...page.matchAll(/api\.jev\w+\(/g)].length, 1);
  // The tab shell and the shared component surface stay as they were; the panel is imported by path.
  const index = fs.readFileSync(path.join(__dirname, "../src/components/index.ts"), "utf8");
  assert.ok(!/Panel/.test(index));
});
