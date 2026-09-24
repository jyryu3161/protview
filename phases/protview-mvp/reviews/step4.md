# M4 final independent review — refreshed after M5 integration

Reviewer: GPT-6 Astra. Date: 2026-09-24. Implementation: GPT-6 Sol, final correction session97453 terminal. Scope: phases/protview-mvp/step4.md and the jobs/runtime contracts.

Verdict: APPROVED

## Final M5 shared-source refresh

Current final parent host Stop **240 passed, 0 skipped, 18.53s**, full Ruff PASS (`/tmp/protview-qa/m5-final-host-evidence.json`). Astra independently passed report/runtime/egress101 tests (3.28s), frontend8 tests and full Ruff, plus unchanged final M5 probes. This paragraph supersedes older current-source counts below; their historical attribution is retained. M5 adds report/workflow event types, fixed local API/report routes, selected-report UI and a compatible ApprovalRequired.requested_args field. Hash comparison against the accepted M4 snapshot identifies the changed existing API/events/runtime/page/globals/API-client files; structural/store/egress/job supervisor implementations remain unchanged.

M4 queue/guardian/cohort/admission code remains unchanged. The full actual-host suite executes all lifecycle cases without process-table skips, including shared ApprovalRequired handling after the runtime attribute correction. Reports snapshot honest unavailable capabilities without dispatching lifecycle fixtures or claiming energies. The previously approved seven corrections and real-vs-mocked process evidence below remain applicable.

The selected M4 gate is satisfied. All seven confirmed findings are resolved: post-spawn cleanup, genuine virtual-environment launch/minimal environment, full active cleanup accounting, reservation-before-intent retry bounds, STOP/STARTED/RESULT ordering, ownership-safe survivor escalation and shared admission while earlier cleanup remains unverified. Full assessment and historical attribution are in docs/reviews/M4_JOBS_REVIEW.md.

Parent's final actual host Stop: **227 passed, 0 skipped, 17.84 seconds**, full Ruff PASS (`/tmp/protview-qa/m4-final-host-evidence.json`). Actual process tests require ready grandchildren with creation identities and verified teardown; they cover timeout/cancel/leader exit/parent death/owner exclusion. The worker sandbox's 17 skips are not used as lifecycle acceptance evidence. Astra independently ran final runtime **24 passed / 1.10s** and admission **5 passed / 0.46s**, plus unchanged independent accounting/admission probes on final source. Earlier reviewer shared regressions passed 120 tests and full Ruff; final host tests cover all current shared code.

Current independent probes establish 5 active seconds/5 charged; four persisted reservations/fifth denied; unclosed A blocks B with zero launch/debit and later resumes exactly once; and zero stranger signal while known survivors retain TERM/KILL escalation. Identity and admission fixtures are deterministic simulations, not actual PID reuse or scientific validation. Parent's actual STARTED BrokenPipe probe and host EOF tests verify real child cleanup. Evidence files are listed in the detailed review and final hash snapshot `/tmp/protview-qa/m4-final-review-hashes.json`.

Parent browser proof `/tmp/protview-qa/m4-browser-evidence.json`, inspected by Astra, retains 1HSG historical97-contact/actualASP A25 focus and shows four energy protocols honestly missing/unimplemented/not validated; no external browser request or page error. No licensed scientific protocol or new OpenRouter call ran. Under D07, unavailable optional engines do not prevent this selected gate; fixture job_lifecycle output is never represented as an energy result. Separate HARNESS_REVIEW.md is approved with actual JSON captures and preserved trust checks.

M0–M3 shared-source reports are refreshed; M5 now has its separate approval in step5.md. Parent must run actual phase checks and record these current review/file hashes through the executor. This document changes no phase status, index or recorded hash.

## Exact reviewed files

- backend/mw/jobs/queue.py
- backend/mw/jobs/guardian.py
- backend/mw/jobs/lifecycle_fixture.py
- backend/mw/jobs/rosetta_worker.py
- backend/mw/runtime/orchestrator.py
- backend/mw/core/events.py
- backend/mw/tools/energetic.py
- backend/mw/api/app.py
- backend/tests/test_jobs.py
- backend/tests/test_runtime.py
- backend/tests/test_api.py
- backend/pyproject.toml
- docs/M4_JOBS.md
- docs/JOBS_CONTRACT.md
- docs/JOBS_POSIX_ADDENDUM.md
- docs/RUNTIME_CONTRACT.md
- docs/reviews/M4_JOBS_REVIEW.md
- backend/mw/reports.py
- backend/mw/workflows.py
- backend/tests/test_reports.py

Final comprehensive scope and source/report hashes: `/tmp/protview-qa/m0-m5-final-reviewed-hashes.json`. Earlier snapshot files remain historical. Parent must reattach current reviews and run final --verify; this reviewer changed no phase index/status or recorded hashes.
