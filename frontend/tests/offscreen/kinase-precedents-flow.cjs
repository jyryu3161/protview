"use strict";

// M27 kinase precedent offscreen QA (spec §8, §10 오프스크린 QA). Real Electron offscreen page (isOffscreen,
// GPU/WebGL, paint). Every product mutation is a Playwright locator mouse/keyboard/file-chooser/select input; nothing
// calls application internals. Observation is read-only: data attributes and text of the 지식·보고서 "키나아제 전례"
// area (and the 잔기 번호 대응 area while maps are made), renderer request/response events, Electron paint frames,
// downloaded bytes and GET reads of the loopback API. Labeled renderer-route fixtures (request bodies altered in flight
// so that the real server refuses them) are recorded in the ledger and never produce a scientific value.
//
// The plan (--plan, written by scripts/m27_offscreen_acceptance.py) names the inputs, what the person enters and the
// expectations. In the fixture stage every precedent value is SYNTHETIC (backend/tests/fixtures/precedent/t8/
// SYNTHETIC-PROVENANCE-t8.md) and the expectations are counted from those records; in the real stage the expectations
// are the counts measured in T1. The screen is always compared with the stored result read back over the API.
// Real stage: the real kbase text is compared in memory only; step records keep IDs, counts, closed codes and digests
// (a failing step's error text is written to precedent-real-errors.txt, which the runner holds when it quotes kbase).
//
// Modes (the full sequence and the folder changes between them: scripts/m27_offscreen_acceptance.py):
//   empty    no precedent set: snapshot block reason + import command only, no numbers, no request controls
//   maps     real M15 numbering maps made by clicks (the plan's structures and chains)
//   main     the active set of the plan: snapshot, request defaults, previews, refusals, links, chain / target states,
//            target tabs, filters, sort, pages, record details, 429 size refusal, report, result list, dry-run run,
//            tab invariants, wording
//   unset    active.json moved aside: not_installed; the main mode's results open with 사용 중 스냅샷 없음
//   invalid  a set file tampered: snapshot_invalid; results open with 사용 중 스냅샷 없음
//   stale    another set active: every earlier result shows 이전 스냅샷 기준 (list and detail)
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { launchOffscreen, capture, downloadByClick } = require("./driver.cjs");
const { waitForViewer } = require("./normal-flow.cjs");

const REPO = path.resolve(__dirname, "../../..");
const MODES = ["empty", "maps", "main", "unset", "invalid", "stale"];
const KNOWLEDGE = "지식·보고서";
const TAB_LABELS = ["구조 분석", "단백질 공학", "리간드 설계·탐색", "지식·보고서"];
const TOOL = "link_kinase_precedents";
// Spec §9.1, verbatim (independent of the product constants).
const KP = {
  KP1: "전례는 kbase_kinase가 논문에서 기계로 추출한 미검수 기록이며 ProtView가 계산하거나 판정한 것이 아니다.",
  KP2: "방향과 크기는 kbase 규칙 v1이 숫자 또는 본문에서 산출한 값이며 논문의 결론도 ProtView의 판정도 아니고, 측정 변화마다 대상 역할(on_target·off_target·not_applicable)이 함께 있다.",
  KP3: "kbase 기계 검사는 kbase가 만들 때 한 결과를 그대로 보인 것이며 ProtView는 논문 원문과 대조하지 않았다. 파일 이름(moves·moves_flagged)은 모든 검사의 통과 여부를 뜻하지 않는다.",
  KP4: "전례가 없다는 표시는 포함한 파일에 기록이 없다는 뜻이며 선행 연구가 없다는 뜻이 아니다. 포함하지 않은 파일의 전례와 표적이 해석되지 않은 전례는 이 결과에 연결하지 않았다.",
  KP5: "표적(UniProt)이 같은 전례만 연결했다. 다른 키나아제의 전례는 연결하지 않았고, 변이·리간드·구조와의 일치는 판단하지 않았다.",
  KP6: "전례 개수와 목록 순서는 순위·추천·유망도·성공률을 뜻하지 않는다.",
};
const KT1 = "kbase_kinase 비공개 저장소 자료 · 이용 조건 명시 없음 · ChEMBL 유래 필드 포함 · 외부 공개 전 확인";
const UP1 = "원문 대조 안 함: ProtView에는 논문 원문이 없어 인용이 원문과 같은지 확인하지 않았다. 'ProtView 무결성 확인'은 가져온 파일과 레코드의 해시, 인용 길이, 논문 쪽 위치 존재만 뜻한다.";
const UP2 = n => `moves_flagged 파일의 전례 ${n}건은 포함하지 않았다.`;
const UP3 = "변이 표기는 kbase 기록 그대로이며 이 구조의 서열과 대조하지 않았다.";
const UP4 = "PDB 언급은 kbase가 기록한 것(근거 수준 포함)이며 이 구조와의 일치를 판단하지 않았다.";
const UP5 = n => `표적이 해석되지 않은 전례 ${n}건(세트 전체)이 있어 어느 체인에도 연결하지 못했다.`;
const LIMITATIONS = Object.values(KP);
const FIXED_PATTERNS = [...LIMITATIONS, KT1, UP1, UP3, UP4].map(text => new RegExp(escapeRe(text), "g"))
  .concat([new RegExp(escapeRe(UP2("N")).replace("N", "\\d+"), "g"), new RegExp(escapeRe(UP5("N")).replace("N", "\\d+"), "g")]);
// Screen text the person sees (the product's wording, copied here as the expectation).
const PROCESSED_LABEL = "kbase_kinase 가공본 · 미검수 · 기계 추출";
const IMPORT_COMMAND = ".venv/bin/python scripts/import_precedent_snapshots.py --from <kbase_kinase 경로>";
const STALE_TEXT = "이전 스냅샷 기준";
const NO_ACTIVE_TEXT = "사용 중 스냅샷 없음";
const NO_RESULTS_TEXT = "이 run에 키나아제 전례 결과가 없습니다.";
const NULL_NO_TARGET_TEXT = "빈 결과: 연결된 표적이 없습니다(체인이 연결되지 않음 — 체인 표의 이유 참조).";
const NO_PDB_TEXT = "PDB ID — (번호 대응에 PDB ID가 없음)";
const KBASE_FIELDS_HEADER = "그 밖의 kbase 필드(원본 값 그대로)";
const EFFECTS_HEADER = "측정 변화(kbase 추출 effects)";
// Removed before the wording check (case-insensitive, CSS may upper-case a heading): the spec's measured-change heading
// (it names the kbase field `effects`) and the kbase version key effect_rules_version, plain and Markdown-escaped.
const EXEMPT_TERMS = [EFFECTS_HEADER, "effect_rules_version", "effect\\_rules\\_version"]
  .map(term => new RegExp(escapeRe(term), "gi"));
const NULL = "—";
const EMPTY_LIST = "빈 목록 ([])";
const REASON = {
  unknown_field: "알 수 없는 요청 항목",
  numbering_map_invalid: "이 run의 번호 대응이 아니거나 도구가 읽는 항목이 없음",
  include_flagged_invalid: "moves_flagged 파일 전례 포함 여부가 true/false가 아님",
  chains_invalid: "체인 목록 오류(비었음·문자열 아님·중복)",
  chain_not_in_map: "번호 대응에 없는 체인",
  not_installed: "키나아제 전례 참조 스냅샷이 설치되지 않음",
  snapshot_invalid: "키나아제 전례 참조 스냅샷의 매니페스트·파일·레코드 해시나 형식이 맞지 않음",
  result_too_large: "결과 크기 상한 초과로 저장하지 않음",
  no_mapped_residues: "번호 대응에 mapped 잔기 행이 없음",
  multiple_accessions: "mapped 잔기의 accession이 둘 이상(융합 단백질 등)",
};
const coded = code => `${REASON[code]} (${code})`;
// Admission refusals: code → the form field the refusal is shown beside (null = the request line under the button).
const REFUSAL_FIELD = { unknown_field: null, numbering_map_invalid: "numbering_map", include_flagged_invalid: "include_flagged",
  chains_invalid: "chains", chain_not_in_map: "chains" };
const CHAIN_LABEL = { linked: "연결", not_linked: "연결 안 함" };
const TARGET_PHRASE = { none_in_included_files: "포함한 파일에 이 표적의 전례 기록 없음",
  not_in_kbase_references: "kbase에 이 표적 참조가 없음(전례 없음과 다름)" };
const FOLD_NULL = `${NULL} (kbase 기록에 값 없음, ProtView는 계산하지 않음)`;
// Spec §7 interpretive wording (M15 + M20 + M26 lists with English counterparts) and 성공률·검증됨·신뢰·효과·승자, 최고,
// checked after removing the fixed sentences, the measured-change heading and every string of the stored answers.
const FORBIDDEN = new RegExp(["안정성", "ΔΔG", "순위", "추천", "최적", "개선", "활성", "예측", "유망", "좋은", "나쁜", "안전",
  "점수", "에너지", "수소\\s*결합", "친화", "필수", "핵심", "중요", "효과", "메커니즘이\\s*유지", "성공률", "검증됨", "신뢰", "승자",
  "최고", "\\brank", "\\bbest\\b", "optimal", "improv", "recommend", "predict", "promising", "\\bgood\\b", "\\bsafe",
  "\\bactiv(?:e|ity)\\b", "\\bscor(?:e|ing)\\b", "energ", "hydrogen[\\s_-]?bond", "stabili", "affinity", "essential",
  "critical", "important", "\\bkey\\b", "\\beffects?\\b", "success[\\s_-]*rate", "\\bverified\\b", "\\btrust",
  "\\bwinner"].join("|"), "gi");
const ALTER_LABEL = "QA refusal fixture (labeled renderer route): the link_kinase_precedents request body is altered in " +
  "flight so that the real server refuses it; the server reply is shown unchanged";
const DRY_RUN_LABEL = "QA setup record: the dry-run run was made through POST /runs by the runner (the UI has no dry-run " +
  "control); every step on it here is a real click";
const PROVIDER_EVENT_TYPES = new Set(["egress", "egress_budget_settled", "viewer_dispatch_started"]);
const DEFAULT_QUERY = "sort=move_id&order=asc&limit=25&offset=0";

function escapeRe(text) { return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
/** Length and SHA-256 of a text that may quote kbase values: what a step returns instead of the text itself. */
const textDigest = text => ({ chars: (text ?? "").length, sha256: sha(Buffer.from(text ?? "", "utf8")) });
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const masked = text => (text ?? "").replace(/\d+(?:[.,]\d+)*/g, "#").replace(/[ \t]+/g, " ").trim();
const noDigit = text => !/\d/.test(text);

function options(argv) {
  const value = { url: "http://127.0.0.1:3000", artifacts: null, mode: null, plan: null, runs: null, "set-hash": null,
    "previous-set-hash": null };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!key.startsWith("--")) throw new Error(`Unknown argument ${key}`);
    const name = key.slice(2);
    if (!(name in value)) throw new Error(`Unknown argument ${key}`);
    value[name] = argv[++i];
  }
  if (!value.artifacts || !MODES.includes(value.mode)) throw new Error(
    `Usage: kinase-precedents-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> [--url http://127.0.0.1:3000] ` +
    "[--plan <plan.json>] [--runs <runA,runD>] [--set-hash <active set>] [--previous-set-hash <hash>]. " +
    "Full sequence: scripts/m27_offscreen_acceptance.py.");
  if (value.mode !== "empty" && !value.plan) throw new Error(`--plan is required for mode ${value.mode}`);
  if (["unset", "invalid", "stale"].includes(value.mode) && (!value.runs || !value["set-hash"]))
    throw new Error(`mode ${value.mode} needs --runs and --set-hash`);
  if (value.mode === "stale" && !value["previous-set-hash"]) throw new Error("mode stale needs --previous-set-hash");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  value.artifacts = path.resolve(value.artifacts);
  value.url = new URL("/", value.url).toString();
  value.planData = value.plan ? JSON.parse(fs.readFileSync(value.plan, "utf8")) : null;
  return value;
}

// ------------------------------------------------------------------ read-only observation
// Every precedent / map read answer seen (stored values and server strings): removed from screen text before the
// wording check. Held in memory only.
const SEEN = [];
async function readApi(page, route) {
  const response = await page.request.get(new URL(`/api${route}`, page.url()).toString());
  assert.equal(response.status(), 200, `${route}: HTTP ${response.status()}`);
  const value = await response.json();
  if (/precedent|numbering_maps/.test(route)) SEEN.push(value);
  return value;
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
const statusApi = page => readApi(page, "/precedent_reference/status");
async function resultList(page, run) {
  const items = [];
  for (;;) {
    const chunk = await readApi(page, `/runs/${run}/kinase_precedents?offset=${items.length}&limit=100`);
    items.push(...chunk.items);
    if (!chunk.items.length || items.length >= chunk.total) return { total: chunk.total, items };
  }
}
const detailApi = (page, run, handle, query = DEFAULT_QUERY) =>
  readApi(page, `/runs/${run}/kinase_precedents/${enc(handle)}?${query}`);
const mapList = page => readApi(page, `/runs/${page.__run}/numbering_maps?offset=0&limit=100`);
async function waitFor(page, probe, label, timeout = 60000) {
  const deadline = Date.now() + timeout;
  let last = null;
  while (Date.now() < deadline) {
    try { last = await probe(); if (last) return last; } catch (error) { last = String(error).slice(0, 200); }
    await page.waitForTimeout(150);
  }
  throw new Error(`${label}: timed out; last=${JSON.stringify(last)?.slice(0, 300)}`);
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
    rows.push({ at: Date.now(), method: request.method(), path: url.pathname, query: url.search.slice(1),
      api: url.pathname.startsWith("/api/"),
      tool: request.method() === "POST" ? (() => { try { return request.postDataJSON()?.tool ?? null; } catch { return null; } })() : null });
  });
  return rows;
}
const posts = (log, since) => log.filter(row => row.at >= since && row.method === "POST" && row.api)
  .map(row => `${row.path}${row.tool ? ` ${row.tool}` : ""}`);

