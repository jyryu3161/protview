# M4 final independent review — durable local jobs

Reviewer: GPT-6 Astra. Date: 2026-09-24. Implementation: GPT-6 Sol; final admission correction session97453 was terminal before review. Specification: phases/protview-mvp/step4.md, docs/JOBS_CONTRACT.md and docs/JOBS_POSIX_ADDENDUM.md.

Verdict: APPROVED

Final M5 shared-source refresh: queue/guardian/lifecycle source is unchanged; shared runtime/API/events integration is reviewed in step4.md. Parent current actual host Stop240 passed/0skipped18.53s and full Ruff PASS include all lifecycle regressions. ApprovalRequired pending arguments now use requested_args while existing job catch behavior is preserved. No new licensed protocol or model call ran. Current scope/hash inventory is `/tmp/protview-qa/m0-m5-final-reviewed-hashes.json`; prior counts below retain their historical attribution.

The selected M4 lifecycle and honest capability boundary meet the gate. All seven independently identified findings have correction evidence. This approval does not claim an available licensed energy implementation or scientific validation. Parent must still execute acceptance checks and attach this review through the real harness; the reviewer has not changed phase status, index, recorded hashes, implementation or hook trust.

## Final verification and attribution

Parent's final actual host Stop ran **227 passed, 0 skipped, 17.84 seconds**, with full Ruff passing. Evidence `/tmp/protview-qa/m4-final-host-evidence.json` binds current sources. It includes actual guardian/worker/grandchild timeout, cancellation, leader-exit, competing-owner and parent-death tests. Mandatory readiness, PID/create-time identity and verified teardown assertions are present. The worker's **210 passed / 17 skipped** sandbox result is separate: Darwin process enumeration was denied there; it is not substituted for the host lifecycle result.

Astra independently reran the final shared runtime suite (**24 passed in 1.10 seconds**) and five admission regressions (**5 passed in 0.46 seconds**). Earlier in this stable correction series, Astra ran **120 runtime/core/API/structural/egress regressions in 3.48 seconds** and full Ruff; the final runtime/admission checks cover the subsequent two source changes. The existing Starlette TestClient deprecation warning remains disclosed.

Astra independently reran the unchanged admission and accounting probes at 03:42:39 UTC against final queue SHA `d607fc7377f40bad87efe37a8b02dce1cbcafa2e8e726f793f8a03c1d34c5910` and runtime SHA `e678c7c5f47c8fd07601b8e28c49b3274fd0753cf2ad90accad899769cdf4143`. Parent independently reran the identity probe against that queue and the actual STARTED-send failure probe, all passing. These probes have distinct evidence boundaries:

- `/tmp/protview-qa/m4-astra-admission-probe.py` and `m4-astra-admission-probe-results.json`: deterministic event/launch simulation. Unclosed A blocks B with zero launch, total expense still one, and B remains claimed. Fixture-only verified closure then permits one fake failed launch and total expense two. No OS process or scientific result.
- `/tmp/protview-qa/m4-astra-accounting-probes.py` and `m4-astra-accounting-probe-results.json`: fake-clock supervision plus cleanup costs **5 seconds / 5 charged**. Four persisted reservation-before-intent interruptions yield ordinal four/four units after reopen; the fifth is denied without a new unit. This boundary fixture does not claim an actual process crash.
- `/tmp/protview-qa/m4-astra-identity-probe.py` and `m4-astra-identity-probe-results.json`: all process identity/enumeration/clock/signals are mocked. A fresh stranger receives zero signals and cleanup remains false; a previously authenticated survivor receives TERM then KILL and cleanup succeeds. **No OS signals or actual PID/PGID reuse are claimed.** Astra previously reran the unchanged probe independently and inspected final cohort code; parent reran against the final hash at 03:42:37 UTC.
- `/tmp/protview-qa/m4-guardian-control-failure-probe.py` and `m4-control-failure-result.json`: parent's actual OS child with injected STARTED-send BrokenPipe exits through cleanup; guardian exits 5, no surviving members. The latest verified fixture worker was PID16130. Actual host parent-death cases separately cover production EOF paths.

## Resolved findings and final contract

**M4-1: cleanup after spawn.** Guardian cleanup finally encloses post-spawn control sends and monitoring. BrokenPipe/EOF/exception, timeout and cancellation reach bounded cleanup and direct-child reap. Earlier leaked fixture PIDs64611/64612 were ownership-verified and cleaned by parent; the failed historical run remains in `m4-initial-host-test-evidence.json`.

**M4-2: interpreter and environment.** Launch keeps the absolute virtual-environment executable symlink without dereferencing it. Actual guardian and worker tests check executable/prefix/psutil and exclude synthetic key/proxy/PYTHONPATH/loader sentinels. The fixed minimal environment and allowlisted adapter boundary remain intact.

