# Integration closure and report capture review

Reviewer: GPT-6 Astra. Implementer: GPT-6 Sol. Review date: 2026-09-27. Application baseline: `ef6f2c7`; production build: `b0Od-CGKBxxBNflZsTDrG`.

## Verdict

Verdict: APPROVED

Approved for the narrow normal-flow report capture repair, dated integration evidence and proposed roadmap. No blocking finding remains. Parent must still record the SHA-bound review and execute the new integration phase acceptance and `--verify`; this review does not predeclare those results or phase completion.

## Scope and resolved finding

The original R03 assertion observed a preview before a saved-report list refresh temporarily replaced it with loading UI. Its screenshot therefore did not establish a saved preview at capture time, although later downloads matched the saved artifact. The failure of capture timing is preserved. An interim correction incorrectly required HTTP200 for creation; the actual endpoint correctly returned201. That failed run is also preserved, not counted as a final passing run.

The final harness waits for actual report creation201 and the subsequent saved-artifact read200, compares report handles, exact Markdown and both download-link handles, and rejects pending state before and after capture. It applies this condition-based check to R01 and R03. It introduces no fabricated report content, arbitrary sleep, production behavior change or new provider request. A conflicting or missing saved read fails rather than silently choosing a report. Fresh corrected normal flow completed37/37.

This extension supersedes only the old M8 review coverage for `frontend/tests/offscreen/normal-flow.cjs`. Independently recomputing all119 original M8 reviewed-file hashes found exactly that one mismatch. Application/backend source and dependency manifests remain unchanged; old scientific, egress and model integration evidence retains its historical scope. Historical M8 review/index records are not rewritten. The prior current M8 verify log records PASS for all seven specified commands and successful overall verification; it contains summary output rather than per-command test output, a disclosed evidence limitation.

## Evidence checked

The reviewer inspected the code diff, pending step/index and integration scope, closure report and roadmap. All68 files in the closure archive independently matched recorded SHA-256, byte length and original temporary-file bytes. All18 archived JSON/JSONL artifacts parsed successfully. Original historical archive73 also passed independent hash/length verification during the earlier completion audit. Archived narrow validation logs record syntax-check exit0, frontend24 passing tests and harness51 passing tests; parent still owns the formal phase recording and verify.

Fresh records contain37 final normal-flow passes,17 real OpenMM flow passes and7 dry-run passes. Keyboard evidence records actual Enter/Space selection changes in the existing run. Loaded-scene records identify Electron44.4.5/Chromium152.0.7977.130 with offscreen true, window nonvisible, GPU enabled, actual ready Mol* and paint frames. The empty host baseline alone is not used as molecular rendering evidence.

Final R01 and R03 assertions contain identical pre/post-capture report handles and Markdown hashes, pending=false and matching links. R03 has14,724 preview characters; its Markdown hash is `c866542ab0f1f4ef41a9afd88b04875b47f45db778051ceba30e388af322d56d`. Download records identify completed Electron downloads and matching saved artifact bytes. The reviewer directly viewed final `normal-final/R03.page.png`: the actual rendered molecular scene and saved SASA report preview/download links are visible. The reviewer also directly viewed `openmm/O07-minimized.page.png`: the actual structure is labeled OpenMM minimized protein, the done job shows native kJ/mol potentials, exclusions and no convergence claim. Other screenshots were integrity-checked, not all individually visually inspected.

The read-only run ledger records five local_only QA runs, zero external token/USD charges and zero outbound events. The real OpenMM job consumed one expensive attempt, completed with verified cleanup and1231 atoms; dry-run has no jobs or expensive attempts. Its native potential change is not affinity, stability or ΔΔG. No fresh provider quality claim is made; the four-call M8 integration evidence is historical and its failed third semantic response remains preserved.

## Limits and roadmap

This closure reruns selected normal/OpenMM/dry-run/keyboard controls, not every historical86 case. Error/race/provider coverage outside these reruns remains attributed to M8's historical source/build evidence. The parent drove the fresh renderer and inspected additional screenshots; this reviewer independently inspected selected raw observations and images, not a separate second full renderer run.

POST_M8_PLAN keeps every M9–M13 item proposed/pending, with acceptance criteria, dependencies and scientific limitations. Snapshots, measurements/alignment, chemical annotations, pockets and workflow assistance remain future scope. Existing geometric contacts, FreeSASA burial and restricted OpenMM potential are not relabeled as chemistry certainty or mutation ranking. This document does not authorize further live calls or expand implementation beyond the closure.

## Exact files inspected and bound for this extension

The following list is the exact extension review inventory. Archive items received integrity/raw-format validation; selected semantic records and the two specified screenshots received direct inspection as explained above. Listing an image does not claim every image was visually reviewed. Parent records these paths through the executor for exact SHA-256 binding; the phase specification is additionally bound by the executor's spec hash. Historical sources read for context retain their existing review bindings.

