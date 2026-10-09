"use strict";

// M23 sequence GA design offscreen QA (.dryforge/spec.md sections 2-5, 7, 9, 10, 12). Real Electron offscreen page
// (isOffscreen, GPU/WebGL, paint). Every product mutation is a Playwright locator mouse/keyboard/file-chooser/select
// input; DOM .click() and product handlers are never called. Observation is read-only: data attributes and text of
// the page, renderer request/response events, Electron paint frames, downloaded bytes, GET reads of the loopback API,
// the stored object payloads in <runs-dir>/<run>/events.jsonl (read-only file reads) and the process table
// (`ps`/`lsof`). Every limit raise is the screen's own button (a person's click); this script never posts one. One
// labeled renderer-route fixture holds a GET response and releases the unchanged backend bytes late (late-response
// case); it never produces a scientific value.
//
// Inputs: public 1UBQ (backend/tests/fixtures/public_1ubq.cif; the only local public structure that passes the M7
// preflight), the M20 tiny set made through the M20 screen (I3 protected, K6, I44, G76; allowed A W: 6 candidates, 26
// combinations at max_mutations 3; candidates and positions = backend/tests/fixtures/sequence_ga/
// m20-candidate-set-1ubq-tiny.json, a stored v1 set; the tool now builds it as v2 (M26: catalytic check not_checked)), an
// I44W-only set (1 combination), and three labeled synthetic ligand SDFs imported through the M18 docking area: the
// phenol (mutation_model/synthetic-phenol-ligand.sdf), a planar one (docking/synthetic-ligand-planar-z0.sdf,
// ligand_not_3d) and an implicit-H one (docking/synthetic-ligand-implicit-h.sdf, refused by the worker's RDKit/Meeko
// step: the wild-type reference row fails).
//
// Independent oracle (written here, never the product helpers): the spec 2 parameter table, the spec 7 arithmetic
// (reserved_evaluations = min(max_new, P + (G − 1)(P − E)); reserved_units = 2 × (reserved_evaluations + 1); wall =
// min(total_s + 600, units × 270 + 300); shortfall = max(0, need − remaining); may-be-partial = units × 270 > total_s),
// the combination-space size N = Σ e_k (elementary symmetric polynomials of the per-position candidate counts), S1–S6
// verbatim (spec 4), the carried rule (score, then mutation count, then pick_index), the display order rule (rows
// without a score always last, never 0) and, for GA 1, the T1 independent oracle vector `s4_tiny_observed` of
// backend/tests/fixtures/sequence_ga/expected.json (same tiny set, GA values and T1 docking values; its scores are the
// T1 real-engine observations). Scores and potentials are never computed here: each shown value is compared with the
// stored M18 result / mutation_set_model@1 payload.
//
// Modes (the full sequence: scripts/m23_offscreen_acceptance.py):
//   main         fresh root: no run → 1UBQ load + 전처리 → GA area without a candidate set (reason only) → M20 tiny and
//                I44W sets → three SDF imports (리간드 탭) and the tab trip back (nothing chosen) → parameter guards (11
//                keys out of range, two cross rules, 기본값으로) → confirmation/acknowledgement blocks → refused preflights
//                (ga_space_too_small twice, ligand_not_3d) → GA 1 preflight (server numbers = spec 7, 4,890 flag) →
//                screen limit approval → GA 1 (run's first expensive approval, progress, done) → results = stored
//                (reference row apart, generation tabs, rows, 7 fields, min/max, S sentences, T1 oracle path), sort,
//                individual + reference detail and mmCIF downloads, M18 detail → GA 1 arguments again (existing job)
//                → GA 2 (other GA seed, same evaluation seed: reuse + evaluation_limit) → GA 3 cancelled while running
//                → GA 4 implicit-H SDF (reference_failed) → held summary-detail response → report + list + downloads +
//                지식·보고서 reopen → tab invariants → processes → wording.
//   repro        two fresh runs in the same backend process replay GA 1 through the screen (load, prepare, M20 tiny set,
//                phenol import, the same inputs and GA values, the screen's limit approval, run); the runner compares
//                the stored summaries and rows (every sequence GA needs ≥ 10 units > the 8-unit default run budget, and
//                only a person's click on the screen raises a limit).
//   unavailable  backend started from a layout without the locked docking environment (runner): no-run and
//                capability-unavailable states show a reason only (no numbers, no controls, no sequence GA requests).
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const { waitForViewer } = require("./normal-flow.cjs");
const m18 = require("./docking-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const FIXTURES = path.join(REPO, "backend/tests/fixtures");
const STRUCTURE = path.join(FIXTURES, "public_1ubq.cif");
const PHENOL = path.join(FIXTURES, "mutation_model/synthetic-phenol-ligand.sdf");
const PLANAR = path.join(FIXTURES, "docking/synthetic-ligand-planar-z0.sdf");
const IMPLICIT_H = path.join(FIXTURES, "docking/synthetic-ligand-implicit-h.sdf");
const TINY_FIXTURE = path.join(FIXTURES, "sequence_ga/m20-candidate-set-1ubq-tiny.json");
const EXPECTED = path.join(FIXTURES, "sequence_ga/expected.json");
const ORACLE_VECTOR = "s4_tiny_observed";
const MODES = ["main", "repro", "unavailable"];
const TAB = "단백질 공학";
const LIGAND_TAB = "리간드 설계·탐색";
const TAB_LABELS = ["구조 분석", "단백질 공학", "리간드 설계·탐색", "지식·보고서"];
const PROTOCOL = "sequence_ga_dock_v1";
const TOOL = "sequence_ga_design";
const M20_TOOL = "generate_mutation_candidates";
const RESIDUE_FIELDS = ["model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname"];
// M20 sets made through the M20 screen (user-selected residues, protection, allowed residues).
const TINY = { residues: [["ILE", 3], ["LYS", 6], ["ILE", 44], ["GLY", 76]], protect: [["ILE", 3]], allowed: ["A", "W"] };
const SMALL = { residues: [["ILE", 44]], protect: [], allowed: ["W"] };
// T1 (g) docking values (backend/tests/test_sequence_ga_jobs.py DOCK, sequence_ga_fixture.args_for box).
const DOCK = { seed: "20261004", exhaustiveness: "4", numModes: "5", energyRange: "3", margin: "8" };
const CANCEL_SEED = "7";
const ACK_KEYS = ["keep_input_protonation", "tool_assigned_types_charges", "rigid_no_optimization"];
// spec 2 table: [min, max, default] (seed: no default)
const RANGES = { seed: [0, 2147483647, null], population_size: [4, 16, 8], generations: [1, 8, 5],
  elite_count: [0, 4, 2], tournament_size: [2, 4, 2], crossover_fraction: [0, 1, 0.5], random_fraction: [0, 0.5, 0.2],
  max_mutations: [1, 4, 3], patience: [1, 8, 3], max_new_evaluations: [4, 64, 32], total_s: [600, 14400, 7200] };
const GA_KEYS = Object.keys(RANGES);
const FLOAT_KEYS = ["crossover_fraction", "random_fraction"];
const OUT_OF_RANGE = { seed: "2147483648", population_size: "17", generations: "9", elite_count: "5",
  tournament_size: "1", crossover_fraction: "1.5", random_fraction: "0.6", max_mutations: "5", patience: "0",
  max_new_evaluations: "65", total_s: "599" };
// GA 1 = the T1 oracle vector s4_tiny_observed (asserted against expected.json); reserved 13 evaluations / 28 units.
const GA1 = { seed: 21, population_size: 4, generations: 4, elite_count: 1, tournament_size: 2, crossover_fraction: 0.5,
  random_fraction: 0.25, max_mutations: 3, patience: 2, max_new_evaluations: 32, total_s: 7200 };
// GA 2: other GA seed, same evaluation seed (the independent oracle on the T1 table: 4 new, 2 reused, evaluation_limit).
const GA2 = { ...GA1, seed: 13, generations: 2, max_new_evaluations: 4, total_s: 600 };
// GA 3 (evaluation seed 7, nothing reusable: cancelled while running) and GA 4 (implicit-H SDF: reference_failed).
const GA3 = { ...GA1, generations: 2, max_new_evaluations: 4, total_s: 600 };
const GA4 = { ...GA3 };
const STOP_STATUS = { generations_complete: "complete", no_change: "complete", space_exhausted: "complete",
  evaluation_limit: "partial", time_exhausted: "partial", cancelled: "partial", worker_failed: "partial",
  resource_exceeded: "partial", reference_failed: "partial", repeated_failure: "partial" };
// spec 4 verbatim (independent of the product constants)
const S = {
  S1: "서열 GA는 변이 조합 공간에서 어떤 조합을 모델링·도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 순위나 " +
    "추천이 아니다. 교차·편집의 부모 선택은 작업 모듈 기록이며 서버가 다시 계산하지 않았고 변이 목록의 부모–자식 관계만 검증했다.",
  S2: "이 실행은 시간·평가 상한·취소·기준 행 실패·연속 실패 등으로 일부만 계산되었다. 계산하지 않은 개체는 점수가 없으며 " +
    "0이 아니고, 한도 도달로 멈춘 실행은 같은 설정으로 다시 해도 같은 경로를 보장하지 않는다.",
  S3: "재사용한 개체는 같은 후보 집합·구조·리간드·상자·seed·값으로 이전에 저장된 모델링·도킹 결과를 가져온 것이며, 저장된 " +
    "결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있다.",
  S4: "점수는 각 개체의 변이 구조(PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 단백질만의 " +
    "모델)에 사용자가 준 리간드 좌표를 그대로 두고 자유 도킹한 qvina 점수이며, 변이의 효과나 결합 친화도를 뜻하지 않는다.",
  S5: "OpenMM 전위는 각 구조의 Amber14-all + GBn2 값(kJ/mol)이며 서열이 다른 구조의 값은 서로 비교할 수 없고 " +
    "ΔΔG·안정성이 아니다.",
  S6: "여러 곳 변이는 구조 순서대로 한 곳씩 PDBFixer로 연속 적용한 모델이며(앞 단계에서 놓은 원자 좌표는 다음 단계 전에 " +
    "소수 넷째 자리로 반올림했다) 적용 순서와 곁사슬 크기에 따라 모델이 달라질 수 있다. 구조의 충돌·전위는 점수나 선택에 " +
    "쓰지 않았고(전위가 늘거나 유한하지 않은 모델만 실패로 처리), 개체마다 수용체가 다르므로 개체 점수를 나란히 두는 것은 " +
    "같은 수용체 안의 비교가 아니며(개체 도킹 결과의 M18 둘째 한계 문장이 말하는 조건과 다르다) 순위나 '더 잘 결합'을 " +
    "뜻하지 않는다.",
};
// mutation_set_model@1 limitation sentences (spec 4: M21 L1, L3 always; SL5 with protonation differences; M21 L6)
const MODEL_LIMITATIONS = [
  "변이 구조는 PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 모델이며 회전이성질체 탐색과 수렴을 주장하지 않는다.",
  "모델은 단백질만 포함하며 리간드·금속 이온·물·보조인자는 제외했다.",
  "변이한 잔기 밖에서 히스티딘·시스테인 양성자 상태가 야생형 기준 구조와 다르게 지정되었으므로 두 구조의 차이는 지정한 변이만이 아니다.",
  "변이형에는 야생형 기준에 없는 이황화 결합이 거리 기준으로 만들어졌다.",
];
const SCORE_LABEL = "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)";
const SCORE_HEADER = "qvina 점수(kcal/mol) · 모드 1(엔진 출력 순서)";
const ENERGY_LABEL = "OpenMM Amber14-all + GBn2 전위(kJ/mol)";
const ORIGIN_LABEL = { initial: "초기", carried: "이어받음", crossover: "교차", edit: "편집", random: "무작위" };
const NO_CHANGE_LABEL = "점수 최솟값 변화 없음";   // spec 5
const NO_RUN_REASON = "구조 분석 탭에서 run을 먼저 고르세요.";
const NO_SET_REASON = "변이 후보 집합이 없습니다";
const MAY_BE_PARTIAL = "끝까지 못 갈 수 있음";
const M18_HEAVY_ATOM_ESTIMATE = 4890;
const UNAVAILABLE_LABEL = "labeled runtime layout without .deps (runner): capability worker_missing";
const HOLD_LABEL = "QA held-response fixture (labeled renderer route; unchanged backend bytes released late)";
const PROVIDER_EVENT_TYPES = new Set(["egress", "egress_budget_settled", "viewer_dispatch_started"]);
const PROCESS_PATTERNS = ["sequence_ga_worker.py", "sequence_model_worker.py", "docking_worker.py", "qvina2", "guardian.py"];
// No rank/best/improvement/winner/recommendation/comparison/difference/change/average/effect/affinity/stability word in
// the GA area outside the fixed sentences (S1–S6, model and M18 limitations) and the exact score names.
const FORBIDDEN = new RegExp(["순위", "최고", "최적(?!화)", "개선", "승자", "우승", "추천", "유망", "좋은", "나쁜", "우수",
  "우월", "상위", "하위", "향상", "악화", "대비", "차이", "증감", "증가", "감소", "변화량", "평균", "효과", "친화", "안정성",
  "ΔΔG", "Δ", "결합\\s*강도", "부분\\s*완료", "\\brank", "\\bbest", "improv", "winner", "recommend", "optimal", "stabili",
  "delta", "differen", "affinity", "better", "worse", "superior", "↑", "↓", "▲", "▼"].join("|"), "gi");

// absolute when present: a PATH without /usr/sbin must not make every process look like it is elsewhere
const LSOF = fs.existsSync("/usr/sbin/lsof") ? "/usr/sbin/lsof" : "lsof";
const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const attr = (name, value) => `[${name}="${String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"]`;
const shortHandle = handle => handle.split("/").at(-1).slice(0, 12);
const { halfUp } = m18;
const seconds = value => `${halfUp(value, 1)}초`;
const pairText = pair => `비싼 계산 ${pair.expensive_calls}단위 · 활동 시간 ${seconds(pair.wall_clock_s)}`;
const count = value => String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const strings = values => Object.fromEntries(Object.entries(values).map(([key, value]) => [key, String(value)]));
const resShort = r => `${r.resname} ${r.chain_auth}:${r.seq_auth}${r.icode}`;
const fieldsText = r => RESIDUE_FIELDS.map(key => `${key}=${JSON.stringify(r[key])}`).join(", ");
const mutText = m => `${resShort(m.residue)} ${m.from}→${m.to}`;
/** "한국어 (code)": the code in parentheses, preceded (after the prefix) by a Korean name. */
function koreanThenCode(text, code) {
  const at = text.indexOf(` (${code})`);
  return at > 0 && /[가-힣]/.test(text.slice(text.indexOf(": ") + 2, at));
}

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, "fixture-label": null, "runs-dir": null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2);
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode) || (value.mode !== "unavailable" && !value["runs-dir"])) throw new Error(
    `Usage: sequence-ga-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> [--url http://127.0.0.1:3000] ` +
    "[--runs-dir <backend MW_RUNS_DIR> (main, repro: stored objects)] [--fixture-label <runtime layout label>]. main " +
    "needs a fresh runs root, OpenMM/PDBFixer and the locked docking environment; repro runs after main on the same " +
    "backend; unavailable needs a backend without the docking environment and a fresh runs root. Full sequence: " +
    "scripts/m23_offscreen_acceptance.py.");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  value.artifacts = path.resolve(value.artifacts);
  if (value["runs-dir"]) value["runs-dir"] = path.resolve(value["runs-dir"]);
  value.url = new URL("/", value.url).toString();
  return value;
}

// ------------------------------------------------------------------ independent oracle
function oracle() {
  const tiny = JSON.parse(fs.readFileSync(TINY_FIXTURE, "utf8"));
  const expected = JSON.parse(fs.readFileSync(EXPECTED, "utf8"));
  const vector = expected.vectors[ORACLE_VECTOR];
  assert.deepEqual(vector.ga, GA1, "GA 1 must be the T1 oracle vector's GA values");
  return { files: [TINY_FIXTURE, EXPECTED].map(fileRecord), tiny: tiny.content, vector,
    space: expected.spaces.s4_tiny_1ubq };
}
/** Exact N = Σ_{k=1..M} e_k(counts) (BigInt-free: small spaces only here). */
function spaceSize(counts, maxMutations) {
  const m = Math.min(maxMutations, counts.length);
  let e = [1];   // e[k] after each position
  for (const n of counts) {
    const next = [...e, 0];
    for (let k = e.length; k >= 1; k--) next[k] = (e[k] ?? 0) + e[k - 1] * n;
    e = next;
  }
  let total = 0;
  for (let k = 1; k <= m; k++) total += e[k] ?? 0;
  return total;
}
/** Spec 7: reserved evaluations and units, need, may-be-partial (hand arithmetic). */
function needFor(ga) {
  const reservedEvaluations = Math.min(ga.max_new_evaluations, ga.population_size + (ga.generations - 1) *
    (ga.population_size - ga.elite_count));
  const units = 2 * (reservedEvaluations + 1);
  return { reservedEvaluations, units,
    needed: { expensive_calls: units, wall_clock_s: Math.min(ga.total_s + 600, units * 270 + 300) },
    mayBePartial: units * 270 > ga.total_s };
}
function shortfallFor(needed, remaining) {
  return { expensive_calls: Math.max(0, needed.expensive_calls - remaining.expensive_calls),
    wall_clock_s: Math.max(0, needed.wall_clock_s - remaining.wall_clock_s) };
}
/** Spec 4 rule for the stored sentence ids: S1; S2 when partial; S3 with reuse; S4–S6. */
function statementIds(stored) {
  return ["S1", ...(stored.status === "partial" ? ["S2"] : []), ...(stored.reused_count > 0 ? ["S3"] : []), "S4", "S5", "S6"];
}
function compareKeys(a, b) {
  const x = a.split("-").map(Number), y = b.split("-").map(Number);
  for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i];
  return x.length - y.length;
}
/** Display order (spec 5, 10), written independently: rows without a score always last in slot order. */
function sortOracle(rows, key, direction) {
  const has = row => row.state === "scored" && typeof row.score === "number";
  const bySlot = [...rows].sort((a, b) => a.position - b.position);
  const head = bySlot.filter(has), tail = bySlot.filter(row => !has(row));
  if (key === null) return [...head, ...tail];
  if (key === "slot") return [...(direction === "asc" ? head : [...head].reverse()), ...tail];
  const sign = direction === "asc" ? 1 : -1;
  if (key === "key") return [...[...head].sort((a, b) => sign * compareKeys(a.key, b.key) || a.position - b.position), ...tail];
  return [...[...head].sort((a, b) => sign * (a.score - b.score) || a.position - b.position), ...tail];
}
/** Spec 3 score order (carried rule): score ascending, then mutation count, then pick_index. */
function scoreOrder(a, b) {
  return a.score - b.score || a.mutations.length - b.mutations.length || a.pick_index - b.pick_index;
}
const PATH_FIELDS = ["key", "origin", "parents", "edit_op", "evaluation", "pick_index", "eval_index", "state",
  "reason_code", "score"];
function projectPath(generations) {
  return generations.map(gen => ({ index: gen.index, complete: gen.complete, min_score: gen.min_score,
    max_score: gen.max_score, individuals: gen.individuals.map(item => Object.fromEntries(PATH_FIELDS.map(key =>
      [key, item[key]]))) }));
}

