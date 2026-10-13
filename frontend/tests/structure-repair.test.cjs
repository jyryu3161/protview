// M29 T10 screen: the pure module of the "구조 보완" area (lib/structure-repair.ts) and the M29 marks on other screens.
// Closed sets, limits and fixed sentences are read from backend/mw/structure_repair_constants.py itself; the panel is
// compiled from source and rendered on the server (effects do not run, so no request is made).
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

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
function compileTsx(relativePath, dependencies) {
  const source = fs.readFileSync(path.join(__dirname, relativePath), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const moduleObject = { exports: {} };
  vm.runInNewContext(compiled, { module: moduleObject, exports: moduleObject.exports, URLSearchParams, AbortSignal,
    AbortController, require: name => dependencies[name] ?? require(name) });
  return moduleObject.exports;
}
const lib = load("structure-repair");
const eventModel = load("event-model");
const numbering = load("numbering");
const siteAnnotation = load("site-annotation", { "./comparison": load("comparison"), "./numbering": numbering,
  "./event-model": eventModel });
const mutations = load("mutations", { "./event-model": eventModel, "./site-annotation": siteAnnotation });
const reportLibrary = load("report-library");
const plain = value => JSON.parse(JSON.stringify(value));
const ROOT = path.join(__dirname, "../..");
const read = relative => fs.readFileSync(path.join(ROOT, relative), "utf8");
const PANEL_FILE = "frontend/src/components/StructureRepairPanel.tsx";

// ---- the backend constants file, read as text (no Python run) ----
const PY = read("backend/mw/structure_repair_constants.py");
function pyAssignment(name) {
  const start = PY.search(new RegExp(`^${name} = `, "m"));
  assert.ok(start >= 0, `backend constant ${name} not found`);
  const rest = PY.slice(start + `${name} = `.length);
  if (rest.startsWith("(")) {
    let depth = 0, end = 0;
    for (; end < rest.length; end += 1) {
      if (rest[end] === "(") depth += 1;
      if (rest[end] === ")") { depth -= 1; if (!depth) break; }
    }
    return rest.slice(1, end);
  }
  return rest.slice(0, rest.indexOf("\n"));
}
const pyString = name => [...pyAssignment(name).replace(/#.*$/gm, "").matchAll(/"([^"]*)"/g)].map(match => match[1]).join("");
const pyTuple = name => [...pyAssignment(name).matchAll(/"([^"]*)"/g)].map(match => match[1]);
const pyNumber = name => Number(pyAssignment(name).replace(/#.*/, "").trim().replace(/_/g, ""));

test("fixed sentences RP1–RP6, SO1–SO3 and JW1 are the backend's, verbatim and in the backend order", () => {
  for (const name of ["RP1", "RP2", "RP3", "RP4", "RP5", "RP6", "SO1", "SO2", "SO3", "JW1"])
    assert.equal(lib[name], pyString(name), name);
  const order = pyAssignment("LIMITATION_ORDER").split(",").map(text => text.trim()).filter(Boolean);
  assert.deepEqual(order, ["RP1", "RP2", "RP3", "RP4", "RP5", "RP6"]);
  assert.deepEqual(plain(lib.LIMITATION_ORDER), order.map(name => pyString(name)));
  assert.deepEqual(plain(lib.REPAIR_FIXED_LINES), [...order, "SO1", "SO2", "SO3", "JW1"].map(name => pyString(name)));
});

test("names, closed sets and limits equal the backend constants", () => {
  assert.equal(lib.REPAIR_TOOL, pyString("TOOL"));
  assert.equal(lib.REPAIR_PROTOCOL, pyString("PROTOCOL"));
  assert.equal(lib.REPAIR_KIND, pyString("KIND"));
  assert.equal(lib.REPAIR_SCHEMA, pyString("SCHEMA"));
  assert.equal(lib.REPAIR_EVENT, pyString("EVENT_PUBLISHED"));
  assert.equal(lib.REPAIR_PREFLIGHT_SCHEMA, pyString("PREFLIGHT_SCHEMA"));
  assert.equal(lib.REPAIR_POLICY, pyString("REPAIR_POLICY"));
  assert.equal(lib.REPAIR_REPORT_TYPE, pyString("REPORT_ANALYSIS_TYPE"));
  assert.equal(lib.REPAIR_REPORT_NAME, pyString("REPORT_LIST_NAME"));
  assert.equal(lib.REPAIRED_NOT_ACCEPTED, pyString("REPAIRED_NOT_ACCEPTED"));
  assert.equal(lib.REPAIR_TIMEOUT_DEFAULT_S, pyNumber("TIMEOUT_DEFAULT_S"));
  assert.equal(lib.REPAIR_TIMEOUT_MAX_S, pyNumber("TIMEOUT_MAX_S"));
  assert.equal(lib.MAX_GAP_RESIDUES, pyNumber("MAX_GAP_RESIDUES"));
  assert.equal(lib.ATOM_PAGE_DEFAULT, pyNumber("ATOM_PAGE_DEFAULT"));
  assert.deepEqual(plain(lib.ATOM_PAGE_RANGE), pyAssignment("ATOM_PAGE_RANGE").split(",").map(Number));
  for (const [jsName, pyName] of [["REPAIR_CLASSES", "REPAIR_CLASSES"], ["REFUSAL_REASONS", "REFUSAL_REASONS"],
    ["ADMISSION_REASON_CODES", "ADMISSION_REASON_CODES"], ["UNAVAILABLE_REASON_CODES", "UNAVAILABLE_REASON_CODES"],
    ["FAILURE_REASON_CODES", "FAILURE_REASON_CODES"], ["COLLISION_CLASSES", "COLLISION_CLASSES"],
    ["ADDED_ATOM_ORIGINS", "ADDED_ATOM_ORIGINS"]])
    assert.deepEqual(plain(lib[jsName]), pyTuple(pyName), jsName);
  // The api submits exactly the protocol, the two arguments and the default timeout.
  const api = read("frontend/src/lib/api.ts");
  assert.ok(api.includes('jsonPost({ protocol_id: "pdbfixer_repair_v1",\n      args: { structure, repair_policy: "complete_missing_atoms_v1" }, timeout_s: timeoutS })'));
});

test("every closed code reads \"한국어 (code)\"; an unknown code stays as it is; class and collision labels cover the sets", () => {
  for (const code of [...lib.REFUSAL_REASONS, ...lib.ADMISSION_REASON_CODES, ...lib.UNAVAILABLE_REASON_CODES,
    ...lib.FAILURE_REASON_CODES, lib.REPAIRED_NOT_ACCEPTED, "worker_version_invalid", "method_evidence_invalid"]) {
    const text = lib.repairReasonText(code);
    assert.ok(text.endsWith(` (${code})`) && /[가-힣]/.test(text.slice(0, -code.length - 3)), `${code}: ${text}`);
  }
  assert.equal(lib.repairReasonText("not_a_code"), "not_a_code");
  assert.deepEqual(Object.keys(lib.CLASS_LABEL), plain(lib.REPAIR_CLASSES));
  assert.deepEqual(Object.keys(lib.COLLISION_LABEL), plain(lib.COLLISION_CLASSES));
  assert.deepEqual(Object.keys(lib.ORIGIN_LABEL), plain(lib.ADDED_ATOM_ORIGINS));
});

// ---- five states, late responses, the open request ----

test("five states: unavailable (no run / no method / reason with code), loading, failed, empty, ready", () => {
  const ok = { available: true, reason_code: null, reason: null };
  assert.equal(lib.repairPanelState({ runId: null, capability: ok }).state, "unavailable");
  assert.deepEqual(plain(lib.repairPanelState({ runId: "r", capability: undefined })), { state: "loading" });
  assert.equal(lib.repairPanelState({ runId: "r", capability: null }).state, "unavailable");
  const off = lib.repairPanelState({ runId: "r",
    capability: { available: false, reason_code: "pdbfixer_unavailable", reason: "PDBFixer is not installed" } });
  assert.deepEqual(plain(off), { state: "unavailable", reason: "PDBFixer is not installed (pdbfixer_unavailable)" });
  assert.equal(lib.repairPanelState({ runId: "r", capability: ok, error: "읽기 실패", structures: [], repairs: [] }).state,
    "failed");
  assert.equal(lib.repairPanelState({ runId: "r", capability: ok, loading: true, structures: [], repairs: [] }).state,
    "loading");
  assert.equal(lib.repairPanelState({ runId: "r", capability: ok, structures: undefined, repairs: [] }).state, "loading");
  const noStructure = lib.repairPanelState({ runId: "r", capability: ok, structures: [], repairs: [] });
  const noRecord = lib.repairPanelState({ runId: "r", capability: ok, structures: [{}], repairs: [] });
  assert.equal(noStructure.state, "empty");
  assert.equal(noRecord.state, "empty");
  assert.notEqual(noStructure.message, noRecord.message);
  assert.deepEqual(plain(lib.repairPanelState({ runId: "r", capability: ok, structures: [{}], repairs: [{}] })),
    { state: "ready" });
  assert.deepEqual(Object.keys(lib.STATE_TEXT), ["loading", "ready", "empty", "failed", "unavailable"]);
});

test("late responses: applied only with the same run, structure/record handle and the area's request number", () => {
  const live = { runId: "r1", handle: "obj://r1/prepared_structure/a", seq: 3 };
  assert.equal(lib.repairResponseCurrent({ ...live }, live), true);
  for (const changed of [{ runId: "r2" }, { handle: "obj://r1/prepared_structure/b" }, { handle: null }, { seq: 4 }])
    assert.equal(lib.repairResponseCurrent({ ...live, ...changed }, live), false, JSON.stringify(changed));
  assert.equal(lib.repairResponseCurrent({ ...live, runId: null }, { ...live, runId: null }), false);
  assert.ok(lib.REPAIR_AREAS.includes("preflight") && lib.REPAIR_AREAS.includes("detail") &&
    lib.REPAIR_AREAS.includes("atoms") && lib.REPAIR_AREAS.includes("report"));
  // A saved report is announced while the run is the same even when its inline answer is dropped.
  assert.equal(lib.repairReportSavedForRun({ runId: "r1", handle: "x", seq: 1 }, "r1"), true);
  assert.equal(lib.repairReportSavedForRun({ runId: "r1", handle: "x", seq: 1 }, "r2"), false);
  // "보완 기록 열기" from another area: this run's, once (a handled request is never replayed).
  const request = { runId: "r1", record: "obj://r1/structure_repair/x", seq: 2, handled: false };
  assert.equal(lib.repairOpenPending(request, "r1"), request.record);
  assert.equal(lib.repairOpenPending({ ...request, handled: true }, "r1"), null);
  assert.equal(lib.repairOpenPending(request, "r2"), null);
  assert.equal(lib.repairOpenPending(null, "r1"), null);
});

// ---- repaired structures in the event log; the lists that drop them; the M20 choice that adds them ----

const PREPARED_A = "obj://r/prepared_structure/a", PREPARED_B = "obj://r/prepared_structure/b";
const REPAIRED = "obj://r/prepared_structure/fixed", RECORD = "obj://r/structure_repair/rec";
const EVENTS = [
  { seq: 1, type: "object_created", handle: "obj://r/structure/s", kind: "structure" },
  { seq: 2, type: "object_created", handle: PREPARED_A, kind: "prepared_structure" },
  { seq: 3, type: "tool_called", tool: "prepare_structure", key: "k", call_id: "c1", args: { structure: "obj://r/structure/s" },
    decided_by: "human", attempt: 1, version: "1" },
  { seq: 4, type: "tool_succeeded", tool: "prepare_structure", key: "k", call_id: "c1",
    output: { handle: PREPARED_A, kind: "prepared_structure" } },
  { seq: 5, type: "job_submitted", job: { job_id: "job_1", protocol_id: "pdbfixer_repair_v1",
    parameters: { structure: PREPARED_A, repair_policy: "complete_missing_atoms_v1" } } },
  { seq: 6, type: "job_submitted", job: { job_id: "job_2", protocol_id: "openmm_mutation_model_v1",
    parameters: { structure: PREPARED_B } } },
  { seq: 7, type: "object_created", handle: RECORD, kind: "structure_repair" },
  { seq: 8, type: "object_created", handle: REPAIRED, kind: "prepared_structure" },
  { seq: 9, type: "structure_repair_published", job_id: "job_1", attempt_id: "a", record: RECORD,
    prepared_structure: REPAIRED, coordinates: "obj://r/prepared_coordinates/c", manifest: "obj://r/preparation_manifest/m" },
];

test("repaired structures come from the publication event; their source from the job's submitted structure", () => {
  assert.deepEqual(plain(lib.repairLinks(EVENTS)), [{ structure: REPAIRED, record: RECORD, source: PREPARED_A, seq: 9 }]);
  assert.deepEqual([...lib.repairedStructureHandles(EVENTS)], [REPAIRED]);
  // Without the submission event the source is unknown (null), never guessed.
  assert.equal(lib.repairLinks(EVENTS.filter(event => event.type !== "job_submitted"))[0].source, null);
  assert.deepEqual(plain(lib.repairLinks(EVENTS.slice(0, 8))), []);   // objects without publication are not repaired
  // Lists that drop them: the viewer / comparison / workflow / pocket options, chemistry, numbering and reaction.
  const options = [{ handle: "obj://r/structure/s", kind: "structure" }, { handle: PREPARED_A, kind: "prepared_structure" },
    { handle: REPAIRED, kind: "prepared_structure" }];
  assert.deepEqual(plain(lib.withoutRepaired(options, lib.repairedStructureHandles(EVENTS))).map(item => item.handle),
    ["obj://r/structure/s", PREPARED_A]);
  assert.deepEqual(plain(numbering.numberingStructures(EVENTS)).map(item => item.handle),
    ["obj://r/structure/s", PREPARED_A]);
  // The repair input: prepared structures only (a repaired structure is never repaired again).
  const prepared = mutations.preparedStructures(EVENTS);
  assert.deepEqual(plain(prepared), [{ handle: PREPARED_A, seq: 4 }]);
  assert.deepEqual(plain(lib.repairInputStructures([...prepared, { handle: REPAIRED, seq: 9 }], EVENTS)), [{ handle: PREPARED_A, seq: 4 }]);
  // M20 adds the repaired structure with its link (badge "보완 구조"), in event order.
  assert.deepEqual(plain(lib.mutationStructureRows(prepared, lib.repairLinks(EVENTS))), [
    { handle: PREPARED_A, seq: 4, repair: null },
    { handle: REPAIRED, seq: 9, repair: { structure: REPAIRED, record: RECORD, source: PREPARED_A, seq: 9 } }]);
  // Reference results: the repaired structure and its original prepared structure; any other structure itself only.
  assert.deepEqual(plain(lib.referenceStructures(REPAIRED, lib.repairLinks(EVENTS))), [REPAIRED, PREPARED_A]);
  assert.deepEqual(plain(lib.referenceStructures(PREPARED_A, lib.repairLinks(EVENTS))), [PREPARED_A]);
  assert.deepEqual(plain(lib.referenceStructures(null, lib.repairLinks(EVENTS))), []);
});

test("page, chemistry and the protein tab: viewer options drop repaired structures; the area is mounted first", () => {
  const page = read("frontend/app/page.tsx");
  const options = page.slice(page.indexOf("const sourceOptions = "), page.indexOf("const measurementOptions"));
  assert.ok(/^const sourceOptions = withoutRepaired\(/.test(options) && options.includes("repairedStructureHandles(events))"),
    options);
  assert.ok(page.includes('import { StructureRepairPanel } from "@/components/StructureRepairPanel";'));
  const protein = page.indexOf("protein={<>"), repair = page.indexOf("<StructureRepairPanel "),
    m20 = page.indexOf("<MutationPanel "), ligand = page.indexOf("ligand={<>");
  assert.ok(protein > 0 && protein < repair && repair < m20 && m20 < ligand, [protein, repair, m20, ligand].join());
  assert.ok(/capability=\{capabilities \? capabilities\.methods\?\.structure_repair \?\? null : undefined\}/.test(page));
  // The M24 element keeps its shape (the M25 mark stays last).
  assert.ok(page.includes("onOpenRepairRecord={openRepairRecord}\n      sendHistoryMark={loopSendHistoryMark} />}"));
  const chemistry = read("frontend/src/components/ChemicalWorkspace.tsx");
  assert.ok(/const sources = useMemo\(\(\) => withoutRepaired\(/.test(chemistry) &&
    chemistry.includes("repairedStructureHandles(events)"));
  // No viewer, saved view or bridge in the repair area; the tab shell is unchanged.
  const panel = read(PANEL_FILE);
  assert.ok(!/MolstarViewer|molstar|viewer-agent|saved-scene|captureScene|restoreScene/.test(panel));
  assert.ok(!/repair|Repair/.test(read("frontend/src/components/WorkspaceTabs.tsx")));
});

// ---- M20: reference results of the original structure, modeled-basis and not-checked marks ----

test("M20 reference results: a repaired structure also offers its original structure's results (spec 5.3)", () => {
  const refs = [REPAIRED, PREPARED_A];
  const pocketRows = [{ handle: "p1", source_handle: PREPARED_A, null_result: false },
    { handle: "p2", source_handle: PREPARED_B, null_result: false }, { handle: "p3", source_handle: PREPARED_A, null_result: true },
    { handle: "p4", source_handle: null, null_result: false }];
  assert.deepEqual(mutations.pocketSetsForStructure(pocketRows, refs).map(row => row.handle), ["p1"]);
  assert.deepEqual(mutations.pocketSetsForStructure(pocketRows, REPAIRED).map(row => row.handle), []);
  assert.deepEqual(mutations.pocketSetsForStructure(pocketRows, PREPARED_A).map(row => row.handle), ["p1"]);
  assert.deepEqual(mutations.pocketSetsForStructure(pocketRows, null), []);
  const maps = [{ handle: "m1", structure: PREPARED_A, created_seq: 3 }, { handle: "m2", structure: PREPARED_B, created_seq: 4 }];
  const annotations = [{ handle: "a1", structure: PREPARED_A, numbering_map: "m1", created_seq: 5 }];
  const reactions = [{ handle: "k1", structure_handle: PREPARED_A }];
  assert.deepEqual(mutations.mapsForStructure(maps, refs).map(row => row.handle), ["m1"]);
  assert.deepEqual(mutations.annotationsForStructure(annotations, refs).map(row => row.handle), ["a1"]);
  assert.deepEqual(mutations.catalyticAnnotationsForStructure(reactions, refs).map(row => row.handle), ["k1"]);
  // The pre-selection runs over both structures for a repaired structure (never submitted by itself).
  const draft = mutations.draftForStructure(mutations.initialMutationDraft(null), REPAIRED, annotations, maps, reactions);
  assert.equal(draft.annotation, null);
  const picked = mutations.draftForReferences(draft, refs, annotations, maps, reactions);
  assert.deepEqual([picked.annotation, picked.numberingMap, picked.catalyticAnnotation], ["a1", "m1", "k1"]);
  assert.equal(mutations.draftForReferences(draft, [REPAIRED], annotations, maps, reactions), draft);
  // The request accepts the original structure's results only with the reference list (the server checks again).
  const base = { ...picked, userOn: true, residues: [{ model_number: 1, chain_auth: "A", chain_label: "A", seq_auth: 10,
    seq_label: 10, icode: "", resname: "LYS" }] };
  const options = { pocketSets: pocketRows, maps, annotations, ligands: [], reactionResults: reactions };
  assert.equal(mutations.mutationRequestArgs(base, { ...options, referenceStructures: refs }).ok, true);
  const refused = mutations.mutationRequestArgs(base, options);
  assert.equal(refused.ok, false);
  assert.ok(refused.errors.some(text => text.includes("번호 대응")) && refused.errors.some(text => text.includes("참조 주석")));
});

test("M20 position marks: modeled basis and \"검사 안 함(모델링 잔기)\" only where the server says so", () => {
  assert.equal(lib.MODELED_NOT_CHECKED_TEXT, "검사 안 함(모델링 잔기)");
  const row = { modeled_basis: true, reference_not_checked: ["numbering", "klifs_sites"] };
  assert.equal(lib.referenceNotCheckedText(row, "numbering"), lib.MODELED_NOT_CHECKED_TEXT);
  assert.equal(lib.referenceNotCheckedText(row, "klifs_sites"), lib.MODELED_NOT_CHECKED_TEXT);
  assert.equal(lib.referenceNotCheckedText(row, "catalytic"), null);   // the stored value is shown
  assert.equal(lib.referenceNotCheckedText({}, "numbering"), null);
  assert.equal(lib.modeledBasisText({ modeled_basis: true }), "모델링 원자·잔기 포함");
  assert.equal(lib.modeledBasisText({ modeled_basis: false }), "관측 원자만");
  assert.equal(lib.modeledBasisText({}), null);
  // The stored "검사함, 해당 없음" text differs from the not-checked mark.
  assert.notEqual(mutations.klifsSitesText([]), lib.MODELED_NOT_CHECKED_TEXT);
  // The M20 table cells take the mark first, the stored value otherwise; the column exists only on a repaired set.
  const panel = read("frontend/src/components/MutationPanel.tsx");
  assert.ok(panel.includes('{referenceNotCheckedText(row, "numbering") ?? numberingText(row.numbering)}'));
  assert.ok(panel.includes('{referenceNotCheckedText(row, "klifs_sites") ?? klifsSitesText(row.protection.klifs_sites)}'));
  assert.ok(/referenceNotCheckedText\(row, "catalytic"\) \?\?\s+catalyticProtectionText\(row\.protection\)/.test(panel));
  assert.ok(panel.includes("{repaired && <td data-cell=\"modeled-basis\">{modeledBasisText(row) ?? NULL_TEXT}</td>}"));
  assert.ok(panel.includes('<RepairOriginNote origin={opened.structure_origin} testId="mutation-repair-origin"'));
  assert.ok(panel.includes("opened.repair_handoff.statements.map(item => <p key={item.id} data-statement={item.id}>{item.text}</p>)"));
});

// ---- preflight, job and record views (server values as they are) ----

const RES = (seq, resname = "LYS", chain = "A") => ({ model_number: 1, chain_auth: chain, chain_label: chain, seq_auth: seq,
  seq_label: seq + 1, icode: "", resname });
const PREFLIGHT = { schema: "structure_repair_preflight@1", starts_job: false, capability: {}, structure: PREPARED_A,
  repairable: true, blockers: [],
  defects: { chain_parts: [{ chain_auth: "A", parts: 3 }], side_chain_residues: [{ residue: RES(100), missing_atoms: ["CD", "CE", "NZ"] }],
    terminal_oxt: [{ residue: RES(300, "GLY") }],
    gaps: [{ chain_auth: "A", after_residue: RES(272, "SER"), before_residue: RES(286, "ALA"), length: 2,
      residues: [RES(273, "GLY"), RES(274, "PRO")] }], nonstandard: [] },
  expected_added_residues: 2, expected_added_heavy_atoms: 15, budget: { expensive_calls: { limit: 2, used: 2 } },
  remaining: { expensive_calls: 0 }, shortfall: { expensive_calls: 1 },
  admission: { admitted: true, error: null, reason_code: null, message: null, detail: null },
  statements: [lib.RP1, lib.RP2, lib.RP3, lib.RP6] };

test("preflight view: defect lists as given, blockers \"한국어 (code)\", admission, budget shortfall as a note", () => {
  assert.equal(lib.preflightMatches(PREFLIGHT, PREPARED_A), true);
  assert.equal(lib.preflightMatches(PREFLIGHT, PREPARED_B), false);
  assert.equal(lib.preflightMatches({ ...PREFLIGHT, starts_job: true }, PREPARED_A), false);
  const view = plain(lib.preflightView(PREFLIGHT));
  assert.equal(view.admitted, true);
  assert.deepEqual(view.chainParts, [{ chain: "A", parts: "3" }]);
  assert.deepEqual(view.sideChain.map(row => [row.residue, row.missing]), [["A/100/LYS", "CD, CE, NZ"]]);
  assert.equal(view.sideChain[0].fields, "모델 1 · auth A/100 · icode \"\" · label A/101 · LYS");
  assert.deepEqual(view.gaps, [{ chain: "A", after: "A/272/SER", before: "A/286/ALA", length: "2", residues: "A/273/GLY, A/274/PRO" }]);
  assert.equal(view.expectedText, "더할 잔기 2개 · 더할 중원자 15개 (사전 검사 값)");
  assert.deepEqual(view.statements, [lib.RP1, lib.RP2, lib.RP3, lib.RP6]);
  assert.match(view.shortfallText, /1단위 부족/);
  const refused = plain(lib.preflightView({ ...PREFLIGHT, repairable: false,
    blockers: [{ reason_code: "gap_too_long", residue: RES(320), chain_auth: "A",
      detail: { after_residue: RES(292), length: 27, max_gap_residues: 20 } }, { reason_code: "nothing_to_repair", detail: {} }],
    admission: { admitted: false, error: "input_invalid", reason_code: "gap_too_long", message: "repair not possible",
      detail: {} } }));
  assert.equal(refused.admitted, false);
  assert.equal(refused.admissionText, `입장 거절: ${lib.repairReasonText("gap_too_long")} · repair not possible`);
  assert.deepEqual(refused.blockers.map(item => [item.reason, item.where, item.detail]), [
    [lib.repairReasonText("gap_too_long"), "A/320/LYS", "after_residue: A/292/LYS · length: 27 · max_gap_residues: 20"],
    [lib.repairReasonText("nothing_to_repair"), "—", ""]]);
  // An environment without the template: no defect numbers, "—" with the reason.
  const blind = plain(lib.preflightView({ ...PREFLIGHT, repairable: null, defects: null, expected_added_residues: null,
    expected_added_heavy_atoms: null, admission: { admitted: false, error: "precondition", reason_code: "openmm_unavailable",
      message: "m", detail: null } }));
  assert.equal(blind.expectedText, "— (결함 분석 없음)");
  assert.equal(blind.repairableText, "— (결함 분석 없음)");
  assert.deepEqual([blind.chainParts, blind.sideChain, blind.oxt, blind.gaps, blind.nonstandard], [[], [], [], [], []]);
  assert.equal(blind.analysed, false);
  assert.equal(blind.blockersHeading, "걸림돌 (— (결함 분석 없음))");
  assert.equal(view.analysed, true);
  assert.equal(view.blockersHeading, "걸림돌 (0개)");
});

test("job: the literal policy only after the confirmation; blocked reasons in order; approval, re-attach, result", () => {
  assert.deepEqual(plain(lib.repairJobBody(PREPARED_A, false)), { ok: false,
    errors: ["보완 정책 확인(complete_missing_atoms_v1)을 체크하세요."] });
  assert.deepEqual(plain(lib.repairJobBody(PREPARED_A, true)), { ok: true, body: { protocol_id: "pdbfixer_repair_v1",
    args: { structure: PREPARED_A, repair_policy: "complete_missing_atoms_v1" }, timeout_s: 120 } });
  assert.equal(lib.repairJobBody(null, true).ok, false);
  const ok = { available: true, reason_code: null, reason: null };
  const blocked = over => lib.repairSubmitBlockedReason({ capability: ok, busy: false, activeJob: null, structure: PREPARED_A,
    preflight: PREFLIGHT, confirmed: true, ...over });
  assert.equal(blocked({}), null);
  assert.match(blocked({ capability: { available: false, reason_code: "openmm_unavailable", reason: "없음" } }), /openmm_unavailable/);
  assert.match(blocked({ busy: true }), /처리하는 중/);
  assert.match(blocked({ activeJob: { status: "running" } }), /한 번에 한 작업/);
  assert.equal(blocked({ activeJob: { status: "done" } }), null);
  assert.match(blocked({ structure: null }), /구조를 고르세요/);
  assert.match(blocked({ preflight: null }), /사전 검사 결과를 읽은 뒤/);
  assert.match(blocked({ preflight: { ...PREFLIGHT, structure: PREPARED_B } }), /사전 검사 결과를 읽은 뒤/);
  assert.match(blocked({ preflight: { ...PREFLIGHT, admission: { admitted: false, error: "input_invalid",
    reason_code: "already_repaired", message: "", detail: null } } }), /already_repaired/);
  assert.match(blocked({ confirmed: false }), /complete_missing_atoms_v1/);
  assert.equal(lib.repairApprovalRequired(409, { gate: "expensive_first_call", tool: "repair_structure" }), true);
  assert.equal(lib.repairApprovalRequired(409, { gate: "expensive_first_call", tool: "openmm_mutation_model" }), false);
  assert.equal(lib.repairApprovalRequired(412, { gate: "expensive_first_call", tool: "repair_structure" }), false);
  const jobs = [{ run_id: "r", job_id: "j1", protocol_id: "pdbfixer_repair_v1", status: "done" },
    { run_id: "r", job_id: "j2", protocol_id: "openmm_mutation_model_v1", status: "running" },
    { run_id: "r", job_id: "j3", protocol_id: "pdbfixer_repair_v1", status: "running" }];
  assert.equal(lib.repairActiveJob(jobs, "r").job_id, "j3");
  assert.equal(lib.repairActiveJob(jobs, "other"), null);
  assert.equal(lib.repairActiveJob("not a list", "r"), null);
  assert.equal(lib.repairJobResult({ status: "done", artifacts: { structure_repair: RECORD, prepared_structure: REPAIRED } }),
    RECORD);
  assert.equal(lib.repairJobResult({ status: "running", artifacts: {} }), null);
  assert.equal(lib.repairCancelEnabled({ job: { status: "queued", cancel_requested: false }, cancelling: false }), true);
  assert.equal(lib.repairCancelEnabled({ job: { status: "queued", cancel_requested: true }, cancelling: false }), false);
  assert.equal(lib.repairCancelEnabled({ job: { status: "done", cancel_requested: false }, cancelling: false }), false);
  const failed = lib.repairJobText({ status: "failed", cancel_requested: false, failure: { error: "input_invalid",
    message: "M7 refused", reason_code: "repair_incomplete", detail: { m7_reason: "peptide_geometry" } } }, false);
  assert.equal(failed, `구조 보완 실패 (결과를 저장하지 않았습니다): ${lib.repairReasonText("repair_incomplete")} · M7 refused · ` +
    "M7 사유 peptide_geometry");
  assert.match(lib.repairJobText({ status: "queued", cancel_requested: false, failure: null }, true), /승인/);
  assert.match(lib.repairSubmitText({ plan_only: true }), /dry-run/);
  assert.match(lib.repairSubmitText({ job_id: "j", status: "done" }), /기존 작업/);
  assert.equal(lib.repairStartProgressed({ run_id: "r", job_id: "j", attempt_ordinal: 1 },
    { run_id: "r", job_id: "j", protocol_id: "pdbfixer_repair_v1", status: "running", attempt_ordinal: 1 }), true);
  assert.equal(lib.repairStartProgressed({ run_id: "r", job_id: "j", attempt_ordinal: 1 },
    { run_id: "r", job_id: "j", protocol_id: "pdbfixer_repair_v1", status: "queued", attempt_ordinal: 1 }), false);
});

const RECORD_VALUE = {
  classes_applied: ["chain_parts_merged", "side_chain_atoms_added", "terminal_oxt_added", "internal_gap_filled"],
  counts: { added_residues: 24, added_atoms: 359, side_chain_residues: 23, terminal_oxt: 2, gaps: 2, replaced: 0,
    chain_parts_merged: 2, protein_heavy_atoms: 4538 },
  unchanged: { atom_count: 4270, max_delta_A: 1.7763568394002505e-15, input_calc_flag_cleared: 0 },
  new_atom_rounding: { decimals: 4, max_abs_delta_A: 0.0000499 },
  chain_ends: [{ chain_auth: "A", observed_first: RES(5), observed_last: RES(330), first_is_sequence_start: false,
    last_is_sequence_end: null }],
  collisions: { protein: { min_distance_A: 1.3612345678901, count_lt_2_0: 6, count_lt_1_5: 2,
    min_pair: { new_residue: RES(100), new_atom: "NZ", partner_residue: RES(140, "GLU"), partner_atom: "OE1" } },
  ligand: { min_distance_A: 8.46, count_lt_2_0: 0, count_lt_1_5: 0,
    min_pair: { new_residue: RES(100), new_atom: "CE", partner_residue: RES(901, "A1AAY"), partner_atom: "C1" } },
  metal: { min_distance_A: null, count_lt_2_0: 0, count_lt_1_5: 0, min_pair: null },
  water: { min_distance_A: 2.49, count_lt_2_0: 0, count_lt_1_5: 0,
    min_pair: { new_residue: RES(100), new_atom: "CD", partner_residue: RES(1001, "HOH"), partner_atom: "O" } },
  other: { min_distance_A: null, count_lt_2_0: 0, count_lt_1_5: 0, min_pair: null } },
  replaced: [{ from: RES(50, "MSE"), to: RES(50, "MET"), atom_map: [{ from: "SE", to: "SD" }],
    record_type: { from: "HETATM", to: "ATOM" } }],
  zero_occupancy_input_atoms: { count: 0, residues: [] },
};

test("record views: stored values as they are (no rounding), none as \"—\" with the reason, no verdict words", () => {
  const summary = lib.repairSummaryText(RECORD_VALUE);
  assert.equal(summary, "보완 종류 체인 조각 합치기, 곁사슬 원자 더하기, C 말단 OXT 더하기, 내부 틈 메우기 · 추가 잔기 24개 · " +
    "추가 원자 359개 · 보완 뒤 단백질 중원자 4538개 · 입력 원자 4270개는 그대로");
  const classes = plain(lib.repairClassRows(RECORD_VALUE));
  assert.deepEqual(classes.map(row => [row.key, row.applied]), [["chain_parts_merged", true], ["side_chain_atoms_added", true],
    ["terminal_oxt_added", true], ["internal_gap_filled", true], ["nonstandard_replaced", false]]);
  assert.equal(classes[3].countText, "틈 2개 · 잔기 24개");
  const collisions = plain(lib.collisionRows(RECORD_VALUE));
  assert.deepEqual(collisions.map(row => row.key), ["protein", "ligand", "metal", "water", "other"]);   // fixed order
  assert.equal(collisions[0].min, "1.3612345678901 Å");   // never rounded
  assert.equal(collisions[0].pair, "A/100/LYS NZ – A/140/GLU OE1");
  assert.equal(collisions[2].min, "— (이 분류의 상대 원자 없음)");
  assert.equal(collisions[2].pair, "— (상대 원자 없음)");
  assert.equal(collisions[2].lt20, "0");
  assert.equal(collisions[2].hasPartner, false);
  assert.ok(lib.COLLISION_NOTE.includes("충돌이 없다는 뜻이 아닙니다"));
  for (const row of collisions) assert.ok(!/충돌\s*없음/.test(Object.values(row).join(" ")));
  const ends = plain(lib.chainEndRows(RECORD_VALUE));
  assert.deepEqual([ends[0].start, ends[0].end, ends[0].differs], ["다름", "—(판정 불가)", true]);
  assert.equal(lib.chainEndFlagText(true), "같음");
  assert.equal(lib.chainEndFlagText(null), lib.UNDETERMINED_TEXT);
  assert.deepEqual(plain(lib.replacedRows(RECORD_VALUE)).map(row => [row.from, row.to, row.atoms, row.recordType]),
    [["A/50/MSE", "A/50/MET", "SE→SD", "HETATM→ATOM"]]);
  assert.equal(lib.zeroOccupancyText({ count: 37, residues: [RES(725, "GLU")] }), "37개 (잔기 1개: A/725/GLU) · 좌표는 입력 그대로");
  assert.equal(lib.zeroOccupancyText({ count: 0, residues: [] }), "0개 (잔기 0개) · 좌표는 입력 그대로");
  assert.ok(lib.unchangedText(RECORD_VALUE).includes("1.7763568394002505e-15 Å"));
  assert.equal(lib.valueText(null, "이유"), "— (이유)");
  assert.equal(lib.valueText(undefined), "—");
  assert.equal(lib.valueText(0), "0");
  assert.equal(lib.valueText(1.23456789), "1.23456789");
  assert.equal(lib.coordinatesText([12.3456, -0.5, 7]), "12.3456, -0.5, 7");
  assert.equal(lib.residueFieldsText({ model_number: 1, chain_auth: "A", chain_label: null, seq_auth: 274, seq_label: null,
    icode: null, resname: "GLY" }), "모델 1 · auth A/274 · icode null · label null/null · GLY");
  assert.equal(lib.atomQuery(3), "page=3&page_size=100");
  assert.equal(lib.atomQuery(0, 500), "page=1&page_size=200");
  assert.equal(lib.atomPageText({ total: 359, page: 4, page_size: 100, rows: new Array(59) }), "301–359 / 전체 359개");
  assert.equal(lib.atomPageText({ total: 0, page: 1, page_size: 100, rows: [] }), "0 / 전체 0개");
  assert.equal(lib.atomPageCount({ total: 359, page_size: 100 }), 4);
  const invalid = lib.repairListRowText({ handle: "h", created_seq: 5, valid: false, prepared_structure: null,
    source_structure: null, classes_applied: null, counts: null });
  assert.ok(!/\d+개/.test(invalid) && invalid.includes("검증되지 않는 기록"));
  assert.ok(lib.repairListRowText({ handle: RECORD, created_seq: 7, valid: true, prepared_structure: REPAIRED,
    source_structure: PREPARED_A, classes_applied: RECORD_VALUE.classes_applied, counts: RECORD_VALUE.counts })
    .includes("보완 뒤 단백질 중원자 4538개"));
  assert.equal(lib.repairReportMatches({ manifest: { schema: "method_report_manifest@1", analysis_type: "structure_repair",
    result_handle: RECORD } }, RECORD), true);
  assert.equal(lib.repairReportMatches({ manifest: { schema: "method_report_manifest@1", analysis_type: "mutation_model",
    result_handle: RECORD } }, RECORD), false);
  assert.equal(lib.detailMatches({ schema: "structure_repair_detail@1", handle: RECORD }, RECORD), true);
  assert.equal(lib.detailMatches({ schema: "structure_repair_detail@1", handle: "x" }, RECORD), false);
});

test("report library names the repair report; no report version is pinned on screen", () => {
  assert.equal(reportLibrary.reportKindLabel({ kind: "structure_repair", handle: "h", target_handle: RECORD, created_seq: 1 }),
    "구조 보완 보고서");
  for (const file of ["frontend/src/lib/report-library.ts", "frontend/src/lib/mutations.ts", "frontend/src/lib/mutation-model.ts",
    "frontend/src/lib/jev.ts", "frontend/src/lib/jev-loop.ts", "frontend/src/lib/docking.ts"])
    assert.ok(!/_markdown@\d/.test(read(file)), file);
});

// ---- wording ----

test("wording: every module text and every panel literal passes the check; fixed sentences are exempt", () => {
  // The check itself finds the words it is for (and skips a fixed sentence line).
  for (const word of ["순위", "추천", "최적", "개선", "안정성", "ΔΔG", "점수", "에너지", "수소결합", "수소 결합", "친화도",
    "충돌 없음", "best", "recommend"]) assert.ok(lib.repairForbiddenWords(`가 ${word} 나`).length > 0, word);
  assert.deepEqual(plain(lib.repairForbiddenWords(lib.REPAIR_FIXED_LINES.join("\n"))), []);
  assert.deepEqual(plain(lib.repairForbiddenWords("최적화")), []);
  const texts = Object.values(lib).filter(value => typeof value === "string");
  for (const record of [lib.CLASS_LABEL, lib.COLLISION_LABEL, lib.ORIGIN_LABEL, lib.STATE_TEXT]) texts.push(...Object.values(record));
  texts.push(...[...lib.REFUSAL_REASONS, ...lib.ADMISSION_REASON_CODES, ...lib.UNAVAILABLE_REASON_CODES,
    ...lib.FAILURE_REASON_CODES].map(lib.repairReasonText));
  texts.push(lib.repairSummaryText(RECORD_VALUE), ...lib.collisionRows(RECORD_VALUE).flatMap(row => Object.values(row).map(String)),
    ...lib.chainEndRows(RECORD_VALUE).flatMap(row => Object.values(row).map(String)), lib.unchangedText(RECORD_VALUE),
    ...Object.values(plain(lib.preflightView(PREFLIGHT))).flat().map(value => typeof value === "string" ? value
      : JSON.stringify(value)));
  for (const text of texts) assert.deepEqual(plain(lib.repairForbiddenWords(text)), [], text);
  // Every literal the panel can render, and its test ids (all "repair-"; the shared notes take the caller's id).
  const source = read(PANEL_FILE);
  const sourceFile = ts.createSourceFile(PANEL_FILE, source, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
  const literals = [], ids = [];
  const visit = node => {
    if (ts.isJsxText(node) && node.text.trim()) literals.push(node.text.trim());
    else if (ts.isStringLiteral(node) && !ts.isImportDeclaration(node.parent)) literals.push(node.text);
    else if (ts.isNoSubstitutionTemplateLiteral(node)) literals.push(node.text);
    else if (ts.isTemplateExpression(node)) literals.push(node.head.text, ...node.templateSpans.map(span => span.literal.text));
    if (ts.isJsxAttribute(node) && ["data-testid", "testId"].includes(node.name.getText(sourceFile))) {
      const value = node.initializer;
      if (value && ts.isStringLiteral(value)) ids.push(value.text);
      else if (value && ts.isJsxExpression(value) && value.expression) ids.push(`<${value.expression.getText(sourceFile)}>`);
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  assert.ok(literals.length > 80, String(literals.length));
  for (const text of literals) assert.deepEqual(plain(lib.repairForbiddenWords(text)), [], text);
  assert.ok(ids.length > 40, String(ids.length));
  for (const id of ids) assert.ok(id.startsWith("repair-") || ["<testId>", "<`${testId}-open`>",
    "<`${testId}-empty`>", "<`${testId}-unknown`>", "<runId === null ? \"repair-no-run\" : \"repair-unavailable\">"]
    .includes(id), id);
  // No fixed sentence is retyped in the panel; values are not computed or sorted there; no HTML strings.
  for (const sentence of lib.REPAIR_FIXED_LINES) assert.ok(!source.includes(sentence.slice(0, 18)), sentence);
  assert.ok(!/\.sort\(|toFixed\(|Math\.|<progress|<meter|style=|dangerouslySetInnerHTML|innerHTML/.test(source));
  // The other screens show the server's SO1 / JW1 and never retype them.
  for (const file of ["MutationPanel.tsx", "MutationModelPanel.tsx", "SequenceGaPanel.tsx", "DockingPanel.tsx",
    "JevPanel.tsx", "JevLoopPanel.tsx"]) {
    const other = read(`frontend/src/components/${file}`);
    for (const sentence of [lib.SO1, lib.SO2, lib.SO3, lib.JW1]) assert.ok(!other.includes(sentence.slice(0, 18)), file);
    assert.ok(/structure_origin/.test(other), file);
  }
  for (const [file, ids_] of [["JevPanel.tsx", ["jev-preview-repair-warning", "jev-approval-repair-warning",
    "jev-send-repair-warning", "jev-repair-origin"]], ["JevLoopPanel.tsx", ["jev-loop-preview-repair-warning",
    "jev-loop-approval-repair-warning", "jev-loop-send-repair-warning", "jev-loop-repair-origin"]],
  ["SequenceGaPanel.tsx", ["sequence-ga-repair-origin"]], ["MutationModelPanel.tsx", ["mutation-model-repair-origin"]]]) {
    const other = read(`frontend/src/components/${file}`);
    for (const id of ids_) assert.ok(other.includes(id), `${file} ${id}`);
  }
});

// ---- the panel rendered on the server (no effect runs, so no request) ----

const primitives = compileTsx("../src/components/primitives.tsx", { "@/lib/contracts": load("contracts") });
const noRequest = () => { throw new Error("a server render makes no request"); };
const apiStub = { api: new Proxy({}, { get: () => noRequest }), ApiError: class ApiError extends Error {} };
const panel = compileTsx("../src/components/StructureRepairPanel.tsx", { "@/lib/api": apiStub, "@/lib/mutations": mutations,
  "@/lib/structure-repair": lib, "./primitives": primitives });
const RUN = { run_id: "fixture-run", goal: "", context: [], dry_run: false, egress: "local_only", last_seq: 1 };
const CAPABILITY = { schema: "structure_repair_capability@1", protocol_id: "pdbfixer_repair_v1", tool_id: "repair_structure",
  execution_lane: "durable_job", result_schema: "structure_repair@1", method_version: "mw.structure_repair/v1",
  timeout_s: { default: 120, max: 240 }, limits: {}, available: true, reason_code: null, reason: null,
  versions: { openmm: "8.6.0", openmm_engine_build: "x", pdbfixer: "1.12.0" } };
const render = props => renderToStaticMarkup(React.createElement(panel.StructureRepairPanel,
  { run: RUN, capability: CAPABILITY, onObjectsChanged: () => undefined, onReportCreated: () => undefined, ...props }));
const tagOf = (html, testId) => new RegExp(`<[a-z]+ [^>]*data-testid="${testId}"[^>]*>`).exec(html)?.[0] ?? "";

test("panel gates: no run, no method, unavailable, not read yet: the reason only, no control and no number", () => {
  const off = { ...CAPABILITY, available: false, reason_code: "pdbfixer_unavailable", reason: "PDBFixer missing",
    versions: null };
  for (const [props, id, state] of [[{ run: null }, "repair-no-run", "unavailable"], [{ capability: null }, "repair-unavailable",
    "unavailable"], [{ capability: off }, "repair-unavailable", "unavailable"], [{ capability: undefined }, null, "loading"]]) {
    const html = render(props);
    assert.match(tagOf(html, "repair-panel"), new RegExp(`data-repair-state="${state}"`), JSON.stringify(props));
    if (id) assert.ok(html.includes(`data-testid="${id}"`), id);
    assert.ok(!/<(input|select|button|table|a) /.test(html), html);
    assert.ok(!/\d/.test(html.replace(/<[^>]+>/g, "")), html);
  }
  assert.ok(render({ capability: off }).includes("(pdbfixer_unavailable)"));
});

test("panel first render: areas in order, nothing chosen, the confirmation off and the submit closed with its reason", () => {
  const html = render({});
  assert.match(tagOf(html, "repair-panel"), /data-repair-state="loading"/);
  assert.deepEqual([...html.matchAll(/data-repair-area="([a-z]+)"/g)].map(match => match[1]),
    ["input", "preflight", "start", "results"]);
  assert.match(tagOf(html, "repair-confirm"), /disabled=""/);
  assert.ok(!/checked/.test(tagOf(html, "repair-confirm")));
  assert.match(tagOf(html, "repair-submit"), /disabled=""/);
  assert.ok(html.includes('data-testid="repair-submit-blocked"'));
  for (const id of ["repair-structure", "repair-preflight", "repair-job", "repair-detail", "repair-report"])
    assert.ok(!html.includes(`data-testid="${id}"`), id);
  const ids = [...html.matchAll(/data-testid="([^"]+)"/g)].map(match => match[1]);
  for (const id of ids) assert.ok(id.startsWith("repair-"), id);
  const text = html.replace(/<[^>]+>/g, "\n");
  assert.deepEqual(plain(lib.repairForbiddenWords(text)), []);
  assert.ok(text.includes(lib.BUDGET_NOTE) && text.includes(lib.METHOD_NOTE));
  assert.ok(!/molstar|<canvas/i.test(html));
});

test("shared notes: SO1 and JW1 exactly as the server gave them, with the record handle and the open button", () => {
  const origin = { repair_record: RECORD, repaired_structure: REPAIRED, source_structure: PREPARED_A,
    counts: RECORD_VALUE.counts, statements: [{ id: "SO1", text: lib.SO1 }] };
  const html = renderToStaticMarkup(React.createElement(panel.RepairOriginNote, { origin, testId: "x-origin",
    onOpenRecord: () => undefined }));
  assert.ok(html.includes(`data-statement="SO1">${lib.SO1}</p>`));
  assert.ok(html.includes(`data-repair-record="${RECORD}"`) && html.includes('data-testid="x-origin-open"'));
  assert.ok(html.includes(lib.OPEN_RECORD_TEXT) && html.includes(lib.REPAIRED_BADGE));
  assert.equal(renderToStaticMarkup(React.createElement(panel.RepairOriginNote, { origin: undefined, testId: "x" })), "");
  const noOpen = renderToStaticMarkup(React.createElement(panel.RepairOriginNote, { origin, testId: "x-origin" }));
  assert.ok(!noOpen.includes("<button"));
  const warning = renderToStaticMarkup(React.createElement(panel.RepairWarningNote, { warning: { id: "JW1", text: lib.JW1 },
    testId: "x-warning" }));
  assert.ok(warning.includes(`>${lib.JW1}</p>`) && warning.includes('data-statement="JW1"'));
  assert.equal(renderToStaticMarkup(React.createElement(panel.RepairWarningNote, { warning: undefined, testId: "x" })), "");
});


test("preflight block: without a defect analysis the blocker and five defect tables say so and never show 0", () => {
  const tables = ["repair-blockers", "repair-defect-chain-parts", "repair-defect-side-chain", "repair-defect-oxt",
    "repair-defect-gaps", "repair-defect-nonstandard"];
  const block = preflight => renderToStaticMarkup(React.createElement(panel.PreflightBlock, { preflight,
    view: lib.preflightView(preflight) }));
  const blindPreflight = { ...PREFLIGHT, repairable: null, blockers: [], defects: null, expected_added_residues: null,
    expected_added_heavy_atoms: null, statements: [], admission: { admitted: false, error: "precondition",
      reason_code: "openmm_unavailable", message: "m", detail: null } };
  const blind = block(blindPreflight);
  const blindText = blind.replace(/<[^>]+>/g, "\n");
  for (const id of tables) {
    assert.ok(blind.includes(`data-testid="${id}-unknown"`), id);
    assert.ok(!blind.includes(`data-testid="${id}-empty"`) && !blind.includes(`data-testid="${id}"`), id);
  }
  assert.equal(blindText.split(lib.NOT_ANALYSED_TEXT).length - 1, 9);    // heading, six tables, repairable, expected
  assert.ok(!/0개/.test(blindText), blindText);
  // With the analysis, an empty list is a real "0" (the server listed none).
  const analysed = block({ ...PREFLIGHT, defects: { ...PREFLIGHT.defects, nonstandard: [] } });
  assert.ok(analysed.includes('data-testid="repair-defect-nonstandard-empty"') && analysed.includes("MSE 잔기 0개"));
  assert.ok(analysed.includes('data-testid="repair-blockers-empty"') && analysed.includes("걸림돌 (0개)"));
  assert.ok(!analysed.includes("-unknown\""));
  assert.deepEqual(plain(lib.repairForbiddenWords(blindText + analysed.replace(/<[^>]+>/g, "\n"))), []);
});

// The user-facing strings M29 added to the other screens (git diff 3c5994e4.. of frontend/src: badges, SO1 notes with
// the record, "보완 전 원본 구조" choices, the modeled-basis column, the M23 screen-only note): each is still in its file and
// none holds a forbidden word (the panel's own literals are checked above).
const M29_SCREEN_STRINGS = {
  "frontend/src/components/MutationPanel.tsx": [" · 보완 전 원본 구조", "보완 전 원본 구조로 검출한 포켓 있는 결과가 " +
    "없습니다. 구조 분석 탭에서 원본 구조의 포켓 검출을 먼저 실행하세요.", "이 구조로 검출한 포켓 있는 결과가 없습니다. " +
    "구조 분석 탭에서 포켓 검출을 먼저 실행하세요.", "모델링 원자·잔기 (SO2)", "원본", "보완 기록"],
  "frontend/src/components/SequenceGaPanel.tsx": [" · 보완 구조", "보완 구조", "보완 기록", "원본",
    "(화면 표시만, 서열 GA 보고서에는 이 사실이 들어가지 않음)", "보완 기록 열기"],
  "frontend/src/components/MutationModelPanel.tsx": ["보완 구조", "보완 기록", "원본", "보완 기록 열기"],
  "frontend/src/components/JevLoopPanel.tsx": ["보완 구조", "보완 기록", "원본", "보완 기록 열기"],
  "frontend/src/components/DockingPanel.tsx": ["보완 구조"],
  "frontend/src/lib/jev.ts": ["보완 구조", "보완 기록", "원본", "보완 기록 열기"],
  "frontend/src/lib/report-library.ts": ["구조 보완 보고서"],
};

test("wording: the M29 strings on the other screens pass the check", () => {
  for (const [file, strings] of Object.entries(M29_SCREEN_STRINGS)) {
    const source = read(file);
    for (const text of strings) {
      assert.ok(source.includes(text), `${file}: ${text}`);
      assert.deepEqual(plain(lib.repairForbiddenWords(text)), [], `${file}: ${text}`);
    }
  }
  assert.deepEqual(plain(lib.repairForbiddenWords([lib.MODELED_NOT_CHECKED_TEXT, lib.modeledBasisText({ modeled_basis: true }),
    lib.modeledBasisText({ modeled_basis: false }), lib.REPAIRED_POCKET_NOTE, lib.REPAIRED_REFERENCE_NOTE].join("\n"))), []);
});