// ------------------------------------------------------------------ evidence
const HANDLE_RE = /^(?:obj:\/\/[\w./-]+|[0-9a-f]{12,64}|run_[\w]+)$/;
// The leak check of scripts/m27_offscreen_acceptance.py (REAL_TEXT_MIN_CHARS there): real kbase strings from this many
// characters on (whitespace collapsed) must never reach committed evidence, so a step record keeps only shorter strings.
const REAL_TEXT_MIN_CHARS = 24;
/** Real stage: a value kept in step records only when it cannot quote kbase text by the runner's measure (numbers,
 * strings shorter than REAL_TEXT_MIN_CHARS after collapsing whitespace, handles, hashes, run IDs); longer text becomes
 * its length and SHA-256. */
function realSafe(value) {
  if (typeof value === "string")
    return value.replace(/\s+/g, " ").trim().length < REAL_TEXT_MIN_CHARS || HANDLE_RE.test(value) ? value
      : { textDigest: textDigest(value) };
  if (Array.isArray(value)) return value.map(realSafe);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, realSafe(v)]));
  return value;
}
function recorder(session, input, evidence) {
  const { app, page, artifacts } = session;
  const real = input.planData?.stage === "real";
  const file = path.join(artifacts, `precedent-${input.mode}.jsonl`);
  const errors = path.join(artifacts, "precedent-real-errors.txt");
  const append = row => fs.appendFileSync(file, JSON.stringify(row) + "\n");
  const safe = value => real ? realSafe(summarize(value)) : summarize(value);
  const errorText = (caseId, error) => {
    const text = String(error.stack ?? error);
    if (!real) return text;
    fs.appendFileSync(errors, `--- ${caseId}\n${text}\n`);
    return { errorDigest: textDigest(text), errorName: error?.name ?? null, heldIn: path.basename(errors) };
  };
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
      append({ caseId, cases, status: "pass", description, assertion: safe(assertion),
        blockedRequests: proof.status.blockedRequests.length, paintCount: proof.status.paintCount,
        screenshot: fileRecord(proof.screenshot), paint: fileRecord(proof.paint.path), durationMs: Date.now() - started });
      for (const id of cases) (evidence.observations[id] ??= []).push({ step: caseId, description });
      mark(cases, true);
      return result;
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* keep the primary failure */ }
      const html = await page.evaluate(() => document.querySelector('[data-testid="kinase-precedents-panel"]')?.outerHTML
        .slice(0, 120000) ?? "").catch(() => null);
      if (html) fs.writeFileSync(path.join(artifacts, `${caseId}-failure.panel.html`), html);
      append({ caseId, cases, status: "fail", description, error: errorText(caseId, error),
        actionResult: result === undefined ? null : real ? { digest: textDigest(JSON.stringify(result) ?? "") } : summarize(result),
        screenshot: proof && fileRecord(proof.screenshot), paint: proof && fileRecord(proof.paint.path),
        durationMs: Date.now() - started });
      mark(cases, false);
      throw error;
    }
  }
  /** An independent part: a failure is recorded (its cases fail) and the mode continues with the next part. */
  async function part(name, cases, work) {
    try { return await work(); } catch (error) {
      append({ caseId: `${name}-aborted`, cases: [], partCases: cases, status: "fail", description: `part ${name} aborted`,
        error: errorText(`${name}-aborted`, error) });
      evidence.partFailures.push({ part: name, cases, error: real ? "held (real stage)" : String(error).slice(0, 800) });
      mark(cases, false);
      return null;
    }
  }
  const cases = () => Object.fromEntries(Object.entries(caseRows).map(([id, list]) =>
    [id, list.length && list.every(Boolean) ? "pass" : "fail"]));
  return { step, part, append, file, cases, app, page, artifacts, real };
}
function summarize(value) {
  try { const text = JSON.stringify(value); return text.length > 6000 ? `${text.slice(0, 6000)}…` : JSON.parse(text); }
  catch { return String(value); }
}
function control(evidence, id, observed) { (evidence.controls[id] ??= []).push(observed); }

// ------------------------------------------------------------------ tabs, runs, structure screen
const tabButton = (page, label) => page.locator(".mw-app-tabs").getByRole("tab", { name: label, exact: true });
async function selectTab(page, label) {
  await tabButton(page, label).click();
  await waitFor(page, async () => await tabButton(page, label).getAttribute("aria-selected") === "true", `${label} selected`, 10000);
}
const globalRun = page => page.evaluate(() => document.querySelector(".mw-app-run")?.getAttribute("data-global-run") ?? null);
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
  page.__run = run;
  return run;
}
/** Choose a run in 구조 분석 (the only run control). ``viewer``: wait until its latest structure is shown, so the
 * structure screen's own viewer-session POST is done before a later "entering the tab posts nothing" check. */
async function chooseRun(page, run, viewer = false) {
  await selectTab(page, "구조 분석");
  await waitForBoot(page);
  await page.getByRole("tab", { name: /^run/i }).click();
  if (await globalRun(page) !== run) await page.locator("#run-choice").selectOption(run);
  await waitFor(page, async () => await globalRun(page) === run, `run ${run} selected`, 30000);
  if (viewer) await waitForViewer(page, value => value.sourceHandle !== null && value.catalogReady === true, 90000);
  page.__run = run;
}
/** Leave the 지식·보고서 tab and come back: the precedent area is mounted per tab entry and reads again. */
async function reenterKnowledge(page) {
  await selectTab(page, "단백질 공학");
  await openKnowledge(page);
}
async function uploadLoad(page, item) {
  await selectTab(page, "구조 분석");
  await page.getByRole("tab", { name: /^run/i }).click();
  const before = (await snapshot(page))?.sourceHandle ?? null;
  const chooser = page.waitForEvent("filechooser", { timeout: 30000 });
  await page.locator('input[type="file"]').first().click();
  await (await chooser).setFiles(item.file);
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: "구조 불러오기", exact: true }).click();
  const viewer = await waitForViewer(page, value => !!value.sourceHandle && value.sourceHandle !== before &&
    value.sourceHandle.includes("/structure/") && value.catalogReady === true, 120000);
  return { handle: viewer.sourceHandle, file: { name: path.basename(item.file), ...fileRecord(item.file),
    provenance: item.provenance } };
}
const structureHidden = page => page.evaluate(() => { const node = document.getElementById("mw-app-panel-structure");
  return node ? { shown: node.getAttribute("data-shown"), inert: node.inert } : null; });
/** Areas and digit-masked text of one tab once settled (no busy element, text stable over 0.7 s); text as a digest. */
async function tabSignature(page, label, id) {
  await selectTab(page, label);
  const tab = page.locator(`#mw-app-panel-${id}`);
  await tab.waitFor({ timeout: 15000 });
  const text = await waitFor(page, async () => {
    if (await tab.locator('[aria-busy="true"]').count()) return null;
    const a = masked(await tab.innerText());
    await page.waitForTimeout(700);
    const b = masked(await tab.innerText());
    return a === b && !(await tab.locator('[aria-busy="true"]').count()) ? b : null;
  }, `${label} settled`, 60000);
  const digest = textDigest(text);
  return { label, areas: await tab.locator("[data-testid$='-panel']").evaluateAll(items =>
    items.map(item => item.getAttribute("data-testid"))), textSha256: digest.sha256, chars: digest.chars };
}

