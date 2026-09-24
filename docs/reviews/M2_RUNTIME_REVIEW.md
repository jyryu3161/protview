# M2 backend runtime correction review

Reviewer: GPT-6 Astra. Date: 2026-09-24. Reviewed the terminal GPT-6 Sol backend correction, independently reran the four original probes and relevant M0/M1/M2 regressions. This approval is limited to the backend. The frontend correction and parent live browser proof were subsequently accepted in docs/reviews/M2_FRONTEND_REVIEW.md; the combined verdict is phases/protview-mvp/reviews/step2.md. No phase status or recorded hash was changed by this review.

Verdict: APPROVED

## Independent execution

- `.venv/bin/python -m pytest -q backend/tests/test_core.py backend/tests/test_structural.py backend/tests/test_api.py backend/tests/test_runtime.py`: **56 passed in 2.28s**, one existing Starlette TestClient deprecation warning.
- `.venv/bin/python -m ruff check backend/mw backend/tests`: **passed**.
- `/tmp/protview-qa/m2-corrected-independent-probes.py`: all four original defect boundaries pass, observed 2026-09-24T01:51:13Z. Results and unchanged before/after source hashes are in `/tmp/protview-qa/m2-corrected-independent-probe-results.json`.
- `/tmp/protview-qa/m2-event-lock-probe.py`: a reader blocks during a deliberately paused partial write under the event writer lock, then reads exactly two complete events. Evidence: `/tmp/protview-qa/m2-event-lock-probe-results.json`.

These isolated temporary probes use identified synthetic runtime fixtures, not scientific measurements. The crash probe kills only its own child. The original failing probe/results are retained as `/tmp/protview-qa/m2-independent-probes.py` and `m2-independent-probe-results.json`; the previous detailed findings report is preserved in `/tmp/protview-qa/m2-initial-runtime-review.md`.

The parent independently reports exact Stop Ruff and 97 backend/harness tests passing, and real HTTP evidence in `/tmp/protview-qa/m2-api-cache-fixture.json`: six physical calls, fixture contact counts 6 and 0, then a distinct cache observation returning the earlier exact interaction handle without duration or expensive charge. These are parent-run integration results; this review does not label them reviewer-executed browser proof.

## Resolution of the four blockers

1. **Atomic index publication.** `rebuild_from_events` now encloses deletion and every verified install in one SQLite transaction, using `commit=False` for individual installs and rollback on any failure. Our paused-install probe reads the existing handle successfully through a separate connection. The executed regression additionally opens a separate spawned reader process, and the corrupt-event regression verifies both existing connections retain the previously published index after rollback. Payload verification and true events-only rebuilding remain intact.
2. **Legacy accounting.** Historical success durations are counted only when that call lacks an explicit M2 attempt charge. The independent two-second fixture remains 2.0 seconds on reopen. Executed mixed legacy/new success/failure regressions retain historical usage, ignore legacy cached successes, and remain stable across repeated reopen.
3. **Interrupted backoff.** Backoff start persists its ID, root, failed call, retry ordinal and allowance/deadline. Completion or interruption is terminal; recovery charges only its unaccounted bounded interval. The actual child killed during sleep now produces `ApprovalRequired(gate="budget")`, charges the remaining approximately five seconds once, and has exactly one backoff interruption even after another owner reopens. Clock reversal and clean idle regression cases also pass. Runtime bookkeeping can add small measured overhead beyond the configured ceiling; the ceiling prevents another physical dispatch, rather than capping observed consumption.
4. **Repair source binding.** Original and repaired imports share `_source_input`; `_key` requires the resolved bytes. In the independent A/B path-swap fixture the repaired tool receives A, produces A, and the later A request returns cached A. Verified HTTP bytes and explicit format checks are preserved. This proves byte/key binding, not PDB parser accuracy.

The additional EventLog shared-read lock closes the prior unguaranteed read-snapshot boundary. Append uses `_read_unlocked` while holding its exclusive lock, avoiding recursive shared-lock acquisition. Sequence validation remains fail-closed.

## Preserved runtime and scientific boundaries

Inspection and executed tests retain pre-dispatch validation, normalized version/seed/mode/content-aware keys, verified cache payload/envelope reads, distinct cache observations, finite transient retry and repair/prerequisite chains, durable human approval and per-physical-attempt expense reservations, branch-specific autonomous stopping, and human cache reads without autonomous penalties. Run ownership is enforced across processes; read-only construction does not reconcile a live owner. Cancellation is cooperative, and abandoned work is reconciled under the next execution owner. M2 makes no hard-kill claim for arbitrary in-process Python/C work; subprocess enforcement belongs to M4.

Dry-run expensive work yields typed plans only. Missing real energetic capability is rejected before approval/reservation and is not advertised as an available tool. No synthetic energy value is accepted as a measurement. M0 semantic handles, immutable preparation provenance, residue/model identity, source-independent replay and M1 typed API/geometry regressions all pass in this revision.

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

The source snapshot is recorded in `/tmp/protview-qa/m2-corrected-backend-review-hashes.json`. The parent must attach actual source hashes through the executor after all M2 files are stable. This document remains the backend-specific evidence; phases/protview-mvp/reviews/step2.md contains the combined final verdict.
