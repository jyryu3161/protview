"use strict";

// Assemble M11 H01–H17 ledger rows (ledger-row.json from chemical-flow.cjs and the acceptance runner)
// into one case-ledger.json. Rows are copied as observed; failures stay listed next to later passes.
// Usage: node frontend/tests/offscreen/m11-case-ledger.cjs --root <artifacts root> --out <case-ledger.json>
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

const T = (file, name) => `backend/tests/${file}::${name}`;
const CI = "test_chemical_interactions.py", JA = "test_m11_job_api.py", II = "test_m11_invalid_inputs.py";
// Declared evidence for every case in docs/M11_OFFSCREEN_QA_PLAN.md. UI controls count only through
// real_electron_offscreen rows; backend tests are the full gate's numeric/lifecycle evidence.
const CASE_PLAN = {
  H01: { title: "Capability ready and missing/wrong-version worker",
    ui: ["capability-ready", "capability-worker_missing", "capability-worker_version_invalid"],
    backend: [T(JA, "test_job_capability_uses_scientific_dependency_validation")],
    note: "Unavailable states use a labeled runtime layout (byte-identical backend copy without, or with a non-pinned, worker interpreter); never a fake success." },
  H02: { title: "Local run, receptor/SDF upload, model/record choice, ligand identity", ui: ["create"],
    backend: [T(CI, "test_raw_import_reuses_exact_bytes_across_filenames_and_old_metadata"),
      T(JA, "test_identical_sdf_import_under_alternate_filename_keeps_immutable_handle")] },
  H03: { title: "Connectivity (PDB CONECT and sidecar), acknowledgement, annotation, terminal declaration",
    ui: ["create", "attach-map_existing"],
    backend: [T(CI, "test_import_preview_and_exact_cap_declaration"),
      T(CI, "test_custom_terminal_cap_uses_exact_graph_and_h_vertices_not_name_template")] },
  H04: { title: "Create-new durable preparation with linked manifest/structure/graph", ui: ["create"],
    backend: [T(CI, "test_actual_native_create_detect_and_tamper_rejection")] },
  H05: { title: "Attach-existing exact instance, bijection preview and H policy",
    ui: ["attach-map_existing", "attach-replace_from_sdf", "invalid-attach"],
    backend: [T(CI, "test_attach_explicit_bijection_and_sidecar"),
      T(CI, "test_attach_covalent_ligand_bond_reports_exact_endpoint_atoms")] },
  H06: { title: "Invalid-input prerequisite errors with exact offending identities",
    ui: ["invalid-inputs", "invalid-attach", "job-controls-failure"],
    backend: [T(II, "test_invalid_create_inputs_reject_with_exact_identities"),
      T(II, "test_invalid_covalent_ligand_sidecar_reports_both_endpoints"),
      T(CI, "test_preflight_rejects_incomplete_backbone_and_histidine_alias"),
      T(CI, "test_v2000_only_and_isotope_radical_input_rejection"),
      T(CI, "test_native_rejects_disconnected_or_atrop_ligand"),
      T(CI, "test_native_receptor_h_valence_and_zero_bond_diagnostics"),
      T(CI, "test_native_ligand_zero_bond_diagnostic_uses_exact_sdf_indices"),
      T(JA, "test_native_receptor_graph_failure_is_typed_with_exact_uploaded_atom_refs")] },
  H07: { title: "Two expensive stages: approval, cancel (queued/running), failed retry, reload ownership",
    ui: ["create", "detect-controls", "job-controls", "job-controls-failure", "running-cancel", "attach-replace_from_sdf"],
    backend: [T(JA, "test_chemical_import_body_bound_and_queued_cancel"),
      T(JA, "test_running_native_worker_cancel_and_timeout"),
      T(JA, "test_native_worker_failure_charges_each_retry_without_publishing"),
      T(JA, "test_cross_run_busy_is_nonapproval_uncharged_and_resumable")] },
  H08: { title: "Actual pinned ProLIF on public example and analytic explicit graph",
    ui: ["create", "attach-map_existing"],
    backend: [T(CI, "test_native_public_geometry_on_both_sides_of_fixed_distance_cutoffs"),
      T(CI, "test_synthetic_acetate_anion_uses_native_reverse_ionic_roles"),
      T(CI, "test_native_graph_derived_doubly_protonated_histidine")],
    note: "Analytic explicit-graph runs are backend numeric tests; the public example is observed in Electron with independent geometry checks." },
  H09: { title: "Valid empty result is scientific_null; invalid chemistry stays error", ui: ["empty", "job-controls-failure"],
    backend: [T(CI, "test_native_valid_empty_after_ligand_translation"),
      T(CI, "test_native_bent_donor_hydrogen_rejects_short_donor_acceptor_pair"),
      T(CI, "test_preview_passes_but_native_rejects_synthetic_pentavalent_carbon")],
    note: "Bent/distant analytic negatives are backend numeric tests; the translated synthetic derivative is observed in Electron." },
  H10: { title: "Assignment table, pagination, categories, stale page, row focus/annotation", ui: ["create", "reopen-complete"],
    backend: [] },
  H11: { title: "Immediate and idle-gated exact refocus after orbit/representation change; return to ordinary",
    ui: ["create", "reopen-complete", "restrictions"], backend: [],
    note: "Camera-settle wait logic is also unit tested by npm --prefix frontend run test:events (tests/chemical.test.cjs)." },
  H12: { title: "M8/M9/M10 controls disabled with source-kind reason, annotation on and off", ui: ["create", "restrictions"],
    backend: [] },
  H13: { title: "Restoring an older M9 scene exits chemical display and re-enables controls", ui: ["restrictions"],
    backend: [] },
  H14: { title: "Report, browser downloads, reopen without recomputation",
    ui: ["create", "attach-map_existing", "reopen-complete", "reopen", "replay"],
    backend: [T(JA, "test_public_fixture_jobs_report_and_events_only_recovery"),
      T(JA, "test_chemical_report_discloses_attached_source_coordinates")] },
  H15: { title: "Races, held responses, busy controls, source deadline, WebGL loss",
    ui: ["create", "job-controls", "running-cancel", "faults"], backend: [] },
  H16: { title: "Events-only restart with original inputs and worker unavailable; reopen",
    ui: ["replay"], api: ["replay-probe-prebrowser", "replay-probe-postbrowser"],
    backend: [T(JA, "test_public_fixture_jobs_report_and_events_only_recovery"),
      T(JA, "test_native_candidates_cancel_before_terminal_remain_inaccessible_after_events_only_replay")] },
  H17: { title: "M8 normal, M9 scenes/export, M10 measure/alignment regressions",
    ui: ["regression-m8-normal", "regression-m9-scenes-core", "regression-m10-measure", "regression-m10-alignment"],
    backend: ["full backend gate: .venv/bin/python -m pytest backend/tests -q"] },
};

