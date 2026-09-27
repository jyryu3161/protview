# Step0 / M9 — saved scenes and local figure export

GPT-6 Astra design/review, GPT-6 Sol implementation. Baseline `6894ab4`; actual branch `phase/m9-scenes-export`. Initial status pending; no acceptance/review evidence is prefilled. User authorized implementation while testing; M10–M13 remain subsequent work.

## Prerequisites and scope

Read AGENTS.md, docs/ARCHITECTURE.md, docs/DECISIONS.md, docs/IMPLEMENTATION_PLAN.md, docs/POST_M8_PLAN.md, docs/M9_SCENES_EXPORT_CONTRACT.md, docs/M8_AGENT_VIEWER_CONTRACT.md, docs/M8_OFFSCREEN_QA_PLAN.md, docs/M8_AGENT_VIEWER_REVIEW.md and phases/protview-integration/reviews/step0.md. Preserve completed historical phase records and scientific reports.

Implement the complete M9 contract: named immutable scenes with exact source/model/full residue identity, full bounded camera/representation/theme, explicit guarded restore into fresh sessions, actual Mol* PNG capture and durable PNG/JSON provenance, events-only replay, strict local API, caps/idempotency and truthful errors. Original, historical/prepared and validated minimized sources are all required. Do not implement only current-scene screenshots or React-state-only restore. No provider/scientific rerun on reopen/restore/export. No new model calls.

Sol creates the pending phase index and implements app/API/bridge/storage/tests plus a real Electron offscreen scene suite. Update usable documentation and publish actual capability/error behavior, then record dated QA results with original failures and corrections. The inherited M8/gallery scope remains distinguishable from new working behavior.

## Exact acceptance command argv

```json
[
  [".venv/bin/python", "-m", "pytest", "backend/tests/test_saved_scenes.py", "backend/tests/test_agent_viewer.py", "backend/tests/test_core.py", "-q"],
  [".venv/bin/python", "-m", "pytest", "backend/tests", "-q"],
  [".venv/bin/python", "-m", "ruff", "check", "backend/mw", "backend/tests", "scripts", ".codex/hooks"],
  [".venv/bin/python", "-m", "pytest", "scripts/test_execute.py", "scripts/test_codex_hooks.py", "-q"],
  ["npm", "--prefix", "frontend", "run", "test:events"],
  ["npm", "--prefix", "frontend", "run", "typecheck"],
  ["npm", "--prefix", "frontend", "run", "build"],
  ["node", "--check", "frontend/tests/offscreen/scenes-flow.cjs"]
]
```

Index stores these arrays exactly. Frontend meaningful scene tests use existing test:events glob. Do not add a fake passing browser check: actual scenes-flow execution requires owned loopback services and production build, so its exact command/environment/input/source evidence is a mandatory review artifact separately.

## Gate evidence beyond command success

1. Full scene/backend invariants and adversarial cases from the contract, including source hash validation and scene/figure/events-only recovery with no original paths, renderer/scientific recomputation or model calls. Existing report bytes survive unchanged.
2. Actual Electron offscreen inventory individually exercises every new scene/export control, including disabled/error/retry states and download completion. Record real isOffscreen/nonvisible/GPU/WebGL/paint, exact versions/source/build, and all results. Original/prepared-history/real OpenMM-minimized source restore after reopen is mandatory.
3. Native readback verifies full camera including roll/up and source-bound selection after settled rendering, not just React updates; late/manual/source-switch and same-source restore guards are observed. Exported PNG decoded dimensions/nonblank molecular content and JSON stored-byte/hash/source matching are independently checked. Reviewer directly views representative restored scenes and actual exported images.
4. Fresh normal37 report/download regression and actual OpenMM source/view workflow on changed page/bridge; backend/full frontend checks preserve M8 intent/egress/job boundaries. Fixture provider responses remain labeled; no live call. Historical86-case ledger is not falsely represented as wholly rerun.
5. Astra resolves blockers and writes a current review with exact changed shared-source and artifact inventory, explicitly superseding relevant prior coverage without modifying prior reports/reviews. Parent records SHA-bound review, actual acceptance and `--verify`, then commits/merges only after the gate passes. No automatic phase completion on successful unit tests alone.

## Limits

Scene/PNG artifacts are reproducible local viewing records, not new scientific claims. Stored bytes replay exactly; future rerendered image pixels are not guaranteed identical across platforms. Labels never become paths or egress content. Missing/corrupt/cross-run/unsupported scenes fail visibly; fallback to current structure is never implicit. M9 does not claim completed measurement/alignment/chemistry/pocket/workflow phases.