- `frontend/tests/offscreen/normal-flow.cjs`
- `docs/INTEGRATION_CLOSURE.md`
- `docs/POST_M8_PLAN.md`
- `docs/qa/closure-20260927/archive.json`
- `docs/qa/closure-20260927/evidence-audit.json`
- `docs/qa/closure-20260927/run-ledger.json`
- `phases/protview-integration/step0.md`
- `docs/qa/closure-20260927/raw/commands/dry-run-command.log`
- `docs/qa/closure-20260927/raw/commands/frontend-tests.log`
- `docs/qa/closure-20260927/raw/commands/harness-tests.log`
- `docs/qa/closure-20260927/raw/commands/keyboard-command.log`
- `docs/qa/closure-20260927/raw/commands/m8-current-verify.log`
- `docs/qa/closure-20260927/raw/commands/node-check.log`
- `docs/qa/closure-20260927/raw/commands/normal-command.log`
- `docs/qa/closure-20260927/raw/commands/normal-corrected-command.log`
- `docs/qa/closure-20260927/raw/commands/normal-final-command.log`
- `docs/qa/closure-20260927/raw/commands/openmm-command.log`
- `docs/qa/closure-20260927/raw/default-service/default-runs-read.json`
- `docs/qa/closure-20260927/raw/dry-run/B03-reopen.page.png`
- `docs/qa/closure-20260927/raw/dry-run/B03-submit.page.png`
- `docs/qa/closure-20260927/raw/dry-run/B03-submit.paint.png`
- `docs/qa/closure-20260927/raw/dry-run/baseline.json`
- `docs/qa/closure-20260927/raw/dry-run/dry-run.jsonl`
- `docs/qa/closure-20260927/raw/keyboard/baseline.json`
- `docs/qa/closure-20260927/raw/keyboard/history-keyboard.json`
- `docs/qa/closure-20260927/raw/keyboard/history-keyboard.page.png`
- `docs/qa/closure-20260927/raw/keyboard/history-keyboard.paint.png`
- `docs/qa/closure-20260927/raw/normal/C03.page.png`
- `docs/qa/closure-20260927/raw/normal/C03.paint.png`
- `docs/qa/closure-20260927/raw/normal/R01.page.png`
- `docs/qa/closure-20260927/raw/normal/R01.paint.png`
- `docs/qa/closure-20260927/raw/normal/R03-json.page.png`
- `docs/qa/closure-20260927/raw/normal/R03-md.page.png`
- `docs/qa/closure-20260927/raw/normal/R03.page.png`
- `docs/qa/closure-20260927/raw/normal/R03.paint.png`
- `docs/qa/closure-20260927/raw/normal/V01-surface.page.png`
- `docs/qa/closure-20260927/raw/normal/V01-surface.paint.png`
- `docs/qa/closure-20260927/raw/normal/baseline.json`
- `docs/qa/closure-20260927/raw/normal/downloads/1790462528662-20057-1-protview-report-85338ac69d2d.md`
- `docs/qa/closure-20260927/raw/normal/downloads/1790462528960-20057-2-protview-report-85338ac69d2d.json`
- `docs/qa/closure-20260927/raw/normal/downloads/1790462531527-20057-3-protview-report-4f7fa1c8f946.md`
- `docs/qa/closure-20260927/raw/normal/downloads/1790462532020-20057-4-protview-report-4f7fa1c8f946.json`
- `docs/qa/closure-20260927/raw/normal/normal-flow.jsonl`
- `docs/qa/closure-20260927/raw/normal-corrected/R01-failure.page.png`
- `docs/qa/closure-20260927/raw/normal-corrected/R01-failure.paint.png`
- `docs/qa/closure-20260927/raw/normal-corrected/baseline.json`
- `docs/qa/closure-20260927/raw/normal-corrected/normal-flow.jsonl`
- `docs/qa/closure-20260927/raw/normal-final/C03.page.png`
- `docs/qa/closure-20260927/raw/normal-final/R01.page.png`
- `docs/qa/closure-20260927/raw/normal-final/R01.paint.png`
- `docs/qa/closure-20260927/raw/normal-final/R02-json.page.png`
- `docs/qa/closure-20260927/raw/normal-final/R02-md.page.png`
- `docs/qa/closure-20260927/raw/normal-final/R03-json.page.png`
- `docs/qa/closure-20260927/raw/normal-final/R03-md.page.png`
- `docs/qa/closure-20260927/raw/normal-final/R03.page.png`
- `docs/qa/closure-20260927/raw/normal-final/R03.paint.png`
- `docs/qa/closure-20260927/raw/normal-final/V01-surface.paint.png`
- `docs/qa/closure-20260927/raw/normal-final/baseline.json`
- `docs/qa/closure-20260927/raw/normal-final/downloads/1790462716523-21921-1-protview-report-ddb317614af2.md`
- `docs/qa/closure-20260927/raw/normal-final/downloads/1790462716825-21921-2-protview-report-ddb317614af2.json`
- `docs/qa/closure-20260927/raw/normal-final/downloads/1790462719722-21921-3-protview-report-743efbe3851e.md`
- `docs/qa/closure-20260927/raw/normal-final/downloads/1790462720219-21921-4-protview-report-743efbe3851e.json`
- `docs/qa/closure-20260927/raw/normal-final/normal-flow.jsonl`
- `docs/qa/closure-20260927/raw/openmm/O06.page.png`
- `docs/qa/closure-20260927/raw/openmm/O06.paint.png`
- `docs/qa/closure-20260927/raw/openmm/O07-minimized.page.png`
- `docs/qa/closure-20260927/raw/openmm/O07-minimized.paint.png`
- `docs/qa/closure-20260927/raw/openmm/O07-original.page.png`
- `docs/qa/closure-20260927/raw/openmm/O08-create.page.png`
- `docs/qa/closure-20260927/raw/openmm/O08-json.page.png`
- `docs/qa/closure-20260927/raw/openmm/O08-md.page.png`
- `docs/qa/closure-20260927/raw/openmm/baseline.json`
- `docs/qa/closure-20260927/raw/openmm/downloads/1790462557355-20219-1-protview-report-140d54e23646.md`
- `docs/qa/closure-20260927/raw/openmm/downloads/1790462558165-20219-2-protview-report-140d54e23646.json`
- `docs/qa/closure-20260927/raw/openmm/openmm-full.jsonl`