// ------------------------------------------------------------------ M15 numbering maps (real clicks)
const numbering = page => page.locator("section.mw-numbering");
const nTestId = (page, id) => numbering(page).locator(`[data-testid="${id}"]`);
async function pickFromSearch(page, chain, accession) {
  await nTestId(page, `numbering-picker-${chain}`).click();
  await nTestId(page, "numbering-uniprot-query").fill(accession);
  await nTestId(page, "numbering-uniprot-search").click();
  const result = numbering(page).locator(`[data-testid="numbering-uniprot-picker"] button[data-uniprot-accession="${accession}"]`);
  await result.waitFor({ timeout: 30000 });
  await result.click();
  await waitFor(page, async () => (await nTestId(page, `numbering-accession-${chain}`).textContent()).includes(accession)
    ? true : null, `${accession} picked for ${chain}`, 15000);
}
/** One M15 map through the 잔기 번호 대응 area: structure, chains, PDB ID confirmation or picked accessions, 실행. */
async function makeMap(page, run, structureHandle, spec, evidence) {
  await selectTab(page, KNOWLEDGE);
  await numbering(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => await numbering(page).locator('[data-numbering-area="create"]').getAttribute("data-state")
    === "ready" ? true : null, "numbering create ready", 60000);
  const select = nTestId(page, "numbering-structure");
  if (await select.inputValue() !== "") await select.selectOption("");
  await select.selectOption(structureHandle);
  for (const chain of spec.chains)
    await waitFor(page, async () => await nTestId(page, `numbering-chain-${chain.chain}`).count() === 1 ? true : null,
      `chain ${chain.chain}`, 30000);
  await waitFor(page, async () => /업로드 원본|PDB ID가 없습니다|읽지 못했습니다/.test(await nTestId(page, "numbering-pdb-hint")
    .textContent()) ? true : null, "PDB ID suggestion", 30000);
  for (const chain of spec.chains) {
    await nTestId(page, `numbering-chain-${chain.chain}`).check();
    control(evidence, "numbering-chain", { map: spec.id, checked: chain.chain });
  }
  if (spec.pdbConfirm) {
    assert.equal(await nTestId(page, "numbering-pdb-id").inputValue(), spec.pdbConfirm, "the file's PDB ID suggestion");
    await nTestId(page, "numbering-pdb-confirm").check();
    control(evidence, "numbering-pdb-confirm", { map: spec.id, pdbId: spec.pdbConfirm });
  }
  for (const chain of spec.chains) {
    if (chain.accession === "sifts")
      await waitFor(page, async () => (await nTestId(page, `numbering-accession-${chain.chain}`).textContent())
        .includes(chain.expect) ? true : null, `SIFTS ${chain.expect} for ${chain.chain}`, 30000);
    else {
      await pickFromSearch(page, chain.chain, chain.accession);
      control(evidence, "numbering-uniprot-pick", { map: spec.id, chain: chain.chain, accession: chain.accession });
    }
  }
  const button = nTestId(page, "numbering-run");
  await waitFor(page, async () => await button.isEnabled() ? true : null, "실행 enabled", 30000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/commands` &&
    response.request().postDataJSON()?.tool === "map_residue_numbering", { timeout: 180000 });
  await button.click();
  const response = await posted;
  const body = await response.json();
  assert.equal(body.ok, true, `map_residue_numbering failed: ${JSON.stringify(body).slice(0, 300)}`);
  await nTestId(page, "numbering-run-result").filter({ hasText: "대응을 만들었습니다" }).waitFor({ timeout: 30000 });
  return { handle: body.handle.handle, args: response.request().postDataJSON().args };
}
async function checkMap(page, handle, spec) {
  const listed = (await mapList(page)).rows.find(row => row.handle === handle);
  assert.ok(listed, "the new map is not listed");
  assert.deepEqual(listed.chains, spec.chains.map(chain => chain.chain), "map chains");
  assert.equal(listed.pdb_id, spec.pdbConfirm ?? null, "map PDB ID");
  const counts = {};
  for (const chain of spec.chains) {
    const detail = listed.chain_details.find(item => item.chain_auth === chain.chain);
    counts[chain.chain] = detail.counts;
    if (chain.accession === "sifts") assert.ok((detail.sifts?.accessions ?? []).includes(chain.expect), `${chain.chain} SIFTS`);
    else assert.equal(detail.requested_uniprot_accession, chain.accession, `${chain.chain} picked accession`);
  }
  return { handle, chains: listed.chains, pdbId: listed.pdb_id, counts };
}

// ------------------------------------------------------------------ precedent area
const panel = page => page.locator('#mw-app-panel-knowledge [data-testid="kinase-precedents-panel"]');
const t = (page, id) => panel(page).locator(`[data-testid="kinase-precedents-${id}"]`);
const area = (page, name) => panel(page).locator(`section[data-precedent-area="${name}"]`);
const areaState = (page, name) => area(page, name).getAttribute("data-state", { timeout: 2000 }).catch(() => null);
const panelState = page => panel(page).getAttribute("data-precedent-state", { timeout: 2000 }).catch(() => null);
async function openKnowledge(page) {
  await selectTab(page, KNOWLEDGE);
  await panel(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => ["ready", "unavailable", "failed"].includes(await areaState(page, "snapshot")) &&
    ["ready", "empty", "failed"].includes(await areaState(page, "results")) ? true : null, "precedent area read", 60000);
}
/** The panel text for the wording check. The entries of "그 밖의 kbase 필드" are kbase paths and values as JSON text
 * (a path such as effects[0].evidence names the kbase field): removed like the other stored strings; the block's
 * summary and note stay checked. */
async function panelText(page) {
  return panel(page).evaluate(node => {
    let text = node.innerText;
    for (const item of node.querySelectorAll('[data-testid="kinase-precedents-kbase-fields"] dl')) {
      const entries = item.innerText;
      if (entries) text = text.split(entries).join("\n");
    }
    return text;
  });
}
/** The area's own wording: the panel text without expanded record details, whose fields are kbase values shown as
 * written (a kbase 0 there is a value, not a missing one; those "—" cells are checked one by one instead). */
async function productText(page) {
  return panel(page).evaluate(node => {
    let text = node.innerText;
    for (const item of node.querySelectorAll('[data-testid="kinase-precedents-record-detail"]')) text = text.split(item.innerText).join("\n");
    return text;
  });
}
function apiStrings(value, out = new Set()) {
  if (typeof value === "string") { if (value.length >= 2) out.add(value); }
  else if (Array.isArray(value)) for (const item of value) apiStrings(item, out);
  else if (value && typeof value === "object") for (const item of Object.values(value)) apiStrings(item, out);
  return out;
}
/** A stored string as the report writes it in Markdown (backend/mw/reports.py ``_md``: HTML escape, then a backslash
 * before Markdown syntax characters, line breaks as spaces). */
function mdEscape(value) {
  const html = String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
  return html.replace(/([\\`*_{}\[\]()#+.!|>~-])/g, "\\$1").replace(/\n/g, " ").replace(/\r/g, " ");
}
/** Forbidden words left after removing the fixed sentences, the measured-change heading and every stored string
 * (``markdown``: also each stored string in its Markdown-escaped form, as a report writes it). */
function forbiddenIn(text, stored = [], markdown = false) {
  let rest = text;
  for (const pattern of FIXED_PATTERNS) rest = rest.replace(pattern, " ");
  for (const pattern of EXEMPT_TERMS) rest = rest.replace(pattern, " ");
  const found = apiStrings([...SEEN, ...stored]);
  if (markdown) for (const item of [...found]) found.add(mdEscape(item));
  const strings = [...found].sort((a, b) => b.length - a.length);
  for (const item of strings) rest = rest.split(item).join(" ");
  return [...rest.matchAll(FORBIDDEN)].map(match => match[0]);
}
/** No bare "0" or "없음" cell / line (values not included, not computed or absent are "—" with the reason). */
function bareZeroOrNone(text) {
  return text.split(/[\n\t]/).map(item => item.trim()).filter(item => item === "0" || item === "없음");
}
const resultRadio = (page, handle) => panel(page).locator(`input[data-testid="kinase-precedents-result"][data-precedent-result="${handle}"]`);
/** Run ``action`` and return the detail answer the screen received (the GET it sent) once the detail area settled. */
async function detailRead(page, run, action) {
  const prefix = `/api/runs/${run}/kinase_precedents/`;
  const waiting = page.waitForResponse(response => response.request().method() === "GET" &&
    new URL(response.url()).pathname.startsWith(prefix), { timeout: 60000 });
  await action();
  const response = await waiting;
  assert.equal(response.status(), 200, `detail read HTTP ${response.status()}`);
  const body = await response.json();
  SEEN.push(body);
  const query = new URL(response.url()).search.slice(1);
  await waitFor(page, async () => ["ready", "empty"].includes(await areaState(page, "detail")) ? true : null, "detail settled", 60000);
  const again = await detailApi(page, run, body.handle, query);
  assert.deepEqual(again, body, "the same GET query gives another answer");
  return { body, query };
}
/** Open one stored result in its default view (default target, no filter, move_id order, first page). */
async function openResult(page, run, handle) {
  await openKnowledge(page);
  const radio = resultRadio(page, handle);
  await radio.waitFor({ timeout: 30000 });
  if (await radio.isChecked()) {
    const others = await panel(page).locator('input[data-testid="kinase-precedents-result"]').evaluateAll((items, own) =>
      items.map(item => item.getAttribute("data-precedent-result")).filter(value => value !== own), handle);
    if (!others.length) return { body: await detailApi(page, run, handle), query: DEFAULT_QUERY };
    await detailRead(page, run, () => resultRadio(page, others[0]).check());
  }
  const read = await detailRead(page, run, () => radio.check());
  assert.equal(read.body.handle, handle);
  return read;
}

// ---- display expectations (independent copies of the spec §8 wording)
function countTexts(counts) {
  return {
    chains: `${counts.chains}개`, linked_chains: `${counts.linked_chains}개`, not_linked_chains: `${counts.not_linked_chains}개`,
    targets: `${counts.targets}개`, records_moves: `${counts.records.moves}건`,
    records_moves_flagged: counts.records.moves_flagged === null ? `${NULL} (포함하지 않음)` : `${counts.records.moves_flagged}건`,
    excluded_moves_flagged: counts.excluded_moves_flagged === null ? `${NULL} (moves_flagged 파일을 포함해 미포함 수 없음)`
      : `${counts.excluded_moves_flagged}건`,
  };
}
function chainCells(chain) {
  const reason = chain.reason === null ? NULL : coded(chain.reason);
  return [chain.chain_auth, `${CHAIN_LABEL[chain.status]} (${chain.status})`, reason,
    chain.accession ?? `${NULL} (${chain.reason === null ? "연결하지 않음" : reason})`,
    chain.accessions.length ? chain.accessions.join(", ") : EMPTY_LIST,
    `mapped ${chain.mapped_residue_count} / 전체 ${chain.total_residue_count}`];
}
const includedCount = counts => counts.moves + (counts.moves_flagged ?? 0);
const targetPhrase = target => target.status === "precedents_found" ? `전례 ${includedCount(target.counts)}건` : TARGET_PHRASE[target.status];
function pageText(page, shown) {
  if (page.target === null) return `${NULL} (연결된 표적 없음)`;
  const head = `전체 ${page.total}건 · 필터 결과 ${page.filtered_total}건`;
  return shown ? `${head} · ${page.offset + 1}–${page.offset + shown}번째` : `${head} · 이 쪽에 없음`;
}
function badgeOf(activeSet) { return activeSet.set_hash === null ? NO_ACTIVE_TEXT : activeSet.same ? null : STALE_TEXT; }
function bibliographyText(record, books) {
  const book = books[record.source.pmid] ?? null;
  return `PMID ${record.source.pmid} · ` + (book === null ? `${NULL} (서지 없음)`
    : [book.title, book.journal, book.year].map(value => value ?? NULL).join(" · "));
}

/** Independent reader of a "a.b[2].c" path on a stored record (undefined when absent). */
function valueAtPath(value, pathText) {
  let node = value;
  for (const [, key, index] of pathText.matchAll(/([^.[\]]+)|\[(\d+)\]/g)) {
    if (node === null || typeof node !== "object") return undefined;
    node = index !== undefined ? node[Number(index)] : node[key];
  }
  return node;
}
const withinPath = (inner, outer) => inner === outer || inner.startsWith(`${outer}.`) || inner.startsWith(`${outer}[`);
// Paths the rest of the detail shows (spec §8 상세), independent of the product: never listed again.
const SHOWN_ELSEWHERE = ["move_id", "content_hash", "target", "source.pmid", "source.locations", "change", "structure_ref",
  "structure_link_reason", "structure_ref_from", "observation.text", "observation.quote", "observation.quote_truncated",
  "tags.site", "tags.goal", "tags.tactic", "review_status", "schema_version", "mutations", "proposed_tags", "figures",
  "extraction.model", "extraction.provider", "extraction.prompt_version", "extraction.run_at"];
const SHOWN_EFFECT_RE = /^effects\[\d+\]\.(metric|assay|target_ref|target_role|direction|direction_basis|magnitude_bucket|comparable|comparability_reason|fold_change)$/;
/** "그 밖의 kbase 필드" opened by a click versus the stored record: each entry is the stored value at its path as JSON
 * text, no path twice, never a left-out path or one the detail shows elsewhere, and the effect / observation / tradeoff
 * fields shown nowhere else are listed. Returns the entry count only (paths and values may quote kbase). */
function checkKbaseFields(block, record) {
  assert.ok(block && block.open === true, "그 밖의 kbase 필드 not opened");
  assert.equal(block.summary, KBASE_FIELDS_HEADER);
  const paths = block.rows.map(row => row.path);
  assert.equal(new Set(paths).size, paths.length, "a kbase field path listed twice");
  for (const row of block.rows) {
    assert.equal(row.dt, row.path, "kbase field label");
    assert.equal(row.value, JSON.stringify(valueAtPath(record, row.path)), `kbase field value at ${row.path}`);
    for (const outer of ["source.parser", "checks.cross_parser_numbers.measurements", ...SHOWN_ELSEWHERE])
      assert.ok(!withinPath(row.path, outer), `${row.path} is shown elsewhere or left out`);
    assert.ok(!SHOWN_EFFECT_RE.test(row.path) && !/^checks\.\w+\.status$/.test(row.path), `${row.path} is shown elsewhere`);
  }
  record.effects.forEach((effect, i) => {
    for (const key of ["assay_context", "chembl_crosscheck", "evidence"])
      if (key in effect) assert.ok(paths.includes(`effects[${i}].${key}`), `effects[${i}].${key} not listed`);
  });
  if ("evidence" in record.observation) assert.ok(paths.includes("observation.evidence"), "observation.evidence not listed");
  record.tradeoffs.forEach((tradeoff, i) => {
    if ("evidence" in tradeoff) assert.ok(paths.includes(`tradeoffs[${i}].evidence`), `tradeoffs[${i}].evidence not listed`);
  });
  return block.rows.length;
}

/** The opened result on screen versus the detail answer it received; the plan's expectation; returns IDs / counts. */
async function verifyDetail(page, body, expect, opts = {}) {
  const detail = panel(page).locator(`[data-testid="kinase-precedents-detail"][data-precedent-detail="${body.handle}"]`);
  await detail.waitFor({ timeout: 60000 });
  const shown = await detail.evaluate(node => {
    const text = el => el ? el.textContent.replace(/\s+/g, " ").trim() : null;
    const q = sel => node.querySelector(sel);
    const qa = sel => [...node.querySelectorAll(sel)];
    const target = q('[data-testid="kinase-precedents-target"]');
    return {
      nullResult: node.getAttribute("data-null-result"), includeFlagged: node.getAttribute("data-include-flagged"),
      marks: qa('[data-testid="kinase-precedents-detail-set"] [data-testid="kinase-precedents-snapshot-mark"]').map(text),
      counts: Object.fromEntries(qa('[data-testid="kinase-precedents-counts"] [data-precedent-count]').map(el =>
        [el.getAttribute("data-precedent-count"), text(el.querySelector("dd"))])),
      nullText: text(q('[data-testid="kinase-precedents-null-result"]')),
      chains: qa('[data-testid="kinase-precedents-chain-table"] tbody tr').map(tr => ({ chain: tr.getAttribute("data-chain"),
        status: tr.getAttribute("data-chain-status"), cells: [...tr.querySelectorAll("td")].map(text) })),
      chainUp5: text(q('[data-testid="kinase-precedents-chain-up5"]')),
      noTarget: text(q('[data-testid="kinase-precedents-no-target"]')),
      tabs: qa('[data-testid="kinase-precedents-target-tab"]').map(b => ({ accession: b.getAttribute("data-accession"),
        status: b.getAttribute("data-target-status"), selected: b.getAttribute("aria-selected") })),
      target: target && { accession: target.getAttribute("data-accession"), status: target.getAttribute("data-target-status"),
        statusText: text(target.querySelector('[data-testid="kinase-precedents-target-status"]')),
        up2: text(target.querySelector('[data-testid="kinase-precedents-up2"]')),
        refs: [...target.querySelectorAll('[data-testid="kinase-precedents-references"] tbody tr')].map(tr => tr.getAttribute("data-ref-id")),
        noRefs: text(target.querySelector('[data-testid="kinase-precedents-no-references"]')),
        counts: text(target.querySelector('[data-testid="kinase-precedents-target-counts"] > p')),
        variants: text(target.querySelector('[data-testid="kinase-precedents-variants"]')),
        tags: Object.fromEntries([...target.querySelectorAll('[data-testid="kinase-precedents-tags"] [data-tag-axis]')].map(el =>
          [el.getAttribute("data-tag-axis"), text(el)])),
        bases: text(target.querySelector('[data-testid="kinase-precedents-target-bases"]')),
        up3: text(target.querySelector('[data-testid="kinase-precedents-up3"]')) },
      pageText: text(q('[data-testid="kinase-precedents-page-text"]')),
      records: qa('[data-testid="kinase-precedents-record-row"]').map(tr => ({ moveId: tr.getAttribute("data-move-id"),
        file: tr.getAttribute("data-file"), cells: [...tr.querySelectorAll(":scope > td")].map(text),
        failNames: tr.querySelector('[data-testid="kinase-precedents-check-badge"]')?.getAttribute("data-fail-names") ?? null })),
      limitations: qa('[data-testid="kinase-precedents-limitations"] [data-limitation]').map(text),
    };
  });
  assert.equal(shown.nullResult, String(body.null_result));
  assert.equal(shown.includeFlagged, String(body.include_flagged));
  const badge = badgeOf(body.active_set);
  assert.deepEqual(shown.marks, badge ? [badge] : [], "detail snapshot mark");
  if (opts.badge !== undefined) assert.equal(badge, opts.badge, "expected snapshot mark");
  assert.deepEqual(shown.counts, countTexts(body.counts), "count rows");
  // an empty result with linked targets says "no record in the included files"; with no linked target it says that
  if (body.null_result && body.targets_overview.length)
    assert.ok((shown.nullText ?? "").includes("선행 연구가 없다는 뜻이 아닙니다"), "null result text");
  else if (body.null_result) assert.equal(shown.nullText, NULL_NO_TARGET_TEXT, "null result text without a linked target");
  else assert.equal(shown.nullText, null);
  // chain table (stored order)
  assert.deepEqual(shown.chains.map(row => row.chain), body.chains.map(chain => chain.chain_auth), "chain order");
  body.chains.forEach((chain, i) => {
    const row = shown.chains[i];
    assert.equal(row.status, chain.status);
    assert.deepEqual(row.cells.slice(0, 6), chainCells(chain), `chain ${chain.chain_auth} cells`);
    assert.ok(chain.cross_check ? row.cells[6] === "두 방법 교차 확인함 (cross_check true)"
      : row.cells[6].startsWith("교차 확인 안 함 (cross_check false)"), `${chain.chain_auth} cross check`);
  });
  const unresolved = body.set_summary.unresolved_target_records.moves + body.set_summary.unresolved_target_records.moves_flagged;
  assert.equal(shown.chainUp5, UP5(unresolved), "UP5 under the chain table");
  // targets
  if (!body.targets_overview.length) {
    assert.equal(shown.noTarget, "연결된 표적이 없어 전례 목록이 없습니다(연결한 체인이 없음).");
    assert.equal(shown.target, null);
    assert.equal(body.page.target, null);
  } else {
    assert.deepEqual(shown.tabs.map(tab => [tab.accession, tab.status]), body.targets_overview.map(item => [item.accession, item.status]));
    assert.deepEqual(shown.tabs.filter(tab => tab.selected === "true").map(tab => tab.accession), [body.page.target]);
    const target = body.targets_overview.find(item => item.accession === body.page.target);
    const ui = shown.target;
    assert.equal(ui.accession, target.accession);
    assert.equal(ui.status, target.status);
    assert.equal(ui.statusText, targetPhrase(target), "target status phrase");
    assert.ok(!/^0|^없음$/.test(ui.statusText), "a bare 0 / 없음 status");
    assert.equal(ui.up2, target.excluded_flagged === null ? null : UP2(target.excluded_flagged), "UP2");
    if (target.references.length) {
      assert.deepEqual(ui.refs, target.references.map(ref => ref.ref_id));
      assert.equal(ui.noRefs, null);
    } else assert.equal(ui.noRefs, `${NULL} (kbase에 이 표적 참조가 없음)`);
    const flagged = target.counts.moves_flagged === null ? `${NULL} (포함하지 않음)` : `${target.counts.moves_flagged}건`;
    assert.equal(ui.counts, `moves 파일 ${target.counts.moves}건 · moves_flagged 파일 ${flagged}`);
    const variants = target.counts.variants.map(item => `${item.variant} ${item.count}건`).join(" · ") || EMPTY_LIST;
    assert.equal(ui.variants, `변이 표기(variant)별 ${variants}`);
    for (const axis of ["site", "goal", "tactic"])
      assert.equal(ui.tags[axis], `${axis}별 ${target.counts.tags[axis].map(item => `${item.term} ${item.count}건`).join(" · ") || EMPTY_LIST}`);
    assert.equal(ui.bases, `표적 해석 근거별 ${target.counts.resolution_basis.map(item => `${item.basis} ${item.count}건`).join(" · ") || EMPTY_LIST}`);
    assert.equal(ui.up3, UP3);
  }
  // no linked target: the no-target sentence stands in for the whole records area (no pager)
  assert.equal(shown.pageText, body.page.target === null ? null : pageText(body.page, body.records.length), "page text");
  assert.deepEqual(shown.records.map(row => row.moveId), body.records.map(item => item.record.move_id), "record order");
  body.records.forEach((item, i) => {
    const row = shown.records[i];
    const record = item.record;
    assert.equal(row.file, item.file);
    assert.equal(row.cells[1], `${item.file} 파일`);
    assert.equal(row.cells[2], clean(record.target.variant));
    assert.equal(row.cells[4], record.target.resolution_basis);
    assert.equal(row.cells[5], clean(bibliographyText(record, body.bibliography)), `${record.move_id} bibliography`);
    const fail = Object.entries(record.checks).filter(([, value]) => value?.status === "fail").map(([name]) => name);
    const lookup = Object.entries(record.checks).filter(([, value]) => value?.status === "lookup_failed").map(([name]) => name);
    assert.equal(row.cells[7], `kbase 기계 검사 fail ${fail.length} · lookup_failed ${lookup.length}`);
  });
  assert.deepEqual(shown.limitations, body.limitations);
  assert.deepEqual(body.limitations, LIMITATIONS, "KP1–KP6 verbatim and in order");
  assert.deepEqual(bareZeroOrNone(await productText(page)), [], "a bare 0 or 없음 in the area");
  const found = forbiddenIn(await panelText(page), [body]);
  assert.deepEqual(found, [], `forbidden wording: ${found.join(", ")}`);
  if (expect) checkExpect(body, expect);
  return { handle: body.handle, nullResult: body.null_result, badge, includeFlagged: body.include_flagged,
    chains: body.chains.map(chain => [chain.chain_auth, chain.status, chain.reason, chain.accession]),
    targets: body.targets_overview.map(item => [item.accession, item.status, item.counts.moves, item.counts.moves_flagged,
      item.excluded_flagged, item.references.length]),
    page: body.page, records: body.records.map(item => item.record.move_id) };
}

/** The plan's expectation (synthetic counts or the T1 real counts) against the stored answer. */
function checkExpect(body, expect) {
  if (expect.nullResult !== undefined) assert.equal(body.null_result, expect.nullResult, "null_result");
  if (expect.chains) {
    assert.deepEqual(body.chains.map(chain => chain.chain_auth).sort(), Object.keys(expect.chains).sort(), "chains");
    for (const [name, [status, reason, accession]] of Object.entries(expect.chains)) {
      const chain = body.chains.find(item => item.chain_auth === name);
      assert.deepEqual([chain.status, chain.reason, chain.accession], [status, reason, accession], `chain ${name}`);
    }
  }
  if (expect.targets) {
    assert.deepEqual(body.targets_overview.map(item => item.accession), Object.keys(expect.targets).sort(), "targets");
    for (const [accession, want] of Object.entries(expect.targets)) {
      const got = body.targets_overview.find(item => item.accession === accession);
      assert.deepEqual([got.status, got.counts.moves, got.counts.moves_flagged, got.excluded_flagged, got.references.length, got.chains],
        [want.status, want.moves, want.movesFlagged, want.excluded, want.references, want.chains], `target ${accession}`);
      if (want.variants)
        assert.deepEqual(Object.fromEntries(got.counts.variants.map(item => [item.variant, item.count])), want.variants, `${accession} variants`);
    }
  }
}

/** Choose a map and chains, set the toggle and click 전례 연결 (real inputs); the opened result checked. */
async function linkCase(page, run, ctx, spec) {
  const mapHandle = ctx.maps[spec.map];
  await openKnowledge(page);
  await t(page, "request-form").waitFor({ timeout: 30000 });
  await setRequest(page, ctx, spec.map, mapHandle, spec.chains, spec.includeFlagged);
  const button = t(page, "link");
  await waitFor(page, async () => await button.isEnabled() ? true : null, "전례 연결 enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === TOOL,
  { timeout: 120000 });
  const read = await detailRead(page, run, async () => {
    await button.click();
    control(ctx.evidence, "kinase-precedents-link", { clicked: spec.id });
  });
  const response = await posted;
  const body = await response.json();
  assert.equal(body.ok, true, `link failed: HTTP ${response.status()}`);
  const args = response.request().postDataJSON().args;
  const made = body.handle.handle;
  await panel(page).locator(`[data-testid="kinase-precedents-link-done"][data-precedent-new-result="${made}"]`).waitFor({ timeout: 30000 });
  assert.deepEqual(args, { numbering_map: mapHandle, chains: spec.chains, include_flagged: spec.includeFlagged }, "request arguments");
  assert.equal(read.body.handle, made, "the opened result is not the new one");
  const verified = await verifyDetail(page, read.body, spec.expect, { badge: null });
  return { handle: made, args, verified };
}
async function setRequest(page, ctx, mapId, mapHandle, chains, includeFlagged) {
  const select = t(page, "numbering-map");
  if (await select.inputValue() !== mapHandle) {
    await select.selectOption(mapHandle);
    control(ctx.evidence, "kinase-precedents-numbering-map", { chosen: mapId });
  }
  await t(page, "chains").waitFor({ timeout: 30000 });
  const names = await panel(page).locator('[data-precedent-chain]').evaluateAll(items => items.map(item => item.getAttribute("data-precedent-chain")));
  for (const name of names) {
    const box = t(page, `chain-${name}`);
    const want = chains === null || chains.includes(name);
    if (await box.isChecked() !== want) {
      if (want) await box.check(); else await box.uncheck();
      control(ctx.evidence, "kinase-precedents-chain", { map: mapId, chain: name, checked: want });
    }
  }
  const toggle = t(page, "include-flagged");
  if (await toggle.isChecked() !== includeFlagged) {
    if (includeFlagged) await toggle.check(); else await toggle.uncheck();
    control(ctx.evidence, "kinase-precedents-include-flagged", { checked: includeFlagged });
  }
  assert.equal(await t(page, "flagged-note").count(), includeFlagged ? 1 : 0, "moves_flagged note");
  return names;
}

// ------------------------------------------------------------------ modes
async function modeEmpty(session, input, rec_, evidence, log) {
  const { page } = session;
  const run = await rec_.step("E01-new-run", [], "Click 구조 분석, 새 run (run E)", () => newRun(page), async id => ({ run: id }));
  evidence.runs.E = run;
  await rec_.step("E02-no-snapshot", ["P-no-snapshot"], "Click 지식·보고서 with no precedent set: snapshot block 사용할 수 " +
    "없음 + not_installed + import command; request block a reason only; no numbers, no controls", async () => {
    const started = Date.now();
    await openKnowledge(page);
    await waitFor(page, async () => await areaState(page, "snapshot") === "unavailable" ? true : null, "snapshot unavailable", 30000);
    await page.waitForTimeout(1000);
    return { snapshotText: clean(await area(page, "snapshot").textContent()), requestText: clean(await area(page, "request").textContent()),
      resultsText: clean(await area(page, "results").textContent()),
      command: clean(await t(page, "import-command").textContent()),
      reasonCode: await t(page, "snapshot-unavailable").getAttribute("data-reason-code"),
      controls: await area(page, "snapshot").locator("button, input, select, textarea, a").count() +
        await area(page, "request").locator("button, input, select, textarea, a").count(),
      forms: await t(page, "request-form").count(), setHash: await t(page, "set-hash").count(),
      results: await panel(page).locator('input[data-testid="kinase-precedents-result"]').count(), state: await panelState(page),
      requestState: await areaState(page, "request"), posts: posts(log, started), api: await statusApi(page),
      capability: (await readApi(page, "/capabilities")).methods?.kinase_precedents ?? null };
  }, async value => {
    assert.equal(value.api.installed, false, "the empty case needs an empty precedent reference folder");
    assert.equal(value.api.reason, "not_installed");
    assert.deepEqual([value.capability.available, value.capability.reason_code, value.capability.set_hash, value.capability.sources],
      [false, "not_installed", null, []]);
    assert.equal(value.reasonCode, "not_installed");
    assert.ok(value.snapshotText.includes("사용할 수 없음") && value.snapshotText.includes(coded("not_installed")), value.snapshotText);
    assert.equal(value.command, IMPORT_COMMAND);
    assert.ok(value.requestText.includes(coded("not_installed")) && value.requestText.includes(IMPORT_COMMAND), value.requestText);
    assert.ok(noDigit(value.snapshotText) && noDigit(value.requestText), "a number is shown in the unavailable blocks");
    assert.equal(value.controls, 0, "controls in the snapshot / request blocks");
    assert.equal(value.forms, 0);
    assert.equal(value.setHash, 0);
    assert.equal(value.results, 0);
    assert.equal(value.requestState, "unavailable");
    assert.ok(value.resultsText.includes(NO_RESULTS_TEXT), value.resultsText);
    assert.deepEqual(value.posts, []);
    assert.notEqual(value.state, "unavailable", "a missing set made the whole area unavailable");
    assert.deepEqual(forbiddenIn(await panelText(page)), []);
    return { reasonCode: value.reasonCode, controls: value.controls, state: value.state };
  });
  evidence.providerCalls.push(await providerCalls(page, run));
}

async function modeMaps(session, input, rec_, evidence) {
  const { page } = session;
  const plan = input.planData;
  const caseId = plan.stage === "real" ? "X-maps" : "P-maps-real-m15";
  if (plan.synthetic) evidence.fixtureLabels.push(plan.synthetic);
  const run = await rec_.step("A01-new-run", [caseId], "Click 구조 분석, 새 run (run A)", () => newRun(page), async id => ({ run: id }));
  evidence.runs.A = run;
  evidence.handles.structures = {};
  evidence.handles.maps = {};
  for (const [id, item] of Object.entries(plan.structures)) {
    const loaded = await rec_.step(`A02-upload-${id}`, [caseId], `Choose ${item.name}, click 구조 불러오기`,
      () => uploadLoad(page, item), async value => { assert.equal(value.file.sha256, item.sha256); return { handle: value.handle }; });
    evidence.inputs.push(loaded.file);
    if (item.provenance.includes("DERIVED")) evidence.fixtureLabels.push(item.provenance);
    evidence.handles.structures[id] = loaded.handle;
  }
  for (const spec of plan.maps) {
    const made = await rec_.step(`A03-map-${spec.id}`, [caseId], `지식·보고서 잔기 번호 대응: choose ${spec.structure}, chains ` +
      `${spec.chains.map(chain => `${chain.chain}:${chain.accession === "sifts" ? `SIFTS ${chain.expect}` : `UniProt 검색 ${chain.accession}`}`)
        .join(" ")}${spec.pdbConfirm ? `, tick 이 PDB ID가 맞습니다 (${spec.pdbConfirm})` : ", PDB ID not confirmed"}, 실행`,
    () => makeMap(page, run, evidence.handles.structures[spec.structure], spec, evidence), async value => checkMap(page, value.handle, spec));
    evidence.handles.maps[spec.id] = made.handle;
  }
  evidence.providerCalls.push(await providerCalls(page, run));
}

async function snapshotReady(page) {
  const api = await statusApi(page);
  const summary = t(page, "unresolved-names").locator("summary");
  await summary.click();
  const value = await panel(page).locator('[data-testid="kinase-precedents-snapshot-ready"]').evaluate(node => {
    const text = el => el ? el.textContent.replace(/\s+/g, " ").trim() : null;
    const one = id => text(node.querySelector(`[data-testid="kinase-precedents-${id}"]`));
    return { hash: one("set-hash"), title: node.querySelector('[data-testid="kinase-precedents-set-hash"]').getAttribute("title"),
      importedAt: one("imported-at"), kbaseCommit: one("kbase-commit"), distCommit: one("dist-commit"),
      distDate: one("dist-commit-date"), dirty: one("dirty"), kbVersion: one("kb-version"),
      versions: [...node.querySelectorAll('[data-testid="kinase-precedents-versions"] [data-version]')].map(el =>
        [el.getAttribute("data-version"), text(el.querySelector("dd"))]),
      files: [...node.querySelectorAll('[data-testid="kinase-precedents-files"] tbody tr')].map(tr =>
        [tr.getAttribute("data-file"), text(tr.querySelectorAll("td")[1])]),
      bibliography: [...node.querySelectorAll('[data-testid="kinase-precedents-bibliography-snapshot"] dd')].map(text),
      processed: one("processed-label"), kt1: one("kt1"), up5: one("snapshot-up5"),
      namesSummary: text(node.querySelector('[data-testid="kinase-precedents-unresolved-names"] summary')),
      nameRows: node.querySelectorAll('[data-testid="kinase-precedents-unresolved-names"] tbody tr').length,
      namesOpen: node.querySelector('[data-testid="kinase-precedents-unresolved-names"]').open,
      other: one("unresolved-other"),
      bases: [...node.querySelectorAll('[data-testid="kinase-precedents-bases"] li[data-basis]')].map(li => li.getAttribute("data-basis")) };
  });
  return { api, ...value };
}
function checkSnapshotReady(value, setHash, plan) {
  const api = value.api;
  assert.equal(api.installed, true);
  assert.equal(api.set_hash, setHash, "the backend's active set is not the plan's");
  assert.equal(value.title, setHash);
  assert.equal(value.hash, setHash.slice(0, 12));
  assert.equal(value.importedAt, api.imported_at);
  assert.equal(value.kbaseCommit, api.kbase.commit.slice(0, 12));
  assert.equal(value.distCommit, api.kbase.dist_commit === null ? `${NULL} (dist를 추적하는 커밋 없음)` : api.kbase.dist_commit.slice(0, 12));
  assert.equal(value.distDate, api.kbase.dist_commit_date ?? "날짜 없음");
  assert.equal(value.dirty, api.kbase.dirty ? "커밋되지 않은 변경 있음 (dirty true)" : "커밋되지 않은 변경 없음 (dirty false)");
  assert.equal(value.kbVersion, api.kbase.kb_version);
  assert.deepEqual(value.versions, [["schema_version", api.kbase.schema_version], ["effect_rules_version", api.kbase.effect_rules_version],
    ["vocab_version", api.kbase.vocab_version]]);
  assert.deepEqual(value.files, api.files.map(item => [item.name, `${item.rows}행`]));
  assert.deepEqual(value.bibliography, [api.bibliography.snapshot_id, api.bibliography.date, api.bibliography.license, `${api.bibliography.rows}행`]);
  assert.equal(value.processed, PROCESSED_LABEL);
  assert.equal(value.kt1, KT1);
  const summary = api.set_summary;
  const unresolved = summary.unresolved_target_records.moves + summary.unresolved_target_records.moves_flagged;
  assert.equal(value.up5, UP5(unresolved));
  assert.equal(unresolved, plan.unresolvedTotal, "UP5 N differs from the plan");
  assert.equal(value.namesOpen, true, "the unresolved-name table did not open");
  assert.equal(value.namesSummary, `표적이 해석되지 않은 전례의 서로 다른 이름 ${summary.unresolved_names_total}개(세트 전체)`);
  assert.equal(summary.unresolved_names_total, plan.unresolvedNamesTotal);
  assert.equal(value.nameRows, summary.unresolved_names.length);
  assert.equal(value.other, summary.unresolved_names_total > summary.unresolved_names.length
    ? `그 밖 ${summary.unresolved_names_total - summary.unresolved_names.length}개(목록 상한 100개)` : null);
  assert.deepEqual(value.bases, summary.resolution_basis_counts.map(item => item.basis));
  if (plan.stage === "real") {
    const want = plan.expect;
    assert.deepEqual(Object.fromEntries(api.files.map(item => [item.name, item.rows])), want.files);
    assert.equal(api.bibliography.rows, want.bibliographyRows);
    for (const [key, item] of Object.entries(want.kbase)) assert.equal(api.kbase[key], item, `kbase ${key}`);
  }
  return { setHash: api.set_hash, files: api.files.map(item => [item.name, item.rows]), bibliographyRows: api.bibliography.rows,
    unresolved, namesTotal: summary.unresolved_names_total, kbaseCommit: api.kbase.commit, distCommit: api.kbase.dist_commit,
    dirty: api.kbase.dirty };
}

// Built-in parts of the main mode → the case ids of the real stage (scripts/m27_offscreen_acceptance.py CASE_PLAN);
// an id without a real-stage counterpart stays as it is (recorded, not judged in that stage).
const REAL_CASE = { "P-snapshot-ready": "X-snapshot-real", "P-request-defaults": "X-request-defaults", "P-tabs": "X-tabs",
  "P-wording": "X-wording", "P-no-zero": "X-no-zero", "P-results-list": "X-results-list", "P-filters": "X-records-real",
  "P-paging": "X-records-real", "P-detail": "X-detail-real" };

async function modeMain(session, input, rec_, evidence, log) {
  const { page } = session;
  const plan = input.planData;
  const real = plan.stage === "real";
  const C = id => real ? REAL_CASE[id] ?? id : id;
  const run = plan.run;
  const ctx = { evidence, maps: plan.mapHandles, links: {} };
  evidence.runs.A = run;
  evidence.handles.maps = plan.mapHandles;
  evidence.handles.links = ctx.links;
  if (plan.synthetic) evidence.fixtureLabels.push(plan.synthetic);
  for (const info of Object.values(plan.derived?.maps ?? {})) evidence.fixtureLabels.push(info.label);
  await rec_.step("M01-run", [], `Choose run ${run} (maps made in the maps mode) in 저장된 run`, () => chooseRun(page, run, true),
    async () => ({ run: await globalRun(page) }));
  // ---- other tabs before any precedent work
  let before = null;
  await rec_.part("tabs-before", [C("P-tabs")], async () => {
    before = await rec_.step("M02-tabs-before", [C("P-tabs")], "Click 단백질 공학 and 리간드 설계·탐색: record their areas and " +
      "digit-masked text before any link", async () => ({ protein: await tabSignature(page, "단백질 공학", "protein"),
      ligand: await tabSignature(page, "리간드 설계·탐색", "ligand") }), async value => value);
  });
  // ---- snapshot block
  await rec_.part("snapshot", [C("P-snapshot-ready")], () => rec_.step("M03-snapshot", [C("P-snapshot-ready")],
    "Click 지식·보고서: the snapshot block of the active set; open the unresolved-name table", async () => {
      await openKnowledge(page);
      const value = await snapshotReady(page);
      control(evidence, "kinase-precedents-unresolved-names", { opened: true });
      return value;
    }, async value => checkSnapshotReady(value, plan.setHash, plan)));
  // ---- request defaults
  await rec_.part("defaults", [C("P-request-defaults")], () => rec_.step("M04-defaults", [C("P-request-defaults")],
    "The newest numbering map is pre-selected, nothing posted; every chain ticked; the toggle off; 전례 연결 enabled", async () => {
      const started = Date.now();
      await openKnowledge(page);
      await t(page, "request-form").waitFor({ timeout: 30000 });
      await waitFor(page, async () => await t(page, "numbering-map").inputValue() !== "" ? true : null, "map pre-selected", 30000);
      await t(page, "chains").waitFor({ timeout: 30000 });
      return { selected: await t(page, "numbering-map").inputValue(), maps: await mapList(page),
        options: await t(page, "numbering-map").locator("option").evaluateAll(items =>
          items.map(item => [item.value, item.textContent.replace(/\s+/g, " ").trim()])),
        chains: await panel(page).locator('input[data-testid^="kinase-precedents-chain-"]').evaluateAll(items =>
          items.map(item => [item.getAttribute("data-testid"), item.checked])),
        toggle: await t(page, "include-flagged").isChecked(), note: await t(page, "flagged-note").count(),
        link: await t(page, "link").isEnabled(), posts: posts(log, started) };
    }, async value => {
      const newest = [...value.maps.rows].sort((a, b) => b.created_seq - a.created_seq)[0];
      assert.equal(value.selected, newest.handle, "not the newest map");
      // every map choice names its PDB ID, or "—" with the reason when the map recorded none (never a bare "PDB —")
      const options = Object.fromEntries(value.options);
      for (const row of value.maps.rows) {
        const label = options[row.handle] ?? "";
        assert.ok(label.includes(row.pdb_id === null ? NO_PDB_TEXT : `PDB ${row.pdb_id} `), `map choice ${label}`);
        assert.ok(!label.includes("PDB — "), `bare PDB — in ${label}`);
      }
      assert.ok(value.chains.length >= 1 && value.chains.every(([, checked]) => checked), "a chain not ticked by default");
      assert.equal(value.toggle, false);
      assert.equal(value.note, 0);
      assert.equal(value.link, true);
      assert.deepEqual(value.posts, [], "entering the tab posted");
      return { selected: value.selected, chains: value.chains.length,
        mapsWithoutPdbId: value.maps.rows.filter(row => row.pdb_id === null).length };
    }));
  // ---- chain previews (server decides; the screen names what it will decide)
  for (const preview of plan.previews ?? []) await rec_.part(`preview-${preview.map}`, ["P-chain-previews"], () =>
    rec_.step(`M05-preview-${preview.map}`, ["P-chain-previews"], `Choose map ${preview.map}: the chain previews before the request`,
      async () => {
        await openKnowledge(page);
        await setRequest(page, ctx, preview.map, ctx.maps[preview.map], null, false);
        await waitFor(page, async () => (await panel(page).locator("[data-precedent-chain][data-preview-status]").count()) ===
          Object.keys(preview.chains).length ? true : null, "previews read", 60000);
        return panel(page).locator("[data-precedent-chain]").evaluateAll(items => items.map(item => ({
          chain: item.getAttribute("data-precedent-chain"), status: item.getAttribute("data-preview-status"),
          reason: item.getAttribute("data-preview-reason"),
          text: item.querySelector('[data-testid^="kinase-precedents-chain-preview-"]')?.textContent.replace(/\s+/g, " ").trim() })));
      }, async rows => {
        for (const [chain, [status, reason]] of Object.entries(preview.chains)) {
          const row = rows.find(item => item.chain === chain);
          assert.deepEqual([row.status, row.reason], [status, reason], `preview ${chain}`);
          if (status === "linked") assert.ok(row.text.includes("연결 예정: accession"), row.text);
          else assert.ok(row.text.includes(coded(reason)), row.text);
          for (const accession of preview.accessions?.[chain] ?? []) assert.ok(row.text.includes(accession), row.text);
        }
        return rows.map(row => [row.chain, row.status, row.reason]);
      }));
  // ---- admission refusals (labelled in-flight alterations; fixture stage)
  if (plan.refusals) await rec_.part("refusals", ["P-refusals"], () => refusalsPart(page, rec_, evidence, run, ctx, plan));
  // ---- the planned links
  for (const spec of plan.links) await rec_.part(`link-${spec.id}`, spec.cases, async () => {
    const result = await rec_.step(`L-${spec.id}`, spec.cases, `Link ${spec.id}: map ${spec.map}, chains ` +
      `${spec.chains === null ? "all (default)" : spec.chains.join(",")}, moves_flagged ${spec.includeFlagged ? "on" : "off"}; ` +
      "전례 연결 → the opened result equals the stored result and the plan", () => linkCase(page, run, ctx, spec),
    async value => ({ handle: value.handle, args: value.args, verified: value.verified }));
    ctx.links[spec.id] = result.handle;
  });
  // ---- 429 size refusal
  if (plan.tooLarge) await rec_.part("too-large", plan.tooLarge.cases, () => tooLargePart(page, rec_, run, ctx, plan.tooLarge));
  // ---- records: filters and sort (fixture), variant filter (real), pages, target tabs, record details
  if (plan.records && ctx.links[plan.records.link]) await rec_.part("records", [C("P-filters"), "P-sort"].filter((id, i, all) =>
    all.indexOf(id) === i), () => recordsPart(page, rec_, run, ctx, plan, C));
  if (plan.paging && ctx.links[plan.paging.link]) await rec_.part("paging", [C("P-paging")], () => pagingPart(page, rec_, run, ctx, plan, C));
  if (plan.targetTabs && ctx.links[plan.targetTabs.link]) await rec_.part("target-tabs", ["P-target-tabs"], () =>
    rec_.step("M20-target-tab", ["P-target-tabs"], `Open ${plan.targetTabs.link}, click the target tab ${plan.targetTabs.to}`, async () => {
      const handle = ctx.links[plan.targetTabs.link];
      await openResult(page, run, handle);
      const tab = panel(page).locator(`button[data-testid="kinase-precedents-target-tab"][data-accession="${plan.targetTabs.to}"]`);
      const read = await detailRead(page, run, () => tab.click());
      control(evidence, "kinase-precedents-target-tab", { clicked: plan.targetTabs.to });
      return read;
    }, async read => {
      assert.ok(read.query.includes(`target=${plan.targetTabs.to}`), read.query);
      assert.equal(read.body.page.target, plan.targetTabs.to);
      return verifyDetail(page, read.body, null, { badge: null });
    }));
  if (plan.detail && ctx.links[plan.detail.link]) await rec_.part("detail", [C("P-detail"), "P-fixed-notes"], () =>
    detailPart(page, rec_, run, ctx, plan, C));
  // ---- result list
  await rec_.part("results", [C("P-results-list"), C("P-no-zero")], () => rec_.step("M30-results", [C("P-results-list"), C("P-no-zero")],
    "Click 전례 결과 목록 다시 읽기: the list equals the stored list (newest first); a file not included is — with the reason",
    async () => {
      const started = Date.now();
      await openKnowledge(page);
      await t(page, "results-refresh").click();
      control(evidence, "kinase-precedents-results-refresh", { clicked: true });
      await waitFor(page, async () => await areaState(page, "results") === "ready" && log.some(row => row.at >= started &&
        row.method === "GET" && row.path === `/api/runs/${run}/kinase_precedents`) ? true : null, "result list re-read", 30000);
      return { labels: await panel(page).locator("label[data-precedent-result]").evaluateAll(items => items.map(item => ({
        handle: item.getAttribute("data-precedent-result"), nullResult: item.getAttribute("data-null-result"),
        includeFlagged: item.getAttribute("data-include-flagged"), stale: item.getAttribute("data-stale"),
        text: item.textContent.replace(/\s+/g, " ").trim() }))), api: await resultList(page, run), posts: posts(log, started) };
    }, async value => {
      assert.deepEqual(value.posts, []);
      assert.deepEqual(value.labels.map(item => item.handle), value.api.items.map(item => item.handle));
      value.api.items.forEach((item, i) => {
        const label = value.labels[i];
        assert.equal(label.nullResult, String(item.null_result));
        assert.equal(label.includeFlagged, String(item.include_flagged));
        assert.equal(label.stale, null);
        assert.equal(item.active, true);
        const pdb = item.pdb_id === null ? `PDB ID ${NULL} (번호 대응에 PDB ID가 없음)` : `PDB ${item.pdb_id}`;
        const flagged = item.records.moves_flagged === null ? `${NULL} (포함하지 않음)` : `${item.records.moves_flagged}건`;
        const want = [pdb, `체인 ${item.chain_count}개(연결 ${item.linked_chain_count}개)`, `표적 ${item.target_count}개`,
          `moves 파일 ${item.records.moves}건 · moves_flagged 파일 ${flagged}`].join(" · ") + (item.null_result ? " · 빈 결과" : "");
        assert.ok(label.text.startsWith(want), `list text: ${label.text}`);
      });
      assert.deepEqual(forbiddenIn(await panelText(page), [value.api]), []);
      return { listed: value.labels.length, items: value.api.items.map(item => ({ handle: item.handle, records: item.records,
        null_result: item.null_result, include_flagged: item.include_flagged })) };
    }));
  // ---- report
  if (plan.report && ctx.links[plan.report.link]) await rec_.part("report", plan.report.cases, () => reportPart(page, rec_, session, run, ctx, plan));
  // ---- dry-run run (record made by the runner over the loopback API; every step here is a real click)
  if (plan.dryRun?.run) await rec_.part("dry-run", plan.dryRun.link.cases, async () => {
    const runD = plan.dryRun.run;
    evidence.runs.D = runD;
    evidence.fixtureLabels.push(DRY_RUN_LABEL);
    const item = plan.structures[plan.dryRun.structure];
    const loaded = await rec_.step("M40-dry-run-upload", plan.dryRun.link.cases, `Choose the dry-run run in 저장된 run, upload ${item.name}`,
      async () => { await chooseRun(page, runD); return uploadLoad(page, item); }, async value => {
        assert.equal((await readApi(page, `/runs/${runD}`)).dry_run, true);
        return { handle: value.handle };
      });
    const map = await rec_.step("M41-dry-run-map", plan.dryRun.link.cases, "In the dry-run run: the M15 map by clicks",
      () => makeMap(page, runD, loaded.handle, plan.dryRun.map, evidence), async value => checkMap(page, value.handle, plan.dryRun.map));
    await reenterKnowledge(page);   // the precedent area read this run's maps when the tab was entered, before the map
    const dctx = { evidence, maps: { [plan.dryRun.map.id]: map.handle }, links: {} };
    const made = await rec_.step("M42-dry-run-link", plan.dryRun.link.cases, "In the dry-run run: 전례 연결 (real clicks); the result " +
      "is stored and opens", () => linkCase(page, runD, dctx, plan.dryRun.link), async value => {
      const list = await resultList(page, runD);
      assert.ok(list.items.some(entry => entry.handle === value.handle));
      return { handle: value.handle, verified: value.verified };
    });
    ctx.links[plan.dryRun.link.id] = made.handle;
    evidence.providerCalls.push(await providerCalls(page, runD));
    await chooseRun(page, run, true);
  });
  // ---- tab invariants and other tabs unchanged
  await rec_.part("tabs", [C("P-tabs")], () => rec_.step("M50-tabs", [C("P-tabs")], "Click 지식·보고서: 구조 분석 hidden and inert, " +
    "no run choice here; click 단백질 공학 and 리간드 설계·탐색: areas and masked text equal the record before the precedent work",
  async () => {
    await chooseRun(page, run, true);
    await openKnowledge(page);
    const value = { hidden: await structureHidden(page), runChoice: await page.locator("#mw-app-panel-knowledge #run-choice").count(),
      runChoiceStructure: await page.locator("#mw-app-panel-structure #run-choice").count(),
      tabs: await page.locator(".mw-app-tabs [role=tab]").evaluateAll(items => items.map(item => item.textContent.trim())),
      line: await globalRun(page) };
    value.after = { protein: await tabSignature(page, "단백질 공학", "protein"), ligand: await tabSignature(page, "리간드 설계·탐색", "ligand") };
    return value;
  }, async value => {
    assert.deepEqual(value.hidden, { shown: "false", inert: true });
    assert.equal(value.runChoice, 0);
    assert.equal(value.runChoiceStructure, 1);
    assert.deepEqual(value.tabs, TAB_LABELS);
    assert.equal(value.line, run);
    for (const name of ["protein", "ligand"]) {
      assert.ok(before?.[name], `${name} signature before was not recorded`);
      assert.deepEqual(value.after[name].areas, before[name].areas, `${name} areas`);
      assert.deepEqual([value.after[name].chars, value.after[name].textSha256], [before[name].chars, before[name].textSha256],
        `${name} text changed`);
    }
    return { hidden: value.hidden, areas: { protein: value.after.protein.areas, ligand: value.after.ligand.areas } };
  }));
  // ---- wording over every stored result
  await rec_.part("wording", [C("P-wording")], () => rec_.step("M51-wording", [C("P-wording")], "Open each stored result: no rank / " +
    "recommendation / verified / effect wording outside the fixed sentences and the stored strings", async () => {
    await openKnowledge(page);
    const list = await resultList(page, run);
    const checked = [];
    for (const item of list.items) {
      const read = await openResult(page, run, item.handle);
      await panel(page).locator(`[data-testid="kinase-precedents-detail"][data-precedent-detail="${item.handle}"]`).waitFor({ timeout: 60000 });
      checked.push({ handle: item.handle, found: forbiddenIn(await panelText(page), [read.body, list]) });
    }
    return checked;
  }, async value => {
    assert.ok(value.length >= 1);
    for (const item of value) assert.deepEqual(item.found, [], `${item.handle}: ${item.found.join(", ")}`);
    return { results: value.length };
  }));
  evidence.providerCalls.push(await providerCalls(page, run));
}

/** The five admission refusals through labelled in-flight alterations of the real request (the form is filled). */
async function refusalsPart(page, rec_, evidence, run, ctx, plan) {
  const mapHandle = ctx.maps[plan.refusals.map];
  const structure = (await mapList(page)).rows.find(row => row.handle === mapHandle).structure;
  const alter = {
    unknown_field: args => ({ ...args, qa_unknown_field: true }),
    numbering_map_invalid: args => ({ ...args, numbering_map: structure }),
    include_flagged_invalid: args => ({ ...args, include_flagged: "yes" }),
    chains_invalid: args => ({ ...args, chains: [] }),
    chain_not_in_map: args => ({ ...args, chains: ["QZ"] }),
  };
  if (!evidence.fixtureLabels.includes(ALTER_LABEL)) evidence.fixtureLabels.push(ALTER_LABEL);
  await openKnowledge(page);
  await t(page, "request-form").waitFor({ timeout: 30000 });
  await setRequest(page, ctx, plan.refusals.map, mapHandle, null, false);
  const done = [];
  for (const [code, change] of Object.entries(alter)) {
    const matcher = url => new URL(url).pathname === `/api/runs/${run}/commands`;
    const handler = async route => {
      const body = route.request().postDataJSON();
      if (route.request().method() !== "POST" || body?.tool !== TOOL) return route.continue();
      return route.continue({ postData: JSON.stringify({ ...body, args: change(body.args) }) });
    };
    await page.route(matcher, handler);
    try {
      done.push(await rec_.step(`F-${code}`, ["P-refusals"], `Click 전례 연결 with the labelled alteration for ${code}: the refusal ` +
        `"${coded(code)}" shows beside ${REFUSAL_FIELD[code] ?? "the request line"}; nothing stored`, async () => {
        const before = (await resultList(page, run)).total;
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === TOOL,
        { timeout: 60000 });
        await waitFor(page, async () => await t(page, "link").isEnabled() ? true : null, "전례 연결 enabled", 15000);
        await t(page, "link").click();
        const response = await posted;
        let body = null;
        try { body = await response.json(); } catch { body = null; }
        const line = panel(page).locator(`[data-testid="kinase-precedents-refusal"][data-reason-code="${code}"]`);
        await line.waitFor({ timeout: 30000 });
        return { status: response.status(), reason: body?.detail?.reason_code ?? null, before, after: (await resultList(page, run)).total,
          text: clean(await line.textContent()), field: await line.evaluate(node => node.closest("[data-precedent-field]")
            ?.getAttribute("data-precedent-field") ?? null), lines: await panel(page).locator('[data-testid="kinase-precedents-refusal"]').count() };
      }, async value => {
        assert.equal(value.status, 422);
        assert.equal(value.reason, code);
        assert.ok(value.text.includes(coded(code)), value.text);
        assert.equal(value.field, REFUSAL_FIELD[code], `${code} shown beside ${value.field}`);
        assert.equal(value.lines, 1);
        assert.equal(value.after, value.before, "a refused request stored a result");
        return { code, status: value.status, field: value.field };
      }));
    } finally { await page.unroute(matcher, handler); }
  }
  return done;
}