// ------------------------------------------------------------------ read-only observation
async function readApi(page, route) {
  const response = await page.request.get(new URL(`/api${route}`, page.url()).toString());
  assert.equal(response.status(), 200, `${route}: ${await response.text()}`);
  return response.json();
}
async function readBytes(page, route) {
  const response = await page.request.get(new URL(`/api${route}`, page.url()).toString());
  assert.equal(response.status(), 200, route);
  return Buffer.from(await response.body());
}
async function runEvents(page, run) {
  const events = [];
  let after = 0;
  for (;;) {
    const chunk = await readApi(page, `/runs/${run}/events?after=${after}&limit=500`);
    events.push(...chunk);
    if (chunk.length < 500) break;
    after = chunk.at(-1).seq;
  }
  return events;
}
async function providerCalls(page, run) {
  const events = await runEvents(page, run);
  const budget = await readApi(page, `/runs/${run}/budget`);
  const egress = events.filter(event => PROVIDER_EVENT_TYPES.has(event.type)).length;
  return { run, egressEvents: egress, externalTokensUsed: budget.external_tokens?.used ?? null,
    usdUsed: budget.usd?.used ?? null,
    zero: egress === 0 && (budget.external_tokens?.used ?? 0) === 0 && (budget.usd?.used ?? 0) === 0 };
}
async function budgetUsed(page, run) { return (await readApi(page, `/runs/${run}/budget`)).expensive_calls; }
/** A stored object's content: the object_created payload in the run's event log (read-only file read). */
function storedObject(runsDir, run, handle, raw = false) {
  const file = path.join(runsDir, run, "events.jsonl");
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    if (!line.includes(handle)) continue;
    const event = JSON.parse(line);
    if (event.type === "object_created" && event.handle === handle) {
      const bytes = Buffer.from(event.payload_b64, "base64");
      return raw ? bytes : JSON.parse(bytes.toString("utf8"));
    }
  }
  throw new Error(`no object_created event for ${handle}`);
}
/** Handles of the run's stored objects of one kind (event-log order, read-only file read). */
function objectHandles(runsDir, run, kind) {
  const found = [];
  for (const line of fs.readFileSync(path.join(runsDir, run, "events.jsonl"), "utf8").split("\n")) {
    if (!line.includes("object_created") || !line.includes(`/${kind}/`)) continue;
    const event = JSON.parse(line);
    if (event.type === "object_created" && (event.handle ?? "").includes(`/${kind}/`)) found.push(event.handle);
  }
  return found;
}
/** Worker, guardian, modeling child and qvina2 processes whose command or working directory lies under the runs folder. */
function jobProcesses(runsDir) {
  const ps = execFileSync("ps", ["-axo", "pid=,command="], { encoding: "utf8" });
  const found = [];
  for (const line of ps.split("\n")) {
    const trimmed = line.trim();
    if (!PROCESS_PATTERNS.some(item => trimmed.includes(item))) continue;
    const pid = trimmed.split(/\s+/, 1)[0];
    let cwd = "";
    try { cwd = execFileSync(LSOF, ["-a", "-p", pid, "-d", "cwd", "-Fn"], { encoding: "utf8" }); } catch { /* exited */ }
    const dirs = cwd.split("\n").filter(item => item.startsWith("n")).map(item => item.slice(1));
    if (trimmed.includes(runsDir) || dirs.some(dir => dir === runsDir || dir.startsWith(`${runsDir}/`)))
      found.push({ pid: Number(pid), command: trimmed.slice(0, 300), cwd: dirs[0] ?? null });
  }
  return found;
}
/** Enabled now (no waiting for an element that is not, or no longer, rendered). */
async function enabled(locator) {
  return await locator.count() > 0 && await locator.isEnabled({ timeout: 1000 }).catch(() => false);
}
async function waitFor(page, probe, label, timeout = 60000) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    try { last = await probe(); if (last) return last; } catch (error) { last = String(error); }
    await page.waitForTimeout(150);
  }
  throw new Error(`${label}: timed out; last=${JSON.stringify(last)?.slice(0, 800)}`);
}

async function offscreenProof(app, page) {
  const state = await app.evaluate(({ app: electronApp }) => electronApp.__offscreenQa.status());
  const webgl = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
    if (!gl) return null;
    const info = gl.getExtension("WEBGL_debug_renderer_info");
    return { version: gl.getParameter(gl.VERSION),
      renderer: info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER) };
  });
  let firstPaint = null;
  if (state.firstPaint?.path) {
    const bytes = fs.existsSync(state.firstPaint.path) ? fs.readFileSync(state.firstPaint.path) : null;
    firstPaint = { ...state.firstPaint, onDiskBytes: bytes?.length ?? null, onDiskSha256: bytes ? sha(bytes) : null };
  }
  return { offscreen: state.offscreen, visible: state.visible, painting: state.painting,
    hardwareAccelerationEnabled: state.hardwareAccelerationEnabled, paintCount: state.paintCount, firstPaint, webgl,
    nonLoopbackRequests: state.blockedRequests.length, blockedRequests: state.blockedRequests,
    loopbackRequestCount: state.loopbackRequestCount, versions: state.versions };
}
function offscreenComplete(proof) {
  return !!proof && proof.offscreen === true && proof.visible === false && proof.painting === true &&
    proof.hardwareAccelerationEnabled === true && proof.paintCount > 0 && !!proof.webgl &&
    !!proof.firstPaint && proof.firstPaint.onDiskBytes > 0 && proof.firstPaint.onDiskSha256 === proof.firstPaint.sha256;
}
function requestLog(page) {
  const rows = [];
  page.on("request", request => {
    const url = new URL(request.url());
    let body = null;
    if (request.method() === "POST") { try { body = request.postDataJSON(); } catch { body = null; } }
    rows.push({ at: Date.now(), method: request.method(), path: url.pathname, search: url.search,
      api: url.pathname.startsWith("/api/"), tool: body?.tool ?? null, protocol: body?.protocol_id ?? null });
  });
  return rows;
}
const posts = (log, since, pattern) => log.filter(row => row.at >= since && row.method === "POST" &&
  (!pattern || pattern.test(row.path))).length;
const GA_POST = /\/sequence_ga\/|\/jobs$/;

// ------------------------------------------------------------------ evidence
function recorder(session, input, evidence) {
  const { app, page, artifacts } = session;
  const file = path.join(artifacts, `sequence-ga-${input.mode}.jsonl`);
  const append = row => fs.appendFileSync(file, JSON.stringify(row) + "\n");
  const caseRows = {};
  const mark = (cases, ok) => { for (const id of cases) (caseRows[id] ??= []).push(ok); };
  async function step(caseId, cases, description, action, check) {
    const started = Date.now();
    let result;
    try {
      result = await action();
      const assertion = await check(result);
      const proof = await capture(app, page, artifacts, caseId);
      assert.equal(proof.status.blockedRequests.length, 0, "renderer attempted a non-loopback request");
      assert.equal(proof.status.offscreen, true);
      append({ caseId, cases, status: "pass", description, assertion: summarize(assertion),
        blockedRequests: proof.status.blockedRequests.length, paintCount: proof.status.paintCount,
        screenshot: fileRecord(proof.screenshot), paint: fileRecord(proof.paint.path), durationMs: Date.now() - started });
      mark(cases, true);
      return result;
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* keep the primary failure */ }
      const html = await page.evaluate(() => document.querySelector('[data-testid="sequence-ga-panel"]')?.outerHTML
        .slice(0, 250000) ?? "").catch(() => null);
      if (html) fs.writeFileSync(path.join(artifacts, `${caseId}-failure.panel.html`), html);
      append({ caseId, cases, status: "fail", description, error: String(error.stack ?? error),
        actionResult: result === undefined ? null : summarize(result), screenshot: proof && fileRecord(proof.screenshot),
        paint: proof && fileRecord(proof.paint.path), durationMs: Date.now() - started });
      mark(cases, false);
      throw error;
    }
  }
  /** An independent part: a failure is recorded (its cases fail) and the mode continues with the next part. */
  async function part(name, cases, work) {
    try { return await work(); } catch (error) {
      append({ caseId: `${name}-aborted`, cases: [], partCases: cases, status: "fail", description: `part ${name} aborted`,
        error: String(error.stack ?? error) });
      evidence.partFailures.push({ part: name, cases, error: String(error).slice(0, 800) });
      mark(cases, false);
      return null;
    }
  }
  const cases = () => Object.fromEntries(Object.entries(caseRows).map(([id, list]) =>
    [id, list.length && list.every(Boolean) ? "pass" : "fail"]));
  return { step, part, append, file, cases, app, page, artifacts };
}
function summarize(value) {
  try { const text = JSON.stringify(value); return text.length > 8000 ? `${text.slice(0, 8000)}…` : JSON.parse(text); }
  catch { return String(value); }
}
/** Every control used at least once, with what was observed right after. */
function control(evidence, id, observed) { (evidence.controls[id] ??= []).push(observed); }

// ------------------------------------------------------------------ tabs, runs, structure screen (as mutation-model-flow.cjs)
const tabButton = (page, label) => page.locator(".mw-app-tabs").getByRole("tab", { name: label, exact: true });
async function selectTab(page, label) {
  await tabButton(page, label).click();
  await waitFor(page, async () => await tabButton(page, label).getAttribute("aria-selected") === "true", `${label} selected`, 10000);
}
const globalRun = page => page.evaluate(() => document.querySelector(".mw-app-run")?.getAttribute("data-global-run") || null);
const snapshot = page => page.evaluate(() => typeof window.__protviewQaSnapshot === "function" ? window.__protviewQaSnapshot() : null);
async function waitForBoot(page) {
  const hasRuns = (await readApi(page, "/runs")).length > 0;
  await page.waitForFunction(existing => {
    const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "새 run");
    const selected = new URL(location.href).searchParams.get("run");
    return !!button && !button.disabled && (existing ? /^run_/.test(selected ?? "")
      : document.body.textContent?.includes("현재 사용 불가"));
  }, hasRuns, { timeout: 45000 });
}
async function newRun(page) {
  await selectTab(page, "구조 분석");
  await waitForBoot(page);
  await page.getByRole("tab", { name: /^run/i }).click();
  const previous = new URL(page.url()).searchParams.get("run");
  await page.getByRole("button", { name: "새 run", exact: true }).click();
  await page.waitForFunction(old => {
    const current = new URL(location.href).searchParams.get("run");
    const button = [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === "새 run");
    return /^run_[a-f0-9]+$/.test(current ?? "") && current !== old && !!button && !button.disabled;
  }, previous, { timeout: 30000 });
  const run = new URL(page.url()).searchParams.get("run");
  await waitFor(page, async () => await globalRun(page) === run, "global run id", 10000);
  return run;
}
async function uploadLoad(page, file) {
  await page.getByRole("tab", { name: /^run/i }).click();
  const before = (await snapshot(page))?.sourceHandle ?? null;
  const chooser = page.waitForEvent("filechooser", { timeout: 30000 });
  await page.locator('input[type="file"]').first().click();
  await (await chooser).setFiles(file);
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).waitFor({ timeout: 30000 });
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    /\/commands$/.test(new URL(response.url()).pathname) && response.request().postDataJSON()?.tool === "load_structure",
  { timeout: 90000 });
  posted.catch(() => undefined); // a failed click must not leave an unhandled rejection
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).click();
  const loadArgs = (await posted).request().postDataJSON().args;
  const viewer = await waitForViewer(page, value => !!value.sourceHandle && value.sourceHandle !== before &&
    value.sourceHandle.includes("/structure/") && value.catalogReady === true, 90000);
  return { handle: viewer.sourceHandle, loadArgs: { model_index: loadArgs.model_index } };
}
async function prepareManual(page) {
  const back = page.getByRole("button", { name: "최신 구조로 돌아가기", exact: true });
  if (await back.isVisible().catch(() => false)) await back.click();
  const row = page.locator(".mw-workflow-row").filter({ has: page.getByRole("button", { name: "전처리", exact: true }) });
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    /\/commands$/.test(new URL(response.url()).pathname) && response.request().postDataJSON()?.tool === "prepare_structure",
  { timeout: 90000 });
  posted.catch(() => undefined); // a failed click must not leave an unhandled rejection
  await row.getByRole("button", { name: "전처리", exact: true }).click();
  const response = await posted;
  const body = await response.json();
  assert.equal(body.ok, true, `prepare failed: ${JSON.stringify(body).slice(0, 400)}`);
  const prepared = body.handle.handle;
  assert.match(prepared, /\/prepared_structure\//);
  await waitForViewer(page, value => value.sourceHandle === prepared && value.catalogReady === true, 90000);
  return { prepared, args: response.request().postDataJSON().args };
}

// ------------------------------------------------------------------ M20 candidate area (inputs)
const m20 = page => page.locator('#mw-app-panel-protein [data-testid="mutation-panel"]');
const m20Id = (page, id) => m20(page).locator(`[data-testid="${id}"]`);
async function m20Ready(page) {
  await waitFor(page, async () => await m20(page).locator('[data-mutation-area="sets"]').getAttribute("data-state") === "ready"
    && await m20(page).locator('[data-testid="mutation-structures"] input').first().isEnabled() ? true : null,
  "M20 lists ready", 60000);
}
async function chosenResidues(page, picker) {
  if (!await m20Id(page, `mutation-chosen-${picker}`).count()) return [];
  return m20Id(page, `mutation-chosen-${picker}`).locator("li[data-mutation-residue]").evaluateAll(items =>
    items.map(item => item.getAttribute("data-mutation-residue")));
}
async function pickerCount(page, picker) {
  return Number(await m20Id(page, `mutation-picker-${picker}`).getAttribute("data-count"));
}
/** Pick one residue in a picker (select + 넣기) by its displayed auth text (the option keeps the 7 fields). */
async function pickResidue(page, picker, resname, seq, evidence) {
  const select = m20Id(page, `mutation-pick-${picker}`);
  const option = await waitFor(page, async () => {
    const found = await select.locator("option").evaluateAll(items => items.map(item => ({ value: item.value,
      text: item.textContent.trim(), disabled: item.disabled })));
    const match = found.filter(item => item.text.startsWith(`${resname} A:${seq} ·`) && !item.disabled);
    return match.length === 1 ? match[0] : null;
  }, `${picker} option ${resname} ${seq}`, 60000);
  const before = await pickerCount(page, picker);
  await select.selectOption(option.value);
  await m20Id(page, `mutation-add-${picker}`).click();
  await waitFor(page, async () => await pickerCount(page, picker) === before + 1 ? true : null, `${picker} count +1`, 10000);
  control(evidence, `mutation-pick-${picker}`, { picked: option.text });
  control(evidence, `mutation-add-${picker}`, { count: before + 1 });
}
async function removeResidue(page, picker, text, evidence) {
  const before = await pickerCount(page, picker);
  await m20Id(page, `mutation-chosen-${picker}`).locator(`li${attr("data-mutation-residue", text)} ` +
    `[data-testid="mutation-remove-${picker}"]`).click();
  await waitFor(page, async () => await pickerCount(page, picker) === before - 1 ? true : null, `${picker} count -1`, 10000);
  control(evidence, `mutation-remove-${picker}`, { removed: text, count: before - 1 });
}
/** The M20 screen: the prepared structure, 직접 선택 + the residues, protection, allowed residues, 후보 만들기. */
async function m20Create(page, run, prepared, spec, evidence) {
  const structure = m20(page).locator(`label${attr("data-mutation-structure", prepared)} input`);
  if (!await structure.isChecked()) {
    await structure.check();
    control(evidence, "mutation-structures", { checked: prepared });
  }
  const user = m20Id(page, "mutation-source-user");
  if (!await user.isChecked()) {
    await user.click();
    control(evidence, "mutation-source-user", { checked: true });
  }
  for (const [picker, wanted] of [["user", spec.residues], ["protect", spec.protect]]) {
    const texts = wanted.map(([name, seq]) => `${name} A:${seq}`);
    for (const text of await chosenResidues(page, picker)) if (!texts.includes(text)) await removeResidue(page, picker, text, evidence);
    for (const [name, seq] of wanted)
      if (!(await chosenResidues(page, picker)).includes(`${name} A:${seq}`)) await pickResidue(page, picker, name, seq, evidence);
  }
  await m20Id(page, "mutation-allowed-none").click();
  control(evidence, "mutation-allowed-none", { clicked: true });
  for (const code of spec.allowed)
    await m20Id(page, "mutation-allowed").getByRole("checkbox", { name: `허용 잔기 ${code}`, exact: true }).check();
  control(evidence, "mutation-allowed", { checked: spec.allowed.join("") });
  await waitFor(page, async () => await m20Id(page, "mutation-create").isEnabled() ? true : null, "후보 만들기 enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === M20_TOOL,
  { timeout: 120000 });
  posted.catch(() => undefined); // a failed click must not leave an unhandled rejection
  await m20Id(page, "mutation-create").click();
  control(evidence, "mutation-create", { clicked: true });
  const response = await posted;
  const body = await response.json();
  assert.equal(body.ok, true, JSON.stringify(body).slice(0, 400));
  const handle = body.handle.handle;
  await m20(page).locator(`[data-testid="mutation-detail"]${attr("data-mutation-detail", handle)}`).waitFor({ timeout: 60000 });
  return { handle, args: response.request().postDataJSON().args };
}
/** Ligand 3D SDF import through the M18 docking area of the ligand tab (file chooser + 가져오기); the new handle. */
async function importLigandSdf(page, run, file, evidence) {
  await selectTab(page, LIGAND_TAB);
  const dock = page.locator('#mw-app-panel-ligand [data-testid="docking-panel"]');
  await dock.waitFor({ timeout: 15000 });
  const known = new Set((await readApi(page, `/runs/${run}/docking/prerequisites`)).imports.map(item => item.handle));
  const chooser = page.waitForEvent("filechooser", { timeout: 15000 });
  await dock.locator('[data-testid="docking-file-ligand"]').click();
  await (await chooser).setFiles(file);
  control(evidence, "docking-file-ligand", { file: path.basename(file) });
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/chemical/imports`, { timeout: 60000 });
  posted.catch(() => undefined); // a failed click must not leave an unhandled rejection
  await dock.locator('[data-testid="docking-import"]').click();
  control(evidence, "docking-import", { file: path.basename(file) });
  assert.equal((await posted).status(), 201);
  await dock.locator('[data-testid="docking-import-done"]').waitFor({ timeout: 60000 });
  const fresh = (await readApi(page, `/runs/${run}/docking/prerequisites`)).imports.filter(item => !known.has(item.handle));
  assert.equal(fresh.length, 1, JSON.stringify(fresh));
  assert.equal(fresh[0].input_kind, "ligand_sdf");
  return fresh[0].handle;
}

// ------------------------------------------------------------------ sequence GA area (real input; read-only helpers)
const seqPanel = page => page.locator('#mw-app-panel-protein [data-testid="sequence-ga-panel"]');
const st = (page, id) => seqPanel(page).locator(`[data-testid="${id}"]`);
const area = (page, name) => seqPanel(page).locator(`[data-sequence-ga-area="${name}"]`);
const gaState = page => seqPanel(page).getAttribute("data-ga-state", { timeout: 2000 }).catch(() => null);
async function openProteinTab(page) {
  await selectTab(page, TAB);
  await seqPanel(page).waitFor({ timeout: 15000 });
  return waitFor(page, async () => {
    const state = await gaState(page);
    if (state === "unavailable" || state === "failed") return state;
    if ((state === "ready" || state === "empty") &&
        await area(page, "results").getAttribute("data-state", { timeout: 1000 }).catch(() => null) === "ready") return state;
    return null;
  }, "sequence GA area settled", 90000);
}
async function gaText(page) { return seqPanel(page).evaluate(node => node.innerText); }
async function noControls(page) {
  return { state: await gaState(page), text: clean(await seqPanel(page).textContent()),
    controls: await seqPanel(page).locator("button, input, select, textarea, a, img, table").count() };
}
/** Forbidden words in the GA area, line by line: a fixed or stored sentence is exempt; the score names are removed. */
function forbiddenWords(text, exempt) {
  const found = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line || exempt.has(line)) continue;
    const checked = line.split(SCORE_LABEL).join("").split("qvina 점수(kcal/mol)").join("");
    for (const match of checked.matchAll(FORBIDDEN)) found.push({ word: match[0], line: line.slice(0, 200) });
  }
  return found;
}
async function fill(page, id, value) {
  const field = st(page, id);
  await field.click();
  await field.fill(String(value));
}
async function setParams(page, values, evidence) {
  for (const [key, value] of Object.entries(values)) {
    await fill(page, `sequence-ga-param-${key}`, value);
    control(evidence, `sequence-ga-param-${key}`, { value: String(value) });
  }
}
async function paramValues(page) {
  return Object.fromEntries(await Promise.all(GA_KEYS.map(async key =>
    [key, await st(page, `sequence-ga-param-${key}`).inputValue()])));
}
async function startState(page) {
  return { enabled: await st(page, "sequence-ga-start").isEnabled(),
    blocked: clean(await st(page, "sequence-ga-start-blocked").textContent({ timeout: 1000 }).catch(() => "")),
    preflightEnabled: await st(page, "sequence-ga-preflight").isEnabled() };
}
async function fieldErrors(page) {
  return Object.fromEntries((await Promise.all(GA_KEYS.map(async key => {
    const node = st(page, `sequence-ga-error-${key}`);
    return await node.count() ? [key, clean(await node.textContent())] : null;
  }))).filter(Boolean));
}
async function inputErrors(page) {
  if (!await st(page, "sequence-ga-input-errors").count()) return [];
  return (await st(page, "sequence-ga-input-errors").locator("li").allTextContents()).map(clean);
}
async function setChecked(page, locator, on, id, evidence) {
  if (await locator.isChecked() !== on) {
    await locator.setChecked(on);
    control(evidence, id, { checked: on });
  }
}
/** ① inputs: candidate set, 3D SDF, box, evaluation seed and docking values, the two confirmations, the three acks. */
async function chooseInputs(page, run, input, evidence) {
  const reread = page.waitForResponse(response => response.request().method() === "GET" &&
    new URL(response.url()).pathname === `/api/runs/${run}/docking/prerequisites`, { timeout: 30000 });
  reread.catch(() => undefined);
  await st(page, "sequence-ga-prereq-refresh").click();
  control(evidence, "sequence-ga-prereq-refresh", { clicked: true });
  await reread;
  await waitFor(page, async () => await st(page, "sequence-ga-candidate-set").locator(`option${attr("value", input.set)}`)
    .count() ? true : null, "candidate set offered", 30000);
  await st(page, "sequence-ga-candidate-set").selectOption(input.set);
  control(evidence, "sequence-ga-candidate-set", { handle: input.set });
  await setChecked(page, seqPanel(page).locator('label[data-pair-ligand-source="sdf"] input'), true,
    "sequence-ga-ligand-source", evidence);
  await waitFor(page, async () => await st(page, "sequence-ga-sdf").locator(`option${attr("value", input.sdf)}`).count()
    ? true : null, "SDF offered", 30000);
  await st(page, "sequence-ga-sdf").selectOption(input.sdf);
  control(evidence, "sequence-ga-sdf", { handle: input.sdf });
  await setChecked(page, seqPanel(page).locator(`label[data-pair-box="${input.box.source}"] input`), true,
    "sequence-ga-box-source", evidence);
  if (input.box.source === "ligand_range") {
    await fill(page, "sequence-ga-margin", input.box.margin);
    control(evidence, "sequence-ga-margin", { value: input.box.margin });
  } else {
    for (const [i, axis] of ["x", "y", "z"].entries()) {
      await fill(page, `sequence-ga-center-${axis}`, input.box.center[i]);
      await fill(page, `sequence-ga-size-${axis}`, input.box.size[i]);
    }
    control(evidence, "sequence-ga-manual-box", { center: input.box.center, size: input.box.size });
  }
  for (const [id, value] of [["sequence-ga-seed", input.seed], ["sequence-ga-exhaustiveness", input.exhaustiveness],
    ["sequence-ga-num-modes", input.numModes], ["sequence-ga-energy-range", input.energyRange]]) {
    await fill(page, id, value);
    control(evidence, id, { value });
  }
  await setChecked(page, st(page, "sequence-ga-confirm-selection"), true, "sequence-ga-confirm-selection", evidence);
  await setChecked(page, st(page, "sequence-ga-confirm-hydrogen"), true, "sequence-ga-confirm-hydrogen", evidence);
  for (const key of ACK_KEYS)
    await setChecked(page, seqPanel(page).locator(`label[data-pair-ack="${key}"] input`), true, `sequence-ga-ack-${key}`, evidence);
}
/** Click 시작 전 확인 보기; returns the server response (what the view shows), the request and the view's DOM. */
async function preflight(page, run, evidence) {
  await waitFor(page, async () => await st(page, "sequence-ga-preflight").isEnabled() ? true : null, "preflight enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/sequence_ga/preflight`, { timeout: 120000 });
  posted.catch(() => undefined);
  await st(page, "sequence-ga-preflight").click();
  const response = await posted;
  const body = await response.json();
  control(evidence, "sequence-ga-preflight", { status: response.status(), admitted: body.admission?.admitted,
    reason: body.admission?.reason_code ?? null });
  return { status: response.status(), body, request: response.request().postDataJSON(), view: await preflightView(page, body) };
}
const factLines = locator => locator.evaluateAll(items => items.map(item =>
  [item.querySelector("dt").textContent.trim(), item.querySelector("dd").textContent.trim()]));
