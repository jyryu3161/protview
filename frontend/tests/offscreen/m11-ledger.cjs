"use strict";

// M11 case-ledger rows for chemical-flow.cjs runs. A row records what one actual offscreen run
// observed; it never upgrades a failure and never supplies scientific values.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

const FRONTEND = path.resolve(__dirname, "../..");
const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");

// Declared provenance for every file a chemical-flow mode may choose. Unknown files are labeled as such.
const PROVENANCE = {
  "prolif-vina-rec.pdb": "public ProLIF tutorial prepared receptor (prepared docking example; not experimental validation)",
  "prolif-vina-output.sdf": "public ProLIF tutorial docking-pose SDF (prepared docking example; not experimental validation)",
  "synthetic-pentavalent-carbon.sdf": "labeled synthetic failure-control SDF (impossible valence; no scientific output)",
  "m11-synthetic-empty-1000A.sdf": "synthetic derivative: public SDF record 0 translated +1000 Å (empty-result control; not experimental evidence)",
  "m11-attach-complex.pdb": "synthetic derivative: public receptor + public SDF record 0 as LIG L 1 (attach fixture; not experimental evidence)",
  "m11-attach-bonds-run.json": "run-bound receptor_bonds@1 sidecar generated from the QA run's own source catalog",
  "m11-attach-mapping-run.json": "run-bound labeled map_existing SDF→AtomRef mapping from the QA run's source catalog",
  "m11-attach-mapping-replace-run.json": "run-bound labeled replace_from_sdf heavy-atom mapping from the QA run's source catalog",
  "m11-attach-ligand-instance-run.json": "run-bound exact selected ligand instance from the QA run's source catalog",
  "m11-invalid-cases.json": "manifest of labeled synthetic invalid-input derivatives (scripts/m11_invalid_inputs.py)",
};
function provenanceLabel(name) {
  if (PROVENANCE[name]) return PROVENANCE[name];
  if (name.startsWith("m11-invalid-")) return "labeled synthetic invalid-input derivative of the public fixture (scripts/m11_invalid_inputs.py); not experimental evidence";
  return "unlabeled file (not a declared M11 QA input)";
}

// Which H cases a passing run of each ledger mode observes through actual offscreen input.
const MODE_CASES = {
  "capability-ready": ["H01"], "capability-worker_missing": ["H01"], "capability-worker_version_invalid": ["H01"],
  create: ["H02", "H03", "H04", "H07", "H08", "H10", "H11", "H12", "H14", "H15"],
  empty: ["H09"],
  "prepare-only": ["H04", "H07"],
  "detect-controls": ["H07"],
  "job-controls": ["H07", "H15"],
  "job-controls-failure": ["H06", "H07", "H09"],
  "running-cancel": ["H07", "H15"],
  "retry-failed": ["H07"],
  "attach-map_existing": ["H03", "H05", "H08", "H14"],
  "attach-replace_from_sdf": ["H05", "H07"],
  "reopen-complete": ["H10", "H11", "H14"],
  restrictions: ["H11", "H12", "H13"],
  faults: ["H15"],
  "invalid-inputs": ["H06"],
  "invalid-attach": ["H05", "H06"],
  reopen: ["H14"],
  replay: ["H14", "H16"],
};

