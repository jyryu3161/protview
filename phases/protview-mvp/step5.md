# Step 5: M5 — Evidence reports and integrated release

## Required reading

- AGENTS.md
- docs/ARCHITECTURE.md
- docs/DECISIONS.md
- docs/IMPLEMENTATION_PLAN.md
- docs/REPORT_CONTRACT.md
- docs/RUNTIME_CONTRACT.md
- docs/EGRESS_CONTRACT.md
- docs/JOBS_CONTRACT.md
- backend/mw/workspace.py
- backend/mw/llm/verifier.py
- backend/mw/api/app.py
- frontend/app/page.tsx
- README.md

Previous M4 phase must pass its gate before this phase is accepted. Read the current implementation and prior phase summary; do not assume archived scaffold behavior is correct.

## Work (GPT-6 Sol)

Complete the offline inspect_complex workflow, saved run reopening and useful report generation from actual objects. Bind every numeric claim to a specific handle/field/row/unit and validate it against that location, not a global number pool. Expose report access and actual capability/provenance information in the UI. Write reproducible install/start/test instructions. Document adopted and deferred reference capabilities accurately. Integrate harness changes and ensure external-source scientific domain code/data did not enter the project.

## Executable acceptance checks

Commands run from repository root with a root .venv and editable backend installation:

```text
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m ruff check backend/mw backend/tests
.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py -q
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

The index stores these commands as argv arrays, not shell scripts. Install dependencies before checking; never replace a failed check with a no-op.

## Required behavioral evidence

Implement the selected workflow/report schema and ten bounded evidence groups in docs/REPORT_CONTRACT.md. Final browser path: upload -> explicit model/preparation -> ligand/cutoff -> geometric contacts -> correct residue focus -> selected-result report preview and Markdown/JSON download -> reopen the saved report. inspect_complex must use Run.call and actual local handles, preserve ambiguous-ligand and empty/error distinctions, and reject the archive's unsupported bridging-water policy. Validate exact handle/row/field/subject/unit/format bindings and derived aggregates; wrong-field/wrong-unit claims and unsupported number-free scientific explanations are rejected. Saved report bytes and source evidence recover from events without original uploads or recomputation. Historical report selection cannot mix structures. Full selected-scope audit checks offline operation, real displayed numbers, source preservation and precise optional capability limitations; no unavailable energy/ranking result is required or invented.

## GPT-6 Astra review gate

Astra inspects code and actual evidence, writes phases/protview-mvp/reviews/step5.md with verdict approved or changes_required, and lists reviewed files and limitations. Record the report with scripts/execute.py --record-review and actual reviewed file hashes. Run --verify before completion. Only actual checks plus a current approving review permit completed status. Fix findings without asking the user to approve ordinary implementation.

## Prohibitions

Do not fabricate scientific output, weaken tests to bless incorrect behavior, make unsupported features appear available, bypass local_only, import kinase domain logic, or overwrite user files. Do not declare work completed merely because it compiles.