async function preflightView(page, body) {
  if (!body.admission.admitted) {
    await st(page, "sequence-ga-preflight-refused").waitFor({ timeout: 30000 });
    return { refused: clean(await st(page, "sequence-ga-preflight-refused").textContent()),
      reasonCode: await st(page, "sequence-ga-preflight-refused").getAttribute("data-reason-code"),
      preflightView: await st(page, "sequence-ga-preflight-view").count(), start: await startState(page),
      spaceLines: Object.fromEntries(await factLines(st(page, "sequence-ga-space").locator("[data-line]"))) };
  }
  const view = st(page, "sequence-ga-preflight-view");
  await waitFor(page, async () => await view.count() &&
    await view.getAttribute("data-reserved-units") === String(body.reserved_units) &&
    await view.getAttribute("data-shortfall-calls") === String(body.shortfall.expensive_calls) ? true : null,
  "preflight view", 30000);
  const data = Object.fromEntries(await Promise.all(["data-reserved-units", "data-reserved-evaluations", "data-reusable",
    "data-reference-reusable", "data-shortfall-calls", "data-shortfall-wall", "data-may-be-partial",
    "data-heavy-atom-warning", "data-space-size"].map(async name => [name, await view.getAttribute(name)])));
  return { data,
    lines: Object.fromEntries(await factLines(view.locator("[data-preflight-line]"))),
    statements: await st(page, "sequence-ga-preflight-statements").locator("li[data-statement]").evaluateAll(items =>
      items.map(item => ({ id: item.getAttribute("data-statement"), text: item.textContent.trim() }))).catch(() => []),
    existingJob: await st(page, "sequence-ga-existing-job").getAttribute("data-job-id", { timeout: 1000 }).catch(() => null),
    existingText: clean(await st(page, "sequence-ga-existing-job").textContent({ timeout: 1000 }).catch(() => "")),
    approvalButtons: await st(page, "sequence-ga-limit-approve").count(),
    spaceLines: Object.fromEntries(await factLines(st(page, "sequence-ga-space").locator("[data-line]"))),
    spaceAttr: { size: await st(page, "sequence-ga-space").getAttribute("data-space-size"),
      effective: await st(page, "sequence-ga-space").getAttribute("data-effective-max-mutations") },
    start: await startState(page) };
}
/** The displayed preflight equals the server numbers, and the server numbers equal the spec 7 arithmetic. */
function preflightMatches(pf, { gaValues, space, reusable, referenceReusable, budget }) {
  const body = pf.body, view = pf.view;
  const want = needFor(gaValues);
  assert.equal(pf.status, 200);
  assert.equal(body.admission.admitted, true, JSON.stringify(body.admission));
  assert.equal(body.starts_job, false);
  assert.deepEqual(body.ga, gaValues, "the preflight's effective parameters differ from the typed values");
  assert.deepEqual(body.space, space, "the preflight space differs from the hand-counted space");
  assert.equal(body.reserved_evaluations, want.reservedEvaluations, "reserved_evaluations differs from spec 7");
  assert.equal(body.reserved_units, want.units, "reserved_units differs from spec 7 (2 × (reserved_evaluations + 1))");
  assert.deepEqual(body.needed, want.needed, "needed differs from spec 7 arithmetic");
  assert.deepEqual(body.shortfall, shortfallFor(body.needed, body.remaining), "shortfall differs from needed − remaining");
  assert.equal(body.full_run_may_be_partial, want.mayBePartial);
  if (reusable !== undefined) assert.equal(body.reusable_count, reusable);
  if (referenceReusable !== undefined) assert.equal(body.reference_reusable, referenceReusable);
  if (budget) {
    assert.equal(body.remaining.expensive_calls, budget.expensive_calls.limit - budget.expensive_calls.used);
    assert.ok(body.remaining.wall_clock_s <= budget.wall_clock_s.limit - budget.wall_clock_s.used + 1e-6);
  }
  assert.deepEqual(body.statements, ["S1", "S4", "S5", "S6"].map(id => ({ id, text: S[id] })),
    "preflight statements are not S1, S4, S5, S6 verbatim");
  // 4,890 warning: the server's flag over its projected heavy-atom count (1UBQ: 602, no warning line)
  assert.equal(typeof body.projection_heavy_atoms, "number");
  assert.equal(body.heavy_atom_warning, body.projection_heavy_atoms > M18_HEAVY_ATOM_ESTIMATE);
  assert.equal(view.data["data-heavy-atom-warning"], String(body.heavy_atom_warning));
  assert.equal("중원자 경고" in view.lines, body.heavy_atom_warning, "the 4,890 warning line follows the server flag");
  assert.equal(view.lines["투영 단백질 중원자"], `${count(body.projection_heavy_atoms)}개`);
  assert.equal(view.data["data-reserved-units"], String(body.reserved_units));
  assert.equal(view.data["data-reserved-evaluations"], String(body.reserved_evaluations));
  assert.equal(view.data["data-reusable"], String(body.reusable_count));
  assert.equal(view.data["data-reference-reusable"], String(body.reference_reusable));
  assert.equal(view.data["data-shortfall-calls"], String(body.shortfall.expensive_calls));
  assert.equal(view.data["data-shortfall-wall"], String(body.shortfall.wall_clock_s));
  assert.equal(view.data["data-may-be-partial"], String(body.full_run_may_be_partial));
  assert.equal(view.data["data-space-size"], String(body.space.size));
  const spaceLine = `위치 ${count(body.space.positions)}개 · 후보 ${count(body.space.candidates)}개 · 조합 ` +
    `${count(body.space.size)}개 (서버 계산)`;
  const capLine = `${body.space.effective_max_mutations}개 (입력 ${body.ga.max_mutations}개, 서버 값)`;
  assert.equal(view.lines["조합 공간"], spaceLine);
  assert.equal(view.lines["유효 동시 변이 수 상한"], capLine);
  assert.deepEqual(view.spaceLines, { "조합 공간": spaceLine, "유효 동시 변이 수 상한": capLine },
    "the parameter area's space lines are not the server's");
  assert.deepEqual(view.spaceAttr, { size: String(body.space.size), effective: String(body.space.effective_max_mutations) });
  assert.ok(view.lines["재사용 가능 개체"].startsWith(`${body.reusable_count}개 (`), view.lines["재사용 가능 개체"]);
  assert.ok(view.lines["야생형 기준 행"].startsWith(body.reference_reusable ? "저장된 결과를 재사용" : "새로 평가"),
    view.lines["야생형 기준 행"]);
  assert.equal(view.lines["예약 단위"], `${body.reserved_units}단위 (새 평가 최대 ${body.reserved_evaluations}건 × 2단위 + ` +
    "야생형 기준 행 2단위)");
  assert.equal(view.lines["예상 시간 상한"], seconds(body.needed.wall_clock_s));
  assert.equal(view.lines["필요"], `${pairText(body.needed)} (최대)`);
  assert.equal(view.lines["현재 잔여"], pairText(body.remaining));
  assert.equal(view.lines["부족분"], pairText(body.shortfall));
  assert.equal(view.lines["과금"], `시작하면 ${body.reserved_units}단위가 예약·소진되고 중간에 멈추거나 재사용이 있어도 돌려받지 않음`);
  assert.ok(view.lines["대기"]?.includes("기다립니다"), view.lines["대기"]);
  assert.equal("시간 상한" in view.lines, body.full_run_may_be_partial);
  if (body.full_run_may_be_partial) assert.ok(view.lines["시간 상한"].startsWith(MAY_BE_PARTIAL), view.lines["시간 상한"]);
  assert.deepEqual(view.statements, ["S1", "S4", "S5", "S6"].map(id => ({ id, text: S[id] })),
    "the shown preflight statements are not S1, S4, S5, S6 verbatim");
  const shortfall = body.shortfall.expensive_calls > 0 || body.shortfall.wall_clock_s > 0;
  assert.equal(view.approvalButtons, shortfall ? 1 : 0, "limit approval shown iff shortfall > 0");
  assert.equal(view.start.enabled, !shortfall, `start ${view.start.enabled} with shortfall ${JSON.stringify(body.shortfall)}`);
  if (shortfall) assert.ok(view.start.blocked.includes("(ga_limit_raise_required)"), view.start.blocked);
  return { reservedEvaluations: body.reserved_evaluations, reserved: body.reserved_units, needed: body.needed,
    remaining: body.remaining, shortfall: body.shortfall, mayBePartial: body.full_run_may_be_partial,
    reusable: body.reusable_count, referenceReusable: body.reference_reusable, heavyAtoms: body.projection_heavy_atoms,
    heavyAtomWarning: body.heavy_atom_warning, existingJob: body.existing_job };
}
/** Click the screen's limit approval button (a person's click); the area reads the preflight again itself. */
async function approveLimits(page, run, pf, evidence) {
  const budget = await readApi(page, `/runs/${run}/budget`);
  const eventsBefore = (await runEvents(page, run)).length;
  const jobsBefore = (await readApi(page, `/runs/${run}/jobs`)).length;
  const approval = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/sequence_ga/limit_approval`, { timeout: 60000 });
  const reread = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/sequence_ga/preflight`, { timeout: 120000 });
  approval.catch(() => undefined);
  reread.catch(() => undefined);
  await st(page, "sequence-ga-limit-approve").click();
  control(evidence, "sequence-ga-limit-approve", { clicked: true });
  const approvedResponse = await approval;
  const approved = await approvedResponse.json();
  const again = await (await reread).json();
  await st(page, "sequence-ga-limit-done").waitFor({ timeout: 30000 });
  const view = await preflightView(page, again);
  await page.waitForTimeout(500);
  return { budget, approved, status: approvedResponse.status(), approvalRequest: approvedResponse.request().postDataJSON(),
    again, view, events: (await runEvents(page, run)).slice(eventsBefore),
    done: clean(await st(page, "sequence-ga-limit-done").textContent()),
    raisedAttr: await st(page, "sequence-ga-limit-done").getAttribute("data-raised"),
    budgetAfter: await readApi(page, `/runs/${run}/budget`), jobsBefore,
    jobsAfter: (await readApi(page, `/runs/${run}/jobs`)).length, jobShown: await st(page, "sequence-ga-job").count(), pf };
}
function approvalMatches(value) {
  const { pf, approved, budget, budgetAfter, events } = value;
  const shortfall = pf.body.shortfall;
  assert.equal(value.status, 200);
  assert.equal(approved.raised, true);
  // the server raises by the shortfall it sees at the click; the wall axis carries the 60 s margin (spec 7)
  assert.equal(approved.increase.expensive_calls, shortfall.expensive_calls, "the raise is not the unit shortfall");
  assert.ok(approved.increase.wall_clock_s >= shortfall.wall_clock_s, "the wall raise is below the shortfall");
  assert.deepEqual(value.approvalRequest, pf.request, "the approval body is not the previewed GA arguments");
  assert.equal(approved.limits_after.expensive_calls, budget.expensive_calls.limit + shortfall.expensive_calls);
  assert.equal(budgetAfter.expensive_calls.limit, budget.expensive_calls.limit + shortfall.expensive_calls);
  assert.equal(budgetAfter.expensive_calls.used, budget.expensive_calls.used, "the approval used budget");
  const updated = events.filter(event => event.type === "budget_limit_updated");
  assert.equal(updated.length, 1, JSON.stringify(events.map(event => event.type)));
  assert.equal(updated[0].by, "human");
  assert.equal(updated[0].context.purpose, "sequence_ga_limit_raise");
  assert.equal(updated[0].context.selection_sha256, pf.body.selection_sha256);
  assert.equal(updated[0].context.reserved_units, pf.body.reserved_units);
  assert.deepEqual(updated[0].context.increase, approved.increase);
  assert.ok(!events.some(event => event.type.startsWith("job_") || event.type === "object_created"),
    "the approval created a job or an object");
  assert.equal(value.jobsAfter, value.jobsBefore, "the approval submitted a job");
  assert.equal(value.raisedAttr, "true");
  assert.ok(value.done.includes("되돌리지 않음"), value.done);
  assert.deepEqual(value.again.shortfall, { expensive_calls: 0, wall_clock_s: 0 });
  assert.equal(value.view.approvalButtons, 0, "approval still offered without a shortfall");
  assert.equal(value.view.start.enabled, true, value.view.start.blocked);
  return { shortfall, increase: approved.increase, limitsBefore: approved.limits_before, limitsAfter: approved.limits_after,
    event: updated[0].seq, jobAreasAfter: value.jobShown, jobsCreated: value.jobsAfter - value.jobsBefore };
}
async function jobPhase(page) {
  const job = st(page, "sequence-ga-job");
  if (!await job.count()) return null;
  return { phase: await job.getAttribute("data-ga-job-phase"), status: await job.getAttribute("data-ga-job-status"),
    id: await job.getAttribute("data-ga-job-id"), reference: await job.getAttribute("data-reference-recorded"),
    generations: Number(await job.getAttribute("data-generations-complete") ?? NaN),
    finished: Number(await job.getAttribute("data-individuals-finished") ?? NaN),
    progress: clean(await st(page, "sequence-ga-progress").textContent({ timeout: 500 }).catch(() => "")) };
}
/** The progress line written independently from the stored job record's `sequence_ga` counts. */
function progressText(p) {
  return `야생형 기준 행 ${p.reference_recorded ? "기록됨" : "아직 기록 없음"}(${p.reference_reuse_planned ? "재사용 예정" : "새 평가"})` +
    ` · 완료한 세대 ${p.generations_complete}개(세대 기록 ${p.generation_records}개) · 새 평가 시작 ${p.individuals_started}건` +
    ` · 새 평가 끝 ${p.individuals_finished}건 · 재사용 가능 개체 ${p.reused_planned}개(파일이 없어 새 평가 수에 들지 않음)` +
    ` · 예약 ${p.reserved_units}단위`;
}
/**
 * Click 서열 GA 시작 (real input); approve through 비싼 계산 승인 when asked, then 작업 시작; while running, compare the
 * progress line with the stored job record (`progress: true`); stop when `until(phase)` holds or the job ends.
 */
