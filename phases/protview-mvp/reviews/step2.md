# M2 independent integrated review — refreshed after final M5 integration

Reviewer: GPT-6 Astra. Date: 2026-09-24. Implementation: GPT-6 Sol. Scope: phases/protview-mvp/step2.md and docs/RUNTIME_CONTRACT.md. Both backend and frontend correction workers were terminal before this final review.

Verdict: APPROVED

## Final M5 shared-source refresh

Current final parent host Stop **240 passed, 0 skipped, 18.53s**, full Ruff PASS (`/tmp/protview-qa/m5-final-host-evidence.json`). Astra independently passed report/runtime/egress101 tests (3.28s), frontend8 tests and full Ruff, plus unchanged final M5 probes. This paragraph supersedes older current-source counts below; their historical attribution is retained. M5 adds report/workflow event types, fixed local API/report routes, selected-report UI and a compatible ApprovalRequired.requested_args field. Hash comparison against the accepted M4 snapshot identifies the changed existing API/events/runtime/page/globals/API-client files; structural/store/egress/job supervisor implementations remain unchanged.

M2 runtime ownership/budget/cache/finite recovery is preserved. The sole existing runtime edit separates pending approval requested_args from Python Exception.args, retaining gate/tool/reason catches; actual budget/loop/cancel and typed runtime failures are tested. Workflow calls remain autonomous within a bounded branch and resume validates its own physical/cache provenance. Human cache observations retain independent IDs and cannot overwrite workflow linkage.

## Earlier M4 shared-source evidence

This current-source refresh supersedes the older validation counts below; those paragraphs retain their historical attribution. Final parent host Stop **227 passed, 0 skipped, 17.84 seconds** and full Ruff PASS are bound in `/tmp/protview-qa/m4-final-host-evidence.json`. Astra independently ran final runtime **24 passed in 1.10s** and five admission regressions **5 passed in 0.46s**; earlier in the correction series, 120 core/structural/API/runtime/egress regressions and full Ruff passed. The later changes were confined to queue admission/shared reservation and their tests. The final parent full suite covers all current sources.

Shared `reserve_attempt` now counts durable job reservations under the short transition lock, preserves persisted approval and checks unresolved dispatch admission immediately before debit. Astra reran final probes: complete supervision+cleanup5s is charged5s; four pre-intent reservations survive reopen and fifth is denied; another unresolved job prevents new reservation/Popen and permits resumption only after verified closure. These changes preserve M2 ownership, cancellation, retry and cache semantics. The M4 lifecycle is separately approved; frontend normalization remains unchanged and previous cache/browser proofs retain their scope.

The selected M2 runtime and its M1 cache/viewer integration meet the gate. Four independently reproduced backend defects and one grouped malformed-cache frontend finding have been corrected and rechecked. This approves M2 implementation; actual step completion still requires the parent's harness acceptance execution and review/hash recording. No phase status, index or recorded hash was edited by the reviewer. M3 has its separate current approval in step3.md. M4 has its separate current approval in step4.md; M5 now has its separate approval in step5.md.

## Executed verification and attribution

Current M3 shared-source refresh: reviewer M3/runtime suites pass **88 tests in 2.49s**, core/structural/API suites pass **32 in 1.22s**, scoped Ruff passes, frontend test:events passes **six tests** and typecheck passes. Parent exact Stop Ruff and **151 combined tests** pass. M3 adds replayed external reservations/settlements under the existing owner; reviewer actual-child crash probes confirm actual usage settles once, overrun stops survive both interruption windows, and ambiguous dispatch retains its reservation without retransmission. The M2 retry/backoff/config/branch/cancellation regressions continue to pass. Final parent browser proof in `/tmp/protview-qa/m3-browser-evidence.json` retains cache/latest-input/empty/legacy 1HSG behavior. Details: docs/reviews/M3_EGRESS_REVIEW.md. The following original M2 evidence remains historical and separately attributed.