async function tooLargePart(page, rec_, run, ctx, spec) {
  return rec_.step("M10-too-large", spec.cases, `Choose map ${spec.map}, tick the moves_flagged toggle, click 전례 연결: 429 ` +
    "result_too_large with the size advice; nothing stored", async () => {
    await openKnowledge(page);
    await t(page, "request-form").waitFor({ timeout: 30000 });
    await setRequest(page, ctx, spec.map, ctx.maps[spec.map], null, spec.includeFlagged);
    const before = (await resultList(page, run)).total;
    const posted = page.waitForResponse(response => response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === TOOL,
    { timeout: 120000 });
    await t(page, "link").click();
    control(ctx.evidence, "kinase-precedents-link", { clicked: `too-large ${spec.map}` });
    const response = await posted;
    const body = await response.json();
    const line = panel(page).locator('[data-testid="kinase-precedents-refusal"][data-reason-code="result_too_large"]');
    await line.waitFor({ timeout: 30000 });
    const advice = await t(page, "size-advice").locator("li").evaluateAll(items => items.map(item => ({
      kind: item.getAttribute("data-advice"), accession: item.getAttribute("data-accession"), fits: item.getAttribute("data-fits") })));
    const value = { status: response.status(), detail: body.detail, before, after: (await resultList(page, run)).total,
      text: clean(await line.textContent()), advice };
    await t(page, "include-flagged").uncheck();
    return value;
  }, async value => {
    assert.equal(value.status, 429);
    assert.equal(value.detail.reason_code, "result_too_large");
    assert.equal(value.detail.limit, 1048576);
    assert.ok(value.detail.actual > value.detail.limit, "the refused size is not above the cap");
    assert.ok(value.text.includes(coded("result_too_large")) && value.text.includes("자르지 않음"), value.text);
    const without = value.advice.find(item => item.kind === "without_flagged");
    assert.equal(without?.fits, String(spec.expect.withoutFlaggedFits));
    assert.equal(value.detail.size_without_flagged <= value.detail.limit, spec.expect.withoutFlaggedFits);
    for (const [accession, fits] of Object.entries(spec.expect.targets)) {
      assert.equal(value.advice.find(item => item.kind === "target" && item.accession === accession)?.fits, String(fits), accession);
      assert.equal(value.detail.target_sizes.find(item => item.accession === accession).bytes <= value.detail.limit, fits, accession);
    }
    assert.equal(value.after, value.before, "a refused request stored a result");
    return { status: value.status, actual: value.detail.actual, limit: value.detail.limit,
      sizeWithoutFlagged: value.detail.size_without_flagged, targetSizes: value.detail.target_sizes, advice: value.advice };
  });
}

