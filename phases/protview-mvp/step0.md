# Step 0: M0 — Objects, imports and preparation

## Required reading

- AGENTS.md
- docs/ARCHITECTURE.md
- docs/DECISIONS.md
- docs/IMPLEMENTATION_PLAN.md
- backend/mw/core/handles.py
- backend/mw/core/events.py
- backend/mw/core/residue.py
- backend/mw/tools/structural.py

Read agent_protein_viewer_plan_v05.md and selected molecular-workspace.zip sources before importing.

## Work (GPT-6 Sol)

Import useful archive scaffold without overwriting authoritative root documents. Implement immutable full-SHA256 objects and durable object events that contain recoverable payloads. Rebuild objects and indices from events alone without original source files. Implement PDB/mmCIF import, model selection, supported deterministic preparation and an accurate manifest. Preserve auth/label identifiers and insertion codes. Highest-occupancy altloc selection must really select occupancy and have a deterministic tie-break. Reject unsupported protonation/reconstruction/symmetry policies. Add test_structural.py with hand-checkable geometry and identity fixtures. Do not promote simple N/O proximity to chemically validated hydrogen bonds.

## Executable acceptance checks

Commands run from repository root with a root .venv and editable backend installation:

```text
.venv/bin/python -m pytest backend/tests/test_core.py backend/tests/test_structural.py -q
.venv/bin/python -m ruff check backend/mw/core backend/mw/tools
```

The index stores these commands as argv arrays, not shell scripts. Install dependencies before checking; never replace a failed check with a no-op.

## Required behavioral evidence

Duplicate imports have stable content hashes; events-only replay restores original bytes and handles after source/objects/indices deletion; non-first altloc, insertion code, model index and distinct mmCIF auth/label cases are tested.

## GPT-6 Astra review gate

Astra inspects code and actual evidence, writes phases/protview-mvp/reviews/step0.md with verdict approved or changes_required, and lists reviewed files and limitations. Record the report with scripts/execute.py --record-review and actual reviewed file hashes. Run --verify before completion. Only actual checks plus a current approving review permit completed status. Fix findings without asking the user to approve ordinary implementation.

## Prohibitions

Do not fabricate scientific output, weaken tests to bless incorrect behavior, make unsupported features appear available, bypass local_only, import kinase domain logic, or overwrite user files. Do not declare work completed merely because it compiles.
