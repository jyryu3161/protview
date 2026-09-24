# Step0 / M6 — final Astra review

Reviewer: GPT-6 Astra. Implementation: GPT-6 Sol. Date: 2026-09-24. Final correction session99489 terminal; branch `phase/m6-interface-sasa`.

Verdict: APPROVED

The selected real FreeSASA Lee–Richards100/probe1.4Å/thread1 protocol, full scientific identity/selection mapping, native preflight, immutable result/claim/report evidence and actual current/historical viewer flow meet step0. Detailed scope, former finding and evidence attribution: `docs/M6_SASA_REVIEW.md`.

The sole discovered blocker is resolved: saved method reports now reject wrong result kind, metadata schema and payload schema even with consistently paired report/event links. The unchanged independent probe rejects both original fixtures and preserves exact events-only replay with zero appended events and no engine calls. Astra corrected SASA tests:11 passed. Parent terminal host backend+harness:251 passed,0 skipped,21.01s, full Ruff PASS; targeted acceptance58 passed, frontend11 tests/typecheck/build passed. Parent will rerun the actual acceptance argv when recording this approval; this document does not prefill the index or claim that recording already ran.

Actual1HSG:1514 protein/45 ligand heavy atoms,198 complete residue identities. Eight summaries match the independent direct-engine reference within4.55e-11Å² and every residue field within1.24e-11Å². Protein burial546.4015616674023Å², ligand burial782.7580589969108Å², total1329.1596206643135Å². Scientific quantities are area, not energy/affinity. The rejected pre-implementation SR configuration is not used or corrected numerically.

Actual-browser proof covers native calculation, exact-input ASP A25 focus,1559-atom/198-row JSON and complete Markdown preview/downloads,53→53-event reopen, unchanged old M5 artifact, backend restart, historical A/B115.48055/0 reports, delayed B200 response rejected after A selection, and503 error/no-preview/retry. Zero external requests/page errors. Astra inspected the browser evidence and screenshot. Synthetic lifecycle fixtures are labeled.

Evidence: `/tmp/protview-qa/m6-final-host-evidence.json`, `/tmp/protview-qa/m6-final-browser-evidence.json`, `/tmp/protview-qa/m6-astra-scientific-probe-results.json`, `/tmp/protview-qa/m6-independent-lr-reference.json`. Final source hash inventory: `/tmp/protview-qa/m6-final-reviewed-hashes.json`.

This M6 review explicitly supersedes shared-source review coverage for the extension relative to accepted baseline `d22fe15`. Original MVP review records remain historical; this is not a claim of fresh current-branch `protview-mvp --verify`. Unchanged core/jobs/old reports/workflows/LLM/harness/hooks were checked for baseline continuity; changed runtime/API/workspace/config/UI paths and existing behavior are covered by source review, full regressions and old/new browser evidence. M7 remains pending. Parent owns actual recording and commits.

## Exact reviewed files

- AGENTS.md
- README.md
- backend/mw/tools/sasa.py
- backend/mw/method_reports.py
- backend/mw/api/app.py
- backend/mw/runtime/orchestrator.py
- backend/mw/workspace.py
- backend/pyproject.toml
- backend/tests/test_sasa.py
- backend/tests/test_api.py
- config/tools.yaml
- frontend/app/page.tsx
- frontend/src/lib/api.ts
- frontend/src/lib/event-model.ts
- frontend/src/lib/report-selection.ts
- frontend/src/lib/area-format.ts
- frontend/tests/event-model.test.cjs
- frontend/tests/report-selection.test.cjs
- frontend/tests/area-format.test.cjs
- docs/ALTERNATIVE_METHODS_CONTRACT.md
- docs/ARCHITECTURE.md
- docs/DECISIONS.md
- docs/IMPLEMENTATION_PLAN.md
- docs/M6_SASA.md
- backend/mw/core/residue.py
- backend/mw/tools/structural.py
- backend/mw/reports.py
- frontend/src/components/MolstarViewer.tsx
- frontend/package.json
- docs/M6_SASA_REVIEW.md