/** Screen rows of the current page equal the answer; the answer's filtered total and IDs equal the plan's counts. */
function checkPage(body, shownIds, want) {
  assert.deepEqual(shownIds, body.records.map(item => item.record.move_id), "screen rows differ from the server page");
  if (want) {
    assert.equal(body.page.filtered_total, want.total, "filtered total differs from the synthetic count");
    if (want.move_ids && want.total <= body.page.limit)
      assert.deepEqual([...shownIds].sort(), want.move_ids, "filtered records differ from the synthetic records");
  }
  return { query: body.page, ids: shownIds };
}
const shownIds = page => panel(page).locator('[data-testid="kinase-precedents-record-row"]').evaluateAll(items =>
  items.map(item => item.getAttribute("data-move-id")));

async function recordsPart(page, rec_, run, ctx, plan, C) {
  const spec = plan.records;
  const handle = ctx.links[spec.link];
  const filterCase = C("P-filters");
  const opened = await openResult(page, run, handle);
  assert.equal(opened.body.page.target, spec.target);
  const read = async action => detailRead(page, run, action);
  const clear = () => read(async () => { await t(page, "filters-clear").click(); control(ctx.evidence, "kinase-precedents-filters-clear", {}); });
  if (spec.variant) {   // real stage: the variant filter only
    await rec_.step("M11-variant", [filterCase], `Choose 변이 표기 ${spec.variant.value}: the server page equals the GET and the count`,
      () => read(async () => { await t(page, "filter-variant").selectOption(spec.variant.value);
        control(ctx.evidence, "kinase-precedents-filter-variant", { chosen: spec.variant.value }); }),
      async value => ({ ...checkPage(value.body, await shownIds(page), { total: spec.variant.total }), check: await verifyDetail(page, value.body, null) }));
    await clear();
    return;
  }
  const filters = spec.filters;
  await rec_.step("M11-file", [filterCase], "Choose 파일 moves_flagged", () => read(async () => {
    await t(page, "filter-file").selectOption("moves_flagged");
    control(ctx.evidence, "kinase-precedents-filter-file", { chosen: "moves_flagged" });
  }), async value => {
    assert.ok(value.query.includes("file=moves_flagged"), value.query);
    assert.ok((await shownIds(page)).length > 0 && value.body.records.every(item => item.file === "moves_flagged"));
    return checkPage(value.body, await shownIds(page), filters["file:moves_flagged"]);
  });
  await clear();
  const term = (axis, value) => panel(page).locator(`input[data-testid="kinase-precedents-filter-term"][data-axis="${axis}"][data-term="${value}"]`);
  const tick = (axis, value) => read(async () => { await term(axis, value).check(); control(ctx.evidence, "kinase-precedents-filter-term", { axis, term: value }); });
  await rec_.step("M12-site-gate", [filterCase], "Tick site gate", () => tick("site", "gate"),
    async value => checkPage(value.body, await shownIds(page), filters["site:gate"]));
  await rec_.step("M13-site-or", [filterCase], "Also tick site back (OR inside the axis)", () => tick("site", "back"),
    async value => { assert.ok(value.query.includes("site=gate&site=back"), value.query);
      return checkPage(value.body, await shownIds(page), filters["site:gate|back"]); });
  await rec_.step("M14-goal-and", [filterCase], "Tick goal potency (AND across axes)", () => tick("goal", "potency"),
    async value => checkPage(value.body, await shownIds(page), filters["site:gate|back&goal:potency"]));
  await clear();
  await rec_.step("M15-variant", [filterCase], "Choose 변이 표기 SYN-A1V", () => read(async () => {
    await t(page, "filter-variant").selectOption("SYN-A1V");
    control(ctx.evidence, "kinase-precedents-filter-variant", { chosen: "SYN-A1V" });
  }), async value => checkPage(value.body, await shownIds(page), filters["variant:SYN-A1V"]));
  await clear();
  await rec_.step("M16-search", [filterCase], `Type ${spec.searchToken}, click 검색`, () => read(async () => {
    await t(page, "search").fill(spec.searchToken);
    await t(page, "search-apply").click();
    control(ctx.evidence, "kinase-precedents-search", { typed: spec.searchToken, applied: "button" });
  }), async value => checkPage(value.body, await shownIds(page), filters[`q:${spec.searchToken}`]));
  const titleToken = spec.titleToken.toLowerCase();
  await rec_.step("M17-search-title", [filterCase], `Type ${titleToken} (bibliography title, lower case), press Enter`, () => read(async () => {
    await t(page, "search").fill(titleToken);
    await t(page, "search").press("Enter");
    control(ctx.evidence, "kinase-precedents-search", { typed: titleToken, applied: "Enter" });
  }), async value => checkPage(value.body, await shownIds(page), filters[`q:${titleToken}`]));
  await rec_.step("M18-search-too-long", [filterCase], "Type 101 characters, click 검색: refused on the screen, no read sent", async () => {
    const started = Date.now();
    await t(page, "search").fill("x".repeat(101));
    await t(page, "search-apply").click();
    control(ctx.evidence, "kinase-precedents-search", { typed: "101 characters", applied: "button" });
    await t(page, "search-error").waitFor({ timeout: 10000 });
    await page.waitForTimeout(500);
    return { error: clean(await t(page, "search-error").textContent()),
      reads: log_(page).filter(row => row.at >= started && row.method === "GET" && row.path.includes("/kinase_precedents/")).length };
  }, async value => {
    assert.equal(value.error, "검색어는 100자 이하입니다.");
    assert.equal(value.reads, 0);
    return value;
  });
  await clear();
  await rec_.step("M19-sort-pmid", ["P-sort"], "Choose 열 정렬 PMID, then 방향 내림차순", async () => {
    await read(async () => { await t(page, "sort").selectOption("pmid"); control(ctx.evidence, "kinase-precedents-sort", { chosen: "pmid" }); });
    return read(async () => { await t(page, "order").selectOption("desc"); control(ctx.evidence, "kinase-precedents-order", { chosen: "desc" }); });
  }, async value => {
    assert.ok(value.query.includes("sort=pmid") && value.query.includes("order=desc"), value.query);
    const pmids = value.body.records.map(item => Number(item.record.source.pmid));
    assert.ok(pmids.every((pmid, i) => i === 0 || pmids[i - 1] >= pmid), "PMIDs not in descending order");
    return checkPage(value.body, await shownIds(page), null);
  });
  await rec_.step("M19-sort-year", ["P-sort"], "Choose 열 정렬 서지 연도, 방향 오름차순 (no integer year last)", async () => {
    await read(async () => { await t(page, "sort").selectOption("year"); control(ctx.evidence, "kinase-precedents-sort", { chosen: "year" }); });
    return read(async () => { await t(page, "order").selectOption("asc"); control(ctx.evidence, "kinase-precedents-order", { chosen: "asc" }); });
  }, async value => {
    const years = value.body.records.map(item => { const year = value.body.bibliography[item.record.source.pmid]?.year;
      return typeof year === "string" && /^\d+$/.test(year) ? Number(year) : null; });
    const firstMissing = years.indexOf(null);
    const present = firstMissing === -1 ? years : years.slice(0, firstMissing);
    assert.ok(present.every((year, i) => i === 0 || present[i - 1] <= year), "years not ascending");
    assert.ok(firstMissing === -1 || years.slice(firstMissing).every(year => year === null), "a missing year is not last");
    assert.ok(firstMissing !== -1, "the page has no record without an integer year (the case is not observed)");
    return checkPage(value.body, await shownIds(page), null);
  });
  await read(async () => { await t(page, "sort").selectOption("move_id"); });
}
let LOG = null;
const log_ = () => LOG;