Astra independently executed the exact selected M2 checks on final source:

- `.venv/bin/python -m pytest backend/tests/test_runtime.py -q`: **24 passed in 1.12 s**.
- `.venv/bin/python -m ruff check backend/mw/runtime`: **passed**.
- `npm --prefix frontend run test:events`: **5 passed**.

Integration regressions independently executed during the final backend correction review: core, structural, API and runtime suites together **56 passed in 2.28 s**; backend Ruff passed. Final frontend typecheck passed. Backend source hashes still match that approved correction snapshot. Parent independently reports exact Stop Ruff and **97 backend/harness tests** passing; final Sol frontend handoff reports sequential passing typecheck/build, followed by parent browser testing of the restarted production artifact. The single existing Starlette TestClient deprecation warning is not suppressed or counted as a product failure.

Detailed reviewer-run probes, findings and exact source snapshots are in docs/reviews/M2_RUNTIME_REVIEW.md and docs/reviews/M2_FRONTEND_REVIEW.md. The parent's real HTTP cache fixture is `/tmp/protview-qa/m2-api-cache-fixture.json`; final browser results are `/tmp/protview-qa/m2-browser-evidence.json`. Fixture calculations are identified as synthetic geometry and are not energy validation.

## Backend contract assessment

Validation rejects unknown/unimplemented tools, invalid parameters, nonfinite values, wrong kinds and scalar/collection shape errors before physical execution. Version/default/seed/mode-aware normalized keys include the exact bytes used for structure import; original and repaired imports share that bound buffer. Cache reads verify the stored payload and immutable envelope, preserve original physical provenance and append an independent observation rather than a second tool success.

Transient policy is bounded to the original attempt plus three retries with 2/4/8 second backoff. Changed-argument repair and allowlisted prerequisite recovery are bounded and retain actual prerequisite output evidence. Resource/fatal failures and cancellation do not become unbounded retries; successful scientific_null is terminal. Human reads remain usable while durable autonomous branches enforce repeat, no-progress and oscillation bounds.

Approval, every real expensive-attempt reservation, failure time, backoff time and budget changes are event backed. Legacy success-only timing and new explicit charges are counted once. Active orphan attempts/backoffs receive bounded conservative reconciliation; clean idle/offline time is free. Configuration and progress state survive reopen; incompatible mode/seed/explicit limits are rejected. Execution ownership is exclusive across processes, with typed busy responses. Read-only construction does not reconcile an active owner.

Index recovery now publishes its complete verified snapshot in one SQLite transaction and rolls back on corruption; separate connections/processes retain the old valid index until commit. Event readers acquire the append lock in shared mode. Events-only recovery, object hash verification, typed API errors and M0/M1 geometry/provenance tests remain valid.

Dry runs emit typed plans even without stubs and never execute a real expensive implementation or produce synthetic scientific energy. The unavailable real energetic protocols fail before approval/reservation and are not exposed as available tools. M2 deadlines and cancellation remain cooperative inside Python/C execution; M4 owns hard subprocess termination.

## Resolved independent defect evidence

`/tmp/protview-qa/m2-corrected-independent-probe-results.json` records successful concurrent reads during paused index rebuild; exact 2.0-second legacy usage before/after reopen; a killed-backoff child producing a budget gate and one interruption/charge after repeated reopen; and repaired A-source output/cache remaining A despite a mutable path swap. The independent shared-event-lock barrier waits through a partial write and returns complete events. These are bounded lifecycle/identity probes, not scientific experiments.

The final frontend malformed-event probe rejects wrong keys, success-before-call order and duplicate observation IDs; it accepts canonical-equivalent reordered args. Source call and success must be unique, precede the cache, share tool/key and exactly match canonical args/output. Timeline cache entries come from validated event objects and use their own noncolliding observation IDs. Legacy cached successes remain readable. Full details and old failing evidence are retained in the two review documents and their referenced temporary artifacts.

