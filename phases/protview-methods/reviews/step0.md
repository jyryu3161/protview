# Step0 / M6 — Astra shared-source refresh after M7

Reviewer: GPT-6 Astra. Implementation: GPT-6 Sol. Date: 2026-09-24. Current branch: phase/m7-openmm-minimization.

Verdict: APPROVED

M6 was actually approved, recorded and committed as50569ee on phase/m6-interface-sasa. Its original scientific validation remains documented in `docs/M6_SASA_REVIEW.md`. This review refreshes current shared-source coverage after the separate M7 extension; it does not pretend M7 code was part of the historical M6 commit.

The SASA engine adapter, result/report validators, area formatting, core residue/object/event/runtime and old M5 report implementations remain unchanged from accepted M6. Approved scientific settings remain real FreeSASA2.2.1 Lee–Richards100/probe1.4Å/thread1 with recorded radii. Original1HSG independent agreement is ≤4.55e-11Å² across summaries and ≤1.24e-11Å² across198 residue rows; no values or settings were patched. The M6 paired kind/schema blocker remains fixed.

Changed API/structure-bytes/registry/dependencies/UI and queue/guardian code is reviewed in the companion `docs/M7_OPENMM_REVIEW.md` and exact file list below. Legacy Rosetta protocol records remain separate from new OpenMM capability. The new protein-only coordinates cannot overwrite source complex or old SASA/contact results. Actual old M6 browser report bytes remain exact; independent copied-events-only M5/M6 recovery forbids both engines, recovers identical manifests/Markdown and adds no events. Source lineage, stale response guards and original-input return remain covered by existing tests and current actual browser evidence.

Current parent full host evidence:288 passed,zero skipped,143.01s plus full Ruff PASS (one existing deprecation warning), with before/after source hashes equal at the original review; the later test-only correction is isolated below. Terminal frontend19 tests/typecheck/build pass. M7 production/native/lifecycle and browser evidence demonstrate that the added shared dispatch/identity paths preserve bounded accounting, cleanup and immutable reports. The current SASA frontend/API regressions are included in this refresh; an auxiliary minimized-view legend wording limitation is explicitly nonblocking and does not alter scientific identity.

Evidence: `/tmp/protview-qa/m7-final-host-evidence.json`, `/tmp/protview-qa/m7-astra-final-probe-evidence.json`, `/tmp/protview-qa/m7-final-browser-evidence.json`, `/tmp/protview-qa/m7-browser-candidate-evidence.json`; original measurement evidence remains `/tmp/protview-qa/m6-independent-lr-reference.json` and `/tmp/protview-qa/m6-final-browser-evidence.json`. Final current hash inventory: `/tmp/protview-qa/m7-final-reviewed-hashes.json`.

This extension supersedes changed shared-source coverage relative to historical MVP baseline d22fe15. Historical MVP review/spec files remain intact; no fresh `protview-mvp --verify` claim is made. Parent will bind this refreshed approval and step1 to actual acceptance reruns and extension --verify. Review approval is distinct from those pending recorder actions.

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