function ledgerMode(input) {
  if (input.mode === "capability") return `capability-${input.expectCapability}`;
  if (input.mode === "job-controls" && input.failureExpected === "true") return "job-controls-failure";
  if (input.mode === "attach" && input.mapping) {
    try { return `attach-${JSON.parse(fs.readFileSync(input.mapping, "utf8")).hydrogen_policy ?? "map_existing"}`; }
    catch { return "attach-unknown"; }
  }
  return input.mode;
}
function fileDigest(file) {
  const bytes = fs.readFileSync(file);
  return { name: path.basename(file), bytes: bytes.length, sha256: sha(bytes), provenance: provenanceLabel(path.basename(file)) };
}
function helperSha256() { return sha(fs.readFileSync(__filename)); }
function buildId() {
  try { return fs.readFileSync(path.join(FRONTEND, ".next/BUILD_ID"), "utf8").trim(); } catch { return null; }
}
/** Real Electron offscreen proof: isOffscreen, GPU, paint and blocked non-loopback requests, plus WebGL renderer. */
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
  return { offscreen: state.offscreen, visible: state.visible, painting: state.painting,
    hardwareAccelerationEnabled: state.hardwareAccelerationEnabled, paintCount: state.paintCount,
    webgl, nonLoopbackRequests: state.blockedRequests.length, blockedRequests: state.blockedRequests,
    loopbackRequestCount: state.loopbackRequestCount, versions: state.versions };
}
function handlesOf(evidence) {
  const pick = value => typeof value === "string" && value.startsWith("obj://") ? value : null;
  return Object.fromEntries(Object.entries({
    result: pick(evidence.resultHandle) ?? pick(evidence.result?.meta?.handle),
    report: pick(evidence.reportHandle),
    source: pick(evidence.prepared?.sourceHandle) ?? pick(evidence.native?.sourceHandle) ??
      pick(evidence.derivedSource?.sourceHandle),
    graph: pick(evidence.prepared?.graphHandle) ?? pick(evidence.prepareOnly?.graphHandle),
    scene: pick(evidence.scene?.handle),
    prepareJob: evidence.prepare?.id ?? evidence.jobControl?.jobId ?? evidence.runningCancellation?.id ?? null,
    detectJob: evidence.detect?.id ?? evidence.detectControl?.id ?? null,
  }).filter(([, value]) => value));
}
function writeRow(input, evidence) {
  const mode = evidence.ledgerMode ?? ledgerMode(input);
  const proof = evidence.offscreen ?? null;
  const offscreenOk = !!proof && proof.offscreen === true && proof.visible === false && proof.painting === true &&
    proof.hardwareAccelerationEnabled === true && proof.paintCount > 0 && !!proof.webgl;
  const pass = evidence.status === "observed_unreviewed" && offscreenOk && proof.nonLoopbackRequests === 0;
  const chosen = [...Object.values(evidence.files ?? {}), ...(evidence.cases ?? []).flatMap(item =>
    [...Object.values(item.files ?? {}), ...(item.upload ? [item.upload] : [])])]
    .map(item => ({ name: item.name ?? path.basename(item.path ?? item.file), sha256: item.sha256,
      provenance: item.provenance ?? provenanceLabel(path.basename(item.path ?? item.file ?? "")) }));
  const fixtures = [...new Map([...Object.values(evidence.fixtureFiles ?? {}),
    ...(evidence.variantsManifest ? [evidence.variantsManifest] : []), ...chosen]
    .map(item => [`${item.name}:${item.sha256}`, item])).values()];
  const labels = [];
  if (input.fixtureLabel) labels.push(input.fixtureLabel);
  if (evidence.conflictProof ?? evidence.prepare?.conflictProof) labels.push("renderer-route fixture: labeled non-approval 409 on Start");
  if (input.mode === "faults") labels.push("renderer-route fixtures: malformed catalog SHA, held GETs, bounded source-read deadline, WEBGL_lose_context");
  if (input.mode === "job-controls") labels.push("renderer-route fixtures: held jobs GET, held upload, held job submission");
  const row = {
    schema: "m11_case_ledger_row@1",
    cases: MODE_CASES[mode] ?? [],
    mode, harnessMode: input.mode,
    evidenceType: "real_electron_offscreen",
    status: pass ? "pass" : "fail",
    harnessStatus: evidence.status,
    error: evidence.error ?? (pass ? null : !offscreenOk ? "offscreen proof incomplete" : null),
    buildId: evidence.buildId ?? buildId(),
    harness: { chemicalFlowSha256: evidence.harnessSha256, ledgerHelperSha256: evidence.ledgerHelperSha256 },
    fixtures, provenanceLabels: [...new Set(fixtures.map(item => item.provenance))], fixtureLabels: labels,
    runId: evidence.run ?? null, handles: handlesOf(evidence),
    expectCapability: input.expectCapability ?? null,
    nonLoopbackRequests: proof ? proof.nonLoopbackRequests : null,
    offscreen: proof && { offscreen: proof.offscreen, visible: proof.visible, painting: proof.painting,
      hardwareAccelerationEnabled: proof.hardwareAccelerationEnabled, paintCount: proof.paintCount, webgl: proof.webgl },
    artifacts: input.artifacts, evidenceFile: "chemical-evidence.json",
    startedAt: evidence.startedAt, finishedAt: evidence.finishedAt,
  };
  fs.writeFileSync(path.join(input.artifacts, "ledger-row.json"), JSON.stringify(row, null, 2) + "\n");
  return row;
}

module.exports = { MODE_CASES, PROVENANCE, provenanceLabel, ledgerMode, fileDigest, helperSha256, buildId,
  offscreenProof, writeRow };