## Live frontend integration

The parent exercised two synthetic inputs with identical model/residue identifiers and different coordinates. A's six-contact cache observation selects A's exact source, gives actual ASP focus and disables conflicting latest-pipeline mutation; B's zero-contact cached result remains a successful empty result after reload. Cached earlier load A displays raw A without a foreign table, and return-to-pipeline finds A's original prepared successor. Cached foreign preparation B after load A shows B without a table; return-to-pipeline restores A. The ledger retains six physical calls/successes and four unique cache observations, with no duplicate physical duration or expensive charge.

The legacy public 1HSG run reopens empty, then restores its historical 97-contact result and real ASP A25 lime focus. Parent observed no external requests or page errors. Astra inspected the cached-old-result, cached-load-pipeline and legacy-1HSG screenshots alongside source and structured evidence. This is review of the parent's actual browser session, not an invented independent session. The broader earlier M1 representation, invalid-upload, stale-byte, row-fetch-error and exact-input identity evidence remains applicable; step1.md is refreshed for current shared code.

Original M2 snapshot: `/tmp/protview-qa/m2-final-integrated-review-hashes.json`; current M3 refresh: `/tmp/protview-qa/m0-m3-refreshed-review-hashes.json`. The parent must record actual current hashes via the harness. M3 adapter safety and the single synthetic live connection have their separate approval in step3.md; no live model-quality benchmark is claimed. M4 hard worker cancellation and honest unavailable energy capability have their separate approval in step4.md; reporting has its separate M5 approval.

Final refreshed file inventory: `/tmp/protview-qa/m0-m4-refreshed-review-hashes.json`. Earlier snapshot paths remain historical. No phase index/status or recorded hash was edited.

## Exact reviewed files

- backend/mw/core/events.py
- backend/mw/core/handles.py
- backend/mw/core/contracts.py
- backend/mw/core/errors.py
- backend/mw/core/residue.py
- backend/mw/runtime/orchestrator.py
- backend/mw/runtime/guards.py
- backend/mw/api/app.py
- backend/mw/workspace.py
- backend/mw/tools/registry.py
- backend/mw/tools/structural.py
- backend/mw/tools/energetic.py
- config/tools.yaml
- backend/tests/test_core.py
- backend/tests/test_structural.py
- backend/tests/test_api.py
- backend/tests/test_runtime.py
- backend/tests/fixtures/mini_complex.pdb
- docs/M2_RUNTIME.md
- docs/RUNTIME_CONTRACT.md
- frontend/src/lib/event-model.ts
- frontend/tests/event-model.test.cjs
- frontend/tests/mode-badge.test.cjs
- frontend/src/components/shell.tsx
- frontend/app/page.tsx
- frontend/src/lib/contracts.ts
- frontend/src/lib/api.ts
- frontend/src/components/run.tsx
- frontend/src/components/MolstarViewer.tsx
- frontend/package.json
- frontend/package-lock.json
- docs/reviews/M2_RUNTIME_REVIEW.md
- docs/reviews/M2_FRONTEND_REVIEW.md
- backend/mw/egress/gate.py
- backend/mw/llm/openrouter.py
- backend/tests/test_llm_egress.py
- backend/pyproject.toml
- config/default.yaml
- docs/M3_EGRESS.md
- docs/reviews/M3_EGRESS_REVIEW.md
- backend/mw/jobs/queue.py
- backend/tests/test_jobs.py
- backend/mw/reports.py
- backend/mw/workflows.py
- backend/tests/test_reports.py
- frontend/src/lib/report-selection.ts
- frontend/tests/report-selection.test.cjs
- frontend/app/globals.css

Final comprehensive scope and source/report hashes: `/tmp/protview-qa/m0-m5-final-reviewed-hashes.json`. Earlier snapshot files remain historical. Parent must reattach current reviews and run final --verify; this reviewer changed no phase index/status or recorded hashes.
