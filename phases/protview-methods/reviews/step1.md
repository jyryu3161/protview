# Step1 / M7 — final Astra review

Reviewer: GPT-6 Astra. Implementation: GPT-6 Sol. Date: 2026-09-24. Product correction87994 and subsequent test-only correction68295 terminated normally; evidence chronology is recorded below.

Verdict: APPROVED

The selected local OpenMM protein-only potential/minimization method satisfies step1. The detailed source review, former findings, bounded scientific interpretation and attribution are in `docs/M7_OPENMM_REVIEW.md`. No blocking finding remains.

Actual final production API/guardian1UBQ success, launched timeout and cancellation have verified cleanup and correct one-attempt accounting. Public1HSG missing-terminal-OXT is typed412 with zero expensive charge. Independent native reconstruction matches the exact serialized System and before/after potentials within1.4552e-11kJ/mol. The fsynced pre-energy preparation and successful/failed/cancelled event-backed paths retain source/System/mapping provenance without inventing energy. Raw process identity preserves full ownership/cohort checks; public clock drift and huge-int malformed input are resolved without tolerance weakening.

Astra terminal independent probes pass positive native/checkpoint publication, all seven malformed scientific bundles, all three malformed checkpoint shapes, raw identity rejection/zero mocked signals, and exact engine-free M5/M6 events-only replay. Parent actual new done/cancelled replay also retains preparation with zero added events and no engine/process invocation.

Final host:288 passed,0 skipped,143.01s; full Ruff PASS; one existing deprecation warning. Terminal frontend19 tests/typecheck/build passed. Source-bound final browser confirms real minimized Mol* coordinates, exact report preview/download,43→43-event reopen,1/8budget, return to original and zero nonloopback/page errors. Complementary unchanged UI/API/science candidate coverage exercises actual approval/cancel, late async reads/actions, policy reset, independent failed reads/retries and old M6 report equality. Its changed guardian is covered by the final production/host reruns. Auxiliary canvas legend wording remains a documented nonblocking display limitation; actual coordinate identity and contact/mutation separation are correct.

Evidence: `/tmp/protview-qa/m7-final-host-evidence.json`, `m7-host-production-evidence.json`, `m7-independent-energy-evidence.json`, `m7-final-browser-evidence.json`, `m7-browser-candidate-evidence.json`, `m7-ui-events-only-recovery.json`, and `m7-astra-final-probe-evidence.json` in the same directory. Final hash inventory: `/tmp/protview-qa/m7-final-reviewed-hashes.json`.

This current extension review supersedes changed shared-source coverage relative to MVP baseline d22fe15 and accepted M6 commit50569ee. Historical MVP reviews remain preserved; no claim is made that their hashes are current. M6 and M7 are actual sequential branches, unlike the earlier unbranched MVP work. Parent owns actual ordered record-review0/1, acceptance reruns, `protview-methods --verify` and commit; those are not claimed complete by this review.

## Final test-only correction after the first verify attempt

The first actual ordered record-review0 and1 succeeded, but the subsequent real extension `--verify` failed: the full backend run reported1 failure/236 passes because the parent-loss test observed an existing but empty barrier marker. `/tmp/protview-qa/m7-final-gate-evidence.json` preserves that failed gate; it is not relabeled successful. Earlier host288/0 and production/browser evidence remain valid historical results on the unchanged product, not a claim that this later verification succeeded.

Astra confirmed a test publication race: child `Path.write_text` created/truncated the marker before writing, while the parent polled existence and immediately required exact content. Actual GPT-6 Sol worker68295 made only the test's private marker publication atomic: write a job-specific sibling temporary file, close it, then `Path.replace(marker)`. Exact stage, authenticated worker-start event, real parent kill/wait, interrupted state, empty owned group, budget1 and finally cleanup assertions are unchanged. No extra sleep, relaxed assertion, mock lifecycle or product change was introduced.

After normal worker termination, parent reran the real host test: **1 passed,0 skipped in1.62s**, with the existing deprecation warning. Evidence: `/tmp/protview-qa/m7-atomic-marker-final-host-evidence.json`. Astra independently compared all51 previously reviewed files: only `backend/tests/test_openmm.py` changed, to SHA256 `697901ea37005f8e3d1f0b0ee65648fddae6ad0adc2c00bd705e50129129ed12`. Product, scientific, UI and other evidence sources are unchanged; no repeat native/browser measurement is claimed or required for this test-only edit. Approval is reaffirmed for the corrected test and source inventory. Parent must now rerun ordered recording and actual extension --verify; no post-correction full-suite or successful final --verify is claimed here.

The original public1HSG/1UBQ CIF fixtures retain their required exact source SHA bytes. Their raw-input trailing whitespace is an explicit exception to staged whitespace checking, limited to those two files; do not normalize source fixtures or conceal a general whitespace-check failure.

## Exact reviewed files

- AGENTS.md
- README.md
- backend/mw/tools/sasa.py
- backend/mw/method_reports.py
- backend/mw/api/app.py
- backend/mw/runtime/orchestrator.py
- backend/mw/workspace.py
- backend/pyproject.toml
- backend/tests/test_sasa.py
- backend/tests/test_api.py
- config/tools.yaml
- frontend/app/page.tsx
- frontend/src/lib/api.ts
- frontend/src/lib/event-model.ts
- frontend/src/lib/report-selection.ts
- frontend/src/lib/area-format.ts
- frontend/tests/event-model.test.cjs
- frontend/tests/report-selection.test.cjs
- frontend/tests/area-format.test.cjs
- docs/ALTERNATIVE_METHODS_CONTRACT.md
- docs/ARCHITECTURE.md
- docs/DECISIONS.md
- docs/IMPLEMENTATION_PLAN.md
- docs/M6_SASA.md
- backend/mw/core/residue.py
- backend/mw/tools/structural.py
- backend/mw/reports.py
- frontend/src/components/MolstarViewer.tsx
- frontend/package.json
- docs/M6_SASA_REVIEW.md
- backend/mw/jobs/queue.py
- backend/mw/jobs/guardian.py
- backend/mw/jobs/lifecycle_fixture.py
- backend/mw/jobs/process_identity.py
- backend/mw/jobs/openmm_worker.py
- backend/mw/openmm_bundle.py
- backend/mw/openmm_reports.py
- backend/mw/tools/openmm_method.py
- backend/mw/tools/energetic.py
- backend/tests/test_jobs.py
- backend/tests/test_openmm.py
- backend/tests/fixtures/public_1ubq.cif
- backend/tests/fixtures/public_1hsg.cif
- frontend/src/lib/openmm-action.ts
- frontend/tests/openmm-action.test.cjs
- frontend/tests/openmm-api.test.cjs
- docs/M7_OPENMM.md
- docs/M7_PROCESS_IDENTITY.md
- docs/M7_OPENMM_REVIEW.md
- docs/JOBS_CONTRACT.md
- docs/JOBS_POSIX_ADDENDUM.md
