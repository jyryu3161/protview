"use strict";

// M26 reaction knowledge offscreen QA (spec §10.1, §12 오프스크린 QA). Real Electron offscreen page (isOffscreen,
// GPU/WebGL, paint). Every product mutation is a Playwright locator mouse/keyboard/file-chooser/select input; nothing
// calls application internals. Observation is read-only: data attributes and text of the 지식·보고서 "효소 반응 지식"
// area (and, for the M20 pre-selection, the 단백질 공학 tab), renderer request/response events, Electron paint frames,
// downloaded bytes and GET reads of the loopback API. Labeled renderer-route fixtures (request bodies altered in flight
// so that the real server refuses them) are recorded in the ledger and never produce a scientific value.
//
// The plan (--plan, written by scripts/m26_offscreen_acceptance.py) names the inputs, what the person enters and the
// expectations; in the fixture stage every reaction reference value is SYNTHETIC (made up, labelled) and the
// expectations are hand-derived from those rows (backend/tests/fixtures/reaction/t9/SYNTHETIC-PROVENANCE-t9.md). The
// screen is always compared with the stored result read back over the API.
//
// Modes (the full sequence and the reference-folder changes between them: scripts/m26_offscreen_acceptance.py):
//   empty    no reaction set: snapshot block reason + import command only, no numbers, no request controls
//   main     the active set of the plan: snapshot block, request defaults, field errors, admission refusals, every
//            planned link (M-CSA / UniProt / reactions), paging, report, result list, M20 pre-selection + UK3,
//            tab invariants, wording, a dry-run run
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
const MODES = ["empty", "main", "unset", "invalid", "stale"];
const KNOWLEDGE = "지식·보고서";
const TAB_LABELS = ["구조 분석", "단백질 공학", "리간드 설계·탐색", "지식·보고서"];
const TOOL = "link_reaction_knowledge";
const UBQ = path.join(REPO, "backend/tests/fixtures/public_1ubq.cif");
// Spec §11.1, verbatim (independent of the product constants).
const RK = {
  RK1: "촉매 잔기·부위·반응은 참조 스냅샷(M-CSA·UniProt·Rhea)에 적힌 값이며 ProtView가 계산하거나 판정한 것이 아니다.",
  RK2: "대응됨은 M-CSA가 적은 PDB·체인·번호와 이 구조의 잔기 이름이 모두 같다는 뜻이며 잔기의 역할이나 활성을 뜻하지 않는다.",
  RK3: "대응 없음·충돌·검사하지 않음은 이 스냅샷과 방법으로 확실하지 않다는 뜻이며 촉매 잔기가 없다는 뜻이 아니다.",
  RK4: "UniProt 부위는 번호 대응이 있는 체인에서만 구조 잔기에 연결했고 그 밖에는 단백질 서열 위치로만 보여 준다.",
  RK5: "반응 정보는 효소 활성·속도·특이성이나 반응 메커니즘이 유지된다는 뜻이 아니다.",
  RK6: "M-CSA·UniProt·Rhea 자료는 CC BY 4.0이며 출처·스냅샷 날짜는 아래에 있다.",
};
const UK = {
  UK1: "촉매 잔기·부위·반응은 M-CSA·UniProt·Rhea가 적은 참조값이며 ProtView가 계산한 값이 아니다. 가져온 스냅샷 날짜 기준이다.",
  UK2: "촉매 잔기 검사 안 함: 이 집합은 M-CSA 촉매 잔기 주석 없이 만들었거나 일부 체인만 검사했다.",
  UK3: "UniProt 부위 정보는 지식 탭에서만 보이며 보호에 쓰지 않음.",
  UK4: "이 체인을 M-CSA가 다루지 않았다는 것은 촉매 잔기가 없다는 뜻이 아니다.",
};
const FIXED = [...Object.values(RK), ...Object.values(UK)];
// Screen text the person sees (the product's wording, copied here as the expectation).
const REFERENCE_COLUMN = "M-CSA 원문, 계산 아님";
const IMPORT_COMMAND = ".venv/bin/python scripts/import_reaction_references.py";
const PROCESSED_LABEL = "공개 서버에서 가져온 가공본";
const STALE_TEXT = "이전 스냅샷 기준";
const NO_ACTIVE_TEXT = "사용 중 스냅샷 없음";
const NO_RESULTS_TEXT = "이 run에 효소 반응 지식 결과가 없습니다.";
const SNAPSHOT_REASON = { not_installed: "반응 참조 스냅샷이 설치되지 않음",
  snapshot_invalid: "반응 참조 스냅샷의 매니페스트·파일 해시나 형식이 맞지 않음" };
// Admission refusals: code → [Korean name shown with the code, the form field it is shown beside (null = the request
// line under the button)].
const REFUSALS = {
  unknown_field: ["알 수 없는 요청 항목", null],
  structure_invalid: ["이 run의 구조·전처리 구조가 아니거나 읽을 수 없음", "structure"],
  pdb_id_invalid: ["PDB ID 형식 오류(숫자 하나와 영숫자 셋)", "pdb_id"],
  chains_invalid: ["체인 목록 오류(비었음·모양·중복·알 수 없는 키)", "chains"],
  chain_not_found: ["구조가 가리키는 모델에 이 체인의 사슬 잔기가 없음", "chains"],
  accession_invalid: ["UniProt accession 형식이 아님", "chains"],
  numbering_map_invalid: ["이 run의 번호 대응이 아님", "numbering_map"],
  structure_mismatch: ["다른 구조의 번호 대응", "numbering_map"],
  map_pdb_mismatch: ["번호 대응의 PDB ID가 요청 PDB ID와 다름", "numbering_map"],
};
const ROW_LABEL = { matched: "대응됨", unmatched: "대응 없음", conflict: "충돌" };
// Spec §7 interpretive wording (M15 + M20 lists, 필수·핵심·중요·메커니즘이 유지, English counterparts), checked after
// removing the fixed sentences and every string of the stored result (verbatim reference values and codes).
const FORBIDDEN = new RegExp(["안정성", "ΔΔG", "순위", "추천", "최적", "개선", "활성", "예측", "유망", "좋은", "나쁜",
  "안전", "점수", "에너지", "수소\\s*결합", "친화", "필수", "핵심", "중요", "메커니즘이\\s*유지", "\\brank", "\\bbest\\b",
  "optimal", "improv", "recommend", "predict", "promising", "\\bgood\\b", "\\bsafe", "\\bactiv(?:e|ity)\\b",
  "\\bscor(?:e|ing)\\b", "energ", "hydrogen[\\s_-]?bond", "stabili", "affinity", "essential", "critical", "important",
  "\\bkey\\b"].join("|"), "gi");
const ALTER_LABEL = "QA refusal fixture (labeled renderer route): the link_reaction_knowledge request body is altered in " +
  "flight so that the real server refuses it; the server reply is shown unchanged";
const DRY_RUN_LABEL = "QA setup record: the dry-run run was made through POST /runs by the runner (the UI has no dry-run " +
  "control); every step on it here is a real click";
const PROVIDER_EVENT_TYPES = new Set(["egress", "egress_budget_settled", "viewer_dispatch_started"]);

const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const fileRecord = file => file && fs.existsSync(file)
  ? { path: file, bytes: fs.statSync(file).size, sha256: sha(fs.readFileSync(file)) } : { path: file ?? null, missing: true };
const enc = encodeURIComponent;
const clean = text => (text ?? "").replace(/\s+/g, " ").trim();
const masked = text => (text ?? "").replace(/\d+(?:[.,]\d+)*/g, "#").replace(/[ \t]+/g, " ").trim();
const NULL = "—";

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
    `Usage: reaction-knowledge-flow.cjs --mode ${MODES.join("|")} --artifacts <dir> [--url http://127.0.0.1:3000] ` +
    "[--plan <plan.json>] [--runs <runA,runD>] [--set-hash <active set>] [--previous-set-hash <hash>]. " +
    "Full sequence: scripts/m26_offscreen_acceptance.py.");
  if (value.mode !== "empty" && !value.plan) throw new Error(`--plan is required for mode ${value.mode}`);
  if (["unset", "invalid", "stale"].includes(value.mode) && !value.runs) throw new Error(`mode ${value.mode} needs --runs`);
  if (value.mode === "stale" && (!value["set-hash"] || !value["previous-set-hash"]))
    throw new Error("mode stale needs --set-hash and --previous-set-hash");
  const url = new URL(value.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) || !["http:", "https:"].includes(url.protocol))
    throw new Error("Only a loopback service is permitted");
  value.artifacts = path.resolve(value.artifacts);
  value.url = new URL("/", value.url).toString();
  value.planData = value.plan ? JSON.parse(fs.readFileSync(value.plan, "utf8")) : null;
  return value;
}

// ------------------------------------------------------------------ read-only observation
// Every reaction read answer seen (stored values and server strings): removed from screen text before the wording check.
const SEEN = [];
async function readApi(page, route) {
  const response = await page.request.get(new URL(`/api${route}`, page.url()).toString());
  assert.equal(response.status(), 200, `${route}: ${await response.text()}`);
  const value = await response.json();
  if (route.includes("reaction")) SEEN.push(value);
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
const statusApi = page => readApi(page, "/reaction_reference/status");
async function resultList(page, run) {
  const items = [];
  for (;;) {
    const chunk = await readApi(page, `/runs/${run}/reaction_knowledge?offset=${items.length}&limit=100`);
    items.push(...chunk.items);
    if (!chunk.items.length || items.length >= chunk.total) return { total: chunk.total, items };
  }
}
const DEFAULT_PAGING = { chain_offset: 0, chain_limit: 10, row_offset: 0, row_limit: 50, feature_offset: 0, feature_limit: 50 };
function pagingQuery(paging) {
  return ["chain_offset", "chain_limit", "row_offset", "row_limit", "feature_offset", "feature_limit"]
    .map(key => `${key}=${paging[key]}`).join("&");
}
const detailApi = (page, run, handle, paging = DEFAULT_PAGING) =>
  readApi(page, `/runs/${run}/reaction_knowledge/${enc(handle)}?${pagingQuery(paging)}`);
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
    rows.push({ at: Date.now(), method: request.method(), path: url.pathname, api: url.pathname.startsWith("/api/"),
      tool: request.method() === "POST" ? (() => { try { return request.postDataJSON()?.tool ?? null; } catch { return null; } })() : null });
  });
  return rows;
}
const posts = (log, since) => log.filter(row => row.at >= since && row.method === "POST" && row.api)
  .map(row => `${row.path}${row.tool ? ` ${row.tool}` : ""}`);