async function pagingPart(page, rec_, run, ctx, plan, C) {
  const spec = plan.paging;
  const caseId = C("P-paging");
  const opened = await openResult(page, run, ctx.links[spec.link]);
  assert.equal(opened.body.page.target, spec.target);
  await rec_.step("M21-page-next", [caseId], "Click 다음 쪽: the next server page", async () => {
    const first = { text: clean(await t(page, "page-text").textContent()), prev: await t(page, "page-prev").isDisabled(),
      ids: await shownIds(page), body: opened.body };
    const read = await detailRead(page, run, () => t(page, "page-next").click());
    control(ctx.evidence, "kinase-precedents-page-next", { clicked: true });
    return { first, read, nextDisabled: await t(page, "page-next").isDisabled(), text: clean(await t(page, "page-text").textContent()) };
  }, async value => {
    assert.equal(value.first.body.page.total, spec.total);
    assert.equal(value.first.text, `전체 ${spec.total}건 · 필터 결과 ${spec.total}건 · 1–${Math.min(25, spec.total)}번째`);
    assert.equal(value.first.prev, true);
    assert.equal(value.read.body.page.offset, 25);
    const last = Math.min(50, spec.total);
    assert.equal(value.text, `전체 ${spec.total}건 · 필터 결과 ${spec.total}건 · 26–${last}번째`);
    assert.equal(value.nextDisabled, spec.total <= 50);
    return checkPage(value.read.body, await shownIds(page), null);
  });
  await rec_.step("M22-page-prev", [caseId], "Click 이전 쪽: back to the first page", async () => {
    const read = await detailRead(page, run, () => t(page, "page-prev").click());
    control(ctx.evidence, "kinase-precedents-page-prev", { clicked: true });
    return read;
  }, async value => {
    assert.equal(value.body.page.offset, 0);
    return checkPage(value.body, await shownIds(page), null);
  });
}

