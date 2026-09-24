# Step 1: M1 — Real viewer and structural API

## Required reading

- AGENTS.md
- docs/ARCHITECTURE.md
- docs/DECISIONS.md
- docs/IMPLEMENTATION_PLAN.md
- backend/mw/api/app.py
- backend/mw/workspace.py
- frontend/app/page.tsx
- frontend/src/components/MolstarViewer.tsx
- frontend/src/lib/api.ts

Previous M0 phase must pass its gate before this phase is accepted. Read the current implementation and prior phase summary; do not assume archived scaffold behavior is correct.

## Work (GPT-6 Sol)

Wire validated local upload, run creation, tool commands, handle metadata/materialization and structure-byte endpoints. Reject path traversal and invalid/foreign run handles. Replace runtime mock values and SVG placeholder with actual locally bundled Mol* and backend results. Make real structure loading, representation controls, residue/interaction focus and result tables work. Use auth/label/icode identity rather than array position as identity. Show empty result and missing capability without fake numbers. Runtime operations must use one call path and record human/rule provenance. Interaction identity must include input structure/selection/method parameters and rows (including empty rows), so different cutoffs or preparation policies cannot alias one table with conflicting summaries. Materialization must preserve row projection through any semantic envelope. Add regressions for identical contact rows under different cutoffs and empty results from distinct inputs.

## Executable acceptance checks

Commands run from repository root with a root .venv and editable backend installation:

```text
.venv/bin/python -m pytest backend/tests/test_api.py backend/tests/test_structural.py -q
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

The index stores these commands as argv arrays, not shell scripts. Install dependencies before checking; never replace a failed check with a no-op.

## Required behavioral evidence

Browser evidence must show a real locally uploaded structure rendered in Mol*, a changed representation and selected measured interaction. API contact distances/counts change correctly when fixture coordinates change. Capture loading/error/empty behavior where practical.

## GPT-6 Astra review gate

Astra inspects code and actual evidence, writes phases/protview-mvp/reviews/step1.md with verdict approved or changes_required, and lists reviewed files and limitations. Record the report with scripts/execute.py --record-review and actual reviewed file hashes. Run --verify before completion. Only actual checks plus a current approving review permit completed status. Fix findings without asking the user to approve ordinary implementation.

## Prohibitions

Do not fabricate scientific output, weaken tests to bless incorrect behavior, make unsupported features appear available, bypass local_only, import kinase domain logic, or overwrite user files. Do not declare work completed merely because it compiles.
