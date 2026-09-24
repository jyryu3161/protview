# M1 frontend integration review

Reviewer: GPT-6 Astra. Date: 2026-09-24. Implementation: GPT-6 Sol, including the terminal generalized-lineage correction at `/tmp/protview-qa/m1-lineage-result.md`.

Verdict: APPROVED

Approval covers the selected M1 local viewer/API integration. It does not approve unimplemented M2–M5 runtime, online, job or reporting features. All frontend findings raised during this review are resolved within that scope.

## Current behavior and resolved findings

The production route consumes actual API handles and locally bundled Mol* 5.11.0. It has no mock scientific result import or SVG structure placeholder. The separately labeled gallery remains design fixtures. Fonts and viewer assets are local; the component uses raw structure data with an allowlist of local behaviors and disables remote volume/state services.

1. Failed contact materialization is a distinct error with manual retry; it cannot display a successful scientific_null. The returned handle/kind/count/null flag is checked. A successful zero-row result remains a neutral measured empty result.
2. Selected metadata and paginated rows share the same effective interaction handle, keyed by run/result/page. Non-interaction results have no borrowed table. Stale request responses are ignored.
3. Every effective interaction, whether default/latest result or an explicit historical selection, resolves its actual immutable prepared input from validated result metadata. The exact input handle/kind is checked before fetching local bytes/residue identities. Viewer readiness is tied to run, input, view intent, inspection revision and source instance. Row focus is disabled before readiness or after a load failure. A selection legend requires a successful actual residue lookup, including model/auth/label/insertion identity.
4. Latest pipeline lineage follows actual original call inputs: newest load, its compatible preparation and that preparation's compatible interaction. Event order alone does not connect unrelated structures. Missing lineage leaves the successor absent. Result inspection is separate from pipeline mutation: a foreign/historical input disables mutation with a visible explanation. Return-to-latest explicitly selects the compatible pipeline result or its structure without a foreign table.
5. Metadata wraps within the Inspector; contact rows have a labeled keyboard-focusable horizontal scroll region. Parent measured 360 px client width, 420 px scroll width and reachable distance/Å values. Run transitions disable workflow mutation while reopen is pending.
6. PostCSS/sharp dependency overrides are recorded in package and lockfile. Parent's live audit reports zero vulnerabilities across 271 dependencies, and a native sharp PNG conversion succeeded (93 bytes). The worker's earlier offline/failed-network audit is not used as a clean live-audit claim.

## Independent verification

Astra ran on final source:

- `npm --prefix frontend run typecheck`: passed.
- `.venv/bin/python -m pytest backend/tests/test_core.py backend/tests/test_api.py backend/tests/test_structural.py -q`: 29 passed in 0.83 s; one upstream Starlette TestClient deprecation warning.
- `.venv/bin/python -m ruff check backend/mw/api backend/mw/core backend/mw/tools backend/tests/test_api.py`: passed.
- Recomputed every source hash in the recorded M0 review: no mismatches. The previously approved backend and M0 shared-source contracts remain unchanged.

The terminal Sol report records successful sequential frontend typecheck and production build. The parent ran the built artifact in Chrome 153.0.8010.53 with SwiftShader at 1536×960, recording/blocking nonloopback requests. Astra reviewed the browser JSON and selected screenshots rather than independently driving another browser session.

## Browser and scientific evidence

Primary final evidence: `/tmp/protview-qa/m1-lineage-browser-evidence.json`. Earlier empty/error/identity baseline: `/tmp/protview-qa/m1-browser-evidence.json`, supplemented by the parent's corrected-build checks and screenshots. Real HTTP geometric reference: `/tmp/protview-qa/m1-api-evidence.json`.

- Public 1HSG mmCIF source SHA-256: `d2ba73b5c4be05c45275571bbb4dd042347927f91c6c05038c0df5d1ce23c268`. Parent uploaded, loaded and prepared it, selected MK1 B902 (label C), and measured 97 atom-pair contacts across 26 residues at cutoff 4.0 Å. Cutoff 4.5 gives 226/30; minimum is 2.6264474104767457 Å. Parent independently matched these with direct gemmi/math.dist calculation. These are geometric measurements, not affinity or hydrogen-bond validation.
- Actual 1HSG cartoon, ball-and-stick and completed molecular-surface renderings, measured ASP A25 focus, and a valid cutoff-2.5 empty result/reopen were observed. Astra inspected final focus and completed-surface screenshots; the latter is the completed render, not the earlier transition frame.
- Synthetic identity fixture: model 5/auth X100A/label L97, one contact at 2 Å, correct actual lime ALA focus. A second model-1 input has six contacts. A third input uses the same model/residue identifiers but different coordinates and no contacts. Historical/default views request the exact appropriate immutable input, not whichever structure has matching identifiers.
- A new default result computed on the older six-contact input displays/focuses that input and disables latest-pipeline mutations. Return-to-latest displays the distinct zero-contact latest input and enables only its controls.
- Delaying old structure bytes by 1200 ms then switching to another result does not overwrite the newer six-row/model-1 display. No false selected-residue legend survives the switch.
- Injected structure-byte HTTP 503 disables row keyboard action, leaves no success legend and does not create scientific_null; explicit structure retry recovers. Earlier injected row HTTP 503 shows an error with zero false-empty messages; retry restores actual rows. Malformed PDB upload gives the expected structured 422.
- In load A -> load B -> prepare A, default inspection honestly shows A with mutation disabled. Return-to-latest shows raw B without an unrelated preparation/table/contact control; clicking prepare submits B's actual loaded handle.
- Final parent capture reports no external requests or page errors. Earlier console errors correspond to deliberate HTTP 503/422 fault injection, not unexplained application crashes.

Astra visually inspected `m1-default-older-result-fixed.png`, `m1-missing-pipeline-preparation.png`, `m1-final-1hsg-focus.png`, `m1-final-1hsg-surface.png`, and earlier `m1-cross-structure-fixed.png` / `m1-same-identifiers-correct-input.png`. Additional parent artifacts include `m1-return-latest-pipeline.png`, `m1-structure-retry.png`, `m1-row-fetch-error-fixed.png`, `m1-table-scroll-fixed.png` and `m1-history-fixed.png`, all under `/tmp/protview-qa/`.

## Reviewed frontend files

- frontend/app/page.tsx
- frontend/app/layout.tsx
- frontend/app/globals.css
- frontend/app/gallery/page.tsx
- frontend/src/components/MolstarViewer.tsx
- frontend/src/components/data.tsx
- frontend/src/components/primitives.tsx
- frontend/src/components/shell.tsx
- frontend/src/components/run.tsx
- frontend/src/lib/api.ts
- frontend/src/lib/contracts.ts
- frontend/src/design/components.css
- frontend/package.json
- frontend/package-lock.json
- frontend/next.config.mjs
- frontend/tsconfig.json
- docs/M1_API.md
- docs/M1_VIEWER.md

## Boundaries carried forward

The evidence establishes selected local geometric viewing and input association, not chemical interaction classification or energy validation. Optional methods remain accurately unavailable. Hard runtime recovery, egress adapters, isolated jobs and evidence reports retain their own later phase gates. M2's separate cache_hit event must update frontend event normalization and preserve original call-input lineage as documented in RUNTIME_CONTRACT.md; the current M1 event shape must not force fabricated physical successes in M2.