async function detailPart(page, rec_, run, ctx, plan, C) {
  const spec = plan.detail;
  const opened = await openResult(page, run, ctx.links[spec.link]);
  assert.equal(opened.body.page.target, spec.target);
  const wanted = spec.expand ? Object.entries(spec.expand) : opened.body.records.slice(0, spec.expandFirst).map(item => [item.record.move_id, null]);
  for (const [moveId, want] of wanted) {
    await rec_.step(`M23-expand-${moveId}`, [C("P-detail"), "P-fixed-notes"], `Click 상세 펼치기 on ${moveId}: every stored field ` +
      "as written, the two check channels apart, UP1, UP4; click 그 밖의 kbase 필드: the rest of the stored copy", async () => {
      await panel(page).locator(`button[data-testid="kinase-precedents-record-toggle"][data-move-id="${moveId}"]`).click();
      control(ctx.evidence, "kinase-precedents-record-toggle", { opened: moveId });
      const node = panel(page).locator(`[data-testid="kinase-precedents-record-detail"][data-move-id="${moveId}"]`);
      await node.waitFor({ timeout: 15000 });
      await node.locator('[data-testid="kinase-precedents-kbase-fields"] > summary').click();
      control(ctx.evidence, "kinase-precedents-kbase-fields", { opened: moveId });
      return node.evaluate(el => {
        const text = item => item ? item.textContent.replace(/\s+/g, " ").trim() : null;
        const one = id => text(el.querySelector(`[data-testid="kinase-precedents-${id}"]`));
        const pairs = root => root ? Object.fromEntries([...root.querySelectorAll("dt")].map(dt => [text(dt), text(dt.nextElementSibling)])) : null;
        const quote = block => block && { ...pairs(block), truncated: text(block.querySelector('[data-quote-flag="truncated"]')),
          assembled: text(block.querySelector('[data-quote-flag="assembled"]')) };
        return { up1: one("up1"), bibliography: pairs(el.querySelector('[data-testid="kinase-precedents-detail-bibliography"]')),
          noBibliography: one("detail-no-bibliography"),
          locations: el.querySelectorAll('[data-testid="kinase-precedents-detail-locations"] dl').length,
          observation: quote(el.querySelector('[data-quote="observation"]')),
          tradeoffs: [...el.querySelectorAll('[data-quote^="tradeoff-"]')].map(quote),
          measures: [...el.querySelectorAll('[data-testid="kinase-precedents-measures"] tbody tr')].map(tr => ({
            role: tr.getAttribute("data-target-role"), basis: tr.getAttribute("data-direction-basis"),
            cells: [...tr.querySelectorAll("td")].map(text), fold: text(tr.querySelector('[data-cell="fold_change"]')) })),
          measuresNote: one("measures-note"), up4: one("up4"),
          structureLinks: el.querySelectorAll('[data-testid="kinase-precedents-detail-structure"] dl').length,
          checks: Object.fromEntries([...el.querySelectorAll('[data-testid="kinase-precedents-kbase-checks"] dd[data-check]')].map(dd =>
            [dd.getAttribute("data-check"), text(dd)])),
          kp3: one("kp3"),
          integrity: Object.fromEntries([...el.querySelectorAll('[data-testid="kinase-precedents-integrity"] dd[data-integrity]')].map(dd =>
            [dd.getAttribute("data-integrity"), text(dd)])),
          contentHash: text(el.querySelector('[data-testid="kinase-precedents-content-hash"] code')),
          kbaseFields: (block => block && { open: block.open, summary: text(block.querySelector("summary")),
            rows: [...block.querySelectorAll("dd[data-kbase-path]")].map(dd => ({ path: dd.getAttribute("data-kbase-path"),
              dt: text(dd.previousElementSibling), value: dd.textContent })) })(
            el.querySelector('[data-testid="kinase-precedents-kbase-fields"]')) };
      });
    }, async ui => {
      const item = opened.body.records.find(entry => entry.record.move_id === moveId);
      assert.ok(item, `${moveId} is not on the page`);
      const record = item.record;
      const book = opened.body.bibliography[record.source.pmid] ?? null;
      assert.equal(ui.up1, UP1);
      if (book) {
        assert.equal(ui.noBibliography, null);
        for (const key of ["title", "journal", "year", "doi", "pmc"])
          assert.equal(ui.bibliography[key], book[key] === null || book[key] === undefined ? NULL : clean(String(book[key])), `bibliography ${key}`);
      } else {
        assert.equal(ui.bibliography, null);
        assert.equal(ui.noBibliography, `${NULL} (서지 없음: 서지 스냅샷에 이 PMID의 행이 없음)`);
      }
      assert.equal(ui.locations, record.source.locations.length);
      assert.equal(ui.observation.text, clean(record.observation.text));
      assert.equal(ui.observation.quote, clean(record.observation.quote));
      assert.equal(ui.observation.truncated, record.observation.quote_truncated === true ? "인용 잘림 표시 (quote_truncated true)"
        : record.observation.quote_truncated === false ? "인용 잘림 표시 없음 (quote_truncated false)" : ui.observation.truncated);
      assert.equal(ui.tradeoffs.length, record.tradeoffs.length);
      record.tradeoffs.forEach((tradeoff, i) => assert.equal(ui.tradeoffs[i].quote, tradeoff.quote === null
        ? `${NULL} (kbase 기록에 인용 없음)` : clean(tradeoff.quote), `tradeoff ${i} quote`));
      assert.equal(ui.measures.length, record.effects.length);
      record.effects.forEach((effect, i) => {
        const row = ui.measures[i];
        assert.equal(row.role, effect.target_role);
        assert.equal(row.cells[6], effect.direction, "direction is the kbase word as written");
        assert.equal(row.cells[7], `kbase 규칙 v1 산출 (${effect.direction_basis})`);
        assert.equal(row.fold, effect.fold_change === null ? FOLD_NULL : String(effect.fold_change), `effect ${i} fold_change`);
      });
      assert.equal(ui.measuresNote, KP.KP2);
      assert.equal(ui.kp3, KP.KP3);
      assert.equal(ui.up4, UP4);
      assert.equal(ui.structureLinks - 1, record.structure_links.length, "structure link blocks (the first list is the three fields)");
      assert.deepEqual(Object.keys(ui.checks).sort(), Object.keys(record.checks).sort());
      for (const [name, value] of Object.entries(record.checks)) assert.equal(ui.checks[name], value.status, `check ${name}`);
      const integrity = item.integrity;
      assert.equal(ui.integrity.hash_verified, "레코드 해시 일치 (hash_verified true)");
      assert.equal(integrity.hash_verified, true);
      assert.equal(ui.integrity.quotes_within_limit, integrity.quotes_within_limit ? "모든 인용 25단어 이하 (quotes_within_limit true)"
        : "25단어를 넘는 인용 있음 (quotes_within_limit false)");
      assert.equal(ui.integrity.locations_have_page, "논문 쪽 위치 있음 (locations_have_page true)");
      assert.equal(ui.contentHash, record.content_hash);
      const kbaseFields = checkKbaseFields(ui.kbaseFields, record);
      if (want) {
        assert.equal(!!book, want.bibliography, "bibliography presence");
        assert.equal(integrity.quotes_within_limit, want.quotesWithinLimit, "quotes_within_limit");
        if (want.truncated) assert.equal(ui.observation.truncated, "인용 잘림 표시 (quote_truncated true)");
        if (want.assembled) assert.ok((ui.observation.assembled ?? "").startsWith("조합된 인용 표시 (quote_assembled)"), "quote_assembled");
        if (want.roles) assert.deepEqual(ui.measures.map(row => row.role), want.roles);
        if (want.foldNull) assert.deepEqual(ui.measures.map(row => row.fold === FOLD_NULL), want.foldNull);
        if (want.fail) assert.deepEqual(Object.entries(ui.checks).filter(([, s]) => s === "fail").map(([n]) => n), want.fail);
        if (want.lookupFailed) assert.deepEqual(Object.entries(ui.checks).filter(([, s]) => s === "lookup_failed").map(([n]) => n), want.lookupFailed);
        if (want.structureLinks !== undefined) assert.equal(record.structure_links.length, want.structureLinks);
        if (want.tradeoffNullQuote) assert.ok(ui.tradeoffs.some(item_ => item_.quote === `${NULL} (kbase 기록에 인용 없음)`));
      }
      assert.deepEqual(bareZeroOrNone(await productText(page)), []);
      assert.deepEqual(forbiddenIn(await panelText(page), [opened.body]), []);
      return { moveId, bibliography: !!book, quotesWithinLimit: integrity.quotes_within_limit, effects: record.effects.length,
        foldNull: record.effects.map(effect => effect.fold_change === null), roles: record.effects.map(effect => effect.target_role),
        kbaseFields };
    });
  }
  const [firstId] = wanted[0];
  await rec_.step("M24-collapse", [C("P-detail")], `Click 상세 접기 on ${firstId}`, async () => {
    await panel(page).locator(`button[data-testid="kinase-precedents-record-toggle"][data-move-id="${firstId}"]`).click();
    control(ctx.evidence, "kinase-precedents-record-toggle", { closed: firstId });
    await page.waitForTimeout(300);
    return { open: await panel(page).locator(`[data-testid="kinase-precedents-record-detail"][data-move-id="${firstId}"]`).count() };
  }, async value => { assert.equal(value.open, 0); return value; });
}