// ------------------------------------------------------------------ evidence
function recorder(session, input, evidence) {
  const { app, page, artifacts } = session;
  const file = path.join(artifacts, `reaction-${input.mode}.jsonl`);
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
      for (const id of cases) (evidence.observations[id] ??= []).push({ step: caseId, description });
      mark(cases, true);
      return result;
    } catch (error) {
      let proof = null;
      try { proof = await capture(app, page, artifacts, `${caseId}-failure`); } catch { /* keep the primary failure */ }
      const html = await page.evaluate(() => document.querySelector('[data-testid="reaction-panel"]')?.outerHTML
        .slice(0, 120000) ?? "").catch(() => null);
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
  return run;
}
async function chooseRun(page, run, waitViewer = true) {
  await selectTab(page, "구조 분석");
  await waitForBoot(page);
  await page.getByRole("tab", { name: /^run/i }).click();
  if (await globalRun(page) !== run) await page.locator("#run-choice").selectOption(run);
  await waitFor(page, async () => await globalRun(page) === run, `run ${run} selected`, 30000);
  if (waitViewer) await waitForViewer(page, value => value.sourceHandle !== null && value.catalogReady === true, 90000);
}
async function uploadLoad(page, item) {
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
async function prepareManual(page) {
  const back = page.getByRole("button", { name: "최신 구조로 돌아가기", exact: true });
  if (await back.isVisible().catch(() => false)) await back.click();
  const row = page.locator(".mw-workflow-row").filter({ has: page.getByRole("button", { name: "전처리", exact: true }) });
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    /\/commands$/.test(new URL(response.url()).pathname) && response.request().postDataJSON()?.tool === "prepare_structure",
  { timeout: 120000 });
  await row.getByRole("button", { name: "전처리", exact: true }).click();
  const body = await (await posted).json();
  assert.equal(body.ok, true, `prepare failed: ${JSON.stringify(body).slice(0, 400)}`);
  const prepared = body.handle.handle;
  assert.match(prepared, /\/prepared_structure\//);
  await waitForViewer(page, value => value.sourceHandle === prepared && value.catalogReady === true, 120000);
  return prepared;
}
const structureHidden = page => page.evaluate(() => { const node = document.getElementById("mw-app-panel-structure");
  return node ? { shown: node.getAttribute("data-shown"), inert: node.inert } : null; });
/** Areas and digit-masked text of one tab once settled (no busy element, text stable over 0.7 s). */
async function tabSignature(page, label, id) {
  await selectTab(page, label);
  const panel = page.locator(`#mw-app-panel-${id}`);
  await panel.waitFor({ timeout: 15000 });
  const text = await waitFor(page, async () => {
    if (await panel.locator('[aria-busy="true"]').count()) return null;
    const a = masked(await panel.innerText());
    await page.waitForTimeout(700);
    const b = masked(await panel.innerText());
    return a === b && !(await panel.locator('[aria-busy="true"]').count()) ? b : null;
  }, `${label} settled`, 60000);
  return { label, areas: await panel.locator("[data-testid$='-panel']").evaluateAll(items =>
    items.map(item => item.getAttribute("data-testid"))), textSha256: sha(Buffer.from(text)), text };
}

// ------------------------------------------------------------------ M15 numbering map (as mutation-flow.cjs)
const numbering = page => page.locator("section.mw-numbering");
const nTestId = (page, id) => numbering(page).locator(`[data-testid="${id}"]`);
async function makeNumberingMap(page, run, structure, spec) {
  await selectTab(page, KNOWLEDGE);
  await numbering(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => await numbering(page).locator('[data-numbering-area="create"]').getAttribute("data-state")
    === "ready" ? true : null, "numbering create ready", 60000);
  const select = nTestId(page, "numbering-structure");
  if (await select.inputValue() !== "") await select.selectOption("");
  await select.selectOption(structure);
  await waitFor(page, async () => await nTestId(page, `numbering-chain-${spec.chain}`).count() === 1 ? true : null,
    `chain ${spec.chain}`, 30000);
  await waitFor(page, async () => /업로드 원본|PDB ID가 없습니다|읽지 못했습니다/.test(await nTestId(page, "numbering-pdb-hint")
    .textContent()) ? true : null, "PDB ID suggestion", 30000);
  await nTestId(page, `numbering-chain-${spec.chain}`).check();
  await nTestId(page, "numbering-pdb-confirm").check();
  await waitFor(page, async () => (await nTestId(page, `numbering-accession-${spec.chain}`).textContent()).includes(spec.accession)
    ? true : null, "SIFTS prefill", 30000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/commands` &&
    response.request().postDataJSON()?.tool === "map_residue_numbering", { timeout: 180000 });
  await nTestId(page, "numbering-run").click();
  const body = await (await posted).json();
  assert.equal(body.ok, true, JSON.stringify(body).slice(0, 400));
  await nTestId(page, "numbering-run-result").filter({ hasText: "대응을 만들었습니다" }).waitFor({ timeout: 30000 });
  return body.handle.handle;
}

// ------------------------------------------------------------------ reaction area
const panel = page => page.locator('#mw-app-panel-knowledge [data-testid="reaction-panel"]');
const t = (page, id) => panel(page).locator(`[data-testid="${id}"]`);
const area = (page, name) => panel(page).locator(`section[data-reaction-area="${name}"]`);
const areaState = (page, name) => area(page, name).getAttribute("data-state", { timeout: 2000 }).catch(() => null);
const panelState = page => panel(page).getAttribute("data-reaction-state", { timeout: 2000 }).catch(() => null);
async function openKnowledge(page) {
  await selectTab(page, KNOWLEDGE);
  await panel(page).waitFor({ timeout: 15000 });
  await waitFor(page, async () => ["ready", "unavailable", "error"].includes(await areaState(page, "snapshot")) &&
    await areaState(page, "results") === "ready" ? true : null, "reaction area read", 60000);
}
async function panelText(page) { return panel(page).evaluate(node => node.innerText); }
function apiStrings(value, out = new Set()) {
  if (typeof value === "string") { if (value.length >= 2) out.add(value); }
  else if (Array.isArray(value)) for (const item of value) apiStrings(item, out);
  else if (value && typeof value === "object") for (const item of Object.values(value)) apiStrings(item, out);
  return out;
}
/** Forbidden words left after removing the fixed sentences and every string of the given stored values. */
function forbiddenIn(text, stored = []) {
  let rest = text;
  for (const sentence of FIXED) rest = rest.split(sentence).join(" ");
  const strings = [...apiStrings([...SEEN, ...stored])].sort((a, b) => b.length - a.length);
  for (const item of strings) rest = rest.split(item).join(" ");
  return [...rest.matchAll(FORBIDDEN)].map(match => match[0]);
}
function identityText(residue, nullReason = "구조 잔기 없음") {
  if (residue === null) return `${NULL} (${nullReason})`;
  return `${residue.resname} auth ${residue.chain_auth}/${residue.seq_auth} icode "${residue.icode}" label ` +
    `${residue.chain_label ?? NULL}/${residue.seq_label ?? NULL} 모델 ${residue.model_number}`;
}
const noDigit = text => !/\d/.test(text);
const rowKey = row => `${row.mcsa_id}/${row.residue_index}`;
const rowState = row => row.reason === null ? row.status : `${row.status}:${row.reason}`;

/** The detail area of one opened result versus the stored detail (same paging); returns a summary. */
async function verifyDetail(page, run, handle, expect, opts = {}) {
  const paging = opts.paging ?? DEFAULT_PAGING;
  const api = await detailApi(page, run, handle, paging);
  const detail = panel(page).locator(`[data-testid="reaction-detail"][data-reaction-detail="${handle}"]`);
  await detail.waitFor({ timeout: 60000 });
  await waitFor(page, async () => await areaState(page, "detail") === "ready" ? true : null, "detail ready", 60000);
  const wantState = api.null_result ? "scientific_null" : "ready";
  await waitFor(page, async () => await panelState(page) === wantState ? true : null, `panel ${wantState}`, 30000);
  assert.equal(await detail.getAttribute("data-null-result"), String(api.null_result));
  if (expect?.nullResult !== undefined) assert.equal(api.null_result, expect.nullResult, "null_result");
  if (api.null_result) assert.ok(clean(await t(page, "reaction-null-result").textContent()).includes("촉매 잔기가 없다는 뜻이 아닙니다"));
  // snapshot badge of the result (never recomputed)
  const badge = api.active_set.set_hash === null ? NO_ACTIVE_TEXT : api.active_set.same ? null : STALE_TEXT;
  const marks = await detail.locator('[data-testid="reaction-snapshot-mark"]').allInnerTexts();
  assert.deepEqual(marks.map(clean), badge ? [badge] : [], "detail snapshot mark");
  if (opts.badge !== undefined) assert.equal(badge, opts.badge, "expected snapshot mark");
  // counts (computed values; not computed = — with the reason, never 0)
  const counts = api.counts;
  const countText = async key => clean(await t(page, "reaction-counts").locator(`[data-reaction-count="${key}"] dd`).textContent());
  assert.equal(await countText("chains"), `${counts.chains}개`);
  const covered = await countText("covered_chains");
  if (api.pdb_id === null) assert.ok(covered.startsWith(NULL) && noDigit(covered), covered);
  else assert.equal(covered, `${counts.covered_chains}개`);
  const rowsText = await countText("mcsa_rows");
  if (counts.mcsa_rows === null) assert.ok(rowsText.startsWith(NULL) && noDigit(rowsText), rowsText);
  else assert.equal(rowsText, `대응됨 ${counts.mcsa_rows.matched} · 대응 없음 ${counts.mcsa_rows.unmatched} · 충돌 ${counts.mcsa_rows.conflict}`);
  for (const [key, format] of [
    ["mcsa_entries", value => `${value}개`],
    ["uniprot_features", value => `Active site ${value["Active site"]} · Binding site ${value["Binding site"]} · Site ${value.Site}`],
    ["linked_positions", value => `번호 대응 행 있음 ${value.mapped} · 번호 대응에 없음 ${value.not_in_map}`],
    ["rhea", value => `스냅샷에 있음 ${value.in_snapshot} · 스냅샷에 없음 ${value.not_in_snapshot}`]]) {
    const shown = await countText(key);
    if (counts[key] === null) assert.ok(shown.startsWith(NULL) && noDigit(shown), `${key}: ${shown}`);
    else assert.equal(shown, format(counts[key]), key);
  }
  // chains in stored order
  const chainNodes = detail.locator("[data-reaction-chain-view]");
  assert.deepEqual(await chainNodes.evaluateAll(items => items.map(item => item.getAttribute("data-reaction-chain-view"))),
    api.chains.map(chain => chain.chain_auth), "chain order");
  const summary = [];
  for (const chain of api.chains) {
    const node = detail.locator(`[data-reaction-chain-view="${chain.chain_auth}"]`);
    const attr = name => node.getAttribute(name);
    const mcsa = chain.mcsa, uniprot = chain.uniprot, reactions = chain.reactions;
    assert.equal(await attr("data-coverage"), mcsa.coverage, `${chain.chain_auth} coverage attr`);
    assert.equal(await attr("data-mcsa-status"), mcsa.status);
    assert.equal(await attr("data-uniprot-status"), uniprot.status);
    assert.equal(await attr("data-reactions-status"), reactions.status);
    const uk4 = await node.locator('[data-testid="reaction-chain-uk4"]').allInnerTexts();
    assert.deepEqual(uk4.map(clean), mcsa.coverage === "covered" ? [] : [UK.UK4], `${chain.chain_auth} UK4`);
    const flags = (await node.locator('[data-testid="reaction-chain-flag"]').allInnerTexts()).map(clean);
    assert.equal(flags.length, chain.flags.length);
    chain.flags.forEach((flag, i) => assert.ok(flags[i].includes(`(${flag})`), flags[i]));
    const statusLine = clean(await node.locator('[data-testid="reaction-mcsa-status"]').textContent());
    assert.ok(statusLine.includes(`(${mcsa.status})`), statusLine);
    if (mcsa.coverage) assert.ok(statusLine.includes(`(${mcsa.coverage})`), statusLine);
    if (mcsa.reason) assert.ok(statusLine.includes(`(${mcsa.reason})`), statusLine);
    // entries
    if (mcsa.entries === null) {
      const none = clean(await node.locator('[data-testid="reaction-mcsa-entries-none"]').textContent());
      assert.ok(none.includes(NULL) && noDigit(none.replace(/^M-CSA/, "")), none);
    } else {
      const shown = await node.locator('[data-testid="reaction-mcsa-entries"] li').evaluateAll(items =>
        items.map(item => ({ id: Number(item.getAttribute("data-mcsa-id")), text: item.textContent })));
      assert.deepEqual(shown.map(item => item.id), mcsa.entries.map(entry => entry.mcsa_id), "entries");
      mcsa.entries.forEach((entry, i) => assert.ok(shown[i].text.includes(entry.enzyme_name), "enzyme name verbatim"));
    }
    const countsLine = clean(await node.locator('[data-testid="reaction-mcsa-counts"]').textContent());
    if (mcsa.counts === null) assert.ok(countsLine.includes(NULL) && noDigit(countsLine), countsLine);
    else assert.ok(countsLine.endsWith(`대응됨 ${mcsa.counts.matched} · 대응 없음 ${mcsa.counts.unmatched} · 충돌 ${mcsa.counts.conflict}`), countsLine);
    // rows
    let shownRows = [];
    if (mcsa.rows === null) {
      const none = clean(await node.locator('[data-testid="reaction-mcsa-rows-none"]').textContent());
      assert.ok(none.includes(NULL) && noDigit(none.replace(/^M-CSA/, "")), none);
      assert.equal(await node.locator('[data-testid="reaction-mcsa-rows"]').count(), 0);
    } else {
      const header = clean(await node.locator('[data-testid="reaction-mcsa-rows"] thead').textContent());
      assert.ok(header.includes(REFERENCE_COLUMN), header);
      shownRows = await node.locator('[data-testid="reaction-mcsa-rows"] tbody tr').evaluateAll(items => items.map(item => {
        const cells = [...item.querySelectorAll(":scope > td")];
        const ref = cells[6];
        const dd = [...ref.querySelectorAll("dl > dd")];
        return { status: item.getAttribute("data-mcsa-row-status"), id: Number(item.getAttribute("data-mcsa-id")),
          index: Number(item.getAttribute("data-residue-index")), statusText: cells[0].textContent.trim(),
          residue: cells[2].textContent.trim(), resname: cells[3].textContent.trim(),
          listed: cells[4].textContent.replace(/\s+/g, " ").trim(), isReference: cells[5].textContent.trim(),
          summary: dd[0]?.textContent ?? null, location: dd[1]?.textContent ?? null, ptm: dd[2]?.textContent ?? null,
          rolesText: dd[3]?.textContent ?? null, roles: [...(dd[3]?.querySelectorAll("li") ?? [])].map(li => li.textContent),
          reason: cells[7].textContent.trim() };
      }));
      assert.equal(shownRows.length, mcsa.rows.length, `${chain.chain_auth} row count`);
      mcsa.rows.forEach((row, i) => {
        const ui = shownRows[i];
        const where = `${chain.chain_auth} ${rowKey(row)}`;
        assert.equal(ui.status, row.status, `${where} status`);
        assert.equal(ui.id, row.mcsa_id);
        assert.equal(ui.index, row.residue_index);
        assert.equal(ui.statusText, `${ROW_LABEL[row.status]} (${row.status})`, where);
        assert.equal(ui.residue, identityText(row.residue), `${where} 7-field identity`);
        assert.equal(ui.resname, row.structure_resname ?? NULL, `${where} structure name`);
        const listed = `${row.listed.pdb_id} · ${row.listed.chain_name} · resid ${row.listed.resid ?? NULL} · auth_resid ` +
          `${row.listed.auth_resid ?? NULL} · ${row.listed.code}`;
        assert.ok(ui.listed.startsWith(listed), `${where} listed: ${ui.listed}`);
        assert.equal(ui.isReference, row.is_reference ? "기준 구조 (is_reference true)" : "기준 구조 아님 (is_reference false)");
        const verbatim = value => value === "" ? '""' : value;
        assert.equal(ui.summary, verbatim(row.reference.roles_summary), `${where} roles_summary verbatim`);
        assert.equal(ui.location, verbatim(row.reference.function_location_abv), `${where} function_location_abv`);
        assert.equal(ui.ptm, verbatim(row.reference.ptm), `${where} ptm`);
        if (row.reference.roles === null) assert.equal(ui.rolesText, NULL);
        else if (!row.reference.roles.length) assert.equal(ui.rolesText, "빈 목록 ([])");
        else assert.deepEqual(ui.roles, row.reference.roles.map(role =>
          verbatim([role.group_function, role.function_type, role.function, role.emo].join(" / "))), `${where} roles`);
        if (row.reason === null) assert.equal(ui.reason, NULL);
        else assert.ok(ui.reason.endsWith(`(${row.reason})`), `${where} reason ${ui.reason}`);
      });
    }
    // UniProt
    const uniStatus = clean(await node.locator('[data-testid="reaction-uniprot-status"]').textContent());
    assert.ok(uniStatus.includes(`(${uniprot.status})`), uniStatus);
    if (uniprot.reason) assert.ok(uniStatus.includes(`(${uniprot.reason})`), uniStatus);
    if (uniprot.skipped) {
      const skipped = clean(await node.locator('[data-testid="reaction-uniprot-skipped"]').textContent());
      assert.ok(skipped.includes(`(${uniprot.skipped.reason})`), skipped);
      for (const target of uniprot.skipped.target_accessions) assert.ok(skipped.includes(target), skipped);
    }
    if (uniprot.entry) assert.ok(clean(await node.locator('[data-testid="reaction-uniprot-entry"]').textContent())
      .includes(uniprot.entry.accession));
    const linkLine = clean(await node.locator('[data-testid="reaction-uniprot-link"]').textContent());
    if (uniprot.status !== "checked") assert.ok(linkLine.includes(NULL) && noDigit(linkLine), linkLine);
    else if (uniprot.linked_via) assert.ok(linkLine.includes("(numbering_map)"), linkLine);
    else assert.ok(linkLine.includes(`(${uniprot.link_reason})`), linkLine);
    let shownFeatures = [];
    if (uniprot.features === null) {
      const none = clean(await node.locator('[data-testid="reaction-features-none"]').textContent());
      assert.ok(none.includes(NULL) && noDigit(none), none);
    } else if (!uniprot.features.length) {
      assert.equal(clean(await node.locator('[data-testid="reaction-features-empty"]').textContent()), "빈 목록 ([])");
    } else {
      shownFeatures = await node.locator('[data-testid="reaction-features"] tbody > tr').evaluateAll(items => items.map(item => ({
        type: item.getAttribute("data-feature-type"), linked: item.getAttribute("data-linked"),
        range: item.querySelectorAll(":scope > td")[1].textContent.trim(),
        linkText: item.querySelectorAll(":scope > td")[4].textContent.replace(/\s+/g, " ").trim(),
        links: [...item.querySelectorAll("li[data-link-status]")].map(li => ({ status: li.getAttribute("data-link-status"),
          position: Number(li.getAttribute("data-position")), text: li.textContent.replace(/\s+/g, " ").trim() })) })));
      assert.equal(shownFeatures.length, uniprot.features.length);
      uniprot.features.forEach((feature, i) => {
        const ui = shownFeatures[i];
        assert.equal(ui.type, feature.type);
        assert.equal(ui.range, feature.start === feature.end ? String(feature.start) : `${feature.start}–${feature.end}`);
        assert.equal(ui.linked, String(feature.links !== null));
        if (feature.links === null) {
          assert.ok(ui.linkText.startsWith(NULL), ui.linkText);
          if (uniprot.link_reason) assert.ok(ui.linkText.includes(`(${uniprot.link_reason})`), ui.linkText);
        } else {
          assert.deepEqual(ui.links.map(link => [link.position, link.status]), feature.links.map(link => [link.position, link.status]));
          feature.links.forEach((link, j) => {
            if (link.residue) assert.ok(ui.links[j].text.includes(identityText(link.residue)), ui.links[j].text);
            else assert.ok(ui.links[j].text.includes(`${NULL} (번호 대응에 없음)`), ui.links[j].text);
          });
        }
      });
    }
    // reactions
    const reactionLine = clean(await node.locator('[data-testid="reaction-reactions-status"]').textContent());
    assert.ok(reactionLine.includes(`(${reactions.status})`), reactionLine);
    const ecText = values => values === null ? null : values.length ? values.join(", ") : "빈 목록 ([])";
    for (const [id, source] of [["reaction-ec-mcsa", "mcsa"], ["reaction-ec-uniprot", "uniprot"]]) {
      const shown = clean(await node.locator(`[data-testid="${id}"]`).textContent()).replace(/^EC \([^)]*\): /, "");
      const want = reactions.ecs === null ? null : ecText(reactions.ecs[source]);
      if (want === null) assert.ok(shown.startsWith(NULL) && noDigit(shown), `${id}: ${shown}`);
      else assert.equal(shown, want, id);
    }
    if (reactions.mcsa_compounds === null || !reactions.mcsa_compounds.length) {
      const none = clean(await node.locator('[data-testid="reaction-compounds-none"]').textContent());
      assert.ok(reactions.mcsa_compounds === null ? none.startsWith(NULL) && noDigit(none) : none === "빈 목록 ([])", none);
    } else {
      const ids = await node.locator('[data-testid="reaction-compounds"] > li').evaluateAll(items =>
        items.map(item => Number(item.getAttribute("data-mcsa-id"))));
      assert.deepEqual(ids, reactions.mcsa_compounds.map(item => item.mcsa_id));
    }
    let rhea = [];
    if (reactions.uniprot_activities === null || !reactions.uniprot_activities.length) {
      const none = clean(await node.locator('[data-testid="reaction-activities-none"]').textContent());
      assert.ok(reactions.uniprot_activities === null ? none.startsWith(NULL) && noDigit(none) : none === "빈 목록 ([])", none);
    } else {
      rhea = await node.locator('[data-testid="reaction-activities"] li[data-rhea-id]').evaluateAll(items => items.map(item =>
        ({ id: item.getAttribute("data-rhea-id"), inSnapshot: item.getAttribute("data-in-snapshot"),
          text: item.textContent.replace(/\s+/g, " ").trim() })));
      const want = reactions.uniprot_activities.flatMap(activity => activity.rhea);
      assert.deepEqual(rhea.map(item => [item.id, item.inSnapshot]), want.map(link => [link.rhea_id, String(link.in_snapshot)]));
      want.forEach((link, i) => {
        if (!link.in_snapshot) assert.ok(rhea[i].text.includes(`${NULL} (스냅샷에 없는 Rhea ID)`), rhea[i].text);
        else assert.ok(rhea[i].text.includes(api.reference_rows.rhea.find(row => row.rhea_id === link.rhea_id).equation),
          "Rhea equation verbatim");
      });
    }
    checkChainExpectation(chain, (expect?.chains ?? {})[chain.chain_auth], api);
    summary.push({ chain: chain.chain_auth, coverage: mcsa.coverage, mcsaStatus: mcsa.status, counts: mcsa.counts,
      rows: mcsa.rows === null ? null : mcsa.rows.map(row => `${rowKey(row)} ${rowState(row)}`),
      uniprot: [uniprot.status, uniprot.reason, uniprot.link_reason], flags: chain.flags,
      features: uniprot.features?.length ?? null, rhea: rhea.map(item => [item.id, item.inSnapshot]) });
  }
  // fixed limitation sentences of the result, verbatim and in order
  const limits = await detail.locator('[data-testid="reaction-limitations"] [data-limitation]').allInnerTexts();
  assert.deepEqual(limits, api.limitations);
  assert.deepEqual(api.limitations, [RK.RK1, RK.RK2, RK.RK3, RK.RK4, RK.RK5]);
  const found = forbiddenIn(await panelText(page), [api]);
  assert.deepEqual(found, [], `forbidden wording: ${found.join(", ")}`);
  return { handle, nullResult: api.null_result, badge, counts, chains: summary, pdbId: api.pdb_id };
}

/** The plan's hand-derived expectations for one chain (fixture: exact; real: coverage, entries, minimum counts). */
function checkChainExpectation(chain, want, api) {
  if (!want) return;
  const where = `chain ${chain.chain_auth}`;
  const mcsa = chain.mcsa;
  if (want.coverage !== undefined) assert.equal(mcsa.coverage, want.coverage, `${where} coverage`);
  if (want.entries) assert.deepEqual((mcsa.entries ?? []).map(entry => entry.mcsa_id), want.entries, `${where} entries`);
  if (want.rows) {
    const got = Object.fromEntries((mcsa.rows ?? []).map(row => [rowKey(row), rowState(row)]));
    assert.deepEqual(got, want.rows, `${where} rows`);
  }
  if (want.rowCount !== undefined) assert.equal((mcsa.rows ?? []).length === 0 ? 0 : mcsa.counts.matched +
    mcsa.counts.unmatched + mcsa.counts.conflict, want.rowCount, `${where} row count`);
  if (want.allRows) assert.ok((mcsa.rows ?? []).every(row => row.status === want.allRows), `${where} all ${want.allRows}`);
  if (want.minMatched !== undefined) assert.ok((mcsa.counts?.matched ?? 0) >= want.minMatched, `${where} matched rows`);
  if (want.rowsInclude) for (const [key, state] of Object.entries(want.rowsInclude)) {
    const [id, at] = key.split("/");
    const row = (mcsa.rows ?? []).find(item => String(item.mcsa_id) === id && (at.startsWith(chain.chain_auth)
      ? String(item.listed.auth_resid) === at.slice(chain.chain_auth.length) : String(item.residue_index) === at));
    assert.ok(row, `${where} row ${key} missing`);
    assert.equal(rowState(row), state, `${where} row ${key}`);
  }
  for (const [key, name] of Object.entries(want.structureResname ?? {}))
    assert.equal(mcsa.rows.find(row => rowKey(row) === key).structure_resname, name, `${where} ${key} structure name`);
  for (const [key, icode] of Object.entries(want.insertionCode ?? {}))
    assert.equal(mcsa.rows.find(row => rowKey(row) === key).residue.icode, icode, `${where} ${key} insertion code`);
  for (const key of want.nullLabels ?? []) {
    const residue = mcsa.rows.find(row => rowKey(row) === key).residue;
    assert.ok(residue.chain_label === null && residue.seq_label === null, `${where} ${key} null labels kept`);
  }
  if (want.uniprot) assert.deepEqual([chain.uniprot.status, chain.uniprot.reason], want.uniprot, `${where} uniprot`);
  if (want.link !== undefined) {
    if (want.link === null) assert.equal(chain.uniprot.linked_via, "numbering_map", `${where} linked`);
    else assert.equal(chain.uniprot.link_reason, want.link, `${where} link_reason`);
  }
  if (want.skipped) assert.deepEqual(chain.uniprot.skipped, want.skipped, `${where} skipped`);
  if (want.flags) assert.deepEqual(chain.flags, want.flags, `${where} flags`);
  if (want.reactions) assert.equal(chain.reactions.status, want.reactions, `${where} reactions`);
  if (want.linkStatuses) assert.deepEqual(chain.uniprot.features.map(feature => (feature.links ?? []).map(link => link.status)),
    want.linkStatuses, `${where} link statuses`);
  if (want.minLinked !== undefined) assert.ok((api.counts.linked_positions?.mapped ?? 0) >= want.minLinked, `${where} linked`);
  if (want.linkedPositions) assert.deepEqual(api.counts.linked_positions, want.linkedPositions, `${where} linked positions`);
  for (const [key, value] of Object.entries(want.isReference ?? {}))
    assert.equal(mcsa.rows.find(row => rowKey(row) === key).is_reference, value, `${where} ${key} is_reference`);
  for (const key of want.rolesGiven ?? []) {
    const reference = mcsa.rows.find(row => rowKey(row) === key).reference;
    assert.ok(reference.roles_summary !== "" && Array.isArray(reference.roles) && reference.roles.length > 0,
      `${where} ${key}: no role text to compare verbatim`);
  }
  if (want.reactionsFilled) {
    const value = chain.reactions;
    assert.ok(value.ecs?.mcsa?.length && value.ecs?.uniprot?.length && value.mcsa_compounds?.length &&
      value.uniprot_activities?.length, `${where} reaction section: a part is empty or not given`);
  }
  if (want.rheaInSnapshot) {
    const seen = new Set((chain.reactions.uniprot_activities ?? []).flatMap(activity => activity.rhea.map(link => link.in_snapshot)));
    for (const value of want.rheaInSnapshot) assert.ok(seen.has(value), `${where} Rhea in_snapshot ${value}`);
  }
}

/** Choose a structure in the request block (a real select input; an empty choice first resets the form). */
async function chooseStructure(page, handle, chains) {
  await t(page, "reaction-request-form").waitFor({ timeout: 30000 });
  const select = t(page, "reaction-structure");
  if (await select.inputValue() !== "") await select.selectOption("");
  await select.selectOption(handle);
  for (const chain of chains)
    await waitFor(page, async () => await t(page, `reaction-chain-${chain}`).count() === 1 ? true : null, `chain row ${chain}`, 60000);
  await waitFor(page, async () => {
    const hint = clean(await t(page, "reaction-pdb-hint").textContent());
    return hint && !hint.includes("읽는 중") ? hint : null;
  }, "PDB ID suggestion read", 30000);
}
async function resultCount(page, run) { return (await resultList(page, run)).total; }

/** One planned link through the request block (real input) → the opened result, checked against the stored one. */
async function linkCase(page, run, ctx, spec, hooks = {}) {
  const handle = ctx.handles[spec.structure][spec.use];
  await openKnowledge(page);
  await chooseStructure(page, handle, spec.chains.map(chain => chain.chain));
  const entered = {};
  if (spec.pdbId.type) {
    await t(page, "reaction-pdb-id").fill(spec.pdbId.type);
    control(ctx.evidence, "reaction-pdb-id", { typed: spec.pdbId.type });
  } else {
    await waitFor(page, async () => await t(page, "reaction-pdb-id").inputValue() === spec.pdbId.suggested ? true : null,
      `PDB ID ${spec.pdbId.suggested} suggested`, 30000);
    entered.suggestedPdb = { value: await t(page, "reaction-pdb-id").inputValue(),
      hint: clean(await t(page, "reaction-pdb-hint").textContent()),
      confirmedBefore: await t(page, "reaction-pdb-confirm").isChecked() };
    assert.equal(entered.suggestedPdb.confirmedBefore, false, "a suggested PDB ID was confirmed by itself");
    assert.ok(entered.suggestedPdb.hint.includes(spec.pdbId.suggested), entered.suggestedPdb.hint);
  }
  await t(page, "reaction-pdb-confirm").check();
  control(ctx.evidence, "reaction-pdb-confirm", { checked: true });
  const pdbId = spec.pdbId.type ?? spec.pdbId.suggested;
  const lookupApi = await readApi(page, `/reaction_reference/pdb/${pdbId}`);
  await waitFor(page, async () => await t(page, "reaction-pdb-lookup").getAttribute("data-entries") === String(lookupApi.entries.length)
    ? true : null, "PDB lookup shown", 30000);
  entered.lookup = { entries: lookupApi.entries.map(entry => entry.mcsa_id), text: clean(await t(page, "reaction-pdb-lookup").textContent()) };
  if (spec.lookupEntries) assert.deepEqual(entered.lookup.entries, spec.lookupEntries, "M-CSA entries for the PDB ID");
  if (!lookupApi.entries.length) assert.ok(entered.lookup.text.includes("촉매 잔기가 없다는 뜻이 아닙니다"), entered.lookup.text);
  entered.chains = [];
  for (const chain of spec.chains) {
    const box = t(page, `reaction-chain-${chain.chain}`);
    assert.equal(await box.isChecked(), false, `chain ${chain.chain} ticked by itself`);
    await box.check();
    control(ctx.evidence, "reaction-chain", { checked: chain.chain });
    const input = t(page, `reaction-accession-${chain.chain}`);
    const accession = chain.accession;
    if (accession === null) {
      if (await input.inputValue() !== "") await input.fill("");
    } else if (accession.type) {
      await input.fill(accession.type);
      control(ctx.evidence, "reaction-accession", { typed: accession.type });
    } else if (accession.suggestion) {
      assert.equal(await input.inputValue(), "", "a suggestion was applied without a click");
      const button = t(page, `reaction-use-accession-${chain.chain}-${accession.suggestion}`);
      await button.waitFor({ timeout: 30000 });
      await button.click();
      control(ctx.evidence, "reaction-use-accession", { chain: chain.chain, accession: accession.suggestion });
    } else if (accession.map) {
      await waitFor(page, async () => await input.inputValue() === accession.map ? true : null, `map accession ${accession.map}`, 30000);
      assert.ok(clean(await t(page, `reaction-map-accession-${chain.chain}`).textContent()).includes(accession.map));
    }
    const value = accession === null ? "" : accession.type ?? accession.suggestion ?? accession.map;
    await waitFor(page, async () => await input.inputValue() === value ? true : null, `accession ${chain.chain} = ${value}`, 15000);
    entered.chains.push({ chain: chain.chain, accession: value || null });
  }
  const mapSelect = t(page, "reaction-numbering-map");
  entered.mapBefore = await mapSelect.inputValue();
  assert.equal(entered.mapBefore, "", "a numbering map was chosen by itself");
  const mapHandle = spec.map ? ctx.maps[spec.map] : null;
  if (mapHandle) {
    await mapSelect.selectOption(mapHandle);
    control(ctx.evidence, "reaction-numbering-map", { chosen: mapHandle });
  }
  if (hooks.beforeLink) entered.hook = await hooks.beforeLink({ structure: handle, map: mapHandle });
  const button = t(page, "reaction-link");
  await waitFor(page, async () => await button.isEnabled() ? true : null, "연결하기 enabled", 15000);
  const posted = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === TOOL,
  { timeout: 180000 });
  await button.click();
  control(ctx.evidence, "reaction-link", { clicked: spec.id });
  const response = await posted;
  const body = await response.json();
  assert.equal(body.ok, true, `link failed: ${JSON.stringify(body).slice(0, 600)}`);
  const args = response.request().postDataJSON().args;
  const made = body.handle.handle;
  await panel(page).locator(`[data-testid="reaction-link-done"][data-reaction-new-result="${made}"]`).waitFor({ timeout: 30000 });
  assert.deepEqual(args, { structure: handle, pdb_id: pdbId.toUpperCase(),
    chains: spec.chains.map((chain, i) => ({ chain_auth: chain.chain, uniprot_accession: entered.chains[i].accession })),
    numbering_map: mapHandle }, "request arguments");
  const verified = await verifyDetail(page, run, made, spec.expect, { badge: null });
  return { handle: made, args, entered, verified };
}

// ------------------------------------------------------------------ modes
async function modeEmpty(session, input, rec_, evidence, log) {
  const { page } = session;
  const run = await rec_.step("E01-new-run", [], "Click 구조 분석, 새 run (run E)", () => newRun(page), async id => ({ run: id }));
  evidence.runs.E = run;
  const loaded = await rec_.step("E02-upload", [], "Choose public_1ubq.cif, 구조 불러오기",
    () => uploadLoad(page, { file: UBQ, provenance: "public PDB entry 1UBQ (repository fixture)" }), async value => value);
  evidence.inputs.push(loaded.file);
  await rec_.step("E03-no-snapshot", ["R-no-snapshot"], "Click 지식·보고서 with no reaction set: snapshot block 사용할 수 " +
    "없음 + not_installed + import command; request block a reason only; no numbers, no controls", async () => {
    const started = Date.now();
    await openKnowledge(page);
    await waitFor(page, async () => await areaState(page, "snapshot") === "unavailable" ? true : null, "snapshot unavailable", 30000);
    await page.waitForTimeout(1000);
    return { snapshotText: clean(await area(page, "snapshot").textContent()), requestText: clean(await area(page, "request").textContent()),
      resultsText: clean(await area(page, "results").textContent()),
      command: clean(await t(page, "reaction-import-command").textContent()),
      reasonCode: await t(page, "reaction-snapshot-unavailable").getAttribute("data-reason-code"),
      controls: await area(page, "snapshot").locator("button, input, select, textarea, a").count() +
        await area(page, "request").locator("button, input, select, textarea, a").count(),
      forms: await t(page, "reaction-request-form").count(), setHash: await t(page, "reaction-set-hash").count(),
      results: await panel(page).locator('input[data-testid="reaction-result"]').count(), state: await panelState(page),
      posts: posts(log, started), api: await statusApi(page),
      capability: (await readApi(page, "/capabilities")).methods?.reaction_knowledge ?? null };
  }, async value => {
    assert.equal(value.api.installed, false, "the empty case needs an empty reaction reference folder");
    assert.equal(value.api.reason, "not_installed");
    assert.deepEqual([value.capability.available, value.capability.reason_code], [false, "not_installed"]);
    assert.equal(value.reasonCode, "not_installed");
    assert.ok(value.snapshotText.includes("사용할 수 없음") && value.snapshotText.includes(`${SNAPSHOT_REASON.not_installed} (not_installed)`),
      value.snapshotText);
    assert.equal(value.command, IMPORT_COMMAND);
    assert.ok(value.requestText.includes(`${SNAPSHOT_REASON.not_installed} (not_installed)`), value.requestText);
    assert.ok(noDigit(value.snapshotText) && noDigit(value.requestText), `a number is shown: ${value.snapshotText} | ${value.requestText}`);
    assert.equal(value.controls, 0, "controls in the snapshot / request blocks");
    assert.equal(value.forms, 0);
    assert.equal(value.setHash, 0);
    assert.equal(value.results, 0);
    assert.ok(value.resultsText.includes(NO_RESULTS_TEXT) && noDigit(value.resultsText.replace("결과 목록 다시 읽기", "")), value.resultsText);
    assert.deepEqual(value.posts, []);
    assert.notEqual(value.state, "unavailable", "a missing set made the whole area unavailable");
    assert.deepEqual(forbiddenIn(await panelText(page)), []);
    return value;
  });
  evidence.providerCalls.push(await providerCalls(page, run));
}

async function snapshotReady(page, plan) {
  const api = await statusApi(page);
  return { api, hash: clean(await t(page, "reaction-set-hash").textContent()), title: await t(page, "reaction-set-hash").getAttribute("title"),
    sources: await t(page, "reaction-snapshot-sources").locator("tbody tr").evaluateAll(items => items.map(item => ({
      source: item.getAttribute("data-snapshot-source"), cells: [...item.querySelectorAll("td")].map(td => td.textContent.trim()) }))),
    processed: clean(await t(page, "reaction-processed-label").textContent()),
    userNamed: clean(await t(page, "reaction-user-named").textContent()), skipped: clean(await t(page, "reaction-skipped").textContent()),
    importedAt: clean(await t(page, "reaction-imported-at").textContent()),
    rk1: clean(await t(page, "reaction-note-rk1").textContent()), uk1: clean(await t(page, "reaction-note-uk1").textContent()),
    rk6: clean(await t(page, "reaction-note-rk6").textContent()), planHash: plan.setHash };
}
function checkSnapshotReady(value, setHash) {
  assert.equal(value.api.installed, true);
  assert.equal(value.api.set_hash, setHash, "the backend's active set is not the plan's");
  assert.equal(value.title, setHash);
  assert.equal(value.hash, setHash.slice(0, 12));
  assert.equal(value.importedAt, value.api.imported_at);
  assert.deepEqual(value.sources.map(item => item.source), value.api.sources.map(item => item.source));
  value.api.sources.forEach((source, i) => {
    const cells = value.sources[i].cells;
    assert.equal(cells[1], source.date);
    assert.equal(cells[2], `CC BY 4.0 (${source.license})`);
    assert.equal(cells[3], `${source.rows}행`);
    assert.equal(cells[4], source.origin);
  });
  assert.deepEqual(value.api.sources.map(item => item.license), ["CC-BY-4.0", "CC-BY-4.0", "CC-BY-4.0"]);
  assert.equal(value.processed, PROCESSED_LABEL);
  assert.equal(value.userNamed, `직접 지정한 accession ${value.api.requested_accessions.user_named.length}개`);
  assert.equal(value.skipped, `가져올 때 건너뛴 accession ${value.api.skipped_accessions.length}개`);
  assert.equal(value.rk1, RK.RK1);
  assert.equal(value.uk1, UK.UK1);
  assert.equal(value.rk6, RK.RK6);
}

// Built-in parts of the main mode → the case ids of the real stage (scripts/m26_offscreen_acceptance.py CASE_PLAN);
// an id without a real-stage counterpart stays as it is (recorded, not judged in that stage).
const REAL_CASE = { "R-snapshot-ready": "X-snapshot-real", "R-report": "X-report", "R-tabs": "X-tabs",
  "R-wording": "X-wording", "R-no-zero": "X-no-zero", "R-uniprot-link": "X-uniprot-link",
  "R-request-defaults": "X-request-defaults", "R-results-list": "X-results-list", "R-m20-uk3": "X-m20-uk3" };

async function modeMain(session, input, rec_, evidence, log) {
  const { page, app } = session;
  const plan = input.planData;
  const C = id => plan.stage === "real" ? REAL_CASE[id] ?? id : id;
  const ctx = { evidence, handles: {}, maps: {}, links: {} };
  evidence.handles.structures = ctx.handles;
  evidence.handles.maps = ctx.maps;
  evidence.handles.links = ctx.links;
  if (plan.synthetic) evidence.fixtureLabels.push(plan.synthetic);
  // labelled synthetic inputs (e.g. the derived 1S9I of the real stage) are named in the ledger as well
  for (const item of Object.values(plan.structures)) if (item.provenance.includes("SYNTHETIC")) evidence.fixtureLabels.push(item.provenance);
  const runA = await rec_.step("M01-new-run", [], "Click 구조 분석, 새 run (run A)", () => newRun(page), async id => ({ run: id }));
  evidence.runs.A = runA;
  // ---- every planned structure through the structure screen (prepared ones with 전처리), then the numbering maps
  for (const [id, item] of Object.entries(plan.structures)) {
    const loaded = await rec_.step(`M02-upload-${id}`, [], `Choose ${item.name}, click 구조 불러오기${item.prepare ? ", 전처리" : ""}`,
      async () => {
        await selectTab(page, "구조 분석");
        const value = await uploadLoad(page, item);
        const prepared = item.prepare ? await prepareManual(page) : null;
        return { ...value, prepared };
      }, async value => { assert.equal(value.file.sha256, item.sha256); return value; });
    evidence.inputs.push(loaded.file);
    ctx.handles[id] = { loaded: loaded.handle, prepared: loaded.prepared };
  }
  for (const spec of plan.maps) {
    const handle = await rec_.step(`M03-map-${spec.id}`, [C("R-uniprot-link")],
      `지식·보고서 잔기 번호 대응: choose the ${spec.use} ${spec.structure}, chain ${spec.chain}, tick 이 PDB ID가 맞습니다 ` +
      `(${spec.pdbId}), SIFTS ${spec.accession}, 실행`, () => makeNumberingMap(page, runA, ctx.handles[spec.structure][spec.use], spec),
      async value => {
        const listed = (await readApi(page, `/runs/${runA}/numbering_maps?offset=0&limit=100`)).rows.find(row => row.handle === value);
        assert.equal(listed.structure, ctx.handles[spec.structure][spec.use]);
        assert.equal(listed.pdb_id, spec.pdbId);
        return { handle: value, setHash: listed.set_hash };
      });
    ctx.maps[spec.id] = handle;
  }
  // ---- other tabs before any reaction work
  let beforeSignatures = null;
  await rec_.part("tabs-before", [C("R-tabs")], async () => {
    beforeSignatures = await rec_.step("M04-tabs-before", [C("R-tabs")], "Click 단백질 공학 and 리간드 설계·탐색: record their " +
      "areas and digit-masked text before any link", async () => ({ protein: await tabSignature(page, "단백질 공학", "protein"),
      ligand: await tabSignature(page, "리간드 설계·탐색", "ligand") }), async value => {
      assert.ok(value.protein.areas.includes("mutation-panel"), value.protein.areas.join(","));
      return { protein: value.protein.areas, ligand: value.ligand.areas };
    });
  });

  // ---- snapshot block and request defaults
  await rec_.part("snapshot", [C("R-snapshot-ready"), C("R-request-defaults")], async () => {
    await rec_.step("M05-snapshot", [C("R-snapshot-ready")], "Click 지식·보고서: the snapshot block of the active set (hash, sources, " +
      "license, rows, processed label, counts, skipped list via its summary, RK1 / UK1 / RK6)", async () => {
      await openKnowledge(page);
      const value = await snapshotReady(page, plan);
      await t(page, "reaction-skipped-list").locator("summary").click();
      control(evidence, "reaction-skipped-list", { opened: true });
      value.skippedList = await t(page, "reaction-skipped-list").locator("li[data-skipped-accession]").evaluateAll(items =>
        items.map(item => ({ accession: item.getAttribute("data-skipped-accession"), text: item.textContent.replace(/\s+/g, " ").trim() })));
      return value;
    }, async value => {
      checkSnapshotReady(value, plan.setHash);
      assert.deepEqual(value.skippedList.map(item => item.accession), value.api.skipped_accessions.map(item => item.accession));
      value.api.skipped_accessions.forEach((item, i) => {
        assert.ok(value.skippedList[i].text.includes(`(${item.reason})`), value.skippedList[i].text);
        for (const target of item.target_accessions) assert.ok(value.skippedList[i].text.includes(target));
      });
      return { setHash: value.api.set_hash, sources: value.api.sources, skipped: value.skippedList };
    });
    await rec_.step("M06-defaults", [C("R-request-defaults")], "Nothing chosen by itself: structure select empty; choose a structure → " +
      "the file's PDB ID in the field unconfirmed, no chain ticked, no numbering map, 연결하기 disabled", async () => {
      const started = Date.now();
      await openKnowledge(page);
      await t(page, "reaction-request-form").waitFor({ timeout: 30000 });
      const first = { structure: await t(page, "reaction-structure").inputValue(), link: await t(page, "reaction-link").isDisabled() };
      const id = plan.fieldErrors?.structure ?? Object.keys(plan.structures)[0];
      const spec = plan.links.find(link => link.structure === id) ?? plan.links[0];
      await chooseStructure(page, ctx.handles[id].loaded, spec.chains.map(chain => chain.chain));
      return { first, pdb: await t(page, "reaction-pdb-id").inputValue(), confirmed: await t(page, "reaction-pdb-confirm").isChecked(),
        ticked: await panel(page).locator('input[data-testid^="reaction-chain-"]:checked').count(),
        chains: await panel(page).locator('input[data-testid^="reaction-chain-"]').count(),
        map: await t(page, "reaction-numbering-map").inputValue(), link: await t(page, "reaction-link").isDisabled(),
        hint: clean(await t(page, "reaction-pdb-hint").textContent()),
        fileHint: await readApi(page, `/runs/${runA}/reference/pdb_id_hint?structure=${enc(ctx.handles[id].loaded)}`),
        posts: posts(log, started) };
    }, async value => {
      assert.equal(value.first.structure, "");
      assert.equal(value.first.link, true);
      assert.equal(value.pdb, value.fileHint.pdb_id ?? "");
      assert.equal(value.confirmed, false);
      assert.equal(value.ticked, 0);
      assert.ok(value.chains >= 1);
      assert.equal(value.map, "");
      assert.equal(value.link, true);
      assert.deepEqual(value.posts, []);
      return value;
    });
  });

  // ---- field errors (the screen's own checks beside the fields)
  if (plan.fieldErrors) await rec_.part("field-errors", ["R-field-errors"], () => rec_.step("M07-field-errors", ["R-field-errors"],
    `Type PDB ID ${plan.fieldErrors.badPdbId} and tick 이 PDB ID가 맞습니다, tick chain ${plan.fieldErrors.chain}, type accession ` +
    `${plan.fieldErrors.badAccession}: reasons beside the fields, 연결하기 disabled, nothing posted`, async () => {
      const started = Date.now();
      const spec = plan.fieldErrors;
      await openKnowledge(page);
      await chooseStructure(page, ctx.handles[spec.structure].loaded, [spec.chain]);
      await t(page, "reaction-pdb-id").fill(spec.badPdbId);
      await t(page, "reaction-pdb-confirm").check();
      await t(page, `reaction-chain-${spec.chain}`).check();
      await t(page, `reaction-accession-${spec.chain}`).fill(spec.badAccession);
      const errors = await panel(page).locator('[data-testid="reaction-field-error"]').evaluateAll(items => items.map(item => ({
        field: item.getAttribute("data-field"), chain: item.getAttribute("data-chain"), text: item.textContent.trim(),
        container: item.closest("[data-reaction-field]")?.getAttribute("data-reaction-field") ?? null })));
      return { errors, link: await t(page, "reaction-link").isDisabled(), posts: posts(log, started),
        lookup: await t(page, "reaction-pdb-lookup").count() };
    }, async value => {
      const pdb = value.errors.find(item => item.field === "pdb_id");
      const acc = value.errors.find(item => item.field === "chains" && item.chain === plan.fieldErrors.chain);
      assert.ok(pdb && pdb.container === "pdb_id" && pdb.text.includes("PDB ID 형식이 올바르지 않습니다"), JSON.stringify(value.errors));
      assert.ok(acc && acc.container === "chains" && acc.text.includes(`UniProt accession 형식이 아닙니다: ${plan.fieldErrors.badAccession}`),
        JSON.stringify(value.errors));
      assert.equal(value.link, true);
      assert.equal(value.lookup, 0, "an invalid PDB ID was looked up");
      assert.deepEqual(value.posts, []);
      return value;
    }));

  // ---- the planned links
  const refusalsDone = { value: null };
  for (const spec of plan.links) {
    const hooks = {};
    if (spec.refusals && plan.refusals) hooks.beforeLink = async ({ structure, map }) => {
      refusalsDone.value = await refusalsPart(page, rec_, evidence, runA, ctx, plan, structure, map);
      return { refusals: refusalsDone.value?.length ?? 0 };
    };
    await rec_.part(`link-${spec.id}`, spec.cases, async () => {
      const result = await rec_.step(`L-${spec.id}`, spec.cases, `Link ${spec.id}: ${spec.structure} (${spec.use}), PDB ID ` +
        `${spec.pdbId.type ?? `${spec.pdbId.suggested} (suggested)`} confirmed, chains ${spec.chains.map(chain =>
          `${chain.chain}${chain.accession ? `:${Object.values(chain.accession)[0]}` : ""}`).join(" ")}${spec.map ? `, map ${spec.map}` : ""}; ` +
        "연결하기 → the opened result equals the stored result", () => linkCase(page, runA, ctx, spec, hooks),
      async value => ({ handle: value.handle, entered: value.entered, chains: value.verified.chains, nullResult: value.verified.nullResult }));
      ctx.links[spec.id] = result.handle;
    });
  }
  if (plan.refusals && refusalsDone.value === null) {
    rec_.append({ caseId: "R-refusals-not-run", cases: ["R-refusals"], status: "fail", description: "refusal part did not run" });
    evidence.partFailures.push({ part: "refusals", cases: ["R-refusals"], error: "not run (its link case failed first)" });
  }

  // ---- result list
  await rec_.part("results-list", [C("R-results-list"), C("R-no-zero")], () => rec_.step("M10-results",
    [C("R-results-list"), C("R-no-zero")],
    "Click 결과 목록 다시 읽기: the list equals the stored list (newest first); counts not made are — with the reason", async () => {
      const started = Date.now();
      await openKnowledge(page);
      await t(page, "reaction-results-refresh").click();
      control(evidence, "reaction-results-refresh", { clicked: true });
      await waitFor(page, async () => await areaState(page, "results") === "ready" && log.some(row => row.at >= started &&
        row.method === "GET" && row.path === `/api/runs/${runA}/reaction_knowledge`) ? true : null, "result list re-read", 30000);
      return { labels: await panel(page).locator("label[data-reaction-result]").evaluateAll(items => items.map(item => ({
        handle: item.getAttribute("data-reaction-result"), nullResult: item.getAttribute("data-null-result"),
        text: item.textContent.replace(/\s+/g, " ").trim(), stale: item.getAttribute("data-stale") }))),
      api: await resultList(page, runA), posts: posts(log, started) };
    }, async value => {
      assert.deepEqual(value.posts, []);
      assert.deepEqual(value.labels.map(item => item.handle), value.api.items.map(item => item.handle));
      value.api.items.forEach((item, i) => {
        const label = value.labels[i];
        assert.equal(label.nullResult, String(item.null_result));
        assert.equal(label.stale, null);
        if (item.null_result) assert.ok(label.text.includes("빈 결과"), label.text);
        if (item.mcsa_rows === null) assert.ok(label.text.includes(`M-CSA 행 ${NULL}`) && !/M-CSA 행 대응됨/.test(label.text), label.text);
        else assert.ok(label.text.includes(`M-CSA 행 대응됨 ${item.mcsa_rows.matched} · 대응 없음 ${item.mcsa_rows.unmatched} · 충돌 ${item.mcsa_rows.conflict}`), label.text);
        if (item.uniprot_feature_count === null) assert.ok(label.text.includes(`UniProt 부위 ${NULL}`), label.text);
        else assert.ok(label.text.includes(`UniProt 부위 ${item.uniprot_feature_count}개`), label.text);
        assert.ok(label.text.includes(`체인 ${item.chain_count}개`));
      });
      assert.deepEqual(forbiddenIn(await panelText(page), [value.api]), []);
      return { listed: value.labels.length, items: value.api.items.map(item => ({ handle: item.handle, mcsa_rows: item.mcsa_rows,
        uniprot_feature_count: item.uniprot_feature_count, null_result: item.null_result })) };
    }));

  // ---- paging
  if (plan.paging && ctx.links[plan.paging]) await rec_.part("paging", ["R-paging"], async () => {
    const handle = ctx.links[plan.paging];
    await rec_.step("M11-paging", ["R-paging"], "Open the 60-row result: M-CSA 행 다음 → rows 51–60 equal the stored page; 이전 → " +
      "back; chain and site pagers disabled", async () => {
      await openKnowledge(page);
      await panel(page).locator(`input[data-testid="reaction-result"][data-reaction-result="${handle}"]`).check();
      control(evidence, "reaction-result", { checked: handle });
      const first = await verifyDetail(page, runA, handle, null, { badge: null });
      const disabled = {};
      for (const id of ["reaction-chains-prev", "reaction-chains-next", "reaction-rows-prev", "reaction-features-prev", "reaction-features-next"])
        disabled[id] = await t(page, id).isDisabled();
      const firstText = clean(await t(page, "reaction-mcsa-rows-page").textContent());
      await t(page, "reaction-rows-next").click();
      control(evidence, "reaction-rows-next", { clicked: true });
      await waitFor(page, async () => clean(await t(page, "reaction-mcsa-rows-page").textContent()) !== firstText ? true : null, "rows page 2", 30000);
      const second = await verifyDetail(page, runA, handle, null, { badge: null, paging: { ...DEFAULT_PAGING, row_offset: 50 } });
      const secondText = clean(await t(page, "reaction-mcsa-rows-page").textContent());
      const nextDisabled = await t(page, "reaction-rows-next").isDisabled();
      await t(page, "reaction-rows-prev").click();
      control(evidence, "reaction-rows-prev", { clicked: true });
      await waitFor(page, async () => clean(await t(page, "reaction-mcsa-rows-page").textContent()) === firstText ? true : null, "rows page 1", 30000);
      return { first: first.chains, second: second.chains, firstText, secondText, disabled, nextDisabled };
    }, async value => {
      assert.ok(value.firstText.includes("전체 60개 중 1–50번째"), value.firstText);
      assert.ok(value.secondText.includes("전체 60개 중 51–60번째"), value.secondText);
      assert.equal(value.first[0].rows.length, 50);
      assert.equal(value.second[0].rows.length, 10);
      assert.equal(value.nextDisabled, true);
      assert.deepEqual(Object.values(value.disabled), [true, true, true, true, true]);
      return { firstText: value.firstText, secondText: value.secondText, disabled: value.disabled };
    });
  });

  // ---- report
  if (plan.report && ctx.links[plan.report]) await rec_.part("report", [C("R-report")], async () => {
    const cases = [C("R-report")];
    const handle = ctx.links[plan.report];
    const created = await rec_.step("M12-report", cases, "Open the result, click 보고서 만들기", async () => {
      await openKnowledge(page);
      await panel(page).locator(`input[data-testid="reaction-result"][data-reaction-result="${handle}"]`).check();
      await verifyDetail(page, runA, handle, null, { badge: null });
      const posted = page.waitForResponse(response => response.request().method() === "POST" &&
        new URL(response.url()).pathname === `/api/runs/${runA}/method_reports`, { timeout: 60000 });
      await t(page, "reaction-report").click();
      control(evidence, "reaction-report", { clicked: true });
      const response = await posted;
      const body = await response.json();
      await t(page, "reaction-report-done").waitFor({ timeout: 30000 });
      return { status: response.status(), handle: body.handle, manifest: body.manifest, request: response.request().postDataJSON(),
        done: await t(page, "reaction-report-done").getAttribute("data-report-handle") };
    }, async value => {
      assert.equal(value.done, value.handle);
      assert.equal(value.manifest.analysis_type, "reaction_knowledge");
      assert.equal(value.manifest.result_handle, handle);
      assert.deepEqual(value.request, { result_handle: handle });
      return { handle: value.handle, status: value.status };
    });
    evidence.handles.report = created.handle;
    const stored = await detailApi(page, runA, handle, { ...DEFAULT_PAGING, row_limit: 200, feature_limit: 200 });
    for (const [id, format] of [["reaction-report-markdown", "markdown"], ["reaction-report-json", "json"]]) {
      const route = `/runs/${runA}/reports/download?handle=${enc(created.handle)}&format=${format}`;
      await rec_.step(`M13-download-${format}`, cases, `Click ${id}: bytes non-empty and equal the backend bytes`, () =>
        downloadByClick(app, t(page, id)), async downloaded => {
        const bytes = fs.readFileSync(downloaded.downloaded);
        const saved = await readBytes(page, route);
        assert.ok(bytes.length > 0);
        assert.equal(sha(bytes), sha(saved), "downloaded bytes differ from the backend bytes");
        const text = bytes.toString("utf8");
        if (format === "markdown") {
          for (const sentence of Object.values(RK)) assert.ok(text.includes(sentence), `report lacks ${sentence}`);
          const found = forbiddenIn(text, [stored]);
          assert.deepEqual(found, [], `report wording: ${found.join(", ")}`);
        } else {
          const manifest = JSON.parse(text);
          assert.equal(manifest.analysis_type ?? manifest.manifest?.analysis_type, "reaction_knowledge");
        }
        return { route, sha256: sha(bytes), bytes: bytes.length };
      });
    }
    const library = page.getByRole("region", { name: "보고서 보관함", exact: true });
    const reports = library.getByRole("region", { name: "저장된 보고서", exact: true });
    const content = library.getByRole("region", { name: "선택한 항목 내용", exact: true });
    await rec_.step("M14-library", cases, "The knowledge-tab report list shows 효소 반응 지식 보고서; click it; content = stored Markdown",
      async () => {
        await selectTab(page, KNOWLEDGE);
        const row = reports.locator("li button").filter({ hasText: created.handle });
        await row.waitFor({ timeout: 30000 });
        const kind = clean(await row.locator(".mw-library-kind").textContent());
        await row.click();
        const pre = content.getByLabel(`저장된 보고서 ${created.handle}`, { exact: true });
        await pre.waitFor({ timeout: 30000 });
        return { kind, text: await pre.textContent() };
      }, async value => {
        assert.equal(value.kind, "효소 반응 지식 보고서");
        const saved = await readApi(page, `/runs/${runA}/reports/selected?handle=${enc(created.handle)}`);
        assert.equal(value.text, saved.markdown);
        return { kind: value.kind, markdownSha256: sha(Buffer.from(value.text)) };
      });
  });

  // ---- M20 request area: newest same-structure result pre-selected (never submitted), UK3 for linked sites
  if (plan.uk3 && ctx.links[plan.uk3.link]) await rec_.part("m20-uk3", [C("R-m20-uk3")], () => rec_.step("M15-m20-uk3", [C("R-m20-uk3")],
    "Click 단백질 공학, choose the prepared structure in 변이 후보: the newest same-structure reaction knowledge result is " +
    "pre-selected; its sites are linked, so UK3 is shown; nothing is posted", async () => {
      const started = Date.now();
      const prepared = ctx.handles[plan.uk3.structure].prepared;
      await selectTab(page, "단백질 공학");
      const m20 = page.locator('[data-testid="mutation-panel"]');
      await m20.waitFor({ timeout: 15000 });
      await waitFor(page, async () => await m20.locator('[data-mutation-area="sets"]').getAttribute("data-state") === "ready" &&
        await m20.locator(`label[data-mutation-structure="${prepared}"] input`).isEnabled() ? true : null, "M20 ready", 60000);
      await m20.locator(`label[data-mutation-structure="${prepared}"] input`).check();
      control(evidence, "mutation-structures", { checked: prepared });
      const select = m20.locator('[data-testid="mutation-catalytic-annotation"]');
      await waitFor(page, async () => await select.inputValue() !== "" ? true : null, "catalytic annotation pre-selected", 30000);
      await waitFor(page, async () => (await m20.locator('[data-testid="mutation-catalytic-notice"]').count()) > 0 ? true : null,
        "catalytic notice", 30000);
      await page.waitForTimeout(800);
      return { value: await select.inputValue(), options: await select.locator("option").evaluateAll(items => items.map(item => item.value)),
        notice: await m20.locator('[data-testid="mutation-catalytic-notice"] p').allInnerTexts(),
        list: await resultList(page, runA), posts: posts(log, started) };
    }, async value => {
      const same = value.list.items.filter(item => item.structure_handle === ctx.handles[plan.uk3.structure].prepared);
      assert.equal(value.value, same[0].handle, "not the newest same-structure result");
      assert.equal(value.value, ctx.links[plan.uk3.link]);
      assert.deepEqual(value.options.filter(Boolean), same.map(item => item.handle));
      assert.ok(value.notice.map(clean).includes(UK.UK3), value.notice.join(" | "));
      assert.deepEqual(value.posts, [], "the M20 request was submitted by itself");
      return { preselected: value.value, notice: value.notice };
    }));

  // ---- tab invariants and other tabs unchanged
  await rec_.part("tabs", [C("R-tabs")], () => rec_.step("M16-tabs",
    [C("R-tabs")], "Click 지식·보고서: 구조 분석 hidden and inert, no run choice here; click 단백질 " +
    "공학 and 리간드 설계·탐색: areas and masked text equal the record before the reaction work", async () => {
      await openKnowledge(page);
      const hidden = await structureHidden(page);
      const runChoice = await page.locator("#mw-app-panel-knowledge #run-choice").count();
      const runChoiceStructure = await page.locator("#mw-app-panel-structure #run-choice").count();
      const tabs = await page.locator(".mw-app-tabs [role=tab]").evaluateAll(items => items.map(item => item.textContent.trim()));
      const line = await globalRun(page);
      const after = { protein: await tabSignature(page, "단백질 공학", "protein"), ligand: await tabSignature(page, "리간드 설계·탐색", "ligand") };
      return { hidden, runChoice, runChoiceStructure, tabs, line, after };
    }, async value => {
      assert.deepEqual(value.hidden, { shown: "false", inert: true });
      assert.equal(value.runChoice, 0);
      assert.equal(value.runChoiceStructure, 1);
      assert.deepEqual(value.tabs, TAB_LABELS);
      assert.equal(value.line, runA);
      for (const name of ["protein", "ligand"]) {
        assert.ok(beforeSignatures[name], `${name} signature before was not recorded`);
        assert.deepEqual(value.after[name].areas, beforeSignatures[name].areas, `${name} areas`);
        assert.equal(value.after[name].text, beforeSignatures[name].text, `${name} text changed`);
      }
      return { hidden: value.hidden, areas: { protein: value.after.protein.areas, ligand: value.after.ligand.areas },
        textSha256: { protein: value.after.protein.textSha256, ligand: value.after.ligand.textSha256 } };
    }));

  // ---- wording summary (every detail check above ran the same search)
  await rec_.part("wording", [C("R-wording")], () => rec_.step("M17-wording",
    [C("R-wording")], "Open each stored result: no rank / importance / activity / effect wording " +
    "outside the fixed sentences and the verbatim reference strings", async () => {
      await openKnowledge(page);
      const list = await resultList(page, runA);
      const checked = [];
      for (const item of list.items) {
        await panel(page).locator(`input[data-testid="reaction-result"][data-reaction-result="${item.handle}"]`).check();
        const api = await detailApi(page, runA, item.handle);
        await panel(page).locator(`[data-testid="reaction-detail"][data-reaction-detail="${item.handle}"]`).waitFor({ timeout: 60000 });
        await waitFor(page, async () => await areaState(page, "detail") === "ready" ? true : null, "detail ready", 60000);
        checked.push({ handle: item.handle, found: forbiddenIn(await panelText(page), [api, list]) });
      }
      return checked;
    }, async value => {
      assert.ok(value.length >= 1);
      for (const item of value) assert.deepEqual(item.found, [], `${item.handle}: ${item.found.join(", ")}`);
      return { results: value.length };
    }));

  // ---- dry-run run (record made by the runner over the loopback API; every step here is a real click)
  if (plan.dryRun?.run) await rec_.part("dry-run", plan.dryRun.link.cases, async () => {
    const runD = plan.dryRun.run;
    evidence.runs.D = runD;
    evidence.fixtureLabels.push(DRY_RUN_LABEL);
    const item = plan.structures[plan.dryRun.structure];
    const loaded = await rec_.step("M18-dry-run-upload", [], `Choose the dry-run run in 저장된 run, upload ${item.name}`, async () => {
      await chooseRun(page, runD, false);
      return uploadLoad(page, item);
    }, async value => {
      const summary = await readApi(page, `/runs/${runD}`);
      assert.equal(summary.dry_run, true);
      return value;
    });
    const dctx = { evidence, handles: { [plan.dryRun.structure]: { loaded: loaded.handle, prepared: null } }, maps: {}, links: {} };
    const made = await rec_.step("M19-dry-run-link", plan.dryRun.link.cases, "In the dry-run run: link the same way (real clicks); " +
      "the result is stored and opens", () => linkCase(page, runD, dctx, plan.dryRun.link), async value => {
      const list = await resultList(page, runD);
      assert.ok(list.items.some(entry => entry.handle === value.handle));
      return { handle: value.handle, chains: value.verified.chains };
    });
    ctx.links[plan.dryRun.link.id] = made.handle;
    evidence.providerCalls.push(await providerCalls(page, runD));
  });
  evidence.providerCalls.push(await providerCalls(page, runA));
}

/** The nine admission refusals through labeled in-flight alterations of the real request (the form is filled). */
async function refusalsPart(page, rec_, evidence, run, ctx, plan, structure, map) {
  const other = ctx.handles[plan.refusals.otherStructure].loaded;
  const alter = {
    unknown_field: args => ({ ...args, qa_unknown_field: true }),
    structure_invalid: args => ({ ...args, structure: map }),
    pdb_id_invalid: args => ({ ...args, pdb_id: `${args.pdb_id}X` }),
    chains_invalid: args => ({ ...args, chains: [] }),
    chain_not_found: args => ({ ...args, chains: [{ chain_auth: "QZ", uniprot_accession: null }] }),
    accession_invalid: args => ({ ...args, chains: args.chains.map(chain => ({ ...chain, uniprot_accession: "not-an-accession" })) }),
    numbering_map_invalid: args => ({ ...args, numbering_map: structure }),
    structure_mismatch: args => ({ ...args, structure: other }),
    map_pdb_mismatch: args => ({ ...args, pdb_id: "0T91" }),
  };
  if (!evidence.fixtureLabels.includes(ALTER_LABEL)) evidence.fixtureLabels.push(ALTER_LABEL);
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
      done.push(await rec_.step(`F-${code}`, ["R-refusals"], `Click 연결하기 with the labeled alteration for ${code}: the refusal ` +
        `"${REFUSALS[code][0]} (${code})" shows beside ${REFUSALS[code][1] ?? "the request line"}; nothing stored`, async () => {
        const before = await resultCount(page, run);
        const posted = page.waitForResponse(response => response.request().method() === "POST" &&
          new URL(response.url()).pathname === `/api/runs/${run}/commands` && response.request().postDataJSON()?.tool === TOOL,
        { timeout: 60000 });
        await waitFor(page, async () => await t(page, "reaction-link").isEnabled() ? true : null, "연결하기 enabled", 15000);
        await t(page, "reaction-link").click();
        const response = await posted;
        let body = null;
        try { body = await response.json(); } catch { body = null; }
        const line = panel(page).locator(`[data-testid="reaction-refusal"][data-reason-code="${code}"]`);
        await line.waitFor({ timeout: 30000 });
        return { status: response.status(), body, before, after: await resultCount(page, run),
          text: clean(await line.textContent()), field: await line.evaluate(node => node.closest("[data-reaction-field]")
            ?.getAttribute("data-reaction-field") ?? null), lines: await panel(page).locator('[data-testid="reaction-refusal"]').count() };
      }, async value => {
        assert.equal(value.status, 422, JSON.stringify(value.body).slice(0, 300));
        const reason = value.body?.detail?.reason_code ?? value.body?.detail?.detail?.reason_code;
        assert.equal(reason, code);
        assert.ok(value.text.includes(`${REFUSALS[code][0]} (${code})`), value.text);
        assert.equal(value.field, REFUSALS[code][1], `${code} shown beside ${value.field}`);
        assert.equal(value.lines, 1);
        assert.equal(value.after, value.before, "a refused request stored a result");
        return { code, status: value.status, shown: value.text, field: value.field };
      }));
    } finally { await page.unroute(matcher, handler); }
  }
  return done;
}

/** After the runner changed the reaction folder: the main mode's stored results still open, with the snapshot mark. */
async function modeAfter(session, input, rec_, evidence, log) {
  const { page } = session;
  const runs = input.runs.split(",").filter(Boolean);
  const mode = input.mode;
  const caseId = { unset: "R-unset", invalid: "R-invalid", stale: "R-stale" }[mode];
  const reason = { unset: "not_installed", invalid: "snapshot_invalid" }[mode] ?? null;
  const badge = mode === "stale" ? STALE_TEXT : NO_ACTIVE_TEXT;
  runs.forEach((run, index) => { evidence.runs[index ? "D" : "A"] = run; });
  await waitForBoot(page);
  for (const [index, run] of runs.entries()) {
    await rec_.step(`${mode.toUpperCase()}-0${index + 1}`, [caseId], `Choose run ${run} in 저장된 run, click 지식·보고서: snapshot ` +
      `block ${reason ?? "of the new set"}; every stored result listed with "${badge}"; open each: it renders from events with the same mark`,
    async () => {
      await chooseRun(page, run);
      const started = Date.now();   // after the run choice (its viewer session POST belongs to 구조 분석)
      await openKnowledge(page);
      const list = await resultList(page, run);
      const labels = await panel(page).locator("label[data-reaction-result]").evaluateAll(items => items.map(item => ({
        handle: item.getAttribute("data-reaction-result"), stale: item.getAttribute("data-stale"),
        noActive: item.getAttribute("data-no-active-set"),
        mark: item.querySelector('[data-testid="reaction-snapshot-mark"]')?.textContent.trim() ?? null })));
      const opened = [];
      for (const item of list.items) {
        await panel(page).locator(`input[data-testid="reaction-result"][data-reaction-result="${item.handle}"]`).check();
        opened.push(await verifyDetail(page, run, item.handle, null, { badge: mode === "stale" ? STALE_TEXT : NO_ACTIVE_TEXT }));
      }
      const value = { api: await statusApi(page), list, labels, opened, posts: posts(log, started),
        snapshotState: await areaState(page, "snapshot"), snapshotText: clean(await area(page, "snapshot").textContent()),
        requestText: clean(await area(page, "request").textContent()), forms: await t(page, "reaction-request-form").count(),
        requestControls: await area(page, "request").locator("button, input, select, textarea, a").count(),
        capability: (await readApi(page, "/capabilities")).methods?.reaction_knowledge ?? null };
      if (mode === "stale") Object.assign(value, await snapshotReady(page, { setHash: input["set-hash"] }));
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
        checkSnapshotReady(value, input["set-hash"]);
        assert.notEqual(input["set-hash"], input["previous-set-hash"]);
        assert.equal(value.forms, 1, "the request block is closed with a usable set");
        for (const item of value.list.items) assert.equal(item.set_hash, input["previous-set-hash"], "a result was recomputed");
        assert.deepEqual([value.capability.available, value.capability.set_hash], [true, input["set-hash"]]);
      } else {
        assert.deepEqual([value.api.installed, value.api.reason], [false, reason]);
        assert.equal(value.snapshotState, "unavailable");
        assert.ok(value.snapshotText.includes(`${SNAPSHOT_REASON[reason]} (${reason})`) && value.snapshotText.includes(IMPORT_COMMAND),
          value.snapshotText);
        assert.ok(value.requestText.includes(`(${reason})`), value.requestText);
        assert.equal(value.forms, 0);
        assert.equal(value.requestControls, 0);
        assert.ok(noDigit(value.snapshotText) && noDigit(value.requestText), "a number in the unavailable blocks");
        assert.deepEqual([value.capability.available, value.capability.reason_code], [false, reason]);
        for (const item of value.list.items) assert.equal(item.set_hash, input["set-hash"]);
      }
      return { results: value.opened.map(item => ({ handle: item.handle, badge: item.badge })), api: value.api };
    });
    evidence.providerCalls.push(await providerCalls(page, run));
  }
}

// ------------------------------------------------------------------ main
const RUNNERS = { empty: modeEmpty, main: modeMain, unset: modeAfter, invalid: modeAfter, stale: modeAfter };
const HARNESS_FILES = ["reaction-knowledge-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs"];

function buildId() {
  const file = path.join(REPO, "frontend/.next/BUILD_ID");
  return fs.existsSync(file) ? fs.readFileSync(file, "utf8").trim() : null;
}

async function main() {
  const input = options(process.argv.slice(2));
  fs.mkdirSync(input.artifacts, { recursive: true });
  const evidence = { schema: "m26_reaction_evidence@1", mode: input.mode, stage: input.planData?.stage ?? null, runs: {},
    inputs: [], handles: {}, fixtureLabels: [], providerCalls: [], partFailures: [], controls: {}, observations: {},
    startedAt: new Date().toISOString() };
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
  const providerZero = evidence.providerCalls.length > 0 && evidence.providerCalls.every(item => item.zero);
  const blockedHosts = [...new Set((proof?.blockedRequests ?? []).map(item => item.origin))];
  const passed = !error && evidence.partFailures.length === 0 && offscreenComplete(proof) && proof.nonLoopbackRequests === 0 &&
    Object.keys(cases).length > 0 && Object.values(cases).every(value => value === "pass") && providerZero;
  evidence.finishedAt = new Date().toISOString();
  evidence.error = error ? String(error.stack ?? error) : null;
  evidence.requestCount = log.length;
  evidence.fixtureLabels = [...new Set(evidence.fixtureLabels)];
  fs.writeFileSync(path.join(input.artifacts, "reaction-evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
  fs.writeFileSync(path.join(input.artifacts, "reaction-requests.jsonl"), log.map(row => JSON.stringify(row)).join("\n") + "\n");
  const harness = Object.fromEntries(HARNESS_FILES.map(name => [name, sha(fs.readFileSync(path.join(__dirname, name)))]));
  const row = { schema: "m26_case_ledger_row@1", mode: input.mode, stage: evidence.stage, evidenceKind: "real_electron_offscreen",
    status: passed ? "pass" : "fail", cases, runId: evidence.runs.A ?? evidence.runs.E ?? null, runs: evidence.runs,
    handles: evidence.handles, inputs: evidence.inputs, fixtureLabels: evidence.fixtureLabels, controls: evidence.controls,
    observations: evidence.observations, buildId: buildId(), harness, setHash: input["set-hash"] ?? input.planData?.setHash ?? null,
    plan: input.plan, offscreen: proof, externalRequestCount: proof ? proof.nonLoopbackRequests : null, blockedHosts,
    providerCalls: evidence.providerCalls, providerCallsZero: providerZero, partFailures: evidence.partFailures,
    error: evidence.error, evidenceFile: path.basename(rec_.file), startedAt: evidence.startedAt, finishedAt: evidence.finishedAt };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ ok: passed, mode: input.mode, runs: evidence.runs, cases }) + "\n");
  if (error) process.stderr.write(`reaction-knowledge-flow ${input.mode} failed: ${error.stack ?? error}\n`);
  if (!passed) process.exitCode = 1;
}

if (require.main === module) main().catch(error => {
  process.stderr.write(`reaction-knowledge-flow failed: ${error.stack ?? error}\n`);
  process.exitCode = 1;
});

module.exports = { options, main, forbiddenIn, identityText, checkChainExpectation };