**M4-3: complete active accounting.** One monotonic reserved-attempt interval includes supervision, fallback cleanup, candidate/result validation and terminal or cleanup-pending work. Failure retains the expensive unit. Exhaustion checkpoints follow cleanup; bounded UTC orphan settlement and terminal-before-charge reconciliation avoid duplicate interrupted-attempt charges. Idle clean offline time is free.

**M4-4: durable retry bound.** Unique reservation attempt IDs bound to root/tool, rather than dispatch intents alone, determine the four-attempt allowance. Reservation-before-intent interruption survives reconstruction and cannot reset the ordinal. Approval is persisted and the shared M2 reservation primitive is used.

**M4-5: STOP/control ordering.** A bounded absolute drain tolerates queued STARTED frames and requires a validated matching RESULT with genuine reap evidence. Missing/malformed result or unknown cleanup stays pending; a group-empty observation does not invent a direct-child attestation.

**M4-6: process ownership after anchor loss.** Parent cleanup admits immutable PID/create-time/UID identities only while the original guardian matches both before and after enumeration. Each signal revalidates identity/group. After anchor loss, only known verified cohort survivors may be escalated; new strangers are not authorized by same UID or reused PGID. Parent no longer falls back to killpg. Guardian remains the live group anchor for its own cleanup. Enumeration failures and ambiguous survivors do not become false emptiness.

**M4-7: shared admission.** Under execution ownership, `reserve_attempt` refreshes and checks unresolved dispatches inside the same short transition lock immediately before debit. A different claimed job remains resumable with typed job_cleanup_pending, no attempt/ordinal/debit/Popen/wall charge, and no duplicate blocked event. Existing dispatches block even after events-only reconstruction; late pre-reservation state is rechecked. Once verified cleanup and terminal state close A, B can reserve once. Five regressions additionally cover direct reservation bypass, reopen and cancellation. Ownership is released on failure; cancellation still uses the short lock rather than waiting for long execution.

The event log is authoritative and SQLite is reconstructible. Claim, cancellation, reservation and terminal transitions retain their respective locks; cancellation cannot be overwritten by late success. Private nonce/owner/process identities are excluded from HTTP projections. Fixed session bootstrap uses authenticated HELLO/receipt and explicit GO before adapter launch; launch identity is OS creation identity plus nonce, not PID/time guesses. Input/production dispatch is allowlisted; public requests cannot select arbitrary executable/module/environment or the internal fixture adapter.

## Product integration and limits

Parent browser evidence `/tmp/protview-qa/m4-browser-evidence.json` confirms truthful unavailable protocol fields, local-only mode, reopened historical 1HSG **97 contacts** and actual ASP A/25 Mol* focus, with zero viewer errors, page errors or nonloopback requests. Astra inspected its structured evidence and `m4-legacy-1hsg-focus.png`. This is review of the parent's actual browser session, not a separate invented session.

The checked project interpreter lacks PyRosetta; rosetta_scripts is not found. Relax, Cartesian ddG, interface analyzer and residue energies are individually unimplemented/not scientifically validated. Discovery alone never advertises protocol support. Known production requests return honest unavailable/precondition responses; dry-run is plan-only. Lifecycle fixtures produce job_lifecycle objects, never energies. The process supervisor assumes fixed allowlisted adapters remain in its group; it is not a sandbox for arbitrary hostile executables. D07 explicitly permits this optional-engine-unavailable MVP.

The separate harness review is APPROVED in docs/reviews/HARNESS_REVIEW.md: JSONL agent/tool contents and quoted tools::router error continuations cannot masquerade as hook trust warnings, while genuine diagnostics, failed turns, bad JSON and trust pin mismatches remain rejected. Astra checked both real captures, injected real warning headers, 51 harness tests and trusted preflight. No security bypass was introduced and no extra external-model smoke was made.

M0–M3 shared-source reviews are refreshed separately. M5 report implementation now has its separate final approval in docs/reviews/M5_REPORTS_REVIEW.md. Reference preservation is independently recorded by parent in `/tmp/protview-qa/reference-preservation-final.json`: all 117 archive reference files match and the root v0.5 plan matches the archive's plan.

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

Final hash inventory: `/tmp/protview-qa/m4-final-review-hashes.json`. Historical rejection documents are preserved in `/tmp/protview-qa/before-final-m4-docs_reviews_M4_JOBS_REVIEW.md`, `m4-pre-identity-terminal-review-preserved.md` and `m4-initial-review-preserved.md`; their intermediate failures are not current verdicts. No phase index/status, implementation, credentials or recorded review hash was edited.