/** Every page of one target (records and the bodies, whose bibliography the report also names). */
async function allRecords(page, run, handle, target) {
  const records = [];
  const bodies = [];
  for (let offset = 0; ; offset += 100) {
    const body = await detailApi(page, run, handle, `target=${enc(target)}&sort=move_id&order=asc&limit=100&offset=${offset}`);
    records.push(...body.records);
    bodies.push(body);
    if (body.page.filtered_total === null || offset + 100 >= body.page.filtered_total) return { records, bodies };
  }
}

async function reportPart(page, rec_, session, run, ctx, plan) {
  const cases = plan.report.cases;
  const handle = ctx.links[plan.report.link];
  const created = await rec_.step("M31-report", cases, "Open the result, click 보고서 만들기", async () => {
    await openResult(page, run, handle);
    const posted = page.waitForResponse(response => response.request().method() === "POST" &&
      new URL(response.url()).pathname === `/api/runs/${run}/method_reports`, { timeout: 60000 });
    await t(page, "report").click();
    control(ctx.evidence, "kinase-precedents-report", { clicked: true });
    const response = await posted;
    const body = await response.json();
    await t(page, "report-done").waitFor({ timeout: 30000 });
    return { status: response.status(), handle: body.handle, analysisType: body.manifest?.analysis_type,
      resultHandle: body.manifest?.result_handle, request: response.request().postDataJSON(),
      done: await t(page, "report-done").getAttribute("data-report-handle"), mark: await t(page, "report-mark").count() };
  }, async value => {
    assert.equal(value.done, value.handle);
    assert.equal(value.analysisType, "kinase_precedents");
    assert.equal(value.resultHandle, handle);
    assert.deepEqual(value.request, { result_handle: handle });
    assert.equal(value.mark, 0, "a snapshot mark on a report of the active set");
    return { handle: value.handle, status: value.status };
  });
  ctx.evidence.handles.report = created.handle;
  const stored = await detailApi(page, run, handle);
  const texts = new Set();
  const pages = [stored];
  for (const target of stored.targets_overview) {
    const all = await allRecords(page, run, handle, target.accession);
    pages.push(...all.bodies);
    for (const item of all.records) {
      const record = item.record;
      for (const value of [record.observation.text, record.observation.quote, ...record.tradeoffs.flatMap(entry => [entry.text, entry.quote])])
        if (typeof value === "string" && value.length >= 12) texts.add(value);
    }
  }
  for (const [id, format] of [["report-markdown", "markdown"], ["report-json", "json"]]) {
    const route = `/runs/${run}/reports/download?handle=${enc(created.handle)}&format=${format}`;
    await rec_.step(`M32-download-${format}`, cases, `Click ${id}: bytes non-empty and equal the backend bytes`, () =>
      downloadByClick(session.app, t(page, id)), async downloaded => {
      const bytes = fs.readFileSync(downloaded.downloaded);
      const saved = await readBytes(page, route);
      assert.ok(bytes.length > 0);
      assert.equal(sha(bytes), sha(saved), "downloaded bytes differ from the backend bytes");
      const text = bytes.toString("utf8");
      if (format === "markdown") {
        for (const sentence of [...LIMITATIONS, KT1]) assert.ok(text.includes(sentence), "the report lacks a fixed sentence");
        const unresolved = stored.set_summary.unresolved_target_records.moves + stored.set_summary.unresolved_target_records.moves_flagged;
        assert.ok(text.includes(UP5(unresolved)), "the report lacks UP5");
        for (const target of stored.targets_overview)
          if (target.excluded_flagged !== null) assert.ok(text.includes(UP2(target.excluded_flagged)), "the report lacks UP2");
        const quoted = [...texts].filter(item => text.includes(item)).length;
        assert.equal(quoted, 0, "the report quotes an observation, quote or tradeoff text");
        const found = forbiddenIn(text, pages, true);
        assert.deepEqual(found, [], `report wording: ${found.join(", ")}`);
      } else {
        const manifest = JSON.parse(text);
        assert.equal(manifest.analysis_type ?? manifest.manifest?.analysis_type, "kinase_precedents");
      }
      return { format, sha256: sha(bytes), bytes: bytes.length, quoteStringsChecked: texts.size };
    });
  }
  const library = page.getByRole("region", { name: "보고서 보관함", exact: true });
  const reports = library.getByRole("region", { name: "저장된 보고서", exact: true });
  const content = library.getByRole("region", { name: "선택한 항목 내용", exact: true });
  await rec_.step("M33-library", cases, "The knowledge-tab report list shows 키나아제 전례 보고서; click it; content = stored Markdown",
    async () => {
      await selectTab(page, KNOWLEDGE);
      const row = reports.locator("li button").filter({ hasText: created.handle });
      await row.waitFor({ timeout: 30000 });
      const kind = clean(await row.locator(".mw-library-kind").textContent());
      await row.click();
      const pre = content.getByLabel(`저장된 보고서 ${created.handle}`, { exact: true });
      await pre.waitFor({ timeout: 30000 });
      // the report may quote kbase titles: only its length and hash leave this action, even on failure
      return { kind, ...textDigest(await pre.textContent()) };
    }, async value => {
      assert.equal(value.kind, "키나아제 전례 보고서");
      const saved = textDigest((await readApi(page, `/runs/${run}/reports/selected?handle=${enc(created.handle)}`)).markdown);
      assert.deepEqual([value.chars, value.sha256], [saved.chars, saved.sha256], "shown report differs from the stored Markdown");
      return { kind: value.kind, markdownSha256: value.sha256 };
    });
}

/** After the runner changed the precedent folder: the main mode's stored results still open, with the snapshot mark. */
async function modeAfter(session, input, rec_, evidence, log) {
  const { page } = session;
  const runs = input.runs.split(",").filter(Boolean);
  const mode = input.mode;
  const caseId = { unset: "P-unset", invalid: "P-invalid", stale: "P-stale" }[mode];
  const reason = { unset: "not_installed", invalid: "snapshot_invalid" }[mode] ?? null;
  const badge = mode === "stale" ? STALE_TEXT : NO_ACTIVE_TEXT;
  runs.forEach((run, index) => { evidence.runs[index ? "D" : "A"] = run; });
  await waitForBoot(page);
  for (const [index, run] of runs.entries()) {
    await rec_.step(`${mode.toUpperCase()}-0${index + 1}`, [caseId], `Choose run ${run} in 저장된 run, click 지식·보고서: snapshot ` +
      `block ${reason ?? "of the new set"}; every stored result listed with "${badge}"; open each: it renders from events with the same mark`,
    async () => {
      await chooseRun(page, run, true);
      const started = Date.now();   // after the run choice (its viewer session POST belongs to 구조 분석)
      await openKnowledge(page);
      const list = await resultList(page, run);
      const labels = await panel(page).locator("label[data-precedent-result]").evaluateAll(items => items.map(item => ({
        handle: item.getAttribute("data-precedent-result"), stale: item.getAttribute("data-stale"),
        noActive: item.getAttribute("data-no-active-set"),
        mark: item.querySelector('[data-testid="kinase-precedents-snapshot-mark"]')?.textContent.trim() ?? null })));
      const opened = [];
      for (const item of list.items) {
        const read = await openResult(page, run, item.handle);
        opened.push(await verifyDetail(page, read.body, null, { badge }));
      }
      const value = { api: await statusApi(page), list, labels, opened, posts: posts(log, started),
        snapshotState: await areaState(page, "snapshot"), snapshotText: clean(await area(page, "snapshot").textContent()),
        requestText: clean(await area(page, "request").textContent()), forms: await t(page, "request-form").count(),
        requestControls: await area(page, "request").locator("button, input, select, textarea, a").count(),
        capability: (await readApi(page, "/capabilities")).methods?.kinase_precedents ?? null };
      if (mode === "stale") value.snapshot = await snapshotReady(page);
      return value;
    }, async value => {
      assert.deepEqual(value.posts, [], "entering the tab posted");
      assert.ok(value.list.items.length >= 1, "no stored result to reopen");
      assert.deepEqual(value.labels.map(item => item.handle), value.list.items.map(item => item.handle));
      for (const label of value.labels) {
        assert.equal(label.mark, badge, `${label.handle} mark`);
        assert.equal(mode === "stale" ? label.stale : label.noActive, "true");
      }
      for (const item of value.list.items) assert.equal(item.active, false);
      if (mode === "stale") {
        checkSnapshotReady(value.snapshot, input["set-hash"], input.planData);
        assert.notEqual(input["set-hash"], input["previous-set-hash"]);
        assert.equal(value.forms, 1, "the request block is closed with a usable set");
        for (const item of value.list.items) assert.equal(item.set_hash, input["previous-set-hash"], "a result was recomputed");
        assert.deepEqual([value.capability.available, value.capability.set_hash], [true, input["set-hash"]]);
      } else {
        assert.deepEqual([value.api.installed, value.api.reason], [false, reason]);
        assert.equal(value.snapshotState, "unavailable");
        assert.ok(value.snapshotText.includes(coded(reason)) && value.snapshotText.includes(IMPORT_COMMAND), value.snapshotText);
        assert.ok(value.requestText.includes(`(${reason})`), value.requestText);
        assert.equal(value.forms, 0);
        assert.equal(value.requestControls, 0);
        assert.ok(noDigit(value.snapshotText) && noDigit(value.requestText), "a number in the unavailable blocks");
        assert.deepEqual([value.capability.available, value.capability.reason_code], [false, reason]);
        for (const item of value.list.items) assert.equal(item.set_hash, input["set-hash"]);
      }
      return { results: value.opened.map(item => ({ handle: item.handle, badge: item.badge })), installed: value.api.installed,
        reason: value.api.reason };
    });
    evidence.providerCalls.push(await providerCalls(page, run));
  }
}

// ------------------------------------------------------------------ main
const RUNNERS = { empty: modeEmpty, maps: modeMaps, main: modeMain, unset: modeAfter, invalid: modeAfter, stale: modeAfter };
const HARNESS_FILES = ["kinase-precedents-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs"];

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const evidence = { schema: "m27_precedent_evidence@1", mode: input.mode, stage: input.planData?.stage ?? null, runs: {},
    inputs: [], handles: {}, fixtureLabels: [], providerCalls: [], partFailures: [], controls: {}, observations: {},
    startedAt: new Date().toISOString() };
  const session = await launchOffscreen({ url: input.url, artifacts: input.artifacts, interactive: false });
  const log = requestLog(session.page);
  LOG = log;
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
  const providerZero = evidence.providerCalls.length > 0 && evidence.providerCalls.every(item => item.zero);
  const blockedHosts = [...new Set((proof?.blockedRequests ?? []).map(item => item.origin))];
  const passed = !error && evidence.partFailures.length === 0 && offscreenComplete(proof) && proof.nonLoopbackRequests === 0 &&
    Object.keys(cases).length > 0 && Object.values(cases).every(value => value === "pass") && providerZero;
  evidence.finishedAt = new Date().toISOString();
  if (error && rec_.real) fs.appendFileSync(path.join(input.artifacts, "precedent-real-errors.txt"), `--- mode\n${error.stack ?? error}\n`);
  evidence.error = error ? (rec_.real ? { errorDigest: textDigest(String(error.stack ?? error)), heldIn: "precedent-real-errors.txt" }
    : String(error.stack ?? error)) : null;
  evidence.requestCount = log.length;
  evidence.fixtureLabels = [...new Set(evidence.fixtureLabels)];
  fs.writeFileSync(path.join(input.artifacts, "precedent-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  fs.writeFileSync(path.join(input.artifacts, "precedent-requests.jsonl"), log.map(row => JSON.stringify(row)).join("\n") + "\n");
  const harness = Object.fromEntries(HARNESS_FILES.map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m27_case_ledger_row@1", mode: input.mode, stage: evidence.stage, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", cases, runId: evidence.runs.A ?? evidence.runs.E ?? null, runs: evidence.runs,
    handles: evidence.handles, inputs: evidence.inputs, fixtureLabels: evidence.fixtureLabels, controls: evidence.controls,
    observations: evidence.observations, buildId: buildId(), harness, setHash: input["set-hash"] ?? input.planData?.setHash ?? null,
    plan: input.plan, offscreen: proof, externalRequestCount: proof ? proof.nonLoopbackRequests : null, blockedHosts,
    providerCalls: evidence.providerCalls, providerCallsZero: providerZero, partFailures: evidence.partFailures,
    error: evidence.error, evidenceFile: path.basename(rec_.file), startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, runs: evidence.runs, cases }) + "\n");
  if (error) process.stderr.write(`kinase-precedents-flow ${input.mode} failed${rec_.real ? " (real stage: error text held)" : `: ${error.stack ?? error}`}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`kinase-precedents-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, forbiddenIn, mdEscape, bareZeroOrNone, realSafe, textDigest, countTexts, chainCells, pageText,
  checkKbaseFields, REAL_TEXT_MIN_CHARS, LIMITATIONS, KT1, UP1, UP2, UP3, UP4, UP5 };
