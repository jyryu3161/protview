# Step 2: M2 — Bounded resumable runtime

## Required reading

- AGENTS.md
- docs/ARCHITECTURE.md
- docs/DECISIONS.md
- docs/IMPLEMENTATION_PLAN.md
- docs/RUNTIME_CONTRACT.md
- backend/mw/runtime/orchestrator.py
- backend/mw/runtime/guards.py
- backend/mw/core/errors.py
- backend/mw/core/contracts.py
- backend/tests/test_runtime.py

Previous M1 phase must pass its gate before this phase is accepted. Read the current implementation and prior phase summary; do not assume archived scaffold behavior is correct.

## Work (GPT-6 Sol)

Validate tool arguments/kinds before execution. Separate stable content identity from normalized call caching. Implement bounded failure-specific retries, changed-argument repair constraints, repeat/no-progress/oscillation guards, checkpoint/resume and durable consumption state. scientific_null is done. Dry-run expensive tools emit clearly typed plans and cannot fall through to actual execution when a stub is missing. Cached reads remain idempotent while autonomous loops still detect no progress. Charge failed attempts and elapsed retry/backoff time correctly. Implement the concrete failure-chain, execution-mode, budget/reopen and locking semantics in docs/RUNTIME_CONTRACT.md. Keep the existing API compatible where possible; internal repair methods and deterministic drivers suffice, with no new conversational UI or agent framework. Do not start M2 implementation before M1 passes its gate.

## Executable acceptance checks

Commands run from repository root with a root .venv and editable backend installation:

```text
.venv/bin/python -m pytest backend/tests/test_runtime.py -q
.venv/bin/python -m ruff check backend/mw/runtime
npm --prefix frontend run test:events
```

The index stores these commands as argv arrays, not shell scripts. Install dependencies before checking; never replace a failed check with a no-op.

## Required behavioral evidence

Test at least ten distinct invalid/failure cases and meaningful stop bounds: unknown tool, wrong kind, invalid selection, invalid policy, exhausted transient retries, same-argument repair, resource timeout, fatal failure, no-progress loop and scientific-null success. Resume does not silently replenish budget or rerun completed calls. Exercise all fourteen behavioral evidence cases in docs/RUNTIME_CONTRACT.md §7, including exact retry ceilings, one-shot changed-argument/prerequisite recovery, human versus autonomous cache behavior, live-owner exclusion, conservative orphan timing, and plan-only dry-run outputs. The executable frontend test:events gate covers reopened cache observations, original input lineage, independent timeline IDs, legacy cached successes, and rejection of malformed key/order/duplicate-ID references with canonical argument comparison. Replace archive tests that treat synthetic rounds_REU as scientific evidence. M2 owns cooperative dispatch/deadline/cancellation accounting; actual subprocess hard-kill proof belongs to M4.

## GPT-6 Astra review gate

Astra inspects code and actual evidence, writes phases/protview-mvp/reviews/step2.md with verdict approved or changes_required, and lists reviewed files and limitations. Record the report with scripts/execute.py --record-review and actual reviewed file hashes. Run --verify before completion. Only actual checks plus a current approving review permit completed status. Fix findings without asking the user to approve ordinary implementation.

## Prohibitions

Do not fabricate scientific output, weaken tests to bless incorrect behavior, make unsupported features appear available, bypass local_only, import kinase domain logic, or overwrite user files. Do not declare work completed merely because it compiles.

## Existing M1 integration to preserve

Introducing the separate cache_hit event requires adapting the frontend event/timeline normalization and actual input-handle lineage joins. Retain the cached output and original physical source_call_id/normalized input evidence; a cache read updates user inspection intent but is not a new physical success or expensive attempt. Follow RUNTIME_CONTRACT.md section 3 and include a reopened-run cache-read UI regression. Do not keep emitting fake physical tool_succeeded events solely for frontend compatibility.
