# M3 independent final review — refreshed after final M5 integration

Reviewer: GPT-6 Astra. Date: 2026-09-24. Specification: phases/protview-mvp/step3.md and docs/EGRESS_CONTRACT.md. Implementation: terminal GPT-6 Sol correction session 50991.

Verdict: APPROVED

## Final M5 shared-source refresh

Current final parent host Stop **240 passed, 0 skipped, 18.53s**, full Ruff PASS (`/tmp/protview-qa/m5-final-host-evidence.json`). Astra independently passed report/runtime/egress101 tests (3.28s), frontend8 tests and full Ruff, plus unchanged final M5 probes. This paragraph supersedes older current-source counts below; their historical attribution is retained. M5 adds report/workflow event types, fixed local API/report routes, selected-report UI and a compatible ApprovalRequired.requested_args field. Hash comparison against the accepted M4 snapshot identifies the changed existing API/events/runtime/page/globals/API-client files; structural/store/egress/job supervisor implementations remain unchanged.

M3 gate/transport/projection and settlement implementations remain unchanged. The101 independently executed tests include64 egress regressions plus runtime/report integration. Report generation stays local_rules_no_egress and never invokes the model, even when a key is configured. No additional live call was made; the single earlier synthetic connectivity smoke retains its original scope and evidence.

## Earlier M4 shared-source evidence

This current-source refresh supersedes the older validation counts below; those paragraphs retain their historical attribution. Final parent host Stop **227 passed, 0 skipped, 17.84 seconds** and full Ruff PASS are bound in `/tmp/protview-qa/m4-final-host-evidence.json`. Astra independently ran final runtime **24 passed in 1.10s** and five admission regressions **5 passed in 0.46s**; earlier in the correction series, 120 core/structural/API/runtime/egress regressions and full Ruff passed. The later changes were confined to queue admission/shared reservation and their tests. The final parent full suite covers all current sources.

M4 changes shared runtime/events/API and adds honest job capabilities; the strict M3 gate/transport/projection source files remain unchanged. Current full regressions preserve reservation/settlement, interruption, owner exclusion and mode behavior. The actual single synthetic live smoke described below remains the only live request; no second request, model-quality claim or credential inspection was made for this refresh. M4 process supervision is approved separately; M5 reporting now has its separate approval in step5.md.

All seven initial findings are resolved and the selected M3 boundary is implemented. Local/dry decisions retain a complete labeled rule path without key lookup or transport. Optional online advice uses a strict numeric projection, one fixed Decisions transport owner, explicit model mapping/privacy policy, bounded request/response handling, durable audit and per-axis actual/unknown accounting. The operation recommends existing local views, not scientific quality or affinity. No response cache, remote fetch or generic chat endpoint is claimed.

## Verification and live evidence

Astra independently executed 88 M3/runtime tests, scoped Ruff, six frontend tests and typecheck; core/structural/API regression suites additionally passed 32 tests. The original real-child crash probes now verify one-time actual settlement and persistent overrun stops, with live-owner exclusion and ambiguous-dispatch reservation preservation. Parent confirms exact Stop Ruff and 151 combined tests passing; the worker's final typecheck/build passed and parent browser QA used that artifact. Detailed correction evidence and exact attribution are in docs/reviews/M3_EGRESS_REVIEW.md.

Parent made one authorized live synthetic request, no retry: HTTP 200, accepted summary, request alias typesafe/jev-1.13, served typesafe/jev-1.13-20260917. Actual usage was 493 input + 52 output = 545 tokens, cost $0.000020706, one expensive attempt. Prepared payload SHA-256 `395fe61ffc464d762b8da09a360c709af81095e2d3862425a4777a9d27907afc` matches the reviewer's independent safe-body recomputation. Audits distinguish prepared, dispatch intent, received response and settlement. Synthetic input produced no scientific object event and the parent's artifact scan found no credential. Evidence: `/tmp/protview-qa/m3-live-evidence.json`. This establishes connectivity/schema compatibility, not scientific model quality.

Final parent browser evidence `/tmp/protview-qa/m3-browser-evidence.json` confirms truthful local/online/dry mode display, default local-only new runs, real reopened 1HSG with 97 contacts and actual ASP A25 focus, six-row cached historical input association and successful cached empty results. No external browser requests or page errors occurred. Astra inspected the mode and 1HSG screenshots. No actual key or external request was used by this reviewer.

Current snapshot: `/tmp/protview-qa/m3-final-review-hashes.json`. M0–M2 shared-source reports are refreshed separately. No phase status or recorded hash was edited by the reviewer; the parent must record actual checks and current hashes through the harness. M4 durable jobs have their separate approval in step4.md; M5 evidence-bound reports now have their separate approval in step5.md.

Final refreshed file inventory: `/tmp/protview-qa/m0-m4-refreshed-review-hashes.json`. Earlier snapshot paths remain historical. No phase index/status or recorded hash was edited.

## Exact reviewed files

- backend/mw/egress/gate.py
- backend/mw/llm/openrouter.py
- backend/mw/llm/prompts.py
- backend/mw/llm/verifier.py
- backend/mw/runtime/orchestrator.py
- backend/mw/runtime/guards.py
- backend/mw/core/events.py
- backend/mw/core/residue.py
- backend/mw/workspace.py
- backend/mw/api/app.py
- config/default.yaml
- backend/tests/test_llm_egress.py
- frontend/src/components/shell.tsx
- frontend/app/page.tsx
- frontend/src/lib/api.ts
- docs/M3_EGRESS.md
- docs/EGRESS_CONTRACT.md
- backend/pyproject.toml
- frontend/package.json
- frontend/tests/mode-badge.test.cjs
- frontend/tests/event-model.test.cjs
- frontend/src/lib/event-model.ts
- docs/reviews/M3_EGRESS_REVIEW.md
- backend/mw/jobs/queue.py
- backend/mw/tools/energetic.py
- backend/tests/test_jobs.py
- backend/mw/reports.py
- backend/mw/workflows.py
- backend/tests/test_reports.py
- frontend/src/lib/report-selection.ts
- frontend/tests/report-selection.test.cjs
- frontend/app/globals.css

Final comprehensive scope and source/report hashes: `/tmp/protview-qa/m0-m5-final-reviewed-hashes.json`. Earlier snapshot files remain historical. Parent must reattach current reviews and run final --verify; this reviewer changed no phase index/status or recorded hashes.