function rowsUnder(root) {
  const found = [];
  const walk = dir => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "browser-profile" || entry.name === "downloads") continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name === "ledger-row.json") found.push(full);
    }
  };
  walk(root);
  return found.sort();
}

function assemble(root) {
  const rows = rowsUnder(root).map(file => {
    const bytes = fs.readFileSync(file);
    return { rowFile: path.relative(root, file), rowSha256: crypto.createHash("sha256").update(bytes).digest("hex"),
      ...JSON.parse(bytes.toString("utf8")) };
  });
  const cases = {};
  for (const [id, plan] of Object.entries(CASE_PLAN)) {
    const required = [...plan.ui.map(mode => ["real_electron_offscreen", mode]),
      ...(plan.api ?? []).map(mode => ["direct_api", mode])];
    const coverage = required.map(([evidenceType, mode]) => {
      const matching = rows.filter(row => row.mode === mode && row.evidenceType === evidenceType);
      return { evidenceType, mode, rows: matching.map(row => ({ rowFile: row.rowFile, status: row.status,
        runId: row.runId, buildId: row.buildId, nonLoopbackRequests: row.nonLoopbackRequests })),
      status: matching.some(row => row.status === "pass") ? "pass" : matching.length ? "fail" : "missing" };
    });
    const status = coverage.every(item => item.status === "pass") ? "pass"
      : coverage.some(item => item.status === "missing") ? "missing" : "fail";
    cases[id] = { title: plan.title, status, coverage,
      backendTests: plan.backend, backendEvidence: "backend numeric/lifecycle test; pass/fail comes from the recorded full backend gate",
      note: plan.note ?? null };
  }
  return { schema: "m11_case_ledger@1", generatedAt: new Date().toISOString(), root: path.resolve(root),
    buildIds: [...new Set(rows.map(row => row.buildId))],
    summary: Object.fromEntries(["pass", "fail", "missing"].map(status =>
      [status, Object.values(cases).filter(item => item.status === status).length])),
    nonLoopbackRequestsTotal: rows.reduce((sum, row) => sum + (row.nonLoopbackRequests ?? 0), 0),
    rowsWithUnknownRequestCount: rows.filter(row => row.nonLoopbackRequests == null).map(row => row.rowFile),
    cases, rows };
}

function main(argv) {
  const input = { root: null, out: null };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--root") input.root = argv[++i];
    else if (argv[i] === "--out") input.out = argv[++i];
    else throw new Error(`Unknown argument ${argv[i]}`);
  }
  if (!input.root || !input.out) throw new Error("Usage: m11-case-ledger.cjs --root <artifacts root> --out <case-ledger.json>");
  const ledger = assemble(path.resolve(input.root));
  fs.mkdirSync(path.dirname(path.resolve(input.out)), { recursive: true });
  fs.writeFileSync(input.out, JSON.stringify(ledger, null, 2) + "\n");
  process.stdout.write(JSON.stringify({ out: path.resolve(input.out), summary: ledger.summary,
    rows: ledger.rows.length, nonLoopbackRequestsTotal: ledger.nonLoopbackRequestsTotal }) + "\n");
}

if (require.main === module) {
  try { main(process.argv.slice(2)); } catch (error) { process.stderr.write(`${error.stack ?? error}\n`); process.exitCode = 1; }
}
module.exports = { CASE_PLAN, assemble };
