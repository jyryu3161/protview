# Step0 — integration closure and stable report capture

Design/review: GPT-6 Astra. Implementation: GPT-6 Sol. Parent owns acceptance recording and Git transitions. Designed 2026-09-27 against accepted application source at `ef6f2c7`. **Pending: no completed check, review or renderer outcome is asserted by this specification.**

## Prerequisites

Read AGENTS.md, docs/ARCHITECTURE.md, docs/DECISIONS.md, docs/IMPLEMENTATION_PLAN.md, docs/M8_AGENT_VIEWER_CONTRACT.md, docs/M8_OFFSCREEN_QA_PLAN.md, docs/M8_AGENT_VIEWER_REVIEW.md, docs/M8_QA_RESULTS.md and frontend/tests/offscreen/README.md. Preserve accepted M8 reports, archive, index and their historical hashes.

The parent has a fresh full M8 `--verify` execution against unchanged application source. Its actual log, command, exit status and source identity must be retained as prerequisite evidence, not inferred from this statement. Fresh integration results must distinguish inherited historical coverage from cases actually rerun.

## Selected repair and scope

Fix only the report capture timing in `frontend/tests/offscreen/normal-flow.cjs`. R03 can observe a first report preview, then capture the subsequent loading interval caused by report-list refresh. The initial assertion and later successful downloads do not prove the captured frame contains the saved report. This is a harness observation race; do not alter product report behavior solely to hide it.

Before capturing report evidence, require the intended saved report preview to be ready and nonempty at the capture boundary, using bounded condition-based waits and source/report identity where available. Validate the captured observation, and fail honestly if it represents loading or a different report. Apply the same narrow capture discipline to other report snapshots in this harness when they share the race. Do not add arbitrary long sleeps, suppress failures, replace screenshots with synthetic output, or convert an initial transient observation into successful final evidence.

Add a dated integration closure report and preserved evidence archive, and include the proposed/pending `docs/POST_M8_PLAN.md`. The closure must disclose original R03 timing evidence and corrected rerun separately. No new product capability, scientific method, provider request, historical phase reconstruction or unlimited implementation expansion is selected.

## Executable acceptance checks

Sol creates the new `phases/protview-integration/index.json` with pending status and these exact command argv arrays; no verification or approval is prefilled:

```json
[
  ["node", "--check", "frontend/tests/offscreen/normal-flow.cjs"],
  ["npm", "--prefix", "frontend", "run", "test:events"],
  [".venv/bin/python", "-m", "pytest", "scripts/test_execute.py", "scripts/test_codex_hooks.py", "-q"]
]
```

These automated checks do not substitute for the mandatory actual renderer evidence below. Do not place a fake always-passing browser command into the index. The normal-flow command needs owned running services, fixtures and an actual Electron host; record the exact invocation and environment in the closure report.

## Mandatory acceptance evidence

1. Preserve the actual current full M8 `--verify` log and bind it to the application source hashes/build used. Demonstrate that product/backend/frontend application files and dependency locks are unchanged by this extension. If they change, expand tests and Astra review explicitly before approval.
2. Run the corrected complete normal-flow harness in the actual nonvisible Electron offscreen renderer. Record Electron/Chromium versions, `offscreen=true`, GPU enabled, loaded ready Mol*, source/build identity, real paint frames and loopback request evidence. Every case must have an actual outcome; failures remain in the archive. No hidden tab or separate headless renderer substitution.
3. Directly inspect corrected R03 saved-report screenshots and structured observations. Verify that captured report content is present, belongs to the intended saved result, and is not a loading frame. Complete Markdown/JSON downloads and reconcile their bytes with saved artifacts. A screenshot alone does not prove numerical correctness; preserve the existing evidence-bound report/scientific checks.
4. Archive the parent's fresh normal/OpenMM/dry-run/keyboard and any additional executed integration evidence accurately, with original file SHA-256 and byte lengths. Do not claim all 86 historical cases were freshly rerun unless they actually were. Label fixture setup and injected errors. Record zero new provider calls; the historical four-call proof is inherited evidence only.
5. A dated Astra approval must inspect the actual harness diff, fresh evidence, selected screenshots and scope statement. Bind exact reviewed files through the executor's SHA-256 review record, including the modified normal-flow harness, closure report, archive manifest/evidence relied on, roadmap and this step specification as required by the executor. Other newly authored documents needed to interpret closure must also be reviewed.
6. Explicitly supersede **only the changed `normal-flow.cjs` coverage** from the M8 review through this new extension. Old M8 application hashes and scientific/provider evidence retain their original meaning; do not rewrite old M8 review/index records to simulate a fresh original gate. Parent records this new review, runs this phase's actual `--verify`, and marks completion only after all required evidence passes.

## Completion boundary

Completion means a bounded harness race repair, real stable report capture, traceable dated integration evidence, and a clearly proposed future roadmap. Unresolved capture failure, missing current-source attribution, missing actual offscreen proof, changed unreviewed product source, or a fabricated successful observation blocks acceptance. Merging and safely removing merged branches are parent-owned Git operations, not claims made by a pending phase.
