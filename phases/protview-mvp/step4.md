# Step 4: M4 — Durable jobs and energy capability boundaries

## Required reading

- AGENTS.md
- docs/ARCHITECTURE.md
- docs/DECISIONS.md
- docs/IMPLEMENTATION_PLAN.md
- docs/RUNTIME_CONTRACT.md
- docs/JOBS_CONTRACT.md
- backend/mw/jobs/queue.py
- backend/mw/jobs/rosetta_worker.py
- backend/mw/tools/energetic.py
- backend/mw/runtime/orchestrator.py

Previous M3 phase must pass its gate before this phase is accepted. Read the current implementation and prior phase summary; do not assume archived scaffold behavior is correct.

## Work (GPT-6 Sol)

Implement durable SQLite-backed local jobs and isolated subprocess supervision with timeout, kill, cancellation and interrupted-job recovery. Budget/approval must precede real expensive execution and failed starts/attempts must charge according to documented policy. Capability status is per protocol, not merely import success. An implemented real PyRosetta protocol records seed, version, score function and REU units. Missing engine or unimplemented protocol is unavailable/precondition with no energy table. Dry-run is a plan, not a simulated measured ΔΔG. Add test_jobs.py; fake workers validate lifecycle only and cannot establish scientific validity.

## Executable acceptance checks

Commands run from repository root with a root .venv and editable backend installation:

```text
.venv/bin/python -m pytest backend/tests/test_jobs.py backend/tests/test_runtime.py -q
.venv/bin/python -m ruff check backend/mw/jobs backend/mw/tools/energetic.py
```

The index stores these commands as argv arrays, not shell scripts. Install dependencies before checking; never replace a failed check with a no-op.

## Required behavioral evidence

Implement the function/data/state boundaries and ten focused evidence groups in docs/JOBS_CONTRACT.md. No process starts without required persisted approval and a shared M2 attempt reservation. Failed launches/attempts consume allowance once; unavailable/invalid/cache/dry-run requests do not. Real subprocess tests must prove timeout/cancel cleanup of the entire owned group, including a SIGTERM-ignoring grandchild after its leader exits, with direct-child reaping. Restart preserves live ownership or verifies orphan cleanup before recording interrupted; ambiguous process identity blocks replacement work. Rebuild job facts from events, serialize claims and reject late terminal races. The production protocol allowlist excludes fixture workers and arbitrary execution. Report engine detection, implementation and scientific validation separately: missing PyRosetta and unimplemented protocols never yield numeric energies. Disclose whether any real licensed protocol was actually tested. M4 may pass with every optional energy protocol explicitly unavailable under D07; fixture lifecycle success is not real energy validation.

## GPT-6 Astra review gate

Astra inspects code and actual evidence, writes phases/protview-mvp/reviews/step4.md with verdict approved or changes_required, and lists reviewed files and limitations. Record the report with scripts/execute.py --record-review and actual reviewed file hashes. Run --verify before completion. Only actual checks plus a current approving review permit completed status. Fix findings without asking the user to approve ordinary implementation.

## Prohibitions

Do not fabricate scientific output, weaken tests to bless incorrect behavior, make unsupported features appear available, bypass local_only, import kinase domain logic, or overwrite user files. Do not declare work completed merely because it compiles.
