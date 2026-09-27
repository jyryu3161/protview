# Step0 / M10 — atom distance and explicit rigid comparison

Design/review GPT-6 Astra; implementation GPT-6 Sol. **Pending.** Start only after actual M9 acceptance and parent-created branch from its real commit; record actual baseline then. User authorized subsequent roadmap implementation, but no success or completed feature is asserted here.

## Read and prerequisites

Read AGENTS.md, docs/ARCHITECTURE.md, docs/DECISIONS.md, docs/IMPLEMENTATION_PLAN.md, docs/POST_M8_PLAN.md, docs/M9_SCENES_EXPORT_CONTRACT.md, accepted M9 review/source interfaces, docs/M10_MEASUREMENT_ALIGNMENT_CONTRACT.md, and M8 viewer/egress/runtime contracts. Preserve all old scientific objects/reports/reviews.

## Implement

Full source-bound AtomRef/catalog/native picking; actual two-click Euclidean distance; explicit3–1000 protein CA pair editor; bounded Run.call Kabsch proper-rotation fitting with degeneracy validation; immutable result handles; actual two-layer aligned/unaligned Mol* display and exact picking; evidence-bound reports/downloads; events-only replay. Keep source coordinates unchanged. Disable incompatible one-source scene/agent controls honestly in comparison and retain return-to-single-source. Implement all contract errors/races and frontend synchronization; do not settle for a backend matrix without usable actual overlay controls.

Declare/test the numerical dependency explicitly. Sol owns the pending index, application/scientific code and new offscreen `comparison-flow.cjs`; Astra reviews numerical/scientific correctness. Parent owns actual phase Git transitions and evidence recording. No provider calls or remote structures.

## Exact acceptance command argv

```json
[
  [".venv/bin/python", "-m", "pytest", "backend/tests/test_comparison.py", "backend/tests/test_saved_scenes.py", "backend/tests/test_structural.py", "backend/tests/test_core.py", "-q"],
  [".venv/bin/python", "-m", "pytest", "backend/tests", "-q"],
  [".venv/bin/python", "-m", "ruff", "check", "backend/mw", "backend/tests", "scripts", ".codex/hooks"],
  [".venv/bin/python", "-m", "pytest", "scripts/test_execute.py", "scripts/test_codex_hooks.py", "-q"],
  ["npm", "--prefix", "frontend", "run", "test:events"],
  ["npm", "--prefix", "frontend", "run", "typecheck"],
  ["npm", "--prefix", "frontend", "run", "build"],
  ["node", "--check", "frontend/tests/offscreen/comparison-flow.cjs"]
]
```

The pending index stores these exact arrays, without fabricated check/review fields. Actual offscreen flow requires owned loopback services/fixtures; record executable command/environment/build/source and complete per-control outcomes separately, never substitute a fake passing browser command.

## Gate requirements

1. Independent numerical/mapping evidence for distance, proper rotation, reflection handling, degeneracy thresholds, pair-order invariance and authoritative atom identities. Real source bytes determine outputs; every unsupported/ambiguous selection fails explicitly.
2. Actual nonvisible Electron offscreen WebGL/paint evidence for two-click selection and genuine transformed overlay, source-layer picks, all pair/layer/mode controls and listed error/race cases. Native coordinates/transform observations agree with result and source hashes remain unchanged. Direct Astra inspection of representative overlays/picks and report downloads.
3. Events-only replay after original inputs/storage removal restores handles/reports/source and comparison without fitting, scientific worker or model. Old reports remain byte-identical. New reports pass exact field/unit evidence checks, with honest RMSD limitations.
4. Full commands above plus fresh M9 scenes/export and M8 normal report/download regressions for changed shared files. Record actual case scope and fixture provenance; do not claim historical full-inventory reruns that did not occur.
5. Current Astra approval tied to exact reviewed hashes and explicit shared-source supersession, then parent record-review/actual --verify/commit. No phase completes on test counts alone. M11–M13 remain subsequent authorized increments.
