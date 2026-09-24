# Step 3: M3 — Local-only egress and provenance

## Required reading

- AGENTS.md
- docs/ARCHITECTURE.md
- docs/DECISIONS.md
- docs/IMPLEMENTATION_PLAN.md
- docs/RUNTIME_CONTRACT.md
- docs/EGRESS_CONTRACT.md
- backend/mw/egress/gate.py
- backend/mw/llm/openrouter.py
- backend/mw/llm/prompts.py
- backend/mw/tools/structural.py
- backend/tests/test_llm_egress.py

Previous M2 phase must pass its gate before this phase is accepted. Read the current implementation and prior phase summary; do not assume archived scaffold behavior is correct.

## Work (GPT-6 Sol)

Make local_only the offline-complete default. Build outbound compact state with allowlisted fields and a bounded preview. Gate all optional HTTP before transport. No coordinate bytes, complete sequence, path, filename, credentials or unfiltered goal text in outbound data. Log sanitized allowed payloads and accurately distinguish attempts from sends. Optional model integration is configured explicitly and fixture-tested; absent key/pin or denied mode uses a labeled rule fallback. Frontend fonts/scripts/samples must be local. Do not hard-code a fictional model pin. Routine tests use fixtures. The user explicitly authorized a separate minimal live OpenRouter connectivity smoke: the parent agent performs it with a configured pin and synthetic compact state via the gate, using the ignored root .env credential (0600). Never expose its value or include real structure data. Jev uses its decisions endpoint rather than chat completions; record requested alias and served snapshot and validate an explicit approved alias-to-snapshot mapping. A completed live check is required before describing the adapter as live-validated. Implement the selected inspection-view choice contract in docs/EGRESS_CONTRACT.md: fixed numeric aggregate projection, static choice question, one transport owner, approved alias/snapshot mapping, safe errors and durable delivery-unknown audit state. No arbitrary messages/state/questions endpoint is needed. The local rule path remains complete and source-labeled.

## Executable acceptance checks

Commands run from repository root with a root .venv and editable backend installation:

```text
.venv/bin/python -m pytest backend/tests/test_llm_egress.py -q
.venv/bin/python -m ruff check backend/mw/egress backend/mw/llm
```

The index stores these commands as argv arrays, not shell scripts. Install dependencies before checking; never replace a failed check with a no-op.

## Required behavioral evidence

Spy transport sees zero calls in local_only/dry_run and for denied content. Test coordinate/sequence/path leakage under non-obvious keys and nested data, credentials exclusion, every decision source label and the full keyless local pipeline. Browser network evidence contains no third-party resource requests in local_only. Separately record the authorized live smoke result and served model; connectivity success is not evidence of scientific quality. Cover the ten bounded evidence groups in docs/EGRESS_CONTRACT.md §8, including credential-resolver non-use locally, metadata/name/goal injection, rejected raw-body exclusion from audits, redirect denial, persistence-before-send and ambiguous timeout/usage. Use fixtures for ordinary checks; the parent performs the single authorized live smoke after the gate is implemented.

## GPT-6 Astra review gate

Astra inspects code and actual evidence, writes phases/protview-mvp/reviews/step3.md with verdict approved or changes_required, and lists reviewed files and limitations. Record the report with scripts/execute.py --record-review and actual reviewed file hashes. Run --verify before completion. Only actual checks plus a current approving review permit completed status. Fix findings without asking the user to approve ordinary implementation.

## Prohibitions

Do not fabricate scientific output, weaken tests to bless incorrect behavior, make unsupported features appear available, bypass local_only, import kinase domain logic, or overwrite user files. Do not declare work completed merely because it compiles.
