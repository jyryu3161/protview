# Step0 / M6 — Real protein–ligand interface SASA

Design/review: GPT-6 Astra. Implementation: GPT-6 Sol. Work branch: phase/m6-interface-sasa, created after honest M0–M5 baseline d22fe15. No retrospective phase branches are claimed.

## Read first

AGENTS.md; docs/ALTERNATIVE_METHODS_CONTRACT.md sections1–3,6–7; docs/RUNTIME_CONTRACT.md; docs/REPORT_CONTRACT.md; backend/mw/tools/structural.py; backend/mw/core/residue.py; backend/mw/reports.py; backend/mw/api/app.py; frontend/app/page.tsx. Preserve all existing MVP specs and immutable saved report bytes.

## Implement

Pin/install the verified FreeSASA2.2.1 project dependency and implement the real compute_interface_sasa tool through Run.call. Follow explicit selected protein/ligand heavy-atom sets, excluded-component manifest, Gemmi radius/version policy, fixed Lee–Richards100slices/probe1.4Å/thread1 (`freesasa_lee_richards_v1`), atom cap and identity mapping. Record all three actual SASA calculations, partner and total loss formulas, complete per-atom/per-residue evidence, units/method/versions and semantic cache identity. No guessed radii, merged same-name ligands or hidden exclusions.

Wire strict public API/registry/capability metadata, exact historic/current input selection, actionable local SASA controls, real table/residue focus and method_report_manifest@1 Markdown/JSON preview/download/reopen. Preserve report_manifest@1 reads. Scientific zero burial, absent/unsupported input, native calculation failure and fetch failure remain separate. The Sol-owned new index has step0 pending and the exact acceptance argv below; no prefilled success/review.

## Acceptance commands

Run at project root with the actual installed dependency; no skipped engine substitute:

```text
.venv/bin/python -m pytest backend/tests/test_sasa.py backend/tests/test_reports.py backend/tests/test_api.py backend/tests/test_runtime.py -q
.venv/bin/python -m ruff check backend/mw backend/tests
npm --prefix frontend run test:events
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

## Required evidence

Actual analytic isolated/separated spheres within1e-6Å² absolute error and overlapping equal spheres within0.5% relative error plus1e-6Å² roundoff; identity/unknown-element/ligand/nonfinite/size/coincident-coordinate rejection before any native call; partner and per-residue sum consistency; cache/dependency identity and dry-run honesty; full method report field/subject/unit/rounding checks; original source/objects/index deletion and exact events-only report/result recovery with FreeSASA calls forbidden. Test stale selection/read failure and previous report bytes. Parent/reviewer directly cross-check real1HSG with production settings, then exercise the actual browser calculation, residue focus, area values, report downloads and reopened/history result with zero external requests. Parent's960-point SR feasibility number is not a Lee–Richards product expectation. The rejected SR1000 single/separated-sphere measurements and passing LR100 evidence are documented in the contract and `/tmp/protview-qa/m6-astra-engine-analytic-probe.json`. Do not correct native outputs with a numeric patch or isolated-atom special case. Cache/result/report metadata must identify LeeRichards and100slices.

Write docs/M6_SASA.md with measured checks, exact version/platform/source hashes, method limitations and adopted capability scope. Astra writes reviews/step0.md with exact inspected files and real evidence. Parent records actual checks/review, refreshes or explicitly supersedes stale shared MVP review coverage, then makes the actual M6 commit. No M7 implementation starts before this gate. No licensed energy, affinity claim or external-model call is required.