async function runGa(page, run, evidence, { until = null, timeout = 1500000, progress = false } = {}) {
  const phases = [], progressSeen = [], attributesSeen = [];
  const before = await budgetUsed(page, run);
  const previousJob = (await jobPhase(page))?.id ?? null;
  const jobsBefore = (await readApi(page, `/runs/${run}/jobs`)).length;
  await waitFor(page, async () => (await startState(page)).enabled ? true : null, "start enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/jobs`, { timeout: 120000 });
  posted.catch(() => undefined);
  await st(page, "sequence-ga-start").click();
  control(evidence, "sequence-ga-start", { clicked: true });
  const response = await posted;
  const request = response.request().postDataJSON();
  const settled = async () => {
    const value = await jobPhase(page);
    if (!value || value.id === previousJob) return null;
    if (["running", "done", "failed", "cancelled"].includes(value.phase)) return value;
    if (value.phase === "awaiting_approval" && await enabled(st(page, "sequence-ga-job-approve"))) return value;
    if (value.phase === "saved" && await enabled(st(page, "sequence-ga-job-start"))) return value;
    return null;
  };
  const first = await waitFor(page, settled, "GA job submitted", 120000);
  phases.push(first.phase);
  let approved = false;
  if (first.phase === "awaiting_approval") {
    await st(page, "sequence-ga-job-approve").click();
    approved = true;
    control(evidence, "sequence-ga-job-approve", { clicked: true });
    await waitFor(page, async () => (await settled())?.phase === "saved" ? true : null, "approval recorded", 30000);
    phases.push("saved");
  }
  if ((await jobPhase(page)).phase === "saved" && await enabled(st(page, "sequence-ga-job-start"))) {
    await st(page, "sequence-ga-job-start").click();
    control(evidence, "sequence-ga-job-start", { clicked: true });
  }
  const stop = until ?? (value => ["done", "failed", "cancelled"].includes(value.phase));
  const done = await waitFor(page, async () => {
    const value = await jobPhase(page);
    if (value && value.phase !== phases.at(-1)) phases.push(value.phase);
    if (progress && value?.phase === "running" && value.finished >= 1 && progressSeen.length < 3) {
      const record = await readApi(page, `/runs/${run}/jobs/${enc(value.id)}`);
      const shown = await jobPhase(page);
      const p = record.sequence_ga;
      if (record.status === "running" && p && shown?.progress === progressText(p) &&
          shown.reference === String(p.reference_recorded) && shown.finished === p.individuals_finished &&
          shown.generations === p.generations_complete && !progressSeen.some(item => item.text === shown.progress))
        progressSeen.push({ text: shown.progress, record: p });
      if (p) attributesSeen.push({ reference: shown?.reference, finished: shown?.finished, recordReference: p.reference_recorded });
    }
    return value && stop(value) ? value : null;
  }, "GA job", timeout);
  const job = await readApi(page, `/runs/${run}/jobs/${enc(done.id)}`);
  return { phases, approved, request, job, phase: done, handle: job.sequence_ga?.summary_handle ?? null,
    budgetBefore: before, budgetAfter: await budgetUsed(page, run), jobsBefore,
    jobsAfter: (await readApi(page, `/runs/${run}/jobs`)).length, progressSeen, attributesSeen: attributesSeen.slice(-3),
    notice: clean(await st(page, "sequence-ga-notice").textContent({ timeout: 1000 }).catch(() => "")) };
}
/** Choose a stored summary in ⑤ (radio); returns the opened result header read from the DOM. */
async function openSummary(page, handle, evidence) {
  await waitFor(page, async () => await enabled(seqPanel(page).locator(`label${attr("data-ga-summary", handle)} input`))
    ? true : null, "summary listed", 60000);
  await seqPanel(page).locator(`label${attr("data-ga-summary", handle)} input`).check();
  control(evidence, "sequence-ga-summary-radio", { handle });
  await st(page, "sequence-ga-result").and(seqPanel(page).locator(attr("data-ga-handle", handle))).waitFor({ timeout: 60000 });
  return resultHeader(page);
}
async function resultHeader(page) {
  const view = st(page, "sequence-ga-result");
  return { handle: await view.getAttribute("data-ga-handle"), status: await view.getAttribute("data-ga-status"),
    stopReason: await view.getAttribute("data-stop-reason"), generationsDone: await view.getAttribute("data-generations-done"),
    statusText: clean(await st(page, "sequence-ga-status").textContent()),
    statements: await st(page, "sequence-ga-statements").locator("li").evaluateAll(items => items.map(item =>
      ({ id: item.getAttribute("data-statement"), text: item.textContent.trim() }))),
    summaryLines: Object.fromEntries(await factLines(st(page, "sequence-ga-summary").locator("[data-line]"))),
    tabs: await st(page, "sequence-ga-generation-tabs").locator('[role="tab"]').evaluateAll(items => items.map(item => ({
      id: item.getAttribute("data-testid"), complete: item.getAttribute("data-complete"), text: item.textContent.trim(),
      selected: item.getAttribute("aria-selected") }))).catch(() => []),
    noGenerations: await st(page, "sequence-ga-no-generations").count(),
    reference: await st(page, "sequence-ga-reference").evaluate(node => ({ state: node.getAttribute("data-state"),
      evaluation: node.getAttribute("data-evaluation"), inTable: !!node.closest("table"),
      title: node.querySelector(".mw-eyebrow")?.textContent.trim() ?? null,
      lines: Object.fromEntries([...node.querySelectorAll("dl > div")].map(item =>
        [item.querySelector("dt").textContent.trim(), item.querySelector("dd").textContent.trim()])) })) };
}
async function generationTable(page) {
  const panel = st(page, "sequence-ga-generation-panel");
  const table = st(page, "sequence-ga-individuals");
  return {
    generation: Number(await panel.getAttribute("data-generation")),
    range: clean(await st(page, "sequence-ga-generation-range").textContent()),
    caption: clean(await table.locator("caption").textContent()),
    headers: (await table.locator("thead th").allTextContents()).map(clean),
    aria: await table.locator("thead th").evaluateAll(items => items.map(item => item.getAttribute("aria-sort"))),
    rows: await table.locator("tbody tr").evaluateAll(items => items.map(item => {
      const t = value => (value ?? "").replace(/\s+/g, " ").trim();
      const cells = [...item.querySelectorAll(":scope > td")];
      const details = cells[2]?.querySelector("details") ?? null;
      return { position: Number(item.getAttribute("data-position")), key: item.getAttribute("data-key"),
        origin: item.getAttribute("data-origin"), evaluation: item.getAttribute("data-evaluation"),
        state: item.getAttribute("data-state"), cells: cells.map(cell => t(cell.textContent)),
        mutationSummary: t(details?.querySelector("summary")?.textContent),
        mutationLines: [...(details?.querySelectorAll("li") ?? [])].map(li => t(li.textContent)),
        detailsId: details?.getAttribute("data-testid") ?? null,
        scoreCell: t(item.querySelector("[data-score-cell]")?.textContent), referenceRow: item.getAttribute("data-key") === "wild_type" };
    })),
  };
}
async function showGeneration(page, index, evidence) {
  await st(page, `sequence-ga-generation-${index}`).click();
  control(evidence, "sequence-ga-generation-tab", { index });
  await waitFor(page, async () => await st(page, "sequence-ga-generation-panel").getAttribute("data-generation") === String(index)
    ? true : null, `generation ${index} shown`, 15000);
  return generationTable(page);
}
/** The mutations the server must have filled from the stored candidate set (7 fields as stored), in structure order. */
function setMutations(setContent, key) {
  return key.split("-").map(Number).map(index => {
    const candidate = setContent.candidates.find(item => item.index === index);
    assert.ok(candidate, `candidate ${index} not in the set`);
    const position = setContent.positions.find(item => item.index === candidate.position_index);
    return { candidate_index: index, residue: position.residue, from: candidate.from, to: candidate.to };
  });
}
/**
 * The opened summary equals the stored object and the stored rules: statements, status, stop reason, reference row
 * (apart), every generation tab and every row (mutations from the set, origin, parents, evaluation, state, score = the
 * stored M18 result's first mode, ROUND_HALF_UP), carried = previous generation's score order, min/max as values only.
 */
async function resultEquals(page, ctx, header, detail, stored, evidence) {
  const { runsDir, run, setContent } = ctx;
  assert.equal(header.handle, detail.handle);
  assert.deepEqual(detail.summary, stored, "detail summary differs from the stored object");
  assert.equal(header.status, stored.status);
  assert.equal(header.stopReason, stored.stop_reason);
  assert.equal(header.generationsDone, String(stored.generations_done));
  assert.equal(STOP_STATUS[stored.stop_reason], stored.status, "stop reason and status disagree");
  assert.ok(header.statusText.startsWith(`서열 GA 상태: `) && header.statusText.includes(`(${stored.status}) · 종료 이유: `),
    header.statusText);
  assert.ok(header.statusText.endsWith(`(${stored.stop_reason})`), header.statusText);
  if (stored.stop_reason === "no_change") assert.ok(header.statusText.includes(NO_CHANGE_LABEL), header.statusText);
  const evaluated = stored.generations.flatMap(gen => gen.individuals).filter(item => item.origin !== "carried");
  const reused = evaluated.filter(item => item.evaluation === "reused").length;
  const computed = evaluated.filter(item => item.evaluation === "computed").length;
  assert.equal(stored.reused_count, reused);
  assert.equal(stored.new_evaluations_used, computed);
  const want = statementIds(stored);
  assert.deepEqual(stored.limitations, want, "stored S sentence ids differ from the spec 4 rule");
  assert.deepEqual(header.statements, want.map(id => ({ id, text: S[id] })), "shown S sentences differ from spec 4");
  assert.deepEqual(detail.statements, want.map(id => ({ id, text: S[id] })));
  const need = needFor(stored.ga);
  assert.equal(stored.reserved_evaluations, need.reservedEvaluations);
  assert.equal(stored.reserved_units, need.units);
  assert.ok(stored.new_evaluations_used <= stored.reserved_evaluations);
  if (stored.stop_reason === "evaluation_limit") assert.equal(stored.new_evaluations_used, stored.reserved_evaluations);
  assert.equal(header.summaryLines["완료한 세대"], `${stored.generations_done}개`);
  assert.equal(header.summaryLines["새 평가"], `${stored.new_evaluations_used}건 (예약 ${stored.reserved_evaluations}건 · ` +
    `${stored.reserved_units}단위)`);
  assert.equal(header.summaryLines["재사용"], `${stored.reused_count}개 (과금하지 않음)`);
  assert.equal(header.summaryLines["조합 공간"], `위치 ${count(stored.space.positions)}개 · 후보 ${count(stored.space.candidates)}개` +
    ` · 조합 ${count(stored.space.size)}개 · 유효 동시 변이 수 상한 ${stored.space.effective_max_mutations}개`);
  assert.equal(header.summaryLines["평가 seed"], String(stored.parameters.seed));
  assert.equal(header.summaryLines["후보 집합"], stored.candidate_set);
  // the wild-type reference row: apart from the individuals table, values only
  const ref = stored.reference;
  assert.equal(header.reference.inTable, false, "the reference row is inside the individuals table");
  assert.equal(header.reference.title, "야생형 기준(참고)");
  assert.equal(header.reference.state, ref.state);
  assert.equal(header.reference.evaluation, ref.evaluation);
  assert.equal(header.reference.lines["키"], "wild_type");
  assert.equal(header.reference.lines[SCORE_HEADER], ref.state === "scored" ? halfUp(ref.score, 1) : "—");
  assert.ok(header.reference.lines["상태"].endsWith(`(${ref.state})`));
  if (ref.reason_code) assert.ok(header.reference.lines["이유"].endsWith(`(${ref.reason_code})`), header.reference.lines["이유"]);
  else assert.equal(header.reference.lines["이유"], "해당 없음");
  if (ref.state === "scored") {
    const result = storedObject(runsDir, run, ref.result_handle);
    assert.equal(ref.score, result.modes[0].score_kcal_mol, "reference score is not the stored first mode");
    assert.deepEqual(result.inputs.receptor.source, { kind: "mutation_model", mutation_model: ref.model_handle,
      side: "wild_type_reference" });
  } else assert.equal(ref.score, null);
  assert.equal(detail.reference.detail_available, ref.result_handle !== null);
  assert.equal(header.tabs.length, stored.generations.length);
  assert.equal(header.noGenerations, stored.generations.length ? 0 : 1);
  const seen = new Map(), evalIndices = [], tables = [];
  let previous = null;
  for (const [g, gen] of stored.generations.entries()) {
    const tab = header.tabs.find(item => item.id === `sequence-ga-generation-${gen.index}`);
    assert.ok(tab, `no tab for generation ${gen.index}`);
    assert.equal(tab.complete, String(gen.complete));
    assert.ok(tab.text === `세대 ${gen.index}` || (!gen.complete && tab.text.startsWith(`세대 ${gen.index} (`)), tab.text);
    assert.equal(tab.text === `세대 ${gen.index}`, gen.complete, tab.text);
    const table = await showGeneration(page, gen.index, evidence);
    assert.equal(table.caption, SCORE_LABEL);
    assert.deepEqual(table.headers, ["자리", "개체 키", "변이 (구조 순서)", "출처", "부모", "평가", "상태", SCORE_HEADER, "이유", "상세"]);
    assert.ok(!table.headers.some(text => /순위|rank|차이|대비/i.test(text)), "a rank or difference column is shown");
    assert.ok(gen.individuals.length <= stored.ga.population_size);
    assert.equal(table.rows.length, gen.individuals.length);
    assert.ok(!table.rows.some(row => row.referenceRow), "the reference row is in the individuals table");
    assert.deepEqual(table.rows.map(row => row.position), sortOracle(gen.individuals.map((item, position) =>
      ({ ...item, position })), null, null).map(row => row.position), "default order: rows without a score are not last");
    const scores = gen.individuals.filter(item => item.state === "scored").map(item => item.score);
    assert.equal(gen.min_score, scores.length ? Math.min(...scores) : null, "stored min_score is not the generation minimum");
    assert.equal(gen.max_score, scores.length ? Math.max(...scores) : null, "stored max_score is not the generation maximum");
    assert.equal(table.range, scores.length ? `점수 최솟값 ${halfUp(gen.min_score, 1)} · 점수 최댓값 ${halfUp(gen.max_score, 1)} ` +
      "(kcal/mol)" : "이 세대에 점수 있는 개체 없음");
    assert.equal(detail.generations[g].min_score, gen.min_score);
    // carried rule (spec 3, 4): the previous generation's scored individuals in score order, first elite_count
    const carried = gen.individuals.filter(item => item.origin === "carried");
    if (previous === null) assert.ok(gen.individuals.every(item => item.origin === "initial"));
    else {
      const order = previous.individuals.filter(item => item.state === "scored").sort(scoreOrder);
      assert.deepEqual(carried.map(item => item.key), order.slice(0, stored.ga.elite_count).map(item => item.key),
        "carried individuals are not the previous generation's first in score order");
      assert.deepEqual(gen.individuals.slice(0, carried.length).map(item => item.origin), carried.map(() => "carried"),
        "carried individuals are not first");
    }
    gen.individuals.forEach((item, position) => {
      const row = table.rows.find(entry => entry.position === position);
      assert.ok(row, `generation ${gen.index} position ${position} not shown`);
      const d = detail.generations[g].individuals[position];
      assert.equal(row.key, item.key);
      assert.equal(row.origin, item.origin);
      assert.equal(row.evaluation, item.evaluation ?? "carried");
      assert.equal(row.state, item.state);
      // mutations: the server filled them from the stored candidate set (indices of the key, 7 fields as stored)
      assert.deepEqual(item.mutations, setMutations(setContent, item.key), `${item.key}: mutations differ from the set`);
      assert.equal(item.mutations.map(m => m.candidate_index).join("-"), item.key);
      assert.ok(item.mutations.length >= 1 && item.mutations.length <= stored.space.effective_max_mutations);
      assert.equal(new Set(item.mutations.map(m => JSON.stringify(m.residue))).size, item.mutations.length,
        "two mutations at one position");
      assert.equal(row.cells[0], String(position + 1));
      assert.equal(row.cells[1], item.key);
      assert.equal(row.mutationSummary, item.mutations.map(mutText).join(", "));
      assert.deepEqual(row.mutationLines, item.mutations.map(m => `후보 번호 ${m.candidate_index} · ${mutText(m)} · ` +
        fieldsText(m.residue)));
      assert.ok(item.origin === "edit" ? row.cells[3].startsWith(`${ORIGIN_LABEL.edit}(`) : row.cells[3] === ORIGIN_LABEL[item.origin],
        row.cells[3]);
      assert.equal(row.cells[4], item.parents?.length ? `부모 ${item.parents.join(" · ")}` : "");
      assert.equal(item.origin === "edit", item.edit_op !== null);
      if (item.origin === "crossover") assert.equal(item.parents.length, 2);
      if (item.origin === "edit") assert.equal(item.parents.length, 1);
      if (["initial", "random", "carried"].includes(item.origin)) assert.equal(item.parents, null);
      for (const parent of item.parents ?? [])
        assert.ok(previous.individuals.some(entry => entry.key === parent && entry.state === "scored"),
          `${item.key}: parent ${parent} is not a scored individual of the previous generation`);
      assert.ok(row.cells[6].endsWith(`(${item.state})`), row.cells[6]);
      if (item.reason_code) assert.ok(row.cells[8].endsWith(`(${item.reason_code})`), row.cells[8]);
      else assert.equal(row.cells[8], "");
      assert.equal(row.cells[9], "개체 상세");
      assert.equal(d.detail_available, item.result_handle !== null);
      if (item.origin === "carried") {
        const first = seen.get(item.key);
        assert.ok(first, "a carried individual not evaluated before");
        for (const key of ["pick_index", "model_handle", "result_handle", "score", "state"]) assert.equal(item[key], first[key], key);
        assert.equal(item.evaluation, null);
        assert.equal(item.eval_index, null);
        assert.ok(row.cells[5].includes("이전 세대 결과 인용"), row.cells[5]);
      } else {
        assert.ok(!seen.has(item.key), `key ${item.key} evaluated twice in one run`);
        seen.set(item.key, item);
        if (item.evaluation === "computed") evalIndices.push(item.eval_index);
        else assert.equal(item.eval_index, null);
        assert.equal(row.cells[5], item.evaluation === "reused" ? "재사용" : "계산");
      }
      if (item.state === "scored") {
        const result = storedObject(runsDir, run, item.result_handle);
        assert.equal(item.score, result.modes[0].score_kcal_mol, "individual score is not the stored first mode");
        assert.deepEqual(result.inputs.receptor.source, { kind: "mutation_model", mutation_model: item.model_handle,
          side: "mutant" });
        assert.equal(result.inputs.mode, "free");
        assert.equal(result.inputs.ligand.source, "sdf");
        assert.deepEqual(result.box, stored.box);
        for (const key of ["seed", "exhaustiveness", "num_modes", "energy_range"])
          assert.equal(result.parameters[key], stored.parameters[key], key);
        assert.equal(row.cells[7], halfUp(item.score, 1));
        assert.equal(row.scoreCell, halfUp(item.score, 1));
      } else {
        assert.equal(item.score, null);
        assert.equal(row.scoreCell, "—", "a row without a score shows a value");
        assert.ok(!/\d/.test(row.scoreCell));
      }
    });
    tables.push({ generation: gen.index, complete: gen.complete, range: table.range, rows: gen.individuals.map(item =>
      ({ key: item.key, origin: item.origin, edit_op: item.edit_op, parents: item.parents, evaluation: item.evaluation,
        state: item.state, score: item.score })) });
    previous = gen;
  }
  assert.deepEqual([...evalIndices].sort((a, b) => a - b), evalIndices.map((_, i) => i), "eval_index is not 0..n-1");
  assert.deepEqual(evalIndices, [...evalIndices].sort((a, b) => a - b), "eval_index is not in evaluation order");
  return { status: stored.status, stopReason: stored.stop_reason, generationsDone: stored.generations_done,
    newEvaluations: stored.new_evaluations_used, reused: stored.reused_count, reserved: stored.reserved_units,
    statements: want, reference: { state: ref.state, score: ref.score, reason: ref.reason_code }, tables };
}
/** Click the slot, key and score headers twice each on the shown generation: the order follows the oracle. */
async function sortChecks(page, gen, evidence) {
  const seen = [];
  const rows = gen.individuals.map((item, position) => ({ ...item, position }));
  for (const key of ["score", "key", "slot"]) {
    for (const direction of ["asc", "desc"]) {
      await st(page, `sequence-ga-sort-${key}`).click();
      control(evidence, `sequence-ga-sort-${key}`, { direction });
      const want = sortOracle(rows, key, direction).map(row => row.position);
      const table = await waitFor(page, async () => {
        const value = await generationTable(page);
        return JSON.stringify(value.rows.map(row => row.position)) === JSON.stringify(want) ? value : null;
      }, `sort ${key} ${direction}`, 10000);
      const column = { slot: 0, key: 1, score: 7 }[key];
      assert.equal(table.aria[column], direction === "asc" ? "ascending" : "descending");
      seen.push({ key, direction, order: want });
    }
  }
  return seen;
}
async function individualView(page) {
  return st(page, "sequence-ga-individual").evaluate(el => {
    const t = value => (value ?? "").replace(/\s+/g, " ").trim();
    const q = id => el.querySelector(`[data-testid="${id}"]`);
    const lines = id => [...(q(id)?.querySelectorAll("li") ?? [])].map(li => t(li.textContent));
    const facts = node => Object.fromEntries([...(node?.querySelectorAll(":scope > div") ?? [])].map(item =>
      [t(item.querySelector("dt")?.textContent), t(item.querySelector("dd")?.textContent)]));
    const model = q("sequence-ga-detail-model");
    return { key: el.getAttribute("data-key"), isReference: el.getAttribute("data-is-reference"),
      state: el.getAttribute("data-state"), title: t(el.querySelector(".mw-mutation-title")?.textContent),
      facts: facts(q("sequence-ga-detail-facts")), mutations: lines("sequence-ga-detail-mutations"),
      mutationsNone: t(q("sequence-ga-detail-mutations-none")?.textContent), appearances: lines("sequence-ga-detail-appearances"),
      model: !!model, structureLabel: t(model?.querySelector(".mw-eyebrow")?.textContent),
      energy: facts(q("sequence-ga-detail-energy")), energyStatements: lines("sequence-ga-detail-energy-statements"),
      counts: facts(q("sequence-ga-detail-counts")),
      variants: lines("sequence-ga-detail-variants"), variantsNone: t(q("sequence-ga-detail-variants-none")?.textContent),
      protonationRows: [...(q("sequence-ga-detail-protonation-outside")?.querySelectorAll("tbody tr") ?? [])].map(tr =>
        [...tr.querySelectorAll("td")].map(td => t(td.textContent))),
      protonationNone: t(q("sequence-ga-detail-protonation-outside-none")?.textContent),
      disulfides: t(q("sequence-ga-detail-disulfides")?.textContent), newDisulfide: t(q("sequence-ga-detail-new-disulfide")?.textContent),
      addedAtoms: lines("sequence-ga-detail-added-atoms"), limitations: lines("sequence-ga-detail-limitations"),
      download: q("sequence-ga-detail-download")?.getAttribute("href") ?? null,
      noModel: t(q("sequence-ga-detail-no-model")?.textContent), score: t(q("sequence-ga-detail-score")?.textContent),
      m18Handle: q("sequence-ga-m18")?.getAttribute("data-docking-result-handle") ?? null,
      m18Modes: [...(q("sequence-ga-m18-modes")?.querySelectorAll("tbody tr") ?? [])].map(tr => ({
        mode: Number(tr.getAttribute("data-mode")), cells: [...tr.querySelectorAll("td")].map(td => t(td.textContent)) })),
      m18Limitations: lines("sequence-ga-m18-limitations"), noM18: t(q("sequence-ga-detail-no-m18")?.textContent) };
  });
}
/** Click 개체 상세 (or 야생형 기준 상세 보기); waits for that key's detail; returns the view and the API read. */
async function openIndividual(page, run, summary, opener, key, evidence) {
  await st(page, opener).click();
  control(evidence, opener, { key });
  const node = st(page, "sequence-ga-individual").and(seqPanel(page).locator(attr("data-key", key)));
  await node.waitFor({ timeout: 60000 });
  await waitFor(page, async () => await area(page, "individual").getAttribute("data-state") === "ready" ? true : null,
    "individual area ready", 30000);
  return { view: await individualView(page),
    read: await readApi(page, `/runs/${run}/sequence_ga/results/${enc(summary)}/individual?key=${enc(key)}`) };
}
/** The individual detail shows the stored model values only and the stored M18 result detail of that row. */
function individualMatches(value, ctx, row) {
  const { view, read } = value;
  const { runsDir, run } = ctx;
  const reference = row.key === "wild_type";
  assert.equal(view.key, row.key);
  assert.equal(view.isReference, String(reference));
  assert.equal(read.is_reference, reference);
  for (const key of ["state", "reason_code", "score", "model_handle", "result_handle"]) assert.equal(read[key], row[key], key);
  assert.equal(view.state, row.state);
  assert.equal(view.score, row.state === "scored" ? halfUp(row.score, 1) : "—");
  assert.ok(view.facts["상태"]?.endsWith(`(${row.state})`), JSON.stringify(view.facts));
  assert.equal(view.facts[SCORE_HEADER], view.score);
  if (row.reason_code) assert.ok(view.facts["이유"].endsWith(`(${row.reason_code})`), view.facts["이유"]);
  else assert.equal(view.facts["이유"], "해당 없음");
  assert.equal(view.title, reference ? "야생형 기준(참고)" : `개체 ${row.key}`);
  if (!row.model_handle) {
    assert.ok(view.noModel.startsWith("저장된 모델 없음"), view.noModel);
    assert.equal(view.model, false);
    return { key: row.key, model: null };
  }
  const model = storedObject(runsDir, run, row.model_handle);
  assert.equal(model.schema, "mutation_set_model@1");
  const side = reference ? "wild_type_reference" : "mutant";
  assert.deepEqual(Object.keys(model.structures), [side]);
  const entry = model.structures[side];
  // the read returns the stored model without its atom and bond rows
  const strip = structures => Object.fromEntries(Object.entries(structures).map(([key, value]) =>
    [key, Object.fromEntries(Object.entries(value).filter(([field]) => !["final_bonds", "atom_mapping"].includes(field)))]));
  assert.deepEqual(read.model, { ...model, structures: strip(model.structures) }, "the read's model is not the stored model");
  for (const field of ["difference", "delta", "rank", "best", "improved", "ddg"])
    assert.ok(!JSON.stringify(model).toLowerCase().includes(`"${field}`), `model field ${field}`);
  assert.equal(view.structureLabel, `저장된 모델 값 · ${reference ? "야생형 기준 구조" : "변이 구조"} (${side})`);
  if (reference) {
    assert.deepEqual(model.mutations, []);
    assert.ok(view.mutationsNone.startsWith("변이 없음"), view.mutationsNone);
    assert.equal(view.protonationNone, "해당 없음(야생형 기준 구조)");
    assert.ok(view.newDisulfide.endsWith("해당 없음(야생형 기준 구조)"), view.newDisulfide);
  } else {
    assert.deepEqual(model.mutations.map(m => ({ candidate_index: m.candidate_index, residue: m.residue, from: m.from, to: m.to })),
      row.mutations, "the model's mutations are not the summary row's");
    assert.deepEqual(view.mutations, model.mutations.map(m => `후보 번호 ${m.candidate_index} · ${mutText(m)} ` +
      `(${m.residue.resname} → ${m.mutant_resname}) · ${fieldsText(m.residue)}`));
    assert.deepEqual(view.appearances, read.appearances.map(item =>
      `세대 ${item.generation} · 자리 ${item.position + 1} · ${ORIGIN_LABEL[item.origin]}`));
    if (model.protonation_differences.length)
      assert.deepEqual(view.protonationRows, model.protonation_differences.map(item => [resShort(item.residue),
        fieldsText(item.residue), item.wild_type_reference ?? "기본 템플릿 (null)", item.mutant ?? "기본 템플릿 (null)"]));
    else assert.ok(view.protonationNone.startsWith("없음"), view.protonationNone);
    assert.equal(view.newDisulfide, `야생형 기준 구조에 없는 이황화 결합이 이 구조에 있음: ${model.new_disulfide_in_mutant ? "예" : "아니요"} ` +
      "(new_disulfide_in_mutant)");
  }
  assert.deepEqual(view.energy, { [`${ENERGY_LABEL} · 최소화 전`]: halfUp(entry.energy.before_kJ_mol, 2),
    [`${ENERGY_LABEL} · 최소화 후`]: halfUp(entry.energy.after_kJ_mol, 2) }, "potentials shown differ from the stored model");
  assert.deepEqual(view.energyStatements, [S.S5], "the potentials do not carry S5 verbatim");
  assert.deepEqual(view.counts, { "중원자 수": String(entry.heavy_atoms), "pH 7.0에서 만든 수소 수": String(entry.added_hydrogens) });
  if (entry.protonation_variants.length)
    assert.deepEqual(view.variants, entry.protonation_variants.map(item => `${resShort(item.residue)} · ` +
      (item.variant === null ? "기본 템플릿 (null)" : item.variant)));
  else assert.ok(view.variantsNone.includes("0개"), view.variantsNone);
  assert.equal(view.disulfides, entry.disulfide_bonds.length ? entry.disulfide_bonds.map(([a, b]) =>
    `${resShort(a)}–${resShort(b)}`).join(", ") : "0개");
  const groups = new Map();
  for (const atom of entry.added_heavy_atoms) {
    const id = fieldsText(atom.residue);
    const group = groups.get(id) ?? { residue: atom.residue, atoms: [] };
    group.atoms.push(`${atom.atom_name} ${atom.element}`);
    groups.set(id, group);
  }
  assert.deepEqual(view.addedAtoms, groups.size ? [...groups.values()].map(group => `${resShort(group.residue)}: ` +
    `${group.atoms.length}개 (${group.atoms.join(", ")})`) : ["0개"]);
  assert.deepEqual(view.limitations, model.limitations, "the shown model limitations are not the stored ones");
  assert.deepEqual(model.limitations.slice(0, 2), MODEL_LIMITATIONS.slice(0, 2));
  assert.ok(model.limitations.every(text => MODEL_LIMITATIONS.includes(text)), "a model limitation is not a fixed sentence");
  assert.equal(model.limitations.includes(MODEL_LIMITATIONS[2]), model.protonation_differences.length > 0);
  assert.equal(model.limitations.includes(MODEL_LIMITATIONS[3]), model.new_disulfide_in_mutant === true);
  if (row.result_handle) {
    const result = storedObject(runsDir, run, row.result_handle);
    assert.equal(view.m18Handle, row.result_handle);
    assert.equal(read.m18_detail.handle, row.result_handle);
    assert.equal(view.m18Modes.length, result.modes.length);
    view.m18Modes.forEach((item, i) => {
      assert.equal(item.mode, result.modes[i].mode);
      assert.equal(item.cells[1], halfUp(result.modes[i].score_kcal_mol, 1), `mode ${item.mode} score`);
    });
    assert.deepEqual(view.m18Limitations, result.limitations);
    assert.ok(result.limitations.at(-1).startsWith("수용체는 변이 모델링으로 최소화한 구조이며"), result.limitations.at(-1));
    assert.equal(row.score, result.modes[0].score_kcal_mol);
  } else {
    assert.equal(view.m18Handle, null);
    assert.ok(view.noM18.startsWith("저장된 M18 도킹 결과 없음"), view.noM18);
    if (row.reason_code) assert.ok(view.noM18.endsWith(`(${row.reason_code})`), view.noM18);
  }
  return { key: row.key, side, structureSha256: entry.structure_sha256, energy: entry.energy, heavyAtoms: entry.heavy_atoms,
    protonationDifferences: model.protonation_differences.length, newDisulfide: model.new_disulfide_in_mutant,
    limitations: model.limitations.length, m18Modes: view.m18Modes.length };
}
/** 구조 mmCIF 내려받기: bytes SHA-256 = stored structure_sha256 = backend bytes. */
async function downloadStructure(page, app, run, summary, key, expected, evidence) {
  const got = await downloadByClick(app, st(page, "sequence-ga-detail-download"));
  control(evidence, "sequence-ga-detail-download", { key });
  const bytes = fs.readFileSync(got.downloaded);
  const route = `/runs/${run}/sequence_ga/results/${enc(summary)}/structure?key=${enc(key)}`;
  const backend = await readBytes(page, route);
  assert.equal(sha(bytes), expected, "downloaded mmCIF is not the stored structure_sha256");
  assert.equal(sha(bytes), sha(backend));
  const url = new URL(got.url);
  assert.equal(`${url.pathname}${url.search}`, `/api${route}`);
  return { key, sha256: sha(bytes), bytes: bytes.length, filename: got.filename };
}
// ------------------------------------------------------------------ mode main
async function modeMain(session, input, rec_, evidence, log) {
  const { page, app } = session;
  const o = oracle();
  const runsDir = input["runs-dir"];
  evidence.inputs.push(...[STRUCTURE, PHENOL, PLANAR, IMPLICIT_H].map(fileRecord), ...o.files);
  const capabilities = await readApi(page, "/capabilities");
  const capability = capabilities.methods?.sequence_ga_design;
  assert.ok(capability?.available === true, `sequence GA capability unavailable: ${JSON.stringify(capability)}`);
  evidence.capability = { available: capability.available, engine: capability.engine, versions: capability.versions,
    ga_ranges: capability.ga_ranges, limits: capability.limits, timeout_s: capability.timeout_s };
  const exempt = new Set([...Object.values(S), ...MODEL_LIMITATIONS, ...(capabilities.methods?.ligand_docking?.limitations ?? [])]);
  const wording = [];
  const checkWording = async where => {
    const found = forbiddenWords(await gaText(page), exempt);
    wording.push({ where, found });
    return found;
  };
  const handles = evidence.handles;
  await waitForBoot(page);

  // ---- no run (fresh root): reason only
  await rec_.part("no-run", ["SG-no-run"], () => rec_.step("N01-no-run", ["SG-no-run"], "Fresh root: click 단백질 공학 " +
    "before any run exists → the sequence GA area shows 사용할 수 없음 + the no-run reason only (no numbers, no controls, " +
    "no sequence GA request)", async () => {
    const runs = await readApi(page, "/runs");
    const before = Date.now();
    await selectTab(page, TAB);
    await st(page, "sequence-ga-no-run").waitFor({ timeout: 15000 });
    await page.waitForTimeout(1000);
    return { runs: runs.length, ...await noControls(page), reason: clean(await st(page, "sequence-ga-no-run").textContent()),
      gaRequests: log.filter(row => row.at >= before && row.path.includes("/sequence_ga")).length };
  }, async value => {
    assert.equal(value.runs, 0, "mode main needs a fresh runs root");
    assert.equal(value.state, "unavailable");
    assert.ok(value.reason.startsWith("사용할 수 없음") && value.reason.includes(NO_RUN_REASON), value.reason);
    assert.ok(!/\d/.test(value.text), `a number is shown: ${value.text}`);
    assert.equal(value.controls, 0);
    assert.equal(value.gaRequests, 0);
    return { reason: value.reason };
  }));

  // ---- run A: 1UBQ load + 전처리
  const runA = await rec_.step("R01-new-run", [], "Click 구조 분석, 새 run (run A)", () => newRun(page), async id => ({ run: id }));
  evidence.runs.A = runA;
  const loaded = await rec_.step("R02-upload", ["SG-load-prepare"], "Choose public_1ubq.cif, click 구조 불러오기",
    () => uploadLoad(page, STRUCTURE), async value => value);
  handles.structure = loaded.handle;
  const prepared = await rec_.step("R03-prepare", ["SG-load-prepare"], "Click 전처리 (displayed default policies)",
    () => prepareManual(page), async value => value);
  handles.prepared = prepared.prepared;

  // ---- the GA area before any candidate set: reason only
  await rec_.step("C01-no-set", ["SG-no-candidate-set"], "Click 단백질 공학: before any M20 set the sequence GA area shows " +
    "사용할 수 없음 with the reason only (no number, no input; only 후보 집합 목록 다시 읽기), no POST", async () => {
    const before = Date.now();
    await selectTab(page, TAB);
    await st(page, "sequence-ga-no-candidate-set").waitFor({ timeout: 60000 });
    await page.waitForTimeout(1000);
    return { state: await gaState(page), reason: clean(await st(page, "sequence-ga-no-candidate-set").textContent()),
      buttons: await seqPanel(page).locator("button").evaluateAll(items => items.map(item => item.getAttribute("data-testid"))),
      inputs: await seqPanel(page).locator("input, select, textarea, table").count(),
      posts: posts(log, before), text: clean(await seqPanel(page).textContent()) };
  }, async value => {
    assert.equal(value.state, "unavailable");
    assert.ok(value.reason.startsWith("사용할 수 없음") && value.reason.includes(NO_SET_REASON), value.reason);
    assert.ok(!/\d/.test(value.text.replace("M20", "")), value.text);
    assert.deepEqual(value.buttons, ["sequence-ga-candidate-sets-refresh"]);
    assert.equal(value.inputs, 0);
    assert.equal(value.posts, 0);
    return value;
  });

  // ---- M20 sets through the M20 screen: the tiny set (= the T1 fixture) and an I44W-only set
  const sets = await rec_.step("C02-candidate-sets", ["SG-candidate-sets"], "M20 screen: the prepared structure, 직접 선택 " +
    "ILE A:3, LYS A:6, ILE A:44, GLY A:76, 보호 ILE A:3, allowed A W, 후보 만들기 (6 candidates); then only ILE A:44, " +
    "no protection, allowed W, 후보 만들기 (1 candidate)", async () => {
    await m20Ready(page);
    const tiny = await m20Create(page, runA, handles.prepared, TINY, evidence);
    const small = await m20Create(page, runA, handles.prepared, SMALL, evidence);
    return { tiny, small };
  }, async value => {
    const tiny = storedObject(runsDir, runA, value.tiny.handle);
    const small = storedObject(runsDir, runA, value.small.handle);
    const pick = position => ({ index: position.index, residue: position.residue, status: position.status,
      candidate_count: position.candidate_count, exclusion_reasons: position.exclusion_reasons });
    assert.deepEqual(tiny.candidates, o.tiny.candidates, "tiny set candidates differ from the T1 fixture");
    assert.deepEqual(tiny.positions.map(pick), o.tiny.positions.map(pick), "tiny set positions differ from the T1 fixture");
    // M26 spec 8: the M20 tool now builds v2 sets; made without an M-CSA annotation the catalytic check is not_checked
    // (annotation_not_given) and the counts gain the v2 key catalytic_residue 0, which counts nothing (the M20 screen
    // shows "—", never 0). The T1 fixture is a stored v1 set and stays the expectation for every other count.
    assert.equal(tiny.method_version, "mw.mutation_candidates/v2");
    assert.deepEqual(tiny.protection_checks.catalytic_residue_database,
      { status: "not_checked", reason: "annotation_not_given", annotation: null });
    assert.deepEqual(tiny.counts, { ...o.tiny.counts,
      exclusion_reason_counts: { ...o.tiny.counts.exclusion_reason_counts, catalytic_residue: 0 } });
    const alts = {};
    for (const candidate of tiny.candidates) (alts[String(candidate.position_index)] ??= []).push(candidate.index);
    assert.deepEqual(alts, o.space.alts, "the set is not the oracle's combination space");
    assert.equal(small.candidates.length, 1);
    assert.deepEqual([small.candidates[0].from, small.candidates[0].to], ["I", "W"]);
    return { tiny: value.tiny.handle, small: value.small.handle, tinyCounts: tiny.counts, smallCandidates: small.candidates };
  });
  handles.tiny = sets.tiny.handle;
  handles.small = sets.small.handle;
  const tinyContent = storedObject(runsDir, runA, handles.tiny);
  const ctx = { runsDir, run: runA, setContent: tinyContent };

  // ---- ligand SDF imports (리간드 탭) and the tab trip back: nothing chosen automatically
  const sdfs = await rec_.step("L01-ligand-imports", ["SG-ligand-imports"], "Click 리간드 설계·탐색; in the docking area " +
    "choose and import the labeled synthetic phenol, planar and implicit-H SDFs (file chooser + 가져오기, one by one)",
  async () => ({ phenol: await importLigandSdf(page, runA, PHENOL, evidence),
    planar: await importLigandSdf(page, runA, PLANAR, evidence),
    implicitH: await importLigandSdf(page, runA, IMPLICIT_H, evidence) }), async value => {
    assert.equal(new Set(Object.values(value)).size, 3);
    return value;
  });
  Object.assign(handles, { phenol: sdfs.phenol, planar: sdfs.planar, implicitH: sdfs.implicitH });
  await rec_.step("G01-initial", ["SG-initial-state", "SG-ligand-imports"], "Click 단백질 공학 again: the area remounts and " +
    "reads its lists (GET only); 빈 결과; nothing chosen, submitted or approved automatically (no set, no SDF, no box, " +
    "confirmations and acknowledgements unchecked, GA seed empty, defaults prefilled); 시작 전 확인 and 서열 GA 시작 blocked " +
    "with the reasons", async () => {
    const before = Date.now();
    await openProteinTab(page);
    await page.waitForTimeout(1500);
    const sdfOptions = await st(page, "sequence-ga-sdf").locator("option").evaluateAll(items => items.map(item => item.value));
    return { state: await gaState(page), badge: clean(await st(page, "sequence-ga-state").textContent()),
      empty: clean(await st(page, "sequence-ga-empty").textContent({ timeout: 1000 }).catch(() => "")),
      capability: clean(await st(page, "sequence-ga-capability").textContent()),
      set: await st(page, "sequence-ga-candidate-set").inputValue(),
      setOptions: await st(page, "sequence-ga-candidate-set").locator("option").evaluateAll(items => items.map(item => item.value)),
      sdf: await st(page, "sequence-ga-sdf").inputValue(), sdfOptions,
      boxChecked: await st(page, "sequence-ga-box-source").locator("input:checked").count(),
      instanceDisabled: await seqPanel(page).locator('label[data-pair-box="instance_range"] input').isDisabled(),
      ligandSources: await st(page, "sequence-ga-ligand-source").locator("label").evaluateAll(items => items.map(item => ({
        source: item.getAttribute("data-pair-ligand-source"), disabled: item.querySelector("input").disabled,
        checked: item.querySelector("input").checked, reason: item.getAttribute("data-disabled-reason") }))),
      confirmations: [await st(page, "sequence-ga-confirm-selection").isChecked(), await st(page, "sequence-ga-confirm-hydrogen").isChecked()],
      acks: await st(page, "sequence-ga-acknowledgement").locator("input:checked").count(),
      seed: await st(page, "sequence-ga-seed").inputValue(), params: await paramValues(page), start: await startState(page),
      errors: await inputErrors(page), spacePending: await st(page, "sequence-ga-space-pending").count(),
      job: await st(page, "sequence-ga-job").count(), preflightView: await st(page, "sequence-ga-preflight-view").count(),
      result: await st(page, "sequence-ga-result").count(), listEmpty: await st(page, "sequence-ga-list-empty").count(),
      posts: posts(log, before), gets: log.filter(row => row.at >= before && row.method === "GET" && row.api).map(row => row.path) };
  }, async value => {
    assert.equal(value.state, "empty");
    assert.equal(value.badge, "빈 결과");
    assert.ok(value.empty.includes("서열 GA 결과가 없습니다"), value.empty);
    assert.ok(value.capability.startsWith(`${TOOL} · ${PROTOCOL} · qvina · 새 평가 1건마다 비싼 계산 2단위`), value.capability);
    assert.equal(value.set, "");
    assert.deepEqual(value.setOptions.filter(Boolean).sort(), [handles.tiny, handles.small].sort());
    assert.equal(value.sdf, "");
    assert.deepEqual(value.sdfOptions.filter(Boolean).sort(), [handles.phenol, handles.planar, handles.implicitH].sort());
    assert.equal(value.boxChecked, 0);
    assert.equal(value.instanceDisabled, true);
    assert.deepEqual(value.ligandSources.filter(item => !item.disabled).map(item => item.source), ["sdf"]);
    assert.ok(value.ligandSources.filter(item => item.disabled).every(item => item.reason?.includes("3D SDF")), JSON.stringify(value.ligandSources));
    assert.deepEqual(value.confirmations, [false, false]);
    assert.equal(value.acks, 0);
    assert.equal(value.seed, "");
    assert.deepEqual(value.params, Object.fromEntries(GA_KEYS.map(key => [key, key === "seed" ? "" : String(RANGES[key][2])])));
    assert.equal(value.start.enabled, false);
    assert.equal(value.start.preflightEnabled, false);
    for (const text of ["변이 후보 집합을 고르세요", "(confirmation_missing)", "(acknowledgement_missing)", "(invalid_job_arguments)"])
      assert.ok(value.errors.some(line => line.includes(text)), `${text}: ${JSON.stringify(value.errors)}`);
    assert.ok(value.start.blocked.includes("변이 후보 집합을 고르세요"), value.start.blocked);
    assert.equal(value.spacePending, 1);
    assert.deepEqual([value.job, value.preflightView, value.result, value.listEmpty], [0, 0, 0, 1]);
    assert.equal(value.posts, 0, "a POST was sent on entering the tab");
    assert.ok(value.gets.includes(`/api/runs/${runA}/mutation_candidate_sets`), JSON.stringify(value.gets));
    assert.ok(value.gets.includes(`/api/runs/${runA}/sequence_ga/results`), JSON.stringify(value.gets));
    const found = await checkWording("initial");
    assert.deepEqual(found, [], JSON.stringify(found));
    return value;
  });

  // ---- inputs, parameter guards (11 keys), cross rules, defaults, confirmations: no request while blocked
  const phenolInput = { set: handles.tiny, sdf: handles.phenol, box: { source: "ligand_range", margin: DOCK.margin }, ...DOCK };
  const look = async (label, key = null) => ({ label, key, errors: await fieldErrors(page), start: await startState(page),
    effectiveBlocked: await st(page, "sequence-ga-effective-blocked").count(), inputErrors: await inputErrors(page) });
  await rec_.step("P01-guards", ["SG-param-guards"], "Choose the tiny set, the phenol SDF, 리간드 범위 + 여백 8, evaluation " +
    "seed 20261004, exhaustiveness 4, num_modes 5, energy_range 3, both confirmations, the three acknowledgements and the " +
    "GA 1 values; then each of the 11 keys out of range (seed 2147483648, population 17, generations 9, elite 5, " +
    "tournament 1, crossover 1.5, random 0.6, max_mutations 5, patience 0, max new 65, total 599) and the GA seed empty: " +
    "each blocks 시작 전 확인 and 서열 GA 시작 with the field's reason; no request", async () => {
    await chooseInputs(page, runA, phenolInput, evidence);
    await setParams(page, strings(GA1), evidence);
    const before = Date.now();
    const baseline = await look("GA 1 values");
    const observed = [];
    for (const [key, bad] of [...Object.entries(OUT_OF_RANGE), ["seed", ""]]) {
      await setParams(page, { [key]: bad }, evidence);
      observed.push(await look(`${key} = ${JSON.stringify(bad)}`, key));
      await setParams(page, { [key]: String(GA1[key]) }, evidence);
    }
    return { baseline, observed, posts: posts(log, before, GA_POST), after: await look("restored") };
  }, async value => {
    for (const seen of [value.baseline, value.after]) {
      assert.deepEqual(seen.errors, {}, JSON.stringify(seen.errors));
      assert.equal(seen.start.preflightEnabled, true, seen.start.blocked);
      assert.equal(seen.effectiveBlocked, 0);
    }
    assert.equal(value.observed.length, 12);
    for (const seen of value.observed) {
      const [low, high] = RANGES[seen.key];
      const kind = FLOAT_KEYS.includes(seen.key) ? "숫자" : "정수";
      assert.deepEqual(Object.keys(seen.errors), [seen.key], `${seen.label}: ${JSON.stringify(seen.errors)}`);
      const text = seen.errors[seen.key];
      assert.ok(text.includes(`${low}–${high} 사이의 ${kind}`) && text.endsWith("(invalid_job_arguments)."), `${seen.label}: ${text}`);
      if (seen.key === "seed") assert.ok(text.includes("(필수)"), text);
      assert.equal(seen.start.enabled, false, `${seen.label}: 서열 GA 시작 enabled`);
      assert.equal(seen.start.preflightEnabled, false, `${seen.label}: 시작 전 확인 enabled`);
      assert.ok(seen.start.blocked.includes(text), `${seen.label}: blocked reason ${seen.start.blocked}`);
      assert.ok(seen.inputErrors.includes(text), `${seen.label}: ${JSON.stringify(seen.inputErrors)}`);
      assert.equal(seen.effectiveBlocked, 1, `${seen.label}: effective summary shown with an error`);
    }
    assert.equal(value.posts, 0, "a sequence GA request was sent while the parameters were invalid");
    return value.observed.map(item => ({ key: item.key, label: item.label, error: item.errors[item.key] }));
  });
  await rec_.step("P02-cross-rules", ["SG-param-guards", "SG-cross-rules"], "Population 4 with elite 3 (population − elite " +
    "< 2) and population 8 with max new 6 (max new < population): each blocks both buttons with its reason at the " +
    "named field; no request", async () => {
    const before = Date.now();
    await setParams(page, { elite_count: "3" }, evidence);
    const elite = await look("population 4, elite 3", "elite_count");
    await setParams(page, { elite_count: "1", population_size: "8", max_new_evaluations: "6" }, evidence);
    const maxNew = await look("population 8, max new 6", "max_new_evaluations");
    await setParams(page, { population_size: "4", max_new_evaluations: "32" }, evidence);
    return { elite, maxNew, after: await look("restored"), posts: posts(log, before, GA_POST) };
  }, async value => {
    for (const [seen, text] of [[value.elite, "세대당 개체 수 − 이어받는 개체 수가 2 이상이어야 합니다"],
      [value.maxNew, "세대당 개체 수(8) 이상이어야 합니다"]]) {
      assert.deepEqual(Object.keys(seen.errors), [seen.key], JSON.stringify(seen.errors));
      assert.ok(seen.errors[seen.key].includes(text) && seen.errors[seen.key].includes("(invalid_job_arguments)"), seen.errors[seen.key]);
      assert.equal(seen.start.enabled, false);
      assert.equal(seen.start.preflightEnabled, false);
      assert.ok(seen.start.blocked.includes(seen.errors[seen.key]), seen.start.blocked);
    }
    assert.deepEqual(value.after.errors, {});
    assert.equal(value.posts, 0);
    return { elite: value.elite.errors, maxNew: value.maxNew.errors };
  });
  await rec_.step("P03-defaults", ["SG-defaults"], "Type other values, click 기본값으로: every parameter is the spec 2 default " +
    "again (8, 5, 2, 2, 0.5, 0.2, 3, 3, 32, 7200) and the GA seed 21 is kept; each field shows its range and default; the " +
    "effective summary lists every key and the job time limit 7800 s; the space waits for the server", async () => {
    await setParams(page, { population_size: "6", generations: "3", random_fraction: "0.1", total_s: "900" }, evidence);
    await st(page, "sequence-ga-defaults").click();
    control(evidence, "sequence-ga-defaults", { clicked: true });
    await st(page, "sequence-ga-effective").waitFor({ timeout: 10000 });
    return { values: await paramValues(page), ranges: Object.fromEntries(await Promise.all(GA_KEYS.map(async key =>
      [key, clean(await st(page, `sequence-ga-range-${key}`).textContent())]))),
    effective: await factLines(st(page, "sequence-ga-effective").locator("[data-line]")), errors: await fieldErrors(page),
    start: await startState(page), spacePending: await st(page, "sequence-ga-space-pending").count() };
  }, async value => {
    const want = Object.fromEntries(GA_KEYS.map(key => [key, key === "seed" ? String(GA1.seed) : String(RANGES[key][2])]));
    assert.deepEqual(value.values, want, "기본값으로 did not restore the spec 2 defaults");
    assert.deepEqual(value.errors, {});
    for (const key of GA_KEYS) {
      const [low, high, fallback] = RANGES[key];
      const text = value.ranges[key];
      assert.ok(text.includes(`–${high}`) && text.includes(fallback === null ? "기본 없음(필수)" : `기본 ${fallback}`), `${key}: ${text}`);
      assert.ok(text.startsWith(key === "max_new_evaluations" ? "세대당 개체 수–" : `${low}–`), `${key}: ${text}`);
    }
    assert.equal(value.effective.length, GA_KEYS.length + 1);
    GA_KEYS.forEach((key, i) => assert.ok(value.effective[i][1].startsWith(want[key]), `${key}: ${value.effective[i]}`));
    assert.deepEqual(value.effective.at(-1), ["작업 시간 한도", "7800초 (GA 전체 시간 상한 + 마무리 600초)"]);
    assert.equal(value.start.preflightEnabled, true);
    assert.equal(value.start.enabled, false, "서열 GA 시작 enabled without a preflight");
    assert.equal(value.spacePending, 1);
    return value;
  });
  await rec_.step("P04-confirmations", ["SG-confirmations"], "Untick rebuild_pH7, then one acknowledgement: 시작 전 확인 is " +
    "blocked with \"… (confirmation_missing)\" / \"… (acknowledgement_missing)\"; no request; tick them again", async () => {
    const before = Date.now();
    await setChecked(page, st(page, "sequence-ga-confirm-hydrogen"), false, "sequence-ga-confirm-hydrogen", evidence);
    const confirmation = await look("rebuild_pH7 unticked");
    await setChecked(page, st(page, "sequence-ga-confirm-hydrogen"), true, "sequence-ga-confirm-hydrogen", evidence);
    const ack = seqPanel(page).locator(`label[data-pair-ack="${ACK_KEYS[1]}"] input`);
    await setChecked(page, ack, false, `sequence-ga-ack-${ACK_KEYS[1]}`, evidence);
    const acknowledgement = await look("acknowledgement unticked");
    await setChecked(page, ack, true, `sequence-ga-ack-${ACK_KEYS[1]}`, evidence);
    return { confirmation, acknowledgement, after: await look("restored"), posts: posts(log, before, GA_POST) };
  }, async value => {
    for (const [seen, code] of [[value.confirmation, "(confirmation_missing)"], [value.acknowledgement, "(acknowledgement_missing)"]]) {
      assert.ok(seen.inputErrors.some(text => text.includes(code)), JSON.stringify(seen.inputErrors));
      assert.equal(seen.start.preflightEnabled, false);
      assert.equal(seen.start.enabled, false);
      assert.ok(seen.start.blocked.includes(code), seen.start.blocked);
    }
    assert.equal(value.after.start.preflightEnabled, true);
    assert.equal(value.posts, 0);
    return { confirmation: value.confirmation.inputErrors, acknowledgement: value.acknowledgement.inputErrors };
  });
  await rec_.step("P05-refusals", ["SG-refusals"], "시작 전 확인 보기 with the defaults and max_mutations 1 (6 combinations < 8): " +
    "ga_space_too_small; the I44W set with population 4 (1 combination): ga_space_too_small; the tiny set with the planar " +
    "SDF: ligand_not_3d — each shown as \"한국어 (code)\" with the server detail; start blocked; no job, no event, no charge",
  async () => {
    const jobsBefore = (await readApi(page, `/runs/${runA}/jobs`)).length;
    const eventsBefore = (await runEvents(page, runA)).length;
    const budgetBefore = await budgetUsed(page, runA);
    await setParams(page, { max_mutations: "1" }, evidence);
    const single = await preflight(page, runA, evidence);
    await setParams(page, { max_mutations: "3", population_size: "4" }, evidence);
    await st(page, "sequence-ga-candidate-set").selectOption(handles.small);
    control(evidence, "sequence-ga-candidate-set", { handle: handles.small });
    const small = await preflight(page, runA, evidence);
    await st(page, "sequence-ga-candidate-set").selectOption(handles.tiny);
    await st(page, "sequence-ga-sdf").selectOption(handles.planar);
    control(evidence, "sequence-ga-sdf", { handle: handles.planar });
    const planar = await preflight(page, runA, evidence);
    await st(page, "sequence-ga-sdf").selectOption(handles.phenol);
    return { single, small, planar, jobsBefore, jobsAfter: (await readApi(page, `/runs/${runA}/jobs`)).length, eventsBefore,
      eventsAfter: (await runEvents(page, runA)).length, budgetBefore, budgetAfter: await budgetUsed(page, runA) };
  }, async value => {
    for (const [pf, size, population] of [[value.single, 6, 8], [value.small, 1, 4]]) {
      assert.equal(pf.status, 200);
      assert.equal(pf.body.admission.admitted, false);
      assert.equal(pf.body.admission.reason_code, "ga_space_too_small");
      assert.equal(pf.body.admission.detail.size, size);
      assert.equal(pf.body.admission.detail.population_size, population);
      assert.equal(pf.view.reasonCode, "ga_space_too_small");
      assert.ok(koreanThenCode(pf.view.refused, "ga_space_too_small"), pf.view.refused);
      assert.ok(pf.view.refused.includes(`· 조합 ${size}개, 세대당 개체 수 ${population}`), pf.view.refused);
    }
    assert.equal(spaceSize([2, 2, 2], 1), 6);
    assert.equal(spaceSize([1], 3), 1);
    assert.equal(value.planar.body.admission.reason_code, "ligand_not_3d");
    assert.equal(value.planar.view.reasonCode, "ligand_not_3d");
    assert.ok(koreanThenCode(value.planar.view.refused, "ligand_not_3d"), value.planar.view.refused);
    for (const pf of [value.single, value.small, value.planar]) {
      assert.equal(pf.body.reserved_units, null);
      assert.equal(pf.body.space, null);
      assert.equal(pf.view.preflightView, 0);
      assert.deepEqual(pf.view.spaceLines, {}, "a refused preflight shows space numbers");
      assert.equal(pf.view.start.enabled, false);
      assert.ok(pf.view.start.blocked.includes(`(${pf.body.admission.reason_code})`), pf.view.start.blocked);
    }
    assert.equal(value.jobsAfter, value.jobsBefore);
    assert.equal(value.eventsAfter, value.eventsBefore, "a preflight read wrote events");
    assert.deepEqual(value.budgetAfter, value.budgetBefore);
    const found = await checkWording("refusals");
    assert.deepEqual(found, [], JSON.stringify(found));
    return { refused: [value.single.view.refused, value.small.view.refused, value.planar.view.refused] };
  });

  // ---- GA 1: preflight, the screen's limit approval, the real GA, results, oracle path, sort, details
  const expectedSpace = { positions: 3, candidates: 6, effective_max_mutations: 3, size: spaceSize([2, 2, 2], 3) };
  const pf1 = await rec_.step("G02-preflight", ["SG-preflight"], "GA 1 values (GA seed 21, population 4, generations 4, " +
    "elite 1, tournament 2, crossover 0.5, random 0.25, max_mutations 3, patience 2, max new 32, total 7200 s); 시작 전 " +
    "확인 보기: space 3 / 6 / 26 (cap 3) shown in ②, 602 heavy atoms and no 4,890 warning (server flag), reusable 0, the " +
    "reference row new, reserved 13 evaluations / 28 units, need 28 units / 7800 s, remaining = budget, shortfall = need " +
    "− remaining (approval offered, start blocked), 끝까지 못 갈 수 있음 (28 × 270 s > 7200 s), S1 S4 S5 S6 verbatim", async () => {
    await setParams(page, strings(GA1), evidence);
    const budget = await readApi(page, `/runs/${runA}/budget`);
    return { pf: await preflight(page, runA, evidence), budget };
  }, async value => {
    const facts = preflightMatches(value.pf, { gaValues: GA1, space: expectedSpace, reusable: 0, referenceReusable: false,
      budget: value.budget });
    assert.equal(expectedSpace.size, 26);
    assert.equal(facts.heavyAtoms, 602);
    assert.equal(facts.heavyAtomWarning, false);
    assert.equal(facts.mayBePartial, true);
    assert.ok(facts.shortfall.expensive_calls > 0, "GA 1 needs no raise in a fresh run");
    assert.equal(value.pf.body.existing_job, null);
    const r = value.pf.request;
    assert.deepEqual(Object.keys(r).sort(), ["acknowledgement", "box", "candidate_set", "ga", "hydrogen_policy", "ligand",
      "parameters", "selection_policy"]);
    assert.deepEqual(r.ligand, { source: "sdf", sdf_handle: handles.phenol });
    assert.deepEqual(r.box, { source: "ligand_range", margin_A: 8 });
    assert.deepEqual(r.parameters, { seed: 20261004, exhaustiveness: 4, num_modes: 5, energy_range: 3 });
    assert.deepEqual([r.selection_policy, r.hydrogen_policy], ["protein_only", "rebuild_pH7"]);
    assert.deepEqual(r.ga, GA1);
    const found = await checkWording("GA 1 preflight");
    assert.deepEqual(found, [], JSON.stringify(found));
    return facts;
  });
  evidence.gaArgs = { run: runA, args: pf1.pf.request, timeoutS: GA1.total_s + 600 };
  await rec_.step("G03-limit-approval", ["SG-limit-approval"], "Click 이 서열 GA에 필요한 만큼 한도를 올림 (a person's click): " +
    "the limit rises by the shortfall only (wall + 60 s margin), by human, sequence GA context, no job/object/charge; the " +
    "preflight is read again with no shortfall; nothing starts by itself", async () =>
    approveLimits(page, runA, pf1.pf, evidence), async value => {
    const facts = approvalMatches(value);
    assert.equal(facts.jobAreasAfter, 0, "a job appeared after the limit approval");
    return facts;
  });
  const ga1 = await rec_.step("G04-run", ["SG-run", "SG-progress"], "Click 서열 GA 시작: the run's first expensive call asks " +
    "for 비싼 계산 승인; click it, then 작업 시작; while running the progress line equals the stored job record (reference row " +
    "recorded, generations, new evaluations); the real GA (OpenMM + PDBFixer modeling child, qvina) runs to done; exactly " +
    "reserved_units (28) units; the summary is listed but not opened", async () => runGa(page, runA, evidence, { progress: true }),
  async value => {
    assert.equal(value.request.protocol_id, PROTOCOL);
    assert.deepEqual(value.request.args, pf1.pf.request);
    assert.equal(value.request.timeout_s, GA1.total_s + 600);
    assert.equal(value.job.status, "done", JSON.stringify(value.job.failure));
    assert.equal(value.job.protocol_id, PROTOCOL);
    assert.equal(value.job.timeout_s, GA1.total_s + 600);
    assert.equal(value.approved, true, "the run's first expensive call did not ask for approval");
    assert.ok(value.phases.includes("running"), JSON.stringify(value.phases));
    assert.ok(value.progressSeen.length >= 1, "no running progress line matched the job record");
    assert.ok(value.progressSeen.some(item => item.record.reference_recorded === true), "reference row never recorded while running");
    assert.match(value.handle ?? "", /\/sequence_ga_result\//);
    assert.equal(value.budgetAfter.used, value.budgetBefore.used + 28, "units differ from reserved_units");
    assert.equal(value.jobsAfter, value.jobsBefore + 1);
    assert.equal(value.job.sequence_ga.summary_status, "complete");
    assert.ok(value.notice.includes(shortHandle(value.handle)), value.notice);
    assert.equal(await st(page, "sequence-ga-result").count(), 0, "the summary was opened automatically");
    return { job: value.job.job_id, handle: value.handle, budget: [value.budgetBefore, value.budgetAfter],
      progressSeen: value.progressSeen, phases: value.phases };
  });
  handles.ga1 = ga1.handle;
  evidence.gaArgs = { ...evidence.gaArgs, job: ga1.job.job_id, summary: ga1.handle };
  evidence.gaRuns = { ga1: ga1.handle };
  const ga1Stored = storedObject(runsDir, runA, ga1.handle);
  await rec_.step("T01-results", ["SG-results", "SG-oracle-path"], "Choose the GA 1 summary: status 완료 (no_change, 점수 " +
    "최솟값 변화 없음), S1 S4 S5 S6, the summary lines, the wild-type reference row apart from the table, every generation " +
    "tab and row (mutations from the set, origin, parents, evaluation, state, score = stored M18 first mode, ROUND_HALF_UP) " +
    "= the stored summary; carried rule; min/max as stored values; the path = the T1 independent oracle vector", async () => {
    const header = await openSummary(page, ga1.handle, evidence);
    const detail = await readApi(page, `/runs/${runA}/sequence_ga/results/${enc(ga1.handle)}`);
    return { header, facts: await resultEquals(page, ctx, header, detail, ga1Stored, evidence) };
  }, async value => {
    assert.equal(value.facts.stopReason, "no_change");
    assert.deepEqual(value.facts.statements, ["S1", "S4", "S5", "S6"]);
    // independent oracle (T1 expected.json vector s4_tiny_observed: same set, GA values and docking values)
    const want = o.vector.expected;
    assert.deepEqual(projectPath(ga1Stored.generations), projectPath(want.generations), "GA 1 path differs from the T1 oracle");
    for (const key of ["stop_reason", "status", "generations_done", "new_evaluations_used", "reused_count",
      "reserved_evaluations", "reserved_units"]) assert.equal(ga1Stored[key], want[key], key);
    assert.deepEqual(ga1Stored.space, want.space);
    for (const key of ["evaluation", "state", "reason_code", "score"]) assert.equal(ga1Stored.reference[key], want.reference[key], key);
    const found = await checkWording("GA 1 results");
    assert.deepEqual(found, [], JSON.stringify(found));
    return value.facts;
  });
  await rec_.step("T02-expand", ["SG-results"], "Click the 변이 cell of a multi-position individual: it opens and shows each " +
    "position's candidate number and the 7 stored residue fields (nulls kept as stored)", async () => {
    const at = ga1Stored.generations.flatMap(gen => gen.individuals.map((item, position) => ({ gen: gen.index, position, item })))
      .find(entry => entry.item.mutations.length >= 2);
    await showGeneration(page, at.gen, evidence);
    const details = st(page, `sequence-ga-mutations-${at.gen}-${at.position}`);
    await details.locator("summary").click();
    control(evidence, "sequence-ga-mutations", { generation: at.gen, position: at.position });
    await waitFor(page, async () => await details.evaluate(node => node.open) ? true : null, "details open", 5000);
    return { at, open: await details.evaluate(node => node.open),
      visible: await details.locator("li").first().isVisible(), lines: (await details.locator("li").allTextContents()).map(clean) };
  }, async value => {
    assert.equal(value.open, true);
    assert.equal(value.visible, true);
    assert.deepEqual(value.lines, value.at.item.mutations.map(m => `후보 번호 ${m.candidate_index} · ${mutText(m)} · ` +
      fieldsText(m.residue)));
    return { key: value.at.item.key, lines: value.lines };
  });
  await rec_.step("T03-sort", ["SG-sort"], "Generation 1 of GA 1: click 점수, 개체 키 and 자리 headers twice each: the order " +
    "follows the stored values (display order only; rows without a score stay last; no rank column); aria-sort follows",
  async () => {
    await showGeneration(page, 1, evidence);
    return sortChecks(page, ga1Stored.generations[0], evidence);
  }, async value => value);
  await rec_.part("detail", ["SG-detail", "SG-download"], async () => {
    const multi = ga1Stored.generations.flatMap(gen => gen.individuals.map((item, position) => ({ gen: gen.index, position, item })))
      .find(entry => entry.item.origin !== "carried" && entry.item.mutations.length >= 2 && entry.item.state === "scored");
    await rec_.step("D01-individual", ["SG-detail"], `Click 개체 상세 of individual ${multi.item.key} ` +
      `(generation ${multi.gen}): the stored model values only (mutations with 7 fields, OpenMM potentials with S5, ` +
      "HIS/CYS states and the list differing from the reference, disulfides, PDBFixer atoms per residue, model " +
      "limitations) and the stored M18 result detail (mode table, 12 limitation sentences)", async () => {
      await showGeneration(page, multi.gen, evidence);
      return openIndividual(page, runA, ga1.handle, `sequence-ga-open-${multi.gen}-${multi.position}`, multi.item.key, evidence);
    }, async value => {
      const facts = individualMatches(value, ctx, multi.item);
      for (const text of value.read.m18_detail?.result?.limitations ?? []) exempt.add(text);
      const found = await checkWording("individual detail");
      assert.deepEqual(found, [], JSON.stringify(found));
      return facts;
    });
    await rec_.step("D02-download", ["SG-download"], "Click 구조 mmCIF 내려받기: bytes SHA-256 = the stored model's " +
      "structure_sha256 = backend bytes", () => downloadStructure(page, app, runA, ga1.handle, multi.item.key,
      storedObject(runsDir, runA, multi.item.model_handle).structures.mutant.structure_sha256, evidence), async value => value);
    const reference = await rec_.step("D03-reference", ["SG-detail"], "Click 야생형 기준 상세 보기: the reference model values " +
      "(no mutation, not applicable comparisons) and its M18 result", async () =>
      openIndividual(page, runA, ga1.handle, "sequence-ga-reference-open", "wild_type", evidence),
    async value => individualMatches(value, ctx, { ...ga1Stored.reference, key: "wild_type", mutations: [] }));
    await rec_.step("D04-reference-download", ["SG-download"], "Click 구조 mmCIF 내려받기 of the reference row: bytes = stored " +
      "structure_sha256 = backend bytes", () => downloadStructure(page, app, runA, ga1.handle, "wild_type",
      reference.read.model.structures.wild_type_reference.structure_sha256, evidence), async value => value);
  });

  // ---- GA 1 arguments again: the existing job (after the screen's raise for these arguments), no new job, no unit
  await rec_.part("dedupe", ["SG-dedupe", "SG-limit-approval"], () => rec_.step("U01-dedupe", ["SG-dedupe", "SG-limit-approval"],
    "With GA 1's arguments unchanged, 시작 전 확인 보기: the existing GA 1 job is named; the remaining budget is short of " +
    "these arguments' 28 units, so the screen offers the raise: click it (a person's click, nothing charged); click 서열 " +
    "GA 시작: GA 1's done job is shown again (no new job, no unit, no object)", async () => {
    const pf = await preflight(page, runA, evidence);
    let approval = null;
    if (pf.body.shortfall && (pf.body.shortfall.expensive_calls > 0 || pf.body.shortfall.wall_clock_s > 0))
      approval = approvalMatches(await approveLimits(page, runA, pf, evidence));
    const units = await budgetUsed(page, runA);
    const jobsBefore = (await readApi(page, `/runs/${runA}/jobs`)).length;
    const objectsBefore = objectHandles(runsDir, runA, "sequence_ga_result").length;
    const posted = page.waitForResponse(response => response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/api/runs/${runA}/jobs`, { timeout: 60000 });
    posted.catch(() => undefined);
    await st(page, "sequence-ga-start").click();
    control(evidence, "sequence-ga-start", { identical: true });
    const response = await posted;
    const body = await response.json();
    await waitFor(page, async () => clean(await st(page, "sequence-ga-notice").textContent({ timeout: 1000 }).catch(() => ""))
      .includes("같은 입력의 기존 서열 GA 작업") ? true : null, "existing job notice", 30000);
    return { pf, approval, status: response.status(), job: body, units, unitsAfter: await budgetUsed(page, runA), jobsBefore,
      jobsAfter: (await readApi(page, `/runs/${runA}/jobs`)).length, objectsBefore,
      objectsAfter: objectHandles(runsDir, runA, "sequence_ga_result").length,
      notice: clean(await st(page, "sequence-ga-notice").textContent()) };
  }, async value => {
    preflightMatches(value.pf, { gaValues: GA1, space: expectedSpace, reusable: ga1Stored.new_evaluations_used,
      referenceReusable: true });
    assert.equal(value.pf.body.existing_job?.job_id, ga1.job.job_id);
    assert.equal(value.pf.body.existing_job?.summary_handle, ga1.handle);
    assert.equal(value.pf.view.existingJob, ga1.job.job_id);
    assert.ok(value.pf.view.existingText.includes("새 작업을 만들지 않고"), value.pf.view.existingText);
    assert.equal(value.status, 200);
    assert.equal(value.job.job_id, ga1.job.job_id, "a new job was created for identical GA arguments");
    assert.equal(value.jobsAfter, value.jobsBefore);
    assert.equal(value.objectsAfter, value.objectsBefore);
    assert.deepEqual(value.unitsAfter, value.units, "identical GA arguments were charged");
    assert.ok(value.notice.includes(ga1.job.job_id) && value.notice.includes("새 작업을 만들지 않았습니다"), value.notice);
    return { job: value.job.job_id, notice: value.notice, approval: value.approval };
  }));

  // ---- GA 2: other GA seed, same evaluation seed → reuse of GA 1's stored rows + evaluation_limit (partial)
  let ga2 = null;
  await rec_.part("reuse", ["SG-reuse", "SG-partial"], async () => {
    ga2 = await rec_.step("U02-reuse-partial", ["SG-reuse", "SG-partial"], "GA seed 13, generations 2, max new 4, total " +
      "600 s (evaluation seed unchanged): preflight reusable = GA 1's 10 rows and the reference row reusable, reserved 4 " +
      "evaluations / 10 units; 서열 GA 시작 (a raise first if short): reused individuals cite GA 1's stored model and result " +
      "(재사용, no new object, no unit); the run stops at the fifth new evaluation: partial / evaluation_limit, generation 2 " +
      "marked stopped, S1–S6; exactly 10 units", async () => {
      await setParams(page, strings(GA2), evidence);
      const budget = await readApi(page, `/runs/${runA}/budget`);
      const pf = await preflight(page, runA, evidence);
      const facts = preflightMatches(pf, { gaValues: GA2, space: expectedSpace, reusable: ga1Stored.new_evaluations_used,
        referenceReusable: true, budget });
      const approval = facts.shortfall.expensive_calls > 0 || facts.shortfall.wall_clock_s > 0
        ? approvalMatches(await approveLimits(page, runA, pf, evidence)) : null;
      const before = { results: objectHandles(runsDir, runA, "docking_result"), models: objectHandles(runsDir, runA, "mutation_set_model") };
      const job = await runGa(page, runA, evidence);
      const header = await openSummary(page, job.handle, evidence);
      const detail = await readApi(page, `/runs/${runA}/sequence_ga/results/${enc(job.handle)}`);
      const stored = storedObject(runsDir, runA, job.handle);
      return { pf, facts, approval, job, header, stored, result: await resultEquals(page, ctx, header, detail, stored, evidence),
        before, after: { results: objectHandles(runsDir, runA, "docking_result"), models: objectHandles(runsDir, runA, "mutation_set_model") },
        published: (await runEvents(page, runA)).filter(event => event.type === "sequence_ga_individual_published" &&
          event.job_id === job.job.job_id) };
    }, async value => {
      const { stored, job } = value;
      assert.equal(job.job.status, "done", JSON.stringify(job.job.failure));
      assert.notEqual(job.job.job_id, ga1.job.job_id);
      assert.equal(job.approved, false);
      assert.equal(stored.status, "partial");
      assert.equal(stored.stop_reason, "evaluation_limit");
      assert.equal(stored.new_evaluations_used, 4);
      assert.ok(stored.reused_count >= 1, "GA 2 reused nothing");
      assert.deepEqual(value.result.statements, ["S1", "S2", "S3", "S4", "S5", "S6"]);
      assert.equal(stored.reference.evaluation, "reused");
      assert.equal(stored.reference.result_handle, ga1Stored.reference.result_handle);
      const first = new Map(ga1Stored.generations.flatMap(gen => gen.individuals).filter(item => item.origin !== "carried")
        .map(item => [item.key, item]));
      for (const item of stored.generations.flatMap(gen => gen.individuals).filter(entry => entry.origin !== "carried")) {
        if (first.has(item.key)) {
          assert.equal(item.evaluation, "reused", `${item.key} was evaluated again`);
          assert.equal(item.result_handle, first.get(item.key).result_handle, "a reused individual does not cite GA 1's result");
          assert.equal(item.model_handle, first.get(item.key).model_handle);
        } else {
          assert.equal(item.evaluation, "computed");
          assert.ok(![...first.values()].some(entry => entry.result_handle === item.result_handle));
        }
      }
      const last = stored.generations.at(-1);
      assert.equal(last.complete, false, "the stopped generation is not marked");
      assert.ok(value.header.tabs.at(-1).text.includes("중간에 멈춤"), value.header.tabs.at(-1).text);
      assert.ok(value.header.statusText.includes("(partial)"), value.header.statusText);
      const newResults = value.after.results.filter(handle => !value.before.results.includes(handle));
      const newModels = value.after.models.filter(handle => !value.before.models.includes(handle));
      assert.equal(newResults.length, stored.new_evaluations_used, "new docking objects differ from new_evaluations_used");
      assert.equal(newModels.length, stored.new_evaluations_used, "new model objects differ from new_evaluations_used");
      assert.equal(value.published.length, stored.new_evaluations_used);
      assert.equal(job.budgetAfter.used, job.budgetBefore.used + value.facts.reserved, "GA 2 was not charged reserved_units once");
      assert.equal(value.facts.reserved, 10);
      const found = await checkWording("GA 2 results");
      assert.deepEqual(found, [], JSON.stringify(found));
      return { job: job.job.job_id, handle: job.handle, reused: stored.reused_count, newEvaluations: stored.new_evaluations_used,
        reserved: value.facts.reserved, units: [job.budgetBefore, job.budgetAfter], approval: value.approval };
    });
    handles.ga2 = ga2.job.handle;
    evidence.gaRuns.ga2 = ga2.job.handle;
  });

  // ---- GA 3: evaluation seed 7 (nothing reusable), cancelled from the screen while running
  await rec_.part("cancel", ["SG-cancel"], () => rec_.step("X01-cancel", ["SG-cancel"], "Evaluation seed 7, GA 1 seed, " +
    "generations 2, max new 4: 시작 전 확인 (reusable 0), 서열 GA 시작; once the reference row is recorded and one " +
    "individual is finished click 작업 취소: the job ends cancelled, a partial / cancelled summary keeps the finished " +
    "individuals (S2), no GA worker, modeling child, docking worker or qvina2 process remains, no refund", async () => {
    await fill(page, "sequence-ga-seed", CANCEL_SEED);
    control(evidence, "sequence-ga-seed", { value: CANCEL_SEED });
    await setParams(page, strings(GA3), evidence);
    const pf = await preflight(page, runA, evidence);
    const facts = preflightMatches(pf, { gaValues: GA3, space: expectedSpace, reusable: 0, referenceReusable: false });
    const approval = facts.shortfall.expensive_calls > 0 || facts.shortfall.wall_clock_s > 0
      ? approvalMatches(await approveLimits(page, runA, pf, evidence)) : null;
    const ran = await runGa(page, runA, evidence, { until: value => value.phase === "running" && value.finished >= 1 ||
      ["done", "failed", "cancelled"].includes(value.phase) });
    const processes = jobProcesses(runsDir);
    const cancel = st(page, "sequence-ga-job-cancel");
    await waitFor(page, async () => await enabled(cancel) ? true : null, "cancel enabled", 60000);
    await cancel.click();
    control(evidence, "sequence-ga-job-cancel", { finishedBefore: ran.phase.finished });
    const final = await waitFor(page, async () => {
      const value = await jobPhase(page);
      return value && ["cancelled", "failed", "done"].includes(value.phase) ? value : null;
    }, "job cancelled", 240000);
    const gone = await waitFor(page, async () => jobProcesses(runsDir).length === 0 ? true : null, "job processes gone", 60000)
      .then(() => true, () => false);
    // the partial summary is published after the group is verified empty; the job record names it once published
    const job = await waitFor(page, async () => {
      const record = await readApi(page, `/runs/${runA}/jobs/${enc(final.id)}`);
      return record.sequence_ga?.summary_handle ? record : null;
    }, "cancelled job names its summary", 60000).catch(() => readApi(page, `/runs/${runA}/jobs/${enc(final.id)}`));
    const handle = job.sequence_ga?.summary_handle ?? null;
    let stored = null, result = null, header = null;
    if (handle) {
      header = await openSummary(page, handle, evidence);
      const detail = await readApi(page, `/runs/${runA}/sequence_ga/results/${enc(handle)}`);
      stored = storedObject(runsDir, runA, handle);
      result = await resultEquals(page, ctx, header, detail, stored, evidence);
    }
    return { pf, facts, approval, ran, running: ran.phase, processes, final, gone, left: jobProcesses(runsDir), job, handle,
      stored, result, header, budgetAfter: await budgetUsed(page, runA) };
  }, async value => {
    assert.equal(value.running.phase, "running", "the GA ended before it could be cancelled");
    assert.ok(value.processes.some(item => /sequence_ga_worker\.py|sequence_model_worker\.py|qvina2/.test(item.command)),
      JSON.stringify(value.processes));
    assert.equal(value.job.status, "cancelled");
    assert.equal(value.gone, true, JSON.stringify(value.left));
    assert.ok(value.handle, "no partial summary was published");
    assert.equal(value.stored.status, "partial");
    assert.equal(value.stored.stop_reason, "cancelled");
    assert.ok(value.stored.new_evaluations_used >= 1);
    assert.equal(value.stored.reused_count, 0);
    assert.deepEqual(value.result.statements, ["S1", "S2", "S4", "S5", "S6"]);
    assert.equal(value.budgetAfter.used, value.ran.budgetBefore.used + value.facts.reserved, "a cancelled GA was refunded or overcharged");
    const found = await checkWording("cancelled results");
    assert.deepEqual(found, [], JSON.stringify(found));
    evidence.gaRuns.ga3 = value.handle;
    return { handle: value.handle, newEvaluations: value.stored.new_evaluations_used, approval: value.approval,
      processesWhileRunning: value.processes.map(item => item.command.slice(0, 120)) };
  }));

  // ---- GA 4: the implicit-H SDF (manual box around GA 1's box centre) → the reference row fails, no generation
  await rec_.part("reference-failed", ["SG-reference-failed", "SG-limit-approval"], () => rec_.step("F01-reference-failed",
    ["SG-reference-failed", "SG-limit-approval"], "Evaluation seed 20261004, the implicit-H SDF, 직접 입력 box at GA 1's stored " +
    "box centre with 20 Å sides, GA 3 values: 시작 전 확인 admits it (the server cannot see implicit hydrogens); after the " +
    "screen's raise, 서열 GA 시작: the wild-type reference row fails in docking (\"한국어 (code)\", score —, never 0), no " +
    "individual is evaluated, partial / reference_failed, no generation tab, S2; the reference detail shows its stored " +
    "model and no M18 result; reserved units charged", async () => {
    const center = ga1Stored.box.center_A.map(String);
    await chooseInputs(page, runA, { set: handles.tiny, sdf: handles.implicitH, box: { source: "manual", center,
      size: ["20", "20", "20"] }, ...DOCK }, evidence);
    await setParams(page, strings(GA4), evidence);
    const pf = await preflight(page, runA, evidence);
    const facts = preflightMatches(pf, { gaValues: GA4, space: expectedSpace, reusable: 0, referenceReusable: false });
    const approval = facts.shortfall.expensive_calls > 0 || facts.shortfall.wall_clock_s > 0
      ? approvalMatches(await approveLimits(page, runA, pf, evidence)) : null;
    const job = await runGa(page, runA, evidence);
    const header = await openSummary(page, job.handle, evidence);
    const detail = await readApi(page, `/runs/${runA}/sequence_ga/results/${enc(job.handle)}`);
    const stored = storedObject(runsDir, runA, job.handle);
    const result = await resultEquals(page, ctx, header, detail, stored, evidence);
    const reference = await openIndividual(page, runA, job.handle, "sequence-ga-reference-open", "wild_type", evidence);
    return { pf, facts, approval, job, header, stored, result, reference };
  }, async value => {
    const { stored, job, header } = value;
    assert.equal(job.job.status, "done", JSON.stringify(job.job.failure));
    assert.equal(stored.status, "partial");
    assert.equal(stored.stop_reason, "reference_failed");
    assert.deepEqual(stored.generations, []);
    assert.equal(stored.reference.state, "failed");
    assert.ok(stored.reference.reason_code, "the failed reference row has no reason");
    assert.equal(stored.reference.score, null);
    assert.equal(stored.reference.result_handle, null);
    assert.ok(stored.reference.model_handle, "the failed reference row has no stored model");
    assert.equal(stored.new_evaluations_used, 0);
    assert.deepEqual(value.result.statements, ["S1", "S2", "S4", "S5", "S6"]);
    assert.equal(header.noGenerations, 1);
    assert.equal(header.reference.lines[SCORE_HEADER], "—");
    assert.ok(!/\d/.test(header.reference.lines[SCORE_HEADER]));
    assert.ok(header.reference.lines["이유"].endsWith(`(${stored.reference.reason_code})`), header.reference.lines["이유"]);
    assert.match(header.reference.lines["이유"], /[가-힣]/);
    const facts = individualMatches(value.reference, ctx, { ...stored.reference, key: "wild_type", mutations: [] });
    assert.equal(job.budgetAfter.used, job.budgetBefore.used + value.facts.reserved, "reserved units were not charged");
    const found = await checkWording("reference failed");
    assert.deepEqual(found, [], JSON.stringify(found));
    evidence.gaRuns.ga4 = job.handle;
    return { handle: job.handle, reason: stored.reference.reason_code, approval: value.approval, reference: facts };
  }));

  // ---- late response: a held summary-detail response released after switching to another summary is not applied
  if (handles.ga2) await rec_.part("late-response", ["SG-late-response"], async () => {
    const held = [];
    let holding = true;
    const detailPath = `/api/runs/${runA}/sequence_ga/results/${handles.ga2}`;
    const matcher = url => decodeURIComponent(new URL(url).pathname) === detailPath;
    const handler = async route => {
      if (!holding || route.request().method() !== "GET") return route.continue();
      try { held.push({ route, response: await route.fetch() }); }
      catch (error) { held.push({ route, response: null, error: String(error).slice(0, 160) }); }
    };
    await page.route(matcher, handler);
    evidence.fixtureLabels.push(HOLD_LABEL);
    try {
      await rec_.step("H01-held", ["SG-late-response"], "Choose the GA 2 summary: its detail response is held; choose the " +
        "GA 1 summary: GA 1 is shown", async () => {
        await seqPanel(page).locator(`label${attr("data-ga-summary", handles.ga2)} input`).check();
        control(evidence, "sequence-ga-summary-radio", { handle: handles.ga2, held: true });
        await waitFor(page, async () => held.length >= 1 ? true : null, "held GA 2 detail", 30000);
        await seqPanel(page).locator(`label${attr("data-ga-summary", handles.ga1)} input`).check();
        control(evidence, "sequence-ga-summary-radio", { handle: handles.ga1 });
        await st(page, "sequence-ga-result").and(seqPanel(page).locator(attr("data-ga-handle", handles.ga1))).waitFor({ timeout: 60000 });
        return { held: held.length, shown: await st(page, "sequence-ga-result").getAttribute("data-ga-handle") };
      }, async value => { assert.equal(value.shown, handles.ga1); return value; });
      await rec_.step("H02-release", ["SG-late-response"], "Release the held GA 2 response: GA 1 stays shown and checked",
        async () => {
          holding = false;
          const released = [];
          for (const item of held) {
            if (!item.response) { released.push({ delivered: false, reason: item.error }); continue; }
            try { await item.route.fulfill({ response: item.response }); released.push({ delivered: true }); }
            catch (error) { released.push({ delivered: false, reason: String(error).slice(0, 160) }); }
          }
          await page.waitForTimeout(2500);
          return { released, shown: await st(page, "sequence-ga-result").getAttribute("data-ga-handle"),
            checked: await seqPanel(page).locator(`label${attr("data-ga-summary", handles.ga1)} input`).isChecked(),
            status: await st(page, "sequence-ga-result").getAttribute("data-stop-reason") };
        }, async value => {
          assert.equal(value.shown, handles.ga1, "the late GA 2 response replaced GA 1");
          assert.equal(value.checked, true);
          assert.equal(value.status, ga1Stored.stop_reason);
          return { released: value.released, layer: value.released.some(item => item.delivered)
            ? "request number (delivered, dropped)" : "not delivered" };
        });
    } finally {
      holding = false;
      for (const item of held) if (item.response) await item.route.fulfill({ response: item.response }).catch(() => undefined);
      await page.unroute(matcher, handler);
    }
  });

  // ---- report of GA 2 (S1–S6, reuse) → list, downloads → 지식·보고서 reopen; global budget = backend
  await rec_.part("report", ["SG-report"], async () => {
    const target = handles.ga2 ?? handles.ga1;
    const created = await rec_.step("Q01-report", ["SG-report"], "Choose the GA 2 summary; click 보고서 만들기: saved, listed " +
      "for this summary (no new GA object, no unit)", async () => {
      await openSummary(page, target, evidence);
      const units = await budgetUsed(page, runA);
      const summaries = objectHandles(runsDir, runA, "sequence_ga_result").length;
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${runA}/method_reports`, { timeout: 120000 });
      posted.catch(() => undefined);
      await st(page, "sequence-ga-report").click();
      control(evidence, "sequence-ga-report", { clicked: true });
      const response = await posted;
      const body = await response.json();
      await st(page, "sequence-ga-report-done").waitFor({ timeout: 60000 });
      await st(page, "sequence-ga-report-list").locator(`li${attr("data-report-handle", body.handle)}`).waitFor({ timeout: 60000 });
      return { status: response.status(), handle: body.handle, request: response.request().postDataJSON(), manifest: body.manifest,
        done: await st(page, "sequence-ga-report-done").getAttribute("data-report-handle"), units,
        unitsAfter: await budgetUsed(page, runA), summaries, summariesAfter: objectHandles(runsDir, runA, "sequence_ga_result").length };
    }, async value => {
      assert.equal(value.status, 201);
      assert.equal(value.done, value.handle);
      assert.equal(value.manifest.analysis_type, "sequence_ga");
      assert.equal(value.manifest.result_handle, target);
      assert.deepEqual(value.request, { result_handle: target });
      assert.deepEqual(value.unitsAfter, value.units);
      assert.equal(value.summariesAfter, value.summaries);
      return { handle: value.handle };
    });
    for (const [id, format] of [["sequence-ga-report-markdown", "markdown"], ["sequence-ga-report-json", "json"]]) {
      const route = `/runs/${runA}/reports/download?handle=${enc(created.handle)}&format=${format}`;
      await rec_.step(`Q02-${format}`, ["SG-report"], `Click ${format} 내려받기 in the area's report list; bytes = backend ` +
        "bytes; the Markdown carries the score name and the summary's S sentences", () => downloadByClick(app,
        st(page, "sequence-ga-report-list").locator(`li${attr("data-report-handle", created.handle)} [data-testid="${id}"]`)),
      async got => {
        control(evidence, id, { clicked: true });
        const bytes = fs.readFileSync(got.downloaded);
        assert.equal(sha(bytes), sha(await readBytes(page, route)), "downloaded bytes differ from the backend bytes");
        if (format === "markdown") {
          const text = bytes.toString("utf8");
          assert.ok(text.includes(SCORE_LABEL), "report lacks the score name");
          for (const id_ of statementIds(storedObject(runsDir, runA, target))) assert.ok(text.includes(S[id_]), `report lacks ${id_}`);
        }
        return { format, sha256: sha(bytes), bytes: bytes.length };
      });
    }
    const library = page.getByRole("region", { name: "보고서 보관함", exact: true });
    const reports = library.getByRole("region", { name: "저장된 보고서", exact: true });
    const content = library.getByRole("region", { name: "선택한 항목 내용", exact: true });
    await rec_.step("Q03-reopen", ["SG-report"], "Click 지식·보고서: the global budget equals the backend; the list shows 서열 GA " +
      "보고서; click it: the text equals the saved Markdown", async () => {
      await selectTab(page, "지식·보고서");
      const budget = await waitFor(page, async () => {
        const backend = await budgetUsed(page, runA);
        const shown = clean(await page.locator(".mw-app-budget").textContent());
        return shown === `expensive ${backend.used}/${backend.limit}` ? { shown, backend } : null;
      }, "global budget equals backend /budget", 15000);
      const row = reports.locator("li button").filter({ hasText: created.handle });
      await row.waitFor({ timeout: 30000 });
      const kind = clean(await row.locator(".mw-library-kind").textContent());
      await row.click();
      const pre = content.getByLabel(`저장된 보고서 ${created.handle}`, { exact: true });
      await pre.waitFor({ timeout: 30000 });
      return { kind, text: await pre.textContent(), budget };
    }, async value => {
      assert.equal(value.kind, "서열 GA 보고서");
      const saved = await readApi(page, `/runs/${runA}/reports/selected?handle=${enc(created.handle)}`);
      assert.equal(value.text, saved.markdown);
      return { kind: value.kind, markdownSha256: sha(Buffer.from(value.text)), budget: value.budget.shown };
    });
  });

  // ---- tabs: back to 단백질 공학 (remount: GET only, nothing opened); 구조 분석 stays mounted and hidden
  await rec_.part("tabs", ["SG-tabs"], () => rec_.step("Y01-tabs", ["SG-tabs"], "Click 단백질 공학: the area remounts and " +
    "reads its lists (GET only), lists the four summaries and opens none by itself; the M20, M21 and sequence GA areas in " +
    "that order; the 구조 분석 panel stays mounted but hidden (inert); the four tabs unchanged", async () => {
    const before = Date.now();
    await openProteinTab(page);
    await page.waitForTimeout(1500);
    return { state: await gaState(page), posts: posts(log, before),
      reads: [...new Set(log.filter(row => row.at >= before && row.method === "GET" && row.api).map(row => row.path))],
      result: await st(page, "sequence-ga-result").count(), checked: await st(page, "sequence-ga-list").locator("input:checked").count(),
      listed: await st(page, "sequence-ga-list").locator("label[data-ga-summary]").count(),
      structure: await page.evaluate(() => { const node = document.getElementById("mw-app-panel-structure");
        return node ? { shown: node.getAttribute("data-shown"), inert: node.inert } : null; }),
      tabs: await page.locator(".mw-app-tabs [role=tab]").evaluateAll(items => items.map(item =>
        ({ label: item.textContent.trim(), selected: item.getAttribute("aria-selected") }))),
      order: await page.locator("#mw-app-panel-protein [data-testid]").evaluateAll(items => items.map(item =>
        item.getAttribute("data-testid")).filter(id => ["mutation-panel", "mutation-model-panel", "sequence-ga-panel"].includes(id))) };
  }, async value => {
    assert.equal(value.state, "ready");
    assert.equal(value.posts, 0);
    assert.ok(value.reads.includes(`/api/runs/${runA}/sequence_ga/results`), JSON.stringify(value.reads));
    assert.equal(value.result, 0, "a summary was opened automatically");
    assert.equal(value.checked, 0);
    assert.equal(value.listed, Object.values(evidence.gaRuns).filter(Boolean).length);
    assert.deepEqual(value.structure, { shown: "false", inert: true });
    assert.deepEqual(value.tabs.map(item => item.label), TAB_LABELS);
    assert.deepEqual(value.tabs.filter(item => item.selected === "true").map(item => item.label), [TAB]);
    assert.deepEqual(value.order, ["mutation-panel", "mutation-model-panel", "sequence-ga-panel"]);
    const found = await checkWording("tab trip");
    assert.deepEqual(found, [], JSON.stringify(found));
    return value;
  }));

  await rec_.part("processes", ["SG-processes"], () => rec_.step("Z01-processes", ["SG-processes"], "After every GA: no GA " +
    "worker, modeling child, docking worker, guardian or qvina2 process remains under the runs folder", async () =>
    waitFor(page, async () => jobProcesses(runsDir).length === 0 ? { left: [] } : null, "no job processes", 60000)
      .catch(() => ({ left: jobProcesses(runsDir) })), async value => {
    assert.deepEqual(value.left, []);
    return value;
  }));

  evidence.budget = await readApi(page, `/runs/${runA}/budget`);
  evidence.wording = wording;
  for (const id of Object.values(evidence.runs).filter(Boolean)) evidence.providerCalls.push(await providerCalls(page, id));
  const wordingOk = wording.length >= 8 && wording.every(item => !item.found.length);
  rec_.append({ caseId: "WORDING", cases: ["SG-wording"], status: wordingOk ? "pass" : "fail", checks: wording });
  if (!wordingOk) evidence.partFailures.push({ part: "wording", cases: ["SG-wording"] });
  evidence.wordingPassed = wordingOk;
}

// ------------------------------------------------------------------ mode repro (two fresh runs, GA 1 through the screen)
async function modeRepro(session, input, rec_, evidence, log) {
  const { page } = session;
  const o = oracle();
  const runsDir = input["runs-dir"];
  evidence.inputs.push(...[STRUCTURE, PHENOL].map(fileRecord), ...o.files);
  evidence.repro = [];
  await waitForBoot(page);
  const expectedSpace = { positions: 3, candidates: 6, effective_max_mutations: 3, size: spaceSize([2, 2, 2], 3) };
  for (const label of ["R1", "R2"]) {
    await rec_.part(`repro-${label}`, ["SG-repro-runs"], async () => {
      const made = await rec_.step(`${label}-01-run`, ["SG-repro-runs"], "Click 구조 분석, 새 run; public_1ubq.cif, 구조 " +
        "불러오기, 전처리", async () => {
        const run = await newRun(page);
        const loaded = await uploadLoad(page, STRUCTURE);
        const prepared = await prepareManual(page);
        return { run, structure: loaded.handle, prepared: prepared.prepared };
      }, async value => value);
      evidence.runs[label] = made.run;
      const set = await rec_.step(`${label}-02-set`, ["SG-repro-runs"], "단백질 공학: the M20 tiny set as in main",
        async () => {
          await selectTab(page, TAB);
          await m20Ready(page);
          return m20Create(page, made.run, made.prepared, TINY, evidence);
        }, async value => {
          const stored = storedObject(runsDir, made.run, value.handle);
          assert.deepEqual(stored.candidates, o.tiny.candidates);
          return { handle: value.handle };
        });
      const sdf = await rec_.step(`${label}-03-sdf`, ["SG-repro-runs"], "리간드 설계·탐색: import the phenol SDF",
        () => importLigandSdf(page, made.run, PHENOL, evidence), async value => ({ handle: value }));
      const ran = await rec_.step(`${label}-04-ga`, ["SG-repro-runs"], "단백질 공학: the GA 1 inputs and values; 시작 전 확인 " +
        "보기; the screen's limit approval; 서열 GA 시작, 비싼 계산 승인, 작업 시작; done", async () => {
        await openProteinTab(page);
        await chooseInputs(page, made.run, { set: set.handle, sdf, box: { source: "ligand_range", margin: DOCK.margin }, ...DOCK },
          evidence);
        await setParams(page, strings(GA1), evidence);
        const budget = await readApi(page, `/runs/${made.run}/budget`);
        const pf = await preflight(page, made.run, evidence);
        const facts = preflightMatches(pf, { gaValues: GA1, space: expectedSpace, reusable: 0, referenceReusable: false, budget });
        const approval = approvalMatches(await approveLimits(page, made.run, pf, evidence));
        const job = await runGa(page, made.run, evidence);
        return { pf, facts, approval, job };
      }, async value => {
        assert.equal(value.job.job.status, "done", JSON.stringify(value.job.job.failure));
        assert.equal(value.job.approved, true);
        assert.equal(value.job.budgetAfter.used, value.job.budgetBefore.used + value.facts.reserved);
        assert.match(value.job.handle ?? "", /\/sequence_ga_result\//);
        return { job: value.job.job.job_id, handle: value.job.handle };
      });
      evidence.repro.push({ label, run: made.run, set: set.handle, sdf, job: ran.job.job.job_id, summary: ran.job.handle,
        args: ran.pf.request, timeoutS: ran.job.request.timeout_s, status: ran.job.job.status });
    });
  }
  evidence.budget = Object.fromEntries(await Promise.all(evidence.repro.map(async item =>
    [item.run, await readApi(page, `/runs/${item.run}/budget`)])));
  await rec_.part("repro-processes", ["SG-repro-runs"], () => rec_.step("R9-processes", ["SG-repro-runs"], "No job process " +
    "remains", async () => waitFor(page, async () => jobProcesses(runsDir).length === 0 ? { left: [] } : null,
    "no job processes", 60000).catch(() => ({ left: jobProcesses(runsDir) })), async value => {
    assert.deepEqual(value.left, []);
    return value;
  }));
  for (const id of Object.values(evidence.runs).filter(Boolean)) evidence.providerCalls.push(await providerCalls(page, id));
}

// ------------------------------------------------------------------ mode unavailable (backend without the environment)
async function modeUnavailable(session, input, rec_, evidence, log) {
  const { page } = session;
  evidence.fixtureLabels.push(input["fixture-label"] || UNAVAILABLE_LABEL);
  const capability = (await readApi(page, "/capabilities")).methods?.sequence_ga_design ?? null;
  evidence.capability = capability && { available: capability.available, reason_code: capability.reason_code };
  assert.ok(capability && capability.available === false, `backend reports the sequence GA available: ${JSON.stringify(capability)}`);
  assert.equal((await readApi(page, "/runs")).length, 0, "mode unavailable needs a fresh runs root");
  await waitForBoot(page);
  await rec_.step("V01-no-run", ["SG-no-run"], "No run yet: click 단백질 공학 → the sequence GA area shows the no-run reason " +
    "only (no numbers, no controls)", async () => {
    await selectTab(page, TAB);
    await st(page, "sequence-ga-no-run").waitFor({ timeout: 15000 });
    return { ...await noControls(page), reason: clean(await st(page, "sequence-ga-no-run").textContent()) };
  }, async value => {
    assert.equal(value.state, "unavailable");
    assert.ok(value.reason.includes(NO_RUN_REASON), value.reason);
    assert.ok(!/\d/.test(value.text), `a number is shown: ${value.text}`);
    assert.equal(value.controls, 0);
    return value;
  });
  const run = await rec_.step("V02-run", [], "Click 구조 분석, 새 run", () => newRun(page), async id => ({ run: id }));
  evidence.runs.A = run;
  await rec_.step("V03-unavailable", ["SG-unavailable"], "Click 단백질 공학: 사용할 수 없음 with the capability reason " +
    "(worker_missing); no numbers, no controls, no sequence GA requests", async () => {
    const before = Date.now();
    await selectTab(page, TAB);
    await st(page, "sequence-ga-unavailable").waitFor({ timeout: 15000 });
    await page.waitForTimeout(2000);
    const gaReads = log.filter(row => row.at >= before && row.path.includes("/sequence_ga")).map(row => `${row.method} ${row.path}`);
    return { ...await noControls(page), reason: clean(await st(page, "sequence-ga-unavailable").textContent()),
      code: await st(page, "sequence-ga-unavailable").getAttribute("data-reason-code"), gaReads };
  }, async value => {
    assert.equal(value.state, "unavailable");
    assert.ok(value.reason.startsWith("사용할 수 없음"), value.reason);
    assert.ok(value.reason.includes(`(${capability.reason_code})`), value.reason);
    assert.ok(value.reason.includes(capability.reason), value.reason);
    assert.equal(value.code, capability.reason_code);
    assert.ok(!/\d/.test(value.text), `a number is shown: ${value.text}`);
    assert.equal(value.controls, 0);
    assert.deepEqual(value.gaReads, [], "the unavailable area sent sequence GA requests");
    return value;
  });
  evidence.providerCalls.push(await providerCalls(page, run));
}

// ------------------------------------------------------------------ main
const RUNNERS = { main: modeMain, repro: modeRepro, unavailable: modeUnavailable };
// Cases the real environment cannot produce honestly here (never forged): kept with the tests that cover them.
const NOT_OBSERVED = [
  { case: "SG-individual-without-score", reason: "every individual of the 1UBQ + phenol GAs is scored (T1: all 26 keys " +
    "and the reference row scored), so no individual row without a score (null_result/failed) is shown; nothing is " +
    "forged. The reference row without a score (—, never 0) is observed (SG-reference-failed). Covered by " +
    "frontend/tests/sequence-ga.test.cjs ('individuals table: score-less rows last…', 'space lines and score cells…') and " +
    "backend/tests/test_sequence_ga_api.py::test_rows_without_a_score_are_null_never_zero." },
  { case: "SG-heavy-atom-warning", reason: "1UBQ projects 602 heavy atoms (< 4,890), so the server flag is false and the " +
    "warning line is absent (asserted on every preflight); no local public structure passing M7 exceeds it. Covered by " +
    "backend/tests/test_sequence_ga_inputs.py (heavy_atom_warning 4890/4891) and frontend/tests/sequence-ga.test.cjs " +
    "('preflight lines: …')." },
  { case: "SG-other-stop-reasons", reason: "generations_complete, space_exhausted, time_exhausted, worker_failed, " +
    "resource_exceeded and repeated_failure need other scores, hours, a killed worker, oversized output or five failing " +
    "models; covered by backend/tests/test_sequence_ga_worker.py (oracle vectors, clock, output bound, failures) and " +
    "test_sequence_ga_jobs.py (time_exhausted, worker_failed, recovery)." },
  { case: "SG-model-conditional-sentences", reason: "SL5 (HIS/CYS state differing from the reference outside the " +
    "mutated residues) and L6 (a new disulfide) need such a difference; the observed 1UBQ tiny-set models have none " +
    "(no Cys; the flow asserts each stored condition against the shown sentences and the empty difference text). " +
    "Covered by backend/tests/test_sequence_model_bundle.py (…_adds_sl5, …_adds_both_rows_and_l6) and " +
    "test_sequence_model_worker.py::test_protonation_and_disulfide_records_are_against_the_reference." },
  { case: "SG-dry-run", reason: "a dry-run run plans only and has no limit to raise; covered by " +
    "backend/tests/test_sequence_ga_jobs.py::test_dry_run_plans_only and frontend/tests/sequence-ga.test.cjs." },
];

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const evidence = { schema: "m23_sequence_ga_evidence@1", mode: input.mode, runs: {}, inputs: [], handles: {},
    fixtureLabels: [], providerCalls: [], partFailures: [], controls: {}, startedAt: new Date().toISOString(),
    notObserved: input.mode === "main" ? NOT_OBSERVED : [] };
  const session = await launchOffscreen({ url: input.url, artifacts: input.artifacts, interactive: false });
  const log = requestLog(session.page);
  const rec_ = recorder(session, input, evidence);
  let error = null;
  let proof = null;
  try {
    proof = await offscreenProof(session.app, session.page);
    await RUNNERS[input.mode](session, input, rec_, evidence, log);
  } catch (caught) {
    error = caught;
  } finally {
    try { proof = { ...await offscreenProof(session.app, session.page), atStart: proof }; } catch { /* keep the start proof */ }
    await session.close();
  }
  const cases = rec_.cases();
  if (input.mode === "main") cases["SG-wording"] = evidence.wordingPassed === true ? "pass" : "fail";
  const providerZero = evidence.providerCalls.length > 0 && evidence.providerCalls.every(item => item.zero);
  const passed = !error && evidence.partFailures.length === 0 && offscreenComplete(proof) && proof.nonLoopbackRequests === 0 &&
    Object.keys(cases).length > 0 && Object.values(cases).every(value => value === "pass") && providerZero;
  evidence.finishedAt = new Date().toISOString();
  evidence.error = error ? String(error.stack ?? error) : null;
  evidence.requestCount = log.length;
  evidence.fixtureLabels = [...new Set(evidence.fixtureLabels)];
  fs.writeFileSync(path.join(input.artifacts, "sequence-ga-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  fs.writeFileSync(path.join(input.artifacts, "sequence-ga-requests.jsonl"), log.map(row => JSON.stringify(row)).join("\n") + "\n");
  const harness = Object.fromEntries(["sequence-ga-flow.cjs", "docking-flow.cjs", "normal-flow.cjs", "driver.cjs", "main.cjs"]
    .map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m23_case_ledger_row@1", mode: input.mode, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", cases, runId: evidence.runs.A ?? null, runs: evidence.runs,
    handles: evidence.handles, inputs: evidence.inputs, fixtureLabels: evidence.fixtureLabels, controls: evidence.controls,
    gaArgs: evidence.gaArgs ?? null, gaRuns: evidence.gaRuns ?? null, repro: evidence.repro ?? null,
    budget: evidence.budget ?? null, notObserved: evidence.notObserved, buildId: buildId(), harness, offscreen: proof,
    externalRequestCount: proof ? proof.nonLoopbackRequests : null, providerCalls: evidence.providerCalls,
    providerCallsZero: providerZero, partFailures: evidence.partFailures, error: evidence.error,
    evidenceFile: path.basename(rec_.file), startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, runs: evidence.runs, cases }) + "\n");
  if (error) process.stderr.write(`sequence-ga-flow ${input.mode} failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`sequence-ga-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, oracle, needFor, shortfallFor, spaceSize, sortOracle, statementIds, projectPath,
  NOT_OBSERVED, GA1, GA2, GA3, GA4 };
