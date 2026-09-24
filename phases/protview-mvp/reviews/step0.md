# M0 independent review — refreshed after final M5 integration

Reviewer: GPT-6 Astra. Date: 2026-09-24. Specification: phases/protview-mvp/step0.md. This refresh covers the M0 contract on the current shared backend revision; it does not grant full M2 or later-phase approval. Parent records actual source hashes through the executor after implementation is stable.

Verdict: APPROVED

## Final M5 shared-source refresh

Current final parent host Stop **240 passed, 0 skipped, 18.53s**, full Ruff PASS (`/tmp/protview-qa/m5-final-host-evidence.json`). Astra independently passed report/runtime/egress101 tests (3.28s), frontend8 tests and full Ruff, plus unchanged final M5 probes. This paragraph supersedes older current-source counts below; their historical attribution is retained. M5 adds report/workflow event types, fixed local API/report routes, selected-report UI and a compatible ApprovalRequired.requested_args field. Hash comparison against the accepted M4 snapshot identifies the changed existing API/events/runtime/page/globals/API-client files; structural/store/egress/job supervisor implementations remain unchanged.

M0 immutable source/handle/preparation and event reconstruction contracts remain covered by the current full host suite. Independent M5 recovery deleted original temporary source, objects and SQLite and restored exact report/evidence bytes with all scientific functions forbidden. Report objects use the existing verified immutable store; no substitute source or new science was used.

## Earlier M4 shared-source evidence

This current-source refresh supersedes the older validation counts below; those paragraphs retain their historical attribution. Final parent host Stop **227 passed, 0 skipped, 17.84 seconds** and full Ruff PASS are bound in `/tmp/protview-qa/m4-final-host-evidence.json`. Astra independently ran final runtime **24 passed in 1.10s** and five admission regressions **5 passed in 0.46s**; earlier in the correction series, 120 core/structural/API/runtime/egress regressions and full Ruff passed. The later changes were confined to queue admission/shared reservation and their tests. The final parent full suite covers all current sources.

M4 adds job event types, API capability/jobs projections, a direct psutil dependency and guarded shared attempt reservation. Existing handle/store/structural source bytes and scientific identity remain unchanged from the accepted M3 snapshot. Event-authoritative recovery, source-bound imports and typed API regression tests remain passing. Unresolved jobs block new physical execution without altering immutable cache reads. This report approves M0 continuity only; M4 process behavior has its separate step4 review.

## Current evidence

Current M3 shared-source refresh: independently executed core/structural/API suites, **32 passed in 1.22s**, and M3/runtime suites, **88 passed in 2.49s**. Scoped egress/llm/runtime Ruff passed. Parent full Stop Ruff and 151 combined tests passed. The existing Starlette TestClient deprecation warning remains disclosed. The egress additions preserve M0 import, handle, preparation and recovery behavior; current M3 review is docs/reviews/M3_EGRESS_REVIEW.md.

Current M0 assertions retain full content SHA identity; type/schema checks; events-only restoration after original source, object directory and SQLite index removal; corrupt payload rejection; deterministic explicit preparation policy; nondefault MODEL 5 preservation; nullable label identifiers with model/auth/insertion-code identity; selected high-occupancy alternate location; nonfinite input rejection; source-byte-aware caching; sparse Parquet normalization before hashing; and rejection of conflicting metadata for identical object content. Preparation envelopes bind coordinate and manifest objects so identical coordinates under different policies retain distinct scientific identity. M1 interaction envelopes similarly bind actual input, ligand selection, cutoff and method, including equal or empty rows.

The M2 index correction now publishes verified replay inside one SQLite transaction. Executed tests cover a reader in a separate spawned process and rollback on a corrupt event. The reviewer's independent paused-rebuild probe also reads the durable handle successfully throughout the rebuild. M2 repaired imports now bind the same bytes to key and implementation: the independent source-swap fixture produces and caches A despite the source path changing to B before the implementation reads. These fixes preserve, rather than weaken, the M0 immutable-content boundary. Detailed corrected probe evidence is in `/tmp/protview-qa/m2-corrected-independent-probe-results.json`; backend review is docs/reviews/M2_RUNTIME_REVIEW.md.

M1 upload confinement, object symlink protections, explicit scalar/collection cardinality and typed invalid-input responses remain covered by the executed API/core regressions. Versioned structure_selection@2 and load_structure 0.1.1 preserve old object identity while exposing unique author-chain summaries.

The parent's earlier independent public 1HSG measurement remains scientific corroboration: source SHA-256 `d2ba73b5c4be05c45275571bbb4dd042347927f91c6c05038c0df5d1ce23c268`; cutoff 4 angstrom produced 97 atom pairs across 26 residues with minimum distance 2.6264474104767457 angstrom, matching a separate direct gemmi/math.dist calculation. This historical real-structure evidence is not relabeled as a newly executed calculation. It supports coordinate geometry, not chemical bond classification, energy, affinity or stability prediction.

## Resolved findings and scope

Earlier M0 model-number, nullable residue identity, preparation-provenance collision and sparse-Parquet defects were corrected and remain tested. Earlier M1 upload and handle-cardinality defects were corrected and remain tested. The M2 concurrent-index and repaired-source defects affecting M0 are now independently resolved. The prior chronological review is retained in `/tmp/protview-qa/m0-review-before-m2-refresh.md`; its intermediate pending statements do not describe this revision.

No energetic backend result, M3 egress behavior, M4 process termination or M5 report behavior is approved here. M2 cache-normalization and browser evidence remain accepted, with M3 current-source regression refresh recorded in step2.md. The parent must refresh review records through the real harness; this document does not change phase status or recorded hashes.

Current hashes for this refreshed scope are in `/tmp/protview-qa/m0-m4-refreshed-review-hashes.json`. Earlier M2 probe hashes refer to their explicitly historical snapshots.

Final refreshed file inventory: `/tmp/protview-qa/m0-m4-refreshed-review-hashes.json`. Earlier snapshot paths remain historical. No phase index/status or recorded hash was edited.

## Exact reviewed files

- backend/mw/core/handles.py
- backend/mw/core/events.py
- backend/mw/core/contracts.py
- backend/mw/core/residue.py
- backend/mw/runtime/orchestrator.py
- backend/mw/tools/structural.py
- backend/mw/tools/registry.py
- backend/mw/workspace.py
- backend/mw/api/app.py
- config/tools.yaml
- backend/tests/test_core.py
- backend/tests/test_structural.py
- backend/tests/test_api.py
- backend/tests/test_runtime.py
- backend/tests/fixtures/mini_complex.pdb
- backend/mw/jobs/queue.py
- backend/mw/tools/energetic.py
- backend/tests/test_jobs.py
- backend/pyproject.toml
- backend/mw/reports.py
- backend/mw/workflows.py
- backend/tests/test_reports.py

Final comprehensive scope and source/report hashes: `/tmp/protview-qa/m0-m5-final-reviewed-hashes.json`. Earlier snapshot files remain historical. Parent must reattach current reviews and run final --verify; this reviewer changed no phase index/status or recorded hashes.
